#!/usr/bin/env python3
"""Signed, bounded Unix-socket broker for central Codex conversation fallback.

This is intentionally narrower than a general model proxy.  It has no HTTP
listener, no tenant filesystem access and no persistence of prompts or model
responses.  A tenant can ask the central OAuth pool for one normalized chat
completion only when the service rechecks its central-sponsored entitlement.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

try:
    from campaign_compiler_broker import (
        NONCE_RE,
        REQUEST_RE,
        _canonical,
        _contains_secret,
        sign_request,
        validate_tenant_id,
    )
except ImportError:  # package imports used by tests
    from deploy.contabo.campaign_compiler_broker import (
        NONCE_RE,
        REQUEST_RE,
        _canonical,
        _contains_secret,
        sign_request,
        validate_tenant_id,
    )
import hashlib
import hmac


MODEL = "gpt-5.6-terra"
PURPOSE = "conversation_inference"
MAX_MESSAGES = 96
MAX_TOOLS = 96
MAX_MESSAGE_BYTES = 900 * 1024
MAX_TOOLS_BYTES = 160 * 1024
MAX_RESPONSE_BYTES = 320 * 1024
MAX_PROVIDER_TIMEOUT_SECONDS = 230
TOOL_CALL_LIMIT = 16
TOOL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,127}$")
TOOL_CALL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
ALLOWED_ROLES = frozenset({"system", "user", "assistant", "tool"})
SAFE_ERRORS = frozenset({
    "invalid_request", "invalid_signature", "expired_request", "replayed_request",
    "entitlement_blocked", "tenant_busy", "global_busy", "provider_failed",
    "response_invalid", "response_too_large", "tenant_not_found", "internal_error",
})


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _message_input(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("invalid_request")
    role = str(value.get("role") or "").strip()
    if role not in ALLOWED_ROLES:
        raise ValueError("invalid_request")
    # The fallback only serves text model turns.  The primary Gemini path
    # retains multimodal support; transporting arbitrary image bodies through
    # a shared OAuth pool would weaken the tenant boundary.
    content = value.get("content")
    if content is not None and not isinstance(content, str):
        raise ValueError("invalid_request")
    result: dict[str, Any] = {"role": role, "content": str(content or "")}
    if role == "tool":
        tool_call_id = value.get("tool_call_id")
        if not isinstance(tool_call_id, str) or not TOOL_CALL_ID_RE.fullmatch(tool_call_id):
            raise ValueError("invalid_request")
        result["tool_call_id"] = tool_call_id
    if role == "assistant" and value.get("tool_calls") is not None:
        raw_calls = value.get("tool_calls")
        if not isinstance(raw_calls, list) or len(raw_calls) > TOOL_CALL_LIMIT:
            raise ValueError("invalid_request")
        calls = []
        for raw in raw_calls:
            if not isinstance(raw, Mapping):
                raise ValueError("invalid_request")
            function = raw.get("function")
            call_id = raw.get("id")
            if not isinstance(function, Mapping) or not isinstance(call_id, str) or not TOOL_CALL_ID_RE.fullmatch(call_id):
                raise ValueError("invalid_request")
            name = function.get("name")
            arguments = function.get("arguments")
            if (not isinstance(name, str) or not TOOL_NAME_RE.fullmatch(name)
                    or not isinstance(arguments, str) or len(arguments) > 65536):
                raise ValueError("invalid_request")
            try:
                parsed_arguments = json.loads(arguments)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("invalid_request") from exc
            if not isinstance(parsed_arguments, (dict, list)):
                raise ValueError("invalid_request")
            calls.append({
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            })
        result["tool_calls"] = calls
    return result


def _tools_input(value: object) -> tuple[list[dict[str, Any]], set[str]]:
    if value is None:
        return [], set()
    if not isinstance(value, list) or len(value) > MAX_TOOLS:
        raise ValueError("invalid_request")
    tools: list[dict[str, Any]] = []
    names: set[str] = set()
    for raw in value:
        if not isinstance(raw, Mapping) or raw.get("type") != "function":
            raise ValueError("invalid_request")
        function = raw.get("function")
        if not isinstance(function, Mapping):
            raise ValueError("invalid_request")
        name = function.get("name")
        parameters = function.get("parameters")
        if (not isinstance(name, str) or not TOOL_NAME_RE.fullmatch(name) or name in names
                or not isinstance(parameters, Mapping)):
            raise ValueError("invalid_request")
        try:
            safe_function = {
                "name": name,
                "description": str(function.get("description") or "")[:8000],
                "parameters": json.loads(_json_bytes(dict(parameters)).decode("utf-8")),
            }
        except (TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid_request") from exc
        names.add(name)
        tools.append({"type": "function", "function": safe_function})
    if len(_json_bytes(tools)) > MAX_TOOLS_BYTES:
        raise ValueError("invalid_request")
    return tools, names


def _tool_choice_input(value: object, names: set[str]) -> str | dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        if value in {"auto", "none", "required"}:
            return value
        raise ValueError("invalid_request")
    if not isinstance(value, Mapping) or value.get("type") != "function":
        raise ValueError("invalid_request")
    function = value.get("function")
    name = function.get("name") if isinstance(function, Mapping) else None
    if not isinstance(name, str) or name not in names:
        raise ValueError("invalid_request")
    return {"type": "function", "function": {"name": name}}


def _provider_message(value: object, *, allowed_tools: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("response_invalid")
    content = value.get("content")
    if content is not None and not isinstance(content, str):
        raise ValueError("response_invalid")
    output = {"role": "assistant", "content": str(content or "")}
    raw_calls = value.get("tool_calls") or []
    if not isinstance(raw_calls, list) or len(raw_calls) > TOOL_CALL_LIMIT:
        raise ValueError("response_invalid")
    calls = []
    for raw in raw_calls:
        if not isinstance(raw, Mapping):
            raise ValueError("response_invalid")
        function = raw.get("function")
        call_id = raw.get("id")
        name = function.get("name") if isinstance(function, Mapping) else None
        arguments = function.get("arguments") if isinstance(function, Mapping) else None
        if (not isinstance(call_id, str) or not TOOL_CALL_ID_RE.fullmatch(call_id)
                or not isinstance(name, str) or name not in allowed_tools
                or not isinstance(arguments, str) or len(arguments) > 65536):
            raise ValueError("response_invalid")
        try:
            parsed_arguments = json.loads(arguments)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("response_invalid") from exc
        if not isinstance(parsed_arguments, (dict, list)):
            raise ValueError("response_invalid")
        calls.append({
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": arguments},
        })
    output["tool_calls"] = calls
    if not output["content"].strip() and not calls:
        raise ValueError("response_invalid")
    if _contains_secret(output):
        raise ValueError("response_invalid")
    if len(_json_bytes(output)) > MAX_RESPONSE_BYTES:
        raise ValueError("response_too_large")
    return output


class ConversationBroker:
    """Authenticate and dispatch a single central Terra completion."""

    def __init__(
        self,
        tenant_keys: Mapping[str, bytes] | Callable[[str], bytes],
        entitlement_callback: Callable[[str, str], str],
        provider_callback: Callable[..., Mapping[str, Any]],
        *,
        max_global: int = 2,
        freshness_seconds: int = 90,
    ) -> None:
        if max_global < 1 or freshness_seconds < 1:
            raise ValueError("invalid_request")
        self.tenant_keys = tenant_keys
        self.entitlement_callback = entitlement_callback
        self.provider_callback = provider_callback
        self.max_global = max_global
        self.freshness_seconds = freshness_seconds
        self._lock = threading.RLock()
        self._seen: dict[tuple[str, str], int] = {}
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
        if not isinstance(envelope, Mapping):
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
        if not isinstance(nonce, str) or not NONCE_RE.fullmatch(nonce) or not isinstance(body, Mapping):
            raise ValueError("invalid_request")
        tenant_id = validate_tenant_id(body.get("tenant_id"))
        expected = hmac.new(self._key(tenant_id), _canonical({
            "timestamp": timestamp, "nonce": nonce, "body": dict(body),
        }), hashlib.sha256).hexdigest()
        if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
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
        return tenant_id, request_id, dict(body)

    def submit(self, envelope: object, *, now: int | None = None) -> dict[str, Any]:
        tenant_id = request_id = None
        entered = False
        try:
            tenant_id, request_id, body = self._authenticate(envelope, now=now)
            if body.get("purpose") != PURPOSE:
                raise ValueError("invalid_request")
            messages = body.get("messages")
            if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_MESSAGES:
                raise ValueError("invalid_request")
            safe_messages = [_message_input(item) for item in messages]
            if len(_json_bytes(safe_messages)) > MAX_MESSAGE_BYTES:
                raise ValueError("invalid_request")
            safe_tools, tool_names = _tools_input(body.get("tools"))
            safe_tool_choice = _tool_choice_input(body.get("tool_choice"), tool_names)
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
                entered = True
            result = self.provider_callback(
                safe_messages,
                tools=safe_tools,
                tool_choice=safe_tool_choice,
                timeout=timeout_seconds,
            )
            if not isinstance(result, Mapping) or result.get("ok") is not True:
                raise ValueError("provider_failed")
            message = _provider_message(result.get("message"), allowed_tools=tool_names)
            finish_reason = str(result.get("finish_reason") or "")
            if finish_reason not in {"stop", "tool_calls"}:
                finish_reason = "tool_calls" if message["tool_calls"] else "stop"
            response = {
                "ok": True,
                "tenant_id": tenant_id,
                "request_id": request_id,
                "model": MODEL,
                "finish_reason": finish_reason,
                "message": message,
            }
            if len(_json_bytes(response)) > MAX_RESPONSE_BYTES:
                raise ValueError("response_too_large")
            return response
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
        finally:
            if entered and tenant_id is not None:
                with self._lock:
                    self._active[tenant_id] -= 1
                    self._global_active -= 1


__all__ = [
    "ConversationBroker", "MAX_PROVIDER_TIMEOUT_SECONDS", "MODEL", "PURPOSE",
    "SAFE_ERRORS", "sign_request",
]
