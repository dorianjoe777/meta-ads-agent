#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-$(cat "$ROOT_DIR/VERSION")}"
APP_VERSION="${VERSION#v}"
if [[ ! "$APP_VERSION" =~ ^[0-9]+(\.[0-9]+){0,2}$ ]]; then
  APP_VERSION="1.0.0"
fi
APP_NAME="Admira IA"
BUNDLE_ID="${MAC_APP_BUNDLE_ID:-lat.uboost.admira.metaadsagent}"
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
  --exclude "brand_guides/Offer map.md" \
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
    "LICENSE_SERVER_URL": os.environ.get("META_ADS_LICENSE_SERVER_URL", "https://admiraia.uboost.lat"),
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

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_BUNDLE="$(cd "$APP_ROOT/.." && pwd)"
SOURCE_DIR="$APP_ROOT/Resources/MetaAdsAgent"
INSTALL_DIR="$HOME/Applications/Admira IA"
INSTALLED_APP="$HOME/Applications/Admira IA.app"
DOCKER_APP="/Applications/Docker.app"
DASHBOARD_URL="http://127.0.0.1:7871/"

osascript_alert() {
  local title="$1"
  local message="$2"
  local style="${3:-informational}"
  /usr/bin/osascript -e "display alert \"${title}\" message \"${message}\" as ${style}" >/dev/null 2>&1 || true
}

docker_bin() {
  if command -v docker >/dev/null 2>&1; then
    command -v docker
    return 0
  fi
  if [ -x "$DOCKER_APP/Contents/Resources/bin/docker" ]; then
    printf "%s\n" "$DOCKER_APP/Contents/Resources/bin/docker"
    return 0
  fi
  return 1
}

ensure_docker_ready() {
  local docker_cmd=""
  docker_cmd="$(docker_bin 2>/dev/null || true)"
  if [ -z "$docker_cmd" ]; then
    /usr/bin/osascript <<'APPLESCRIPT' >/dev/null 2>&1 || true
set choice to button returned of (display dialog "Para instalar Admira IA necesitas Docker Desktop. Es gratis para este uso y mantiene el producto aislado en tu Mac." buttons {"Abrir Docker", "Cancelar"} default button "Abrir Docker" cancel button "Cancelar")
if choice is "Abrir Docker" then
  open location "https://www.docker.com/products/docker-desktop/"
end if
APPLESCRIPT
    exit 1
  fi

  if "$docker_cmd" info >/dev/null 2>&1; then
    return 0
  fi

  if [ -d "$DOCKER_APP" ]; then
    open -a Docker >/dev/null 2>&1 || true
    /usr/bin/osascript -e 'display notification "Abriendo Docker Desktop. Puede tardar unos segundos." with title "Admira IA"' >/dev/null 2>&1 || true
    for _ in $(seq 1 75); do
      if "$docker_cmd" info >/dev/null 2>&1; then
        return 0
      fi
      sleep 2
    done
  fi

  osascript_alert "Docker aun no esta listo" "Abre Docker Desktop, espera que diga Running y vuelve a abrir Admira IA." "warning"
  exit 1
}

ensure_docker_ready

if curl -fsS "${DASHBOARD_URL}health" >/dev/null 2>&1 || curl -fsS "$DASHBOARD_URL" >/dev/null 2>&1; then
  open "$DASHBOARD_URL"
  exit 0
fi

mkdir -p "$HOME/Applications"
if [ "$APP_BUNDLE" != "$INSTALLED_APP" ]; then
  rsync -a --delete "$APP_BUNDLE/" "$INSTALLED_APP/" >/dev/null 2>&1 || true
  xattr -dr com.apple.quarantine "$INSTALLED_APP" 2>/dev/null || true
fi

FIRST_INSTALL=false
if [ ! -f "$INSTALL_DIR/docker-compose.yml" ]; then
  FIRST_INSTALL=true
  mkdir -p "$INSTALL_DIR"
  rsync -a "$SOURCE_DIR/" "$INSTALL_DIR/" \
    --exclude ".env" \
    --exclude "ad-config.json" \
    --exclude "dashboard/data" \
    --exclude "logs" \
    --exclude "output" \
    --exclude "release" || {
      osascript -e 'display alert "No pude copiar Admira IA" message "Cierra la app e intentalo otra vez. Si sigue fallando, contacta soporte."'
      exit 1
    }
else
  mkdir -p "$INSTALL_DIR"
