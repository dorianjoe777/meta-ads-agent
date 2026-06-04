#!/usr/bin/env python3
"""Setup diagnostics for the self-hosted Meta Ads Agent."""
import shutil
import importlib.util
import subprocess
from pathlib import Path

from creative_refresh import INDEX_FILE as CREATIVE_INDEX_FILE
from creative_refresh import load_ad_config, read_json
from agent_runtime import load_agent_profile
from license import license_status as current_license_status
from meta_upload import UPLOAD_INDEX_FILE, recent_uploads
from product_config import ENV_FILE, ROOT_DIR, load_config
from security import is_public_bind, permission_detail
from telegram_agent import telegram_settings


DATA_DIR = ROOT_DIR / "dashboard" / "data"
OUTPUT_DIR = ROOT_DIR / "output"
AD_CONFIG_FILE = ROOT_DIR / "ad-config.json"
AD_CONFIG_EXAMPLE_FILE = ROOT_DIR / "ad-config.example.json"
SCRIPTS_DIR = ROOT_DIR / "scripts"
ACTIONS_FILE = DATA_DIR / "actions.json"
PENDING_FILE = DATA_DIR / "pending_approvals.json"
METRICS_FILE = DATA_DIR / "metrics.json"


def item(key, label, status, detail="", action=""):
    return {"key": key, "label": label, "status": status, "detail": detail, "action": action}


def exists_item(key, label, path, action=""):
    path = Path(path)
    if path.exists():
        return item(key, label, "ok", str(path))
    return item(key, label, "blocked", f"Missing: {path}", action)


def configured(value):
    return bool(str(value or "").strip())


def direct_model_ready(config):
    return (
        config.agent_chat_provider in {"minimax", "openai_compatible", "openai"}
        and configured(config.agent_chat_base_url)
        and configured(config.agent_chat_model)
        and configured(config.agent_chat_api_key)
    )


