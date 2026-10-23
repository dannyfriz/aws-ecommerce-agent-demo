"""Contexto mínimo de conversación; nunca contiene decisiones de autorización."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
import time
from uuid import UUID, uuid4

from botocore.exceptions import BotoCoreError, ClientError

from .domain import AppError


@dataclass(frozen=True)
class ConversationContext:
    """Referencia recordada; el servidor debe volver a autorizar cada uso."""

    order_id: str | None
    pending_action: str | None
    expires_at: int


def validate_session_id(session_id: str) -> str:
    """Acepta únicamente UUIDv4 canónico; la sesión no acredita identidad."""
    try:
        value = UUID(session_id) if isinstance(session_id, str) else None
        if value is None or value.version != 4 or str(value) != session_id:
            raise ValueError()
    except (ValueError, AttributeError):
        raise AppError("INVALID_SESSION", "La conversación no es válida. Inicia una conversación nueva.", 400) from None
    return session_id


def memory_actor_id(actor_sub: str, environment: str) -> str:
    """Deriva el identificador desde el sub verificado, sin persistirlo en claro."""
    if not isinstance(actor_sub, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", actor_sub):
        raise AppError("INVALID_SESSION", "No se pudo identificar la conversación de tu sesión.", 400)
    if environment not in {"demo", "dev", "test"}:
        raise ValueError("El ambiente de memoria debe ser demo, dev o test")
    return f"{environment}-{hashlib.sha256(actor_sub.encode('utf-8')).hexdigest()}"


def _validate_context(order_id, pending_action):
    if order_id is not None and (not isinstance(order_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", order_id)):
        raise ValueError("El contexto requiere un identificador de pedido válido")
    if pending_action is not None and (not isinstance(pending_action, str) or pending_action not in {"read_order", "request_return"}):
        raise ValueError("El contexto no admite esa acción")


def _unavailable():
    return AppError("MEMORY_UNAVAILABLE", "No se pudo recuperar o guardar el contexto de la conversación. Intenta nuevamente.", 503)


class LocalConversationMemory:
    """Adaptador local para pruebas; no reemplaza la memoria administrada en AWS."""

    def __init__(self, environment="test", ttl_seconds=900, clock=time.time):
        if type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 1800:
            raise ValueError("La vigencia del contexto debe estar entre 60 y 1800 segundos")
        memory_actor_id("validation", environment)
        self.environment, self.ttl_seconds, self.clock = environment, ttl_seconds, clock
        self._contexts = {}

    def _key(self, actor_sub, session_id):
        return memory_actor_id(actor_sub, self.environment), validate_session_id(session_id)

    def get(self, actor_sub: str, session_id: str) -> ConversationContext | None:
        context = self._contexts.get(self._key(actor_sub, session_id))
        return context if context and context.expires_at > int(self.clock()) else None

    def remember(self, actor_sub: str, session_id: str, order_id: str | None,
                 pending_action: str | None = None) -> None:
        """El llamador guarda un pedido solo después de comprobar su acceso."""
        key = self._key(actor_sub, session_id)
        _validate_context(order_id, pending_action)
        self._contexts[key] = ConversationContext(order_id, pending_action, int(self.clock()) + self.ttl_seconds)


class AgentCoreConversationMemory(LocalConversationMemory):
    """Eventos acotados por actor y sesión, sin prompts ni extracción de largo plazo."""

    MAX_PAGES = 5
    PAGE_SIZE = 100

    def __init__(self, client, memory_id: str, environment: str, ttl_seconds=900, clock=time.time):
        super().__init__(environment, ttl_seconds, clock)
        if not isinstance(memory_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,99}-[A-Za-z0-9]{10}", memory_id):
            raise ValueError("AGENTCORE_MEMORY_ID debe identificar la memoria configurada")
        self.client, self.memory_id = client, memory_id

    def _validate_event_header(self, event, actor_id, session_id, now):
        """Valida la identidad y metadatos, incluso cuando CreateEvent no repite el payload."""
        if not isinstance(event, dict) or any(event.get(key) != value for key, value in
                (("memoryId", self.memory_id), ("actorId", actor_id), ("sessionId", session_id))):
            raise ValueError("El evento no corresponde a la conversación solicitada")
        timestamp = event.get("eventTimestamp")
        event_id = event.get("eventId")
        if (not isinstance(timestamp, datetime) or timestamp.tzinfo is None or timestamp.utcoffset() is None or
                timestamp.timestamp() > now + 5 or not isinstance(event_id, str) or
                not re.fullmatch(r"[0-9]+#[a-fA-F0-9]+", event_id)):
            raise ValueError("El evento no tiene una fecha o identificador válido")
        return timestamp.timestamp(), event_id

    def _decode_event(self, event, actor_id, session_id, now):
        timestamp, event_id = self._validate_event_header(event, actor_id, session_id, now)
        payload = event.get("payload")
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict) or set(payload[0]) != {"blob"}:
            raise ValueError("La memoria solo admite el contexto mínimo")
        blob = payload[0]["blob"]
        if isinstance(blob, str):
            if len(blob) > 512:
                raise ValueError("El contexto serializado excede el límite")
            blob = json.loads(blob)
        if not isinstance(blob, dict) or set(blob) != {"schema_version", "order_id", "pending_action", "expires_at"}:
            raise ValueError("El contexto contiene campos no admitidos")
        if type(blob["schema_version"]) is not int or blob["schema_version"] != 1:
            raise ValueError("La versión del contexto no es válida")
        _validate_context(blob["order_id"], blob["pending_action"])
        expiry = blob["expires_at"]
        if (type(expiry) is not int or not int(timestamp) < expiry <= int(timestamp) + self.ttl_seconds):
            raise ValueError("La vigencia del contexto no es válida")
        return timestamp, event_id, ConversationContext(blob["order_id"], blob["pending_action"], expiry)

    def get(self, actor_sub: str, session_id: str) -> ConversationContext | None:
        actor_id, session_id = self._key(actor_sub, session_id)
        now, latest, next_token, seen_tokens = self.clock(), None, None, set()
        try:
            for _ in range(self.MAX_PAGES):
                params = {"memoryId": self.memory_id, "actorId": actor_id, "sessionId": session_id,
                          "includePayloads": True, "maxResults": self.PAGE_SIZE}
                if next_token:
                    params["nextToken"] = next_token
                response = self.client.list_events(**params)
                if not isinstance(response, dict):
                    raise ValueError("La respuesta de memoria no es válida")
                events = response.get("events")
                if not isinstance(events, list) or len(events) > self.PAGE_SIZE:
                    raise ValueError("La respuesta de memoria no es válida")
                for event in events:
                    candidate = self._decode_event(event, actor_id, session_id, now)
                    if latest and candidate[0] == latest[0] and candidate[2] != latest[2]:
                        raise ValueError("La memoria contiene contextos simultáneos ambiguos")
                    if latest is None or candidate[:2] > latest[:2]:
                        latest = candidate
                next_token = response.get("nextToken")
                if not next_token:
                    context = latest[2] if latest else None
                    return context if context and context.expires_at > int(now) else None
                if not isinstance(next_token, str) or len(next_token) > 2048 or next_token in seen_tokens:
                    raise ValueError("La paginación de memoria no es válida")
                seen_tokens.add(next_token)
            raise ValueError("La conversación excede el límite de recuperación")
        except (BotoCoreError, ClientError, KeyError, TypeError, ValueError, OverflowError):
            raise _unavailable() from None


    def remember(self, actor_sub: str, session_id: str, order_id: str | None,
                 pending_action: str | None = None) -> None:
        """Persiste solo una referencia validada o una marca vacía para reiniciar."""
        actor_id, session_id = self._key(actor_sub, session_id)
        _validate_context(order_id, pending_action)
        now = self.clock()
        context = ConversationContext(order_id, pending_action, int(now) + self.ttl_seconds)
        blob = {"schema_version": 1, **asdict(context)}
        try:
            # El servicio conserva una cadena JSON; un objeto Document puede normalizarse como un mapa no JSON.
            serialized = json.dumps(blob, sort_keys=True, separators=(",", ":"))
            response = self.client.create_event(memoryId=self.memory_id, actorId=actor_id, sessionId=session_id,
                eventTimestamp=datetime.fromtimestamp(now, timezone.utc), payload=[{"blob": serialized}],
                extractionMode="SKIP", clientToken=str(uuid4()))
            if not isinstance(response, dict):
                raise ValueError("La respuesta de memoria no es válida")
            acknowledged = response.get("event")
            self._validate_event_header(acknowledged, actor_id, session_id, now)
            # CreateEvent confirma con metadatos; si también devuelve contenido, se valida completo.
            if "payload" in acknowledged:
                _, _, written = self._decode_event(acknowledged, actor_id, session_id, now)
                if written != context:
                    raise ValueError("La memoria no confirmó el contexto guardado")
        except (BotoCoreError, ClientError, KeyError, TypeError, ValueError, OverflowError):
            raise _unavailable() from None


PREFERENCE_RETENTION_DAYS = 31
DEFAULT_PREFERENCES = {"preferred_detail": "brief", "language": "es"}


def _preference_detail(detail):
    if not isinstance(detail, str) or detail not in {"brief", "detailed"}:
        raise AppError("INVALID_PREFERENCES", "Elige respuestas breves o detalladas.", 400)
    return detail


def _preferences_unavailable():
    return AppError("PREFERENCES_UNAVAILABLE", "No se pudieron recuperar o guardar tus preferencias. Intenta nuevamente.", 503)


def _preferences_pending():
    return AppError("PREFERENCES_PENDING", "La escritura de tu preferencia fue aceptada, pero todavía no pudimos confirmar que el nuevo valor esté disponible. Espera unos segundos y vuelve a consultar tus preferencias.", 503)


class LocalPreferenceMemory:
    """Preferencias elegidas explícitamente; no se infieren de las conversaciones."""

    def __init__(self, environment="test", clock=time.time):
        memory_actor_id("validation", environment)
        self.environment, self.clock, self._preferences = environment, clock, {}

    def get_preferences(self, actor_sub: str) -> dict:
        stored = self._preferences.get(memory_actor_id(actor_sub, self.environment))
        if stored and stored[1] > int(self.clock()):
            return dict(stored[0])
        return dict(DEFAULT_PREFERENCES)

    def save_preferences(self, actor_sub: str, detail: str) -> dict:
        key = memory_actor_id(actor_sub, self.environment)
        value = {"preferred_detail": _preference_detail(detail), "language": "es"}
        self._preferences[key] = value, int(self.clock()) + PREFERENCE_RETENTION_DAYS * 86400
        return dict(value)


class AgentCorePreferenceMemory(LocalPreferenceMemory):
    """Registros tipados de largo plazo escritos directamente, sin extracción de prompts."""

    MAX_PAGES = 3
    MAX_CONFIRMATION_ATTEMPTS = 8
    CONFIRMATION_TIMEOUT_SECONDS = 2.0
    CONFIRMATION_INTERVAL_SECONDS = 0.2

    def __init__(self, client, memory_id: str, environment: str, clock=time.time,
                 monotonic=time.monotonic, sleeper=time.sleep):
        super().__init__(environment, clock)
        if not isinstance(memory_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,99}-[A-Za-z0-9]{10}", memory_id):
            raise ValueError("AGENTCORE_PREFERENCES_MEMORY_ID debe identificar la memoria configurada")
        self.client, self.memory_id = client, memory_id
        self.monotonic, self.sleeper = monotonic, sleeper

    def _namespace(self, actor_sub):
        return f"/preferences/{memory_actor_id(actor_sub, self.environment)}/"

    def _record_identity(self, record, namespace, expected_id=None):
        if not isinstance(record, dict) or record.get("namespaces") != [namespace]:
            raise ValueError("La preferencia no pertenece a este usuario")
        record_id = record.get("memoryRecordId")
        if not isinstance(record_id, str) or not re.fullmatch(r"mem-[A-Za-z0-9_-]{36,46}", record_id):
            raise ValueError("El registro de preferencias no es válido")
        if expected_id is not None and record_id != expected_id:
            raise ValueError("La memoria devolvió otro registro")
        return record_id

    def _read_record(self, record_id, namespace):
        """Lee por ID el contenido vigente: el resumen de List puede conservar un valor anterior."""
        response = self.client.get_memory_record(memoryId=self.memory_id, memoryRecordId=record_id, namespace=namespace)
        if not isinstance(response, dict):
            raise ValueError("La respuesta de preferencias no es válida")
        record = response.get("memoryRecord")
        self._record_identity(record, namespace, expected_id=record_id)
        content = record.get("content")
        if not isinstance(content, dict) or set(content) != {"text"} or not isinstance(content["text"], str) or len(content["text"]) > 512:
            raise ValueError("La preferencia no contiene datos admitidos")
        value = json.loads(content["text"])
        if (not isinstance(value, dict) or set(value) != {"schema_version", "preferred_detail", "language", "updated_at", "expires_at"}
                or type(value["schema_version"]) is not int or value["schema_version"] != 1
                or value["language"] != "es" or type(value["updated_at"]) is not int
                or type(value["expires_at"]) is not int):
            raise ValueError("El esquema de preferencias no es válido")
        detail = value["preferred_detail"]
        if not isinstance(detail, str) or detail not in {"brief", "detailed"}:
            raise ValueError("El estilo de respuesta no es válido")
        updated = value["updated_at"] / 1000000
        if not 0 <= updated <= self.clock() + 5 or not int(updated) < value["expires_at"] <= int(updated) + PREFERENCE_RETENTION_DAYS * 86400:
            raise ValueError("La vigencia de la preferencia no es válida")
        return record_id, value

    def _record_ids(self, actor_sub):
        """Descubre IDs dentro del namespace exacto; nunca interpreta contenido del índice eventual."""
        namespace = self._namespace(actor_sub)
        record_ids, next_token, seen_tokens = [], None, set()
        for _ in range(self.MAX_PAGES):
            params = {"memoryId": self.memory_id, "namespace": namespace, "maxResults": 100}
            if next_token:
                params["nextToken"] = next_token
            response = self.client.list_memory_records(**params)
            if not isinstance(response, dict) or not isinstance(response.get("memoryRecordSummaries"), list):
                raise ValueError("La respuesta de preferencias no es válida")
            records = response["memoryRecordSummaries"]
            if len(records) > 100:
                raise ValueError("La respuesta de preferencias excede el límite")
            for record in records:
                record_id = self._record_identity(record, namespace)
                if record_id not in record_ids:
                    record_ids.append(record_id)
                if len(record_ids) > 20:
                    raise ValueError("Las preferencias exceden el límite de registros por usuario")
            next_token = response.get("nextToken")
            if not next_token:
                return record_ids
            if not isinstance(next_token, str) or len(next_token) > 2048 or next_token in seen_tokens:
                raise ValueError("La paginación de preferencias no es válida")
            seen_tokens.add(next_token)
        raise ValueError("Las preferencias exceden el límite de recuperación")

    def _record(self, actor_sub):
        namespace, latest = self._namespace(actor_sub), None
        for record_id in self._record_ids(actor_sub):
            candidate = self._read_record(record_id, namespace)
            value = candidate[1]
            if latest and value["updated_at"] == latest[1]["updated_at"] and value != latest[1]:
                raise ValueError("Las preferencias simultáneas son ambiguas")
            if latest is None or value["updated_at"] > latest[1]["updated_at"]:
                latest = candidate
        return latest

    def get_preferences(self, actor_sub: str) -> dict:
        self._namespace(actor_sub)
        try:
            stored = self._record(actor_sub)
            if stored and stored[1]["expires_at"] > int(self.clock()):
                return {key: stored[1][key] for key in DEFAULT_PREFERENCES}
            return dict(DEFAULT_PREFERENCES)
        except (BotoCoreError, ClientError, KeyError, TypeError, ValueError, OverflowError):
            raise _preferences_unavailable() from None

    def _confirm_preferences(self, actor_sub, record_id, value):
        """Espera una lectura visible del valor confirmado, sin repetir la escritura ni usar caché."""
        deadline = self.monotonic() + self.CONFIRMATION_TIMEOUT_SECONDS
        for attempt in range(self.MAX_CONFIRMATION_ATTEMPTS):
            stored = self._read_record(record_id, self._namespace(actor_sub))
            # La primera creación también debe ser descubrible en otra sesión sin un ID en caché.
            if stored[1] == value and record_id in self._record_ids(actor_sub):
                return
            remaining = deadline - self.monotonic()
            if remaining <= 0 or attempt + 1 == self.MAX_CONFIRMATION_ATTEMPTS:
                raise _preferences_pending()
            self.sleeper(min(self.CONFIRMATION_INTERVAL_SECONDS, remaining))

    def save_preferences(self, actor_sub: str, detail: str) -> dict:
        namespace, detail = self._namespace(actor_sub), _preference_detail(detail)
        try:
            stored, now = self._record(actor_sub), self.clock()
            preferences = {"preferred_detail": detail, "language": "es"}
            value = {"schema_version": 1, **preferences, "updated_at": int(now * 1000000),
                     "expires_at": int(now) + PREFERENCE_RETENTION_DAYS * 86400}
            record = {"content": {"text": json.dumps(value, sort_keys=True, separators=(",", ":"))},
                      "namespaces": [namespace], "timestamp": datetime.fromtimestamp(now, timezone.utc)}
            params = {"memoryId": self.memory_id, "recordExpirySpecification": {"recordExpiryDurationDays": PREFERENCE_RETENTION_DAYS}}
            if stored:
                record.update({"memoryRecordId": stored[0], "sourceNamespaces": [namespace]})
                response = self.client.batch_update_memory_records(**params, records=[record])
            else:
                record["requestIdentifier"] = "preferences"
                response = self.client.batch_create_memory_records(**params, records=[record], clientToken=str(uuid4()))
            if not isinstance(response, dict) or response.get("failedRecords"):
                raise ValueError("La memoria rechazó la preferencia")
            successful = response.get("successfulRecords")
            if not isinstance(successful, list) or len(successful) != 1 or not isinstance(successful[0], dict):
                raise ValueError("La memoria no confirmó la preferencia")
            result = successful[0]
            if result.get("status") != "SUCCEEDED" or not isinstance(result.get("memoryRecordId"), str):
                raise ValueError("La memoria no confirmó el resultado")
            if stored and result["memoryRecordId"] != stored[0]:
                raise ValueError("La memoria confirmó otro registro")
            if not stored and result.get("requestIdentifier") != "preferences":
                raise ValueError("La memoria confirmó otra solicitud")
            self._confirm_preferences(actor_sub, result["memoryRecordId"], value)
            return preferences
        except (BotoCoreError, ClientError, KeyError, TypeError, ValueError, OverflowError):
            raise _preferences_unavailable() from None
