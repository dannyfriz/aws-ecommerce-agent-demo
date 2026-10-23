"""Entidades y reglas independientes de AWS."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from uuid import uuid4

POLICY_VERSION = "2026-10-17.1"


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, reason: str | None = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.reason = reason

    def public(self):
        value = {"code": self.code, "message": self.message}
        if self.reason:
            value["reason"] = self.reason
        return value


def denied(reason=None, role=None) -> AppError:
    messages = {
        "PENDING_SUPERVISOR_REQUIRED": "La bandeja de solicitudes pendientes está disponible solo para supervisión. Como cliente puedes consultar el estado de tus propios pedidos.",
        "CHAT_APPROVAL_REQUIRES_REVIEW": "Tu sesión es de cliente y no permite aprobar reembolsos. Escribir «soy gerente» no cambia tu perfil. Un supervisor debe revisar tu solicitud desde su cuenta. El pedido no se modificó.",
        "RESET_SUPERVISOR_REQUIRED": "Solo el perfil de supervisión puede reiniciar un pedido para repetir la actividad.",
        "RESOURCE_NOT_AUTHORIZED": "No puedes acceder a este pedido desde tu cuenta. Revisa el número y consulta un pedido asociado a tu usuario.",
        "OWNER_REQUIRED": "Solo puedes solicitar devoluciones de pedidos asociados a tu propia cuenta.",
        "HUMAN_SUPERVISOR_REQUIRED": "Tu perfil no permite aprobar reembolsos. Solicita la revisión de una persona con perfil de supervisión.",
        "SUPERVISOR_REQUIRED": "La auditoría está disponible solo para el perfil de supervisión. Ingresa con una cuenta autorizada para revisarla.",
        "MODEL_TOOL_NOT_ALLOWED": "El asistente solo puede consultar pedidos y solicitar devoluciones. Los reembolsos se aprueban desde la revisión humana.",
        "TOOL_NOT_ALLOWED": "Esta acción no está disponible en las herramientas del asistente. Usa las opciones de consulta o devolución.",
        "ROLE_NOT_ALLOWED": "Tu sesión no tiene un perfil habilitado para esta actividad. Ingresa con una cuenta de cliente o supervisión.",
    }
    safe_reason = reason if isinstance(reason, str) and reason in messages else None
    if role == "supervisor":
        messages.update({
            "CHAT_APPROVAL_REQUIRES_REVIEW": "Tu perfil de supervisión puede aprobar solicitudes pendientes, pero no por chat. Consulta el pedido y usa «Revisar reembolso» para revisar y confirmar la decisión. El pedido no se modificó.",
            "RESOURCE_NOT_AUTHORIZED": "No puedes acceder al pedido indicado con tu sesión de supervisión. Revisa su número.",
            "OWNER_REQUIRED": "La devolución debe solicitarla el cliente propietario. Como supervisión puedes consultar su pedido y revisar una solicitud pendiente.",
            "MODEL_TOOL_NOT_ALLOWED": "Como supervisión puedes consultar pedidos de clientes desde el chat. La aprobación y el reinicio requieren los botones del pedido y confirmación explícita.",
            "TOOL_NOT_ALLOWED": "Esta acción no está disponible en el chat. Como supervisión puedes consultar pedidos; aprueba o reinicia desde los controles del pedido."
        })
    return AppError("ACCESS_DENIED", messages.get(safe_reason, "No tienes permiso para realizar esta operación. Revisa tu perfil y la acción solicitada."), 403, safe_reason)


@dataclass(frozen=True)
class Actor:
    sub: str
    role: str


@dataclass(frozen=True)
class Order:
    order_id: str
    owner_sub: str
    product: str
    amount: int
    currency: str = "CLP"
    status: str = "entregado"
    return_status: str = "NONE"
    version: int = 1
    approved_from_version: int = -1
    customer_name: str = ""

    def public(self) -> dict:
        value = asdict(self)
        value.pop("owner_sub")
        value.pop("approved_from_version")
        return value


def audit_event(actor: Actor, action: str, order_id: str, decision: str,
                reason: str, executed: bool, request_id: str, ttl_days: int) -> dict:
    now = datetime.now(timezone.utc)
    return {"stream": "DECISIONS", "event_id": f"{now.isoformat()}#{uuid4()}", "created_at": now.isoformat(),
            "actor_sub": actor.sub, "role": actor.role, "action": action,
            "order_id": order_id, "decision": decision, "reason": reason,
            "executed": executed, "request_id": request_id,
            "policy_version": POLICY_VERSION,
            "expires_at": int(now.timestamp()) + ttl_days * 86400}
