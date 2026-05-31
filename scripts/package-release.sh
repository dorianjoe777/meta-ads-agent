#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-v1.0.2}"
RELEASE_DIR="$ROOT_DIR/release"
BUILD_DIR="$RELEASE_DIR/source-build"
ZIP_STABLE_NAME="MetaAdsAgent-source.zip"
ZIP_VERSIONED_NAME="MetaAdsAgent-${VERSION}-source.zip"
ZIP_LEGACY_NAME="meta-ads-operator-${VERSION}.zip"
STAGING_DIR="$BUILD_DIR/MetaAdsAgent"

mkdir -p "$RELEASE_DIR"
rm -rf "$BUILD_DIR"
mkdir -p "$STAGING_DIR"
rm -f "$RELEASE_DIR/$ZIP_STABLE_NAME" "$RELEASE_DIR/$ZIP_VERSIONED_NAME" "$RELEASE_DIR/$ZIP_LEGACY_NAME"

rsync -a "$ROOT_DIR/" "$STAGING_DIR/" \
  --exclude ".env" \
  --exclude "ad-config.json" \
  --exclude ".git" \
  --exclude ".git/*" \
  --exclude ".DS_Store" \
  --exclude "release" \
  --exclude "seller" \
  --exclude "seller/*" \
  --exclude "docs/es-servidor-licencias.md" \
  --exclude "docs/es-cierre-v1-vendible.md" \
  --exclude "docs/marketing-strategy-brief.md" \
  --exclude "docs/product-positioning.md" \
  --exclude "docs/content-creation-system.md" \
  --exclude "docs/keyframe-to-motion-pipeline.md" \
  --exclude "logs" \
  --exclude "logs/*" \
  --exclude "output" \
  --exclude "output/*" \
  --exclude "dashboard/data" \
  --exclude "dashboard/data/*" \
  --exclude "dashboard/data/update-snapshots" \
  --exclude "dashboard/data/update-snapshots/*" \
  --exclude "dashboard/content-dashboard.py" \
  --exclude "public/content-keyframes" \
  --exclude "public/content-keyframes/*" \
  --exclude "scripts/generate-content-batch.sh" \
  --exclude "scripts/plan-keyframes.sh" \
  --exclude "scripts/render-content-video.mjs" \
  --exclude "scripts/run-content-dashboard.sh" \
  --exclude "src/content_pipeline.py" \
  --exclude "src/keyframe_planner.py" \
  --exclude "src/remotion" \
  --exclude "src/remotion/*" \
  --exclude "package.json" \
  --exclude "package-lock.json" \
  --exclude "node_modules" \
  --exclude "node_modules/*" \
  --exclude "*/node_modules" \
  --exclude "*/node_modules/*" \
  --exclude "__pycache__" \
  --exclude "__pycache__/*" \
  --exclude "*/__pycache__" \
  --exclude "*/__pycache__/*" \
  --exclude ".pytest_cache" \
  --exclude ".pytest_cache/*" \
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
    "LICENSE_SERVER_URL": os.environ.get("META_ADS_LICENSE_SERVER_URL", "https://licencias-admiro-ai.uboost.lat"),
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

(cd "$STAGING_DIR" && zip -qr "$RELEASE_DIR/$ZIP_STABLE_NAME" .)
cp "$RELEASE_DIR/$ZIP_STABLE_NAME" "$RELEASE_DIR/$ZIP_VERSIONED_NAME"
cp "$RELEASE_DIR/$ZIP_STABLE_NAME" "$RELEASE_DIR/$ZIP_LEGACY_NAME"

echo "Release ZIPs created:"
echo "$RELEASE_DIR/$ZIP_STABLE_NAME"
echo "$RELEASE_DIR/$ZIP_VERSIONED_NAME"
echo "$RELEASE_DIR/$ZIP_LEGACY_NAME"
