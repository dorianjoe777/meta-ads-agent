from __future__ import annotations

import hashlib
import importlib.util
import inspect
import sys
import tempfile
import time
import unittest
import urllib.error
from datetime import datetime, timezone
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


class MediaRetryIngress:
    def __init__(self, handle_statuses: list[str], fallback_result: object = True,
                 fallback_error: Exception | None = None) -> None:
        self.handle_statuses = iter(handle_statuses)
        self.fallback_result = fallback_result
        self.fallback_error = fallback_error
        self.handle_calls = 0
        self.fallback_calls = 0

    def handle_update(self, raw: object, *, bot_id: str) -> dict[str, object]:
        self.handle_calls += 1
        return {"status": next(self.handle_statuses), "tenant_id": "tenant-a"}

    def enqueue_media_fallback(self, raw: object, *, bot_id: str, expected_tenant_id: str):
        self.fallback_calls += 1
        if self.fallback_error:
            raise self.fallback_error
        return self.fallback_result


class SequencePollerAPI(PollerAPI):
    def __init__(self, update_batches: list[list[dict[str, object]]]) -> None:
        super().__init__([])
        self.update_batches = iter(update_batches)

    def get_updates(self, *, offset: int, timeout: int) -> list[dict[str, object]]:
        self.calls.append((offset, timeout))
        return next(self.update_batches)


class StopAfterPolls:
    def __init__(self, api: SequencePollerAPI, polls: int) -> None:
        self.api, self.polls = api, polls

    def is_set(self) -> bool:
        return len(self.api.calls) >= self.polls


