#!/usr/bin/env python3
"""Configuration helpers for Admira IA."""
import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from communication_style import ad_experience_from_environment, communication_style_from_environment


ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"
DASHBOARD_IDENTITY_FILE = ROOT_DIR / "dashboard" / "data" / "dashboard_identity.json"
DEFAULT_HERMES_CODEX_MODEL = "gpt-5.4-mini"
DEFAULT_CODEX_IMAGE_SOURCE = "main_chatgpt"
DEFAULT_NVIDIA_NIM_MODEL = "minimaxai/minimax-m3"
LEGACY_NVIDIA_NIM_DEFAULT_MODELS = frozenset({"z-ai/glm-5.2"})
AGENT_MODEL_CONNECTION_SPECS = {
    "openai_api": {
        "env_prefix": "ADMIRA_OPENAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "api": "openai-chat-completions",
    },
    "minimax": {
        "env_prefix": "ADMIRA_MINIMAX",
        "base_url": "https://api.minimax.io/v1",
        "model": "MiniMax-M3",
        "api": "openai-chat-completions",
    },
    "nvidia_nim": {
        "env_prefix": "ADMIRA_NVIDIA",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": DEFAULT_NVIDIA_NIM_MODEL,
        "api": "openai-chat-completions",
    },
    "custom_api": {
        "env_prefix": "ADMIRA_CUSTOM",
        "base_url": "",
        "model": "",
        "api": "openai-chat-completions",
    },
}

# The account catalog is authoritative, but the provider does not guarantee a
# stable ordering. Keep a small, buyer-safe preference order so new installs
# do not silently default to the heaviest model. Luna is the preferred GPT-5.6
# option when it is actually available; Go accounts commonly expose the
# smaller GPT-5.4 mini model instead.
_HERMES_DEFAULT_MODEL_PREFERENCE = (
    "gpt-5.6-luna",
    "gpt-5.6-mini",
    "gpt-5.4-mini",
    "gpt-5.6-terra",
    "gpt-5.6-sol",
    "gpt-5.5-mini",
    "gpt-5.5",
    "gpt-5.4",
)
_SMALL_MODEL_MARKERS = ("mini", "small", "lite", "nano", "flash", "haiku")


def normalize_hermes_model(value):
    model = str(value or "").strip()
    if not model or model.lower() in {"auto", "recommended", "recomendado", "default"}:
        return DEFAULT_HERMES_CODEX_MODEL
    return model


def normalize_nvidia_model(value, user_selected=False):
    """Return the effective NVIDIA chat model without hiding explicit choices.

    Older releases used GLM 5.2 as the implicit NIM default.  MiniMax M3 is
    now the product default because it is the first model proven responsive on
    the hosted catalog used by fresh installs.  A buyer who explicitly chose
    another model keeps that choice; untouched legacy profiles are migrated at
    runtime and by the dashboard's one-time persistence hook.
    """
    model = str(value or "").strip()
    if not model:
        return DEFAULT_NVIDIA_NIM_MODEL
    if not user_selected and model.lower() in LEGACY_NVIDIA_NIM_DEFAULT_MODELS:
        return DEFAULT_NVIDIA_NIM_MODEL
    return model


def preferred_hermes_model(models):
    """Choose the lightest sensible model from a real account catalog.

    The returned value is always one of ``models`` (after whitespace cleanup),
    so this helper never invents a model an account did not advertise.
    """
    cleaned = []
    seen = set()
    for item in models or []:
        model = str(item or "").strip()
        key = model.lower()
        if model and key not in seen:
            cleaned.append(model)
            seen.add(key)
    if not cleaned:
        return DEFAULT_HERMES_CODEX_MODEL

    by_key = {model.lower(): model for model in cleaned}
    for preferred in _HERMES_DEFAULT_MODEL_PREFERENCE:
        if preferred in by_key:
            return by_key[preferred]

    # Graceful fallback for future provider names (for example, a new
    # ``gpt-5.7-mini``) while still favoring explicitly lightweight models.
    small = [model for model in cleaned if any(marker in model.lower() for marker in _SMALL_MODEL_MARKERS)]
    if small:
        return sorted(small, key=lambda value: (len(value), value.lower()))[0]
    return cleaned[0]


