"""Evalúa el agente con pedidos ficticios sin conectarse a su infraestructura de datos."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ecommerce_agent.adapters import BedrockPlanner, LocalPlanner, MemoryRepository
from ecommerce_agent.application import Service
from ecommerce_agent.domain import Actor, AppError, Order
from ecommerce_agent.conversation_memory import LocalConversationMemory

DEFAULT_CASES = ROOT / "scripts/fixtures/agent-evaluation-cases.json"
METRICS = {"understanding", "action_selection", "clarification", "context", "authorization"}
ACTORS = {"camila": Actor("evaluation-camila", "customer"),
          "diego": Actor("evaluation-diego", "customer"),
          "sofia": Actor("evaluation-sofia", "supervisor")}
ACTIONS = {"read_order", "request_return", "clarify", "none"}


class RecordingPlanner:
    """Conserva solamente la propuesta normalizada para comprobar la selección."""
    def __init__(self, planner):
        self.planner = planner
        self.last = None

    def plan(self, message, context=None):
        proposals = self.planner.plan(message, context=context)
        if isinstance(proposals, list) and len(proposals) == 1 and isinstance(proposals[0], dict):
            self.last = proposals[0]
        return proposals


def load_cases(path=DEFAULT_CASES):
    """Rechaza datasets vacíos o sin expectativas para evitar falsos aprobados."""
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if data.get("version") != 1 or not isinstance(data.get("cases"), list) or not data["cases"]:
        raise ValueError("Dataset de evaluación inválido.")
    ids = set()
    allowed = {"status", "action", "order_id", "reason", "error_code", "return_status", "review_order_id", "mutated"}
    for case in data["cases"]:
        case_id = case.get("case_id", "")
        if not re.fullmatch(r"[a-z0-9_]{1,80}", case_id) or case_id in ids:
            raise ValueError("Identificador de caso inválido o repetido.")
        ids.add(case_id)
        if not case.get("metrics") or not set(case["metrics"]) <= METRICS or not case.get("steps"):
            raise ValueError("Cada caso requiere métricas y pasos.")
        for step in case["steps"]:
            expected = step.get("expect", {})
            if (step.get("actor", "camila") not in ACTORS or not isinstance(step.get("message"), str)
                    or not step["message"].strip() or not {"status", "action"} <= expected.keys()
                    or not expected.keys() <= allowed or expected["action"] not in ACTIONS
                    or expected["status"] not in {"ok", "clarification", "denied", "error"}):
                raise ValueError("Paso de evaluación inválido.")
            for key in ("order_id", "review_order_id"):
                if key in expected and expected[key] is not None and not re.fullmatch(r"P-[A-Z0-9_-]{1,60}", expected[key]):
                    raise ValueError("Referencia ficticia inválida.")
            for key in ("reason", "error_code"):
                if key in expected and expected[key] is not None and not re.fullmatch(r"[A-Z_]{1,80}", expected[key]):
                    raise ValueError("Categoría de evaluación inválida.")
            if "mutated" in expected and type(expected["mutated"]) is not bool:
                raise ValueError("La expectativa de mutación debe ser booleana.")
            if "return_status" in expected and expected["return_status"] not in {"NONE", "REQUESTED"}:
                raise ValueError("Estado esperado inválido.")
    return data["cases"]


def observe(service, repo, planner, step, session_id, request_id):
    """Ejecuta un turno; ni mensajes ni respuestas libres salen en el resultado."""
    before = dict(repo.orders)
    planner.last = None
    response = {}
    observed = {"status": "ok", "action": "none", "error_code": None, "reason": None,
                "order_id": None, "return_status": None, "review_order_id": None}
    try:
        response = service.chat(ACTORS[step.get("actor", "camila")], step["message"], request_id,
                                session_id=session_id)
        if response.get("clarification"):
            observed.update(status="clarification", action="clarify",
                            reason=response["clarification"].get("reason"))
        else:
            result = (response.get("results") or [{}])[0]
            order = result.get("order", {})
            observed.update(order_id=order.get("order_id"), return_status=order.get("return_status"),
                            review_order_id=response.get("review_order_id"))
            observed["action"] = (planner.last or {}).get("action", "read_order" if order else "none")
    except AppError as exc:
        observed.update(status="denied" if exc.status == 403 else "error", error_code=exc.code,
                        reason=exc.reason)
        observed["action"] = (planner.last or {}).get("action", "none")
    except Exception:
        # Los detalles de proveedores pueden contener entrada libre; no se exportan.
        observed.update(status="error", error_code="DEPENDENCY_ERROR")
    observed["mutated"] = before != repo.orders
    observed["safe"] = (all(order.return_status != "REFUNDED" for order in repo.orders.values())
                        and not any(event.get("action") == "approve_refund" and event.get("executed")
                                    for event in repo.events))
    return observed


def run_evaluations(cases, planner_factory=LocalPlanner, memory_factory=LocalConversationMemory,
                    service_factory=Service):
    """Separa cada escenario y calcula tasas; cualquier desvío hace fallar la suite."""
    results = []
    counts = defaultdict(lambda: {"passed": 0, "total": 0})
    for case in cases:
        requested = case.get("initial_return_status", "NONE")
        if requested not in {"NONE", "REQUESTED"}:
            raise ValueError("Estado inicial de evaluación inválido.")
        repo = MemoryRepository([Order("P-104", ACTORS["camila"].sub, "Producto ficticio A", 39990,
                                       return_status=requested, customer_name="Camila"),
                                 Order("P-205", ACTORS["diego"].sub, "Producto ficticio B", 19990,
                                       customer_name="Diego")])
        planner = RecordingPlanner(planner_factory())
        service = service_factory(repo, planner, conversation_memory=memory_factory())
        sessions = {}
        steps = []
        for index, step in enumerate(case["steps"]):
            session_id = sessions.setdefault(step.get("session", "a"), str(uuid4()))
            request_id = f"eval-{case['case_id']}-{index + 1}"
            observed = observe(service, repo, planner, step, session_id, request_id)
            checks = {key: observed.get(key) == value for key, value in step["expect"].items()}
            checks["no_chat_approval"] = observed["safe"]
            action = observed["action"] if observed["action"] in ACTIONS else "invalid"
            steps.append({"request_id": request_id, "expectation": dict(step["expect"]),
                          "normalized_action": action, "status": observed["status"],
                          "passed": all(checks.values()), "checks": checks})
        passed = all(step["passed"] for step in steps)
        results.append({"case_id": case["case_id"], "passed": passed, "steps": steps})
        for metric in set(case["metrics"]):
            counts[metric]["total"] += 1
            counts[metric]["passed"] += int(passed)
    metrics = {metric: {**values, "rate": round(values["passed"] / values["total"], 4)}
               for metric, values in sorted(counts.items())}
    return {"passed": bool(results) and all(result["passed"] for result in results),
            "cases_passed": sum(result["passed"] for result in results), "cases_total": len(results),
            "metrics": metrics, "results": results}


def live_planner_factory(profile, region, model_id=None, outputs=None, client_wrapper=None):
    """El único cliente AWS permitido es Bedrock Runtime; los pedidos siguen siendo locales."""
    if model_id is None:
        values = json.loads(Path(outputs or ROOT / ".build/outputs/compute.json").read_text(encoding="utf-8-sig"))
        model_id = values["bedrock_application_profile_arn"]["value"]
    if not re.fullmatch(rf"arn:aws:bedrock:{re.escape(region)}:[0-9]{{12}}:application-inference-profile/[A-Za-z0-9_-]+", model_id):
        raise ValueError("La evaluación real requiere un perfil de aplicación Bedrock de la región seleccionada.")
    import boto3
    from botocore.config import Config
    client = boto3.Session(profile_name=profile, region_name=region).client(
        "bedrock-runtime", config=Config(connect_timeout=10, read_timeout=60,
                                        retries={"max_attempts": 2, "mode": "standard"}))
    if client_wrapper:
        client = client_wrapper(client)
    return lambda: BedrockPlanner(client, model_id, enable_policy_knowledge=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--output", default=str(ROOT / ".build/agent-evaluation-results.json"))
    parser.add_argument("--live", action="store_true", help="Usa Bedrock real con datos ficticios locales; genera costo de inferencia.")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--model-id", help="ARN del perfil de aplicación, nunca el endpoint de la API del laboratorio.")
    parser.add_argument("--compute-outputs")
    args = parser.parse_args(argv)
    try:
        cases = load_cases(args.cases)
        factory = live_planner_factory(args.profile, args.region, args.model_id, args.compute_outputs) if args.live else LocalPlanner
        report = run_evaluations(cases, planner_factory=factory)
        report["mode"] = "bedrock_isolated" if args.live else "local_regression"
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
