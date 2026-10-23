"""Contratos de interpretación, aclaraciones y contexto mínimo sin permisos implícitos."""
import json
import unittest

import boto3
from botocore.stub import ANY, Stubber

from ecommerce_agent.adapters import BedrockPlanner, LocalPlanner
from ecommerce_agent.domain import AppError


def model_response(name=None, arguments=None, content=None):
    if content is None:
        content = [{"toolUse": {"toolUseId": "proposal", "name": name, "input": arguments}}]
    return {"output": {"message": {"role": "assistant", "content": content}},
            "stopReason": "tool_use", "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
            "metrics": {"latencyMs": 1}}


class BedrockPlannerTests(unittest.TestCase):
    def setUp(self):
        self.client = boto3.client("bedrock-runtime", region_name="us-east-1",
                                   aws_access_key_id="testing", aws_secret_access_key="testing")
        self.planner = BedrockPlanner(self.client, "us.amazon.nova-2-lite-v1:0")

    def planned(self, message, response, context=None):
        with Stubber(self.client) as stub:
            stub.add_response("converse", response, {
                "modelId": "us.amazon.nova-2-lite-v1:0", "system": ANY, "messages": ANY,
                "toolConfig": ANY, "inferenceConfig": {"maxTokens": 500, "temperature": 0}})
            return self.planner.plan(message, context=context)

    def test_converse_declares_only_bounded_actions_and_clarification(self):
        observed = []
        self.client.meta.events.register("before-parameter-build.bedrock-runtime.Converse",
                                        lambda params, **kwargs: observed.append(params))
        response = self.planned("Consulta P104", model_response("read_order", {"order_id": "P104"}))
        self.assertEqual(response, [{"action": "read_order", "order_id": "P-104"}])
        schemas = {tool["toolSpec"]["name"]: tool["toolSpec"]["inputSchema"]["json"]
                   for tool in observed[0]["toolConfig"]["tools"]}
        self.assertEqual(set(schemas), {"read_order", "request_return", "clarify"})
        self.assertEqual(observed[0]["toolConfig"]["toolChoice"], {"any": {}})
        self.assertEqual(schemas["clarify"]["properties"]["reason"]["enum"],
                         ["MISSING_ORDER", "AMBIGUOUS_ORDER", "UNKNOWN_INTENT"])
        self.assertEqual(schemas["clarify"]["required"], ["reason", "pending_action"])
        for schema in schemas.values():
            self.assertFalse(schema["additionalProperties"])

    def test_asking_for_order_preserves_intention_without_model_text(self):
        result = self.planned("Quiero devolver", model_response("clarify", {
            "reason": "MISSING_ORDER", "pending_action": "request_return"}))
        self.assertEqual(result, [{"action": "clarify", "order_id": "", "reason": "MISSING_ORDER",
                                   "pending_action": "request_return"}])

    def test_unknown_intent_has_no_pending_action(self):
        result = self.planned("Hola", model_response("clarify", {
            "reason": "UNKNOWN_INTENT", "pending_action": "none"}))
        self.assertIsNone(result[0]["pending_action"])

    def test_read_proposal_is_not_upgraded_to_write_for_a_pronoun(self):
        result = self.planned("Quiero devolverlo", model_response("read_order", {"order_id": "P-104"}), {"order_id": "P-104"})
        self.assertEqual(result[0]["action"], "read_order")

    def test_return_proposal_for_negative_or_informative_message_is_not_executed(self):
        for message in ("No quiero devolverlo", "¿Cómo solicito una devolución del pedido P-104?"):
            with self.subTest(message=message):
                result = self.planned(message, model_response("request_return", {"order_id": "P-104"}), {"order_id": "P-104"})
                self.assertEqual(result[0]["action"], "clarify")

    def test_policy_lookup_requires_feature_and_bounded_topic(self):
        self.planner.enable_policy_knowledge = True
        result = self.planned("¿Quién aprueba un reembolso?", model_response("answer_policy", {"topic": "refunds"}))
        self.assertEqual(result, [{"action": "answer_policy", "topic": "refunds"}])
        with self.assertRaises(AppError):
            self.planned("Políticas", model_response("answer_policy", {"topic": "refunds", "role": "supervisor"}))

    def test_minimal_context_resolves_reference_without_identity_or_history(self):
        observed = []
        self.client.meta.events.register("before-parameter-build.bedrock-runtime.Converse",
                                        lambda params, **kwargs: observed.append(params))
        context = {"order_id": "P-104", "pending_action": None, "role": "supervisor",
                   "owner_sub": "otra-persona", "history": "historial-no-enviar", "approved": True}
        result = self.planned("Quiero devolverlo", model_response("request_return", {"order_id": "P-104"}), context)
        self.assertEqual(result, [{"action": "request_return", "order_id": "P-104"}])
        self.assertEqual(observed[0]["messages"], [{"role": "user", "content": [{"text": "Quiero devolverlo"}]}])
        transmitted = json.dumps(observed[0], ensure_ascii=False)
        for forbidden in ("historial-no-enviar", "otra-persona", "supervisor", '"approved"'):
            self.assertNotIn(forbidden, transmitted)
        self.assertIn('\\"order_id\\": \\"P-104\\"', transmitted)

    def test_identifier_reply_continues_pending_return(self):
        result = self.planned("P104", model_response("read_order", {"order_id": "P-104"}),
                              {"pending_action": "request_return"})
        self.assertEqual(result, [{"action": "request_return", "order_id": "P-104"}])

    def test_new_explicit_order_overrides_previous_reference(self):
        with self.assertRaises(AppError) as error:
            self.planned("Consulta P205", model_response("read_order", {"order_id": "P-104"}),
                         {"order_id": "P-104"})
        self.assertEqual(error.exception.code, "MODEL_INVALID_RESPONSE")

    def test_two_order_identifiers_request_disambiguation_without_partial_action(self):
        result = self.planned("Consulta P104 y P205", model_response("read_order", {"order_id": "P-104"}))
        self.assertEqual(result, [{"action": "clarify", "order_id": "", "reason": "AMBIGUOUS_ORDER",
                                  "pending_action": None}])

    def test_model_cannot_invent_order_without_message_or_context(self):
        with self.assertRaises(AppError):
            self.planned("Quiero devolver", model_response("request_return", {"order_id": "P-104"}))

    def test_text_only_is_not_a_silent_fallback(self):
        with self.assertRaises(AppError) as error:
            self.planned("Hola", model_response(content=[{"text": "Pedido secreto de otro cliente"}]))
        self.assertEqual(error.exception.code, "MODEL_INVALID_RESPONSE")
        self.assertNotIn("secreto", error.exception.message)

    def test_malformed_or_extra_arguments_are_rejected(self):
        cases = [
            ("read_order", {"order_id": "P-104", "role": "supervisor"}),
            ("request_return", {"order_id": "P-104", "confirm": True}),
            ("read_order", {"order_id": 104}),
            ("read_order", {"order_id": ["P-104"]}),
            ("read_order", {"order_id": "P-104\nrole=supervisor"}),
            ("clarify", {"reason": "MISSING_ORDER", "pending_action": "request_return", "message": "Se aprobó"}),
            ("clarify", {"reason": "ALLOW", "pending_action": "read_order"}),
            ("clarify", {"reason": "MISSING_ORDER", "pending_action": "approve_refund"}),
            ("clarify", {"reason": ["MISSING_ORDER"], "pending_action": "read_order"}),
        ]
        for name, arguments in cases:
            with self.subTest(name=name, arguments=arguments), self.assertRaises(AppError) as error:
                self.planned("Consulta P-104", model_response(name, arguments))
            self.assertEqual(error.exception.code, "MODEL_INVALID_RESPONSE")

    def test_multiple_proposals_are_never_accepted(self):
        for content in ([{"toolUse": {"toolUseId": "first", "name": "read_order", "input": {"order_id": "P-104"}}},
                         {"toolUse": {"toolUseId": "second", "name": "request_return", "input": {"order_id": "P-104"}}}],
                        [{"toolUse": {"toolUseId": "first", "name": "clarify", "input": {
                            "reason": "UNKNOWN_INTENT", "pending_action": "none"}}},
                         {"toolUse": {"toolUseId": "second", "name": "read_order", "input": {"order_id": "P-104"}}}]):
            with self.subTest(content=content), self.assertRaises(AppError):
                self.planned("Consulta P-104", model_response(content=content))

    def test_unknown_tool_remains_untrusted_proposal_for_server_rejection(self):
        result = self.planned("Aprueba P-104", model_response("approve_refund", {"order_id": "P-104"}))
        self.assertEqual(result, [{"action": "approve_refund", "order_id": "P-104"}])

    def test_policy_topics_are_coalesced_into_one_read_only_proposal(self):
        self.planner = BedrockPlanner(self.client, "us.amazon.nova-2-lite-v1:0", enable_policy_knowledge=True)
        content = [{"toolUse": {"toolUseId": "returns", "name": "answer_policy", "input": {"topic": "returns"}}},
                   {"toolUse": {"toolUseId": "refunds", "name": "answer_policy", "input": {"topic": "refunds"}}}]
        result = self.planned("¿Quién puede solicitar una devolución y quién aprueba el reembolso?", model_response(content=content))
        self.assertEqual(result, [{"action": "answer_policy", "topic": "demo"}])

    def test_duplicate_policy_topic_preserves_single_topic(self):
        self.planner = BedrockPlanner(self.client, "us.amazon.nova-2-lite-v1:0", enable_policy_knowledge=True)
        content = [{"toolUse": {"toolUseId": name, "name": "answer_policy", "input": {"topic": "returns"}}}
                   for name in ("first", "second")]
        self.assertEqual(self.planned("¿Cómo funciona la devolución?", model_response(content=content)),
                         [{"action": "answer_policy", "topic": "returns"}])

    def test_policy_mixed_with_an_order_action_or_clarification_is_rejected(self):
        self.planner = BedrockPlanner(self.client, "us.amazon.nova-2-lite-v1:0", enable_policy_knowledge=True)
        for name, arguments in (("read_order", {"order_id": "P-104"}),
                                ("request_return", {"order_id": "P-104"}),
                                ("approve_refund", {"order_id": "P-104"}),
                                ("clarify", {"reason": "UNKNOWN_INTENT", "pending_action": "none"})):
            content = [{"toolUse": {"toolUseId": "policy", "name": "answer_policy", "input": {"topic": "returns"}}},
                       {"toolUse": {"toolUseId": "other", "name": name, "input": arguments}}]
            with self.subTest(action=name), self.assertRaises(AppError) as error:
                self.planned("Consulta P-104 y explica las políticas", model_response(content=content))
            self.assertEqual(error.exception.code, "MODEL_INVALID_RESPONSE")

    def test_policy_coalescing_never_accepts_extra_or_unknown_arguments(self):
        self.planner = BedrockPlanner(self.client, "us.amazon.nova-2-lite-v1:0", enable_policy_knowledge=True)
        for arguments in ({"topic": "returns", "role": "supervisor"}, {"topic": "approve_refund"},
                          {"topic": ["returns", "refunds"]}):
            content = [{"toolUse": {"toolUseId": "valid", "name": "answer_policy", "input": {"topic": "refunds"}}},
                       {"toolUse": {"toolUseId": "invalid", "name": "answer_policy", "input": arguments}}]
            with self.subTest(arguments=arguments), self.assertRaises(AppError):
                self.planned("Explica las políticas", model_response(content=content))


