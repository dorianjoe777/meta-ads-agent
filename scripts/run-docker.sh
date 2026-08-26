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
# the same release.  Without this explicit build value, Compose can continue
# tagging a rebuilt image as `local` (or retain a previous version tag), which
# makes a successful in-container update look like a stale installation.
if [ -f "$ROOT_DIR/VERSION" ]; then
  export ADMIRA_BUILD_VERSION="${ADMIRA_BUILD_VERSION:-$(tr -d '[:space:]' < "$ROOT_DIR/VERSION")}"
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

# Every installation has its own Compose project/container/volume namespace.
# Older installations keep the original defaults, while new profiles can set
# these values in .env without affecting any other instance on the machine.
compose_project="${ADMIRA_COMPOSE_PROJECT_NAME:-admira-ia}"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example for Docker Compose."
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
