#!/usr/bin/env python3
"""License-key and cloud unlock helpers for the guided setup product."""
import base64
import hashlib
import json
import re
import socket
import subprocess
import tempfile
import threading
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from product_config import ROOT_DIR


LICENSE_PREFIX = "MAO"
LICENSE_SALT = "meta-ads-operator-v1"
LICENSE_CACHE_FILE = ROOT_DIR / "dashboard" / "data" / "license_unlock.json"
INDIVIDUAL_FEATURES = ["dashboard", "chat", "telegram", "campaign_creation", "live_actions"]
AGENCY_FEATURES = [*INDIVIDUAL_FEATURES, "agency_workspaces", "multi_telegram_profiles"]
PLAN_DEFAULTS = {
    "individual": {"max_devices": 1, "workspace_limit": 1, "features": INDIVIDUAL_FEATURES},
    "agency": {"max_devices": 4, "workspace_limit": 50, "features": AGENCY_FEATURES},
}
LICENSE_REFRESH_WINDOW = timedelta(hours=24)
LICENSE_REFRESH_RETRY_SECONDS = 300
_LICENSE_REFRESH_LOCK = threading.Lock()
_LICENSE_REFRESH_ATTEMPTS = {}


def clean_license_key(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def checksum_for(body):
    return hashlib.sha256(f"{LICENSE_SALT}:{body}".encode("utf-8")).hexdigest()[:6].upper()


def format_license(body):
    clean = clean_license_key(body)
    grouped = "-".join(clean[i : i + 4] for i in range(0, len(clean), 4))
    return f"{LICENSE_PREFIX}-{grouped}-{checksum_for(clean)}"


def validate_license_key(value):
    raw = str(value or "").strip().upper()
    if not raw:
        return {"status": "missing", "valid": False, "detail": "License key missing"}
    if raw in {"DEMO", "INTERNAL-DEMO"}:
        return {"status": "active", "valid": True, "detail": "Demo/internal license"}
    parts = raw.split("-")
    if len(parts) < 4 or parts[0] != LICENSE_PREFIX:
        return {"status": "invalid", "valid": False, "detail": "Invalid license format"}
    supplied = clean_license_key(parts[-1])
    body = clean_license_key("".join(parts[1:-1]))
    if len(supplied) != 6 or len(body) < 8:
        return {"status": "invalid", "valid": False, "detail": "Invalid license format"}
    expected = checksum_for(body)
    if supplied != expected:
        return {"status": "invalid", "valid": False, "detail": "License checksum mismatch"}
    return {"status": "active", "valid": True, "detail": "License active"}


def normalize_license_entitlements(status=None):
    """Return one safe local entitlement object for UI and server-side checks."""
    status = status or {}
    raw_features = status.get("features") or []
    if isinstance(raw_features, str):
        raw_features = [raw_features]
    features = sorted({str(feature).strip() for feature in raw_features if str(feature).strip()})
    requested_plan = str(status.get("plan") or "").strip().lower()
    is_agency = requested_plan == "agency" or (not requested_plan and "agency_workspaces" in features)
    plan = "agency" if is_agency else "individual"
    defaults = PLAN_DEFAULTS[plan]
    if not features:
        features = list(defaults["features"])
    try:
        max_devices = int(status.get("max_devices") or defaults["max_devices"])
    except (TypeError, ValueError):
        max_devices = defaults["max_devices"]
    try:
        workspace_limit = int(status.get("workspace_limit") or defaults["workspace_limit"])
    except (TypeError, ValueError):
        workspace_limit = defaults["workspace_limit"]
    if plan == "individual":
        max_devices = min(max_devices, defaults["max_devices"])
        workspace_limit = min(workspace_limit, defaults["workspace_limit"])
        features = [feature for feature in features if feature not in {"agency_workspaces", "multi_telegram_profiles"}]
    return {
        "plan": plan,
        "max_devices": max(1, max_devices),
        "workspace_limit": max(1, workspace_limit),
        "features": features,
        "is_individual": plan == "individual",
        "is_agency": plan == "agency",
        "can_use_agency_workspaces": plan == "agency" and "agency_workspaces" in features,
        "can_use_multi_telegram_profiles": plan == "agency" and "multi_telegram_profiles" in features,
    }


def now_utc():
    return datetime.now(timezone.utc)


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def default_device_id():
    raw = f"{socket.gethostname()}:{uuid.getnode()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def read_unlock_cache():
    if not LICENSE_CACHE_FILE.exists():
        return {}
    try:
        return json.loads(LICENSE_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_unlock_cache(payload):
    LICENSE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LICENSE_CACHE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def canonical_payload(payload):
    safe = {key: value for key, value in payload.items() if key != "signature"}
    return json.dumps(safe, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def verify_signature(payload, public_key):
    """Verify the unlock with the seller public key; the private key never ships."""
    if not public_key:
        return False
    signature = str(payload.get("signature") or "")
    if not signature:
        return False
    try:
        pem = base64.b64decode(public_key.encode("ascii")).decode("utf-8")
        signature_bytes = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public_path = root / "license-public.pem"
            payload_path = root / "unlock.json"
            signature_path = root / "unlock.sig"
            public_path.write_text(pem, encoding="utf-8")
            payload_path.write_bytes(canonical_payload(payload))
            signature_path.write_bytes(signature_bytes)
            result = subprocess.run(
                [
                    "openssl",
                    "pkeyutl",
                    "-verify",
                    "-pubin",
                    "-inkey",
                    str(public_path),
                    "-rawin",
                    "-in",
                    str(payload_path),
                    "-sigfile",
                    str(signature_path),
                ],
                capture_output=True,
                check=False,
            )
        return result.returncode == 0
    except (OSError, ValueError, UnicodeDecodeError):
        return False


def lifetime_license_status(status, detail=""):
    """Expose the commercial lifetime term without calling refresh dates expiry."""
    result = dict(status or {})
    result.pop("expires_at", None)
    result["license_term"] = "lifetime"
    result["lifetime"] = True
    if detail:
        result["detail"] = detail
    return result


def cached_unlock_status(config):
    cache = read_unlock_cache()
    if not cache:
        return {"online": False, "valid": False, "status": "missing_unlock", "detail": "No license unlock cached"}
    if cache.get("license_key") != config.license_key:
        return {"online": False, "valid": False, "status": "wrong_license", "detail": "Cached unlock belongs to another license"}
    if not verify_signature(cache, getattr(config, "license_public_key", "")):
        return {"online": False, "valid": False, "status": "bad_signature", "detail": "License unlock signature failed"}
    expires = parse_time(cache.get("expires_at"))
    entitlements = normalize_license_entitlements(cache)
    if expires and expires >= now_utc():
        return lifetime_license_status(
            {"online": False, "valid": True, "status": "active", "expires_at": cache.get("expires_at"), **entitlements},
            "Lifetime license active",
        )

    # `expires_at` is a refresh deadline for the signed verification proof, not
    # the commercial term of the purchase. A previously verified lifetime
    # license remains usable during network/server outages. `license_status`
    # refreshes it online and an authoritative rejection still takes effect.
    return lifetime_license_status(
        {"online": False, "valid": True, "status": "verification_due", "expires_at": cache.get("expires_at"), **entitlements},
        "Lifetime license active; online verification refresh pending",
    )


def activate_license(config, transfer_device=False):
    offline = validate_license_key(config.license_key)
    if not offline["valid"]:
        return offline
    if not config.license_server_url:
        if config.license_required_for_live and config.license_key not in {"DEMO", "INTERNAL-DEMO"}:
            return {
                **offline,
                "online": False,
                "valid": False,
                "status": "cloud_server_missing",
                "cloud_required": True,
                "offline_valid": True,
                "detail": "No se pudo confirmar tu licencia. Revisa internet o contacta soporte.",
            }
        return {**offline, "online": False, "detail": "Offline license active; no license server configured"}

    device_id = config.license_device_id or default_device_id()
    payload = {
        "license_key": config.license_key,
        "buyer_email": config.license_buyer_email,
        "device_id": device_id,
        "product": "meta-ads-operator",
        "version": "v1",
        "transfer_device": bool(transfer_device),
    }
    request = urllib.request.Request(
        f"{config.license_server_url}/api/license/activate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        cached = cached_unlock_status(config)
        if cached.get("valid"):
            return {**cached, "detail": "License server unavailable; using the saved unlock on this device"}
        return {**cached, "detail": "No se pudo confirmar tu licencia. Revisa internet o contacta soporte."}

    if not data.get("valid"):
        return {"online": True, "valid": False, "status": data.get("status", "rejected"), "detail": data.get("detail", "License could not be activated. Check the key or contact support.")}

    unlock = {
        "license_key": config.license_key,
        "buyer_email": config.license_buyer_email,
        "device_id": device_id,
        "issued_at": data.get("issued_at") or now_utc().isoformat(),
        "expires_at": data.get("expires_at"),
        "features": data.get("features", []),
        "plan": data.get("plan", "individual"),
        "max_devices": int(data.get("max_devices") or 1),
        "workspace_limit": int(data.get("workspace_limit") or 1),
        "signature": data.get("signature", ""),
    }
    if not verify_signature(unlock, getattr(config, "license_public_key", "")):
        return {"online": True, "valid": False, "status": "bad_signature", "detail": "License response could not be trusted. Contact support."}
    write_unlock_cache(unlock)
    return lifetime_license_status(
        {"online": True, "valid": True, "status": "active", "expires_at": unlock.get("expires_at"), **normalize_license_entitlements(unlock)},
        "Lifetime license active",
    )


def mark_license_install_state(config, event):
    """Best-effort server-side install/onboarding signal for the buyer portal."""
    if not config.license_server_url or not config.license_key or not config.license_buyer_email:
        return {"valid": False, "status": "missing_license_context"}
    device_id = config.license_device_id or default_device_id()
    payload = {
        "license_key": config.license_key,
        "buyer_email": config.license_buyer_email,
        "device_id": device_id,
        "install_event": event,
    }
    request = urllib.request.Request(
        f"{config.license_server_url}/api/license/activate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return {"valid": False, "status": "server_unavailable"}


def license_status(config):
    offline = validate_license_key(config.license_key)
    if not offline["valid"]:
        return offline
    if not config.license_server_url:
        if config.license_required_for_live and config.license_key not in {"DEMO", "INTERNAL-DEMO"}:
            return {
                **offline,
                "online": False,
                "valid": False,
                "status": "cloud_server_missing",
                "cloud_required": True,
                "offline_valid": True,
                "detail": "No se pudo confirmar tu licencia. Revisa internet o contacta soporte.",
            }
        return {**offline, "online": False, "cloud_required": False}
    cached = cached_unlock_status(config)
    verification_expires = parse_time(read_unlock_cache().get("expires_at")) if cached.get("valid") else None
    refresh_due = (
        not cached.get("valid")
        or cached.get("status") == "verification_due"
        or (verification_expires is not None and verification_expires <= now_utc() + LICENSE_REFRESH_WINDOW)
    )
    if refresh_due:
        device_id = config.license_device_id or default_device_id()
        refresh_key = f"{config.license_key}:{device_id}"
        should_refresh = False
        current = time.monotonic()
        with _LICENSE_REFRESH_LOCK:
            last_attempt = _LICENSE_REFRESH_ATTEMPTS.get(refresh_key, 0)
            if current - last_attempt >= LICENSE_REFRESH_RETRY_SECONDS:
                _LICENSE_REFRESH_ATTEMPTS[refresh_key] = current
                should_refresh = True
        if should_refresh:
            refreshed = activate_license(config)
            # An online response is authoritative: revocation, refund, transfer,
            # or device-limit rejection must be respected immediately.
            if refreshed.get("online"):
                return {**refreshed, "cloud_required": True, "offline_valid": bool(cached.get("valid"))}
            if refreshed.get("valid"):
                return {**refreshed, "cloud_required": True}

    if cached.get("valid"):
        return {**cached, "cloud_required": True}
    return {**cached, "cloud_required": True, "offline_valid": True}
