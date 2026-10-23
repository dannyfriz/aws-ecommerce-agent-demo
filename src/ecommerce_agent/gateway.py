"""AgentCore Gateway con identidad vinculada criptográficamente a cada herramienta."""
import base64
from datetime import date
import json
import time
from urllib.parse import urlparse
from urllib.request import Request
from uuid import uuid4
from .domain import Actor, AppError, REFUND_WINDOW_DAYS, denied, refund_policy_error

ALLOWED_TOOLS = {"read_order", "request_return"}
TOOL_PREFIX = "EcommerceTools___"
MCP_PROTOCOL_VERSION = "2026-07-28"
CONTEXT_FIELDS = {"sub", "role", "action", "order_id", "request_id", "expires_at", "nonce"}


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_context(kms, key_id: str, actor: Actor, action: str, order_id: str,
                 request_id: str, now: int | None = None) -> dict:
    if action not in ALLOWED_TOOLS:
        raise denied()
    payload = {"sub": actor.sub, "role": actor.role, "action": action,
               "order_id": order_id, "request_id": request_id,
               "expires_at": (int(time.time()) if now is None else now) + 30,
               "nonce": str(uuid4())}
    result = kms.generate_mac(KeyId=key_id, Message=canonical(payload), MacAlgorithm="HMAC_SHA_256")
    return {"payload": payload, "mac": base64.b64encode(result["Mac"]).decode("ascii")}


def verify_context(kms, key_id: str, envelope: dict, action: str, order_id: str,
                   now: int | None = None) -> tuple[Actor, str]:
    from botocore.exceptions import ClientError
    try:
        if action not in ALLOWED_TOOLS or not isinstance(envelope, dict) or set(envelope) != {"payload", "mac"}:
            raise ValueError()
        payload = envelope["payload"]
        if not isinstance(payload, dict) or set(payload) != CONTEXT_FIELDS:
            raise ValueError()
        if any(not isinstance(payload[name], str) or not 1 <= len(payload[name]) <= 128
               for name in CONTEXT_FIELDS - {"expires_at"}):
            raise ValueError()
        if payload["action"] != action or payload["order_id"] != order_id or payload["role"] not in {"customer", "supervisor"}:
            raise ValueError()
        current = int(time.time()) if now is None else now
        if type(payload["expires_at"]) is not int or not current <= payload["expires_at"] <= current + 30:
            raise ValueError()
        if not isinstance(envelope["mac"], str) or len(envelope["mac"]) > 128:
            raise ValueError()
        mac = base64.b64decode(envelope["mac"], validate=True)
        if len(mac) != 32:
            raise ValueError()
        result = kms.verify_mac(KeyId=key_id, Message=canonical(payload),
                                Mac=mac, MacAlgorithm="HMAC_SHA_256")
        if result.get("MacValid") is not True:
            raise ValueError()
        return Actor(payload["sub"], payload["role"]), payload["request_id"]
    except (ValueError, TypeError, KeyError, ClientError):
        raise denied() from None


class SigV4Transport:
    """Transporte MCP acotado; nunca sigue redirecciones con credenciales firmadas."""
    def __init__(self, session, region: str):
        self.session, self.region = session, region

    def call(self, url: str, payload: dict) -> dict:
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        from urllib.request import HTTPRedirectHandler, build_opener
        from urllib.error import HTTPError, URLError

        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise AppError("GATEWAY_CONFIGURATION", "La URL de Gateway debe usar HTTPS.", 503)
        data = canonical(payload)
        credentials = self.session.get_credentials()
        if credentials is None:
            raise AppError("GATEWAY_UNAVAILABLE", "Gateway no está disponible.", 503)
        request = AWSRequest(method="POST", url=url, data=data,
                             headers={"Content-Type": "application/json", "Accept": "application/json",
                                      "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
                                      "Mcp-Method": "tools/call", "Mcp-Name": payload["params"]["name"]})
        SigV4Auth(credentials.get_frozen_credentials(), "bedrock-agentcore", self.region).add_auth(request)
        try:
            with build_opener(NoRedirect()).open(Request(url, data=data, headers=dict(request.headers), method="POST"), timeout=8) as result:
                raw = result.read(65537)
                if len(raw) > 65536:
                    raise ValueError()
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError()
                return value
        except (HTTPError, URLError, TimeoutError, ValueError, UnicodeError):
            raise AppError("GATEWAY_UNAVAILABLE", "Gateway no pudo confirmar la operación.", 503) from None


