#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="$HOME/.meta-ads-agent"
BIN_DIR="$HOME/.local/bin"
CONFIG_FILE="$CONFIG_DIR/digitalocean-strict-access.env"
WRAPPER="$BIN_DIR/meta-ads-refresh-access"
PROFILE_FILE="$HOME/.profile"

read_env_value() {
  local env_file="$1"
  local key="$2"
  [ -f "$env_file" ] || return 0
  awk -F= -v wanted="$key" '
    $0 !~ /^[[:space:]]*#/ && $1 == wanted {
      print substr($0, index($0, "=") + 1)
      exit
    }
  ' "$env_file"
}

DIGITALOCEAN_TOKEN="${DIGITALOCEAN_TOKEN:-$(read_env_value "$ROOT_DIR/.env" DIGITALOCEAN_TOKEN)}"
DIGITALOCEAN_FIREWALL_ID="${DIGITALOCEAN_FIREWALL_ID:-$(read_env_value "$ROOT_DIR/.env" DIGITALOCEAN_FIREWALL_ID)}"
DIGITALOCEAN_DROPLET_ID="${DIGITALOCEAN_DROPLET_ID:-$(read_env_value "$ROOT_DIR/.env" DIGITALOCEAN_DROPLET_ID)}"
DASHBOARD_PORT="${DASHBOARD_PORT:-$(read_env_value "$ROOT_DIR/.env" DASHBOARD_PORT)}"
DASHBOARD_PORT="${DASHBOARD_PORT:-7871}"
DO_STRICT_EXTRA_TCP_PORTS="${DO_STRICT_EXTRA_TCP_PORTS:-$(read_env_value "$ROOT_DIR/.env" DO_STRICT_EXTRA_TCP_PORTS)}"
DO_STRICT_ALLOW_SSH_FROM_ANYWHERE="${DO_STRICT_ALLOW_SSH_FROM_ANYWHERE:-$(read_env_value "$ROOT_DIR/.env" DO_STRICT_ALLOW_SSH_FROM_ANYWHERE)}"
DO_STRICT_ALLOW_SSH_FROM_ANYWHERE="${DO_STRICT_ALLOW_SSH_FROM_ANYWHERE:-false}"
DO_STRICT_ACCESS_GATE_PORT="${DO_STRICT_ACCESS_GATE_PORT:-$(read_env_value "$ROOT_DIR/.env" DO_STRICT_ACCESS_GATE_PORT)}"
DO_STRICT_SKIP_DROPLET_ID_PROMPT="${DO_STRICT_SKIP_DROPLET_ID_PROMPT:-false}"
DO_STRICT_INITIAL_CLIENT_IP="${DO_STRICT_INITIAL_CLIENT_IP:-}"

if [ -z "${DIGITALOCEAN_TOKEN:-}" ]; then
  printf "DigitalOcean API token: "
  IFS= read -r DIGITALOCEAN_TOKEN
fi
if [ -z "${DIGITALOCEAN_FIREWALL_ID:-}" ]; then
  printf "DigitalOcean firewall ID dedicated to Meta Ads Agent: "
  IFS= read -r DIGITALOCEAN_FIREWALL_ID
fi
if [ -z "${DIGITALOCEAN_DROPLET_ID:-}" ] && [ "$DO_STRICT_SKIP_DROPLET_ID_PROMPT" != "true" ]; then
  printf "DigitalOcean droplet ID (recommended): "
  IFS= read -r DIGITALOCEAN_DROPLET_ID
fi

if [ -z "$DIGITALOCEAN_TOKEN" ] || [ -z "$DIGITALOCEAN_FIREWALL_ID" ]; then
  echo "Need DIGITALOCEAN_TOKEN and DIGITALOCEAN_FIREWALL_ID."
  exit 1
fi

mkdir -p "$CONFIG_DIR" "$BIN_DIR"
chmod 700 "$CONFIG_DIR"

umask 077
{
  printf 'DIGITALOCEAN_TOKEN=%s\n' "$DIGITALOCEAN_TOKEN"
  printf 'DIGITALOCEAN_FIREWALL_ID=%s\n' "$DIGITALOCEAN_FIREWALL_ID"
  printf 'DIGITALOCEAN_DROPLET_ID=%s\n' "$DIGITALOCEAN_DROPLET_ID"
  printf 'DASHBOARD_PORT=%s\n' "$DASHBOARD_PORT"
  printf 'DO_STRICT_EXTRA_TCP_PORTS=%s\n' "$DO_STRICT_EXTRA_TCP_PORTS"
  printf 'DO_STRICT_ALLOW_SSH_FROM_ANYWHERE=%s\n' "$DO_STRICT_ALLOW_SSH_FROM_ANYWHERE"
  printf 'DO_STRICT_ACCESS_GATE_PORT=%s\n' "$DO_STRICT_ACCESS_GATE_PORT"
} > "$CONFIG_FILE"
chmod 600 "$CONFIG_FILE"

cat > "$WRAPPER" <<SH
#!/usr/bin/env bash
set -euo pipefail
set -a
. "$CONFIG_FILE"
set +a
exec /usr/bin/env bash "$ROOT_DIR/scripts/digitalocean-refresh-firewall.sh" "\$@"
SH
chmod 700 "$WRAPPER"

PROFILE_MARKER_BEGIN="# meta-ads-agent strict DigitalOcean access begin"
PROFILE_MARKER_END="# meta-ads-agent strict DigitalOcean access end"
if ! grep -Fq "$PROFILE_MARKER_BEGIN" "$PROFILE_FILE" 2>/dev/null; then
  cat >> "$PROFILE_FILE" <<SH

$PROFILE_MARKER_BEGIN
if [ -n "\${SSH_CONNECTION:-}\${SSH_CLIENT:-}" ] && [ -x "$WRAPPER" ]; then
  "$WRAPPER" --quiet >/dev/null 2>&1 || true
fi
$PROFILE_MARKER_END
SH
fi

if [ -n "$DO_STRICT_INITIAL_CLIENT_IP" ]; then
  "$WRAPPER" --ip "$DO_STRICT_INITIAL_CLIENT_IP"
else
  "$WRAPPER"
fi

echo
echo "Strict DigitalOcean access installed."
echo "Manual refresh command:"
echo "$WRAPPER"
