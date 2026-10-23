"""Filtro de contenido independiente de los permisos y las reglas del pedido."""
from .domain import AppError


class BedrockContentGuard:
    def __init__(self, client, guardrail_id, version):
        self.client, self.guardrail_id, self.version = client, guardrail_id, version

    def check(self, text, source="INPUT"):
        if source not in {"INPUT", "OUTPUT"} or not isinstance(text, str) or not text.strip():
            raise ValueError("El contenido del filtro no es válido")
        result = self.client.apply_guardrail(
            guardrailIdentifier=self.guardrail_id, guardrailVersion=self.version,
            source=source, content=[{"text": {"text": text}}])
        if result.get("action") == "GUARDRAIL_INTERVENED":
            raise AppError("CONTENT_BLOCKED", "El filtro de seguridad bloqueó contenido sensible o instrucciones no permitidas. Reformula tu consulta sin contraseñas ni datos sensibles. No se ejecutó ninguna acción sobre un pedido.", 422,
                           "GUARDRAIL_BLOCKED")
        if result.get("action") != "NONE":
            raise AppError("DEPENDENCY_UNAVAILABLE", "No se pudo comprobar el contenido. No se ejecutó la solicitud.", 503)
