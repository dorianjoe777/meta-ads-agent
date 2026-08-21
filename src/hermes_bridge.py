#!/usr/bin/env python3
"""Hermes Agent bridge for dashboard and Telegram conversations."""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

from agent_runtime import build_system_prompt
from communication_style import ad_experience_from_environment, ad_experience_instruction, communication_style_from_environment, communication_style_instruction
from decision_memory import decision_memory_payload, format_learning_log
from experiment_scheduler import experiment_review_payload
from local_store import read_json
from optimization_engine import load_optimization_state
from optimization_research import load_research
from admira_rate_limit_messages import (
    codex_go_limit_reply,
    codex_plan_type_from_text,
    is_rate_limit_text,
    lighter_model_switch_hint,
    localized_textual_hint,
    retry_delay_hint,
    retry_seconds_from_text,
    textual_retry_hint,
)
from security import redact_payload

try:
    from product_config import DEFAULT_NVIDIA_NIM_MODEL, agent_model_connections, normalize_hermes_model, normalize_nvidia_model, preferred_hermes_model
except ImportError:
    DEFAULT_NVIDIA_NIM_MODEL = "minimaxai/minimax-m3"
    def normalize_hermes_model(value):
        model = str(value or "").strip()
        if not model or model.lower() in {"auto", "recommended", "recomendado", "default"}:
            return "gpt-5.4-mini"
        return model

    def preferred_hermes_model(models):
        return next((str(model).strip() for model in models or [] if str(model).strip()), "gpt-5.4-mini")

    def normalize_nvidia_model(value, user_selected=False):
        model = str(value or "").strip()
        return model if model and (user_selected or model.lower() != "z-ai/glm-5.2") else "minimaxai/minimax-m3"

    def agent_model_connections(config=None, include_secrets=False):
        return {}


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "dashboard" / "data"
BRAND_GUIDES_DIR = ROOT_DIR / "brand_guides"
AGENT_SKILLS_DIR = ROOT_DIR / "agent" / "skills"
HERMES_WORKSPACE_DIR = DATA_DIR / "hermes-workspace" / "current"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ADMIRA_MINIMAX_KEY_ENV = "ADMIRA_MINIMAX_API_KEY"
ADMIRA_MINIMAX_BASE_URL_ENV = "ADMIRA_MINIMAX_BASE_URL"
ADMIRA_MINIMAX_PROVIDER = "admira-minimax"
ADMIRA_MINIMAX_PROVIDER_NAME = "MiniMax M3 oficial"
ADMIRA_NVIDIA_KEY_ENV = "ADMIRA_NVIDIA_API_KEY"
ADMIRA_NVIDIA_BASE_URL_ENV = "ADMIRA_NVIDIA_BASE_URL"
ADMIRA_NVIDIA_PROVIDER = "admira-nvidia"
ADMIRA_CODEX_SUBSCRIPTION_FALLBACK_MODEL = "gpt-5.6-terra"
ADMIRA_NVIDIA_PROVIDER_NAME = "NVIDIA NIM API"
ADMIRA_NVIDIA_DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
ADMIRA_NVIDIA_DEFAULT_MODEL = DEFAULT_NVIDIA_NIM_MODEL
ADMIRA_OPENAI_KEY_ENV = "ADMIRA_OPENAI_API_KEY"
ADMIRA_OPENAI_PROVIDER = "admira-openai"
ADMIRA_CUSTOM_KEY_ENV = "ADMIRA_CUSTOM_API_KEY"
ADMIRA_CUSTOM_PROVIDER = "admira-custom"
ADMIRA_GEMINI_KEY_ENV = "GEMINI_API_KEY"
ADMIRA_GEMINI_PROVIDER = "gemini"
ADMIRA_GEMINI_PROVIDER_NAME = "Google AI Studio"
ADMIRA_GEMINI_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
ADMIRA_GEMINI_DEFAULT_MODEL = "gemini-3.5-flash-lite"
BASE_ALLOWED_IMAGE_DIRS = (
    ROOT_DIR / "output",
    ROOT_DIR / "dashboard" / "data" / "uploads",
    ROOT_DIR / "dashboard" / "data" / "content-assets",
    ROOT_DIR / "dashboard" / "data" / "hermes-home" / "cache" / "images",
)
IMAGE_PATH_TEXT_KEYS = {
    "request",
    "prompt",
    "image_prompt",
    "reference_image_summary",
    "message",
    "text",
    "description",
    "image_path",
    "photo_path",
    "asset_path",
    "real_photo_path",
    "reference_image_path",
}
EMBEDDED_IMAGE_PATH_RE = re.compile(r"(?P<path>(?:~|/|\.{1,2}/)?(?:[^\s\"'<>|]+/)+[^\s\"'<>|]+\.(?:jpe?g|png|webp|gif))", re.IGNORECASE)
MEMORY_TEXT_LIMIT = 14000
MEMORY_ITEM_LIMIT = 8
RECENT_CONTEXT_LOOKBACK_DAYS = 7
RECENT_CONTEXT_ITEM_LIMIT = 12
BLOCKED_MEMORY_TOKENS = {".env", "license_unlock.json"}
PROFILE_FILES = ("SOUL.md", "USER.md", "AGENTS.md", "TOOLS.md", "SKILLS.md")
# The versioned skills and their generated buyer-state companions are the
# detailed operating manual.  Do not concatenate every legacy profile into
# the root AGENTS.md: NVIDIA's hosted models have a much smaller *practical*
# context window than their advertised maximum and Hermes truncates context
# files before the agent can read a specialist skill.  Keep the root profile
# to identity + buyer preferences + the concise runtime contract below, then
# have the agent load the relevant official skill on demand.
COMBINED_AGENT_PROFILE_FILES = ("SOUL.md", "USER.md")
SKILL_FILE_NAME = "SKILL.md"
HERMES_CONTEXT_FILE_SAFE_MAX_CHARS = 60000
CODEX_MODEL_CATALOG_FILE = DATA_DIR / "codex_model_catalog.json"
NVIDIA_MODEL_CATALOG_FILE = DATA_DIR / "nvidia_model_catalog.json"
# A same-key NIM fallback is useful only when the model catalog was recently
# verified against NVIDIA.  A stale/safe catalog must never manufacture a
# second route that may not exist for the buyer's key.
NVIDIA_LIVE_CATALOG_MAX_AGE_SECONDS = 6 * 60 * 60
# A hosted NIM pool can be temporarily saturated while other models behind
# the same buyer key remain healthy. These are bounded, model-specific
# alternates (never retries of the model that just failed).
NVIDIA_SAME_KEY_FALLBACK_LIMIT = 4
MODEL_USAGE_LIMIT_PATTERNS = (
    r"\b429\b",
    r"too many requests",
    r"rate limit",
    r"rate-limiting",
    r"rate limited",
    r"usage limit",
    r"usage cap",
    r"usage exhausted",
    r"message limit",
    r"limit reached",
    r"reached (?:your|the) limit",
    r"reached (?:your|the) .* cap",
    r"hit (?:your|the) .* limit",
    r"maximum usage",
    r"cap reached",
    r"quota exceeded",
    r"insufficient quota",
    r"temporarily unavailable due to limits",
    r"limite de uso",
    r"límite de uso",
    r"limite temporal",
    r"límite temporal",
    r"cuota excedida",
)


def split_csv(value):
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def controlled_hermes_toolsets(values):
    """Keep Hermes' runtime skill library out of the buyer-facing product.

    Admira ships its official skills as versioned workspace files. Hermes'
    personal `skills` toolset can create or patch a separate per-installation
    library, which makes two buyers drift into different behavior. Keep the
    useful runtime tools, but never expose that mutable skill manager.
    """
    return [item for item in values if str(item or "").strip() != "skills"]


