import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_dashboard():
    spec = importlib.util.spec_from_file_location("oauth_dashboard_test", ROOT / "dashboard" / "monitoring-dashboard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MetaOAuthConnectionTests(unittest.TestCase):
    def setUp(self):
        self.dashboard = load_dashboard()
        self.temp = tempfile.TemporaryDirectory()
        data = Path(self.temp.name)
        self.patches = [
            patch.object(self.dashboard, "META_OAUTH_PENDING_FILE", data / "pending.json"),
            patch.object(self.dashboard, "META_OAUTH_CONNECTION_FILE", data / "connection.json"),
            patch.object(self.dashboard, "TELEGRAM_RUNTIME_CHAT_FILE", data / "telegram-chat.json"),
            patch.object(self.dashboard, "AD_CONFIG_FILE", data / "ad-config.json"),
            patch.object(self.dashboard, "ACTIONS_FILE", data / "actions.json"),
            patch.object(self.dashboard, "BUSINESS_PROFILE_FILE", data / "business-profile.json"),
        ]
        for item in self.patches:
            item.start()
        self.config = SimpleNamespace(
            meta_oauth_broker_url="https://admiraia.uboost.lat/api/meta-oauth",
            telegram_chat_id="123",
            telegram_bot_token="bot-token",
            license_device_id="device",
            license_key="license",
            meta_access_token="",
            meta_access_token_kind="",
        )

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_start_uses_one_time_handoff_and_sends_plain_url_to_telegram(self):
        sent = []
        with patch.object(self.dashboard, "load_config", return_value=self.config), \
             patch.object(self.dashboard, "resolved_device_id", return_value="device"), \
             patch.object(self.dashboard, "_meta_oauth_request", return_value={"ok": True, "request_id": "r" * 43, "authorization_url": "https://facebook.example/oauth", "expires_in_seconds": 900}), \
             patch.object(self.dashboard, "telegram_bot_request", side_effect=lambda _c, _m, payload, **_k: sent.append(payload)):
            result = self.dashboard.social_oauth_start({})
        self.assertTrue(result["sent_to_telegram"])
        pending = self.dashboard._meta_oauth_pending()
        self.assertEqual(pending["request_id"], "r" * 43)
        self.assertGreater(len(pending["handoff_secret"]), 32)
        self.assertNotIn(pending["handoff_secret"], str(sent))
        self.assertIn("https://facebook.example/oauth", sent[0]["text"])
        self.assertNotIn("reply_markup", sent[0])

    def test_workspace_picker_lists_accounts_and_pages_without_buttons(self):
        sent = []
        connection = {
            "accounts": [
                {"id": "act_1", "name": "Cuenta Uno", "currency": "USD"},
                {"id": "act_2", "name": "Cuenta Dos", "currency": "COP"},
            ],
            "pages": [
                {"id": "page_1", "name": "Página Uno", "access_token": "p" * 40},
                {"id": "page_2", "name": "Página Dos", "access_token": "p" * 40},
            ],
        }
        with patch.object(self.dashboard, "load_config", return_value=self.config), \
             patch.object(self.dashboard, "telegram_bot_request", side_effect=lambda _c, _m, payload, **_k: sent.append(payload)):
            self.dashboard._send_meta_oauth_account_picker(self.config, connection, "123")
        self.assertEqual(len(sent), 1)
        self.assertIn("Cuenta Uno", sent[0]["text"])
        self.assertIn("Página Dos", sent[0]["text"])
        self.assertIn("cuenta 1", sent[0]["text"])
        self.assertNotIn("reply_markup", sent[0])

    def test_start_uses_runtime_telegram_chat_when_dashboard_chat_is_not_available(self):
        sent = []
        self.config.telegram_chat_id = "telegram:legacy-channel"
        self.dashboard.write_private_json(self.dashboard.TELEGRAM_RUNTIME_CHAT_FILE, {"chat_id": "123456"})
        with patch.object(self.dashboard, "load_config", return_value=self.config), \
             patch.object(self.dashboard, "resolved_device_id", return_value="device"), \
             patch.object(self.dashboard, "_meta_oauth_request", return_value={"ok": True, "request_id": "r" * 43, "authorization_url": "https://facebook.example/oauth"}), \
             patch.object(self.dashboard, "telegram_bot_request", side_effect=lambda _c, _m, payload, **_k: sent.append(payload)), \
             patch.object(self.dashboard.threading, "Thread"):
            result = self.dashboard.social_oauth_start({})
        self.assertTrue(result["sent_to_telegram"])
        self.assertEqual(sent[0]["chat_id"], "123456")
        self.assertEqual(self.dashboard._meta_oauth_pending()["telegram_chat_id"], "123456")

    def test_apply_keeps_all_assets_and_waits_for_explicit_workspace_choice(self):
        credentials = {
            "user_token": "x" * 40,
            "expires_at": "2026-10-01T00:00:00Z",
            "user": {"id": "user", "name": "Buyer"},
            "accounts": [{"id": "act_1", "name": "One", "currency": "USD"}],
            "pages": [{"id": "page_1", "name": "Page", "access_token": "p" * 40, "instagram": None}],
        }
        updates = []
        with patch.object(self.dashboard, "update_env_values", side_effect=lambda values: updates.append(values)), \
             patch.object(self.dashboard, "save_setup_config", return_value={"saved": True}):
            result = self.dashboard._apply_meta_oauth_credentials(credentials)
        self.assertEqual(result["active_ad_account_id"], "")
        self.assertEqual(result["active_page_id"], "")
        token_update = next(update for update in updates if "META_ACCESS_TOKEN_KIND" in update)
        self.assertEqual(token_update["META_ACCESS_TOKEN_KIND"], "oauth")
        self.assertNotIn("user_token", str(result))

    def test_apply_keeps_business_discovered_pages_without_selecting_unpublishable_page(self):
        credentials = {
            "user_token": "x" * 40,
            "user": {"id": "user", "name": "Buyer"},
            "accounts": [{"id": "act_1", "name": "One", "currency": "USD"}],
            "pages": [
                {"id": "page_1", "name": "Usable", "access_token": "p" * 40},
                {"id": "page_2", "name": "Business client page", "sources": ["client_pages"], "business_ids": ["biz_1"]},
            ],
            "businesses": [{"id": "biz_1", "name": "Client portfolio"}],
        }
        with patch.object(self.dashboard, "update_env_values"), patch.object(self.dashboard, "save_setup_config", return_value={"saved": True}):
            result = self.dashboard._apply_meta_oauth_credentials(credentials)
        self.assertEqual(result["active_page_id"], "")
        self.assertEqual(len(result["pages"]), 2)
        self.assertFalse(next(item for item in result["pages"] if item["id"] == "page_2")["can_publish"])
        self.assertEqual(result["businesses"][0]["name"], "Client portfolio")

    def test_select_rejects_an_asset_not_returned_by_facebook(self):
        self.dashboard.write_private_json(self.dashboard.META_OAUTH_CONNECTION_FILE, {"connected": True, "accounts": [{"id": "act_1"}], "pages": [{"id": "page_1", "access_token": "p" * 40}]})
        with self.assertRaises(ValueError):
            self.dashboard.social_oauth_select({"ad_account_id": "act_2", "page_id": "page_1"})

    def test_telegram_workspace_selection_requires_account_before_page(self):
        self.dashboard.write_private_json(self.dashboard.META_OAUTH_CONNECTION_FILE, {
            "connected": True,
            "accounts": [{"id": "act_1", "name": "One", "currency": "USD"}],
            "pages": [{"id": "page_1", "name": "Page", "access_token": "p" * 40}],
        })
        updates = []
        with patch.object(self.dashboard, "update_env_values", side_effect=lambda value: updates.append(value)), \
             patch.object(self.dashboard, "save_setup_config", return_value={"saved": True}):
            account = self.dashboard.social_oauth_select_account("act_1")
            self.assertEqual(account["pages"][0]["id"], "page_1")
            result = self.dashboard.social_oauth_select_page("page_1")
        self.assertTrue(result["selected"])
        self.assertEqual(updates[-1]["META_AD_ACCOUNT_ID"], "act_1")

    def test_completed_business_enters_organic_strategy_before_branding_or_ads(self):
        profile = {"context_completed_at": "2026-08-16T00:00:00+00:00"}
        connected = {"connected": True, "active_ad_account_id": "act_1", "active_page_id": "page_1"}
        with patch.object(self.dashboard, "social_oauth_status", return_value=connected), patch.dict(os.environ, {"DAILY_SOCIAL_CONTENT_DECISION": ""}, clear=False):
            phase = self.dashboard.agent_onboarding_phase(profile)
        self.assertEqual(phase["phase"], "organic_content_strategy")
        self.assertEqual(phase["organic_content"], "pending")
        with patch.object(self.dashboard, "social_oauth_status", return_value=connected), patch.dict(os.environ, {"DAILY_SOCIAL_CONTENT_DECISION": "accepted_pending_setup"}, clear=False):
            phase = self.dashboard.agent_onboarding_phase(profile)
        self.assertEqual(phase["phase"], "branding_creatives_creation")

    def test_gateway_requires_oauth_before_business_discovery(self):
        import sys

        sys.path.insert(0, str(ROOT / "src"))
        import hermes_gateway

        prompt = hermes_gateway.gateway_prompt("es")
        self.assertIn("REGLA ESTRICTA DE PRIMERA VEZ", prompt)
        self.assertIn("el primer paso útil de una instalación nueva es conectar Facebook", prompt)
        self.assertIn("mcp_admira_get_meta_oauth_workspaces", prompt)
        self.assertIn("mcp_admira_get_meta_oauth_workspaces", prompt)
        self.assertIn("mcp_admira_start_meta_oauth_connection", prompt)
        self.assertIn("URL segura como texto visible normal", prompt)
        self.assertIn("nunca dependas de un botón", prompt)
        self.assertIn("con números/nombres breves", prompt)
        self.assertIn("mcp_admira_select_meta_oauth_workspace", prompt)
        self.assertIn("Después de conectar y elegir cuenta/Página: básicos del negocio", prompt)
        self.assertLess(
            prompt.index("mcp_admira_get_meta_oauth_workspaces"),
            prompt.index("Después de conectar y elegir cuenta/Página: básicos del negocio"),
        )

    def test_unconnected_installation_starts_with_facebook_connection(self):
        with patch.object(self.dashboard, "social_oauth_status", return_value={"connected": False}):
            phase = self.dashboard.agent_onboarding_phase({})
        self.assertEqual(phase["phase"], "facebook_connection")
        self.assertFalse(phase["facebook_connected"])

    def test_initial_telegram_setup_dispatches_oauth_without_model_permission(self):
        started = []
        with patch.object(self.dashboard, "telegram_settings", return_value={
            "enabled": True, "bot_configured": True, "chat_id": "123",
        }), patch.object(self.dashboard, "social_oauth_status", return_value={
            "connected": False, "pending": False,
        }), patch.object(self.dashboard, "social_oauth_start", side_effect=lambda payload: started.append(payload)):
            self.dashboard._dispatch_initial_meta_oauth_link(self.config)
        self.assertEqual(started, [{"telegram_chat_id": "123", "source": "initial_telegram_setup"}])

    def test_initial_telegram_setup_preserves_existing_meta_connection(self):
        with patch.object(self.dashboard, "telegram_settings", return_value={
            "enabled": True, "bot_configured": True, "chat_id": "123",
        }), patch.object(self.dashboard, "social_oauth_status", return_value={
            "connected": True, "pending": False,
        }), patch.object(self.dashboard, "social_oauth_start") as start:
            self.dashboard._dispatch_initial_meta_oauth_link(self.config)
        start.assert_not_called()

    def test_business_save_marks_organic_transition_without_sending_oauth(self):
        import sys

        sys.path.insert(0, str(ROOT / "src"))
        import admira_tool_bridge

        fake_dashboard = SimpleNamespace(
            execute_agent_tool=lambda _request, _payload: {
                "saved": True,
                "profile": {"context_completed_at": "2026-08-16T00:00:00+00:00"},
            },
            social_oauth_start=lambda _payload: self.fail("OAuth must not start immediately after business discovery"),
        )
        with patch.object(admira_tool_bridge, "load_dashboard", return_value=fake_dashboard):
            result = admira_tool_bridge.call_tool(
                "admira_save_business_memory",
                {"business_type": "clinica", "context_complete": True},
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["organic_content_strategy_required"])
        self.assertEqual(result["next_onboarding_phase"], "organic_content_strategy")
        self.assertNotIn("facebook_connection_handoff", result)


if __name__ == "__main__":
    unittest.main()
