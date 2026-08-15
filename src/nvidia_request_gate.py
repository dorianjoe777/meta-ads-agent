#!/usr/bin/env python3
"""Cross-process request gate for hosted NVIDIA NIM inference."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback is process-local.
    fcntl = None


DEFAULT_REQUESTS_PER_MINUTE = 36  # keep headroom below NVIDIA's nominal 40
DEFAULT_MIN_INTERVAL_SECONDS = 1.7
WINDOW_SECONDS = 60.0


def _positive_float(value, default):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _positive_int(value, default):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def state_path() -> Path:
    configured = str(os.environ.get("ADMIRA_NVIDIA_RATE_LIMIT_STATE") or "").strip()
    if configured:
        return Path(configured).expanduser()
    root = str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "").strip()
    if root:
        return Path(root).expanduser() / "runtime" / "nvidia-request-gate.json"
    return Path.home() / ".cache" / "admira-ia" / "nvidia-request-gate.json"


def _read_starts(handle, now):
    try:
        handle.seek(0)
        payload = json.load(handle)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        payload = {}
    starts = []
    for value in (payload.get("starts") if isinstance(payload, dict) else []) or []:
        try:
            stamp = float(value)
        except (TypeError, ValueError):
            continue
        if now - stamp < WINDOW_SECONDS and stamp <= now + 1:
            starts.append(stamp)
    return starts


def _write_starts(handle, starts, now):
    handle.seek(0)
    handle.truncate()
    json.dump({"version": 1, "updated_at": now, "starts": starts[-80:]}, handle, separators=(",", ":"))
    handle.flush()
    try:
        os.fchmod(handle.fileno(), 0o600)
    except OSError:
        pass


def _lock(handle):
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock(handle):
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def acquire_request(*, provider="", now_fn=time.time, sleep_fn=time.sleep):
    """Reserve one NIM request slot and return seconds waited.

    State contains timestamps only. If local persistence fails, fail open so a
    diagnostics helper cannot make a healthy provider unusable.
    """
    if str(provider or "").strip().lower().replace("_", "-") != "admira-nvidia":
        return 0.0
    if str(os.environ.get("ADMIRA_NVIDIA_RATE_LIMIT_DISABLED") or "").strip() == "1":
        return 0.0
    rpm = _positive_int(os.environ.get("ADMIRA_NVIDIA_REQUESTS_PER_MINUTE"), DEFAULT_REQUESTS_PER_MINUTE)
    min_interval = _positive_float(os.environ.get("ADMIRA_NVIDIA_MIN_REQUEST_INTERVAL_SECONDS"), DEFAULT_MIN_INTERVAL_SECONDS)
    path = state_path()
    waited = 0.0
    for _ in range(180):
        now = float(now_fn())
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a+", encoding="utf-8") as handle:
                _lock(handle)
                try:
                    starts = _read_starts(handle, now)
                    interval_wait = max(0.0, starts[-1] + min_interval - now) if starts else 0.0
                    window_wait = max(0.0, starts[0] + WINDOW_SECONDS - now) if len(starts) >= rpm else 0.0
                    delay = max(interval_wait, window_wait)
                    if delay <= 0:
                        starts.append(now)
                        _write_starts(handle, starts, now)
                        return waited
                finally:
                    _unlock(handle)
        except (OSError, ValueError, TypeError):
            return waited
        sleep_for = min(max(delay, 0.05), 5.0)
        sleep_fn(sleep_for)
        waited += sleep_for
    return waited


def recent_request_count(*, now_fn=time.time):
    now = float(now_fn())
    try:
        with state_path().open("a+", encoding="utf-8") as handle:
            _lock(handle)
            try:
                return len(_read_starts(handle, now))
            finally:
                _unlock(handle)
    except OSError:
        return 0

