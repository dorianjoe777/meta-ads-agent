#!/usr/bin/env python3
"""Narrow host broker for isolated Admira tenant runtimes.

The Telegram-facing services never receive the Docker socket.  A dedicated
host service owns lifecycle/turn execution and exposes only this authenticated
Unix-socket protocol.  The shared Telegram token is never passed to this
process.  Requests and responses are one bounded JSON line each.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import socket
import socketserver
import stat
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tenant_turn import MEDIA_RE, run_turn
from tenantctl import DEFAULT_BASE, compose_argv, lifecycle, status, tenant_path, validate_tenant_id


DEFAULT_SOCKET = Path("/run/admira-runtime-broker/broker.sock")
DEFAULT_KEY_FILE = Path("/etc/admira/runtime-broker.key")
DEFAULT_SPOOL = Path("/srv/admira/shared/telegram-spool")
DEFAULT_NORMAL_ACTIVE_TENANTS = 4
DEFAULT_HARD_MAX_ACTIVE_TENANTS = 4
DEFAULT_BURST_MIN_AVAILABLE_MB = 2048
MAX_CONFIGURED_ACTIVE_TENANTS = 8
MAX_WIRE_BYTES = 524_288
MAX_MEDIA_BYTES = 50 * 1024 * 1024
MAX_HERMES_ATTACHMENTS = 6
MEDIA_REF_RE = re.compile(r"^[a-f0-9]{32,64}\.(?:jpg|jpeg|png|webp|gif|mp4|mov|pdf|bin)$", re.IGNORECASE)
JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_SUFFIXES = {".mp4", ".mov"}
ALLOWED_SUFFIXES = IMAGE_SUFFIXES | VIDEO_SUFFIXES | {".pdf", ".bin"}
HOSTED_RESET_REQUEST = "telegram_hosted_reset_request.json"
HOSTED_RESET_RECEIPT = ".hosted-reset-receipt.json"

HOSTED_RESET_SCRIPT = r'''
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app/src")
from complete_reset import reset_workspace

clear_keys = {
    "DASHBOARD_PASSWORD", "DASHBOARD_PASSWORD_HASH", "DASHBOARD_TOKEN",
    "META_AD_ACCOUNT_ID", "META_ACCESS_TOKEN", "META_ACCESS_TOKEN_KIND",
    "META_ACCESS_TOKEN_SAVED_AT", "META_PUBLISHING_ACCESS_TOKEN",
    "META_PUBLISHING_TOKEN_SAVED_AT", "META_OAUTH_CONNECTED_AT",
    "META_OAUTH_EXPIRES_AT", "META_OAUTH_USER_ID", "META_TARGET_CPA",
    "META_NOTIFY_CHANNEL", "META_DAILY_BRIEF_TIME", "META_DAILY_BRIEF_TIMEZONE",
    "SHOPIFY_SHOP_DOMAIN", "SHOPIFY_ADMIN_API_TOKEN", "SHOPIFY_API_VERSION",
    "DAILY_BRIEF_TIME", "DAILY_BRIEF_TIMEZONE", "DAILY_BRIEF_TIMEZONE_SOURCE",
    "DAILY_SOCIAL_CONTENT_ENABLED", "DAILY_SOCIAL_CONTENT_DECISION",
    "DAILY_SOCIAL_CONTENT_TIME", "DAILY_SOCIAL_CONTENT_POSTS_PER_DAY",
    "DAILY_SOCIAL_CONTENT_INTERVAL_DAYS", "DAILY_SOCIAL_CONTENT_FORMATS",
    "DAILY_SOCIAL_CONTENT_VIDEO_INTERVAL_DAYS", "AGENT_COMMUNICATION_STYLE",
    "AGENT_AD_EXPERIENCE_LEVEL",
}
result = reset_workspace(
    runtime_dir=Path("/app/runtime"),
    data_dir=Path("/app/dashboard/data"),
    output_dir=Path("/app/output"),
    logs_dir=Path("/app/logs"),
    brand_guides_dir=Path("/app/brand_guides"),
    brand_seed_dir=Path("/app/brand_guides_seed"),
    ad_config_example=Path("/app/ad-config.example.json"),
    env_paths=[Path("/app/runtime/.env")],
    clear_env_keys=clear_keys,
    forced_env_values={"LIVE_ACTIONS_ENABLED": "false", "META_ADS_AGENT_MODE": "dry-run"},
)
print(json.dumps({"ok": bool(result.get("ok"))}))
'''
HOSTED_IMAGE_ACCESS_FILE = "hosted_image_access.json"
HOSTED_IMAGE_ROUTES = {"central_sponsored", "personal_chatgpt", "blocked"}
HOSTED_LIFECYCLE_STATES = {
    "pending_claim", "trial", "trial_expired", "licensed", "suspended", "cancelled",
}

CRON_RUN_SCRIPT = r'''
import json
import sys

from cron.jobs import advance_next_run, claim_dispatch, get_job, list_jobs, mark_job_run, save_job_output
from cron.scheduler import run_job

job_id = str(json.load(sys.stdin).get("job_id") or "")
job = get_job(job_id)
if not job:
    print(json.dumps({"ok": False, "error_code": "cron_job_not_found"}))
    raise SystemExit(0)
if not claim_dispatch(job_id):
    print(json.dumps({"ok": True, "reply": "", "cron_jobs": list_jobs(include_disabled=True)}))
    raise SystemExit(0)
advance_next_run(job_id)
success, output_doc, final_response, error = run_job(job)
if output_doc:
    save_job_output(job_id, output_doc)
mark_job_run(job_id, success, error)
print(json.dumps({
    "ok": bool(success),
    "reply": str(final_response or ""),
    "error_code": "" if success else "cron_execution_failed",
    "cron_jobs": list_jobs(include_disabled=True),
}, ensure_ascii=False))
'''


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _load_key(path: Path) -> bytes:
    key = path.read_bytes().strip()
    if len(key) < 32:
        raise ValueError("runtime broker key is missing or too short")
    return key


def _acquire_instance_lock(path: Path):
    """Hold a non-blocking process lock for the single host broker instance."""
    handle = path.open("a+b")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.chmod(path, 0o600)
    except (BlockingIOError, OSError) as exc:
        handle.close()
        raise RuntimeError("broker_already_running") from exc
    return handle


def sign_body(key: bytes, body: dict[str, object], *, now: int | None = None, nonce: str | None = None) -> dict[str, object]:
    envelope: dict[str, object] = {
        "timestamp": int(now if now is not None else time.time()),
        "nonce": nonce or secrets.token_hex(16),
        "body": body,
    }
    envelope["signature"] = hmac.new(key, _canonical(envelope), hashlib.sha256).hexdigest()
    return envelope


class ReplayWindow:
    def __init__(self) -> None:
        self._seen: dict[str, int] = {}
        self._lock = threading.Lock()

    def verify(self, envelope: object, key: bytes, *, now: int | None = None) -> dict[str, object]:
        if not isinstance(envelope, dict):
            raise ValueError("invalid_envelope")
        timestamp = int(envelope.get("timestamp") or 0)
        current = int(now if now is not None else time.time())
        if abs(current - timestamp) > 90:
            raise ValueError("expired_request")
        nonce = str(envelope.get("nonce") or "")
        signature = str(envelope.get("signature") or "")
        body = envelope.get("body")
        if not re.fullmatch(r"[a-f0-9]{32}", nonce) or not isinstance(body, dict):
            raise ValueError("invalid_envelope")
        unsigned = {"timestamp": timestamp, "nonce": nonce, "body": body}
        expected = hmac.new(key, _canonical(unsigned), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid_signature")
        with self._lock:
            self._seen = {item: seen_at for item, seen_at in self._seen.items() if seen_at >= current - 180}
            if nonce in self._seen:
                raise ValueError("replayed_request")
            self._seen[nonce] = current
        return body


def _safe_ref(value: object) -> str:
    ref = str(value or "").strip().lower()
    if not MEDIA_REF_RE.fullmatch(ref):
        raise ValueError("invalid_media_ref")
    return ref


def _regular_file(path: Path, root: Path, *, limit: int = MAX_MEDIA_BYTES) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("media_path_escape") from exc
    details = resolved.lstat()
    if not stat.S_ISREG(details.st_mode) or path.is_symlink() or details.st_size > limit:
        raise ValueError("invalid_media_file")
    return resolved


def _cron_snapshot(root: Path) -> list[dict[str, object]]:
    jobs_file = root / "runtime" / "hermes" / "cron" / "jobs.json"
    try:
        # Cron state is writable by the tenant runtime. Reject links, escapes,
        # special files and unbounded input before the privileged host broker
        # reads it.
        jobs_file = _regular_file(jobs_file, root / "runtime", limit=1024 * 1024)
        raw = json.loads(jobs_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    result: list[dict[str, object]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not JOB_ID_RE.fullmatch(str(item.get("id") or "")):
            continue
        result.append({
            "id": str(item["id"]),
            "name": str(item.get("name") or "")[:200],
            "enabled": bool(item.get("enabled", True)),
            "next_run_at": str(item.get("next_run_at") or ""),
            "schedule_display": str(item.get("schedule_display") or "")[:200],
            "timezone": str(item.get("timezone") or "UTC")[:100],
        })
    return result[:100]


def _write_hosted_image_access(
    root: Path, tenant_id: str, raw: object, *, request_marker: object = ""
) -> Path:
    """Persist one trusted, non-secret hosted execution claim for the tenant.

    The central service independently rechecks the database entitlement.  This
    file carries both the image route and the lifecycle already admitted by the
    control plane.  It prevents r91 from selecting a local ChatGPT account and
    lets the hosted runtime distinguish an admitted trial/license from an
    unlicensed self-hosted install.  It is rewritten before every turn/job so a
    persistent MCP process cannot retain authorization across requests.
    """
    tenant_id = validate_tenant_id(tenant_id)
    values = raw if isinstance(raw, dict) else {}
    route = str(values.get("route") or "blocked")
    lifecycle_state = str(values.get("lifecycle_state") or "suspended")
    if route not in HOSTED_IMAGE_ROUTES:
        route = "blocked"
    if lifecycle_state not in HOSTED_LIFECYCLE_STATES:
        lifecycle_state = "suspended"
        route = "blocked"
    marker = str(request_marker or "")
    if len(marker) > 128 or any(ord(char) < 32 or ord(char) == 127 for char in marker):
        marker = ""
    sponsorship_end = str(values.get("image_sponsorship_ends_at") or "")[:80]
    if any(ord(char) < 32 or ord(char) == 127 for char in sponsorship_end):
        sponsorship_end = ""
    payload = {
        "tenant_id": tenant_id,
        "route": route,
        "lifecycle_state": lifecycle_state,
        "central_ready": values.get("central_ready") is True,
        "image_sponsorship_ends_at": sponsorship_end,
        "update_id": marker,
    }
    root_details = root.lstat()
    if root.is_symlink() or not stat.S_ISDIR(root_details.st_mode):
        raise ValueError("tenant_not_provisioned")
    runtime = root / "runtime"
    runtime.mkdir(mode=0o700, exist_ok=True)
    runtime_details = runtime.lstat()
    if runtime.is_symlink() or not stat.S_ISDIR(runtime_details.st_mode):
        raise ValueError("tenant_not_provisioned")
    runtime.chmod(0o700)
    destination = runtime / HOSTED_IMAGE_ACCESS_FILE
    fd, temporary = tempfile.mkstemp(prefix=".hosted-image-access.", dir=str(runtime))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        directory_fd = os.open(runtime, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return destination


class BrokerCore:
    def __init__(self, *, tenants_base: Path = Path(DEFAULT_BASE), spool_base: Path = DEFAULT_SPOOL) -> None:
        self.tenants_base = tenants_base
        self.spool_base = spool_base
        self.inbound = spool_base / "inbound"
        self.outbound = spool_base / "outbound"
        for directory in (self.inbound, self.outbound):
            directory.mkdir(parents=True, exist_ok=True)
            # Poller/delivery run with the dedicated spool supplementary
            # group. Preserve group access instead of silently undoing the
            # permissions established by install-runtime-broker.sh.
            directory.chmod(0o770)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._admission_lock = threading.Lock()

    def _lock_for(self, tenant_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(tenant_id, threading.Lock())

    @staticmethod
    def _capacity_config() -> tuple[int, int, int]:
        """Read bounded capacity settings, failing closed on bad input.

        ``ADMIRA_MAX_ACTIVE_TENANTS`` remains a compatibility hard cap for the
        starter deployment.  The candidate profile uses normal=6, hard=8 and
        only admits slots 7/8 when MemAvailable has the configured headroom.
        """
        legacy = os.environ.get("ADMIRA_MAX_ACTIVE_TENANTS")
        normal_raw = os.environ.get("ADMIRA_NORMAL_ACTIVE_TENANTS", legacy or str(DEFAULT_NORMAL_ACTIVE_TENANTS))
        hard_raw = os.environ.get("ADMIRA_HARD_MAX_ACTIVE_TENANTS", legacy or str(DEFAULT_HARD_MAX_ACTIVE_TENANTS))
        headroom_raw = os.environ.get("ADMIRA_BURST_MIN_AVAILABLE_MB", str(DEFAULT_BURST_MIN_AVAILABLE_MB))
        try:
            normal, hard, headroom_mb = int(normal_raw), int(hard_raw), int(headroom_raw)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("capacity_config_invalid") from exc
        if not 1 <= normal <= hard <= MAX_CONFIGURED_ACTIVE_TENANTS or headroom_mb < 0:
            raise RuntimeError("capacity_config_invalid")
        return normal, hard, headroom_mb

    @classmethod
    def _max_active_tenants(cls) -> int:
        """Return the configured hard ceiling (kept for compatibility/tests)."""
        return cls._capacity_config()[1]

    @staticmethod
    def _mem_available_bytes() -> int:
        """Read MemAvailable from procfs; absence or malformed data fails closed."""
        try:
            for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    if len(parts) == 3 and parts[2] == "kB":
                        value = int(parts[1])
                        if value >= 0:
                            return value * 1024
                    break
        except (OSError, UnicodeError, ValueError):
            pass
        raise RuntimeError("memory_headroom_unavailable")

    @classmethod
    def _capacity_rejection(cls, active_count: int) -> str | None:
        normal, hard, headroom_mb = cls._capacity_config()
        if active_count >= hard:
            return "runtime_capacity_exhausted"
        if active_count < normal:
            return None
        try:
            available = cls._mem_available_bytes()
        except RuntimeError:
            # Procfs is the admission signal for burst capacity. If it cannot
            # be trusted, keep the normal slots available and reject only the
            # burst request with durable backpressure.
            return "runtime_capacity_headroom_low"
        if available < headroom_mb * 1024 * 1024:
            return "runtime_capacity_headroom_low"
        return None

    @classmethod
    def _capacity_allows(cls, active_count: int) -> bool:
        return cls._capacity_rejection(active_count) is None

    @staticmethod
    def _active_managed_tenants() -> set[str]:
        """List running tenant labels without broadening broker privileges."""
        result = subprocess.run(
            ["docker", "ps", "--filter", "label=com.admira.managed=true",
             "--filter", "status=running", "--format", "{{.Label \"com.admira.tenant\"}}"],
            check=False, text=True, capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError("runtime_capacity_check_failed")
        return {
            line.strip() for line in (result.stdout or "").splitlines()
            if re.fullmatch(r"[a-z0-9][a-z0-9-]{2,62}", line.strip())
        }

    def _ensure_running(self, tenant_id: str) -> Path:
        root = tenant_path(self.tenants_base, tenant_id)
        if not (root / "compose.yaml").is_file():
            raise ValueError("tenant_not_provisioned")
        # Serialize count + start across different tenant request threads so
        # two simultaneous wake-ups cannot both consume the final slot.
        with self._admission_lock:
            active = self._active_managed_tenants()
            if tenant_id in active:
                return root
            rejection = self._capacity_rejection(len(active))
            if rejection is not None:
                raise RuntimeError(rejection)
            result = lifecycle(self.tenants_base, tenant_id, "start")
            if not result.get("ok"):
                raise RuntimeError("runtime_start_failed")
        return root

    @staticmethod
    def _validated_reset_request(root: Path, turn: dict[str, object]) -> dict[str, object]:
        path = root / "runtime" / HOSTED_RESET_REQUEST
        try:
            resolved = _regular_file(path, root / "runtime", limit=16_384)
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("hosted_reset_not_authorized") from exc
        if not isinstance(payload, dict) or payload.get("status") != "pending":
            raise ValueError("hosted_reset_not_authorized")
        if not re.fullmatch(r"^-?[0-9]{1,32}$", str(payload.get("chat_id") or "")):
            raise ValueError("hosted_reset_not_authorized")
        if not re.fullmatch(r"^[0-9]{1,32}$", str(payload.get("user_id") or "")):
            raise ValueError("hosted_reset_not_authorized")
        try:
            expected_update_id = int(turn.get("update_id"))
            recorded_update_id = int(payload.get("hosted_update_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("hosted_reset_not_authorized") from exc
        if (
            str(payload.get("chat_id") or "") != str(turn.get("chat_id") or "")
            or str(payload.get("user_id") or "") != str(turn.get("user_id") or "")
            or recorded_update_id != expected_update_id
        ):
            raise ValueError("hosted_reset_not_authorized")
        try:
            requested = datetime.fromisoformat(str(payload.get("requested_at") or "").replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("hosted_reset_not_authorized") from exc
        if requested.tzinfo is None:
            requested = requested.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - requested.astimezone(timezone.utc)).total_seconds()
        if age < -60 or age > 15 * 60:
            raise ValueError("hosted_reset_not_authorized")
        return payload

    @staticmethod
    def _reset_identity(turn: dict[str, object]) -> dict[str, object]:
        try:
            update_id = int(turn.get("update_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("hosted_reset_not_authorized") from exc
        chat_id = str(turn.get("chat_id") or "")
        user_id = str(turn.get("user_id") or "")
        if not re.fullmatch(r"^-?[0-9]{1,32}$", chat_id) or not re.fullmatch(r"^[0-9]{1,32}$", user_id):
            raise ValueError("hosted_reset_not_authorized")
        return {"chat_id": chat_id, "user_id": user_id, "update_id": update_id}

    @classmethod
    def _write_reset_receipt(
        cls, root: Path, turn: dict[str, object], *, status_value: str = "completed"
    ) -> None:
        if status_value not in {"in_progress", "completed"}:
            raise ValueError("invalid_reset_receipt_status")
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "status": status_value,
            **cls._reset_identity(turn),
            "updated_at": now,
        }
        if status_value == "completed":
            payload["completed_at"] = now
        fd, temporary = tempfile.mkstemp(prefix=".hosted-reset-receipt.", dir=str(root))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, root / HOSTED_RESET_RECEIPT)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    @classmethod
    def _reset_receipt_status(cls, root: Path, turn: dict[str, object]) -> str:
        try:
            path = _regular_file(root / HOSTED_RESET_RECEIPT, root, limit=16_384)
            payload = json.loads(path.read_text(encoding="utf-8"))
            expected = cls._reset_identity(turn)
        except (OSError, ValueError, TypeError):
            return ""
        if not (
            isinstance(payload, dict)
            and payload.get("status") in {"in_progress", "completed"}
            and str(payload.get("chat_id") or "") == expected["chat_id"]
            and str(payload.get("user_id") or "") == expected["user_id"]
            and payload.get("update_id") == expected["update_id"]
        ):
            return ""
        return str(payload["status"])

    @classmethod
    def _completed_reset_matches(cls, root: Path, turn: dict[str, object]) -> bool:
        return cls._reset_receipt_status(root, turn) == "completed"

    @staticmethod
    def _complete_reset_reply(language: object) -> str:
        if str(language or "es").lower().startswith("en"):
            return (
                "✅ I completely reset your private Admira space. I kept the license and model connections; "
                "the Meta connection, business setup, memory, sessions, local files, and scheduled jobs were removed. "
                "Campaigns that already exist in Meta were not deleted."
            )
        return (
            "✅ Reinicié completamente tu espacio privado de Admira. Conservé la licencia y las conexiones del modelo; "
            "se borraron la conexión de Meta, el negocio, la memoria, las sesiones, los archivos locales y los cronjobs. "
            "Las campañas que ya existen dentro de Meta no fueron borradas."
        )

    def _perform_complete_reset(
        self, root: Path, turn: dict[str, object], *, resume: bool = False
    ) -> None:
        """Quiesce and reset one tenant without modifying the pinned image."""
        if resume:
            if self._reset_receipt_status(root, turn) != "in_progress":
                raise ValueError("hosted_reset_not_authorized")
        else:
            self._validated_reset_request(root, turn)
            # Persist authorization outside every tenant container mount before
            # stopping anything. If the broker dies at any later instruction,
            # the exact same durable Telegram update resumes here instead of
            # sending the destructive confirmation phrase to Hermes.
            self._write_reset_receipt(root, turn, status_value="in_progress")
        # A one-off container mounts exactly this tenant's private directories
        # after the interactive runtime has stopped.  This avoids deleting
        # Hermes/session files while the live agent still has them open.
        command = compose_argv(
            root, "run", "--rm", "--no-deps", "-T", "--pull", "never",
            "--entrypoint", "python3", "admira", "-c", HOSTED_RESET_SCRIPT,
        )
        reset_error: Exception | None = None
        response: object = {}
        # Reserve the tenant's former admission slot throughout stop, reset and
        # restart so another tenant cannot consume the final slot in between.
        # During crash recovery the tenant may already be stopped; if every
        # slot was consumed meanwhile, finish the reset but leave it asleep.
        with self._admission_lock:
            active = self._active_managed_tenants()
            should_restart = root.name in active or len(active) < self._max_active_tenants()
            stopped = lifecycle(self.tenants_base, root.name, "suspend")
            if not stopped.get("ok"):
                raise RuntimeError("hosted_reset_restart_failed")
            try:
                completed = subprocess.run(
                    command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=180, check=False,
                )
                try:
                    response = json.loads(completed.stdout or "")
                except (TypeError, ValueError):
                    response = {}
                if completed.returncode != 0 or not isinstance(response, dict) or not response.get("ok"):
                    reset_error = RuntimeError("hosted_reset_failed")
            except (OSError, subprocess.TimeoutExpired) as exc:
                reset_error = exc
            # Always attempt to restore availability, even if the isolated
            # reset process failed after partially touching tenant state, but
            # never exceed capacity while resuming after a broker crash.
            if should_restart:
                started = lifecycle(self.tenants_base, root.name, "start")
                if not started.get("ok"):
                    raise RuntimeError("hosted_reset_restart_failed")
        if reset_error is not None:
            raise RuntimeError("hosted_reset_failed") from reset_error
        # The database update is acknowledged after the broker response. Keep a
        # host-only receipt so a lost socket response or worker crash replays
        # success instead of sending the destructive phrase to the model.
        self._write_reset_receipt(root, turn, status_value="completed")

    def _prepare_inbound(self, root: Path, media: object, update_id: object) -> dict[str, object]:
        if not isinstance(media, list) or len(media) > 8:
            raise ValueError("invalid_inbound_media")
        if not media:
            return {"image_paths": [], "attachments": [], "cleanup_path": None}
        token = hashlib.sha256(f"{update_id}:{secrets.token_hex(8)}".encode()).hexdigest()[:32]
        target_dir = root / "output" / "telegram_uploads" / token
        target_dir.mkdir(parents=True, exist_ok=True)
        target_dir.chmod(0o700)
        images: list[str] = []
        attachments: list[dict[str, object]] = []
        try:
            for item in media:
                if not isinstance(item, dict):
                    raise ValueError("invalid_inbound_media")
                ref = _safe_ref(item.get("ref"))
                source = _regular_file(self.inbound / ref, self.inbound)
                suffix = source.suffix.lower()
                if suffix not in ALLOWED_SUFFIXES:
                    raise ValueError("unsupported_media_type")
                target_name = hashlib.sha256(ref.encode()).hexdigest()[:32] + suffix
                target = target_dir / target_name
                shutil.copyfile(source, target)
                target.chmod(0o600)
                hosted_path = f"/app/output/telegram_uploads/{token}/{target_name}"
                digest = hashlib.sha256()
                with source.open("rb") as reader:
                    while chunk := reader.read(1024 * 1024):
                        digest.update(chunk)
                attachments.append({
                    # Derive the effective kind from the validated suffix;
                    # never let stored metadata reinterpret an executable/file.
                    "kind": "photo" if suffix in IMAGE_SUFFIXES else "video" if suffix in VIDEO_SUFFIXES else "document",
                    "path": hosted_path,
                    "mime_type": str(item.get("mime_type") or "")[:120],
                    "size": int(source.stat().st_size),
                    "sha256": digest.hexdigest(),
                })
                if suffix in IMAGE_SUFFIXES and len(images) < MAX_HERMES_ATTACHMENTS:
                    images.append(hosted_path)
        except Exception:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise
        return {"image_paths": images, "attachments": attachments, "cleanup_path": target_dir}

    def _stage_outbound(self, root: Path, media_paths: object) -> list[dict[str, str]]:
        staged: list[dict[str, str]] = []
        output_root = root / "output"
        for raw in list(media_paths or [])[:8]:
            path = str(raw or "").strip()
            if not path.startswith("/app/output/"):
                continue
            relative = path.removeprefix("/app/output/")
            source = _regular_file(output_root / relative, output_root)
            suffix = source.suffix.lower()
            if suffix not in ALLOWED_SUFFIXES:
                continue
            ref = f"{secrets.token_hex(24)}{suffix}"
            temporary = self.outbound / f".{ref}.tmp"
            destination = self.outbound / ref
            digest = hashlib.sha256()
            with source.open("rb") as reader, temporary.open("xb") as writer:
                while chunk := reader.read(1024 * 1024):
                    digest.update(chunk)
                    writer.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            temporary.chmod(0o660)
            os.replace(temporary, destination)
            kind = "photo" if suffix in IMAGE_SUFFIXES else "video" if suffix in VIDEO_SUFFIXES else "document"
            staged.append({"kind": kind, "ref": ref, "sha256": digest.hexdigest(), "caption": ""})
        return staged

    def _turn(self, tenant_id: str, request: dict[str, object]) -> dict[str, object]:
        turn = request.get("turn")
        if not isinstance(turn, dict):
            raise ValueError("invalid_turn")
        payload = dict(turn)
        root = tenant_path(self.tenants_base, tenant_id)
        if not (root / "compose.yaml").is_file():
            raise ValueError("tenant_not_provisioned")
        # A reset receipt is host-only control state. Replaying its response or
        # resuming it must not depend on waking a tenant or consuming capacity.
        reset_receipt_status = self._reset_receipt_status(root, payload)
        if reset_receipt_status == "completed":
            return {
                "ok": True,
                "reply": self._complete_reset_reply(payload.get("language")),
                "media": [],
                "error_code": "",
                "cron_jobs": _cron_snapshot(root),
            }
        if reset_receipt_status == "in_progress":
            try:
                self._perform_complete_reset(root, payload, resume=True)
            except ValueError as exc:
                return {"ok": False, "reply": "", "media": [], "error_code": str(exc), "cron_jobs": []}
            except RuntimeError as exc:
                return {"ok": False, "reply": "", "media": [], "error_code": str(exc), "cron_jobs": []}
            return {
                "ok": True,
                "reply": self._complete_reset_reply(payload.get("language")),
                "media": [],
                "error_code": "",
                "cron_jobs": _cron_snapshot(root),
            }
        root = self._ensure_running(tenant_id)
        _write_hosted_image_access(
            root, tenant_id, payload.get("image_access"),
            request_marker=payload.get("update_id"),
        )
        inbound = self._prepare_inbound(root, request.get("media") or [], payload.get("update_id"))
        try:
            if inbound["image_paths"]:
                payload["image_paths"] = inbound["image_paths"]
            if inbound["attachments"]:
                payload["attachments"] = inbound["attachments"]
            result: dict[str, object] = {"ok": False, "error_code": "runtime_not_ready"}
            for attempt in range(10):
                result = run_turn(self.tenants_base, tenant_id, payload)
                if result.get("error_code") != "runtime_not_ready":
                    break
                if attempt < 9:
                    time.sleep(2)
            reply = str(result.get("reply") or "")
            # The tenant boundary marks a failed image receipt explicitly.
            # Keep this second check here so a future transport change cannot
            # accidentally stage a model-written MEDIA path after failure.
            staged = [] if result.get("image_generation_failed") else self._stage_outbound(root, result.get("media_paths") or [])
            visible = MEDIA_RE.sub("", reply).strip()
            if result.get("control_action") == "complete_reset":
                try:
                    self._perform_complete_reset(root, payload)
                except ValueError as exc:
                    return {"ok": False, "reply": "", "media": [], "error_code": str(exc), "cron_jobs": []}
                except RuntimeError as exc:
                    return {"ok": False, "reply": "", "media": [], "error_code": str(exc), "cron_jobs": []}
                visible = self._complete_reset_reply(payload.get("language"))
            return {
                "ok": bool(result.get("ok")) or bool(visible) or bool(staged),
                "reply": visible,
                "media": staged,
                "error_code": str(result.get("error_code") or "")[:80],
                "cron_jobs": _cron_snapshot(root),
            }
        finally:
            cleanup_path = inbound.get("cleanup_path")
            if isinstance(cleanup_path, Path):
                shutil.rmtree(cleanup_path, ignore_errors=True)

    def _run_job(self, tenant_id: str, request: dict[str, object]) -> dict[str, object]:
        root = self._ensure_running(tenant_id)
        job_id = str(request.get("job_id") or "")
        if not JOB_ID_RE.fullmatch(job_id):
            raise ValueError("invalid_job_id")
        _write_hosted_image_access(
            root, tenant_id, request.get("image_access"), request_marker=job_id,
        )
        command = compose_argv(root, "exec", "-T", "admira", "python3", "-c", CRON_RUN_SCRIPT)
        try:
            completed = subprocess.run(
                command, input=json.dumps({"job_id": job_id}), text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("cron_timeout") from exc
        if completed.returncode != 0:
            raise RuntimeError("cron_runtime_failed")
        try:
            raw = json.loads(completed.stdout or "")
        except ValueError as exc:
            raise RuntimeError("cron_protocol_error") from exc
        reply = str(raw.get("reply") or "")
        media_paths = MEDIA_RE.findall(reply)
        staged = self._stage_outbound(root, media_paths)
        return {
            "ok": bool(raw.get("ok")),
            "reply": MEDIA_RE.sub("", reply).strip(),
            "media": staged,
            "error_code": str(raw.get("error_code") or "")[:80],
            "cron_jobs": _cron_snapshot(root),
        }

    def handle(self, request: object) -> dict[str, object]:
        if not isinstance(request, dict):
            raise ValueError("invalid_request")
        action = str(request.get("action") or "")
        tenant_id = validate_tenant_id(str(request.get("tenant_id") or ""))
        with self._lock_for(tenant_id):
            if action == "turn":
                return self._turn(tenant_id, request)
            if action == "run_job":
                return self._run_job(tenant_id, request)
            if action == "sync_jobs":
                root = tenant_path(self.tenants_base, tenant_id)
                return {"ok": True, "cron_jobs": _cron_snapshot(root)}
            if action == "suspend":
                result = lifecycle(self.tenants_base, tenant_id, "suspend")
                return {"ok": bool(result.get("ok")), "error_code": "" if result.get("ok") else "runtime_suspend_failed"}
            if action == "status":
                result = status(self.tenants_base, tenant_id)
                valid = bool(result.get("ok"))
                return {"ok": valid, "running": valid and bool(str(result.get("output") or "").strip())}
        raise ValueError("unsupported_action")


class BrokerClient:
    def __init__(self, socket_path: Path = DEFAULT_SOCKET, key_file: Path = DEFAULT_KEY_FILE, *, timeout: float = 920.0) -> None:
        self.socket_path, self.key_file, self.timeout = socket_path, key_file, timeout

    def request(self, body: dict[str, object]) -> dict[str, object]:
        wire = _canonical(sign_body(_load_key(self.key_file), body)) + b"\n"
        if len(wire) > MAX_WIRE_BYTES:
            raise ValueError("broker_request_too_large")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(self.timeout)
            client.connect(str(self.socket_path))
            client.sendall(wire)
            response = b""
            while not response.endswith(b"\n"):
                chunk = client.recv(min(65536, MAX_WIRE_BYTES + 1 - len(response)))
                if not chunk:
                    break
                response += chunk
                if len(response) > MAX_WIRE_BYTES:
                    raise RuntimeError("broker_response_too_large")
        try:
            parsed = json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError("broker_protocol_error") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("broker_protocol_error")
        return parsed


class _ThreadingUnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        line = self.rfile.readline(MAX_WIRE_BYTES + 1)
        if not line or len(line) > MAX_WIRE_BYTES:
            self._send({"ok": False, "error_code": "invalid_request"})
            return
        try:
            envelope = json.loads(line.decode("utf-8"))
            body = self.server.replay.verify(envelope, self.server.key)  # type: ignore[attr-defined]
            response = self.server.core.handle(body)  # type: ignore[attr-defined]
        except (ValueError, OSError) as exc:
            code = str(exc) if re.fullmatch(r"[a-z0-9_]{3,80}", str(exc)) else "invalid_request"
            response = {"ok": False, "error_code": code}
        except RuntimeError as exc:
            # BrokerCore raises stable snake-case dependency/control-plane
            # codes. Preserve those for retry policy, but never turn an
            # arbitrary internal exception message into a client response.
            code = str(exc) if re.fullmatch(r"[a-z0-9_]{3,80}", str(exc)) else "broker_failure"
            response = {"ok": False, "error_code": code}
        except Exception:
            response = {"ok": False, "error_code": "broker_failure"}
        self._send(response)

    def _send(self, response: dict[str, object]) -> None:
        wire = _canonical(response)
        if len(wire) > MAX_WIRE_BYTES:
            wire = _canonical({"ok": False, "error_code": "broker_response_too_large"})
        self.wfile.write(wire + b"\n")


def serve(*, socket_path: Path, key_file: Path, tenants_base: Path, spool_base: Path, socket_gid: int | None = None) -> None:
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.parent.chmod(0o750)
    instance_lock = _acquire_instance_lock(socket_path.with_name("broker.lock"))
    server = None
    try:
        if socket_path.exists():
            if not stat.S_ISSOCK(socket_path.lstat().st_mode):
                raise RuntimeError("refusing to replace non-socket broker path")
            socket_path.unlink()
        server = _ThreadingUnixServer(str(socket_path), _Handler)
        server.key = _load_key(key_file)  # type: ignore[attr-defined]
        server.replay = ReplayWindow()  # type: ignore[attr-defined]
        server.core = BrokerCore(tenants_base=tenants_base, spool_base=spool_base)  # type: ignore[attr-defined]
        os.chmod(socket_path, 0o660)
        if socket_gid is not None:
            os.chown(socket_path, -1, socket_gid)
        server.serve_forever(poll_interval=0.5)
    finally:
        if server is not None:
            server.server_close()
        if socket_path.exists() and stat.S_ISSOCK(socket_path.lstat().st_mode):
            socket_path.unlink()
        fcntl.flock(instance_lock.fileno(), fcntl.LOCK_UN)
        instance_lock.close()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Admira isolated runtime broker")
    result.add_argument("command", choices=("serve", "call"))
    result.add_argument("--socket", type=Path, default=Path(os.environ.get("ADMIRA_BROKER_SOCKET", DEFAULT_SOCKET)))
    result.add_argument("--key-file", type=Path, default=Path(os.environ.get("ADMIRA_BROKER_KEY_FILE", DEFAULT_KEY_FILE)))
    result.add_argument("--tenants-base", type=Path, default=Path(os.environ.get("ADMIRA_TENANTS_BASE", DEFAULT_BASE)))
    result.add_argument("--spool-base", type=Path, default=Path(os.environ.get("ADMIRA_TELEGRAM_SPOOL", DEFAULT_SPOOL)))
    result.add_argument("--socket-gid", type=int, default=None)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "serve":
        serve(socket_path=args.socket, key_file=args.key_file, tenants_base=args.tenants_base,
              spool_base=args.spool_base, socket_gid=args.socket_gid)
        return 0
    try:
        body = json.load(sys.stdin)
        result = BrokerClient(args.socket, args.key_file).request(body)
    except Exception as exc:
        result = {"ok": False, "error_code": str(exc) if re.fullmatch(r"[a-z0-9_]{3,80}", str(exc)) else "broker_client_failed"}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
