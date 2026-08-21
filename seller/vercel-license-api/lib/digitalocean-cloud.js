import { randomBytes } from "node:crypto";

export const DIGITALOCEAN_REGIONS = [
  { id: "nyc3", label: "Nueva York", note: "Buena opcion general para America Latina." },
  { id: "sfo3", label: "San Francisco", note: "Buena si el comprador esta cerca de la costa oeste." },
  { id: "tor1", label: "Toronto", note: "Alternativa estable para norte/centro America." },
  { id: "ams3", label: "Amsterdam", note: "Para compradores o cuentas en Europa." }
];

export const DIGITALOCEAN_SIZES = [
  { id: "s-1vcpu-1gb", label: "Minimo viable - 1GB RAM", note: "Adecuado para Telegram, dashboard y uso ligero; las tareas creativas intensivas pueden requerir mas memoria." },
  { id: "s-1vcpu-2gb", label: "Trabajo diario recomendado", note: "Mas margen para sesiones largas, reportes y generacion frecuente de creativos." },
  { id: "s-2vcpu-2gb", label: "Trabajo diario comodo", note: "Buen margen para varias cuentas y creativos frecuentes." },
  { id: "s-2vcpu-4gb", label: "Agencia / creativos intensivos", note: "Mejor si usara varias cuentas, imagenes, videos o revisiones creativas con frecuencia." }
];

const SSH_PREFIXES = [
  "ssh-ed25519",
  "ssh-rsa",
  "ecdsa-sha2-nistp256",
  "ecdsa-sha2-nistp384",
  "ecdsa-sha2-nistp521"
];

export function validateDigitalOceanToken(token = "") {
  const value = String(token || "").trim();
  return value.length >= 40 && value.length <= 256 && /^[A-Za-z0-9_.:-]+$/.test(value);
}

export function validateSshPublicKey(key = "") {
  const value = String(key || "").trim();
  if (value.length < 80 || value.length > 8192 || value.includes("\n") || value.includes("\r")) {
    return false;
  }
  const [prefix, body] = value.split(/\s+/, 2);
  if (!SSH_PREFIXES.includes(prefix) || !body) {
    return false;
  }
  return /^[A-Za-z0-9+/=]+$/.test(body);
}

function cloudGateIp(cloud = {}) {
  const candidates = [
    cloud.droplet_ip,
    cloud.dashboard_http_url,
    cloud.dashboard_url,
    cloud.cloud_open_url
  ];
  for (const candidate of candidates) {
    const raw = String(candidate || "").trim();
    if (!raw) continue;
    try {
      const hostname = new URL(raw.includes("://") ? raw : `http://${raw}`).hostname;
      if (/^(?:\d{1,3}\.){3}\d{1,3}$/.test(hostname)) {
        const parts = hostname.split(".").map(Number);
        if (parts.length === 4 && parts.every((part) => Number.isInteger(part) && part >= 0 && part <= 255)) {
          return hostname;
        }
      }
    } catch {
      // Ignore malformed legacy URLs and try the next stored candidate.
    }
  }
  return "";
}

