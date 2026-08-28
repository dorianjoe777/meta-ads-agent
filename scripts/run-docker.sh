#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required for this install option."
  exit 1
fi

detect_lan_ip() {
  python3 - <<'PY' 2>/dev/null || true
import socket

ip = ""
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.2)
    sock.connect(("8.8.8.8", 80))
    ip = sock.getsockname()[0]
    sock.close()
except OSError:
    pass
print(ip)
PY
}

legacy_host_lan_var="ADMI""RO_HOST_LAN_IP"
legacy_skip_build_var="ADMI""RO_DOCKER_SKIP_BUILD"
legacy_detached_var="ADMI""RO_DOCKER_DETACHED"

export ADMIRA_HOST_LAN_IP="${ADMIRA_HOST_LAN_IP:-${!legacy_host_lan_var:-$(detect_lan_ip)}}"

# Keep the Docker image label, runtime environment and application payload on
# the same release.  VERSION is authoritative whenever this is run from a
# versioned source tree: an exported value from a previous install must not
# make a newer checkout build under an older release tag.
if [ -f "$ROOT_DIR/VERSION" ]; then
  canonical_version="$(tr -d '[:space:]' < "$ROOT_DIR/VERSION")"
  if [ -n "$canonical_version" ]; then
    export ADMIRA_BUILD_VERSION="$canonical_version"
  fi
fi
if git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  export ADMIRA_BUILD_SHA="${ADMIRA_BUILD_SHA:-$(git -C "$ROOT_DIR" rev-parse HEAD)}"
  export ADMIRA_SOURCE_MANIFEST="${ADMIRA_SOURCE_MANIFEST:-$(python3 "$ROOT_DIR/scripts/source_manifest.py" --root "$ROOT_DIR")}"
else
  if [ -f "$ROOT_DIR/build-commit.sha" ]; then
    export ADMIRA_BUILD_SHA="${ADMIRA_BUILD_SHA:-$(tr -d '[:space:]' < "$ROOT_DIR/build-commit.sha")}"
  fi
  if [ -f "$ROOT_DIR/source-manifest.sha256" ]; then
    export ADMIRA_SOURCE_MANIFEST="${ADMIRA_SOURCE_MANIFEST:-$(tr -d '[:space:]' < "$ROOT_DIR/source-manifest.sha256")}"
  fi
fi
export ADMIRA_BUILD_SHA="${ADMIRA_BUILD_SHA:-unknown}"
export ADMIRA_SOURCE_MANIFEST="${ADMIRA_SOURCE_MANIFEST:-unknown}"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example for Docker Compose."
fi

# Compose loads .env after the shell has already started.  We need the project
# name for `docker compose -p` ourselves, so read only this one safe key rather
# than sourcing the complete file (which may contain secrets or shell syntax).
# Preserve Compose's precedence: an explicitly exported environment value wins
# over .env, and the product default is used only when neither has a value.
read_dotenv_value() {
  local key="$1"
  local file="$2"
  awk -F= -v wanted="$key" '
    /^[[:space:]]*(#|$)/ { next }
    {
      lhs=$1
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", lhs)
      if (lhs != wanted) { next }
      value=$0
      sub(/^[^=]*=/, "", value)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      if (value ~ /^".*"$/ || value ~ /^'"'"'.*'"'"'$/) {
        value=substr(value, 2, length(value)-2)
      }
      print value
      exit
    }
  ' "$file"
}

# A previous shell or .env can retain the image name from an older release.
# Update only the conventional release tags (:rNN); custom tags such as
# `:staging` remain user-controlled.  This keeps registry/repository prefixes
# intact while preventing a stale canary image from being selected.
dotenv_image_name="$(read_dotenv_value ADMIRA_IMAGE_NAME .env)"
image_name="${ADMIRA_IMAGE_NAME:-$dotenv_image_name}"
if [[ "$image_name" =~ ^(.+):r[0-9]+$ && -n "${canonical_version:-}" ]]; then
  export ADMIRA_IMAGE_NAME="${BASH_REMATCH[1]}:$canonical_version"
fi

if [[ -n "${ADMIRA_COMPOSE_PROJECT_NAME+x}" && -n "$ADMIRA_COMPOSE_PROJECT_NAME" ]]; then
  compose_project="$ADMIRA_COMPOSE_PROJECT_NAME"
else
  compose_project="$(read_dotenv_value ADMIRA_COMPOSE_PROJECT_NAME .env)"
  compose_project="${compose_project:-admira-ia}"
fi

compose_args=(up)
if [ "${ADMIRA_DOCKER_SKIP_BUILD:-${!legacy_skip_build_var:-false}}" != "true" ]; then
  compose_args+=(--build)
fi
if [ "${ADMIRA_DOCKER_DETACHED:-${!legacy_detached_var:-false}}" = "true" ]; then
  compose_args+=(--detach)
fi

if docker compose version >/dev/null 2>&1; then
  docker compose -p "$compose_project" "${compose_args[@]}"
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose -p "$compose_project" "${compose_args[@]}"
else
  echo "Docker Compose is required. Install Docker Desktop or docker compose plugin."
  exit 1
fi
