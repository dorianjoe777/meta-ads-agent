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
from typing import Any, Callable

from hosted_worker import (
    OutboxItem, OutboxWorker, RecoveryOutboxItem, RuntimeUpdate, RuntimeWorker,
    ScheduledWork, SchedulerWorker, TelegramTypingHeartbeat,
)
from recovery_email_worker import RecoveryEmailItem, RecoveryEmailWorker
from recovery_identity import read_private_hmac_key
from recovery_service import RecoveryEnvelopeCipher, TelegramRecoveryService, read_private_envelope_key
from recovery_smtp import SMTPRecoveryEmailTransport
from runtime_broker import BrokerClient, DEFAULT_KEY_FILE, DEFAULT_SOCKET
from telegram_ingress import IncomingMedia, StagedMedia, TelegramIngress


DEFAULT_SPOOL = Path("/srv/admira-spool")
MEDIA_REF_RE = re.compile(r"^[a-f0-9]{32,64}\.(?:jpg|jpeg|png|webp|gif|mp4|mov|pdf|bin)$")
ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov", ".pdf", ".bin"}
MAX_MEDIA_BYTES = 50 * 1024 * 1024
JANITOR_INTERVAL_SECONDS = 3600
INBOUND_RETENTION_SECONDS = 7 * 86400
OUTBOUND_RETENTION_SECONDS = 14 * 86400
MAX_TELEGRAM_RETRY_AFTER_SECONDS = 900
_TELEGRAM_MARKDOWN_V2_SPECIALS = frozenset("\\_*[]()~`>#+-=|{}.!")
_TELEGRAM_BOLD_RE = re.compile(r"(?<!\*)\*\*(.+?)(?<!\*)\*\*(?!\*)", re.DOTALL)
_TELEGRAM_ESCAPED_BOLD_RE = re.compile(r"\\\*\\\*(.+?)\\\*\\\*", re.DOTALL)


def _read_secret(path: str | Path) -> str:
    value = Path(path).read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError("required_secret_missing")
    return value


class Pg:
    def __init__(self, *, user: str | None = None,
                 password_file: str | Path | None = None) -> None:
        self.host = os.environ.get("ADMIRA_DB_HOST", "postgres")
        self.port = int(os.environ.get("ADMIRA_DB_PORT", "5432"))
        self.dbname = os.environ.get("ADMIRA_DB_NAME", "admira_control")
        self.user = user or os.environ["ADMIRA_DB_USER"]
        self.password_file = str(password_file or os.environ["ADMIRA_DB_PASSWORD_FILE"])
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

    def close(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is not None and not connection.closed:
            connection.close()


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

    def telegram_update_pending(self, *, bot_id: str, update_id: int) -> bool:
        rows = self.db.query(
            "SELECT admira.telegram_update_pending(%s,%s) AS pending",
            (bot_id, update_id),
        )
        return bool(rows and rows[0]["pending"])


class RecoveryStore:
    """Function-only adapter for the separately credentialed recovery role."""

    def __init__(self, db: Pg) -> None:
        self.db = db

    def begin_telegram_recovery(
        self, request_id, bot_id: str, chat_id: str, user_id: str,
        email_hmac_hex: str, license_hmac_hex: str, otp_hash_hex: str,
        otp_ciphertext: bytes, delivery_key_version: str,
    ) -> dict[str, object]:
        rows = self.db.query(
            "SELECT * FROM admira.begin_telegram_recovery(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (request_id, bot_id, chat_id, user_id, email_hmac_hex,
             license_hmac_hex, otp_hash_hex, otp_ciphertext,
             delivery_key_version),
        )
        return dict(rows[0]) if rows else {"public_outcome": "recovery_pending"}

    def confirm_telegram_recovery(
        self, request_id, bot_id: str, chat_id: str, user_id: str,
        otp_hash_hex: str,
    ) -> dict[str, object]:
        rows = self.db.query(
            "SELECT * FROM admira.confirm_telegram_recovery(%s,%s,%s,%s,%s)",
            (request_id, bot_id, chat_id, user_id, otp_hash_hex),
        )
        return dict(rows[0]) if rows else {
            "completed": False, "public_outcome": "recovery_failed",
        }

    def enqueue_public_reply(
        self, request_id, bot_id: str, chat_id: str, user_id: str,
        template_code: str,
    ) -> dict[str, object]:
        rows = self.db.query(
            "SELECT admira.enqueue_telegram_recovery_public_reply(%s,%s,%s,%s,%s) AS public_outcome",
            (request_id, bot_id, chat_id, user_id, template_code),
        )
        return dict(rows[0]) if rows else {"public_outcome": template_code}


