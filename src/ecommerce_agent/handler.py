"""Entrada HTTP API v2; no interpreta JWT enviados directamente por el cliente."""
import base64
import json
import logging
import os
from uuid import uuid4
from .application import Service
from .domain import AppError, Order
from .identity import actor_from_event

_service = None
logger = logging.getLogger(__name__)


def build_service():
    from .adapters import BedrockPlanner, DynamoRepository, LocalPlanner, MemoryRepository
    mode = os.environ.get("MODE", "aws")
    if mode == "local":
        return Service(MemoryRepository([Order("P-104", "camila", "Audífonos", 39990, customer_name="Camila"),
                                        Order("P-205", "diego", "Mouse", 24990, customer_name="Diego")]), LocalPlanner())
    if mode != "aws":
        raise RuntimeError("MODE debe ser aws o local")
    import boto3
    from botocore.config import Config
    data_config = Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 1})
    model_config = Config(connect_timeout=2, read_timeout=10, retries={"max_attempts": 0})
    region = os.environ.get("MODEL_REGION", os.environ.get("AWS_REGION", "us-east-1"))
    repo = DynamoRepository(boto3.client("dynamodb", config=data_config), os.environ["ORDERS_TABLE"], os.environ["AUDIT_TABLE"])
    planner = BedrockPlanner(boto3.client("bedrock-runtime", region_name=region, config=model_config), os.environ["BEDROCK_MODEL_ID"])
    gateway_url = os.environ.get("AGENTCORE_GATEWAY_URL")
    mac_key = os.environ.get("AGENTCORE_MAC_KEY_ID")
    executor = None
    if bool(gateway_url) != bool(mac_key):
        raise RuntimeError("Gateway requiere URL y clave MAC juntas")
    if gateway_url:
        from .gateway import GatewayExecutor, SigV4Transport
        executor = GatewayExecutor(boto3.client("kms", config=data_config), mac_key, gateway_url,
                                   SigV4Transport(boto3.Session(), os.environ.get("AWS_REGION", "us-east-1")))
    return Service(repo, planner, int(os.environ.get("AUDIT_TTL_DAYS", "30")), executor)


def body_from_event(event):
    raw = event.get("body") or "{}"
    try:
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw, validate=True).decode("utf-8")
        if len(raw) > 10000:
            raise ValueError()
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise AppError("INVALID_INPUT", "El cuerpo debe ser un objeto JSON válido.") from None


def response(status, value, request_id):
    return {"statusCode": status, "headers": {"content-type": "application/json; charset=utf-8",
            "cache-control": "no-store", "x-content-type-options": "nosniff"},
            "body": json.dumps({**value, "request_id": request_id}, ensure_ascii=False, default=int)}


def lambda_handler(event, context):
    global _service
    request_id = event.get("requestContext", {}).get("requestId") or str(uuid4())
    try:
        method = event.get("requestContext", {}).get("http", {}).get("method", "")
        path = event.get("rawPath", "")
        if method == "GET" and path in {"/health", "/api/health"}:
            return response(200, {"ok": True, "data": {"status": "ok"}}, request_id)
        actor = actor_from_event(event)
        if _service is None:
            _service = build_service()
        if method == "GET" and path == "/api/me":
            claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
            username = claims.get("username")
            if not isinstance(username, str) or not username.strip():
                username = actor.sub
            data = {"sub": actor.sub, "username": username, "role": actor.role}
        elif method == "GET" and path.startswith("/api/orders/"):
            data = _service.execute(actor, "read_order", path.removeprefix("/api/orders/"), request_id)
        elif method == "GET" and path == "/api/refunds/pending":
            data = _service.pending(actor, request_id, (event.get('queryStringParameters') or {}).get('after'))
        elif method == "GET" and path == "/api/audit":
            data = _service.audit(actor, request_id)
        elif method == "POST" and path == "/api/chat":
            data = _service.chat(actor, body_from_event(event).get("message"), request_id)
        elif method == "POST" and path == "/api/tools":
            body = body_from_event(event)
            action = body.get("action")
            if action not in {"read_order", "request_return"}:
                data = _service.reject(actor, "tools", "", "TOOL_NOT_ALLOWED", request_id)
            else:
                data = _service.execute(actor, action, body.get("order_id"), request_id)
        elif method == "POST" and path == "/api/orders/reset":
            body = body_from_event(event)
            data = _service.reset_order(actor, body.get("order_id"), request_id,
                                        body.get("expected_version"), body.get("confirm"))
        elif method == "POST" and path == "/api/refunds/approve":
            body = body_from_event(event)
            data = _service.execute(actor, "approve_refund", body.get("order_id"), request_id,
                                    body.get("expected_version"), body.get("confirm"))
        else:
            raise AppError("NOT_FOUND", "Ruta no disponible.", 404)
        return response(200, {"ok": True, "data": data}, request_id)
    except AppError as exc:
        return response(exc.status, {"ok": False, "error": exc.public()}, request_id)
    except Exception:
        # No registrar mensajes de excepciones de SDK que podrían contener datos de solicitudes.
        logger.error("Operación interrumpida; request_id=%s", request_id)
        return response(503, {"ok": False, "error": {"code": "DEPENDENCY_UNAVAILABLE",
                         "message": "El servicio no está disponible. No se confirmó la operación."}}, request_id)
