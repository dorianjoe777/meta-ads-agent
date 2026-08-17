#!/usr/bin/env bash
set -euo pipefail

# Admira IA macOS cloud installer engine.
# The visible AppKit/AppleScript UI starts this script without opening Terminal.
# It provisions a DigitalOcean Droplet, installs Docker remotely and leaves only
# a browser shortcut on the buyer's Mac.

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

ENGINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLOUD_ASSET_DIR="${ADMIRA_CLOUD_ASSET_DIR:-$ENGINE_DIR/cloud-agent}"

STATE_DIR="$HOME/Library/Application Support/Admira IA/Cloud Installer"
JOBS_DIR="$STATE_DIR/jobs"
KEYS_DIR="$STATE_DIR/keys"
LOG_FILE="$STATE_DIR/install.log"
STATUS_FILE="$STATE_DIR/status.txt"
URL_FILE="$STATE_DIR/dashboard-url.txt"
KEYCHAIN_SERVICE="lat.uboost.admira.cloud-installer"
CONTINUATION_LABEL="lat.uboost.admira.cloud-installer"
INSTALLER_APP="$HOME/Applications/Admira IA Cloud Installer.app"
INSTALLER_MODE="${ADMIRA_INSTALLER_MODE:-gui}"
INSTALLER_COMMAND_FILE="${ADMIRA_INSTALLER_COMMAND_FILE:-}"
DO_API="https://api.digitalocean.com/v2"
LICENSE_SERVER_URL="https://admiraia.uboost.lat"
LICENSE_ENDPOINT="/api/license/release"
CLOUD_INSTALL_ENDPOINT="/api/license/release"
RELEASE_ASSET="MetaAdsAgent-source.zip"
RELEASE_CHANNEL="stable"
DO_TOKEN=""
BUYER_EMAIL=""
LICENSE_KEY=""
DEVICE_ID=""
TRANSFER_DEVICE="false"
DO_SIZE="s-1vcpu-2gb"
DO_REGION="nyc3"
LICENSE_SUFFIX=""
JOB_FILE=""
KEY_PATH=""
SSH_ID=""
SSH_PUBLIC_KEY=""
DROPLET_ID=""
FIREWALL_ID=""
DROPLET_IP=""
INSTANCE_SLUG=""
INSTANCE_PROJECT=""
RELEASE_URL=""
RELEASE_SHA256=""
TMP_DIR=""
API_RESPONSE=""
CLOUD_INSTALL_TOKEN=""
CLOUD_ACCESS_SECRET=""
CLOUD_ACCESS_PORT="7870"

mkdir -p "$STATE_DIR" "$JOBS_DIR" "$KEYS_DIR"
umask 077

log_line() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$LOG_FILE"
}

emit() {
  local stage="$1" percent="$2" message="$3"
  printf 'ADMIRA|%s|%s|%s\n' "$stage" "$percent" "$message"
  printf '%s\n%s\n%s\n%s\n' "$stage" "$percent" "$message" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$STATUS_FILE.tmp"
  mv -f "$STATUS_FILE.tmp" "$STATUS_FILE"
  log_line "$stage: $message"
}

alert() {
  local title="$1" message="$2" style="${3:-warning}"
  /usr/bin/osascript - "$title" "$message" "$style" <<'APPLESCRIPT' >/dev/null 2>&1 || true
on run argv
  set titleText to item 1 of argv
  set messageText to item 2 of argv
  set alertStyle to item 3 of argv
  if alertStyle is "critical" then
    display alert titleText message messageText as critical
  else if alertStyle is "informational" then
    display alert titleText message messageText as informational
  else
    display alert titleText message messageText as warning
  end if
end run
APPLESCRIPT
}

job_get() {
  local key="$1"
  [ -f "$JOB_FILE" ] || return 0
  /usr/bin/awk -F= -v wanted="$key" '$1 == wanted {print substr($0, index($0,"=")+1); exit}' "$JOB_FILE"
}

job_set() {
  local key="$1" value="$2" tmp="$JOB_FILE.tmp"
  mkdir -p "$(dirname "$JOB_FILE")"
  if [ -f "$JOB_FILE" ]; then
    /usr/bin/awk -v key="$key" -v value="$value" '
      BEGIN { updated=0 }
      $0 ~ ("^" key "=") { print key "=" value; updated=1; next }
      { print }
      END { if (!updated) print key "=" value }
    ' "$JOB_FILE" > "$tmp"
  else
    printf '%s=%s\n' "$key" "$value" > "$tmp"
  fi
  mv -f "$tmp" "$JOB_FILE"
}

set_phase() {
  [ -n "$JOB_FILE" ] && job_set phase "$1"
}

cleanup() {
  if [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ]; then
    /bin/rm -rf "$TMP_DIR" 2>/dev/null || true
  fi
}
trap cleanup EXIT

remove_continuation() {
  local plist="$HOME/Library/LaunchAgents/$CONTINUATION_LABEL.plist"
  /bin/launchctl bootout "gui/$(id -u)/$CONTINUATION_LABEL" >/dev/null 2>&1 || true
  [ -f "$plist" ] && /bin/rm -f "$plist"
}

keychain_read() {
  local account="$1"
  /usr/bin/security find-generic-password -a "$account" -s "$KEYCHAIN_SERVICE" -w 2>/dev/null || true
}

keychain_write() {
  local account="$1" value="$2"
  /usr/bin/security add-generic-password -U -a "$account" -s "$KEYCHAIN_SERVICE" -w "$value" "$HOME/Library/Keychains/login.keychain-db" >/dev/null 2>&1 || \
    /usr/bin/security add-generic-password -U -a "$account" -s "$KEYCHAIN_SERVICE" -w "$value" >/dev/null 2>&1 || true
}

keychain_delete() {
  /usr/bin/security delete-generic-password -a "$1" -s "$KEYCHAIN_SERVICE" >/dev/null 2>&1 || true
}

