#!/usr/bin/env bash
set -euo pipefail

cd /app

mkdir -p /app/runtime/hermes /app/runtime/codex /app/runtime/codex/generated_images /app/dashboard/data/update-snapshots /app/output /app/logs /app/brand_guides/products
chmod 700 /app/runtime /app/runtime/hermes /app/runtime/codex /app/runtime/codex/generated_images /app/dashboard/data /app/dashboard/data/update-snapshots /app/output /app/logs || true

if [ ! -f /app/runtime/.env ]; then
  cp /app/.env.example /app/runtime/.env
  echo "Created persistent runtime .env"
fi

if [ ! -f /app/runtime/ad-config.json ]; then
  cp /app/ad-config.example.json /app/runtime/ad-config.json
  echo "Created persistent ad-config.json"
fi

if [ ! -f /app/brand_guides/general_branding.example.md ] && [ -d /app/brand_guides_seed ]; then
  cp -R /app/brand_guides_seed/. /app/brand_guides/
fi

ln -sf /app/runtime/.env /app/.env
ln -sf /app/runtime/ad-config.json /app/ad-config.json

python3 - <<'PY'
from pathlib import Path
import hashlib
import json
import socket
import uuid

path = Path("/app/runtime/.env")
text = path.read_text(encoding="utf-8")
lines = text.splitlines()
keys = {line.split("=", 1)[0] for line in lines if "=" in line and not line.lstrip().startswith("#")}
defaults = {
    "REQUIRE_DASHBOARD_TOKEN": "true",
    "LIVE_ACTIONS_ENABLED": "false",
    "LAN_ACCESS_ENABLED": "false",
    "CODEX_CREATIVE_ENABLED": "true",
    "CODEX_CLI": "codex",
    "CODEX_HOME": "/app/runtime/codex",
    "HERMES_HOME": "/app/runtime/hermes",
    "TELEGRAM_AGENT_MODE": "hermes_gateway",
    "HERMES_STATUS_TIMEOUT_SECONDS": "20",
    "HERMES_RESPONSE_TIMEOUT_SECONDS": "300",
    "HERMES_TIMEOUT_SECONDS": "300",
    "DAILY_BRIEF_TIME": "08:00",
    "DAILY_BRIEF_TIMEZONE": "UTC",
    "HERMES_ENABLED_TOOLSETS": "memory,skills,session_search,vision,file,web,browser",
    "HERMES_DISABLED_TOOLSETS": "terminal,code_execution,image_gen",
}
forced = {
    "DASHBOARD_HOST": "0.0.0.0",
    "DASHBOARD_PORT": "7871",
    "ALLOW_PUBLIC_DASHBOARD": "true",
}
for key, value in forced.items():
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[index] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")
keys = {line.split("=", 1)[0] for line in lines if "=" in line and not line.lstrip().startswith("#")}
for key, value in defaults.items():
    replaced_blank = False
    for index, line in enumerate(lines):
        if line.startswith(f"{key}=") and not line.split("=", 1)[1].strip():
            lines[index] = f"{key}={value}"
            replaced_blank = True
            break
    if key not in keys and not replaced_blank:
        lines.append(f"{key}={value}")
for index, line in enumerate(lines):
    if line.startswith("HERMES_ENABLED_TOOLSETS=") and "image_gen" in line:
        toolsets = [item for item in line.split("=", 1)[1].split(",") if item and item != "image_gen"]
        lines[index] = "HERMES_ENABLED_TOOLSETS=" + ",".join(toolsets)
    if line.startswith("HERMES_DISABLED_TOOLSETS=") and "image_gen" not in line:
        disabled = [item for item in line.split("=", 1)[1].split(",") if item]
        disabled.append("image_gen")
        lines[index] = "HERMES_DISABLED_TOOLSETS=" + ",".join(disabled)
if "LICENSE_DEVICE_ID" not in keys:
    unlock_path = Path("/app/dashboard/data/license_unlock.json")
    try:
        unlock = json.loads(unlock_path.read_text(encoding="utf-8")) if unlock_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        unlock = {}
    device_id = str(unlock.get("device_id") or "").strip()
    if not device_id:
        device_id = hashlib.sha256(f"{socket.gethostname()}:{uuid.getnode()}".encode("utf-8")).hexdigest()[:24]
    lines.append(f"LICENSE_DEVICE_ID={device_id}")
path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
PY

echo "Checking runtime tools..."
python3 --version
node --version
npm --version
codex --version || echo "Codex CLI is installed but not authenticated/configured yet."

exec python3 dashboard/monitoring-dashboard.py
