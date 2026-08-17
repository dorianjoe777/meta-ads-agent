#!/usr/bin/env python3
"""Security helpers for Admira IA."""
import base64
import hashlib
import hmac
import secrets
import stat
from pathlib import Path


SENSITIVE_KEY_PARTS = ("secret", "password", "api_key", "access_key")
SENSITIVE_KEY_NAMES = {"token", "access_token", "dashboard_token", "dashboard_password", "license_key", "meta_access_token", "telegram_bot_token", "gemini_api_key"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
PUBLIC_HOSTS = {"", "0.0.0.0", "::"}
PASSWORD_HASH_PREFIX = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 260_000


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
    provided = str(provided or "")
    password_hash = str(getattr(config, "dashboard_password_hash", "") or "")
    if password_hash and verify_dashboard_password_hash(password_hash, provided):
        return True
    if config.dashboard_token and hmac.compare_digest(provided, str(config.dashboard_token)):
        return True
    return False


def dashboard_password_configured(config):
    return bool(
        str(getattr(config, "dashboard_password_hash", "") or "")
        or str(getattr(config, "dashboard_password", "") or "")
        or str(getattr(config, "dashboard_token", "") or "")
    )


def hash_dashboard_password(password):
    password = str(password or "")
    salt = secrets.token_urlsafe(18)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_HASH_ITERATIONS,
    )
    encoded = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"{PASSWORD_HASH_PREFIX}${PASSWORD_HASH_ITERATIONS}${salt}${encoded}"


def verify_dashboard_password_hash(encoded, password):
    try:
        prefix, iterations, salt, stored = str(encoded or "").split("$", 3)
        if prefix != PASSWORD_HASH_PREFIX:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            str(password or "").encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        )
        candidate = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return hmac.compare_digest(candidate, stored)
    except (TypeError, ValueError, OverflowError):
        return False


def permission_detail(path):
    path = Path(path)
    if not path.exists():
        return {"exists": False, "mode": "", "private": False}
    mode = stat.S_IMODE(path.stat().st_mode)
    return {"exists": True, "mode": oct(mode), "private": (mode & 0o077) == 0}
