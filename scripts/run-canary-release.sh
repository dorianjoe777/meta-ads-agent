#!/usr/bin/env bash
set -euo pipefail

# Runs only read-only compatibility checks against a designated canary
# container. It never changes the buyer's Meta account, generates images, or
# sends Telegram messages. Use it before declaring an update successful.
CONTAINER="${1:?Usage: $0 <canary-container> [hermes-home]}"
HERMES_HOME_PATH="${2:-/app/dashboard/data/hermes-home}"

docker exec "$CONTAINER" sh -lc '
  test -x /usr/local/bin/hermes
  test -f /app/src/admira_mcp_server.py
  test -f /app/src/admira_hermes_runtime_patch.py
  HERMES_HOME="'"$HERMES_HOME_PATH"'" hermes mcp test admira
  HERMES_HOME="'"$HERMES_HOME_PATH"'" hermes -z "Call mcp_admira_preflight_campaign exactly once with empty arguments. Do not create, update, pause, activate, or delete anything. Reply with exactly one Spanish sentence describing the result." --accept-hooks
  HERMES_HOME="'"$HERMES_HOME_PATH"'" hermes -z "Call mcp_admira_codex_image_generate exactly once with empty arguments. Do not generate an image and do not retry. Reply with exactly one Spanish sentence describing the validation result." --accept-hooks
'

echo "CANARY PASS: Hermes consumed both safe Admira MCP calls without a buyer-facing action."
