"""Tenant-side capability client for the central Terra conversation fallback.

It deliberately resembles the small subset of an OpenAI chat client Hermes
uses.  The broker socket and an HMAC capability are enough to make a request;
operator OAuth tokens remain mounted only in the central service.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import socket
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

try:
    from hosted_central_image_client import _canonical, _json_file, _private_file, _tenant
except ModuleNotFoundError:
    from src.hosted_central_image_client import _canonical, _json_file, _private_file, _tenant


MODEL = "admira-terra"
CENTRAL_MODEL = "gpt-5.6-terra"
PURPOSE = "conversation_inference"
MAX_MESSAGES = 96
MAX_TOOLS = 96
MAX_REQUEST = 1024 * 1024
MAX_RESPONSE = 320 * 1024
MAX_PROVIDER_TIMEOUT_SECONDS = 230
TIMEOUT_RESPONSE_RESERVE_SECONDS = 5
_BASE_URL = "http://admira-central.invalid/v1"


class CentralCodexProviderError(RuntimeError):
    """A safe provider-shaped error that lets Hermes continue its chain."""

    def __init__(self, code: str = "provider_failed") -> None:
        self.code = code
        self.status_code = 429 if code in {"tenant_busy", "global_busy"} else 503
        super().__init__("central Codex provider unavailable")


def central_conversation_route() -> str:
    """Return central, blocked, or local without exposing entitlement detail."""
    access = _json_file(Path(os.environ.get(
        "ADMIRA_HOSTED_IMAGE_ACCESS_FILE", "/app/runtime/hosted_image_access.json",
    )))
    if not access:
        return "local"
    route = str(access.get("route") or "")
    if route != "central_sponsored":
        return "local"
    try:
        tenant_id = _tenant(os.environ.get("ADMIRA_TENANT_ID"))
    except ValueError:
        return "blocked"
    if access.get("tenant_id") != tenant_id or access.get("central_ready") is not True:
        return "blocked"
    return "central"


def central_conversation_available() -> bool:
    return central_conversation_route() == "central"


def _json_safe(value: object, *, depth: int = 0) -> object:
    if depth > 12:
        raise ValueError("invalid_request")
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, depth=depth + 1) for item in value]
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return _json_safe(dump(), depth=depth + 1)
    values = getattr(value, "__dict__", None)
    if isinstance(values, dict):
        return _json_safe(values, depth=depth + 1)
    raise ValueError("invalid_request")


def _messages(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not 1 <= len(value) <= MAX_MESSAGES:
        raise ValueError("invalid_request")
    output = []
    for item in value:
        normalized = _json_safe(item)
        if not isinstance(normalized, Mapping):
            raise ValueError("invalid_request")
        role = str(normalized.get("role") or "").strip()
        content = normalized.get("content")
        if role not in {"system", "user", "assistant", "tool"} or content is not None and not isinstance(content, str):
            raise ValueError("invalid_request")
        message: dict[str, Any] = {"role": role, "content": str(content or "")}
        if role == "tool":
            call_id = normalized.get("tool_call_id")
            if not isinstance(call_id, str):
                raise ValueError("invalid_request")
            message["tool_call_id"] = call_id
        if role == "assistant" and normalized.get("tool_calls") is not None:
            calls = _json_safe(normalized.get("tool_calls"))
            if not isinstance(calls, list):
                raise ValueError("invalid_request")
            message["tool_calls"] = calls
        output.append(message)
    if len(_canonical({"messages": output})) > MAX_REQUEST:
        raise ValueError("invalid_request")
    return output


def _tools(value: object) -> list[dict[str, Any]]:
    if value in (None, []):
        return []
    normalized = _json_safe(value)
    if not isinstance(normalized, list) or len(normalized) > MAX_TOOLS:
        raise ValueError("invalid_request")
    tools = [dict(item) for item in normalized if isinstance(item, Mapping)]
    if len(tools) != len(normalized):
        raise ValueError("invalid_request")
    if len(_canonical({"tools": tools})) > MAX_REQUEST:
        raise ValueError("invalid_request")
    return tools


def _tool_choice(value: object) -> object:
    if value is None:
        return None
    try:
        normalized = _json_safe(value)
    except ValueError:
        return None
    return normalized if isinstance(normalized, (str, Mapping)) else None


def _request_id(tenant_id: str, update_id: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
                tool_choice: object) -> str:
    digest = hashlib.sha256(_canonical({
        "tenant_id": tenant_id,
        "update_id": update_id,
        "messages": messages,
        "tools": tools,
        "tool_choice": tool_choice,
        "purpose": PURPOSE,
    })).hexdigest()
    return str(uuid.UUID(hex=digest[:32]))


def _read_response(sock: socket.socket) -> Mapping[str, Any] | None:
    chunks: list[bytes] = []
    size = 0
    while size < MAX_RESPONSE:
        chunk = sock.recv(min(16384, MAX_RESPONSE - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
        if b"\n" in chunk:
            break
    raw = b"".join(chunks)
    if b"\n" not in raw:
        return None
    value = json.loads(raw.split(b"\n", 1)[0])
    return value if isinstance(value, Mapping) else None


def _response(response: Mapping[str, Any], *, tenant_id: str, request_id: str) -> Any:
    if response.get("ok") is not True:
        raise CentralCodexProviderError(str(response.get("error_code") or "provider_failed"))
    if (response.get("tenant_id") != tenant_id or response.get("request_id") != request_id
            or response.get("model") != CENTRAL_MODEL):
        raise CentralCodexProviderError("response_invalid")
    message = response.get("message")
    if not isinstance(message, Mapping):
        raise CentralCodexProviderError("response_invalid")
    content = message.get("content")
    calls = message.get("tool_calls") or []
    if content is not None and not isinstance(content, str) or not isinstance(calls, list):
        raise CentralCodexProviderError("response_invalid")
    tool_calls = []
    for raw in calls:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("id"), str):
            raise CentralCodexProviderError("response_invalid")
        function = raw.get("function")
        if not isinstance(function, Mapping) or not isinstance(function.get("name"), str) or not isinstance(function.get("arguments"), str):
            raise CentralCodexProviderError("response_invalid")
        tool_calls.append(SimpleNamespace(
            id=raw["id"],
            type="function",
            function=SimpleNamespace(name=function["name"], arguments=function["arguments"]),
        ))
    finish_reason = str(response.get("finish_reason") or "")
    if finish_reason not in {"stop", "tool_calls"}:
        raise CentralCodexProviderError("response_invalid")
    choice = SimpleNamespace(
        index=0,
        message=SimpleNamespace(content=str(content or ""), tool_calls=tool_calls, refusal=None),
        finish_reason=finish_reason,
    )
    return SimpleNamespace(
        id=f"admira-central-{request_id[:12]}",
        object="chat.completion",
        model=MODEL,
        choices=[choice],
        usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0),
    )


class _CentralCompletions:
    def create(self, **kwargs: Any) -> Any:
        if central_conversation_route() != "central":
            raise CentralCodexProviderError("entitlement_blocked")
        if str(kwargs.get("model") or "") != MODEL:
            raise CentralCodexProviderError("invalid_request")
        try:
            messages = _messages(kwargs.get("messages"))
            tools = _tools(kwargs.get("tools"))
            choice = _tool_choice(kwargs.get("tool_choice"))
            timeout = max(1.0, min(float(kwargs.get("timeout") or 240), 300.0))
            tenant_id = _tenant(os.environ.get("ADMIRA_TENANT_ID"))
            access = _json_file(Path(os.environ.get(
                "ADMIRA_HOSTED_IMAGE_ACCESS_FILE", "/app/runtime/hosted_image_access.json",
            ))) or {}
            update_id = str(access.get("update_id") or "")
            request_id = _request_id(tenant_id, update_id, messages, tools, choice)
            key = _private_file(Path(os.environ.get(
                "ADMIRA_CENTRAL_IMAGE_CLIENT_KEY_FILE", "/app/runtime/central_image_client.key",
            )), 32)
            socket_path = Path(os.environ.get(
                "ADMIRA_CENTRAL_CONVERSATION_SOCKET", "/run/admira-central-image-broker/conversation.sock",
            ))
            provider_timeout = max(1, min(
                int(timeout) - TIMEOUT_RESPONSE_RESERVE_SECONDS,
                MAX_PROVIDER_TIMEOUT_SECONDS,
            ))
            body = {
                "tenant_id": tenant_id,
                "request_id": request_id,
                "purpose": PURPOSE,
                "messages": messages,
                "tools": tools,
                "tool_choice": choice,
                "update_id": update_id,
                "timeout_seconds": provider_timeout,
            }
            envelope = {
                "timestamp": int(time.time()),
                "nonce": secrets.token_hex(16),
                "body": body,
            }
            envelope["signature"] = hmac.new(key, _canonical(envelope), hashlib.sha256).hexdigest()
            line = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
            if len(line) > MAX_REQUEST:
                raise ValueError("invalid_request")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect(str(socket_path))
                sock.sendall(line)
                response = _read_response(sock)
            if response is None:
                raise CentralCodexProviderError("provider_failed")
            return _response(response, tenant_id=tenant_id, request_id=request_id)
        except CentralCodexProviderError:
            raise
        except (OSError, socket.timeout, socket.error, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
            raise CentralCodexProviderError("provider_failed") from None


class _CentralChat:
    def __init__(self) -> None:
        self.completions = _CentralCompletions()


class CentralCodexRuntimeClient:
    """OpenAI-shaped runtime client whose only transport is the Unix socket."""

    api_key = "admira-central-capability"
    base_url = _BASE_URL

    def __init__(self) -> None:
        self.chat = _CentralChat()

    def close(self) -> None:
        return None


def central_codex_runtime_client(*, model: str = MODEL) -> tuple[CentralCodexRuntimeClient | None, str | None]:
    if model != MODEL or not central_conversation_available():
        return None, None
    return CentralCodexRuntimeClient(), MODEL


__all__ = [
    "CentralCodexProviderError", "CentralCodexRuntimeClient", "MODEL",
    "central_codex_runtime_client", "central_conversation_available", "central_conversation_route",
]
