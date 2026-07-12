#!/usr/bin/env python3
"""Runtime patches for third-party Hermes gateway buyer-facing messages.

The Hermes gateway is installed as a dependency inside the buyer container.
Admira should not edit site-packages in place, so this module is loaded through
PYTHONPATH/sitecustomize only for the gateway process and wraps the narrow
provider-error formatter that can otherwise leak raw English provider text.
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from admira_rate_limit_messages import gateway_rate_limit_reply, is_rate_limit_text

ADMIRA_MINIMAX_PROVIDER = "admira-minimax"
ADMIRA_MINIMAX_PROVIDER_NAME = "MiniMax M3 oficial"
ADMIRA_MINIMAX_MODEL = "MiniMax-M3"
ADMIRA_MINIMAX_KEY_ENV = "ADMIRA_MINIMAX_API_KEY"
ADMIRA_MINIMAX_DEFAULT_BASE_URL = "https://api.minimax.io/v1"
ADMIRA_MINIMAX_ALIASES = {
    "minimax",
    "minimax m3",
    "minimax-m3",
    "minimax_m3",
    "minimaxm3",
    "minimax-m3-official",
    "minimax m3 official",
    "minimax m3 oficial",
    "minimax-m3-oficial",
    ADMIRA_MINIMAX_MODEL.lower(),
}
ADMIRA_MEDIA_EXTENSIONS = "png|jpe?g|gif|webp"
ADMIRA_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
ADMIRA_MEDIA_TAG_RE = re.compile(
    rf"MEDIA:\s*(?P<path>(?:/|~/)\S+?\.(?:{ADMIRA_MEDIA_EXTENSIONS})(?=[\s\"'`,;:)\]]|$))",
    re.IGNORECASE,
)
ADMIRA_OUTPUT_IMAGE_RE = re.compile(
    rf"(?P<path>(?:/|~/)\S*?/output/\S+?\.(?:{ADMIRA_MEDIA_EXTENSIONS})(?=[\s\"'`,;:)\]]|$))",
    re.IGNORECASE,
)
ADMIRA_GENERATED_MEDIA_KEYS = {
    "image_path",
    "media_attachment",
    "generated_image_path",
    "creative_image_path",
}
ADMIRA_RECENT_TURNS_LIMIT = 80
ADMIRA_AUTH_INVALID_PATTERNS = (
    "token_invalidated",
    "authentication token has been invalidated",
    "invalid_grant",
    "refresh token is invalid",
    "refresh token has been revoked",
    "oauth token has been revoked",
)
ADMIRA_PERSISTENCE_CLAIM_RE = re.compile(
    r"(?i)(?:\b(?:ya\s+)?(?:lo|la|esto|eso)?\s*(?:he\s+)?guard(?:é|ado|ada)\b|"
    r"\b(?:ya\s+)?qued[oó]\s+guardad[oa]\b|\blo\s+recordar[eé]\b|"
    r"\b(?:ya\s+)?qued[oó]\s+en\s+mis\s+indicaciones\b|"
    r"\b(?:i(?:'ve| have)?\s+)?saved\s+(?:it|that|this)\b|\bi(?:'ll| will)\s+remember\s+(?:it|that|this)\b)"
)
ADMIRA_DURABLE_TOOL_MARKERS = (
    "admira_save_",
    "mcp_admira_save_",
    "admira_record_verified_signal",
    "mcp_admira_record_verified_signal",
)


def _recent_turns_path():
    configured = str(os.environ.get("ADMIRA_TELEGRAM_RECENT_TURNS_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser()
    root = str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "").strip()
    if not root:
        return None
    return Path(root).expanduser() / "dashboard" / "data" / "hermes_gateway_recent_turns.json"


def _redact_turn_text(value):
    text = str(value or "")
    if not text:
        return ""
    lower = text.lower()
    if "código temporal para conectar chatgpt" in lower or "temporary code to connect chatgpt" in lower:
        return "Se inició una reconexión segura de ChatGPT/Codex. Los datos temporales de acceso no se guardaron."
    clean = re.sub(r"MEDIA:\s*(?:/|~/)\S+", "MEDIA:[attached]", text)
    product_root = str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "").strip().rstrip("/")
    if product_root:
        clean = clean.replace(product_root, "[internal-path]")
    clean = re.sub(r"(?:/app|/Users|/root)(?:/[^\s\"'`]+)+", "[internal-path]", clean)
    clean = re.sub(r"\b(?:EA[A-Za-z0-9_-]{40,}|EAA[A-Za-z0-9_-]{40,})\b", "[redacted-token]", clean)
    clean = re.sub(r"\bdop_v1_[A-Za-z0-9_-]{40,}\b", "[redacted-token]", clean)
    clean = re.sub(r"\bsk-[A-Za-z0-9_-]{24,}\b", "[redacted-token]", clean)
    clean = re.sub(r"(?i)\b(passphrase|password|contraseña|token|api key|access token)\s*[:=]\s*\S+", r"\1: [redacted]", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:5000]


def _append_gateway_turn(role, content):
    path = _recent_turns_path()
    text = _redact_turn_text(content)
    if not path or not text:
        return False
    try:
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        else:
            existing = []
        existing.append(
            {
                "role": "agent" if str(role or "").lower() in {"agent", "assistant"} else "user",
                "content": text,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source": "hermes_gateway",
            }
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing[-ADMIRA_RECENT_TURNS_LIMIT:], ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return True
    except Exception:
        return False


def _runtime_model_state_path():
    configured = str(os.environ.get("ADMIRA_TELEGRAM_MODEL_STATE_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser()
    root = str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "").strip()
    if not root:
        return None
    return Path(root).expanduser() / "dashboard" / "data" / "telegram_model_state.json"


def _model_switch_succeeded(result):
    if isinstance(result, dict):
        if result.get("success") is False or result.get("ok") is False:
            return False
        if str(result.get("status") or "").strip().lower() in {"failed", "error", "cancelled", "canceled"}:
            return False
    return True


def _write_runtime_model_state(provider, model, base_url="", source="telegram_model_command"):
    path = _runtime_model_state_path()
    if not path:
        return False
    provider = str(provider or "").strip()
    model = str(model or "").strip()
    if not (provider or model):
        return False
    payload = {
        "provider": provider,
        "model": model,
        "base_url": str(base_url or "").strip(),
        "source": source,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return True
    except OSError:
        return False


def is_authentication_error_text(text):
    lowered = str(text or "").lower()
    if any(pattern in lowered for pattern in ADMIRA_AUTH_INVALID_PATTERNS):
        return True
    return any(
        pattern in lowered
        for pattern in (
            "provider authentication failed",
            "authentication failed",
            "authenticationerror",
            "unauthorized provider",
        )
    )


def _dashboard_recovery_link():
    raw = str(os.environ.get("ADMIRA_DASHBOARD_RECOVERY_URL") or "").strip()
    if not raw:
        return "", ""
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError:
        return "", ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return "", ""
    safe = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))
    kind = "portal" if str(os.environ.get("ADMIRA_DASHBOARD_RECOVERY_KIND") or "").lower() == "portal" else "dashboard"
    return safe, kind


def _safe_openai_login_url(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError:
        return ""
    hostname = str(parsed.hostname or "").lower().rstrip(".")
    allowed = hostname in {"openai.com", "chatgpt.com"} or hostname.endswith(".openai.com") or hostname.endswith(".chatgpt.com")
    if parsed.scheme != "https" or not allowed or parsed.username or parsed.password:
        return ""
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _internal_recovery_settings():
    raw_url = str(os.environ.get("ADMIRA_INTERNAL_MODEL_RECOVERY_URL") or "").strip()
    token_path = str(os.environ.get("ADMIRA_INTERNAL_MODEL_RECOVERY_TOKEN_FILE") or "").strip()
    if not raw_url or not token_path:
        return "", ""
    try:
        parsed = urllib.parse.urlsplit(raw_url)
    except ValueError:
        return "", ""
    if parsed.scheme != "http" or str(parsed.hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
        return "", ""
    try:
        token = Path(token_path).expanduser().read_text(encoding="utf-8").strip()
    except OSError:
        return "", ""
    if len(token) < 32:
        return "", ""
    return raw_url, token


def _request_internal_model_recovery(action):
    url, token = _internal_recovery_settings()
    if not url:
        return {}
    body = json.dumps({"action": str(action or "status")}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Admira-Internal-Recovery": token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            if int(getattr(response, "status", 200)) != 200:
                return {}
            payload = json.loads(response.read(64 * 1024).decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError):
        return {}
    result = payload.get("result") if isinstance(payload, dict) else {}
    return result if isinstance(result, dict) else {}


def _automatic_codex_recovery(wait_seconds=12):
    if not _internal_recovery_settings()[0]:
        return {}
    result = _request_internal_model_recovery("start")
    deadline = time.monotonic() + max(0, min(float(wait_seconds), 15))
    while time.monotonic() < deadline:
        urls = [_safe_openai_login_url(item) for item in (result.get("urls") or [])]
        login_url = next((item for item in urls if item), "")
        codes = result.get("login_codes") if isinstance(result.get("login_codes"), list) else []
        login_code = str(result.get("login_code") or (codes[0] if codes else "")).strip()
        login_code = login_code if re.fullmatch(r"[A-Z0-9](?:[A-Z0-9-]{4,30})[A-Z0-9]", login_code.upper()) else ""
        if login_url and login_code:
            return {"url": login_url, "code": login_code.upper()}
        if str(result.get("phase") or "") == "device_auth_settings":
            return {"device_auth_settings": True}
        if result and not result.get("running") and str(result.get("status") or "") not in {"browser_login_started", "browser_login_waiting", "needs_login"}:
            break
        time.sleep(0.65)
        result = _request_internal_model_recovery("status")
    return {}


def gateway_authentication_reply(text, language=None):
    language = str(language or os.environ.get("ADMIRA_GATEWAY_LANGUAGE", "es")).lower()
    lowered = str(text or "").lower()
    codex_session = any(
        marker in lowered
        for marker in (
            "token_invalidated",
            "authentication token has been invalidated",
            "openai-codex",
            "chatgpt.com/backend-api/codex",
        )
    )
    codex_session = codex_session or "codex" in str(os.environ.get("ADMIRA_GATEWAY_PROVIDER") or "").lower()
    recovery_url, recovery_kind = _dashboard_recovery_link()
    automatic = _automatic_codex_recovery() if codex_session else {}
    if language.startswith("en"):
        if codex_session:
            intro = "🔐 The ChatGPT/Codex connection expired or was closed."
            if automatic.get("url") and automatic.get("code"):
                return (
                    f"{intro}\n\nI opened a new secure login for you:\n"
                    f"1. Open: {automatic['url']}\n"
                    f"2. Enter this temporary code to connect ChatGPT: {automatic['code']}\n"
                    "3. Finish the ChatGPT login and then message me again.\n\n"
                    "The code expires shortly. Your saved business memory and work are safe."
                )
            if recovery_url:
                first_step = f"1. Open your Admira access page and then open the dashboard: {recovery_url}" if recovery_kind == "portal" else f"1. Open the dashboard: {recovery_url}"
                return (
                    f"{intro}\n\nTo reconnect it:\n{first_step}\n"
                    "2. Open Setup.\n3. Find Agent model.\n4. Open ChatGPT subscription.\n"
                    "5. Click connect/reconnect and finish the secure ChatGPT login.\n\n"
                    "Your saved business memory and work are safe."
                )
            return f"{intro} Open Setup → Agent model → ChatGPT subscription and reconnect the account. Your saved business memory and work are safe."
        return (
            "🔐 The agent model connection is no longer valid. Open Settings → Agent model and reconnect "
            "the selected provider. Your saved business memory and work are safe."
        )
    if codex_session:
        intro = "🔐 La conexión de ChatGPT/Codex venció o fue cerrada."
        if automatic.get("url") and automatic.get("code"):
            return (
                f"{intro}\n\nYa abrí un login seguro nuevo:\n"
                f"1. Abre: {automatic['url']}\n"
                f"2. Escribe este código temporal para conectar ChatGPT: {automatic['code']}\n"
                "3. Termina el login de ChatGPT y luego vuelve a escribirme.\n\n"
                "El código vence pronto. La memoria y el trabajo guardado no se pierden."
            )
        if recovery_url:
            first_step = f"1. Abre tu acceso de Admira y luego abre el dashboard: {recovery_url}" if recovery_kind == "portal" else f"1. Abre el dashboard: {recovery_url}"
            return (
                f"{intro}\n\nPara reconectarla:\n{first_step}\n"
                "2. Entra a Configuración.\n3. Busca Modelo del agente.\n4. Abre ChatGPT suscripción.\n"
                "5. Toca conectar/reconectar y completa el login seguro de ChatGPT.\n\n"
                "La memoria y el trabajo guardado no se pierden."
            )
        return f"{intro} Abre Configuración → Modelo del agente → ChatGPT suscripción y vuelve a conectar la cuenta. La memoria y el trabajo guardado no se pierden."
    return (
        "🔐 La conexión del modelo dejó de ser válida. Abre Configuración → Modelo del agente y vuelve a "
        "conectar el proveedor seleccionado. La memoria y el trabajo guardado no se pierden."
    )


def provider_error_reply(text, language=None, original=None):
    if is_rate_limit_text(text):
        return gateway_rate_limit_reply(text, language or os.environ.get("ADMIRA_GATEWAY_LANGUAGE", "es"))
    if is_authentication_error_text(text):
        return gateway_authentication_reply(text, language)
    if callable(original):
        return original(text)
    return str(text or "")


def _path_within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _admira_generated_media_roots():
    roots = []
    product_root = str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "").strip()
    if product_root:
        roots.append(Path(product_root).expanduser() / "output")
    roots.append(Path("/app/output"))
    extra_roots = str(os.environ.get("HERMES_MEDIA_ALLOW_DIRS") or "")
    for chunk in extra_roots.split(os.pathsep):
        raw = chunk.strip()
        if raw:
            roots.append(Path(raw).expanduser())
    normalized = []
    seen = set()
    for root in roots:
        try:
            resolved = root.resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            continue
        key = str(resolved)
        if key not in seen:
            seen.add(key)
            normalized.append(resolved)
    return normalized


def _safe_generated_media_path(raw_path):
    value = str(raw_path or "").strip()
    if value.startswith("MEDIA:"):
        value = value.split("MEDIA:", 1)[1].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "`\"'":
        value = value[1:-1].strip()
    value = value.lstrip("`\"'").rstrip("`\"',.;:)}]")
    if not value:
        return ""
    candidate = Path(os.path.expanduser(value))
    if not candidate.is_absolute():
        return ""
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return ""
    if not resolved.is_file() or not re.search(rf"\.(?:{ADMIRA_MEDIA_EXTENSIONS})$", resolved.name, re.IGNORECASE):
        return ""
    for root in _admira_generated_media_roots():
        if _path_within(resolved, root):
            return str(resolved)
    return ""


def _collect_generated_media_paths(value, key_hint="", paths=None, depth=0):
    paths = paths if paths is not None else []
    if depth > 12:
        return paths
    if isinstance(value, dict):
        for key, item in value.items():
            _collect_generated_media_paths(item, str(key or ""), paths, depth + 1)
        return paths
    if isinstance(value, (list, tuple, set)):
        for item in value:
            _collect_generated_media_paths(item, key_hint, paths, depth + 1)
        return paths
    if not isinstance(value, str):
        return paths
    text = value.strip()
    if not text:
        return paths
    if key_hint in ADMIRA_GENERATED_MEDIA_KEYS:
        safe_path = _safe_generated_media_path(text)
        if safe_path:
            paths.append(safe_path)
    for pattern in (ADMIRA_MEDIA_TAG_RE, ADMIRA_OUTPUT_IMAGE_RE):
        for match in pattern.finditer(text):
            safe_path = _safe_generated_media_path(match.group("path"))
            if safe_path:
                paths.append(safe_path)
    return paths


def _latest_assistant_message(messages):
    """Return only the newest assistant/tool message to avoid replaying old media."""
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        if role in {"assistant", "tool"}:
            return message
    return None


def _current_generated_media_sources(response):
    """Collect media-bearing fields from the current turn, not the whole session history."""
    sources = []
    final_response = str(response.get("final_response") or "")
    if final_response:
        sources.append(final_response)
    for key in ADMIRA_GENERATED_MEDIA_KEYS:
        if key in response:
            sources.append({key: response.get(key)})
    for key in (
        "tool_result",
        "tool_results",
        "tool_response",
        "tool_responses",
        "result",
        "results",
        "action_result",
        "action_results",
        "mcp_result",
        "mcp_results",
    ):
        if key in response:
            sources.append(response.get(key))
    latest_message = _latest_assistant_message(response.get("messages"))
    if latest_message:
        sources.append(latest_message)
    return sources


def _current_turn_messages(messages):
    if not isinstance(messages, list):
        return []
    start = 0
    for index, message in enumerate(messages):
        if isinstance(message, dict) and str(message.get("role") or "").strip().lower() == "user":
            start = index + 1
    return messages[start:]


def _has_confirmed_durable_save(response):
    if not isinstance(response, dict):
        return False
    sources = []
    for key in ("tool_result", "tool_results", "tool_response", "tool_responses", "result", "results", "action_result", "action_results", "mcp_result", "mcp_results"):
        if key in response:
            sources.append(response.get(key))
    sources.extend(_current_turn_messages(response.get("messages")))
    try:
        text = json.dumps(sources, ensure_ascii=False, default=str).lower()
    except (TypeError, ValueError):
        text = str(sources).lower()
    # Tool content may itself be a JSON string inside the outer response JSON.
    text = text.replace('\\"', '"')
    has_save_tool = any(marker in text for marker in ADMIRA_DURABLE_TOOL_MARKERS)
    has_success = any(
        marker in text
        for marker in (
            '"saved": true',
            '"saved":true',
            '"ok": true',
            '"ok":true',
            '"executed": true',
            '"executed":true',
            '"status": "completed"',
            '"status":"completed"',
        )
    )
    return has_save_tool and has_success


def _guard_unconfirmed_persistence_claim(response):
    """Prevent a model from promising memory when no save tool succeeded."""
    if not isinstance(response, dict):
        return response
    final_response = str(response.get("final_response") or "")
    if not final_response or not ADMIRA_PERSISTENCE_CLAIM_RE.search(final_response):
        return response
    if _has_confirmed_durable_save(response):
        return response
    language = str(os.environ.get("ADMIRA_GATEWAY_LANGUAGE") or "es").lower()
    correction = (
        "I could not confirm a durable save in this turn, so I will not claim that it will survive a reset yet."
        if language.startswith("en")
        else "No pude confirmar un guardado durable en este turno, así que todavía no voy a afirmar que esto sobrevivirá un reinicio."
    )
    cleaned = ADMIRA_PERSISTENCE_CLAIM_RE.sub("", final_response)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip(" \n-—:;,.\t")
    response["final_response"] = (cleaned + "\n\n" + correction).strip()
    return response


def _append_generated_media_attachments(response):
    """Append native MEDIA directives for generated images in any result shape."""
    if not isinstance(response, dict):
        return response
    final_response = str(response.get("final_response") or "")
    paths = []
    for source in _current_generated_media_sources(response):
        _collect_generated_media_paths(source, paths=paths)
    if not paths:
        return response
    existing_media_paths = {
        safe_path
        for match in ADMIRA_MEDIA_TAG_RE.finditer(final_response)
        for safe_path in [_safe_generated_media_path(match.group("path"))]
        if safe_path
    }
    seen = set()
    tags = []
    for path in paths:
        tag = f"MEDIA:{path}"
        if path in seen or path in existing_media_paths or tag in final_response:
            continue
        seen.add(path)
        tags.append(tag)
    if not tags:
        return response
    response["final_response"] = (final_response.rstrip() + "\n" + "\n".join(tags)).strip()
    return response


def _event_video_paths(event):
    video_paths = []
    media_urls = list(getattr(event, "media_urls", None) or [])
    media_types = list(getattr(event, "media_types", None) or [])
    for index, raw_path in enumerate(media_urls):
        media_type = str(media_types[index] if index < len(media_types) else "").lower()
        try:
            path = Path(str(raw_path or "")).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            continue
        if media_type.startswith("video/") or path.suffix.lower() in ADMIRA_VIDEO_EXTENSIONS:
            video_paths.append(str(path))
    return video_paths


def _append_video_frame_inputs_to_event(event):
    """Convert cached inbound videos into frame image inputs before Hermes processes them."""
    video_paths = _event_video_paths(event)
    if not video_paths:
        return event
    try:
        from public_asset_fetcher import extract_video_preview_frames
    except Exception:
        return event
    media_urls = list(getattr(event, "media_urls", None) or [])
    media_types = list(getattr(event, "media_types", None) or [])
    existing = {str(Path(str(path)).expanduser()) for path in media_urls}
    notes = []
    for video_path in video_paths[:3]:
        frame_dir = Path(video_path).parent / f"{Path(video_path).stem}_admira_frames"
        frame_result = extract_video_preview_frames(video_path, output_dir=frame_dir)
        frames = frame_result.get("frames") or []
        if frames:
            added = 0
            for frame_path in frames:
                normalized = str(Path(frame_path).expanduser())
                if normalized in existing:
                    continue
                media_urls.append(normalized)
                media_types.append("image/jpeg")
                existing.add(normalized)
                added += 1
            duration = frame_result.get("duration_seconds") or 0
            duration_note = f" Duration: about {duration:g} seconds." if duration else ""
            notes.append(
                f"[Admira prepared {added or len(frames)} representative frames from the user's uploaded video for visual review.{duration_note} "
                "Use those attached frames to understand the video; the raw MP4 remains the original video creative asset.]"
            )
        else:
            reason = frame_result.get("reason") or "frame_extraction_failed"
            notes.append(f"[The user uploaded a video, but Admira could not extract preview frames automatically: {reason}.]")
    if media_urls != list(getattr(event, "media_urls", None) or []):
        event.media_urls = media_urls
        event.media_types = media_types
    if notes:
        original_text = str(getattr(event, "text", "") or "")
        event.text = ("\n".join(notes) + ("\n\n" + original_text if original_text else "")).strip()
    return event


def _admira_minimax_model():
    return os.environ.get("ADMIRA_MINIMAX_MODEL", ADMIRA_MINIMAX_MODEL).strip() or ADMIRA_MINIMAX_MODEL


def _admira_minimax_base_url():
    return (
        os.environ.get("ADMIRA_MINIMAX_BASE_URL")
        or os.environ.get("MINIMAX_BASE_URL")
        or ADMIRA_MINIMAX_DEFAULT_BASE_URL
    ).strip().rstrip("/") or ADMIRA_MINIMAX_DEFAULT_BASE_URL


def _admira_minimax_provider():
    return os.environ.get("ADMIRA_MINIMAX_PROVIDER", ADMIRA_MINIMAX_PROVIDER).strip() or ADMIRA_MINIMAX_PROVIDER


def _is_admira_minimax_value(value):
    normalized = str(value or "").strip().lower().replace("_", "-")
    compact = normalized.replace(" ", "").replace("-", "")
    model = _admira_minimax_model().lower().replace("_", "-")
    model_compact = model.replace(" ", "").replace("-", "")
    return normalized in ADMIRA_MINIMAX_ALIASES or compact in {"minimax", "minimaxm3"} or compact == model_compact


def _is_admira_minimax_provider(value):
    normalized = str(value or "").strip().lower()
    return normalized in {
        "minimax",
        "custom:admira-minimax",
        "admira-minimax",
        _admira_minimax_provider().lower(),
    }


def _admira_minimax_provider_entry():
    model = _admira_minimax_model()
    return {
        "name": ADMIRA_MINIMAX_PROVIDER_NAME,
        "base_url": _admira_minimax_base_url(),
        "key_env": ADMIRA_MINIMAX_KEY_ENV,
        "api_mode": "chat_completions",
        "model": model,
        "models": {model: {}},
    }


def _ensure_admira_minimax_user_provider(user_providers):
    providers = dict(user_providers or {}) if isinstance(user_providers, dict) else {}
    provider_key = _admira_minimax_provider()
    existing = providers.get(provider_key)
    wanted = _admira_minimax_provider_entry()
    if isinstance(existing, dict):
        merged = {**wanted, **existing}
        merged.setdefault("key_env", ADMIRA_MINIMAX_KEY_ENV)
        merged.setdefault("api_mode", "chat_completions")
        merged.setdefault("model", wanted["model"])
        models = merged.get("models")
        if not isinstance(models, dict):
            merged["models"] = {wanted["model"]: {}}
        elif wanted["model"] not in models:
            models[wanted["model"]] = {}
        providers[provider_key] = merged
    else:
        providers[provider_key] = wanted
    return providers


def _patch_minimax_model_switch():
    try:
        import hermes_cli.model_switch as model_switch
    except Exception:
        return False
    if getattr(model_switch, "_admira_minimax_official_patch", False):
        return True

    direct_alias = getattr(model_switch, "DirectAlias", None)
    aliases = getattr(model_switch, "DIRECT_ALIASES", None)
    if isinstance(aliases, dict) and direct_alias is not None:
        for alias in ADMIRA_MINIMAX_ALIASES:
            aliases.setdefault(
                alias,
                direct_alias(
                    model=_admira_minimax_model(),
                    provider=_admira_minimax_provider(),
                    base_url=_admira_minimax_base_url(),
                ),
            )

    original_resolve_alias = getattr(model_switch, "resolve_alias", None)
    if callable(original_resolve_alias):
        def patched_resolve_alias(raw_input, current_provider=""):
            if _is_admira_minimax_value(raw_input):
                return (_admira_minimax_provider(), _admira_minimax_model(), str(raw_input or "").strip().lower())
            return original_resolve_alias(raw_input, current_provider)

        model_switch._admira_original_resolve_alias = original_resolve_alias
        model_switch.resolve_alias = patched_resolve_alias

    original_switch_model = getattr(model_switch, "switch_model", None)
    if callable(original_switch_model):
        def patched_switch_model(
            raw_input,
            current_provider,
            current_model,
            current_base_url="",
            current_api_key="",
            is_global=False,
            explicit_provider="",
            user_providers=None,
            custom_providers=None,
        ):
            requested_minimax = _is_admira_minimax_value(raw_input)
            native_minimax_provider = _is_admira_minimax_provider(explicit_provider)
            if requested_minimax or native_minimax_provider:
                raw_input = _admira_minimax_model()
                explicit_provider = _admira_minimax_provider()
                user_providers = _ensure_admira_minimax_user_provider(user_providers)
            result = original_switch_model(
                raw_input=raw_input,
                current_provider=current_provider,
                current_model=current_model,
                current_base_url=current_base_url,
                current_api_key=current_api_key,
                is_global=is_global,
                explicit_provider=explicit_provider,
                user_providers=user_providers,
                custom_providers=custom_providers,
            )
            if _model_switch_succeeded(result):
                result_provider = result.get("provider") if isinstance(result, dict) else ""
                result_model = result.get("model") if isinstance(result, dict) else ""
                result_base_url = result.get("base_url") if isinstance(result, dict) else ""
                selected_provider = result_provider or explicit_provider or current_provider
                selected_model = result_model or raw_input or current_model
                selected_base_url = result_base_url or (
                    _admira_minimax_base_url() if _is_admira_minimax_provider(selected_provider) else current_base_url
                )
                _write_runtime_model_state(selected_provider, selected_model, selected_base_url)
            return result

        model_switch._admira_original_switch_model = original_switch_model
        model_switch.switch_model = patched_switch_model

    original_list_authenticated = getattr(model_switch, "list_authenticated_providers", None)
    if callable(original_list_authenticated):
        def patched_list_authenticated_providers(*args, **kwargs):
            rows = list(original_list_authenticated(*args, **kwargs) or [])
            # Hide Hermes' native MiniMax row in Admira installs. MiniMax M3 is
            # intentionally exposed through the official OpenAI-compatible
            # custom provider, not Hermes' native provider transport.
            if os.environ.get(ADMIRA_MINIMAX_KEY_ENV):
                rows = [row for row in rows if str((row or {}).get("slug") or "").strip().lower() != "minimax"]
            for row in rows:
                slug = str((row or {}).get("slug") or "").strip().lower()
                if slug == "admira-minimax":
                    row["name"] = "MiniMax M3 oficial"
            return rows

        model_switch._admira_original_list_authenticated_providers = original_list_authenticated
        model_switch.list_authenticated_providers = patched_list_authenticated_providers

    original_list_picker = getattr(model_switch, "list_picker_providers", None)
    if callable(original_list_picker):
        def patched_list_picker_providers(*args, **kwargs):
            rows = list(original_list_picker(*args, **kwargs) or [])
            if os.environ.get(ADMIRA_MINIMAX_KEY_ENV):
                rows = [row for row in rows if str((row or {}).get("slug") or "").strip().lower() != "minimax"]
            for row in rows:
                slug = str((row or {}).get("slug") or "").strip().lower()
                if slug == "admira-minimax":
                    row["name"] = "MiniMax M3 oficial"
            return rows

        model_switch._admira_original_list_picker_providers = original_list_picker
        model_switch.list_picker_providers = patched_list_picker_providers

    model_switch._admira_minimax_official_patch = True
    return True


def _patch_minimax_runtime_provider():
    try:
        import hermes_cli.runtime_provider as runtime_provider
    except Exception:
        return False
    if getattr(runtime_provider, "_admira_minimax_official_patch", False):
        return True
    original_get_named = getattr(runtime_provider, "_get_named_custom_provider", None)
    if not callable(original_get_named):
        return False

    def patched_get_named_custom_provider(requested_provider):
        found = original_get_named(requested_provider)
        if found:
            return found
        if _is_admira_minimax_provider(requested_provider):
            entry = _admira_minimax_provider_entry()
            return {
                "name": entry["name"],
                "base_url": entry["base_url"],
                "api_key": os.getenv(ADMIRA_MINIMAX_KEY_ENV, "").strip(),
                "key_env": ADMIRA_MINIMAX_KEY_ENV,
                "model": entry["model"],
                "api_mode": entry["api_mode"],
            }
        return None

    runtime_provider._admira_original_get_named_custom_provider = original_get_named
    runtime_provider._get_named_custom_provider = patched_get_named_custom_provider
    runtime_provider._admira_minimax_official_patch = True
    return True


def _patch_gateway_rate_limit_reply():
    try:
        import gateway.run as gateway_run
    except Exception:
        return False
    original = getattr(gateway_run, "_gateway_provider_error_reply", None)
    if not callable(original):
        return False
    if getattr(gateway_run, "_admira_rate_limit_reply_patch", False):
        return True

    def patched_gateway_provider_error_reply(text):
        return provider_error_reply(text, os.environ.get("ADMIRA_GATEWAY_LANGUAGE", "es"), original)

    gateway_run._admira_original_gateway_provider_error_reply = original
    gateway_run._gateway_provider_error_reply = patched_gateway_provider_error_reply
    gateway_run._admira_rate_limit_reply_patch = True
    return True


def _patch_gateway_generated_media_delivery():
    try:
        import gateway.run as gateway_run
    except Exception:
        return False
    runner = getattr(gateway_run, "GatewayRunner", None)
    original = getattr(runner, "_run_agent", None) if runner is not None else None
    if not callable(original):
        return False
    if getattr(runner, "_admira_generated_media_delivery_patch", False):
        return True

    async def patched_run_agent(self, *args, **kwargs):
        result = await original(self, *args, **kwargs)
        try:
            result = _guard_unconfirmed_persistence_claim(result)
        except Exception:
            pass
        try:
            result = _append_generated_media_attachments(result)
        except Exception:
            pass
        try:
            if isinstance(result, dict):
                _append_gateway_turn("agent", result.get("final_response") or result.get("response") or result.get("message") or "")
            else:
                _append_gateway_turn("agent", result)
        except Exception:
            pass
        return result

    runner._admira_original_run_agent = original
    runner._run_agent = patched_run_agent
    runner._admira_generated_media_delivery_patch = True
    return True


def _patch_gateway_inbound_video_frames():
    try:
        import gateway.run as gateway_run
    except Exception:
        return False
    runner = getattr(gateway_run, "GatewayRunner", None)
    original = getattr(runner, "_prepare_inbound_message_text", None) if runner is not None else None
    if not callable(original):
        return False
    if getattr(runner, "_admira_inbound_video_frame_patch", False):
        return True

    async def patched_prepare_inbound_message_text(self, *args, **kwargs):
        event = kwargs.get("event")
        if event is None and args:
            # _prepare_inbound_message_text is keyword-only in current Hermes,
            # but this makes the patch tolerant if the signature changes.
            event = args[0]
        if event is not None:
            try:
                _append_video_frame_inputs_to_event(event)
            except Exception:
                pass
        result = await original(self, *args, **kwargs)
        try:
            _append_gateway_turn("user", result)
        except Exception:
            pass
        return result

    runner._admira_original_prepare_inbound_message_text = original
    runner._prepare_inbound_message_text = patched_prepare_inbound_message_text
    runner._admira_inbound_video_frame_patch = True
    return True


def apply():
    rate_limit_patched = _patch_gateway_rate_limit_reply()
    minimax_patched = _patch_minimax_model_switch()
    runtime_patched = _patch_minimax_runtime_provider()
    media_patched = _patch_gateway_generated_media_delivery()
    video_patched = _patch_gateway_inbound_video_frames()
    return bool(rate_limit_patched or minimax_patched or runtime_patched or media_patched or video_patched)
