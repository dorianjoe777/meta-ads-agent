#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MAC_DIR="$ROOT_DIR/installer/mac"
RELEASE_DIR="$ROOT_DIR/release"
VERSION="${1:-1.0.0}"
OUTPUT="$RELEASE_DIR/AdmiraIA-Cloud-Installer-v$VERSION.command"
TEMPLATE="$MAC_DIR/AdmiraIA-Cloud-Installer.command.template"
ENGINE="$MAC_DIR/admira-mac-cloud-engine.sh"

mkdir -p "$RELEASE_DIR"

echo "Empaquetando instalador cloud de terminal…"
/usr/bin/awk '
  /^__ADMIRA_ENGINE_PAYLOAD_BELOW__$/ { exit }
  { print }
' "$TEMPLATE" > "$OUTPUT"
/usr/bin/printf '%s\n' '__ADMIRA_ENGINE_PAYLOAD_BELOW__' >> "$OUTPUT"
/bin/cat "$ENGINE" >> "$OUTPUT"
/usr/bin/printf '%s\n' '__ADMIRA_GATE_PAYLOAD__' >> "$OUTPUT"
/bin/cat "$MAC_DIR/admira-cloud-access-gate.py" >> "$OUTPUT"
/usr/bin/printf '%s\n' '__ADMIRA_RESET_PAYLOAD__' >> "$OUTPUT"
/bin/cat "$MAC_DIR/admira-cloud-clean-reset.sh" >> "$OUTPUT"
/bin/chmod 755 "$OUTPUT"

if command -v shasum >/dev/null 2>&1; then
  (cd "$RELEASE_DIR" && shasum -a 256 "$(basename "$OUTPUT")" > "AdmiraIA-Cloud-Installer-v$VERSION.sha256")
fi

echo "Instalador command creado:"
echo "  $OUTPUT"
