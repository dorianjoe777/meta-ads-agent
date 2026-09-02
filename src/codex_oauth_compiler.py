"""Small, structured Codex-OAuth compiler for high-value Admira actions.

Campaign compilation must be able to use an authenticated Codex *OAuth*
session without invoking the ``codex`` executable.  The helper deliberately
has a narrow, JSON-only protocol: it runs inside the Hermes Python runtime,
returns no provider diagnostics, and accepts no tools or filesystem access.

Hosted central slots still store the original Codex session at the root of a
private ``auth.json``.  Hermes stores its equivalent provider state below
``providers.openai-codex``.  The bridge mirrors that already-authorized token
shape inside the same private file immediately before and after a request so
the two runtimes cannot drift into separate refresh-token chains.  The
central account-pool lock serializes all work per slot.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping


MAX_PROMPT_BYTES = 128 * 1024
MAX_SCHEMA_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
SAFE_FAILURE_CATEGORIES = frozenset({
    "provider_auth",
    "provider_failed",
    "provider_limited",
    "provider_timeout",
    "provider_unavailable",
    "output_invalid",
})


# This is intentionally a Python/Hermes bridge, not a ``codex exec`` wrapper.
# It writes only one compact JSON line to stdout; errors and provider output
# never cross this process boundary.  The outer helper also refuses any
# malformed or oversized response before returning it to the caller.
HERMES_CODEX_OAUTH_COMPILER_BRIDGE = r'''
import json
import os
import sys
from codex_oauth_session import mirror_back_to_root, prepare_hermes_oauth


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
    if any(token in text for token in ("unavailable", "overloaded", "connection")):
        return "provider_unavailable"
    return "provider_failed"


try:
    payload = json.loads(sys.stdin.read() or "{}")
    if not isinstance(payload, dict):
        raise ValueError("invalid_request")
    model = str(payload.get("model") or "").strip()
    prompt = str(payload.get("prompt") or "").strip()
    schema = payload.get("schema")
    timeout = float(payload.get("timeout") or 0)
    if not model or not prompt or not isinstance(schema, dict) or timeout <= 0:
        raise ValueError("invalid_request")
    auth_path = prepare_hermes_oauth()
    client = None
    try:
        from hermes_cli.auth import resolve_codex_runtime_credentials
        resolve_codex_runtime_credentials(refresh_if_expiring=True)
        from agent.auxiliary_client import _build_codex_client
        client, selected_model = _build_codex_client(model)
        if client is None or not selected_model:
            raise RuntimeError("provider_auth")
        system = (
            "You are Admira's structured campaign compiler. Return exactly one JSON object, "
            "with no Markdown, no prose, and no tool calls. The object must satisfy this JSON Schema: "
            + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        )
        response = client.chat.completions.create(
            model=selected_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            timeout=timeout,
            extra_body={"reasoning": {"effort": "medium"}},
        )
        content = str(response.choices[0].message.content or "").strip()
        if content.startswith("```"):
            content = content.split("\\n", 1)[1] if "\\n" in content else ""
            if content.rstrip().endswith("```"):
                content = content.rstrip()[:-3].rstrip()
        compiled = json.loads(content)
        if not isinstance(compiled, dict):
            raise ValueError("output_invalid")
    finally:
        if client is not None:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        # ``resolve_codex_runtime_credentials`` may refresh before a provider
        # error. Persist that refresh even when the call itself fails so the
        # next pooled request does not resume with an old root token.
        mirror_back_to_root(auth_path)
    respond({"ok": True, "compiled": compiled, "model": selected_model})
except Exception as exc:
    if isinstance(exc, ValueError) and str(exc) in {"invalid_request", "output_invalid"}:
        category = str(exc)
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
        return {
            "ok": False,
            "reason": "campaign_compiler_provider_failed",
            "model": model,
            "failure_category": "provider_failed",
        }
    last_line = next((line for line in reversed(raw.splitlines()) if line.lstrip().startswith("{")), "")
    try:
        result = json.loads(last_line) if last_line else {}
    except json.JSONDecodeError:
        result = {}
    if not isinstance(result, dict):
        result = {}
    if result.get("ok") is True and isinstance(result.get("compiled"), dict):
        return {
            "ok": True,
            "compiled": dict(result["compiled"]),
            "model": model,
            "provider": "openai-codex-oauth",
        }
    category = _failure_category(result.get("failure_category"))
    reason = "campaign_compiler_invalid_json" if category == "output_invalid" else (
        "campaign_compiler_timeout" if category == "provider_timeout" else "campaign_compiler_provider_failed"
    )
    return {
        "ok": False,
        "reason": reason,
        "model": model,
        "failure_category": category,
        "provider": "openai-codex-oauth",
    }


def compile_with_codex_oauth(
    prompt: str,
    schema: Mapping[str, Any],
    *,
    model: str,
    timeout: int | float,
    hermes_home: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Compile a structured result through Hermes' Codex OAuth transport.

    ``hermes_home`` may be one private central-pool slot or an install's
    regular Hermes profile.  No token is passed to the subprocess or returned
    from it; the environment only identifies the already-private profile.
    """
    selected_model = str(model or "").strip()
    request = str(prompt or "").strip()
    if not selected_model or not request or not isinstance(schema, Mapping):
        return {
            "ok": False,
            "reason": "campaign_compiler_provider_failed",
            "model": selected_model,
            "failure_category": "provider_failed",
        }
    encoded_prompt = request.encode("utf-8", errors="replace")
    try:
        encoded_schema = json.dumps(dict(schema), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError):
        encoded_schema = b""
    if len(encoded_prompt) > MAX_PROMPT_BYTES or not encoded_schema or len(encoded_schema) > MAX_SCHEMA_BYTES:
        return {
            "ok": False,
            "reason": "campaign_compiler_provider_failed",
            "model": selected_model,
            "failure_category": "provider_failed",
        }
    try:
        timeout_seconds = max(1.0, min(float(timeout), 300.0))
    except (TypeError, ValueError):
        timeout_seconds = 1.0
    environment = os.environ.copy()
    if hermes_home:
        home = Path(hermes_home).expanduser()
        environment["HERMES_HOME"] = str(home)
        # A central account slot retains the root Codex session for image
        # generation.  Exposing only its path keeps the OAuth secret inside
        # the protected profile; no credential enters process arguments.
        environment["CODEX_HOME"] = str(home)
    payload = json.dumps({
        "prompt": request,
        "schema": dict(schema),
        "model": selected_model,
        "timeout": timeout_seconds,
    }, ensure_ascii=False, separators=(",", ":"))
    try:
        completed = subprocess.run(
            [sys.executable, "-c", HERMES_CODEX_OAUTH_COMPILER_BRIDGE],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 5,
            check=False,
            env=environment,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "reason": "campaign_compiler_timeout",
            "model": selected_model,
            "failure_category": "provider_timeout",
            "provider": "openai-codex-oauth",
        }
    except (OSError, ValueError):
        return {
            "ok": False,
            "reason": "campaign_compiler_provider_failed",
            "model": selected_model,
            "failure_category": "provider_failed",
            "provider": "openai-codex-oauth",
        }
    return _response_from_stdout(completed.stdout, model=selected_model)


__all__ = ["compile_with_codex_oauth"]
