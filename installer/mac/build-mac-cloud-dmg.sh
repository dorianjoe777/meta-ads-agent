#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MAC_DIR="$ROOT_DIR/installer/mac"
RELEASE_DIR="$ROOT_DIR/release"
VERSION="${1:-1.0.0}"
BUILD_DIR="$RELEASE_DIR/admira-mac-cloud-installer-build"
APP_BUNDLE="$BUILD_DIR/Admira IA Cloud Installer.app"
APP_CONTENTS="$APP_BUNDLE/Contents"
APP_RESOURCES="$APP_CONTENTS/Resources"
CORE_BUNDLE="$APP_RESOURCES/AdmiraCore.app"
CORE_CONTENTS="$CORE_BUNDLE/Contents"
SCRIPT_COPY="$BUILD_DIR/AdmiraCloudInstaller-$VERSION.applescript"
DMG_STAGE="$BUILD_DIR/dmg-stage"
DMG_PATH="$RELEASE_DIR/AdmiraIA-CloudInstaller-mac-v$VERSION.dmg"
ZIP_PATH="$RELEASE_DIR/AdmiraIA-CloudInstaller-mac-v$VERSION.zip"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Este empaquetador debe ejecutarse en macOS." >&2
  exit 1
fi
for tool in osacompile hdiutil rsync clang plutil; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Falta la herramienta requerida: $tool" >&2; exit 1; }
done

mkdir -p "$RELEASE_DIR"
/bin/rm -rf "$BUILD_DIR"
mkdir -p "$DMG_STAGE" "$APP_RESOURCES"

echo "Compilando la interfaz gráfica de instalación cloud…"
sed "s/^property buildVersion : .*/property buildVersion : \"$VERSION\"/" \
  "$MAC_DIR/AdmiraCloudInstaller.applescript" > "$SCRIPT_COPY"
osacompile -s -o "$CORE_BUNDLE" "$SCRIPT_COPY"
cp "$MAC_DIR/admira-mac-cloud-engine.sh" "$APP_RESOURCES/admira-mac-cloud-engine.sh"
chmod 755 "$APP_RESOURCES/admira-mac-cloud-engine.sh"
mkdir -p "$APP_RESOURCES/cloud-agent"
cp "$MAC_DIR/admira-cloud-access-gate.py" "$MAC_DIR/admira-cloud-clean-reset.sh" "$APP_RESOURCES/cloud-agent/"
chmod 700 "$APP_RESOURCES/cloud-agent/admira-cloud-access-gate.py" "$APP_RESOURCES/cloud-agent/admira-cloud-clean-reset.sh"
mkdir -p "$APP_CONTENTS/MacOS"
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

set_core_plist_string CFBundleName "Admira IA Cloud Installer"
set_core_plist_string CFBundleDisplayName "Admira IA Cloud Installer"
set_core_plist_string CFBundleIdentifier "lat.uboost.admira.cloud-installer.core.$VERSION"
set_core_plist_string CFBundleShortVersionString "$VERSION"
set_core_plist_string CFBundleVersion "$VERSION"
set_plist_string CFBundleExecutable "Launcher"
set_plist_string CFBundleDisplayName "Admira IA Cloud Installer"
set_plist_string CFBundleName "Admira IA Cloud Installer"
set_plist_string CFBundleIdentifier "lat.uboost.admira.cloud-installer.wrapper.$VERSION"
set_plist_string CFBundleShortVersionString "$VERSION"
set_plist_string CFBundleVersion "$VERSION"
set_plist_string LSMinimumSystemVersion "12.0"
/usr/bin/plutil -remove OSAAppletStayOpen "$APP_CONTENTS/Info.plist" 2>/dev/null || true
/usr/bin/plutil -remove CFBundleSignature "$APP_CONTENTS/Info.plist" 2>/dev/null || true

if command -v codesign >/dev/null 2>&1 && [[ -n "${MAC_APP_SIGN_IDENTITY:-}" ]]; then
  codesign --force --deep --options runtime --timestamp --sign "$MAC_APP_SIGN_IDENTITY" "$APP_BUNDLE"
else
  echo "Aviso: el DMG se empaquetará sin firma de Developer ID. macOS puede pedir confirmación al abrirlo."
fi

cat > "$DMG_STAGE/LEEME - Admira IA Cloud.txt" <<'README'
ADMIRA IA · INSTALADOR CLOUD PARA macOS

1. Abre «Admira IA Cloud Installer.app».
2. Escribe el correo de compra, la licencia y tu token personal de DigitalOcean.
3. Elige el tamaño y la región del Droplet.

La interfaz genera una clave SSH local, valida la licencia, crea el Droplet,
configura el firewall, instala Docker y prepara Admira IA sin abrir Terminal.
Al terminar abre el onboarding en el navegador y crea «Admira IA Dashboard -
correo@cliente.webloc» en el Escritorio, usando el correo de la licencia para
que puedas distinguir varias instalaciones. Ese acceso directo solo abre el
dashboard remoto.

Si el Mac se reinicia durante la instalación, el proceso se reanuda automáticamente
al iniciar sesión y no crea un Droplet duplicado. La clave privada SSH queda en:
~/Library/Application Support/Admira IA/Cloud Installer/keys/

El token de DigitalOcean se guarda temporalmente en el Llavero de macOS y se elimina
al finalizar. El DMG no está notarizado todavía; si macOS lo bloquea, haz clic
derecho sobre la app → Abrir → Abrir.
README
cp -R "$APP_BUNDLE" "$DMG_STAGE/"
ln -s /Applications "$DMG_STAGE/Applications"

echo "Creando DMG…"
/bin/rm -f "$DMG_PATH" "$ZIP_PATH"
(cd "$DMG_STAGE" && /usr/bin/zip -qry -X "$ZIP_PATH" .)
/usr/bin/hdiutil create -volname "Admira IA Cloud Installer" -srcfolder "$DMG_STAGE" -format UDZO -ov "$DMG_PATH" >/dev/null

if command -v shasum >/dev/null 2>&1; then
  (cd "$RELEASE_DIR" && shasum -a 256 "$(basename "$DMG_PATH")" "$(basename "$ZIP_PATH")" > "AdmiraIA-CloudInstaller-mac-v$VERSION.sha256")
fi

echo
echo "Instalador cloud creado:"
echo "  $DMG_PATH"
echo "  $ZIP_PATH"
