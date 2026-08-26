import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import admira_hermes_runtime_patch
import admira_mcp_server
import admira_tool_bridge
import campaign_editing
import campaign_claim_classifier
import hermes_bridge
import hermes_gateway
import mcp_skill_registry
import product_config
from agent import prompt_builder
from agent import coding_context
from tools import memory_tool


class NvidiaInferencePolicyTests(unittest.TestCase):
    def setUp(self):
        # Guard unit tests must never spend buyer provider quota. Individual
        # semantic-classifier integration cases override this deterministic
        # unavailable result explicitly.
        semantic = mock.patch.object(
            admira_hermes_runtime_patch,
            "_classify_campaign_creation_claim_semantically",
            return_value={"ok": False, "confirmation": "", "reason": "unit_test"},
        )
        semantic.start()
        self.addCleanup(semantic.stop)

    @staticmethod
    def _admira_tool(name):
        return {"type": "function", "function": {"name": f"mcp_admira_{name}", "description": name}}

    def test_session_selected_codex_models_do_not_inherit_gemini_compression(self):
        from agent import auxiliary_client

        self.assertTrue(admira_hermes_runtime_patch._patch_model_aware_compression_threshold())
        threshold = auxiliary_client._compression_threshold_for_model
        self.assertEqual(threshold("gpt-5.6-luna", "openai-codex"), 0.85)
        self.assertEqual(threshold("gpt-5.6-terra", "openai_codex"), 0.85)
        self.assertNotEqual(threshold("gemini-3.5-flash-lite", "gemini"), 0.85)

    def test_assistant_campaign_question_is_not_persisted_as_buyer_decision(self):
        memory = {
            "onboarding_plan": "",
            "brand_guides": {"general_branding": {"name": "Clínica"}, "ad_briefs": []},
            "business_profile": {"business_name": "Clínica"},
            "recent_history": {},
        }
        latest = {
            "selected_date": "2026-08-23",
            "items": [
                {"role": "user", "content": "hola"},
                {"role": "agent", "content": "¿Damos de alta la campaña con 40.000 COP?"},
            ],
        }
        workflow = hermes_bridge.active_workflow_payload(memory, latest)
        self.assertIn("plan comercial concreto", workflow["next_step"])
        self.assertIn("never buyer decisions", workflow["resume_instruction"])
        self.assertNotIn("Responder la última pregunta", workflow["next_step"])

    def test_freeform_agent_mode_exposes_full_catalog_without_language_routing(self):
        previous = admira_hermes_runtime_patch.os.environ.get("ADMIRA_FREEFORM_AGENT_MODE")
        admira_hermes_runtime_patch.os.environ["ADMIRA_FREEFORM_AGENT_MODE"] = "true"
        try:
            tools = [
                self._admira_tool("create_whatsapp_campaign"),
                self._admira_tool("codex_image_generate"),
                self._admira_tool("edit_campaign"),
                self._admira_tool("connect_chatgpt"),
            ]
            messages = [{"role": "user", "content": "aproximadamente 40 mil pesos al dia"}]
            request = {
                "messages": messages,
                "tools": tools,
                "tool_choice": {"type": "function", "function": {"name": "mcp_admira_codex_image_generate"}},
                "parallel_tool_calls": False,
            }
            # A unit test must not inherit a real buyer's durable campaign
            # workflow from the mounted canary data volume.  That context is
            # covered separately by the campaign-continuation tests below.
            with mock.patch.object(
                admira_hermes_runtime_patch,
                "_admira_latest_campaign_routing_context",
                return_value="",
            ):
                routed = admira_hermes_runtime_patch._admira_route_request_tools(request)
                prepared = admira_hermes_runtime_patch._nvidia_prepare_request(request)
            expected = {
                "create_whatsapp_campaign", "codex_image_generate",
                "edit_campaign", "connect_chatgpt",
            }
            for result in (routed, prepared):
                names = {
                    admira_hermes_runtime_patch._nvidia_normalize_tool_name(
                        admira_hermes_runtime_patch._nvidia_tool_name(item)
                    )
                    for item in result.get("tools", [])
                }
                self.assertEqual(names, expected)
                self.assertEqual(result["messages"], messages)
                self.assertNotIn("tool_choice", result)
                self.assertNotIn("parallel_tool_calls", result)
        finally:
            if previous is None:
                admira_hermes_runtime_patch.os.environ.pop("ADMIRA_FREEFORM_AGENT_MODE", None)
            else:
                admira_hermes_runtime_patch.os.environ["ADMIRA_FREEFORM_AGENT_MODE"] = previous

    def test_freeform_agent_mode_does_not_rewrite_model_prose(self):
        previous = admira_hermes_runtime_patch.os.environ.get("ADMIRA_FREEFORM_AGENT_MODE")
        admira_hermes_runtime_patch.os.environ["ADMIRA_FREEFORM_AGENT_MODE"] = "true"
        try:
            response = {
                "final_response": "La estructura quedó creada en pausa y Image requiere autenticación.",
                "messages": [{"role": "assistant", "content": "raw model prose"}],
            }
            guarded = admira_hermes_runtime_patch._apply_conversational_output_guards(response)
            self.assertIs(guarded, response)
            self.assertEqual(
                guarded["final_response"],
                "La estructura quedó creada en pausa y Image requiere autenticación.",
            )
        finally:
            if previous is None:
                admira_hermes_runtime_patch.os.environ.pop("ADMIRA_FREEFORM_AGENT_MODE", None)
            else:
                admira_hermes_runtime_patch.os.environ["ADMIRA_FREEFORM_AGENT_MODE"] = previous

    def test_freeform_bridge_sends_unmodified_buyer_language(self):
        previous = hermes_bridge.os.environ.get("ADMIRA_FREEFORM_AGENT_MODE")
        hermes_bridge.os.environ["ADMIRA_FREEFORM_AGENT_MODE"] = "true"
        try:
            message = "aproximadamente 40 mil pesos al dia"
            query = hermes_bridge.hermes_user_query(
                {"channel": "telegram", "message": message}, {}
            )
            self.assertEqual(query, message)
            self.assertNotIn("Nota de sistema del producto", query)
        finally:
            if previous is None:
                hermes_bridge.os.environ.pop("ADMIRA_FREEFORM_AGENT_MODE", None)
            else:
                hermes_bridge.os.environ["ADMIRA_FREEFORM_AGENT_MODE"] = previous

    def test_chatgpt_connection_request_is_deterministic_and_narrow(self):
        self.assertTrue(admira_hermes_runtime_patch._chatgpt_connection_request("/conectar_chatgpt"))
        self.assertTrue(admira_hermes_runtime_patch._chatgpt_connection_request("/conectar_chatgpt@admira_bot"))
        self.assertTrue(admira_hermes_runtime_patch._chatgpt_connection_request("Dame el enlace para cambiar la cuenta de ChatGPT"))
        self.assertTrue(admira_hermes_runtime_patch._chatgpt_connection_request("dame un enlance para cambiar conexión de chatgpt"))
        self.assertTrue(admira_hermes_runtime_patch._chatgpt_connection_request("me ayudas a usar otra cuenta de chatgpot"))
        self.assertTrue(admira_hermes_runtime_patch._chatgpt_connection_request("Quiero usar otra cuenta de ChatGPT"))
        self.assertTrue(admira_hermes_runtime_patch._chatgpt_connection_request("Necesito una URL nueva para Codex"))
        self.assertTrue(admira_hermes_runtime_patch._chatgpt_connection_request("Reconnect Codex"))
        self.assertTrue(admira_hermes_runtime_patch._chatgpt_connection_request("Conectar ChatGPT"))
        self.assertFalse(admira_hermes_runtime_patch._chatgpt_connection_request("¿Qué modelo de ChatGPT recomiendas?"))
        self.assertFalse(admira_hermes_runtime_patch._chatgpt_connection_request("La cuota semanal de ChatGPT se terminó"))
        self.assertFalse(admira_hermes_runtime_patch._chatgpt_connection_request("Crea una campaña de WhatsApp"))

    def test_chatgpt_connection_tool_stays_available_without_driving_other_intents(self):
        self.assertIn("connect_chatgpt", admira_mcp_server.TOOL_INPUT_SCHEMAS)
        self.assertIn("admira_connect_chatgpt", admira_tool_bridge.PUBLIC_TOOLS)
        for prompt in (
            "Hola",
            "Crea una campaña de WhatsApp",
            "Analiza el rendimiento",
            "Quiero usar otra cuenta de ChatGPT",
        ):
            with self.subTest(prompt=prompt):
                routed = admira_hermes_runtime_patch._admira_route_request_tools({
                    "messages": [{"role": "user", "content": prompt}],
                    "tools": [
                        self._admira_tool("connect_chatgpt"),
                        self._admira_tool("create_whatsapp_campaign"),
                        self._admira_tool("get_real_meta_context"),
                    ],
                })
                names = {
                    item.get("function", {}).get("name")
                    for item in routed.get("tools") or []
                }
                self.assertIn("mcp_admira_connect_chatgpt", names)

    def test_chatgpt_connection_tool_returns_secure_handoff(self):
        original_recovery = admira_hermes_runtime_patch._automatic_codex_recovery
        original_remember = admira_hermes_runtime_patch._remember_chatgpt_login_pending
        try:
            admira_hermes_runtime_patch._automatic_codex_recovery = lambda **_kwargs: {
                "url": "https://auth.openai.com/codex/device",
                "code": "ABCD-EFGH",
            }
            admira_hermes_runtime_patch._remember_chatgpt_login_pending = lambda _key: True
            dashboard = admira_tool_bridge.load_dashboard()
            result = dashboard.handle_connect_chatgpt_tool({}, {"language": "es"})
            self.assertTrue(result.get("executed"))
            self.assertTrue(result.get("needs_login"))
            self.assertIn("https://auth.openai.com/codex/device", result.get("reply", ""))
            self.assertIn("ABCD-EFGH", result.get("reply", ""))
            self.assertNotIn("terminal", result.get("reply", "").lower())
        finally:
            admira_hermes_runtime_patch._automatic_codex_recovery = original_recovery
            admira_hermes_runtime_patch._remember_chatgpt_login_pending = original_remember

    def test_configured_brain_runtime_exception_never_claims_setup_is_missing(self):
        class FakeConfig:
            agent_brain_provider = "gemini"
            agent_chat_api_key = "configured-key"
            agent_chat_model = "gemini-3.5-flash-lite"
            agent_chat_base_url = "https://generativelanguage.googleapis.com/v1beta"
            hermes_require_codex_auth = False
            hermes_use_python_library = True

        original_library = hermes_bridge.library_chat
        try:
            def fail_library(_config, _payload):
                raise RuntimeError("targeting compiler failed")

            hermes_bridge.library_chat = fail_library
            result = hermes_bridge.chat(FakeConfig(), {"message": "Hola", "language": "es"})
            self.assertFalse(result["ok"])
            self.assertIn("error interno temporal", result["reply"])
            self.assertNotIn("conectar el cerebro", result["reply"])
            self.assertEqual(result["error"], "targeting compiler failed")
        finally:
            hermes_bridge.library_chat = original_library

    def test_library_chat_applies_campaign_evidence_guard(self):
        guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_claim({
            "final_response": "Campaña creada con éxito en estado PAUSED.",
            "messages": [
                {"role": "user", "content": "Crea una campaña web pausada."},
                {"role": "assistant", "tool_calls": [{"function": {"name": "mcp_admira_create_website_campaign"}}]},
                {"role": "tool", "name": "mcp_admira_create_website_campaign", "content": json.dumps({
                    "ok": False,
                    "campaign_creation_verified": False,
                    "reason": "placement_deprecated",
                })},
            ],
        })
        self.assertIn("No se creó la campaña en Meta", guarded["final_response"])

    def test_chatgpt_connection_reply_contains_only_safe_login_handoff(self):
        reply = admira_hermes_runtime_patch._chatgpt_connection_reply(
            {"url": "https://auth.openai.com/device", "code": "ABCD-EFGH"},
            "es",
        )
        self.assertIn("https://auth.openai.com/device", reply)
        self.assertIn("ABCD-EFGH", reply)
        self.assertIn("fallback Terra", reply)

    def test_chatgpt_login_confirmation_is_scoped_and_never_reaches_campaign_tools(self):
        original_file = admira_hermes_runtime_patch.os.environ.get("ADMIRA_CHATGPT_LOGIN_PENDING_FILE")
        original_root = admira_hermes_runtime_patch.os.environ.get("ADMIRA_PRODUCT_ROOT")
        original_request = admira_hermes_runtime_patch._request_internal_model_recovery
        try:
            admira_hermes_runtime_patch.os.environ.pop("ADMIRA_CHATGPT_LOGIN_PENDING_FILE", None)
            admira_hermes_runtime_patch.os.environ.pop("ADMIRA_PRODUCT_ROOT", None)
            self.assertEqual(
                admira_hermes_runtime_patch._chatgpt_login_pending_path(),
                Path("/app/dashboard/data/chatgpt_login_pending.json"),
            )
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "chatgpt-login-pending.json"
                admira_hermes_runtime_patch.os.environ["ADMIRA_CHATGPT_LOGIN_PENDING_FILE"] = str(path)
                key = "agent:main:telegram:dm:123"
                self.assertFalse(admira_hermes_runtime_patch._chatgpt_login_confirmation_request("Listo", key))
                self.assertTrue(admira_hermes_runtime_patch._remember_chatgpt_login_pending(key))
                self.assertTrue(admira_hermes_runtime_patch._chatgpt_login_confirmation_request("Listo", key))
                self.assertFalse(admira_hermes_runtime_patch._chatgpt_login_confirmation_request("Listo", "another-session"))
                self.assertFalse(admira_hermes_runtime_patch._chatgpt_login_confirmation_request("Crea la campaña", key))
                admira_hermes_runtime_patch._request_internal_model_recovery = lambda _action: {
                    "status": "completed",
                    "running": False,
                }
                reply = admira_hermes_runtime_patch._chatgpt_login_confirmation_reply(key, "es")
                self.assertIn("ChatGPT conectado", reply)
                self.assertFalse(admira_hermes_runtime_patch._chatgpt_login_confirmation_request("Listo", key))
                self.assertTrue(admira_hermes_runtime_patch._remember_chatgpt_login_pending(key))
                admira_hermes_runtime_patch._request_internal_model_recovery = lambda _action: {}
                retry_reply = admira_hermes_runtime_patch._chatgpt_login_confirmation_reply(key, "es")
                self.assertIn("Responde Listo otra vez", retry_reply)
                self.assertTrue(admira_hermes_runtime_patch._chatgpt_login_confirmation_request("Listo", key))
                self.assertNotIn("campaign", path.read_text(encoding="utf-8").lower())
        finally:
            admira_hermes_runtime_patch._request_internal_model_recovery = original_request
            if original_file is None:
                admira_hermes_runtime_patch.os.environ.pop("ADMIRA_CHATGPT_LOGIN_PENDING_FILE", None)
            else:
                admira_hermes_runtime_patch.os.environ["ADMIRA_CHATGPT_LOGIN_PENDING_FILE"] = original_file
            if original_root is None:
                admira_hermes_runtime_patch.os.environ.pop("ADMIRA_PRODUCT_ROOT", None)
            else:
                admira_hermes_runtime_patch.os.environ["ADMIRA_PRODUCT_ROOT"] = original_root

    def test_workspace_selection_prose_is_not_rewritten_by_a_transcript_guard(self):
        response = {
            "final_response": "Hemos conectado la cuenta publicitaria SX con la Página seleccionada.",
            "messages": [
                {"role": "user", "content": "Sí"},
                {
                    "role": "tool",
                    "name": "mcp_admira_select_meta_oauth_workspace",
                    "content": (
                        '<untrusted_tool_result>{"result": '
                        '"{\\"selected\\": true, \\"verified_persisted\\": true}"}'
                        "</untrusted_tool_result>"
                    ),
                },
                {
                    "role": "assistant",
                    "content": "Hemos conectado la cuenta publicitaria SX con la Página seleccionada.",
                },
            ],
        }
        guarded = admira_hermes_runtime_patch._apply_conversational_output_guards(response)
        self.assertIs(guarded, response)
        self.assertIn("Hemos conectado", guarded["final_response"])
        self.assertNotIn("todavía no quedaron guardadas", guarded["final_response"])
        self.assertFalse(
            hasattr(admira_hermes_runtime_patch, "_guard_unconfirmed_workspace_selection_claim")
        )

    def test_native_clarify_toolset_is_disabled_and_legacy_gate_is_removed(self):
        source = Path(hermes_gateway.__file__).read_text(encoding="utf-8")
        bridge_source = Path(hermes_bridge.__file__).read_text(encoding="utf-8")
        runtime_source = Path(admira_hermes_runtime_patch.__file__).read_text(encoding="utf-8")
        self.assertIn('"    - clarify"', source)
        self.assertNotIn("clarify_timeout", source)
        self.assertIn("Never call Hermes' native `clarify` tool", bridge_source)
        self.assertIn("Never choose the first Page", bridge_source)
        self.assertIn("`verified_persisted: true`", bridge_source)
        self.assertNotIn("_patch_campaign_clarify_gate", runtime_source)

    def test_explicit_creative_request_keeps_image_tools_without_forcing_one(self):
        for prompt in ("Creemos un creativo", "Debemos crear ese creativo", "Dije creativo"):
            with self.subTest(prompt=prompt):
                routed = admira_hermes_runtime_patch._admira_route_request_tools({
                    "messages": [{"role": "user", "content": prompt}],
                    "tools": [
                        self._admira_tool("codex_image_generate"),
                        self._admira_tool("codex_creative_plan"),
                    ],
                })
                names = {
                    item.get("function", {}).get("name")
                    for item in routed.get("tools") or []
                }
                self.assertEqual(
                    names,
                    {
                        "mcp_admira_codex_image_generate",
                        "mcp_admira_codex_creative_plan",
                    },
                )
                # Natural-language mode leaves the model free to discuss or
                # plan an underspecified request.  The provider boundary must
                # not turn one keyword into a forced mutating tool call.
                self.assertNotIn("tool_choice", routed)
                self.assertNotIn("parallel_tool_calls", routed)

    def test_campaign_budget_followup_cannot_call_image_until_buyer_requests_it(self):
        original_context = admira_hermes_runtime_patch._admira_latest_campaign_routing_context
        admira_hermes_runtime_patch._admira_latest_campaign_routing_context = lambda: ""
        self.addCleanup(
            setattr,
            admira_hermes_runtime_patch,
            "_admira_latest_campaign_routing_context",
            original_context,
        )
        tools = [
            self._admira_tool("create_whatsapp_campaign"),
            self._admira_tool("codex_image_generate"),
            self._admira_tool("codex_creative_plan"),
        ]
        messages = [
            {"role": "user", "content": "Hagamos una campaña para captar clientes por WhatsApp"},
            {"role": "assistant", "content": "¿Cuál será el presupuesto diario?"},
            {"role": "user", "content": "aproximadamente 40 mil pesos al dia"},
        ]
        routed = admira_hermes_runtime_patch._admira_route_request_tools({
            "messages": messages,
            "tools": tools,
        })
        names = {
            admira_hermes_runtime_patch._nvidia_normalize_tool_name(
                admira_hermes_runtime_patch._nvidia_tool_name(item)
            )
            for item in routed.get("tools", [])
        }
        self.assertNotIn("codex_image_generate", names)
        self.assertNotIn("codex_creative_plan", names)
        self.assertNotIn("tool_choice", routed)

        requested = admira_hermes_runtime_patch._admira_route_request_tools({
            "messages": messages + [
                {"role": "assistant", "content": "Todavía falta el creativo."},
                {"role": "user", "content": "sí, crea el creativo para esa campaña"},
            ],
            "tools": tools,
        })
        requested_names = {
            admira_hermes_runtime_patch._nvidia_normalize_tool_name(
                admira_hermes_runtime_patch._nvidia_tool_name(item)
            )
            for item in requested.get("tools", [])
        }
        self.assertIn("codex_image_generate", requested_names)
        self.assertEqual(
            requested.get("tool_choice"),
            {"type": "function", "function": {"name": "mcp_admira_codex_image_generate"}},
        )

    def test_short_confusion_turn_explains_without_campaign_or_image_tools(self):
        routed = admira_hermes_runtime_patch._admira_route_request_tools({
            "messages": [
                {"role": "user", "content": "Crea una campaña de WhatsApp"},
                {"role": "assistant", "content": "No confirmé ningún límite de Image."},
                {"role": "user", "content": "que?"},
            ],
            "tools": [
                self._admira_tool("create_whatsapp_campaign"),
                self._admira_tool("codex_image_generate"),
            ],
        })
        names = {
            admira_hermes_runtime_patch._nvidia_normalize_tool_name(
                admira_hermes_runtime_patch._nvidia_tool_name(item)
            )
            for item in routed.get("tools", [])
        }
        self.assertNotIn("create_whatsapp_campaign", names)
        self.assertNotIn("codex_image_generate", names)
        self.assertIn("CONVERSATION REPAIR RULE", str(routed.get("messages")))

    def test_image_quota_claim_requires_current_image_error(self):
        stale = {
            "final_response": "ChatGPT/Codex alcanzó el límite de generación de imágenes.",
            "messages": [
                {"role": "tool", "name": "mcp_admira_codex_image_generate", "content": '{"error_type":"rate_limit"}'},
                {"role": "user", "content": "Dije creativo"},
                {"role": "assistant", "content": "ChatGPT/Codex alcanzó el límite de generación de imágenes."},
            ],
        }
        guarded = admira_hermes_runtime_patch._guard_unconfirmed_image_unavailable_claim(stale)
        self.assertIn("No hay evidencia de un límite ni de un fallo de conexión", guarded["final_response"])

        irrelevant_empty_call = {
            "final_response": "La herramienta de generación no está autenticada; no puedo generar la imagen.",
            "messages": [
                {"role": "user", "content": "aproximadamente 40 mil pesos al dia"},
                {"role": "assistant", "tool_calls": [{"function": {"name": "mcp_admira_codex_image_generate"}}]},
                {"role": "tool", "name": "mcp_admira_codex_image_generate", "content": '{"ok":false,"reason":"empty_tool_arguments"}'},
                {"role": "assistant", "content": "La herramienta de generación no está autenticada; no puedo generar la imagen."},
            ],
        }
        corrected_budget = admira_hermes_runtime_patch._guard_unconfirmed_image_unavailable_claim(irrelevant_empty_call)
        self.assertIn("No hay evidencia", corrected_budget["final_response"])
        self.assertNotIn("autenticada", corrected_budget["final_response"])

        invented_auth = {
            "final_response": "Codex en este servidor requiere autenticación activa para generar imágenes.",
            "messages": [
                {"role": "user", "content": "si, pero no tenemos creativo aun"},
                {"role": "assistant", "content": "Codex en este servidor requiere autenticación activa para generar imágenes."},
            ],
        }
        corrected_creative = admira_hermes_runtime_patch._guard_unconfirmed_image_unavailable_claim(invented_auth)
        self.assertIn("No hay evidencia", corrected_creative["final_response"])
        self.assertNotIn("todavía no tenemos el creativo", corrected_creative["final_response"])
        self.assertNotIn("autenticación", corrected_creative["final_response"])

        invented_credentials = {
            "final_response": "La herramienta de imagen automática no está disponible en este momento por credenciales.",
            "messages": [
                {"role": "user", "content": "si, pero no tenemos creativo aun"},
                {"role": "assistant", "content": "La herramienta de imagen automática no está disponible en este momento por credenciales."},
            ],
        }
        corrected_credentials = admira_hermes_runtime_patch._guard_unconfirmed_image_unavailable_claim(invented_credentials)
        self.assertIn("No hay evidencia", corrected_credentials["final_response"])
        self.assertNotIn("todavía no tenemos el creativo", corrected_credentials["final_response"])
        self.assertNotIn("credenciales", corrected_credentials["final_response"])

        current_timeout = {
            "final_response": "ChatGPT/Codex alcanzó el límite de generación de imágenes.",
            "messages": [
                {"role": "user", "content": "Dije creativo"},
                {"role": "tool", "name": "mcp_admira_codex_image_generate", "content": '{"ok":false,"error_type":"timeout"}'},
                {"role": "assistant", "content": "ChatGPT/Codex alcanzó el límite de generación de imágenes."},
            ],
        }
        corrected = admira_hermes_runtime_patch._guard_unconfirmed_image_unavailable_claim(current_timeout)
        self.assertIn("tiempo de espera", corrected["final_response"])
        self.assertIn("no hay evidencia", corrected["final_response"])

        current_quota = {
            "final_response": "ChatGPT/Codex alcanzó el límite de generación de imágenes.",
            "messages": [
                {"role": "user", "content": "Dije creativo"},
                {"role": "tool", "name": "mcp_admira_codex_image_generate", "content": '{"ok":false,"error_type":"rate_limit","error":"usage limit"}'},
                {"role": "assistant", "content": "ChatGPT/Codex alcanzó el límite de generación de imágenes."},
            ],
        }
        kept = admira_hermes_runtime_patch._guard_unconfirmed_image_unavailable_claim(current_quota)
        self.assertIn("alcanzó el límite", kept["final_response"])

    def test_missing_creative_correction_is_reconciled_by_agent_not_canned_guard(self):
        rules = hermes_bridge.combined_agent_rules()
        self.assertIn("reconcile that statement with the current campaign evidence", rules)
        compiled = admira_hermes_runtime_patch._admira_compiled_procedure_instruction({
            "complete": True,
            "status": "complete",
            "master_plan_status": "confirmed",
            "lifecycle_state": "active_with_confirmed_strategic_plan",
        })
        self.assertIn("do not accept either the buyer's statement or old memory blindly", compiled)
        self.assertIn("show or re-attach it", compiled)
        self.assertIn("do not mix budget, audience, service, location", compiled)
        strategy_skill = (
            Path(hermes_bridge.AGENT_SKILLS_DIR)
            / "campaign-strategy"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Do not blindly accept the statement", strategy_skill)
        self.assertIn("show or re-attach it", strategy_skill)

        unsupported_failure = {
            "final_response": "Codex en este servidor requiere autenticación activa para generar imágenes.",
            "messages": [
                {"role": "user", "content": "aunque no hemos creado creativo"},
                {"role": "assistant", "content": "Codex requiere autenticación."},
            ],
        }
        guarded = admira_hermes_runtime_patch._guard_unconfirmed_image_unavailable_claim(
            unsupported_failure
        )
        self.assertIn("No hay evidencia", guarded["final_response"])
        self.assertNotIn("todavía no tenemos el creativo", guarded["final_response"])
        self.assertNotIn("Puedo generarlo", guarded["final_response"])

    def test_recent_generated_creatives_enter_continuity_without_implying_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recent = root / "output" / "creatives" / "codex-recent" / "fixed-01.png"
            recent.parent.mkdir(parents=True)
            recent.write_bytes(b"png")
            unrelated = root / "output" / "creatives" / "codex-recent" / "notes.txt"
            unrelated.write_text("not media", encoding="utf-8")
            previous_root = hermes_bridge.ROOT_DIR
            hermes_bridge.ROOT_DIR = root
            try:
                items = hermes_bridge.recent_generated_creative_context()
            finally:
                hermes_bridge.ROOT_DIR = previous_root
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["file_path"], str(recent.resolve()))
        self.assertEqual(items[0]["approval_state"], "file_exists_only_not_campaign_approval")

    def test_old_campaign_failure_does_not_replace_current_technical_detail(self):
        response = {
            "final_response": "Detalle técnico: no se creó porque la ruta del creativo no existía.",
            "messages": [
                {"role": "user", "content": "Crea la campaña"},
                {"role": "tool", "name": "mcp_admira_create_whatsapp_campaign", "content": '{"campaign_creation_verified":false}'},
                {"role": "assistant", "content": "No se creó."},
                {"role": "user", "content": "Dame el detalle técnico para soporte"},
                {"role": "assistant", "content": "Detalle técnico: no se creó porque la ruta del creativo no existía."},
            ],
        }
        guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_claim(response)
        self.assertEqual(guarded["final_response"], response["final_response"])

    def test_campaign_creation_claim_without_tool_evidence_is_rejected(self):
        response = {
            "final_response": "La estructura quedó completamente configurada y lista para su validación final.",
            "messages": [
                {
                    "role": "user",
                    "content": "Crea una campaña de WhatsApp pausada para mi empresa.",
                },
                {
                    "role": "assistant",
                    "content": "La estructura quedó completamente configurada y lista para su validación final.",
                },
            ],
        }
        guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_claim(response)
        self.assertIn("ninguna herramienta de campaña devolvió IDs reales", guarded["final_response"])

    def test_campaign_guard_preserves_future_planning_without_real_ids(self):
        response = {
            "final_response": (
                "No te preocupes por el creativo. Puedo redactar los textos y dejar la estructura "
                "creada en pausa cuando confirmemos los detalles. ¿Qué beneficio quieres destacar?"
            ),
            "messages": [
                {"role": "user", "content": "si, pero no tenemos creativo aun"},
                {"role": "assistant", "content": "Puedo dejar la estructura creada en pausa cuando confirmemos los detalles."},
            ],
        }
        guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_claim(response)
        self.assertEqual(guarded["final_response"], response["final_response"])

    def test_campaign_guard_uses_semantic_no_for_quedo_atento_false_positive(self):
        response = {
            "final_response": (
                "¡Listo, Dorian! Ya diseñé la pieza publicitaria profesional. "
                "Quedo atento para estructurar la campaña de mensajes a WhatsApp con este creativo."
            ),
            "messages": [
                {"role": "user", "content": "crear un diseño con eso"},
                {
                    "role": "tool",
                    "name": "mcp_admira_codex_image_generate",
                    "content": '{"ok":true,"image_path":"/app/output/creatives/fixed-01.png"}',
                },
                {"role": "assistant", "content": "Quedo atento para estructurar la campaña."},
            ],
        }
        with mock.patch.object(
            admira_hermes_runtime_patch,
            "_classify_campaign_creation_claim_semantically",
            return_value={"ok": True, "confirmation": "no"},
        ) as classify:
            guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_claim(response)
        self.assertEqual(guarded["final_response"], response["final_response"])
        classify.assert_called_once_with(response["final_response"])

    def test_campaign_guard_semantic_yes_still_requires_real_ids(self):
        response = {
            "final_response": "Perfecto, la campaña quedó creada y pausada.",
            "messages": [
                {"role": "user", "content": "créala"},
                {"role": "assistant", "content": "Perfecto, la campaña quedó creada y pausada."},
            ],
        }
        with mock.patch.object(
            admira_hermes_runtime_patch,
            "_classify_campaign_creation_claim_semantically",
            return_value={"ok": True, "confirmation": "si"},
        ):
            guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_claim(response)
        self.assertIn("ninguna herramienta de campaña devolvió IDs reales", guarded["final_response"])

    def test_campaign_guard_classifier_failure_preserves_known_prospective_phrase(self):
        response = {
            "final_response": "Quedo atento para estructurar la campaña de WhatsApp con este creativo.",
            "messages": [
                {"role": "user", "content": "crear un diseño con eso"},
                {"role": "assistant", "content": "Quedo atento para estructurar la campaña."},
            ],
        }
        with mock.patch.object(
            admira_hermes_runtime_patch,
            "_classify_campaign_creation_claim_semantically",
            return_value={"ok": False, "confirmation": "", "reason": "rate_limit"},
        ):
            guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_claim(response)
        self.assertEqual(guarded["final_response"], response["final_response"])

    def test_campaign_guard_verified_ids_skip_semantic_classifier(self):
        response = {
            "final_response": "Perfecto, la campaña quedó creada y pausada.",
            "messages": [
                {"role": "user", "content": "créala"},
                {
                    "role": "tool",
                    "name": "mcp_admira_create_whatsapp_campaign",
                    "content": '{"campaign_creation_verified":true,"campaign_id":"1201"}',
                },
                {"role": "assistant", "content": "Perfecto, la campaña quedó creada y pausada."},
            ],
        }
        with mock.patch.object(
            admira_hermes_runtime_patch,
            "_classify_campaign_creation_claim_semantically",
        ) as classify:
            guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_claim(response)
        self.assertEqual(guarded["final_response"], response["final_response"])
        classify.assert_not_called()

    def test_campaign_guard_recovers_same_turn_receipt_from_hermes_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state_db = Path(directory) / "state.db"
            with sqlite3.connect(state_db) as connection:
                connection.execute(
                    "CREATE TABLE sessions (id TEXT PRIMARY KEY, session_key TEXT, started_at REAL)"
                )
                connection.execute(
                    "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, "
                    "content TEXT, tool_name TEXT, tool_call_id TEXT, active INTEGER)"
                )
                connection.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?)",
                    ("session-1", "telegram-chat-1", 1.0),
                )
                connection.execute(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (1, "session-1", "user", "créala", "", "", 1),
                )
                connection.execute(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        2,
                        "session-1",
                        "tool",
                        '{"campaign_creation_verified":true,"campaign_id":"1201"}',
                        "mcp_admira_create_whatsapp_campaign",
                        "call-1",
                        1,
                    ),
                )
            response = {
                "final_response": "Perfecto, la campaña quedó creada y pausada.",
                # This matches the real provider shape that exposed the bug:
                # the final response omitted tool rows even though state.db
                # already contained them.
                "messages": [{"role": "assistant", "content": "Campaña creada."}],
            }
            enriched = admira_hermes_runtime_patch._attach_current_turn_tool_receipts(
                response,
                "telegram-chat-1",
                state_db_path=state_db,
            )
            guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_claim(enriched)
        self.assertEqual(guarded["final_response"], response["final_response"])
        self.assertEqual(
            guarded[admira_hermes_runtime_patch.ADMIRA_CURRENT_TURN_TOOL_RECEIPTS_KEY][0]["name"],
            "mcp_admira_create_whatsapp_campaign",
        )

    def test_campaign_guard_preserves_exact_latest_verified_restatement(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory) / "dashboard" / "data"
            data_dir.mkdir(parents=True)
            (data_dir / "actions.json").write_text(json.dumps([{
                "id": "act-1",
                "type": "create_campaign",
                "status": "completed",
                "payload": {
                    "name": "Rodeo - Full Detail en Taller (WhatsApp)",
                    "result": {
                        "ok": True,
                        "executed": True,
                        "campaign_id": "120250882548000425",
                        "adset_ids": ["120250882548160425"],
                        "ad_ids": ["120250882549100425"],
                    },
                },
            }]), encoding="utf-8")
            with mock.patch.dict(
                admira_hermes_runtime_patch.os.environ,
                {"ADMIRA_PRODUCT_ROOT": directory},
            ):
                response = {
                    "final_response": (
                        "La campaña Rodeo - Full Detail en Taller (WhatsApp) ya existe en Meta y está pausada; "
                        "no la volveré a duplicar."
                    ),
                    "messages": [
                        {"role": "user", "content": "intenta de nuevo crear la campaña"},
                        {"role": "assistant", "content": "La campaña ya existe."},
                    ],
                }
                guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_claim(response)
        self.assertEqual(guarded["final_response"], response["final_response"])

    def test_campaign_guard_does_not_reuse_receipt_for_another_campaign(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory) / "dashboard" / "data"
            data_dir.mkdir(parents=True)
            (data_dir / "actions.json").write_text(json.dumps([{
                "id": "act-1",
                "type": "create_campaign",
                "status": "completed",
                "payload": {
                    "name": "Rodeo - Full Detail en Taller (WhatsApp)",
                    "result": {
                        "executed": True,
                        "campaign_id": "1201",
                        "adset_ids": ["1202"],
                        "ad_ids": ["1203"],
                    },
                },
            }]), encoding="utf-8")
            with mock.patch.dict(
                admira_hermes_runtime_patch.os.environ,
                {"ADMIRA_PRODUCT_ROOT": directory},
            ):
                guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_claim({
                    "final_response": "La campaña Nueva Oferta de Medellín quedó creada y pausada.",
                    "messages": [
                        {"role": "user", "content": "crea otra campaña"},
                        {"role": "assistant", "content": "La campaña quedó creada."},
                    ],
                })
        self.assertIn("ninguna herramienta de campaña devolvió IDs reales", guarded["final_response"])

    def test_completed_campaign_workflow_keeps_graph_receipt_without_blocker(self):
        with tempfile.TemporaryDirectory() as directory:
            workflow_path = Path(directory) / "pending_campaign_workflow.json"
            result = {
                "executed": True,
                "result": {
                    "status": "created_paused",
                    "executed": True,
                    "result": {
                        "ok": True,
                        "executed": True,
                        "campaign_id": "1201",
                        "adset_ids": ["1202"],
                        "ad_ids": ["1203"],
                        "graph_verification": {
                            "ok": True,
                            "objects": [
                                {"http_status": 200},
                                {"http_status": 200},
                                {"http_status": 200},
                            ],
                        },
                    },
                },
            }
            with mock.patch.object(
                admira_tool_bridge,
                "PENDING_CAMPAIGN_WORKFLOW_FILE",
                workflow_path,
            ):
                saved = admira_tool_bridge.persist_pending_campaign_workflow(
                    "admira_create_whatsapp_campaign",
                    {"name": "Campaign", "daily_budget": 10},
                    "",
                    result=result,
                    status="completed",
                )
            persisted = json.loads(workflow_path.read_text(encoding="utf-8"))
        self.assertTrue(saved)
        self.assertTrue(persisted["meta_creation_verified"])
        self.assertEqual(persisted["blocker"], "")
        self.assertEqual(persisted["blocker_details"], [])
        self.assertEqual(persisted["creation_receipt"]["campaign_id"], "1201")
        self.assertEqual(persisted["creation_receipt"]["graph_http_statuses"], [200, 200, 200])
        self.assertEqual(len(persisted["creation_fingerprint"]), 64)

    def test_identical_completed_campaign_retry_reads_graph_and_never_mutates(self):
        args = {
            "name": "Rodeo - Full Detail en Taller (WhatsApp)",
            "objective": "OUTCOME_ENGAGEMENT",
            "daily_budget": 50000,
            "budget_confirmation": "50000 COP",
            "primary_text": "Full Detail profesional.",
            "headline": "Agenda tu Full Detail",
            "prefilled_message": "Hola, quiero agendar el diagnóstico del Full Detail.",
            "image_hash": "hash-approved",
        }
        tool = "admira_create_whatsapp_campaign"

        class FakeClient:
            def __init__(self, _config):
                pass

        class FakeDashboard:
            SocialFlowClient = FakeClient
            execute_calls = 0

            @staticmethod
            def load_config():
                return SimpleNamespace()

            @staticmethod
            def verify_campaign_stack_with_graph(_client, execution):
                return {
                    "ok": execution["campaign_id"] == "1201",
                    "objects": [
                        {"http_status": 200},
                        {"http_status": 200},
                        {"http_status": 200},
                    ],
                }

            @classmethod
            def execute_agent_tool(cls, _request, _payload):
                cls.execute_calls += 1
                raise AssertionError("an identical verified retry must not mutate Meta")

        with tempfile.TemporaryDirectory() as directory:
            workflow_path = Path(directory) / "pending_campaign_workflow.json"
            workflow_path.write_text(json.dumps({
                "status": "completed",
                "destination": "whatsapp",
                "tool": tool,
                "meta_creation_verified": True,
                "creation_fingerprint": admira_tool_bridge.campaign_creation_fingerprint(tool, args),
                "campaign_contract": {"name": args["name"]},
                "creation_receipt": {
                    "campaign_id": "1201",
                    "adset_ids": ["1202"],
                    "ad_ids": ["1203"],
                },
            }), encoding="utf-8")
            with (
                mock.patch.object(admira_tool_bridge, "PENDING_CAMPAIGN_WORKFLOW_FILE", workflow_path),
                mock.patch.object(admira_tool_bridge, "load_dashboard", return_value=FakeDashboard()),
                mock.patch.object(admira_tool_bridge, "strategic_profile_gate_result", return_value=None),
                mock.patch.object(
                    admira_tool_bridge,
                    "compile_campaign_brief",
                    return_value={
                        "ok": True,
                        "payload": args,
                        "model": "test-compiler",
                        "destination": "whatsapp",
                    },
                ),
                mock.patch.object(
                    admira_tool_bridge,
                    "destination_campaign_arguments",
                    side_effect=lambda _tool, values, **_kwargs: (dict(values), None),
                ),
            ):
                response = admira_tool_bridge.call_tool(tool, {"brief_markdown": "brief canónico aprobado"})

        self.assertTrue(response["ok"])
        self.assertTrue(response["campaign_creation_verified"])
        self.assertTrue(response["reused_existing"])
        self.assertFalse(response["executed"])
        self.assertEqual(response["campaign_id"], "1201")
        self.assertEqual(FakeDashboard.execute_calls, 0)

    def test_generic_acknowledgement_after_restart_never_surfaces_stale_campaign_failure(self):
        response = {
            "final_response": "Listo, la campaña quedó configurada en pausa.",
            "messages": [
                {"role": "user", "content": "Hola"},
                {"role": "assistant", "content": "Hola. ¿En qué quieres trabajar?"},
                {"role": "user", "content": "Ok"},
                {"role": "assistant", "content": "Listo, la campaña quedó configurada en pausa."},
            ],
        }
        guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_claim(response)
        self.assertIn("ninguna herramienta de campaña devolvió IDs reales", guarded["final_response"])
        self.assertNotIn("No se creó la campaña", guarded["final_response"])

    def test_campaign_outcome_guard_does_not_classify_buyer_phrasing(self):
        variants = (
            "Déjamela andando, porfa",
            "Armemos lo de ayer con los cambios que te dije",
            "plis as lo d guasap",
            "Hola",
        )
        for prompt in variants:
            with self.subTest(prompt=prompt):
                guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_claim({
                    "final_response": "Perfecto, la campaña quedó creada y pausada.",
                    "messages": [
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": "Perfecto, la campaña quedó creada y pausada."},
                    ],
                })
                self.assertIn("ninguna herramienta de campaña devolvió IDs reales", guarded["final_response"])

    def test_campaign_edit_outcome_guard_distinguishes_staged_from_applied(self):
        with mock.patch.object(
            campaign_claim_classifier,
            "classify_campaign_edit_claim",
            return_value={"ok": True, "confirmation": "si"},
        ):
            staged = admira_hermes_runtime_patch._guard_unconfirmed_campaign_edit_claim({
                "final_response": "He dejado configurado el presupuesto diario de la campaña en 11 USD.",
                "buyer_message": "En la campaña Rodeo cambia el presupuesto a 11 USD.",
                "messages": [{
                    "role": "tool",
                    "name": "mcp_admira_edit_campaign",
                    "content": '{"executed":false,"staged":true,"reason":"campaign_edit_pending_approval"}',
                }],
            })
        self.assertIn("todavía no lo apliqué", staged["final_response"])
        with mock.patch.object(
            campaign_claim_classifier,
            "classify_campaign_edit_claim",
            return_value={"ok": True, "confirmation": "si"},
        ):
            applied = admira_hermes_runtime_patch._guard_unconfirmed_campaign_edit_claim({
                "final_response": "He dejado configurado el presupuesto diario de la campaña en 11 USD.",
                "buyer_message": "En la campaña Rodeo cambia el presupuesto a 11 USD.",
                "messages": [{
                    "role": "tool",
                    "name": "mcp_admira_stage_budget_change",
                    "content": '{"executed":true,"ok":true,"blocked":false}',
                }],
            })
        self.assertIn("He dejado configurado", applied["final_response"])

    def test_campaign_edit_guard_never_classifies_response_without_campaign_word(self):
        original = "Hola, Dorian. Ya habíamos creado el logo."
        with mock.patch.object(campaign_claim_classifier, "classify_campaign_edit_claim") as classifier:
            guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_edit_claim({
                "final_response": original,
                "messages": [{"role": "user", "content": "hola"}],
            })
        self.assertEqual(guarded["final_response"], original)
        classifier.assert_not_called()

    def test_campaign_edit_guard_semantic_no_passes_original_response(self):
        original = "Podemos revisar la campaña después de terminar el creativo."
        with mock.patch.object(
            campaign_claim_classifier,
            "classify_campaign_edit_claim",
            return_value={"ok": True, "confirmation": "no"},
        ):
            guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_edit_claim({
                "final_response": original,
                "buyer_message": "En la campaña Rodeo actualiza el creativo.",
                "messages": [],
            })
        self.assertEqual(guarded["final_response"], original)

    def test_campaign_edit_guard_does_not_rewrite_historical_claim_after_greeting(self):
        """The latest buyer turn, not stale session prose, defines relevance."""
        original = "Ya actualicé la campaña de Rodeo correctamente."
        with mock.patch.object(
            campaign_claim_classifier,
            "classify_campaign_edit_claim",
            return_value={"ok": True, "confirmation": "no"},
        ) as classifier:
            guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_edit_claim({
                "final_response": original,
                "messages": [
                    {"role": "user", "content": "En la campaña Rodeo cambia el presupuesto."},
                    {"role": "assistant", "content": "Ya actualicé la campaña de Rodeo correctamente."},
                    {"role": "user", "content": "Hola"},
                ],
            })
        self.assertEqual(guarded["final_response"], original)
        self.assertEqual(classifier.call_args.kwargs["buyer_message"], "Hola")

    def test_campaign_edit_guard_requires_current_turn_receipt_after_semantic_yes(self):
        original = "Ya apliqué el cambio de presupuesto en la campaña Rodeo."
        with mock.patch.object(
            campaign_claim_classifier,
            "classify_campaign_edit_claim",
            return_value={"ok": True, "confirmation": "si"},
        ):
            guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_edit_claim({
                "final_response": original,
                "buyer_message": "En la campaña Rodeo cambia el presupuesto a 12 USD.",
                "messages": [],
            })
        self.assertIn("No pude verificar", guarded["final_response"])

    def test_campaign_edit_guard_is_idempotent_without_language_matching(self):
        response = {
            "final_response": "No pude verificar una edición de campaña en este turno.",
            admira_hermes_runtime_patch.ADMIRA_CAMPAIGN_EDIT_GUARD_APPLIED_KEY: True,
        }
        with mock.patch.object(
            campaign_claim_classifier,
            "classify_campaign_edit_claim",
        ) as classifier:
            guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_edit_claim(
                response,
                buyer_message="hola",
            )
        self.assertIs(guarded, response)
        classifier.assert_not_called()

    def test_campaign_edit_guard_preserves_success_from_nested_private_approval_receipt(self):
        """A successful approval after a pending stage must not be rewritten.

        Some Hermes adapters expose the current-turn receipts only in the
        private gateway field.  The approval result is itself JSON encoded
        inside the action envelope, so this reproduces the real nested and
        escaped shape seen after a successful Meta read-back.
        """
        original = "Actualicé la campaña y su presupuesto correctamente."
        successful_result = {
            "ok": True,
            "executed": True,
            "verified": True,
            "campaign_id": "120250882548000425",
            "applied": [{
                "entity_type": "ad",
                "entity_id": "120250882549100425",
                "fields": ["creative"],
                "creative_id": "1409761134411839",
            }],
            "verification": [{
                "target_id": "120250882549100425",
                "ok": True,
                "http_status": 200,
            }],
            "results": [{
                "ok": True,
                "status": 200,
                "body": {"success": True},
            }],
        }
        approve_envelope = {
            "ok": True,
            "result": json.dumps({
                "type": "approval_decision",
                "executed": True,
                "decision": "approve",
                "result": [{
                    "type": "campaign_edit",
                    "status": "approved",
                    "result": successful_result,
                }],
            }),
        }
        receipts = [
            {
                "role": "tool",
                "name": "mcp_admira_edit_campaign",
                "content": json.dumps({
                    "executed": False,
                    "staged": True,
                    "reason": "campaign_edit_pending_approval",
                }),
            },
            {
                "role": "tool",
                "name": "mcp_admira_approve_action",
                # The wrapper plus encoded result reproduces the two escaping
                # layers present in the real state.db receipt.
                "content": (
                    '<untrusted_tool_result source="mcp_admira_approve_action">\n'
                    + json.dumps(json.dumps(approve_envelope))
                    + "\n</untrusted_tool_result>"
                ),
            },
        ]
        with mock.patch.object(
            campaign_claim_classifier,
            "classify_campaign_edit_claim",
            return_value={"ok": True, "confirmation": "si"},
        ):
            guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_edit_claim({
                "final_response": original,
                "buyer_message": "En la campaña Rodeo cambia el presupuesto.",
                "messages": [],
                admira_hermes_runtime_patch.ADMIRA_CURRENT_TURN_TOOL_RECEIPTS_KEY: receipts,
            })
        self.assertEqual(guarded["final_response"], original)

    def test_campaign_edit_receipt_rejects_success_for_a_different_campaign(self):
        staged = {
            "role": "tool",
            "name": "mcp_admira_edit_campaign",
            "content": json.dumps({
                "campaign_id": "campaign-a",
                "executed": False,
                "staged": True,
                "reason": "campaign_edit_pending_approval",
            }),
        }
        unrelated_success = {
            "role": "tool",
            "name": "mcp_admira_approve_action",
            "content": json.dumps({
                "campaign_id": "campaign-b",
                "ok": True,
                "executed": True,
                "verified": True,
                "verification": [{"target_id": "ad-b", "ok": True, "http_status": 200}],
                "results": [{"ok": True, "status": 200}],
            }),
        }

        state = admira_hermes_runtime_patch._campaign_edit_receipt_state([
            staged,
            unrelated_success,
        ])

        self.assertTrue(state["attempted"])
        self.assertTrue(state["staged"])
        self.assertFalse(state["applied"])

    def test_direct_edit_receipt_requires_verified_graph_readback(self):
        state = admira_hermes_runtime_patch._campaign_edit_receipt_state([{
            "role": "tool",
            "name": "mcp_admira_edit_campaign",
            "content": json.dumps({
                "campaign_id": "campaign-a",
                "ok": True,
                "executed": True,
            }),
        }])

        self.assertTrue(state["attempted"])
        self.assertFalse(state["applied"])

    def test_campaign_edit_guard_keeps_real_pending_receipt_blocked(self):
        """A pending edit without an executed approval remains pending."""
        original = "Actualicé la campaña y su presupuesto correctamente."
        with mock.patch.object(
            campaign_claim_classifier,
            "classify_campaign_edit_claim",
            return_value={"ok": True, "confirmation": "si"},
        ):
            guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_edit_claim({
                "final_response": original,
                "buyer_message": "En la campaña Rodeo cambia el presupuesto.",
                "messages": [],
                admira_hermes_runtime_patch.ADMIRA_CURRENT_TURN_TOOL_RECEIPTS_KEY: [{
                    "role": "tool",
                    "name": "mcp_admira_edit_campaign",
                    "content": json.dumps({
                        "executed": False,
                        "staged": True,
                        "reason": "campaign_edit_pending_approval",
                    }),
                }],
            })
        self.assertIn("todavía no lo apliqué", guarded["final_response"])

    def test_campaign_edit_backend_fills_only_unambiguous_missing_ids(self):
        snapshot = {
            "campaign": {"id": "120000000000001"},
            "ad_sets": [{"id": "120000000000002"}],
            "ads": [{"id": "120000000000003"}],
        }
        operations, errors = campaign_editing._validate_operations(
            {"operations": [{"entity_type": "campaign", "changes": {"daily_budget": 11}}]},
            snapshot,
        )
        self.assertFalse(errors)
        self.assertEqual(operations[0]["entity_id"], "120000000000001")
        ambiguous, errors = campaign_editing._validate_operations(
            {"operations": [{"entity_type": "adset", "changes": {"age_min": 25}}]},
            {**snapshot, "ad_sets": [{"id": "120000000000002"}, {"id": "120000000000004"}]},
        )
        self.assertIsNone(ambiguous)
        self.assertIn("operations[0].entity_id", errors)

    def test_campaign_edit_backend_normalizes_compiler_key_aliases(self):
        snapshot = {
            "campaign": {"id": "120000000000001"},
            "ad_sets": [],
            "ads": [],
        }
        variants = (
            {"object_type": "campaign", "id": "120000000000001", "daily_budget": 11},
            {"object_type": "campaign", "object_id": "120000000000001", "daily_budget": 11},
            {"target_type": "campaign", "target_id": "120000000000001", "daily_budget": 11},
            {"entity": "campaign", "id": "120000000000001", "changes": {"daily_budget": 11}},
            {"type": "campaign", "id": "120000000000001", "daily_budget": 11},
        )
        for operation in variants:
            with self.subTest(operation=operation):
                normalized, errors = campaign_editing._validate_operations(
                    {"operations": [operation]}, snapshot,
                )
                self.assertFalse(errors)
                self.assertEqual(normalized[0]["entity_type"], "campaign")
                self.assertEqual(normalized[0]["entity_id"], "120000000000001")
                self.assertEqual(normalized[0]["changes"]["daily_budget"], 11.0)

    def test_campaign_edit_backend_normalizes_adset_and_fields_aliases(self):
        snapshot = {
            "campaign": {"id": "120000000000001"},
            "ad_sets": [{"id": "120000000000002"}],
            "ads": [],
        }
        normalized, errors = campaign_editing._validate_operations(
            {"operations": [{
                "target_type": "ad_set",
                "target_id": "120000000000002",
                "fields": {
                    "daily_budget": 6,
                    "budget_confirmation": {"amount": 6, "currency": "USD"},
                },
            }]},
            snapshot,
        )
        self.assertFalse(errors)
        self.assertEqual(normalized[0]["entity_type"], "adset")
        self.assertEqual(normalized[0]["entity_id"], "120000000000002")
        self.assertEqual(normalized[0]["changes"]["daily_budget"], 6.0)

    def test_campaign_edit_budget_dict_preserves_major_units_exactly(self):
        checked = campaign_editing._budget_amount(
            {
                "daily_budget": 11.0,
                "budget_confirmation": {"amount": 11.0, "currency": "USD"},
            },
            "USD",
            dashboard_contract=lambda phrase, account_currency="": {
                "ok": phrase == "11 USD" and account_currency == "USD",
                "amount": 11.0,
                "api_amount": 1100,
            },
        )
        changes, error = checked
        self.assertFalse(error)
        self.assertEqual(changes["daily_budget"], 11.0)
        self.assertEqual(changes["_daily_budget_api"], 1100)

    def test_campaign_edit_fingerprint_normalizes_graph_minor_budget_units(self):
        dashboard_item = {"id": "120000000000001", "daily_budget": 11.0, "status": "paused", "start_time": "2026-08-20T09:00:00-0500"}
        graph_item = {"id": "120000000000001", "daily_budget": "1100", "status": "PAUSED", "start_time": "2026-08-20T09:00:00-0500", "_meta_graph_minor_units": True}
        self.assertEqual(campaign_editing._fingerprint(dashboard_item), campaign_editing._fingerprint(graph_item))

    def test_adset_fingerprint_ignores_graph_only_targeting_and_zero_budget_shape(self):
        dashboard_item = {
            "id": "120000000000002",
            "name": "Core",
            "status": "paused",
            "daily_budget": 7.0,
            "lifetime_budget": 0.0,
            "start_time": "2026-08-20T09:00:00-0500",
        }
        graph_item = {
            "id": "120000000000002",
            "name": "Core",
            "status": "PAUSED",
            "configured_status": "PAUSED",
            "daily_budget": "700",
            "lifetime_budget": "0",
            "start_time": "2026-08-20T09:00:00-0500",
            "targeting": {"age_min": 23, "publisher_platforms": ["instagram"]},
            "_meta_graph_minor_units": True,
        }
        self.assertEqual(campaign_editing._fingerprint(dashboard_item), campaign_editing._fingerprint(graph_item))

    def test_campaign_edit_detection_does_not_treat_status_question_as_mutation(self):
        messages = [{"role": "user", "content": "qiero saber si la campaña de guasap esta bien o si solo esta pausada"}]
        self.assertFalse(admira_hermes_runtime_patch._admira_campaign_edit_requested(messages))

    def test_campaign_edit_detection_accepts_natural_budget_mutation(self):
        messages = [{"role": "user", "content": "En la de WhatsApp bájame el presupuesto a 11 dólares y mantenla pausada"}]
        self.assertTrue(admira_hermes_runtime_patch._admira_campaign_edit_requested(messages))

    def test_cli_query_preserves_existing_campaign_edit_language_verbatim(self):
        query = hermes_bridge.hermes_user_query(
            {"message": "En la de WhatsApp bájame el presupuesto", "channel": "telegram"},
            {},
        )
        self.assertEqual(query, "En la de WhatsApp bájame el presupuesto")
        self.assertNotIn("Nota de sistema del producto", query)

    def test_campaign_edit_bridge_accepts_natural_brief_alias(self):
        normalized = admira_tool_bridge.normalize_campaign_edit_arguments({
            "brief_markdown": "Bajar la campaña 120000000000001 a 11 USD diarios",
        })
        self.assertEqual(normalized["change_request"], "Bajar la campaña 120000000000001 a 11 USD diarios")
        self.assertEqual(normalized["campaign_reference"], normalized["change_request"])
        self.assertNotIn("brief_markdown", normalized)

    def test_campaign_edit_bridge_accepts_query_and_instructions_aliases(self):
        normalized = admira_tool_bridge.normalize_campaign_edit_arguments({
            "campaign_query": "Medellín",
            "instructions": "Bajar el presupuesto del conjunto a 6 USD",
        })
        self.assertEqual(normalized["campaign_reference"], "Medellín")
        self.assertEqual(normalized["change_request"], "Bajar el presupuesto del conjunto a 6 USD")
        self.assertNotIn("campaign_query", normalized)
        self.assertNotIn("instructions", normalized)

    def test_hyphenated_campaign_edit_approval_id_resolves_exactly(self):
        dashboard = admira_tool_bridge.load_dashboard()
        pending = [
            {"id": "approval-edit-first-r1", "status": "pending"},
            {"id": "approval-edit-second-r1", "status": "pending"},
        ]
        item, reason = dashboard.find_pending_approval_for_text(
            "approve approval-edit-second-r1",
            pending,
        )
        self.assertEqual(reason, "id")
        self.assertEqual(item["id"], "approval-edit-second-r1")

    def test_campaign_edit_cli_turn_removes_file_mutation_toolset(self):
        config = SimpleNamespace(hermes_enabled_toolsets="memory,file,terminal,code_execution")
        toolsets = hermes_bridge.cli_toolsets(config, {
            "channel": "telegram",
            "message": "En la campaña de WhatsApp bájame el presupuesto a 11 USD",
        })
        self.assertIn("admira", toolsets)
        self.assertNotIn("file", toolsets)
        self.assertNotIn("terminal", toolsets)
        self.assertNotIn("code_execution", toolsets)

    def test_internal_file_mutation_verifier_is_never_buyer_visible(self):
        text, _meta = admira_hermes_runtime_patch.normalize_telegram_outbound_text(
            "Cambio preparado.\n\n⚠️ File-mutation verifier: 1 file was NOT modified.\n  • memory/a.json — patch failed",
            "es",
        )
        self.assertEqual(text, "Cambio preparado.")

    def test_recent_creative_path_becomes_native_attachment_not_visible_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output" / "creatives" / "codex-test" / "fixed-01.png"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"png")
            previous = admira_hermes_runtime_patch.os.environ.get("ADMIRA_PRODUCT_ROOT")
            admira_hermes_runtime_patch.os.environ["ADMIRA_PRODUCT_ROOT"] = str(root)
            try:
                text, metadata = admira_hermes_runtime_patch.normalize_telegram_outbound_text(
                    f"Ya existe este creativo: `{output}`. Podemos reutilizarlo o crear otro.",
                    "es",
                )
            finally:
                if previous is None:
                    admira_hermes_runtime_patch.os.environ.pop("ADMIRA_PRODUCT_ROOT", None)
                else:
                    admira_hermes_runtime_patch.os.environ["ADMIRA_PRODUCT_ROOT"] = previous
        self.assertNotIn(str(output), text.split("MEDIA:", 1)[0])
        self.assertIn("el archivo adjunto", text)
        self.assertTrue(text.endswith(f"MEDIA:{output.resolve()}"))
        self.assertIn("internal_media_path_attached", metadata["reasons"])

    def test_existing_media_directive_is_not_duplicated_when_path_also_leaks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output" / "creatives" / "codex-test" / "fixed-01.png"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"png")
            previous = admira_hermes_runtime_patch.os.environ.get("ADMIRA_PRODUCT_ROOT")
            admira_hermes_runtime_patch.os.environ["ADMIRA_PRODUCT_ROOT"] = str(root)
            try:
                text, _metadata = admira_hermes_runtime_patch.normalize_telegram_outbound_text(
                    f"MEDIA:{output}\nYa existe `{output}` y podemos reutilizarlo.",
                    "es",
                )
            finally:
                if previous is None:
                    admira_hermes_runtime_patch.os.environ.pop("ADMIRA_PRODUCT_ROOT", None)
                else:
                    admira_hermes_runtime_patch.os.environ["ADMIRA_PRODUCT_ROOT"] = previous
        self.assertEqual(text.count("MEDIA:"), 1)
        self.assertNotIn(f"`{output}`", text)

    def test_duplicate_native_media_directives_are_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output" / "creatives" / "codex-test" / "fixed-01.png"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"png")
            previous = admira_hermes_runtime_patch.os.environ.get("ADMIRA_PRODUCT_ROOT")
            admira_hermes_runtime_patch.os.environ["ADMIRA_PRODUCT_ROOT"] = str(root)
            try:
                text, metadata = admira_hermes_runtime_patch.normalize_telegram_outbound_text(
                    f"Dos opciones recientes:\nMEDIA:{output}\nMEDIA:{output}\n¿Cuál prefieres?",
                    "es",
                )
            finally:
                if previous is None:
                    admira_hermes_runtime_patch.os.environ.pop("ADMIRA_PRODUCT_ROOT", None)
                else:
                    admira_hermes_runtime_patch.os.environ["ADMIRA_PRODUCT_ROOT"] = previous
        self.assertEqual(text.count(f"MEDIA:{output.resolve()}"), 1)
        self.assertIn("¿Cuál prefieres?", text)
        self.assertIn("duplicate_media_directive_removed", metadata["reasons"])

    def test_campaign_edit_guard_accepts_hermes_result_object_shape(self):
        raw = SimpleNamespace(
            final_response="Actualicé la campaña y su presupuesto.",
            messages=[SimpleNamespace(
                role="tool",
                name="mcp_admira_edit_campaign",
                content='{"executed":false,"staged":true,"reason":"campaign_edit_pending_approval"}',
            )],
        )
        normalized = {
            "final_response": raw.final_response,
            "messages": raw.messages,
        }
        normalized["buyer_message"] = "En la campaña Rodeo cambia el presupuesto."
        with mock.patch.object(
            campaign_claim_classifier,
            "classify_campaign_edit_claim",
            return_value={"ok": True, "confirmation": "si"},
        ):
            guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_edit_claim(normalized)
        self.assertIn("todavía no lo apliqué", guarded["final_response"])

    def test_campaign_edit_guard_without_buyer_provenance_preserves_response(self):
        original = "Ya actualicé la campaña de Rodeo correctamente."
        with mock.patch.object(
            campaign_claim_classifier,
            "classify_campaign_edit_claim",
            return_value={"ok": True, "confirmation": "si"},
        ) as classifier:
            guarded = admira_hermes_runtime_patch._guard_unconfirmed_campaign_edit_claim({
                "final_response": original,
                "messages": [],
            })
        self.assertEqual(guarded["final_response"], original)
        classifier.assert_not_called()

    def test_cli_edit_text_without_structured_evidence_is_not_reported_as_applied(self):
        corrected = admira_hermes_runtime_patch.guard_unverified_campaign_edit_text(
            "💰 Presupuesto actualizado a 11 USD diarios y campaña mantenida en pausa.",
            "es",
        )
        self.assertIn("No pude verificar", corrected)
        question = admira_hermes_runtime_patch.guard_unverified_campaign_edit_text(
            "¿Qué pasa si actualizo el presupuesto de una campaña?", "es",
        )
        self.assertIn("¿Qué pasa", question)

    def test_cli_edit_guard_reports_new_real_pending_edit_as_prepared(self):
        corrected = admira_hermes_runtime_patch.guard_unverified_campaign_edit_text(
            "Actualicé el presupuesto del conjunto a 6 USD.",
            "es",
            pending_edit={
                "type": "campaign_edit",
                "status": "pending",
                "payload": {
                    "campaign_name": "Campaña Medellín",
                    "summary": "Presupuesto del conjunto a 6 USD",
                },
            },
        )
        self.assertIn("Preparé el cambio para Campaña Medellín", corrected)
        self.assertIn("pendiente de aprobación", corrected)
        self.assertNotIn("Actualicé", corrected)

    def test_forced_chatgpt_switch_waits_for_replacement_credential(self):
        dashboard = admira_tool_bridge.load_dashboard()
        originals = {
            "environment": dashboard.hermes_environment,
            "ready": dashboard.browserless_chatgpt_ready,
            "nudge": dashboard.nudge_hermes_browserless_autodrive,
            "refresh": dashboard.refresh_telegram_gateway_after_agent_model_change,
            "cache": dashboard.cache_codex_session_status,
            "update": dashboard.update_env_values,
            "catalog": dashboard.codex_model_catalog,
        }
        old_state = dict(dashboard.HERMES_LOGIN_STATE)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                (home / "auth.json").write_text('{"account":"old"}', encoding="utf-8")
                dashboard.hermes_environment = lambda _config: {"CODEX_HOME": str(home)}
                dashboard.browserless_chatgpt_ready = lambda _config: (True, "authenticated")
                dashboard.nudge_hermes_browserless_autodrive = lambda: None
                dashboard.refresh_telegram_gateway_after_agent_model_change = lambda *_args, **_kwargs: {"started": True}
                dashboard.cache_codex_session_status = lambda *_args, **_kwargs: None
                delayed_updates = []
                dashboard.update_env_values = lambda values: delayed_updates.append(values)
                dashboard.codex_model_catalog = lambda **_kwargs: {"models": []}
                config = SimpleNamespace(hermes_model="gpt-5.6-terra")
                baseline = dashboard.codex_cli_auth_fingerprint(config)
                process_state = {"returncode": None}
                dashboard.HERMES_LOGIN_STATE.clear()
                dashboard.HERMES_LOGIN_STATE.update({
                    "id": "switch-test",
                    "proc": SimpleNamespace(poll=lambda: process_state["returncode"]),
                    "output": "https://auth.openai.com/codex/device\nABCD-EFGH",
                    "force_reconnect": True,
                    "baseline_auth_fingerprint": baseline,
                })
                waiting = dashboard.hermes_browserless_snapshot(config)
                self.assertNotEqual(waiting.get("status"), "completed")
                self.assertFalse(delayed_updates)
                (home / "auth.json").write_text('{"account":"new"}', encoding="utf-8")
                process_state["returncode"] = 0
                completed = dashboard.hermes_browserless_snapshot(config)
                self.assertEqual(completed.get("status"), "completed")
                # Polling is read-only.  The process finalizer owns the single
                # durable environment update after the replacement login has
                # actually exited and its credential was imported.
                self.assertFalse(delayed_updates)
        finally:
            dashboard.hermes_environment = originals["environment"]
            dashboard.browserless_chatgpt_ready = originals["ready"]
            dashboard.nudge_hermes_browserless_autodrive = originals["nudge"]
            dashboard.refresh_telegram_gateway_after_agent_model_change = originals["refresh"]
            dashboard.cache_codex_session_status = originals["cache"]
            dashboard.update_env_values = originals["update"]
            dashboard.codex_model_catalog = originals["catalog"]
            dashboard.HERMES_LOGIN_STATE.clear()
            dashboard.HERMES_LOGIN_STATE.update(old_state)

    def test_campaign_request_wins_over_incidental_business_phrase_in_ad_copy(self):
        prompt = (
            "Crea ahora una campaña real de WhatsApp completamente pausada. "
            "Usa el mensaje exacto: Hola, quiero asesoría legal para mi empresa."
        )
        self.assertEqual(
            admira_hermes_runtime_patch._nvidia_request_profile([
                {"role": "user", "content": prompt},
            ]),
            "messaging_campaign",
        )

    def test_campaign_destination_router_honors_natural_negations(self):
        cases = (
            (
                "Crea una campaña hacia Facebook Messenger. No uses WhatsApp ni Instagram Direct.",
                "create_messaging_campaign",
            ),
            (
                "Crea una campaña de WhatsApp; no uses Messenger.",
                "create_whatsapp_campaign",
            ),
            (
                "Crea una campaña para Instagram Direct, sin WhatsApp.",
                "create_messaging_campaign",
            ),
        )
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                self.assertEqual(
                    admira_hermes_runtime_patch._admira_destination_campaign_creator([
                        {"role": "user", "content": prompt},
                    ]),
                    expected,
                )

    def test_short_confirmation_keeps_destination_and_existing_creative_from_two_prior_turns(self):
        messages = [
            {
                "role": "user",
                "content": (
                    "Campaña de WhatsApp. Reutiliza la imagen existente de ayer; "
                    "no generes otra. Estos son los conjuntos A y B."
                ),
            },
            {"role": "assistant", "content": "Conservo la primera parte y espero la segunda."},
            {
                "role": "user",
                "content": "Estos son los conjuntos C y D. No crees nada todavía.",
            },
            {"role": "assistant", "content": "Tengo los cuatro conjuntos y espero confirmación."},
            {"role": "user", "content": "Sí, procede ahora exactamente como acordamos."},
        ]
        self.assertEqual(
            admira_hermes_runtime_patch._admira_destination_campaign_creator(messages),
            "create_whatsapp_campaign",
        )
        self.assertTrue(admira_hermes_runtime_patch._admira_existing_creative_reuse_requested(messages))

        tools = [
            self._admira_tool(name)
            for name in sorted(
                admira_hermes_runtime_patch.ADMIRA_CAMPAIGN_CREATOR_TOOLS
                | admira_hermes_runtime_patch.ADMIRA_CAMPAIGN_CREATION_SUPPORT_TOOLS
            )
        ]
        routed = admira_hermes_runtime_patch._admira_route_request_tools({
            "messages": messages,
            "tools": tools,
        })
        names = {
            admira_hermes_runtime_patch._nvidia_normalize_tool_name(
                admira_hermes_runtime_patch._nvidia_tool_name(tool)
            )
            for tool in routed["tools"]
        }
        self.assertEqual(
            names & admira_hermes_runtime_patch.ADMIRA_CAMPAIGN_CREATOR_TOOLS,
            set(),
        )
        self.assertIn("preflight_campaign", names)
        self.assertNotIn("codex_image_generate", names)
        self.assertNotIn("codex_creative_plan", names)

    def test_active_tool_call_count_is_scoped_to_current_buyer_turn(self):
        messages = [
            {"role": "user", "content": "Crea WhatsApp"},
            {"role": "assistant", "tool_calls": [{"function": {"name": "mcp_admira_create_whatsapp_campaign"}}]},
            {"role": "tool", "name": "mcp_admira_create_whatsapp_campaign", "content": "retry"},
            {"role": "assistant", "tool_calls": [{"function": {"name": "mcp_admira_create_whatsapp_campaign"}}]},
            {"role": "tool", "name": "mcp_admira_create_whatsapp_campaign", "content": "failed"},
        ]
        self.assertEqual(
            admira_hermes_runtime_patch._nvidia_active_tool_call_count(
                messages, "create_whatsapp_campaign"
            ),
            2,
        )
        routed = admira_hermes_runtime_patch._admira_route_request_tools({
            "messages": messages,
            "tools": [self._admira_tool("create_whatsapp_campaign")],
        })
        self.assertEqual(routed["tools"], [])
        messages.append({"role": "user", "content": "Otro asunto"})
        self.assertEqual(
            admira_hermes_runtime_patch._nvidia_active_tool_call_count(
                messages, "create_whatsapp_campaign"
            ),
            0,
        )

    def test_deferred_campaign_part_exposes_no_creation_tools(self):
        messages = [{
            "role": "user",
            "content": "Estos son los conjuntos C y D. Todavía no crees nada; espera mi mensaje final.",
        }]
        self.assertTrue(admira_hermes_runtime_patch._admira_campaign_creation_deferred(messages))
        tools = [
            self._admira_tool("create_whatsapp_campaign"),
            self._admira_tool("create_messaging_campaign"),
            self._admira_tool("codex_image_generate"),
            self._admira_tool("get_real_meta_context"),
        ]
        routed = admira_hermes_runtime_patch._admira_route_request_tools({
            "messages": messages,
            "tools": tools,
        })
        names = {
            admira_hermes_runtime_patch._nvidia_normalize_tool_name(
                admira_hermes_runtime_patch._nvidia_tool_name(tool)
            )
            for tool in routed["tools"]
        }
        self.assertNotIn("create_whatsapp_campaign", names)
        self.assertNotIn("create_messaging_campaign", names)
        self.assertNotIn("codex_image_generate", names)

    def test_short_continuation_recovers_recent_destination_and_reuse_decision(self):
        original_root = admira_hermes_runtime_patch.os.environ.get("ADMIRA_PRODUCT_ROOT")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                compiler_dir = root / "dashboard" / "data" / "campaign-compiler"
                compiler_dir.mkdir(parents=True)
                (compiler_dir / "latest-campaign.md").write_text(
                    "- Destination contract: `whatsapp`\n"
                    "- Creative reused: /app/output/existing.png (approved)\n"
                    "- creative_approved: true\n",
                    encoding="utf-8",
                )
                admira_hermes_runtime_patch.os.environ["ADMIRA_PRODUCT_ROOT"] = str(root)
                messages = [{"role": "user", "content": "Sí, procede con la campaña completa."}]
                self.assertEqual(
                    admira_hermes_runtime_patch._admira_destination_campaign_creator(messages),
                    "create_whatsapp_campaign",
                )
                self.assertTrue(
                    admira_hermes_runtime_patch._admira_existing_creative_reuse_requested(messages)
                )
        finally:
            if original_root is None:
                admira_hermes_runtime_patch.os.environ.pop("ADMIRA_PRODUCT_ROOT", None)
            else:
                admira_hermes_runtime_patch.os.environ["ADMIRA_PRODUCT_ROOT"] = original_root

    def test_initial_campaign_request_resolves_destination_but_stays_in_planning(self):
        """A destination is understood without exposing premature creation."""
        creator_names = sorted(admira_hermes_runtime_patch.ADMIRA_CAMPAIGN_CREATOR_TOOLS)
        support_names = sorted(admira_hermes_runtime_patch.ADMIRA_CAMPAIGN_CREATION_SUPPORT_TOOLS)
        tools = [self._admira_tool(name) for name in creator_names + support_names]
        tools.extend([
            {"type": "function", "function": {"name": "memory_search"}},
            {"type": "function", "function": {"name": "web_search"}},
        ])
        cases = (
            ("Crea una campaña de WhatsApp pausada", "create_whatsapp_campaign"),
            ("Crea una campaña de Messenger pausada", "create_messaging_campaign"),
            ("Crea una campaña de formulario instantáneo pausada", "create_lead_form_campaign"),
            ("Crea una campaña para mi sitio web pausada", "create_website_campaign"),
            ("Crea una campaña de instalación de app pausada", "create_app_campaign"),
            ("Crea una campaña de reconocimiento pausada", "create_on_meta_campaign"),
        )
        for prompt, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(
                    admira_hermes_runtime_patch._admira_destination_campaign_creator([
                        {"role": "user", "content": prompt},
                    ]),
                    expected,
                )
                routed = admira_hermes_runtime_patch._admira_route_request_tools({
                    "messages": [{"role": "user", "content": prompt}],
                    "tools": tools,
                })
                names = {
                    admira_hermes_runtime_patch._nvidia_normalize_tool_name(
                        admira_hermes_runtime_patch._nvidia_tool_name(tool)
                    )
                    for tool in routed.get("tools", [])
                }
                visible_creators = names & admira_hermes_runtime_patch.ADMIRA_CAMPAIGN_CREATOR_TOOLS
                self.assertEqual(visible_creators, set())
                self.assertIn("preflight_campaign", names)
                self.assertNotIn("codex_image_generate", names)
                self.assertIn("list_recent_creatives", names)
                self.assertIn("select_meta_oauth_workspace", names)
                self.assertIn("memory_search", names)
                self.assertIn("web_search", names)
                self.assertTrue(any(
                    "CAMPAIGN STRATEGY-FIRST RULE" in str(message.get("content") or "")
                    for message in routed.get("messages") or []
                ))

    def test_destination_brief_includes_verbatim_recent_buyer_messages(self):
        messages = [
            {"role": "user", "content": "Parte uno: Bogotá, Meta city ID 458130."},
            {"role": "assistant", "content": "Conservado."},
            {"role": "user", "content": "Parte dos: Facebook Video Feeds exclusivamente."},
            {"role": "assistant", "content": "Conservado."},
            {"role": "user", "content": "Confirmación final: crea todo PAUSED."},
        ]
        source = admira_hermes_runtime_patch._admira_campaign_verbatim_source(messages)
        self.assertIn("Meta city ID 458130", source)
        self.assertIn("Facebook Video Feeds", source)
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[
            SimpleNamespace(function=SimpleNamespace(
                name="mcp_admira_create_website_campaign",
                arguments=json.dumps({"brief_markdown": "Resumen que omitió Video Feeds."}),
            ))
        ]))])
        enriched = admira_hermes_runtime_patch._admira_attach_verbatim_campaign_source(response, source)
        arguments = json.loads(enriched.choices[0].message.tool_calls[0].function.arguments)
        self.assertIn("## Verbatim recent buyer messages (authoritative)", arguments["brief_markdown"])
        self.assertIn("Facebook Video Feeds exclusivamente", arguments["brief_markdown"])
        # A second wrapper layer must not append the source twice.
        admira_hermes_runtime_patch._admira_attach_verbatim_campaign_source(enriched, source)
        self.assertEqual(
            enriched.choices[0].message.tool_calls[0].function.arguments.count(
                "## Verbatim recent buyer messages (authoritative)"
            ),
            1,
        )

    def test_ambiguous_campaign_keeps_destination_choice_available(self):
        tools = [self._admira_tool(name) for name in admira_hermes_runtime_patch.ADMIRA_CAMPAIGN_CREATOR_TOOLS]
        routed = admira_hermes_runtime_patch._admira_route_request_tools({
            "messages": [{"role": "user", "content": "Quiero crear una campaña, ayúdame a elegir el destino"}],
            "tools": tools,
        })
        names = {
            admira_hermes_runtime_patch._nvidia_normalize_tool_name(
                admira_hermes_runtime_patch._nvidia_tool_name(tool)
            )
            for tool in routed.get("tools", [])
        }
        self.assertEqual(names, admira_hermes_runtime_patch.ADMIRA_CAMPAIGN_CREATOR_TOOLS)

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
            ("campaign_execution", "Prepara la campaña de ventas pausada con los creativos aprobados", 8192, "create_on_meta_campaign"),
            ("messaging_campaign", "Crea una campaña de WhatsApp con el mensaje inicial aprobado", 8192, "create_whatsapp_campaign"),
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
        all_names = sorted(
            set().union(*admira_hermes_runtime_patch.ADMIRA_NVIDIA_TOOL_PROFILES.values())
            | admira_hermes_runtime_patch.ADMIRA_CAMPAIGN_CREATION_SUPPORT_TOOLS
        )
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
                {"create_on_meta_campaign", "pause_campaign"},
                {"codex_image_generate", "generate_motion_graphic_video", "create_lead_form"},
            ),
            (
                "Prepara la campaña de WhatsApp con el mensaje inicial aprobado.",
                {"create_whatsapp_campaign", "codex_image_generate", "list_recent_creatives"},
                {"delete_campaign", "create_messaging_campaign", "create_lead_form"},
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
                self.assertLessEqual(len(names), 30)

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
            ["name", "questions", "privacy_policy_url"],
        )
        self.assertIn("questions", parameters["properties"])

    def test_nvidia_restores_empty_hermes_mcp_parameters_without_mutating_registry(self):
        original = self._admira_tool("create_lead_form")
        original["function"]["parameters"] = {"type": "object", "additionalProperties": True}
        restored = admira_hermes_runtime_patch._nvidia_restore_admira_tool_schemas([original])
        self.assertEqual(original["function"]["parameters"].get("properties"), None)
        self.assertIn("page_id", restored[0]["function"]["parameters"]["properties"])
        self.assertIn("questions", restored[0]["function"]["parameters"]["required"])

    def test_restores_canonical_schema_for_flat_responses_tools(self):
        original = {
            "type": "function",
            "name": "mcp_admira_save_business_memory",
            "description": "Save business memory",
            "strict": False,
            "parameters": {"type": "object", "properties": {}},
        }

        restored = admira_hermes_runtime_patch._nvidia_restore_admira_tool_schemas(
            [original]
        )

        self.assertEqual(original["parameters"], {"type": "object", "properties": {}})
        parameters = restored[0]["parameters"]
        self.assertIn("buyer_evidence", parameters["required"])
        self.assertIn("confirm_profile_review", parameters["properties"])
        self.assertIn("strategic_topics", parameters["properties"])
        self.assertEqual(restored[0]["description"], original["description"])
        self.assertFalse(restored[0]["strict"])

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
            ["deepseek-ai/deepseek-v4-flash-0731", "z-ai/glm-5.2", "openai/gpt-oss-20b"],
        )

    def test_nvidia_uses_one_attempt_and_serial_crons(self):
        policy = hermes_bridge.inference_runtime_policy({
            "brain": "nvidia_nim",
            "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
            "model": "z-ai/glm-5.2",
        })
        self.assertEqual(policy["api_max_retries"], 0)
        self.assertEqual(policy["max_turns"], 8)
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

    def test_gemini_free_tier_compacts_before_tpm_exhaustion(self):
        brain = {
            "brain": "gemini",
            "provider": hermes_bridge.ADMIRA_GEMINI_PROVIDER,
            "model": "gemini-3.5-flash-lite",
        }
        policy = hermes_bridge.inference_runtime_policy(brain)
        self.assertEqual(policy["compression_threshold"], 0.06)
        self.assertEqual(policy["compression_protect_last_n"], 12)
        self.assertEqual(policy["compression_hard_message_limit"], 400)
        config_text = """
model:
  provider: "gemini"
  default: "gemini-3.5-flash-lite"
compression:
  threshold: 0.85
  protect_last_n: 20
  hygiene_hard_message_limit: 400
"""
        self.assertTrue(hermes_bridge._cli_hermes_config_needs_write(config_text, brain))
        generated = "\n".join(hermes_bridge.hermes_compression_config_lines(None, brain, policy))
        self.assertIn("threshold: 0.06", generated)
        self.assertIn("protect_last_n: 12", generated)
        self.assertIn("hygiene_hard_message_limit: 400", generated)

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
        self.assertIn("compact compiled procedure", profile)

    def test_root_agent_profile_is_concise_outcome_based_and_schema_driven(self):
        profile = hermes_bridge.combined_agent_rules()
        self.assertLess(len(profile), 22000)
        self.assertIn("Understand the buyer's meaning from the whole conversation", profile)
        self.assertIn("Tool descriptions and JSON schemas are authoritative", profile)
        self.assertIn("use exactly one destination creator", profile)
        self.assertIn("mcp_admira_create_whatsapp_campaign", profile)
        self.assertIn("mcp_admira_create_lead_form_campaign", profile)
        self.assertIn("mcp_admira_create_website_campaign", profile)
        self.assertIn("mcp_admira_edit_campaign", profile)
        self.assertIn("mcp_admira_codex_image_generate", profile)
        self.assertIn("mcp_admira_connect_chatgpt", profile)
        self.assertNotIn("Live Meta First On Every Turn", profile)
        self.assertNotIn("Before every buyer-facing turn", profile)

    def test_root_agent_profile_uses_compiled_procedure_instead_of_large_skill_map(self):
        profile = hermes_bridge.combined_agent_rules()
        self.assertIn("## Compiled operating procedures", profile)
        self.assertIn("state-based, not phrase-based", profile)
        self.assertNotIn("## Mandatory MCP → primary skill map", profile)
        self.assertNotIn("read that primary skill's complete", profile)

    def test_every_public_mcp_description_requires_its_primary_skill(self):
        definitions = dict(admira_mcp_server.TOOL_DEFINITIONS)
        self.assertEqual(set(definitions), set(mcp_skill_registry.MCP_PRIMARY_SKILL))
        for name, skill in mcp_skill_registry.MCP_PRIMARY_SKILL.items():
            self.assertIn(
                f"read `skills/{skill}/SKILL.md` completely before calling this MCP",
                definitions[name],
            )

    def test_primary_skill_read_audit_uses_exact_session_and_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.db"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, tool_calls TEXT)"
            )
            calls = [{
                "function": {
                    "name": "read_file",
                    "arguments": json.dumps({
                        "path": "/app/dashboard/data/hermes-workspace/current/skills/campaign-strategy/SKILL.md"
                    }),
                }
            }]
            connection.execute(
                "INSERT INTO messages(session_id, role, tool_calls) VALUES (?, ?, ?)",
                ("session-a", "assistant", json.dumps(calls)),
            )
            connection.commit()
            connection.close()
            self.assertTrue(
                admira_hermes_runtime_patch._session_has_read_primary_skill(
                    "session-a", "skills/campaign-strategy/SKILL.md", state_db_path=db_path
                )
            )
            self.assertFalse(
                admira_hermes_runtime_patch._session_has_read_primary_skill(
                    "session-b", "skills/campaign-strategy/SKILL.md", state_db_path=db_path
                )
            )
            self.assertFalse(
                admira_hermes_runtime_patch._session_has_read_primary_skill(
                    "session-a", "skills/meta-campaign-execution/SKILL.md", state_db_path=db_path
                )
            )

    def test_product_prompt_removes_generic_cli_action_pressure(self):
        admira_hermes_runtime_patch._patch_product_prompt_guidance()
        self.assertIn("Tools execute buyer outcomes", prompt_builder.TOOL_USE_ENFORCEMENT_GUIDANCE)
        self.assertNotIn("You MUST use your tools to take action", prompt_builder.TOOL_USE_ENFORCEMENT_GUIDANCE)
        self.assertIn("For advice or planning, a useful answer is completion", prompt_builder.TASK_COMPLETION_GUIDANCE)
        self.assertNotIn("Keep going", prompt_builder.GOOGLE_MODEL_OPERATIONAL_GUIDANCE)
        self.assertIn("buyer-facing chat transport", prompt_builder.PLATFORM_HINTS["cli"])
        self.assertIn("MEDIA:/absolute/path", prompt_builder.PLATFORM_HINTS["cli"])
        self.assertIn("not a coding agent", coding_context.CODING_PROFILE.guidance)
        self.assertIsNone(
            memory_tool.MemoryStore.format_for_system_prompt(object(), "memory")
        )

    def test_product_request_removes_only_hermes_personal_state_tools(self):
        tools = [
            {"type": "function", "function": {"name": "memory"}},
            {"type": "function", "function": {"name": "skill_manage"}},
            self._admira_tool("codex_image_generate"),
            {"type": "function", "function": {"name": "read_file"}},
        ]
        filtered = admira_hermes_runtime_patch._remove_hermes_personal_state_tools(
            {"tools": tools, "messages": []}
        )
        names = {
            admira_hermes_runtime_patch._nvidia_tool_name(tool)
            for tool in filtered["tools"]
        }
        self.assertEqual(names, {"mcp_admira_codex_image_generate", "read_file"})

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
                self.assertEqual(chain, [{
                    "provider": "openai-codex",
                    "model": "gpt-5.6-luna",
                }])
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

    def test_nvidia_live_catalog_never_adds_a_nvidia_fallback(self):
        """NVIDIA is not a fallback even when an old live catalog remains."""
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
                self.assertEqual(chain, [])
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

    def test_gemini_uses_only_luna_subscription_fallback_and_omits_nvidia_catalog(self):
        original_connections = hermes_bridge.agent_model_connections
        original_health = hermes_bridge.codex_credential_health
        try:
            hermes_bridge.agent_model_connections = lambda _config, include_secrets=False: {
                "nvidia_nim": {
                    "configured": True,
                    "base_url": hermes_bridge.ADMIRA_NVIDIA_DEFAULT_BASE_URL,
                    "model": "minimaxai/minimax-m3",
                },
            }
            hermes_bridge.codex_credential_health = lambda _config: {
                "state": "stored", "reauth_required": False,
            }
            brain = {
                "brain": "gemini",
                "provider": "gemini",
                "model": "gemini-3.5-flash-lite",
            }
            self.assertEqual(
                hermes_bridge.admira_inference_fallback_chain(object(), brain),
                [{"provider": "openai-codex", "model": "gpt-5.6-luna"}],
            )
            config_text = "\n".join(hermes_bridge.admira_connected_model_config_lines(object(), brain))
            self.assertNotIn("admira-nvidia", config_text)
        finally:
            hermes_bridge.agent_model_connections = original_connections
            hermes_bridge.codex_credential_health = original_health

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
