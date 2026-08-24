#!/usr/bin/env python3
import json
import os
import sys
import tempfile
import unittest
import asyncio
import importlib.util
import types
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import hermes_gateway
import admira_hermes_runtime_patch
import update_notifier


def load_dashboard():
    spec = importlib.util.spec_from_file_location(
        "startup_update_dashboard_test",
        ROOT / "dashboard" / "monitoring-dashboard.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UpdateNotifierTest(unittest.TestCase):
    def config(self):
        return SimpleNamespace(
            telegram_bot_token="123456:test-bot-token",
            telegram_chat_id="998877",
            dashboard_port=7871,
        )

    def release(self, version="v1.0.163", available=True):
        return {
            "available": available,
            "current_version": "v1.0.162",
            "latest_version": version,
            "improvements": [
                {"title": "Avisos en Telegram", "body": "", "impact": ""},
                {"title": "Actualización segura", "body": "", "impact": ""},
            ],
        }

    def test_sends_only_once_per_version_without_ai(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "update-state.json"
            calls = []

            def send(_config, method, payload, timeout=0):
                calls.append((method, payload, timeout))
                return {"message_id": 1}

            kwargs = {
                "request_release": lambda: self.release(),
                "bot_request": send,
                "state_file": state_file,
                "update_url": "https://buyer.example/?open_update=1",
                "language": "es",
                "now": "2026-07-16T10:00:00+00:00",
            }
            first = update_notifier.check_and_notify_update(self.config(), **kwargs)
            second = update_notifier.check_and_notify_update(self.config(), **kwargs)

            self.assertTrue(first["notified"])
            self.assertFalse(second["notified"])
            self.assertEqual(second["reason"], "already_notified")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], "sendMessage")
            self.assertIn("Actualización de Admira IA disponible", calls[0][1]["text"])
            keyboard = json.loads(calls[0][1]["reply_markup"])["inline_keyboard"]
            self.assertEqual(keyboard[0][0]["text"], "Instalar actualización")
            self.assertEqual(keyboard[0][0]["callback_data"], "au:v1.0.163")
            self.assertEqual(keyboard[1][0]["url"], "https://buyer.example/?open_update=1&update_version=v1.0.163")
            stored = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(stored["last_notified_version"], "v1.0.163")
            self.assertEqual(stored["last_notification_message_id"], "1")

    def test_retries_failed_delivery_and_skips_when_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "update-state.json"
            attempts = []

            def flaky(_config, _method, _payload, timeout=0):
                attempts.append(timeout)
                if len(attempts) == 1:
                    raise OSError("offline")
                return {"message_id": 2}

            common = {
                "request_release": lambda: self.release(),
                "bot_request": flaky,
                "state_file": state_file,
                "language": "es",
            }
            failed = update_notifier.check_and_notify_update(self.config(), **common)
            retried = update_notifier.check_and_notify_update(self.config(), **common)
            current = update_notifier.check_and_notify_update(
                self.config(),
                request_release=lambda: self.release(available=False),
                bot_request=flaky,
                state_file=state_file,
                language="es",
            )

            self.assertEqual(failed["reason"], "telegram_send_failed")
            self.assertTrue(retried["notified"])
            self.assertEqual(current["reason"], "up_to_date")
            self.assertEqual(len(attempts), 3)

    def test_marks_installed_notification_as_resolved_and_removes_buttons(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "update-state.json"
            calls = []

            def send(_config, method, payload, timeout=0):
                calls.append((method, payload, timeout))
                if method == "sendMessage":
                    return {"ok": True, "result": {"message_id": 41}}
                return {"ok": True, "result": True}

            first = update_notifier.check_and_notify_update(
                self.config(),
                request_release=lambda: self.release(),
                bot_request=send,
                state_file=state_file,
                update_url="https://buyer.example/?open_update=1",
                language="es",
            )
            current = update_notifier.check_and_notify_update(
                self.config(),
                request_release=lambda: self.release(available=False),
                bot_request=send,
                state_file=state_file,
                language="es",
            )

            self.assertTrue(first["notified"])
            self.assertEqual(current["reason"], "up_to_date")
            self.assertEqual([call[0] for call in calls], ["sendMessage", "editMessageText"])
            self.assertEqual(calls[1][1]["message_id"], "41")
            self.assertEqual(json.loads(calls[1][1]["reply_markup"]), {"inline_keyboard": []})
            stored = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(stored["last_notification_resolved_version"], "v1.0.163")

    def test_update_link_opens_update_review_not_model_reconnect(self):
        with patch.dict(os.environ, {"ADMIRA_DASHBOARD_URL": "https://buyer.example/dashboard?keep=1"}, clear=False):
            link = hermes_gateway.dashboard_update_link(self.config())
        self.assertEqual(link["kind"], "dashboard")
        self.assertIn("open_update=1", link["url"])
        self.assertNotIn("reconnect_model", link["url"])

    def test_dashboard_keeps_manual_update_review_without_starting_notifications(self):
        dashboard_source = (ROOT / "dashboard" / "monitoring-dashboard.py").read_text(encoding="utf-8")
        dashboard_main = dashboard_source.split("def main():", 1)[1]
        dashboard_js = (ROOT / "public" / "dashboard" / "dashboard.js").read_text(encoding="utf-8")
        notifier_source = (ROOT / "src" / "update_notifier.py").read_text(encoding="utf-8")
        self.assertIn("ensure_telegram_update_notification_monitor()", dashboard_source)
        self.assertNotIn("ensure_telegram_update_notification_monitor()", dashboard_main)
        self.assertIn("openUpdateFromUrl()", dashboard_js)
        self.assertIn("showUpdateDetails()", dashboard_js)
        self.assertIn("update_version", dashboard_js)
        self.assertNotIn("agent_chat", notifier_source)
        self.assertNotIn("hermes", notifier_source.lower())

    def test_desktop_startup_recovers_a_missed_daily_update_window(self):
        dashboard = load_dashboard()
        afternoon = datetime(2026, 8, 22, 14, 30)
        quiet_window = datetime(2026, 8, 22, 4, 0)
        previous_day = {"attempted_on": "2026-08-21"}
        today = {"attempted_on": "2026-08-22"}

        self.assertTrue(dashboard.automatic_update_is_due(previous_day, afternoon, startup=True))
        self.assertFalse(dashboard.automatic_update_is_due(previous_day, afternoon, startup=False))
        self.assertTrue(dashboard.automatic_update_is_due(previous_day, quiet_window, startup=False))
        self.assertFalse(dashboard.automatic_update_is_due(today, afternoon, startup=True))

    def test_install_button_is_optional_when_version_is_not_known(self):
        keyboard = update_notifier.telegram_update_keyboard(
            "https://buyer.example/?open_update=1", "es", ""
        )
        self.assertEqual(keyboard, [[{"text": "Ver detalles", "url": "https://buyer.example/?open_update=1"}]])

    def test_stale_valid_button_resolves_to_current_stable_release(self):
        release = self.release(version="v1.0.183", available=True)
        self.assertEqual(
            update_notifier.install_version_for_request("v1.0.182", release),
            "v1.0.183",
        )
        with self.assertRaises(ValueError):
            update_notifier.install_version_for_request("v1.0.184", release)

    def test_native_gateway_callback_records_authorized_install_request(self):
        class FakeAdapter:
            async def _handle_callback_query(self, _update, _context):
                raise AssertionError("Admira callback was not intercepted")

        adapter_module = types.ModuleType("plugins.platforms.telegram.adapter")
        adapter_module.TelegramAdapter = FakeAdapter
        plugin_modules = {
            "plugins": types.ModuleType("plugins"),
            "plugins.platforms": types.ModuleType("plugins.platforms"),
            "plugins.platforms.telegram": types.ModuleType("plugins.platforms.telegram"),
            "plugins.platforms.telegram.adapter": adapter_module,
        }

        class Query:
            def __init__(self):
                self.data = "au:v1.0.177"
                self.from_user = SimpleNamespace(id=123, first_name="Dorian")
                self.message = SimpleNamespace(
                    chat_id=456,
                    chat=SimpleNamespace(type="private"),
                    message_thread_id=None,
                )
                self.answers = []
                self.edited = False

            async def answer(self, text):
                self.answers.append(text)

            async def edit_message_text(self, **_kwargs):
                self.edited = True

        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, plugin_modules):
            path = Path(tmp) / "telegram-update.json"
            with patch.dict(os.environ, {"ADMIRA_TELEGRAM_UPDATE_INSTALL_REQUEST_FILE": str(path)}, clear=False):
                self.assertTrue(admira_hermes_runtime_patch._patch_telegram_update_install_callback())
                adapter = FakeAdapter()
                adapter._is_callback_user_authorized = lambda *_args, **_kwargs: True
                adapter.format_message = lambda text: text
                query = Query()
                asyncio.run(adapter._handle_callback_query(SimpleNamespace(callback_query=query), None))
            request = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(request["status"], "pending")
            self.assertEqual(request["version"], "v1.0.177")
            self.assertEqual(request["chat_id"], "456")
            self.assertTrue(query.answers)
            self.assertTrue(query.edited)

    def test_current_hermes_adapter_path_records_authorized_install_request(self):
        class FakeAdapter:
            async def _handle_callback_query(self, _update, _context):
                raise AssertionError("Admira callback was not intercepted")

        adapter_module = types.ModuleType("hermes_plugins.telegram_platform.adapter")
        adapter_module.TelegramAdapter = FakeAdapter
        plugin_modules = {
            "hermes_plugins": types.ModuleType("hermes_plugins"),
            "hermes_plugins.telegram_platform": types.ModuleType("hermes_plugins.telegram_platform"),
            "hermes_plugins.telegram_platform.adapter": adapter_module,
        }

        class Query:
            def __init__(self):
                self.data = "au:v1.0.182"
                self.from_user = SimpleNamespace(id=123, first_name="Dorian")
                self.message = SimpleNamespace(
                    chat_id=456,
                    chat=SimpleNamespace(type="private"),
                    message_thread_id=None,
                )
                self.answers = []
                self.edited = False

            async def answer(self, text):
                self.answers.append(text)

            async def edit_message_text(self, **_kwargs):
                self.edited = True

        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, plugin_modules):
            path = Path(tmp) / "telegram-update-current.json"
            with patch.dict(os.environ, {"ADMIRA_TELEGRAM_UPDATE_INSTALL_REQUEST_FILE": str(path)}, clear=False):
                self.assertTrue(admira_hermes_runtime_patch._patch_telegram_update_install_callback())
                adapter = FakeAdapter()
                adapter._is_callback_user_authorized = lambda *_args, **_kwargs: True
                adapter.format_message = lambda text: text
                query = Query()
                asyncio.run(adapter._handle_callback_query(SimpleNamespace(callback_query=query), None))
            request = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(request["status"], "pending")
            self.assertEqual(request["version"], "v1.0.182")
            self.assertTrue(query.answers)
            self.assertTrue(query.edited)


if __name__ == "__main__":
    unittest.main()
