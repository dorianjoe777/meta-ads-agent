from __future__ import annotations

import importlib.util
import random
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hosted_worker", ROOT / "deploy" / "contabo" / "hosted_worker.py")
worker = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules["hosted_worker"] = worker
SPEC.loader.exec_module(worker)


def runtime_update(attempts=1):
    return worker.RuntimeUpdate("u1", "tenant-uuid", "client-001", "bot-1", 7, "123", "123",
                                {"message": "hola", "language": "es", "media": []}, attempts, "update-lease")


class RuntimeStore:
    def __init__(self, items, runtime_lease="runtime-lease"):
        self.items, self.runtime_lease, self.events = list(items), runtime_lease, []
    def claim_updates(self, **_): result, self.items = self.items, []; return result
    def acquire_runtime(self, tenant_id, **_): self.events.append(("acquire", tenant_id)); return self.runtime_lease
    def release_runtime(self, tenant_id, lease): self.events.append(("release", tenant_id, lease))
    def sync_jobs(self, update, lease, jobs): self.events.append(("sync", update.row_id, lease, jobs))
    def complete_update(self, update, **data): self.events.append(("complete", update.row_id, data))
    def retry_update(self, update, **data): self.events.append(("retry", update.row_id, data["error_code"]))


class Broker:
    def __init__(self, result): self.result, self.calls = result, []
    def request(self, body): self.calls.append(body); return self.result


class DeliveryStore:
    def __init__(self, items): self.items, self.events, self.claim_limits = list(items), [], []
    def claim_outbox(self, **kwargs):
        self.claim_limits.append(kwargs["limit"])
        result, self.items = self.items[:kwargs["limit"]], self.items[kwargs["limit"]:]
        return result
    def ack_outbox(self, item, **data): self.events.append((item.row_id, data)); return True


class Telegram:
    def __init__(self): self.calls = []
    def send_text(self, bot, chat, text): self.calls.append(("text", chat, text)); return 10
    def send_media(self, bot, chat, kind, ref, caption="", sha256=""): self.calls.append((kind, chat, ref)); return 11
    def cleanup_media(self, ref): self.calls.append(("cleanup", ref))


class RateLimitSignal(RuntimeError):
    error_code = "telegram_rate_limited"
    def __init__(self, retry_after):
        self.retry_after = retry_after
        super().__init__(self.error_code)


class FakeClock:
    def __init__(self): self.value, self.sleeps = 0.0, []
    def now(self): return self.value
    def sleep(self, amount): self.sleeps.append(amount); self.value += amount


class SchedulerStore:
    def __init__(self, items): self.items, self.events = list(items), []
    def claim_jobs(self, **_): result, self.items = self.items, []; return result
    def acquire_runtime(self, tenant_id, **_): return "runtime-lease"
    def release_runtime(self, tenant_id, lease): self.events.append(("release", tenant_id))
    def complete_job(self, work, **data): self.events.append(("complete", work.run_id, data))
    def retry_job(self, work, **data): self.events.append(("retry", work.run_id, data["error_code"]))
    def idle_runtimes(self, **_): return [("tenant-uuid", "client-001")]
    def mark_suspended(self, tenant_id): self.events.append(("suspended", tenant_id))