fail() {
  local message="$1"
  set_phase error || true
  emit "error" 100 "$message"
  remove_continuation || true
  keychain_delete do-token
  keychain_delete buyer-email
  keychain_delete license-key
  keychain_delete transfer-device
  keychain_delete do-size
  keychain_delete do-region
  keychain_delete cloud-access-secret
  alert "Admira IA no pudo completar la instalación" "$message Puedes volver a abrir el instalador; el registro está en: $LOG_FILE" warning
  exit 1
}

require_tools() {
  local tool
  for tool in curl ssh scp ssh-keygen shasum unzip security osascript plutil base64; do
    command -v "$tool" >/dev/null 2>&1 || fail "macOS no encontró la herramienta requerida: $tool"
  done
  [ -f "$CLOUD_ASSET_DIR/admira-cloud-access-gate.py" ] || fail "Falta el componente cloud de acceso seguro"
  [ -f "$CLOUD_ASSET_DIR/admira-cloud-clean-reset.sh" ] || fail "Falta el componente cloud de limpieza segura"
}

json_get() {
  local path="$1" key="$2"
  /usr/bin/plutil -extract "$key" raw -o - "$path" 2>/dev/null && return 0
  /usr/bin/osascript -l JavaScript - "$path" "$key" <<'JXA' 2>/dev/null || true
ObjC.import('Foundation');
const args = $.NSProcessInfo.processInfo.arguments;
const path = ObjC.unwrap(args.objectAtIndex(4));
const key = ObjC.unwrap(args.objectAtIndex(5));
const text = ObjC.unwrap($.NSString.stringWithContentsOfFileEncodingError(path, $.NSUTF8StringEncoding, null));
let value = JSON.parse(text);
for (const part of key.split('.')) { value = value === undefined || value === null ? undefined : value[part]; }
if (value === undefined || value === null) { $.exit(2); }
if (typeof value === 'boolean') { console.log(value ? 'true' : 'false'); }
else { console.log(String(value)); }
JXA
}

jxa_json() {
  # On macOS, osascript writes JavaScript's console.log output to stderr.
  # These JSON helpers are consumed through command substitution, so merge
  # stderr into stdout or the caller receives an empty request body and the
  # license endpoint correctly answers `status=invalid`.
  /usr/bin/osascript -l JavaScript 2>&1 <<'JXA'
ObjC.import('Foundation');
const env = $.NSProcessInfo.processInfo.environment;
const value = (name) => {
  const item = env.objectForKey(name);
  return item ? ObjC.unwrap(item) : '';
};
const mode = value('ADMIRA_JSON_MODE');
let output = {};
if (mode === 'license') {
  output = {license_key: value('ADMIRA_JSON_LICENSE'), buyer_email: value('ADMIRA_JSON_EMAIL'), device_id: value('ADMIRA_JSON_DEVICE'), asset_name: value('ADMIRA_JSON_ASSET'), channel: value('ADMIRA_JSON_CHANNEL'), transfer_device: value('ADMIRA_JSON_TRANSFER') === 'true'};
} else if (mode === 'ssh') {
  output = {name: value('ADMIRA_JSON_NAME'), public_key: value('ADMIRA_JSON_PUBLIC_KEY')};
} else if (mode === 'droplet') {
  output = {name: value('ADMIRA_JSON_NAME'), region: value('ADMIRA_JSON_REGION'), size: value('ADMIRA_JSON_SIZE'), image: 'ubuntu-24-04-x64', ssh_keys: [Number(value('ADMIRA_JSON_SSH_ID'))], monitoring: true, tags: ['admira-ia', value('ADMIRA_JSON_TAG')], user_data: value('ADMIRA_JSON_USER_DATA')};
} else if (mode === 'firewall') {
  output = {name: value('ADMIRA_JSON_NAME'), droplet_ids: [Number(value('ADMIRA_JSON_DROPLET_ID'))], inbound_rules: [{protocol: 'tcp', ports: '22', sources: {addresses: ['0.0.0.0/0', '::/0']}}, {protocol: 'tcp', ports: '7870', sources: {addresses: ['0.0.0.0/0', '::/0']}}, {protocol: 'tcp', ports: '7871', sources: {addresses: ['0.0.0.0/0', '::/0']}}], outbound_rules: [{protocol: 'tcp', ports: '1-65535', destinations: {addresses: ['0.0.0.0/0', '::/0']}}, {protocol: 'udp', ports: '1-65535', destinations: {addresses: ['0.0.0.0/0', '::/0']}}, {protocol: 'icmp', destinations: {addresses: ['0.0.0.0/0', '::/0']}}]};
} else if (mode === 'cloud-install') {
  output = {action: 'cloud_install', cloud_install_token: value('ADMIRA_JSON_CLOUD_TOKEN'), license_key: value('ADMIRA_JSON_LICENSE'), buyer_email: value('ADMIRA_JSON_EMAIL'), device_id: value('ADMIRA_JSON_DEVICE'), droplet_id: value('ADMIRA_JSON_DROPLET_ID'), droplet_ip: value('ADMIRA_JSON_DROPLET_IP'), droplet_name: value('ADMIRA_JSON_DROPLET_NAME'), firewall_id: value('ADMIRA_JSON_FIREWALL_ID'), ssh_key_id: value('ADMIRA_JSON_SSH_ID'), region: value('ADMIRA_JSON_REGION'), size: value('ADMIRA_JSON_SIZE'), cloud_access_secret: value('ADMIRA_JSON_CLOUD_SECRET'), access_gate_port: 7870, install_status: value('ADMIRA_JSON_INSTALL_STATUS'), install_progress: Number(value('ADMIRA_JSON_INSTALL_PROGRESS') || '88'),};
}
console.log(JSON.stringify(output));
JXA
}

license_body() {
  ADMIRA_JSON_MODE=license ADMIRA_JSON_LICENSE="$LICENSE_KEY" ADMIRA_JSON_EMAIL="$BUYER_EMAIL" ADMIRA_JSON_DEVICE="$DEVICE_ID" ADMIRA_JSON_ASSET="$RELEASE_ASSET" ADMIRA_JSON_CHANNEL="$RELEASE_CHANNEL" ADMIRA_JSON_TRANSFER="$TRANSFER_DEVICE" jxa_json
}