function cloudGateSecret(cloud = {}) {
  if (cloud.cloud_access_secret) return String(cloud.cloud_access_secret).trim();
  try {
    const parsed = new URL(String(cloud.cloud_open_url || ""));
    return decodeURIComponent(parsed.pathname.replace(/^\/open\//, "")).trim();
  } catch {
    return "";
  }
}

function cloudGatePort(value = "7870") {
  const port = String(value || "7870").trim();
  return /^\d{2,5}$/.test(port) ? port : "7870";
}

async function cloudGateRequest(cloud = {}, path = "/admin/reset-status", options = {}, dependencies = {}) {
  const ip = cloudGateIp(cloud);
  const secret = cloudGateSecret(cloud);
  if (!ip || !secret) {
    const error = new Error("cloud_clean_reset_unavailable");
    error.code = "cloud_clean_reset_unavailable";
    throw error;
  }
  const fetchImpl = dependencies.fetchImpl || globalThis.fetch;
  if (typeof fetchImpl !== "function") {
    const error = new Error("cloud_clean_reset_fetch_unavailable");
    error.code = "cloud_clean_reset_fetch_unavailable";
    throw error;
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetchImpl(`http://${ip}:${cloudGatePort(cloud.access_gate_port)}${path}`, {
      method: options.method || "GET",
      headers: {
        "Accept": "application/json",
        "X-Admira-Cloud-Secret": secret,
        ...(options.body ? { "Content-Type": "application/json" } : {})
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: controller.signal
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload?.ok === false) {
      const code = response.status === 404 ? "cloud_clean_reset_unavailable" : String(payload?.error || "cloud_clean_reset_failed");
      const error = new Error(code);
      error.code = code;
      error.statusCode = response.status;
      throw error;
    }
    return payload;
  } catch (error) {
    if (error?.name === "AbortError") {
      const timeoutError = new Error("cloud_clean_reset_timeout");
      timeoutError.code = "cloud_clean_reset_timeout";
      throw timeoutError;
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export function cloudCleanResetCapability(cloud = {}) {
  return Boolean(cloudGateIp(cloud) && cloudGateSecret(cloud));
}

export async function requestCloudCleanReset(cloud = {}, dependencies = {}) {
  return cloudGateRequest(cloud, "/admin/reset", {
    method: "POST",
    body: {
      scope: "clean_installation",
      preserve: ["provider_credentials", "chatgpt_connection", "telegram_connection"],
      clear: ["business_state", "facebook_token", "dashboard_password"]
    }
  }, dependencies);
}

export async function cloudCleanResetStatus(cloud = {}, dependencies = {}) {
  return cloudGateRequest(cloud, "/admin/reset-status", { method: "GET" }, dependencies);
}

export function normalizeChoice(value, choices, fallback) {
  const selected = String(value || "").trim().toLowerCase();
  return choices.some((choice) => choice.id === selected) ? selected : fallback;
}

export function currentClientIp(request) {
  const forwarded = String(request.headers["x-forwarded-for"] || "").split(",")[0].trim();
  const direct = String(request.headers["x-real-ip"] || request.socket?.remoteAddress || "").trim();
  const raw = forwarded || direct;
  const match = raw.match(/\b(?:\d{1,3}\.){3}\d{1,3}\b/);
  if (!match) return "";
  const parts = match[0].split(".").map((part) => Number(part));
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) {
    return "";
  }
  return match[0];
}

export function shellQuote(value = "") {
  return `'${String(value).replace(/'/g, `'\\''`)}'`;
}

function cloudEnvSetterSnippet() {
  return `set_env_value() {
  python3 - "$1" "$2" <<'PY'
import sys
from pathlib import Path

path = Path(".env")
key, value = sys.argv[1], sys.argv[2]
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
found = False
for index, line in enumerate(lines):
    if line.startswith(f"{key}="):
        lines[index] = f"{key}={value}"
        found = True
        break
if not found:
    lines.append(f"{key}={value}")
path.write_text("\\n".join(lines).rstrip() + "\\n", encoding="utf-8")
PY
}`;
}

function zipValidationSnippet() {
  return `python3 - "$TMP_DIR/source.zip" <<'PY'
import stat
import sys
import zipfile
from pathlib import PurePosixPath

archive_path = sys.argv[1]
total = 0
with zipfile.ZipFile(archive_path) as archive:
    for member in archive.infolist():
        normalized = member.filename.replace("\\\\", "/")
        parts = PurePosixPath(normalized).parts
        mode = member.external_attr >> 16
        total += int(member.file_size or 0)
        if total > 350 * 1024 * 1024:
            raise SystemExit("Release too large")
        if not normalized or normalized.startswith("/") or normalized.startswith("~") or ".." in parts or stat.S_IFMT(mode) == stat.S_IFLNK:
            raise SystemExit("Unsafe release archive")
PY`;
}

export function buildDigitalOceanCloudInit({
  signedDownloadUrl,
  licenseKey,
  buyerEmail,
  deviceId,
  licenseServerUrl,
  digitalOceanToken,
  firewallId,
  initialClientIp,
  dashboardPort = "7871",
  cloudAccessSecret = "",
  cloudAccessPort = "7870",
  cloudDashboardHostname = ""
}) {
  return `#!/usr/bin/env bash
set -euo pipefail
exec > >(tee -a /var/log/admira-cloud-install.log) 2>&1

export DEBIAN_FRONTEND=noninteractive
SIGNED_RELEASE_URL=${shellQuote(signedDownloadUrl)}
LICENSE_KEY=${shellQuote(licenseKey)}
BUYER_EMAIL=${shellQuote(buyerEmail)}
LICENSE_DEVICE_ID=${shellQuote(deviceId)}
LICENSE_SERVER_URL=${shellQuote(licenseServerUrl)}
DIGITALOCEAN_TOKEN=${shellQuote(digitalOceanToken)}
DIGITALOCEAN_FIREWALL_ID=${shellQuote(firewallId)}
INITIAL_CLIENT_IP=${shellQuote(initialClientIp)}
DASHBOARD_PORT=${shellQuote(String(dashboardPort || "7871"))}
CLOUD_ACCESS_SECRET=${shellQuote(cloudAccessSecret)}
CLOUD_ACCESS_PORT=${shellQuote(String(cloudAccessPort || "7870"))}
CLOUD_DASHBOARD_HOSTNAME=${shellQuote(cloudDashboardHostname)}
CLOUD_DASHBOARD_HTTPS_URL=${cloudDashboardHostname ? shellQuote(`https://${cloudDashboardHostname}`) : "''"}

report_cloud_runtime() {
  local stage="$1"
  local progress="$2"
  local ready="$3"
  local public_ip
  public_ip="$(curl -fsS --max-time 4 http://169.254.169.254/metadata/v1/interfaces/public/0/ipv4/address 2>/dev/null || curl -fsS --max-time 4 https://api.ipify.org 2>/dev/null || true)"
  [ -n "$public_ip" ] || return 0
  python3 - "$LICENSE_SERVER_URL" "$LICENSE_KEY" "$BUYER_EMAIL" "$CLOUD_ACCESS_SECRET" "$public_ip" "$DASHBOARD_PORT" "$stage" "$progress" "$ready" "$CLOUD_DASHBOARD_HOSTNAME" "$CLOUD_DASHBOARD_HTTPS_URL" <<'PY'
import json
import sys
import urllib.request

base, license_key, buyer_email, secret, ip, dashboard_port, stage, progress, ready, hostname, https_url = sys.argv[1:12]
payload = {
    "action": "runtime_report",
    "license_key": license_key,
    "buyer_email": buyer_email,
    "cloud_access_secret": secret,
    "droplet_ip": ip,
    "dashboard_port": dashboard_port,
    "stage": stage,
    "progress": int(progress or "0"),
    "ready": ready.lower() == "true",
    "cloud_dashboard_hostname": hostname,
    "dashboard_https_url": https_url,
}
request = urllib.request.Request(
    base.rstrip("/") + "/api/portal/cloud/digitalocean",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json", "Accept": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=8) as response:
        response.read()
except Exception:
    pass
PY
}

echo "ADMIRA_STAGE bootstrap"
install_cloud_status_gate_early() {
  [ -n "$CLOUD_ACCESS_SECRET" ] || return 0
  mkdir -p /opt/admira-cloud-access-gate /etc/admira-cloud-access-gate
  cat > /opt/admira-cloud-access-gate/server.py <<'PY'
#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import subprocess
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

SECRET = os.environ.get("CLOUD_ACCESS_SECRET", "").strip()
PORT = int(os.environ.get("CLOUD_ACCESS_PORT", "7870") or "7870")
DASHBOARD_PORT = os.environ.get("DASHBOARD_PORT", "7871").strip() or "7871"

def dashboard_ready():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{DASHBOARD_PORT}/", timeout=3) as response:
            return 200 <= int(response.status) < 500
    except Exception:
        return False

def install_log_tail():
    try:
        with open("/var/log/admira-cloud-install.log", "r", encoding="utf-8", errors="ignore") as handle:
            lines = handle.readlines()[-24:]
        return "".join(lines)[-2600:]
    except Exception:
        return ""

def stage_from_log(log_tail):
    current_prefix = "ADMIRA_STAGE"
    legacy_prefix = "ADMI" + "RO_STAGE"
    stage_markers = [
        ("verifying_dashboard", "verificando_dashboard", 98),
        ("starting_dashboard", "iniciando_dashboard", 92),
        ("app_installed", "preparando_dashboard", 86),
        ("running_installer", "instalando_dependencias", 72),
        ("unpacked_release", "preparando_archivos", 56),
        ("downloading_release", "descargando_producto", 44),
        ("packages_ready", "paquetes_listos", 34),
        ("package_install", "instalando_paquetes", 24),
        ("bootstrap", "arrancando_servidor", 12),
    ]
    markers = [
        ("Admira IA cloud install complete", "verificando_dashboard", 98),
    ]
    markers.extend((current_prefix + " " + marker, stage, progress) for marker, stage, progress in stage_markers)
    markers.extend((legacy_prefix + " " + marker, stage, progress) for marker, stage, progress in stage_markers)
    for marker, stage, progress in markers:
        if marker in log_tail:
            return stage, progress
    return "arrancando_servidor", 8

def docker_snapshot():
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}|{{.Status}}|{{.Ports}}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=4,
        )
        return [line for line in result.stdout.splitlines()[-8:] if line.strip()]
    except Exception:
        return []

def docker_logs_tail():
    try:
        names = docker_snapshot()
        container = ""
        for line in names:
            candidate = line.split("|", 1)[0].strip()
            if candidate:
                container = candidate
                break
        if not container:
            return ""
        result = subprocess.run(
            ["docker", "logs", "--tail", "80", container],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return (result.stdout + result.stderr)[-5000:]
    except Exception:
        return ""

def status_payload():
    ready = dashboard_ready()
    log_tail = install_log_tail()
    stage, progress = stage_from_log(log_tail)
    if ready:
        stage, progress = "dashboard_ready", 100
    return {
        "ok": True,
        "ready": ready,
        "stage": stage,
        "progress": progress,
        "dashboard_port": DASHBOARD_PORT,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "docker_ps": docker_snapshot(),
        "docker_logs_tail": docker_logs_tail(),
        "log_tail": log_tail,
    }

class Handler(BaseHTTPRequestHandler):
    server_version = "AdmiraCloudAccessGate/1.0"

    def log_message(self, fmt, *args):
        return

    def send_json(self, code, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_text(self, code, body):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/health":
            self.send_text(200, "ok")
            return
        prefix = "/status/"
        supplied = urllib.parse.unquote(parsed.path[len(prefix):]) if parsed.path.startswith(prefix) else ""
        if supplied and SECRET and supplied == SECRET:
            self.send_json(200, status_payload())
            return
        if parsed.path.startswith("/open/"):
            self.send_text(503, "<h1>Dashboard preparandose</h1><p>DigitalOcean ya creo el servidor, pero Admira IA todavia se esta instalando. Vuelve a intentar en unos minutos.</p>")
            return
        self.send_json(404, {"ok": False, "ready": False, "stage": "not_found", "progress": 0})

if __name__ == "__main__":
    if not SECRET:
        raise SystemExit("CLOUD_ACCESS_SECRET is required")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
PY
  chmod 700 /opt/admira-cloud-access-gate/server.py
  cat > /etc/admira-cloud-access-gate/env <<EOF
CLOUD_ACCESS_SECRET=$CLOUD_ACCESS_SECRET
CLOUD_ACCESS_PORT=$CLOUD_ACCESS_PORT
DASHBOARD_PORT=$DASHBOARD_PORT
EOF
  chmod 600 /etc/admira-cloud-access-gate/env
  cat > /etc/systemd/system/admira-cloud-access-gate.service <<'SERVICE'
[Unit]
Description=Admira IA dashboard access gate
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/admira-cloud-access-gate/env
ExecStart=/usr/bin/python3 /opt/admira-cloud-access-gate/server.py
Restart=always
RestartSec=5
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=read-only
PrivateTmp=true

[Install]
WantedBy=multi-user.target
SERVICE
  systemctl daemon-reload
  systemctl enable --now admira-cloud-access-gate.service || true
}
install_cloud_status_gate_early

mkdir -p /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/99-admira-key-only.conf <<'SSHCONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
SSHCONF
systemctl restart ssh || systemctl restart sshd || true

echo "ADMIRA_STAGE package_install"
apt-get update
apt-get install -y ca-certificates curl unzip rsync python3 gnupg
install_docker_runtime() {
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \${VERSION_CODENAME:-noble} stable" > /etc/apt/sources.list.d/docker.list
  apt-get update
  if apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin; then
    return 0
  fi
  echo "ADMIRA_STAGE docker_official_repo_fallback"
  apt-get install -y docker.io
  mkdir -p /usr/local/lib/docker/cli-plugins
  case "$(uname -m)" in
    x86_64|amd64) compose_arch="x86_64" ;;
    aarch64|arm64) compose_arch="aarch64" ;;
    *) compose_arch="x86_64" ;;
  esac
  curl -fL --retry 4 "https://github.com/docker/compose/releases/download/v2.36.2/docker-compose-linux-$compose_arch" -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
}
install_docker_runtime
docker --version
docker compose version
systemctl enable --now docker || true
echo "ADMIRA_STAGE packages_ready"
report_cloud_runtime "paquetes_listos" "34" "false" || true

TMP_DIR="$(mktemp -d)"
INSTALL_DIR="/opt/meta-ads-agent"
mkdir -p "$TMP_DIR/unpack" "$INSTALL_DIR"
echo "ADMIRA_STAGE downloading_release"
curl -fL --retry 6 --connect-timeout 20 "$SIGNED_RELEASE_URL" -o "$TMP_DIR/source.zip"
${zipValidationSnippet()}
unzip -q "$TMP_DIR/source.zip" -d "$TMP_DIR/unpack"
echo "ADMIRA_STAGE unpacked_release"
report_cloud_runtime "preparando_archivos" "56" "false" || true
rsync -a "$TMP_DIR/unpack/" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/scripts/"*.sh 2>/dev/null || true

cd "$INSTALL_DIR"
echo "ADMIRA_STAGE running_installer"
./scripts/install-local.sh
echo "ADMIRA_STAGE app_installed"
${cloudEnvSetterSnippet()}
set_env_value LICENSE_KEY "$LICENSE_KEY"
set_env_value LICENSE_BUYER_EMAIL "$BUYER_EMAIL"
set_env_value LICENSE_DEVICE_ID "$LICENSE_DEVICE_ID"
set_env_value LICENSE_SERVER_URL "$LICENSE_SERVER_URL"
set_env_value DASHBOARD_PORT "$DASHBOARD_PORT"
set_env_value DIGITALOCEAN_TOKEN "$DIGITALOCEAN_TOKEN"
set_env_value DIGITALOCEAN_FIREWALL_ID "$DIGITALOCEAN_FIREWALL_ID"
set_env_value DO_STRICT_ALLOW_SSH_FROM_ANYWHERE "true"
set_env_value DO_STRICT_ACCESS_GATE_PORT "$CLOUD_ACCESS_PORT"
set_env_value CLOUD_ACCESS_SECRET "$CLOUD_ACCESS_SECRET"
set_env_value CLOUD_DASHBOARD_HOSTNAME "$CLOUD_DASHBOARD_HOSTNAME"
set_env_value CLOUD_DASHBOARD_HTTPS_URL "$CLOUD_DASHBOARD_HTTPS_URL"

export DIGITALOCEAN_TOKEN DIGITALOCEAN_FIREWALL_ID DASHBOARD_PORT
export DO_STRICT_ACCESS_GATE_PORT="$CLOUD_ACCESS_PORT"
export DO_STRICT_SKIP_DROPLET_ID_PROMPT=true
export DO_STRICT_INITIAL_CLIENT_IP="$INITIAL_CLIENT_IP"
./scripts/install-digitalocean-strict-access.sh || true
install -d -m 0700 /root/.meta-ads-agent /usr/local/bin
cat > /root/.meta-ads-agent/digitalocean-strict-access.env <<EOF
DIGITALOCEAN_TOKEN=$DIGITALOCEAN_TOKEN
DIGITALOCEAN_FIREWALL_ID=$DIGITALOCEAN_FIREWALL_ID
DIGITALOCEAN_DROPLET_ID=
DASHBOARD_PORT=$DASHBOARD_PORT
DO_STRICT_EXTRA_TCP_PORTS=443
DO_STRICT_PUBLIC_TCP_PORTS=80
DO_STRICT_ALLOW_SSH_FROM_ANYWHERE=true
DO_STRICT_ACCESS_GATE_PORT=$CLOUD_ACCESS_PORT
EOF
chmod 0600 /root/.meta-ads-agent/digitalocean-strict-access.env
cat > /usr/local/bin/meta-ads-refresh-access <<'SH'
#!/usr/bin/env bash
set -euo pipefail
set -a
. /root/.meta-ads-agent/digitalocean-strict-access.env
set +a
exec /usr/bin/env bash /opt/meta-ads-agent/scripts/digitalocean-refresh-firewall.sh "$@"
SH
chmod 0700 /usr/local/bin/meta-ads-refresh-access
cat > /usr/local/bin/admira-cloud-clean-reset <<'SH'
#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  exit 2
fi
JOB_ID="$1"
STATE_DIR="/var/lib/admira-cloud-access-gate"
STATE_FILE="$STATE_DIR/reset-state.json"
INSTALL_DIR="/opt/meta-ads-agent"
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
        handle.write("\\n")
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
  if [ -f "$HOST_ENV_BACKUP" ]; then
    cp -p "$HOST_ENV_BACKUP" "$ENV_FILE"
  fi
}

on_error() {
  local code="$1"
  trap - ERR
  restore_host_env || true
  if [ -d "$INSTALL_DIR" ]; then
    cd "$INSTALL_DIR" || true
    docker compose up -d --force-recreate >/dev/null 2>&1 || true
  fi
  set_state "failed" "No pude completar la limpieza de la instalacion cloud."
  exit "$code"
}
trap 'on_error $?' ERR

cleanup() {
  /bin/rm -rf "$BACKUP_DIR"
}
trap cleanup EXIT

set_state "running" "Limpiando el estado de prueba y conservando las conexiones autorizadas…"
if [ ! -d "$INSTALL_DIR" ] || [ ! -f "$ENV_FILE" ]; then
  set_state "failed" "No encontre la instalacion cloud en el servidor."
  exit 1
fi
cp -p "$ENV_FILE" "$HOST_ENV_BACKUP"

cd "$INSTALL_DIR"
docker compose down --remove-orphans

/usr/bin/python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
clear_keys = {
    "DASHBOARD_PASSWORD",
    "DASHBOARD_PASSWORD_HASH",
    "DASHBOARD_TOKEN",
    "META_AD_ACCOUNT_ID",
    "META_ACCESS_TOKEN",
    "META_ACCESS_TOKEN_KIND",
    "META_ACCESS_TOKEN_SAVED_AT",
    "META_PUBLISHING_ACCESS_TOKEN",
    "META_PUBLISHING_TOKEN_SAVED_AT",
    "SHOPIFY_SHOP_DOMAIN",
    "SHOPIFY_ADMIN_API_TOKEN",
    "TELEGRAM_AGENT_ENABLED",
    "TELEGRAM_CHAT_ID",
    "DAILY_SOCIAL_CONTENT_ENABLED",
    "DAILY_SOCIAL_CONTENT_DECISION",
    "DAILY_SOCIAL_CONTENT_TIME",
    "DAILY_SOCIAL_CONTENT_POSTS_PER_DAY",
    "DAILY_SOCIAL_CONTENT_INTERVAL_DAYS",
    "DAILY_SOCIAL_CONTENT_FORMATS",
    "DAILY_SOCIAL_CONTENT_VIDEO_INTERVAL_DAYS",
}
lines = []
seen = set()
for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
    if "=" in line and not line.lstrip().startswith("#"):
        key = line.split("=", 1)[0].strip()
        if key in clear_keys:
            lines.append(f"{key}=")
            seen.add(key)
            continue
    lines.append(line)
for key in sorted(clear_keys - seen):
    lines.append(f"{key}=")
path.write_text("\\n".join(lines).rstrip() + "\\n", encoding="utf-8")
path.chmod(0o600)
PY

docker compose run --rm --no-deps -T --entrypoint python3 meta-ads-agent - "$RUNTIME_ENV_BACKUP" <<'PY'
import json
from pathlib import Path
import shutil
import sys

backup_name = sys.argv[1]
runtime = Path("/app/runtime")
runtime_env = runtime / ".env"
runtime_backup = runtime / backup_name
if runtime_env.exists():
    shutil.copy2(runtime_env, runtime_backup)
    runtime_backup.chmod(0o600)
clear_keys = {
    "DASHBOARD_PASSWORD",
    "DASHBOARD_PASSWORD_HASH",
    "DASHBOARD_TOKEN",
    "META_AD_ACCOUNT_ID",
    "META_ACCESS_TOKEN",
    "META_ACCESS_TOKEN_KIND",
    "META_ACCESS_TOKEN_SAVED_AT",
    "META_PUBLISHING_ACCESS_TOKEN",
    "META_PUBLISHING_TOKEN_SAVED_AT",
    "SHOPIFY_SHOP_DOMAIN",
    "SHOPIFY_ADMIN_API_TOKEN",
    "TELEGRAM_AGENT_ENABLED",
    "TELEGRAM_CHAT_ID",
    "DAILY_SOCIAL_CONTENT_ENABLED",
    "DAILY_SOCIAL_CONTENT_DECISION",
    "DAILY_SOCIAL_CONTENT_TIME",
    "DAILY_SOCIAL_CONTENT_POSTS_PER_DAY",
    "DAILY_SOCIAL_CONTENT_INTERVAL_DAYS",
    "DAILY_SOCIAL_CONTENT_FORMATS",
    "DAILY_SOCIAL_CONTENT_VIDEO_INTERVAL_DAYS",
}
if runtime_env.exists():
    lines = []
    seen = set()
    for line in runtime_env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in clear_keys:
                lines.append(f"{key}=")
                seen.add(key)
                continue
        lines.append(line)
    for key in sorted(clear_keys - seen):
        lines.append(f"{key}=")
    runtime_env.write_text("\\n".join(lines).rstrip() + "\\n", encoding="utf-8")
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

# This is a fresh buyer workspace, not a source-code reset. Keep the durable
# license identity and only provider authentication artifacts. Remove all
# mutable Hermes state (memory, sessions, history, personal skills, prompts,
# caches and old workspaces), then recreate the homes empty below. ChatGPT/Codex
# authentication files are retained so image generation does not need reconnecting.
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
    return path.is_file() and (
        path.name in AUTH_FILES
        or (path.suffix.lower() in AUTH_SUFFIXES and any(part in name for part in AUTH_NAME_PARTS))
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
    ad_config.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
else:
    ad_config.write_text("{}\\n", encoding="utf-8")
ad_config.chmod(0o600)
seed = Path("/app/brand_guides_seed")
if seed.exists():
    shutil.copytree(seed, "/app/brand_guides", dirs_exist_ok=True)
PY

docker compose up -d --force-recreate
ready="false"
for attempt in $(seq 1 90); do
  if curl -fsS --max-time 3 "http://127.0.0.1:\${DASHBOARD_PORT:-7871}/" >/dev/null 2>&1; then
    ready="true"
    break
  fi
  sleep 2
done
if [ "$ready" != "true" ]; then
  restore_host_env
  docker compose up -d --force-recreate || true
  set_state "failed" "El dashboard no respondio despues de limpiar la instalacion."
  exit 1
fi

docker compose run --rm --no-deps -T --entrypoint python3 meta-ads-agent - "$RUNTIME_ENV_BACKUP" <<'PY'
from pathlib import Path
import sys

backup = Path("/app/runtime") / sys.argv[1]
if backup.exists():
    backup.unlink()
PY
set_state "complete" "Instalacion base lista. Se conservaron las credenciales autorizadas y la licencia; se borraron memoria, skills personales, sesiones, configuracion de anuncios, Meta y contraseña."
SH
chmod 0700 /usr/local/bin/admira-cloud-clean-reset
install_cloud_access_gate() {
  [ -n "$CLOUD_ACCESS_SECRET" ] || return 0
  mkdir -p /opt/admira-cloud-access-gate /etc/admira-cloud-access-gate
  cat > /opt/admira-cloud-access-gate/server.py <<'PY'
#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import hmac
import ipaddress
import json
import os
import re
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import socket

SECRET = os.environ.get("CLOUD_ACCESS_SECRET", "").strip()
PORT = int(os.environ.get("CLOUD_ACCESS_PORT", "7870") or "7870")
DASHBOARD_PORT = os.environ.get("DASHBOARD_PORT", "7871").strip() or "7871"
REFRESH_COMMAND = os.environ.get("REFRESH_COMMAND", "/usr/local/bin/meta-ads-refresh-access")
RESET_COMMAND = os.environ.get("RESET_COMMAND", "/usr/local/bin/admira-cloud-clean-reset")
STATE_DIR = "/var/lib/admira-cloud-access-gate"
STATE_FILE = f"{STATE_DIR}/state.json"
RESET_STATE_FILE = f"{STATE_DIR}/reset-state.json"

def valid_client_ip(value):
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return ""
    return str(ip) if ip.version == 4 else ""

def redirect_host(raw_host):
    host = str(raw_host or "").split(":", 1)[0].strip().lower()
    if re.fullmatch(r"[a-z0-9.-]{1,253}", host):
        return host
    return "127.0.0.1"

def hostname_resolves(raw_url):
    try:
        parsed = urllib.parse.urlparse(raw_url)
        hostname = (parsed.hostname or "").strip().lower()
        if not hostname:
            return False
        socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
        return True
    except Exception:
        return False

def save_state(payload):
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.chmod(STATE_FILE, 0o600)

def read_reset_state():
    try:
        with open(RESET_STATE_FILE, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {"status": "idle"}
    except (OSError, ValueError):
        return {"status": "idle"}

def write_reset_state(payload):
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    temporary = f"{RESET_STATE_FILE}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.chmod(temporary, 0o600)
    os.replace(temporary, RESET_STATE_FILE)

def admin_secret_is_valid(handler):
    supplied = str(handler.headers.get("X-Admira-Cloud-Secret", "")).strip()
    return bool(SECRET and supplied and hmac.compare_digest(supplied, SECRET))

def start_clean_reset():
    current = read_reset_state()
    if current.get("status") in {"queued", "running"}:
        return current
    job_id = secrets.token_urlsafe(18)
    queued = {
        "ok": True,
        "job_id": job_id,
        "status": "queued",
        "detail": "La limpieza se iniciara en el servidor.",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    write_reset_state(queued)
    try:
        subprocess.Popen(
            [RESET_COMMAND, job_id],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except Exception as exc:
        failed = {**queued, "status": "failed", "detail": "No pude iniciar la limpieza del servidor."}
        write_reset_state(failed)
        print(f"clean reset launch failed: {exc}", flush=True)
        return failed
    return queued

def dashboard_ready():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{DASHBOARD_PORT}/", timeout=3) as response:
            return 200 <= int(response.status) < 500
    except Exception:
        return False

def install_log_tail():
    try:
        with open("/var/log/admira-cloud-install.log", "r", encoding="utf-8", errors="ignore") as handle:
            lines = handle.readlines()[-24:]
        return "".join(lines)[-2600:]
    except Exception:
        return ""

def stage_from_log(log_tail):
    current_prefix = "ADMIRA_STAGE"
    legacy_prefix = "ADMI" + "RO_STAGE"
    stage_markers = [
        ("verifying_dashboard", "verificando_dashboard", 98),
        ("starting_dashboard", "iniciando_dashboard", 92),
        ("app_installed", "preparando_dashboard", 86),
        ("running_installer", "instalando_dependencias", 72),
        ("unpacked_release", "preparando_archivos", 56),
        ("downloading_release", "descargando_producto", 44),
        ("packages_ready", "paquetes_listos", 34),
        ("package_install", "instalando_paquetes", 24),
        ("bootstrap", "arrancando_servidor", 12),
    ]
    markers = [
        ("Admira IA cloud install complete", "verificando_dashboard", 98),
    ]
    markers.extend((current_prefix + " " + marker, stage, progress) for marker, stage, progress in stage_markers)
    markers.extend((legacy_prefix + " " + marker, stage, progress) for marker, stage, progress in stage_markers)
    for marker, stage, progress in markers:
        if marker in log_tail:
            return stage, progress
    return "arrancando_servidor", 8

def docker_snapshot():
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}|{{.Status}}|{{.Ports}}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=4,
        )
        return [line for line in result.stdout.splitlines()[-8:] if line.strip()]
    except Exception:
        return []

def docker_logs_tail():
    try:
        names = docker_snapshot()
        container = ""
        for line in names:
            candidate = line.split("|", 1)[0].strip()
            if candidate:
                container = candidate
                break
        if not container:
            return ""
        result = subprocess.run(
            ["docker", "logs", "--tail", "80", container],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return (result.stdout + result.stderr)[-5000:]
    except Exception:
        return ""

def ensure_refresh_helper_permissions():
    for path in [REFRESH_COMMAND, "/opt/meta-ads-agent/scripts/digitalocean-refresh-firewall.sh"]:
        try:
            if path and os.path.isfile(path):
                current = os.stat(path).st_mode
                if not current & 0o111:
                    os.chmod(path, current | 0o700)
        except Exception as exc:
            print(f"access helper permission repair skipped for {path}: {exc}", flush=True)

def run_refresh_access(client_ip):
    command = [REFRESH_COMMAND, "--ip", client_ip, "--quiet"]
    ensure_refresh_helper_permissions()
    try:
        result = subprocess.run(command, check=False, timeout=75, capture_output=True, text=True)
    except PermissionError:
        result = subprocess.run(["/usr/bin/env", "bash", *command], check=False, timeout=75, capture_output=True, text=True)
    if result.returncode == 126:
        ensure_refresh_helper_permissions()
        result = subprocess.run(["/usr/bin/env", "bash", *command], check=False, timeout=75, capture_output=True, text=True)
    if result.returncode != 0:
        print((result.stdout or "")[-1200:], flush=True)
        print((result.stderr or "")[-1200:], flush=True)
        raise subprocess.CalledProcessError(result.returncode, command, output=result.stdout, stderr=result.stderr)

def status_payload():
    ready = dashboard_ready()
    log_tail = install_log_tail()
    stage, progress = stage_from_log(log_tail)
    if ready:
        stage, progress = "dashboard_ready", 100
    payload = {
        "ok": True,
        "ready": ready,
        "stage": stage,
        "progress": progress,
        "dashboard_port": DASHBOARD_PORT,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "docker_ps": docker_snapshot(),
        "docker_logs_tail": docker_logs_tail(),
        "log_tail": log_tail,
    }
    return payload

class Handler(BaseHTTPRequestHandler):
    server_version = "AdmiraCloudAccessGate/1.0"

    def log_message(self, fmt, *args):
        return

    def send_text(self, code, body):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, code, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/admin/reset":
            self.send_json(404, {"ok": False, "error": "not_found"})
            return
        if not admin_secret_is_valid(self):
            self.send_json(404, {"ok": False, "error": "not_found"})
            return
        payload = start_clean_reset()
        status = 202 if payload.get("status") in {"queued", "running"} else 500
        self.send_json(status, payload)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/health":
            self.send_text(200, "ok")
            return
        if parsed.path == "/admin/reset-status":
            if not admin_secret_is_valid(self):
                self.send_json(404, {"ok": False, "error": "not_found"})
                return
            self.send_json(200, {"ok": True, **read_reset_state()})
            return
        status_prefix = "/status/"
        status_secret = urllib.parse.unquote(parsed.path[len(status_prefix):]) if parsed.path.startswith(status_prefix) else ""
        if status_secret:
            if not SECRET or status_secret != SECRET:
                self.send_json(404, {"ok": False, "ready": False, "stage": "not_found", "progress": 0})
                return
            self.send_json(200, status_payload())
            return
        prefix = "/open/"
        supplied = urllib.parse.unquote(parsed.path[len(prefix):]) if parsed.path.startswith(prefix) else ""
        if not SECRET or supplied != SECRET:
            self.send_text(404, "<h1>No encontrado</h1>")
            return
        client_ip = valid_client_ip(self.client_address[0])
        if not client_ip:
            self.send_text(400, "<h1>No pude detectar tu red</h1><p>Intenta otra vez desde una conexion IPv4.</p>")
            return
        try:
            run_refresh_access(client_ip)
            save_state({"last_ip": client_ip, "last_success_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        except Exception as exc:
            self.send_text(
                503,
                "<h1>No pude preparar el acceso</h1>"
                "<p>El agente sigue encendido, pero no pude autorizar esta red ahora. Intenta de nuevo en un minuto o contacta soporte.</p>"
                f"<small>{html.escape(str(exc))}</small>"
            )
            return
        https_url = os.environ.get("CLOUD_DASHBOARD_HTTPS_URL", "").strip().rstrip("/")
        host = redirect_host(self.headers.get("Host", ""))
        location = f"{https_url}/?cloud_access=ok" if https_url and hostname_resolves(https_url) else f"http://{host}:{DASHBOARD_PORT}/?cloud_access=ok"
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()

if __name__ == "__main__":
    if not SECRET:
        raise SystemExit("CLOUD_ACCESS_SECRET is required")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
PY
  chmod 700 /opt/admira-cloud-access-gate/server.py
  cat > /etc/admira-cloud-access-gate/env <<EOF
CLOUD_ACCESS_SECRET=$CLOUD_ACCESS_SECRET
CLOUD_ACCESS_PORT=$CLOUD_ACCESS_PORT
DASHBOARD_PORT=$DASHBOARD_PORT
CLOUD_DASHBOARD_HTTPS_URL=$CLOUD_DASHBOARD_HTTPS_URL
REFRESH_COMMAND=/usr/local/bin/meta-ads-refresh-access
RESET_COMMAND=/usr/local/bin/admira-cloud-clean-reset
EOF
  chmod 600 /etc/admira-cloud-access-gate/env
  cat > /etc/systemd/system/admira-cloud-access-gate.service <<'SERVICE'
[Unit]
Description=Admira IA dashboard access gate
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/admira-cloud-access-gate/env
ExecStart=/usr/bin/python3 /opt/admira-cloud-access-gate/server.py
Restart=always
RestartSec=5
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=read-only
PrivateTmp=true

[Install]
WantedBy=multi-user.target
SERVICE
  systemctl daemon-reload
  systemctl restart admira-cloud-access-gate.service || systemctl enable --now admira-cloud-access-gate.service || true
}
install_cloud_access_gate

install_caddy_https() {
  [ -n "$CLOUD_DASHBOARD_HOSTNAME" ] || return 0
  echo "ADMIRA_STAGE configuring_https"
  if ! command -v caddy >/dev/null 2>&1; then
    apt-get update || true
    apt-get install -y caddy || {
      echo "ADMIRA_STAGE caddy_install_skipped"
      return 0
    }
  fi
  mkdir -p /etc/caddy
  cat > /etc/caddy/Caddyfile <<EOF
$CLOUD_DASHBOARD_HOSTNAME {
  encode gzip
  reverse_proxy 127.0.0.1:$DASHBOARD_PORT
}
EOF
  systemctl enable --now caddy || true
  systemctl reload caddy || systemctl restart caddy || true
}

echo "ADMIRA_STAGE starting_dashboard"
docker compose up -d --build
install_caddy_https
dashboard_ready=false
for attempt in $(seq 1 30); do
  if curl -fsS --max-time 2 "http://127.0.0.1:$DASHBOARD_PORT/" >/dev/null 2>&1; then
    dashboard_ready=true
    break
  fi
  sleep 2
done
if [ "$dashboard_ready" = "true" ]; then
  report_cloud_runtime "dashboard_ready" "100" "true" || true
  echo "Admira IA cloud install complete. Dashboard port: $DASHBOARD_PORT"
else
  report_cloud_runtime "verificando_dashboard" "98" "false" || true
  echo "ADMIRA_STAGE verifying_dashboard"
fi
rm -rf "$TMP_DIR"
`;
}

export function digitalOceanFirewallPayload({
  name,
  tag,
  clientIp,
  dashboardPort = "7871",
  allowSshFromAnywhere = false,
  accessGatePort = "7870"
}) {
  const clientCidr = `${clientIp}/32`;
  const sshSources = allowSshFromAnywhere ? { addresses: ["0.0.0.0/0", "::/0"] } : { addresses: [clientCidr] };
  return {
    name,
    inbound_rules: [
      { protocol: "tcp", ports: "22", sources: sshSources },
      { protocol: "tcp", ports: String(dashboardPort || "7871"), sources: { addresses: [clientCidr] } },
      { protocol: "tcp", ports: "80", sources: { addresses: ["0.0.0.0/0", "::/0"] } },
      { protocol: "tcp", ports: "443", sources: { addresses: [clientCidr] } },
      { protocol: "tcp", ports: String(accessGatePort || "7870"), sources: { addresses: ["0.0.0.0/0", "::/0"] } }
    ],
    outbound_rules: [
      { protocol: "tcp", ports: "0", destinations: { addresses: ["0.0.0.0/0", "::/0"] } },
      { protocol: "udp", ports: "0", destinations: { addresses: ["0.0.0.0/0", "::/0"] } },
      { protocol: "icmp", ports: "0", destinations: { addresses: ["0.0.0.0/0", "::/0"] } }
    ],
    tags: [tag]
  };
}

export function dropletIpv4(droplet = {}) {
  const networks = droplet.networks?.v4 || [];
  return networks.find((network) => network.type === "public")?.ip_address || "";
}

export function installId() {
  return randomBytes(6).toString("hex");
}

export function cloudAccessSecret() {
  return randomBytes(24).toString("hex");
}

export function publicCloudOptions() {
  return {
    regions: DIGITALOCEAN_REGIONS,
    sizes: DIGITALOCEAN_SIZES,
    default_region: "nyc3",
    default_size: "s-1vcpu-1gb"
  };
}
