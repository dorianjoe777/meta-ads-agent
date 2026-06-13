#!/usr/bin/env python3
"""Configuration helpers for Admira IA."""
import os
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"


def load_dotenv(path=ENV_FILE):
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
            os.environ[key] = value


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
    social_cli: str
    ad_account_id: str
    meta_access_token: str
    meta_graph_api_version: str
    notify_channel: str
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
    agent_brain_provider: str = "openai_codex"
    dashboard_password_hash: str = ""
    license_public_key: str = ""
    hermes_cli: str = "hermes"
    hermes_home: str = ""
    hermes_model: str = ""
    hermes_timeout_seconds: int = 300
    hermes_status_timeout_seconds: int = 20
    hermes_response_timeout_seconds: int = 300
    hermes_max_iterations: int = 12
    hermes_enabled_toolsets: str = "memory,skills,session_search,vision,file,web,browser"
    hermes_disabled_toolsets: str = "terminal,code_execution,image_gen"
    hermes_use_python_library: bool = True
    hermes_require_codex_auth: bool = True
    meta_access_token_kind: str = ""
    meta_access_token_saved_at: str = ""

    @property
    def live(self):
        return self.mode == "live"

    @property
    def creative_live(self):
        return self.creative_image_mode == "live"


def load_config():
    load_dotenv()
    mode = os.environ.get("META_ADS_AGENT_MODE", "dry-run").strip().lower()
    if mode not in {"dry-run", "live"}:
        mode = "dry-run"
    legacy_chat_provider = normalize_chat_provider(env_first("AGENT_CHAT_PROVIDER", default="hermes"))
    base_url = env_first("AGENT_CHAT_BASE_URL", "MINIMAX_BASE_URL", default="https://api.minimax.io/v1").rstrip("/")
    brain_provider = normalize_agent_brain_provider(
        env_first("AGENT_BRAIN_PROVIDER", default=""),
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
        autonomy_mode=os.environ.get("META_AUTONOMY_MODE", "supervised").strip().lower() if os.environ.get("META_AUTONOMY_MODE", "supervised").strip().lower() in {"supervised", "autopilot"} else "supervised",
        auto_budget_change_pct=env_float("META_AUTO_BUDGET_CHANGE_PCT", 10),
        auto_budget_change_amount=env_float("META_AUTO_BUDGET_CHANGE_AMOUNT", 25),
        auto_pause_max_spend=env_float("META_AUTO_PAUSE_MAX_SPEND", 100),
        require_approval_for_resume=env_bool("META_REQUIRE_APPROVAL_FOR_RESUME", True),
        require_approval_for_new_campaigns=env_bool("META_REQUIRE_APPROVAL_FOR_NEW_CAMPAIGNS", True),
        require_approval_for_creatives=env_bool("META_REQUIRE_APPROVAL_FOR_CREATIVES", True),
        auto_pause_enabled=env_bool("META_AUTO_PAUSE_ENABLED", True),
        zero_conversion_spend=env_float("META_AUTO_PAUSE_ZERO_CONVERSION_SPEND", 50),
        high_cpa_multiplier=env_float("META_AUTO_PAUSE_HIGH_CPA_MULTIPLIER", 3),
        meta_connector=os.environ.get("META_CONNECTOR", "social_cli").strip().lower(),
        social_cli=os.environ.get("SOCIAL_CLI", "social"),
        ad_account_id=os.environ.get("META_AD_ACCOUNT_ID", ""),
        meta_access_token=os.environ.get("META_ACCESS_TOKEN", ""),
        meta_access_token_kind=os.environ.get("META_ACCESS_TOKEN_KIND", ""),
        meta_access_token_saved_at=os.environ.get("META_ACCESS_TOKEN_SAVED_AT", ""),
        meta_graph_api_version=os.environ.get("META_GRAPH_API_VERSION", "v24.0"),
        notify_channel=os.environ.get("META_NOTIFY_CHANNEL", "dashboard").strip().lower(),
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
        agent_chat_model=env_first("AGENT_CHAT_MODEL", "MINIMAX_MODEL", default="MiniMax-M3"),
        agent_chat_temperature=env_float("AGENT_CHAT_TEMPERATURE", 0.65),
        agent_profile_dir=os.environ.get("AGENT_PROFILE_DIR", "agent"),
        codex_creative_enabled=env_bool("CODEX_CREATIVE_ENABLED", True),
        codex_cli=os.environ.get("CODEX_CLI", "codex"),
        codex_creative_model=os.environ.get("CODEX_CREATIVE_MODEL", ""),
        agent_brain_provider=brain_provider,
        dashboard_password_hash=os.environ.get("DASHBOARD_PASSWORD_HASH", ""),
        license_public_key=os.environ.get("LICENSE_PUBLIC_KEY", ""),
        hermes_cli=os.environ.get("HERMES_CLI", "hermes"),
        hermes_home=os.environ.get("HERMES_HOME", ""),
        hermes_model=os.environ.get("HERMES_MODEL", ""),
        hermes_timeout_seconds=env_int("HERMES_TIMEOUT_SECONDS", 300),
        hermes_status_timeout_seconds=env_int("HERMES_STATUS_TIMEOUT_SECONDS", 20),
        hermes_response_timeout_seconds=env_int("HERMES_RESPONSE_TIMEOUT_SECONDS", env_int("HERMES_TIMEOUT_SECONDS", 300)),
        hermes_max_iterations=env_int("HERMES_MAX_ITERATIONS", 12),
        hermes_enabled_toolsets=os.environ.get("HERMES_ENABLED_TOOLSETS", "memory,skills,session_search,vision,file,web,browser"),
        hermes_disabled_toolsets=os.environ.get("HERMES_DISABLED_TOOLSETS", "terminal,code_execution,image_gen"),
        hermes_use_python_library=env_bool("HERMES_USE_PYTHON_LIBRARY", True),
        hermes_require_codex_auth=env_bool("HERMES_REQUIRE_CODEX_AUTH", True),
    )
