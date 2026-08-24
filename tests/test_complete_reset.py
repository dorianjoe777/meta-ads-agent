#!/usr/bin/env python3
import asyncio
import json
import os
import stat
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import admira_hermes_runtime_patch
from complete_reset import (
    COMPLETE_RESET_ENV_GUARD_FILENAME,
    COMPLETE_RESET_CONFIRMATION_PHRASE,
    begin_reset_confirmation,
    consume_reset_confirmation,
    reset_workspace,
)


class CompleteResetTest(unittest.TestCase):
    def test_exact_confirmation_is_private_short_lived_and_owner_bound(self):
        now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            confirmation = Path(tmp) / "confirmation.json"
            request = Path(tmp) / "request.json"
            started = begin_reset_confirmation(confirmation, request, "456", "123", now=now)
            self.assertTrue(started["ok"])
            self.assertEqual(stat.S_IMODE(confirmation.stat().st_mode), 0o600)

            other_user = consume_reset_confirmation(
                confirmation, request, COMPLETE_RESET_CONFIRMATION_PHRASE, "456", "999", now=now
            )
            self.assertFalse(other_user["matched"])
            self.assertTrue(confirmation.exists())

            confirmed = consume_reset_confirmation(
                confirmation, request, COMPLETE_RESET_CONFIRMATION_PHRASE, "456", "123", now=now
            )
            self.assertEqual(confirmed["status"], "confirmed")
            self.assertFalse(confirmation.exists())
            stored = json.loads(request.read_text(encoding="utf-8"))
            self.assertEqual(stored["status"], "pending")
            self.assertEqual(stored["target"], "latest_stable")
            self.assertEqual(stored["preserve"], ["license", "telegram", "primary_model", "image2_chatgpt"])
            self.assertEqual(stat.S_IMODE(request.stat().st_mode), 0o600)

    def test_any_non_exact_reply_cancels_without_creating_request(self):
        now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            confirmation = Path(tmp) / "confirmation.json"
            request = Path(tmp) / "request.json"
            begin_reset_confirmation(confirmation, request, "456", "123", now=now)
            cancelled = consume_reset_confirmation(
                confirmation, request, "Sí quiero resetear completamente", "456", "123", now=now
            )
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertFalse(confirmation.exists())
            self.assertFalse(request.exists())

    def test_expired_confirmation_never_resets(self):
        now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            confirmation = Path(tmp) / "confirmation.json"
            request = Path(tmp) / "request.json"
            begin_reset_confirmation(confirmation, request, "456", "123", now=now)
            expired = consume_reset_confirmation(
                confirmation,
                request,
                COMPLETE_RESET_CONFIRMATION_PHRASE,
                "456",
                "123",
                now=now + timedelta(minutes=11),
            )
            self.assertEqual(expired["status"], "expired")
            self.assertFalse(request.exists())

    def test_workspace_reset_preserves_connections_and_removes_buyer_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime"
            data = root / "data"
            output = root / "output"
            logs = root / "logs"
            brand = root / "brand"
            seed = root / "seed"
            for path in (runtime, data, output, logs, brand, seed):
                path.mkdir(parents=True)
            env = runtime / ".env"
            env.write_text(
                "LICENSE_KEY=MAO-KEEP\n"
                "TELEGRAM_BOT_TOKEN=123:keep\n"
                "TELEGRAM_CHAT_ID=456\n"
                "AGENT_BRAIN_PROVIDER=gemini\n"
                "AGENT_CHAT_MODEL=gemini-3.5-flash-lite\n"
                "GEMINI_API_KEY=keep-gemini\n"
                "META_ACCESS_TOKEN=delete-meta\n"
                "META_AD_ACCOUNT_ID=act_delete\n"
                "DASHBOARD_PASSWORD=delete-password\n",
                encoding="utf-8",
            )
            example = root / "ad-config.example.json"
            example.write_text(json.dumps({
                "account": {"id": "example", "name": "Example"},
                "brand": {"name": "Example", "offer": "Example", "voice": "x", "visual_style": "x", "avoid": ["x"]},
                "creative": {"destination": {"page_id": "1", "instagram_actor_id": "2", "default_adset_id": "3", "url": "https://example.com"}},
            }), encoding="utf-8")
            (runtime / "ad-config.json").write_text("{}", encoding="utf-8")
            (runtime / "hermes").mkdir()
            (runtime / "hermes" / "auth.json").write_text("auth", encoding="utf-8")
            (runtime / "hermes" / "sessions").mkdir()
            (runtime / "hermes" / "sessions" / "old.json").write_text("old", encoding="utf-8")
            (runtime / "codex").mkdir()
            (runtime / "codex" / "auth.json").write_text("auth", encoding="utf-8")
            (data / "hermes-home").mkdir()
            (data / "hermes-home" / "auth.lock").write_text("", encoding="utf-8")
            (data / "hermes-image-home").mkdir()
            (data / "hermes-image-home" / "auth.json").write_text("image-auth", encoding="utf-8")
            (data / "hermes-image-home" / "state.db").write_text("old-state", encoding="utf-8")
            (data / "license_unlock.json").write_text("{}", encoding="utf-8")
            (data / "update-snapshots").mkdir()
            (data / "update-snapshots" / "keep-mounted-volume.json").write_text("{}", encoding="utf-8")
            (data / "business_profile.json").write_text("{}", encoding="utf-8")
            (data / "meta_oauth_connection.json").write_text("{}", encoding="utf-8")
            (data / "telegram_complete_reset_result.json").write_text("{}", encoding="utf-8")
            (output / "old-creative.png").write_bytes(b"old")
            (logs / "old.log").write_text("old", encoding="utf-8")
            (brand / "old-business.md").write_text("old", encoding="utf-8")
            (seed / "general_branding.example.md").write_text("seed", encoding="utf-8")

            reset_workspace(
                runtime_dir=runtime,
                data_dir=data,
                output_dir=output,
                logs_dir=logs,
                brand_guides_dir=brand,
                brand_seed_dir=seed,
                ad_config_example=example,
                env_paths=[env],
                clear_env_keys={"META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID", "DASHBOARD_PASSWORD"},
                forced_env_values={"LIVE_ACTIONS_ENABLED": "false"},
                preserve_data_names=("telegram_complete_reset_result.json",),
            )

            env_text = env.read_text(encoding="utf-8")
            self.assertIn("LICENSE_KEY=MAO-KEEP", env_text)
            self.assertIn("AGENT_BRAIN_PROVIDER=gemini", env_text)
            self.assertIn("AGENT_CHAT_MODEL=gemini-3.5-flash-lite", env_text)
            self.assertIn("TELEGRAM_CHAT_ID=456", env_text)
            self.assertIn("META_ACCESS_TOKEN=\n", env_text)
            self.assertIn("META_AD_ACCOUNT_ID=\n", env_text)
            self.assertTrue((runtime / "hermes" / "auth.json").exists())
            self.assertFalse((runtime / "hermes" / "sessions").exists())
            self.assertTrue((runtime / "codex" / "auth.json").exists())
            self.assertTrue((data / "hermes-image-home" / "auth.json").exists())
            self.assertFalse((data / "hermes-image-home" / "state.db").exists())
            self.assertTrue((data / "license_unlock.json").exists())
            self.assertTrue((data / "update-snapshots" / "keep-mounted-volume.json").exists())
            self.assertTrue((data / "telegram_complete_reset_result.json").exists())
            self.assertFalse((data / "business_profile.json").exists())
            self.assertFalse((data / "meta_oauth_connection.json").exists())
            guard_path = data / COMPLETE_RESET_ENV_GUARD_FILENAME
            self.assertTrue(guard_path.exists())
            self.assertEqual(guard_path.stat().st_mode & 0o777, 0o600)
            guard = json.loads(guard_path.read_text(encoding="utf-8"))
            self.assertIn("META_ACCESS_TOKEN", guard["clear_env_keys"])
            self.assertNotIn("GEMINI_API_KEY", guard["clear_env_keys"])
            self.assertEqual(list(output.iterdir()), [])
            self.assertEqual(list(logs.iterdir()), [])
            self.assertFalse((brand / "old-business.md").exists())
            self.assertTrue((brand / "general_branding.example.md").exists())
            config = json.loads((runtime / "ad-config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["account"]["id"], "")
            self.assertEqual(config["brand"]["name"], "")

    def test_telegram_command_and_confirmation_bypass_the_model(self):
        class FakeAdapter:
            def __init__(self):
                self.original_commands = 0
                self.original_texts = 0

            async def _handle_command(self, _update, _context):
                self.original_commands += 1

            async def _handle_text_message(self, _update, _context):
                self.original_texts += 1

        adapter_module = types.ModuleType("plugins.platforms.telegram.adapter")
        adapter_module.TelegramAdapter = FakeAdapter
        modules = {
            "plugins": types.ModuleType("plugins"),
            "plugins.platforms": types.ModuleType("plugins.platforms"),
            "plugins.platforms.telegram": types.ModuleType("plugins.platforms.telegram"),
            "plugins.platforms.telegram.adapter": adapter_module,
        }

        class Message:
            def __init__(self, text):
                self.text = text
                self.chat_id = 456
                self.chat = SimpleNamespace(id=456, type="private")
                self.from_user = SimpleNamespace(id=123)
                self.replies = []

            async def reply_text(self, text):
                self.replies.append(text)

        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, modules):
            product_root = Path(tmp)
            (product_root / "dashboard" / "data").mkdir(parents=True, exist_ok=True)
            confirmation = Path(tmp) / "confirmation.json"
            request = Path(tmp) / "request.json"
            result = Path(tmp) / "result.json"
            environment = {
                "ADMIRA_PRODUCT_ROOT": str(product_root),
                "ADMIRA_TELEGRAM_COMPLETE_RESET_CONFIRMATION_FILE": str(confirmation),
                "ADMIRA_TELEGRAM_COMPLETE_RESET_REQUEST_FILE": str(request),
                "ADMIRA_TELEGRAM_COMPLETE_RESET_RESULT_FILE": str(result),
            }
            with patch.dict(os.environ, environment, clear=False):
                self.assertTrue(admira_hermes_runtime_patch._patch_telegram_complete_reset_command())
                adapter = FakeAdapter()
                adapter._effective_update_message = lambda update: update.effective_message
                adapter._is_user_authorized_from_message = lambda _message: True
                command = Message("/resetear_completamente")
                asyncio.run(adapter._handle_command(SimpleNamespace(effective_message=command), None))
                self.assertTrue(confirmation.exists())
                self.assertIn(COMPLETE_RESET_CONFIRMATION_PHRASE, command.replies[0])
                cancelled_command = Message("/restart")
                asyncio.run(adapter._handle_command(SimpleNamespace(effective_message=cancelled_command), None))
                self.assertFalse(confirmation.exists())
                self.assertFalse(request.exists())
                self.assertIn("cancelada", cancelled_command.replies[0])
                asyncio.run(adapter._handle_command(SimpleNamespace(effective_message=command), None))
                confirmation_message = Message(COMPLETE_RESET_CONFIRMATION_PHRASE)
                asyncio.run(adapter._handle_text_message(SimpleNamespace(effective_message=confirmation_message), None))
                self.assertTrue(request.exists())
                self.assertEqual(adapter.original_commands, 0)
                self.assertEqual(adapter.original_texts, 0)

    def test_dashboard_wires_verified_reinstall_and_reset_monitor(self):
        source = (ROOT / "dashboard" / "monitoring-dashboard.py").read_text(encoding="utf-8")
        self.assertIn("request_update_release()", source)
        self.assertIn("validate_update_archive_sha256", source)
        self.assertIn("if not integrity.get(\"verified\")", source)
        self.assertIn("reset_complete_workspace(", source)
        self.assertIn("ensure_telegram_complete_reset_monitor()", source)
        self.assertIn("version_parts(latest_version) < version_parts(current_version)", source)
        entrypoint = (ROOT / "scripts" / "docker-entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn("complete_reset_environment_guard.json", entrypoint)
        self.assertIn('unset "$reset_key"', entrypoint)


if __name__ == "__main__":
    unittest.main()
