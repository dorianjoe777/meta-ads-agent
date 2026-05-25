#!/usr/bin/env python3
"""
Meta Ads Agent - web dashboard and daily agent runner.

Run:
    python3 dashboard/monitoring-dashboard.py

Open:
    http://127.0.0.1:7871
"""
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_chat import chat as agent_chat
from audience_builder import build_audience_strategy
from budget_optimizer import BudgetOptimizer, OptimizationStrategy, PerformanceMetrics
from campaign_creator import CampaignCreator
from codex_brand_guides import brand_guide_status, build_codex_creative_prompt, call_codex_cli, ensure_brand_guides
from creative_refresh import generate_creative_refresh, recent_creative_refreshes
from daily_agent import approve as approve_pending, run_daily as run_scheduled_daily
from graph_executor import execute_upload_payload
from license import activate_license, license_status, validate_license_key
from meta_upload import recent_uploads, stage_upload
from product_config import ENV_FILE, load_config
from security import dashboard_token_valid, is_public_bind, redact_payload
from setup_status import build_setup_status
from social_flow_client import SocialFlowClient
from telegram_agent import bot_request as telegram_bot_request
from telegram_agent import run as run_telegram_listener
from telegram_agent import send_message as send_telegram_message
from telegram_agent import telegram_settings


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(__file__).resolve().parent / "data"
OUTPUT_DIR = ROOT_DIR / "output"
METRICS_FILE = DATA_DIR / "metrics.json"
ACTIONS_FILE = DATA_DIR / "actions.json"
PENDING_FILE = DATA_DIR / "pending_approvals.json"
CREATED_FILE = DATA_DIR / "created_campaigns.json"
AUDIENCE_FILE = DATA_DIR / "audience_strategy.json"
ONBOARDING_FILE = DATA_DIR / "onboarding_state.json"
CHAT_HISTORY_FILE = DATA_DIR / "chat_history.json"
BUSINESS_PROFILE_FILE = DATA_DIR / "business_profile.json"
INDIVIDUAL_BINDING_FILE = DATA_DIR / "individual_business_binding.json"
AGENCY_SPACES_FILE = DATA_DIR / "agency_spaces.json"
AGENCY_SPACES_DIR = DATA_DIR / "agency_spaces"
AD_CONFIG_FILE = ROOT_DIR / "ad-config.json"
DASHBOARD_HTML_FILE = DATA_DIR / "dashboard.html"
BRAND_GUIDES_DIR = ROOT_DIR / "brand_guides"
BRAND_PRODUCTS_DIR = BRAND_GUIDES_DIR / "products"
PORT = 7871
TARGET_CPA = 50.0
TELEGRAM_THREAD = None
TELEGRAM_STOP = None
CHAT_HISTORY_LIMIT = 40
BUSINESS_DATA_FILES = [
    "metrics.json",
    "actions.json",
    "pending_approvals.json",
    "created_campaigns.json",
    "audience_strategy.json",
    "onboarding_state.json",
    "chat_history.json",
    "business_profile.json",
    "telegram_chat_history.json",
    "telegram_offset.json",
]
BUSINESS_ENV_KEYS = [
    "META_AD_ACCOUNT_ID",
    "META_ACCESS_TOKEN",
    "TELEGRAM_AGENT_ENABLED",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_LANGUAGE",
]


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path, fallback):
    if not path.exists():
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return fallback


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def write_private_json(path, payload):
    write_json(path, payload)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def update_env_values(values):
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    seen = set()
    updated = []
    for line in lines:
        if "=" not in line or line.lstrip().startswith("#"):
            updated.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in values:
            updated.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            updated.append(line)
    for key, value in values.items():
        if key not in seen:
            updated.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")
    for key, value in values.items():
        os.environ[key] = str(value)


def license_entitlements():
    status = license_status(load_config())
    features = status.get("features") or []
    agency = bool(status.get("valid") and (status.get("plan") == "agency" or "agency_workspaces" in features))
    return {
        "plan": "agency" if agency else "individual",
        "is_agency": agency,
        "max_devices": int(status.get("max_devices") or (4 if agency else 1)),
        "workspace_limit": int(status.get("workspace_limit") or (50 if agency else 1)),
    }


def business_identity(payload=None):
    config = load_config()
    ad_config = read_json(AD_CONFIG_FILE, {})
    destination = ad_config.get("creative", {}).get("destination", {})
    incoming = payload or {}
    return {
        "ad_account_id": str(incoming.get("ad_account_id") or config.ad_account_id or ad_config.get("account", {}).get("id", "")).strip(),
        "page_id": str(incoming.get("page_id") or destination.get("page_id", "")).strip(),
    }


def changed_business_fields(payload):
    current = business_identity()
    changes = {}
    for key in ["ad_account_id", "page_id"]:
        incoming = str(payload.get(key) or "").strip() if key in payload else ""
        if incoming and current.get(key) and incoming != current[key]:
            changes[key] = {"from": current[key], "to": incoming}
    return changes


def clear_business_memory():
    for name in BUSINESS_DATA_FILES:
        path = DATA_DIR / name
        if path.exists():
            path.unlink()


def clear_business_brand_guides():
    """Remove buyer-authored creative memory, retaining only packaged examples."""
    general = BRAND_GUIDES_DIR / "general_branding.md"
    if general.exists():
        general.unlink()
    if BRAND_PRODUCTS_DIR.exists():
        for path in BRAND_PRODUCTS_DIR.glob("*.md"):
            if path.name != "product.example.md":
                path.unlink()


def snapshot_business_brand_guides(target):
    stored = target / "brand_guides"
    if stored.exists():
        shutil.rmtree(stored)
    (stored / "products").mkdir(parents=True, exist_ok=True)
    general = BRAND_GUIDES_DIR / "general_branding.md"
    if general.exists():
        shutil.copy2(general, stored / general.name)
    if BRAND_PRODUCTS_DIR.exists():
        for path in BRAND_PRODUCTS_DIR.glob("*.md"):
            if path.name != "product.example.md":
                shutil.copy2(path, stored / "products" / path.name)


def restore_business_brand_guides(source_dir):
    clear_business_brand_guides()
    stored = source_dir / "brand_guides"
    general = stored / "general_branding.md"
    if general.exists():
        BRAND_GUIDES_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(general, BRAND_GUIDES_DIR / general.name)
    product_source = stored / "products"
    if product_source.exists():
        BRAND_PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
        for path in product_source.glob("*.md"):
            shutil.copy2(path, BRAND_PRODUCTS_DIR / path.name)


def enforce_individual_business_change(payload):
    has_bound_business = INDIVIDUAL_BINDING_FILE.exists() or load_onboarding_state().get("completed")
    if license_entitlements()["is_agency"] or not has_bound_business:
        return False
    changes = changed_business_fields(payload)
    if not changes:
        return False
    if not bool(payload.get("confirm_replace_business")):
        raise ValueError("CONFIRM_BUSINESS_REPLACE: Tu licencia Individual administra un solo negocio. Si cambias la cuenta o página, se borrará la memoria anterior del dashboard y del agente.")
    clear_business_memory()
    clear_business_brand_guides()
    update_env_values({"LIVE_ACTIONS_ENABLED": "false", "META_ADS_AGENT_MODE": "dry-run"})
    write_json(INDIVIDUAL_BINDING_FILE, {"replaced_at": now_iso(), **business_identity(payload)})
    return True


def save_individual_binding():
    if not license_entitlements()["is_agency"]:
        write_json(INDIVIDUAL_BINDING_FILE, {"bound_at": now_iso(), **business_identity()})


def agency_registry():
    if AGENCY_SPACES_DIR.exists():
        try:
            AGENCY_SPACES_DIR.chmod(0o700)
        except OSError:
            pass
        for target in AGENCY_SPACES_DIR.iterdir():
            if target.is_dir():
                try:
                    target.chmod(0o700)
                except OSError:
                    pass
                private_config = target / "workspace_config.json"
                if private_config.exists():
                    try:
                        private_config.chmod(0o600)
                    except OSError:
                        pass
    registry = read_json(AGENCY_SPACES_FILE, {"active_id": "", "spaces": []})
    if not isinstance(registry, dict):
        registry = {"active_id": "", "spaces": []}
    registry.setdefault("active_id", "")
    registry.setdefault("spaces", [])
    return registry


def workspace_slug(value):
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return (slug[:48] or "cliente") + "-" + datetime.now().strftime("%H%M%S")


def snapshot_workspace(space_id):
    if not space_id:
        return
    target = AGENCY_SPACES_DIR / space_id
    target.mkdir(parents=True, mode=0o700, exist_ok=True)
    target.chmod(0o700)
    for name in BUSINESS_DATA_FILES:
        source = DATA_DIR / name
        destination = target / name
        if source.exists():
            shutil.copy2(source, destination)
        elif destination.exists():
            destination.unlink()
    snapshot_business_brand_guides(target)
    config = load_config()
    env_values = {
        "META_AD_ACCOUNT_ID": config.ad_account_id,
        "META_ACCESS_TOKEN": config.meta_access_token,
        "TELEGRAM_AGENT_ENABLED": "true" if telegram_settings(config)["enabled"] else "false",
        "TELEGRAM_BOT_TOKEN": config.telegram_bot_token,
        "TELEGRAM_CHAT_ID": config.telegram_chat_id,
        "TELEGRAM_LANGUAGE": telegram_settings(config)["language"],
    }
    write_private_json(target / "workspace_config.json", {"env": env_values, "ad_config": read_json(AD_CONFIG_FILE, {})})


def restore_workspace(space_id):
    source_dir = AGENCY_SPACES_DIR / space_id
    clear_business_memory()
    restore_business_brand_guides(source_dir)
    for name in BUSINESS_DATA_FILES:
        source = source_dir / name
        if source.exists():
            shutil.copy2(source, DATA_DIR / name)
    stored = read_json(source_dir / "workspace_config.json", {"env": {}, "ad_config": {}})
    update_env_values({
        "META_AD_ACCOUNT_ID": "",
        "META_ACCESS_TOKEN": "",
        "TELEGRAM_AGENT_ENABLED": "false",
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
        "TELEGRAM_LANGUAGE": "es",
        **stored.get("env", {}),
    })
    write_json(AD_CONFIG_FILE, stored.get("ad_config") or {"account": {}, "creative": {"destination": {}}})


def agency_spaces_payload():
    limits = license_entitlements()
    registry = agency_registry()
    return {**limits, **registry}


def create_agency_space(payload):
    limits = license_entitlements()
    if not limits["is_agency"]:
        raise ValueError("Los espacios para varios clientes requieren licencia Agencia.")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("Escribe el nombre del cliente o negocio.")
    registry = agency_registry()
    if len(registry["spaces"]) >= limits["workspace_limit"]:
        raise ValueError("Alcanzaste el limite de espacios de esta licencia.")
    space = {"id": workspace_slug(name), "name": name[:80], "created_at": now_iso()}
    registry["spaces"].append(space)
    target = AGENCY_SPACES_DIR / space["id"]
    target.mkdir(parents=True, mode=0o700, exist_ok=True)
    target.chmod(0o700)
    write_json(AGENCY_SPACES_FILE, registry)
    log_action("agency_space_create", {"space_id": space["id"], "name": space["name"]}, "completed")
    return {**space, "active": False}


def switch_agency_space(payload):
    global TELEGRAM_THREAD, TELEGRAM_STOP
    if not license_entitlements()["is_agency"]:
        raise ValueError("Cambiar entre clientes requiere licencia Agencia.")
    target_id = str(payload.get("space_id") or "").strip()
    registry = agency_registry()
    target = next((space for space in registry["spaces"] if space["id"] == target_id), None)
    if not target:
        raise ValueError("No encontré ese espacio de cliente.")
    if registry.get("active_id"):
        snapshot_workspace(registry["active_id"])
    restore_workspace(target_id)
    registry["active_id"] = target_id
    write_json(AGENCY_SPACES_FILE, registry)
    if TELEGRAM_STOP:
        TELEGRAM_STOP.set()
    TELEGRAM_THREAD = None
    TELEGRAM_STOP = None
    ensure_telegram_listener()
    log_action("agency_space_switch", {"space_id": target_id, "name": target["name"]}, "completed")
    return agency_spaces_payload()


def set_mode(payload):
    requested = str(payload.get("mode") or "").strip().lower()
    if requested not in {"dry-run", "live"}:
        raise ValueError("Unsupported mode")
    config = load_config()
    status = activate_license(config) if requested == "live" else license_status(config)
    if requested == "live" and config.license_required_for_live and not status.get("valid"):
        raise ValueError(f"License unlock required before live mode: {status.get('detail')}")
    live_enabled = bool(payload.get("live_actions_enabled")) if requested == "live" else False
    values = {
        "META_ADS_AGENT_MODE": requested,
        "LIVE_ACTIONS_ENABLED": "true" if live_enabled else "false",
    }
    update_env_values(values)
    log_action("mode_switch", {"mode": requested, "live_actions_enabled": live_enabled}, "completed")
    return {"mode": requested, "live_actions_enabled": live_enabled}


def save_guardrails(payload):
    mode = str(payload.get("autonomy_mode") or "supervised").strip().lower()
    if mode not in {"supervised", "autopilot"}:
        mode = "supervised"
    bool_value = lambda key, default=True: str(payload.get(key, "true" if default else "false")).strip().lower() in {"1", "true", "yes", "on"}
    values = {
        "META_AUTONOMY_MODE": mode,
        "META_APPROVAL_REQUIRED_OVER_PCT": str(float(payload.get("approval_required_over_pct") or 20)),
        "META_AUTO_BUDGET_CHANGE_PCT": str(float(payload.get("auto_budget_change_pct") or 10)),
        "META_AUTO_BUDGET_CHANGE_AMOUNT": str(float(payload.get("auto_budget_change_amount") or 25)),
        "META_AUTO_PAUSE_MAX_SPEND": str(float(payload.get("auto_pause_max_spend") or 100)),
        "META_REQUIRE_APPROVAL_FOR_RESUME": "true" if bool_value("require_approval_for_resume", True) else "false",
        "META_REQUIRE_APPROVAL_FOR_NEW_CAMPAIGNS": "true" if bool_value("require_approval_for_new_campaigns", True) else "false",
        "META_REQUIRE_APPROVAL_FOR_CREATIVES": "true" if bool_value("require_approval_for_creatives", True) else "false",
    }
    update_env_values(values)
    log_action("guardrails_update", values, "completed")
    return {"saved": True, "values": values}


def save_telegram_config(payload):
    values = {}
    if "enabled" in payload:
        values["TELEGRAM_AGENT_ENABLED"] = "true" if str(payload.get("enabled")).strip().lower() in {"1", "true", "yes", "on"} else "false"
    if str(payload.get("bot_token") or "").strip():
        values["TELEGRAM_BOT_TOKEN"] = str(payload.get("bot_token")).strip()
    if "chat_id" in payload:
        values["TELEGRAM_CHAT_ID"] = str(payload.get("chat_id") or "").strip()
    if "language" in payload:
        values["TELEGRAM_LANGUAGE"] = "en" if str(payload.get("language")).strip().lower() == "en" else "es"
    if values:
        update_env_values(values)
    config = load_config()
    status = telegram_settings(config)
    status["listener_started"] = ensure_telegram_listener()
    log_action("telegram_config_save", {"enabled": status["enabled"], "bot_configured": status["bot_configured"], "chat_id_set": bool(status["chat_id"])}, "completed")
    return status


def ensure_telegram_listener():
    global TELEGRAM_THREAD, TELEGRAM_STOP
    config = load_config()
    status = telegram_settings(config)
    if not (status["enabled"] and status["bot_configured"] and status["chat_id"]):
        if TELEGRAM_STOP:
            TELEGRAM_STOP.set()
        return False
    if TELEGRAM_THREAD and TELEGRAM_THREAD.is_alive() and not (TELEGRAM_STOP and TELEGRAM_STOP.is_set()):
        return True
    TELEGRAM_STOP = threading.Event()
    TELEGRAM_THREAD = threading.Thread(target=run_telegram_listener, args=(TELEGRAM_STOP,), name="telegram-agent", daemon=True)
    TELEGRAM_THREAD.start()
    return True


def detect_telegram_chats():
    config = load_config()
    if not config.telegram_bot_token:
        raise ValueError("Primero guarda el token del bot de Telegram.")
    updates = telegram_bot_request(config, "getUpdates", {"timeout": 0, "allowed_updates": json.dumps(["message"])}, timeout=10) or []
    candidates = {}
    for update in updates:
        chat = (update.get("message") or {}).get("chat") or {}
        if chat.get("type") != "private" or not chat.get("id"):
            continue
        label = " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])).strip()
        username = f"@{chat.get('username')}" if chat.get("username") else ""
        candidates[str(chat["id"])] = {"id": str(chat["id"]), "label": label or username or "Chat privado", "username": username}
    return list(candidates.values())[-5:]


def test_telegram_connection():
    config = load_config()
    status = telegram_settings(config)
    if not status["bot_configured"] or not status["chat_id"]:
        raise ValueError("Guarda el bot y el chat antes de enviar la prueba.")
    send_telegram_message(config, status["chat_id"], "Conexion lista. Ya puedes hablar con tu manager IA desde Telegram.")
    log_action("telegram_test_message", {"chat_id_set": True}, "completed")
    return {"sent": True}


def activate_license_now():
    status = activate_license(load_config())
    log_action("license_activate", {"status": status.get("status"), "valid": bool(status.get("valid")), "online": bool(status.get("online"))}, "completed" if status.get("valid") else "blocked")
    return status


def social_command(args, timeout=30):
    config = load_config()
    cmd = [config.social_cli] + args + ["--no-banner"]
    try:
        result = subprocess.run(cmd, cwd=str(ROOT_DIR), text=True, capture_output=True, timeout=timeout)
        output = (result.stdout or "") + (result.stderr or "")
        return {"ok": result.returncode == 0, "code": result.returncode, "command": " ".join(cmd), "output": output[-5000:]}
    except FileNotFoundError:
        return {"ok": False, "code": 127, "command": " ".join(cmd), "output": "social-cli was not found on this machine."}
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or "") + (exc.stderr or "")) if isinstance(exc.stdout, str) else ""
        return {"ok": False, "code": 124, "command": " ".join(cmd), "output": (output + "\nCommand timed out.").strip()}


def social_auth_status():
    result = social_command(["auth", "status"], timeout=15)
    output = result.get("output", "")
    default_match = re.search(r"Ad Account\s+(act_\d+)", output)
    token_ready = bool(re.search(r"facebook\s+READY", output, re.I))
    expired = "expired" in output.lower() or "OAuthException" in output
    return {**result, "facebook_ready": token_ready and not expired, "token_expired": expired, "default_account": default_match.group(1) if default_match else ""}


def social_login_url():
    config = load_config()
    version = config.meta_graph_api_version or "v20.0"
    return {
        "url": f"https://developers.facebook.com/tools/explorer/?version={version}",
        "instructions": {
            "es": "Inicia sesión con Facebook/Meta, genera o copia el token de acceso y pégalo de vuelta en este dashboard.",
            "en": "Log in with Facebook/Meta, generate or copy the access token, and paste it back into this dashboard.",
        },
    }


def social_save_facebook_token(payload):
    token = str(payload.get("token") or "").strip()
    if len(token) < 20:
        raise ValueError("Token is too short")
    update_env_values({"META_ACCESS_TOKEN": token})
    result = social_command(["auth", "login", "--token", token], timeout=30)
    redacted = dict(result)
    redacted["output"] = re.sub(re.escape(token), "[token hidden]", redacted.get("output", ""))
    redacted["saved"] = bool(result.get("ok"))
    return redacted


def graph_get(path, params=None, page_token=""):
    config = load_config()
    token = page_token or config.meta_access_token
    if not token:
        return {"ok": False, "error": "missing_token", "data": None}
    version = config.meta_graph_api_version or "v20.0"
    query = {"access_token": token, **(params or {})}
    url = f"https://graph.facebook.com/{version}/{path.lstrip('/')}?{urllib.parse.urlencode(query)}"
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        return {"ok": True, "data": data}
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8"))
        except Exception:
            data = {"error": str(exc)}
        return {"ok": False, "error": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def graph_error_message(result):
    error = result.get("error") if isinstance(result, dict) else result
    if isinstance(error, dict):
        nested = error.get("error")
        if isinstance(nested, dict):
            return nested.get("message") or json.dumps(nested)[:500]
        return error.get("message") or json.dumps(error)[:500]
    return str(error or "")


def action_metric_value(rows, names):
    names = {str(name).lower() for name in names}
    total = 0.0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        action_type = str(row.get("action_type") or row.get("type") or "").lower()
        if action_type in names or any(action_type.endswith(f".{name}") for name in names):
            try:
                total += float(row.get("value") or 0)
            except (TypeError, ValueError):
                continue
    return total


def normalize_insights_rows(rows, account_id=""):
    campaigns = []
    conversion_actions = {
        "purchase",
        "omni_purchase",
        "offsite_conversion.fb_pixel_purchase",
        "onsite_conversion.purchase",
        "lead",
        "onsite_conversion.lead_grouped",
        "offsite_conversion.fb_pixel_lead",
    }
    purchase_value_actions = {
        "purchase",
        "omni_purchase",
        "offsite_conversion.fb_pixel_purchase",
        "onsite_conversion.purchase",
    }
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        campaign_id = str(row.get("campaign_id") or row.get("id") or "").strip()
        campaign_name = row.get("campaign_name") or row.get("name") or campaign_id or "Campaign"
        spend = money(row.get("spend", 0))
        clicks = int(float(row.get("clicks") or row.get("inline_link_clicks") or 0))
        impressions = int(float(row.get("impressions") or 0))
        actions = row.get("actions") or []
        action_values = row.get("action_values") or []
        conversions = int(round(action_metric_value(actions, conversion_actions)))
        revenue = money(action_metric_value(action_values, purchase_value_actions))
        ctr = float(row.get("ctr") or 0)
        cpc = float(row.get("cpc") or 0)
        frequency = float(row.get("frequency") or 1.0)
        campaign = {
            "id": campaign_id or campaign_name,
            "campaign_id": campaign_id,
            "name": campaign_name,
            "status": str(row.get("effective_status") or row.get("status") or "active").lower(),
            "target_type": "campaign",
            "target_id": campaign_id or campaign_name,
            "daily_budget": money(float(row.get("daily_budget") or 0) / 100) if row.get("daily_budget") else 0,
            "spend": spend,
            "impressions": impressions,
            "clicks": clicks,
            "conversions": conversions,
            "revenue": revenue,
            "frequency": frequency,
            "ctr": ctr,
            "cpc": cpc,
            "previous_ctr": ctr,
            "previous_cpc": cpc,
            "updated_at": now_iso(),
        }
        campaigns.append(campaign)
    return {
        "timestamp": now_iso(),
        "source": "meta_graph",
        "source_label": "Meta Ads real data",
        "account_id": account_id,
        "date_preset": "last_7d",
        "campaigns": campaigns,
        "summary": {},
    }


def fetch_real_metrics(account_id=""):
    config = load_config()
    account_id = str(account_id or config.ad_account_id or "").strip()
    if account_id and not account_id.startswith("act_"):
        account_id = f"act_{account_id}"
    if not account_id:
        return {"ok": False, "reason": "missing_account", "message": "Missing Meta ad account."}
    if not config.meta_access_token:
        return {"ok": False, "reason": "missing_token", "message": "Missing Meta access token."}
    result = graph_get(
        f"/{account_id}/insights",
        {
            "level": "campaign",
            "date_preset": "last_7d",
            "fields": "campaign_id,campaign_name,spend,impressions,clicks,ctr,cpc,frequency,actions,action_values",
            "limit": 100,
        },
    )
    if not result.get("ok"):
        return {"ok": False, "reason": "graph_error", "message": graph_error_message(result), "raw": result.get("error")}
    rows = (result.get("data") or {}).get("data") or []
    metrics = normalize_insights_rows(rows, account_id)
    return {"ok": True, "metrics": metrics, "rows": len(rows), "account_id": account_id}


def refresh_real_metrics(account_id="", reason="manual"):
    result = fetch_real_metrics(account_id)
    if result.get("ok"):
        save_metrics(result["metrics"])
        log_action("live_insights_pull", {"account_id": result.get("account_id"), "rows": result.get("rows"), "reason": reason}, "completed")
        return {"ok": True, "saved": True, "source": "meta_graph", "rows": result.get("rows"), "account_id": result.get("account_id")}
    log_action("live_insights_pull", {"account_id": account_id or load_config().ad_account_id, "reason": reason, "error": result.get("message"), "code": result.get("reason")}, "blocked")
    return {**result, "saved": False}


def normalize_page_asset(row):
    if not isinstance(row, dict):
        return None
    page = {
        "id": str(row.get("id") or "").strip(),
        "name": row.get("name") or "",
        "category": row.get("category") or "",
        "link": row.get("link") or "",
        "website": row.get("website") or "",
        "instagram": None,
    }
    for key in ["instagram_business_account", "connected_instagram_account"]:
        ig = row.get(key)
        if isinstance(ig, dict) and ig.get("id"):
            page["instagram"] = {
                "id": str(ig.get("id")),
                "username": ig.get("username") or ig.get("name") or "",
                "name": ig.get("name") or ig.get("username") or "",
            }
            break
    return page if page["id"] else None


def extract_urls(value):
    urls = []
    if isinstance(value, str):
        urls.extend(re.findall(r"https?://[^\s\"'<>]+", value))
    elif isinstance(value, dict):
        for nested in value.values():
            urls.extend(extract_urls(nested))
    elif isinstance(value, list):
        for nested in value:
            urls.extend(extract_urls(nested))
    cleaned = []
    for url in urls:
        url = url.rstrip(".,);]")
        if url and url not in cleaned:
            cleaned.append(url)
    return cleaned


def social_discover_assets(payload):
    account_id = str(payload.get("ad_account_id") or "").strip() or load_config().ad_account_id
    if account_id and not account_id.startswith("act_"):
        account_id = f"act_{account_id}"
    pages_result = graph_get(
        "/me/accounts",
        {
            "fields": "id,name,category,link,website,access_token,instagram_business_account{id,username,name},connected_instagram_account{id,username,name}",
            "limit": 100,
        },
    )
    pages = []
    for row in (pages_result.get("data") or {}).get("data", []) if pages_result.get("ok") else []:
        page = normalize_page_asset(row)
        if page:
            pages.append(page)

    page_with_ig = next((page for page in pages if page.get("instagram")), None)
    first_page = page_with_ig or (pages[0] if pages else None)
    suggested = {
        "page_id": first_page.get("id", "") if first_page else "",
        "page_name": first_page.get("name", "") if first_page else "",
        "instagram_actor_id": (first_page.get("instagram") or {}).get("id", "") if first_page else "",
        "instagram_username": (first_page.get("instagram") or {}).get("username", "") if first_page else "",
        "landing_url": first_page.get("website", "") if first_page else "",
    }

    urls = []
    ads_result = {"ok": False, "skipped": True}
    if account_id:
        ads_result = graph_get(
            f"/{account_id}/ads",
            {"fields": "creative{object_story_spec,asset_feed_spec,url_tags,link_url}", "limit": 25},
        )
        if ads_result.get("ok"):
            urls = extract_urls(ads_result.get("data"))
            if urls and not suggested["landing_url"]:
                suggested["landing_url"] = urls[0]

    if any(suggested.get(key) for key in ["page_id", "instagram_actor_id", "landing_url"]) and not load_onboarding_state().get("completed"):
        save_setup_config({key: value for key, value in suggested.items() if key in {"page_id", "instagram_actor_id", "landing_url"} and value})

    result = {
        "ok": pages_result.get("ok") or bool(urls),
        "ad_account_id": account_id,
        "pages": pages,
        "urls": urls[:8],
        "suggested": suggested,
        "saved": any(suggested.get(key) for key in ["page_id", "instagram_actor_id", "landing_url"]),
        "needs_page_permissions": not pages_result.get("ok") or not pages,
        "pages_error": pages_result.get("error") if not pages_result.get("ok") else "",
        "ads_error": ads_result.get("error") if isinstance(ads_result, dict) and not ads_result.get("ok") and not ads_result.get("skipped") else "",
    }
    log_action("meta_asset_discovery", redact_payload(result), "completed" if result["ok"] else "warn")
    return result


def extract_json_payload(text):
    text = text.strip()
    for opener, closer in [("[", "]"), ("{", "}")]:
        start = text.find(opener)
        end = text.rfind(closer)
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


def normalize_social_accounts(payload):
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("accounts") or payload.get("items") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    accounts = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_id = str(row.get("account_id") or row.get("id") or row.get("accountId") or "").strip()
        if not raw_id:
            continue
        account_id = raw_id if raw_id.startswith("act_") else f"act_{raw_id}"
        accounts.append({
            "id": account_id,
            "name": row.get("name") or row.get("account_name") or row.get("business_name") or account_id,
            "currency": row.get("currency", ""),
            "status": row.get("account_status", row.get("status", "")),
        })
    return accounts


def social_marketing_accounts():
    result = social_command(["marketing", "accounts", "--json"], timeout=30)
    output = result.get("output", "")
    output_lower = output.lower()
    token_expired = "expired" in output_lower or "oauth" in output_lower or "code: 190" in output_lower or "auth login" in output_lower
    payload = extract_json_payload(output)
    accounts = normalize_social_accounts(payload)
    return {
        **result,
        "accounts": accounts,
        "needs_login": not result.get("ok") and token_expired,
        "token_expired": token_expired,
        "friendly_reason": "token_expired" if token_expired else "",
    }


def social_set_default_account(payload):
    account_id = str(payload.get("ad_account_id") or "").strip()
    if not account_id:
        raise ValueError("Missing ad account")
    if not account_id.startswith("act_"):
        account_id = f"act_{account_id}"
    replace_payload = {"ad_account_id": account_id, "confirm_replace_business": payload.get("confirm_replace_business")}
    enforce_individual_business_change(replace_payload)
    result = social_command(["marketing", "set-default-account", account_id], timeout=20)
    if result.get("ok"):
        save_setup_config(replace_payload)
    return {**result, "ad_account_id": account_id}


def set_dashboard_password(payload):
    password = str(payload.get("password") or "").strip()
    confirm = str(payload.get("confirm_password") or "").strip()
    if len(password) < 8:
        raise ValueError("Dashboard password must have at least 8 characters")
    if confirm and confirm != password:
        raise ValueError("Dashboard password confirmation does not match")
    update_env_values({"DASHBOARD_PASSWORD": password})
    log_action("dashboard_password_set", {"status": "configured"}, "completed")
    return {"configured": True}


def save_setup_config(payload):
    replaced = enforce_individual_business_change(payload)
    env_updates = {}
    text_fields = {
        "license_key": "LICENSE_KEY",
        "license_buyer_email": "LICENSE_BUYER_EMAIL",
        "ad_account_id": "META_AD_ACCOUNT_ID",
    }
    for field, env_key in text_fields.items():
        if field not in payload:
            continue
        value = str(payload.get(field) or "").strip()
        if field == "license_key" and not value:
            continue
        env_updates[env_key] = value
    if env_updates:
        update_env_values(env_updates)

    ad_config = read_json(AD_CONFIG_FILE, {})
    ad_config.setdefault("account", {})
    ad_config.setdefault("creative", {})
    ad_config["creative"].setdefault("destination", {})
    destination = ad_config["creative"]["destination"]
    if "ad_account_id" in payload and str(payload.get("ad_account_id") or "").strip():
        ad_config["account"]["id"] = str(payload.get("ad_account_id")).strip()
    for field, key in {
        "page_id": "page_id",
        "instagram_actor_id": "instagram_actor_id",
        "default_adset_id": "default_adset_id",
        "landing_url": "url",
    }.items():
        if field in payload:
            destination[key] = str(payload.get(field) or "").strip()
    write_json(AD_CONFIG_FILE, ad_config)
    log_action("setup_config_save", {"updated": sorted(list(env_updates.keys()) + ["ad-config.json"]), "business_replaced": replaced}, "completed")
    return {"saved": True, "business_replaced": replaced, "env_updated": sorted(env_updates.keys()), "ad_config": ad_config}


class WebsiteSummaryParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.meta = {}
        self.headings = []
        self.links = []
        self._tag = ""
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self._tag = tag
        self._buffer = []
        if tag == "meta":
            name = (attrs.get("name") or attrs.get("property") or "").lower()
            content = (attrs.get("content") or "").strip()
            if name and content:
                self.meta[name] = content[:500]
        if tag == "a" and attrs.get("href"):
            href = attrs.get("href", "")
            if len(self.links) < 30:
                self.links.append({"href": href[:300], "text": ""})

    def handle_data(self, data):
        if self._tag in {"title", "h1", "h2", "a"}:
            text = re.sub(r"\s+", " ", data or "").strip()
            if text:
                self._buffer.append(text)

    def handle_endtag(self, tag):
        text = " ".join(self._buffer).strip()
        if tag == "title" and text and not self.title:
            self.title = text[:180]
        elif tag in {"h1", "h2"} and text and len(self.headings) < 12:
            self.headings.append(text[:180])
        elif tag == "a" and text and self.links:
            self.links[-1]["text"] = text[:120]
        self._tag = ""
        self._buffer = []


def normalize_website_url(value):
    url = str(value or "").strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, flags=re.I):
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    if not parsed.netloc:
        raise ValueError("Escribe una web valida, por ejemplo https://tumarca.com")
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", parsed.query, ""))


def infer_business_profile(url, parser, context):
    description = parser.meta.get("description") or parser.meta.get("og:description") or ""
    title = parser.title or parser.meta.get("og:title") or ""
    headings = [h for h in parser.headings if len(h) > 3]
    joined = " ".join([title, description, *headings, context]).lower()
    business_type = "negocio online"
    if any(word in joined for word in ["curso", "mentoria", "mentor", "coaching", "academia", "masterclass"]):
        business_type = "infoproducto, curso o mentoría"
    elif any(word in joined for word in ["shop", "tienda", "producto", "carrito", "envio", "ecommerce", "comprar"]):
        business_type = "tienda online o ecommerce"
    elif any(word in joined for word in ["consulta", "servicio", "agenda", "reserva", "abogado", "clinica", "asesoria"]):
        business_type = "servicio local o profesional"
    elif any(word in joined for word in ["software", "app", "saas", "plataforma", "demo"]):
        business_type = "software o plataforma digital"
    offer = headings[0] if headings else title or "oferta principal por definir"
    audience = "personas con intención de comprar o pedir información"
    if "empresa" in joined or "negocio" in joined or "emprendedor" in joined:
        audience = "dueños de negocio, emprendedores o equipos pequeños"
    elif "mujer" in joined or "belleza" in joined or "estetica" in joined:
        audience = "personas interesadas en belleza, cuidado personal o bienestar"
    elif "curso" in joined or "aprende" in joined:
        audience = "personas que quieren aprender o mejorar una habilidad concreta"
    pain = context or "El comprador quiere entender mejor sus anuncios, decidir con menos estrés y mejorar resultados con ayuda del agente."
    angles = [
        f"Claridad: explicar rápido por qué {offer} resuelve un problema concreto.",
        "Confianza: mostrar prueba, experiencia, resultados o garantías antes de pedir la compra.",
        "Acción simple: llevar a una sola decisión clara, sin llenar el anuncio de demasiadas ideas.",
    ]
    plan = [
        "Primero leer datos reales de Meta para no decidir a ciegas.",
        f"Preparar una campaña inicial para {business_type} con 2 o 3 ángulos creativos.",
        "Mantener el primer ciclo con supervisión: el agente recomienda y prepara, el comprador aprueba.",
        "Revisar en la lectura diaria qué sube, qué se cansa y qué conviene escalar.",
    ]
    return {
        "website_url": url,
        "business_type": business_type,
        "offer": offer,
        "audience": audience,
        "current_stage": context[:800],
        "positioning": description or title,
        "detected_title": title,
        "detected_headings": headings[:8],
        "suggested_angles": angles,
        "initial_plan": plan,
        "source": "website_scan_basic",
        "created_at": now_iso(),
    }


def scan_business_website(payload):
    url = normalize_website_url(payload.get("website_url"))
    context = str(payload.get("current_stage") or "").strip()
    if not url:
        raise ValueError("Escribe la web de tu negocio.")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MetaAdsAgentWebsiteScanner/1.0 (+local onboarding)"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read(350000).decode(response.headers.get_content_charset() or "utf-8", errors="ignore")
    except Exception as exc:
        profile = {
            "website_url": url,
            "business_type": "negocio por definir",
            "offer": "oferta por definir",
            "audience": "audiencia por definir",
            "current_stage": context,
            "positioning": "",
            "detected_title": "",
            "detected_headings": [],
            "suggested_angles": [
                "Claridad: explicar la oferta en una frase simple.",
                "Confianza: mostrar prueba o razón para creer.",
                "Acción: llevar a una sola acción clara.",
            ],
            "initial_plan": [
                "Completar la conexión de Meta.",
                "Contarle al agente qué vendes y qué quieres mejorar.",
                "Crear una primera campaña con supervisión.",
            ],
            "source": "manual_context",
            "scan_error": str(exc)[:300],
            "created_at": now_iso(),
        }
    else:
        parser = WebsiteSummaryParser()
        parser.feed(body)
        profile = infer_business_profile(url, parser, context)
    write_json(BUSINESS_PROFILE_FILE, profile)
    save_setup_config({"landing_url": url})
    log_action("business_website_scan", {"website_url": url, "source": profile.get("source"), "scan_error": profile.get("scan_error", "")}, "completed" if not profile.get("scan_error") else "warn")
    return {"saved": True, "profile": profile}


