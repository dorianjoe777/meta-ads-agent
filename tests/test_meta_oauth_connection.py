import importlib.util
import os
import tempfile
import threading
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
            patch.object(self.dashboard, "META_OAUTH_SELECTION_AUTH_FILE", data / "selection-auth.json"),
            patch.object(self.dashboard, "META_OAUTH_SELECTION_KEY_FILE", data / "selection-auth.key"),
            patch.object(self.dashboard, "TRUSTED_BUYER_TURN_FILE", data / "trusted-turn.json"),
            patch.object(self.dashboard, "TELEGRAM_RUNTIME_CHAT_FILE", data / "telegram-chat.json"),
            patch.object(self.dashboard, "ENV_FILE", data / ".env"),
            patch.object(self.dashboard, "AD_CONFIG_FILE", data / "ad-config.json"),
            patch.object(self.dashboard, "MANAGED_AD_ACCOUNTS_FILE", data / "managed-ad-accounts.json"),
            patch.object(self.dashboard, "TIMEZONE_PREFERENCE_FILE", data / "timezone-preference.json"),
            patch.object(self.dashboard, "INDIVIDUAL_BINDING_FILE", data / "individual-binding.json"),
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

    def test_workspace_picker_lists_pages_then_accounts_and_requires_numeric_pair(self):
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
        message = sent[0]["text"]
        self.assertIn("Cuenta Uno", message)
        self.assertIn("Página Dos", message)
        self.assertLess(message.index("PÁGINAS DE FACEBOOK"), message.index("CUENTAS PUBLICITARIAS"))
        self.assertIn("Responde únicamente con dos números", message)
        self.assertIn("1, 8", message)
        self.assertNotIn("nombres exactos", message)
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

    def test_status_applies_completed_handoff_without_background_process(self):
        self.dashboard.write_private_json(self.dashboard.META_OAUTH_PENDING_FILE, {
            "request_id": "request-id",
            "handoff_secret": "handoff-secret",
            "broker_url": "https://admiraia.uboost.lat/api/meta-oauth",
            "created_at": "2026-08-19T00:00:00+00:00",
        })
        credentials = {
            "user_token": "x" * 40,
            "expires_at": "2026-10-01T00:00:00Z",
            "user": {"id": "user", "name": "Buyer"},
            "accounts": [{"id": "act_1", "name": "One", "currency": "USD"}],
            "pages": [{"id": "page_1", "name": "Page", "access_token": "p" * 40}],
            "businesses": [{"id": "business_1", "name": "Business"}],
        }
        with patch.object(self.dashboard, "load_config", return_value=self.config), \
             patch.object(self.dashboard, "_meta_oauth_request", return_value={"ok": True, "status": "connected", "credentials": credentials}), \
             patch.object(self.dashboard, "update_env_values"), \
             patch.object(self.dashboard, "save_setup_config", return_value={"saved": True}), \
             patch.object(self.dashboard, "log_action"):
            result = self.dashboard.social_oauth_status()
        self.assertTrue(result["connected"])
        self.assertEqual(result["accounts"][0]["id"], "act_1")
        self.assertEqual(result["pages"][0]["id"], "page_1")
        self.assertFalse(result["pending"])
        self.assertFalse(self.dashboard.META_OAUTH_PENDING_FILE.exists())

    def test_status_preserves_current_trusted_turn_and_opens_intent_after_oauth_handoff(self):
        self.dashboard.write_private_json(self.dashboard.META_OAUTH_PENDING_FILE, {
            "request_id": "request-id",
            "handoff_secret": "handoff-secret",
            "broker_url": "https://admiraia.uboost.lat/api/meta-oauth",
            "created_at": "2026-08-19T00:00:00+00:00",
        })
        credentials = {
            "user_token": "x" * 40,
            "expires_at": "2026-10-01T00:00:00Z",
            "user": {"id": "user", "name": "Buyer"},
            "accounts": [{"id": "act_1", "name": "One", "currency": "USD"}],
            "pages": [{"id": "page_1", "name": "Page", "access_token": "p" * 40}],
        }
        with patch.object(self.dashboard, "load_config", return_value=self.config):
            self.dashboard.record_trusted_buyer_turn("123", "telegram:123", 5, "listo")
            with patch.object(self.dashboard, "_meta_oauth_request", return_value={"ok": True, "status": "connected", "credentials": credentials}), \
                 patch.object(self.dashboard, "update_env_values"), \
                 patch.object(self.dashboard, "save_setup_config", return_value={"saved": True}), \
                 patch.object(self.dashboard, "log_action"):
                result = self.dashboard.social_oauth_status()
        self.assertTrue(result["selection_required"])
        self.assertEqual(result["selection_authorization"]["status"], "waiting_for_buyer_selection")
        self.assertEqual(
            self.dashboard.read_json(self.dashboard.TRUSTED_BUYER_TURN_FILE, {}).get("message_sequence"),
            5,
        )

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

    def test_legacy_telegram_workspace_callbacks_cannot_bypass_numeric_pair(self):
        self.dashboard.write_private_json(self.dashboard.META_OAUTH_CONNECTION_FILE, {
            "connected": True,
            "accounts": [{"id": "act_1", "name": "One", "currency": "USD"}],
            "pages": [{"id": "page_1", "name": "Page", "access_token": "p" * 40}],
        })
        with self.assertRaisesRegex(ValueError, "par numérico completo"):
            self.dashboard.social_oauth_select_account("act_1")
        with self.assertRaisesRegex(ValueError, "par numérico completo"):
            self.dashboard.social_oauth_select_page("page_1")

    def test_natural_name_pair_is_rejected_until_buyer_sends_numeric_pair(self):
        connection = {
            "connected": True,
            "accounts": [
                {"id": "act_1", "name": "Cuenta Uno", "currency": "USD"},
                {"id": "act_2", "name": "Dorian Singularity", "currency": "COP"},
            ],
            "pages": [
                {"id": "page_1", "name": "Página Uno", "access_token": "p" * 40},
                {"id": "page_2", "name": "Rodeo - Car Detailing", "access_token": "q" * 40},
            ],
            "active_ad_account_id": "",
            "active_page_id": "",
        }
        self.dashboard.write_private_json(self.dashboard.META_OAUTH_CONNECTION_FILE, connection)
        with patch.object(self.dashboard, "load_config", return_value=self.config):
            self.dashboard.record_trusted_buyer_turn(
                "123",
                "telegram:123",
                10,
                "muéstrame las opciones",
            )
            status = self.dashboard.social_oauth_status()
            self.assertEqual(
                status["selection_authorization"]["status"],
                "waiting_for_buyer_selection",
            )
            natural_name_turn = self.dashboard.record_trusted_buyer_turn(
                "123",
                "telegram:123",
                11,
                "Usa Dorian Singularity con Rodeo Car Detailing",
            )
            self.assertEqual(natural_name_turn["meta_selection_authorization"]["status"], "rejected")
            self.assertEqual(
                natural_name_turn["meta_selection_authorization"]["reason"],
                "numeric_pair_required",
            )
            self.assertNotIn(
                "meta_selection_ticket",
                self.dashboard.read_json(self.dashboard.TRUSTED_BUYER_TURN_FILE, {}),
            )
            numeric_turn = self.dashboard.record_trusted_buyer_turn(
                "123",
                "telegram:123",
                12,
                "2, 2",
            )
            self.assertEqual(numeric_turn["meta_selection_authorization"]["status"], "authorized")
            status = self.dashboard.social_oauth_status()
        self.assertEqual(
            status["selection_authorization"]["status"],
            "authorized_pending_persistence",
        )
        trusted = self.dashboard.read_json(self.dashboard.TRUSTED_BUYER_TURN_FILE, {})
        self.assertTrue(trusted.get("meta_selection_ticket"))
        self.assertEqual(
            trusted["meta_selection_authorization"]["status"],
            "authorized",
        )

    def test_text_workspace_selection_uses_only_trusted_message_ticket(self):
        connection = {
            "connected": True,
            "accounts": [
                {"id": "act_1", "name": "Cuenta Uno", "currency": "USD"},
                {"id": "act_2", "name": "Cuenta Dos", "currency": "COP"},
            ],
            "pages": [
                {"id": "page_1", "name": "Página Uno", "access_token": "p" * 40},
                {"id": "page_2", "name": "Página Dos", "access_token": "q" * 40},
            ],
            "active_ad_account_id": "",
            "active_page_id": "",
        }
        self.dashboard.write_private_json(self.dashboard.META_OAUTH_CONNECTION_FILE, connection)
        with patch.object(self.dashboard, "load_config", return_value=self.config):
            first_turn = self.dashboard.record_trusted_buyer_turn("123", "telegram:123", 10, "listo")
            self.assertTrue(first_turn["recorded"])
            status = self.dashboard.social_oauth_status()
            self.assertTrue(status["selection_required"])
            self.assertEqual(status["selection_authorization"]["status"], "waiting_for_buyer_selection")
            selection_turn = self.dashboard.record_trusted_buyer_turn(
                "123",
                "telegram:123",
                11,
                "1, 2",
            )
            self.assertEqual(selection_turn["meta_selection_authorization"]["status"], "authorized")
            repeated_status = self.dashboard.social_oauth_status()
            self.assertEqual(
                repeated_status["selection_authorization"]["status"],
                "authorized_pending_persistence",
            )

            with patch.object(
                self.dashboard,
                "synchronize_selected_ad_account_timezone",
                return_value={"ok": True, "changed": False, "account": connection["accounts"][1]},
            ), patch.object(self.dashboard, "update_env_values"), \
                 patch.object(self.dashboard, "save_setup_config", return_value={"saved": True}), \
                 patch.object(
                     self.dashboard,
                     "_verify_meta_oauth_workspace_persistence",
                     side_effect=lambda *_args: self.dashboard._meta_oauth_connection(),
                 ), \
                 patch.object(self.dashboard, "log_action"):
                # These model-supplied IDs are deliberately wrong. The exact
                # pair authorized from the buyer's raw text is authoritative.
                result = self.dashboard.social_oauth_select({
                    "ad_account_id": "act_1",
                    "page_id": "page_2",
                })
        self.assertEqual(result["active_ad_account_id"], "act_2")
        self.assertEqual(result["active_page_id"], "page_1")
        self.assertTrue(result["selection_authorized_by_trusted_turn"])
        self.assertTrue(result["model_arguments_ignored"])
        self.assertNotIn(
            "meta_selection_ticket",
            self.dashboard.read_json(self.dashboard.TRUSTED_BUYER_TURN_FILE, {}),
        )

    def test_ticket_cleanup_cannot_overwrite_a_newer_trusted_buyer_turn(self):
        connection = {
            "connected": True,
            "accounts": [{"id": "act_1", "name": "Cuenta Uno", "currency": "USD"}],
            "pages": [{"id": "page_1", "name": "Página Uno", "access_token": "p" * 40}],
            "active_ad_account_id": "",
            "active_page_id": "",
        }
        self.dashboard.write_private_json(self.dashboard.META_OAUTH_CONNECTION_FILE, connection)
        cleanup_started = threading.Event()
        newer_turn_finished = threading.Event()
        worker_errors = []
        original_write_private_json = self.dashboard.write_private_json

        def delayed_turn_write(path, value, *args, **kwargs):
            is_consumed_ticket_cleanup = (
                Path(path) == Path(self.dashboard.TRUSTED_BUYER_TURN_FILE)
                and isinstance(value, dict)
                and value.get("meta_selection_authorization", {}).get("status") == "consumed"
                and "meta_selection_ticket" not in value
            )
            if is_consumed_ticket_cleanup:
                cleanup_started.set()
                # With the fix, the newer turn must wait for the trusted-turn
                # lock. Before the fix it completes here and is then replaced
                # by this stale cleanup write.
                newer_turn_finished.wait(timeout=0.25)
            return original_write_private_json(path, value, *args, **kwargs)

        def record_newer_turn():
            if not cleanup_started.wait(timeout=2):
                worker_errors.append(AssertionError("ticket cleanup never started"))
                return
            try:
                self.dashboard.record_trusted_buyer_turn(
                    "123", "telegram:123", 72, "hola después de seleccionar"
                )
            except Exception as exc:  # pragma: no cover - reported below
                worker_errors.append(exc)
            finally:
                newer_turn_finished.set()

        with patch.object(self.dashboard, "load_config", return_value=self.config):
            self.dashboard.record_trusted_buyer_turn(
                "123", "telegram:123", 70, "muéstrame las cuentas y páginas"
            )
            self.dashboard.social_oauth_status()
            authorized_turn = self.dashboard.record_trusted_buyer_turn(
                "123", "telegram:123", 71, "1, 1"
            )
            self.assertEqual(
                authorized_turn["meta_selection_authorization"]["status"],
                "authorized",
            )

            worker = threading.Thread(target=record_newer_turn, daemon=True)
            worker.start()
            with patch.object(
                self.dashboard,
                "_persist_meta_oauth_workspace_pair",
                return_value={
                    "selected": True,
                    "active_ad_account_id": "act_1",
                    "active_page_id": "page_1",
                    "_deferred_timezone_sync": {},
                },
            ), patch.object(
                self.dashboard,
                "_finalize_meta_oauth_workspace_persistence",
            ), patch.object(
                self.dashboard,
                "write_private_json",
                side_effect=delayed_turn_write,
            ):
                result = self.dashboard.social_oauth_select({})
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(worker_errors, [])
        self.assertTrue(result["selection_authorized_by_trusted_turn"])
        latest_turn = self.dashboard.read_json(self.dashboard.TRUSTED_BUYER_TURN_FILE, {})
        self.assertEqual(latest_turn.get("message_sequence"), 72)
        self.assertEqual(latest_turn.get("message"), "hola después de seleccionar")
        self.assertNotIn("meta_selection_ticket", latest_turn)

    def test_text_selection_rejects_missing_ticket_non_numeric_replies_and_replay(self):
        connection = {
            "connected": True,
            "accounts": [
                {"id": "act_1", "name": "Cuenta Uno", "currency": "USD"},
                {"id": "act_2", "name": "Cuenta Dos", "currency": "COP"},
            ],
            "pages": [
                {"id": "page_1", "name": "Página Uno", "access_token": "p" * 40},
                {"id": "page_2", "name": "Página Dos", "access_token": "q" * 40},
            ],
            "active_ad_account_id": "",
            "active_page_id": "",
        }
        self.dashboard.write_private_json(self.dashboard.META_OAUTH_CONNECTION_FILE, connection)
        with patch.object(self.dashboard, "load_config", return_value=self.config):
            self.dashboard.record_trusted_buyer_turn("123", "telegram:123", 20, "muéstrame las opciones")
            self.dashboard.social_oauth_status()
            partial = self.dashboard.record_trusted_buyer_turn("123", "telegram:123", 21, "2")
            self.assertEqual(partial["meta_selection_authorization"]["status"], "rejected")
            self.assertEqual(partial["meta_selection_authorization"]["reason"], "numeric_pair_required")
            with self.assertRaisesRegex(ValueError, "no fue autorizada"):
                self.dashboard.social_oauth_select({"ad_account_id": "act_2", "page_id": "page_1"})

            scoped_prose = self.dashboard.record_trusted_buyer_turn(
                "123", "telegram:123", 22, "página 1 y cuenta 2"
            )
            self.assertEqual(scoped_prose["meta_selection_authorization"]["status"], "rejected")
            self.assertEqual(scoped_prose["meta_selection_authorization"]["reason"], "numeric_pair_required")
            with self.assertRaisesRegex(ValueError, "no fue autorizada"):
                self.dashboard.social_oauth_select({"ad_account_id": "act_2", "page_id": "page_1"})

            completed = self.dashboard.record_trusted_buyer_turn("123", "telegram:123", 23, "1, 2")
            self.assertEqual(completed["meta_selection_authorization"]["status"], "authorized")
            with patch.object(
                self.dashboard,
                "synchronize_selected_ad_account_timezone",
                return_value={"ok": True, "changed": False, "account": connection["accounts"][1]},
            ), patch.object(self.dashboard, "update_env_values"), \
                 patch.object(self.dashboard, "save_setup_config", return_value={"saved": True}), \
                 patch.object(
                     self.dashboard,
                     "_verify_meta_oauth_workspace_persistence",
                     side_effect=lambda *_args: self.dashboard._meta_oauth_connection(),
                 ), \
                 patch.object(self.dashboard, "log_action"):
                result = self.dashboard.social_oauth_select({})
            self.assertTrue(result["selected"])
            with self.assertRaisesRegex(ValueError, "no fue autorizada"):
                self.dashboard.social_oauth_select({})

    def test_generic_delegation_cannot_authorize_workspace(self):
        connection = {
            "connected": True,
            "accounts": [{"id": "act_1", "name": "Cuenta Uno"}],
            "pages": [{"id": "page_1", "name": "Página Uno", "access_token": "p" * 40}],
            "active_ad_account_id": "",
            "active_page_id": "",
        }
        self.dashboard.write_private_json(self.dashboard.META_OAUTH_CONNECTION_FILE, connection)
        with patch.object(self.dashboard, "load_config", return_value=self.config):
            self.dashboard.record_trusted_buyer_turn("123", "telegram:123", 30, "listo")
            self.dashboard.social_oauth_status()
            rejected = self.dashboard.record_trusted_buyer_turn(
                "123", "telegram:123", 31, "usa lo que veas"
            )
            self.assertEqual(rejected["meta_selection_authorization"]["status"], "rejected")
            self.assertEqual(rejected["meta_selection_authorization"]["reason"], "numeric_pair_required")
            with self.assertRaisesRegex(ValueError, "no fue autorizada"):
                self.dashboard.social_oauth_select({"ad_account_id": "act_1", "page_id": "page_1"})

    def test_explicit_switch_rejects_scoped_partial_until_full_numeric_pair(self):
        connection = {
            "connected": True,
            "accounts": [
                {"id": "act_1", "name": "Cuenta Uno"},
                {"id": "act_2", "name": "Cuenta Dos"},
            ],
            "pages": [{"id": "page_1", "name": "Página Uno", "access_token": "p" * 40}],
            "active_ad_account_id": "act_1",
            "active_page_id": "page_1",
        }
        self.dashboard.write_private_json(self.dashboard.META_OAUTH_CONNECTION_FILE, connection)
        with patch.object(self.dashboard, "load_config", return_value=self.config):
            self.dashboard.record_trusted_buyer_turn("123", "telegram:123", 40, "quiero cambiar de cuenta")
            ordinary = self.dashboard.social_oauth_status()
            self.assertFalse(ordinary["selection_required"])
            switched = self.dashboard.social_oauth_workspaces_for_text_selection(allow_switch=True)
            self.assertEqual(switched["selection_authorization"]["mode"], "switch")
            scoped_partial = self.dashboard.record_trusted_buyer_turn(
                "123", "telegram:123", 41, "cambia la cuenta a la 2"
            )
            self.assertEqual(scoped_partial["meta_selection_authorization"]["status"], "rejected")
            self.assertEqual(scoped_partial["meta_selection_authorization"]["reason"], "numeric_pair_required")
            self.assertNotIn(
                "meta_selection_ticket",
                self.dashboard.read_json(self.dashboard.TRUSTED_BUYER_TURN_FILE, {}),
            )
            numeric_pair = self.dashboard.record_trusted_buyer_turn(
                "123", "telegram:123", 42, "1, 2"
            )
            self.assertEqual(numeric_pair["meta_selection_authorization"]["status"], "authorized")

    def test_selected_workspace_listing_cannot_open_switch_from_model_choice_alone(self):
        connection = {
            "connected": True,
            "accounts": [
                {"id": "act_1", "name": "Cuenta Uno"},
                {"id": "act_2", "name": "Cuenta Dos"},
            ],
            "pages": [{"id": "page_1", "name": "Página Uno", "access_token": "p" * 40}],
            "active_ad_account_id": "act_1",
            "active_page_id": "page_1",
        }
        self.dashboard.write_private_json(self.dashboard.META_OAUTH_CONNECTION_FILE, connection)
        with patch.object(self.dashboard, "load_config", return_value=self.config):
            self.dashboard.record_trusted_buyer_turn("123", "telegram:123", 45, "hola")
            result = self.dashboard.social_oauth_workspaces_for_text_selection(allow_switch=True)
        self.assertEqual(result["selection_authorization"]["status"], "not_required")
        authorizer = self.dashboard._meta_oauth_selection_authorizer()
        self.assertIsNone(authorizer.current_intent(chat_id="123", session_id="telegram:123"))

    def test_completed_reconnect_clears_old_selection_authorization(self):
        old_connection = {
            "connected": True,
            "accounts": [{"id": "act_1", "name": "Vieja"}],
            "pages": [{"id": "page_1", "name": "Vieja", "access_token": "p" * 40}],
            "active_ad_account_id": "",
            "active_page_id": "",
        }
        self.dashboard.write_private_json(self.dashboard.META_OAUTH_CONNECTION_FILE, old_connection)
        with patch.object(self.dashboard, "load_config", return_value=self.config):
            self.dashboard.record_trusted_buyer_turn("123", "telegram:123", 50, "listo")
            self.dashboard.social_oauth_status()
        credentials = {
            "user_token": "x" * 40,
            "user": {"id": "user", "name": "Buyer"},
            "accounts": [{"id": "act_2", "name": "Nueva"}],
            "pages": [{"id": "page_2", "name": "Nueva", "access_token": "q" * 40}],
        }
        with patch.object(self.dashboard, "update_env_values"), \
             patch.object(self.dashboard, "save_setup_config", return_value={"saved": True}):
            self.dashboard._apply_meta_oauth_credentials(credentials)
        retained_turn = self.dashboard.read_json(self.dashboard.TRUSTED_BUYER_TURN_FILE, {})
        self.assertNotIn("meta_selection_ticket", retained_turn)
        self.assertNotIn("meta_selection_authorization", retained_turn)
        authorizer = self.dashboard._meta_oauth_selection_authorizer()
        self.assertIsNone(authorizer.current_intent(chat_id="123", session_id="telegram:123"))

    def test_completed_business_requires_master_plan_before_branding_or_ads(self):
        strategic = self.dashboard.new_strategic_profile("page_1")
        strategic = self.dashboard.apply_strategic_profile_updates(
            strategic,
            {
                topic: {
                    "status": "confirmed",
                    "value": f"Confirmed {topic}",
                    "confirmation_state": "buyer_confirmed",
                }
                for topic in self.dashboard.STRATEGIC_PROFILE_TOPICS
            },
            page_id="page_1",
            trusted_buyer_confirmation=True,
            evidence={
                "source": "test_trusted_turn",
                "chat_id": "123",
                "session_id": "telegram:123",
                "transport": "telegram",
                "message_sequence": 10,
            },
        )
        strategic = self.dashboard.mark_strategic_profile_review_presented(
            strategic,
            page_id="page_1",
            after_buyer_message_sequence=10,
            assistant_message_hash="canonical-summary",
            evidence={
                "source": "test_outbound",
                "chat_id": "123",
                "session_id": "telegram:123",
                "transport": "telegram",
                "message_sequence": 10,
            },
        )
        strategic = self.dashboard.confirm_strategic_profile_revision(
            strategic,
            page_id="page_1",
            trusted_buyer_confirmation=True,
            evidence={
                "source": "test_trusted_review",
                "chat_id": "123",
                "session_id": "telegram:123",
                "transport": "telegram",
                "message_sequence": 11,
            },
        )
        profile = self.dashboard.embed_strategic_profile({}, strategic)
        connected = {"connected": True, "active_ad_account_id": "act_1", "active_page_id": "page_1"}
        with patch.object(self.dashboard, "social_oauth_status", return_value=connected), \
             patch.object(self.dashboard, "active_meta_page_id", return_value="page_1"), \
             patch.object(self.dashboard, "branding_creatives_status", return_value="pending"), \
             patch.dict(os.environ, {"DAILY_SOCIAL_CONTENT_DECISION": ""}, clear=False):
            phase = self.dashboard.agent_onboarding_phase(profile)
        self.assertEqual(phase["phase"], "business_master_plan")
        self.assertEqual(phase["organic_content"], "pending")
        with patch.object(self.dashboard, "social_oauth_status", return_value=connected), \
             patch.object(self.dashboard, "active_meta_page_id", return_value="page_1"), \
             patch.object(self.dashboard, "branding_creatives_status", return_value="pending"), \
             patch.dict(os.environ, {"DAILY_SOCIAL_CONTENT_DECISION": "accepted_pending_setup"}, clear=False):
            phase = self.dashboard.agent_onboarding_phase(profile)
        self.assertEqual(phase["phase"], "business_master_plan")

    def test_gateway_requires_oauth_before_business_discovery(self):
        spec = importlib.util.spec_from_file_location(
            "oauth_hermes_gateway_test",
            ROOT / "src" / "hermes_gateway.py",
        )
        hermes_gateway = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hermes_gateway)

        prompt = hermes_gateway.gateway_prompt("es")
        self.assertIn("REGLA ESTRICTA DE PRIMERA VEZ", prompt)
        self.assertIn("el primer paso útil de una instalación nueva es conectar Facebook", prompt)
        self.assertIn("mcp_admira_get_meta_oauth_workspaces", prompt)
        self.assertIn("mcp_admira_get_meta_oauth_workspaces", prompt)
        self.assertIn("mcp_admira_start_meta_oauth_connection", prompt)
        self.assertIn("URL segura como texto visible normal", prompt)
        self.assertIn("nunca dependas de un botón", prompt)
        self.assertIn("Lista primero todas las Páginas publicables y después todas las cuentas publicitarias", prompt)
        self.assertIn("Pide exactamente dos números sin texto adicional", prompt)
        self.assertIn("primero el número de Página y después el número de cuenta publicitaria", prompt)
        self.assertIn("Nombres, frases, confirmaciones o elecciones parciales no autorizan la selección", prompt)
        self.assertIn("mcp_admira_select_meta_oauth_workspace", prompt)
        self.assertIn("Nunca selecciones automáticamente ni infieras ningún activo", prompt)
        self.assertIn("verified_persisted: true", prompt)
        self.assertIn("Nunca llames la herramienta nativa `clarify`", prompt)
        onboarding_sequence = "Después de conectar y elegir cuenta/Página: completar el perfil estratégico íntegro asociado a esa Página"
        self.assertIn(onboarding_sequence, prompt)
        self.assertLess(
            prompt.index("mcp_admira_get_meta_oauth_workspaces"),
            prompt.index(onboarding_sequence),
        )

    def test_empty_business_profile_requires_strategic_onboarding(self):
        spec = importlib.util.spec_from_file_location(
            "onboarding_choice_hermes_gateway_test",
            ROOT / "src" / "hermes_gateway.py",
        )
        hermes_gateway = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hermes_gateway)
        prompt = hermes_gateway.gateway_prompt("es")
        bridge_source = (ROOT / "src" / "hermes_bridge.py").read_text(encoding="utf-8")
        runtime_source = (ROOT / "src" / "admira_hermes_runtime_patch.py").read_text(encoding="utf-8")
        skill = (ROOT / "agent" / "skills" / "business-onboarding" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("el onboarding estratégico es obligatorio", prompt)
        self.assertIn("no ofrezcas saltarlo", prompt)
        self.assertIn("onboarding estratégico es la siguiente etapa obligatoria", runtime_source)
        self.assertIn("begin the strategic business onboarding as a required product stage", skill)
        self.assertIn("Do not offer a skip-to-campaign path", skill)
        self.assertIn("strategic business onboarding is mandatory", bridge_source)
        self.assertIn("one decision-focused owner question at a time", bridge_source)
        for required_area in (
            "complete set of services/products",
            "ideal customers",
            "differentiators and proof",
            "service locations/markets",
            "delivery capacity",
            "prices or useful ranges",
            "contribution margins",
            "global business and marketing objectives",
            "prior advertising experience",
            "branding",
        ):
            self.assertIn(required_area, skill)

    def test_unconnected_installation_starts_with_facebook_connection(self):
        with patch.object(self.dashboard, "social_oauth_status", return_value={"connected": False}):
            phase = self.dashboard.agent_onboarding_phase({})
        self.assertEqual(phase["phase"], "facebook_connection")
        self.assertFalse(phase["facebook_connected"])

    def test_authorized_oauth_without_selection_does_not_request_new_permissions(self):
        oauth = {
            "connected": True,
            "active_ad_account_id": "",
            "active_page_id": "",
            "accounts": [{"id": "act_1"}, {"id": "act_2"}],
            "pages": [{"id": "page_1"}],
            "businesses": [{"id": "business_1"}],
        }
        with patch.object(self.dashboard, "social_oauth_status", return_value=oauth):
            phase = self.dashboard.agent_onboarding_phase({})
        self.assertFalse(phase["facebook_connected"])
        self.assertTrue(phase["facebook_authorized"])
        self.assertTrue(phase["workspace_selection_required"])
        self.assertEqual(phase["oauth_account_count"], 2)
        self.assertIn("No pidas permisos ni otro enlace", phase["next_step"])

    def test_live_context_distinguishes_workspace_selection_from_authorization(self):
        import sys

        sys.path.insert(0, str(ROOT / "src"))
        import admira_tool_bridge

        class FakeDashboard:
            def refresh_managed_real_metrics(self, **_kwargs):
                return {"ok": False, "reason": "missing_account", "message": "Missing Meta ad account."}

            def dashboard_payload(self):
                return {
                    "metrics": {}, "recommendations": [], "fatigue": [], "pending": [],
                    "audience_strategy": {}, "business_profile": {}, "brand_guides": {},
                    "agent_onboarding_phase": {},
                }

            def social_oauth_status(self):
                return {
                    "connected": True,
                    "active_ad_account_id": "",
                    "active_page_id": "",
                    "accounts": [{"id": "act_1", "name": "Account"}],
                    "pages": [{"id": "page_1", "name": "Page", "can_publish": True}],
                    "businesses": [{"id": "business_1", "name": "Business"}],
                }

        with patch.object(admira_tool_bridge, "load_dashboard", return_value=FakeDashboard()):
            result = admira_tool_bridge.call_tool("mcp_admira_get_real_meta_context", {})
        oauth = result["context"]["oauth_workspace"]
        self.assertTrue(oauth["authorized"])
        self.assertTrue(oauth["selection_required"])
        self.assertEqual(result["live_sync"]["reason"], "workspace_selection_required")
        self.assertIn("no solicites permisos ni otro enlace", result["metrics_source"]["notice"])

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

    def test_business_save_marks_branding_transition_without_sending_oauth(self):
        import sys

        sys.path.insert(0, str(ROOT / "src"))
        import admira_tool_bridge

        fake_dashboard = SimpleNamespace(
            execute_agent_tool=lambda _request, _payload: {
                "saved": True,
                "strategic_profile": {"complete": True},
            },
            social_oauth_start=lambda _payload: self.fail("OAuth must not start immediately after business discovery"),
            agent_onboarding_phase=lambda: {"phase": "branding_creatives_creation"},
        )
        with patch.object(admira_tool_bridge, "load_dashboard", return_value=fake_dashboard):
            result = admira_tool_bridge.call_tool(
                "admira_save_business_memory",
                {"business_type": "clinica", "confirmation_state": "buyer_confirmed"},
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["branding_required"])
        self.assertFalse(result["organic_content_strategy_required"])
        self.assertEqual(result["next_onboarding_phase"], "branding_creatives_creation")
        self.assertNotIn("facebook_connection_handoff", result)

    def test_logo_exploration_is_allowed_before_strategic_profile_completion(self):
        incomplete = {
            "strategic_profile": {
                "status": "collecting",
                "revision": 0,
                "confirmed_revision": None,
                "scope": {"page_id": "page_1"},
            }
        }
        with patch.object(self.dashboard, "active_meta_page_id", return_value="page_1"):
            logo = self.dashboard.strategic_product_action_eligibility(
                "brand_exploration", profile=incomplete, page_id="page_1"
            )
            campaign = self.dashboard.strategic_product_action_eligibility(
                "campaign_create", profile=incomplete, page_id="page_1"
            )
        self.assertTrue(logo["allowed"])
        self.assertEqual(logo["code"], "brand_exploration_allowed_during_onboarding")
        self.assertFalse(campaign["allowed"])

    def test_business_memory_accepts_value_source_confirmation_alias(self):
        normalized = self.dashboard.normalize_agent_tool_arguments({
            "buyer_evidence": "oh, atiendo en zonas de poblado",
            "markets": "El Poblado, Medellín",
            "value_source": "buyer_confirmed",
        })
        self.assertEqual(normalized["confirmation_state"], "buyer_confirmed")
        self.assertEqual(normalized["buyer_evidence"], "oh, atiendo en zonas de poblado")

    def test_failed_workspace_persistence_rolls_back_and_keeps_ticket_retryable(self):
        connection = {
            "connected": True,
            "accounts": [
                {"id": "act_1", "name": "Cuenta Uno", "currency": "USD"},
                {
                    "id": "act_2",
                    "name": "Cuenta Dos",
                    "currency": "COP",
                    "timezone_name": "America/Bogota",
                },
            ],
            "pages": [
                {"id": "page_1", "name": "Página Uno", "access_token": "p" * 40},
                {"id": "page_2", "name": "Página Dos", "access_token": "q" * 40},
            ],
            "active_ad_account_id": "act_1",
            "active_page_id": "page_1",
        }
        self.dashboard.write_private_json(self.dashboard.META_OAUTH_CONNECTION_FILE, connection)
        self.dashboard.ENV_FILE.write_text(
            "META_AD_ACCOUNT_ID=act_1\n"
            f"META_PUBLISHING_ACCESS_TOKEN={'p' * 40}\n"
            "META_PUBLISHING_TOKEN_SAVED_AT=before\n"
            "DAILY_BRIEF_TIMEZONE=America/New_York\n"
            "DAILY_BRIEF_TIMEZONE_SOURCE=buyer\n",
            encoding="utf-8",
        )
        self.dashboard.write_json(self.dashboard.AD_CONFIG_FILE, {
            "account": {"id": "act_1"},
            "creative": {"destination": {"page_id": "page_1"}},
        })
        self.dashboard.write_json(self.dashboard.MANAGED_AD_ACCOUNTS_FILE, {
            "active_ad_account_id": "act_1",
            "accounts": [{"id": "act_1"}],
        })
        self.dashboard.write_private_json(self.dashboard.TIMEZONE_PREFERENCE_FILE, {
            "timezone": "America/New_York",
            "source": "buyer",
            "account_id": "act_1",
        })

        def fake_timezone_sync(account, reconcile_crons=False):
            self.dashboard.save_timezone_preference("America/Bogota", "meta_ad_account", account_id="act_2")
            return {
                "ok": True,
                "changed": True,
                "timezone": "America/Bogota",
                "source": "meta_ad_account",
                "account_id": "act_2",
                "account": dict(account),
            }

        def fake_save_setup(payload):
            self.dashboard.update_env_values({"META_AD_ACCOUNT_ID": payload["ad_account_id"]})
            self.dashboard.write_json(self.dashboard.AD_CONFIG_FILE, {
                "account": {"id": payload["ad_account_id"]},
                "creative": {"destination": {"page_id": payload["page_id"]}},
            })
            self.dashboard.write_json(self.dashboard.MANAGED_AD_ACCOUNTS_FILE, {
                "active_ad_account_id": payload["ad_account_id"],
                "accounts": [{"id": payload["ad_account_id"]}],
            })
            return {"saved": True}

        tracked_paths = self.dashboard._meta_oauth_selection_snapshot_paths()
        before_files = {
            path: path.read_bytes() if path.exists() else None
            for path in tracked_paths
        }
        original_write_private_json = self.dashboard.write_private_json

        with patch.dict(os.environ, {
            "META_AD_ACCOUNT_ID": "act_1",
            "META_PUBLISHING_ACCESS_TOKEN": "p" * 40,
            "META_PUBLISHING_TOKEN_SAVED_AT": "before",
            "DAILY_BRIEF_TIMEZONE": "America/New_York",
            "DAILY_BRIEF_TIMEZONE_SOURCE": "buyer",
        }, clear=False), patch.object(self.dashboard, "load_config", return_value=self.config):
            self.dashboard.record_trusted_buyer_turn(
                "123", "telegram:123", 60, "quiero cambiar de cuenta y página"
            )
            listing = self.dashboard.social_oauth_workspaces_for_text_selection(allow_switch=True)
            self.assertEqual(listing["selection_authorization"]["status"], "waiting_for_buyer_selection")
            authorized_turn = self.dashboard.record_trusted_buyer_turn(
                "123", "telegram:123", 61, "2, 2"
            )
            self.assertEqual(authorized_turn["meta_selection_authorization"]["status"], "authorized")

            def fail_final_connection_write(path, value, *args, **kwargs):
                if (
                    Path(path) == Path(self.dashboard.META_OAUTH_CONNECTION_FILE)
                    and isinstance(value, dict)
                    and value.get("active_ad_account_id") == "act_2"
                ):
                    raise OSError("injected durable write failure")
                return original_write_private_json(path, value, *args, **kwargs)

            with patch.object(
                self.dashboard,
                "synchronize_selected_ad_account_timezone",
                side_effect=fake_timezone_sync,
            ), patch.object(
                self.dashboard,
                "save_setup_config",
                side_effect=fake_save_setup,
            ), patch.object(
                self.dashboard,
                "write_private_json",
                side_effect=fail_final_connection_write,
            ):
                with self.assertRaisesRegex(OSError, "injected durable write failure"):
                    self.dashboard.social_oauth_select({
                        "ad_account_id": "act_1",
                        "page_id": "page_1",
                    })

            for path, expected in before_files.items():
                actual = path.read_bytes() if path.exists() else None
                self.assertEqual(actual, expected, f"rollback mismatch for {path.name}")
            self.assertEqual(os.environ["META_AD_ACCOUNT_ID"], "act_1")
            self.assertEqual(os.environ["META_PUBLISHING_ACCESS_TOKEN"], "p" * 40)
            retained_turn = self.dashboard.read_json(self.dashboard.TRUSTED_BUYER_TURN_FILE, {})
            self.assertIn("meta_selection_ticket", retained_turn)

            with patch.object(
                self.dashboard,
                "synchronize_selected_ad_account_timezone",
                side_effect=fake_timezone_sync,
            ), patch.object(
                self.dashboard,
                "save_setup_config",
                side_effect=fake_save_setup,
            ), patch.object(
                self.dashboard,
                "reconcile_timezone_crons",
                return_value={"reconciled": True},
            ), patch.object(self.dashboard, "log_action"):
                result = self.dashboard.social_oauth_select({
                    "ad_account_id": "act_1",
                    "page_id": "page_1",
                })

            self.assertTrue(result["verified_persisted"])
            self.assertEqual(result["active_ad_account_id"], "act_2")
            self.assertEqual(result["active_page_id"], "page_2")
            self.assertTrue(result["model_arguments_ignored"])
            self.assertNotIn(
                "meta_selection_ticket",
                self.dashboard.read_json(self.dashboard.TRUSTED_BUYER_TURN_FILE, {}),
            )
            with self.assertRaisesRegex(ValueError, "no fue autorizada"):
                self.dashboard.social_oauth_select({})


if __name__ == "__main__":
    unittest.main()
