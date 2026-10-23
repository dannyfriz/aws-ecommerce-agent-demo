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
        for url in ("http://example.com", "https://@example.com/mcp", "https://example.com/mcp#",
                    "https://example.com/mcp#fragment", "https://[invalid"):
            with self.subTest(url=url), patch("urllib3.PoolManager") as manager:
                session = Mock()
                with self.assertRaises(AppError) as error:
                    SigV4Transport(session, "us-east-1").call(url, {})
                self.assertEqual(error.exception.code, "GATEWAY_CONFIGURATION")
                session.get_credentials.assert_not_called()
                manager.return_value.request.assert_not_called()

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
        credentials = Mock(wraps=Credentials("testing", "testing", "temporary-token"))
        session.get_credentials.return_value = credentials
        result = Mock()
        result.status = 200
        result.read.return_value = b'{"result":{}}'
        pool = Mock()
        pool.request.return_value = result
        with patch("urllib3.PoolManager", return_value=pool) as manager:
            SigV4Transport(session, "us-east-1").call("https://example.com/mcp", {"params": {"name": "EcommerceTools___read_order"}})
        manager.assert_called_once_with(num_pools=1, maxsize=1, cert_reqs="CERT_REQUIRED")
        self.assertEqual(pool.request.call_args.args, ("POST", "https://example.com/mcp"))
        options = pool.request.call_args.kwargs
        headers = {name.lower(): value for name, value in options["headers"].items()}
        self.assertEqual(headers["mcp-protocol-version"], "2026-07-28")
        self.assertEqual(headers["mcp-method"], "tools/call")
        self.assertEqual(headers["mcp-name"], "EcommerceTools___read_order")
        self.assertIn("authorization", headers)
        self.assertEqual(headers["x-amz-security-token"], "temporary-token")
        self.assertEqual(headers["accept-encoding"], "identity")
        self.assertEqual(options["timeout"].total, 8)
        for name in ("retries", "redirect", "preload_content", "decode_content"):
            self.assertIs(options[name], False)
        result.read.assert_called_once_with(65537, decode_content=False)
        result.release_conn.assert_called_once_with()
        result.close.assert_not_called()
        credentials.get_frozen_credentials.assert_called_once_with()

    def test_transport_reuses_pool_but_refreshes_signature_and_credentials(self):
        from botocore.credentials import Credentials
        session = Mock()
        first = Mock(wraps=Credentials("first-key", "testing", "first-token"))
        second = Mock(wraps=Credentials("second-key", "testing", "second-token"))
        session.get_credentials.side_effect = (first, second)
        results = [Mock(status=200), Mock(status=200)]
        for result in results:
            result.read.return_value = b'{"result":{}}'
        pool = Mock()
        pool.request.side_effect = results
        with patch("urllib3.PoolManager", return_value=pool) as manager:
            transport = SigV4Transport(session, "us-east-1")
            for action in ("read_order", "request_return"):
                transport.call("https://example.com/mcp", {"params": {"name": "EcommerceTools___" + action}})
        manager.assert_called_once()
        self.assertEqual(session.get_credentials.call_count, 2)
        self.assertEqual(pool.request.call_count, 2)
        for credentials, result, request_call, key in zip((first, second), results, pool.request.call_args_list, ("first", "second")):
            credentials.get_frozen_credentials.assert_called_once_with()
            headers = {name.lower(): value for name, value in request_call.kwargs["headers"].items()}
            self.assertIn("Credential=" + key + "-key/", headers["authorization"])
            self.assertEqual(headers["x-amz-security-token"], key + "-token")
            result.release_conn.assert_called_once_with()
            result.close.assert_not_called()

    def test_transport_closes_rejected_status_without_reading_or_retrying(self):
        from botocore.credentials import Credentials
        session = Mock()
        session.get_credentials.return_value = Credentials("testing", "testing")
        for status in (301, 302, 303, 307, 308, 400, 403, 429, 500, 503):
            with self.subTest(status=status), patch("urllib3.PoolManager") as manager:
                result = Mock(status=status)
                pool = manager.return_value
                pool.request.return_value = result
                with self.assertRaises(AppError) as error:
                    SigV4Transport(session, "us-east-1").call("https://example.com/mcp", {"params": {"name": "EcommerceTools___request_return"}})
                self.assertEqual((error.exception.code, error.exception.status), ("GATEWAY_UNAVAILABLE", 503))
                pool.request.assert_called_once()
                result.read.assert_not_called()
                result.close.assert_called_once_with()
                result.release_conn.assert_called_once_with()

    def test_transport_bounds_body_before_json_and_closes_invalid_response(self):
        from botocore.credentials import Credentials
        from urllib3.exceptions import ProtocolError
        session = Mock()
        session.get_credentials.return_value = Credentials("testing", "testing")
        failures = (b"x" * 65537, b"[1]", b"invalid", b"\xff", ProtocolError("private diagnostic"))
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), patch("urllib3.PoolManager") as manager:
                result = Mock(status=200)
                if isinstance(failure, Exception):
                    result.read.side_effect = failure
                else:
                    result.read.return_value = failure
                pool = manager.return_value
                pool.request.return_value = result
                with self.assertRaises(AppError) as error:
                    SigV4Transport(session, "us-east-1").call("https://example.com/mcp", {"params": {"name": "EcommerceTools___request_return"}})
                self.assertEqual(error.exception.code, "GATEWAY_UNAVAILABLE")
                self.assertNotIn("private diagnostic", error.exception.message)
                pool.request.assert_called_once()
                result.read.assert_called_once_with(65537, decode_content=False)
                result.close.assert_called_once_with()
                result.release_conn.assert_called_once_with()

    def test_transport_accepts_json_at_body_size_limit(self):
        from botocore.credentials import Credentials
        session = Mock()
        session.get_credentials.return_value = Credentials("testing", "testing")
        with patch("urllib3.PoolManager") as manager:
            result = Mock(status=200)
            result.read.return_value = b'{"value":"' + b"x" * (65536 - 12) + b'"}'
            self.assertEqual(len(result.read.return_value), 65536)
            manager.return_value.request.return_value = result
            value = SigV4Transport(session, "us-east-1").call("https://example.com/mcp", {"params": {"name": "EcommerceTools___read_order"}})
            self.assertEqual(len(value["value"]), 65536 - 12)
            result.close.assert_not_called()
            result.release_conn.assert_called_once_with()

    def test_transport_network_and_credential_failures_do_not_retry_or_leak_details(self):
        from botocore.credentials import Credentials
        from botocore.exceptions import CredentialRetrievalError
        from urllib3.exceptions import SSLError, ReadTimeoutError
        for failure in (SSLError("private diagnostic"), ReadTimeoutError(None, None, "private diagnostic"), OSError("private diagnostic")):
            with self.subTest(failure=type(failure).__name__), patch("urllib3.PoolManager") as manager:
                session = Mock()
                session.get_credentials.return_value = Credentials("testing", "testing")
                pool = manager.return_value
                pool.request.side_effect = failure
                with self.assertRaises(AppError) as error:
                    SigV4Transport(session, "us-east-1").call("https://example.com/mcp", {"params": {"name": "EcommerceTools___request_return"}})
                self.assertEqual((error.exception.code, error.exception.status), ("GATEWAY_UNAVAILABLE", 503))
                self.assertNotIn("private diagnostic", error.exception.message)
                pool.request.assert_called_once()
        for failure in (None, CredentialRetrievalError(provider="test", error_msg="private diagnostic")):
            with self.subTest(credentials=type(failure).__name__), patch("urllib3.PoolManager") as manager:
                session = Mock()
                if isinstance(failure, Exception):
                    session.get_credentials.side_effect = failure
                else:
                    session.get_credentials.return_value = failure
                with self.assertRaises(AppError) as error:
                    SigV4Transport(session, "us-east-1").call("https://example.com/mcp", {"params": {"name": "EcommerceTools___read_order"}})
                self.assertEqual(error.exception.code, "GATEWAY_UNAVAILABLE")
                self.assertNotIn("private diagnostic", error.exception.message)
                manager.return_value.request.assert_not_called()

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
