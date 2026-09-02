from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import hermes_bridge
import hosted_central_conversation_client


class ConversationalProviderFallbackTests(unittest.TestCase):
    def _brain(self, model="gemini-3.5-flash-lite"):
        return {"brain": "gemini", "provider": "gemini", "model": model}

    def test_gemini_advances_through_full_flash_models_before_central_terra(self):
        with mock.patch.object(hosted_central_conversation_client, "central_conversation_route", return_value="central"):
            chain = hermes_bridge.admira_inference_fallback_chain(object(), self._brain())
        self.assertEqual(chain, [
            {"provider": "gemini", "model": "gemini-3.5-flash"},
            {"provider": "gemini", "model": "gemini-3.6-flash"},
            {"provider": "gemini", "model": "gemini-3.7-flash"},
            {"provider": "admira-central-codex", "model": "admira-terra"},
        ])
        self.assertNotIn({"provider": "gemini", "model": "gemini-3.5-flash-lite"}, chain)

    def test_central_route_never_crosses_to_personal_oauth(self):
        with mock.patch.object(hosted_central_conversation_client, "central_conversation_route", return_value="central"), \
                mock.patch.object(hermes_bridge, "codex_credential_health", side_effect=AssertionError("must not read personal OAuth")):
            chain = hermes_bridge.admira_inference_fallback_chain(object(), self._brain())
        self.assertEqual(chain[-1], {"provider": "admira-central-codex", "model": "admira-terra"})

    def test_pool_off_uses_buyer_oauth_only_after_flash_models(self):
        with mock.patch.object(hosted_central_conversation_client, "central_conversation_route", return_value="local"), \
                mock.patch.object(hermes_bridge, "codex_credential_health", return_value={"state": "stored", "reauth_required": False}):
            chain = hermes_bridge.admira_inference_fallback_chain(object(), self._brain())
        self.assertEqual(chain[-1], {"provider": "openai-codex", "model": "gpt-5.6-luna"})
        self.assertEqual([item["model"] for item in chain[:-1]], [
            "gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash",
        ])

    def test_gemini_never_retries_the_same_model_before_chain_advance(self):
        policy = hermes_bridge.inference_runtime_policy(self._brain("gemini-3.6-flash"))
        self.assertEqual(policy["api_max_retries"], 0)
        with tempfile.TemporaryDirectory() as directory:
            config = type("Config", (), {"hermes_home": str(Path(directory))})()
            with mock.patch.object(hosted_central_conversation_client, "central_conversation_route", return_value="blocked"):
                rendered = "\n".join(hermes_bridge.admira_fallback_config_lines(config, self._brain()))
        self.assertIn('provider: "gemini"', rendered)
        self.assertNotIn('provider: "openai-codex"', rendered)


if __name__ == "__main__":
    unittest.main()
