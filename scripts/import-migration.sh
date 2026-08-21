#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCHIVE="${1:-}"

if [ -z "$ARCHIVE" ]; then
  printf "Ruta del respaldo .tar.gz: "
  IFS= read -r ARCHIVE
fi

if [ ! -f "$ARCHIVE" ]; then
  echo "No encontre el respaldo: $ARCHIVE"
  exit 1
fi

TMP_DIR="$(mktemp -d)"
BACKUP_DIR="$ROOT_DIR/dashboard/data/import-backups/$(date +%Y%m%d-%H%M%S)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mkdir -p "$BACKUP_DIR"
tar -xzf "$ARCHIVE" -C "$TMP_DIR"
SOURCE_DIR="$TMP_DIR/MetaAdsAgent-migracion"

if [ ! -d "$SOURCE_DIR" ]; then
  echo "El archivo no parece ser un respaldo de Meta Ads Agent."
  exit 1
fi

copy_current_if_exists() {
  local source="$1"
  local target="$2"
  if [ -e "$source" ]; then
    mkdir -p "$(dirname "$target")"
    cp -R "$source" "$target"
  fi
}

copy_current_if_exists "$ROOT_DIR/.env" "$BACKUP_DIR/.env"
copy_current_if_exists "$ROOT_DIR/ad-config.json" "$BACKUP_DIR/ad-config.json"
copy_current_if_exists "$ROOT_DIR/dashboard/data" "$BACKUP_DIR/dashboard-data"
copy_current_if_exists "$ROOT_DIR/brand_guides" "$BACKUP_DIR/brand_guides"
copy_current_if_exists "$ROOT_DIR/output" "$BACKUP_DIR/output"

restore_if_exists() {
  local source="$1"
  local target="$2"
  if [ -e "$source" ]; then
    rm -rf "$target"
    mkdir -p "$(dirname "$target")"
    cp -R "$source" "$target"
  fi
}

restore_if_exists "$SOURCE_DIR/.env" "$ROOT_DIR/.env"
restore_if_exists "$SOURCE_DIR/ad-config.json" "$ROOT_DIR/ad-config.json"
restore_if_exists "$SOURCE_DIR/dashboard/data" "$ROOT_DIR/dashboard/data"
restore_if_exists "$SOURCE_DIR/brand_guides" "$ROOT_DIR/brand_guides"
restore_if_exists "$SOURCE_DIR/output" "$ROOT_DIR/output"

rm -f "$ROOT_DIR/dashboard/data/license_unlock.json"
rm -f "$ROOT_DIR/dashboard/data/dashboard.html"

if [ -f "$ROOT_DIR/.env" ]; then
  python3 - "$ROOT_DIR/.env" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
found = False
for index, line in enumerate(lines):
    if line.startswith("LICENSE_DEVICE_ID="):
        lines[index] = "LICENSE_DEVICE_ID="
        found = True
if not found:
    lines.append("LICENSE_DEVICE_ID=")
path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
PY
fi

chmod 700 "$ROOT_DIR/dashboard/data" 2>/dev/null || true
chmod 600 "$ROOT_DIR/.env" 2>/dev/null || true

echo "Datos restaurados."
echo "Respaldo del estado anterior:"
echo "$BACKUP_DIR"
echo
echo "Ahora abre el dashboard y valida la licencia. Si era una licencia Individual en otro equipo, confirma la transferencia."
