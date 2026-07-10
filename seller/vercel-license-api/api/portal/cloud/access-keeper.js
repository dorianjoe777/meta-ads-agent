const POSIX_INSTALLER = `#!/usr/bin/env bash
set -euo pipefail

HOST=""
SSH_USER="root"
SSH_PORT="22"
IDENTITY_FILE="$HOME/.ssh/admira_ia"
LEGACY_IDENTITY_FILE="$HOME/.ssh/admi""ro_ai"
INTERVAL_MINUTES="60"
RUN_NOW="false"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --host)
      HOST="$2"
      shift 2
      ;;
    --user)
      SSH_USER="$2"
      shift 2
      ;;
    --port)
      SSH_PORT="$2"
      shift 2
      ;;
    --identity)
      IDENTITY_FILE="$2"
      shift 2
      ;;
    --interval-minutes)
      INTERVAL_MINUTES="$2"
      shift 2
      ;;
    --run-now)
      RUN_NOW="true"
      shift
      ;;
    -h|--help)
      echo "Usage: install --host DROPLET_IP [--identity ~/.ssh/admira_ia] [--run-now]"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 2
      ;;
  esac
done

if [ "$IDENTITY_FILE" = "$HOME/.ssh/admira_ia" ] && [ ! -f "$IDENTITY_FILE" ] && [ -f "$LEGACY_IDENTITY_FILE" ]; then
  IDENTITY_FILE="$LEGACY_IDENTITY_FILE"
fi

if [ -z "$HOST" ]; then
  echo "Missing --host DROPLET_IP"
  exit 2
fi
if ! printf '%s' "$HOST" | grep -Eq '^[A-Za-z0-9.-]+$'; then
  echo "Invalid host."
  exit 2
fi
if ! printf '%s' "$SSH_PORT" | grep -Eq '^[0-9]{1,5}$'; then
  echo "Invalid SSH port."
  exit 2
fi
if ! printf '%s' "$INTERVAL_MINUTES" | grep -Eq '^[0-9]{1,4}$'; then
  echo "Invalid interval."
  exit 2
fi

CONFIG_DIR="$HOME/.meta-ads-agent"
BIN_DIR="$HOME/.local/bin"
LOG_DIR="$CONFIG_DIR/logs"
CONFIG_FILE="$CONFIG_DIR/cloud-access-keeper.env"
STATE_FILE="$CONFIG_DIR/cloud-access-keeper.state"
LOG_FILE="$LOG_DIR/cloud-access-keeper.log"
BIN_FILE="$BIN_DIR/admira-cloud-access-keeper"

mkdir -p "$CONFIG_DIR" "$BIN_DIR" "$LOG_DIR"
chmod 700 "$CONFIG_DIR" "$LOG_DIR"

quote_value() {
  printf "%s" "$1" | sed "s/'/'\\\\''/g; s/^/'/; s/$/'/"
}

cat > "$BIN_FILE" <<'KEEPER'
#!/usr/bin/env bash
set -eo pipefail

CONFIG_FILE="$HOME/.meta-ads-agent/cloud-access-keeper.env"
[ -f "$CONFIG_FILE" ] || { echo "Missing config: $CONFIG_FILE"; exit 1; }
set -a
. "$CONFIG_FILE"
set +a

mkdir -p "$(dirname "$LOG_FILE")"

log() {
  printf '%s %s\\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >> "$LOG_FILE"
}

current_ip() {
  curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null ||
  curl -fsS --max-time 10 https://checkip.amazonaws.com 2>/dev/null ||
  curl -fsS --max-time 10 https://ifconfig.me/ip 2>/dev/null
}

valid_ipv4() {
  printf '%s' "$1" | grep -Eq '^([0-9]{1,3}\\.){3}[0-9]{1,3}$'
}

CURRENT_IP="$(current_ip | tr -d '[:space:]' || true)"
if [ -z "$CURRENT_IP" ] || ! valid_ipv4 "$CURRENT_IP"; then
  log "Could not detect public IPv4."
  exit 1
fi

LAST_SUCCESS_IP=""
LAST_SUCCESS_EPOCH="0"
[ -f "$STATE_FILE" ] && . "$STATE_FILE" || true
NOW="$(date +%s)"
if ! printf '%s' "$LAST_SUCCESS_EPOCH" | grep -Eq '^[0-9]+$'; then
  LAST_SUCCESS_EPOCH="0"
fi
AGE="$((NOW - LAST_SUCCESS_EPOCH))"
MAX_AGE_SECONDS="$REFRESH_MAX_AGE_SECONDS"
if [ -z "$MAX_AGE_SECONDS" ]; then
  MAX_AGE_SECONDS="86400"
fi

if [ "$CURRENT_IP" = "$LAST_SUCCESS_IP" ] && [ "$AGE" -lt "$MAX_AGE_SECONDS" ]; then
  log "IP unchanged: $CURRENT_IP"
  exit 0
fi

if [ ! -f "$SSH_IDENTITY_FILE" ]; then
  log "SSH identity file missing: $SSH_IDENTITY_FILE"
  exit 1
fi

if [ -z "$REMOTE_REFRESH_COMMAND" ]; then
  REMOTE_REFRESH_COMMAND="~/.local/bin/meta-ads-refresh-access"
fi
ssh -i "$SSH_IDENTITY_FILE" \\
  -p "$SSH_PORT" \\
  -o BatchMode=yes \\
  -o ConnectTimeout=20 \\
  -o ServerAliveInterval=10 \\
  -o StrictHostKeyChecking=accept-new \\
  "$SSH_USER@$DROPLET_HOST" \\
  "$REMOTE_REFRESH_COMMAND --ip $CURRENT_IP --quiet"

{
  printf 'LAST_SUCCESS_IP=%s\\n' "$CURRENT_IP"
  printf 'LAST_SUCCESS_EPOCH=%s\\n' "$NOW"
} > "$STATE_FILE"
chmod 600 "$STATE_FILE"
log "Dashboard access refreshed for $CURRENT_IP"
KEEPER
chmod 700 "$BIN_FILE"

{
  printf 'DROPLET_HOST=%s\\n' "$(quote_value "$HOST")"
  printf 'SSH_USER=%s\\n' "$(quote_value "$SSH_USER")"
  printf 'SSH_PORT=%s\\n' "$(quote_value "$SSH_PORT")"
  printf 'SSH_IDENTITY_FILE=%s\\n' "$(quote_value "$IDENTITY_FILE")"
  printf 'STATE_FILE=%s\\n' "$(quote_value "$STATE_FILE")"
  printf 'LOG_FILE=%s\\n' "$(quote_value "$LOG_FILE")"
  printf 'REFRESH_MAX_AGE_SECONDS=%s\\n' "$(quote_value "86400")"
  printf 'REMOTE_REFRESH_COMMAND=%s\\n' "$(quote_value "~/.local/bin/meta-ads-refresh-access")"
} > "$CONFIG_FILE"
chmod 600 "$CONFIG_FILE"

install_launchd() {
  local plist_dir="$HOME/Library/LaunchAgents"
  local plist="$plist_dir/lat.uboost.admira-cloud-access-keeper.plist"
  mkdir -p "$plist_dir"
  cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>lat.uboost.admira-cloud-access-keeper</string>
  <key>ProgramArguments</key>
  <array><string>$BIN_FILE</string></array>
  <key>StartInterval</key><integer>$((INTERVAL_MINUTES * 60))</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOG_FILE</string>
  <key>StandardErrorPath</key><string>$LOG_FILE</string>
</dict>
</plist>
PLIST
  launchctl bootout "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$(id -u)" "$plist" >/dev/null 2>&1 || launchctl load "$plist" >/dev/null 2>&1 || true
}

install_systemd_or_cron() {
  if command -v systemctl >/dev/null 2>&1; then
    local user_dir="$HOME/.config/systemd/user"
    mkdir -p "$user_dir"
    cat > "$user_dir/admira-cloud-access-keeper.service" <<SERVICE
[Unit]
Description=Admira IA cloud access keeper

[Service]
Type=oneshot
ExecStart=$BIN_FILE
SERVICE
    local interval_seconds="$((INTERVAL_MINUTES * 60))"
    cat > "$user_dir/admira-cloud-access-keeper.timer" <<TIMER
[Unit]
Description=Run Admira IA cloud access keeper

[Timer]
OnBootSec=2min
OnUnitActiveSec=$interval_seconds
Unit=admira-cloud-access-keeper.service

[Install]
WantedBy=timers.target
TIMER
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    systemctl --user enable --now admira-cloud-access-keeper.timer >/dev/null 2>&1 && return 0
  fi
  local cron_schedule="*/$INTERVAL_MINUTES * * * *"
  if [ "$INTERVAL_MINUTES" -ge 60 ]; then
    local cron_hours="$((INTERVAL_MINUTES / 60))"
    [ "$cron_hours" -lt 1 ] && cron_hours="1"
    cron_schedule="0 */$cron_hours * * *"
  fi
  local cron_line="$cron_schedule $BIN_FILE >/dev/null 2>&1"
  (crontab -l 2>/dev/null | grep -v 'admira-cloud-access-keeper'; echo "$cron_line") | crontab -
}

case "$(uname -s)" in
  Darwin) install_launchd ;;
  *) install_systemd_or_cron ;;
esac

if [ "$RUN_NOW" = "true" ]; then
  "$BIN_FILE" || true
fi

echo "Admira IA access keeper installed."
echo "It will check this computer public IP every $INTERVAL_MINUTES minutes."
echo "Log: $LOG_FILE"
`;

export default function handler(request, response) {
  response.setHeader("Content-Type", "text/plain; charset=utf-8");
  response.setHeader("Cache-Control", "public, max-age=300");
  return response.status(200).send(POSIX_INSTALLER);
}