def save_business_context(payload):
    profile = read_json(BUSINESS_PROFILE_FILE, {})
    if not isinstance(profile, dict):
        profile = {}
    for field in ["website_url", "current_stage", "what_to_improve", "main_offer", "ideal_customer"]:
        if field in payload:
            profile[field] = str(payload.get(field) or "").strip()
    if payload.get("website_url"):
        profile["website_url"] = normalize_website_url(payload.get("website_url"))
        save_setup_config({"landing_url": profile["website_url"]})
    if not profile.get("initial_plan"):
        context = " ".join(
            str(profile.get(key) or "")
            for key in ["current_stage", "what_to_improve", "main_offer", "ideal_customer"]
        ).strip()
        profile.update(infer_business_profile(profile.get("website_url", ""), WebsiteSummaryParser(), context))
    profile.setdefault("source", "manual_context")
    profile["updated_at"] = now_iso()
    write_json(BUSINESS_PROFILE_FILE, profile)
    log_action("business_context_save", {"website_url": profile.get("website_url"), "fields": sorted(payload.keys())}, "completed")
    return {"saved": True, "profile": profile}


def initialize_brand_guides(payload):
    product_name = str(payload.get("product_name") or "").strip() or "Oferta principal"
    result = ensure_brand_guides(product_name)
    log_action("brand_guides_init", {"product_name": product_name, "created": result.get("created", [])}, "completed")
    return result


def codex_creative_plan(payload):
    config = load_config()
    if not getattr(config, "codex_creative_enabled", False):
        raise ValueError("La capa opcional de Codex esta desactivada. Actívala solo si aceptas que Codex CLI es un agente local con acceso adicional al equipo.")
    product_guide = str(payload.get("product_guide") or "").strip()
    request = str(payload.get("request") or "").strip()
    if not request:
        request = "Crear una estrategia visual y prompts de imagen para Meta Ads usando las guias de marca."
    try:
        prompt = build_codex_creative_prompt(product_guide, request)
        result = call_codex_cli(prompt)
    except ValueError as exc:
        result = {"ok": False, "error": str(exc)}
    log_action("codex_creative_plan", {"product_guide": product_guide, "ok": result.get("ok"), "error": result.get("error", "")}, "completed" if result.get("ok") else "blocked")
    return result


def load_onboarding_state():
    state = read_json(ONBOARDING_FILE, {})
    if not isinstance(state, dict):
        state = {}
    state.setdefault("completed", False)
    state.setdefault("completed_at", "")
    state.setdefault("completed_by", "")
    state.setdefault("setup_snapshot", {})
    return state


def complete_onboarding():
    config = load_config()
    if not (config.dashboard_password or config.dashboard_token):
        raise ValueError("Create a dashboard password before finishing onboarding")
    license_info = license_status(config)
    if not license_info.get("valid"):
        raise ValueError("No se pudo confirmar tu licencia. Revisa internet o contacta soporte.")
    ad_config = read_json(AD_CONFIG_FILE, {})
    destination = ad_config.get("creative", {}).get("destination", {})
    if not config.meta_access_token:
        raise ValueError("Pega y guarda tu token de Meta antes de terminar.")
    if not config.ad_account_id:
        raise ValueError("Elige tu cuenta publicitaria antes de terminar.")
    if not destination.get("page_id") or not destination.get("url"):
        raise ValueError("Elige tu pagina de Facebook y el link de tu web antes de terminar.")
    business_profile = read_json(BUSINESS_PROFILE_FILE, {})
    if not business_profile.get("website_url") or not (business_profile.get("initial_plan") or business_profile.get("what_to_improve")):
        raise ValueError("Primero deja listo el perfil del negocio y el plan inicial del agente.")
    setup = build_setup_status()
    insights_refresh = refresh_real_metrics(reason="onboarding_complete") if config.ad_account_id and config.meta_access_token else {"ok": False, "saved": False, "reason": "missing_account_or_token"}
    metrics = load_metrics()
    if not insights_refresh.get("ok") and metrics.get("source") != "meta_graph":
        raise ValueError("Todavia no pude leer datos reales de Meta. Actualiza el token o revisa permisos y vuelve a intentar.")
    state = {
        "completed": True,
        "completed_at": now_iso(),
        "completed_by": "dashboard",
        "setup_snapshot": setup.get("summary", {}),
        "first_insights_refresh": redact_payload(insights_refresh),
        "business_profile_snapshot": redact_payload(business_profile),
    }
    write_json(ONBOARDING_FILE, state)
    entitlements = license_entitlements()
    if entitlements["is_agency"]:
        registry = agency_registry()
        if not registry["spaces"]:
            name = business_profile.get("detected_title") or business_profile.get("main_offer") or "Cliente principal"
            space = {"id": workspace_slug(name), "name": str(name)[:80], "created_at": now_iso()}
            registry["spaces"].append(space)
            registry["active_id"] = space["id"]
            write_json(AGENCY_SPACES_FILE, registry)
        elif not registry.get("active_id"):
            registry["active_id"] = registry["spaces"][0]["id"]
            write_json(AGENCY_SPACES_FILE, registry)
        snapshot_workspace(registry["active_id"])
    else:
        save_individual_binding()
    log_action("onboarding_complete", {"setup_summary": state["setup_snapshot"], "first_insights_refresh": state["first_insights_refresh"]}, "completed")
    return state


def reset_onboarding():
    if load_onboarding_state().get("completed") and not license_entitlements()["is_agency"]:
        save_individual_binding()
    state = {
        "completed": False,
        "completed_at": "",
        "completed_by": "",
        "setup_snapshot": {},
        "reset_at": now_iso(),
    }
    write_json(ONBOARDING_FILE, state)
    log_action("onboarding_reset", {}, "completed")
    return state


def onboarding_health(state, config, metrics, current_license_status, destination, business_profile):
    """Guide a completed legacy install back through setup if its real connection is gone."""
    result = dict(state)
    result["requires_repair"] = False
    result["repair_reasons"] = []
    if not result.get("completed"):
        return result
    checks = [
        (current_license_status.get("valid"), "licencia"),
        (bool(config.meta_access_token), "conexion_meta"),
        (bool(config.ad_account_id), "cuenta_publicitaria"),
        (bool(destination.get("page_id")) and bool(destination.get("url")), "destinos"),
        (bool(business_profile.get("website_url")), "perfil_negocio"),
        (metrics.get("source") == "meta_graph", "datos_reales"),
    ]
    result["repair_reasons"] = [reason for ready, reason in checks if not ready]
    result["requires_repair"] = bool(result["repair_reasons"])
    return result


def money(value):
    return round(float(value or 0), 2)


def pct_change(current, previous):
    current = float(current or 0)
    previous = float(previous or 0)
    if previous == 0:
        return 0.0
    return ((current - previous) / previous) * 100


def sample_metrics():
    today = now_iso()
    campaigns = [
        {
            "id": "camp_001",
            "name": "Q2 Conversion Campaign",
            "status": "active",
            "daily_budget": 180,
            "spend": 1500,
            "impressions": 450000,
            "clicks": 15000,
            "conversions": 450,
            "revenue": 9000,
            "frequency": 2.1,
            "cpc": 0.10,
            "previous_ctr": 3.05,
            "previous_cpc": 0.11,
            "trend": [4.8, 5.1, 5.4, 5.2, 5.7, 6.1, 6.0],
            "updated_at": today,
        },
        {
            "id": "camp_002",
            "name": "Brand Awareness Campaign",
            "status": "active",
            "daily_budget": 120,
            "spend": 800,
            "impressions": 250000,
            "clicks": 5000,
            "conversions": 100,
            "revenue": 4000,
            "frequency": 3.4,
            "cpc": 0.16,
            "previous_ctr": 2.8,
            "previous_cpc": 0.11,
            "trend": [5.8, 5.5, 5.2, 4.9, 4.8, 5.0, 5.0],
            "updated_at": today,
        },
        {
            "id": "camp_003",
            "name": "Retargeting - Warm Leads",
            "status": "active",
            "daily_budget": 90,
            "spend": 920,
            "impressions": 96000,
            "clicks": 4600,
            "conversions": 230,
            "revenue": 7360,
            "frequency": 2.7,
            "cpc": 0.20,
            "previous_ctr": 4.1,
            "previous_cpc": 0.21,
            "trend": [6.4, 6.7, 7.0, 7.3, 7.6, 7.9, 8.0],
            "updated_at": today,
        },
        {
            "id": "camp_004",
            "name": "Prospecting - Broad Testing",
            "status": "active",
            "daily_budget": 150,
            "spend": 640,
            "impressions": 180000,
            "clicks": 1980,
            "conversions": 6,
            "revenue": 420,
            "frequency": 1.5,
            "cpc": 0.32,
            "previous_ctr": 1.25,
            "previous_cpc": 0.26,
            "trend": [1.1, 1.0, 0.9, 0.8, 0.7, 0.64, 0.66],
            "updated_at": today,
        },
    ]
    return {
        "timestamp": today,
        "source": "demo",
        "source_label": "Demo data",
        "campaigns": [enrich_campaign(c) for c in campaigns],
        "summary": {},
    }


def looks_like_demo_metrics(metrics):
    if not isinstance(metrics, dict):
        return False
    ids = {str(c.get("id") or "") for c in metrics.get("campaigns", []) if isinstance(c, dict)}
    names = {str(c.get("name") or "") for c in metrics.get("campaigns", []) if isinstance(c, dict)}
    return bool({"camp_001", "camp_002", "camp_003", "camp_004"} & ids) or "Q2 Conversion Campaign" in names


def enrich_campaign(campaign):
    campaign = dict(campaign)
    spend = float(campaign.get("spend", 0))
    clicks = int(campaign.get("clicks", 0))
    impressions = int(campaign.get("impressions", 0))
    conversions = int(campaign.get("conversions", 0))
    revenue = float(campaign.get("revenue", 0))
    campaign.setdefault("daily_budget", 100)
    campaign.setdefault("frequency", 1.0)
    campaign["ctr"] = (clicks / impressions * 100) if impressions else float(campaign.get("ctr", 0))
    campaign["cpa"] = (spend / conversions) if conversions else float(campaign.get("cpa", 0) or 9999)
    campaign["cpc"] = (spend / clicks) if clicks else float(campaign.get("cpc", 0))
    campaign["roas"] = (revenue / spend) if spend else float(campaign.get("roas", 0))
    campaign.setdefault("previous_ctr", campaign["ctr"] * 1.05)
    campaign.setdefault("previous_cpc", campaign["cpc"] * 0.92 if campaign["cpc"] else 0)
    campaign.setdefault("trend", [round(campaign["roas"] * v, 2) for v in [0.82, 0.88, 0.93, 0.96, 1.0, 1.03, 1.0]])
    campaign.setdefault("updated_at", now_iso())
    campaign["health"] = classify_campaign(campaign)
    return campaign


def classify_campaign(campaign):
    if campaign.get("status") == "paused":
        return "paused"
    ctr_drop = pct_change(campaign.get("ctr"), campaign.get("previous_ctr"))
    cpc_rise = pct_change(campaign.get("cpc"), campaign.get("previous_cpc"))
    if campaign.get("frequency", 0) > 3.0 or ctr_drop <= -20 or cpc_rise >= 30:
        return "fatigue"
    if campaign.get("roas", 0) >= 3 and campaign.get("cpa", 9999) <= TARGET_CPA:
        return "winning"
    if campaign.get("roas", 0) < 1.2 or campaign.get("cpa", 0) > TARGET_CPA * 3:
        return "losing"
    return "neutral"


def load_metrics():
    metrics = read_json(METRICS_FILE, None)
    if metrics is None:
        metrics = sample_metrics()
    if "source" not in metrics and looks_like_demo_metrics(metrics):
        metrics["source"] = "demo"
        metrics["source_label"] = "Demo data"
    metrics.setdefault("source", "cached")
    metrics.setdefault("source_label", "Cached dashboard data")
    metrics["campaigns"] = [enrich_campaign(c) for c in metrics.get("campaigns", [])]
    metrics["summary"] = build_summary(metrics["campaigns"])
    return metrics


def save_metrics(metrics):
    metrics["timestamp"] = now_iso()
    metrics.setdefault("source", "manual")
    metrics.setdefault("source_label", "Dashboard data")
    metrics["campaigns"] = [enrich_campaign(c) for c in metrics.get("campaigns", [])]
    metrics["summary"] = build_summary(metrics["campaigns"])
    write_json(METRICS_FILE, metrics)


def build_summary(campaigns):
    spend = sum(float(c.get("spend", 0)) for c in campaigns)
    revenue = sum(float(c.get("revenue", 0)) for c in campaigns)
    clicks = sum(int(c.get("clicks", 0)) for c in campaigns)
    impressions = sum(int(c.get("impressions", 0)) for c in campaigns)
    conversions = sum(int(c.get("conversions", 0)) for c in campaigns)
    budget = sum(float(c.get("daily_budget", 0)) for c in campaigns if c.get("status") != "paused")
    return {
        "total_spend": money(spend),
        "total_revenue": money(revenue),
        "total_impressions": impressions,
        "total_clicks": clicks,
        "total_conversions": conversions,
        "overall_roas": round(revenue / spend, 2) if spend else 0,
        "overall_ctr": round(clicks / impressions * 100, 2) if impressions else 0,
        "overall_cpa": money(spend / conversions) if conversions else 0,
        "active_budget": money(budget),
        "active_campaigns": len([c for c in campaigns if c.get("status") == "active"]),
    }


def calculate_recommendations(campaigns):
    optimizer = BudgetOptimizer()
    recommendations = []
    for campaign in campaigns:
        metrics = PerformanceMetrics(
            spend=float(campaign.get("spend", 0)),
            impressions=int(campaign.get("impressions", 0)),
            clicks=int(campaign.get("clicks", 0)),
            conversions=int(campaign.get("conversions", 0)),
            revenue=float(campaign.get("revenue", 0)),
            cost_per_result=float(campaign.get("cpa", 0)),
            roas=float(campaign.get("roas", 0)),
        )
        current_budget = float(campaign.get("daily_budget", 100))
        rec = optimizer.calculate_optimal_budget(metrics, current_budget, OptimizationStrategy.PERFORMANCE_BASED)
        change = rec.recommended_budget - current_budget
        change_pct = (change / current_budget * 100) if current_budget else 0
        recommendations.append(
            {
                "campaign_id": campaign.get("id"),
                "campaign_name": campaign.get("name"),
                "current_budget": money(current_budget),
                "recommended_budget": money(rec.recommended_budget),
                "change": money(change),
                "change_pct": round(change_pct, 1),
                "confidence": round(float(rec.confidence), 1),
                "reason": rec.reasoning,
                "requires_approval": abs(change_pct) > 20,
                "roas": round(campaign.get("roas", 0), 2),
                "health": campaign.get("health"),
            }
        )
    return recommendations


def fatigue_items(campaigns):
    items = []
    for campaign in campaigns:
        ctr_drop = pct_change(campaign.get("ctr"), campaign.get("previous_ctr"))
        cpc_rise = pct_change(campaign.get("cpc"), campaign.get("previous_cpc"))
        reasons = []
        if campaign.get("frequency", 0) > 3:
            reasons.append(f"frequency {campaign.get('frequency'):.1f}")
        if ctr_drop <= -20:
            reasons.append(f"CTR {abs(ctr_drop):.0f}% down")
        if cpc_rise >= 30:
            reasons.append(f"CPC {cpc_rise:.0f}% up")
        if reasons:
            items.append(
                {
                    "campaign_id": campaign.get("id"),
                    "campaign_name": campaign.get("name"),
                    "severity": "high" if len(reasons) > 1 else "medium",
                    "reasons": reasons,
                    "frequency": campaign.get("frequency", 0),
                    "ctr_change": round(ctr_drop, 1),
                    "cpc_change": round(cpc_rise, 1),
                }
            )
    return items


def build_daily_brief(metrics, recommendations):
    campaigns = metrics.get("campaigns", [])
    summary = metrics.get("summary", {})
    active = [c for c in campaigns if c.get("status") == "active"]
    winners = sorted([c for c in campaigns if c.get("health") == "winning"], key=lambda c: c.get("roas", 0), reverse=True)
    losers = sorted([c for c in campaigns if c.get("health") == "losing"], key=lambda c: c.get("roas", 0))
    fatigue = fatigue_items(campaigns)
    projected_spend = summary.get("active_budget", 0)
    return {
        "generated_at": now_iso(),
        "questions": [
            {
                "question": "Am I on track?",
                "answer": f"Active daily budget is ${projected_spend:,.2f}; account ROAS is {summary.get('overall_roas', 0):.2f}x with CPA ${summary.get('overall_cpa', 0):,.2f}.",
            },
            {
                "question": "What's running?",
                "answer": f"{len(active)} active campaigns, {len(campaigns) - len(active)} paused or staged.",
            },
            {
                "question": "How's performance?",
                "answer": f"7-day view shows ${summary.get('total_spend', 0):,.2f} spend, ${summary.get('total_revenue', 0):,.2f} revenue, {summary.get('total_conversions', 0):,} conversions, and {summary.get('overall_ctr', 0):.2f}% CTR.",
            },
            {
                "question": "Who's winning/losing?",
                "answer": f"Top winner: {winners[0]['name']} at {winners[0]['roas']:.2f}x ROAS." if winners else "No clear winner yet.",
            },
            {
                "question": "Any fatigue?",
                "answer": f"{len(fatigue)} campaign(s) show fatigue signals." if fatigue else "No material fatigue triggers right now.",
            },
        ],
        "winners": [{"name": c["name"], "roas": round(c["roas"], 2), "cpa": money(c["cpa"])} for c in winners[:4]],
        "losers": [{"name": c["name"], "roas": round(c["roas"], 2), "cpa": money(c["cpa"])} for c in losers[:4]],
        "pending_actions": [r for r in recommendations if r["requires_approval"]],
    }


def latest_daily_report():
    reports = sorted(OUTPUT_DIR.glob("daily_brief_*.json"), reverse=True)
    for path in reports:
        report = read_json(path, None)
        if isinstance(report, dict) and isinstance(report.get("brief"), dict):
            report["_path"] = str(path)
            return report
    return None


def scheduled_brief_or_live(metrics, recommendations):
    report = latest_daily_report()
    if not report:
        return build_daily_brief(metrics, recommendations)
    brief = report.get("brief", {})
    five = brief.get("five_questions", {})
    questions = [
        ("Am I on track?", five.get("am_i_on_track")),
        ("What's running?", five.get("whats_running")),
        ("How's performance?", five.get("hows_performance")),
        ("Who's winning/losing?", five.get("winning_losing")),
        ("Any fatigue?", five.get("fatigue")),
    ]
    fallback = build_daily_brief(metrics, recommendations)
    return {
        "generated_at": brief.get("generated_at") or report.get("generated_at") or now_iso(),
        "source": "scheduled_daily_agent",
        "report_path": report.get("_path"),
        "questions": [
            {"question": question, "answer": answer or fallback["questions"][idx]["answer"]}
            for idx, (question, answer) in enumerate(questions)
        ],
        "winners": [{"name": c.get("name"), "roas": round(c.get("roas", 0), 2), "cpa": money(c.get("cpa", 0))} for c in brief.get("winners", [])[:4]],
        "losers": [{"name": c.get("name"), "roas": round(c.get("roas", 0), 2), "cpa": money(c.get("cpa", 0))} for c in brief.get("losers", [])[:4]],
        "pending_actions": [r for r in brief.get("recommendations", []) if r.get("requires_approval")],
    }


def log_action(action_type, payload, status="completed"):
    actions = read_json(ACTIONS_FILE, [])
    record = {"id": f"act_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}", "type": action_type, "status": status, "payload": redact_payload(payload), "created_at": now_iso()}
    actions.insert(0, record)
    write_json(ACTIONS_FILE, actions[:200])
    return record


def add_pending(action_type, payload):
    pending = read_json(PENDING_FILE, [])
    record = {"id": f"approval_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}", "type": action_type, "status": "pending", "payload": payload, "created_at": now_iso()}
    pending.insert(0, record)
    write_json(PENDING_FILE, pending[:100])
    log_action(action_type, payload, "pending_approval")
    return record


def campaign_by_id(metrics, campaign_id):
    for campaign in metrics.get("campaigns", []):
        if campaign.get("id") == campaign_id:
            return campaign
    return None


def should_stage_action(config, action_type, payload):
    if config.autonomy_mode == "supervised" or not config.live or not config.live_actions_enabled:
        return True, "supervised_mode"
    if action_type == "pause_campaign":
        return float(payload.get("spend", 0) or 0) > config.auto_pause_max_spend, "pause_spend_over_limit"
    if action_type == "budget_change":
        return (
            abs(float(payload.get("change_pct", 0) or 0)) > config.auto_budget_change_pct
            or abs(float(payload.get("new_budget", 0) or 0) - float(payload.get("current_budget", 0) or 0)) > config.auto_budget_change_amount
            or abs(float(payload.get("change_pct", 0) or 0)) > config.approval_required_over_pct
        ), "budget_over_autopilot_limit"
    if action_type == "resume_campaign":
        return config.require_approval_for_resume, "resume_requires_approval"
    if action_type == "create_campaign":
        return config.require_approval_for_new_campaigns, "new_campaign_requires_approval"
    if action_type in {"creative_upload", "create_ad", "create_creative"}:
        return config.require_approval_for_creatives, "creative_requires_approval"
    return False, "within_rules"


def execute_autopilot_action(config, action_type, campaign, action_payload):
    require_cloud_license(f"{action_type} requires an active license")
    client = SocialFlowClient(config)
    target_type = campaign.get("target_type", "campaign")
    target_id = campaign.get("target_id", campaign.get("id"))
    if action_type == "pause_campaign":
        result = client.pause(target_type, target_id)
    elif action_type == "resume_campaign":
        result = client.resume(target_type, target_id)
    elif action_type == "budget_change":
        result = client.set_budget(target_type, target_id, int(float(action_payload.get("new_budget", 0)) * 100))
    else:
        raise ValueError("Unsupported automatic action")
    action_payload["connector"] = "social_cli"
    action_payload["result"] = result
    action_payload["executed"] = bool(result.get("executed") and result.get("returncode") == 0)
    if not action_payload["executed"]:
        log_action(action_type, action_payload, "failed")
        raise ValueError("No pude confirmar el cambio en Meta. La cuenta no fue marcada como modificada; revisa conexión y permisos.")
    return action_payload


def apply_action(payload):
    config = load_config()
    action = payload.get("action")
    if action == "refresh_insights":
        return refresh_real_metrics(reason="dashboard_action")
    metrics = load_metrics()
    campaign_id = payload.get("campaign_id")
    campaign = campaign_by_id(metrics, campaign_id)
    if action in {"pause", "resume", "adjust_budget", "apply_recommendation"} and not campaign:
        raise ValueError("Campaign not found")

    if action == "pause":
        action_payload = {"campaign_id": campaign_id, "name": campaign.get("name"), "spend": campaign.get("spend", 0)}
        stage, reason = should_stage_action(config, "pause_campaign", action_payload)
        if stage:
            action_payload["guardrail_reason"] = reason
            return add_pending("pause_campaign", action_payload)
        execute_autopilot_action(config, "pause_campaign", campaign, action_payload)
        campaign["status"] = "paused"
        save_metrics(metrics)
        return log_action("pause_campaign", action_payload, "completed")

    if action == "resume":
        action_payload = {"campaign_id": campaign_id, "name": campaign.get("name")}
        stage, reason = should_stage_action(config, "resume_campaign", action_payload)
        if stage:
            action_payload["guardrail_reason"] = reason
            return add_pending("resume_campaign", action_payload)
        execute_autopilot_action(config, "resume_campaign", campaign, action_payload)
        campaign["status"] = "active"
        save_metrics(metrics)
        return log_action("resume_campaign", action_payload, "completed")

    if action in {"adjust_budget", "apply_recommendation"}:
        current = float(campaign.get("daily_budget", 0))
        new_budget = float(payload.get("new_budget", current))
        change_pct = abs((new_budget - current) / current * 100) if current else 100
        action_payload = {"campaign_id": campaign_id, "name": campaign.get("name"), "current_budget": current, "new_budget": new_budget, "change_pct": round(change_pct, 1)}
        stage, reason = should_stage_action(config, "budget_change", action_payload)
        if stage:
            action_payload["guardrail_reason"] = reason
            return add_pending("budget_change", action_payload)
        execute_autopilot_action(config, "budget_change", campaign, action_payload)
        campaign["daily_budget"] = money(new_budget)
        save_metrics(metrics)
        return log_action("budget_change", action_payload, "completed")

    if action == "run_agent":
        return run_daily_agent()

    raise ValueError("Unsupported action")


def create_campaign(payload):
    final_status = str(payload.get("final_status") or "ACTIVE").strip().upper()
    if final_status not in {"PAUSED", "ACTIVE"}:
        final_status = "ACTIVE"
    active_confirmed = str(payload.get("active_spend_confirmed") or "").strip().lower() in {"1", "true", "yes", "on", "si", "sí"}
    if final_status == "ACTIVE" and not active_confirmed:
        raise ValueError("Para dejar anuncios activos debes marcar: Sí, crear y dejar activo.")
    creator = CampaignCreator()
    interests = [item.strip() for item in str(payload.get("interests", "")).split(",") if item.strip()]
    locations = [item.strip().upper() for item in str(payload.get("locations", "US")).split(",") if item.strip()]
    audience = creator.create_audience_targeting(
        locations=locations or ["US"],
        age_min=int(payload.get("age_min", 18)),
        age_max=int(payload.get("age_max", 65)),
        interests=interests,
    )
    campaign = creator.create_campaign_config(
        name=payload.get("name", "New Campaign"),
        objective=payload.get("objective", "PURCHASES"),
        budget_daily=float(payload.get("daily_budget", 50)),
        budget_total=float(payload.get("total_budget", 1500)),
        pixel_id=payload.get("pixel_id") or None,
        ad_sets=[creator.create_ad_set_config(f"{payload.get('name', 'New Campaign')} - Core", audience, float(payload.get("total_budget", 1500)) / 3)],
    )
    campaign["id"] = creator.generate_campaign_id(campaign)
    campaign["ab_test"] = {
        "enabled": bool(payload.get("ab_test")),
        "creative_variations": int(payload.get("creative_variations", 3)),
    }
    campaign["ad"] = {
        "primary_text": str(payload.get("primary_text") or "").strip(),
        "headline": str(payload.get("headline") or payload.get("name") or "Nueva oferta").strip(),
        "creative_image_path": str(payload.get("creative_image_path") or "").strip(),
        "landing_url": str(payload.get("landing_url") or "").strip(),
        "cta": str(payload.get("cta") or "LEARN_MORE").strip().upper(),
        "final_status": final_status,
        "active_spend_confirmed": active_confirmed,
    }
    out_path = OUTPUT_DIR / f"{campaign['id']}.json"
    creator.save_campaign(campaign, str(out_path))
    created = read_json(CREATED_FILE, [])
    created.insert(0, {"created_at": now_iso(), "path": str(out_path), "campaign": campaign})
    write_json(CREATED_FILE, created[:100])
    pending_payload = {
        "campaign_id": campaign["id"],
        "name": campaign["name"],
        "path": str(out_path),
        "final_status": final_status,
        "active_spend_confirmed": active_confirmed,
        "requested": {
            "campaign": campaign["name"],
            "daily_budget": campaign["budget"]["daily"],
            "objective": campaign["objective"],
            "ad_sets": [adset.get("name") for adset in campaign.get("ad_sets", [])],
            "creative_image_path": campaign["ad"]["creative_image_path"],
        },
        "guardrail_reason": "new_campaigns_always_require_approval",
    }
    return add_pending("create_campaign", pending_payload)


def create_audience_strategy(payload, language="es"):
    strategy = build_audience_strategy(payload, language)
    write_json(AUDIENCE_FILE, strategy)
    log_action("audience_strategy", {"product": strategy.get("product"), "objective": strategy.get("objective")}, "completed")
    return strategy


def run_daily_agent():
    config = load_config()
    if config.ad_account_id and config.meta_access_token:
        refresh_real_metrics(reason="daily_agent_before_brief")
    report_path, report = run_scheduled_daily()
    actions = read_json(ACTIONS_FILE, [])
    action = actions[0] if actions else log_action("daily_agent_run", {"report_path": str(report_path)}, "completed")
    return action, report


def export_csv():
    metrics = load_metrics()
    out_path = OUTPUT_DIR / f"campaign_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fields = ["id", "name", "status", "daily_budget", "spend", "revenue", "roas", "cpa", "ctr", "frequency", "health"]
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for campaign in metrics.get("campaigns", []):
            writer.writerow({field: campaign.get(field) for field in fields})
    log_action("export_csv", {"path": str(out_path)})
    return {"path": str(out_path)}


def chat_lang(payload):
    return "es" if payload.get("language") == "es" else "en"


def chat_reply(payload, es, en):
    return es if chat_lang(payload) == "es" else en


def load_chat_history():
    items = read_json(CHAT_HISTORY_FILE, [])
    if not isinstance(items, list):
        return []
    history = []
    for item in items[-CHAT_HISTORY_LIMIT:]:
        if not isinstance(item, dict):
            continue
        role = "agent" if item.get("role") == "agent" else "user"
        content = str(item.get("content") or "").strip()
        if content:
            history.append({"role": role, "content": content[:5000], "created_at": item.get("created_at") or now_iso()})
    return history


def save_chat_history(history):
    cleaned = []
    for item in history[-CHAT_HISTORY_LIMIT:]:
        if not isinstance(item, dict):
            continue
        role = "agent" if item.get("role") == "agent" else "user"
        content = str(item.get("content") or "").strip()
        if content:
            cleaned.append({"role": role, "content": content[:5000], "created_at": item.get("created_at") or now_iso()})
    write_json(CHAT_HISTORY_FILE, cleaned)
    return cleaned


def append_chat_turn(message, reply):
    history = load_chat_history()
    if message:
        history.append({"role": "user", "content": str(message), "created_at": now_iso()})
    if reply:
        history.append({"role": "agent", "content": str(reply), "created_at": now_iso()})
    return save_chat_history(history)


def reset_chat_history():
    save_chat_history([])
    log_action("chat_new_conversation", {"cleared": True}, "completed")
    return {"cleared": True}


def normalize_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def text_has_any(text, terms):
    padded = f" {text} "
    for term in terms:
        normalized = normalize_text(term)
        if re.search(rf"(?<![\wáéíóúñ]){re.escape(normalized)}(?![\wáéíóúñ])", padded):
            return True
    return False


def find_campaign_for_text(text, metrics):
    campaigns = metrics.get("campaigns", [])
    if not campaigns:
        return None, "no_campaigns"
    for campaign in campaigns:
        if normalize_text(campaign.get("id")) and normalize_text(campaign.get("id")) in text:
            return campaign, ""
    scored = []
    for campaign in campaigns:
        name = normalize_text(campaign.get("name"))
        words = [word for word in re.split(r"[^a-z0-9áéíóúñ]+", name) if len(word) >= 4]
        score = sum(1 for word in words if word in text)
        if score:
            scored.append((score, campaign))
    if scored:
        scored.sort(key=lambda item: item[0], reverse=True)
        if len(scored) == 1 or scored[0][0] > scored[1][0]:
            return scored[0][1], ""
    if any(word in text for word in ["ganadora", "winner", "winning"]):
        winners = sorted([c for c in campaigns if c.get("health") == "winning"], key=lambda c: c.get("roas", 0), reverse=True)
        if winners:
            return winners[0], ""
    if any(word in text for word in ["perdedora", "loser", "losing"]):
        losers = sorted([c for c in campaigns if c.get("health") == "losing"], key=lambda c: c.get("roas", 0))
        if losers:
            return losers[0], ""
    if "fatiga" in text or "fatigue" in text:
        fatigued = [c for c in campaigns if c.get("health") == "fatigue"]
        if fatigued:
            return fatigued[0], ""
    return None, "ambiguous_campaign"


def parse_budget_request(text, campaign):
    percent = re.search(r"(\d+(?:[.,]\d+)?)\s*%", text)
    current = float(campaign.get("daily_budget", 0) or 0)
    if percent and current:
        pct = float(percent.group(1).replace(",", "."))
        direction = -1 if any(word in text for word in ["baja", "bajar", "reduce", "lower", "decrease"]) else 1
        return round(current * (1 + direction * pct / 100), 2)
    money_match = re.search(r"(?:\$|usd\s*)?(\d+(?:[.,]\d+)?)", text)
    if money_match:
        return float(money_match.group(1).replace(",", "."))
    return None


def extract_adset_id(text):
    match = re.search(r"\b(?:act_)?(\d{6,})\b", text or "")
    if not match:
        return ""
    return match.group(1)


def extract_url(text):
    match = re.search(r"https?://[^\s\"'<>]+", text or "")
    return match.group(0).rstrip(".,);]") if match else ""


def extract_image_path(text):
    match = re.search(r"(?:/|~\/)[^\s\"'<>]+\.(?:png|jpg|jpeg|webp)", text or "", flags=re.I)
    return match.group(0).rstrip(".,);]") if match else ""


def parse_campaign_creation_payload(text, payload):
    product = ""
    match = re.search(r"(?:campaña|campana|anuncios|ads)\s+(?:para|de)\s+(.+?)(?:\s+con\s+|\s+en\s+|\s+presupuesto|\s+https?://|$)", text, flags=re.I)
    if match:
        product = match.group(1).strip(" .,:;")
    budget_match = re.search(r"(?:presupuesto|budget|diario|daily|con)\s*(?:de)?\s*\$?\s*(\d+(?:[.,]\d+)?)", text, flags=re.I)
    budget = float(budget_match.group(1).replace(",", ".")) if budget_match else 0
    url = extract_url(payload.get("message", ""))
    image_path = extract_image_path(payload.get("message", ""))
    final_status = "ACTIVE" if text_has_any(text, ["activo", "activa", "active", "encendida", "encendido"]) else "PAUSED"
    confirmed = "sí, crear y dejar activo" in text or "si, crear y dejar activo" in text or "crear y dejar activo" in text
    return {
        "name": f"{product.title()} - Ventas" if product else "",
        "product": product,
        "objective": "PURCHASES",
        "daily_budget": budget,
        "total_budget": budget * 30 if budget else 0,
        "locations": "MX, CO, CL",
        "interests": "",
        "age_min": 18,
        "age_max": 65,
        "primary_text": f"Hice el analisis y esta oferta esta lista para probarse: {product}." if product else "",
        "headline": product.title() if product else "",
        "landing_url": url,
        "creative_image_path": image_path,
        "final_status": final_status,
        "active_spend_confirmed": confirmed,
    }


