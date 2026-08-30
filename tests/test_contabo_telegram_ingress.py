from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("telegram_ingress", ROOT / "deploy" / "contabo" / "telegram_ingress.py")
ingress_module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules["telegram_ingress"] = ingress_module
SPEC.loader.exec_module(ingress_module)


def update(text="hola", update_id=7):
    return {
        "update_id": update_id,
        "message": {"chat": {"id": 123, "type": "private"}, "from": {"id": 456}, "text": text},
    }


class Resolver:
    def resolve(self, *, bot_id, chat_id, user_id):
        return "tenant-a" if (bot_id, chat_id, user_id) == ("bot-1", "123", "456") else None

    def claim(self, *, bot_id, chat_id, user_id, token):
        if (bot_id, chat_id, user_id, token) == ("bot-1", "123", "456", "a" * 32):
            return "tenant-a"
        return None


class Inbox:
    def __init__(self):
        self.keys, self.items = set(), []

    def ingest(self, *, message, tenant_id, payload):
        key = (message.bot_id, message.update_id)
        if key in self.keys:
            return False
        self.keys.add(key)
        self.items.append((tenant_id, payload))
        return True


class Stager:
    def __init__(self):
        self.calls = []

    def stage(self, media):
        self.calls.append(media)
        return ingress_module.StagedMedia(media.kind, "a" * 32 + ".jpg", media.file_name, media.mime_type, 10, "b" * 64)


