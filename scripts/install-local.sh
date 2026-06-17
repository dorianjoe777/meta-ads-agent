#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Self-Hosted Meta Ads Agent installer"
echo "Project: $ROOT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required. Install Python 3.10+ and rerun this script."
  exit 1
fi

mkdir -p dashboard/data output logs
chmod 700 dashboard/data output logs

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
else
  echo ".env already exists; leaving it unchanged"
fi
python3 - <<'PY'
from pathlib import Path

path = Path(".env")
text = path.read_text(encoding="utf-8") if path.exists() else ""
defaults = {
    "REQUIRE_DASHBOARD_TOKEN": "true",
    "ALLOW_PUBLIC_DASHBOARD": "false",
    "LAN_ACCESS_ENABLED": "false",
    "LIVE_ACTIONS_ENABLED": "false",
    "LICENSE_KEY": "",
    "LICENSE_BUYER_EMAIL": "",
    "LICENSE_SERVER_URL": "",
    "LICENSE_DEVICE_ID": "",
    "LICENSE_GRACE_HOURS": "72",
    "LICENSE_REQUIRED_FOR_LIVE": "true",
    "LICENSE_PUBLIC_KEY": "",
    "TELEGRAM_AGENT_ENABLED": "false",
    "TELEGRAM_AGENT_MODE": "hermes_gateway",
    "TELEGRAM_LANGUAGE": "es",
    "TELEGRAM_POLL_TIMEOUT": "25",
    "AGENT_PROFILE_DIR": "agent",
    "AGENT_CHAT_PROVIDER": "hermes",
    "HERMES_CLI": "hermes",
    "HERMES_HOME": "dashboard/data/hermes-home",
    "HERMES_MODEL": "",
    "HERMES_STATUS_TIMEOUT_SECONDS": "20",
    "HERMES_RESPONSE_TIMEOUT_SECONDS": "300",
    "HERMES_TIMEOUT_SECONDS": "300",
    "HERMES_MAX_ITERATIONS": "12",
    "HERMES_ENABLED_TOOLSETS": "memory,skills,session_search,vision,file,web,browser",
    "HERMES_DISABLED_TOOLSETS": "terminal,code_execution,image_gen",
    "HERMES_USE_PYTHON_LIBRARY": "true",
    "MINIMAX_BASE_URL": "https://api.minimax.io/v1",
    "MINIMAX_API": "openai-completions",
    "MINIMAX_MODEL": "MiniMax-M2.7",
    "AGENT_CHAT_TEMPERATURE": "0.65",
    "CODEX_CREATIVE_ENABLED": "true",
    "CODEX_CLI": "codex",
}
lines = text.splitlines()
keys = {line.split("=", 1)[0] for line in lines if "=" in line and not line.lstrip().startswith("#")}
for key, value in defaults.items():
    if key not in keys:
        lines.append(f"{key}={value}")
if "DASHBOARD_PASSWORD" not in keys:
    lines.append("DASHBOARD_PASSWORD=")
if "LICENSE_DEVICE_ID=" in "\n".join(lines):
    import hashlib, socket, uuid
    device_id = hashlib.sha256(f"{socket.gethostname()}:{uuid.getnode()}".encode("utf-8")).hexdigest()[:24]
    lines = [f"LICENSE_DEVICE_ID={device_id}" if line == "LICENSE_DEVICE_ID=" else line for line in lines]
path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
PY
chmod 600 .env
echo "Secured .env. The buyer creates their dashboard password during onboarding."

if [ ! -f ad-config.json ]; then
  cp ad-config.example.json ad-config.json
  echo "Created ad-config.json from ad-config.example.json"
else
  echo "ad-config.json already exists; leaving it unchanged"
fi

mkdir -p brand_guides/products
if [ ! -f brand_guides/general_branding.md ] && [ -f brand_guides/general_branding.example.md ]; then
  cp brand_guides/general_branding.example.md brand_guides/general_branding.md
  echo "Created brand_guides/general_branding.md"
fi

if command -v codex >/dev/null 2>&1; then
  echo "Codex CLI found: $(command -v codex)"
else
  echo "Codex CLI was not found."
  echo "Creative strategy still works with saved brand guides, but Codex-powered plans and image prompts need Codex CLI configured."
  if [ "${INSTALL_CODEX_CLI:-false}" = "true" ] && command -v npm >/dev/null 2>&1; then
    echo "INSTALL_CODEX_CLI=true detected; attempting Codex CLI install with npm."
    npm install -g @openai/codex || echo "Codex CLI install failed. Install it manually after setup."
  fi
fi

if command -v hermes >/dev/null 2>&1; then
  echo "Hermes Agent found: $(command -v hermes)"
else
  echo "Hermes Agent was not found."
  echo "Attempting to install Hermes Agent so the manager can use ChatGPT/Codex OAuth through Hermes."
  python3 -m pip install --user "mcp>=1.0.0" "python-telegram-bot>=21,<22" "git+https://github.com/NousResearch/hermes-agent.git" || echo "Hermes install failed. Install it manually, then run: hermes model"
fi

python3 - <<'PY' || python3 -m pip install --user "mcp>=1.0.0" "python-telegram-bot>=21,<22" || echo "MCP/Telegram package install failed. Hermes Telegram tools may need: python3 -m pip install --user mcp python-telegram-bot"
import importlib.util
required = ("mcp", "telegram")
raise SystemExit(0 if all(importlib.util.find_spec(name) for name in required) else 1)
PY

python3 -m py_compile src/daily_agent.py dashboard/monitoring-dashboard.py

if command -v social >/dev/null 2>&1; then
  echo "social-cli found: $(command -v social)"
else
  echo "social-cli was not found. Con supervision remains available after you connect Meta."
  echo "Para conectar Meta con datos reales, instala/configura social-cli y ejecuta: social auth login"
fi

echo
echo "Install complete."
echo "Next:"
echo "  1. Edit .env"
echo "  2. Run hermes model and choose OpenAI Codex to use the buyer's ChatGPT subscription"
echo "  3. Run ./scripts/run-dashboard.sh"
echo "  4. Open http://127.0.0.1:7871"
