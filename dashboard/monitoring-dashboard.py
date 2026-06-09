#!/usr/bin/env python3
"""
Meta Ads Agent - web dashboard and daily agent runner.

Run:
    python3 dashboard/monitoring-dashboard.py

Open:
    http://127.0.0.1:7871
"""
import csv
import base64
import ipaddress
import json
import mimetypes
import os
import py_compile
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
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
from codex_brand_guides import (
    build_codex_creative_prompt,
    call_codex_cli,
    ensure_brand_guides,
    guide_library,
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
from graph_executor import execute_upload_payload
from hermes_bridge import hermes_codex_ready, hermes_environment, safe_image_paths
from license import activate_license, default_device_id, license_status, mark_license_install_state, normalize_license_entitlements, validate_license_key
from local_store import now_iso, read_json, write_json, write_private_json
from meta_upload import recent_uploads, stage_upload
from product_config import ENV_FILE, load_config
from security import dashboard_token_valid, is_local_host, is_public_bind, redact_payload
from setup_status import build_setup_status
from social_flow_client import SocialFlowClient
from telegram_agent import bot_request as telegram_bot_request
from telegram_agent import reset_polling_state as reset_telegram_polling_state
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
ONBOARDING_QUESTIONS_FILE = DATA_DIR / "Onboarding questions.md"
AGENT_ONBOARDING_PLAN_FILE = DATA_DIR / "Agent onboarding plan.md"
ADS_ONBOARDING_FILE = DATA_DIR / "Ads campaign onboarding.md"
INDIVIDUAL_BINDING_FILE = DATA_DIR / "individual_business_binding.json"
AGENCY_SPACES_FILE = DATA_DIR / "agency_spaces.json"
AGENCY_SPACES_DIR = DATA_DIR / "agency_spaces"
AD_CONFIG_FILE = ROOT_DIR / "ad-config.json"
DASHBOARD_HTML_FILE = DATA_DIR / "dashboard.html"
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
CURRENT_DASHBOARD_BIND_HOST = ""
CURRENT_DASHBOARD_BIND_PORT = 0
CREATIVE_ASSET_ROOT = OUTPUT_DIR / "creatives"
CREATIVE_ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
PORT = 7871
TARGET_CPA = 50.0
TELEGRAM_THREAD = None
TELEGRAM_STOP = None
TELEGRAM_FINGERPRINT = None
HERMES_LOGIN_OUTPUT_LIMIT = 12000
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
    "started_at": "",
    "updated_at": "",
    "proc": None,
    "fd": None,
    "command": "",
}
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
    "business_profile.json",
    "Onboarding questions.md",
    "Agent onboarding plan.md",
    "Ads campaign onboarding.md",
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
BUSINESS_OUTPUT_DIRS = [
    OUTPUT_DIR / "creatives",
    OUTPUT_DIR / "uploads",
    OUTPUT_DIR / "telegram_uploads",
]

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
    ]:
        target = root / relative
        if target.exists():
            target.unlink()


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
        "Este respaldo mueve la memoria local del Meta Ads Agent a otro equipo.\n"
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
    if source.name in {".git", "node_modules", "__pycache__", ".pytest_cache", ".DS_Store"}:
        return True
    if source.name.endswith((".pyc", ".log")):
        return True
    if relative.parts and relative.parts[0] in {"release", "node_modules", ".git"}:
        return True
    if relative.parts[:3] == ("dashboard", "data", "update-snapshots"):
        return True
    if relative.parts[:3] == ("dashboard", "data", "import-backups"):
        return True
    if relative.parts == ("dashboard", "data", "dashboard.html"):
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
    env_value = os.environ.get("META_ADS_AGENT_VERSION", "").strip()
    if env_value:
        return env_value
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "v1"
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
    preserved = {".env", "ad-config.json", "dashboard/data", "logs", "output"}
    for item in source.iterdir():
        relative = item.relative_to(base).as_posix()
        if relative in preserved or any(relative.startswith(prefix + "/") for prefix in preserved):
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
    load_config()
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
        VERSION_FILE.write_text(str(release["latest_version"]).strip() + "\n", encoding="utf-8")
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
    for key, value in values.items():
        os.environ[key] = str(value)


def license_entitlements():
    status = license_status(load_config())
    if not status.get("valid"):
        status = {**status, "plan": "individual", "max_devices": 1, "workspace_limit": 1, "features": []}
    return normalize_license_entitlements(status)


def business_identity(payload=None):
    config = load_config()
    ad_config = read_json(AD_CONFIG_FILE, {})
    destination = ad_config.get("creative", {}).get("destination", {})
    incoming = payload or {}
    return {
        "ad_account_id": str(incoming.get("ad_account_id") or config.ad_account_id or ad_config.get("account", {}).get("id", "")).strip(),
        "page_id": str(incoming.get("page_id") or destination.get("page_id", "")).strip(),
        "instagram_actor_id": str(incoming.get("instagram_actor_id") or destination.get("instagram_actor_id", "")).strip(),
    }


def changed_business_fields(payload):
    current = business_identity()
    changes = {}
    for key in ["ad_account_id", "page_id", "instagram_actor_id"]:
        incoming = str(payload.get(key) or "").strip() if key in payload else ""
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
    return {
        **identity,
        **binding,
        "locked": not license_entitlements().get("is_agency") and bool(binding or load_onboarding_state().get("completed")),
    }


def create_agency_space(payload):
    limits = license_entitlements()
    if not limits.get("can_use_agency_workspaces", bool(limits.get("is_agency"))):
        raise ValueError("Tu licencia Individual cuida un solo negocio activo. Para manejar varios clientes, usa Licencia Agencia.")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("Escribe el nombre del cliente o negocio.")
    registry = agency_registry()
    workspace_limit = int(limits.get("workspace_limit") or 1)
    if len(registry["spaces"]) >= workspace_limit:
        raise ValueError("Alcanzaste el limite de espacios de esta licencia. Para manejar mas clientes, contacta soporte para ampliar tu Licencia Agencia.")
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
        raise ValueError("Cambiar entre clientes requiere Licencia Agencia.")
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


def save_profitability_rule_settings(payload):
    rules = persist_profitability_rules(payload)
    log_action("profitability_rules_update", rules, "completed")
    return {"saved": True, "rules": rules}


def save_telegram_config(payload):
    old_config = load_config()
    limits = license_entitlements()
    registry = agency_registry()
    if limits.get("is_agency") and not limits.get("can_use_multi_telegram_profiles", bool(limits.get("is_agency"))) and len(registry.get("spaces", [])) > 1:
        raise ValueError("Varios perfiles de Telegram por cliente requieren Licencia Agencia completa.")
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
    status["listener_started"] = ensure_telegram_listener()
    if status.get("enabled") and status.get("bot_configured") and status.get("chat_id"):
        profile = read_json(BUSINESS_PROFILE_FILE, {})
        if isinstance(profile, dict) and not profile.get("telegram_onboarding_message_sent_at"):
            try:
                write_onboarding_questions_memory(profile, "pending")
                send_telegram_message(
                    config,
                    status["chat_id"],
                    "Listo, ya puedo hablar contigo por Telegram.\n\n"
                    "Cuando quieras, respóndeme: quiero completar mi negocio.\n"
                    "Te haré preguntas fáciles, una por una: primero tu negocio, luego el estilo de tus creativos y después tus campañas.",
                )
                profile["telegram_onboarding_message_sent_at"] = now_iso()
                write_json(BUSINESS_PROFILE_FILE, profile)
                status["onboarding_message_sent"] = True
            except Exception as exc:
                status["onboarding_message_error"] = str(exc)[:220]
    log_action("telegram_config_save", {"enabled": status["enabled"], "bot_configured": status["bot_configured"], "chat_id_set": bool(status["chat_id"])}, "completed")
    return status


def ensure_telegram_listener():
    global TELEGRAM_THREAD, TELEGRAM_STOP, TELEGRAM_FINGERPRINT
    config = load_config()
    status = telegram_settings(config)
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
    TELEGRAM_THREAD = threading.Thread(target=run_telegram_listener, args=(TELEGRAM_STOP,), name="telegram-agent", daemon=True)
    TELEGRAM_THREAD.start()
    TELEGRAM_FINGERPRINT = fingerprint
    return True


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
    send_telegram_message(config, status["chat_id"], "Conexion lista. Ya puedes hablar con tu manager IA desde Telegram.")
    log_action("telegram_test_message", {"chat_id_set": True}, "completed")
    return {"sent": True}


def activate_license_now(payload=None):
    payload = payload or {}
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
    config = load_config()
    version = config.meta_graph_api_version or "v24.0"
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
    return f"{shlex.quote(cli)} model"


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
    return "select provider" in lower and (
        "select by number" in lower
        or "enter to confirm" in lower
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


def hermes_codex_provider_choice(output):
    parsed = hermes_choice_number_for_label(output, ["openai codex", "chatgpt/codex", "chatgpt codex"])
    if parsed:
        return parsed
    if hermes_provider_prompt_visible(output):
        return str(os.environ.get("HERMES_CODEX_PROVIDER_CHOICE") or "6").strip() or "6"
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
            "detail": "Hermes pidió elegir entre OpenAI Codex y OpenAI API. Estoy confirmando OpenAI Codex automáticamente.",
            "auto_note": "OpenAI Codex confirmado." if auto_codex_subprovider_sent else "Confirmando OpenAI Codex automáticamente.",
            "login_code": "",
        }
    if hermes_provider_prompt_visible(cleaned):
        return {
            "phase": "provider_selection",
            "needs_input": manual_input,
            "title": "Eligiendo OpenAI Codex",
            "detail": "Hermes pidió elegir proveedor. Estoy seleccionando OpenAI Codex automáticamente para que no tengas que leer la terminal.",
            "auto_note": "OpenAI Codex se selecciona automáticamente." if not auto_provider_sent else state.get("auto_note") or "OpenAI Codex seleccionado. Continúo con el siguiente paso.",
            "login_code": "",
        }
    if hermes_model_prompt_visible(cleaned):
        return {
            "phase": "model_selection",
            "needs_input": manual_input,
            "title": "Eligiendo modelo recomendado",
            "detail": "Hermes pidió elegir modelo. Estoy aceptando el modelo recomendado por defecto.",
            "auto_note": "Modelo recomendado confirmado." if auto_model_sent else "Confirmando el modelo recomendado automáticamente.",
            "login_code": "",
        }
    return {
        "phase": "waiting",
        "needs_input": manual_input,
        "title": "Hermes está trabajando",
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
            payload = "1\n"
        elif not provider_sent:
            provider_choice = hermes_codex_provider_choice(output)
            if provider_choice:
                HERMES_LOGIN_STATE["auto_provider_sent"] = True
                HERMES_LOGIN_STATE["phase"] = "provider_selection"
                HERMES_LOGIN_STATE["auto_note"] = "Estoy eligiendo OpenAI Codex automáticamente."
                payload = f"{provider_choice}\n"
            else:
                payload = ""
        elif not model_sent and hermes_model_prompt_visible(output):
            HERMES_LOGIN_STATE["auto_model_sent"] = True
            HERMES_LOGIN_STATE["phase"] = "model_selection"
            HERMES_LOGIN_STATE["auto_note"] = "Estoy confirmando el modelo recomendado automáticamente."
            payload = "\n"
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
        "echo 'Conectando ChatGPT/Codex para Admiro AI...'\n"
        "echo 'Si Hermes pregunta por proveedor, elige OpenAI Codex / ChatGPT.'\n"
        "echo\n"
        f"{command}\n"
        "status=$?\n"
        "echo\n"
        "if [ $status -eq 0 ]; then\n"
        "  echo 'Listo. Vuelve al dashboard y toca Revisar conexion.'\n"
        "else\n"
        "  echo 'Hermes terminó con un aviso. Si ves un enlace o código, complétalo y vuelve al dashboard.'\n"
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
            ps_command = (
                f"Set-Location -LiteralPath '{ps_root}'; "
                "Write-Host 'Conectando ChatGPT/Codex para Admiro AI...'; "
                "Write-Host 'Si Hermes pregunta por proveedor, elige OpenAI Codex / ChatGPT.'; "
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


def hermes_browserless_snapshot(config=None):
    config = config or load_config()
    ready, auth_detail = hermes_codex_ready(config)
    if not ready:
        nudge_hermes_browserless_autodrive()
    with HERMES_LOGIN_LOCK:
        state = dict(HERMES_LOGIN_STATE)
        proc = state.get("proc")
        running = bool(proc and proc.poll() is None)
        output = state.get("output", "")
    if ready:
        return hermes_connect_response(
            "completed",
            "ChatGPT/Codex conectado",
            "Hermes ya tiene lista la conexión con ChatGPT/Codex en esta instalación.",
            mode="browserless_ready",
            command=hermes_browserless_shell_command(config),
            output=output or auth_detail,
            running=False,
            job_id=state.get("id") or "",
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
                needs_input=False,
                phase=prompt["phase"],
                auto_note=prompt["auto_note"],
                log=False,
            )
        return hermes_connect_response(
            "needs_terminal",
            "Hermes necesita una respuesta",
            "La sesión terminó antes de quedar conectada. Revisa el detalle, vuelve a tocar Conectar ahora o usa una API compatible.",
            mode="browserless_finished",
            command=hermes_browserless_shell_command(config),
            output=output or auth_detail,
            running=False,
            job_id=state.get("id") or "",
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
    config = load_config()
    ready, auth_detail = hermes_codex_ready(config)
    with HERMES_LOGIN_LOCK:
        if HERMES_LOGIN_STATE.get("id") != session_id:
            return
        HERMES_LOGIN_STATE["status"] = "completed" if ready else "needs_terminal"
        HERMES_LOGIN_STATE["title"] = "ChatGPT/Codex conectado" if ready else "Hermes necesita una respuesta"
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


def start_hermes_browserless_login(config):
    cli_path = shutil.which(str(getattr(config, "hermes_cli", "") or "hermes").strip() or "hermes")
    if not cli_path:
        return hermes_connect_response(
            "not_installed",
            "Hermes no está instalado",
            "Instala o actualiza Admiro AI para incluir Hermes, y vuelve a tocar Conectar ahora.",
            mode="missing_runtime",
            command=hermes_browserless_shell_command(config),
        )
    ready, auth_detail = hermes_codex_ready(config)
    if ready:
        return hermes_connect_response(
            "completed",
            "ChatGPT/Codex conectado",
            "Hermes ya tiene lista la conexión con ChatGPT/Codex.",
            mode="already_ready",
            command=hermes_browserless_shell_command(config),
            output=auth_detail,
            running=False,
        )
    with HERMES_LOGIN_LOCK:
        proc = HERMES_LOGIN_STATE.get("proc")
        running = bool(proc and proc.poll() is None)
    if running:
        return hermes_browserless_snapshot(config)
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
                    "detail": "Sesion de Hermes abierta dentro de este servidor.",
                    "output": "",
                    "phase": "starting",
                    "auto_note": "Estoy preparando Hermes para usar OpenAI Codex.",
                    "auto_provider_sent": False,
                    "auto_codex_subprovider_sent": False,
                    "auto_model_sent": False,
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
            "Abrí Hermes dentro de este servidor. Voy a elegir OpenAI Codex y el modelo recomendado automáticamente. Si aparece un enlace, ábrelo aquí.",
            mode="browserless_started",
            command=hermes_browserless_shell_command(config),
            running=True,
            job_id=session_id,
            needs_input=False,
            phase="starting",
            auto_note="Estoy preparando Hermes para usar OpenAI Codex.",
        )
    except Exception as exc:
        return hermes_connect_response(
            "needs_terminal",
            "No pude abrir la sesión segura",
            "Este servidor no permitió abrir Hermes desde el dashboard. Usa una API compatible o revisa la instalación con soporte.",
            mode="browserless_error",
            command=hermes_browserless_shell_command(config),
            output=str(exc),
        )


def agent_model_connect_status(payload=None):
    return hermes_browserless_snapshot(load_config())


def agent_model_connect_input(payload=None):
    text = str((payload or {}).get("input") or "")
    if not text.strip():
        return hermes_browserless_snapshot(load_config())
    if not text.endswith("\n"):
        text += "\n"
    with HERMES_LOGIN_LOCK:
        fd = HERMES_LOGIN_STATE.get("fd")
        proc = HERMES_LOGIN_STATE.get("proc")
        running = bool(proc and proc.poll() is None and fd is not None)
    if not running:
        return hermes_browserless_snapshot(load_config())
    os.write(fd, text.encode("utf-8", errors="replace"))
    return hermes_browserless_snapshot(load_config())


def probe_hermes_model_login(config):
    cli = str(getattr(config, "hermes_cli", "") or "hermes").strip() or "hermes"
    try:
        result = subprocess.run([cli, "model", "--no-browser"], cwd=str(ROOT_DIR), text=True, capture_output=True, timeout=10, check=False)
    except FileNotFoundError:
        return hermes_connect_response(
            "not_installed",
            "Hermes no está instalado",
            "Instala o actualiza Admiro AI para incluir Hermes, y vuelve a tocar Conectar ahora.",
            mode="missing_runtime",
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        output = "\n".join([stdout, stderr]).strip()
        return hermes_connect_response(
            "needs_login" if extract_urls_from_text(output) else "needs_terminal",
            "Hermes necesita terminar el login",
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
            "Hermes terminó correctamente. Ahora revisa la conexión y prueba el chat.",
            mode="probe_completed",
            command=hermes_browserless_shell_command(config),
            output=output,
        )
    return hermes_connect_response(
        "needs_login" if extract_urls_from_text(output) else "needs_terminal",
        "Falta terminar la conexión",
        "Hermes respondió, pero todavía necesita que termines el login o elijas el proveedor.",
        mode="probe_failed",
        command=hermes_browserless_shell_command(config),
        output=output,
    )


def connect_agent_model(payload=None):
    update_env_values({"AGENT_CHAT_PROVIDER": "hermes", "AGENT_BRAIN_PROVIDER": "openai_codex", "HERMES_REQUIRE_CODEX_AUTH": "true"})
    config = load_config()
    if launch_hermes_terminal(config):
        return hermes_connect_response(
            "terminal_opened",
            "Abrí la terminal",
            "Sigue la ventana que se abrió. Cuando termines, vuelve al dashboard y toca Revisar conexión.",
            mode="terminal",
        )
    return start_hermes_browserless_login(config)


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
        hermes_model = str(payload.get("hermes_model") or "").strip()
        env_updates["HERMES_MODEL"] = hermes_model
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
        "Lee esta web publica con la herramienta de navegador o retrieval de Hermes si esta disponible: "
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
    updated["agent_scan_detail"] = "Hermes browser/retrieval enrichment applied"
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
        "Analiza estos links publicos con browser/retrieval de Hermes si esta disponible:\n"
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
    updated["agent_scan_detail"] = "Hermes browser/retrieval enrichment applied to public links"
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


def branding_creatives_status():
    library = guide_library()
    general = (library.get("general") or {}).get("fields") or {}
    has_product = bool(library.get("product_count"))
    visual_fields = [
        general.get("colors"),
        general.get("typography"),
        general.get("visual_style"),
        general.get("references"),
        library.get("creative_references_text"),
    ]
    ready = bool(library.get("general_exists") and has_product and any(str(item or "").strip() for item in visual_fields))
    if ready:
        return "completed"
    if library.get("general_exists") or has_product or library.get("creative_references_exists"):
        return "in_progress"
    return "pending"


def ads_campaign_onboarding_status(profile=None):
    profile = profile if isinstance(profile, dict) else read_json(BUSINESS_PROFILE_FILE, {})
    if not isinstance(profile, dict):
        profile = {}
    if profile.get("ads_onboarding_completed_at"):
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
    if business != "completed":
        phase = "business_discovery"
        next_step = "Entrevistar al cliente sobre negocio, oferta, cliente ideal, etapa actual, problemas y meta de 30 dias."
    elif branding != "completed":
        phase = "branding_creatives_creation"
        next_step = "Usar el skill branding creatives creation para definir estilo visual, referencias, paletas, fuentes y reglas de creativos."
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

## Fases

1. business_discovery
   - Entender que vende, oferta principal, productos/servicios prioritarios, cliente ideal, etapa actual, dolores, meta de 30 dias y tono comercial.
   - Preguntar una sola cosa a la vez.
   - Guardar lo aprendido con `save_business_context`.

2. branding_creatives_creation
   - Usar el skill `branding creatives creation`.
   - Buscar referencias visuales de anuncios del nicho con las herramientas web/browser disponibles.
   - Proponer estilos, paletas, fuentes, sensaciones y reglas visuales.
   - Distinguir que es continuo para toda la marca y que cambia por producto, servicio o campana.
   - Si el cliente aprueba referencias encontradas, generadas o ambas, guardarlas con `save_creative_references`.
   - Guardar la guia general con `save_brand_guide` y fichas por producto con `save_product_guide`.

3. ads_campaign_onboarding
   - Entender que anuncio antes, que resultados tuvo, que cree que fallo, que quiere mantener, presupuesto, paises, ofertas y restricciones.
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

Instrucciones para el agente:
- Habla en espanol latino natural, como manager calido y directo.
- Haz una sola pregunta a la vez.
- No hagas una lista enorme de preguntas en un solo mensaje.
- Usa los links guardados como contexto, pero deja que el cliente corrija todo.
- Documenta lo aprendido en el perfil del negocio y en las guias de marca/producto/brief cuando corresponda.
- Si falta informacion, pregunta lo minimo necesario para poder actuar.
- Cuando el negocio este claro, pasa a la fase de branding/creativos; no saltes directo a campanas si faltan estilo, referencias, colores o reglas visuales.
- Despues de branding, pregunta por anuncios/campanas anteriores y guarda aprendizajes antes de proponer la estrategia inicial.

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
    ]
    changed = {}
    for key in allowed:
        value = str(payload.get(key) or "").strip()
        if value:
            profile[key] = value[:1600]
            changed[key] = profile[key]
    if payload.get("ads_onboarding_complete") or payload.get("completed"):
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
    config = load_config()
    product_guide = str(payload.get("product_guide") or "").strip()
    request = str(payload.get("request") or "").strip()
    if not request:
        request = "Crear una estrategia visual y prompts de imagen para Meta Ads usando las guias de marca."
    if not getattr(config, "codex_creative_enabled", False):
        result = {
            "ok": False,
            "error": "La capa opcional de Codex CLI esta desactivada. Actívala solo si aceptas que Codex CLI es un agente local con acceso adicional al equipo.",
        }
        log_action("codex_creative_plan", {"product_guide": product_guide, "ok": False, "error": result["error"]}, "blocked")
        return result
    try:
        prompt = build_codex_creative_prompt(product_guide, request, str(payload.get("ad_brief") or "").strip())
        result = call_codex_cli(prompt)
    except ValueError as exc:
        result = {"ok": False, "error": str(exc)}
    log_action("codex_creative_plan", {"product_guide": product_guide, "ok": result.get("ok"), "error": result.get("error", "")}, "completed" if result.get("ok") else "blocked")
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
    insights_refresh = refresh_real_metrics(reason="onboarding_complete") if config.ad_account_id and config.meta_access_token else {"ok": False, "saved": False, "reason": "missing_account_or_token"}
    metrics = load_metrics()
    if not insights_refresh.get("ok") and metrics.get("source") != "meta_graph":
        raise ValueError("Todavía no pude leer datos reales de Meta. Cambia tu clave o revisa sus permisos y vuelve a intentar.")
    deferred_reasons = agent_onboarding_deferred_reasons(business_profile)
    state = {
        "completed": True,
        "skipped": False,
        "deferred": bool(deferred_reasons),
        "deferred_reasons": deferred_reasons,
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
    mark_license_install_state(config, "onboarding_completed")
    log_action("onboarding_complete", {"setup_summary": state["setup_snapshot"], "first_insights_refresh": state["first_insights_refresh"]}, "completed")
    return state


def skip_onboarding():
    config = load_config()
    if not (config.dashboard_password or config.dashboard_token):
        raise ValueError("Crea primero la contraseña del dashboard.")
    business_profile = read_json(BUSINESS_PROFILE_FILE, {})
    if not isinstance(business_profile, dict):
        business_profile = {}
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
    for reason in agent_onboarding_deferred_reasons(business_profile):
        if reason not in missing:
            missing.append(reason)
    state = {
        "completed": True,
        "skipped": True,
        "deferred": True,
        "deferred_reasons": missing,
        "completed_at": now_iso(),
        "completed_by": "skip_and_complete_later",
        "setup_snapshot": build_setup_status().get("summary", {}),
        "business_profile_snapshot": redact_payload(business_profile),
    }
    write_json(ONBOARDING_FILE, state)
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
    rules = load_profitability_rules()
    config = load_config()
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
        recommendation = {
            "campaign_id": campaign.get("id"),
            "campaign_name": campaign.get("name"),
            "current_budget": money(current_budget),
            "recommended_budget": money(rec.recommended_budget),
            "change": money(change),
            "change_pct": round(change_pct, 1),
            "confidence": round(float(rec.confidence), 1),
            "reason": rec.reasoning,
            "requires_approval": abs(change_pct) > float(config.approval_required_over_pct or 20),
            "roas": round(campaign.get("roas", 0), 2),
            "health": campaign.get("health"),
        }
        recommendation["decision_evidence"] = recommendation_decision_evidence(campaign, recommendation, rules)
        recommendations.append(recommendation)
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
    if selected_locations or selected_interests:
        audience["meta_targeting"] = {
            "locations": selected_locations,
            "interests": selected_interests,
        }
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
            "targeting": targeting_summary(audience),
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
                "es": "¿Cómo debe sonar la marca? Por ejemplo: cercana, experta, elegante, directa, divertida.",
                "en": "How should the brand sound? For example: warm, expert, elegant, direct, playful.",
            },
            {
                "key": "colors",
                "es": "¿Qué colores o sensación visual debe respetar el agente al crear anuncios?",
                "en": "What colors or visual feeling should the agent respect when creating ads?",
            },
            {
                "key": "visual_style",
                "es": "¿Cómo deben verse los anuncios? Puedes contarme sobre colores, fondos, fotos o ejemplos que te gustan.",
                "en": "How should the creatives look? Think backgrounds, photos, style, composition, or references.",
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
                "es": "¿Cuántas imágenes o textos quieres que prepare? Puedes pedir solo uno.",
                "en": "How many images or texts would you like prepared? You can request just one.",
            },
            {
                "key": "creative_hypothesis",
                "es": "Si vas a comparar opciones, ¿qué te gustaría descubrir? Si no, di \"saltar\".",
                "en": "If you will compare options, what would you like to learn? Otherwise, say \"skip\".",
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
    image_path = extract_image_path(payload.get("message", ""))
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


def handle_export_report_tool(arguments, chat_payload, tool):
    return export_report_action(chat_payload, tool)


def handle_create_campaign_stack_tool(arguments, chat_payload, tool):
    required = ["name", "daily_budget", "landing_url", "creative_image_path"]
    missing = [key for key in required if not arguments.get(key)]
    final_status = str(arguments.get("final_status") or "ACTIVE").upper()
    if final_status == "ACTIVE" and not arguments.get("active_spend_confirmed"):
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
    if not any(arguments.get(key) for key in ["promoted_before", "previous_ads_results", "campaign_goal", "first_strategy", "current_campaign_context"]):
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
    if not any(arguments.get(key) for key in ["name", "promotion", "campaign_name", "base_ad_name"]):
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
    image_paths = safe_image_paths(chat_payload)
    if image_paths:
        arguments = dict(arguments)
        image_context = "\n\nImagen de referencia recibida en el chat. Hermes debe usar su análisis visual como guía creativa; no asumas que Codex puede leer archivos locales directamente."
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
    "export_report": handle_export_report_tool,
    "create_campaign_stack": handle_create_campaign_stack_tool,
    "build_audience_strategy": handle_build_audience_strategy_tool,
    "init_brand_guides": handle_init_brand_guides_tool,
    "save_business_context": handle_save_business_context_tool,
    "save_brand_guide": handle_save_brand_guide_tool,
    "save_product_guide": handle_save_product_guide_tool,
    "save_creative_references": handle_save_creative_references_tool,
    "save_ads_onboarding": handle_save_ads_onboarding_tool,
    "save_ad_brief": handle_save_ad_brief_tool,
    "codex_creative_plan": handle_codex_creative_plan_tool,
    "save_existing_adset": handle_save_existing_adset_tool,
    "pause_campaign": handle_campaign_mutation_tool,
    "resume_campaign": handle_campaign_mutation_tool,
    "set_budget": handle_campaign_mutation_tool,
    "generate_creatives": handle_campaign_mutation_tool,
}


def execute_agent_tool(tool_request, chat_payload):
    if not isinstance(tool_request, dict):
        return None
    tool = str(tool_request.get("tool") or "").strip()
    arguments = tool_request.get("arguments") or {}
    if not isinstance(arguments, dict):
        arguments = {}

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
    config = load_config()
    setup = build_setup_status()
    current_license_status = license_status(config)
    ad_config = read_json(AD_CONFIG_FILE, {})
    destination = ad_config.get("creative", {}).get("destination", {})
    business_profile = read_json(BUSINESS_PROFILE_FILE, {})
    onboarding = onboarding_health(load_onboarding_state(), config, metrics, current_license_status, destination, business_profile)
    entitlements = license_entitlements()
    business_spaces = agency_spaces_payload()
    business_snapshot = business_context_snapshot(business_profile)
    return {
        "metrics": metrics,
        "recommendations": recommendations,
        "brief": scheduled_brief_or_live(metrics, recommendations, business_profile),
        "fatigue": fatigue,
        "decision_memory": decisions,
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
        "onboarding_questions": {
            "status": onboarding_interview_status(business_profile),
            "file_exists": ONBOARDING_QUESTIONS_FILE.exists(),
        },
        "agent_onboarding_phase": agent_onboarding_phase(business_profile),
        "license_entitlements": entitlements,
        "business_spaces": business_spaces,
        "active_workspace": active_workspace_payload(),
        "workspace_usage": workspace_usage_payload(),
        "business_binding": business_binding_payload(),
        "local_network_access": dashboard_network_access_payload(),
        "config": {
            "mode": config.mode,
            "notify_channel": config.notify_channel,
            "telegram_agent": telegram_settings(config),
            "dashboard_token_required": config.dashboard_token_required,
            "dashboard_token_set": bool(config.dashboard_token),
            "dashboard_password_required": config.dashboard_token_required,
            "dashboard_password_set": bool(config.dashboard_password or config.dashboard_token),
            "live_actions_enabled": config.live_actions_enabled,
            "creative_studio": {
                "provider": config.creative_provider,
                "image_mode": config.creative_image_mode,
                "image_generation_ready": bool(config.creative_live and config.gemini_api_key),
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
                "ad_account_id": config.ad_account_id or ad_config.get("account", {}).get("id", ""),
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
.onboarding-flow{position:fixed;inset:0;z-index:50;display:none;background:linear-gradient(145deg,#101315,#171b1f);overflow:auto;padding:26px}.onboarding-flow.open{display:grid;place-items:center}.onboarding-shell{width:min(1080px,100%);display:grid;grid-template-columns:270px minmax(0,1fr);gap:18px;align-items:start}.onboarding-side{border:1px solid var(--line);border-radius:10px;background:rgba(255,255,255,.055);padding:16px;box-shadow:var(--shadow),var(--glow);position:sticky;top:26px}.onboarding-side h1{font-size:20px;line-height:1.05}.onboarding-side p{font-size:12px;color:var(--dim);line-height:1.5;margin-top:8px}.onboarding-card{display:block;min-height:0;border:1px solid var(--line);border-radius:10px;background:rgba(22,26,30,.86);box-shadow:var(--shadow),var(--glow);padding:20px}.onboarding-card h2{font-size:23px;line-height:1.1;max-width:720px}.onboarding-card>p{font-size:13px;color:var(--dim);line-height:1.55;margin-top:8px;max-width:760px}.onboarding-progress{display:flex;gap:6px;margin:14px 0}.onboarding-progress span{height:6px;flex:1;border-radius:999px;background:rgba(255,255,255,.1)}.onboarding-progress span.done{background:var(--accent)}.onboarding-step-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.onboarding-command{border:1px solid var(--line);background:rgba(0,0,0,.22);border-radius:8px;padding:10px;margin-top:8px;font-size:12px;color:var(--text);word-break:break-word}.helper-command{margin-top:10px;color:var(--dim);font-size:11px}.helper-command summary{cursor:pointer;font-weight:900;color:var(--accent);list-style:none}.helper-command summary::-webkit-details-marker{display:none}.helper-command summary:before{content:"+";display:inline-grid;place-items:center;width:16px;height:16px;margin-right:6px;border-radius:5px;background:rgba(39,199,167,.13);color:var(--accent)}.helper-command[open] summary:before{content:"-"}.onboarding-helper{border:1px solid rgba(39,199,167,.18);border-radius:8px;padding:10px;background:rgba(39,199,167,.045)}.onboarding-helper .btn{margin-top:8px}.onboarding-mini{display:grid;gap:8px;margin-top:12px}.onboarding-mini.two{grid-template-columns:1fr 1fr}.onboarding-mini label{display:flex;flex-direction:column;gap:5px}.onboarding-mini input,.onboarding-mini textarea{width:100%}.onboarding-mini textarea{resize:vertical;min-height:92px;background:var(--surface2);border:1px solid var(--border);border-radius:7px;color:var(--text);padding:9px;font-size:12px;line-height:1.4}.onboarding-mini .wide{grid-column:1/-1}.onboarding-mini>.btn,.unlock-form>.btn{justify-self:start}.business-question-shell{max-width:820px}.compact-business-scan,.compact-business-context{grid-template-columns:minmax(0,1fr) auto}.business-question-progress{display:grid;place-items:center;min-width:92px;border:1px solid rgba(167,124,255,.24);border-radius:10px;background:rgba(0,0,0,.18);padding:12px}.business-question-progress b{font-size:22px}.business-question-progress span{font-size:10px;color:var(--dim);text-transform:uppercase}.business-question-card{display:grid;gap:14px;border:1px solid rgba(167,124,255,.22);border-radius:12px;background:linear-gradient(145deg,rgba(11,10,17,.78),rgba(28,24,39,.72));padding:16px;box-shadow:0 24px 60px rgba(0,0,0,.22),var(--glow)}.business-question-label span{display:inline-flex;border:1px solid rgba(167,124,255,.26);border-radius:999px;background:rgba(167,124,255,.12);color:#cbb8ff;font-size:10px;font-weight:950;padding:5px 8px}.business-question-label h3{font-size:22px;line-height:1.1;margin-top:10px}.business-question-label p{font-size:12px;color:var(--dim);line-height:1.5;margin-top:7px}.business-question-card textarea{min-height:142px;resize:vertical;background:#12101a;border:1px solid rgba(199,178,255,.22);border-radius:10px;color:var(--text);padding:13px;font-size:14px;line-height:1.5}.business-question-card textarea:focus{outline:none;border-color:rgba(167,124,255,.58);box-shadow:0 0 0 3px rgba(167,124,255,.13)}.business-question-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}.business-question-actions .btn:first-child{margin-right:auto}.setup-guide{display:grid;gap:12px;margin-top:16px}.guide-card,.guide-panel{border:1px solid var(--line);border-radius:8px;background:rgba(255,255,255,.055);padding:12px}.guide-card b,.guide-panel b{display:block;font-size:12px;line-height:1.25}.guide-card p,.guide-card li,.guide-panel p,.guide-panel li{font-size:11px;color:var(--dim);line-height:1.45}.guide-card ol,.guide-panel ol{margin:8px 0 0 18px;padding:0}.private-connection{grid-template-columns:1fr}.guide-hero{display:grid;grid-template-columns:minmax(0,1fr) 270px;gap:14px;align-items:stretch;border:1px solid rgba(39,199,167,.2);border-radius:10px;background:linear-gradient(135deg,rgba(39,199,167,.09),rgba(255,255,255,.045));padding:14px;box-shadow:var(--glow)}.guide-main{display:grid;gap:12px;align-content:start}.guide-eyebrow{display:inline-flex;width:max-content;border:1px solid rgba(39,199,167,.24);border-radius:999px;background:rgba(39,199,167,.09);color:var(--accent);padding:5px 8px;font-size:10px;font-weight:950;text-transform:uppercase}.guide-main h3{font-size:18px;line-height:1.12}.guide-main p{font-size:12px;color:var(--dim);line-height:1.55;max-width:610px}.guide-actions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.guide-actions .btn{text-align:center;text-decoration:none}.guide-checklist{border:1px solid rgba(255,255,255,.1);border-radius:8px;background:rgba(0,0,0,.14);padding:12px}.guide-checklist b{font-size:12px}.guide-checklist ol{margin:9px 0 0 18px}.guide-checklist li{font-size:11px;color:var(--dim);line-height:1.5;margin-bottom:6px}.guide-support-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.manual-account{margin:0}.manual-account .btn{justify-self:start}.fallback-details{border:1px solid var(--line);border-radius:8px;background:rgba(255,255,255,.035);padding:0}.fallback-details summary{cursor:pointer;list-style:none;padding:11px 12px;font-size:11px;font-weight:900;color:var(--dim)}.fallback-details summary::-webkit-details-marker{display:none}.fallback-details summary:before{content:"+";display:inline-grid;place-items:center;width:16px;height:16px;margin-right:6px;border-radius:5px;background:rgba(255,255,255,.06);color:var(--accent)}.fallback-details[open] summary:before{content:"-"}.fallback-details .manual-account{border:0;border-top:1px solid var(--line);border-radius:0;background:transparent}.token-box{display:none;gap:8px;margin-top:0;border:1px solid rgba(39,199,167,.18);border-radius:8px;background:rgba(0,0,0,.16);padding:10px}.token-box.open{display:grid}.token-box textarea{min-height:86px;resize:vertical;background:var(--surface2);border:1px solid var(--border);border-radius:7px;color:var(--text);padding:9px;font-size:12px;line-height:1.35}.guide-visual{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;gap:8px;align-items:center}.mini-screen{border:1px solid rgba(255,255,255,.14);border-radius:8px;background:rgba(0,0,0,.18);padding:10px;min-height:82px}.mini-screen span{display:block;height:8px;border-radius:99px;background:rgba(255,255,255,.14);margin-bottom:7px}.mini-screen strong{display:block;font-size:11px}.mini-screen em{display:block;font-style:normal;font-size:10px;color:var(--accent);margin-top:5px}.guide-arrow{color:var(--accent);font-weight:950}.passive-guide{display:grid;grid-template-columns:minmax(0,1fr) 230px;gap:12px;margin-top:16px}.passive-card{border:1px solid rgba(99,168,255,.2);border-radius:10px;background:rgba(99,168,255,.065);padding:14px;box-shadow:var(--glow)}.passive-card b,.passive-side b{font-size:12px}.passive-card p,.passive-side p{font-size:12px;color:var(--dim);line-height:1.5;margin-top:6px}.passive-side{border:1px solid var(--line);border-radius:8px;background:rgba(255,255,255,.045);padding:12px}.passive-state{display:inline-flex;align-items:center;gap:7px;border:1px solid rgba(39,199,167,.22);border-radius:999px;background:rgba(39,199,167,.08);color:var(--accent);font-size:10px;font-weight:950;padding:5px 8px;text-transform:uppercase}.passive-state:before{content:"";width:7px;height:7px;border-radius:50%;background:var(--accent)}.business-start-shell{max-width:820px}.business-start-form textarea{min-height:116px;font-size:13px;line-height:1.45}
.onboarding-security-note{display:grid;grid-template-columns:auto minmax(0,1fr);gap:10px;align-items:start;margin-bottom:16px;border:1px solid rgba(109,227,172,.24);border-radius:12px;background:linear-gradient(135deg,rgba(109,227,172,.105),rgba(167,124,255,.075),rgba(0,0,0,.18));padding:13px 14px;box-shadow:0 18px 48px rgba(0,0,0,.22),0 0 0 1px rgba(255,255,255,.06) inset}.onboarding-security-note:before{content:"";width:14px;height:14px;border-radius:50%;margin-top:2px;background:radial-gradient(circle,#fff 0 18%,#6de3ac 20% 58%,rgba(109,227,172,.18) 60% 100%);box-shadow:0 0 22px rgba(109,227,172,.42)}.onboarding-security-note b{display:block;font-size:12px;line-height:1.2;color:#eafff6}.onboarding-security-note p{font-size:11px;line-height:1.5;color:var(--dim);margin-top:4px}.settings-stack{display:grid;gap:12px}.profitability-rules{border-top:1px solid var(--line);padding-top:12px}.profitability-rules h3{font-size:15px;line-height:1.15}
header{position:sticky;top:0;z-index:4;background:rgba(18,21,24,.62);backdrop-filter:blur(22px) saturate(145%);-webkit-backdrop-filter:blur(22px) saturate(145%);border-bottom:1px solid var(--line);display:grid;grid-template-columns:minmax(178px,220px) minmax(360px,1fr) auto auto;align-items:center;gap:12px;padding:12px 18px;box-shadow:0 8px 28px rgba(0,0,0,.18),var(--glow)}
.brand{min-width:0;position:relative;padding-left:36px}.brand:before{content:"";position:absolute;left:0;top:1px;width:24px;height:24px;border-radius:7px;background:linear-gradient(135deg,var(--accent),var(--accent2));box-shadow:0 0 0 1px rgba(255,255,255,.14) inset}.brand h1{font-size:16px;line-height:1.05;letter-spacing:0;font-weight:900}.brand span{color:var(--accent)}.brand div{font-size:11px;color:var(--dim);margin-top:4px}
.panel-caret{margin-left:auto;color:var(--zone);font-size:12px;font-weight:950;transition:transform .16s ease}.panel-caret:before{content:"+"}body.left-panel-open .brief-zone .panel-caret:before,body.right-panel-open .rail .panel-caret:before{content:"-"}.zone-badge{display:none;margin-left:auto;border:1px solid var(--zone-border);border-radius:999px;background:color-mix(in srgb,var(--zone) 16%,transparent);color:var(--zone);padding:3px 7px;font-size:9px;font-weight:950;text-transform:uppercase;letter-spacing:.02em}.zone-label.has-new-brief{position:relative;overflow:hidden;border-color:color-mix(in srgb,var(--zone) 62%,var(--zone-border));box-shadow:0 0 0 1px color-mix(in srgb,var(--zone) 18%,transparent) inset,0 0 24px var(--zone-glow)}.zone-label.has-new-brief .zone-badge{display:inline-flex}.zone-label.has-new-brief:before{animation:daily-brief-dot 1.6s ease-in-out infinite}.zone-label.has-new-brief:after{content:"";position:absolute;inset:-1px;background:linear-gradient(105deg,transparent 0%,transparent 34%,rgba(255,255,255,.2) 45%,color-mix(in srgb,var(--zone) 30%,transparent) 52%,transparent 66%,transparent 100%);transform:translateX(-120%);animation:daily-brief-sheen 3.4s ease-in-out infinite;pointer-events:none}.zone-label.has-new-brief>*{position:relative;z-index:1}@keyframes daily-brief-sheen{0%,38%{transform:translateX(-120%)}72%,100%{transform:translateX(120%)}}@keyframes daily-brief-dot{0%,100%{box-shadow:0 0 0 4px var(--zone-glow),0 0 0 0 color-mix(in srgb,var(--zone) 0%,transparent)}50%{box-shadow:0 0 0 4px var(--zone-glow),0 0 0 8px color-mix(in srgb,var(--zone) 16%,transparent)}}@media(prefers-reduced-motion:reduce){.zone-label.has-new-brief:before,.zone-label.has-new-brief:after{animation:none}}
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
.update-banner,.deferred-onboarding-banner{margin:0 8px 8px;border:1px solid rgba(244,183,64,.42);background:linear-gradient(135deg,rgba(244,183,64,.13),rgba(39,199,167,.08));border-radius:8px;padding:10px 12px;display:flex;align-items:center;justify-content:space-between;gap:10px;box-shadow:0 1px 0 rgba(255,255,255,.08) inset}.update-banner b,.deferred-onboarding-banner b{font-size:12px}.update-banner p,.deferred-onboarding-banner p{font-size:11px;color:var(--dim);line-height:1.4;margin-top:3px}.deferred-onboarding-banner{border-color:rgba(167,124,255,.5);background:linear-gradient(135deg,rgba(167,124,255,.16),rgba(48,215,180,.1));box-shadow:0 0 0 1px rgba(167,124,255,.1) inset,0 0 28px rgba(167,124,255,.16)}.deferred-onboarding-banner .pulse-dot{width:9px;height:9px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 0 rgba(167,124,255,.5);animation:setup-pulse 1.7s ease-in-out infinite;flex:none}@keyframes setup-pulse{0%,100%{box-shadow:0 0 0 0 rgba(167,124,255,.5);transform:scale(.9)}50%{box-shadow:0 0 0 9px rgba(167,124,255,0);transform:scale(1.08)}}.deferred-onboarding-copy{display:flex;align-items:flex-start;gap:9px}.update-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin-top:12px}.update-card{border:1px solid rgba(244,183,64,.25);background:rgba(244,183,64,.06);border-radius:8px;padding:10px}.update-card span{display:inline-block;font-size:9px;font-weight:950;text-transform:uppercase;color:var(--accent2);margin-bottom:6px}.update-card b{display:block;font-size:12px;line-height:1.25}.update-card p{font-size:11px;color:var(--dim);line-height:1.45;margin-top:5px}
.brief-q{background:rgba(255,255,255,.07);border:1px solid var(--line);border-radius:8px;padding:11px;margin-bottom:9px;box-shadow:0 1px 0 rgba(255,255,255,.08) inset}.brief-q b{font-size:12px;color:var(--text);font-weight:900}.brief-q p{font-size:12px;color:var(--dim);line-height:1.5;margin-top:6px}
.business-profile-panel{display:grid;gap:9px}.business-profile-hero{border:1px solid var(--line);border-radius:9px;background:linear-gradient(135deg,var(--zone-bg),rgba(255,255,255,.055));padding:12px;box-shadow:var(--glow)}.business-profile-hero h3{font-size:15px;line-height:1.15}.business-profile-hero p{font-size:12px;color:var(--dim);line-height:1.45;margin-top:6px}.business-profile-pills{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px}.business-profile-pill{display:inline-flex;max-width:100%;border:1px solid var(--zone-border);border-radius:999px;background:color-mix(in srgb,var(--zone) 10%,transparent);color:var(--text);font-size:10px;font-weight:850;line-height:1.2;padding:5px 8px}.business-profile-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.business-profile-mini{border:1px solid var(--line);border-radius:8px;background:rgba(255,255,255,.05);padding:10px}.business-profile-mini span{display:block;color:var(--dim);font-size:9px;font-weight:950;letter-spacing:.02em;text-transform:uppercase}.business-profile-mini b{display:block;font-size:12px;line-height:1.32;margin-top:5px}.business-profile-actions{display:flex;gap:7px;flex-wrap:wrap}.business-profile-empty{border:1px dashed var(--line);border-radius:9px;padding:12px;background:rgba(255,255,255,.035)}.business-profile-empty p{font-size:12px;color:var(--dim);line-height:1.45}.business-profile-empty .btn{margin-top:9px}@media(max-width:760px){.business-profile-grid{grid-template-columns:1fr}}
table{width:100%;border-collapse:separate;border-spacing:0;font-size:12px}th,td{padding:10px;border-bottom:1px solid var(--line);text-align:left}th{color:var(--dim);font-size:10px;text-transform:uppercase;background:rgba(255,255,255,.035)}td:last-child{text-align:right}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.field{display:flex;flex-direction:column;gap:5px}.field.wide{grid-column:1/-1}.field-help{display:block;margin-top:1px;color:var(--dim);font-size:10px;line-height:1.35;text-transform:none;font-weight:650;opacity:.86}label{font-size:10px;color:var(--dim);font-weight:800;text-transform:uppercase}input,select{background:var(--surface2);border:1px solid var(--border);border-radius:7px;color:var(--text);padding:9px;font-size:12px}input:focus,select:focus{outline:none;border-color:var(--accent)}
.creator-hero{position:relative;overflow:hidden;margin-bottom:12px;border:1px solid color-mix(in srgb,var(--accent) 26%,var(--line));border-radius:14px;background:linear-gradient(130deg,color-mix(in srgb,var(--accent) 10%,transparent),color-mix(in srgb,var(--accent2) 8%,transparent)),var(--glass);padding:18px;box-shadow:var(--shadow),var(--glow)}.creator-hero:after{content:"";position:absolute;right:-72px;bottom:-100px;width:230px;height:190px;border-radius:50%;background:color-mix(in srgb,var(--accent) 16%,transparent);filter:blur(42px);pointer-events:none}.creator-hero>*{position:relative;z-index:1}.creator-hero h2{font-size:23px;line-height:1.1;font-weight:950}.creator-hero p{max-width:540px;margin-top:8px;color:var(--dim);font-size:12px;line-height:1.55}.creator-hero-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.creator-safety{display:flex;align-items:flex-start;gap:10px;margin-bottom:12px;padding:12px;border:1px solid rgba(85,212,122,.23);border-radius:11px;background:rgba(85,212,122,.06)}.creator-safety-mark{display:grid;place-items:center;width:24px;height:24px;flex:none;border-radius:999px;background:rgba(85,212,122,.14);color:var(--green);font-size:12px;font-weight:950}.creator-safety b{display:block;font-size:12px}.creator-safety p{margin-top:4px;color:var(--dim);font-size:11px;line-height:1.5}.creator-manual-entry{border:1px solid var(--line);border-radius:12px;background:var(--glass);padding:0;overflow:hidden}.creator-manual-entry>summary{display:flex;align-items:center;justify-content:space-between;cursor:pointer;list-style:none;padding:13px 14px;color:var(--text);font-size:12px;font-weight:850}.creator-manual-entry>summary::-webkit-details-marker{display:none}.creator-manual-entry>summary:after{content:"+";color:var(--accent);font-size:17px}.creator-manual-entry[open]>summary{border-bottom:1px solid var(--line)}.creator-manual-entry[open]>summary:after{content:"-"}.creator-manual-entry b{display:block;font-size:12px}.creator-manual-entry small{display:block;margin-top:4px;color:var(--dim);font-size:10px;font-weight:600}.creator-manual-form{display:grid;gap:17px;padding:14px}.creator-form-section{display:grid;gap:11px}.creator-form-section+.creator-form-section{padding-top:14px;border-top:1px solid var(--line)}.creator-form-section h3{font-size:11px;font-weight:950;color:var(--dim);text-transform:uppercase}.creator-confirm{display:flex;align-items:flex-start;gap:8px;color:var(--dim);font-size:11px;font-weight:750;line-height:1.45;text-transform:none}.creator-confirm input{margin-top:2px;flex:none}.creator-advanced{border:1px solid var(--line);border-radius:8px;overflow:hidden;background:rgba(0,0,0,.08)}.creator-advanced summary{cursor:pointer;list-style:none;padding:11px;color:var(--dim);font-size:11px;font-weight:850}.creator-advanced summary::-webkit-details-marker{display:none}.creator-advanced summary:before{content:"+";margin-right:7px;color:var(--accent)}.creator-advanced[open] summary:before{content:"-"}.creator-advanced .form-grid{padding:0 11px 11px}.creator-submit-note{color:var(--dim);font-size:11px;line-height:1.5}.targeting-workbench{grid-column:1/-1;display:grid;gap:11px;border:1px solid color-mix(in srgb,var(--accent) 18%,var(--line));border-radius:12px;background:color-mix(in srgb,var(--surface) 86%,transparent);padding:12px}.targeting-intro{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.targeting-intro b{font-size:12px}.targeting-intro p{margin-top:4px;color:var(--dim);font-size:11px;line-height:1.45}.targeting-mode-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.targeting-mode-card{min-height:84px;border:1px solid var(--line);border-radius:10px;background:var(--glass);color:var(--text);padding:10px;text-align:left;cursor:pointer}.targeting-mode-card.active,.targeting-mode-card:hover{border-color:color-mix(in srgb,var(--accent) 48%,var(--line));box-shadow:var(--glow)}.targeting-mode-card b{display:block;font-size:11px}.targeting-mode-card span{display:block;margin-top:5px;color:var(--dim);font-size:10px;line-height:1.35}.targeting-search-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.targeting-picker{display:grid;gap:7px;min-width:0}.targeting-search-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px}.targeting-results{display:grid;gap:6px}.targeting-result{display:flex;align-items:center;justify-content:space-between;gap:8px;border:1px solid var(--line);border-radius:9px;background:var(--surface2);padding:8px;text-align:left}.targeting-result b{display:block;font-size:11px}.targeting-result span{display:block;color:var(--dim);font-size:10px;line-height:1.35}.targeting-chips{display:flex;gap:6px;flex-wrap:wrap;min-height:26px}.targeting-chip{display:inline-flex;align-items:center;gap:6px;border:1px solid color-mix(in srgb,var(--accent) 26%,var(--line));border-radius:999px;background:color-mix(in srgb,var(--accent) 8%,transparent);padding:5px 8px;color:var(--text);font-size:10px;font-weight:850}.targeting-chip button{display:grid;place-items:center;width:16px;height:16px;border:0;border-radius:50%;background:rgba(255,255,255,.09);color:inherit;cursor:pointer}.targeting-empty,.targeting-error{border:1px dashed var(--line);border-radius:9px;padding:9px;color:var(--dim);font-size:11px;line-height:1.45}.targeting-error{border-color:rgba(245,176,46,.38);background:rgba(245,176,46,.07)}.targeting-manual-fallback{border:1px solid var(--line);border-radius:9px;background:rgba(0,0,0,.08);overflow:hidden}.targeting-manual-fallback summary{cursor:pointer;list-style:none;padding:10px;color:var(--dim);font-size:11px;font-weight:900}.targeting-manual-fallback summary::-webkit-details-marker{display:none}.targeting-manual-fallback summary:before{content:"+";margin-right:7px;color:var(--accent)}.targeting-manual-fallback[open] summary:before{content:"-"}.targeting-manual-fallback .form-grid{padding:0 10px 10px}
.fatigue{border-left:3px solid var(--yellow);padding:9px 10px;background:rgba(244,201,93,.07);border-radius:7px;margin-bottom:8px}.fatigue b{font-size:12px}.fatigue div{font-size:11px;color:var(--dim);margin-top:4px}
.log-item{font-size:11px;color:var(--dim);padding:9px 0;border-bottom:1px solid var(--line)}.log-item b{color:var(--text)}.action-detail{margin-top:7px;border:1px solid var(--line);background:rgba(255,255,255,.045);border-radius:7px;padding:8px;font-size:11px;color:var(--dim);line-height:1.45}.action-detail strong{color:var(--text)}.notice{font-size:11px;color:var(--dim);line-height:1.45}.mobile-recs{display:none}.rec-card{background:rgba(255,255,255,.07);border:1px solid var(--line);border-radius:8px;padding:11px;margin-bottom:9px;box-shadow:0 1px 0 rgba(255,255,255,.08) inset}.rec-card h3{font-size:12px;line-height:1.3;margin-bottom:8px}.rec-values{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:8px 0}.rec-values div{background:rgba(255,255,255,.055);border:1px solid var(--line);border-radius:7px;padding:8px}.rec-values b{display:block;font-size:13px}.rec-values span{display:block;color:var(--dim);font-size:9px;text-transform:uppercase;margin-top:3px}.approval-stack{display:grid;gap:10px}.approval-card{border:1px solid color-mix(in srgb,var(--accent) 20%,var(--line));border-radius:10px;background:linear-gradient(145deg,color-mix(in srgb,var(--accent) 7%,transparent),rgba(255,255,255,.045));padding:11px;box-shadow:var(--glow)}.approval-card.high{border-color:rgba(255,107,107,.42);background:linear-gradient(145deg,rgba(255,107,107,.08),rgba(255,255,255,.045))}.approval-card.medium{border-color:rgba(244,183,64,.34);background:linear-gradient(145deg,rgba(244,183,64,.08),rgba(255,255,255,.045))}.approval-top{display:flex;align-items:flex-start;gap:9px;margin-bottom:9px}.approval-icon{display:grid;place-items:center;width:24px;height:24px;flex:none;border-radius:8px;background:color-mix(in srgb,var(--accent) 18%,transparent);color:var(--accent);font-weight:950;font-size:12px}.approval-title{min-width:0;flex:1}.approval-title b{display:block;font-size:12px;line-height:1.25;color:var(--text)}.approval-title span{display:block;color:var(--dim);font-size:10px;line-height:1.35;margin-top:3px}.approval-risk{font-size:9px;font-weight:950;text-transform:uppercase;border:1px solid var(--line);border-radius:999px;padding:4px 7px;color:var(--dim);white-space:nowrap}.approval-risk.high{color:#ff8d8d;border-color:rgba(255,107,107,.45);background:rgba(255,107,107,.08)}.approval-risk.medium{color:var(--accent2);border-color:rgba(244,183,64,.42);background:rgba(244,183,64,.08)}.approval-section{border:1px solid var(--line);border-radius:8px;background:rgba(255,255,255,.045);padding:8px;margin-top:7px}.approval-section b{display:block;color:var(--text);font-size:10px;text-transform:uppercase;letter-spacing:.02em}.approval-section p{color:var(--dim);font-size:11px;line-height:1.45;margin-top:4px}.approval-facts{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:8px}.approval-fact{border:1px solid var(--line);border-radius:8px;background:rgba(0,0,0,.08);padding:7px}.approval-fact span{display:block;color:var(--dim);font-size:9px;text-transform:uppercase}.approval-fact strong{display:block;color:var(--text);font-size:12px;margin-top:3px}.approval-actions{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:9px}.approval-actions .btn{width:100%}.chat-fab{position:fixed;right:18px;bottom:18px;z-index:30;border:1px solid rgba(39,199,167,.4);background:linear-gradient(135deg,rgba(39,199,167,.95),rgba(244,183,64,.92));color:#071411;border-radius:999px;padding:12px 15px;font-size:12px;font-weight:950;box-shadow:0 18px 55px rgba(0,0,0,.42);cursor:pointer;transition:transform .18s ease,box-shadow .18s ease;animation:chat-fab-breathe 3.8s ease-in-out infinite}.chat-fab:hover{transform:translateY(-2px) scale(1.02);box-shadow:0 20px 62px rgba(0,0,0,.46),0 0 0 6px rgba(39,199,167,.08)}.chat-panel{position:fixed;right:18px;bottom:76px;z-index:31;width:min(390px,calc(100vw - 24px));height:min(620px,calc(100vh - 96px));display:none;grid-template-rows:auto 1fr auto;border:1px solid var(--line);border-radius:10px;background:rgba(20,24,28,.78);backdrop-filter:blur(24px) saturate(140%);-webkit-backdrop-filter:blur(24px) saturate(140%);box-shadow:var(--shadow),var(--glow);overflow:hidden;transform-origin:calc(100% - 40px) 100%}.chat-panel.open{display:grid;animation:chat-panel-in .34s cubic-bezier(.16,1,.3,1) both}.chat-panel.open .chat-head{animation:chat-head-sheen .62s ease-out both}.chat-panel.open .chat-avatar{animation:chat-avatar-pop .46s cubic-bezier(.16,1,.3,1) both}.chat-head{display:flex;align-items:center;gap:10px;padding:12px;border-bottom:1px solid var(--line);background:rgba(255,255,255,.055)}.chat-avatar{display:grid;place-items:center;width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,var(--accent),var(--accent2));color:#061512;font-weight:950}.chat-title{flex:1}.chat-title b{display:block;font-size:13px}.chat-title span{display:block;font-size:10px;color:var(--dim);margin-top:2px}.chat-close{width:30px;height:30px;border-radius:8px}.chat-log{padding:12px;overflow:auto}.msg{max-width:88%;padding:10px 11px;border-radius:9px;margin-bottom:9px;font-size:12px;line-height:1.5;white-space:normal}.msg strong{font-weight:900;color:var(--text)}.msg p{margin:0 0 8px}.msg p:last-child{margin-bottom:0}.msg ul,.msg ol{margin:6px 0 8px 17px;padding:0}.msg li{margin:3px 0}.msg.agent{background:rgba(255,255,255,.08);border:1px solid var(--line);color:var(--text)}.msg.user{margin-left:auto;background:rgba(39,199,167,.16);border:1px solid rgba(39,199,167,.32);color:var(--text)}.msg.thinking{color:transparent;background:linear-gradient(100deg,var(--dim) 0%,var(--dim) 35%,#fff 48%,var(--accent) 54%,var(--dim) 68%,var(--dim) 100%);background-size:240% 100%;-webkit-background-clip:text;background-clip:text;animation:thinking-shimmer 1.35s linear infinite}.msg.thinking:before{content:"";display:inline-block;width:5px;height:5px;border-radius:50%;margin-right:7px;background:var(--accent);box-shadow:0 0 12px rgba(39,199,167,.75);vertical-align:middle;animation:thinking-pulse 1.1s ease-in-out infinite}@keyframes chat-panel-in{0%{opacity:0;transform:translateY(18px) scale(.94);filter:blur(8px)}55%{opacity:1;transform:translateY(-2px) scale(1.01);filter:blur(0)}100%{opacity:1;transform:translateY(0) scale(1);filter:blur(0)}}@keyframes chat-head-sheen{0%{box-shadow:0 -18px 45px rgba(39,199,167,.28) inset}100%{box-shadow:0 0 0 rgba(39,199,167,0) inset}}@keyframes chat-avatar-pop{0%{transform:scale(.72) rotate(-8deg);box-shadow:0 0 0 rgba(39,199,167,0)}70%{transform:scale(1.08) rotate(2deg);box-shadow:0 0 0 6px rgba(39,199,167,.13)}100%{transform:scale(1) rotate(0);box-shadow:0 0 0 rgba(39,199,167,0)}}@keyframes chat-fab-breathe{0%,100%{box-shadow:0 18px 55px rgba(0,0,0,.42),0 0 0 0 rgba(39,199,167,0)}50%{box-shadow:0 18px 55px rgba(0,0,0,.42),0 0 0 7px rgba(39,199,167,.08)}}@keyframes thinking-shimmer{0%{background-position:120% 0}100%{background-position:-120% 0}}@keyframes thinking-pulse{0%,100%{opacity:.35;transform:scale(.72)}50%{opacity:1;transform:scale(1)}}.chat-quick{display:flex;gap:7px;flex-wrap:wrap;padding:0 12px 9px}.chip{border:1px solid var(--line);background:rgba(255,255,255,.055);color:var(--dim);border-radius:999px;padding:7px 9px;font-size:11px;font-weight:800;cursor:pointer}.chat-form{display:grid;grid-template-columns:1fr auto;gap:8px;padding:11px;border-top:1px solid var(--line);background:rgba(255,255,255,.035);align-items:end}.chat-form textarea{min-height:44px;max-height:150px;resize:none;overflow-y:hidden;background:rgba(255,255,255,.07);border:1px solid var(--line);border-radius:8px;color:var(--text);padding:9px;font-size:12px;line-height:1.4}.unlock-overlay,.confirm-overlay,.guide-overlay{position:fixed;inset:0;z-index:60;display:none;place-items:center;padding:16px;background:rgba(8,10,12,.72);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px)}.unlock-overlay.open,.confirm-overlay.open,.guide-overlay.open{display:grid}.unlock-card,.confirm-card,.guide-modal-card{width:min(430px,100%);border:1px solid var(--line);border-radius:10px;background:rgba(22,26,30,.9);box-shadow:var(--shadow),var(--glow);padding:18px}.guide-modal-card{width:min(760px,calc(100vw - 28px));max-height:calc(100vh - 36px);overflow:auto}.unlock-card h2,.confirm-card h2,.guide-modal-card h2{font-size:19px;line-height:1.15}.unlock-card p,.confirm-card p,.guide-modal-card p{font-size:12px;color:var(--dim);line-height:1.5;margin-top:8px}.confirm-card ul{margin:10px 0 0 18px;color:var(--dim);font-size:12px;line-height:1.5}.confirm-actions{display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;margin-top:14px}.unlock-form{display:grid;gap:9px;margin-top:14px}.unlock-error{display:none;color:#ff9a9a;font-size:12px}.unlock-error.show{display:block}.hidden{display:none}.toast{position:fixed;right:16px;bottom:74px;z-index:58;max-width:min(340px,calc(100vw - 32px));background:var(--surface);border:1px solid var(--accent);border-radius:8px;padding:10px 12px;font-size:12px;display:none;box-shadow:var(--shadow)}
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
 .trust-grid,.update-cards{grid-template-columns:1fr}.update-banner,.next-step,.mode-panel{align-items:flex-start;flex-direction:column}.copy-btn,.mode-actions{width:100%}.mode-actions .btn{flex:1}
 #recs-table{display:none}.mobile-recs{display:block}
 .form-grid{grid-template-columns:1fr}table{min-width:560px}.brief-q p,.notice,.log-item{font-size:12px}
}
@media(max-width:420px){
 .kpis{grid-template-columns:1fr}.metrics{grid-template-columns:1fr}.floating-tip{max-width:calc(100vw - 18px)}
}
.business-summary-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.business-summary-grid div{border:1px solid rgba(255,255,255,.11);border-radius:8px;background:rgba(0,0,0,.13);padding:10px}.business-summary-grid b{display:block;font-size:10px;text-transform:uppercase;color:var(--dim);margin-bottom:5px}.business-summary-grid span{display:block;font-size:12px;line-height:1.35}.business-hero{background:linear-gradient(135deg,rgba(39,199,167,.1),rgba(99,168,255,.08),rgba(244,183,64,.06))}@media(max-width:760px){.business-summary-grid{grid-template-columns:1fr}}
/* Visual renovation: soft light shell, aurora selections, and alternate dashboard views. */
body.theme-light,body.theme-aurora{--bg:#f7f8fd;--shell:rgba(255,255,255,.82);--surface:#ffffff;--surface2:#f4f6fb;--surface3:#e9edf7;--glass:rgba(255,255,255,.72);--glass2:rgba(255,255,255,.64);--border:#dfe5f1;--line:rgba(38,44,57,.11);--text:#171a22;--dim:#6b7284;--muted:#98a0af;--accent:#7b4dff;--accent2:#30d7b4;--green:#20b777;--red:#ef5d66;--yellow:#f3b33f;--blue:#5b8bff;--cyan:#31c8df;--shadow:0 26px 80px rgba(85,96,132,.18);--glow:0 0 0 1px rgba(255,255,255,.8) inset,0 1px 0 rgba(255,255,255,.9) inset;background:radial-gradient(circle at 9% 4%,rgba(115,211,255,.36),transparent 24rem),radial-gradient(circle at 74% 2%,rgba(255,185,239,.4),transparent 28rem),radial-gradient(circle at 90% 44%,rgba(246,223,128,.27),transparent 25rem),linear-gradient(180deg,#fbfcff 0%,#eef3fb 100%);color:var(--text);font-family:"Satoshi","Plus Jakarta Sans","Manrope","Avenir Next",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
body.theme-dark,body.theme-sapphire{--bg:#04040a;--shell:rgba(6,6,13,.97);--surface:#090a12;--surface2:#10101b;--surface3:#181729;--glass:rgba(8,8,16,.9);--glass2:rgba(157,116,255,.065);--border:#29233d;--line:rgba(199,178,255,.12);--text:#f7f3ff;--dim:#aaa1bd;--muted:#706981;--accent:#a77cff;--accent2:#ff6bd6;--green:#6de3ac;--red:#ff6c8a;--yellow:#ffd76d;--blue:#65a7ff;--cyan:#72f4ff;--shadow:0 30px 88px rgba(0,0,0,.72);--glow:0 0 0 1px rgba(199,178,255,.09) inset,0 1px 0 rgba(255,255,255,.045) inset;background:radial-gradient(ellipse at 100% 10%,rgba(119,81,255,.105),transparent 30rem),radial-gradient(ellipse at 16% 0%,rgba(66,153,255,.06),transparent 25rem),linear-gradient(180deg,#080812 0%,#05050b 20%,#030307 58%,#010103 100%);color:var(--text);font-family:"Satoshi","Plus Jakarta Sans","Manrope","Avenir Next",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
body.theme-light header,body.theme-aurora header{background:rgba(255,255,255,.68);border-bottom-color:rgba(33,40,60,.1);box-shadow:0 14px 50px rgba(97,106,138,.16),var(--glow)}
body.theme-dark header,body.theme-sapphire header{background:linear-gradient(180deg,rgba(9,9,17,.99),rgba(4,4,9,.97));border-bottom-color:rgba(199,178,255,.1);box-shadow:0 20px 66px rgba(0,0,0,.7),var(--glow)}
body.theme-light .unlock-card,body.theme-light .confirm-card,body.theme-light .guide-modal-card,body.theme-light .chat-panel,body.theme-aurora .unlock-card,body.theme-aurora .confirm-card,body.theme-aurora .guide-modal-card,body.theme-aurora .chat-panel{background:rgba(255,255,255,.88);color:var(--text)}
body.theme-light .section,body.theme-aurora .section{background:linear-gradient(145deg,color-mix(in srgb,var(--zone-bg) 55%,rgba(255,255,255,.72)),rgba(255,255,255,.7));box-shadow:0 18px 58px rgba(85,96,132,.15),var(--glow)}
body.theme-dark .section,body.theme-sapphire .section{background:linear-gradient(145deg,rgba(11,11,20,.97),rgba(4,4,9,.96));border-color:rgba(199,178,255,.105);box-shadow:0 30px 86px rgba(0,0,0,.68),var(--glow)}
body.theme-light .head,body.theme-light .tabs,body.theme-light .pill,body.theme-light .lang-select,body.theme-light .chip,body.theme-light .agent-chat-bar,body.theme-aurora .head,body.theme-aurora .tabs,body.theme-aurora .pill,body.theme-aurora .lang-select,body.theme-aurora .chip,body.theme-aurora .agent-chat-bar{background:rgba(255,255,255,.62)}
body.theme-dark .head,body.theme-dark .tabs,body.theme-dark .pill,body.theme-dark .lang-select,body.theme-dark .chip,body.theme-dark .agent-chat-bar,body.theme-sapphire .head,body.theme-sapphire .tabs,body.theme-sapphire .pill,body.theme-sapphire .lang-select,body.theme-sapphire .chip,body.theme-sapphire .agent-chat-bar{background:rgba(7,7,14,.9);border-color:rgba(199,178,255,.115)}
body.theme-light .tab.active,body.theme-light .view-chip.active,body.theme-light .theme-chip.active,body.theme-aurora .tab.active,body.theme-aurora .view-chip.active,body.theme-aurora .theme-chip.active,.aurora-selected{background:radial-gradient(circle at 82% 18%,rgba(92,222,245,.62),transparent 28%),radial-gradient(circle at 62% 10%,rgba(255,144,217,.48),transparent 28%),radial-gradient(circle at 36% 64%,rgba(255,226,103,.46),transparent 25%),linear-gradient(135deg,rgba(255,255,255,.92),rgba(245,241,255,.82));color:#161820;border-color:rgba(127,93,255,.18);box-shadow:0 14px 38px rgba(125,84,255,.12),var(--glow)}
body.theme-dark .tab.active,body.theme-dark .view-chip.active,body.theme-dark .theme-chip.active,body.theme-sapphire .tab.active,body.theme-sapphire .view-chip.active,body.theme-sapphire .theme-chip.active{background:linear-gradient(135deg,rgba(31,26,53,.9),rgba(9,9,18,.97));color:#fff;border-color:rgba(167,124,255,.46);box-shadow:0 0 0 1px rgba(255,255,255,.045) inset,0 14px 38px rgba(123,77,255,.18),0 0 24px rgba(255,107,214,.12)}
body.theme-light input,body.theme-light select,body.theme-light textarea,body.theme-aurora input,body.theme-aurora select,body.theme-aurora textarea{background:#fff;color:var(--text);border-color:var(--border)}
body.theme-dark input,body.theme-dark select,body.theme-dark textarea,body.theme-sapphire input,body.theme-sapphire select,body.theme-sapphire textarea{background:#06060d;color:var(--text);border-color:rgba(199,178,255,.15)}
body.theme-light .btn,body.theme-aurora .btn{background:rgba(255,255,255,.72);color:var(--text)}
body.theme-dark .btn,body.theme-sapphire .btn{background:rgba(9,9,18,.9);color:var(--text);border-color:rgba(199,178,255,.13)}
.chat-head .chat-close{flex:0 0 28px;width:28px;min-width:28px;min-height:28px;height:28px;padding:0;display:grid;place-items:center;border-radius:999px;font-size:15px;line-height:1;color:var(--dim)}
.chat-head .chat-close:hover{color:var(--text);background:rgba(255,255,255,.09)}
body.theme-light .btn.primary,body.theme-light .agent-bar-send,body.theme-aurora .btn.primary,body.theme-aurora .agent-bar-send{background:#171a22;color:#fff;border-color:#171a22}
body.theme-dark .btn.primary,body.theme-dark .agent-bar-send,body.theme-sapphire .btn.primary,body.theme-sapphire .agent-bar-send{background:linear-gradient(135deg,#a77cff,#ff6bd6);color:#0e0c14;border-color:rgba(255,255,255,.16)}
body.theme-light .ask-btn,body.theme-aurora .ask-btn{background:rgba(123,77,255,.08);border-color:rgba(123,77,255,.25);color:#5f35d8}
body.theme-dark .ask-btn,body.theme-sapphire .ask-btn{background:rgba(167,124,255,.12);border-color:rgba(167,124,255,.32);color:#c6adff}
body.theme-light .signal,body.theme-aurora .signal{color:#5f35d8;background:rgba(123,77,255,.08);border-color:rgba(123,77,255,.18)}
body.theme-dark .signal,body.theme-sapphire .signal{color:#c6adff;background:rgba(167,124,255,.13);border-color:rgba(167,124,255,.3)}
body.theme-light .signal:before,body.theme-aurora .signal:before{background:#7b4dff;box-shadow:0 0 0 4px rgba(123,77,255,.12)}
body.theme-dark .signal:before,body.theme-sapphire .signal:before{background:#a77cff;box-shadow:0 0 0 4px rgba(167,124,255,.16),0 0 18px rgba(255,107,214,.32)}
body.theme-light .kpi,body.theme-light .analytics-card,body.theme-light .timeline-shell,body.theme-light .idle-hero,body.theme-light .view-switcher,body.theme-light .theme-switcher,body.theme-light .view-panel,body.theme-aurora .kpi,body.theme-aurora .analytics-card,body.theme-aurora .timeline-shell,body.theme-aurora .idle-hero,body.theme-aurora .view-switcher,body.theme-aurora .theme-switcher,body.theme-aurora .view-panel{background:rgba(255,255,255,.75);border:1px solid var(--line);box-shadow:0 22px 64px rgba(85,96,132,.16),var(--glow);backdrop-filter:blur(22px) saturate(145%);-webkit-backdrop-filter:blur(22px) saturate(145%)}
body.theme-dark .kpi,body.theme-dark .analytics-card,body.theme-dark .timeline-shell,body.theme-dark .idle-hero,body.theme-dark .view-switcher,body.theme-dark .theme-switcher,body.theme-dark .view-panel,body.theme-sapphire .kpi,body.theme-sapphire .analytics-card,body.theme-sapphire .timeline-shell,body.theme-sapphire .idle-hero,body.theme-sapphire .view-switcher,body.theme-sapphire .theme-switcher,body.theme-sapphire .view-panel{background:linear-gradient(145deg,rgba(10,10,19,.985),rgba(3,3,8,.97));border:1px solid rgba(199,178,255,.11);box-shadow:0 30px 86px rgba(0,0,0,.7),var(--glow);backdrop-filter:blur(24px) saturate(132%);-webkit-backdrop-filter:blur(24px) saturate(132%)}
body.theme-light .card,body.theme-aurora .card{background:linear-gradient(145deg,rgba(255,255,255,.82),rgba(248,251,255,.64));border-color:rgba(38,44,57,.11);box-shadow:0 24px 70px rgba(85,96,132,.16),var(--glow);color:var(--text)}
body.theme-dark .card,body.theme-sapphire .card{background:linear-gradient(145deg,rgba(11,11,20,.99),rgba(3,3,8,.97));border-color:rgba(199,178,255,.105);box-shadow:0 30px 86px rgba(0,0,0,.72),var(--glow);color:var(--text)}
body.theme-light .metric,body.theme-light .rec-card,body.theme-light .trust-card,body.theme-light .guide-card,body.theme-light .guide-panel,body.theme-light .brief-q,body.theme-aurora .metric,body.theme-aurora .rec-card,body.theme-aurora .trust-card,body.theme-aurora .guide-card,body.theme-aurora .guide-panel,body.theme-aurora .brief-q{background:rgba(255,255,255,.62);border-color:rgba(38,44,57,.1);color:var(--text)}
body.theme-dark .metric,body.theme-dark .rec-card,body.theme-dark .trust-card,body.theme-dark .guide-card,body.theme-dark .guide-panel,body.theme-dark .brief-q,body.theme-sapphire .metric,body.theme-sapphire .rec-card,body.theme-sapphire .trust-card,body.theme-sapphire .guide-card,body.theme-sapphire .guide-panel,body.theme-sapphire .brief-q{background:rgba(7,7,14,.94);border-color:rgba(199,178,255,.1);color:var(--text)}
body.theme-light .badge,body.theme-aurora .badge{background:rgba(255,255,255,.58)}
body.theme-dark .badge,body.theme-sapphire .badge{background:rgba(167,124,255,.06)}
body.theme-dark .spark polyline,body.theme-sapphire .spark polyline{stroke:#a77cff}
#tab-overview{padding-bottom:96px}
.dashboard-toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end}.view-switcher,.theme-switcher{display:flex;gap:4px;padding:4px;border-radius:14px}.view-chip,.theme-chip{border:1px solid transparent;background:transparent;color:var(--dim);border-radius:10px;padding:8px 10px;font-size:10px;font-weight:950;cursor:pointer;white-space:nowrap}.view-chip:hover,.theme-chip:hover{color:var(--text);background:rgba(255,255,255,.16)}.theme-switcher{border:1px solid var(--line);background:var(--glass);box-shadow:var(--glow)}
.dashboard-view{animation:view-rise .24s ease both}.dashboard-view.hidden{display:none}.dashboard-view+.dashboard-view{margin-top:0}@keyframes view-rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}@media(prefers-reduced-motion:reduce){.dashboard-view{animation:none}.view-chip,.theme-chip{transition:none}}
.onboarding-flow{--surface:#171520;--surface2:#211d2e;--border:#3a334f;--line:rgba(199,178,255,.16);--text:#f7f3ff;--dim:#a99fbd;--muted:#746a86;--accent:#a77cff;--accent2:#ff6bd6;--green:#6de3ac;--red:#ff6c8a;--yellow:#ffd76d;--blue:#65a7ff;--shadow:0 30px 90px rgba(0,0,0,.52);--glow:0 0 0 1px rgba(199,178,255,.12) inset,0 1px 0 rgba(255,255,255,.08) inset;color:var(--text);background:linear-gradient(180deg,#403f4a 0%,#181522 18%,#0b0b10 100%)}.onboarding-flow:before{content:"";position:fixed;inset:0;background:linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(0deg,rgba(255,255,255,.026) 1px,transparent 1px);background-size:34px 34px;mask-image:linear-gradient(180deg,rgba(0,0,0,.74),transparent 82%);pointer-events:none}.onboarding-shell{position:relative;z-index:1}.onboarding-flow .onboarding-side,.onboarding-flow .onboarding-card{background:linear-gradient(145deg,rgba(24,22,34,.94),rgba(13,12,18,.9));border-color:rgba(199,178,255,.18);box-shadow:0 30px 90px rgba(0,0,0,.55),var(--glow)}.onboarding-flow .onboarding-card{position:relative;overflow:hidden}.onboarding-flow .onboarding-card:before{content:"";position:absolute;right:-70px;top:-90px;width:280px;height:220px;background:radial-gradient(circle at 42% 42%,rgba(167,124,255,.35),transparent 62%),radial-gradient(circle at 62% 58%,rgba(255,107,214,.25),transparent 58%);filter:blur(8px);pointer-events:none}.onboarding-flow .onboarding-card>*{position:relative;z-index:1}.onboarding-flow .guide-card,.onboarding-flow .guide-panel,.onboarding-flow .guide-checklist,.onboarding-flow .mini-screen,.onboarding-flow .passive-card,.onboarding-flow .passive-side,.onboarding-flow .setup-step,.onboarding-flow .fallback-details{background:rgba(255,255,255,.045);border-color:rgba(199,178,255,.15);color:var(--text)}.onboarding-flow .guide-hero,.onboarding-flow .business-hero{background:linear-gradient(135deg,rgba(167,124,255,.13),rgba(255,107,214,.07),rgba(101,167,255,.06));border-color:rgba(167,124,255,.24)}.onboarding-flow .guide-eyebrow,.onboarding-flow .passive-state{background:rgba(167,124,255,.14);border-color:rgba(167,124,255,.32);color:#cbb8ff}.onboarding-flow .onboarding-progress span.done,.onboarding-flow .btn.primary{background:linear-gradient(135deg,#a77cff,#ff6bd6);border-color:rgba(255,255,255,.14);color:#0e0c14}.onboarding-flow .btn{background:rgba(255,255,255,.06);border-color:rgba(199,178,255,.16);color:var(--text)}.onboarding-flow input,.onboarding-flow select,.onboarding-flow textarea{background:#15131d;border-color:rgba(199,178,255,.18);color:var(--text)}
.aurora-card{position:relative;overflow:hidden}.aurora-card:after{content:"";position:absolute;right:-32px;top:-34px;width:170px;height:140px;background:radial-gradient(circle at 72% 26%,rgba(92,222,245,.7),transparent 18%),radial-gradient(circle at 44% 22%,rgba(255,151,218,.72),transparent 24%),radial-gradient(circle at 32% 66%,rgba(255,224,100,.62),transparent 20%),radial-gradient(circle at 72% 72%,rgba(77,255,195,.52),transparent 23%);filter:saturate(1.12);opacity:.58;pointer-events:none}.aurora-card .starfield{display:none}.timeline-shell:before,.analytics-hero:before,.idle-hero:before{content:none}.card.aurora-card:after{opacity:.32}.card.aurora-card[data-health=winning]:after{opacity:.55}.card.aurora-card[data-health=fatigue]:after{filter:hue-rotate(24deg);opacity:.46}.card.aurora-card[data-health=losing]:after{filter:hue-rotate(142deg);opacity:.38}
.aurora-card:after,.aurora-card .starfield{z-index:0}.aurora-card>*:not(.starfield),.card .top,.card .metrics,.card .spark,.card .actions,.kpi .v,.kpi .l{position:relative;z-index:1}
.timeline-shell,.analytics-hero,.idle-hero{position:relative;overflow:hidden;border-radius:18px}.timeline-shell{padding:18px;margin-bottom:14px}.timeline-head,.analytics-head,.idle-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:16px;position:relative;z-index:1}.timeline-head h3,.analytics-head h3,.idle-head h3{font-size:20px;line-height:1.05;font-weight:950}.timeline-head p,.analytics-head p,.idle-head p{font-size:12px;color:var(--dim);line-height:1.45;margin-top:5px}.timeline-scale{display:grid;grid-template-columns:120px repeat(7,1fr);gap:8px;align-items:center;color:var(--muted);font-size:10px;font-weight:900;text-transform:uppercase;margin-bottom:10px;position:relative;z-index:1}.timeline-row{display:grid;grid-template-columns:120px 1fr;gap:8px;align-items:center;margin-bottom:9px;position:relative;z-index:1}.timeline-name{font-size:12px;font-weight:950;line-height:1.2}.timeline-track{position:relative;height:42px;border-radius:13px;background:linear-gradient(90deg,rgba(108,118,147,.1),rgba(108,118,147,.04));border:1px solid var(--line);overflow:hidden}.timeline-track:before{content:"";position:absolute;inset:0;background:repeating-linear-gradient(90deg,transparent 0,transparent calc(14.285% - 1px),rgba(108,118,147,.12) calc(14.285% - 1px),rgba(108,118,147,.12) 14.285%)}.timeline-bar{position:absolute;top:7px;height:26px;border-radius:10px;background:linear-gradient(90deg,#ffe06b,#ff9edb,#7bdfff);box-shadow:0 10px 25px rgba(123,77,255,.18);display:flex;align-items:center;justify-content:space-between;gap:8px;padding:0 9px;color:#171a22;font-size:10px;font-weight:950;min-width:120px}.timeline-bar.paused{background:linear-gradient(90deg,#d7dce8,#f3f5fa);color:#697080}.timeline-bar.fatigue{background:linear-gradient(90deg,#ffe071,#ffb26b,#ff8ab5)}.timeline-bar.losing{background:linear-gradient(90deg,#ffb2b8,#ef6a75,#9f74ff);color:#fff}.timeline-status{font-size:10px;color:var(--dim);margin-top:4px}
.analytics-grid{display:grid;grid-template-columns:1.08fr .92fr;gap:12px}.analytics-hero{padding:18px;min-height:214px;background:rgba(255,255,255,.72);border:1px solid var(--line);box-shadow:var(--shadow),var(--glow)}.analytics-legend{display:grid;gap:12px;margin-top:20px;position:relative;z-index:1}.legend-row{display:grid;grid-template-columns:auto 1fr auto;gap:9px;align-items:center;font-size:12px}.legend-dot{width:11px;height:11px;border-radius:3px}.legend-track{height:7px;border-radius:99px;background:rgba(108,118,147,.13);overflow:hidden}.legend-fill{height:100%;border-radius:99px;background:linear-gradient(90deg,#7b4dff,#30d7b4)}.calendar-mini{display:grid;grid-template-columns:repeat(7,1fr);gap:8px;align-items:end;min-height:210px}.calendar-day{display:grid;align-content:end;gap:6px}.calendar-day span{font-size:10px;color:var(--muted);font-weight:900;text-align:center}.day-stack{height:150px;border-radius:14px;background:rgba(255,255,255,.56);border:1px solid var(--line);display:grid;align-content:end;gap:5px;padding:7px}.day-seg{border-radius:6px;background:#dfe4ee}.day-seg.a{background:#c6b8ff}.day-seg.b{background:#ffd55d}.day-seg.c{background:#7fded5}.analytics-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:12px}.analytics-card{border-radius:16px;padding:16px;min-height:150px}.analytics-card h4{font-size:12px;color:var(--dim);margin-bottom:6px}.analytics-card strong{display:block;font-size:24px;line-height:1}.mini-bars{display:grid;grid-template-columns:repeat(7,1fr);gap:6px;align-items:end;height:70px;margin-top:14px}.mini-bars i{display:block;border-radius:7px 7px 4px 4px;background:linear-gradient(180deg,#b9a8ff,#f1efff);min-height:10px}.mini-line{height:70px;margin-top:14px}.avatar-row{display:flex;align-items:center;gap:6px;margin-top:16px}.avatar-chip{display:grid;place-items:center;width:26px;height:26px;border-radius:50%;background:linear-gradient(135deg,#ffe06b,#ff9edb,#78dcff);font-size:10px;font-weight:950;color:#171a22}
.idle-hero{min-height:520px;padding:26px;background:linear-gradient(135deg,rgba(250,247,255,.78),rgba(246,252,255,.72));border:1px solid var(--line);box-shadow:var(--shadow),var(--glow)}.idle-hero:after{content:"";position:absolute;right:4%;bottom:-4%;width:min(42vw,420px);aspect-ratio:1;border-radius:38% 62% 42% 58%;background:radial-gradient(circle at 48% 45%,rgba(150,96,255,.72),rgba(207,171,255,.38) 38%,transparent 62%);filter:blur(.2px);opacity:.9}.idle-grid{position:relative;z-index:1;display:grid;grid-template-columns:1fr;gap:20px;align-items:stretch}.idle-copy h3{font-size:clamp(28px,3vw,38px);line-height:1.08;font-weight:900;letter-spacing:0;max-width:620px}.idle-copy h3 span{color:#7b4dff}.idle-copy p{font-size:14px;color:var(--dim);line-height:1.6;margin-top:14px;max-width:560px}.idle-product-stage{position:relative;min-height:300px;border:1px solid rgba(123,77,255,.14);border-radius:24px;background:radial-gradient(circle at 48% 35%,rgba(255,255,255,.94),rgba(255,255,255,.38) 42%,transparent 62%),linear-gradient(135deg,rgba(123,77,255,.12),rgba(48,215,180,.1));box-shadow:0 30px 90px rgba(123,77,255,.13);overflow:hidden}.idle-product-stage:before{content:"";position:absolute;left:22%;right:22%;bottom:14%;height:28px;border-radius:50%;background:rgba(70,72,93,.18);filter:blur(12px)}.product-orb{position:absolute;left:50%;top:46%;width:180px;aspect-ratio:1;transform:translate(-50%,-50%);border-radius:32% 68% 44% 56%;background:radial-gradient(circle at 35% 28%,#fff,rgba(255,255,255,.4) 20%,transparent 21%),linear-gradient(135deg,#ffe06b,#ff9edb 45%,#7bdfff);box-shadow:inset -22px -22px 48px rgba(85,54,160,.2),0 28px 62px rgba(123,77,255,.22)}.idle-floating{position:absolute;z-index:2;isolation:isolate;border:1px solid rgba(255,255,255,.2);background:linear-gradient(145deg,rgba(9,10,18,.88),rgba(22,19,33,.73));border-radius:16px;padding:13px;box-shadow:0 18px 45px rgba(5,6,13,.34),inset 0 1px 0 rgba(255,255,255,.13);backdrop-filter:blur(20px) saturate(155%) contrast(110%);-webkit-backdrop-filter:blur(20px) saturate(155%) contrast(110%);color:#fbfaff}.idle-floating b{display:block;color:#fbfaff;font-size:21px;line-height:1;text-shadow:0 1px 8px rgba(0,0,0,.32)}.idle-floating span{display:block;font-size:10px;color:rgba(227,220,255,.82);font-weight:900;text-transform:uppercase;margin-top:5px}.idle-floating.one{left:4%;top:20%;border-color:rgba(88,186,255,.5);box-shadow:0 18px 45px rgba(5,6,13,.34),0 0 19px rgba(88,186,255,.18),inset 0 1px 0 rgba(255,255,255,.13)}.idle-floating.two{right:5%;top:36%;border-color:rgba(255,107,214,.45);box-shadow:0 18px 45px rgba(5,6,13,.34),0 0 19px rgba(255,107,214,.16),inset 0 1px 0 rgba(255,255,255,.13)}.idle-floating.three{left:16%;bottom:11%;border-color:rgba(255,172,83,.48);box-shadow:0 18px 45px rgba(5,6,13,.34),0 0 19px rgba(255,172,83,.15),inset 0 1px 0 rgba(255,255,255,.13)}.showcase-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:18px}
body.theme-sapphire .brief-zone{--zone:#64c894;--zone-glow:rgba(100,200,148,.16);--zone-bg:rgba(100,200,148,.024);--zone-border:rgba(100,200,148,.12)}
body.theme-sapphire .work-zone{--zone:#68a7ff;--zone-glow:rgba(104,167,255,.18);--zone-bg:rgba(104,167,255,.026);--zone-border:rgba(104,167,255,.13)}
body.theme-sapphire .rail{--zone:#e4a243;--zone-glow:rgba(228,162,67,.16);--zone-bg:rgba(228,162,67,.024);--zone-border:rgba(228,162,67,.12)}
body.theme-sapphire .page-title{background:linear-gradient(130deg,rgba(10,10,19,.985),rgba(3,3,8,.97));border-color:rgba(199,178,255,.11);box-shadow:0 26px 76px rgba(0,0,0,.7),var(--glow)}
body.theme-sapphire .header-guide-btn{background:rgba(8,8,16,.94);border-color:rgba(167,124,255,.28);color:#cbb8ff}
body.theme-sapphire .header-guide-btn:hover{background:rgba(167,124,255,.11);border-color:rgba(167,124,255,.56)}
body.theme-sapphire .idle-floating{background:linear-gradient(145deg,rgba(7,7,15,.97),rgba(2,2,7,.94));box-shadow:0 20px 48px rgba(0,0,0,.64),inset 0 1px 0 rgba(255,255,255,.09)}
body.theme-sapphire .aurora-card:after{display:none}body.theme-sapphire .idle-hero:after{opacity:.2;filter:blur(24px)}body.theme-sapphire .timeline-shell,body.theme-sapphire .analytics-hero{border-color:rgba(167,124,255,.62);box-shadow:0 0 0 1px rgba(112,193,255,.18),0 0 22px rgba(167,124,255,.22),0 0 42px rgba(255,107,214,.12),inset 0 0 22px rgba(167,124,255,.05)}body.theme-sapphire .idle-hero{border-color:transparent;background:radial-gradient(ellipse at 104% 48%,rgba(255,145,64,.105),transparent 34%),radial-gradient(ellipse at 4% 10%,rgba(93,153,255,.065),transparent 30%),linear-gradient(145deg,rgba(7,7,15,.995),rgba(2,2,6,.995));box-shadow:0 0 0 1px rgba(101,176,255,.35),0 0 10px rgba(116,146,255,.46),0 0 28px rgba(187,78,255,.4),18px 0 48px -16px rgba(255,146,66,.6),-12px 0 32px -15px rgba(93,174,255,.48),inset 0 0 34px rgba(172,93,255,.075)}body.theme-sapphire .timeline-shell:before,body.theme-sapphire .analytics-hero:before,body.theme-sapphire .idle-hero:before{content:"";position:absolute;inset:0;z-index:2;border-radius:inherit;padding:1px;background:linear-gradient(112deg,rgba(105,194,255,.92),rgba(167,124,255,.95) 34%,rgba(255,107,214,.96) 80%,rgba(255,187,107,.72));-webkit-mask:linear-gradient(#fff 0 0) content-box,linear-gradient(#fff 0 0);-webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none}body.theme-sapphire .idle-hero:before{padding:2px;background:linear-gradient(112deg,#58baff 0%,#736eff 22%,#cd57ff 52%,#ff54b5 76%,#ffac53 100%);filter:drop-shadow(0 0 6px rgba(166,106,255,.78)) drop-shadow(7px 0 12px rgba(255,151,63,.55))}body.theme-sapphire .idle-copy h3,body.theme-sapphire .idle-copy h3 span{color:transparent;background:linear-gradient(92deg,#51baff 0%,#8c7cff 30%,#f065d8 61%,#ff9d4f 98%);background-clip:text;-webkit-background-clip:text;-webkit-text-fill-color:transparent}body.theme-sapphire .card.aurora-card[data-health=winning]{border-color:rgba(167,124,255,.52);box-shadow:0 0 0 1px rgba(105,194,255,.12),0 0 18px rgba(167,124,255,.18),0 0 30px rgba(255,107,214,.09),var(--glow)}body.theme-sapphire .idle-product-stage{border-color:rgba(167,124,255,.34);background:radial-gradient(circle at 48% 35%,rgba(167,124,255,.085),rgba(6,6,13,.9) 54%,rgba(2,2,6,.99)),linear-gradient(135deg,rgba(167,124,255,.065),rgba(255,107,214,.035));box-shadow:inset 0 0 40px rgba(167,124,255,.07)}
body.theme-sapphire .kpi,body.theme-sapphire .timeline-shell,body.theme-sapphire .analytics-hero{position:relative;border-color:transparent;background:radial-gradient(ellipse at 102% 48%,rgba(255,145,64,.07),transparent 34%),radial-gradient(ellipse at 2% 5%,rgba(93,153,255,.05),transparent 32%),linear-gradient(145deg,rgba(8,8,16,.993),rgba(2,2,6,.99));box-shadow:0 0 0 1px rgba(101,176,255,.26),0 0 11px rgba(116,146,255,.34),0 0 25px rgba(187,78,255,.28),13px 0 36px -16px rgba(255,146,66,.52),inset 0 0 22px rgba(172,93,255,.065)}
body.theme-sapphire .kpi:before{content:"";position:absolute;inset:0;z-index:2;border-radius:inherit;padding:2px;background:linear-gradient(112deg,#58baff 0%,#736eff 22%,#cd57ff 52%,#ff54b5 76%,#ffac53 100%);-webkit-mask:linear-gradient(#fff 0 0) content-box,linear-gradient(#fff 0 0);-webkit-mask-composite:xor;mask-composite:exclude;filter:drop-shadow(0 0 5px rgba(166,106,255,.7)) drop-shadow(5px 0 9px rgba(255,151,63,.44));pointer-events:none}
body.theme-sapphire .timeline-shell:before,body.theme-sapphire .analytics-hero:before{padding:2px;background:linear-gradient(112deg,#58baff 0%,#736eff 22%,#cd57ff 52%,#ff54b5 76%,#ffac53 100%);filter:drop-shadow(0 0 6px rgba(166,106,255,.72)) drop-shadow(7px 0 11px rgba(255,151,63,.48))}
body.theme-sapphire .kpi .l .tip,body.theme-sapphire .timeline-head h3,body.theme-sapphire .analytics-hero .analytics-head h3{color:transparent;background:linear-gradient(92deg,#51baff 0%,#8c7cff 32%,#f065d8 65%,#ff9d4f 100%);background-clip:text;-webkit-background-clip:text;-webkit-text-fill-color:transparent}
body.theme-sapphire .kpi .help-dot{color:#cbb8ff;-webkit-text-fill-color:#cbb8ff;background:rgba(167,124,255,.12);border-color:rgba(167,124,255,.32)}
body.theme-sapphire .chat-panel{background:linear-gradient(180deg,rgba(5,5,12,.997),rgba(1,1,4,.998));border-color:rgba(167,124,255,.32);box-shadow:10px 0 48px rgba(0,0,0,.75),1px 0 0 rgba(167,124,255,.62),5px 0 26px rgba(255,107,214,.14),inset -1px 0 0 rgba(255,170,77,.12)}
body.theme-sapphire .chat-head{background:linear-gradient(180deg,#050509 0%,#030306 46%,#010103 100%);border-color:rgba(167,124,255,.15);box-shadow:inset 0 -1px 0 rgba(167,124,255,.07)}
body.theme-sapphire .chat-panel.open .chat-head{animation:sapphire-chat-head-sheen .62s ease-out both}
body.theme-sapphire .chat-panel.open .chat-avatar{animation:sapphire-chat-avatar-pop .46s cubic-bezier(.16,1,.3,1) both}
body.theme-sapphire .chat-avatar,body.theme-sapphire .agent-bar-mark{background:linear-gradient(135deg,#58baff,#cd57ff 52%,#ffac53);color:#100c18;box-shadow:0 0 18px rgba(205,87,255,.32)}
body.theme-sapphire .chat-title b{color:transparent;background:linear-gradient(92deg,#51baff,#8c7cff 38%,#f065d8 70%,#ff9d4f);background-clip:text;-webkit-background-clip:text;-webkit-text-fill-color:transparent}
body.theme-sapphire .msg.agent{background:rgba(8,8,16,.94);border-color:rgba(167,124,255,.16)}
body.theme-sapphire .msg.user{background:linear-gradient(135deg,rgba(31,39,70,.58),rgba(40,18,57,.52),rgba(36,13,31,.56));border-color:rgba(205,87,255,.34)}
body.theme-sapphire .msg.thinking{background:linear-gradient(100deg,var(--dim) 0%,var(--dim) 32%,#fff 47%,#cd57ff 54%,#ff9d4f 60%,var(--dim) 72%,var(--dim) 100%);background-size:240% 100%;-webkit-background-clip:text;background-clip:text}
body.theme-sapphire .msg.thinking:before{background:#cd57ff;box-shadow:0 0 12px rgba(205,87,255,.84),0 0 20px rgba(255,157,79,.26)}
body.theme-sapphire .chat-quick .chip{background:rgba(167,124,255,.07);border-color:rgba(167,124,255,.18)}
body.theme-sapphire .chat-form{border-color:rgba(167,124,255,.15);background:rgba(2,2,6,.98)}
body.theme-sapphire .chat-form textarea{background:rgba(6,6,13,.98);border-color:rgba(167,124,255,.17)}
body.theme-sapphire .chat-form textarea:focus{outline:none;border-color:rgba(205,87,255,.62);box-shadow:0 0 0 3px rgba(205,87,255,.12)}
body.theme-sapphire .chat-log{scrollbar-color:rgba(205,87,255,.82) rgba(167,124,255,.08)}
body.theme-sapphire .chat-log::-webkit-scrollbar-track{background:rgba(167,124,255,.08)}
body.theme-sapphire .chat-log::-webkit-scrollbar-thumb{background:linear-gradient(180deg,#58baff,#cd57ff 55%,#ff9d4f);border-color:rgba(15,13,22,.94)}
body.theme-sapphire .chat-log::-webkit-scrollbar-thumb:hover{background:linear-gradient(180deg,#72c7ff,#e679ff 54%,#ffb75e)}
body.theme-sapphire .agent-chat-bar{border-color:rgba(167,124,255,.34);background:rgba(3,3,8,.975);box-shadow:0 22px 74px rgba(0,0,0,.72),0 0 0 1px rgba(88,186,255,.14),0 0 24px rgba(205,87,255,.16),8px 0 32px -15px rgba(255,157,79,.42)}
body.theme-sapphire .agent-chat-bar:before{background:linear-gradient(90deg,rgba(88,186,255,.16),rgba(205,87,255,.2),rgba(255,157,79,.18))}
body.theme-sapphire .agent-chat-bar:focus-within{border-color:rgba(205,87,255,.7);box-shadow:0 24px 80px rgba(0,0,0,.5),0 0 0 1px rgba(88,186,255,.22),0 0 0 6px rgba(205,87,255,.1),10px 0 34px -10px rgba(255,157,79,.5)}
body.theme-sapphire .agent-bar-expand{border-color:rgba(167,124,255,.32);background:rgba(167,124,255,.1);color:#d8c7ff}
body.theme-sapphire .agent-bar-expand:hover{border-color:rgba(205,87,255,.62);background:rgba(205,87,255,.15)}
@keyframes sapphire-chat-head-sheen{0%{box-shadow:inset 0 -1px 0 rgba(167,124,255,.08),0 -14px 30px rgba(255,255,255,.035) inset}100%{box-shadow:inset 0 -1px 0 rgba(167,124,255,.08),0 0 0 rgba(255,255,255,0) inset}}
@keyframes sapphire-chat-avatar-pop{0%{transform:scale(.72) rotate(-8deg);box-shadow:0 0 0 rgba(205,87,255,0)}70%{transform:scale(1.08) rotate(2deg);box-shadow:0 0 0 6px rgba(205,87,255,.15),0 0 20px rgba(255,157,79,.22)}100%{transform:scale(1) rotate(0);box-shadow:0 0 18px rgba(205,87,255,.32)}}
body.theme-aurora .idle-floating,body.theme-light .idle-floating{border-color:rgba(255,255,255,.9);background:linear-gradient(145deg,rgba(255,255,255,.94),rgba(248,247,255,.82));box-shadow:0 16px 36px rgba(80,83,120,.14),inset 0 1px 0 rgba(255,255,255,.96);backdrop-filter:blur(22px) saturate(150%) contrast(104%);-webkit-backdrop-filter:blur(22px) saturate(150%) contrast(104%);color:#18162a}
body.theme-aurora .idle-floating b,body.theme-light .idle-floating b{color:#19162c;text-shadow:0 1px 0 rgba(255,255,255,.7)}
body.theme-aurora .idle-floating span,body.theme-light .idle-floating span{color:rgba(67,61,92,.72)}
body.theme-aurora .idle-floating.one,body.theme-light .idle-floating.one{border-color:rgba(66,161,231,.4);box-shadow:0 16px 36px rgba(80,83,120,.14),0 0 20px rgba(66,161,231,.12),inset 0 1px 0 rgba(255,255,255,.96)}
body.theme-aurora .idle-floating.two,body.theme-light .idle-floating.two{border-color:rgba(220,90,185,.31);box-shadow:0 16px 36px rgba(80,83,120,.14),0 0 20px rgba(220,90,185,.1),inset 0 1px 0 rgba(255,255,255,.96)}
body.theme-aurora .idle-floating.three,body.theme-light .idle-floating.three{border-color:rgba(217,157,47,.34);box-shadow:0 16px 36px rgba(80,83,120,.14),0 0 20px rgba(217,157,47,.1),inset 0 1px 0 rgba(255,255,255,.96)}
/* Ember: black carbon surfaces with a restrained copper/orange signal glow. */
body.theme-ember{--bg:#020202;--shell:rgba(4,4,4,.97);--surface:#070707;--surface2:#0b0a0a;--surface3:#12100f;--glass:rgba(5,5,5,.9);--glass2:rgba(255,103,40,.045);--border:#241b17;--line:rgba(255,133,67,.13);--text:#f5eee9;--dim:#a89387;--muted:#6d574c;--accent:#ff662b;--accent2:#ff9e45;--green:#f69143;--red:#ff6240;--yellow:#ffc05a;--blue:#ff8740;--cyan:#ffb259;--shadow:0 30px 88px rgba(0,0,0,.78);--glow:0 0 0 1px rgba(255,150,85,.055) inset,0 1px 0 rgba(255,202,155,.045) inset;background:radial-gradient(ellipse at 100% 12%,rgba(255,116,45,.1),transparent 30rem),radial-gradient(ellipse at 98% 74%,rgba(255,76,18,.045),transparent 32rem),linear-gradient(to top right,#010101 0%,#020202 42%,#030303 70%,#090503 100%);color:var(--text);font-family:"Satoshi","Plus Jakarta Sans","Manrope","Avenir Next",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
body.theme-ember header{background:linear-gradient(180deg,rgba(6,6,6,.99),rgba(2,2,2,.97));border-bottom-color:rgba(255,120,52,.12);box-shadow:0 18px 65px rgba(0,0,0,.74),0 1px 0 rgba(255,102,43,.16)}
body.theme-ember .brand:before{background:linear-gradient(135deg,#ff3e18,#ff9c43);box-shadow:0 0 19px rgba(255,88,28,.4),inset 0 1px 0 rgba(255,226,194,.28)}
body.theme-ember .brand span{color:#ff7134}
body.theme-ember .brief-zone{--zone:#ffac53;--zone-glow:rgba(255,139,53,.18);--zone-bg:rgba(255,139,53,.028);--zone-border:rgba(255,139,53,.14)}
body.theme-ember .work-zone{--zone:#ff672d;--zone-glow:rgba(255,94,37,.24);--zone-bg:rgba(255,94,37,.034);--zone-border:rgba(255,94,37,.17)}
body.theme-ember .rail{--zone:#e64b20;--zone-glow:rgba(230,75,32,.22);--zone-bg:rgba(230,75,32,.03);--zone-border:rgba(230,75,32,.15)}
body.theme-ember .section{background:linear-gradient(148deg,rgba(7,7,7,.98),rgba(3,3,3,.97));border-color:rgba(255,117,51,.105);box-shadow:0 25px 72px rgba(0,0,0,.7),inset 0 1px 0 rgba(255,167,106,.025)}
body.theme-ember .head,body.theme-ember .tabs,body.theme-ember .pill,body.theme-ember .lang-select,body.theme-ember .chip{background:rgba(6,6,6,.88);border-color:rgba(255,124,58,.12)}
body.theme-ember .header-guide-btn{border-color:rgba(255,106,40,.3);background:rgba(255,97,33,.08);color:#ff9850}
body.theme-ember .header-guide-btn:hover{border-color:rgba(255,105,39,.62);background:rgba(255,95,31,.14)}
body.theme-ember .page-title{background:linear-gradient(125deg,rgba(8,8,8,.97),rgba(3,3,3,.95));border-color:rgba(255,118,46,.12);box-shadow:0 22px 65px rgba(0,0,0,.68),inset 0 1px 0 rgba(255,166,99,.035)}
body.theme-ember .tab.active,body.theme-ember .view-chip.active,body.theme-ember .theme-chip.active{background:linear-gradient(135deg,rgba(80,29,12,.66),rgba(15,10,8,.95));color:#fff5ee;border-color:rgba(255,111,44,.46);box-shadow:inset 0 1px 0 rgba(255,192,134,.13),0 0 22px rgba(255,86,25,.2)}
body.theme-ember .theme-switcher,body.theme-ember .view-switcher{background:rgba(3,3,3,.9);border-color:rgba(255,116,45,.12)}
body.theme-ember input,body.theme-ember select,body.theme-ember textarea{background:#050505;color:var(--text);border-color:rgba(255,125,56,.14)}
body.theme-ember input:focus,body.theme-ember select:focus,body.theme-ember textarea:focus{border-color:rgba(255,103,40,.6)}
body.theme-ember .btn{background:rgba(5,5,5,.9);color:var(--text);border-color:rgba(255,126,54,.14)}
body.theme-ember .btn:hover{background:rgba(255,99,38,.12);border-color:rgba(255,105,39,.52)}
body.theme-ember .btn.primary,body.theme-ember .agent-bar-send{background:linear-gradient(135deg,#ff5523,#ff9c43);color:#160906;border-color:rgba(255,183,110,.36);box-shadow:0 8px 24px rgba(255,84,27,.27)}
body.theme-ember .ask-btn{background:rgba(255,94,35,.055);border-color:rgba(255,105,37,.3);color:#ff9f59}
body.theme-ember .signal{color:#ffae68;background:rgba(255,95,36,.045);border-color:rgba(255,105,37,.22)}
body.theme-ember .signal:before{background:#ff6328;box-shadow:0 0 0 4px rgba(255,101,40,.15),0 0 18px rgba(255,85,25,.44)}
body.theme-ember .kpi,body.theme-ember .analytics-card,body.theme-ember .timeline-shell,body.theme-ember .idle-hero,body.theme-ember .view-panel{background:linear-gradient(148deg,rgba(7,7,7,.985),rgba(2,2,2,.975));border-color:rgba(255,116,47,.12);box-shadow:0 27px 74px rgba(0,0,0,.72),inset 0 1px 0 rgba(255,161,92,.028);backdrop-filter:blur(22px) saturate(110%);-webkit-backdrop-filter:blur(22px) saturate(110%)}
body.theme-ember .kpi{position:relative;overflow:hidden}
body.theme-ember .kpi:after{content:"";position:absolute;inset:auto -24% -65% 12%;height:92px;background:radial-gradient(ellipse,rgba(255,88,24,.11),transparent 66%);pointer-events:none}
body.theme-ember .card{background:linear-gradient(145deg,rgba(7,7,7,.99),rgba(2,2,2,.97));border-color:rgba(255,118,49,.105);box-shadow:0 28px 80px rgba(0,0,0,.74),inset 0 1px 0 rgba(255,173,103,.025);color:var(--text)}
body.theme-ember .aurora-card:after{background:radial-gradient(circle at 54% 40%,rgba(255,100,30,.12),transparent 34%),radial-gradient(circle at 75% 66%,rgba(255,166,73,.06),transparent 30%);filter:none;opacity:.68}
body.theme-ember .metric,body.theme-ember .rec-card,body.theme-ember .trust-card,body.theme-ember .guide-card,body.theme-ember .guide-panel,body.theme-ember .brief-q{background:rgba(4,4,4,.92);border-color:rgba(255,127,58,.095);color:var(--text)}
body.theme-ember .badge{background:rgba(255,105,42,.035)}
body.theme-ember .spark polyline{stroke:#ff6c30}
body.theme-ember .timeline-track{background:linear-gradient(90deg,rgba(6,6,6,.98),rgba(2,2,2,.98));border-color:rgba(255,125,58,.11)}
body.theme-ember .timeline-bar{background:linear-gradient(90deg,#ff5322,#ff9c43);color:#170906;box-shadow:0 12px 28px rgba(255,78,21,.27)}
body.theme-ember .timeline-bar.fatigue{background:linear-gradient(90deg,#ff8b36,#ffc05a)}
body.theme-ember .timeline-bar.losing{background:linear-gradient(90deg,#ff7140,#c73c22);color:#fff0e8}
body.theme-ember .legend-fill,body.theme-ember .mini-bars i{background:linear-gradient(90deg,#ff5824,#ff9d43)}
body.theme-ember .day-seg.a{background:#8f391d}body.theme-ember .day-seg.b{background:#ff672d}body.theme-ember .day-seg.c{background:#ffab52}
body.theme-ember .idle-hero{border-color:rgba(255,100,33,.2);background:radial-gradient(ellipse at 96% 48%,rgba(255,87,22,.065),transparent 38%),linear-gradient(145deg,rgba(6,6,6,.995),rgba(1,1,1,.99));box-shadow:0 0 0 1px rgba(255,110,38,.13),0 0 30px rgba(255,77,17,.08),18px 0 55px -25px rgba(255,101,30,.25),0 28px 80px rgba(0,0,0,.78)}
body.theme-ember .idle-hero:after{opacity:.08;background:radial-gradient(circle at 48% 45%,rgba(255,98,27,.66),rgba(255,142,54,.22) 38%,transparent 63%);filter:blur(20px)}
body.theme-ember .idle-copy h3 span{color:#ff7133}
body.theme-ember .idle-product-stage{border-color:rgba(255,112,41,.15);background:radial-gradient(circle at 48% 38%,rgba(255,92,25,.075),rgba(5,5,5,.9) 52%,rgba(1,1,1,.99)),linear-gradient(135deg,rgba(255,97,29,.04),transparent);box-shadow:inset 0 0 44px rgba(255,79,18,.05)}
body.theme-ember .product-orb{background:radial-gradient(circle at 34% 28%,#ffd4ad,rgba(255,210,167,.35) 19%,transparent 20%),linear-gradient(135deg,#ffbc58,#ff6126 46%,#7d2212);box-shadow:inset -22px -22px 48px rgba(78,20,9,.28),0 30px 66px rgba(255,80,18,.23)}
body.theme-ember .idle-floating{background:linear-gradient(145deg,rgba(8,8,8,.96),rgba(2,2,2,.92));border-color:rgba(255,117,44,.21);color:#fff3e9;box-shadow:0 20px 46px rgba(0,0,0,.58),0 0 15px rgba(255,86,21,.08),inset 0 1px 0 rgba(255,186,117,.06);backdrop-filter:blur(20px) saturate(116%);-webkit-backdrop-filter:blur(20px) saturate(116%)}
body.theme-ember .idle-floating b{color:#fff4eb;text-shadow:0 1px 9px rgba(0,0,0,.48)}body.theme-ember .idle-floating span{color:#cb9f89}
body.theme-ember .idle-floating.one,body.theme-ember .idle-floating.two,body.theme-ember .idle-floating.three{border-color:rgba(255,108,41,.36);box-shadow:0 20px 46px rgba(0,0,0,.48),0 0 17px rgba(255,84,22,.17),inset 0 1px 0 rgba(255,186,117,.09)}
body.theme-ember .chat-panel{background:linear-gradient(180deg,rgba(5,5,5,.995),rgba(1,1,1,.998));border-color:rgba(255,104,37,.22);box-shadow:10px 0 46px rgba(0,0,0,.8),1px 0 0 rgba(255,100,32,.32),5px 0 26px rgba(255,78,17,.08)}
body.theme-ember .chat-head{background:linear-gradient(180deg,#040404,#010101 100%);border-color:rgba(255,117,48,.11)}
body.theme-ember .chat-panel.open .chat-head{animation:ember-chat-head-sheen .62s ease-out both}body.theme-ember .chat-panel.open .chat-avatar{animation:ember-chat-avatar-pop .46s cubic-bezier(.16,1,.3,1) both}
body.theme-ember .chat-avatar,body.theme-ember .agent-bar-mark{background:linear-gradient(135deg,#ff4720,#ff9c43);color:#1b0a05;box-shadow:0 0 18px rgba(255,83,22,.32)}
body.theme-ember .chat-title b{color:#ff8b4b}body.theme-ember .msg.agent{background:rgba(6,6,6,.96);border-color:rgba(255,127,57,.095)}body.theme-ember .msg.user{background:linear-gradient(135deg,rgba(70,26,13,.42),rgba(8,7,6,.94));border-color:rgba(255,103,38,.28)}
body.theme-ember .msg.thinking{background:linear-gradient(100deg,var(--dim) 0%,var(--dim) 34%,#fff 47%,#ff662b 55%,#ffab55 61%,var(--dim) 73%,var(--dim) 100%);background-size:240% 100%;-webkit-background-clip:text;background-clip:text}body.theme-ember .msg.thinking:before{background:#ff6328;box-shadow:0 0 12px rgba(255,90,26,.82)}
body.theme-ember .chat-form{border-color:rgba(255,119,49,.1);background:rgba(2,2,2,.98)}body.theme-ember .chat-form textarea{background:rgba(5,5,5,.98);border-color:rgba(255,125,56,.12)}body.theme-ember .chat-form textarea:focus{outline:none;border-color:rgba(255,105,39,.62);box-shadow:0 0 0 3px rgba(255,95,30,.12)}
body.theme-ember .chat-log{scrollbar-color:rgba(255,102,40,.82) rgba(255,105,40,.06)}body.theme-ember .chat-log::-webkit-scrollbar-track{background:rgba(255,105,40,.06)}body.theme-ember .chat-log::-webkit-scrollbar-thumb{background:linear-gradient(180deg,#ff5123,#ff9f46);border-color:rgba(7,5,4,.94)}
body.theme-ember .agent-chat-bar{border-color:rgba(255,106,40,.26);background:rgba(3,3,3,.975);box-shadow:0 20px 72px rgba(0,0,0,.76),0 0 0 1px rgba(255,106,40,.095),0 0 24px rgba(255,75,14,.09)}body.theme-ember .agent-chat-bar:before{background:linear-gradient(90deg,rgba(255,77,18,.1),rgba(255,152,60,.075))}body.theme-ember .agent-chat-bar:focus-within{border-color:rgba(255,105,39,.58);box-shadow:0 24px 80px rgba(0,0,0,.8),0 0 0 5px rgba(255,96,31,.075)}
body.theme-ember .agent-bar-expand{border-color:rgba(255,108,43,.28);background:rgba(255,103,40,.08);color:#ff9e59}body.theme-ember .agent-bar-expand:hover{border-color:rgba(255,106,40,.58);background:rgba(255,100,37,.15)}
@keyframes ember-chat-head-sheen{0%{box-shadow:inset 0 -1px 0 rgba(255,111,40,.12),0 -14px 30px rgba(255,97,29,.11) inset}100%{box-shadow:inset 0 -1px 0 rgba(255,111,40,.12),0 0 0 rgba(255,97,29,0) inset}}
@keyframes ember-chat-avatar-pop{0%{transform:scale(.72) rotate(-8deg);box-shadow:0 0 0 rgba(255,84,22,0)}70%{transform:scale(1.08) rotate(2deg);box-shadow:0 0 0 6px rgba(255,94,30,.14),0 0 21px rgba(255,145,58,.19)}100%{transform:scale(1) rotate(0);box-shadow:0 0 18px rgba(255,83,22,.32)}}
#tab-creatives{padding-bottom:96px}
.creative-studio-hero{position:relative;overflow:hidden;display:grid;grid-template-columns:1fr;gap:14px;padding:18px;margin-bottom:12px;border:1px solid var(--line);border-radius:18px;background:var(--glass);box-shadow:var(--shadow),var(--glow)}
.creative-studio-hero:before{content:"";position:absolute;inset:auto -68px -110px auto;width:310px;height:260px;background:linear-gradient(120deg,rgba(123,77,255,.2),rgba(48,215,180,.13),rgba(255,210,87,.2));filter:blur(34px);pointer-events:none}
.creative-studio-copy,.creative-studio-pulse{position:relative;z-index:1}.creative-kicker{display:block;margin-bottom:8px;color:var(--accent);font-size:10px;font-weight:950;text-transform:uppercase}.creative-studio-copy h2{font-size:28px;line-height:1.06;font-weight:950}.creative-studio-copy p{max-width:550px;margin-top:9px;color:var(--dim);font-size:13px;line-height:1.55}.creative-studio-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
.creative-studio-pulse{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;align-content:center}.creative-studio-pulse .notice{grid-column:1/-1;margin:1px 0 0}.creative-pulse-stat{border:1px solid var(--line);border-radius:12px;background:var(--glass2);padding:10px}.creative-pulse-stat b{display:block;font-size:20px;line-height:1}.creative-pulse-stat span{display:block;margin-top:5px;color:var(--dim);font-size:10px;font-weight:850;text-transform:uppercase}
.creative-studio-layout{display:grid;grid-template-columns:1fr;gap:12px;align-items:start}.creative-studio-memory,.creative-gallery-panel,.creative-approval-panel{border:1px solid var(--line);border-radius:16px;background:var(--glass);box-shadow:var(--glow);padding:14px}.creative-studio-memory{padding:0}.brand-vault-strip{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:12px 14px}.brand-vault-summary{display:flex;align-items:center;gap:11px;min-width:0}.brand-vault-mark{display:grid;place-items:center;width:39px;height:39px;flex:none;border-radius:12px;background:linear-gradient(138deg,var(--accent),var(--accent2));color:#fff;font-size:12px;font-weight:950;box-shadow:0 8px 20px rgba(76,102,228,.2)}.brand-vault-summary b{display:block;font-size:13px}.brand-vault-summary p{margin:3px 0 0;color:var(--dim);font-size:11px;line-height:1.35}.brand-vault-pills{display:flex;align-items:center;gap:5px;flex-wrap:wrap;margin-top:7px}.brand-vault-pill{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--line);border-radius:999px;background:var(--surface);padding:4px 7px;color:var(--dim);font-size:10px;font-weight:750}.brand-vault-pill.ready:before{content:"";display:block;width:6px;height:6px;border-radius:50%;background:var(--success)}.brand-vault-actions{display:flex;align-items:center;gap:7px;flex:none}.brand-memory-overlay{position:fixed;inset:0;z-index:69;display:none;place-items:center;padding:18px;background:rgba(4,5,11,.68);backdrop-filter:blur(18px)}.brand-memory-overlay.open{display:grid}.brand-memory-modal{width:min(980px,100%);height:min(780px,calc(100vh - 36px));display:grid;grid-template-rows:auto minmax(0,1fr);overflow:hidden;border:1px solid var(--line);border-radius:22px;background:var(--bg);box-shadow:0 32px 100px rgba(4,8,21,.42),var(--glow)}.brand-memory-head{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;padding:20px 22px 16px;border-bottom:1px solid var(--line);background:var(--glass)}.brand-memory-head .creative-kicker{margin-bottom:6px}.brand-memory-head h2{font-size:23px;line-height:1.1}.brand-memory-head p{margin-top:6px;max-width:620px;color:var(--dim);font-size:12px;line-height:1.5}.brand-memory-close{display:grid;place-items:center;width:34px;height:34px;min-height:34px;padding:0;border-radius:50%;font-size:17px}.brand-memory-workspace{display:grid;grid-template-columns:242px minmax(0,1fr);min-height:0}.brand-memory-nav{overflow:auto;border-right:1px solid var(--line);background:var(--glass);padding:15px 11px}.brand-nav-label{display:block;margin:2px 8px 9px;color:var(--dim);font-size:10px;font-weight:950;text-transform:uppercase}.brand-nav-item{display:flex;justify-content:space-between;align-items:center;gap:8px;width:100%;margin-bottom:6px;padding:11px 10px;border:1px solid transparent;border-radius:11px;background:transparent;color:var(--text);text-align:left;cursor:pointer}.brand-nav-item:hover,.brand-nav-item.active{border-color:var(--line);background:var(--surface)}.brand-nav-item b{display:block;max-width:135px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}.brand-nav-item small{display:block;margin-top:3px;color:var(--dim);font-size:10px}.brand-ready{border-radius:999px;padding:4px 6px;background:rgba(44,191,124,.13);color:var(--success);font-size:9px;font-weight:950}.brand-ready.draft{background:rgba(245,176,46,.13);color:var(--warning)}.brand-new-product{width:100%;margin-top:10px}.brand-memory-editor{min-height:0;overflow:auto;padding:20px 22px}.brand-editor-intro{margin-bottom:18px}.brand-editor-intro h3{font-size:19px;line-height:1.15}.brand-editor-intro p{margin-top:7px;max-width:630px;color:var(--dim);font-size:12px;line-height:1.55}.memory-wizard-cta{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:13px;padding:12px;border:1px solid color-mix(in srgb,var(--accent) 32%,var(--line));border-radius:14px;background:linear-gradient(135deg,color-mix(in srgb,var(--accent) 12%,transparent),color-mix(in srgb,var(--accent2) 10%,transparent)),var(--surface);box-shadow:0 14px 35px rgba(0,0,0,.08)}.memory-wizard-cta b{display:block;font-size:12px}.memory-wizard-cta p{margin-top:3px;font-size:11px;line-height:1.4}.memory-wizard-cta .btn{flex:none}.brand-editor-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}.brand-editor-form{display:grid;gap:19px}.brand-form-section{padding-top:16px;border-top:1px solid var(--line)}.brand-form-section:first-of-type{padding-top:0;border-top:0}.brand-form-section h4{margin-bottom:12px;font-size:12px;font-weight:950;text-transform:uppercase;color:var(--dim)}.brand-form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px}.brand-field{display:grid;gap:6px;min-width:0}.brand-field.wide{grid-column:1/-1}.brand-field span{color:var(--dim);font-size:10px;font-weight:900;text-transform:uppercase}.brand-field input,.brand-field textarea{width:100%;min-height:42px;border:1px solid var(--line);border-radius:10px;padding:11px;background:var(--surface);color:var(--text);font:inherit;font-size:12px}.brand-field textarea{min-height:73px;resize:vertical;line-height:1.45}.brand-field input:focus,.brand-field textarea:focus{outline:2px solid color-mix(in srgb,var(--accent) 38%,transparent);border-color:var(--accent)}.brand-form-save{display:flex;align-items:center;justify-content:flex-end;gap:9px;padding-top:2px}.creative-gallery-head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:14px}.creative-gallery-head h3{font-size:17px;line-height:1.15}.creative-batch{border-top:1px solid var(--line);padding-top:14px;margin-top:14px}.creative-batch:first-child{border-top:0;padding-top:0;margin-top:0}.creative-batch-head{display:flex;gap:12px;justify-content:space-between;align-items:center;margin-bottom:11px}.creative-batch-head h4{font-size:13px}.creative-batch-meta{color:var(--dim);font-size:10px;margin-top:4px}.creative-batch-product{display:inline-flex;margin-left:5px;border-radius:999px;padding:3px 7px;background:rgba(123,77,255,.1);color:var(--accent);font-size:9px;font-weight:900}.creative-variants{display:grid;grid-template-columns:repeat(auto-fit,minmax(188px,1fr));gap:9px}
.brand-advanced{border-top:1px solid var(--line);padding-top:13px}.brand-advanced summary{display:flex;align-items:center;justify-content:space-between;cursor:pointer;list-style:none;border:1px solid var(--line);border-radius:10px;padding:11px 12px;color:var(--dim);font-size:11px;font-weight:900}.brand-advanced summary::-webkit-details-marker{display:none}.brand-advanced summary:after{content:"+";font-size:15px;color:var(--accent)}.brand-advanced[open] summary:after{content:"-"}.brand-advanced .brand-form-section{margin-top:15px}.memory-manual-entry{margin-top:17px}.memory-manual-entry>summary{display:flex;align-items:center;justify-content:space-between;cursor:pointer;list-style:none;border:1px solid var(--line);border-radius:12px;padding:13px 14px;color:var(--text);background:var(--surface);font-size:12px;font-weight:850}.memory-manual-entry>summary::-webkit-details-marker{display:none}.memory-manual-entry>summary:after{content:"+";color:var(--accent);font-size:17px}.memory-manual-entry[open]>summary{margin-bottom:18px}.memory-manual-entry[open]>summary:after{content:"-"}.memory-manual-help{display:block;margin-top:4px;color:var(--dim);font-size:10px;font-weight:600}.creative-variant{display:flex;flex-direction:column;min-width:0;border:1px solid var(--line);border-radius:12px;background:var(--surface);overflow:hidden}.creative-frame{position:relative;aspect-ratio:4/3;overflow:hidden;border-bottom:1px solid var(--line);background:linear-gradient(122deg,rgba(123,77,255,.14),rgba(48,215,180,.09),rgba(244,183,64,.12))}.creative-frame img{display:block;width:100%;height:100%;object-fit:cover}.creative-frame-loading{position:absolute;inset:0;display:grid;place-items:center;color:var(--dim);font-size:10px;font-weight:850}.creative-concept-board{height:100%;display:flex;flex-direction:column;justify-content:space-between;padding:11px;background:linear-gradient(145deg,rgba(255,255,255,.07),transparent),repeating-linear-gradient(90deg,transparent 0,transparent 23px,rgba(255,255,255,.04) 24px),linear-gradient(125deg,rgba(123,77,255,.14),rgba(48,215,180,.09),rgba(244,183,64,.12))}.creative-concept-board b{max-width:132px;font-size:12px;line-height:1.2}.creative-ratios{display:flex;gap:4px}.creative-ratios span{border:1px solid var(--line);border-radius:999px;padding:4px 6px;color:var(--dim);font-size:9px;font-weight:850}.creative-asset-state{position:absolute;right:8px;top:8px;border:1px solid var(--line);border-radius:999px;background:rgba(10,11,16,.7);color:#fff;padding:4px 7px;font-size:9px;font-weight:900}
.creative-variant-body{display:grid;gap:8px;padding:11px;flex:1}.creative-variant-body h4{font-size:12px;line-height:1.3}.creative-angle{width:max-content;border-radius:999px;background:rgba(123,77,255,.1);color:var(--accent);padding:4px 7px;font-size:9px;font-weight:950;text-transform:uppercase}.creative-copy{color:var(--dim);font-size:10px;line-height:1.45;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}.creative-cta{font-size:10px;font-weight:900}.creative-actions{display:flex;gap:6px;margin-top:auto}.creative-actions .btn{min-height:32px;padding:7px 8px;font-size:10px;flex:1}.creative-empty{display:grid;place-items:center;min-height:260px;border:1px dashed var(--line);border-radius:14px;text-align:center;padding:24px}.creative-empty h3{font-size:17px}.creative-empty p{max-width:370px;margin:8px auto 16px;color:var(--dim);font-size:12px;line-height:1.55}
.creative-approval-panel{margin-top:12px}.creative-upload-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.creative-upload-card{border:1px solid var(--line);border-radius:11px;background:var(--surface);padding:12px}.creative-upload-card h4{font-size:12px;line-height:1.3}.creative-upload-card p{color:var(--dim);font-size:10px;line-height:1.45;margin-top:6px}.creative-upload-card .badge{margin-top:9px}.creative-blockers{margin-top:8px;color:var(--dim);font-size:10px;line-height:1.45}.creative-retention-card{grid-column:1/-1;display:grid;grid-template-columns:auto 1fr;gap:10px;align-items:start;margin-top:2px;padding:12px;border:1px solid color-mix(in srgb,var(--accent) 28%,var(--line));border-radius:14px;background:linear-gradient(135deg,color-mix(in srgb,var(--accent) 10%,transparent),color-mix(in srgb,var(--accent2) 8%,transparent)),var(--surface);box-shadow:var(--glow)}.creative-retention-icon{display:grid;place-items:center;width:32px;height:32px;border-radius:11px;background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;font-size:15px;font-weight:950}.creative-retention-card b{display:block;font-size:12px}.creative-retention-card p{margin-top:4px;color:var(--dim);font-size:11px;line-height:1.42}.creative-retention-tags{display:flex;gap:5px;flex-wrap:wrap;margin-top:8px}.creative-retention-tags span,.creative-retention-note{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--line);border-radius:999px;background:var(--glass2);padding:4px 7px;color:var(--dim);font-size:9px;font-weight:900}.creative-retention-actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}.creative-retention-actions .btn{min-height:30px;padding:7px 9px;font-size:10px}.creative-retention-note.saved{color:var(--success);border-color:color-mix(in srgb,var(--success) 35%,var(--line));background:color-mix(in srgb,var(--success) 10%,transparent)}.creative-retention-note.expiring{color:var(--warning);border-color:color-mix(in srgb,var(--warning) 40%,var(--line));background:color-mix(in srgb,var(--warning) 12%,transparent)}
body.theme-aurora .creative-studio-hero,body.theme-aurora .creative-studio-memory,body.theme-aurora .creative-gallery-panel,body.theme-aurora .creative-approval-panel{background:rgba(255,255,255,.68);box-shadow:0 24px 66px rgba(85,96,132,.13),var(--glow)}
body.theme-aurora .brand-memory-modal{background:#fbfcff}body.theme-aurora .brand-memory-head,body.theme-aurora .brand-memory-nav{background:rgba(249,250,255,.92)}
body.theme-sapphire .creative-studio-hero,body.theme-sapphire .creative-gallery-panel{border-color:rgba(167,124,255,.52);background:linear-gradient(145deg,rgba(8,8,16,.99),rgba(2,2,6,.99));box-shadow:0 0 0 1px rgba(101,176,255,.17),0 0 26px rgba(187,78,255,.18),12px 0 38px -19px rgba(255,146,66,.46),var(--shadow)}
body.theme-sapphire .creative-studio-copy h2{color:transparent;background:linear-gradient(92deg,#51baff,#8c7cff 34%,#f065d8 67%,#ff9d4f);background-clip:text;-webkit-background-clip:text;-webkit-text-fill-color:transparent}
body.theme-sapphire .brand-memory-modal{border-color:rgba(167,124,255,.48);box-shadow:0 0 0 1px rgba(101,176,255,.15),0 0 45px rgba(187,78,255,.17),0 34px 100px rgba(0,0,0,.7)}
body.theme-ember .creative-studio-hero,body.theme-ember .creative-studio-memory,body.theme-ember .creative-gallery-panel,body.theme-ember .creative-approval-panel{border-color:rgba(255,105,39,.17);background:linear-gradient(148deg,rgba(7,7,7,.985),rgba(2,2,2,.98));box-shadow:0 28px 82px rgba(0,0,0,.76),inset 0 1px 0 rgba(255,171,101,.05)}
body.theme-ember .brand-memory-modal{border-color:rgba(255,105,39,.22);background:#030303;box-shadow:0 0 28px rgba(255,79,21,.12),0 34px 100px rgba(0,0,0,.8)}body.theme-ember .brand-vault-mark{background:linear-gradient(135deg,#ff491e,#ffa443)}
body.theme-ember .creative-studio-hero:before{background:linear-gradient(120deg,rgba(255,74,20,.2),rgba(255,150,51,.12),transparent)}body.theme-ember .creative-kicker,body.theme-ember .creative-angle{color:#ff823e}body.theme-ember .creative-concept-board{background:linear-gradient(145deg,rgba(255,105,39,.08),transparent),repeating-linear-gradient(90deg,transparent 0,transparent 23px,rgba(255,105,39,.035) 24px),#050505}
@media(max-width:1180px){.dashboard-toolbar{justify-content:flex-start}.analytics-grid{grid-template-columns:1fr}.analytics-cards{grid-template-columns:1fr 1fr}.idle-grid{grid-template-columns:1fr}.idle-product-stage{min-height:300px}}
@media(max-width:780px){.dashboard-toolbar,.view-switcher,.theme-switcher{width:100%;justify-content:stretch}.view-switcher,.theme-switcher{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.view-chip,.theme-chip{width:100%;padding:9px 8px}.timeline-scale{display:none}.timeline-row{grid-template-columns:1fr}.timeline-track{height:48px}.analytics-cards{grid-template-columns:1fr}.calendar-mini{gap:5px}.idle-hero{min-height:auto;padding:18px}.idle-copy h3{font-size:30px}.idle-product-stage{min-height:260px}.idle-floating{position:relative;left:auto!important;right:auto!important;top:auto!important;bottom:auto!important;margin:8px 0}.idle-product-stage .idle-floating{display:none}.creative-studio-hero{padding:16px}.creative-studio-copy h2{font-size:23px}.creative-studio-pulse{grid-template-columns:repeat(3,minmax(0,1fr))}.creative-pulse-stat{padding:9px}.creative-pulse-stat b{font-size:17px}.brand-vault-strip{align-items:flex-start;flex-direction:column}.brand-vault-actions{width:100%}.brand-vault-actions .btn{flex:1}.brand-memory-overlay{padding:0}.brand-memory-modal{height:100vh;max-height:none;border-radius:0}.brand-memory-head{padding:16px}.brand-memory-head h2{font-size:20px}.brand-memory-workspace{grid-template-columns:1fr;grid-template-rows:auto minmax(0,1fr)}.brand-memory-nav{display:flex;gap:6px;border-right:0;border-bottom:1px solid var(--line);padding:10px;overflow-x:auto}.brand-nav-label{display:none}.brand-nav-item{width:auto;min-width:146px;margin:0}.brand-new-product{min-width:130px;margin:0}.brand-memory-editor{padding:16px}.memory-wizard-cta{align-items:stretch;flex-direction:column}.memory-wizard-cta .btn{width:100%}.brand-form-grid{grid-template-columns:1fr}.creative-gallery-head{align-items:flex-start;flex-direction:column}.creative-variants,.creative-upload-grid{grid-template-columns:1fr}.creative-frame{aspect-ratio:16/10}.targeting-intro{flex-direction:column}.targeting-intro .btn{width:100%}.targeting-mode-grid,.targeting-search-grid{grid-template-columns:1fr}.targeting-search-row{grid-template-columns:1fr}.targeting-search-row .btn{width:100%}}
@media(max-width:780px){.theme-switcher{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:780px){.brand-memory-nav{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));overflow:visible}.brand-nav-item,.brand-new-product{width:100%;min-width:0}.brand-nav-item b{max-width:none;white-space:normal;line-height:1.25}}
.msg-actions{display:grid;gap:7px;margin-top:10px;padding-top:9px;border-top:1px solid var(--line)}.msg-approval-card{border:1px solid color-mix(in srgb,var(--accent) 22%,var(--line));border-radius:9px;background:rgba(255,255,255,.05);padding:8px}.msg-approval-card b{display:block;font-size:11px;color:var(--text);line-height:1.25}.msg-approval-card span{display:block;font-size:10px;color:var(--dim);margin-top:3px}.msg-approval-buttons{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:7px}.msg-approval-buttons .btn{width:100%;font-size:10px;padding:8px}
.chatgpt-connect-card{position:relative;overflow:hidden;border:1px solid color-mix(in srgb,var(--accent) 28%,var(--line));border-radius:10px;background:linear-gradient(135deg,rgba(39,199,167,.12),rgba(99,168,255,.08),rgba(255,255,255,.04));padding:13px;margin-bottom:14px;box-shadow:var(--glow)}.chatgpt-connect-card:before{content:"";position:absolute;inset:0;background:linear-gradient(120deg,transparent,rgba(255,255,255,.08),transparent);transform:translateX(-100%);animation:softSweep 8s ease-in-out infinite;pointer-events:none}.chatgpt-connect-card>*{position:relative;z-index:1}.chatgpt-connect-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:10px}.chatgpt-connect-head .badge{border:1px solid color-mix(in srgb,var(--accent) 32%,var(--line));background:rgba(0,0,0,.22);color:var(--text);box-shadow:0 8px 22px rgba(0,0,0,.14)}.chatgpt-connect-head .badge.warn{color:#fff;background:linear-gradient(135deg,rgba(123,77,255,.48),rgba(255,111,205,.36))}.chatgpt-connect-head .badge.ok{color:#0b2118;background:linear-gradient(135deg,#6ff0a0,#9ef6d3)}.chatgpt-connect-head h3{font-size:15px;line-height:1.14}.chatgpt-connect-head p{font-size:11px;color:var(--dim);line-height:1.45;margin-top:5px}.model-route-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:10px 0}.model-route-card{border:1px solid var(--line);border-radius:8px;background:rgba(0,0,0,.12);padding:10px}.model-route-card>span{display:inline-grid;place-items:center;width:24px;height:24px;border-radius:7px;background:color-mix(in srgb,var(--accent) 20%,transparent);color:var(--accent);font-size:11px;font-weight:950}.model-route-card b{display:block;font-size:11px;line-height:1.25;margin-top:7px}.model-route-card p{font-size:10px;color:var(--dim);line-height:1.45;margin-top:4px}.agent-model-picker{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:12px 0}.agent-model-option{display:grid;grid-template-columns:auto 1fr;gap:9px;align-items:start;min-height:88px;border:1px solid var(--line);border-radius:11px;background:rgba(0,0,0,.12);color:var(--text);padding:11px;text-align:left;cursor:pointer;transition:transform .16s ease,border-color .16s ease,background .16s ease,box-shadow .16s ease}.agent-model-option:hover{transform:translateY(-1px);border-color:color-mix(in srgb,var(--accent) 38%,var(--line));background:rgba(255,255,255,.055)}.agent-model-option.active{border-color:color-mix(in srgb,var(--accent) 62%,var(--line));background:linear-gradient(135deg,color-mix(in srgb,var(--accent) 16%,transparent),color-mix(in srgb,var(--accent2) 10%,transparent)),rgba(255,255,255,.055);box-shadow:0 14px 34px rgba(0,0,0,.14),var(--glow)}.agent-model-option .route-icon{display:grid;place-items:center;width:31px;height:31px;border-radius:10px;background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;font-size:13px;font-weight:950}.agent-model-option b{display:block;font-size:12px;line-height:1.2}.agent-model-option p{margin-top:4px;color:var(--dim);font-size:10px;line-height:1.35}.agent-route-panels{display:grid;gap:10px}.agent-route-panel{display:none;border:1px solid var(--line);border-radius:12px;background:rgba(0,0,0,.14);padding:12px}.agent-route-panel.active{display:block;animation:routePanelIn .18s ease both}.agent-route-panel h4{font-size:14px;line-height:1.2}.agent-route-panel p{margin-top:5px;color:var(--dim);font-size:11px;line-height:1.45}.agent-route-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.agent-route-actions .btn{flex:1 1 170px}.model-provider-form{margin-top:0}.chatgpt-command{display:flex;align-items:flex-start;justify-content:flex-start;flex-direction:column;gap:8px;border:1px solid var(--line);border-radius:8px;background:rgba(0,0,0,.18);padding:9px;margin-top:8px}.chatgpt-command code,.chatgpt-command>span{display:block;width:100%;height:auto;font-size:11px;line-height:1.4;font-weight:800;color:var(--text);word-break:normal;overflow-wrap:anywhere}.chatgpt-command .mode-actions{width:100%;flex-wrap:wrap}.chatgpt-command .mode-actions .btn{flex:1 1 150px}.chatgpt-connect-result{margin-top:8px;border:1px solid color-mix(in srgb,var(--accent) 24%,var(--line));border-radius:8px;background:rgba(255,255,255,.055);padding:10px}.chatgpt-connect-result b{display:block;font-size:12px;line-height:1.25}.chatgpt-connect-result p,.chatgpt-connect-result a{font-size:11px;line-height:1.45}.chatgpt-connect-result a{color:var(--accent);font-weight:900}.chatgpt-terminal-output{max-height:150px;overflow:auto;margin-top:8px;border:1px solid var(--line);border-radius:7px;background:rgba(0,0,0,.22);padding:8px;color:var(--dim);font-size:10px;line-height:1.4;white-space:pre-wrap}.chatgpt-foot{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:10px}.chatgpt-foot p{font-size:10px;color:var(--dim);line-height:1.45}.chatgpt-connect-card.ready{border-color:rgba(85,212,122,.3);background:linear-gradient(135deg,rgba(85,212,122,.12),rgba(99,168,255,.06),rgba(255,255,255,.04))}@keyframes softSweep{0%,62%{transform:translateX(-120%)}82%,100%{transform:translateX(120%)}}@keyframes routePanelIn{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:translateY(0)}}
.chatgpt-connect-result.has-device-code{border-color:color-mix(in srgb,var(--warning) 60%,var(--accent));background:linear-gradient(135deg,rgba(244,183,64,.18),color-mix(in srgb,var(--accent) 12%,transparent),rgba(0,0,0,.22));box-shadow:0 18px 48px rgba(0,0,0,.24),0 0 0 1px rgba(244,183,64,.18) inset}.chatgpt-device-code{display:grid;grid-template-columns:1fr auto;gap:14px;align-items:center;margin:12px 0 4px;border:2px solid color-mix(in srgb,var(--warning) 64%,var(--accent));border-radius:16px;background:linear-gradient(135deg,rgba(244,183,64,.22),color-mix(in srgb,var(--accent) 18%,transparent),rgba(0,0,0,.28));padding:16px;box-shadow:0 20px 54px rgba(0,0,0,.24),0 0 34px color-mix(in srgb,var(--warning) 18%,transparent);min-width:0}.chatgpt-device-code span{display:block;color:var(--text);font-size:12px;font-weight:950;text-transform:uppercase;letter-spacing:.02em}.chatgpt-device-code small{display:block;margin-top:8px;color:var(--dim);font-size:12px;line-height:1.35;font-weight:700;text-transform:none}.chatgpt-device-code strong{display:block;margin-top:7px;font-size:clamp(30px,6vw,54px);line-height:1;letter-spacing:.04em;color:#fff;font-weight:950;text-shadow:0 4px 24px rgba(0,0,0,.34);overflow-wrap:anywhere;word-break:break-all;max-width:100%}.chatgpt-device-code .btn{white-space:nowrap;min-height:46px;padding:12px 16px;font-size:12px}.chatgpt-device-actions{display:grid;gap:8px;min-width:190px}.chatgpt-retry-login{display:flex;width:100%;align-items:center;justify-content:center;margin-top:12px;min-height:52px;padding:14px 18px;font-size:13px}
@media(max-width:980px){.agent-model-picker{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:780px){.chatgpt-connect-head,.chatgpt-foot,.chatgpt-command{align-items:flex-start;flex-direction:column}.model-route-grid,.agent-model-picker{grid-template-columns:1fr}.chatgpt-command .btn,.chatgpt-foot .btn,.agent-route-actions .btn{width:100%}.chatgpt-device-code{grid-template-columns:1fr}.chatgpt-device-code .btn{width:100%}}
body .onboarding-flow input:not([type="checkbox"]):not([type="radio"]):not([type="range"]),body .onboarding-flow select,body .onboarding-flow textarea{background:linear-gradient(180deg,#171420,#100f18);border-color:rgba(199,178,255,.26);color:#f7f3ff;caret-color:#ff6bd6;box-shadow:inset 0 1px 0 rgba(255,255,255,.055),0 0 0 1px rgba(0,0,0,.12)}
body .onboarding-flow input:not([type="checkbox"]):not([type="radio"]):not([type="range"])::placeholder,body .onboarding-flow textarea::placeholder{color:rgba(221,212,240,.52);opacity:1}
body .onboarding-flow input:not([type="checkbox"]):not([type="radio"]):not([type="range"]):focus,body .onboarding-flow select:focus,body .onboarding-flow textarea:focus{outline:none;background:#12101a;border-color:rgba(167,124,255,.72);box-shadow:0 0 0 3px rgba(167,124,255,.15),inset 0 1px 0 rgba(255,255,255,.06)}
body .onboarding-flow input:-webkit-autofill,body .onboarding-flow textarea:-webkit-autofill,body .onboarding-flow select:-webkit-autofill{-webkit-text-fill-color:#f7f3ff;box-shadow:0 0 0 1000px #15131d inset;border-color:rgba(199,178,255,.3)}
body .onboarding-flow select option{background:#15131d;color:#f7f3ff}
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
<section class="update-banner hidden" id="update-banner"></section>
<section class="deferred-onboarding-banner hidden" id="deferred-onboarding-banner"></section>
<main>
<aside class="col brief-zone">
<button class="zone-label" id="toggle-left-panel" type="button" onclick="togglePanel('left')"><span data-i18n="zone_brief">Daily intelligence</span><small class="zone-badge" id="daily-brief-badge" data-i18n="new_brief">New</small><i class="panel-caret" aria-hidden="true"></i></button>
<section class="section"><div class="head"><span>01</span><b id="business-profile-title">Perfil del negocio</b><button class="btn ask-btn" onclick="openChat(businessProfileChatPrompt())" data-i18n="ask_agent">Ask agent</button></div><div class="body" id="business-profile-panel"></div></section>
<section class="section"><div class="head"><span>02</span><b data-i18n="daily_brief">Daily Brief</b><button class="btn ask-btn" onclick="openChat(t('draft_catchup'))" data-i18n="ask_agent">Ask agent</button><button class="btn" onclick="runAgent()" data-i18n="run">Run</button></div><div class="body" id="brief"></div></section>
<section class="section"><div class="head"><span>03</span><b data-i18n="fatigue_monitor">Fatigue Monitor</b><button class="btn ask-btn" onclick="openChat(t('draft_fatigue'))" data-i18n="ask_agent">Ask agent</button></div><div class="body" id="fatigue"></div></section>
</aside>
<section class="col work-zone">
<div class="zone-label" data-i18n="zone_work">Campaign workspace</div>
<div id="tab-overview">
<div class="page-title"><div><h2 data-i18n="control_center">Control Center</h2><p data-i18n="control_subtitle">Daily decisions, risk signals, and ad account health in one place.</p></div><div class="dashboard-toolbar"><div class="view-switcher" role="group" aria-label="Vistas del dashboard"><button class="view-chip active" type="button" data-view="control" onclick="setDashboardView('control')">Control</button><button class="view-chip" type="button" data-view="timeline" onclick="setDashboardView('timeline')">Timeline</button><button class="view-chip" type="button" data-view="analytics" onclick="setDashboardView('analytics')">Overview</button><button class="view-chip" type="button" data-view="idle" onclick="setDashboardView('idle')">Showcase</button></div><div class="theme-switcher" id="theme-toggle" role="group" aria-label="Temas del dashboard"><button class="theme-chip active" type="button" data-theme="aurora" onclick="setDashboardTheme('aurora')">Aurora</button><button class="theme-chip" type="button" data-theme="sapphire" onclick="setDashboardTheme('sapphire')">Sapphire</button><button class="theme-chip" type="button" data-theme="ember" onclick="setDashboardTheme('ember')">Ember</button></div><button class="btn ask-btn" onclick="openChat(t('draft_where_are_we'))" data-i18n="ask_manager">Ask manager</button><button class="btn primary hidden" id="real-data-refresh" onclick="refreshInsights()">Actualizar datos reales</button><div class="signal" id="data-source-signal">--</div><div class="signal" data-i18n="safe_mode">Safe mode active</div></div></div>
<div class="dashboard-view" id="view-control">
<div class="kpis" id="kpis"></div>
<div class="campaign-grid" id="campaigns"></div>
</div>
<div class="dashboard-view hidden" id="view-timeline"></div>
<div class="dashboard-view hidden" id="view-analytics"></div>
<div class="dashboard-view hidden" id="view-idle"></div>
</div>
<div id="tab-setup" class="hidden">
<section class="section"><div class="head"><span>03</span><b data-i18n="setup_status">Setup Status</b><button class="btn ask-btn" onclick="openChat(t('draft_setup'))" data-i18n="ask_agent">Ask agent</button><button class="btn" onclick="load()" data-i18n="refresh">Refresh</button></div><div class="body"><div id="mode-control"></div><div id="guardrails-panel"></div><div id="onboarding-wizard"></div><div id="license-panel"></div><div id="agency-panel"></div><div id="setup-config"></div><div id="chatgpt-panel"></div><div id="telegram-panel"></div><div id="local-network-panel"></div><div id="migration-panel"></div><div id="update-rollback-panel"></div><div id="cloud-access-panel"></div><div id="setup-summary"></div><div id="setup-sections"></div></div></section>
</div>
<div id="tab-creator" class="hidden">
<section class="section"><div class="head"><span>04</span><b data-i18n="campaign_creator">Campaign Creator</b></div><div class="body">
<section class="creator-hero"><span class="creative-kicker" data-i18n="creator_kicker">New campaign</span><h2 data-i18n="creator_title">Create a campaign</h2><p data-i18n="creator_body">Tell the agent what you sell, who should see it, and how much you can spend. It will organize the campaign and show it to you before anything can spend money.</p><div class="creator-hero-actions"><button class="btn primary" type="button" onclick="openChat(isEs()?'Quiero crear una campaña nueva. Hazme preguntas fáciles, una a la vez: qué vendo, a quién quiero llegar, cuánto puedo gastar al día, a qué página enviar a las personas y si quiero dejarla lista o activa después de aprobar. Si necesito imágenes o textos, guíame para prepararlos.':'I want to create a new campaign. Ask me simple questions one at a time: what I sell, who I want to reach, how much I can spend daily, where people should go, and whether it should remain ready or active after approval. If I need images or text, guide me through preparing them.')"><span data-i18n="creator_chat_cta">Create by talking to the agent</span></button></div></section>
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
<div class="targeting-intro"><div><b data-i18n="targeting_picker_title">Choose the audience with Meta options</b><p data-i18n="targeting_picker_body">Search locations and interests from Meta, or let the agent suggest the safest audience.</p></div><button class="btn ask-btn" type="button" onclick="openChat(isEs()?'Ayúdame a elegir quién debería ver esta campaña. Pregúntame qué vendo, dónde vendo y cuánto puedo gastar. Si ya me conocen, dime cómo aprovecharlo.':'Help me choose who should see this campaign. Ask what I sell, where I sell, and how much I can spend. If people already know my business, tell me how to use that.')"><span data-i18n="targeting_agent_cta">Ask the agent</span></button></div>
<div class="targeting-mode-grid"><button class="targeting-mode-card active" type="button" onclick="setTargetingMode('broad')"><b data-i18n="targeting_broad_title">Broad audience</b><span data-i18n="targeting_broad_body">Best default: age, location, creative and Meta learning.</span></button><button class="targeting-mode-card" type="button" onclick="setTargetingMode('guided')"><b data-i18n="targeting_guided_title">Guided interests</b><span data-i18n="targeting_guided_body">Use Meta interests as hints when the niche is clear.</span></button><button class="targeting-mode-card" type="button" onclick="openChat(isEs()?'Revisa si ya tengo información de personas que visitaron, escribieron o compraron. Si no, dime qué me falta para mostrar anuncios a personas parecidas.':'Check whether I already have information from people who visited, wrote, or bought. If not, tell me what I need to show ads to similar people.')"><b data-i18n="targeting_warm_title">People who know you / similar people</b><span data-i18n="targeting_warm_body">Only when visitor, page, Instagram or permitted customer data is ready.</span></button></div>
<div class="targeting-search-grid">
<div class="targeting-picker"><label data-i18n="locations_simple">Where those people live</label><div class="targeting-search-row"><input id="targeting-location-query" data-i18n-placeholder="locations_example" placeholder="Example: Colombia"><button class="btn" type="button" onclick="searchTargeting('location')" data-i18n="targeting_search">Search Meta</button></div><div id="targeting-location-results" class="targeting-results"></div><div id="targeting-location-selected" class="targeting-chips"></div></div>
<div class="targeting-picker"><label data-i18n="interests_simple">Things they may be interested in</label><div class="targeting-search-row"><input id="targeting-interest-query" data-i18n-placeholder="interests_example" placeholder="Example: online stores"><button class="btn" type="button" onclick="searchTargeting('interest')" data-i18n="targeting_search">Search Meta</button></div><div id="targeting-interest-results" class="targeting-results"></div><div id="targeting-interest-selected" class="targeting-chips"></div></div>
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
<section class="section"><div class="head"><span>05</span><b data-i18n="audience_builder">Audience Builder</b><button class="btn ask-btn" onclick="openChat(t('draft_audience'))" data-i18n="ask_agent">Ask agent</button></div><div class="body">
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
<div id="audience-result" style="margin-top:12px"></div>
</div></section>
</div>
<div id="tab-creatives" class="hidden">
<section class="creative-studio-hero"><div class="creative-studio-copy"><span class="creative-kicker" id="creative-studio-kicker">Ideas para anuncios</span><h2 id="creative-studio-title">Crea tus anuncios</h2><p id="creative-studio-description"></p><div class="creative-studio-actions"><button class="btn primary" id="creative-agent-cta" onclick="openChat(isEs()?'Quiero crear imágenes y textos para un anuncio. Puede ser para una promoción, una campaña nueva o para mejorar un anuncio que ya funciona. Ayúdame a definir la idea creativa.':'I want to create images and text for an ad. It may be for a promotion, a new campaign, or to improve an ad that already works. Help me define the creative idea.')"></button><button class="btn" id="creative-refresh-cta" onclick="generateRefresh()"></button></div></div><div class="creative-studio-pulse" id="creative-studio-pulse"></div></section>
<div class="creative-studio-layout">
<aside class="creative-studio-memory"><div id="brand-guides-panel"></div></aside>
<section class="creative-gallery-panel"><div class="creative-gallery-head"><div><span class="creative-kicker" id="creative-library-kicker"></span><h3 id="creative-library-title"></h3></div><button class="btn ask-btn" onclick="openChat(isEs()?'Revisa mis ideas de anuncios y dime cuál probarías primero y por qué.':'Review my current ad ideas and tell me which one you would test first and why.')"><span data-i18n="ask_agent">Ask agent</span></button></div><div id="creative-list"></div></section>
</div>
<section class="creative-approval-panel"><div class="creative-gallery-head"><div><span class="creative-kicker" id="creative-upload-kicker"></span><h3 id="creative-upload-title"></h3></div></div><div id="upload-list"></div></section>
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
<section class="brand-memory-overlay" id="brand-memory-overlay" aria-modal="true" role="dialog" aria-labelledby="brand-memory-title">
<div class="brand-memory-modal">
<header class="brand-memory-head"><div><span class="creative-kicker" id="brand-memory-kicker">Lo que sabe el agente</span><h2 id="brand-memory-title">Marca, productos y anuncios</h2><p id="brand-memory-subtitle"></p></div><button class="btn brand-memory-close" type="button" onclick="closeBrandMemory()" aria-label="Cerrar">×</button></header>
<div class="brand-memory-workspace"><nav class="brand-memory-nav" id="brand-memory-nav"></nav><div class="brand-memory-editor" id="brand-memory-editor"></div></div>
</div>
</section>
<div class="floating-tip" id="floating-tip" role="tooltip"></div>
<form class="agent-chat-bar" id="agent-chat-bar">
<div class="agent-bar-mark">AI</div>
<button class="agent-bar-expand" type="button" onclick="openChat()" aria-label="Abrir conversación completa" title="Abrir conversación completa">⌃</button>
<textarea id="agent-bar-input" rows="1" data-i18n-placeholder="chat_fab"></textarea>
<button class="agent-bar-send" type="submit" aria-label="Send">↑</button>
</form>
<section class="chat-panel" id="chat-panel" aria-live="polite">
<div class="chat-head"><div class="chat-avatar">AI</div><div class="chat-title"><b data-i18n="chat_title">Meta Ads Manager</b><span data-i18n="chat_subtitle">Ask for catchups, actions, or explanations.</span></div><button class="btn" onclick="newChatConversation()" data-i18n="new_chat">New chat</button><button class="btn chat-close" onclick="closeChat()" aria-label="Cerrar conversación" title="Cerrar conversación">×</button></div>
<div class="chat-log" id="chat-log"></div>
<div class="chat-quick"><button class="chip" onclick="openChat(t('draft_where_are_we'))" data-i18n="quick_status">Where are we?</button><button class="chip" onclick="openChat(t('draft_budget'))" data-i18n="quick_budget">Review budget</button><button class="chip" onclick="openChat(t('draft_fatigue'))" data-i18n="quick_fatigue">Check fatigue</button></div>
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
<script>
let state=null;
let chatHistory=[];
let chatHydrated=false;
let onboardingFlowStep=0;
let onboardingFlowTouched=false;
let businessContextQuestionIndex=0;
let destinationAutoDiscoveryKey='';
let updateCheckStarted=false;
let updateInfo=null;
const fmtMoney=n=>'$'+Number(n||0).toLocaleString(undefined,{maximumFractionDigits:2});
const fmtPct=n=>Number(n||0).toFixed(2)+'%';
const qs=s=>document.querySelector(s);
const urlParams=new URLSearchParams(window.location.search);
function isLocalWorkbenchHost(host){
 return host==='127.0.0.1'||host==='localhost'||host==='0.0.0.0'||host.startsWith('192.168.')||host.startsWith('10.')||/^172\.(1[6-9]|2\d|3[0-1])\./.test(host);
}
function readUiWorkbenchPreview(){
 const forced=urlParams.get('ui_preview');
 if(forced==='1')return true;
 if(forced==='0'||urlParams.get('full_setup')==='1')return false;
 const saved=localStorage.getItem('dashboardUiPreview');
 if(saved==='1')return true;
 return false;
}
let lang=localStorage.getItem('dashboardLang')||'es';
let dashboardView=localStorage.getItem('dashboardView')||'control';
function normalizeDashboardTheme(value){
 if(value==='light')return 'aurora';
 if(value==='dark')return 'sapphire';
 return value==='sapphire'||value==='ember'?value:'aurora';
}
let dashboardTheme=normalizeDashboardTheme(localStorage.getItem('dashboardTheme')||'aurora');
let uiWorkbenchPreview=readUiWorkbenchPreview();
const copy={
 en:{
	  brand_subtitle:'Self-hosted local/VPS operator',zone_brief:'Profile and daily read',zone_work:'Campaign workspace',zone_actions:'Approvals and activity',control_center:'Control Center',control_subtitle:'Daily decisions, risk signals, and ad account health in one place.',safe_mode:'Safe mode active',ask_agent:'Ask agent',ask_manager:'Ask manager',chat_fab:'Talk to agent',chat_title:'Meta Ads Manager',chat_subtitle:'Ask for catchups, actions, or explanations.',new_chat:'New chat',quick_status:'Where are we?',quick_budget:'Review budget',quick_fatigue:'Check fatigue',send:'Send',usage_guide:'Guide',tab_overview:'Overview',tab_setup:'Setup',tab_creator:'Create campaign',tab_audiences:'Audiences',tab_creatives:'Creatives',tab_reports:'Reports',updated:'Updated',new_brief:'New',daily_brief:'Daily Brief',run:'Refresh',fatigue_monitor:'Fatigue Monitor',setup_status:'Setup Status',setup_form_title:'Buyer setup fields',setup_form_body:'Save the few account details the assistant needs. No technical file editing here.',license_panel_title:'License unlock',license_panel_body:'Activate the license before live setup. If cloud validation is configured, this device checks your seller domain and caches a safe unlock.',license_active:'Active',license_missing:'Missing',license_invalid:'Needs attention',license_cloud:'Cloud validation',license_local:'Local license',license_activate:'Activate license',license_key:'License key',buyer_email:'Buyer email',ad_account_id:'Ad account',page_id:'Facebook page',instagram_actor_id:'Instagram profile',default_adset_id:'Advanced field',landing_url:'Website link',save_setup:'Save',refresh:'Refresh',campaign_creator:'Create a campaign',creator_kicker:'New campaign',creator_title:'Create a campaign',creator_body:'Tell the agent what you sell, who should see it, and how much you can spend. It will organize the campaign and show it to you before anything can spend money.',creator_chat_cta:'Create by talking to the agent',paused_draft_title:'You decide before money is spent',paused_draft_body:'The agent prepares the campaign and asks for your approval. If you choose to leave it active, it can start spending only after you approve it.',creator_manual_title:'I prefer to enter the details myself',creator_manual_help:'Optional: the agent can ask you these questions in chat.',creator_basic:'What will you advertise?',campaign_name_simple:'Name for this campaign',campaign_name_example:'Example: June promotion',campaign_goal_simple:'What should people do?',goal_purchases:'Buy',goal_contacts:'Leave their details',goal_action:'Take an action on your website',landing_url_simple:'Page people will visit',landing_url_example:'https://your-page.com',primary_text_simple:'Message people will read',primary_text_example:'Example: Discover how this offer can help you today.',headline_simple:'Short title',headline_example:'Example: See the offer',image_simple:'Image already prepared, if you have one',image_path_example:'Optional: image file path',creator_people_budget:'Who will see it and how much can it spend?',daily_budget_simple:'Maximum to spend each day',total_budget_simple:'Maximum to spend in total',locations_simple:'Where those people live',locations_example:'Example: Colombia, Mexico, or Miami',interests_simple:'Things they may be interested in',interests_example:'Example: online stores, beauty, education',age_min_simple:'Youngest age',age_max_simple:'Oldest age',creator_decision:'How should it be prepared?',creative_variations_simple:'How many ideas to compare?',compare_options_simple:'Compare those ideas?',compare_yes:'Yes, compare them',compare_no:'No, use one idea',after_approval_simple:'After you approve it',active_after_approval:'Start showing the ads and spending the chosen budget',ready_not_spending:'Leave it ready without spending',confirm_active_spend:'Only if I choose to turn it on: I understand that after approving, this campaign may start spending my chosen budget.',creator_meta_optional:'Only if you already know this Meta detail',pixel_optional:'Meta tracking number (Pixel ID), optional',creator_review_notice:'Nothing will be created in your Meta account until you review and approve this request.',audience_builder:'Audience Builder',what_sell:'What do you sell?',who_buys:'Who buys today?',audience_product_example:'Example: an online course or beauty product',audience_buyer_example:'Example: people who want to sell more',audience_locations_example:'Example: Colombia or Mexico',audience_interests_example:'Example: beauty, education, local stores',audience_data_example:'Example: people who messaged on Instagram or buyers',age_range:'Age range',budget_level:'Budget level',budget_small:'Small',budget_medium:'Medium',budget_large:'Large',data_sources:'Data sources',consent_upload:'I have consent to use customer emails/phones if I upload them later.',notes:'Notes',optional:'Optional',build_audience:'Build Audience Strategy',lookalike_status:'Lookalike status',recommended_audiences:'Recommended audiences',next_steps:'Next steps',name:'Name',objective:'Objective',daily_budget:'Daily Budget',total_budget:'Total Budget',locations:'Locations',interests:'Interests',age_min:'Age Min',age_max:'Age Max',creative_variations:'Creative Variations',ab_test:'A/B Test',enabled:'Enabled',disabled:'Disabled',stage_campaign:'Send for my approval',creative_refresh:'Creative Refresh',generate_drafts:'Generate Drafts',upload_payloads:'Upload Payloads',campaign_comparison:'Campaign Comparison',export_csv:'Export CSV',campaign:'Campaign',status:'Status',budget_optimizer:'Budget Optimizer',now:'Now',rec:'Rec',pending_approvals:'Pending Approvals',action_log:'Action Log',
  targeting_picker_title:'Choose the audience with Meta options',targeting_picker_body:'Search locations and interests from Meta, or let the agent suggest the safest audience.',targeting_agent_cta:'Ask the agent',targeting_broad_title:'Broad audience',targeting_broad_body:'Best default: age, location, creative and Meta learning.',targeting_guided_title:'Guided interests',targeting_guided_body:'Use Meta interests as hints when the niche is clear.',targeting_warm_title:'Retargeting / lookalike',targeting_warm_body:'Only when pixel, page, Instagram or customer data is ready.',targeting_search:'Search Meta',targeting_manual_fallback:'If Meta search is not available',targeting_no_results:'No Meta options found. Try another word.',targeting_need_query:'Write what you want to search first.',
  spend:'Spend',revenue:'Revenue',conversions:'Conversions',active_budget:'Active Budget',active_daily_budget:'Active daily budget',roas:'ROAS',cpa:'CPA',ctr:'CTR',cpc:'CPC',frequency:'Frequency',mode:'Mode',ok:'OK',warnings:'Warnings',blocked:'Blocked',live_ready:'Live Ready',
  spend_tip:'How much money has been spent on ads in this period.',revenue_tip:'How much sales value the ads are estimated to have produced.',conversions_tip:'How many desired actions happened, such as purchases, leads, or signups.',active_budget_tip:'The total daily budget still running across active campaigns.',active_daily_budget_tip:'The total daily ad budget currently running across active campaigns.',daily_budget_tip:'How much the campaign is allowed to spend per day.',roas_tip:'Return on ad spend. If ROAS is 3x, every $1 in ads brought about $3 back.',cpa_tip:'Cost per acquisition. This is roughly what you paid to get one conversion.',ctr_tip:'Click-through rate. The percent of people who saw the ad and clicked it.',cpc_tip:'Cost per click. The average amount paid for one click.',frequency_tip:'How many times the average person has seen the ad. High frequency can mean people are getting tired of it.',mode_tip:'The current control level. Supervised means real data is read, but changes wait for approval; autopilot can act inside your rules.',ok_tip:'Items already configured correctly.',warnings_tip:'Items that are not blocking the demo, but should be reviewed before going live.',blocked_tip:'Items that must be fixed before the full live workflow can run.',live_ready_tip:'Whether the install has the key pieces needed before live Meta Ads actions are allowed.',
  no_fatigue:'No fatigue triggers right now.',no_pending:'No pending approvals.',no_actions:'No actions logged yet.',no_creatives:'No creative refresh drafts yet.',no_uploads:'No upload payloads staged yet.',request:'Request',apply:'Apply',approve:'Approve',stage_v1_upload:'Stage v1 Upload',missing:'Missing',variants:'variants',increase_budget:'Increase budget',adjust_budget:'Adjust budget',refresh_creative:'Refresh creative',pause:'Pause',resume:'Resume',details:'Details',
  q_track:'Am I on track?',q_running:"What's running?",q_performance:"How's performance?",q_winners:"Who's winning or losing?",q_fatigue:'Any fatigue?',
	  live_ready_yes:'Yes',live_ready_no:'No',check:'Check',draft_where_are_we:'Give me a business catch-up: where are we today, what should I watch, and what would you do next?',draft_catchup:'Explain today’s daily brief like my Meta Ads manager. What matters most?',draft_fatigue:'Review fatigue risk. Which ads need new creative and why?',draft_budget:'Review the budget optimizer. Which recommendations are safe and which need caution?',draft_setup:'Review setup status. What blocks us from going live safely?',draft_audience:'Help me choose targeting. Ask me only what is missing, then recommend broad, interest, retargeting, and lookalike options safely.',chat_welcome:'Hi, I’m your Meta Ads manager. Ask me for a catch-up, a decision, or help taking an action.',chat_summary:'Here is the catch-up: account ROAS is {roas}x, CPA is {cpa}, active budget is {budget}, and {pending} approval(s) are pending. The safest next step is to review budget recommendations and fatigue before going live.',chat_budget:'Budget view: compare current vs suggested budgets. For winning campaigns, scale carefully; for weak campaigns, fix creative or pause before adding spend.',chat_fatigue:'Fatigue view: watch frequency, CTR drops, and rising CPC. If fatigue is present, generate creative refresh drafts before increasing budget.',chat_setup:'Setup view: check blocked items first. Live actions stay protected until credentials, destination IDs, and the live-action switch are ready.',chat_action_hint:'I can open the right workflow from here. For live account changes, the approval queue and dashboard password still protect the account.',toast_resume:'Resume staged for approval',toast_action:'Action complete',toast_budget:'Budget action recorded',toast_daily:'Daily agent report generated',toast_export:'CSV exported: ',toast_approval:'Approval executed',toast_refresh:'Creative refresh draft generated',toast_upload:'Upload payload staged',toast_audience:'Audience strategy generated',toast_setup_saved:'Setup fields saved',toast_license:'License checked',toast_details:'Campaign details visible on this card.',prompt_budget:'New daily budget',unlock_title:'Unlock dashboard',unlock_body:'Enter the password for this dashboard to continue.',unlock_create_title:'Create your password',unlock_create_body:'This is your private password for this dashboard on this computer or server. You choose it now; we do not send one to you.',dashboard_password:'Dashboard password',dashboard_password_confirm:'Repeat password',remember_device:'Remember this device',unlock_button:'Unlock dashboard',unlock_create_button:'Save my password',unlock_needed:'Enter the password for this dashboard to continue.',unlock_create_needed:'Create a password to protect this dashboard before continuing.',unlock_failed:'That password did not unlock the dashboard. Try again.',dashboard_password_short:'Use at least 8 characters.',dashboard_password_mismatch:'Passwords do not match.',copy_command:'Copy',copied:'Copied'
 },
 es:{
	  brand_subtitle:'Operador local/VPS para Meta Ads',zone_brief:'Perfil y lectura',zone_work:'Área de campañas',zone_actions:'Aprobaciones y actividad',control_center:'Centro de control',control_subtitle:'Decisiones diarias, señales de riesgo y salud de la cuenta en un solo lugar.',safe_mode:'Modo seguro activo',ask_agent:'Preguntar',ask_manager:'Hablar con el agente',chat_fab:'Hablar con el agente',chat_title:'Manager de Meta Ads',chat_subtitle:'Pide resumen, decisiones o acciones.',new_chat:'Nuevo chat',quick_status:'¿Dónde estamos?',quick_budget:'Revisar presupuesto',quick_fatigue:'Ver cansancio',send:'Enviar',usage_guide:'Guía',tab_overview:'Resumen',tab_setup:'Configuración',tab_creator:'Crear campaña',tab_audiences:'Audiencias',tab_creatives:'Creativos',tab_reports:'Reportes',updated:'Actualizado',new_brief:'Nuevo',daily_brief:'Resumen diario',run:'Actualizar',fatigue_monitor:'Cansancio de anuncios',setup_status:'Configuración y seguridad',setup_form_title:'Datos importantes guardados',setup_form_body:'Aquí puedes cambiar licencia, cuenta, página y web. Normalmente esto ya queda listo en la configuración inicial. Si no sabes qué poner, pregúntale al agente.',license_panel_title:'Activación de licencia',license_panel_body:'Activa el código de compra para usar funciones reales. Este equipo confirma tu licencia con nuestro servidor y guarda permiso temporal para no pedirlo todo el tiempo.',license_active:'Activa',license_missing:'Falta',license_invalid:'Revisar',license_cloud:'Confirmada online',license_local:'Licencia local',license_activate:'Activar licencia',license_key:'Licencia',buyer_email:'Email del comprador',ad_account_id:'Cuenta publicitaria',page_id:'Página de Facebook',instagram_actor_id:'Perfil de Instagram',default_adset_id:'Campo avanzado',landing_url:'Link de tu web',save_setup:'Guardar',refresh:'Actualizar',campaign_creator:'Crear una campaña',creator_kicker:'Nueva campaña',creator_title:'Crea una campaña',creator_body:'Cuéntale al agente qué vendes, quién debe verlo y cuánto puedes gastar. Él organizará la campaña y te la mostrará antes de que pueda gastar dinero.',creator_chat_cta:'Crear hablando con el agente',paused_draft_title:'Tú decides antes de gastar dinero',paused_draft_body:'El agente prepara la campaña y te pide aprobación. Si decides dejarla activa, solo podrá empezar a gastar después de que la apruebes.',creator_manual_title:'Prefiero escribir los datos yo',creator_manual_help:'Opcional: el agente puede preguntarte todo esto en el chat.',creator_basic:'Qué vas a anunciar',campaign_name_simple:'Nombre para esta campaña',campaign_name_example:'Ej: Promo de junio',campaign_goal_simple:'Qué quieres que haga la persona',goal_purchases:'Comprar',goal_contacts:'Dejar sus datos',goal_action:'Hacer una acción en tu página',landing_url_simple:'Página que visitarán',landing_url_example:'https://tu-pagina.com',primary_text_simple:'Mensaje que leerán',primary_text_example:'Ej: Descubre cómo esta oferta puede ayudarte hoy.',headline_simple:'Título corto',headline_example:'Ej: Mira la oferta',image_simple:'Imagen ya preparada, si tienes una',image_path_example:'Opcional: ruta del archivo de imagen',creator_people_budget:'Quién lo verá y cuánto puede gastar',daily_budget_simple:'Máximo que puede gastar al día',total_budget_simple:'Máximo que puede gastar en total',locations_simple:'Dónde viven esas personas',locations_example:'Ej: Colombia, México o Miami',interests_simple:'Qué cosas podrían interesarles',interests_example:'Ej: tiendas online, belleza, educación',age_min_simple:'Edad más joven',age_max_simple:'Edad mayor',creator_decision:'Cómo quieres dejarla preparada',creative_variations_simple:'Cuántas ideas quieres comparar',compare_options_simple:'Comparar esas ideas',compare_yes:'Sí, compararlas',compare_no:'No, usar una sola idea',after_approval_simple:'Después de que la apruebes',active_after_approval:'Empezar a mostrar anuncios y gastar el presupuesto elegido',ready_not_spending:'Dejarla lista sin gastar',confirm_active_spend:'Marcar solo si elegiste empezar a mostrar anuncios: entiendo que, después de aprobar, esta campaña podrá gastar el presupuesto que elegí.',creator_meta_optional:'Solo si ya conoces este dato de Meta',pixel_optional:'Número de seguimiento de Meta (Pixel ID), opcional',creator_review_notice:'Nada se creará en tu cuenta de Meta hasta que revises y apruebes esta solicitud.',audience_builder:'Elegir público',what_sell:'¿Qué vendes?',who_buys:'¿Quién compra hoy?',audience_product_example:'Ej: un curso o un producto de belleza',audience_buyer_example:'Ej: personas que quieren vender más',audience_locations_example:'Ej: Colombia o México',audience_interests_example:'Ej: belleza, educación o negocios locales',audience_data_example:'Ej: personas que escribieron por Instagram o compradores',age_range:'Edad aproximada',budget_level:'Tamaño del presupuesto',budget_small:'Pequeño',budget_medium:'Mediano',budget_large:'Grande',data_sources:'Datos que ya tienes',consent_upload:'Tengo permiso para usar emails/teléfonos de clientes si los subo después.',notes:'Notas',optional:'Opcional',build_audience:'Crear recomendación de público',lookalike_status:'Público parecido',recommended_audiences:'A quién mostrar anuncios',next_steps:'Siguientes pasos',name:'Nombre',objective:'Objetivo',daily_budget:'Presupuesto diario',total_budget:'Presupuesto total',locations:'Países/ubicaciones',interests:'Intereses',age_min:'Edad mínima',age_max:'Edad máxima',creative_variations:'Opciones de anuncios',ab_test:'Comparar ideas',enabled:'Activada',disabled:'Desactivada',stage_campaign:'Enviar para mi aprobación',creative_refresh:'Crear ideas nuevas',generate_drafts:'Crear ideas',upload_payloads:'Anuncios listos para revisar',campaign_comparison:'Comparación de campañas',export_csv:'Descargar reporte',campaign:'Campaña',status:'Estado',budget_optimizer:'Qué hacer con el presupuesto',now:'Actual',rec:'Sugerido',pending_approvals:'Decisiones por aprobar',action_log:'Lo que hizo el agente',
  targeting_picker_title:'Elige público con opciones de Meta',targeting_picker_body:'Busca países, ciudades o intereses reales de Meta. Si no sabes qué elegir, pídeselo al agente.',targeting_agent_cta:'Preguntar al agente',targeting_broad_title:'Público amplio',targeting_broad_body:'Buen punto de partida: país, edad y buenos anuncios. Meta aprende con señales.',targeting_guided_title:'Intereses simples',targeting_guided_body:'Úsalos como pistas cuando sabes qué temas le importan a tu cliente.',targeting_warm_title:'Personas que ya te conocen / parecidos',targeting_warm_body:'Solo cuando ya tienes visitas, Instagram activo o clientes con permiso.',targeting_search:'Buscar en Meta',targeting_manual_fallback:'Solo si el buscador no funciona',targeting_no_results:'No encontré opciones en Meta. Prueba otra palabra.',targeting_need_query:'Escribe primero qué quieres buscar.',
  spend:'Gasto',revenue:'Ingresos',conversions:'Conversiones',active_budget:'Presupuesto activo',active_daily_budget:'Presupuesto diario activo',roas:'ROAS',cpa:'CPA',ctr:'CTR',cpc:'CPC',frequency:'Frecuencia',mode:'Modo',ok:'Listo',warnings:'Revisar',blocked:'Falta arreglar',live_ready:'Meta listo?',
  spend_tip:'Dinero que ya se gastó en anuncios.',revenue_tip:'Ventas o valor que los anuncios parecen haber producido.',conversions_tip:'Acciones importantes: compras, formularios, registros u otro objetivo.',active_budget_tip:'Dinero máximo por día que sigue encendido en campañas activas.',active_daily_budget_tip:'Dinero máximo por día que puede gastarse ahora.',daily_budget_tip:'Máximo que una campaña puede gastar por día.',roas_tip:'Cuánto vuelve por cada $1 gastado. ROAS 3x significa que $1 trajo aprox. $3.',cpa_tip:'Cuánto cuesta conseguir una compra, lead o acción importante.',ctr_tip:'De cada 100 personas que ven el anuncio, cuántas hacen clic.',cpc_tip:'Cuánto pagas por cada clic.',frequency_tip:'Cuántas veces ve una persona el mismo anuncio. Si sube mucho, puede cansarse.',mode_tip:'Con supervisión: tú apruebas. Piloto automático: el agente puede actuar solo dentro de tus reglas.',ok_tip:'Esto ya está bien.',warnings_tip:'No es urgente, pero conviene revisarlo.',blocked_tip:'Esto falta antes de usar todo el producto.',live_ready_tip:'Dice si ya puedes permitir acciones reales en Meta Ads.',
  no_fatigue:'No hay señales de cansancio de anuncios por ahora.',no_pending:'No hay aprobaciones pendientes.',no_actions:'Todavía no hay acciones registradas.',no_creatives:'Todavía no hay ideas de anuncios.',no_uploads:'Todavía no hay imágenes preparadas para publicar.',request:'Solicitar',apply:'Aplicar',approve:'Aprobar',stage_v1_upload:'Preparar para publicar',missing:'Falta',variants:'opciones',increase_budget:'Subir presupuesto',adjust_budget:'Ajustar presupuesto',refresh_creative:'Probar imagen nueva',pause:'Pausar',resume:'Reactivar',details:'Detalles',
  q_track:'¿Voy bien?',q_running:'¿Qué está corriendo?',q_performance:'¿Cómo va el rendimiento?',q_winners:'¿Qué gana y qué pierde?',q_fatigue:'¿Se está cansando algún anuncio?',
	  live_ready_yes:'Sí',live_ready_no:'No',check:'Revisar',draft_where_are_we:'Dame un resumen del negocio: dónde estamos hoy, qué debo vigilar y qué harías después.',draft_catchup:'Explícame el resumen diario como mi manager de Meta Ads. ¿Qué es lo más importante?',draft_fatigue:'Revisa el riesgo de cansancio del anuncio. ¿Qué anuncios necesitan una imagen o texto nuevo y por qué?',draft_budget:'Revisa el presupuesto. ¿Qué recomendaciones son seguras y cuáles requieren cuidado?',draft_setup:'Revisa el estado de configuración. ¿Qué nos falta para activar piloto automático con seguridad?',draft_audience:'Ayúdame a elegir a quién mostrar anuncios. Pregúntame solo lo que falte y dime si conviene llegar a personas nuevas, personas que ya me conocen o personas parecidas a mis clientes.',chat_welcome:'Hola, soy tu manager de Meta Ads. Pídeme un resumen, una decisión o ayuda para ejecutar una acción.',chat_summary:'Resumen: por cada $1 invertido regresan {roas}; conseguir una compra cuesta {cpa}; el presupuesto activo es {budget} y hay {pending} decisión(es) pendientes. El siguiente paso más seguro es revisar presupuesto y cansancio antes de aumentar gasto.',chat_budget:'Presupuesto: compara el presupuesto actual contra el sugerido. En campañas ganadoras, aumenta con cuidado; en campañas débiles, prueba otra imagen o texto o pausa antes de invertir más.',chat_fatigue:'Cansancio del anuncio: revisa si muchas personas ven el mismo anuncio, si bajan los clics o si cada clic cuesta más. Si pasa, crea nuevas imágenes o textos antes de subir presupuesto.',chat_setup:'Configuración: resuelve primero lo que falta. Las acciones reales requieren una aprobación exacta o piloto automático activo dentro de tus reglas.',chat_action_hint:'Puedo abrir el paso correcto desde aquí. Para cambios reales, tus decisiones y la contraseña del dashboard protegen la cuenta.',toast_resume:'Reactivación enviada a aprobación',toast_action:'Acción completada',toast_budget:'Acción de presupuesto registrada',toast_daily:'Resumen diario generado',toast_export:'Reporte descargado: ',toast_approval:'Aprobación ejecutada',toast_refresh:'Ideas de anuncio creadas',toast_upload:'Imagen preparada para revisar',toast_audience:'Recomendación de público creada',toast_setup_saved:'Configuración guardada',toast_license:'Licencia revisada',toast_details:'Los detalles clave están visibles en esta tarjeta.',prompt_budget:'Nuevo presupuesto diario',unlock_title:'Desbloquear dashboard',unlock_body:'Escribe la contraseña de este dashboard para continuar.',unlock_create_title:'Crea tu contraseña',unlock_create_body:'Esta será tu contraseña privada para proteger este dashboard en este equipo o servidor. La eliges tú ahora; nosotros no te enviamos una.',dashboard_password:'Contraseña del dashboard',dashboard_password_confirm:'Repetir contraseña',remember_device:'Recordar este dispositivo',unlock_button:'Desbloquear dashboard',unlock_create_button:'Guardar mi contraseña',unlock_needed:'Escribe la contraseña de este dashboard para continuar.',unlock_create_needed:'Crea una contraseña para proteger este dashboard antes de seguir.',unlock_failed:'Esa contraseña no desbloqueó el dashboard. Intenta de nuevo.',dashboard_password_short:'Usa al menos 8 caracteres.',dashboard_password_mismatch:'Las contraseñas no coinciden.',copy_command:'Copiar',copied:'Copiado'
 }
};
const labelKeys={Spend:'spend',Revenue:'revenue',Conversions:'conversions','Active Budget':'active_budget',ROAS:'roas',CPA:'cpa',CTR:'ctr',CPC:'cpc',Frequency:'frequency',frequency:'frequency',conversions:'conversions','Active daily budget':'active_daily_budget','active daily budget':'active_daily_budget','daily budget':'daily_budget',Mode:'mode',OK:'ok',Warnings:'warnings',Blocked:'blocked','Live Ready':'live_ready'};
const questionKeys={'Am I on track?':'q_track',"What's running?":'q_running',"How's performance?":'q_performance',"Who's winning/losing?":'q_winners',"Who's winning or losing?":'q_winners','Any fatigue?':'q_fatigue'};
const esText={
 Files:'Instalación',Runtime:'Funcionamiento',Security:'Protección','Meta Live Requirements':'Conexión con Meta','Creative Generation':'Imágenes de anuncios','Agent Chat':'Chat con el agente',Telegram:'Telegram','Upload Readiness':'Publicación de anuncios',Scheduler:'Lectura diaria automática',
 '.env config':'Llaves locales guardadas','ad-config.json':'Datos de anuncios guardados','Metrics cache':'Datos del dashboard','Dashboard script':'Pantalla del dashboard','Daily agent script':'Agente diario','Agent mode':'Nivel de control','Primary connector':'Conexión principal','social-cli installed':'Conexión con Meta instalada','social-cli onboarding':'Conexión con Meta iniciada','Latest daily report':'Última lectura diaria','Latest action log':'Última acción registrada','Dashboard bind host':'Dónde se abre el dashboard','Dashboard write token':'Contraseña del dashboard','Dashboard password':'Contraseña del dashboard','Token required for writes':'Contraseña requerida para acciones','Password required for actions':'Contraseña requerida para acciones','License key':'Licencia','Public dashboard opt-in':'Acceso público permitido','Live-action kill switch':'Permiso de piloto automático','.env permissions':'Protección de llaves','Dashboard data permissions':'Protección de datos del dashboard','Output permissions':'Protección de archivos creados','Logs permissions':'Protección de registros','Meta ad account':'Cuenta publicitaria de Meta','Direct Graph token':'Clave de acceso de Meta','Meta token':'Clave de acceso de Meta','Page ID':'Página de Facebook','Landing page URL':'Web de destino','Creative refresh enabled':'Ideas nuevas de anuncios activas','Creative image mode':'Modo de imágenes','Nano Banana / Gemini key':'Clave para crear imágenes','Codex CLI':'Codex para creativos','Codex creative bridge (optional local-agent access)':'Codex creativo opcional','Brand guide files':'Memoria de marca','Agent chat provider':'Motor del chat','Hermes runtime':'Hermes instalado','Hermes ChatGPT/Codex login':'ChatGPT/Codex conectado en Hermes','OpenAI-compatible model':'Modelo externo compatible','Agent chat model':'Modelo del chat','MiniMax fallback':'Plan B del chat','MiniMax API key':'Clave de MiniMax','Agent profile files':'Personalidad del agente','Telegram agent access':'Chat por Telegram','Telegram bot':'Bot de Telegram','Allowed Telegram chat':'Tu chat privado de Telegram','Upload staging index':'Anuncios preparados','Latest upload payload':'Última publicación preparada','Cron setup script':'Lectura diaria automática','VPS systemd setup script':'Servicio en servidor','Logs directory':'Registros del sistema',
 'No daily report yet.':'Todavía no hay lectura diaria.','No actions logged yet.':'Todavía no hay acciones registradas.','Run social setup or social onboard, then social auth login.':'Falta terminar la conexión con Meta. Sigue el paso de Meta en la configuración inicial.','Recommended: social setup':'Recomendado: seguir el paso de conexión con Meta','configured':'configurado','Configured inside Hermes':'Listo dentro de Hermes','No usado; el chat usa una API compatible OpenAI.':'No usado; el chat usa el modelo externo configurado.','Hermes not installed':'Hermes no está instalado','Hermes selected model':'Modelo elegido en Hermes','Optional fallback not configured':'Plan B opcional no configurado','Optional unless AGENT_CHAT_PROVIDER is minimax/openai_compatible/openai.':'Opcional si usas Hermes.','Missing AGENT_CHAT_API_KEY, AGENT_CHAT_BASE_URL, or AGENT_CHAT_MODEL':'Falta clave, URL o nombre del modelo externo.','Missing DASHBOARD_TOKEN':'Falta contraseña del dashboard','Missing DASHBOARD_PASSWORD':'Falta contraseña del dashboard','License key missing':'Falta la licencia','Invalid license format':'La licencia no se ve correcta','License checksum mismatch':'La licencia no pasó validación','License active':'Licencia activa','Cloud unlock active':'Licencia confirmada online','Cloud license active':'Licencia confirmada online','Offline license active; no license server configured':'Licencia local activa','Cloud unlock expired; grace period active':'Permiso guardado temporalmente activo','Could not validate the license online. Check internet access or contact support.':'No pudimos confirmar tu licencia. Revisa internet o contacta soporte.','License server unavailable; using the saved unlock on this device':'No pudimos contactar el servidor; usando permiso guardado en este equipo','Demo/internal license':'Licencia de prueba','Missing META_AD_ACCOUNT_ID':'Falta elegir cuenta publicitaria','Not configured; paste your Meta token in onboarding.':'Falta pegar tu clave de Meta en la configuración inicial.','Not configured; optional unless using graph_api connector.':'No configurado; normalmente puedes seguir.','Missing creative.destination.page_id':'Falta elegir página de Facebook','Missing creative.destination.url':'Falta guardar el link de tu web','Missing GEMINI_API_KEY':'Falta conectar el generador de imágenes','Missing MINIMAX_API_KEY; chat will use local fallback replies.':'Plan B de chat no configurado. Hermes sigue siendo el principal.','Set MINIMAX_API_KEY in .env for real agent conversation.':'Solo necesario si cambias el chat a MiniMax.','No creative drafts yet.':'Todavía no hay ideas de anuncios.','No upload payloads staged yet.':'Todavía no hay anuncios preparados para publicar.','None':'Ninguno','logs directory not created yet':'Todavía no hay carpeta de registros'
};
function t(key){return (copy[lang]&&copy[lang][key])||copy.en[key]||key}
function uiLang(){
 const selected=qs('#language-select')?.value;
 if(selected==='es'||selected==='en')return selected;
 const stored=localStorage.getItem('dashboardLang');
 if(stored==='es'||stored==='en')return stored;
 return lang==='en'?'en':'es';
}
function isEs(){return uiLang()==='es'}
function localText(value){if(lang!=='es')return value;let text=String(value??'');return esText[text]||text.replace(/^Missing: /,'Falta: ').replace('blocked / missing','bloqueado / faltan').replace('ready_for_approval','listo para aprobación').replace('dry-run','con supervisión').replace('True','Sí').replace('False','No')}
function actionName(value){const raw=String(value||'').replaceAll('_',' ');if(lang!=='es')return raw;return raw.replace('budget change','cambio de presupuesto').replace('resume campaign','reactivar campaña').replace('create campaign','crear campaña').replace('creative upload','subida creativa').replace('daily agent run','ejecución diaria del agente').replace('creative refresh','renovación creativa').replace('creative upload execute','ejecución de subida creativa').replace('creative upload stage','preparación de subida creativa')}
function actionDetail(a){const p=a.payload||{};const result=p.result||p.social_cli_result||{};const requested=p.name||p.campaign_name||p.campaign_id||p.path||'';const connector=p.connector||result.connector||(result.command?'social-cli':'local');const mode=p.mode||result.mode||state?.config?.mode||'';const executed=(p.executed!==undefined?p.executed:result.executed);const response=result.stderr||result.stdout||p.response_summary||'';const rows=[];if(requested)rows.push(`<strong>${lang==='es'?'Pedido':'Requested'}:</strong> ${requested}`);rows.push(`<strong>${lang==='es'?'Conector':'Connector'}:</strong> ${connector}`);if(mode)rows.push(`<strong>${lang==='es'?'Modo':'Mode'}:</strong> ${mode}`);if(executed!==undefined)rows.push(`<strong>${lang==='es'?'Ejecutado':'Executed'}:</strong> ${executed? (lang==='es'?'sí':'yes') : (lang==='es'?'no':'no')}`);if(response)rows.push(`<strong>${lang==='es'?'Respuesta':'Response'}:</strong> ${String(response).slice(0,180)}`);return rows.length?`<div class="action-detail">${rows.join('<br>')}</div>`:''}
function keyFor(label){return labelKeys[label]||label}
function tip(label){const key=keyFor(label);return `<span class="tip" tabindex="0" data-tip="${t(key+'_tip')}">${t(key)} <span class="help-dot">?</span></span>`}
function kpi(label,value){return `<div class="kpi aurora-card"><span class="starfield" aria-hidden="true"></span><div class="v">${value}</div><div class="l">${tip(label)}</div></div>`}
function metric(label,value){return `<div class="metric"><b>${value}</b><span>${tip(label)}</span></div>`}
function explainTerms(text){return String(text||'').replace(/\b(ROAS|CPA|CTR|CPC|Frequency|frequency|conversions|Conversions|Active daily budget|active daily budget|daily budget)\b/g,match=>tip(match))}
function briefAnswer(text){
 if(lang!=='es')return text;
 let answer=String(text||'')
  .replace(/^Spend:\s*/,'Gasto: ')
  .replace(/^Revenue:\s*/,'Ingresos: ')
  .replace(/^(\d+) active campaigns\.?$/,'$1 campañas activas.')
  .replace(/^(\d+) fatigue flag\(s\)\.?$/,'$1 señales de cansancio del anuncio.')
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
  .replace('No material fatigue triggers right now.','No hay señales importantes de cansancio por ahora.')
  .replace('No clear winner yet.','Todavía no hay una campaña claramente ganadora.');
 if(state?.metrics?.source==='demo'){
  answer=answer.replaceAll('Q2 Conversion Campaign','Campaña de ventas Q2')
   .replaceAll('Brand Awareness Campaign','Campaña para dar a conocer la marca')
   .replaceAll('Retargeting - Warm Leads','Personas que ya mostraron interés')
   .replaceAll('Prospecting - Broad Testing','Prueba con personas nuevas');
 }
 return answer;
}
function recommendationText(text){
 if(lang!=='es')return text;
 const map={
  'High performance detected - increasing budget':'Buen rendimiento: conviene aumentar el presupuesto con cuidado.',
  'Good performance - maintaining current budget':'Buen rendimiento: conviene mantener el presupuesto actual.',
  'Average performance - slight budget reduction':'Rendimiento medio: conviene bajar un poco el presupuesto.',
  'Low performance - reducing budget significantly':'Rendimiento bajo: conviene reducir el presupuesto.',
  'Even distribution maintains stable performance':'Mantener este presupuesto ayuda a conservar estabilidad.'
 };
 return map[String(text||'')]||String(text||'')
  .replace('Highly efficient conversions - increasing budget aggressively','Compras a buen costo: conviene aumentar el presupuesto con cuidado.')
  .replace('Efficient conversions - increasing budget moderately','Compras a buen costo: conviene aumentar un poco el presupuesto.')
  .replace('Break-even efficiency - maintaining budget','Resultados estables: conviene mantener el presupuesto.')
  .replace('Inefficient conversions - decreasing budget','Compras costosas: conviene bajar el presupuesto.');
}
function fatigueText(text){
 if(lang!=='es')return text;
 return String(text||'')
  .replace(/^frequency ([\d.]+)$/,'Una persona lo ve $1 veces')
  .replace(/^CTR ([\d.]+)% down$/,'Los clics bajaron $1%')
  .replace(/^CPC ([\d.]+)% up$/,'Cada clic cuesta $1% más');
}
function demoCampaignName(name){
 if(lang!=='es'||state?.metrics?.source!=='demo')return name;
 const map={'Q2 Conversion Campaign':'Campaña de ventas Q2','Brand Awareness Campaign':'Campaña para dar a conocer la marca','Retargeting - Warm Leads':'Personas que ya mostraron interés','Prospecting - Broad Testing':'Prueba con personas nuevas'};
 return map[name]||name;
}
function briefQuestion(q){return t(questionKeys[q]||q)}
function modeText(value){if(value==='dry-run')return lang==='es'?'supervisado':'supervised';if(value==='live')return lang==='es'?'piloto':'autopilot';return value}
function statusText(value){const map={active:lang==='es'?'activa':'active',paused:lang==='es'?'pausada':'paused',winning:lang==='es'?'ganadora':'winning',losing:lang==='es'?'perdedora':'losing',fatigue:lang==='es'?'cansancio':'fatigue',neutral:lang==='es'?'neutral':'neutral',blocked:lang==='es'?'bloqueado':'blocked',warn:lang==='es'?'alerta':'warn',ok:lang==='es'?'ok':'ok'};return map[value]||value}
function applyTranslations(){
 document.documentElement.lang=lang;
 qs('#language-select').value=lang;
 document.querySelectorAll('[data-i18n]').forEach(el=>{el.textContent=t(el.dataset.i18n)});
 document.querySelectorAll('[data-i18n-placeholder]').forEach(el=>{el.placeholder=t(el.dataset.i18nPlaceholder)});
 qs('#top-roas').innerHTML=tip('ROAS'); qs('#top-cpa').innerHTML=tip('CPA'); qs('#top-mode').innerHTML=tip('Mode');
 qs('#th-spend').innerHTML=tip('Spend'); qs('#th-roas').innerHTML=tip('ROAS'); qs('#th-cpa').innerHTML=tip('CPA'); qs('#th-ctr').innerHTML=tip('CTR');
 applyDashboardTheme();
 syncDashboardView();
 syncPanels();
}
function viewLabels(){return lang==='es'?{control:'Control',timeline:'En el tiempo',analytics:'Vista total',idle:'Producto',aurora:'Aurora',sapphire:'Sapphire',ember:'Ember'}:{control:'Control',timeline:'Timeline',analytics:'Total view',idle:'Showcase',aurora:'Aurora',sapphire:'Sapphire',ember:'Ember'}}
function applyDashboardTheme(){
 dashboardTheme=normalizeDashboardTheme(dashboardTheme);
 document.body.classList.toggle('theme-aurora',dashboardTheme==='aurora');
 document.body.classList.toggle('theme-sapphire',dashboardTheme==='sapphire');
 document.body.classList.toggle('theme-ember',dashboardTheme==='ember');
 document.body.classList.toggle('theme-light',dashboardTheme==='aurora');
 document.body.classList.toggle('theme-dark',dashboardTheme==='sapphire'||dashboardTheme==='ember');
 const labels=viewLabels();
 document.querySelectorAll('.theme-chip').forEach(btn=>{const theme=normalizeDashboardTheme(btn.dataset.theme);btn.textContent=labels[theme]||theme;btn.classList.toggle('active',theme===dashboardTheme);btn.setAttribute('aria-pressed',theme===dashboardTheme?'true':'false')});
 const group=qs('#theme-toggle');if(group)group.setAttribute('aria-label',lang==='es'?'Temas del dashboard':'Dashboard themes');
}
function setDashboardTheme(theme){dashboardTheme=normalizeDashboardTheme(theme);localStorage.setItem('dashboardTheme',dashboardTheme);applyDashboardTheme()}
function toggleDashboardTheme(){setDashboardTheme(dashboardTheme==='aurora'?'sapphire':dashboardTheme==='sapphire'?'ember':'aurora')}
function syncDashboardView(){
 const labels=viewLabels();
 document.querySelectorAll('.view-chip').forEach(btn=>{const view=btn.dataset.view;btn.textContent=labels[view]||view;btn.classList.toggle('active',view===dashboardView);btn.setAttribute('aria-pressed',view===dashboardView?'true':'false')});
 ['control','timeline','analytics','idle'].forEach(view=>{const el=qs(`#view-${view}`);if(el)el.classList.toggle('hidden',view!==dashboardView)})
}
function setDashboardView(view){dashboardView=view;localStorage.setItem('dashboardView',view);syncDashboardView();renderOverviewViews()}
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
window.addEventListener('resize',()=>{hideFloatingTip();syncPanels()})
function toast(msg){const t=qs('#toast');t.textContent=msg;t.style.display='block';setTimeout(()=>t.style.display='none',2600)}
function fillTemplate(text){const s=state?.metrics?.summary||{};return String(text).replace('{roas}',Number(s.overall_roas||0).toFixed(2)).replace('{cpa}',fmtMoney(s.overall_cpa)).replace('{budget}',fmtMoney(s.active_budget)).replace('{pending}',state?.pending?.length||0)}
function escapeHtml(value){return String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]))}
function isMobilePanelLayout(){return window.matchMedia('(max-width: 780px)').matches}
function panelStorageKey(side){const desktopKey=`dashboardPanel:${side}`;return isMobilePanelLayout()?`dashboardPanelMobile:${side}`:desktopKey}
function panelOpen(side){return localStorage.getItem(panelStorageKey(side))==='open'}
let dailyBriefReadTimer=null;
function dailyBriefStamp(){return String(state?.brief?.generated_at||state?.metrics?.timestamp||'')}
function hasUnreadDailyBrief(){const stamp=dailyBriefStamp();return Boolean(stamp&&state?.brief?.questions?.length&&localStorage.getItem('dashboardDailyBriefReadStamp')!==stamp)}
function syncDailyBriefUnread(){
 const unread=hasUnreadDailyBrief();
 const btn=qs('#toggle-left-panel');if(!btn)return;
 btn.classList.toggle('has-new-brief',unread);
 btn.setAttribute('data-unread',unread?'true':'false');
 const badge=qs('#daily-brief-badge');if(badge){badge.textContent=t('new_brief');badge.setAttribute('aria-hidden',unread?'false':'true')}
}
function markDailyBriefRead(){const stamp=dailyBriefStamp();if(stamp)localStorage.setItem('dashboardDailyBriefReadStamp',stamp);syncDailyBriefUnread()}
function scheduleVisibleBriefRead(){
 clearTimeout(dailyBriefReadTimer);
 if(!panelOpen('left')||!hasUnreadDailyBrief())return;
 const stamp=dailyBriefStamp();
 dailyBriefReadTimer=setTimeout(()=>{if(panelOpen('left')&&dailyBriefStamp()===stamp)markDailyBriefRead()},2200);
}
function panelTitle(side,open){
 if(side==='left')return open?(lang==='es'?'Ocultar perfil y lectura':'Hide profile and daily read'):(lang==='es'?'Mostrar perfil y lectura':'Show profile and daily read');
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
 syncDailyBriefUnread();
 scheduleVisibleBriefRead();
}
function togglePanel(side){const open=panelOpen(side);localStorage.setItem(panelStorageKey(side),open?'closed':'open');syncPanels();if(side==='left')markDailyBriefRead()}
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
function chatApprovalItems(result){
 const routed=result?.routed_action||{};const items=[];
 if(Array.isArray(result?.approval_choices))items.push(...result.approval_choices);
 if(Array.isArray(routed?.approval_choices))items.push(...routed.approval_choices);
 const candidate=routed?.result;
 if(candidate&&candidate.id&&candidate.status==='pending')items.push(candidate);
 const seen=new Set();
 return items.filter(item=>{const id=item&&item.id;if(!id||seen.has(id))return false;seen.add(id);return true}).slice(0,4);
}
function approvalItemName(item){return escapeHtml(item.name||item.payload?.name||item.payload?.campaign_name||item.type||'Decisión pendiente')}
function appendChatApprovalActions(node,result){
 const items=chatApprovalItems(result);if(!items.length)return;
 const wrap=document.createElement('div');wrap.className='msg-actions approval-chat-actions';
 wrap.innerHTML=items.map(item=>{const active=item.requires_active_confirmation||item.final_status==='ACTIVE'||item.payload?.final_status==='ACTIVE';const approveLabel=active?(lang==='es'?'Sí, crear y dejar activo':'Yes, create and leave active'):(lang==='es'?'Aprobar':'Approve');return `<div class="msg-approval-card"><b>${approvalItemName(item)}</b><span>${escapeHtml(item.type||'approval')} · ${escapeHtml(item.id)}</span><div class="msg-approval-buttons"><button class="btn primary" type="button" onclick="chatApproveDecision('${escapeHtml(item.id)}')">${approveLabel}</button><button class="btn danger" type="button" onclick="chatRejectDecision('${escapeHtml(item.id)}')">${lang==='es'?'No aprobar':'Reject'}</button></div></div>`}).join('');
 node.appendChild(wrap);qs('#chat-log').scrollTop=qs('#chat-log').scrollHeight;
}
async function chatApproveDecision(id){const attempted=await approvePending(id);const done=Array.isArray(attempted)&&attempted[0]?.status==='approved';addMessage('agent',done?(lang==='es'?'Listo. Aprobé y ejecuté esa decisión.':'Done. I approved and executed that decision.'):(lang==='es'?'Intenté aprobarla, pero quedó pendiente para reintentar. Revisa el detalle en Aprobaciones.':'I tried to approve it, but it remains pending for retry. Check the detail in Approvals.'))}
async function chatRejectDecision(id){await api('/api/reject',{method:'POST',body:JSON.stringify({approval_id:id,reason:'Rejected from chat button'})});toast(lang==='es'?'Decisión rechazada':'Decision rejected');await load();addMessage('agent',lang==='es'?'Listo. Rechacé esa decisión y no se ejecutará.':'Done. I rejected that decision and it will not execute.')}
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
async function sendChatMessage(text,{workspace=false,memoryWizard=null}={}){
 if(!text)return;
 if(workspace)document.body.classList.add('chat-workspace-open');
 openChat();
 addMessage('user',text);
 const pending=addMessage('agent',lang==='es'?'Pensando...':'Thinking...',false);pending.classList.add('thinking');
 try{const chatPayload={message:text,history:chatHistory,metrics:state.metrics,recommendations:state.recommendations,fatigue:state.fatigue,pending:state.pending,language:lang};if(memoryWizard)chatPayload.memory_wizard=memoryWizard;const res=await api('/api/chat',{method:'POST',body:JSON.stringify(chatPayload)});const reply=res.result.reply||agentReply(text);const rendered=await streamMessageContent(pending,reply);chatHistory.push({role:'agent',content:rendered});appendChatApprovalActions(pending,res.result);if(res.result.routed_action){await load();const action=res.result.routed_action;if(action.type==='creative_memory_wizard_complete'){toast(lang==='es'?'Información del anuncio actualizada':'Creative memory updated')}}}catch(err){const raw=String(err&&err.message||err||'');const needsPassword=raw.includes('dashboard password')||raw.includes('password')||raw.includes('401');const fallback=needsPassword?(lang==='es'?'Necesito la contraseña del dashboard para hablar con el agente real y ejecutar acciones protegidas. Desbloquea el dashboard y vuelve a enviar el mensaje.':'I need the dashboard password to talk to the real agent and run protected actions. Unlock the dashboard and send the message again.'):agentReply(text);const rendered=await streamMessageContent(pending,fallback);chatHistory.push({role:'agent',content:rendered})}
}
async function newChatConversation(){
 await api('/api/chat/reset',{method:'POST',body:JSON.stringify({})});
 chatHistory=[];chatHydrated=true;qs('#chat-log').innerHTML='';addMessage('agent',t('chat_welcome'));
 toast(lang==='es'?'Conversación nueva lista':'New conversation ready');
}
function agentReply(text){const msg=String(text||'').toLowerCase();if(msg.includes('presupuesto')||msg.includes('budget'))return t('chat_budget');if(msg.includes('fatiga')||msg.includes('creative')||msg.includes('creativo'))return t('chat_fatigue');if(msg.includes('config')||msg.includes('setup')||msg.includes('live'))return t('chat_setup');if(msg.includes('resumen')||msg.includes('catch')||msg.includes('dónde')||msg.includes('where'))return t('chat_summary');return `${t('chat_summary')}\n\n${t('chat_action_hint')}`}
function dataSourceText(m){const source=String(m?.source||'');if(source==='meta_graph')return lang==='es'?'Datos reales de Meta':'Real Meta data';if(source==='demo')return lang==='es'?'Datos de ejemplo':'Demo data';return lang==='es'?'Datos guardados':'Saved data'}
function chatArg(value){return JSON.stringify(String(value||'')).replaceAll('"','&quot;')}
let targetingSelections={location:[],interest:[]};
let targetingSearchResults={location:[],interest:[]};
function targetingDom(kind){return {query:qs(`#targeting-${kind}-query`),results:qs(`#targeting-${kind}-results`),selected:qs(`#targeting-${kind}-selected`),hidden:qs(`#campaign-targeting-${kind==='location'?'locations':'interests'}-json`)}}
function targetingMetaLine(item){if(item.kind==='interest'){const path=Array.isArray(item.path)&&item.path.length?` · ${item.path.join(' › ')}`:'';const size=item.audience_size?` · ${Number(item.audience_size).toLocaleString()}`:'';return `${path}${size}`.replace(/^ · /,'')}return [item.type,item.country_code].filter(Boolean).join(' · ')}
function syncTargetingHidden(kind){const dom=targetingDom(kind);if(dom.hidden)dom.hidden.value=JSON.stringify(targetingSelections[kind]||[])}
function renderSelectedTargeting(kind){const dom=targetingDom(kind);if(!dom.selected)return;const items=targetingSelections[kind]||[];dom.selected.innerHTML=items.map((item,index)=>`<span class="targeting-chip">${escapeHtml(item.label||item.name||item.key)} <button type="button" aria-label="${lang==='es'?'Quitar':'Remove'}" onclick="removeTargetingItem('${kind}',${index})">×</button></span>`).join('');syncTargetingHidden(kind)}
function addTargetingItem(kind,index){const item=(targetingSearchResults[kind]||[])[index];if(!item)return;const key=item.id||item.key||item.name;if(!(targetingSelections[kind]||[]).some(existing=>(existing.id||existing.key||existing.name)===key)){targetingSelections[kind].push(item)}renderSelectedTargeting(kind)}
function removeTargetingItem(kind,index){targetingSelections[kind].splice(index,1);renderSelectedTargeting(kind)}
function setTargetingMode(mode){document.querySelectorAll('.targeting-mode-card').forEach(btn=>btn.classList.remove('active'));const cards=[...document.querySelectorAll('.targeting-mode-card')];if(mode==='guided'&&cards[1])cards[1].classList.add('active');else if(mode==='warm'&&cards[2])cards[2].classList.add('active');else if(cards[0])cards[0].classList.add('active')}
async function searchTargeting(kind){
 const dom=targetingDom(kind);const q=(dom.query?.value||'').trim();
 if(!q){if(dom.results)dom.results.innerHTML=`<div class="targeting-empty">${t('targeting_need_query')}</div>`;return}
 if(dom.results)dom.results.innerHTML=`<div class="targeting-empty">${lang==='es'?'Buscando opciones reales de Meta...':'Searching real Meta options...'}</div>`;
 try{
  const res=await api('/api/targeting/search',{method:'POST',body:JSON.stringify({kind,q,limit:8})});
  const result=res.result||{};const items=result.items||[];targetingSearchResults[kind]=items;
  if(!result.ok){dom.results.innerHTML=`<div class="targeting-error">${escapeHtml(result.message||'Meta search unavailable')}</div>`;return}
  if(!items.length){dom.results.innerHTML=`<div class="targeting-empty">${t('targeting_no_results')}</div>`;return}
  dom.results.innerHTML=items.map((item,index)=>`<button class="targeting-result" type="button" onclick="addTargetingItem('${kind}',${index})"><span><b>${escapeHtml(item.label||item.name)}</b><span>${escapeHtml(targetingMetaLine(item))}</span></span><strong>+</strong></button>`).join('');
 }catch(err){if(dom.results)dom.results.innerHTML=`<div class="targeting-error">${escapeHtml(err.message||String(err))}</div>`}
}
function clamp(n,min,max){return Math.max(min,Math.min(max,n))}
function dayLabels(){return lang==='es'?['Lun','Mar','Mié','Jue','Vie','Sáb','Dom']:['Mon','Tue','Wed','Thu','Fri','Sat','Sun']}
function campaignInitials(name){return String(name||'AD').split(/\s+/).filter(Boolean).slice(0,2).map(x=>x[0]).join('').toUpperCase()||'AD'}
function aggregateTrend(campaigns){
 const rows=(campaigns||[]).filter(c=>Array.isArray(c.trend)&&c.trend.length);
 if(!rows.length)return [12,18,14,22,28,24,31];
 const len=Math.max(...rows.map(c=>c.trend.length));
 return Array.from({length:Math.min(7,len)},(_,i)=>rows.reduce((sum,c)=>sum+Number(c.trend[i%c.trend.length]||0),0));
}
function miniBars(values,cls=''){
 const max=Math.max(...values,1);
 return `<div class="mini-bars ${cls}">${values.map(v=>`<i style="height:${clamp((Number(v||0)/max)*64,10,70)}px"></i>`).join('')}</div>`;
}
function renderOverviewViews(){
 syncDashboardView();
 if(!state||!state.metrics)return;
 renderTimelineView();
 renderAnalyticsView();
 renderIdleView();
}
function renderTimelineView(){
 const box=qs('#view-timeline');if(!box)return;
 const campaigns=state.metrics?.campaigns||[];
 const days=dayLabels();
 const rows=campaigns.length?campaigns.map((c,i)=>{
  const left=clamp((i%4)*5,0,22);
  const width=c.status==='paused'?34:clamp(42+Number(c.roas||1)*6,42,82);
  const health=String(c.health||'neutral');
  const label=c.status==='active'?(lang==='es'?'Activa':'Active'):statusText(c.status||health);
  const draft=lang==='es'?`Muéstrame qué pasó estos días con ${c.name} y dime qué harías ahora.`:`Give me a timeline read for ${c.name}. What happened this week and what would you move now?`;
  const returnLabel=lang==='es'?`Vuelve ${Number(c.roas||0).toFixed(2)}x por cada $1`:`ROAS ${Number(c.roas||0).toFixed(2)}x`;
  return `<div class="timeline-row"><div><div class="timeline-name">${escapeHtml(demoCampaignName(c.name))}</div><div class="timeline-status">${label} · ${returnLabel}</div></div><div class="timeline-track"><button class="timeline-bar ${escapeHtml(health)}" style="left:${left}%;width:${width}%" onclick="openChat(${chatArg(draft)})"><span>${campaignInitials(demoCampaignName(c.name))}</span><span>${label}</span></button></div></div>`;
 }).join(''):`<p class="notice">${lang==='es'?'Cuando tengas anuncios activos, los verás aquí como una línea de tiempo visual.':'When ads are active, you will see them here as a visual timeline.'}</p>`;
 box.innerHTML=`<section class="timeline-shell"><div class="timeline-head"><div><h3>${lang==='es'?'Anuncios en el tiempo':'Active ads timeline'}</h3><p>${lang==='es'?'Una vista rápida para entender qué está corriendo, qué está pausado y dónde conviene preguntarle al agente.':'A fast view of what is running, what is paused, and where to ask the manager.'}</p></div><button class="btn ask-btn" onclick="openChat(${chatArg(lang==='es'?'Mira todos mis anuncios en el tiempo y dime cuál necesita atención hoy.':'Read the full timeline and tell me which campaign needs attention today.')})">${t('ask_agent')}</button></div><div class="timeline-scale"><span></span>${days.map(d=>`<span>${d}</span>`).join('')}</div>${rows}</section>`;
}
function renderAnalyticsView(){
 const box=qs('#view-analytics');if(!box)return;
 const m=state.metrics||{},s=m.summary||{},campaigns=m.campaigns||[];
 const total=Math.max(Number(s.total_spend||0)+Number(s.total_revenue||0)+Number(s.total_conversions||0),1);
 const trends=aggregateTrend(campaigns);
 const top=[...campaigns].sort((a,b)=>Number(b.roas||0)-Number(a.roas||0)).slice(0,6);
 const winner=top[0];
 const days=dayLabels();
 box.innerHTML=`<section class="analytics-grid"><div class="analytics-hero analytics-card"><div class="analytics-head"><div><h3>${lang==='es'?'Vista general':'Total overview'}</h3><p>${lang==='es'?'Lectura visual de inversión, resultados y movimiento de los últimos días.':'Visual read of spend, results, and recent movement.'}</p></div><span class="badge winning">+ ${Number(s.overall_roas||0).toFixed(2)}x</span></div><div class="analytics-legend"><div class="legend-row"><span class="legend-dot" style="background:#b9a8ff"></span><span>${t('spend')}</span><b>${fmtMoney(s.total_spend)}</b></div><div class="legend-track"><i class="legend-fill" style="display:block;width:${clamp(Number(s.total_spend||0)/total*100,8,100)}%"></i></div><div class="legend-row"><span class="legend-dot" style="background:#ffd55d"></span><span>${t('revenue')}</span><b>${fmtMoney(s.total_revenue)}</b></div><div class="legend-track"><i class="legend-fill" style="display:block;width:${clamp(Number(s.total_revenue||0)/total*100,8,100)}%"></i></div><div class="legend-row"><span class="legend-dot" style="background:#7fded5"></span><span>${t('conversions')}</span><b>${Number(s.total_conversions||0).toLocaleString()}</b></div><div class="legend-track"><i class="legend-fill" style="display:block;width:${clamp(Number(s.total_conversions||0)/total*100,8,100)}%"></i></div></div></div><div class="analytics-card"><div class="analytics-head"><div><h3>${lang==='es'?'Semana':'Week'}</h3><p>${lang==='es'?'Pulso diario de actividad.':'Daily activity pulse.'}</p></div></div><div class="calendar-mini">${days.map((d,i)=>{const v=Number(trends[i]||0),h=clamp(v/Math.max(...trends,1),.18,1);return `<div class="calendar-day"><span>${d}</span><div class="day-stack"><i class="day-seg a" style="height:${20*h}px"></i><i class="day-seg b" style="height:${34*h}px"></i><i class="day-seg c" style="height:${24*h}px"></i></div></div>`}).join('')}</div></div></section><section class="analytics-cards"><div class="analytics-card"><h4>${lang==='es'?'Señales del negocio':'Market signal'}</h4><strong>${fmtMoney(s.total_spend)}</strong><p class="notice">${lang==='es'?'Inversión leída por el agente para decidir con menos estrés.':'Spend read by the agent for calmer decisions.'}</p>${miniBars(trends)}</div><div class="analytics-card"><h4>${lang==='es'?'Resultados':'Efficiency'}</h4><strong>${Number(s.overall_roas||0).toFixed(2)}x</strong><p class="notice">${lang==='es'?'Resultado general con alertas de costo por compra y cansancio de anuncios.':'Global ROAS with CPA and fatigue alerts.'}</p>${spark(trends)}</div><div class="analytics-card"><h4>${lang==='es'?'Mejores campañas':'Top campaigns'}</h4><strong>${campaigns.length}</strong><p class="notice">${winner?`${escapeHtml(demoCampaignName(winner.name))} · ${Number(winner.roas||0).toFixed(2)}x`:lang==='es'?'Aún no hay campañas.':'No campaigns yet.'}</p><div class="avatar-row">${top.map(c=>`<span class="avatar-chip" title="${escapeHtml(demoCampaignName(c.name))}">${campaignInitials(demoCampaignName(c.name))}</span>`).join('')}</div></div></section>`;
}
function renderIdleView(){
 const box=qs('#view-idle');if(!box)return;
 const m=state.metrics||{},s=m.summary||{},p=state.business_profile||{};
 const offer=p.main_offer||p.offer||p.detected_title||(lang==='es'?'tu producto':'your product');
 const draft=lang==='es'?'Quiero crear una imagen showcase de mi producto para el modo idle. Usa mis guías de marca, pregúntame por la imagen de referencia si hace falta y prepara prompts consistentes.':'I want to create a product showcase image for idle mode. Use my brand guides, ask for the reference image if needed, and prepare consistent prompts.';
 box.innerHTML=`<section class="idle-hero"><div class="idle-grid"><div class="idle-copy"><div class="idle-head"><div><h3>${lang==='es'?'Hola, este es el pulso de ':'Hello, this is the pulse for '}<span>${escapeHtml(offer)}</span></h3><p>${lang==='es'?'Una vista tranquila para dejar abierta en pantalla: el agente sigue leyendo datos, cuidando señales y esperando que le hables como a un manager.':'A calm view to leave open: the agent keeps reading data, watching signals, and waiting for you to talk to it like a manager.'}</p></div></div><div class="showcase-actions"><button class="btn primary" onclick="openChat(${chatArg(draft)})">${lang==='es'?'Crear imagen del producto con Codex':'Create showcase with Codex'}</button><button class="btn ask-btn" onclick="openChat(${chatArg(lang==='es'?'Dime qué debería vigilar hoy en esta cuenta y qué harías tú ahora.':'Tell me what I should watch today in this account and what you would do now.')})">${t('ask_manager')}</button></div></div><div class="idle-product-stage"><div class="product-orb"></div><div class="idle-floating one"><b>${Number(s.overall_roas||0).toFixed(2)}x</b><span>${lang==='es'?'VUELVE / $1':'ROAS'}</span></div><div class="idle-floating two"><b>${fmtMoney(s.overall_cpa)}</b><span>${lang==='es'?'COSTO / COMPRA':'CPA'}</span></div><div class="idle-floating three"><b>${Number(s.total_conversions||0).toLocaleString()}</b><span>${t('conversions')}</span></div></div></div></section>`;
}
let unlockResolver=null;
let unlockMode='unlock';
function dashboardPassword(){return localStorage.getItem('dashboardPassword')||localStorage.getItem('dashboardToken')||''}
function dashboardPasswordIsSet(){return !state||!state.config||state.config.dashboard_password_set!==false}
function setUnlockError(message=''){const err=qs('#unlock-error');if(err){err.textContent=message;err.classList.toggle('show',Boolean(message))}}
function syncUnlockMode(mode=''){unlockMode=mode||(dashboardPasswordIsSet()?'unlock':'create');const create=unlockMode==='create';const title=qs('#unlock-title'),body=qs('#unlock-body'),button=qs('#unlock-submit'),label=qs('#unlock-password-label'),confirmLabel=qs('#unlock-confirm-label'),input=qs('#unlock-password'),confirmInput=qs('#unlock-confirm-password'),confirmWrap=qs('#unlock-confirm-wrap');if(title){title.dataset.i18n=create?'unlock_create_title':'unlock_title';title.textContent=t(title.dataset.i18n)}if(body){body.dataset.i18n=create?'unlock_create_body':'unlock_body';body.textContent=t(body.dataset.i18n)}if(button){button.dataset.i18n=create?'unlock_create_button':'unlock_button';button.textContent=t(button.dataset.i18n)}if(label){label.dataset.i18n='dashboard_password';label.textContent=t('dashboard_password')}if(confirmLabel){confirmLabel.dataset.i18n='dashboard_password_confirm';confirmLabel.textContent=t('dashboard_password_confirm')}if(input){input.autocomplete=create?'new-password':'current-password';input.placeholder=create?(lang==='es'?'Crea una contraseña segura':'Create a secure password'):''}if(confirmInput){confirmInput.classList.toggle('hidden',!create);confirmInput.disabled=!create;confirmInput.placeholder=create?(lang==='es'?'Escríbela otra vez':'Type it again'):'';confirmInput.value=''}if(confirmWrap)confirmWrap.classList.toggle('hidden',!create)}
function showUnlock(message='',mode=''){const overlay=qs('#unlock-overlay');syncUnlockMode(mode);setUnlockError(message);overlay.classList.add('open');setTimeout(()=>qs('#unlock-password')?.focus(),30);return new Promise(resolve=>{unlockResolver=resolve})}
function hideUnlock(){qs('#unlock-overlay')?.classList.remove('open');setUnlockError('')}
async function requestUnlock(message=''){const mode=dashboardPasswordIsSet()?'unlock':'create';return showUnlock(message||t(mode==='create'?'unlock_create_needed':'unlock_needed'),mode)}
async function responseErrorMessage(res){const text=await res.text();try{const data=JSON.parse(text);return data.error||data.detail||text}catch{return text}}
async function api(path,opts={}){const headers={'Content-Type':'application/json',...(opts.headers||{})};const password=dashboardPassword();if(password)headers['X-Dashboard-Token']=password;let res=await fetch(path,{...opts,headers});if(res.status===401){const entered=await requestUnlock();if(entered){headers['X-Dashboard-Token']=entered;res=await fetch(path,{...opts,headers});if(res.status===401){localStorage.removeItem('dashboardPassword');await requestUnlock(t('unlock_failed'));throw new Error(t('unlock_failed'))}}}if(!res.ok)throw new Error(await responseErrorMessage(res));return res.json()}
async function load(){state=await api('/api/dashboard');render();if(!uiWorkbenchPreview&&state.config.dashboard_password_required&&!state.config.dashboard_password_set)showUnlock(t('unlock_create_needed'),'create');else if(!uiWorkbenchPreview&&state.config.dashboard_password_required&&state.config.dashboard_password_set&&!dashboardPassword()&&state.onboarding&&state.onboarding.completed)showUnlock(t('unlock_needed'),'unlock');checkForUpdates(false)}
function decisionEvidenceMarkup(card){
 if(!card)return '';
 const ask=lang==='es'?`Explícame esta decisión sobre ${card.campaign_name||'mi campaña'} en palabras simples. Señal: ${card.signal||''}. Recomendación: ${card.recommendation||''}`:`Explain this decision about ${card.campaign_name||'my campaign'} in simple words. Signal: ${card.signal||''}. Recommendation: ${card.recommendation||''}`;
 return `<div class="brief-q decision-card"><b>${escapeHtml(card.title|| (lang==='es'?'Decisión con evidencia':'Decision with evidence'))}: ${escapeHtml(demoCampaignName(card.campaign_name||''))}</b><p>${escapeHtml(card.diagnosis||'')}</p><p><strong>${lang==='es'?'Señal':'Signal'}:</strong> ${escapeHtml(card.signal||'')}</p><p><strong>${lang==='es'?'Sugerencia':'Suggestion'}:</strong> ${escapeHtml(card.recommendation||'')}</p><p><strong>${lang==='es'?'Riesgo':'Risk'}:</strong> ${escapeHtml(card.risk||'')}</p><button class="btn ask-btn" onclick="openChat(${chatArg(ask)})">${t('ask_agent')}</button></div>`;
}
function decisionCardsMarkup(){
 const cards=state.decision_memory?.cards||[];
 if(!cards.length)return '';
 return `<div class="decision-memory-stack"><div class="next-step"><div><b>${lang==='es'?'Decisiones con evidencia':'Evidence-backed decisions'}</b><p>${lang==='es'?'El agente guarda por qué recomendó algo y lo revisa después de 24h, 3 días y 7 días.':'The agent saves why it recommended something and checks it again after 24h, 3 days, and 7 days.'}</p></div></div>${cards.slice(0,3).map(decisionEvidenceMarkup).join('')}</div>`;
}
function actionLabelText(text){
 if(lang!=='es')return text;
 return String(text||'')
  .replace(/^Paused (\d+) clear bleeder\(s\) under autopilot rules\.$/,'Pausé $1 gasto malo claro bajo tus reglas de piloto automático.')
  .replace(/^Prepared (\d+) creative refresh draft\(s\)\.$/,'Preparé $1 idea(s) nueva(s) para anuncios.')
  .replace(/^(\d+) pause decision\(s\) need buyer approval\.$/,'$1 pausa(s) necesitan tu aprobación.')
  .replace(/^(\d+) budget move\(s\) need buyer approval\.$/,'$1 cambio(s) de presupuesto necesitan tu aprobación.')
  .replace(/^(\d+) smaller budget move\(s\) are worth reviewing\.$/,'$1 movimiento(s) pequeños de presupuesto valen la pena revisar.')
  .replace(/^(\d+) fatigue signal\(s\) should feed the next creative test\.$/,'$1 señal(es) de cansancio deberían alimentar la próxima prueba creativa.')
  .replace('No strong action signal yet. Keep watching pacing, CPA, ROAS, CTR, and frequency.','Todavía no hay una señal fuerte para tocar Meta. Sigo vigilando ritmo de gasto, CPA, ROAS, clics y frecuencia.');
}
function actionSummaryMarkup(){
 const summary=state.brief?.action_summary||{};
 const buckets=[
  ['already_done',lang==='es'?'Ya hice':'Already done'],
  ['waiting_for_approval',lang==='es'?'Necesita tu luz verde':'Waiting for approval'],
  ['recommended_next',lang==='es'?'Siguiente movimiento':'Next move'],
  ['watching',lang==='es'?'Estoy vigilando':'Watching']
 ];
 const html=buckets.map(([key,title])=>{
  const items=summary[key]||[];if(!items.length)return '';
  return `<div class="brief-q action-bucket"><b>${title}</b>${items.map(item=>`<p>${escapeHtml(actionLabelText(item.label||''))}</p>`).join('')}</div>`;
 }).join('');
 return html?`<div class="decision-memory-stack action-summary-stack">${html}</div>`:'';
}
function render(){
 applyTranslations();
 hydrateChatHistory();
 renderUpdateBanner(updateInfo);
 renderDeferredOnboardingBanner();
 const m=state.metrics, s=m.summary;
 qs('#s-roas').textContent=Number(s.overall_roas||0).toFixed(2)+'x'; qs('#s-cpa').textContent=fmtMoney(s.overall_cpa); qs('#s-mode').textContent=modeText(state.config.mode); qs('#s-updated').textContent=new Date(m.timestamp).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
 qs('#data-source-signal').textContent=dataSourceText(m);
 const refreshBtn=qs('#real-data-refresh');if(refreshBtn){refreshBtn.classList.toggle('hidden',m.source==='meta_graph');refreshBtn.textContent=lang==='es'?'Actualizar datos reales':'Refresh real data'}
 qs('#kpis').innerHTML=[['Spend',fmtMoney(s.total_spend)],['Revenue',fmtMoney(s.total_revenue)],['Conversions',Number(s.total_conversions||0).toLocaleString()],['Active Budget',fmtMoney(s.active_budget)]].map(x=>kpi(x[0],x[1])).join('');
 renderBusinessProfilePanel();
 qs('#brief').innerHTML=state.brief.questions.map(q=>`<div class="brief-q"><b>${briefQuestion(q.question)}</b><p>${explainTerms(briefAnswer(q.answer))}</p></div>`).join('')+actionSummaryMarkup()+decisionCardsMarkup();
 qs('#fatigue').innerHTML=state.fatigue.length?state.fatigue.map(f=>`<div class="fatigue"><b>${escapeHtml(demoCampaignName(f.campaign_name))}</b><div>${escapeHtml(f.reasons.map(fatigueText).join(' / '))}</div></div>`).join(''):`<p class="notice">${t('no_fatigue')}</p>`;
 qs('#campaigns').innerHTML=m.campaigns.map(card).join('');
 renderOverviewViews();
 qs('#recs').innerHTML=state.recommendations.map(r=>{const draft=lang==='es'?`Revisa esta recomendación de presupuesto para ${r.campaign_name}: actual ${fmtMoney(r.current_budget)}, sugerido ${fmtMoney(r.recommended_budget)}. ¿La aplicarías o esperarías?`:`Review this budget recommendation for ${r.campaign_name}: current ${fmtMoney(r.current_budget)}, suggested ${fmtMoney(r.recommended_budget)}. Would you apply it or wait?`;return `<tr><td>${escapeHtml(demoCampaignName(r.campaign_name))}<br><span class="notice">${escapeHtml(recommendationText(r.reason))}</span></td><td>${fmtMoney(r.current_budget)}</td><td>${fmtMoney(r.recommended_budget)}</td><td><button class="btn" onclick="applyRec('${r.campaign_id}',${r.recommended_budget})">${r.requires_approval?t('request'):t('apply')}</button><button class="btn ask-btn" style="margin-top:6px" onclick="openChat(${JSON.stringify(draft).replaceAll('"','&quot;')})">${t('ask_agent')}</button></td></tr>`}).join('');
 qs('#recs-mobile').innerHTML=state.recommendations.map(r=>{const draft=lang==='es'?`Revisa esta recomendación de presupuesto para ${r.campaign_name}: actual ${fmtMoney(r.current_budget)}, sugerido ${fmtMoney(r.recommended_budget)}. ¿La aplicarías o esperarías?`:`Review this budget recommendation for ${r.campaign_name}: current ${fmtMoney(r.current_budget)}, suggested ${fmtMoney(r.recommended_budget)}. Would you apply it or wait?`;return `<div class="rec-card"><h3>${escapeHtml(demoCampaignName(r.campaign_name))}</h3><p class="notice">${escapeHtml(recommendationText(r.reason))}</p><div class="rec-values"><div><b>${fmtMoney(r.current_budget)}</b><span>${t('now')}</span></div><div><b>${fmtMoney(r.recommended_budget)}</b><span>${t('rec')}</span></div></div><button class="btn primary" onclick="applyRec('${r.campaign_id}',${r.recommended_budget})">${r.requires_approval?t('request'):t('apply')}</button><button class="btn ask-btn" style="margin-top:7px" onclick="openChat(${JSON.stringify(draft).replaceAll('"','&quot;')})">${t('ask_agent')}</button></div>`}).join('');
 qs('#pending').innerHTML=state.pending.length?`<div class="approval-stack">${state.pending.map(approvalCard).join('')}</div>`:`<p class="notice">${t('no_pending')}</p>`;
 qs('#actions').innerHTML=state.actions.length?state.actions.map(a=>`<div class="log-item"><b>${actionName(a.type)}</b> - ${statusText(a.status)}<br>${new Date(a.created_at).toLocaleString()}${actionDetail(a)}</div>`).join(''):`<p class="notice">${t('no_actions')}</p>`;
 qs('#report-rows').innerHTML=m.campaigns.map(c=>`<tr><td>${escapeHtml(demoCampaignName(c.name))}</td><td>${fmtMoney(c.spend)}</td><td>${Number(c.roas).toFixed(2)}x</td><td>${fmtMoney(c.cpa)}</td><td>${fmtPct(c.ctr)}</td><td>${statusText(c.health)}</td></tr>`).join('');
 renderCreativeStudio();
 renderSetup();
 renderAudience();
 renderOnboardingFlow();
}
let brandEditorMode='general';
let brandEditorProductId='';
let brandAdBriefProductGuide='';
function brandProductById(id){return (state.brand_guides?.products||[]).find(product=>product.id===id)}
function brandAdBriefById(id){return (state.brand_guides?.ad_briefs||[]).find(brief=>brief.id===id)}
function openBrandMemory(mode='general',itemId=''){
 brandEditorMode=mode;brandEditorProductId=itemId||'';
 qs('#brand-memory-overlay')?.classList.add('open');
 renderBrandMemoryModal();
}
function closeBrandMemory(){qs('#brand-memory-overlay')?.classList.remove('open')}
function memoryField(name,label,value='',placeholder='',wide=false,area=false){
 const classes=`brand-field${wide?' wide':''}`;
 const content=area?`<textarea name="${name}" placeholder="${escapeHtml(placeholder)}">${escapeHtml(value)}</textarea>`:`<input name="${name}" value="${escapeHtml(value)}" placeholder="${escapeHtml(placeholder)}">`;
 return `<label class="${classes}"><span>${escapeHtml(label)}</span>${content}</label>`;
}
function memorySelect(name,label,value='',options=[]){
 return `<label class="brand-field"><span>${escapeHtml(label)}</span><select name="${name}"><option value="">${lang==='es'?'Sin producto fijo':'No fixed product'}</option>${options.map(option=>`<option value="${escapeHtml(option.value)}" ${option.value===value?'selected':''}>${escapeHtml(option.label)}</option>`).join('')}</select></label>`;
}
function memoryWizardCta(kind,itemId=''){
 const labels={
  general:[lang==='es'?'Contarle cómo es mi marca':'Tell the agent about my brand',lang==='es'?'Te hará preguntas fáciles y lo recordará cuando cree anuncios.':'It asks simple questions and saves your answers for future ads.'],
  product:[lang==='es'?'Contarle qué vendo':'Tell it about my product',lang==='es'?'Te pregunta sobre tu producto, sin hacerte llenar casillas.':'Explain it in chat instead of filling every field.'],
  ad_brief:[lang==='es'?'Hablar y crear mi anuncio':'Create the idea with the agent',lang==='es'?'Dile qué quieres mostrar. El agente hará preguntas fáciles y preparará tu idea.':'It asks what you want to advertise and prepares a clear idea for your images and text.']
 };
 const copy=labels[kind]||labels.general;
 return `<div class="memory-wizard-cta"><div><b>${copy[0]}</b><p>${copy[1]}</p></div><button class="btn primary ask-btn" type="button" onclick="startCreativeMemoryWizard(${chatArg(kind)},${chatArg(itemId)},${chatArg(lang)})">${lang==='es'?'Empezar a hablar':'Answer in chat'}</button></div>`;
}
function startCreativeMemoryWizard(kind,itemId='',draftLang=''){
 const productGuide=kind==='ad_brief'?brandAdBriefProductGuide:'';
 closeBrandMemory();
 const es=(draftLang||uiLang())==='es';
 const labels={
  general:es?'Quiero contarte cómo es mi marca. Hazme preguntas fáciles, una a la vez, y recuerda mis respuestas para los anuncios.':'I want to complete my general brand memory with you. Ask simple questions and save it at the end.',
  product:es?'Quiero contarte qué vendo. Hazme preguntas fáciles, una a la vez, y recuerda mis respuestas para los anuncios.':'I want to create a product or offer sheet with you. Ask simple questions and save it at the end.',
  ad_brief:es?'Quiero preparar una idea para un anuncio contigo. Pregúntame qué vendo, qué oferta quiero mostrar, a quién quiero llegar y qué imágenes o textos quiero preparar. Al final guarda la idea.':'I want to prepare an ad idea with you. Ask what I sell, what offer I want to show, who I want to reach, and what images or text I want prepared. Save the idea at the end.'
 };
 sendChatMessage(labels[kind]||labels.general,{workspace:true,memoryWizard:{mode:'start',kind,id:itemId||'',product_guide:productGuide}});
}
function generalMemoryForm(fields){
 return `<div class="brand-editor-intro"><h3>${lang==='es'?'Cómo es tu marca':'Your brand foundation'}</h3><p>${lang==='es'?'Cuéntale al agente cómo quieres que se vean y suenen tus anuncios.':'The manager learns this once and respects it across every product creative.'}</p>${memoryWizardCta('general')}</div><form class="brand-editor-form" onsubmit="saveGeneralMemory(event)"><section class="brand-form-section"><h4>${lang==='es'?'Sobre tu negocio':'Business'}</h4><div class="brand-form-grid">${memoryField('brand_name',lang==='es'?'Nombre de tu marca':'Brand name',fields.brand_name,'Miro Ads')}${memoryField('offer',lang==='es'?'Qué vendes':'What you sell',fields.offer,'Cursos, productos o servicios')}${memoryField('promise',lang==='es'?'Qué ayudas a conseguir':'Main promise',fields.promise,'El cambio que busca tu comprador',true,true)}${memoryField('ideal_customer',lang==='es'?'A quién quieres ayudar':'Ideal customer',fields.ideal_customer,'Quién compraría tu producto',true,true)}</div></section><section class="brand-form-section"><h4>${lang==='es'?'Cómo deben verse tus anuncios':'Visual style'}</h4><div class="brand-form-grid">${memoryField('colors',lang==='es'?'Colores que usas':'Core colors',fields.colors,'Rosa suave, blanco, turquesa')}${memoryField('visual_style',lang==='es'?'Cómo quieres que se vean':'How it should look',fields.visual_style,'Limpio, sencillo, con el producto visible',true,true)}${memoryField('references',lang==='es'?'Ejemplos que te gustan':'Visual references',fields.references,'Marcas, fotos o estilos que te gustan',true,true)}</div></section><section class="brand-form-section"><h4>${lang==='es'?'Cómo debe hablar':'Voice and boundaries'}</h4><div class="brand-form-grid">${memoryField('tone',lang==='es'?'Cómo quieres que suene':'How it should sound',fields.tone,'Cercano, seguro y simple',true,true)}${memoryField('show_always',lang==='es'?'Qué siempre debe mostrar':'Always show',fields.show_always,'Producto, beneficio claro, personas reales',true,true)}${memoryField('avoid_always',lang==='es'?'Qué nunca debe mostrar ni decir':'Always avoid',fields.avoid_always,'Promesas que no puedes probar o demasiado texto',true,true)}</div></section><div class="brand-form-save"><button class="btn primary" type="submit">${lang==='es'?'Guardar mi marca':'Save brand memory'}</button></div></form>`;
}
function productMemoryForm(fields,product){
 const hidden=product?`<input type="hidden" name="id" value="${escapeHtml(product.id)}">`:'';
 return `<div class="brand-editor-intro"><h3>${product?(lang==='es'?'Datos de tu producto':'Product details'):(lang==='es'?'Nuevo producto o promoción':'New product or offer')}</h3><p>${lang==='es'?'El agente usa esto para crear anuncios sobre lo que de verdad vendes.':'The manager uses these details so images and text match the right product.'}</p>${memoryWizardCta('product',product?.id||'')}${product?`<div class="brand-editor-actions"><button class="btn primary" type="button" onclick="refreshForProduct(${chatArg(product.id)})">${lang==='es'?'Crear ideas de anuncios':'Create ad ideas'}</button><button class="btn" type="button" onclick="startAdBriefForProduct(${chatArg(product.id)})">${lang==='es'?'Crear un anuncio para este producto':'Create an ad for this product'}</button><button class="btn" type="button" onclick="chatForProduct(${chatArg(product.id)},${chatArg(lang)})">${lang==='es'?'Hablar con el agente':'Talk with the agent'}</button></div>`:''}</div><form class="brand-editor-form" onsubmit="saveProductMemory(event)">${hidden}<section class="brand-form-section"><h4>${lang==='es'?'Lo que vendes':'Offer'}</h4><div class="brand-form-grid">${memoryField('name',lang==='es'?'Nombre del producto':'Product name',fields.name,'Curso de anuncios para tiendas')}${memoryField('url',lang==='es'?'Página donde pueden comprar':'Sales page',fields.url,'https://...')}${memoryField('price',lang==='es'?'Precio':'Price or range',fields.price,'USD $49')}${memoryField('includes',lang==='es'?'Qué recibe la persona':'What is included',fields.includes,'Describe lo que recibe',true,true)}</div></section><section class="brand-form-section"><h4>${lang==='es'?'Quién lo compra':'Buyer and transformation'}</h4><div class="brand-form-grid">${memoryField('audience',lang==='es'?'Para quién es':'Who it is for',fields.audience,'A quién quieres atraer',true,true)}${memoryField('pain',lang==='es'?'Qué problema tiene':'Pain they feel',fields.pain,'Qué le preocupa hoy',true,true)}${memoryField('desire',lang==='es'?'Qué quiere conseguir':'Desired outcome',fields.desire,'Qué desea conseguir',true,true)}${memoryField('objections',lang==='es'?'Qué duda puede tener':'Buying objections',fields.objections,'Precio, confianza, tiempo...',true,true)}</div></section><section class="brand-form-section"><h4>${lang==='es'?'Ideas para mostrarlo':'Angles and creative rules'}</h4><div class="brand-form-grid">${memoryField('angle_pain',lang==='es'?'Mostrar su problema':'Pain angle',fields.angle_pain,'Cómo mostrar el problema',true,true)}${memoryField('angle_desire',lang==='es'?'Mostrar el resultado':'Desire angle',fields.angle_desire,'Cómo mostrar el resultado',true,true)}${memoryField('angle_trust',lang==='es'?'Dar confianza':'Trust angle',fields.angle_trust,'Reseñas, datos reales o tranquilidad',true,true)}${memoryField('show',lang==='es'?'Qué debe mostrar':'Show',fields.show,'Producto, personas, detalle visual',true,true)}${memoryField('avoid',lang==='es'?'Qué no debe aparecer':'Do not show',fields.avoid,'Lo que dañaría la marca',true,true)}${memoryField('strong_phrases',lang==='es'?'Frases que puede usar':'Approved phrases',fields.strong_phrases,'Mensajes que sí puedes prometer',true,true)}</div></section><div class="brand-form-save"><button class="btn primary" type="submit">${lang==='es'?'Guardar producto':'Save product details'}</button></div></form>`;
}
function adBriefMemoryForm(fields,brief){
 const products=state.brand_guides?.products||[];
 const productValue=fields.product_guide||brandAdBriefProductGuide||'';
 const productOptions=products.map(product=>({value:product.guide,label:product.name}));
 const hidden=brief?`<input type="hidden" name="id" value="${escapeHtml(brief.id)}">`:'';
 const manualForm=`<form class="brand-editor-form" onsubmit="saveAdBriefMemory(event)">${hidden}<section class="brand-form-section"><h4>${lang==='es'?'Lo básico':'The basics'}</h4><div class="brand-form-grid">${memoryField('name',lang==='es'?'Nombre de esta idea':'Idea name',fields.name,'Promo de junio')}${memorySelect('product_guide',lang==='es'?'Qué vendes':'Product/offer',productValue,productOptions)}${memoryField('adset_name',lang==='es'?'Quién debe ver el anuncio':'Audience',fields.adset_name,'Mujeres de 25 a 44 años en Colombia')}${memoryField('objective',lang==='es'?'Qué quieres que hagan':'Goal',fields.objective,'Comprar, escribirte, reservar...')}${memoryField('promotion',lang==='es'?'Qué quieres mostrarles':'Promotion or specific idea',fields.promotion,'2x1, lanzamiento, bono, temporada...',true,true)}${memoryField('audience_slice',lang==='es'?'Qué les importa o preocupa':'Audience needs',fields.audience_slice,'Qué buscan o qué les preocupa',true,true)}</div></section><section class="brand-form-section"><h4>${lang==='es'?'Lo que puede cambiar':'Options to try'}</h4><div class="brand-form-grid">${memoryField('base_ad',lang==='es'?'Qué ya te funcionó':'What already works',fields.base_ad,'Imagen, frase, testimonio u oferta...',true,true)}${memoryField('locked_elements',lang==='es'?'Qué no debe cambiar':'Do not change',fields.locked_elements,'Precio, oferta, producto o frase...',true,true)}${memoryField('variation_window',lang==='es'?'Quieres una idea o varias opciones':'Creative options',fields.variation_window,'Ej: una idea, o tres opciones cambiando colores',true,true)}${memoryField('variation_axes',lang==='es'?'Qué se puede cambiar':'What can vary',fields.variation_axes,'Colores, fondo, foto o título',true,true)}${memoryField('variation_count',lang==='es'?'Cuántas opciones preparar':'Number of options',fields.variation_count,'1')}${memoryField('creative_hypothesis',lang==='es'?'Qué quieres comparar':'What to compare',fields.creative_hypothesis,'Ej: si una foto clara recibe más clics',true,true)}${memoryField('agent_notes',lang==='es'?'Algo más que deba saber':'Manager notes',fields.agent_notes,'Cualquier detalle importante',true,true)}</div></section><details class="brand-advanced"><summary>${lang==='es'?'Solo si ya tienes anuncios en Meta':'Only if you already have Meta ads'}</summary><section class="brand-form-section"><div class="brand-form-grid">${memoryField('campaign_name',lang==='es'?'Nombre de la campaña anterior':'Campaign',fields.campaign_name,'Opcional')}${memoryField('base_ad_name',lang==='es'?'Nombre del anuncio que quieres mejorar':'Base ad',fields.base_ad_name,'Opcional')}${memoryField('base_ad_id',lang==='es'?'Número del anuncio, si lo conoces':'Base ad ID',fields.base_ad_id,'Opcional')}</div></section></details><div class="brand-form-save"><button class="btn primary" type="submit">${lang==='es'?'Guardar esta idea':'Save ad idea'}</button></div></form>`;
 return `<div class="brand-editor-intro"><h3>${brief?(lang==='es'?'Tu idea de anuncio':'Ad idea'):(lang==='es'?'Crear un anuncio':'New ad idea')}</h3><p>${lang==='es'?'Puedes explicárselo al agente hablando, como se lo contarías a una persona. Él organizará la información por ti.':'Describe what you want to advertise, who you want to reach, and which images or text you want prepared.'}</p>${memoryWizardCta('ad_brief',brief?.id||'')}${brief?`<div class="brand-editor-actions"><button class="btn primary" type="button" onclick="refreshForAdBrief(${chatArg(brief.id)})">${lang==='es'?'Crear imágenes y textos':'Create images and text'}</button><button class="btn" type="button" onclick="chatForAdBrief(${chatArg(brief.id)},${chatArg(lang)})">${lang==='es'?'Pedir cambios al agente':'Ask the agent for changes'}</button></div>`:''}</div><details class="memory-manual-entry" ${brief?'open':''}><summary><span>${lang==='es'?'Prefiero escribir los detalles yo':'I prefer to enter details myself'}<small class="memory-manual-help">${lang==='es'?'Opcional: el agente puede preguntarte todo en el chat.':'Optional: the agent can ask you everything in chat.'}</small></span></summary>${manualForm}</details>`;
}
function advancedMemoryFields(mode,fields){
 if(mode==='general')return `<details class="brand-advanced"><summary>${lang==='es'?'Más detalles, si los quieres agregar':'Optional brand details'}</summary><section class="brand-form-section"><div class="brand-form-grid">${memoryField('category',lang==='es'?'Tipo de negocio':'Category',fields.category,'Belleza, educación, servicios...')}${memoryField('market',lang==='es'?'País o ciudad principal':'Main market',fields.market,'México, Colombia...')}${memoryField('website',lang==='es'?'Página web':'Website',fields.website,'https://...')}${memoryField('personality',lang==='es'?'Cómo se siente tu marca':'Personality',fields.personality,'Elegante, práctica, atrevida...',true,true)}${memoryField('avoid_colors',lang==='es'?'Colores que no quieres':'Colors to avoid',fields.avoid_colors,'')}${memoryField('typography',lang==='es'?'Tipo de letras que te gusta':'Typography style',fields.typography,'')}${memoryField('energy',lang==='es'?'Sensación que debe dar':'Energy level',fields.energy,'Tranquila, alegre, fuerte...')}${memoryField('sales_energy',lang==='es'?'Qué tan directa debe vender':'Sales intensity',fields.sales_energy,'Directa sin promesas falsas',true,true)}${memoryField('words_use',lang==='es'?'Palabras que sí usa tu marca':'Words to use',fields.words_use,'',true,true)}${memoryField('words_avoid',lang==='es'?'Palabras que no quieres usar':'Words to avoid',fields.words_avoid,'',true,true)}${memoryField('authority',lang==='es'?'Pruebas que puedes mostrar':'Allowed proof',fields.authority,'Reseñas o cifras reales...',true,true)}</div></section></details>`;
 return `<details class="brand-advanced"><summary>${lang==='es'?'Más detalles, si los quieres agregar':'Optional product details'}</summary><section class="brand-form-section"><div class="brand-form-grid">${memoryField('not_for',lang==='es'?'Para quién no es':'Who it is not for',fields.not_for,'',true,true)}${memoryField('before_buying',lang==='es'?'Qué piensa antes de comprar':'Before buying thought',fields.before_buying,'',true,true)}${memoryField('after_buying',lang==='es'?'Cómo quiere sentirse después':'After buying feeling',fields.after_buying,'',true,true)}${memoryField('angle_urgency',lang==='es'?'Cómo mostrar que es el momento':'Urgency angle',fields.angle_urgency,'',true,true)}${memoryField('angle_education',lang==='es'?'Qué necesita entender primero':'Educational angle',fields.angle_education,'',true,true)}${memoryField('avoid_phrases',lang==='es'?'Frases que no debe usar':'Phrases to avoid',fields.avoid_phrases,'',true,true)}</div></section></details>`;
}
function renderBrandMemoryModal(){
 const overlay=qs('#brand-memory-overlay');if(!overlay?.classList.contains('open'))return;
 const memory=state.brand_guides||{};const products=memory.products||[];const adBriefs=memory.ad_briefs||[];
 qs('#brand-memory-kicker').textContent=lang==='es'?'El agente recuerda esto':'Manager memory';
 qs('#brand-memory-title').textContent=lang==='es'?'Tu marca, lo que vendes y tus anuncios':'Brand, products, and ads';
 qs('#brand-memory-subtitle').textContent=lang==='es'?'Cuéntale estas cosas al agente para que cree imágenes y textos que sí se parezcan a tu negocio.':'Save how your brand looks, what you sell, and which ad you want to prepare. This helps the agent create relevant images and text.';
 const activeGeneral=brandEditorMode==='general';const activeProduct=brandEditorMode==='product';const activeAdBrief=brandEditorMode==='ad_brief';
 qs('#brand-memory-nav').innerHTML=`<span class="brand-nav-label">${lang==='es'?'Tu marca':'Base'}</span><button class="brand-nav-item ${activeGeneral?'active':''}" type="button" onclick="openBrandMemory('general')"><span><b>${lang==='es'?'Cómo se ve mi marca':'General brand'}</b><small>${memory.general?.saved?(lang==='es'?'Guardado':'Saved'):(lang==='es'?'Completar':'Complete')}</small></span><span class="brand-ready ${memory.general?.saved?'':'draft'}">${memory.general?.saved?'OK':'...'}</span></button><span class="brand-nav-label">${lang==='es'?'Productos':'Products'}</span>${products.map(product=>`<button class="brand-nav-item ${activeProduct&&brandEditorProductId===product.id?'active':''}" type="button" onclick="openBrandMemory('product',${chatArg(product.id)})"><span><b>${escapeHtml(product.name)}</b><small>${product.ready?(lang==='es'?'Listo':'Ready'):(lang==='es'?'Falta detalle':'Needs details')}</small></span><span class="brand-ready ${product.ready?'':'draft'}">${product.ready?'OK':'...'}</span></button>`).join('')}<button class="btn brand-new-product" type="button" onclick="openBrandMemory('product','')">${lang==='es'?'+ Producto':'+ New product'}</button><span class="brand-nav-label">${lang==='es'?'Anuncios':'Ad ideas'}</span>${adBriefs.map(brief=>`<button class="brand-nav-item ${activeAdBrief&&brandEditorProductId===brief.id?'active':''}" type="button" onclick="openBrandMemory('ad_brief',${chatArg(brief.id)})"><span><b>${escapeHtml(brief.name)}</b><small>${escapeHtml(brief.adset_name||brief.campaign_name||brief.base_ad_name||(lang==='es'?'Idea guardada':'Saved idea'))}</small></span><span class="brand-ready ${brief.ready?'':'draft'}">${brief.ready?'OK':'...'}</span></button>`).join('')}<button class="btn brand-new-product" type="button" onclick="openBrandMemory('ad_brief','')">${lang==='es'?'+ Anuncio':'+ Ad idea'}</button>`;
 const selected=brandProductById(brandEditorProductId);
 const selectedBrief=brandAdBriefById(brandEditorProductId);
 const fields=activeGeneral?(memory.general?.fields||{}):(activeProduct?(selected?.fields||{}):(selectedBrief?.fields||{}));
 qs('#brand-memory-editor').innerHTML=activeGeneral?generalMemoryForm(fields):(activeProduct?productMemoryForm(fields,selected):adBriefMemoryForm(fields,selectedBrief));
 if(!activeAdBrief)qs('#brand-memory-editor .brand-form-save')?.insertAdjacentHTML('beforebegin',advancedMemoryFields(activeGeneral?'general':'product',fields));
}
function renderBrandGuides(){
 const box=qs('#brand-guides-panel');if(!box)return;
 const memory=state.brand_guides||{};const products=memory.products||[];const adBriefs=memory.ad_briefs||[];
 const status=memory.general?.saved?(lang==='es'?'Marca guardada':'Brand saved'):(lang==='es'?'Completa tu marca':'Complete your brand');
 box.innerHTML=`<div class="brand-vault-strip"><div class="brand-vault-summary"><span class="brand-vault-mark">AI</span><div><b>${lang==='es'?'Lo que el agente recuerda':'Ad creative memory'}</b><p>${escapeHtml(status)} · ${lang==='es'?`${products.length} producto${products.length===1?'':'s'} · ${adBriefs.length} idea${adBriefs.length===1?'':'s'} de anuncio`:`${products.length} product${products.length===1?'':'s'} · ${adBriefs.length} ad idea${adBriefs.length===1?'':'s'}`}</p>${(products.length||adBriefs.length)?`<div class="brand-vault-pills">${products.slice(0,2).map(product=>`<span class="brand-vault-pill ${product.ready?'ready':''}">${escapeHtml(product.name)}</span>`).join('')}${adBriefs.slice(0,2).map(brief=>`<span class="brand-vault-pill ${brief.ready?'ready':''}">${escapeHtml(brief.name)}</span>`).join('')}</div>`:''}</div></div><div class="brand-vault-actions"><button class="btn primary" type="button" onclick="openBrandMemory('ad_brief','')">${lang==='es'?'Nueva idea':'New idea'}</button><button class="btn" type="button" onclick="openBrandMemory('general')">${lang==='es'?'Mi marca':'Memory'}</button><button class="btn" type="button" onclick="openBrandMemory('product','')">${lang==='es'?'+ Producto':'+ Product'}</button></div></div>`;
 renderBrandMemoryModal();
}
async function saveGeneralMemory(event){
 event.preventDefault();
 const res=await api('/api/brand-guides/general',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(event.target).entries()))});
 state.brand_guides=res.result;toast(lang==='es'?'Memoria de marca guardada':'Brand memory saved');renderCreativeStudio();
}
async function saveProductMemory(event){
 event.preventDefault();
 const res=await api('/api/brand-guides/product',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(event.target).entries()))});
 state.brand_guides=res.result.library;brandEditorMode='product';brandEditorProductId=res.result.product_id;
 toast(lang==='es'?'Ficha del producto guardada':'Product sheet saved');renderCreativeStudio();
}
async function saveAdBriefMemory(event){
 event.preventDefault();
 const res=await api('/api/ad-briefs',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(event.target).entries()))});
 state.brand_guides=res.result.library;brandEditorMode='ad_brief';brandEditorProductId=res.result.ad_brief_id;brandAdBriefProductGuide='';
 toast(lang==='es'?'Idea de anuncio guardada':'Ad idea saved');renderCreativeStudio();
}
function startAdBriefForProduct(productId){
 const product=brandProductById(productId);brandAdBriefProductGuide=product?.guide||'';openBrandMemory('ad_brief','');
}
function chatForProduct(productId,draftLang=''){
 const product=brandProductById(productId);if(!product)return;
 closeBrandMemory();
 const es=(draftLang||uiLang())==='es';
 openChat(es?`Quiero preparar anuncios para ${product.name}. Usa los datos guardados de este producto y pregúntame solo lo que falte antes de proponer imágenes y textos.`:`I want to prepare ads for ${product.name}. Use this product's saved details and ask only for anything missing before proposing images and text.`);
}
function chatForAdBrief(briefId,draftLang=''){
 const brief=brandAdBriefById(briefId);if(!brief)return;
 closeBrandMemory();
 const es=(draftLang||uiLang())==='es';
 openChat(es?`Quiero trabajar en la idea de anuncio ${brief.name}. Usa lo que ya guardé y ayúdame a preparar imágenes y textos. Si falta algo, pregúntame una sola cosa a la vez.`:`I want to work on the ${brief.name} ad idea. Use what I already saved and help me prepare images and text. Ask one question at a time if anything is missing.`);
}
async function refreshForProduct(productId){
 const product=brandProductById(productId);if(!product)return;
 closeBrandMemory();await generateRefresh('',product.guide);
}
async function refreshForAdBrief(briefId){
 const brief=brandAdBriefById(briefId);if(!brief)return;
 closeBrandMemory();await generateRefresh('','',brief.guide);
}
const creativePreviewUrls=new Map();
function creativeStatus(value){
 const labels={dry_run:lang==='es'?'Ideas listas':'Ideas ready',images_ready:lang==='es'?'Imágenes listas':'Images ready',partially_generated:lang==='es'?'Revisar imágenes':'Review images',generation_failed:lang==='es'?'Falló la imagen':'Image failed'};
 return labels[value]||statusText(value);
}
function creativeMissingText(value){
 const raw=String(value||'');
 if(lang!=='es')return raw;
 if(raw.includes('generated image asset'))return 'Falta generar la imagen final';
 if(raw.includes('default_adset_id'))return 'Falta elegir dónde irá este anuncio';
 if(raw.includes('page_id'))return 'Falta página de Facebook';
 if(raw.includes('META_AD_ACCOUNT_ID'))return 'Falta cuenta publicitaria';
 return raw;
}
function demoCreativeText(value){
 if(lang!=='es'||state?.metrics?.source!=='demo')return String(value||'');
 return String(value||'').replaceAll('Brand Awareness Campaign','Campaña para dar a conocer la marca')
  .replaceAll('Q2 Conversion Campaign','Campaña de ventas Q2')
  .replaceAll('Premium product or service','este producto');
}
function creativeStorageNote(asset){
 if(!asset)return '';
 if(asset.saved_for_ad)return `<span class="creative-retention-note saved">${lang==='es'?'Guardada por usarse en anuncio':'Saved because it is used in an ad'}</span>`;
 return `<span class="creative-retention-note">${lang==='es'?'Guardada localmente. Puedes descargarla o limpiar borradores.':'Saved locally. You can download it or clear drafts.'}</span>`;
}
function creativeStorageReminderMarkup(policy){
 const p=policy||{};const cleaned=p.cleanup?.deleted||0;
 return `<div class="creative-retention-card"><span class="creative-retention-icon">↓</span><div><b>${lang==='es'?'Tus imágenes quedan guardadas aquí':'Your images stay saved here'}</b><p>${lang==='es'?`Como un droplet pequeño ya trae espacio suficiente para empezar, no borro tus creativos automáticamente. Descarga las piezas importantes y, si algún día necesitas liberar espacio, limpia solo los borradores. Las imágenes ya elegidas para anuncios se conservan.`:`A small droplet has enough storage to get started, so drafts are not deleted automatically. Download important files, and if you ever need space, clear only draft images. Images chosen for ads are preserved.`}</p><div class="creative-retention-tags"><span>${lang==='es'?`${p.temporary_image_count||0} borradores guardados`:`${p.temporary_image_count||0} saved drafts`}</span><span>${lang==='es'?`${p.saved_ad_image_count||0} piezas de anuncio protegidas`:`${p.saved_ad_image_count||0} protected ad assets`}</span>${cleaned?`<span>${lang==='es'?`${cleaned} borradores limpiados`:`${cleaned} drafts cleared`}</span>`:''}</div><div class="creative-retention-actions"><button class="btn" type="button" onclick="clearCreativeStorage()">${lang==='es'?'Limpiar borradores':'Clear drafts'}</button></div></div></div>`;
}
function creativeVariantMarkup(batch,variant){
 const copy=variant.copy||{};const asset=(variant.assets||[])[0];const prompts=(variant.image_prompts||[]).map(p=>p.aspect_ratio).join(' / ');
 const frame=asset?`<div class="creative-frame"><div class="creative-frame-loading">${lang==='es'?'Cargando vista previa...':'Loading preview...'}</div><img data-preview-url="${escapeHtml(asset.preview_url)}" alt="${escapeHtml(demoCreativeText(copy.headline)||'Creative preview')}" hidden><span class="creative-asset-state">${lang==='es'?'Imagen lista':'Image ready'}</span></div>`:`<div class="creative-frame"><div class="creative-concept-board"><span class="creative-angle">${escapeHtml(demoCreativeText(copy.angle)||'idea')}</span><b>${escapeHtml(demoCreativeText(copy.headline)||'Nueva idea')}</b><div class="creative-ratios">${(variant.image_prompts||[]).map(p=>`<span>${escapeHtml(p.aspect_ratio)}</span>`).join('')}</div></div><span class="creative-asset-state">${variant.generation_errors?.length?(lang==='es'?'No generada':'Not generated'):(lang==='es'?'Idea':'Idea')}</span></div>`;
 const canRender=Boolean(state.config?.creative_studio?.image_generation_ready);const productGuide=batch.brand_memory?.product?.guide||'';const adBrief=batch.brand_memory?.ad_brief?.guide||'';
 const primary=asset?`<button class="btn primary" onclick="stageUpload(${chatArg(batch.manifest_path)},${chatArg(variant.variant_id)},${JSON.stringify((variant.assets||[]).map(a=>a.aspect_ratio))})">${lang==='es'?'Preparar para publicar':'Prepare to publish'}</button>`:canRender?`<button class="btn primary" onclick="generateRefresh(${chatArg(batch.campaign.id)},${chatArg(productGuide)},${chatArg(adBrief)})">${lang==='es'?'Crear imagen final':'Create final image'}</button>`:`<button class="btn" onclick="openChat(${chatArg(lang==='es'?`Convierte la idea ${copy.headline||variant.variant_id} de ${batch.campaign.name} en una imagen final para anuncios. Dime qué necesitas para generarla.`:`Turn the ${copy.headline||variant.variant_id} idea from ${batch.campaign.name} into a final ad image. Tell me what you need to generate it.`)})">${lang==='es'?'Crear imagen':'Create image'}</button>`;
 const download=asset?`<button class="btn" onclick="downloadCreativeAsset(${chatArg(asset.preview_url)},${chatArg(asset.filename||'creative.png')})">${lang==='es'?'Descargar':'Download'}</button>`:'';
 return `<article class="creative-variant">${frame}<div class="creative-variant-body"><span class="creative-angle">${escapeHtml(demoCreativeText(copy.angle)||variant.variant_id)}</span><h4>${escapeHtml(demoCreativeText(copy.headline)||variant.variant_id)}</h4>${asset?creativeStorageNote(asset):''}<p class="creative-copy">${escapeHtml(demoCreativeText(copy.primary_text)||'')}</p><p class="creative-cta">${escapeHtml(demoCreativeText(copy.cta)||'')} ${prompts?` · ${escapeHtml(prompts)}`:''}</p><div class="creative-actions">${primary}${download}<button class="btn ask-btn" onclick="openChat(${chatArg(lang==='es'?`Revisa la idea ${copy.headline||variant.variant_id} para ${batch.campaign.name}. ¿La probarías y qué cambiarías?`:`Review the ${copy.headline||variant.variant_id} idea for ${batch.campaign.name}. Would you test it and what would you change?`)})">${lang==='es'?'Preguntar':'Ask'}</button></div></div></article>`;
}
function renderCreativeStudio(){
 renderBrandGuides();
 const studio=state.config.creative_studio||{};const batches=state.creative_refreshes||[];const uploads=state.creative_uploads||[];
 const variants=batches.reduce((count,batch)=>count+(batch.variants||[]).length,0);const imageCount=batches.reduce((count,batch)=>count+(batch.variants||[]).reduce((subtotal,variant)=>subtotal+(variant.assets||[]).length,0),0);
 qs('#creative-studio-kicker').textContent=lang==='es'?'Ideas para anuncios':'Ad ideas';
 qs('#creative-studio-title').textContent=lang==='es'?'Crea tus anuncios':'Create your ads';
 qs('#creative-studio-description').textContent=lang==='es'?'Cuéntale al agente qué quieres vender y cómo quieres mostrarlo. Te ayudará a preparar imágenes y textos para tus anuncios.':'Tell the agent what you want to sell and how you want to show it. It will help prepare images and text for your ads.';
 qs('#creative-agent-cta').textContent=lang==='es'?'Crear con el agente':'Create with the agent';
 qs('#creative-refresh-cta').textContent=lang==='es'?'Mejorar un anuncio actual':'Improve an existing ad';
 qs('#creative-library-kicker').textContent=lang==='es'?'Ideas creadas':'Agent ideas';
 qs('#creative-library-title').textContent=lang==='es'?'Creativos para revisar':'Images and text to review';
 qs('#creative-upload-kicker').textContent=lang==='es'?'Antes de publicar':'Ready for Meta';
 qs('#creative-upload-title').textContent=lang==='es'?'Anuncios que puedes aprobar':'Ads you can approve';
 const renderer=studio.image_generation_ready?(lang==='es'?'Puede crear imágenes':'Image generator active'):(lang==='es'?'Crear imágenes aún no está activado':'Image generation not active');
 qs('#creative-studio-pulse').innerHTML=`<div class="creative-pulse-stat"><b>${variants}</b><span>${lang==='es'?'Ideas':'Ideas'}</span></div><div class="creative-pulse-stat"><b>${imageCount}</b><span>${lang==='es'?'Imágenes listas':'Final images'}</span></div><div class="creative-pulse-stat"><b>${uploads.length}</b><span>${lang==='es'?'Por aprobar':'Staged uploads'}</span></div><p class="notice">${escapeHtml(renderer)}</p>${creativeStorageReminderMarkup(studio.asset_policy)}`;
 qs('#creative-list').innerHTML=batches.length?batches.map(batch=>`<section class="creative-batch"><div class="creative-batch-head"><div><h4>${escapeHtml(demoCreativeText(batch.campaign?.name||'Campaña'))}${batch.brand_memory?.product?.name?`<span class="creative-batch-product">${escapeHtml(batch.brand_memory.product.name)}</span>`:''}${batch.brand_memory?.ad_brief?.name?`<span class="creative-batch-product">${escapeHtml(batch.brand_memory.ad_brief.name)}</span>`:''}</h4><p class="creative-batch-meta">${creativeStatus(batch.status)} · ${new Date(batch.created_at).toLocaleString()}</p></div><span class="badge ${batch.has_generated_images?'ok':'warn'}">${batch.has_generated_images?(lang==='es'?'Vista previa':'Preview'):(lang==='es'?'Sin imagen':'No image')}</span></div><div class="creative-variants">${(batch.variants||[]).map(variant=>creativeVariantMarkup(batch,variant)).join('')}</div></section>`).join(''):`<div class="creative-empty"><div><h3>${lang==='es'?'Todavía no has creado ideas de anuncios':'No ad ideas yet'}</h3><p>${lang==='es'?'Habla con el agente sobre lo que quieres anunciar. Preparará ideas de imágenes y textos para que elijas la que más te guste.':'Talk to the agent about what you want to advertise. It will prepare image and text ideas for you to choose from.'}</p><button class="btn primary" onclick="openBrandMemory('ad_brief','')">${lang==='es'?'Crear una idea de anuncio':'Create an ad idea'}</button></div></div>`;
 qs('#upload-list').innerHTML=uploads.length?`<div class="creative-upload-grid">${uploads.map(upload=>`<article class="creative-upload-card"><h4>${escapeHtml(demoCreativeText(upload.campaign?.name||'Campaña'))} · ${escapeHtml(upload.variant_id||'')}</h4><span class="badge ${upload.status==='ready_for_approval'?'ok':'warn'}">${upload.status==='ready_for_approval'?(lang==='es'?'Espera tu aprobación':'In approval'):(lang==='es'?'Falta completar':'Needs work')}</span><p>${upload.status==='ready_for_approval'?(lang==='es'?'Revisa esta imagen. Solo se creará el anuncio en Meta cuando lo apruebes.':'This proposal waits for your confirmation before creating the Meta ad.'):(lang==='es'?'Completa lo que falta antes de enviarla a Meta.':'Complete missing items before sending it to Meta.')}</p>${upload.missing_requirements?.length?`<div class="creative-blockers">${upload.missing_requirements.map(item=>`· ${escapeHtml(creativeMissingText(item))}`).join('<br>')}</div>`:''}</article>`).join('')}</div>`:`<p class="notice">${lang==='es'?'Cuando prepares una imagen para publicar, aparecerá aquí para que la apruebes.':'Once you choose a finished image, preparation for approval will appear here.'}</p>`;
 hydrateCreativePreviews();
}
async function hydrateCreativePreviews(){
 const images=[...document.querySelectorAll('#creative-list img[data-preview-url]')];
 for(const image of images){
  const path=image.dataset.previewUrl;if(!path)continue;
  try{
   if(!creativePreviewUrls.has(path)){const response=await fetchProtectedFile(path);creativePreviewUrls.set(path,URL.createObjectURL(await response.blob()))}
   image.src=creativePreviewUrls.get(path);image.hidden=false;image.previousElementSibling?.remove();
  }catch(err){const loading=image.previousElementSibling;if(loading)loading.textContent=lang==='es'?'Vista previa protegida':'Protected preview'}
 }
}
async function downloadCreativeAsset(path,filename){
 try{
  const response=await fetchProtectedFile(path);
  const blob=await response.blob();
  const url=URL.createObjectURL(blob);
  const link=document.createElement('a');
  link.href=url;link.download=filename||'meta-ads-creative.png';
  document.body.appendChild(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
  toast(lang==='es'?'Imagen descargada. Guárdala si quieres conservarla.':'Image downloaded. Keep it if you want to save it.');
 }catch(err){toast(lang==='es'?'No pude descargar esa imagen.':'Could not download that image.')}
}
function clearCreativeStorage(){
 const p=state.config?.creative_studio?.asset_policy||{};const count=p.temporary_image_count||0;
 const box=qs('#confirm-overlay');
 box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Limpiar borradores creativos':'Clear creative drafts'}</h2><p>${lang==='es'?`Esto borrará ${count} imagen${count===1?'':'es'} generada${count===1?'':'s'} que todavía no elegiste para anuncios. No borra piezas ya preparadas para publicar ni anuncios activos en Meta.`:`This deletes ${count} generated draft image${count===1?'':'s'} that you have not chosen for ads yet. It does not delete images prepared for publishing or active Meta ads.`}</p><div class="confirm-actions"><button class="btn" type="button" onclick="closeConfirm()">${lang==='es'?'Cancelar':'Cancel'}</button><button class="btn primary" type="button" onclick="confirmClearCreativeStorage()">${lang==='es'?'Limpiar borradores':'Clear drafts'}</button></div></div>`;
 box.classList.add('open');
}
async function confirmClearCreativeStorage(){
 try{
  closeConfirm();
  const res=await api('/api/creative-storage/clear',{method:'POST',body:'{}'});
  toast(lang==='es'?`${res.result?.deleted||0} borrador${res.result?.deleted===1?'':'es'} limpiado${res.result?.deleted===1?'':'s'}`:`${res.result?.deleted||0} draft image${res.result?.deleted===1?'':'s'} cleared`);
  await load();
 }catch(err){toast(lang==='es'?'No pude limpiar esos borradores.':'Could not clear those drafts.')}
}
function approvalNote(p){
 if(p.type==='create_campaign'&&p.payload?.final_status==='ACTIVE')return lang==='es'?'Si apruebas, la campaña se encenderá y podrá empezar a gastar el presupuesto que elegiste.':'If you approve, the campaign will turn on and may start spending the budget you chose.';
 if(p.type==='create_campaign'||p.type==='creative_upload')return lang==='es'?'Si apruebas, quedará lista pero apagada. No mostrará anuncios ni gastará dinero hasta que decidas encenderla.':'If you approve, it will be ready but turned off. It will not show ads or spend money until you turn it on.';
 if(p.type==='pause_campaign')return lang==='es'?'Esto apagará una campaña que ya está mostrando anuncios. Revisa bien antes de aprobar.':'This will turn off a campaign that is already showing ads. Check carefully before approving.';
 return '';
}
function guardrailText(reason){
 const es={supervised_mode:'Estás en Con supervisión, así que el agente prepara la acción y espera tu sí.',budget_over_autopilot_limit:'El cambio de presupuesto supera tus reglas de piloto automático.',resume_requires_approval:'Reactivar campañas siempre pide aprobación.',new_campaign_requires_approval:'Las campañas nuevas siempre pasan por aprobación.',new_campaigns_always_require_approval:'Las campañas nuevas siempre pasan por aprobación.',creative_requires_approval:'Los anuncios o creativos nuevos siempre pasan por aprobación.',pause_spend_over_limit:'La campaña ya gastó más de tu límite para pausar sin pedir permiso.'};
 const en={supervised_mode:'You are in Supervised mode, so the agent prepares the action and waits for your yes.',budget_over_autopilot_limit:'The budget change is above your autopilot rules.',resume_requires_approval:'Resuming campaigns always asks for approval.',new_campaign_requires_approval:'New campaigns always go through approval.',new_campaigns_always_require_approval:'New campaigns always go through approval.',creative_requires_approval:'New ads or creatives always go through approval.',pause_spend_over_limit:'The campaign already spent more than your no-approval pause limit.'};
 return (lang==='es'?es:en)[reason]||String(reason||'');
}
function approvalMeta(p){
 const payload=p.payload||{};const requested=payload.requested||{};const type=p.type||'';
 const name=payload.name||payload.campaign_name||requested.campaign||payload.campaign_id||payload.upload_id||type;
 const created=new Date(p.created_at||Date.now()).toLocaleString();
 const base={name,created,severity:'medium',riskLabel:lang==='es'?'Revisar':'Review',title:actionName(type),requested:lang==='es'?'El agente preparó una acción para revisar.':'The agent prepared an action for review.',reason:guardrailText(payload.guardrail_reason)||approvalNote(p)||'',outcome:approvalNote(p)||'',risk:lang==='es'?'Revisa que esta acción tenga sentido antes de aprobar.':'Check that this action makes sense before approving.',facts:[]};
 if(type==='budget_change'){
  const current=payload.current_budget??payload.current??payload.recommended_budget;const next=payload.new_budget??payload.recommended_budget;const change=payload.change_pct;
  base.title=lang==='es'?'Cambiar presupuesto':'Change budget';
  base.requested=lang==='es'?`Ajustar el presupuesto diario de ${name}.`:`Adjust daily budget for ${name}.`;
  base.reason=base.reason|| (lang==='es'?'El cambio necesita tu aprobación por tus reglas.':'Your rules require approval for this change.');
  base.outcome=lang==='es'?`Pasará de ${fmtMoney(current)} a ${fmtMoney(next)} por día.`:`It will move from ${fmtMoney(current)} to ${fmtMoney(next)} per day.`;
  base.risk=lang==='es'?'Subir presupuesto puede acelerar gasto; bajarlo puede frenar aprendizaje o ventas.':'Increasing budget can accelerate spend; lowering it can slow learning or sales.';
  base.facts=[['Actual',fmtMoney(current)],['Nuevo',fmtMoney(next)]];
  if(change!==undefined)base.facts.push([lang==='es'?'Cambio':'Change',`${change}%`]);
 }else if(type==='pause_campaign'){
  base.title=lang==='es'?'Pausar campaña':'Pause campaign';base.severity='high';base.riskLabel=lang==='es'?'Alto':'High';
  base.requested=lang==='es'?`Pausar ${name}.`:`Pause ${name}.`;
  base.outcome=lang==='es'?'La campaña dejará de mostrar anuncios.':'The campaign will stop showing ads.';
  base.risk=lang==='es'?'Puede cortar gasto débil, pero también puede detener ventas si la lectura está incompleta.':'It can stop weak spend, but it can also stop sales if the read is incomplete.';
  base.facts=[[lang==='es'?'Gasto':'Spend',fmtMoney(payload.spend||0)]];
 }else if(type==='resume_campaign'){
  base.title=lang==='es'?'Reactivar campaña':'Resume campaign';base.severity='medium';base.riskLabel=lang==='es'?'Medio':'Medium';
  base.requested=lang==='es'?`Reactivar ${name}.`:`Resume ${name}.`;
  base.outcome=lang==='es'?'La campaña podrá volver a mostrar anuncios y gastar presupuesto.':'The campaign may show ads and spend budget again.';
  base.risk=lang==='es'?'Reactivar puede volver a gastar; confirma que el problema anterior ya fue corregido.':'Resuming can spend again; confirm the previous issue is fixed.';
 }else if(type==='create_campaign'){
  const active=payload.final_status==='ACTIVE';
  base.title=active?(lang==='es'?'Crear campaña activa':'Create active campaign'):(lang==='es'?'Crear campaña lista':'Create ready campaign');
  base.severity=active?'high':'medium';base.riskLabel=active?(lang==='es'?'Puede gastar':'Can spend'):(lang==='es'?'Preparada':'Prepared');
  base.requested=lang==='es'?`Crear ${name}.`:`Create ${name}.`;
  base.outcome=active?(lang==='es'?'Al aprobar, quedará activa y podrá empezar a gastar el presupuesto elegido.':'If approved, it will be active and may start spending the selected budget.'):(lang==='es'?'Al aprobar, se crea lista pero apagada. No gastará hasta que la enciendas.':'If approved, it is created ready but off. It will not spend until turned on.');
  base.risk=active?(lang==='es'?'Es una luz verde real para inversión. Revisa presupuesto, destino, imagen y mensaje.':'This is a real green light for spend. Review budget, destination, image, and message.'):(lang==='es'?'Riesgo bajo de gasto inmediato, pero revisa que la estructura esté correcta.':'Low immediate spend risk, but check that the structure is right.');
  base.facts=[[lang==='es'?'Presupuesto':'Budget',fmtMoney(requested.daily_budget||0)],[lang==='es'?'Estado final':'Final status',active?'ACTIVE':'PAUSED']];
 }else if(type==='creative_upload'){
  base.title=lang==='es'?'Publicar creativo':'Publish creative';base.severity='medium';base.riskLabel=lang==='es'?'Creativo':'Creative';
  base.requested=lang==='es'?`Preparar el anuncio ${payload.variant_id||''} para ${name}.`:`Prepare ad ${payload.variant_id||''} for ${name}.`;
  base.outcome=lang==='es'?'Creará o preparará piezas en Meta solo después de tu aprobación.':'It will create or prepare Meta assets only after approval.';
  base.risk=lang==='es'?'Revisa que imagen, texto, destino y página sean correctos antes de aprobar.':'Review image, text, destination, and Page before approving.';
  base.facts=[[lang==='es'?'Variante':'Variant',payload.variant_id||'-']];
 }
 return base;
}
function approvalAskDraft(p,meta){
 const safeName=meta.name||actionName(p.type);
 if(lang==='es')return `Explícame esta aprobación antes de que decida: ${meta.title} para ${safeName}. Quiero entender qué pidió el agente, por qué lo sugiere, qué riesgo tiene, qué pasa si apruebo y si tú lo aprobarías ahora o esperarías.`;
 return `Explain this approval before I decide: ${meta.title} for ${safeName}. I want to understand what the agent requested, why, the risk, what happens if I approve, and whether you would approve now or wait.`;
}
function approvalCard(p){
 const meta=approvalMeta(p);const riskClass=meta.severity||'medium';const facts=meta.facts||[];
 return `<article class="approval-card ${riskClass}"><div class="approval-top"><div class="approval-icon">AI</div><div class="approval-title"><b>${escapeHtml(meta.title)}</b><span>${escapeHtml(meta.name)} · ${escapeHtml(meta.created)}</span></div><span class="approval-risk ${riskClass}">${escapeHtml(meta.riskLabel)}</span></div><div class="approval-section"><b>${lang==='es'?'Qué pidió el agente':'What the agent requested'}</b><p>${escapeHtml(meta.requested)}</p></div><div class="approval-section"><b>${lang==='es'?'Por qué está esperando tu sí':'Why it is waiting for your yes'}</b><p>${escapeHtml(meta.reason|| (lang==='es'?'Tus reglas piden aprobación para esta acción.':'Your rules require approval for this action.'))}</p></div><div class="approval-section"><b>${lang==='es'?'Qué pasa si apruebas':'What happens if you approve'}</b><p>${escapeHtml(meta.outcome)}</p></div><div class="approval-section"><b>${lang==='es'?'Riesgo a revisar':'Risk to review'}</b><p>${escapeHtml(meta.risk)}</p></div>${facts.length?`<div class="approval-facts">${facts.map(([label,value])=>`<div class="approval-fact"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join('')}</div>`:''}<div class="approval-actions"><button class="btn ask-btn" onclick="openChat(${chatArg(approvalAskDraft(p,meta))})">${lang==='es'?'Preguntar antes':'Ask first'}</button><button class="btn primary" onclick="approvePending(${chatArg(p.id)})">${t('approve')}</button></div></article>`;
}
function statusLabel(s){return s==='ok'?t('ok'):s==='blocked'?t('blocked'):t('check')}
function setupItem(key){for(const sec of state.setup.sections){const found=sec.items.find(i=>i.key===key);if(found)return found}return {status:'blocked',detail:''}}
function stepCopy(key){
	 const en={
	  title:'Initial setup',subtitle:'Connect the essentials. The deep business questions happen later through the agent.',progress:'ready',done:'Done',next:'Next',review:'Review',
	  helper:'Help',
	  website:['Paste your website and social media','I scan your public links so the agent has a first map of your products and services.',''],
	  context:['Business interview','The agent asks this later through Telegram, one question at a time.',''],
	  strategy:['First plan','The agent prepares this after the interview.',''],
	  license:['Add your license','Paste the one code you received from us.',''],
	  chatgpt:['Connect ChatGPT','Choose ChatGPT/Codex or an API model like MiniMax M3.',''],
	  telegram:['Finish with Telegram','Recommended: talk to the manager from your phone. After this, the agent can ask the business questions there.',''],
	  meta:['Connect my Facebook account','Secure step: use your own Facebook/Meta connection and access key.',''],
	  account:['Pick one account','Choose the ad account this tool should help with.',''],
	  destination:['Pick where ads go','Add the Facebook Page, Instagram, and website.',''],
	  insights:['Read real results','I check your real numbers and do not change anything yet.',''],
	  dryrun:['Review with supervision','The agent prepares suggestions and waits for your yes.',''],
	  approval:['Approve one change','Check one suggested change before anything real happens.',''],
	  live:['Keep supervision on','Best for the first run. You can turn autopilot on later.',''],
	  smoke:['Tiny live test later','Use this only when you are ready for a very small real change.',''],
	  password:['Create your password','Choose a password only you know.',''],
	  guide:['Quick guide','Read the short cards before entering the dashboard.','']
	 };
	 const es={
	  title:'Configuración inicial',subtitle:'Conecta lo esencial. La entrevista profunda la hace el agente después.',progress:'listo',done:'Listo',next:'Siguiente',review:'Revisar',
	  helper:'Ayuda',
	  website:['Pega tu web y redes','Escaneo tus links públicos para que el agente tenga un primer mapa de productos y servicios.',''],
	  context:['Entrevista del negocio','El agente la hace después por Telegram, una pregunta a la vez.',''],
	  strategy:['Primer plan','El agente lo prepara después de la entrevista.',''],
	  license:['Pega tu licencia','Pega el único código que recibiste de nosotros.',''],
	  chatgpt:['Conecta ChatGPT','Elige ChatGPT/Codex o un modelo API como MiniMax M3.',''],
	  telegram:['Termina con Telegram','Recomendado: habla con el manager desde tu celular. Después de esto, el agente puede hacerte la entrevista del negocio allí.',''],
	  meta:['Conectar mi cuenta de Facebook','Paso seguro: usa tu propia conexión de Facebook/Meta y tu propia clave.',''],
	  account:['Elige una cuenta','Escoge la cuenta de anuncios que quieres usar.',''],
	  destination:['Elige dónde van los anuncios','Agrega la página de Facebook, Instagram y la web.',''],
	  insights:['Lee datos reales','Miro tus números reales y todavía no cambio nada.',''],
	  dryrun:['Revisar con supervisión','El agente prepara sugerencias y espera tu sí.',''],
	  approval:['Aprueba un cambio','Revisa un cambio sugerido antes de que pase algo real.',''],
	  live:['Deja la supervisión activa','Mejor para la primera vez. Luego puedes activar piloto automático.',''],
	  smoke:['Prueba pequeña después','Úsalo solo cuando quieras hacer un cambio real muy pequeño.',''],
	  password:['Crea tu contraseña','Elige una contraseña que solo tú conozcas.',''],
	  guide:['Guía rápida','Lee las tarjetas cortas antes de entrar al dashboard.','']
	 };
 return (lang==='es'?es:en)[key];
}
function copyCommand(value){navigator.clipboard?.writeText(value).then(()=>toast(t('copied'))).catch(()=>toast(value))}
function onboardingSteps(){
 const setup=state.setup, summary=setup.summary;
 const profile=state.business_profile||{};
 const websiteOk=Boolean(profile.website_url||(profile.social_links&&profile.social_links.length)||profile.telegram_onboarding_requested_at||profile.website_skipped);
 const licenseOk=Boolean(summary.license_ready);
 const passwordOk=Boolean(state.config.dashboard_password_set);
 const model=state.config.agent_model||{};
 const brain=model.brain_provider||'openai_codex';
 const apiBrainOk=['openai_api','minimax','custom_api'].includes(brain)&&model.api_key_set&&Boolean(model.base_url)&&Boolean(model.model);
 const chatgptOk=(setupItem('hermes_runtime').status==='ok'&&setupItem('hermes_auth').status==='ok')||apiBrainOk;
 const telegram=state.config.telegram_agent||{};
 const telegramOk=Boolean(telegram.enabled&&telegram.bot_configured&&telegram.chat_id);
 const tokenOk=setupItem('access_token').status==='ok';
 const accountOk=setupItem('ad_account').status==='ok';
 const destinationOk=['page_id','landing_url'].every(k=>setupItem(k).status==='ok');
 const socialOk=setupItem('social_cli').status==='ok';
 const dryrunOk=setupItem('daily_report').status==='ok';
 const approvalOk=state.pending.length>0||state.actions.some(a=>String(a.status)==='pending_approval'||String(a.status)==='completed');
 const insightsOk=state.metrics?.source==='meta_graph'||state.actions.some(a=>a.type==='live_insights_pull'||a.type==='daily_agent_run')||dryrunOk;
 const steps=[];
 if(!passwordOk)steps.push({id:'password',status:'blocked'});
 if(!licenseOk)steps.push({id:'license',status:'blocked'});
 steps.push(
	  {id:'chatgpt',status:chatgptOk?'ok':'warn'},
	  {id:'telegram',status:telegramOk?'ok':'warn'},
	  {id:'meta',status:tokenOk?'ok':(socialOk?'warn':'blocked')},
	  {id:'account',status:accountOk?'ok':'blocked'},
	  {id:'destination',status:destinationOk?'ok':'blocked'},
	  {id:'website',status:websiteOk?'ok':'warn'}
	 );
 return steps;
	}
function renderOnboarding(){
 const doneState=state.onboarding||{};
 if(doneState.completed){
  const when=doneState.completed_at?new Date(doneState.completed_at).toLocaleString():'';
  qs('#onboarding-wizard').innerHTML=`<div class="onboarding"><div class="next-step"><div><b>${lang==='es'?'Configuración inicial terminada':'Initial setup complete'}</b><p>${lang==='es'?'La guía inicial ya fue completada en este equipo. Puedes volver a abrirla cuando necesites cambiar algo.':'The initial guide has already been completed on this device. You can open it again whenever you need to change something.'}${when?` ${when}`:''}</p></div><button class="btn" onclick="resetOnboarding()">${lang==='es'?'Revisar configuración inicial':'Run initial setup again'}</button></div></div>`;
  return;
 }
 const labels=stepCopy('title'); const sub=stepCopy('subtitle'); const progress=stepCopy('progress');
 const steps=onboardingSteps(); const done=steps.filter(s=>s.status==='ok').length;
 const labelFor=s=>s.status==='ok'?stepCopy('done'):(s.status==='blocked'?stepCopy('next'):stepCopy('review'));
 const next=steps.find(s=>s.status!=='ok')||steps[steps.length-1]; const nextCopy=stepCopy(next.id);
 qs('#onboarding-wizard').innerHTML=`<div class="onboarding"><div class="onboarding-head"><div><h3>${labels}</h3><p>${sub}</p></div><div class="progress"><b>${done}/${steps.length}</b><span>${progress}</span></div></div><div class="next-step"><div><b>${lang==='es'?'Siguiente':'Next'}: ${nextCopy[0]}</b><p>${nextCopy[1]}</p></div>${nextCopy[2]?`<button class="btn copy-btn" onclick="copyCommand(${JSON.stringify(nextCopy[2]).replaceAll('"','&quot;')})">${t('copy_command')}</button>`:''}</div><div class="step-list">${steps.map((s,i)=>{const c=stepCopy(s.id);return `<div class="setup-step ${s.status}"><div class="step-num">${i+1}</div><div class="step-main"><b>${c[0]}</b><p>${c[1]}</p>${c[2]?`<details class="helper-command"><summary>${stepCopy('helper')}</summary><span class="step-command">${c[2]}</span></details>`:''}</div><div class="step-badge">${labelFor(s)}</div></div>`}).join('')}</div><div class="mode-actions" style="margin-top:10px"><button class="btn ask-btn" onclick="openChat(lang==='es'?'Revisa mi configuración. Explícame el siguiente paso con palabras muy simples.':'Review my setup. Explain the next step in very simple words.')">${t('ask_agent')}</button><button class="btn primary" onclick="completeOnboarding()">${lang==='es'?'Terminar configuración':'Finish setup'}</button></div></div>`;
}
function onboardingFormFor(stepId){
	 const v=state.config.setup_values||{};
 if(stepId==='website')return websiteScanGuide();
 if(stepId==='context')return businessContextGuide();
 if(stepId==='strategy')return initialStrategyGuide();
	 if(stepId==='license')return `<form class="onboarding-mini two" onsubmit="saveOnboardingSetupConfig(event)"><label>${t('license_key')}<input name="license_key" placeholder="MAO-..."></label><label>${t('buyer_email')}<input name="license_buyer_email" value="${escapeHtml(v.license_buyer_email||'')}" placeholder="buyer@email.com"></label><div class="onboarding-step-actions"><button class="btn primary" type="submit">${t('save_setup')}</button><button class="btn" type="button" onclick="activateLicense()">${t('license_activate')}</button></div></form>`;
 if(stepId==='chatgpt')return chatGptConnectMarkup(true);
 if(stepId==='telegram')return telegramOnboardingGuide();
 if(stepId==='meta')return metaConnectionGuide();
 if(stepId==='account')return accountPickerGuide();
 if(stepId==='destination')return destinationPickerGuide();
 if(stepId==='password')return `<form class="unlock-form" onsubmit="setDashboardPasswordFromOnboarding(event)"><label>${t('dashboard_password')}<input id="new-dashboard-password" type="password" autocomplete="new-password" minlength="8" placeholder="${lang==='es'?'Crea una contraseña segura':'Create a secure password'}"></label><label>${lang==='es'?'Repetir contraseña':'Repeat password'}<input id="confirm-dashboard-password" type="password" autocomplete="new-password" minlength="8" placeholder="${lang==='es'?'Escríbela otra vez':'Type it again'}"></label><label><input id="new-dashboard-remember" type="checkbox" checked> ${t('remember_device')}</label><div class="unlock-error" id="dashboard-password-error"></div><button class="btn primary" type="submit">${lang==='es'?'Guardar mi contraseña':'Save my password'}</button></form>`;
	 return passiveStepGuide(stepId);
	}
function websiteScanGuide(){
 const p=state.business_profile||{};
 const links=[p.website_url,...(p.social_links||[])].filter(Boolean).filter((item,index,arr)=>arr.indexOf(item)===index).join('\n');
 const business=p.business_type||p.business_short||'';
 return `<div class="setup-guide private-connection business-start-shell"><section class="guide-hero business-hero compact-business-scan"><div class="guide-main"><span class="guide-eyebrow">${lang==='es'?'Escaneo rápido':'Quick scan'}</span><h3>${lang==='es'?'Pega tu web y redes':'Paste your website and social media'}</h3><p>${lang==='es'?'El agente las revisa ahora para tener una primera idea de tus productos y servicios. Después seguirá la entrevista por Telegram, con calma y una pregunta a la vez.':'The agent scans them now to get a first idea of your products and services. The full interview continues later through Telegram, one question at a time.'}</p><form class="onboarding-mini business-start-form" onsubmit="saveBusinessLinks(event)"><label>${lang==='es'?'Web, Instagram, Facebook, TikTok o tienda':'Website, Instagram, Facebook, TikTok, or store'}<textarea name="links" rows="5" placeholder="${lang==='es'?'Pega un link por línea. Ej:\\nhttps://tumarca.com\\nhttps://instagram.com/tumarca':'Paste one link per line. Ex:\\nhttps://yourbrand.com\\nhttps://instagram.com/yourbrand'}">${escapeHtml(links)}</textarea></label><label>${lang==='es'?'Qué vendes, en pocas palabras':'What you sell, in a few words'}<input name="business_type" value="${escapeHtml(business)}" placeholder="${lang==='es'?'Ej: curso de uñas, clínica dental, tienda de ropa':'Ex: nail course, dental clinic, clothing store'}"></label><div class="onboarding-step-actions"><button class="btn primary" type="submit">${lang==='es'?'Guardar y escanear ahora':'Save and scan now'}</button><button class="btn" type="button" onclick="skipWebsiteScan()">${lang==='es'?'No tengo links ahora':'I do not have links now'}</button></div></form></div><aside class="guide-checklist"><b>${lang==='es'?'Qué pasa después':'What happens next'}</b><ol><li>${lang==='es'?'El agente revisa lo público y guarda una primera lectura.':'The agent reads what is public and saves a first view.'}</li><li>${lang==='es'?'Por Telegram te preguntará lo que falte.':'Through Telegram it asks what is missing.'}</li><li>${lang==='es'?'Lo aprendido queda guardado para campañas y creativos.':'What it learns is saved for campaigns and ads.'}</li></ol></aside></section><div id="business-scan-results" class="setup-guide">${businessProfileCard()}</div></div>`;
}
function businessQuestionValue(key,p){
 if(key==='main_offer')return p.main_offer||p.offer||'';
 if(key==='ideal_customer')return p.ideal_customer||p.audience||'';
 if(key==='sales_channel')return p.sales_channel||p.channel||'';
 if(key==='current_ads')return p.current_ads||p.ad_results||'';
 if(key==='what_to_improve')return p.what_to_improve||'';
 if(key==='success_goal')return p.success_goal||'';
 if(key==='budget_comfort')return p.budget_comfort||'';
 if(key==='brand_tone')return p.brand_tone||'';
 return p[key]||'';
}
function businessContextQuestions(){
 const p=state.business_profile||{};
 const custom=Array.isArray(p.onboarding_questions)&&p.onboarding_questions.length?p.onboarding_questions:[];
 if(custom.length){
  return custom.slice(0,6).map((q)=>({key:q.key,label:q.label,help:q.help,placeholder:q.placeholder||'',value:businessQuestionValue(q.key,p)}));
 }
 const hasWebsite=Boolean(p.website_url);
 const stageSuggestion=p.current_stage|| (hasWebsite?(lang==='es'?'Tengo una web lista y quiero un plan claro.':'I have a website ready and want a clear plan.'):'');
 const improvementSuggestion=p.what_to_improve|| (lang==='es'?'Entender qué hacer primero y no adivinar.':'Know what to do first without guessing.');
 return [
  {key:'main_offer',label:lang==='es'?'¿Qué vendes?':'What do you sell?',help:lang==='es'?'Una frase corta.':'One short sentence.',placeholder:lang==='es'?'Ej: un curso, una tienda, un servicio...':'Ex: a course, a store, a service...',value:businessQuestionValue('main_offer',p)},
  {key:'ideal_customer',label:lang==='es'?'¿Quién compra?':'Who buys?',help:lang==='es'?'La persona que más quieres atraer.':'The person you most want to attract.',placeholder:lang==='es'?'Ej: mamás, dueños de negocio, parejas...':'Ex: moms, business owners, couples...',value:businessQuestionValue('ideal_customer',p)},
  {key:'sales_channel',label:lang==='es'?'¿Dónde vendes?':'Where do you sell?',help:lang==='es'?'Web, WhatsApp, Instagram, tienda física o llamada.':'Website, WhatsApp, Instagram, store, or call.',placeholder:lang==='es'?'Ej: WhatsApp y mi web.':'Ex: WhatsApp and my website.',value:businessQuestionValue('sales_channel',p)},
  {key:'current_stage',label:lang==='es'?'¿En qué punto estás?':'Where are you now?',help:lang==='es'?'Empiezas, ya vendes o ya tienes anuncios.':'Starting, already selling, or already running ads.',placeholder:lang==='es'?'Ej: Ya vendo, pero cada compra me cuesta más.':'Ex: I already sell, but each purchase costs more.',value:stageSuggestion},
  {key:'what_to_improve',label:lang==='es'?'¿Qué quieres mejorar?':'What do you want to improve?',help:lang==='es'?'Qué te gustaría arreglar primero.':'What you want to fix first.',placeholder:lang==='es'?'Ej: bajar el costo de cada compra, entender anuncios, vender más.':'Ex: lower the cost per purchase, understand ads, sell more.',value:improvementSuggestion},
  {key:'success_goal',label:lang==='es'?'¿Cómo se ve una victoria?':'What is a win?',help:lang==='es'?'Algo claro para los próximos 30 días.':'Something clear for the next 30 days.',placeholder:lang==='es'?'Ej: vender 20 más, bajar costo, tener más leads.':'Ex: sell 20 more, lower cost, get more leads.',value:businessQuestionValue('success_goal',p)}
 ];
}
function businessContextGuide(){
 const p=state.business_profile||{};
 const questions=businessContextQuestions();
 businessContextQuestionIndex=Math.max(0,Math.min(businessContextQuestionIndex,questions.length-1));
 const q=questions[businessContextQuestionIndex];
 const sourceNote=p.agent_scan_status==='agent_enriched'
  ? (lang==='es'?'Leí tu web y dejé una sugerencia.':'I read your site and made a suggestion.')
  : (p.website_url?(lang==='es'?'Tomé tu web como guía. Puedes cambiar todo.':'I used your website as a guide. You can change anything.'):(lang==='es'?'Sin web no pasa nada. Te haré preguntas cortas.':'No website is fine. I will ask short questions.'));
 const isLast=businessContextQuestionIndex>=questions.length-1;
 const progress=`${businessContextQuestionIndex+1}/${questions.length}`;
 const draft=lang==='es'?`Ayúdame a responder esta pregunta con palabras simples: "${q.label}". Lo que tengo ahora es: "${q.value||'vacío'}". Si falta algo, hazme una sola pregunta.`:`Help me answer this question in simple words: "${q.label}". Current answer: "${q.value||'empty'}". If something is missing, ask one question.`;
 return `<div class="setup-guide private-connection business-question-shell"><section class="guide-hero business-hero compact-business-context"><div class="guide-main"><span class="guide-eyebrow">${lang==='es'?'Preguntas del negocio':'Business questions'}</span><h3>${lang==='es'?'Una pregunta a la vez':'One question at a time'}</h3><p>${sourceNote}</p></div><div class="business-question-progress"><b>${progress}</b><span>${lang==='es'?'pregunta':'question'}</span></div></section><form class="business-question-card" onsubmit="saveBusinessContextQuestion(event)"><input type="hidden" name="field" value="${escapeHtml(q.key)}"><div class="business-question-label"><span>${progress}</span><h3>${escapeHtml(q.label)}</h3><p>${escapeHtml(q.help)}</p></div><textarea name="answer" rows="6" placeholder="${escapeHtml(q.placeholder)}">${escapeHtml(q.value||'')}</textarea><div class="business-question-actions"><button class="btn" type="button" onclick="setBusinessContextQuestionIndex(${businessContextQuestionIndex-1})" ${businessContextQuestionIndex===0?'disabled':''}>${lang==='es'?'Atrás':'Back'}</button><button class="btn ask-btn" type="button" onclick="openChat(${chatArg(draft)})">${lang==='es'?'Ayudarme':'Help me'}</button><button class="btn primary" type="submit">${isLast?(lang==='es'?'Guardar y crear plan':'Save and build plan'):(lang==='es'?'Guardar y seguir':'Save and continue')}</button></div></form>${businessProfileCard()}</div>`;
}
function initialStrategyGuide(){
 const p=state.business_profile||{};
 const plan=(p.initial_plan&&p.initial_plan.length?p.initial_plan:[
  lang==='es'?'Conectar mi cuenta de Facebook.':'Connect my Facebook account.',
  lang==='es'?'Hablar con el agente.':'Talk to the agent.',
  lang==='es'?'Empezar con supervisión.':'Start with supervision.'
  ]);
  const angles=p.suggested_angles||[];
 return `<div class="setup-guide private-connection"><section class="guide-hero business-hero"><div class="guide-main"><span class="guide-eyebrow">${lang==='es'?'Primer plan':'First plan'}</span><h3>${lang==='es'?'Esto entendí':'This is what I understood'}</h3><p>${escapeHtml(p.positioning||p.detected_title||p.offer|| (lang==='es'?'Todavía falta más contexto.':'We still need more context.'))}</p><div class="business-summary-grid"><div><b>${lang==='es'?'Tipo':'Type'}</b><span>${escapeHtml(p.business_type||'-')}</span></div><div><b>${lang==='es'?'Oferta':'Offer'}</b><span>${escapeHtml(p.main_offer||p.offer||'-')}</span></div><div><b>${lang==='es'?'Cliente':'Customer'}</b><span>${escapeHtml(p.ideal_customer||p.audience||'-')}</span></div></div></div><aside class="guide-checklist"><b>${lang==='es'?'Plan inicial':'Initial plan'}</b><ol>${plan.map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ol></aside></section>${angles.length?`<div class="guide-panel"><b>${lang==='es'?'Ideas iniciales':'Initial ideas'}</b><ol>${angles.map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ol></div>`:''}<div class="onboarding-step-actions"><button class="btn" type="button" onclick="onboardingFlowStep=Math.max(0,onboardingFlowStep-1);renderOnboardingFlow()">${lang==='es'?'Editar':'Edit'}</button><button class="btn primary" type="button" onclick="onboardingFlowTouched=true;onboardingFlowStep=Math.min(onboardingSteps().length-1,onboardingFlowStep+1);renderOnboardingFlow()">${lang==='es'?'Seguir':'Continue'}</button><button class="btn ask-btn" type="button" onclick="openChat('${lang==='es'?'Revisa esta información de mi negocio y dime qué estrategia inicial prepararías para Meta Ads.':'Review this business profile and tell me what initial Meta Ads strategy you would prepare.'}')">${t('ask_agent')}</button></div></div>`;
}
function businessProfileCard(){
 const p=state.business_profile||{};
 const links=[p.website_url,...(p.social_links||[])].filter(Boolean).filter((item,index,arr)=>arr.indexOf(item)===index);
 if(!links.length&&!p.business_type&&!p.telegram_onboarding_requested_at)return '';
 return `<div class="guide-card"><b>${lang==='es'?'Contexto inicial guardado':'Initial context saved'}</b><p>${escapeHtml(p.business_type||links[0]||'')}${links.length?` · ${links.length} ${lang==='es'?'link(s)':'link(s)'}`:''}${p.scan_error?` · ${lang==='es'?'No pude leer toda la web, pero guardé el link y puedes seguir.':'I could not read the full site, but saved the link and you can continue.'}`:''}</p>${p.main_offer||p.offer?`<p>${lang==='es'?'Oferta detectada':'Detected offer'}: ${escapeHtml(p.main_offer||p.offer)}</p>`:''}<p class="notice">${lang==='es'?'La entrevista profunda queda pendiente para el agente por Telegram.':'The deep interview is pending for the agent through Telegram.'}</p></div>`;
}
function businessSnapshotData(){
 const p=state.business_profile||{};
 const s=state.business_snapshot||state.brief?.business_context||{};
 return {
  ready:Boolean(s.ready||p.business_type||p.main_offer||p.offer||p.ideal_customer||p.audience||p.website_url),
  business_type:s.business_type||p.business_type||p.business_short||'',
  main_offer:s.main_offer||p.main_offer||p.offer||p.detected_title||'',
  ideal_customer:s.ideal_customer||p.ideal_customer||p.audience||'',
  current_stage:s.current_stage||p.current_stage||'',
  what_to_improve:s.what_to_improve||p.what_to_improve||'',
  success_goal:s.success_goal||p.success_goal||'',
  sales_channel:s.sales_channel||p.sales_channel||p.channel||'',
  brand_tone:s.brand_tone||p.brand_tone||'',
  website_url:s.website_url||p.website_url||'',
  next_step:s.next_step||'',
  audience_hint:s.audience_hint||'',
  creative_hint:s.creative_hint||'',
  campaign_hint:s.campaign_hint||'',
  summary:s.summary||''
 };
}
function businessProfileFallbacks(d){
 const es=lang==='es';
 return {
  title:d.business_type||d.main_offer||(es?'Negocio por definir':'Business to define'),
  summary:d.summary||[d.main_offer,d.ideal_customer,d.current_stage].filter(Boolean).join(' · ')||(es?'Cuéntame qué vendes y a quién ayudas.':'Tell me what you sell and who you help.'),
  offer:d.main_offer||(es?'Falta decir qué vendes':'Need what you sell'),
  customer:d.ideal_customer||(es?'Falta decir quién compra':'Need who buys'),
  stage:d.current_stage||(es?'Falta decir en qué punto estás':'Need current stage'),
  improve:d.what_to_improve||(es?'Falta elegir qué mejorar primero':'Need first improvement target'),
  next:d.next_step||(es?'Completar oferta, cliente y objetivo.':'Complete offer, customer, and goal.'),
  audience:d.audience_hint||(es?'Empezar amplio y ajustar con datos reales.':'Start broad and refine with real data.'),
  creative:d.creative_hint||(es?'Imagen clara, beneficio directo y poco texto.':'Clear image, direct benefit, little text.'),
  campaign:d.campaign_hint||(es?'Campaña simple, visible y fácil de medir.':'Simple, visible, easy-to-measure campaign.')
 };
}
function businessProfileChatPrompt(){
 const d=businessSnapshotData();
 if(!d.ready)return lang==='es'?'Quiero contarte mi negocio para que personalices el dashboard. Hazme preguntas fáciles, una por una.':'I want to tell you about my business so you can personalize the dashboard. Ask me simple questions one at a time.';
 const c=businessProfileFallbacks(d);
 return lang==='es'?`Revisa mi perfil de negocio y dime qué harías hoy. Negocio: ${c.title}. Oferta: ${c.offer}. Cliente: ${c.customer}. Quiero mejorar: ${c.improve}. Dime el siguiente paso, una audiencia inicial y una idea de creativo.`:`Review my business profile and tell me what you would do today. Business: ${c.title}. Offer: ${c.offer}. Customer: ${c.customer}. I want to improve: ${c.improve}. Give me the next step, an initial audience, and one creative idea.`;
}
function businessMini(label,value){return `<div class="business-profile-mini"><span>${escapeHtml(label)}</span><b>${escapeHtml(value)}</b></div>`}
function renderBusinessProfilePanel(){
 const title=qs('#business-profile-title');if(title)title.textContent=lang==='es'?'Perfil del negocio':'Business profile';
 const box=qs('#business-profile-panel');if(!box)return;
 const d=businessSnapshotData();
 if(!d.ready){
  box.innerHTML=`<div class="business-profile-empty"><p>${lang==='es'?'Todavía no sé suficiente del negocio. Cuéntame qué vendes para que el brief, los creativos y las audiencias tengan contexto real.':'I do not know enough about the business yet. Tell me what you sell so the brief, creatives, and audiences have real context.'}</p><button class="btn primary ask-btn" onclick="openChat(${chatArg(businessProfileChatPrompt())})">${lang==='es'?'Contarle al agente':'Tell the agent'}</button></div>`;
  return;
 }
 const c=businessProfileFallbacks(d);
 const pills=[
  d.website_url?[lang==='es'?'Web':'Website',d.website_url]:null,
  d.sales_channel?[lang==='es'?'Venta':'Sales',d.sales_channel]:null,
  d.success_goal?[lang==='es'?'Meta':'Goal',d.success_goal]:null,
  d.brand_tone?[lang==='es'?'Tono':'Tone',d.brand_tone]:null
 ].filter(Boolean);
 box.innerHTML=`<div class="business-profile-panel"><div class="business-profile-hero"><h3>${escapeHtml(c.title)}</h3><p>${escapeHtml(c.summary)}</p>${pills.length?`<div class="business-profile-pills">${pills.map(([label,value])=>`<span class="business-profile-pill">${escapeHtml(label)}: ${escapeHtml(value)}</span>`).join('')}</div>`:''}</div><div class="business-profile-grid">${businessMini(lang==='es'?'Oferta':'Offer',c.offer)}${businessMini(lang==='es'?'Cliente':'Customer',c.customer)}${businessMini(lang==='es'?'Siguiente paso':'Next step',c.next)}${businessMini(lang==='es'?'Creativo':'Creative',c.creative)}</div><div class="business-profile-grid">${businessMini(lang==='es'?'Audiencia':'Audience',c.audience)}${businessMini(lang==='es'?'Campaña':'Campaign',c.campaign)}</div><div class="business-profile-actions"><button class="btn primary ask-btn" onclick="openChat(${chatArg(businessProfileChatPrompt())})">${lang==='es'?'Preguntar qué haría':'Ask what to do'}</button><button class="btn" onclick="openChat(${chatArg(lang==='es'?'Quiero corregir o completar mi perfil de negocio. Hazme una pregunta simple a la vez.':'I want to correct or complete my business profile. Ask me one simple question at a time.')})">${lang==='es'?'Ajustar perfil':'Adjust profile'}</button></div></div>`;
}
function passiveStepGuide(stepId){
 const es={
  insights:['Leer sin tocar','El agente lee datos reales y no cambia anuncios.','Cuando conectes Meta, este paso se valida con datos reales.'],
  dryrun:['Revisar con ayuda','El resumen diario usa datos reales y prepara ideas sin tocar dinero.','Puedes actualizarlo desde Lectura diaria o desde el chat.'],
  approval:['Pedir tu sí','Los cambios importantes esperan tu aprobación.','Revisa Aprobaciones para ver las solicitudes pendientes.'],
  live:['Con supervisión','El agente lee datos reales y prepara acciones. Los cambios importantes esperan tu sí.','Entra al dashboard y deja la supervisión activa.'],
  smoke:['Prueba pequeña','Solo cuando quieras probar un cambio real muy pequeño.','No hace falta para entrar al dashboard.']
 };
 const en={
  insights:['Read only','The agent reads real data and does not change ads.','Once Meta is connected, this step checks real results.'],
  dryrun:['Review with help','The daily brief uses real data and prepares ideas without spending money.','You can refresh it from Daily Brief or ask chat.'],
  approval:['Ask for your yes','Important changes wait for your approval.','Check Approvals for pending requests.'],
  live:['Supervised mode','The agent reads real data and prepares actions. Important changes wait for your yes.','Enter the dashboard and keep supervision on.'],
  smoke:['Tiny test','Only when you want to try a very small real change.','You do not need this to enter the dashboard.']
 };
 if(stepId==='guide')return usageCheatSheetMarkup(true);
 const copy=(lang==='es'?es:en)[stepId]||[stepCopy(stepId)[0],stepCopy(stepId)[1],lang==='es'?'Usa Siguiente cuando estes listo.':'Use Next when you are ready.'];
 return `<div class="passive-guide"><div class="passive-card"><span class="passive-state">${lang==='es'?'Paso de revisión':'Review step'}</span><b>${copy[0]}</b><p>${copy[1]}</p></div><div class="passive-side"><b>${lang==='es'?'Qué hacer ahora':'What to do now'}</b><p>${copy[2]}</p></div></div>`;
}
function metaConnectionGuide(){
 const v=state.config.setup_values||{};
 if(lang==='es')return `<div class="setup-guide private-connection"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Paso seguro</span><h3>Conectar mi cuenta de Facebook</h3><p>Usa las imágenes de guía incluidas con tu compra. La clave nace dentro de tu propia cuenta de Facebook/Meta, se guarda solo en este computador o VPS y la puedes quitar cuando quieras desde Facebook/Meta.</p><div class="guide-visual"><div class="mini-screen"><span></span><span></span><strong>1. Facebook/Meta</strong><em>crea tu app</em></div><div class="guide-arrow">&rarr;</div><div class="mini-screen"><span></span><span></span><strong>2. Clave propia</strong><em>cópiala de tu cuenta</em></div><div class="guide-arrow">&rarr;</div><div class="mini-screen"><span></span><span></span><strong>3. Dashboard local</strong><em>pégala aquí</em></div></div><div class="guide-actions"><a class="btn" href="/api/social/login" target="_blank" rel="noopener" onclick="connectMetaStarted()">Abrir Facebook/Meta</a><button class="btn" type="button" onclick="showMetaTokenBox()">Ya tengo mi clave</button><button class="btn primary" type="button" onclick="refreshSocialAccounts()">Buscar mis cuentas</button></div><div id="meta-token-box" class="token-box"><label>Clave segura de Facebook/Meta<textarea id="meta-token-input" oninput="scheduleMetaTokenAutoSave()" onpaste="setTimeout(scheduleMetaTokenAutoSave,0)" placeholder="Pega aquí la clave que generaste siguiendo la guía"></textarea></label><button class="btn" type="button" onclick="saveMetaToken()">Reintentar guardar</button><p class="notice">Se guarda automáticamente al pegarla. Nosotros no recibimos esta clave; queda local en esta instalación.</p></div></div><aside class="guide-checklist"><b>Sigue tus imágenes de guía</b><ol><li>Crea una app nueva en Facebook/Meta Developers.</li><li>Abre Marketing API o Graph API Explorer.</li><li>Genera una clave con permisos de anuncios y páginas.</li><li>Pega la clave aquí; el dashboard la guarda solo.</li><li>Busca tus cuentas y elige la correcta.</li></ol></aside></section><div id="social-account-results" class="setup-guide"></div><div class="guide-panel"><b>Por qué esto es más seguro</b><p>La conexión queda entre tu cuenta de Facebook/Meta y tu instalación local. Si algún día quieres cortar acceso, quitas la clave desde Facebook/Meta y listo.</p></div></div>`;
 return `<div class="setup-guide private-connection"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Secure step</span><h3>Connect my Facebook account</h3><p>Use the screenshots included with your purchase. The access key starts inside your own Facebook/Meta account, is stored only on this computer or VPS, and can be revoked whenever you want from Facebook/Meta.</p><div class="guide-visual"><div class="mini-screen"><span></span><span></span><strong>1. Facebook/Meta</strong><em>create your app</em></div><div class="guide-arrow">&rarr;</div><div class="mini-screen"><span></span><span></span><strong>2. Your own key</strong><em>copy it from your account</em></div><div class="guide-arrow">&rarr;</div><div class="mini-screen"><span></span><span></span><strong>3. Local dashboard</strong><em>paste it here</em></div></div><div class="guide-actions"><a class="btn" href="/api/social/login" target="_blank" rel="noopener" onclick="connectMetaStarted()">Open Facebook/Meta</a><button class="btn" type="button" onclick="showMetaTokenBox()">I have my key</button><button class="btn primary" type="button" onclick="refreshSocialAccounts()">Find my accounts</button></div><div id="meta-token-box" class="token-box"><label>Secure Facebook/Meta key<textarea id="meta-token-input" oninput="scheduleMetaTokenAutoSave()" onpaste="setTimeout(scheduleMetaTokenAutoSave,0)" placeholder="Paste the key you generated by following the guide"></textarea></label><button class="btn" type="button" onclick="saveMetaToken()">Retry save</button><p class="notice">It saves automatically when pasted. We do not receive this key; it stays local to this install.</p></div></div><aside class="guide-checklist"><b>Follow your screenshots</b><ol><li>Create a new app in Facebook/Meta Developers.</li><li>Open Marketing API or Graph API Explorer.</li><li>Generate a key with ads and Page permissions.</li><li>Paste the key here; the dashboard saves it automatically.</li><li>Find your accounts and choose the right one.</li></ol></aside></section><div id="social-account-results" class="setup-guide"></div><div class="guide-panel"><b>Why this is safer</b><p>The connection stays between your Facebook/Meta account and your local install. If you ever want to cut access, revoke the key from Facebook/Meta.</p></div></div>`;
}
function accountPickerGuide(){
 const v=state.config.setup_values||{};
 if(lang==='es')return `<div class="setup-guide private-connection"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Cuenta publicitaria</span><h3>Elige una cuenta y seguimos solos</h3><p>Despues de tocar <strong>Usar esta cuenta</strong>, la guia guarda la cuenta y avanza al siguiente paso automaticamente.</p><div class="guide-actions"><button class="btn primary" type="button" onclick="refreshSocialAccounts()">Buscar mis cuentas</button><button class="btn" type="button" onclick="openChat('Ayudame a elegir la cuenta publicitaria correcta con palabras simples.')">${t('ask_agent')}</button></div></div><aside class="guide-checklist"><b>Que debes elegir</b><ol><li>La cuenta donde estan tus campanas reales.</li><li>La cuenta donde tienes permiso para administrar anuncios.</li><li>Si solo aparece una, normalmente esa es la correcta.</li></ol></aside></section><div id="social-account-results" class="setup-guide"></div><details class="fallback-details"><summary>Solo si no aparecen tus cuentas</summary><form class="manual-account onboarding-mini" onsubmit="saveOnboardingSetupConfig(event)"><b>Pegar ID manualmente</b><p>Usa esto solo si el buscador de cuentas no funciona. Se ve asi: <strong>act_123456789</strong>.</p><label>${t('ad_account_id')}<input name="ad_account_id" value="${escapeHtml(v.ad_account_id||'')}" placeholder="act_123456789"></label><button class="btn primary" type="submit">${t('save_setup')}</button></form></details></div>`;
 return `<div class="setup-guide private-connection"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Ad account</span><h3>Choose one account and we continue automatically</h3><p>After you click <strong>Use this account</strong>, the guide saves the account and moves to the next step by itself.</p><div class="guide-actions"><button class="btn primary" type="button" onclick="refreshSocialAccounts()">Find my accounts</button><button class="btn" type="button" onclick="openChat('Help me choose the right ad account in simple words.')">${t('ask_agent')}</button></div></div><aside class="guide-checklist"><b>What to choose</b><ol><li>The account with your real campaigns.</li><li>The account where you can manage ads.</li><li>If only one appears, it is usually the right one.</li></ol></aside></section><div id="social-account-results" class="setup-guide"></div><details class="fallback-details"><summary>Only if your accounts do not appear</summary><form class="manual-account onboarding-mini" onsubmit="saveOnboardingSetupConfig(event)"><b>Paste ID manually</b><p>Use this only if account search does not work. It looks like <strong>act_123456789</strong>.</p><label>${t('ad_account_id')}<input name="ad_account_id" value="${escapeHtml(v.ad_account_id||'')}" placeholder="act_123456789"></label><button class="btn primary" type="submit">${t('save_setup')}</button></form></details></div>`;
}
function destinationPickerGuide(){
 const v=state.config.setup_values||{};
 const current=[v.page_id?`${lang==='es'?'Pagina':'Page'}: ${escapeHtml(v.page_id)}`:'',v.instagram_actor_id?`Instagram: ${escapeHtml(v.instagram_actor_id)}`:'',v.landing_url?`${lang==='es'?'Web':'Website'}: ${escapeHtml(v.landing_url)}`:''].filter(Boolean).join(' · ');
 if(lang==='es')return `<div class="setup-guide private-connection"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Destino de anuncios</span><h3>Busquemos tus páginas automáticamente</h3><p>Con la clave de Meta que ya pegaste, el dashboard intenta traer tus páginas de Facebook, el Instagram conectado y la web. Normalmente solo eliges la página correcta y seguimos.</p><div class="guide-actions"><button class="btn primary" type="button" onclick="discoverMetaAssets('${escapeHtml(v.ad_account_id||'')}')">Buscar páginas e Instagram</button><button class="btn" type="button" onclick="openChat('Ayúdame a escoger la página de Facebook correcta para mis anuncios.')">${t('ask_agent')}</button></div>${current?`<p class="notice">Guardado ahora: ${current}</p>`:''}</div><aside class="guide-checklist"><b>Qué estamos buscando</b><ol><li>Tu página de Facebook para publicar los anuncios.</li><li>Tu Instagram conectado, si existe.</li><li>El link de tu web para enviar visitas.</li></ol></aside></section><div id="destination-discovery-results" class="setup-guide"></div><details class="fallback-details"><summary>Solo si no aparece tu página</summary><form class="manual-account onboarding-mini two" onsubmit="saveOnboardingSetupConfig(event)"><b>Escribir datos manualmente</b><p>Usa esto solo si Meta no devuelve tus páginas. El agente también puede ayudarte por chat a encontrarlas.</p><label>${t('page_id')}<input name="page_id" value="${escapeHtml(v.page_id||'')}" placeholder="123456789"></label><label>${t('instagram_actor_id')}<input name="instagram_actor_id" value="${escapeHtml(v.instagram_actor_id||'')}" placeholder="opcional"></label><label>${t('landing_url')}<input name="landing_url" value="${escapeHtml(v.landing_url||'')}" placeholder="https://..."></label><button class="btn primary" type="submit">${t('save_setup')}</button></form></details></div>`;
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
 if(uiWorkbenchPreview){flow.classList.remove('open');flow.innerHTML='';return}
 const doneState=state.onboarding||{};
 if(doneState.completed&&!doneState.requires_repair){flow.classList.remove('open');return}
 const steps=onboardingSteps();if(onboardingFlowStep>=steps.length)onboardingFlowStep=steps.length-1;
 if(!onboardingFlowTouched&&(steps[onboardingFlowStep]||{}).status==='ok')onboardingFlowStep=firstActionableOnboardingIndex(steps);
 const step=steps[onboardingFlowStep]||steps[0];const copyStep=stepCopy(step.id);const doneCount=steps.filter(s=>s.status==='ok').length;
 const isLast=onboardingFlowStep===steps.length-1;
 const canGoNext=!isLast&&step.status!=='blocked';
 const nextButton=canGoNext?`<button class="btn" onclick="onboardingFlowTouched=true;onboardingFlowStep=Math.min(${steps.length-1},onboardingFlowStep+1);renderOnboardingFlow()">${lang==='es'?'Siguiente':'Next'}</button>`:'';
 const finishButton=isLast?`<button class="btn primary" onclick="completeOnboarding()">${lang==='es'?'Terminar y abrir dashboard':'Finish and open dashboard'}</button>`:'';
 const skipButton=`<button class="btn" onclick="skipOnboarding()">${lang==='es'?'Saltar y completar luego':'Skip and finish later'}</button>`;
 const spaces=state.business_spaces||{};
 const agencySwitch=spaces.is_agency&&spaces.spaces?.length?`<div class="guide-card" style="margin-top:14px"><b>${lang==='es'?'Clientes de agencia':'Agency clients'}</b><p>${lang==='es'?'Abre otro cliente cuando quieras continuar su configuración. Sus datos se mantienen separados.':'Open another client when you want to continue its setup. Its data remains separate.'}</p>${spaces.spaces.map(s=>`<button class="btn ${spaces.active_id===s.id?'primary':''}" style="margin:5px 5px 0 0" type="button" onclick="switchAgencySpace('${escapeHtml(s.id)}')">${escapeHtml(s.name)}</button>`).join('')}</div>`:'';
 const repairNotice=doneState.requires_repair?`<div class="guide-card"><b>${lang==='es'?'Reconectemos tus datos reales':'Reconnect your real data'}</b><p>${lang==='es'?'Tu configuración anterior quedó incompleta o perdió la conexión con Meta. Completa los pasos que falten para que el dashboard no use información de demostración.':'Your previous setup is incomplete or lost its Meta connection. Complete the missing steps so the dashboard does not use demonstration information.'}</p></div>`:'';
 const securityNotice=`<div class="onboarding-security-note"><div><b>${lang==='es'?'Instalación privada y segura':'Private and secure install'}</b><p>${lang==='es'?'Recuerda: nada de lo que coloques aquí lo podemos ver nosotros. Esta instalación vive en tu propio entorno y solo entra tu dispositivo autorizado. Es más privada que entregar tus credenciales a un SaaS. Si tienes dudas, contáctanos.':'Remember: we cannot see anything you enter here. This install lives in your own environment and only your authorized device can enter. It is more private than handing credentials to a SaaS. Contact us if you have questions.'}</p></div></div>`;
 flow.classList.add('open');
 flow.innerHTML=`<div class="onboarding-shell"><aside class="onboarding-side"><h1>Meta Ads Agent</h1><p>${lang==='es'?'Conecta lo esencial. Después hablarás con el agente por Telegram para contarle tu negocio con calma.':'Connect the essentials. Then you talk with the agent through Telegram so it can learn the business calmly.'}</p><div class="onboarding-progress">${steps.map((s,i)=>`<span class="${i<=onboardingFlowStep?'done':''}"></span>`).join('')}</div><p>${doneCount}/${steps.length} ${stepCopy('progress')}</p>${agencySwitch}</aside><main class="onboarding-card">${securityNotice}${repairNotice}<h2>${copyStep[0]}</h2><p>${copyStep[1]}</p>${onboardingFormFor(step.id)}<div class="onboarding-step-actions"><button class="btn" ${onboardingFlowStep===0?'disabled':''} onclick="onboardingFlowTouched=true;onboardingFlowStep=Math.max(0,onboardingFlowStep-1);renderOnboardingFlow()">${lang==='es'?'Atrás':'Back'}</button>${nextButton}${skipButton}${finishButton}</div></main></div>`;
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
 const r=state.config.profitability_rules||state.decision_memory?.profitability_rules||{};
 qs('#guardrails-panel').innerHTML=`<div class="settings-stack"><form class="onboarding-mini two" onsubmit="saveGuardrails(event)"><label>${lang==='es'?'Cuánto puede hacer solo':'How much can it do alone?'}<select name="autonomy_mode"><option value="supervised" ${g.autonomy_mode!=='autopilot'?'selected':''}>${lang==='es'?'Con supervisión: preguntarme primero':'Supervised: ask me first'}</option><option value="autopilot" ${g.autonomy_mode==='autopilot'?'selected':''}>${lang==='es'?'Piloto automático: actuar dentro de mis reglas':'Autopilot: act inside my rules'}</option></select></label><label>${lang==='es'?'Preguntar si el presupuesto cambia más de %':'Ask if budget changes over %'}<input name="approval_required_over_pct" type="number" min="1" step="1" value="${g.approval_required_over_pct||20}"></label><label>${lang==='es'?'Piloto: cambio máximo en %':'Autopilot: max change %'}<input name="auto_budget_change_pct" type="number" min="1" step="1" value="${g.auto_budget_change_pct||10}"></label><label>${lang==='es'?'Piloto: cambio máximo en dinero':'Autopilot: max change amount'}<input name="auto_budget_change_amount" type="number" min="1" step="1" value="${g.auto_budget_change_amount||25}"></label><label>${lang==='es'?'Puede pausar solo si gastó menos de':'Can pause alone only if spend is under'}<input name="auto_pause_max_spend" type="number" min="0" step="1" value="${g.auto_pause_max_spend||100}"></label><label><input type="checkbox" name="require_approval_for_resume" ${g.require_approval_for_resume!==false?'checked':''}> ${lang==='es'?'Para reactivar, siempre preguntarme':'Resume always needs approval'}</label><label><input type="checkbox" name="require_approval_for_new_campaigns" ${g.require_approval_for_new_campaigns!==false?'checked':''}> ${lang==='es'?'Campañas nuevas siempre preguntan primero':'New campaigns always need approval'}</label><label><input type="checkbox" name="require_approval_for_creatives" ${g.require_approval_for_creatives!==false?'checked':''}> ${lang==='es'?'Anuncios nuevos siempre preguntan primero':'New creatives/ads always need approval'}</label><button class="btn primary" type="submit">${lang==='es'?'Guardar reglas':'Save rules'}</button><p class="notice">${lang==='es'?'Estas reglas separan mirar datos reales de tocar dinero real. Chat y Telegram solo aprueban una decisión exacta elegida por ti.':'These rules separate reading real data from touching real money. Chat and Telegram approve only an exact decision chosen by you.'}</p></form><form class="onboarding-mini two profitability-rules" onsubmit="saveProfitabilityRules(event)"><div class="wide"><h3>${lang==='es'?'Reglas de rentabilidad':'Profitability rules'}</h3><p class="notice">${lang==='es'?'Estas son las líneas que el agente usa para explicar por qué recomienda subir, bajar, pausar o crear variantes. Así no decide por “intuición”; decide contra tus reglas.':'These are the lines the agent uses to explain why it recommends scaling, cutting, pausing, or refreshing creatives.'}</p></div><label>${lang==='es'?'CPA objetivo':'Target CPA'}<input name="target_cpa" type="number" min="0" step="1" value="${r.target_cpa||50}"></label><label>${lang==='es'?'ROAS mínimo sano':'Healthy ROAS floor'}<input name="target_roas" type="number" min="0" step=".1" value="${r.target_roas||2.5}"></label><label>${lang==='es'?'Gasto mínimo antes de juzgar':'Min spend before judging'}<input name="min_spend_before_judging" type="number" min="0" step="1" value="${r.min_spend_before_judging||50}"></label><label>${lang==='es'?'Compras mínimas antes de escalar':'Min purchases before scaling'}<input name="min_conversions_before_scaling" type="number" min="0" step="1" value="${r.min_conversions_before_scaling||3}"></label><label>${lang==='es'?'Frecuencia máxima antes de refrescar':'Max frequency before refresh'}<input name="max_frequency_before_refresh" type="number" min="0" step=".1" value="${r.max_frequency_before_refresh||3}"></label><label>${lang==='es'?'CTR mínimo %':'Minimum CTR %'}<input name="min_ctr_pct" type="number" min="0" step=".1" value="${r.min_ctr_pct||0.8}"></label><label class="wide">${lang==='es'?'Notas para el agente':'Notes for the agent'}<textarea name="notes" rows="3" placeholder="${lang==='es'?'Ej: prefiero proteger margen antes que vender más volumen.':'Ex: protect margin before chasing volume.'}">${escapeHtml(r.notes||'')}</textarea></label><button class="btn primary" type="submit">${lang==='es'?'Guardar rentabilidad':'Save profitability rules'}</button></form></div>`;
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
 const ent=state.license_entitlements||state.config.license_entitlements||{};
 const usage=state.workspace_usage||{};
 const workspace=state.active_workspace||{};
 const binding=state.business_binding||{};
 const planName=ent.is_agency?(lang==='es'?'Agencia':'Agency'):(lang==='es'?'Individual':'Individual');
 const activeName=workspace.name||[binding.ad_account_id,binding.page_id].filter(Boolean).join(' · ')||(lang==='es'?'Aún sin negocio activo':'No active business yet');
 const individualCopy=lang==='es'?'Tu licencia Individual cuida un solo negocio activo. Si cambias de negocio, empezamos limpio para evitar mezclar datos.':'Your Individual license protects one active business. If you switch business, we start clean to avoid mixing data.';
 const agencyCopy=lang==='es'?'Licencia Agencia permite varios clientes, cada uno con su propia cuenta, página, memoria y Telegram.':'Agency license allows several clients, each with its own account, Page, memory, and Telegram.';
 qs('#license-panel').innerHTML=`<div class="mode-panel license-status-card"><div><h3>${t('license_panel_title')}: ${licenseLabel(status)}</h3><p>${ent.is_agency?agencyCopy:individualCopy}</p><p class="notice">${licenseDetail(status)}</p></div><div class="mode-actions"><button class="btn ${valid?'':'primary'}" onclick="activateLicense()">${t('license_activate')}</button></div></div><div class="trust-grid license-limits-grid"><div class="trust-card"><b>${lang==='es'?'Plan':'Plan'}</b><p>${planName}</p></div><div class="trust-card"><b>${lang==='es'?'Equipos permitidos':'Allowed devices'}</b><p>${ent.max_devices||1}</p></div><div class="trust-card"><b>${lang==='es'?'Clientes permitidos':'Allowed clients'}</b><p>${usage.used||0}/${usage.limit||ent.workspace_limit||1}</p></div><div class="trust-card"><b>${lang==='es'?'Negocio activo':'Active business'}</b><p>${escapeHtml(activeName)}</p></div></div>`;
}
function renderAgencyPanel(){
 const spaces=state.business_spaces||{};const isAgency=Boolean(spaces.is_agency);
 const box=qs('#agency-panel');if(!box)return;
 if(!isAgency){
  box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'Licencia Individual: un negocio activo':'Individual license: one active business'}</b><p>${lang==='es'?'Tu licencia Individual cuida un solo negocio activo: una cuenta publicitaria, una página de Facebook y un Telegram privado.':'Your Individual license protects one active business: one ad account, one Facebook Page, and one private Telegram.'}</p><p class="notice">${lang==='es'?'Para manejar varios clientes, usa Licencia Agencia. Si cambias de negocio, empezamos limpio para evitar mezclar datos.':'To manage several clients, use Agency License. If you switch business, we start clean to avoid mixing data.'}</p></div>`;
  return;
 }
 const items=(spaces.spaces||[]).map(space=>`<div class="log-item"><b>${escapeHtml(space.name)}</b> ${spaces.active_id===space.id?`<span class="badge ok">${lang==='es'?'Activo':'Active'}</span>`:`<button class="btn" type="button" onclick="switchAgencySpace('${escapeHtml(space.id)}')">${lang==='es'?'Abrir cliente':'Open client'}</button>`}</div>`).join('');
 box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'Licencia Agencia: espacios por cliente':'Agency license: client spaces'}</b><p>${lang==='es'?'Cada cliente conserva su cuenta, página, memoria y configuración de Telegram. Al abrir ese cliente, su agente de Telegram queda activo sin mezclar datos con otro.':'Each client keeps its account, Page, memory and Telegram settings. When you open that client, its Telegram agent becomes active without mixing data with another.'}</p><p class="notice">${lang==='es'?'Uso actual':'Current usage'}: ${(spaces.spaces||[]).length}/${spaces.workspace_limit||50} ${lang==='es'?'clientes':'clients'} · ${lang==='es'?'hasta':'up to'} ${spaces.max_devices||4} ${lang==='es'?'equipos':'devices'}</p>${items||`<p class="notice">${lang==='es'?'Tu primer espacio se crea cuando termines la configuración inicial.':'Your first space is created when initial setup finishes.'}</p>`}<form class="onboarding-mini" onsubmit="createAgencySpace(event)"><label>${lang==='es'?'Nuevo cliente o marca':'New client or brand'}<input name="name" placeholder="${lang==='es'?'Ej. Clínica Norte':'E.g. North Clinic'}"></label><button class="btn primary" type="submit">${lang==='es'?'Agregar cliente':'Add client'}</button></form></div>`;
}
function renderSetupConfig(){
 const v=state.config.setup_values||{};
 const licensePlaceholder=v.license_key_set?(lang==='es'?'Licencia ya guardada. Pega una nueva solo si quieres cambiarla.':'License already saved. Paste a new one only to replace it.'):'MAO-...';
 qs('#setup-config').innerHTML=`<div class="next-step"><div><b>${t('setup_form_title')}</b><p>${t('setup_form_body')}</p></div><button class="btn ask-btn" type="button" onclick="openChat(lang==='es'?'Ayúdame a revisar estos datos de configuración y dime si falta algo importante.':'Help me review these setup details and tell me if anything important is missing.')">${t('ask_agent')}</button></div><form id="setup-config-form" class="form-grid">
  <div class="field"><label>${t('license_key')}</label><span class="field-help">${lang==='es'?'El código que recibiste al comprar.':'The code you received after purchase.'}</span><input name="license_key" value="" placeholder="${escapeHtml(licensePlaceholder)}"></div>
  <div class="field"><label>${t('buyer_email')}</label><span class="field-help">${lang==='es'?'El email usado para la compra o soporte.':'Email used for purchase or support.'}</span><input name="license_buyer_email" value="${escapeHtml(v.license_buyer_email||'')}" placeholder="buyer@email.com"></div>
  <div class="field wide"><label>${t('ad_account_id')}</label><span class="field-help">${lang==='es'?'La cuenta de Meta Ads que este agente va a cuidar.':'The Meta Ads account this agent will manage.'}</span><input name="ad_account_id" value="${escapeHtml(v.ad_account_id||'')}" placeholder="act_123456789"></div>
  <div class="field"><label>${t('page_id')}</label><span class="field-help">${lang==='es'?'La página desde donde salen tus anuncios.':'The Page your ads publish from.'}</span><input name="page_id" value="${escapeHtml(v.page_id||'')}"></div>
  <div class="field"><label>${t('instagram_actor_id')}</label><span class="field-help">${lang==='es'?'Solo si tu Instagram está conectado a la página.':'Only if Instagram is connected to the Page.'}</span><input name="instagram_actor_id" value="${escapeHtml(v.instagram_actor_id||'')}" placeholder="${lang==='es'?'opcional':'optional'}"></div>
  <div class="field"><label>${t('landing_url')}</label><span class="field-help">${lang==='es'?'La web a la que llegarán las personas.':'The website people will visit.'}</span><input name="landing_url" value="${escapeHtml(v.landing_url||'')}" placeholder="https://..."></div>
  <div class="field wide"><button class="btn primary" type="submit">${t('save_setup')}</button></div>
 </form>`;
 qs('#setup-config-form').addEventListener('submit',saveSetupConfig);
}
function chatGptConnectMarkup(onboarding=false){
 const runtime=setupItem('hermes_runtime');
 const auth=setupItem('hermes_auth');
 const codex=setupItem('codex_cli');
 const model=state.config.agent_model||{};
 const brain=model.brain_provider||'openai_codex';
 const apiBrain=['openai_api','minimax','custom_api'].includes(brain);
 const apiReady=apiBrain&&model.api_key_set&&Boolean(model.base_url)&&Boolean(model.model);
 const chatgptReady=runtime.status==='ok'&&auth.status==='ok'&&brain==='openai_codex';
 const ready=chatgptReady||apiReady;
 const hermesMissing=runtime.status==='blocked';
 const title=ready?(lang==='es'?'Modelo del agente conectado':'Agent model connected'):(lang==='es'?'Conecta el cerebro del agente':'Connect the agent brain');
 const body=ready?(apiReady?(lang==='es'?`El manager ya puede pensar con ${model.model||'el modelo configurado'} sin perder memoria, herramientas ni aprobaciones.`:`The manager can now think with ${model.model||'the configured model'} while keeping memory, tools, and approvals.`):(lang==='es'?'El manager ya puede conversar usando tu sesion de ChatGPT/Codex. El chat, Telegram y las herramientas quedan sobre esta conexión.':'The manager can now talk through your ChatGPT/Codex session. Chat, Telegram, and agent tools use this connection.')):(onboarding?(lang==='es'?'Elige qué modelo usará el agente. Toca una opción y solo verás lo necesario.':'Choose which model the agent will use. Click an option and only the needed steps will open.'):(lang==='es'?'Elige cómo pensará el manager: OpenAI, tu suscripción de ChatGPT, MiniMax M3 u otra API compatible.':'Choose how the manager thinks: OpenAI, your ChatGPT subscription, MiniMax M3, or another compatible API.'));
 const badge=ready?(lang==='es'?'Listo':'Ready'):(hermesMissing?(lang==='es'?'Falta base del agente':'Agent base missing'):(lang==='es'?'Falta conectar':'Needs connection'));
 const detail=[runtime.detail,auth.detail,codex.detail].filter(Boolean).map(localText).join(' · ');
 const draft=lang==='es'?'Ayúdame a elegir el cerebro del agente. Explícame en palabras simples si me conviene ChatGPT/Codex, MiniMax M3 u otra API.':'Help me choose the agent brain. Explain simply whether ChatGPT/Codex, MiniMax M3, or another API is better for me.';
 const savedBase=model.base_url||'';
 const selectedRoute=brain==='openai_codex'?'chatgpt_subscription':(brain==='minimax'||savedBase.includes('minimax')?'minimax_m3':(brain==='openai_api'||savedBase.includes('api.openai.com')?'openai_api':'custom_api'));
 const base=model.base_url||(selectedRoute==='openai_api'?'https://api.openai.com/v1':(selectedRoute==='custom_api'?'':'https://api.minimax.io/v1'));
 const modelName=model.model||(selectedRoute==='openai_api'?'gpt-4.1-mini':(selectedRoute==='custom_api'?'':'MiniMax-M3'));
 const api=model.api||'openai-chat-completions';
 const keyPlaceholder=model.api_key_set?(lang==='es'?'Clave guardada. Pega otra solo si quieres cambiarla.':'Key saved. Paste another only to replace it.'):(lang==='es'?'Pega la clave API del proveedor':'Paste the provider API key');
 const routeCopy={
  openai_api:{icon:'OA',title:lang==='es'?'OpenAI API':'OpenAI API',desc:lang==='es'?'Si tienes una clave API de OpenAI.':'If you have an OpenAI API key.',panel:lang==='es'?'Pega tu clave API de OpenAI. El agente seguirá usando su memoria, herramientas y aprobaciones.':'Paste your OpenAI API key. The agent still keeps its memory, tools, and approvals.'},
  chatgpt_subscription:{icon:'CG',title:lang==='es'?'ChatGPT suscripción':'ChatGPT subscription',desc:lang==='es'?'Login OAuth con ChatGPT/Codex.':'OAuth login with ChatGPT/Codex.',panel:lang==='es'?'Primero, en ChatGPT abre Ajustes > Seguridad y activa el login por código para Codex. Después toca Conectar ahora; en PC/Mac abriré la terminal y en DigitalOcean mostraré aquí el enlace seguro.':'First, in ChatGPT open Settings > Security and enable device-code login for Codex. Then click Connect now; on PC/Mac I open the terminal and on DigitalOcean I show the secure link here.'},
  minimax_m3:{icon:'M3',title:'MiniMax M3',desc:lang==='es'?'Con clave de MiniMax.':'With a MiniMax key.',panel:lang==='es'?'Pega tu clave de MiniMax. Ya dejé URL y modelo listos para M3. El agente seguirá usando su memoria y herramientas.':'Paste your MiniMax key. URL and model are already set for M3. The agent still keeps memory and tools.'},
  custom_api:{icon:'{}',title:lang==='es'?'Otra API compatible':'Other compatible API',desc:lang==='es'?'Para proveedores tipo OpenAI.':'For OpenAI-style providers.',panel:lang==='es'?'Pega la URL, el nombre del modelo y la clave del proveedor. El agente la usará como cerebro.':'Paste the provider URL, model name, and key. The agent will use it as its brain.'}
 };
 const routeButton=kind=>`<button class="agent-model-option ${selectedRoute===kind?'active':''}" type="button" data-agent-route="${kind}" aria-expanded="${selectedRoute===kind?'true':'false'}" onclick="selectAgentModelRoute('${kind}')"><span class="route-icon">${routeCopy[kind].icon}</span><span><b>${routeCopy[kind].title}</b><p>${routeCopy[kind].desc}</p></span></button>`;
 const apiPanelTitle=selectedRoute==='chatgpt_subscription'?routeCopy.minimax_m3.title:routeCopy[selectedRoute].title;
 const apiPanelHelp=selectedRoute==='chatgpt_subscription'?routeCopy.minimax_m3.panel:routeCopy[selectedRoute].panel;
 const providerValue=brain;
 return `<section class="chatgpt-connect-card ${ready?'ready':''}"><div class="chatgpt-connect-head"><div><h3>${title}</h3><p>${body}</p></div><span class="badge ${ready?'ok':'warn'}">${badge}</span></div><div class="agent-model-picker" role="tablist" aria-label="${lang==='es'?'Opciones de modelo del agente':'Agent model options'}">${routeButton('openai_api')}${routeButton('chatgpt_subscription')}${routeButton('minimax_m3')}${routeButton('custom_api')}</div><form id="agent-model-form" class="model-provider-form" onsubmit="saveSetupConfig(event)">
 <input type="hidden" name="agent_chat_provider" value="${escapeHtml(providerValue)}">
 <input type="hidden" name="agent_chat_api" value="${escapeHtml(api)}">
 <div class="agent-route-panels">
  <div class="agent-route-panel ${selectedRoute==='chatgpt_subscription'?'active':''}" data-agent-route-panel="chatgpt_subscription"><h4>${routeCopy.chatgpt_subscription.title}</h4><p>${routeCopy.chatgpt_subscription.panel}</p><div class="chatgpt-preflight"><b>${lang==='es'?'Antes de conectar':'Before connecting'}</b><ol><li>${lang==='es'?'Abre ChatGPT en otra pestaña.':'Open ChatGPT in another tab.'}</li><li>${lang==='es'?'Entra a Ajustes > Seguridad.':'Go to Settings > Security.'}</li><li>${lang==='es'?'Activa “Enable device code authorization for Codex”.':'Turn on “Enable device code authorization for Codex”.'}</li></ol></div><div class="agent-route-actions"><button class="btn primary" type="button" onclick="connectChatGpt(event)">${lang==='es'?'Conectar ahora':'Connect now'}</button><button class="btn ask-btn" type="button" onclick="openChat(${JSON.stringify(draft).replaceAll('"','&quot;')})">${t('ask_agent')}</button></div><div id="chatgpt-connect-result" class="chatgpt-connect-result hidden"></div></div>
  <div class="agent-route-panel ${selectedRoute!=='chatgpt_subscription'?'active':''}" data-agent-route-panel="api"><h4 id="agent-api-route-title">${apiPanelTitle}</h4><p id="agent-api-route-help">${apiPanelHelp}</p><div class="form-grid">
   <div class="field"><label>${lang==='es'?'Modelo':'Model'}</label><input name="agent_chat_model" value="${escapeHtml(modelName)}" placeholder="${lang==='es'?'Nombre del modelo':'Model name'}"></div>
   <div class="field"><label>${lang==='es'?'URL compatible OpenAI':'OpenAI-compatible URL'}</label><span class="field-help">${lang==='es'?'Debe usar https://. Solo se permite http:// para modelos locales como 127.0.0.1.':'Must use https://. http:// is allowed only for local models such as 127.0.0.1.'}</span><input name="agent_chat_base_url" value="${escapeHtml(base)}" placeholder="https://api.ejemplo.com/v1"></div>
   <div class="field wide"><label>${lang==='es'?'Clave API del modelo':'Model API key'}</label><span class="field-help">${lang==='es'?'Se guarda dentro de este PC/VPS. No aparece de vuelta en el dashboard.':'Stored on this PC/VPS. It is never shown back in the dashboard.'}</span><input type="password" name="agent_chat_api_key" value="" placeholder="${escapeHtml(keyPlaceholder)}"></div>
   <div class="field wide"><button class="btn primary" type="submit">${lang==='es'?'Guardar modelo del agente':'Save agent model'}</button></div>
  </div></div>
 </div>
 </form><details class="helper-command"><summary>${lang==='es'?'Ver diagnóstico para soporte':'Show support diagnostics'}</summary><span class="step-command">${escapeHtml(detail||'-')}</span></details><div class="chatgpt-foot"><div></div><div class="mode-actions"><button class="btn" type="button" onclick="load()">${lang==='es'?'Ya lo hice, revisar conexión':'I did it, recheck'}</button></div></div></section>`;
}
function renderChatGptPanel(){
 qs('#chatgpt-panel').innerHTML=chatGptConnectMarkup(false);
}
function telegramOnboardingGuide(){
 const v=state.config.telegram_agent||{};
 const ready=Boolean(v.enabled&&v.bot_configured&&v.chat_id);
 const checked=v.enabled||!v.bot_configured?'checked':'';
 const result=ready
  ? `<div class="guide-card"><b>${lang==='es'?'Telegram listo':'Telegram ready'}</b><p>${lang==='es'?'Ya puedes hablar con el manager desde tu celular. También podrá mostrarte aprobaciones con botones seguros.':'You can now talk with the manager from your phone. It can also show approval buttons safely.'}</p><button class="btn" type="button" onclick="testTelegram()">${lang==='es'?'Enviar prueba':'Send test'}</button></div>`
  : `<div class="guide-card"><b>${lang==='es'?'Después de pegar la clave':'After pasting the key'}</b><p>${lang==='es'?'Escríbele “hola” a tu bot en Telegram, vuelve aquí y toca Detectar mi chat. Yo guardaré solo ese chat como autorizado.':'Send “hello” to your bot in Telegram, come back here, and click Detect my chat. I will save only that chat as authorized.'}</p></div>`;
 if(lang==='es')return `<div class="setup-guide private-connection telegram-onboarding"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Celular</span><h3>Habla con tu manager por Telegram</h3><p>Recomendado: podrás escribirle al agente desde tu celular, enviar imágenes y aprobar decisiones exactas con botones. Esto se configura una sola vez y luego queda funcionando.</p><div class="guide-actions"><a class="btn primary" href="https://telegram.org/dl" target="_blank" rel="noopener noreferrer">Descargar Telegram</a><a class="btn" href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer">Abrir BotFather</a><button class="btn" type="button" onclick="copyCommand('/newbot')">Copiar /newbot</button></div></div><aside class="guide-checklist"><b>Pasos simples</b><ol><li>Instala Telegram en tu celular. Si puedes, instala Telegram en tu PC para copiar y pegar más fácil.</li><li>En Telegram busca <b>BotFather</b>, entra al chat oficial y escribe <b>/newbot</b>.</li><li>Escribe cualquier nombre para tu bot, por ejemplo <b>Manager de anuncios</b>.</li><li>Escribe un usuario parecido, pero terminado en <b>bot</b>, por ejemplo <b>manageranuncios_bot</b>.</li><li>BotFather te enviará una clave larga. Cópiala y pégala aquí.</li><li>Escríbele <b>hola</b> a tu bot y toca <b>Detectar mi chat</b>.</li></ol></aside></section><div class="guide-card"><b>Qué puedo automatizar</b><p>No puedo crear el bot por ti porque Telegram solo entrega la clave dentro del chat oficial BotFather. Sí puedo abrir BotFather, copiarte el comando, validar la clave, detectar tu chat y dejarlo listo para siempre.</p></div><form class="onboarding-mini two" onsubmit="saveTelegramConfig(event)"><label class="wide">Clave larga que te dio BotFather<span class="field-help">Pégala completa. Suele verse como números, dos puntos y muchas letras. Queda guardada solo en este PC/VPS.</span><input type="password" name="bot_token" value="" placeholder="${v.bot_configured?'Bot guardado. Pega otra clave solo si quieres cambiarlo.':'Pega aquí la clave larga de BotFather'}"></label><label>Idioma del manager<select name="language"><option value="es" ${v.language!=='en'?'selected':''}>Español</option><option value="en" ${v.language==='en'?'selected':''}>English</option></select></label><label><input type="checkbox" name="enabled" ${checked}> Activar Telegram</label><div class="field wide onboarding-step-actions"><button class="btn primary" type="submit">Guardar bot</button><button class="btn" type="button" onclick="detectTelegramChats()">Detectar mi chat</button><button class="btn" type="button" onclick="testTelegram()">Enviar prueba</button></div></form><div id="telegram-results" class="setup-guide">${result}</div><details class="fallback-details"><summary>Lo puedo hacer después</summary><p class="notice">Puedes seguir ahora y volver a este paso desde Configuración. Para usar Telegram, el dashboard debe estar encendido en tu PC/VPS.</p></details></div>`;
 return `<div class="setup-guide private-connection telegram-onboarding"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Phone</span><h3>Talk to your manager through Telegram</h3><p>Recommended: you can message the agent from your phone, send images, and approve exact decisions with buttons. You do this once and it keeps working.</p><div class="guide-actions"><a class="btn primary" href="https://telegram.org/dl" target="_blank" rel="noopener noreferrer">Download Telegram</a><a class="btn" href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer">Open BotFather</a><button class="btn" type="button" onclick="copyCommand('/newbot')">Copy /newbot</button></div></div><aside class="guide-checklist"><b>Simple steps</b><ol><li>Install Telegram on your phone. If possible, also install Telegram on your PC so copying the long key is easier.</li><li>In Telegram search for <b>BotFather</b>, open the official chat, and send <b>/newbot</b>.</li><li>Enter any bot name, for example <b>Ads Manager</b>.</li><li>Enter a similar username, but it must end in <b>bot</b>, for example <b>adsmanager_bot</b>.</li><li>BotFather will send a long key. Copy it and paste it here.</li><li>Send <b>hello</b> to your bot, then click <b>Detect my chat</b>.</li></ol></aside></section><div class="guide-card"><b>What I can automate</b><p>I cannot create the bot for you because Telegram gives the key only inside the official BotFather chat. I can open BotFather, copy the command, validate the key, detect your chat, and keep it ready after that.</p></div><form class="onboarding-mini two" onsubmit="saveTelegramConfig(event)"><label class="wide">Long key from BotFather<span class="field-help">Paste it complete. It usually looks like numbers, a colon, and many letters. It stays saved only on this PC/VPS.</span><input type="password" name="bot_token" value="" placeholder="${v.bot_configured?'Bot saved. Paste another key only to replace it.':'Paste the long BotFather key here'}"></label><label>Manager language<select name="language"><option value="es" ${v.language!=='en'?'selected':''}>Español</option><option value="en" ${v.language==='en'?'selected':''}>English</option></select></label><label><input type="checkbox" name="enabled" ${checked}> Enable Telegram</label><div class="field wide onboarding-step-actions"><button class="btn primary" type="submit">Save bot</button><button class="btn" type="button" onclick="detectTelegramChats()">Detect my chat</button><button class="btn" type="button" onclick="testTelegram()">Send test</button></div></form><div id="telegram-results" class="setup-guide">${result}</div><details class="fallback-details"><summary>I can do this later</summary><p class="notice">You can continue now and come back from Setup. To use Telegram, the dashboard must be running on your PC/VPS.</p></details></div>`;
}
let chatGptConnectPollTimer=null;
let chatGptAuthWindow=null;
let chatGptAuthOpenedUrl='';
function prepareChatGptAuthWindow(){
 try{
  chatGptAuthWindow=window.open('about:blank','admiro_chatgpt_login');
  if(!chatGptAuthWindow)return false;
  chatGptAuthWindow.document.write(`<!doctype html><html><head><title>Admiro AI</title><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#101113;color:#f2f2ee;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.card{width:min(420px,calc(100vw - 32px));border:1px solid rgba(255,255,255,.14);border-radius:14px;background:linear-gradient(135deg,rgba(39,199,167,.12),rgba(99,168,255,.08));padding:22px;box-shadow:0 24px 70px rgba(0,0,0,.34)}h1{font-size:20px;margin:0 0 8px}p{color:#a7adb5;font-size:14px;line-height:1.45;margin:0}.dot{width:10px;height:10px;border-radius:50%;background:#27c7a7;box-shadow:0 0 22px #27c7a7;margin-bottom:14px;animation:pulse 1.2s ease-in-out infinite}@keyframes pulse{0%,100%{transform:scale(.85);opacity:.55}50%{transform:scale(1.18);opacity:1}}</style></head><body><div class="card"><div class="dot"></div><h1>${lang==='es'?'Preparando login':'Preparing login'}</h1><p>${lang==='es'?'Estoy buscando el enlace seguro de ChatGPT/Codex. Esta pestaña se abrirá sola cuando esté listo.':'I am finding the secure ChatGPT/Codex link. This tab will open automatically when it is ready.'}</p></div></body></html>`);
  chatGptAuthWindow.document.close();
  return true;
 }catch(_err){
  chatGptAuthWindow=null;
  return false;
 }
}
function maybeOpenChatGptAuthUrl(url){
 const raw=String(url||'').trim();
 if(!raw||raw===chatGptAuthOpenedUrl)return false;
 let parsed;
 try{parsed=new URL(raw)}catch(_err){return false}
 if(!['https:','http:'].includes(parsed.protocol))return false;
 if(parsed.protocol==='http:'&&!['127.0.0.1','localhost','::1'].includes(parsed.hostname))return false;
 chatGptAuthOpenedUrl=raw;
 try{
  if(chatGptAuthWindow&&!chatGptAuthWindow.closed){
   try{chatGptAuthWindow.opener=null}catch(_err){}
   chatGptAuthWindow.location.href=raw;
   return true;
  }
 }catch(_err){}
 return false;
}
function reopenChatGptAuthUrl(){
 const raw=String(chatGptAuthOpenedUrl||'').trim();
 if(!raw)return false;
 window.open(raw,'admiro_chatgpt_login');
 return true;
}
function scheduleChatGptConnectPoll(result){
 const r=result?.result||result||{};
 const status=String(r.status||'');
 const shouldPoll=Boolean(r.running)||['browser_login_started','browser_login_waiting','needs_login'].includes(status);
 if(chatGptConnectPollTimer)clearTimeout(chatGptConnectPollTimer);
 if(!shouldPoll)return;
 chatGptConnectPollTimer=setTimeout(()=>pollChatGptConnection(),2400);
}
async function pollChatGptConnection(){
 try{
  const res=await api('/api/agent-model/connect-status',{method:'POST',body:'{}'});
  renderChatGptConnectResult(res);
  if((res.result?.status||res.status)==='completed')await load();
 }catch(_err){
  if(chatGptConnectPollTimer)clearTimeout(chatGptConnectPollTimer);
 }
}
async function sendChatGptTerminalInput(event){
 event.preventDefault();
 const form=event.target;
 const input=(new FormData(form).get('input')||'').toString();
 if(!input.trim())return;
 const btn=form.querySelector('button');if(btn)btn.disabled=true;
 try{
  const res=await api('/api/agent-model/connect-input',{method:'POST',body:JSON.stringify({input})});
  form.reset();
  renderChatGptConnectResult(res);
 }finally{
  if(btn)btn.disabled=false;
 }
}
function chatGptDeviceAuthHelpMarkup(){
 return `<div id="chatgpt-device-auth-help" class="guide-card chatgpt-settings-help hidden"><b>${lang==='es'?'Si ChatGPT te mostró un error en rojo':'If ChatGPT showed a red error'}</b><p>${lang==='es'?'No pasa nada. Falta activar un permiso de seguridad de ChatGPT para usar Codex con códigos.':'No problem. A ChatGPT security permission must be enabled before Codex can use device codes.'}</p><ol><li>${lang==='es'?'Abre chatgpt.com con la misma cuenta.':'Open chatgpt.com with the same account.'}</li><li>${lang==='es'?'Entra a Configuración.':'Open Settings.'}</li><li>${lang==='es'?'Entra a Seguridad.':'Open Security.'}</li><li>${lang==='es'?'Activa la última opción: “Activar autorización con códigos de dispositivo para Codex”.':'Turn on the last option: “Enable device code authorization for Codex”.'}</li><li>${lang==='es'?'Cierra la pestaña de login de ChatGPT/Codex donde viste el error.':'Close the ChatGPT/Codex login tab where you saw the error.'}</li><li>${lang==='es'?'Vuelve aquí y abre el login otra vez.':'Come back here and open the login again.'}</li></ol><button class="btn primary chatgpt-retry-login" type="button" onclick="reopenChatGptAuthUrl()">${lang==='es'?'Ya lo activé, abrir login de nuevo':'I enabled it, open login again'}</button></div>`;
}
function toggleChatGptDeviceAuthHelp(){
 const box=qs('#chatgpt-device-auth-help');
 if(!box)return;
 box.classList.toggle('hidden');
 box.scrollIntoView({behavior:'smooth',block:'center'});
}
function renderChatGptConnectResult(response){
 const box=qs('#chatgpt-connect-result');if(!box)return;
 const r=response.result||response||{};
 const status=String(r.status||'');
 const urls=Array.isArray(r.urls)?r.urls:[];
 if(urls.length)maybeOpenChatGptAuthUrl(urls[0]);
 const output=String(r.output||'').trim();
 const running=Boolean(r.running);
 const titles={
  terminal_opened:lang==='es'?'Terminal abierta':'Terminal opened',
  completed:lang==='es'?'Conexión revisada':'Connection checked',
  browser_login_started:lang==='es'?'Login abierto en el servidor':'Server login started',
  browser_login_waiting:lang==='es'?'Hermes está esperando':'Hermes is waiting',
  needs_login:lang==='es'?'Termina el login':'Finish login',
  needs_terminal:lang==='es'?'Necesita una terminal':'Terminal needed',
 not_installed:lang==='es'?'Hermes no está instalado':'Hermes is not installed'
 };
 const fallbackTitle=lang==='es'?'No pude conectar automáticamente':'Could not connect automatically';
 const title=escapeHtml(r.title||titles[status]||fallbackTitle);
 const detail=escapeHtml(r.detail||'');
 const autoNote=String(r.auto_note||'').trim();
 const phaseNote=autoNote?`<div class="notice">${escapeHtml(autoNote)}</div>`:'';
 const deviceAuthHelp=r.phase==='device_auth_settings'?`<div class="guide-card chatgpt-settings-help"><b>${lang==='es'?'Haz esto en ChatGPT':'Do this in ChatGPT'}</b><ol><li>${lang==='es'?'Abre ChatGPT con la misma cuenta que usarás aquí.':'Open ChatGPT with the same account you will use here.'}</li><li>${lang==='es'?'Ve a Ajustes > Seguridad.':'Go to Settings > Security.'}</li><li>${lang==='es'?'Activa “Enable device code authorization for Codex”.':'Turn on “Enable device code authorization for Codex”.'}</li><li>${lang==='es'?'Cierra la pestaña de login de ChatGPT/Codex donde viste el error.':'Close the ChatGPT/Codex login tab where you saw the error.'}</li><li>${lang==='es'?'Vuelve aquí y abre el login otra vez.':'Come back here and open the login again.'}</li></ol><button class="btn primary chatgpt-retry-login" type="button" onclick="reopenChatGptAuthUrl()">${lang==='es'?'Ya lo activé, abrir login de nuevo':'I enabled it, open login again'}</button></div>`:'';
 const loginCode=String(r.login_code||(Array.isArray(r.login_codes)&&r.login_codes.length?r.login_codes[0]:'')||'').trim();
 const codeBlock=loginCode?`<div class="chatgpt-device-code" role="status" aria-live="polite"><div><span>${lang==='es'?'Código para OpenAI':'Code for OpenAI'}</span><strong>${escapeHtml(loginCode)}</strong><small>${lang==='es'?'Pégalo en la pestaña de OpenAI/Codex que se abrió. Si ChatGPT muestra un error en rojo, toca el botón de ayuda.':'Paste it in the OpenAI/Codex tab that opened. If ChatGPT shows a red error, click the help button.'}</small></div><div class="chatgpt-device-actions"><button class="btn primary" type="button" onclick="copyCommand(${JSON.stringify(loginCode).replaceAll('"','&quot;')})">${lang==='es'?'Copiar código':'Copy code'}</button><button class="btn" type="button" onclick="toggleChatGptDeviceAuthHelp()">${lang==='es'?'Haz clic aquí si te apareció un error':'Click here if you saw an error'}</button></div></div>${chatGptDeviceAuthHelpMarkup()}`:'';
 const links=urls.length?`<div class="onboarding-step-actions">${urls.map(url=>`<a class="btn primary" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${lang==='es'?'Abrir login':'Open login'}</a>`).join('')}</div>`:'';
 const inputBox=running&&r.needs_input?`<form class="onboarding-mini chatgpt-inline-input" onsubmit="sendChatGptTerminalInput(event)"><label>${lang==='es'?'Responder a Hermes':'Reply to Hermes'}<input name="input" autocomplete="off" placeholder="${lang==='es'?'Ej: número de OpenAI Codex o Enter':'Ex: OpenAI Codex number or Enter'}"></label><button class="btn primary" type="submit">${lang==='es'?'Enviar':'Send'}</button></form>`:'';
 const command=status==='needs_terminal'||status==='not_installed'?`<details class="helper-command"><summary>${lang==='es'?'Comando técnico para soporte':'Technical support command'}</summary><span class="step-command">${escapeHtml(r.command||'hermes model --no-browser')}</span><button class="btn" type="button" onclick="copyCommand(${JSON.stringify(r.command||'hermes model --no-browser').replaceAll('"','&quot;')})">${t('copy_command')}</button></details>`:'';
 const outputBlock=output?`<details class="helper-command"><summary>${lang==='es'?'Ver detalle técnico de Hermes':'Show Hermes technical detail'}</summary><pre class="chatgpt-terminal-output">${escapeHtml(output)}</pre></details>`:'';
 const review=status==='terminal_opened'||status==='completed'||status==='needs_login'||status==='browser_login_started'||status==='browser_login_waiting'?`<button class="btn" type="button" onclick="pollChatGptConnection()">${lang==='es'?'Revisar conexión':'Recheck connection'}</button>`:'';
 box.classList.toggle('has-device-code',Boolean(loginCode));
 box.innerHTML=`<b>${title}</b><p>${detail}</p>${phaseNote}${deviceAuthHelp}${codeBlock}${links}${outputBlock}${inputBox}${command}${review?`<div class="onboarding-step-actions">${review}</div>`:''}`;
 box.classList.remove('hidden');
 if(loginCode)setTimeout(()=>box.querySelector('.chatgpt-device-code')?.scrollIntoView({behavior:'smooth',block:'center'}),80);
 scheduleChatGptConnectPoll(r);
}
async function connectChatGpt(event){
 const btn=event?.currentTarget||event?.target;
 const box=qs('#chatgpt-connect-result');
 if(btn)btn.disabled=true;
 const popupReady=prepareChatGptAuthWindow();
 if(box){box.classList.remove('hidden');box.innerHTML=`<b>${lang==='es'?'Conectando...':'Connecting...'}</b><p>${popupReady?(lang==='es'?'Abrí una pestaña de espera. Cuando aparezca el login seguro, la llevaré ahí automáticamente.':'I opened a waiting tab. When the secure login appears, I will send it there automatically.'):(lang==='es'?'Si el navegador bloqueó la pestaña, te mostraré un botón para abrir el login.':'If the browser blocked the tab, I will show a button to open the login.')}</p>`}
 try{
  const res=await api('/api/agent-model/connect',{method:'POST',body:'{}'});
  renderChatGptConnectResult(res);
  const status=res.result?.status||res.status;
  if(status==='terminal_opened')toast(lang==='es'?'Abrí la terminal para conectar ChatGPT/Codex.':'Opened the terminal to connect ChatGPT/Codex.');
  else if(status==='completed')toast(lang==='es'?'Hermes respondió correctamente.':'Hermes responded successfully.');
  else if(String(status).startsWith('browser_login'))toast(lang==='es'?'Login de Hermes abierto aquí.':'Hermes login opened here.');
 }catch(err){
  if(box){box.classList.remove('hidden');box.innerHTML=`<b>${lang==='es'?'No pude abrirlo todavía':'Could not open it yet'}</b><p>${escapeHtml(err.message||String(err))}</p>`}
 }finally{
  if(btn)btn.disabled=false;
 }
}
function applyAgentModelPreset(kind){
 const form=qs('#agent-model-form');if(!form)return;
 const fields=form.elements;
 const route=kind==='hermes'?'chatgpt_subscription':(kind==='custom'?'custom_api':kind);
 if(fields.agent_chat_api)fields.agent_chat_api.value='openai-chat-completions';
 if(route==='chatgpt_subscription'){fields.agent_chat_provider.value='openai_codex';return}
 if(route==='openai_api'){
  fields.agent_chat_provider.value='openai_api';
  fields.agent_chat_base_url.value='https://api.openai.com/v1';
  if(!fields.agent_chat_model.value||fields.agent_chat_model.value.includes('MiniMax'))fields.agent_chat_model.value='gpt-4.1-mini';
  return;
 }
 if(route==='minimax_m3'){
  fields.agent_chat_provider.value='minimax';
  fields.agent_chat_base_url.value='https://api.minimax.io/v1';
  fields.agent_chat_model.value='MiniMax-M3';
  return;
 }
 if(route==='custom_api'){
  fields.agent_chat_provider.value='custom_api';
  if(fields.agent_chat_base_url.value.includes('api.minimax.io')||fields.agent_chat_base_url.value.includes('api.openai.com'))fields.agent_chat_base_url.value='';
  if(fields.agent_chat_model.value.includes('MiniMax')||fields.agent_chat_model.value.includes('gpt-'))fields.agent_chat_model.value='';
 }
}
function selectAgentModelRoute(kind){
 const route=kind==='hermes'?'chatgpt_subscription':(kind==='custom'?'custom_api':kind);
 applyAgentModelPreset(route);
 document.querySelectorAll('[data-agent-route]').forEach(btn=>{
  const active=btn.dataset.agentRoute===route;
  btn.classList.toggle('active',active);
  btn.setAttribute('aria-expanded',active?'true':'false');
 });
 document.querySelectorAll('[data-agent-route-panel]').forEach(panel=>{
  const panelRoute=panel.dataset.agentRoutePanel;
  panel.classList.toggle('active',panelRoute===route||(panelRoute==='api'&&route!=='chatgpt_subscription'));
 });
 const copy={
  openai_api:{title:lang==='es'?'OpenAI API':'OpenAI API',help:lang==='es'?'Pega tu clave API de OpenAI. El agente la usará como cerebro sin perder memoria, herramientas ni aprobaciones.':'Paste your OpenAI API key. The agent will use it as its brain while keeping memory, tools, and approvals.'},
  minimax_m3:{title:'MiniMax M3',help:lang==='es'?'Pega tu clave de MiniMax. Ya dejé URL y modelo listos para M3. El agente seguirá usando su memoria y herramientas.':'Paste your MiniMax key. URL and model are already set for M3. The agent still keeps memory and tools.'},
  custom_api:{title:lang==='es'?'Otra API compatible':'Other compatible API',help:lang==='es'?'Pega la URL, el nombre del modelo y la clave del proveedor. El agente la usará como cerebro.':'Paste the provider URL, model name, and key. The agent will use it as its brain.'}
 };
 if(copy[route]){
  const title=qs('#agent-api-route-title');const help=qs('#agent-api-route-help');
  if(title)title.textContent=copy[route].title;
  if(help)help.textContent=copy[route].help;
 }
}
function renderTelegramPanel(){
 const v=state.config.telegram_agent||{};
 const ready=v.enabled&&v.bot_configured&&v.chat_id;
 qs('#telegram-panel').innerHTML=`<div class="next-step"><div><b>${lang==='es'?'Hablar por Telegram':'Talk through Telegram'}</b><p>${lang==='es'?'Opcional recomendado: conecta un bot privado para conversar con el manager desde tu celular y aprobar decisiones exactas con botones seguros.':'Recommended optional step: connect a private bot to talk with the manager from your phone and approve exact decisions with safe buttons.'}</p></div><span class="badge ${ready?'ok':'warn'}">${ready?(lang==='es'?'Listo':'Ready'):(lang==='es'?'Opcional':'Optional')}</span></div><div class="setup-guide private-connection"><div class="guide-actions"><a class="btn primary" href="https://telegram.org/dl" target="_blank" rel="noopener noreferrer">${lang==='es'?'Descargar Telegram':'Download Telegram'}</a><a class="btn" href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer">${lang==='es'?'Abrir BotFather':'Open BotFather'}</a><button class="btn" type="button" onclick="copyCommand('/newbot')">${lang==='es'?'Copiar /newbot':'Copy /newbot'}</button></div><div class="guide-card"><b>${lang==='es'?'Cómo crear el bot':'How to create the bot'}</b><ol><li>${lang==='es'?'Instala Telegram en tu celular. Si puedes, también en tu PC para copiar más fácil.':'Install Telegram on your phone. If possible, also install it on your PC so copying is easier.'}</li><li>${lang==='es'?'Busca BotFather, entra al chat oficial y escribe /newbot.':'Search for BotFather, open the official chat, and send /newbot.'}</li><li>${lang==='es'?'Pon cualquier nombre. Luego pon un usuario parecido que termine en bot.':'Enter any name. Then enter a similar username that ends in bot.'}</li><li>${lang==='es'?'Copia la clave larga que te entrega BotFather y pégala abajo.':'Copy the long key BotFather gives you and paste it below.'}</li><li>${lang==='es'?'Escríbele hola a tu bot y toca Detectar mi chat. Esto se hace una sola vez.':'Send hello to your bot and click Detect my chat. You only do this once.'}</li></ol></div></div><form id="telegram-config-form" class="form-grid">
 <div class="field wide"><label>${lang==='es'?'Clave larga que te dio BotFather':'Long key from BotFather'}</label><span class="field-help">${lang==='es'?'Pégala completa. Queda guardada solo en este PC/VPS.':'Paste it complete. It stays saved only on this PC/VPS.'}</span><input type="password" name="bot_token" value="" placeholder="${v.bot_configured?(lang==='es'?'Bot guardado. Pega otro solo si quieres cambiarlo.':'Bot saved. Paste another only to replace it.'):'123456:ABC...'}"></div>
 <div class="field"><label>${lang==='es'?'Tu chat privado':'Your private chat'}</label><span class="field-help">${lang==='es'?'Solo este chat podrá hablar con el agente.':'Only this chat can talk to the agent.'}</span><input name="chat_id" value="${escapeHtml(v.chat_id||'')}" placeholder="${lang==='es'?'Detectar después de escribirle al bot':'Detect after messaging the bot'}"></div>
 <div class="field"><label>${lang==='es'?'Idioma del manager':'Manager language'}</label><select name="language"><option value="es" ${v.language!=='en'?'selected':''}>Español</option><option value="en" ${v.language==='en'?'selected':''}>English</option></select></div>
 <label class="field wide"><input type="checkbox" name="enabled" ${v.enabled?'checked':''}> ${lang==='es'?'Activar conversación por Telegram':'Enable Telegram conversation'}</label>
 <div class="field wide onboarding-step-actions"><button class="btn primary" type="submit">${lang==='es'?'Guardar Telegram':'Save Telegram'}</button><button class="btn" type="button" onclick="detectTelegramChats()">${lang==='es'?'Detectar mi chat':'Detect my chat'}</button><button class="btn" type="button" onclick="testTelegram()">${lang==='es'?'Enviar prueba':'Send test'}</button></div>
 </form><div id="telegram-results"></div><p class="notice">${lang==='es'?'No puedo crear el bot por ti porque Telegram entrega la clave dentro de BotFather. Sí puedo guardar la clave, detectar tu chat y dejar el manager listo para responder desde Telegram.':'I cannot create the bot for you because Telegram gives the key inside BotFather. I can save the key, detect your chat, and keep the manager ready to reply through Telegram.'}</p>`;
 qs('#telegram-config-form').addEventListener('submit',saveTelegramConfig);
}
function renderMigrationPanel(){
 qs('#migration-panel').innerHTML=`<div class="next-step"><div><b>${lang==='es'?'Cambiar de equipo sin perder memoria':'Move device without losing memory'}</b><p>${lang==='es'?'Crea una copia segura de esta instalación o trae una copia anterior. Incluye chat, marca, productos, configuración y memoria del dashboard.':'Create a safe copy of this install or bring back an earlier one. It includes chat, brand, products, setup, and dashboard memory.'}</p></div><div class="mode-actions"><button class="btn primary" type="button" onclick="downloadMigrationBackup()">${lang==='es'?'Crear copia segura':'Create safe copy'}</button><button class="btn" type="button" onclick="qs('#migration-restore-file').click()">${lang==='es'?'Traer copia anterior':'Restore backup'}</button><input id="migration-restore-file" class="hidden" type="file" accept=".tar.gz,.tgz,.zip,application/gzip,application/zip" onchange="restoreMigrationBackup(event)"></div></div><div id="migration-result"></div><p class="notice">${lang==='es'?'Esa copia puede incluir claves privadas. Guárdala como guardarías una llave de tu negocio.':'The backup may contain private keys. Store it like a key to your business.'}</p>`;
}
function renderLocalNetworkPanel(){
 const box=qs('#local-network-panel');if(!box)return;
 const net=state.local_network_access||{};
 if(net.install_environment==='cloud'){box.innerHTML='';return}
 const enabled=Boolean(net.enabled);
 const active=Boolean(net.active);
 const url=net.lan_url||'';
 const status=enabled?(active?(lang==='es'?'Activo':'Active'):(lang==='es'?'Reiniciando':'Restarting')):(lang==='es'?'Apagado':'Off');
 const body=lang==='es'
  ? 'Actívalo solo cuando quieras abrir este dashboard desde tu teléfono. El teléfono debe estar conectado al mismo Wi‑Fi o red local, y seguirá pidiendo tu contraseña.'
  : 'Turn this on only when you want to open this dashboard from your phone. The phone must be on the same Wi‑Fi or local network, and your password is still required.';
 const linkBlock=enabled?`<div class="guide-card"><b>${lang==='es'?'Enlace para tu teléfono':'Phone link'}</b><p>${url?escapeHtml(url):(lang==='es'?'No pude detectar el IP automáticamente. Usa el IP local de este computador con el puerto '+escapeHtml(String(net.port||7871))+'.':'I could not detect the IP automatically. Use this computer local IP with port '+escapeHtml(String(net.port||7871))+'.')}</p><div class="onboarding-step-actions">${url?`<button class="btn primary" type="button" onclick="copyCommand(${JSON.stringify(url).replaceAll('"','&quot;')})">${lang==='es'?'Copiar enlace':'Copy link'}</button>`:''}<button class="btn ask-btn" type="button" onclick="openChat(${chatArg(lang==='es'?'Quiero abrir el dashboard desde mi teléfono. Explícame los pasos simples y qué revisar si no carga.':'I want to open the dashboard from my phone. Explain the simple steps and what to check if it does not load.')})">${t('ask_agent')}</button></div></div>`:'';
 const restartNote=net.restart_needed?`<p class="notice">${lang==='es'?'Estoy aplicando el cambio. Si la página se desconecta unos segundos, vuelve a abrir el enlace cuando termine.':'Applying the change. If the page disconnects for a few seconds, reopen the link when it finishes.'}</p>`:'';
 box.innerHTML=`<section class="chatgpt-connect-card local-network-card ${enabled?'ready':''}"><div class="chatgpt-connect-head"><div><h3>${lang==='es'?'Ver desde mi teléfono':'View from my phone'}</h3><p>${body}</p></div><span class="badge ${enabled?'ok':'warn'}">${status}</span></div><div class="model-route-grid"><div class="model-route-card"><span>1</span><b>${lang==='es'?'Mismo Wi‑Fi':'Same Wi‑Fi'}</b><p>${lang==='es'?'Tu teléfono y este computador deben estar en la misma red.':'Your phone and this computer must be on the same network.'}</p></div><div class="model-route-card"><span>2</span><b>${lang==='es'?'Con contraseña':'Password protected'}</b><p>${lang==='es'?'Aunque alguien vea el enlace, necesita la contraseña del dashboard para acciones y datos protegidos.':'Even if someone sees the link, the dashboard password is required for protected data and actions.'}</p></div></div>${linkBlock}${restartNote}<div class="mode-actions"><button class="btn ${enabled?'':'primary'}" type="button" onclick="setLocalNetworkAccess(true)">${lang==='es'?'Activar para teléfono':'Turn on phone access'}</button><button class="btn ${enabled?'primary':''}" type="button" onclick="setLocalNetworkAccess(false)">${lang==='es'?'Apagar acceso por Wi‑Fi':'Turn off Wi‑Fi access'}</button></div></section>`;
}
function renderCloudAccessPanel(){
 qs('#cloud-access-panel').innerHTML=`<div class="next-step"><div><b>${lang==='es'?'Mantener acceso cuando estás en la nube':'Keep cloud dashboard access'}</b><p>${lang==='es'?'Si este dashboard ya abrió desde tu red actual, este botón autoriza esta red en DigitalOcean. Úsalo cuando cambies de Wi-Fi antes de cerrar la página.':'If this dashboard already opened from your current network, this button authorizes this network in DigitalOcean. Use it when you change Wi-Fi before closing the page.'}</p></div><div class="mode-actions"><button class="btn" type="button" onclick="refreshCloudAccess()">${lang==='es'?'Permitir esta red':'Allow this network'}</button></div></div><div id="cloud-access-result"></div><p class="notice">${lang==='es'?'Si el dashboard no carga porque tu IP ya cambió, este botón no puede ayudarte todavía. Recupera entrada desde el portal de DigitalOcean, SSH o la consola web; después vuelve aquí para dejar la nueva red guardada.':'If the dashboard does not load because your IP already changed, this button cannot help yet. Recover access from the DigitalOcean portal, SSH, or web console; then return here to save the new network.'}</p>`;
}
function renderUpdateRollbackPanel(){
 qs('#update-rollback-panel').innerHTML=`<div class="next-step"><div><b>${lang==='es'?'Volver a una versión anterior':'Restore previous update'}</b><p>${lang==='es'?'Antes de instalar una actualización oficial, guardo una copia de seguridad. Conservo las últimas 3 por si necesitas volver a algo que ya funcionaba.':'Before installing an official update, I save a backup. The last 3 are kept so you can return to something that was working.'}</p></div><div class="mode-actions"><button class="btn" type="button" onclick="loadUpdateSnapshots(true)">${lang==='es'?'Ver copias guardadas':'View saved copies'}</button></div></div><div id="update-snapshot-list"></div>`;
 loadUpdateSnapshots(false);
}
function updateCardsMarkup(info){
 const cards=(info?.improvements||[]).map(item=>`<div class="update-card"><span>${escapeHtml(item.impact||'Optimización')}</span><b>${escapeHtml(item.title||'Mejora incluida')}</b><p>${escapeHtml(item.body||'Actualización publicada desde el canal oficial.')}</p></div>`).join('');
 return `<div class="update-cards">${cards}</div>`;
}
function updateWarningsMarkup(info){
 const warnings=info?.warnings||[];if(!warnings.length)return '';
 return `<div class="update-cards">${warnings.map(item=>`<div class="update-card"><span>${lang==='es'?'Atención':'Warning'}</span><b>${escapeHtml(localText(item.title||''))}</b><p>${escapeHtml(localText(item.body||''))}</p></div>`).join('')}</div>`;
}
function renderUpdateBanner(info){
 const box=qs('#update-banner');if(!box)return;
 if(!info||!info.available){box.classList.add('hidden');box.innerHTML='';return}
 box.classList.remove('hidden');
 box.innerHTML=`<div><b>${lang==='es'?'Actualización oficial disponible':'Official update available'}: ${escapeHtml(info.latest_version||'')}</b><p>${lang==='es'?'Antes de instalarla puedes ver qué mejora. Crearé una copia de seguridad automática.':'Review what improved before installing. I will create an automatic backup.'}</p></div><button class="btn primary" type="button" onclick="showUpdateDetails()">${lang==='es'?'Ver mejoras e instalar':'View improvements and install'}</button>`;
}
function renderDeferredOnboardingBanner(){
 const box=qs('#deferred-onboarding-banner');if(!box)return;
 const onboarding=state.onboarding||{};
 const deferred=Boolean(onboarding.deferred||onboarding.skipped||onboarding.requires_repair);
 if(!deferred){box.classList.add('hidden');box.innerHTML='';return}
 const reasons=(onboarding.deferred_reasons||onboarding.repair_reasons||[]).filter(Boolean);
 const labelMap={
  licencia:lang==='es'?'licencia':'license',
  conexion_facebook:lang==='es'?'Facebook':'Facebook',
  cuenta_publicitaria:lang==='es'?'cuenta publicitaria':'ad account',
  cerebro_agente:lang==='es'?'ChatGPT':'ChatGPT',
  telegram:'Telegram',
  entrevista_negocio:lang==='es'?'entrevista del negocio':'business interview',
  branding_creativos:lang==='es'?'marca y creativos':'brand and creatives',
  campanas_anuncios:lang==='es'?'campañas previas':'past campaigns',
  conexion_meta:lang==='es'?'Facebook':'Facebook',
  destinos:lang==='es'?'página y web':'Page and website',
  datos_reales:lang==='es'?'datos reales':'real data',
  perfil_negocio:lang==='es'?'perfil del negocio':'business profile'
 };
 const summary=reasons.length?reasons.slice(0,3).map(reason=>labelMap[reason]||reason).join(', '):(lang==='es'?'algunos pasos':'some steps');
 box.classList.remove('hidden');
 box.innerHTML=`<div class="deferred-onboarding-copy"><span class="pulse-dot"></span><div><b>${lang==='es'?'Completa la configuración cuando puedas':'Finish setup when you can'}</b><p>${lang==='es'?`Falta revisar: ${summary}. Puedes usar el dashboard, pero el agente funcionará mejor cuando termines.`:`Still to review: ${summary}. You can use the dashboard, but the agent works better after this is done.`}</p></div></div><button class="btn primary" type="button" onclick="resumeOnboarding()">${lang==='es'?'Completar ahora':'Finish now'}</button>`;
}
function showUpdateDetails(){
 if(!updateInfo)return;
 const box=qs('#confirm-overlay');box.innerHTML=`<div class="confirm-card guide-modal-card"><div class="next-step"><div><h2>${lang==='es'?'Actualización oficial':'Official update'}</h2><p>${lang==='es'?'Versión':'Version'}: ${escapeHtml(updateInfo.current_version||'')} → ${escapeHtml(updateInfo.latest_version||'')}</p></div><button class="btn" type="button" onclick="closeConfirm()">${lang==='es'?'Cerrar':'Close'}</button></div>${updateWarningsMarkup(updateInfo)}${updateCardsMarkup(updateInfo)}<p class="notice">${lang==='es'?'Antes de cambiar archivos crearé una copia de seguridad. Si algo falla, podrás volver desde Configuración. Meta seguirá ejecutando lo que ya esté activo fuera del dashboard.':'Before changing files I will create a backup. If something fails, you can return from Setup. Meta will keep running anything already active outside the dashboard.'}</p><div class="confirm-actions"><button class="btn" type="button" onclick="closeConfirm()">${lang==='es'?'Ahora no':'Not now'}</button><button class="btn primary" type="button" onclick="applyDashboardUpdate()">${lang==='es'?'Crear copia e instalar':'Backup and install'}</button></div></div>`;box.classList.add('open');
}
async function checkForUpdates(force=false){
 if(updateCheckStarted&&!force)return;
 if(!dashboardPassword()&&!force)return;
 updateCheckStarted=true;
 try{const res=await api('/api/update/check',{method:'POST',body:'{}'});updateInfo=res.result||null;renderUpdateBanner(updateInfo);if(force)toast(updateInfo?.available?(lang==='es'?'Actualización disponible':'Update available'):(lang==='es'?'Ya tienes la versión más reciente':'You already have the latest version'))}catch(err){if(force)toast(lang==='es'?'No pude revisar actualizaciones':'Could not check for updates')}
}
async function applyDashboardUpdate(){
 const box=qs('#confirm-overlay');box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Instalando actualización':'Installing update'}</h2><p>${lang==='es'?'Estoy descargando el paquete oficial y conservando tus datos locales. El dashboard se reiniciará al terminar.':'Downloading the official package and keeping local data. The dashboard will restart when finished.'}</p></div>`;box.classList.add('open');
 try{const res=await api('/api/update/apply',{method:'POST',body:'{}'});box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Actualización instalada':'Update installed'}</h2><p>${escapeHtml(res.result?.message||'')}</p><p class="notice">${lang==='es'?'Copia guardada':'Saved backup'}: ${escapeHtml(res.result?.snapshot?.id||'')}</p><p class="notice">${lang==='es'?'Si la página tarda unos segundos, espera y recarga.':'If the page takes a few seconds, wait and refresh.'}</p></div>`;toast(lang==='es'?'Actualización instalada':'Update installed')}catch(err){box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'No pude actualizar':'Could not update'}</h2><p>${escapeHtml(err.message||String(err))}</p><p class="notice">${lang==='es'?'Si la copia se creó, estará disponible en Configuración para restaurar.':'If a backup was created, it will be available in Setup to restore.'}</p><div class="confirm-actions"><button class="btn primary" type="button" onclick="closeConfirm()">${lang==='es'?'Cerrar':'Close'}</button></div></div>`}
}
function setupSimpleText(item){
 const es={
  license_key:['Licencia','Pega y activa el código que recibiste al comprar.'],
  ad_account:['Cuenta publicitaria','Elige la cuenta de Meta Ads que quieres que el agente cuide.'],
  access_token:['Clave de Meta','Pega la clave de acceso que creaste siguiendo tus imágenes de guía.'],
  page_id:['Página de Facebook','Elige la página desde donde saldrán tus anuncios.'],
  landing_url:['Link de tu web','Guarda la página a la que llegarán las personas.'],
  dashboard_token:['Contraseña del dashboard','Crea una contraseña para proteger acciones importantes.'],
  hermes_runtime:['Chat con agente','Falta instalar o conectar Hermes para que el chat use tu sesión de ChatGPT/Codex.'],
  hermes_auth:['ChatGPT/Codex','Conecta Hermes con tu cuenta de ChatGPT/Codex.'],
  openai_compatible_model:['Modelo del agente','Si usas MiniMax M3 u otra API, falta guardar URL, modelo y clave.'],
  social_cli:['Conexión con Meta','Falta la pieza local que ayuda a leer datos de Meta.'],
  daily_report:['Lectura diaria','Todavía no hay resumen diario. Puedes tocar Actualizar o pedírselo al agente.'],
  gemini_key:['Crear imágenes','Opcional: falta conectar la clave para generar imágenes reales.'],
  telegram_bot:['Telegram','Opcional: falta la clave del bot si quieres hablar desde Telegram.'],
  telegram_chat:['Telegram','Opcional: falta elegir tu chat privado.'],
  creative_index:['Ideas de anuncios','Todavía no hay ideas de anuncios creadas.'],
  latest_upload:['Publicar anuncios','Todavía no hay anuncios preparados para revisar.'],
 };
 const en={
  license_key:['License','Paste and activate the code you received after purchase.'],
  ad_account:['Ad account','Choose the Meta Ads account this agent should manage.'],
  access_token:['Meta key','Paste the access key you created with your screenshots.'],
  page_id:['Facebook Page','Choose the Page your ads will publish from.'],
  landing_url:['Website link','Save the page people will visit.'],
  dashboard_token:['Dashboard password','Create a password to protect important actions.'],
  hermes_runtime:['Agent chat','Install or connect Hermes so chat can use your ChatGPT/Codex session.'],
  hermes_auth:['ChatGPT/Codex','Connect Hermes with your ChatGPT/Codex account.'],
  openai_compatible_model:['Agent model','If you use MiniMax M3 or another API, save URL, model, and key.'],
  social_cli:['Meta connection','The local helper for reading Meta data is missing.'],
  daily_report:['Daily reading','No daily brief exists yet. Click Refresh or ask the agent.'],
  gemini_key:['Create images','Optional: connect the key for real image generation.'],
  telegram_bot:['Telegram','Optional: add the bot key if you want to chat from Telegram.'],
  telegram_chat:['Telegram','Optional: choose your private chat.'],
  creative_index:['Ad ideas','No ad ideas have been created yet.'],
  latest_upload:['Publish ads','No ads are prepared for review yet.'],
 };
 const dict=lang==='es'?es:en;const found=dict[item.key];
 if(found)return {title:found[0],body:found[1]};
 return {title:localText(item.label),body:localText(item.action||item.detail||'')};
}
function renderSetupBeginnerSummary(setup){
 const all=setup.sections.flatMap(sec=>sec.items||[]);
 const blocked=all.filter(i=>i.status==='blocked');
 const warnings=all.filter(i=>i.status==='warn');
 const list=(blocked.length?blocked:warnings).slice(0,4);
 const good=!blocked.length&&!warnings.length;
 const title=good?(lang==='es'?'Todo lo importante se ve listo':'The important pieces look ready'):(blocked.length?(lang==='es'?'Lo que falta primero':'Fix these first'):(lang==='es'?'Cosas para revisar':'Things to review'));
 const body=good?(lang==='es'?'Tu configuración principal está en verde. Si algo te confunde, pregúntale al agente antes de activar piloto automático.':'Your main setup is green. If anything feels unclear, ask the agent before enabling autopilot.'):(lang==='es'?'No necesitas entender cada detalle técnico. Empieza por estas tarjetas y el agente puede explicarte una por una.':'You do not need to understand every technical detail. Start with these cards and the agent can explain them one by one.');
 return `<div class="guide-panel setup-simple-panel"><div class="next-step"><div><b>${title}</b><p>${body}</p></div><button class="btn ask-btn" type="button" onclick="openChat(lang==='es'?'Explícame qué falta en mi configuración con palabras muy simples y dime qué hago primero.':'Explain what is missing in my setup in very simple words and tell me what to do first.')">${t('ask_agent')}</button></div>${list.length?`<div class="trust-grid">${list.map(item=>{const copy=setupSimpleText(item);return `<div class="trust-card"><b>${statusLabel(item.status)} · ${escapeHtml(copy.title)}</b><p>${escapeHtml(copy.body)}</p></div>`}).join('')}</div>`:''}</div>`;
}
function renderSetupTechnicalDetails(setup){
 return `<details class="fallback-details setup-technical-details"><summary>${lang==='es'?'Revisión técnica para soporte':'Technical review for support'}</summary>${setup.sections.map(sec=>`<div class="section"><div class="head"><b>${localText(sec.title)}</b></div><div class="body">${sec.items.map(i=>`<div class="log-item"><b>${statusLabel(i.status)} - ${localText(i.label)}</b><br>${localText(i.detail||'')}${i.action?`<br><span class="notice">${localText(i.action)}</span>`:''}</div>`).join('')}</div></div>`).join('')}</details>`;
}
function renderSetup(){const setup=state.setup;const counts=setup.summary.counts;renderModeControl();renderGuardrails();renderOnboarding();renderLicensePanel();renderAgencyPanel();renderSetupConfig();renderChatGptPanel();renderTelegramPanel();renderLocalNetworkPanel();renderMigrationPanel();renderUpdateRollbackPanel();renderCloudAccessPanel();qs('#setup-summary').innerHTML=`<div class="kpis">${kpi(t('ok'),counts.ok||0)}${kpi(t('warnings'),counts.warn||0)}${kpi(t('blocked'),counts.blocked||0)}${kpi(t('live_ready'),setup.summary.live_ads_ready?t('live_ready_yes'):t('live_ready_no'))}</div>`;qs('#setup-sections').innerHTML=renderSetupBeginnerSummary(setup)+renderSetupTechnicalDetails(setup)}
function audienceText(value){
 const raw=String(value||'');if(lang!=='es')return raw;
 const exact={
  'Broad / Advantage+ prospecting':'Llegar a personas nuevas',
  'Prospección amplia / Advantage+':'Llegar a personas nuevas',
  'Interest testing':'Personas con intereses relacionados',
  'Prueba por intereses':'Personas con intereses relacionados',
  'Warm retargeting':'Personas que ya te conocen',
  'Retargeting tibio':'Personas que ya te conocen',
  'Lookalike from seed audience':'Personas parecidas a tus mejores clientes',
  'Lookalike desde audiencia semilla':'Personas parecidas a tus mejores clientes',
  'Use after the seed source is clean and large enough.':'Úsalo cuando ya tengas suficientes visitas o compradores reales.',
  'Úsalo cuando la audiencia semilla esté limpia y tenga suficiente tamaño.':'Úsalo cuando ya tengas suficientes visitas o compradores reales.',
  'Las audiencias tibias suelen convertir mejor, pero se fatigan rápido si son pequeñas.':'Las personas que ya te conocen suelen comprar más fácilmente, pero el mismo anuncio puede cansarlas si son pocas.',
  'Lanza primero amplia + una prueba de intereses.':'Empieza llegando a personas nuevas y prueba un grupo con intereses.',
  'Separa retargeting si ya existe tráfico tibio.':'Si ya tienes visitas o mensajes, prepara un grupo aparte para esas personas.',
  'Crea lookalike solo cuando la data semilla y el consentimiento estén claros.':'Prueba personas parecidas solo cuando tengas suficientes datos y permiso para usarlos.',
 };
 if(exact[raw])return exact[raw];
 if(raw.startsWith('Meta usually finds buyers faster'))return 'Empieza sin poner demasiados filtros. Las imágenes, textos y resultados ayudarán al agente a encontrar compradores.';
 if(raw.startsWith('Start with interests that describe'))return 'Prueba temas que ya le interesan a tu comprador, sin limitar demasiado el alcance.';
 if(raw.startsWith('Lookalikes can scale what already works'))return 'Las personas parecidas pueden ampliar lo que ya funciona, siempre que los datos de partida sean buenos.';
 return raw;
}
function audienceTargetingText(targeting){
 if(lang!=='es')return JSON.stringify(targeting||{});
 const value=targeting||{}, parts=[];
 if(value.locations?.length)parts.push(`Lugar: ${value.locations.join(', ')}`);
 if(value.age)parts.push(`Edad: ${value.age}`);
 if(value.interests?.length)parts.push(`Intereses: ${value.interests.join(', ')}`);
 if(value.sources?.length)parts.push(`Ya te conocen por: ${value.sources.map(source=>source==='Pixel / IG engagement / leads'?'visitas web, Instagram o formularios':source).join(', ')}`);
 if(value.window)parts.push('Probar durante: 7, 14 y 30 días');
 if(value.exclusions)parts.push('Evitar mostrarlo a compradores recientes, si puedes identificarlos');
 if(value.seed)parts.push('Basado en: visitantes, compradores o personas que interactuaron');
 if(value.sizes)parts.push('Probar cercanía: 1%, 2% y 5%');
 return parts.join(' · ')||'El agente ajustará este público con lo que le cuentes.';
}
function renderAudience(){
 const r=state.audience_strategy||{};const box=qs('#audience-result');if(!box)return;
 if(!r.strategies){box.innerHTML=`<p class="notice">${lang==='es'?'Completa estas preguntas para que el agente te sugiera a qué personas mostrar tus anuncios. El agente no sube listas de clientes todavía; solo te dirá si valdría la pena después.':'Fill the form to create a clear targeting recommendation. The agent does not upload customer lists yet; it only checks whether that would make sense later.'}</p>`;return}
 const ready=r.lookalike_readiness?.ready;
 box.innerHTML=`<div class="trust-grid"><div class="trust-card"><b>${t('lookalike_status')}</b><p>${ready?(lang==='es'?'Ya tienes información suficiente para probar con personas parecidas a tus clientes o visitantes.':'You have enough information to test with people similar to your customers or visitors.'):(lang==='es'?'Todavía no conviene. Primero reúne visitas, interacciones o una lista de clientes que te dio permiso.':'Not yet. First gather visits, interactions, or a customer list with permission.')}</p></div><div class="trust-card"><b>${lang==='es'?'Qué falta':'What is missing'}</b><p>${escapeHtml((r.blockers&&r.blockers.length?r.blockers.map(audienceText):[lang==='es'?'Nada importante por resolver.':'Nothing important to resolve.']).join(' '))}</p></div><div class="trust-card"><b>${lang==='es'?'Producto':'Product'}</b><p>${escapeHtml(r.product||'')}</p></div></div><h3 style="font-size:13px;margin:8px 0">${t('recommended_audiences')}</h3>${r.strategies.map(s=>`<div class="rec-card"><h3>${escapeHtml(audienceText(s.name))}</h3><p class="notice">${escapeHtml(audienceText(s.use_when))}</p><div class="action-detail"><strong>${lang==='es'?'Por qué':'Why'}:</strong> ${escapeHtml(audienceText(s.why))}<br><strong>${lang==='es'?'Personas que verá':'People it reaches'}:</strong> ${escapeHtml(audienceTargetingText(s.targeting))}</div></div>`).join('')}<h3 style="font-size:13px;margin:8px 0">${t('next_steps')}</h3>${(r.next_steps||[]).map(step=>`<div class="log-item">${escapeHtml(audienceText(step))}</div>`).join('')}`;
}
function spark(vals){const w=220,h=46,max=Math.max(...vals,1),min=Math.min(...vals,0),range=max-min||1;const pts=vals.map((v,i)=>`${i*(w/(vals.length-1))},${h-((v-min)/range*h*.78+5)}`).join(' ');return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="#7c5cff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><line x1="0" y1="${h-4}" x2="${w}" y2="${h-4}" stroke="#2a2a30"/></svg>`}
function campaignButtons(c){
 if(c.status==='paused')return `<button class="btn primary" onclick="campaignAction('resume','${c.id}')">${t('resume')}</button><button class="btn" onclick="budgetPrompt('${c.id}',${c.daily_budget})">${t('adjust_budget')}</button><button class="btn" onclick="showDetails('${c.id}')">${t('details')}</button>`;
 if(c.health==='winning')return `<button class="btn primary" onclick="budgetPrompt('${c.id}',${Math.round(Number(c.daily_budget||0)*1.15)})">${t('increase_budget')}</button><button class="btn" onclick="showDetails('${c.id}')">${t('details')}</button><button class="btn" onclick="budgetPrompt('${c.id}',${c.daily_budget})">${t('adjust_budget')}</button>`;
 if(c.health==='fatigue')return `<button class="btn primary" onclick="generateRefresh('${c.id}')">${t('refresh_creative')}</button><button class="btn" onclick="budgetPrompt('${c.id}',${c.daily_budget})">${t('adjust_budget')}</button><button class="btn danger" onclick="campaignAction('pause','${c.id}')">${t('pause')}</button>`;
 if(c.health==='losing')return `<button class="btn danger" onclick="campaignAction('pause','${c.id}')">${t('pause')}</button><button class="btn primary" onclick="generateRefresh('${c.id}')">${t('refresh_creative')}</button><button class="btn" onclick="budgetPrompt('${c.id}',${c.daily_budget})">${t('adjust_budget')}</button>`;
 return `<button class="btn" onclick="budgetPrompt('${c.id}',${c.daily_budget})">${t('adjust_budget')}</button><button class="btn" onclick="generateRefresh('${c.id}')">${t('refresh_creative')}</button><button class="btn danger" onclick="campaignAction('pause','${c.id}')">${t('pause')}</button>`;
}
function card(c){const draft=lang==='es'?`Analiza la campaña ${c.name}. Está como ${statusText(c.health)} con ROAS ${Number(c.roas).toFixed(2)}x y CPA ${fmtMoney(c.cpa)}. ¿Qué harías como manager?`:`Analyze campaign ${c.name}. It is ${statusText(c.health)} with ROAS ${Number(c.roas).toFixed(2)}x and CPA ${fmtMoney(c.cpa)}. What would you do as manager?`;return `<article class="card aurora-card" data-health="${c.health}"><span class="starfield" aria-hidden="true"></span><div class="top"><h3>${escapeHtml(demoCampaignName(c.name))}</h3><span class="badge ${c.health}">${statusText(c.health)}</span></div><div class="metrics">${metric('Spend',fmtMoney(c.spend))}${metric('ROAS',Number(c.roas).toFixed(2)+'x')}${metric('CPA',fmtMoney(c.cpa))}${metric('CTR',fmtPct(c.ctr))}</div>${spark(c.trend)}<div class="actions">${campaignButtons(c)}<button class="btn ask-btn" onclick="openChat(${JSON.stringify(draft).replaceAll('"','&quot;')})">${t('ask_agent')}</button></div></article>`}
async function campaignAction(action,campaign_id){const res=await api('/api/action',{method:'POST',body:JSON.stringify({action,campaign_id})});const staged=res.result?.status==='pending';toast(staged?(lang==='es'?'Decisión enviada a aprobación':'Decision sent for approval'):(action==='resume'?t('toast_resume'):t('toast_action')));await load()}
async function applyRec(campaign_id,new_budget){const res=await api('/api/action',{method:'POST',body:JSON.stringify({action:'apply_recommendation',campaign_id,new_budget})});toast(res.result?.status==='pending'?(lang==='es'?'Cambio enviado a aprobación':'Change sent for approval'):t('toast_budget'));await load()}
function budgetDialog(campaign_id,current){
 const campaign=(state.metrics?.campaigns||[]).find(c=>c.id===campaign_id)||{};
 const safeCurrent=Number(current||campaign.daily_budget||0)||0;
 const suggestions=[safeCurrent,Math.round(safeCurrent*1.1),Math.round(safeCurrent*1.2)].filter((v,i,a)=>v>0&&a.indexOf(v)===i);
 const agentDraft=lang==='es'?`Revisa el presupuesto de ${campaign.name||'esta campaña'}. Está con presupuesto diario ${fmtMoney(safeCurrent)}, ROAS ${Number(campaign.roas||0).toFixed(2)}x y CPA ${fmtMoney(campaign.cpa)}. Dime cuánto pondrías y por qué antes de tocar nada.`:`Review the budget for ${campaign.name||'this campaign'}. Daily budget is ${fmtMoney(safeCurrent)}, ROAS ${Number(campaign.roas||0).toFixed(2)}x and CPA ${fmtMoney(campaign.cpa)}. Tell me what you would set and why before touching anything.`;
 const box=qs('#confirm-overlay');
 box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Ajustar presupuesto con calma':'Adjust budget calmly'}</h2><p>${lang==='es'?'Elige el nuevo máximo diario. Si no estás seguro, pregúntale al manager primero y vuelve a esta decisión después.':'Choose the new daily maximum. If you are not sure, ask the manager first and come back to this decision.'}</p><form class="unlock-form" onsubmit="submitBudgetDialog(event,${chatArg(campaign_id)})"><label>${lang==='es'?'Nuevo presupuesto diario':'New daily budget'}<input id="budget-dialog-value" type="number" min="1" step="1" value="${safeCurrent}" inputmode="decimal"></label>${suggestions.length?`<div class="mode-actions">${suggestions.map(v=>`<button class="btn" type="button" onclick="qs('#budget-dialog-value').value='${v}'">${fmtMoney(v)}</button>`).join('')}</div>`:''}<p class="notice">${lang==='es'?'Si supera tus reglas, quedará en aprobación antes de tocar Meta Ads.':'If it exceeds your rules, it will go to approval before touching Meta Ads.'}</p><div class="confirm-actions"><button class="btn" type="button" onclick="closeConfirm()">${lang==='es'?'Cancelar':'Cancel'}</button><button class="btn ask-btn" type="button" onclick="closeConfirm();openChat(${chatArg(agentDraft)})">${lang==='es'?'Preguntar al manager':'Ask manager'}</button><button class="btn primary" type="submit">${lang==='es'?'Enviar cambio':'Send change'}</button></div></form></div>`;
 box.classList.add('open');
 setTimeout(()=>qs('#budget-dialog-value')?.focus(),30);
}
async function submitBudgetDialog(event,campaign_id){event.preventDefault();const val=Number(qs('#budget-dialog-value')?.value||0);if(!val||val<1){toast(lang==='es'?'Escribe un presupuesto mayor a cero.':'Enter a budget greater than zero.');return}closeConfirm();const res=await api('/api/action',{method:'POST',body:JSON.stringify({action:'adjust_budget',campaign_id,new_budget:val})});toast(res.result?.status==='pending'?(lang==='es'?'Cambio enviado a aprobación':'Change sent for approval'):t('toast_budget'));await load()}
async function budgetPrompt(campaign_id,current){budgetDialog(campaign_id,current)}
async function runAgent(){await api('/api/action',{method:'POST',body:JSON.stringify({action:'run_agent'})});toast(t('toast_daily'));await load()}
async function refreshInsights(){const res=await api('/api/action',{method:'POST',body:JSON.stringify({action:'refresh_insights'})});if(res.result&&res.result.ok){toast(lang==='es'?'Datos reales actualizados desde Meta.':'Real Meta data refreshed.')}else{toast(lang==='es'?'No pude leer datos reales todavía. Revisa tu clave de Meta y la cuenta elegida.':'Could not read real data yet. Check your Meta key and chosen account.')}await load();return res}
async function exportCsv(){const r=await api('/api/export');toast(t('toast_export')+r.path)}
async function approvePending(id){const item=(state.pending||[]).find(p=>p.id===id);if(item&&item.type==='create_campaign'&&item.payload?.final_status==='ACTIVE'){const ok=await showDecisionConfirm({title:lang==='es'?'Esta campaña puede empezar a gastar':'This campaign can start spending',body:lang==='es'?'Al aprobar, se creará o encenderá como ACTIVA y podrá usar el presupuesto elegido. Revisa esto como si le dieras luz verde a un manager humano.':'When approved, it will be created or turned on as ACTIVE and may use the selected budget. Review this like giving a human manager the green light.',items:[item.payload?.name||item.payload?.campaign_name||item.type,lang==='es'?'La aprobación debe salir de un botón exacto o de una frase exacta; el agente no puede decidir solo.':'Approval must come from an exact button or exact phrase; the agent cannot decide alone.'],confirmLabel:lang==='es'?'Sí, aprobar activa':'Yes, approve active',agentDraft:lang==='es'?`Explícame esta aprobación de campaña activa antes de que yo decida. ¿Qué riesgo tiene y qué debería revisar?`:`Explain this active campaign approval before I decide. What is the risk and what should I review?`});if(!ok)return []}const res=await api('/api/approve',{method:'POST',body:JSON.stringify({approval_id:id})});const attempted=(res.result||[])[0]||{};toast(attempted.status==='approved'?t('toast_approval'):(lang==='es'?'No se pudo ejecutar. La decisión sigue pendiente para reintentar.':'Execution failed. The decision remains pending so you can retry.'));await load();return res.result||[]}
async function setMode(mode){if(mode==='live'){const ok=await showDecisionConfirm({title:lang==='es'?'Activar piloto automático':'Turn on autopilot',body:lang==='es'?'El agente podrá ejecutar acciones reales solo cuando entren dentro de tus reglas. Lo que se salga de los límites seguirá pidiendo aprobación.':'The agent can execute real actions only when they fit your rules. Anything outside the limits will still ask for approval.',items:[lang==='es'?'Leer datos reales no cambia nada en Meta.':'Reading real data does not change Meta.',lang==='es'?'Piloto automático sí puede tocar campañas dentro de tus reglas.':'Autopilot can touch campaigns inside your rules.'],confirmLabel:lang==='es'?'Activar piloto':'Turn on autopilot',agentDraft:lang==='es'?'Antes de activar piloto automático, revisa mis reglas y dime si están prudentes para mi cuenta.':'Before turning on autopilot, review my rules and tell me if they are prudent for my account.'});if(!ok)return}await api('/api/mode',{method:'POST',body:JSON.stringify({mode,live_actions_enabled:mode==='live'})});toast(mode==='live'?(lang==='es'?'Piloto automático activado':'Autopilot enabled'):(lang==='es'?'Modo con supervisión activado':'Supervised mode enabled'));await load()}
async function setLocalNetworkAccess(enabled){
 const box=qs('#local-network-panel');
 if(box)box.insertAdjacentHTML('afterbegin',`<div class="guide-card"><p>${enabled?(lang==='es'?'Preparando enlace para tu teléfono...':'Preparing phone link...'):(lang==='es'?'Apagando acceso por Wi‑Fi...':'Turning off Wi‑Fi access...')}</p></div>`);
 const res=await api('/api/local-network-access',{method:'POST',body:JSON.stringify({enabled})});
 const result=res.result||res;
 if(result.restarting){
  toast(enabled?(lang==='es'?'Activando acceso por Wi‑Fi. El dashboard se reiniciará.':'Turning on Wi‑Fi access. The dashboard will restart.'):(lang==='es'?'Apagando acceso por Wi‑Fi. El dashboard se reiniciará.':'Turning off Wi‑Fi access. The dashboard will restart.'));
  setTimeout(()=>window.location.reload(),2200);
  return;
 }
 toast(enabled?(lang==='es'?'Acceso para teléfono activado.':'Phone access enabled.'):(lang==='es'?'Acceso por Wi‑Fi apagado.':'Wi‑Fi access turned off.'));
 await load();
}
async function saveGuardrails(e){e.preventDefault();const form=e.target;const data=Object.fromEntries(new FormData(form).entries());data.require_approval_for_resume=form.require_approval_for_resume.checked;data.require_approval_for_new_campaigns=form.require_approval_for_new_campaigns.checked;data.require_approval_for_creatives=form.require_approval_for_creatives.checked;await api('/api/guardrails',{method:'POST',body:JSON.stringify(data)});toast(lang==='es'?'Reglas guardadas':'Rules saved');await load()}
async function saveProfitabilityRules(e){e.preventDefault();const form=e.target;const data=Object.fromEntries(new FormData(form).entries());await api('/api/profitability-rules',{method:'POST',body:JSON.stringify(data)});toast(lang==='es'?'Reglas de rentabilidad guardadas':'Profitability rules saved');await load()}
async function saveTelegramConfig(e){e.preventDefault();const form=e.target;const data=Object.fromEntries(new FormData(form).entries());data.enabled=form.enabled.checked;await api('/api/telegram/config',{method:'POST',body:JSON.stringify(data)});toast(lang==='es'?'Telegram guardado':'Telegram saved');await load()}
async function fetchProtectedFile(path,opts={}){
 const headers={...(opts.headers||{})};const password=dashboardPassword();if(password)headers['X-Dashboard-Token']=password;
 let res=await fetch(path,{...opts,headers});
 if(res.status===401){const entered=await requestUnlock();if(entered){headers['X-Dashboard-Token']=entered;res=await fetch(path,{...opts,headers})}}
 if(!res.ok)throw new Error(await responseErrorMessage(res));
 return res;
}
async function downloadMigrationBackup(){
 const box=qs('#migration-result');if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Preparando respaldo seguro...':'Preparing secure backup...'}</p></div>`;
 try{
  const res=await fetchProtectedFile('/api/migration/export',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  const blob=await res.blob();const disposition=res.headers.get('Content-Disposition')||'';const match=disposition.match(/filename="([^"]+)"/);const filename=match?match[1]:'meta-ads-agent-respaldo.tar.gz';
  const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=filename;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  if(box)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'Respaldo creado':'Backup created'}</b><p>${lang==='es'?'Se descargó el archivo. Guárdalo en un lugar privado.':'The file downloaded. Store it somewhere private.'}</p></div>`;
 }catch(err){if(box)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude crear el respaldo':'Could not create backup'}</b><p>${escapeHtml(err.message||String(err))}</p></div>`}
}
let pendingMigrationFile=null;
function restoreMigrationBackup(event){
 const file=event.target.files&&event.target.files[0];event.target.value='';
 if(!file)return;pendingMigrationFile=file;
 const box=qs('#confirm-overlay');box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Restaurar respaldo':'Restore backup'}</h2><p>${lang==='es'?'Voy a reemplazar la memoria local de este dashboard por el respaldo seleccionado. Haré una copia interna de lo actual antes de restaurar.':'I will replace this dashboard local memory with the selected backup. I will make an internal copy of the current state before restoring.'}</p><p class="notice">${escapeHtml(file.name)} · ${Math.round(file.size/1024)} KB</p><div class="confirm-actions"><button class="btn" type="button" onclick="pendingMigrationFile=null;closeConfirm()">${lang==='es'?'Cancelar':'Cancel'}</button><button class="btn primary" type="button" onclick="confirmMigrationRestore()">${lang==='es'?'Restaurar':'Restore'}</button></div></div>`;box.classList.add('open');
}
function arrayBufferToBase64(buffer){let binary='';const bytes=new Uint8Array(buffer);const chunk=0x8000;for(let i=0;i<bytes.length;i+=chunk){binary+=String.fromCharCode.apply(null,bytes.subarray(i,i+chunk))}return btoa(binary)}
async function confirmMigrationRestore(){
 const file=pendingMigrationFile;pendingMigrationFile=null;closeConfirm();if(!file)return;
 const box=qs('#migration-result');if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Restaurando respaldo...':'Restoring backup...'}</p></div>`;
 try{
  const content_base64=arrayBufferToBase64(await file.arrayBuffer());
  const res=await api('/api/migration/import',{method:'POST',body:JSON.stringify({filename:file.name,content_base64})});
  const restored=(res.result?.restored||[]).join(', ');
  if(box)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'Respaldo restaurado':'Backup restored'}</b><p>${escapeHtml(res.result?.message||'')}</p><p class="notice">${escapeHtml(restored)}</p></div>`;
  toast(lang==='es'?'Respaldo restaurado':'Backup restored');await load();
 }catch(err){if(box)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude restaurar':'Could not restore'}</b><p>${escapeHtml(err.message||String(err))}</p></div>`}
}
async function refreshCloudAccess(){
 const box=qs('#cloud-access-result');if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Permitiendo que abras tu dashboard desde esta red...':'Allowing dashboard access from this network...'}</p></div>`;
 try{
  const res=await api('/api/cloud-access/refresh',{method:'POST',body:'{}'});
  if(box)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'Esta red ya puede entrar':'This network can now enter'}</b><p>${lang==='es'?'Ya puedes abrir el dashboard desde este lugar.':'You can now open the dashboard from this location.'}</p></div>`;
  toast(lang==='es'?'Acceso listo para esta red':'Access ready for this network');
 }catch(err){if(box)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude actualizar el acceso':'Could not refresh access'}</b><p>${escapeHtml(err.message||String(err))}</p></div>`}
}
function updateSnapshotMarkup(items){
 if(!items||!items.length)return `<div class="guide-card"><p class="notice">${lang==='es'?'Todavía no hay copias guardadas. Se crearán automáticamente antes de la próxima actualización oficial.':'No saved copies yet. They will be created automatically before the next official update.'}</p></div>`;
 return `<div class="update-cards">${items.map(item=>`<div class="update-card"><span>${escapeHtml(item.channel||'stable')}</span><b>${escapeHtml(item.version||'')}</b><p>${escapeHtml(new Date(item.created_at||Date.now()).toLocaleString())}</p><button class="btn" type="button" onclick="confirmUpdateRollback('${escapeHtml(item.id||'')}')">${lang==='es'?'Volver a esta versión':'Restore this version'}</button></div>`).join('')}</div>`;
}
async function loadUpdateSnapshots(force=false){
 const box=qs('#update-snapshot-list');if(!box)return;
 if(force)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Buscando copias guardadas...':'Looking for saved copies...'}</p></div>`;
 try{const res=await api('/api/update/snapshots');box.innerHTML=updateSnapshotMarkup(res.result||[])}catch(err){if(force)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude leer las copias':'Could not read saved copies'}</b><p>${escapeHtml(err.message||String(err))}</p></div>`}
}
function confirmUpdateRollback(snapshotId){
 if(!snapshotId)return;
 const box=qs('#confirm-overlay');box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Volver a una versión anterior':'Restore previous version'}</h2><p>${lang==='es'?'Voy a devolver el dashboard a esta copia guardada. Esto no deshace cambios que Meta ya haya realizado en campañas activas.':'I will return the dashboard to this saved copy. This does not undo changes Meta already made to active campaigns.'}</p><p class="notice">${escapeHtml(snapshotId)}</p><div class="confirm-actions"><button class="btn" type="button" onclick="closeConfirm()">${lang==='es'?'Cancelar':'Cancel'}</button><button class="btn primary" type="button" onclick="rollbackUpdateSnapshot('${escapeHtml(snapshotId)}')">${lang==='es'?'Volver ahora':'Restore now'}</button></div></div>`;box.classList.add('open');
}
async function rollbackUpdateSnapshot(snapshotId){
 const box=qs('#confirm-overlay');box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Volviendo a la versión elegida':'Restoring'}</h2><p>${lang==='es'?'Estoy usando la copia guardada y conservando una copia de lo que tienes ahora.':'Restoring the saved copy and keeping a copy of what you have now.'}</p></div>`;box.classList.add('open');
 try{const res=await api('/api/update/rollback',{method:'POST',body:JSON.stringify({snapshot_id:snapshotId})});box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Versión lista':'Version restored'}</h2><p>${escapeHtml(res.result?.message||'')}</p><p class="notice">${lang==='es'?'Copia de lo anterior':'Backup of previous state'}: ${escapeHtml(res.result?.rescue_snapshot_id||'')}</p></div>`;toast(lang==='es'?'Ya estás usando la versión anterior':'Previous version restored')}catch(err){box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'No pude volver a esa versión':'Could not restore'}</h2><p>${escapeHtml(err.message||String(err))}</p><div class="confirm-actions"><button class="btn primary" type="button" onclick="closeConfirm()">${lang==='es'?'Cerrar':'Close'}</button></div></div>`}
}
async function detectTelegramChats(){const res=await api('/api/telegram/detect',{method:'POST',body:'{}'});const rows=res.result||[];const box=qs('#telegram-results');if(!rows.length){box.innerHTML=`<p class="notice">${lang==='es'?'No encontré mensajes. Escríbele primero a tu bot en Telegram y vuelve a intentar.':'I found no messages. Message your bot in Telegram first, then try again.'}</p>`;return}box.innerHTML=rows.map(c=>`<div class="log-item"><b>${escapeHtml(c.label)} ${escapeHtml(c.username||'')}</b><br><button class="btn primary" type="button" onclick="selectTelegramChat('${escapeHtml(c.id)}',qs('#onboarding-flow')?.classList.contains('open'))">${lang==='es'?'Usar este chat':'Use this chat'}</button></div>`).join('')}
async function selectTelegramChat(id,fromOnboarding=false){await api('/api/telegram/config',{method:'POST',body:JSON.stringify(fromOnboarding?{chat_id:id,enabled:'true'}:{chat_id:id})});toast(lang==='es'?'Chat de Telegram guardado':'Telegram chat saved');await load();if(fromOnboarding){const steps=onboardingSteps();const idx=steps.findIndex(s=>s.id==='telegram');onboardingFlowTouched=true;onboardingFlowStep=Math.min(steps.length-1,(idx>=0?idx:onboardingFlowStep)+1);renderOnboardingFlow()}}
async function testTelegram(){await api('/api/telegram/test',{method:'POST',body:'{}'});toast(lang==='es'?'Mensaje enviado a Telegram':'Test message sent to Telegram')}
function showDetails(campaign_id){const c=state.metrics.campaigns.find(item=>item.id===campaign_id);if(c)toast(lang==='es'?`${t('details')}: ${demoCampaignName(c.name)} · vuelve ${Number(c.roas).toFixed(2)}x por cada $1 · cada compra cuesta ${fmtMoney(c.cpa)}`:`${t('details')}: ${c.name} · ROAS ${Number(c.roas).toFixed(2)}x · CPA ${fmtMoney(c.cpa)}`);else toast(t('toast_details'))}
function initBrandGuides(){
 const suggested=state.business_profile?.main_offer||state.business_profile?.offer||'';
 const draft=lang==='es'?'Ayúdame a definir mi producto principal y mi guía de marca para crear anuncios consistentes. Hazme preguntas fáciles, una por una.':'Help me define my main product and brand guide for consistent ads. Ask simple questions one at a time.';
 const box=qs('#confirm-overlay');box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Crear memoria de marca':'Create brand memory'}</h2><p>${lang==='es'?'Escribe el producto u oferta principal. Si no sabes cómo resumirlo, háblalo con el agente y él te guía.':'Enter the main product or offer. If you are not sure how to summarize it, talk to the agent and it will guide you.'}</p><form class="unlock-form" onsubmit="submitBrandGuideInit(event)"><label>${lang==='es'?'Producto u oferta principal':'Main product or offer'}<input id="brand-guide-init-name" value="${escapeHtml(suggested)}" placeholder="${lang==='es'?'Ej: curso de uñas, ecommerce de ropa, clínica dental':'Ex: nail course, clothing store, dental clinic'}"></label><div class="confirm-actions"><button class="btn" type="button" onclick="closeConfirm()">${lang==='es'?'Cancelar':'Cancel'}</button><button class="btn ask-btn" type="button" onclick="closeConfirm();openChat(${chatArg(draft)})">${lang==='es'?'Hablarlo con el agente':'Talk with agent'}</button><button class="btn primary" type="submit">${lang==='es'?'Crear memoria':'Create memory'}</button></div></form></div>`;box.classList.add('open');setTimeout(()=>qs('#brand-guide-init-name')?.focus(),30)
}
async function submitBrandGuideInit(event){event.preventDefault();const name=(qs('#brand-guide-init-name')?.value||'').trim();if(!name){toast(lang==='es'?'Escribe el nombre de tu producto u oferta.':'Enter your product or offer name.');return}closeConfirm();await api('/api/brand-guides/init',{method:'POST',body:JSON.stringify({product_name:name})});toast(lang==='es'?'Guías de marca creadas.':'Brand guides created.');await load()}
async function generateRefresh(campaign_id='',product_guide='',ad_brief=''){
 const products=state.brand_guides?.products||[];const adBriefs=state.brand_guides?.ad_briefs||[];
 if(!campaign_id&&!product_guide&&!ad_brief&&adBriefs.length===1)ad_brief=adBriefs[0].guide;
 if(!campaign_id&&!product_guide&&!ad_brief&&adBriefs.length>1){openBrandMemory('ad_brief',adBriefs[0].id);toast(lang==='es'?'Elige la idea de anuncio que quieres trabajar':'Choose the ad idea to work on');return}
 if(!campaign_id&&!product_guide&&products.length===1)product_guide=products[0].guide;
 if(!campaign_id&&!product_guide&&products.length>1){openBrandMemory('product',products[0].id);toast(lang==='es'?'Elige el producto para crear propuestas coherentes':'Choose a product for consistent proposals');return}
 const payload={};if(campaign_id)payload.campaign_id=campaign_id;if(product_guide)payload.product_guide=product_guide;if(ad_brief)payload.ad_brief=ad_brief;
 await api('/api/creative-refresh',{method:'POST',body:JSON.stringify(payload)});toast(t('toast_refresh'));await load();
}
async function stageUpload(manifest_path,variant_id,ratios=['1:1']){await api('/api/stage-upload',{method:'POST',body:JSON.stringify({manifest_path,variant_id,ratios:ratios.length?ratios:['1:1']})});toast(lang==='es'?'Imagen lista para que la apruebes. También quedó guardada como pieza de anuncio.':'Image sent for approval. It was also saved as an ad asset.');await load()}
async function buildAudienceStrategy(payload){const res=await api('/api/audience-strategy',{method:'POST',body:JSON.stringify({...payload,language:lang})});state.audience_strategy=res.result;renderAudience();toast(t('toast_audience'))}
let pendingBusinessReplacement=null;
function needsBusinessReplacement(err){return String(err?.message||err||'').includes('CONFIRM_BUSINESS_REPLACE')}
function showBusinessReplacementConfirm(payload){
 pendingBusinessReplacement=payload;
 const box=qs('#confirm-overlay');box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Cambiar de negocio':'Change business'}</h2><p>${lang==='es'?'Tu licencia Individual cuida un solo negocio activo. Para manejar varios clientes, usa Licencia Agencia. Si cambias de negocio, empezamos limpio para evitar mezclar datos.':'Your Individual license protects one active business. To manage several clients, use Agency License. If you switch business, we start clean to avoid mixing data.'}</p><p class="notice">${lang==='es'?'Esto borra memoria del agente, métricas guardadas, chat, actividad, guías creativas e imágenes de trabajo del negocio anterior. No borra tu licencia, email, contraseña ni este equipo.':'This removes agent memory, saved metrics, chat, activity, creative guides, and working images for the previous business. It does not remove your license, email, password, or this device.'}</p><div class="confirm-actions"><button class="btn" type="button" onclick="pendingBusinessReplacement=null;closeConfirm()">${lang==='es'?'Cancelar':'Cancel'}</button><button class="btn primary" type="button" onclick="confirmBusinessReplacement()">${lang==='es'?'Cambiar y empezar limpio':'Change and start clean'}</button></div></div>`;box.classList.add('open')
}
async function confirmBusinessReplacement(){const payload={...(pendingBusinessReplacement||{}),confirm_replace_business:true};pendingBusinessReplacement=null;closeConfirm();await api('/api/setup-config',{method:'POST',body:JSON.stringify(payload)});toast(lang==='es'?'Nuevo negocio guardado. Empezamos con memoria limpia.':'New business saved. Starting with clean memory.');await load()}
async function saveSetupPayload(payload,advance=false){try{await api('/api/setup-config',{method:'POST',body:JSON.stringify(payload)});toast(t('toast_setup_saved'));await load();if(advance)advanceOnboardingAfterLoad()}catch(err){if(needsBusinessReplacement(err)){showBusinessReplacementConfirm(payload);return}throw err}}
async function saveSetupConfig(e){e.preventDefault();await saveSetupPayload(Object.fromEntries(new FormData(e.target).entries()))}
async function saveOnboardingSetupConfig(e){e.preventDefault();await saveSetupPayload(Object.fromEntries(new FormData(e.target).entries()),true)}
async function createAgencySpace(e){e.preventDefault();const payload=Object.fromEntries(new FormData(e.target).entries());await api('/api/agency/spaces',{method:'POST',body:JSON.stringify(payload)});toast(lang==='es'?'Cliente agregado. Ábrelo para configurarlo.':'Client added. Open it to configure it.');await load()}
async function switchAgencySpace(id){await api('/api/agency/spaces/switch',{method:'POST',body:JSON.stringify({space_id:id})});toast(lang==='es'?'Cliente activo cambiado.':'Active client changed.');await load()}
async function saveBusinessLinks(e){
 e.preventDefault();
 const payload=Object.fromEntries(new FormData(e.target).entries());
 const box=qs('#business-scan-results');
 if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Guardando links para que el agente los revise...':'Saving links for the agent to review...'}</p></div>`;
 try{
  const res=await api('/api/business-profile/links',{method:'POST',body:JSON.stringify(payload)});
  toast(lang==='es'?'Listo. El agente usará esto para entrevistarte por Telegram.':'Ready. The agent will use this when interviewing you through Telegram.');
  await load();
  const steps=onboardingSteps();
  const idx=steps.findIndex(s=>s.id==='telegram');
  onboardingFlowTouched=true;
  onboardingFlowStep=idx>=0?idx:onboardingFlowStep;
  renderOnboardingFlow();
  return res;
 }catch(err){
  if(box)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude guardar esos links':'I could not save those links'}</b><p>${escapeHtml(err.message||String(err))}</p></div>`;
  throw err;
 }
}
async function startBusinessInterview(e){
 e.preventDefault();
 const payload=Object.fromEntries(new FormData(e.target).entries());
 payload.language=lang;
 const business=String(payload.business_type||'').trim();
 if(!business){toast(lang==='es'?'Escribe tu negocio en pocas palabras.':'Write your business in a few words.');return}
 const box=qs('#business-scan-results');
 if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Preparando preguntas...':'Preparing questions...'}</p></div>`;
 try{
  const res=await api('/api/business-profile/questions',{method:'POST',body:JSON.stringify(payload)});
  toast(lang==='es'?'Listo. Ahora vamos pregunta por pregunta.':'Ready. Now we go one question at a time.');
  await load();
  businessContextQuestionIndex=0;
  const steps=onboardingSteps();
  const idx=steps.findIndex(s=>s.id==='context');
  onboardingFlowTouched=true;
  onboardingFlowStep=idx>=0?idx:onboardingFlowStep;
  renderOnboardingFlow();
  return res;
 }catch(err){
  if(box)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude preparar las preguntas':'Could not prepare the questions'}</b><p>${escapeHtml(err.message||String(err))}</p></div>`;
  throw err;
 }
}
async function scanBusinessWebsite(e){e.preventDefault();const payload=Object.fromEntries(new FormData(e.target).entries());const box=qs('#business-scan-results');if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Leyendo tu web y preparando respuestas sugeridas...':'Reading your website and preparing suggested answers...'}</p></div>`;try{const res=await api('/api/business-profile/scan',{method:'POST',body:JSON.stringify(payload)});toast(lang==='es'?'Web analizada. Ahora revisamos una respuesta a la vez.':'Website scanned. Now we review one answer at a time.');await load();businessContextQuestionIndex=0;const steps=onboardingSteps();const idx=steps.findIndex(s=>s.id==='context');onboardingFlowTouched=true;onboardingFlowStep=idx>=0?idx:onboardingFlowStep;renderOnboardingFlow();return res}catch(err){if(box)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude leer la web todavía':'I could not read the website yet'}</b><p>${escapeHtml(err.message||String(err))}</p></div>`;throw err}}
async function skipWebsiteScan(){await api('/api/business-profile/links',{method:'POST',body:JSON.stringify({website_skipped:true})});toast(lang==='es'?'Perfecto. El agente te preguntará lo necesario después.':'Perfect. The agent will ask what it needs later.');await load();const steps=onboardingSteps();const idx=steps.findIndex(s=>s.id==='telegram');onboardingFlowTouched=true;onboardingFlowStep=idx>=0?idx:onboardingFlowStep;renderOnboardingFlow()}
function setBusinessContextQuestionIndex(index){const questions=businessContextQuestions();businessContextQuestionIndex=Math.max(0,Math.min(Number(index)||0,questions.length-1));renderOnboardingFlow()}
async function saveBusinessContextQuestion(e){e.preventDefault();const form=e.target;const field=String(new FormData(form).get('field')||'').trim();const answer=String(new FormData(form).get('answer')||'').trim();if(!field||!answer){toast(lang==='es'?'Escribe una respuesta corta para seguir.':'Write a short answer to continue.');return}const questions=businessContextQuestions();const idx=Math.max(0,questions.findIndex(q=>q.key===field));const isLast=idx>=questions.length-1;const payload={[field]:answer};if(isLast)payload.context_complete=true;await api('/api/business-profile',{method:'POST',body:JSON.stringify(payload)});await load();if(isLast){toast(lang==='es'?'Contexto listo. Te muestro el primer plan.':'Context ready. Showing the first plan.');const steps=onboardingSteps();const strategyIndex=steps.findIndex(s=>s.id==='strategy');onboardingFlowTouched=true;onboardingFlowStep=strategyIndex>=0?strategyIndex:onboardingFlowStep}else{toast(lang==='es'?'Respuesta guardada. Vamos con la siguiente.':'Answer saved. On to the next one.');businessContextQuestionIndex=Math.min(idx+1,questions.length-1)}renderOnboardingFlow()}
async function saveBusinessContext(e){e.preventDefault();const payload=Object.fromEntries(new FormData(e.target).entries());payload.context_complete=true;await api('/api/business-profile',{method:'POST',body:JSON.stringify(payload)});toast(lang==='es'?'Contexto guardado. Te muestro el primer plan.':'Context saved. Showing the first plan.');await load();const steps=onboardingSteps();const idx=steps.findIndex(s=>s.id==='strategy');onboardingFlowTouched=true;onboardingFlowStep=idx>=0?idx:onboardingFlowStep;renderOnboardingFlow()}
function showMetaTokenBox(){const box=qs('#meta-token-box');if(box)box.classList.add('open')}
function goToMetaTokenStep(reason='',output=''){const steps=onboardingSteps();const idx=steps.findIndex(s=>s.id==='meta');onboardingFlowTouched=true;onboardingFlowStep=idx>=0?idx:1;renderOnboardingFlow();setTimeout(()=>{showMetaTokenBox();const box=qs('#social-account-results');if(box&&reason==='expired'){box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'Pega una clave nueva':'Paste a new key'}</b><p>${lang==='es'?'Meta rechazó la clave anterior porque venció o ya no sirve. Pega aquí la clave nueva; el dashboard la guarda automáticamente y después vuelve a buscar tus cuentas.':'Meta rejected the previous key because it expired or is no longer valid. Paste the new key here; the dashboard saves it automatically and then finds your accounts again.'}</p><p class="notice">${lang==='es'?'Cuando pegas una clave válida, queda guardada localmente en este computador o VPS. No se guarda en cookies del navegador.':'When you paste a valid key, it is stored locally on this computer or VPS. It is not stored in browser cookies.'}</p>${output?`<details class="helper-command"><summary>${lang==='es'?'Detalles técnicos':'Technical details'}</summary><span class="step-command">${escapeHtml(String(output).slice(0,900))}</span></details>`:''}</div>`}},0)}
function connectMetaStarted(){showMetaTokenBox();toast(lang==='es'?'Meta Developers se abrirá en otra pestaña. Sigue tus screenshots y pega aquí tu clave.':'Meta Developers will open in another tab. Follow your screenshots and paste your key here.')}
let metaTokenAutoSaveTimer=null;
let metaTokenSaving=false;
let lastMetaTokenSaved='';
function renderTokenSavedState(){const tokenBox=qs('#meta-token-box');if(tokenBox){tokenBox.innerHTML=`<div class="guide-card"><b>${lang==='es'?'Clave de Meta guardada':'Meta key saved'}</b><p>${lang==='es'?'La conexión quedó guardada en este computador o VPS. Ahora buscaré tus cuentas publicitarias.':'The connection is saved on this computer or VPS. I will now find your ad accounts.'}</p><button class="btn" type="button" onclick="goToMetaTokenStep()">${lang==='es'?'Cambiar clave de Meta':'Change Meta key'}</button></div>`;tokenBox.classList.add('open')}}
function scheduleMetaTokenAutoSave(){clearTimeout(metaTokenAutoSaveTimer);const token=(qs('#meta-token-input')?.value||'').trim();if(token.length<20||token===lastMetaTokenSaved)return;metaTokenAutoSaveTimer=setTimeout(()=>saveMetaToken({auto:true}),500)}
async function saveMetaToken(options={}){const auto=Boolean(options.auto);const input=qs('#meta-token-input');const token=(input?.value||'').trim();const box=qs('#social-account-results');if(!token){if(!auto)toast(lang==='es'?'Pega primero la clave de Meta.':'Paste the Meta key first.');return}if(token.length<20){if(!auto)toast(lang==='es'?'Esa clave se ve muy corta. Revisa que la pegaste completa.':'That key looks too short. Check that you pasted the full value.');return}if(metaTokenSaving||token===lastMetaTokenSaved)return;metaTokenSaving=true;lastMetaTokenSaved=token;if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Guardando conexión local...':'Saving local connection...'}</p></div>`;try{const res=await api('/api/social/token',{method:'POST',body:JSON.stringify({token})});const result=res.result||res;if(result.saved){toast(lang==='es'?'Clave de Meta guardada localmente. Buscando cuentas...':'Meta key saved locally. Finding accounts...');renderTokenSavedState();await refreshSocialAccounts()}else{lastMetaTokenSaved='';renderSocialAccountResults({...result,accounts:[]})}}finally{metaTokenSaving=false}}
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
 const loginHint=lang==='es'?'No pude traer cuentas todavía. Pega tu clave de Meta, o revisa que esa clave tenga permisos de anuncios.':'I could not fetch accounts yet. Paste your Meta key, or check that the key has ads permissions.';
 box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No encontré cuentas':'No accounts found'}</b><p>${loginHint}</p><div class="onboarding-step-actions"><button class="btn primary" type="button" onclick="goToMetaTokenStep()">${lang==='es'?'Pegar clave':'Paste key'}</button></div>${output?`<details class="helper-command"><summary>${lang==='es'?'Detalles técnicos':'Technical details'}</summary><span class="step-command">${escapeHtml(output)}</span></details>`:''}</div>`;
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
  box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'Encontré datos conectados':'I found connected assets'}</b><p>${lang==='es'?'Usé tu clave de Meta guardada para buscar páginas, Instagram y web. Si la página sugerida no es la correcta, elige otra de la lista.':'I used your saved Meta key to find Pages, Instagram, and website. If the suggested Page is not right, choose another one from the list.'}</p></div>${rows.join('')}${pageCards}`;
  return;
 }
 box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude encontrar todo automáticamente':'I could not find everything automatically'}</b><p>${lang==='es'?'Tu clave de Meta puede no tener permiso para ver páginas, o tu página e Instagram pueden no estar conectados. Puedes seguir y escribir esos datos en el siguiente paso.':'Your Meta key may not be allowed to see Pages, or your Page and Instagram may not be connected. You can continue and enter those details in the next step.'}</p><p class="notice">${pages.length?`${pages.length} page(s)`:''}${urls.length?` · ${urls.length} URL(s)`:''}</p></div>`;
}
async function discoverMetaAssets(id){const box=discoveryResultsBox();if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Buscando página, Instagram y web conectados...':'Finding connected Page, Instagram, and website...'}</p></div>`;const res=await api('/api/social/discover-assets',{method:'POST',body:JSON.stringify({ad_account_id:id})});renderDiscoveredAssets(res);return res}
async function selectSocialAccount(id){try{await api('/api/social/default-account',{method:'POST',body:JSON.stringify({ad_account_id:id})})}catch(err){if(needsBusinessReplacement(err)){showBusinessReplacementConfirm({ad_account_id:id});return}throw err}const input=qs('input[name="ad_account_id"]');if(input)input.value=id;toast(lang==='es'?'Cuenta guardada. Buscando perfiles conectados...':'Account saved. Finding connected assets...');const discovered=await discoverMetaAssets(id);try{await api('/api/action',{method:'POST',body:JSON.stringify({action:'refresh_insights'})})}catch(err){}await load();const steps=onboardingSteps();const destinationIndex=steps.findIndex(s=>s.id==='destination');if(destinationIndex>=0){onboardingFlowTouched=true;onboardingFlowStep=destinationIndex;renderOnboardingFlow();renderDiscoveredAssets(discovered)}else advanceOnboardingAfterLoad()}
async function unlockFromOnboarding(e){e.preventDefault();const input=qs('#onboarding-password');const err=qs('#onboarding-unlock-error');const value=(input?.value||'').trim();if(!value)return;if(err){err.textContent='';err.classList.remove('show')}const res=await fetch('/api/unlock',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':value},body:JSON.stringify({})});if(!res.ok){if(err){err.textContent=t('unlock_failed');err.classList.add('show')}return}localStorage.removeItem('dashboardToken');if(qs('#onboarding-remember')?.checked)localStorage.setItem('dashboardPassword',value);else localStorage.removeItem('dashboardPassword');toast(lang==='es'?'Dashboard desbloqueado':'Dashboard unlocked');onboardingFlowStep=Math.max(onboardingFlowStep,1);await load()}
async function setDashboardPasswordFromOnboarding(e){e.preventDefault();const password=(qs('#new-dashboard-password')?.value||'').trim();const confirm=(qs('#confirm-dashboard-password')?.value||'').trim();const err=qs('#dashboard-password-error');if(err){err.textContent='';err.classList.remove('show')}if(password.length<8){if(err){err.textContent=lang==='es'?'Usa al menos 8 caracteres.':'Use at least 8 characters.';err.classList.add('show')}return}if(password!==confirm){if(err){err.textContent=lang==='es'?'Las contraseñas no coinciden.':'Passwords do not match.';err.classList.add('show')}return}const res=await fetch('/api/dashboard-password',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':dashboardPassword()},body:JSON.stringify({password,confirm_password:confirm})});if(!res.ok){if(err){err.textContent=await responseErrorMessage(res);err.classList.add('show')}return}localStorage.removeItem('dashboardToken');if(qs('#new-dashboard-remember')?.checked)localStorage.setItem('dashboardPassword',password);else localStorage.removeItem('dashboardPassword');toast(lang==='es'?'Contraseña guardada. Sigamos con el siguiente paso.':'Password saved. Let us continue with the next step.');await load();onboardingFlowTouched=true;advanceOnboardingAfterLoad()}
async function activateLicense(transferDevice=false){const res=await api('/api/license/activate',{method:'POST',body:JSON.stringify({transfer_device:transferDevice})});const result=res.result||{};toast(`${t('toast_license')}: ${localText(result.detail||result.status||'')}`);await load();if(result&&result.valid){advanceOnboardingAfterLoad();return}if(result.status==='device_limit'&&result.transfer_available&&!transferDevice)showLicenseTransferConfirm()}
function showLicenseTransferConfirm(){const box=qs('#confirm-overlay');box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Usar licencia en este equipo':'Use license on this device'}</h2><p>${lang==='es'?'Esta licencia Individual ya esta activa en otro equipo. Si continuas, este equipo quedara como el equipo activo para nuevas validaciones y el anterior perdera acceso cuando vuelva a validar la licencia online.':'This Individual license is already active on another device. If you continue, this device becomes the active device for new validations and the previous one loses access when it validates online again.'}</p><p class="notice">${lang==='es'?'Si estas cambiando de PC o reinstalando el producto, esta es la opcion correcta.':'If you are changing PC or reinstalling the product, this is the right option.'}</p><div class="confirm-actions"><button class="btn" type="button" onclick="closeConfirm()">${lang==='es'?'Cancelar':'Cancel'}</button><button class="btn primary" type="button" onclick="closeConfirm();activateLicense(true)">${lang==='es'?'Transferir a este equipo':'Transfer to this device'}</button></div></div>`;box.classList.add('open')}
let decisionConfirmResolver=null;
function resolveDecisionConfirm(value){const resolver=decisionConfirmResolver;decisionConfirmResolver=null;qs('#confirm-overlay')?.classList.remove('open');if(resolver)resolver(Boolean(value))}
function closeConfirm(){resolveDecisionConfirm(false)}
function showDecisionConfirm(options={}){
 const box=qs('#confirm-overlay');
 const items=(options.items||[]).filter(Boolean);
 const agentDraft=String(options.agentDraft||'');
 return new Promise(resolve=>{
  decisionConfirmResolver=resolve;
  box.innerHTML=`<div class="confirm-card"><h2>${escapeHtml(options.title||'')}</h2><p>${escapeHtml(options.body||'')}</p>${items.length?`<ul>${items.map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ul>`:''}<div class="confirm-actions"><button class="btn" type="button" onclick="resolveDecisionConfirm(false)">${escapeHtml(options.cancelLabel||(lang==='es'?'Cancelar':'Cancel'))}</button>${agentDraft?`<button class="btn ask-btn" type="button" onclick="resolveDecisionConfirm(false);openChat(${chatArg(agentDraft)})">${lang==='es'?'Preguntar al manager':'Ask manager'}</button>`:''}<button class="btn primary" type="button" onclick="resolveDecisionConfirm(true)">${escapeHtml(options.confirmLabel||t('approve'))}</button></div></div>`;
  box.classList.add('open');
 });
}
function showOnboardingCompleteConfirm(){const box=qs('#confirm-overlay');box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Terminar configuración inicial':'Finish initial setup'}</h2><p>${lang==='es'?'La guía inicial dejará de aparecer automáticamente en este equipo. Esto no bloquea nada: podrás cambiar todo después desde Configuración.':'The initial guide will stop opening automatically on this device. This does not lock anything: you can change everything later from Setup.'}</p><ul><li>${lang==='es'?'Cuenta publicitaria':'Ad account'}</li><li>${lang==='es'?'Página de Facebook, Instagram y web':'Facebook Page, Instagram, and website'}</li><li>${lang==='es'?'Contraseña del dashboard':'Dashboard password'}</li><li>${lang==='es'?'Reglas de supervisión y piloto automático':'Supervision and autopilot rules'}</li></ul><div class="confirm-actions"><button class="btn" type="button" onclick="closeConfirm()">${lang==='es'?'Seguir revisando':'Keep reviewing'}</button><button class="btn primary" type="button" onclick="finishOnboardingConfirmed()">${lang==='es'?'Terminar y abrir dashboard':'Finish and open dashboard'}</button></div></div>`;box.classList.add('open')}
async function finishOnboardingConfirmed(){closeConfirm();await api('/api/onboarding/complete',{method:'POST',body:JSON.stringify({})});toast(lang==='es'?'Configuración inicial terminada. Puedes editarla cuando quieras.':'Initial setup complete. You can edit it anytime.');await load()}
async function completeOnboarding(){if(!state.config.dashboard_password_set){toast(lang==='es'?'Primero crea tu contraseña del dashboard.':'Create your dashboard password first.');const steps=onboardingSteps();const passwordIndex=steps.findIndex(s=>s.id==='password');onboardingFlowStep=passwordIndex>=0?passwordIndex:onboardingFlowStep;renderOnboardingFlow();return}showOnboardingCompleteConfirm()}
async function skipOnboarding(){const ok=await showDecisionConfirm({title:lang==='es'?'Completar después':'Finish later',body:lang==='es'?'Abriré el dashboard ahora. Arriba verás un aviso brillante para volver y terminar lo pendiente cuando quieras.':'I will open the dashboard now. A glowing notice at the top will bring you back to finish the pending parts later.',confirmLabel:lang==='es'?'Abrir dashboard':'Open dashboard'});if(!ok)return;await api('/api/onboarding/skip',{method:'POST',body:JSON.stringify({})});toast(lang==='es'?'Puedes completar la configuración después.':'You can finish setup later.');await load()}
async function resumeOnboarding(){await api('/api/onboarding/reset',{method:'POST',body:JSON.stringify({})});toast(lang==='es'?'Sigamos con lo pendiente.':'Let us finish the pending setup.');await load()}
async function resetOnboarding(){const ok=await showDecisionConfirm({title:lang==='es'?'Revisar configuración inicial':'Run initial setup again',body:lang==='es'?'La guía inicial volverá a aparecer para revisar conexión, cuenta, página y reglas. No borra tus datos por sí sola.':'The initial guide will appear again to review connection, account, Page, and rules. It does not delete your data by itself.',confirmLabel:lang==='es'?'Abrir guía inicial':'Open initial guide',agentDraft:lang==='es'?'Ayúdame a revisar si necesito repetir la configuración inicial o solo cambiar una parte.':'Help me decide whether I should rerun initial setup or only change one setup area.'});if(!ok)return;await api('/api/onboarding/reset',{method:'POST',body:JSON.stringify({})});toast(lang==='es'?'Guía inicial abierta':'Initial guide opened');await load()}
qs('#unlock-form').addEventListener('submit',async e=>{e.preventDefault();const value=qs('#unlock-password').value.trim();if(!value)return;setUnlockError('');if(unlockMode==='create'){const confirm=(qs('#unlock-confirm-password')?.value||'').trim();if(value.length<8){setUnlockError(t('dashboard_password_short'));return}if(value!==confirm){setUnlockError(t('dashboard_password_mismatch'));return}const res=await fetch('/api/dashboard-password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:value,confirm_password:confirm})});if(!res.ok){setUnlockError(await responseErrorMessage(res));return}localStorage.removeItem('dashboardToken');if(qs('#remember-device').checked)localStorage.setItem('dashboardPassword',value);else localStorage.removeItem('dashboardPassword');hideUnlock();if(unlockResolver){unlockResolver(value);unlockResolver=null}qs('#unlock-password').value='';qs('#unlock-confirm-password').value='';toast(lang==='es'?'Contraseña creada. Seguimos con la configuración.':'Password created. Continuing setup.');await load();return}localStorage.removeItem('dashboardToken');if(qs('#remember-device').checked)localStorage.setItem('dashboardPassword',value);else localStorage.removeItem('dashboardPassword');hideUnlock();if(unlockResolver){unlockResolver(value);unlockResolver=null}qs('#unlock-password').value=''})
qs('#language-select').addEventListener('change',e=>{lang=e.target.value;localStorage.setItem('dashboardLang',lang);render()})
qs('#chat-input').addEventListener('input',resizeChatInput)
qs('#agent-bar-input').addEventListener('input',resizeAgentBarInput)
qs('#chat-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();const form=qs('#chat-form');if(form.requestSubmit){form.requestSubmit()}else{form.dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}))}}})
qs('#agent-bar-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();const form=qs('#agent-chat-bar');if(form.requestSubmit){form.requestSubmit()}else{form.dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}))}}})
qs('#chat-form').addEventListener('submit',async e=>{e.preventDefault();const input=qs('#chat-input');const text=input.value.trim();if(!text)return;input.value='';resizeChatInput();await sendChatMessage(text)})
qs('#agent-chat-bar').addEventListener('submit',async e=>{e.preventDefault();const input=qs('#agent-bar-input');const text=input.value.trim();if(!text){input.focus();return}input.value='';resizeAgentBarInput();await sendChatMessage(text,{workspace:true})})
document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));btn.classList.add('active');['overview','setup','creator','audiences','creatives','reports'].forEach(t=>qs('#tab-'+t).classList.toggle('hidden',t!==btn.dataset.tab))}))
qs('#campaign-form').addEventListener('submit',async e=>{e.preventDefault();syncTargetingHidden('location');syncTargetingHidden('interest');const payload=Object.fromEntries(new FormData(e.target).entries());await api('/api/campaigns',{method:'POST',body:JSON.stringify(payload)});toast(lang==='es'?'Campaña enviada para tu aprobación':'Campaign sent for your approval');await load()})
qs('#audience-form').addEventListener('submit',async e=>{e.preventDefault();const payload=Object.fromEntries(new FormData(e.target).entries());payload.consent=e.target.elements.consent.checked?'yes':'no';await buildAudienceStrategy(payload)})
applyDashboardTheme();
syncDashboardView();
syncPanels();
load();
</script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    HTML_PATHS = {"/", "/dashboard"}
    PROTECTED_GET_PATHS = {"/api/dashboard", "/api/export", "/api/report", "/api/setup", "/api/social/auth-status", "/api/social/accounts", "/api/update/snapshots", "/api/creative-asset"}
    PROTECTED_POST_PATHS = {"/api/unlock", "/api/dashboard-password", "/api/action", "/api/campaigns", "/api/targeting/search", "/api/audience-strategy", "/api/business-profile", "/api/business-profile/scan", "/api/business-profile/questions", "/api/business-profile/links", "/api/social/token", "/api/social/default-account", "/api/social/discover-assets", "/api/agent-model/connect", "/api/agent-model/connect-status", "/api/agent-model/connect-input", "/api/brand-guides/init", "/api/brand-guides/general", "/api/brand-guides/product", "/api/ad-briefs", "/api/codex/creative-plan", "/api/setup-config", "/api/guardrails", "/api/profitability-rules", "/api/telegram/config", "/api/telegram/detect", "/api/telegram/test", "/api/license/activate", "/api/onboarding/complete", "/api/onboarding/skip", "/api/onboarding/reset", "/api/agency/spaces", "/api/agency/spaces/switch", "/api/approve", "/api/reject", "/api/chat", "/api/chat/reset", "/api/creative-refresh", "/api/creative-storage/clear", "/api/stage-upload", "/api/execute-upload", "/api/mode", "/api/migration/export", "/api/migration/import", "/api/local-network-access", "/api/cloud-access/refresh", "/api/update/check", "/api/update/apply", "/api/update/rollback"}
    ONBOARDING_OPEN_GETS = {"/api/dashboard", "/api/setup"}
    ONBOARDING_OPEN_POSTS = {"/api/dashboard-password", "/api/business-profile", "/api/business-profile/scan", "/api/business-profile/questions", "/api/business-profile/links", "/api/license/activate"}
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
        "/api/unlock": lambda _payload: {"unlocked": True},
        "/api/dashboard-password": set_dashboard_password,
        "/api/social/token": social_save_facebook_token,
        "/api/social/default-account": social_set_default_account,
        "/api/social/discover-assets": social_discover_assets,
        "/api/agent-model/connect": connect_agent_model,
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
        "/api/brand-guides/product": save_product_brand_memory,
        "/api/ad-briefs": save_ad_brief_memory,
        "/api/codex/creative-plan": codex_creative_plan,
        "/api/setup-config": save_setup_config,
        "/api/guardrails": save_guardrails,
        "/api/profitability-rules": save_profitability_rule_settings,
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
        "/api/onboarding/complete": lambda _payload: complete_onboarding(),
        "/api/onboarding/skip": lambda _payload: skip_onboarding(),
        "/api/onboarding/reset": lambda _payload: reset_onboarding(),
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
            body = f"""<!DOCTYPE html><html lang=\"es\"><head><meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Acceso local apagado</title><style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#101113;color:#f2f2ee;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:22px}}main{{max-width:430px;border:1px solid rgba(255,255,255,.14);border-radius:14px;background:rgba(255,255,255,.06);padding:22px;box-shadow:0 22px 70px rgba(0,0,0,.34)}}h1{{font-size:22px;margin:0 0 8px}}p{{color:#a7adb5;line-height:1.5}}</style></head><body><main><h1>Acceso por Wi‑Fi apagado</h1><p>{message}</p><p>El teléfono debe estar en el mismo Wi‑Fi y el dashboard seguirá protegido por contraseña.</p></main></body></html>""".encode("utf-8")
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
        if dashboard_token_valid(config, self.provided_token(parsed, payload)):
            return True
        self.send_json({"error": "dashboard password required"}, 401)
        return False

    def onboarding_open_without_password(self, path):
        if load_onboarding_state().get("completed") or path not in self.ONBOARDING_OPEN_POSTS:
            return False
        config = load_config()
        return not bool(config.dashboard_token)

    def auth_required_for_post(self, path):
        return path in self.PROTECTED_POST_PATHS and not self.onboarding_open_without_password(path)

    def auth_required_for_get(self, path):
        if path not in self.PROTECTED_GET_PATHS:
            return False
        config = load_config()
        if not load_onboarding_state().get("completed") and not config.dashboard_token:
            return path not in self.ONBOARDING_OPEN_GETS
        return bool(config.dashboard_token_required and config.dashboard_token)

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
        chat_result = route_chat_approval_decision(chat_payload)
        if not chat_result:
            chat_result = handle_creative_memory_wizard(chat_payload)
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
        if not self.local_network_request_allowed():
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
        save_metrics(sample_metrics())
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