def hermes_codex_status(config):
    hermes_cli = shutil.which(getattr(config, "hermes_cli", "hermes"))
    if not hermes_cli:
        return {"ready": False, "detail": "Hermes not installed"}
    try:
        completed = subprocess.run(
            [hermes_cli, "status"],
            cwd=str(ROOT_DIR),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        return {"ready": False, "detail": f"Could not check Hermes status: {exc}"}
    output = (completed.stdout or "") + "\n" + (completed.stderr or "")
    provider_line = next((line.strip() for line in output.splitlines() if "Provider:" in line), "")
    codex_line = next((line.strip() for line in output.splitlines() if "OpenAI Codex" in line), "")
    codex_logged_in = bool(codex_line and "not logged in" not in codex_line.lower() and "\u2717" not in codex_line)
    codex_selected = "codex" in provider_line.lower() or "openai codex" in provider_line.lower()
    ready = codex_logged_in and codex_selected
    detail = f"{provider_line or 'Provider unknown'}; {codex_line or 'OpenAI Codex auth unknown'}"
    return {"ready": ready, "detail": detail}


def latest_daily_report():
    reports = sorted(OUTPUT_DIR.glob("daily_brief_*.json"), reverse=True)
    return reports[0] if reports else None


def latest_action():
    actions = read_json(ACTIONS_FILE, [])
    return actions[0] if actions else None


def status_counts(items):
    counts = {"ok": 0, "warn": 0, "blocked": 0}
    for entry in items:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    return counts


def files_section():
    return [
        exists_item("env_file", ".env config", ENV_FILE, "Run ./scripts/install-local.sh or copy .env.example to .env."),
        exists_item("ad_config", "ad-config.json", AD_CONFIG_FILE, "Copy ad-config.example.json to ad-config.json and set brand/account values."),
        exists_item("metrics", "Metrics cache", METRICS_FILE, "Run the dashboard or daily agent once."),
        exists_item("run_dashboard", "Dashboard script", SCRIPTS_DIR / "run-dashboard.sh"),
        exists_item("run_daily", "Daily agent script", SCRIPTS_DIR / "run-daily-agent.sh"),
    ]


def runtime_section(config, social_path, daily_report, action):
    return [
        item("mode", "Nivel de control", "ok" if config.mode == "dry-run" else "warn", "Con supervision" if config.mode == "dry-run" else "Piloto automatico", "Usa Con supervision hasta confirmar licencia, Meta, datos reales y aprobaciones." if config.mode != "dry-run" else ""),
        item("connector", "Primary connector", "ok" if config.meta_connector == "social_cli" else "warn", config.meta_connector, "Use social_cli for easiest buyer onboarding; graph_api is advanced."),
        item("social_cli", "social-cli installed", "ok" if social_path else "warn", social_path or f"{config.social_cli} not found", "Install/configure social-cli before live Meta actions."),
        item("social_onboarding", "social-cli onboarding", "warn", "Run social setup or social onboard, then social auth login.", "Recommended: social setup"),
        item("daily_report", "Latest daily report", "ok" if daily_report else "warn", str(daily_report) if daily_report else "No daily report yet.", "Run ./scripts/run-daily-agent.sh"),
        item("latest_action", "Latest action log", "ok" if action else "warn", action.get("type", "No actions yet") if action else "No actions logged yet."),
    ]


def security_section(config, license_status):
    env_perm = permission_detail(ENV_FILE)
    data_perm = permission_detail(DATA_DIR)
    output_perm = permission_detail(OUTPUT_DIR)
    logs_perm = permission_detail(ROOT_DIR / "logs")
    public_bind = is_public_bind(config.dashboard_host)
    return [
        item("dashboard_host", "Dashboard bind host", "blocked" if public_bind and not config.allow_public_dashboard else ("warn" if public_bind else "ok"), config.dashboard_host, "Keep DASHBOARD_HOST=127.0.0.1 unless using a reverse proxy or VPN."),
        item("dashboard_token", "Dashboard password", "ok" if configured(config.dashboard_token) else ("blocked" if config.dashboard_token_required else "warn"), "configured" if configured(config.dashboard_token) else "Missing DASHBOARD_PASSWORD", "Run ./scripts/install-local.sh or set a strong DASHBOARD_PASSWORD."),
        item("dashboard_token_required", "Password required for actions", "ok" if config.dashboard_token_required else "warn", str(config.dashboard_token_required), "Keep REQUIRE_DASHBOARD_TOKEN=true for buyer installs."),
        item("public_dashboard", "Public dashboard opt-in", "warn" if config.allow_public_dashboard else "ok", str(config.allow_public_dashboard), "Only enable behind HTTPS, firewall, and a reverse proxy."),
        item("live_actions", "Switch de acciones reales", "warn" if config.live_actions_enabled else "ok", str(config.live_actions_enabled), "Mantenlo apagado hasta confirmar licencia, datos reales y aprobaciones."),
        item("license_key", "License key", "ok" if license_status["valid"] else "warn", license_status["detail"], "Enter LICENSE_KEY in the Setup tab before guided live setup." if not license_status["valid"] else ""),
        item("env_permissions", ".env permissions", "ok" if env_perm["private"] else ("warn" if env_perm["exists"] else "blocked"), env_perm["mode"] or "missing", "Run chmod 600 .env."),
        item("data_permissions", "Dashboard data permissions", "ok" if data_perm["private"] else ("warn" if data_perm["exists"] else "blocked"), data_perm["mode"] or "missing", "Run chmod 700 dashboard/data."),
        item("output_permissions", "Output permissions", "ok" if output_perm["private"] else ("warn" if output_perm["exists"] else "blocked"), output_perm["mode"] or "missing", "Run chmod 700 output."),
        item("logs_permissions", "Logs permissions", "ok" if logs_perm["private"] else ("warn" if logs_perm["exists"] else "blocked"), logs_perm["mode"] or "missing", "Run chmod 700 logs."),
    ]


def meta_section(config, destination):
    return [
        item("ad_account", "Meta ad account", "ok" if configured(config.ad_account_id) else "blocked", config.ad_account_id or "Missing META_AD_ACCOUNT_ID", "Run social marketing accounts, then set META_AD_ACCOUNT_ID or social marketing set-default-account act_XXXX."),
        item("access_token", "Meta token", "ok" if configured(config.meta_access_token) else ("blocked" if config.live and config.meta_connector == "graph_api" else "warn"), "configured" if configured(config.meta_access_token) else "Not configured; paste your Meta token in onboarding.", "Pega el token creado en tu propia app de Meta."),
        item("page_id", "Page ID", "ok" if configured(destination.get("page_id")) else "blocked", destination.get("page_id") or "Missing creative.destination.page_id", "Set creative.destination.page_id in ad-config.json."),
        item("landing_url", "Landing page URL", "ok" if configured(destination.get("url")) else "blocked", destination.get("url") or "Missing creative.destination.url", "Set creative.destination.url in ad-config.json."),
    ]


def creative_section(config, codex_path):
    return [
        item("creative_enabled", "Creative refresh enabled", "ok" if config.creative_refresh_enabled else "warn", str(config.creative_refresh_enabled)),
        item("creative_mode", "Creative image mode", "ok" if config.creative_image_mode == "dry-run" else "warn", config.creative_image_mode, "Live image generation requires GEMINI_API_KEY." if config.creative_image_mode == "live" else ""),
        item("gemini_key", "Nano Banana / Gemini key", "ok" if configured(config.gemini_api_key) else ("blocked" if config.creative_live else "warn"), "configured" if configured(config.gemini_api_key) else "Missing GEMINI_API_KEY", "Set GEMINI_API_KEY to generate images live."),
        item("codex_cli", "Codex CLI", "ok" if codex_path else "warn", codex_path or f"{config.codex_cli} not found", "Install Codex CLI to use the Codex creative strategy bridge."),
        item("codex_creative", "Codex creative bridge (optional local-agent access)", "ok" if config.codex_creative_enabled else "warn", str(config.codex_creative_enabled), "Optional and off by default; enable only after reviewing local CLI access."),
        item("brand_guides", "Brand guide files", "ok" if (ROOT_DIR / "brand_guides" / "general_branding.md").exists() else "warn", str(ROOT_DIR / "brand_guides" / "general_branding.md"), "Create base guides from Creativos."),
        item("creative_index", "Creative drafts", "ok" if CREATIVE_INDEX_FILE.exists() else "warn", str(CREATIVE_INDEX_FILE) if CREATIVE_INDEX_FILE.exists() else "No creative drafts yet.", "Run python3 src/daily_agent.py creative-refresh --all"),
    ]


def agent_chat_section(config, agent_profile):
    hermes_cli = shutil.which(config.hermes_cli)
    hermes_library = importlib.util.find_spec("run_agent") is not None
    direct_ready = direct_model_ready(config)
    direct_selected = config.agent_chat_provider in {"minimax", "openai_compatible", "openai"}
    hermes_auth = hermes_codex_status(config) if config.agent_chat_provider == "hermes" else {"ready": False, "detail": "Hermes not selected"}
    hermes_runtime_status = "ok" if (hermes_cli or hermes_library) else "blocked"
    hermes_auth_status = "ok" if hermes_auth["ready"] else "blocked"
    hermes_runtime_detail = hermes_cli or ("Python library installed" if hermes_library else "Hermes not installed")
    if direct_selected:
        hermes_runtime_status = "ok"
        hermes_auth_status = "ok"
        hermes_runtime_detail = "No usado; el chat usa una API compatible OpenAI."
        hermes_auth = {"ready": False, "detail": "No usado; el chat usa una API compatible OpenAI."}
    direct_detail = "configured" if direct_ready else "Missing AGENT_CHAT_API_KEY, AGENT_CHAT_BASE_URL, or AGENT_CHAT_MODEL"
    if not direct_selected:
        direct_detail = "Optional unless AGENT_CHAT_PROVIDER is minimax/openai_compatible/openai."
    entries = [
        item("chat_provider", "Agent chat provider", "ok" if config.agent_chat_provider in {"hermes", "minimax", "openai_compatible", "openai"} else "blocked", config.agent_chat_provider, "Recommended provider: hermes, or openai_compatible for MiniMax M3/custom URLs."),
        item("hermes_runtime", "Hermes runtime", hermes_runtime_status, hermes_runtime_detail, "Install Hermes, then use the dashboard ChatGPT connection step. VPS installs use hermes model --no-browser."),
        item("hermes_auth", "Hermes ChatGPT/Codex login", hermes_auth_status, hermes_auth["detail"], "Use Configuracion > Conectar ChatGPT. On VPS the dashboard shows the Hermes login from the browser."),
        item("openai_compatible_model", "OpenAI-compatible model", "ok" if direct_ready else ("blocked" if direct_selected else "warn"), direct_detail, "Set AGENT_CHAT_PROVIDER=openai_compatible, AGENT_CHAT_BASE_URL, AGENT_CHAT_MODEL, and AGENT_CHAT_API_KEY."),
        item("chat_model", "Agent chat model", "ok", config.hermes_model if config.agent_chat_provider == "hermes" else config.agent_chat_model or "MiniMax-M3"),
        item("agent_profile", "Agent profile files", "ok" if not agent_profile["missing"] else "blocked", f"{len(agent_profile['sections'])}/5 loaded from {agent_profile['dir']}", "Restore agent/SOUL.md, AGENTS.md, TOOLS.md, SKILLS.md, and USER.md." if agent_profile["missing"] else ""),
    ]
    return entries, {"hermes_cli": hermes_cli, "hermes_library": hermes_library, "hermes_auth": hermes_auth, "direct_model_ready": direct_ready}


def telegram_access_section(telegram):
    return [
        item("telegram_enabled", "Telegram agent access", "ok" if telegram["enabled"] else "warn", "Enabled" if telegram["enabled"] else "Optional; not enabled", "Enable it in Configuracion when the buyer wants to talk from Telegram."),
        item("telegram_bot", "Telegram bot", "ok" if telegram["bot_configured"] else "warn", "configured" if telegram["bot_configured"] else "Not configured", "Create a private bot with @BotFather and save its token in Configuracion."),
        item("telegram_chat", "Allowed Telegram chat", "ok" if telegram["chat_id"] else "warn", "configured" if telegram["chat_id"] else "Not configured", "Send a message to the bot, then select your private chat in Configuracion."),
    ]


def upload_readiness_section(latest_upload):
    uploads = [
        item("upload_index", "Upload staging index", "ok" if UPLOAD_INDEX_FILE.exists() else "warn", str(UPLOAD_INDEX_FILE) if UPLOAD_INDEX_FILE.exists() else "No upload payloads staged yet.", "Stage a creative upload from the Creatives tab."),
    ]
    if latest_upload:
        uploads.append(item("latest_upload", "Latest upload payload", "ok" if latest_upload.get("missing_count", 1) == 0 else "blocked", f"{latest_upload.get('status')} / missing {latest_upload.get('missing_count')}", latest_upload.get("payload_path", "")))
    else:
        uploads.append(item("latest_upload", "Latest upload payload", "warn", "None"))
    return uploads


def scheduler_section():
    return [
        exists_item("cron_script", "Cron setup script", SCRIPTS_DIR / "setup-cron.sh"),
        exists_item("systemd_script", "VPS systemd setup script", SCRIPTS_DIR / "install-systemd-service.sh"),
        item("logs_dir", "Logs directory", "ok" if (ROOT_DIR / "logs").exists() else "warn", str(ROOT_DIR / "logs") if (ROOT_DIR / "logs").exists() else "logs directory not created yet", "Run ./scripts/install-local.sh"),
    ]


def setup_summary(config, sections, context):
    all_items = []
    for section in sections:
        all_items.extend(section["items"])
    security = next(section["items"] for section in sections if section["title"] == "Security")
    meta = next(section["items"] for section in sections if section["title"] == "Meta Live Requirements")
    return {
        "counts": status_counts(all_items),
        "demo_ready": ENV_FILE.exists() and METRICS_FILE.exists(),
        "security_ready": all(entry["status"] == "ok" for entry in security[:4]),
        "license_ready": context["license_status"]["valid"],
        "live_actions_enabled": config.live_actions_enabled,
        "live_ads_ready": bool(context["social_path"] and configured(config.ad_account_id) and config.live_actions_enabled),
        "direct_graph_ready": all(entry["status"] == "ok" for entry in meta),
        "creative_ready": config.creative_refresh_enabled and (config.creative_image_mode == "dry-run" or configured(config.gemini_api_key)),
        "agent_chat_ready": (
            (config.agent_chat_provider == "hermes" and bool(context["hermes_cli"] or context["hermes_library"]) and context["hermes_auth"]["ready"])
            or bool(context.get("direct_model_ready"))
        ),
        "telegram_ready": context["telegram"]["enabled"] and context["telegram"]["bot_configured"] and bool(context["telegram"]["chat_id"]),
        "agent_profile_ready": not context["agent_profile"]["missing"],
        "upload_ready": bool(context["latest_upload"] and context["latest_upload"].get("missing_count") == 0),
    }


def build_setup_status():
    config = load_config()
    ad_config = load_ad_config()
    creative_cfg = ad_config.get("creative", {})
    destination = creative_cfg.get("destination", {})
    social_path = shutil.which(config.social_cli)
    codex_path = shutil.which(config.codex_cli)
    recent_upload = recent_uploads(1)
    latest_upload = recent_upload[0] if recent_upload else None
    agent_profile = load_agent_profile(config)
    license_status = current_license_status(config)
    telegram = telegram_settings(config)

    files = files_section()
    runtime = runtime_section(config, social_path, latest_daily_report(), latest_action())
    security = security_section(config, license_status)
    meta = meta_section(config, destination)
    creative = creative_section(config, codex_path)
    agent_chat, agent_context = agent_chat_section(config, agent_profile)
    telegram_access = telegram_access_section(telegram)
    uploads = upload_readiness_section(latest_upload)
    scheduler = scheduler_section()
    sections = [
        {"title": "Files", "items": files},
        {"title": "Runtime", "items": runtime},
        {"title": "Security", "items": security},
        {"title": "Meta Live Requirements", "items": meta},
        {"title": "Creative Generation", "items": creative},
        {"title": "Agent Chat", "items": agent_chat},
        {"title": "Telegram", "items": telegram_access},
        {"title": "Upload Readiness", "items": uploads},
        {"title": "Scheduler", "items": scheduler},
    ]
    context = {
        **agent_context,
        "agent_profile": agent_profile,
        "latest_upload": latest_upload,
        "license_status": license_status,
        "social_path": social_path,
        "telegram": telegram,
    }
    return {
        "summary": setup_summary(config, sections, context),
        "sections": sections,
    }
