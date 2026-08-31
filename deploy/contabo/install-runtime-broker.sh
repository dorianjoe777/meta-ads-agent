#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_USER="${ADMIRA_SERVICE_USER:-admiraops}"
BROKER_GROUP="${ADMIRA_BROKER_GROUP:-admira-broker}"
BROKER_GID="${ADMIRA_BROKER_GID:-19091}"
SPOOL_GROUP="${ADMIRA_SPOOL_GROUP:-admira-spool}"
SPOOL_GID="${ADMIRA_SPOOL_GID:-19092}"
BROKER_KEY_SOURCE="$ROOT_DIR/secrets/runtime_broker_key.txt"
MAX_ACTIVE_TENANTS="${ADMIRA_MAX_ACTIVE_TENANTS:-}"
NORMAL_ACTIVE_TENANTS="${ADMIRA_NORMAL_ACTIVE_TENANTS:-}"
HARD_MAX_ACTIVE_TENANTS="${ADMIRA_HARD_MAX_ACTIVE_TENANTS:-}"
BURST_MIN_AVAILABLE_MB="${ADMIRA_BURST_MIN_AVAILABLE_MB:-}"
CENTRAL_IMAGE_IMAGE="${CENTRAL_IMAGE_IMAGE:-}"
FILE_MAX_ACTIVE_TENANTS=""
FILE_NORMAL_ACTIVE_TENANTS=""
FILE_HARD_MAX_ACTIVE_TENANTS=""
FILE_BURST_MIN_AVAILABLE_MB=""
if [[ -r "$ROOT_DIR/.env" ]]; then
  while IFS='=' read -r config_key config_value; do
    config_value="${config_value%$'\r'}"
    case "$config_key" in
      ADMIRA_MAX_ACTIVE_TENANTS) FILE_MAX_ACTIVE_TENANTS="$config_value" ;;
      ADMIRA_NORMAL_ACTIVE_TENANTS) FILE_NORMAL_ACTIVE_TENANTS="$config_value" ;;
      ADMIRA_HARD_MAX_ACTIVE_TENANTS) FILE_HARD_MAX_ACTIVE_TENANTS="$config_value" ;;
      ADMIRA_BURST_MIN_AVAILABLE_MB) FILE_BURST_MIN_AVAILABLE_MB="$config_value" ;;
      CENTRAL_IMAGE_IMAGE) CENTRAL_IMAGE_IMAGE="$config_value" ;;
    esac
  done < "$ROOT_DIR/.env"
fi
MAX_ACTIVE_TENANTS="${MAX_ACTIVE_TENANTS:-${FILE_MAX_ACTIVE_TENANTS:-4}}"
NORMAL_ACTIVE_TENANTS="${NORMAL_ACTIVE_TENANTS:-$FILE_NORMAL_ACTIVE_TENANTS}"
HARD_MAX_ACTIVE_TENANTS="${HARD_MAX_ACTIVE_TENANTS:-$FILE_HARD_MAX_ACTIVE_TENANTS}"
BURST_MIN_AVAILABLE_MB="${BURST_MIN_AVAILABLE_MB:-$FILE_BURST_MIN_AVAILABLE_MB}"
NORMAL_ACTIVE_TENANTS="${NORMAL_ACTIVE_TENANTS:-$MAX_ACTIVE_TENANTS}"
HARD_MAX_ACTIVE_TENANTS="${HARD_MAX_ACTIVE_TENANTS:-$MAX_ACTIVE_TENANTS}"
BURST_MIN_AVAILABLE_MB="${BURST_MIN_AVAILABLE_MB:-2048}"

# This installer never builds or pulls tenant images. If the optional
# central-images profile is configured, reject mutable/ambiguous references
# before a later operator activation can select one accidentally.
if [[ -n "$CENTRAL_IMAGE_IMAGE" ]] && [[ ! "$CENTRAL_IMAGE_IMAGE" =~ ^admira-ia-hosted:r91-canary-[0-9a-f]{12}$ ]]; then
  printf '%s\n' 'CENTRAL_IMAGE_IMAGE must be an exact admira-ia-hosted:r91-canary-<12 lowercase commit hex> tag.' >&2
  exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
  printf '%s\n' 'Run this installer with sudo.' >&2
  exit 1
fi
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  printf 'Service user does not exist: %s\n' "$SERVICE_USER" >&2
  exit 1
fi
if [[ ! -s "$BROKER_KEY_SOURCE" ]]; then
  printf '%s\n' 'Generate control-plane secrets before installing the broker.' >&2
  exit 1
