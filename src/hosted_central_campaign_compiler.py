"""Authenticated tenant client for the hosted central campaign compiler.

The central service owns the Codex OAuth pool. Tenant runtimes receive only a
private HMAC key and a Unix-socket capability, so campaign compilation can use
Terra without mounting or exposing any operator credential in the tenant.
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
from typing import Any, Mapping

from hosted_central_image_client import _canonical, _json_file, _private_file, _tenant


MAX_PROMPT = 100_000
MAX_RESPONSE = 128 * 1024
# The tenant's outer compilation deadline is 240 seconds. Reserve a little
# time for socket I/O and response validation so a central Codex process never
# continues beyond the turn that asked for it.
MAX_PROVIDER_TIMEOUT_SECONDS = 230
TIMEOUT_RESPONSE_RESERVE_SECONDS = 5
MODEL = "gpt-5.6-terra"
TOOLS = {
    "admira_create_whatsapp_campaign",
    "admira_create_lead_form_campaign",
    "admira_create_website_campaign",
    "admira_create_messaging_campaign",
    "admira_create_app_campaign",
    "admira_create_on_meta_campaign",
    "create_whatsapp_campaign",
    "create_lead_form_campaign",
    "create_website_campaign",
    "create_messaging_campaign",
    "create_app_campaign",
    "create_on_meta_campaign",
}
SAFE_FAILURES = {
    "invalid_request",
    "invalid_signature",
    "expired_request",
    "replayed_request",
    "entitlement_blocked",
    "personal_provider_required",
    "tenant_busy",
    "global_busy",
    "tool_not_allowed",
    "schema_failed",
    "provider_failed",
    "provider_unavailable",
    "provider_timeout",
    "output_invalid",
    "compiled_invalid",
    "response_too_large",
    "tenant_not_found",
    "central_not_ready",
    "internal_error",
}


def _error(reason: object) -> dict[str, Any]:
    code = str(reason or "provider_failed")
    if code not in SAFE_FAILURES:
        code = "provider_failed"
    return {"ok": False, "reason": code, "model": MODEL}


def _request_uuid(tenant_id: str, update_id: str, tool: str, prompt: str) -> str:
    digest = hashlib.sha256(_canonical({
        "tenant_id": tenant_id,
        "update_id": update_id,
        "tool": tool,
        "prompt": prompt,
        "purpose": "campaign_compile",
    })).hexdigest()
    return str(uuid.UUID(hex=digest[:32]))


def _read_response(sock: socket.socket) -> Mapping[str, Any] | None:
    chunks: list[bytes] = []
    size = 0
    while size < MAX_RESPONSE:
        chunk = sock.recv(min(8192, MAX_RESPONSE - size))
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
    return value if isinstance(value, dict) else None


def maybe_compile_central_campaign(
    tool: str,
    prompt: str,
    *,
    timeout: float = 240,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Compile through the central pool only for an entitled hosted turn.

    ``None`` preserves the established single-runtime DigitalOcean/local path.
    Once a hosted turn is explicitly routed to the central pool, any broker
    failure is returned as a safe failure and never falls through to a
    tenant-local or unrelated Codex credential.
    """
    access_path = Path(os.environ.get(
        "ADMIRA_HOSTED_IMAGE_ACCESS_FILE",
        "/app/runtime/hosted_image_access.json",
    ))
    access = _json_file(access_path)
    if not access:
        return None
    route = str(access.get("route") or "")
    if route in {"", "disabled", "legacy", "personal_chatgpt"}:
        return None
    if route != "central_sponsored":
        return _error("entitlement_blocked")
    if access.get("central_ready") is not True:
        return _error("central_not_ready")
    try:
        tenant_id = _tenant(os.environ.get("ADMIRA_TENANT_ID"))
    except ValueError:
        return _error("invalid_request")
    if access.get("tenant_id") != tenant_id:
        return _error("invalid_request")
    selected_tool = str(tool or "").strip()
    request_prompt = str(prompt or "").strip()
    if selected_tool not in TOOLS or not request_prompt or len(request_prompt) > MAX_PROMPT:
        return _error("invalid_request")
    try:
        key_path = Path(os.environ.get(
            "ADMIRA_CENTRAL_IMAGE_CLIENT_KEY_FILE",
            "/app/runtime/central_image_client.key",
        ))
        key = _private_file(key_path, 32)
        socket_path = Path(os.environ.get(
            "ADMIRA_CENTRAL_CAMPAIGN_COMPILER_SOCKET",
            "/run/admira-central-image-broker/compiler.sock",
        ))
        update_id = str(access.get("update_id") or "")
        request_id = _request_uuid(tenant_id, update_id, selected_tool, request_prompt)
        socket_timeout = max(0.1, min(float(timeout), 300.0))
        provider_timeout = max(
            1,
            min(
                int(socket_timeout) - TIMEOUT_RESPONSE_RESERVE_SECONDS,
                MAX_PROVIDER_TIMEOUT_SECONDS,
            ),
        )
        body = {
            "tenant_id": tenant_id,
            "request_id": request_id,
            "purpose": "campaign_compile",
            "tool": selected_tool,
            "prompt": request_prompt,
            "update_id": update_id,
            # This is authenticated with the rest of the body. The central
            # service separately caps it before invoking the provider.
            "timeout_seconds": provider_timeout,
        }
        envelope = {
            "timestamp": int(time.time() if now is None else now),
            "nonce": secrets.token_hex(16),
            "body": body,
        }
        envelope["signature"] = hmac.new(key, _canonical(envelope), hashlib.sha256).hexdigest()
        line = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        if len(line) > MAX_RESPONSE:
            return _error("invalid_request")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(socket_timeout)
            sock.connect(str(socket_path))
            sock.sendall(line)
            response = _read_response(sock)
        if not isinstance(response, Mapping) or response.get("ok") is not True:
            return _error(response.get("error_code") if isinstance(response, Mapping) else "provider_failed")
        if response.get("tenant_id") != tenant_id or response.get("request_id") != request_id:
            return _error("output_invalid")
        if str(response.get("model") or "") != MODEL:
            return _error("output_invalid")
        compiled = response.get("compiled")
        if not isinstance(compiled, Mapping):
            return _error("output_invalid")
        return {"ok": True, "compiled": dict(compiled), "model": MODEL, "provider": "hosted-central-codex"}
    except (OSError, socket.timeout, socket.error, UnicodeError, ValueError, json.JSONDecodeError):
        return _error("provider_failed")


__all__ = ["MODEL", "maybe_compile_central_campaign"]