class RuntimeStore:
    def __init__(self, db: Pg) -> None:
        self.db = db

    def claim_updates(self, *, worker_id: str, limit: int):
        # Expiry is enforced immediately before the active-tenant claim.  The
        # database function is idempotent, so every runtime replica may call
        # it without racing or extending a trial.
        self.db.query("SELECT admira.expire_due_trials()")
        rows = self.db.query("SELECT * FROM admira.claim_telegram_updates(%s,%s,%s)", (worker_id, limit, 360))
        return [RuntimeUpdate(
            str(row["update_row_id"]), str(row["tenant_id"]), str(row["runtime_key"]), str(row["bot_id"]),
            int(row["update_id"]), str(row["telegram_chat_id"]), str(row["telegram_user_id"]),
            dict(row["payload"] or {}), int(row["attempt_count"]), str(row["lease_token"]),
        ) for row in rows]

    def image_access(self, tenant_id: str) -> dict[str, object]:
        rows = self.db.query("SELECT * FROM admira.resolve_tenant_image_access(%s)", (tenant_id,))
        if not rows:
            return {"lifecycle_state": "suspended", "route": "blocked", "image_sponsorship_ends_at": ""}
        row = rows[0]
        ends_at = row.get("image_sponsorship_ends_at")
        if hasattr(ends_at, "isoformat"):
            ends_at = ends_at.isoformat()
        return {
            "lifecycle_state": str(row.get("lifecycle_state") or "suspended"),
            "route": str(row.get("route") or row.get("image_route") or "blocked"),
            "image_sponsorship_ends_at": str(ends_at or ""),
        }

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

    def defer_update_capacity(self, update: RuntimeUpdate, *, delay_seconds: int, error_code: str) -> None:
        self.db.query("SELECT admira.defer_telegram_update_capacity(%s,%s,%s,%s)",
                      (update.row_id, update.lease_token, error_code, delay_seconds))

    def claim_idle_runtime(self, *, worker_id: str, idle_seconds: int, claim_seconds: int):
        rows = self.db.query(
            "SELECT * FROM admira.claim_idle_runtime(%s,%s,%s)",
            (worker_id, idle_seconds, claim_seconds),
        )
        return [
            (str(row["tenant_id"]), str(row["runtime_key"]), str(row["eviction_token"]))
            for row in rows
        ]

    def complete_idle_runtime(self, tenant_id: str, eviction_token: str) -> bool:
        rows = self.db.query(
            "SELECT admira.complete_idle_runtime(%s,%s) AS completed",
            (tenant_id, eviction_token),
        )
        return bool(rows and rows[0]["completed"])

    def release_idle_runtime_claim(self, tenant_id: str, eviction_token: str) -> bool:
        rows = self.db.query(
            "SELECT admira.release_idle_runtime_claim(%s,%s) AS released",
            (tenant_id, eviction_token),
        )
        return bool(rows and rows[0]["released"])


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
                   delay_seconds: int = 30, error_code: str = "", max_attempts: int = 8) -> bool:
        rows = self.db.query("SELECT admira.ack_telegram_outbox(%s,%s,%s,%s,%s,%s,%s) AS acknowledged",
                             (item.row_id, item.lease_token, success, message_id, error_code or None, delay_seconds, max_attempts))
        return bool(rows and rows[0]["acknowledged"])

    def claim_recovery_outbox(self, *, worker_id: str, limit: int):
        rows = self.db.query(
            "SELECT * FROM admira.claim_recovery_chat_outbox(%s,%s,%s)",
            (worker_id, limit, 120),
        )
        return [RecoveryOutboxItem(
            str(row["outbox_id"]), str(row["request_id"]), str(row["bot_id"]),
            str(row["chat_id"]), str(row["user_id"]), str(row["template_code"]),
            str(row["body"] or ""), int(row["attempt_count"]), str(row["lease_token"]),
        ) for row in rows]

    def ack_recovery_outbox(self, item: RecoveryOutboxItem, *, success: bool,
                            delay_seconds: int = 30, error_code: str = "",
                            max_attempts: int = 5) -> bool:
        rows = self.db.query(
            "SELECT admira.ack_recovery_chat_outbox(%s,%s,%s,%s,%s,%s) AS acknowledged",
            (item.row_id, item.lease_token, success, error_code or None,
             delay_seconds, max_attempts),
        )
        return bool(rows and rows[0]["acknowledged"])


