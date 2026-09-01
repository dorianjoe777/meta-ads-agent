from __future__ import annotations

import importlib.util
import random
import sys
import time
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
    def __init__(self, items, runtime_lease="runtime-lease", idle_candidates=()):
        self.items, self.runtime_lease, self.events = list(items), runtime_lease, []
        self.idle_candidates = list(idle_candidates)
    def claim_updates(self, **kwargs):
        result, self.items = self.items[:kwargs.get("limit", 1)], self.items[kwargs.get("limit", 1):]
        return result
    def image_access(self, tenant_id):
        self.events.append(("image-access", tenant_id))
        return {
            "lifecycle_state": "trial",
            "route": "central_sponsored",
            "image_sponsorship_ends_at": "",
        }
    def acquire_runtime(self, tenant_id, **_): self.events.append(("acquire", tenant_id)); return self.runtime_lease
    def release_runtime(self, tenant_id, lease): self.events.append(("release", tenant_id, lease))
    def sync_jobs(self, update, lease, jobs): self.events.append(("sync", update.row_id, lease, jobs))
    def complete_update(self, update, **data): self.events.append(("complete", update.row_id, data))
    def retry_update(self, update, **data): self.events.append(("retry", update.row_id, data["error_code"]))
    def defer_update_capacity(self, update, **data): self.events.append(("defer", update.row_id, data["error_code"]))
    def claim_idle_runtime(self, **kwargs):
        self.events.append(("evict-claim", kwargs))
        return self.idle_candidates[:1]
    def complete_idle_runtime(self, tenant_id, token):
        self.events.append(("evict-complete", tenant_id, token))
        if self.idle_candidates:
            self.idle_candidates.pop(0)
        return True
    def release_idle_runtime_claim(self, tenant_id, token):
        self.events.append(("evict-release", tenant_id, token))
        return True


class Broker:
    def __init__(self, result):
        self.results = list(result) if isinstance(result, list) else [result]
        self.calls = []
    def request(self, body):
        self.calls.append(body)
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


class DeliveryStore:
    def __init__(self, items): self.items, self.events, self.claim_limits = list(items), [], []
    def claim_outbox(self, **kwargs):
        self.claim_limits.append(kwargs["limit"])
        result, self.items = self.items[:kwargs["limit"]], self.items[kwargs["limit"]:]
        return result
    def ack_outbox(self, item, **data): self.events.append((item.row_id, data)); return True


class RecoveryDeliveryStore(DeliveryStore):
    def __init__(self, items):
        super().__init__([])
        self.recovery_items, self.recovery_events = list(items), []
    def claim_recovery_outbox(self, **kwargs):
        self.claim_limits.append(("recovery", kwargs["limit"]))
        result, self.recovery_items = self.recovery_items[:kwargs["limit"]], self.recovery_items[kwargs["limit"]:]
        return result
    def ack_recovery_outbox(self, item, **data):
        self.recovery_events.append((item.row_id, data))
        return True


class Telegram:
    def __init__(self): self.calls = []
    def send_text(self, bot, chat, text): self.calls.append(("text", chat, text)); return 10
    def send_media(self, bot, chat, kind, ref, caption="", sha256=""): self.calls.append((kind, chat, ref)); return 11
    def send_chat_action(self, bot, chat, action="typing"): self.calls.append(("action", bot, chat, action))
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
    def __init__(self, items, runtime_lease="runtime-lease"):
        self.items, self.events, self.runtime_lease = list(items), [], runtime_lease
    def claim_jobs(self, **_): result, self.items = self.items, []; return result
    def image_access(self, tenant_id):
        return {
            "lifecycle_state": "licensed",
            "route": "central_sponsored",
            "image_sponsorship_ends_at": "2026-09-28T00:00:00+00:00",
        }
    def acquire_runtime(self, tenant_id, **_): return self.runtime_lease
    def release_runtime(self, tenant_id, lease): self.events.append(("release", tenant_id))
    def complete_job(self, work, **data): self.events.append(("complete", work.run_id, data))
    def retry_job(self, work, **data): self.events.append(("retry", work.run_id, data["error_code"]))
    def defer_job_capacity(self, work, **data): self.events.append(("defer", work.run_id, data["error_code"]))
    def idle_runtimes(self, **_): return [("tenant-uuid", "client-001")]
    def mark_suspended(self, tenant_id): self.events.append(("suspended", tenant_id))


