"""Focused tests for native Meta customer-message validation."""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from social_flow_client import SocialFlowClient  # noqa: E402


class SocialFlowClientMessageValidationTests(unittest.TestCase):
    @staticmethod
    def config():
        return SimpleNamespace(mode="dry-run", live=False)

    def test_eighty_characters_is_accepted_without_changing_text(self):
        message = "x" * 80
        result = SocialFlowClient.validate_page_welcome_message(message)
        self.assertTrue(result["ok"])
        self.assertEqual(result["length"], 80)
        self.assertEqual(result["customer_action"], message)

    def test_long_message_returns_precise_retryable_diagnostic(self):
        message = "Hola, quiero agendar el diagnóstico o conocer más sobre el Full Detail en el taller para mi vehículo."
        result = SocialFlowClient.validate_page_welcome_message(message)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "meta_page_welcome_message_too_long")
        self.assertEqual(result["max_length"], 80)
        self.assertEqual(result["length"], len(message))
        self.assertEqual(result["approved_value"], message)
        self.assertLessEqual(len(result["safe_short_proposal"]), 80)
        self.assertTrue(result["retryable"])

    def test_create_creative_fails_before_graph_call_and_preserves_approved_inputs(self):
        client = SocialFlowClient(self.config())
        client.run = Mock()
        message = "Hola, quiero agendar el diagnóstico o conocer más sobre el Full Detail en el taller para mi vehículo."
        result = client.create_creative(
            "act_123",
            "Full Detail",
            "page_123",
            "https://api.whatsapp.com/send",
            "Copy aprobado",
            "Título aprobado",
            "hash_123",
            "WHATSAPP_MESSAGE",
            prefilled_message=message,
            message_destination="WHATSAPP",
            approved=True,
        )
        client.run.assert_not_called()
        self.assertEqual(result["returncode"], 422)
        self.assertEqual(result["graph_endpoint"], "adcreatives:validation")
        body = json.loads(result["stderr"])
        self.assertEqual(body["error"], "meta_page_welcome_message_too_long")
        self.assertEqual(body["validation"]["approved_value"], message)
        self.assertEqual(body["preserved_inputs"]["body_text"], "Copy aprobado")
        self.assertEqual(body["preserved_inputs"]["headline"], "Título aprobado")
        self.assertIn("shorter customer message", body["next_step"])


if __name__ == "__main__":
    unittest.main()