class RecoveryEmailStore:
    """Function-only adapter; it cannot select recovery tables directly."""

    def __init__(self, db: Pg) -> None:
        self.db = db

    def claim_recovery_email_outbox(self, *, worker_id: str, limit: int):
        rows = self.db.query(
            "SELECT * FROM admira.claim_recovery_email_outbox(%s,%s,%s)",
            (worker_id, limit, 120),
        )
        return [RecoveryEmailItem(
            str(row["outbox_id"]), str(row["challenge_id"]),
            str(row["request_id"]), str(row["delivery_ref"]),
            str(row["template_code"]), bytes(row["encrypted_payload"]),
            str(row["delivery_key_version"]), int(row["attempt_count"]),
            str(row["lease_token"]),
        ) for row in rows]

    def ack_recovery_email_outbox(
        self, item: RecoveryEmailItem, *, success: bool, error_code: str = "",
        retry_after_seconds: int = 60, max_attempts: int = 5,
    ) -> bool:
        rows = self.db.query(
            "SELECT admira.ack_recovery_email_outbox(%s,%s,%s,%s,%s,%s) AS acknowledged",
            (item.outbox, item.lease, success, error_code or None,
             retry_after_seconds, max_attempts),
        )
        return bool(rows and rows[0]["acknowledged"])

class SchedulerStore:
    def __init__(self, db: Pg) -> None:
        self.db = db

    def maintain_trial_lifecycle(self, broker, *, worker_id: str) -> dict[str, int]:
        """Run the durable grace lifecycle around the host boundary.

        PostgreSQL decides which tenants are eligible.  The broker owns the
        tenant Docker workspace, so a grace account is only deleted from the
        database after its validated host workspace has been stopped/removed.
        """
        self.db.query("SELECT admira.expire_due_trials()")
        queued_rows = self.db.query("SELECT admira.enqueue_due_trial_grace_reminders() AS queued")
        queued = int(queued_rows[0]["queued"]) if queued_rows else 0
        suspended = deleted = 0
        for row in self.db.query("SELECT * FROM admira.grace_runtime_candidates()"):
            try:
                result = broker.request({"action": "suspend", "tenant_id": str(row["runtime_key"])})
            except Exception:
                continue
            if isinstance(result, dict) and result.get("ok"):
                marked = self.db.query(
                    "SELECT admira.mark_grace_runtime_suspended(%s) AS marked",
                    (row["tenant_id"],),
                )
                if marked and marked[0].get("marked"):
                    suspended += 1
        deletion_rows = self.db.query(
            "SELECT * FROM admira.claim_grace_deletion_candidates(%s,%s,%s)",
            (worker_id, 25, 900),
        )
        for row in deletion_rows:
            claim_id = row["deletion_claim_id"]
            if not bool(row.get("workspace_purged")):
                try:
                    result = broker.request({"action": "purge", "tenant_id": str(row["runtime_key"])})
                except Exception:
                    continue
                if not isinstance(result, dict) or not result.get("ok"):
                    continue
                marked = self.db.query(
                    "SELECT admira.mark_grace_workspace_purged(%s,%s) AS marked",
                    (row["tenant_id"], claim_id),
                )
                if not marked or not marked[0].get("marked"):
                    continue
            removed = self.db.query(
                "SELECT admira.delete_grace_tenant(%s,%s) AS deleted",
                (row["tenant_id"], claim_id),
            )
            if removed and removed[0].get("deleted"):
                deleted += 1
        return {"reminders_queued": queued, "runtimes_suspended": suspended,
                "tenants_deleted": deleted}

    def claim_jobs(self, *, worker_id: str, limit: int):
        # Scheduled work must obey the same five-day boundary as Telegram
        # turns; expired trials are suspended before any job is leased.
        self.db.query("SELECT admira.expire_due_trials()")
        rows = self.db.query("SELECT * FROM admira.claim_due_scheduled_jobs(%s,%s,%s)", (worker_id, limit, 900))
        return [ScheduledWork(
            str(row["job_id"]), str(row["tenant_id"]), str(row["runtime_key"]), str(row["job_key"]),
            dict(row["payload"] or {}), row["scheduled_for"], str(row["run_id"]),
            int(row["attempt_count"]), str(row["lease_token"]),
        ) for row in rows]

    def image_access(self, tenant_id: str) -> dict[str, object]:
        rows = self.db.query("SELECT * FROM admira.resolve_tenant_image_access(%s)", (tenant_id,))
        if not rows:
            return {"lifecycle_state": "suspended", "route": "blocked", "image_sponsorship_ends_at": ""}
        row = rows[0]
        ends_at = row.get("image_sponsorship_ends_at")
        if hasattr(ends_at, "isoformat"):
            ends_at = ends_at.isoformat()
        return {
            "lifecycle_state": str(row.get("lifecycle_state") or "suspended"),
            "route": str(row.get("route") or row.get("image_route") or "blocked"),
            "image_sponsorship_ends_at": str(ends_at or ""),
        }

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

    def defer_job_capacity(self, work: ScheduledWork, *, delay_seconds: int, error_code: str) -> None:
        self.db.query(
            "SELECT admira.defer_scheduled_job_capacity(%s,%s,%s,%s,%s)",
            (work.job_id, work.run_id, work.lease_token, error_code, delay_seconds),
        )

    def idle_runtimes(self, *, idle_seconds: int):
        rows = self.db.query("SELECT * FROM admira.list_idle_runtime_keys(%s)", (idle_seconds,))
        return [(str(row["tenant_id"]), str(row["runtime_key"])) for row in rows]

    def mark_suspended(self, tenant_id: str) -> None:
        self.db.query("SELECT admira.mark_runtime_suspended(%s)", (tenant_id,))


