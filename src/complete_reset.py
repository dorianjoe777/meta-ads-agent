#!/usr/bin/env python3
"""Deterministic two-step complete reset support for Admira IA.

The language model never authorizes or executes this operation.  Telegram
records an exact, short-lived confirmation and the dashboard consumes a small
private request file from its own worker thread.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import shutil
import stat
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


COMPLETE_RESET_COMMAND = "/resetear_completamente"
COMPLETE_RESET_CONFIRMATION_PHRASE = "Si quiero resetear completamente"
COMPLETE_RESET_CONFIRMATION_TTL_SECONDS = 10 * 60
COMPLETE_RESET_EXECUTION_DELAY_SECONDS = 3
COMPLETE_RESET_ENV_GUARD_FILENAME = "complete_reset_environment_guard.json"


def utc_now():
    return datetime.now(timezone.utc)


def iso_utc(value):
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_utc(value):
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_private_json(path):
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_private_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return payload


def remove_private_file(path):
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


def reset_control_paths(product_root=None):
    root = Path(product_root or os.environ.get("ADMIRA_PRODUCT_ROOT") or Path(__file__).resolve().parent.parent).expanduser()
    data = root / "dashboard" / "data"
    return {
        "confirmation": Path(
            os.environ.get("ADMIRA_TELEGRAM_COMPLETE_RESET_CONFIRMATION_FILE")
            or data / "telegram_complete_reset_confirmation.json"
        ).expanduser(),
        "request": Path(
            os.environ.get("ADMIRA_TELEGRAM_COMPLETE_RESET_REQUEST_FILE")
            or data / "telegram_complete_reset_request.json"
        ).expanduser(),
        "result": Path(
            os.environ.get("ADMIRA_TELEGRAM_COMPLETE_RESET_RESULT_FILE")
            or data / "telegram_complete_reset_result.json"
        ).expanduser(),
    }


def active_reset_request(path):
    request = read_private_json(path)
    return request if request.get("status") in {"pending", "installing"} else {}


def begin_reset_confirmation(confirmation_path, request_path, chat_id, user_id, now=None):
    if active_reset_request(request_path):
        return {"ok": False, "status": "already_running"}
    current = now or utc_now()
    expires = current + timedelta(seconds=COMPLETE_RESET_CONFIRMATION_TTL_SECONDS)
    payload = {
        "status": "awaiting_confirmation",
        "confirmation_id": secrets.token_urlsafe(18),
        "chat_id": str(chat_id or ""),
        "user_id": str(user_id or ""),
        "created_at": iso_utc(current),
        "expires_at": iso_utc(expires),
    }
    write_private_json(confirmation_path, payload)
    return {"ok": True, **payload}


def pending_reset_confirmation(path, chat_id, user_id, now=None):
    pending = read_private_json(path)
    if pending.get("status") != "awaiting_confirmation":
        return {}
    if str(pending.get("chat_id") or "") != str(chat_id or ""):
        return {}
    if str(pending.get("user_id") or "") != str(user_id or ""):
        return {}
    expires = parse_utc(pending.get("expires_at"))
    if not expires or (now or utc_now()) >= expires:
        remove_private_file(path)
        return {"status": "expired"}
    return pending


def consume_reset_confirmation(confirmation_path, request_path, text, chat_id, user_id, now=None):
    current = now or utc_now()
    pending = pending_reset_confirmation(confirmation_path, chat_id, user_id, now=current)
    if not pending:
        return {"matched": False, "status": "none"}
    if pending.get("status") == "expired":
        return {"matched": True, "status": "expired"}
    supplied = str(text or "").strip()
    if not hmac.compare_digest(
        supplied.encode("utf-8"), COMPLETE_RESET_CONFIRMATION_PHRASE.encode("utf-8")
    ):
        remove_private_file(confirmation_path)
        return {"matched": True, "status": "cancelled"}
    execute_after = current + timedelta(seconds=COMPLETE_RESET_EXECUTION_DELAY_SECONDS)
    request = {
        "status": "pending",
        "request_id": secrets.token_urlsafe(18),
        "confirmation_id": str(pending.get("confirmation_id") or ""),
        "chat_id": str(chat_id or ""),
        "user_id": str(user_id or ""),
        "requested_at": iso_utc(current),
        "execute_after": iso_utc(execute_after),
        "target": "latest_stable",
        "preserve": ["license", "telegram", "primary_model", "image2_chatgpt"],
    }
    write_private_json(request_path, request)
    remove_private_file(confirmation_path)
    return {"matched": True, "status": "confirmed", "request": request}


AUTH_FILES = {
    "account.json", "auth.json", "auth.lock", "credentials.json", "credential.json",
    "login.json", "oauth.json", "openai.json", "token.json", "tokens.json",
    "openai-auth.json", "codex-auth.json",
}
AUTH_DIRS = {
    ".codex", "codex", "openai", "account", "auth", "login", "oauth", "tokens",
    "credentials", "openai-auth", "codex-auth",
}
AUTH_NAME_PARTS = {"account", "auth", "credential", "login", "oauth", "token"}
AUTH_SUFFIXES = {"", ".json", ".lock", ".db", ".sqlite", ".sqlite3"}


def is_auth_file(path):
    path = Path(path)
    name = path.name.lower()
    return path.is_file() and (
        path.name in AUTH_FILES
        or (path.suffix.lower() in AUTH_SUFFIXES and any(part in name for part in AUTH_NAME_PARTS))
    )


def _owner_writable(path, directory=False):
    try:
        mode = path.stat(follow_symlinks=False).st_mode
        additions = stat.S_IRUSR | stat.S_IWUSR | (stat.S_IXUSR if directory else 0)
        path.chmod(mode | additions, follow_symlinks=False)
    except (FileNotFoundError, NotImplementedError, OSError):
        pass


def remove_path_writable(path):
    path = Path(path)
    if path.is_symlink() or path.is_file():
        _owner_writable(path)
        path.unlink(missing_ok=True)
        return
    if not path.exists():
        return
    for root, directories, files in os.walk(path, topdown=False, followlinks=False):
        root_path = Path(root)
        for name in files:
            _owner_writable(root_path / name)
        for name in directories:
            child = root_path / name
            if child.is_symlink():
                child.unlink(missing_ok=True)
            else:
                _owner_writable(child, directory=True)
        _owner_writable(root_path, directory=True)
    shutil.rmtree(path)


def clear_directory(path, preserve=()):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    preserved = set(preserve)
    for child in list(path.iterdir()):
        if child.name not in preserved:
            remove_path_writable(child)


def prune_auth_directory(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    for child in list(path.iterdir()):
        if child.is_symlink():
            if not is_auth_file(child):
                child.unlink(missing_ok=True)
        elif child.is_dir():
            if child.name.lower() in AUTH_DIRS:
                prune_auth_directory(child)
            else:
                remove_path_writable(child)
        elif not is_auth_file(child):
            child.unlink(missing_ok=True)


def reset_state_home(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    for child in list(path.iterdir()):
        if child.is_symlink():
            if not is_auth_file(child):
                child.unlink(missing_ok=True)
        elif child.is_dir():
            if child.name.lower() in AUTH_DIRS:
                prune_auth_directory(child)
            else:
                remove_path_writable(child)
        elif not is_auth_file(child):
            child.unlink(missing_ok=True)


def rewrite_env(path, clear_keys, forced_values=None):
    path = Path(path)
    if not path.exists():
        return False
    forced_values = {str(key): str(value) for key, value in (forced_values or {}).items()}
    clear_keys = set(clear_keys)
    lines = []
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in forced_values:
            lines.append(f"{key}={forced_values[key]}")
            seen.add(key)
        elif key in clear_keys:
            lines.append(f"{key}=")
            seen.add(key)
        else:
            lines.append(line)
    for key in sorted(clear_keys - seen - set(forced_values)):
        lines.append(f"{key}=")
    for key, value in forced_values.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path.chmod(0o600)
    return True


def reset_workspace(
    *,
    runtime_dir,
    data_dir,
    output_dir,
    logs_dir,
    brand_guides_dir,
    brand_seed_dir,
    ad_config_example,
    env_paths,
    clear_env_keys,
    forced_env_values=None,
    preserve_data_names=(),
):
    """Remove buyer state while preserving only durable auth and control files."""
    runtime = Path(runtime_dir)
    data = Path(data_dir)
    output = Path(output_dir)
    logs = Path(logs_dir)
    brand_guides = Path(brand_guides_dir)
    brand_seed = Path(brand_seed_dir)
    ad_config_example = Path(ad_config_example)
    preserved_data = {
        # This path is a dedicated Docker volume in cloud and desktop installs.
        # Deleting the mount point raises EBUSY and aborts the confirmed reset.
        # Snapshot retention is owned by the updater, so preserve the mount.
        "license_unlock.json", "hermes-home", "hermes-image-home", "update-snapshots",
        *preserve_data_names,
    }

    for env_path in {Path(item).resolve() for item in env_paths if Path(item).exists()}:
        rewrite_env(env_path, clear_env_keys, forced_env_values)

    clear_directory(data, preserve=preserved_data)
    reset_state_home(data / "hermes-home")
    reset_state_home(data / "hermes-image-home")
    clear_directory(output)
    clear_directory(logs)
    clear_directory(brand_guides)
    if brand_seed.exists():
        shutil.copytree(brand_seed, brand_guides, dirs_exist_ok=True)

    runtime.mkdir(parents=True, exist_ok=True)
    reset_state_home(runtime / "hermes")
    reset_state_home(runtime / "codex")
    (runtime / "codex" / "generated_images").mkdir(parents=True, exist_ok=True)
    for child in list(runtime.iterdir()):
        if child.name in {".env", "ad-config.json", "hermes", "codex"}:
            continue
        remove_path_writable(child)

    ad_config_path = runtime / "ad-config.json"
    try:
        config = json.loads(ad_config_example.read_text(encoding="utf-8")) if ad_config_example.exists() else {}
    except (OSError, json.JSONDecodeError):
        config = {}
    account = config.setdefault("account", {})
    account["id"] = ""
    account["name"] = ""
    brand = config.setdefault("brand", {})
    for key in ("name", "offer", "voice", "visual_style"):
        brand[key] = ""
    brand["avoid"] = []
    destination = config.setdefault("creative", {}).setdefault("destination", {})
    for key in ("page_id", "instagram_actor_id", "default_adset_id", "url"):
        destination[key] = ""
    ad_config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ad_config_path.chmod(0o600)
    write_private_json(data / COMPLETE_RESET_ENV_GUARD_FILENAME, {
        "status": "active",
        "created_at": iso_utc(utc_now()),
        "clear_env_keys": sorted(str(key) for key in clear_env_keys),
    })
    return {
        "ok": True,
        "preserved": ["license", "telegram", "primary_model", "image2_chatgpt"],
    }
