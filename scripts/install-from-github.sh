#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="$ROOT_DIR/installer/release-bootstrap.env"
PLATFORM="${1:-mac}"

read_config_value() {
  local key="$1"
  if [ ! -f "$CONFIG_FILE" ]; then
    return 0
  fi
  awk -F= -v wanted="$key" '
    $0 !~ /^[[:space:]]*#/ && $1 == wanted {
      sub(/^[[:space:]]+/, "", $2)
      sub(/[[:space:]]+$/, "", $2)
      print $2
      exit
    }
  ' "$CONFIG_FILE"
}

lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

default_device_id() {
  python3 - <<'PY'
import hashlib
import socket
import uuid
print(hashlib.sha256(f"{socket.gethostname()}:{uuid.getnode()}".encode("utf-8")).hexdigest()[:24])
PY
}

read_env_file_value() {
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

prompt_if_missing() {
  local label="$1"
  local current="${2:-}"
  if [ -n "$current" ]; then
    printf '%s' "$current"
    return 0
  fi
  if [ ! -t 0 ]; then
    return 1
  fi
  printf "%s" "$label" >&2
  local entered=""
  IFS= read -r entered
  printf '%s' "$entered"
}

persist_bootstrap_license_values() {
  local env_file="$1"
  local license_key="${2:-}"
  local buyer_email="${3:-}"
  local device_id="${4:-}"
  local license_server_url="${5:-}"
  [ -f "$env_file" ] || return 0
  python3 - "$env_file" "$license_key" "$buyer_email" "$device_id" "$license_server_url" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
updates = {
    "LICENSE_KEY": sys.argv[2],
    "LICENSE_BUYER_EMAIL": sys.argv[3],
    "LICENSE_DEVICE_ID": sys.argv[4],
    "LICENSE_SERVER_URL": sys.argv[5],
}
lines = path.read_text(encoding="utf-8").splitlines()
keys = {line.split("=", 1)[0]: index for index, line in enumerate(lines) if "=" in line and not line.lstrip().startswith("#")}
for key, value in updates.items():
    if not value:
        continue
    if key in keys:
        prefix = f"{key}="
        current = lines[keys[key]]
        if current == prefix:
            lines[keys[key]] = f"{prefix}{value}"
    else:
        lines.append(f"{key}={value}")
path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
PY
}

download_file() {
  local url="$1"
  local target="$2"
  echo "Descargando el paquete publicado..."
  echo "$url"
  curl -fL --retry 3 --connect-timeout 20 "$url" -o "$target"
}

validate_zip_archive() {
  local zip_path="$1"
  python3 - "$zip_path" <<'PY'
import stat
import sys
import zipfile
from pathlib import PurePosixPath

archive_path = sys.argv[1]
max_unpacked = 300 * 1024 * 1024
total = 0
with zipfile.ZipFile(archive_path) as archive:
    for member in archive.infolist():
        name = member.filename
        normalized = name.replace("\\", "/")
        parts = PurePosixPath(normalized).parts
        mode = member.external_attr >> 16
        total += int(member.file_size or 0)
        if total > max_unpacked:
            raise SystemExit("El paquete publicado es demasiado grande.")
        if (
            not normalized
            or normalized.startswith("/")
            or normalized.startswith("~")
            or ".." in parts
            or stat.S_IFMT(mode) == stat.S_IFLNK
        ):
            raise SystemExit("El paquete publicado contiene rutas no seguras.")
PY
}

request_signed_release_url() {
  local install_dir="$1"
  local tmp_dir="$2"
  local provider="${META_ADS_BOOTSTRAP_PROVIDER:-$(read_config_value BOOTSTRAP_PROVIDER)}"
  local license_server_url="${META_ADS_LICENSE_SERVER_URL:-$(read_config_value LICENSE_SERVER_URL)}"
  local release_endpoint="${META_ADS_LICENSE_RELEASE_ENDPOINT:-$(read_config_value LICENSE_RELEASE_ENDPOINT)}"
  local release_channel="${META_ADS_RELEASE_CHANNEL:-$(read_config_value RELEASE_CHANNEL)}"
  local release_asset_name="${META_ADS_RELEASE_ASSET_NAME:-$(read_config_value RELEASE_ASSET_NAME)}"

  if [ "$(lower "${provider:-}")" != "license_server" ]; then
    return 42
  fi
  if [ -z "${license_server_url:-}" ]; then
    echo "No hay LICENSE_SERVER_URL para pedir una descarga firmada."
    return 42
  fi
  release_endpoint="${release_endpoint:-/api/license/release}"
  release_channel="${release_channel:-stable}"
  release_asset_name="${release_asset_name:-MetaAdsAgent-source.zip}"

  local install_env="$install_dir/.env"
  local current_env="$ROOT_DIR/.env"
  local license_key="${META_ADS_LICENSE_KEY:-$(read_env_file_value "$install_env" LICENSE_KEY)}"
  license_key="${license_key:-$(read_env_file_value "$current_env" LICENSE_KEY)}"
  local buyer_email="${META_ADS_LICENSE_BUYER_EMAIL:-$(read_env_file_value "$install_env" LICENSE_BUYER_EMAIL)}"
  buyer_email="${buyer_email:-$(read_env_file_value "$current_env" LICENSE_BUYER_EMAIL)}"
  local device_id="${META_ADS_LICENSE_DEVICE_ID:-$(read_env_file_value "$install_env" LICENSE_DEVICE_ID)}"
  device_id="${device_id:-$(read_env_file_value "$current_env" LICENSE_DEVICE_ID)}"

  license_key="$(prompt_if_missing $'Ingresa tu licencia: ' "$license_key" || true)"
  buyer_email="$(prompt_if_missing $'Ingresa el email de compra: ' "$buyer_email" || true)"
  device_id="${device_id:-$(default_device_id)}"

  if [ -z "$license_key" ] || [ -z "$buyer_email" ]; then
    echo "Necesito licencia y email para preparar tu descarga protegida."
    return 41
  fi

  export META_ADS_BOOTSTRAP_LICENSE_KEY="$license_key"
  export META_ADS_BOOTSTRAP_LICENSE_EMAIL="$buyer_email"
  export META_ADS_BOOTSTRAP_DEVICE_ID="$device_id"
  export META_ADS_BOOTSTRAP_LICENSE_SERVER_URL="$license_server_url"
  export META_ADS_BOOTSTRAP_RELEASE_ENDPOINT="$release_endpoint"
  export META_ADS_BOOTSTRAP_RELEASE_CHANNEL="$release_channel"
  export META_ADS_BOOTSTRAP_RELEASE_ASSET_NAME="$release_asset_name"
  export META_ADS_BOOTSTRAP_TRANSFER_DEVICE="${META_ADS_TRANSFER_DEVICE:-false}"

  request_license_release() {
    python3 - "$tmp_dir/license-release.json" <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

target = sys.argv[1]
payload = {
    "license_key": os.environ["META_ADS_BOOTSTRAP_LICENSE_KEY"],
    "buyer_email": os.environ["META_ADS_BOOTSTRAP_LICENSE_EMAIL"],
    "device_id": os.environ["META_ADS_BOOTSTRAP_DEVICE_ID"],
    "channel": os.environ["META_ADS_BOOTSTRAP_RELEASE_CHANNEL"],
    "asset_name": os.environ["META_ADS_BOOTSTRAP_RELEASE_ASSET_NAME"],
    "transfer_device": os.environ.get("META_ADS_BOOTSTRAP_TRANSFER_DEVICE", "").lower() == "true",
}
url = os.environ["META_ADS_BOOTSTRAP_LICENSE_SERVER_URL"].rstrip("/") + os.environ["META_ADS_BOOTSTRAP_RELEASE_ENDPOINT"]
request = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
    data = {"valid": False, "status": "server_unreachable", "detail": "No pude contactar el servidor de licencias.", "error": str(exc)}
with open(target, "w", encoding="utf-8") as handle:
    json.dump(data, handle)
if not data.get("valid"):
    raise SystemExit(1)
PY
  }

  if ! request_license_release; then
    local status=""
    local transfer_available=""
    status="$(python3 - "$tmp_dir/license-release.json" <<'PY'
import json
import sys
try:
    print(json.load(open(sys.argv[1], encoding="utf-8")).get("status", ""))
except Exception:
    print("")
PY
)"
    transfer_available="$(python3 - "$tmp_dir/license-release.json" <<'PY'
import json
import sys
try:
    print("true" if json.load(open(sys.argv[1], encoding="utf-8")).get("transfer_available") else "false")
except Exception:
    print("false")
PY
)"
    if [ "$status" = "device_limit" ] && [ "$transfer_available" = "true" ] && [ -t 0 ] && [ "$(lower "${META_ADS_TRANSFER_DEVICE:-false}")" != "true" ]; then
      echo "Esta licencia ya esta activa en otro equipo."
      printf "Transferir la licencia a este equipo? Escribe SI para continuar: " >&2
      local confirm=""
      IFS= read -r confirm
      if [ "$(printf '%s' "$confirm" | tr '[:lower:]' '[:upper:]')" = "SI" ]; then
        export META_ADS_BOOTSTRAP_TRANSFER_DEVICE="true"
        request_license_release || true
      fi
    fi
  fi

  if ! python3 - "$tmp_dir/license-release.json" <<'PY'
