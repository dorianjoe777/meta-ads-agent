#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ "${1:-}" = "" ]; then
  echo "Usage: ./scripts/approve.sh APPROVAL_ID"
  echo "Run ./scripts/list-pending.sh to see pending approvals."
  exit 1
fi

python3 src/daily_agent.py approve "$1"

