import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import admira_hermes_runtime_patch as runtime
import hermes_bridge as bridge


class ConversationRecoveryTests(unittest.TestCase):
    def test_private_context_never_changes_user_tools_or_attachments(self):
        for content in ("que", "explícame lo que pasó", [
            {"type": "text", "text": "mira esta imagen"},
            {"type": "image_url", "image_url": {"url": "https://example.com/image.png"}},
        ]):
            original = [{"role": "user", "content": content},
                        {"role": "tool", "content": "tool-data", "tool_call_id": "call-1"}]
            before = copy.deepcopy(original)
            result = runtime._nvidia_append_private_instruction(original, "application-only guidance")
            self.assertEqual(result[0]["role"], "system")
            self.assertEqual(result[1:], original)
            self.assertEqual(original, before)

    def test_existing_system_message_receives_context(self):
        source = [{"role": "system", "content": "Existing policy"}, {"role": "user", "content": "que"}]
        result = runtime._nvidia_append_private_instruction(source, "runtime-context")
        self.assertIn("Existing policy", result[0]["content"])
        self.assertIn("runtime-context", result[0]["content"])
        self.assertEqual(result[1], source[1])

    def test_previous_final_reply_and_failure_are_system_data_in_both_provider_formats(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            data = root / "dashboard/data"
            data.mkdir(parents=True)
            previous = {"buyer_message": "confirmo el resumen", "assistant_reply": "Tu resumen está guardado. La propuesta falló temporalmente."}
            (data / "trusted_buyer_turn.json").write_text(json.dumps({"message": "que", "previous_exchange": previous}))
            (data / "strategic_plan_generation.json").write_text(json.dumps({"p1": {
                "profile_revision": 5, "status": "failed", "reason": "strategic_plan_provider_http_503", "retry_after": "2026-09-09T15:44:58Z"}}))
            state = {"complete": True, "revision": 5, "master_plan_status": "missing", "bound_page_id": "p1"}
            with patch.dict(os.environ, {"ADMIRA_PRODUCT_ROOT": raw}):
                chat = runtime._admira_attach_compiled_procedure({"messages": [{"role": "user", "content": "que"}]}, state=state)
                responses = runtime._admira_attach_compiled_procedure({"input": [{"role": "user", "content": "que"}], "instructions": "Policy"}, state=state)
            self.assertEqual(chat["messages"][-1], {"role": "user", "content": "que"})
            self.assertIn(previous["assistant_reply"], chat["messages"][0]["content"])
            self.assertIn("strategic_plan_provider_http_503", responses["instructions"])
            self.assertEqual(responses["input"], [
                {"role": "user", "content": previous["buyer_message"]},
                {"role": "assistant", "content": previous["assistant_reply"]},
                {"role": "user", "content": "que"},
            ])
            self.assertNotIn("messages", responses)

    def test_reconcile_replaces_raw_draft_preserving_tools_and_current_buyer(self):
        source = [{"role": "user", "content": "confirmo"},
                  {"role": "assistant", "tool_calls": [{"id": "call-1"}]},
                  {"role": "tool", "tool_call_id": "call-1", "content": "receipt"},
                  {"role": "assistant", "content": "wrong raw draft"},
                  {"role": "user", "content": "qué pasó"}]
        before = copy.deepcopy(source)
        turn = {"message": "qué pasó", "previous_exchange": {
            "buyer_message": "confirmo", "assistant_reply": "Tu resumen se guardó. La propuesta falló temporalmente."}}
        actual = runtime._admira_reconcile_finalized_exchange(source, turn)
        self.assertEqual(actual[:3], source[:3])
        self.assertEqual(actual[-1], source[-1])
        self.assertEqual(actual[-2]["content"], turn["previous_exchange"]["assistant_reply"])
        self.assertEqual(source, before)
        self.assertEqual(runtime._admira_reconcile_finalized_exchange(actual, turn), actual)
        self.assertEqual(runtime._admira_reconcile_finalized_exchange(source, {**turn, "message": "another request"}), source)

    def test_pending_compilation_resumes_without_a_new_confirmation_or_keyword(self):
        for message in ("que", "háblame de mi video", "sigamos", "¿qué pasó?"):
            payload = {"channel": "telegram", "message": message, "message_sequence": 45,
                       "_admira_trusted_chat_id": "legacy_telegram:123", "_admira_trusted_session_id": "s1"}
            with patch.object(runtime, "_resolve_business_lifecycle_transition", return_value={"transitioned": False}), \
                 patch.object(runtime, "_ensure_initial_business_master_plan", return_value={"created": True}) as ensure:
                result = bridge._resolve_bridge_business_lifecycle(payload)
            self.assertTrue(result["plan_generation"]["created"])
            self.assertEqual(ensure.call_args.kwargs["expected_turn"]["raw_message"], message)

    def test_failed_compilation_uses_normal_agent_and_records_its_final_reply(self):
        payload = {"channel": "telegram", "message": "confirmo el resumen", "message_sequence": 45,
                   "_admira_trusted_chat_id": "legacy_telegram:123", "_admira_trusted_session_id": "s1"}
        config = SimpleNamespace(hermes_require_codex_auth=False)
        dashboard = Mock()
        with patch.object(bridge, "_record_bridge_trusted_buyer_turn", side_effect=lambda p: p), \
             patch.object(bridge, "hermes_brain_settings", return_value={}), \
             patch.object(bridge, "hermes_brain_ready", return_value=(True, "ready")), \
             patch.object(bridge, "_resolve_bridge_business_lifecycle", return_value={"plan_generation": {
                 "attempted": True, "created": False, "ok": False, "reason": "strategic_plan_provider_http_503"}}), \
             patch.object(bridge, "cli_chat", return_value="Tu resumen se guardó. Estoy teniendo un fallo temporal al preparar la propuesta.") as chat, \
             patch.object(bridge, "_finalize_bridge_lifecycle_reply", side_effect=lambda p, r, *_: r), \
             patch.object(runtime, "_admira_dashboard_module", return_value=dashboard):
            result = bridge.chat(config, payload)
        chat.assert_called_once_with(config, payload)
        self.assertTrue(result["ok"])
        self.assertNotIn("evidencia necesaria", result["reply"])
        self.assertEqual(dashboard.record_finalized_buyer_reply.call_args.kwargs["assistant_text"], result["reply"])


if __name__ == "__main__":
    unittest.main()
