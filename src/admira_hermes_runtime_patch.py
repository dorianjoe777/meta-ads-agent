#!/usr/bin/env python3
"""Runtime patches for third-party Hermes gateway buyer-facing messages.

The Hermes gateway is installed as a dependency inside the buyer container.
Admira should not edit site-packages in place, so this module is loaded through
PYTHONPATH/sitecustomize only for the gateway process and wraps the narrow
provider-error formatter that can otherwise leak raw English provider text.
"""
import os
import re
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


def provider_error_reply(text, language=None, original=None):
    if is_rate_limit_text(text):
        return gateway_rate_limit_reply(text, language or os.environ.get("ADMIRA_GATEWAY_LANGUAGE", "es"))
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


def _append_generated_media_attachments(response):
    """Append native MEDIA directives for generated images in any result shape."""
    if not isinstance(response, dict):
        return response
    final_response = str(response.get("final_response") or "")
    paths = _collect_generated_media_paths(response)
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
            return original_switch_model(
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
            return _append_generated_media_attachments(result)
        except Exception:
            return result

    runner._admira_original_run_agent = original
    runner._run_agent = patched_run_agent
    runner._admira_generated_media_delivery_patch = True
    return True


def apply():
    rate_limit_patched = _patch_gateway_rate_limit_reply()
    minimax_patched = _patch_minimax_model_switch()
    runtime_patched = _patch_minimax_runtime_provider()
    media_patched = _patch_gateway_generated_media_delivery()
    return bool(rate_limit_patched or minimax_patched or runtime_patched or media_patched)
