#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEFAULT_DIR="$HOME/Desktop"
if [ ! -d "$DEFAULT_DIR" ]; then
  DEFAULT_DIR="$ROOT_DIR/migration"
fi
mkdir -p "$DEFAULT_DIR"

OUT_FILE="${1:-$DEFAULT_DIR/MetaAdsAgent-migracion-$STAMP.tar.gz}"
TMP_DIR="$(mktemp -d)"
WORK_DIR="$TMP_DIR/MetaAdsAgent-migracion"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mkdir -p "$WORK_DIR"

copy_if_exists() {
  local source="$1"
  local target="$2"
  if [ -e "$source" ]; then
    mkdir -p "$(dirname "$target")"
    cp -R "$source" "$target"
  fi
}

copy_if_exists "$ROOT_DIR/.env" "$WORK_DIR/.env"
copy_if_exists "$ROOT_DIR/ad-config.json" "$WORK_DIR/ad-config.json"
copy_if_exists "$ROOT_DIR/dashboard/data" "$WORK_DIR/dashboard/data"
copy_if_exists "$ROOT_DIR/brand_guides" "$WORK_DIR/brand_guides"
copy_if_exists "$ROOT_DIR/output" "$WORK_DIR/output"

rm -f "$WORK_DIR/dashboard/data/license_unlock.json"
rm -f "$WORK_DIR/dashboard/data/dashboard.html"

if [ -f "$WORK_DIR/.env" ]; then
  python3 - "$WORK_DIR/.env" <<'PY'
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

cat > "$WORK_DIR/LEEME-MIGRACION.txt" <<'TXT'
Este archivo mueve la memoria local de Meta Ads Agent a otro equipo.

Incluye configuracion, historial del chat del dashboard, acciones, aprobaciones,
guias de marca, reportes y archivos generados.

Importante:
- Puede incluir tokens y claves privadas del comprador.
- Guardalo como guardarias una contrasena.
- LICENSE_DEVICE_ID y el desbloqueo cloud no se copian; el nuevo equipo debe validar
  la licencia y, si aplica, confirmar transferencia.
TXT

(cd "$TMP_DIR" && tar -czf "$OUT_FILE" "MetaAdsAgent-migracion")

echo "Respaldo creado:"
echo "$OUT_FILE"
echo
echo "Este archivo contiene datos privados del comprador. Guardalo con cuidado."
