#!/usr/bin/env python3
"""Injectable workers for hosted Telegram turns, delivery, and cron jobs."""

from __future__ import annotations

import random
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol, Sequence


MEDIA_REF_RE = re.compile(r"^[a-f0-9]{32,64}\.(?:jpg|jpeg|png|webp|gif|mp4|mov|pdf|bin)$")
CAPACITY_ERROR_CODES = frozenset({"runtime_capacity_exhausted", "runtime_capacity_headroom_low"})
CAPACITY_DEFER_SECONDS = 2
# The intended 6-normal/8-hard profile needs at most three idle evictions to
# drain burst and replace one warm runtime. Eight keeps every valid 1..8 custom
# profile correct while the loop still stops immediately after admission.
MAX_CAPACITY_EVICTIONS = 8


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def retry_delay(attempt: int, *, base: float = 5.0, cap: float = 900.0, rng: random.Random | None = None) -> int:
    maximum = min(cap, base * (2 ** min(max(0, attempt), 20)))
    return max(1, int((rng or random).uniform(0.0, maximum)))


@dataclass(frozen=True)
class RuntimeUpdate:
    row_id: str
    tenant_id: str
    runtime_key: str
    bot_id: str
    update_id: int
    chat_id: str
    user_id: str
    payload: dict[str, object]
    attempts: int
    lease_token: str


@dataclass(frozen=True)
class OutboxItem:
    row_id: str
    tenant_id: str
    bot_id: str
    chat_id: str
    kind: str
    body: str
    media_ref: str
    media_sha256: str
    caption: str
    attempts: int
    lease_token: str


@dataclass(frozen=True)
class RecoveryOutboxItem:
    """Fixed-template recovery reply with no tenant or media access."""

    row_id: str
    request_id: str
    bot_id: str
    chat_id: str
    user_id: str
    template_code: str
    body: str
    attempts: int
    lease_token: str


@dataclass(frozen=True)
class ScheduledWork:
    job_id: str
    tenant_id: str
    runtime_key: str
    job_key: str
    payload: dict[str, object]
    scheduled_for: datetime
    run_id: str
    attempts: int
    lease_token: str


class RuntimeStore(Protocol):
    def claim_updates(self, *, worker_id: str, limit: int) -> Sequence[RuntimeUpdate]: ...
    def image_access(self, tenant_id: str) -> dict[str, object]: ...
    def acquire_runtime(self, tenant_id: str, *, holder: str) -> str | None: ...
    def release_runtime(self, tenant_id: str, lease_token: str) -> None: ...
    def sync_jobs(self, update: RuntimeUpdate, runtime_lease_token: str, jobs: list[dict[str, object]]) -> None: ...
    def complete_update(self, update: RuntimeUpdate, *, reply: str, media: list[dict[str, str]]) -> None: ...
    def retry_update(self, update: RuntimeUpdate, *, delay_seconds: int, error_code: str) -> None: ...
    def defer_update_capacity(self, update: RuntimeUpdate, *, delay_seconds: int, error_code: str) -> None: ...
    def claim_idle_runtime(self, *, worker_id: str, idle_seconds: int,
                           claim_seconds: int) -> Sequence[tuple[str, str, str]]: ...
    def complete_idle_runtime(self, tenant_id: str, eviction_token: str) -> bool: ...
    def release_idle_runtime_claim(self, tenant_id: str, eviction_token: str) -> bool: ...


class DeliveryStore(Protocol):
    def claim_outbox(self, *, worker_id: str, limit: int) -> Sequence[OutboxItem]: ...
    def ack_outbox(self, item: OutboxItem, *, success: bool, message_id: int | None = None,
                   delay_seconds: int = 30, error_code: str = "", max_attempts: int = 8) -> bool: ...
    def claim_recovery_outbox(self, *, worker_id: str, limit: int) -> Sequence[RecoveryOutboxItem]: ...
    def ack_recovery_outbox(self, item: RecoveryOutboxItem, *, success: bool,
                            delay_seconds: int = 30, error_code: str = "",
                            max_attempts: int = 5) -> bool: ...