ssh_body() {
  ADMIRA_JSON_MODE=ssh ADMIRA_JSON_NAME="$1" ADMIRA_JSON_PUBLIC_KEY="$2" jxa_json
}

droplet_body() {
  ADMIRA_JSON_MODE=droplet ADMIRA_JSON_NAME="$1" ADMIRA_JSON_REGION="$2" ADMIRA_JSON_SIZE="$3" ADMIRA_JSON_SSH_ID="$4" ADMIRA_JSON_TAG="$5" ADMIRA_JSON_USER_DATA="$6" jxa_json
}

firewall_body() {
  ADMIRA_JSON_MODE=firewall ADMIRA_JSON_NAME="$1" ADMIRA_JSON_DROPLET_ID="$2" jxa_json
}

cloud_install_body() {
  ADMIRA_JSON_MODE=cloud-install \
  ADMIRA_JSON_CLOUD_TOKEN="$CLOUD_INSTALL_TOKEN" \
  ADMIRA_JSON_LICENSE="$LICENSE_KEY" \
  ADMIRA_JSON_EMAIL="$BUYER_EMAIL" \
  ADMIRA_JSON_DEVICE="$DEVICE_ID" \
  ADMIRA_JSON_DROPLET_ID="$DROPLET_ID" \
  ADMIRA_JSON_DROPLET_IP="$DROPLET_IP" \
  ADMIRA_JSON_DROPLET_NAME="admira-ia-$LICENSE_SUFFIX" \
  ADMIRA_JSON_FIREWALL_ID="$FIREWALL_ID" \
  ADMIRA_JSON_SSH_ID="$SSH_ID" \
  ADMIRA_JSON_REGION="$DO_REGION" \
  ADMIRA_JSON_SIZE="$DO_SIZE" \
  ADMIRA_JSON_CLOUD_SECRET="$CLOUD_ACCESS_SECRET" \
  ADMIRA_JSON_INSTALL_STATUS="ready" \
  ADMIRA_JSON_INSTALL_PROGRESS="100" \
  jxa_json
}

find_ssh_key_id() {
  local response="$1" public_key="$2"
  /usr/bin/osascript -l JavaScript - "$response" "$public_key" <<'JXA' 2>&1 || true
ObjC.import('Foundation');
const args = $.NSProcessInfo.processInfo.arguments;
const path = ObjC.unwrap(args.objectAtIndex(4));
const wanted = ObjC.unwrap(args.objectAtIndex(5));
const text = ObjC.unwrap($.NSString.stringWithContentsOfFileEncodingError(path, $.NSUTF8StringEncoding, null));
const payload = JSON.parse(text);
const match = (payload.ssh_keys || []).find((item) => String(item.public_key || '').trim() === wanted.trim());
if (match && match.id) console.log(String(match.id));
JXA
}

do_api_optional() {
  local method="$1" path="$2" body="${3:-}" response="$TMP_DIR/do-optional-$RANDOM.json" http_status
  if [ "$method" = "GET" ]; then
    http_status="$(/usr/bin/curl --silent --show-error --location --connect-timeout 20 --max-time 120 \
      -H "Authorization: Bearer $DO_TOKEN" -H 'Content-Type: application/json' \
      -w '%{http_code}' "$DO_API$path" -o "$response" || printf '000')"
  else
    http_status="$(printf '%s' "$body" | /usr/bin/curl --silent --show-error --location --connect-timeout 20 --max-time 120 \
      -H "Authorization: Bearer $DO_TOKEN" -H 'Content-Type: application/json' \
      -X "$method" --data-binary @- -w '%{http_code}' "$DO_API$path" -o "$response" || printf '000')"
  fi
  API_RESPONSE="$response"
  if [[ "$http_status" =~ ^2 ]]; then return 0; fi
  log_line "DigitalOcean optional request failed: $method $path http=$http_status"
  return 1
}

do_api() {
  local method="$1" path="$2" body="${3:-}" response="$TMP_DIR/do-$RANDOM.json"
  if [ "$method" = "GET" ]; then
    if ! /usr/bin/curl --fail --silent --show-error --location --connect-timeout 20 --max-time 120 \
      -H "Authorization: Bearer $DO_TOKEN" -H 'Content-Type: application/json' \
      "$DO_API$path" -o "$response"; then
      fail "DigitalOcean no respondió a la solicitud $path"
    fi
  else
    if ! printf '%s' "$body" | /usr/bin/curl --fail --silent --show-error --location --connect-timeout 20 --max-time 120 \
      -H "Authorization: Bearer $DO_TOKEN" -H 'Content-Type: application/json' \
      -X "$method" --data-binary @- "$DO_API$path" -o "$response"; then
      local detail
      detail="$(/bin/cat "$response" 2>/dev/null || true)"
      [ -n "$detail" ] || detail="DigitalOcean rechazó la solicitud $path"
      fail "$detail"
    fi
  fi
  API_RESPONSE="$response"
}

