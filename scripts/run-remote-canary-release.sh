#!/usr/bin/env bash
set -euo pipefail

# Execute the non-destructive Hermes/MCP canary on the maintained DigitalOcean
# canary installation. Credentials never belong in this script or the repo.
# Usage: ./scripts/run-remote-canary-release.sh root@host ~/.ssh/key container
TARGET="${1:?Usage: $0 <user@host> <identity-file> <container> [hermes-home]}"
IDENTITY_FILE="${2:?Usage: $0 <user@host> <identity-file> <container> [hermes-home]}"
CONTAINER="${3:?Usage: $0 <user@host> <identity-file> <container> [hermes-home]}"
HERMES_HOME_PATH="${4:-/app/runtime/hermes}"
AGENT_TIMEOUT_SECONDS="${ADMIRA_CANARY_AGENT_TIMEOUT_SECONDS:-45}"

ssh -i "$IDENTITY_FILE" \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  -o ConnectTimeout=20 \
  "$TARGET" \
  "docker exec '$CONTAINER' sh -lc '
    test -x /usr/local/bin/hermes && \
    test -f /app/src/admira_mcp_server.py && \
    test -f /app/src/admira_hermes_runtime_patch.py && \
    test -d "$HERMES_HOME_PATH" && \
    test -f "$HERMES_HOME_PATH/.env" && \
    test -f "$HERMES_HOME_PATH/auth.json" && \
    (test -f "$HERMES_HOME_PATH/config.yaml" || test -f "$HERMES_HOME_PATH/config.toml") && \
    export PYTHONPATH=\"/app/src\" && \
    export ADMIRA_HERMES_RUNTIME_PATCHES=1 && \
    HERMES_HOME=\"$HERMES_HOME_PATH\" hermes mcp test admira && \
    canary_home=\$(mktemp -d) && canary_log=\$(mktemp) && \
    cleanup() { rm -rf \"\$canary_home\" \"\$canary_log\"; } && trap cleanup EXIT INT TERM && \
    for file in config.yaml config.toml .env auth.json; do test ! -f \"$HERMES_HOME_PATH/\$file\" || cp \"$HERMES_HOME_PATH/\$file\" \"\$canary_home/\$file\"; done && \
    if ! timeout -k 5 \"$AGENT_TIMEOUT_SECONDS\" env HERMES_HOME=\"\$canary_home\" hermes -z \"Reply with exactly CANARY_AGENT_OK. Do not call a tool, read a session, create data, or send a message.\" --accept-hooks >\"\$canary_log\" 2>&1; then echo \"CANARY FAILED: bounded Hermes agent smoke did not complete.\"; tail -80 \"\$canary_log\"; exit 1; fi && \
    grep -qx \"CANARY_AGENT_OK\" \"\$canary_log\" \
  '"

echo "REMOTE CANARY PASS: candidate MCP bridge and isolated, bounded Hermes agent smoke completed safely."
