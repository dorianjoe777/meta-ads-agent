#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$ROOT_DIR/dashboard/data"

mkdir -p "$DATA_DIR"

ROOT_DIR="$ROOT_DIR" python3 - <<'PY'
from pathlib import Path
import os
import sys

root = Path(os.environ["ROOT_DIR"]).resolve()
sys.path.insert(0, str(root / "dashboard"))

import importlib.util

module_path = root / "dashboard" / "monitoring-dashboard.py"
spec = importlib.util.spec_from_file_location("monitoring_dashboard", module_path)
dashboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dashboard)

dashboard.save_metrics(dashboard.sample_metrics())
for path in [
    dashboard.ACTIONS_FILE,
    dashboard.PENDING_FILE,
    dashboard.CREATED_FILE,
    dashboard.ONBOARDING_FILE,
]:
    dashboard.write_json(path, [])

dashboard.write_json(dashboard.ONBOARDING_FILE, {"completed": False, "completed_at": "", "completed_by": "", "setup_snapshot": {}})
dashboard.write_json(dashboard.DATA_DIR / "telegram_chat_history.json", {})
dashboard.write_json(dashboard.DATA_DIR / "telegram_offset.json", {})

for folder in [
    dashboard.DATA_DIR / "uploads",
    dashboard.DATA_DIR / "creative_refreshes",
    dashboard.OUTPUT_DIR / "telegram_uploads",
]:
    if folder.exists():
        for item in folder.glob("*"):
            if item.is_file():
                item.unlink()

print("Demo metrics restored. Runtime actions, approvals, uploads, Telegram conversations, onboarding state, and created campaigns cleared.")
print(".env was not changed.")
PY