class SchedulerStore(Protocol):
    def claim_jobs(self, *, worker_id: str, limit: int) -> Sequence[ScheduledWork]: ...
    def image_access(self, tenant_id: str) -> dict[str, object]: ...
    def acquire_runtime(self, tenant_id: str, *, holder: str) -> str | None: ...
    def release_runtime(self, tenant_id: str, lease_token: str) -> None: ...
    def complete_job(self, work: ScheduledWork, *, next_run_at: str | None,
                     reply: str, media: list[dict[str, str]], result: dict[str, object]) -> None: ...
    def retry_job(self, work: ScheduledWork, *, delay_seconds: int, error_code: str) -> None: ...
    def defer_job_capacity(self, work: ScheduledWork, *, delay_seconds: int,
                           error_code: str) -> None: ...
    def idle_runtimes(self, *, idle_seconds: int) -> Sequence[tuple[str, str]]: ...
    def mark_suspended(self, tenant_id: str) -> None: ...


class Broker(Protocol):
    def request(self, body: dict[str, object]) -> dict[str, object]: ...


class TelegramTransport(Protocol):
    def send_text(self, bot_id: str, chat_id: str, text: str) -> int: ...
    def send_media(self, bot_id: str, chat_id: str, kind: str, media_ref: str, caption: str = "", sha256: str = "") -> int: ...
    def cleanup_media(self, media_ref: str) -> None: ...


class DeliveryRateLimiter:
    """Serialize sends, pace the shared bot globally, and pace each chat."""

    def __init__(self, *, global_interval: float = 0.05, chat_interval: float = 1.0,
                 clock: Callable[[], float] = time.monotonic,
                 sleeper: Callable[[float], None] = time.sleep) -> None:
        self.global_interval = max(0.0, float(global_interval))
        self.chat_interval = max(0.0, float(chat_interval))
        self.clock, self.sleeper = clock, sleeper
        self._lock = threading.Lock()
        self._last_global = float("-inf")
        self._blocked_until = float("-inf")
        self._last_chat: dict[str, float] = {}

    def before_send(self, chat_id: str) -> None:
        with self._lock:
            now = self.clock()
            chat_last = self._last_chat.get(chat_id, float("-inf"))
            wait = max(self._blocked_until - now,
                       self._last_global + self.global_interval - now,
                       chat_last + self.chat_interval - now, 0.0)
            if wait:
                self.sleeper(wait)
                now = self.clock()
            self._last_global = now
            self._last_chat[chat_id] = now

    def before_claim(self) -> None:
        """Apply shared-bot backpressure before acquiring an outbox lease."""
        with self._lock:
            now = self.clock()
            wait = max(self._blocked_until - now,
                       self._last_global + self.global_interval - now, 0.0)
            if wait:
                self.sleeper(wait)

    def defer(self, seconds: int) -> None:
        """Pause every subsequent send after a Telegram rate-limit response."""
        with self._lock:
            self._blocked_until = max(self._blocked_until, self.clock() + max(1, int(seconds)))


def _safe_error(value: object, fallback: str) -> str:
    text = str(value or "").strip().lower()
    return text if re.fullmatch(r"[a-z0-9_]{3,80}", text) else fallback


def _safe_media(raw: object) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("ref") or "").lower()
        kind = str(item.get("kind") or "")
        digest = str(item.get("sha256") or "").lower()
        caption = str(item.get("caption") or "")[:1024]
        if kind not in {"photo", "video", "document"} or not MEDIA_REF_RE.fullmatch(ref):
            continue
        if digest and not re.fullmatch(r"[a-f0-9]{64}", digest):
            continue
        result.append({"kind": kind, "ref": ref, "sha256": digest, "caption": caption})
    return result[:8]


