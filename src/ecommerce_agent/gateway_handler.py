"""Target Lambda privado: exige contexto firmado; nunca acepta un JWT del modelo."""
import os
from .application import Service
from .domain import AppError
from .gateway import TOOL_PREFIX, ALLOWED_TOOLS, verify_context

_service = None
_kms = None


def dependencies():
    global _service, _kms
    import boto3
    from botocore.config import Config
    from .adapters import DynamoRepository
    config = Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 1})
    if _kms is None:
        _kms = boto3.client("kms", config=config)
    if _service is None:
        _service = Service(DynamoRepository(boto3.client("dynamodb", config=config),
                           os.environ["ORDERS_TABLE"], os.environ["AUDIT_TABLE"]),
                           None, int(os.environ.get("AUDIT_TTL_DAYS", "30")))
    return _service, _kms


def lambda_handler(event, context):
    try:
        custom = context.client_context.custom
        name = custom["bedrockAgentCoreToolName"]
        if not isinstance(name, str) or not name.startswith(TOOL_PREFIX):
            raise AppError("ACCESS_DENIED", "Herramienta no autorizada.", 403)
        action = name.removeprefix(TOOL_PREFIX)
        if action not in ALLOWED_TOOLS or not isinstance(event, dict) or set(event) != {"order_id", "context"}:
            raise AppError("ACCESS_DENIED", "Herramienta no autorizada.", 403)
        service, kms = dependencies()
        actor, request_id = verify_context(kms, os.environ["AGENTCORE_MAC_KEY_ID"],
                                           event["context"], action, event["order_id"])
        return service.execute(actor, action, event["order_id"], request_id)
    except AppError as exc:
        return {"ok": False, "error": exc.public()}
    except (AttributeError, KeyError, TypeError):
        return {"ok": False, "error": {"code": "ACCESS_DENIED", "message": "Contexto de herramienta no válido."}}
    except Exception:
        return {"ok": False, "error": {"code": "DEPENDENCY_UNAVAILABLE", "message": "La herramienta no está disponible."}}