def route_chat_action(payload):
    message = payload.get("message", "")
    text = normalize_text(message)
    if not text:
        return None
    metrics = load_metrics()
    setup = build_setup_status()
    wants_pause = text_has_any(text, ["pausa", "pausar", "pause", "detén", "detener"])
    wants_resume = text_has_any(text, ["reactiva", "reactivar", "resume", "activar de nuevo"])
    wants_budget = text_has_any(text, ["sube", "subir", "aumenta", "aumentar", "reduce", "reducir", "baja", "bajar", "pon", "poner", "cambia", "cambiar", "set budget", "increase budget", "decrease budget", "lower budget"])
    wants_creative = text_has_any(text, ["creativo", "creativa", "creative", "imagen", "refresh", "renovar"])
    wants_daily = text_has_any(text, ["ejecuta el agente", "corre el agente", "run daily", "daily check", "revisión diaria", "revision diaria"])
    wants_export = text_has_any(text, ["exporta", "exportar", "csv", "reporte csv", "export"])
    wants_approve = text_has_any(text, ["aprueba", "aprobar", "approve"])
    wants_create_campaign = text_has_any(text, ["crea una campaña", "crear una campaña", "crea campaña", "crear campaña", "lanzar anuncios", "lanza anuncios", "prepara una campaña", "campaña de ventas", "haz una campaña", "create campaign", "launch ads"])
    wants_live_gap = any(phrase in text for phrase in ["qué falta para pasar a live", "que falta para pasar a live", "qué falta para pasar live", "que falta para pasar live", "what is missing to go live", "what blocks live"])
    mentions_adset = text_has_any(text, ["adset", "ad set", "grupo de anuncios", "conjunto de anuncios"])

    if wants_approve:
        return {
            "ok": True,
            "provider": "local-action-router",
            "fallback": False,
            "routed_action": {"type": "approval_guardrail", "executed": False},
            "reply": chat_reply(payload, "Por seguridad, no apruebo acciones reales desde el chat. Abre la cola de aprobaciones o usa el botón exacto de Telegram para confirmar esa decisión.", "For safety, I do not approve real account changes from chat. Open the approval queue or use the exact Telegram button to confirm that decision."),
        }

    if mentions_adset:
        adset_id = extract_adset_id(text)
        if adset_id:
            result = save_setup_config({"default_adset_id": adset_id})
            return {
                "ok": True,
                "provider": "local-action-router",
                "fallback": False,
                "routed_action": {"type": "save_existing_adset", "executed": True, "default_adset_id": adset_id, "result": result},
                "reply": chat_reply(payload, f"Listo. Guardé ese grupo de anuncios existente ({adset_id}) para usarlo solo cuando quieras poner anuncios nuevos dentro de esa estructura.", f"Done. I saved that existing ad set ({adset_id}) for cases where you want new ads placed inside that structure."),
            }
        return {
            "ok": True,
            "provider": "local-action-router",
            "fallback": False,
            "routed_action": {"type": "guide_existing_adset", "executed": False},
            "reply": chat_reply(
                payload,
                "Eso es opcional. Solo lo necesito si ya tienes un grupo de anuncios creado y quieres que ponga anuncios nuevos ahí. Para encontrarlo: abre Meta Ads Manager, entra a la campaña, toca el grupo de anuncios y copia el número largo que aparece en la URL o en la columna ID. Si no tienes uno, seguimos creando la estructura desde cero.",
                "That is optional. I only need it if you already have an ad set and want new ads placed there. To find it: open Meta Ads Manager, enter the campaign, select the ad set, and copy the long number from the URL or ID column. If you do not have one, we continue by creating the structure from scratch.",
            ),
        }

    if wants_live_gap:
        blockers = []
        for section in setup.get("sections", []):
            for item in section.get("items", []):
                if item.get("status") in {"blocked", "warn"}:
                    blockers.append(item)
        top = blockers[:3]
        if chat_lang(payload) == "es":
            detail = "; ".join(f"{item.get('label')}: {item.get('detail')}" for item in top) or "no veo bloqueos principales"
            reply = f"Para activar piloto automático con calma, atiende esto primero: {detail}. Después corre una revisión con supervisión, revisa la cola de aprobaciones y recién ahí activa piloto automático."
        else:
            detail = "; ".join(f"{item.get('label')}: {item.get('detail')}" for item in top) or "I do not see major blockers"
            reply = f"To enable autopilot calmly, handle this first: {detail}. Then run one supervised check, review the approval queue, and only then enable autopilot."
        return {
            "ok": True,
            "provider": "local-action-router",
            "fallback": False,
            "routed_action": {"type": "live_readiness_review", "executed": False, "blocker_count": len(blockers)},
            "reply": reply,
        }

    if wants_create_campaign:
        draft = parse_campaign_creation_payload(text, payload)
        missing = []
        if not draft.get("product"):
            missing.append("producto u oferta")
        if not draft.get("daily_budget"):
            missing.append("presupuesto diario")
        if not draft.get("landing_url"):
            missing.append("link de destino")
        if not draft.get("creative_image_path"):
            missing.append("ruta de imagen creativa")
        if draft.get("final_status") == "ACTIVE" and not draft.get("active_spend_confirmed"):
            missing.append("confirmación exacta: Sí, crear y dejar activo")
        if missing:
            first = missing[0]
            questions = {
                "producto u oferta": "¿Qué producto u oferta quieres anunciar?",
                "presupuesto diario": "¿Qué presupuesto diario quieres usar para esta campaña?",
                "link de destino": "¿A qué link debe mandar el anuncio?",
                "ruta de imagen creativa": "Pásame la ruta local de la imagen creativa que quieres usar, por ejemplo /Users/tu/imagen.png.",
                "confirmación exacta: Sí, crear y dejar activo": "Como pediste dejarla activa, necesito que confirmes exactamente: Sí, crear y dejar activo.",
            }
            return {"ok": True, "provider": "local-action-router", "fallback": False, "routed_action": {"type": "clarify_campaign_creation", "executed": False, "missing": missing}, "reply": chat_reply(payload, questions[first], f"I need one detail first: {first}.")}
        try:
            require_cloud_license("Campaign creation requires an active license")
            result = create_campaign(draft)
            return {"ok": True, "provider": "local-action-router", "fallback": False, "routed_action": {"type": "create_campaign_stack", "executed": False, "staged": True, "result": result}, "reply": chat_reply(payload, "Hice el analisis y ya preparé la campaña completa para aprobación. Revísala en Aprobaciones; si confirmas, quedará activa y podrá gastar presupuesto real.", "I analyzed the request and staged the full campaign stack for approval. Review it in Approvals; if confirmed, it will be active and able to spend real budget.")}
        except Exception as exc:
            return {"ok": True, "provider": "local-action-router", "fallback": False, "routed_action": {"type": "create_campaign_stack", "executed": False, "blocked": True, "error": str(exc)}, "reply": chat_reply(payload, f"No puedo preparar esa campaña todavía: {exc}", f"I cannot stage that campaign yet: {exc}")}

    if wants_daily:
        action, report = run_daily_agent()
        return {
            "ok": True,
            "provider": "local-action-router",
            "fallback": False,
            "routed_action": {"type": "run_daily_agent", "executed": True, "action_id": action.get("id")},
            "reply": chat_reply(payload, "Listo. Ejecuté la revisión diaria en modo seguro y actualicé el resumen, recomendaciones y aprobaciones.", "Done. I ran the daily check in safe mode and refreshed the brief, recommendations, and approvals."),
        }

    if wants_export:
        result = export_csv()
        return {
            "ok": True,
            "provider": "local-action-router",
            "fallback": False,
            "routed_action": {"type": "export_csv", "executed": True, "path": result.get("path")},
            "reply": chat_reply(payload, f"Listo. Exporté el reporte CSV: {result.get('path')}", f"Done. I exported the CSV report: {result.get('path')}"),
        }

    if wants_pause or wants_resume or wants_budget or wants_creative:
        campaign, reason = find_campaign_for_text(text, metrics)
        if not campaign:
            return {
                "ok": True,
                "provider": "local-action-router",
                "fallback": False,
                "routed_action": {"type": "clarify_campaign", "executed": False, "reason": reason},
                "reply": chat_reply(payload, "Puedo hacerlo, pero necesito saber la campaña exacta. Dime el nombre o usa el botón Preguntar desde la tarjeta de esa campaña.", "I can do that, but I need the exact campaign. Tell me the name or use the Ask button from that campaign card."),
            }
        campaign_id = campaign.get("id")
        if wants_pause:
            result = apply_action({"action": "pause", "campaign_id": campaign_id})
            staged = isinstance(result, dict) and result.get("status") == "pending"
            return {
                "ok": True,
                "provider": "local-action-router",
                "fallback": False,
                "routed_action": {"type": "pause", "executed": not staged, "staged": staged, "campaign_id": campaign_id, "result": result},
                "reply": chat_reply(payload, f"{'Preparé la pausa para aprobación' if staged else 'Listo. Pausé'} {campaign.get('name')}.", f"I {'staged the pause for approval' if staged else 'paused'} {campaign.get('name')}."),
            }
        if wants_resume:
            result = apply_action({"action": "resume", "campaign_id": campaign_id})
            return {
                "ok": True,
                "provider": "local-action-router",
                "fallback": False,
                "routed_action": {"type": "resume", "executed": False, "campaign_id": campaign_id, "result": result},
                "reply": chat_reply(payload, f"Preparé la reactivación de {campaign.get('name')} para aprobación. Revísala en la cola antes de ejecutarla.", f"I staged the reactivation of {campaign.get('name')} for approval. Review it in the queue before execution."),
            }
        if wants_budget:
            new_budget = parse_budget_request(text, campaign)
            if new_budget is None:
                return {
                    "ok": True,
                    "provider": "local-action-router",
                    "fallback": False,
                    "routed_action": {"type": "clarify_budget", "executed": False, "campaign_id": campaign_id},
                    "reply": chat_reply(payload, f"¿A cuánto quieres dejar el presupuesto diario de {campaign.get('name')}? Puedes decir algo como: sube 15% o ponlo en 200.", f"What daily budget should {campaign.get('name')} use? You can say: increase 15% or set it to 200."),
                }
            result = apply_action({"action": "adjust_budget", "campaign_id": campaign_id, "new_budget": new_budget})
            staged = isinstance(result, dict) and result.get("status") == "pending"
            return {
                "ok": True,
                "provider": "local-action-router",
                "fallback": False,
                "routed_action": {"type": "adjust_budget", "executed": not staged, "campaign_id": campaign_id, "new_budget": new_budget, "result": result},
                "reply": chat_reply(payload, f"Listo. {'Dejé en aprobación' if staged else 'Ajusté'} el presupuesto de {campaign.get('name')} a ${new_budget:,.2f}.", f"Done. I {'staged for approval' if staged else 'adjusted'} {campaign.get('name')} to ${new_budget:,.2f} daily budget."),
            }
        if wants_creative:
            plan, manifest_path = generate_creative_refresh(campaign)
            log_action("chat_creative_refresh", {"campaign_id": campaign_id, "name": campaign.get("name"), "manifest_path": str(manifest_path)}, "generated")
            return {
                "ok": True,
                "provider": "local-action-router",
                "fallback": False,
                "routed_action": {"type": "creative_refresh", "executed": True, "campaign_id": campaign_id, "manifest_path": str(manifest_path)},
                "reply": chat_reply(payload, f"Listo. Generé un borrador creativo para {campaign.get('name')}. Lo puedes revisar en Creatividades.", f"Done. I generated a creative refresh draft for {campaign.get('name')}. You can review it in Creatives."),
            }
    return None


def execute_agent_tool(tool_request, chat_payload):
    if not isinstance(tool_request, dict):
        return None
    tool = str(tool_request.get("tool") or "").strip()
    arguments = tool_request.get("arguments") or {}
    if not isinstance(arguments, dict):
        arguments = {}

    def reply(es, en):
        return chat_reply(chat_payload, es, en)

    if tool == "approval_guardrail":
        return {
            "type": tool,
            "executed": False,
            "reply": reply(
                "Por seguridad, el chat no aprueba cambios. Abre la cola de aprobaciones y confirma la acción exacta desde ahí.",
                "For safety, chat does not approve changes. Open the approval queue and confirm the exact action there.",
            ),
        }

    if tool == "review_live_readiness":
        setup = build_setup_status()
        blockers = []
        for section in setup.get("sections", []):
            for item in section.get("items", []):
                if item.get("status") in {"blocked", "warn"}:
                    blockers.append(item)
        top = blockers[:3]
        if chat_lang(chat_payload) == "es":
            detail = "; ".join(f"{item.get('label')}: {item.get('detail')}" for item in top) or "no veo bloqueos principales"
            message = f"Para activar piloto automático con calma, atiende esto primero: {detail}. Después corre una revisión con supervisión, revisa aprobaciones y activa piloto automático al final."
        else:
            detail = "; ".join(f"{item.get('label')}: {item.get('detail')}" for item in top) or "I do not see major blockers"
            message = f"To enable autopilot calmly, handle this first: {detail}. Then run one supervised check, review approvals, and enable autopilot last."
        return {"type": tool, "executed": False, "blocker_count": len(blockers), "reply": message}

    if tool == "run_daily_check":
        action, report = run_daily_agent()
        return {
            "type": tool,
            "executed": True,
            "action_id": action.get("id"),
            "reply": reply("Listo. Ejecuté la revisión diaria y actualicé resumen, recomendaciones y aprobaciones.", "Done. I ran the daily check and refreshed the brief, recommendations, and approvals."),
        }

    if tool == "export_report":
        result = export_csv()
        return {
            "type": tool,
            "executed": True,
            "path": result.get("path"),
            "reply": reply(f"Listo. Exporté el reporte CSV: {result.get('path')}", f"Done. I exported the CSV report: {result.get('path')}"),
        }

    if tool == "create_campaign_stack":
        required = ["name", "daily_budget", "landing_url", "creative_image_path"]
        missing = [key for key in required if not arguments.get(key)]
        final_status = str(arguments.get("final_status") or "ACTIVE").upper()
        if final_status == "ACTIVE" and not arguments.get("active_spend_confirmed"):
            missing.append("active_spend_confirmed")
        if missing:
            return {
                "type": tool,
                "executed": False,
                "blocked": True,
                "reason": "missing_campaign_creation_detail",
                "missing": missing,
                "reply": reply(
                    f"Puedo preparar la campaña, pero falta esto: {', '.join(missing)}. Dame ese dato y la dejo lista para aprobación.",
                    f"I can prepare the campaign, but this is missing: {', '.join(missing)}. Send that detail and I will stage it for approval.",
                ),
            }
        require_cloud_license("Campaign creation requires an active license")
        result = create_campaign(arguments)
        return {
            "type": tool,
            "executed": False,
            "staged": True,
            "result": result,
            "reply": reply(
                "Hice el analisis y preparé la campaña completa para aprobación. Revísala en Aprobaciones; si confirmas, se ejecutará con el estado final elegido.",
                "I analyzed the request and staged the full campaign for approval. Review it in Approvals; if confirmed, it will execute with the selected final status.",
            ),
        }

    if tool == "build_audience_strategy":
        if not any(arguments.get(key) for key in ["product", "buyer", "locations", "interests", "data_sources"]):
            return {
                "type": tool,
                "executed": False,
                "blocked": True,
                "reason": "missing_audience_brief",
                "reply": reply(
                    "Puedo ayudarte, pero necesito al menos qué vendes, a quién le vendes y en qué país o ciudad quieres anunciar.",
                    "I can help, but I need at least what you sell, who buys, and which country or city you want to target.",
                ),
            }
        result = create_audience_strategy(arguments, chat_lang(chat_payload))
        if chat_lang(chat_payload) == "es":
            status = "lista" if result["lookalike_readiness"]["ready"] else "todavía no lista"
            message = f"Listo. Preparé una estrategia de audiencias para {result['product']}. Lookalike: {status}. Te recomiendo empezar con amplia/Advantage+ y una prueba de intereses, dejando lookalike para cuando la data semilla esté clara."
        else:
            status = "ready" if result["lookalike_readiness"]["ready"] else "not ready yet"
            message = f"Done. I prepared an audience strategy for {result['product']}. Lookalike is {status}. Start with broad/Advantage+ plus one interest test, then use lookalike once the seed data is clean."
        return {"type": tool, "executed": True, "result": result, "reply": message}

    if tool == "init_brand_guides":
        product_name = str(arguments.get("product_name") or "").strip()
        if not product_name:
            return {
                "type": tool,
                "executed": False,
                "blocked": True,
                "reason": "missing_product_name",
                "reply": reply("Dime el nombre del producto u oferta principal y creo las guías base.", "Tell me the main product or offer name and I will create the base guides."),
            }
        result = initialize_brand_guides({"product_name": product_name})
        return {
            "type": tool,
            "executed": True,
            "result": result,
            "reply": reply(
                f"Listo. Creé las guías base para {product_name}. Puedo usarlas directamente para trabajar creativos; Codex CLI queda como complemento opcional que el dueño debe activar.",
                f"Done. I created the base guides for {product_name}. I can use them directly for creative work; Codex CLI remains an optional owner-enabled add-on.",
            ),
        }

    if tool == "codex_creative_plan":
        result = codex_creative_plan(arguments)
        if result.get("ok"):
            message = result.get("stdout") or "Codex devolvió un plan creativo."
            return {"type": tool, "executed": True, "result": result, "reply": message}
        return {
            "type": tool,
            "executed": False,
            "blocked": True,
            "result": result,
            "reply": reply(
                f"Todavía no pude usar Codex CLI: {result.get('error') or result.get('stderr') or 'revisa la configuración'}. Las guías quedan listas para cuando Codex esté configurado.",
                f"I could not use Codex CLI yet: {result.get('error') or result.get('stderr') or 'check setup'}. The guides remain ready for when Codex is configured.",
            ),
        }

    if tool == "save_existing_adset":
        adset_id = extract_adset_id(str(arguments.get("adset_id") or arguments.get("default_adset_id") or ""))
        if not adset_id:
            return {
                "type": tool,
                "executed": False,
                "blocked": True,
                "reason": "missing_adset_id",
                "reply": reply(
                    "Puedo guardarlo, pero necesito el número del grupo de anuncios. Se ve como un número largo dentro de Meta Ads Manager.",
                    "I can save it, but I need the ad set number. It looks like a long number inside Meta Ads Manager.",
                ),
            }
        result = save_setup_config({"default_adset_id": adset_id})
        return {
            "type": tool,
            "executed": True,
            "default_adset_id": adset_id,
            "result": result,
            "reply": reply(
                f"Listo. Guardé el grupo de anuncios existente {adset_id}. Lo usaré solo si me pides crear anuncios dentro de una estructura que ya existe.",
                f"Done. I saved existing ad set {adset_id}. I will use it only when you ask me to create ads inside an existing structure.",
            ),
        }

    if tool in {"pause_campaign", "resume_campaign", "set_budget", "generate_creatives"}:
        campaign_id = arguments.get("campaign_id")
        metrics = load_metrics()
        campaign = campaign_by_id(metrics, campaign_id)
        if not campaign:
            return {
                "type": tool,
                "executed": False,
                "blocked": True,
                "reason": "missing_or_unknown_campaign_id",
                "reply": reply("Necesito la campaña exacta antes de hacer eso. Usa el botón Preguntar en la tarjeta correcta o dime el nombre exacto.", "I need the exact campaign before doing that. Use the Ask button on the right card or tell me the exact name."),
            }

        if tool == "pause_campaign":
            result = apply_action({"action": "pause", "campaign_id": campaign_id})
            staged = isinstance(result, dict) and result.get("status") == "pending"
            return {"type": tool, "executed": not staged, "staged": staged, "campaign_id": campaign_id, "result": result, "reply": reply(f"{'Preparé la pausa para aprobación' if staged else 'Listo. Pausé'} {campaign.get('name')}.", f"I {'staged the pause for approval' if staged else 'paused'} {campaign.get('name')}.")}

        if tool == "resume_campaign":
            result = apply_action({"action": "resume", "campaign_id": campaign_id})
            return {"type": tool, "executed": False, "staged": True, "campaign_id": campaign_id, "result": result, "reply": reply(f"Preparé la reactivación de {campaign.get('name')} para aprobación.", f"I staged the reactivation of {campaign.get('name')} for approval.")}

        if tool == "set_budget":
            try:
                new_budget = float(arguments.get("new_budget"))
            except (TypeError, ValueError):
                return {
                    "type": tool,
                    "executed": False,
                    "blocked": True,
                    "reason": "missing_new_budget",
                    "reply": reply(f"¿A cuánto quieres dejar el presupuesto diario de {campaign.get('name')}?", f"What daily budget should {campaign.get('name')} use?"),
                }
            result = apply_action({"action": "adjust_budget", "campaign_id": campaign_id, "new_budget": new_budget})
            staged = isinstance(result, dict) and result.get("status") == "pending"
            return {"type": tool, "executed": not staged, "staged": staged, "campaign_id": campaign_id, "new_budget": new_budget, "result": result, "reply": reply(f"{'Dejé en aprobación' if staged else 'Ajusté'} el presupuesto de {campaign.get('name')} a ${new_budget:,.2f}.", f"I {'staged for approval' if staged else 'adjusted'} {campaign.get('name')} to ${new_budget:,.2f} daily budget.")}

        if tool == "generate_creatives":
            plan, manifest_path = generate_creative_refresh(campaign)
            log_action("chat_creative_refresh", {"campaign_id": campaign_id, "name": campaign.get("name"), "manifest_path": str(manifest_path)}, "generated")
            return {"type": tool, "executed": True, "campaign_id": campaign_id, "manifest_path": str(manifest_path), "reply": reply(f"Listo. Generé un borrador creativo para {campaign.get('name')}.", f"Done. I generated a creative refresh draft for {campaign.get('name')}.")}

    return {
        "type": tool or "unknown_tool",
        "executed": False,
        "blocked": True,
        "reason": "unsupported_tool",
        "reply": reply("Ese tipo de acción todavía no está disponible en el dashboard.", "That action is not available in the dashboard yet."),
    }


def require_license_unlock(action_name="action"):
    config = load_config()
    if not config.license_required_for_live or not (config.live or config.live_actions_enabled):
        return
    status = license_status(config)
    if not status.get("valid"):
        raise ValueError(f"License unlock required for {action_name}: {status.get('detail')}")


def require_cloud_license(action_name="buyer feature"):
    config = load_config()
    if not config.license_required_for_live:
        return
    status = license_status(config)
    if not status.get("valid"):
        raise ValueError(f"{action_name}: {status.get('detail')}")