class TelegramError(RuntimeError):
    pass


class TelegramRateLimit(TelegramError):
    """A Telegram 429 with a bounded, machine-readable retry delay."""

    error_code = "telegram_rate_limited"

    def __init__(self, retry_after: object = 1) -> None:
        try:
            value = int(retry_after)
        except (TypeError, ValueError):
            value = 1
        self.retry_after = max(1, min(MAX_TELEGRAM_RETRY_AFTER_SECONDS, value))
        super().__init__(self.error_code)


def _telegram_rate_limit(body: object, *, status: int | None = None) -> TelegramRateLimit | None:
    if status == 429 or (isinstance(body, dict) and body.get("error_code") == 429):
        parameters = body.get("parameters") if isinstance(body, dict) else {}
        retry_after = parameters.get("retry_after", 1) if isinstance(parameters, dict) else 1
        return TelegramRateLimit(retry_after)
    return None


def _telegram_markdown_v2(text: str) -> str:
    """Escape text for MarkdownV2 while translating the supported bold form."""
    # Hermes/model responses sometimes contain Markdown delimiters already
    # escaped as ``\*\*bold\*\*``.  Treat that representation as the same
    # supported bold form before escaping the rest for Telegram; otherwise the
    # backslashes are escaped a second time and Telegram displays them.
    text = _TELEGRAM_ESCAPED_BOLD_RE.sub(
        lambda match: "**" + match.group(1) + "**", text,
    )

    def escape(value: str) -> str:
        return "".join(f"\\{char}" if char in _TELEGRAM_MARKDOWN_V2_SPECIALS else char for char in value)

    parts: list[str] = []
    position = 0
    for match in _TELEGRAM_BOLD_RE.finditer(text):
        parts.append(escape(text[position:match.start()]))
        parts.append("*" + escape(match.group(1)) + "*")
        position = match.end()
    parts.append(escape(text[position:]))
    return "".join(parts)