class HostedServiceTests(unittest.TestCase):
    def test_recovery_store_calls_only_security_definer_functions(self):
        class DB:
            def __init__(self): self.calls = []
            def query(self, sql, params):
                self.calls.append((sql, params))
                if "confirm_telegram_recovery" in sql:
                    return [{"completed": True, "public_outcome": "recovery_completed"}]
                return [{"public_outcome": "recovery_pending"}]

        db = DB()
        store = service.RecoveryStore(db)
        request_id = __import__("uuid").uuid4()
        pending = store.begin_telegram_recovery(
            request_id, "123", "456", "456", "a" * 64, "b" * 64,
            "c" * 64, b"encrypted", "v1",
        )
        completed = store.confirm_telegram_recovery(
            request_id, "123", "456", "456", "c" * 64,
        )
        store.enqueue_public_reply(
            request_id, "123", "456", "456", "recovery_instructions",
        )
        self.assertEqual(pending["public_outcome"], "recovery_pending")
        self.assertTrue(completed["completed"])
        self.assertEqual([call[0].split("admira.", 1)[1].split("(", 1)[0] for call in db.calls], [
            "begin_telegram_recovery", "confirm_telegram_recovery",
            "enqueue_telegram_recovery_public_reply",
        ])
        self.assertNotIn("encrypted", repr(pending) + repr(completed))

    def test_recovery_email_store_maps_ciphertext_and_fenced_ack(self):
        class DB:
            def __init__(self): self.calls = []
            def query(self, sql, params):
                self.calls.append((sql, params))
                if "claim_recovery_email_outbox" in sql:
                    return [{
                        "outbox_id": "outbox", "challenge_id": "challenge",
                        "request_id": "123e4567-e89b-12d3-a456-426614174000",
                        "delivery_ref": "sealed-envelope://v1",
                        "template_code": "telegram_recovery_otp",
                        "encrypted_payload": memoryview(b"ciphertext"),
                        "delivery_key_version": "v1", "attempt_count": 2,
                        "lease_token": "lease",
                    }]
                return [{"acknowledged": True}]

        db = DB()
        store = service.RecoveryEmailStore(db)
        item = store.claim_recovery_email_outbox(worker_id="email-1", limit=1)[0]
        self.assertEqual(item.request_id, "123e4567-e89b-12d3-a456-426614174000")
        self.assertEqual(item.ciphertext, b"ciphertext")
        self.assertTrue(store.ack_recovery_email_outbox(
            item, success=False, error_code="provider_unavailable",
            retry_after_seconds=45,
        ))
        self.assertIn("ack_recovery_email_outbox", db.calls[-1][0])
        self.assertEqual(db.calls[-1][1], (
            "outbox", "lease", False, "provider_unavailable", 45, 5,
        ))

    def test_runtime_claim_expires_trials_before_leasing_updates(self):
        class DB:
            def __init__(self): self.calls = []
            def query(self, sql, params=()):
                self.calls.append((sql, params))
                return []

        db = DB()
        self.assertEqual(service.RuntimeStore(db).claim_updates(worker_id="runtime-1", limit=2), [])
        self.assertEqual(db.calls, [
            ("SELECT admira.expire_due_trials()", ()),
            ("SELECT * FROM admira.claim_telegram_updates(%s,%s,%s)", ("runtime-1", 2, 360)),
        ])

    def test_scheduler_claim_expires_trials_before_leasing_jobs(self):
        class DB:
            def __init__(self): self.calls = []
            def query(self, sql, params=()):
                self.calls.append((sql, params))
                return []

        db = DB()
        self.assertEqual(service.SchedulerStore(db).claim_jobs(worker_id="scheduler-1", limit=3), [])
        self.assertEqual(db.calls, [
            ("SELECT admira.expire_due_trials()", ()),
            ("SELECT * FROM admira.claim_due_scheduled_jobs(%s,%s,%s)", ("scheduler-1", 3, 900)),
        ])

    def test_scheduler_image_access_fails_closed_and_serializes_deadline(self):
        class DB:
            def __init__(self, rows): self.rows = rows
            def query(self, sql, params=()):
                self.sql, self.params = sql, params
                return self.rows

        empty = DB([])
        self.assertEqual(service.SchedulerStore(empty).image_access("tenant-a"), {
            "lifecycle_state": "suspended", "route": "blocked",
            "image_sponsorship_ends_at": "",
        })
        db = DB([{
            "lifecycle_state": "licensed", "route": "central_sponsored",
            "image_sponsorship_ends_at": datetime(2026, 9, 28, tzinfo=timezone.utc),
        }])
        resolved = service.SchedulerStore(db).image_access("tenant-a")
        self.assertEqual(resolved["route"], "central_sponsored")
        self.assertEqual(resolved["image_sponsorship_ends_at"], "2026-09-28T00:00:00+00:00")

    def test_telegram_429_is_typed_and_retry_after_is_bounded(self):
        signal = service._telegram_rate_limit(
            {"ok": False, "error_code": 429, "parameters": {"retry_after": 999999}}
        )
        self.assertIsInstance(signal, service.TelegramRateLimit)
        self.assertEqual(signal.error_code, "telegram_rate_limited")
        self.assertEqual(signal.retry_after, 900)
        self.assertIsNone(service._telegram_rate_limit("not-json"))
        self.assertIsNone(service._telegram_rate_limit({"ok": False, "error_code": 400}))

    def test_delivery_store_passes_max_attempts_to_ack_function(self):
        class DB:
            def __init__(self): self.calls = []
            def query(self, sql, params):
                self.calls.append((sql, params))
                return [{"acknowledged": True}]
        db = DB()
        store = service.DeliveryStore(db)
        item = worker_module.OutboxItem("row", "tenant", "bot", "123", "text", "body", "", "", "", 8, "lease")
        self.assertTrue(store.ack_outbox(item, success=False, delay_seconds=37,
                                         error_code="telegram_rate_limited", max_attempts=20))
        self.assertEqual(db.calls[0][1][-2:], (37, 20))

    def test_delivery_store_claims_and_acks_recovery_chat_outbox(self):
        class DB:
            def __init__(self): self.calls = []
            def query(self, sql, params):
                self.calls.append((sql, params))
                if "claim_recovery_chat_outbox" in sql:
                    return [{"outbox_id": "row", "request_id": "request", "bot_id": "bot-1",
                             "chat_id": "123", "user_id": "456", "template_code": "recovery_pending",
                             "body": "Código enviado.", "attempt_count": 1, "lease_token": "lease"}]
                return [{"acknowledged": True}]
        db = DB()
        store = service.DeliveryStore(db)
        item = store.claim_recovery_outbox(worker_id="delivery-1", limit=1)[0]
        self.assertIsInstance(item, worker_module.RecoveryOutboxItem)
        self.assertEqual(item.body, "Código enviado.")
        self.assertTrue(store.ack_recovery_outbox(item, success=False,
                                                   error_code="telegram_unavailable", delay_seconds=12))
        self.assertIn("ack_recovery_chat_outbox", db.calls[-1][0])
        self.assertEqual(db.calls[-1][1][-2:], (12, 5))

    def test_telegram_request_http_429_never_exposes_response_body(self):
        api = object.__new__(service.TelegramAPI)
        api.token, api._bot_id = "redacted-test-token", ""
        error = urllib.error.HTTPError(
            "https://api.telegram.org", 429, "too many", {},
            __import__("io").BytesIO(b'{"ok":false,"error_code":429,"parameters":{"retry_after":4},"description":"secret body"}'),
        )
        with patch.object(service.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(service.TelegramRateLimit) as raised:
                api._request("sendMessage", {"chat_id": "123", "text": "hello"})
        self.assertEqual(raised.exception.retry_after, 4)
        self.assertEqual(str(raised.exception), "telegram_rate_limited")

    def test_multipart_non_json_429_is_typed_rate_limit(self):
        class Response:
            status = 429
            def read(self): return b"temporarily blocked"
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def __getattr__(self, name): return lambda *args, **kwargs: None
            def getresponse(self): return Response()
            def close(self): pass
        api = object.__new__(service.TelegramAPI)
        api.token, api._bot_id = "redacted-test-token", ""
        with tempfile.TemporaryDirectory() as raw, patch.object(service.http.client, "HTTPSConnection", Connection):
            path = Path(raw) / "x.png"
            path.write_bytes(b"image")
            with self.assertRaises(service.TelegramRateLimit) as raised:
                api.send_file("123", "photo", path)
        self.assertEqual(raised.exception.retry_after, 1)

    def test_multipart_non_dict_400_is_generic_media_rejection(self):
        class Response:
            status = 400
            def read(self): return b"[]"
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def __getattr__(self, name): return lambda *args, **kwargs: None
            def getresponse(self): return Response()
            def close(self): pass
        api = object.__new__(service.TelegramAPI)
        api.token, api._bot_id = "redacted-test-token", ""
        with tempfile.TemporaryDirectory() as raw, patch.object(service.http.client, "HTTPSConnection", Connection):
            path = Path(raw) / "x.png"
            path.write_bytes(b"image")
            with self.assertRaisesRegex(service.TelegramError, "telegram_media_rejected"):
                api.send_file("123", "photo", path)

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

    def test_poller_does_not_advance_after_inbox_database_failure(self):
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

    def test_media_retry_then_durable_text_fallback_advances_cursor(self):
        api = PollerAPI([update(11)])
        store = CursorStore()
        ingress = MediaRetryIngress(["media_failed", "media_failed", "media_failed"], fallback_result=True)
        with patch.object(service, "TelegramAPI", return_value=api), \
             patch.object(service, "Pg", return_value=object()), \
             patch.object(service, "IngressStore", return_value=store), \
             patch.object(service, "TelegramIngress", return_value=ingress), \
             patch.object(service, "TelegramMediaStager"), \
             patch.dict(service.os.environ, {"TELEGRAM_BOT_TOKEN_FILE": "/not-read"}), \
             patch.object(service, "_stop_event", return_value=__import__("threading").Event()):
            service.run_poller(once=True)
        self.assertEqual(ingress.handle_calls, 3)
        self.assertEqual(ingress.fallback_calls, 1)
        self.assertEqual(store.advanced, [("bot-1", 12)])

    def test_media_fallback_db_failure_or_binding_change_keeps_cursor_parked(self):
        for fallback_result, fallback_error in ((None, None), (None, RuntimeError("db_down"))):
            with self.subTest(fallback_result=fallback_result, fallback_error=fallback_error):
                api = PollerAPI([update(11)])
                store = CursorStore()
                ingress = MediaRetryIngress(
                    ["media_failed", "media_failed", "media_failed"],
                    fallback_result=fallback_result,
                    fallback_error=fallback_error,
                )
                with patch.object(service, "TelegramAPI", return_value=api), \
                     patch.object(service, "Pg", return_value=object()), \
                     patch.object(service, "IngressStore", return_value=store), \
                     patch.object(service, "TelegramIngress", return_value=ingress), \
                     patch.object(service, "TelegramMediaStager"), \
                     patch.dict(service.os.environ, {"TELEGRAM_BOT_TOKEN_FILE": "/not-read"}), \
                     patch.object(service, "_stop_event", return_value=__import__("threading").Event()):
                    service.run_poller(once=True)
                self.assertEqual(ingress.fallback_calls, 1)
                self.assertEqual(store.advanced, [])

    def test_later_media_retry_success_advances_without_fallback(self):
        api = SequencePollerAPI([[update(11)], [update(11)]])
        store = CursorStore()
        ingress = MediaRetryIngress(
            ["media_failed", "media_failed", "media_failed", "queued"],
            fallback_error=RuntimeError("db_down"),
        )
        stop = StopAfterPolls(api, 2)
        with patch.object(service, "TelegramAPI", return_value=api), \
             patch.object(service, "Pg", return_value=object()), \
             patch.object(service, "IngressStore", return_value=store), \
             patch.object(service, "TelegramIngress", return_value=ingress), \
             patch.object(service, "TelegramMediaStager"), \
             patch.dict(service.os.environ, {"TELEGRAM_BOT_TOKEN_FILE": "/not-read"}), \
             patch.object(service, "_stop_event", return_value=stop):
            service.run_poller()
        self.assertEqual(ingress.fallback_calls, 1)
        self.assertEqual(store.advanced, [("bot-1", 12)])
        self.assertEqual(api.calls, [(10, 25), (10, 25)])

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
        self.assertEqual(worker.process_once(), {"completed": 0, "retried": 0, "busy": 0, "deferred": 0, "evicted": 0})

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
