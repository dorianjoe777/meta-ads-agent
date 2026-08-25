"""Contract tests for the isolated campaign-creation claim classifier.

These tests deliberately exercise the public function with an injected model
callable.  They must never contact Gemini, Codex, Hermes, Meta, or a network
endpoint: the classifier is an inexpensive semantic check around an already
generated assistant response.
"""

from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "src", ROOT / "dashboard"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


classifier = importlib.import_module("campaign_claim_classifier")


class CampaignClaimClassifierTests(unittest.TestCase):
    """Public contract and provider-routing tests."""

    @staticmethod
    def _config(*, provider="gemini", model="gemini-3.5-flash-lite"):
        """Return a provider config without credentials or network access."""
        return SimpleNamespace(
            agent_brain_provider=provider,
            agent_chat_provider=provider,
            agent_chat_model=model,
            agent_chat_api_key="test-key",
            gemini_api_key="test-key",
        )

    @staticmethod
    def _compiled(value):
        return {"ok": True, "compiled": {"confirmacion_creacion_campana": value}}

    def test_gemini_yes_is_normalized_to_si(self):
        config = self._config()
        with patch.object(classifier, "_gemini_api_key", return_value="test-key"), patch.object(
            classifier, "_gemini_compile", return_value=self._compiled("si")
        ) as invoke:
            result = classifier.classify_campaign_creation_claim(
                "La campaña quedó creada y pausada.",
                provider="gemini",
                model="gemini-3.5-flash-lite",
                config=config,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["confirmation"], "si")
        invoke.assert_called_once()

    def test_gemini_no_is_normalized_to_no(self):
        config = self._config()
        with patch.object(classifier, "_gemini_api_key", return_value="test-key"), patch.object(
            classifier, "_gemini_compile", return_value=self._compiled("no")
        ):
            result = classifier.classify_campaign_creation_claim(
                "Quedo atento para estructurar la campaña.",
                provider="gemini",
                model="gemini-3.5-flash-lite",
                config=config,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["confirmation"], "no")

    def test_malformed_json_fails_closed_to_no(self):
        config = self._config()
        with patch.object(classifier, "_gemini_api_key", return_value="test-key"), patch.object(
            classifier, "_gemini_compile", return_value={"ok": True, "compiled": "not-json"
            }
        ):
            result = classifier.classify_campaign_creation_claim(
                "La campaña quedó creada y pausada.",
                provider="gemini",
                model="gemini-3.5-flash-lite",
                config=config,
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["confirmation"], "no")
        self.assertIn(result.get("reason"), {"invalid_schema", "invalid_response", "malformed_json"})

    def test_timeout_fails_closed_without_retrying_a_real_provider(self):
        def timeout(*_args, **_kwargs):
            raise TimeoutError("classifier timeout")

        config = self._config()
        with patch.object(classifier, "_gemini_api_key", return_value="test-key"), patch.object(
            classifier, "_gemini_compile", side_effect=timeout
        ):
            result = classifier.classify_campaign_creation_claim(
                "La campaña quedó creada y pausada.",
                provider="gemini",
                model="gemini-3.5-flash-lite",
                timeout=0.2,
                config=config,
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["confirmation"], "no")
        self.assertIn(result.get("reason"), {"provider_exception", "timeout", "provider_error"})

    def test_http_429_fails_closed_and_reports_rate_limit(self):
        class RateLimitError(Exception):
            status_code = 429

        config = self._config()
        with patch.object(classifier, "_gemini_api_key", return_value="test-key"), patch.object(
            classifier, "_gemini_compile", side_effect=RateLimitError("rate limited")
        ):
            result = classifier.classify_campaign_creation_claim(
                "La campaña quedó creada y pausada.",
                provider="gemini",
                model="gemini-3.5-flash-lite",
                config=config,
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["confirmation"], "no")
        self.assertIn(result.get("reason"), {"provider_exception", "rate_limit", "provider_error"})

    def test_active_model_selection_is_forwarded_to_injected_llm(self):
        config = self._config(model="gemini-3.7-flash")
        with patch.object(classifier, "_runtime_model_state", return_value={}), patch.object(
            classifier, "_gemini_api_key", return_value="test-key"
        ), patch.object(
            classifier, "_gemini_compile", return_value=self._compiled("no")
        ) as invoke:
            result = classifier.classify_campaign_creation_claim(
                "¿Quieres que prepare la campaña?",
                config=config,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["confirmation"], "no")
        self.assertEqual(invoke.call_args.args[0], "gemini-3.7-flash")

    def test_codex_uses_the_same_active_model_without_silent_model_switch(self):
        config = self._config(provider="openai-codex", model="gpt-5.6-luna")
        with patch.object(classifier, "_terra_compile", return_value=self._compiled("si")) as invoke:
            result = classifier.classify_campaign_creation_claim(
                "La campaña quedó creada en pausa.",
                provider="openai-codex",
                model="gpt-5.6-luna",
                config=config,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["confirmation"], "si")
        self.assertEqual(invoke.call_args.kwargs["model"], "gpt-5.6-luna")


if __name__ == "__main__":
    unittest.main()
