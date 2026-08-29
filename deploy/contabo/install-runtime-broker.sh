#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_USER="${ADMIRA_SERVICE_USER:-admiraops}"
BROKER_GROUP="${ADMIRA_BROKER_GROUP:-admira-broker}"
BROKER_GID="${ADMIRA_BROKER_GID:-19091}"
SPOOL_GROUP="${ADMIRA_SPOOL_GROUP:-admira-spool}"
SPOOL_GID="${ADMIRA_SPOOL_GID:-19092}"
BROKER_KEY_SOURCE="$ROOT_DIR/secrets/runtime_broker_key.txt"
HOSTED_GEMINI_KEY_SOURCE="$ROOT_DIR/secrets/hosted_gemini_api_key.txt"
MAX_ACTIVE_TENANTS="${ADMIRA_MAX_ACTIVE_TENANTS:-}"
if [[ -z "$MAX_ACTIVE_TENANTS" && -r "$ROOT_DIR/.env" ]]; then
  while IFS='=' read -r config_key config_value; do
    if [[ "$config_key" == "ADMIRA_MAX_ACTIVE_TENANTS" ]]; then
      MAX_ACTIVE_TENANTS="$config_value"
    fi
  done < "$ROOT_DIR/.env"
fi
MAX_ACTIVE_TENANTS="${MAX_ACTIVE_TENANTS:-4}"

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
if [[ ! "$MAX_ACTIVE_TENANTS" =~ ^[1-9][0-9]*$ ]] || (( MAX_ACTIVE_TENANTS > 64 )); then
  printf '%s\n' 'ADMIRA_MAX_ACTIVE_TENANTS must be between 1 and 64.' >&2
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
if [[ -s "$HOSTED_GEMINI_KEY_SOURCE" ]]; then
  install -m 0600 -o "$SERVICE_USER" -g "$SERVICE_USER" "$HOSTED_GEMINI_KEY_SOURCE" /etc/admira/hosted-gemini-api-key
else
  # Emptying the control-plane source is an explicit revocation for future
  # tenant provisioning; never leave an older host-funded key installed.
  rm -f /etc/admira/hosted-gemini-api-key
fi

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
# Always reload the versioned Python module after a release copy. `enable
# --now` alone leaves an already-running broker on its former in-memory code.
systemctl restart admira-runtime-broker.service
systemctl is-active --quiet admira-runtime-broker.service
printf '%s\n' 'Admira runtime broker installed and active.'
