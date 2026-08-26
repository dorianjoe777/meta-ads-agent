#!/usr/bin/env bash
set -euo pipefail

# Final, non-mutating integrity gate for a canary.  It proves that the source
# tree, build metadata, image, and running container all describe one exact
# commit/version/source manifest.  It never builds, restarts, or deploys.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER="${1:-}"
cd "$ROOT_DIR"

die() { echo "CANARY INTEGRITY FAILED: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }
need git
need python3

version="$(tr -d '[:space:]' < VERSION)"
[[ "$version" =~ ^r[0-9]+$ ]] || die "VERSION must be one canonical rXX value (got '$version')"
env_version="$(sed -n 's/^META_ADS_AGENT_VERSION=//p' .env.example | head -n 1 | tr -d '[:space:]')"
[[ "$env_version" == "$version" ]] || die "VERSION/.env.example mismatch: $version vs $env_version"
commit_sha="$(git rev-parse HEAD)"
git diff --quiet --ignore-submodules -- || die "tracked worktree changes are not committed"
git diff --cached --quiet --ignore-submodules -- || die "staged worktree changes are not committed"
untracked="$(git ls-files --others --exclude-standard)"
[[ -z "$untracked" ]] || die "untracked source files remain: $untracked"
git rev-parse --verify --quiet "refs/tags/$version" >/dev/null || die "missing exact version tag: $version"

source_manifest="$(python3 scripts/source_manifest.py)"
printf 'CANARY SOURCE: version=%s commit=%s manifest=%s\n' "$version" "$commit_sha" "$source_manifest"

if [[ -z "$CONTAINER" ]]; then
  echo "CANARY INTEGRITY PASS: local tree is clean, tagged, and internally versioned."
  echo "Container/image checks skipped (pass the running container name as argument)."
  exit 0
fi

need docker
docker inspect "$CONTAINER" >/dev/null 2>&1 || die "container not found: $CONTAINER"
image="$(docker inspect --format '{{.Config.Image}}' "$CONTAINER")"
[[ -n "$image" ]] || die "container has no image reference"
image_version="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.version"}}' "$image" 2>/dev/null || true)"
image_revision="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image" 2>/dev/null || true)"
image_manifest="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.source-manifest"}}' "$image" 2>/dev/null || true)"
[[ "$image_version" == "$version" ]] || die "image version '$image_version' != source '$version'"
[[ "$image_revision" == "$commit_sha" ]] || die "image revision '$image_revision' != source '$commit_sha'"
[[ "$image_manifest" == "$source_manifest" ]] || die "image source manifest '$image_manifest' != source '$source_manifest'"

runtime_version="$(docker exec "$CONTAINER" sh -lc 'tr -d "[:space:]" < /app/VERSION' 2>/dev/null || true)"
[[ "$runtime_version" == "$version" ]] || die "container /app/VERSION '$runtime_version' != '$version'"
runtime_env_version="$(docker exec "$CONTAINER" sh -lc 'sed -n "s/^META_ADS_AGENT_VERSION=//p" /app/.env.example | head -n 1 | tr -d "[:space:]"' 2>/dev/null || true)"
[[ "$runtime_env_version" == "$version" ]] || die "container .env.example version '$runtime_env_version' != '$version'"
# Production images intentionally exclude .git, so the build must persist the
# digest as a tiny immutable provenance file. Do not recompute from the
# container's filesystem: ignored runtime state must never affect the source
# identity.
container_manifest="$(docker exec "$CONTAINER" sh -lc 'tr -d "[:space:]" < /app/source-manifest.sha256' 2>/dev/null || true)"
[[ "$container_manifest" == "$source_manifest" ]] || die "container source manifest '$container_manifest' != '$source_manifest'"

printf 'CANARY IMAGE: image=%s version=%s revision=%s manifest=%s\n' "$image" "$image_version" "$image_revision" "$image_manifest"
echo "CANARY INTEGRITY PASS: source, image, and container are one exact build."