def dashboard_payload():
    metrics = load_metrics()
    recommendations = calculate_recommendations(metrics.get("campaigns", []))
    config = load_config()
    setup = build_setup_status()
    current_license_status = license_status(config)
    ad_config = read_json(AD_CONFIG_FILE, {})
    destination = ad_config.get("creative", {}).get("destination", {})
    business_profile = read_json(BUSINESS_PROFILE_FILE, {})
    onboarding = onboarding_health(load_onboarding_state(), config, metrics, current_license_status, destination, business_profile)
    return {
        "metrics": metrics,
        "recommendations": recommendations,
        "brief": scheduled_brief_or_live(metrics, recommendations),
        "fatigue": fatigue_items(metrics.get("campaigns", [])),
        "actions": read_json(ACTIONS_FILE, [])[:20],
        "pending": read_json(PENDING_FILE, [])[:20],
        "created_campaigns": read_json(CREATED_FILE, [])[:10],
        "audience_strategy": read_json(AUDIENCE_FILE, {}),
        "brand_guides": brand_guide_status(),
        "creative_refreshes": recent_creative_refreshes(8),
        "creative_uploads": recent_uploads(8),
        "chat_history": load_chat_history(),
        "business_profile": business_profile,
        "business_spaces": agency_spaces_payload(),
        "config": {
            "mode": config.mode,
            "notify_channel": config.notify_channel,
            "telegram_agent": telegram_settings(config),
            "dashboard_token_required": config.dashboard_token_required,
            "dashboard_token_set": bool(config.dashboard_token),
            "dashboard_password_required": config.dashboard_token_required,
            "dashboard_password_set": bool(config.dashboard_password or config.dashboard_token),
            "live_actions_enabled": config.live_actions_enabled,
            "guardrails": {
                "autonomy_mode": config.autonomy_mode,
                "approval_required_over_pct": config.approval_required_over_pct,
                "auto_budget_change_pct": config.auto_budget_change_pct,
                "auto_budget_change_amount": config.auto_budget_change_amount,
                "auto_pause_max_spend": config.auto_pause_max_spend,
                "require_approval_for_resume": config.require_approval_for_resume,
                "require_approval_for_new_campaigns": config.require_approval_for_new_campaigns,
                "require_approval_for_creatives": config.require_approval_for_creatives,
            },
            "license_status": current_license_status,
            "license_buyer_email_set": bool(config.license_buyer_email),
            "setup_values": {
                "license_key_set": bool(config.license_key),
                "license_buyer_email": config.license_buyer_email,
                "license_server_url_set": bool(config.license_server_url),
                "license_required_for_live": config.license_required_for_live,
                "ad_account_id": config.ad_account_id or ad_config.get("account", {}).get("id", ""),
                "page_id": destination.get("page_id", ""),
                "instagram_actor_id": destination.get("instagram_actor_id", ""),
                "default_adset_id": destination.get("default_adset_id", ""),
                "landing_url": destination.get("url", ""),
            },
        },
        "setup": setup,
        "onboarding": onboarding,
        "generated_at": now_iso(),
    }


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Meta Ads Agent</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#101113;--shell:#14171a;--surface:#1a1d21;--surface2:#22262b;--surface3:#2b3036;--glass:rgba(28,33,38,.58);--glass2:rgba(255,255,255,.075);--border:#343a42;--line:rgba(255,255,255,.12);--text:#f2f2ee;--dim:#a7adb5;--muted:#777f89;--accent:#27c7a7;--accent2:#f4b740;--green:#55d47a;--red:#ff6b6b;--yellow:#f4c95d;--blue:#63a8ff;--cyan:#4bd4d4;--shadow:0 22px 70px rgba(0,0,0,.34);--glow:0 0 0 1px rgba(255,255,255,.09) inset,0 1px 0 rgba(255,255,255,.12) inset}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:radial-gradient(circle at 18% -8%,rgba(39,199,167,.18),transparent 32rem),radial-gradient(circle at 86% 12%,rgba(244,183,64,.12),transparent 26rem),linear-gradient(180deg,#121517 0%,#0f1113 100%);color:var(--text);min-height:100vh;background-attachment:fixed}
button,input,select,textarea{font:inherit}
.onboarding-flow{position:fixed;inset:0;z-index:50;display:none;background:linear-gradient(145deg,#101315,#171b1f);overflow:auto;padding:26px}.onboarding-flow.open{display:grid;place-items:center}.onboarding-shell{width:min(1080px,100%);display:grid;grid-template-columns:270px minmax(0,1fr);gap:18px;align-items:start}.onboarding-side{border:1px solid var(--line);border-radius:10px;background:rgba(255,255,255,.055);padding:16px;box-shadow:var(--shadow),var(--glow);position:sticky;top:26px}.onboarding-side h1{font-size:20px;line-height:1.05}.onboarding-side p{font-size:12px;color:var(--dim);line-height:1.5;margin-top:8px}.onboarding-card{display:block;min-height:0;border:1px solid var(--line);border-radius:10px;background:rgba(22,26,30,.86);box-shadow:var(--shadow),var(--glow);padding:20px}.onboarding-card h2{font-size:23px;line-height:1.1;max-width:720px}.onboarding-card>p{font-size:13px;color:var(--dim);line-height:1.55;margin-top:8px;max-width:760px}.onboarding-progress{display:flex;gap:6px;margin:14px 0}.onboarding-progress span{height:6px;flex:1;border-radius:999px;background:rgba(255,255,255,.1)}.onboarding-progress span.done{background:var(--accent)}.onboarding-step-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.onboarding-command{border:1px solid var(--line);background:rgba(0,0,0,.22);border-radius:8px;padding:10px;margin-top:8px;font-size:12px;color:var(--text);word-break:break-word}.helper-command{margin-top:10px;color:var(--dim);font-size:11px}.helper-command summary{cursor:pointer;font-weight:900;color:var(--accent);list-style:none}.helper-command summary::-webkit-details-marker{display:none}.helper-command summary:before{content:"+";display:inline-grid;place-items:center;width:16px;height:16px;margin-right:6px;border-radius:5px;background:rgba(39,199,167,.13);color:var(--accent)}.helper-command[open] summary:before{content:"-"}.onboarding-helper{border:1px solid rgba(39,199,167,.18);border-radius:8px;padding:10px;background:rgba(39,199,167,.045)}.onboarding-helper .btn{margin-top:8px}.onboarding-mini{display:grid;gap:8px;margin-top:12px}.onboarding-mini.two{grid-template-columns:1fr 1fr}.onboarding-mini label{display:flex;flex-direction:column;gap:5px}.onboarding-mini input,.onboarding-mini textarea{width:100%}.onboarding-mini textarea{resize:vertical;min-height:92px;background:var(--surface2);border:1px solid var(--border);border-radius:7px;color:var(--text);padding:9px;font-size:12px;line-height:1.4}.onboarding-mini .wide{grid-column:1/-1}.onboarding-mini>.btn,.unlock-form>.btn{justify-self:start}.setup-guide{display:grid;gap:12px;margin-top:16px}.guide-card,.guide-panel{border:1px solid var(--line);border-radius:8px;background:rgba(255,255,255,.055);padding:12px}.guide-card b,.guide-panel b{display:block;font-size:12px;line-height:1.25}.guide-card p,.guide-card li,.guide-panel p,.guide-panel li{font-size:11px;color:var(--dim);line-height:1.45}.guide-card ol,.guide-panel ol{margin:8px 0 0 18px;padding:0}.private-connection{grid-template-columns:1fr}.guide-hero{display:grid;grid-template-columns:minmax(0,1fr) 270px;gap:14px;align-items:stretch;border:1px solid rgba(39,199,167,.2);border-radius:10px;background:linear-gradient(135deg,rgba(39,199,167,.09),rgba(255,255,255,.045));padding:14px;box-shadow:var(--glow)}.guide-main{display:grid;gap:12px;align-content:start}.guide-eyebrow{display:inline-flex;width:max-content;border:1px solid rgba(39,199,167,.24);border-radius:999px;background:rgba(39,199,167,.09);color:var(--accent);padding:5px 8px;font-size:10px;font-weight:950;text-transform:uppercase}.guide-main h3{font-size:18px;line-height:1.12}.guide-main p{font-size:12px;color:var(--dim);line-height:1.55;max-width:610px}.guide-actions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.guide-actions .btn{text-align:center;text-decoration:none}.guide-checklist{border:1px solid rgba(255,255,255,.1);border-radius:8px;background:rgba(0,0,0,.14);padding:12px}.guide-checklist b{font-size:12px}.guide-checklist ol{margin:9px 0 0 18px}.guide-checklist li{font-size:11px;color:var(--dim);line-height:1.5;margin-bottom:6px}.guide-support-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.manual-account{margin:0}.manual-account .btn{justify-self:start}.fallback-details{border:1px solid var(--line);border-radius:8px;background:rgba(255,255,255,.035);padding:0}.fallback-details summary{cursor:pointer;list-style:none;padding:11px 12px;font-size:11px;font-weight:900;color:var(--dim)}.fallback-details summary::-webkit-details-marker{display:none}.fallback-details summary:before{content:"+";display:inline-grid;place-items:center;width:16px;height:16px;margin-right:6px;border-radius:5px;background:rgba(255,255,255,.06);color:var(--accent)}.fallback-details[open] summary:before{content:"-"}.fallback-details .manual-account{border:0;border-top:1px solid var(--line);border-radius:0;background:transparent}.token-box{display:none;gap:8px;margin-top:0;border:1px solid rgba(39,199,167,.18);border-radius:8px;background:rgba(0,0,0,.16);padding:10px}.token-box.open{display:grid}.token-box textarea{min-height:86px;resize:vertical;background:var(--surface2);border:1px solid var(--border);border-radius:7px;color:var(--text);padding:9px;font-size:12px;line-height:1.35}.guide-visual{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;gap:8px;align-items:center}.mini-screen{border:1px solid rgba(255,255,255,.14);border-radius:8px;background:rgba(0,0,0,.18);padding:10px;min-height:82px}.mini-screen span{display:block;height:8px;border-radius:99px;background:rgba(255,255,255,.14);margin-bottom:7px}.mini-screen strong{display:block;font-size:11px}.mini-screen em{display:block;font-style:normal;font-size:10px;color:var(--accent);margin-top:5px}.guide-arrow{color:var(--accent);font-weight:950}.passive-guide{display:grid;grid-template-columns:minmax(0,1fr) 230px;gap:12px;margin-top:16px}.passive-card{border:1px solid rgba(99,168,255,.2);border-radius:10px;background:rgba(99,168,255,.065);padding:14px;box-shadow:var(--glow)}.passive-card b,.passive-side b{font-size:12px}.passive-card p,.passive-side p{font-size:12px;color:var(--dim);line-height:1.5;margin-top:6px}.passive-side{border:1px solid var(--line);border-radius:8px;background:rgba(255,255,255,.045);padding:12px}.passive-state{display:inline-flex;align-items:center;gap:7px;border:1px solid rgba(39,199,167,.22);border-radius:999px;background:rgba(39,199,167,.08);color:var(--accent);font-size:10px;font-weight:950;padding:5px 8px;text-transform:uppercase}.passive-state:before{content:"";width:7px;height:7px;border-radius:50%;background:var(--accent)}
header{position:sticky;top:0;z-index:4;background:rgba(18,21,24,.62);backdrop-filter:blur(22px) saturate(145%);-webkit-backdrop-filter:blur(22px) saturate(145%);border-bottom:1px solid var(--line);display:grid;grid-template-columns:minmax(178px,220px) minmax(360px,1fr) auto auto;align-items:center;gap:12px;padding:12px 18px;box-shadow:0 8px 28px rgba(0,0,0,.18),var(--glow)}
.brand{min-width:0;position:relative;padding-left:36px}.brand:before{content:"";position:absolute;left:0;top:1px;width:24px;height:24px;border-radius:7px;background:linear-gradient(135deg,var(--accent),var(--accent2));box-shadow:0 0 0 1px rgba(255,255,255,.14) inset}.brand h1{font-size:16px;line-height:1.05;letter-spacing:0;font-weight:900}.brand span{color:var(--accent)}.brand div{font-size:11px;color:var(--dim);margin-top:4px}
.panel-caret{margin-left:auto;color:var(--zone);font-size:12px;font-weight:950;transition:transform .16s ease}.panel-caret:before{content:"+"}body.left-panel-open .brief-zone .panel-caret:before,body.right-panel-open .rail .panel-caret:before{content:"-"}
.tabs{display:flex;flex-wrap:wrap;align-items:center;gap:5px;min-width:0;overflow:visible;padding:3px;border:1px solid var(--line);background:rgba(255,255,255,.055);border-radius:10px;box-shadow:var(--glow);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}.tab{border:0;background:transparent;color:var(--dim);border-radius:7px;padding:7px 10px;font-size:11px;font-weight:850;cursor:pointer;white-space:nowrap;flex:1 1 96px;text-align:center;min-width:max-content}.tab:hover{color:var(--text);background:rgba(255,255,255,.07)}.tab.active{background:rgba(255,255,255,.13);color:var(--text);box-shadow:0 1px 0 rgba(255,255,255,.12) inset}
.header-guide-btn{display:grid;place-items:center;width:32px;height:32px;border:1px solid rgba(39,199,167,.28);border-radius:8px;background:rgba(39,199,167,.08);color:var(--accent);font-size:13px;font-weight:950;cursor:pointer;box-shadow:var(--glow);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}.header-guide-btn:hover{border-color:rgba(39,199,167,.7);background:rgba(39,199,167,.14)}
.status{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:6px;align-items:center;max-width:360px}.pill{border:1px solid var(--line);background:rgba(255,255,255,.065);border-radius:999px;padding:6px 9px;color:var(--dim);font-size:10px;white-space:nowrap;box-shadow:var(--glow);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}.pill strong{color:var(--text);font-weight:850}.lang-select{background:rgba(255,255,255,.075);border:1px solid var(--line);border-radius:999px;color:var(--text);padding:6px 8px;font-size:10px;font-weight:900;cursor:pointer;box-shadow:var(--glow);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
.tip{display:inline-flex;align-items:center;gap:4px;cursor:help;overflow:visible}.help-dot{display:inline-grid;place-items:center;width:14px;height:14px;border:1px solid var(--border);border-radius:50%;font-size:9px;font-weight:900;color:var(--dim);background:rgba(255,255,255,.04)}.floating-tip{position:fixed;left:0;top:0;z-index:1000;max-width:min(260px,calc(100vw - 24px));background:#f4f5f8;color:#111217;border:1px solid rgba(255,255,255,.2);border-radius:7px;padding:9px 10px;font-size:11px;font-weight:650;line-height:1.35;text-transform:none;box-shadow:0 12px 32px rgba(0,0,0,.38);opacity:0;pointer-events:none;transform:translateY(4px);transition:opacity .12s ease,transform .12s ease}.floating-tip.show{opacity:1;transform:translateY(0)}
main{display:grid;grid-template-columns:320px minmax(500px,1fr) 380px;gap:14px;min-height:calc(100vh - 66px);padding:14px}body:not(.left-panel-open) .brief-zone .section,body:not(.right-panel-open) .rail .section{display:none}
.col{padding:0;overflow:auto;min-width:0;position:relative}.col:before{content:"";position:sticky;top:0;display:block;height:3px;border-radius:999px;margin-bottom:10px;background:var(--zone);box-shadow:0 0 20px var(--zone-glow);z-index:1}.brief-zone{--zone:#55d47a;--zone-glow:rgba(85,212,122,.36);--zone-bg:rgba(85,212,122,.075);--zone-border:rgba(85,212,122,.18)}.work-zone{--zone:#63a8ff;--zone-glow:rgba(99,168,255,.34);--zone-bg:rgba(99,168,255,.065);--zone-border:rgba(99,168,255,.17)}.rail{min-width:0;--zone:#f4b740;--zone-glow:rgba(244,183,64,.35);--zone-bg:rgba(244,183,64,.07);--zone-border:rgba(244,183,64,.17)}
.zone-label{display:flex;align-items:center;gap:8px;margin:0 0 10px;padding:9px 11px;border:1px solid var(--zone-border);background:var(--zone-bg);border-radius:8px;color:var(--text);font-size:11px;font-weight:900;letter-spacing:0}.zone-label:before{content:"";width:8px;height:8px;border-radius:50%;background:var(--zone);box-shadow:0 0 0 4px var(--zone-glow)}button.zone-label{width:100%;cursor:pointer;text-align:left;font:inherit}button.zone-label:hover{border-color:var(--zone);background:color-mix(in srgb,var(--zone-bg) 72%,rgba(255,255,255,.08))}
.section{border:1px solid color-mix(in srgb,var(--zone-border) 55%,var(--line));background:linear-gradient(145deg,var(--zone-bg),rgba(28,33,38,.56));backdrop-filter:blur(22px) saturate(135%);-webkit-backdrop-filter:blur(22px) saturate(135%);border-radius:8px;margin-bottom:14px;overflow:hidden;box-shadow:var(--shadow),var(--glow)}.head{display:flex;align-items:center;gap:9px;background:rgba(255,255,255,.055);border-bottom:1px solid var(--line);padding:11px 13px}.head b{font-size:12px;flex:1;font-weight:900}.head span{display:inline-grid;place-items:center;width:22px;height:22px;border-radius:6px;background:var(--zone-bg);color:var(--zone);font-size:10px;font-weight:900;box-shadow:0 0 0 1px var(--zone-border) inset}.body{padding:13px}
.page-title{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:14px;padding:15px 16px;border:1px solid var(--line);background:linear-gradient(135deg,rgba(255,255,255,.095),rgba(255,255,255,.035));backdrop-filter:blur(24px) saturate(145%);-webkit-backdrop-filter:blur(24px) saturate(145%);border-radius:8px;box-shadow:var(--shadow),var(--glow)}.page-title h2{font-size:18px;line-height:1.1;font-weight:950}.page-title p{font-size:12px;color:var(--dim);margin-top:4px}.signal{display:flex;align-items:center;gap:8px;color:var(--accent);font-size:11px;font-weight:900;white-space:nowrap;background:rgba(39,199,167,.1);border:1px solid rgba(39,199,167,.22);border-radius:999px;padding:7px 10px}.signal:before{content:"";width:8px;height:8px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 4px rgba(39,199,167,.12)}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px}.kpi{background:linear-gradient(145deg,rgba(255,255,255,.105),rgba(255,255,255,.04));border:1px solid var(--line);border-radius:8px;padding:15px;box-shadow:0 18px 45px rgba(0,0,0,.22),var(--glow);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px)}.kpi .v{font-size:23px;font-weight:900;line-height:1}.kpi .l{font-size:10px;color:var(--dim);margin-top:7px;text-transform:uppercase}
.campaign-grid{display:grid;grid-template-columns:repeat(2,minmax(280px,1fr));gap:13px}.card{background:linear-gradient(145deg,rgba(255,255,255,.08),rgba(26,31,36,.56));backdrop-filter:blur(22px) saturate(135%);-webkit-backdrop-filter:blur(22px) saturate(135%);border:1px solid var(--line);border-radius:8px;padding:14px;box-shadow:var(--shadow),var(--glow);position:relative;overflow:hidden}.card:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--blue)}.card:after{content:"";position:absolute;left:1px;right:1px;top:0;height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.34),transparent);pointer-events:none}.card[data-health=winning]:before{background:var(--green)}.card[data-health=losing]:before{background:var(--red)}.card[data-health=fatigue]:before{background:var(--yellow)}.card[data-health=paused]{opacity:.72}
.top{display:flex;align-items:flex-start;gap:10px;margin-bottom:12px}.top h3{font-size:14px;line-height:1.25;flex:1;font-weight:900}.badge{font-size:10px;padding:4px 8px;border-radius:999px;border:1px solid var(--line);color:var(--dim);background:rgba(255,255,255,.035);font-weight:850}.badge.winning{color:var(--green);border-color:rgba(85,212,122,.35);background:rgba(85,212,122,.08)}.badge.losing{color:var(--red);border-color:rgba(255,107,107,.38);background:rgba(255,107,107,.08)}.badge.fatigue{color:var(--yellow);border-color:rgba(244,201,93,.38);background:rgba(244,201,93,.08)}.badge.neutral{color:var(--blue);border-color:rgba(99,168,255,.35);background:rgba(99,168,255,.08)}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:12px}.metric{background:rgba(255,255,255,.07);border:1px solid var(--line);border-radius:8px;padding:9px;overflow:visible;box-shadow:0 1px 0 rgba(255,255,255,.08) inset}.metric b{font-size:15px;font-weight:900}.metric span{display:block;font-size:9px;color:var(--dim);margin-top:4px}
.spark{width:100%;height:48px;margin:4px 0 12px}.actions{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}.btn{border:1px solid var(--line);background:rgba(255,255,255,.045);color:var(--text);border-radius:7px;padding:8px 10px;font-size:11px;font-weight:850;cursor:pointer;transition:border-color .12s ease,background .12s ease,transform .12s ease}.btn:hover{border-color:rgba(39,199,167,.7);background:rgba(39,199,167,.09);transform:translateY(-1px)}.btn.primary{background:var(--accent);border-color:var(--accent);color:#061512}.btn.danger{border-color:rgba(255,107,107,.4);color:#ff8585;background:rgba(255,107,107,.06)}.ask-btn{border-color:rgba(39,199,167,.32);color:var(--accent);background:rgba(39,199,167,.08)}
.onboarding{margin-bottom:14px}.onboarding-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:10px}.onboarding-head h3{font-size:15px;font-weight:950;line-height:1.15}.onboarding-head p{font-size:12px;color:var(--dim);line-height:1.45;margin-top:4px}.progress{min-width:92px;text-align:right}.progress b{display:block;font-size:18px}.progress span{display:block;font-size:10px;color:var(--dim);margin-top:2px;text-transform:uppercase}.step-list{display:grid;gap:8px}.setup-step{display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:start;border:1px solid var(--line);background:rgba(255,255,255,.055);border-radius:8px;padding:10px;box-shadow:0 1px 0 rgba(255,255,255,.08) inset}.step-num{display:grid;place-items:center;width:26px;height:26px;border-radius:7px;background:rgba(255,255,255,.07);color:var(--dim);font-size:11px;font-weight:950}.setup-step.ok{border-color:rgba(85,212,122,.3);background:rgba(85,212,122,.075)}.setup-step.ok .step-num{background:rgba(85,212,122,.16);color:var(--green)}.setup-step.blocked{border-color:rgba(255,107,107,.32);background:rgba(255,107,107,.055)}.setup-step.blocked .step-num{background:rgba(255,107,107,.14);color:var(--red)}.setup-step.warn{border-color:rgba(244,183,64,.3);background:rgba(244,183,64,.06)}.setup-step.warn .step-num{background:rgba(244,183,64,.14);color:var(--accent2)}.step-main b{display:block;font-size:12px;line-height:1.25}.step-main p{font-size:11px;color:var(--dim);line-height:1.45;margin-top:4px}.step-command{display:inline-block;margin-top:7px;border:1px solid var(--line);border-radius:6px;background:rgba(0,0,0,.18);color:var(--text);font-size:11px;font-weight:800;padding:6px 7px}.step-badge{font-size:10px;font-weight:900;text-transform:uppercase;color:var(--dim);padding-top:5px;white-space:nowrap}.setup-step.ok .step-badge{color:var(--green)}.setup-step.blocked .step-badge{color:var(--red)}.setup-step.warn .step-badge{color:var(--accent2)}
.next-step{display:flex;align-items:center;justify-content:space-between;gap:12px;border:1px solid rgba(39,199,167,.26);background:rgba(39,199,167,.075);border-radius:8px;padding:11px;margin-bottom:10px}.next-step b{display:block;font-size:12px}.next-step p{font-size:11px;color:var(--dim);line-height:1.45;margin-top:4px}.copy-btn{white-space:nowrap}
.mode-panel{display:flex;align-items:center;justify-content:space-between;gap:12px;border:1px solid rgba(99,168,255,.24);background:rgba(99,168,255,.07);border-radius:8px;padding:12px;margin-bottom:14px}.mode-panel h3{font-size:13px;line-height:1.2}.mode-panel p{font-size:11px;color:var(--dim);line-height:1.45;margin-top:4px}.mode-actions{display:flex;gap:7px;flex:0 0 auto}.mode-actions .btn.active{background:var(--accent);border-color:var(--accent);color:#061512}
.trust-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:0 0 14px}.trust-card{border:1px solid var(--line);background:rgba(255,255,255,.055);border-radius:8px;padding:10px;box-shadow:0 1px 0 rgba(255,255,255,.08) inset}.trust-card b{display:block;font-size:11px;line-height:1.25}.trust-card p{font-size:11px;color:var(--dim);line-height:1.45;margin-top:5px}
.brief-q{background:rgba(255,255,255,.07);border:1px solid var(--line);border-radius:8px;padding:11px;margin-bottom:9px;box-shadow:0 1px 0 rgba(255,255,255,.08) inset}.brief-q b{font-size:12px;color:var(--text);font-weight:900}.brief-q p{font-size:12px;color:var(--dim);line-height:1.5;margin-top:6px}
table{width:100%;border-collapse:separate;border-spacing:0;font-size:12px}th,td{padding:10px;border-bottom:1px solid var(--line);text-align:left}th{color:var(--dim);font-size:10px;text-transform:uppercase;background:rgba(255,255,255,.035)}td:last-child{text-align:right}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.field{display:flex;flex-direction:column;gap:5px}.field.wide{grid-column:1/-1}label{font-size:10px;color:var(--dim);font-weight:800;text-transform:uppercase}input,select{background:var(--surface2);border:1px solid var(--border);border-radius:7px;color:var(--text);padding:9px;font-size:12px}input:focus,select:focus{outline:none;border-color:var(--accent)}
.fatigue{border-left:3px solid var(--yellow);padding:9px 10px;background:rgba(244,201,93,.07);border-radius:7px;margin-bottom:8px}.fatigue b{font-size:12px}.fatigue div{font-size:11px;color:var(--dim);margin-top:4px}
.log-item{font-size:11px;color:var(--dim);padding:9px 0;border-bottom:1px solid var(--line)}.log-item b{color:var(--text)}.action-detail{margin-top:7px;border:1px solid var(--line);background:rgba(255,255,255,.045);border-radius:7px;padding:8px;font-size:11px;color:var(--dim);line-height:1.45}.action-detail strong{color:var(--text)}.notice{font-size:11px;color:var(--dim);line-height:1.45}.mobile-recs{display:none}.rec-card{background:rgba(255,255,255,.07);border:1px solid var(--line);border-radius:8px;padding:11px;margin-bottom:9px;box-shadow:0 1px 0 rgba(255,255,255,.08) inset}.rec-card h3{font-size:12px;line-height:1.3;margin-bottom:8px}.rec-values{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:8px 0}.rec-values div{background:rgba(255,255,255,.055);border:1px solid var(--line);border-radius:7px;padding:8px}.rec-values b{display:block;font-size:13px}.rec-values span{display:block;color:var(--dim);font-size:9px;text-transform:uppercase;margin-top:3px}.chat-fab{position:fixed;right:18px;bottom:18px;z-index:30;border:1px solid rgba(39,199,167,.4);background:linear-gradient(135deg,rgba(39,199,167,.95),rgba(244,183,64,.92));color:#071411;border-radius:999px;padding:12px 15px;font-size:12px;font-weight:950;box-shadow:0 18px 55px rgba(0,0,0,.42);cursor:pointer;transition:transform .18s ease,box-shadow .18s ease;animation:chat-fab-breathe 3.8s ease-in-out infinite}.chat-fab:hover{transform:translateY(-2px) scale(1.02);box-shadow:0 20px 62px rgba(0,0,0,.46),0 0 0 6px rgba(39,199,167,.08)}.chat-panel{position:fixed;right:18px;bottom:76px;z-index:31;width:min(390px,calc(100vw - 24px));height:min(620px,calc(100vh - 96px));display:none;grid-template-rows:auto 1fr auto;border:1px solid var(--line);border-radius:10px;background:rgba(20,24,28,.78);backdrop-filter:blur(24px) saturate(140%);-webkit-backdrop-filter:blur(24px) saturate(140%);box-shadow:var(--shadow),var(--glow);overflow:hidden;transform-origin:calc(100% - 40px) 100%}.chat-panel.open{display:grid;animation:chat-panel-in .34s cubic-bezier(.16,1,.3,1) both}.chat-panel.open .chat-head{animation:chat-head-sheen .62s ease-out both}.chat-panel.open .chat-avatar{animation:chat-avatar-pop .46s cubic-bezier(.16,1,.3,1) both}.chat-head{display:flex;align-items:center;gap:10px;padding:12px;border-bottom:1px solid var(--line);background:rgba(255,255,255,.055)}.chat-avatar{display:grid;place-items:center;width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,var(--accent),var(--accent2));color:#061512;font-weight:950}.chat-title{flex:1}.chat-title b{display:block;font-size:13px}.chat-title span{display:block;font-size:10px;color:var(--dim);margin-top:2px}.chat-close{width:30px;height:30px;border-radius:8px}.chat-log{padding:12px;overflow:auto}.msg{max-width:88%;padding:10px 11px;border-radius:9px;margin-bottom:9px;font-size:12px;line-height:1.5;white-space:normal}.msg strong{font-weight:900;color:var(--text)}.msg p{margin:0 0 8px}.msg p:last-child{margin-bottom:0}.msg ul,.msg ol{margin:6px 0 8px 17px;padding:0}.msg li{margin:3px 0}.msg.agent{background:rgba(255,255,255,.08);border:1px solid var(--line);color:var(--text)}.msg.user{margin-left:auto;background:rgba(39,199,167,.16);border:1px solid rgba(39,199,167,.32);color:var(--text)}.msg.thinking{color:transparent;background:linear-gradient(100deg,var(--dim) 0%,var(--dim) 35%,#fff 48%,var(--accent) 54%,var(--dim) 68%,var(--dim) 100%);background-size:240% 100%;-webkit-background-clip:text;background-clip:text;animation:thinking-shimmer 1.35s linear infinite}.msg.thinking:before{content:"";display:inline-block;width:5px;height:5px;border-radius:50%;margin-right:7px;background:var(--accent);box-shadow:0 0 12px rgba(39,199,167,.75);vertical-align:middle;animation:thinking-pulse 1.1s ease-in-out infinite}@keyframes chat-panel-in{0%{opacity:0;transform:translateY(18px) scale(.94);filter:blur(8px)}55%{opacity:1;transform:translateY(-2px) scale(1.01);filter:blur(0)}100%{opacity:1;transform:translateY(0) scale(1);filter:blur(0)}}@keyframes chat-head-sheen{0%{box-shadow:0 -18px 45px rgba(39,199,167,.28) inset}100%{box-shadow:0 0 0 rgba(39,199,167,0) inset}}@keyframes chat-avatar-pop{0%{transform:scale(.72) rotate(-8deg);box-shadow:0 0 0 rgba(39,199,167,0)}70%{transform:scale(1.08) rotate(2deg);box-shadow:0 0 0 6px rgba(39,199,167,.13)}100%{transform:scale(1) rotate(0);box-shadow:0 0 0 rgba(39,199,167,0)}}@keyframes chat-fab-breathe{0%,100%{box-shadow:0 18px 55px rgba(0,0,0,.42),0 0 0 0 rgba(39,199,167,0)}50%{box-shadow:0 18px 55px rgba(0,0,0,.42),0 0 0 7px rgba(39,199,167,.08)}}@keyframes thinking-shimmer{0%{background-position:120% 0}100%{background-position:-120% 0}}@keyframes thinking-pulse{0%,100%{opacity:.35;transform:scale(.72)}50%{opacity:1;transform:scale(1)}}.chat-quick{display:flex;gap:7px;flex-wrap:wrap;padding:0 12px 9px}.chip{border:1px solid var(--line);background:rgba(255,255,255,.055);color:var(--dim);border-radius:999px;padding:7px 9px;font-size:11px;font-weight:800;cursor:pointer}.chat-form{display:grid;grid-template-columns:1fr auto;gap:8px;padding:11px;border-top:1px solid var(--line);background:rgba(255,255,255,.035);align-items:end}.chat-form textarea{min-height:44px;max-height:150px;resize:none;overflow-y:hidden;background:rgba(255,255,255,.07);border:1px solid var(--line);border-radius:8px;color:var(--text);padding:9px;font-size:12px;line-height:1.4}.unlock-overlay,.confirm-overlay,.guide-overlay{position:fixed;inset:0;z-index:60;display:none;place-items:center;padding:16px;background:rgba(8,10,12,.72);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px)}.unlock-overlay.open,.confirm-overlay.open,.guide-overlay.open{display:grid}.unlock-card,.confirm-card,.guide-modal-card{width:min(430px,100%);border:1px solid var(--line);border-radius:10px;background:rgba(22,26,30,.9);box-shadow:var(--shadow),var(--glow);padding:18px}.guide-modal-card{width:min(760px,calc(100vw - 28px));max-height:calc(100vh - 36px);overflow:auto}.unlock-card h2,.confirm-card h2,.guide-modal-card h2{font-size:19px;line-height:1.15}.unlock-card p,.confirm-card p,.guide-modal-card p{font-size:12px;color:var(--dim);line-height:1.5;margin-top:8px}.confirm-card ul{margin:10px 0 0 18px;color:var(--dim);font-size:12px;line-height:1.5}.confirm-actions{display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;margin-top:14px}.unlock-form{display:grid;gap:9px;margin-top:14px}.unlock-error{display:none;color:#ff9a9a;font-size:12px}.unlock-error.show{display:block}.hidden{display:none}.toast{position:fixed;right:16px;bottom:74px;z-index:58;max-width:min(340px,calc(100vw - 32px));background:var(--surface);border:1px solid var(--accent);border-radius:8px;padding:10px 12px;font-size:12px;display:none;box-shadow:var(--shadow)}
.chat-log{scrollbar-width:thin;scrollbar-color:rgba(39,199,167,.72) rgba(255,255,255,.055);scrollbar-gutter:stable}.chat-log::-webkit-scrollbar{width:10px}.chat-log::-webkit-scrollbar-track{background:rgba(255,255,255,.045);border-radius:999px}.chat-log::-webkit-scrollbar-thumb{background:linear-gradient(180deg,rgba(39,199,167,.92),rgba(244,183,64,.72));border:2px solid rgba(20,24,28,.9);border-radius:999px}.chat-log::-webkit-scrollbar-thumb:hover{background:linear-gradient(180deg,var(--accent),var(--accent2))}
.agent-chat-bar{position:fixed;left:50%;bottom:18px;z-index:32;width:min(65vw,860px);min-height:56px;display:grid;grid-template-columns:auto auto 1fr auto;align-items:center;gap:10px;padding:8px 10px;border:1px solid rgba(39,199,167,.34);border-radius:999px;background:rgba(20,24,28,.82);backdrop-filter:blur(24px) saturate(145%);-webkit-backdrop-filter:blur(24px) saturate(145%);box-shadow:0 20px 70px rgba(0,0,0,.45),var(--glow),0 0 0 0 rgba(39,199,167,0);transform:translateX(-50%);animation:agent-bar-breathe 4s ease-in-out infinite}.agent-chat-bar:before{content:"";position:absolute;left:12%;right:12%;top:-16px;height:34px;border-radius:999px;background:linear-gradient(90deg,rgba(39,199,167,.18),rgba(244,183,64,.13));filter:blur(18px);opacity:.45;transform:scaleY(.65);transition:opacity .18s ease,top .18s ease,height .18s ease,transform .18s ease;pointer-events:none}.agent-chat-bar:hover:before,.agent-chat-bar:focus-within:before{top:-29px;height:52px;opacity:.82;transform:scaleY(1)}.agent-chat-bar>*{position:relative;z-index:1}.agent-chat-bar:focus-within{border-color:rgba(39,199,167,.72);box-shadow:0 24px 80px rgba(0,0,0,.5),var(--glow),0 0 0 6px rgba(39,199,167,.08)}.agent-bar-mark{display:grid;place-items:center;width:34px;height:34px;border-radius:11px;background:linear-gradient(135deg,var(--accent),var(--accent2));color:#061512;font-size:11px;font-weight:950}.agent-bar-expand{display:grid;place-items:center;width:34px;height:34px;border:1px solid rgba(39,199,167,.28);border-radius:999px;background:rgba(39,199,167,.09);color:var(--accent);font-size:16px;font-weight:950;cursor:pointer}.agent-bar-expand:hover{background:rgba(39,199,167,.16);border-color:rgba(39,199,167,.7);transform:translateY(-2px)}.agent-chat-bar textarea{height:36px;max-height:92px;resize:none;overflow-y:hidden;border:0;background:transparent;color:var(--text);font-size:13px;line-height:1.35;padding:9px 4px}.agent-chat-bar textarea:focus{outline:none}.agent-chat-bar textarea::placeholder{color:var(--dim)}.agent-bar-send{display:grid;place-items:center;width:38px;height:38px;border:0;border-radius:999px;background:var(--accent);color:#061512;font-size:18px;font-weight:950;cursor:pointer}.agent-bar-send:hover{filter:brightness(1.05);transform:translateY(-1px)}body.chat-workspace-open .agent-chat-bar{display:none}body.chat-workspace-open .chat-panel{display:grid;left:0;right:auto;top:0;bottom:0;width:min(390px,32vw);height:100vh;border-radius:0;border-top:0;border-left:0;border-bottom:0;transform-origin:0 100%;animation:chat-panel-in .34s cubic-bezier(.16,1,.3,1) both}body.chat-workspace-open header,body.chat-workspace-open main{margin-left:min(390px,32vw)}body.chat-workspace-open main{padding-left:14px}.chat-panel.open{display:grid}@keyframes agent-bar-breathe{0%,100%{box-shadow:0 20px 70px rgba(0,0,0,.45),var(--glow),0 0 0 0 rgba(39,199,167,0)}50%{box-shadow:0 20px 70px rgba(0,0,0,.45),var(--glow),0 0 0 8px rgba(39,199,167,.055)}}
@media(max-width:1180px){header{grid-template-columns:minmax(170px,210px) minmax(330px,1fr) auto}.status{grid-column:1/-1;max-width:none;justify-content:flex-start}main{grid-template-columns:300px minmax(0,1fr)}.rail{grid-column:1/-1}.campaign-grid{grid-template-columns:1fr}.kpis{grid-template-columns:repeat(2,1fr)}body.chat-workspace-open .chat-panel{width:360px}body.chat-workspace-open header,body.chat-workspace-open main{margin-left:360px}body.chat-workspace-open main{padding-left:14px}}
@media(max-width:780px){
 body{background-attachment:scroll}
 .onboarding-flow{padding:12px}.onboarding-shell{grid-template-columns:1fr}.onboarding-side{position:static}.onboarding-card{padding:14px}.onboarding-mini.two{grid-template-columns:1fr}.guide-hero{grid-template-columns:1fr;padding:12px}.guide-actions,.guide-support-grid,.passive-guide{grid-template-columns:1fr}.guide-visual{grid-template-columns:1fr}.guide-arrow{display:none}
 header{display:grid;grid-template-columns:1fr auto;gap:10px;padding:12px;position:sticky}.tabs,.status{grid-column:1/-1}
 .brand{min-width:0;width:100%;padding-left:34px}.brand h1{font-size:15px}.brand div{font-size:10px}
 .tabs{width:100%;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));overflow:visible;scrollbar-width:none}.tabs::-webkit-scrollbar{display:none}.tab{min-width:0;padding:8px 8px;flex:initial}
 .status{margin-left:0;width:100%;display:grid;grid-template-columns:auto repeat(3,minmax(0,1fr));gap:5px;overflow:visible;padding-bottom:0;scrollbar-width:none;max-width:none}.status::-webkit-scrollbar{display:none}.pill,.lang-select{width:auto;min-width:0;height:28px;padding:5px 8px;font-size:10px}.pill{display:flex;align-items:center;justify-content:center;gap:4px;overflow:hidden}.pill .tip{min-width:0}.pill .help-dot{display:none}.pill strong{overflow:hidden;text-overflow:ellipsis;font-size:10px}.pill span[data-i18n=updated]{display:none}.lang-select{max-width:58px}
 main,body.left-panel-open.right-panel-open main,body.left-panel-open:not(.right-panel-open) main,body:not(.left-panel-open).right-panel-open main,body:not(.left-panel-open):not(.right-panel-open) main{display:grid;grid-template-columns:1fr;gap:12px;padding:10px;min-height:auto}
 .col{border:0;overflow:visible}.col:before{position:static;margin-bottom:8px}.zone-label,body:not(.left-panel-open) .brief-zone .zone-label,body:not(.right-panel-open) .rail .zone-label{position:static;margin-bottom:9px;min-height:auto;writing-mode:horizontal-tb;padding:9px 11px}
 .page-title{align-items:flex-start;flex-direction:column;padding:13px}.page-title h2{font-size:17px}.signal{white-space:normal}
 .kpis{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.kpi{padding:12px}.kpi .v{font-size:19px}.kpi .l{font-size:9px}
 .campaign-grid{grid-template-columns:1fr;gap:11px}.card{padding:12px}.top h3{font-size:13px}.metrics{grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.metric b{font-size:14px}
 .actions{grid-template-columns:1fr;gap:7px}.btn{width:100%;min-height:38px}
 .agent-chat-bar{left:12px;right:12px;bottom:12px;width:auto;transform:none;border-radius:18px}.chat-fab{right:12px;bottom:12px}.chat-panel{right:12px;bottom:66px;height:min(560px,calc(100vh - 78px))}body.chat-workspace-open .chat-panel{left:0;right:0;top:0;bottom:0;width:auto;height:100vh;border-radius:0}body.chat-workspace-open header,body.chat-workspace-open main{margin-left:0}body.chat-workspace-open main{padding-left:10px}
 .section{margin-bottom:12px}.section .body{overflow-x:auto}.head{padding:10px}.head b{font-size:12px}
 .onboarding-head{flex-direction:column}.progress{text-align:left}.setup-step{grid-template-columns:auto 1fr}.step-badge{grid-column:2;grid-row:2;padding-top:0}
 .trust-grid{grid-template-columns:1fr}.next-step,.mode-panel{align-items:flex-start;flex-direction:column}.copy-btn,.mode-actions{width:100%}.mode-actions .btn{flex:1}
 #recs-table{display:none}.mobile-recs{display:block}
 .form-grid{grid-template-columns:1fr}table{min-width:560px}.brief-q p,.notice,.log-item{font-size:12px}
}
@media(max-width:420px){
 .kpis{grid-template-columns:1fr}.metrics{grid-template-columns:1fr}.floating-tip{max-width:calc(100vw - 18px)}
}
.business-summary-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.business-summary-grid div{border:1px solid rgba(255,255,255,.11);border-radius:8px;background:rgba(0,0,0,.13);padding:10px}.business-summary-grid b{display:block;font-size:10px;text-transform:uppercase;color:var(--dim);margin-bottom:5px}.business-summary-grid span{display:block;font-size:12px;line-height:1.35}.business-hero{background:linear-gradient(135deg,rgba(39,199,167,.1),rgba(99,168,255,.08),rgba(244,183,64,.06))}@media(max-width:760px){.business-summary-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<section class="onboarding-flow" id="onboarding-flow" aria-modal="true" role="dialog"></section>
<header>
<div class="brand"><h1>Meta <span>Ads Agent</span></h1><div data-i18n="brand_subtitle">Self-hosted local/VPS operator</div></div>
<nav class="tabs">
<button class="tab active" data-tab="overview" data-i18n="tab_overview">Overview</button>
<button class="tab" data-tab="setup" data-i18n="tab_setup">Setup</button>
<button class="tab" data-tab="creator" data-i18n="tab_creator">Creator</button>
<button class="tab" data-tab="audiences" data-i18n="tab_audiences">Audiences</button>
<button class="tab" data-tab="creatives" data-i18n="tab_creatives">Creatives</button>
<button class="tab" data-tab="reports" data-i18n="tab_reports">Reports</button>
</nav>
<button class="header-guide-btn" type="button" onclick="openUsageGuide()" aria-label="Guía rápida" title="Guía rápida">?</button>
<div class="status">
<select class="lang-select" id="language-select" aria-label="Language"><option value="es">ES</option><option value="en">EN</option></select>
<div class="pill"><span id="top-roas"></span> <strong id="s-roas">--</strong></div>
<div class="pill"><span id="top-cpa"></span> <strong id="s-cpa">--</strong></div>
<div class="pill"><span id="top-mode"></span> <strong id="s-mode">--</strong></div>
<div class="pill"><span data-i18n="updated">Updated</span> <strong id="s-updated">--</strong></div>
</div>
</header>
<main>
<aside class="col brief-zone">
<button class="zone-label" id="toggle-left-panel" type="button" onclick="togglePanel('left')"><span data-i18n="zone_brief">Daily intelligence</span><i class="panel-caret" aria-hidden="true"></i></button>
<section class="section"><div class="head"><span>01</span><b data-i18n="daily_brief">Daily Brief</b><button class="btn ask-btn" onclick="openChat(t('draft_catchup'))" data-i18n="ask_agent">Ask agent</button><button class="btn" onclick="runAgent()" data-i18n="run">Run</button></div><div class="body" id="brief"></div></section>
<section class="section"><div class="head"><span>02</span><b data-i18n="fatigue_monitor">Fatigue Monitor</b><button class="btn ask-btn" onclick="openChat(t('draft_fatigue'))" data-i18n="ask_agent">Ask agent</button></div><div class="body" id="fatigue"></div></section>
</aside>
<section class="col work-zone">
<div class="zone-label" data-i18n="zone_work">Campaign workspace</div>
<div id="tab-overview">
<div class="page-title"><div><h2 data-i18n="control_center">Control Center</h2><p data-i18n="control_subtitle">Daily decisions, risk signals, and ad account health in one place.</p></div><button class="btn ask-btn" onclick="openChat(t('draft_where_are_we'))" data-i18n="ask_manager">Ask manager</button><button class="btn primary hidden" id="real-data-refresh" onclick="refreshInsights()">Actualizar datos reales</button><div class="signal" id="data-source-signal">--</div><div class="signal" data-i18n="safe_mode">Safe mode active</div></div>
<div class="kpis" id="kpis"></div>
<div class="campaign-grid" id="campaigns"></div>
</div>
<div id="tab-setup" class="hidden">
<section class="section"><div class="head"><span>03</span><b data-i18n="setup_status">Setup Status</b><button class="btn ask-btn" onclick="openChat(t('draft_setup'))" data-i18n="ask_agent">Ask agent</button><button class="btn" onclick="load()" data-i18n="refresh">Refresh</button></div><div class="body"><div id="mode-control"></div><div id="guardrails-panel"></div><div id="onboarding-wizard"></div><div id="license-panel"></div><div id="agency-panel"></div><div id="setup-config"></div><div id="telegram-panel"></div><div id="setup-summary"></div><div id="setup-sections"></div></div></section>
</div>
<div id="tab-creator" class="hidden">
<section class="section"><div class="head"><span>04</span><b data-i18n="campaign_creator">Campaign Creator</b></div><div class="body">
<div class="guide-card"><b data-i18n="paused_draft_title">Safe draft mode</b><p data-i18n="paused_draft_body">New campaigns, ad sets and ads are created paused first. This is not the bad pause/resume habit that interrupts learning; it is a safe draft before the campaign ever spends money.</p></div>
<form id="campaign-form" class="form-grid">
<div class="field wide"><label data-i18n="name">Name</label><input name="name" value="New Purchase Campaign" required></div>
<div class="field"><label data-i18n="objective">Objective</label><select name="objective"><option>PURCHASES</option><option>LEADS</option><option>CONVERSIONS</option></select></div>
<div class="field"><label>Pixel ID</label><input name="pixel_id" placeholder="optional"></div>
<div class="field"><label data-i18n="daily_budget">Daily Budget</label><input type="number" name="daily_budget" value="75" min="10"></div>
<div class="field"><label data-i18n="total_budget">Total Budget</label><input type="number" name="total_budget" value="2250" min="100"></div>
<div class="field"><label data-i18n="locations">Locations</label><input name="locations" value="US"></div>
<div class="field"><label data-i18n="interests">Interests</label><input name="interests" value="online shopping, ecommerce"></div>
<div class="field"><label data-i18n="age_min">Age Min</label><input type="number" name="age_min" value="25"></div>
<div class="field"><label data-i18n="age_max">Age Max</label><input type="number" name="age_max" value="54"></div>
<div class="field"><label data-i18n="creative_variations">Creative Variations</label><input type="number" name="creative_variations" value="3" min="1" max="10"></div>
<div class="field"><label data-i18n="ab_test">A/B Test</label><select name="ab_test"><option value="true" data-i18n="enabled">Enabled</option><option value="" data-i18n="disabled">Disabled</option></select></div>
<div class="field wide"><label>Texto principal</label><input name="primary_text" value="Hice el analisis y esta oferta esta lista para probarse con una campaña clara."></div>
<div class="field"><label>Titular</label><input name="headline" value="Mejora tus resultados hoy"></div>
<div class="field"><label>Imagen creativa</label><input name="creative_image_path" placeholder="/ruta/a/imagen.png"></div>
<div class="field"><label>Link de destino</label><input name="landing_url" placeholder="https://..."></div>
<div class="field"><label>Estado final</label><select name="final_status"><option value="ACTIVE">Activo despues de aprobar</option><option value="PAUSED">Borrador pausado</option></select></div>
<div class="field"><label><input type="checkbox" name="active_spend_confirmed" value="true"> Sí, crear y dejar activo</label></div>
<div class="field wide"><button class="btn primary" type="submit" data-i18n="stage_campaign">Stage Campaign For Approval</button></div>
</form>
</div></section>
</div>
<div id="tab-audiences" class="hidden">
<section class="section"><div class="head"><span>05</span><b data-i18n="audience_builder">Audience Builder</b><button class="btn ask-btn" onclick="openChat(t('draft_audience'))" data-i18n="ask_agent">Ask agent</button></div><div class="body">
<form id="audience-form" class="form-grid">
<div class="field wide"><label data-i18n="what_sell">What do you sell?</label><input name="product" value="Online course for small business owners"></div>
<div class="field wide"><label data-i18n="who_buys">Who buys today?</label><input name="buyer" value="Small business owners who want more leads"></div>
<div class="field"><label data-i18n="objective">Objective</label><select name="objective"><option value="Compras">Compras</option><option value="Leads">Leads</option><option value="Mensajes">Mensajes</option></select></div>
<div class="field"><label data-i18n="locations">Locations</label><input name="locations" value="Mexico, Colombia, Chile"></div>
<div class="field"><label data-i18n="age_range">Age range</label><input name="age" value="25-54"></div>
<div class="field"><label data-i18n="budget_level">Budget level</label><select name="budget_level"><option value="small">Small</option><option value="medium">Medium</option><option value="scale">Scale</option></select></div>
<div class="field wide"><label data-i18n="interests">Interests</label><input name="interests" value="emprendimiento, marketing digital, ecommerce"></div>
<div class="field wide"><label data-i18n="data_sources">Data sources</label><input name="data_sources" value="Pixel purchases, Instagram engagement"></div>
<div class="field wide"><label><input name="consent" type="checkbox"> <span data-i18n="consent_upload">I have consent to use customer emails/phones if I upload them later.</span></label></div>
<div class="field wide"><label data-i18n="notes">Notes</label><input name="notes" placeholder="Optional"></div>
<div class="field wide"><button class="btn primary" type="submit" data-i18n="build_audience">Build Audience Strategy</button></div>
</form>
<div id="audience-result" style="margin-top:12px"></div>
</div></section>
</div>
<div id="tab-creatives" class="hidden">
<section class="section"><div class="head"><span>05</span><b>Guías de marca para Codex</b><button class="btn ask-btn" onclick="openChat('Ayudame a crear una guia visual consistente para mis creativos de Meta Ads.')">Preguntar</button></div><div class="body"><div id="brand-guides-panel"></div></div></section>
<section class="section"><div class="head"><span>05</span><b data-i18n="creative_refresh">Creative Refresh</b><button class="btn" onclick="generateRefresh()" data-i18n="generate_drafts">Generate Drafts</button></div><div class="body"><div id="creative-list"></div></div></section>
<section class="section"><div class="head"><span>06</span><b data-i18n="upload_payloads">Upload Payloads</b></div><div class="body"><div id="upload-list"></div></div></section>
</div>
<div id="tab-reports" class="hidden">
<section class="section"><div class="head"><span>07</span><b data-i18n="campaign_comparison">Campaign Comparison</b><button class="btn" onclick="exportCsv()" data-i18n="export_csv">Export CSV</button></div><div class="body"><table><thead><tr><th data-i18n="campaign">Campaign</th><th id="th-spend"></th><th id="th-roas"></th><th id="th-cpa"></th><th id="th-ctr"></th><th data-i18n="status">Status</th></tr></thead><tbody id="report-rows"></tbody></table></div></section>
</div>
</section>
<aside class="col rail">
<button class="zone-label" id="toggle-right-panel" type="button" onclick="togglePanel('right')"><span data-i18n="zone_actions">Approvals and activity</span><i class="panel-caret" aria-hidden="true"></i></button>
<section class="section"><div class="head"><span>05</span><b data-i18n="budget_optimizer">Budget Optimizer</b><button class="btn ask-btn" onclick="openChat(t('draft_budget'))" data-i18n="ask_agent">Ask agent</button></div><div class="body"><table id="recs-table"><thead><tr><th data-i18n="campaign">Campaign</th><th data-i18n="now">Now</th><th data-i18n="rec">Rec</th><th></th></tr></thead><tbody id="recs"></tbody></table><div class="mobile-recs" id="recs-mobile"></div></div></section>
<section class="section"><div class="head"><span>06</span><b data-i18n="pending_approvals">Pending Approvals</b></div><div class="body" id="pending"></div></section>
<section class="section"><div class="head"><span>07</span><b data-i18n="action_log">Action Log</b></div><div class="body" id="actions"></div></section>
</aside>
</main>
<div class="toast" id="toast"></div>
<section class="confirm-overlay" id="confirm-overlay" aria-modal="true" role="dialog"></section>
<section class="guide-overlay" id="guide-overlay" aria-modal="true" role="dialog"></section>
<div class="floating-tip" id="floating-tip" role="tooltip"></div>
<form class="agent-chat-bar" id="agent-chat-bar">
<div class="agent-bar-mark">AI</div>
<button class="agent-bar-expand" type="button" onclick="openChat()" aria-label="Abrir conversación completa" title="Abrir conversación completa">⌃</button>
<textarea id="agent-bar-input" rows="1" data-i18n-placeholder="chat_fab"></textarea>
<button class="agent-bar-send" type="submit" aria-label="Send">↑</button>
</form>
<section class="chat-panel" id="chat-panel" aria-live="polite">
<div class="chat-head"><div class="chat-avatar">AI</div><div class="chat-title"><b data-i18n="chat_title">Meta Ads Manager</b><span data-i18n="chat_subtitle">Ask for catchups, actions, or explanations.</span></div><button class="btn" onclick="newChatConversation()" data-i18n="new_chat">New chat</button><button class="btn chat-close" onclick="closeChat()">×</button></div>
<div class="chat-log" id="chat-log"></div>
<div class="chat-quick"><button class="chip" onclick="openChat(t('draft_where_are_we'))" data-i18n="quick_status">Where are we?</button><button class="chip" onclick="openChat(t('draft_budget'))" data-i18n="quick_budget">Review budget</button><button class="chip" onclick="openChat(t('draft_fatigue'))" data-i18n="quick_fatigue">Check fatigue</button></div>
<form class="chat-form" id="chat-form"><textarea id="chat-input" rows="2"></textarea><button class="btn primary" type="submit" data-i18n="send">Send</button></form>
</section>
<section class="unlock-overlay" id="unlock-overlay" aria-modal="true" role="dialog">
<div class="unlock-card">
<h2 data-i18n="unlock_title">Unlock dashboard</h2>
<p data-i18n="unlock_body">Enter the dashboard password you created during onboarding. This protects important actions in your Meta account.</p>
<form class="unlock-form" id="unlock-form">
<label for="unlock-password" data-i18n="dashboard_password">Dashboard password</label>
<input id="unlock-password" type="password" autocomplete="current-password">
<label><input id="remember-device" type="checkbox" checked> <span data-i18n="remember_device">Remember this device</span></label>
<div class="unlock-error" id="unlock-error"></div>
<button class="btn primary" type="submit" data-i18n="unlock_button">Unlock dashboard</button>
</form>
</div>
</section>
<script>
let state=null;
let chatHistory=[];
let chatHydrated=false;
let onboardingFlowStep=0;
let onboardingFlowTouched=false;
let destinationAutoDiscoveryKey='';
const fmtMoney=n=>'$'+Number(n||0).toLocaleString(undefined,{maximumFractionDigits:2});
const fmtPct=n=>Number(n||0).toFixed(2)+'%';
const qs=s=>document.querySelector(s);
let lang=localStorage.getItem('dashboardLang')||'es';
const copy={
 en:{
	  brand_subtitle:'Self-hosted local/VPS operator',zone_brief:'Daily intelligence',zone_work:'Campaign workspace',zone_actions:'Approvals and activity',control_center:'Control Center',control_subtitle:'Daily decisions, risk signals, and ad account health in one place.',safe_mode:'Safe mode active',ask_agent:'Ask agent',ask_manager:'Ask manager',chat_fab:'Talk to agent',chat_title:'Meta Ads Manager',chat_subtitle:'Ask for catchups, actions, or explanations.',new_chat:'New chat',quick_status:'Where are we?',quick_budget:'Review budget',quick_fatigue:'Check fatigue',send:'Send',usage_guide:'Guide',tab_overview:'Overview',tab_setup:'Setup',tab_creator:'Creator',tab_audiences:'Audiences',tab_creatives:'Creatives',tab_reports:'Reports',updated:'Updated',daily_brief:'Daily Brief',run:'Refresh',fatigue_monitor:'Fatigue Monitor',setup_status:'Setup Status',setup_form_title:'Buyer setup fields',setup_form_body:'Save the few account details the assistant needs. No technical file editing here.',license_panel_title:'License unlock',license_panel_body:'Activate the license before live setup. If cloud validation is configured, this device checks your seller domain and caches a safe unlock.',license_active:'Active',license_missing:'Missing',license_invalid:'Needs attention',license_cloud:'Cloud validation',license_local:'Local license',license_activate:'Activate license',license_key:'License key',buyer_email:'Buyer email',ad_account_id:'Ad account',page_id:'Facebook page',instagram_actor_id:'Instagram profile',default_adset_id:'Advanced field',landing_url:'Website link',save_setup:'Save',refresh:'Refresh',campaign_creator:'Campaign Creator',paused_draft_title:'Safe draft mode',paused_draft_body:'New campaigns, ad sets and ads are created paused first. This is not the bad pause/resume habit that interrupts learning; it is a safe draft before the campaign ever spends money.',audience_builder:'Audience Builder',what_sell:'What do you sell?',who_buys:'Who buys today?',age_range:'Age range',budget_level:'Budget level',data_sources:'Data sources',consent_upload:'I have consent to use customer emails/phones if I upload them later.',notes:'Notes',build_audience:'Build Audience Strategy',lookalike_status:'Lookalike status',recommended_audiences:'Recommended audiences',next_steps:'Next steps',name:'Name',objective:'Objective',daily_budget:'Daily Budget',total_budget:'Total Budget',locations:'Locations',interests:'Interests',age_min:'Age Min',age_max:'Age Max',creative_variations:'Creative Variations',ab_test:'A/B Test',enabled:'Enabled',disabled:'Disabled',stage_campaign:'Stage Campaign For Approval',creative_refresh:'Creative Refresh',generate_drafts:'Generate Drafts',upload_payloads:'Upload Payloads',campaign_comparison:'Campaign Comparison',export_csv:'Export CSV',campaign:'Campaign',status:'Status',budget_optimizer:'Budget Optimizer',now:'Now',rec:'Rec',pending_approvals:'Pending Approvals',action_log:'Action Log',
  spend:'Spend',revenue:'Revenue',conversions:'Conversions',active_budget:'Active Budget',active_daily_budget:'Active daily budget',roas:'ROAS',cpa:'CPA',ctr:'CTR',cpc:'CPC',frequency:'Frequency',mode:'Mode',ok:'OK',warnings:'Warnings',blocked:'Blocked',live_ready:'Live Ready',
  spend_tip:'How much money has been spent on ads in this period.',revenue_tip:'How much sales value the ads are estimated to have produced.',conversions_tip:'How many desired actions happened, such as purchases, leads, or signups.',active_budget_tip:'The total daily budget still running across active campaigns.',active_daily_budget_tip:'The total daily ad budget currently running across active campaigns.',daily_budget_tip:'How much the campaign is allowed to spend per day.',roas_tip:'Return on ad spend. If ROAS is 3x, every $1 in ads brought about $3 back.',cpa_tip:'Cost per acquisition. This is roughly what you paid to get one conversion.',ctr_tip:'Click-through rate. The percent of people who saw the ad and clicked it.',cpc_tip:'Cost per click. The average amount paid for one click.',frequency_tip:'How many times the average person has seen the ad. High frequency can mean people are getting tired of it.',mode_tip:'The current control level. Supervised means real data is read, but changes wait for approval; autopilot can act inside your rules.',ok_tip:'Items already configured correctly.',warnings_tip:'Items that are not blocking the demo, but should be reviewed before going live.',blocked_tip:'Items that must be fixed before the full live workflow can run.',live_ready_tip:'Whether the install has the key pieces needed before live Meta Ads actions are allowed.',
  no_fatigue:'No fatigue triggers right now.',no_pending:'No pending approvals.',no_actions:'No actions logged yet.',no_creatives:'No creative refresh drafts yet.',no_uploads:'No upload payloads staged yet.',request:'Request',apply:'Apply',approve:'Approve',stage_v1_upload:'Stage v1 Upload',missing:'Missing',variants:'variants',increase_budget:'Increase budget',adjust_budget:'Adjust budget',refresh_creative:'Refresh creative',pause:'Pause',resume:'Resume',details:'Details',
  q_track:'Am I on track?',q_running:"What's running?",q_performance:"How's performance?",q_winners:"Who's winning or losing?",q_fatigue:'Any fatigue?',
	  live_ready_yes:'Yes',live_ready_no:'No',check:'Check',draft_where_are_we:'Give me a business catch-up: where are we today, what should I watch, and what would you do next?',draft_catchup:'Explain today’s daily brief like my Meta Ads manager. What matters most?',draft_fatigue:'Review fatigue risk. Which ads need new creative and why?',draft_budget:'Review the budget optimizer. Which recommendations are safe and which need caution?',draft_setup:'Review setup status. What blocks us from going live safely?',draft_audience:'Help me choose targeting. Ask me only what is missing, then recommend broad, interest, retargeting, and lookalike options safely.',chat_welcome:'Hi, I’m your Meta Ads manager. Ask me for a catch-up, a decision, or help taking an action.',chat_summary:'Here is the catch-up: account ROAS is {roas}x, CPA is {cpa}, active budget is {budget}, and {pending} approval(s) are pending. The safest next step is to review budget recommendations and fatigue before going live.',chat_budget:'Budget view: compare current vs suggested budgets. For winning campaigns, scale carefully; for weak campaigns, fix creative or pause before adding spend.',chat_fatigue:'Fatigue view: watch frequency, CTR drops, and rising CPC. If fatigue is present, generate creative refresh drafts before increasing budget.',chat_setup:'Setup view: check blocked items first. Live actions stay protected until credentials, destination IDs, and the live-action switch are ready.',chat_action_hint:'I can open the right workflow from here. For live account changes, the approval queue and dashboard password still protect the account.',toast_resume:'Resume staged for approval',toast_action:'Action complete',toast_budget:'Budget action recorded',toast_daily:'Daily agent report generated',toast_export:'CSV exported: ',toast_approval:'Approval executed',toast_refresh:'Creative refresh draft generated',toast_upload:'Upload payload staged',toast_audience:'Audience strategy generated',toast_setup_saved:'Setup fields saved',toast_license:'License checked',toast_details:'Campaign details visible on this card.',prompt_budget:'New daily budget',unlock_title:'Unlock dashboard',unlock_body:'Enter the dashboard password you created during onboarding. This protects important actions in your account.',dashboard_password:'Dashboard password',remember_device:'Remember this device',unlock_button:'Unlock dashboard',unlock_needed:'Enter the dashboard password you created during onboarding.',unlock_failed:'That password did not unlock the dashboard. Try the password you created during onboarding.',copy_command:'Copy',copied:'Copied'
 },
 es:{
	  brand_subtitle:'Operador local/VPS para Meta Ads',zone_brief:'Lectura diaria',zone_work:'Área de campañas',zone_actions:'Aprobaciones y actividad',control_center:'Centro de control',control_subtitle:'Decisiones diarias, señales de riesgo y salud de la cuenta en un solo lugar.',safe_mode:'Modo seguro activo',ask_agent:'Preguntar',ask_manager:'Hablar con manager',chat_fab:'Hablar con el agente',chat_title:'Manager de Meta Ads',chat_subtitle:'Pide resumen, decisiones o acciones.',new_chat:'Nuevo chat',quick_status:'¿Dónde estamos?',quick_budget:'Revisar presupuesto',quick_fatigue:'Ver fatiga',send:'Enviar',usage_guide:'Guía',tab_overview:'Resumen',tab_setup:'Configuración',tab_creator:'Creador',tab_audiences:'Audiencias',tab_creatives:'Creatividades',tab_reports:'Reportes',updated:'Actualizado',daily_brief:'Resumen diario',run:'Actualizar',fatigue_monitor:'Fatiga de anuncios',setup_status:'Estado de configuración',setup_form_title:'Datos de configuración',setup_form_body:'Guarda aquí los poquitos datos que necesita el asistente. No tienes que editar archivos técnicos.',license_panel_title:'Activación de licencia',license_panel_body:'Activa la licencia antes de configurar el uso real. Si la validación cloud está configurada, este equipo consulta tu dominio y guarda un desbloqueo seguro.',license_active:'Activa',license_missing:'Falta',license_invalid:'Revisar',license_cloud:'Validación cloud',license_local:'Licencia local',license_activate:'Activar licencia',license_key:'Licencia',buyer_email:'Email del comprador',ad_account_id:'Cuenta publicitaria',page_id:'Página de Facebook',instagram_actor_id:'Perfil de Instagram',default_adset_id:'Campo avanzado',landing_url:'Link de tu web',save_setup:'Guardar',refresh:'Actualizar',campaign_creator:'Creador de campañas',paused_draft_title:'Borrador seguro antes de gastar',paused_draft_body:'Las campañas, grupos de anuncios y anuncios nuevos se crean en pausa primero. No es la mala práctica de prender y apagar algo que ya está aprendiendo; es un borrador seguro antes de que gaste dinero.',audience_builder:'Constructor de audiencias',what_sell:'¿Qué vendes?',who_buys:'¿Quién compra hoy?',age_range:'Rango de edad',budget_level:'Nivel de presupuesto',data_sources:'Fuentes de datos',consent_upload:'Tengo consentimiento para usar emails/teléfonos de clientes si los subo después.',notes:'Notas',build_audience:'Crear estrategia de audiencias',lookalike_status:'Estado de lookalike',recommended_audiences:'Audiencias recomendadas',next_steps:'Siguientes pasos',name:'Nombre',objective:'Objetivo',daily_budget:'Presupuesto diario',total_budget:'Presupuesto total',locations:'Países/ubicaciones',interests:'Intereses',age_min:'Edad mínima',age_max:'Edad máxima',creative_variations:'Variaciones creativas',ab_test:'Prueba A/B',enabled:'Activada',disabled:'Desactivada',stage_campaign:'Preparar campaña para aprobación',creative_refresh:'Renovación creativa',generate_drafts:'Generar borradores',upload_payloads:'Paquetes de subida',campaign_comparison:'Comparación de campañas',export_csv:'Exportar CSV',campaign:'Campaña',status:'Estado',budget_optimizer:'Optimizador de presupuesto',now:'Actual',rec:'Sugerido',pending_approvals:'Aprobaciones pendientes',action_log:'Registro de acciones',
  spend:'Gasto',revenue:'Ingresos',conversions:'Conversiones',active_budget:'Presupuesto activo',active_daily_budget:'Presupuesto diario activo',roas:'ROAS',cpa:'CPA',ctr:'CTR',cpc:'CPC',frequency:'Frecuencia',mode:'Modo',ok:'OK',warnings:'Alertas',blocked:'Bloqueado',live_ready:'Listo para acciones reales',
  spend_tip:'Cuánto dinero se gastó en anuncios durante este periodo.',revenue_tip:'Valor estimado de ventas que generaron los anuncios.',conversions_tip:'Cantidad de acciones importantes logradas: compras, leads, registros u otro objetivo.',active_budget_tip:'Suma del presupuesto diario que sigue activo en las campañas encendidas.',active_daily_budget_tip:'Presupuesto diario total que está corriendo ahora en las campañas activas.',daily_budget_tip:'Monto máximo que una campaña puede gastar por día.',roas_tip:'Retorno de la inversión publicitaria. Si el ROAS es 3x, cada $1 en anuncios generó aproximadamente $3.',cpa_tip:'Costo por adquisición. Aproximadamente cuánto pagaste en anuncios para conseguir una compra, lead o conversión.',ctr_tip:'Porcentaje de personas que vieron el anuncio y dieron clic. Ayuda a medir qué tan atractivo es el anuncio.',cpc_tip:'Costo por clic. Promedio que pagas cada vez que alguien hace clic.',frequency_tip:'Promedio de veces que una persona vio el anuncio. Si sube mucho, la audiencia puede estar cansándose.',mode_tip:'Nivel de control actual. Con supervisión lee datos reales y ejecuta solo lo que apruebas; piloto automático puede actuar dentro de tus reglas.',ok_tip:'Elementos configurados correctamente.',warnings_tip:'No bloquean la demostración, pero conviene revisarlos antes de permitir acciones reales.',blocked_tip:'Elementos que debes corregir antes de usar acciones reales en Meta.',live_ready_tip:'Indica si ya están las piezas clave para permitir acciones reales en Meta Ads.',
  no_fatigue:'No hay señales de fatiga por ahora.',no_pending:'No hay aprobaciones pendientes.',no_actions:'Todavía no hay acciones registradas.',no_creatives:'Todavía no hay borradores creativos.',no_uploads:'Todavía no hay paquetes de subida preparados.',request:'Solicitar',apply:'Aplicar',approve:'Aprobar',stage_v1_upload:'Preparar subida v1',missing:'Falta',variants:'variantes',increase_budget:'Subir presupuesto',adjust_budget:'Ajustar presupuesto',refresh_creative:'Renovar creativo',pause:'Pausar',resume:'Reactivar',details:'Detalles',
  q_track:'¿Voy bien?',q_running:'¿Qué está corriendo?',q_performance:'¿Cómo va el rendimiento?',q_winners:'¿Qué gana y qué pierde?',q_fatigue:'¿Hay fatiga?',
	  live_ready_yes:'Sí',live_ready_no:'No',check:'Revisar',draft_where_are_we:'Dame un catch-up del negocio: dónde estamos hoy, qué debo vigilar y qué harías después.',draft_catchup:'Explícame el resumen diario como mi manager de Meta Ads. ¿Qué es lo más importante?',draft_fatigue:'Revisa el riesgo de fatiga. ¿Qué anuncios necesitan creativo nuevo y por qué?',draft_budget:'Revisa el optimizador de presupuesto. ¿Qué recomendaciones son seguras y cuáles requieren cuidado?',draft_setup:'Revisa el estado de configuración. ¿Qué nos falta para activar piloto automático con seguridad?',draft_audience:'Ayúdame a elegir segmentación. Pregúntame solo lo que falte y recomiéndame opciones amplias, intereses, retargeting y lookalike con seguridad.',chat_welcome:'Hola, soy tu manager de Meta Ads. Pídeme un resumen, una decisión o ayuda para ejecutar una acción.',chat_summary:'Catch-up: el ROAS de la cuenta es {roas}x, el CPA es {cpa}, el presupuesto activo es {budget} y hay {pending} aprobación(es) pendientes. El siguiente paso más seguro es revisar presupuesto y fatiga antes de escalar.',chat_budget:'Presupuesto: compara el presupuesto actual contra el sugerido. En campañas ganadoras, escala con cuidado; en campañas débiles, mejora creativo o pausa antes de meter más dinero.',chat_fatigue:'Fatiga: vigila frecuencia, caída de CTR y subida de CPC. Si hay fatiga, genera borradores creativos antes de subir presupuesto.',chat_setup:'Configuración: resuelve primero los bloqueos. Las acciones reales requieren una aprobación exacta o piloto automático activo dentro de tus reglas.',chat_action_hint:'Puedo abrir el flujo correcto desde aquí. Para cambios reales, la cola de aprobaciones y la contraseña del dashboard siguen protegiendo la cuenta.',toast_resume:'Reactivación enviada a aprobación',toast_action:'Acción completada',toast_budget:'Acción de presupuesto registrada',toast_daily:'Resumen diario generado',toast_export:'CSV exportado: ',toast_approval:'Aprobación ejecutada',toast_refresh:'Borrador creativo generado',toast_upload:'Paquete de subida preparado',toast_audience:'Estrategia de audiencias generada',toast_setup_saved:'Configuración guardada',toast_license:'Licencia revisada',toast_details:'Los detalles clave están visibles en esta tarjeta.',prompt_budget:'Nuevo presupuesto diario',unlock_title:'Desbloquear dashboard',unlock_body:'Escribe la contraseña del dashboard que creaste durante el onboarding. Esto protege acciones importantes de tu cuenta.',dashboard_password:'Contraseña del dashboard',remember_device:'Recordar este dispositivo',unlock_button:'Desbloquear dashboard',unlock_needed:'Escribe la contraseña del dashboard que creaste durante el onboarding.',unlock_failed:'Esa contraseña no desbloqueó el dashboard. Prueba la contraseña que creaste durante el onboarding.',copy_command:'Copiar',copied:'Copiado'
 }
};
const labelKeys={Spend:'spend',Revenue:'revenue',Conversions:'conversions','Active Budget':'active_budget',ROAS:'roas',CPA:'cpa',CTR:'ctr',CPC:'cpc',Frequency:'frequency',frequency:'frequency',conversions:'conversions','Active daily budget':'active_daily_budget','active daily budget':'active_daily_budget','daily budget':'daily_budget',Mode:'mode',OK:'ok',Warnings:'warnings',Blocked:'blocked','Live Ready':'live_ready'};
const questionKeys={'Am I on track?':'q_track',"What's running?":'q_running',"How's performance?":'q_performance',"Who's winning/losing?":'q_winners',"Who's winning or losing?":'q_winners','Any fatigue?':'q_fatigue'};
const esText={
 Files:'Archivos',Runtime:'Ejecución',Security:'Seguridad','Meta Live Requirements':'Requisitos para acciones reales en Meta','Creative Generation':'Generación creativa','Agent Chat':'Chat del agente',Telegram:'Telegram','Upload Readiness':'Preparación de subida',Scheduler:'Programador',
 '.env config':'Configuración .env','ad-config.json':'ad-config.json','Metrics cache':'Cache de métricas','Dashboard script':'Script del dashboard','Daily agent script':'Script del agente diario','Agent mode':'Modo del agente','Primary connector':'Conector principal','social-cli installed':'social-cli instalado','social-cli onboarding':'Onboarding de social-cli','Latest daily report':'Último reporte diario','Latest action log':'Última acción registrada','Dashboard bind host':'Host del dashboard','Dashboard write token':'Contraseña del dashboard','Dashboard password':'Contraseña del dashboard','Token required for writes':'Contraseña requerida para acciones','Password required for actions':'Contraseña requerida para acciones','License key':'Licencia','Public dashboard opt-in':'Dashboard público habilitado','Live-action kill switch':'Permiso de piloto automático','.env permissions':'Permisos de .env','Dashboard data permissions':'Permisos de datos del dashboard','Output permissions':'Permisos de output','Logs permissions':'Permisos de logs','Meta ad account':'Cuenta publicitaria de Meta','Direct Graph token':'Token directo de Graph','Page ID':'ID de la página','Landing page URL':'URL de destino','Creative refresh enabled':'Renovación creativa activada','Creative image mode':'Modo de imagen creativa','Nano Banana / Gemini key':'Clave de Nano Banana / Gemini','Creative drafts':'Borradores creativos','Agent chat provider':'Proveedor del chat','Agent chat model':'Modelo del chat','MiniMax API key':'API key de MiniMax','Telegram agent access':'Acceso del agente por Telegram','Telegram bot':'Bot de Telegram','Allowed Telegram chat':'Chat permitido de Telegram','Upload staging index':'Índice de subidas preparadas','Latest upload payload':'Último paquete de subida','Cron setup script':'Script de cron','VPS systemd setup script':'Script systemd para VPS','Logs directory':'Carpeta de logs',
 'No daily report yet.':'Todavía no hay reporte diario.','No actions logged yet.':'Todavía no hay acciones registradas.','Run social setup or social onboard, then social auth login.':'Ejecuta social setup o social onboard, y luego social auth login.','Recommended: social setup':'Recomendado: social setup','configured':'configurado','Missing DASHBOARD_TOKEN':'Falta DASHBOARD_PASSWORD','Missing DASHBOARD_PASSWORD':'Falta DASHBOARD_PASSWORD','License key missing':'Falta la licencia','Invalid license format':'Formato de licencia inválido','License checksum mismatch':'La licencia no pasó validación','License active':'Licencia activa','Cloud unlock active':'Licencia cloud activa','Cloud license active':'Licencia cloud activa','Offline license active; no license server configured':'Licencia local activa; no hay servidor cloud configurado','Cloud unlock expired; grace period active':'El desbloqueo cloud venció; periodo de gracia activo','Could not validate the license online. Check internet access or contact support.':'No pudimos validar la licencia online. Revisa internet o contacta soporte.','License server unavailable; using the saved unlock on this device':'Servidor de licencia no disponible; usando el desbloqueo guardado en este equipo','Demo/internal license':'Licencia demo/interna','Missing META_AD_ACCOUNT_ID':'Falta META_AD_ACCOUNT_ID','Not configured; optional unless using graph_api connector.':'No configurado; es opcional salvo que uses el conector graph_api.','Missing creative.destination.page_id':'Falta creative.destination.page_id','Missing creative.destination.url':'Falta creative.destination.url','Missing GEMINI_API_KEY':'Falta GEMINI_API_KEY','Missing MINIMAX_API_KEY; chat will use local fallback replies.':'Falta MINIMAX_API_KEY; el chat usará respuestas locales de respaldo.','Set MINIMAX_API_KEY in .env for real agent conversation.':'Configura MINIMAX_API_KEY en .env para conversación real con el agente.','No creative drafts yet.':'Todavía no hay borradores creativos.','No upload payloads staged yet.':'Todavía no hay paquetes de subida preparados.','None':'Ninguno','logs directory not created yet':'La carpeta logs todavía no existe'
};
function t(key){return (copy[lang]&&copy[lang][key])||copy.en[key]||key}
function localText(value){if(lang!=='es')return value;let text=String(value??'');return esText[text]||text.replace(/^Missing: /,'Falta: ').replace('blocked / missing','bloqueado / faltan').replace('ready_for_approval','listo para aprobación').replace('dry-run','con supervisión').replace('True','Sí').replace('False','No')}
function actionName(value){const raw=String(value||'').replaceAll('_',' ');if(lang!=='es')return raw;return raw.replace('budget change','cambio de presupuesto').replace('resume campaign','reactivar campaña').replace('create campaign','crear campaña').replace('creative upload','subida creativa').replace('daily agent run','ejecución diaria del agente').replace('creative refresh','renovación creativa').replace('creative upload execute','ejecución de subida creativa').replace('creative upload stage','preparación de subida creativa')}
function actionDetail(a){const p=a.payload||{};const result=p.result||p.social_cli_result||{};const requested=p.name||p.campaign_name||p.campaign_id||p.path||'';const connector=p.connector||result.connector||(result.command?'social-cli':'local');const mode=p.mode||result.mode||state?.config?.mode||'';const executed=(p.executed!==undefined?p.executed:result.executed);const response=result.stderr||result.stdout||p.response_summary||'';const rows=[];if(requested)rows.push(`<strong>${lang==='es'?'Pedido':'Requested'}:</strong> ${requested}`);rows.push(`<strong>${lang==='es'?'Conector':'Connector'}:</strong> ${connector}`);if(mode)rows.push(`<strong>${lang==='es'?'Modo':'Mode'}:</strong> ${mode}`);if(executed!==undefined)rows.push(`<strong>${lang==='es'?'Ejecutado':'Executed'}:</strong> ${executed? (lang==='es'?'sí':'yes') : (lang==='es'?'no':'no')}`);if(response)rows.push(`<strong>${lang==='es'?'Respuesta':'Response'}:</strong> ${String(response).slice(0,180)}`);return rows.length?`<div class="action-detail">${rows.join('<br>')}</div>`:''}
function keyFor(label){return labelKeys[label]||label}
function tip(label){const key=keyFor(label);return `<span class="tip" tabindex="0" data-tip="${t(key+'_tip')}">${t(key)} <span class="help-dot">?</span></span>`}
function kpi(label,value){return `<div class="kpi"><div class="v">${value}</div><div class="l">${tip(label)}</div></div>`}
function metric(label,value){return `<div class="metric"><b>${value}</b><span>${tip(label)}</span></div>`}
function explainTerms(text){return String(text||'').replace(/\b(ROAS|CPA|CTR|CPC|Frequency|frequency|conversions|Conversions|Active daily budget|active daily budget|daily budget)\b/g,match=>tip(match))}
function briefAnswer(text){
 if(lang!=='es')return text;
 return String(text||'')
  .replace(/^Active daily budget is /,'El presupuesto diario activo es ')
  .replace('; account ROAS is ','; el ROAS de la cuenta es ')
  .replace(' with CPA ',' con CPA ')
  .replace(/^(\d+) active campaigns, (\d+) paused or staged\.$/,'$1 campañas activas, $2 pausadas o preparadas.')
  .replace(/^7-day view shows /,'Vista de 7 días: ')
  .replace(' spend, ',' de gasto, ')
  .replace(' revenue, ',' de ingresos, ')
  .replace(' conversions, and ',' conversiones y ')
  .replace(/^Top winner: /,'Mejor campaña: ')
  .replace(' at ',' con ')
  .replace('No material fatigue triggers right now.','No hay señales importantes de fatiga por ahora.')
  .replace('No clear winner yet.','Todavía no hay una campaña claramente ganadora.');
}
function briefQuestion(q){return t(questionKeys[q]||q)}
function modeText(value){if(value==='dry-run')return lang==='es'?'supervisado':'supervised';if(value==='live')return lang==='es'?'piloto':'autopilot';return value}
function statusText(value){const map={active:lang==='es'?'activa':'active',paused:lang==='es'?'pausada':'paused',winning:lang==='es'?'ganadora':'winning',losing:lang==='es'?'perdedora':'losing',fatigue:lang==='es'?'fatiga':'fatigue',neutral:lang==='es'?'neutral':'neutral',blocked:lang==='es'?'bloqueado':'blocked',warn:lang==='es'?'alerta':'warn',ok:lang==='es'?'ok':'ok'};return map[value]||value}
function applyTranslations(){
 document.documentElement.lang=lang;
 qs('#language-select').value=lang;
 document.querySelectorAll('[data-i18n]').forEach(el=>{el.textContent=t(el.dataset.i18n)});
 document.querySelectorAll('[data-i18n-placeholder]').forEach(el=>{el.placeholder=t(el.dataset.i18nPlaceholder)});
 qs('#top-roas').innerHTML=tip('ROAS'); qs('#top-cpa').innerHTML=tip('CPA'); qs('#top-mode').innerHTML=tip('Mode');
 qs('#th-spend').innerHTML=tip('Spend'); qs('#th-roas').innerHTML=tip('ROAS'); qs('#th-cpa').innerHTML=tip('CPA'); qs('#th-ctr').innerHTML=tip('CTR');
 syncPanels();
}
function positionFloatingTip(target){
 const box=qs('#floating-tip'); if(!box||!target)return;
 box.textContent=target.dataset.tip||''; box.classList.add('show');
 const rect=target.getBoundingClientRect(); const tipRect=box.getBoundingClientRect(); const gap=10; const margin=12;
 let left=rect.left+(rect.width-tipRect.width)/2;
 left=Math.max(margin,Math.min(left,window.innerWidth-tipRect.width-margin));
 let top=rect.top-tipRect.height-gap;
 if(top<margin)top=rect.bottom+gap;
 if(top+tipRect.height>window.innerHeight-margin)top=Math.max(margin,window.innerHeight-tipRect.height-margin);
 box.style.left=`${left}px`; box.style.top=`${top}px`;
}
function hideFloatingTip(){const box=qs('#floating-tip');if(box)box.classList.remove('show')}
document.addEventListener('pointerover',e=>{const target=e.target.closest?.('.tip');if(target)positionFloatingTip(target)})
document.addEventListener('pointerout',e=>{const target=e.target.closest?.('.tip');if(target&&!target.contains(e.relatedTarget))hideFloatingTip()})
document.addEventListener('focusin',e=>{const target=e.target.closest?.('.tip');if(target)positionFloatingTip(target)})
document.addEventListener('focusout',e=>{if(e.target.closest?.('.tip'))hideFloatingTip()})
document.addEventListener('scroll',hideFloatingTip,true)
window.addEventListener('resize',hideFloatingTip)
function toast(msg){const t=qs('#toast');t.textContent=msg;t.style.display='block';setTimeout(()=>t.style.display='none',2600)}
function fillTemplate(text){const s=state?.metrics?.summary||{};return String(text).replace('{roas}',Number(s.overall_roas||0).toFixed(2)).replace('{cpa}',fmtMoney(s.overall_cpa)).replace('{budget}',fmtMoney(s.active_budget)).replace('{pending}',state?.pending?.length||0)}
function escapeHtml(value){return String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]))}
function panelOpen(side){return localStorage.getItem(`dashboardPanel:${side}`)==='open'}
function panelTitle(side,open){
 if(side==='left')return open?(lang==='es'?'Ocultar lectura diaria':'Hide daily intelligence'):(lang==='es'?'Mostrar lectura diaria':'Show daily intelligence');
 return open?(lang==='es'?'Ocultar aprobaciones y actividad':'Hide approvals and activity'):(lang==='es'?'Mostrar aprobaciones y actividad':'Show approvals and activity')
}
function syncPanels(){
 const left=panelOpen('left'),right=panelOpen('right');
 document.body.classList.toggle('left-panel-open',left);
 document.body.classList.toggle('right-panel-open',right);
 [['left',left],['right',right]].forEach(([side,open])=>{
  const btn=qs(`#toggle-${side}-panel`);if(!btn)return;
  const title=panelTitle(side,open);
  btn.classList.toggle('active',open);btn.setAttribute('aria-expanded',open?'true':'false');btn.setAttribute('aria-label',title);btn.title=title;
 })
}
function togglePanel(side){localStorage.setItem(`dashboardPanel:${side}`,panelOpen(side)?'closed':'open');syncPanels()}
function inlineMarkdown(value){return escapeHtml(value).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')}
function formatChatContent(text){
 const raw=fillTemplate(text).replace(/\r\n/g,'\n').trim();
 if(!raw)return '';
 const blocks=[]; let list=[];
 const flushList=()=>{if(list.length){blocks.push(`<ul>${list.map(item=>`<li>${inlineMarkdown(item)}</li>`).join('')}</ul>`);list=[]}};
 raw.split(/\n+/).forEach(line=>{
  const trimmed=line.trim();
  if(!trimmed)return flushList();
  const bullet=trimmed.match(/^[-*]\s+(.+)$/);
  const numbered=trimmed.match(/^\d+[.)]\s+(.+)$/);
  if(bullet||numbered){list.push((bullet||numbered)[1]);return}
  flushList();
  blocks.push(`<p>${inlineMarkdown(trimmed)}</p>`);
 });
 flushList();
 return blocks.join('');
}
function setMessageContent(node,text){const content=fillTemplate(text);node.classList.remove('thinking');node.innerHTML=formatChatContent(content);node.dataset.rawContent=content;return content}
function addMessage(role,text,store=true){const log=qs('#chat-log');const node=document.createElement('div');node.className=`msg ${role}`;const content=setMessageContent(node,text);log.appendChild(node);log.scrollTop=log.scrollHeight;if(store)chatHistory.push({role,content});return node}
function hydrateChatHistory(force=false){
 if(chatHydrated&&!force)return;
 const log=qs('#chat-log');if(!log)return;
 const history=Array.isArray(state?.chat_history)?state.chat_history:[];
 log.innerHTML='';chatHistory=[];
 history.slice(-40).forEach(item=>addMessage(item.role==='agent'?'agent':'user',item.content,false));
 chatHistory=history.slice(-40).map(item=>({role:item.role==='agent'?'agent':'user',content:item.content}));
 chatHydrated=true;
}
function streamMessageContent(node,text){
 const content=fillTemplate(text);
 node.dataset.rawContent='';
 node.classList.remove('thinking');
 node.classList.add('streaming');
 const parts=content.match(/\S+\s*/g)||[''];
 let index=0;
 return new Promise(resolve=>{
  const tick=()=>{
   index+=1;
   const partial=parts.slice(0,index).join('');
   node.dataset.rawContent=partial;
   node.innerHTML=formatChatContent(partial);
   qs('#chat-log').scrollTop=qs('#chat-log').scrollHeight;
   if(index<parts.length){setTimeout(tick,18)}else{node.classList.remove('streaming');resolve(content)}
  };
  tick();
 });
}
function openChat(draft=''){hydrateChatHistory();document.body.classList.add('chat-workspace-open');const panel=qs('#chat-panel');panel.classList.add('open');if(!qs('#chat-log').children.length)addMessage('agent',t('chat_welcome'));if(draft)qs('#chat-input').value=draft;resizeChatInput();qs('#chat-input').focus()}
function closeChat(){qs('#chat-panel').classList.remove('open');document.body.classList.remove('chat-workspace-open')}
function resizeChatInput(){const input=qs('#chat-input');if(!input)return;input.style.height='auto';const max=150;const next=Math.min(input.scrollHeight,max);input.style.height=`${next}px`;input.style.overflowY=input.scrollHeight>max?'auto':'hidden'}
function resizeAgentBarInput(){const input=qs('#agent-bar-input');if(!input)return;input.style.height='auto';const max=92;const next=Math.min(input.scrollHeight,max);input.style.height=`${next}px`;input.style.overflowY=input.scrollHeight>max?'auto':'hidden'}
async function sendChatMessage(text,{workspace=false}={}){
 if(!text)return;
 if(workspace)document.body.classList.add('chat-workspace-open');
 openChat();
 addMessage('user',text);
 const pending=addMessage('agent',lang==='es'?'Pensando...':'Thinking...',false);pending.classList.add('thinking');
 try{const res=await api('/api/chat',{method:'POST',body:JSON.stringify({message:text,history:chatHistory,metrics:state.metrics,recommendations:state.recommendations,fatigue:state.fatigue,pending:state.pending,language:lang})});const reply=res.result.reply||agentReply(text);const rendered=await streamMessageContent(pending,reply);chatHistory.push({role:'agent',content:rendered});if(res.result.routed_action){await load()}}catch(err){const raw=String(err&&err.message||err||'');const needsPassword=raw.includes('dashboard password')||raw.includes('password')||raw.includes('401');const fallback=needsPassword?(lang==='es'?'Necesito la contraseña del dashboard para hablar con el agente real y ejecutar acciones protegidas. Desbloquea el dashboard y vuelve a enviar el mensaje.':'I need the dashboard password to talk to the real agent and run protected actions. Unlock the dashboard and send the message again.'):agentReply(text);const rendered=await streamMessageContent(pending,fallback);chatHistory.push({role:'agent',content:rendered})}
}
async function newChatConversation(){
 await api('/api/chat/reset',{method:'POST',body:JSON.stringify({})});
 chatHistory=[];chatHydrated=true;qs('#chat-log').innerHTML='';addMessage('agent',t('chat_welcome'));
 toast(lang==='es'?'Conversación nueva lista':'New conversation ready');
}
function agentReply(text){const msg=String(text||'').toLowerCase();if(msg.includes('presupuesto')||msg.includes('budget'))return t('chat_budget');if(msg.includes('fatiga')||msg.includes('creative')||msg.includes('creativo'))return t('chat_fatigue');if(msg.includes('config')||msg.includes('setup')||msg.includes('live'))return t('chat_setup');if(msg.includes('resumen')||msg.includes('catch')||msg.includes('dónde')||msg.includes('where'))return t('chat_summary');return `${t('chat_summary')}\n\n${t('chat_action_hint')}`}
function dataSourceText(m){const source=String(m?.source||'');if(source==='meta_graph')return lang==='es'?'Datos reales de Meta':'Real Meta data';if(source==='demo')return lang==='es'?'Datos demo':'Demo data';return lang==='es'?'Datos guardados':'Saved data'}
let unlockResolver=null;
function dashboardPassword(){return localStorage.getItem('dashboardPassword')||localStorage.getItem('dashboardToken')||''}
function showUnlock(message=''){const overlay=qs('#unlock-overlay');const err=qs('#unlock-error');if(err){err.textContent=message;err.classList.toggle('show',Boolean(message))}overlay.classList.add('open');setTimeout(()=>qs('#unlock-password')?.focus(),30);return new Promise(resolve=>{unlockResolver=resolve})}
function hideUnlock(){qs('#unlock-overlay')?.classList.remove('open')}
async function requestUnlock(message=''){return showUnlock(message||t('unlock_needed'))}
async function api(path,opts={}){const headers={'Content-Type':'application/json',...(opts.headers||{})};const password=dashboardPassword();if(password)headers['X-Dashboard-Token']=password;let res=await fetch(path,{...opts,headers});if(res.status===401){const entered=await requestUnlock();if(entered){headers['X-Dashboard-Token']=entered;res=await fetch(path,{...opts,headers});if(res.status===401){localStorage.removeItem('dashboardPassword');await requestUnlock(t('unlock_failed'));throw new Error(t('unlock_failed'))}}}if(!res.ok)throw new Error(await res.text());return res.json()}
async function load(){state=await api('/api/dashboard');render();if(state.config.dashboard_password_required&&state.config.dashboard_password_set&&!dashboardPassword()&&state.onboarding&&state.onboarding.completed)showUnlock(t('unlock_needed'))}
function render(){
 applyTranslations();
 hydrateChatHistory();
 const m=state.metrics, s=m.summary;
 qs('#s-roas').textContent=Number(s.overall_roas||0).toFixed(2)+'x'; qs('#s-cpa').textContent=fmtMoney(s.overall_cpa); qs('#s-mode').textContent=modeText(state.config.mode); qs('#s-updated').textContent=new Date(m.timestamp).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
 qs('#data-source-signal').textContent=dataSourceText(m);
 const refreshBtn=qs('#real-data-refresh');if(refreshBtn){refreshBtn.classList.toggle('hidden',m.source==='meta_graph');refreshBtn.textContent=lang==='es'?'Actualizar datos reales':'Refresh real data'}
 qs('#kpis').innerHTML=[['Spend',fmtMoney(s.total_spend)],['Revenue',fmtMoney(s.total_revenue)],['Conversions',Number(s.total_conversions||0).toLocaleString()],['Active Budget',fmtMoney(s.active_budget)]].map(x=>kpi(x[0],x[1])).join('');
 qs('#brief').innerHTML=state.brief.questions.map(q=>`<div class="brief-q"><b>${briefQuestion(q.question)}</b><p>${explainTerms(briefAnswer(q.answer))}</p></div>`).join('');
 qs('#fatigue').innerHTML=state.fatigue.length?state.fatigue.map(f=>`<div class="fatigue"><b>${f.campaign_name}</b><div>${f.reasons.join(' / ')}</div></div>`).join(''):`<p class="notice">${t('no_fatigue')}</p>`;
 qs('#campaigns').innerHTML=m.campaigns.map(card).join('');
 qs('#recs').innerHTML=state.recommendations.map(r=>{const draft=lang==='es'?`Revisa esta recomendación de presupuesto para ${r.campaign_name}: actual ${fmtMoney(r.current_budget)}, sugerido ${fmtMoney(r.recommended_budget)}. ¿La aplicarías o esperarías?`:`Review this budget recommendation for ${r.campaign_name}: current ${fmtMoney(r.current_budget)}, suggested ${fmtMoney(r.recommended_budget)}. Would you apply it or wait?`;return `<tr><td>${r.campaign_name}<br><span class="notice">${r.reason}</span></td><td>${fmtMoney(r.current_budget)}</td><td>${fmtMoney(r.recommended_budget)}</td><td><button class="btn" onclick="applyRec('${r.campaign_id}',${r.recommended_budget})">${r.requires_approval?t('request'):t('apply')}</button><button class="btn ask-btn" style="margin-top:6px" onclick="openChat(${JSON.stringify(draft).replaceAll('"','&quot;')})">${t('ask_agent')}</button></td></tr>`}).join('');
 qs('#recs-mobile').innerHTML=state.recommendations.map(r=>{const draft=lang==='es'?`Revisa esta recomendación de presupuesto para ${r.campaign_name}: actual ${fmtMoney(r.current_budget)}, sugerido ${fmtMoney(r.recommended_budget)}. ¿La aplicarías o esperarías?`:`Review this budget recommendation for ${r.campaign_name}: current ${fmtMoney(r.current_budget)}, suggested ${fmtMoney(r.recommended_budget)}. Would you apply it or wait?`;return `<div class="rec-card"><h3>${r.campaign_name}</h3><p class="notice">${r.reason}</p><div class="rec-values"><div><b>${fmtMoney(r.current_budget)}</b><span>${t('now')}</span></div><div><b>${fmtMoney(r.recommended_budget)}</b><span>${t('rec')}</span></div></div><button class="btn primary" onclick="applyRec('${r.campaign_id}',${r.recommended_budget})">${r.requires_approval?t('request'):t('apply')}</button><button class="btn ask-btn" style="margin-top:7px" onclick="openChat(${JSON.stringify(draft).replaceAll('"','&quot;')})">${t('ask_agent')}</button></div>`}).join('');
 qs('#pending').innerHTML=state.pending.length?state.pending.map(p=>`<div class="log-item"><b>${actionName(p.type)}</b><br>${p.payload.name||p.payload.campaign_name||''}<br>${approvalNote(p)?`<span class="notice">${approvalNote(p)}</span><br>`:''}${new Date(p.created_at).toLocaleString()}<br><button class="btn" style="margin-top:7px" onclick="approvePending('${p.id}')">${t('approve')}</button></div>`).join(''):`<p class="notice">${t('no_pending')}</p>`;
 qs('#actions').innerHTML=state.actions.length?state.actions.map(a=>`<div class="log-item"><b>${actionName(a.type)}</b> - ${statusText(a.status)}<br>${new Date(a.created_at).toLocaleString()}${actionDetail(a)}</div>`).join(''):`<p class="notice">${t('no_actions')}</p>`;
 qs('#report-rows').innerHTML=m.campaigns.map(c=>`<tr><td>${c.name}</td><td>${fmtMoney(c.spend)}</td><td>${Number(c.roas).toFixed(2)}x</td><td>${fmtMoney(c.cpa)}</td><td>${fmtPct(c.ctr)}</td><td>${statusText(c.health)}</td></tr>`).join('');
 renderBrandGuides();
 qs('#creative-list').innerHTML=state.creative_refreshes.length?state.creative_refreshes.map(c=>`<div class="log-item"><b>${c.campaign.name}</b><br>${statusText(c.status)} / ${c.variant_count} ${t('variants')}<br><span>${c.manifest_path}</span><br>${new Date(c.created_at).toLocaleString()}<br><button class="btn" style="margin-top:7px" onclick="stageUpload('${c.manifest_path}','v1')">${t('stage_v1_upload')}</button></div>`).join(''):`<p class="notice">${t('no_creatives')}</p>`;
 qs('#upload-list').innerHTML=state.creative_uploads.length?state.creative_uploads.map(u=>`<div class="log-item"><b>${u.campaign.name}</b><br>${statusText(u.status)} / ${u.variant_id}<br>${t('missing')}: ${u.missing_count}<br><span>${u.payload_path}</span></div>`).join(''):`<p class="notice">${t('no_uploads')}</p>`;
 renderSetup();
 renderAudience();
 renderOnboardingFlow();
}
function renderBrandGuides(){
 const box=qs('#brand-guides-panel');if(!box)return;
 const g=state.brand_guides||{};
 const products=g.product_guides||[];
 box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'Memoria creativa de marca':'Brand creative memory'}</b><p>${lang==='es'?'El agente usa una guía general y una guía por producto para mantener conceptos y prompts visuales consistentes.':'The agent uses a general guide and one guide per product to keep concepts and visual prompts consistent.'}</p><p class="notice">${lang==='es'?'Codex CLI es un complemento opcional: viene apagado por defecto porque es un agente local. Si el dueño lo activa, prepara estrategia y prompts; el proveedor creativo genera la imagen.':'Codex CLI is an optional add-on: it is off by default because it is a local agent. If the owner enables it, it prepares strategy and prompts; the creative provider generates the image.'}</p><p class="notice">${lang==='es'?'Guía general':'General guide'}: ${escapeHtml(g.general_guide||'brand_guides/general_branding.md')} · ${lang==='es'?'Productos':'Products'}: ${products.length}</p><div class="onboarding-step-actions"><button class="btn primary" onclick="initBrandGuides()">${lang==='es'?'Crear guías base':'Create base guides'}</button><button class="btn" onclick="openChat('${lang==='es'?'Usa mis guías de marca y producto para preparar 3 conceptos visuales de anuncios.':'Use my brand and product guides to prepare 3 visual ad concepts.'}')">${t('ask_agent')}</button></div>${products.length?products.map(p=>`<div class="log-item"><b>${escapeHtml(p.split('/').pop())}</b><br><span>${escapeHtml(p)}</span></div>`).join(''):''}</div>`;
}
function approvalNote(p){
 if(p.type==='create_campaign'&&p.payload?.final_status==='ACTIVE')return lang==='es'?'Atención: al aprobar, se creará la campaña completa y el anuncio quedará ACTIVO, capaz de gastar presupuesto real.':'Attention: approving creates the full campaign stack and leaves the ad ACTIVE, able to spend real budget.';
 if(p.type==='create_campaign'||p.type==='creative_upload')return lang==='es'?'Se creará en pausa como borrador seguro: todavía no gasta ni entra a aprendizaje hasta que lo actives.':'It will be created paused as a safe draft: it does not spend or enter learning until you activate it.';
 if(p.type==='pause_campaign')return lang==='es'?'Esta sí es una pausa sobre algo existente; úsala solo cuando tenga sentido por rendimiento o seguridad.':'This is a pause on something existing; use it only when performance or safety justifies it.';
 return '';
}
function statusLabel(s){return s==='ok'?t('ok'):s==='blocked'?t('blocked'):t('check')}
function setupItem(key){for(const sec of state.setup.sections){const found=sec.items.find(i=>i.key===key);if(found)return found}return {status:'blocked',detail:''}}
function stepCopy(key){
	 const en={
	  title:'Setup path',subtitle:'One small step at a time. First we look only. Real ad changes stay off until you say yes at the end.',progress:'done',done:'Done',next:'Do this next',review:'Check',
	  helper:'For setup helper',
	  website:['Tell the agent what business this is','Paste your website so the agent can understand the offer, products, tone, and landing page before showing the dashboard.',''],
	  context:['Tell the agent where you are today','Write what stage you are in, what feels confusing, and what you want to improve. This makes the first plan feel personal, not generic.',''],
	  strategy:['Review the first plan','Before entering the dashboard, the agent creates a simple starting strategy from your website and your answers.',''],
	  license:['Add your license','Paste the only code you received from us. This code proves this copy belongs to you.','LICENSE_KEY=MAO-...'],
	  meta:['Create your private Meta connection','You will use your own Meta app and token. This keeps access under your control and this tool still will not change ads yet.','Open Meta Developers'],
	  account:['Choose the ad account','Pick the ad account you want this tool to help with. If you have only one, choose that one.','social marketing accounts'],
	  destination:['Tell us where ads should point','Add the Facebook page, Instagram profile if you use one, and your website link. The agent will prepare the structure through chat.',''],
	  insights:['Let the tool read your results','The tool checks your real ad numbers so it can give useful advice. It still does not change anything.','social marketing insights --preset last_7d --level campaign'],
	  dryrun:['Do one safe practice run','The tool makes a daily summary and suggestions, but only as practice. No Meta Ads changes happen.','python3 src/daily_agent.py status'],
	  approval:['Practice approving a change','Make sure you can review a suggested change before anything real happens.','python3 src/daily_agent.py pending'],
	  live:['Keep autopilot off for now','Recommended for the first run: enter the dashboard with supervision. You can turn autopilot on later from Setup when you feel ready.',''],
	  smoke:['Optional tiny live test later','After you are comfortable, approve one very small change and check that Meta says it worked. This is not needed to enter the dashboard.',''],
	  password:['Create your dashboard password','Choose a password only you know. From now on, this protects your local dashboard on this computer or server.',''],
	  guide:['How to use your agent','Read these quick cards before entering the dashboard. You can open them again later from Setup > Guide.','']
	 };
	 const es={
	  title:'Camino de configuración',subtitle:'Un pasito a la vez. Primero solo miramos. Los cambios reales en anuncios quedan apagados hasta que tú digas que sí al final.',progress:'listo',done:'Listo',next:'Haz esto ahora',review:'Revisar',
	  helper:'Para quien te ayuda a instalar',
	  website:['Dile al agente cuál es tu negocio','Pega tu web para que el agente entienda tu oferta, productos, tono y página de destino antes de mostrar el dashboard.',''],
	  context:['Cuéntale al agente en qué punto estás','Escribe en qué etapa estás, qué te confunde y qué sientes que podrías mejorar. Así el primer plan se siente personal, no genérico.',''],
	  strategy:['Revisa el primer plan','Antes de entrar al dashboard, el agente crea una estrategia inicial simple usando tu web y tus respuestas.',''],
	  license:['Poner tu licencia','Pega el único código que recibiste de nosotros. Este código confirma que esta copia es tuya.','LICENSE_KEY=MAO-...'],
	  meta:['Crear tu conexion privada con Meta','Usaras tu propia app de Meta y tu propio token. Asi el acceso queda bajo tu control y la herramienta todavia no cambia anuncios.','Abrir Meta Developers'],
	  account:['Escoger la cuenta publicitaria','Elige la cuenta de anuncios que quieres que esta herramienta cuide. Si solo tienes una, elige esa.','social marketing accounts'],
	  destination:['Decir a dónde van tus anuncios','Agrega la página de Facebook, Instagram si lo usas y el link de tu web. El agente preparará la estructura conversando contigo.',''],
	  insights:['Dejar que lea tus resultados','La herramienta mira tus números reales para darte buenos consejos. Todavía no cambia nada.','social marketing insights --preset last_7d --level campaign'],
	  dryrun:['Hacer una práctica segura','La herramienta prepara un resumen diario y sugerencias, pero solo como práctica. No toca Meta Ads.','python3 src/daily_agent.py status'],
	  approval:['Practicar una aprobación','Revisa cómo aprobarías un cambio sugerido antes de permitir cualquier cambio real.','python3 src/daily_agent.py pending'],
	  live:['Dejar piloto automático apagado por ahora','Recomendado para la primera entrada: entra al dashboard con supervisión. Luego puedes activar piloto automático desde Configuración cuando te sientas listo.',''],
	  smoke:['Prueba real pequeña para después','Cuando ya estés cómodo, aprueba un cambio mínimo y revisa que Meta confirme que funcionó. No hace falta para entrar al dashboard.',''],
	  password:['Crear tu contraseña del dashboard','Elige una contraseña que solo tú conozcas. Desde ahora protege tu dashboard local en este computador o servidor.',''],
	  guide:['Cómo usar tu agente','Lee estas tarjetas rápidas antes de entrar al dashboard. Luego puedes verlas otra vez en Configuración > Guía.','']
	 };
 return (lang==='es'?es:en)[key];
}
function copyCommand(value){navigator.clipboard?.writeText(value).then(()=>toast(t('copied'))).catch(()=>toast(value))}
function onboardingSteps(){
 const setup=state.setup, summary=setup.summary;
 const profile=state.business_profile||{};
 const websiteOk=Boolean(profile.website_url);
 const contextOk=Boolean(profile.current_stage||profile.what_to_improve||profile.main_offer);
 const strategyOk=Boolean(profile.initial_plan&&profile.initial_plan.length);
 const licenseOk=Boolean(summary.license_ready);
 const passwordOk=Boolean(dashboardPassword())&&state.config.dashboard_password_set;
 const accountOk=setupItem('ad_account').status==='ok';
 const destinationOk=['page_id','landing_url'].every(k=>setupItem(k).status==='ok');
 const socialOk=setupItem('social_cli').status==='ok';
 const dryrunOk=setupItem('daily_report').status==='ok';
 const approvalOk=state.pending.length>0||state.actions.some(a=>String(a.status)==='pending_approval'||String(a.status)==='completed');
 const insightsOk=state.metrics?.source==='meta_graph'||state.actions.some(a=>a.type==='live_insights_pull'||a.type==='daily_agent_run')||dryrunOk;
 const smokeOk=state.actions.some(a=>a.type==='live_smoke_test'||(a.status==='completed'&&a.payload&&a.payload.connector));
 return [
  {id:'website',status:websiteOk?'ok':'blocked'},
  {id:'context',status:contextOk?'ok':'blocked'},
  {id:'strategy',status:strategyOk?'ok':'warn'},
  {id:'license',status:licenseOk?'ok':'blocked'},
  {id:'meta',status:accountOk?'ok':(socialOk?'warn':'blocked')},
  {id:'account',status:accountOk?'ok':'blocked'},
  {id:'destination',status:destinationOk?'ok':'blocked'},
  {id:'insights',status:insightsOk?'ok':(accountOk?'warn':'blocked')},
  {id:'dryrun',status:dryrunOk?'ok':'warn'},
  {id:'approval',status:approvalOk?'ok':'warn'},
  {id:'live',status:summary.live_ads_ready?'ok':'warn'},
  {id:'smoke',status:smokeOk?'ok':'warn'},
  {id:'password',status:passwordOk?'ok':'blocked'},
  {id:'guide',status:'warn'},
	 ];
	}
function renderOnboarding(){
 const doneState=state.onboarding||{};
 if(doneState.completed){
  const when=doneState.completed_at?new Date(doneState.completed_at).toLocaleString():'';
  qs('#onboarding-wizard').innerHTML=`<div class="onboarding"><div class="next-step"><div><b>${lang==='es'?'Onboarding completado':'Onboarding completed'}</b><p>${lang==='es'?'Esta instalación ya terminó el onboarding, así que la guía inicial no volverá a arrancar automáticamente.':'This installation has already finished onboarding, so the guided setup will not restart automatically.'}${when?` ${when}`:''}</p></div><button class="btn" onclick="resetOnboarding()">${lang==='es'?'Configurar onboarding otra vez':'Set Up Onboarding again'}</button></div></div>`;
  return;
 }
 const labels=stepCopy('title'); const sub=stepCopy('subtitle'); const progress=stepCopy('progress');
 const steps=onboardingSteps(); const done=steps.filter(s=>s.status==='ok').length;
 const labelFor=s=>s.status==='ok'?stepCopy('done'):(s.status==='blocked'?stepCopy('next'):stepCopy('review'));
 const next=steps.find(s=>s.status!=='ok')||steps[steps.length-1]; const nextCopy=stepCopy(next.id);
 qs('#onboarding-wizard').innerHTML=`<div class="onboarding"><div class="onboarding-head"><div><h3>${labels}</h3><p>${sub}</p></div><div class="progress"><b>${done}/${steps.length}</b><span>${progress}</span></div></div><div class="next-step"><div><b>${lang==='es'?'Siguiente paso':'Next step'}: ${nextCopy[0]}</b><p>${nextCopy[1]}</p></div>${nextCopy[2]?`<button class="btn copy-btn" onclick="copyCommand(${JSON.stringify(nextCopy[2]).replaceAll('"','&quot;')})">${t('copy_command')}</button>`:''}</div><div class="step-list">${steps.map((s,i)=>{const c=stepCopy(s.id);return `<div class="setup-step ${s.status}"><div class="step-num">${i+1}</div><div class="step-main"><b>${c[0]}</b><p>${c[1]}</p>${c[2]?`<details class="helper-command"><summary>${stepCopy('helper')}</summary><span class="step-command">${c[2]}</span></details>`:''}</div><div class="step-badge">${labelFor(s)}</div></div>`}).join('')}</div><div class="mode-actions" style="margin-top:10px"><button class="btn ask-btn" onclick="openChat(lang==='es'?'Revisa mi ruta de onboarding. Explícame el siguiente paso con palabras muy simples.':'Review my onboarding path. Explain the next step in very simple words.')">${t('ask_agent')}</button><button class="btn primary" onclick="completeOnboarding()">${lang==='es'?'Finalizar onboarding':'Finish onboarding'}</button></div></div>`;
}
function onboardingFormFor(stepId){
	 const v=state.config.setup_values||{};
 if(stepId==='website')return websiteScanGuide();
 if(stepId==='context')return businessContextGuide();
 if(stepId==='strategy')return initialStrategyGuide();
	 if(stepId==='license')return `<form class="onboarding-mini two" onsubmit="saveOnboardingSetupConfig(event)"><label>${t('license_key')}<input name="license_key" placeholder="MAO-..."></label><label>${t('buyer_email')}<input name="license_buyer_email" value="${escapeHtml(v.license_buyer_email||'')}" placeholder="buyer@email.com"></label><div class="onboarding-step-actions"><button class="btn primary" type="submit">${t('save_setup')}</button><button class="btn" type="button" onclick="activateLicense()">${t('license_activate')}</button></div></form>`;
 if(stepId==='meta')return metaConnectionGuide();
 if(stepId==='account')return accountPickerGuide();
 if(stepId==='destination')return destinationPickerGuide();
 if(stepId==='password')return `<form class="unlock-form" onsubmit="setDashboardPasswordFromOnboarding(event)"><label>${t('dashboard_password')}<input id="new-dashboard-password" type="password" autocomplete="new-password" minlength="8" placeholder="${lang==='es'?'Crea una contraseña segura':'Create a secure password'}"></label><label>${lang==='es'?'Repetir contraseña':'Repeat password'}<input id="confirm-dashboard-password" type="password" autocomplete="new-password" minlength="8" placeholder="${lang==='es'?'Escríbela otra vez':'Type it again'}"></label><label><input id="new-dashboard-remember" type="checkbox" checked> ${t('remember_device')}</label><div class="unlock-error" id="dashboard-password-error"></div><button class="btn primary" type="submit">${lang==='es'?'Guardar mi contraseña':'Save my password'}</button></form>`;
	 return passiveStepGuide(stepId);
	}
function websiteScanGuide(){
 const p=state.business_profile||{};
 const url=p.website_url||state.config.setup_values?.landing_url||'';
 return `<div class="setup-guide private-connection"><section class="guide-hero business-hero"><div class="guide-main"><span class="guide-eyebrow">${lang==='es'?'Inteligencia del negocio':'Business intelligence'}</span><h3>${lang==='es'?'Primero entiendo tu web':'First I understand your website'}</h3><p>${lang==='es'?'Pega el link principal de tu negocio. El agente intenta leer la página para detectar qué vendes, a quién le vendes y qué ángulos podrían funcionar en Meta Ads.':'Paste the main link for your business. The agent tries to read the page and detect what you sell, who it is for, and which ad angles may work.'}</p><form class="onboarding-mini" onsubmit="scanBusinessWebsite(event)"><label>${lang==='es'?'Web del negocio':'Business website'}<input name="website_url" value="${escapeHtml(url)}" placeholder="https://tumarca.com"></label><button class="btn primary" type="submit">${lang==='es'?'Escanear mi web':'Scan my website'}</button></form></div><aside class="guide-checklist"><b>${lang==='es'?'Qué busca el agente':'What the agent looks for'}</b><ol><li>${lang==='es'?'Oferta principal y productos.':'Main offer and products.'}</li><li>${lang==='es'?'A quién parece dirigida la web.':'Who the site seems to target.'}</li><li>${lang==='es'?'Mensajes, promesas, objeciones y llamados a la acción.':'Messaging, promises, objections, and calls to action.'}</li></ol></aside></section><div id="business-scan-results" class="setup-guide">${businessProfileCard()}</div></div>`;
}
function businessContextGuide(){
 const p=state.business_profile||{};
 return `<form class="setup-guide private-connection" onsubmit="saveBusinessContext(event)"><section class="guide-hero business-hero"><div class="guide-main"><span class="guide-eyebrow">${lang==='es'?'Contexto humano':'Human context'}</span><h3>${lang==='es'?'Ahora cuéntale lo que la web no sabe':'Now tell it what the website cannot know'}</h3><p>${lang==='es'?'Esto es lo que vuelve al agente más útil: no solo ve una web, entiende tu momento actual. Escribe simple, como se lo contarías a una persona.':'This makes the agent more useful: it does not just see a website, it understands your current moment. Write simply, like you would tell a person.'}</p></div><aside class="guide-checklist"><b>${lang==='es'?'Ejemplos':'Examples'}</b><ol><li>${lang==='es'?'Estoy empezando y no sé qué campaña lanzar.':'I am starting and do not know which campaign to launch.'}</li><li>${lang==='es'?'Ya vendo, pero el CPA subió.':'I already sell, but CPA increased.'}</li><li>${lang==='es'?'Tengo visitas, pero pocas compras.':'I get visitors, but few purchases.'}</li></ol></aside></section><div class="onboarding-mini two"><label>${lang==='es'?'Oferta principal':'Main offer'}<input name="main_offer" value="${escapeHtml(p.main_offer||p.offer||'')}" placeholder="${lang==='es'?'Ej: curso, ecommerce, servicio, software':'Ex: course, ecommerce, service, software'}"></label><label>${lang==='es'?'Cliente ideal':'Ideal customer'}<input name="ideal_customer" value="${escapeHtml(p.ideal_customer||p.audience||'')}" placeholder="${lang==='es'?'Quién compra o debería comprar':'Who buys or should buy'}"></label><label class="wide">${lang==='es'?'¿En qué etapa estás ahora?':'What stage are you in now?'}<textarea name="current_stage" rows="4" placeholder="${lang==='es'?'Cuéntame si estás empezando, si ya vendes, si tienes campañas activas, si algo te preocupa...':'Tell me if you are starting, already selling, have active campaigns, or something worries you...'}">${escapeHtml(p.current_stage||'')}</textarea></label><label class="wide">${lang==='es'?'¿Qué sientes que podrías mejorar?':'What do you feel could improve?'}<textarea name="what_to_improve" rows="3" placeholder="${lang==='es'?'Ej: entender mejor mis números, bajar CPA, crear mejores anuncios, saber qué pausar...':'Ex: understand my numbers, lower CPA, create better ads, know what to pause...'}">${escapeHtml(p.what_to_improve||'')}</textarea></label></div><button class="btn primary" type="submit">${lang==='es'?'Guardar contexto y crear plan':'Save context and create plan'}</button></form>`;
}
function initialStrategyGuide(){
 const p=state.business_profile||{};
 const plan=(p.initial_plan&&p.initial_plan.length?p.initial_plan:[
  lang==='es'?'Conectar Meta para leer datos reales.':'Connect Meta to read real data.',
  lang==='es'?'Conversar con el agente para preparar la primera campaña.':'Talk to the agent to prepare the first campaign.',
  lang==='es'?'Trabajar con supervisión antes de activar piloto automático.':'Work with supervision before enabling autopilot.'
 ]);
 const angles=p.suggested_angles||[];
 return `<div class="setup-guide private-connection"><section class="guide-hero business-hero"><div class="guide-main"><span class="guide-eyebrow">${lang==='es'?'Primer diagnóstico':'First diagnosis'}</span><h3>${lang==='es'?'Esto entendí de tu negocio':'This is what I understood about your business'}</h3><p>${escapeHtml(p.positioning||p.detected_title||p.offer|| (lang==='es'?'Todavía falta más contexto, pero ya podemos empezar con una estrategia simple.':'We still need more context, but we can start with a simple strategy.'))}</p><div class="business-summary-grid"><div><b>${lang==='es'?'Tipo':'Type'}</b><span>${escapeHtml(p.business_type||'-')}</span></div><div><b>${lang==='es'?'Oferta':'Offer'}</b><span>${escapeHtml(p.main_offer||p.offer||'-')}</span></div><div><b>${lang==='es'?'Cliente':'Customer'}</b><span>${escapeHtml(p.ideal_customer||p.audience||'-')}</span></div></div></div><aside class="guide-checklist"><b>${lang==='es'?'Plan inicial':'Initial plan'}</b><ol>${plan.map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ol></aside></section>${angles.length?`<div class="guide-panel"><b>${lang==='es'?'Ángulos iniciales para anuncios':'Initial ad angles'}</b><ol>${angles.map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ol></div>`:''}<div class="onboarding-step-actions"><button class="btn" type="button" onclick="onboardingFlowStep=Math.max(0,onboardingFlowStep-1);renderOnboardingFlow()">${lang==='es'?'Editar contexto':'Edit context'}</button><button class="btn primary" type="button" onclick="onboardingFlowTouched=true;onboardingFlowStep=Math.min(onboardingSteps().length-1,onboardingFlowStep+1);renderOnboardingFlow()">${lang==='es'?'Me sirve, seguir':'Looks good, continue'}</button><button class="btn ask-btn" type="button" onclick="openChat('${lang==='es'?'Revisa este perfil de negocio y dime qué estrategia inicial prepararías para Meta Ads.':'Review this business profile and tell me what initial Meta Ads strategy you would prepare.'}')">${t('ask_agent')}</button></div></div>`;
}
function businessProfileCard(){
 const p=state.business_profile||{};
 if(!p.website_url)return '';
 return `<div class="guide-card"><b>${lang==='es'?'Perfil guardado':'Profile saved'}</b><p>${escapeHtml(p.website_url)}${p.scan_error?` · ${lang==='es'?'No pude leer toda la web, pero guardé el link y puedes seguir.':'I could not read the full site, but saved the link and you can continue.'}`:''}</p>${p.offer?`<p>${lang==='es'?'Oferta detectada':'Detected offer'}: ${escapeHtml(p.offer)}</p>`:''}</div>`;
}
function passiveStepGuide(stepId){
 const es={
  insights:['Lectura segura','El agente intenta leer resultados reales para darte mejores recomendaciones. Sigue en modo lectura: no cambia anuncios.','Cuando tu cuenta este conectada, este paso se valida con una lectura de resultados.'],
  dryrun:['Practica con supervisión','El resumen diario usa datos reales y prepara recomendaciones sin ejecutar cambios importantes por su cuenta. Sirve para ver si el agente entiende tus campañas antes de permitir piloto automático.','Puedes usar Actualizar en Lectura diaria o pedirle al chat que corra una revision.'],
  approval:['Ensaya una aprobacion','Aqui confirmamos que los cambios importantes pasan por una cola antes de ejecutarse. Nada riesgoso debe saltarse esta puerta.','Revisa la zona de Aprobaciones para ver solicitudes pendientes.'],
  live:['Qué significa trabajar con supervisión','Con supervisión el agente puede leer datos reales, explicar y preparar acciones, pero los cambios importantes esperan tu aprobación. Para la primera vez, este es el camino recomendado.','Toca Siguiente y entra al dashboard. Cuando quieras que el agente actúe solo dentro de tus reglas, ve a Configuración y activa piloto automático.'],
  smoke:['Prueba pequeña para más adelante','Esta prueba es opcional y sirve cuando ya quieres confirmar que las acciones reales funcionan. Debe ser algo mínimo: presupuesto bajo, una pausa o una acción fácil de revisar.','Puedes saltar este paso ahora. La recomendación para empezar es conversar con el agente y revisar sugerencias con supervisión.']
 };
 const en={
  insights:['Safe reading','The agent tries to read real results so it can give better recommendations. This is still read-only: it does not change ads.','Once your account is connected, this step is validated with a results read.'],
  dryrun:['Practice with supervision','The daily brief uses real data and prepares recommendations without executing important changes by itself. This shows whether the agent understands your campaigns before autopilot is allowed.','Use Refresh in Daily Brief or ask chat to run a review.'],
  approval:['Practice an approval','This confirms important changes go through a queue before execution. Risky actions should never skip this gate.','Check the Approvals area for pending requests.'],
  live:['What supervised mode means','With supervision, the agent can read real data, explain, and prepare actions, but important changes wait for your approval. For the first run, this is the recommended path.','Click Next and enter the dashboard. When you want the agent to act by itself inside your rules, go to Setup and enable autopilot.'],
  smoke:['Tiny test for later','This test is optional and useful when you are ready to confirm real actions work. It should be minimal: low budget, one pause, or an action that is easy to verify.','You can skip this now. The best first step is to chat with the agent and review suggestions with supervision.']
 };
 if(stepId==='guide')return usageCheatSheetMarkup(true);
 const copy=(lang==='es'?es:en)[stepId]||[stepCopy(stepId)[0],stepCopy(stepId)[1],lang==='es'?'Usa Siguiente cuando estes listo.':'Use Next when you are ready.'];
 return `<div class="passive-guide"><div class="passive-card"><span class="passive-state">${lang==='es'?'Paso de revision':'Review step'}</span><b>${copy[0]}</b><p>${copy[1]}</p></div><div class="passive-side"><b>${lang==='es'?'Que hacer ahora':'What to do now'}</b><p>${copy[2]}</p></div></div>`;
}
function metaConnectionGuide(){
 const v=state.config.setup_values||{};
 if(lang==='es')return `<div class="setup-guide private-connection"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Conexion privada</span><h3>Tu propia app de Meta, tu propio token</h3><p>Usa los screenshots incluidos con tu compra. El acceso nace en tu cuenta de Meta, se guarda en este computador o VPS y lo puedes revocar cuando quieras.</p><div class="guide-visual"><div class="mini-screen"><span></span><span></span><strong>1. Meta Developers</strong><em>crea tu app</em></div><div class="guide-arrow">&rarr;</div><div class="mini-screen"><span></span><span></span><strong>2. Token propio</strong><em>copialo de Meta</em></div><div class="guide-arrow">&rarr;</div><div class="mini-screen"><span></span><span></span><strong>3. Dashboard local</strong><em>pegalo aqui</em></div></div><div class="guide-actions"><a class="btn" href="/api/social/login" target="_blank" rel="noopener" onclick="connectMetaStarted()">Abrir Meta</a><button class="btn" type="button" onclick="showMetaTokenBox()">Ya tengo mi token</button><button class="btn primary" type="button" onclick="refreshSocialAccounts()">Buscar cuentas</button></div><div id="meta-token-box" class="token-box"><label>Token de acceso de Meta<textarea id="meta-token-input" oninput="scheduleMetaTokenAutoSave()" onpaste="setTimeout(scheduleMetaTokenAutoSave,0)" placeholder="Pega aqui el token que generaste en tu propia app de Meta"></textarea></label><button class="btn" type="button" onclick="saveMetaToken()">Reintentar guardar</button><p class="notice">Se guarda automaticamente al pegarlo. Nosotros no recibimos este token; queda local en esta instalacion.</p></div></div><aside class="guide-checklist"><b>Sigue tus screenshots</b><ol><li>Crea una app nueva en Meta Developers.</li><li>Abre Marketing API o Graph API Explorer.</li><li>Genera un token con permisos de anuncios.</li><li>Pega el token aqui; el dashboard lo guarda solo.</li><li>Busca tus cuentas y elige la correcta.</li></ol></aside></section><div id="social-account-results" class="setup-guide"></div><div class="guide-panel"><b>Por que esto es mas seguro</b><p>La conexion queda entre tu cuenta de Meta y tu instalacion local. Si algun dia quieres cortar acceso, revocas el token desde Meta y listo.</p></div></div>`;
 return `<div class="setup-guide private-connection"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Private connection</span><h3>Your own Meta app, your own token</h3><p>Use the screenshots included with your purchase. Access starts inside your Meta account, is stored on this computer or VPS, and can be revoked whenever you want.</p><div class="guide-visual"><div class="mini-screen"><span></span><span></span><strong>1. Meta Developers</strong><em>create your app</em></div><div class="guide-arrow">&rarr;</div><div class="mini-screen"><span></span><span></span><strong>2. Your token</strong><em>copy it from Meta</em></div><div class="guide-arrow">&rarr;</div><div class="mini-screen"><span></span><span></span><strong>3. Local dashboard</strong><em>paste it here</em></div></div><div class="guide-actions"><a class="btn" href="/api/social/login" target="_blank" rel="noopener" onclick="connectMetaStarted()">Open Meta</a><button class="btn" type="button" onclick="showMetaTokenBox()">I have my token</button><button class="btn primary" type="button" onclick="refreshSocialAccounts()">Find accounts</button></div><div id="meta-token-box" class="token-box"><label>Meta access token<textarea id="meta-token-input" oninput="scheduleMetaTokenAutoSave()" onpaste="setTimeout(scheduleMetaTokenAutoSave,0)" placeholder="Paste the token you generated in your own Meta app"></textarea></label><button class="btn" type="button" onclick="saveMetaToken()">Retry save</button><p class="notice">It saves automatically when pasted. We do not receive this token; it stays local to this install.</p></div></div><aside class="guide-checklist"><b>Follow your screenshots</b><ol><li>Create a new app in Meta Developers.</li><li>Open Marketing API or Graph API Explorer.</li><li>Generate a token with ads permissions.</li><li>Paste the token here; the dashboard saves it automatically.</li><li>Find your accounts and choose the right one.</li></ol></aside></section><div id="social-account-results" class="setup-guide"></div><div class="guide-panel"><b>Why this is safer</b><p>The connection stays between your Meta account and your local install. If you ever want to cut access, revoke the token in Meta.</p></div></div>`;
}
function accountPickerGuide(){
 const v=state.config.setup_values||{};
 if(lang==='es')return `<div class="setup-guide private-connection"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Cuenta publicitaria</span><h3>Elige una cuenta y seguimos solos</h3><p>Despues de tocar <strong>Usar esta cuenta</strong>, la guia guarda la cuenta y avanza al siguiente paso automaticamente.</p><div class="guide-actions"><button class="btn primary" type="button" onclick="refreshSocialAccounts()">Buscar mis cuentas</button><button class="btn" type="button" onclick="openChat('Ayudame a elegir la cuenta publicitaria correcta con palabras simples.')">${t('ask_agent')}</button></div></div><aside class="guide-checklist"><b>Que debes elegir</b><ol><li>La cuenta donde estan tus campanas reales.</li><li>La cuenta donde tienes permiso para administrar anuncios.</li><li>Si solo aparece una, normalmente esa es la correcta.</li></ol></aside></section><div id="social-account-results" class="setup-guide"></div><details class="fallback-details"><summary>Solo si no aparecen tus cuentas</summary><form class="manual-account onboarding-mini" onsubmit="saveOnboardingSetupConfig(event)"><b>Pegar ID manualmente</b><p>Usa esto solo si el buscador de cuentas no funciona. Se ve asi: <strong>act_123456789</strong>.</p><label>${t('ad_account_id')}<input name="ad_account_id" value="${escapeHtml(v.ad_account_id||'')}" placeholder="act_123456789"></label><button class="btn primary" type="submit">${t('save_setup')}</button></form></details></div>`;
 return `<div class="setup-guide private-connection"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Ad account</span><h3>Choose one account and we continue automatically</h3><p>After you click <strong>Use this account</strong>, the guide saves the account and moves to the next step by itself.</p><div class="guide-actions"><button class="btn primary" type="button" onclick="refreshSocialAccounts()">Find my accounts</button><button class="btn" type="button" onclick="openChat('Help me choose the right ad account in simple words.')">${t('ask_agent')}</button></div></div><aside class="guide-checklist"><b>What to choose</b><ol><li>The account with your real campaigns.</li><li>The account where you can manage ads.</li><li>If only one appears, it is usually the right one.</li></ol></aside></section><div id="social-account-results" class="setup-guide"></div><details class="fallback-details"><summary>Only if your accounts do not appear</summary><form class="manual-account onboarding-mini" onsubmit="saveOnboardingSetupConfig(event)"><b>Paste ID manually</b><p>Use this only if account search does not work. It looks like <strong>act_123456789</strong>.</p><label>${t('ad_account_id')}<input name="ad_account_id" value="${escapeHtml(v.ad_account_id||'')}" placeholder="act_123456789"></label><button class="btn primary" type="submit">${t('save_setup')}</button></form></details></div>`;
}
function destinationPickerGuide(){
 const v=state.config.setup_values||{};
 const current=[v.page_id?`${lang==='es'?'Pagina':'Page'}: ${escapeHtml(v.page_id)}`:'',v.instagram_actor_id?`Instagram: ${escapeHtml(v.instagram_actor_id)}`:'',v.landing_url?`${lang==='es'?'Web':'Website'}: ${escapeHtml(v.landing_url)}`:''].filter(Boolean).join(' · ');
 if(lang==='es')return `<div class="setup-guide private-connection"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Destino de anuncios</span><h3>Busquemos tus páginas automáticamente</h3><p>Con el token que ya pegaste, el dashboard intenta traer tus páginas de Facebook, el Instagram conectado y la web. Normalmente solo eliges la página correcta y seguimos.</p><div class="guide-actions"><button class="btn primary" type="button" onclick="discoverMetaAssets('${escapeHtml(v.ad_account_id||'')}')">Buscar páginas e Instagram</button><button class="btn" type="button" onclick="openChat('Ayudame a escoger la pagina de Facebook correcta para mis anuncios.')">${t('ask_agent')}</button></div>${current?`<p class="notice">Guardado ahora: ${current}</p>`:''}</div><aside class="guide-checklist"><b>Qué estamos buscando</b><ol><li>Tu página de Facebook para publicar los anuncios.</li><li>Tu Instagram conectado, si existe.</li><li>El link de tu web o landing para mandar visitas.</li></ol></aside></section><div id="destination-discovery-results" class="setup-guide"></div><details class="fallback-details"><summary>Solo si no aparece tu página</summary><form class="manual-account onboarding-mini two" onsubmit="saveOnboardingSetupConfig(event)"><b>Pegar datos manualmente</b><p>Usa esto solo si Meta no devuelve tus páginas. El agente también puede ayudarte por chat a encontrarlos.</p><label>${t('page_id')}<input name="page_id" value="${escapeHtml(v.page_id||'')}" placeholder="123456789"></label><label>${t('instagram_actor_id')}<input name="instagram_actor_id" value="${escapeHtml(v.instagram_actor_id||'')}" placeholder="opcional"></label><label>${t('landing_url')}<input name="landing_url" value="${escapeHtml(v.landing_url||'')}" placeholder="https://..."></label><button class="btn primary" type="submit">${t('save_setup')}</button></form></details></div>`;
 return `<div class="setup-guide private-connection"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Ad destination</span><h3>Let's find your pages automatically</h3><p>Using the token you already pasted, the dashboard tries to load your Facebook Pages, connected Instagram, and website. Usually you only choose the correct Page and continue.</p><div class="guide-actions"><button class="btn primary" type="button" onclick="discoverMetaAssets('${escapeHtml(v.ad_account_id||'')}')">Find Pages and Instagram</button><button class="btn" type="button" onclick="openChat('Help me choose the right Facebook Page for my ads.')">${t('ask_agent')}</button></div>${current?`<p class="notice">Saved now: ${current}</p>`:''}</div><aside class="guide-checklist"><b>What we are finding</b><ol><li>Your Facebook Page for publishing ads.</li><li>Your connected Instagram, if one exists.</li><li>Your website or landing page link.</li></ol></aside></section><div id="destination-discovery-results" class="setup-guide"></div><details class="fallback-details"><summary>Only if your Page does not appear</summary><form class="manual-account onboarding-mini two" onsubmit="saveOnboardingSetupConfig(event)"><b>Paste details manually</b><p>Use this only if Meta does not return your pages. The agent can also help you find them by chat.</p><label>${t('page_id')}<input name="page_id" value="${escapeHtml(v.page_id||'')}" placeholder="123456789"></label><label>${t('instagram_actor_id')}<input name="instagram_actor_id" value="${escapeHtml(v.instagram_actor_id||'')}" placeholder="optional"></label><label>${t('landing_url')}<input name="landing_url" value="${escapeHtml(v.landing_url||'')}" placeholder="https://..."></label><button class="btn primary" type="submit">${t('save_setup')}</button></form></details></div>`;
}
function firstActionableOnboardingIndex(steps){
 const next=steps.findIndex(s=>s.status!=='ok');
 return next>=0?next:Math.max(0,steps.length-1);
}
function advanceOnboardingAfterLoad(){
 const steps=onboardingSteps();
 const next=firstActionableOnboardingIndex(steps);
 if(next>onboardingFlowStep)onboardingFlowStep=next;
 renderOnboardingFlow();
}
function renderOnboardingFlow(){
 const flow=qs('#onboarding-flow');if(!flow)return;
 const doneState=state.onboarding||{};
 if(doneState.completed&&!doneState.requires_repair){flow.classList.remove('open');return}
 const steps=onboardingSteps();if(onboardingFlowStep>=steps.length)onboardingFlowStep=steps.length-1;
 if(!onboardingFlowTouched&&(steps[onboardingFlowStep]||{}).status==='ok')onboardingFlowStep=firstActionableOnboardingIndex(steps);
 const step=steps[onboardingFlowStep]||steps[0];const copyStep=stepCopy(step.id);const doneCount=steps.filter(s=>s.status==='ok').length;
 const isLast=onboardingFlowStep===steps.length-1;
 const canGoNext=!isLast&&step.status!=='blocked';
 const nextButton=canGoNext?`<button class="btn" onclick="onboardingFlowTouched=true;onboardingFlowStep=Math.min(${steps.length-1},onboardingFlowStep+1);renderOnboardingFlow()">${lang==='es'?'Siguiente':'Next'}</button>`:'';
 const finishButton=isLast?`<button class="btn primary" onclick="completeOnboarding()">${lang==='es'?'Terminar y abrir dashboard':'Finish and open dashboard'}</button>`:'';
 const spaces=state.business_spaces||{};
 const agencySwitch=spaces.is_agency&&spaces.spaces?.length?`<div class="guide-card" style="margin-top:14px"><b>${lang==='es'?'Clientes de agencia':'Agency clients'}</b><p>${lang==='es'?'Abre otro cliente cuando quieras continuar su configuración. Sus datos se mantienen separados.':'Open another client when you want to continue its setup. Its data remains separate.'}</p>${spaces.spaces.map(s=>`<button class="btn ${spaces.active_id===s.id?'primary':''}" style="margin:5px 5px 0 0" type="button" onclick="switchAgencySpace('${escapeHtml(s.id)}')">${escapeHtml(s.name)}</button>`).join('')}</div>`:'';
 const repairNotice=doneState.requires_repair?`<div class="guide-card"><b>${lang==='es'?'Reconectemos tus datos reales':'Reconnect your real data'}</b><p>${lang==='es'?'Tu configuración anterior quedó incompleta o perdió la conexión con Meta. Completa los pasos que falten para que el dashboard no use información de demostración.':'Your previous setup is incomplete or lost its Meta connection. Complete the missing steps so the dashboard does not use demonstration information.'}</p></div>`:'';
 flow.classList.add('open');
 flow.innerHTML=`<div class="onboarding-shell"><aside class="onboarding-side"><h1>Meta Ads Agent</h1><p>${lang==='es'?'Vamos a dejar todo listo con calma. Al terminar, se abre el dashboard completo.':'We will get everything ready calmly. When you finish, the full dashboard opens.'}</p><div class="onboarding-progress">${steps.map((s,i)=>`<span class="${i<=onboardingFlowStep?'done':''}"></span>`).join('')}</div><p>${doneCount}/${steps.length} ${stepCopy('progress')}</p>${agencySwitch}</aside><main class="onboarding-card">${repairNotice}<h2>${copyStep[0]}</h2><p>${copyStep[1]}</p>${onboardingFormFor(step.id)}<div class="onboarding-step-actions"><button class="btn" ${onboardingFlowStep===0?'disabled':''} onclick="onboardingFlowTouched=true;onboardingFlowStep=Math.max(0,onboardingFlowStep-1);renderOnboardingFlow()">${lang==='es'?'Atrás':'Back'}</button>${nextButton}${finishButton}</div></main></div>`;
 maybeAutoDiscoverDestination(step.id);
}
function maybeAutoDiscoverDestination(stepId){
 if(stepId!=='destination')return;
 const v=state.config.setup_values||{};const account=v.ad_account_id||'';
 if(!account||v.page_id)return;
 const key=`${account}:${v.page_id||''}:${v.landing_url||''}`;
 if(destinationAutoDiscoveryKey===key)return;
 destinationAutoDiscoveryKey=key;
 setTimeout(()=>discoverMetaAssets(account),60);
}
function usageCheatSheetMarkup(onboarding=false){const cards=lang==='es'?[
 ['Habla primero','Usa el chat como si hablaras con un manager: "qué hacemos hoy", "revisa presupuesto", "prepara una campaña para mi oferta".'],
 ['El dashboard es control','Mira números, aprobaciones y actividad cuando quieras verificar qué vio el agente y qué dejó preparado.'],
 ['Pide una cosa concreta','Mientras más simple la petición, mejor responde: producto, país, presupuesto y objetivo. Si falta algo, el agente debe preguntarte.'],
 ['Crear en pausa es borrador seguro','Cuando algo nuevo nace en pausa, todavía no empezó a gastar ni aprender. Es distinto a prender, pausar y reactivar campañas vivas muchas veces.'],
 ['Supervisión antes de piloto automático','Primero deja que lea datos reales, recomiende y prepare. Activa piloto automático solo cuando entiendas qué puede hacer solo.'],
 ['Aprueba con calma','El chat puede preparar acciones, pero las decisiones riesgosas se confirman desde aprobaciones. Esa pausa es parte de la seguridad.'],
 ['Vuelve a esta guía','Si te pierdes, abre Configuración > Guía y pídele al agente un resumen en palabras simples.']
]:[
 ['Talk first','Use chat like a manager: "what should we do today", "review budget", "prepare a campaign for my offer".'],
 ['Dashboard is control','Use the dashboard to verify numbers, approvals, and activity when you want to see what the agent saw and prepared.'],
 ['Ask one concrete thing','Simple requests work best: product, country, budget, and goal. If something is missing, the agent should ask.'],
 ['Paused creation is a safe draft','When something new starts paused, it has not spent or learned yet. That is different from repeatedly pausing and resuming live campaigns.'],
 ['Supervised before autopilot','Let it read real data, recommend, and prepare first. Enable autopilot only when you understand what it can do by itself.'],
 ['Approve calmly','Chat can prepare actions, but risky decisions are confirmed in approvals. That pause is part of the safety.'],
 ['Return to this guide','If you feel lost, open Setup > Guide and ask the agent for a plain-language catch-up.']
];return `<div class="${onboarding?'setup-guide':'guide-panel'}" id="${onboarding?'':'usage-guide-card'}"><div class="next-step"><div><b>${lang==='es'?'Guía rápida de uso':'Quick usage guide'}</b><p>${lang==='es'?'La filosofía: conversa con el agente y usa el dashboard para confirmar, aprobar y revisar.':'The philosophy: talk with the agent and use the dashboard to confirm, approve, and review.'}</p></div><button class="btn ask-btn" onclick="openChat(lang==='es'?'Explícame cómo usar este producto con palabras muy simples.':'Explain how to use this product in very simple words.')">${t('ask_agent')}</button></div><div class="trust-grid">${cards.map(c=>`<div class="trust-card"><b>${c[0]}</b><p>${c[1]}</p></div>`).join('')}</div></div>`}
function renderUsageCheatsheet(){const box=qs('#usage-cheatsheet');if(box)box.innerHTML=''}
function closeUsageGuide(){qs('#guide-overlay')?.classList.remove('open')}
function openUsageGuide(){
 const box=qs('#guide-overlay');if(!box)return;
 box.innerHTML=`<div class="guide-modal-card"><div class="next-step"><div><h2>${lang==='es'?'Guía rápida':'Quick guide'}</h2><p>${lang==='es'?'Tarjetas cortas para recordar cómo usar el producto sin llenar la pantalla principal.':'Short cards to remember how to use the product without filling the main screen.'}</p></div><button class="btn" type="button" onclick="closeUsageGuide()">${lang==='es'?'Cerrar':'Close'}</button></div>${usageCheatSheetMarkup(false)}</div>`;
 box.classList.add('open')
}
function scrollToUsageGuide(){openUsageGuide()}
function renderModeControl(){const live=state.config.mode==='live'&&state.config.live_actions_enabled;const title=lang==='es'?'Nivel de control':'Control level';const detail=live?(lang==='es'?'Piloto automático activo: el agente puede ejecutar cambios reales cuando estén dentro de tus reglas. Lo que supere tus límites pasa a aprobación.':'Autopilot is active: the agent can execute real changes when they fit your rules. Anything over your limits goes to approval.'):(lang==='es'?'Con supervisión activa: el agente lee datos reales, explica y prepara acciones. Solo ejecuta el cambio exacto que tú apruebes.':'Supervised mode is active: the agent reads real data, explains, and prepares actions. It only executes the exact change you approve.');qs('#mode-control').innerHTML=`<div class="mode-panel"><div><h3>${title}: ${live?(lang==='es'?'Piloto automático':'Autopilot'):(lang==='es'?'Con supervisión':'Supervised')}</h3><p>${detail}</p></div><div class="mode-actions"><button class="btn ${!live?'active':''}" onclick="setMode('dry-run')">${lang==='es'?'Con supervisión':'Supervised'}</button><button class="btn ${live?'active':''}" onclick="setMode('live')">${lang==='es'?'Piloto automático':'Autopilot'}</button></div></div>`}
function renderGuardrails(){
 const g=state.config.guardrails||{};
 qs('#guardrails-panel').innerHTML=`<form class="onboarding-mini two" onsubmit="saveGuardrails(event)"><label>${lang==='es'?'Modo de autonomía':'Autonomy mode'}<select name="autonomy_mode"><option value="supervised" ${g.autonomy_mode!=='autopilot'?'selected':''}>${lang==='es'?'Con supervisión: pedir aprobación':'Supervised: ask approval'}</option><option value="autopilot" ${g.autonomy_mode==='autopilot'?'selected':''}>${lang==='es'?'Piloto automático: actuar dentro de reglas':'Autopilot: act inside rules'}</option></select></label><label>${lang==='es'?'Aprobación si presupuesto cambia más de %':'Approval if budget changes over %'}<input name="approval_required_over_pct" type="number" min="1" step="1" value="${g.approval_required_over_pct||20}"></label><label>${lang==='es'?'Piloto automático: máximo cambio %':'Autopilot: max change %'}<input name="auto_budget_change_pct" type="number" min="1" step="1" value="${g.auto_budget_change_pct||10}"></label><label>${lang==='es'?'Piloto automático: máximo cambio $':'Autopilot: max change $'}<input name="auto_budget_change_amount" type="number" min="1" step="1" value="${g.auto_budget_change_amount||25}"></label><label>${lang==='es'?'Pausar solo sin aprobación si gastó menos de':'Pause without approval only if spend is under'}<input name="auto_pause_max_spend" type="number" min="0" step="1" value="${g.auto_pause_max_spend||100}"></label><label><input type="checkbox" name="require_approval_for_resume" ${g.require_approval_for_resume!==false?'checked':''}> ${lang==='es'?'Reactivar siempre pide aprobación':'Resume always needs approval'}</label><label><input type="checkbox" name="require_approval_for_new_campaigns" ${g.require_approval_for_new_campaigns!==false?'checked':''}> ${lang==='es'?'Campañas nuevas siempre piden aprobación':'New campaigns always need approval'}</label><label><input type="checkbox" name="require_approval_for_creatives" ${g.require_approval_for_creatives!==false?'checked':''}> ${lang==='es'?'Creativos/anuncios nuevos siempre piden aprobación':'New creatives/ads always need approval'}</label><button class="btn primary" type="submit">${lang==='es'?'Guardar reglas':'Save rules'}</button><p class="notice">${lang==='es'?'Estas reglas separan leer datos reales de tocar dinero real. El chat no puede aprobar sus propias acciones.':'These rules separate reading real data from touching real money. Chat cannot approve its own actions.'}</p></form>`;
}
function licenseLabel(status){
 if(status.status==='grace')return lang==='es'?'En periodo de gracia':'Grace period';
 if(status.status==='cloud_server_missing'||status.status==='missing_unlock'||status.status==='expired')return lang==='es'?'No se pudo validar con el servidor':'Could not validate with server';
 if(status.valid)return t('license_active');
 if(status.status==='missing')return t('license_missing');
 return t('license_invalid');
}
function licenseDetail(status){
 const detail=localText(status.detail||'');
 const mode=status.cloud_required?t('license_cloud'):t('license_local');
 const plan=status.plan==='agency'?(lang==='es'?'Agencia':'Agency'):(lang==='es'?'Individual':'Individual');
 const expires=status.expires_at?` · ${lang==='es'?'vence':'expires'} ${new Date(status.expires_at).toLocaleDateString()}`:'';
 return `${plan} · ${mode} · ${detail}${expires}`;
}
function renderLicensePanel(){
 const status=state.config.license_status||{};const valid=Boolean(status.valid);
 const badge=valid?'ok':(status.status==='missing'?'warn':'blocked');
 qs('#license-panel').innerHTML=`<div class="mode-panel"><div><h3>${t('license_panel_title')}: ${licenseLabel(status)}</h3><p>${t('license_panel_body')}</p><p class="notice">${licenseDetail(status)}</p></div><div class="mode-actions"><button class="btn ${valid?'':'primary'}" onclick="activateLicense()">${t('license_activate')}</button></div></div>`;
}
function renderAgencyPanel(){
 const spaces=state.business_spaces||{};const isAgency=Boolean(spaces.is_agency);
 const box=qs('#agency-panel');if(!box)return;
 if(!isAgency){
  box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'Licencia Individual: un negocio activo':'Individual license: one active business'}</b><p>${lang==='es'?'Puedes administrar una cuenta publicitaria y una página de Facebook. Si luego cambias a otro negocio, la memoria, historial y datos anteriores del agente se eliminan para iniciar limpio.':'You may manage one ad account and one Facebook Page. If you later switch to another business, prior agent memory, history, and data are removed for a clean start.'}</p><p class="notice">${lang==='es'?'Para agencias con varios clientes existe la licencia Agencia.':'For agencies managing multiple clients, the Agency license is available.'}</p></div>`;
  return;
 }
 const items=(spaces.spaces||[]).map(space=>`<div class="log-item"><b>${escapeHtml(space.name)}</b> ${spaces.active_id===space.id?`<span class="badge ok">${lang==='es'?'Activo':'Active'}</span>`:`<button class="btn" type="button" onclick="switchAgencySpace('${escapeHtml(space.id)}')">${lang==='es'?'Abrir cliente':'Open client'}</button>`}</div>`).join('');
 box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'Licencia Agencia: espacios por cliente':'Agency license: client spaces'}</b><p>${lang==='es'?'Cada cliente conserva su cuenta, página, memoria y configuración de Telegram. Al abrir ese cliente, su agente de Telegram queda activo sin mezclar datos con otro. Disponible hasta en 4 dispositivos.':'Each client keeps its account, Page, memory and Telegram settings. When you open that client, its Telegram agent becomes active without mixing data with another. Available on up to 4 devices.'}</p>${items||`<p class="notice">${lang==='es'?'Tu primer espacio se crea cuando termines el onboarding.':'Your first space is created when onboarding finishes.'}</p>`}<form class="onboarding-mini" onsubmit="createAgencySpace(event)"><label>${lang==='es'?'Nuevo cliente o marca':'New client or brand'}<input name="name" placeholder="${lang==='es'?'Ej. Clínica Norte':'E.g. North Clinic'}"></label><button class="btn primary" type="submit">${lang==='es'?'Agregar cliente':'Add client'}</button></form></div>`;
}
function renderSetupConfig(){
 const v=state.config.setup_values||{};
 const licensePlaceholder=v.license_key_set?(lang==='es'?'Licencia ya guardada. Pega una nueva solo si quieres cambiarla.':'License already saved. Paste a new one only to replace it.'):'MAO-...';
 qs('#setup-config').innerHTML=`<div class="next-step"><div><b>${t('setup_form_title')}</b><p>${t('setup_form_body')}</p></div></div><form id="setup-config-form" class="form-grid">
  <div class="field"><label>${t('license_key')}</label><input name="license_key" value="" placeholder="${escapeHtml(licensePlaceholder)}"></div>
  <div class="field"><label>${t('buyer_email')}</label><input name="license_buyer_email" value="${escapeHtml(v.license_buyer_email||'')}" placeholder="buyer@email.com"></div>
  <div class="field wide"><label>${t('ad_account_id')}</label><input name="ad_account_id" value="${escapeHtml(v.ad_account_id||'')}" placeholder="act_123456789"></div>
  <div class="field"><label>${t('page_id')}</label><input name="page_id" value="${escapeHtml(v.page_id||'')}"></div>
  <div class="field"><label>${t('instagram_actor_id')}</label><input name="instagram_actor_id" value="${escapeHtml(v.instagram_actor_id||'')}" placeholder="${lang==='es'?'opcional':'optional'}"></div>
  <div class="field"><label>${t('landing_url')}</label><input name="landing_url" value="${escapeHtml(v.landing_url||'')}" placeholder="https://..."></div>
  <div class="field wide"><button class="btn primary" type="submit">${t('save_setup')}</button></div>
 </form>`;
 qs('#setup-config-form').addEventListener('submit',saveSetupConfig);
}
function renderTelegramPanel(){
 const v=state.config.telegram_agent||{};
 const ready=v.enabled&&v.bot_configured&&v.chat_id;
 qs('#telegram-panel').innerHTML=`<div class="next-step"><div><b>${lang==='es'?'Hablar por Telegram':'Talk through Telegram'}</b><p>${lang==='es'?'Opcional: conecta un bot privado para conversar con el manager desde tu celular y aprobar decisiones exactas con botones seguros.':'Optional: connect a private bot to talk with the manager from your phone and approve exact decisions with safe buttons.'}</p></div><span class="badge ${ready?'ok':'warn'}">${ready?(lang==='es'?'Listo':'Ready'):(lang==='es'?'Opcional':'Optional')}</span></div><form id="telegram-config-form" class="form-grid">
 <div class="field wide"><label>${lang==='es'?'Token de tu bot de Telegram':'Your Telegram bot token'}</label><input type="password" name="bot_token" value="" placeholder="${v.bot_configured?(lang==='es'?'Bot guardado. Pega otro solo si quieres cambiarlo.':'Bot saved. Paste another only to replace it.'):'123456:ABC...'}"></div>
 <div class="field"><label>${lang==='es'?'Chat privado permitido':'Allowed private chat'}</label><input name="chat_id" value="${escapeHtml(v.chat_id||'')}" placeholder="${lang==='es'?'Detectar después de escribirle al bot':'Detect after messaging the bot'}"></div>
 <div class="field"><label>${lang==='es'?'Idioma del manager':'Manager language'}</label><select name="language"><option value="es" ${v.language!=='en'?'selected':''}>Español</option><option value="en" ${v.language==='en'?'selected':''}>English</option></select></div>
 <label class="field wide"><input type="checkbox" name="enabled" ${v.enabled?'checked':''}> ${lang==='es'?'Activar conversación por Telegram':'Enable Telegram conversation'}</label>
 <div class="field wide onboarding-step-actions"><button class="btn primary" type="submit">${lang==='es'?'Guardar Telegram':'Save Telegram'}</button><button class="btn" type="button" onclick="detectTelegramChats()">${lang==='es'?'Detectar mi chat':'Detect my chat'}</button><button class="btn" type="button" onclick="testTelegram()">${lang==='es'?'Enviar prueba':'Send test'}</button></div>
 </form><div id="telegram-results"></div><p class="notice">${lang==='es'?'Pasos: crea un bot con @BotFather, guarda su token, escríbele cualquier mensaje al bot y toca Detectar mi chat. Cuando el dashboard está encendido, el bot queda escuchando.':'Steps: create a bot with @BotFather, save its token, send the bot any message, then click Detect my chat. While the dashboard is running, the bot stays listening.'}</p>`;
 qs('#telegram-config-form').addEventListener('submit',saveTelegramConfig);
}
function renderSetup(){const setup=state.setup;const counts=setup.summary.counts;renderModeControl();renderGuardrails();renderOnboarding();renderLicensePanel();renderAgencyPanel();renderSetupConfig();renderTelegramPanel();qs('#setup-summary').innerHTML=`<div class="kpis">${kpi('OK',counts.ok||0)}${kpi('Warnings',counts.warn||0)}${kpi('Blocked',counts.blocked||0)}${kpi('Live Ready',setup.summary.live_ads_ready?t('live_ready_yes'):t('live_ready_no'))}</div>`;qs('#setup-sections').innerHTML=setup.sections.map(sec=>`<div class="section"><div class="head"><b>${localText(sec.title)}</b></div><div class="body">${sec.items.map(i=>`<div class="log-item"><b>${statusLabel(i.status)} - ${localText(i.label)}</b><br>${localText(i.detail||'')}${i.action?`<br><span class="notice">${localText(i.action)}</span>`:''}</div>`).join('')}</div></div>`).join('')}
function renderAudience(){
 const r=state.audience_strategy||{};const box=qs('#audience-result');if(!box)return;
 if(!r.strategies){box.innerHTML=`<p class="notice">${lang==='es'?'Completa el formulario para crear una recomendación clara de segmentación. El agente no sube listas de clientes todavía; solo revisa si tendría sentido hacerlo después.':'Fill the form to create a clear targeting recommendation. The agent does not upload customer lists yet; it only checks whether that would make sense later.'}</p>`;return}
 const ready=r.lookalike_readiness?.ready;
 box.innerHTML=`<div class="trust-grid"><div class="trust-card"><b>${t('lookalike_status')}</b><p>${ready?(lang==='es'?'Listo para probar con una audiencia semilla válida.':'Ready to test from a valid seed audience.'):(lang==='es'?'Todavía no conviene. Primero junta pixel, engagement o lista con consentimiento.':'Not yet. First collect pixel, engagement, or consented customer-list data.')}</p></div><div class="trust-card"><b>${lang==='es'?'Bloqueos':'Blockers'}</b><p>${(r.blockers&&r.blockers.length?r.blockers:[lang==='es'?'Sin bloqueos fuertes detectados.':'No major blockers detected.']).join(' ')}</p></div><div class="trust-card"><b>${lang==='es'?'Producto':'Product'}</b><p>${escapeHtml(r.product||'')}</p></div></div><h3 style="font-size:13px;margin:8px 0">${t('recommended_audiences')}</h3>${r.strategies.map(s=>`<div class="rec-card"><h3>${escapeHtml(s.name)}</h3><p class="notice">${escapeHtml(s.use_when)}</p><div class="action-detail"><strong>${lang==='es'?'Por qué':'Why'}:</strong> ${escapeHtml(s.why)}<br><strong>${lang==='es'?'Segmentación':'Targeting'}:</strong> ${escapeHtml(JSON.stringify(s.targeting))}</div></div>`).join('')}<h3 style="font-size:13px;margin:8px 0">${t('next_steps')}</h3>${(r.next_steps||[]).map(step=>`<div class="log-item">${escapeHtml(step)}</div>`).join('')}`;
}
function spark(vals){const w=220,h=46,max=Math.max(...vals,1),min=Math.min(...vals,0),range=max-min||1;const pts=vals.map((v,i)=>`${i*(w/(vals.length-1))},${h-((v-min)/range*h*.78+5)}`).join(' ');return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="#7c5cff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><line x1="0" y1="${h-4}" x2="${w}" y2="${h-4}" stroke="#2a2a30"/></svg>`}
function campaignButtons(c){
 if(c.status==='paused')return `<button class="btn primary" onclick="campaignAction('resume','${c.id}')">${t('resume')}</button><button class="btn" onclick="budgetPrompt('${c.id}',${c.daily_budget})">${t('adjust_budget')}</button><button class="btn" onclick="showDetails('${c.id}')">${t('details')}</button>`;
 if(c.health==='winning')return `<button class="btn primary" onclick="budgetPrompt('${c.id}',${Math.round(Number(c.daily_budget||0)*1.15)})">${t('increase_budget')}</button><button class="btn" onclick="showDetails('${c.id}')">${t('details')}</button><button class="btn" onclick="budgetPrompt('${c.id}',${c.daily_budget})">${t('adjust_budget')}</button>`;
 if(c.health==='fatigue')return `<button class="btn primary" onclick="generateRefresh('${c.id}')">${t('refresh_creative')}</button><button class="btn" onclick="budgetPrompt('${c.id}',${c.daily_budget})">${t('adjust_budget')}</button><button class="btn danger" onclick="campaignAction('pause','${c.id}')">${t('pause')}</button>`;
 if(c.health==='losing')return `<button class="btn danger" onclick="campaignAction('pause','${c.id}')">${t('pause')}</button><button class="btn primary" onclick="generateRefresh('${c.id}')">${t('refresh_creative')}</button><button class="btn" onclick="budgetPrompt('${c.id}',${c.daily_budget})">${t('adjust_budget')}</button>`;
 return `<button class="btn" onclick="budgetPrompt('${c.id}',${c.daily_budget})">${t('adjust_budget')}</button><button class="btn" onclick="generateRefresh('${c.id}')">${t('refresh_creative')}</button><button class="btn danger" onclick="campaignAction('pause','${c.id}')">${t('pause')}</button>`;
}
function card(c){const draft=lang==='es'?`Analiza la campaña ${c.name}. Está como ${statusText(c.health)} con ROAS ${Number(c.roas).toFixed(2)}x y CPA ${fmtMoney(c.cpa)}. ¿Qué harías como manager?`:`Analyze campaign ${c.name}. It is ${statusText(c.health)} with ROAS ${Number(c.roas).toFixed(2)}x and CPA ${fmtMoney(c.cpa)}. What would you do as manager?`;return `<article class="card" data-health="${c.health}"><div class="top"><h3>${c.name}</h3><span class="badge ${c.health}">${statusText(c.health)}</span></div><div class="metrics">${metric('Spend',fmtMoney(c.spend))}${metric('ROAS',Number(c.roas).toFixed(2)+'x')}${metric('CPA',fmtMoney(c.cpa))}${metric('CTR',fmtPct(c.ctr))}</div>${spark(c.trend)}<div class="actions">${campaignButtons(c)}<button class="btn ask-btn" onclick="openChat(${JSON.stringify(draft).replaceAll('"','&quot;')})">${t('ask_agent')}</button></div></article>`}
async function campaignAction(action,campaign_id){const res=await api('/api/action',{method:'POST',body:JSON.stringify({action,campaign_id})});const staged=res.result?.status==='pending';toast(staged?(lang==='es'?'Decisión enviada a aprobación':'Decision sent for approval'):(action==='resume'?t('toast_resume'):t('toast_action')));await load()}
async function applyRec(campaign_id,new_budget){const res=await api('/api/action',{method:'POST',body:JSON.stringify({action:'apply_recommendation',campaign_id,new_budget})});toast(res.result?.status==='pending'?(lang==='es'?'Cambio enviado a aprobación':'Change sent for approval'):t('toast_budget'));await load()}
async function budgetPrompt(campaign_id,current){const val=prompt(t('prompt_budget'),current);if(!val)return;const res=await api('/api/action',{method:'POST',body:JSON.stringify({action:'adjust_budget',campaign_id,new_budget:Number(val)})});toast(res.result?.status==='pending'?(lang==='es'?'Cambio enviado a aprobación':'Change sent for approval'):t('toast_budget'));await load()}
async function runAgent(){await api('/api/action',{method:'POST',body:JSON.stringify({action:'run_agent'})});toast(t('toast_daily'));await load()}
async function refreshInsights(){const res=await api('/api/action',{method:'POST',body:JSON.stringify({action:'refresh_insights'})});if(res.result&&res.result.ok){toast(lang==='es'?'Datos reales actualizados desde Meta.':'Real Meta data refreshed.')}else{toast(lang==='es'?'No pude leer datos reales todavía. Revisa token y cuenta.':'Could not read real data yet. Check token and account.')}await load();return res}
async function exportCsv(){const r=await api('/api/export');toast(t('toast_export')+r.path)}
async function approvePending(id){const item=(state.pending||[]).find(p=>p.id===id);if(item&&item.type==='create_campaign'&&item.payload?.final_status==='ACTIVE'){const ok=confirm(lang==='es'?'Esta aprobación dejará un anuncio ACTIVO y capaz de gastar presupuesto real. ¿Confirmas: Sí, crear y dejar activo?':'This approval leaves an ad ACTIVE and able to spend real budget. Confirm?');if(!ok)return}const res=await api('/api/approve',{method:'POST',body:JSON.stringify({approval_id:id})});const attempted=(res.result||[])[0]||{};toast(attempted.status==='approved'?t('toast_approval'):(lang==='es'?'No se pudo ejecutar. La decisión sigue pendiente para reintentar.':'Execution failed. The decision remains pending so you can retry.'));await load()}
async function setMode(mode){if(mode==='live'){const ok=confirm(lang==='es'?'Activar piloto automático permite acciones reales en Meta Ads cuando estén dentro de tus reglas. Lo que supere los límites queda en aprobación. ¿Quieres continuar?':'Autopilot allows real Meta Ads changes when they fit your rules. Anything over the limits goes to approval. Continue?');if(!ok)return}await api('/api/mode',{method:'POST',body:JSON.stringify({mode,live_actions_enabled:mode==='live'})});toast(mode==='live'?(lang==='es'?'Piloto automático activado':'Autopilot enabled'):(lang==='es'?'Modo con supervisión activado':'Supervised mode enabled'));await load()}
async function saveGuardrails(e){e.preventDefault();const form=e.target;const data=Object.fromEntries(new FormData(form).entries());data.require_approval_for_resume=form.require_approval_for_resume.checked;data.require_approval_for_new_campaigns=form.require_approval_for_new_campaigns.checked;data.require_approval_for_creatives=form.require_approval_for_creatives.checked;await api('/api/guardrails',{method:'POST',body:JSON.stringify(data)});toast(lang==='es'?'Reglas guardadas':'Rules saved');await load()}
async function saveTelegramConfig(e){e.preventDefault();const form=e.target;const data=Object.fromEntries(new FormData(form).entries());data.enabled=form.enabled.checked;await api('/api/telegram/config',{method:'POST',body:JSON.stringify(data)});toast(lang==='es'?'Telegram guardado':'Telegram saved');await load()}
async function detectTelegramChats(){const res=await api('/api/telegram/detect',{method:'POST',body:'{}'});const rows=res.result||[];const box=qs('#telegram-results');if(!rows.length){box.innerHTML=`<p class="notice">${lang==='es'?'No encontré mensajes. Escríbele primero a tu bot en Telegram y vuelve a intentar.':'I found no messages. Message your bot in Telegram first, then try again.'}</p>`;return}box.innerHTML=rows.map(c=>`<div class="log-item"><b>${escapeHtml(c.label)} ${escapeHtml(c.username||'')}</b><br><button class="btn primary" type="button" onclick="selectTelegramChat('${escapeHtml(c.id)}')">${lang==='es'?'Usar este chat':'Use this chat'}</button></div>`).join('')}
async function selectTelegramChat(id){await api('/api/telegram/config',{method:'POST',body:JSON.stringify({chat_id:id})});toast(lang==='es'?'Chat de Telegram guardado':'Telegram chat saved');await load()}
async function testTelegram(){await api('/api/telegram/test',{method:'POST',body:'{}'});toast(lang==='es'?'Mensaje enviado a Telegram':'Test message sent to Telegram')}
function showDetails(campaign_id){const c=state.metrics.campaigns.find(item=>item.id===campaign_id);if(c)toast(`${t('details')}: ${c.name} · ROAS ${Number(c.roas).toFixed(2)}x · CPA ${fmtMoney(c.cpa)}`);else toast(t('toast_details'))}
async function initBrandGuides(){const name=prompt(lang==='es'?'Nombre del producto u oferta principal':'Main product or offer name',state.business_profile?.main_offer||state.business_profile?.offer||'Oferta principal');if(!name)return;await api('/api/brand-guides/init',{method:'POST',body:JSON.stringify({product_name:name})});toast(lang==='es'?'Guías de marca creadas.':'Brand guides created.');await load()}
async function generateRefresh(campaign_id=''){await api('/api/creative-refresh',{method:'POST',body:JSON.stringify(campaign_id?{campaign_id}:{})});toast(t('toast_refresh'));await load()}
async function stageUpload(manifest_path,variant_id){await api('/api/stage-upload',{method:'POST',body:JSON.stringify({manifest_path,variant_id,ratios:['1:1']})});toast(t('toast_upload'));await load()}
async function buildAudienceStrategy(payload){const res=await api('/api/audience-strategy',{method:'POST',body:JSON.stringify({...payload,language:lang})});state.audience_strategy=res.result;renderAudience();toast(t('toast_audience'))}
let pendingBusinessReplacement=null;
function needsBusinessReplacement(err){return String(err?.message||err||'').includes('CONFIRM_BUSINESS_REPLACE')}
function showBusinessReplacementConfirm(payload){
 pendingBusinessReplacement=payload;
 const box=qs('#confirm-overlay');box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Cambiar de negocio':'Change business'}</h2><p>${lang==='es'?'Tu licencia Individual permite una cuenta publicitaria y una página a la vez. Al continuar, borraré la memoria anterior del agente, métricas guardadas, chat, actividad y guías creativas para empezar limpio con el nuevo negocio.':'Your Individual license allows one ad account and one Page at a time. Continuing removes previous agent memory, stored metrics, chat, activity, and creative guides to start clean with the new business.'}</p><div class="confirm-actions"><button class="btn" type="button" onclick="pendingBusinessReplacement=null;closeConfirm()">${lang==='es'?'Cancelar':'Cancel'}</button><button class="btn primary" type="button" onclick="confirmBusinessReplacement()">${lang==='es'?'Cambiar y borrar datos anteriores':'Change and delete previous data'}</button></div></div>`;box.classList.add('open')
}
async function confirmBusinessReplacement(){const payload={...(pendingBusinessReplacement||{}),confirm_replace_business:true};pendingBusinessReplacement=null;closeConfirm();await api('/api/setup-config',{method:'POST',body:JSON.stringify(payload)});toast(lang==='es'?'Nuevo negocio guardado. Empezamos con memoria limpia.':'New business saved. Starting with clean memory.');await load()}
async function saveSetupPayload(payload,advance=false){try{await api('/api/setup-config',{method:'POST',body:JSON.stringify(payload)});toast(t('toast_setup_saved'));await load();if(advance)advanceOnboardingAfterLoad()}catch(err){if(needsBusinessReplacement(err)){showBusinessReplacementConfirm(payload);return}throw err}}
async function saveSetupConfig(e){e.preventDefault();await saveSetupPayload(Object.fromEntries(new FormData(e.target).entries()))}
async function saveOnboardingSetupConfig(e){e.preventDefault();await saveSetupPayload(Object.fromEntries(new FormData(e.target).entries()),true)}
async function createAgencySpace(e){e.preventDefault();const payload=Object.fromEntries(new FormData(e.target).entries());await api('/api/agency/spaces',{method:'POST',body:JSON.stringify(payload)});toast(lang==='es'?'Cliente agregado. Ábrelo para configurarlo.':'Client added. Open it to configure it.');await load()}
async function switchAgencySpace(id){await api('/api/agency/spaces/switch',{method:'POST',body:JSON.stringify({space_id:id})});toast(lang==='es'?'Cliente activo cambiado.':'Active client changed.');await load()}
async function scanBusinessWebsite(e){e.preventDefault();const payload=Object.fromEntries(new FormData(e.target).entries());const box=qs('#business-scan-results');if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Leyendo tu web y preparando el perfil inicial...':'Reading your website and preparing the initial profile...'}</p></div>`;try{const res=await api('/api/business-profile/scan',{method:'POST',body:JSON.stringify(payload)});toast(lang==='es'?'Web analizada. Te llevo al contexto del negocio.':'Website scanned. Taking you to business context.');await load();const steps=onboardingSteps();const idx=steps.findIndex(s=>s.id==='context');onboardingFlowTouched=true;onboardingFlowStep=idx>=0?idx:onboardingFlowStep;renderOnboardingFlow();return res}catch(err){if(box)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude leer la web todavía':'I could not read the website yet'}</b><p>${escapeHtml(err.message||String(err))}</p></div>`;throw err}}
async function saveBusinessContext(e){e.preventDefault();const payload=Object.fromEntries(new FormData(e.target).entries());await api('/api/business-profile',{method:'POST',body:JSON.stringify(payload)});toast(lang==='es'?'Contexto guardado. Te muestro el primer plan.':'Context saved. Showing the first plan.');await load();const steps=onboardingSteps();const idx=steps.findIndex(s=>s.id==='strategy');onboardingFlowTouched=true;onboardingFlowStep=idx>=0?idx:onboardingFlowStep;renderOnboardingFlow()}
function showMetaTokenBox(){const box=qs('#meta-token-box');if(box)box.classList.add('open')}
function goToMetaTokenStep(reason='',output=''){const steps=onboardingSteps();const idx=steps.findIndex(s=>s.id==='meta');onboardingFlowTouched=true;onboardingFlowStep=idx>=0?idx:1;renderOnboardingFlow();setTimeout(()=>{showMetaTokenBox();const box=qs('#social-account-results');if(box&&reason==='expired'){box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'Pega un token nuevo':'Paste a new token'}</b><p>${lang==='es'?'Meta rechazo el token anterior porque vencio o ya no sirve. Pega aqui el token nuevo; el dashboard lo guarda automaticamente y despues vuelve a buscar tus cuentas.':'Meta rejected the previous token because it expired or is no longer valid. Paste the new token here; the dashboard saves it automatically and then finds your accounts again.'}</p><p class="notice">${lang==='es'?'Cuando pegas un token valido, queda guardado localmente por Social Flow en este computador o VPS. No se guarda en cookies del navegador.':'When you paste a valid token, Social Flow stores it locally on this computer or VPS. It is not stored in browser cookies.'}</p>${output?`<details class="helper-command"><summary>${lang==='es'?'Detalles tecnicos':'Technical details'}</summary><span class="step-command">${escapeHtml(String(output).slice(0,900))}</span></details>`:''}</div>`}},0)}
function connectMetaStarted(){showMetaTokenBox();toast(lang==='es'?'Meta Developers se abrira en otra pestaña. Sigue tus screenshots y pega aqui tu token.':'Meta Developers will open in another tab. Follow your screenshots and paste your token here.')}
let metaTokenAutoSaveTimer=null;
let metaTokenSaving=false;
let lastMetaTokenSaved='';
function renderTokenSavedState(){const tokenBox=qs('#meta-token-box');if(tokenBox){tokenBox.innerHTML=`<div class="guide-card"><b>${lang==='es'?'Token guardado':'Token saved'}</b><p>${lang==='es'?'La conexión quedó guardada en este computador o VPS. Ahora buscaré tus cuentas publicitarias.':'The connection is saved on this computer or VPS. I will now find your ad accounts.'}</p><button class="btn" type="button" onclick="goToMetaTokenStep()">${lang==='es'?'Pegar otro token':'Paste another token'}</button></div>`;tokenBox.classList.add('open')}}
function scheduleMetaTokenAutoSave(){clearTimeout(metaTokenAutoSaveTimer);const token=(qs('#meta-token-input')?.value||'').trim();if(token.length<20||token===lastMetaTokenSaved)return;metaTokenAutoSaveTimer=setTimeout(()=>saveMetaToken({auto:true}),500)}
async function saveMetaToken(options={}){const auto=Boolean(options.auto);const input=qs('#meta-token-input');const token=(input?.value||'').trim();const box=qs('#social-account-results');if(!token){if(!auto)toast(lang==='es'?'Pega primero el token de Meta.':'Paste the Meta token first.');return}if(token.length<20){if(!auto)toast(lang==='es'?'Ese token se ve muy corto. Revisa que lo pegaste completo.':'That token looks too short. Check that you pasted the full value.');return}if(metaTokenSaving||token===lastMetaTokenSaved)return;metaTokenSaving=true;lastMetaTokenSaved=token;if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Guardando conexion local...':'Saving local connection...'}</p></div>`;try{const res=await api('/api/social/token',{method:'POST',body:JSON.stringify({token})});const result=res.result||res;if(result.saved){toast(lang==='es'?'Token guardado localmente. Buscando cuentas...':'Token saved locally. Finding accounts...');renderTokenSavedState();await refreshSocialAccounts()}else{lastMetaTokenSaved='';renderSocialAccountResults({...result,accounts:[]})}}finally{metaTokenSaving=false}}
function renderSocialAccountResults(res){
 const box=qs('#social-account-results');if(!box)return;
 if(res.accounts&&res.accounts.length){
  box.innerHTML=res.accounts.map(a=>`<div class="guide-card"><b>${escapeHtml(a.name||a.id)}</b><p>${escapeHtml(a.id)}${a.currency?` · ${escapeHtml(a.currency)}`:''}</p><button class="btn primary" type="button" onclick="selectSocialAccount('${escapeHtml(a.id)}')">${lang==='es'?'Usar esta cuenta y seguir':'Use this account and continue'}</button></div>`).join('');
  return;
 }
 const output=String(res.output||'').slice(0,900);
 const expired=Boolean(res.needs_login||res.token_expired||/expired|OAuthException|Code:\\s*190|auth login/i.test(output));
 if(expired){
  goToMetaTokenStep('expired',output);
  return;
 }
 const loginHint=lang==='es'?'No pude traer cuentas todavia. Pega y guarda tu token de Meta, o revisa que el token tenga permisos de anuncios.':'I could not fetch accounts yet. Paste and save your Meta token, or check that the token has ads permissions.';
 box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No encontre cuentas':'No accounts found'}</b><p>${loginHint}</p><div class="onboarding-step-actions"><button class="btn primary" type="button" onclick="goToMetaTokenStep()">${lang==='es'?'Pegar token':'Paste token'}</button></div>${output?`<details class="helper-command"><summary>${lang==='es'?'Detalles tecnicos':'Technical details'}</summary><span class="step-command">${escapeHtml(output)}</span></details>`:''}</div>`;
}
async function refreshSocialAccounts(){const box=qs('#social-account-results');if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Buscando cuentas...':'Finding accounts...'}</p></div>`;const res=await api('/api/social/accounts');renderSocialAccountResults(res)}
function discoveryResultsBox(){return qs('#destination-discovery-results')||qs('#social-account-results')}
function encodePageChoice(page){return encodeURIComponent(JSON.stringify(page||{}))}
function renderPageChoice(page){
 const ig=page.instagram||{};const website=page.website||page.link||'';const encoded=encodePageChoice(page);
 return `<div class="guide-card"><b>${escapeHtml(page.name||page.id)}</b><p>${escapeHtml(page.id)}${ig.id?` · Instagram: ${escapeHtml(ig.username||ig.name||ig.id)}`:''}${website?` · ${escapeHtml(website)}`:''}</p><button class="btn primary" type="button" onclick="selectMetaDestination('${encoded}')">${lang==='es'?'Usar esta página':'Use this Page'}</button></div>`;
}
async function selectMetaDestination(encoded){
 const page=JSON.parse(decodeURIComponent(encoded));const ig=page.instagram||{};const website=page.website||page.link||'';
 const payload={page_id:page.id||'',instagram_actor_id:ig.id||'',landing_url:website||''};
 try{await api('/api/setup-config',{method:'POST',body:JSON.stringify(payload)});toast(lang==='es'?'Página guardada. Sigamos.':'Page saved. Let us continue.');await load();advanceOnboardingAfterLoad()}catch(err){if(needsBusinessReplacement(err)){showBusinessReplacementConfirm(payload);return}throw err}
}
function renderDiscoveredAssets(res){
 const box=discoveryResultsBox();if(!box)return;
 const result=res.result||res;const s=result.suggested||{};const pages=result.pages||[];const urls=result.urls||[];
 const pageCards=pages.length?`<div class="guide-panel"><b>${lang==='es'?'Páginas encontradas':'Pages found'}</b><p>${lang==='es'?'Elige la página que quieres usar para tus anuncios. Si tiene Instagram conectado, también lo guardo.':'Choose the Page you want to use for your ads. If it has connected Instagram, I save it too.'}</p></div>${pages.map(renderPageChoice).join('')}`:'';
 if(result.ok&&(result.saved||pages.length)){
  const rows=[];
  if(s.page_id)rows.push(`<div class="guide-card"><b>${lang==='es'?'Página encontrada':'Page found'}</b><p>${escapeHtml(s.page_name||s.page_id)} · ${escapeHtml(s.page_id)}</p></div>`);
  if(s.instagram_actor_id)rows.push(`<div class="guide-card"><b>Instagram</b><p>${escapeHtml(s.instagram_username||s.instagram_actor_id)} · ${escapeHtml(s.instagram_actor_id)}</p></div>`);
  if(s.landing_url)rows.push(`<div class="guide-card"><b>${lang==='es'?'Web encontrada':'Website found'}</b><p>${escapeHtml(s.landing_url)}</p></div>`);
  box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'Encontré datos conectados':'I found connected assets'}</b><p>${lang==='es'?'Usé el token local para buscar páginas, Instagram y web. Si la página sugerida no es la correcta, elige otra de la lista.':'I used the local token to find Pages, Instagram, and website. If the suggested Page is not right, choose another one from the list.'}</p></div>${rows.join('')}${pageCards}`;
  return;
 }
 box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude encontrar todo automáticamente':'I could not find everything automatically'}</b><p>${lang==='es'?'Esto normalmente significa que el token no tiene permisos de páginas, o que la página/Instagram no están conectados. Puedes seguir y llenar esos datos manualmente en el siguiente paso.':'This usually means the token does not have Page permissions, or the Page/Instagram are not connected. You can continue and fill those details manually in the next step.'}</p><p class="notice">${pages.length?`${pages.length} page(s)`:''}${urls.length?` · ${urls.length} URL(s)`:''}</p></div>`;
}
async function discoverMetaAssets(id){const box=discoveryResultsBox();if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Buscando página, Instagram y web conectados...':'Finding connected Page, Instagram, and website...'}</p></div>`;const res=await api('/api/social/discover-assets',{method:'POST',body:JSON.stringify({ad_account_id:id})});renderDiscoveredAssets(res);return res}
async function selectSocialAccount(id){try{await api('/api/social/default-account',{method:'POST',body:JSON.stringify({ad_account_id:id})})}catch(err){if(needsBusinessReplacement(err)){showBusinessReplacementConfirm({ad_account_id:id});return}throw err}const input=qs('input[name="ad_account_id"]');if(input)input.value=id;toast(lang==='es'?'Cuenta guardada. Buscando perfiles conectados...':'Account saved. Finding connected assets...');const discovered=await discoverMetaAssets(id);try{await api('/api/action',{method:'POST',body:JSON.stringify({action:'refresh_insights'})})}catch(err){}await load();const steps=onboardingSteps();const destinationIndex=steps.findIndex(s=>s.id==='destination');if(destinationIndex>=0){onboardingFlowTouched=true;onboardingFlowStep=destinationIndex;renderOnboardingFlow();renderDiscoveredAssets(discovered)}else advanceOnboardingAfterLoad()}
async function unlockFromOnboarding(e){e.preventDefault();const input=qs('#onboarding-password');const err=qs('#onboarding-unlock-error');const value=(input?.value||'').trim();if(!value)return;if(err){err.textContent='';err.classList.remove('show')}const res=await fetch('/api/unlock',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':value},body:JSON.stringify({})});if(!res.ok){if(err){err.textContent=t('unlock_failed');err.classList.add('show')}return}localStorage.removeItem('dashboardToken');if(qs('#onboarding-remember')?.checked)localStorage.setItem('dashboardPassword',value);else localStorage.removeItem('dashboardPassword');toast(lang==='es'?'Dashboard desbloqueado':'Dashboard unlocked');onboardingFlowStep=Math.max(onboardingFlowStep,1);await load()}
async function setDashboardPasswordFromOnboarding(e){e.preventDefault();const password=(qs('#new-dashboard-password')?.value||'').trim();const confirm=(qs('#confirm-dashboard-password')?.value||'').trim();const err=qs('#dashboard-password-error');if(err){err.textContent='';err.classList.remove('show')}if(password.length<8){if(err){err.textContent=lang==='es'?'Usa al menos 8 caracteres.':'Use at least 8 characters.';err.classList.add('show')}return}if(password!==confirm){if(err){err.textContent=lang==='es'?'Las contraseñas no coinciden.':'Passwords do not match.';err.classList.add('show')}return}const res=await fetch('/api/dashboard-password',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':dashboardPassword()},body:JSON.stringify({password,confirm_password:confirm})});if(!res.ok){if(err){err.textContent=await res.text();err.classList.add('show')}return}localStorage.removeItem('dashboardToken');if(qs('#new-dashboard-remember')?.checked)localStorage.setItem('dashboardPassword',password);else localStorage.removeItem('dashboardPassword');toast(lang==='es'?'Contraseña guardada. Te llevo a la guía final.':'Password saved. Taking you to the final guide.');await load();const steps=onboardingSteps();const guideIndex=steps.findIndex(s=>s.id==='guide');onboardingFlowTouched=true;onboardingFlowStep=guideIndex>=0?guideIndex:onboardingFlowStep;renderOnboardingFlow()}
async function activateLicense(){const res=await api('/api/license/activate',{method:'POST',body:JSON.stringify({})});toast(`${t('toast_license')}: ${localText(res.result.detail||res.result.status||'')}`);await load();if(res.result&&res.result.valid)advanceOnboardingAfterLoad()}
function closeConfirm(){qs('#confirm-overlay')?.classList.remove('open')}
function showOnboardingCompleteConfirm(){const box=qs('#confirm-overlay');box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Terminar onboarding':'Finish onboarding'}</h2><p>${lang==='es'?'La guía inicial dejará de aparecer automáticamente en este equipo. Esto no bloquea la configuración: podrás cambiar todo después desde Configuración.':'The initial guide will stop opening automatically on this device. This does not lock your setup: you can change everything later from Setup.'}</p><ul><li>${lang==='es'?'Cuenta publicitaria':'Ad account'}</li><li>${lang==='es'?'Página de Facebook, Instagram y web':'Facebook Page, Instagram, and website'}</li><li>${lang==='es'?'Contraseña del dashboard':'Dashboard password'}</li><li>${lang==='es'?'Reglas de supervisión y piloto automático':'Supervision and autopilot rules'}</li></ul><div class="confirm-actions"><button class="btn" type="button" onclick="closeConfirm()">${lang==='es'?'Seguir revisando':'Keep reviewing'}</button><button class="btn primary" type="button" onclick="finishOnboardingConfirmed()">${lang==='es'?'Terminar y abrir dashboard':'Finish and open dashboard'}</button></div></div>`;box.classList.add('open')}
async function finishOnboardingConfirmed(){closeConfirm();await api('/api/onboarding/complete',{method:'POST',body:JSON.stringify({})});toast(lang==='es'?'Onboarding completado. Puedes editar la configuración cuando quieras.':'Onboarding completed. You can edit setup anytime.');await load()}
async function completeOnboarding(){if(!(dashboardPassword()&&state.config.dashboard_password_set)){toast(lang==='es'?'Primero crea tu contraseña del dashboard.':'Create your dashboard password first.');onboardingFlowStep=onboardingSteps().length-1;renderOnboardingFlow();return}showOnboardingCompleteConfirm()}
async function resetOnboarding(){const ok=confirm(lang==='es'?'Esto hará que la guía de onboarding vuelva a aparecer. ¿Continuar?':'This will make the onboarding guide appear again. Continue?');if(!ok)return;await api('/api/onboarding/reset',{method:'POST',body:JSON.stringify({})});toast(lang==='es'?'Onboarding reiniciado':'Onboarding reset');await load()}
qs('#unlock-form').addEventListener('submit',e=>{e.preventDefault();const value=qs('#unlock-password').value.trim();if(!value)return;localStorage.removeItem('dashboardToken');if(qs('#remember-device').checked)localStorage.setItem('dashboardPassword',value);else localStorage.removeItem('dashboardPassword');hideUnlock();if(unlockResolver){unlockResolver(value);unlockResolver=null}qs('#unlock-password').value=''})
qs('#language-select').addEventListener('change',e=>{lang=e.target.value;localStorage.setItem('dashboardLang',lang);render()})
qs('#chat-input').addEventListener('input',resizeChatInput)
qs('#agent-bar-input').addEventListener('input',resizeAgentBarInput)
qs('#chat-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();const form=qs('#chat-form');if(form.requestSubmit){form.requestSubmit()}else{form.dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}))}}})
qs('#agent-bar-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();const form=qs('#agent-chat-bar');if(form.requestSubmit){form.requestSubmit()}else{form.dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}))}}})
qs('#chat-form').addEventListener('submit',async e=>{e.preventDefault();const input=qs('#chat-input');const text=input.value.trim();if(!text)return;input.value='';resizeChatInput();await sendChatMessage(text)})
qs('#agent-chat-bar').addEventListener('submit',async e=>{e.preventDefault();const input=qs('#agent-bar-input');const text=input.value.trim();if(!text){input.focus();return}input.value='';resizeAgentBarInput();await sendChatMessage(text,{workspace:true})})
document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));btn.classList.add('active');['overview','setup','creator','audiences','creatives','reports'].forEach(t=>qs('#tab-'+t).classList.toggle('hidden',t!==btn.dataset.tab))}))
qs('#campaign-form').addEventListener('submit',async e=>{e.preventDefault();const payload=Object.fromEntries(new FormData(e.target).entries());await api('/api/campaigns',{method:'POST',body:JSON.stringify(payload)});toast('Campaign staged for approval');await load()})
qs('#audience-form').addEventListener('submit',async e=>{e.preventDefault();const payload=Object.fromEntries(new FormData(e.target).entries());payload.consent=e.target.elements.consent.checked?'yes':'no';await buildAudienceStrategy(payload)})
syncPanels();
load();
</script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    PROTECTED_GET_PATHS = {"/api/export", "/api/report"}
    PROTECTED_POST_PATHS = {"/api/unlock", "/api/dashboard-password", "/api/action", "/api/campaigns", "/api/audience-strategy", "/api/business-profile", "/api/business-profile/scan", "/api/brand-guides/init", "/api/codex/creative-plan", "/api/setup-config", "/api/guardrails", "/api/telegram/config", "/api/telegram/detect", "/api/telegram/test", "/api/license/activate", "/api/onboarding/complete", "/api/onboarding/reset", "/api/agency/spaces", "/api/agency/spaces/switch", "/api/approve", "/api/chat", "/api/chat/reset", "/api/creative-refresh", "/api/stage-upload", "/api/execute-upload", "/api/mode"}
    ONBOARDING_OPEN_POSTS = {"/api/dashboard-password", "/api/setup-config", "/api/business-profile", "/api/business-profile/scan", "/api/brand-guides/init", "/api/license/activate", "/api/social/token", "/api/social/default-account", "/api/social/discover-assets", "/api/onboarding/complete", "/api/agency/spaces/switch"}

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self):
        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_redirect(self, url):
        self.send_response(302)
        self.send_header("Location", url)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def provided_token(self, parsed, payload=None):
        query = parse_qs(parsed.query)
        return self.headers.get("X-Dashboard-Token") or query.get("token", [""])[0] or (payload or {}).get("dashboard_token", "")

    def require_auth(self, parsed, payload=None):
        config = load_config()
        if dashboard_token_valid(config, self.provided_token(parsed, payload)):
            return True
        self.send_json({"error": "dashboard password required"}, 401)
        return False

    def auth_required_for_post(self, path):
        return path in self.PROTECTED_POST_PATHS and not (path in self.ONBOARDING_OPEN_POSTS and not load_onboarding_state().get("completed"))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in self.PROTECTED_GET_PATHS and not self.require_auth(parsed):
            return
        if parsed.path in {"/", "/dashboard"}:
            self.send_html()
        elif parsed.path == "/api/dashboard":
            self.send_json(dashboard_payload())
        elif parsed.path == "/api/export":
            self.send_json(export_csv())
        elif parsed.path == "/api/report":
            self.send_json(run_daily_agent()[1])
        elif parsed.path == "/api/setup":
            self.send_json(build_setup_status())
        elif parsed.path == "/api/social/auth-status":
            self.send_json(social_auth_status())
        elif parsed.path == "/api/social/login-url":
            self.send_json(social_login_url())
        elif parsed.path == "/api/social/login":
            self.send_redirect(social_login_url()["url"])
        elif parsed.path == "/api/social/accounts":
            self.send_json(social_marketing_accounts())
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        try:
            parsed = urlparse(self.path)
            payload = self.read_body()
            if self.auth_required_for_post(parsed.path) and not self.require_auth(parsed, payload):
                return
            if parsed.path == "/api/unlock":
                self.send_json({"ok": True, "result": {"unlocked": True}})
            elif parsed.path == "/api/dashboard-password":
                self.send_json({"ok": True, "result": set_dashboard_password(payload)})
            elif parsed.path == "/api/social/token":
                self.send_json({"ok": True, "result": social_save_facebook_token(payload)})
            elif parsed.path == "/api/social/default-account":
                self.send_json({"ok": True, "result": social_set_default_account(payload)})
            elif parsed.path == "/api/social/discover-assets":
                self.send_json({"ok": True, "result": social_discover_assets(payload)})
            elif parsed.path == "/api/action":
                if payload.get("action") not in {"run_agent"}:
                    require_license_unlock("live dashboard action")
                result = apply_action(payload)
                if isinstance(result, tuple):
                    result = result[0]
                self.send_json({"ok": True, "result": result})
            elif parsed.path == "/api/campaigns":
                require_cloud_license("Campaign creation requires an active license")
                self.send_json({"ok": True, "result": create_campaign(payload)})
            elif parsed.path == "/api/audience-strategy":
                self.send_json({"ok": True, "result": create_audience_strategy(payload, payload.get("language", "es"))})
            elif parsed.path == "/api/business-profile":
                self.send_json({"ok": True, "result": save_business_context(payload)})
            elif parsed.path == "/api/business-profile/scan":
                self.send_json({"ok": True, "result": scan_business_website(payload)})
            elif parsed.path == "/api/brand-guides/init":
                self.send_json({"ok": True, "result": initialize_brand_guides(payload)})
            elif parsed.path == "/api/codex/creative-plan":
                self.send_json({"ok": True, "result": codex_creative_plan(payload)})
            elif parsed.path == "/api/setup-config":
                self.send_json({"ok": True, "result": save_setup_config(payload)})
            elif parsed.path == "/api/guardrails":
                self.send_json({"ok": True, "result": save_guardrails(payload)})
            elif parsed.path == "/api/agency/spaces":
                self.send_json({"ok": True, "result": create_agency_space(payload)})
            elif parsed.path == "/api/agency/spaces/switch":
                self.send_json({"ok": True, "result": switch_agency_space(payload)})
            elif parsed.path == "/api/telegram/config":
                self.send_json({"ok": True, "result": save_telegram_config(payload)})
            elif parsed.path == "/api/telegram/detect":
                self.send_json({"ok": True, "result": detect_telegram_chats()})
            elif parsed.path == "/api/telegram/test":
                self.send_json({"ok": True, "result": test_telegram_connection()})
            elif parsed.path == "/api/license/activate":
                self.send_json({"ok": True, "result": activate_license_now()})
            elif parsed.path == "/api/onboarding/complete":
                self.send_json({"ok": True, "result": complete_onboarding()})
            elif parsed.path == "/api/onboarding/reset":
                self.send_json({"ok": True, "result": reset_onboarding()})
            elif parsed.path == "/api/approve":
                require_license_unlock("approval execution")
                self.send_json({"ok": True, "result": approve_pending(payload.get("approval_id"))})
            elif parsed.path == "/api/mode":
                self.send_json({"ok": True, "result": set_mode(payload)})
            elif parsed.path == "/api/chat/reset":
                self.send_json({"ok": True, "result": reset_chat_history()})
            elif parsed.path == "/api/chat":
                chat_payload = dict(payload)
                dashboard = dashboard_payload()
                previous_history = load_chat_history()
                chat_payload["history"] = previous_history
                chat_payload.setdefault("metrics", dashboard["metrics"])
                chat_payload.setdefault("recommendations", dashboard["recommendations"])
                chat_payload.setdefault("fatigue", dashboard["fatigue"])
                chat_payload.setdefault("pending", dashboard["pending"])
                chat_payload.setdefault("audience_strategy", dashboard["audience_strategy"])
                chat_payload.setdefault("brand_guides", dashboard["brand_guides"])
                chat_payload.setdefault("business_profile", dashboard.get("business_profile", {}))
                chat_result = agent_chat(load_config(), chat_payload)
                tool_result = execute_agent_tool(chat_result.get("tool_request"), chat_payload)
                if tool_result:
                    chat_result["routed_action"] = tool_result
                    chat_result["reply"] = tool_result.get("reply") or chat_result.get("reply")
                chat_result["history"] = append_chat_turn(payload.get("message", ""), chat_result.get("reply", ""))
                self.send_json({"ok": True, "result": chat_result})
            elif parsed.path == "/api/creative-refresh":
                metrics = load_metrics()
                campaign_id = payload.get("campaign_id")
                campaigns = metrics.get("campaigns", [])
                if campaign_id:
                    campaigns = [campaign for campaign in campaigns if campaign.get("id") == campaign_id]
                else:
                    campaigns = [campaign for campaign in campaigns if campaign.get("health") in {"fatigue", "losing"}]
                    if not campaigns and metrics.get("campaigns"):
                        campaigns = [sorted(metrics.get("campaigns", []), key=lambda c: c.get("roas", 0))[0]]
                results = []
                for campaign in campaigns:
                    plan, manifest_path = generate_creative_refresh(campaign)
                    results.append({"id": plan["id"], "manifest_path": str(manifest_path)})
                self.send_json({"ok": True, "result": results})
            elif parsed.path == "/api/stage-upload":
                payload_result, payload_path, approval = stage_upload(payload.get("manifest_path"), payload.get("variant_id", "v1"), payload.get("ratios") or ["1:1"])
                self.send_json({"ok": True, "result": {"payload_path": str(payload_path), "status": payload_result["status"], "missing_requirements": payload_result["missing_requirements"], "approval": approval}})
            elif parsed.path == "/api/execute-upload":
                require_license_unlock("creative upload execution")
                self.send_json({"ok": True, "result": execute_upload_payload(payload.get("payload_path"))})
            else:
                self.send_json({"error": "not found"}, 404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 400)

    def log_message(self, fmt, *args):
        print(f"[dashboard] {self.address_string()} - {fmt % args}")


def write_static_snapshot():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not METRICS_FILE.exists():
        save_metrics(sample_metrics())
    with open(DASHBOARD_HTML_FILE, "w", encoding="utf-8") as handle:
        handle.write(HTML)


def main():
    query = parse_qs(urlparse(sys.argv[1]).query) if len(sys.argv) > 1 and sys.argv[1].startswith("?") else {}
    config = load_config()
    host = query.get("host", [config.dashboard_host])[0]
    port = int(query.get("port", [config.dashboard_port or PORT])[0])
    allow_public_for_session = str(query.get("allow_public", ["false"])[0]).lower() in {"1", "true", "yes", "on"}
    if is_public_bind(host) and not (config.allow_public_dashboard or allow_public_for_session):
        print("Refusing to start dashboard on a public host.")
        print("Keep DASHBOARD_HOST=127.0.0.1, or set ALLOW_PUBLIC_DASHBOARD=true only behind HTTPS, firewall, and a reverse proxy.")
        return 2
    write_static_snapshot()
    ensure_telegram_listener()
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print("Meta Ads Agent dashboard")
    print(f"URL: http://{host}:{port}")
    print(f"Dashboard password required: {config.dashboard_token_required}")
    print(f"Data: {DATA_DIR}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
