#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-v1.0.2}"
RELEASE_DIR="$ROOT_DIR/release"
BUILD_DIR="$RELEASE_DIR/windows-msi-build"
STAGING_DIR="$BUILD_DIR/MetaAdsAgent"
WXS_BUILD="$BUILD_DIR/MetaAdsAgentInstaller.generated.wxs"
MSI_PATH="$RELEASE_DIR/MetaAdsAgent-$VERSION-windows.msi"
SOURCE_ZIP="$RELEASE_DIR/MetaAdsAgent-$VERSION-windows-msi-source.zip"
MANUFACTURER="${WINDOWS_MSI_MANUFACTURER:-Admiro AI}"
UPGRADE_CODE="${WINDOWS_MSI_UPGRADE_CODE:-7B24A49C-5E95-4C16-9C32-86E58A90B2D7}"

MSI_VERSION="$(python3 - "$VERSION" <<'PY'
import re
import sys

raw = sys.argv[1].lstrip("vV")
parts = re.findall(r"\d+", raw)
parts = (parts + ["0", "0"])[:3]
print(".".join(parts))
PY
)"

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

python3 - "$STAGING_DIR" "$WXS_BUILD" "$MSI_VERSION" "$MANUFACTURER" "$UPGRADE_CODE" <<'PY'
import hashlib
import sys
import xml.sax.saxutils as sax
from pathlib import Path

source = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2])
version = sys.argv[3]
manufacturer = sys.argv[4]
upgrade_code = sys.argv[5]

def esc(value):
    return sax.escape(str(value), {'"': '&quot;'})

def safe_id(prefix, value):
    digest = hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:16].upper()
    return f"{prefix}_{digest}"

directories = {}
components = []

