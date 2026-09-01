"""Focused regressions for campaign compiler provider resilience.

These tests deliberately stop at mocked provider boundaries.  They never call
Meta, Telegram, Gemini, or Codex.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import admira_hermes_runtime_patch as runtime_patch
import admira_tool_bridge as bridge
import campaign_payload_compiler as compiler
import hosted_central_campaign_compiler as central_client


class CampaignProviderResilienceTests(unittest.TestCase):
    def config(self, *, model="gemini-3.5-flash", api_key="test-gemini-key"):
        return SimpleNamespace(
            agent_chat_model=model,
            gemini_api_key=api_key,
            agent_chat_api="",
            agent_chat_base_url="",
            agent_chat_api_key="",
            codex_cli="codex",
            hermes_home="/tmp/hermes-test",
        )

    def test_campaign_compiler_uses_exact_flash_chain_then_terra(self):
        calls = []

        def gemini(model, *_args, **_kwargs):
            calls.append(("gemini", model))
            return {"ok": False, "reason": "provider_unavailable"}

        def terra(*_args, **_kwargs):
            calls.append(("terra", _kwargs.get("model", compiler.TERRA_COMPILER_MODEL)))
            return {"ok": False, "reason": "provider_unavailable"}

        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(compiler, "LATEST_BRIEF_FILE", Path(directory) / "brief.md"), \
                mock.patch.object(compiler, "LATEST_PAYLOAD_FILE", Path(directory) / "payload.json"), \
                mock.patch.object(compiler, "CONTRACT_FILE", Path(directory) / "contract.md"), \
                mock.patch.object(compiler, "_buyer_decision_gaps", return_value=[]), \
                mock.patch.object(compiler, "_held_campaign_proposal", return_value=""), \
                mock.patch.object(compiler, "_gemini_compile", side_effect=gemini), \
                mock.patch.object(compiler, "_terra_compile", side_effect=terra), \
                mock.patch.object(compiler, "codex_auth_artifact_present", return_value=True, create=True), \
                mock.patch.object(compiler, "codex_cli_environment", return_value={}, create=True):
            result = compiler.compile_campaign_brief(
                "admira_create_whatsapp_campaign",
                "## Verbatim recent buyer messages (authoritative)\n\nCrear campaña con todos los datos aprobados.",
                config=self.config(model="gemini-3.5-flash-lite"),
            )

        self.assertFalse(result["ok"])
        self.assertEqual(
            [model for provider, model in calls],
            [
                "gemini-3.5-flash",
                "gemini-3.6-flash",
                "gemini-3.7-flash",
                "gpt-5.6-terra",
            ],
        )
        self.assertNotIn("gemini-3.5-flash-lite", [model for provider, model in calls])

    def test_terra_uses_central_pool_when_hosted_and_preserves_local_do_path(self):
        central = {
            "ok": True,
            "compiled": {"ready": False, "missing_fields": [], "payload_json": "{}"},
            "model": compiler.TERRA_COMPILER_MODEL,
            "provider": "hosted-central-codex",
        }
        config = SimpleNamespace(codex_cli="codex", hermes_home="/tmp/hermes-test")
        with mock.patch.object(central_client, "maybe_compile_central_campaign", return_value=central), \
                mock.patch.object(compiler.subprocess, "Popen", side_effect=AssertionError("must not use tenant Codex")):
            hosted = compiler._terra_compile(
                "approved brief", {"type": "object"}, config=config, timeout=10,
                tool="admira_create_whatsapp_campaign",
            )
        self.assertEqual(hosted, central)

        compiled_output = {"ready": False, "missing_fields": [], "payload_json": "{}"}

        class LocalProcess:
            def __init__(self, command, **_kwargs):
                self.command = command
                self.returncode = 0
                self.pid = 1

            def communicate(self, _prompt, timeout=None):
                output = Path(self.command[self.command.index("-o") + 1])
                output.write_text(json.dumps(compiled_output), encoding="utf-8")
                return "", ""

        with mock.patch.object(central_client, "maybe_compile_central_campaign", return_value=None), \
                mock.patch.object(compiler, "codex_cli_environment", return_value={"CODEX_HOME": "/tmp/do-codex"}) as environment, \
                mock.patch.object(compiler.subprocess, "Popen", LocalProcess):
            local = compiler._terra_compile(
                "approved brief", {"type": "object"}, config=config, timeout=10,
                tool="admira_create_whatsapp_campaign",
            )
        self.assertTrue(local["ok"])
        self.assertEqual(local["model"], compiler.TERRA_COMPILER_MODEL)
        environment.assert_called_once_with(config, codex_home=None)

    def pending_contract(self):
        return {
            "name": "Campaña USD 10",
            "daily_budget": 10,
            "budget_confirmation": "USD 10 diarios",
            "primary_text": "Texto aprobado completo",
            "headline": "Título aprobado",
            "primary_text_approved": True,
            "headline_approved": True,
            "creative_decision": "/tmp/creative-approved.png",
            "creative_approved": True,
            "prefilled_message": "Hola, quiero reservar.",
            "prefilled_message_approved": True,
        }

    def test_compiler_retry_failure_preserves_complete_pending_campaign_contract(self):
        contract = self.pending_contract()
        with tempfile.TemporaryDirectory() as directory:
            pending_path = Path(directory) / "pending-workflow.json"
            previous_fingerprint = bridge.campaign_creation_fingerprint(
                "admira_create_whatsapp_campaign", contract,
            )
            pending_path.write_text(json.dumps({
                "status": "pending",
                "destination": "whatsapp",
                "tool": "admira_create_whatsapp_campaign",
                "creation_fingerprint": previous_fingerprint,
                "campaign_contract": contract,
                "blocker": "campaign_retry_ready",
                "meta_creation_verified": False,
                "proposal_brief_markdown": "Approved exact campaign proposal.",
            }), encoding="utf-8")
            failure = {
                "ok": False,
                "reason": "campaign_compiler_provider_failed",
                "error": "No pude compilar la campaña todavía; conservaré todo lo aprobado para reintentar.",
            }
            with mock.patch.object(bridge, "PENDING_CAMPAIGN_WORKFLOW_FILE", pending_path), \
                    mock.patch.object(bridge, "compile_campaign_brief", return_value=failure), \
                    mock.patch.object(bridge, "load_dashboard", return_value=SimpleNamespace()), \
                    mock.patch.object(bridge, "strategic_profile_gate_result", return_value=None):
                result = bridge.call_tool(
                    "admira_create_whatsapp_campaign",
                    {"brief_markdown": "## Approved campaign\n\nRetry unchanged."},
                )

            stored = json.loads(pending_path.read_text(encoding="utf-8"))

        self.assertFalse(result["ok"])
        self.assertEqual(stored["campaign_contract"], contract)
        self.assertEqual(stored["blocker"], failure["reason"])
        self.assertEqual(stored["creation_fingerprint"], previous_fingerprint)

    def test_safe_compiler_failure_reply_survives_telegram_normalization_without_generic_fallback(self):
        internal_error = "Codex CLI no está autenticado; usa Hermes/API."
        failure = {"ok": False, "reason": "campaign_compiler_provider_failed", "error": internal_error}
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(bridge, "PENDING_CAMPAIGN_WORKFLOW_FILE", Path(directory) / "pending.json"), \
                mock.patch.object(bridge, "compile_campaign_brief", return_value=failure), \
                mock.patch.object(bridge, "load_dashboard", return_value=SimpleNamespace()), \
                mock.patch.object(bridge, "strategic_profile_gate_result", return_value=None):
            result = bridge.call_tool(
                "admira_create_whatsapp_campaign",
                {**self.pending_contract(), "brief_markdown": "## Approved campaign\n\nRetry unchanged."},
            )

        normalized, metadata = runtime_patch.normalize_telegram_outbound_text(result["reply"], "es")
        self.assertEqual(normalized, result["reply"])
        self.assertFalse(metadata["fallback"])
        self.assertIn("No se creó nada en Meta", normalized)
        self.assertIn("Conservé el presupuesto", normalized)
        self.assertNotIn("Codex CLI", normalized)
        self.assertNotIn("Hermes", normalized)
        self.assertNotIn("No pude mostrar correctamente", normalized)


if __name__ == "__main__":
    unittest.main()
