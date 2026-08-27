from __future__ import annotations

import hashlib
import importlib.util
import inspect
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "deploy" / "contabo" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


worker_module = load("hosted_worker", "hosted_worker.py")
ingress_module = load("telegram_ingress", "telegram_ingress.py")
load("runtime_broker", "runtime_broker.py")
service = load("hosted_service", "hosted_service.py")


def update(update_id: int, text: str = "hola") -> dict[str, object]:
    return {
        "update_id": update_id,
        "message": {
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 456},
            "text": text,
        },
    }


class PollerAPI:
    def __init__(self, updates: list[dict[str, object]]) -> None:
        self.updates = updates
        self.calls: list[tuple[int, int]] = []

    def bot_id(self) -> str:
        return "bot-1"

    def get_updates(self, *, offset: int, timeout: int) -> list[dict[str, object]]:
        self.calls.append((offset, timeout))
        return self.updates


class CursorStore:
    def __init__(self) -> None:
        self.advanced: list[tuple[str, int]] = []

    def cursor(self, bot_id: str) -> int:
        return 10

    def advance(self, bot_id: str, next_update_id: int) -> int:
        self.advanced.append((bot_id, next_update_id))
        return next_update_id


class FakeIngress:
    def __init__(self, statuses: dict[int, str]) -> None:
        self.statuses = statuses

    def handle_update(self, raw: object, *, bot_id: str) -> dict[str, object]:
        return {"status": self.statuses[int(raw["update_id"])]}


