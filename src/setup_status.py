#!/usr/bin/env python3
"""Setup diagnostics for Admira IA."""
import shutil
import importlib.util
import subprocess
from datetime import datetime
from pathlib import Path

from codex_brand_guides import hermes_codex_image_status
from creative_refresh import INDEX_FILE as CREATIVE_INDEX_FILE
from creative_refresh import load_ad_config, read_json
from agent_runtime import load_agent_profile
from hermes_bridge import codex_auth_line_from_status, codex_auth_line_is_logged_in, hermes_brain_ready, hermes_brain_settings
from license import license_status as current_license_status
from meta_upload import UPLOAD_INDEX_FILE, recent_uploads
from product_config import ENV_FILE, ROOT_DIR, load_config
from security import is_public_bind, permission_detail
from hermes_gateway import telegram_settings


DATA_DIR = ROOT_DIR / "dashboard" / "data"
OUTPUT_DIR = ROOT_DIR / "output"
AD_CONFIG_FILE = ROOT_DIR / "ad-config.json"
AD_CONFIG_EXAMPLE_FILE = ROOT_DIR / "ad-config.example.json"
SCRIPTS_DIR = ROOT_DIR / "scripts"
ACTIONS_FILE = DATA_DIR / "actions.json"
PENDING_FILE = DATA_DIR / "pending_approvals.json"
METRICS_FILE = DATA_DIR / "metrics.json"
META_OAUTH_CONNECTION_FILE = DATA_DIR / "meta_oauth_connection.json"


def item(key, label, status, detail="", action=""):
    return {"key": key, "label": label, "status": status, "detail": detail, "action": action}


def exists_item(key, label, path, action=""):
    path = Path(path)
    if path.exists():
        return item(key, label, "ok", str(path))
    return item(key, label, "blocked", f"Missing: {path}", action)


def configured(value):
    return bool(str(value or "").strip())


def meta_oauth_summary(config):
    """Return the local, non-secret OAuth state used by the dashboard.

    OAuth credentials are intentionally not exposed in setup diagnostics.  The
    connection record only contains the safe account/Page summary and is the
    source of truth for OAuth-first installations.
    """
    connection = read_json(META_OAUTH_CONNECTION_FILE, {})
    if not isinstance(connection, dict):
        connection = {}
    accounts = [entry for entry in (connection.get("accounts") or []) if isinstance(entry, dict)]
    pages = [entry for entry in (connection.get("pages") or []) if isinstance(entry, dict)]
    return {
        "enabled": configured(getattr(config, "meta_oauth_broker_url", "")) or META_OAUTH_CONNECTION_FILE.exists(),
        "connected": bool(connection.get("connected")),
        "accounts": accounts,
        "pages": pages,
        "active_ad_account_id": str(connection.get("active_ad_account_id") or "").strip(),
        "active_page_id": str(connection.get("active_page_id") or "").strip(),
    }


