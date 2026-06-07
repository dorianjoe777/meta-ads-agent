#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-$(cat "$ROOT_DIR/VERSION")}"
APP_VERSION="${VERSION#v}"
if [[ ! "$APP_VERSION" =~ ^[0-9]+(\.[0-9]+){0,2}$ ]]; then
  APP_VERSION="1.0.0"
fi
APP_NAME="Meta Ads Agent"
BUNDLE_ID="${MAC_APP_BUNDLE_ID:-lat.uboost.admiro.metaadsagent}"
RELEASE_DIR="$ROOT_DIR/release"
BUILD_DIR="$RELEASE_DIR/dmg-build"
DMG_STAGE="$BUILD_DIR/dmg-stage"
APP_BUNDLE="$DMG_STAGE/$APP_NAME.app"
APP_CONTENTS="$APP_BUNDLE/Contents"
APP_MACOS="$APP_CONTENTS/MacOS"
APP_RESOURCES="$APP_CONTENTS/Resources"
APP_PAYLOAD="$APP_RESOURCES/MetaAdsAgent"
DMG_PATH="$RELEASE_DIR/MetaAdsAgent-$VERSION-mac.dmg"

if ! command -v hdiutil >/dev/null 2>&1; then
  echo "No encontre hdiutil. Este script debe correrse en macOS."
  exit 1
fi

rm -rf "$BUILD_DIR"
mkdir -p "$APP_MACOS" "$APP_PAYLOAD" "$RELEASE_DIR"

rsync -a "$ROOT_DIR/" "$APP_PAYLOAD/" \
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

python3 - "$APP_PAYLOAD/installer/release-bootstrap.env" <<'PY'
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

chmod +x "$APP_PAYLOAD/Instalar en Mac.command" || true
chmod +x "$APP_PAYLOAD/Instalar en Linux.sh" || true
chmod +x "$APP_PAYLOAD/scripts/"*.sh || true

cat > "$APP_CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>es</string>
  <key>CFBundleDisplayName</key>
  <string>$APP_NAME</string>
  <key>CFBundleExecutable</key>
  <string>MetaAdsAgentLauncher</string>
  <key>CFBundleIdentifier</key>
  <string>$BUNDLE_ID</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>$APP_NAME</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>$APP_VERSION</string>
  <key>CFBundleVersion</key>
  <string>$APP_VERSION</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

cat > "$APP_MACOS/MetaAdsAgentLauncher" <<'LAUNCHER'
#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_DIR="$APP_ROOT/Resources/MetaAdsAgent"
INSTALL_DIR="$HOME/Applications/Meta Ads Agent"

mkdir -p "$INSTALL_DIR"
rsync -a "$SOURCE_DIR/" "$INSTALL_DIR/" \
  --exclude ".env" \
  --exclude "ad-config.json" \
  --exclude "dashboard/data" \
  --exclude "logs" \
  --exclude "output" \
  --exclude "release" || {
    osascript -e 'display alert "No pude copiar Meta Ads Agent" message "Cierra la app e intentalo otra vez. Si sigue fallando, contacta soporte."'
    exit 1
  }

chmod +x "$INSTALL_DIR/Instalar en Mac.command" || true
chmod +x "$INSTALL_DIR/scripts/"*.sh || true
xattr -dr com.apple.quarantine "$INSTALL_DIR" 2>/dev/null || true
open -a Terminal "$INSTALL_DIR/Instalar en Mac.command"
LAUNCHER
chmod +x "$APP_MACOS/MetaAdsAgentLauncher"

ln -s /Applications "$DMG_STAGE/Applications"

if [[ -n "${MAC_APP_SIGN_IDENTITY:-}" ]]; then
  codesign --force --deep --options runtime --timestamp --sign "$MAC_APP_SIGN_IDENTITY" "$APP_BUNDLE"
else
  echo "Aviso: app sin firma. macOS puede mostrar advertencia de desarrollador no verificado."
fi

rm -f "$DMG_PATH"
hdiutil create -volname "$APP_NAME" -srcfolder "$DMG_STAGE" -ov -format UDZO "$DMG_PATH"

if [[ -n "${MAC_DMG_SIGN_IDENTITY:-}" ]]; then
  codesign --force --timestamp --sign "$MAC_DMG_SIGN_IDENTITY" "$DMG_PATH"
elif [[ -n "${MAC_APP_SIGN_IDENTITY:-}" ]]; then
  codesign --force --timestamp --sign "$MAC_APP_SIGN_IDENTITY" "$DMG_PATH"
fi

if [[ "${MAC_NOTARIZE:-false}" == "true" ]]; then
  if [[ -z "${MAC_APP_SIGN_IDENTITY:-}" ]]; then
    echo "MAC_NOTARIZE=true requiere MAC_APP_SIGN_IDENTITY con certificado Developer ID Application."
    exit 1
  fi
  if ! command -v xcrun >/dev/null 2>&1; then
    echo "No encontre xcrun. Instala Xcode Command Line Tools para notarizar."
    exit 1
  fi

  NOTARY_ARGS=(notarytool submit "$DMG_PATH" --wait)
  if [[ -n "${APPLE_NOTARY_KEYCHAIN_PROFILE:-}" ]]; then
    NOTARY_ARGS+=(--keychain-profile "$APPLE_NOTARY_KEYCHAIN_PROFILE")
  else
    if [[ -z "${APPLE_ID:-}" || -z "${APPLE_TEAM_ID:-}" || -z "${APPLE_APP_SPECIFIC_PASSWORD:-}" ]]; then
      echo "Para notarizar define APPLE_NOTARY_KEYCHAIN_PROFILE o APPLE_ID, APPLE_TEAM_ID y APPLE_APP_SPECIFIC_PASSWORD."
      exit 1
    fi
    NOTARY_ARGS+=(--apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_SPECIFIC_PASSWORD")
  fi

  xcrun "${NOTARY_ARGS[@]}"
  xcrun stapler staple "$DMG_PATH"
  xcrun stapler validate "$DMG_PATH" || true
fi

if command -v shasum >/dev/null 2>&1; then
  (cd "$RELEASE_DIR" && shasum -a 256 "$(basename "$DMG_PATH")" > "$(basename "$DMG_PATH").sha256")
fi

echo "DMG creado:"
echo "$DMG_PATH"
if [[ -n "${MAC_APP_SIGN_IDENTITY:-}" ]]; then
  echo "App firmada con: $MAC_APP_SIGN_IDENTITY"
fi
if [[ "${MAC_NOTARIZE:-false}" == "true" ]]; then
  echo "DMG notarizado y stapled por Apple."
fi