class HostedWorkerTests(unittest.TestCase):
    def test_runtime_turn_is_queued_transactionally_and_syncs_cron(self):
        store = RuntimeStore([runtime_update()])
        broker = Broker({"ok": True, "reply": "respuesta", "media": [], "cron_jobs": [{"id": "j1"}]})
        result = worker.RuntimeWorker(store, broker, rng=random.Random(1)).process_once()
        self.assertEqual(result, {"completed": 1, "retried": 0, "busy": 0})
        self.assertEqual(broker.calls[0]["tenant_id"], "client-001")
        self.assertEqual(broker.calls[0]["turn"]["user_id"], "123")
        self.assertEqual([event[0] for event in store.events], ["acquire", "sync", "complete", "release"])

    def test_runtime_failure_retries_with_safe_code(self):
        store = RuntimeStore([runtime_update()])
        result = worker.RuntimeWorker(store, Broker({"ok": False, "error_code": "runtime_timeout"}), rng=random.Random(1)).process_once()
        self.assertEqual(result["retried"], 1)
        self.assertIn(("retry", "u1", "runtime_timeout"), store.events)

    def test_busy_runtime_does_not_call_broker(self):
        store, broker = RuntimeStore([runtime_update()], runtime_lease=None), Broker({"ok": True})
        result = worker.RuntimeWorker(store, broker).process_once()
        self.assertEqual(result["busy"], 1)
        self.assertFalse(broker.calls)

    def test_outbox_delivers_opaque_media_and_cleans_after_ack(self):
        ref = "a" * 32 + ".png"
        item = worker.OutboxItem("o1", "t1", "bot", "123", "photo", "", ref, "b" * 64, "", 1, "lease")
        store, telegram = DeliveryStore([item]), Telegram()
        result = worker.OutboxWorker(store, telegram).process_once()
        self.assertEqual(result, {"sent": 1, "retried": 0})
        self.assertEqual(store.claim_limits, [1])
        self.assertEqual([call[0] for call in telegram.calls], ["photo", "cleanup"])
        self.assertTrue(store.events[0][1]["success"])

    def test_outbox_rejects_host_paths(self):
        item = worker.OutboxItem("o1", "t1", "bot", "123", "photo", "", "/etc/passwd", "", "", 1, "lease")
        store = DeliveryStore([item])
        result = worker.OutboxWorker(store, Telegram(), rng=random.Random(1)).process_once()
        self.assertEqual(result["retried"], 1)
        self.assertFalse(store.events[0][1]["success"])

    def test_outbox_does_not_delete_media_when_ack_lease_is_lost(self):
        class LostLeaseStore(DeliveryStore):
            def ack_outbox(self, item, **data):
                self.events.append((item.row_id, data))
                return False

        ref = "a" * 32 + ".png"
        item = worker.OutboxItem("o1", "t1", "bot", "123", "photo", "", ref, "b" * 64, "", 1, "lease")
        store, telegram = LostLeaseStore([item]), Telegram()
        result = worker.OutboxWorker(store, telegram).process_once()
        self.assertEqual(result, {"sent": 0, "retried": 1})
        self.assertNotIn("cleanup", [call[0] for call in telegram.calls])

    def test_outbox_rate_limit_uses_bounded_retry_and_extended_attempt_budget(self):
        item = worker.OutboxItem("o1", "t1", "bot", "123", "text", "hello", "", "", "", 8, "lease")
        store = DeliveryStore([item])
        class Limited:
            def send_text(self, bot, chat, text):
                raise RateLimitSignal(37)
        result = worker.OutboxWorker(store, Limited(), limiter=worker.DeliveryRateLimiter(global_interval=0, chat_interval=0)).process_once()
        self.assertEqual(result, {"sent": 0, "retried": 1})
        self.assertEqual(store.events[0][1]["delay_seconds"], 37)
        self.assertEqual(store.events[0][1]["max_attempts"], 20)
        self.assertEqual(store.events[0][1]["error_code"], "telegram_rate_limited")

    def test_delivery_rate_limiter_paces_global_and_per_chat(self):
        clock = FakeClock()
        limiter = worker.DeliveryRateLimiter(global_interval=0.5, chat_interval=1.0,
                                             clock=clock.now, sleeper=clock.sleep)
        limiter.before_send("chat-a")
        limiter.before_send("chat-b")
        limiter.before_send("chat-a")
        self.assertEqual(clock.sleeps, [0.5, 0.5])

    def test_rate_limit_defers_next_different_chat_before_claim(self):
        clock = FakeClock()
        limiter = worker.DeliveryRateLimiter(global_interval=0, chat_interval=0,
                                             clock=clock.now, sleeper=clock.sleep)
        first = worker.OutboxItem("o1", "t1", "bot", "123", "text", "one", "", "", "", 1, "l1")
        second = worker.OutboxItem("o2", "t2", "bot", "456", "text", "two", "", "", "", 1, "l2")
        class Telegram429ThenOK:
            def __init__(self): self.calls = []
            def send_text(self, bot, chat, text):
                self.calls.append(chat)
                if len(self.calls) == 1: raise RateLimitSignal(7)
                return 2
        store = DeliveryStore([first, second])
        telegram = Telegram429ThenOK()
        delivery = worker.OutboxWorker(store, telegram, limiter=limiter)
        first_result = delivery.process_once()
        second_result = delivery.process_once()
        self.assertEqual(first_result, {"sent": 0, "retried": 1})
        self.assertEqual(second_result, {"sent": 1, "retried": 0})
        self.assertEqual(clock.sleeps, [7])
        self.assertEqual(telegram.calls, ["123", "456"])
        self.assertEqual(store.claim_limits, [1, 1])

    def test_delivery_never_holds_a_batch_lease_through_backpressure(self):
        clock = FakeClock()
        limiter = worker.DeliveryRateLimiter(global_interval=0, chat_interval=0,
                                             clock=clock.now, sleeper=clock.sleep)
        items = [worker.OutboxItem(f"o{i}", "t1", "bot", str(i), "text", "x", "", "", "", 1, f"l{i}")
                 for i in range(3)]
        store = DeliveryStore(items)
        delivery = worker.OutboxWorker(store, Telegram(), limiter=limiter)
        delivery.process_once(limit=99)
        self.assertEqual(store.claim_limits, [1])
        self.assertEqual(len(store.items), 2)

    def test_scheduler_executes_and_uses_runtime_next_run(self):
        work = worker.ScheduledWork("j-db", "tenant-uuid", "client-001", "hermes-1", {"chat_id": "123"},
                                    datetime.now(timezone.utc), "run-1", 1, "job-lease")
        store = SchedulerStore([work])
        broker = Broker({"ok": True, "reply": "lectura", "media": [],
                         "cron_jobs": [{"id": "hermes-1", "enabled": True, "next_run_at": "2026-08-28T08:00:00+00:00"}]})
        result = worker.SchedulerWorker(store, broker).process_once()
        self.assertEqual(result["completed"], 1)
        self.assertEqual(store.events[0][0], "complete")
        self.assertEqual(store.events[0][2]["next_run_at"], "2026-08-28T08:00:00+00:00")

    def test_idle_runtime_is_suspended_only_after_broker_success(self):
        store = SchedulerStore([])
        count = worker.SchedulerWorker(store, Broker({"ok": True})).suspend_idle_once()
        self.assertEqual(count, 1)
        self.assertIn(("suspended", "tenant-uuid"), store.events)


if __name__ == "__main__":
    unittest.main()
