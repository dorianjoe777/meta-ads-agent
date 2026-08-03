#!/usr/bin/env bash
set -euo pipefail

# Execute the non-destructive Hermes/MCP canary on the maintained DigitalOcean
# canary installation. Credentials never belong in this script or the repo:
# provide the host and SSH identity at invocation time.
#
# Usage:
#   ./scripts/run-remote-canary-release.sh root@host ~/.ssh/admiro_ai container-name
#
# This is a release gate, not an updater. The target must already run the
# candidate build. It cannot create or change a Meta object, generate media,
# send Telegram messages, or restart the Gateway.
TARGET="${1:?Usage: $0 <user@host> <identity-file> <container> [hermes-home]}"
IDENTITY_FILE="${2:?Usage: $0 <user@host> <identity-file> <container> [hermes-home]}"
CONTAINER="${3:?Usage: $0 <user@host> <identity-file> <container> [hermes-home]}"
HERMES_HOME_PATH="${4:-/app/dashboard/data/hermes-home}"

ssh -i "$IDENTITY_FILE" \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  -o ConnectTimeout=20 \
  "$TARGET" \
  "docker exec '$CONTAINER' sh -lc '\
    test -x /usr/local/bin/hermes && \
    test -f /app/src/admira_mcp_server.py && \
    test -f /app/src/admira_hermes_runtime_patch.py && \
    HERMES_HOME=\"$HERMES_HOME_PATH\" hermes mcp test admira && \
    HERMES_HOME=\"$HERMES_HOME_PATH\" hermes -z \"Call mcp_admira_preflight_campaign exactly once with empty arguments. Do not create, update, pause, activate, or delete anything. Reply with exactly one Spanish sentence describing the result.\" --accept-hooks && \
    HERMES_HOME=\"$HERMES_HOME_PATH\" hermes -z \"Call mcp_admira_codex_image_generate exactly once with empty arguments. Do not generate an image and do not retry. Reply with exactly one Spanish sentence describing the validation result.\" --accept-hooks\
  '"

echo "REMOTE CANARY PASS: candidate Hermes/MCP bridge completed only safe calls."
