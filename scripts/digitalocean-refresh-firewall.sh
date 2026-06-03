#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${META_ADS_ENV_FILE:-$ROOT_DIR/.env}"

read_env_value() {
  local key="$1"
  [ -f "$ENV_FILE" ] || return 0
  awk -F= -v wanted="$key" '
    $0 !~ /^[[:space:]]*#/ && $1 == wanted {
      print substr($0, index($0, "=") + 1)
      exit
    }
  ' "$ENV_FILE"
}

usage() {
  cat <<'USAGE'
Usage:
  ./scripts/digitalocean-refresh-firewall.sh [--ip A.B.C.D] [--quiet]

Required environment or .env values:
  DIGITALOCEAN_TOKEN
  DIGITALOCEAN_FIREWALL_ID

Recommended environment or .env values:
  DIGITALOCEAN_DROPLET_ID
  DASHBOARD_PORT=7871

Optional:
  DO_STRICT_EXTRA_TCP_PORTS=443,8443
  DO_STRICT_ALLOW_SSH_FROM_ANYWHERE=false
  DO_STRICT_ACCESS_GATE_PORT=7870

Run this on the DigitalOcean server after connecting by SSH. When --ip is not
provided, it uses the client IP from SSH_CONNECTION or SSH_CLIENT.
USAGE
}

QUIET=false
REQUESTED_IP=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --ip)
      REQUESTED_IP="${2:-}"
      shift 2
      ;;
    --quiet)
      QUIET=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      usage
      exit 2
      ;;
  esac
done

DIGITALOCEAN_TOKEN="${DIGITALOCEAN_TOKEN:-$(read_env_value DIGITALOCEAN_TOKEN)}"
DIGITALOCEAN_FIREWALL_ID="${DIGITALOCEAN_FIREWALL_ID:-$(read_env_value DIGITALOCEAN_FIREWALL_ID)}"
DIGITALOCEAN_DROPLET_ID="${DIGITALOCEAN_DROPLET_ID:-$(read_env_value DIGITALOCEAN_DROPLET_ID)}"
DASHBOARD_PORT="${DASHBOARD_PORT:-$(read_env_value DASHBOARD_PORT)}"
DASHBOARD_PORT="${DASHBOARD_PORT:-7871}"
DO_STRICT_EXTRA_TCP_PORTS="${DO_STRICT_EXTRA_TCP_PORTS:-$(read_env_value DO_STRICT_EXTRA_TCP_PORTS)}"
DO_STRICT_ALLOW_SSH_FROM_ANYWHERE="${DO_STRICT_ALLOW_SSH_FROM_ANYWHERE:-$(read_env_value DO_STRICT_ALLOW_SSH_FROM_ANYWHERE)}"
DO_STRICT_ALLOW_SSH_FROM_ANYWHERE="${DO_STRICT_ALLOW_SSH_FROM_ANYWHERE:-false}"
DO_STRICT_ACCESS_GATE_PORT="${DO_STRICT_ACCESS_GATE_PORT:-$(read_env_value DO_STRICT_ACCESS_GATE_PORT)}"

if [ -z "${DIGITALOCEAN_TOKEN:-}" ] || [ -z "${DIGITALOCEAN_FIREWALL_ID:-}" ]; then
  echo "Missing DIGITALOCEAN_TOKEN or DIGITALOCEAN_FIREWALL_ID."
  exit 1
fi

detect_client_ip() {
  if [ -n "$REQUESTED_IP" ]; then
    printf '%s' "$REQUESTED_IP"
    return 0
  fi
  if [ -n "${SSH_CONNECTION:-}" ]; then
    printf '%s' "$SSH_CONNECTION" | awk '{print $1}'
    return 0
  fi
  if [ -n "${SSH_CLIENT:-}" ]; then
    printf '%s' "$SSH_CLIENT" | awk '{print $1}'
    return 0
  fi
  return 1
}

CLIENT_IP="$(detect_client_ip || true)"
if [ -z "$CLIENT_IP" ]; then
  echo "Could not detect the SSH client IP. Run again with --ip A.B.C.D."
  exit 1