def emit_directory(path, indent="        "):
    rel = path.relative_to(source)
    if rel.parts:
        directory_id = safe_id("DIR", rel.as_posix())
    else:
        directory_id = "INSTALLFOLDER"
    lines = []
    if rel.parts:
        lines.append(f'{indent}<Directory Id="{directory_id}" Name="{esc(path.name)}">')
    else:
        lines.append(f'{indent}<Directory Id="INSTALLFOLDER" Name="Meta Ads Agent">')

    for child in sorted([p for p in path.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
        lines.extend(emit_directory(child, indent + "  "))
    for file_path in sorted([p for p in path.iterdir() if p.is_file()], key=lambda p: p.name.lower()):
        rel_file = file_path.relative_to(source).as_posix()
        source_ref = "MetaAdsAgent\\" + rel_file.replace("/", "\\")
        component_id = safe_id("CMP", rel_file)
        file_id = safe_id("FIL", rel_file)
        components.append(component_id)
        lines.append(f'{indent}  <Component Id="{component_id}" Guid="*">')
        lines.append(f'{indent}    <File Id="{file_id}" Source="{esc(source_ref)}" KeyPath="yes" />')
        lines.append(f'{indent}  </Component>')

    lines.append(f"{indent}</Directory>")
    return lines

directory_xml = "\n".join(emit_directory(source))
component_refs = "\n".join(f'      <ComponentRef Id="{component_id}" />' for component_id in components)

out.write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="*" Name="Meta Ads Agent" Language="1033" Version="{esc(version)}" Manufacturer="{esc(manufacturer)}" UpgradeCode="{esc(upgrade_code)}">
    <Package InstallerVersion="500" Compressed="yes" InstallScope="perUser" />
    <MajorUpgrade DowngradeErrorMessage="Ya hay una version mas nueva de Meta Ads Agent instalada." />
    <MediaTemplate EmbedCab="yes" />
    <Directory Id="TARGETDIR" Name="SourceDir">
      <Directory Id="LocalAppDataFolder">
{directory_xml}
      </Directory>
      <Directory Id="DesktopFolder" />
      <Directory Id="ProgramMenuFolder" />
    </Directory>
    <DirectoryRef Id="INSTALLFOLDER">
      <Component Id="Shortcuts" Guid="*">
        <Shortcut Id="DesktopShortcut" Directory="DesktopFolder" Name="Meta Ads Agent" Target="[INSTALLFOLDER]Instalar en Windows.bat" WorkingDirectory="INSTALLFOLDER" />
        <Shortcut Id="StartMenuShortcut" Directory="ProgramMenuFolder" Name="Meta Ads Agent" Target="[INSTALLFOLDER]Instalar en Windows.bat" WorkingDirectory="INSTALLFOLDER" />
        <RegistryValue Root="HKCU" Key="Software\\Admiro AI\\Meta Ads Agent" Name="installed" Type="integer" Value="1" KeyPath="yes" />
      </Component>
    </DirectoryRef>
    <Feature Id="MainFeature" Title="Meta Ads Agent" Level="1">
{component_refs}
      <ComponentRef Id="Shortcuts" />
    </Feature>
  </Product>
</Wix>
''', encoding="utf-8")
PY

sign_windows_file() {
  local target="$1"
  SIGNTOOL="${WINDOWS_SIGNTOOL_PATH:-}"
  if [[ -z "$SIGNTOOL" ]]; then
    if command -v signtool.exe >/dev/null 2>&1; then
      SIGNTOOL="$(command -v signtool.exe)"
    elif command -v signtool >/dev/null 2>&1; then
      SIGNTOOL="$(command -v signtool)"
    fi
  fi
  if [[ -z "$SIGNTOOL" ]]; then
    echo "WINDOWS_SIGN_MSI=true requiere SignTool del Windows SDK en PATH o WINDOWS_SIGNTOOL_PATH."
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

  "$SIGNTOOL" "${SIGN_ARGS[@]}" "$target"
  "$SIGNTOOL" verify /pa "$target" || true
}

if command -v candle.exe >/dev/null 2>&1 && command -v light.exe >/dev/null 2>&1; then
  candle.exe -nologo -out "$BUILD_DIR/MetaAdsAgentInstaller.wixobj" "$WXS_BUILD"
  light.exe -nologo -out "$MSI_PATH" "$BUILD_DIR/MetaAdsAgentInstaller.wixobj"
elif command -v candle >/dev/null 2>&1 && command -v light >/dev/null 2>&1; then
  candle -nologo -out "$BUILD_DIR/MetaAdsAgentInstaller.wixobj" "$WXS_BUILD"
  light -nologo -out "$MSI_PATH" "$BUILD_DIR/MetaAdsAgentInstaller.wixobj"
else
  rm -f "$SOURCE_ZIP"
  (cd "$BUILD_DIR" && zip -qr "$SOURCE_ZIP" "MetaAdsAgent" "MetaAdsAgentInstaller.generated.wxs")
  echo "No encontre WiX Toolset (candle/light), asi que no pude compilar el .msi en esta maquina."
  echo
  echo "Deje listo el paquete fuente para Windows MSI:"
  echo "$SOURCE_ZIP"
  echo
  echo "Para crear el .msi instala WiX Toolset y ejecuta:"
  echo "candle MetaAdsAgentInstaller.generated.wxs && light -out MetaAdsAgent-$VERSION-windows.msi MetaAdsAgentInstaller.wixobj"
  exit 0
fi

if [[ "${WINDOWS_SIGN_MSI:-false}" == "true" || "${WINDOWS_SIGN_EXE:-false}" == "true" ]]; then
  sign_windows_file "$MSI_PATH"
  echo "MSI firmado con Authenticode."
else
  echo "Aviso: MSI sin firma. Windows puede mostrar Unknown Publisher o SmartScreen."
fi

if command -v shasum >/dev/null 2>&1; then
  (cd "$RELEASE_DIR" && shasum -a 256 "$(basename "$MSI_PATH")" > "$(basename "$MSI_PATH").sha256")
fi

echo "MSI creado:"
echo "$MSI_PATH"
