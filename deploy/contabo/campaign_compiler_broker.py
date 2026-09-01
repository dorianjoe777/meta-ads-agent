#!/usr/bin/env python3
"""Synchronous, provider-neutral broker for tenant campaign compilation.

The broker intentionally has no network, Meta, filesystem, or prompt storage
responsibility.  Keys, entitlements, schemas, and compilation are injected by
the server-side caller.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any


MODEL = "gpt-5.6-terra"
PURPOSE = "campaign_compile"
MAX_PROMPT = 100_000
MAX_RESPONSE_BYTES = 1_000_000
MAX_PROVIDER_TIMEOUT_SECONDS = 230
TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")
REQUEST_RE = re.compile(r"^[A-Za-z0-9_-]{8,96}$")
NONCE_RE = re.compile(r"^[a-f0-9]{32,128}$")

ALLOWED_TOOLS = frozenset({
    "admira_create_whatsapp_campaign", "admira_create_lead_form_campaign",
    "admira_create_website_campaign", "admira_create_messaging_campaign",
    "admira_create_app_campaign", "admira_create_on_meta_campaign",
    "create_whatsapp_campaign", "create_lead_form_campaign",
    "create_website_campaign", "create_messaging_campaign",
    "create_app_campaign", "create_on_meta_campaign",
})
SAFE_ERRORS = frozenset({
    "invalid_request", "invalid_signature", "expired_request", "replayed_request",
    "entitlement_blocked", "tool_not_allowed", "tenant_busy", "global_busy",
    "schema_failed", "provider_failed", "compiled_invalid", "response_too_large",
    "tenant_not_found", "internal_error",
})

_SECRET_PATTERNS = (
    re.compile(r"\bbearer\s+[a-z0-9._~+/=-]{8,}", re.I),
    re.compile(r"\b(?:access|refresh)[_-]?token\b\s*[:=]\s*\S+", re.I),
    re.compile(r"\bsk-[a-z0-9_-]{8,}", re.I),
    re.compile(r"\bey[a-z0-9_-]{4,}\.[a-z0-9_-]{4,}\.[a-z0-9_-]{4,}\b", re.I),
)


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sign_request(key: bytes, body: Mapping[str, Any], *, timestamp: int | None = None,
                 nonce: str | None = None) -> dict[str, Any]:
    """Create a protocol envelope; clients must sign the complete request body."""
    envelope: dict[str, Any] = {
        "timestamp": int(time.time() if timestamp is None else timestamp),
        "nonce": nonce or secrets.token_hex(16),
        "body": dict(body),
    }
    envelope["signature"] = hmac.new(key, _canonical(envelope), hashlib.sha256).hexdigest()
    return envelope


def validate_tenant_id(value: object) -> str:
    tenant_id = str(value or "")
    if not TENANT_RE.fullmatch(tenant_id):
        raise ValueError("invalid_request")
    return tenant_id


def _contains_secret(value: Any) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _SECRET_PATTERNS)
    if isinstance(value, Mapping):
        return any(_contains_secret(k) or _contains_secret(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_secret(item) for item in value)
    return False


class CampaignCompilerBroker:
    """Authenticate and synchronously dispatch one campaign compilation."""

    def __init__(self, tenant_keys: Mapping[str, bytes] | Callable[[str], bytes],
                 schema_callback: Callable[[str], Mapping[str, Any]],
                 entitlement_callback: Callable[[str, str], str],
                 provider_callback: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]],
                 *, max_global: int = 4, freshness_seconds: int = 90,
                 max_response_bytes: int = MAX_RESPONSE_BYTES) -> None:
        if max_global < 1 or freshness_seconds < 1 or max_response_bytes < 1:
            raise ValueError("invalid_request")
        self.tenant_keys = tenant_keys
        self.schema_callback = schema_callback
        self.entitlement_callback = entitlement_callback
        self.provider_callback = provider_callback
        self.max_global = max_global
        self.freshness_seconds = freshness_seconds
        self.max_response_bytes = max_response_bytes
        self._lock = threading.RLock()
        self._seen: dict[tuple[str, str], int] = {}
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._active: dict[str, int] = {}
        self._global_active = 0

    def _key(self, tenant_id: str) -> bytes:
        try:
            key = self.tenant_keys(tenant_id) if callable(self.tenant_keys) else self.tenant_keys[tenant_id]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("tenant_not_found") from exc
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("tenant_not_found")
        return key

    def _authenticate(self, envelope: object, *, now: int | None) -> tuple[str, str, dict[str, Any]]:
        if not isinstance(envelope, dict):
            raise ValueError("invalid_request")
        try:
            timestamp = int(envelope["timestamp"])
            nonce = envelope["nonce"]
            body = envelope["body"]
            signature = envelope["signature"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid_request") from exc
        current = int(time.time() if now is None else now)
        if abs(current - timestamp) > self.freshness_seconds:
            raise ValueError("expired_request")
        if not isinstance(nonce, str) or not NONCE_RE.fullmatch(nonce) or not isinstance(body, dict):
            raise ValueError("invalid_request")
        tenant_id = validate_tenant_id(body.get("tenant_id"))
        if not isinstance(signature, str) or not hmac.compare_digest(
                signature, hmac.new(self._key(tenant_id), _canonical({
                    "timestamp": timestamp, "nonce": nonce, "body": body}), hashlib.sha256).hexdigest()):
            raise ValueError("invalid_signature")
        request_id = body.get("request_id")
        if not isinstance(request_id, str) or not REQUEST_RE.fullmatch(request_id):
            raise ValueError("invalid_request")
        with self._lock:
            cutoff = current - self.freshness_seconds * 2
            self._seen = {key: seen for key, seen in self._seen.items() if seen >= cutoff}
            replay_key = (tenant_id, nonce)
            if replay_key in self._seen:
                raise ValueError("replayed_request")
            self._seen[replay_key] = current
            cached = self._cache.get((tenant_id, request_id))
        return tenant_id, request_id, (cached if cached is not None else body)

    def submit(self, envelope: object, *, now: int | None = None) -> dict[str, Any]:
        tenant_id = request_id = None
        try:
            tenant_id, request_id, body_or_cached = self._authenticate(envelope, now=now)
            if isinstance(body_or_cached, dict) and body_or_cached.get("ok") is True:
                return dict(body_or_cached)
            body = body_or_cached
            if body.get("purpose") != PURPOSE or not isinstance(body.get("prompt"), str):
                raise ValueError("invalid_request")
            if not body["prompt"].strip() or len(body["prompt"]) > MAX_PROMPT:
                raise ValueError("invalid_request")
            tool = body.get("tool")
            if not isinstance(tool, str) or tool not in ALLOWED_TOOLS:
                raise ValueError("tool_not_allowed")
            timeout_seconds = body.get("timeout_seconds", MAX_PROVIDER_TIMEOUT_SECONDS)
            if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int)
                    or not 1 <= timeout_seconds <= MAX_PROVIDER_TIMEOUT_SECONDS):
                raise ValueError("invalid_request")
            if self.entitlement_callback(tenant_id, PURPOSE) != "central_sponsored":
                raise ValueError("entitlement_blocked")
            with self._lock:
                if self._active.get(tenant_id, 0) >= 1:
                    raise ValueError("tenant_busy")
                if self._global_active >= self.max_global:
                    raise ValueError("global_busy")
                self._active[tenant_id] = self._active.get(tenant_id, 0) + 1
                self._global_active += 1
            try:
                schema = self.schema_callback(tool)
                if not isinstance(schema, Mapping):
                    raise ValueError("schema_failed")
                compiled = self.provider_callback({
                    "tool": tool,
                    "prompt": body["prompt"],
                    "purpose": PURPOSE,
                    "timeout_seconds": timeout_seconds,
                }, schema)
                if not isinstance(compiled, Mapping) or _contains_secret(compiled):
                    raise ValueError("compiled_invalid")
                result = {"ok": True, "tenant_id": tenant_id, "request_id": request_id,
                          "model": MODEL, "compiled": dict(compiled)}
                if len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()) > self.max_response_bytes:
                    raise ValueError("response_too_large")
                with self._lock:
                    self._cache[(tenant_id, request_id)] = result
                return dict(result)
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError("provider_failed") from exc
            finally:
                with self._lock:
                    self._active[tenant_id] -= 1
                    self._global_active -= 1
        except ValueError as exc:
            code = str(exc) if str(exc) in SAFE_ERRORS else "internal_error"
            result: dict[str, Any] = {"ok": False, "error_code": code}
            if tenant_id is not None:
                result["tenant_id"] = tenant_id
            if request_id is not None:
                result["request_id"] = request_id
            return result
        except Exception:
            return {"ok": False, "error_code": "internal_error"}


__all__ = [
    "ALLOWED_TOOLS", "CampaignCompilerBroker", "MAX_PROVIDER_TIMEOUT_SECONDS",
    "MODEL", "PURPOSE", "SAFE_ERRORS", "sign_request",
]
