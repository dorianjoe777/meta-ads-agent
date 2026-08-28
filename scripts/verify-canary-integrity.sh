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

# Read only individual non-secret identity keys.  Sourcing the buyer's whole
# .env would execute shell syntax and could leak credentials into this check.
read_dotenv_value() {
  local key="$1"
  local file="$2"
  [[ -f "$file" ]] || return 0
  awk -F= -v wanted="$key" '
    /^[[:space:]]*(#|$)/ { next }
    {
      lhs=$1
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", lhs)
      if (lhs != wanted) { next }
      value=$0
      sub(/^[^=]*=/, "", value)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      if (value ~ /^".*"$/ || value ~ /^'"'"'.*'"'"'$/) {
        value=substr(value, 2, length(value)-2)
      }
      print value
      exit
    }
  ' "$file"
}

version="$(tr -d '[:space:]' < VERSION)"
[[ "$version" =~ ^r[0-9]+$ ]] || die "VERSION must be one canonical rXX value (got '$version')"
env_version="$(sed -n 's/^META_ADS_AGENT_VERSION=//p' .env.example | head -n 1 | tr -d '[:space:]')"
[[ "$env_version" == "$version" ]] || die "VERSION/.env.example mismatch: $version vs $env_version"
commit_sha="$(git rev-parse HEAD)"
git diff --quiet --ignore-submodules -- || die "tracked worktree changes are not committed"
git diff --cached --quiet --ignore-submodules -- || die "staged worktree changes are not committed"
untracked="$(git ls-files --others --exclude-standard)"
[[ -z "$untracked" ]] || die "untracked source files remain: $untracked"
tag_commit="$(git rev-parse --verify --quiet "refs/tags/$version^{commit}" 2>/dev/null || true)"
[[ "$tag_commit" == "$commit_sha" ]] || die "tag '$version' points to '$tag_commit' instead of HEAD '$commit_sha'"

source_manifest="$(python3 scripts/source_manifest.py)"
printf 'CANARY SOURCE: version=%s commit=%s manifest=%s\n' "$version" "$commit_sha" "$source_manifest"

if [[ -z "$CONTAINER" ]]; then
  echo "CANARY INTEGRITY PASS: local tree is clean, tagged, and internally versioned."
  echo "Container/image checks skipped (pass the running container name as argument)."
  exit 0
fi

need docker
docker inspect "$CONTAINER" >/dev/null 2>&1 || die "container not found: $CONTAINER"
configured_project="$(read_dotenv_value ADMIRA_COMPOSE_PROJECT_NAME .env)"
configured_container="$(read_dotenv_value ADMIRA_CONTAINER_NAME .env)"
configured_volume_prefix="$(read_dotenv_value ADMIRA_VOLUME_PREFIX .env)"
configured_project="${configured_project:-admira-ia}"
configured_container="${configured_container:-admira-ia}"
configured_volume_prefix="${configured_volume_prefix:-meta_ads}"
actual_project="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$CONTAINER" 2>/dev/null || true)"
actual_container="$(docker inspect --format '{{.Name}}' "$CONTAINER" 2>/dev/null | sed 's#^/##')"
[[ "$actual_project" == "$configured_project" ]] || die "container Compose project '$actual_project' != configured '$configured_project'"
[[ "$actual_container" == "$configured_container" ]] || die "container name '$actual_container' != configured '$configured_container'"

mount_name_at() {
  local destination="$1"
  # Emit a literal tab from the Go template. A printable delimiter such as
  # " | " is not portable across awk implementations: mawk can parse the
  # expression as a regex and return the delimiter itself instead of `.Name`.
  docker inspect --format '{{range .Mounts}}{{printf "%s\t%s\n" .Destination .Name}}{{end}}' "$CONTAINER" 2>/dev/null \
    | awk -F '\t' -v wanted="$destination" '$1 == wanted { print $2; exit }'
}

while IFS='|' read -r destination suffix; do
  actual_mount="$(mount_name_at "$destination")"
  expected_mount="${configured_volume_prefix}_${suffix}"
  [[ "$actual_mount" == "$expected_mount" ]] || die "mount '$destination' uses '$actual_mount' != configured '$expected_mount'"
done <<'MOUNTS'
/app/runtime|config
/app/dashboard/data|data
/app/dashboard/data/update-snapshots|update_snapshots
/app/output|output
/app/logs|logs
/app/brand_guides|brand_guides
MOUNTS

image="$(docker inspect --format '{{.Config.Image}}' "$CONTAINER")"
[[ -n "$image" ]] || die "container has no image reference"
# The immutable labels below are necessary but not sufficient: Compose can
# accidentally keep an older `ADMIRA_IMAGE_NAME` from `.env`, leaving a
# container on (for example) `admira-ia:r95` while its labels and payload say
# r96.  Require the active image's tag itself to be the source VERSION.  A
# digest suffix is allowed, but an untagged image (or any other tag) is not.
image_without_digest="${image%@*}"
image_leaf="${image_without_digest##*/}"
[[ "$image_leaf" == *:* ]] || die "active image '$image' has no explicit release tag; expected '$version'"
image_tag="${image_leaf##*:}"
[[ "$image_tag" == "$version" ]] || die "active image tag '$image_tag' != source '$version' (image '$image')"
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
container_product_version="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER" | sed -n 's/^META_ADS_AGENT_VERSION=//p' | head -n 1 | tr -d '[:space:]')"
container_build_version="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER" | sed -n 's/^ADMIRA_BUILD_VERSION=//p' | head -n 1 | tr -d '[:space:]')"
container_image_version="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER" | sed -n 's/^ADMIRA_IMAGE_VERSION=//p' | head -n 1 | tr -d '[:space:]')"
[[ "$container_product_version" == "$version" ]] || die "container META_ADS_AGENT_VERSION '$container_product_version' != '$version'"
[[ "$container_build_version" == "$version" ]] || die "container ADMIRA_BUILD_VERSION '$container_build_version' != '$version'"
[[ "$container_image_version" == "$version" ]] || die "container ADMIRA_IMAGE_VERSION '$container_image_version' != '$version'"
# Production images intentionally exclude .git, so the build must persist the
# digest as a tiny immutable provenance file. Do not recompute from the
# container's filesystem: ignored runtime state must never affect the source
# identity.
container_manifest="$(docker exec "$CONTAINER" sh -lc 'tr -d "[:space:]" < /app/source-manifest.sha256' 2>/dev/null || true)"
[[ "$container_manifest" == "$source_manifest" ]] || die "container source manifest '$container_manifest' != '$source_manifest'"
container_revision="$(docker exec "$CONTAINER" sh -lc 'tr -d "[:space:]" < /app/build-commit.sha' 2>/dev/null || true)"
[[ "$container_revision" == "$commit_sha" ]] || die "container build commit '$container_revision' != '$commit_sha'"

printf 'CANARY IMAGE: image=%s tag=%s version=%s revision=%s manifest=%s\n' "$image" "$image_tag" "$image_version" "$image_revision" "$image_manifest"
echo "CANARY INTEGRITY PASS: source, image, and container are one exact build."
