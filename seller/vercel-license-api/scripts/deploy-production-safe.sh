#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET_FILE="$API_ROOT/deployment-target.json"
LINK_FILE="$API_ROOT/.vercel/project.json"
MODE="${1:-deploy}"

EXPECTED_SERVICE="admira-ia-license-api"
EXPECTED_PROJECT_NAME="miro-ai-license-api"
EXPECTED_PROJECT_ID="prj_7EHTqtYTj4V1wxUeFvU5h4gzKqLX"
EXPECTED_ORG_ID="team_1dW3qJzfquT0ONCFYEw2GRE1"
EXPECTED_SCOPE="dorianx"
EXPECTED_DOMAIN="admiraia.uboost.lat"

if [[ "$MODE" != "deploy" && "$MODE" != "--check" ]]; then
  echo "Usage: $0 [--check]" >&2
  exit 2
fi

for command_name in node npm vercel curl; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Deployment blocked: required command '$command_name' is unavailable." >&2
    exit 1
  fi
done

node - "$TARGET_FILE" \
  "$EXPECTED_SERVICE" \
  "$EXPECTED_PROJECT_NAME" \
  "$EXPECTED_PROJECT_ID" \
  "$EXPECTED_ORG_ID" \
  "$EXPECTED_SCOPE" \
  "$EXPECTED_DOMAIN" <<'NODE'
import fs from "node:fs";

const [
  targetPath,
  service,
  projectName,
  projectId,
  orgId,
  scope,
  productionDomain,
] = process.argv.slice(2);
const actual = JSON.parse(fs.readFileSync(targetPath, "utf8"));
const expected = {
  service,
  project_name: projectName,
  project_id: projectId,
  org_id: orgId,
  scope,
  production_domain: productionDomain,
};
for (const [key, value] of Object.entries(expected)) {
  if (actual[key] !== value) {
    throw new Error(
      `Deployment blocked: ${key} is ${JSON.stringify(actual[key])}; expected ${JSON.stringify(value)}.`
    );
  }
}
NODE

# Vercel's local project link is intentionally ignored by Git. Recreate it
# from the reviewed, tracked manifest so a clean checkout cannot auto-link to
# an auxiliary project.
mkdir -p "$(dirname "$LINK_FILE")"
node - "$TARGET_FILE" "$LINK_FILE" <<'NODE'
import fs from "node:fs";

const [targetPath, linkPath] = process.argv.slice(2);
const target = JSON.parse(fs.readFileSync(targetPath, "utf8"));
fs.writeFileSync(
  linkPath,
  `${JSON.stringify(
    {
      projectId: target.project_id,
      orgId: target.org_id,
      projectName: target.project_name,
    },
    null,
    2
  )}\n`
);
NODE

node - "$LINK_FILE" "$EXPECTED_PROJECT_ID" "$EXPECTED_ORG_ID" "$EXPECTED_PROJECT_NAME" <<'NODE'
import fs from "node:fs";

const [linkPath, projectId, orgId, projectName] = process.argv.slice(2);
const link = JSON.parse(fs.readFileSync(linkPath, "utf8"));
if (
  link.projectId !== projectId ||
  link.orgId !== orgId ||
  link.projectName !== projectName
) {
  throw new Error("Deployment blocked: generated Vercel link does not match the locked production target.");
}
NODE

strip_ansi() {
  sed $'s/\033\\[[0-9;]*[[:alpha:]]//g'
}

assert_project_identity() {
  local output_file="$1"
  local plain_file="$2"
  strip_ansi <"$output_file" >"$plain_file"
  if ! grep -Fq "$EXPECTED_PROJECT_NAME" "$plain_file" ||
     ! grep -Fq "$EXPECTED_PROJECT_ID" "$plain_file"; then
    echo "Deployment blocked: Vercel project inspection does not match the locked production project." >&2
    cat "$plain_file" >&2
    exit 1
  fi
}

assert_public_target() {
  local inspect_file="$1"
  local plain_file="$2"
  strip_ansi <"$inspect_file" >"$plain_file"
  if ! grep -Fq "$EXPECTED_PROJECT_NAME" "$plain_file" ||
     ! grep -Fq "production" "$plain_file" ||
     ! grep -Fq "Ready" "$plain_file" ||
     ! grep -Fq "https://$EXPECTED_DOMAIN" "$plain_file"; then
    return 1
  fi
}

verify_health() {
  local health_file="$1"
  curl -fsS "https://$EXPECTED_DOMAIN/api/health" >"$health_file"
  node - "$health_file" "$EXPECTED_SERVICE" <<'NODE'
import fs from "node:fs";

const [healthPath, expectedService] = process.argv.slice(2);
const health = JSON.parse(fs.readFileSync(healthPath, "utf8"));
if (health.ok !== true || health.service !== expectedService) {
  throw new Error(
    `Public health check failed: expected ok=true and service=${expectedService}.`
  );
}
NODE
}

PROJECT_OUTPUT="$(mktemp)"
PROJECT_PLAIN="$(mktemp)"
DOMAIN_OUTPUT="$(mktemp)"
DOMAIN_PLAIN="$(mktemp)"
HEALTH_OUTPUT="$(mktemp)"
trap 'rm -f "$PROJECT_OUTPUT" "$PROJECT_PLAIN" "$DOMAIN_OUTPUT" "$DOMAIN_PLAIN" "$HEALTH_OUTPUT"' EXIT

cd "$API_ROOT"
npm test
vercel project inspect "$EXPECTED_PROJECT_NAME" --scope "$EXPECTED_SCOPE" >"$PROJECT_OUTPUT" 2>&1
assert_project_identity "$PROJECT_OUTPUT" "$PROJECT_PLAIN"

if [[ "$MODE" == "--check" ]]; then
  vercel inspect "https://$EXPECTED_DOMAIN" --scope "$EXPECTED_SCOPE" >"$DOMAIN_OUTPUT" 2>&1
  if ! assert_public_target "$DOMAIN_OUTPUT" "$DOMAIN_PLAIN"; then
    echo "Production verification failed: the public domain is not a Ready production deployment of $EXPECTED_PROJECT_NAME." >&2
    cat "$DOMAIN_PLAIN" >&2
    exit 1
  fi
  verify_health "$HEALTH_OUTPUT"
  echo "Verified: https://$EXPECTED_DOMAIN is served by $EXPECTED_PROJECT_NAME and is healthy."
  exit 0
fi

vercel deploy --prod --yes --scope "$EXPECTED_SCOPE"

# Alias propagation can lag slightly after Vercel reports the deployment ready.
verified=false
for _attempt in 1 2 3 4 5 6; do
  if vercel inspect "https://$EXPECTED_DOMAIN" --scope "$EXPECTED_SCOPE" >"$DOMAIN_OUTPUT" 2>&1 &&
     assert_public_target "$DOMAIN_OUTPUT" "$DOMAIN_PLAIN" &&
     verify_health "$HEALTH_OUTPUT"; then
    verified=true
    break
  fi
  sleep 2
done

if [[ "$verified" != "true" ]]; then
  echo "Deployment verification failed: $EXPECTED_DOMAIN does not resolve to the expected Ready production service." >&2
  [[ -f "$DOMAIN_PLAIN" ]] && cat "$DOMAIN_PLAIN" >&2
  exit 1
fi

echo "Deployed and verified: https://$EXPECTED_DOMAIN -> $EXPECTED_PROJECT_NAME."
