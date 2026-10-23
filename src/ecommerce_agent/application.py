"""Casos de uso: autorización externa al modelo y aprobación humana."""
import re
import unicodedata
from dataclasses import replace
from .domain import Actor, AppError, audit_event, denied
from .ports import Repository, Planner, ToolExecutor


def requests_chat_approval(message: str) -> bool:
    text = ''.join(char for char in unicodedata.normalize('NFKD', message.casefold()) if not unicodedata.combining(char))
    verbs = r'(?:aprueba(?:me|lo|la)?|apruebes|aprobar|autoriza(?:me|lo|la)?|autorices|autorizar)'
    # Esta detección prepara una revisión; nunca concede permisos ni aprueba reembolsos.
    return (bool(re.search(r'\breembolsos?\b', text) and re.search(rf'\b{verbs}\b', text))
            and not re.search(rf'\b(?:no|sin|nunca)\s+{verbs}\b', text))


class Service:
    def __init__(self, repo: Repository, planner: Planner | None, ttl_days: int = 30,
                 tool_executor: ToolExecutor | None = None):
        self.repo, self.planner, self.ttl_days = repo, planner, ttl_days
        self.tool_executor = tool_executor

    def event(self, actor, action, order_id, decision, reason, executed, request_id):
        return audit_event(actor, action, order_id, decision, reason, executed, request_id, self.ttl_days)

    def reject(self, actor, action, order_id, reason, request_id):
        self.repo.record(self.event(actor, action, order_id, "DENY", reason, False, request_id))
        raise denied(reason, actor.role)

    def execute(self, actor: Actor, action: str, order_id: str, request_id: str,
                expected_version=None, confirm=False) -> dict:
        if actor.role not in {"customer", "supervisor"}:
            return self.reject(actor, "unknown_role", "", "ROLE_NOT_ALLOWED", request_id)
        if action not in {"read_order", "request_return", "approve_refund"}:
            return self.reject(actor, "unknown_tool", "", "TOOL_NOT_ALLOWED", request_id)
        if not isinstance(order_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", order_id):
            raise AppError("INVALID_INPUT", "El identificador del pedido no es válido.")
        if action == "approve_refund" and actor.role != "supervisor":
            return self.reject(actor, action, order_id, "HUMAN_SUPERVISOR_REQUIRED", request_id)
        order = self.repo.get(order_id)
        if order is None or (actor.role != "supervisor" and order.owner_sub != actor.sub):
            return self.reject(actor, action, order_id, "RESOURCE_NOT_AUTHORIZED", request_id)
        if action == "read_order":
            self.repo.record(self.event(actor, action, order_id, "ALLOW", "AUTHORIZED", True, request_id))
            return {"order": order.public(), "decision": "ALLOW"}
        if action == "request_return":
            if order.owner_sub != actor.sub:
                return self.reject(actor, action, order_id, "OWNER_REQUIRED", request_id)
            if order.return_status != "NONE":
                self.repo.record(self.event(actor, action, order_id, "ALLOW", "ALREADY_REQUESTED", False, request_id))
                return {"order": order.public(), "decision": "ALLOW", "executed": False}
            after = replace(order, return_status="REQUESTED", version=order.version + 1)
        else:
            if confirm is not True or type(expected_version) is not int or expected_version < 1:
                self.repo.record(self.event(actor, action, order_id, "DENY", "INVALID_CONFIRMATION", False, request_id))
                raise AppError("INVALID_CONFIRMATION", "Confirma el pedido y su versión antes de aprobar.")
            if order.return_status == "REFUNDED" and order.approved_from_version == expected_version:
                self.repo.record(self.event(actor, action, order_id, "ALLOW", "ALREADY_APPROVED", False, request_id))
                return {"order": order.public(), "decision": "ALLOW", "executed": False}
            if order.version != expected_version or order.return_status != "REQUESTED":
                self.repo.record(self.event(actor, action, order_id, "DENY", "STALE_OR_INVALID_STATE", False, request_id))
                raise AppError("CONFLICT", "El pedido cambió. Revisa su estado y vuelve a confirmar.", 409)
            after = replace(order, return_status="REFUNDED", version=order.version + 1,
                            approved_from_version=expected_version)
        event = self.event(actor, action, order_id, "ALLOW", "AUTHORIZED", True, request_id)
        try:
            self.repo.mutate(order, after, event)
        except AppError as exc:
            if exc.status == 409:
                self.repo.record(self.event(actor, action, order_id, "DENY", "CONCURRENT_CHANGE", False, request_id))
            raise
        return {"order": after.public(), "decision": "ALLOW", "executed": True}

    def reset_order(self, actor: Actor, order_id: str, request_id: str,
                    expected_version=None, confirm=False) -> dict:
        if actor.role != "supervisor":
            return self.reject(actor, "reset_order", "", "RESET_SUPERVISOR_REQUIRED", request_id)
        if not isinstance(order_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", order_id):
            raise AppError("INVALID_INPUT", "El identificador del pedido no es válido.")
        if confirm is not True or type(expected_version) is not int or expected_version < 1:
            self.repo.record(self.event(actor, "reset_order", order_id, "DENY", "INVALID_CONFIRMATION", False, request_id))
            raise AppError("INVALID_CONFIRMATION", "Confirma el pedido y su versión antes de reiniciar la actividad.")
        before = self.repo.get(order_id)
        if before is None:
            return self.reject(actor, "reset_order", order_id, "RESOURCE_NOT_AUTHORIZED", request_id)
        if before.version != expected_version:
            raise AppError("CONFLICT", "El pedido cambió. Consúltalo y confirma nuevamente el reinicio.", 409)
        if before.return_status == "NONE":
            self.repo.record(self.event(actor, "reset_order", order_id, "ALLOW", "ALREADY_RESET", False, request_id))
            return {"order": before.public(), "decision": "ALLOW", "executed": False, "action": "reset_order"}
        # Incrementar la versión invalida aprobaciones antiguas; nunca se borra la auditoría.
        after = replace(before, return_status="NONE", approved_from_version=-1, version=before.version + 1)
        self.repo.mutate(before, after, self.event(actor, "reset_order", order_id, "ALLOW", "LAB_RESET", True, request_id))
        return {"order": after.public(), "decision": "ALLOW", "executed": True, "action": "reset_order"}

    def chat(self, actor: Actor, message: str, request_id: str) -> dict:
        if not isinstance(message, str) or not message.strip() or len(message) > 2000:
            raise AppError("INVALID_INPUT", "Escribe una consulta de hasta 2.000 caracteres.")
        if actor.role not in {"customer", "supervisor"}:
            return self.reject(actor, "chat", "", "ROLE_NOT_ALLOWED", request_id)
        if requests_chat_approval(message):
            if actor.role != "supervisor":
                return self.reject(actor, "chat", "", "CHAT_APPROVAL_REQUIRES_REVIEW", request_id)
            identifiers = set(re.findall(r'\bP-[A-Za-z0-9_-]+\b', message, re.IGNORECASE))
            if len(identifiers) != 1:
                raise AppError("INVALID_INPUT", "Indica un único número de pedido, por ejemplo P-104, para preparar la revisión del reembolso.")
            result = self.execute(actor, "read_order", identifiers.pop().upper(), request_id)
            order = result["order"]
            pending = order["return_status"] == "REQUESTED"
            reference = f"el pedido {order['order_id']} del cliente {order.get('customer_name') or 'sin nombre registrado'}"
            explanation = ("La solicitud está pendiente. Usa «Revisar reembolso» para comprobar los datos y confirmar tu decisión. Todavía no se aprobó el reembolso."
                           if pending else "El reembolso ya está aprobado en la demo; no realicé cambios."
                           if order["return_status"] == "REFUNDED" else
                           "No hay una solicitud de devolución pendiente. Primero debe enviarla el cliente propietario.")
            return {"message": f"Como supervisor, puedes revisar {reference}. {explanation}",
                    "results": [result], "review_order_id": order["order_id"] if pending else None}
        try:
            proposals = self.planner.plan(message)
        except AppError:
            self.repo.record(self.event(actor, "chat", "", "DENY", "MODEL_INVALID_RESPONSE", False, request_id))
            raise
        if not isinstance(proposals, list) or len(proposals) != 1:
            self.repo.record(self.event(actor, "chat", "", "DENY", "MODEL_INVALID_RESPONSE", False, request_id))
            raise AppError("MODEL_INVALID_RESPONSE", "No se pudo interpretar una acción segura.", 502)
        # Validar todo antes de ejecutar evita un efecto parcial por una herramienta inventada.
        for proposal in proposals:
            if not isinstance(proposal, dict) or set(proposal) != {"action", "order_id"} or proposal["action"] not in {"read_order", "request_return"}:
                return self.reject(actor, "chat", "", "MODEL_TOOL_NOT_ALLOWED", request_id)
        executor = self.tool_executor if self.tool_executor is not None else self
        results = [executor.execute(actor, p["action"], p["order_id"], request_id) for p in proposals]
        result = results[0]
        order = result["order"]
        reference = (f"el pedido {order['order_id']} del cliente {order['customer_name']}"
                     if actor.role == "supervisor" and order.get("customer_name") else
                     f"el pedido {order['order_id']} de un cliente" if actor.role == "supervisor" else
                     f"tu pedido {order['order_id']}")
        if proposals[0]["action"] == "read_order":
            states = {"NONE": "sin devolución solicitada", "REQUESTED": "solicitud enviada, en espera de supervisión",
                      "REFUNDED": "reembolso aprobado en la demo"}
            message = f"Consulté {reference}. Estado: {order['status']}. Devolución: {states.get(order['return_status'], order['return_status'])}."
            if actor.role == "supervisor":
                message += " Estás consultando como supervisión; el pedido pertenece al cliente."
                if order["return_status"] == "REQUESTED":
                    message += " Puedes revisar la solicitud con «Revisar reembolso» y confirmar allí tu decisión."
                elif order["return_status"] == "NONE":
                    message += " No hay un reembolso pendiente de aprobación. La devolución debe solicitarla el propietario."
                elif order["return_status"] == "REFUNDED":
                    message += " La revisión de este cliente ya finalizó. Para repetir la actividad puedes usar «Reiniciar pedido (demo)»; se conservará la auditoría."
            elif order["return_status"] == "NONE":
                message += " Puedes solicitar su devolución; la aprobación del reembolso requiere supervisión humana."
            elif order["return_status"] == "REQUESTED":
                message += " Tu solicitud está enviada y espera la revisión de un supervisor. No necesitas enviarla nuevamente."
            elif order["return_status"] == "REFUNDED":
                message += " Supervisión ya autorizó tu reembolso en esta demo; no se transfieren fondos reales. Si deseas repetir la actividad, solicita a supervisión el reinicio del pedido."
        elif result.get("executed"):
            message = f"Solicitud de devolución de {reference} enviada a revisión. Está en espera de un supervisor para evaluar el reembolso. El reembolso aún no está aprobado."
        elif order["return_status"] == "REFUNDED":
            message = f"El reembolso de {reference} ya estaba aprobado en la demo. No se realizó otro cambio."
        else:
            message = f"La solicitud de devolución de {reference} ya estaba enviada y sigue en espera de un supervisor. No se duplicó la solicitud ni se aprobó el reembolso."
        return {"message": message, "results": results}

    def pending(self, actor: Actor, request_id: str, after=None):
        if actor.role != 'supervisor':
            return self.reject(actor, 'pending:read', '', 'PENDING_SUPERVISOR_REQUIRED', request_id)
        if after is not None and (not isinstance(after, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', after)):
            raise AppError('INVALID_INPUT', 'El cursor de solicitudes no es válido. Vuelve a la primera página.')
        orders, next_after = self.repo.pending(after=after, limit=25)
        self.repo.record(self.event(actor, 'pending:read', '', 'ALLOW', 'AUTHORIZED', True, request_id))
        return {'orders':[order.public() for order in orders], 'next_after':next_after}

    def audit(self, actor: Actor, request_id: str):
        if actor.role != "supervisor":
            return self.reject(actor, "audit:read", "", "SUPERVISOR_REQUIRED", request_id)
        self.repo.record(self.event(actor, "audit:read", "", "ALLOW", "AUTHORIZED", True, request_id))
        return {"events": self.repo.audit()}
