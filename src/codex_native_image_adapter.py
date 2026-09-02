"""Slot-scoped compatibility adapter for Hermes 0.18's native image provider.

Used only inside the short-lived image bridge subprocess. The installed
provider accepts **kwargs but ignores local reference paths; attach those
bytes to its existing Responses request instead of starting Codex CLI.
"""
from __future__ import annotations

import base64
import os
import stat
import sys
from pathlib import Path


def _reference_parts(paths):
    if len(paths) > 8:
        raise ValueError("reference_images_unsupported")
    parts = []
    for raw in paths:
        path = Path(raw)
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 20 * 1024 * 1024:
                    raise ValueError("reference_images_unsupported")
                data = handle.read(20 * 1024 * 1024 + 1)
                if len(data) > 20 * 1024 * 1024:
                    raise ValueError("reference_images_unsupported")
        except OSError as exc:
            raise ValueError("reference_images_unsupported") from exc
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif data.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            mime = "image/webp"
        else:
            raise ValueError("reference_images_unsupported")
        parts.append({"type": "input_image", "image_url":
                      f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"})
    return parts


def generate_pool_image(provider, *, prompt, aspect_ratio, reference_paths):
    """Use only the selected slot's OAuth identity and native image transport."""
    from codex_oauth_session import prepare_hermes_oauth, mirror_back_to_root
    from hermes_cli.auth import resolve_codex_runtime_credentials

    module = sys.modules[type(provider).__module__]
    builder = getattr(module, "_build_responses_payload", None)
    events = getattr(module, "_iter_sse_json", None)
    reader = getattr(module, "_read_codex_access_token", None)
    # Fail closed on an incompatible Hermes package, never silently drop the
    # photograph or route the request through a reasoning/CLI session.
    if not all(callable(item) for item in (builder, events, reader)):
        return {"success": False, "error_type": "provider_contract",
                "error": "El proveedor nativo de imágenes necesita una versión compatible."}
    parts = _reference_parts(reference_paths)
    auth_path = prepare_hermes_oauth()
    try:
        credentials = resolve_codex_runtime_credentials(refresh_if_expiring=True)
        # Keep a refreshed token canonical before the long image request: a
        # process timeout must not leave the root refresh chain stale.
        mirror_back_to_root(auth_path)
        token = credentials.get("api_key")
        if not isinstance(token, str) or not token.strip():
            raise RuntimeError("provider_auth")

        def build_with_references(**kwargs):
            body = builder(**kwargs)
            body["input"][0]["content"].extend(parts)
            return body

        def checked_events(response):
            for event in events(response):
                if isinstance(event, dict):
                    kind = event.get("type")
                    if kind in {"error", "response.failed", "response.incomplete"}:
                        detail = event.get("error") or (event.get("response") or {}).get("error") or {}
                        # This text remains inside the private bridge and is
                        # reduced to an allowlisted category by its caller.
                        raise RuntimeError(str(detail or "provider_failed"))
                    if kind == "response.image_generation_call.partial_image":
                        continue
                yield event

        module._read_codex_access_token = lambda: token
        module._build_responses_payload = build_with_references
        module._iter_sse_json = checked_events
        result = provider.generate(prompt=prompt, aspect_ratio=aspect_ratio)
        if isinstance(result, dict):
            result["reference_image_count"] = len(parts)
            result["reference_image_arg"] = "input_image" if parts else ""
        return result
    finally:
        module._read_codex_access_token = reader
        module._build_responses_payload = builder
        module._iter_sse_json = events
        mirror_back_to_root(auth_path)