fi

chmod +x "$INSTALL_DIR/Instalar en Mac.command" || true
chmod +x "$INSTALL_DIR/scripts/"*.sh || true
xattr -dr com.apple.quarantine "$INSTALL_DIR" 2>/dev/null || true

LOG_DIR="$INSTALL_DIR/logs"
LOG_FILE="$LOG_DIR/mac-docker-launcher.log"
mkdir -p "$LOG_DIR"

{
  echo "==============================================="
  echo "Admira IA Docker launcher"
  date
  echo "Install dir: $INSTALL_DIR"
  echo "==============================================="
} >> "$LOG_FILE"

cd "$INSTALL_DIR"
if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  chmod 600 .env || true
fi
if [ ! -f ad-config.json ] && [ -f ad-config.example.json ]; then
  cp ad-config.example.json ad-config.json
fi
mkdir -p dashboard/data output logs brand_guides/products
if [ ! -f brand_guides/general_branding.md ] && [ -f brand_guides/general_branding.example.md ]; then
  cp brand_guides/general_branding.example.md brand_guides/general_branding.md
fi

/usr/bin/osascript -e 'display notification "Estoy preparando Admira IA dentro de Docker. La primera vez puede tardar varios minutos." with title "Admira IA"' >/dev/null 2>&1 || true

skip_build="true"
if [ "$FIRST_INSTALL" = "true" ]; then
  skip_build="false"
fi
docker_cmd="$(docker_bin 2>/dev/null || true)"
if [ -n "$docker_cmd" ] && ! "$docker_cmd" image inspect meta-ads-agent:local >/dev/null 2>&1; then
  skip_build="false"
fi

if ADMIRA_DOCKER_DETACHED=true ADMIRA_DOCKER_SKIP_BUILD="$skip_build" ./scripts/run-docker.sh >> "$LOG_FILE" 2>&1; then
  for _ in $(seq 1 90); do
    if curl -fsS "${DASHBOARD_URL}health" >/dev/null 2>&1 || curl -fsS "$DASHBOARD_URL" >/dev/null 2>&1; then
      open "$DASHBOARD_URL"
      /usr/bin/osascript -e 'display notification "Dashboard listo. Lo abrí en tu navegador." with title "Admira IA"' >/dev/null 2>&1 || true
      exit 0
    fi
    sleep 2
  done
  open "$DASHBOARD_URL"
  /usr/bin/osascript -e 'display notification "Docker quedó iniciado. Si el navegador tarda, espera unos segundos y recarga." with title "Admira IA"' >/dev/null 2>&1 || true
  exit 0
fi

osascript_alert "No pude iniciar Admira IA" "Docker no pudo completar la instalacion. Voy a abrir la carpeta de logs para soporte." "warning"
open -R "$LOG_FILE" >/dev/null 2>&1 || true
exit 1
LAUNCHER
chmod +x "$APP_MACOS/MetaAdsAgentLauncher"

mkdir -p "$DMG_STAGE/.background"
python3 - "$DMG_STAGE/.background/background.png" <<'PY'
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

out = Path(sys.argv[1])
width, height = 720, 460
img = Image.new("RGB", (width, height), "#11131a")
pixels = img.load()
for y in range(height):
    for x in range(width):
        nx = x / max(width - 1, 1)
        ny = y / max(height - 1, 1)
        r = int(18 + 58 * nx + 32 * (1 - ny))
        g = int(20 + 42 * (1 - nx) + 62 * (1 - ny))
        b = int(28 + 82 * ny + 72 * nx)
        pixels[x, y] = (r, g, b)

glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
gd.ellipse((430, -80, 820, 250), fill=(165, 124, 255, 95))
gd.ellipse((-90, 250, 300, 570), fill=(48, 215, 180, 78))
gd.ellipse((390, 245, 770, 585), fill=(255, 107, 214, 58))
glow = glow.filter(ImageFilter.GaussianBlur(34))
img = Image.alpha_composite(img.convert("RGBA"), glow)
draw = ImageDraw.Draw(img)

