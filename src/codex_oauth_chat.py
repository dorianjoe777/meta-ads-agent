"""Narrow Hermes/Codex-OAuth transport for central conversational fallback.

The hosted tenant never mounts an operator OAuth token.  A central account
slot runs this helper in a short-lived Hermes Python process and exposes only
one structured assistant message to the signed Unix-socket broker.  In
particular, this is *not* a ``codex exec`` wrapper.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


MAX_MESSAGES_BYTES = 900 * 1024
MAX_TOOLS_BYTES = 160 * 1024
MAX_RESPONSE_BYTES = 320 * 1024
MAX_TOOL_CALLS = 16
SAFE_FAILURE_CATEGORIES = frozenset({
    "provider_auth",
    "provider_failed",
    "provider_limited",
    "provider_timeout",
    "provider_unavailable",
    "output_invalid",
})


# The bridge owns authentication state only inside the protected Hermes home.
# It emits exactly one compact JSON line.  Neither diagnostics nor OAuth
# material can cross this process boundary.
HERMES_CODEX_OAUTH_CHAT_BRIDGE = r'''
import json
import re
import sys
from codex_oauth_session import mirror_back_to_root, prepare_hermes_oauth


MAX_CONTENT = 240000
MAX_ARGUMENTS = 65536
MAX_TOOL_CALLS = 16
TOOL_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,127}$")
TOOL_CALL_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def respond(value):
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def classify(exc):
    text = str(exc or "").lower()
    if "timeout" in text or "timed out" in text:
        return "provider_timeout"
    if any(token in text for token in ("unauthorized", "authentication", "auth", "token", "login")):
        return "provider_auth"
    if any(token in text for token in ("rate limit", "quota", "usage limit", "429", "limit reached")):
        return "provider_limited"
    if any(token in text for token in ("unavailable", "overloaded", "connection", "503")):
        return "provider_unavailable"
    return "provider_failed"


def tool_names(tools):
    names = set()
    for item in tools:
        function = item.get("function") if isinstance(item, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        if isinstance(name, str) and TOOL_NAME.fullmatch(name):
            names.add(name)
    return names


def normalize_tool_calls(raw, allowed):
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)) or len(raw) > MAX_TOOL_CALLS:
        raise ValueError("output_invalid")
    result = []
    for item in raw:
        function = getattr(item, "function", None)
        name = getattr(function, "name", None)
        arguments = getattr(function, "arguments", None)
        call_id = getattr(item, "id", None)
        if (not isinstance(name, str) or name not in allowed or not TOOL_NAME.fullmatch(name)
                or not isinstance(arguments, str) or len(arguments) > MAX_ARGUMENTS
                or not isinstance(call_id, str) or not TOOL_CALL_ID.fullmatch(call_id)):
            raise ValueError("output_invalid")
        try:
            parsed = json.loads(arguments)
        except Exception as exc:
            raise ValueError("output_invalid") from exc
        if not isinstance(parsed, (dict, list)):
            raise ValueError("output_invalid")
        result.append({
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": arguments},
        })
    return result


try:
    payload = json.loads(sys.stdin.read() or "{}")
    if not isinstance(payload, dict):
        raise ValueError("invalid_request")
    model = str(payload.get("model") or "").strip()
    messages = payload.get("messages")
    tools = payload.get("tools") or []
    tool_choice = payload.get("tool_choice")
    timeout = float(payload.get("timeout") or 0)
    if (not model or not isinstance(messages, list) or not messages
            or not isinstance(tools, list) or timeout <= 0):
        raise ValueError("invalid_request")
    allowed = tool_names(tools)
    auth_path = prepare_hermes_oauth()
    client = None
    try:
        from hermes_cli.auth import resolve_codex_runtime_credentials
        resolve_codex_runtime_credentials(refresh_if_expiring=True)
        from agent.auxiliary_client import _build_codex_client
        client, selected_model = _build_codex_client(model)
        if client is None or not selected_model:
            raise RuntimeError("provider_auth")
        request = {"model": selected_model, "messages": messages, "timeout": timeout}
        if tools:
            request["tools"] = tools
        if tool_choice is not None:
            request["tool_choice"] = tool_choice
        request["extra_body"] = {"reasoning": {"effort": "medium"}}
        response = client.chat.completions.create(**request)
        raw_message = response.choices[0].message
        content = getattr(raw_message, "content", None)
        if content is not None and not isinstance(content, str):
            raise ValueError("output_invalid")
        content = str(content or "")
        if len(content) > MAX_CONTENT:
            raise ValueError("output_invalid")
        calls = normalize_tool_calls(getattr(raw_message, "tool_calls", None), allowed)
        if not content.strip() and not calls:
            raise ValueError("output_invalid")
        finish_reason = str(getattr(response.choices[0], "finish_reason", "") or "")
        if finish_reason not in {"stop", "tool_calls"}:
            finish_reason = "tool_calls" if calls else "stop"
        respond({
            "ok": True,
            "model": selected_model,
            "finish_reason": finish_reason,
            "message": {"role": "assistant", "content": content, "tool_calls": calls},
        })
    finally:
        if client is not None:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        mirror_back_to_root(auth_path)
except Exception as exc:
    if isinstance(exc, ValueError) and str(exc) in {"invalid_request", "output_invalid"}:
        category = "output_invalid"
    else:
        category = classify(exc)
    respond({"ok": False, "failure_category": category})
'''


def _failure_category(value: object) -> str:
    candidate = str(value or "provider_failed").strip().lower()
    return candidate if candidate in SAFE_FAILURE_CATEGORIES else "provider_failed"


def _response_from_stdout(stdout: str, *, model: str) -> dict[str, Any]:
    raw = str(stdout or "").strip()
    if len(raw.encode("utf-8", errors="replace")) > MAX_RESPONSE_BYTES:
        return {"ok": False, "failure_category": "provider_failed", "model": model}
    last_line = next((line for line in reversed(raw.splitlines()) if line.lstrip().startswith("{")), "")
    try:
        result = json.loads(last_line) if last_line else {}
    except json.JSONDecodeError:
        result = {}
    if not isinstance(result, dict):
        result = {}
    message = result.get("message")
    if result.get("ok") is True and isinstance(message, Mapping):
        return {
            "ok": True,
            "model": model,
            "finish_reason": str(result.get("finish_reason") or "stop"),
            "message": dict(message),
            "provider": "openai-codex-oauth",
        }
    return {
        "ok": False,
        "model": model,
        "failure_category": _failure_category(result.get("failure_category")),
        "provider": "openai-codex-oauth",
    }


def chat_with_codex_oauth(
    messages: Sequence[Mapping[str, Any]],
    *,
    tools: Sequence[Mapping[str, Any]] | None = None,
    tool_choice: object = None,
    model: str,
    timeout: int | float,
    hermes_home: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Run one safe chat-completion through an already-authorized OAuth slot."""
    selected_model = str(model or "").strip()
    if not selected_model or not isinstance(messages, Sequence) or not messages:
        return {"ok": False, "model": selected_model, "failure_category": "provider_failed"}
    try:
        request_messages = [dict(item) for item in messages if isinstance(item, Mapping)]
        request_tools = [dict(item) for item in (tools or []) if isinstance(item, Mapping)]
        encoded_messages = json.dumps(request_messages, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encoded_tools = json.dumps(request_tools, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError):
        return {"ok": False, "model": selected_model, "failure_category": "provider_failed"}
    if (len(request_messages) != len(messages) or len(encoded_messages) > MAX_MESSAGES_BYTES
            or len(encoded_tools) > MAX_TOOLS_BYTES):
        return {"ok": False, "model": selected_model, "failure_category": "provider_failed"}
    try:
        timeout_seconds = max(1.0, min(float(timeout), 300.0))
    except (TypeError, ValueError):
        timeout_seconds = 1.0
    environment = os.environ.copy()
    if hermes_home:
        home = Path(hermes_home).expanduser()
        environment["HERMES_HOME"] = str(home)
        environment["CODEX_HOME"] = str(home)
    payload = json.dumps({
        "messages": request_messages,
        "tools": request_tools,
        "tool_choice": tool_choice,
        "model": selected_model,
        "timeout": timeout_seconds,
    }, ensure_ascii=False, separators=(",", ":"))
    try:
        completed = subprocess.run(
            [sys.executable, "-c", HERMES_CODEX_OAUTH_CHAT_BRIDGE],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 5,
            check=False,
            env=environment,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False, "model": selected_model,
            "failure_category": "provider_timeout", "provider": "openai-codex-oauth",
        }
    except (OSError, ValueError):
        return {
            "ok": False, "model": selected_model,
            "failure_category": "provider_failed", "provider": "openai-codex-oauth",
        }
    return _response_from_stdout(completed.stdout, model=selected_model)


__all__ = ["chat_with_codex_oauth"]