class HostedServiceTests(unittest.TestCase):
    def test_poller_advances_cursor_for_queued_duplicate_unbound_and_invalid(self):
        api = PollerAPI([update(11), update(12), update(13), update(14)])
        store = CursorStore()
        ingress = FakeIngress({11: "queued", 12: "duplicate", 13: "unbound", 14: "invalid"})
        with patch.object(service, "TelegramAPI", return_value=api), \
             patch.object(service, "Pg", return_value=object()), \
             patch.object(service, "IngressStore", return_value=store), \
             patch.object(service, "TelegramIngress", return_value=ingress), \
             patch.object(service, "TelegramMediaStager"), \
             patch.dict(service.os.environ, {"TELEGRAM_BOT_TOKEN_FILE": "/not-read"}), \
             patch.object(service, "_stop_event", return_value=__import__("threading").Event()):
            service.run_poller(once=True)
        self.assertEqual(store.advanced, [("bot-1", 12), ("bot-1", 13), ("bot-1", 14), ("bot-1", 15)])
        self.assertEqual(api.calls, [(10, 1)])

    def test_poller_does_not_advance_after_media_stage_failure(self):
        api = PollerAPI([update(11), update(12), update(13)])
        store = CursorStore()
        ingress = FakeIngress({11: "queued", 12: "failed", 13: "queued"})
        with patch.object(service, "TelegramAPI", return_value=api), \
             patch.object(service, "Pg", return_value=object()), \
             patch.object(service, "IngressStore", return_value=store), \
             patch.object(service, "TelegramIngress", return_value=ingress), \
             patch.object(service, "TelegramMediaStager"), \
             patch.dict(service.os.environ, {"TELEGRAM_BOT_TOKEN_FILE": "/not-read"}), \
             patch.object(service, "_stop_event", return_value=__import__("threading").Event()):
            service.run_poller(once=True)
        self.assertEqual(store.advanced, [("bot-1", 12)])

    def test_resolution_and_ingest_receive_bot_chat_and_user_identity(self):
        calls: dict[str, object] = {}

        class Resolver:
            def resolve(self, *, bot_id, chat_id, user_id):
                calls["resolve"] = (bot_id, chat_id, user_id)
                return "tenant-a"

            def claim(self, **_kwargs):
                raise AssertionError("already bound")

        class Inbox:
            def ingest(self, *, message, tenant_id, payload):
                calls["ingest"] = (message.bot_id, message.chat_id, message.user_id, tenant_id, payload)
                return True

        class Stager:
            def stage(self, media):
                raise AssertionError("no media expected")

        result = ingress_module.TelegramIngress(Resolver(), Inbox(), Stager()).handle_update(
            update(8, "mensaje"), bot_id="bot-9"
        )
        self.assertEqual(result["status"], "queued")
        self.assertEqual(calls["resolve"], ("bot-9", "123", "456"))
        self.assertEqual(calls["ingest"][:4], ("bot-9", "123", "456", "tenant-a"))
        self.assertEqual(calls["ingest"][4]["message"], "mensaje")

    def test_runtime_process_forwards_no_telegram_token(self):
        class Store:
            def claim_updates(self, **kwargs):
                return []

        class Broker:
            def request(self, body):
                raise AssertionError("broker must not be called without updates")

        # The runtime service only constructs Pg/Broker/RuntimeWorker; the bot
        # token is intentionally absent from its process and request boundary.
        self.assertNotIn("TELEGRAM_BOT_TOKEN_FILE", inspect.getsource(service.run_runtime))
        self.assertNotIn("TelegramAPI", inspect.getsource(service.run_runtime))
        self.assertNotIn("TELEGRAM_BOT_TOKEN_FILE", inspect.getsource(worker_module.RuntimeWorker))
        worker = worker_module.RuntimeWorker(Store(), Broker())
        self.assertEqual(worker.process_once(), {"completed": 0, "retried": 0, "busy": 0})

    def test_delivery_accepts_only_opaque_reference_and_verifies_hash(self):
        class API:
            def __init__(self):
                self.checked: list[tuple[str, str, Path]] = []

            def bot_id(self):
                return "bot-1"

            def send_file(self, chat_id, kind, path, caption):
                self.checked.append((chat_id, kind, path))
                return 99

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "outbound"
            root.mkdir()
            data = b"approved-media"
            digest = hashlib.sha256(data).hexdigest()
            ref = "a" * 48 + ".png"
            (root / ref).write_bytes(data)
            api = API()
            transport = service.TelegramTransport.__new__(service.TelegramTransport)
            transport.api, transport.root = api, root
            self.assertEqual(transport.send_media("bot-1", "123", "photo", ref, sha256=digest), 99)
            self.assertEqual(api.checked[0][2], (root / ref).resolve())
            with self.assertRaises(service.TelegramError):
                transport.send_media("bot-1", "123", "photo", "../secret.png")
            with self.assertRaises((service.TelegramError, FileNotFoundError)):
                transport.send_media("bot-1", "123", "photo", "b" * 48 + ".png", sha256="0" * 64)
            outside = Path(directory) / "outside.png"
            outside.write_bytes(data)
            (root / ("c" * 48 + ".png")).symlink_to(outside)
            with self.assertRaises(service.TelegramError):
                transport.send_media("bot-1", "123", "photo", "c" * 48 + ".png", sha256=digest)

    def test_text_delivery_still_checks_bot_identity(self):
        class API:
            def bot_id(self):
                return "other-bot"

            def send_message(self, chat_id, text):
                return 1

        transport = service.TelegramTransport.__new__(service.TelegramTransport)
        transport.api = API()
        with tempfile.TemporaryDirectory() as directory:
            transport.root = Path(directory)
            with self.assertRaises(service.TelegramError):
                transport.send_text("bot-1", "123", "hola")

    def test_spool_janitor_only_removes_stale_opaque_regular_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stale = root / ("a" * 48 + ".png")
            recent = root / ("b" * 48 + ".png")
            unrelated = root / "keep-me.txt"
            stale.write_bytes(b"old")
            recent.write_bytes(b"new")
            unrelated.write_bytes(b"unrelated")
            now = time.time()
            stale.touch()
            __import__("os").utime(stale, (now - 10_000, now - 10_000))
            removed = service.clean_spool(root, retention_seconds=3600, now=now)
            self.assertEqual(removed, 1)
            self.assertFalse(stale.exists())
            self.assertTrue(recent.exists())
            self.assertTrue(unrelated.exists())


if __name__ == "__main__":
    unittest.main()
