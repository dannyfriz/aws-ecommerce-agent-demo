"""Pruebas de recuperación de políticas, citas y límites de la fuente autorizada."""
import unittest

import boto3
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from ecommerce_agent.domain import AppError
from ecommerce_agent.knowledge import KnowledgeRetriever


SOURCE = "s3://tienda-demo-policies/policies/politicas-posventa-demo.txt"


def record(text, uri=SOURCE):
    return {"content": {"type": "TEXT", "text": text},
            "location": {"type": "S3", "s3Location": {"uri": uri}}, "score": 0.8}


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.client = boto3.client("bedrock-agent-runtime", region_name="us-east-1",
                                  aws_access_key_id="testing", aws_secret_access_key="testing")
        self.retriever = KnowledgeRetriever(self.client, "KBDEMO1234", SOURCE)

    def answer(self, results, detail="detailed"):
        with Stubber(self.client) as stub:
            stub.add_response("retrieve", {"retrievalResults": results}, {
                "knowledgeBaseId": "KBDEMO1234", "retrievalQuery": {"text": "¿Quién aprueba el reembolso?"},
                "retrievalConfiguration": {"vectorSearchConfiguration": {"numberOfResults": 3}}})
            return self.retriever.answer("¿Quién aprueba el reembolso?", detail=detail)

    def test_retrieves_exact_excerpt_with_explicit_source(self):
        text = "La aprobación requiere un supervisor y confirmación explícita. La demo no transfiere dinero."
        result = self.answer([record(text)])
        self.assertIn(text, result["message"])
        self.assertEqual(result["sources"], [{"title": "Políticas de posventa de Tienda Clara · Demo educativa", "uri": SOURCE}])

    def test_duplicate_excerpts_are_not_repeated(self):
        result = self.answer([record("Solo supervisión aprueba."), record("Solo supervisión aprueba.")])
        self.assertEqual(result["message"].count("Solo supervisión aprueba."), 1)
        self.assertEqual(len(result["sources"]), 1)

    def test_brief_preference_selects_first_complete_excerpt(self):
        result = self.answer([record("Primero se solicita la devolución."), record("Luego revisa supervisión.")], "brief")
        self.assertIn("Primero se solicita la devolución.", result["message"])
        self.assertNotIn("Luego revisa", result["message"])

    def test_unapproved_document_or_bucket_is_rejected(self):
        for uri in (SOURCE + ".otro", "s3://otro-bucket/policies/politicas-posventa-demo.txt", "https://sitio.example/politica"):
            with self.subTest(uri=uri), self.assertRaises(AppError) as error:
                self.answer([record("No se debe mostrar esta fuente.", uri)])
            self.assertEqual(error.exception.code, "KNOWLEDGE_INVALID_RESPONSE")
            self.assertNotIn("No se debe mostrar", error.exception.message)

    def test_mixed_authorized_and_unauthorized_results_fail_closed(self):
        with self.assertRaises(AppError):
            self.answer([record("Fuente permitida."), record("Dato privado.", "s3://privado/orders.txt")])

    def test_empty_retrieval_does_not_invent_policy(self):
        result = self.answer([])
        self.assertIn("No encontré", result["message"])
        self.assertEqual(result["sources"], [])

    def test_retrieve_failure_has_no_local_policy_fallback(self):
        with Stubber(self.client) as stub:
            stub.add_client_error("retrieve", "DependencyFailedException")
            with self.assertRaises(ClientError):
                self.retriever.answer("¿Quién aprueba?")

    def test_nontext_empty_control_characters_and_oversize_are_rejected(self):
        for text in ("", "   ", "Texto\x00oculto", "x" * 6001):
            with self.subTest(text=text[:20]), self.assertRaises(AppError):
                self.answer([record(text)])

    def test_initialization_requires_exact_document_and_bounded_kb_id(self):
        for kb_id, source in (("kb", SOURCE), ("KBDEMO1234", "s3://tienda-demo-policies/policies/"),
                              ("KBDEMO1234", SOURCE + "\n"), ("KBDEMO1234", "https://example.com")):
            with self.subTest(source=source), self.assertRaises(ValueError):
                KnowledgeRetriever(self.client, kb_id, source)

    def test_invalid_query_or_preference_never_calls_retrieve(self):
        for message, detail in (("", "detailed"), ("x" * 2001, "detailed"), ("consulta", "approve_refund")):
            with self.subTest(message=message[:10]), self.assertRaises(AppError):
                self.retriever.answer(message, detail=detail)


if __name__ == "__main__":
    unittest.main()
