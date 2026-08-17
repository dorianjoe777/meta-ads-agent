#!/usr/bin/env bash
set -euo pipefail

# Admira IA macOS installer engine.
# The visible installer is a small AppKit app; this script performs the
# privileged/download/Docker work without opening a Terminal window.

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

STATE_DIR="${HOME}/Library/Application Support/Admira IA/Installer"
LOG_FILE="$STATE_DIR/install.log"
STATUS_FILE="$STATE_DIR/status.txt"
PORT_FILE="$STATE_DIR/port.txt"
KEYCHAIN_SERVICE="lat.uboost.admira.installer"
CONTINUATION_LABEL="lat.uboost.admira.installer"
AUTOSTART_LABEL="lat.uboost.admira.autostart"
INSTALL_ROOT="$HOME/Applications/Admira IA"
INSTALLER_APP="$HOME/Applications/Admira IA Installer.app"
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LICENSE_SERVER_URL="https://admiraia.uboost.lat"
LICENSE_ENDPOINT="/api/license/release"
RELEASE_ASSET="MetaAdsAgent-source.zip"
RELEASE_CHANNEL="stable"
DEVICE_ID=""
BUYER_EMAIL=""
LICENSE_KEY=""
INSTANCE_DIR=""
INSTANCE_PORT=""
INSTANCE_PROJECT=""
INSTANCE_SLUG=""
RELEASE_JSON=""
RELEASE_URL=""
RELEASE_SHA256=""
TRANSFER_DEVICE="false"
TMP_DIR=""

mkdir -p "$STATE_DIR"
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

fail() {
  local message="$1"
  emit "error" 100 "$message"
  alert "Admira IA no pudo completar la instalación" "$message. Puedes volver a abrir la app; el registro está en: $LOG_FILE" warning
  exit 1
}

cleanup() {
  if [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ]; then
    /bin/rm -rf "$TMP_DIR" 2>/dev/null || true
  fi
}
trap cleanup EXIT

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

docker_bin() {
  if command -v docker >/dev/null 2>&1; then command -v docker; return 0; fi
  if [ -x "/Applications/Docker.app/Contents/Resources/bin/docker" ]; then
    printf '%s\n' "/Applications/Docker.app/Contents/Resources/bin/docker"; return 0
  fi
  if [ -x "$HOME/Applications/Docker.app/Contents/Resources/bin/docker" ]; then
    printf '%s\n' "$HOME/Applications/Docker.app/Contents/Resources/bin/docker"; return 0
  fi
  return 1
}

compose_cmd() {
  local docker="$1"
  if "$docker" compose version >/dev/null 2>&1; then
    printf '%s\n' "$docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then
    printf '%s\n' "$(command -v docker-compose)"
  else
    return 1
  fi
}

run_compose() {
  local docker="$1" project="$2" config="$3" config_dir="$4"
  if "$docker" compose version >/dev/null 2>&1; then
    (cd "$config_dir" && "$docker" compose -f "$config" -p "$project" up -d --build)
  else
    (cd "$config_dir" && docker-compose -f "$config" -p "$project" up -d --build)
  fi
}

wait_for_docker() {
  local docker="$1"
  for _ in $(seq 1 180); do
    if "$docker" info >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  return 1
}