import json
import sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    data = {}
raise SystemExit(0 if data.get("valid") else 1)
PY
  then
    local detail=""
    detail="$(python3 - "$tmp_dir/license-release.json" <<'PY'
import json
import sys
try:
    print(json.load(open(sys.argv[1], encoding="utf-8")).get("detail", "No se pudo preparar tu descarga."))
except Exception:
    print("No se pudo preparar tu descarga.")
PY
)"
    echo "$detail"
    return 41
  fi

  SIGNED_RELEASE_URL="$(python3 - "$tmp_dir/license-release.json" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8")).get("download_url", ""))
PY
)"
  if [ -z "$SIGNED_RELEASE_URL" ]; then
    echo "El servidor no devolvio una URL de descarga."
    return 41
  fi

  BOOTSTRAP_LICENSE_KEY="$license_key"
  BOOTSTRAP_BUYER_EMAIL="$buyer_email"
  BOOTSTRAP_DEVICE_ID="$device_id"
  BOOTSTRAP_LICENSE_SERVER_URL="$license_server_url"
  return 0
}

request_github_release_url() {
  local bootstrap_enabled="${META_ADS_BOOTSTRAP_FROM_GITHUB:-$(read_config_value BOOTSTRAP_FROM_GITHUB)}"
  local repo="${META_ADS_GITHUB_REPO:-$(read_config_value GITHUB_RELEASE_REPO)}"
  local asset="${META_ADS_GITHUB_SOURCE_ASSET:-$(read_config_value GITHUB_SOURCE_ASSET)}"
  local channel="${META_ADS_GITHUB_RELEASE_CHANNEL:-$(read_config_value GITHUB_RELEASE_CHANNEL)}"

  if [ "$(lower "${bootstrap_enabled:-false}")" != "true" ]; then
    return 42
  fi
  if [ -z "${repo:-}" ] || [ "$repo" = "REPLACE_WITH_GITHUB_REPO" ]; then
    return 42
  fi
  asset="${asset:-MetaAdsAgent-source.zip}"
  channel="${channel:-latest}"
  if [ "$channel" = "latest" ]; then
    GITHUB_RELEASE_URL="https://github.com/$repo/releases/latest/download/$asset"
  else
    GITHUB_RELEASE_URL="https://github.com/$repo/releases/download/$channel/$asset"
  fi
  return 0
}

