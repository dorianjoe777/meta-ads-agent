#!/usr/bin/env bash
set -euo pipefail

# Runs only read-only compatibility checks against a designated canary
# container. It never changes a buyer's Meta account, generates images, or
# sends Telegram messages. Use it before declaring an update successful.
CONTAINER="${1:?Usage: $0 <canary-container> [hermes-home]}"
HERMES_HOME_PATH="${2:-/app/dashboard/data/hermes-home}"
# A real model invocation is useful, but must never inherit a buyer session or
# accumulate on a small canary host. A timeout is a failed gate, never a retry.
AGENT_TIMEOUT_SECONDS="${ADMIRA_CANARY_AGENT_TIMEOUT_SECONDS:-45}"

docker exec \
  -e "ADMIRA_CANARY_AGENT_TIMEOUT_SECONDS=$AGENT_TIMEOUT_SECONDS" \
  "$CONTAINER" sh -lc '
  test -x /usr/local/bin/hermes
  test -f /app/src/admira_mcp_server.py
  test -f /app/src/admira_hermes_runtime_patch.py
  HERMES_HOME="'"$HERMES_HOME_PATH"'" hermes mcp test admira

  canary_home=$(mktemp -d)
  canary_log=$(mktemp)
  cleanup() { rm -rf "$canary_home" "$canary_log"; }
  trap cleanup EXIT INT TERM
  for file in config.yaml config.toml .env auth.json; do
    test ! -f "'"$HERMES_HOME_PATH"'"/$file || cp "'"$HERMES_HOME_PATH"'"/$file "$canary_home/$file"
  done
  if ! timeout -k 5 "$ADMIRA_CANARY_AGENT_TIMEOUT_SECONDS" env HERMES_HOME="$canary_home" hermes -z "Reply with exactly CANARY_AGENT_OK. Do not call a tool, read a session, create data, or send a message." --accept-hooks >"$canary_log" 2>&1; then
    echo "CANARY FAILED: bounded Hermes agent smoke did not complete."
    tail -80 "$canary_log"
    exit 1
  fi
  grep -qx "CANARY_AGENT_OK" "$canary_log"
'

echo "CANARY PASS: MCP bridge and isolated, bounded Hermes agent smoke completed without a buyer-facing action."