def load_dotenv(path=None):
    """Load persisted settings without clobbering explicit process settings.

    Docker Compose injects the installation's environment (including the
    cloud/LAN access mode) while the named runtime volume contains defaults
    from an older image.  The persisted file should fill in missing values,
    not override explicit environment variables on every dashboard restart.

    Compose commonly exports optional settings as *empty* strings.  Those are
    placeholders, not an intentional override: treating them as authoritative
    would make a saved Telegram/model connection disappear every time a
    container is recreated.  A non-empty process value remains authoritative;
    a blank one is filled from the persistent runtime file.
    """
    path = Path(path or ENV_FILE)
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key not in os.environ or not str(os.environ.get(key) or "").strip():
                os.environ[key] = value


def recover_dashboard_identity_from_data(path=None):
    if os.environ.get("DASHBOARD_PASSWORD_HASH") or os.environ.get("DASHBOARD_PASSWORD") or os.environ.get("DASHBOARD_TOKEN"):
        return False
    path = Path(path or DASHBOARD_IDENTITY_FILE)
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    password_hash = str(payload.get("dashboard_password_hash") or "").strip()
    if not password_hash.startswith("pbkdf2_sha256$"):
        return False
    os.environ["DASHBOARD_PASSWORD_HASH"] = password_hash
    return True


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


def env_first(*names, default=""):
    for name in names:
        value = os.environ.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def normalize_chat_provider(value):
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "hermes": "hermes",
        "openai": "openai_compatible",
        "openai_api": "openai_compatible",
        "openai_compatible": "openai_compatible",
        "openai_compat": "openai_compatible",
        "compatible": "openai_compatible",
        "custom": "openai_compatible",
        "custom_api": "openai_compatible",
        "minimax": "minimax",
        "minimax_m3": "minimax",
        "nvidia": "nvidia_nim",
        "nvidia_nim": "nvidia_nim",
        "nvidia_api": "nvidia_nim",
    }
    return aliases.get(raw, "hermes")


def normalize_agent_brain_provider(value, legacy_chat_provider="hermes", base_url=""):
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "hermes": "openai_codex",
        "chatgpt": "openai_codex",
        "chatgpt_subscription": "openai_codex",
        "codex": "openai_codex",
        "openai_codex": "openai_codex",
        "openai": "openai_api",
        "openai_api": "openai_api",
        "minimax": "minimax",
        "minimax_m3": "minimax",
        "nvidia": "nvidia_nim",
        "nvidia_api": "nvidia_nim",
        "nvidia_nim": "nvidia_nim",
        "openai_compatible": "custom_api",
        "openai_compat": "custom_api",
        "compatible": "custom_api",
        "custom": "custom_api",
        "custom_api": "custom_api",
    }
    if raw in aliases:
        return aliases[raw]
    legacy = normalize_chat_provider(legacy_chat_provider)
    if legacy == "minimax":
        return "minimax"
    if legacy in {"openai_compatible", "openai"}:
        return "openai_api" if "api.openai.com" in str(base_url or "") else "custom_api"
    return "openai_codex"


def agent_model_connection_env_keys(provider):
    """Return the private env keys owned by one saved API connection."""
    normalized = normalize_agent_brain_provider(provider)
    spec = AGENT_MODEL_CONNECTION_SPECS.get(normalized)
    if not spec:
        return {}
    prefix = spec["env_prefix"]
    return {
        "api_key": f"{prefix}_API_KEY",
        "base_url": f"{prefix}_BASE_URL",
        "model": f"{prefix}_MODEL",
        "api": f"{prefix}_API",
    }