class HostedWorkerTests(unittest.TestCase):
    def test_runtime_stores_reply_without_leaked_tirith_review_preamble(self):
        store = RuntimeStore([runtime_update()])
        broker = Broker({
            "ok": True,
            "reply": (
                "Tirith security scanner review\n"
                "Review diff\n"
                "a/deploy/worker.py -> b/deploy/worker.py\n"
                "@@ -1,2 +1,2 @@\n"
                "- internal detail\n"
                "+ another detail\n"
                "Hola **comprador**, tu pedido está listo.\n"
                "¿Necesitas algo más?"
            ),
            "media": [],
        })
        result = worker.RuntimeWorker(store, broker).process_once()
        self.assertEqual(result["completed"], 1)
        complete = next(event for event in store.events if event[0] == "complete")
        self.assertEqual(
            complete[2]["reply"],
            "Hola **comprador**, tu pedido está listo.\n¿Necesitas algo más?",
        )

    def test_scheduler_preserves_ordinary_reply_content_when_cleaning(self):
        work = worker.ScheduledWork("j-db", "tenant-uuid", "client-001", "hermes-1", {},
                                    datetime.now(timezone.utc), "run-1", 1, "job-lease")
        store = SchedulerStore([work])
        broker = Broker({
            "ok": True,
            "reply": "tirith security scanner\n@@ review\n- leaked\n**Oferta especial** para ti",
            "media": [], "cron_jobs": [],
        })
        result = worker.SchedulerWorker(store, broker).process_once()
        self.assertEqual(result["completed"], 1)
        self.assertEqual(store.events[0][2]["reply"], "**Oferta especial** para ti")

    def test_typing_heartbeat_starts_refreshes_and_stops(self):
        telegram = Telegram()
        heartbeat = worker.TelegramTypingHeartbeat(telegram, "bot-1", "123", interval=0.01)
        heartbeat.start()
        deadline = time.monotonic() + 1
        while len([call for call in telegram.calls if call[0] == "action"]) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        heartbeat.stop()
        count = len([call for call in telegram.calls if call[0] == "action"])
        time.sleep(0.03)
        self.assertGreaterEqual(count, 2)
        self.assertEqual(count, len([call for call in telegram.calls if call[0] == "action"]))
        self.assertTrue(all(call == ("action", "bot-1", "123", "typing")
                            for call in telegram.calls if call[0] == "action"))

    def test_typing_heartbeat_ignores_send_failures_and_stops(self):
        class FailingTelegram:
            def __init__(self): self.calls = 0
            def send_chat_action(self, *_args):
                self.calls += 1
                raise RuntimeError("token must not escape")

        telegram = FailingTelegram()
        heartbeat = worker.TelegramTypingHeartbeat(telegram, "bot-1", "123", interval=0.01).start()
        time.sleep(0.25)
        heartbeat.stop()
        self.assertGreaterEqual(telegram.calls, 2)

    def test_runtime_turn_is_queued_transactionally_and_syncs_cron(self):
        store = RuntimeStore([runtime_update()])
        broker = Broker({"ok": True, "reply": "respuesta", "media": [], "cron_jobs": [{"id": "j1"}]})
        result = worker.RuntimeWorker(store, broker, rng=random.Random(1)).process_once()
        self.assertEqual(result, {"completed": 1, "retried": 0, "busy": 0, "deferred": 0, "evicted": 0})
        self.assertEqual(broker.calls[0]["tenant_id"], "client-001")
        self.assertEqual(broker.calls[0]["turn"]["user_id"], "123")
        self.assertEqual(broker.calls[0]["turn"]["image_access"]["route"], "central_sponsored")
        self.assertFalse(broker.calls[0]["turn"]["image_access"]["central_ready"])
        self.assertEqual([event[0] for event in store.events], ["acquire", "image-access", "sync", "complete", "release"])

    def test_runtime_marks_central_image_service_ready_only_when_explicit(self):
        store = RuntimeStore([runtime_update()])
        broker = Broker({"ok": True, "reply": "respuesta", "media": []})
        worker.RuntimeWorker(store, broker, central_image_ready=True).process_once()
        self.assertTrue(broker.calls[0]["turn"]["image_access"]["central_ready"])

    def test_runtime_failure_retries_with_safe_code(self):
        store = RuntimeStore([runtime_update()])
        result = worker.RuntimeWorker(store, Broker({"ok": False, "error_code": "runtime_timeout"}), rng=random.Random(1)).process_once()
        self.assertEqual(result["retried"], 1)
        self.assertIn(("retry", "u1", "runtime_timeout"), store.events)

    def test_busy_runtime_does_not_call_broker(self):
        store = RuntimeStore(
            [runtime_update()], runtime_lease=None,
            idle_candidates=[("idle-tenant", "client-idle", "eviction-token")],
        )
        broker = Broker({"ok": True})
        result = worker.RuntimeWorker(store, broker).process_once()
        self.assertEqual(result["busy"], 1)
        self.assertEqual(result["deferred"], 1)
        self.assertIn(("defer", "u1", "tenant_busy"), store.events)
        self.assertNotIn("evict-claim", [event[0] for event in store.events])
        self.assertFalse(broker.calls)

    def test_capacity_failure_evicts_one_fenced_idle_runtime_and_retries(self):
        store = RuntimeStore(
            [runtime_update()],
            idle_candidates=[("idle-tenant", "client-idle", "eviction-token")],
        )
        broker = Broker([
            {"ok": False, "error_code": "runtime_capacity_exhausted"},
            {"ok": True},
            {"ok": True, "reply": "respuesta", "media": []},
        ])
        result = worker.RuntimeWorker(store, broker, worker_id="worker-1").process_once()
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["evicted"], 1)
        self.assertEqual([call["action"] for call in broker.calls], ["turn", "suspend", "turn"])
        claim = next(event for event in store.events if event[0] == "evict-claim")
        self.assertEqual(claim[1], {"worker_id": "worker-1", "idle_seconds": 0, "claim_seconds": 60})
        self.assertIn(("evict-complete", "idle-tenant", "eviction-token"), store.events)

    def test_capacity_headroom_without_idle_runtime_is_durably_deferred(self):
        store = RuntimeStore([runtime_update()])
        result = worker.RuntimeWorker(
            store, Broker({"ok": False, "error_code": "runtime_capacity_headroom_low"})
        ).process_once()
        self.assertEqual(result["retried"], 0)
        self.assertEqual(result["deferred"], 1)
        self.assertIn(("defer", "u1", "runtime_capacity_headroom_low"), store.events)

    def test_failed_suspend_releases_fenced_claim_and_defers(self):
        store = RuntimeStore(
            [runtime_update()],
            idle_candidates=[("idle-tenant", "client-idle", "eviction-token")],
        )
        broker = Broker([
            {"ok": False, "error_code": "runtime_capacity_exhausted"},
            {"ok": False, "error_code": "runtime_suspend_failed"},
        ])
        result = worker.RuntimeWorker(store, broker).process_once()
        self.assertEqual(result["deferred"], 1)
        self.assertEqual(result["evicted"], 0)
        self.assertIn(("evict-release", "idle-tenant", "eviction-token"), store.events)

    def test_runtime_worker_claims_one_update_per_cycle(self):
        second = worker.RuntimeUpdate("u2", "tenant-uuid", "client-001", "bot-1", 8, "123", "123",
                                      {"message": "dos", "language": "es", "media": []}, 1, "lease-2")
        store = RuntimeStore([runtime_update(), second])
        result = worker.RuntimeWorker(store, Broker({"ok": True, "reply": "ok", "media": []})).process_once(limit=4)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(len(store.items), 1)

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

    def test_recovery_outbox_sends_fixed_body_and_acks(self):
        item = worker.RecoveryOutboxItem("r1", "request-1", "bot", "123", "456",
                                         "recovery_pending", "Código enviado.", 1, "lease")
        store, telegram = RecoveryDeliveryStore([item]), Telegram()
        result = worker.OutboxWorker(
            store, telegram, limiter=worker.DeliveryRateLimiter(global_interval=0, chat_interval=0)
        ).process_once()
        self.assertEqual(result, {"sent": 1, "retried": 0})
        self.assertEqual(telegram.calls, [("text", "123", "Código enviado.")])
        self.assertEqual(store.recovery_events[0][1]["success"], True)

    def test_recovery_outbox_rate_limit_uses_allowed_code(self):
        item = worker.RecoveryOutboxItem("r1", "request-1", "bot", "123", "456",
                                         "recovery_failed", "No se pudo.", 1, "lease")
        class LimitedTelegram:
            def send_text(self, bot, chat, text): raise RateLimitSignal(37)
        store = RecoveryDeliveryStore([item])
        result = worker.OutboxWorker(
            store, LimitedTelegram(), limiter=worker.DeliveryRateLimiter(global_interval=0, chat_interval=0)
        ).process_once()
        self.assertEqual(result, {"sent": 0, "retried": 1})
        self.assertEqual(store.recovery_events[0][1]["error_code"], "telegram_rate_limited")
        self.assertEqual(store.recovery_events[0][1]["delay_seconds"], 37)

    def test_recovery_outbox_provider_error_is_safe_and_retryable(self):
        item = worker.RecoveryOutboxItem("r1", "request-1", "bot", "123", "456",
                                         "recovery_failed", "No se pudo.", 1, "lease")
        class FailedTelegram:
            def send_text(self, bot, chat, text): raise RuntimeError("secret provider detail")
        store = RecoveryDeliveryStore([item])
        result = worker.OutboxWorker(store, FailedTelegram(), rng=random.Random(1),
                                      limiter=worker.DeliveryRateLimiter(global_interval=0, chat_interval=0)).process_once()
        self.assertEqual(result["retried"], 1)
        self.assertEqual(store.recovery_events[0][1]["error_code"], "internal_error")

    def test_recovery_outbox_uses_transport_bot_identity_fence(self):
        item = worker.RecoveryOutboxItem("r1", "request-1", "wrong-bot", "123", "456",
                                         "recovery_failed", "No se pudo.", 1, "lease")
        class IdentityCheckingTelegram:
            def send_text(self, bot, chat, text):
                if bot != "bot-1":
                    error = RuntimeError("telegram_bot_mismatch")
                    error.error_code = "telegram_bot_mismatch"
                    raise error
                return 1
        store = RecoveryDeliveryStore([item])
        worker.OutboxWorker(store, IdentityCheckingTelegram(),
                            limiter=worker.DeliveryRateLimiter(global_interval=0, chat_interval=0)).process_once()
        self.assertEqual(store.recovery_events[0][1]["error_code"], "telegram_unavailable")

    def test_recovery_outbox_does_not_ack_after_lost_lease(self):
        item = worker.RecoveryOutboxItem("r1", "request-1", "bot", "123", "456",
                                         "recovery_completed", "Listo.", 1, "lease")
        class LostLeaseStore(RecoveryDeliveryStore):
            def ack_recovery_outbox(self, item, **data):
                self.recovery_events.append((item.row_id, data))
                return False
        store = LostLeaseStore([item])
        result = worker.OutboxWorker(store, Telegram(), limiter=worker.DeliveryRateLimiter(global_interval=0, chat_interval=0)).process_once()
        self.assertEqual(result, {"sent": 0, "retried": 1})
        # The second acknowledgement is the durable retry attempt; it must
        # still use the recovery-safe error enum rather than exception text.
        self.assertEqual(store.recovery_events[-1][1]["error_code"], "internal_error")

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
        self.assertEqual(broker.calls[0]["image_access"]["route"], "central_sponsored")
        self.assertFalse(broker.calls[0]["image_access"]["central_ready"])
        self.assertEqual(store.events[0][0], "complete")
        self.assertEqual(store.events[0][2]["next_run_at"], "2026-08-28T08:00:00+00:00")

    def test_scheduler_marks_central_image_service_ready_only_when_explicit(self):
        work = worker.ScheduledWork("j-db", "tenant-uuid", "client-001", "hermes-1", {},
                                    datetime.now(timezone.utc), "run-1", 1, "job-lease")
        broker = Broker({"ok": True, "reply": "", "media": [], "cron_jobs": []})
        worker.SchedulerWorker(
            SchedulerStore([work]), broker, central_image_ready=True
        ).process_once()
        self.assertTrue(broker.calls[0]["image_access"]["central_ready"])

    def test_scheduler_capacity_does_not_spend_failure_budget(self):
        work = worker.ScheduledWork("j-db", "tenant-uuid", "client-001", "hermes-1", {},
                                    datetime.now(timezone.utc), "run-1", 5, "job-lease")
        store = SchedulerStore([work])
        result = worker.SchedulerWorker(
            store, Broker({"ok": False, "error_code": "runtime_capacity_exhausted"})
        ).process_once()
        self.assertEqual(result["retried"], 0)
        self.assertEqual(result["deferred"], 1)
        self.assertIn(("defer", "run-1", "runtime_capacity_exhausted"), store.events)

    def test_scheduler_same_tenant_contention_is_deferred(self):
        work = worker.ScheduledWork("j-db", "tenant-uuid", "client-001", "hermes-1", {},
                                    datetime.now(timezone.utc), "run-1", 5, "job-lease")
        store = SchedulerStore([work], runtime_lease=None)
        broker = Broker({"ok": True})
        result = worker.SchedulerWorker(store, broker).process_once()
        self.assertEqual(result["deferred"], 1)
        self.assertIn(("defer", "run-1", "tenant_busy"), store.events)
        self.assertFalse(broker.calls)

    def test_idle_runtime_is_suspended_only_after_broker_success(self):
        store = SchedulerStore([])
        count = worker.SchedulerWorker(store, Broker({"ok": True})).suspend_idle_once()
        self.assertEqual(count, 1)
        self.assertIn(("suspended", "tenant-uuid"), store.events)


if __name__ == "__main__":
    unittest.main()
