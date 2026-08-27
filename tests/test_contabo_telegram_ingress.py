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


if __name__ == "__main__":
    unittest.main()
