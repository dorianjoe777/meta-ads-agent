#!/usr/bin/env bash
set -euo pipefail

# Install the host-only lifecycle bridge. It deliberately has Docker access
# because it must call the existing allowlisted tenant tools; the dashboard
# never receives that access, the tenant root, or a provisioner DB password.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_USER="${ADMIRA_SERVICE_USER:-admiraops}"
GROUP="${ADMIRA_PROVISIONER_GROUP:-admira-provisioner}"
GID="${ADMIRA_PROVISIONER_GID:-19094}"
KEY_SOURCE="$ROOT_DIR/secrets/tenant_provisioner_key.txt"
BRIDGE_SOURCE="$ROOT_DIR/secrets/license_hosted_bridge_key.txt"
KEY_TARGET="/etc/admira/tenant-provisioner.key"
BRIDGE_TARGET="/etc/admira/hosted-license-bridge.key"
STATE_DIR="/var/lib/admira/tenant-provisioner"

die() { printf '%s\n' "$1" >&2; exit 1; }

if [[ "$(id -u)" -ne 0 ]]; then die 'Run with sudo.'; fi

safe_secret_source() {
  local path="$1"
  if [[ -L "$path" || ! -f "$path" || ! -s "$path" ]]; then
    die 'A required private lifecycle secret is absent or unsafe. Run bootstrap first.'
  fi
  local mode
  mode="$(stat -c '%a' "$path" 2>/dev/null || stat -f '%Lp' "$path")"
  if [[ ! "$mode" =~ ^0*(400|600)$ ]]; then
    die 'A required lifecycle secret must be a private 0400 or 0600 file.'
  fi
}

read_config() {
  local wanted="$1" fallback="$2" result="" line key value
  if [[ -n "${!wanted+x}" ]]; then
    printf '%s' "${!wanted}"
    return
  fi
  if [[ -r "$ROOT_DIR/.env" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      [[ "$line" == *=* ]] || continue
      key="${line%%=*}"; value="${line#*=}"; value="${value%$'\r'}"
      if [[ "$key" == "$wanted" ]]; then
        value="${value#\"}"; value="${value%\"}"
        value="${value#\'}"; value="${value%\'}"
        result="$value"
      fi
    done < "$ROOT_DIR/.env"
  fi
  printf '%s' "${result:-$fallback}"
}

SERVICE_USER="$(read_config ADMIRA_SERVICE_USER "$SERVICE_USER")"
GROUP="$(read_config ADMIRA_PROVISIONER_GROUP "$GROUP")"
GID="$(read_config ADMIRA_PROVISIONER_GID "$GID")"
if ! id "$SERVICE_USER" >/dev/null 2>&1; then die 'The Admira service user does not exist.'; fi
if [[ ! "$GROUP" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]]; then die 'Provisioner group is invalid.'; fi
if [[ ! "$GID" =~ ^[1-9][0-9]{3,4}$ || "$GID" -gt 65534 ]]; then die 'Provisioner GID is invalid.'; fi

BOT_USERNAME="$(read_config ADMIRA_TELEGRAM_BOT_USERNAME admiraia_bot)"
LICENSE_URL="$(read_config ADMIRA_LICENSE_API_URL https://admiraia.uboost.lat/api/admin/licenses)"
if [[ ! "$BOT_USERNAME" =~ ^[A-Za-z0-9_]{5,32}$ ]]; then die 'ADMIRA_TELEGRAM_BOT_USERNAME is invalid.'; fi
if [[ "$LICENSE_URL" != 'https://admiraia.uboost.lat/api/admin/licenses' ]]; then
  die 'ADMIRA_LICENSE_API_URL must be the approved HTTPS hosted-license endpoint.'
fi

safe_secret_source "$KEY_SOURCE"
safe_secret_source "$BRIDGE_SOURCE"

existing_gid="$(getent group "$GROUP" | cut -d: -f3 || true)"
if [[ -z "$existing_gid" ]]; then
  groupadd --system --gid "$GID" "$GROUP"
elif [[ "$existing_gid" != "$GID" ]]; then
  die 'The configured tenant-provisioner group has a different GID.'
fi
usermod -a -G "$GROUP" "$SERVICE_USER"

for path in /etc/admira /var/lib/admira "$STATE_DIR" "$STATE_DIR/docker"; do
  if [[ -L "$path" || ( -e "$path" && ! -d "$path" ) ]]; then
    die 'A required lifecycle directory is unsafe.'
  fi
done
install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_USER" /etc/admira
install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_USER" /var/lib/admira
install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_USER" "$STATE_DIR" "$STATE_DIR/docker"
install -m 0600 -o "$SERVICE_USER" -g "$SERVICE_USER" "$KEY_SOURCE" "$KEY_TARGET"
install -m 0600 -o "$SERVICE_USER" -g "$SERVICE_USER" "$BRIDGE_SOURCE" "$BRIDGE_TARGET"

install -m 0644 /dev/stdin /etc/systemd/system/admira-tenant-provisioner.service <<UNIT
[Unit]
Description=Admira host-only tenant lifecycle boundary
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
# Docker membership is root-equivalent on this host. It is intentionally
# confined to this allowlisted daemon; never add the dashboard container/user.
SupplementaryGroups=docker $GROUP
WorkingDirectory=$ROOT_DIR
RuntimeDirectory=admira-tenant-provisioner
RuntimeDirectoryMode=0750
Environment=ADMIRA_TELEGRAM_BOT_USERNAME=$BOT_USERNAME
Environment=ADMIRA_LICENSE_API_URL=$LICENSE_URL
Environment=ADMIRA_LICENSE_BRIDGE_KEY_FILE=$BRIDGE_TARGET
Environment=ADMIRA_BROKER_SOCKET=/run/admira-runtime-broker/broker.sock
Environment=ADMIRA_BROKER_KEY_FILE=/etc/admira/runtime-broker.key
Environment=DOCKER_CONFIG=$STATE_DIR/docker
ExecStart=/usr/bin/python3 $ROOT_DIR/tenant_provisioner.py serve --socket-gid $GID --replay-state $STATE_DIR/replay-nonces.json
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
# gemini_pool_admin.assign reads the private pool key through this root and
# normalizes its private mode. tenantctl.provision also creates only the
# per-tenant central-image verifier and exchange directory when those host
# roots were explicitly prepared. Keep all of these narrow capabilities on
# this host daemon only; the dashboard has no mount or write access to them.
ReadWritePaths=/srv/admira/tenants /etc/admira/gemini-pool /etc/admira/central-image-keys /srv/admira/shared/central-image-exchange $STATE_DIR /run/admira-tenant-provisioner
CapabilityBoundingSet=
RestrictSUIDSGID=true
LockPersonality=true
MemoryDenyWriteExecute=true
SystemCallArchitectures=native

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable admira-tenant-provisioner.service
systemctl restart admira-tenant-provisioner.service
systemctl is-active --quiet admira-tenant-provisioner.service
printf '%s\n' 'Admira tenant provisioner is active. The dashboard still has no Docker, tenant-root, or provisioner-DB access.'
