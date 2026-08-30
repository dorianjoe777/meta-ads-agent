#!/usr/bin/env bash
set -euo pipefail

# Build the shared-VPS tenant runtime from an immutable Git commit.
#
# This is intentionally separate from scripts/run-docker.sh: the latter is
# the developer/local installer and may build the generic admira-ia image.
# Hosted images use the same committed r91 product source and Dockerfile, but
# have a separate deployment tag/provenance contract. This is a deployment
# variant, not a fork of Admira's product code.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

die() {
  echo "Hosted runtime build blocked: $*" >&2
  exit 1
}

inspect_only=false
if [[ "${1:-}" == "--inspect" ]]; then
  inspect_only=true
elif [[ -n "${1:-}" ]]; then
  die "usage: $0 [--inspect]"
fi

command -v git >/dev/null 2>&1 || die "git is required"
if [[ "$inspect_only" != true ]]; then
  command -v docker >/dev/null 2>&1 || die "docker is required"
fi

git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  || die "source must be inside a Git worktree"

if ! git diff --quiet --ignore-submodules -- || ! git diff --cached --quiet --ignore-submodules --; then
  die "tracked source has uncommitted changes; commit the exact Hosted source first"
fi
untracked="$(git ls-files --others --exclude-standard)"
if [[ -n "$untracked" ]]; then
  die "untracked source files would enter the image: $(printf '%s' "$untracked" | tr '\n' ' ')"
fi

version="$(tr -d '[:space:]' < VERSION)"
[[ "$version" == r91 ]] || die "Hosted r91 builder requires VERSION=r91 (got '$version')"

build_sha="$(git rev-parse HEAD)"
manifest="$(python3 scripts/source_manifest.py --root "$ROOT_DIR")"
[[ "$manifest" =~ ^[0-9a-f]{64}$ ]] || die "source manifest is not a SHA-256 digest"

image_repository="${ADMIRA_HOSTED_IMAGE_REPOSITORY:-admira-ia-hosted}"
[[ "$image_repository" =~ ^[a-z0-9][a-z0-9._/-]*$ ]] \
  || die "invalid ADMIRA_HOSTED_IMAGE_REPOSITORY"
short_sha="${build_sha:0:12}"
channel="canary"
# Deliberately not configurable: a Hosted build is never allowed to become a
# stable image by changing an environment variable or command-line argument.
tag="${version}-canary-${short_sha}"
image="${image_repository}:${tag}"

if [[ "$inspect_only" != true ]]; then
  docker build \
    --file Dockerfile \
    --tag "$image" \
    --label "org.opencontainers.image.variant=hosted-shared-vps" \
    --label "org.opencontainers.image.channel=${channel}" \
    --build-arg "ADMIRA_BUILD_VERSION=${version}" \
    --build-arg "ADMIRA_BUILD_SHA=${build_sha}" \
    --build-arg "ADMIRA_SOURCE_MANIFEST=${manifest}" \
    .

  actual_version="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.version"}}' "$image")"
  actual_sha="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")"
  actual_manifest="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.source-manifest"}}' "$image")"
  actual_variant="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.variant"}}' "$image")"
  actual_channel="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.channel"}}' "$image")"
  [[ "$actual_version" == "$version" ]] || die "image version label mismatch"
  [[ "$actual_sha" == "$build_sha" ]] || die "image revision label mismatch"
  [[ "$actual_manifest" == "$manifest" ]] || die "image source-manifest label mismatch"
  [[ "$actual_variant" == hosted-shared-vps ]] || die "image variant label mismatch"
  [[ "$actual_channel" == canary ]] || die "image channel label mismatch"
fi

if [[ "$inspect_only" == true ]]; then
  echo "Hosted runtime provenance contract inspected (Docker build not run):"
else
  echo "Hosted runtime built and provenance verified:"
fi
echo "  image:    $image"
echo "  version:  $version"
echo "  commit:   $build_sha"
echo "  manifest: $manifest"
echo "  channel:  $channel"
