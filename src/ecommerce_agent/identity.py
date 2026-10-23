"""Identidad procedente exclusivamente del authorizer de API Gateway."""
import json
from .domain import Actor, AppError


def actor_from_event(event: dict) -> Actor:
    try:
        claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
        sub = claims["sub"]
        if not isinstance(sub, str) or not sub.strip() or claims.get("token_use") != "access":
            raise ValueError()
        groups = claims.get("cognito:groups", [])
        if isinstance(groups, str):
            value = groups.strip()
            if value.startswith("["):
                try:
                    groups = json.loads(value)
                except json.JSONDecodeError:
                    # API Gateway también serializa listas como [customer supervisor].
                    inner = value[1:-1] if value.endswith("]") else "!"
                    if any(ch in inner for ch in '\"\'[]{}'):
                        raise ValueError()
                    groups = inner.replace(",", " ").split()
            elif value and all(c.isalnum() or c in "_- ," for c in value):
                groups = value.replace(",", " ").split()
            else:
                raise ValueError()
        if not isinstance(groups, list) or not groups or any(
                not isinstance(g, str) or g not in {"customer", "supervisor"} for g in groups):
            raise ValueError()
        role = "supervisor" if "supervisor" in groups else "customer"
        return Actor(sub, role)
    except (KeyError, TypeError, ValueError):
        raise AppError("UNAUTHENTICATED", "Se requiere una sesión válida.", 401) from None
