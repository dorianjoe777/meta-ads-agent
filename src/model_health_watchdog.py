#!/usr/bin/env python3
"""Deterministic, bounded self-healing for the Admira Telegram model runtime.

The watchdog never calls an LLM.  It observes the Gateway supervisor, the
configured provider, explicit credential failures, and *new* Gateway log
output.  Repairs are intentionally narrow: restart a dead/crashing Gateway,
reconcile scheduled jobs, or ask the buyer to reconnect credentials.  A
restart budget prevents a bad provider configuration from becoming a loop.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from hermes_bridge import hermes_brain_settings, hermes_environment
from local_store import read_json, write_private_json


STATE_VERSION = 1
DEFAULT_RESTART_LIMIT = 2
DEFAULT_RESTART_WINDOW_SECONDS = 60 * 60
DEFAULT_RESTART_COOLDOWN_SECONDS = 10 * 60
DEFAULT_NOTIFICATION_COOLDOWN_SECONDS = 6 * 60 * 60
MAX_LOG_READ_BYTES = 96 * 1024

PERMANENT_AUTH_PATTERNS = (
    "authentication token has been invalidated",
    "token_invalidated",
    "invalid_grant",
    "refresh token is invalid",
    "refresh token has been revoked",
    "oauth token has been revoked",
    "provider authentication failed",
    "could not resolve credentials",
    "no credentials available",
    "not logged in",
)
CONFIG_PATTERNS = (
    "unknown provider",
    "api key is missing",
    "missing api key",
    "model not configured",
    "no model configured",
)
RATE_LIMIT_PATTERNS = (
    "rate limit",
    "rate-limit",
    "rate_limited",
    "quota exhausted",
    "usage limit",
    "status 429",
    "error 429",
    "(429)",
)


def _now_iso(epoch):
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()


def _safe_state(path):
    state = read_json(Path(path), {})
    if not isinstance(state, dict):
        state = {}
    state.setdefault("version", STATE_VERSION)
    state.setdefault("restart_epochs", [])
    state.setdefault("consecutive_failures", 0)
    state.setdefault("last_issue", "")
    state.setdefault("last_notification_issue", "")
    state.setdefault("last_notification_epoch", 0)
    state.setdefault("log_offset", 0)
    state.setdefault("log_inode", 0)
    return state


def _save_state(path, state):
    state["version"] = STATE_VERSION
    write_private_json(Path(path), state, ensure_ascii=False)


def _configured_provider_issue(config):
    brain = hermes_brain_settings(config)
    provider = str(brain.get("provider") or "").strip()
    model = str(brain.get("model") or "").strip()
    if not provider or not model:
        return "provider_config_missing"
    if not brain.get("requires_codex_auth"):
        if not str(brain.get("api_key") or "").strip():
            return "provider_config_missing"
        if provider == "custom" and not str(brain.get("base_url") or "").strip():
            return "provider_config_missing"
    return ""


def classify_gateway_log(text):
    """Classify only fresh Gateway output; never infer from old log history."""
    lower = str(text or "").lower()
    if not lower:
        return {"issue": "", "exit_count": 0}
    exit_count = len(re.findall(r"hermes gateway exited with code\s+(-?\d+)", lower))
    if any(marker in lower for marker in PERMANENT_AUTH_PATTERNS):
        return {"issue": "credential_reconnect_required", "exit_count": exit_count}
    if any(marker in lower for marker in CONFIG_PATTERNS):
        return {"issue": "provider_config_missing", "exit_count": exit_count}
    if any(marker in lower for marker in RATE_LIMIT_PATTERNS):
        return {"issue": "provider_rate_limited", "exit_count": exit_count}
    if exit_count >= 2:
        return {"issue": "gateway_crash_loop", "exit_count": exit_count}
    if exit_count == 1:
        return {"issue": "gateway_exit", "exit_count": exit_count}
    return {"issue": "", "exit_count": exit_count}


def read_new_gateway_log(log_path, state):
    """Read new bytes since the last check and advance a rotation-safe cursor.

    On the first check we start at EOF. This deliberately ignores historical
    failures that may already have been fixed before the watchdog was shipped.
    """
    path = Path(log_path)
    try:
        stat = path.stat()
    except OSError:
        return "", state
    inode = int(getattr(stat, "st_ino", 0) or 0)
    size = int(stat.st_size or 0)
    previous_inode = int(state.get("log_inode") or 0)
    previous_offset = int(state.get("log_offset") or 0)
    if not previous_inode:
        state["log_inode"] = inode
        state["log_offset"] = size
        return "", state
    if inode != previous_inode or previous_offset > size:
        previous_offset = max(0, size - MAX_LOG_READ_BYTES)
    start = max(previous_offset, size - MAX_LOG_READ_BYTES)
    try:
        with path.open("rb") as handle:
            handle.seek(start)
            payload = handle.read(MAX_LOG_READ_BYTES)
    except OSError:
        payload = b""
    state["log_inode"] = inode
    state["log_offset"] = size
    return payload.decode("utf-8", errors="replace"), state


def run_hermes_doctor(config, timeout=25):
    """Run Hermes' read-only diagnosis. Never use ``doctor --fix`` unattended."""
    cli = shutil.which(getattr(config, "hermes_cli", "hermes") or "hermes")
    if not cli:
        return {"ok": False, "returncode": None, "reason": "hermes_not_installed"}
    try:
        result = subprocess.run(
            [cli, "doctor"],
            cwd=str(Path(__file__).resolve().parent.parent),
            env=hermes_environment(config),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(5, min(45, int(timeout or 25))),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": None, "reason": "doctor_timeout"}
    except OSError:
        return {"ok": False, "returncode": None, "reason": "doctor_failed"}
    # Persist no raw output: doctor can mention local paths/provider metadata.
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "reason": "doctor_ok" if result.returncode == 0 else "doctor_found_issues",
    }


