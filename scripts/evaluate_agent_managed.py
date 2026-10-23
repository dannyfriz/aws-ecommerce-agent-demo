"""Evalúa trazas reales de escenarios ficticios; no exporta conversaciones de producción."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate_agent as base

SCOPE = {"name": "opentelemetry.instrumentation.tienda_clara", "version": "1"}
EVALUATORS = {"Builtin.ToolSelectionAccuracy", "Builtin.Helpfulness", "Builtin.Correctness"}
TOOLS = ["read_order", "request_return", "clarify"]


class TraceCollector:
    """Instrumentación manual de llamadas efectivas, retenida únicamente en RAM."""
    def __init__(self):
        self.sessions = {}
        self.current = None

    def start(self, operation, name, attributes=None):
        if self.current is None:
            raise RuntimeError("La captura requiere un turno activo.")
        return {"traceId": self.current["trace_id"], "spanId": uuid4().hex[:16],
                "parentSpanId": self.current["root_id"], "name": name, "kind": "INTERNAL",
                "scope": dict(SCOPE), "startTimeUnixNano": time.time_ns(),
                "attributes": {"gen_ai.operation.name": operation, "session.id": self.current["session_id"],
                               **(attributes or {})},
                "resource": {"attributes": {"service.name": "tienda-clara-evaluation-isolated"}}}

    def finish(self, span, attributes=None, failed=False):
        span["endTimeUnixNano"] = time.time_ns()
        span["durationNano"] = span["endTimeUnixNano"] - span["startTimeUnixNano"]
        span["attributes"].update(attributes or {})
        span["status"] = {"code": "ERROR" if failed else "OK"}
        self.sessions[self.current["session_id"]]["spans"].append(span)

    def begin_turn(self, actor, session_id, request_id, message):
        # El prefijo es sintético y evita mezclar dos actores que prueban el mismo UUID.
        key = hashlib.sha256(f"{actor.sub}:{session_id}".encode()).hexdigest()
        self.sessions.setdefault(key, {"case_id": request_id.removeprefix("eval-").rsplit("-", 1)[0], "spans": []})
        self.current = {"session_id": key, "trace_id": uuid4().hex, "root_id": uuid4().hex[:16]}
        root = self.start("invoke_agent", "invoke_agent TiendaClaraEvaluation", {
            "gen_ai.agent.name": "TiendaClaraEvaluation", "gen_ai.agent.tools": json.dumps(TOOLS),
            "gen_ai.task.input": message})
        root["spanId"] = self.current["root_id"]
        root.pop("parentSpanId")
        return root


def traced_service_factory(collector):
    class TracedService(base.Service):
        """Conserva las mismas reglas; solo mide el recorrido real del escenario."""
        def chat(self, actor, message, request_id, session_id=None):
            root = collector.begin_turn(actor, session_id, request_id, message)
            try:
                result = super().chat(actor, message, request_id, session_id=session_id)
                collector.finish(root, {"gen_ai.task.output": result["message"]})
                return result
            except base.AppError as exc:
                collector.finish(root, {"gen_ai.task.output": exc.message})
                raise
            except Exception:
                collector.finish(root, {"gen_ai.task.output": "DEPENDENCY_ERROR"}, failed=True)
                raise
            finally:
                collector.current = None

        def execute(self, actor, action, order_id, request_id, expected_version=None, confirm=False):
            span = collector.start("execute_tool", f"execute_tool {action}", {
                "gen_ai.tool.name": action, "gen_ai.tool.call.id": uuid4().hex,
                "gen_ai.tool.call.arguments": json.dumps({"order_id": order_id})})
            try:
                result = super().execute(actor, action, order_id, request_id, expected_version, confirm)
                collector.finish(span, {"gen_ai.tool.call.result": json.dumps(result, ensure_ascii=False)})
                return result
            except base.AppError as exc:
                collector.finish(span, {"gen_ai.tool.call.result": json.dumps(exc.public(), ensure_ascii=False)})
                raise
            except Exception:
                collector.finish(span, {"gen_ai.tool.call.result": "DEPENDENCY_ERROR"}, failed=True)
                raise
    return TracedService


class TracedRuntimeClient:
    """Captura la inferencia efectivamente ejecutada sobre el dataset ficticio."""
    def __init__(self, client, collector):
        self.client, self.collector = client, collector

    def converse(self, **kwargs):
        span = self.collector.start("chat", "chat", {
            "gen_ai.input.messages": json.dumps(kwargs.get("messages", []), ensure_ascii=False),
            "gen_ai.system_instructions": "\n".join(block["text"] for block in kwargs.get("system", [])),
            "gen_ai.request.model": kwargs["modelId"],
            "gen_ai.agent.tools": json.dumps(kwargs.get("toolConfig", {}).get("tools", []), ensure_ascii=False)})
        try:
            response = self.client.converse(**kwargs)
            self.collector.finish(span, {"gen_ai.output.messages": json.dumps(
                [response.get("output", {}).get("message", {})], ensure_ascii=False)})
            return response
        except Exception:
            self.collector.finish(span, {"gen_ai.output.messages": "DEPENDENCY_ERROR"}, failed=True)
            raise


def score_sessions(client, collector, evaluator, threshold):
    """Exporta solo métricas; rechaza respuestas vacías, errores y valores no finitos."""
    results, skipped = [], []
    for session in collector.sessions.values():
        spans = session["spans"]
        if evaluator == "Builtin.ToolSelectionAccuracy" and not any(
                span["attributes"]["gen_ai.operation.name"] == "execute_tool" for span in spans):
            skipped.append({"case_id": session["case_id"], "reason": "NO_TOOL_CALLS"})
            continue
        try:
            response = client.evaluate(evaluatorId=evaluator, evaluationInput={"sessionSpans": spans})
            entries = response.get("evaluationResults", [])
            if not isinstance(entries, list) or not entries:
                raise ValueError("La evaluación no produjo resultados.")
            for entry in entries:
                value = entry.get("value")
                valid = (not entry.get("errorCode") and type(value) in {int, float}
                         and math.isfinite(value) and 0 <= value <= 1)
                results.append({"case_id": session["case_id"], "evaluator": evaluator,
                                "status": "scored" if valid else "evaluation_error",
                                "score": value if valid else None,
                                "passed": valid and value >= threshold})
        except Exception:
            results.append({"case_id": session["case_id"], "evaluator": evaluator,
                            "status": "evaluation_error", "score": None, "passed": False})
    return results, skipped


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="default")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--model-id")
    parser.add_argument("--compute-outputs")
    parser.add_argument("--output", default=str(base.ROOT / ".build/agent-managed-evaluation-results.json"))
    parser.add_argument("--evaluator", choices=sorted(EVALUATORS), default="Builtin.ToolSelectionAccuracy")
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--case-id", action="append", help="Limita la evaluación a casos del dataset ficticio versionado.")
    args = parser.parse_args(argv)
    try:
        if not math.isfinite(args.threshold) or not 0 <= args.threshold <= 1:
            raise ValueError("Umbral inválido.")
        cases = base.load_cases()
        if args.case_id:
            if not set(args.case_id) <= {case["case_id"] for case in cases}:
                raise ValueError("Caso desconocido.")
            cases = [case for case in cases if case["case_id"] in args.case_id]
        collector = TraceCollector()
        factory = base.live_planner_factory(args.profile, args.region, args.model_id, args.compute_outputs,
                                             client_wrapper=lambda client: TracedRuntimeClient(client, collector))
        regression = base.run_evaluations(cases, planner_factory=factory,
                                          service_factory=traced_service_factory(collector))
        import boto3
        from botocore.config import Config
        client = boto3.Session(profile_name=args.profile, region_name=args.region).client(
            "bedrock-agentcore", config=Config(connect_timeout=10, read_timeout=180,
                                              retries={"max_attempts": 2, "mode": "standard"}))
        results, skipped = score_sessions(client, collector, args.evaluator, args.threshold)
        report = {"mode": "agentcore_managed_isolated", "passed": regression["passed"] and bool(results)
                  and all(result["passed"] for result in results), "regression": regression,
                  "managed": results, "skipped": skipped, "threshold": args.threshold}
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["passed"] else 1
    except Exception:
        print(json.dumps({"passed": False, "status": "configuration_error"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
