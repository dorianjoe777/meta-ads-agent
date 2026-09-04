"""Standalone ChatGPT/Codex OAuth image transport.

This module mirrors Codex's native Images client contract instead of routing an
image request through the Responses API.  Hermes remains responsible for OAuth
storage/refresh only; no conversational model or ``codex exec`` process is
started here.
"""

from __future__ import annotations

import base64
import json
import os
import stat
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence


CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
API_MODEL = "gpt-image-2"
DEFAULT_TIER = "gpt-image-2-medium"
PROVIDER = "openai-codex-images"
MAX_REFERENCES = 8
MAX_REFERENCE_BYTES = 20 * 1024 * 1024

_QUALITY_BY_TIER = {
    "gpt-image-2-low": "low",
    "gpt-image-2-medium": "medium",
    "gpt-image-2-high": "high",
}
_SIZE_BY_ASPECT = {
    "1:1": "1024x1024",
    "square": "1024x1024",
    "4:5": "1024x1536",
    "9:16": "1024x1536",
    "portrait": "1024x1536",
    "16:9": "1536x1024",
    "landscape": "1536x1024",
}


def _selected_tier(value: object = "") -> tuple[str, str]:
    requested = str(value or os.environ.get("OPENAI_IMAGE_MODEL") or DEFAULT_TIER).strip()
    if requested in _QUALITY_BY_TIER:
        return requested, _QUALITY_BY_TIER[requested]
    if requested == API_MODEL:
        return DEFAULT_TIER, "medium"
    # Never let a chat-model value become the image model.  Image generation
    # is intentionally pinned to the standalone image endpoint/model.
    return DEFAULT_TIER, "medium"


def _size_for_aspect(value: object) -> str:
    return _SIZE_BY_ASPECT.get(str(value or "1:1").strip().lower(), "1024x1024")


