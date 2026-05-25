#!/usr/bin/env python3
"""Security helpers for the self-hosted Meta Ads Agent."""
import hmac
import stat
from pathlib import Path


SENSITIVE_KEY_PARTS = ("secret", "password", "api_key", "access_key")
SENSITIVE_KEY_NAMES = {"token", "access_token", "dashboard_token", "dashboard_password", "license_key", "meta_access_token", "telegram_bot_token", "gemini_api_key"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
PUBLIC_HOSTS = {"", "0.0.0.0", "::"}


def redact(value):
    if not value:
        return value
    return "configured"


def redact_payload(payload):
    if isinstance(payload, dict):
        redacted = {}
        for key, value in payload.items():
            key_lower = key.lower()
            if key_lower in SENSITIVE_KEY_NAMES or key_lower.endswith("_token") or any(part in key_lower for part in SENSITIVE_KEY_PARTS):
                redacted[key] = redact(value)
            else:
                redacted[key] = redact_payload(value)
        return redacted
    if isinstance(payload, list):
        return [redact_payload(item) for item in payload]
    return payload


def is_local_host(host):
    return str(host or "").strip().lower() in LOCAL_HOSTS


def is_public_bind(host):
    normalized = str(host or "").strip().lower()
    return normalized in PUBLIC_HOSTS or not is_local_host(normalized)


def dashboard_token_valid(config, provided):
    if not config.dashboard_token_required:
        return True
    if not config.dashboard_token:
        return False
    return hmac.compare_digest(str(provided or ""), str(config.dashboard_token))


def permission_detail(path):
    path = Path(path)
    if not path.exists():
        return {"exists": False, "mode": "", "private": False}
    mode = stat.S_IMODE(path.stat().st_mode)
    return {"exists": True, "mode": oct(mode), "private": (mode & 0o077) == 0}