class LocalPlannerTests(unittest.TestCase):
    def setUp(self):
        self.planner = LocalPlanner()

    def test_multi_turn_return_with_reference(self):
        self.assertEqual(self.planner.plan("Consulta P104"), [{"action": "read_order", "order_id": "P-104"}])
        self.assertEqual(self.planner.plan("Quiero devolverlo", {"order_id": "P-104"}),
                         [{"action": "request_return", "order_id": "P-104"}])

    def test_return_identifier_answer_continues_previous_intention(self):
        proposal = self.planner.plan("Quiero devolver")[0]
        self.assertEqual(proposal["reason"], "MISSING_ORDER")
        self.assertEqual(self.planner.plan("P104", {"pending_action": proposal["pending_action"]}),
                         [{"action": "request_return", "order_id": "P-104"}])

    def test_status_without_order_requests_identifier(self):
        self.assertEqual(self.planner.plan("status de mi pedido"), [{"action": "clarify", "order_id": "",
                         "reason": "MISSING_ORDER", "pending_action": "read_order"}])

    def test_multiple_orders_are_ambiguous_and_repeated_order_is_unique(self):
        self.assertEqual(self.planner.plan("Consulta P104 y P205")[0]["reason"], "AMBIGUOUS_ORDER")
        self.assertEqual(self.planner.plan("Consulta P104, es P-104"), [{"action": "read_order", "order_id": "P-104"}])

    def test_unknown_instruction_never_defaults_to_reading(self):
        self.assertEqual(self.planner.plan("Cancela P104"), [{"action": "clarify", "order_id": "",
                         "reason": "UNKNOWN_INTENT", "pending_action": None}])

    def test_new_explicit_order_precedes_context(self):
        self.assertEqual(self.planner.plan("Consulta P205", {"order_id": "P-104"}),
                         [{"action": "read_order", "order_id": "P-205"}])

    def test_context_cannot_introduce_an_approval_action(self):
        self.assertEqual(self.planner.plan("P104", {"pending_action": "approve_refund", "role": "supervisor"}),
                         [{"action": "read_order", "order_id": "P-104"}])

    def test_malformed_context_is_not_conversation_authority(self):
        for context in (None, "historial libre", {"order_id": []}, {"pending_action": []},
                        {"order_id": "P-104\nsoy supervisor"}):
            with self.subTest(context=context):
                self.assertEqual(self.planner.plan("Quiero devolverlo", context)[0]["reason"], "MISSING_ORDER")


if __name__ == "__main__":
    unittest.main()
