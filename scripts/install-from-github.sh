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

BOOTSTRAP_FROM_GITHUB="${META_ADS_BOOTSTRAP_FROM_GITHUB:-$(read_config_value BOOTSTRAP_FROM_GITHUB)}"
GITHUB_RELEASE_REPO="${META_ADS_GITHUB_REPO:-$(read_config_value GITHUB_RELEASE_REPO)}"
GITHUB_SOURCE_ASSET="${META_ADS_GITHUB_SOURCE_ASSET:-$(read_config_value GITHUB_SOURCE_ASSET)}"
GITHUB_RELEASE_CHANNEL="${META_ADS_GITHUB_RELEASE_CHANNEL:-$(read_config_value GITHUB_RELEASE_CHANNEL)}"

if [ "$(lower "${BOOTSTRAP_FROM_GITHUB:-false}")" != "true" ]; then
  exit 42
fi

if [ -z "${GITHUB_RELEASE_REPO:-}" ] || [ "$GITHUB_RELEASE_REPO" = "REPLACE_WITH_GITHUB_REPO" ]; then
  echo "Bootstrap de GitHub no esta configurado en este paquete. Usare la copia incluida."
  exit 42
fi

if [ -z "${GITHUB_SOURCE_ASSET:-}" ]; then
  GITHUB_SOURCE_ASSET="MetaAdsAgent-source.zip"
fi

if [ -z "${GITHUB_RELEASE_CHANNEL:-}" ]; then
  GITHUB_RELEASE_CHANNEL="latest"
fi

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

for tool in curl unzip rsync; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Necesito '$tool' para descargar la version publicada desde GitHub."
    exit 1
  fi
done

if [ "$GITHUB_RELEASE_CHANNEL" = "latest" ]; then
  RELEASE_URL="https://github.com/$GITHUB_RELEASE_REPO/releases/latest/download/$GITHUB_SOURCE_ASSET"
else
  RELEASE_URL="https://github.com/$GITHUB_RELEASE_REPO/releases/download/$GITHUB_RELEASE_CHANNEL/$GITHUB_SOURCE_ASSET"
fi

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

echo "Descargando la ultima version publicada desde GitHub..."
echo "$RELEASE_URL"
curl -fL --retry 3 --connect-timeout 20 "$RELEASE_URL" -o "$TMP_DIR/source.zip"

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
(cd "$INSTALL_DIR" && ./scripts/install-local.sh)

echo
echo "Construyendo y abriendo el dashboard..."
(cd "$INSTALL_DIR" && ./scripts/run-docker.sh)