def _restart_allowed(state, now_epoch, limit, window_seconds, cooldown_seconds):
    cutoff = now_epoch - window_seconds
    recent = [float(item) for item in state.get("restart_epochs", []) if float(item or 0) >= cutoff]
    state["restart_epochs"] = recent
    if len(recent) >= limit:
        return False, "restart_budget_exhausted"
    if recent and now_epoch - recent[-1] < cooldown_seconds:
        return False, "restart_cooldown"
    return True, ""


def _should_notify(state, issue, now_epoch, cooldown_seconds):
    if not issue:
        return False
    if state.get("last_notification_issue") != issue:
        return True
    return now_epoch - float(state.get("last_notification_epoch") or 0) >= cooldown_seconds


def run_model_health_check(
    config,
    *,
    state_file,
    log_path,
    telegram_status,
    gateway_status,
    runtime_model_state,
    codex_session_status,
    start_gateway,
    stop_gateway,
    reconcile_crons,
    notify,
    doctor=run_hermes_doctor,
    now_epoch=None,
    restart_limit=DEFAULT_RESTART_LIMIT,
    restart_window_seconds=DEFAULT_RESTART_WINDOW_SECONDS,
    restart_cooldown_seconds=DEFAULT_RESTART_COOLDOWN_SECONDS,
    notification_cooldown_seconds=DEFAULT_NOTIFICATION_COOLDOWN_SECONDS,
):
    """Check and, when safe, repair the model/Gateway runtime once."""
    now_epoch = float(now_epoch if now_epoch is not None else time.time())
    state = _safe_state(state_file)
    state["last_check_epoch"] = now_epoch
    state["last_check_at"] = _now_iso(now_epoch)

    telegram = telegram_status(config) or {}
    if not (
        telegram.get("enabled")
        and telegram.get("bot_configured")
        and telegram.get("chat_id")
        and telegram.get("mode") != "legacy"
    ):
        state.update({"status": "disabled", "last_issue": "", "consecutive_failures": 0})
        _save_state(state_file, state)
        return {"ok": True, "status": "disabled", "action": "none"}

    gateway = gateway_status(config) or {}
    runtime = runtime_model_state(config) or {}
    fresh_log, state = read_new_gateway_log(log_path, state)
    log_health = classify_gateway_log(fresh_log)
    issue = ""
    detail = ""

    if not gateway.get("process_running"):
        issue = "gateway_down"
    else:
        issue = _configured_provider_issue(config)

    brain = hermes_brain_settings(config)
    if not issue and brain.get("requires_codex_auth"):
        session = codex_session_status(config, timeout=10) or {}
        # Only explicit permanent invalidation triggers reconnection. A vague
        # status parse is not allowed to interrupt a Gateway that is serving.
        if session.get("reauth_required"):
            issue = "credential_reconnect_required"
        elif session.get("ready"):
            detail = "codex_ready"
        else:
            detail = "codex_status_inconclusive"

    log_issue = log_health.get("issue") or ""
    log_lower = fresh_log.lower()
    if (
        log_issue == "credential_reconnect_required"
        and not brain.get("requires_codex_auth")
        and any(marker in log_lower for marker in ("openai-codex", "openai codex", "codex/image", "codex image"))
    ):
        # A separate Image 2/Codex session may need attention while the main
        # MiniMax/NVIDIA/custom brain remains healthy. Do not misdiagnose that
        # optional image credential as a broken Telegram brain.
        log_issue = ""
    if log_issue in {"credential_reconnect_required", "provider_config_missing"}:
        issue = log_issue
    elif not issue and log_issue:
        issue = log_issue

    previous_issue = str(state.get("last_issue") or "")
    if issue and issue == previous_issue:
        consecutive = int(state.get("consecutive_failures") or 0) + 1
    elif issue:
        consecutive = 1
    else:
        consecutive = 0
    state["consecutive_failures"] = consecutive
    state["last_issue"] = issue
    state["configured_provider"] = str(runtime.get("configured_provider") or brain.get("provider") or "")
    state["configured_model"] = str(runtime.get("configured_model") or brain.get("model") or "")
    state["runtime_provider"] = str(runtime.get("provider") or "")
    state["runtime_model"] = str(runtime.get("model") or "")

    action = "none"
    doctor_result = None
    notification_sent = False

    if not issue:
        # Keep cron inference pinned to the selected product brain. This is
        # safe, does not interrupt Telegram, and repairs old unpinned jobs.
        last_reconcile = float(state.get("last_cron_reconcile_epoch") or 0)
        if now_epoch - last_reconcile >= 60 * 60:
            reconcile_result = reconcile_crons(config) or {}
            state["last_cron_reconcile_epoch"] = now_epoch
            state["last_cron_reconcile_ok"] = bool(reconcile_result.get("ok"))
        state.update({"status": "healthy", "last_healthy_at": _now_iso(now_epoch)})
    elif issue == "provider_rate_limited":
        # A restart cannot restore provider quota and can interrupt a useful
        # fallback. Hermes' runtime fallback handles this condition.
        state["status"] = "degraded_rate_limit"
        action = "fallback_left_running"
    elif issue in {"credential_reconnect_required", "provider_config_missing"}:
        state["status"] = "needs_buyer_action"
        if _should_notify(state, issue, now_epoch, notification_cooldown_seconds):
            notification_sent = bool(notify(issue, {"detail": detail, "runtime": runtime}))
            if notification_sent:
                state["last_notification_issue"] = issue
                state["last_notification_epoch"] = now_epoch
        action = "buyer_notified" if notification_sent else "waiting_for_buyer"
    else:
        allowed, blocked_reason = _restart_allowed(
            state,
            now_epoch,
            max(1, int(restart_limit)),
            max(60, int(restart_window_seconds)),
            max(30, int(restart_cooldown_seconds)),
        )
        should_restart = issue in {"gateway_down", "gateway_crash_loop"} or consecutive >= 2
        if should_restart and allowed:
            if issue != "gateway_down":
                doctor_result = doctor(config)
            stop_gateway()
            started = start_gateway(config) or {}
            state.setdefault("restart_epochs", []).append(now_epoch)
            state["last_restart_at"] = _now_iso(now_epoch)
            state["last_restart_reason"] = issue
            state["status"] = "recovering" if started.get("started") else "unhealthy"
            action = "gateway_restarted" if started.get("started") else "restart_failed"
        elif should_restart and blocked_reason == "restart_budget_exhausted":
            state["status"] = "unhealthy"
            escalation_issue = "restart_budget_exhausted"
            if _should_notify(state, escalation_issue, now_epoch, notification_cooldown_seconds):
                notification_sent = bool(notify(escalation_issue, {"original_issue": issue, "runtime": runtime}))
                if notification_sent:
                    state["last_notification_issue"] = escalation_issue
                    state["last_notification_epoch"] = now_epoch
            action = "restart_budget_exhausted"
        else:
            state["status"] = "observing" if consecutive < 2 else "restart_cooldown"
            action = "observe_once" if consecutive < 2 else "cooldown"

    if doctor_result is not None:
        state["last_doctor_at"] = _now_iso(now_epoch)
        state["last_doctor"] = doctor_result
    _save_state(state_file, state)
    return {
        "ok": state.get("status") in {"healthy", "disabled", "recovering", "degraded_rate_limit"},
        "status": state.get("status"),
        "issue": issue,
        "action": action,
        "consecutive_failures": consecutive,
        "notification_sent": notification_sent,
        "doctor": doctor_result,
    }
