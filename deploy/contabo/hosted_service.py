#!/usr/bin/env python3
"""Concrete hosted control-plane services.

Commands are intentionally separate processes so only poller/delivery mount
the Telegram token, while only runtime/scheduler mount the broker socket/key.
Buyer traffic remains opt-in through the Compose ``buyers`` profile.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import mimetypes
import os
import re
import secrets
import signal
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from hosted_worker import OutboxItem, OutboxWorker, RuntimeUpdate, RuntimeWorker, ScheduledWork, SchedulerWorker
from runtime_broker import BrokerClient, DEFAULT_KEY_FILE, DEFAULT_SOCKET
from telegram_ingress import IncomingMedia, StagedMedia, TelegramIngress


DEFAULT_SPOOL = Path("/srv/admira-spool")
MEDIA_REF_RE = re.compile(r"^[a-f0-9]{32,64}\.(?:jpg|jpeg|png|webp|gif|mp4|mov|pdf|bin)$")
ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov", ".pdf", ".bin"}
MAX_MEDIA_BYTES = 50 * 1024 * 1024
JANITOR_INTERVAL_SECONDS = 3600
INBOUND_RETENTION_SECONDS = 7 * 86400
OUTBOUND_RETENTION_SECONDS = 14 * 86400


def _read_secret(path: str | Path) -> str:
    value = Path(path).read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError("required_secret_missing")
    return value


class Pg:
    def __init__(self) -> None:
        self.host = os.environ.get("ADMIRA_DB_HOST", "postgres")
        self.port = int(os.environ.get("ADMIRA_DB_PORT", "5432"))
        self.dbname = os.environ.get("ADMIRA_DB_NAME", "admira_control")
        self.user = os.environ["ADMIRA_DB_USER"]
        self.password_file = os.environ["ADMIRA_DB_PASSWORD_FILE"]
        self._connection = None

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        if self._connection is None or self._connection.closed:
            self._connection = psycopg.connect(
                host=self.host, port=self.port, dbname=self.dbname, user=self.user,
                password=_read_secret(self.password_file), row_factory=dict_row,
                connect_timeout=10, application_name=f"admira-{self.user}",
            )
        return self._connection

    def query(self, sql: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
        connection = self._connect()
        try:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(sql, params)
                    return list(cursor.fetchall()) if cursor.description else []
        except Exception:
            try:
                connection.rollback()
            except Exception:
                pass
            raise


class IngressStore:
    def __init__(self, db: Pg) -> None:
        self.db = db

    def resolve(self, *, bot_id: str, chat_id: str, user_id: str) -> str | None:
        rows = self.db.query("SELECT tenant_id FROM admira.resolve_telegram_chat(%s,%s,%s)", (bot_id, chat_id, user_id))
        return str(rows[0]["tenant_id"]) if rows else None

    def claim(self, *, bot_id: str, chat_id: str, user_id: str, token: str) -> str | None:
        rows = self.db.query(
            "SELECT tenant_id FROM admira.claim_telegram_tenant(%s,%s,%s,%s)",
            (bot_id, chat_id, user_id, token),
        )
        return str(rows[0]["tenant_id"]) if rows else None

    def ingest(self, *, message, tenant_id: str, payload: dict[str, object]) -> bool:
        from psycopg.types.json import Jsonb

        rows = self.db.query(
            "SELECT update_row_id, tenant_id, inserted FROM admira.ingest_telegram_update(%s,%s,%s,%s,%s)",
            (message.bot_id, message.update_id, message.chat_id, message.user_id, Jsonb(payload)),
        )
        if not rows or str(rows[0]["tenant_id"]) != tenant_id:
            raise RuntimeError("telegram_binding_changed")
        return bool(rows[0]["inserted"])

    def cursor(self, bot_id: str) -> int:
        rows = self.db.query("SELECT admira.get_telegram_ingress_cursor(%s) AS value", (bot_id,))
        return int(rows[0]["value"])

    def advance(self, bot_id: str, next_update_id: int) -> int:
        rows = self.db.query("SELECT admira.advance_telegram_ingress_cursor(%s,%s) AS value", (bot_id, next_update_id))
        return int(rows[0]["value"])


class RuntimeStore:
    def __init__(self, db: Pg) -> None:
        self.db = db

    def claim_updates(self, *, worker_id: str, limit: int):
        rows = self.db.query("SELECT * FROM admira.claim_telegram_updates(%s,%s,%s)", (worker_id, limit, 360))
        return [RuntimeUpdate(
            str(row["update_row_id"]), str(row["tenant_id"]), str(row["runtime_key"]), str(row["bot_id"]),
            int(row["update_id"]), str(row["telegram_chat_id"]), str(row["telegram_user_id"]),
            dict(row["payload"] or {}), int(row["attempt_count"]), str(row["lease_token"]),
        ) for row in rows]

    def acquire_runtime(self, tenant_id: str, *, holder: str) -> str | None:
        rows = self.db.query("SELECT * FROM admira.acquire_runtime_lease(%s,%s,%s)", (tenant_id, holder, 900))
        return str(rows[0]["lease_token"]) if rows and rows[0]["acquired"] else None

    def release_runtime(self, tenant_id: str, lease_token: str) -> None:
        self.db.query("SELECT admira.release_runtime_lease(%s,%s)", (tenant_id, lease_token))

    def sync_jobs(self, update: RuntimeUpdate, runtime_lease_token: str, jobs: list[dict[str, object]]) -> None:
        from psycopg.types.json import Jsonb

        self.db.query("SELECT admira.sync_hermes_scheduled_jobs(%s,%s,%s,%s,%s)",
                      (update.tenant_id, runtime_lease_token, update.bot_id, update.chat_id, Jsonb(jobs)))

    def complete_update(self, update: RuntimeUpdate, *, reply: str, media: list[dict[str, str]]) -> None:
        from psycopg.types.json import Jsonb

        rows = self.db.query("SELECT admira.complete_telegram_update(%s,%s,%s,%s) AS queued",
                             (update.row_id, update.lease_token, reply, Jsonb(media)))
        if not rows or int(rows[0]["queued"]) < 0:
            raise RuntimeError("update_lease_lost")

    def retry_update(self, update: RuntimeUpdate, *, delay_seconds: int, error_code: str) -> None:
        self.db.query("SELECT admira.retry_telegram_update(%s,%s,%s,%s,%s)",
                      (update.row_id, update.lease_token, error_code, delay_seconds, 5))


class DeliveryStore:
    def __init__(self, db: Pg) -> None:
        self.db = db

    def claim_outbox(self, *, worker_id: str, limit: int):
        rows = self.db.query("SELECT * FROM admira.claim_telegram_outbox(%s,%s,%s)", (worker_id, limit, 180))
        return [OutboxItem(
            str(row["outbox_id"]), str(row["tenant_id"]), str(row["bot_id"]), str(row["telegram_chat_id"]),
            str(row["kind"]), str(row["body"] or ""), str(row["media_ref"] or ""),
            str(row["media_sha256"] or ""), str(row["caption"] or ""), int(row["attempt_count"]),
            str(row["lease_token"]),
        ) for row in rows]

    def ack_outbox(self, item: OutboxItem, *, success: bool, message_id: int | None = None,
                   delay_seconds: int = 30, error_code: str = "") -> bool:
        rows = self.db.query("SELECT admira.ack_telegram_outbox(%s,%s,%s,%s,%s,%s,%s) AS acknowledged",
                             (item.row_id, item.lease_token, success, message_id, error_code or None, delay_seconds, 8))
        return bool(rows and rows[0]["acknowledged"])


class SchedulerStore:
    def __init__(self, db: Pg) -> None:
        self.db = db

    def claim_jobs(self, *, worker_id: str, limit: int):
        rows = self.db.query("SELECT * FROM admira.claim_due_scheduled_jobs(%s,%s,%s)", (worker_id, limit, 900))
        return [ScheduledWork(
            str(row["job_id"]), str(row["tenant_id"]), str(row["runtime_key"]), str(row["job_key"]),
            dict(row["payload"] or {}), row["scheduled_for"], str(row["run_id"]),
            int(row["attempt_count"]), str(row["lease_token"]),
        ) for row in rows]

    def acquire_runtime(self, tenant_id: str, *, holder: str) -> str | None:
        rows = self.db.query("SELECT * FROM admira.acquire_runtime_lease(%s,%s,%s)", (tenant_id, holder, 1200))
        return str(rows[0]["lease_token"]) if rows and rows[0]["acquired"] else None

    def release_runtime(self, tenant_id: str, lease_token: str) -> None:
        self.db.query("SELECT admira.release_runtime_lease(%s,%s)", (tenant_id, lease_token))

    def complete_job(self, work: ScheduledWork, *, next_run_at: str | None, reply: str,
                     media: list[dict[str, str]], result: dict[str, object]) -> None:
        from psycopg.types.json import Jsonb

        rows = self.db.query("SELECT admira.complete_scheduled_job_run(%s,%s,%s,%s,%s,%s,%s) AS queued", (
            work.job_id, work.run_id, work.lease_token, next_run_at, reply, Jsonb(media), Jsonb(result),
        ))
        if not rows or int(rows[0]["queued"]) < 0:
            raise RuntimeError("scheduled_lease_lost")

    def retry_job(self, work: ScheduledWork, *, delay_seconds: int, error_code: str) -> None:
        self.db.query("SELECT admira.retry_scheduled_job_run(%s,%s,%s,%s,%s,%s)",
                      (work.job_id, work.run_id, work.lease_token, error_code, delay_seconds, 5))

    def idle_runtimes(self, *, idle_seconds: int):
        rows = self.db.query("SELECT * FROM admira.list_idle_runtime_keys(%s)", (idle_seconds,))
        return [(str(row["tenant_id"]), str(row["runtime_key"])) for row in rows]

    def mark_suspended(self, tenant_id: str) -> None:
        self.db.query("SELECT admira.mark_runtime_suspended(%s)", (tenant_id,))


class TelegramError(RuntimeError):
    pass


class TelegramAPI:
    def __init__(self, token_file: str | Path) -> None:
        self.token = _read_secret(token_file)
        self._bot_id = ""

    def _request(self, method: str, payload: dict[str, object] | None = None, *, timeout: int = 45):
        data = urllib.parse.urlencode(payload or {}).encode("utf-8")
        request = urllib.request.Request(f"https://api.telegram.org/bot{self.token}/{method}", data=data, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise TelegramError("telegram_transport_error") from exc
        if not isinstance(body, dict) or not body.get("ok"):
            raise TelegramError("telegram_api_rejected")
        return body.get("result")

    def bot_id(self) -> str:
        if not self._bot_id:
            result = self._request("getMe", timeout=15)
            self._bot_id = str((result or {}).get("id") or "")
            if not re.fullmatch(r"[0-9]{1,32}", self._bot_id):
                raise TelegramError("telegram_identity_invalid")
        return self._bot_id

    def get_updates(self, *, offset: int, timeout: int = 25) -> list[dict[str, object]]:
        result = self._request("getUpdates", {
            "offset": offset, "timeout": timeout, "limit": 100,
            "allowed_updates": json.dumps(["message"]),
        }, timeout=timeout + 10)
        return [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []

    def file_info(self, file_id: str) -> dict[str, object]:
        result = self._request("getFile", {"file_id": file_id}, timeout=20)
        if not isinstance(result, dict):
            raise TelegramError("telegram_file_missing")
        return result

    def download(self, remote_path: str, target: Path) -> tuple[int, str]:
        if not remote_path or ".." in Path(remote_path).parts or remote_path.startswith("/"):
            raise TelegramError("telegram_file_path_invalid")
        request = urllib.request.Request(f"https://api.telegram.org/file/bot{self.token}/{remote_path}")
        digest, total = hashlib.sha256(), 0
        try:
            with urllib.request.urlopen(request, timeout=60) as response, target.open("xb") as writer:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_MEDIA_BYTES:
                        raise TelegramError("telegram_file_too_large")
                    digest.update(chunk)
                    writer.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return total, digest.hexdigest()

    def send_message(self, chat_id: str, text: str) -> int:
        result = self._request("sendMessage", {"chat_id": chat_id, "text": text}, timeout=45)
        return int((result or {}).get("message_id") or 0)

    def send_file(self, chat_id: str, kind: str, path: Path, caption: str = "") -> int:
        field = {"photo": "photo", "video": "video", "document": "document"}[kind]
        method = {"photo": "sendPhoto", "video": "sendVideo", "document": "sendDocument"}[kind]
        boundary = "----admira-" + secrets.token_hex(16)
        prefix = bytearray()
        for key, value in {"chat_id": chat_id, "caption": caption}.items():
            if not value:
                continue
            prefix.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode())
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        prefix.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{path.name}\"\r\nContent-Type: {mime}\r\n\r\n".encode())
        suffix = f"\r\n--{boundary}--\r\n".encode()
        connection = http.client.HTTPSConnection("api.telegram.org", timeout=120)
        try:
            connection.putrequest("POST", f"/bot{self.token}/{method}")
            connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
            connection.putheader("Content-Length", str(len(prefix) + path.stat().st_size + len(suffix)))
            connection.endheaders()
            connection.send(prefix)
            with path.open("rb") as reader:
                while chunk := reader.read(1024 * 1024):
                    connection.send(chunk)
            connection.send(suffix)
            response = connection.getresponse()
            result = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise TelegramError("telegram_media_delivery_failed") from exc
        finally:
            connection.close()
        if not result.get("ok"):
            raise TelegramError("telegram_media_rejected")
        return int((result.get("result") or {}).get("message_id") or 0)


def _media_suffix(media: IncomingMedia, remote_path: str) -> str:
    for value in (media.file_name, remote_path):
        suffix = Path(value).suffix.lower()
        if suffix in ALLOWED_SUFFIXES:
            return suffix
    guessed = mimetypes.guess_extension(media.mime_type or "") or ".bin"
    return guessed if guessed in ALLOWED_SUFFIXES else ".bin"


class TelegramMediaStager:
    def __init__(self, api: TelegramAPI, spool: Path) -> None:
        self.api, self.root = api, spool / "inbound"
        self.root.mkdir(parents=True, exist_ok=True)

    def stage(self, media: IncomingMedia) -> StagedMedia:
        info = self.api.file_info(media.file_id)
        remote = str(info.get("file_path") or "")
        ref = secrets.token_hex(24) + _media_suffix(media, remote)
        temporary, destination = self.root / f".{ref}.tmp", self.root / ref
        size, digest = self.api.download(remote, temporary)
        temporary.chmod(0o660)
        os.replace(temporary, destination)
        return StagedMedia(media.kind, ref, media.file_name, media.mime_type, size, digest)


class TelegramTransport:
    def __init__(self, api: TelegramAPI, spool: Path) -> None:
        self.api, self.root = api, spool / "outbound"
        self.root.mkdir(parents=True, exist_ok=True)

    def _check_bot(self, bot_id: str) -> None:
        if str(bot_id) != self.api.bot_id():
            raise TelegramError("telegram_bot_mismatch")

    def send_text(self, bot_id: str, chat_id: str, text: str) -> int:
        self._check_bot(bot_id)
        return self.api.send_message(chat_id, text)

    def send_media(self, bot_id: str, chat_id: str, kind: str, media_ref: str,
                   caption: str = "", sha256: str = "") -> int:
        self._check_bot(bot_id)
        if not MEDIA_REF_RE.fullmatch(media_ref):
            raise TelegramError("invalid_media_ref")
        path = self.root / media_ref
        resolved = path.resolve(strict=True)
        if resolved.parent != self.root.resolve() or path.is_symlink() or not stat.S_ISREG(resolved.lstat().st_mode):
            raise TelegramError("invalid_media_file")
        if sha256:
            digest = hashlib.sha256()
            with resolved.open("rb") as reader:
                while chunk := reader.read(1024 * 1024):
                    digest.update(chunk)
            if not secrets.compare_digest(digest.hexdigest(), sha256):
                raise TelegramError("media_integrity_failed")
        return self.api.send_file(chat_id, kind, resolved, caption)

    def cleanup_media(self, media_ref: str) -> None:
        if MEDIA_REF_RE.fullmatch(media_ref):
            (self.root / media_ref).unlink(missing_ok=True)


def _stop_event() -> threading.Event:
    event = threading.Event()
    for value in (signal.SIGTERM, signal.SIGINT):
        signal.signal(value, lambda *_args: event.set())
    return event


def clean_spool(directory: Path, *, retention_seconds: int, now: float | None = None, limit: int = 1000) -> int:
    """Remove only stale opaque regular files from one isolated spool."""
    cutoff = (time.time() if now is None else now) - max(3600, retention_seconds)
    removed = 0
    try:
        entries = list(directory.iterdir())
    except FileNotFoundError:
        return 0
    for path in entries:
        if removed >= max(1, min(limit, 10_000)):
            break
        try:
            details = path.lstat()
            name = path.name.removeprefix(".").removesuffix(".tmp")
            valid_name = bool(MEDIA_REF_RE.fullmatch(name))
            temporary = path.name.startswith(".") and path.name.endswith(".tmp")
            file_cutoff = (time.time() if now is None else now) - 3600 if temporary else cutoff
            if valid_name and stat.S_ISREG(details.st_mode) and not path.is_symlink() and details.st_mtime < file_cutoff:
                path.unlink()
                removed += 1
        except (FileNotFoundError, OSError):
            continue
    return removed


def run_poller(*, once: bool = False) -> None:
    spool = Path(os.environ.get("ADMIRA_SPOOL_ROOT", DEFAULT_SPOOL))
    api, store = TelegramAPI(os.environ["TELEGRAM_BOT_TOKEN_FILE"]), IngressStore(Pg())
    bot_id = api.bot_id()
    ingress = TelegramIngress(store, store, TelegramMediaStager(api, spool))
    stop = _stop_event()
    last_janitor = 0.0
    while not stop.is_set():
        if time.monotonic() - last_janitor >= JANITOR_INTERVAL_SECONDS:
            clean_spool(spool / "inbound", retention_seconds=INBOUND_RETENTION_SECONDS)
            last_janitor = time.monotonic()
        cursor = store.cursor(bot_id)
        updates = api.get_updates(offset=cursor, timeout=1 if once else 25)
        for raw in sorted(updates, key=lambda item: int(item.get("update_id", 0))):
            update_id = int(raw.get("update_id", -1))
            try:
                result = ingress.handle_update(raw, bot_id=bot_id)
            except ValueError:
                result = {"status": "invalid"}
            if result.get("status") == "failed":
                break
            store.advance(bot_id, update_id + 1)
        if once:
            return


def _broker() -> BrokerClient:
    return BrokerClient(Path(os.environ.get("ADMIRA_BROKER_SOCKET", DEFAULT_SOCKET)),
                        Path(os.environ.get("ADMIRA_BROKER_KEY_FILE", DEFAULT_KEY_FILE)))


def run_runtime(*, once: bool = False) -> None:
    worker, stop = RuntimeWorker(RuntimeStore(Pg()), _broker()), _stop_event()
    while not stop.is_set():
        result = worker.process_once()
        if once:
            return
        stop.wait(0.2 if any(result.values()) else 1.0)


def run_delivery(*, once: bool = False) -> None:
    spool = Path(os.environ.get("ADMIRA_SPOOL_ROOT", DEFAULT_SPOOL))
    api = TelegramAPI(os.environ["TELEGRAM_BOT_TOKEN_FILE"])
    worker = OutboxWorker(DeliveryStore(Pg()), TelegramTransport(api, spool))
    stop = _stop_event()
    last_janitor = 0.0
    while not stop.is_set():
        if time.monotonic() - last_janitor >= JANITOR_INTERVAL_SECONDS:
            clean_spool(spool / "outbound", retention_seconds=OUTBOUND_RETENTION_SECONDS)
            last_janitor = time.monotonic()
        result = worker.process_once()
        if once:
            return
        stop.wait(0.2 if any(result.values()) else 1.0)


def run_scheduler(*, once: bool = False) -> None:
    worker, stop = SchedulerWorker(SchedulerStore(Pg()), _broker()), _stop_event()
    last_idle = 0.0
    while not stop.is_set():
        result = worker.process_once()
        if time.monotonic() - last_idle >= 60:
            worker.suspend_idle_once(idle_seconds=int(os.environ.get("ADMIRA_RUNTIME_IDLE_SECONDS", "900")))
            last_idle = time.monotonic()
        if once:
            return
        stop.wait(0.5 if any(result.values()) else 2.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Admira hosted control-plane service")
    parser.add_argument("command", choices=("poller", "runtime", "delivery", "scheduler"))
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    {"poller": run_poller, "runtime": run_runtime, "delivery": run_delivery, "scheduler": run_scheduler}[args.command](once=args.once)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
