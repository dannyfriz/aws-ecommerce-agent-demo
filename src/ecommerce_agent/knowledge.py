"""Consulta de políticas públicas con Amazon Bedrock Knowledge Bases y citas acotadas."""
import re

from .domain import AppError


class KnowledgeRetriever:
    """Devuelve extractos literales de una única fuente; nunca consulta pedidos ni decide permisos."""

    def __init__(self, client, knowledge_base_id, allowed_source_uri):
        if (not isinstance(knowledge_base_id, str) or not re.fullmatch(r"[A-Za-z0-9]{10}", knowledge_base_id)
                or not isinstance(allowed_source_uri, str)
                or not re.fullmatch(r"s3://[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]/policies/politicas-posventa-demo\.txt", allowed_source_uri)):
            raise ValueError("La base de políticas requiere un ID y una fuente S3 explícitos.")
        self.client = client
        self.knowledge_base_id = knowledge_base_id
        self.allowed_source_uri = allowed_source_uri

    def answer(self, message, detail="detailed"):
        if not isinstance(message, str) or not message.strip() or len(message) > 2000:
            raise AppError("INVALID_INPUT", "Escribe una pregunta sobre las políticas de la demo.")
        if detail not in {"brief", "detailed"}:
            raise AppError("INVALID_INPUT", "El nivel de detalle debe ser breve o detallado.")
        # Retrieve genera la búsqueda semántica; el backend no genera condiciones comerciales nuevas.
        result = self.client.retrieve(knowledgeBaseId=self.knowledge_base_id,
            retrievalQuery={"text": message},
            retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 3}})
        try:
            records = result["retrievalResults"]
            if not isinstance(records, list) or len(records) > 3:
                raise ValueError()
            extracts = []
            for record in records:
                content, location = record["content"], record["location"]
                text = content["text"]
                if (content.get("type", "TEXT") != "TEXT" or location.get("type") != "S3"
                        or location["s3Location"]["uri"] != self.allowed_source_uri
                        or not isinstance(text, str) or not text.strip() or len(text) > 6000
                        or any(ord(char) < 32 and char not in "\n\r\t" for char in text)):
                    raise ValueError()
                if text.strip() not in extracts:
                    extracts.append(text.strip())
        except (KeyError, TypeError, ValueError):
            raise AppError("KNOWLEDGE_INVALID_RESPONSE", "No pude verificar la fuente de las políticas. Intenta nuevamente.", 502) from None
        if not extracts:
            return {"message": "No encontré una respuesta en la política ficticia de esta demo. No puedo confirmar plazos ni condiciones que no estén documentados.", "sources": []}
        selected = extracts[:1] if detail == "brief" else extracts
        # Los extractos conservan su texto y sus condiciones; no se truncan a mitad de una regla.
        return {"message": "Según la política ficticia de Tienda Clara:\n\n" + "\n\n".join(selected),
                "sources": [{"title": "Políticas de posventa de Tienda Clara · Demo educativa",
                             "uri": self.allowed_source_uri}]}