def _telegram_plain_text(text: str) -> str:
    """Keep a readable fallback if Telegram rejects a formatted payload."""
    text = _TELEGRAM_ESCAPED_BOLD_RE.sub(
        lambda match: "**" + match.group(1) + "**", text,
    )
    return _TELEGRAM_BOLD_RE.sub(lambda match: match.group(1), text).replace("**", "")


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
        except urllib.error.HTTPError as exc:
            body: object = {}
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except (OSError, UnicodeDecodeError, ValueError):
                pass
            finally:
                exc.close()
            rate_limit = _telegram_rate_limit(body, status=exc.code)
            if rate_limit is not None:
                raise rate_limit from exc
            if exc.code == 400:
                raise TelegramError("telegram_api_rejected") from exc
            raise TelegramError("telegram_transport_error") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise TelegramError("telegram_transport_error") from exc
        if not isinstance(body, dict) or not body.get("ok"):
            rate_limit = _telegram_rate_limit(body)
            if rate_limit is not None:
                raise rate_limit
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
        payload = {
            "chat_id": chat_id,
            "text": _telegram_markdown_v2(text),
            "parse_mode": "MarkdownV2",
        }
        try:
            result = self._request("sendMessage", payload, timeout=45)
        except TelegramError as exc:
            # A malformed/unsupported Telegram entity should not strand the
            # outbox item. Keep rate limits and transport errors retryable.
            if str(exc) != "telegram_api_rejected":
                raise
            result = self._request(
                "sendMessage", {"chat_id": chat_id, "text": _telegram_plain_text(text)}, timeout=45,
            )
        return int((result or {}).get("message_id") or 0)

    def send_chat_action(self, chat_id: str, action: str = "typing") -> None:
        self._request("sendChatAction", {"chat_id": chat_id, "action": action}, timeout=8)

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
        response_status: int | None = None
        result: object = None
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
            response_status = response.status
            raw_body = response.read()
        except Exception as exc:
            raise TelegramError("telegram_media_delivery_failed") from exc
        finally:
            connection.close()
        try:
            result = json.loads(raw_body.decode("utf-8"))
        except (AttributeError, UnicodeDecodeError, ValueError):
            result = None
        rate_limit = _telegram_rate_limit(result, status=response_status)
        if rate_limit is not None:
            raise rate_limit
        if not isinstance(result, dict) or not result.get("ok"):
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

    def send_chat_action(self, bot_id: str, chat_id: str, action: str = "typing") -> None:
        self._check_bot(bot_id)
        self.api.send_chat_action(chat_id, action)

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


class TelegramTypingTransport:
    """Poller-only adapter that cannot send messages or access media."""

    def __init__(self, api: TelegramAPI) -> None:
        self.api = api

    def send_chat_action(self, bot_id: str, chat_id: str, action: str = "typing") -> None:
        if str(bot_id) != self.api.bot_id():
            raise TelegramError("telegram_bot_mismatch")
        self.api.send_chat_action(chat_id, action)


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


def _watch_telegram_typing(
    heartbeat: TelegramTypingHeartbeat,
    pending: Callable[[], bool],
    *,
    poll_interval: float = 0.5,
    cleanup: Callable[[], None] | None = None,
) -> None:
    """Keep typing visible until the durable update leaves active states."""
    heartbeat.start()
    try:
        while pending():
            time.sleep(max(0.1, poll_interval))
    except Exception:
        # A status lookup failure must fail closed: never leave a background
        # indicator running indefinitely, and never affect message delivery.
        pass
    finally:
        try:
            heartbeat.stop()
        finally:
            if cleanup is not None:
                cleanup()


def run_poller(*, once: bool = False) -> None:
    spool = Path(os.environ.get("ADMIRA_SPOOL_ROOT", DEFAULT_SPOOL))
    api, store = TelegramAPI(os.environ["TELEGRAM_BOT_TOKEN_FILE"]), IngressStore(Pg())
    recovery = None
    if str(os.environ.get("ADMIRA_TELEGRAM_RECOVERY_READY") or "false").strip().lower() == "true":
        recovery = TelegramRecoveryService(
            RecoveryStore(Pg(
                user=os.environ.get("ADMIRA_RECOVERY_DB_USER", "admira_recovery_login"),
                password_file=os.environ["ADMIRA_RECOVERY_DB_PASSWORD_FILE"],
            )),
            read_private_hmac_key(os.environ["ADMIRA_RECOVERY_HMAC_KEY_FILE"]),
            read_private_envelope_key(os.environ["ADMIRA_RECOVERY_DELIVERY_KEY_FILE"]),
            envelope_key_version=os.environ.get("ADMIRA_RECOVERY_DELIVERY_KEY_VERSION", "v1"),
        )
    bot_id = api.bot_id()
    typing_transport = TelegramTypingTransport(api)
    ingress = TelegramIngress(
        store, store, TelegramMediaStager(api, spool), recovery=recovery,
    )
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
            if result.get("status") == "media_failed":
                # Telegram media can transiently fail during getFile/download.
                # Retry only staging; never hide a durable DB failure.
                for _attempt in range(2):
                    try:
                        result = ingress.handle_update(raw, bot_id=bot_id)
                    except ValueError:
                        result = {"status": "invalid"}
                    if result.get("status") != "media_failed":
                        break
                if result.get("status") == "media_failed":
                    try:
                        fallback = ingress.enqueue_media_fallback(
                            raw,
                            bot_id=bot_id,
                            expected_tenant_id=str(result.get("tenant_id") or ""),
                        )
                    except Exception:
                        # The fallback itself must be durable before the
                        # cursor advances; retry it on a later poll iteration.
                        break
                    if fallback is None:
                        # Binding disappeared or update was malformed; do not
                        # guess a tenant and do not advance the cursor.
                        break
            if result.get("status") == "failed":
                break
            store.advance(bot_id, update_id + 1)
            if result.get("status") == "queued":
                chat_id = str(result.get("chat_id") or "")
                if not chat_id:
                    continue
                # The watcher runs in a separate thread.  It must not share
                # the poller's psycopg connection: concurrent transactions on
                # one connection corrupt psycopg's transaction nesting and
                # can restart the poller mid-turn.
                typing_db = Pg()
                typing_store = IngressStore(typing_db)
                heartbeat = TelegramTypingHeartbeat(typing_transport, bot_id, chat_id)
                threading.Thread(
                    target=_watch_telegram_typing,
                    args=(
                        heartbeat,
                        lambda bot_id=bot_id, update_id=update_id: typing_store.telegram_update_pending(
                            bot_id=bot_id, update_id=update_id,
                        ),
                    ),
                    kwargs={"cleanup": typing_db.close},
                    name=f"telegram-typing-{update_id}",
                    daemon=True,
                ).start()
        if once:
            return


