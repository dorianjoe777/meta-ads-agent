#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-$(cat "$ROOT_DIR/VERSION")}"
RELEASE_DIR="$ROOT_DIR/release"
BUILD_DIR="$RELEASE_DIR/windows-cloud-build"
STAGING_DIR="$BUILD_DIR/AdmiraCloudInstaller"
TEMPLATE="$ROOT_DIR/installer/windows/AdmiraCloudInstaller.nsi"
GENERATED="$BUILD_DIR/AdmiraCloudInstaller.generated.nsi"
EXE_PATH="$RELEASE_DIR/AdmiraIA-CloudInstaller-$VERSION-windows.exe"

rm -rf "$BUILD_DIR"
mkdir -p "$STAGING_DIR" "$RELEASE_DIR"
rsync -a "$ROOT_DIR/" "$STAGING_DIR/" \
  --exclude ".env" --exclude "ad-config.json" --exclude ".git" --exclude "release" \
  --exclude "dashboard/data" --exclude "logs" --exclude "output" --exclude "seller" \
  --exclude "node_modules" --exclude "*/node_modules" \
  --exclude "installer/local-gui/AdmiraIA-Installer.exe" \
  --exclude "installer/local-gui/gui/bin" --exclude "installer/local-gui/gui/obj" \
  --exclude "__pycache__" --exclude "*/__pycache__" \
  --exclude "*.pyc" --exclude "*.log"

sed -e "s|@@VERSION@@|$VERSION|g" -e "s|@@STAGING_DIR@@|$STAGING_DIR|g" -e "s|@@EXE_PATH@@|$EXE_PATH|g" "$TEMPLATE" > "$GENERATED"

if ! command -v makensis >/dev/null 2>&1; then
  echo "NSIS no está instalado. Paquete fuente listo en $STAGING_DIR"
  exit 2
fi
makensis "$GENERATED"
if command -v shasum >/dev/null 2>&1; then
  (cd "$RELEASE_DIR" && shasum -a 256 "$(basename "$EXE_PATH")" > "$(basename "$EXE_PATH").sha256")
fi
echo "$EXE_PATH"
