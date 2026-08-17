import json
import tempfile
import time
import unittest
from pathlib import Path

import admira_hermes_runtime_patch
import hermes_bridge
import hermes_gateway
import product_config


class NvidiaInferencePolicyTests(unittest.TestCase):
    @staticmethod
    def _admira_tool(name):
        return {"type": "function", "function": {"name": f"mcp_admira_{name}", "description": name}}

    def test_nvidia_profile_matrix_routes_only_needed_product_tools(self):
        """Every common workflow gets a bounded, purpose-specific registry."""
        all_names = sorted(set().union(*admira_hermes_runtime_patch.ADMIRA_NVIDIA_TOOL_PROFILES.values()))
        tools = [self._admira_tool(name) for name in all_names]
        tools.extend([
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "memory_search"}},
            {"type": "function", "function": {"name": "web_search"}},
            {"type": "function", "function": {"name": "vision_analyze"}},
        ])
        cases = (
            ("onboarding", "Es mi primera conversación: mi negocio es una clínica y quiero reservas", 8192, "save_agent_preferences"),
            ("metrics", "Revisa las métricas, gasto, CTR y compras de la campaña", 8192, "get_real_meta_context"),
            ("campaign_strategy", "Recomienda la audiencia, ubicaciones e intereses para mi campaña", 8192, "search_meta_targeting"),
            ("campaign_execution", "Prepara la campaña de ventas pausada con los creativos aprobados", 8192, "stage_campaign"),
            ("messaging_campaign", "Crea una campaña de WhatsApp con el mensaje inicial aprobado", 8192, "stage_campaign"),
            ("campaign_media", "Crea dos imágenes Image 2 para la campaña que vamos a lanzar", 12288, "codex_image_generate"),
            ("lead_form", "Necesito crear un formulario nativo de leads para mi página", 8192, "create_lead_form"),
            ("creative", "Crea un video con storyboard, recetas e Image 2 para este producto", 12288, "generate_motion_graphic_video"),
            ("organic", "Prepara una publicación orgánica para Facebook y déjala en borrador", 12288, "stage_organic_social_post"),
            ("organic_en", "Create an organic social media post and leave it as a draft", 12288, "stage_organic_social_post"),
            ("catalog", "Importa el catálogo, busca productos y arma un bundle", 8192, "import_product_catalog"),
        )
        native_names = {"read_file", "memory_search", "web_search", "vision_analyze"}
        for expected_profile, prompt, max_tokens, expected_tool in cases:
            with self.subTest(profile=expected_profile):
                prepared = admira_hermes_runtime_patch._nvidia_prepare_request({
                    "messages": [{"role": "user", "content": prompt}],
                    "tools": tools,
                    "max_tokens": 65536,
                })
                names = {
                    admira_hermes_runtime_patch._nvidia_normalize_tool_name(
                        admira_hermes_runtime_patch._nvidia_tool_name(item)
                    )
                    for item in prepared.get("tools", [])
                }
                self.assertEqual(prepared["max_tokens"], max_tokens)
                if expected_tool:
                    self.assertIn(expected_tool, names)
                if expected_profile == "lead_form":
                    self.assertEqual(names, {"create_lead_form", "list_lead_forms"})
                else:
                    self.assertTrue(native_names.issubset(names))
                self.assertLess(len(names), len(all_names) + len(native_names))
                self.assertLessEqual(
                    admira_hermes_runtime_patch._nvidia_estimated_input_tokens(
                        prepared["messages"], prepared.get("tools", [])
                    ),
                    admira_hermes_runtime_patch.ADMIRA_NVIDIA_INPUT_BUDGET_TOKENS,
                )

    def test_nvidia_onboarding_profile_excludes_campaign_and_creative_tools(self):
        all_names = sorted(set().union(*admira_hermes_runtime_patch.ADMIRA_NVIDIA_TOOL_PROFILES.values()))
        prepared = admira_hermes_runtime_patch._nvidia_prepare_request({
            "messages": [{"role": "user", "content": "Primera conversación: mi negocio ofrece estética facial en Medellín y quiero reservas."}],
            "tools": [self._admira_tool(name) for name in all_names],
            "max_tokens": 65536,
        })
        names = {
            admira_hermes_runtime_patch._nvidia_normalize_tool_name(
                admira_hermes_runtime_patch._nvidia_tool_name(item)
            )
            for item in prepared.get("tools", [])
        }
        self.assertEqual(names, {"save_agent_preferences", "get_meta_oauth_workspaces", "start_meta_oauth_connection", "select_meta_oauth_workspace"})
        self.assertNotIn("stage_campaign", names)
        self.assertNotIn("codex_image_generate", names)

    def test_nvidia_lead_form_profile_excludes_unrelated_campaign_and_creative_tools(self):
        """A native form turn must not carry the whole campaign/media registry."""
        all_names = sorted(set().union(*admira_hermes_runtime_patch.ADMIRA_NVIDIA_TOOL_PROFILES.values()))
        tools = [self._admira_tool(name) for name in all_names]
        tools.extend([
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "memory_search"}},
        ])
        prepared = admira_hermes_runtime_patch._nvidia_prepare_request({
            "messages": [{"role": "user", "content": "Crea el formulario instantáneo de leads con las preguntas que aprobamos"}],
            "tools": tools,
            "max_tokens": 65536,
        })
        names = {
            admira_hermes_runtime_patch._nvidia_normalize_tool_name(
                admira_hermes_runtime_patch._nvidia_tool_name(item)
            )
            for item in prepared.get("tools", [])
        }
        self.assertIn("create_lead_form", names)
        self.assertIn("list_lead_forms", names)
        self.assertNotIn("stage_campaign", names)
        self.assertNotIn("codex_image_generate", names)
        self.assertNotIn("generate_motion_graphic_video", names)
        self.assertEqual(names, {"create_lead_form", "list_lead_forms"})

    def test_nvidia_campaign_subprofiles_do_not_leak_unrelated_mutations_or_media(self):
        """Campaign wording must not re-expand to the old all-in-one registry."""
        all_names = sorted(set().union(*admira_hermes_runtime_patch.ADMIRA_NVIDIA_TOOL_PROFILES.values()))
        tools = [self._admira_tool(name) for name in all_names]
        tools.extend([
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "memory_search"}},
        ])
        cases = (
            (
                "Recomienda la segmentación, ciudades e intereses para mi campaña.",
                {"search_meta_targeting"},
                {"stage_campaign", "delete_campaign", "codex_image_generate", "create_lead_form"},
            ),
            (
                "Crea la campaña pausada con los anuncios y creativos ya aprobados.",
                {"stage_campaign", "pause_campaign"},
                {"codex_image_generate", "generate_motion_graphic_video", "create_lead_form"},
            ),
            (
                "Prepara la campaña de WhatsApp con el mensaje inicial aprobado.",
                {"stage_campaign"},
                {"delete_campaign", "codex_image_generate", "create_lead_form"},
            ),
            (
                "Genera dos imágenes con Image 2 para la campaña de lanzamiento.",
                {"codex_image_generate", "codex_creative_plan"},
                {"stage_campaign", "delete_campaign", "create_lead_form"},
            ),
        )
        for prompt, expected, forbidden in cases:
            with self.subTest(prompt=prompt):
                prepared = admira_hermes_runtime_patch._nvidia_prepare_request({
                    "messages": [{"role": "user", "content": prompt}],
                    "tools": tools,
                    "max_tokens": 65536,
                })
                names = {
                    admira_hermes_runtime_patch._nvidia_normalize_tool_name(
                        admira_hermes_runtime_patch._nvidia_tool_name(item)
                    )
                    for item in prepared.get("tools", [])
                }
                self.assertTrue(expected.issubset(names))
                self.assertTrue(names.isdisjoint(forbidden))
                # Two Hermes-native tools remain. Every product profile stays
                # far below the previous 42-tool campaign payload.
                self.assertLessEqual(len(names), 20)

    def test_nvidia_profile_ignores_system_capability_words_but_keeps_active_tool_error(self):
        system = {
            "role": "system",
            "content": "Admira puede crear contenido orgánico, publicaciones, videos y formularios.",
        }
        self.assertEqual(
            admira_hermes_runtime_patch._nvidia_request_profile([
                system,
                {"role": "user", "content": "Recomienda audiencia, ciudades e intereses para mi campaña."},
            ]),
            "campaign_strategy",
        )
        self.assertEqual(
            admira_hermes_runtime_patch._nvidia_request_profile([
                system,
                {"role": "user", "content": "Crea el formulario de leads con los datos confirmados."},
                {"role": "assistant", "tool_calls": [{"function": {"name": "mcp_admira_create_lead_form"}}]},
                {"role": "tool", "name": "mcp_admira_create_lead_form", "content": "missing_lead_form_detail"},
            ]),
            "lead_form",
        )

    def test_nvidia_profile_stays_on_buyer_intent_after_live_meta_tool_result(self):
        messages = [
            {
                "role": "user",
                "content": "Consulta Meta en vivo y dime la cuenta, página y cuántas campañas activas hay.",
            },
            {
                "role": "assistant",
                "tool_calls": [{"function": {"name": "mcp_admira_get_real_meta_context"}}],
            },
            {
                "role": "tool",
                "name": "mcp_admira_get_real_meta_context",
                "content": "Campañas pausadas con creativos de imagen, video y formularios disponibles.",
            },
        ]
        self.assertEqual(
            admira_hermes_runtime_patch._nvidia_request_profile(messages),
            "insights",
        )
        self.assertNotIn(
            "creativos de imagen",
            admira_hermes_runtime_patch._nvidia_routing_text(messages),
        )

    def test_nvidia_lead_form_retry_injects_no_empty_arguments_rule(self):
        prepared = admira_hermes_runtime_patch._nvidia_prepare_request({
            "messages": [
                {"role": "tool", "name": "mcp_admira_create_lead_form", "content": '{"reason":"missing_lead_form_detail","missing":["name"]}'},
                {"role": "user", "content": "Inténtalo de nuevo"},
            ],
            "tools": [
                self._admira_tool("create_lead_form"),
                self._admira_tool("stage_campaign"),
            ],
            "max_tokens": 65536,
        })
        text = "\n".join(str(message.get("content") or "") for message in prepared["messages"])
        self.assertIn("Never call it with {}", text)
        self.assertIn("Do not inspect files", text)
        names = {
            admira_hermes_runtime_patch._nvidia_normalize_tool_name(
                admira_hermes_runtime_patch._nvidia_tool_name(item)
            )
            for item in prepared.get("tools", [])
        }
        self.assertIn("create_lead_form", names)
        self.assertNotIn("stage_campaign", names)

    def test_nvidia_lead_form_tool_loop_cannot_repeat_the_mutation(self):
        prepared = admira_hermes_runtime_patch._nvidia_prepare_request({
            "messages": [
                {"role": "user", "content": "Crea el formulario de leads con los datos confirmados."},
                {"role": "assistant", "tool_calls": [{
                    "function": {"name": "mcp_admira_create_lead_form", "arguments": "{}"},
                }]},
                {"role": "tool", "name": "mcp_admira_create_lead_form", "content": '{"reason":"empty_tool_arguments"}'},
            ],
            "tools": [self._admira_tool("create_lead_form")],
            "max_tokens": 65536,
        })
        self.assertEqual(prepared["tool_choice"], "none")

    def test_nvidia_explicit_lead_form_creation_requires_the_one_function(self):
        prepared = admira_hermes_runtime_patch._nvidia_prepare_request({
            "messages": [{
                "role": "user",
                "content": "Crea el formulario de leads con nombre, preguntas y URL ya confirmados.",
            }],
            "tools": [
                self._admira_tool("create_lead_form"),
                self._admira_tool("list_lead_forms"),
                {"type": "function", "function": {"name": "read_file"}},
            ],
            "max_tokens": 65536,
        })
        self.assertEqual(
            prepared["tool_choice"],
            {
                "type": "function",
                "function": {"name": "mcp_admira_create_lead_form"},
            },
        )
        self.assertFalse(prepared["parallel_tool_calls"])
        create_tool = next(
            item for item in prepared.get("tools", [])
            if admira_hermes_runtime_patch._nvidia_normalize_tool_name(
                admira_hermes_runtime_patch._nvidia_tool_name(item)
            ) == "create_lead_form"
        )
        parameters = create_tool["function"]["parameters"]
        self.assertEqual(
            parameters["required"],
            ["page_id", "name", "questions", "privacy_policy_url"],
        )
        self.assertIn("questions", parameters["properties"])

    def test_nvidia_restores_empty_hermes_mcp_parameters_without_mutating_registry(self):
        original = self._admira_tool("create_lead_form")
        original["function"]["parameters"] = {"type": "object", "additionalProperties": True}
        restored = admira_hermes_runtime_patch._nvidia_restore_admira_tool_schemas([original])
        self.assertEqual(original["function"]["parameters"].get("properties"), None)
        self.assertIn("page_id", restored[0]["function"]["parameters"]["properties"])
        self.assertIn("questions", restored[0]["function"]["parameters"]["required"])

    def test_nvidia_plain_lead_form_advice_does_not_force_creation(self):
        prepared = admira_hermes_runtime_patch._nvidia_prepare_request({
            "messages": [{"role": "user", "content": "¿Qué preguntas recomiendas para mi formulario de leads?"}],
            "tools": [self._admira_tool("create_lead_form")],
            "max_tokens": 65536,
        })
        self.assertNotIn("tool_choice", prepared)

    def test_nvidia_tool_continuity_keeps_only_an_active_loop_not_history(self):
        active = [
            {"role": "user", "content": "Crea la campaña"},
            {"role": "assistant", "tool_calls": [{"function": {"name": "mcp_admira_stage_campaign"}}]},
            {"role": "tool", "name": "mcp_admira_stage_campaign", "content": "{\"ok\": false}"},
        ]
        self.assertEqual(
            admira_hermes_runtime_patch._nvidia_used_tool_names(active),
            {"stage_campaign"},
        )
        next_buyer_turn = active + [{"role": "user", "content": "Ahora revisa el rendimiento"}]
        self.assertEqual(admira_hermes_runtime_patch._nvidia_used_tool_names(next_buyer_turn), set())

    def test_nvidia_default_is_minimax_m3_and_legacy_glm_migrates_only_when_untouched(self):
        self.assertEqual(product_config.DEFAULT_NVIDIA_NIM_MODEL, "minimaxai/minimax-m3")
        self.assertEqual(
            product_config.normalize_nvidia_model("z-ai/glm-5.2"),
            "minimaxai/minimax-m3",
        )
        self.assertEqual(
            product_config.normalize_nvidia_model("z-ai/glm-5.2", user_selected=True),
            "z-ai/glm-5.2",
        )

    def test_nvidia_fallback_preference_keeps_m3_first_and_uses_live_ids(self):
        models = [
            "z-ai/glm-5.2",
            "deepseek-ai/deepseek-v4-flash-0731",
            "openai/gpt-oss-20b",
            "minimaxai/minimax-m3",
        ]
        ordered = hermes_bridge._nvidia_model_specific_fallback_order(models, "minimaxai/minimax-m3")
        self.assertEqual(
            ordered,
            ["deepseek-ai/deepseek-v4-flash-0731", "openai/gpt-oss-20b", "z-ai/glm-5.2"],
        )

    def test_nvidia_uses_one_attempt_and_serial_crons(self):
        policy = hermes_bridge.inference_runtime_policy({
            "brain": "nvidia_nim",
            "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
            "model": "z-ai/glm-5.2",
        })
        self.assertEqual(policy["api_max_retries"], 0)
        self.assertEqual(policy["max_turns"], 10)
        self.assertEqual(policy["cron_max_parallel"], 1)
        self.assertEqual(policy["model_context_length"], 80000)
        self.assertEqual(policy["compression_threshold"], 0.45)
        self.assertEqual(policy["compression_hard_message_limit"], 24)
        self.assertEqual(policy["compression_provider"], "custom")
        self.assertEqual(policy["compression_abort_on_failure"], False)
        self.assertEqual(policy["compression_timeout"], 45)
        self.assertEqual(policy["compression_base_url"], hermes_bridge.ADMIRA_NVIDIA_DEFAULT_BASE_URL)
        self.assertEqual(policy["context_file_max_chars"], 30000)
        self.assertEqual(policy["requests_per_minute"], 36)
        self.assertEqual(policy["min_request_interval_seconds"], 1.7)
        self.assertEqual(policy["stream_retries"], 0)

    def test_nvidia_auxiliary_session_titles_are_suppressed_without_affecting_other_providers(self):
        import sys
        import types

        calls = []
        original_module = sys.modules.get("agent.title_generator")
        module = types.ModuleType("agent.title_generator")

        def native(*args, **kwargs):
            calls.append((args, kwargs))
            return "native-title"

        module.maybe_auto_title = native
        sys.modules["agent.title_generator"] = module
        try:
            self.assertTrue(admira_hermes_runtime_patch._patch_nvidia_auxiliary_title_generation())
            self.assertIsNone(module.maybe_auto_title(main_runtime={
                "provider": "admira-nvidia",
                "base_url": "https://integrate.api.nvidia.com/v1",
            }))
            self.assertEqual(calls, [])
            self.assertEqual(
                module.maybe_auto_title(main_runtime={"provider": "openai-codex"}),
                "native-title",
            )
            self.assertEqual(len(calls), 1)
        finally:
            if original_module is None:
                sys.modules.pop("agent.title_generator", None)
            else:
                sys.modules["agent.title_generator"] = original_module

    def test_nvidia_request_gate_records_only_bounded_request_timestamps(self):
        import nvidia_request_gate

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gate.json"
            old_path = nvidia_request_gate.os.environ.get("ADMIRA_NVIDIA_RATE_LIMIT_STATE")
            old_interval = nvidia_request_gate.os.environ.get("ADMIRA_NVIDIA_MIN_REQUEST_INTERVAL_SECONDS")
            try:
                nvidia_request_gate.os.environ["ADMIRA_NVIDIA_RATE_LIMIT_STATE"] = str(path)
                nvidia_request_gate.os.environ["ADMIRA_NVIDIA_MIN_REQUEST_INTERVAL_SECONDS"] = "0.01"
                self.assertEqual(
                    nvidia_request_gate.acquire_request(provider="admira-nvidia", now_fn=lambda: 100.0),
                    0.0,
                )
                self.assertEqual(nvidia_request_gate.recent_request_count(now_fn=lambda: 100.0), 1)
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertNotIn("api_key", payload)
                self.assertNotIn("messages", payload)
            finally:
                if old_path is None:
                    nvidia_request_gate.os.environ.pop("ADMIRA_NVIDIA_RATE_LIMIT_STATE", None)
                else:
                    nvidia_request_gate.os.environ["ADMIRA_NVIDIA_RATE_LIMIT_STATE"] = old_path
                if old_interval is None:
                    nvidia_request_gate.os.environ.pop("ADMIRA_NVIDIA_MIN_REQUEST_INTERVAL_SECONDS", None)
                else:
                    nvidia_request_gate.os.environ["ADMIRA_NVIDIA_MIN_REQUEST_INTERVAL_SECONDS"] = old_interval

    def test_nvidia_hook_diagnostic_is_redacted_and_never_serializes_request_content(self):
        class NvidiaAgent:
            provider = "custom"
            base_url = "https://integrate.api.nvidia.com/v1"

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hook.jsonl"
            previous = admira_hermes_runtime_patch.os.environ.get("ADMIRA_NVIDIA_HOOK_DIAGNOSTICS_FILE")
            try:
                admira_hermes_runtime_patch.os.environ["ADMIRA_NVIDIA_HOOK_DIAGNOSTICS_FILE"] = str(path)
                admira_hermes_runtime_patch._record_nvidia_hook_diagnostic(
                    NvidiaAgent(),
                    {
                        "messages": [{"role": "user", "content": "private buyer message"}],
                        "api_key": "secret",
                        "tools": [],
                        "max_tokens": 8192,
                    },
                    path="agent_stream",
                    is_nvidia=True,
                    prepared_profile="campaign_strategy",
                    tools_before=42,
                )
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(payload["path"], "agent_stream")
                self.assertTrue(payload["is_nvidia"])
                self.assertTrue(payload["base_url_is_nvidia"])
                self.assertTrue(payload["request_is_mapping"])
                self.assertTrue(payload["prepared"])
                self.assertEqual(payload["profile"], "campaign_strategy")
                self.assertEqual(payload["tools_before"], 42)
                self.assertEqual(payload["tools_after"], 0)
                self.assertEqual(payload["tool_schema_summaries"], [])
                self.assertNotIn("messages", payload)
                self.assertNotIn("api_key", payload)
                self.assertNotIn("private buyer message", json.dumps(payload))
            finally:
                if previous is None:
                    admira_hermes_runtime_patch.os.environ.pop("ADMIRA_NVIDIA_HOOK_DIAGNOSTICS_FILE", None)
                else:
                    admira_hermes_runtime_patch.os.environ["ADMIRA_NVIDIA_HOOK_DIAGNOSTICS_FILE"] = previous

    def test_nvidia_request_preflight_routes_only_relevant_admira_tools(self):
        def tool(name):
            return {"type": "function", "function": {"name": f"mcp_admira_{name}", "description": name}}

        original = {
            "model": "minimaxai/minimax-m3",
            "messages": [{"role": "user", "content": "Dame las métricas y el gasto de la campaña"}],
            "tools": [
                tool("get_real_meta_context"),
                tool("run_daily_brief"),
                tool("stage_campaign"),
                tool("codex_image_generate"),
                {"type": "function", "function": {"name": "read_file"}},
            ],
            "max_tokens": 65536,
        }
        prepared = admira_hermes_runtime_patch._nvidia_prepare_request(original)
        names = {admira_hermes_runtime_patch._nvidia_normalize_tool_name(
            admira_hermes_runtime_patch._nvidia_tool_name(item)
        ) for item in prepared.get("tools", [])}
        self.assertEqual(original["max_tokens"], 65536)
        self.assertEqual(prepared["max_tokens"], 8192)
        self.assertIn("get_real_meta_context", names)
        self.assertIn("run_daily_brief", names)
        self.assertNotIn("stage_campaign", names)
        self.assertNotIn("codex_image_generate", names)
        self.assertIn("read_file", names)

    def test_nvidia_creative_preflight_keeps_video_tools_with_bounded_output(self):
        def tool(name):
            return {"type": "function", "function": {"name": f"mcp_admira_{name}"}}

        prepared = admira_hermes_runtime_patch._nvidia_prepare_request({
            "messages": [{"role": "user", "content": "Crea un video educativo con Image 2"}],
            "tools": [
                tool("get_real_meta_context"),
                tool("generate_motion_graphic_video"),
                tool("codex_image_generate"),
                tool("stage_campaign"),
            ],
            "max_tokens": 65536,
        })
        names = {admira_hermes_runtime_patch._nvidia_normalize_tool_name(
            admira_hermes_runtime_patch._nvidia_tool_name(item)
        ) for item in prepared.get("tools", [])}
        self.assertEqual(prepared["max_tokens"], 12288)
        self.assertIn("generate_motion_graphic_video", names)
        self.assertIn("codex_image_generate", names)
        self.assertNotIn("stage_campaign", names)

    def test_nvidia_preflight_caps_plain_requests_without_tools(self):
        prepared = admira_hermes_runtime_patch._nvidia_prepare_request({
            "messages": [{"role": "user", "content": "Responde brevemente"}],
            "max_tokens": 65536,
        })
        self.assertEqual(prepared["max_tokens"], 8192)

    def test_nvidia_preflight_compacts_complete_payload_when_tools_push_it_over_budget(self):
        messages = [{"role": "system", "content": "system"}]
        messages.extend({"role": "user", "content": "x" * 30000} for _ in range(10))
        messages.append({"role": "user", "content": "latest"})
        prepared = admira_hermes_runtime_patch._nvidia_prepare_request({
            "messages": messages,
            "tools": [{"type": "function", "function": {"name": "read_file"}}],
            "max_tokens": 65536,
        })
        self.assertLess(len(prepared["messages"]), len(messages))
        self.assertEqual(prepared["messages"][0]["role"], "system")
        self.assertEqual(prepared["messages"][-1]["content"], "latest")
        self.assertLessEqual(
            admira_hermes_runtime_patch._nvidia_estimated_input_tokens(
                prepared["messages"], prepared.get("tools", [])
            ),
            admira_hermes_runtime_patch.ADMIRA_NVIDIA_INPUT_BUDGET_TOKENS,
        )

    def test_nvidia_hard_budget_holds_for_single_opaque_large_turn(self):
        prepared = admira_hermes_runtime_patch._nvidia_prepare_request({
            "messages": [{"role": "system", "content": "S" * 250000}, {"role": "user", "content": "U" * 250000}],
            "tools": [self._admira_tool("get_real_meta_context")],
            "max_tokens": 100000,
        })
        self.assertLessEqual(
            admira_hermes_runtime_patch._nvidia_estimated_input_tokens(
                prepared["messages"], prepared.get("tools", [])
            ),
            admira_hermes_runtime_patch.ADMIRA_NVIDIA_INPUT_BUDGET_TOKENS,
        )
        self.assertLessEqual(prepared["max_tokens"], 12288)

    def test_nvidia_request_diagnostics_redact_payload_and_record_counts(self):
        def tool(name):
            return {"type": "function", "function": {"name": f"mcp_admira_{name}"}}

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nvidia.jsonl"
            old = admira_hermes_runtime_patch.os.environ.get("ADMIRA_NVIDIA_REQUEST_DIAGNOSTICS_FILE")
            try:
                admira_hermes_runtime_patch.os.environ["ADMIRA_NVIDIA_REQUEST_DIAGNOSTICS_FILE"] = str(path)
                admira_hermes_runtime_patch._nvidia_prepare_request({
                    "model": "minimaxai/minimax-m3",
                    "messages": [{"role": "user", "content": "hola"}],
                    "tools": [tool("get_real_meta_context"), tool("stage_campaign")],
                    "max_tokens": 65536,
                })
                record = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
                self.assertEqual(record["tools_before"], 2)
                self.assertEqual(record["tools_after"], 1)
                self.assertEqual(record["max_tokens_before"], 65536)
                self.assertEqual(record["max_tokens_after"], 8192)
                self.assertEqual(record["input_budget_tokens"], admira_hermes_runtime_patch.ADMIRA_NVIDIA_INPUT_BUDGET_TOKENS)
                self.assertLessEqual(record["estimated_input_tokens"], record["input_budget_tokens"])
                self.assertNotIn("content", record)
                self.assertNotIn("api_key", record)
            finally:
                if old is None:
                    admira_hermes_runtime_patch.os.environ.pop("ADMIRA_NVIDIA_REQUEST_DIAGNOSTICS_FILE", None)
                else:
                    admira_hermes_runtime_patch.os.environ["ADMIRA_NVIDIA_REQUEST_DIAGNOSTICS_FILE"] = old

    def test_nvidia_compression_uses_compatible_custom_endpoint_and_safe_fallback(self):
        policy = hermes_bridge.inference_runtime_policy({
            "brain": "nvidia_nim",
            "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
            "model": "z-ai/glm-5.2",
            "base_url": hermes_bridge.ADMIRA_NVIDIA_DEFAULT_BASE_URL,
        })
        original_chain = hermes_bridge.admira_inference_fallback_chain
        try:
            hermes_bridge.admira_inference_fallback_chain = lambda _config, _brain: [
                {"provider": "admira-minimax", "model": "MiniMax-M3"},
                {"provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER, "model": "meta/llama"},
            ]
            lines = hermes_bridge.hermes_compression_config_lines(object(), {
                "brain": "nvidia_nim",
                "model": "z-ai/glm-5.2",
                "base_url": hermes_bridge.ADMIRA_NVIDIA_DEFAULT_BASE_URL,
            }, policy)
            text = "\n".join(lines)
            self.assertIn('abort_on_summary_failure: false', text)
            self.assertIn('provider: "custom"', text)
            self.assertIn('base_url: "https://integrate.api.nvidia.com/v1"', text)
            self.assertIn('fallback_chain:', text)
            self.assertIn('provider: "admira-minimax"', text)
            self.assertNotIn('meta/llama', text)
        finally:
            hermes_bridge.admira_inference_fallback_chain = original_chain

    def test_nvidia_model_config_has_operational_context_cap(self):
        policy = hermes_bridge.inference_runtime_policy({"brain": "nvidia_nim"})
        brain = {
            "brain": "nvidia_nim",
            "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
            "model": "z-ai/glm-5.2",
            "base_url": hermes_bridge.ADMIRA_NVIDIA_DEFAULT_BASE_URL,
            "context_length": policy["model_context_length"],
        }
        bridge_config = "\n".join(hermes_bridge._hermes_model_config_lines(brain))
        gateway_config = "\n".join(hermes_gateway._gateway_model_config_lines(brain))
        self.assertIn("context_length: 80000", bridge_config)
        self.assertIn("context_length: 80000", gateway_config)

    def test_nvidia_root_agent_profile_fits_without_hermes_truncation(self):
        """Specialist skills must remain reachable before the first tool call."""
        profile = hermes_bridge.combined_agent_rules()
        policy = hermes_bridge.inference_runtime_policy({"brain": "nvidia_nim"})
        self.assertLessEqual(len(profile), policy["context_file_max_chars"])
        self.assertIn("mcp_admira_generate_motion_graphic_video", profile)
        self.assertIn("skills/core-agent-behavior", profile)

    def test_nvidia_config_rewrites_retired_deepseek_fallback(self):
        config_text = """
mcp_servers:\n  admira:\n    command: admira_mcp_server.py
creation_nudge_interval: 0
memory_notifications: off
context_file_max_chars: 30000
fallback_providers:
  - provider: \"admira-nvidia\"
    model: \"deepseek-ai/deepseek-v4-flash\"
providers:
  admira-nvidia:
    base_url: \"https://integrate.api.nvidia.com/v1\"
agent:
  context_length: 80000
compression:
  threshold: 0.45
  hygiene_hard_message_limit: 24
  abort_on_summary_failure: false
  models:
    - provider: \"custom\"
      base_url: \"https://integrate.api.nvidia.com/v1\"
"""
        brain = {
            "brain": "nvidia_nim",
            "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
            "model": "z-ai/glm-5.2",
            "base_url": hermes_bridge.ADMIRA_NVIDIA_DEFAULT_BASE_URL,
        }
        self.assertTrue(hermes_bridge._cli_hermes_config_needs_write(config_text, brain))

    def test_connected_model_catalog_keeps_primary_context_cap(self):
        original_connections = hermes_bridge.agent_model_connections
        try:
            hermes_bridge.agent_model_connections = lambda _config, include_secrets=False: {
                "nvidia_nim": {
                    "configured": True,
                    "base_url": hermes_bridge.ADMIRA_NVIDIA_DEFAULT_BASE_URL,
                    "model": "z-ai/glm-5.2",
                }
            }
            lines = hermes_bridge.admira_connected_model_config_lines(
                object(),
                {
                    "brain": "nvidia_nim",
                    "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
                    "model": "z-ai/glm-5.2",
                    "context_length": 80000,
                },
            )
            self.assertIn("  context_length: 80000", lines)
        finally:
            hermes_bridge.agent_model_connections = original_connections

    def test_always_on_meta_context_is_compact_and_not_persisted(self):
        metric_row = {
            "id": "1",
            "name": "Active item",
            "status": "ACTIVE",
            "effective_status": "ACTIVE",
            "campaign_id": "1",
            "adset_id": "1",
            "spend": 12.5,
            "impressions": 1000,
            "clicks": 20,
            "ctr": 2,
            "funnel": {"large_duplicate_payload": "x" * 5000},
        }
        raw = {
            "ok": True,
            "campaigns": [{**metric_row, "id": str(index)} for index in range(100)],
            "adsets": [{**metric_row, "id": str(index)} for index in range(200)],
            "ads": [{**metric_row, "id": str(index)} for index in range(400)],
            "campaign_tree": [{"duplicate": "x" * 10000}] * 100,
        }
        compact = admira_hermes_runtime_patch._compact_live_meta_context(raw)
        serialized = json.dumps(compact, ensure_ascii=False)
        self.assertLess(len(serialized), 50000)
        self.assertNotIn("campaign_tree", compact)
        enriched = admira_hermes_runtime_patch._append_live_meta_context("hola", raw)
        persisted = admira_hermes_runtime_patch._strip_admira_runtime_injections(enriched)
        self.assertEqual(persisted, "hola")

    def test_independent_provider_precedes_same_nvidia_key(self):
        original_connections = hermes_bridge.agent_model_connections
        original_nvidia_catalog = hermes_bridge.NVIDIA_MODEL_CATALOG_FILE
        original_codex_catalog = hermes_bridge.CODEX_MODEL_CATALOG_FILE
        original_codex_health = hermes_bridge.codex_credential_health
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                hermes_bridge.NVIDIA_MODEL_CATALOG_FILE = root / "nvidia.json"
                hermes_bridge.CODEX_MODEL_CATALOG_FILE = root / "codex.json"
                hermes_bridge.NVIDIA_MODEL_CATALOG_FILE.write_text(json.dumps({"models": ["z-ai/glm-5.2", "meta/llama-3.1-8b-instruct"]}), encoding="utf-8")
                hermes_bridge.CODEX_MODEL_CATALOG_FILE.write_text(json.dumps({"models": ["gpt-5.4-mini"]}), encoding="utf-8")
                hermes_bridge.agent_model_connections = lambda _config, include_secrets=False: {
                    "minimax": {"configured": True, "base_url": "https://api.minimax.io/v1", "model": "MiniMax-M3"}
                }
                hermes_bridge.codex_credential_health = lambda _config: {"state": "stored", "reauth_required": False}
                chain = hermes_bridge.admira_inference_fallback_chain(object(), {
                    "brain": "nvidia_nim",
                    "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
                    "model": "z-ai/glm-5.2",
                    "base_url": hermes_bridge.ADMIRA_NVIDIA_DEFAULT_BASE_URL,
                })
                self.assertEqual(chain[0]["provider"], hermes_bridge.ADMIRA_MINIMAX_PROVIDER)
                self.assertEqual(chain[1]["provider"], "openai-codex")
                self.assertFalse(any(item["provider"] == hermes_bridge.ADMIRA_NVIDIA_PROVIDER for item in chain[1:]))
        finally:
            hermes_bridge.agent_model_connections = original_connections
            hermes_bridge.NVIDIA_MODEL_CATALOG_FILE = original_nvidia_catalog
            hermes_bridge.CODEX_MODEL_CATALOG_FILE = original_codex_catalog
            hermes_bridge.codex_credential_health = original_codex_health

    def test_unconnected_codex_catalog_is_not_a_cron_fallback(self):
        original_connections = hermes_bridge.agent_model_connections
        original_catalog = hermes_bridge.CODEX_MODEL_CATALOG_FILE
        original_codex_health = hermes_bridge.codex_credential_health
        try:
            with tempfile.TemporaryDirectory() as directory:
                catalog = Path(directory) / "codex.json"
                catalog.write_text(json.dumps({"models": ["gpt-5.4-mini"]}), encoding="utf-8")
                hermes_bridge.CODEX_MODEL_CATALOG_FILE = catalog
                hermes_bridge.agent_model_connections = lambda _config, include_secrets=False: {}
                hermes_bridge.codex_credential_health = lambda _config: {"state": "missing", "reauth_required": False}
                chain = hermes_bridge.admira_inference_fallback_chain(object(), {
                    "brain": "nvidia_nim",
                    "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
                    "model": "z-ai/glm-5.2",
                })
                self.assertFalse(any(item["provider"] == "openai-codex" for item in chain))
        finally:
            hermes_bridge.agent_model_connections = original_connections
            hermes_bridge.CODEX_MODEL_CATALOG_FILE = original_catalog
            hermes_bridge.codex_credential_health = original_codex_health

    def test_nvidia_primary_has_no_invented_fallback_without_another_provider(self):
        original_catalog = hermes_bridge.NVIDIA_MODEL_CATALOG_FILE
        original_connections = hermes_bridge.agent_model_connections
        original_codex_health = hermes_bridge.codex_credential_health
        try:
            with tempfile.TemporaryDirectory() as directory:
                hermes_bridge.NVIDIA_MODEL_CATALOG_FILE = Path(directory) / "missing-nvidia.json"
                hermes_bridge.agent_model_connections = lambda _config, include_secrets=False: {}
                hermes_bridge.codex_credential_health = lambda _config: {"state": "missing", "reauth_required": False}
                chain = hermes_bridge.admira_inference_fallback_chain(object(), {
                    "brain": "nvidia_nim",
                    "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
                    "model": "z-ai/glm-5.2",
                    "base_url": hermes_bridge.ADMIRA_NVIDIA_DEFAULT_BASE_URL,
                })
                self.assertEqual(chain, [])
        finally:
            hermes_bridge.NVIDIA_MODEL_CATALOG_FILE = original_catalog
            hermes_bridge.agent_model_connections = original_connections
            hermes_bridge.codex_credential_health = original_codex_health

    def test_nvidia_live_catalog_adds_one_model_specific_same_key_fallback(self):
        """A fresh live catalog permits one alternate NIM pool, never guesses IDs."""
        original_catalog = hermes_bridge.NVIDIA_MODEL_CATALOG_FILE
        original_connections = hermes_bridge.agent_model_connections
        original_codex_health = hermes_bridge.codex_credential_health
        try:
            with tempfile.TemporaryDirectory() as directory:
                hermes_bridge.NVIDIA_MODEL_CATALOG_FILE = Path(directory) / "nvidia.json"
                hermes_bridge.NVIDIA_MODEL_CATALOG_FILE.write_text(json.dumps({
                    "models": ["z-ai/glm-5.2", "minimaxai/minimax-m3", "openai/gpt-oss-20b"],
                    "source": "nvidia_live_catalog",
                    "account_verified": True,
                    "checked_epoch": time.time(),
                }), encoding="utf-8")
                hermes_bridge.agent_model_connections = lambda _config, include_secrets=False: {}
                hermes_bridge.codex_credential_health = lambda _config: {"state": "missing", "reauth_required": False}
                chain = hermes_bridge.admira_inference_fallback_chain(object(), {
                    "brain": "nvidia_nim",
                    "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
                    "model": "z-ai/glm-5.2",
                    "base_url": hermes_bridge.ADMIRA_NVIDIA_DEFAULT_BASE_URL,
                })
                self.assertEqual(len(chain), 1)
                self.assertEqual(chain[0]["provider"], hermes_bridge.ADMIRA_NVIDIA_PROVIDER)
                self.assertEqual(chain[0]["model"], "minimaxai/minimax-m3")
                self.assertEqual(chain[0]["key_env"], hermes_bridge.ADMIRA_NVIDIA_KEY_ENV)
        finally:
            hermes_bridge.NVIDIA_MODEL_CATALOG_FILE = original_catalog
            hermes_bridge.agent_model_connections = original_connections
            hermes_bridge.codex_credential_health = original_codex_health

    def test_stale_nvidia_catalog_does_not_enable_same_key_fallback(self):
        original_catalog = hermes_bridge.NVIDIA_MODEL_CATALOG_FILE
        original_connections = hermes_bridge.agent_model_connections
        original_codex_health = hermes_bridge.codex_credential_health
        try:
            with tempfile.TemporaryDirectory() as directory:
                hermes_bridge.NVIDIA_MODEL_CATALOG_FILE = Path(directory) / "nvidia.json"
                hermes_bridge.NVIDIA_MODEL_CATALOG_FILE.write_text(json.dumps({
                    "models": ["z-ai/glm-5.2", "minimaxai/minimax-m3"],
                    "source": "nvidia_live_catalog",
                    "account_verified": True,
                    "checked_epoch": time.time() - hermes_bridge.NVIDIA_LIVE_CATALOG_MAX_AGE_SECONDS - 1,
                }), encoding="utf-8")
                hermes_bridge.agent_model_connections = lambda _config, include_secrets=False: {}
                hermes_bridge.codex_credential_health = lambda _config: {"state": "missing", "reauth_required": False}
                chain = hermes_bridge.admira_inference_fallback_chain(object(), {
                    "brain": "nvidia_nim",
                    "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
                    "model": "z-ai/glm-5.2",
                })
                self.assertEqual(chain, [])
        finally:
            hermes_bridge.NVIDIA_MODEL_CATALOG_FILE = original_catalog
            hermes_bridge.agent_model_connections = original_connections
            hermes_bridge.codex_credential_health = original_codex_health

    def test_same_nvidia_guard_only_blocks_shared_key_failures(self):
        self.assertTrue(admira_hermes_runtime_patch._admira_same_nvidia_fallback_blocked("billing"))
        self.assertTrue(admira_hermes_runtime_patch._admira_same_nvidia_fallback_blocked("authentication_error"))
        self.assertTrue(admira_hermes_runtime_patch._admira_same_nvidia_fallback_blocked("quota exhausted"))
        self.assertFalse(admira_hermes_runtime_patch._admira_same_nvidia_fallback_blocked("upstream_rate_limit"))
        self.assertFalse(admira_hermes_runtime_patch._admira_same_nvidia_fallback_blocked("HTTP 429: Too Many Requests"))
        self.assertFalse(admira_hermes_runtime_patch._admira_same_nvidia_fallback_blocked("timeout"))
        self.assertFalse(admira_hermes_runtime_patch._admira_same_nvidia_fallback_blocked("internal_server_error"))

    def test_nvidia_policy_has_zero_retries_and_at_most_one_same_key_candidate(self):
        policy = hermes_bridge.inference_runtime_policy({
            "brain": "nvidia_nim",
            "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
            "model": "minimaxai/minimax-m3",
        })
        self.assertEqual(policy["api_max_retries"], 0)
        self.assertEqual(policy["stream_retries"], 0)
        self.assertFalse(admira_hermes_runtime_patch._admira_same_nvidia_fallback_blocked("429 upstream rate limit"))
        self.assertFalse(admira_hermes_runtime_patch._admira_same_nvidia_fallback_blocked("model timeout"))


if __name__ == "__main__":
    unittest.main()