fi

export DIGITALOCEAN_TOKEN
export DIGITALOCEAN_FIREWALL_ID
export DIGITALOCEAN_DROPLET_ID
export DASHBOARD_PORT
export DO_STRICT_EXTRA_TCP_PORTS
export DO_STRICT_ALLOW_SSH_FROM_ANYWHERE
export DO_STRICT_ACCESS_GATE_PORT
export CLIENT_IP

python3 - <<'PY'
import ipaddress
import json
import os
import sys
import urllib.error
import urllib.request

token = os.environ["DIGITALOCEAN_TOKEN"]
firewall_id = os.environ["DIGITALOCEAN_FIREWALL_ID"]
dashboard_port = os.environ.get("DASHBOARD_PORT", "7871").strip() or "7871"
droplet_id = os.environ.get("DIGITALOCEAN_DROPLET_ID", "").strip()
extra_ports = [port.strip() for port in os.environ.get("DO_STRICT_EXTRA_TCP_PORTS", "").split(",") if port.strip()]
allow_ssh_anywhere = os.environ.get("DO_STRICT_ALLOW_SSH_FROM_ANYWHERE", "false").strip().lower() == "true"
access_gate_port = os.environ.get("DO_STRICT_ACCESS_GATE_PORT", "").strip()
client_ip = os.environ["CLIENT_IP"].strip()

try:
    ip = ipaddress.ip_address(client_ip)
except ValueError:
    raise SystemExit(f"Invalid client IP: {client_ip}")

if ip.version != 4:
    raise SystemExit("Strict DigitalOcean mode currently expects an IPv4 client address.")

client_cidr = f"{ip}/32"
base_url = "https://api.digitalocean.com/v2"
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
}

def request(method, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"DigitalOcean API error {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not contact DigitalOcean API: {exc}")

current = request("GET", f"/firewalls/{firewall_id}").get("firewall", {})
if not current:
    raise SystemExit("DigitalOcean firewall not found.")

ssh_sources = {"addresses": ["0.0.0.0/0", "::/0"]} if allow_ssh_anywhere else {"addresses": [client_cidr]}
inbound_rules = [
    {"protocol": "tcp", "ports": "22", "sources": ssh_sources},
    {"protocol": "tcp", "ports": dashboard_port, "sources": {"addresses": [client_cidr]}},
]
if access_gate_port:
    inbound_rules.append({"protocol": "tcp", "ports": access_gate_port, "sources": {"addresses": ["0.0.0.0/0", "::/0"]}})
for port in extra_ports:
    inbound_rules.append({"protocol": "tcp", "ports": port, "sources": {"addresses": [client_cidr]}})

outbound_rules = current.get("outbound_rules") or [
    {"protocol": "tcp", "ports": "0", "destinations": {"addresses": ["0.0.0.0/0", "::/0"]}},
    {"protocol": "udp", "ports": "0", "destinations": {"addresses": ["0.0.0.0/0", "::/0"]}},
    {"protocol": "icmp", "ports": "0", "destinations": {"addresses": ["0.0.0.0/0", "::/0"]}},
]

droplet_ids = current.get("droplet_ids") or []
if droplet_id:
    try:
        droplet_ids = [int(droplet_id)]
    except ValueError:
        raise SystemExit("DIGITALOCEAN_DROPLET_ID must be numeric.")

payload = {
    "name": current.get("name") or "meta-ads-agent-strict-access",
    "inbound_rules": inbound_rules,
    "outbound_rules": outbound_rules,
    "droplet_ids": droplet_ids,
    "tags": current.get("tags") or [],
}
request("PUT", f"/firewalls/{firewall_id}", payload)
print(json.dumps({"ok": True, "allowed_ip": client_cidr, "dashboard_port": dashboard_port, "firewall_id": firewall_id}, indent=2))
PY

if [ "$QUIET" != "true" ]; then
  echo
  echo "DigitalOcean firewall refreshed."
  echo "Allowed IP: $CLIENT_IP/32"
  echo "Dashboard port: $DASHBOARD_PORT"
fi