def _broker() -> BrokerClient:
    return BrokerClient(Path(os.environ.get("ADMIRA_BROKER_SOCKET", DEFAULT_SOCKET)),
                        Path(os.environ.get("ADMIRA_BROKER_KEY_FILE", DEFAULT_KEY_FILE)))


def run_runtime(*, once: bool = False) -> None:
    central_image_ready = str(os.environ.get("ADMIRA_CENTRAL_IMAGE_READY") or "false").strip().lower() == "true"
    worker, stop = RuntimeWorker(
        RuntimeStore(Pg()), _broker(), central_image_ready=central_image_ready
    ), _stop_event()
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


def run_recovery_email(*, once: bool = False) -> None:
    envelope_cipher = RecoveryEnvelopeCipher(
        read_private_envelope_key(os.environ["ADMIRA_RECOVERY_DELIVERY_KEY_FILE"])
    )
    transport = SMTPRecoveryEmailTransport(
        os.environ["ADMIRA_SMTP_HOST"], int(os.environ["ADMIRA_SMTP_PORT"]),
        os.environ["ADMIRA_SMTP_FROM"],
        security=os.environ["ADMIRA_SMTP_SECURITY"],
        username_file=os.environ.get("ADMIRA_SMTP_USERNAME_FILE"),
        password_file=os.environ.get("ADMIRA_SMTP_PASSWORD_FILE"),
    )
    worker = RecoveryEmailWorker(
        RecoveryEmailStore(Pg()), transport, envelope_cipher.decrypt,
        expected_key_version=os.environ.get("ADMIRA_RECOVERY_DELIVERY_KEY_VERSION", "v1"),
    )
    stop = _stop_event()
    while not stop.is_set():
        result = worker.process_once(limit=1)
        if once:
            return
        stop.wait(0.5 if any(result.values()) else 2.0)


def run_scheduler(*, once: bool = False) -> None:
    central_image_ready = str(os.environ.get("ADMIRA_CENTRAL_IMAGE_READY") or "false").strip().lower() == "true"
    worker, stop = SchedulerWorker(
        SchedulerStore(Pg()), _broker(), central_image_ready=central_image_ready
    ), _stop_event()
    last_idle = 0.0
    last_lifecycle = 0.0
    while not stop.is_set():
        if time.monotonic() - last_lifecycle >= 30:
            try:
                worker.maintain_trial_lifecycle()
            except Exception:
                # Lifecycle work is retried on the next scheduler tick; a
                # transient database/broker outage must not stop cron jobs.
                pass
            last_lifecycle = time.monotonic()
        result = worker.process_once()
        if time.monotonic() - last_idle >= 60:
            worker.suspend_idle_once(idle_seconds=int(os.environ.get("ADMIRA_RUNTIME_IDLE_SECONDS", "900")))
            last_idle = time.monotonic()
        if once:
            return
        stop.wait(0.5 if any(result.values()) else 2.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Admira hosted control-plane service")
    parser.add_argument(
        "command", choices=("poller", "runtime", "delivery", "recovery-email", "scheduler")
    )
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    {
        "poller": run_poller, "runtime": run_runtime, "delivery": run_delivery,
        "recovery-email": run_recovery_email, "scheduler": run_scheduler,
    }[args.command](once=args.once)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
