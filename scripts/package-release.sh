#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-$(cat "$ROOT_DIR/VERSION")}"
RELEASE_DIR="$ROOT_DIR/release"
BUILD_DIR="$RELEASE_DIR/source-build"
ZIP_STABLE_NAME="MetaAdsAgent-source.zip"
ZIP_VERSIONED_NAME="MetaAdsAgent-${VERSION}-source.zip"
ZIP_LEGACY_NAME="meta-ads-operator-${VERSION}.zip"
STAGING_DIR="$BUILD_DIR/MetaAdsAgent"

# A buyer release must be reproducible from the committed source. Building
# from a dirty tree previously allowed a package to contain fixes that never
# reached Git, so later updates could silently lose them.
if git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if ! git -C "$ROOT_DIR" diff --quiet --ignore-submodules -- || \
     ! git -C "$ROOT_DIR" diff --cached --quiet --ignore-submodules --; then
    echo "Release blocked: tracked source has uncommitted changes. Commit and push the exact release source first." >&2
    exit 1
  fi
  python3 - "$ROOT_DIR" <<'PY'
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
raw = subprocess.check_output(
    ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard", "-z"]
)
allowed_prefixes = (
    "brand_guides/",
    "dashboard/data/",
    "logs/",
    "output/",
    "release/",
    ".vercel/",
)
allowed_names = {".DS_Store"}
unexpected = []
for item in raw.split(b"\0"):
    if not item:
        continue
    path = item.decode("utf-8", errors="replace")
    name = Path(path).name
    if path.startswith(allowed_prefixes) or name in allowed_names or name.endswith((".pyc", ".log")):
        continue
    if "node_modules/" in path or "__pycache__/" in path or ".pytest_cache/" in path:
        continue
    unexpected.append(path)
if unexpected:
    raise SystemExit(
        "Release blocked: untracked source files would enter the package: "
        + ", ".join(unexpected)
    )
PY
fi

mkdir -p "$RELEASE_DIR"
rm -rf "$BUILD_DIR"
mkdir -p "$STAGING_DIR"
rm -f "$RELEASE_DIR/$ZIP_STABLE_NAME" "$RELEASE_DIR/$ZIP_VERSIONED_NAME" "$RELEASE_DIR/$ZIP_LEGACY_NAME"

rsync -a "$ROOT_DIR/" "$STAGING_DIR/" \
  --exclude ".env" \
  --exclude "ad-config.json" \
  --exclude "brand_guides" \
  --exclude ".git" \
  --exclude ".git/*" \
  --exclude "agents.md" \
  --exclude ".vercel" \
  --exclude ".vercel/*" \
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
  --exclude "public/tutorial-meta/*.mp4" \
  --exclude "public/tutorial-meta/*.mov" \
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

python3 - "$STAGING_DIR" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1])
version = (root / "VERSION").read_text(encoding="utf-8").strip()
env_version = ""
for line in (root / ".env.example").read_text(encoding="utf-8").splitlines():
    if line.startswith("META_ADS_AGENT_VERSION="):
        env_version = line.split("=", 1)[1].strip()
        break
if not version or env_version != version:
    raise SystemExit(f"Release blocked: VERSION/.env.example mismatch ({version!r} != {env_version!r})")
required = [
    "dashboard/monitoring-dashboard.py",
    "src/meta_action_metrics.py",
    "src/product_catalog.py",
    "agent/skills/product-catalog-management/SKILL.md",
    "scripts/install-local.sh",
]
missing = [item for item in required if not (root / item).exists()]
if missing:
    raise SystemExit("Release blocked: missing required files: " + ", ".join(missing))
PY

PYTHONPATH="$STAGING_DIR/src" python3 - <<'PY'
from meta_action_metrics import assert_reporting_contract

assert_reporting_contract()
PY

# A release cannot be marked shippable merely because it zips. Verify the
# product-owned MCP transport and its compatibility contract before publishing
# anything to the stable update channel.
PYTHONPATH="$STAGING_DIR/src" python3 "$STAGING_DIR/scripts/release_canary.py"

python3 - "$STAGING_DIR/installer/release-bootstrap.env" <<'PY'
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

(cd "$STAGING_DIR" && zip -qr "$RELEASE_DIR/$ZIP_STABLE_NAME" .)
cp "$RELEASE_DIR/$ZIP_STABLE_NAME" "$RELEASE_DIR/$ZIP_VERSIONED_NAME"
cp "$RELEASE_DIR/$ZIP_STABLE_NAME" "$RELEASE_DIR/$ZIP_LEGACY_NAME"

if command -v sha256sum >/dev/null 2>&1; then
  (cd "$RELEASE_DIR" && sha256sum "$ZIP_STABLE_NAME" "$ZIP_VERSIONED_NAME" "$ZIP_LEGACY_NAME" > "SHA256SUMS.txt")
elif command -v shasum >/dev/null 2>&1; then
  (cd "$RELEASE_DIR" && shasum -a 256 "$ZIP_STABLE_NAME" "$ZIP_VERSIONED_NAME" "$ZIP_LEGACY_NAME" > "SHA256SUMS.txt")
fi

echo "Candidate release ZIPs created (not yet stable; remote canary is still required):"
echo "$RELEASE_DIR/$ZIP_STABLE_NAME"
echo "$RELEASE_DIR/$ZIP_VERSIONED_NAME"
echo "$RELEASE_DIR/$ZIP_LEGACY_NAME"
if [[ -f "$RELEASE_DIR/SHA256SUMS.txt" ]]; then
  echo "$RELEASE_DIR/SHA256SUMS.txt"
fi