request_license() {
  local body response valid status transfer_available detail
  body="$(license_body)" || fail "No se pudo preparar la validación de licencia"
  response="$TMP_DIR/license-release.json"
  emit "license" 10 "Comprobando la licencia de compra…"
  if ! printf '%s' "$body" | /usr/bin/curl --fail --silent --show-error --location --connect-timeout 20 --max-time 90 \
    -H 'Content-Type: application/json' -X POST --data-binary @- "${LICENSE_SERVER_URL%/}${LICENSE_ENDPOINT}" -o "$response"; then
    fail "No se pudo contactar el servidor de licencias"
  fi
  valid="$(json_get "$response" valid || true)"
  status="$(json_get "$response" status || true)"
  transfer_available="$(json_get "$response" transfer_available || true)"
  detail="$(json_get "$response" detail || true)"
  if [ "$valid" != "true" ]; then
    printf 'ADMIRA|license_diagnostic|0|status=%s transfer_available=%s detail=%s\n' "${status:-unknown}" "${transfer_available:-false}" "${detail:-unknown}"
    if [ "$status" = "device_limit" ] && [ "$transfer_available" = "true" ] && [ "$TRANSFER_DEVICE" != "true" ]; then
      set_phase running
      printf 'ADMIRA|transfer_required|0|Esta licencia ya está vinculada a otro equipo.\n'
      exit 42
    fi
    [ -n "$detail" ] || detail="El servidor no autorizó esta licencia"
    fail "$detail"
  fi
  RELEASE_URL="$(json_get "$response" download_url || true)"
  RELEASE_SHA256="$(json_get "$response" sha256 || true)"
  CLOUD_INSTALL_TOKEN="$(json_get "$response" cloud_install_token || true)"
  [ -n "$RELEASE_URL" ] || fail "La licencia fue validada, pero no se recibió el paquete autorizado"
  [[ "$RELEASE_SHA256" =~ ^[A-Fa-f0-9]{64}$ ]] || fail "La descarga autorizada no incluyó una huella SHA-256 válida"
  [ -n "$CLOUD_INSTALL_TOKEN" ] || fail "La licencia fue validada, pero el servidor no habilitó el registro seguro de la instalación cloud"
}

download_source() {
  local archive="$TMP_DIR/MetaAdsAgent-source.zip" actual expected extract compose_root
  emit "download" 18 "Descargando el paquete autorizado de Admira IA…"
  /usr/bin/curl --fail --silent --show-error --location --retry 3 --connect-timeout 30 --max-time 1800 "$RELEASE_URL" -o "$archive" || fail "No se pudo descargar el paquete de Admira IA"
  actual="$(/usr/bin/shasum -a 256 "$archive" | /usr/bin/awk '{print $1}')"
  actual="$(printf '%s' "$actual" | tr '[:upper:]' '[:lower:]')"
  expected="$(printf '%s' "$RELEASE_SHA256" | tr '[:upper:]' '[:lower:]')"
  [ "$actual" = "$expected" ] || fail "La descarga no coincide con la huella autorizada"
  /usr/bin/unzip -tq "$archive" >/dev/null || fail "El paquete descargado está incompleto"
  if /usr/bin/zipinfo -1 "$archive" | /usr/bin/grep -Eq '(^/|(^|/)\\.\\.(\\/|$))'; then fail "El paquete contiene una ruta no segura"; fi
  extract="$TMP_DIR/source"
  mkdir -p "$extract"
  /usr/bin/unzip -q "$archive" -d "$extract" || fail "No se pudo extraer el paquete de Admira IA"
  compose_root="$(/usr/bin/find "$extract" -name docker-compose.yml -print -quit)"
  [ -n "$compose_root" ] || fail "El paquete no contiene docker-compose.yml"
  emit "download" 24 "Paquete descargado y verificado"
}

ensure_ssh_key() {
  mkdir -p "$(dirname "$KEY_PATH")"
  if [ ! -f "$KEY_PATH" ] || [ ! -f "${KEY_PATH}.pub" ]; then
    /usr/bin/ssh-keygen -q -t ed25519 -N "" -C "admira-ia-cloud-$LICENSE_SUFFIX" -f "$KEY_PATH" || fail "No se pudo generar la clave SSH"
  fi
  /bin/chmod 600 "$KEY_PATH"
  /bin/cat "${KEY_PATH}.pub"
}

wait_droplet() {
  local status public_ip
  for i in $(seq 1 90); do
    do_api GET "/droplets/$DROPLET_ID"
    status="$(json_get "$API_RESPONSE" droplet.status || true)"
    public_ip="$(/usr/bin/osascript -l JavaScript - "$API_RESPONSE" <<'JXA' 2>&1 || true
ObjC.import('Foundation');
const args=$.NSProcessInfo.processInfo.arguments;
const path=ObjC.unwrap(args.objectAtIndex(4));
const text=ObjC.unwrap($.NSString.stringWithContentsOfFileEncodingError(path,$.NSUTF8StringEncoding,null));
const d=JSON.parse(text).droplet;
const item=(d.networks && d.networks.v4 || []).find(n => n.type === 'public');
if (item && item.ip_address) console.log(item.ip_address);
JXA
    )"
    if [ "$status" = "active" ] && [[ "$public_ip" =~ ^[0-9.]+$ ]]; then
      DROPLET_IP="$public_ip"
      job_set droplet_ip "$DROPLET_IP"
      return 0
    fi
    emit "do" "$((28 + i / 4))" "Esperando que DigitalOcean prepare el servidor… ($i/90)"
    sleep 4
  done
  fail "DigitalOcean no terminó de preparar el servidor a tiempo"
}

wait_ssh() {
  for i in $(seq 1 90); do
    if /usr/bin/ssh -i "$KEY_PATH" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=4 root@"$DROPLET_IP" "echo ready" >/dev/null 2>&1; then return 0; fi
    emit "ssh" "$((55 + i / 5))" "Esperando acceso SSH al servidor… ($i/90)"
    sleep 4
  done
  fail "No se pudo acceder por SSH al servidor recién creado"
}

