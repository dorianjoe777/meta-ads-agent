#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-v1.0.3}"
RELEASE_DIR="$ROOT_DIR/release"
BUILD_DIR="$RELEASE_DIR/windows-build"
STAGING_DIR="$BUILD_DIR/MetaAdsAgent"
NSI_TEMPLATE="$ROOT_DIR/installer/windows/MetaAdsAgentInstaller.nsi"
NSI_BUILD="$BUILD_DIR/MetaAdsAgentInstaller.generated.nsi"
EXE_PATH="$RELEASE_DIR/MetaAdsAgent-$VERSION-windows.exe"
SOURCE_ZIP="$RELEASE_DIR/MetaAdsAgent-$VERSION-windows-installer-source.zip"

rm -rf "$BUILD_DIR"
mkdir -p "$STAGING_DIR" "$RELEASE_DIR"

rsync -a "$ROOT_DIR/" "$STAGING_DIR/" \
  --exclude ".env" \
  --exclude "ad-config.json" \
  --exclude ".git" \
  --exclude ".DS_Store" \
  --exclude "release" \
  --exclude "seller" \
  --exclude "docs/es-servidor-licencias.md" \
  --exclude "docs/es-cierre-v1-vendible.md" \
  --exclude "docs/marketing-strategy-brief.md" \
  --exclude "docs/product-positioning.md" \
  --exclude "docs/content-creation-system.md" \
  --exclude "docs/keyframe-to-motion-pipeline.md" \
  --exclude "logs" \
  --exclude "output" \
  --exclude "dashboard/data" \
  --exclude "dashboard/content-dashboard.py" \
  --exclude "public/content-keyframes" \
  --exclude "scripts/generate-content-batch.sh" \
  --exclude "scripts/plan-keyframes.sh" \
  --exclude "scripts/render-content-video.mjs" \
  --exclude "scripts/run-content-dashboard.sh" \
  --exclude "src/content_pipeline.py" \
  --exclude "src/keyframe_planner.py" \
  --exclude "src/remotion" \
  --exclude "package.json" \
  --exclude "package-lock.json" \
  --exclude "node_modules" \
  --exclude "*/node_modules" \
  --exclude "__pycache__" \
  --exclude "*/__pycache__" \
  --exclude ".pytest_cache" \
  --exclude "tests/integration_test_results.json" \
  --exclude "*.pyc" \
  --exclude "*.log"

python3 - "$STAGING_DIR/installer/release-bootstrap.env" <<'PY'
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists():
    raise SystemExit(0)

updates = {
    "BOOTSTRAP_PROVIDER": os.environ.get("META_ADS_BOOTSTRAP_PROVIDER", "license_server"),
    "LICENSE_SERVER_URL": os.environ.get("META_ADS_LICENSE_SERVER_URL", "https://admiroia.uboost.lat"),
    "LICENSE_RELEASE_ENDPOINT": os.environ.get("META_ADS_LICENSE_RELEASE_ENDPOINT", "/api/license/release"),
    "RELEASE_CHANNEL": os.environ.get("META_ADS_RELEASE_CHANNEL", "stable"),
    "RELEASE_ASSET_NAME": os.environ.get("META_ADS_RELEASE_ASSET_NAME", "MetaAdsAgent-source.zip"),
    "ALLOW_GITHUB_FALLBACK": os.environ.get("META_ADS_ALLOW_GITHUB_FALLBACK", "false"),
    "BOOTSTRAP_FROM_GITHUB": os.environ.get("META_ADS_BOOTSTRAP_FROM_GITHUB", "false"),
    "GITHUB_RELEASE_REPO": os.environ.get("META_ADS_GITHUB_REPO", "REPLACE_WITH_GITHUB_REPO"),
    "GITHUB_SOURCE_ASSET": os.environ.get("META_ADS_GITHUB_SOURCE_ASSET", "MetaAdsAgent-source.zip"),
    "GITHUB_RELEASE_CHANNEL": os.environ.get("META_ADS_GITHUB_RELEASE_CHANNEL", "latest"),
}
lines = path.read_text(encoding="utf-8").splitlines()
result = []
for line in lines:
    if "=" not in line or line.lstrip().startswith("#"):
        result.append(line)
        continue
    key, _ = line.split("=", 1)
    if key in updates and updates[key]:
        result.append(f"{key}={updates[key]}")
    else:
        result.append(line)
path.write_text("\n".join(result).rstrip() + "\n", encoding="utf-8")
PY

sed \
  -e "s|@@VERSION@@|$VERSION|g" \
  -e "s|@@STAGING_DIR@@|$STAGING_DIR|g" \
  -e "s|@@EXE_PATH@@|$EXE_PATH|g" \
  "$NSI_TEMPLATE" > "$NSI_BUILD"

if command -v makensis >/dev/null 2>&1; then
  makensis "$NSI_BUILD"
  if [[ "${WINDOWS_SIGN_EXE:-false}" == "true" ]]; then
    SIGNTOOL="${WINDOWS_SIGNTOOL_PATH:-}"
    if [[ -z "$SIGNTOOL" ]]; then
      if command -v signtool.exe >/dev/null 2>&1; then
        SIGNTOOL="$(command -v signtool.exe)"
      elif command -v signtool >/dev/null 2>&1; then
        SIGNTOOL="$(command -v signtool)"
      fi
    fi
    if [[ -z "$SIGNTOOL" ]]; then
      echo "WINDOWS_SIGN_EXE=true requiere SignTool del Windows SDK en PATH o WINDOWS_SIGNTOOL_PATH."
      exit 1
    fi

    TIMESTAMP_URL="${WINDOWS_TIMESTAMP_URL:-http://timestamp.digicert.com}"
    SIGN_ARGS=(sign /fd SHA256 /td SHA256 /tr "$TIMESTAMP_URL")
    if [[ -n "${WINDOWS_SIGNING_CERT_PATH:-}" ]]; then
      SIGN_ARGS+=(/f "$WINDOWS_SIGNING_CERT_PATH")
      if [[ -n "${WINDOWS_SIGNING_CERT_PASSWORD:-}" ]]; then
        SIGN_ARGS+=(/p "$WINDOWS_SIGNING_CERT_PASSWORD")
      fi
    else
      SIGN_ARGS+=(/a)
    fi

    "$SIGNTOOL" "${SIGN_ARGS[@]}" "$EXE_PATH"
    "$SIGNTOOL" verify /pa "$EXE_PATH" || true
    echo "EXE firmado con Authenticode."
  else
    echo "Aviso: EXE sin firma. Windows puede mostrar Unknown Publisher o SmartScreen."
  fi
  if command -v shasum >/dev/null 2>&1; then
    (cd "$RELEASE_DIR" && shasum -a 256 "$(basename "$EXE_PATH")" > "$(basename "$EXE_PATH").sha256")
  fi
  echo "EXE creado:"
  echo "$EXE_PATH"
else
  rm -f "$SOURCE_ZIP"
  (cd "$BUILD_DIR" && zip -qr "$SOURCE_ZIP" "MetaAdsAgent" "MetaAdsAgentInstaller.generated.nsi")
  echo "No encontre makensis, asi que no pude compilar el .exe en esta maquina."
  echo
  echo "Deje listo el paquete fuente para Windows:"
  echo "$SOURCE_ZIP"
  echo
  echo "Para crear el .exe instala NSIS y ejecuta:"
  echo "makensis $NSI_BUILD"
fi
