#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then exit 2; fi
JOB_ID="$1"
CONFIG_FILE="/etc/admira-cloud-access-gate/env"
if [ -f "$CONFIG_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$CONFIG_FILE"
  set +a
fi
STATE_DIR="${ADMIRA_CLOUD_STATE_DIR:-/var/lib/admira-cloud-access-gate}"
STATE_FILE="$STATE_DIR/reset-state.json"
INSTALL_DIR="${ADMIRA_CLOUD_INSTALL_DIR:-/opt/admira-ia}"
COMPOSE_PROJECT="${ADMIRA_CLOUD_COMPOSE_PROJECT:-admira-ia}"
ENV_FILE="$INSTALL_DIR/.env"
BACKUP_DIR="$(mktemp -d /run/admira-clean-reset.XXXXXX)"
HOST_ENV_BACKUP="$BACKUP_DIR/host.env"
RUNTIME_ENV_BACKUP=".clean-reset-backup"
mkdir -p "$STATE_DIR"
chmod 0700 "$STATE_DIR"

set_state() {
  /usr/bin/python3 - "$STATE_FILE" "$JOB_ID" "$1" "$2" <<'PY'
import json
import os
import sys
import tempfile
import time
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "job_id": sys.argv[2],
    "status": sys.argv[3],
    "detail": sys.argv[4],
    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
}
path.parent.mkdir(parents=True, exist_ok=True)
fd, temporary = tempfile.mkstemp(prefix="reset-state.", dir=str(path.parent))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
        handle.write("\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY
}

restore_host_env() {
  if [ -f "$HOST_ENV_BACKUP" ]; then cp -p "$HOST_ENV_BACKUP" "$ENV_FILE"; fi
}

on_error() {
  local code="$1"
  trap - ERR
  restore_host_env || true
  if [ -d "$INSTALL_DIR" ]; then
    cd "$INSTALL_DIR" || true
    docker compose -p "$COMPOSE_PROJECT" up -d --force-recreate >/dev/null 2>&1 || true
  fi
  set_state failed "No pude completar la limpieza de la instalacion cloud."
  rm -rf "$BACKUP_DIR"
  exit "$code"
}
trap 'on_error $?' ERR

set_state running "Limpiando el estado de prueba y conservando las conexiones autorizadas…"
if [ ! -d "$INSTALL_DIR" ] || [ ! -f "$ENV_FILE" ]; then
  set_state failed "No encontre la instalacion cloud en el servidor."
  exit 1
fi
cp -p "$ENV_FILE" "$HOST_ENV_BACKUP"
cd "$INSTALL_DIR"
docker compose -p "$COMPOSE_PROJECT" down --remove-orphans

/usr/bin/python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
clear_keys = {
    "DASHBOARD_PASSWORD", "DASHBOARD_PASSWORD_HASH", "DASHBOARD_TOKEN",
    "META_AD_ACCOUNT_ID",
    "META_ACCESS_TOKEN", "META_ACCESS_TOKEN_KIND", "META_ACCESS_TOKEN_SAVED_AT",
    "META_PUBLISHING_ACCESS_TOKEN", "META_PUBLISHING_TOKEN_SAVED_AT",
    "SHOPIFY_SHOP_DOMAIN", "SHOPIFY_ADMIN_API_TOKEN",
    "TELEGRAM_AGENT_ENABLED", "TELEGRAM_CHAT_ID",
    "DAILY_SOCIAL_CONTENT_ENABLED", "DAILY_SOCIAL_CONTENT_DECISION",
    "DAILY_SOCIAL_CONTENT_TIME", "DAILY_SOCIAL_CONTENT_POSTS_PER_DAY",
    "DAILY_SOCIAL_CONTENT_INTERVAL_DAYS", "DAILY_SOCIAL_CONTENT_FORMATS",
    "DAILY_SOCIAL_CONTENT_VIDEO_INTERVAL_DAYS",
}
lines, seen = [], set()
for line in path.read_text(encoding="utf-8").splitlines():
    key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
    if key in clear_keys:
        lines.append(f"{key}=")
        seen.add(key)
    else:
        lines.append(line)
for key in sorted(clear_keys - seen):
    lines.append(f"{key}=")
path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
path.chmod(0o600)
PY

docker compose -p "$COMPOSE_PROJECT" run --rm --no-deps -T --entrypoint python3 meta-ads-agent - "$RUNTIME_ENV_BACKUP" <<'PY'
import json
from pathlib import Path
import shutil
import sys

runtime = Path("/app/runtime")
runtime_env = runtime / ".env"
backup = runtime / sys.argv[1]
if runtime_env.exists():
    shutil.copy2(runtime_env, backup)
    backup.chmod(0o600)
clear_keys = {
    "DASHBOARD_PASSWORD", "DASHBOARD_PASSWORD_HASH", "DASHBOARD_TOKEN",
    "META_AD_ACCOUNT_ID",
    "META_ACCESS_TOKEN", "META_ACCESS_TOKEN_KIND", "META_ACCESS_TOKEN_SAVED_AT",
    "META_PUBLISHING_ACCESS_TOKEN", "META_PUBLISHING_TOKEN_SAVED_AT",
    "SHOPIFY_SHOP_DOMAIN", "SHOPIFY_ADMIN_API_TOKEN",
    "TELEGRAM_AGENT_ENABLED", "TELEGRAM_CHAT_ID",
    "DAILY_SOCIAL_CONTENT_ENABLED", "DAILY_SOCIAL_CONTENT_DECISION",
    "DAILY_SOCIAL_CONTENT_TIME", "DAILY_SOCIAL_CONTENT_POSTS_PER_DAY",
    "DAILY_SOCIAL_CONTENT_INTERVAL_DAYS", "DAILY_SOCIAL_CONTENT_FORMATS",
    "DAILY_SOCIAL_CONTENT_VIDEO_INTERVAL_DAYS",
}
if runtime_env.exists():
    lines, seen = [], set()
    for line in runtime_env.read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in clear_keys:
            lines.append(f"{key}=")
            seen.add(key)
        else:
            lines.append(line)
    for key in sorted(clear_keys - seen):
        lines.append(f"{key}=")
    runtime_env.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    runtime_env.chmod(0o600)

def clear_directory(path, preserve=()):
    path.mkdir(parents=True, exist_ok=True)
    preserved = set(preserve)
    for child in path.iterdir():
        if child.name in preserved:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()

# A cloud reset is a fresh buyer workspace, not a source-code reset. Keep only
# the durable license identity and provider authentication artifacts. All other
# Hermes state (memory, sessions, history, personal skills, prompts, caches and
# old workspaces) is removed and recreated empty below.
AUTH_FILES = {
    "account.json", "auth.json", "auth.lock", "credentials.json", "credential.json",
    "login.json", "oauth.json", "openai.json", "token.json", "tokens.json",
    "session.json", "sessions.json", "openai-auth.json", "codex-auth.json",
}
AUTH_DIRS = {".codex", "codex", "openai", "account", "auth", "login", "oauth", "tokens", "credentials", "openai-auth", "codex-auth"}
AUTH_NAME_PARTS = {"account", "auth", "credential", "login", "oauth", "session", "token"}
AUTH_SUFFIXES = {"", ".json", ".lock", ".db", ".sqlite", ".sqlite3"}

def is_auth_file(path):
    name = path.name.lower()
    return (
        path.is_file()
        and (
            path.name in AUTH_FILES
            or (path.suffix.lower() in AUTH_SUFFIXES and any(part in name for part in AUTH_NAME_PARTS))
        )
    )

def prune_auth_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    for child in list(path.iterdir()):
        if child.is_symlink():
            if not is_auth_file(child):
                child.unlink()
        elif child.is_dir():
            if child.name.lower() in AUTH_DIRS:
                prune_auth_dir(child)
            else:
                shutil.rmtree(child)
        elif not is_auth_file(child):
            child.unlink()

def reset_state_home(path):
    path.mkdir(parents=True, exist_ok=True)
    for child in list(path.iterdir()):
        if child.is_symlink():
            if not is_auth_file(child):
                child.unlink()
        elif child.is_dir():
            if child.name.lower() in AUTH_DIRS:
                prune_auth_dir(child)
            else:
                shutil.rmtree(child)
        elif not is_auth_file(child):
            child.unlink()

clear_directory(Path("/app/dashboard/data"), preserve=("hermes-home", "hermes-image-home", "license_unlock.json", "update-snapshots"))
clear_directory(Path("/app/dashboard/data/update-snapshots"))
reset_state_home(Path("/app/dashboard/data/hermes-home"))
reset_state_home(Path("/app/dashboard/data/hermes-image-home"))
clear_directory(Path("/app/output"))
clear_directory(Path("/app/logs"))
clear_directory(Path("/app/brand_guides"))
reset_state_home(runtime / "hermes")
reset_state_home(runtime / "codex")
(runtime / "codex" / "generated_images").mkdir(parents=True, exist_ok=True)
for child in list(runtime.iterdir()):
    if child.name in {".env", "ad-config.json", "hermes", "codex"}:
        continue
    if child.is_dir() and not child.is_symlink():
        shutil.rmtree(child)
    else:
        child.unlink()
ad_config = runtime / "ad-config.json"
example = Path("/app/ad-config.example.json")
if example.exists():
    try:
        config = json.loads(example.read_text(encoding="utf-8"))
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
    ad_config.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
else:
    ad_config.write_text("{}\n", encoding="utf-8")
ad_config.chmod(0o600)
seed = Path("/app/brand_guides_seed")
if seed.exists():
    shutil.copytree(seed, "/app/brand_guides", dirs_exist_ok=True)
PY

docker compose -p "$COMPOSE_PROJECT" up -d --force-recreate
ready="false"
for _attempt in $(seq 1 90); do
  if curl -fsS --max-time 3 "http://127.0.0.1:${DASHBOARD_PORT:-7871}/" >/dev/null 2>&1; then
    ready="true"
    break
  fi
  sleep 2
done
if [ "$ready" != "true" ]; then
  restore_host_env
  docker compose -p "$COMPOSE_PROJECT" up -d --force-recreate || true
  set_state failed "El dashboard no respondio despues de limpiar la instalacion."
  rm -rf "$BACKUP_DIR"
  exit 1
fi

docker compose -p "$COMPOSE_PROJECT" run --rm --no-deps -T --entrypoint python3 meta-ads-agent - "$RUNTIME_ENV_BACKUP" <<'PY'
from pathlib import Path
import sys
backup = Path("/app/runtime") / sys.argv[1]
if backup.exists():
    backup.unlink()
PY
set_state complete "Instalacion base lista. Se conservaron las credenciales autorizadas y la licencia; se borraron memoria, skills personales, sesiones, configuracion de anuncios, Meta y contraseña."
rm -rf "$BACKUP_DIR"