class GatewayExecutor:
    def __init__(self, kms, key_id: str, url: str, transport: SigV4Transport):
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("AGENTCORE_GATEWAY_URL debe usar HTTPS sin credenciales")
        self.kms, self.key_id, self.url, self.transport = kms, key_id, url, transport

    def execute(self, actor: Actor, action: str, order_id: str, request_id: str) -> dict:
        if action not in ALLOWED_TOOLS:
            raise denied()
        envelope = sign_context(self.kms, self.key_id, actor, action, order_id, request_id)
        result = self.transport.call(self.url, {"jsonrpc": "2.0", "id": str(uuid4()),
            "method": "tools/call", "params": {"name": TOOL_PREFIX + action,
                "arguments": {"order_id": order_id, "context": envelope},
                "_meta": {"io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
                          "io.modelcontextprotocol/clientInfo": {"name": "ecommerce-identity-lab", "version": "0.1.0"},
                          "io.modelcontextprotocol/clientCapabilities": {}}}})
        try:
            if "error" in result or result["result"].get("isError"):
                raise ValueError()
            content = result["result"]["content"]
            if not isinstance(content, list) or len(content) != 1 or content[0].get("type") != "text":
                raise ValueError()
            value = json.loads(content[0]["text"])
            if not isinstance(value, dict):
                raise ValueError()
            if value.get("ok") is False:
                error = value.get("error")
                if not isinstance(error, dict):
                    raise ValueError()
                if error.get("code") == "ACCESS_DENIED":
                    raise denied(error.get("reason"), actor.role)
                if error.get("code") in {"REFUND_WINDOW_EXPIRED", "PURCHASE_DATE_UNAVAILABLE"}:
                    # Reconstruir el texto controlado; nunca reenviar un mensaje libre del target.
                    raise refund_policy_error(error["code"])
                raise AppError("GATEWAY_UNAVAILABLE", "La herramienta no pudo confirmar la operación.", 503)
            # Solo aceptar los datos contractuales del target, nunca texto libre de MCP.
            if value.get("decision") != "ALLOW" or not isinstance(value.get("order"), dict):
                raise ValueError()
            order = value["order"]
            expected = {"order_id", "product", "amount", "currency", "status", "return_status", "version", "customer_name",
                        "purchased_on", "purchase_age_days", "refund_eligible"}
            if set(order) != expected or order["order_id"] != order_id:
                raise ValueError()
            if not isinstance(order["customer_name"], str) or len(order["customer_name"]) > 120:
                raise ValueError()
            age = order["purchase_age_days"]
            if (not isinstance(order["purchased_on"], str) or len(order["purchased_on"]) > 10
                    or (age is not None and (type(age) is not int or age < 0))
                    or type(order["refund_eligible"]) is not bool
                    or order["refund_eligible"] != (age is not None and age <= REFUND_WINDOW_DAYS)):
                raise ValueError()
            if order["purchased_on"]:
                if date.fromisoformat(order["purchased_on"]).isoformat() != order["purchased_on"]:
                    raise ValueError()
            elif age is not None:
                raise ValueError()
            return {name: value[name] for name in ("order", "decision", "executed") if name in value}
        except (KeyError, TypeError, ValueError):
            raise AppError("GATEWAY_INVALID_RESPONSE", "Gateway entregó una respuesta no válida.", 502) from None