install_docker_desktop() {
  local docker=""
  docker="$(docker_bin 2>/dev/null || true)"
  if [ -n "$docker" ]; then
    emit "docker" 18 "Docker Desktop está instalado; esperando a que el motor esté listo…"
    open -a Docker >/dev/null 2>&1 || true
    wait_for_docker "$docker" || fail "Docker Desktop no respondió después de varios minutos"
    return 0
  fi

  local arch url cache dmg mount_line mount_point
  arch="$(uname -m)"
  if [ "$arch" = "arm64" ]; then
    url="https://desktop.docker.com/mac/main/arm64/Docker.dmg"
  else
    url="https://desktop.docker.com/mac/main/amd64/Docker.dmg"
  fi
  cache="$HOME/Library/Caches/Admira IA"
  dmg="$cache/Docker.dmg"
  mkdir -p "$cache"
  emit "docker" 10 "Descargando Docker Desktop oficial para tu Mac…"
  /usr/bin/curl --fail --location --retry 3 --connect-timeout 30 --max-time 1800 "$url" -o "$dmg" || fail "No se pudo descargar Docker Desktop"
  /usr/bin/hdiutil verify "$dmg" >/dev/null || fail "La descarga de Docker Desktop no superó la verificación"

  emit "docker" 25 "Instalando Docker Desktop…"
  mount_line="$(/usr/bin/hdiutil attach "$dmg" -nobrowse -readonly 2>/dev/null | /usr/bin/grep -m1 -o '/Volumes/.*' || true)"
  [ -n "$mount_line" ] || fail "No se pudo abrir el instalador de Docker Desktop"
  mount_point="${mount_line%%$'\r'}"
  if [ ! -d "$mount_point/Docker.app" ]; then
    /usr/bin/hdiutil detach "$mount_point" -quiet >/dev/null 2>&1 || true
    fail "El instalador de Docker Desktop no contiene Docker.app"
  fi
  /usr/bin/codesign --verify --deep --strict "$mount_point/Docker.app" >/dev/null 2>&1 || {
    /usr/bin/hdiutil detach "$mount_point" -quiet >/dev/null 2>&1 || true
    fail "La aplicación de Docker Desktop no superó la verificación de firma"
  }
  /usr/bin/osascript - "$mount_point/Docker.app" <<'APPLESCRIPT' >/dev/null 2>&1 || {
on run argv
  set sourceApp to item 1 of argv
  do shell script "/usr/bin/ditto " & quoted form of sourceApp & " /Applications/Docker.app" with administrator privileges
end run
APPLESCRIPT
    /usr/bin/hdiutil detach "$mount_point" -quiet >/dev/null 2>&1 || true
    fail "macOS no autorizó copiar Docker Desktop a Aplicaciones"
  }
  /usr/bin/hdiutil detach "$mount_point" -quiet >/dev/null 2>&1 || true
  open -a Docker >/dev/null 2>&1 || true
  docker="$(docker_bin 2>/dev/null || true)"
  [ -n "$docker" ] || fail "Docker Desktop se instaló, pero no se encontró su CLI"
  emit "docker" 35 "Docker Desktop está iniciando…"
  wait_for_docker "$docker" || fail "Docker Desktop no llegó a estado operativo"
}

request_release() {
  local transfer="${1:-false}" response="$TMP_DIR/license-release.json" body endpoint
  endpoint="${LICENSE_SERVER_URL%/}${LICENSE_ENDPOINT}"
  body="{\"license_key\":\"$LICENSE_KEY\",\"buyer_email\":\"$BUYER_EMAIL\",\"device_id\":\"$DEVICE_ID\",\"asset_name\":\"$RELEASE_ASSET\",\"channel\":\"$RELEASE_CHANNEL\",\"transfer_device\":$transfer}"
  emit "license" 43 "Verificando la licencia de compra…"
  if ! /usr/bin/curl --fail --silent --show-error --location --connect-timeout 20 --max-time 90 \
      -H 'Content-Type: application/json' -d "$body" "$endpoint" -o "$response"; then
    fail "No se pudo contactar el servidor de licencias"
  fi
  RELEASE_JSON="$response"
  local valid status transfer_available detail
  valid="$(json_get "$response" valid || true)"
  status="$(json_get "$response" status || true)"
  transfer_available="$(json_get "$response" transfer_available || true)"
  detail="$(json_get "$response" detail || true)"
  if [ "$valid" != "true" ]; then
    if [ "$status" = "device_limit" ] && [ "$transfer_available" = "true" ] && [ "$transfer" != "true" ]; then
      printf 'ADMIRA|transfer_required|0|Esta licencia ya está vinculada a otro equipo.\n'
      exit 42
    fi
    [ -n "$detail" ] || detail="El servidor no autorizó esta licencia"
    fail "$detail"
  fi
  RELEASE_URL="$(json_get "$response" download_url || true)"
  RELEASE_SHA256="$(json_get "$response" sha256 || true)"
  [ -n "$RELEASE_URL" ] || fail "La licencia fue validada, pero no se recibió el enlace de instalación"
  [[ "$RELEASE_SHA256" =~ ^[A-Fa-f0-9]{64}$ ]] || fail "La descarga autorizada no incluyó una huella SHA-256 válida"
  log_line "Licencia validada para la instancia local"
}