def agent_model_connections(config=None, include_secrets=False):
    """Return every independently saved API brain without exposing keys by default.

    Older installs only have the generic ``AGENT_CHAT_*`` fields. When that
    connection is the active brain, treat it as the matching saved profile so
    an update migrates it without asking the buyer to paste the key again.
    """
    active_provider = normalize_agent_brain_provider(
        getattr(config, "agent_brain_provider", "") if config is not None else os.environ.get("AGENT_BRAIN_PROVIDER", ""),
        legacy_chat_provider=getattr(config, "agent_chat_provider", "hermes") if config is not None else os.environ.get("AGENT_CHAT_PROVIDER", "hermes"),
        base_url=getattr(config, "agent_chat_base_url", "") if config is not None else os.environ.get("AGENT_CHAT_BASE_URL", ""),
    )
    legacy_key = str(
        getattr(config, "agent_chat_api_key", "") if config is not None else os.environ.get("AGENT_CHAT_API_KEY", "")
    ).strip()
    legacy_base = str(
        getattr(config, "agent_chat_base_url", "") if config is not None else os.environ.get("AGENT_CHAT_BASE_URL", "")
    ).strip().rstrip("/")
    legacy_model = str(
        getattr(config, "agent_chat_model", "") if config is not None else os.environ.get("AGENT_CHAT_MODEL", "")
    ).strip()
    legacy_api = str(
        getattr(config, "agent_chat_api", "") if config is not None else os.environ.get("AGENT_CHAT_API", "")
    ).strip().lower()
    nvidia_model_user_selected = bool(
        getattr(config, "agent_nvidia_model_user_selected", False)
        if config is not None
        else env_bool("AGENT_NVIDIA_MODEL_USER_SELECTED", False)
    )
    legacy_provider = active_provider if active_provider in AGENT_MODEL_CONNECTION_SPECS else ""
    if legacy_key and not legacy_provider:
        legacy_url = legacy_base.lower()
        if "integrate.api.nvidia.com" in legacy_url:
            legacy_provider = "nvidia_nim"
        elif "minimax" in legacy_url:
            legacy_provider = "minimax"
        elif "api.openai.com" in legacy_url:
            legacy_provider = "openai_api"
        else:
            legacy_provider = "custom_api"
    result = {}
    for provider, spec in AGENT_MODEL_CONNECTION_SPECS.items():
        keys = agent_model_connection_env_keys(provider)
        saved_key = str(os.environ.get(keys["api_key"], "") or "").strip()
        saved_base = str(os.environ.get(keys["base_url"], "") or "").strip().rstrip("/")
        saved_model = str(os.environ.get(keys["model"], "") or "").strip()
        saved_api = str(os.environ.get(keys["api"], "") or "").strip().lower()
        if provider == legacy_provider:
            saved_key = saved_key or legacy_key
            saved_base = saved_base or legacy_base
            saved_model = saved_model or legacy_model
            saved_api = saved_api or legacy_api
        if provider == "nvidia_nim":
            saved_model = normalize_nvidia_model(saved_model, user_selected=nvidia_model_user_selected)
        base_url = saved_base or spec["base_url"]
        model = saved_model or spec["model"]
        api = saved_api or spec["api"]
        configured = bool(saved_key and base_url and model)
        connection = {
            "provider": provider,
            "configured": configured,
            "base_url": base_url,
            "model": model,
            "api": api,
            "api_key_set": bool(saved_key),
            "primary": provider == active_provider,
        }
        if include_secrets:
            connection["api_key"] = saved_key
        result[provider] = connection
    return result


def normalize_daily_time(value, default="08:00"):
    raw = str(value or "").strip()
    if not raw:
        return default
    if ":" in raw:
        hour_raw, minute_raw = raw.split(":", 1)
    else:
        hour_raw, minute_raw = raw, "00"
    try:
        hour = int(hour_raw)
        minute = int(minute_raw)
    except (TypeError, ValueError):
        return default
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return default
    return f"{hour:02d}:{minute:02d}"


def normalize_timezone(value, default="UTC"):
    raw = str(value or "").strip() or str(default or "UTC").strip() or "UTC"
    try:
        ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError):
        return str(default or "UTC").strip() or "UTC"
    return raw


def normalize_local_path(value, default):
    raw = str(value or "").strip()
    if not raw:
        raw = str(default)
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return str(path)


def normalize_codex_image_source(value):
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "": "main_chatgpt",
        "auto": "main_chatgpt",
        "main": "main_chatgpt",
        "main_chatgpt": "main_chatgpt",
        "primary": "main_chatgpt",
        "agent": "main_chatgpt",
        "same": "main_chatgpt",
        "shared": "main_chatgpt",
        "dedicated": "dedicated_chatgpt",
        "separate": "dedicated_chatgpt",
        "image": "dedicated_chatgpt",
        "image_only": "dedicated_chatgpt",
        "dedicated_chatgpt": "dedicated_chatgpt",
        "image_chatgpt": "dedicated_chatgpt",
    }
    return aliases.get(raw, DEFAULT_CODEX_IMAGE_SOURCE)