case "$PLATFORM" in
  mac)
    default_install_dir="${META_ADS_MAC_INSTALL_DIR:-$(read_config_value MAC_INSTALL_DIR)}"
    default_install_dir="${default_install_dir:-$HOME/Applications/Meta Ads Agent}"
    ;;
  linux)
    default_install_dir="${META_ADS_LINUX_INSTALL_DIR:-$(read_config_value LINUX_INSTALL_DIR)}"
    default_install_dir="${default_install_dir:-$HOME/.local/share/meta-ads-agent}"
    ;;
  *)
    echo "Uso: $0 [mac|linux] [destino]"
    exit 1
    ;;
esac

INSTALL_DIR="${2:-$default_install_dir}"

for tool in curl unzip rsync python3; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Necesito '$tool' para instalar la ultima version."
    exit 1
  fi
done

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

DOWNLOAD_URL=""
if request_signed_release_url "$INSTALL_DIR" "$TMP_DIR"; then
  DOWNLOAD_URL="$SIGNED_RELEASE_URL"
elif [ "$?" -eq 42 ]; then
  if [ "$(lower "${ALLOW_GITHUB_FALLBACK:-$(read_config_value ALLOW_GITHUB_FALLBACK)}")" = "true" ] && request_github_release_url; then
    DOWNLOAD_URL="$GITHUB_RELEASE_URL"
  else
    exit 42
  fi