read_env() {
  local file="$1" key="$2"
  [ -f "$file" ] || return 0
  /usr/bin/awk -F= -v wanted="$key" '$1 == wanted {print substr($0, index($0,"=")+1); exit}' "$file"
}

set_env_value() {
  local file="$1" key="$2" value="$3" tmp="$file.tmp"
  /usr/bin/awk -v key="$key" -v value="$value" '
    BEGIN { updated=0 }
    $0 !~ /^[[:space:]]*#/ && index($0, key "=") == 1 { print key "=" value; updated=1; next }
    { print }
    END { if (!updated) print key "=" value }
  ' "$file" > "$tmp"
  mv -f "$tmp" "$file"
}

choose_instance() {
  local existing_license base="$HOME/Applications/Admira IA"
  existing_license="$(read_env "$base/.env" LICENSE_KEY || true)"
  if [ -d "$base" ] && [ -n "$existing_license" ] && [ "$existing_license" != "$LICENSE_KEY" ]; then
    local fingerprint
    fingerprint="$(printf '%s:%s' "$BUYER_EMAIL" "$LICENSE_KEY" | /usr/bin/shasum -a 256 | /usr/bin/cut -c1-10)"
    INSTANCE_DIR="$HOME/Applications/Admira IA Instances/$fingerprint"
  else
    INSTANCE_DIR="$base"
  fi
  mkdir -p "$INSTANCE_DIR"
  INSTANCE_PORT="$(read_env "$INSTANCE_DIR/.env" DASHBOARD_PORT || true)"
  if ! [[ "$INSTANCE_PORT" =~ ^[0-9]{4,5}$ ]]; then INSTANCE_PORT=""; fi
  if [ -z "$INSTANCE_PORT" ]; then
    for candidate in $(seq 7871 7890); do
      if ! /usr/sbin/lsof -nP -iTCP:"$candidate" -sTCP:LISTEN >/dev/null 2>&1; then INSTANCE_PORT="$candidate"; break; fi
    done
  fi
  [ -n "$INSTANCE_PORT" ] || fail "No hay un puerto libre entre 7871 y 7890"
  printf '%s\n' "$INSTANCE_PORT" > "$PORT_FILE"
  INSTANCE_SLUG="$(basename "$INSTANCE_DIR" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"
  INSTANCE_SLUG="${INSTANCE_SLUG:-default}"
  INSTANCE_PROJECT="admira-ia-${INSTANCE_SLUG}"
}

