#!/usr/bin/env python3
"""
Admira IA - web dashboard and daily agent runner.

Run:
    python3 dashboard/monitoring-dashboard.py

Open:
    http://127.0.0.1:7871
"""
import csv
import base64
import hashlib
import hmac
import ipaddress
import json
import mimetypes
import os
import py_compile
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import datetime
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import zipfile

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_chat import chat as agent_chat
from audience_builder import build_audience_strategy
from budget_optimizer import BudgetOptimizer, OptimizationStrategy, PerformanceMetrics
from campaign_creator import CampaignCreator
from communication_style import (
    ad_experience_from_environment,
    ad_experience_instruction,
    ad_experience_is_configured,
    communication_preference,
    communication_style_from_environment,
    communication_style_is_configured,
    normalize_ad_experience_level,
    normalize_communication_style,
)
from codex_brand_guides import (
    BRAND_ASSET_DIR,
    BRAND_LOGO_EXTENSIONS,
    build_codex_image_prompt_package,
    call_codex_image_cli,
    call_codex_cli,
    composite_official_logo,
    ensure_brand_guides,
    guide_library,
    hermes_codex_image_status,
    normalize_ad_brief_payload,
    normalize_general_payload,
    normalize_product_payload,
    official_logo_prompt_lock,
    official_brand_logo_path,
    product_reference,
    save_creative_references,
    save_ad_brief,
    save_general_guide,
    save_product_guide,
)
from creative_refresh import (
    CREATIVE_IMAGE_STORAGE_POLICY,
    asset_storage_state,
    clear_temporary_creative_assets,
    generate_creative_refresh,
    recent_creative_refreshes,
)
from daily_agent import approve as approve_pending, build_action_summary, reject as reject_pending, run_daily as run_scheduled_daily
from decision_memory import (
    decision_memory_payload,
    load_profitability_rules,
    recommendation_decision_evidence,
    save_profitability_rules as persist_profitability_rules,
)
from experiment_scheduler import (
    experiment_review_payload,
    normalize_insight_rows as normalize_experiment_insights,
    run_due_reviews as run_due_experiment_reviews,
    schedule_experiment,
)
from graph_executor import execute_upload_payload
from hermes_bridge import hermes_codex_ready, hermes_codex_session_status, hermes_environment, safe_image_paths
from hermes_gateway import (
    ensure_daily_brief_cron,
    ensure_experiment_review_cron,
    ensure_experiment_review_crons,
    ensure_weekly_research_cron,
    gateway_status as hermes_gateway_status,
    start_gateway as start_hermes_gateway,
)
from hermes_gateway import telegram_settings
from license import activate_license, default_device_id, license_status, mark_license_install_state, normalize_license_entitlements, validate_license_key
from local_store import now_iso, read_json, write_json, write_private_json
from meta_insights import aggregate_campaigns as aggregate_meta_campaigns, collect_meta_snapshot, save_meta_snapshot
from meta_upload import recent_uploads, stage_upload
from optimization_engine import (
    anomaly_diagnostics,
    funnel_diagnostics,
    confirm_and_unlock as confirm_optimization_unlock,
    load_optimization_state,
    portfolio_recommendations,
    reconcile_business_outcomes,
    record_optimization_action,
    save_optimization_state,
    unlock_status as optimization_unlock_status,
)
from optimization_research import RESEARCH_FILE, load_research, save_research_item, seed_current_research
from product_config import (
    ENV_FILE,
    default_codex_image_hermes_home,
    env_bool,
    image_codex_config,
    load_config,
    normalize_codex_image_source,
    normalize_daily_time,
    normalize_timezone,
    resolved_codex_image_hermes_home,
)
from public_asset_fetcher import fetch_public_asset_result
from security import dashboard_password_configured, dashboard_token_valid, hash_dashboard_password, is_local_host, is_public_bind, redact_payload
from shopify_connector import normalize_shop_domain, shopify_status, sync_shopify, test_connection as test_shopify_connection
from setup_status import build_setup_status
from adset_controls import normalize_placement_config, placement_config_summary
from expert_campaign import (
    campaign_preview,
    creative_format_review,
    merge_expert_targeting,
    normalize_bidding,
    normalize_billing_event,
    normalize_budget_plan,
    normalize_creative_controls,
    normalize_schedule,
    success_metric_candidates_from_text,
    normalize_success_metrics,
    normalize_status_plan,
    requires_active_confirmation,
)
from signal_quality import apply_signal_quality_to_adset, review_signal_quality, signal_quality_reply
from social_flow_client import SocialFlowClient
from telegram_agent import bot_request as telegram_bot_request
from telegram_agent import reset_polling_state as reset_telegram_polling_state
from verified_signal_ledger import feedback_prompt as verified_signal_feedback_prompt
from verified_signal_ledger import ledger_summary as verified_signal_ledger_summary
from verified_signal_ledger import record_signal as record_verified_signal
from verified_signal_ledger import record_signal_batch as record_verified_signal_batch

try:
    from product_config import normalize_hermes_model
except ImportError:
    def normalize_hermes_model(value):
        model = str(value or "").strip()
        if not model or model.lower() in {"auto", "recommended", "recomendado", "default"}:
            return "gpt-5.5"
        return model


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(__file__).resolve().parent / "data"
PUBLIC_ASSETS_DIR = ROOT_DIR / "public"
OUTPUT_DIR = ROOT_DIR / "output"
METRICS_FILE = DATA_DIR / "metrics.json"
ACTIONS_FILE = DATA_DIR / "actions.json"
PENDING_FILE = DATA_DIR / "pending_approvals.json"
CREATED_FILE = DATA_DIR / "created_campaigns.json"
AUDIENCE_FILE = DATA_DIR / "audience_strategy.json"
ONBOARDING_FILE = DATA_DIR / "onboarding_state.json"
CHAT_HISTORY_FILE = DATA_DIR / "chat_history.json"
DASHBOARD_SESSIONS_FILE = DATA_DIR / "dashboard_sessions.json"
BUSINESS_PROFILE_FILE = DATA_DIR / "business_profile.json"
VERIFIED_SIGNAL_LEDGER_FILE = DATA_DIR / "verified_signal_ledger.json"
ONBOARDING_QUESTIONS_FILE = DATA_DIR / "Onboarding questions.md"
AGENT_ONBOARDING_PLAN_FILE = DATA_DIR / "Agent onboarding plan.md"
ADS_ONBOARDING_FILE = DATA_DIR / "Ads campaign onboarding.md"
INDIVIDUAL_BINDING_FILE = DATA_DIR / "individual_business_binding.json"
MANAGED_AD_ACCOUNTS_FILE = DATA_DIR / "managed_ad_accounts.json"
AGENCY_SPACES_FILE = DATA_DIR / "agency_spaces.json"
AGENCY_SPACES_DIR = DATA_DIR / "agency_spaces"
AD_CONFIG_FILE = ROOT_DIR / "ad-config.json"
DASHBOARD_HTML_FILE = DATA_DIR / "dashboard.html"
DASHBOARD_IDENTITY_FILE = DATA_DIR / "dashboard_identity.json"
BRAND_GUIDES_DIR = ROOT_DIR / "brand_guides"
BRAND_PRODUCTS_DIR = BRAND_GUIDES_DIR / "products"
MIGRATION_ROOT_NAME = "MetaAdsAgent-migracion"
VERSION_FILE = ROOT_DIR / "VERSION"
BOOTSTRAP_CONFIG_FILE = ROOT_DIR / "installer" / "release-bootstrap.env"
UPDATE_SNAPSHOTS_DIR = DATA_DIR / "update-snapshots"
UPDATE_SNAPSHOT_ROOT_NAME = "MetaAdsAgent-rollback"
MAX_UPDATE_SNAPSHOTS = 3
DEFAULT_POST_LIMIT_BYTES = 2 * 1024 * 1024
MIGRATION_POST_LIMIT_BYTES = 140 * 1024 * 1024
MAX_MIGRATION_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_UPDATE_ARCHIVE_BYTES = 220 * 1024 * 1024
MAX_UPDATE_UNPACKED_BYTES = 300 * 1024 * 1024
MAX_MANAGED_META_AD_ACCOUNTS = 5
CURRENT_DASHBOARD_BIND_HOST = ""
CURRENT_DASHBOARD_BIND_PORT = 0
CREATIVE_ASSET_ROOT = OUTPUT_DIR / "creatives"
CREATIVE_ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
PUBLIC_ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".css", ".js", ".mp4", ".mov"}
MAX_BRAND_LOGO_BYTES = 1 * 1024 * 1024
PORT = 7871
TARGET_CPA = 50.0
TELEGRAM_THREAD = None
TELEGRAM_STOP = None
TELEGRAM_FINGERPRINT = None
HERMES_LOGIN_OUTPUT_LIMIT = 12000
DASHBOARD_SESSION_PREFIX = "das_"
DASHBOARD_SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
HERMES_LOGIN_LOCK = threading.Lock()
HERMES_LOGIN_STATE = {
    "id": "",
    "status": "idle",
    "title": "",
    "detail": "",
    "output": "",
    "phase": "",
    "auto_note": "",
    "auto_provider_sent": False,
    "auto_codex_subprovider_sent": False,
    "auto_model_sent": False,
    "preferred_model": "",
    "started_at": "",
    "updated_at": "",
    "proc": None,
    "fd": None,
    "command": "",
}
AGENT_INTERVIEW_DEFERRED_REASONS = {"entrevista_negocio", "branding_creativos", "campanas_anuncios", "perfil_negocio"}
DASHBOARD_SETUP_DEFERRED_REASONS = {"licencia", "conexion_facebook", "cuenta_publicitaria", "cerebro_agente", "telegram", "conexion_meta", "destinos", "datos_reales"}
CHAT_HISTORY_LIMIT = 40
CREATIVE_MEMORY_WIZARD_FILE = DATA_DIR / "creative_memory_wizard.json"
BUSINESS_DATA_FILES = [
    "metrics.json",
    "actions.json",
    "pending_approvals.json",
    "created_campaigns.json",
    "audience_strategy.json",
    "onboarding_state.json",
    "chat_history.json",
    "creative_memory_wizard.json",
    "creative_experiments.json",
    "optimization_state.json",
    "performance_history.json",
    "business_outcomes.json",
    "shopify_sync_state.json",
    "optimization_research.json",
    "business_profile.json",
    "managed_ad_accounts.json",
    "Onboarding questions.md",
    "Agent onboarding plan.md",
    "Ads campaign onboarding.md",
    "telegram_chat_history.json",
    "telegram_offset.json",
]
EXAMPLE_AD_ACCOUNT_IDS = {"123456789", "act_123456789"}
BUSINESS_ENV_KEYS = [
    "META_AD_ACCOUNT_ID",
    "META_ACCESS_TOKEN",
    "META_ACCESS_TOKEN_KIND",
    "META_ACCESS_TOKEN_SAVED_AT",
    "TELEGRAM_AGENT_ENABLED",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_LANGUAGE",
    "SHOPIFY_SHOP_DOMAIN",
    "SHOPIFY_ADMIN_API_TOKEN",
    "SHOPIFY_API_VERSION",
]
BUSINESS_OUTPUT_DIRS = [
    OUTPUT_DIR / "creatives",
    OUTPUT_DIR / "uploads",
    OUTPUT_DIR / "telegram_uploads",
]
PRESERVED_UPDATE_PATHS = {".env", "ad-config.json", "dashboard/data", "logs", "output", "runtime"}

def redact_error_text(value, limit=1200):
    text = str(value or "")
    replacements = [
        (r"EAA[A-Za-z0-9_\-]{20,}", "[meta-token-redacted]"),
        (r"sk-[A-Za-z0-9_\-]{16,}", "[api-key-redacted]"),
        (r"\b\d{6,}:[A-Za-z0-9_\-]{20,}\b", "[telegram-token-redacted]"),
        (r"\bMAO-[A-Z0-9\-]{8,}\b", "[license-redacted]"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    text = text.replace(str(ROOT_DIR), "[instalacion]")
    return text[:limit]


def client_error_message(exc):
    message = redact_error_text(exc)
    if isinstance(exc, (ValueError, json.JSONDecodeError)):
        return message or "No pude completar la solicitud."
    print(f"[dashboard] internal error: {message}")
    return "No pude completar la solicitud. Revisa la configuracion o intenta de nuevo."


def sanitize_migration_env(path):
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    sanitized = []
    seen_device_id = False
    for line in lines:
        if line.startswith("LICENSE_DEVICE_ID="):
            sanitized.append("LICENSE_DEVICE_ID=")
            seen_device_id = True
        else:
            sanitized.append(line)
    if not seen_device_id:
        sanitized.append("LICENSE_DEVICE_ID=")
    path.write_text("\n".join(sanitized).rstrip() + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def remove_device_specific_unlocks(root):
    for relative in [
        Path("dashboard/data/license_unlock.json"),
        Path("dashboard/data/dashboard.html"),
        Path("dashboard/data/dashboard_sessions.json"),
    ]:
        target = root / relative
        if target.exists():
            target.unlink()


def dashboard_session_digest(token):
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def valid_dashboard_password_hash(value):
    return str(value or "").strip().startswith("pbkdf2_sha256$")


def save_dashboard_identity_backup(password_hash):
    password_hash = str(password_hash or "").strip()
    if not valid_dashboard_password_hash(password_hash):
        return False
    existing = read_json(DASHBOARD_IDENTITY_FILE, {})
    payload = {
        "dashboard_password_hash": password_hash,
        "updated_at": now_iso(),
        "created_at": existing.get("created_at") or now_iso() if isinstance(existing, dict) else now_iso(),
    }
    write_private_json(DASHBOARD_IDENTITY_FILE, payload)
    return True


def ensure_dashboard_identity_backup(config=None):
    config = config or load_config()
    password_hash = str(getattr(config, "dashboard_password_hash", "") or "").strip()
    if not valid_dashboard_password_hash(password_hash):
        return False
    existing = read_json(DASHBOARD_IDENTITY_FILE, {})
    if isinstance(existing, dict) and existing.get("dashboard_password_hash") == password_hash:
        return True
    return save_dashboard_identity_backup(password_hash)


def dashboard_session_store():
    payload = read_json(DASHBOARD_SESSIONS_FILE, {"sessions": []})
    if not isinstance(payload, dict):
        payload = {"sessions": []}
    sessions = payload.get("sessions")
    if not isinstance(sessions, list):
        sessions = []
    now_ts = int(time.time())
    payload["sessions"] = [
        session
        for session in sessions
        if isinstance(session, dict) and int(session.get("expires_at") or 0) > now_ts
    ][:20]
    return payload


def save_dashboard_session_store(payload):
    write_private_json(DASHBOARD_SESSIONS_FILE, payload)


def create_dashboard_session(remember=True):
    token = DASHBOARD_SESSION_PREFIX + secrets.token_urlsafe(32)
    now_ts = int(time.time())
    ttl = DASHBOARD_SESSION_TTL_SECONDS if remember else 12 * 60 * 60
    payload = dashboard_session_store()
    payload["sessions"].insert(
        0,
        {
            "digest": dashboard_session_digest(token),
            "created_at": now_ts,
            "expires_at": now_ts + ttl,
            "remembered": bool(remember),
        },
    )
    payload["sessions"] = payload["sessions"][:20]
    save_dashboard_session_store(payload)
    return {"session_token": token, "expires_at": now_ts + ttl}


def dashboard_session_valid(token):
    token = str(token or "")
    if not token.startswith(DASHBOARD_SESSION_PREFIX):
        return False
    digest = dashboard_session_digest(token)
    payload = dashboard_session_store()
    valid = any(
        hmac.compare_digest(str(session.get("digest") or ""), digest)
        for session in payload.get("sessions", [])
    )
    save_dashboard_session_store(payload)
    return valid


def copy_migration_state(target_root):
    package_root = target_root / MIGRATION_ROOT_NAME
    package_root.mkdir(parents=True, exist_ok=True)
    for relative in [Path(".env"), Path("ad-config.json")]:
        source = ROOT_DIR / relative
        if source.exists():
            destination = package_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    for relative in [Path("dashboard/data"), Path("brand_guides"), Path("output")]:
        source = ROOT_DIR / relative
        if source.exists():
            destination = package_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "import-backups"))
    sanitize_migration_env(package_root / ".env")
    remove_device_specific_unlocks(package_root)
    (package_root / "LEEME-MIGRACION.txt").write_text(
        "Este respaldo mueve la memoria local de Admira IA a otro equipo.\n"
        "Despues de restaurarlo, activa la licencia en el nuevo equipo para generar un nuevo ID local.\n",
        encoding="utf-8",
    )
    return package_root


def create_migration_archive():
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"meta-ads-agent-respaldo-{timestamp}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="meta-ads-migration-") as tmp_name:
        tmp_root = Path(tmp_name)
        package_root = copy_migration_state(tmp_root)
        archive_path = tmp_root / filename
        with tarfile.open(archive_path, "w:gz") as archive:
            archive.add(package_root, arcname=MIGRATION_ROOT_NAME)
        return filename, archive_path.read_bytes()


def is_safe_extract_member(base_dir, member_name):
    target = (base_dir / member_name).resolve()
    return str(target).startswith(str(base_dir.resolve()) + os.sep) or target == base_dir.resolve()


def zip_member_is_safe(member):
    mode = (member.external_attr >> 16) & 0o170000
    return mode != 0o120000


def extract_migration_archive(archive_path, target_dir):
    name = archive_path.name.lower()
    if name.endswith(".zip"):
        total_size = 0
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                total_size += int(member.file_size or 0)
                if total_size > MAX_MIGRATION_ARCHIVE_BYTES:
                    raise ValueError("El respaldo es demasiado grande para restaurarlo desde el dashboard.")
                if not is_safe_extract_member(target_dir, member.filename) or not zip_member_is_safe(member):
                    raise ValueError("El respaldo contiene rutas no seguras.")
            archive.extractall(target_dir)
        return
    with tarfile.open(archive_path, "r:*") as archive:
        total_size = 0
        for member in archive.getmembers():
            if not is_safe_extract_member(target_dir, member.name):
                raise ValueError("El respaldo contiene rutas no seguras.")
            if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                raise ValueError("El respaldo contiene enlaces no seguros.")
            total_size += int(member.size or 0)
            if total_size > MAX_MIGRATION_ARCHIVE_BYTES:
                raise ValueError("El respaldo es demasiado grande para restaurarlo desde el dashboard.")
        archive.extractall(target_dir)


def backup_current_migration_state():
    backup_dir = DATA_DIR / "import-backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    copy_migration_state(backup_dir)
    return backup_dir / MIGRATION_ROOT_NAME


def restore_migration_archive(payload):
    filename = str(payload.get("filename") or "respaldo.tar.gz")
    encoded = str(payload.get("content_base64") or "")
    if not encoded:
        raise ValueError("Sube el respaldo que creaste desde este dashboard.")
    try:
        content = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("No pude leer ese archivo de respaldo.") from exc
    if len(content) > MAX_MIGRATION_ARCHIVE_BYTES:
        raise ValueError("El respaldo es demasiado grande para restaurarlo desde el dashboard.")
    restored = []
    with tempfile.TemporaryDirectory(prefix="meta-ads-restore-") as tmp_name:
        tmp_root = Path(tmp_name)
        archive_path = tmp_root / Path(filename).name
        archive_path.write_bytes(content)
        extract_dir = tmp_root / "extract"
        extract_dir.mkdir()
        extract_migration_archive(archive_path, extract_dir)
        source_root = extract_dir / MIGRATION_ROOT_NAME
        if not source_root.exists():
            candidates = [item for item in extract_dir.iterdir() if item.is_dir()]
            source_root = candidates[0] if candidates else extract_dir
        backup_root = backup_current_migration_state()
        for relative in [Path(".env"), Path("ad-config.json")]:
            source = source_root / relative
            if source.exists():
                destination = ROOT_DIR / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                restored.append(str(relative))
        for relative in [Path("dashboard/data"), Path("brand_guides"), Path("output")]:
            source = source_root / relative
            if source.exists():
                destination = ROOT_DIR / relative
                if destination.exists():
                    shutil.rmtree(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "import-backups"))
                restored.append(str(relative))
        sanitize_migration_env(ENV_FILE)
        remove_device_specific_unlocks(ROOT_DIR)
    log_action("migration_restore", {"restored": restored, "backup": str(backup_root)}, "completed")
    return {
        "restored": restored,
        "backup": str(backup_root),
        "message": "Respaldo restaurado. Activa la licencia en este equipo antes de usar acciones reales.",
    }


def update_snapshot_id():
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def safe_snapshot_id(value):
    snapshot_id = str(value or "").strip()
    if not snapshot_id or not re.fullmatch(r"[A-Za-z0-9_.-]+", snapshot_id):
        raise ValueError("Ese punto de restauracion no es valido.")
    return snapshot_id


def is_skipped_snapshot_path(relative, source):
    parts = set(relative.parts)
    if source.name in {".git", "node_modules", "__pycache__", ".pytest_cache", ".DS_Store", ".env", "ad-config.json"}:
        return True
    if source.name.endswith((".pyc", ".log", ".zip", ".tar.gz", ".dmg", ".exe", ".pkg", ".msi")):
        return True
    if relative.parts and relative.parts[0] in {"release", "node_modules", ".git", "logs", "output", "dist", "build"}:
        return True
    if relative.parts[:2] == ("dashboard", "data"):
        return True
    return "__pycache__" in parts or "node_modules" in parts


def copy_for_update_snapshot(source, destination, relative):
    if is_skipped_snapshot_path(relative, source):
        return
    if source.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            copy_for_update_snapshot(child, destination / child.name, relative / child.name)
        return
    if source.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def copy_update_snapshot_payload(target_root):
    payload_root = target_root / UPDATE_SNAPSHOT_ROOT_NAME
    payload_root.mkdir(parents=True, exist_ok=True)
    for item in ROOT_DIR.iterdir():
        copy_for_update_snapshot(item, payload_root / item.name, Path(item.name))
    return payload_root


def directory_size(path):
    total = 0
    if not path.exists():
        return total
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def read_update_snapshot_manifest(snapshot_dir):
    manifest = read_json(snapshot_dir / "manifest.json", {})
    if not manifest:
        return {}
    manifest.setdefault("id", snapshot_dir.name)
    manifest.setdefault("version", "")
    manifest.setdefault("created_at", "")
    manifest.setdefault("reason", "")
    manifest.setdefault("channel", "stable")
    return manifest


def list_update_snapshots(include_rescue=False):
    UPDATE_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    snapshots = []
    for item in UPDATE_SNAPSHOTS_DIR.iterdir():
        if not item.is_dir() or item.name.endswith(".tmp"):
            continue
        manifest = read_update_snapshot_manifest(item)
        if not manifest or not (item / UPDATE_SNAPSHOT_ROOT_NAME).exists():
            continue
        if not include_rescue and manifest.get("reason") != "pre_update":
            continue
        snapshots.append(manifest)
    return sorted(snapshots, key=lambda item: item.get("created_at", ""), reverse=True)


def prune_update_snapshots(limit=MAX_UPDATE_SNAPSHOTS):
    snapshots = list_update_snapshots(include_rescue=False)
    for manifest in snapshots[limit:]:
        snapshot_id = safe_snapshot_id(manifest.get("id"))
        shutil.rmtree(UPDATE_SNAPSHOTS_DIR / snapshot_id, ignore_errors=True)


def create_update_snapshot(reason="pre_update", release=None, prune=True):
    UPDATE_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_id = update_snapshot_id()
    temp_dir = UPDATE_SNAPSHOTS_DIR / f"{snapshot_id}.tmp"
    final_dir = UPDATE_SNAPSHOTS_DIR / snapshot_id
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)
    try:
        copy_update_snapshot_payload(temp_dir)
        manifest = {
            "id": snapshot_id,
            "created_at": now_iso(),
            "reason": reason,
            "version": current_product_version(),
            "target_version": str((release or {}).get("latest_version") or ""),
            "channel": str((release or {}).get("channel") or release_settings(load_config())["channel"]),
            "payload_root": UPDATE_SNAPSHOT_ROOT_NAME,
            "size_bytes": directory_size(temp_dir / UPDATE_SNAPSHOT_ROOT_NAME),
        }
        write_private_json(temp_dir / "manifest.json", manifest)
        temp_dir.rename(final_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    if prune:
        prune_update_snapshots()
    log_action("update_snapshot_create", {"id": snapshot_id, "reason": reason, "version": manifest["version"]}, "completed")
    return manifest


def remove_path(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def restore_dashboard_data(source_data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for child in DATA_DIR.iterdir():
        if child.name == "update-snapshots":
            continue
        remove_path(child)
    for child in source_data.iterdir():
        if child.name == "update-snapshots":
            continue
        restore_path(child, DATA_DIR / child.name)


def restore_dashboard_dir(source_dashboard):
    destination_dashboard = ROOT_DIR / "dashboard"
    destination_dashboard.mkdir(parents=True, exist_ok=True)
    for child in source_dashboard.iterdir():
        if child.name == "data":
            restore_dashboard_data(child)
        else:
            restore_path(child, destination_dashboard / child.name)


def restore_path(source, destination):
    if source.is_dir() and not source.is_symlink():
        remove_path(destination)
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "node_modules", ".git"))
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    remove_path(destination)
    shutil.copy2(source, destination)


def restore_update_snapshot(payload):
    snapshot_id = safe_snapshot_id(payload.get("snapshot_id"))
    snapshot_dir = UPDATE_SNAPSHOTS_DIR / snapshot_id
    manifest = read_update_snapshot_manifest(snapshot_dir)
    source_payload = snapshot_dir / UPDATE_SNAPSHOT_ROOT_NAME
    if not manifest or not source_payload.exists():
        raise ValueError("No encontre ese punto de restauracion.")
    rescue = create_update_snapshot(reason="pre_rollback", release={"channel": manifest.get("channel", ""), "latest_version": manifest.get("version", "")}, prune=False)
    restored = []
    with tempfile.TemporaryDirectory(prefix="meta-ads-rollback-") as tmp_name:
        tmp_payload = Path(tmp_name) / UPDATE_SNAPSHOT_ROOT_NAME
        shutil.copytree(source_payload, tmp_payload, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for child in tmp_payload.iterdir():
            if child.name == "dashboard":
                restore_dashboard_dir(child)
            else:
                restore_path(child, ROOT_DIR / child.name)
            restored.append(child.name)
    log_action("official_update_rollback", {"snapshot_id": snapshot_id, "version": manifest.get("version"), "rescue_snapshot_id": rescue.get("id")}, "completed")
    threading.Timer(1.2, restart_dashboard_process).start()
    return {
        "restored": restored,
        "snapshot": manifest,
        "rescue_snapshot_id": rescue.get("id"),
        "message": "Version anterior restaurada. El dashboard se reiniciara automaticamente.",
    }


def public_client_ip(handler):
    forwarded = handler.headers.get("X-Forwarded-For", "")
    candidates = [item.strip() for item in forwarded.split(",") if item.strip()]
    candidates.append(handler.client_address[0] if handler.client_address else "")
    for candidate in candidates:
        try:
            parsed = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if not (parsed.is_loopback or parsed.is_private or parsed.is_link_local or parsed.is_reserved):
            return str(parsed)
    return ""


def refresh_digitalocean_access(client_ip):
    if not client_ip:
        raise ValueError("No pude reconocer esta red. Abre el dashboard desde la red que quieres usar e intenta otra vez.")
    script = ROOT_DIR / "scripts" / "digitalocean-refresh-firewall.sh"
    if not script.exists():
        raise ValueError("No encontre el actualizador de DigitalOcean en esta instalacion.")
    result = subprocess.run(
        [str(script), "--ip", client_ip, "--quiet"],
        cwd=str(ROOT_DIR),
        text=True,
        capture_output=True,
        timeout=45,
        check=False,
    )
    output = "\n".join((result.stdout or "").splitlines()[-8:] + (result.stderr or "").splitlines()[-8:])
    if result.returncode != 0:
        raise ValueError("No pude permitir esta red todavía. Revisa tu instalación en DigitalOcean o contacta soporte.")
    log_action("digitalocean_access_refresh", {"client_ip": client_ip}, "completed")
    return {"client_ip": client_ip, "output": output.strip(), "message": "Acceso actualizado para esta red."}


def read_key_value_file(path):
    values = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def current_product_version():
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "v1"
    env_value = os.environ.get("META_ADS_AGENT_VERSION", "").strip()
    if env_value:
        return env_value
    return "v1"


def version_parts(value):
    numbers = re.findall(r"\d+", str(value or ""))
    return tuple(int(part) for part in numbers) if numbers else (0,)


def is_newer_version(remote, current):
    remote_text = str(remote or "").strip()
    current_text = str(current or "").strip()
    if not remote_text or remote_text == current_text:
        return False
    return version_parts(remote_text) > version_parts(current_text)


def release_settings(config):
    bootstrap = read_key_value_file(BOOTSTRAP_CONFIG_FILE)
    return {
        "license_server_url": (config.license_server_url or bootstrap.get("LICENSE_SERVER_URL", "")).rstrip("/"),
        "release_endpoint": bootstrap.get("LICENSE_RELEASE_ENDPOINT", "/api/license/release") or "/api/license/release",
        "channel": os.environ.get("META_ADS_RELEASE_CHANNEL", bootstrap.get("RELEASE_CHANNEL", "stable")) or "stable",
        "asset_name": os.environ.get("META_ADS_RELEASE_ASSET_NAME", bootstrap.get("RELEASE_ASSET_NAME", "MetaAdsAgent-source.zip")) or "MetaAdsAgent-source.zip",
    }


def official_download_url_allowed(download_url, settings):
    parsed_download = urllib.parse.urlparse(str(download_url or ""))
    parsed_server = urllib.parse.urlparse(str(settings.get("license_server_url") or ""))
    if parsed_download.scheme != "https" or parsed_server.scheme != "https":
        return False
    return parsed_download.netloc.lower() == parsed_server.netloc.lower() and parsed_download.path.startswith("/api/download/release")


def download_limited(url, target_path, max_bytes):
    request = urllib.request.Request(str(url), headers={"User-Agent": "MetaAdsAgentUpdater/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            raise ValueError("La actualizacion oficial es demasiado grande.")
        total = 0
        with open(target_path, "wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("La actualizacion oficial es demasiado grande.")
                handle.write(chunk)


def normalize_improvements(items):
    if not isinstance(items, list):
        return []
    normalized = []
    for item in items[:8]:
        if isinstance(item, str):
            normalized.append({"title": item[:90], "body": "", "impact": "Mejora incluida"})
        elif isinstance(item, dict):
            title = str(item.get("title") or item.get("name") or "Mejora incluida").strip()
            body = str(item.get("body") or item.get("description") or "").strip()
            impact = str(item.get("impact") or item.get("area") or "Optimización").strip()
            normalized.append({"title": title[:90], "body": body[:260], "impact": impact[:80]})
    return normalized


def fallback_improvements():
    return [
        {
            "title": "Mejoras oficiales del manager",
            "body": "Esta version fue publicada desde el canal oficial y puede incluir estabilidad, seguridad, interfaz y capacidades nuevas del agente.",
            "impact": "Actualizacion recomendada",
        }
    ]


def update_safety_warnings():
    config = load_config()
    warnings = []
    if getattr(config, "live_actions_enabled", False) or getattr(config, "mode", "") == "live":
        warnings.append({
            "code": "live_mode",
            "title": "Piloto automatico activo",
            "body": "Estas en modo de cambios reales. Si no necesitas esta actualizacion ahora, es mas tranquilo actualizar fuera de una ventana critica.",
        })
    metrics = load_metrics()
    active = [campaign for campaign in metrics.get("campaigns", []) if str(campaign.get("status", "")).lower() in {"active", "enabled"}]
    if active:
        warnings.append({
            "code": "active_campaigns",
            "title": "Campanas activas detectadas",
            "body": f"Hay {len(active)} campana(s) activa(s). Se creara un punto de restauracion antes de actualizar, pero Meta seguira corriendo afuera del dashboard.",
        })
    return warnings


def request_update_release():
    config = load_config()
    settings = release_settings(config)
    if not settings["license_server_url"]:
        raise ValueError("No hay servidor oficial de actualizaciones configurado.")
    device_id = config.license_device_id or os.environ.get("LICENSE_DEVICE_ID", "") or default_device_id()
    payload = {
        "license_key": config.license_key,
        "buyer_email": config.license_buyer_email,
        "device_id": device_id,
        "channel": settings["channel"],
        "asset_name": settings["asset_name"],
    }
    request = urllib.request.Request(
        settings["license_server_url"] + settings["release_endpoint"],
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=18) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise ValueError("No pude consultar el canal oficial de actualizaciones. Revisa internet o intenta mas tarde.") from exc
    if not data.get("valid"):
        raise ValueError(data.get("detail") or "No pude confirmar tu licencia para buscar actualizaciones.")
    current = current_product_version()
    remote = str(data.get("version") or "").strip()
    improvements = normalize_improvements(data.get("improvements")) or fallback_improvements()
    return {
        "available": is_newer_version(remote, current),
        "current_version": current,
        "latest_version": remote or current,
        "channel": settings["channel"],
        "asset_name": settings["asset_name"],
        "download_url": data.get("download_url", ""),
        "expires_at": data.get("expires_at", ""),
        "improvements": improvements,
        "warnings": update_safety_warnings(),
        "snapshot_policy": {"automatic": True, "keep": MAX_UPDATE_SNAPSHOTS},
    }


def safe_copytree_contents(source, target, base=None):
    base = base or source
    for item in source.iterdir():
        relative = item.relative_to(base).as_posix()
        if relative in PRESERVED_UPDATE_PATHS or any(relative.startswith(prefix + "/") for prefix in PRESERVED_UPDATE_PATHS):
            continue
        destination = target / item.name
        if item.is_dir():
            if item.name in {"dashboard", "brand_guides"}:
                destination.mkdir(parents=True, exist_ok=True)
                safe_copytree_contents(item, destination, base)
            else:
                if destination.exists():
                    shutil.rmtree(destination)
                shutil.copytree(item, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "node_modules", ".git"))
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)


def restart_dashboard_process():
    try:
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except OSError as exc:
        print(f"[dashboard] restart failed after update: {exc}")


def detect_lan_ip():
    configured = str(os.environ.get("ADMIRO_HOST_LAN_IP") or "").strip()
    if configured:
        try:
            if ipaddress.ip_address(configured).version == 4:
                return configured
        except ValueError:
            pass
    candidates = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.settimeout(0.2)
            probe.connect(("8.8.8.8", 80))
            candidates.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_DGRAM):
            candidates.append(info[4][0])
    except OSError:
        pass
    for candidate in candidates:
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if ip.version == 4 and not ip.is_loopback:
            return str(ip)
    return ""


def install_environment_label():
    if os.environ.get("CLOUD_DASHBOARD_HOSTNAME") or os.environ.get("DIGITALOCEAN_DROPLET_ID"):
        return "cloud"
    if Path("/.dockerenv").exists() or os.environ.get("ADMIRO_HOST_LAN_IP"):
        return "docker"
    return "native"


def host_header_hostname(raw_host):
    value = str(raw_host or "").strip()
    if not value:
        return ""
    if value.startswith("[") and "]" in value:
        return value[1:value.index("]")]
    return value.split(":", 1)[0].strip().lower()


def request_host_is_local(raw_host):
    hostname = host_header_hostname(raw_host)
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return ip.is_loopback


def dashboard_network_access_payload():
    config = load_config()
    bind_host = CURRENT_DASHBOARD_BIND_HOST or config.dashboard_host
    bind_port = CURRENT_DASHBOARD_BIND_PORT or config.dashboard_port or PORT
    public_bind = is_public_bind(bind_host)
    enabled = bool(config.lan_access_enabled)
    lan_ip = detect_lan_ip()
    lan_url = f"http://{lan_ip}:{bind_port}/" if enabled and lan_ip else ""
    desired_host = "0.0.0.0" if enabled else "127.0.0.1"
    restart_needed = bool((enabled and not public_bind) or (not enabled and public_bind and install_environment_label() == "native"))
    return {
        "enabled": enabled,
        "active": bool(enabled and public_bind),
        "lan_url": lan_url,
        "lan_ip": lan_ip,
        "port": bind_port,
        "bind_host": bind_host,
        "public_bind": public_bind,
        "restart_needed": restart_needed,
        "install_environment": install_environment_label(),
        "desired_host": desired_host,
    }


def set_local_network_access(payload):
    enabled = str((payload or {}).get("enabled") or "").strip().lower() in {"1", "true", "yes", "on", "si", "sí"}
    environment = install_environment_label()
    updates = {"LAN_ACCESS_ENABLED": "true" if enabled else "false"}
    if environment == "native":
        updates["DASHBOARD_HOST"] = "0.0.0.0" if enabled else "127.0.0.1"
        updates["ALLOW_PUBLIC_DASHBOARD"] = "true" if enabled else "false"
    elif enabled:
        updates["ALLOW_PUBLIC_DASHBOARD"] = "true"
    update_env_values(updates)
    result = dashboard_network_access_payload()
    should_restart = bool(result["restart_needed"])
    log_action("local_network_access", {"enabled": enabled, "environment": environment, "restart_needed": should_restart}, "completed")
    if should_restart:
        threading.Timer(1.0, restart_dashboard_process).start()
    return {**result, "saved": True, "restarting": should_restart}


def run_update_health_checks():
    dashboard_file = ROOT_DIR / "dashboard" / "monitoring-dashboard.py"
    py_compile.compile(str(dashboard_file), doraise=True)
    config = load_config()
    ensure_dashboard_identity_backup(config)
    required = [ROOT_DIR / ".env", ROOT_DIR / "ad-config.json", VERSION_FILE, dashboard_file]
    missing = [str(path.relative_to(ROOT_DIR)) for path in required if not path.exists()]
    if missing:
        raise ValueError("La actualizacion quedo incompleta. Faltan: " + ", ".join(missing))
    if "</html>" not in dashboard_file.read_text(encoding="utf-8").lower():
        raise ValueError("La interfaz del dashboard no pudo validarse despues de actualizar.")
    return {"ok": True, "checked": ["python", "config", "required_files", "dashboard_html"]}


def apply_official_update():
    release = request_update_release()
    if not release["available"]:
        return {**release, "installed": False, "message": "Ya tienes la version mas reciente."}
    download_url = release.get("download_url")
    settings = release_settings(load_config())
    if not download_url or not official_download_url_allowed(download_url, settings):
        raise ValueError("El servidor oficial no devolvio una descarga valida.")
    snapshot = create_update_snapshot(reason="pre_update", release=release)
    with tempfile.TemporaryDirectory(prefix="meta-ads-update-") as tmp_name:
        tmp_root = Path(tmp_name)
        archive_path = tmp_root / "release.zip"
        try:
            download_limited(download_url, archive_path, MAX_UPDATE_ARCHIVE_BYTES)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise ValueError("No pude descargar la actualizacion oficial. Intenta mas tarde.") from exc
        unpack_dir = tmp_root / "unpack"
        unpack_dir.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            total_size = 0
            for member in archive.infolist():
                total_size += int(member.file_size or 0)
                if total_size > MAX_UPDATE_UNPACKED_BYTES:
                    raise ValueError("La actualizacion oficial es demasiado grande.")
                if not is_safe_extract_member(unpack_dir, member.filename) or not zip_member_is_safe(member):
                    raise ValueError("La actualizacion contiene rutas no seguras.")
            archive.extractall(unpack_dir)
        safe_copytree_contents(unpack_dir, ROOT_DIR)
        installed_version = str(release["latest_version"]).strip()
        VERSION_FILE.write_text(installed_version + "\n", encoding="utf-8")
        update_env_values({"META_ADS_AGENT_VERSION": installed_version})
        os.environ["META_ADS_AGENT_VERSION"] = installed_version
        try:
            for script in (ROOT_DIR / "scripts").glob("*.sh"):
                script.chmod(0o755)
        except OSError:
            pass
    health = run_update_health_checks()
    log_action("official_update_apply", {"from": release["current_version"], "to": release["latest_version"], "channel": release["channel"], "snapshot_id": snapshot.get("id")}, "completed")
    threading.Timer(1.2, restart_dashboard_process).start()
    return {**release, "installed": True, "snapshot": snapshot, "health": health, "message": "Actualizacion instalada. El dashboard se reiniciara automaticamente."}


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
    try:
        ENV_FILE.chmod(0o600)
    except OSError:
        pass
    for key, value in values.items():
        os.environ[key] = str(value)


def license_entitlements():
    status = license_status(load_config())
    if not status.get("valid"):
        status = {**status, "plan": "individual", "max_devices": 1, "workspace_limit": 1, "features": []}
    return normalize_license_entitlements(status)


def clean_ad_account_id(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    return raw if raw.startswith("act_") else f"act_{raw}"


def business_manager_info_from(value):
    if not isinstance(value, dict):
        return {"id": "", "name": ""}
    business = value.get("business") if isinstance(value.get("business"), dict) else {}
    business_manager = value.get("business_manager") if isinstance(value.get("business_manager"), dict) else {}
    business_id = str(
        value.get("business_id")
        or value.get("business_manager_id")
        or business.get("id")
        or business_manager.get("id")
        or ""
    ).strip()
    business_name = str(
        value.get("business_name")
        or value.get("business_manager_name")
        or business.get("name")
        or business_manager.get("name")
        or ""
    ).strip()
    return {"id": business_id, "name": business_name}


def managed_account_from(value):
    if not isinstance(value, dict):
        value = {"id": value}
    account_id = clean_ad_account_id(value.get("id") or value.get("ad_account_id") or value.get("account_id") or value.get("accountId"))
    if not account_id:
        return {}
    business = business_manager_info_from(value)
    return {
        "id": account_id,
        "name": str(value.get("name") or value.get("account_name") or value.get("business_name") or account_id).strip(),
        "currency": str(value.get("currency") or "").strip(),
        "status": str(value.get("account_status", value.get("status", ""))).strip(),
        "business_id": business["id"],
        "business_name": business["name"],
    }


def current_configured_ad_account_id():
    config = load_config()
    ad_config = read_json(AD_CONFIG_FILE, {})
    stored_ad_account_id = str(ad_config.get("account", {}).get("id", "")).strip()
    if stored_ad_account_id in EXAMPLE_AD_ACCOUNT_IDS:
        stored_ad_account_id = ""
    return clean_ad_account_id(config.ad_account_id or stored_ad_account_id)


def normalize_managed_accounts_state(state=None, seed=True):
    raw = state if isinstance(state, dict) else read_json(MANAGED_AD_ACCOUNTS_FILE, {})
    if not isinstance(raw, dict):
        raw = {}
    business = business_manager_info_from(raw.get("business_manager") if isinstance(raw.get("business_manager"), dict) else raw)
    active_id = clean_ad_account_id(raw.get("active_ad_account_id") or raw.get("active_account_id") or "")
    seen = set()
    accounts = []
    for item in raw.get("accounts") or []:
        account = managed_account_from(item)
        if not account or account["id"] in seen:
            continue
        if not business["id"] and account.get("business_id"):
            business = {"id": account.get("business_id", ""), "name": account.get("business_name", "")}
        if business["id"] and not account.get("business_id"):
            account["business_id"] = business["id"]
            account["business_name"] = business["name"]
        seen.add(account["id"])
        accounts.append(account)
    should_seed_current = seed and (INDIVIDUAL_BINDING_FILE.exists() or load_onboarding_state().get("completed") or bool(raw.get("accounts")))
    if should_seed_current and not accounts:
        seeded_id = current_configured_ad_account_id()
        binding = read_json(INDIVIDUAL_BINDING_FILE, {})
        binding_business = business_manager_info_from(binding)
        if not business["id"] and binding_business["id"]:
            business = binding_business
        if seeded_id:
            accounts.append({
                "id": seeded_id,
                "name": seeded_id,
                "currency": "",
                "status": "",
                "business_id": business["id"],
                "business_name": business["name"],
            })
            active_id = active_id or seeded_id
    if active_id and all(account["id"] != active_id for account in accounts):
        active_id = accounts[0]["id"] if accounts else ""
    if not active_id and accounts:
        active_id = accounts[0]["id"]
    return {
        "business_manager": business,
        "active_ad_account_id": active_id,
        "accounts": accounts[:MAX_MANAGED_META_AD_ACCOUNTS],
        "max_accounts": MAX_MANAGED_META_AD_ACCOUNTS,
    }


def write_managed_accounts_state(state):
    normalized = normalize_managed_accounts_state(state, seed=False)
    normalized["updated_at"] = now_iso()
    write_json(MANAGED_AD_ACCOUNTS_FILE, normalized)
    return normalize_managed_accounts_state(normalized, seed=False)


def managed_ad_accounts_payload():
    state = normalize_managed_accounts_state()
    used = len(state["accounts"])
    return {
        **state,
        "used": used,
        "remaining": max(0, MAX_MANAGED_META_AD_ACCOUNTS - used),
        "limit_note": "Máximo 5 cuentas publicitarias, todas bajo el mismo Business Manager.",
    }


def managed_account_context(account_id):
    account_id = clean_ad_account_id(account_id)
    if not account_id:
        return {}
    for account in normalize_managed_accounts_state().get("accounts", []):
        if account.get("id") == account_id:
            return account
    return {"id": account_id, "name": account_id}


def managed_metric_accounts():
    state = normalize_managed_accounts_state()
    accounts = [account for account in state.get("accounts", []) if account.get("id")]
    if accounts:
        return accounts
    active = current_configured_ad_account_id()
    return [{"id": active, "name": active}] if active else []


def managed_account_limit_status(account, state=None):
    account = managed_account_from(account)
    state = normalize_managed_accounts_state(state, seed=False) if state is not None else normalize_managed_accounts_state()
    if not account:
        return {"can_select": False, "reason": "missing_account"}
    accounts = state.get("accounts") or []
    managed_ids = {item.get("id") for item in accounts}
    if account["id"] in managed_ids:
        return {"can_select": True, "reason": "already_managed"}
    if len(accounts) >= MAX_MANAGED_META_AD_ACCOUNTS:
        return {"can_select": False, "reason": "max_accounts"}
    business = state.get("business_manager") or {}
    if business.get("id"):
        if not account.get("business_id"):
            return {"can_select": False, "reason": "business_manager_unknown"}
        if account.get("business_id") != business.get("id"):
            return {"can_select": False, "reason": "business_manager_mismatch"}
    elif accounts:
        return {"can_select": False, "reason": "business_manager_unknown"}
    return {"can_select": True, "reason": "same_business_manager"}


def annotate_accounts_with_management(accounts):
    state = normalize_managed_accounts_state()
    managed_ids = {item.get("id") for item in state.get("accounts", [])}
    active_id = state.get("active_ad_account_id", "")
    annotated = []
    for raw in accounts or []:
        account = managed_account_from(raw)
        if not account:
            continue
        status = managed_account_limit_status(account, state)
        annotated.append({
            **raw,
            **account,
            "managed": account["id"] in managed_ids,
            "active": account["id"] == active_id,
            **status,
        })
    return annotated


def prepare_managed_ad_account_update(account, replace_business=False):
    account = managed_account_from(account)
    if not account:
        raise ValueError("Missing ad account")
    state = normalize_managed_accounts_state(seed=not replace_business)
    if replace_business:
        state = {"business_manager": {"id": account.get("business_id", ""), "name": account.get("business_name", "")}, "active_ad_account_id": "", "accounts": [], "max_accounts": MAX_MANAGED_META_AD_ACCOUNTS}
    accounts = state.get("accounts") or []
    business = state.get("business_manager") or {"id": "", "name": ""}
    existing_index = next((idx for idx, item in enumerate(accounts) if item.get("id") == account["id"]), -1)
    if existing_index < 0:
        status = managed_account_limit_status(account, state)
        if not status["can_select"]:
            if status["reason"] == "max_accounts":
                raise ValueError("MAX_META_ACCOUNTS: Esta instalación puede manejar máximo 5 cuentas publicitarias al mismo tiempo.")
            if status["reason"] == "business_manager_mismatch":
                raise ValueError("CONFIRM_BUSINESS_REPLACE: Esa cuenta pertenece a otro Business Manager. Para cambiar de negocio hay que empezar limpio y quitar las cuentas anteriores.")
            raise ValueError("CONFIRM_BUSINESS_REPLACE: No pude confirmar que esa cuenta pertenece al mismo Business Manager. Para evitar mezclar negocios, confirma el cambio y empezamos limpio.")
        account["added_at"] = now_iso()
        accounts.append(account)
    else:
        account["added_at"] = accounts[existing_index].get("added_at") or now_iso()
        account["updated_at"] = now_iso()
        accounts[existing_index] = {**accounts[existing_index], **{key: value for key, value in account.items() if value or key in {"id", "name"}}}
    if not business.get("id") and account.get("business_id"):
        business = {"id": account.get("business_id", ""), "name": account.get("business_name", "")}
    for item in accounts:
        if business.get("id") and not item.get("business_id"):
            item["business_id"] = business.get("id", "")
            item["business_name"] = business.get("name", "")
    return {
        "business_manager": business,
        "active_ad_account_id": account["id"],
        "accounts": accounts,
        "max_accounts": MAX_MANAGED_META_AD_ACCOUNTS,
    }


def upsert_managed_ad_account(account, replace_business=False):
    return write_managed_accounts_state(prepare_managed_ad_account_update(account, replace_business=replace_business))


def business_identity(payload=None):
    config = load_config()
    ad_config = read_json(AD_CONFIG_FILE, {})
    destination = ad_config.get("creative", {}).get("destination", {})
    incoming = payload or {}
    stored_ad_account_id = str(ad_config.get("account", {}).get("id", "")).strip()
    if stored_ad_account_id in EXAMPLE_AD_ACCOUNT_IDS:
        stored_ad_account_id = ""
    managed = normalize_managed_accounts_state()
    business = business_manager_info_from(incoming) if incoming else {"id": "", "name": ""}
    if not business["id"]:
        business = managed.get("business_manager") or {"id": "", "name": ""}
    return {
        "ad_account_id": clean_ad_account_id(incoming.get("ad_account_id") or config.ad_account_id or stored_ad_account_id),
        "page_id": str(incoming.get("page_id") or destination.get("page_id", "")).strip(),
        "instagram_actor_id": str(incoming.get("instagram_actor_id") or destination.get("instagram_actor_id", "")).strip(),
        "business_manager_id": business["id"],
        "business_manager_name": business["name"],
    }


def changed_business_fields(payload):
    current = business_identity()
    incoming_identity = business_identity(payload)
    incoming_has_business_manager = bool(payload.get("business_manager_id") or payload.get("business_id"))
    same_business_manager = bool(
        incoming_has_business_manager
        and
        incoming_identity.get("business_manager_id")
        and current.get("business_manager_id")
        and incoming_identity.get("business_manager_id") == current.get("business_manager_id")
    )
    changes = {}
    for key in ["ad_account_id", "page_id", "instagram_actor_id"]:
        incoming = clean_ad_account_id(payload.get(key)) if key == "ad_account_id" and key in payload else (str(payload.get(key) or "").strip() if key in payload else "")
        if same_business_manager:
            continue
        if incoming and current.get(key) and incoming != current[key]:
            changes[key] = {"from": current[key], "to": incoming}
    return changes


def clear_business_memory():
    for name in BUSINESS_DATA_FILES:
        path = DATA_DIR / name
        if path.exists():
            path.unlink()
    for path in BUSINESS_OUTPUT_DIRS:
        if path.exists():
            shutil.rmtree(path)


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
        current_business = business_identity()
        incoming_business = business_identity(payload)
        if incoming_business.get("business_manager_id") and current_business.get("business_manager_id") and incoming_business.get("business_manager_id") != current_business.get("business_manager_id"):
            raise ValueError("CONFIRM_BUSINESS_REPLACE: Esa cuenta pertenece a otro Business Manager. Para cambiar de negocio hay que empezar limpio y quitar las cuentas anteriores.")
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
    output_target = target / "output"
    if output_target.exists():
        shutil.rmtree(output_target)
    output_target.mkdir(parents=True, exist_ok=True)
    for source in BUSINESS_OUTPUT_DIRS:
        if source.exists():
            shutil.copytree(source, output_target / source.name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    snapshot_business_brand_guides(target)
    config = load_config()
    env_values = {
        "META_AD_ACCOUNT_ID": config.ad_account_id,
        "META_ACCESS_TOKEN": config.meta_access_token,
        "META_ACCESS_TOKEN_KIND": config.meta_access_token_kind,
        "META_ACCESS_TOKEN_SAVED_AT": config.meta_access_token_saved_at,
        "TELEGRAM_AGENT_ENABLED": "true" if telegram_settings(config)["enabled"] else "false",
        "TELEGRAM_BOT_TOKEN": config.telegram_bot_token,
        "TELEGRAM_CHAT_ID": config.telegram_chat_id,
        "TELEGRAM_LANGUAGE": telegram_settings(config)["language"],
        "SHOPIFY_SHOP_DOMAIN": getattr(config, "shopify_shop_domain", ""),
        "SHOPIFY_ADMIN_API_TOKEN": getattr(config, "shopify_admin_token", ""),
        "SHOPIFY_API_VERSION": getattr(config, "shopify_api_version", "2026-04"),
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
    output_source = source_dir / "output"
    for source in BUSINESS_OUTPUT_DIRS:
        stored = output_source / source.name
        if stored.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(stored, source)
    stored = read_json(source_dir / "workspace_config.json", {"env": {}, "ad_config": {}})
    update_env_values({
        "META_AD_ACCOUNT_ID": "",
        "META_ACCESS_TOKEN": "",
        "META_ACCESS_TOKEN_KIND": "",
        "META_ACCESS_TOKEN_SAVED_AT": "",
        "TELEGRAM_AGENT_ENABLED": "false",
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
        "TELEGRAM_LANGUAGE": "es",
        "SHOPIFY_SHOP_DOMAIN": "",
        "SHOPIFY_ADMIN_API_TOKEN": "",
        "SHOPIFY_API_VERSION": "2026-04",
        **stored.get("env", {}),
    })
    write_json(AD_CONFIG_FILE, stored.get("ad_config") or {"account": {}, "creative": {"destination": {}}})


def agency_spaces_payload():
    limits = license_entitlements()
    registry = agency_registry()
    active = next((space for space in registry.get("spaces", []) if space.get("id") == registry.get("active_id")), None)
    usage = {
        "used": len(registry.get("spaces", [])),
        "limit": int(limits.get("workspace_limit") or 1),
        "remaining": max(0, int(limits.get("workspace_limit") or 1) - len(registry.get("spaces", []))),
    }
    return {**limits, **registry, "active_workspace": active or {}, "workspace_usage": usage}


def active_workspace_payload():
    spaces = agency_spaces_payload()
    if spaces["is_agency"]:
        return spaces.get("active_workspace") or {}
    binding = read_json(INDIVIDUAL_BINDING_FILE, {}) or business_identity()
    name_parts = [binding.get("ad_account_id"), binding.get("page_id")]
    return {
        "id": "individual-active-business",
        "name": " · ".join([part for part in name_parts if part]) or "Negocio activo",
        "type": "individual",
    }


def workspace_usage_payload():
    spaces = agency_spaces_payload()
    return spaces.get("workspace_usage") or {
        "used": 1 if any(business_identity().values()) else 0,
        "limit": license_entitlements()["workspace_limit"],
        "remaining": 0,
    }


def business_binding_payload():
    binding = read_json(INDIVIDUAL_BINDING_FILE, {})
    identity = business_identity()
    managed = managed_ad_accounts_payload()
    return {
        **identity,
        **binding,
        "managed_ad_accounts": managed,
        "business_manager": managed.get("business_manager", {}),
        "locked": not license_entitlements().get("is_agency") and bool(binding or load_onboarding_state().get("completed")),
    }


def create_agency_space(payload):
    limits = license_entitlements()
    if not limits.get("can_use_agency_workspaces", bool(limits.get("is_agency"))):
        raise ValueError("Tu licencia Individual cuida un solo negocio activo. Para manejar otro negocio, usa otra licencia separada.")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("Escribe el nombre del cliente o negocio.")
    registry = agency_registry()
    workspace_limit = int(limits.get("workspace_limit") or 1)
    if len(registry["spaces"]) >= workspace_limit:
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
    global TELEGRAM_THREAD, TELEGRAM_STOP, TELEGRAM_FINGERPRINT
    limits = license_entitlements()
    if not limits.get("can_use_agency_workspaces", bool(limits.get("is_agency"))):
        raise ValueError("Cambiar entre negocios no está disponible en esta licencia.")
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
    TELEGRAM_FINGERPRINT = None
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


def save_daily_brief_schedule(payload):
    raw_time = str(payload.get("time") or "").strip()
    normalized_time = normalize_daily_time(raw_time, default="")
    if not normalized_time or normalized_time != raw_time:
        raise ValueError("Elige una hora válida para la lectura diaria.")
    raw_timezone = str(payload.get("timezone") or "").strip()
    normalized_timezone = normalize_timezone(raw_timezone, default="")
    if not normalized_timezone or normalized_timezone != raw_timezone:
        raise ValueError("No pude reconocer la zona horaria de este dispositivo.")

    update_env_values({
        "DAILY_BRIEF_TIME": normalized_time,
        "DAILY_BRIEF_TIMEZONE": normalized_timezone,
    })
    ad_config = read_json(AD_CONFIG_FILE, {})
    ad_config.setdefault("reporting", {})["timezone"] = normalized_timezone
    write_json(AD_CONFIG_FILE, ad_config)

    config = load_config()
    gateway = start_hermes_gateway(config)
    cron = ensure_daily_brief_cron(config)
    experiment_crons = ensure_experiment_review_crons(config)
    research_cron = ensure_weekly_research_cron(config)
    log_action(
        "daily_brief_schedule_update",
        {"time": normalized_time, "timezone": normalized_timezone, "cron_configured": bool(cron.get("configured"))},
        "completed" if cron.get("configured") else "blocked",
    )
    return {
        "saved": True,
        "time": normalized_time,
        "timezone": normalized_timezone,
        "gateway": gateway,
        "cron": cron,
        "experiment_crons": experiment_crons,
        "research_cron": research_cron,
    }


def save_profitability_rule_settings(payload):
    rules = persist_profitability_rules(payload)
    log_action("profitability_rules_update", rules, "completed")
    return {"saved": True, "rules": rules}


def save_optimization_settings(payload):
    state = save_optimization_state(payload)
    log_action("optimization_settings_update", {key: value for key, value in state.items() if key not in {"last_actions", "proposal_outcomes"}}, "completed")
    return {"saved": True, "state": state, "unlock": optimization_unlock_status(state)}


def unlock_optimization(payload):
    result = confirm_optimization_unlock(bool(payload.get("confirm")))
    log_action("optimization_mode_update", {"mode": result["state"].get("mode"), "buyer_confirmed": bool(payload.get("confirm"))}, "completed")
    return result


def save_shopify_config(payload):
    config = load_config()
    disconnect = str(payload.get("disconnect") or "").lower() in {"1", "true", "yes", "on"}
    if disconnect:
        update_env_values({"SHOPIFY_SHOP_DOMAIN": "", "SHOPIFY_ADMIN_API_TOKEN": "", "SHOPIFY_API_VERSION": "2026-04"})
        log_action("shopify_disconnect", {}, "completed")
        return {"saved": True, "status": shopify_status(load_config())}
    domain = normalize_shop_domain(payload.get("shop_domain") or getattr(config, "shopify_shop_domain", ""))
    token = str(payload.get("admin_token") or "").strip()
    if token and len(token) < 20:
        raise ValueError("The Shopify Admin API token is too short.")
    if not token:
        token = getattr(config, "shopify_admin_token", "")
    if not token:
        raise ValueError("Paste a read-only Shopify Admin API token with read_orders scope.")
    api_version = str(payload.get("api_version") or getattr(config, "shopify_api_version", "2026-04")).strip()
    if not re.fullmatch(r"20\d{2}-(01|04|07|10)", api_version):
        api_version = "2026-04"
    update_env_values({"SHOPIFY_SHOP_DOMAIN": domain, "SHOPIFY_ADMIN_API_TOKEN": token, "SHOPIFY_API_VERSION": api_version})
    log_action("shopify_config_update", {"shop_domain": domain, "token_set": True, "api_version": api_version}, "completed")
    return {"saved": True, "status": shopify_status(load_config())}


def test_shopify_settings(_payload=None):
    config = load_config()
    if not getattr(config, "shopify_shop_domain", "") or not getattr(config, "shopify_admin_token", ""):
        raise ValueError("Connect Shopify first.")
    result = test_shopify_connection(config.shopify_shop_domain, config.shopify_admin_token, config.shopify_api_version)
    if not result.get("ok"):
        raise ValueError((result.get("error") or {}).get("message") or "Shopify connection failed.")
    log_action("shopify_connection_test", {"shop_domain": config.shopify_shop_domain, "ok": True}, "completed")
    return result


def sync_shopify_outcomes(_payload=None):
    config = load_config()
    if not getattr(config, "shopify_shop_domain", "") or not getattr(config, "shopify_admin_token", ""):
        raise ValueError("Connect Shopify first.")
    result = sync_shopify(config.shopify_shop_domain, config.shopify_admin_token, config.shopify_api_version)
    if not result.get("ok"):
        log_action("shopify_sync", {"shop_domain": config.shopify_shop_domain, "error": result.get("error")}, "blocked")
        raise ValueError((result.get("error") or {}).get("message") or "Shopify sync failed.")
    safe_result = {key: value for key, value in result.items() if key != "outcomes"}
    log_action("shopify_sync", safe_result, "completed")
    return safe_result


def telegram_welcome_text(language="es"):
    if str(language or "es").lower().startswith("en"):
        return (
            "Hello, I am connected now.\n\n"
            "You can talk to me here as your Meta Ads manager. "
            "I will first understand your business, then your visual brand, and then your ads strategy.\n\n"
            "Reply here when you are ready and I will continue one question at a time."
        )
    return (
        "Hola, ya quedé conectado.\n\n"
        "Puedes hablarme por aquí como tu manager de Meta Ads. "
        "Primero voy a entender tu negocio, después tu marca visual y luego tu estrategia de anuncios.\n\n"
        "Respóndeme aquí cuando estés listo y seguimos una pregunta a la vez."
    )


def send_telegram_welcome_message(config, chat_id, language="es"):
    chat = str(chat_id or "").strip()
    if not (config.telegram_bot_token and chat):
        return {"sent": False, "error": "telegram_not_ready"}
    try:
        telegram_bot_request(config, "sendMessage", {"chat_id": chat, "text": telegram_welcome_text(language)}, timeout=10)
        log_action("telegram_welcome_send", {"chat_id_set": True}, "completed")
        return {"sent": True}
    except Exception as exc:
        log_action("telegram_welcome_send", {"chat_id_set": True, "error": str(exc)}, "failed")
        return {"sent": False, "error": str(exc)}


def save_telegram_config(payload):
    old_config = load_config()
    limits = license_entitlements()
    registry = agency_registry()
    if limits.get("is_agency") and not limits.get("can_use_multi_telegram_profiles", bool(limits.get("is_agency"))) and len(registry.get("spaces", [])) > 1:
        raise ValueError("Varios perfiles de Telegram no están disponibles en esta licencia.")
    values = {}
    if "enabled" in payload:
        values["TELEGRAM_AGENT_ENABLED"] = "true" if str(payload.get("enabled")).strip().lower() in {"1", "true", "yes", "on"} else "false"
    if str(payload.get("bot_token") or "").strip():
        values["TELEGRAM_BOT_TOKEN"] = str(payload.get("bot_token")).strip()
    if "chat_id" in payload:
        values["TELEGRAM_CHAT_ID"] = str(payload.get("chat_id") or "").strip()
    if "language" in payload:
        values["TELEGRAM_LANGUAGE"] = "en" if str(payload.get("language")).strip().lower() == "en" else "es"
    next_bot = values.get("TELEGRAM_BOT_TOKEN", old_config.telegram_bot_token)
    next_chat = values.get("TELEGRAM_CHAT_ID", old_config.telegram_chat_id)
    connection_changed = next_bot != old_config.telegram_bot_token or next_chat != old_config.telegram_chat_id
    if values:
        update_env_values(values)
    if connection_changed:
        reset_telegram_polling_state()
    config = load_config()
    status = telegram_settings(config)
    gateway = ensure_telegram_listener()
    status["listener_started"] = bool(gateway.get("started") if isinstance(gateway, dict) else gateway)
    status["gateway"] = gateway if isinstance(gateway, dict) else {}
    if str(payload.get("send_welcome") or "").strip().lower() in {"1", "true", "yes", "on"} and status.get("chat_id"):
        welcome = send_telegram_welcome_message(config, status.get("chat_id"), status.get("language") or values.get("TELEGRAM_LANGUAGE") or "es")
        status["welcome_sent"] = bool(welcome.get("sent"))
        if welcome.get("error"):
            status["welcome_error"] = welcome.get("error")
    if status.get("enabled") and status.get("bot_configured") and status.get("chat_id"):
        profile = read_json(BUSINESS_PROFILE_FILE, {})
        if isinstance(profile, dict) and not profile.get("telegram_onboarding_message_sent_at"):
            write_onboarding_questions_memory(profile, "pending")
            profile["telegram_onboarding_message_sent_at"] = now_iso()
            profile["telegram_onboarding_channel"] = "hermes_gateway"
            write_json(BUSINESS_PROFILE_FILE, profile)
            status["onboarding_message_ready"] = True
        status["daily_brief_cron"] = ensure_daily_brief_cron(config)
        status["experiment_review_crons"] = ensure_experiment_review_crons(config)
        status["research_cron"] = ensure_weekly_research_cron(config)
    log_action("telegram_config_save", {"enabled": status["enabled"], "mode": status.get("mode"), "bot_configured": status["bot_configured"], "chat_id_set": bool(status["chat_id"])}, "completed")
    return status


def ensure_telegram_listener():
    global TELEGRAM_THREAD, TELEGRAM_STOP, TELEGRAM_FINGERPRINT
    config = load_config()
    status = telegram_settings(config)
    if status.get("mode") != "legacy":
        if TELEGRAM_STOP:
            TELEGRAM_STOP.set()
        TELEGRAM_THREAD = None
        TELEGRAM_STOP = None
        TELEGRAM_FINGERPRINT = None
        return start_hermes_gateway(config)
    fingerprint = (config.telegram_bot_token, status["chat_id"], status["enabled"], status["language"])
    if not (status["enabled"] and status["bot_configured"] and status["chat_id"]):
        if TELEGRAM_STOP:
            TELEGRAM_STOP.set()
        TELEGRAM_FINGERPRINT = None
        return False
    if TELEGRAM_THREAD and TELEGRAM_THREAD.is_alive() and not (TELEGRAM_STOP and TELEGRAM_STOP.is_set()) and TELEGRAM_FINGERPRINT == fingerprint:
        return True
    if TELEGRAM_STOP:
        TELEGRAM_STOP.set()
    TELEGRAM_STOP = threading.Event()
    from telegram_agent import run as run_telegram_listener
    TELEGRAM_THREAD = threading.Thread(target=run_telegram_listener, args=(TELEGRAM_STOP,), name="telegram-agent", daemon=True)
    TELEGRAM_THREAD.start()
    TELEGRAM_FINGERPRINT = fingerprint
    return {"started": True, "mode": "legacy"}


def detect_telegram_chats():
    config = load_config()
    if not config.telegram_bot_token:
        raise ValueError("Primero guarda la clave que te entregó @BotFather.")
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
    gateway = ensure_telegram_listener()
    log_action("telegram_gateway_check", {"chat_id_set": True, "mode": status.get("mode")}, "completed")
    return {"ready": bool(gateway.get("started") if isinstance(gateway, dict) else gateway), "gateway": gateway if isinstance(gateway, dict) else {}}


def activate_license_now(payload=None):
    payload = payload or {}
    env_updates = {}
    license_key = str(payload.get("license_key") or "").strip()
    buyer_email = str(payload.get("license_buyer_email") or payload.get("buyer_email") or "").strip().lower()
    if license_key:
        env_updates["LICENSE_KEY"] = license_key.upper()
    if buyer_email:
        env_updates["LICENSE_BUYER_EMAIL"] = buyer_email
    if env_updates:
        update_env_values(env_updates)
    config = load_config()
    status = activate_license(config, transfer_device=bool(payload.get("transfer_device")))
    if status.get("valid"):
        mark_license_install_state(config, "local_activated")
        mark_license_install_state(config, "onboarding_opened")
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
    return {
        "url": "https://business.facebook.com/settings/system-users",
        "instructions": {
            "es": "Abre Meta Business, crea un Usuario del sistema y genera una clave estable para tu propia cuenta publicitaria.",
            "en": "Open Meta Business, create a System User, and generate a stable key for your own ad account.",
        },
    }


def social_save_facebook_token(payload):
    token = str(payload.get("token") or "").strip()
    if len(token) < 20:
        raise ValueError("Token is too short")
    token_kind = str(payload.get("token_kind") or "unknown").strip().lower()
    if token_kind not in {"stable", "quick"}:
        token_kind = "unknown"
    env_updates = {
        "META_ACCESS_TOKEN": token,
        "META_ACCESS_TOKEN_KIND": token_kind,
        "META_ACCESS_TOKEN_SAVED_AT": now_iso(),
    }
    update_env_values(env_updates)
    result = social_command(["auth", "login", "--token", token], timeout=30)
    redacted = dict(result)
    redacted["output"] = re.sub(re.escape(token), "[token hidden]", redacted.get("output", ""))
    redacted["saved"] = True
    redacted["cli_ready"] = bool(result.get("ok"))
    redacted["token_kind"] = token_kind
    return redacted


def graph_get(path, params=None, page_token=""):
    config = load_config()
    token = page_token or config.meta_access_token
    if not token:
        return {"ok": False, "error": "missing_token", "data": None}
    version = config.meta_graph_api_version or "v24.0"
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


def clamp_int(value, default=10, minimum=1, maximum=25):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def normalize_targeting_item(item, kind):
    if not isinstance(item, dict):
        return {}
    if kind == "location":
        key = str(item.get("key") or item.get("id") or "").strip()
        name = str(item.get("name") or item.get("canonical_name") or key).strip()
        location_type = str(item.get("type") or item.get("location_type") or "").strip().lower()
        country_code = str(item.get("country_code") or item.get("country") or "").strip().upper()
        if not location_type and len(key) == 2 and key.isalpha():
            location_type = "country"
            country_code = key.upper()
        label_bits = [name]
        if country_code and country_code not in name.upper():
            label_bits.append(country_code)
        return {
            "kind": "location",
            "id": key,
            "key": key,
            "name": name,
            "label": " · ".join([part for part in label_bits if part]),
            "type": location_type or "location",
            "country_code": country_code,
        }
    interest_id = str(item.get("id") or item.get("key") or "").strip()
    name = str(item.get("name") or interest_id).strip()
    path = item.get("path") if isinstance(item.get("path"), list) else []
    audience_size = item.get("audience_size") or item.get("audience_size_lower_bound") or item.get("audience_size_upper_bound") or ""
    return {
        "kind": "interest",
        "id": interest_id,
        "name": name,
        "label": name,
        "path": path[:5],
        "audience_size": audience_size,
    }


def meta_targeting_search(payload):
    kind = str(payload.get("kind") or payload.get("type") or "interest").strip().lower()
    if kind in {"interests", "adinterest"}:
        kind = "interest"
    if kind in {"locations", "geo", "adgeolocation"}:
        kind = "location"
    if kind not in {"interest", "location"}:
        raise ValueError("Tipo de segmentación no soportado.")
    query = str(payload.get("q") or payload.get("query") or "").strip()
    if len(query) < 2:
        raise ValueError("Escribe al menos 2 letras para buscar en Meta.")
    limit = clamp_int(payload.get("limit"), default=8, minimum=1, maximum=25)
    params = {"type": "adinterest" if kind == "interest" else "adgeolocation", "q": query, "limit": limit}
    if kind == "location":
        params["location_types"] = json.dumps(["country", "region", "city"])
        country_code = str(payload.get("country_code") or "").strip().upper()
        if country_code:
            params["country_code"] = country_code
    result = graph_get("search", params)
    if not result.get("ok"):
        reason = result.get("error")
        raw_message = graph_error_message(result)
        if reason == "missing_token":
            message = "Primero conecta Meta para buscar opciones reales de público."
        elif any(token_hint in raw_message.lower() for token_hint in ["expired", "oauth", "access token", "validating access token"]):
            message = "Tu conexión con Meta venció. Vuelve al paso de conexión, pega una clave nueva y luego busca el público otra vez."
        else:
            message = "No pude consultar opciones de Meta todavía. Revisa internet, permisos de tu clave o intenta con otra palabra."
        return {"ok": False, "kind": kind, "query": query, "items": [], "message": message}
    rows = ((result.get("data") or {}).get("data") or [])[:limit]
    items = [normalize_targeting_item(row, kind) for row in rows]
    items = [item for item in items if item.get("id") or item.get("name")]
    return {"ok": True, "kind": kind, "query": query, "items": items}


def parse_targeting_items(value, kind):
    if not value:
        return []
    if isinstance(value, str):
        try:
            raw = json.loads(value)
        except json.JSONDecodeError:
            return []
    else:
        raw = value
    if not isinstance(raw, list):
        return []
    items = []
    seen = set()
    for entry in raw[:25]:
        item = normalize_targeting_item(entry, kind)
        key = item.get("id") or item.get("name")
        if not key or key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items


def targeting_location_values(selected, fallback):
    values = []
    for item in selected:
        if item.get("type") == "country" and item.get("key"):
            values.append(str(item["key"]).upper())
        elif item.get("country_code"):
            values.append(str(item["country_code"]).upper())
        elif item.get("name"):
            values.append(str(item["name"]))
    return values or fallback


def targeting_summary(audience):
    meta = audience.get("meta_targeting") or {}
    locations = [item.get("label") or item.get("name") or item.get("key") for item in meta.get("locations") or []]
    interests = [item.get("name") for item in meta.get("interests") or []]
    return {
        "locations": locations or audience.get("locations", []),
        "interests": interests or audience.get("interests", []),
        "source": "meta_search" if (locations or interests) else "manual_or_broad",
    }


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


def fetch_real_metrics(account_id="", persist_snapshot=True):
    config = load_config()
    account_id = str(account_id or config.ad_account_id or "").strip()
    if account_id and not account_id.startswith("act_"):
        account_id = f"act_{account_id}"
    if not account_id:
        return {"ok": False, "reason": "missing_account", "message": "Missing Meta ad account."}
    if not config.meta_access_token:
        return {"ok": False, "reason": "missing_token", "message": "Missing Meta access token."}
    snapshot = collect_meta_snapshot(
        account_id,
        config.meta_access_token,
        config.meta_graph_api_version or "v24.0",
        date_preset="last_30d",
    )
    campaigns = aggregate_meta_campaigns(snapshot)
    if not campaigns and snapshot.get("data_quality", {}).get("unavailable"):
        first_error = snapshot["data_quality"]["unavailable"][0].get("reason") or {}
        return {"ok": False, "reason": "graph_error", "message": str(first_error.get("message") or "Meta Graph request failed"), "raw": first_error}
    account = managed_account_context(account_id)
    for campaign in campaigns:
        campaign["account_id"] = account_id
        campaign["ad_account_id"] = account_id
        campaign["account_name"] = account.get("name") or account_id
        if account.get("business_id"):
            campaign["business_manager_id"] = account.get("business_id")
            campaign["business_manager_name"] = account.get("business_name", "")
    metrics = {
        "timestamp": now_iso(),
        "source": "meta_graph",
        "source_label": "Meta Ads real data",
        "account_id": account_id,
        "date_preset": "last_30d",
        "campaigns": campaigns,
        "summary": {},
        "data_quality": snapshot.get("data_quality"),
    }
    if persist_snapshot:
        save_meta_snapshot(snapshot)
    return {"ok": True, "metrics": metrics, "rows": len(campaigns), "account_id": account_id, "data_quality": snapshot.get("data_quality")}


def refresh_managed_real_metrics(reason="manual"):
    accounts = managed_metric_accounts()
    if len(accounts) <= 1:
        return refresh_real_metrics(accounts[0]["id"] if accounts else "", reason=reason)
    campaigns = []
    account_results = []
    errors = []
    for account in accounts:
        account_id = account.get("id")
        result = fetch_real_metrics(account_id, persist_snapshot=False)
        if result.get("ok"):
            rows = result.get("rows", 0)
            account_results.append({"id": account_id, "name": account.get("name") or account_id, "rows": rows})
            campaigns.extend(result.get("metrics", {}).get("campaigns", []))
        else:
            errors.append({"id": account_id, "name": account.get("name") or account_id, "reason": result.get("reason"), "message": result.get("message")})
    if campaigns or account_results:
        managed = normalize_managed_accounts_state()
        metrics = {
            "timestamp": now_iso(),
            "source": "meta_graph",
            "source_label": "Meta Ads real data · multiple accounts",
            "account_id": managed.get("active_ad_account_id") or (accounts[0].get("id") if accounts else ""),
            "date_preset": "last_30d",
            "business_manager": managed.get("business_manager", {}),
            "accounts": account_results,
            "campaigns": campaigns,
            "summary": {},
            "data_quality": {"complete": not errors, "unavailable": errors, "source": "meta_graph_read_only_multi_account"},
        }
        save_metrics(metrics)
        status = "completed" if not errors else "partial"
        log_action("live_insights_pull", {"account_ids": [item.get("id") for item in accounts], "rows": len(campaigns), "errors": len(errors), "reason": reason}, status)
        return {"ok": True, "saved": True, "source": "meta_graph", "rows": len(campaigns), "accounts": account_results, "errors": errors, "account_id": metrics["account_id"]}
    message = errors[0]["message"] if errors else "Missing Meta ad account."
    log_action("live_insights_pull", {"account_ids": [item.get("id") for item in accounts], "reason": reason, "errors": errors}, "blocked")
    return {"ok": False, "saved": False, "reason": errors[0]["reason"] if errors else "missing_account", "message": message, "errors": errors}


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


def read_meta_page_profile(page_id):
    page_id = str(page_id or "").strip()
    if not page_id:
        return {}
    field_sets = [
        "id,name,category,link,website,about,description,phone,emails,instagram_business_account{id,username,name},connected_instagram_account{id,username,name}",
        "id,name,category,link,website,about,description,instagram_business_account{id,username,name},connected_instagram_account{id,username,name}",
        "id,name,category,link,website,instagram_business_account{id,username,name},connected_instagram_account{id,username,name}",
        "id,name,category,link,website",
    ]
    last_error = ""
    for fields in field_sets:
        result = graph_get(f"/{page_id}", {"fields": fields})
        if result.get("ok") and isinstance(result.get("data"), dict):
            data = result["data"]
            page = normalize_page_asset(data) or {"id": page_id}
            for key in ["about", "description", "phone"]:
                if data.get(key):
                    page[key] = str(data.get(key) or "")[:800]
            emails = data.get("emails")
            if isinstance(emails, list):
                page["emails"] = [str(item or "")[:120] for item in emails if item][:3]
            return page
        last_error = str(result.get("error") or "")[:300]
    return {"id": page_id, "graph_error": last_error}


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
        save_setup_config({**{key: value for key, value in suggested.items() if key in {"page_id", "instagram_actor_id", "landing_url"} and value}, "_skip_meta_profile_sync": True})
        sync_business_profile_from_meta_assets(first_page, suggested, urls)

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


def sync_business_profile_from_meta_assets(page, suggested, urls=None):
    profile = read_json(BUSINESS_PROFILE_FILE, {})
    if not isinstance(profile, dict):
        profile = {}
    links = []
    for existing in profile.get("social_links") or []:
        if existing:
            links.append(str(existing))
    page = page or {}
    page_id = str((suggested or {}).get("page_id") or page.get("id") or "").strip()
    if page_id:
        graph_page = read_meta_page_profile(page_id)
        if graph_page and not graph_page.get("graph_error"):
            page = {**page, **graph_page}
        elif graph_page.get("graph_error"):
            page = {**page, "graph_error": graph_page.get("graph_error")}
    if page.get("link"):
        links.append(str(page.get("link")))
    instagram = page.get("instagram") if isinstance(page.get("instagram"), dict) else {}
    if instagram.get("username"):
        links.append(f"https://instagram.com/{str(instagram.get('username')).strip().lstrip('@')}")
    clean_links = []
    for link in links:
        value = str(link or "").strip()
        if value and value not in clean_links:
            clean_links.append(value[:300])
    if clean_links:
        profile["social_links"] = clean_links[:8]
    landing = str((suggested or {}).get("landing_url") or "").strip()
    if not landing and urls:
        landing = str((urls or [""])[0] or "").strip()
    if landing:
        profile["website_url"] = landing[:300]
        profile["website_skipped"] = False
    profile["meta_assets"] = {
        "page_id": page_id,
        "page_name": str((suggested or {}).get("page_name") or page.get("name") or "").strip(),
        "instagram_actor_id": str((suggested or {}).get("instagram_actor_id") or "").strip(),
        "instagram_username": str((suggested or {}).get("instagram_username") or "").strip(),
    }
    meta_page_profile = {
        "id": page_id,
        "name": str(page.get("name") or (suggested or {}).get("page_name") or "").strip(),
        "category": str(page.get("category") or "").strip(),
        "link": str(page.get("link") or "").strip(),
        "website": str(page.get("website") or landing or "").strip(),
        "about": str(page.get("about") or "").strip(),
        "description": str(page.get("description") or "").strip(),
        "phone_set": bool(page.get("phone")),
        "email_count": len(page.get("emails") or []) if isinstance(page.get("emails"), list) else 0,
        "instagram": instagram,
        "graph_error": str(page.get("graph_error") or "").strip(),
    }
    profile["meta_page_profile"] = {key: value for key, value in meta_page_profile.items() if value not in ("", [], {}, None)}
    graph_context = " ".join(str(meta_page_profile.get(key) or "") for key in ["name", "category", "about", "description"]).strip()
    if graph_context:
        profile["meta_page_context"] = graph_context[:1200]
        profile.setdefault("positioning", graph_context[:900])
        if not profile.get("business_type") and meta_page_profile.get("category"):
            profile["business_type"] = str(meta_page_profile.get("category"))[:220]
        if not profile.get("main_offer") and (meta_page_profile.get("about") or meta_page_profile.get("description")):
            profile["main_offer"] = str(meta_page_profile.get("about") or meta_page_profile.get("description"))[:220]
    profile.setdefault("source", "meta_asset_discovery")
    profile["updated_at"] = now_iso()
    write_json(BUSINESS_PROFILE_FILE, profile)
    write_onboarding_questions_memory(profile, "pending")
    return profile


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
        account = managed_account_from(row)
        if not account:
            continue
        accounts.append(account)
    return accounts


def merge_account_metadata(accounts, richer_accounts):
    richer_by_id = {account.get("id"): account for account in richer_accounts or [] if account.get("id")}
    merged = []
    for account in accounts or []:
        richer = richer_by_id.get(account.get("id"), {})
        merged.append({
            **account,
            **{key: value for key, value in richer.items() if value and not account.get(key)}
        })
    return merged


def normalize_graph_account_rows(rows):
    accounts = normalize_social_accounts(rows)
    deduped = []
    seen = set()
    for account in accounts:
        account_id = account.get("id")
        if not account_id or account_id in seen:
            continue
        seen.add(account_id)
        deduped.append(account)
    return deduped


def graph_business_account_rows(rows):
    found = []
    for business in rows or []:
        if not isinstance(business, dict):
            continue
        business_info = {"business_id": business.get("id", ""), "business_name": business.get("name", "")}
        for edge in ("owned_ad_accounts", "client_ad_accounts"):
            nested = business.get(edge) or {}
            if isinstance(nested, dict):
                for account in nested.get("data") or []:
                    if isinstance(account, dict):
                        found.append({**account, **business_info, "account_source": edge})
    return found


def graph_marketing_accounts():
    direct = graph_get(
        "/me/adaccounts",
        {"fields": "id,account_id,name,currency,account_status,business{id,name}", "limit": 100},
    )
    if direct.get("ok"):
        accounts = normalize_graph_account_rows((direct.get("data") or {}).get("data") or [])
        if accounts:
            return {"ok": True, "accounts": accounts, "source": "graph_api", "graph_checked": True}
    businesses = graph_get(
        "/me/businesses",
        {
            "fields": "id,name,owned_ad_accounts{id,account_id,name,currency,account_status},client_ad_accounts{id,account_id,name,currency,account_status}",
            "limit": 50,
        },
    )
    if businesses.get("ok"):
        accounts = normalize_graph_account_rows(graph_business_account_rows((businesses.get("data") or {}).get("data") or []))
        if accounts:
            return {"ok": True, "accounts": accounts, "source": "graph_businesses", "graph_checked": True}
    errors = []
    if not direct.get("ok"):
        errors.append(graph_error_message(direct))
    if not businesses.get("ok"):
        errors.append(graph_error_message(businesses))
    return {
        "ok": direct.get("ok") or businesses.get("ok"),
        "accounts": [],
        "source": "graph_api",
        "graph_checked": True,
        "graph_empty": direct.get("ok") or businesses.get("ok"),
        "graph_error": " | ".join([item for item in errors if item])[:900],
    }


def social_accounts_friendly_message(cli_result, graph_result):
    raw = " ".join([
        str(cli_result.get("output") or ""),
        str(graph_result.get("graph_error") or ""),
    ])
    raw_lower = raw.lower()
    if any(token in raw_lower for token in ["expired", "oauthexception", "code: 190", "validating access token"]):
        return "Tu clave de Meta venció o Meta la rechazó. Pega una clave nueva y vuelve a buscar tus cuentas."
    if any(token in raw_lower for token in ["permission", "permissions", "permis", "ads_read", "ads_management"]):
        return "La clave está guardada, pero Meta no permitió leer cuentas publicitarias. Revisa que la clave tenga permisos de anuncios y que tu usuario tenga acceso a esa cuenta."
    if graph_result.get("graph_empty"):
        return "La clave respondió, pero Meta devolvió 0 cuentas publicitarias. Revisa que estés usando el usuario correcto y que ese usuario tenga acceso a la cuenta de anuncios en Meta Business."
    return "No pude traer cuentas todavía. La clave quedó guardada; revisa permisos de anuncios o intenta crear una clave nueva."


def social_marketing_accounts():
    result = social_command(["marketing", "accounts", "--json"], timeout=30)
    output = result.get("output", "")
    output_lower = output.lower()
    token_expired = "expired" in output_lower or "oauth" in output_lower or "code: 190" in output_lower or "auth login" in output_lower
    payload = extract_json_payload(output)
    accounts = normalize_social_accounts(payload)
    cli_accounts_found = bool(accounts)
    graph_result = graph_marketing_accounts()
    graph_accounts = graph_result.get("accounts") or []
    if accounts and graph_accounts:
        accounts = merge_account_metadata(accounts, graph_accounts)
    elif not accounts and graph_accounts:
        accounts = graph_accounts
    accounts = annotate_accounts_with_management(accounts)
    managed = managed_ad_accounts_payload()
    friendly_message = social_accounts_friendly_message(result, graph_result) if not accounts else ""
    graph_error_lower = str(graph_result.get("graph_error") or "").lower()
    graph_expired = "expired" in graph_error_lower or "oauthexception" in graph_error_lower or "code: 190" in graph_error_lower or "validating access token" in graph_error_lower
    return {
        **result,
        "accounts": accounts,
        "managed_ad_accounts": managed,
        "business_manager": managed.get("business_manager", {}),
        "max_managed_accounts": MAX_MANAGED_META_AD_ACCOUNTS,
        "ok": bool(accounts) or bool(result.get("ok")) or bool(graph_result.get("ok")),
        "source": "social_cli" if cli_accounts_found else ("graph_api" if graph_accounts else "social_cli"),
        "graph_checked": bool(graph_result.get("graph_checked")),
        "needs_login": not accounts and ((not result.get("ok") and token_expired) or graph_expired),
        "token_expired": token_expired or graph_expired,
        "friendly_reason": "token_expired" if token_expired or graph_expired else ("empty_accounts" if not accounts else ""),
        "message": friendly_message,
    }


def discover_account_metadata(account_id):
    account_id = clean_ad_account_id(account_id)
    if not account_id:
        return {}
    try:
        result = social_command(["marketing", "accounts", "--json"], timeout=20)
        cli_accounts = normalize_social_accounts(extract_json_payload(result.get("output", "")))
    except Exception:
        cli_accounts = []
    try:
        graph_accounts = graph_marketing_accounts().get("accounts") or []
    except Exception:
        graph_accounts = []
    accounts = merge_account_metadata(cli_accounts, graph_accounts) if cli_accounts else graph_accounts
    return next((account for account in accounts if account.get("id") == account_id), {"id": account_id})


def social_set_default_account(payload):
    account_id = str(payload.get("ad_account_id") or "").strip()
    if not account_id:
        raise ValueError("Missing ad account")
    account_id = clean_ad_account_id(account_id)
    account = {
        **discover_account_metadata(account_id),
        **{key: value for key, value in {
            "id": account_id,
            "name": payload.get("name"),
            "currency": payload.get("currency"),
            "status": payload.get("status"),
            "business_id": payload.get("business_id") or payload.get("business_manager_id"),
            "business_name": payload.get("business_name") or payload.get("business_manager_name"),
        }.items() if value}
    }
    business = business_manager_info_from(account)
    replace_payload = {
        "ad_account_id": account_id,
        "business_manager_id": business["id"],
        "business_manager_name": business["name"],
        "account_name": account.get("name", ""),
        "account_currency": account.get("currency", ""),
        "account_status": account.get("status", ""),
        "confirm_replace_business": payload.get("confirm_replace_business"),
    }
    replaced = enforce_individual_business_change(replace_payload)
    saved = save_setup_config({**replace_payload, "_skip_business_enforcement": True})
    saved["business_replaced"] = replaced
    saved["managed_ad_accounts"] = managed_ad_accounts_payload()
    result = social_command(["marketing", "set-default-account", account_id], timeout=20)
    if not result.get("ok"):
        return {**result, "ok": True, "local_saved": True, "social_cli_default_set": False, "warning": "social_cli_default_failed_but_account_saved_locally", "saved": saved, "ad_account_id": account_id, "managed_ad_accounts": saved["managed_ad_accounts"]}
    return {**result, "local_saved": True, "social_cli_default_set": True, "saved": saved, "ad_account_id": account_id, "managed_ad_accounts": saved["managed_ad_accounts"]}


def set_dashboard_password(payload):
    password = str(payload.get("password") or "").strip()
    confirm = str(payload.get("confirm_password") or "").strip()
    if len(password) < 8:
        raise ValueError("Dashboard password must have at least 8 characters")
    if confirm and confirm != password:
        raise ValueError("Dashboard password confirmation does not match")
    password_hash = hash_dashboard_password(password)
    update_env_values({"DASHBOARD_PASSWORD_HASH": password_hash, "DASHBOARD_PASSWORD": "", "DASHBOARD_TOKEN": ""})
    save_dashboard_identity_backup(password_hash)
    session = create_dashboard_session(remember=bool(payload.get("remember_device", True)))
    log_action("dashboard_password_set", {"status": "configured"}, "completed")
    return {"configured": True, **session}


def normalize_agent_chat_provider(value):
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "hermes": "openai_codex",
        "chatgpt": "openai_codex",
        "chatgpt_subscription": "openai_codex",
        "codex": "openai_codex",
        "openai_codex": "openai_codex",
        "openai": "openai_api",
        "openai_api": "openai_api",
        "openai_compatible": "custom_api",
        "openai_compat": "custom_api",
        "compatible": "custom_api",
        "custom": "custom_api",
        "custom_api": "custom_api",
        "minimax": "minimax",
        "minimax_m3": "minimax",
    }
    return aliases.get(raw, "")


def validate_agent_chat_base_url(value):
    url = str(value or "").strip().rstrip("/")
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https" and parsed.netloc:
        return url
    if parsed.scheme == "http" and is_local_host(parsed.hostname or ""):
        return url
    raise ValueError("La URL del modelo debe usar https://, excepto modelos locales en http://127.0.0.1 o http://localhost.")


def running_inside_container():
    return Path("/.dockerenv").exists() or bool(os.environ.get("container") or os.environ.get("KUBERNETES_SERVICE_HOST"))


def hermes_shell_command(config):
    cli = str(getattr(config, "hermes_cli", "") or "hermes").strip() or "hermes"
    home = str(getattr(config, "hermes_home", "") or "").strip()
    prefix = f"HERMES_HOME={shlex.quote(home)} " if home else ""
    return f"{prefix}{shlex.quote(cli)} model"


def hermes_browserless_command(config):
    cli = str(getattr(config, "hermes_cli", "") or "hermes").strip() or "hermes"
    return [cli, "model", "--no-browser"]


def hermes_browserless_shell_command(config):
    return " ".join(shlex.quote(part) for part in hermes_browserless_command(config))


def clean_terminal_text(value):
    text = str(value or "")
    text = re.sub(r"\x1b\][^\a]*(?:\a|\x1b\\)", "", text)
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def extract_urls_from_text(value):
    urls = []
    for match in re.findall(r"https?://[^\s<>'\")]+", str(value or "")):
        url = match.rstrip(".,;:")
        if url not in urls:
            urls.append(url)
        if len(urls) >= 4:
            break
    return urls


def extract_login_codes_from_text(value):
    cleaned = clean_terminal_text(value)
    if not cleaned:
        return []
    codes = []
    lines = cleaned.splitlines()
    hint_re = re.compile(r"\b(code|codigo|código|verification|verify|device|one-time|otp)\b", re.I)
    token_re = re.compile(r"\b[A-Z0-9]{4}(?:[- ][A-Z0-9]{2,8}){1,5}\b|\b[A-Z0-9]{6,24}\b")
    label_re = re.compile(
        r"(?:verification|device|one[- ]time|login|openai|codex|auth)?\s*(?:code|codigo|código)\s*[:=\-]?\s*([A-Z0-9][A-Z0-9\- ]{4,40}[A-Z0-9])\s*$",
        re.I,
    )
    blocked_parts = {
        "OPENAI",
        "HERMES",
        "CODEX",
        "MODEL",
        "DEVICE",
        "CODE",
        "CODIGO",
        "VERIFICATION",
        "VERIFY",
        "TERMINAL",
        "DISPLAYED",
        "BROWSER",
        "OPEN",
        "THIS",
        "URL",
        "CONTINUE",
        "AUTH",
        "ASK",
        "FOR",
        "LOGIN",
        "PROVIDER",
        "DEFAULT",
    }

    def add_code(raw, contextual=False):
        normalized = re.sub(r"[^A-Z0-9]+", "-", str(raw or "").upper()).strip("-")
        if not normalized:
            return
        parts = [part for part in normalized.split("-") if part]
        compact = "".join(parts)
        if not 6 <= len(compact) <= 24:
            return
        if compact in blocked_parts or any(part in blocked_parts for part in parts):
            return
        looks_like_code = contextual or "-" in normalized or any(char.isdigit() for char in compact)
        if looks_like_code and normalized not in codes:
            codes.append(normalized)

    def standalone_code_line(line):
        candidate = re.sub(r"https?://[^\s<>'\")]+", " ", str(line or ""))
        candidate = candidate.strip().strip("`'\"|>.,;:()[]{}")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\- ]{4,40}[A-Za-z0-9]", candidate):
            return ""
        compact = re.sub(r"[^A-Za-z0-9]+", "", candidate)
        if not 6 <= len(compact) <= 24:
            return ""
        tokens = [token for token in re.split(r"[-\s]+", candidate.strip()) if token]
        has_separator = len(tokens) > 1
        if has_separator and any(len(token) > 8 for token in tokens):
            return ""
        has_digit = any(char.isdigit() for char in compact)
        has_upper_signal = any(char.isupper() for char in candidate) and candidate.upper() == candidate
        if not (has_digit or has_upper_signal or has_separator):
            return ""
        return candidate

    explicit_code_prompt_re = re.compile(
        r"\b(?:enter|copy|use|paste|ingresa|copia|usa|pega)\b.{0,40}\b(?:code|codigo|código)\b|\b(?:verification|device|login|auth|openai|codex)\s+(?:code|codigo|código)\b",
        re.I,
    )

    def prioritized_codes():
        found = []

        def remember(raw):
            before = len(codes)
            add_code(raw, contextual=True)
            if len(codes) > before:
                found.append(codes.pop())

        for index in range(len(lines) - 1, -1, -1):
            line_without_urls = re.sub(r"https?://[^\s<>'\")]+", " ", lines[index])
            if not explicit_code_prompt_re.search(line_without_urls):
                continue
            match = label_re.search(line_without_urls)
            if match:
                remember(match.group(1))
            tail = line_without_urls.split(":", 1)[1] if ":" in line_without_urls else ""
            tail_candidate = standalone_code_line(tail)
            if tail_candidate:
                remember(tail_candidate)
            for candidate_line in lines[index + 1 : min(len(lines), index + 7)]:
                candidate = standalone_code_line(candidate_line)
                if candidate:
                    remember(candidate)
                    break
            if len(found) >= 2:
                break
        unique = []
        for code in found:
            if code not in unique:
                unique.append(code)
        return unique[:2]

    high_confidence = prioritized_codes()
    if high_confidence:
        return high_confidence

    for line in lines:
        line_without_urls = re.sub(r"https?://[^\s<>'\")]+", " ", line)
        match = label_re.search(line_without_urls)
        if match:
            add_code(match.group(1), contextual=True)
        if len(codes) >= 2:
            return codes[:2]
    for index, line in enumerate(lines):
        line_without_urls = re.sub(r"https?://[^\s<>'\")]+", " ", line)
        if not hint_re.search(line_without_urls):
            continue
        for candidate_line in lines[index + 1 : min(len(lines), index + 10)]:
            candidate = standalone_code_line(candidate_line)
            if candidate:
                add_code(candidate, contextual=True)
                break
        segment_lines = lines[max(0, index - 1) : min(len(lines), index + 8)]
        segment_for_menu_check = "\n".join(segment_lines).lower()
        if "select provider" in segment_for_menu_check or "(○)" in segment_for_menu_check or "(●)" in segment_for_menu_check:
            continue
        segment = " ".join(segment_lines)
        segment = re.sub(r"https?://[^\s<>'\")]+", " ", segment)
        for match in token_re.findall(segment.upper()):
            add_code(match)
        if len(codes) >= 2:
            break
    return codes[:2]


def hermes_provider_prompt_visible(output):
    lower = clean_terminal_text(output).lower()
    provider_prompt = "select provider" in lower or "select openai provider" in lower
    return provider_prompt and (
        "select by number" in lower
        or "enter to confirm" in lower
        or "enter/space select" in lower
        or "navigate" in lower
        or "choice [default" in lower
        or "choice:" in lower
    )


def hermes_model_prompt_visible(output):
    lower = clean_terminal_text(output).lower()
    return (
        ("select model" in lower or "choose model" in lower or "default model" in lower)
        and ("select by number" in lower or "enter to confirm" in lower or "default" in lower)
    )


def hermes_openai_subprovider_prompt_visible(output):
    lower = clean_terminal_text(output).lower()
    return hermes_provider_prompt_visible(output) and "openai codex" in lower and "openai api" in lower


def hermes_choice_number_for_label(output, labels):
    wanted = [str(label or "").lower() for label in labels if str(label or "").strip()]
    for line in clean_terminal_text(output).splitlines():
        lower = line.lower()
        if not any(label in lower for label in wanted):
            continue
        match = re.match(r"^\s*(?:[\[\(]?(\d{1,2})[\]\).:-]?|\b(\d{1,2})\b)\s+", line)
        if match:
            return next((part for part in match.groups() if part), "")
        before_label = lower.split(next((label for label in wanted if label in lower), ""), 1)[0]
        reverse_match = re.search(r"(\d{1,2})\D*$", before_label)
        if reverse_match:
            return reverse_match.group(1)
    return ""


def hermes_arrow_menu_payload_for_label(output, labels):
    cleaned = clean_terminal_text(output)
    lower = cleaned.lower()
    provider_prompt = "select provider" in lower or "select openai provider" in lower
    if not provider_prompt or not ("navigate" in lower or "enter/space select" in lower):
        return ""
    wanted = [str(label or "").lower() for label in labels if str(label or "").strip()]
    if not wanted:
        return ""
    menu_lines = []
    for line in cleaned.splitlines():
        menu_text = line.strip()
        menu_lower = menu_text.lower()
        if not menu_text:
            continue
        if "(●)" in menu_text or "(○)" in menu_text or menu_text.startswith("→"):
            menu_lines.append((menu_text, menu_lower))
    if not menu_lines:
        return ""
    current_index = next((index for index, (line, _lower) in enumerate(menu_lines) if "→" in line), 0)
    target_index = next(
        (
            index
            for index, (_line, menu_lower) in enumerate(menu_lines)
            if any(label in menu_lower for label in wanted)
        ),
        -1,
    )
    if target_index < 0:
        return ""
    delta = target_index - current_index
    if delta > 0:
        return ("\x1b[B" * delta) + "\n"
    if delta < 0:
        return ("\x1b[A" * abs(delta)) + "\n"
    return "\n"


def hermes_model_choice(output, preferred_model=""):
    preferred = str(preferred_model or "").strip()
    if preferred and hermes_model_prompt_visible(output):
        parsed = hermes_choice_number_for_label(output, [preferred])
        if parsed:
            return parsed
    return ""


def hermes_codex_provider_choice(output):
    arrow_payload = hermes_arrow_menu_payload_for_label(output, ["openai ▸", "openai (codex cli", "openai"])
    if arrow_payload:
        return arrow_payload
    parsed = hermes_choice_number_for_label(output, ["openai ▸", "openai (codex cli", "openai"])
    if parsed:
        return f"{parsed}\n"
    parsed = hermes_choice_number_for_label(output, ["openai codex", "chatgpt/codex", "chatgpt codex"])
    if parsed:
        return f"{parsed}\n"
    if hermes_provider_prompt_visible(output):
        explicit_choice = str(os.environ.get("HERMES_CODEX_PROVIDER_CHOICE") or "").strip()
        if explicit_choice:
            return f"{explicit_choice}\n"
    return ""


def codex_device_auth_disabled(output):
    lower = clean_terminal_text(output).lower()
    return (
        "enable device code authorization" in lower
        or ("device code authorization" in lower and "chatgpt security settings" in lower)
        or ("codex login --device-auth" in lower and "security settings" in lower)
    )


def hermes_login_prompt_state(output, state=None):
    state = state or {}
    cleaned = clean_terminal_text(output)
    lower = cleaned.lower()
    urls = extract_urls_from_text(cleaned)
    login_codes = extract_login_codes_from_text(cleaned)
    auto_provider_sent = bool(state.get("auto_provider_sent"))
    auto_codex_subprovider_sent = bool(state.get("auto_codex_subprovider_sent"))
    auto_model_sent = bool(state.get("auto_model_sent"))
    manual_input = any(marker in lower for marker in ["invalid choice", "invalid selection", "try again", "not recognized"])
    if codex_device_auth_disabled(cleaned):
        return {
            "phase": "device_auth_settings",
            "needs_input": False,
            "title": "Activa el login por código",
            "detail": "ChatGPT pide activar el login por código para Codex. Abre ChatGPT, entra a Ajustes > Seguridad y activa Enable device code authorization for Codex. Luego vuelve aquí y toca Conectar ahora.",
            "auto_note": "Es una protección de ChatGPT para permitir login desde servidores o contenedores.",
            "login_code": "",
        }
    if urls and login_codes:
        return {
            "phase": "login_code",
            "needs_input": False,
            "title": "Copia el código de OpenAI",
            "detail": "OpenAI abrió una pantalla segura y te pedirá este código. Cópialo, vuelve a la pestaña de login y pégalo allí.",
            "auto_note": state.get("auto_note") or "",
            "login_code": login_codes[0],
        }
    if urls:
        return {
            "phase": "login_link",
            "needs_input": False,
            "title": "Termina el login",
            "detail": "Abre el enlace de ChatGPT/Codex que aparece aquí. Después vuelve a esta pantalla y revisaré la conexión.",
            "auto_note": state.get("auto_note") or "",
            "login_code": "",
        }
    if hermes_openai_subprovider_prompt_visible(cleaned):
        return {
            "phase": "codex_subprovider_selection",
            "needs_input": manual_input,
            "title": "Confirmando OpenAI Codex",
            "detail": "El agente pidió elegir entre OpenAI Codex y OpenAI API. Estoy confirmando OpenAI Codex automáticamente.",
            "auto_note": "OpenAI Codex confirmado." if auto_codex_subprovider_sent else "Confirmando OpenAI Codex automáticamente.",
            "login_code": "",
        }
    if hermes_provider_prompt_visible(cleaned):
        return {
            "phase": "provider_selection",
            "needs_input": manual_input,
            "title": "Eligiendo OpenAI Codex",
            "detail": "El agente pidió elegir proveedor. Estoy seleccionando OpenAI Codex automáticamente para que no tengas que leer la terminal.",
            "auto_note": "OpenAI Codex se selecciona automáticamente." if not auto_provider_sent else state.get("auto_note") or "OpenAI Codex seleccionado. Continúo con el siguiente paso.",
            "login_code": "",
        }
    if hermes_model_prompt_visible(cleaned):
        preferred_model = normalize_hermes_model(state.get("preferred_model"))
        chosen = bool(preferred_model and hermes_model_choice(cleaned, preferred_model))
        return {
            "phase": "model_selection",
            "needs_input": manual_input,
            "title": "Eligiendo modelo del agente",
            "detail": f"El agente pidió elegir modelo. Estoy usando {preferred_model}." if chosen else "El agente pidió elegir modelo. Estoy aceptando el recomendado para no detener la instalación.",
            "auto_note": f"Modelo {preferred_model} confirmado." if auto_model_sent and chosen else ("Modelo recomendado confirmado." if auto_model_sent else (f"Confirmando {preferred_model} automáticamente." if preferred_model else "Confirmando el modelo recomendado automáticamente.")),
            "login_code": "",
        }
    return {
        "phase": "waiting",
        "needs_input": manual_input,
        "title": "El agente está trabajando",
        "detail": "Estoy preparando la conexión. Si aparece un enlace de ChatGPT/Codex, ábrelo desde este navegador.",
        "auto_note": state.get("auto_note") or "",
        "login_code": login_codes[0] if login_codes else "",
    }


def maybe_auto_drive_hermes_browserless(session_id, master_fd):
    with HERMES_LOGIN_LOCK:
        if HERMES_LOGIN_STATE.get("id") != session_id:
            return False
        output = HERMES_LOGIN_STATE.get("output") or ""
        provider_sent = bool(HERMES_LOGIN_STATE.get("auto_provider_sent"))
        codex_subprovider_sent = bool(HERMES_LOGIN_STATE.get("auto_codex_subprovider_sent"))
        model_sent = bool(HERMES_LOGIN_STATE.get("auto_model_sent"))
        if provider_sent and not codex_subprovider_sent and hermes_openai_subprovider_prompt_visible(output):
            HERMES_LOGIN_STATE["auto_codex_subprovider_sent"] = True
            HERMES_LOGIN_STATE["phase"] = "codex_subprovider_selection"
            HERMES_LOGIN_STATE["auto_note"] = "Estoy confirmando OpenAI Codex automáticamente."
            payload = hermes_arrow_menu_payload_for_label(output, ["openai codex", "chatgpt/codex", "chatgpt codex"]) or "1\n"
        elif not provider_sent:
            provider_payload = hermes_codex_provider_choice(output)
            if provider_payload:
                HERMES_LOGIN_STATE["auto_provider_sent"] = True
                HERMES_LOGIN_STATE["phase"] = "provider_selection"
                HERMES_LOGIN_STATE["auto_note"] = "Estoy eligiendo OpenAI Codex automáticamente."
                payload = provider_payload
            else:
                payload = ""
        elif not model_sent and hermes_model_prompt_visible(output):
            preferred_model = normalize_hermes_model(HERMES_LOGIN_STATE.get("preferred_model"))
            model_choice = hermes_model_choice(output, preferred_model)
            HERMES_LOGIN_STATE["auto_model_sent"] = True
            HERMES_LOGIN_STATE["phase"] = "model_selection"
            HERMES_LOGIN_STATE["auto_note"] = f"Estoy eligiendo {preferred_model} automáticamente." if model_choice else "Estoy confirmando el modelo recomendado automáticamente."
            payload = f"{model_choice}\n" if model_choice else "\n"
        else:
            payload = ""
    if not payload:
        return False
    try:
        os.write(master_fd, payload.encode("utf-8", errors="replace"))
        return True
    except OSError:
        return False


def nudge_hermes_browserless_autodrive():
    with HERMES_LOGIN_LOCK:
        session_id = HERMES_LOGIN_STATE.get("id") or ""
        fd = HERMES_LOGIN_STATE.get("fd")
        proc = HERMES_LOGIN_STATE.get("proc")
        running = bool(session_id and proc and proc.poll() is None and fd is not None)
    if running:
        return maybe_auto_drive_hermes_browserless(session_id, fd)
    return False


def hermes_connect_response(status, title, detail, **extra):
    command = extra.pop("command", "hermes model")
    should_log = extra.pop("log", True)
    output = redact_error_text(clean_terminal_text(extra.pop("output", "")), limit=HERMES_LOGIN_OUTPUT_LIMIT)
    login_codes = extract_login_codes_from_text(output)
    payload = {
        "ok": status in {"terminal_opened", "completed", "needs_login", "needs_terminal", "browser_login_started", "browser_login_waiting", "browser_login_ready"},
        "status": status,
        "title": title,
        "detail": detail,
        "command": command,
        "urls": extract_urls_from_text(output),
        "login_codes": login_codes,
        "login_code": extra.pop("login_code", login_codes[0] if login_codes else ""),
        "output": output,
        **extra,
    }
    if should_log:
        log_status = "completed" if status in {"terminal_opened", "completed"} else "warn"
        log_action("agent_model_connect", {"status": status, "mode": payload.get("mode"), "urls_found": len(payload["urls"])}, log_status)
    return payload


def terminal_launcher_command(config):
    command = hermes_shell_command(config)
    root = shlex.quote(str(ROOT_DIR))
    return (
        f"cd {root}\n"
        "echo 'Conectando ChatGPT/Codex para Admira IA...'\n"
        "echo 'Si el agente pregunta por proveedor, elige OpenAI Codex / ChatGPT.'\n"
        "echo\n"
        f"{command}\n"
        "status=$?\n"
        "echo\n"
        "if [ $status -eq 0 ]; then\n"
        "  echo 'Listo. Vuelve al dashboard y toca Revisar conexion.'\n"
        "else\n"
        "  echo 'La conexión terminó con un aviso. Si ves un enlace o código, complétalo y vuelve al dashboard.'\n"
        "fi\n"
        "echo\n"
    )


def launch_hermes_terminal(config):
    if running_inside_container():
        return False
    command = terminal_launcher_command(config)
    try:
        if sys.platform == "darwin":
            command_dir = DATA_DIR / "runtime_commands"
            command_dir.mkdir(parents=True, exist_ok=True)
            script_path = command_dir / "connect-chatgpt-codex.command"
            script_path.write_text(
                "#!/bin/zsh\n"
                "clear\n"
                f"{command}"
                "echo 'Puedes cerrar esta ventana cuando termines.'\n"
                "read -k 1 '?Presiona cualquier tecla para cerrar...'\n",
                encoding="utf-8",
            )
            script_path.chmod(0o700)
            subprocess.Popen(["open", "-a", "Terminal", str(script_path)], cwd=str(ROOT_DIR))
            return True
        if os.name == "nt":
            ps_root = str(ROOT_DIR).replace("'", "''")
            ps_cli = str(getattr(config, "hermes_cli", "") or "hermes").replace("'", "''")
            ps_home = str(getattr(config, "hermes_home", "") or "").replace("'", "''")
            ps_home_prefix = f"$env:HERMES_HOME='{ps_home}'; " if ps_home else ""
            ps_command = (
                f"Set-Location -LiteralPath '{ps_root}'; "
                f"{ps_home_prefix}"
                "Write-Host 'Conectando ChatGPT/Codex para Admira IA...'; "
                "Write-Host 'Si el agente pregunta por proveedor, elige OpenAI Codex / ChatGPT.'; "
                f"& '{ps_cli}' model; "
                "Read-Host 'Presiona Enter para cerrar'"
            )
            subprocess.Popen(["cmd", "/c", "start", "powershell", "-NoExit", "-Command", ps_command], cwd=str(ROOT_DIR))
            return True
        if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
            shell_command = command + "read -n 1 -s -r -p 'Presiona una tecla para cerrar...'"
            launchers = [
                ("gnome-terminal", ["gnome-terminal", "--", "bash", "-lc", shell_command]),
                ("konsole", ["konsole", "-e", "bash", "-lc", shell_command]),
                ("xfce4-terminal", ["xfce4-terminal", "--command", f"bash -lc {shlex.quote(shell_command)}"]),
                ("xterm", ["xterm", "-e", "bash", "-lc", shell_command]),
            ]
            for binary, args in launchers:
                if shutil.which(binary):
                    subprocess.Popen(args, cwd=str(ROOT_DIR))
                    return True
    except Exception:
        return False
    return False


def normalize_connect_purpose(value):
    return "image" if str(value or "").strip().lower() in {"image", "images", "codex_image", "image_only", "dedicated_chatgpt"} else "agent"


def config_for_connect_purpose(purpose):
    config = load_config()
    return image_codex_config(config) if normalize_connect_purpose(purpose) == "image" else config


HERMES_CODEX_AUTH_FILES = {
    "auth.json",
    "auth.lock",
    "credentials.json",
    "credential.json",
    "token.json",
    "tokens.json",
    "session.json",
    "sessions.json",
    "openai-auth.json",
    "codex-auth.json",
}

HERMES_CODEX_AUTH_DIRS = {
    "auth",
    "oauth",
    "tokens",
    "credentials",
    "openai-auth",
    "codex-auth",
}

HERMES_CODEX_AUTH_RELATIVE_FILES = {
    ".codex/auth.json",
    ".codex/auth.lock",
    ".codex/credentials.json",
    "codex/auth.json",
    "codex/auth.lock",
    "openai/auth.json",
    "openai/tokens.json",
}


def safe_hermes_auth_home(path):
    home = Path(str(path or "")).expanduser()
    if not home.is_absolute():
        home = ROOT_DIR / home
    try:
        resolved = home.resolve()
    except OSError:
        resolved = home.absolute()
    allowed_roots = [
        (ROOT_DIR / "dashboard" / "data").resolve(),
        (ROOT_DIR / "runtime").resolve(),
    ]
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise ValueError("No puedo desconectar esa sesión porque la ruta de autenticación no pertenece a Admira IA.")
    return resolved


def stop_hermes_login_session(purpose="agent"):
    purpose = normalize_connect_purpose(purpose)
    with HERMES_LOGIN_LOCK:
        state_purpose = normalize_connect_purpose(HERMES_LOGIN_STATE.get("purpose"))
        proc = HERMES_LOGIN_STATE.get("proc")
        fd = HERMES_LOGIN_STATE.get("fd")
        running = bool(proc and proc.poll() is None)
        if state_purpose != purpose:
            return False
        HERMES_LOGIN_STATE.update({"proc": None, "fd": None, "status": "disconnected", "output": "", "updated_at": now_iso()})
    if running:
        try:
            proc.terminate()
        except Exception:
            pass
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    return running


def clear_hermes_codex_auth(home):
    auth_home = safe_hermes_auth_home(home)
    removed = []
    auth_home.mkdir(parents=True, exist_ok=True)
    for child in auth_home.iterdir():
        name = child.name
        target = None
        if child.is_file() and name in HERMES_CODEX_AUTH_FILES:
            target = child
        elif child.is_dir() and name in HERMES_CODEX_AUTH_DIRS:
            target = child
        if not target:
            continue
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            removed.append(str(target.relative_to(auth_home)))
        except OSError:
            continue
    for relative in HERMES_CODEX_AUTH_RELATIVE_FILES:
        target = auth_home / relative
        if not target.exists():
            continue
        try:
            target.unlink()
            removed.append(relative)
        except OSError:
            continue
    return {"home": str(auth_home), "removed": removed}


def disconnect_agent_model(payload=None):
    payload = payload or {}
    purpose = normalize_connect_purpose(payload.get("connection_purpose") or payload.get("purpose"))
    config = config_for_connect_purpose(purpose)
    stop_hermes_login_session(purpose)
    cleared = clear_hermes_codex_auth(getattr(config, "hermes_home", ""))
    env_updates = {}
    gateway = None
    if purpose == "agent":
        env_updates = {"HERMES_REQUIRE_CODEX_AUTH": "true"}
        update_env_values(env_updates)
        gateway = refresh_telegram_gateway_after_agent_model_change({"HERMES_MODEL": getattr(config, "hermes_model", "")})
    else:
        env_updates = {
            "CODEX_IMAGE_SOURCE": "dedicated_chatgpt",
            "CODEX_IMAGE_HERMES_HOME": str(default_codex_image_hermes_home()),
            "CODEX_IMAGE_HERMES_MODEL": normalize_hermes_model(getattr(config, "codex_image_hermes_model", "") or getattr(config, "hermes_model", "")),
        }
        update_env_values(env_updates)
    log_action("agent_model_disconnect", {"purpose": purpose, "removed": len(cleared.get("removed", []))}, "completed")
    label = "ChatGPT/Codex de imágenes" if purpose == "image" else "ChatGPT/Codex"
    return {
        "ok": True,
        "status": "disconnected",
        "connection_purpose": purpose,
        "title": f"{label} desconectado",
        "detail": "Puedes conectar otra cuenta cuando quieras. No borré memoria, campañas ni configuración del agente.",
        "removed": cleared.get("removed", []),
        "home": cleared.get("home", ""),
        "env_updated": sorted(env_updates.keys()),
        "gateway": gateway,
    }


def hermes_browserless_snapshot(config=None, purpose="agent"):
    config = config or load_config()
    purpose = normalize_connect_purpose(purpose)
    ready, auth_detail = hermes_codex_ready(config)
    if not ready:
        nudge_hermes_browserless_autodrive()
    with HERMES_LOGIN_LOCK:
        state = dict(HERMES_LOGIN_STATE)
        proc = state.get("proc")
        running = bool(proc and proc.poll() is None)
        output = state.get("output", "")
    if ready:
        gateway = refresh_telegram_gateway_after_agent_model_change(
            {"AGENT_BRAIN_PROVIDER": "openai_codex", "HERMES_MODEL": getattr(config, "hermes_model", "")}
        ) if purpose == "agent" else None
        return hermes_connect_response(
            "completed",
            "ChatGPT/Codex conectado",
            "El agente ya tiene lista la conexión con ChatGPT/Codex en esta instalación.",
            mode="browserless_ready",
            command=hermes_browserless_shell_command(config),
            output=output or auth_detail,
            running=False,
            job_id=state.get("id") or "",
            connection_purpose=purpose,
            gateway=gateway,
            log=False,
        )
    if running:
        prompt = hermes_login_prompt_state(output, state)
        status = "needs_login" if extract_urls_from_text(output) else "browser_login_waiting"
        return hermes_connect_response(
            status,
            prompt["title"],
            prompt["detail"],
            mode="browserless_running",
            command=hermes_browserless_shell_command(config),
            output=output,
            running=True,
            job_id=state.get("id") or "",
            connection_purpose=purpose,
            needs_input=prompt["needs_input"],
            phase=prompt["phase"],
            auto_note=prompt["auto_note"],
            log=False,
        )
    if output:
        prompt = hermes_login_prompt_state(output, state)
        if prompt["phase"] == "device_auth_settings":
            return hermes_connect_response(
                "needs_login",
                prompt["title"],
                prompt["detail"],
                mode="browserless_device_auth_disabled",
                command=hermes_browserless_shell_command(config),
                output=output or auth_detail,
                running=False,
                job_id=state.get("id") or "",
                connection_purpose=purpose,
                needs_input=False,
                phase=prompt["phase"],
                auto_note=prompt["auto_note"],
                log=False,
            )
        return hermes_connect_response(
            "needs_terminal",
            "El agente necesita una respuesta",
            "La sesión terminó antes de quedar conectada. Revisa el detalle, vuelve a tocar Conectar ahora o usa una API compatible.",
            mode="browserless_finished",
            command=hermes_browserless_shell_command(config),
            output=output or auth_detail,
            running=False,
            job_id=state.get("id") or "",
            connection_purpose=purpose,
            log=False,
        )
    return hermes_connect_response(
        "needs_terminal",
        "Falta conectar ChatGPT/Codex",
        "Toca Conectar ahora para iniciar el login en este servidor.",
        mode="browserless_idle",
        command=hermes_browserless_shell_command(config),
        output=auth_detail,
        running=False,
        job_id=state.get("id") or "",
        connection_purpose=purpose,
        log=False,
    )


def append_hermes_login_output(session_id, text):
    if not text:
        return
    with HERMES_LOGIN_LOCK:
        if HERMES_LOGIN_STATE.get("id") != session_id:
            return
        output = (HERMES_LOGIN_STATE.get("output") or "") + text
        HERMES_LOGIN_STATE["output"] = output[-HERMES_LOGIN_OUTPUT_LIMIT:]
        HERMES_LOGIN_STATE["updated_at"] = now_iso()


def finish_hermes_browserless_session(session_id, returncode):
    with HERMES_LOGIN_LOCK:
        if HERMES_LOGIN_STATE.get("id") != session_id:
            return
        purpose = HERMES_LOGIN_STATE.get("purpose") or "agent"
    config = config_for_connect_purpose(purpose)
    ready, auth_detail = hermes_codex_ready(config)
    with HERMES_LOGIN_LOCK:
        if HERMES_LOGIN_STATE.get("id") != session_id:
            return
        HERMES_LOGIN_STATE["status"] = "completed" if ready else "needs_terminal"
        HERMES_LOGIN_STATE["title"] = "ChatGPT/Codex conectado" if ready else "El agente necesita una respuesta"
        HERMES_LOGIN_STATE["detail"] = auth_detail
        HERMES_LOGIN_STATE["phase"] = "completed" if ready else "finished"
        HERMES_LOGIN_STATE["auto_note"] = ""
        HERMES_LOGIN_STATE["returncode"] = returncode
        HERMES_LOGIN_STATE["updated_at"] = now_iso()
        fd = HERMES_LOGIN_STATE.get("fd")
        HERMES_LOGIN_STATE["proc"] = None
        HERMES_LOGIN_STATE["fd"] = None
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass


def read_hermes_browserless_output(session_id, master_fd, proc):
    while True:
        try:
            chunk = os.read(master_fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        append_hermes_login_output(session_id, chunk.decode("utf-8", errors="replace"))
        maybe_auto_drive_hermes_browserless(session_id, master_fd)
    try:
        returncode = proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        returncode = proc.poll()
    finish_hermes_browserless_session(session_id, returncode)


def start_hermes_browserless_login(config, purpose="agent"):
    purpose = normalize_connect_purpose(purpose)
    cli_path = shutil.which(str(getattr(config, "hermes_cli", "") or "hermes").strip() or "hermes")
    if not cli_path:
        return hermes_connect_response(
            "not_installed",
            "Falta la base del agente",
            "Instala o actualiza Admira IA y vuelve a tocar Conectar ahora.",
            mode="missing_runtime",
            command=hermes_browserless_shell_command(config),
            connection_purpose=purpose,
        )
    ready, auth_detail = hermes_codex_ready(config)
    if ready:
        gateway = refresh_telegram_gateway_after_agent_model_change(
            {"AGENT_BRAIN_PROVIDER": "openai_codex", "HERMES_MODEL": getattr(config, "hermes_model", "")}
        ) if purpose == "agent" else None
        return hermes_connect_response(
            "completed",
            "ChatGPT/Codex conectado",
            "El agente ya tiene lista la conexión con ChatGPT/Codex.",
            mode="already_ready",
            command=hermes_browserless_shell_command(config),
            output=auth_detail,
            running=False,
            connection_purpose=purpose,
            gateway=gateway,
        )
    with HERMES_LOGIN_LOCK:
        proc = HERMES_LOGIN_STATE.get("proc")
        running = bool(proc and proc.poll() is None)
    if running:
        return hermes_browserless_snapshot(config, purpose=purpose)
    if os.name == "nt":
        return probe_hermes_model_login(config)
    try:
        import pty

        master_fd, slave_fd = pty.openpty()
        command = hermes_browserless_command(config)
        command[0] = cli_path
        env = hermes_environment(config)
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            command,
            cwd=str(ROOT_DIR),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            close_fds=True,
        )
        os.close(slave_fd)
        session_id = f"hermes-{int(datetime.utcnow().timestamp())}"
        with HERMES_LOGIN_LOCK:
            HERMES_LOGIN_STATE.update(
                {
                    "id": session_id,
                    "status": "browser_login_started",
                    "title": "Conecta ChatGPT desde este navegador",
                    "detail": "Sesion segura abierta dentro de este servidor.",
                    "output": "",
                    "phase": "starting",
                    "auto_note": "Estoy preparando el agente para usar OpenAI Codex.",
                    "auto_provider_sent": False,
                    "auto_codex_subprovider_sent": False,
                    "auto_model_sent": False,
                    "preferred_model": normalize_hermes_model(getattr(config, "hermes_model", "")),
                    "purpose": purpose,
                    "started_at": now_iso(),
                    "updated_at": now_iso(),
                    "proc": proc,
                    "fd": master_fd,
                    "command": hermes_browserless_shell_command(config),
                }
            )
        threading.Thread(target=read_hermes_browserless_output, args=(session_id, master_fd, proc), name="hermes-browserless-login", daemon=True).start()
        return hermes_connect_response(
            "browser_login_started",
            "Conecta ChatGPT desde este navegador",
            f"Abrí la sesión segura dentro de este servidor. Voy a elegir OpenAI Codex y el modelo {normalize_hermes_model(config.hermes_model)} automáticamente. Si aparece un enlace, ábrelo aquí.",
            mode="browserless_started",
            command=hermes_browserless_shell_command(config),
            running=True,
            job_id=session_id,
            connection_purpose=purpose,
            needs_input=False,
            phase="starting",
            auto_note="Estoy preparando el agente para usar OpenAI Codex.",
        )
    except Exception as exc:
        return hermes_connect_response(
            "needs_terminal",
            "No pude abrir la sesión segura",
            "Este servidor no permitió abrir la sesión desde el dashboard. Usa una API compatible o revisa la instalación con soporte.",
            mode="browserless_error",
            command=hermes_browserless_shell_command(config),
            output=str(exc),
        )


def agent_model_connect_status(payload=None):
    payload = payload or {}
    purpose = normalize_connect_purpose(payload.get("connection_purpose") or payload.get("purpose"))
    return hermes_browserless_snapshot(config_for_connect_purpose(purpose), purpose=purpose)


def agent_model_connect_input(payload=None):
    payload = payload or {}
    text = str((payload or {}).get("input") or "")
    if not text.strip():
        purpose = normalize_connect_purpose(payload.get("connection_purpose") or payload.get("purpose"))
        return hermes_browserless_snapshot(config_for_connect_purpose(purpose), purpose=purpose)
    if not text.endswith("\n"):
        text += "\n"
    with HERMES_LOGIN_LOCK:
        fd = HERMES_LOGIN_STATE.get("fd")
        proc = HERMES_LOGIN_STATE.get("proc")
        running = bool(proc and proc.poll() is None and fd is not None)
    if not running:
        purpose = normalize_connect_purpose(payload.get("connection_purpose") or payload.get("purpose"))
        return hermes_browserless_snapshot(config_for_connect_purpose(purpose), purpose=purpose)
    os.write(fd, text.encode("utf-8", errors="replace"))
    with HERMES_LOGIN_LOCK:
        purpose = normalize_connect_purpose(HERMES_LOGIN_STATE.get("purpose"))
    return hermes_browserless_snapshot(config_for_connect_purpose(purpose), purpose=purpose)


def probe_hermes_model_login(config):
    cli = str(getattr(config, "hermes_cli", "") or "hermes").strip() or "hermes"
    try:
        result = subprocess.run([cli, "model", "--no-browser"], cwd=str(ROOT_DIR), env=hermes_environment(config), text=True, capture_output=True, timeout=10, check=False)
    except FileNotFoundError:
        return hermes_connect_response(
            "not_installed",
            "Falta la base del agente",
            "Instala o actualiza Admira IA y vuelve a tocar Conectar ahora.",
            mode="missing_runtime",
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        output = "\n".join([stdout, stderr]).strip()
        return hermes_connect_response(
            "needs_login" if extract_urls_from_text(output) else "needs_terminal",
            "Falta terminar el login",
            "No pude abrir una terminal en este entorno. Si apareció un enlace, ábrelo; si no, usa Conectar desde este navegador o una API compatible.",
            mode="probe_timeout",
            command=hermes_browserless_shell_command(config),
            output=output,
        )
    output = "\n".join([(result.stdout or ""), (result.stderr or "")]).strip()
    if result.returncode == 0:
        return hermes_connect_response(
            "completed",
            "Conexión revisada",
            "El agente terminó correctamente. Ahora revisa la conexión y prueba el chat.",
            mode="probe_completed",
            command=hermes_browserless_shell_command(config),
            output=output,
        )
    return hermes_connect_response(
        "needs_login" if extract_urls_from_text(output) else "needs_terminal",
        "Falta terminar la conexión",
        "El agente respondió, pero todavía necesita que termines el login o elijas el proveedor.",
        mode="probe_failed",
        command=hermes_browserless_shell_command(config),
        output=output,
    )


def connect_agent_model(payload=None):
    payload = payload or {}
    purpose = normalize_connect_purpose(payload.get("connection_purpose") or payload.get("purpose"))
    if purpose == "image":
        image_model = normalize_hermes_model(payload.get("codex_image_hermes_model") or payload.get("hermes_model") or "")
        update_env_values(
            {
                "CODEX_IMAGE_SOURCE": "dedicated_chatgpt",
                "CODEX_IMAGE_HERMES_HOME": str(default_codex_image_hermes_home()),
                "CODEX_IMAGE_HERMES_MODEL": image_model,
            }
        )
        config = image_codex_config(load_config())
        ready, auth_detail = hermes_codex_ready(config)
        if ready:
            return hermes_connect_response(
                "completed",
                "ChatGPT/Codex para imágenes conectado",
                "Image 2 ya tiene lista una sesión de ChatGPT/Codex separada. El cerebro principal del agente no cambió.",
                mode="image_already_ready",
                command=hermes_browserless_shell_command(config),
                output=auth_detail,
                running=False,
                connection_purpose="image",
            )
        if launch_hermes_terminal(config):
            return hermes_connect_response(
                "terminal_opened",
                "Abrí la terminal",
                "Sigue la ventana que se abrió para conectar ChatGPT/Codex solo para imágenes. El modelo principal no cambiará.",
                mode="image_terminal",
                connection_purpose="image",
            )
        return start_hermes_browserless_login(config, purpose="image")
    env_updates = {"AGENT_CHAT_PROVIDER": "hermes", "AGENT_BRAIN_PROVIDER": "openai_codex", "HERMES_REQUIRE_CODEX_AUTH": "true"}
    env_updates["HERMES_MODEL"] = normalize_hermes_model(payload.get("hermes_model") if "hermes_model" in payload else "")
    update_env_values(env_updates)
    config = load_config()
    ready, auth_detail = hermes_codex_ready(config)
    if ready:
        gateway = refresh_telegram_gateway_after_agent_model_change(env_updates)
        return hermes_connect_response(
            "completed",
            "ChatGPT/Codex conectado",
            "El agente ya tiene lista tu sesión de ChatGPT/Codex. No hace falta abrir otro login.",
            mode="already_ready",
            command=hermes_browserless_shell_command(config),
            output=auth_detail,
            running=False,
            gateway=gateway,
        )
    if launch_hermes_terminal(config):
        return hermes_connect_response(
            "terminal_opened",
            "Abrí la terminal",
            "Sigue la ventana que se abrió. Cuando termines, vuelve al dashboard y toca Revisar conexión.",
            mode="terminal",
        )
    return start_hermes_browserless_login(config)


AGENT_MODEL_GATEWAY_ENV_KEYS = {
    "AGENT_BRAIN_PROVIDER",
    "AGENT_CHAT_PROVIDER",
    "AGENT_CHAT_BASE_URL",
    "AGENT_CHAT_MODEL",
    "AGENT_CHAT_API",
    "AGENT_CHAT_API_KEY",
    "HERMES_MODEL",
    "HERMES_REQUIRE_CODEX_AUTH",
}


def refresh_telegram_gateway_after_agent_model_change(env_updates):
    changed = sorted(set(env_updates or {}) & AGENT_MODEL_GATEWAY_ENV_KEYS)
    if not changed:
        return None
    try:
        gateway = start_hermes_gateway(load_config())
    except Exception as exc:
        return {"started": False, "mode": "hermes_gateway", "detail": "No pude refrescar Telegram con el modelo nuevo.", "error": str(exc), "changed": changed}
    if isinstance(gateway, dict):
        return {**gateway, "changed": changed}
    return {"started": bool(gateway), "mode": "hermes_gateway", "changed": changed}


def save_setup_config(payload):
    replaced = False if payload.get("_skip_business_enforcement") else enforce_individual_business_change(payload)
    managed_state = None
    cleaned_ad_account_id = clean_ad_account_id(payload.get("ad_account_id")) if "ad_account_id" in payload else ""
    if cleaned_ad_account_id:
        managed_state = prepare_managed_ad_account_update(
            {
                "id": cleaned_ad_account_id,
                "name": payload.get("account_name") or cleaned_ad_account_id,
                "currency": payload.get("account_currency", ""),
                "status": payload.get("account_status", ""),
                "business_id": payload.get("business_id") or payload.get("business_manager_id"),
                "business_name": payload.get("business_name") or payload.get("business_manager_name"),
            },
            replace_business=replaced,
        )
    env_updates = {}
    text_fields = {
        "license_key": "LICENSE_KEY",
        "license_buyer_email": "LICENSE_BUYER_EMAIL",
        "ad_account_id": "META_AD_ACCOUNT_ID",
    }
    for field, env_key in text_fields.items():
        if field not in payload:
            continue
        value = cleaned_ad_account_id if field == "ad_account_id" else str(payload.get(field) or "").strip()
        if field == "license_key" and not value:
            continue
        env_updates[env_key] = value
    provider = normalize_agent_chat_provider(payload.get("agent_chat_provider")) if "agent_chat_provider" in payload else ""
    if provider:
        env_updates["AGENT_CHAT_PROVIDER"] = "hermes"
        env_updates["AGENT_BRAIN_PROVIDER"] = provider
        env_updates["HERMES_REQUIRE_CODEX_AUTH"] = "true" if provider == "openai_codex" else "false"
    if "agent_chat_base_url" in payload:
        base_url = validate_agent_chat_base_url(payload.get("agent_chat_base_url"))
        if base_url:
            env_updates["AGENT_CHAT_BASE_URL"] = base_url
    if "agent_chat_model" in payload:
        model = str(payload.get("agent_chat_model") or "").strip()
        if model:
            env_updates["AGENT_CHAT_MODEL"] = model
    if "agent_chat_api" in payload:
        api = str(payload.get("agent_chat_api") or "").strip().lower()
        if api:
            env_updates["AGENT_CHAT_API"] = api
    if "agent_chat_api_key" in payload:
        api_key = str(payload.get("agent_chat_api_key") or "").strip()
        if api_key:
            env_updates["AGENT_CHAT_API_KEY"] = api_key
    if "hermes_model" in payload:
        hermes_model = normalize_hermes_model(payload.get("hermes_model"))
        env_updates["HERMES_MODEL"] = hermes_model
    if "codex_image_source" in payload:
        image_source = normalize_codex_image_source(payload.get("codex_image_source"))
        env_updates["CODEX_IMAGE_SOURCE"] = image_source
        if image_source == "dedicated_chatgpt":
            env_updates["CODEX_IMAGE_HERMES_HOME"] = str(default_codex_image_hermes_home())
    if "codex_image_hermes_model" in payload:
        env_updates["CODEX_IMAGE_HERMES_MODEL"] = normalize_hermes_model(payload.get("codex_image_hermes_model"))
    if env_updates:
        update_env_values(env_updates)
    gateway_refresh = None

    ad_config = read_json(AD_CONFIG_FILE, {})
    ad_config.setdefault("account", {})
    ad_config.setdefault("creative", {})
    ad_config["creative"].setdefault("destination", {})
    destination = ad_config["creative"]["destination"]
    if cleaned_ad_account_id:
        ad_config["account"]["id"] = cleaned_ad_account_id
        if payload.get("business_manager_id") or payload.get("business_id"):
            ad_config["account"]["business_manager_id"] = str(payload.get("business_manager_id") or payload.get("business_id") or "").strip()
        if payload.get("business_manager_name") or payload.get("business_name"):
            ad_config["account"]["business_manager_name"] = str(payload.get("business_manager_name") or payload.get("business_name") or "").strip()
    for field, key in {
        "page_id": "page_id",
        "instagram_actor_id": "instagram_actor_id",
        "default_adset_id": "default_adset_id",
        "landing_url": "url",
    }.items():
        if field in payload:
            destination[key] = str(payload.get(field) or "").strip()
    write_json(AD_CONFIG_FILE, ad_config)
    if managed_state:
        managed_state = write_managed_accounts_state(managed_state)
    if str(payload.get("page_id") or "").strip() and not payload.get("_skip_meta_profile_sync"):
        page = read_meta_page_profile(payload.get("page_id"))
        suggested = {
            "page_id": destination.get("page_id", ""),
            "page_name": page.get("name", ""),
            "instagram_actor_id": destination.get("instagram_actor_id", "") or (page.get("instagram") or {}).get("id", ""),
            "instagram_username": (page.get("instagram") or {}).get("username", ""),
            "landing_url": destination.get("url", "") or page.get("website", ""),
        }
        sync_business_profile_from_meta_assets(page, suggested, [suggested["landing_url"]] if suggested.get("landing_url") else [])
    gateway_refresh = refresh_telegram_gateway_after_agent_model_change(env_updates)
    log_action("setup_config_save", {"updated": sorted(list(env_updates.keys()) + ["ad-config.json"] + (["managed_ad_accounts.json"] if managed_state else [])), "business_replaced": replaced}, "completed")
    return {"saved": True, "business_replaced": replaced, "env_updated": sorted(env_updates.keys()), "ad_config": ad_config, "managed_ad_accounts": managed_ad_accounts_payload(), "gateway": gateway_refresh}


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
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Solo puedo leer webs http o https.")
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", parsed.query, ""))


def public_website_host(hostname):
    host = str(hostname or "").strip().strip("[]").lower()
    if not host or host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        parsed_ip = ipaddress.ip_address(host)
        return not (
            parsed_ip.is_loopback
            or parsed_ip.is_private
            or parsed_ip.is_link_local
            or parsed_ip.is_reserved
            or parsed_ip.is_multicast
            or parsed_ip.is_unspecified
        )
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True
    if not infos:
        return False
    for family, _, _, _, sockaddr in infos:
        address = sockaddr[0]
        try:
            parsed_ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if (
            parsed_ip.is_loopback
            or parsed_ip.is_private
            or parsed_ip.is_link_local
            or parsed_ip.is_reserved
            or parsed_ip.is_multicast
            or parsed_ip.is_unspecified
        ):
            return False
    return True


def validate_public_website_url(url):
    parsed = urllib.parse.urlparse(str(url or ""))
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Escribe una web publica valida, por ejemplo https://tumarca.com")
    if not public_website_host(parsed.hostname):
        raise ValueError("Por seguridad, solo puedo leer webs publicas. No puedo abrir direcciones locales o privadas.")
    return True


class SafeWebsiteRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_website_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


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
        "main_offer": offer,
        "audience": audience,
        "ideal_customer": audience,
        "current_stage": context[:800],
        "what_to_improve": "Entender mejor qué anuncios pueden vender esta oferta y preparar el primer plan sin adivinar.",
        "positioning": description or title,
        "detected_title": title,
        "detected_headings": headings[:8],
        "suggested_angles": angles,
        "initial_plan": plan,
        "source": "website_scan_basic",
        "created_at": now_iso(),
    }


def extract_json_object_from_text(text):
    raw = str(text or "").strip()
    if not raw:
        return {}
    candidates = [raw]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1))
    if "{" in raw and "}" in raw:
        candidates.append(raw[raw.find("{") : raw.rfind("}") + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def apply_business_profile_enrichment(profile, enrichment):
    allowed_strings = [
        "business_type",
        "offer",
        "main_offer",
        "audience",
        "ideal_customer",
        "current_stage",
        "what_to_improve",
        "positioning",
    ]
    allowed_lists = ["suggested_angles", "initial_plan", "detected_headings", "products_services"]
    merged = dict(profile or {})
    for key in allowed_strings:
        value = str((enrichment or {}).get(key) or "").strip()
        if value:
            merged[key] = value[:1200]
    for key in allowed_lists:
        value = (enrichment or {}).get(key)
        if isinstance(value, list):
            merged[key] = [str(item or "").strip()[:300] for item in value if str(item or "").strip()][:8]
    if merged.get("main_offer") and not merged.get("offer"):
        merged["offer"] = merged["main_offer"]
    if merged.get("offer") and not merged.get("main_offer"):
        merged["main_offer"] = merged["offer"]
    if merged.get("ideal_customer") and not merged.get("audience"):
        merged["audience"] = merged["ideal_customer"]
    if merged.get("audience") and not merged.get("ideal_customer"):
        merged["ideal_customer"] = merged["audience"]
    return merged


BUSINESS_QUESTION_FIELDS = {
    "main_offer",
    "ideal_customer",
    "sales_channel",
    "current_stage",
    "current_ads",
    "biggest_blocker",
    "what_to_improve",
    "success_goal",
    "budget_comfort",
    "brand_tone",
}


def default_business_context_questions(business_type="", language="es"):
    business_type = str(business_type or "").strip()
    if language != "en":
        offer_hint = f"Ej: vendo {business_type}" if business_type else "Ej: vendo cursos, ropa, servicios, tratamientos..."
        return [
            {"key": "main_offer", "label": "¿Qué vendes?", "help": "Una frase corta.", "placeholder": offer_hint},
            {"key": "ideal_customer", "label": "¿Quién compra?", "help": "La persona que más quieres atraer.", "placeholder": "Ej: mujeres de 25 a 40, dueños de negocio, mamás..."},
            {"key": "sales_channel", "label": "¿Dónde vendes?", "help": "Web, WhatsApp, Instagram, tienda física o llamada.", "placeholder": "Ej: vendo por WhatsApp y mi web."},
            {"key": "current_stage", "label": "¿En qué punto estás?", "help": "Dime si empiezas, ya vendes o ya tienes anuncios.", "placeholder": "Ej: ya vendo, pero mis anuncios me confunden."},
            {"key": "biggest_blocker", "label": "¿Qué te frena hoy?", "help": "Lo que más te preocupa ahora.", "placeholder": "Ej: no sé qué anuncio pausar o escalar."},
            {"key": "success_goal", "label": "¿Qué sería una victoria?", "help": "Algo claro para los próximos 30 días.", "placeholder": "Ej: bajar costo por compra o vender 20 unidades más."},
        ]
    offer_hint = f"Ex: I sell {business_type}" if business_type else "Ex: courses, clothing, services, treatments..."
    return [
        {"key": "main_offer", "label": "What do you sell?", "help": "One short sentence.", "placeholder": offer_hint},
        {"key": "ideal_customer", "label": "Who buys?", "help": "The person you most want to attract.", "placeholder": "Ex: women 25-40, business owners, moms..."},
        {"key": "sales_channel", "label": "Where do you sell?", "help": "Website, WhatsApp, Instagram, store, or call.", "placeholder": "Ex: I sell through WhatsApp and my website."},
        {"key": "current_stage", "label": "Where are you now?", "help": "Starting, already selling, or already running ads.", "placeholder": "Ex: I sell already, but ads confuse me."},
        {"key": "biggest_blocker", "label": "What blocks you today?", "help": "The thing that worries you most.", "placeholder": "Ex: I do not know what to pause or scale."},
        {"key": "success_goal", "label": "What would be a win?", "help": "Something clear for the next 30 days.", "placeholder": "Ex: lower purchase cost or sell 20 more units."},
    ]


def normalize_business_context_questions(value, business_type="", language="es"):
    questions = []
    seen = set()
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        key = re.sub(r"[^a-z0-9_]+", "_", str(item.get("key") or "").strip().lower()).strip("_")
        if key not in BUSINESS_QUESTION_FIELDS or key in seen:
            continue
        label = str(item.get("label") or "").strip()
        help_text = str(item.get("help") or "").strip()
        placeholder = str(item.get("placeholder") or "").strip()
        if not label:
            continue
        questions.append({
            "key": key,
            "label": label[:90],
            "help": help_text[:180] or ("Respuesta corta." if language != "en" else "Short answer."),
            "placeholder": placeholder[:180],
        })
        seen.add(key)
        if len(questions) >= 6:
            break
    required = ["main_offer", "ideal_customer", "current_stage", "what_to_improve"]
    existing = {question["key"] for question in questions}
    fallback = default_business_context_questions(business_type, language)
    for key in required:
        if key in existing:
            continue
        match = next((question for question in fallback if question["key"] == key), None)
        if match:
            questions.append(match)
            existing.add(key)
    if len(questions) < 4:
        return fallback
    return questions[:6]


def generate_business_context_questions(payload):
    language = str((payload or {}).get("language") or "es").lower()
    if language not in {"es", "en"}:
        language = "es"
    profile = read_json(BUSINESS_PROFILE_FILE, {})
    if not isinstance(profile, dict):
        profile = {}
    business_type = str((payload or {}).get("business_type") or (payload or {}).get("business_short") or "").strip()
    website_url = str((payload or {}).get("website_url") or "").strip()
    extra_context = str((payload or {}).get("context") or "").strip()
    if not business_type:
        raise ValueError("Escribe en pocas palabras qué tipo de negocio tienes.")
    profile["business_type"] = business_type[:220]
    profile["business_short"] = business_type[:220]
    profile["onboarding_questions_started"] = True
    if website_url:
        normalized_url = normalize_website_url(website_url)
        validate_public_website_url(normalized_url)
        profile["website_url"] = normalized_url
        profile["website_skipped"] = False
        save_setup_config({"landing_url": normalized_url})
    else:
        profile["website_skipped"] = True
    config = load_config()
    questions = []
    source = "fallback_questions"
    agent_detail = ""
    model_ready = False
    if config.agent_chat_provider == "hermes":
        model_ready, agent_detail = hermes_codex_ready(config)
    else:
        model_ready = bool(config.agent_chat_api_key and config.agent_chat_base_url and config.agent_chat_model)
    if model_ready:
        message = (
            "Eres un manager experto de Meta Ads para compradores principiantes. "
            "Crea preguntas de onboarding tipo Typeform, una pregunta a la vez, para entender este negocio antes de mostrar el dashboard. "
            "Si hay web, puedes usar browser/retrieval para entenderla, pero no inventes datos delicados. "
            "Devuelve SOLO JSON valido con esta forma: "
            '{"questions":[{"key":"main_offer","label":"...","help":"...","placeholder":"..."}]}. '
            "Usa solo estas keys cuando apliquen: main_offer, ideal_customer, sales_channel, current_stage, current_ads, biggest_blocker, what_to_improve, success_goal, budget_comfort, brand_tone. "
            "Haz 5 o 6 preguntas maximo. Lenguaje para una persona de 8 años: corto, claro, sin jerga. "
            "La primera pregunta debe confirmar qué vende. Incluye current_stage y what_to_improve. "
            f"Idioma: {'español latino' if language == 'es' else 'English'}.\n"
            f"Tipo de negocio dicho por el comprador: {business_type}\n"
            f"Web: {profile.get('website_url') or 'sin web'}\n"
            f"Contexto extra: {extra_context or 'sin contexto'}"
        )
        result = agent_chat(
            config,
            {
                "message": message,
                "language": language,
                "metrics": {},
                "recommendations": [],
                "fatigue": [],
                "pending": [],
                "business_profile": profile,
                "brand_guides": {},
                "channel": "onboarding_business_questions",
            },
        )
        parsed = extract_json_object_from_text(result.get("raw_reply") or result.get("reply") or "") if result.get("ok") and not result.get("fallback") else {}
        questions = normalize_business_context_questions(parsed.get("questions"), business_type, language)
        source = "agent_questions" if parsed.get("questions") else "fallback_questions"
        agent_detail = str(result.get("error") or result.get("reply") or agent_detail or "")[:300]
    else:
        questions = default_business_context_questions(business_type, language)
    profile["onboarding_questions"] = questions
    profile["onboarding_questions_source"] = source
    profile["agent_questions_detail"] = agent_detail
    profile["updated_at"] = now_iso()
    profile.setdefault("source", "manual_context")
    write_json(BUSINESS_PROFILE_FILE, profile)
    log_action("business_questions_generate", {"business_type": business_type, "website_url": profile.get("website_url", ""), "source": source, "count": len(questions)}, "completed")
    return {"saved": True, "profile": profile, "questions": questions, "source": source}


def enrich_business_profile_with_agent(url, profile, context):
    config = load_config()
    if config.agent_chat_provider != "hermes":
        return profile, "basic_scan"
    ready, detail = hermes_codex_ready(config)
    if not ready:
        result = dict(profile)
        result["agent_scan_status"] = "agent_not_connected"
        result["agent_scan_detail"] = detail[:300]
        return result, "basic_scan"
    message = (
        "Lee esta web publica con la herramienta de navegador o retrieval del agente si esta disponible: "
        f"{url}\n\n"
        "Necesito preparar el onboarding de un comprador principiante de Meta Ads. "
        "Devuelve SOLO JSON valido, sin markdown, con estas claves: "
        "business_type, main_offer, ideal_customer, current_stage, what_to_improve, positioning, "
        "suggested_angles, initial_plan. "
        "Escribe en español latino natural. Si algo no se puede saber por la web, haz una sugerencia prudente para que el comprador la revise. "
        "Contexto adicional del comprador: "
        f"{context or 'sin contexto adicional'}\n\n"
        "Perfil basico detectado hasta ahora:\n"
        f"{json.dumps(profile, ensure_ascii=False)}"
    )
    result = agent_chat(
        config,
        {
            "message": message,
            "language": "es",
            "metrics": {},
            "recommendations": [],
            "fatigue": [],
            "pending": [],
            "business_profile": profile,
            "brand_guides": {},
            "channel": "onboarding_website_scan",
        },
    )
    if not result.get("ok") or result.get("fallback"):
        updated = dict(profile)
        updated["agent_scan_status"] = "agent_scan_unavailable"
        updated["agent_scan_detail"] = str(result.get("error") or result.get("reply") or "")[:300]
        return updated, "basic_scan"
    enrichment = extract_json_object_from_text(result.get("raw_reply") or result.get("reply") or "")
    if not enrichment:
        updated = dict(profile)
        updated["agent_scan_status"] = "agent_scan_empty"
        return updated, "basic_scan"
    updated = apply_business_profile_enrichment(profile, enrichment)
    updated["agent_scan_status"] = "agent_enriched"
    updated["agent_scan_detail"] = "Agent browser/retrieval enrichment applied"
    updated["source"] = "hermes_browser_scan"
    return updated, "hermes_browser_scan"


def enrich_business_links_with_agent(links, profile, context=""):
    config = load_config()
    if config.agent_chat_provider != "hermes":
        return profile, "links_saved_for_agent"
    ready, detail = hermes_codex_ready(config)
    if not ready:
        result = dict(profile)
        result["agent_scan_status"] = "agent_not_connected"
        result["agent_scan_detail"] = detail[:300]
        return result, "links_saved_for_agent"
    link_block = "\n".join(f"- {link}" for link in links[:8])
    message = (
        "Analiza estos links publicos con browser/retrieval del agente si esta disponible:\n"
        f"{link_block}\n\n"
        "Objetivo: antes de que el cliente hable por Telegram, necesito una idea general de que tipo de negocio es, "
        "que productos o servicios ofrece, cual parece ser la oferta principal y que angulos de anuncios podrian tener sentido. "
        "No inicies sesion, no intentes saltar restricciones y no inventes datos privados. "
        "Si una red social bloquea contenido, usa solo lo visible y marca lo demas como sugerencia prudente. "
        "Devuelve SOLO JSON valido, sin markdown, con estas claves: "
        "business_type, main_offer, offer, products_services, ideal_customer, audience, current_stage, "
        "what_to_improve, positioning, suggested_angles, initial_plan. "
        "Escribe en español latino natural y simple para principiantes. "
        f"Contexto breve escrito por el comprador: {context or 'sin contexto adicional'}\n\n"
        "Perfil guardado hasta ahora:\n"
        f"{json.dumps(profile, ensure_ascii=False)}"
    )
    result = agent_chat(
        config,
        {
            "message": message,
            "language": "es",
            "metrics": {},
            "recommendations": [],
            "fatigue": [],
            "pending": [],
            "business_profile": profile,
            "brand_guides": {},
            "channel": "onboarding_public_links_scan",
        },
    )
    if not result.get("ok") or result.get("fallback"):
        updated = dict(profile)
        updated["agent_scan_status"] = "agent_scan_unavailable"
        updated["agent_scan_detail"] = str(result.get("error") or result.get("reply") or "")[:300]
        return updated, "links_saved_for_agent"
    enrichment = extract_json_object_from_text(result.get("raw_reply") or result.get("reply") or "")
    if not enrichment:
        updated = dict(profile)
        updated["agent_scan_status"] = "agent_scan_empty"
        return updated, "links_saved_for_agent"
    updated = apply_business_profile_enrichment(profile, enrichment)
    updated["agent_scan_status"] = "agent_enriched"
    updated["agent_scan_detail"] = "Agent browser/retrieval enrichment applied to public links"
    updated["source"] = "hermes_links_scan"
    return updated, "hermes_links_scan"


def scan_business_website(payload):
    url = normalize_website_url(payload.get("website_url"))
    context = str(payload.get("current_stage") or "").strip()
    if not url:
        raise ValueError("Escribe la web de tu negocio.")
    validate_public_website_url(url)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MetaAdsAgentWebsiteScanner/1.0 (+local onboarding)"},
        method="GET",
    )
    try:
        opener = urllib.request.build_opener(SafeWebsiteRedirectHandler)
        with opener.open(request, timeout=15) as response:
            validate_public_website_url(response.geturl())
            body = response.read(350000).decode(response.headers.get_content_charset() or "utf-8", errors="ignore")
    except Exception as exc:
        profile = {
            "website_url": url,
            "business_type": "negocio por definir",
            "offer": "oferta por definir",
            "main_offer": "oferta por definir",
            "audience": "audiencia por definir",
            "ideal_customer": "audiencia por definir",
            "current_stage": context,
            "what_to_improve": "Preparar una primera lectura clara del negocio y convertirla en anuncios simples.",
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
    profile, source = enrich_business_profile_with_agent(url, profile, context)
    profile["source"] = source or profile.get("source") or "website_scan_basic"
    profile["onboarding_questions_started"] = True
    profile["onboarding_questions"] = normalize_business_context_questions(profile.get("onboarding_questions") or [], profile.get("business_type") or "", "es")
    write_json(BUSINESS_PROFILE_FILE, profile)
    save_setup_config({"landing_url": url})
    log_action("business_website_scan", {"website_url": url, "source": profile.get("source"), "scan_error": profile.get("scan_error", "")}, "completed" if not profile.get("scan_error") else "warn")
    return {"saved": True, "profile": profile}


def onboarding_interview_status(profile=None):
    profile = profile if isinstance(profile, dict) else read_json(BUSINESS_PROFILE_FILE, {})
    if not isinstance(profile, dict):
        profile = {}
    if profile.get("context_completed_at"):
        return "completed"
    if profile.get("telegram_onboarding_requested_at"):
        return "pending_telegram"
    if profile.get("website_url") or profile.get("social_links") or profile.get("business_type"):
        return "ready_to_ask"
    return "empty"


UNDEFINED_PRODUCT_CONTEXT_PHRASES = (
    "oferta por definir",
    "audiencia por definir",
    "producto por definir",
    "servicio por definir",
    "negocio por definir",
    "to be defined",
    "tbd",
)


def meaningful_creative_context_text(value, min_len=3):
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) < min_len:
        return False
    lowered = text.lower()
    return not any(phrase in lowered for phrase in UNDEFINED_PRODUCT_CONTEXT_PHRASES)


def payload_has_product_context(payload):
    payload = normalize_product_payload(payload or {})
    for key in ("name", "product_name", "product", "offer", "main_offer", "audience", "pain", "desire"):
        if meaningful_creative_context_text(payload.get(key)):
            return True
    for key in ("product_guide", "promotion", "request", "image_prompt", "prompt"):
        value = str(payload.get(key) or "").strip()
        if (
            len(value) >= 8
            and not value.lower().strip().startswith((".env", "license_unlock"))
            and meaningful_creative_context_text(value, min_len=8)
        ):
            return True
    return False


def business_profile_product_context(profile=None):
    profile = profile if isinstance(profile, dict) else read_json(BUSINESS_PROFILE_FILE, {})
    if not isinstance(profile, dict):
        return ""
    lines = []

    def add(label, value):
        text = compact_creative_context_value(value)
        if meaningful_creative_context_text(text):
            lines.append(f"{label}: {text}")

    add("Producto/oferta", profile.get("main_offer") or profile.get("offer") or profile.get("products_services"))
    add("Tipo de negocio", profile.get("business_type") or profile.get("business_short"))
    add("Público", profile.get("ideal_customer") or profile.get("audience"))
    add("Etapa", profile.get("current_stage"))
    add("Meta/problema a mejorar", profile.get("what_to_improve") or profile.get("success_goal"))
    return "; ".join(lines)


def truthy_payload_flag(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "sí", "on", "required", "require"}


def logo_text_disables_official_use(value):
    text = str(value or "").strip().lower()
    if not text:
        return False
    conditional_allow = (
        "hasta tener archivo oficial",
        "hasta que tenga archivo oficial",
        "cuando exista archivo oficial",
        "until official",
        "until the official",
    )
    if any(phrase in text for phrase in conditional_allow):
        return False
    opt_out_phrases = (
        "sin logo",
        "no logo",
        "without logo",
        "no incluir logo",
        "no incluyas logo",
        "no usar logo",
        "no uses logo",
        "no mostrar logo",
        "no muestres logo",
        "logo nunca",
        "never use logo",
        "never show logo",
    )
    return any(phrase in text for phrase in opt_out_phrases)


def creative_image_requires_brief(payload=None, purpose="ad_creative"):
    payload = payload or {}
    purpose = str(purpose or "ad_creative").strip().lower()
    if "require_brief" in payload:
        return truthy_payload_flag(payload.get("require_brief"))
    if any(truthy_payload_flag(payload.get(key)) for key in ("asset_only", "draft_only", "standalone_creative")):
        return False
    if purpose in {"logo", "brand_exploration", "moodboard", "creative_asset", "standalone_creative", "draft_creative", "asset_only"}:
        return False
    if purpose in {"launch_ad", "campaign_ad", "ad_test", "live_ad", "campaign_ready", "launch_ready"}:
        return True
    request = str(payload.get("request") or payload.get("image_prompt") or payload.get("prompt") or "").lower()
    launch_words = ("lanzar", "activar", "publicar campaña", "subir a meta", "ready to launch", "launch campaign", "stage campaign")
    if any(word in request for word in launch_words):
        return True
    return False


def branding_creative_readiness(require_product=True, payload=None):
    payload = payload or {}
    brand_payload = normalize_general_payload(payload)
    library = guide_library()
    profile = read_json(BUSINESS_PROFILE_FILE, {})
    if not isinstance(profile, dict):
        profile = {}
    general = (library.get("general") or {}).get("fields") or {}
    missing = []
    requirements = [
        ("brand_core", bool((library.get("general_exists") and (general.get("brand_name") or general.get("offer"))) or brand_payload.get("brand_name") or brand_payload.get("offer")), "¿Cómo se llama la marca y qué vende exactamente?"),
        ("colors", bool(general.get("colors") or brand_payload.get("colors")), "¿Qué colores exactos debemos respetar, o quieres que te proponga una paleta?"),
        ("visual_style", bool(general.get("visual_style") or brand_payload.get("visual_style")), "¿Cómo deben verse los anuncios: fondos, composición, energía y estilo fotográfico?"),
        ("tone", bool(general.get("tone") or general.get("personality") or brand_payload.get("tone")), "¿Cómo debe sonar la marca: cercana, experta, directa, divertida u otra combinación?"),
        (
            "logo_decision",
            bool(general.get("logo_path") or general.get("logo_notes") or general.get("logo_usage") or brand_payload.get("logo_path") or brand_payload.get("logo_notes") or brand_payload.get("logo_usage")),
            "¿Tienes un logo oficial para subir, quieres crear uno después o prefieres trabajar sin logo?",
        ),
        (
            "reference_decision",
            bool(general.get("references") or library.get("creative_references_exists") or brand_payload.get("references")),
            "¿Tienes algún diseño, anuncio o marca de referencia que te guste? Puedes subirlo; si no tienes, dímelo y busco direcciones contigo.",
        ),
        (
            "real_asset_decision",
            bool(general.get("asset_notes") or brand_payload.get("asset_notes")),
            "¿Tienes fotos reales del producto, fundador, clientes, local o empaque para usar, o debemos generar las imágenes?",
        ),
    ]
    if general.get("logo_path"):
        requirements.append(("logo_usage", bool(general.get("logo_usage") or general.get("logo_path")), "¿El logo oficial debe aparecer siempre, a veces o nunca en los anuncios, y en qué posición prefieres verlo?"))
    if require_product:
        product_ready = (
            any(bool(item.get("ready")) for item in library.get("products") or [])
            or payload_has_product_context(payload)
            or payload_has_product_context(profile)
        )
        requirements.append(("product_guide", product_ready, "¿Cuál es el producto u oferta principal, para quién es y qué problema resuelve?"))
    for key, ready, question in requirements:
        if not ready:
            missing.append({"key": key, "question": question})
    return {
        "ready": not missing,
        "missing": missing,
        "next_question": missing[0]["question"] if missing else "",
        "general": general,
        "library": library,
    }


CREATIVE_TEST_BUDGET_KEYS = (
    "test_budget",
    "budget_comfort",
    "budget",
    "ad_test_budget",
    "daily_test_budget",
    "test_daily_budget",
    "daily_budget",
    "adset_daily_budget",
    "campaign_daily_budget",
    "monthly_budget",
)


def budget_like_text(value):
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if any(token in lowered for token in ["presupuesto", "budget", "usd", "us$", "$"]) and re.search(r"\d", text):
        return text[:240]
    if re.search(r"\d+(?:[.,]\d+)?\s*(?:d[oó]lares?|usd|us\$|\$)", lowered):
        return text[:240]
    if re.search(r"\d+(?:[.,]\d+)?\s*(?:/)?\s*(?:d[ií]a|diario|diarios|daily|mes|mensual|monthly|semana|week)", lowered):
        return text[:240]
    return ""


def budget_from_mapping(mapping, scan_notes=False):
    if not isinstance(mapping, dict):
        return ""
    for key in CREATIVE_TEST_BUDGET_KEYS:
        value = str(mapping.get(key) or "").strip()
        if value:
            return value[:240]
    if scan_notes:
        for key, value in mapping.items():
            if key in {"name", "campaign_name", "campaign_id", "adset_id", "base_ad_id"}:
                continue
            detected = budget_like_text(value)
            if detected:
                return detected
    return ""


def creative_test_budget_value(profile, library, payload=None):
    budget = budget_from_mapping(payload)
    if budget:
        return budget
    budget = budget_from_mapping(profile)
    if budget:
        return budget
    briefs = (library or {}).get("ad_briefs") or []
    if briefs:
        brief_fields = (briefs[-1].get("fields") or {}) if isinstance(briefs[-1], dict) else {}
        budget = budget_from_mapping(brief_fields, scan_notes=True)
        if budget:
            return budget
    return ""


def creative_strategy_readiness(require_brief=False, purpose="ad_creative", payload=None):
    purpose = str(purpose or "ad_creative").strip().lower()
    is_ad = purpose not in {"logo", "brand_exploration", "moodboard"}
    payload = normalize_ad_brief_payload(payload or {})
    branding = branding_creative_readiness(require_product=is_ad, payload=payload)
    missing = list(branding["missing"])
    library = branding["library"]
    profile = read_json(BUSINESS_PROFILE_FILE, {})
    if not isinstance(profile, dict):
        profile = {}
    budget = creative_test_budget_value(profile, library, payload)
    if is_ad and require_brief:
        briefs = library.get("ad_briefs") or []
        brief_fields = dict((briefs[-1].get("fields") or {}) if briefs else {})
        for key, value in payload.items():
            if key in {
                "name",
                "product_guide",
                "campaign_name",
                "base_ad_name",
                "base_ad",
                "objective",
                "promotion",
                "audience_slice",
                "variation_window",
                "variation_axes",
                "variation_count",
                "concurrent_variations",
                "formats",
                "creative_hypothesis",
            } and str(value or "").strip():
                brief_fields[key] = str(value).strip()
        has_brief_context = bool(
            briefs
            or any(str(brief_fields.get(key) or "").strip() for key in ("name", "promotion", "campaign_name", "base_ad_name", "base_ad", "variation_window", "variation_axes", "creative_hypothesis"))
        )
        if not has_brief_context:
            missing.append({"key": "ad_brief", "question": "Antes de generar, ¿qué oferta, audiencia y acción debe probar este primer grupo de creativos?"})
        else:
            if not str(brief_fields.get("variation_count") or "").strip():
                missing.append({"key": "variation_count", "question": "¿Cuántos creativos quieres producir y cuántos probar al mismo tiempo con ese presupuesto?"})
            if not str(brief_fields.get("concurrent_variations") or "").strip():
                missing.append({"key": "concurrent_variations", "question": "Con ese presupuesto, ¿cuántos creativos vamos a probar simultáneamente y cuáles quedarán en backlog?"})
            if not str(brief_fields.get("formats") or "").strip():
                missing.append({"key": "creative_formats", "question": "¿Qué mezcla vamos a probar: UGC, foto real, demostración, prueba, diseño estático, carrusel o video?"})
            if not str(brief_fields.get("variation_axes") or "").strip():
                missing.append({"key": "variation_axes", "question": "¿Qué perspectivas distintas vamos a probar: dolor, deseo, prueba, demostración, objeción u oferta?"})
            if not str(brief_fields.get("creative_hypothesis") or "").strip():
                missing.append({"key": "creative_hypothesis", "question": "¿Qué queremos aprender con estas variaciones para reconocer al ganador?"})
    return {
        "ready": not missing,
        "purpose": purpose,
        "missing": missing,
        "next_question": missing[0]["question"] if missing else "",
        "budget": budget,
        "branding": branding,
    }


def creative_not_ready_result(reason, readiness):
    missing = readiness.get("missing") or []
    return {
        "ok": False,
        "blocked": True,
        "reason": reason,
        "error": readiness.get("next_question") or "Antes de crear creativos, falta completar la estrategia de marca.",
        "readiness": readiness,
        "missing": [item.get("key") for item in missing if isinstance(item, dict)],
    }


def compact_creative_context_value(value, limit=260):
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def creative_direct_context(payload):
    """Return prompt-safe context explicitly sent by Hermes when library files lag behind."""
    payload = payload or {}
    general = normalize_general_payload(payload)
    product = normalize_product_payload(payload)
    brief = normalize_ad_brief_payload(payload)
    lines = []

    def add(label, value):
        text = compact_creative_context_value(value)
        if text:
            lines.append(f"- {label}: {text}")

    add("Marca", general.get("brand_name"))
    add("Qué vende", general.get("offer"))
    add("Mercado/ubicación", general.get("market"))
    add("Colores", general.get("colors"))
    add("Estilo visual", general.get("visual_style"))
    add("Tono", general.get("tone"))
    add("Logo", general.get("logo_notes") or general.get("logo_usage") or general.get("logo_path"))
    add("Referencias", general.get("references"))
    add("Fotos/activos reales", general.get("asset_notes"))
    add("Producto/oferta", product.get("name") or brief.get("product_guide"))
    add("Precio", product.get("price"))
    add("Público", product.get("audience") or brief.get("audience_slice"))
    add("Problema", product.get("pain"))
    add("Beneficio/deseo", product.get("desire"))
    add("Debe mostrar", product.get("show") or brief.get("required_assets"))
    add("Promoción", brief.get("promotion"))
    add("Formatos", brief.get("formats"))
    add("Ejes de variación", brief.get("variation_axes"))
    add("Hipótesis creativa", brief.get("creative_hypothesis"))
    if not lines:
        return ""
    return "Contexto explícito recibido en esta solicitud:\n" + "\n".join(lines)


def direct_product_guide_text(payload):
    payload = payload or {}
    product = normalize_product_payload(payload)
    brief = normalize_ad_brief_payload(payload)
    parts = []

    def add(label, value):
        text = compact_creative_context_value(value)
        if text:
            parts.append(f"{label}: {text}")

    add("Producto/oferta", product.get("name") or brief.get("product_guide"))
    add("Precio", product.get("price"))
    add("Público", product.get("audience") or brief.get("audience_slice"))
    add("Problema", product.get("pain"))
    add("Beneficio/deseo", product.get("desire"))
    add("Debe mostrar", product.get("show") or brief.get("required_assets"))
    add("Promoción", brief.get("promotion"))
    return "; ".join(parts)


REFERENCE_AS_BACKGROUND_FLAGS = (
    "use_reference_as_background",
    "use_uploaded_image_as_background",
    "preserve_reference_image",
    "preserve_real_photo",
    "real_photo_background",
    "reference_as_base",
    "base_image",
)
REFERENCE_AS_BACKGROUND_TEXT = (
    "base visual",
    "como base",
    "como fondo",
    "conservar la foto",
    "conservar mi foto",
    "conserva la foto",
    "conserva mi foto",
    "foto real",
    "fondo real",
    "imagen de fondo",
    "no cambies el fondo",
    "no cambies el local",
    "no reemplaces",
    "pixel por pixel",
    "píxel por píxel",
    "recepcion",
    "recepción",
    "same background",
    "use as background",
    "use as base",
    "use the real photo",
)


def reference_as_background_requested(payload, request=""):
    payload = payload or {}
    if any(truthy_payload_flag(payload.get(key)) for key in REFERENCE_AS_BACKGROUND_FLAGS):
        return True
    for key in ("reference_image_role", "image_reference_role", "reference_usage", "image_use_mode", "background_source"):
        value = str(payload.get(key) or "").strip().lower()
        if value and any(token in value for token in ("background", "base", "fondo", "foto real", "real_photo", "real photo", "recepcion", "recepción")):
            return True
    try:
        text = json.dumps(payload, ensure_ascii=False).lower()
    except (TypeError, ValueError):
        text = str(payload or "").lower()
    text = f"{text}\n{str(request or '').lower()}"
    return any(phrase in text for phrase in REFERENCE_AS_BACKGROUND_TEXT)


def reference_background_prompt_lock(reference_paths, payload=None, request=""):
    if not reference_paths or not reference_as_background_requested(payload, request):
        return ""
    return (
        "\nMODO FOTO REAL COMO BASE OBLIGATORIA PARA IMAGE 2:\n"
        "- La primera imagen adjunta es la foto real/base/fondo del anuncio. No es solo inspiración.\n"
        "- Usa esa foto real como la base visual principal y conserva fielmente la recepción/local/escena real.\n"
        "- Mantén la composición, perspectiva, arquitectura, distribución, muebles, paredes, suelo, iluminación base, encuadre y proporciones de la foto original.\n"
        "- No reemplaces el local por otra escena, no inventes otra recepción, no cambies el negocio visible ni conviertas la foto en una escena genérica de spa.\n"
        "- Preserva el fondo de forma pixel-faithful / fiel píxel por píxel tanto como Image 2 lo permita.\n"
        "- Sí puedes hacer mejoras globales sutiles para que se vea publicitario y bonito: luz, color, contraste, limpieza visual, nitidez y jerarquía de texto.\n"
        "- Agrega el texto/oferta/CTA del anuncio encima de forma profesional, legible y elegante, sin tapar las partes importantes del local.\n"
    )


def branding_creatives_status():
    readiness = branding_creative_readiness()
    library = readiness["library"]
    if readiness["ready"]:
        return "completed"
    if library.get("general_exists") or library.get("product_count") or library.get("creative_references_exists"):
        return "in_progress"
    return "pending"


def ads_campaign_onboarding_status(profile=None):
    profile = profile if isinstance(profile, dict) else read_json(BUSINESS_PROFILE_FILE, {})
    if not isinstance(profile, dict):
        profile = {}
    completion_fields = ["campaign_goal", "budget_comfort", "first_strategy"]
    if profile.get("ads_onboarding_completed_at") and all(str(profile.get(key) or "").strip() for key in completion_fields):
        return "completed"
    fields = ["promoted_before", "previous_ads_results", "current_campaign_context", "campaign_goal", "campaign_constraints"]
    if any(str(profile.get(key) or "").strip() for key in fields) or ADS_ONBOARDING_FILE.exists():
        return "in_progress"
    return "pending"


def agent_onboarding_phase(profile=None):
    profile = profile if isinstance(profile, dict) else read_json(BUSINESS_PROFILE_FILE, {})
    if not isinstance(profile, dict):
        profile = {}
    business = onboarding_interview_status(profile)
    branding = branding_creatives_status()
    campaigns = ads_campaign_onboarding_status(profile)
    creative_readiness = creative_strategy_readiness(require_brief=False)
    if business != "completed":
        phase = "business_discovery"
        next_step = "Entrevistar al cliente sobre negocio, oferta, cliente ideal, etapa actual, problemas y meta de 30 dias."
    elif branding != "completed":
        phase = "branding_creatives_creation"
        next_step = creative_readiness.get("next_question") or "Usar el skill branding creatives creation para definir marca, logo, productos, referencias, paletas, fuentes y reglas de creativos."
    elif campaigns != "completed":
        phase = "ads_campaign_onboarding"
        next_step = "Entender que ha promovido antes, resultados, aprendizajes, restricciones y primera estrategia de campanas."
    else:
        phase = "continuous_ads_manager"
        next_step = "Operar como manager continuo: leer datos, recordar decisiones, proponer acciones, esperar resultados cuando conviene."
    return {
        "phase": phase,
        "business": business,
        "branding": branding,
        "campaigns": campaigns,
        "next_step": next_step,
        "creative_readiness": {
            "ready": creative_readiness.get("ready", False),
            "missing": creative_readiness.get("missing", []),
            "next_question": creative_readiness.get("next_question", ""),
            "budget": creative_readiness.get("budget", ""),
        },
    }


def agent_onboarding_deferred_reasons(profile=None):
    phase = agent_onboarding_phase(profile)
    reasons = []
    if phase["business"] != "completed":
        reasons.append("entrevista_negocio")
    if phase["branding"] != "completed":
        reasons.append("branding_creativos")
    if phase["campaigns"] != "completed":
        reasons.append("campanas_anuncios")
    return reasons


def write_agent_onboarding_plan(profile=None):
    profile = profile if isinstance(profile, dict) else read_json(BUSINESS_PROFILE_FILE, {})
    if not isinstance(profile, dict):
        profile = {}
    phase = agent_onboarding_phase(profile)
    body = f"""# Agent onboarding plan

Estado actual: {phase["phase"]}.

Siguiente movimiento: {phase["next_step"]}

## Primer mensaje del onboarding

Antes de hacer la primera pregunta, explica el camino con palabras simples:

1. Primero voy a entender tu negocio: que vendes, a quien le vendes, en que etapa estas y que quieres mejorar.
2. Despues vamos a definir tu parte visual: marca, logo, colores, referencias, estilo y tono.
3. Luego aterrizamos anuncios: ofertas especificas, campanas anteriores, estrategia, briefs y proximos pasos.

Despues de explicar esto, pregunta tambien la preferencia global del operador: "Tienes experiencia creando o gestionando anuncios? Quieres que te explique cosas tecnicas con detalle, o prefieres que yo tome las decisiones de mejores practicas y te lo explique en palabras simples? Esto lo puedes cambiar cuando quieras."

Cuando responda, guarda esa preferencia con `save_agent_preferences` / `mcp_admira_save_agent_preferences` usando:
- `ad_experience_level`: `beginner`, `intermediate` o `advanced`.
- `communication_style`: `simple` o `technical`.

Despues de esa preferencia, haz una sola pregunta clara de negocio. La mejor primera pregunta es: "Que vendes exactamente y cual es tu oferta principal hoy?"

## Postura experta global

El agente no debe ser pasivo ni limitar su criterio experto a placements. Debe proponer mejoras de alto impacto en todo lo que pueda afectar aprendizaje o gasto: evento de optimizacion, Pixel/Dataset, CAPI/EMQ/AEM como diagnostico, presupuesto, calendario, audiencias, exclusiones, placements, formato creativo, preflight, aprobaciones y revisiones futuras. Si el comprador pidio palabras simples, explica el impacto en negocio y evita tecnicismos; si pidio detalle tecnico, puede profundizar.

## Fases

1. business_discovery
   - Entender que vende, oferta principal, productos/servicios prioritarios, cliente ideal, etapa actual, dolores, meta de 30 dias y tono comercial.
   - Preguntar una sola cosa a la vez.
   - Guardar lo aprendido con `save_business_context`.

2. branding_creatives_creation
   - Usar el skill `skills/branding-creatives-creation/SKILL.md`.
   - Buscar referencias visuales de anuncios del nicho con las herramientas web/browser disponibles.
   - No generar anuncios todavía. Completar colores, estilo visual, tono, decisión de logo, decisión de referencias y decisión sobre fotos/activos reales.
   - Preguntar activamente si el cliente quiere subir un logo, diseño de referencia, foto de producto, fundador, cliente, local o empaque.
   - Proponer estilos, paletas, fuentes, sensaciones, uso de logo y reglas visuales solo después de escuchar esas respuestas.
   - Distinguir que es continuo para toda la marca y que cambia por producto, servicio o campana.
   - Si el cliente envia un logo, guardarlo en la guia general como Logo de marca y Notas del logo.
   - Si el cliente aprueba referencias encontradas, generadas o ambas, guardarlas con `save_creative_references`.
   - Guardar la guia general con `save_brand_guide` y fichas por producto con `save_product_guide`.

3. ads_campaign_onboarding
   - Entender que anuncio antes, que resultados tuvo, que cree que fallo, que quiere mantener, presupuesto, CPA/CPL objetivo cuando exista, paises, ofertas y restricciones.
   - Preguntar por los 3 resultados/KPIs mas importantes para juzgar cada campana en orden de prioridad, por ejemplo ROAS, costo por compra y costo por iniciar checkout; guardarlos y pasarlos como `success_metrics`.
   - Preguntar el presupuesto antes de proponer cuantos creativos probar simultaneamente.
   - Preparar un portafolio de hipotesis y formatos: UGC, fotos reales, demostracion, prueba, estaticos, carrusel o movimiento segun la oferta. Image 2 es una herramienta, no la estrategia.
   - Recomendar varias perspectivas creativas y guardar extras en backlog si el presupuesto no permite probarlas todas a la vez.
   - Recordar el bonus incluido para crear videos UGC con ElevenLabs y preguntar si el cliente ya tiene cuenta.
   - Guardar contexto con `save_ads_onboarding`.
   - Crear briefs por promocion, campana, conjunto o anuncio con `save_ad_brief`.

4. continuous_ads_manager
   - Usar metricas, memoria de decisiones, guias de marca, referencias, briefs y contexto de campanas para responder como manager coherente.
   - Si no hay accion clara, decir que conviene esperar y que senal revisar despues.
   - Si hay accion clara, preparar o ejecutar bajo las reglas del backend.

## Estado resumido

- Negocio: {phase["business"]}
- Branding/creativos: {phase["branding"]}
- Campanas/anuncios previos: {phase["campaigns"]}

## Preparacion creativa actual

- Lista para estrategia: {"si" if phase["creative_readiness"]["ready"] else "no"}
- Presupuesto de prueba guardado: {phase["creative_readiness"]["budget"] or "pendiente"}
- Pendientes: {", ".join(item.get("key", "") for item in phase["creative_readiness"]["missing"]) or "ninguno"}
- Proxima pregunta exacta: {phase["creative_readiness"]["next_question"] or "ninguna"}
"""
    AGENT_ONBOARDING_PLAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    AGENT_ONBOARDING_PLAN_FILE.write_text(body, encoding="utf-8")
    return {"path": str(AGENT_ONBOARDING_PLAN_FILE), **phase}


def write_onboarding_questions_memory(profile=None, status="pending"):
    profile = profile if isinstance(profile, dict) else read_json(BUSINESS_PROFILE_FILE, {})
    if not isinstance(profile, dict):
        profile = {}
    status = str(status or "pending").strip().lower()
    links = []
    if profile.get("website_url"):
        links.append(str(profile.get("website_url")))
    for item in profile.get("social_links") or []:
        if item:
            links.append(str(item))
    business_hint = str(profile.get("business_type") or profile.get("business_short") or "negocio por entender").strip()
    link_block = "\n".join(f"- {link}" for link in links) or "- No hay links guardados todavia."
    if status == "completed":
        body = f"""# Onboarding questions

Estado: completado.

El cliente ya compartio suficiente contexto inicial. Usa `dashboard/data/business_profile.json`, `brand_guides/general_branding.md`, las fichas de producto y los briefs publicitarios para responder con memoria real.

Si el cliente pide revisar su negocio desde cero, vuelve a preguntar una cosa a la vez y actualiza la memoria con las herramientas disponibles.
"""
    else:
        body = f"""# Onboarding questions

Estado: todavia no preguntado al cliente.

Cuando el cliente escriba por Telegram o por el chat del dashboard, empieza una entrevista corta y amable para entender su negocio antes de recomendar anuncios.

Primer mensaje obligatorio:
- Explica brevemente que el proceso tiene 3 partes:
  1. entender el negocio,
  2. definir la marca visual/branding,
  3. convertir eso en ofertas, estrategia y anuncios.
- Despues de explicarlo, pregunta si tiene experiencia creando/gestionando anuncios y si quiere detalles tecnicos profundos o palabras simples.
- Guarda esa preferencia global con `save_agent_preferences` / `mcp_admira_save_agent_preferences`.
- Despues haz solo una pregunta de negocio.
- Primera pregunta de negocio recomendada: "Que vendes exactamente y cual es tu oferta principal hoy?"

Instrucciones para el agente:
- Habla en espanol latino natural, como manager calido y directo.
- Haz una sola pregunta a la vez.
- No hagas una lista enorme de preguntas en un solo mensaje.
- Actua como experto proactivo en todo lo que impacte el resultado: medicion, evento correcto, presupuesto, calendario, audiencias, exclusiones, ubicaciones, formato creativo, diagnosticos, aprobaciones y seguimiento. No esperes a que el cliente sepa pedir esas configuraciones.
- Usa los links guardados como contexto, pero deja que el cliente corrija todo.
- Documenta lo aprendido en el perfil del negocio y en las guias de marca/producto/brief cuando corresponda.
- Si falta informacion, pregunta lo minimo necesario para poder actuar.
- Cuando el negocio este claro, pasa a la fase de branding/creativos; no saltes directo a campanas si faltan estilo, referencias, colores o reglas visuales.
- Despues de branding, pregunta por anuncios/campanas anteriores y guarda aprendizajes antes de proponer la estrategia inicial.
- Antes de crear o preparar una campana, pregunta por los 3 resultados principales que importan para juzgarla, no solo por un evento. Ejemplos: ROAS, costo por compra, costo por iniciar checkout, costo por lead calificado, reservas o conversaciones reales de WhatsApp.

Preguntas que debes cubrir poco a poco:
1. Que vende exactamente y cual es su oferta principal.
2. Que productos o servicios quiere priorizar.
3. Quien compra o quien deberia comprar.
4. En que etapa esta ahora: empezando, ya vende, ya corre anuncios, o quiere escalar.
5. Que le duele hoy: costo alto, poco ROAS, no entiende Ads Manager, falta de creativos, pocas ventas, etc.
6. Que quiere lograr en 30 dias.
7. Que tono y estilo visual quiere para sus anuncios.

Despues de estas preguntas:
- Usa `save_business_context`.
- Luego usa el skill `branding creatives creation`.
- Luego usa `save_ads_onboarding`.
- Solo despues propone una estrategia inicial robusta pero clara.

Contexto inicial guardado:
- Tipo de negocio: {business_hint}
- Links para revisar:
{link_block}
"""
    ONBOARDING_QUESTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ONBOARDING_QUESTIONS_FILE.write_text(body, encoding="utf-8")
    write_agent_onboarding_plan(profile)
    return {"path": str(ONBOARDING_QUESTIONS_FILE), "status": status}


SOCIAL_PROFILE_DOMAINS = (
    "instagram.com",
    "facebook.com",
    "fb.com",
    "tiktok.com",
    "wa.me",
    "whatsapp.com",
    "youtube.com",
    "linkedin.com",
    "x.com",
    "twitter.com",
    "threads.net",
)


def is_social_profile_url(value):
    lower = str(value or "").lower()
    return any(domain in lower for domain in SOCIAL_PROFILE_DOMAINS)


def classify_business_links(links):
    website = next((link for link in links if not is_social_profile_url(link)), "")
    social_links = [link for link in links if link != website]
    return website, social_links


def save_business_links_for_agent(payload):
    profile = read_json(BUSINESS_PROFILE_FILE, {})
    if not isinstance(profile, dict):
        profile = {}
    raw_links = []
    for key in ("website_url", "social_links", "links"):
        value = payload.get(key)
        if isinstance(value, list):
            raw_links.extend(value)
        elif value:
            raw_links.extend(str(value).replace(",", "\n").splitlines())
    links = []
    for raw in raw_links:
        value = str(raw or "").strip()
        if not value:
            continue
        if not re.match(r"^https?://", value, re.I):
            value = f"https://{value}"
        try:
            validate_public_website_url(value)
        except ValueError as exc:
            raise ValueError("Pega solo links publicos de tu web o redes sociales.") from exc
        if value not in links:
            links.append(value[:300])
        if len(links) >= 8:
            break
    business_type = str(payload.get("business_type") or payload.get("business_short") or "").strip()
    if business_type:
        profile["business_type"] = business_type[:220]
        profile["business_short"] = business_type[:220]
    if links:
        website, social_links = classify_business_links(links)
        profile["social_links"] = social_links
        if website:
            profile["website_url"] = website
            save_setup_config({"landing_url": website})
        profile["website_skipped"] = False
        profile, scan_source = enrich_business_links_with_agent(links, profile, business_type)
        profile["source"] = scan_source or profile.get("source") or "links_for_agent_scan"
    elif payload.get("website_skipped"):
        profile["website_skipped"] = True
    profile["onboarding_questions_started"] = False
    profile["telegram_onboarding_requested_at"] = now_iso()
    profile.setdefault("source", "links_for_agent_scan")
    if not profile.get("initial_plan"):
        profile["initial_plan"] = [
            "Revisar los links guardados.",
            "Entrevistar al cliente por Telegram con una pregunta a la vez.",
            "Guardar oferta, cliente ideal, estilo y objetivo antes de preparar campanas.",
        ]
    profile["updated_at"] = now_iso()
    write_json(BUSINESS_PROFILE_FILE, profile)
    memory = write_onboarding_questions_memory(profile, "pending")
    log_action("business_links_save", {"links_count": len(links), "interview_memory": memory["status"]}, "completed")
    return {"saved": True, "profile": profile, "onboarding_questions": memory}


def save_business_context(payload):
    profile = read_json(BUSINESS_PROFILE_FILE, {})
    if not isinstance(profile, dict):
        profile = {}
    for field in ["website_url", "business_type", "business_short", "current_stage", "what_to_improve", "main_offer", "ideal_customer", "offer", "audience", "sales_channel", "current_ads", "biggest_blocker", "success_goal", "budget_comfort", "brand_tone"]:
        if field in payload:
            profile[field] = str(payload.get(field) or "").strip()
    if "website_skipped" in payload:
        profile["website_skipped"] = bool(payload.get("website_skipped"))
        profile["onboarding_questions_started"] = True
    if payload.get("website_url"):
        profile["website_url"] = normalize_website_url(payload.get("website_url"))
        profile["website_skipped"] = False
        save_setup_config({"landing_url": profile["website_url"]})
    if not profile.get("initial_plan"):
        context = " ".join(
            str(profile.get(key) or "")
            for key in ["current_stage", "what_to_improve", "main_offer", "ideal_customer"]
        ).strip()
        profile.update(infer_business_profile(profile.get("website_url", ""), WebsiteSummaryParser(), context))
    if profile.get("main_offer") and not profile.get("offer"):
        profile["offer"] = profile["main_offer"]
    if profile.get("ideal_customer") and not profile.get("audience"):
        profile["audience"] = profile["ideal_customer"]
    context_fields = ["main_offer", "ideal_customer", "current_stage", "what_to_improve"]
    if payload.get("context_complete") and all(str(profile.get(key) or "").strip() for key in context_fields):
        profile["context_completed_at"] = now_iso()
    profile.setdefault("source", "manual_context")
    profile["updated_at"] = now_iso()
    write_json(BUSINESS_PROFILE_FILE, profile)
    if profile.get("context_completed_at"):
        write_onboarding_questions_memory(profile, "completed")
    write_agent_onboarding_plan(profile)
    log_action("business_context_save", {"website_url": profile.get("website_url"), "fields": sorted(payload.keys())}, "completed")
    return {"saved": True, "profile": profile}


def save_ads_campaign_onboarding(payload):
    profile = read_json(BUSINESS_PROFILE_FILE, {})
    if not isinstance(profile, dict):
        profile = {}
    allowed = [
        "promoted_before",
        "previous_ads_results",
        "current_campaign_context",
        "campaign_goal",
        "campaign_constraints",
        "budget_comfort",
        "countries",
        "offers_to_promote",
        "lessons_learned",
        "first_strategy",
        "primary_success_metric",
        "secondary_success_metric",
        "tertiary_success_metric",
    ]
    changed = {}
    for key in allowed:
        value = str(payload.get(key) or "").strip()
        if value:
            profile[key] = value[:1600]
            changed[key] = profile[key]
    success_metrics = normalize_success_metrics(payload)
    explicit_success_metric_keys = {
        "success_metrics",
        "success_metrics_json",
        "priority_metrics",
        "priority_results",
        "key_results",
        "important_results",
        "main_results",
        "desired_results",
        "top_results",
        "top_3_results",
        "kpis",
        "primary_metrics",
        "conversion_results",
        "primary_success_metric",
        "secondary_success_metric",
        "tertiary_success_metric",
        "primary_kpi",
        "secondary_kpi",
        "tertiary_kpi",
        "primary_result",
        "secondary_result",
        "tertiary_result",
    }
    if any(payload.get(key) for key in explicit_success_metric_keys):
        profile["success_metrics"] = success_metrics
        changed["success_metrics"] = json.dumps(success_metrics.get("items", []), ensure_ascii=False)
    completion_ready = all(str(profile.get(key) or "").strip() for key in ["campaign_goal", "budget_comfort", "first_strategy"])
    if (payload.get("ads_onboarding_complete") or payload.get("completed")) and completion_ready:
        profile["ads_onboarding_completed_at"] = now_iso()
    profile["updated_at"] = now_iso()
    write_json(BUSINESS_PROFILE_FILE, profile)
    body = f"""# Ads campaign onboarding

Usa este archivo para recordar lo que el cliente ya intento en anuncios y que estrategia inicial conviene.

## Historial

- Ha promovido antes: {profile.get('promoted_before', '')}
- Resultados anteriores: {profile.get('previous_ads_results', '')}
- Contexto actual de campanas: {profile.get('current_campaign_context', '')}
- Aprendizajes: {profile.get('lessons_learned', '')}

## Objetivo y limites

- Meta principal: {profile.get('campaign_goal', '')}
- 3 resultados principales/KPIs: {json.dumps((profile.get('success_metrics') or {}).get('items', []), ensure_ascii=False) if isinstance(profile.get('success_metrics'), dict) else profile.get('success_metrics', '')}
- Presupuesto comodo: {profile.get('budget_comfort', '')}
- Paises o zonas: {profile.get('countries', '')}
- Ofertas a promover: {profile.get('offers_to_promote', '')}
- Restricciones: {profile.get('campaign_constraints', '')}

## Primera estrategia

{profile.get('first_strategy') or 'Pendiente de preparar despues de entender negocio, marca y campanas previas.'}

Estado: {'completado' if profile.get('ads_onboarding_completed_at') else 'pendiente'}
"""
    ADS_ONBOARDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    ADS_ONBOARDING_FILE.write_text(body, encoding="utf-8")
    write_agent_onboarding_plan(profile)
    log_action("ads_campaign_onboarding_save", {"fields": sorted(changed.keys()), "completed": bool(profile.get("ads_onboarding_completed_at"))}, "completed")
    return {"saved": True, "profile": profile, "path": str(ADS_ONBOARDING_FILE), "phase": agent_onboarding_phase(profile)}


def initialize_brand_guides(payload):
    product_name = str(payload.get("product_name") or "").strip() or "Oferta principal"
    result = ensure_brand_guides(product_name)
    write_agent_onboarding_plan()
    log_action("brand_guides_init", {"product_name": product_name, "created": result.get("created", [])}, "completed")
    return result


def save_general_brand_memory(payload):
    result = save_general_guide(payload)
    write_agent_onboarding_plan()
    log_action("brand_general_save", {"brand_name": result.get("general", {}).get("fields", {}).get("brand_name", "")}, "completed")
    return result


def save_product_brand_memory(payload):
    result = save_product_guide(payload)
    write_agent_onboarding_plan()
    product = next(
        (item for item in result["library"].get("products", []) if item.get("id") == result.get("product_id")),
        {},
    )
    log_action("brand_product_save", {"product_id": result.get("product_id"), "name": product.get("name", "")}, "completed")
    return result


def save_ad_brief_memory(payload):
    result = save_ad_brief(payload)
    write_agent_onboarding_plan()
    brief = next(
        (item for item in result["library"].get("ad_briefs", []) if item.get("id") == result.get("ad_brief_id")),
        {},
    )
    log_action("ad_brief_save", {"ad_brief_id": result.get("ad_brief_id"), "name": brief.get("name", "")}, "completed")
    return result


def save_creative_references_memory(payload):
    result = save_creative_references(payload)
    write_agent_onboarding_plan()
    log_action("creative_references_save", {"path": result.get("creative_references", "")}, "completed")
    return result


def codex_creative_plan(payload):
    payload = payload or {}
    brief_payload = normalize_ad_brief_payload(payload)
    product_guide = str(brief_payload.get("product_guide") or payload.get("product_guide") or "").strip()
    if not product_guide:
        product_guide = direct_product_guide_text(payload)
    if not product_guide:
        product_guide = business_profile_product_context()
    request = str(payload.get("request") or "").strip()
    mode = str(payload.get("mode") or payload.get("image_mode") or "fixed").strip().lower()
    variations = payload.get("variations") or brief_payload.get("variation_count") or 3
    if not request:
        request = "Crear una estrategia visual y prompts de imagen para Meta Ads usando las guias de marca."
    context = creative_direct_context(payload)
    if context and context not in request:
        request = f"{request}\n\n{context}"
    purpose = str(payload.get("purpose") or "ad_creative").strip().lower()
    readiness = creative_strategy_readiness(require_brief=False, purpose=purpose, payload=payload)
    if not readiness["ready"]:
        result = creative_not_ready_result("creative_strategy_not_ready", readiness)
        log_action(
            "codex_creative_plan",
            {"product_guide": product_guide, "mode": mode, "variations": variations, "ok": False, "reason": result["reason"], "missing": result["missing"]},
            "blocked",
        )
        return result
    config = load_config()
    if not getattr(config, "codex_creative_enabled", False):
        result = {
            "ok": False,
            "error": "La capa opcional de Codex CLI esta desactivada. Actívala solo si aceptas que Codex CLI es un agente local con acceso adicional al equipo.",
        }
        log_action("codex_creative_plan", {"product_guide": product_guide, "ok": False, "error": result["error"]}, "blocked")
        return result
    try:
        ad_brief = str(payload.get("ad_brief") or "").strip()
        prompt_package = build_codex_image_prompt_package(
            product_guide=product_guide,
            request=request,
            ad_brief=ad_brief,
            mode=mode,
            variations=variations,
            seed=str(payload.get("seed") or "").strip() or None,
        )
        result = call_codex_cli(prompt_package["codex_prompt"], model=getattr(config, "codex_creative_model", ""))
        result["prompt_package"] = {
            "mode": prompt_package["mode"],
            "seed": prompt_package["seed"],
            "variation_count": prompt_package["variation_count"],
            "variation_ledger": prompt_package["variation_ledger"],
            "prompts": prompt_package["prompts"],
            "product_guide": prompt_package["product_guide"],
            "ad_brief": prompt_package["ad_brief"],
        }
    except ValueError as exc:
        result = {"ok": False, "error": str(exc)}
    log_action("codex_creative_plan", {"product_guide": product_guide, "mode": mode, "variations": variations, "ok": result.get("ok"), "error": result.get("error", "")}, "completed" if result.get("ok") else "blocked")
    return result


def codex_image_generate(payload):
    """Generate a raster creative through the Codex/Image bridge."""
    payload = payload or {}
    brief_payload = normalize_ad_brief_payload(payload)
    product_guide = str(brief_payload.get("product_guide") or payload.get("product_guide") or "").strip()
    if not product_guide:
        product_guide = direct_product_guide_text(payload)
    if not product_guide:
        product_guide = business_profile_product_context()
    ad_brief = str(payload.get("ad_brief") or "").strip()
    mode = str(payload.get("mode") or payload.get("image_mode") or "fixed").strip().lower()
    variations = payload.get("variations") or brief_payload.get("variation_count") or 1
    request = str(payload.get("request") or payload.get("image_prompt") or payload.get("prompt") or "").strip()
    if not request:
        request = "Crear una imagen final para Meta Ads usando las guias de marca disponibles."
    context = creative_direct_context(payload)
    if context and context not in request:
        request = f"{request}\n\n{context}"
    purpose = str(payload.get("purpose") or "ad_creative").strip().lower()
    require_brief = creative_image_requires_brief(payload, purpose)
    readiness = creative_strategy_readiness(require_brief=require_brief, purpose=purpose, payload=payload)
    if not readiness["ready"]:
        result = creative_not_ready_result("creative_production_not_ready", readiness)
        log_action(
            "codex_image_generate",
            {"product_guide": product_guide, "ad_brief": ad_brief, "mode": mode, "require_brief": require_brief, "ok": False, "reason": result["reason"], "missing": result["missing"]},
            "blocked",
        )
        return result
    try:
        prompt_package = build_codex_image_prompt_package(
            product_guide=product_guide,
            request=request,
            ad_brief=ad_brief,
            mode=mode,
            variations=variations,
            seed=str(payload.get("seed") or "").strip() or None,
        )
        selected_prompt = (prompt_package.get("prompts") or [{}])[0]
        image_prompt = (
            f"{selected_prompt.get('image_prompt') or request}\n\n"
            f"Pedido puntual del comprador: {request}\n\n"
            f"Modo creativo: {prompt_package.get('mode')}\n"
            f"Eje visual: {selected_prompt.get('design_axis') or ''}\n"
            f"Composicion: {selected_prompt.get('composition') or ''}\n"
            f"Experimento: {selected_prompt.get('experiment') or ''}\n"
        )
        if payload.get("reference_image_summary"):
            image_prompt += f"\nReferencia visual descrita por el agente: {payload.get('reference_image_summary')}\n"
        reference_paths = safe_image_paths(payload)
        background_prompt_lock = reference_background_prompt_lock(reference_paths, payload, request)
        if background_prompt_lock:
            image_prompt += background_prompt_lock
        official_logo = official_brand_logo_path()
        brand_fields = (guide_library().get("general") or {}).get("fields") or {}
        include_logo_value = payload.get("include_logo")
        if include_logo_value is None:
            request_lower = request.lower()
            logo_usage = str(brand_fields.get("logo_usage") or "").lower()
            include_logo = bool(
                official_logo
                and not logo_text_disables_official_use(request_lower)
                and not logo_text_disables_official_use(logo_usage)
            )
        else:
            include_logo = str(include_logo_value).strip().lower() in {"1", "true", "yes", "si", "sí", "on"}
        logo_position = str(payload.get("logo_position") or "top-right").strip().lower()
        logo_background = str(payload.get("logo_background") or "auto").strip().lower()
        logo_render_mode = str(payload.get("logo_render_mode") or "protected_context").strip().lower()
        if logo_render_mode in {"context", "direct", "model"}:
            logo_render_mode = "protected_context"
        elif logo_render_mode in {"composite", "overlay", "post_process"}:
            logo_render_mode = "exact_composite"
        if logo_render_mode not in {"protected_context", "exact_composite"}:
            raise ValueError("logo_render_mode debe ser protected_context o exact_composite.")
        if include_logo and not official_logo:
            raise ValueError("El brief pide usar el logo, pero todavía no hay un archivo oficial guardado. Pide al comprador que lo suba; no generes uno parecido.")
        if include_logo and official_logo:
            if str(official_logo) not in reference_paths:
                reference_paths = [*reference_paths, str(official_logo)]
            if logo_render_mode == "protected_context":
                image_prompt += f"\n{official_logo_prompt_lock(logo_position)}\n"
            else:
                image_prompt += (
                    "\nMODO DE RESPALDO CON COMPOSICIÓN EXACTA: el logo oficial está adjunto solo como contexto de marca. "
                    f"No dibujes, imites ni incluyas ningún logo en la imagen base. Deja una zona limpia en {logo_position} "
                    "para que el producto aplique después el archivo oficial exacto.\n"
                )
        result = call_codex_image_cli(
            image_prompt,
            model=load_config().codex_creative_model,
            output_root=CREATIVE_ASSET_ROOT,
            output_name=payload.get("output_name") or selected_prompt.get("variant_id") or "meta-ad-creative",
            reference_image_paths=reference_paths,
        )
        if result.get("ok") and include_logo and official_logo and logo_render_mode == "exact_composite" and result.get("image_path"):
            result["official_logo"] = composite_official_logo(
                result["image_path"],
                official_logo,
                position=logo_position,
                background=logo_background,
            )
            if not result["official_logo"].get("applied"):
                result["warning"] = result["official_logo"].get("error") or "No pude aplicar el logo oficial exacto."
        result["prompt_package"] = {
            "mode": prompt_package["mode"],
            "seed": prompt_package["seed"],
            "variation_count": prompt_package["variation_count"],
            "variation_ledger": prompt_package["variation_ledger"],
            "product_guide": prompt_package["product_guide"],
            "ad_brief": prompt_package["ad_brief"],
            "selected_prompt": selected_prompt,
            "logo_context": prompt_package.get("logo_context", ""),
            "reference_image_count": len(reference_paths),
            "include_logo": bool(include_logo and official_logo),
            "logo_render_mode": logo_render_mode if include_logo and official_logo else "none",
            "logo_protection": "exact_prompt_lock" if include_logo and official_logo and logo_render_mode == "protected_context" else ("deterministic_composite" if include_logo and official_logo else "none"),
            "reference_image_role": "real_photo_background" if background_prompt_lock else ("reference" if reference_paths else "none"),
            "requires_full_ad_brief": require_brief,
        }
        if result.get("asset_id"):
            result["preview_url"] = f"/api/creative-asset?id={urllib.parse.quote(str(result['asset_id']))}"
    except ValueError as exc:
        result = {"ok": False, "error": str(exc)}
    log_action(
        "codex_image_generate",
        {
            "product_guide": product_guide,
            "ad_brief": ad_brief,
            "mode": mode,
            "require_brief": require_brief,
            "ok": result.get("ok"),
            "asset_id": result.get("asset_id", ""),
            "error": result.get("error", ""),
        },
        "completed" if result.get("ok") else "blocked",
    )
    return result


def creative_asset_path(asset_id):
    relative = Path(str(asset_id or "").strip())
    if not str(relative) or relative.is_absolute() or relative.suffix.lower() not in CREATIVE_ASSET_EXTENSIONS:
        raise ValueError("No encontré esa imagen creativa.")
    candidate = (CREATIVE_ASSET_ROOT / relative).resolve()
    try:
        candidate.relative_to(CREATIVE_ASSET_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("No encontré esa imagen creativa.") from exc
    if not candidate.exists() or not candidate.is_file():
        raise ValueError("No encontré esa imagen creativa.")
    return candidate


def brand_logo_extension(filename="", content_type=""):
    ext = Path(str(filename or "")).suffix.lower()
    if ext not in BRAND_LOGO_EXTENSIONS:
        ext = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/webp": ".webp",
        }.get(str(content_type or "").split(";")[0].strip().lower(), "")
    if ext not in BRAND_LOGO_EXTENSIONS:
        raise ValueError("Sube tu logo en PNG, JPG o WebP.")
    return ext


def brand_logo_bytes_look_valid(raw, ext):
    if not raw:
        return False
    if ext == ".png":
        return raw.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in {".jpg", ".jpeg"}:
        return raw.startswith(b"\xff\xd8")
    if ext == ".webp":
        return raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"
    return False


def store_brand_logo_bytes(raw, ext, original_name="logo"):
    if len(raw) > MAX_BRAND_LOGO_BYTES:
        raise ValueError("Ese logo pesa demasiado. Usa una imagen menor a 1 MB.")
    if not brand_logo_bytes_look_valid(raw, ext):
        raise ValueError("No pude confirmar que ese archivo sea una imagen válida.")
    BRAND_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", Path(str(original_name or "logo")).stem.lower()).strip("-") or "logo"
    digest = hashlib.sha256(raw).hexdigest()[:10]
    target = BRAND_ASSET_DIR / f"{slug[:34]}-{digest}{ext}"
    target.write_bytes(raw)
    return product_reference(target)


def copy_brand_logo_from_path(source_path, logo_notes=""):
    source = Path(str(source_path or "")).expanduser()
    if not source.exists() or not source.is_file():
        raise ValueError("No encontré la imagen del logo.")
    ext = brand_logo_extension(source.name, mimetypes.guess_type(source.name)[0] or "")
    raw = source.read_bytes()
    relative = store_brand_logo_bytes(raw, ext, source.name)
    return {
        "logo_path": relative,
        "logo_notes": str(logo_notes or "").strip() or "Logo enviado por el comprador en el chat.",
        "logo_usage": "Usar el logo oficial guardado en futuros creativos salvo que el comprador pida explícitamente sin logo.",
    }


def save_brand_logo_asset(payload):
    data_url = str((payload or {}).get("data_url") or "").strip()
    if not data_url or "," not in data_url:
        raise ValueError("Sube una imagen de logo.")
    header, encoded = data_url.split(",", 1)
    content_type = str((payload or {}).get("content_type") or "")
    if "image/" in header and not content_type:
        content_type = header.split(";", 1)[0].removeprefix("data:")
    ext = brand_logo_extension((payload or {}).get("filename") or "logo", content_type)
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("No pude leer esa imagen de logo.") from exc
    relative = store_brand_logo_bytes(raw, ext, (payload or {}).get("filename") or "logo")
    existing = (guide_library().get("general", {}) or {}).get("fields", {}) or {}
    update = dict(existing)
    update["logo_path"] = relative
    if (payload or {}).get("logo_notes"):
        update["logo_notes"] = str((payload or {}).get("logo_notes") or "").strip()
    elif not update.get("logo_notes"):
        update["logo_notes"] = "Logo oficial subido por el comprador. Usarlo como referencia visual de marca."
    if not update.get("brand_name") and not update.get("offer"):
        update["brand_name"] = "Marca principal"
    usage_lower = str(update.get("logo_usage") or "").strip().lower()
    if not usage_lower or any(phrase in usage_lower for phrase in ["hasta tener archivo oficial", "until official", "no usar hasta"]):
        update["logo_usage"] = "Usar el logo oficial guardado en futuros creativos salvo que el comprador pida explícitamente sin logo."
    library = save_general_brand_memory(update)
    return {
        "saved": True,
        "logo_path": relative,
        "preview_url": f"/api/brand-asset?id={urllib.parse.quote(relative)}",
        "library": library,
    }


def brand_asset_path(asset_id):
    relative = Path(urllib.parse.unquote(str(asset_id or "").strip()))
    if not str(relative) or relative.is_absolute() or relative.suffix.lower() not in BRAND_LOGO_EXTENSIONS:
        raise ValueError("No encontré ese logo.")
    if relative.parts[:2] == ("brand_guides", "assets"):
        candidate = (ROOT_DIR / relative).resolve()
    else:
        candidate = (BRAND_ASSET_DIR / relative).resolve()
    try:
        candidate.relative_to(BRAND_ASSET_DIR.resolve())
    except ValueError as exc:
        raise ValueError("No encontré ese logo.") from exc
    if not candidate.exists() or not candidate.is_file():
        raise ValueError("No encontré ese logo.")
    return candidate


def public_asset_path(asset_id):
    relative = Path(urllib.parse.unquote(str(asset_id or "").strip()))
    if not str(relative) or relative.is_absolute() or relative.suffix.lower() not in PUBLIC_ASSET_EXTENSIONS:
        raise ValueError("No encontré ese recurso.")
    candidate = (PUBLIC_ASSETS_DIR / relative).resolve()
    try:
        candidate.relative_to(PUBLIC_ASSETS_DIR.resolve())
    except ValueError as exc:
        raise ValueError("No encontré ese recurso.") from exc
    if not candidate.exists() or not candidate.is_file():
        raise ValueError("No encontré ese recurso.")
    return candidate


def creative_asset_summary(asset, refresh_id):
    path = Path(str(asset.get("path") or ""))
    if not path.exists() or not path.is_file() or path.suffix.lower() not in CREATIVE_ASSET_EXTENSIONS:
        return None
    try:
        relative = path.resolve().relative_to(CREATIVE_ASSET_ROOT.resolve())
    except ValueError:
        return None
    if not relative.parts or relative.parts[0] != refresh_id:
        return None
    storage = asset_storage_state(asset)
    return {
        "aspect_ratio": str(asset.get("aspect_ratio") or ""),
        "mime_type": str(asset.get("mime_type") or mimetypes.guess_type(path.name)[0] or "image/png"),
        "preview_url": f"/api/creative-asset?id={urllib.parse.quote(str(relative))}",
        "filename": path.name,
        "storage": storage,
        "retention": storage,
        "temporary": not bool(storage.get("saved")),
        "saved_for_ad": bool(storage.get("saved")),
        "expires_at": storage.get("expires_at", ""),
        "days_remaining": storage.get("days_remaining"),
    }


def creative_studio_items(limit=8):
    items = []
    for summary in recent_creative_refreshes(limit):
        manifest = read_json(Path(summary.get("manifest_path") or ""), {})
        if not isinstance(manifest, dict) or not manifest.get("id"):
            continue
        variants = []
        for variant in manifest.get("variants", [])[:6]:
            assets = [
                safe_asset
                for safe_asset in (
                    creative_asset_summary(asset, manifest["id"])
                    for asset in variant.get("assets", [])
                )
                if safe_asset
            ]
            errors = [
                str(asset.get("error") or "")[:180]
                for asset in variant.get("assets", [])
                if asset.get("error")
            ]
            variants.append({
                "variant_id": str(variant.get("variant_id") or ""),
                "copy": variant.get("copy", {}),
                "image_prompts": variant.get("image_prompts", [])[:3],
                "assets": assets,
                "has_generated_image": bool(assets),
                "generation_errors": errors,
            })
        items.append({
            **summary,
            "provider": manifest.get("provider", ""),
            "image_mode": manifest.get("image_mode", ""),
            "brand_memory": manifest.get("brand_memory", {}),
            "variants": variants,
            "has_generated_images": any(item["has_generated_image"] for item in variants),
            "requires_approval": bool(manifest.get("upload_policy", {}).get("requires_approval", True)),
        })
    return items


def creative_asset_policy(cleanup=None):
    items = creative_studio_items(25)
    temporary = 0
    saved = 0
    for batch in items:
        for variant in batch.get("variants", []):
            for asset in variant.get("assets", []):
                if asset.get("saved_for_ad"):
                    saved += 1
                elif asset.get("temporary"):
                    temporary += 1
    return {
        "storage_policy": CREATIVE_IMAGE_STORAGE_POLICY,
        "temporary_image_count": temporary,
        "saved_ad_image_count": saved,
        "cleanup": cleanup or {},
    }


def creative_upload_studio_items(limit=8):
    items = []
    for summary in recent_uploads(limit):
        payload = read_json(Path(summary.get("payload_path") or ""), {})
        items.append({
            **summary,
            "missing_requirements": payload.get("missing_requirements", []),
            "selected_ratios": payload.get("selected_ratios", []),
        })
    return items


def load_onboarding_state():
    state = read_json(ONBOARDING_FILE, {})
    if not isinstance(state, dict):
        state = {}
    state.setdefault("completed", False)
    state.setdefault("skipped", False)
    state.setdefault("deferred", False)
    state.setdefault("deferred_reasons", [])
    state.setdefault("completed_at", "")
    state.setdefault("completed_by", "")
    state.setdefault("communication_style", "")
    state.setdefault("ad_experience_level", "")
    state.setdefault("setup_snapshot", {})
    return state


def dashboard_setup_deferred_reasons(reasons):
    return [reason for reason in (reasons or []) if reason in DASHBOARD_SETUP_DEFERRED_REASONS and reason not in AGENT_INTERVIEW_DEFERRED_REASONS]


def save_agent_preferences(payload, restart_gateway=True):
    payload = payload or {}
    raw_style = str(payload.get("communication_style") or "").strip().lower()
    raw_experience = str(payload.get("ad_experience_level") or payload.get("ads_experience_level") or payload.get("ads_experience") or "").strip().lower()
    style = normalize_communication_style(raw_style, default="") if raw_style else communication_style_from_environment(default="")
    ad_experience = normalize_ad_experience_level(raw_experience, default="") if raw_experience else ad_experience_from_environment(default="")
    if raw_style and not style:
        raise ValueError("Elige si prefieres palabras simples o explicaciones técnicas.")
    if raw_experience and not ad_experience:
        raise ValueError("Elige si la experiencia en anuncios es principiante, intermedia o avanzada.")
    if not style and not ad_experience:
        raise ValueError("Elige al menos una preferencia del agente.")
    updates = {}
    if style:
        updates["AGENT_COMMUNICATION_STYLE"] = style
    if ad_experience:
        updates["AGENT_AD_EXPERIENCE_LEVEL"] = ad_experience
    update_env_values(updates)
    if ONBOARDING_FILE.exists():
        state = load_onboarding_state()
        if style:
            state["communication_style"] = style
        if ad_experience:
            state["ad_experience_level"] = ad_experience
        write_json(ONBOARDING_FILE, state)
    if restart_gateway:
        config = load_config()
        gateway = start_hermes_gateway(config)
    else:
        gateway = {
            "started": False,
            "mode": "hermes_gateway",
            "restart_deferred": True,
            "detail": "Preference saved without restarting the active Telegram gateway.",
        }
    log_action("agent_preferences_update", {"communication_style": style, "ad_experience_level": ad_experience}, "completed")
    return {
        "saved": True,
        "ad_experience_level": ad_experience,
        "ad_experience_instruction": ad_experience_instruction(ad_experience, (payload or {}).get("language") or "es"),
        "communication_preference": {
            **communication_preference(style, (payload or {}).get("language") or "es", ad_experience_level=ad_experience),
            "configured": communication_style_is_configured(),
            "ad_experience_configured": ad_experience_is_configured(),
        },
        "gateway": gateway,
    }


def save_communication_style(payload):
    raw_style = str((payload or {}).get("communication_style") or "").strip().lower()
    if not normalize_communication_style(raw_style, default=""):
        raise ValueError("Elige si prefieres palabras simples o explicaciones técnicas.")
    result = save_agent_preferences(payload)
    log_action("communication_style_update", {"communication_style": result.get("communication_preference", {}).get("style")}, "completed")
    return result


def complete_onboarding(payload=None):
    payload = payload or {}
    requested_style = str(payload.get("communication_style") or "").strip().lower()
    requested_experience = str(payload.get("ad_experience_level") or payload.get("ads_experience_level") or "").strip().lower()
    communication_style = normalize_communication_style(requested_style, default="simple") if requested_style else communication_style_from_environment(default="simple")
    ad_experience = normalize_ad_experience_level(requested_experience, default="") if requested_experience else ad_experience_from_environment(default="")
    if requested_experience and not ad_experience:
        raise ValueError("Elige si la experiencia en anuncios es principiante, intermedia o avanzada.")
    updates = {}
    if requested_style:
        updates["AGENT_COMMUNICATION_STYLE"] = communication_style
    if requested_experience and ad_experience:
        updates["AGENT_AD_EXPERIENCE_LEVEL"] = ad_experience
    if updates:
        update_env_values(updates)
    config = load_config()
    if not dashboard_password_configured(config):
        raise ValueError("Create a dashboard password before finishing onboarding")
    license_info = license_status(config)
    if not license_info.get("valid"):
        raise ValueError("No se pudo confirmar tu licencia. Revisa internet o contacta soporte.")
    ad_config = read_json(AD_CONFIG_FILE, {})
    destination = ad_config.get("creative", {}).get("destination", {})
    if not config.meta_access_token:
        raise ValueError("Pega y guarda tu clave de Meta antes de terminar.")
    if not config.ad_account_id:
        raise ValueError("Elige tu cuenta publicitaria antes de terminar.")
    if not destination.get("page_id") or not destination.get("url"):
        raise ValueError("Elige tu pagina de Facebook y el link de tu web antes de terminar.")
    business_profile = read_json(BUSINESS_PROFILE_FILE, {})
    if not isinstance(business_profile, dict):
        business_profile = {}
    if not business_profile.get("website_url") and not business_profile.get("social_links"):
        write_onboarding_questions_memory(business_profile, "pending")
    setup = build_setup_status()
    insights_refresh = refresh_managed_real_metrics(reason="onboarding_complete") if config.ad_account_id and config.meta_access_token else {"ok": False, "saved": False, "reason": "missing_account_or_token"}
    metrics = load_metrics()
    if not insights_refresh.get("ok") and metrics.get("source") != "meta_graph":
        raise ValueError("Todavía no pude leer datos reales de Meta. Cambia tu clave o revisa sus permisos y vuelve a intentar.")
    state = {
        "completed": True,
        "skipped": False,
        "deferred": False,
        "deferred_reasons": [],
        "completed_at": now_iso(),
        "completed_by": "dashboard",
        "communication_style": communication_style,
        "ad_experience_level": ad_experience,
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
    mark_license_install_state(config, "onboarding_completed")
    gateway = start_hermes_gateway(config)
    state["communication_gateway_updated"] = bool(gateway.get("started")) if isinstance(gateway, dict) else bool(gateway)
    write_json(ONBOARDING_FILE, state)
    log_action("onboarding_complete", {"setup_summary": state["setup_snapshot"], "first_insights_refresh": state["first_insights_refresh"]}, "completed")
    return state


def skip_onboarding():
    config = load_config()
    if not dashboard_password_configured(config):
        raise ValueError("Crea primero la contraseña del dashboard.")
    business_profile = read_json(BUSINESS_PROFILE_FILE, {})
    if not isinstance(business_profile, dict):
        business_profile = {}
    communication_style = communication_style_from_environment()
    ad_experience = ad_experience_from_environment(default="")
    updates = {"AGENT_COMMUNICATION_STYLE": communication_style}
    if ad_experience:
        updates["AGENT_AD_EXPERIENCE_LEVEL"] = ad_experience
    update_env_values(updates)
    if not ONBOARDING_QUESTIONS_FILE.exists():
        write_onboarding_questions_memory(business_profile, "pending")
    missing = []
    if not license_status(config).get("valid"):
        missing.append("licencia")
    if not config.meta_access_token:
        missing.append("conexion_facebook")
    if not config.ad_account_id:
        missing.append("cuenta_publicitaria")
    if not (config.agent_chat_provider == "hermes" or config.agent_chat_api_key):
        missing.append("cerebro_agente")
    if not telegram_settings(config).get("chat_id"):
        missing.append("telegram")
    state = {
        "completed": True,
        "skipped": True,
        "deferred": True,
        "deferred_reasons": missing,
        "completed_at": now_iso(),
        "completed_by": "skip_and_complete_later",
        "communication_style": communication_style,
        "ad_experience_level": ad_experience,
        "setup_snapshot": build_setup_status().get("summary", {}),
        "business_profile_snapshot": redact_payload(business_profile),
    }
    write_json(ONBOARDING_FILE, state)
    start_hermes_gateway(config)
    log_action("onboarding_skip", {"deferred_reasons": missing}, "completed")
    return state


def reset_onboarding():
    if load_onboarding_state().get("completed") and not license_entitlements()["is_agency"]:
        save_individual_binding()
    state = {
        "completed": False,
        "skipped": False,
        "deferred": False,
        "deferred_reasons": [],
        "completed_at": "",
        "completed_by": "",
        "communication_style": communication_style_from_environment(default=""),
        "ad_experience_level": ad_experience_from_environment(default=""),
        "setup_snapshot": {},
        "reset_at": now_iso(),
    }
    write_json(ONBOARDING_FILE, state)
    log_action("onboarding_reset", {}, "completed")
    return state


def onboarding_health(state, config, metrics, current_license_status, destination, business_profile):
    """Guide a completed legacy install back through setup if its real connection is gone."""
    result = dict(state)
    result["deferred_reasons"] = dashboard_setup_deferred_reasons(result.get("deferred_reasons", []))
    if result.get("deferred") and not result["deferred_reasons"]:
        result["deferred"] = False
    result["requires_repair"] = False
    result["repair_reasons"] = []
    result.setdefault("deferred", bool(result.get("skipped")))
    result.setdefault("deferred_reasons", [])
    if not result.get("completed"):
        return result
    if result.get("skipped"):
        return result
    checks = [
        (current_license_status.get("valid"), "licencia"),
        (bool(config.meta_access_token), "conexion_meta"),
        (bool(config.ad_account_id), "cuenta_publicitaria"),
        (bool(destination.get("page_id")) and bool(destination.get("url")), "destinos"),
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


def empty_meta_metrics(reason="missing"):
    return {
        "timestamp": now_iso(),
        "source": reason,
        "source_label": "Sin datos reales de Meta",
        "campaigns": [],
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
    campaign["cpa"] = (spend / conversions) if conversions else 0.0
    campaign["cpc"] = (spend / clicks) if clicks else float(campaign.get("cpc", 0))
    campaign["roas"] = (revenue / spend) if spend else float(campaign.get("roas", 0))
    campaign.setdefault("previous_cpa", campaign["cpa"])
    campaign.setdefault("previous_ctr", campaign["ctr"] * 1.05)
    campaign.setdefault("previous_cpc", campaign["cpc"] * 0.92 if campaign["cpc"] else 0)
    campaign.setdefault("trend", [round(campaign["roas"] * v, 2) for v in [0.82, 0.88, 0.93, 0.96, 1.0, 1.03, 1.0]])
    campaign.setdefault("updated_at", now_iso())
    campaign["health"] = classify_campaign(campaign)
    return campaign


def classify_campaign(campaign):
    if str(campaign.get("status") or "").lower() == "paused":
        return "paused"
    ctr_drop = pct_change(campaign.get("ctr"), campaign.get("previous_ctr"))
    cpc_rise = pct_change(campaign.get("cpc"), campaign.get("previous_cpc"))
    cpa_rise = pct_change(campaign.get("cpa"), campaign.get("previous_cpa"))
    deterioration = ctr_drop <= -20 or cpc_rise >= 30 or cpa_rise >= 25
    frequency_with_deterioration = campaign.get("frequency", 0) > 3 and (ctr_drop <= -10 or cpc_rise >= 15 or cpa_rise >= 15)
    if deterioration or frequency_with_deterioration:
        return "fatigue"
    decision = portfolio_recommendations([campaign], load_profitability_rules())[0]
    if decision.get("decision") == "scale":
        return "winning"
    if decision.get("decision") in {"reduce", "pause_candidate"}:
        return "losing"
    return "neutral"


def load_metrics():
    metrics = read_json(METRICS_FILE, None)
    if metrics is None:
        metrics = empty_meta_metrics()
    if "source" not in metrics and looks_like_demo_metrics(metrics):
        metrics["source"] = "demo"
        metrics["source_label"] = "Demo data"
    if metrics.get("source") == "demo" and not env_bool("ADMIRO_ALLOW_DEMO_METRICS", False):
        metrics = empty_meta_metrics("missing")
    metrics.setdefault("source", "cached")
    metrics.setdefault("source_label", "Cached dashboard data")
    metrics["campaigns"] = [enrich_campaign({**c, "data_source": c.get("data_source") or metrics.get("source", "")}) for c in metrics.get("campaigns", [])]
    metrics["summary"] = build_summary(metrics["campaigns"])
    return metrics


def save_metrics(metrics):
    metrics["timestamp"] = now_iso()
    metrics.setdefault("source", "manual")
    metrics.setdefault("source_label", "Dashboard data")
    metrics["campaigns"] = [enrich_campaign({**c, "data_source": c.get("data_source") or metrics.get("source", "")}) for c in metrics.get("campaigns", [])]
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
    rules = load_profitability_rules()
    config = load_config()
    state = load_optimization_state()
    recommendations = []
    campaigns_by_id = {str(c.get("id") or c.get("campaign_id")): c for c in campaigns}
    for decision in portfolio_recommendations(campaigns, rules, state):
        campaign = campaigns_by_id.get(str(decision.get("campaign_id")), {})
        current_budget = float(decision.get("current_budget", 0))
        recommended_budget = float(decision.get("recommended_budget", current_budget))
        change = recommended_budget - current_budget
        change_pct = float(decision.get("change_pct", 0))
        recommendation = {
            "campaign_id": decision.get("campaign_id"),
            "campaign_name": decision.get("campaign_name"),
            "current_budget": money(current_budget),
            "recommended_budget": money(recommended_budget),
            "change": money(change),
            "change_pct": round(change_pct, 1),
            "confidence": 90 if decision.get("ready") else 0,
            "reason": decision.get("reason"),
            "proposal_only": decision.get("shadow_mode", True) and decision.get("action") != "observe",
            "requires_approval": decision.get("action") != "observe" and not decision.get("shadow_mode", True) and (
                config.autonomy_mode == "supervised" or abs(change_pct) > float(config.approval_required_over_pct or 20)
            ),
            "roas": round(campaign.get("roas", 0), 2),
            "health": campaign.get("health"),
            "decision": decision.get("decision"),
            "action": decision.get("action"),
            "objective": decision.get("objective"),
            "evidence_gate": decision.get("evidence_gate"),
            "mutation_allowed": decision.get("mutation_allowed", False),
            "shadow_mode": decision.get("shadow_mode", True),
        }
        recommendation["decision_evidence"] = recommendation_decision_evidence(campaign, recommendation, rules)
        recommendations.append(recommendation)
    return recommendations


def fatigue_items(campaigns):
    items = []
    for campaign in campaigns:
        ctr_drop = pct_change(campaign.get("ctr"), campaign.get("previous_ctr"))
        cpc_rise = pct_change(campaign.get("cpc"), campaign.get("previous_cpc"))
        cpa_rise = pct_change(campaign.get("cpa"), campaign.get("previous_cpa"))
        reasons = []
        deterioration = ctr_drop <= -20 or cpc_rise >= 30 or cpa_rise >= 25
        if campaign.get("frequency", 0) > 3 and deterioration:
            reasons.append(f"frequency {campaign.get('frequency'):.1f}")
        if ctr_drop <= -20:
            reasons.append(f"CTR {abs(ctr_drop):.0f}% down")
        if cpc_rise >= 30:
            reasons.append(f"CPC {cpc_rise:.0f}% up")
        if cpa_rise >= 25:
            reasons.append(f"CPA {cpa_rise:.0f}% up")
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


def business_context_snapshot(profile):
    profile = profile if isinstance(profile, dict) else {}
    business_type = str(profile.get("business_type") or profile.get("business_short") or "").strip()
    main_offer = str(profile.get("main_offer") or profile.get("offer") or "").strip()
    ideal_customer = str(profile.get("ideal_customer") or profile.get("audience") or "").strip()
    current_stage = str(profile.get("current_stage") or "").strip()
    what_to_improve = str(profile.get("what_to_improve") or "").strip()
    success_goal = str(profile.get("success_goal") or "").strip()
    sales_channel = str(profile.get("sales_channel") or profile.get("channel") or "").strip()
    brand_tone = str(profile.get("brand_tone") or "").strip()
    website_url = str(profile.get("website_url") or "").strip()
    current_ads = str(profile.get("current_ads") or "").strip()
    ready = bool(business_type or main_offer or ideal_customer or current_stage or what_to_improve or website_url)
    summary_parts = [part for part in [business_type, main_offer, ideal_customer, current_stage] if part]
    summary = " · ".join(summary_parts)
    if not summary and website_url:
        summary = website_url
    if not summary:
        summary = "Perfil del negocio pendiente"
    if not main_offer:
        next_step = "Definir en una frase qué vendes."
    elif not ideal_customer:
        next_step = "Decir quién compra hoy."
    elif not current_stage:
        next_step = "Contar en qué punto está el negocio."
    elif not what_to_improve:
        next_step = "Decir qué quiere mejorar primero."
    else:
        next_step = "Convertir esto en un plan simple de anuncios."
    if any(term in sales_channel.lower() for term in ["whatsapp", "instagram", "dm", "mensaje", "mensajes"]):
        audience_hint = "Empezar amplio y dejar mensajes o retargeting para personas que ya conocen el negocio."
    elif website_url:
        audience_hint = "Probar una audiencia amplia con el sitio como destino y dejar que Meta aprenda."
    else:
        audience_hint = "Empezar con una audiencia amplia y ajustar luego con datos reales."
    if current_stage.lower().startswith(("ya vendo", "already", "ya tengo", "tengo anuncios")) or current_ads:
        creative_hint = "Buscar un ángulo nuevo sin perder lo que ya funcionó."
    elif what_to_improve:
        creative_hint = f"Crear creativos que ataquen: {what_to_improve.lower()}"
    else:
        creative_hint = "Usar una imagen clara, un beneficio directo y poco texto."
    if "lead" in success_goal.lower() or "mensaje" in success_goal.lower():
        campaign_hint = "Campaña de leads o mensajes, con supervisión primero."
    elif "venta" in success_goal.lower() or "buy" in success_goal.lower() or website_url:
        campaign_hint = "Campaña de conversiones o compras, con una oferta fácil de entender."
    else:
        campaign_hint = "Campaña simple, visible y fácil de medir."
    return {
        "ready": ready,
        "business_type": business_type,
        "main_offer": main_offer,
        "ideal_customer": ideal_customer,
        "current_stage": current_stage,
        "what_to_improve": what_to_improve,
        "success_goal": success_goal,
        "sales_channel": sales_channel,
        "brand_tone": brand_tone,
        "website_url": website_url,
        "current_ads": current_ads,
        "summary": summary,
        "next_step": next_step,
        "audience_hint": audience_hint,
        "creative_hint": creative_hint,
        "campaign_hint": campaign_hint,
    }


def build_daily_brief(metrics, recommendations, business_profile=None):
    campaigns = metrics.get("campaigns", [])
    summary = metrics.get("summary", {})
    business_context = business_context_snapshot(business_profile)
    active = [c for c in campaigns if c.get("status") == "active"]
    winners = sorted([c for c in campaigns if c.get("health") == "winning"], key=lambda c: c.get("roas", 0), reverse=True)
    losers = sorted([c for c in campaigns if c.get("health") == "losing"], key=lambda c: c.get("roas", 0))
    fatigue = fatigue_items(campaigns)
    projected_spend = summary.get("active_budget", 0)
    action_summary = build_action_summary(recommendations, [], [], fatigue)
    optimization_state = load_optimization_state()
    optimization = {
        "mode": optimization_state.get("mode", "shadow"),
        "unlock": optimization_unlock_status(optimization_state),
        "reconciliation": reconcile_business_outcomes(metrics),
        "anomalies": anomaly_diagnostics(metrics),
        "funnel": funnel_diagnostics(),
        "data_quality": metrics.get("data_quality", {}),
    }
    business_prefix = f"{business_context.get('summary')} · {business_context.get('next_step')} · " if business_context.get("ready") else ""
    return {
        "generated_at": now_iso(),
        "business_context": business_context,
        "questions": [
            {
                "question": "Am I on track?",
                "answer": f"{business_prefix}Active daily budget is ${projected_spend:,.2f}; account ROAS is {summary.get('overall_roas', 0):.2f}x with CPA ${summary.get('overall_cpa', 0):,.2f}.",
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
        "action_summary": action_summary,
        "optimization": optimization,
    }


def latest_daily_report():
    reports = sorted(OUTPUT_DIR.glob("daily_brief_*.json"), reverse=True)
    for path in reports:
        report = read_json(path, None)
        if isinstance(report, dict) and isinstance(report.get("brief"), dict):
            report["_path"] = str(path)
            return report
    return None


def scheduled_brief_or_live(metrics, recommendations, business_profile=None):
    report = latest_daily_report()
    if not report:
        return build_daily_brief(metrics, recommendations, business_profile)
    brief = report.get("brief", {})
    five = brief.get("five_questions", {})
    business_context = business_context_snapshot(business_profile)
    questions = [
        ("Am I on track?", five.get("am_i_on_track")),
        ("What's running?", five.get("whats_running")),
        ("How's performance?", five.get("hows_performance")),
        ("Who's winning/losing?", five.get("winning_losing")),
        ("Any fatigue?", five.get("fatigue")),
    ]
    fallback = build_daily_brief(metrics, recommendations, business_profile)
    return {
        "generated_at": brief.get("generated_at") or report.get("generated_at") or now_iso(),
        "source": "scheduled_daily_agent",
        "report_path": report.get("_path"),
        "business_context": business_context,
        "questions": [
            {"question": question, "answer": answer or fallback["questions"][idx]["answer"]}
            for idx, (question, answer) in enumerate(questions)
        ],
        "winners": [{"name": c.get("name"), "roas": round(c.get("roas", 0), 2), "cpa": money(c.get("cpa", 0))} for c in brief.get("winners", [])[:4]],
        "losers": [{"name": c.get("name"), "roas": round(c.get("roas", 0), 2), "cpa": money(c.get("cpa", 0))} for c in brief.get("losers", [])[:4]],
        "pending_actions": [r for r in brief.get("recommendations", []) if r.get("requires_approval")],
        "action_summary": brief.get("action_summary") or fallback.get("action_summary"),
        "optimization": brief.get("optimization") or fallback.get("optimization"),
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


def assert_campaign_uses_active_account(config, campaign):
    campaign_account = clean_ad_account_id(campaign.get("ad_account_id") or campaign.get("account_id") or "")
    active_account = clean_ad_account_id(getattr(config, "ad_account_id", "") or "")
    if campaign_account and active_account and campaign_account != active_account:
        account_name = campaign.get("account_name") or campaign_account
        raise ValueError(f"Esa campaña pertenece a {account_name}. Primero cambia la cuenta activa a {campaign_account} en Configuración para evitar tocar la cuenta equivocada.")


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
        return refresh_managed_real_metrics(reason="dashboard_action")
    metrics = load_metrics()
    campaign_id = payload.get("campaign_id")
    campaign = campaign_by_id(metrics, campaign_id)
    if action in {"pause", "resume", "adjust_budget", "apply_recommendation"} and not campaign:
        raise ValueError("Campaign not found")
    if action in {"pause", "resume", "adjust_budget", "apply_recommendation"}:
        assert_campaign_uses_active_account(config, campaign)

    if action == "pause":
        action_payload = {"campaign_id": campaign_id, "name": campaign.get("name"), "spend": campaign.get("spend", 0)}
        stage, reason = should_stage_action(config, "pause_campaign", action_payload)
        if stage:
            action_payload["guardrail_reason"] = reason
            return add_pending("pause_campaign", action_payload)
        execute_autopilot_action(config, "pause_campaign", campaign, action_payload)
        campaign["status"] = "paused"
        record_optimization_action(campaign_id)
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
        record_optimization_action(campaign_id)
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
        record_optimization_action(campaign_id)
        save_metrics(metrics)
        return log_action("budget_change", action_payload, "completed")

    if action == "run_agent":
        return run_daily_agent()

    raise ValueError("Unsupported action")


def create_campaign(payload):
    payload = normalize_campaign_stack_arguments(payload)
    final_status = str(payload.get("final_status") or "ACTIVE").strip().upper()
    if final_status not in {"PAUSED", "ACTIVE"}:
        final_status = "ACTIVE"
    active_confirmed = boolish(payload.get("active_spend_confirmed")) is True
    if requires_active_confirmation(payload, final_status) and not active_confirmed:
        raise ValueError("Para dejar anuncios activos debes marcar: Sí, crear y dejar activo.")
    budget_plan = normalize_budget_plan(payload, parse_money_like(payload.get("daily_budget"), 50) or 50)
    status_plan = normalize_status_plan(payload, final_status, active_confirmed)
    creator = CampaignCreator()
    selected_interests = parse_targeting_items(payload.get("targeting_interests_json") or payload.get("targeting_interests"), "interest")
    selected_locations = parse_targeting_items(payload.get("targeting_locations_json") or payload.get("targeting_locations"), "location")
    manual_interests = [item.strip() for item in str(payload.get("interests", "")).split(",") if item.strip()]
    manual_locations = [item.strip().upper() for item in str(payload.get("locations", "US")).split(",") if item.strip()]
    interests = [item.get("name") for item in selected_interests if item.get("name")] or manual_interests
    locations = targeting_location_values(selected_locations, manual_locations or ["US"])
    audience = creator.create_audience_targeting(
        locations=locations or ["US"],
        age_min=int(payload.get("age_min", 18)),
        age_max=int(payload.get("age_max", 65)),
        interests=interests,
    )
    audience = merge_expert_targeting(audience, payload)
    if selected_locations or selected_interests:
        audience["meta_targeting"] = {
            "locations": selected_locations,
            "interests": selected_interests,
        }
    signal_review = review_signal_quality(payload, metrics=load_metrics(), language=chat_lang(payload))
    success_metrics = normalize_success_metrics(payload)
    placement_config = normalize_placement_config(payload.get("placements") or payload.get("placement_preset") or payload.get("manual_placements"))
    schedule = normalize_schedule(payload)
    bidding = normalize_bidding(payload)
    creative_controls = normalize_creative_controls(payload)
    ad_set = creator.create_ad_set_config(
        f"{payload.get('name', 'New Campaign')} - Core",
        audience,
        budget_plan["adset_daily"],
    )
    if budget_plan.get("adset_lifetime"):
        ad_set["lifetime_budget"] = budget_plan["adset_lifetime"]
    ad_set["placements"] = placement_config
    ad_set["billing_event"] = normalize_billing_event(payload.get("billing_event"))
    if bidding:
        ad_set["bidding"] = bidding
    if schedule.get("start_time"):
        ad_set["start_time"] = schedule["start_time"]
    if schedule.get("end_time"):
        ad_set["end_time"] = schedule["end_time"]
    ad_set["status"] = status_plan["adset"]
    ad_set = apply_signal_quality_to_adset(ad_set, signal_review)
    campaign = creator.create_campaign_config(
        name=payload.get("name", "New Campaign"),
        objective=payload.get("objective", "PURCHASES"),
        budget_daily=budget_plan["campaign_daily"],
        budget_total=budget_plan["total_budget"],
        pixel_id=payload.get("pixel_id") or None,
        ad_sets=[ad_set],
    )
    campaign["status"] = status_plan["campaign"]
    campaign["status_plan"] = status_plan
    campaign["budget_plan"] = budget_plan
    campaign["budget_currency"] = payload.get("budget_currency") or "account_default"
    campaign["budget_currency_hint"] = payload.get("budget_currency_hint") or ""
    if payload.get("budget_currency_warning"):
        campaign["budget_currency_warning"] = payload.get("budget_currency_warning")
    campaign["success_metrics"] = success_metrics
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
        "cta_link": creative_controls["cta_link"],
        "image_hash": creative_controls["image_hash"],
        "image_url": creative_controls["image_url"],
        "video_url": creative_controls["video_url"],
        "object_story_spec": creative_controls["object_story_spec"],
        "creative_format": creative_controls["format"],
        "final_status": final_status,
        "active_spend_confirmed": active_confirmed,
    }
    campaign["creative_format_review"] = creative_format_review(campaign["ad"], placement_config)
    campaign["signal_quality_review"] = signal_review
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
            "currency": campaign.get("budget_currency"),
            "currency_hint": campaign.get("budget_currency_hint"),
            "currency_warning": campaign.get("budget_currency_warning", ""),
            "budget_plan": budget_plan,
            "status_plan": status_plan,
            "objective": campaign["objective"],
            "success_metrics": success_metrics,
            "ad_sets": [adset.get("name") for adset in campaign.get("ad_sets", [])],
            "creative_image_path": campaign["ad"]["creative_image_path"],
            "creative_controls": {
                "has_object_story_spec": bool(campaign["ad"].get("object_story_spec")),
                "has_image_hash": bool(campaign["ad"].get("image_hash")),
                "has_image_url": bool(campaign["ad"].get("image_url")),
                "has_video_url": bool(campaign["ad"].get("video_url")),
                "cta_link": campaign["ad"].get("cta_link"),
                "format_review": campaign.get("creative_format_review"),
            },
            "targeting": targeting_summary(audience),
            "placements": placement_config_summary(placement_config),
            "adset_controls": {
                "optimization_goal": ad_set.get("optimization_goal"),
                "billing_event": ad_set.get("billing_event"),
                "promoted_object": ad_set.get("promoted_object"),
                "bidding": ad_set.get("bidding", {}),
                "schedule": schedule,
            },
            "signal_quality": {
                "status": signal_review.get("status"),
                "recommended_event": signal_review.get("recommended_event"),
                "safe_to_launch_active": signal_review.get("safe_to_launch_active"),
                "checks": signal_review.get("checks", []),
            },
        },
        "guardrail_reason": "new_campaigns_always_require_approval",
        "dry_run_preview": campaign_preview(campaign),
        "signal_quality_review": signal_review,
    }
    return add_pending("create_campaign", pending_payload)


CAMPAIGN_CREATIVE_SOURCE_KEYS = (
    "creative_image_path",
    "image_hash",
    "image_url",
    "video_url",
    "object_story_spec",
    "object_story_spec_json",
)

CAMPAIGN_CREATIVE_ALIAS_KEYS = (
    "creative_image_path_or_url_or_story_spec",
    "creative_path",
    "creative_asset",
    "creative_asset_path",
    "creative_url",
    "creative_image_url",
    "ad_image_path",
    "image_path",
    "image",
    "asset_path",
    "asset_url",
    "media_path",
    "media_url",
    "video_path",
    "video_asset",
    "video_asset_url",
)

CURRENCY_SYMBOL_HINTS = (
    ("US$", "USD"),
    ("USD", "USD"),
    ("COP", "COP"),
    ("COL$", "COP"),
    ("MXN", "MXN"),
    ("MX$", "MXN"),
    ("PEN", "PEN"),
    ("S/", "PEN"),
    ("EUR", "EUR"),
    ("€", "EUR"),
    ("GBP", "GBP"),
    ("£", "GBP"),
    ("BRL", "BRL"),
    ("R$", "BRL"),
    ("CLP", "CLP"),
    ("ARS", "ARS"),
    ("CAD", "CAD"),
    ("AUD", "AUD"),
)


def parse_localized_number_token(token):
    text = str(token or "").strip()
    if not text:
        return None
    if "," in text and "." in text:
        decimal_separator = "," if text.rfind(",") > text.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        normalized = text.replace(thousands_separator, "").replace(decimal_separator, ".")
    elif "." in text:
        parts = text.split(".")
        normalized = "".join(parts) if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]) else text
    elif "," in text:
        parts = text.split(",")
        normalized = "".join(parts) if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]) else text.replace(",", ".")
    else:
        normalized = text
    try:
        return float(normalized)
    except ValueError:
        return None


def parse_money_like(value, default=None):
    if value in (None, ""):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return default
    match = re.search(r"[-+]?\d[\d.,]*", text)
    if not match:
        return default
    parsed = parse_localized_number_token(match.group(0))
    return default if parsed is None else parsed


def currency_hint_from_text(value):
    text = str(value or "").strip().upper()
    if not text:
        return ""
    for token, currency in CURRENCY_SYMBOL_HINTS:
        if token in text:
            return currency
    return ""


def configured_ad_account_currency():
    state = normalize_managed_accounts_state(seed=False)
    active_id = clean_ad_account_id(state.get("active_ad_account_id") or "")
    accounts = state.get("accounts") or []
    active = next((account for account in accounts if clean_ad_account_id(account.get("id")) == active_id), None)
    if not active and accounts:
        active = accounts[0]
    return str((active or {}).get("currency") or "").strip().upper()


def boolish(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "si", "sí", "claro", "confirmado"}:
        return True
    if text in {"0", "false", "no", "n", "off", "pausado", "pausada", "paused"}:
        return False
    return None


def campaign_status_from_text(value):
    if isinstance(value, dict):
        value = " ".join(str(item or "") for item in value.values())
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if re.search(r"\b(paused|pause|pausar|pausad[oa]|en pausa|draft|borrador)\b", text):
        return "PAUSED"
    if re.search(r"\b(active|activo|activa|encendid[oa]|live|lanzar|publicar)\b", text):
        return "ACTIVE"
    return ""


def normalize_campaign_stack_arguments(arguments, chat_payload=None):
    """Accept the looser shapes Hermes/Telegram may send for campaign staging."""
    args = dict(arguments or {})

    if not args.get("daily_budget"):
        for key in ("budget", "budget_daily", "daily_budget_usd", "daily_budget_amount", "presupuesto_diario"):
            if args.get(key):
                args["daily_budget"] = args.get(key)
                break
    daily_budget = parse_money_like(args.get("daily_budget"))
    if daily_budget is not None:
        args["daily_budget"] = daily_budget
    total_budget = parse_money_like(args.get("total_budget"))
    if total_budget is not None:
        args["total_budget"] = total_budget
    currency_hint = (
        currency_hint_from_text(args.get("daily_budget_raw"))
        or currency_hint_from_text(arguments.get("daily_budget") if isinstance(arguments, dict) else "")
        or currency_hint_from_text(arguments.get("budget") if isinstance(arguments, dict) else "")
    )
    account_currency = str(
        args.get("ad_account_currency")
        or args.get("account_currency")
        or configured_ad_account_currency()
        or ""
    ).strip().upper()
    if currency_hint:
        args["budget_currency_hint"] = currency_hint
    if account_currency:
        args["ad_account_currency"] = account_currency
        args["budget_currency"] = account_currency
    elif currency_hint:
        args["budget_currency"] = currency_hint
    else:
        args.setdefault("budget_currency", "account_default")
    if currency_hint and account_currency and currency_hint != account_currency:
        args["budget_currency_warning"] = (
            f"El presupuesto se aplicará en la moneda de la cuenta publicitaria ({account_currency}), "
            f"pero el texto enviado mencionaba {currency_hint}. No se hizo conversión automática."
        )

    if not args.get("final_status"):
        for key in ("status_plan", "status", "desired_status", "campaign_status", "adset_status", "ad_set_status", "ad_status"):
            status = campaign_status_from_text(args.get(key))
            if status:
                args["final_status"] = status
                break
    if not args.get("final_status"):
        args["final_status"] = "PAUSED"

    confirmed = boolish(args.get("active_spend_confirmed"))
    if confirmed is not None:
        args["active_spend_confirmed"] = confirmed

    if not any(args.get(key) for key in CAMPAIGN_CREATIVE_SOURCE_KEYS):
        safe_from_args = safe_image_paths(args)
        safe_from_chat = safe_image_paths(chat_payload or {})
        if safe_from_args:
            args["creative_image_path"] = safe_from_args[0]
        elif safe_from_chat:
            args["creative_image_path"] = safe_from_chat[0]

    if not any(args.get(key) for key in CAMPAIGN_CREATIVE_SOURCE_KEYS):
        alias_value = ""
        for key in CAMPAIGN_CREATIVE_ALIAS_KEYS:
            if args.get(key):
                alias_value = args.get(key)
                break
        if isinstance(alias_value, dict):
            args["object_story_spec"] = alias_value
        elif alias_value:
            parsed_story = None
            if isinstance(alias_value, str):
                try:
                    parsed_story = json.loads(alias_value)
                except json.JSONDecodeError:
                    parsed_story = None
            if isinstance(parsed_story, dict):
                args["object_story_spec"] = parsed_story
            else:
                safe_alias_paths = safe_image_paths({"creative_image_path": alias_value})
                if safe_alias_paths:
                    args["creative_image_path"] = safe_alias_paths[0]
                else:
                    text = str(alias_value or "").strip()
                    lowered = text.lower()
                    if text.startswith(("http://", "https://")):
                        if any(lowered.split("?", 1)[0].endswith(ext) for ext in (".mp4", ".mov", ".m4v", ".webm")):
                            args["video_url"] = text
                        else:
                            args["image_url"] = text

    return args


def create_audience_strategy(payload, language="es"):
    strategy = build_audience_strategy(payload, language)
    write_json(AUDIENCE_FILE, strategy)
    log_action("audience_strategy", {"product": strategy.get("product"), "objective": strategy.get("objective")}, "completed")
    return strategy


def run_daily_agent():
    config = load_config()
    if config.ad_account_id and config.meta_access_token:
        refresh_managed_real_metrics(reason="daily_agent_before_brief")
    report_path, report = run_scheduled_daily()
    actions = read_json(ACTIONS_FILE, [])
    action = actions[0] if actions else log_action("daily_agent_run", {"report_path": str(report_path)}, "completed")
    return action, report


def live_experiment_insight_rows():
    """Read ad-level insights for experiment comparisons without mutating Meta."""
    config = load_config()
    if not (config.ad_account_id or config.meta_access_token):
        return []
    result = SocialFlowClient(config).insights("last_7d", "ad")
    if not result.get("data"):
        return []
    return normalize_experiment_insights(result.get("data"), "ad")


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
    reset_creative_memory_wizard()
    log_action("chat_new_conversation", {"cleared": True}, "completed")
    return {"cleared": True}


CREATIVE_MEMORY_WIZARD_SPECS = {
    "general": {
        "title_es": "información de tu marca",
        "title_en": "general brand memory",
        "save": "general",
        "fields": [
            {
                "key": "brand_name",
                "required": True,
                "es": "Primero, dime el nombre de la marca. Si la marca es personal, dime el nombre que usa el negocio.",
                "en": "First, tell me the brand name. If it is a personal brand, tell me the business-facing name.",
            },
            {
                "key": "offer",
                "required": True,
                "es": "Perfecto. ¿Qué vende esta marca, explicado en palabras simples?",
                "en": "Perfect. What does this brand sell, in simple words?",
            },
            {
                "key": "promise",
                "es": "¿Qué cambio espera conseguir la persona que compra?",
                "en": "What is the main promise? In other words: what change does the buyer expect?",
            },
            {
                "key": "ideal_customer",
                "es": "¿Quién es el cliente ideal? Cuéntamelo como si describieras a una persona real.",
                "en": "Who is the ideal customer? Tell me as if describing a real person.",
            },
            {
                "key": "tone",
                "required": True,
                "es": "¿Cómo debe sonar la marca? Por ejemplo: cercana, experta, elegante, directa, divertida.",
                "en": "How should the brand sound? For example: warm, expert, elegant, direct, playful.",
            },
            {
                "key": "colors",
                "required": True,
                "es": "¿Qué colores o sensación visual debe respetar el agente al crear anuncios?",
                "en": "What colors or visual feeling should the agent respect when creating ads?",
            },
            {
                "key": "visual_style",
                "required": True,
                "es": "¿Cómo deben verse los anuncios? Puedes contarme sobre colores, fondos, fotos o ejemplos que te gustan.",
                "en": "How should the creatives look? Think backgrounds, photos, style, composition, or references.",
            },
            {
                "key": "logo_usage",
                "required": True,
                "es": "¿Tienes un logo oficial para subir, quieres crear uno después o prefieres trabajar sin logo? Si existe, dime si debe aparecer siempre, a veces o nunca.",
                "en": "Do you have an official logo to upload, want to create one later, or prefer no logo? If it exists, should it appear always, sometimes, or never?",
            },
            {
                "key": "references",
                "required": True,
                "es": "¿Tienes un diseño, anuncio o marca de referencia que te guste? Puedes subirlo. Si no tienes, responde: no tengo referencia.",
                "en": "Do you have a design, ad, or brand reference you like? You can upload it. If not, say: I have no reference.",
            },
            {
                "key": "asset_notes",
                "required": True,
                "es": "¿Tienes fotos reales del producto, fundador, clientes, local o empaque, o debemos generar las imágenes?",
                "en": "Do you have real product, founder, customer, location, or packaging photos, or should the images be generated?",
            },
            {
                "key": "avoid_always",
                "es": "Última de marca: ¿qué NO debe hacer nunca el agente con esta marca?",
                "en": "Last brand question: what should the agent never do with this brand?",
            },
        ],
    },
    "product": {
        "title_es": "información de tu producto",
        "title_en": "product or offer sheet",
        "save": "product",
        "fields": [
            {
                "key": "name",
                "required": True,
                "es": "Empecemos por lo básico: ¿cómo se llama este producto u oferta?",
                "en": "Let's start with the basics: what is this product or offer called?",
            },
            {
                "key": "url",
                "es": "¿Cuál es la página donde la persona puede comprar, registrarse o saber más? Si no existe todavía, di saltar.",
                "en": "What page can people use to buy, sign up, or learn more? If it does not exist yet, say skip.",
            },
            {
                "key": "price",
                "es": "¿Cuál es el precio o rango de precio?",
                "en": "What is the price or price range?",
            },
            {
                "key": "includes",
                "es": "¿Qué recibe exactamente la persona cuando compra o deja sus datos?",
                "en": "What exactly does the person receive when they buy or submit their details?",
            },
            {
                "key": "audience",
                "es": "¿Para quién es este producto? Dime el tipo de persona o negocio que más te interesa atraer.",
                "en": "Who is this product for? Tell me the type of person or business you most want to attract.",
            },
            {
                "key": "pain",
                "es": "¿Qué problema, frustración o preocupación tiene esa persona antes de comprar?",
                "en": "What problem, frustration, or worry does that person have before buying?",
            },
            {
                "key": "desire",
                "es": "¿Qué resultado desea conseguir esa persona?",
                "en": "What result does that person want to get?",
            },
            {
                "key": "objections",
                "es": "¿Qué dudas suelen frenar la compra? Precio, confianza, tiempo, miedo, comparación, etc.",
                "en": "What doubts usually block the purchase? Price, trust, time, fear, comparison, etc.",
            },
            {
                "key": "show",
                "es": "Visualmente, ¿qué debería mostrar el anuncio para este producto?",
                "en": "Visually, what should the ad show for this product?",
            },
            {
                "key": "avoid",
                "es": "¿Qué debería evitar mostrar o decir cuando anuncie este producto?",
                "en": "What should it avoid showing or saying when advertising this product?",
            },
            {
                "key": "strong_phrases",
                "es": "Dame 2 o 3 frases que sí te gustaría ver en el anuncio.",
                "en": "Give me 2 or 3 strong phrases you would like the agent to be able to use.",
            },
        ],
    },
    "ad_brief": {
        "title_es": "idea para un anuncio",
        "title_en": "ad idea",
        "save": "ad_brief",
        "fields": [
            {
                "key": "name",
                "es": "Vamos a preparar una idea para tu anuncio. ¿Cómo quieres llamarla? Ejemplo: Promo de junio.",
                "en": "Let's prepare an idea for your ad. What would you like to call it? Example: June promotion.",
            },
            {
                "key": "promotion",
                "es": "¿Cuál es la promoción, idea puntual u oferta que quieres anunciar?",
                "en": "What is the promotion, specific idea, or offer you want to advertise?",
            },
            {
                "key": "campaign_name",
                "es": "¿Ya tienes una campaña donde poner este anuncio? Si sí, dime su nombre. Si todavía no existe, di \"saltar\".",
                "en": "Do you already have a campaign for this ad? If so, tell me its name. If not, say \"skip\".",
            },
            {
                "key": "adset_name",
                "es": "¿A qué tipo de personas quieres mostrarles este anuncio? Por ejemplo: mujeres de 25 a 44 años en Colombia.",
                "en": "What type of people should see this ad? For example: women aged 25 to 44 in Colombia.",
            },
            {
                "key": "base_ad_name",
                "es": "¿Quieres mejorar un anuncio que ya tienes? Si sí, dime cuál. Si esta idea es nueva, di \"saltar\".",
                "en": "Do you want to improve an ad you already have? If so, tell me which one. If this is new, say \"skip\".",
            },
            {
                "key": "objective",
                "es": "¿Qué quieres que haga la persona al ver este anuncio? Comprar, escribirte, reservar o visitar tu página.",
                "en": "What should this ad achieve? Sales, leads, messages, visits, bookings, etc.",
            },
            {
                "key": "audience_slice",
                "es": "¿Qué desea o qué le preocupa a la persona que verá este anuncio?",
                "en": "What does the person who will see this ad want or worry about?",
            },
            {
                "key": "base_ad",
                "es": "¿Hay una foto, frase, precio o promoción que ya te funciona y quieres conservar?",
                "en": "What already works or should be preserved from the ad? Hook, structure, product, proof, offer...",
            },
            {
                "key": "locked_elements",
                "es": "¿Hay algo que el agente nunca deba cambiar en esta idea? Por ejemplo: el precio o la oferta.",
                "en": "Is there anything the agent must never change in this idea? For example: the price or offer.",
            },
            {
                "key": "variation_window",
                "required": True,
                "es": "¿Quieres una sola idea o varias opciones para comparar? Si quieres varias, dime qué puede cambiar: colores, foto, título u otro detalle.",
                "en": "Do you want one idea or several options to compare? If you want several, tell me what may change: colors, photo, headline, or another detail.",
            },
            {
                "key": "variation_axes",
                "es": "Si quieres opciones, ¿qué partes puede cambiar el agente? Si solo quieres una idea, di \"saltar\".",
                "en": "If you want options, which parts may the agent change? If you only want one idea, say \"skip\".",
            },
            {
                "key": "variation_count",
                "required": True,
                "es": "¿Cuántas imágenes o textos quieres que prepare? Puedes pedir solo uno.",
                "en": "How many images or texts would you like prepared? You can request just one.",
            },
            {
                "key": "concurrent_variations",
                "required": True,
                "es": "Con tu presupuesto, ¿cuántos de esos creativos probaremos al mismo tiempo y cuántos quedarán para después?",
                "en": "With your budget, how many of those creatives will run at the same time and how many stay in the backlog?",
            },
            {
                "key": "formats",
                "required": True,
                "es": "¿Qué formatos vamos a probar? Por ejemplo: UGC, foto real, demostración, prueba, estático, carrusel o video.",
                "en": "Which formats will we test? For example: UGC, real photo, demonstration, proof, static, carousel, or video.",
            },
            {
                "key": "required_assets",
                "es": "¿Qué fotos, videos, logos, testimonios o productos necesitamos para producirlos?",
                "en": "Which photos, videos, logos, testimonials, or products are needed to produce them?",
            },
            {
                "key": "creative_hypothesis",
                "required": True,
                "es": "Si vas a comparar opciones, ¿qué te gustaría descubrir? Si no, di \"saltar\".",
                "en": "If you will compare options, what would you like to learn? Otherwise, say \"skip\".",
            },
            {
                "key": "success_signal",
                "es": "¿Qué señal dirá que una idea merece seguir: CTR, costo por lead, compras u otra métrica?",
                "en": "Which signal will tell us an idea deserves more spend: CTR, cost per lead, purchases, or another metric?",
            },
        ],
    },
}


def load_creative_memory_wizard():
    session = read_json(CREATIVE_MEMORY_WIZARD_FILE, {})
    return session if isinstance(session, dict) else {}


def save_creative_memory_wizard(session):
    write_json(CREATIVE_MEMORY_WIZARD_FILE, session)
    return session


def reset_creative_memory_wizard():
    if CREATIVE_MEMORY_WIZARD_FILE.exists():
        CREATIVE_MEMORY_WIZARD_FILE.unlink()
    return {"cleared": True}


def wizard_kind(value):
    raw = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "brand": "general",
        "marca": "general",
        "marca_general": "general",
        "general_brand": "general",
        "producto": "product",
        "offer": "product",
        "oferta": "product",
        "brief": "ad_brief",
        "ad": "ad_brief",
        "anuncio": "ad_brief",
        "brief_anuncio": "ad_brief",
    }
    return aliases.get(raw, raw if raw in CREATIVE_MEMORY_WIZARD_SPECS else "")


def wizard_is_skip(text):
    return normalize_text(text) in {"saltar", "skip", "no se", "no sé", "no aplica", "n/a", "ninguno", "none"}


def wizard_question(session, payload):
    kind = session.get("kind")
    spec = CREATIVE_MEMORY_WIZARD_SPECS.get(kind) or {}
    fields = session.get("fields") or {}
    index = int(session.get("index") or 0)
    items = spec.get("fields", [])
    lang_es = chat_lang(payload) == "es"
    while index < len(items):
        item = items[index]
        if str(fields.get(item["key"]) or "").strip():
            index += 1
            continue
        session["index"] = index
        return item.get("es" if lang_es else "en", item.get("es", ""))
    session["index"] = len(items)
    return ""


def wizard_existing_fields(kind, item_id):
    library = guide_library()
    if kind == "general":
        return {}
    if kind == "product" and item_id:
        product = next((item for item in library.get("products", []) if item.get("id") == item_id), None)
        return dict(product.get("fields") or {}) if product else {}
    if kind == "ad_brief" and item_id:
        brief = next((item for item in library.get("ad_briefs", []) if item.get("id") == item_id), None)
        return dict(brief.get("fields") or {}) if brief else {}
    return {}


def wizard_intro(kind, payload):
    spec = CREATIVE_MEMORY_WIZARD_SPECS[kind]
    if chat_lang(payload) == "es":
        return f"Perfecto. Vamos a guardar la {spec['title_es']} hablando. Te haré una pregunta a la vez. Responde con tus palabras. Si algo no aplica, escribe \"saltar\"."
    return f"Perfect. I will complete the {spec['title_en']} with you conversationally. I will ask one question at a time; answer simply, like talking to someone on your team. If something does not apply, say \"skip\"."


def wizard_completion_reply(kind, result, payload):
    lang_es = chat_lang(payload) == "es"
    if kind == "general":
        name = (guide_library().get("general", {}).get("fields") or {}).get("brand_name") or "tu marca"
        return f"Listo. Ya guardé cómo es {name}. Desde ahora usaré esa información para que sus anuncios se vean y suenen como tu marca." if lang_es else f"Done. I saved the general memory for {name}. From now on, the agent will use it to keep ads visually and verbally consistent."
    if kind == "product":
        product = next((item for item in result.get("library", {}).get("products", []) if item.get("id") == result.get("product_id")), {})
        name = product.get("name") or "este producto"
        return f"Listo. Ya guardé los datos de {name}. Ahora puedo crear ideas, imágenes y textos que hablen de esa oferta con más precisión." if lang_es else f"Done. I saved the details for {name}. I can now create ideas, images, and text that speak about that offer more precisely."
    brief = next((item for item in result.get("library", {}).get("ad_briefs", []) if item.get("id") == result.get("ad_brief_id")), {})
    name = brief.get("name") or "este anuncio"
    return f"Listo. Ya guardé la idea de anuncio {name}. Puedo ayudarte a crear imágenes y textos basados en ella cuando me lo pidas." if lang_es else f"Done. I saved the ad idea {name}. I can help create images and text based on it whenever you ask."


def complete_creative_memory_wizard(session, payload):
    kind = session.get("kind")
    fields = dict(session.get("fields") or {})
    item_id = str(session.get("item_id") or "").strip()
    if item_id:
        fields["id"] = item_id
    if kind == "ad_brief" and session.get("product_guide") and not fields.get("product_guide"):
        fields["product_guide"] = session.get("product_guide")
    if kind == "general":
        result = save_general_guide(fields)
    elif kind == "product":
        result = save_product_guide(fields)
    elif kind == "ad_brief":
        result = save_ad_brief(fields)
    else:
        raise ValueError("Tipo de memoria creativa no soportado.")
    reset_creative_memory_wizard()
    log_action("creative_memory_wizard_complete", {"kind": kind, "item_id": item_id}, "completed")
    return {
        "ok": True,
        "provider": "creative-memory-wizard",
        "fallback": False,
        "reply": wizard_completion_reply(kind, result if isinstance(result, dict) else {"library": result}, payload),
        "routed_action": {"type": "creative_memory_wizard_complete", "kind": kind, "result": result},
    }


def handle_creative_memory_wizard(payload):
    message = str(payload.get("message") or "").strip()
    request = payload.get("memory_wizard") if isinstance(payload.get("memory_wizard"), dict) else {}
    active = load_creative_memory_wizard()
    if request.get("mode") == "start":
        kind = wizard_kind(request.get("kind"))
        if not kind:
            return {
                "ok": True,
                "provider": "creative-memory-wizard",
                "fallback": False,
                "reply": chat_reply(payload, "Puedo ayudarte, pero necesito saber si quieres contarme sobre tu marca, tu producto o una idea de anuncio.", "I can help, but I need to know whether you want to tell me about your brand, product, or an ad idea."),
                "routed_action": {"type": "creative_memory_wizard_start", "blocked": True},
            }
        session = {
            "kind": kind,
            "item_id": str(request.get("id") or "").strip(),
            "product_guide": str(request.get("product_guide") or "").strip(),
            "fields": wizard_existing_fields(kind, request.get("id")),
            "index": 0,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        question = wizard_question(session, payload)
        save_creative_memory_wizard(session)
        return {
            "ok": True,
            "provider": "creative-memory-wizard",
            "fallback": False,
            "reply": f"{wizard_intro(kind, payload)}\n\n{question}",
            "routed_action": {"type": "creative_memory_wizard_start", "kind": kind},
        }
    if not active:
        return None
    if text_has_any(normalize_text(message), ["cancelar guia", "cancelar guía", "cancelar memoria", "cancel wizard", "stop wizard"]):
        reset_creative_memory_wizard()
        return {
            "ok": True,
            "provider": "creative-memory-wizard",
            "fallback": False,
            "reply": chat_reply(payload, "Listo, cancelé esta guía. No guardé cambios nuevos.", "Done, I cancelled this guide. I did not save new changes."),
            "routed_action": {"type": "creative_memory_wizard_cancelled"},
        }
    kind = active.get("kind")
    spec = CREATIVE_MEMORY_WIZARD_SPECS.get(kind)
    if not spec:
        reset_creative_memory_wizard()
        return None
    fields = dict(active.get("fields") or {})
    index = int(active.get("index") or 0)
    items = spec.get("fields", [])
    while index < len(items) and str(fields.get(items[index]["key"]) or "").strip():
        index += 1
    if index >= len(items):
        return complete_creative_memory_wizard(active, payload)
    current = items[index]
    answer = "" if wizard_is_skip(message) else message
    if current.get("required") and not answer:
        active["index"] = index
        save_creative_memory_wizard(active)
        retry = chat_reply(
            payload,
            "Ese dato sí lo necesito para guardar bien esta memoria. Respóndeme con una frase corta y seguimos.",
            "I do need that detail to save this memory properly. Reply with a short phrase and we will continue.",
        )
        return {"ok": True, "provider": "creative-memory-wizard", "fallback": False, "reply": retry}
    fields[current["key"]] = answer
    active["fields"] = fields
    active["index"] = index + 1
    active["updated_at"] = now_iso()
    question = wizard_question(active, payload)
    if question:
        save_creative_memory_wizard(active)
        prefix = chat_reply(payload, "Anotado.", "Got it.")
        return {
            "ok": True,
            "provider": "creative-memory-wizard",
            "fallback": False,
            "reply": f"{prefix}\n\n{question}",
            "routed_action": {"type": "creative_memory_wizard_answer", "kind": kind, "field": current["key"]},
        }
    return complete_creative_memory_wizard(active, payload)


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
    attached_images = safe_image_paths(payload)
    image_path = extract_image_path(payload.get("message", "")) or (attached_images[0] if attached_images else "")
    success_metric_candidates = success_metric_candidates_from_text(payload.get("message", ""))
    final_status = "ACTIVE" if text_has_any(text, ["activo", "activa", "active", "encendida", "encendido"]) else "PAUSED"
    confirmed = text_confirms_active_approval(text)
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
        "success_metrics": success_metric_candidates,
        "final_status": final_status,
        "active_spend_confirmed": confirmed,
    }


def pending_approval_title(item):
    payload = item.get("payload", {}) if isinstance(item, dict) else {}
    requested = payload.get("requested") if isinstance(payload.get("requested"), dict) else {}
    return payload.get("name") or payload.get("campaign_name") or requested.get("campaign") or payload.get("action") or item.get("type", "Decision")


def approval_public_payload(item):
    payload = item.get("payload", {}) if isinstance(item, dict) else {}
    return {
        "id": item.get("id", ""),
        "type": item.get("type", "approval"),
        "name": pending_approval_title(item),
        "final_status": payload.get("final_status", ""),
        "requires_active_confirmation": approval_requires_active_confirmation(item),
    }


def approval_requires_active_confirmation(item):
    payload = item.get("payload", {}) if isinstance(item, dict) else {}
    return item.get("type") == "create_campaign" and str(payload.get("final_status") or "").upper() == "ACTIVE"


def approval_text_decision(text):
    normalized = normalize_text(text)
    if text_confirms_active_approval(normalized):
        return "approve"
    if text_has_any(normalized, ["rechaza", "rechazar", "recházalo", "rechazalo", "no aprobar", "no apruebo", "deny", "reject"]):
        return "reject"
    if text_has_any(normalized, ["aprueba", "aprobar", "apruébalo", "aprobalo", "approve"]):
        return "approve"
    return ""


def text_confirms_active_approval(text):
    normalized = normalize_text(text)
    return any(
        phrase in normalized
        for phrase in [
            "sí, crear y dejar activo",
            "si, crear y dejar activo",
            "si crear y dejar activo",
            "sí crear y dejar activo",
            "aprobar activo",
            "crear y dejar activo",
            "yes, create and leave active",
            "yes create and leave active",
            "yes, create and keep active",
            "yes create and keep active",
            "yes, approve active",
            "yes approve active",
            "create and leave active",
        ]
    )


def find_pending_approval_for_text(text, pending):
    pending = [item for item in pending if item.get("status", "pending") == "pending"]
    if not pending:
        return None, "empty"
    normalized = normalize_text(text)
    id_matches = re.findall(r"approval_[a-zA-Z0-9_\-]+", str(text or ""))
    for approval_id in id_matches:
        for item in pending:
            if item.get("id") == approval_id:
                return item, "id"
    if len(pending) == 1:
        return pending[0], "single"
    title_matches = []
    for item in pending:
        title = normalize_text(pending_approval_title(item))
        if title and len(title) >= 4 and title in normalized:
            title_matches.append(item)
    if len(title_matches) == 1:
        return title_matches[0], "title"
    return None, "ambiguous"


def route_chat_approval_decision(payload):
    message = payload.get("message", "")
    decision = approval_text_decision(message)
    if not decision:
        return None
    pending = read_json(PENDING_FILE, [])
    item, reason = find_pending_approval_for_text(message, pending)
    if not item:
        choices = [approval_public_payload(p) for p in pending[:4]]
        if reason == "empty":
            reply_text = chat_reply(payload, "No veo aprobaciones pendientes ahora mismo.", "I do not see pending approvals right now.")
        else:
            reply_text = chat_reply(
                payload,
                "Tengo varias decisiones pendientes. Dime cuál quieres aprobar o usa los botones exactos que te muestro aquí.",
                "I have several pending decisions. Tell me which one you want to approve or use the exact buttons shown here.",
            )
        return {
            "ok": True,
            "provider": "local-approval-router",
            "fallback": False,
            "approval_choices": choices,
            "routed_action": {"type": "approval_decision", "executed": False, "blocked": True, "reason": reason, "approval_choices": choices},
            "reply": reply_text,
        }

    approval_id = item.get("id")
    if decision == "reject":
        rejected = reject_pending(approval_id, "Rejected from chat")
        return {
            "ok": True,
            "provider": "local-approval-router",
            "fallback": False,
            "routed_action": {"type": "approval_decision", "executed": bool(rejected), "decision": "reject", "approval_id": approval_id, "result": rejected},
            "reply": chat_reply(payload, f"Listo. Rechacé esta decisión: {pending_approval_title(item)}.", f"Done. I rejected this decision: {pending_approval_title(item)}."),
        }

    if approval_requires_active_confirmation(item) and not text_confirms_active_approval(message):
        choice = approval_public_payload(item)
        return {
            "ok": True,
            "provider": "local-approval-router",
            "fallback": False,
            "approval_choices": [choice],
            "routed_action": {"type": "approval_decision", "executed": False, "blocked": True, "reason": "active_confirmation_required", "approval_id": approval_id, "approval_choices": [choice]},
            "reply": chat_reply(
                payload,
                "Esta aprobación puede dejar anuncios activos y gastar presupuesto real. Para aprobarla por chat, escribe exactamente: Sí, crear y dejar activo.",
                "This approval can leave ads active and spend real budget. To approve it in chat, type exactly: Yes, create and leave active.",
            ),
        }

    require_license_unlock("approval execution")
    result = approve_pending(approval_id)
    attempted = result[0] if result else {}
    succeeded = attempted.get("status") == "approved"
    return {
        "ok": True,
        "provider": "local-approval-router",
        "fallback": False,
        "routed_action": {"type": "approval_decision", "executed": succeeded, "decision": "approve", "approval_id": approval_id, "result": result},
        "reply": chat_reply(
            payload,
            f"{'Listo. Aprobé y ejecuté' if succeeded else 'Intenté aprobar, pero quedó pendiente para reintentar'}: {pending_approval_title(item)}.",
            f"{'Done. I approved and executed' if succeeded else 'I tried to approve it, but it remains pending for retry'}: {pending_approval_title(item)}.",
        ),
    }


def agent_action_result(action_type, executed=False, reply_text="", **fields):
    result = {"type": action_type, "executed": executed}
    result.update(fields)
    if reply_text:
        result["reply"] = reply_text
    return result


def local_chat_route(payload, action):
    return {
        "ok": True,
        "provider": "local-action-router",
        "fallback": False,
        "routed_action": action,
        "reply": action.get("reply", ""),
    }


def live_readiness_blockers():
    blockers = []
    for section in build_setup_status().get("sections", []):
        for item in section.get("items", []):
            if item.get("status") in {"blocked", "warn"}:
                blockers.append(item)
    return blockers


def live_readiness_reply(payload, blockers, include_queue_wording=True):
    top = blockers[:3]
    if chat_lang(payload) == "es":
        detail = "; ".join(f"{item.get('label')}: {item.get('detail')}" for item in top) or "no veo bloqueos principales"
        approval_part = "revisa la cola de aprobaciones" if include_queue_wording else "revisa aprobaciones"
        return f"Para activar piloto automático con calma, atiende esto primero: {detail}. Después corre una revisión con supervisión, {approval_part} y recién ahí activa piloto automático."
    detail = "; ".join(f"{item.get('label')}: {item.get('detail')}" for item in top) or "I do not see major blockers"
    approval_part = "review the approval queue" if include_queue_wording else "review approvals"
    return f"To enable autopilot calmly, handle this first: {detail}. Then run one supervised check, {approval_part}, and only then enable autopilot."


def run_daily_check_action(payload, action_type="run_daily_check"):
    action, report = run_daily_agent()
    return agent_action_result(
        action_type,
        True,
        chat_reply(payload, "Listo. Ejecuté la revisión diaria y actualicé resumen, recomendaciones y aprobaciones.", "Done. I ran the daily check and refreshed the brief, recommendations, and approvals."),
        action_id=action.get("id"),
        brief=redact_payload((report or {}).get("brief", {})),
    )


def export_report_action(payload, action_type="export_report"):
    result = export_csv()
    return agent_action_result(
        action_type,
        True,
        chat_reply(payload, f"Listo. Exporté el reporte CSV: {result.get('path')}", f"Done. I exported the CSV report: {result.get('path')}"),
        path=result.get("path"),
    )


def save_existing_adset_action(adset_id, payload):
    normalized_id = extract_adset_id(str(adset_id or ""))
    if not normalized_id:
        return agent_action_result(
            "save_existing_adset",
            False,
            chat_reply(
                payload,
                "Puedo guardarlo, pero necesito el número del grupo de anuncios. Se ve como un número largo dentro de Meta Ads Manager.",
                "I can save it, but I need the ad set number. It looks like a long number inside Meta Ads Manager.",
            ),
            blocked=True,
            reason="missing_adset_id",
        )
    result = save_setup_config({"default_adset_id": normalized_id})
    return agent_action_result(
        "save_existing_adset",
        True,
        chat_reply(
            payload,
            f"Listo. Guardé el grupo de anuncios existente {normalized_id}. Lo usaré solo si me pides crear anuncios dentro de una estructura que ya existe.",
            f"Done. I saved existing ad set {normalized_id}. I will use it only when you ask me to create ads inside an existing structure.",
        ),
        default_adset_id=normalized_id,
        result=result,
    )


def guide_existing_adset_action(payload):
    return agent_action_result(
        "guide_existing_adset",
        False,
        chat_reply(
            payload,
            "Eso es opcional. Solo lo necesito si ya tienes un grupo de anuncios creado y quieres que ponga anuncios nuevos ahí. Para encontrarlo: abre Meta Ads Manager, entra a la campaña, toca el grupo de anuncios y copia el número largo que aparece en la URL o en la columna ID. Si no tienes uno, seguimos creando la estructura desde cero.",
            "That is optional. I only need it if you already have an ad set and want new ads placed there. To find it: open Meta Ads Manager, enter the campaign, select the ad set, and copy the long number from the URL or ID column. If you do not have one, we continue by creating the structure from scratch.",
        ),
    )


def campaign_pause_action(campaign, payload, tool_type="pause"):
    result = apply_action({"action": "pause", "campaign_id": campaign.get("id")})
    staged = isinstance(result, dict) and result.get("status") == "pending"
    return agent_action_result(
        tool_type,
        not staged,
        chat_reply(payload, f"{'Preparé la pausa para aprobación' if staged else 'Listo. Pausé'} {campaign.get('name')}.", f"I {'staged the pause for approval' if staged else 'paused'} {campaign.get('name')}."),
        staged=staged,
        campaign_id=campaign.get("id"),
        result=result,
    )


def campaign_resume_action(campaign, payload, tool_type="resume"):
    result = apply_action({"action": "resume", "campaign_id": campaign.get("id")})
    return agent_action_result(
        tool_type,
        False,
        chat_reply(payload, f"Preparé la reactivación de {campaign.get('name')} para aprobación.", f"I staged the reactivation of {campaign.get('name')} for approval."),
        staged=True,
        campaign_id=campaign.get("id"),
        result=result,
    )


def campaign_budget_action(campaign, new_budget, payload, tool_type="adjust_budget"):
    result = apply_action({"action": "adjust_budget", "campaign_id": campaign.get("id"), "new_budget": new_budget})
    staged = isinstance(result, dict) and result.get("status") == "pending"
    return agent_action_result(
        tool_type,
        not staged,
        chat_reply(payload, f"{'Dejé en aprobación' if staged else 'Ajusté'} el presupuesto de {campaign.get('name')} a ${new_budget:,.2f}.", f"I {'staged for approval' if staged else 'adjusted'} {campaign.get('name')} to ${new_budget:,.2f} daily budget."),
        staged=staged,
        campaign_id=campaign.get("id"),
        new_budget=new_budget,
        result=result,
    )


def campaign_creative_action(campaign, payload, tool_type="generate_creatives", arguments=None):
    arguments = arguments or {}
    plan, manifest_path = generate_creative_refresh(
        campaign,
        generate_images=load_config().creative_live,
        product_guide=arguments.get("product_guide", payload.get("product_guide", "")),
        ad_brief=arguments.get("ad_brief", payload.get("ad_brief", "")),
    )
    log_action("chat_creative_refresh", {"campaign_id": campaign.get("id"), "name": campaign.get("name"), "manifest_path": str(manifest_path)}, "generated")
    return agent_action_result(
        tool_type,
        True,
        chat_reply(payload, f"Listo. Preparé ideas de imágenes y textos para {campaign.get('name')}.", f"Done. I prepared image and text ideas for {campaign.get('name')}."),
        campaign_id=campaign.get("id"),
        manifest_path=str(manifest_path),
    )


def route_chat_action(payload):
    message = payload.get("message", "")
    text = normalize_text(message)
    if not text:
        return None
    metrics = load_metrics()
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
        return route_chat_approval_decision(payload)

    if mentions_adset:
        adset_id = extract_adset_id(text)
        if adset_id:
            return local_chat_route(payload, save_existing_adset_action(adset_id, payload))
        return local_chat_route(payload, guide_existing_adset_action(payload))

    if wants_live_gap:
        blockers = live_readiness_blockers()
        return local_chat_route(
            payload,
            agent_action_result("live_readiness_review", False, live_readiness_reply(payload, blockers), blocker_count=len(blockers)),
        )

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
                "ruta de imagen creativa": "Adjunta la imagen creativa final que quieres usar o compárteme un enlace público del asset.",
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
        return local_chat_route(payload, run_daily_check_action(payload, "run_daily_agent"))

    if wants_export:
        return local_chat_route(payload, export_report_action(payload, "export_csv"))

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
            return local_chat_route(payload, campaign_pause_action(campaign, payload, "pause"))
        if wants_resume:
            action = campaign_resume_action(campaign, payload, "resume")
            action["reply"] = chat_reply(payload, f"Preparé la reactivación de {campaign.get('name')} para aprobación. Revísala en la cola antes de ejecutarla.", f"I staged the reactivation of {campaign.get('name')} for approval. Review it in the queue before execution.")
            return local_chat_route(payload, action)
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
            action = campaign_budget_action(campaign, new_budget, payload, "adjust_budget")
            action["reply"] = chat_reply(payload, f"Listo. {action['reply']}", f"Done. {action['reply']}")
            return local_chat_route(payload, action)
        if wants_creative:
            action = campaign_creative_action(campaign, payload, "creative_refresh")
            action["reply"] = chat_reply(payload, f"Listo. Preparé creativos para {campaign.get('name')}. Los puedes revisar en Creativos.", f"Done. I prepared creatives for {campaign.get('name')}. You can review them in Creatives.")
            return local_chat_route(payload, action)
    return None


def handle_agent_approval_tool(arguments, chat_payload, tool):
    decision = str(arguments.get("decision") or "").strip().lower()
    approval_id = str(arguments.get("approval_id") or "").strip()
    message = f"{decision} {approval_id}".strip() if decision in {"approve", "reject"} and approval_id else str(chat_payload.get("message") or "")
    routed = route_chat_approval_decision({**chat_payload, "message": message})
    if routed:
        action = routed.get("routed_action", {})
        action["reply"] = routed.get("reply")
        if routed.get("approval_choices"):
            action["approval_choices"] = routed.get("approval_choices")
        return action
    choices = [approval_public_payload(item) for item in read_json(PENDING_FILE, [])[:4]]
    return agent_action_result(
        tool,
        False,
        chat_reply(
            chat_payload,
            "Puedo ayudarte a aprobar, pero necesito una decisión exacta. Usa el botón de la aprobación o dime el ID que aparece en la tarjeta.",
            "I can help you approve, but I need an exact decision. Use the approval button or tell me the ID shown on the card.",
        ),
        blocked=True,
        approval_choices=choices,
    )


def handle_review_live_readiness_tool(arguments, chat_payload, tool):
    blockers = live_readiness_blockers()
    return agent_action_result(
        tool,
        False,
        live_readiness_reply(chat_payload, blockers, include_queue_wording=False),
        blocker_count=len(blockers),
    )


def handle_run_daily_check_tool(arguments, chat_payload, tool):
    return run_daily_check_action(chat_payload, tool)


def handle_schedule_experiment_review_tool(arguments, chat_payload, tool):
    try:
        experiment = schedule_experiment(
            arguments,
            insight_rows=live_experiment_insight_rows(),
            campaign_metrics=load_metrics(),
        )
        cron = ensure_experiment_review_cron(load_config(), experiment)
    except ValueError as exc:
        return agent_action_result(
            tool,
            False,
            chat_reply(chat_payload, f"No puedo programar el seguimiento todavía: {exc}", f"I cannot schedule the follow-up yet: {exc}"),
            blocked=True,
            reason="missing_experiment_detail",
        )
    if not cron.get("configured"):
        return agent_action_result(
            tool,
            False,
            chat_reply(
                chat_payload,
                f"Guardé el seguimiento de {experiment.get('name')}, pero no pude crear el recordatorio en Hermes: {cron.get('detail') or 'revisa Telegram y Hermes'}. Cuando la conexión esté lista lo volveré a programar.",
                f"I saved the follow-up for {experiment.get('name')}, but I could not create the Hermes reminder: {cron.get('detail') or 'check Telegram and Hermes'}. I will reconcile it when the connection is ready.",
            ),
            blocked=True,
            reason="experiment_cron_unavailable",
            experiment=experiment,
            cron=cron,
        )
    return agent_action_result(
        tool,
        True,
        chat_reply(
            chat_payload,
            f"Programé el seguimiento de {experiment.get('name')}. Primero revisaré entrega y después esperaré evidencia suficiente según el presupuesto; no declararé ganador antes de tiempo.",
            f"I scheduled the follow-up for {experiment.get('name')}. I will check delivery first, then wait for enough budget-adjusted evidence before declaring a winner.",
        ),
        experiment=experiment,
        cron=cron,
    )


def handle_list_experiment_reviews_tool(arguments, chat_payload, tool):
    reviews = experiment_review_payload(load_metrics())
    return agent_action_result(
        tool,
        False,
        chat_reply(
            chat_payload,
            f"Hay {reviews.get('active_count', 0)} experimento(s) en seguimiento y {reviews.get('decision_ready_count', 0)} con decisión lista.",
            f"There are {reviews.get('active_count', 0)} experiment(s) under review and {reviews.get('decision_ready_count', 0)} with a decision ready.",
        ),
        reviews=reviews,
    )


def handle_run_due_experiment_reviews_tool(arguments, chat_payload, tool):
    result = run_due_experiment_reviews(
        insight_rows=live_experiment_insight_rows(),
        campaign_metrics=load_metrics(),
        experiment_id=str(arguments.get("experiment_id") or "").strip(),
    )
    cron_results = []
    config = load_config()
    for experiment in result.get("experiments", []):
        if any(item.get("experiment_id") == experiment.get("id") for item in result.get("reviews", [])):
            cron_results.append(ensure_experiment_review_cron(config, experiment))
    if not result.get("reviewed_count"):
        reply = chat_reply(
            chat_payload,
            "No había una revisión vencida. Mantengo la próxima fecha programada y no sacaré conclusiones antes de tiempo.",
            "No review was due. I am keeping the next scheduled checkpoint and will not draw conclusions early.",
        )
    else:
        first = result["reviews"][0]
        reply = first.get("summary") or chat_reply(chat_payload, "Revisión completada.", "Review completed.")
        failed_cron = next((item for item in cron_results if item.get("needed") and not item.get("configured")), None)
        if failed_cron:
            reply += chat_reply(
                chat_payload,
                f" No pude dejar la próxima revisión en Hermes: {failed_cron.get('detail') or 'revisa la conexión de Telegram'}.",
                f" I could not schedule the next Hermes review: {failed_cron.get('detail') or 'check the Telegram connection'}.",
            )
    return agent_action_result(tool, True, reply, result=result, cron=cron_results)


def handle_save_optimization_research_tool(arguments, chat_payload, tool):
    try:
        item = save_research_item(arguments)
    except ValueError as exc:
        return agent_action_result(tool, False, str(exc), blocked=True, reason="invalid_research_item")
    return agent_action_result(
        tool,
        True,
        chat_reply(
            chat_payload,
            "Guardé la fuente como hipótesis de prueba. No puede ejecutar cambios de gasto por sí sola.",
            "I saved the source as a test hypothesis. It cannot trigger spend changes by itself.",
        ),
        item=item,
    )


def handle_list_optimization_research_tool(arguments, chat_payload, tool):
    research = load_research(include_expired=bool(arguments.get("include_expired")))
    return agent_action_result(
        tool,
        False,
        chat_reply(chat_payload, f"Hay {len(research.get('items', []))} fuente(s) de optimización vigentes.", f"There are {len(research.get('items', []))} active optimization source(s)."),
        research=research,
    )


def handle_review_signal_quality_tool(arguments, chat_payload, tool):
    review = review_signal_quality(arguments or {}, metrics=load_metrics(), language=chat_lang(chat_payload))
    return agent_action_result(
        tool,
        False,
        signal_quality_reply(review, chat_lang(chat_payload)),
        result=review,
    )


def summarize_cli_result(result, max_items=8):
    result = result or {}
    parsed = None
    try:
        parsed = json.loads(result.get("stdout") or "")
    except (TypeError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, dict):
        data = parsed.get("data", parsed)
        if isinstance(data, list):
            data = data[:max_items]
        parsed = data
    elif isinstance(parsed, list):
        parsed = parsed[:max_items]
    return {
        "ok": bool(result.get("executed")) and int(result.get("returncode") or 0) == 0 and not result.get("stderr"),
        "executed": bool(result.get("executed")),
        "returncode": result.get("returncode"),
        "stderr": str(result.get("stderr") or "")[:500],
        "data": redact_payload(parsed) if parsed is not None else None,
    }


def campaign_preflight(arguments, chat_payload):
    arguments = normalize_campaign_stack_arguments(arguments or {}, chat_payload)
    config = load_config()
    client = SocialFlowClient(config)
    account_id = config.ad_account_id or str(arguments.get("ad_account_id") or "").strip()
    signal = review_signal_quality(arguments, metrics=load_metrics(), language=chat_lang(chat_payload))
    placement_config = normalize_placement_config(arguments.get("placements") or arguments.get("placement_preset") or arguments.get("manual_placements"))
    creative_controls = normalize_creative_controls(arguments)
    budget_plan = normalize_budget_plan(arguments, float(arguments.get("daily_budget", 50) or 50))
    success_metrics = normalize_success_metrics(arguments)
    final_status = str(arguments.get("final_status") or "PAUSED").upper()
    active_confirmed = boolish(arguments.get("active_spend_confirmed")) is True
    status_plan = normalize_status_plan(arguments, final_status, active_confirmed)
    preflight = {
        "ok": True,
        "account_id": account_id,
        "checks": {
            "account_status": summarize_cli_result(client.marketing_status()),
            "rate_limits": summarize_cli_result(client.rate_limits()),
            "policy_preflight": summarize_cli_result(client.policy_preflight(arguments.get("intent") or arguments.get("objective") or "create Meta ad")),
        },
        "dry_run_preview": {
            "budget_plan": budget_plan,
            "success_metrics": success_metrics,
            "status_plan": status_plan,
            "placements": placement_config_summary(placement_config),
            "creative_controls": {
                "has_object_story_spec": bool(creative_controls.get("object_story_spec")),
                "has_image_hash": bool(creative_controls.get("image_hash")),
                "has_image_url": bool(creative_controls.get("image_url")),
                "has_video_url": bool(creative_controls.get("video_url")),
                "cta_link": creative_controls.get("cta_link"),
                "format": creative_controls.get("format"),
            },
            "signal_quality": {
                "status": signal.get("status"),
                "recommended_event": signal.get("recommended_event"),
                "safe_to_launch_active": signal.get("safe_to_launch_active"),
                "questions": signal.get("questions", []),
            },
        },
    }
    if account_id:
        preflight["checks"]["custom_audiences"] = summarize_cli_result(client.custom_audiences(account_id, limit=25))
        preflight["checks"]["existing_creatives"] = summarize_cli_result(client.creatives(account_id, limit=25))
        if arguments.get("include_recent_insights"):
            preflight["checks"]["recent_insights_by_placement_device"] = summarize_cli_result(
                client.insights(
                    "last_7d",
                    "ad",
                    fields="spend,impressions,clicks,actions,action_values",
                    breakdowns="publisher_platform,platform_position,impression_device",
                    limit=250,
                    timeout=90,
                )
            )
        else:
            metrics = load_metrics()
            preflight["checks"]["recent_insights_by_placement_device"] = {
                "ok": bool((metrics.get("breakdowns") or {}).get("placement_device")),
                "source": metrics.get("source") or "metrics_cache",
                "data": ((metrics.get("breakdowns") or {}).get("placement_device") or [])[:8],
                "skipped_live_read": True,
            }
    preflight["ok"] = all(
        check.get("ok") or check.get("skipped_live_read")
        for check in preflight.get("checks", {}).values()
        if isinstance(check, dict)
    )
    return preflight


def handle_preflight_campaign_tool(arguments, chat_payload, tool):
    preflight = campaign_preflight(arguments, chat_payload)
    return agent_action_result(
        tool,
        False,
        chat_reply(chat_payload, "Hice la revisión previa de cuenta, señal, presupuesto, placements y creatividad.", "I ran the preflight review for account, signal, budget, placements, and creative setup."),
        result=preflight,
    )


def handle_fetch_public_asset_tool(arguments, chat_payload, tool):
    result = fetch_public_asset_result(arguments)
    if result.get("ok"):
        asset_type = result.get("asset_type") or "recurso"
        if asset_type == "video":
            frame_count = int(result.get("video_frame_count") or 0)
            if frame_count:
                reply_es = f"Listo. Pude abrir el enlace público, descargar el video y extraer {frame_count} capturas para revisarlo visualmente. Lo puedo usar como fuente del anuncio o como referencia para preparar la campaña."
                reply_en = f"Done. I opened the public link, downloaded the video, and extracted {frame_count} frames for visual review. I can use it as the ad source or as campaign creative reference."
            else:
                reply_es = "Listo. Pude abrir el enlace público y detecté un video usable para creativos, pero no pude extraer capturas automáticas en este entorno. Lo puedo usar como fuente del anuncio; si quieres feedback visual fino, sube 2-4 capturas clave."
                reply_en = "Done. I opened the public link and detected a video usable for creatives, but I could not extract automatic frames in this environment. I can use it as the ad source; for detailed visual feedback, upload 2-4 key screenshots."
        elif asset_type == "image":
            reply_es = "Listo. Pude abrir el enlace público y guardar la imagen como referencia creativa."
            reply_en = "Done. I opened the public link and saved the image as a creative reference."
        else:
            title = result.get("title") or "el enlace"
            reply_es = f"Listo. Pude leer {title} y extraer contexto útil del enlace público."
            reply_en = f"Done. I read {title} and extracted useful context from the public link."
        return agent_action_result(tool, True, chat_reply(chat_payload, reply_es, reply_en), result=result)
    detail = result.get("error") or "No pude abrir ese enlace."
    return agent_action_result(
        tool,
        False,
        chat_reply(
            chat_payload,
            f"No pude usar ese enlace todavía: {detail} Si es de Google Drive, asegúrate de que esté compartido como público con enlace; también puedes subir el video directo por Telegram.",
            f"I could not use that link yet: {detail} If it is from Google Drive, make sure it is shared publicly by link; you can also upload the video directly in Telegram.",
        ),
        blocked=True,
        reason=result.get("reason") or "url_fetch_failed",
        result=result,
    )


def handle_export_report_tool(arguments, chat_payload, tool):
    return export_report_action(chat_payload, tool)


def handle_create_campaign_stack_tool(arguments, chat_payload, tool):
    arguments = normalize_campaign_stack_arguments(arguments or {}, chat_payload)
    required = ["name", "daily_budget", "landing_url"]
    missing = [key for key in required if not arguments.get(key)]
    if not any(arguments.get(key) for key in CAMPAIGN_CREATIVE_SOURCE_KEYS):
        missing.append("creative_image_path_or_url_or_story_spec")
    final_status = str(arguments.get("final_status") or "PAUSED").strip().upper()
    active_confirmed = boolish(arguments.get("active_spend_confirmed")) is True
    if requires_active_confirmation(arguments, final_status) and not active_confirmed:
        missing.append("active_spend_confirmed")
    if missing:
        return agent_action_result(
            tool,
            False,
            chat_reply(
                chat_payload,
                f"Puedo preparar la campaña, pero falta esto: {', '.join(missing)}. Dame ese dato y la dejo lista para aprobación.",
                f"I can prepare the campaign, but this is missing: {', '.join(missing)}. Send that detail and I will stage it for approval.",
            ),
            blocked=True,
            reason="missing_campaign_creation_detail",
            missing=missing,
        )
    require_cloud_license("Campaign creation requires an active license")
    result = create_campaign(arguments)
    return agent_action_result(
        tool,
        False,
        chat_reply(
            chat_payload,
            "Hice el analisis y preparé la campaña completa para aprobación. Revísala en Aprobaciones; si confirmas, se ejecutará con el estado final elegido.",
            "I analyzed the request and staged the full campaign for approval. Review it in Approvals; if confirmed, it will execute with the selected final status.",
        ),
        staged=True,
        result=result,
    )


def handle_build_audience_strategy_tool(arguments, chat_payload, tool):
    if not any(arguments.get(key) for key in ["product", "buyer", "locations", "interests", "data_sources"]):
        return agent_action_result(
            tool,
            False,
            chat_reply(
                chat_payload,
                "Puedo ayudarte, pero necesito al menos qué vendes, a quién le vendes y en qué país o ciudad quieres anunciar.",
                "I can help, but I need at least what you sell, who buys, and which country or city you want to target.",
            ),
            blocked=True,
            reason="missing_audience_brief",
        )
    result = create_audience_strategy(arguments, chat_lang(chat_payload))
    if chat_lang(chat_payload) == "es":
        similar_people = "ya se puede probar" if result["lookalike_readiness"]["ready"] else "todavía necesita más información"
        message = f"Listo. Preparé una recomendación de público para {result['product']}. El público de personas parecidas {similar_people}. Mi sugerencia es empezar llegando a personas nuevas y probar un grupo con intereses claros; cuando tengamos suficientes visitas o compradores, probamos personas parecidas."
    else:
        status = "ready" if result["lookalike_readiness"]["ready"] else "not ready yet"
        message = f"Done. I prepared an audience strategy for {result['product']}. Lookalike is {status}. Start with broad/Advantage+ plus one interest test, then use lookalike once the seed data is clean."
    return agent_action_result(tool, True, message, result=result)


def handle_init_brand_guides_tool(arguments, chat_payload, tool):
    product_name = str(arguments.get("product_name") or "").strip()
    if not product_name:
        return agent_action_result(
            tool,
            False,
            chat_reply(chat_payload, "Dime el nombre del producto u oferta principal y creo las guías base.", "Tell me the main product or offer name and I will create the base guides."),
            blocked=True,
            reason="missing_product_name",
        )
    result = initialize_brand_guides({"product_name": product_name})
    return agent_action_result(
        tool,
        True,
        chat_reply(
            chat_payload,
            f"Listo. Guardé la información base de {product_name}. Puedo usarla directamente para preparar imágenes y textos de anuncios; Codex CLI queda como complemento opcional que el dueño debe activar.",
            f"Done. I created the base guides for {product_name}. I can use them directly for creative work; Codex CLI remains an optional owner-enabled add-on.",
        ),
        result=result,
    )


def handle_save_agent_preferences_tool(arguments, chat_payload, tool):
    payload = dict(arguments or {})
    payload.setdefault("language", chat_lang(chat_payload))
    result = save_agent_preferences(payload, restart_gateway=False)
    ad_level = result.get("ad_experience_level") or ""
    style = result.get("communication_preference", {}).get("style") or ""
    if chat_lang(chat_payload) == "es":
        message = "Listo. Guardé cómo quieres que trabaje contigo"
        if ad_level or style:
            details = []
            if ad_level:
                details.append(f"experiencia en anuncios: {ad_level}")
            if style:
                details.append(f"detalle: {style}")
            message += " (" + ", ".join(details) + ")"
        message += ". Lo usaré en todos los negocios y canales."
    else:
        message = "Done. I saved how you want me to work with you"
        if ad_level or style:
            details = []
            if ad_level:
                details.append(f"ads experience: {ad_level}")
            if style:
                details.append(f"detail: {style}")
            message += " (" + ", ".join(details) + ")"
        message += ". I will use it across every business and channel."
    return agent_action_result(tool, True, message, result=result)


def handle_record_verified_signal_tool(arguments, chat_payload, tool):
    payload = dict(arguments or {})
    if isinstance(payload.get("items"), list):
        result = record_verified_signal_batch(payload.get("items"), VERIFIED_SIGNAL_LEDGER_FILE)
    else:
        result = record_verified_signal(payload, VERIFIED_SIGNAL_LEDGER_FILE)
    summary = result.get("summary") or {}
    privacy_needed = int(summary.get("privacy_confirmation_needed") or 0)
    if chat_lang(chat_payload) == "es":
        message = "Listo. Guardé la señal verificada en el registro local."
        if privacy_needed:
            message += " Antes de enviar señales o identificadores a Meta, confirma que el negocio actualizó su aviso/política de privacidad y tiene consentimiento o base legal."
        message += f" Total registrado: {summary.get('total_events', 0)}."
    else:
        message = "Done. I saved the verified signal in the local ledger."
        if privacy_needed:
            message += " Before sending signals or identifiers to Meta, confirm the business has updated its privacy notice/policy and has consent or legal basis."
        message += f" Total recorded: {summary.get('total_events', 0)}."
    log_action(
        "verified_signal_record",
        {
            "count": result.get("count", 1),
            "deduped": result.get("deduped", False),
            "stage": (result.get("record") or {}).get("stage"),
            "privacy_confirmation_needed": privacy_needed,
        },
        "completed",
    )
    return agent_action_result(tool, True, message, result=result)


def handle_get_verified_signal_summary_tool(arguments, chat_payload, tool):
    result = verified_signal_ledger_summary(VERIFIED_SIGNAL_LEDGER_FILE)
    return agent_action_result(
        tool,
        True,
        chat_reply(
            chat_payload,
            f"El registro tiene {result.get('total_events', 0)} señales. Hay {result.get('open_followups', 0)} seguimientos abiertos.",
            f"The ledger has {result.get('total_events', 0)} signals. There are {result.get('open_followups', 0)} open follow-ups.",
        ),
        result=result,
    )


def handle_verified_signal_feedback_prompt_tool(arguments, chat_payload, tool):
    result = verified_signal_feedback_prompt(VERIFIED_SIGNAL_LEDGER_FILE, chat_lang(chat_payload))
    return agent_action_result(tool, True, result.get("message", ""), result=result)


def handle_save_business_context_tool(arguments, chat_payload, tool):
    if not any(arguments.get(key) for key in ["main_offer", "ideal_customer", "current_stage", "what_to_improve", "success_goal", "business_type"]):
        return agent_action_result(
            tool,
            False,
            chat_reply(chat_payload, "Puedo guardar el perfil, pero necesito al menos oferta, cliente ideal o etapa actual.", "I can save the profile, but I need at least the offer, ideal customer, or current stage."),
            blocked=True,
            reason="missing_business_context",
        )
    result = save_business_context(arguments)
    phase = agent_onboarding_phase(result.get("profile"))
    return agent_action_result(
        tool,
        True,
        chat_reply(
            chat_payload,
            f"Listo. Guardé esa parte del negocio. Siguiente paso: {phase['next_step']}",
            f"Done. I saved that business context. Next step: {phase['next_step']}",
        ),
        result=result,
    )


def handle_save_brand_guide_tool(arguments, chat_payload, tool):
    raw_arguments = dict(arguments or {})
    arguments = normalize_general_payload(raw_arguments)
    image_paths = safe_image_paths(chat_payload)
    logo_signal = (
        "logo" in json.dumps(raw_arguments, ensure_ascii=False).lower()
        or "logo" in json.dumps(arguments, ensure_ascii=False).lower()
        or "logo" in str((chat_payload or {}).get("message", "")).lower()
    )
    if image_paths and logo_signal and not arguments.get("logo_path"):
        arguments = dict(arguments)
        try:
            logo = copy_brand_logo_from_path(image_paths[0], arguments.get("logo_notes") or "")
            arguments.update(logo)
        except ValueError:
            arguments.setdefault("logo_notes", "El comprador envio una imagen como referencia de logo, pero no pude guardarla como archivo de logo.")
    if not arguments.get("brand_name") and not arguments.get("offer"):
        return agent_action_result(
            tool,
            False,
            chat_reply(chat_payload, "Necesito al menos el nombre de marca o qué vende para guardar la guía.", "I need at least the brand name or what it sells to save the guide."),
            blocked=True,
            reason="missing_brand_core",
        )
    result = save_general_brand_memory(arguments)
    phase = agent_onboarding_phase()
    return agent_action_result(
        tool,
        True,
        chat_reply(chat_payload, f"Listo. Guardé la guía visual y verbal de la marca. Siguiente paso: {phase['next_step']}", f"Done. I saved the brand's visual and verbal guide. Next step: {phase['next_step']}"),
        result=result,
    )


def handle_save_product_guide_tool(arguments, chat_payload, tool):
    arguments = normalize_product_payload(arguments or {})
    if not arguments.get("name"):
        return agent_action_result(
            tool,
            False,
            chat_reply(chat_payload, "Dime el nombre del producto u oferta para guardar su ficha.", "Tell me the product or offer name so I can save its guide."),
            blocked=True,
            reason="missing_product_name",
        )
    result = save_product_brand_memory(arguments)
    phase = agent_onboarding_phase()
    return agent_action_result(
        tool,
        True,
        chat_reply(chat_payload, f"Listo. Guardé la ficha del producto. Siguiente paso: {phase['next_step']}", f"Done. I saved the product guide. Next step: {phase['next_step']}"),
        result=result,
    )


def handle_save_creative_references_tool(arguments, chat_payload, tool):
    image_paths = safe_image_paths(chat_payload)
    if image_paths and not arguments.get("generated_references"):
        arguments = dict(arguments)
        arguments["generated_references"] = "\n".join(image_paths)
    result = save_creative_references_memory(arguments)
    phase = agent_onboarding_phase()
    return agent_action_result(
        tool,
        True,
        chat_reply(chat_payload, f"Listo. Guardé las referencias creativas aprobadas. Siguiente paso: {phase['next_step']}", f"Done. I saved the approved creative references. Next step: {phase['next_step']}"),
        result=result,
    )


def handle_save_ads_onboarding_tool(arguments, chat_payload, tool):
    if not any(arguments.get(key) for key in ["promoted_before", "previous_ads_results", "campaign_goal", "first_strategy", "current_campaign_context", "budget_comfort", "countries", "offers_to_promote", "campaign_constraints", "success_metrics", "success_metrics_json", "key_results", "top_3_results", "primary_success_metric"]):
        return agent_action_result(
            tool,
            False,
            chat_reply(chat_payload, "Necesito saber qué ha promovido antes, resultados o meta de campaña para guardar esta etapa.", "I need to know what they promoted before, the results, or the campaign goal to save this stage."),
            blocked=True,
            reason="missing_ads_onboarding_context",
        )
    result = save_ads_campaign_onboarding(arguments)
    phase = result.get("phase") or agent_onboarding_phase(result.get("profile"))
    return agent_action_result(
        tool,
        True,
        chat_reply(chat_payload, f"Listo. Guardé el contexto de campañas. Siguiente paso: {phase['next_step']}", f"Done. I saved the campaign context. Next step: {phase['next_step']}"),
        result=result,
    )


def handle_save_ad_brief_tool(arguments, chat_payload, tool):
    arguments = normalize_ad_brief_payload(arguments or {})
    if not any(arguments.get(key) for key in ["name", "product_guide", "promotion", "campaign_name", "base_ad_name", "base_ad", "variation_axes", "creative_hypothesis", "formats"]):
        return agent_action_result(
            tool,
            False,
            chat_reply(chat_payload, "Necesito al menos nombre, promoción, campaña o anuncio base para guardar el brief.", "I need at least a name, promotion, campaign, or base ad to save the brief."),
            blocked=True,
            reason="missing_ad_brief_core",
        )
    if not arguments.get("variation_window"):
        arguments = dict(arguments)
        arguments["variation_window"] = chat_reply(
            chat_payload,
            "Probar variaciones claras sin cambiar la oferta, el beneficio principal ni el destino.",
            "Test clear variations without changing the offer, main benefit, or destination.",
        )
    result = save_ad_brief_memory(arguments)
    phase = agent_onboarding_phase()
    return agent_action_result(
        tool,
        True,
        chat_reply(chat_payload, f"Listo. Guardé el brief del anuncio. Siguiente paso: {phase['next_step']}", f"Done. I saved the ad brief. Next step: {phase['next_step']}"),
        result=result,
    )


def handle_codex_creative_plan_tool(arguments, chat_payload, tool):
    purpose = str((arguments or {}).get("purpose") or "ad_creative").strip().lower()
    readiness = creative_strategy_readiness(require_brief=False, purpose=purpose, payload=arguments)
    if not readiness["ready"]:
        return agent_action_result(
            tool,
            False,
            readiness["next_question"],
            blocked=True,
            reason="creative_strategy_not_ready",
            result={"readiness": readiness},
        )
    image_paths = safe_image_paths(chat_payload)
    if image_paths:
        arguments = dict(arguments)
        image_context = "\n\nImagen de referencia recibida en el chat. El agente debe usar su análisis visual como guía creativa; no asumas que Codex puede leer archivos locales directamente."
        arguments["request"] = (str(arguments.get("request") or "").strip() + image_context).strip()
        arguments["reference_image_paths"] = image_paths
    result = codex_creative_plan(arguments)
    if result.get("ok"):
        message = result.get("stdout") or "Codex devolvió un plan creativo."
        return agent_action_result(tool, True, message, result=result)
    return agent_action_result(
        tool,
        False,
        chat_reply(
            chat_payload,
            f"Todavía no pude usar Codex CLI: {result.get('error') or result.get('stderr') or 'revisa la configuración'}. Las guías quedan listas para cuando Codex esté configurado.",
            f"I could not use Codex CLI yet: {result.get('error') or result.get('stderr') or 'check setup'}. The guides remain ready for when Codex is configured.",
        ),
        blocked=True,
        result=result,
    )


def handle_codex_image_generate_tool(arguments, chat_payload, tool):
    image_paths = safe_image_paths(chat_payload)
    if image_paths:
        arguments = dict(arguments)
        arguments["reference_image_paths"] = image_paths
        arguments["reference_image_summary"] = (
            str(arguments.get("reference_image_summary") or "").strip()
            or "El comprador adjunto una imagen de referencia. El backend debe pasarla como imagen de entrada a Image 2/Codex Image, no solo describirla en texto."
        )
    result = codex_image_generate(arguments)
    if result.get("ok"):
        preview = result.get("preview_url") or ""
        reply = chat_reply(
            chat_payload,
            f"Listo. Generé una imagen final con Codex/Image y la dejé guardada en Creativos. Vista previa: {preview}",
            f"Done. I generated a final image with Codex/Image and saved it in Creatives. Preview: {preview}",
        )
        return agent_action_result(tool, True, reply, result=result)
    return agent_action_result(
        tool,
        False,
        chat_reply(
            chat_payload,
            f"Todavía no pude generar la imagen con Codex/Image: {result.get('error') or 'revisa la conexión de ChatGPT/Codex'}. No necesitas otra API de imágenes.",
            f"I could not generate the image with Codex/Image yet: {result.get('error') or 'check ChatGPT/Codex connection'}. No extra image API is required.",
        ),
        blocked=True,
        reason=result.get("reason", "creative_production_not_ready") if result.get("blocked") else result.get("reason", "codex_image_generate_failed"),
        result=result,
    )


def handle_save_existing_adset_tool(arguments, chat_payload, tool):
    return save_existing_adset_action(arguments.get("adset_id") or arguments.get("default_adset_id"), chat_payload)


def handle_campaign_mutation_tool(arguments, chat_payload, tool):
    campaign_id = arguments.get("campaign_id")
    campaign = campaign_by_id(load_metrics(), campaign_id)
    if not campaign:
        return agent_action_result(
            tool,
            False,
            chat_reply(chat_payload, "Necesito la campaña exacta antes de hacer eso. Usa el botón Preguntar en la tarjeta correcta o dime el nombre exacto.", "I need the exact campaign before doing that. Use the Ask button on the right card or tell me the exact name."),
            blocked=True,
            reason="missing_or_unknown_campaign_id",
        )
    if tool == "pause_campaign":
        return campaign_pause_action(campaign, chat_payload, tool)
    if tool == "resume_campaign":
        return campaign_resume_action(campaign, chat_payload, tool)
    if tool == "set_budget":
        try:
            new_budget = float(arguments.get("new_budget"))
        except (TypeError, ValueError):
            return agent_action_result(
                tool,
                False,
                chat_reply(chat_payload, f"¿A cuánto quieres dejar el presupuesto diario de {campaign.get('name')}?", f"What daily budget should {campaign.get('name')} use?"),
                blocked=True,
                reason="missing_new_budget",
            )
        return campaign_budget_action(campaign, new_budget, chat_payload, tool)
    if tool == "generate_creatives":
        return campaign_creative_action(campaign, chat_payload, tool, arguments)
    return None


AGENT_TOOL_HANDLERS = {
    "approval_guardrail": handle_agent_approval_tool,
    "approval_decision": handle_agent_approval_tool,
    "review_live_readiness": handle_review_live_readiness_tool,
    "run_daily_check": handle_run_daily_check_tool,
    "schedule_experiment_review": handle_schedule_experiment_review_tool,
    "list_experiment_reviews": handle_list_experiment_reviews_tool,
    "run_due_experiment_reviews": handle_run_due_experiment_reviews_tool,
    "save_optimization_research": handle_save_optimization_research_tool,
    "list_optimization_research": handle_list_optimization_research_tool,
    "review_signal_quality": handle_review_signal_quality_tool,
    "preflight_campaign": handle_preflight_campaign_tool,
    "fetch_public_asset": handle_fetch_public_asset_tool,
    "export_report": handle_export_report_tool,
    "create_campaign_stack": handle_create_campaign_stack_tool,
    "build_audience_strategy": handle_build_audience_strategy_tool,
    "init_brand_guides": handle_init_brand_guides_tool,
    "save_agent_preferences": handle_save_agent_preferences_tool,
    "record_verified_signal": handle_record_verified_signal_tool,
    "get_verified_signal_summary": handle_get_verified_signal_summary_tool,
    "verified_signal_feedback_prompt": handle_verified_signal_feedback_prompt_tool,
    "save_business_context": handle_save_business_context_tool,
    "save_brand_guide": handle_save_brand_guide_tool,
    "save_product_guide": handle_save_product_guide_tool,
    "save_creative_references": handle_save_creative_references_tool,
    "save_ads_onboarding": handle_save_ads_onboarding_tool,
    "save_ad_brief": handle_save_ad_brief_tool,
    "codex_creative_plan": handle_codex_creative_plan_tool,
    "codex_image_generate": handle_codex_image_generate_tool,
    "save_existing_adset": handle_save_existing_adset_tool,
    "pause_campaign": handle_campaign_mutation_tool,
    "resume_campaign": handle_campaign_mutation_tool,
    "set_budget": handle_campaign_mutation_tool,
    "generate_creatives": handle_campaign_mutation_tool,
}


AGENT_TOOL_ARGUMENT_WRAPPER_KEYS = {"arguments", "args", "kwargs", "payload", "fields", "data", "input"}


def parse_agent_tool_argument_mapping(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def normalize_agent_tool_arguments(arguments, depth=0):
    values = parse_agent_tool_argument_mapping(arguments)
    if not values or depth > 4:
        return values
    nested = {}
    direct = {}
    for key, value in values.items():
        if key in AGENT_TOOL_ARGUMENT_WRAPPER_KEYS:
            parsed = parse_agent_tool_argument_mapping(value)
            if parsed:
                nested.update(normalize_agent_tool_arguments(parsed, depth + 1))
                continue
        direct[key] = value
    return {**nested, **direct}


def execute_agent_tool(tool_request, chat_payload):
    if isinstance(tool_request, str):
        try:
            tool_request = json.loads(tool_request)
        except json.JSONDecodeError:
            tool_request = {}
    if not isinstance(tool_request, dict):
        return None
    tool = str(tool_request.get("tool") or "").strip()
    arguments = normalize_agent_tool_arguments(tool_request.get("arguments") or {})

    handler = AGENT_TOOL_HANDLERS.get(tool)
    if handler:
        return handler(arguments, chat_payload, tool)

    return {
        "type": tool or "unknown_tool",
        "executed": False,
        "blocked": True,
        "reason": "unsupported_tool",
        "reply": chat_reply(chat_payload, "Ese tipo de acción todavía no está disponible en el dashboard.", "That action is not available in the dashboard yet."),
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
    fatigue = fatigue_items(metrics.get("campaigns", []))
    decisions = decision_memory_payload(metrics, recommendations, fatigue)
    experiment_reviews = experiment_review_payload(metrics)
    config = load_config()
    ensure_dashboard_identity_backup(config)
    optimization_state = load_optimization_state()
    if not RESEARCH_FILE.exists():
        seed_current_research()
    setup = build_setup_status()
    current_license_status = license_status(config)
    ad_config = read_json(AD_CONFIG_FILE, {})
    destination = ad_config.get("creative", {}).get("destination", {})
    business_profile = read_json(BUSINESS_PROFILE_FILE, {})
    onboarding = onboarding_health(load_onboarding_state(), config, metrics, current_license_status, destination, business_profile)
    entitlements = license_entitlements()
    business_spaces = agency_spaces_payload()
    managed_accounts = managed_ad_accounts_payload()
    business_snapshot = business_context_snapshot(business_profile)
    main_codex_session = hermes_codex_session_status(config, timeout=3)
    image_codex_session = (
        hermes_codex_session_status(image_codex_config(config), timeout=3)
        if normalize_codex_image_source(getattr(config, "codex_image_source", "")) == "dedicated_chatgpt"
        else main_codex_session
    )
    codex_image_status = hermes_codex_image_status(timeout=2, config=config)
    codex_image_ready = bool(codex_image_status.get("ok"))
    image_home = resolved_codex_image_hermes_home(config)
    return {
        "metrics": metrics,
        "recommendations": recommendations,
        "brief": scheduled_brief_or_live(metrics, recommendations, business_profile),
        "fatigue": fatigue,
        "decision_memory": decisions,
        "experiment_reviews": experiment_reviews,
        "optimization": {
            "state": optimization_state,
            "unlock": optimization_unlock_status(optimization_state),
            "shopify": shopify_status(config),
            "business_outcomes": read_json(DATA_DIR / "business_outcomes.json", {}),
            "research": load_research(),
        },
        "actions": read_json(ACTIONS_FILE, [])[:20],
        "pending": read_json(PENDING_FILE, [])[:20],
        "created_campaigns": read_json(CREATED_FILE, [])[:10],
        "audience_strategy": read_json(AUDIENCE_FILE, {}),
        "brand_guides": guide_library(),
        "creative_refreshes": creative_studio_items(8),
        "creative_uploads": creative_upload_studio_items(8),
        "chat_history": load_chat_history(),
        "business_profile": business_profile,
        "business_snapshot": business_snapshot,
        "verified_signals": verified_signal_ledger_summary(VERIFIED_SIGNAL_LEDGER_FILE),
        "onboarding_questions": {
            "status": onboarding_interview_status(business_profile),
            "file_exists": ONBOARDING_QUESTIONS_FILE.exists(),
        },
        "agent_onboarding_phase": agent_onboarding_phase(business_profile),
        "license_entitlements": entitlements,
        "business_spaces": business_spaces,
        "active_workspace": active_workspace_payload(),
        "workspace_usage": workspace_usage_payload(),
        "managed_ad_accounts": managed_accounts,
        "business_binding": business_binding_payload(),
        "local_network_access": dashboard_network_access_payload(),
        "config": {
            "mode": config.mode,
            "communication_preference": {
                **communication_preference(
                    config.communication_style,
                    telegram_settings(config).get("language") or "es",
                    ad_experience_level=config.ad_experience_level,
                ),
                "configured": communication_style_is_configured(),
                "ad_experience_configured": ad_experience_is_configured(),
            },
            "notify_channel": config.notify_channel,
            "telegram_agent": telegram_settings(config),
            "daily_brief": {
                "mode": "hermes_cron",
                "time": config.daily_brief_time,
                "timezone": config.daily_brief_timezone,
                **hermes_gateway_status(config),
            },
            "dashboard_token_required": config.dashboard_token_required,
            "dashboard_token_set": dashboard_password_configured(config),
            "dashboard_password_required": config.dashboard_token_required,
            "dashboard_password_set": dashboard_password_configured(config),
            "live_actions_enabled": config.live_actions_enabled,
            "creative_studio": {
                "provider": "codex-image",
                "image_mode": "codex-image",
                "image_generation_ready": bool(codex_image_ready),
                "image_generation_provider": "codex_image" if codex_image_ready else "",
                "codex_image_ready": codex_image_ready,
                "codex_image_error": "" if codex_image_ready else codex_image_status.get("error", ""),
                "codex_image_source": getattr(config, "codex_image_source", "main_chatgpt"),
                "codex_image_dedicated": getattr(config, "codex_image_source", "") == "dedicated_chatgpt",
                "codex_image_home_configured": bool(image_home),
                "codex_image_model": getattr(config, "codex_image_hermes_model", config.hermes_model),
                "codex_image_account": image_codex_session.get("identity", {}),
                "codex_image_session_detail": image_codex_session.get("detail", ""),
                "codex_image_connected": bool(image_codex_session.get("ready")),
                "codex_planning_enabled": bool(config.codex_creative_enabled),
                "asset_policy": creative_asset_policy(),
            },
            "agent_model": {
                "provider": config.agent_chat_provider,
                "brain_provider": getattr(config, "agent_brain_provider", "openai_codex"),
                "base_url": config.agent_chat_base_url,
                "api": config.agent_chat_api,
                "api_key_set": bool(config.agent_chat_api_key),
                "model": config.agent_chat_model,
                "temperature": config.agent_chat_temperature,
                "hermes_model": config.hermes_model,
                "hermes_require_codex_auth": config.hermes_require_codex_auth,
                "chatgpt_connected": bool(main_codex_session.get("ready")),
                "chatgpt_account": main_codex_session.get("identity", {}),
                "chatgpt_session_detail": main_codex_session.get("detail", ""),
                "primary_brain": getattr(config, "agent_brain_provider", "openai_codex"),
                "codex_image_source": getattr(config, "codex_image_source", "main_chatgpt"),
                "codex_image_hermes_model": getattr(config, "codex_image_hermes_model", config.hermes_model),
                "codex_image_ready": codex_image_ready,
                "codex_image_error": "" if codex_image_ready else codex_image_status.get("error", ""),
                "codex_image_connected": bool(image_codex_session.get("ready")),
                "codex_image_account": image_codex_session.get("identity", {}),
                "codex_image_session_detail": image_codex_session.get("detail", ""),
            },
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
            "profitability_rules": decisions.get("profitability_rules", {}),
            "license_status": current_license_status,
            "license_entitlements": entitlements,
            "license_buyer_email_set": bool(config.license_buyer_email),
            "setup_values": {
                "license_key_set": bool(config.license_key),
                "license_buyer_email": config.license_buyer_email,
                "license_server_url_set": bool(config.license_server_url),
                "license_required_for_live": config.license_required_for_live,
                "meta_access_token_set": bool(config.meta_access_token),
                "ad_account_id": config.ad_account_id or ("" if str(ad_config.get("account", {}).get("id", "")).strip() in EXAMPLE_AD_ACCOUNT_IDS else ad_config.get("account", {}).get("id", "")),
                "managed_ad_accounts": managed_accounts,
                "meta_access_token_kind": config.meta_access_token_kind,
                "meta_access_token_saved_at": config.meta_access_token_saved_at,
                "page_id": destination.get("page_id", ""),
                "instagram_actor_id": destination.get("instagram_actor_id", ""),
                "default_adset_id": destination.get("default_adset_id", ""),
                "landing_url": destination.get("url", ""),
                "agent_chat_provider": config.agent_chat_provider,
                "agent_brain_provider": getattr(config, "agent_brain_provider", "openai_codex"),
                "agent_chat_base_url": config.agent_chat_base_url,
                "agent_chat_model": config.agent_chat_model,
                "agent_chat_api": config.agent_chat_api,
                "agent_chat_api_key_set": bool(config.agent_chat_api_key),
                "codex_image_source": getattr(config, "codex_image_source", "main_chatgpt"),
                "codex_image_hermes_model": getattr(config, "codex_image_hermes_model", config.hermes_model),
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
<title>Admira IA</title>
<link rel="stylesheet" href="/assets/dashboard/dashboard.css?v=1">
</head>
<body>
<section class="onboarding-flow" id="onboarding-flow" aria-modal="true" role="dialog"></section>
<header>
<div class="brand"><h1>Admira <span>IA</span></h1><div data-i18n="brand_subtitle">Self-hosted local/VPS operator for Meta Ads</div></div>
<nav class="tabs">
<button class="tab active" data-tab="overview" data-i18n="tab_overview">Overview</button>
<button class="tab" data-tab="setup" data-i18n="tab_setup">Setup</button>
<button class="tab" data-tab="creator" data-i18n="tab_creator">Creator</button>
<button class="tab" data-tab="audiences" data-i18n="tab_audiences">Audiences</button>
<button class="tab" data-tab="creatives" data-i18n="tab_creatives">Creatives</button>
<button class="tab" data-tab="reports" data-i18n="tab_reports">Reports</button>
</nav>
<div class="header-theme-slot"><div class="theme-switcher" id="theme-toggle" role="group" aria-label="Temas del dashboard"><button class="theme-chip active" type="button" data-theme="aurora" data-action-code="setDashboardTheme('aurora')">Aurora</button><button class="theme-chip" type="button" data-theme="sapphire" data-action-code="setDashboardTheme('sapphire')">Sapphire</button><button class="theme-chip" type="button" data-theme="ember" data-action-code="setDashboardTheme('ember')">Ember</button></div></div>
<button class="header-guide-btn" type="button" data-action-code="openUsageGuide()" aria-label="Guía rápida" title="Guía rápida">?</button>
<div class="status">
<select class="lang-select" id="language-select" aria-label="Language"><option value="es">ES</option><option value="en">EN</option></select>
<div class="pill"><span id="top-roas"></span> <strong id="s-roas">--</strong></div>
<div class="pill"><span id="top-cpa"></span> <strong id="s-cpa">--</strong></div>
<div class="pill"><span id="top-mode"></span> <strong id="s-mode">--</strong></div>
<div class="pill"><span data-i18n="updated">Updated</span> <strong id="s-updated">--</strong></div>
</div>
</header>
<section class="update-banner hidden" id="update-banner"></section>
<section class="deferred-onboarding-banner hidden" id="deferred-onboarding-banner"></section>
<main>
<aside class="col brief-zone">
<div class="brief-zone-heading"><button class="zone-label" id="toggle-left-panel" type="button" data-action-code="togglePanel('left')"><span data-i18n="zone_brief">Daily intelligence</span><small class="zone-badge" id="daily-brief-badge" data-i18n="new_brief">New</small><i class="panel-caret" aria-hidden="true"></i></button><button class="brief-schedule-button" id="daily-brief-schedule-button" type="button" data-action-code="openDailyBriefSchedule()" aria-label="Cambiar hora de la lectura diaria" title="Cambiar hora de la lectura diaria"><span aria-hidden="true">☀</span><strong id="daily-brief-schedule-label">Brief 08:00</strong></button></div>
<section class="section"><div class="head"><span>01</span><b id="business-profile-title">Perfil del negocio</b><button class="btn ask-btn" data-action-code="openChat(businessProfileChatPrompt())" data-i18n="ask_agent">Ask agent</button></div><div class="body" id="business-profile-panel"></div></section>
<section class="section"><div class="head"><span>02</span><b data-i18n="daily_brief">Daily Brief</b><button class="btn ask-btn" data-action-code="openChat(t('draft_catchup'))" data-i18n="ask_agent">Ask agent</button><button class="btn" data-action-code="runAgent()" data-i18n="run">Run</button></div><div class="body" id="brief"></div></section>
<section class="section"><div class="head"><span>03</span><b data-i18n="fatigue_monitor">Fatigue Monitor</b><button class="btn ask-btn" data-action-code="openChat(t('draft_fatigue'))" data-i18n="ask_agent">Ask agent</button></div><div class="body" id="fatigue"></div></section>
</aside>
<section class="col work-zone">
<div class="zone-label" data-i18n="zone_work">Campaign workspace</div>
<div id="tab-overview">
<div class="page-title"><div><h2 data-i18n="control_center">Control Center</h2><p data-i18n="control_subtitle">Daily decisions, risk signals, and ad account health in one place.</p></div><div class="dashboard-toolbar"><div class="view-switcher" role="group" aria-label="Vistas del dashboard"><button class="view-chip active" type="button" data-view="control" data-action-code="setDashboardView('control')">Control</button><button class="view-chip" type="button" data-view="timeline" data-action-code="setDashboardView('timeline')">Timeline</button><button class="view-chip" type="button" data-view="analytics" data-action-code="setDashboardView('analytics')">Overview</button><button class="view-chip" type="button" data-view="idle" data-action-code="setDashboardView('idle')">Showcase</button></div><button class="btn ask-btn" data-action-code="openChat(t('draft_where_are_we'))" data-i18n="ask_manager">Ask manager</button><button class="btn primary hidden" id="real-data-refresh" data-action-code="refreshInsights()">Actualizar datos reales</button><div class="signal" id="data-source-signal">--</div><div class="signal" data-i18n="safe_mode">Safe mode active</div></div></div>
<div class="dashboard-view" id="view-control">
<div class="kpis" id="kpis"></div>
<div class="campaign-grid" id="campaigns"></div>
</div>
<div class="dashboard-view hidden" id="view-timeline"></div>
<div class="dashboard-view hidden" id="view-analytics"></div>
<div class="dashboard-view hidden" id="view-idle"></div>
</div>
<div id="tab-setup" class="hidden">
<section class="section"><div class="head"><span>03</span><b data-i18n="setup_status">Setup Status</b><button class="btn ask-btn" data-action-code="openChat(t('draft_setup'))" data-i18n="ask_agent">Ask agent</button><button class="btn" data-action-code="load()" data-i18n="refresh">Refresh</button></div><div class="body"><div id="mode-control"></div><div id="guardrails-panel"></div><div id="onboarding-wizard"></div><div id="license-panel"></div><div id="meta-connection-panel"></div><div id="setup-config"></div><div id="chatgpt-panel"></div><div id="telegram-panel"></div><div id="communication-style-panel"></div><div id="local-network-panel"></div><div id="migration-panel"></div><div id="update-rollback-panel"></div><div id="cloud-access-panel"></div><div id="setup-summary"></div><div id="setup-sections"></div></div></section>
</div>
<div id="tab-creator" class="hidden">
<section class="section"><div class="head"><span>04</span><b data-i18n="campaign_creator">Campaign Creator</b></div><div class="body">
<section class="creator-hero"><span class="creative-kicker" data-i18n="creator_kicker">New campaign</span><h2 data-i18n="creator_title">Create a campaign</h2><p data-i18n="creator_body">Tell the agent what you sell, who should see it, and how much you can spend. It will organize the campaign and show it to you before anything can spend money.</p><div class="creator-hero-actions"><button class="btn primary" type="button" data-action-code="openChat(isEs()?'Quiero crear una campaña nueva. Hazme preguntas fáciles, una a la vez: qué vendo, a quién quiero llegar, cuánto puedo gastar al día, a qué página enviar a las personas y si quiero dejarla lista o activa después de aprobar. Si necesito imágenes o textos, guíame para prepararlos.':'I want to create a new campaign. Ask me simple questions one at a time: what I sell, who I want to reach, how much I can spend daily, where people should go, and whether it should remain ready or active after approval. If I need images or text, guide me through preparing them.')"><span data-i18n="creator_chat_cta">Create by talking to the agent</span></button></div></section>
<div class="creator-safety"><span class="creator-safety-mark">✓</span><div><b data-i18n="paused_draft_title">You decide before money is spent</b><p data-i18n="paused_draft_body">The agent prepares the campaign and asks for your approval. If you choose to leave it active, it can start spending only after you approve it.</p></div></div>
<details class="creator-manual-entry">
<summary><span><b data-i18n="creator_manual_title">I prefer to enter the details myself</b><small data-i18n="creator_manual_help">Optional: the agent can ask you these questions in chat.</small></span></summary>
<form id="campaign-form" class="creator-manual-form">
<section class="creator-form-section"><h3 data-i18n="creator_basic">What will you advertise?</h3><div class="form-grid">
<div class="field wide"><label data-i18n="campaign_name_simple">Name for this campaign</label><input name="name" data-i18n-placeholder="campaign_name_example" placeholder="Example: June promotion" required></div>
<div class="field"><label data-i18n="campaign_goal_simple">What should people do?</label><select name="objective"><option value="PURCHASES" data-i18n="goal_purchases">Buy</option><option value="LEADS" data-i18n="goal_contacts">Leave their details</option><option value="CONVERSIONS" data-i18n="goal_action">Take an action on your website</option></select></div>
<div class="field"><label data-i18n="landing_url_simple">Page people will visit</label><input name="landing_url" data-i18n-placeholder="landing_url_example" placeholder="https://..."></div>
<div class="field wide"><label data-i18n="primary_text_simple">Message people will read</label><input name="primary_text" data-i18n-placeholder="primary_text_example" placeholder="Example: Discover the offer made for your business."></div>
<div class="field"><label data-i18n="headline_simple">Short title</label><input name="headline" data-i18n-placeholder="headline_example" placeholder="Example: See the offer"></div>
<div class="field"><label data-i18n="image_simple">Image already prepared, if you have one</label><input name="creative_image_path" data-i18n-placeholder="image_path_example" placeholder="Optional"></div>
</div></section>
<section class="creator-form-section"><h3 data-i18n="creator_people_budget">Who will see it and how much can it spend?</h3><div class="form-grid">
<div class="field"><label data-i18n="daily_budget_simple">Maximum to spend each day</label><input type="number" name="daily_budget" value="75" min="10"></div>
<div class="field"><label data-i18n="total_budget_simple">Maximum to spend in total</label><input type="number" name="total_budget" value="2250" min="100"></div>
<input type="hidden" name="targeting_locations_json" id="campaign-targeting-locations-json" value="[]">
<input type="hidden" name="targeting_interests_json" id="campaign-targeting-interests-json" value="[]">
<div class="targeting-workbench wide">
<div class="targeting-intro"><div><b data-i18n="targeting_picker_title">Choose the audience with Meta options</b><p data-i18n="targeting_picker_body">Search locations and interests from Meta, or let the agent suggest the safest audience.</p></div><button class="btn ask-btn" type="button" data-action-code="openChat(isEs()?'Ayúdame a elegir quién debería ver esta campaña. Pregúntame qué vendo, dónde vendo y cuánto puedo gastar. Si ya me conocen, dime cómo aprovecharlo.':'Help me choose who should see this campaign. Ask what I sell, where I sell, and how much I can spend. If people already know my business, tell me how to use that.')"><span data-i18n="targeting_agent_cta">Ask the agent</span></button></div>
<div class="targeting-mode-grid"><button class="targeting-mode-card active" type="button" data-action-code="setTargetingMode('broad')"><b data-i18n="targeting_broad_title">Broad audience</b><span data-i18n="targeting_broad_body">Best default: age, location, creative and Meta learning.</span></button><button class="targeting-mode-card" type="button" data-action-code="setTargetingMode('guided')"><b data-i18n="targeting_guided_title">Guided interests</b><span data-i18n="targeting_guided_body">Use Meta interests as hints when the niche is clear.</span></button><button class="targeting-mode-card" type="button" data-action-code="openChat(isEs()?'Revisa si ya tengo información de personas que visitaron, escribieron o compraron. Si no, dime qué me falta para mostrar anuncios a personas parecidas.':'Check whether I already have information from people who visited, wrote, or bought. If not, tell me what I need to show ads to similar people.')"><b data-i18n="targeting_warm_title">People who know you / similar people</b><span data-i18n="targeting_warm_body">Only when visitor, page, Instagram or permitted customer data is ready.</span></button></div>
<div class="targeting-search-grid">
<div class="targeting-picker"><label data-i18n="locations_simple">Where those people live</label><div class="targeting-search-row"><input id="targeting-location-query" data-i18n-placeholder="locations_example" placeholder="Example: Colombia"><button class="btn" type="button" data-action-code="searchTargeting('location')" data-i18n="targeting_search">Search Meta</button></div><div id="targeting-location-results" class="targeting-results"></div><div id="targeting-location-selected" class="targeting-chips"></div></div>
<div class="targeting-picker"><label data-i18n="interests_simple">Things they may be interested in</label><div class="targeting-search-row"><input id="targeting-interest-query" data-i18n-placeholder="interests_example" placeholder="Example: online stores"><button class="btn" type="button" data-action-code="searchTargeting('interest')" data-i18n="targeting_search">Search Meta</button></div><div id="targeting-interest-results" class="targeting-results"></div><div id="targeting-interest-selected" class="targeting-chips"></div></div>
</div>
<details class="targeting-manual-fallback"><summary data-i18n="targeting_manual_fallback">If Meta search is not available</summary><div class="form-grid"><div class="field"><label data-i18n="locations_simple">Where those people live</label><input name="locations" data-i18n-placeholder="locations_example" placeholder="Example: Colombia"></div><div class="field"><label data-i18n="interests_simple">Things they may be interested in</label><input name="interests" data-i18n-placeholder="interests_example" placeholder="Example: online stores"></div></div></details>
</div>
<div class="field"><label data-i18n="age_min_simple">Youngest age</label><input type="number" name="age_min" value="25"></div>
<div class="field"><label data-i18n="age_max_simple">Oldest age</label><input type="number" name="age_max" value="54"></div>
</div></section>
<section class="creator-form-section"><h3 data-i18n="creator_decision">How should it be prepared?</h3><div class="form-grid">
<div class="field"><label data-i18n="creative_variations_simple">How many ideas to compare?</label><input type="number" name="creative_variations" value="3" min="1" max="10"></div>
<div class="field"><label data-i18n="compare_options_simple">Compare those ideas?</label><select name="ab_test"><option value="true" data-i18n="compare_yes">Yes, compare them</option><option value="" data-i18n="compare_no">No, use one idea</option></select></div>
<div class="field wide"><label data-i18n="after_approval_simple">After you approve it</label><select name="final_status"><option value="PAUSED" data-i18n="ready_not_spending">Leave it ready without spending</option><option value="ACTIVE" data-i18n="active_after_approval">Start showing the ads and spending the chosen budget</option></select></div>
<div class="field wide"><label class="creator-confirm"><input type="checkbox" name="active_spend_confirmed" value="true"> <span data-i18n="confirm_active_spend">Only if I choose to turn it on: I understand that after approving, this campaign may start spending my chosen budget.</span></label></div>
</div></section>
<details class="creator-advanced"><summary data-i18n="creator_meta_optional">Only if you already know this Meta detail</summary><div class="form-grid"><div class="field wide"><label data-i18n="pixel_optional">Meta tracking number (Pixel ID), optional</label><input name="pixel_id" data-i18n-placeholder="optional" placeholder="Optional"></div></div></details>
<p class="creator-submit-note" data-i18n="creator_review_notice">Nothing will be created in your Meta account until you review and approve this request.</p>
<button class="btn primary" type="submit" data-i18n="stage_campaign">Send for my approval</button>
</form>
</details>
</div></section>
</div>
<div id="tab-audiences" class="hidden">
<section class="section"><div class="head"><span>05</span><b data-i18n="audience_builder">Audience Builder</b><button class="btn ask-btn" data-action-code="openChat(t('draft_audience'))" data-i18n="ask_agent">Ask agent</button></div><div class="body">
<form id="audience-form" class="form-grid">
<div class="field wide"><label data-i18n="what_sell">What do you sell?</label><input name="product" data-i18n-placeholder="audience_product_example" placeholder="Example: online course for small business owners"></div>
<div class="field wide"><label data-i18n="who_buys">Who buys today?</label><input name="buyer" data-i18n-placeholder="audience_buyer_example" placeholder="Example: owners who need more sales"></div>
<div class="field"><label data-i18n="objective">Objective</label><select name="objective"><option value="Compras">Compras</option><option value="Leads">Leads</option><option value="Mensajes">Mensajes</option></select></div>
<div class="field"><label data-i18n="locations">Locations</label><input name="locations" data-i18n-placeholder="audience_locations_example" placeholder="Example: Colombia or Mexico"></div>
<div class="field"><label data-i18n="age_range">Age range</label><input name="age" placeholder="25-54"></div>
<div class="field"><label data-i18n="budget_level">Budget level</label><select name="budget_level"><option value="small" data-i18n="budget_small">Small</option><option value="medium" data-i18n="budget_medium">Medium</option><option value="scale" data-i18n="budget_large">Large</option></select></div>
<div class="field wide"><label data-i18n="interests">Interests</label><input name="interests" data-i18n-placeholder="audience_interests_example" placeholder="Example: beauty, education, local stores"></div>
<div class="field wide"><label data-i18n="data_sources">Data sources</label><input name="data_sources" data-i18n-placeholder="audience_data_example" placeholder="Example: people who wrote on Instagram or buyers"></div>
<div class="field wide"><label><input name="consent" type="checkbox"> <span data-i18n="consent_upload">I have consent to use customer emails/phones if I upload them later.</span></label></div>
<div class="field wide"><label data-i18n="notes">Notes</label><input name="notes" data-i18n-placeholder="optional" placeholder="Optional"></div>
<div class="field wide"><button class="btn primary" type="submit" data-i18n="build_audience">Build Audience Strategy</button></div>
</form>
<div id="audience-result" data-style-code="margin-top:12px"></div>
</div></section>
</div>
<div id="tab-creatives" class="hidden">
<section class="creative-studio-hero"><div class="creative-studio-copy"><span class="creative-kicker" id="creative-studio-kicker">Ideas para anuncios</span><h2 id="creative-studio-title">Crea tus anuncios</h2><p id="creative-studio-description"></p><div class="creative-studio-actions"><button class="btn primary" id="creative-agent-cta" data-action-code="openChat(isEs()?'Quiero crear imágenes y textos para un anuncio. Puede ser para una promoción, una campaña nueva o para mejorar un anuncio que ya funciona. Ayúdame a definir la idea creativa.':'I want to create images and text for an ad. It may be for a promotion, a new campaign, or to improve an ad that already works. Help me define the creative idea.')"></button><button class="btn" id="creative-refresh-cta" data-action-code="generateRefresh()"></button></div></div><div class="creative-studio-pulse" id="creative-studio-pulse"></div></section>
<div class="creative-studio-layout">
<aside class="creative-studio-memory"><div id="brand-guides-panel"></div></aside>
<section class="creative-gallery-panel"><div class="creative-gallery-head"><div><span class="creative-kicker" id="creative-library-kicker"></span><h3 id="creative-library-title"></h3></div><button class="btn ask-btn" data-action-code="openChat(isEs()?'Revisa mis ideas de anuncios y dime cuál probarías primero y por qué.':'Review my current ad ideas and tell me which one you would test first and why.')"><span data-i18n="ask_agent">Ask agent</span></button></div><div id="creative-list"></div></section>
</div>
<section class="creative-approval-panel"><div class="creative-gallery-head"><div><span class="creative-kicker" id="creative-upload-kicker"></span><h3 id="creative-upload-title"></h3></div></div><div id="upload-list"></div></section>
</div>
<div id="tab-reports" class="hidden">
<section class="section"><div class="head"><span>07</span><b data-i18n="campaign_comparison">Campaign Comparison</b><button class="btn" data-action-code="exportCsv()" data-i18n="export_csv">Export CSV</button></div><div class="body"><table><thead><tr><th data-i18n="campaign">Campaign</th><th id="th-spend"></th><th id="th-roas"></th><th id="th-cpa"></th><th id="th-ctr"></th><th data-i18n="status">Status</th></tr></thead><tbody id="report-rows"></tbody></table></div></section>
</div>
</section>
<aside class="col rail">
<button class="zone-label" id="toggle-right-panel" type="button" data-action-code="togglePanel('right')"><span data-i18n="zone_actions">Approvals and activity</span><i class="panel-caret" aria-hidden="true"></i></button>
<section class="section"><div class="head"><span>05</span><b data-i18n="budget_optimizer">Budget Optimizer</b><button class="btn ask-btn" data-action-code="openChat(t('draft_budget'))" data-i18n="ask_agent">Ask agent</button></div><div class="body"><table id="recs-table"><thead><tr><th data-i18n="campaign">Campaign</th><th data-i18n="now">Now</th><th data-i18n="rec">Rec</th><th></th></tr></thead><tbody id="recs"></tbody></table><div class="mobile-recs" id="recs-mobile"></div></div></section>
<section class="section"><div class="head"><span>06</span><b data-i18n="pending_approvals">Pending Approvals</b></div><div class="body" id="pending"></div></section>
<section class="section"><div class="head"><span>07</span><b data-i18n="action_log">Action Log</b></div><div class="body" id="actions"></div></section>
</aside>
</main>
<div class="toast" id="toast"></div>
<section class="confirm-overlay" id="confirm-overlay" aria-modal="true" role="dialog"></section>
<section class="guide-overlay" id="guide-overlay" aria-modal="true" role="dialog"></section>
<section class="brand-memory-overlay" id="brand-memory-overlay" aria-modal="true" role="dialog" aria-labelledby="brand-memory-title">
<div class="brand-memory-modal">
<header class="brand-memory-head"><div><span class="creative-kicker" id="brand-memory-kicker">Lo que sabe el agente</span><h2 id="brand-memory-title">Marca, productos y anuncios</h2><p id="brand-memory-subtitle"></p></div><button class="btn brand-memory-close" type="button" data-action-code="closeBrandMemory()" aria-label="Cerrar">×</button></header>
<div class="brand-memory-workspace"><nav class="brand-memory-nav" id="brand-memory-nav"></nav><div class="brand-memory-editor" id="brand-memory-editor"></div></div>
</div>
</section>
<div class="floating-tip" id="floating-tip" role="tooltip"></div>
<form class="agent-chat-bar" id="agent-chat-bar">
<div class="agent-bar-mark">AI</div>
<button class="agent-bar-expand" type="button" data-action-code="openChat()" aria-label="Abrir conversación completa" title="Abrir conversación completa">⌃</button>
<textarea id="agent-bar-input" rows="1" data-i18n-placeholder="chat_fab"></textarea>
<button class="agent-bar-send" type="submit" aria-label="Send">↑</button>
</form>
<section class="chat-panel" id="chat-panel" aria-live="polite">
<div class="chat-head"><div class="chat-avatar">AI</div><div class="chat-title"><b data-i18n="chat_title">Meta Ads Manager</b><span data-i18n="chat_subtitle">Ask for catchups, actions, or explanations.</span></div><button class="btn" data-action-code="newChatConversation()" data-i18n="new_chat">New chat</button><button class="btn chat-close" data-action-code="closeChat()" aria-label="Cerrar conversación" title="Cerrar conversación">×</button></div>
<div class="chat-log" id="chat-log"></div>
<div class="chat-quick"><button class="chip" data-action-code="openChat(t('draft_where_are_we'))" data-i18n="quick_status">Where are we?</button><button class="chip" data-action-code="openChat(t('draft_budget'))" data-i18n="quick_budget">Review budget</button><button class="chip" data-action-code="openChat(t('draft_fatigue'))" data-i18n="quick_fatigue">Check fatigue</button></div>
<form class="chat-form" id="chat-form"><textarea id="chat-input" rows="2"></textarea><button class="btn primary" type="submit" data-i18n="send">Send</button></form>
</section>
<section class="unlock-overlay" id="unlock-overlay" aria-modal="true" role="dialog">
<div class="unlock-card">
<h2 id="unlock-title" data-i18n="unlock_title">Unlock dashboard</h2>
<p id="unlock-body" data-i18n="unlock_body">Enter the password for this dashboard to continue.</p>
<form class="unlock-form" id="unlock-form">
<label for="unlock-password"><span id="unlock-password-label" data-i18n="dashboard_password">Dashboard password</span></label>
<input id="unlock-password" type="password" autocomplete="current-password">
<label id="unlock-confirm-wrap" class="hidden" for="unlock-confirm-password"><span id="unlock-confirm-label" data-i18n="dashboard_password_confirm">Repeat password</span></label>
<input id="unlock-confirm-password" class="hidden" type="password" autocomplete="new-password">
<label><input id="remember-device" type="checkbox" checked> <span data-i18n="remember_device">Remember this device</span></label>
<div class="unlock-error" id="unlock-error"></div>
<button class="btn primary" id="unlock-submit" type="submit" data-i18n="unlock_button">Unlock dashboard</button>
</form>
</div>
</section>
<script src="/assets/dashboard/dashboard.js?v=1" defer></script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    HTML_PATHS = {"/", "/dashboard"}
    PROTECTED_GET_PATHS = {"/api/dashboard", "/api/export", "/api/report", "/api/setup", "/api/social/auth-status", "/api/social/accounts", "/api/update/snapshots", "/api/creative-asset", "/api/brand-asset"}
    PROTECTED_POST_PATHS = {"/api/unlock", "/api/dashboard-password", "/api/action", "/api/campaigns", "/api/targeting/search", "/api/audience-strategy", "/api/business-profile", "/api/business-profile/scan", "/api/business-profile/questions", "/api/business-profile/links", "/api/social/token", "/api/social/default-account", "/api/social/discover-assets", "/api/agent-model/connect", "/api/agent-model/disconnect", "/api/agent-model/connect-status", "/api/agent-model/connect-input", "/api/brand-guides/init", "/api/brand-guides/general", "/api/brand-guides/logo", "/api/brand-guides/product", "/api/ad-briefs", "/api/codex/creative-plan", "/api/codex/image-generate", "/api/setup-config", "/api/guardrails", "/api/profitability-rules", "/api/optimization/settings", "/api/optimization/unlock", "/api/shopify/config", "/api/shopify/test", "/api/shopify/sync", "/api/daily-brief/schedule", "/api/telegram/config", "/api/telegram/detect", "/api/telegram/test", "/api/license/activate", "/api/onboarding/communication-style", "/api/onboarding/complete", "/api/onboarding/skip", "/api/onboarding/reset", "/api/agency/spaces", "/api/agency/spaces/switch", "/api/approve", "/api/reject", "/api/chat", "/api/chat/reset", "/api/creative-refresh", "/api/creative-storage/clear", "/api/stage-upload", "/api/execute-upload", "/api/mode", "/api/migration/export", "/api/migration/import", "/api/local-network-access", "/api/cloud-access/refresh", "/api/update/check", "/api/update/apply", "/api/update/rollback"}
    ONBOARDING_OPEN_GETS = {"/api/dashboard", "/api/setup"}
    ONBOARDING_OPEN_POSTS = {"/api/dashboard-password", "/api/business-profile", "/api/business-profile/scan", "/api/business-profile/questions", "/api/business-profile/links", "/api/license/activate", "/api/agent-model/connect", "/api/agent-model/connect-status", "/api/agent-model/connect-input", "/api/onboarding/communication-style", "/api/onboarding/complete"}
    GET_JSON_ROUTES = {
        "/api/dashboard": dashboard_payload,
        "/api/export": export_csv,
        "/api/report": lambda: run_daily_agent()[1],
        "/api/setup": build_setup_status,
        "/api/social/auth-status": social_auth_status,
        "/api/social/login-url": social_login_url,
        "/api/social/accounts": social_marketing_accounts,
        "/api/update/snapshots": lambda: {"ok": True, "result": list_update_snapshots()},
    }
    POST_JSON_ROUTES = {
        "/api/unlock": lambda payload: {"unlocked": True, **create_dashboard_session(remember=bool(payload.get("remember_device", True)))},
        "/api/dashboard-password": set_dashboard_password,
        "/api/social/token": social_save_facebook_token,
        "/api/social/default-account": social_set_default_account,
        "/api/social/discover-assets": social_discover_assets,
        "/api/agent-model/connect": connect_agent_model,
        "/api/agent-model/disconnect": disconnect_agent_model,
        "/api/agent-model/connect-status": agent_model_connect_status,
        "/api/agent-model/connect-input": agent_model_connect_input,
        "/api/targeting/search": meta_targeting_search,
        "/api/audience-strategy": lambda payload: create_audience_strategy(payload, payload.get("language", "es")),
        "/api/business-profile": save_business_context,
        "/api/business-profile/scan": scan_business_website,
        "/api/business-profile/questions": generate_business_context_questions,
        "/api/business-profile/links": save_business_links_for_agent,
        "/api/brand-guides/init": initialize_brand_guides,
        "/api/brand-guides/general": save_general_brand_memory,
        "/api/brand-guides/logo": save_brand_logo_asset,
        "/api/brand-guides/product": save_product_brand_memory,
        "/api/ad-briefs": save_ad_brief_memory,
        "/api/codex/creative-plan": codex_creative_plan,
        "/api/codex/image-generate": codex_image_generate,
        "/api/setup-config": save_setup_config,
        "/api/guardrails": save_guardrails,
        "/api/daily-brief/schedule": save_daily_brief_schedule,
        "/api/profitability-rules": save_profitability_rule_settings,
        "/api/optimization/settings": save_optimization_settings,
        "/api/optimization/unlock": unlock_optimization,
        "/api/shopify/config": save_shopify_config,
        "/api/shopify/test": test_shopify_settings,
        "/api/shopify/sync": sync_shopify_outcomes,
        "/api/migration/import": restore_migration_archive,
        "/api/update/check": lambda _payload: request_update_release(),
        "/api/update/apply": lambda _payload: apply_official_update(),
        "/api/update/rollback": restore_update_snapshot,
        "/api/local-network-access": set_local_network_access,
        "/api/agency/spaces": create_agency_space,
        "/api/agency/spaces/switch": switch_agency_space,
        "/api/telegram/config": save_telegram_config,
        "/api/telegram/detect": lambda _payload: detect_telegram_chats(),
        "/api/telegram/test": lambda _payload: test_telegram_connection(),
        "/api/license/activate": activate_license_now,
        "/api/onboarding/agent-preferences": save_agent_preferences,
        "/api/onboarding/communication-style": save_communication_style,
        "/api/onboarding/complete": complete_onboarding,
        "/api/onboarding/skip": lambda _payload: skip_onboarding(),
        "/api/onboarding/reset": lambda _payload: reset_onboarding(),
        "/api/verified-signals/record": lambda payload: record_verified_signal(payload, VERIFIED_SIGNAL_LEDGER_FILE),
        "/api/verified-signals/batch": lambda payload: record_verified_signal_batch(payload.get("items") if isinstance(payload, dict) else [], VERIFIED_SIGNAL_LEDGER_FILE),
        "/api/verified-signals/summary": lambda _payload: verified_signal_ledger_summary(VERIFIED_SIGNAL_LEDGER_FILE),
        "/api/verified-signals/feedback-prompt": lambda payload: verified_signal_feedback_prompt(VERIFIED_SIGNAL_LEDGER_FILE, (payload or {}).get("language") or "es"),
        "/api/reject": lambda payload: reject_pending(payload.get("approval_id"), payload.get("reason") or "Rejected from dashboard"),
        "/api/mode": set_mode,
        "/api/chat/reset": lambda _payload: reset_chat_history(),
        "/api/creative-storage/clear": lambda _payload: clear_temporary_creative_assets(),
    }
    POST_SPECIAL_ROUTES = {
        "/api/action": "post_action",
        "/api/campaigns": "post_campaigns",
        "/api/migration/export": "post_migration_export",
        "/api/cloud-access/refresh": "post_cloud_access_refresh",
        "/api/approve": "post_approve",
        "/api/chat": "post_chat",
        "/api/creative-refresh": "post_creative_refresh",
        "/api/stage-upload": "post_stage_upload",
        "/api/execute-upload": "post_execute_upload",
    }

    def send_security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "base-uri 'self'; "
            "object-src 'none'; "
            "frame-ancestors 'none'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' https://graph.facebook.com https://api.openai.com https://auth.openai.com https://*.openai.com; "
            "script-src 'self'; "
            "script-src-elem 'self'; "
            "script-src-attr 'none'; "
            "style-src 'self'; "
            "style-src-elem 'self'; "
            "style-src-attr 'none'; "
            "form-action 'self'",
        )

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_security_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_binary(self, body, filename, content_type="application/octet-stream"):
        self.send_response(200)
        self.send_security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_preview_image(self, path):
        body = path.read_bytes()
        self.send_response(200)
        self.send_security_headers()
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "image/png")
        self.send_header("Content-Disposition", f'inline; filename="{path.name}"')
        self.send_header("Cache-Control", "private, max-age=300")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_public_asset(self, path):
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'inline; filename="{path.name}"')
        cache_control = "private, no-store" if path.suffix.lower() in {".css", ".js"} else "private, max-age=300"
        self.send_header("Cache-Control", cache_control)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self):
        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_security_headers()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_local_network_disabled(self, parsed):
        message = "Ver desde mi teléfono está apagado. Actívalo desde Configuración en el computador principal y vuelve a abrir este enlace."
        if parsed.path in self.HTML_PATHS:
            body = f"""<!DOCTYPE html><html lang=\"es\"><head><meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Acceso local apagado</title><link rel=\"stylesheet\" href=\"/assets/dashboard/local-disabled.css?v=1\"></head><body><main><h1>Acceso por Wi‑Fi apagado</h1><p>{message}</p><p>El teléfono debe estar en el mismo Wi‑Fi y el dashboard seguirá protegido por contraseña.</p></main></body></html>""".encode("utf-8")
            self.send_response(403)
            self.send_security_headers()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_json({"error": message}, 403)

    def local_network_request_allowed(self):
        config = load_config()
        if install_environment_label() == "cloud" or config.lan_access_enabled:
            return True
        return request_host_is_local(self.headers.get("Host", ""))

    def send_redirect(self, url):
        self.send_response(302)
        self.send_security_headers()
        self.send_header("Location", url)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def post_body_limit(self, path):
        return MIGRATION_POST_LIMIT_BYTES if path == "/api/migration/import" else DEFAULT_POST_LIMIT_BYTES

    def read_body(self, path):
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        if length > self.post_body_limit(path):
            raise ValueError("La solicitud es demasiado grande.")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def provided_token(self, parsed, payload=None):
        return self.headers.get("X-Dashboard-Token") or ""

    def require_auth(self, parsed, payload=None):
        config = load_config()
        provided = self.provided_token(parsed, payload)
        if dashboard_session_valid(provided) or dashboard_token_valid(config, provided):
            return True
        self.send_json({"error": "dashboard password required"}, 401)
        return False

    def onboarding_open_without_password(self, path):
        if load_onboarding_state().get("completed") or path not in self.ONBOARDING_OPEN_POSTS:
            return False
        config = load_config()
        return not dashboard_password_configured(config)

    def auth_required_for_post(self, path):
        if path == "/api/dashboard-password" and not dashboard_password_configured(load_config()):
            return False
        return path in self.PROTECTED_POST_PATHS and not self.onboarding_open_without_password(path)

    def auth_required_for_get(self, path):
        if path not in self.PROTECTED_GET_PATHS:
            return False
        config = load_config()
        if not load_onboarding_state().get("completed") and not dashboard_password_configured(config):
            return path not in self.ONBOARDING_OPEN_GETS
        return bool(config.dashboard_token_required and dashboard_password_configured(config))

    def send_ok_result(self, result):
        self.send_json({"ok": True, "result": result})

    def post_action(self, payload):
        if payload.get("action") not in {"run_agent"}:
            require_license_unlock("live dashboard action")
        result = apply_action(payload)
        if isinstance(result, tuple):
            result = result[0]
        self.send_ok_result(result)

    def post_campaigns(self, payload):
        require_cloud_license("Campaign creation requires an active license")
        self.send_ok_result(create_campaign(payload))

    def post_migration_export(self, _payload):
        filename, body = create_migration_archive()
        self.send_binary(body, filename, "application/gzip")

    def post_cloud_access_refresh(self, _payload):
        self.send_ok_result(refresh_digitalocean_access(public_client_ip(self)))

    def post_approve(self, payload):
        require_license_unlock("approval execution")
        self.send_ok_result(approve_pending(payload.get("approval_id")))

    def post_chat(self, payload):
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
        chat_payload.setdefault("agent_onboarding_phase", dashboard.get("agent_onboarding_phase", {}))
        chat_payload.setdefault("channel", "dashboard")
        chat_result = route_chat_approval_decision(chat_payload)
        if not chat_result:
            chat_result = handle_creative_memory_wizard(chat_payload)
        if not chat_result:
            chat_result = route_chat_action(chat_payload)
        if not chat_result:
            chat_result = agent_chat(load_config(), chat_payload)
            tool_result = execute_agent_tool(chat_result.get("tool_request"), chat_payload)
            if tool_result:
                chat_result["routed_action"] = tool_result
                chat_result["reply"] = tool_result.get("reply") or chat_result.get("reply")
        chat_result["history"] = append_chat_turn(payload.get("message", ""), chat_result.get("reply", ""))
        self.send_ok_result(chat_result)

    def post_creative_refresh(self, payload):
        metrics = load_metrics()
        generate_images = load_config().creative_live
        campaign_id = payload.get("campaign_id")
        product_guide = str(payload.get("product_guide") or "").strip()
        ad_brief = str(payload.get("ad_brief") or "").strip()
        campaigns = metrics.get("campaigns", [])
        if campaign_id:
            campaigns = [campaign for campaign in campaigns if campaign.get("id") == campaign_id]
        else:
            campaigns = [campaign for campaign in campaigns if campaign.get("health") in {"fatigue", "losing"}]
            if not campaigns and metrics.get("campaigns"):
                campaigns = [sorted(metrics.get("campaigns", []), key=lambda c: c.get("roas", 0))[0]]
        results = []
        for campaign in campaigns:
            plan, manifest_path = generate_creative_refresh(campaign, generate_images=generate_images, product_guide=product_guide, ad_brief=ad_brief)
            results.append({"id": plan["id"], "manifest_path": str(manifest_path)})
        self.send_ok_result(results)

    def post_stage_upload(self, payload):
        payload_result, payload_path, approval = stage_upload(payload.get("manifest_path"), payload.get("variant_id", "v1"), payload.get("ratios") or ["1:1"])
        self.send_ok_result({
            "payload_path": str(payload_path),
            "status": payload_result["status"],
            "missing_requirements": payload_result["missing_requirements"],
            "approval": approval,
        })

    def post_execute_upload(self, payload):
        require_license_unlock("creative upload execution")
        self.send_ok_result(execute_upload_payload(payload.get("payload_path")))

    def do_GET(self):
        parsed = urlparse(self.path)
        if not self.local_network_request_allowed() and parsed.path != "/assets/dashboard/local-disabled.css":
            self.send_local_network_disabled(parsed)
            return
        if self.auth_required_for_get(parsed.path) and not self.require_auth(parsed):
            return
        if parsed.path in self.HTML_PATHS:
            self.send_html()
        elif parsed.path == "/api/social/login":
            self.send_redirect(social_login_url()["url"])
        elif parsed.path == "/api/creative-asset":
            asset_id = (parse_qs(parsed.query).get("id") or [""])[0]
            try:
                self.send_preview_image(creative_asset_path(asset_id))
            except ValueError as exc:
                self.send_json({"error": str(exc)}, 404)
        elif parsed.path == "/api/brand-asset":
            asset_id = (parse_qs(parsed.query).get("id") or [""])[0]
            try:
                self.send_preview_image(brand_asset_path(asset_id))
            except ValueError as exc:
                self.send_json({"error": str(exc)}, 404)
        elif parsed.path.startswith("/assets/"):
            try:
                self.send_public_asset(public_asset_path(parsed.path.removeprefix("/assets/")))
            except ValueError as exc:
                self.send_json({"error": str(exc)}, 404)
        elif parsed.path in self.GET_JSON_ROUTES:
            self.send_json(self.GET_JSON_ROUTES[parsed.path]())
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        try:
            parsed = urlparse(self.path)
            if not self.local_network_request_allowed():
                self.send_local_network_disabled(parsed)
                return
            payload = self.read_body(parsed.path)
            if self.auth_required_for_post(parsed.path) and not self.require_auth(parsed, payload):
                return
            if parsed.path in self.POST_JSON_ROUTES:
                self.send_ok_result(self.POST_JSON_ROUTES[parsed.path](payload))
            elif parsed.path in self.POST_SPECIAL_ROUTES:
                getattr(self, self.POST_SPECIAL_ROUTES[parsed.path])(payload)
            else:
                self.send_json({"error": "not found"}, 404)
        except Exception as exc:
            self.send_json({"error": client_error_message(exc)}, 400)

    def log_message(self, fmt, *args):
        print(f"[dashboard] {self.address_string()} - {fmt % args}")


def write_static_snapshot():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not METRICS_FILE.exists():
        save_metrics(sample_metrics() if env_bool("ADMIRO_ALLOW_DEMO_METRICS", False) else empty_meta_metrics())
    with open(DASHBOARD_HTML_FILE, "w", encoding="utf-8") as handle:
        handle.write(HTML)


def main():
    global CURRENT_DASHBOARD_BIND_HOST, CURRENT_DASHBOARD_BIND_PORT
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
    CURRENT_DASHBOARD_BIND_HOST = host
    CURRENT_DASHBOARD_BIND_PORT = port
    print("Admira IA dashboard")
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