else
  exit 1
fi

download_file "$DOWNLOAD_URL" "$TMP_DIR/source.zip"
validate_zip_archive "$TMP_DIR/source.zip"

mkdir -p "$TMP_DIR/unpack" "$TMP_DIR/keep" "$INSTALL_DIR"
unzip -q "$TMP_DIR/source.zip" -d "$TMP_DIR/unpack"

preserve_paths=(
  ".env"
  "ad-config.json"
  "dashboard/data"
  "brand_guides"
  "logs"
  "output"
)

for rel_path in "${preserve_paths[@]}"; do
  if [ -e "$INSTALL_DIR/$rel_path" ]; then
    mkdir -p "$TMP_DIR/keep/$(dirname "$rel_path")"
    mv "$INSTALL_DIR/$rel_path" "$TMP_DIR/keep/$rel_path"
  fi
done

rsync -a "$TMP_DIR/unpack/" "$INSTALL_DIR/"

for rel_path in "${preserve_paths[@]}"; do
  if [ -e "$TMP_DIR/keep/$rel_path" ]; then
    rm -rf "$INSTALL_DIR/$rel_path"
    mkdir -p "$INSTALL_DIR/$(dirname "$rel_path")"
    mv "$TMP_DIR/keep/$rel_path" "$INSTALL_DIR/$rel_path"
  fi
done

chmod +x "$INSTALL_DIR/Instalar en Mac.command" 2>/dev/null || true
chmod +x "$INSTALL_DIR/Instalar en Linux.sh" 2>/dev/null || true
chmod +x "$INSTALL_DIR/scripts/"*.sh 2>/dev/null || true

echo
echo "Version publicada lista en:"
echo "$INSTALL_DIR"
echo
echo "Preparando tu configuracion local..."
(cd "$INSTALL_DIR" && /usr/bin/env bash ./scripts/install-local.sh)

persist_bootstrap_license_values \
  "$INSTALL_DIR/.env" \
  "${BOOTSTRAP_LICENSE_KEY:-}" \
  "${BOOTSTRAP_BUYER_EMAIL:-}" \
  "${BOOTSTRAP_DEVICE_ID:-}" \
  "${BOOTSTRAP_LICENSE_SERVER_URL:-}"

echo
echo "Construyendo y abriendo el dashboard..."
(cd "$INSTALL_DIR" && /usr/bin/env bash ./scripts/run-docker.sh)
