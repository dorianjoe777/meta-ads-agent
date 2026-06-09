import { randomBytes } from "node:crypto";

export const DIGITALOCEAN_REGIONS = [
  { id: "nyc3", label: "Nueva York", note: "Buena opcion general para America Latina." },
  { id: "sfo3", label: "San Francisco", note: "Buena si el comprador esta cerca de la costa oeste." },
  { id: "tor1", label: "Toronto", note: "Alternativa estable para norte/centro America." },
  { id: "ams3", label: "Amsterdam", note: "Para compradores o cuentas en Europa." }
];

export const DIGITALOCEAN_SIZES = [
  { id: "s-1vcpu-1gb", label: "Basico recomendado", note: "Suficiente para empezar con Docker y el dashboard." },
  { id: "s-1vcpu-2gb", label: "Mas comodo", note: "Mejor si usara Telegram, creativos y reportes con frecuencia." },
  { id: "s-2vcpu-2gb", label: "Agencia pequena", note: "Mas margen para varias cuentas y trabajo diario." }
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
exec > >(tee -a /var/log/admiro-cloud-install.log) 2>&1

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

echo "ADMIRO_STAGE bootstrap"
install_cloud_status_gate_early() {
  [ -n "$CLOUD_ACCESS_SECRET" ] || return 0
  mkdir -p /opt/admiro-cloud-access-gate /etc/admiro-cloud-access-gate
  cat > /opt/admiro-cloud-access-gate/server.py <<'PY'
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
        with open("/var/log/admiro-cloud-install.log", "r", encoding="utf-8", errors="ignore") as handle:
            lines = handle.readlines()[-24:]
        return "".join(lines)[-2600:]
    except Exception:
        return ""

def stage_from_log(log_tail):
    markers = [
        ("Admiro AI cloud install complete", "verificando_dashboard", 98),
        ("ADMIRO_STAGE verifying_dashboard", "verificando_dashboard", 98),
        ("ADMIRO_STAGE starting_dashboard", "iniciando_dashboard", 92),
        ("ADMIRO_STAGE app_installed", "preparando_dashboard", 86),
        ("ADMIRO_STAGE running_installer", "instalando_dependencias", 72),
        ("ADMIRO_STAGE unpacked_release", "preparando_archivos", 56),
        ("ADMIRO_STAGE downloading_release", "descargando_producto", 44),
        ("ADMIRO_STAGE packages_ready", "paquetes_listos", 34),
        ("ADMIRO_STAGE package_install", "instalando_paquetes", 24),
        ("ADMIRO_STAGE bootstrap", "arrancando_servidor", 12),
    ]
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
    server_version = "AdmiroCloudAccessGate/1.0"

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
            self.send_text(503, "<h1>Dashboard preparandose</h1><p>DigitalOcean ya creo el servidor, pero Admiro AI todavia se esta instalando. Vuelve a intentar en unos minutos.</p>")
            return
        self.send_json(404, {"ok": False, "ready": False, "stage": "not_found", "progress": 0})

if __name__ == "__main__":
    if not SECRET:
        raise SystemExit("CLOUD_ACCESS_SECRET is required")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
PY
  chmod 700 /opt/admiro-cloud-access-gate/server.py
  cat > /etc/admiro-cloud-access-gate/env <<EOF
CLOUD_ACCESS_SECRET=$CLOUD_ACCESS_SECRET
CLOUD_ACCESS_PORT=$CLOUD_ACCESS_PORT
DASHBOARD_PORT=$DASHBOARD_PORT
EOF
  chmod 600 /etc/admiro-cloud-access-gate/env
  cat > /etc/systemd/system/admiro-cloud-access-gate.service <<'SERVICE'
[Unit]
Description=Admiro AI dashboard access gate
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/admiro-cloud-access-gate/env
ExecStart=/usr/bin/python3 /opt/admiro-cloud-access-gate/server.py
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
  systemctl enable --now admiro-cloud-access-gate.service || true
}
install_cloud_status_gate_early

mkdir -p /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/99-admiro-key-only.conf <<'SSHCONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
SSHCONF
systemctl restart ssh || systemctl restart sshd || true

echo "ADMIRO_STAGE package_install"
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
  echo "ADMIRO_STAGE docker_official_repo_fallback"
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
echo "ADMIRO_STAGE packages_ready"
report_cloud_runtime "paquetes_listos" "34" "false" || true

TMP_DIR="$(mktemp -d)"
INSTALL_DIR="/opt/meta-ads-agent"
mkdir -p "$TMP_DIR/unpack" "$INSTALL_DIR"
echo "ADMIRO_STAGE downloading_release"
curl -fL --retry 6 --connect-timeout 20 "$SIGNED_RELEASE_URL" -o "$TMP_DIR/source.zip"
${zipValidationSnippet()}
unzip -q "$TMP_DIR/source.zip" -d "$TMP_DIR/unpack"
echo "ADMIRO_STAGE unpacked_release"
report_cloud_runtime "preparando_archivos" "56" "false" || true
rsync -a "$TMP_DIR/unpack/" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/scripts/"*.sh 2>/dev/null || true

cd "$INSTALL_DIR"
echo "ADMIRO_STAGE running_installer"
./scripts/install-local.sh
echo "ADMIRO_STAGE app_installed"
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
exec /opt/meta-ads-agent/scripts/digitalocean-refresh-firewall.sh "$@"
SH
chmod 0700 /usr/local/bin/meta-ads-refresh-access
install_cloud_access_gate() {
  [ -n "$CLOUD_ACCESS_SECRET" ] || return 0
  mkdir -p /opt/admiro-cloud-access-gate /etc/admiro-cloud-access-gate
  cat > /opt/admiro-cloud-access-gate/server.py <<'PY'
#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import ipaddress
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

SECRET = os.environ.get("CLOUD_ACCESS_SECRET", "").strip()
PORT = int(os.environ.get("CLOUD_ACCESS_PORT", "7870") or "7870")
DASHBOARD_PORT = os.environ.get("DASHBOARD_PORT", "7871").strip() or "7871"
REFRESH_COMMAND = os.environ.get("REFRESH_COMMAND", "/usr/local/bin/meta-ads-refresh-access")
STATE_DIR = "/var/lib/admiro-cloud-access-gate"
STATE_FILE = f"{STATE_DIR}/state.json"

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

def dashboard_ready():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{DASHBOARD_PORT}/", timeout=3) as response:
            return 200 <= int(response.status) < 500
    except Exception:
        return False

def install_log_tail():
    try:
        with open("/var/log/admiro-cloud-install.log", "r", encoding="utf-8", errors="ignore") as handle:
            lines = handle.readlines()[-24:]
        return "".join(lines)[-2600:]
    except Exception:
        return ""

def stage_from_log(log_tail):
    markers = [
        ("Admiro AI cloud install complete", "verificando_dashboard", 98),
        ("ADMIRO_STAGE verifying_dashboard", "verificando_dashboard", 98),
        ("ADMIRO_STAGE starting_dashboard", "iniciando_dashboard", 92),
        ("ADMIRO_STAGE app_installed", "preparando_dashboard", 86),
        ("ADMIRO_STAGE running_installer", "instalando_dependencias", 72),
        ("ADMIRO_STAGE unpacked_release", "preparando_archivos", 56),
        ("ADMIRO_STAGE downloading_release", "descargando_producto", 44),
        ("ADMIRO_STAGE packages_ready", "paquetes_listos", 34),
        ("ADMIRO_STAGE package_install", "instalando_paquetes", 24),
        ("ADMIRO_STAGE bootstrap", "arrancando_servidor", 12),
    ]
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
    server_version = "AdmiroCloudAccessGate/1.0"

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

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/health":
            self.send_text(200, "ok")
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
            subprocess.run([REFRESH_COMMAND, "--ip", client_ip, "--quiet"], check=True, timeout=75)
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
  chmod 700 /opt/admiro-cloud-access-gate/server.py
  cat > /etc/admiro-cloud-access-gate/env <<EOF
CLOUD_ACCESS_SECRET=$CLOUD_ACCESS_SECRET
CLOUD_ACCESS_PORT=$CLOUD_ACCESS_PORT
DASHBOARD_PORT=$DASHBOARD_PORT
CLOUD_DASHBOARD_HTTPS_URL=$CLOUD_DASHBOARD_HTTPS_URL
REFRESH_COMMAND=/usr/local/bin/meta-ads-refresh-access
EOF
  chmod 600 /etc/admiro-cloud-access-gate/env
  cat > /etc/systemd/system/admiro-cloud-access-gate.service <<'SERVICE'
[Unit]
Description=Admiro AI dashboard access gate
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/admiro-cloud-access-gate/env
ExecStart=/usr/bin/python3 /opt/admiro-cloud-access-gate/server.py
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
  systemctl restart admiro-cloud-access-gate.service || systemctl enable --now admiro-cloud-access-gate.service || true
}
install_cloud_access_gate

install_caddy_https() {
  [ -n "$CLOUD_DASHBOARD_HOSTNAME" ] || return 0
  echo "ADMIRO_STAGE configuring_https"
  if ! command -v caddy >/dev/null 2>&1; then
    apt-get update || true
    apt-get install -y caddy || {
      echo "ADMIRO_STAGE caddy_install_skipped"
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

echo "ADMIRO_STAGE starting_dashboard"
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
  echo "Admiro AI cloud install complete. Dashboard port: $DASHBOARD_PORT"
else
  report_cloud_runtime "verificando_dashboard" "98" "false" || true
  echo "ADMIRO_STAGE verifying_dashboard"
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