class Recovery:
    def __init__(self, result=None, error=None):
        self.calls, self.result, self.error = [], result, error

    def handle_unbound(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


class TelegramIngressTests(unittest.TestCase):
    def test_parses_private_command_and_largest_photo(self):
        raw = update("/restart@my_bot now")
        raw["message"]["photo"] = [
            {"file_id": "small_file_1", "file_size": 5},
            {"file_id": "large_file_2", "file_size": 10},
        ]
        message = ingress_module.parse_update(raw, bot_id="bot-1")
        self.assertEqual(message.command, "restart")
        self.assertEqual(message.command_args, "now")
        self.assertEqual(message.media[0].file_id, "large_file_2")

    def test_group_and_non_message_updates_are_ignored(self):
        raw = update()
        raw["message"]["chat"]["type"] = "group"
        self.assertIsNone(ingress_module.parse_update(raw, bot_id="bot-1"))
        self.assertIsNone(ingress_module.parse_update({"update_id": 1, "callback_query": {}}, bot_id="bot-1"))

    def test_rejects_invalid_ids_and_oversized_media(self):
        raw = update()
        raw["message"]["chat"]["id"] = "not-an-id"
        with self.assertRaises(ValueError):
            ingress_module.parse_update(raw, bot_id="bot-1")
        raw = update()
        raw["message"]["document"] = {"file_id": "valid_file_123", "file_size": ingress_module.MAX_MEDIA_BYTES + 1}
        with self.assertRaises(ValueError):
            ingress_module.parse_update(raw, bot_id="bot-1")

    def test_routes_stages_and_durably_enqueues_without_runtime(self):
        inbox, stager = Inbox(), Stager()
        raw = update()
        raw["message"]["photo"] = [{"file_id": "photo_file_123", "file_size": 10}]
        ingress = ingress_module.TelegramIngress(Resolver(), inbox, stager)
        first = ingress.handle_update(raw, bot_id="bot-1")
        second = ingress.handle_update(raw, bot_id="bot-1")
        self.assertEqual(first["status"], "queued")
        self.assertEqual(second["status"], "duplicate")
        self.assertEqual(inbox.items[0][0], "tenant-a")
        self.assertEqual(inbox.items[0][1]["media"][0]["ref"], "a" * 32 + ".jpg")
        self.assertFalse(hasattr(ingress, "runtime"))

    def test_unbound_chat_never_downloads_media(self):
        inbox, stager = Inbox(), Stager()
        raw = update()
        raw["message"]["photo"] = [{"file_id": "photo_file_123", "file_size": 10}]
        result = ingress_module.TelegramIngress(Resolver(), inbox, stager).handle_update(raw, bot_id="other")
        self.assertEqual(result["status"], "unbound")
        self.assertFalse(stager.calls)

    def test_recovery_handles_command_without_staging_or_tenant_inbox(self):
        inbox, stager = Inbox(), Stager()
        recovery = Recovery({
            "request_id": "4c6d1a2e-1111-4222-8333-123456789abc",
            "public_outcome": "recovery_pending",
            "email": "secret@example.test",
            "license_id": "LIC-SECRET",
            "otp": "123456",
        })
        raw = update("/recuperar secret@example.test LIC-SECRET")
        raw["message"]["photo"] = [{"file_id": "photo_file_123", "file_size": 10}]
        result = ingress_module.TelegramIngress(Resolver(), inbox, stager, recovery).handle_update(
            raw, bot_id="other"
        )
        self.assertEqual(result, {
            "status": "recovery", "update_id": 7,
            "public_outcome": "recovery_pending",
        })
        self.assertEqual(recovery.calls[0]["text"], "/recuperar secret@example.test LIC-SECRET")
        self.assertFalse(stager.calls)
        self.assertFalse(inbox.items)
        self.assertNotIn("secret@example.test", repr(result))
        self.assertNotIn("LIC-SECRET", repr(result))
        self.assertNotIn("123456", repr(result))

    def test_recovery_unknown_command_preserves_unbound(self):
        recovery = Recovery(None)
        result = ingress_module.TelegramIngress(Resolver(), Inbox(), Stager(), recovery).handle_update(
            update("/ayuda"), bot_id="other"
        )
        self.assertEqual(result, {"status": "unbound", "update_id": 7})
        self.assertEqual(recovery.calls[0]["text"], "/ayuda")

    def test_recovery_durable_failure_blocks_cursor_without_detail(self):
        recovery = Recovery(error=OSError("postgres password=raw-secret"))
        result = ingress_module.TelegramIngress(Resolver(), Inbox(), Stager(), recovery).handle_update(
            update("/recuperar a@b.test LIC-123"), bot_id="other"
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "OSError")
        self.assertNotIn("raw-secret", repr(result))

    def test_start_claim_has_precedence_over_recovery(self):
        class ClaimOnlyResolver:
            def resolve(self, **_kwargs):
                return None

            def claim(self, **kwargs):
                return "tenant-a" if kwargs["token"] == "a" * 32 else None

        recovery = Recovery(error=AssertionError("must not run"))
        result = ingress_module.TelegramIngress(ClaimOnlyResolver(), Inbox(), Stager(), recovery).handle_update(
            update("/start " + "a" * 32), bot_id="bot-1"
        )
        self.assertEqual(result["status"], "claimed")
        self.assertFalse(recovery.calls)

    def test_default_recovery_none_keeps_unbound_compatibility(self):
        result = ingress_module.TelegramIngress(Resolver(), Inbox(), Stager()).handle_update(
            update("/recuperar a@b.test LIC-123"), bot_id="other"
        )
        self.assertEqual(result, {"status": "unbound", "update_id": 7})

    def test_one_time_start_claim_is_not_sent_to_the_model(self):
        class ClaimResolver:
            def resolve(self, **_kwargs):
                return None

            def claim(self, **kwargs):
                return "tenant-a" if kwargs["token"] == "a" * 32 else None

        inbox, stager = Inbox(), Stager()
        result = ingress_module.TelegramIngress(ClaimResolver(), inbox, stager).handle_update(
            update("/start " + "a" * 32, update_id=9), bot_id="bot-1"
        )
        self.assertEqual(result["status"], "claimed")
        self.assertEqual(result["tenant_id"], "tenant-a")
        self.assertFalse(inbox.items)
        self.assertFalse(stager.calls)

    def test_media_stage_failure_is_distinct_from_inbox_failure(self):
        class FailingStager(Stager):
            def stage(self, media):
                raise OSError("temporary download detail")

        class FailingInbox(Inbox):
            def ingest(self, **_kwargs):
                raise OSError("database detail")

        raw = update()
        raw["message"]["photo"] = [{"file_id": "photo_file_123", "file_size": 10}]
        result = ingress_module.TelegramIngress(Resolver(), Inbox(), FailingStager()).handle_update(raw, bot_id="bot-1")
        self.assertEqual(result["status"], "media_failed")
        self.assertNotIn("detail", result)
        result = ingress_module.TelegramIngress(Resolver(), FailingInbox(), Stager()).handle_update(update(), bot_id="bot-1")
        self.assertEqual(result["status"], "failed")

    def test_media_fallback_is_text_only_and_idempotent_store_result(self):
        inbox, stager = Inbox(), Stager()
        raw = update("hazlo con esta imagen")
        raw["message"]["photo"] = [{"file_id": "photo_file_123", "file_size": 10}]
        ingress = ingress_module.TelegramIngress(Resolver(), inbox, stager)
        result = ingress.enqueue_media_fallback(raw, bot_id="bot-1", expected_tenant_id="tenant-a")
        self.assertTrue(result)
        payload = inbox.items[0][1]
        self.assertIn("No pude recuperar el archivo adjunto", payload["message"])
        self.assertEqual(payload["media"], [])
        self.assertNotIn("photo_file_123", repr(payload))
        self.assertIsNone(ingress.enqueue_media_fallback(raw, bot_id="other", expected_tenant_id="tenant-a"))


if __name__ == "__main__":
    unittest.main()
