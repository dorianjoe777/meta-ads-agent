#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOUR="${DAILY_AGENT_CRON_HOUR:-8}"
MINUTE="${DAILY_AGENT_CRON_MINUTE:-0}"
CRON_LINE="$MINUTE $HOUR * * * cd \"$ROOT_DIR\" && ./scripts/run-daily-agent.sh >> \"$ROOT_DIR/logs/daily-agent.log\" 2>&1"

mkdir -p "$ROOT_DIR/logs"

TMP_FILE="$(mktemp)"
crontab -l 2>/dev/null | grep -v "run-daily-agent.sh" > "$TMP_FILE" || true
echo "$CRON_LINE" >> "$TMP_FILE"
crontab "$TMP_FILE"
rm -f "$TMP_FILE"

echo "Installed daily cron:"
echo "$CRON_LINE"
echo "Default time is 08:00 local machine time. Override with DAILY_AGENT_CRON_HOUR and DAILY_AGENT_CRON_MINUTE."