def enforce_official_skill_catalog(home):
    """Quarantine legacy Hermes-created skills without deleting buyer data."""
    home = Path(home)
    skills_dir = home / "skills"
    archive_dir = home / "disabled-agent-skills"
    moved = []
    if skills_dir.exists():
        entries = []
        for entry in skills_dir.iterdir():
            if entry.name == "README.md":
                try:
                    if "Hermes personal skill creation and patching are disabled" in entry.read_text(encoding="utf-8"):
                        continue
                except OSError:
                    pass
            entries.append(entry)
        if entries:
            archive_dir.mkdir(parents=True, exist_ok=True)
            for entry in entries:
                target = archive_dir / entry.name
                if target.exists():
                    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    target = archive_dir / f"{entry.name}.{suffix}"
                try:
                    shutil.move(str(entry), str(target))
                    moved.append(str(target))
                except OSError:
                    # A read-only legacy skill must not prevent the agent from
                    # starting; the disabled toolset still blocks mutation/use.
                    continue
    skills_dir.mkdir(parents=True, exist_ok=True)
    try:
        (skills_dir / "README.md").write_text(
            "Admira IA uses only the versioned official skills copied into the current workspace.\n"
            "Hermes personal skill creation and patching are disabled for this product.\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    return moved


def _quote_yaml(value):
    return json.dumps(str(value or ""), ensure_ascii=False)


def hermes_home_path(config):
    path = Path(str(getattr(config, "hermes_home", "") or DATA_DIR / "hermes-home")).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def _hermes_model_config_lines(brain):
    """Return Hermes model config lines for the selected Admira brain.

    MiniMax M3 must use the official MiniMax OpenAI-compatible endpoint, not
    OpenRouter. Hermes' native MiniMax provider can lag the official model
    catalog, so Admira exposes it as a named custom provider while keeping the
    API key only in the process environment.
    """
    model_provider = brain.get("provider") or "openai-codex"
    model_default = brain.get("model") or normalize_hermes_model("")
    base_url = str(brain.get("base_url") or "").strip().rstrip("/")
    lines = [
        "model:",
        f"  provider: {_quote_yaml(model_provider)}",
        f"  default: {_quote_yaml(model_default)}",
    ]
    if brain.get("brain") == "minimax":
        provider_slug = ADMIRA_MINIMAX_PROVIDER
        provider_name = ADMIRA_MINIMAX_PROVIDER_NAME
        official_base_url = base_url or "https://api.minimax.io/v1"
        lines = [
            "model:",
            f"  provider: {_quote_yaml(provider_slug)}",
            f"  default: {_quote_yaml(model_default)}",
            "providers:",
            f"  {provider_slug}:",
            f"    name: {_quote_yaml(provider_name)}",
            f"    base_url: {_quote_yaml(official_base_url)}",
            f"    key_env: {_quote_yaml(ADMIRA_MINIMAX_KEY_ENV)}",
            "    api_mode: \"chat_completions\"",
            f"    model: {_quote_yaml(model_default)}",
            "    models:",
            f"      {_quote_yaml(model_default)}: {{}}",
            "model_aliases:",
            f"  {_quote_yaml(model_default)}:",
            f"    model: {_quote_yaml(model_default)}",
            f"    provider: {_quote_yaml(provider_slug)}",
            f"    base_url: {_quote_yaml(official_base_url)}",
            "  \"minimax m3\":",
            f"    model: {_quote_yaml(model_default)}",
            f"    provider: {_quote_yaml(provider_slug)}",
            f"    base_url: {_quote_yaml(official_base_url)}",
            "  \"minimax-m3\":",
            f"    model: {_quote_yaml(model_default)}",
            f"    provider: {_quote_yaml(provider_slug)}",
            f"    base_url: {_quote_yaml(official_base_url)}",
            "  \"minimax\":",
            f"    model: {_quote_yaml(model_default)}",
            f"    provider: {_quote_yaml(provider_slug)}",
            f"    base_url: {_quote_yaml(official_base_url)}",
        ]
    elif brain.get("brain") == "nvidia_nim":
        provider_slug = ADMIRA_NVIDIA_PROVIDER
        official_base_url = base_url or ADMIRA_NVIDIA_DEFAULT_BASE_URL
        lines = [
            "model:",
            f"  provider: {_quote_yaml(provider_slug)}",
            f"  default: {_quote_yaml(model_default)}",
            *([f"  context_length: {int(brain['context_length'])}"] if brain.get("context_length") else []),
            "providers:",
            f"  {provider_slug}:",
            f"    name: {_quote_yaml(ADMIRA_NVIDIA_PROVIDER_NAME)}",
            f"    base_url: {_quote_yaml(official_base_url)}",
            f"    key_env: {_quote_yaml(ADMIRA_NVIDIA_KEY_ENV)}",
            "    api_mode: \"chat_completions\"",
            f"    model: {_quote_yaml(model_default)}",
            "    models:",
            f"      {_quote_yaml(model_default)}: {{}}",
            "model_aliases:",
            f"  {_quote_yaml(model_default)}:",
            f"    model: {_quote_yaml(model_default)}",
            f"    provider: {_quote_yaml(provider_slug)}",
            f"    base_url: {_quote_yaml(official_base_url)}",
            "  \"nvidia\":",
            f"    model: {_quote_yaml(model_default)}",
            f"    provider: {_quote_yaml(provider_slug)}",
            f"    base_url: {_quote_yaml(official_base_url)}",
            "  \"nvidia nim\":",
            f"    model: {_quote_yaml(model_default)}",
            f"    provider: {_quote_yaml(provider_slug)}",
            f"    base_url: {_quote_yaml(official_base_url)}",
        ]
    return lines


def _admira_provider_metadata(provider, connection):
    metadata = {
        "minimax": (ADMIRA_MINIMAX_PROVIDER, ADMIRA_MINIMAX_PROVIDER_NAME, ADMIRA_MINIMAX_KEY_ENV, ("minimax", "minimax m3", "minimax-m3")),
        "nvidia_nim": (ADMIRA_NVIDIA_PROVIDER, ADMIRA_NVIDIA_PROVIDER_NAME, ADMIRA_NVIDIA_KEY_ENV, ("nvidia", "nvidia nim")),
        "gemini": (ADMIRA_GEMINI_PROVIDER, ADMIRA_GEMINI_PROVIDER_NAME, ADMIRA_GEMINI_KEY_ENV, ("gemini", "google", "google ai studio")),
        "openai_api": (ADMIRA_OPENAI_PROVIDER, "OpenAI API", ADMIRA_OPENAI_KEY_ENV, ("openai api",)),
        "custom_api": (ADMIRA_CUSTOM_PROVIDER, "API compatible guardada", ADMIRA_CUSTOM_KEY_ENV, ("api compatible", "custom api")),
    }
    slug, name, key_env, aliases = metadata[provider]
    return {
        "provider": provider,
        "slug": slug,
        "name": name,
        "key_env": key_env,
        "aliases": aliases,
        "base_url": str(connection.get("base_url") or "").strip().rstrip("/"),
        "model": str(connection.get("model") or "").strip(),
    }


def admira_connected_model_config_lines(config, primary_settings=None):
    """Build one Hermes catalog containing every saved buyer connection."""
    brain = dict(primary_settings or hermes_brain_settings(config))
    connections = agent_model_connections(config, include_secrets=True)
    configured = [
        _admira_provider_metadata(provider, connection)
        for provider, connection in connections.items()
        if connection.get("configured")
    ]
    primary_brain = str(brain.get("brain") or "gemini")
    primary_slugs = {
        "minimax": ADMIRA_MINIMAX_PROVIDER,
        "nvidia_nim": ADMIRA_NVIDIA_PROVIDER,
        "gemini": ADMIRA_GEMINI_PROVIDER,
        "openai_api": ADMIRA_OPENAI_PROVIDER,
        "custom_api": ADMIRA_CUSTOM_PROVIDER,
    }
    primary_provider = primary_slugs.get(primary_brain, str(brain.get("provider") or "openai-codex"))
    primary_model = str(brain.get("model") or normalize_hermes_model("")).strip()
    lines = [
        "model:",
        f"  provider: {_quote_yaml(primary_provider)}",
        f"  default: {_quote_yaml(primary_model)}",
        *([f"  context_length: {int(brain['context_length'])}"] if brain.get("context_length") else []),
    ]
    # Native Gemini is registered by Hermes itself. Do not shadow it
    # with a named OpenAI-compatible provider block. Other saved
    # connections remain available as explicit fallbacks.
    custom_configured = [
        item for item in configured
        if item["provider"] not in {"gemini", "nvidia_nim"}
    ]
    if not custom_configured:
        return lines
    lines.append("providers:")
    for item in custom_configured:
        lines.extend([
            f"  {item['slug']}:",
            f"    name: {_quote_yaml(item['name'])}",
            f"    base_url: {_quote_yaml(item['base_url'])}",
            f"    key_env: {_quote_yaml(item['key_env'])}",
            "    api_mode: \"chat_completions\"",
            f"    model: {_quote_yaml(item['model'])}",
            "    models:",
            f"      {_quote_yaml(item['model'])}: {{}}",
        ])
    lines.append("model_aliases:")
    seen = set()
    for item in custom_configured:
        for alias in (item["model"], *item["aliases"]):
            alias_key = str(alias or "").strip()
            if not alias_key or alias_key in seen:
                continue
            seen.add(alias_key)
            lines.extend([
                f"  {_quote_yaml(alias)}:",
                f"    model: {_quote_yaml(item['model'])}",
                f"    provider: {_quote_yaml(item['slug'])}",
                f"    base_url: {_quote_yaml(item['base_url'])}",
            ])
    return lines


def _runtime_provider_for_brain(brain):
    if (brain or {}).get("brain") == "minimax":
        return ADMIRA_MINIMAX_PROVIDER
    if (brain or {}).get("brain") == "nvidia_nim":
        return ADMIRA_NVIDIA_PROVIDER
    if (brain or {}).get("brain") == "gemini":
        return ADMIRA_GEMINI_PROVIDER
    if (brain or {}).get("brain") == "openai_api":
        return ADMIRA_OPENAI_PROVIDER
    if (brain or {}).get("brain") == "custom_api":
        return ADMIRA_CUSTOM_PROVIDER
    return str((brain or {}).get("provider") or "openai-codex").strip() or "openai-codex"


def _cached_model_ids(path, limit=40):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return []
    values = payload.get("models") if isinstance(payload, dict) else []
    models = []
    seen = set()
    for value in values or []:
        model = str(value or "").strip()
        key = model.lower()
        if not model or key in seen or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{1,100}", model):
            continue
        seen.add(key)
        models.append(model)
    try:
        maximum = max(1, int(limit))
    except (TypeError, ValueError):
        maximum = 40
    return models[:maximum]


def _live_nvidia_model_ids(path, now=None):
    """Return model IDs from a recent, authenticated NVIDIA catalog only.

    The model list is deliberately not treated as a credential or entitlement
    proof.  It is merely the last successful `/models` response, and therefore
    only qualifies for model-specific failover while it is fresh.  This keeps a
    first-time/offline install honest: no guessed NIM endpoint is added.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict) or payload.get("source") != "nvidia_live_catalog":
        return []
    if not bool(payload.get("account_verified")):
        return []
    try:
        checked_epoch = float(payload.get("checked_epoch") or 0)
    except (TypeError, ValueError):
        return []
    if checked_epoch <= 0:
        return []
    current = float(now if now is not None else time.time())
    age = current - checked_epoch
    if age < 0 or age > NVIDIA_LIVE_CATALOG_MAX_AGE_SECONDS:
        return []
    # The dashboard stores the catalog alphabetically. Restricting it to the
    # first 40 generic entries silently removes late-alphabet models such as
    # GLM and Nemotron before fallback selection. Keep the UI/catalog display
    # bounded elsewhere, but inspect the complete validated NIM list here.
    return _cached_model_ids(path, limit=160)


def _nvidia_model_specific_fallback_order(models, primary_model):
    """Prefer a different live NIM pool, without inventing model IDs."""
    primary_key = str(primary_model or "").strip().lower()
    preferred = (
        # MiniMax M3 is the primary NIM route. The remaining entries are
        # same-key fallbacks only when NVIDIA's live catalog confirms them.
        "minimaxai/minimax-m3",
        # DeepSeek V4 Flash is the first lightweight alternate hosted pool.
        "deepseek-ai/deepseek-v4-flash-0731",
        # Lightning is deliberately ahead of larger reasoning models: it is
        # fast enough to preserve a normal Telegram conversation.
        "nvidia/nemotron-3.5-lightning-30b-a3b",
        "z-ai/glm-5.2",
        # Last-resort high-capability pool. It is used only when each prior
        # live model-specific attempt failed; thinking is disabled at runtime.
        "nvidia/nemotron-3-ultra-550b-a55b",
        "deepseek-ai/deepseek-v4-flash",
        "openai/gpt-oss-20b",
        "nvidia/nemotron-3-nano-30b-a3b",
    )
    ordered = []
    for model in [*preferred, *models]:
        value = str(model or "").strip()
        key = value.lower()
        if not value or key == primary_key or key in {item.lower() for item in ordered}:
            continue
        if value not in models:
            continue
        ordered.append(value)
    return ordered


def _light_model_order(models):
    cleaned = [str(model or "").strip() for model in models or [] if str(model or "").strip()]
    if not cleaned:
        return []
    preferred = preferred_hermes_model(cleaned)
    small_markers = ("mini", "nano", "small", "lite", "flash", "20b")
    ordered = []
    for model in [preferred, *[item for item in cleaned if any(marker in item.lower() for marker in small_markers)], *cleaned]:
        if model and model not in ordered:
            ordered.append(model)
    return ordered


def inference_runtime_policy(primary_settings=None):
    """Return bounded inference settings for the selected product brain.

    Hosted/free NVIDIA NIM capacity can be account-wide for quota/auth errors,
    while individual model pools can still fail independently. Retrying the
    same request several times, or exhausting several NVIDIA models after a
    shared 429, turns one temporary limit into an avoidable burst. Keep the
    primary route conservative; the runtime guard permits one live-catalog
    model fallback only for model-specific transport failures.
    """
    brain = dict(primary_settings or {})
    is_nvidia = _runtime_provider_for_brain(brain) == ADMIRA_NVIDIA_PROVIDER
    gemini_model = str(brain.get("model") or "").strip().lower()
    is_gemini_35 = (
        _runtime_provider_for_brain(brain) == ADMIRA_GEMINI_PROVIDER
        # Product defaults can move between Flash and Flash Lite. Both 3.5
        # Flash routes share the free-tier token-pressure behavior this policy
        # protects against, so do not key the guard to one default constant.
        and gemini_model.startswith("gemini-3.5-flash")
    )
    policy = {
        # Hosted/free NIM endpoints enforce a shared request quota.  A retry
        # after a 429 is not useful and can turn one user turn into a burst;
        # the cross-process request gate plus an independent configured
        # provider fallback are safer than retrying the same NIM call.
        "api_max_retries": 0 if is_nvidia else (1 if is_gemini_35 else 3),
        # One buyer message can consume one inference call per tool turn. Keep
        # the free hosted NVIDIA route bounded so a normal request cannot fan
        # out into dozens of calls and exhaust its shared capacity.
        "max_turns": 10 if is_nvidia else (12 if is_gemini_35 else 60),
        "cron_max_parallel": 1 if (is_nvidia or is_gemini_35) else 0,
        "disable_delegation": is_nvidia or is_gemini_35,
        # A failed summary must never freeze a buyer session. Hermes keeps the
        # protected head/tail and drops the middle window as a last resort;
        # Admira's durable workspace memory remains available to recover it.
        "compression_abort_on_failure": False,
        "compression_timeout": 45,
    }
    if is_nvidia:
        # NVIDIA's hosted endpoint can return a generic 5xx well before the
        # advertised model window.  Treat 80K as the operational ceiling and
        # summarize at 45%, rather than waiting for a request near 120K to
        # fail.  Durable Admira memory keeps the business state intact while
        # Hermes condenses old chat/tool turns.
        policy.update({
            "model_context_length": 80000,
            # Keep the large product prompt from consuming most of the
            # operational window before the conversation itself is sent.
            "context_file_max_chars": 30000,
            "compression_threshold": 0.45,
            "compression_target_ratio": 0.20,
            "compression_protect_first_n": 1,
            "compression_protect_last_n": 6,
            "compression_hard_message_limit": 24,
            # Use the explicit named provider. Hermes' generic "main" alias
            # can fail to resolve named OpenAI-compatible providers, leaving
            # oversized NVIDIA sessions unable to produce a summary.
            # Hermes versions used by existing installs do not all resolve
            # Admira's named custom providers from auxiliary tasks. Route the
            # compressor through the universally supported OpenAI-compatible
            # `custom` provider and inject the NVIDIA key only into the
            # gateway process (never into config files).
            "compression_provider": "custom",
            "compression_model": str(brain.get("model") or ADMIRA_NVIDIA_DEFAULT_MODEL),
            "compression_base_url": str(brain.get("base_url") or ADMIRA_NVIDIA_DEFAULT_BASE_URL).rstrip("/"),
            # Keep a safety margin below NVIDIA's nominal 40 RPM. Hermes has
            # an additional streaming retry loop; the runtime gate spaces
            # starts across Telegram, dashboard and cron processes.
            "requests_per_minute": 36,
            "min_request_interval_seconds": 1.7,
            "stream_retries": 0,
        })
    else:
        policy.update({
            "model_context_length": 0,
            "context_file_max_chars": HERMES_CONTEXT_FILE_SAFE_MAX_CHARS,
            "compression_threshold": 0.85,
            "compression_target_ratio": 0.20,
            "compression_protect_first_n": 3,
            "compression_protect_last_n": 20,
            "compression_hard_message_limit": 400,
            "compression_provider": "",
            "compression_model": "",
            "compression_base_url": "",
        })
        if is_gemini_35:
            policy.update({
                # Gemini's free tier is constrained by input tokens per
                # minute, not only by the model's 1M-token context window.
                # Compress at Hermes' safe 64K floor so one multi-tool turn
                # does not resend a 70K+ session several times and exhaust
                # the project quota.
                "compression_threshold": 0.06,
                "compression_protect_last_n": 12,
                "compression_hard_message_limit": 120,
                # Google reports a project/model free-tier quota of 20
                # requests per day. Reserve two for operator diagnostics.
                "daily_request_limit": 18,
                # The live free-tier project returned 429 after a sixth
                # request inside one minute. Keep a full request of headroom
                # for Google-side accounting and auxiliary activity.
                "requests_per_minute": 4,
                "min_request_interval_seconds": 15.5,
            })
    return policy


def hermes_compression_config_lines(config, brain, policy=None):
    """Build one safe compression configuration for dashboard and Telegram.

    The same block is emitted by both Hermes entry points so an install cannot
    have a working dashboard compressor but a broken Telegram compressor.
    NVIDIA's auxiliary route uses the generic `custom` resolver with an
    explicit endpoint; the key is supplied through the gateway environment.
    A configured independent provider may be used as a second attempt.
    """
    policy = dict(policy or inference_runtime_policy(brain))
    lines = [
        "compression:",
        "  enabled: true",
        f"  threshold: {policy['compression_threshold']}",
        f"  target_ratio: {policy['compression_target_ratio']}",
        f"  protect_first_n: {policy['compression_protect_first_n']}",
        f"  protect_last_n: {policy['compression_protect_last_n']}",
        f"  hygiene_hard_message_limit: {policy['compression_hard_message_limit']}",
        f"  abort_on_summary_failure: {'true' if policy['compression_abort_on_failure'] else 'false'}",
        "  codex_gpt55_autoraise: false",
    ]
    provider = str(policy.get("compression_provider") or "").strip()
    if not provider:
        return lines

    lines.extend([
        "auxiliary:",
        "  compression:",
        f"    provider: {_quote_yaml(provider)}",
        f"    model: {_quote_yaml(policy.get('compression_model') or brain.get('model') or '')}",
        f"    base_url: {_quote_yaml(policy.get('compression_base_url') or brain.get('base_url') or '')}",
        f"    timeout: {int(policy.get('compression_timeout') or 45)}",
    ])

    # Use only providers with independent credentials. Entries are resolved
    # from the provider catalog/key_env at runtime; no secret is persisted in
    # config.yaml. Never add another NVIDIA model under the same key here.
    fallback_entries = []
    for entry in admira_inference_fallback_chain(config, brain):
        entry_provider = str(entry.get("provider") or "").strip()
        entry_model = str(entry.get("model") or "").strip()
        if not entry_provider or not entry_model:
            continue
        if entry_provider == ADMIRA_NVIDIA_PROVIDER:
            continue
        if any(item["provider"] == entry_provider and item["model"] == entry_model for item in fallback_entries):
            continue
        fallback_entries.append({"provider": entry_provider, "model": entry_model})
    if fallback_entries:
        lines.append("    fallback_chain:")
        for entry in fallback_entries[:4]:
            lines.extend([
                f"      - provider: {_quote_yaml(entry['provider'])}",
                f"        model: {_quote_yaml(entry['model'])}",
            ])
    return lines


def admira_inference_fallback_chain(config, primary_settings=None):
    """Return the single supported subscription fallback for non-Codex brains.

    Admira no longer fails over to NVIDIA/NIM or another API provider. A
    connected ChatGPT/Codex subscription may provide one fallback route through
    Terra. The buyer selected this exact model; it is therefore not inferred
    from an unordered cache and never silently changes to another Codex tier.
    """
    brain = dict(primary_settings or hermes_brain_settings(config))
    primary_provider = _runtime_provider_for_brain(brain)
    primary_model = str(brain.get("model") or "").strip()
    if str(os.environ.get("ADMIRA_HYBRID_ROUTER_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}:
        return []
    if primary_provider == "openai-codex":
        return []

    # A cached Codex model catalog only says which model names Hermes has seen;
    # it does not prove that this buyer has a live Codex OAuth session.  Never
    # place Codex in a fallback chain unless its credential is actually stored
    # and healthy, otherwise a primary-provider failure becomes a misleading
    # second failure (notably for unattended cron jobs).
    try:
        codex_health = codex_credential_health(config)
        codex_fallback_ready = (
            str(codex_health.get("state") or "") == "stored"
            and not bool(codex_health.get("reauth_required"))
        )
    except Exception:
        codex_fallback_ready = False
    if not codex_fallback_ready:
        return []
    return [{
        "provider": "openai-codex",
        "model": ADMIRA_CODEX_SUBSCRIPTION_FALLBACK_MODEL,
    }]


def admira_fallback_config_lines(config, primary_settings=None):
    chain = admira_inference_fallback_chain(config, primary_settings)
    if not chain:
        return ["fallback_providers: []"]
    lines = ["fallback_providers:"]
    for entry in chain:
        lines.extend([
            f"  - provider: {_quote_yaml(entry['provider'])}",
            f"    model: {_quote_yaml(entry['model'])}",
        ])
        if entry.get("base_url"):
            lines.append(f"    base_url: {_quote_yaml(entry['base_url'])}")
        if entry.get("key_env"):
            lines.append(f"    key_env: {_quote_yaml(entry['key_env'])}")
    return lines


def _nvidia_same_key_models_in_fallback_config(config_text):
    """Read only same-provider entries from Hermes' fallback YAML block."""
    match = re.search(
        r"(?ms)^fallback_providers:\s*\n(?P<body>.*?)(?=^[A-Za-z_][A-Za-z0-9_-]*:|\Z)",
        str(config_text or ""),
    )
    if not match:
        return []
    models = []
    for block in re.split(r"(?m)^\s*-\s+provider:", match.group("body"))[1:]:
        provider = block.splitlines()[0].strip().strip("\"'").lower().replace("_", "-")
        if provider != ADMIRA_NVIDIA_PROVIDER:
            continue
        model_match = re.search(r"(?m)^\s+model:\s*[\"']?([^\"'\n]+)", block)
        if model_match:
            models.append(model_match.group(1).strip())
    return models


def hermes_cli_provider(brain):
    if brain.get("brain") == "minimax":
        return ADMIRA_MINIMAX_PROVIDER
    if brain.get("brain") == "nvidia_nim":
        return ADMIRA_NVIDIA_PROVIDER
    if brain.get("brain") == "gemini":
        return ADMIRA_GEMINI_PROVIDER
    if brain.get("brain") == "openai_api":
        return ADMIRA_OPENAI_PROVIDER
    if brain.get("brain") == "custom_api":
        return ADMIRA_CUSTOM_PROVIDER
    return brain.get("provider") or ""


def cli_toolsets(config, payload=None):
    configured = split_csv(getattr(config, "hermes_enabled_toolsets", ""))
    toolsets = controlled_hermes_toolsets(configured or ["memory", "session_search", "vision", "file", "web", "browser"])
    channel = str((payload or {}).get("channel") or "").strip().lower()
    if channel in {"dashboard", "telegram"} or not channel:
        toolsets.append("admira")
    if channel in {"dashboard", "telegram"}:
        try:
            from admira_hermes_runtime_patch import _admira_campaign_edit_requested
            edit_turn = _admira_campaign_edit_requested([
                {"role": "user", "content": str((payload or {}).get("message") or "")}
            ])
        except Exception:
            edit_turn = False
        if edit_turn:
            # Existing-campaign mutations must go through the official MCP.
            # Keep model interpretation, live reads and approval handling, but
            # do not let a provider imitate a Meta edit by patching snapshots.
            toolsets = [value for value in toolsets if value not in {"file", "terminal", "code_execution"}]
    seen = set()
    unique = []
    for toolset in toolsets:
        key = str(toolset or "").strip()
        if key and key not in seen:
            unique.append(key)
            seen.add(key)
    return unique


def _cli_hermes_config_needs_write(config_text, brain, config=None):
    if "mcp_servers:" not in config_text or "admira_mcp_server.py" not in config_text:
        return True
    if "creation_nudge_interval: 0" not in config_text or "memory_notifications: off" not in config_text:
        return True
    if f"context_file_max_chars: {HERMES_CONTEXT_FILE_SAFE_MAX_CHARS}" not in config_text or "fallback_providers:" not in config_text:
        return True
    image_model = normalize_hermes_model(
        getattr(config, "codex_image_hermes_model", "") or getattr(config, "hermes_model", "")
    )
    if f'CODEX_IMAGE_HERMES_MODEL: "{image_model}"' not in config_text:
        return True
    if re.search(r"(?m)^\s*-\s+skills\s*$", config_text):
        return True
    if brain.get("brain") == "minimax":
        lowered = config_text.lower()
        return "admira-minimax" not in config_text or "providers:" not in config_text or "api.minimax.io/v1" not in config_text or "openrouter" in lowered or "custom:admira-minimax" in config_text
    if brain.get("brain") == "gemini":
        policy = inference_runtime_policy(brain)
        fallback_model_line = f'    model: "{ADMIRA_CODEX_SUBSCRIPTION_FALLBACK_MODEL}"'
        return (
            'provider: "gemini"' not in config_text
            or f'default: "{brain.get("model")}"' not in config_text
            or f"  threshold: {policy['compression_threshold']}" not in config_text
            or f"  protect_last_n: {policy['compression_protect_last_n']}" not in config_text
            or f"  hygiene_hard_message_limit: {policy['compression_hard_message_limit']}" not in config_text
            or "admira-nvidia" in config_text.lower()
            or '- provider: "openai-codex"' not in config_text
            or fallback_model_line not in config_text
        )
    if brain.get("brain") == "nvidia_nim":
        lowered = config_text.lower()
        policy = inference_runtime_policy(brain)
        live_models = _live_nvidia_model_ids(NVIDIA_MODEL_CATALOG_FILE)
        expected_same_key = _nvidia_model_specific_fallback_order(
            live_models, brain.get("model")
        )[:NVIDIA_SAME_KEY_FALLBACK_LIMIT]
        existing_same_key = _nvidia_same_key_models_in_fallback_config(config_text)
        deepseek_is_not_live = (
            # Match only the retired bare ID. A valid live successor such as
            # ``deepseek-v4-flash-0731`` must not trigger a rewrite just
            # because it contains the legacy value as a prefix.
            bool(re.search(
                r'(?m)^\s*model:\s*["\']deepseek-ai/deepseek-v4-flash["\']\s*$',
                config_text,
            ))
            and "deepseek-ai/deepseek-v4-flash" not in {item.lower() for item in live_models}
        )
        return (
            "admira-nvidia" not in lowered
            or "integrate.api.nvidia.com/v1" not in lowered
            or "providers:" not in lowered
            or f"context_file_max_chars: {policy['context_file_max_chars']}" not in config_text
            or f"  context_length: {policy['model_context_length']}" not in config_text
            or f"  api_max_retries: {policy['api_max_retries']}" not in config_text
            or f"  threshold: {policy['compression_threshold']}" not in config_text
            or f"  hygiene_hard_message_limit: {policy['compression_hard_message_limit']}" not in config_text
            or "abort_on_summary_failure: false" not in config_text
            or '    provider: "custom"' not in config_text
            or f"    base_url: \"{policy['compression_base_url']}\"" not in config_text
            # NVIDIA retired this model.  Existing installations may retain
            # the old fallback block even after updating product code, which
            # turns an otherwise recoverable provider stall into a guaranteed
            # 410 failure.  Rewrite the generated config once it is seen.
            or deepseek_is_not_live
            # Keep the fallback block synchronized with the live catalog:
            # add the one current model-specific candidate after a refresh,
            # or remove old same-key entries when the catalog is stale/missing.
            or existing_same_key != expected_same_key
        )
    return False


def write_cli_hermes_config(config, workspace_info, payload=None):
    """Ensure Hermes CLI chats have the same safe Admira MCP tools as Telegram.

    The dashboard chat already routes through Hermes, but Hermes only gains
    product "hands" when its home has the Admira MCP server registered. This
    writer is intentionally conservative: if a gateway-generated config already
    has the Admira MCP server, it leaves that richer config untouched.
    """
    home = hermes_home_path(config)
    enforce_official_skill_catalog(home)
    config_path = home / "config.yaml"
    brain = hermes_brain_settings(config)
    inference_policy = inference_runtime_policy(brain)
    if inference_policy["model_context_length"]:
        brain = {**brain, "context_length": inference_policy["model_context_length"]}
    existing = ""
    if config_path.exists():
        try:
            existing = config_path.read_text(encoding="utf-8")
        except OSError:
            existing = ""
    if existing and not _cli_hermes_config_needs_write(existing, brain, config):
        return {"hermes_home": str(home), "config": str(config_path), "written": False}

    timezone_name = str(getattr(config, "daily_brief_timezone", "UTC") or "UTC")
    workspace_path = str(workspace_info.get("path") or HERMES_WORKSPACE_DIR)
    mcp_server_path = ROOT_DIR / "src" / "admira_mcp_server.py"
    disabled = split_csv(getattr(config, "hermes_disabled_toolsets", ""))
    for protected in ("terminal", "code_execution", "image_gen", "skills"):
        if protected not in disabled:
            disabled.append(protected)
    if inference_policy["disable_delegation"] and "delegation" not in disabled:
        disabled.append("delegation")
    dashboard_toolsets = cli_toolsets(config, {"channel": "dashboard"})
    telegram_toolsets = ["hermes-telegram", *cli_toolsets(config, {"channel": "telegram"})]
    config_yaml = [
        f"timezone: {_quote_yaml(timezone_name)}",
        *admira_connected_model_config_lines(config, brain),
        *admira_fallback_config_lines(config, brain),
        f"context_file_max_chars: {inference_policy['context_file_max_chars']}",
        "agent:",
        f"  max_turns: {min(inference_policy['max_turns'], max(1, int(getattr(config, 'hermes_max_iterations', 12) or 12)))}",
        f"  api_max_retries: {inference_policy['api_max_retries']}",
        "  disabled_toolsets:",
        *[f"    - {toolset}" for toolset in disabled],
        "skills:",
        "  creation_nudge_interval: 0",
        "display:",
        "  memory_notifications: off",
        *hermes_compression_config_lines(config, brain, inference_policy),
        "mcp_servers:",
        "  admira:",
        "    enabled: true",
        f"    command: {_quote_yaml(sys.executable)}",
        "    args:",
        f"      - {_quote_yaml(str(mcp_server_path))}",
        "    env:",
        f"      PYTHONPATH: {_quote_yaml(str(ROOT_DIR / 'src'))}",
        f"      ADMIRA_PRODUCT_ROOT: {_quote_yaml(str(ROOT_DIR))}",
        f"      CODEX_IMAGE_HERMES_MODEL: {_quote_yaml(normalize_hermes_model(getattr(config, 'codex_image_hermes_model', '') or getattr(config, 'hermes_model', '')))}",
        '      ADMIRA_HEAVY_TOOL_TIMEOUT_SECONDS: "300"',
        # Hermes filters the parent process environment before launching MCP.
        # Declare both paths explicitly so a stale product .env cannot send the
        # image bridge back to dashboard/data/hermes-home or runtime/codex.
        f"      HERMES_HOME: {_quote_yaml(str(home))}",
        f"      CODEX_HOME: {_quote_yaml(str(home / 'codex-auth'))}",
        "    timeout: 900",
        "    connect_timeout: 45",
        "    keepalive_interval: 1200",
        "terminal:",
        f"  cwd: {_quote_yaml(workspace_path)}",
        "telegram:",
        "  gateway_restart_notification: false",
        "  reactions: false",
        "platform_toolsets:",
        "  dashboard:",
        *[f"    - {toolset}" for toolset in dashboard_toolsets],
        "  telegram:",
        *[f"    - {toolset}" for toolset in telegram_toolsets],
        "  cli:",
        *[f"    - {toolset}" for toolset in dashboard_toolsets],
        "streaming:",
        "  enabled: false",
        "hooks_auto_accept: true",
    ]
    config_path.write_text("\n".join(config_yaml).rstrip() + "\n", encoding="utf-8")
    try:
        config_path.chmod(0o600)
    except OSError:
        pass
    return {"hermes_home": str(home), "config": str(config_path), "written": True}


def allowed_image_dirs():
    roots = [*BASE_ALLOWED_IMAGE_DIRS, HERMES_WORKSPACE_DIR / "uploads"]
    hermes_home = str(os.environ.get("HERMES_HOME") or "").strip()
    if hermes_home:
        roots.append(Path(hermes_home).expanduser() / "cache" / "images")
    return roots


def embedded_image_paths_from_text(value):
    paths = []
    for match in EMBEDDED_IMAGE_PATH_RE.finditer(str(value or "")):
        candidate = match.group("path").strip().rstrip(").,;:]}'\"")
        if candidate:
            paths.append(candidate)
    return paths


def image_path_candidates(value, scan_all_strings=False):
    candidates = []
    if isinstance(value, dict):
        for key in ("image_paths", "reference_image_paths", "images", "files"):
            candidates.extend(image_path_candidates(value.get(key), scan_all_strings=True))
        for key, item in value.items():
            lowered = str(key or "").strip().lower()
            should_scan = scan_all_strings or lowered in IMAGE_PATH_TEXT_KEYS or "image" in lowered or "photo" in lowered
            if should_scan:
                candidates.extend(image_path_candidates(item, scan_all_strings=True))
        return candidates
    if isinstance(value, (list, tuple, set)):
        for item in value:
            candidates.extend(image_path_candidates(item, scan_all_strings=scan_all_strings))
        return candidates
    if isinstance(value, str):
        text = value.strip()
        if text:
            candidates.append(text)
            candidates.extend(embedded_image_paths_from_text(text))
    return candidates


def safe_image_paths(payload, limit=4):
    safe = []
    seen = set()
    for raw_path in image_path_candidates(payload):
        try:
            path = Path(str(raw_path)).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if str(path) in seen:
            continue
        if path.suffix.lower() not in IMAGE_EXTENSIONS or not path.exists() or not path.is_file():
            continue
        allowed = False
        for root in allowed_image_dirs():
            try:
                path.relative_to(root.resolve())
                allowed = True
                break
            except ValueError:
                continue
        if allowed:
            seen.add(str(path))
            safe.append(str(path))
    if limit is None:
        return safe
    try:
        bounded = max(0, int(limit))
    except (TypeError, ValueError):
        bounded = 4
    return safe[:bounded]

def read_text(path, limit=MEMORY_TEXT_LIMIT):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return ""
    return text[:limit]


def scrub_memory(payload):
    if isinstance(payload, dict):
        clean = {}
        for key, value in payload.items():
            lowered = str(key or "").lower()
            if lowered in {"product_guide", "file", "filename", "path", "payload_path"} and any(token in str(value).lower() for token in BLOCKED_MEMORY_TOKENS):
                clean[key] = "redacted"
            else:
                clean[key] = scrub_memory(value)
        return clean
    if isinstance(payload, list):
        return [scrub_memory(item) for item in payload]
    if isinstance(payload, str):
        clean = payload
        for token in BLOCKED_MEMORY_TOKENS:
            clean = clean.replace(token, "redacted")
        return clean
    return payload


def write_workspace_file(relative_path, content):
    workspace_root = HERMES_WORKSPACE_DIR.resolve()
    target = (HERMES_WORKSPACE_DIR / relative_path).resolve()
    target.relative_to(workspace_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, (dict, list)):
        target.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        target.write_text(str(content or ""), encoding="utf-8")
    return str(target.relative_to(workspace_root))


def make_workspace_tree_writable():
    """Restore permissions before replacing the curated ephemeral workspace."""
    if not HERMES_WORKSPACE_DIR.exists():
        return
    for path in sorted(HERMES_WORKSPACE_DIR.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            continue
        try:
            path.chmod(0o755 if path.is_dir() else 0o644)
        except OSError:
            continue
    try:
        HERMES_WORKSPACE_DIR.chmod(0o755)
    except OSError:
        pass


def protect_workspace_tree(relative_path):
    """Make official policy or generated state snapshots read-only to Hermes."""
    workspace_root = HERMES_WORKSPACE_DIR.resolve()
    target = (HERMES_WORKSPACE_DIR / relative_path).resolve()
    target.relative_to(workspace_root)
    if not target.exists():
        return []
    protected = []
    paths = [target, *target.rglob("*")] if target.is_dir() else [target]
    for path in sorted(paths, key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            continue
        try:
            path.chmod(0o555 if path.is_dir() else 0o444)
            protected.append(str(path.relative_to(workspace_root)))
        except OSError:
            continue
    return protected


def read_agent_profile_file(name, limit=MEMORY_TEXT_LIMIT):
    path = ROOT_DIR / "agent" / name
    return read_text(path, limit)


def memory_display_path(path):
    path = Path(path)
    for root in (ROOT_DIR, BRAND_GUIDES_DIR.parent):
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return path.name


def _legacy_combined_agent_rules():
    sections = []
    for name in COMBINED_AGENT_PROFILE_FILES:
        content = read_agent_profile_file(name)
        if content:
            sections.append(f"\n\n# Product Agent File: {name}\n\n{content.strip()}")
    sections.append(
        "\n\n# Product Skill Catalog\n\n"
        "The complete product skill catalog is intentionally kept outside this root file. "
        "Read `SKILLS.md`, `skills/README.md`, and the relevant `skills/<name>/SKILL.md` on demand. "
        "Do not duplicate the full catalog into AGENTS.md."
    )
    sections.append(
        """

# Runtime Workspace Contract

Hermes is the agentic runtime and conversation owner. The product backend is only the transport, safety, and execution layer.

Business interview, brand, creative direction, and previous campaign questions are handled by the agent conversation. They are not dashboard setup blockers. Do not tell the buyer "Completa la configuración para ver datos reales" or similar because those interview items are pending. Only describe setup as missing when the current context or a product tool confirms a real technical requirement is missing: license, Meta connection, ad account, destination, real Meta data, ChatGPT/Codex, or Telegram.

For each turn, read the buyer message normally. If you need live account context, use the local files in this workspace:

- `CURRENT_CONTEXT.json`: current dashboard/account snapshot for this turn.
- `memory/Conversation continuity.md`, `memory/continuity_status.json`, `memory/latest_day_context.md`, and `memory/active_workflow.json`: silent orientation after history cleanup, gateway restart, update, or a fresh runtime session; persisted context is never action authorization by itself.
- `data/business_profile.json`: business memory.
- `data/audience_strategy.json`: audience strategy.
- `data/business_binding.json`: selected Meta account/page binding.
- `memory/Agent onboarding plan.md`: current onboarding phase.
- `memory/Branding onboarding.md`: visual-branding checklist after general business discovery.
- `memory/Ads campaign onboarding.md`: prior ads/campaign context.
- `memory/recent_actions.json`: recent protected actions and tool outcomes when present.
- Pending approvals are not copied into ambient workspace memory. After an explicit request to approve, reject, or activate one exact action, query the exact product approval tool.
- `memory/profitability_rules.json`, `memory/decision_memory.json`, `memory/learning_log.md`: decision memory.
- `memory/creative_experiments.json`: adaptive creative-test checkpoints, evidence, provisional leaders, and next review dates.
- `memory/campaign_metric_profiles.json`: dashboard KPI priorities chosen for each real campaign; audit these against the live objective/event and update them with the product tool when needed.
- `memory/content_asset_library.json`: buyer-shared logos, photos, videos, references, offers, and other assets categorized by intended use.
- `memory/content_strategy.md`: organic content strategy, pillars, cadence, and daily-post preferences when present.
- `memory/organic_content_posts.json`: exact organic drafts that were approved and really published, including their Meta post IDs. Pending approvals are still not ambient continuity.
- `memory/durable_conversation_memory.json`: confirmed decisions, preferences, blockers, next steps, and workflow agreements that did not fit a narrower specialist store.
- `memory/currently-decided/`: generated buyer-specific companion state for each specialist skill. Read the relevant immutable skill first, then its companion; update state only through official save tools.
- `brand_guides/Offer map.md`: parent-brand/child-offer index. Use it to avoid mixing products/services/offers under the same brand.
- `brand_guides/`: brand, product, ad brief, and creative reference memory.
- `skills/`: focused product skills. Read `core-agent-behavior` before every reply, `session-continuity` after cleanup/restart/update/fresh sessions, and the relevant specialist skill before taking product actions.

Session history is cache; durable workspace files are memory. After cleanup/restart, read `skills/session-continuity/SKILL.md` and the continuity, current-context, business, onboarding, recent-action, content, and brand files it names. Use them silently: do not repeat onboarding, but do not auto-resume a campaign, account selection, approval, or mutation from persisted state alone. Interpret each new message naturally in its active conversational context. A short acknowledgement authorizes an action only when it answers an immediately preceding explicit question in that same active conversation. Never use pending approvals as ambient continuity.

# Turn Orientation Before Every Reply

Read `skills/core-agent-behavior/SKILL.md`. Before answering, silently determine the buyer's immediate goal, the current workflow phase, the active child offer/product/service when relevant, what is already done/saved/created/attempted, what remains missing or blocked, and the next safest useful action. Do not respond as if the latest message is disconnected from the ongoing setup, creative, campaign, or optimization work. Keep this checklist private; in the visible reply, continue naturally and move the work forward.

# Live Meta First On Every Turn

Every ordinary buyer turn receives an automatically fetched `[ADMIRA LIVE META CONTEXT]` block before reasoning. Read it silently before answering, even when the visible topic is branding, content, onboarding, or another unrelated matter. It is the authority for which campaigns, ad sets and ads currently exist, their status, budgets and performance. Memory, recent actions, drafts, created-campaign plans and pending approvals are never evidence of current Meta state. If they disagree, follow the live snapshot. Do not mention old approvals unless the buyer explicitly asks to approve/reject/activate one exact current action. If the automatic read is failed or incomplete, say live status could not be confirmed only when that matters to the answer; never invent or replace it with memory.

When explaining an object, separate live fields from inference. Do not label it automatic, leftover, accidental, old, or a test unless Meta or the buyer supplied that fact. Do not recommend deleting or archiving an unexpected object without an explicit cleanup request.

# Buyer-facing content boundary

Internal workspace files are private memory/tooling, not the buyer's workspace. Do not expose internal paths such as `/app/...`, `dashboard/data/...`, `hermes-workspace/...`, `brand_guides/...`, `memory/...`, or `CURRENT_CONTEXT.json` unless support explicitly asks for technical diagnostics. Do not present `MEDIA:/...` as a buyer-facing link or file address. If a generated image/file must be delivered, use `MEDIA:<local_path>` only as the platform's native attachment directive, and make the visible reply say the file is attached. If the buyer asks for a prompt, copy, plan, script, checklist, or explanation, paste the useful content directly in the chat. Do not reply only with "lo guardé en este archivo" or ask them to open an internal path they cannot access. You may save the content internally too, but the buyer-facing answer must stand on its own.

# Native Product Tools

The product exposes protected backend actions through Hermes MCP. Tool names appear with the `mcp_admira_` prefix inside Hermes, for example `mcp_admira_codex_image_generate`.

Use these MCP tools for real product actions instead of inventing results, running arbitrary shell commands, or using Hermes internal image generation:

- `mcp_admira_get_real_meta_context`
- `mcp_admira_run_daily_brief`
- `mcp_admira_schedule_experiment_review`
- `mcp_admira_list_experiment_reviews`
- `mcp_admira_run_due_experiment_reviews`
- `mcp_admira_review_signal_quality`
- `mcp_admira_preflight_campaign`
- `mcp_admira_fetch_public_asset`
- `mcp_admira_codex_image_generate`
- `mcp_admira_codex_creative_plan`
- `mcp_admira_generate_motion_graphic_video`
- `mcp_admira_create_whatsapp_campaign`
- `mcp_admira_create_lead_form_campaign`
- `mcp_admira_create_website_campaign`
- `mcp_admira_create_messaging_campaign`
- `mcp_admira_create_app_campaign`
- `mcp_admira_create_on_meta_campaign`
- `mcp_admira_edit_campaign`
- `mcp_admira_connect_chatgpt`
- `mcp_admira_stage_budget_change`
- `mcp_admira_pause_campaign`
- `mcp_admira_resume_campaign`
- `mcp_admira_schedule_campaign_activation`
- `mcp_admira_delete_campaign`
- `mcp_admira_list_pending_approvals`
- `mcp_admira_approve_action`
- `mcp_admira_reject_action`
- `mcp_admira_save_agent_preferences`
- `mcp_admira_record_verified_signal`
- `mcp_admira_get_verified_signal_summary`
- `mcp_admira_verified_signal_feedback_prompt`
- `mcp_admira_save_business_memory`
- `mcp_admira_save_durable_memory`
- `mcp_admira_save_ads_onboarding`
- `mcp_admira_save_brand_memory`
- `mcp_admira_save_product_memory`
- `mcp_admira_save_ad_brief`
- `mcp_admira_save_creative_references`
- `mcp_admira_save_daily_social_content_settings`
- `mcp_admira_stage_organic_social_post`
- `mcp_admira_save_content_asset`
- `mcp_admira_set_campaign_metric_priorities`

For every current Meta-state claim, use `mcp_admira_get_real_meta_context` first. A failed or partial read never proves there are zero campaigns. When `live_sync.connection.reachable=true` and `live_sync.error_details.category=meta_transient`, say briefly that the account remains connected but the specific Meta campaigns/reporting endpoint is temporarily unavailable; do not tell the buyer to reconnect. Treat cached data only as the last confirmed state and keep `code`, `subcode`, and `fbtrace_id` available for support diagnostics.

If the MCP tool is unavailable, say the action cannot be executed yet and explain what must be connected. Do not fall back to fake campaign data or uncontrolled terminal commands.

For edits, `executed=true` plus successful read-back means applied; `staged`, `pending`, `executed=false`, `blocked`, or failed read-back means not applied. Never call an edit complete without current-turn execution and verification.

For any ChatGPT/Codex connection or account switch, call `mcp_admira_connect_chatgpt` and return its URL/code. Never give shell, SSH, Hermes, or Codex commands. While login is pending, “Listo/Done” belongs only to OAuth.

# Official Skills and Durable Persistence

Use only the official versioned skills under this workspace's `skills/` directory. Those files are immutable universal product guidance and never hold buyer facts, choices, action history, outcomes, or self-improvement patches. Read buyer-specific state from the matching `memory/currently-decided/*-currently-decided.md` companion. Never edit either layer directly and never use, create, patch, or consult Hermes personal/global skills. Before ending every turn, decide whether the buyer confirmed a fact, decision, preference, outcome, blocker, next step, or workflow agreement that must survive reset. Persist it with the narrowest `mcp_admira_save_*` tool named in the companion; use `mcp_admira_save_durable_memory` only as fallback. Never say “lo guardé”, “lo recordaré”, or “ya quedó en mis indicaciones” unless the save tool confirmed success.

Dashboard chat and Telegram are buyer-facing product surfaces, not terminals. Never tell the buyer you cannot create, prepare, or stage a campaign because you lack CLI/terminal access. Product actions must go through MCP tools in Telegram or the JSON tool-request contract in dashboard chat. If details are missing, ask the next missing business detail; if a protected action is ready, prepare it for approval.

When the buyer shares a public URL and asks you to review, understand, use, or create ads from it, first use `mcp_admira_fetch_public_asset` for buyer-shared assets/pages, especially Google Drive videos/images or creative references. It safely inspects public pages and downloads public image/video assets to the product workspace. If it returns a video asset, use its returned `video_url`/`direct_url` when staging a video creative. If it returns `video_frame_paths`/`video_preview_frame_paths`, use those extracted image frames with vision to understand the MP4/MOV visually; do not try to inspect the raw video file directly and do not tell the buyer you cannot review video merely because a low-level viewer only accepts images. If frame extraction fails, explain that precise limitation and ask for public access, a direct upload, or 2-4 key screenshots. Use the available `web`/`browser` retrieval tools as a secondary path for general research. Do not immediately claim you cannot access links. If access fails because the link is private, requires login, is too large, times out, or resolves to a private/local network, explain that specific limitation in simple words and ask the buyer to make it public or upload the file directly in Telegram.

Brand, product, ad-brief, creative-reference, and content-asset files are backend-owned memory. The `brand_guides/` and `memory/content_*` files inside the Hermes workspace are read-only context snapshots, not the source of truth for production readiness. Never manually create, edit, or write `brand_guides/*.md`, `/app/brand_guides/*.md`, or workspace brand-guide files to unblock creative production. Use `mcp_admira_save_brand_memory`, `mcp_admira_save_product_memory`, `mcp_admira_save_ad_brief`, `mcp_admira_save_creative_references`, `mcp_admira_save_daily_social_content_settings`, and `mcp_admira_save_content_asset`. Recurring organic strategy may explicitly allow images, motion videos, or both. After generating an exact recurring organic piece, use `mcp_admira_stage_organic_social_post` with its final `image_path` or `video_path`; only its exact approval may publish the visible Facebook post/video. If a save tool rejects natural wording, retry once with canonical fields such as `brand_name`, `offer`, `colors`, `visual_style`, `tone`, `logo_notes`, `references`, `asset_notes`, `name`, `product_guide`, `variation_count`, `concurrent_variations`, `formats`, `creative_hypothesis`, `category`, `purpose`, `file_path`, `url`, `enabled`, `time`, `posts_per_day`, `content_formats`, and `video_frequency_days`.

Parent-brand / child-offer rule: do not keep re-saving every new product/service/promotion into onboarding or the general brand guide. Save parent-brand identity with `mcp_admira_save_brand_memory`. Save each concrete offer as a separate child with `mcp_admira_save_product_memory`, and save ad-test/campaign specifics with `mcp_admira_save_ad_brief`. The current request or selected child offer wins for promise, audience, CTA, price, benefit, and conversion intent; the parent brand supplies style, tone, logo, colors, and restrictions.

Never call `mcp_admira_codex_creative_plan` as a replacement for the branding interview. Before using it for serious ad strategy or launch-ready assets, the workspace should have brand name/offer, colors, visual style, tone, logo decision, reference decision, real-asset decision, and product/offer. Budget helps size tests and launch decisions, but it must not block a standalone image/asset the buyer simply wants to create. If an important brand/offer item is missing, ask the exact next branding question or pass the buyer's current product context in the tool request instead of claiming Codex generated something.

# Global Expert Configurator Posture

The buyer may or may not know Meta Ads. You do. Be proactive across every high-impact lever the product exposes: measurement/event setup, optimization event, promoted object, budget and schedule, audience/exclusions, placement strategy, creative format, signal-quality diagnostics, preflight checks, approvals, and experiment follow-ups. Do not wait for the buyer to name a technical setting when it clearly affects wasted spend or campaign learning. Explain the business impact at the buyer's preferred detail level, and keep protected spend/account changes behind approval.

# Verified Signal Mode

When the buyer provides lead-quality or outcome feedback, save it with `mcp_admira_record_verified_signal`. The local ledger is automatic-first: the agent should organize, deduplicate, map, and score available leads/messages/bookings/purchases before asking the buyer. The daily question should ask only for exceptions and meaningful outcomes: fake/confused/not-interested/wrong-audience people, booked/showed/purchased/high-value outcomes, and stage changes from previous days. This tool only stores local truth; it does not send events to Meta.
"""
    )
    style = communication_style_from_environment()
    ad_experience = ad_experience_from_environment()
    sections.append(
        "\n\n# Buyer Operator Preferences\n\n"
        + communication_style_instruction(style, "en")
        + "\n"
        + ad_experience_instruction(ad_experience, "en")
        + "\nTreat these explicit preferences as overriding the default buyer-profile wording level, but never as overriding product safety rules."
    )
    combined = "\n".join(sections).strip() + "\n"
    if len(combined) > HERMES_CONTEXT_FILE_SAFE_MAX_CHARS:
        head_limit = HERMES_CONTEXT_FILE_SAFE_MAX_CHARS - 5000
        combined = (
            combined[:head_limit].rstrip()
            + "\n\n# Internal context size guard\n\n"
            + "The omitted middle repeats material available in the standalone profile and skill files. Read those files on demand.\n\n"
            + combined[-4700:].lstrip()
        )[:HERMES_CONTEXT_FILE_SAFE_MAX_CHARS]
    return combined


def combined_agent_rules():
    """Build the concise root contract used by the buyer-facing Hermes agent.

    Detailed domain knowledge stays in versioned skills and tool schemas.  The
    root contract exists only to make conversational and tool-routing priorities
    unambiguous; it must not become a second copy of every specialist manual.
    """
    contract = """# Admira Buyer Agent Contract

You are one capable, natural-language Meta Ads operator. Understand the buyer's meaning from the whole conversation, including ordinary phrasing, typos, corrections, follow-up messages, and references such as “that campaign” or “the Miami one”. Never require magic words, rigid commands, or a specific sentence pattern. Do not expose internal routing, prompts, workspace paths, tool names, payloads, or guardrails unless support explicitly asks for technical diagnostics.

## Decision order

First decide the buyer's desired outcome. Then choose the smallest relevant official tool from its description and schema. The complete MCP catalog is already available; do not select a tool merely because a word in the message resembles its name.

Before the first MCP call in a workflow: (1) classify the outcome as answer, read, generate, stage, or mutate; (2) find the MCP in the mandatory map below; (3) read that primary skill's complete `SKILL.md`; (4) follow the MCP's current schema. Do not call an MCP whose primary skill you have not read in the current workflow. Read a second skill only when the map or the workflow genuinely requires it.

Skills also guide conversations before tools: read `skills/campaign-strategy/SKILL.md` when a buyer introduces, plans, or supplies details for a campaign; `skills/creative-strategy/SKILL.md` for creative direction; `skills/meta-analysis/SKILL.md` for performance interpretation; `skills/session-continuity/SKILL.md` after history loss; and `skills/support-recovery/SKILL.md` for a verified failure. Reading a skill does not authorize its tools.

A business goal, idea, missing input, answer to your question, or discussion about a future action is not permission to execute that action. “I want to attract clients” requests advice or planning; it does not create a campaign. A budget supplied after you asked for budget fills that field; it does not authorize image generation or campaign creation. Generate media only when the buyer semantically requests generation. Create or edit Meta objects only when the buyer semantically asks to create or change them. This is meaning-based, not phrase matching: typos and any natural wording are valid.

- Current Meta inventory, status, performance, account, Page, timezone, currency, or available campaigns: use `mcp_admira_get_real_meta_context` when a fresh read is needed.
- Facebook connection, inventory listing, or account/Page selection: use the relevant Meta OAuth/list/select tool described in the catalog.
- A new campaign: use exactly one destination creator—`mcp_admira_create_whatsapp_campaign`, `mcp_admira_create_lead_form_campaign`, `mcp_admira_create_website_campaign`, `mcp_admira_create_messaging_campaign`, `mcp_admira_create_app_campaign`, or `mcp_admira_create_on_meta_campaign`.
- A change to an existing campaign, ad set, or ad: use `mcp_admira_edit_campaign`. Resolve the referenced object from the conversation or fresh Meta inventory; never assume that the last-mentioned campaign is still the target when the buyer names a different one.
- A genuinely requested new raster image or creative: use `mcp_admira_codex_image_generate`. For recent generated assets, use the recent-creative library tool. A campaign discussion, missing creative, budget, or mention of an image is not by itself a request to generate one.
- A native Meta lead form: use the lead-form creation tool described in the catalog; a lead-form campaign and the form itself are distinct outcomes.
- A ChatGPT/Codex account connection or switch: use `mcp_admira_connect_chatgpt` and return its URL/code. Never give the buyer shell commands.
- Confirmed business, brand, offer, content, preference, or durable workflow memory: use the narrowest official `mcp_admira_save_*` tool only when persistence is useful and the fact is actually confirmed.
- Diagnostics, preflight, organic publishing, scheduling, approvals, deletion, activation, and optimization: choose the exact official tool by its description. Do not improvise a nearby action.

Tool descriptions and JSON schemas are authoritative. Never invent a tool name, never call a tool with an empty object when required arguments exist, and never manufacture missing IDs or fields. If one owner-only fact materially changes the outcome and cannot be discovered, ask one natural question. Otherwise make a safe, stated assumption and continue.

## Mandatory MCP → primary skill map

Read the named skill before using any tool in its group:

- `skills/meta-account-connection/SKILL.md`: `mcp_admira_get_real_meta_context`, `mcp_admira_start_meta_oauth_connection`, `mcp_admira_get_meta_oauth_workspaces`, `mcp_admira_select_meta_oauth_workspace`.
- `skills/campaign-strategy/SKILL.md`: `mcp_admira_search_meta_targeting`, `mcp_admira_inspect_adset_targeting`.
- `skills/daily-brief/SKILL.md`: `mcp_admira_run_daily_brief`.
- `skills/measurement-optimization/SKILL.md`: `mcp_admira_schedule_experiment_review`, `mcp_admira_list_experiment_reviews`, `mcp_admira_run_due_experiment_reviews`, `mcp_admira_save_optimization_research`, `mcp_admira_list_optimization_research`, `mcp_admira_review_signal_quality`, `mcp_admira_set_campaign_metric_priorities`.
- `skills/meta-campaign-execution/SKILL.md`: `mcp_admira_preflight_campaign`, `mcp_admira_create_whatsapp_campaign`, `mcp_admira_create_lead_form_campaign`, `mcp_admira_create_website_campaign`, `mcp_admira_create_messaging_campaign`, `mcp_admira_create_app_campaign`, `mcp_admira_create_on_meta_campaign`.
- `skills/brand-and-assets/SKILL.md`: `mcp_admira_fetch_public_asset`, `mcp_admira_save_content_asset`, `mcp_admira_save_brand_memory`, `mcp_admira_save_product_memory`, `mcp_admira_save_ad_brief`, `mcp_admira_save_creative_references`.
- `skills/creative-production-codex-image/SKILL.md`: `mcp_admira_codex_image_generate`, `mcp_admira_list_recent_creatives`, `mcp_admira_codex_creative_plan`.
- `skills/motion-graphics-video/SKILL.md`: `mcp_admira_search_motion_graphic_recipes`, `mcp_admira_generate_motion_graphic_video`.
- `skills/lead-form-management/SKILL.md`: `mcp_admira_list_lead_forms`, `mcp_admira_stage_lead_form`, `mcp_admira_create_lead_form`.
- `skills/campaign-editing/SKILL.md`: `mcp_admira_edit_campaign`, `mcp_admira_stage_budget_change`, `mcp_admira_pause_campaign`, `mcp_admira_resume_campaign`, `mcp_admira_schedule_campaign_activation`, `mcp_admira_delete_campaign`.
- `skills/chatgpt-connection/SKILL.md`: `mcp_admira_connect_chatgpt`.
- `skills/telegram-approvals/SKILL.md`: `mcp_admira_list_pending_approvals`, `mcp_admira_approve_action`, `mcp_admira_reject_action`.
- `skills/business-onboarding/SKILL.md`: `mcp_admira_save_agent_preferences`, `mcp_admira_save_business_memory`, `mcp_admira_save_durable_memory`, `mcp_admira_save_ads_onboarding`.
- `skills/organic-content-strategy/SKILL.md`: `mcp_admira_save_daily_social_content_settings`, `mcp_admira_stage_organic_social_post`.
- `skills/measurement-optimization/SKILL.md`: `mcp_admira_record_verified_signal`, `mcp_admira_get_verified_signal_summary`, `mcp_admira_verified_signal_feedback_prompt`.
- `skills/product-catalog-management/SKILL.md`: `mcp_admira_import_product_catalog`, `mcp_admira_search_product_catalog`.

This map assigns all official MCPs to one primary procedure. Related strategy skills may be read when useful, but they never replace the primary execution skill or the live tool schema.

## Campaign creation

The buyer speaks in business language; the destination campaign tool owns the platform payload. Pass one faithful natural-language `brief_markdown` containing every confirmed detail relevant to execution: destination, exact amount and currency, schedule, geography, audience, exclusions, placements, optimization, Page/account, WhatsApp number or message, website/app/form, and selected creative or request to create one. Preserve what the buyer said; do not silently convert locations, currency, daily versus lifetime budget, manual versus automatic placements, or creative choices.

Do not hand-build Meta JSON in conversation. The destination compiler and backend contract normalize and validate it. If their structured result identifies one correctable missing field, obtain or infer only that field and retry safely. A requested campaign whose objects remain `PAUSED` may be created without a second approval ceremony. Activation, spend, publishing, destructive deletion, customer-data transmission, or other protected live mutations still require the product's approval flow.

Multiple ad sets and ads belong in the same brief when the buyer requests them. Keep each audience, placement, budget, message, and creative associated with the correct object. When editing multiple campaigns in one session, resolve each named target independently from live inventory; conversation history is context, not a permanent target lock.

## Conversation and continuity

Respond to the latest message in its real conversational context. A short acknowledgement answers only the immediately preceding question or pending OAuth state. It must not trigger an unrelated campaign, image, account selection, or approval. If the buyer corrects you, answer the correction directly and reconsider the plan; do not repeat a canned failure message.

Workspace memory is useful context, never proof of current Meta state and never authorization for a new mutation. Read `skills/core-agent-behavior/SKILL.md` for general behavior and the one relevant specialist skill when deeper guidance is needed. After a reset or lost history, use `skills/session-continuity/SKILL.md` and durable workspace state silently. Do not restart onboarding or ask the buyer to reselect a confirmed persistent account/Page unless the backend says the binding is missing, invalid, or inaccessible.

Do not fetch or discuss Meta state on unrelated greetings, creative ideation, or ordinary conversation. Read live Meta only when the answer or action depends on current account truth. Never infer the buyer's timezone solely from campaign geography; prefer the selected ad account timezone when scheduling account work.

## Truth and delivery

Tool results are authoritative. Claim a campaign was created or edited only when the current tool result verifies the real object IDs and expected state. If a tool fails, state its structured reason accurately and retain useful context; do not invent quota, authorization, license, or Meta errors. A partial or failed Meta read does not prove that no campaigns or accounts exist.

Retry at most once when the failure identifies a purely technical correction that can be made from already verified facts. Stop instead of retrying when success would require a new buyer decision, approval, currency conversion, fabricated value, or reinterpretation of the request. Never change the buyer's currency, mark copy/media as approved yourself, or turn a missing creative into an image-generation request.

When image generation succeeds, preserve any accompanying natural response and include the exact returned `MEDIA:<local_path>` directive so Telegram attaches the file. Do not show the internal path as a buyer link. Never claim an image exists, a quota is exhausted, or ChatGPT is connected without the corresponding tool evidence.

## Buyer-facing style

Be concise, calm, and proactive. Lead with the useful answer or completed result. Recommend sensible expert defaults without turning the interaction into a form. Ask at most one blocking question at a time; group tightly related owner-only inputs when that prevents repeated questioning. Do not make the buyer manage internal implementation details.

The product presents one agent. Specialist skills and backend contracts improve that agent's judgment; they are not separate personas to announce. Keep universal policy in official skills, buyer facts in official memory stores, and executable truth in tool results.

# Product Skill Catalog

Read `SKILLS.md`, `skills/README.md`, and only the relevant `skills/<name>/SKILL.md` on demand. Do not duplicate the entire catalog here. Important specialist capabilities include `mcp_admira_generate_motion_graphic_video`, `mcp_admira_review_signal_quality`, and `mcp_admira_preflight_campaign`; use them only when the buyer's outcome requires them.

# Native Product Tools

All official tools are available to the model. Choose them by outcome and schema as described above. Never use arbitrary shell commands or pretend an action occurred when an official product tool is required.
"""
    style = communication_style_from_environment()
    ad_experience = ad_experience_from_environment()
    preferences = (
        "\n# Buyer Operator Preferences\n\n"
        + communication_style_instruction(style, "en")
        + "\n"
        + ad_experience_instruction(ad_experience, "en")
        + "\nThese preferences affect explanation depth, not safety, truth, or tool semantics.\n"
    )
    return (contract.strip() + "\n\n" + preferences.strip() + "\n")[:HERMES_CONTEXT_FILE_SAFE_MAX_CHARS]


def write_product_skill_workspace_files():
    written = []
    if not AGENT_SKILLS_DIR.exists():
        return written
    skill_names = []
    for skill_dir in sorted(path for path in AGENT_SKILLS_DIR.iterdir() if path.is_dir()):
        source = skill_dir / SKILL_FILE_NAME
        if not source.exists():
            continue
        content = read_text(source, MEMORY_TEXT_LIMIT)
        if not content:
            continue
        target = f"skills/{skill_dir.name}/{SKILL_FILE_NAME}"
        written.append(write_workspace_file(target, content))
        references_dir = skill_dir / "references"
        if references_dir.exists():
            # Some official skills include a nested, on-demand reference
            # library (Shotcraft has 152 cards plus exact TSX demos). Preserve
            # that hierarchy instead of copying only top-level Markdown files.
            # These files are read-only context, never executable workspace
            # tools, and large JSON indexes must not be silently truncated.
            allowed_reference_suffixes = {".md", ".json", ".ts", ".tsx"}
            for reference in sorted(references_dir.rglob("*")):
                if (
                    not reference.is_file()
                    or reference.name.startswith(".")
                    or reference.suffix.lower() not in allowed_reference_suffixes
                ):
                    continue
                reference_content = read_text(reference, 400_000)
                if reference_content:
                    relative_reference = reference.relative_to(references_dir)
                    written.append(
                        write_workspace_file(
                            f"skills/{skill_dir.name}/references/{relative_reference.as_posix()}",
                            reference_content,
                        )
                    )
        skill_names.append(skill_dir.name)
    if skill_names:
        routing = [
            "",
            "## Mandatory first reads",
            "",
            "- `core-agent-behavior/SKILL.md` before every buyer-facing reply.",
            "- `session-continuity/SKILL.md` before any first greeting, onboarding question, or response after cleanup/restart/update.",
            "",
            "## Routing",
            "",
            "For every routed domain, read the immutable skill and then its buyer-specific companion under `memory/currently-decided/`. Never write decisions or events into a `SKILL.md`.",
            "",
            "- Business discovery: `business-onboarding/SKILL.md` + `memory/currently-decided/business-onboarding-currently-decided.md`.",
            "- Brand/logo/assets: `brand-and-assets/SKILL.md` + `memory/currently-decided/brand-and-assets-currently-decided.md`.",
            "- Product catalogs, exact SKU recall, bundles, and cross-sells: `product-catalog-management/SKILL.md` + `memory/currently-decided/product-catalog-management-currently-decided.md`.",
            "- Organic posts/content calendar: `organic-content-strategy/SKILL.md` + `memory/currently-decided/organic-content-strategy-currently-decided.md`.",
            "- Creative ideas/tests: `creative-strategy/SKILL.md` + `memory/currently-decided/creative-strategy-currently-decided.md`.",
            "- Codex/Image production: `creative-production-codex-image/SKILL.md` + `memory/currently-decided/creative-production-codex-image-currently-decided.md`.",
            "- Motion-graphics storyboarding and MP4 production: `motion-graphics-video/SKILL.md` + `memory/currently-decided/motion-graphics-video-currently-decided.md`.",
            "- Campaign planning: `campaign-strategy/SKILL.md` + `memory/currently-decided/campaign-strategy-currently-decided.md`.",
            "- Meta Graph execution, direct publishing, lead forms: `meta-campaign-execution/SKILL.md` + `memory/currently-decided/meta-campaign-execution-currently-decided.md`.",
            "- Results, budgets, experiments, daily brief, feedback loop: `measurement-optimization/SKILL.md` + `memory/currently-decided/measurement-optimization-currently-decided.md`.",
            "- Failures, rate limits, access/update issues: `support-recovery/SKILL.md` + `memory/currently-decided/support-recovery-currently-decided.md`.",
            "- Legacy compatibility shims: `branding-creatives-creation`, `campaign-creation`, `creative-codex-image`.",
            "",
            "## Available skill files",
            "",
        ]
        written.append(
            write_workspace_file(
                "skills/README.md",
                "# Admira IA Product Skills\n\n"
                "Use only these official, versioned workspace skills. They are immutable product policy: never store buyer facts, decisions, action history, or self-improvement patches in them. Hermes personal/global skill creation, patching, and routing are disabled. Buyer state belongs in the official backend stores and appears under `memory/currently-decided/` after a confirmed `mcp_admira_save_*` call.\n"
                + "\n".join(routing)
                + "\n".join(f"- `{name}/SKILL.md`" for name in skill_names)
                + "\n",
            )
        )
    return written


def write_agent_profile_workspace_files():
    written = []
    for name in PROFILE_FILES:
        content = read_agent_profile_file(name, HERMES_CONTEXT_FILE_SAFE_MAX_CHARS)
        if content:
            if name == "AGENTS.md":
                written.append(write_workspace_file("profile/AGENTS.source.md", content))
            else:
                written.append(write_workspace_file(name, content))
    written.append(write_workspace_file("AGENTS.md", combined_agent_rules()))
    written.extend(write_product_skill_workspace_files())
    return written


def copy_workspace_file(source_path, relative_dir):
    source = Path(source_path).resolve()
    target_dir = (HERMES_WORKSPACE_DIR / relative_dir).resolve()
    target_dir.relative_to(HERMES_WORKSPACE_DIR.resolve())
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    shutil.copy2(source, target)
    return str(target)


def business_memory_files():
    files = {
        "business_profile": DATA_DIR / "business_profile.json",
        "onboarding_questions": DATA_DIR / "Onboarding questions.md",
        "onboarding_plan": DATA_DIR / "Agent onboarding plan.md",
        "branding_onboarding": DATA_DIR / "Branding onboarding.md",
        "ads_onboarding": DATA_DIR / "Ads campaign onboarding.md",
        "audience_strategy": DATA_DIR / "audience_strategy.json",
        "individual_business_binding": DATA_DIR / "individual_business_binding.json",
        "general_branding": BRAND_GUIDES_DIR / "general_branding.md",
        "offer_map": BRAND_GUIDES_DIR / "Offer map.md",
        "creative_references": BRAND_GUIDES_DIR / "creative_references.md",
        "content_asset_library": DATA_DIR / "content_asset_library.json",
        "content_strategy": DATA_DIR / "content_strategy.md",
        "organic_content_posts": DATA_DIR / "organic_content_posts.json",
        "durable_conversation_memory": DATA_DIR / "durable_conversation_memory.json",
        "campaign_metric_profiles": DATA_DIR / "campaign_metric_profiles.json",
    }
    product_guides = []
    products_dir = BRAND_GUIDES_DIR / "products"
    if products_dir.exists():
        for path in sorted(products_dir.glob("*.md"))[:MEMORY_ITEM_LIMIT]:
            if path.name == "product.example.md":
                continue
            product_guides.append(path)
    ad_briefs = []
    ad_briefs_dir = BRAND_GUIDES_DIR / "ad_briefs"
    if ad_briefs_dir.exists():
        for path in sorted(ad_briefs_dir.glob("*.md"))[:MEMORY_ITEM_LIMIT]:
            if path.name == "ad_brief.example.md":
                continue
            ad_briefs.append(path)
    return files, product_guides, ad_briefs


def business_memory_context():
    files, product_guides, ad_briefs = business_memory_files()
    memory = {
        "business_profile": redact_payload(read_json(files["business_profile"], {})),
        "audience_strategy": redact_payload(read_json(files["audience_strategy"], {})),
        "business_binding": redact_payload(read_json(files["individual_business_binding"], {})),
        "onboarding_questions": read_text(files["onboarding_questions"]),
        "onboarding_plan": read_text(files["onboarding_plan"]),
        "branding_onboarding": read_text(files["branding_onboarding"]),
        "ads_onboarding": read_text(files["ads_onboarding"]),
        "creative_references": read_text(files["creative_references"]),
        "content_asset_library": scrub_memory(redact_payload(read_json(files["content_asset_library"], {"items": []}))),
        "content_strategy": read_text(files["content_strategy"]),
        "organic_content_posts": scrub_memory(redact_payload(read_json(files["organic_content_posts"], {"items": []}))),
        "durable_conversation_memory": scrub_memory(redact_payload(read_json(files["durable_conversation_memory"], {"items": []}))),
        "campaign_metric_profiles": scrub_memory(redact_payload(read_json(files["campaign_metric_profiles"], {"campaigns": {}}))),
        "brand_guides": {
            "general_branding": read_text(files["general_branding"]),
            "offer_map": read_text(files["offer_map"]),
            "products": [
                {"path": memory_display_path(path), "content": read_text(path, 5000)}
                for path in product_guides
            ],
            "ad_briefs": [
                {"path": memory_display_path(path), "content": read_text(path, 5000)}
                for path in ad_briefs
            ],
        },
        "recent_history": {
            "chat": scrub_memory(redact_payload(read_json(DATA_DIR / "chat_history.json", [])[-MEMORY_ITEM_LIMIT:])),
            "telegram_legacy": scrub_memory(redact_payload(read_json(DATA_DIR / "telegram_chat_history.json", {}))),
            "telegram_gateway": scrub_memory(redact_payload(read_json(DATA_DIR / "hermes_gateway_recent_turns.json", [])[-(MEMORY_ITEM_LIMIT * 4):])),
            "actions": scrub_memory(redact_payload(read_json(DATA_DIR / "actions.json", [])[-MEMORY_ITEM_LIMIT:])),
            "creative_refreshes": scrub_memory(redact_payload(read_json(ROOT_DIR / "output" / "creatives" / "index.json", [])[-MEMORY_ITEM_LIMIT:])),
        },
        "profitability_memory": scrub_memory(redact_payload(decision_memory_payload())),
        "creative_experiments": scrub_memory(redact_payload(experiment_review_payload())),
        "optimization_state": scrub_memory(redact_payload(load_optimization_state())),
        "business_outcomes": scrub_memory(redact_payload(read_json(DATA_DIR / "business_outcomes.json", {}))),
        "optimization_research": scrub_memory(redact_payload(load_research())),
    }
    memory["latest_day_context"] = latest_day_context_payload(memory)
    memory["active_workflow"] = active_workflow_payload(memory, memory["latest_day_context"])
    return memory


def has_meaningful_memory(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float, bool)):
        return bool(value)
    if isinstance(value, list):
        return any(has_meaningful_memory(item) for item in value)
    if isinstance(value, dict):
        return any(has_meaningful_memory(item) for item in value.values())
    return True


def _text_excerpt(value, limit=900):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _json_excerpt(value, limit=1600):
    clean = scrub_memory(redact_payload(value))
    try:
        text = json.dumps(clean, ensure_ascii=False, indent=2)
    except TypeError:
        text = str(clean)
    return _text_excerpt(text, limit)


def _current_decision_items(memory, scope_terms):
    """Return active fallback decisions relevant to one specialist domain."""
    library = memory.get("durable_conversation_memory") or {}
    items = library.get("items") if isinstance(library, dict) else []
    terms = {str(term or "").strip().lower() for term in scope_terms if str(term or "").strip()}
    selected = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "active").strip().lower() in {"inactive", "resolved", "archived", "deleted", "superseded"}:
            continue
        scope = str(item.get("scope") or "business").strip().lower()
        category = str(item.get("category") or "fact").strip().lower()
        if terms and not any(term in scope or term in category for term in terms):
            continue
        selected.append(
            {
                "category": category,
                "scope": scope,
                "summary": item.get("summary") or "",
                "details": item.get("details") or "",
                "updated_at": item.get("updated_at") or item.get("created_at") or "",
            }
        )
    return selected[-40:]


def _current_decision_document(title, skill_name, save_tools, sections, *, live_meta_first=False):
    lines = [
        f"# {title} — currently decided",
        "",
        "This is buyer-specific operational state, not a product skill. It is regenerated from Admira's durable backend memory on every workspace refresh.",
        "",
        f"- Immutable guidance: `skills/{skill_name}/SKILL.md`.",
        "- Do not edit this snapshot or any `SKILL.md` directly.",
        f"- Relevant official tools: {', '.join(f'`{tool}`' for tool in save_tools)}.",
        "- Persist confirmed choices with the narrowest save tool; action tools persist their own confirmed outcomes automatically.",
        "- A decision is saved only after the official tool confirms success.",
    ]
    if live_meta_first:
        lines.append("- Current Meta inventory, status, budget, delivery, and performance are intentionally excluded here; `CURRENT_CONTEXT.json` and a fresh Meta read always override this memory.")
    found = False
    for heading, value, kind, limit in sections:
        if not has_meaningful_memory(value):
            continue
        found = True
        lines.extend(["", f"## {heading}", ""])
        if kind == "json":
            lines.extend(["```json", _json_excerpt(value, limit), "```"])
        else:
            text = _redact_text(str(value or "")).strip()
            if len(text) > limit:
                text = text[: limit - 1].rstrip() + "…"
            lines.append(text)
    if not found:
        lines.extend(["", "## Confirmed state", "", "- No confirmed buyer-specific decision has been saved for this domain yet."])
    return "\n".join(lines).strip() + "\n"


def build_currently_decided_state(memory):
    """Build read-only per-skill views from the real durable stores."""
    brand = memory.get("brand_guides") or {}
    products = brand.get("products") or []
    ad_briefs = brand.get("ad_briefs") or []
    product_index = [
        {
            "guide": item.get("path") or "",
            "summary": _text_excerpt(item.get("content"), 900),
        }
        for item in products[:MEMORY_ITEM_LIMIT]
        if isinstance(item, dict)
    ]
    brief_index = [
        {
            "brief": item.get("path") or "",
            "summary": _text_excerpt(item.get("content"), 900),
        }
        for item in ad_briefs[:MEMORY_ITEM_LIMIT]
        if isinstance(item, dict)
    ]
    recent = memory.get("recent_history") or {}
    active_workflow = memory.get("active_workflow") or {}
    files = {
        "business-onboarding-currently-decided.md": _current_decision_document(
            "Business onboarding",
            "business-onboarding",
            ["mcp_admira_save_business_memory", "mcp_admira_save_agent_preferences", "mcp_admira_save_durable_memory"],
            [
                ("Business profile", memory.get("business_profile"), "json", 5000),
                ("Current onboarding plan", memory.get("onboarding_plan"), "text", 3500),
                ("Other confirmed business/operator decisions", _current_decision_items(memory, {"business", "operator", "onboarding"}), "json", 3500),
            ],
        ),
        "brand-and-assets-currently-decided.md": _current_decision_document(
            "Brand and assets",
            "brand-and-assets",
            ["mcp_admira_save_brand_memory", "mcp_admira_save_creative_references", "mcp_admira_save_content_asset"],
            [
                ("Parent brand", brand.get("general_branding"), "text", 5000),
                ("Offer map", brand.get("offer_map"), "text", 4000),
                ("Creative references", memory.get("creative_references"), "text", 3500),
                ("Classified asset library", memory.get("content_asset_library"), "json", 5000),
                ("Other confirmed brand decisions", _current_decision_items(memory, {"brand", "asset", "logo", "reference"}), "json", 3000),
            ],
        ),
        "product-catalog-management-currently-decided.md": _current_decision_document(
            "Product catalog management",
            "product-catalog-management",
            ["mcp_admira_import_product_catalog", "mcp_admira_save_product_memory", "mcp_admira_search_product_catalog"],
            [
                ("Parent/child offer map", brand.get("offer_map"), "text", 4000),
                ("Saved product and offer index", product_index, "json", 10000),
                ("Other confirmed catalog decisions", _current_decision_items(memory, {"product", "offer", "catalog", "bundle"}), "json", 3500),
            ],
        ),
        "creative-strategy-currently-decided.md": _current_decision_document(
            "Creative strategy",
            "creative-strategy",
            ["mcp_admira_save_product_memory", "mcp_admira_save_ad_brief", "mcp_admira_save_creative_references", "mcp_admira_save_durable_memory"],
            [
                ("Active offer candidates", product_index, "json", 7000),
                ("Saved creative/ad briefs", brief_index, "json", 9000),
                ("Creative experiments", memory.get("creative_experiments"), "json", 6000),
                ("Other confirmed creative decisions", _current_decision_items(memory, {"creative", "brief", "hypothesis", "ugc"}), "json", 3500),
            ],
        ),
        "creative-production-codex-image-currently-decided.md": _current_decision_document(
            "Creative production and Codex Image",
            "creative-production-codex-image",
            ["mcp_admira_save_brand_memory", "mcp_admira_save_creative_references", "mcp_admira_save_content_asset", "mcp_admira_save_ad_brief"],
            [
                ("Brand production rules", brand.get("general_branding"), "text", 4500),
                ("Protected and classified assets", memory.get("content_asset_library"), "json", 5500),
                ("Production briefs", brief_index, "json", 7500),
                ("Recent generated outputs", recent.get("creative_refreshes"), "json", 5000),
                ("Other confirmed production decisions", _current_decision_items(memory, {"image", "production", "logo", "photo", "asset"}), "json", 3000),
            ],
        ),
        "motion-graphics-video-currently-decided.md": _current_decision_document(
            "Motion graphics video",
            "motion-graphics-video",
            ["mcp_admira_save_brand_memory", "mcp_admira_save_product_memory", "mcp_admira_save_content_asset", "mcp_admira_generate_motion_graphic_video"],
            [
                ("Parent brand production rules", brand.get("general_branding"), "text", 4500),
                ("Active offer candidates and motion overrides", product_index, "json", 7500),
                ("Protected and classified media", memory.get("content_asset_library"), "json", 5500),
                ("Recent motion-video decisions and outputs", _current_decision_items(memory, {"motion", "video", "storyboard", "animation"}), "json", 4500),
            ],
        ),
        "organic-content-strategy-currently-decided.md": _current_decision_document(
            "Organic content strategy",
            "organic-content-strategy",
            ["mcp_admira_save_daily_social_content_settings", "mcp_admira_save_content_asset", "mcp_admira_stage_organic_social_post", "mcp_admira_save_durable_memory"],
            [
                ("Accepted content strategy and cadence", memory.get("content_strategy"), "text", 7000),
                ("Content asset library", memory.get("content_asset_library"), "json", 5500),
                ("Approved and published organic posts", memory.get("organic_content_posts"), "json", 5500),
                ("Other confirmed organic-content decisions", _current_decision_items(memory, {"organic", "content", "social", "post"}), "json", 3500),
            ],
        ),
        "campaign-strategy-currently-decided.md": _current_decision_document(
            "Campaign strategy",
            "campaign-strategy",
            ["mcp_admira_save_ads_onboarding", "mcp_admira_save_ad_brief", "mcp_admira_save_durable_memory"],
            [
                ("Campaign onboarding and strategic choices", memory.get("ads_onboarding"), "text", 6000),
                ("Audience strategy", memory.get("audience_strategy"), "json", 4500),
                ("Campaign/ad briefs", brief_index, "json", 8000),
                ("Active workflow", active_workflow, "json", 3500),
                ("Other confirmed campaign decisions", _current_decision_items(memory, {"campaign", "ads", "targeting", "budget", "placement"}), "json", 5000),
            ],
            live_meta_first=True,
        ),
        "meta-campaign-execution-currently-decided.md": _current_decision_document(
            "Meta campaign execution",
            "meta-campaign-execution",
            ["mcp_admira_create_whatsapp_campaign", "mcp_admira_create_lead_form_campaign", "mcp_admira_create_website_campaign", "mcp_admira_create_messaging_campaign", "mcp_admira_create_app_campaign", "mcp_admira_create_on_meta_campaign", "mcp_admira_edit_campaign", "mcp_admira_save_durable_memory"],
            [
                ("Active workflow", active_workflow, "json", 3500),
                ("Recent confirmed backend actions", recent.get("actions"), "json", 7000),
                ("Other confirmed execution decisions", _current_decision_items(memory, {"execution", "campaign", "meta", "activation"}), "json", 4500),
            ],
            live_meta_first=True,
        ),
        "measurement-optimization-currently-decided.md": _current_decision_document(
            "Measurement and optimization",
            "measurement-optimization",
            ["mcp_admira_set_campaign_metric_priorities", "mcp_admira_record_verified_signal", "mcp_admira_save_durable_memory"],
            [
                ("Profitability and decision rules", memory.get("profitability_memory"), "json", 7500),
                ("Campaign metric profiles", memory.get("campaign_metric_profiles"), "json", 5500),
                ("Creative experiments", memory.get("creative_experiments"), "json", 5500),
                ("Business outcomes", memory.get("business_outcomes"), "json", 4500),
                ("Other confirmed measurement decisions", _current_decision_items(memory, {"measurement", "optimization", "metric", "signal", "profit"}), "json", 4500),
            ],
            live_meta_first=True,
        ),
        "support-recovery-currently-decided.md": _current_decision_document(
            "Support and recovery",
            "support-recovery",
            ["mcp_admira_save_durable_memory"],
            [
                ("Current workflow or blocker", active_workflow, "json", 4000),
                ("Recent recovery-relevant actions", recent.get("actions"), "json", 5500),
                ("Confirmed support/recovery decisions", _current_decision_items(memory, {"support", "recovery", "blocker", "connection", "update"}), "json", 4500),
            ],
        ),
    }
    index_lines = [
        "# Currently decided state index",
        "",
        "Admira has two strictly separated layers:",
        "",
        "1. `skills/*/SKILL.md` contains universal product guidance. It is versioned, immutable, and never stores one buyer's facts, decisions, or action history.",
        "2. `memory/currently-decided/*.md` contains generated buyer-specific state. Save changes through the official `mcp_admira_save_*` tools; never edit these files directly.",
        "",
        "Read the relevant skill first, then its companion state file. Current live Meta data always overrides campaign/execution/measurement memory.",
        "",
        "## Companions",
        "",
    ]
    for filename in files:
        index_lines.append(f"- `{filename}`")
    files = {"README.md": "\n".join(index_lines).strip() + "\n", **files}
    return files


def _redact_text(value):
    text = str(value or "")
    if not text:
        return ""
    replacements = [
        (r"\b(?:EA[A-Za-z0-9_-]{40,}|EAA[A-Za-z0-9_-]{40,})\b", "[redacted-token]"),
        (r"\bdop_v1_[A-Za-z0-9_-]{40,}\b", "[redacted-token]"),
        (r"\bsk-[A-Za-z0-9_-]{24,}\b", "[redacted-token]"),
        (r"(?i)\b(passphrase|password|contraseña|token|api key|access token)\s*[:=]\s*\S+", r"\1: [redacted]"),
    ]
    clean = text
    for pattern, replacement in replacements:
        clean = re.sub(pattern, replacement, clean)
    return clean


def _continuity_timezone():
    raw = (
        os.environ.get("HERMES_TIMEZONE")
        or os.environ.get("DAILY_BRIEF_TIMEZONE")
        or os.environ.get("META_DAILY_BRIEF_TIMEZONE")
        or os.environ.get("TZ")
        or "UTC"
    )
    name = str(raw or "UTC").strip() or "UTC"
    if ZoneInfo is not None:
        try:
            return name, ZoneInfo(name)
        except Exception:
            pass
    return "UTC", timezone.utc


def _parse_datetime(value):
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00") if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _append_timeline_item(items, source, role, content, created_at="", kind="message", extra=None):
    text = _redact_text(_text_excerpt(content, 1400))
    if not text:
        return
    dt = _parse_datetime(created_at) or datetime.now(timezone.utc)
    timezone_name, tz = _continuity_timezone()
    local_dt = dt.astimezone(tz)
    items.append(
        {
            "source": source,
            "role": role,
            "kind": kind,
            "content": text,
            "created_at": dt.isoformat(),
            "local_date": local_dt.date().isoformat(),
            "local_time": local_dt.strftime("%H:%M"),
            "timezone": timezone_name,
            **(extra or {}),
        }
    )


def _history_list_items(raw, source):
    items = []
    if isinstance(raw, dict):
        iterable = []
        for chat_id, history in raw.items():
            if isinstance(history, list):
                for item in history:
                    if isinstance(item, dict):
                        iterable.append({**item, "_chat_id": str(chat_id)})
    elif isinstance(raw, list):
        iterable = [item for item in raw if isinstance(item, dict)]
    else:
        iterable = []
    for item in iterable:
        role = "agent" if str(item.get("role") or "").lower() in {"agent", "assistant"} else "user"
        content = item.get("content") or item.get("message") or item.get("text") or item.get("reply") or ""
        _append_timeline_item(
            items,
            source=source,
            role=role,
            content=content,
            created_at=item.get("created_at") or item.get("updated_at") or item.get("timestamp"),
            extra={"chat_id": item.get("_chat_id", "")} if item.get("_chat_id") else None,
        )
    return items


def _activity_items(memory):
    recent = memory.get("recent_history") or {}
    items = []
    items.extend(_history_list_items(recent.get("chat"), "dashboard_chat"))
    items.extend(_history_list_items(recent.get("telegram_legacy"), "telegram_legacy"))
    items.extend(_history_list_items(recent.get("telegram_gateway"), "telegram_gateway"))
    for action in recent.get("actions") or []:
        if not isinstance(action, dict):
            continue
        summary = {
            "type": action.get("type") or action.get("action") or action.get("tool"),
            "status": action.get("status"),
            "payload": action.get("payload") or action.get("request") or action.get("result") or {},
        }
        _append_timeline_item(
            items,
            source="protected_actions",
            role="system",
            kind="action",
            content=_json_excerpt(summary, 1200),
            created_at=action.get("created_at") or action.get("timestamp") or action.get("updated_at"),
        )
    # Pending approvals are an operational inbox, not conversation memory and
    # not Meta inventory. They are intentionally excluded from the ambient
    # timeline so abandoned local requests cannot become the resumed workflow.
    for creative in recent.get("creative_refreshes") or []:
        if not isinstance(creative, dict):
            continue
        _append_timeline_item(
            items,
            source="creative_outputs",
            role="system",
            kind="creative",
            content=_json_excerpt(creative, 1200),
            created_at=creative.get("created_at") or creative.get("updated_at") or creative.get("timestamp"),
        )
    return sorted(items, key=lambda item: item.get("created_at") or "")


def latest_day_context_payload(memory, lookback_days=RECENT_CONTEXT_LOOKBACK_DAYS):
    timezone_name, tz = _continuity_timezone()
    items = _activity_items(memory)
    recent = memory.get("recent_history") or {}
    today = datetime.now(timezone.utc).astimezone(tz).date()
    selected_date = ""
    selected_items = []
    for offset in range(max(1, int(lookback_days))):
        candidate = (today - timedelta(days=offset)).isoformat()
        matches = [item for item in items if item.get("local_date") == candidate]
        if matches:
            selected_date = candidate
            selected_items = matches[-RECENT_CONTEXT_ITEM_LIMIT:]
            break
    if not selected_items and items:
        recent_cutoff = today - timedelta(days=max(1, int(lookback_days)) - 1)
        recent_items = [item for item in items if item.get("local_date", "0000-00-00") >= recent_cutoff.isoformat()]
        if recent_items:
            selected_date = recent_items[-1].get("local_date") or ""
            selected_items = [item for item in recent_items if item.get("local_date") == selected_date][-RECENT_CONTEXT_ITEM_LIMIT:]
    return {
        "selected_date": selected_date,
        "timezone": timezone_name,
        "lookback_days": lookback_days,
        "items": selected_items,
        "item_count": len(selected_items),
        "source_counts": {
            "dashboard_chat": len(recent.get("chat") or []),
            "telegram_legacy": sum(len(value) for value in (recent.get("telegram_legacy") or {}).values()) if isinstance(recent.get("telegram_legacy"), dict) else len(recent.get("telegram_legacy") or []),
            "telegram_gateway": len(recent.get("telegram_gateway") or []),
            "actions": len(recent.get("actions") or []),
            "creative_outputs": len(recent.get("creative_refreshes") or []),
        },
    }


def _latest_by_role(items, role):
    for item in reversed(items or []):
        if item.get("role") == role:
            return item
    return {}


def _infer_next_step(memory, latest_context, blocker=""):
    onboarding_plan = str(memory.get("onboarding_plan") or "")
    if blocker:
        return "Retomar el bloqueo técnico o de datos más reciente y explicar el siguiente intento seguro."
    match = re.search(r"Siguiente paso\s*:\s*([^\n.]+)", onboarding_plan, re.IGNORECASE)
    if match:
        return _text_excerpt(match.group(1), 260)
    last_agent = _latest_by_role(latest_context.get("items") or [], "agent")
    if str(last_agent.get("content") or "").strip().endswith("?"):
        return "Responder la última pregunta pendiente antes de avanzar."
    if memory.get("brand_guides", {}).get("ad_briefs"):
        return "Continuar desde el brief guardado y preparar la siguiente acción creativa o de campaña."
    if memory.get("brand_guides", {}).get("general_branding"):
        return "Continuar desde la marca guardada y completar producto/oferta, brief o campaña según el pedido."
    if has_meaningful_memory(memory.get("business_profile")):
        return "Continuar el onboarding desde la memoria de negocio ya guardada."
    return ""


def active_workflow_payload(memory, latest_context):
    items = latest_context.get("items") or []
    recent = memory.get("recent_history") or {}
    blockers = [
        item
        for item in reversed(items)
        if re.search(r"(?i)\b(error|fall[óo]|bloque|missing|falta|rate limit|timeout|not logged|page_not_found|creative_production_not_ready)\b", item.get("content") or "")
    ]
    blocker = blockers[0] if blockers else {}
    brand = memory.get("brand_guides") or {}
    if blocker:
        phase = "blocked_or_retrying"
    elif recent.get("creative_refreshes"):
        phase = "creative_review"
    elif brand.get("ad_briefs"):
        phase = "creative_or_campaign_brief"
    elif brand.get("general_branding"):
        phase = "brand_ready"
    elif has_meaningful_memory(memory.get("business_profile")):
        phase = "business_onboarding"
    else:
        phase = ""
    next_step = _infer_next_step(memory, latest_context, blocker.get("content", ""))
    return {
        "has_active_workflow": bool(phase or items),
        "phase": phase,
        "last_day_context_date": latest_context.get("selected_date", ""),
        "last_user_message": _latest_by_role(items, "user"),
        "last_agent_message": _latest_by_role(items, "agent"),
        "recent_blocker": blocker,
        "approval_context_policy": "excluded from ambient continuity; query the exact approval tool only after an explicit buyer request",
        "next_step": next_step,
        "resume_instruction": "Use this workflow silently for orientation. Resume it when the active conversation establishes that scope again; persisted workflow state alone never authorizes a product action.",
    }


def build_latest_day_context(latest_context, active_workflow):
    lines = [
        "# Latest day context",
        "",
        "This file summarizes the most recent local day with buyer activity. Use it after history cleanup, gateway restart, update, or a fresh runtime session.",
        f"Timezone: {latest_context.get('timezone', 'UTC')}",
        f"Lookback days: {latest_context.get('lookback_days', RECENT_CONTEXT_LOOKBACK_DAYS)}",
        f"Latest local activity day: {latest_context.get('selected_date') or 'none'}",
        "",
    ]
    if latest_context.get("items"):
        lines.extend(["## Timeline", ""])
        for item in latest_context.get("items", []):
            role = item.get("role", "system")
            source = item.get("source", "")
            when = f"{item.get('local_date', '')} {item.get('local_time', '')}".strip()
            lines.append(f"- {when} [{source}/{role}]: {_text_excerpt(item.get('content'), 420)}")
        lines.append("")
    else:
        lines.extend(["## Timeline", "", "- No chat/action activity found in the recent lookback window.", ""])
    lines.extend(
        [
            "## Active workflow",
            "",
            f"- Phase: {active_workflow.get('phase') or 'none'}",
            f"- Next step: {active_workflow.get('next_step') or 'Use durable business/brand memory and ask one necessary question.'}",
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def conversation_continuity_status(memory):
    brand = memory.get("brand_guides") or {}
    recent = memory.get("recent_history") or {}
    latest_context = memory.get("latest_day_context") or {}
    active_workflow = memory.get("active_workflow") or {}
    communication_style = communication_style_from_environment()
    ad_experience = ad_experience_from_environment()
    operator_preference_saved = bool(str(os.environ.get("AGENT_COMMUNICATION_STYLE") or "").strip()) or bool(ad_experience)
    sources = {
        "business_profile": has_meaningful_memory(memory.get("business_profile")),
        "onboarding_questions": has_meaningful_memory(memory.get("onboarding_questions")),
        "onboarding_plan": has_meaningful_memory(memory.get("onboarding_plan")),
        "branding_onboarding": has_meaningful_memory(memory.get("branding_onboarding")),
        "ads_campaign_onboarding": has_meaningful_memory(memory.get("ads_onboarding")),
        "audience_strategy": has_meaningful_memory(memory.get("audience_strategy")),
        "general_branding": has_meaningful_memory(brand.get("general_branding")),
        "offer_map": has_meaningful_memory(brand.get("offer_map")),
        "creative_references": has_meaningful_memory(memory.get("creative_references")),
        "content_asset_library": has_meaningful_memory(memory.get("content_asset_library")),
        "content_strategy": has_meaningful_memory(memory.get("content_strategy")),
        "durable_conversation_memory": has_meaningful_memory(memory.get("durable_conversation_memory")),
        "product_guides": has_meaningful_memory(brand.get("products")),
        "ad_briefs": has_meaningful_memory(brand.get("ad_briefs")),
        "latest_day_context": bool(latest_context.get("selected_date")),
        "active_workflow": bool(active_workflow.get("has_active_workflow")),
        "telegram_gateway_turns": has_meaningful_memory(recent.get("telegram_gateway")),
        "telegram_legacy_history": has_meaningful_memory(recent.get("telegram_legacy")),
        "recent_actions": has_meaningful_memory(recent.get("actions")),
        "recent_creative_outputs": has_meaningful_memory(recent.get("creative_refreshes")),
        "creative_experiments": has_meaningful_memory(memory.get("creative_experiments")),
        "business_outcomes": has_meaningful_memory(memory.get("business_outcomes")),
        "operator_preferences": operator_preference_saved,
    }
    resume_sources = {key: value for key, value in sources.items() if key != "operator_preferences"}
    has_persistent_memory = any(resume_sources.values())
    return {
        "has_persistent_memory": has_persistent_memory,
        "has_saved_operator_preferences": operator_preference_saved,
        "resume_required": False,
        "orientation_required": has_persistent_memory,
        "auto_resume_allowed": False,
        "session_history_is_cache": True,
        "instructions": {
            "on_history_cleanup_or_gateway_restart": "read durable workspace files silently for orientation; infer intent from the new active exchange and never resume a product mutation from persisted state alone",
            "if_has_persistent_memory": "do not restart onboarding, do not introduce yourself as first time, and do not repeat the ads-experience question unless it is genuinely missing after checking memory",
            "if_no_persistent_memory": "a first onboarding greeting is acceptable",
        },
        "sources": sources,
        "counts": {
            "product_guides": len(brand.get("products") or []),
            "ad_briefs": len(brand.get("ad_briefs") or []),
            "recent_actions": len(recent.get("actions") or []),
            "telegram_gateway_turns": len(recent.get("telegram_gateway") or []),
            "recent_creative_outputs": len(recent.get("creative_refreshes") or []),
            "content_assets": len((memory.get("content_asset_library") or {}).get("items") or []),
        },
        "latest_day_context": {
            "selected_date": latest_context.get("selected_date", ""),
            "timezone": latest_context.get("timezone", ""),
            "item_count": latest_context.get("item_count", 0),
        },
        "active_workflow": {
            "has_active_workflow": bool(active_workflow.get("has_active_workflow")),
            "phase": active_workflow.get("phase", ""),
            "next_step": active_workflow.get("next_step", ""),
        },
        "operator_preferences": {
            "communication_style": communication_style,
            "ad_experience_level": ad_experience,
        },
    }


def build_conversation_continuity(memory, status=None):
    status = status or conversation_continuity_status(memory)
    brand = memory.get("brand_guides") or {}
    recent = memory.get("recent_history") or {}
    latest_context = memory.get("latest_day_context") or {}
    active_workflow = memory.get("active_workflow") or {}
    lines = [
        "# Conversation continuity",
        "",
        "This file is the recovery brief for Telegram/Hermes history cleanup, gateway restarts, updates, or a brand-new runtime session.",
        f"Persistent memory found: {'yes' if status.get('has_persistent_memory') else 'no'}",
        "",
    ]
    if status.get("has_persistent_memory"):
        lines.extend(
            [
                "## Resume behavior",
                "",
                "- Treat Telegram/Hermes session history as cache. These durable workspace files are the source of truth after cleanup or updates.",
                "- Before sending a first message, read this file plus `memory/latest_day_context.md`, `memory/active_workflow.json`, `CURRENT_CONTEXT.json`, `data/business_profile.json`, `memory/Agent onboarding plan.md`, `memory/Ads campaign onboarding.md`, `memory/recent_actions.json`, `memory/creative_experiments.json`, `memory/content_asset_library.json`, `memory/content_strategy.md`, and relevant `brand_guides/` files.",
                "- Pending approvals are intentionally absent from ambient continuity. Query the exact product approval tool only after an explicit buyer request to approve, reject, or activate one exact action.",
                "- Do not restart onboarding, do not introduce yourself as if this were the first conversation, and do not repeat the initial ads-experience/technical-style question if it is already configured or implied by saved memory.",
                "- If the current Hermes session is empty, use memory silently for orientation while interpreting the buyer's new message naturally. Resume a saved workflow only when the active exchange establishes that scope again.",
                "- A short acknowledgement can approve an action only when it answers an immediately preceding explicit question in the active conversation; persisted memory alone cannot supply the missing question or authorization.",
                "- If needed, use session search to look for the previous Telegram session, but never block the buyer on that search when durable workspace memory is enough to continue.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## First-run behavior",
                "",
                "- No durable business/brand/ad memory was found. A normal first onboarding greeting is acceptable.",
                "",
            ]
        )
    lines.extend(
        [
            "## Source checklist",
            "",
            *[f"- {name}: {'yes' if found else 'no'}" for name, found in (status.get("sources") or {}).items()],
            "",
        ]
    )
    if latest_context.get("selected_date"):
        lines.extend(
            [
                "## Latest day context",
                "",
                f"- Latest local activity day: {latest_context.get('selected_date')} ({latest_context.get('timezone', 'UTC')})",
                f"- Activity items in that day: {latest_context.get('item_count', 0)}",
                "",
            ]
        )
    if active_workflow.get("has_active_workflow"):
        last_user = active_workflow.get("last_user_message") or {}
        last_agent = active_workflow.get("last_agent_message") or {}
        lines.extend(
            [
                "## Active workflow",
                "",
                f"- Phase: {active_workflow.get('phase') or 'unknown'}",
                f"- Next step: {active_workflow.get('next_step') or 'continue from saved memory'}",
            ]
        )
        if last_user.get("content"):
            lines.append(f"- Last buyer message: {_text_excerpt(last_user.get('content'), 500)}")
        if last_agent.get("content"):
            lines.append(f"- Last agent message: {_text_excerpt(last_agent.get('content'), 500)}")
        lines.append("")
    if has_meaningful_memory(memory.get("business_profile")):
        lines.extend(["## Known business profile", "", "```json", _json_excerpt(memory.get("business_profile"), 2200), "```", ""])
    if has_meaningful_memory(memory.get("onboarding_plan")):
        lines.extend(["## Last known onboarding plan", "", _text_excerpt(memory.get("onboarding_plan"), 1800), ""])
    if has_meaningful_memory(memory.get("branding_onboarding")):
        lines.extend(["## Branding onboarding", "", _text_excerpt(memory.get("branding_onboarding"), 1600), ""])
    if has_meaningful_memory(memory.get("ads_onboarding")):
        lines.extend(["## Ads/campaign onboarding memory", "", _text_excerpt(memory.get("ads_onboarding"), 1800), ""])
    if has_meaningful_memory(brand.get("general_branding")):
        lines.extend(["## Brand memory", "", _text_excerpt(brand.get("general_branding"), 1800), ""])
    if has_meaningful_memory(brand.get("offer_map")):
        lines.extend(["## Offer map", "", _text_excerpt(brand.get("offer_map"), 1800), ""])
    if has_meaningful_memory(memory.get("creative_references")):
        lines.extend(["## Creative references", "", _text_excerpt(memory.get("creative_references"), 1200), ""])
    if has_meaningful_memory(memory.get("content_strategy")):
        lines.extend(["## Organic content strategy", "", _text_excerpt(memory.get("content_strategy"), 1600), ""])
    if has_meaningful_memory(memory.get("content_asset_library")):
        lines.extend(["## Content asset library", "", "```json", _json_excerpt(memory.get("content_asset_library"), 2200), "```", ""])
    products = brand.get("products") or []
    if products:
        lines.extend(["## Product guides", ""])
        for product in products[:MEMORY_ITEM_LIMIT]:
            lines.append(f"- `{product.get('path', 'product')}`: {_text_excerpt(product.get('content'), 700)}")
        lines.append("")
    ad_briefs = brand.get("ad_briefs") or []
    if ad_briefs:
        lines.extend(["## Ad briefs", ""])
        for ad_brief in ad_briefs[:MEMORY_ITEM_LIMIT]:
            lines.append(f"- `{ad_brief.get('path', 'ad_brief')}`: {_text_excerpt(ad_brief.get('content'), 700)}")
        lines.append("")
    if has_meaningful_memory(recent.get("actions")):
        lines.extend(["## Recent protected actions", "", "```json", _json_excerpt(recent.get("actions"), 2200), "```", ""])
    if has_meaningful_memory(recent.get("creative_refreshes")):
        lines.extend(["## Recent creative outputs", "", "```json", _json_excerpt(recent.get("creative_refreshes"), 2200), "```", ""])
    if has_meaningful_memory(memory.get("creative_experiments")):
        lines.extend(["## Creative experiment checkpoints", "", "```json", _json_excerpt(memory.get("creative_experiments"), 2200), "```", ""])
    lines.extend(
        [
            "## Safe next-message pattern",
            "",
            "When memory exists, start with something like: “Retomo donde quedamos: ya tengo [one concrete remembered item]. Lo siguiente es [next useful step].” Then ask only one clear question if needed.",
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def prepare_hermes_workspace(payload):
    memory = business_memory_context()
    continuity_status = conversation_continuity_status(memory)
    if HERMES_WORKSPACE_DIR.exists():
        make_workspace_tree_writable()
        # Hermes keeps the gateway and MCP server cwd inside this directory.
        # Removing the root leaves those long-lived processes in a Linux
        # ``(deleted)`` cwd, which then breaks otherwise valid subprocesses
        # such as ``codex login status``. Refresh only its curated contents so
        # the workspace inode remains stable for the lifetime of the gateway.
        for child in HERMES_WORKSPACE_DIR.iterdir():
            if child.is_symlink() or child.is_file():
                child.unlink()
            else:
                shutil.rmtree(child)
    HERMES_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    written = write_agent_profile_workspace_files()
    written.append(
        write_workspace_file(
            "README.md",
            """# Hermes Workspace

This folder is the only workspace Hermes should read for this product turn.
It contains curated business memory, brand guides, recent activity, and uploaded reference images.

The only operational skills allowed in Admira IA are the official, versioned files under this workspace's `skills/` directory. Never consult, create, patch, or route through Hermes personal/global skills. Product-wide behavior changes must arrive through an official Admira update; buyer facts, decisions, preferences, and action history belong in durable memory through the product's save tools.

Skills are immutable guidance. They never hold one buyer's current choices. Read the relevant companion under `memory/currently-decided/` for buyer-specific state, and persist updates only through the named `mcp_admira_save_*` tool. This entire curated workspace is read-only to Hermes; official tools update backend-owned stores and the next turn regenerates the snapshots.

Hermes owns the conversation and should use its own session memory. The backend does not paste the whole chat history into the prompt.
Before every buyer-facing turn, read `skills/core-agent-behavior/SKILL.md`. If session memory was cleaned, the gateway restarted, or an update created a fresh runtime session, also read `skills/session-continuity/SKILL.md`, `memory/Conversation continuity.md`, `memory/continuity_status.json`, `memory/latest_day_context.md`, `memory/active_workflow.json`, `CURRENT_CONTEXT.json`, `data/business_profile.json`, `memory/Agent onboarding plan.md`, `memory/Branding onboarding.md`, `memory/Ads campaign onboarding.md`, `brand_guides/Offer map.md`, and relevant `brand_guides/` files before greeting.

Every ordinary buyer message is accompanied by an automatically fetched live Meta context. Read it silently first on every turn. It overrides memory, plans, action logs, created-campaign drafts, and pending approvals for the current campaign/ad set/ad inventory and performance. Pending approvals are absent from ambient workspace memory; query the exact product approval tool only after an explicit request to approve, reject, or activate one exact action.

Never expose this workspace's internal paths to the buyer. If the buyer asks for a prompt, plan, script, copy, or diagnosis, paste the useful content directly in the chat instead of pointing them to `/app/...`, `dashboard/data/...`, `hermes-workspace/...`, `brand_guides/...`, `memory/...`, or `CURRENT_CONTEXT.json`.

Do not request files outside this workspace. If something is missing, ask the buyer or request a backend tool.

Product actions are exposed as Hermes MCP tools with names starting with `mcp_admira_`.
Read `skills/README.md`, then the relevant `skills/*/SKILL.md` file before acting.
""",
        )
    )
    written.append(
        write_workspace_file(
            "CURRENT_CONTEXT.json",
            scrub_memory(
                redact_payload(
                    {
                        "channel": payload.get("channel") or "dashboard",
                        "language": payload.get("language") or "",
                        "account_context": payload.get("account_context") or {},
                        "image_paths": safe_image_paths(payload),
                    }
                )
            ),
        )
    )
    written.append(write_workspace_file("data/business_profile.json", memory["business_profile"]))
    written.append(write_workspace_file("memory/continuity_status.json", continuity_status))
    written.append(write_workspace_file("memory/Conversation continuity.md", build_conversation_continuity(memory, continuity_status)))
    written.append(write_workspace_file("memory/latest_day_context.md", build_latest_day_context(memory["latest_day_context"], memory["active_workflow"])))
    written.append(write_workspace_file("memory/active_workflow.json", memory["active_workflow"]))
    written.append(write_workspace_file("memory/Onboarding questions.md", memory.get("onboarding_questions", "")))
    written.append(write_workspace_file("memory/Agent onboarding plan.md", memory.get("onboarding_plan", "")))
    written.append(write_workspace_file("memory/Branding onboarding.md", memory.get("branding_onboarding", "")))
    written.append(write_workspace_file("memory/Ads campaign onboarding.md", memory.get("ads_onboarding", "")))
    written.append(write_workspace_file("data/audience_strategy.json", memory["audience_strategy"]))
    written.append(write_workspace_file("data/business_binding.json", memory["business_binding"]))
    written.append(write_workspace_file("memory/recent_actions.json", memory["recent_history"]["actions"]))
    written.append(write_workspace_file("memory/recent_telegram_gateway_turns.json", memory["recent_history"].get("telegram_gateway", [])))
    written.append(write_workspace_file("memory/creative_refreshes.json", memory["recent_history"]["creative_refreshes"]))
    written.append(write_workspace_file("memory/profitability_rules.json", memory["profitability_memory"].get("profitability_rules", {})))
    written.append(write_workspace_file("memory/decision_memory.json", memory["profitability_memory"]))
    written.append(write_workspace_file("memory/creative_experiments.json", memory["creative_experiments"]))
    written.append(write_workspace_file("memory/campaign_metric_profiles.json", memory.get("campaign_metric_profiles", {"campaigns": {}})))
    written.append(write_workspace_file("memory/content_asset_library.json", memory.get("content_asset_library", {"items": []})))
    written.append(write_workspace_file("memory/content_strategy.md", memory.get("content_strategy", "")))
    written.append(write_workspace_file("memory/organic_content_posts.json", memory.get("organic_content_posts", {"items": []})))
    written.append(write_workspace_file("memory/durable_conversation_memory.json", memory.get("durable_conversation_memory", {"items": []})))
    for name, content in build_currently_decided_state(memory).items():
        written.append(write_workspace_file(f"memory/currently-decided/{name}", content))
    written.append(write_workspace_file("memory/optimization_state.json", memory["optimization_state"]))
    written.append(write_workspace_file("memory/business_outcomes.json", memory["business_outcomes"]))
    written.append(write_workspace_file("memory/optimization_research.json", memory["optimization_research"]))
    written.append(write_workspace_file("memory/learning_log.md", format_learning_log()))
    written.append(write_workspace_file("brand_guides/general_branding.md", memory["brand_guides"]["general_branding"]))
    written.append(write_workspace_file("brand_guides/Offer map.md", memory["brand_guides"].get("offer_map", "")))
    written.append(write_workspace_file("brand_guides/creative_references.md", memory.get("creative_references", "")))
    for product in memory["brand_guides"]["products"]:
        name = Path(product["path"]).name
        written.append(write_workspace_file(f"brand_guides/products/{name}", product["content"]))
    for ad_brief in memory["brand_guides"].get("ad_briefs", []):
        name = Path(ad_brief["path"]).name
        written.append(write_workspace_file(f"brand_guides/ad_briefs/{name}", ad_brief["content"]))
    workspace_images = []
    uploads_dir = HERMES_WORKSPACE_DIR / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    for image_path in safe_image_paths(payload):
        workspace_images.append(copy_workspace_file(image_path, "uploads"))
    # Hermes reads this curated workspace but never writes policy or buyer
    # state into it. Official MCP tools update backend-owned stores; the next
    # turn rebuilds this complete snapshot from those confirmed stores.
    protected_files = protect_workspace_tree(".")
    # Telegram/dashboard may receive another attachment after the curated
    # snapshot was built. Keep only this bounded inbox writable; it contains
    # assets, never policy or durable buyer-state source files.
    uploads_dir.chmod(0o755)
    return {
        "path": str(HERMES_WORKSPACE_DIR),
        "files": written,
        "image_paths": workspace_images,
        "protected_files": protected_files,
        "memory": memory,
        "continuity_status": continuity_status,
        "active_workflow": memory["active_workflow"],
        "latest_day_context": memory["latest_day_context"],
    }


def hermes_session_name(payload):
    if not payload.get("channel"):
        return ""
    channel = str(payload.get("channel") or "").strip().lower()
    if channel == "telegram":
        raw_key = str(payload.get("session_key") or "default")
        digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:12]
        return f"meta-ads-agent-telegram-{digest}"
    if channel == "dashboard":
        return "meta-ads-agent-dashboard"
    return ""


def hermes_session_source(payload):
    channel = str(payload.get("channel") or "").strip().lower()
    if channel == "telegram":
        return "meta-ads-agent-telegram"
    if channel == "dashboard":
        return "meta-ads-agent-dashboard"
    return "meta-ads-agent"


def freeform_agent_mode_enabled():
    raw = str(os.environ.get("ADMIRA_FREEFORM_AGENT_MODE") or "").strip().lower()
    if raw:
        return raw in {"1", "true", "yes", "on", "enabled"}
    marker = ROOT_DIR / "runtime" / "freeform-agent-mode"
    try:
        return marker.read_text(encoding="utf-8").strip().lower() in {
            "1", "true", "yes", "on", "enabled"
        }
    except OSError:
        return False


def hermes_user_query(payload, workspace_info):
    message = str(payload.get("message") or "").strip()
    if not message:
        return ""
    if freeform_agent_mode_enabled():
        # The concise root contract plus the MCP→skill map are the only routing
        # instructions needed. Repeating action-biased notes after every buyer
        # message makes ordinary answers look like execution authorization.
        return message
    channel = str(payload.get("channel") or "dashboard").strip().lower()
    if channel in {"telegram", "dashboard"}:
        return (
            f"{message}\n\n"
            "Nota de sistema del producto: el contexto actual de la cuenta está en `CURRENT_CONTEXT.json`. "
            "Usa ese archivo y tu memoria de sesión solo si hace falta para responder o preparar una acción. "
            "Si el mensaje incluye una URL pública o un enlace de Google Drive para usar como creativo, usa mcp_admira_fetch_public_asset antes de decir que no puedes acceder; después usa web/browser si hace falta investigación adicional. "
            "Si el comprador pide crear o preparar campaña, usa las herramientas MCP de Admira cuando estén disponibles. "
            "Si el comprador pide modificar una campaña existente, con cualquier redacción o error tipográfico, debes llamar a mcp_admira_edit_campaign pasando su solicitud original; no respondas desde memoria ni narres el cambio como aplicado. El MCP resuelve la campaña, prepara el diff y devuelve el estado real. "
            "Si estás en un contexto sin MCP, devuelve el JSON tool_request del producto. No digas que necesitas terminal o CLI."
        )
    return (
        f"{message}\n\n"
        "Nota de sistema del producto: usa solo los archivos de este workspace y las reglas de `AGENTS.md`. "
        "No necesitas historial acumulado para esta tarea puntual."
    )


def hermes_environment(config):
    env = os.environ.copy()
    # Every Hermes subprocess must load Admira's compatibility hooks. This is
    # not provider-specific: dashboard and simulated-Telegram conversations
    # launch Hermes CLI processes directly, and every brain consumes MCP tool
    # results. Hermes 0.18 reads ``CallToolResult.isError`` while MCP 2.x
    # exposes ``is_error`` as the Python field, so sitecustomize must install
    # the compatibility alias before Hermes imports its MCP adapter.
    source_path = str(ROOT_DIR / "src")
    python_paths = [path for path in str(env.get("PYTHONPATH") or "").split(os.pathsep) if path]
    if source_path not in python_paths:
        python_paths.insert(0, source_path)
    env["PYTHONPATH"] = os.pathsep.join(python_paths)
    env["ADMIRA_HERMES_RUNTIME_PATCHES"] = "1"
    # Make the cross-process NIM request gate resolve to the product runtime
    # even when the dashboard was launched from a different working directory.
    env["ADMIRA_PRODUCT_ROOT"] = str(ROOT_DIR)
    timezone_name = str(getattr(config, "daily_brief_timezone", "UTC") or "UTC")
    # Hermes' scheduler resolves wall-clock time from HERMES_TIMEZONE. TZ is
    # also set for child processes and third-party tools launched by Hermes.
    env["HERMES_TIMEZONE"] = timezone_name
    env["TZ"] = timezone_name
    hermes_home = getattr(config, "hermes_home", "") or DATA_DIR / "hermes-home"
    if hermes_home:
        path = Path(str(hermes_home)).expanduser()
        if not path.is_absolute():
            path = ROOT_DIR / path
        env["HERMES_HOME"] = str(path)
        # Keep Codex/ChatGPT auth isolated to the same buyer-specific home.
        # Some Codex paths still consult CODEX_HOME; inheriting the container's
        # global value can keep an old account alive after the dashboard says it
        # was disconnected.
        configured_codex_home = (
            os.environ.get("ADMIRA_CODEX_AUTH_HOME")
            or os.environ.get("CODEX_AUTH_HOME")
            or ""
        ).strip()
        codex_home = Path(configured_codex_home).expanduser() if configured_codex_home else path / "codex-auth"
        env["CODEX_HOME"] = str(codex_home)
    settings = hermes_brain_settings(config)
    connections = agent_model_connections(config, include_secrets=True)
    provider_env = {
        "minimax": (ADMIRA_MINIMAX_KEY_ENV, "ADMIRA_MINIMAX_BASE_URL", "ADMIRA_MINIMAX_MODEL"),
        "nvidia_nim": (ADMIRA_NVIDIA_KEY_ENV, "ADMIRA_NVIDIA_BASE_URL", "ADMIRA_NVIDIA_MODEL"),
        "gemini": (ADMIRA_GEMINI_KEY_ENV, "GEMINI_BASE_URL", "GEMINI_MODEL"),
        "openai_api": (ADMIRA_OPENAI_KEY_ENV, "ADMIRA_OPENAI_BASE_URL", "ADMIRA_OPENAI_MODEL"),
        "custom_api": (ADMIRA_CUSTOM_KEY_ENV, "ADMIRA_CUSTOM_BASE_URL", "ADMIRA_CUSTOM_MODEL"),
    }
    for provider, connection in connections.items():
        if not connection.get("configured"):
            continue
        key_env, base_env, model_env = provider_env[provider]
        env[key_env] = str(connection.get("api_key") or "").strip()
        env[base_env] = str(connection.get("base_url") or "").strip()
        env[model_env] = str(connection.get("model") or "").strip()
    minimax_settings = admira_minimax_credentials(config, settings)
    if minimax_settings.get("api_key"):
        # Do not expose Admira's official MiniMax key as MINIMAX_API_KEY.
        # Hermes treats that variable as a signal to show/use its native
        # MiniMax provider, whose transport can differ from MiniMax's official
        # OpenAI-compatible endpoint. Admira registers MiniMax M3 as a named
        # custom provider instead, so keep the key under an Admira-only env var.
        env.pop("MINIMAX_API_KEY", None)
        env[ADMIRA_MINIMAX_KEY_ENV] = minimax_settings["api_key"]
        if minimax_settings.get("base_url"):
            env[ADMIRA_MINIMAX_BASE_URL_ENV] = minimax_settings["base_url"]
        env["ADMIRA_MINIMAX_PROVIDER"] = ADMIRA_MINIMAX_PROVIDER
        env["ADMIRA_MINIMAX_MODEL"] = minimax_settings.get("model") or "MiniMax-M3"
    if settings.get("brain") == "nvidia_nim" and settings.get("api_key"):
        env[ADMIRA_NVIDIA_KEY_ENV] = settings["api_key"]
        env[ADMIRA_NVIDIA_BASE_URL_ENV] = settings.get("base_url") or ADMIRA_NVIDIA_DEFAULT_BASE_URL
        env["ADMIRA_NVIDIA_PROVIDER"] = ADMIRA_NVIDIA_PROVIDER
        env["ADMIRA_NVIDIA_MODEL"] = settings.get("model") or ADMIRA_NVIDIA_DEFAULT_MODEL
        # The auxiliary compressor is deliberately configured through
        # Hermes' universally supported `custom` endpoint. Keep this bridge
        # process-local; never write the key to config.yaml or workspace
        # memory. The main agent still uses the named Admira NVIDIA provider.
        env["OPENAI_API_KEY"] = settings["api_key"]
        # Prevent one failed stream from being replayed by Hermes' inner
        # transport loop. The outer agent policy owns the single bounded
        # attempt, while the runtime patch applies the shared request gate.
        env["HERMES_STREAM_RETRIES"] = "0"
        env["ADMIRA_NVIDIA_REQUESTS_PER_MINUTE"] = "36"
        env["ADMIRA_NVIDIA_MIN_REQUEST_INTERVAL_SECONDS"] = "1.7"
        env["ADMIRA_NVIDIA_REQUEST_DIAGNOSTICS_FILE"] = str(ROOT_DIR / "logs" / "nvidia-request-diagnostics.jsonl")
        env["ADMIRA_HERMES_RUNTIME_PATCHES"] = "1"
    if settings.get("brain") == "gemini" and settings.get("api_key"):
        env[ADMIRA_GEMINI_KEY_ENV] = settings["api_key"]
        env["GEMINI_BASE_URL"] = settings.get("base_url") or ADMIRA_GEMINI_DEFAULT_BASE_URL
        env["GEMINI_MODEL"] = settings.get("model") or ADMIRA_GEMINI_DEFAULT_MODEL
        if str(settings.get("model") or "").strip().lower() == ADMIRA_GEMINI_DEFAULT_MODEL:
            policy = inference_runtime_policy(settings)
            env["ADMIRA_GEMINI_DAILY_REQUEST_LIMIT"] = str(policy["daily_request_limit"])
            env["ADMIRA_GEMINI_REQUESTS_PER_MINUTE"] = str(policy["requests_per_minute"])
            env["ADMIRA_GEMINI_MIN_REQUEST_INTERVAL_SECONDS"] = str(policy["min_request_interval_seconds"])
            env["HERMES_STREAM_RETRIES"] = "0"
            env["HERMES_CRON_MAX_PARALLEL"] = "1"
            env["ADMIRA_HERMES_RUNTIME_PATCHES"] = "1"
    if settings.get("provider") == "custom" and settings.get("api_key"):
        env["OPENAI_API_KEY"] = settings["api_key"]
        if settings.get("base_url"):
            env["OPENAI_BASE_URL"] = settings["base_url"]
    return env


def admira_minimax_credentials(config, primary_settings=None):
    """Return MiniMax credentials that should be available to Hermes /model.

    MiniMax may be the primary text brain, or it may be a saved secondary API
    credential the buyer wants to select manually from Telegram with /model.
    In both cases the key must be available under Admira's custom provider env,
    otherwise Hermes can list/select MiniMax and then fail provider auth.
    """
    settings = dict(primary_settings or {})
    if settings.get("provider") == "minimax" and settings.get("api_key"):
        return {
            "api_key": str(settings.get("api_key") or "").strip(),
            "base_url": str(settings.get("base_url") or "https://api.minimax.io/v1").strip().rstrip("/"),
            "model": str(settings.get("model") or "MiniMax-M3").strip(),
        }
    api_key = str(getattr(config, "agent_chat_api_key", "") or "").strip()
    base_url = str(getattr(config, "agent_chat_base_url", "") or "").strip().rstrip("/")
    model = str(getattr(config, "agent_chat_model", "") or "").strip()
    brain = str(getattr(config, "agent_brain_provider", "") or "").strip().lower().replace("-", "_")
    looks_like_minimax = (
        brain in {"minimax", "minimax_m3"}
        or "minimax" in base_url.lower()
        or "minimax" in model.lower()
    )
    if api_key and looks_like_minimax:
        return {
            "api_key": api_key,
            "base_url": base_url or "https://api.minimax.io/v1",
            "model": model or "MiniMax-M3",
        }
    env_key = os.environ.get(ADMIRA_MINIMAX_KEY_ENV, "").strip()
    if env_key:
        return {
            "api_key": env_key,
            "base_url": os.environ.get(ADMIRA_MINIMAX_BASE_URL_ENV, "https://api.minimax.io/v1").strip().rstrip("/") or "https://api.minimax.io/v1",
            "model": os.environ.get("ADMIRA_MINIMAX_MODEL", "MiniMax-M3").strip() or "MiniMax-M3",
        }
    return {}


def hermes_brain_settings(config):
    brain = str(getattr(config, "agent_brain_provider", "") or "").strip().lower().replace("-", "_")
    if not brain:
        legacy = str(getattr(config, "agent_chat_provider", "") or "").strip().lower().replace("-", "_")
        if legacy == "minimax":
            brain = "minimax"
        elif legacy in {"openai", "openai_compatible"}:
            base = str(getattr(config, "agent_chat_base_url", "") or "")
            brain = "openai_api" if "api.openai.com" in base else "custom_api"
        else:
            brain = "openai_codex"
    if brain in {"chatgpt", "chatgpt_subscription", "codex", "openai_codex", "hermes"}:
        return {
            "brain": "openai_codex",
            "provider": "openai-codex",
            "model": normalize_hermes_model(getattr(config, "hermes_model", "")),
            "base_url": "",
            "api_key": "",
            "requires_codex_auth": True,
        }
    if brain in {"minimax", "minimax_m3"}:
        return {
            "brain": "minimax",
            "provider": "minimax",
            "model": str(getattr(config, "agent_chat_model", "") or "MiniMax-M3").strip(),
            "base_url": str(getattr(config, "agent_chat_base_url", "") or "https://api.minimax.io/v1").strip().rstrip("/"),
            "api_key": str(getattr(config, "agent_chat_api_key", "") or "").strip(),
            "requires_codex_auth": False,
        }
    if brain in {"gemini", "google", "google_ai_studio"}:
        return {
            "brain": "gemini",
            "provider": ADMIRA_GEMINI_PROVIDER,
            "model": str(getattr(config, "agent_chat_model", "") or ADMIRA_GEMINI_DEFAULT_MODEL).strip(),
            "base_url": str(getattr(config, "agent_chat_base_url", "") or ADMIRA_GEMINI_DEFAULT_BASE_URL).strip().rstrip("/"),
            "api_key": str(getattr(config, "agent_chat_api_key", "") or os.environ.get(ADMIRA_GEMINI_KEY_ENV, "")).strip(),
            "requires_codex_auth": False,
        }
    if brain in {"nvidia", "nvidia_api", "nvidia_nim"}:
        user_selected = bool(getattr(config, "agent_nvidia_model_user_selected", False))
        return {
            "brain": "nvidia_nim",
            "provider": "nvidia_nim",
            "model": normalize_nvidia_model(
                getattr(config, "agent_chat_model", "") or ADMIRA_NVIDIA_DEFAULT_MODEL,
                user_selected=user_selected,
            ),
            "base_url": str(getattr(config, "agent_chat_base_url", "") or ADMIRA_NVIDIA_DEFAULT_BASE_URL).strip().rstrip("/"),
            "api_key": str(getattr(config, "agent_chat_api_key", "") or "").strip(),
            "requires_codex_auth": False,
        }
    if brain in {"openai", "openai_api"}:
        return {
            "brain": "openai_api",
            "provider": "custom",
            "model": str(getattr(config, "agent_chat_model", "") or "gpt-4.1-mini").strip(),
            "base_url": str(getattr(config, "agent_chat_base_url", "") or "https://api.openai.com/v1").strip().rstrip("/"),
            "api_key": str(getattr(config, "agent_chat_api_key", "") or "").strip(),
            "requires_codex_auth": False,
        }
    return {
        "brain": "custom_api",
        "provider": "custom",
        "model": str(getattr(config, "agent_chat_model", "") or "").strip(),
        "base_url": str(getattr(config, "agent_chat_base_url", "") or "").strip().rstrip("/"),
        "api_key": str(getattr(config, "agent_chat_api_key", "") or "").strip(),
        "requires_codex_auth": False,
    }


def hermes_brain_ready(config):
    settings = hermes_brain_settings(config)
    if settings["requires_codex_auth"]:
        ready, detail = hermes_codex_ready(config)
        return ready, detail
    missing = []
    if not settings.get("api_key"):
        missing.append("API key")
    if not settings.get("model"):
        missing.append("model")
    if settings.get("provider") == "custom" and not settings.get("base_url"):
        missing.append("base URL")
    if missing:
        return False, "Missing " + ", ".join(missing)
    label = settings["brain"].replace("_", " ")
    return True, f"{label} configured inside Hermes"


def setup_reply(language="es"):
    if language == "es":
        return (
            "Todavia falta conectar el cerebro del agente. Abre Configuracion > Conectar ChatGPT o modelo API "
            "para terminar el paso guiado. En PC/Mac se abre la terminal; en VPS/DigitalOcean el dashboard "
            "muestra el login desde el navegador."
        )
    return (
        "The agent brain is not connected yet. Open Setup > Connect ChatGPT or API model for guided steps. "
        "On desktop it can open a terminal; on VPS/DigitalOcean the dashboard shows the login in the browser."
    )


def runtime_failure_reply(language="es"):
    if language == "es":
        return (
            "No pude completar este turno por un error interno temporal del agente. "
            "Tus conexiones y el trabajo guardado siguen intactos; intenta de nuevo."
        )
    return (
        "I could not complete this turn because of a temporary internal agent error. "
        "Your connections and saved work are intact; please try again."
    )


def model_usage_limit_error(error_text):
    return is_rate_limit_text(error_text)


def model_usage_limit_retry_hint(error_text):
    seconds = retry_seconds_from_text(error_text)
    if seconds is not None:
        return retry_delay_hint(error_text, "en")
    return textual_retry_hint(error_text)


def localized_retry_hint(hint, language="es"):
    return localized_textual_hint(hint, language)


def model_usage_limit_reply(language="es", error_text=""):
    if codex_plan_type_from_text(error_text) == "go":
        return codex_go_limit_reply(error_text, language)
    hint = retry_delay_hint(error_text, language)
    if language == "en":
        base = (
            "ChatGPT/Codex is connected, but the model hit a temporary usage limit. "
            "I will not invent an answer or execute actions while the brain cannot respond."
        )
        model_hint = lighter_model_switch_hint("en")
        if hint:
            return f"{base} Try again after: {localized_retry_hint(hint, 'en')}. {model_hint}"
        return f"{base} Try again later; the provider did not send me an exact reset time. {model_hint}"
    base = (
        "Tu ChatGPT/Codex sí está conectado, pero el modelo alcanzó su límite temporal de uso. "
        "No voy a inventar una respuesta ni ejecutar acciones mientras el cerebro no pueda responder."
    )
    model_hint = lighter_model_switch_hint("es")
    if hint:
        return f"{base} Puedes intentar de nuevo en {localized_retry_hint(hint, 'es')}. {model_hint}"
    return f"{base} Intenta de nuevo más tarde; el proveedor no me dio una hora exacta de reinicio. {model_hint}"


def extract_codex_account_identity(text):
    """Best-effort extraction of the connected ChatGPT/Codex account label."""
    raw = str(text or "")
    email_match = re.search(r"[\w.!#$%&'*+/=?^_`{|}~-]+@[\w-]+(?:\.[\w-]+)+", raw)
    email = email_match.group(0) if email_match else ""
    if email:
        return {"email": email, "label": email, "visible": True}
    for pattern in (
        r"(?:logged\s+in\s+as|signed\s+in\s+as|account)\s*[:=-]?\s*([^\n;]+)",
        r"(?:usuario|cuenta)\s*[:=-]?\s*([^\n;]+)",
    ):
        match = re.search(pattern, raw, re.IGNORECASE)
        if match:
            label = re.sub(r"\s+", " ", match.group(1)).strip(" .;:-")
            if label and "unknown" not in label.lower() and "not logged" not in label.lower():
                return {"email": "", "label": label[:140], "visible": True}
    return {"email": "", "label": "", "visible": False}


CODEX_AUTH_NEGATIVE_PARTS = (
    "not logged",
    "logged out",
    "auth unknown",
    "unknown",
    "login required",
    "missing",
    "unauthorized",
    "401",
    "error:",
    "failed",
)
CODEX_AUTH_POSITIVE_PARTS = ("logged in", "signed in", "authenticated")
CODEX_AUTH_POSITIVE_MARKS = ("\u2713", "\u2714", "✅")


def codex_auth_line_is_logged_in(line):
    """Return True only for a positive OpenAI Codex auth signal."""
    text = str(line or "").strip()
    lower = text.lower()
    if not text or "openai codex" not in lower:
        return False
    if any(part in lower for part in CODEX_AUTH_NEGATIVE_PARTS):
        return False
    return any(part in lower for part in CODEX_AUTH_POSITIVE_PARTS) or any(mark in text for mark in CODEX_AUTH_POSITIVE_MARKS)


def codex_auth_line_from_status(output):
    lines = [line.strip() for line in str(output or "").splitlines() if line.strip()]
    explicit = next((line for line in lines if "openai codex" in line.lower() and "provider:" not in line.lower()), "")
    if explicit:
        return explicit
    provider_line = next((line for line in lines if "provider:" in line.lower() and "openai codex" in line.lower()), "")
    return provider_line if codex_auth_line_is_logged_in(provider_line) else ""


def codex_credential_health(config):
    """Detect a revoked OAuth session that Hermes status still calls logged in.

    Hermes' status command currently treats the presence of ``auth.json`` as a
    positive login signal. The credential pool, however, records the real 401
    returned by OpenAI. Only permanent OAuth failures force reconnection here;
    temporary 429 usage limits remain connected.
    """
    home = Path(str(getattr(config, "hermes_home", "") or DATA_DIR / "hermes-home")).expanduser()
    if not home.is_absolute():
        home = ROOT_DIR / home
    auth_path = home / "auth.json"
    try:
        payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {"state": "unknown", "reauth_required": False, "auth_path_exists": auth_path.exists()}

    pool = (payload.get("credential_pool") or {}).get("openai-codex") or []
    if not isinstance(pool, list):
        pool = []
    permanent_patterns = (
        "token_invalidated",
        "authentication token has been invalidated",
        "invalid_grant",
        "refresh token is invalid",
        "refresh token has been revoked",
        "oauth token has been revoked",
    )
    for entry in pool:
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("last_status") or "").strip().lower()
        message = str(entry.get("last_error_message") or "").strip().lower()
        try:
            error_code = int(entry.get("last_error_code") or 0)
        except (TypeError, ValueError):
            error_code = 0
        permanently_invalid = any(pattern in message for pattern in permanent_patterns)
        permanently_invalid = permanently_invalid or (error_code == 401 and status in {"dead", "invalid", "revoked"})
        if permanently_invalid:
            return {
                "state": "reauth_required",
                "reauth_required": True,
                "auth_path_exists": True,
                "last_error_code": error_code or 401,
            }
    return {"state": "stored", "reauth_required": False, "auth_path_exists": True}


def hermes_codex_session_status(config, timeout=None):
    hermes_cli = shutil.which(getattr(config, "hermes_cli", "hermes") or "hermes")
    if not hermes_cli:
        return {"ready": False, "detail": "Hermes not installed", "identity": extract_codex_account_identity("")}
    if timeout is None:
        status_timeout = max(8, min(45, int(getattr(config, "hermes_status_timeout_seconds", 20) or 20)))
    else:
        try:
            status_timeout = max(1, min(45, int(timeout)))
        except (TypeError, ValueError):
            status_timeout = 5
    try:
        completed = subprocess.run(
            [hermes_cli, "status"],
            cwd=str(ROOT_DIR),
            env=hermes_environment(config),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=status_timeout,
            check=False,
        )
    except Exception as exc:
        detail = f"Could not check Hermes status: {exc}"
        return {"ready": False, "detail": detail, "identity": extract_codex_account_identity(detail)}
    output = (completed.stdout or "") + "\n" + (completed.stderr or "")
    provider_line = next((line.strip() for line in output.splitlines() if "Provider:" in line), "")
    codex_line = codex_auth_line_from_status(output)
    provider_ok = "codex" in provider_line.lower() or "openai codex" in provider_line.lower()
    codex_ok = codex_auth_line_is_logged_in(codex_line)
    credential_health = codex_credential_health(config)
    reauth_required = bool(credential_health.get("reauth_required"))
    explicit_negative = any(part in output.lower() for part in CODEX_AUTH_NEGATIVE_PARTS)
    # Hermes/Codex wording changes over time. A successful ``hermes status``
    # for the Codex provider plus a stored, non-revoked credential is a valid
    # auth signal even when the output no longer contains the literal phrase
    # "logged in". Explicit negative markers and revoked OAuth still win.
    if (
        not codex_ok
        and completed.returncode == 0
        and provider_ok
        and credential_health.get("state") == "stored"
        and not explicit_negative
    ):
        codex_ok = True
    if reauth_required:
        codex_ok = False
    auth_detail = "OpenAI Codex session invalidated; reconnect required" if reauth_required else (codex_line or "OpenAI Codex auth unknown")
    detail = f"{provider_line or 'Provider unknown'}; {auth_detail}"
    return {
        "ready": provider_ok and codex_ok,
        "authenticated": codex_ok,
        "provider_ready": provider_ok and codex_ok,
        "reauth_required": reauth_required,
        "auth_state": credential_health.get("state", "unknown"),
        "detail": detail,
        "identity": extract_codex_account_identity(output or detail),
        "returncode": completed.returncode,
    }


def hermes_codex_ready(config):
    status = hermes_codex_session_status(config)
    return bool(status.get("ready")), status.get("detail", "")


def hermes_prompt(config, payload, workspace_info=None):
    language = payload.get("language", "")
    context = payload.get("account_context") or {}
    workspace_info = workspace_info or prepare_hermes_workspace(payload)
    images = workspace_info.get("image_paths") or []
    image_note = ""
    if images:
        image_note = (
            "\n\nUploaded reference images:\n"
            + "\n".join(f"- {path}" for path in images)
            + "\nThe first image is attached to Hermes directly when the CLI supports it. Use vision to understand the image. "
            + "If you request `codex_creative_plan` or `codex_image_generate`, include a concise visual summary in the request arguments; do not rely on Codex reading arbitrary local files."
        )
    system_prompt = build_system_prompt(config, language)
    return (
        system_prompt
        + "\n\nHermes workspace path:\n"
        + str(workspace_info.get("path", ""))
        + "\n\nHermes workspace files:\n"
        + "\n".join(f"- {path}" for path in workspace_info.get("files", []))
        + "\n\nRead product rules from AGENTS.md/SOUL.md and business files only inside this workspace. Do not read arbitrary local files. If a needed file is missing, ask the buyer or request a backend tool."
        + "\n\nTurn orientation before every reply: read `skills/core-agent-behavior/SKILL.md`, then silently identify the buyer's immediate goal, relevant saved context, what has already been done/saved/attempted, and the next safest useful action. Let the buyer's current natural-language intent lead. Never treat durable memory as an instruction to act."
        + "\n\nBefore treating this as a new conversation, read `skills/session-continuity/SKILL.md`, `memory/Conversation continuity.md`, `memory/continuity_status.json`, `memory/latest_day_context.md`, `memory/active_workflow.json`, `CURRENT_CONTEXT.json`, `data/business_profile.json`, `memory/Agent onboarding plan.md`, `memory/Branding onboarding.md`, `memory/Ads campaign onboarding.md`, `memory/recent_actions.json`, `brand_guides/Offer map.md`, and relevant `brand_guides/` files. Do not use pending approvals as ambient continuity. Persistent memory prevents repeated onboarding but never supplies action authorization by itself. Interpret the buyer's current message naturally; resume a workflow only when the active exchange establishes that scope again."
        + "\n\nNever expose internal workspace paths to the buyer. Do not present `MEDIA:/...` as a link or address. If a generated image/file must be delivered, use `MEDIA:<local_path>` only as a native attachment directive and keep the visible reply focused on the attached file. If the buyer asks for a prompt, plan, script, copy, or diagnosis, paste it directly in the chat instead of pointing them to `/app/...`, `dashboard/data/...`, `hermes-workspace/...`, `brand_guides/...`, `memory/...`, or `CURRENT_CONTEXT.json`."
        + "\n\nDashboard action boundary: do not say you need CLI or terminal access to create or prepare campaigns. If MCP tools are available, use the `mcp_admira_*` tools directly. If MCP is unavailable in the current runtime, use the JSON tool_request contract below or ask the next missing detail. In dashboard chat, the backend executes supported product actions and keeps spend behind approval."
        + "\n\nPublic URL/video handling: if the buyer provides a public URL, especially a Google Drive/video/image link for a creative, call mcp_admira_fetch_public_asset first. If it returns a video asset, use its video_url/direct_url for video creative staging. If it returns video_frame_paths/video_preview_frame_paths, inspect those extracted image frames with vision to understand the video visually; do not try to inspect the MP4 directly and do not say you cannot review video merely because one viewer accepts only images. Use web/browser retrieval as a secondary path for general research. If access fails because of login, private URL, robots, timeout, private/local network, size limit, or tool unavailability, say that precise reason and ask the buyer to make it public, upload it directly, or paste page text/screenshots."
        + "\n\nCurrent account context JSON:\n"
        + json.dumps(context, ensure_ascii=False)
        + image_note
        + "\n\nDo not expect full conversation history here. Hermes session memory helps continuity, but durable workspace memory is the fallback after cleanup/update/restart. Return normal helpful text for explanations. If the user asks for a product action, return this JSON contract only:\n"
        + '{"assistant_message":"short user-facing reply","tool_request":{"tool":"tool_name","arguments":{}}}\n'
        + "Approvals must target one exact pending decision, but approval IDs are internal routing metadata and must never appear in the buyer-facing reply. After staging, ask the buyer to reply `aprobado` or use the buttons; internally use the exact ID returned by the tool. If an older intended decision is genuinely unclear, show human-readable choices without IDs. Never invent IDs.\n"
        + "For campaign activation/resume that can spend real money, ask for the short exact phrase `Sí, activar` without appending an ID. Do not say the dashboard Approvals UI is required; it is only a backup.\n\n"
        + f"User message:\n{str(payload.get('message') or '')[:5000]}"
    )


def library_chat(config, payload):
    from run_agent import AIAgent

    workspace_info = prepare_hermes_workspace(payload)
    brain = hermes_brain_settings(config)
    inference_policy = inference_runtime_policy(brain)
    kwargs = {
        "quiet_mode": True,
        "platform": payload.get("channel") or "dashboard",
        "max_iterations": min(
            inference_policy["max_turns"],
            max(1, int(getattr(config, "hermes_max_iterations", 12) or 12)),
        ),
    }
    if brain.get("provider"):
        kwargs["provider"] = brain["provider"]
    if brain.get("base_url"):
        kwargs["base_url"] = brain["base_url"]
    if brain.get("api_key"):
        kwargs["api_key"] = brain["api_key"]
    if brain.get("model"):
        kwargs["model"] = brain["model"]
    enabled = controlled_hermes_toolsets(split_csv(getattr(config, "hermes_enabled_toolsets", "")))
    disabled = split_csv(getattr(config, "hermes_disabled_toolsets", ""))
    if "skills" not in disabled:
        disabled.append("skills")
    if inference_policy["disable_delegation"] and "delegation" not in disabled:
        disabled.append("delegation")
    if enabled:
        kwargs["enabled_toolsets"] = enabled
    if disabled:
        kwargs["disabled_toolsets"] = disabled

    env = hermes_environment(config)
    old_home = os.environ.get("HERMES_HOME")
    old_cwd = os.getcwd()
    if "HERMES_HOME" in env:
        os.environ["HERMES_HOME"] = env["HERMES_HOME"]
    try:
        os.chdir(workspace_info["path"])
        agent = AIAgent(**kwargs)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = agent.run_conversation(
                user_message=str(payload.get("message") or "")[:5000],
                system_message=hermes_prompt(config, payload, workspace_info),
            )
        if isinstance(result, dict) or hasattr(result, "final_response") or hasattr(result, "messages"):
            # Direct Python-library conversations (used by Telegram and the
            # real-conversation canary) do not pass through GatewayRunner's
            # outbound guards. Apply the same evidence check here so a model
            # cannot turn a failed/cleaned-up Meta mutation into "created".
            guarded_result = result if isinstance(result, dict) else {
                "final_response": str(
                    getattr(result, "final_response", "")
                    or getattr(result, "response", "")
                    or result
                ),
                "messages": getattr(result, "messages", []) or [],
            }
            try:
                from admira_hermes_runtime_patch import (
                    _guard_unconfirmed_campaign_claim,
                    _guard_unconfirmed_campaign_edit_claim,
                )
                guarded_result = _guard_unconfirmed_campaign_claim(guarded_result)
                guarded_result = _guard_unconfirmed_campaign_edit_claim(guarded_result)
            except Exception:
                pass
            return str(guarded_result.get("final_response") or guarded_result.get("response") or "").strip()
        return str(result or "").strip()
    finally:
        os.chdir(old_cwd)
        if old_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = old_home


def cli_chat(config, payload):
    workspace_info = prepare_hermes_workspace(payload)
    hermes_files = write_cli_hermes_config(config, workspace_info, payload)
    query = hermes_user_query(payload, workspace_info)
    images = workspace_info.get("image_paths") or []
    brain = hermes_brain_settings(config)
    hermes_cli = getattr(config, "hermes_cli", "hermes") or "hermes"
    source = hermes_session_source(payload)
    session_name = hermes_session_name(payload)

    def build_command(use_continue):
        command = [
            hermes_cli,
            "chat",
            "--quiet",
            "--source",
            source,
            "--max-turns",
            str(max(1, int(getattr(config, "hermes_max_iterations", 12) or 12))),
            "-q",
            query,
        ]
        if use_continue and session_name:
            command.extend(["--continue", session_name])
        provider = hermes_cli_provider(brain)
        if provider:
            command.extend(["--provider", provider])
        if brain.get("model"):
            command.extend(["--model", brain["model"]])
        enabled = ",".join(cli_toolsets(config, payload))
        if enabled:
            command.extend(["--toolsets", enabled])
        if images:
            command.extend(["--image", images[0]])
        return command

    def run_command(command):
        env = hermes_environment(config)
        env["HERMES_HOME"] = hermes_files["hermes_home"]
        return subprocess.run(
            command,
            cwd=workspace_info["path"],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(30, int(getattr(config, "hermes_response_timeout_seconds", getattr(config, "hermes_timeout_seconds", 300)) or 300)),
            check=False,
        )

    command = build_command(use_continue=bool(session_name))
    completed = run_command(command)
    if completed.returncode != 0 and session_name and "No session found matching" in ((completed.stderr or "") + (completed.stdout or "")):
        completed = run_command(build_command(use_continue=False))
        if completed.returncode == 0:
            name_latest_session(config, source, session_name)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "Hermes command failed").strip()[:1000])
    return (completed.stdout or "").strip()


def name_latest_session(config, source, title):
    if not title:
        return False
    hermes_cli = getattr(config, "hermes_cli", "hermes") or "hermes"
    env = hermes_environment(config)
    try:
        listed = subprocess.run(
            [hermes_cli, "sessions", "list", "--source", source, "--limit", "1"],
            cwd=str(ROOT_DIR),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
    except Exception:
        return False
    if listed.returncode != 0:
        return False
    match = re.search(r"\b(\d{8}_\d{6}_[0-9a-f]+)\b", listed.stdout or "")
    if not match:
        return False
    session_id = match.group(1)
    try:
        renamed = subprocess.run(
            [hermes_cli, "sessions", "rename", session_id, title],
            cwd=str(ROOT_DIR),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
    except Exception:
        return False
    return renamed.returncode == 0


def pending_campaign_edit_snapshot():
    """Return non-secret pending edit metadata for CLI outcome reconciliation."""
    path = DATA_DIR / "pending_approvals.json"
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    result = {}
    for item in values if isinstance(values, list) else []:
        if not isinstance(item, dict) or item.get("type") != "campaign_edit" or item.get("status") != "pending":
            continue
        approval_id = str(item.get("id") or "").strip()
        if approval_id:
            result[approval_id] = item
    return result


def chat(config, payload):
    language = payload.get("language", "es")
    try:
        brain = hermes_brain_settings(config)
        if getattr(config, "hermes_require_codex_auth", True) or brain.get("requires_codex_auth"):
            ready, detail = hermes_brain_ready(config)
            if not ready:
                return {
                    "ok": False,
                    "provider": "hermes",
                    "fallback": True,
                    "reply": setup_reply(language),
                    "error": f"Hermes brain is not ready: {detail}",
                }
        elif not brain.get("requires_codex_auth"):
            ready, detail = hermes_brain_ready(config)
            if not ready:
                return {
                    "ok": False,
                    "provider": "hermes",
                    "fallback": True,
                    "reply": setup_reply(language),
                    "error": f"Hermes brain is not ready: {detail}",
                }
        pending_edits_before = pending_campaign_edit_snapshot()
        images = safe_image_paths(payload)
        used_cli = False
        if images:
            used_cli = True
            reply = cli_chat(config, payload)
        elif hermes_session_name(payload):
            used_cli = True
            reply = cli_chat(config, payload)
        elif getattr(config, "hermes_use_python_library", True):
            try:
                reply = library_chat(config, payload)
            except (ImportError, ModuleNotFoundError):
                used_cli = True
                reply = cli_chat(config, payload)
            if not str(reply or "").strip():
                used_cli = True
                reply = cli_chat(config, payload)
        else:
            used_cli = True
            reply = cli_chat(config, payload)
        try:
            from admira_hermes_runtime_patch import (
                normalize_telegram_outbound_text,
                guard_unverified_campaign_edit_text,
                _admira_campaign_edit_requested,
            )
            reply, _metadata = normalize_telegram_outbound_text(reply, language)
            # The CLI fallback does not expose structured tool evidence. Only
            # apply its conservative mutation-claim guard when the buyer's
            # latest turn actually asks for an edit. A status question can
            # naturally contain words such as "campaign" and "paused" and
            # must remain a normal read-only conversation.
            edit_requested = _admira_campaign_edit_requested([
                {"role": "user", "content": str(payload.get("message") or "")}
            ])
            if used_cli and edit_requested:
                pending_edits_after = pending_campaign_edit_snapshot()
                new_pending = [
                    item for approval_id, item in pending_edits_after.items()
                    if approval_id not in pending_edits_before
                ]
                new_pending.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
                reply = guard_unverified_campaign_edit_text(
                    reply,
                    language,
                    pending_edit=(new_pending[0] if new_pending else None),
                )
        except Exception:
            pass
        if not str(reply or "").strip():
            return {
                "ok": False,
                "provider": "hermes",
                "fallback": True,
                "reply": "",
                "error": "Hermes returned an empty reply",
            }
        return {"ok": True, "provider": "hermes", "brain_provider": brain.get("brain"), "model": brain.get("model") or "configured-in-hermes", "reply": reply}
    except (ImportError, ModuleNotFoundError) as exc:
        return {"ok": False, "provider": "hermes", "fallback": True, "reply": setup_reply(language), "error": f"Hermes Python library is not installed: {exc}"}
    except FileNotFoundError as exc:
        return {"ok": False, "provider": "hermes", "fallback": True, "reply": setup_reply(language), "error": f"Hermes CLI is not installed: {exc}"}
    except Exception as exc:
        error_text = str(exc)
        if model_usage_limit_error(error_text):
            return {
                "ok": False,
                "provider": "hermes",
                "fallback": True,
                "error_type": "model_usage_limit",
                "retry_after_hint": model_usage_limit_retry_hint(error_text),
                "reply": model_usage_limit_reply(language, error_text),
                "error": error_text,
            }
        return {"ok": False, "provider": "hermes", "fallback": True, "reply": runtime_failure_reply(language), "error": error_text}
