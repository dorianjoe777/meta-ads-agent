#!/usr/bin/env python3
"""Injectable workers for hosted Telegram turns, delivery, and cron jobs."""

from __future__ import annotations

import random
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol, Sequence


MEDIA_REF_RE = re.compile(r"^[a-f0-9]{32,64}\.(?:jpg|jpeg|png|webp|gif|mp4|mov|pdf|bin)$")


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
    def acquire_runtime(self, tenant_id: str, *, holder: str) -> str | None: ...
    def release_runtime(self, tenant_id: str, lease_token: str) -> None: ...
    def sync_jobs(self, update: RuntimeUpdate, runtime_lease_token: str, jobs: list[dict[str, object]]) -> None: ...
    def complete_update(self, update: RuntimeUpdate, *, reply: str, media: list[dict[str, str]]) -> None: ...
    def retry_update(self, update: RuntimeUpdate, *, delay_seconds: int, error_code: str) -> None: ...


class DeliveryStore(Protocol):
    def claim_outbox(self, *, worker_id: str, limit: int) -> Sequence[OutboxItem]: ...
    def ack_outbox(self, item: OutboxItem, *, success: bool, message_id: int | None = None,
                   delay_seconds: int = 30, error_code: str = "") -> bool: ...


class SchedulerStore(Protocol):
    def claim_jobs(self, *, worker_id: str, limit: int) -> Sequence[ScheduledWork]: ...
    def acquire_runtime(self, tenant_id: str, *, holder: str) -> str | None: ...
    def release_runtime(self, tenant_id: str, lease_token: str) -> None: ...
    def complete_job(self, work: ScheduledWork, *, next_run_at: str | None,
                     reply: str, media: list[dict[str, str]], result: dict[str, object]) -> None: ...
    def retry_job(self, work: ScheduledWork, *, delay_seconds: int, error_code: str) -> None: ...
    def idle_runtimes(self, *, idle_seconds: int) -> Sequence[tuple[str, str]]: ...
    def mark_suspended(self, tenant_id: str) -> None: ...


class Broker(Protocol):
    def request(self, body: dict[str, object]) -> dict[str, object]: ...


class TelegramTransport(Protocol):
    def send_text(self, bot_id: str, chat_id: str, text: str) -> int: ...
    def send_media(self, bot_id: str, chat_id: str, kind: str, media_ref: str, caption: str = "", sha256: str = "") -> int: ...
    def cleanup_media(self, media_ref: str) -> None: ...


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
                 rng: random.Random | None = None) -> None:
        self.store, self.broker = store, broker
        self.worker_id = worker_id or f"runtime-{uuid.uuid4().hex}"
        self.rng = rng or random.Random()

    def process_once(self, *, limit: int = 4) -> dict[str, int]:
        completed = retried = busy = 0
        for update in self.store.claim_updates(worker_id=self.worker_id, limit=limit):
            runtime_lease = self.store.acquire_runtime(update.tenant_id, holder=self.worker_id)
            if not runtime_lease:
                self.store.retry_update(update, delay_seconds=1, error_code="tenant_busy")
                busy += 1
                continue
            try:
                message = str(update.payload.get("message") or "").strip()
                if not message:
                    message = "El comprador adjuntó un archivo. Analízalo y responde según el contexto."
                result = self.broker.request({
                    "action": "turn",
                    "tenant_id": update.runtime_key,
                    "turn": {
                        "message": message,
                        "language": str(update.payload.get("language") or "es"),
                        "chat_id": update.chat_id,
                        "update_id": update.update_id,
                    },
                    "media": list(update.payload.get("media") or []),
                })
                reply = str(result.get("reply") or "").strip()
                media = _safe_media(result.get("media"))
                if not result.get("ok") and not reply and not media:
                    raise RuntimeError(_safe_error(result.get("error_code"), "runtime_failure"))
                jobs = result.get("cron_jobs") if isinstance(result.get("cron_jobs"), list) else []
                self.store.sync_jobs(update, runtime_lease, jobs)
                self.store.complete_update(update, reply=reply, media=media)
                completed += 1
            except Exception as exc:
                delay = retry_delay(update.attempts, rng=self.rng)
                self.store.retry_update(update, delay_seconds=delay,
                                        error_code=_safe_error(str(exc), type(exc).__name__.lower()))
                retried += 1
            finally:
                self.store.release_runtime(update.tenant_id, runtime_lease)
        return {"completed": completed, "retried": retried, "busy": busy}


class OutboxWorker:
    def __init__(self, store: DeliveryStore, telegram: TelegramTransport, *, worker_id: str | None = None,
                 rng: random.Random | None = None) -> None:
        self.store, self.telegram = store, telegram
        self.worker_id = worker_id or f"delivery-{uuid.uuid4().hex}"
        self.rng = rng or random.Random()

    def process_once(self, *, limit: int = 20) -> dict[str, int]:
        sent = retried = 0
        for item in self.store.claim_outbox(worker_id=self.worker_id, limit=limit):
            try:
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
                try:
                    self.store.ack_outbox(
                        item, success=False, delay_seconds=retry_delay(item.attempts, rng=self.rng),
                        error_code=_safe_error(str(exc), type(exc).__name__.lower()),
                    )
                except Exception:
                    # A lost fencing token must not crash delivery or delete
                    # the media; the durable lease owner decides the retry.
                    pass
                retried += 1
        return {"sent": sent, "retried": retried}


class SchedulerWorker:
    def __init__(self, store: SchedulerStore, broker: Broker, *, worker_id: str | None = None,
                 rng: random.Random | None = None) -> None:
        self.store, self.broker = store, broker
        self.worker_id = worker_id or f"scheduler-{uuid.uuid4().hex}"
        self.rng = rng or random.Random()

    def process_once(self, *, limit: int = 4) -> dict[str, int]:
        completed = retried = busy = 0
        for work in self.store.claim_jobs(worker_id=self.worker_id, limit=limit):
            runtime_lease = self.store.acquire_runtime(work.tenant_id, holder=self.worker_id)
            if not runtime_lease:
                self.store.retry_job(work, delay_seconds=1, error_code="tenant_busy")
                busy += 1
                continue
            try:
                result = self.broker.request({"action": "run_job", "tenant_id": work.runtime_key, "job_id": work.job_key})
                reply = str(result.get("reply") or "").strip()
                media = _safe_media(result.get("media"))
                if not result.get("ok") and not reply and not media:
                    raise RuntimeError(_safe_error(result.get("error_code"), "cron_execution_failed"))
                next_run = None
                for job in result.get("cron_jobs") if isinstance(result.get("cron_jobs"), list) else []:
                    if isinstance(job, dict) and str(job.get("id") or "") == work.job_key and bool(job.get("enabled", True)):
                        next_run = str(job.get("next_run_at") or "") or None
                        break
                self.store.complete_job(work, next_run_at=next_run, reply=reply, media=media,
                                        result={"runtime_ok": bool(result.get("ok"))})
                completed += 1
            except Exception as exc:
                self.store.retry_job(work, delay_seconds=retry_delay(work.attempts, base=30, rng=self.rng),
                                     error_code=_safe_error(str(exc), type(exc).__name__.lower()))
                retried += 1
            finally:
                self.store.release_runtime(work.tenant_id, runtime_lease)
        return {"completed": completed, "retried": retried, "busy": busy}

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