fi
if [[ ! "$MAX_ACTIVE_TENANTS" =~ ^[1-9][0-9]*$ ]] ||
   [[ ! "$NORMAL_ACTIVE_TENANTS" =~ ^[1-9][0-9]*$ ]] ||
   [[ ! "$HARD_MAX_ACTIVE_TENANTS" =~ ^[1-9][0-9]*$ ]] ||
   [[ ! "$BURST_MIN_AVAILABLE_MB" =~ ^[0-9]+$ ]] ||
   (( MAX_ACTIVE_TENANTS > 8 || NORMAL_ACTIVE_TENANTS > HARD_MAX_ACTIVE_TENANTS || HARD_MAX_ACTIVE_TENANTS > 8 )); then
  printf '%s\n' 'Capacity settings must satisfy 1 <= normal <= hard <= 8.' >&2
  exit 1
fi

ensure_group() {
  local group_name="$1" group_gid="$2" existing
  existing="$(getent group "$group_name" | cut -d: -f3 || true)"
  if [[ -z "$existing" ]]; then
    if getent group "$group_gid" >/dev/null; then
      printf 'Requested group id %s is already in use.\n' "$group_gid" >&2
      exit 1
    fi
    groupadd --system --gid "$group_gid" "$group_name"
  elif [[ "$existing" != "$group_gid" ]]; then
    printf 'Group %s exists with gid %s, expected %s.\n' "$group_name" "$existing" "$group_gid" >&2
    exit 1
  fi
}

ensure_group "$BROKER_GROUP" "$BROKER_GID"
ensure_group "$SPOOL_GROUP" "$SPOOL_GID"
usermod -a -G "$BROKER_GROUP,$SPOOL_GROUP" "$SERVICE_USER"

install -d -m 0750 -o "$SERVICE_USER" -g "$BROKER_GROUP" /run/admira-runtime-broker
DOCKER_CONFIG_DIR=/run/admira-runtime-broker/docker-config
# Docker's CLI may otherwise consult a home-directory config. Keep the
# broker's rootless CLI state in its explicitly writable, private runtime
# directory; root performs the installation, but the broker user owns it.
install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_USER" "$DOCKER_CONFIG_DIR"
printf '%s\n' '{}' | install -m 0600 -o "$SERVICE_USER" -g "$SERVICE_USER" /dev/stdin "$DOCKER_CONFIG_DIR/config.json"
install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_USER" /etc/admira
install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" /srv/admira/shared/telegram-spool
install -d -m 0770 -o "$SERVICE_USER" -g "$SPOOL_GROUP" /srv/admira/shared/telegram-spool/inbound
install -d -m 0770 -o "$SERVICE_USER" -g "$SPOOL_GROUP" /srv/admira/shared/telegram-spool/outbound
install -m 0600 -o "$SERVICE_USER" -g "$SERVICE_USER" "$BROKER_KEY_SOURCE" /etc/admira/runtime-broker.key
install -m 0644 /dev/stdin /etc/systemd/system/admira-runtime-broker.service <<UNIT
[Unit]
Description=Admira isolated tenant runtime broker
After=docker.service
Requires=docker.service

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
SupplementaryGroups=docker $BROKER_GROUP $SPOOL_GROUP
WorkingDirectory=$ROOT_DIR
ExecStart=/usr/bin/python3 $ROOT_DIR/runtime_broker.py serve --socket-gid $BROKER_GID
Restart=on-failure
RestartSec=3
UMask=0077
Environment=ADMIRA_MAX_ACTIVE_TENANTS=$MAX_ACTIVE_TENANTS
Environment=ADMIRA_NORMAL_ACTIVE_TENANTS=$NORMAL_ACTIVE_TENANTS
Environment=ADMIRA_HARD_MAX_ACTIVE_TENANTS=$HARD_MAX_ACTIVE_TENANTS
Environment=ADMIRA_BURST_MIN_AVAILABLE_MB=$BURST_MIN_AVAILABLE_MB
Environment=DOCKER_CONFIG=$DOCKER_CONFIG_DIR
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/srv/admira/tenants /srv/admira/shared /run/admira-runtime-broker /var/run/docker.sock
CapabilityBoundingSet=
RestrictSUIDSGID=true
RestrictRealtime=true
LockPersonality=true

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable admira-runtime-broker.service
# Always reload the versioned Python module after a release copy. An
# enable-and-start operation alone leaves an already-running broker on its
# former in-memory code.
systemctl restart admira-runtime-broker.service
systemctl is-active --quiet admira-runtime-broker.service
printf '%s\n' 'Admira runtime broker installed and active.'