create_or_resume_resources() {
  local public_key key_name body user_data tag ssh_error
  SSH_ID="$(job_get ssh_id)"
  DROPLET_ID="$(job_get droplet_id)"
  FIREWALL_ID="$(job_get firewall_id)"
  DROPLET_IP="$(job_get droplet_ip)"
  KEY_PATH="$(job_get key_path)"
  [ -n "$KEY_PATH" ] || { KEY_PATH="$KEYS_DIR/$LICENSE_SUFFIX/id_ed25519"; job_set key_path "$KEY_PATH"; }

  if [ -z "$SSH_ID" ]; then
    emit "ssh" 30 "Generando acceso SSH seguro…"
    public_key="$(ensure_ssh_key)"
    SSH_PUBLIC_KEY="$public_key"

    # A retry after a network timeout can leave the key created in
    # DigitalOcean while the local job still has no ssh_id. Reuse by public
    # key before creating another one, so the next run is idempotent.
    if do_api_optional GET /account/keys?per_page=200; then
      SSH_ID="$(find_ssh_key_id "$API_RESPONSE" "$public_key")"
      [[ "$SSH_ID" =~ ^[0-9]+$ ]] || SSH_ID=""
    fi
    if [ -z "$SSH_ID" ]; then
      key_name="admira-ia-$LICENSE_SUFFIX-$(date '+%Y%m%d%H%M%S')"
      body="$(ssh_body "$key_name" "$public_key")" || fail "No se pudo preparar la clave SSH para DigitalOcean"
      if do_api_optional POST /account/keys "$body"; then
        SSH_ID="$(json_get "$API_RESPONSE" ssh_key.id || true)"
      else
        ssh_error="$(json_get "$API_RESPONSE" message || true)"
        [ -n "$ssh_error" ] || ssh_error="DigitalOcean rechazó la solicitud /account/keys"
        # The POST may have succeeded remotely even when the response was
        # lost. Refresh the list once before presenting an unrecoverable error.
        sleep 1
        if do_api_optional GET /account/keys?per_page=200; then
          SSH_ID="$(find_ssh_key_id "$API_RESPONSE" "$public_key")"
          [[ "$SSH_ID" =~ ^[0-9]+$ ]] || SSH_ID=""
        fi
        [ -n "$SSH_ID" ] || fail "$ssh_error"
      fi
    fi
    [ -n "$SSH_ID" ] || fail "DigitalOcean no devolvió el identificador de la clave SSH"
    job_set ssh_id "$SSH_ID"
  else
    SSH_PUBLIC_KEY="$(ensure_ssh_key)"
  fi

  if [ -z "$DROPLET_ID" ]; then
    emit "do" 38 "Creando tu Droplet en DigitalOcean…"
    # Do not install packages from cloud-init.  cloud-init runs apt in the
    # background on a new Ubuntu Droplet, and the remote setup below also
    # needs apt to install Docker.  Having both do it at once races for
    # /var/lib/dpkg/lock-frontend.  Keep user-data side-effect free and let
    # the single remote setup script own package installation.
    user_data=$'#cloud-config\nruncmd:\n  - touch /var/lib/admira-cloud-init-ready\n'
    tag="admira-$LICENSE_SUFFIX"
    body="$(droplet_body "admira-ia-$LICENSE_SUFFIX" "$DO_REGION" "$DO_SIZE" "$SSH_ID" "$tag" "$user_data")" || fail "No se pudo preparar la creación del Droplet"
    do_api POST /droplets "$body"
    DROPLET_ID="$(json_get "$API_RESPONSE" droplet.id || true)"
    [ -n "$DROPLET_ID" ] || fail "DigitalOcean no devolvió el identificador del Droplet"
    job_set droplet_id "$DROPLET_ID"
  fi
  if [ -z "$DROPLET_IP" ]; then wait_droplet; fi

  if [ -z "$FIREWALL_ID" ]; then
    emit "firewall" 52 "Configurando el firewall del dashboard…"
    body="$(firewall_body "admira-ia-$LICENSE_SUFFIX-firewall" "$DROPLET_ID")" || fail "No se pudo preparar el firewall de DigitalOcean"
    do_api POST /firewalls "$body"
    FIREWALL_ID="$(json_get "$API_RESPONSE" firewall.id || true)"
    [ -n "$FIREWALL_ID" ] || fail "DigitalOcean no devolvió el identificador del firewall"
    job_set firewall_id "$FIREWALL_ID"
  fi
  emit "ssh" 58 "Servidor listo; comprobando el acceso SSH…"
  wait_ssh
}