class RuntimeWorker:
    def __init__(self, store: RuntimeStore, broker: Broker, *, worker_id: str | None = None,
                 rng: random.Random | None = None, central_image_ready: bool = False) -> None:
        self.store, self.broker = store, broker
        self.worker_id = worker_id or f"runtime-{uuid.uuid4().hex}"
        self.rng = rng or random.Random()
        self.central_image_ready = central_image_ready is True

    def process_once(self, *, limit: int = 1) -> dict[str, int]:
        completed = retried = busy = deferred = evicted = 0
        claimed = self.store.claim_updates(worker_id=self.worker_id, limit=1)
        for update in claimed[:1]:
            runtime_lease = self.store.acquire_runtime(update.tenant_id, holder=self.worker_id)
            if not runtime_lease:
                # This is serialization for the same tenant, not host
                # capacity. Evicting another tenant cannot make this lease
                # available and would cause needless churn.
                self.store.defer_update_capacity(
                    update, delay_seconds=CAPACITY_DEFER_SECONDS, error_code="tenant_busy"
                )
                busy += 1
                deferred += 1
                continue
            try:
                message = str(update.payload.get("message") or "").strip()
                if not message:
                    message = "El comprador adjuntó un archivo. Analízalo y responde según el contexto."
                image_access = dict(self.store.image_access(update.tenant_id) or {})
                image_access["central_ready"] = self.central_image_ready
                turn_request = {
                    "action": "turn",
                    "tenant_id": update.runtime_key,
                    "turn": {
                        "message": message,
                        "language": str(update.payload.get("language") or "es"),
                        "chat_id": update.chat_id,
                        "user_id": update.user_id,
                        "update_id": update.update_id,
                        "image_access": image_access,
                    },
                    "media": list(update.payload.get("media") or []),
                }
                result = self.broker.request(turn_request)
                error_code = _safe_error(result.get("error_code"), "runtime_failure")

                # Capacity is known only after the broker counts real Docker
                # runtimes. Claim and suspend the least-recently-used runtime
                # that PostgreSQL has fenced as truly idle, then retry the
                # turn. Never evict merely because this tenant's lease is busy.
                for _attempt in range(MAX_CAPACITY_EVICTIONS):
                    if result.get("ok") or error_code not in CAPACITY_ERROR_CODES:
                        break
                    candidates = self.store.claim_idle_runtime(
                        worker_id=self.worker_id, idle_seconds=0, claim_seconds=60
                    )
                    if not candidates:
                        break
                    idle_tenant, idle_runtime, eviction_token = candidates[0]
                    eviction_completed = False
                    try:
                        suspension = self.broker.request({"action": "suspend", "tenant_id": idle_runtime})
                        if suspension.get("ok"):
                            eviction_completed = self.store.complete_idle_runtime(idle_tenant, eviction_token)
                    except Exception:
                        # The original turn is already known to be blocked on
                        # capacity. A failed eviction must release its fence
                        # and defer, not spend the turn's execution budget.
                        pass
                    finally:
                        if not eviction_completed:
                            self.store.release_idle_runtime_claim(idle_tenant, eviction_token)
                    if not eviction_completed:
                        break
                    evicted += 1
                    result = self.broker.request(turn_request)
                    error_code = _safe_error(result.get("error_code"), "runtime_failure")

                if not result.get("ok") and error_code in CAPACITY_ERROR_CODES:
                    self.store.defer_update_capacity(
                        update, delay_seconds=CAPACITY_DEFER_SECONDS, error_code=error_code
                    )
                    busy += 1
                    deferred += 1
                    continue
                reply = str(result.get("reply") or "").strip()
                media = _safe_media(result.get("media"))
                if not result.get("ok") and not reply and not media:
                    raise RuntimeError(error_code)
                jobs = result.get("cron_jobs") if isinstance(result.get("cron_jobs"), list) else []
                self.store.sync_jobs(update, runtime_lease, jobs)
                self.store.complete_update(update, reply=reply, media=media)
                completed += 1
            except Exception as exc:
                error_code = _safe_error(str(exc), type(exc).__name__.lower())
                if error_code in CAPACITY_ERROR_CODES:
                    self.store.defer_update_capacity(
                        update, delay_seconds=CAPACITY_DEFER_SECONDS, error_code=error_code
                    )
                    busy += 1
                    deferred += 1
                else:
                    delay = retry_delay(update.attempts, rng=self.rng)
                    self.store.retry_update(update, delay_seconds=delay, error_code=error_code)
                    retried += 1
            finally:
                self.store.release_runtime(update.tenant_id, runtime_lease)
        return {"completed": completed, "retried": retried, "busy": busy, "deferred": deferred, "evicted": evicted}


