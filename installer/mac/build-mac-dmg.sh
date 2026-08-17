#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MAC_DIR="$ROOT_DIR/installer/mac"
RELEASE_DIR="$ROOT_DIR/release"
VERSION="${1:-1.0.0}"
BUILD_DIR="$RELEASE_DIR/admira-mac-installer-build"
APP_BUNDLE="$BUILD_DIR/Admira IA Installer.app"
APP_CONTENTS="$APP_BUNDLE/Contents"
APP_RESOURCES="$APP_CONTENTS/Resources"
CORE_BUNDLE="$APP_RESOURCES/AdmiraCore.app"
CORE_CONTENTS="$CORE_BUNDLE/Contents"
CORE_RESOURCES="$CORE_CONTENTS/Resources"
SCRIPT_COPY="$BUILD_DIR/AdmiraInstaller-$VERSION.applescript"
DMG_STAGE="$BUILD_DIR/dmg-stage"
DMG_PATH="$RELEASE_DIR/AdmiraIA-Installer-mac-v$VERSION.dmg"
ZIP_PATH="$RELEASE_DIR/AdmiraIA-Installer-mac-v$VERSION.zip"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Este empaquetador debe ejecutarse en macOS." >&2
  exit 1
fi
for tool in osacompile hdiutil rsync clang; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Falta la herramienta requerida: $tool" >&2; exit 1; }
done

mkdir -p "$RELEASE_DIR"
/bin/rm -rf "$BUILD_DIR"
mkdir -p "$DMG_STAGE"

echo "Compilando la interfaz gráfica de instalación…"
# A harmless version property gives each core applet a distinct AppleScript
# identity, so an older installer process cannot swallow a new double-click.
sed "s/^property parent : class \"NSObject\"$/&\nproperty buildVersion : \"$VERSION\"/" \
  "$MAC_DIR/AdmiraInstaller.applescript" > "$SCRIPT_COPY"
mkdir -p "$APP_RESOURCES"
osacompile -s -o "$CORE_BUNDLE" "$SCRIPT_COPY"
mkdir -p "$APP_CONTENTS/MacOS" "$APP_RESOURCES"
cp "$MAC_DIR/admira-mac-engine.sh" "$CORE_RESOURCES/admira-mac-engine.sh"
chmod 755 "$CORE_RESOURCES/admira-mac-engine.sh"
clang -O2 -o "$APP_CONTENTS/MacOS/Launcher" "$MAC_DIR/admira-mac-launcher.m"
chmod 755 "$APP_CONTENTS/MacOS/Launcher"
cp "$CORE_CONTENTS/Info.plist" "$APP_CONTENTS/Info.plist"
set_plist_string() {
  local key="$1" value="$2"
  /usr/bin/plutil -replace "$key" -string "$value" "$APP_CONTENTS/Info.plist" 2>/dev/null || \
    /usr/bin/plutil -insert "$key" -string "$value" "$APP_CONTENTS/Info.plist"
}
set_core_plist_string() {
  local key="$1" value="$2"
  /usr/bin/plutil -replace "$key" -string "$value" "$CORE_CONTENTS/Info.plist" 2>/dev/null || \
    /usr/bin/plutil -insert "$key" -string "$value" "$CORE_CONTENTS/Info.plist"
}
set_core_plist_string CFBundleName "Admira IA Installer"
set_core_plist_string CFBundleDisplayName "Admira IA Installer"
set_plist_string CFBundleExecutable "Launcher"
set_plist_string CFBundleDisplayName "Admira IA Installer"
set_plist_string CFBundleName "Admira IA Installer"
set_plist_string CFBundleIdentifier "lat.uboost.admira.installer.wrapper"
set_plist_string CFBundleShortVersionString "$VERSION"
set_plist_string CFBundleVersion "$VERSION"
set_plist_string LSMinimumSystemVersion "12.0"
/usr/bin/plutil -remove OSAAppletStayOpen "$APP_CONTENTS/Info.plist" 2>/dev/null || true
/usr/bin/plutil -remove CFBundleSignature "$APP_CONTENTS/Info.plist" 2>/dev/null || true

if command -v codesign >/dev/null 2>&1 && [[ -n "${MAC_APP_SIGN_IDENTITY:-}" ]]; then
  codesign --force --deep --options runtime --timestamp --sign "$MAC_APP_SIGN_IDENTITY" "$APP_BUNDLE"
else
  echo "Aviso: la app se empaquetará sin firma de Developer ID. macOS puede pedir confirmación al abrirla."
fi

cat > "$DMG_STAGE/LEEME - Admira IA.txt" <<'README'
ADMIRA IA · INSTALADOR PARA macOS

1. Haz doble clic en «Admira IA Installer.app».
2. Escribe el correo utilizado para comprar Admira IA y tu licencia.
3. La interfaz descargará Docker Desktop oficial, esperará a que esté listo,
   instalará el contenedor y abrirá el dashboard en el navegador.

Si el Mac se reinicia, la instalación continúa automáticamente al iniciar sesión.
Al terminar, se crea «Admira IA Dashboard.webloc» en el Escritorio. Ese archivo
solo abre el dashboard en el navegador; no es una app nativa del dashboard.

Esta versión del instalador aún no está notarizada por Apple. Si macOS la bloquea,
haz clic derecho sobre la app → Abrir → Abrir.
README
cp -R "$APP_BUNDLE" "$DMG_STAGE/"

echo "Creando DMG…"
/bin/rm -f "$DMG_PATH" "$ZIP_PATH"
(cd "$DMG_STAGE" && /usr/bin/zip -qry -X "$ZIP_PATH" .)
/usr/bin/hdiutil create -volname "Admira IA Installer" -srcfolder "$DMG_STAGE" -format UDZO -ov "$DMG_PATH" >/dev/null

if command -v shasum >/dev/null 2>&1; then
  (cd "$RELEASE_DIR" && shasum -a 256 "$(basename "$DMG_PATH")" "$(basename "$ZIP_PATH")" > "AdmiraIA-Installer-mac-v$VERSION.sha256")
fi

echo
echo "Instalador creado:"
echo "  $DMG_PATH"
echo "  $ZIP_PATH"