install_remote() {
  local source_archive="$TMP_DIR/MetaAdsAgent-source.zip" remote_script="$TMP_DIR/remote-setup.sh" license_b64 email_b64 secret_b64 gate_asset reset_asset
  license_b64="$(printf '%s' "$LICENSE_KEY" | /usr/bin/base64 | tr -d '\n')"
  email_b64="$(printf '%s' "$BUYER_EMAIL" | /usr/bin/base64 | tr -d '\n')"
  secret_b64="$(printf '%s' "$CLOUD_ACCESS_SECRET" | /usr/bin/base64 | tr -d '\n')"
  gate_asset="$CLOUD_ASSET_DIR/admira-cloud-access-gate.py"
  reset_asset="$CLOUD_ASSET_DIR/admira-cloud-clean-reset.sh"
  emit "transfer" 64 "Subiendo el paquete autorizado al servidor…"
  /usr/bin/scp -q -i "$KEY_PATH" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$source_archive" root@"$DROPLET_IP":/tmp/admira-source.zip || fail "No se pudo subir Admira IA al servidor"
  /usr/bin/scp -q -i "$KEY_PATH" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$gate_asset" root@"$DROPLET_IP":/tmp/admira-cloud-access-gate.py || fail "No se pudo preparar el acceso seguro cloud"
  /usr/bin/scp -q -i "$KEY_PATH" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$reset_asset" root@"$DROPLET_IP":/tmp/admira-cloud-clean-reset.sh || fail "No se pudo preparar la limpieza segura cloud"

  cat > "$remote_script" <<SCRIPT
#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
if command -v cloud-init >/dev/null 2>&1; then
  cloud-init status --wait >/dev/null 2>&1 || true
fi
wait_for_package_manager() {
  local attempts=0
  while true; do
    if command -v fuser >/dev/null 2>&1; then
      if ! fuser /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/lib/apt/lists/lock /var/cache/apt/archives/lock >/dev/null 2>&1; then
        return 0
      fi
    elif command -v pgrep >/dev/null 2>&1; then
      if ! pgrep -x apt-get >/dev/null 2>&1 \
         && ! pgrep -x dpkg >/dev/null 2>&1 \
         && ! pgrep -f 'unattended[-_]upgrade' >/dev/null 2>&1; then
        return 0
      fi
    else
      # Ubuntu cloud images normally include fuser/pgrep.  If a minimal
      # image has neither, cloud-init was disabled above and we can proceed.
      return 0
    fi
    attempts=\$((attempts + 1))
    if [ "\$attempts" -gt 180 ]; then
      echo 'Timed out waiting for Ubuntu package manager locks' >&2
      return 1
    fi
    sleep 2
  done
}
wait_for_package_manager
dpkg --configure -a
apt-get update -qq
if ! apt-get install -y -qq ca-certificates curl unzip rsync python3 docker.io docker-compose-v2; then
  apt-get install -y -qq ca-certificates curl unzip rsync python3 docker.io docker-compose-plugin
fi
systemctl enable --now docker
mkdir -p /opt/admira-ia /tmp/admira-source
rm -rf /tmp/admira-source/*
unzip -q /tmp/admira-source.zip -d /tmp/admira-source
compose_root=\$(find /tmp/admira-source -name docker-compose.yml -print -quit)
[ -n "\$compose_root" ]
rsync -a "\$(dirname "\$compose_root")/" /opt/admira-ia/ --exclude '.env' --exclude 'ad-config.json' --exclude 'dashboard/data/' --exclude 'logs/' --exclude 'output/'
[ -f /opt/admira-ia/.env ] || cp /opt/admira-ia/.env.example /opt/admira-ia/.env
[ -f /opt/admira-ia/ad-config.json ] || { [ -f /opt/admira-ia/ad-config.example.json ] && cp /opt/admira-ia/ad-config.example.json /opt/admira-ia/ad-config.json || true; }
mkdir -p /opt/admira-ia/dashboard/data /opt/admira-ia/logs /opt/admira-ia/output /opt/admira-ia/brand_guides/products
set_env() {
  local key="\$1" value="\$2"
  if grep -q "^\${key}=" /opt/admira-ia/.env; then
    sed -i "s#^\${key}=.*#\${key}=\${value}#" /opt/admira-ia/.env
  else
    printf '\\n%s=%s\\n' "\$key" "\$value" >> /opt/admira-ia/.env
  fi
}
license_key=\$(printf '%s' '$license_b64' | base64 -d)
buyer_email=\$(printf '%s' '$email_b64' | base64 -d)
set_env DASHBOARD_HOST 0.0.0.0
set_env DASHBOARD_PORT 7871
set_env ALLOW_PUBLIC_DASHBOARD true
set_env LAN_ACCESS_ENABLED true
set_env REQUIRE_DASHBOARD_TOKEN true
set_env LICENSE_KEY "\$license_key"
set_env LICENSE_BUYER_EMAIL "\$buyer_email"
set_env LICENSE_REQUIRED_FOR_LIVE true
set_env DIGITALOCEAN_DROPLET_ID '$DROPLET_ID'
set_env ADMIRA_INSTANCE_SLUG '$INSTANCE_SLUG'
set_env ADMIRA_COMPOSE_PROJECT_NAME '$INSTANCE_PROJECT'
set_env ADMIRA_CONTAINER_NAME 'admira-ia-$INSTANCE_SLUG'
set_env ADMIRA_VOLUME_PREFIX 'meta_ads_${LICENSE_SUFFIX//-/_}'
if [ '$DO_SIZE' = 's-1vcpu-1gb' ]; then
  if ! swapon --show | grep -q /swapfile; then
    if [ ! -f /swapfile ]; then fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048; chmod 600 /swapfile; mkswap /swapfile; fi
    swapon /swapfile || true
  fi
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
cd /opt/admira-ia
compose_cli="docker compose"
if ! docker compose version >/dev/null 2>&1; then
  compose_cli="docker-compose"
fi
\$compose_cli -p '$INSTANCE_PROJECT' up -d --build

# The image entrypoint initializes /app/runtime/.env in its named volume.
# Compose's env_file values are visible as process environment, but the
# dashboard intentionally loads that persistent file on startup and older
# releases let its defaults (LAN_ACCESS_ENABLED=false, empty Droplet id, ...)
# override the cloud values. Synchronize the cloud settings into the volume
# after the first start, then restart once so the dashboard reads them.
runtime_sync_attempts=0
while true; do
  if \$compose_cli -p '$INSTANCE_PROJECT' exec -T meta-ads-agent python3 - <<'PY'
from pathlib import Path
import os

path = Path('/app/runtime/.env')
path.parent.mkdir(parents=True, exist_ok=True)
lines = path.read_text(encoding='utf-8').splitlines() if path.exists() else []
values = {}
for key in (
    'DASHBOARD_HOST', 'DASHBOARD_PORT', 'ALLOW_PUBLIC_DASHBOARD',
    'LAN_ACCESS_ENABLED', 'REQUIRE_DASHBOARD_TOKEN', 'LICENSE_KEY',
    'LICENSE_BUYER_EMAIL', 'LICENSE_REQUIRED_FOR_LIVE',
    'DIGITALOCEAN_DROPLET_ID', 'ADMIRA_INSTANCE_SLUG',
    'ADMIRA_COMPOSE_PROJECT_NAME', 'ADMIRA_CONTAINER_NAME',
    'ADMIRA_VOLUME_PREFIX',
):
    value = str(os.environ.get(key) or '').strip()
    if value:
        values[key] = value

for key, value in values.items():
    prefix = f'{key}='
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = prefix + value
            break
    else:
        lines.append(prefix + value)

path.write_text(('\n'.join(lines) + '\n') if lines else '', encoding='utf-8')
PY
  then
    break
  fi
  runtime_sync_attempts=\$((runtime_sync_attempts + 1))
  if [ "\$runtime_sync_attempts" -gt 30 ]; then
    echo 'The Admira IA container did not become ready for runtime configuration' >&2
    exit 1
  fi
  sleep 2
done
\$compose_cli -p '$INSTANCE_PROJECT' restart meta-ads-agent
install -D -m 0700 /tmp/admira-cloud-access-gate.py /opt/admira-cloud-access-gate/server.py
install -D -m 0700 /tmp/admira-cloud-clean-reset.sh /usr/local/bin/admira-cloud-clean-reset
install -d -m 0700 /opt/admira-cloud-access-gate /etc/admira-cloud-access-gate /var/lib/admira-cloud-access-gate
cloud_access_secret=\$(printf '%s' '$secret_b64' | base64 -d)
cat > /etc/admira-cloud-access-gate/env <<EOF
CLOUD_ACCESS_SECRET=\$cloud_access_secret
CLOUD_ACCESS_PORT=$CLOUD_ACCESS_PORT
RESET_COMMAND=/usr/local/bin/admira-cloud-clean-reset
ADMIRA_CLOUD_INSTALL_DIR=/opt/admira-ia
ADMIRA_CLOUD_COMPOSE_PROJECT=$INSTANCE_PROJECT
ADMIRA_CLOUD_STATE_DIR=/var/lib/admira-cloud-access-gate
DASHBOARD_PORT=7871
EOF
chmod 0600 /etc/admira-cloud-access-gate/env
cat > /etc/systemd/system/admira-cloud-access-gate.service <<'SERVICE'
[Unit]
Description=Admira IA cloud clean reset gate
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
systemctl enable --now admira-cloud-access-gate.service
rm -f /tmp/admira-cloud-access-gate.py /tmp/admira-cloud-clean-reset.sh
rm -f /tmp/admira-source.zip
SCRIPT
  /bin/chmod 600 "$remote_script"
  emit "transfer" 72 "Esperando las tareas iniciales de Ubuntu e instalando Docker…"
  /usr/bin/scp -q -i "$KEY_PATH" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$remote_script" root@"$DROPLET_IP":/tmp/admira-setup.sh || fail "No se pudo enviar la configuración al servidor"
  if ! /usr/bin/ssh -i "$KEY_PATH" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$DROPLET_IP" "bash /tmp/admira-setup.sh" > "$TMP_DIR/remote-setup.log" 2>&1; then
    /usr/bin/tail -40 "$TMP_DIR/remote-setup.log" >> "$LOG_FILE" || true
    fail "El servidor no pudo completar la instalación de Docker. Revisa el registro"
  fi
  /usr/bin/ssh -i "$KEY_PATH" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$DROPLET_IP" "rm -f /tmp/admira-setup.sh" >/dev/null 2>&1 || true
}

register_cloud_installation() {
  local body response ok
  body="$(cloud_install_body)" || fail "No se pudo preparar el registro seguro de la instalación cloud"
  response="$TMP_DIR/cloud-install-registration.json"
  emit "register" 84 "Registrando el servidor para futuras limpiezas seguras…"
  for _attempt in $(seq 1 4); do
    if printf '%s' "$body" | /usr/bin/curl --fail --silent --show-error --location --connect-timeout 20 --max-time 90 \
      -H 'Content-Type: application/json' -X POST --data-binary @- \
      "${LICENSE_SERVER_URL%/}${CLOUD_INSTALL_ENDPOINT}" -o "$response"; then
      ok="$(json_get "$response" ok || true)"
      [ "$ok" = "true" ] && return 0
    fi
    sleep 3
  done
  fail "El servidor cloud quedó instalado, pero no se pudo registrar su limpieza segura. Revisa el registro y vuelve a abrir el instalador."
}

wait_dashboard() {
  local url="http://$DROPLET_IP:7871/" status
  emit "container" 88 "Contenedor iniciado; esperando que el dashboard responda…"
  for i in $(seq 1 180); do
    status="$(/usr/bin/curl --silent --show-error --max-time 5 -o "$TMP_DIR/dashboard-probe.html" -w '%{http_code}' "$url" 2>/dev/null || true)"
    case "$status" in
      2*|3*) return 0 ;;
      403)
        if /usr/bin/grep -qi 'Acceso por Wi' "$TMP_DIR/dashboard-probe.html" 2>/dev/null; then
          fail "El dashboard respondió 403 porque el acceso público quedó desactivado en su volumen persistente"
        fi
        ;;
    esac
    emit "container" "$((88 + i / 20))" "Esperando el dashboard… ($i/180)"
    sleep 2
  done
  fail "El dashboard se instaló, pero no respondió en $url"
}

write_shortcut() {
  local desktop="$HOME/Desktop" file url email_label
  # Keep one recognizable shortcut per licensed buyer when several cloud
  # installations are created from the same Mac. The email is normalized
  # earlier in main(); sanitize the filename without changing the URL.
  email_label="$(printf '%s' "$BUYER_EMAIL" | /usr/bin/sed 's/[^A-Za-z0-9@._+-]/_/g')"
  [ -n "$email_label" ] || email_label="cliente"
  file="$HOME/Desktop/Admira IA Dashboard - $email_label.webloc"
  url="http://$DROPLET_IP:7871/"
  mkdir -p "$desktop"
  printf '%s\n' \
    '<?xml version="1.0" encoding="UTF-8"?>' \
    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">' \
    '<plist version="1.0"><dict><key>URL</key><string>'"$url"'</string></dict></plist>' > "$file.tmp"
  /usr/bin/plutil -lint "$file.tmp" >/dev/null || fail "No se pudo crear el acceso directo del dashboard"
  mv -f "$file.tmp" "$file"
  printf '%s\n' "$url" > "$URL_FILE"
}

register_continuation() {
  local launch_dir plist
  launch_dir="$HOME/Library/LaunchAgents"
  plist="$launch_dir/$CONTINUATION_LABEL.plist"
  mkdir -p "$launch_dir"
  if [ "$INSTALLER_MODE" = "command" ] && [ -n "$INSTALLER_COMMAND_FILE" ]; then
    cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$CONTINUATION_LABEL</string>
<key>ProgramArguments</key><array><string>/bin/bash</string><string>$INSTALLER_COMMAND_FILE</string><string>--resume</string></array>
<key>RunAtLoad</key><true/><key>LimitLoadToSessionType</key><string>Aqua</string>
<key>ProcessType</key><string>Interactive</string>
<key>StandardOutPath</key><string>$STATE_DIR/continuation.log</string>
<key>StandardErrorPath</key><string>$STATE_DIR/continuation.log</string>
</dict></plist>
PLIST
  else
    cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$CONTINUATION_LABEL</string>
<key>ProgramArguments</key><array><string>/usr/bin/open</string><string>-a</string><string>$INSTALLER_APP</string></array>
<key>RunAtLoad</key><true/><key>LimitLoadToSessionType</key><string>Aqua</string>
<key>ProcessType</key><string>Interactive</string>
<key>StandardOutPath</key><string>$STATE_DIR/continuation.log</string>
<key>StandardErrorPath</key><string>$STATE_DIR/continuation.log</string>
</dict></plist>
PLIST
  fi
  /bin/launchctl bootout "gui/$(id -u)/$CONTINUATION_LABEL" >/dev/null 2>&1 || true
  /bin/launchctl bootstrap "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
}

main() {
  local resume="false"
  [ "${1:-}" = "--resume" ] && resume="true"
  TMP_DIR="$(/usr/bin/mktemp -d "$STATE_DIR/work.XXXXXX")"
  require_tools
  if [ "$resume" = "true" ]; then
    BUYER_EMAIL="$(keychain_read buyer-email)"
    LICENSE_KEY="$(keychain_read license-key)"
    DO_TOKEN="$(keychain_read do-token)"
    DEVICE_ID="$(keychain_read device-id)"
    TRANSFER_DEVICE="${ADMIRA_TRANSFER_DEVICE:-$(keychain_read transfer-device)}"
    DO_SIZE="$(keychain_read do-size)"
    DO_REGION="$(keychain_read do-region)"
    CLOUD_ACCESS_SECRET="$(keychain_read cloud-access-secret)"
  else
    BUYER_EMAIL="${ADMIRA_INSTALLER_EMAIL:-}"
    LICENSE_KEY="${ADMIRA_INSTALLER_LICENSE:-}"
    DO_TOKEN="${ADMIRA_DO_TOKEN:-}"
    DO_SIZE="${ADMIRA_DO_SIZE:-s-1vcpu-2gb}"
    DO_REGION="${ADMIRA_DO_REGION:-nyc3}"
    DEVICE_ID="$(keychain_read device-id)"
    TRANSFER_DEVICE="${ADMIRA_TRANSFER_DEVICE:-false}"
  fi
  BUYER_EMAIL="$(printf '%s' "$BUYER_EMAIL" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
  LICENSE_KEY="$(printf '%s' "$LICENSE_KEY" | tr -d '[:space:]' | tr '[:lower:]' '[:upper:]')"
  [ -n "$DO_TOKEN" ] || fail "Pega un token de DigitalOcean para continuar"
  [[ "$DO_SIZE" =~ ^s-[0-9]+vcpu-[0-9]+gb$ ]] || fail "El tamaño de Droplet seleccionado no es válido"
  [[ "$DO_REGION" =~ ^[a-z0-9]+$ ]] || fail "La región seleccionada no es válida"
  [[ "$BUYER_EMAIL" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]] || fail "Escribe un correo de compra válido"
  [[ "$LICENSE_KEY" =~ ^[A-Z0-9][A-Z0-9-]{7,120}$ ]] || fail "Escribe una licencia válida"
  if [ -z "$DEVICE_ID" ]; then DEVICE_ID="$(/usr/bin/uuidgen | tr -d '-')"; keychain_write device-id "$DEVICE_ID"; fi
  LICENSE_SUFFIX="$(printf '%s:%s' "$BUYER_EMAIL" "$LICENSE_KEY" | /usr/bin/shasum -a 256 | /usr/bin/cut -c1-10 | tr '[:upper:]' '[:lower:]')"
  INSTANCE_SLUG="client-$LICENSE_SUFFIX"
  INSTANCE_PROJECT="admira-ia-$LICENSE_SUFFIX"
  JOB_FILE="$JOBS_DIR/$LICENSE_SUFFIX.state"
  if [ -z "$CLOUD_ACCESS_SECRET" ]; then
    CLOUD_ACCESS_SECRET="$(printf '%s:%s:%s' "$LICENSE_KEY" "$DEVICE_ID" "$(/usr/bin/uuidgen)" | /usr/bin/shasum -a 256 | /usr/bin/cut -d' ' -f1)"
    keychain_write cloud-access-secret "$CLOUD_ACCESS_SECRET"
  fi
  if [ -n "$(job_get size 2>/dev/null || true)" ]; then DO_SIZE="$(job_get size)"; fi
  if [ -n "$(job_get region 2>/dev/null || true)" ]; then DO_REGION="$(job_get region)"; fi
  job_set phase running
  job_set license_suffix "$LICENSE_SUFFIX"
  job_set size "$DO_SIZE"
  job_set region "$DO_REGION"
  job_set instance_slug "$INSTANCE_SLUG"
  job_set instance_project "$INSTANCE_PROJECT"
  keychain_write buyer-email "$BUYER_EMAIL"
  keychain_write license-key "$LICENSE_KEY"
  keychain_write do-token "$DO_TOKEN"
  keychain_write transfer-device "$TRANSFER_DEVICE"
  keychain_write do-size "$DO_SIZE"
  keychain_write do-region "$DO_REGION"
  register_continuation
  emit "prepare" 5 "Preparando la instalación en DigitalOcean…"
  request_license
  do_api GET /account
  download_source
  create_or_resume_resources
  install_remote
  wait_dashboard
  register_cloud_installation
  write_shortcut
  job_set droplet_ip "$DROPLET_IP"
  job_set firewall_id "$FIREWALL_ID"
  job_set url "http://$DROPLET_IP:7871/"
  job_set phase complete
  remove_continuation
  keychain_delete do-token
  keychain_delete buyer-email
  keychain_delete license-key
  keychain_delete transfer-device
  keychain_delete do-size
  keychain_delete do-region
  keychain_delete cloud-access-secret
  emit "complete" 100 "Instalación completada. Abriendo el dashboard…"
  /usr/bin/open "http://$DROPLET_IP:7871/" >/dev/null 2>&1 || true
}

main "$@"
