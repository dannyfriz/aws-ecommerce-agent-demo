"""Pruebas de bloqueo y falla segura del filtro de contenido."""
import unittest
from unittest.mock import Mock
from ecommerce_agent.content_guard import BedrockContentGuard
from ecommerce_agent.domain import AppError


class ContentGuardTests(unittest.TestCase):
    def test_allow_uses_published_guardrail_and_exact_source(self):
        client = Mock()
        client.apply_guardrail.return_value = {"action": "NONE"}
        BedrockContentGuard(client, "guard", "1").check("Consulta P-104")
        client.apply_guardrail.assert_called_once_with(
            guardrailIdentifier="guard", guardrailVersion="1", source="INPUT",
            content=[{"text": {"text": "Consulta P-104"}}])

    def test_block_does_not_return_detected_sensitive_content(self):
        client = Mock()
        client.apply_guardrail.return_value = {"action": "GUARDRAIL_INTERVENED", "outputs": [{"text": "dato privado"}]}
        with self.assertRaises(AppError) as error:
            BedrockContentGuard(client, "guard", "1").check("dato privado")
        self.assertEqual(error.exception.reason, "GUARDRAIL_BLOCKED")
        self.assertNotIn("dato privado", error.exception.message)

    def test_unknown_result_and_dependency_failure_never_allow(self):
        client = Mock()
        client.apply_guardrail.return_value = {}
        with self.assertRaises(AppError):
            BedrockContentGuard(client, "guard", "1").check("consulta")
        client.apply_guardrail.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            BedrockContentGuard(client, "guard", "1").check("consulta")

    def test_output_is_checked_separately(self):
        client = Mock()
        client.apply_guardrail.return_value = {"action": "NONE"}
        BedrockContentGuard(client, "guard", "1").check("Política de la demo", "OUTPUT")
        self.assertEqual(client.apply_guardrail.call_args.kwargs["source"], "OUTPUT")
