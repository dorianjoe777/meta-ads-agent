#!/usr/bin/env bash
set -euo pipefail

# Prepare only the host-owned boundaries for the dormant central image broker.
# This script never starts Compose, enables ADMIRA_CENTRAL_IMAGE_READY, logs in
# to ChatGPT/Codex, or copies the central credential into a tenant.

SERVICE_USER="${ADMIRA_SERVICE_USER:-admiraops}"
CENTRAL_IMAGE_GROUP="${ADMIRA_CENTRAL_IMAGE_GROUP:-admira-central-image}"
CENTRAL_IMAGE_GID="${ADMIRA_CENTRAL_IMAGE_GID:-19093}"

if [[ "$(id -u)" -ne 0 ]]; then
  printf '%s\n' 'Run this preparation with sudo.' >&2
  exit 1
fi
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  printf 'Service user does not exist: %s\n' "$SERVICE_USER" >&2
  exit 1
fi

service_uid="$(id -u "$SERVICE_USER")"

if [[ ! "$CENTRAL_IMAGE_GID" =~ ^[0-9]+$ || "$CENTRAL_IMAGE_GID" -lt 1 || "$CENTRAL_IMAGE_GID" -gt 65534 ]]; then
  printf 'Invalid central-image GID: %s\n' "$CENTRAL_IMAGE_GID" >&2
  exit 1
fi

# Reserve one stable host/container group for the broker socket. Refuse an
# occupied numeric GID rather than silently changing permissions for another
# service. Re-running this script is safe once the mapping exists.
if getent group "$CENTRAL_IMAGE_GROUP" >/dev/null 2>&1; then
  existing_gid="$(getent group "$CENTRAL_IMAGE_GROUP" | awk -F: 'NR == 1 { print $3 }')"
  if [[ "$existing_gid" != "$CENTRAL_IMAGE_GID" ]]; then
    printf 'Central-image group has unexpected GID: %s (%s)\n' "$CENTRAL_IMAGE_GROUP" "$existing_gid" >&2
    exit 1
  fi
elif getent group "$CENTRAL_IMAGE_GID" >/dev/null 2>&1; then
  occupied_group="$(getent group "$CENTRAL_IMAGE_GID" | awk -F: 'NR == 1 { print $1 }')"
  printf 'Central-image GID %s is already assigned to %s\n' "$CENTRAL_IMAGE_GID" "$occupied_group" >&2
  exit 1
else
  groupadd --system --gid "$CENTRAL_IMAGE_GID" "$CENTRAL_IMAGE_GROUP"
fi

prepare_directory() {
  local path="$1" mode="$2" owner_uid owner_gid
  if [[ -L "$path" || ( -e "$path" && ! -d "$path" ) ]]; then
    printf 'Refusing unsafe central-image path: %s\n' "$path" >&2
    exit 1
  fi
  if [[ -d "$path" ]]; then
    owner_uid="$(stat -c '%u' "$path" 2>/dev/null || stat -f '%u' "$path")"
    owner_gid="$(stat -c '%g' "$path" 2>/dev/null || stat -f '%g' "$path")"
    if [[ "$owner_uid" != "$service_uid" || "$owner_gid" != "$CENTRAL_IMAGE_GID" ]]; then
      printf 'Central-image path has unexpected ownership: %s\n' "$path" >&2
      exit 1
    fi
    chmod "$mode" "$path"
  else
    install -d -m "$mode" -o "$SERVICE_USER" -g "$CENTRAL_IMAGE_GROUP" "$path"
  fi
}

prepare_directory /run/admira-central-image-broker 0750
prepare_directory /etc/admira/central-image-keys 0700
prepare_directory /srv/admira/shared/central-image-exchange 0700
prepare_directory /srv/admira/shared/central-codex-auth 0700

printf '%s\n' 'Central-image host boundaries are prepared; the service remains disabled.'
