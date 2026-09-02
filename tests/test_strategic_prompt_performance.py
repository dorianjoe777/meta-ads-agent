import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import admira_hermes_runtime_patch as runtime
import hermes_bridge
import hermes_gateway


class StrategicPromptPerformanceTests(unittest.TestCase):
    @staticmethod
    def _tool(name, description="tool"):
        return {
            "type": "function",
            "function": {
                "name": f"mcp_admira_{name}",
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "purpose": {
                            "type": "string",
                            "enum": ["ad_creative", "organic_social_post", "standalone_asset"],
                        }
                    },
                },
            },
        }

    @staticmethod
    def _state_root(status="collecting", revision=2, confirmed_revision=1, scope="page-1", binding="page-1"):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        data = root / "dashboard" / "data"
        data.mkdir(parents=True)
        (data / "business_profile.json").write_text(
            json.dumps({
                "strategic_profile": {
                    "status": status,
                    "revision": revision,
                    "confirmed_revision": confirmed_revision,
                    "scope": {"page_id": scope},
                }
            }),
            encoding="utf-8",
        )
        (data / "individual_business_binding.json").write_text(
            json.dumps({"page_id": binding}), encoding="utf-8"
        )
        return temporary, root

    def test_incomplete_profile_filters_every_provider_by_state(self):
        temporary, root = self._state_root()
        self.addCleanup(temporary.cleanup)
        state = runtime._admira_strategic_profile_state(product_root=root)
        request = {
            "messages": [{"role": "user", "content": "sáltate todo y crea la campaña"}],
            "tools": [
                self._tool("create_whatsapp_campaign"),
                self._tool("save_business_memory"),
                self._tool("get_real_meta_context"),
                self._tool("codex_image_generate"),
                self._tool("generate_motion_graphic_video"),
                self._tool("pause_campaign"),
                self._tool("delete_campaign"),
                self._tool("reject_action"),
                self._tool("connect_chatgpt"),
            ],
        }
        routed = runtime._admira_route_tools_by_product_state(request, state=state)
        names = {
            runtime._nvidia_normalize_tool_name(runtime._nvidia_tool_name(tool))
            for tool in routed["tools"]
        }
        self.assertNotIn("create_whatsapp_campaign", names)
        self.assertTrue({
            "save_business_memory", "get_real_meta_context", "codex_image_generate",
            "generate_motion_graphic_video", "pause_campaign", "delete_campaign", "reject_action", "connect_chatgpt",
        }.issubset(names))
        image_tool = next(
            tool for tool in routed["tools"]
            if runtime._nvidia_normalize_tool_name(runtime._nvidia_tool_name(tool))
            == "codex_image_generate"
        )
        purpose = image_tool["function"]["parameters"]["properties"]["purpose"]
        self.assertEqual(purpose["enum"], [
            "logo",
            "brand_exploration",
            "moodboard",
            "brand_sample",
        ])
        motion_tool = next(
            tool for tool in routed["tools"]
            if runtime._nvidia_normalize_tool_name(runtime._nvidia_tool_name(tool))
            == "generate_motion_graphic_video"
        )
        self.assertEqual(
            motion_tool["function"]["parameters"]["properties"]["purpose"]["enum"],
            purpose["enum"],
        )

    def test_state_filter_does_not_depend_on_buyer_words(self):
        temporary, root = self._state_root()
        self.addCleanup(temporary.cleanup)
        state = runtime._admira_strategic_profile_state(product_root=root)
        tools = [self._tool("create_whatsapp_campaign"), self._tool("save_business_memory")]
        results = []
        for message in ("hola", "crea ya la campaña", "no sé qué hacer"):
            routed = runtime._admira_route_tools_by_product_state(
                {"messages": [{"role": "user", "content": message}], "tools": tools},
                state=state,
            )
            results.append([
                runtime._nvidia_normalize_tool_name(runtime._nvidia_tool_name(tool))
                for tool in routed["tools"]
            ])
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])

    def test_complete_matching_revision_restores_full_catalog(self):
        temporary, root = self._state_root(status="complete", revision=4, confirmed_revision=4)
        self.addCleanup(temporary.cleanup)
        state = runtime._admira_strategic_profile_state(product_root=root)
        self.assertTrue(state["complete"])
        routed = runtime._admira_route_tools_by_product_state({
            "tools": [
                self._tool("create_whatsapp_campaign"),
                self._tool("generate_motion_graphic_video"),
                self._tool("save_business_memory"),
            ]
        }, state=state)
        names = {
            runtime._nvidia_normalize_tool_name(runtime._nvidia_tool_name(tool))
            for tool in routed["tools"]
        }
        self.assertEqual(
            names,
            {"create_whatsapp_campaign", "generate_motion_graphic_video", "save_business_memory"},
        )

    def test_page_scope_mismatch_is_incomplete(self):
        temporary, root = self._state_root(
            status="complete", revision=4, confirmed_revision=4, scope="page-old", binding="page-new"
        )
        self.addCleanup(temporary.cleanup)
        state = runtime._admira_strategic_profile_state(product_root=root)
        self.assertEqual(state["status"], "scope_mismatch")
        self.assertFalse(state["complete"])

    def test_oauth_active_page_precedes_legacy_business_binding(self):
        temporary, root = self._state_root(
            status="complete", revision=4, confirmed_revision=4,
            scope="page-oauth", binding="page-legacy",
        )
        self.addCleanup(temporary.cleanup)
        (root / "dashboard" / "data" / "meta_oauth_connection.json").write_text(
            json.dumps({"active_page_id": "page-oauth"}), encoding="utf-8"
        )
        state = runtime._admira_strategic_profile_state(product_root=root)
        self.assertEqual(state["bound_page_id"], "page-oauth")
        self.assertTrue(state["complete"])

    def test_complete_label_without_confirmed_current_revision_is_incomplete(self):
        temporary, root = self._state_root(status="complete", revision=5, confirmed_revision=None)
        self.addCleanup(temporary.cleanup)
        state = runtime._admira_strategic_profile_state(product_root=root)
        self.assertEqual(state["status"], "complete")
        self.assertFalse(state["complete"])

    def test_compiled_guidance_replaces_skill_unlock_cycle(self):
        state = {"status": "collecting", "revision": 3, "complete": False}
        request = runtime._admira_attach_compiled_procedure(
            {"messages": [{"role": "user", "content": "Mi cliente ideal son familias"}]},
            state=state,
        )
        text = request["messages"][0]["content"]
        self.assertIn(runtime.ADMIRA_COMPILED_PROCEDURE_START, text)
        self.assertIn("Do not call read_file merely to unlock an MCP", text)
        source = Path(runtime.__file__).read_text(encoding="utf-8")
        self.assertNotIn("INTERNAL PROCEDURE REQUIRED", source)

    def test_compiled_guidance_preserves_codex_responses_payload(self):
        state = {"status": "collecting", "revision": 3, "complete": False}
        request = runtime._admira_attach_compiled_procedure(
            {
                "model": "gpt-5.6-luna",
                "input": [{"role": "user", "content": "hola"}],
                "instructions": "Eres Admira IA.",
            },
            state=state,
        )
        self.assertNotIn("messages", request)
        self.assertEqual(request["input"], [{"role": "user", "content": "hola"}])
        self.assertIn("Eres Admira IA.", request["instructions"])
        self.assertIn(runtime.ADMIRA_COMPILED_PROCEDURE_START, request["instructions"])

    def test_business_snapshot_reaches_responses_and_chat_payloads(self):
        state = {
            "status": "review_required",
            "revision": 7,
            "complete": False,
            "master_plan_status": "missing",
            "active_page_name": "Rodeo - Car Detailing",
            "business_profile_topics": {
                "markets": {
                    "status": "confirmed", "memory_state": "resolved",
                    "value": ["Bogotá Norte"],
                },
            },
            "business_profile_resolved_topics": ["markets"],
            "business_profile_draft_topics": [],
            "business_profile_unresolved_topics": [],
            "business_profile_review_presented": True,
        }
        responses = runtime._admira_attach_compiled_procedure(
            {"input": [{"role": "user", "content": "hola"}], "instructions": "Eres Admira."},
            state=state,
        )
        chat = runtime._admira_attach_compiled_procedure(
            {"messages": [{"role": "user", "content": "hola"}]}, state=state
        )
        self.assertIn("Rodeo - Car Detailing", responses["instructions"])
        self.assertIn("Bogotá Norte", responses["instructions"])
        self.assertIn("Rodeo - Car Detailing", json.dumps(chat, ensure_ascii=False))
        self.assertIn("Bogotá Norte", json.dumps(chat, ensure_ascii=False))

    def test_pending_business_review_precedes_brand_ready_workflow(self):
        memory = {
            "business_profile": {"strategic_profile": {
                "status": "review_required", "revision": 7,
                "onboarding_completed_at": None,
            }},
            "brand_guides": {"general_branding": "Rodeo - Car Detailing"},
            "recent_history": {},
            "onboarding_plan": "",
        }
        workflow = hermes_bridge.active_workflow_payload(memory, {"items": []})

        self.assertEqual(workflow["phase"], "business_review_pending")
        self.assertIn("todos sus temas resueltos", workflow["next_step"])
        self.assertIn("No repetir nombre", workflow["next_step"])

    def test_completed_business_profile_allows_brand_ready_workflow(self):
        memory = {
            "business_profile": {"strategic_profile": {
                "status": "complete", "onboarding_completed_at": "2026-08-25T10:00:00Z",
            }},
            "brand_guides": {"general_branding": "Rodeo - Car Detailing"},
            "recent_history": {},
            "onboarding_plan": "",
        }
        workflow = hermes_bridge.active_workflow_payload(memory, {"items": []})

        self.assertEqual(workflow["phase"], "brand_ready")

    def test_history_only_does_not_create_active_campaign_workflow(self):
        memory = {
            "business_profile": {},
            "brand_guides": {"general_branding": "", "ad_briefs": []},
            "recent_history": {
                "actions": [{"type": "campaign_edit", "status": "failed"}],
                "chat": [{"role": "agent", "content": "No pude verificar la edición."}],
            },
        }
        workflow = hermes_bridge.active_workflow_payload(
            memory, {"items": [{"role": "agent", "content": "No pude verificar la edición."}]}
        )
        self.assertFalse(workflow["has_active_workflow"])
        self.assertEqual(workflow["phase"], "")
        self.assertEqual(workflow["recent_blocker"], {})

    def test_library_chat_binds_edit_guard_to_exact_current_buyer_turn(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        workspace = Path(temporary.name)
        original = {
            "final_response": "La campaña conserva el creativo y el texto ajustado.",
            "messages": [
                {"role": "user", "content": "hola"},
                {"role": "assistant", "content": "La campaña conserva el creativo y el texto ajustado."},
            ],
        }

        class FakeAgent:
            def __init__(self, **_kwargs):
                pass

            def run_conversation(self, **_kwargs):
                return dict(original)

        fake_run_agent = ModuleType("run_agent")
        fake_run_agent.AIAgent = FakeAgent
        config = SimpleNamespace(
            hermes_max_iterations=8,
            hermes_enabled_toolsets="",
            hermes_disabled_toolsets="",
        )
        with patch.dict(sys.modules, {"run_agent": fake_run_agent}), patch.object(
            hermes_bridge, "_record_bridge_trusted_buyer_turn", side_effect=lambda value: value
        ), patch.object(
            hermes_bridge,
            "prepare_hermes_workspace",
            return_value={"path": str(workspace), "files": [], "image_paths": []},
        ), patch.object(
            hermes_bridge, "hermes_brain_settings", return_value={}
        ), patch.object(
            hermes_bridge,
            "inference_runtime_policy",
            return_value={"max_turns": 8, "disable_delegation": False},
        ), patch.object(
            hermes_bridge, "admira_inference_fallback_chain", return_value=[]
        ), patch.object(
            hermes_bridge, "hermes_environment", return_value={}
        ), patch.object(
            hermes_bridge, "hermes_prompt", return_value="system"
        ), patch.object(
            runtime, "_guard_unconfirmed_campaign_claim", side_effect=lambda value: value
        ), patch.object(
            runtime, "_guard_unconfirmed_campaign_edit_claim", side_effect=lambda value, **_kwargs: value
        ) as edit_guard:
            reply = hermes_bridge.library_chat(config, {"message": "hola", "channel": "telegram"})

        self.assertEqual(reply, original["final_response"])
        self.assertEqual(edit_guard.call_args.kwargs["buyer_message"], "hola")

    def test_library_chat_surfaces_failed_provider_result_as_an_exception(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        workspace = Path(temporary.name)
        failure = {
            "final_response": "API call failed after retries: Gemini quota exhausted",
            "messages": [],
            "completed": False,
            "failed": True,
            "error": "GeminiAPIError: HTTP 429 RESOURCE_EXHAUSTED",
            "failure_reason": "rate_limit",
        }

        class FakeAgent:
            def __init__(self, **_kwargs):
                pass

            def run_conversation(self, **_kwargs):
                return dict(failure)

        fake_run_agent = ModuleType("run_agent")
        fake_run_agent.AIAgent = FakeAgent
        config = SimpleNamespace(
            hermes_max_iterations=8,
            hermes_enabled_toolsets="",
            hermes_disabled_toolsets="",
        )
        with patch.dict(sys.modules, {"run_agent": fake_run_agent}), patch.object(
            hermes_bridge, "_record_bridge_trusted_buyer_turn", side_effect=lambda value: value
        ), patch.object(
            hermes_bridge,
            "prepare_hermes_workspace",
            return_value={"path": str(workspace), "files": [], "image_paths": []},
        ), patch.object(hermes_bridge, "hermes_brain_settings", return_value={}), patch.object(
            hermes_bridge,
            "inference_runtime_policy",
            return_value={"max_turns": 8, "disable_delegation": False},
        ), patch.object(hermes_bridge, "admira_inference_fallback_chain", return_value=[]), patch.object(
            hermes_bridge, "hermes_environment", return_value={}
        ), patch.object(hermes_bridge, "hermes_prompt", return_value="system"):
            with self.assertRaisesRegex(RuntimeError, "429.*RESOURCE_EXHAUSTED"):
                hermes_bridge.library_chat(config, {"message": "hola", "channel": "telegram"})

    def test_terminal_transaction_is_history_not_active_workflow(self):
        memory = {
            "business_profile": {},
            "brand_guides": {"general_branding": "", "ad_briefs": []},
            "recent_history": {},
            "transactional_workflow": {
                "type": "campaign_edit", "status": "failed",
                "edit_id": "edit-123",
                "campaign_id": "cmp-123", "account_id": "act-123",
                "blocker": "old failure",
            },
        }
        workflow = hermes_bridge.active_workflow_payload(memory, {"items": []})
        self.assertFalse(workflow["has_active_workflow"])
        self.assertEqual(workflow["phase"], "")

    def test_identity_bound_pending_transaction_is_active(self):
        memory = {
            "business_profile": {},
            "brand_guides": {"general_branding": "", "ad_briefs": []},
            "recent_history": {},
            "transactional_workflow": {
                "type": "campaign_edit", "status": "pending",
                "edit_id": "edit-123",
                "campaign_id": "cmp-123", "account_id": "act-123",
                "blocker": "awaiting readback",
            },
        }
        workflow = hermes_bridge.active_workflow_payload(memory, {"items": []})
        self.assertTrue(workflow["has_active_workflow"])
        self.assertEqual(workflow["phase"], "blocked_or_retrying")
        self.assertEqual(workflow["recent_blocker"]["campaign_id"], "cmp-123")

    def test_identity_bound_pending_transaction_without_error_is_not_a_blocker(self):
        memory = {
            "business_profile": {},
            "brand_guides": {"general_branding": "", "ad_briefs": []},
            "recent_history": {},
            "transactional_workflow": {
                "type": "campaign_edit", "status": "pending",
                "edit_id": "edit-456", "campaign_id": "cmp-456",
            },
        }
        workflow = hermes_bridge.active_workflow_payload(memory, {"items": []})
        self.assertTrue(workflow["has_active_workflow"])
        self.assertEqual(workflow["phase"], "campaign_transaction_pending")
        self.assertEqual(workflow["recent_blocker"], {})

    def test_admira_skill_unlock_block_is_suppressed_but_other_safety_blocks_survive(self):
        calls = []

        def original(tool_name, args, **kwargs):
            calls.append((tool_name, args, kwargs))
            if tool_name == "mcp_admira_save_business_memory":
                return "Read skills/business-onboarding/SKILL.md before retrying this tool."
            if tool_name == "mcp_admira_pause_campaign":
                return "Security policy blocked this destructive action."
            return "Read skills/example/SKILL.md before retrying this tool."

        fake_plugins = SimpleNamespace(get_pre_tool_call_block_message=original)
        fake_hermes = SimpleNamespace(plugins=fake_plugins)
        with patch.dict(sys.modules, {"hermes_cli": fake_hermes}):
            self.assertTrue(runtime._patch_mcp_primary_skill_gate())

        patched = fake_plugins.get_pre_tool_call_block_message
        self.assertIsNone(patched("mcp_admira_save_business_memory", {}))
        self.assertEqual(
            patched("mcp_admira_pause_campaign", {}),
            "Security policy blocked this destructive action.",
        )
        self.assertEqual(
            patched("read_file", {}),
            "Read skills/example/SKILL.md before retrying this tool.",
        )
        self.assertEqual(len(calls), 3)

    def test_native_clarify_is_removed_at_the_provider_boundary(self):
        request = runtime._remove_hermes_personal_state_tools({
            "tools": [
                self._tool("save_business_memory"),
                {"type": "function", "function": {"name": "clarify"}},
                {"type": "function", "function": {"name": "memory"}},
            ]
        })
        names = {
            runtime._nvidia_tool_name(tool)
            for tool in request["tools"]
        }
        self.assertIn("mcp_admira_save_business_memory", names)
        self.assertNotIn("clarify", names)
        self.assertNotIn("memory", names)

    def test_old_skill_and_mcp_outputs_are_compacted_after_next_buyer_turn(self):
        huge = json.dumps({"ok": True, "campaign_id": "123", "inventory": "x" * 5000})
        messages = [
            {"role": "assistant", "tool_calls": [{
                "id": "read-1",
                "function": {
                    "name": "read_file",
                    "arguments": json.dumps({"path": "skills/campaign-strategy/SKILL.md"}),
                },
            }]},
            {"role": "tool", "tool_call_id": "read-1", "content": "y" * 9000},
            {"role": "assistant", "tool_calls": [{
                "id": "mcp-1",
                "function": {"name": "mcp_admira_get_real_meta_context", "arguments": "{}"},
            }]},
            {"role": "tool", "tool_call_id": "mcp-1", "content": huge},
            {"role": "user", "content": "gracias"},
            {"role": "tool", "name": "mcp_admira_get_real_meta_context", "content": huge},
        ]
        compacted = runtime._admira_compact_consumed_observations(messages)
        self.assertLess(len(compacted[1]["content"]), 300)
        self.assertLess(len(compacted[3]["content"]), 300)
        self.assertEqual(compacted[5]["content"], huge)

    def test_all_conversation_transports_use_exact_buyer_text(self):
        message = "aproximadamente 40 mil pesos al día"
        for channel in ("telegram", "dashboard", "simulated_telegram"):
            self.assertEqual(
                hermes_bridge.hermes_user_query({"channel": channel, "message": message}, {}),
                message,
            )

    def test_real_telegram_turn_is_recorded_before_inference(self):
        calls = []

        class FakeAdapter:
            def _effective_update_message(self, update):
                return update.effective_message

            def _is_user_authorized_from_message(self, _message):
                return True

            async def _handle_text_message(self, _update, _context):
                self.assert_recorded_before_original = bool(calls)
                return "inference"

        def record_trusted_buyer_turn(**kwargs):
            calls.append(kwargs)

        message = SimpleNamespace(
            message_id=42,
            text="la cuenta DOrian2 y la página María Flores",
            chat=SimpleNamespace(id=123, type="private"),
            from_user=SimpleNamespace(id=456),
        )
        dashboard = SimpleNamespace(record_trusted_buyer_turn=record_trusted_buyer_turn)
        with patch.object(runtime, "_telegram_adapter_classes", return_value=[FakeAdapter]), \
                patch.object(runtime, "_admira_dashboard_module", return_value=dashboard), \
                patch.object(runtime, "_record_telegram_runtime_chat", return_value=True):
            self.assertTrue(runtime._patch_telegram_runtime_chat_capture())
            adapter = FakeAdapter()
            result = asyncio.run(adapter._handle_text_message(
                SimpleNamespace(effective_message=message, update_id=900), None
            ))

        self.assertEqual(result, "inference")
        self.assertTrue(adapter.assert_recorded_before_original)
        self.assertEqual(calls, [{
            "chat_id": "123",
            "session_id": "agent:main:telegram:dm:123",
            "message_sequence": 42,
            "raw_message": message.text,
            "transport": "telegram",
        }])

    def test_gateway_boundary_records_real_turn_when_adapter_loaded_late(self):
        calls = []

        class FakeRunner:
            def _is_user_authorized(self, _source):
                return True

            def _session_key_for_source(self, _source):
                return "agent:main:telegram:dm:123"

            async def _handle_message(self, _event):
                self.recorded_before_original = bool(calls)
                return "inference"

        gateway_package = ModuleType("gateway")
        gateway_run = ModuleType("gateway.run")
        gateway_run.GatewayRunner = FakeRunner
        gateway_package.run = gateway_run
        source = SimpleNamespace(
            chat_id="123",
            platform=SimpleNamespace(value="telegram"),
        )
        event = SimpleNamespace(
            text="mi marca se llama Sonrisa Clara",
            source=source,
            message_id="73",
            platform_update_id=900,
            internal=False,
        )
        with patch.dict(sys.modules, {"gateway": gateway_package, "gateway.run": gateway_run}), \
                patch.object(runtime, "_record_trusted_buyer_turn", side_effect=lambda **kwargs: calls.append(kwargs) or True):
            self.assertTrue(runtime._patch_gateway_chatgpt_slash_commands())
            runner = FakeRunner()
            result = asyncio.run(runner._handle_message(event))

        self.assertEqual(result, "inference")
        self.assertTrue(runner.recorded_before_original)
        self.assertEqual(calls[0]["raw_message"], event.text)
        self.assertEqual(calls[0]["message_sequence"], "73")
        self.assertEqual(calls[0]["transport"], "telegram")

    def test_initial_strategic_plan_compilation_skips_hermes_inference(self):
        class FakeRunner:
            async def _run_agent(self, *_args, **_kwargs):
                self.original_calls = getattr(self, "original_calls", 0) + 1
                return {"final_response": "Hermes improvised a shallow plan", "messages": []}

        gateway_package = ModuleType("gateway")
        gateway_run = ModuleType("gateway.run")
        gateway_run.GatewayRunner = FakeRunner
        gateway_package.run = gateway_run
        canonical = "Plan estratégico del negocio\n\n1. Diagnóstico\nPlan completo y fundamentado"

        with patch.dict(sys.modules, {"gateway": gateway_package, "gateway.run": gateway_run}), \
                patch.object(runtime, "_continuity_resume_hint", return_value=""), \
                patch.object(runtime, "_resolve_business_lifecycle_transition", return_value={}), \
                patch.object(runtime, "_ensure_initial_business_master_plan", return_value={
                    "ok": True,
                    "attempted": True,
                    "created": True,
                    "model": "gpt-5.6-sol",
                }) as ensure_plan, \
                patch.object(runtime, "_apply_authoritative_tool_result_guards", side_effect=lambda value: value), \
                patch.object(runtime, "_apply_conversational_output_guards", side_effect=lambda value: value), \
                patch.object(runtime, "_normalize_gateway_outbound_response", side_effect=lambda value: value), \
                patch.object(runtime, "_append_generated_media_attachments", side_effect=lambda value: value), \
                patch.object(runtime, "_admira_strategic_profile_state", return_value={
                    "complete": True,
                    "master_plan_status": "proposed",
                }), \
                patch.object(runtime, "_ensure_business_lifecycle_artifact_visible", return_value={"text": canonical}), \
                patch.object(runtime, "_record_business_lifecycle_artifact_presented", return_value=True), \
                patch.object(runtime, "_append_gateway_turn"):
            self.assertTrue(runtime._patch_gateway_generated_media_delivery())
            runner = FakeRunner()
            result = asyncio.run(runner._run_agent(
                "sí, el resumen está correcto",
                session_key="agent:main:telegram:dm:123",
                persist_user_message="sí, el resumen está correcto",
                source=SimpleNamespace(
                    chat_id="123",
                    platform=SimpleNamespace(value="telegram"),
                ),
                event_message_id=20,
            ))

        self.assertEqual(result["final_response"], canonical)
        self.assertEqual(getattr(runner, "original_calls", 0), 0)
        ensure_plan.assert_called_once_with(expected_turn={
            "chat_id": "123",
            "session_id": "agent:main:telegram:dm:123",
            "transport": "telegram",
            "raw_message": "sí, el resumen está correcto",
            "message_sequence": 20,
        })

    def test_blocked_image_receipt_cannot_be_narrated_as_queued(self):
        response = {
            "final_response": "Ya envié la orden. En un momento aparecerá la imagen.",
            "messages": [
                {"role": "user", "content": "crea la imagen"},
                {"role": "assistant", "tool_calls": [{"function": {"name": "mcp_admira_codex_image_generate"}}]},
                {"role": "tool", "content": json.dumps({
                    "type": "codex_image_generate",
                    "executed": False,
                    "blocked": True,
                    "reason": "creative_production_not_ready",
                    "error": "¿Qué colores debe respetar la marca?",
                }, ensure_ascii=False)},
            ],
        }
        guarded = runtime._apply_authoritative_tool_result_guards(response)
        self.assertIn("No se generó ni se envió", guarded["final_response"])
        self.assertIn("¿Qué colores debe respetar la marca?", guarded["final_response"])
        self.assertNotIn("aparecerá", guarded["final_response"])

    def test_private_blocked_image_receipt_overrides_assistant_text_and_media(self):
        response = {
            "final_response": "Aquí está el diseño.\nMEDIA:/app/output/codex-test/design.png",
            # This is the provider shape from the hosted incident: a current
            # assistant message exists, while the authoritative receipt is
            # attached separately after the model returns.
            "messages": [{"role": "assistant", "content": "Aquí está el diseño."}],
            runtime.ADMIRA_CURRENT_TURN_TOOL_RECEIPTS_KEY: [{
                "name": "mcp_admira_codex_image_generate",
                "content": json.dumps({
                    "type": "codex_image_generate",
                    "ok": False,
                    "blocked": True,
                    "executed": False,
                    "error": "Primero necesito la decisión de logo.",
                }, ensure_ascii=False),
            }],
        }
        guarded = runtime._apply_authoritative_tool_result_guards(response)
        self.assertIn("No se generó ni se envió", guarded["final_response"])
        self.assertIn("Primero necesito", guarded["final_response"])
        self.assertNotIn("MEDIA:", guarded["final_response"])

    def test_transport_success_does_not_count_as_durable_save(self):
        response = {
            "final_response": "Ya lo guardé.",
            "messages": [
                {"role": "user", "content": "mi color es azul"},
                {"role": "tool", "name": "mcp_admira_save_brand_memory", "content": json.dumps({
                    "ok": True,
                    "executed": True,
                    "result": {"saved": False, "draft": True, "reason": "missing_current_trusted_buyer_turn"},
                })},
            ],
        }
        self.assertFalse(runtime._has_confirmed_durable_save(response))

    def test_direct_bridge_turns_use_exact_text_and_transport_scopes(self):
        calls = []

        def recorder(**kwargs):
            calls.append(kwargs)
            return True

        with patch.object(runtime, "_record_trusted_buyer_turn", side_effect=recorder):
            dashboard_payload = hermes_bridge._record_bridge_trusted_buyer_turn({
                "channel": "dashboard",
                "session_key": "buyer-7",
                "message_sequence": 101,
                "message": "  la cuenta dos y la página uno  ",
            })
            simulated_payload = hermes_bridge._record_bridge_trusted_buyer_turn({
                "channel": "simulated_telegram",
                "session_key": "canary-case-3",
                "message_sequence": 202,
                "message": "usa DOrian2 con María Flores",
            })

        self.assertEqual(dashboard_payload["message_sequence"], 101)
        self.assertEqual(simulated_payload["message_sequence"], 202)
        self.assertEqual(calls, [
            {
                "chat_id": "dashboard:buyer-7",
                "session_id": "agent:main:dashboard:buyer-7",
                "message_sequence": 101,
                "raw_message": "  la cuenta dos y la página uno  ",
                "transport": "dashboard",
            },
            {
                "chat_id": "simulated_telegram:canary-case-3",
                "session_id": "agent:main:simulated_telegram:canary-case-3",
                "message_sequence": 202,
                "raw_message": "usa DOrian2 con María Flores",
                "transport": "simulated_telegram",
            },
        ])

    def test_direct_bridge_canonicalizes_and_records_profile_review(self):
        class FakeConfig:
            hermes_require_codex_auth = False
            hermes_use_python_library = False

        payload = {
            "channel": "telegram",
            "session_key": "agent:main:telegram:dm:123:g0",
            "message_sequence": 41,
            "message": "¿puedes revisar el resumen?",
            "language": "es",
            "_admira_trusted_session_id": "agent:main:legacy_telegram:agent:main:telegram:dm:123:g0",
            "_admira_trusted_chat_id": "legacy_telegram:agent:main:telegram:dm:123:g0",
        }
        canonical = "Resumen del negocio — revisión 1\n\n- Servicios y productos [confirmado]: restaurante"

        with patch.object(hermes_bridge, "_record_bridge_trusted_buyer_turn", side_effect=lambda value: value), \
                patch.object(hermes_bridge, "hermes_brain_settings", return_value={
                    "requires_codex_auth": False, "brain": "openai_codex", "model": "gpt-5.6-luna",
                }), \
                patch.object(hermes_bridge, "hermes_brain_ready", return_value=(True, "ready")), \
                patch.object(hermes_bridge, "cli_chat", return_value="Aquí está el resumen del negocio. ¿Lo confirmas?"), \
                patch.object(runtime, "_resolve_business_lifecycle_transition", return_value={}) as resolve, \
                patch.object(runtime, "_attach_current_turn_tool_receipts", side_effect=lambda value, _session: value), \
                patch.object(runtime, "_admira_strategic_profile_state", return_value={"complete": False}), \
                patch.object(runtime, "_ensure_business_lifecycle_artifact_visible", return_value={"text": canonical}) as ensure, \
                patch.object(runtime, "_record_business_lifecycle_artifact_presented", return_value=True) as record:
            result = hermes_bridge.chat(FakeConfig(), payload)

        self.assertTrue(result["ok"])
        self.assertEqual(result["reply"], canonical)
        resolve.assert_called_once_with(
            session_id=payload["_admira_trusted_session_id"],
            chat_id=payload["_admira_trusted_chat_id"],
            raw_message=payload["message"],
            target="",
        )
        ensure.assert_called_once_with(
            session_id=payload["_admira_trusted_session_id"],
            chat_id=payload["_admira_trusted_chat_id"],
            assistant_text="Aquí está el resumen del negocio. ¿Lo confirmas?",
            target="business_profile",
        )
        record.assert_called_once_with(
            session_id=payload["_admira_trusted_session_id"],
            chat_id=payload["_admira_trusted_chat_id"],
            assistant_text=canonical,
            target="business_profile",
        )

    def test_direct_bridge_resolves_confirmation_without_model_reinterpretation(self):
        class FakeConfig:
            hermes_require_codex_auth = False
            hermes_use_python_library = False

        payload = {
            "channel": "telegram",
            "session_key": "agent:main:telegram:dm:123:g0",
            "message_sequence": 42,
            "message": "sí, confirmo el resumen",
            "language": "es",
            "_admira_trusted_session_id": "agent:main:legacy_telegram:agent:main:telegram:dm:123:g0",
            "_admira_trusted_chat_id": "legacy_telegram:agent:main:telegram:dm:123:g0",
        }
        canonical = "Propuesta inicial de anuncios\n\n1. Diagnóstico\nPlan completo"

        with patch.object(hermes_bridge, "_record_bridge_trusted_buyer_turn", side_effect=lambda value: value), \
                patch.object(hermes_bridge, "hermes_brain_settings", return_value={
                    "requires_codex_auth": False, "brain": "openai_codex", "model": "gpt-5.6-luna",
                }), \
                patch.object(hermes_bridge, "hermes_brain_ready", return_value=(True, "ready")), \
                patch.object(hermes_bridge, "cli_chat") as cli, \
                patch.object(runtime, "_resolve_business_lifecycle_transition", return_value={
                    "transitioned": True, "target": "business_profile",
                }), \
                patch.object(runtime, "_ensure_initial_business_master_plan", return_value={
                    "ok": True, "attempted": True, "created": True,
                }) as ensure_plan, \
                patch.object(runtime, "_attach_current_turn_tool_receipts", side_effect=lambda value, _session: value), \
                patch.object(runtime, "_admira_strategic_profile_state", return_value={
                    "complete": True, "master_plan_status": "proposed",
                }), \
                patch.object(runtime, "_ensure_business_lifecycle_artifact_visible", return_value={"text": canonical}), \
                patch.object(runtime, "_record_business_lifecycle_artifact_presented", return_value=True):
            result = hermes_bridge.chat(FakeConfig(), payload)

        self.assertTrue(result["ok"])
        self.assertEqual(result["reply"], canonical)
        cli.assert_not_called()
        ensure_plan.assert_called_once_with(expected_turn={
            "chat_id": payload["_admira_trusted_chat_id"],
            "session_id": payload["_admira_trusted_session_id"],
            "transport": "legacy_telegram",
            "raw_message": payload["message"],
            "message_sequence": 42,
        })

    def test_direct_bridge_removes_unverified_profile_save_claim(self):
        class FakeConfig:
            hermes_require_codex_auth = False
            hermes_use_python_library = False

        payload = {
            "channel": "telegram",
            "session_key": "agent:main:telegram:dm:123:g0",
            "message_sequence": 43,
            "message": "sí",
            "language": "es",
            "_admira_trusted_session_id": "agent:main:legacy_telegram:agent:main:telegram:dm:123:g0",
            "_admira_trusted_chat_id": "legacy_telegram:agent:main:telegram:dm:123:g0",
        }

        with patch.object(hermes_bridge, "_record_bridge_trusted_buyer_turn", side_effect=lambda value: value), \
                patch.object(hermes_bridge, "hermes_brain_settings", return_value={
                    "requires_codex_auth": False, "brain": "openai_codex", "model": "gpt-5.6-luna",
                }), \
                patch.object(hermes_bridge, "hermes_brain_ready", return_value=(True, "ready")), \
                patch.object(hermes_bridge, "cli_chat", return_value="El perfil quedó oficialmente confirmado y guardado."), \
                patch.object(runtime, "_resolve_business_lifecycle_transition", return_value={}), \
                patch.object(runtime, "_attach_current_turn_tool_receipts", side_effect=lambda value, _session: value), \
                patch.object(runtime, "_admira_strategic_profile_state", return_value={"complete": False}), \
                patch.object(runtime, "_ensure_business_lifecycle_artifact_visible", side_effect=lambda **kwargs: {"text": kwargs["assistant_text"]}), \
                patch.object(runtime, "_record_business_lifecycle_artifact_presented", return_value=False):
            result = hermes_bridge.chat(FakeConfig(), payload)

        self.assertTrue(result["ok"])
        self.assertNotIn("guardado", result["reply"].lower())
        self.assertNotIn("oficialmente confirmado", result["reply"].lower())

    def test_prompts_require_onboarding_without_campaign_first_option(self):
        english = hermes_gateway.gateway_prompt("en")
        spanish = hermes_gateway.gateway_prompt("es")
        self.assertIn("strategic business onboarding is mandatory", english)
        self.assertIn("only the confirmed current revision is complete", english)
        self.assertIn("complete the full Page-scoped strategic profile -> present and confirm its current review", english)
        self.assertNotIn("starting with one concrete campaign", english)
        self.assertNotIn("campaign-first path", english)
        self.assertIn("el onboarding estratégico es obligatorio", spanish)
        self.assertIn("solo la revisión actual confirmada queda completa", spanish)
        self.assertIn("completar el perfil estratégico íntegro asociado a esa Página -> presentar y confirmar su revisión actual", spanish)

    def test_provider_turn_budget_is_eight(self):
        for brain in (
            {"brain": "gemini", "provider": "google-ai-studio", "model": "gemini-3.5-flash-lite"},
            {"brain": "openai_codex", "provider": "openai-codex", "model": "gpt-5.6-terra"},
            {"brain": "nvidia_nim", "provider": "admira-nvidia", "model": "x"},
        ):
            self.assertEqual(hermes_bridge.inference_runtime_policy(brain)["max_turns"], 8)


if __name__ == "__main__":
    unittest.main()