def _mime_for_bytes(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("reference_images_unsupported")


def _reference_urls(paths: Sequence[object]) -> list[dict[str, str]]:
    if len(paths) > MAX_REFERENCES:
        raise ValueError("reference_images_unsupported")
    images: list[dict[str, str]] = []
    for raw in paths:
        path = Path(str(raw or ""))
        try:
            if path.is_symlink():
                raise ValueError("reference_images_unsupported")
            resolved = path.resolve(strict=True)
            descriptor = os.open(resolved, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, "rb") as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_REFERENCE_BYTES:
                    raise ValueError("reference_images_unsupported")
                data = handle.read(MAX_REFERENCE_BYTES + 1)
        except (OSError, RuntimeError) as exc:
            raise ValueError("reference_images_unsupported") from exc
        if len(data) > MAX_REFERENCE_BYTES:
            raise ValueError("reference_images_unsupported")
        mime = _mime_for_bytes(data)
        encoded = base64.b64encode(data).decode("ascii")
        images.append({"image_url": f"data:{mime};base64,{encoded}"})
    return images


def _build_request(payload: Mapping[str, Any]) -> tuple[str, dict[str, Any], str, int]:
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt_required")
    tier, quality = _selected_tier(payload.get("model"))
    body: dict[str, Any] = {
        "prompt": prompt,
        "background": "opaque",
        "model": API_MODEL,
        "quality": quality,
        "size": _size_for_aspect(payload.get("aspect_ratio")),
    }
    references = payload.get("reference_image_paths") or payload.get("image_paths") or []
    if not isinstance(references, list):
        references = []
    image_urls = _reference_urls(references)
    endpoint = "images/generations"
    if image_urls:
        body["images"] = image_urls
        endpoint = "images/edits"
    return endpoint, body, tier, len(image_urls)


def _first_party_headers(access_token: str) -> dict[str, str]:
    try:
        from agent.auxiliary_client import _codex_cloudflare_headers

        headers = dict(_codex_cloudflare_headers(access_token))
    except Exception:
        headers = {
            "User-Agent": "codex_cli_rs/0.0.0 (Admira IA)",
            "originator": "codex_cli_rs",
        }
        try:
            parts = access_token.split(".")
            if len(parts) >= 2:
                payload = parts[1] + "=" * (-len(parts[1]) % 4)
                claims = json.loads(base64.urlsafe_b64decode(payload))
                account_id = claims.get("https://api.openai.com/auth", {}).get("chatgpt_account_id")
                if isinstance(account_id, str) and account_id:
                    headers["ChatGPT-Account-ID"] = account_id
        except Exception:
            pass
    headers.update({
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "x-codex-image-turn-id": str(uuid.uuid4()),
    })
    return headers


def _post_json(url: str, body: Mapping[str, Any], headers: Mapping[str, str], timeout: float):
    import httpx

    limits = httpx.Timeout(timeout, connect=min(30.0, timeout), read=timeout,
                           write=min(30.0, timeout), pool=min(30.0, timeout))
    with httpx.Client(timeout=limits, headers=dict(headers)) as client:
        response = client.post(url, json=dict(body))
        try:
            data = response.json()
        except Exception:
            data = {}
        return response.status_code, dict(response.headers), data


def _retry_after(headers: Mapping[str, Any]) -> float | None:
    raw = headers.get("retry-after") or headers.get("Retry-After")
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    return seconds if 0 <= seconds <= 86400 else None


def _http_failure(status: int, headers: Mapping[str, Any]) -> dict[str, Any]:
    if status == 401:
        error_type = "auth_required"
        message = "Codex Images OAuth authentication was rejected (HTTP 401)."
    elif status == 429:
        error_type = "rate_limit"
        message = "Codex Images API returned HTTP 429 image generation limit."
    elif status in {408, 502, 503, 504}:
        error_type = "provider_unavailable"
        message = f"Codex Images API is temporarily unavailable (HTTP {status})."
    elif status == 403:
        error_type = "provider_unavailable"
        message = "Codex Images API rejected this runtime (HTTP 403)."
    else:
        error_type = "api_error"
        message = f"Codex Images API returned HTTP {status}."
    result: dict[str, Any] = {"success": False, "error": message, "error_type": error_type}
    retry = _retry_after(headers)
    if retry is not None:
        result["retry_after_seconds"] = retry
    return result


def _save_image(data: bytes) -> Path:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid_image_response")
    raw_home = str(os.environ.get("HERMES_HOME") or "").strip()
    if not raw_home:
        raise RuntimeError("provider_auth")
    root = Path(raw_home).expanduser() / "cache" / "images" / uuid.uuid4().hex
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    output = root / "image.png"
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return output


def handle_image_bridge_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve OAuth, call Codex Images directly, and return a bounded result."""
    pool_auth_path = None
    try:
        if payload.get("pool_oauth") is True:
            from codex_oauth_session import prepare_hermes_oauth

            pool_auth_path = prepare_hermes_oauth()

        from hermes_cli.auth import resolve_codex_runtime_credentials

        credentials = resolve_codex_runtime_credentials(refresh_if_expiring=True)
        access_token = str(credentials.get("api_key") or "").strip()
        if not access_token:
            return {"success": False, "error": "Codex OAuth credentials are unavailable.",
                    "error_type": "auth_required"}
        if pool_auth_path:
            from codex_oauth_session import mirror_back_to_root

            mirror_back_to_root(pool_auth_path)

        if str(payload.get("mode") or "generate") == "status":
            tier, _quality = _selected_tier(payload.get("model"))
            return {
                "success": True,
                "provider": PROVIDER,
                "display_name": "OpenAI Codex Images OAuth",
                "model": tier,
                "transport": "images/generations",
            }

        endpoint, body, tier, reference_count = _build_request(payload)
        timeout = float(payload.get("http_timeout_seconds") or 240.0)
        timeout = max(10.0, min(timeout, 270.0))
        status, response_headers, response = _post_json(
            f"{CODEX_BASE_URL}/{endpoint}", body, _first_party_headers(access_token), timeout,
        )
        if not 200 <= int(status) < 300:
            failure = _http_failure(int(status), response_headers)
            failure.update({
                "provider": PROVIDER,
                "model": tier,
                "transport": endpoint,
                "reference_image_count": reference_count,
            })
            return failure
        data = response.get("data") if isinstance(response, Mapping) else None
        encoded = data[0].get("b64_json") if isinstance(data, list) and data and isinstance(data[0], Mapping) else None
        if not isinstance(encoded, str) or not encoded:
            return {"success": False, "error": "Codex Images returned no image data.",
                    "error_type": "invalid_response"}
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
            output = _save_image(image_bytes)
        except Exception:
            return {"success": False, "error": "Codex Images returned invalid image data.",
                    "error_type": "invalid_response"}
        return {
            "success": True,
            "image": str(output),
            "model": tier,
            "provider": PROVIDER,
            "transport": endpoint,
            "reference_image_count": reference_count,
            "reference_image_arg": "images" if reference_count else "",
        }
    except ValueError as exc:
        reason = str(exc)
        error_type = "reference_images_unsupported" if reason == "reference_images_unsupported" else "provider_contract"
        return {"success": False, "error": reason, "error_type": error_type}
    except Exception as exc:
        lowered = str(exc).lower()
        name = type(exc).__name__.lower()
        if "timeout" in name or "timed out" in lowered:
            error_type = "timeout"
            error = "Codex Images request timed out."
        elif any(marker in lowered for marker in ("auth", "credential", "token")):
            error_type = "auth_required"
            error = "Codex OAuth credentials are unavailable."
        else:
            error_type = "provider_unavailable"
            error = "Codex Images direct transport is unavailable."
        return {"success": False, "error": error, "error_type": error_type}
    finally:
        if pool_auth_path:
            try:
                from codex_oauth_session import mirror_back_to_root

                mirror_back_to_root(pool_auth_path)
            except Exception:
                pass


__all__ = [
    "API_MODEL",
    "CODEX_BASE_URL",
    "DEFAULT_TIER",
    "PROVIDER",
    "handle_image_bridge_payload",
]