download_source() {
  local archive="$TMP_DIR/MetaAdsAgent-source.zip" extract="$TMP_DIR/source"
  emit "download" 55 "Descargando el paquete autorizado de Admira IA…"
  /usr/bin/curl --fail --silent --show-error --location --retry 3 --connect-timeout 30 --max-time 1800 "$RELEASE_URL" -o "$archive" || fail "No se pudo descargar el paquete de Admira IA"
  local actual
  actual="$(/usr/bin/shasum -a 256 "$archive" | /usr/bin/awk '{print $1}')"
  [ "${actual,,}" = "${RELEASE_SHA256,,}" ] || fail "La descarga no coincide con la huella autorizada"
  /usr/bin/unzip -tq "$archive" >/dev/null || fail "El paquete descargado está incompleto"
  if /usr/bin/zipinfo -1 "$archive" | /usr/bin/grep -Eq '(^/|(^|/)\.\.(\/|$))'; then fail "El paquete contiene una ruta no segura"; fi
  mkdir -p "$extract"
  /usr/bin/unzip -q "$archive" -d "$extract" || fail "No se pudo extraer el paquete de Admira IA"
  local compose_root
  compose_root="$(/usr/bin/find "$extract" -name docker-compose.yml -print -quit)"
  [ -n "$compose_root" ] || fail "El paquete no contiene docker-compose.yml"
  compose_root="$(cd "$(dirname "$compose_root")" && pwd)"
  emit "download" 62 "Paquete descargado y verificado"

  if [ -f "$INSTANCE_DIR/docker-compose.yml" ]; then
    /usr/bin/rsync -a "$compose_root/" "$INSTANCE_DIR/" --exclude '.env' --exclude 'ad-config.json' --exclude 'dashboard/data/' --exclude 'logs/' --exclude 'output/'
  else
    /usr/bin/rsync -a "$compose_root/" "$INSTANCE_DIR/" --exclude '.env' --exclude 'ad-config.json' --exclude 'dashboard/data/' --exclude 'logs/' --exclude 'output/'
  fi
  [ -f "$INSTANCE_DIR/.env" ] || cp "$INSTANCE_DIR/.env.example" "$INSTANCE_DIR/.env"
  [ -f "$INSTANCE_DIR/ad-config.json" ] || { [ -f "$INSTANCE_DIR/ad-config.example.json" ] && cp "$INSTANCE_DIR/ad-config.example.json" "$INSTANCE_DIR/ad-config.json" || true; }
  mkdir -p "$INSTANCE_DIR/dashboard/data" "$INSTANCE_DIR/logs" "$INSTANCE_DIR/output" "$INSTANCE_DIR/brand_guides/products"
  chmod 600 "$INSTANCE_DIR/.env" || true
}

configure_instance() {
  emit "configure" 68 "Preparando la instancia y sus datos locales…"
  set_env_value "$INSTANCE_DIR/.env" LICENSE_KEY "$LICENSE_KEY"
  set_env_value "$INSTANCE_DIR/.env" LICENSE_BUYER_EMAIL "$BUYER_EMAIL"
  set_env_value "$INSTANCE_DIR/.env" LICENSE_DEVICE_ID "$DEVICE_ID"
  set_env_value "$INSTANCE_DIR/.env" LICENSE_SERVER_URL "$LICENSE_SERVER_URL"
  set_env_value "$INSTANCE_DIR/.env" LICENSE_REQUIRED_FOR_LIVE true
  set_env_value "$INSTANCE_DIR/.env" REQUIRE_DASHBOARD_TOKEN true
  set_env_value "$INSTANCE_DIR/.env" ALLOW_PUBLIC_DASHBOARD false
  set_env_value "$INSTANCE_DIR/.env" LAN_ACCESS_ENABLED false
  set_env_value "$INSTANCE_DIR/.env" LIVE_ACTIONS_ENABLED false
  set_env_value "$INSTANCE_DIR/.env" DASHBOARD_PORT "$INSTANCE_PORT"
  set_env_value "$INSTANCE_DIR/.env" ADMIRA_INSTANCE_SLUG "$INSTANCE_SLUG"
  set_env_value "$INSTANCE_DIR/.env" ADMIRA_COMPOSE_PROJECT_NAME "$INSTANCE_PROJECT"
  set_env_value "$INSTANCE_DIR/.env" ADMIRA_CONTAINER_NAME "admira-ia-$INSTANCE_SLUG"
  set_env_value "$INSTANCE_DIR/.env" ADMIRA_VOLUME_PREFIX "meta_ads_${INSTANCE_SLUG//-/_}"
}

