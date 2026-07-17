#!/usr/bin/env python3
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import hermes_gateway
import update_notifier


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
            self.assertEqual(keyboard[0][0]["url"], "https://buyer.example/?open_update=1")
            stored = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(stored["last_notified_version"], "v1.0.163")

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
            self.assertEqual(len(attempts), 2)

    def test_update_link_opens_update_review_not_model_reconnect(self):
        with patch.dict(os.environ, {"ADMIRA_DASHBOARD_URL": "https://buyer.example/dashboard?keep=1"}, clear=False):
            link = hermes_gateway.dashboard_update_link(self.config())
        self.assertEqual(link["kind"], "dashboard")
        self.assertIn("open_update=1", link["url"])
        self.assertNotIn("reconnect_model", link["url"])

    def test_dashboard_starts_monitor_and_deep_link_opens_review(self):
        dashboard_source = (ROOT / "dashboard" / "monitoring-dashboard.py").read_text(encoding="utf-8")
        dashboard_js = (ROOT / "public" / "dashboard" / "dashboard.js").read_text(encoding="utf-8")
        notifier_source = (ROOT / "src" / "update_notifier.py").read_text(encoding="utf-8")
        self.assertIn("ensure_telegram_update_notification_monitor()", dashboard_source)
        self.assertIn("openUpdateFromUrl()", dashboard_js)
        self.assertIn("showUpdateDetails()", dashboard_js)
        self.assertNotIn("agent_chat", notifier_source)
        self.assertNotIn("hermes", notifier_source.lower())


if __name__ == "__main__":
    unittest.main()