def agent_brain_uses_chatgpt_codex(config):
    """Return whether the primary agent brain is the buyer's ChatGPT/Codex login.

    Image 2 can use a separate ChatGPT/Codex home only when the text brain is
    an API/custom provider. When the primary brain is already ChatGPT/Codex,
    images must reuse that same authenticated session so reconnecting the main
    account does not leave Image 2 pointed at a stale image-only home.
    """
    brain = normalize_agent_brain_provider(
        getattr(config, "agent_brain_provider", ""),
        legacy_chat_provider=getattr(config, "agent_chat_provider", "hermes"),
        base_url=getattr(config, "agent_chat_base_url", ""),
    )
    return brain == "openai_codex"


def effective_codex_image_source(config):
    source = normalize_codex_image_source(getattr(config, "codex_image_source", ""))
    if agent_brain_uses_chatgpt_codex(config):
        return "main_chatgpt"
    return source


def default_codex_image_hermes_home():
    return str(ROOT_DIR / "dashboard" / "data" / "hermes-image-home")


def resolved_codex_image_hermes_home(config):
    source = effective_codex_image_source(config)
    if source != "dedicated_chatgpt":
        return ""
    configured = str(getattr(config, "codex_image_hermes_home", "") or "").strip()
    return normalize_local_path(configured, default_codex_image_hermes_home())


def image_codex_config(config):
    """Return a config clone that points Codex/Image at the selected ChatGPT session."""
    image_home = resolved_codex_image_hermes_home(config)
    if not image_home:
        return config
    updates = {
        "hermes_home": image_home,
        "agent_brain_provider": "openai_codex",
        "hermes_require_codex_auth": True,
        "hermes_model": normalize_hermes_model(
            getattr(config, "codex_image_hermes_model", "") or getattr(config, "hermes_model", "")
        ),
    }
    try:
        return replace(config, **updates)
    except TypeError:
        values = {}
        for name in dir(config):
            if name.startswith("_"):
                continue
            try:
                value = getattr(config, name)
            except Exception:
                continue
            if not callable(value):
                values[name] = value
        values.update(updates)
        return SimpleNamespace(**values)


@dataclass
class AgentConfig:
    mode: str
    dashboard_host: str
    dashboard_port: int
    dashboard_token: str
    dashboard_password: str
    dashboard_token_required: bool
    allow_public_dashboard: bool
    lan_access_enabled: bool
    live_actions_enabled: bool
    license_key: str
    license_buyer_email: str
    license_server_url: str
    license_device_id: str
    license_grace_hours: int
    license_required_for_live: bool
    license_signature_secret: str
    target_cpa: float
    approval_required_over_pct: float
    autonomy_mode: str
    auto_budget_change_pct: float
    auto_budget_change_amount: float
    auto_pause_max_spend: float
    require_approval_for_resume: bool
    require_approval_for_new_campaigns: bool
    require_approval_for_creatives: bool
    auto_pause_enabled: bool
    zero_conversion_spend: float
    high_cpa_multiplier: float
    meta_connector: str
    ad_account_id: str
    meta_access_token: str
    meta_graph_api_version: str
    notify_channel: str
    daily_brief_time: str
    daily_brief_timezone: str
    daily_social_content_enabled: bool
    daily_social_content_decision: str
    daily_social_content_time: str
    daily_social_content_posts_per_day: int
    daily_social_content_interval_days: int
    daily_social_content_formats: str
    daily_social_content_video_interval_days: int
    telegram_bot_token: str
    telegram_chat_id: str
    creative_refresh_enabled: bool
    creative_auto_generate_on_daily: bool
    creative_provider: str
    creative_image_mode: str
    gemini_api_key: str
    nano_banana_model: str
    creative_variants_per_campaign: int
    agent_chat_provider: str
    agent_chat_base_url: str
    agent_chat_api_key: str
    agent_chat_api: str
    agent_chat_model: str
    agent_chat_temperature: float
    agent_profile_dir: str
    codex_creative_enabled: bool
    codex_cli: str
    codex_creative_model: str
    codex_image_source: str = DEFAULT_CODEX_IMAGE_SOURCE
    codex_image_hermes_home: str = ""
    codex_image_hermes_model: str = DEFAULT_HERMES_CODEX_MODEL
    agent_brain_provider: str = "nvidia_nim"
    agent_nvidia_model_user_selected: bool = False
    dashboard_password_hash: str = ""
    license_public_key: str = ""
    hermes_cli: str = "hermes"
    hermes_home: str = ""
    hermes_model: str = DEFAULT_HERMES_CODEX_MODEL
    hermes_model_user_selected: bool = False
    hermes_timeout_seconds: int = 300
    hermes_status_timeout_seconds: int = 20
    hermes_response_timeout_seconds: int = 300
    hermes_max_iterations: int = 12
    hermes_enabled_toolsets: str = "memory,session_search,vision,file,web,browser"
    hermes_disabled_toolsets: str = "terminal,code_execution,image_gen,skills"
    hermes_use_python_library: bool = True
    hermes_require_codex_auth: bool = True
    meta_access_token_kind: str = ""
    meta_access_token_saved_at: str = ""
    meta_publishing_access_token: str = ""
    meta_publishing_token_saved_at: str = ""
    shopify_shop_domain: str = ""
    shopify_admin_token: str = ""
    shopify_api_version: str = "2026-04"
    communication_style: str = "simple"
    ad_experience_level: str = ""
    # OAuth is additive: old installer/test configuration can omit it.
    meta_oauth_broker_url: str = ""
    meta_oauth_connected_at: str = ""
    meta_oauth_expires_at: str = ""
    meta_oauth_user_id: str = ""

    @property
    def live(self):
        return self.mode == "live"

    @property
    def creative_live(self):
        return self.creative_image_mode == "live"


