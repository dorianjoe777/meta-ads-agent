#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_FILE="$HOME/.config/systemd/user/meta-ads-agent-dashboard.service"
TIMER_FILE="$HOME/.config/systemd/user/meta-ads-agent-daily.timer"
DAILY_FILE="$HOME/.config/systemd/user/meta-ads-agent-daily.service"

mkdir -p "$HOME/.config/systemd/user" "$ROOT_DIR/logs"

cat > "$SERVICE_FILE" <<SERVICE
[Unit]
Description=Self-Hosted Meta Ads Agent Dashboard

[Service]
WorkingDirectory=$ROOT_DIR
ExecStart=/usr/bin/env bash $ROOT_DIR/scripts/run-dashboard.sh
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
SERVICE

cat > "$DAILY_FILE" <<SERVICE
[Unit]
Description=Self-Hosted Meta Ads Agent Daily Run

[Service]
Type=oneshot
WorkingDirectory=$ROOT_DIR
ExecStart=/usr/bin/env bash $ROOT_DIR/scripts/run-daily-agent.sh
SERVICE

cat > "$TIMER_FILE" <<TIMER
[Unit]
Description=Run Meta Ads Agent every morning

[Timer]
OnCalendar=*-*-* 08:00:00
Persistent=true
Unit=meta-ads-agent-daily.service

[Install]
WantedBy=timers.target
TIMER

systemctl --user daemon-reload
systemctl --user enable --now meta-ads-agent-dashboard.service
systemctl --user enable --now meta-ads-agent-daily.timer

echo "Installed user services:"
echo "  meta-ads-agent-dashboard.service"
echo "  meta-ads-agent-daily.timer"
echo "  Telegram conversations run inside the dashboard service when enabled."