build_and_start() {
  local docker compose_output docker_config
  docker="$(docker_bin 2>/dev/null || true)"
  [ -n "$docker" ] || fail "No se encontró Docker Desktop"
  emit "container" 74 "Construyendo y arrancando Admira IA en Docker…"
  compose_output="$TMP_DIR/compose.log"
  if ! run_compose "$docker" "$INSTANCE_PROJECT" "$INSTANCE_DIR/docker-compose.yml" "$INSTANCE_DIR" > "$compose_output" 2>&1; then
    if /usr/bin/grep -qi 'docker-credential-.*executable file not found' "$compose_output"; then
      docker_config="$TMP_DIR/docker-config"
      mkdir -p "$docker_config"
      printf '%s\n' '{"auths":{}}' > "$docker_config/config.json"
      emit "container" 78 "Corrigiendo la configuración local de credenciales de Docker…"
      if ! (DOCKER_CONFIG="$docker_config" run_compose "$docker" "$INSTANCE_PROJECT" "$INSTANCE_DIR/docker-compose.yml" "$INSTANCE_DIR") >> "$compose_output" 2>&1; then
        log_line "Docker Compose falló; diagnóstico guardado en $LOG_FILE"
        fail "Docker no pudo construir la imagen. Revisa el registro de instalación"
      fi
    else
      log_line "Docker Compose falló; diagnóstico guardado en $LOG_FILE"
      fail "Docker no pudo construir la imagen. Revisa el registro de instalación"
    fi
  fi
  /usr/bin/grep -vE 'LICENSE_KEY|buyer_email|download_url|sha256' "$compose_output" >> "$LOG_FILE" || true
  emit "container" 90 "Contenedor iniciado; esperando el dashboard…"
  local url="http://127.0.0.1:$INSTANCE_PORT/"
  for _ in $(seq 1 180); do
    if /usr/bin/curl --fail --silent --max-time 5 "$url" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  fail "El contenedor inició, pero el dashboard no respondió en $url"
}

write_shortcut() {
  local desktop="$HOME/Desktop" file="$HOME/Desktop/Admira IA Dashboard.webloc" url="http://127.0.0.1:$INSTANCE_PORT/"
  mkdir -p "$desktop"
  printf '%s\n' \
    '<?xml version="1.0" encoding="UTF-8"?>' \
    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">' \
    '<plist version="1.0"><dict><key>URL</key><string>'"$url"'</string></dict></plist>' > "$file.tmp"
  /usr/bin/plutil -lint "$file.tmp" >/dev/null || fail "No se pudo crear el acceso directo del dashboard"
  mv -f "$file.tmp" "$file"
}

install_autostart() {
  local launch_dir="$HOME/Library/LaunchAgents" plist="$launch_dir/$AUTOSTART_LABEL.plist" script="$INSTANCE_DIR/start-admira.sh"
  mkdir -p "$launch_dir"
  cat > "$script" <<SCRIPT
#!/usr/bin/env bash
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:\${PATH:-}"
docker="\$(command -v docker || true)"
if [ -z "\$docker" ] && [ -x /Applications/Docker.app/Contents/Resources/bin/docker ]; then docker=/Applications/Docker.app/Contents/Resources/bin/docker; fi
[ -n "\$docker" ] || exit 0
open -a Docker >/dev/null 2>&1 || true
for _ in \$(seq 1 180); do "\$docker" info >/dev/null 2>&1 && break; sleep 2; done
if "\$docker" compose version >/dev/null 2>&1; then (cd "$(printf '%s' "$INSTANCE_DIR")" && "\$docker" compose -p "$(printf '%s' "$INSTANCE_PROJECT")" up -d); else (cd "$(printf '%s' "$INSTANCE_DIR")" && docker-compose -p "$(printf '%s' "$INSTANCE_PROJECT")" up -d); fi
SCRIPT
  chmod 700 "$script"
  cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$AUTOSTART_LABEL</string>
<key>ProgramArguments</key><array><string>/bin/bash</string><string>$script</string></array>
<key>RunAtLoad</key><true/><key>LimitLoadToSessionType</key><string>Aqua</string>
<key>StandardOutPath</key><string>$INSTANCE_DIR/logs/autostart.log</string>
<key>StandardErrorPath</key><string>$INSTANCE_DIR/logs/autostart.log</string>
</dict></plist>
PLIST
  /bin/launchctl bootout "gui/$(id -u)/$AUTOSTART_LABEL" >/dev/null 2>&1 || true
  /bin/launchctl bootstrap "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
}

