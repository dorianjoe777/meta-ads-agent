from __future__ import annotations

import importlib.util
import sys
import tempfile
import threading
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


load("hosted_worker", "hosted_worker.py")
load("runtime_broker", "runtime_broker.py")
service = load("hosted_service", "hosted_service.py")


class TelegramTypingTests(unittest.TestCase):
    def test_telegram_api_sends_typing_action(self):
        api = object.__new__(service.TelegramAPI)
        api._bot_id = "bot-1"
        calls = []

        def request(method, payload, *, timeout):
            calls.append((method, payload, timeout))
            return True

        api._request = request
        service.TelegramTypingTransport(api).send_chat_action("bot-1", "123")
        self.assertEqual(calls, [(
            "sendChatAction", {"chat_id": "123", "action": "typing"}, 8,
        )])

    def test_poller_starts_typing_for_newly_queued_update(self):
        class API:
            def bot_id(self):
                return "bot-1"

            def get_updates(self, *, offset, timeout):
                return [{
                    "update_id": 42,
                    "message": {"chat": {"id": 123}, "from": {"id": 456}, "text": "hola"},
                }]

        class Store:
            def __init__(self):
                self.advanced = []
                self.pending_calls = []

            def cursor(self, bot_id):
                return 42

            def advance(self, bot_id, next_update_id):
                self.advanced.append((bot_id, next_update_id))
                return next_update_id

            def telegram_update_pending(self, *, bot_id, update_id):
                self.pending_calls.append((bot_id, update_id))
                return False

        class Ingress:
            def handle_update(self, raw, *, bot_id):
                return {"status": "queued", "update_id": 42, "chat_id": "123"}

        class Heartbeat:
            instances = []

            def __init__(self, transport, bot_id, chat_id):
                self.args = (transport, bot_id, chat_id)
                self.started = threading.Event()
                self.stopped = threading.Event()
                self.instances.append(self)

            def start(self):
                self.started.set()

            def stop(self):
                self.stopped.set()

        class Database:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        api, ingress_store, typing_store = API(), Store(), Store()
        ingress_db, typing_db = Database(), Database()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(service, "TelegramAPI", return_value=api), \
             patch.object(service, "Pg", side_effect=(ingress_db, typing_db)) as pg, \
             patch.object(service, "IngressStore", side_effect=(ingress_store, typing_store)), \
             patch.object(service, "TelegramIngress", return_value=Ingress()), \
             patch.object(service, "TelegramMediaStager"), \
             patch.object(service, "TelegramTypingHeartbeat", Heartbeat), \
             patch.dict(service.os.environ, {
                 "TELEGRAM_BOT_TOKEN_FILE": "/not-read",
                 "ADMIRA_SPOOL_ROOT": directory,
             }), \
             patch.object(service, "_stop_event", return_value=threading.Event()):
            service.run_poller(once=True)

        deadline = time.monotonic() + 1
        while not Heartbeat.instances and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertEqual(len(Heartbeat.instances), 1)
        heartbeat = Heartbeat.instances[0]
        self.assertEqual(heartbeat.args[1:], ("bot-1", "123"))
        self.assertTrue(heartbeat.started.wait(1))
        self.assertTrue(heartbeat.stopped.wait(1))
        self.assertEqual(pg.call_count, 2)
        self.assertEqual(ingress_store.advanced, [("bot-1", 43)])
        self.assertEqual(ingress_store.pending_calls, [])
        self.assertEqual(typing_store.pending_calls, [("bot-1", 42)])
        self.assertTrue(typing_db.closed)

    def test_ingress_store_uses_narrow_pending_function(self):
        class DB:
            def __init__(self):
                self.calls = []

            def query(self, sql, params):
                self.calls.append((sql, params))
                return [{"pending": True}]

        db = DB()
        self.assertTrue(service.IngressStore(db).telegram_update_pending(
            bot_id="123", update_id=456,
        ))
        self.assertEqual(db.calls, [(
            "SELECT admira.telegram_update_pending(%s,%s) AS pending",
            ("123", 456),
        )])

    def test_migration_is_least_privilege_and_tracks_active_lease(self):
        sql = (ROOT / "deploy/contabo/db/migrations/014_telegram_typing_indicator.sql").read_text()
        self.assertIn("u.status = 'received'", sql)
        self.assertIn("u.status = 'processing'", sql)
        self.assertIn("u.leased_until > now()", sql)
        self.assertIn("REVOKE ALL ON FUNCTION admira.telegram_update_pending(text, bigint) FROM PUBLIC", sql)
        self.assertIn("GRANT EXECUTE ON FUNCTION admira.telegram_update_pending(text, bigint) TO admira_ingress", sql)
        self.assertNotIn("GRANT SELECT", sql)

    def test_typing_watcher_stops_when_update_is_no_longer_pending(self):
        events = []

        class Heartbeat:
            def start(self): events.append("start")
            def stop(self): events.append("stop")

        pending_values = iter((True, False))
        service._watch_telegram_typing(
            Heartbeat(), lambda: next(pending_values), poll_interval=0.1,
        )
        self.assertEqual(events, ["start", "stop"])


if __name__ == "__main__":
    unittest.main()