class OutboxWorker:
    def __init__(self, store: DeliveryStore, telegram: TelegramTransport, *, worker_id: str | None = None,
                 rng: random.Random | None = None, limiter: DeliveryRateLimiter | None = None) -> None:
        self.store, self.telegram = store, telegram
        self.worker_id = worker_id or f"delivery-{uuid.uuid4().hex}"
        self.rng = rng or random.Random()
        self.limiter = limiter or DeliveryRateLimiter()

    def process_once(self, *, limit: int = 20) -> dict[str, int]:
        sent = retried = 0
        # Never hold a batch of leases while Telegram backpressure is active.
        # In particular, retry_after may be many minutes long.
        self.limiter.before_claim()
        claimed = self.store.claim_outbox(worker_id=self.worker_id, limit=1)
        for item in claimed:
            try:
                self.limiter.before_send(item.chat_id)
                if item.kind == "text":
                    message_id = self.telegram.send_text(item.bot_id, item.chat_id, item.body)
                else:
                    if not MEDIA_REF_RE.fullmatch(item.media_ref):
                        raise ValueError("invalid_media_ref")
                    message_id = self.telegram.send_media(item.bot_id, item.chat_id, item.kind, item.media_ref, item.caption, item.media_sha256)
                if not self.store.ack_outbox(item, success=True, message_id=message_id):
                    raise RuntimeError("outbox_lease_lost")
                if item.media_ref:
                    self.telegram.cleanup_media(item.media_ref)
                sent += 1
            except Exception as exc:
                rate_after = getattr(exc, "retry_after", None)
                is_rate_limit = isinstance(rate_after, int) and getattr(exc, "error_code", "") == "telegram_rate_limited"
                if is_rate_limit:
                    self.limiter.defer(rate_after)
                try:
                    self.store.ack_outbox(
                        item, success=False,
                        delay_seconds=rate_after if is_rate_limit else retry_delay(item.attempts, rng=self.rng),
                        error_code="telegram_rate_limited" if is_rate_limit else _safe_error(str(exc), type(exc).__name__.lower()),
                        # The SQL function bounds this parameter at 20. Keep
                        # rate-limited messages on the longest supported retry
                        # budget instead of accidentally leaving the lease
                        # stuck with an invalid request.
                        max_attempts=20 if is_rate_limit else 8,
                    )
                except Exception:
                    # A lost fencing token must not crash delivery or delete
                    # the media; the durable lease owner decides the retry.
                    pass
                retried += 1
        # Recovery replies use this same delivery service, pacing and Telegram
        # identity check, but remain isolated from tenant/media outbox rows.
        # getattr keeps compatibility with older adapters and test stores.
        claim_recovery = getattr(self.store, "claim_recovery_outbox", None)
        ack_recovery = getattr(self.store, "ack_recovery_outbox", None)
        if callable(claim_recovery) and callable(ack_recovery):
            self.limiter.before_claim()
            for item in claim_recovery(worker_id=self.worker_id, limit=1):
                try:
                    self.limiter.before_send(item.chat_id)
                    self.telegram.send_text(item.bot_id, item.chat_id, item.body)
                    if not ack_recovery(item, success=True):
                        raise RuntimeError("outbox_lease_lost")
                    sent += 1
                except Exception as exc:
                    rate_after = getattr(exc, "retry_after", None)
                    is_rate_limit = isinstance(rate_after, int) and getattr(exc, "error_code", "") == "telegram_rate_limited"
                    if is_rate_limit:
                        self.limiter.defer(rate_after)
                    provider_code = getattr(exc, "error_code", "") or str(exc)
                    error_code = "telegram_rate_limited" if is_rate_limit else (
                        "telegram_unavailable" if provider_code in {
                            "telegram_transport_error", "telegram_api_rejected",
                            "telegram_identity_invalid", "telegram_bot_mismatch",
                            "telegram_media_rejected",
                        } else "internal_error"
                    )
                    try:
                        ack_recovery(
                            item, success=False,
                            delay_seconds=rate_after if is_rate_limit else retry_delay(item.attempts, rng=self.rng),
                            error_code=error_code, max_attempts=5,
                        )
                    except Exception:
                        # A lost fencing token must not crash delivery.
                        pass
                    retried += 1
        return {"sent": sent, "retried": retried}