remove_continuation() {
  local plist="$HOME/Library/LaunchAgents/$CONTINUATION_LABEL.plist"
  /bin/launchctl bootout "gui/$(id -u)/$CONTINUATION_LABEL" >/dev/null 2>&1 || true
  if [ -f "$plist" ]; then /bin/rm -f "$plist"; fi
}

register_continuation() {
  local launch_dir="$HOME/Library/LaunchAgents" plist="$launch_dir/$CONTINUATION_LABEL.plist" engine="$INSTALLER_APP/Contents/Resources/admira-mac-engine.sh"
  mkdir -p "$launch_dir"
  cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$CONTINUATION_LABEL</string>
<key>ProgramArguments</key><array><string>/bin/bash</string><string>$engine</string><string>--resume</string></array>
<key>RunAtLoad</key><true/><key>LimitLoadToSessionType</key><string>Aqua</string>
<key>ProcessType</key><string>Interactive</string>
<key>StandardOutPath</key><string>$STATE_DIR/continuation.log</string>
<key>StandardErrorPath</key><string>$STATE_DIR/continuation.log</string>
</dict></plist>
PLIST
  /bin/launchctl bootout "gui/$(id -u)/$CONTINUATION_LABEL" >/dev/null 2>&1 || true
  /bin/launchctl bootstrap "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
}

main() {
  local resume="false"
  [ "${1:-}" = "--resume" ] && resume="true"
  TMP_DIR="$(/usr/bin/mktemp -d "$STATE_DIR/work.XXXXXX")"
  if [ "$resume" = "true" ]; then
    BUYER_EMAIL="$(keychain_read buyer-email)"
    LICENSE_KEY="$(keychain_read license-key)"
    DEVICE_ID="$(keychain_read device-id)"
    TRANSFER_DEVICE="$(keychain_read transfer-device)"
    [ -n "$TRANSFER_DEVICE" ] || TRANSFER_DEVICE="false"
  else
    BUYER_EMAIL="${ADMIRA_INSTALLER_EMAIL:-}"
    LICENSE_KEY="${ADMIRA_INSTALLER_LICENSE:-}"
    DEVICE_ID="$(keychain_read device-id)"
    TRANSFER_DEVICE="${ADMIRA_TRANSFER_DEVICE:-false}"
  fi
  BUYER_EMAIL="$(printf '%s' "$BUYER_EMAIL" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
  LICENSE_KEY="$(printf '%s' "$LICENSE_KEY" | tr -d '[:space:]' | tr '[:lower:]' '[:upper:]')"
  if [ -z "$DEVICE_ID" ]; then DEVICE_ID="$(/usr/bin/uuidgen | tr -d '-')"; keychain_write device-id "$DEVICE_ID"; fi
  [[ "$BUYER_EMAIL" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]] || fail "Escribe un correo de compra válido"
  [[ "$LICENSE_KEY" =~ ^[A-Z0-9][A-Z0-9-]{7,120}$ ]] || fail "Escribe una licencia válida"
  keychain_write buyer-email "$BUYER_EMAIL"
  keychain_write license-key "$LICENSE_KEY"
  keychain_write transfer-device "$TRANSFER_DEVICE"
  register_continuation
  emit "prepare" 5 "Preparando la instalación…"
  install_docker_desktop
  request_release "$TRANSFER_DEVICE"
  choose_instance
  download_source
  configure_instance
  build_and_start
  write_shortcut
  install_autostart
  remove_continuation
  keychain_delete buyer-email
  keychain_delete license-key
  keychain_delete transfer-device
  emit "complete" 100 "Instalación completada. Abriendo el dashboard…"
  open "http://127.0.0.1:$INSTANCE_PORT/" >/dev/null 2>&1 || true
}

main "$@"