def load_config():
    load_dotenv()
    recover_dashboard_identity_from_data()
    mode = os.environ.get("META_ADS_AGENT_MODE", "dry-run").strip().lower()
    if mode not in {"dry-run", "live"}:
        mode = "dry-run"
    legacy_chat_provider = normalize_chat_provider(env_first("AGENT_CHAT_PROVIDER", default="hermes"))
    base_url = env_first("AGENT_CHAT_BASE_URL", "ADMIRA_NVIDIA_BASE_URL", default="https://integrate.api.nvidia.com/v1").rstrip("/")
    brain_provider = normalize_agent_brain_provider(
        env_first("AGENT_BRAIN_PROVIDER", default="nvidia_nim"),
        legacy_chat_provider=legacy_chat_provider,
        base_url=base_url,
    )
    return AgentConfig(
        mode=mode,
        dashboard_host=os.environ.get("DASHBOARD_HOST", "127.0.0.1"),
        dashboard_port=env_int("DASHBOARD_PORT", 7871),
        dashboard_token=os.environ.get("DASHBOARD_TOKEN", "") or os.environ.get("DASHBOARD_PASSWORD", ""),
        dashboard_password=os.environ.get("DASHBOARD_PASSWORD", "") or os.environ.get("DASHBOARD_TOKEN", ""),
        dashboard_token_required=env_bool("REQUIRE_DASHBOARD_TOKEN", True),
        allow_public_dashboard=env_bool("ALLOW_PUBLIC_DASHBOARD", False),
        lan_access_enabled=env_bool("LAN_ACCESS_ENABLED", False),
        live_actions_enabled=env_bool("LIVE_ACTIONS_ENABLED", False),
        license_key=os.environ.get("LICENSE_KEY", ""),
        license_buyer_email=os.environ.get("LICENSE_BUYER_EMAIL", ""),
        license_server_url=os.environ.get("LICENSE_SERVER_URL", "").rstrip("/"),
        license_device_id=os.environ.get("LICENSE_DEVICE_ID", ""),
        license_grace_hours=env_int("LICENSE_GRACE_HOURS", 72),
        license_required_for_live=env_bool("LICENSE_REQUIRED_FOR_LIVE", True),
        license_signature_secret=os.environ.get("LICENSE_SIGNATURE_SECRET", ""),
        target_cpa=env_float("META_TARGET_CPA", 50),
        approval_required_over_pct=env_float("META_APPROVAL_REQUIRED_OVER_PCT", 20),
        autonomy_mode="approval",
        auto_budget_change_pct=env_float("META_AUTO_BUDGET_CHANGE_PCT", 10),
        auto_budget_change_amount=env_float("META_AUTO_BUDGET_CHANGE_AMOUNT", 25),
        auto_pause_max_spend=env_float("META_AUTO_PAUSE_MAX_SPEND", 100),
        require_approval_for_resume=env_bool("META_REQUIRE_APPROVAL_FOR_RESUME", True),
        require_approval_for_new_campaigns=env_bool("META_REQUIRE_APPROVAL_FOR_NEW_CAMPAIGNS", True),
        require_approval_for_creatives=env_bool("META_REQUIRE_APPROVAL_FOR_CREATIVES", True),
        auto_pause_enabled=env_bool("META_AUTO_PAUSE_ENABLED", True),
        zero_conversion_spend=env_float("META_AUTO_PAUSE_ZERO_CONVERSION_SPEND", 50),
        high_cpa_multiplier=env_float("META_AUTO_PAUSE_HIGH_CPA_MULTIPLIER", 3),
        meta_connector="graph_api",
        ad_account_id=os.environ.get("META_AD_ACCOUNT_ID", ""),
        meta_access_token=os.environ.get("META_ACCESS_TOKEN", ""),
        meta_oauth_broker_url=env_first("META_OAUTH_BROKER_URL", default=(os.environ.get("LICENSE_SERVER_URL", "").rstrip("/") + "/api/meta-oauth") if os.environ.get("LICENSE_SERVER_URL", "").strip() else ""),
        meta_oauth_connected_at=os.environ.get("META_OAUTH_CONNECTED_AT", ""),
        meta_oauth_expires_at=os.environ.get("META_OAUTH_EXPIRES_AT", ""),
        meta_oauth_user_id=os.environ.get("META_OAUTH_USER_ID", ""),
        meta_access_token_kind=os.environ.get("META_ACCESS_TOKEN_KIND", ""),
        meta_access_token_saved_at=os.environ.get("META_ACCESS_TOKEN_SAVED_AT", ""),
        meta_publishing_access_token=os.environ.get("META_PUBLISHING_ACCESS_TOKEN", ""),
        meta_publishing_token_saved_at=os.environ.get("META_PUBLISHING_TOKEN_SAVED_AT", ""),
        meta_graph_api_version=os.environ.get("META_GRAPH_API_VERSION", "v24.0"),
        notify_channel=os.environ.get("META_NOTIFY_CHANNEL", "dashboard").strip().lower(),
        daily_brief_time=normalize_daily_time(env_first("DAILY_BRIEF_TIME", "META_DAILY_BRIEF_TIME", default="08:00")),
        daily_brief_timezone=normalize_timezone(env_first("DAILY_BRIEF_TIMEZONE", "TZ", default="UTC")),
        daily_social_content_enabled=env_bool("DAILY_SOCIAL_CONTENT_ENABLED", False),
        daily_social_content_decision=os.environ.get("DAILY_SOCIAL_CONTENT_DECISION", "").strip().lower(),
        daily_social_content_time=normalize_daily_time(env_first("DAILY_SOCIAL_CONTENT_TIME", default="10:00")),
        daily_social_content_posts_per_day=max(1, min(5, env_int("DAILY_SOCIAL_CONTENT_POSTS_PER_DAY", 1))),
        daily_social_content_interval_days=max(1, min(30, env_int("DAILY_SOCIAL_CONTENT_INTERVAL_DAYS", 1))),
        daily_social_content_formats=os.environ.get("DAILY_SOCIAL_CONTENT_FORMATS", "image").strip().lower() or "image",
        daily_social_content_video_interval_days=max(1, min(30, env_int("DAILY_SOCIAL_CONTENT_VIDEO_INTERVAL_DAYS", 7))),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        creative_refresh_enabled=env_bool("CREATIVE_REFRESH_ENABLED", True),
        creative_auto_generate_on_daily=env_bool("CREATIVE_AUTO_GENERATE_ON_DAILY", True),
        creative_provider=os.environ.get("CREATIVE_PROVIDER", "codex-image").strip().lower(),
        creative_image_mode=os.environ.get("CREATIVE_IMAGE_MODE", "codex-image").strip().lower(),
        gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
        nano_banana_model=os.environ.get("NANO_BANANA_MODEL", ""),
        creative_variants_per_campaign=env_int("CREATIVE_VARIANTS_PER_CAMPAIGN", 3),
        agent_chat_provider="hermes",
        agent_chat_base_url=base_url,
        agent_chat_api_key=env_first("AGENT_CHAT_API_KEY", "MINIMAX_API_KEY", default=""),
        agent_chat_api=env_first("AGENT_CHAT_API", "MINIMAX_API", default="openai-chat-completions").lower(),
        agent_chat_model=normalize_nvidia_model(
            env_first("AGENT_CHAT_MODEL", "ADMIRA_NVIDIA_MODEL", default=DEFAULT_NVIDIA_NIM_MODEL),
            user_selected=env_bool("AGENT_NVIDIA_MODEL_USER_SELECTED", False),
        ) if brain_provider == "nvidia_nim" else env_first("AGENT_CHAT_MODEL", "ADMIRA_NVIDIA_MODEL", default=""),
        agent_chat_temperature=env_float("AGENT_CHAT_TEMPERATURE", 0.65),
        agent_profile_dir=os.environ.get("AGENT_PROFILE_DIR", "agent"),
        codex_creative_enabled=env_bool("CODEX_CREATIVE_ENABLED", True),
        codex_cli=os.environ.get("CODEX_CLI", "codex"),
        codex_creative_model=os.environ.get("CODEX_CREATIVE_MODEL", ""),
        codex_image_source=normalize_codex_image_source(os.environ.get("CODEX_IMAGE_SOURCE", DEFAULT_CODEX_IMAGE_SOURCE)),
        codex_image_hermes_home=normalize_local_path(os.environ.get("CODEX_IMAGE_HERMES_HOME", ""), default_codex_image_hermes_home()) if os.environ.get("CODEX_IMAGE_HERMES_HOME") else "",
        codex_image_hermes_model=normalize_hermes_model(os.environ.get("CODEX_IMAGE_HERMES_MODEL", os.environ.get("HERMES_MODEL", ""))),
        agent_brain_provider=brain_provider,
        agent_nvidia_model_user_selected=env_bool("AGENT_NVIDIA_MODEL_USER_SELECTED", False),
        dashboard_password_hash=os.environ.get("DASHBOARD_PASSWORD_HASH", ""),
        license_public_key=os.environ.get("LICENSE_PUBLIC_KEY", ""),
        hermes_cli=os.environ.get("HERMES_CLI", "hermes"),
        hermes_home=normalize_local_path(os.environ.get("HERMES_HOME", ""), ROOT_DIR / "dashboard" / "data" / "hermes-home"),
        hermes_model=normalize_hermes_model(os.environ.get("HERMES_MODEL", "")),
        hermes_model_user_selected=env_bool("HERMES_MODEL_USER_SELECTED", False),
        hermes_timeout_seconds=env_int("HERMES_TIMEOUT_SECONDS", 300),
        hermes_status_timeout_seconds=env_int("HERMES_STATUS_TIMEOUT_SECONDS", 20),
        hermes_response_timeout_seconds=env_int("HERMES_RESPONSE_TIMEOUT_SECONDS", env_int("HERMES_TIMEOUT_SECONDS", 300)),
        hermes_max_iterations=env_int("HERMES_MAX_ITERATIONS", 12),
        hermes_enabled_toolsets=os.environ.get("HERMES_ENABLED_TOOLSETS", "memory,session_search,vision,file,web,browser"),
        hermes_disabled_toolsets=os.environ.get("HERMES_DISABLED_TOOLSETS", "terminal,code_execution,image_gen,skills"),
        hermes_use_python_library=env_bool("HERMES_USE_PYTHON_LIBRARY", True),
        hermes_require_codex_auth=env_bool("HERMES_REQUIRE_CODEX_AUTH", True),
        shopify_shop_domain=os.environ.get("SHOPIFY_SHOP_DOMAIN", "").strip().lower(),
        shopify_admin_token=os.environ.get("SHOPIFY_ADMIN_API_TOKEN", ""),
        shopify_api_version=os.environ.get("SHOPIFY_API_VERSION", "2026-04"),
        communication_style=communication_style_from_environment(),
        ad_experience_level=ad_experience_from_environment(),
    )