def font(size, bold=False):
    candidates = [
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            pass
    return ImageFont.load_default()

title_font = font(34, True)
body_font = font(17)
small_font = font(14)
pill_font = font(15, True)

draw.rounded_rectangle((34, 34, width - 34, height - 34), radius=28, fill=(10, 12, 18, 176), outline=(196, 178, 255, 90), width=2)
draw.rounded_rectangle((56, 62, 106, 112), radius=14, fill=(167, 124, 255, 230))
draw.text((72, 74), "AI", font=font(18, True), fill=(10, 12, 18, 255))
draw.text((124, 62), "Admira IA", font=title_font, fill=(248, 245, 255, 255))
draw.text((124, 101), "Instalador Docker para Meta Ads", font=body_font, fill=(207, 199, 224, 255))

steps = [
    ("1", "Abre Docker Desktop si aun no esta abierto."),
    ("2", "Haz doble clic en Admira IA.app."),
    ("3", "El dashboard se abrira solo en tu navegador."),
]
y = 160
for number, text in steps:
    draw.rounded_rectangle((70, y - 5, 104, y + 29), radius=10, fill=(48, 215, 180, 210))
    draw.text((82, y + 1), number, font=pill_font, fill=(7, 18, 17, 255))
    draw.text((120, y), text, font=body_font, fill=(246, 242, 255, 255))
    y += 54

draw.rounded_rectangle((70, 342, width - 70, 393), radius=16, fill=(255, 255, 255, 24), outline=(255, 255, 255, 42), width=1)
draw.text((92, 354), "No arrastres nada a Aplicaciones. La app se copia sola.", font=small_font, fill=(224, 218, 238, 255))
draw.text((92, 374), "Si ya estaba instalado, solo inicia Docker y abre el dashboard.", font=small_font, fill=(185, 177, 205, 255))

out.parent.mkdir(parents=True, exist_ok=True)
img.convert("RGB").save(out, quality=96)
PY

cat > "$DMG_STAGE/LEEME - DOBLE CLIC.txt" <<'TXT'
Admira IA - Instalador Docker

1. Abre Docker Desktop y espera que diga Running.
2. Haz doble clic en Admira IA.app.
3. La app instala o inicia el contenedor Docker y abre http://127.0.0.1:7871/

No arrastres nada a Aplicaciones. La app se copia sola la primera vez.
Si ya estaba instalado, vuelve a abrir esta app para iniciar Docker y abrir el dashboard.

Si macOS muestra un aviso de seguridad:

1. Abre Configuracion del Sistema.
2. Entra a Privacidad y seguridad.
3. Baja hasta la seccion Seguridad.
4. Haz clic en Abrir de todos modos para Admira IA.
5. Confirma y vuelve a abrir Admira IA.app.

Esto puede pasar porque esta version del launcher de Mac aun no esta firmada por Apple.
Admira IA seguira corriendo dentro de Docker en tu propio equipo.
TXT

if [[ -n "${MAC_APP_SIGN_IDENTITY:-}" ]]; then
  codesign --force --deep --options runtime --timestamp --sign "$MAC_APP_SIGN_IDENTITY" "$APP_BUNDLE"
else
  echo "Aviso: app sin firma. macOS puede mostrar advertencia de desarrollador no verificado."
fi

rm -f "$DMG_PATH"
DMG_RW="$BUILD_DIR/$APP_NAME-rw.dmg"
rm -f "$DMG_RW"
hdiutil create -volname "$APP_NAME" -srcfolder "$DMG_STAGE" -ov -format UDRW "$DMG_RW"

MOUNT_DIR="$BUILD_DIR/mount"
mkdir -p "$MOUNT_DIR"
if hdiutil attach "$DMG_RW" -mountpoint "$MOUNT_DIR" -nobrowse -quiet; then
  SetFile -a V "$MOUNT_DIR/.background" 2>/dev/null || true
  osascript <<APPLESCRIPT >/dev/null 2>&1 || true
tell application "Finder"
  tell disk "$APP_NAME"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {120, 120, 840, 580}
    set viewOptions to the icon view options of container window
    set arrangement of viewOptions to not arranged
    set icon size of viewOptions to 96
    set background picture of viewOptions to file ".background:background.png"
    try
      set position of item "$APP_NAME.app" of container window to {214, 244}
    end try
    try
      set position of item "LEEME - DOBLE CLIC.txt" of container window to {506, 244}
    end try
    close
    open
    update without registering applications
    delay 1
  end tell
end tell
APPLESCRIPT
  sync
  hdiutil detach "$MOUNT_DIR" -quiet || hdiutil detach "$MOUNT_DIR" -force -quiet || true
fi

hdiutil convert "$DMG_RW" -format UDZO -o "$DMG_PATH" -ov >/dev/null

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
