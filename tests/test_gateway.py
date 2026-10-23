"""Contexto de identidad firmado y fronteras del Gateway sin servicios remotos."""
import copy
from datetime import date
import hashlib
import hmac
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import boto3
from botocore.stub import Stubber, ANY
from ecommerce_agent.adapters import MemoryRepository, LocalPlanner
from ecommerce_agent.application import Service
from ecommerce_agent.domain import Actor, AppError, Order
from ecommerce_agent.gateway import canonical, sign_context, verify_context, GatewayExecutor, SigV4Transport, MCP_PROTOCOL_VERSION
from ecommerce_agent import gateway_handler


class FakeKms:
    def generate_mac(self, **kwargs):
        return {"Mac": hmac.new(b"test-key", kwargs["Message"], hashlib.sha256).digest()}

    def verify_mac(self, **kwargs):
        expected = self.generate_mac(**kwargs)["Mac"]
        return {"MacValid": hmac.compare_digest(expected, kwargs["Mac"])}


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.kms = FakeKms()
        self.actor = Actor("camila", "customer")
        self.envelope = sign_context(self.kms, "key", self.actor, "read_order", "P-104", "r1", now=100)

    def test_valid_context(self):
        actor, request_id = verify_context(self.kms, "key", self.envelope, "read_order", "P-104", now=101)
        self.assertEqual((actor, request_id), (self.actor, "r1"))

    def test_tampered_identity_rejected(self):
        for field, value in (("role", "supervisor"), ("sub", "diego"), ("request_id", "forged")):
            envelope = copy.deepcopy(self.envelope)
            envelope["payload"][field] = value
            with self.assertRaises(AppError):
                verify_context(self.kms, "key", envelope, "read_order", "P-104", now=101)

    def test_tool_and_resource_binding(self):
        for action, order_id in (("request_return", "P-104"), ("read_order", "P-205"), ("approve_refund", "P-104")):
            with self.assertRaises(AppError):
                verify_context(self.kms, "key", self.envelope, action, order_id, now=101)

    def test_expired_or_future_context_rejected(self):
        for now in (131, 99):
            with self.assertRaises(AppError):
                verify_context(self.kms, "key", self.envelope, "read_order", "P-104", now=now)

    def test_kms_stubber_round_trip(self):
        kms = boto3.client("kms", region_name="us-east-1", aws_access_key_id="testing", aws_secret_access_key="testing")
        mac = b"x" * 32
        with Stubber(kms) as stub:
            stub.add_response("generate_mac", {"Mac": mac, "MacAlgorithm": "HMAC_SHA_256"},
                {"KeyId": "key", "Message": ANY, "MacAlgorithm": "HMAC_SHA_256"})
            envelope = sign_context(kms, "key", self.actor, "read_order", "P-104", "r1", now=100)
            stub.add_response("verify_mac", {"MacValid": True, "MacAlgorithm": "HMAC_SHA_256"},
                {"KeyId": "key", "Message": canonical(envelope["payload"]), "Mac": mac, "MacAlgorithm": "HMAC_SHA_256"})
            self.assertEqual(verify_context(kms, "key", envelope, "read_order", "P-104", now=101)[0], self.actor)

    def test_unknown_context_fields_or_bool_expiry_rejected(self):
        for extra in ({"expires_at": True}, {"jwt": "token"}):
            envelope = copy.deepcopy(self.envelope)
            envelope["payload"].update(extra)
            with self.assertRaises(AppError):
                verify_context(self.kms, "key", envelope, "read_order", "P-104", now=101)


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.actor = Actor("camila", "customer")
        self.transport = Mock()
        self.executor = GatewayExecutor(FakeKms(), "key", "https://example.com/mcp", self.transport)

    def test_http_urls_rejected_before_signing(self):
        for url in ("http://example.com/mcp", "https://user:pass@example.com/mcp", "file:///tmp/x"):
            with self.assertRaises(ValueError):
                GatewayExecutor(FakeKms(), "key", url, self.transport)
        with self.assertRaises(AppError):
            SigV4Transport(Mock(), "us-east-1").call("http://example.com", {})

    def test_denial_uses_known_reason_and_never_arbitrary_target_text(self):
        for reason in ("RESOURCE_NOT_AUTHORIZED", "UNTRUSTED_REASON", {"invalid": True}):
            payload = {"ok": False, "error": {"code": "ACCESS_DENIED", "reason": reason, "message": "texto no confiable"}}
            self.transport.call.return_value = {"result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}
            with self.assertRaises(AppError) as error:
                self.executor.execute(self.actor, "read_order", "P-205", "r")
            self.assertNotIn("texto no confiable", error.exception.message)
            self.assertEqual(error.exception.reason, reason if reason == "RESOURCE_NOT_AUTHORIZED" else None)

    def test_no_refund_tool_can_leave_backend(self):
        with self.assertRaises(AppError):
            self.executor.execute(Actor("sofia", "supervisor"), "approve_refund", "P-104", "r")
        self.transport.call.assert_not_called()

    def test_refund_policy_errors_keep_their_code_without_untrusted_target_text(self):
        for code in ("REFUND_WINDOW_EXPIRED", "PURCHASE_DATE_UNAVAILABLE"):
            payload = {"ok": False, "error": {"code": code, "reason": "untrusted", "message": "texto no confiable"}}
            self.transport.call.return_value = {"result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}
            with self.assertRaises(AppError) as error:
                self.executor.execute(self.actor, "request_return", "P-104", "r")
            self.assertEqual((error.exception.code, error.exception.reason, error.exception.status), (code, code, 422))
            self.assertIn("90 días", error.exception.message)
            self.assertNotIn("texto no confiable", error.exception.message)

    def test_signed_gateway_target_preserves_the_refund_window_rejection(self):
        before = Order("P-206", "diego", "Producto de práctica", 19990, purchased_on="2026-06-25")
        repo = MemoryRepository([before])
        service = Service(repo, None, clock=lambda: date(2026, 10, 23))
        kms = FakeKms()

        def transport_call(url, payload):
            params = payload["params"]
            context = SimpleNamespace(client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": params["name"]}))
            result = gateway_handler.lambda_handler(params["arguments"], context)
            return {"result": {"content": [{"type": "text", "text": json.dumps(result)}]}}

        transport = Mock()
        transport.call.side_effect = transport_call
        executor = GatewayExecutor(kms, "key", "https://example.com/mcp", transport)
        with patch.object(gateway_handler, "dependencies", return_value=(service, kms)), patch.dict("os.environ", {"AGENTCORE_MAC_KEY_ID": "key"}):
            with self.assertRaises(AppError) as denied:
                executor.execute(Actor("diego", "customer"), "request_return", "P-206", "signed-rejection")
        self.assertEqual((denied.exception.code, denied.exception.status), ("REFUND_WINDOW_EXPIRED", 422))
        self.assertEqual(repo.get("P-206"), before)
        self.assertEqual(repo.events[-1]["request_id"], "signed-rejection")
        self.assertFalse(repo.events[-1]["executed"])

    def test_gateway_rejects_inconsistent_age_and_eligibility(self):
        valid = Order("P-104", "camila", "Notebook", 499990).public()
        for changes in ({"purchase_age_days": True}, {"purchase_age_days": -1},
                        {"purchase_age_days": 91, "refund_eligible": True}, {"refund_eligible": "true"},
                        {"purchased_on": "2026-02-30"}, {"purchased_on": "20261023"},
                        {"purchase_age_days": 1, "refund_eligible": True}):
            payload = {"order": {**valid, **changes}, "decision": "ALLOW"}
            self.transport.call.return_value = {"result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}
            with self.assertRaises(AppError) as error:
                self.executor.execute(self.actor, "read_order", "P-104", "r")
            self.assertEqual(error.exception.code, "GATEWAY_INVALID_RESPONSE")

    def test_gateway_result_and_private_envelope(self):
        order = Order("P-104", "camila", "Notebook", 499990).public()
        self.transport.call.return_value = {"result": {"content": [{"type": "text", "text": json.dumps({"order": order, "decision": "ALLOW"})}]}}
        result = self.executor.execute(self.actor, "read_order", "P-104", "r")
        self.assertEqual(result, {"order": order, "decision": "ALLOW"})
        payload = self.transport.call.call_args.args[1]
        self.assertEqual(payload["params"]["name"], "EcommerceTools___read_order")
        self.assertEqual(payload["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"], MCP_PROTOCOL_VERSION)
        self.assertEqual(MCP_PROTOCOL_VERSION, "2026-07-28")
        self.assertEqual(payload["params"]["_meta"]["io.modelcontextprotocol/clientCapabilities"], {})
        self.assertIn("context", payload["params"]["arguments"])
        self.assertNotIn("context", result)

    def test_transport_stateless_mcp_headers_and_timeout(self):
        from botocore.credentials import Credentials
        session = Mock()
        session.get_credentials.return_value = Credentials("testing", "testing")
        result = Mock()
        result.read.return_value = b'{"result":{}}'
        opened = Mock()
        opened.__enter__ = Mock(return_value=result)
        opened.__exit__ = Mock(return_value=None)
        opener = Mock()
        opener.open.return_value = opened
        with patch("urllib.request.build_opener", return_value=opener):
            SigV4Transport(session, "us-east-1").call("https://example.com/mcp", {"params": {"name": "EcommerceTools___read_order"}})
        request = opener.open.call_args.args[0]
        headers = {name.lower(): value for name, value in request.header_items()}
        self.assertEqual(headers["mcp-protocol-version"], "2026-07-28")
        self.assertEqual(headers["mcp-method"], "tools/call")
        self.assertEqual(headers["mcp-name"], "EcommerceTools___read_order")
        self.assertIn("authorization", headers)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 8)

    def test_gateway_failure_has_no_direct_fallback(self):
        repo = MemoryRepository([Order("P-104", "camila", "Notebook", 499990)])
        executor = Mock()
        executor.execute.side_effect = AppError("GATEWAY_UNAVAILABLE", "No disponible", 503)
        service = Service(repo, LocalPlanner(), tool_executor=executor)
        with self.assertRaises(AppError):
            service.chat(self.actor, "Solicita devolución P-104", "r")
        self.assertEqual(repo.get("P-104").return_status, "NONE")

    def test_target_denies_context_from_body_without_tool_context(self):
        result = gateway_handler.lambda_handler({"order_id": "P-104", "context": {}}, SimpleNamespace())
        self.assertEqual(result["error"]["code"], "ACCESS_DENIED")

    def test_target_authorizes_verified_actor_not_forged_body_identity(self):
        repo = MemoryRepository([Order("P-104", "camila", "Notebook", 499990), Order("P-205", "diego", "Audífonos", 39990)])
        service = Service(repo, None)
        kms = FakeKms()
        envelope = sign_context(kms, "key", self.actor, "read_order", "P-205", "r")
        context = SimpleNamespace(client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": "EcommerceTools___read_order"}))
        with patch.object(gateway_handler, "dependencies", return_value=(service, kms)), patch.dict("os.environ", {"AGENTCORE_MAC_KEY_ID": "key"}):
            result = gateway_handler.lambda_handler({"order_id": "P-205", "context": envelope}, context)
        self.assertEqual(result["error"]["code"], "ACCESS_DENIED")
        self.assertEqual(repo.events[0]["actor_sub"], "camila")


if __name__ == "__main__":
    unittest.main()