def meta_token_age_days(config):
    saved_at = str(getattr(config, "meta_access_token_saved_at", "") or "").strip()
    if not saved_at:
        return None
    try:
        saved = datetime.fromisoformat(saved_at)
        now = datetime.now(saved.tzinfo) if saved.tzinfo else datetime.now()
        return max(0, int((now - saved).total_seconds() // 86400))
    except ValueError:
        return None


def meta_token_detail(config):
    kind = str(getattr(config, "meta_access_token_kind", "") or "").strip().lower()
    if kind == "stable":
        return "Clave estable recomendada guardada"
    if kind == "quick":
        days = meta_token_age_days(config)
        if days is None:
            return "Clave rápida guardada; recuerda renovarla aproximadamente cada 60 días"
        return f"Clave rápida guardada hace {days} días; recuerda renovarla aproximadamente cada 60 días"
    return "configured"


def meta_token_renewal_item(config):
    kind = str(getattr(config, "meta_access_token_kind", "") or "").strip().lower()
    if kind != "quick" or not configured(config.meta_access_token):
        return item("access_token_renewal", "Meta key renewal", "ok", "No renewal reminder needed")
    days = meta_token_age_days(config)
    if days is not None and days >= 55:
        return item("access_token_renewal", "Meta key renewal", "warn", f"Clave rápida guardada hace {days} días", "Renueva la clave rápida o cambia a clave estable desde Configuración.")
    return item("access_token_renewal", "Meta key renewal", "ok", "Recordatorio activo para renovar la clave rápida alrededor de 60 días")


def direct_model_ready(config):
    brain = hermes_brain_settings(config)
    return (
        brain.get("brain") in {"minimax", "nvidia_nim", "openai_api", "custom_api"}
        and configured(brain.get("model"))
        and configured(brain.get("api_key"))
        and (brain.get("provider") != "custom" or configured(brain.get("base_url")))
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
    codex_line = codex_auth_line_from_status(output)
    codex_logged_in = codex_auth_line_is_logged_in(codex_line)
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


def runtime_section(config, daily_report, action):
    oauth = meta_oauth_summary(config)
    graph_ready = bool(getattr(config, "meta_access_token", "")) or oauth["connected"]
    return [
        item("approval_protection", "Protección por aprobación", "ok", "Crear pausado permitido; activar/gastar pide aprobación", "Admira puede dejar estructuras listas en pausa. La luz verde se pide al activar o gastar."),
        item("connector", "Meta execution path", "ok" if graph_ready else "warn", "Facebook OAuth seguro" if oauth["connected"] else ("Meta Graph API directo" if configured(getattr(config, "meta_access_token", "")) else "Conecta Facebook desde el enlace seguro de Telegram"), "Conecta Facebook desde Telegram; no necesitas pegar claves." if oauth["enabled"] else "Pega una clave de Meta válida en Configuración para que Admira ejecute acciones reales."),
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
        item("license_key", "License key", "ok" if license_status["valid"] else "warn", license_status["detail"], "Enter LICENSE_KEY in the Setup tab before guided live setup." if not license_status["valid"] else ""),
        item("env_permissions", ".env permissions", "ok" if env_perm["private"] else ("warn" if env_perm["exists"] else "blocked"), env_perm["mode"] or "missing", "Run chmod 600 .env."),
        item("data_permissions", "Dashboard data permissions", "ok" if data_perm["private"] else ("warn" if data_perm["exists"] else "blocked"), data_perm["mode"] or "missing", "Run chmod 700 dashboard/data."),
        item("output_permissions", "Output permissions", "ok" if output_perm["private"] else ("warn" if output_perm["exists"] else "blocked"), output_perm["mode"] or "missing", "Run chmod 700 output."),
        item("logs_permissions", "Logs permissions", "ok" if logs_perm["private"] else ("warn" if logs_perm["exists"] else "blocked"), logs_perm["mode"] or "missing", "Run chmod 700 logs."),
    ]


def meta_section(config, destination):
    oauth = meta_oauth_summary(config)
    # New installations are OAuth-first.  Do not expose the obsolete token
    # checklist in their setup status; legacy token installs remain supported.
    if oauth["enabled"]:
        account_id = oauth["active_ad_account_id"] or str(config.ad_account_id or "").strip()
        page_id = oauth["active_page_id"] or str(destination.get("page_id") or "").strip()
        return [
            item("facebook_oauth", "Facebook connection", "ok" if oauth["connected"] else "blocked", "Connected with secure Facebook OAuth" if oauth["connected"] else "Connect Facebook from the secure link sent to Telegram.", "Open Telegram and press Connect Facebook."),
            item("ad_account", "Meta ad account", "ok" if configured(account_id) else "blocked", account_id or "Choose an ad account after Facebook OAuth.", "Choose one of the ad accounts returned by Facebook."),
            item("page_id", "Page ID", "ok" if configured(page_id) else "blocked", page_id or "Choose a Facebook Page after Facebook OAuth.", "Choose the Page where ads and organic posts will run."),
            item("landing_url", "Landing page URL", "ok" if configured(destination.get("url")) else "blocked", destination.get("url") or "Missing creative.destination.url", "Set creative.destination.url in ad-config.json."),
        ]
    return [
        item("ad_account", "Meta ad account", "ok" if configured(config.ad_account_id) else "blocked", config.ad_account_id or "Missing META_AD_ACCOUNT_ID", "Elige una cuenta publicitaria desde Configuración o pega el ID act_XXXX manualmente."),
        item("access_token", "Meta access key", "ok" if configured(config.meta_access_token) else ("blocked" if config.live and config.meta_connector == "graph_api" else "warn"), meta_token_detail(config) if configured(config.meta_access_token) else "Not configured; paste your Meta key in onboarding.", "Pega la clave creada en tu propia app de Meta."),
        item("publishing_token", "Direct publishing key", "ok" if configured(getattr(config, "meta_access_token", "")) or configured(getattr(config, "meta_publishing_access_token", "")) else "warn", "configured" if configured(getattr(config, "meta_access_token", "")) or configured(getattr(config, "meta_publishing_access_token", "")) else "Pega un único token de Meta con permisos de anuncios y de Página.", "La publicación orgánica usa el mismo token principal de Meta; no se necesita una segunda clave."),
        meta_token_renewal_item(config),
        item("page_id", "Page ID", "ok" if configured(destination.get("page_id")) else "blocked", destination.get("page_id") or "Missing creative.destination.page_id", "Set creative.destination.page_id in ad-config.json."),
        item("landing_url", "Landing page URL", "ok" if configured(destination.get("url")) else "blocked", destination.get("url") or "Missing creative.destination.url", "Set creative.destination.url in ad-config.json."),
    ]


def creative_section(config, codex_path, image_status=None):
    image_status = image_status if isinstance(image_status, dict) else hermes_codex_image_status(timeout=5, config=config)
    image_ready = bool(image_status.get("ok"))
    return [
        item("creative_enabled", "Creative refresh enabled", "ok" if config.creative_refresh_enabled else "warn", str(config.creative_refresh_enabled)),
        item("creative_mode", "Image generation path", "ok", "ChatGPT/Codex por Hermes", "Las imagenes finales usan la misma conexion ChatGPT/Codex del agente, sin otra API de imagenes."),
        item("codex_cli", "Codex CLI", "ok" if codex_path else "warn", codex_path or f"{config.codex_cli} not found", "Solo se usa como respaldo en instalaciones antiguas; la ruta principal es Hermes + ChatGPT/Codex."),
        item("codex_image_auth", "Imagenes con ChatGPT/Codex", "ok" if image_ready else "blocked", "connected" if image_ready else (image_status.get("detail") or "Conecta ChatGPT/Codex"), "Conecta ChatGPT/Codex antes de pedir imagenes finales."),
        item("codex_creative", "Codex creative bridge", "ok" if config.codex_creative_enabled else "warn", str(config.codex_creative_enabled), "Keep enabled so the agent can request Codex/Image creative generation."),
        item("brand_guides", "Brand guide files", "ok" if (ROOT_DIR / "brand_guides" / "general_branding.md").exists() else "warn", str(ROOT_DIR / "brand_guides" / "general_branding.md"), "Create base guides from Creativos."),
        item("creative_index", "Creative drafts", "ok" if CREATIVE_INDEX_FILE.exists() else "warn", str(CREATIVE_INDEX_FILE) if CREATIVE_INDEX_FILE.exists() else "No creative drafts yet.", "Run python3 src/daily_agent.py creative-refresh --all"),
    ]


def agent_chat_section(config, agent_profile, brain_status=None):
    hermes_cli = shutil.which(config.hermes_cli)
    hermes_library = importlib.util.find_spec("run_agent") is not None
    brain = hermes_brain_settings(config)
    direct_ready = direct_model_ready(config)
    if isinstance(brain_status, dict):
        brain_ready = bool(brain_status.get("authenticated", brain_status.get("ready")))
        brain_detail = str(brain_status.get("detail") or "")
    else:
        brain_ready, brain_detail = hermes_brain_ready(config)
    hermes_auth = {"ready": brain_ready, "detail": brain_detail}
    hermes_runtime_status = "ok" if (hermes_cli or hermes_library) else "blocked"
    hermes_auth_status = "ok" if hermes_auth["ready"] else "blocked"
    hermes_runtime_detail = hermes_cli or ("Agent base installed" if hermes_library else "Agent base not installed")
    api_brain_selected = brain.get("brain") in {"minimax", "nvidia_nim", "openai_api", "custom_api"}
    direct_detail = "configured inside the agent" if direct_ready else "Missing AGENT_CHAT_API_KEY, AGENT_CHAT_BASE_URL, or AGENT_CHAT_MODEL"
    if not api_brain_selected:
        direct_detail = "Opcional: solo si eliges NVIDIA NIM, MiniMax M3, OpenAI API u otra API compatible como cerebro del agente."
    entries = [
        item("chat_provider", "Agent base", "ok" if config.agent_chat_provider == "hermes" else "blocked", "fixed", "The agent base is fixed; you only choose the brain/model."),
        item("hermes_runtime", "Agent base installed", hermes_runtime_status, hermes_runtime_detail, "Use the dashboard ChatGPT/Codex connection step."),
        item("hermes_auth", "Agent brain", hermes_auth_status, hermes_auth["detail"], "Use Configuracion > Conectar ChatGPT/modelo API. On VPS the dashboard shows the login from the browser."),
        item("openai_compatible_model", "API-compatible brain", "ok" if direct_ready else ("blocked" if api_brain_selected else "warn"), direct_detail, "Save model URL, model name, and API key; the agent base remains the same."),
        item("chat_model", "Agent chat model", "ok", brain.get("model") or "configured in the agent"),
        item("agent_profile", "Agent profile files", "ok" if not agent_profile["missing"] else "blocked", f"{len(agent_profile['sections'])}/5 loaded from {agent_profile['dir']}", "Restore agent/SOUL.md, AGENTS.md, TOOLS.md, SKILLS.md, and USER.md." if agent_profile["missing"] else ""),
    ]
    return entries, {"hermes_cli": hermes_cli, "hermes_library": hermes_library, "hermes_auth": hermes_auth, "direct_model_ready": direct_ready, "agent_brain": brain}


def telegram_access_section(telegram):
    return [
        item("telegram_enabled", "Telegram directo por Hermes", "ok" if telegram["enabled"] else "warn", "Enabled" if telegram["enabled"] else "Optional; not enabled", "Enable it in Configuracion when the buyer wants to talk from Telegram."),
        item("telegram_mode", "Modo Telegram", "ok" if telegram.get("mode") == "hermes_gateway" else "warn", telegram.get("mode") or "hermes_gateway", "Usa hermes_gateway para que Telegram sea Hermes directo."),
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
    creative = next(section["items"] for section in sections if section["title"] == "Creative Generation")
    codex_image_ready = any(entry["key"] == "codex_image_auth" and entry["status"] == "ok" for entry in creative)
    oauth = meta_oauth_summary(config)
    live_connection = oauth["connected"] or configured(config.meta_access_token)
    return {
        "counts": status_counts(all_items),
        "demo_ready": ENV_FILE.exists() and METRICS_FILE.exists(),
        "security_ready": all(entry["status"] == "ok" for entry in security[:4]),
        "license_ready": context["license_status"]["valid"],
        "live_actions_enabled": False,
        "live_ads_ready": bool(live_connection and configured(config.ad_account_id)),
        "approval_protection": True,
        "direct_graph_ready": all(entry["status"] == "ok" for entry in meta),
        "creative_ready": config.creative_refresh_enabled and codex_image_ready,
        "agent_chat_ready": (
            bool(context["hermes_cli"] or context["hermes_library"]) and context["hermes_auth"]["ready"]
        ),
        "telegram_ready": context["telegram"]["enabled"] and context["telegram"]["bot_configured"] and bool(context["telegram"]["chat_id"]),
        "agent_profile_ready": not context["agent_profile"]["missing"],
        "upload_ready": bool(context["latest_upload"] and context["latest_upload"].get("missing_count") == 0),
    }


def build_setup_status(runtime_status=None):
    config = load_config()
    ad_config = load_ad_config()
    creative_cfg = ad_config.get("creative", {})
    destination = creative_cfg.get("destination", {})
    codex_path = shutil.which(config.codex_cli)
    recent_upload = recent_uploads(1)
    latest_upload = recent_upload[0] if recent_upload else None
    agent_profile = load_agent_profile(config)
    license_status = current_license_status(config)
    telegram = telegram_settings(config)

    files = files_section()
    runtime = runtime_section(config, latest_daily_report(), latest_action())
    security = security_section(config, license_status)
    meta = meta_section(config, destination)
    runtime_status = runtime_status if isinstance(runtime_status, dict) else {}
    creative = creative_section(config, codex_path, runtime_status.get("codex_image_status"))
    agent_chat, agent_context = agent_chat_section(config, agent_profile, runtime_status.get("main_codex_session"))
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
        "telegram": telegram,
    }
    return {
        "summary": setup_summary(config, sections, context),
        "sections": sections,
    }
