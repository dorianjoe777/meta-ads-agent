"""No-network contract tests for business lifecycle transition classification."""

from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "src", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

classifier = importlib.import_module("business_lifecycle_classifier")


class BusinessLifecycleClassifierTests(unittest.TestCase):
    @staticmethod
    def config(provider="gemini", model="gemini-3.5-flash-lite"):
        return SimpleNamespace(
            agent_brain_provider=provider,
            agent_chat_provider=provider,
            agent_chat_model=model,
            agent_chat_api_key="test-key",
            gemini_api_key="test-key",
        )

    @staticmethod
    def compiled(value):
        return {"ok": True, "compiled": {"confirmacion_transicion": value}}

    def classify(self, buyer, value="si", target="business_profile"):
        with patch.object(classifier, "_gemini_api_key", return_value="test-key"), patch.object(
            classifier, "_gemini_compile", return_value=self.compiled(value)
        ) as call:
            result = classifier.classify_lifecycle_transition(
                target, "Perfil presentado: servicios, público y marca.", buyer,
                provider="gemini", model="gemini-3.5-flash-lite", config=self.config(),
            )
        self.assertEqual(call.call_count, 1)
        return result

    def test_natural_acceptance_is_yes(self):
        result = self.classify("Me parece genial, podemos seguir.")
        self.assertTrue(result["ok"])
        self.assertEqual(result["confirmation"], "si")

    def test_explicit_confirmation_is_yes_for_strategic_plan(self):
        result = self.classify("Sí, confirmo el plan y quiero guardarlo.", target="strategic_plan")
        self.assertTrue(result["ok"])
        self.assertEqual(result["confirmation"], "si")

    def test_correction_is_no(self):
        self.assertEqual(self.classify("Corrige la ciudad: atendemos en Cali.", value="no")["confirmation"], "no")

    def test_question_is_no(self):
        self.assertEqual(self.classify("¿Qué incluye exactamente este perfil?", value="no")["confirmation"], "no")

    def test_greeting_is_no(self):
        self.assertEqual(self.classify("Hola, ¿cómo estás?", value="no")["confirmation"], "no")

    def test_repeated_facts_without_acceptance_are_no(self):
        self.assertEqual(self.classify("Ofrecemos detailing premium y servicio a domicilio.", value="no")["confirmation"], "no")

    def test_malformed_json_fails_closed(self):
        with patch.object(classifier, "_gemini_api_key", return_value="test-key"), patch.object(
            classifier, "_gemini_compile", return_value={"ok": True, "compiled": "bad"
        }):
            result = classifier.classify_lifecycle_transition(
                "business_profile", "Perfil presentado", "Sí, está confirmado.", config=self.config()
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["confirmation"], "no")

    def test_timeout_fails_closed(self):
        with patch.object(classifier, "_gemini_api_key", return_value="test-key"), patch.object(
            classifier, "_gemini_compile", side_effect=TimeoutError()
        ):
            result = classifier.classify_lifecycle_transition(
                "business_profile", "Perfil presentado", "Sí.", config=self.config()
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["confirmation"], "no")
        self.assertEqual(result["reason"], "timeout")

    def test_429_fails_closed(self):
        class RateLimitError(Exception):
            status_code = 429
        with patch.object(classifier, "_gemini_api_key", return_value="test-key"), patch.object(
            classifier, "_gemini_compile", side_effect=RateLimitError()
        ):
            result = classifier.classify_lifecycle_transition(
                "business_profile", "Perfil presentado", "Sí.", config=self.config()
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["confirmation"], "no")
        self.assertEqual(result["reason"], "rate_limit")

    def test_gemini_routes_once_with_schema_and_no_history(self):
        with patch.object(classifier, "_gemini_api_key", return_value="test-key"), patch.object(
            classifier, "_gemini_compile", return_value=self.compiled("si")
        ) as call:
            result = classifier.classify_lifecycle_transition(
                "business_profile", "Perfil presentado", "Sí, confirmo.",
                provider="gemini", model="gemini-3.5-flash-lite", config=self.config()
            )
        self.assertTrue(result["ok"])
        self.assertEqual(call.call_args.args[2], classifier.SCHEMA)
        prompt = call.call_args.args[1]
        self.assertIn("<presented_artifact>", prompt)
        self.assertNotIn("Hermes", prompt)

    def test_codex_luna_routes_same_active_model_once(self):
        config = self.config("openai-codex", "gpt-5.6-luna")
        with patch.object(classifier, "_terra_compile", return_value=self.compiled("si")) as call:
            result = classifier.classify_lifecycle_transition(
                "strategic_plan", "Plan presentado", "Sí, guárdalo como plan final.",
                provider="openai-codex", model="gpt-5.6-luna", config=config
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["confirmation"], "si")
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.kwargs["model"], "gpt-5.6-luna")

    def test_invalid_target_and_missing_artifact_fail_closed_without_call(self):
        config = self.config()
        with patch.object(classifier, "_gemini_compile") as call:
            invalid = classifier.classify_lifecycle_transition("other", "x", "sí", config=config)
            missing = classifier.classify_lifecycle_transition("business_profile", "", "sí", config=config)
        self.assertEqual(invalid["confirmation"], "no")
        self.assertEqual(missing["confirmation"], "no")
        call.assert_not_called()

    def test_plan_update_direct_request_is_yes(self):
        with patch.object(classifier, "_gemini_api_key", return_value="test-key"), patch.object(
            classifier, "_gemini_compile", return_value={"ok": True, "compiled": {"solicitud_actualizacion_plan": "si"}}
        ) as call:
            result = classifier.classify_strategic_plan_update_request(
                "Plan confirmado: captar clientes por WhatsApp.",
                "Quiero añadir el servicio de pulido al plan estratégico guardado.",
                provider="gemini", model="gemini-3.5-flash-lite", config=self.config(),
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["confirmation"], "si")
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[2], classifier.PLAN_UPDATE_SCHEMA)

    def test_plan_update_new_fact_campaign_and_informal_idea_are_no(self):
        for message in (
            "También ofrecemos lavado de motor desde 50.000 COP.",
            "Crea una campaña de WhatsApp para el servicio premium.",
            "Podríamos probar videos de antes y después.",
        ):
            with self.subTest(message=message), patch.object(
                classifier, "_gemini_api_key", return_value="test-key"
            ), patch.object(
                classifier, "_gemini_compile", return_value={
                    "ok": True, "compiled": {"solicitud_actualizacion_plan": "no"}
                }
            ):
                result = classifier.classify_strategic_plan_update_request(
                    "Plan confirmado: captar clientes por WhatsApp.", message,
                    provider="gemini", model="gemini-3.5-flash-lite", config=self.config(),
                )
            self.assertTrue(result["ok"])
            self.assertEqual(result["confirmation"], "no")

    def test_plan_update_codex_luna_routes_once(self):
        config = self.config("openai-codex", "gpt-5.6-luna")
        with patch.object(classifier, "_terra_compile", return_value={
            "ok": True, "compiled": {"solicitud_actualizacion_plan": "si"}
        }) as call:
            result = classifier.classify_strategic_plan_update_request(
                "Plan confirmado", "Modifica el plan estratégico: prioricemos Bogotá.",
                provider="openai-codex", model="gpt-5.6-luna", config=config,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["confirmation"], "si")
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.kwargs["model"], "gpt-5.6-luna")

    def test_plan_update_timeout_and_invalid_json_fail_closed(self):
        with patch.object(classifier, "_gemini_api_key", return_value="test-key"), patch.object(
            classifier, "_gemini_compile", side_effect=TimeoutError()
        ):
            timeout = classifier.classify_strategic_plan_update_request(
                "Plan confirmado", "Actualiza el plan estratégico.", config=self.config()
            )
        self.assertFalse(timeout["ok"])
        self.assertEqual(timeout["confirmation"], "no")
        self.assertEqual(timeout["reason"], "timeout")

        with patch.object(classifier, "_gemini_api_key", return_value="test-key"), patch.object(
            classifier, "_gemini_compile", return_value={"ok": True, "compiled": {"unexpected": "si"}}
        ):
            malformed = classifier.classify_strategic_plan_update_request(
                "Plan confirmado", "Actualiza el plan estratégico.", config=self.config()
            )
        self.assertFalse(malformed["ok"])
        self.assertEqual(malformed["confirmation"], "no")


if __name__ == "__main__":
    unittest.main()