class SchedulerWorker:
    def __init__(self, store: SchedulerStore, broker: Broker, *, worker_id: str | None = None,
                 rng: random.Random | None = None, central_image_ready: bool = False) -> None:
        self.store, self.broker = store, broker
        self.worker_id = worker_id or f"scheduler-{uuid.uuid4().hex}"
        self.rng = rng or random.Random()
        self.central_image_ready = central_image_ready is True

    def process_once(self, *, limit: int = 4) -> dict[str, int]:
        completed = retried = busy = deferred = 0
        for work in self.store.claim_jobs(worker_id=self.worker_id, limit=limit):
            runtime_lease = self.store.acquire_runtime(work.tenant_id, holder=self.worker_id)
            if not runtime_lease:
                self.store.defer_job_capacity(work, delay_seconds=5, error_code="tenant_busy")
                busy += 1
                deferred += 1
                continue
            try:
                image_access = dict(self.store.image_access(work.tenant_id) or {})
                image_access["central_ready"] = self.central_image_ready
                result = self.broker.request({
                    "action": "run_job", "tenant_id": work.runtime_key,
                    "job_id": work.job_key, "image_access": image_access,
                })
                reply = str(result.get("reply") or "").strip()
                media = _safe_media(result.get("media"))
                if not result.get("ok") and not reply and not media:
                    error_code = _safe_error(result.get("error_code"), "cron_execution_failed")
                    if error_code in CAPACITY_ERROR_CODES:
                        self.store.defer_job_capacity(work, delay_seconds=5, error_code=error_code)
                        busy += 1
                        deferred += 1
                        continue
                    raise RuntimeError(error_code)
                next_run = None
                for job in result.get("cron_jobs") if isinstance(result.get("cron_jobs"), list) else []:
                    if isinstance(job, dict) and str(job.get("id") or "") == work.job_key and bool(job.get("enabled", True)):
                        next_run = str(job.get("next_run_at") or "") or None
                        break
                self.store.complete_job(work, next_run_at=next_run, reply=reply, media=media,
                                        result={"runtime_ok": bool(result.get("ok"))})
                completed += 1
            except Exception as exc:
                error_code = _safe_error(str(exc), type(exc).__name__.lower())
                if error_code in CAPACITY_ERROR_CODES:
                    self.store.defer_job_capacity(work, delay_seconds=5, error_code=error_code)
                    busy += 1
                    deferred += 1
                else:
                    self.store.retry_job(
                        work,
                        delay_seconds=retry_delay(work.attempts, base=30, rng=self.rng),
                        error_code=error_code,
                    )
                    retried += 1
            finally:
                self.store.release_runtime(work.tenant_id, runtime_lease)
        return {"completed": completed, "retried": retried, "busy": busy, "deferred": deferred}

    def suspend_idle_once(self, *, idle_seconds: int = 900) -> int:
        suspended = 0
        for tenant_id, runtime_key in self.store.idle_runtimes(idle_seconds=idle_seconds):
            result = self.broker.request({"action": "suspend", "tenant_id": runtime_key})
            if result.get("ok"):
                self.store.mark_suspended(tenant_id)
                suspended += 1
        return suspended


def run_loop(step: Callable[[], object], *, interval: float, stop: Callable[[], bool] = lambda: False) -> None:
    while not stop():
        step()
        time.sleep(max(0.1, interval))
