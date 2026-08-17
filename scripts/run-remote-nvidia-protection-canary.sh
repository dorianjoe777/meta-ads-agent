#!/usr/bin/env bash
set -euo pipefail

# One bounded, no-write NVIDIA/Hermes smoke request on an isolated Hermes home.
# It deliberately does not call Meta, create media, publish, or mutate a
# buyer session. Credentials stay on the canary host and never enter output.
# Usage: ./run-remote-nvidia-protection-canary.sh user@host identity-file container [hermes-home]
TARGET="${1:?Usage: $0 <user@host> <identity-file> <container> [hermes-home]}"
IDENTITY_FILE="${2:?Usage: $0 <user@host> <identity-file> <container> [hermes-home]}"
CONTAINER="${3:?Usage: $0 <user@host> <identity-file> <container> [hermes-home]}"
HERMES_HOME_PATH="${4:-/app/dashboard/data/hermes-home}"
AGENT_TIMEOUT_SECONDS="${ADMIRA_CANARY_AGENT_TIMEOUT_SECONDS:-60}"

# Send the canary script through stdin instead of nesting a Python heredoc in
# ssh/docker/sh quotes. This keeps validation code intact on every shell.
ssh -i "$IDENTITY_FILE" \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  -o ConnectTimeout=20 \
  "$TARGET" \
  "docker exec -i '$CONTAINER' sh -s -- '$HERMES_HOME_PATH' '$AGENT_TIMEOUT_SECONDS'" <<'REMOTE_CANARY'
set -eu
HERMES_HOME_PATH="$1"
AGENT_TIMEOUT_SECONDS="$2"
test -x /usr/local/bin/hermes
test -f /app/src/admira_hermes_runtime_patch.py
export PYTHONPATH=/tmp/admira-nvidia-canary-src:/app/src
export ADMIRA_HERMES_RUNTIME_PATCHES=1
export HERMES_STREAM_RETRIES=0
export ADMIRA_NVIDIA_REQUESTS_PER_MINUTE=36
export ADMIRA_NVIDIA_MIN_REQUEST_INTERVAL_SECONDS=1.7

canary_home=$(mktemp -d)
diagnostics="$canary_home/nvidia-request-diagnostics.jsonl"
canary_log="$canary_home/hermes.log"
cleanup() { rm -rf "$canary_home"; }
trap cleanup EXIT INT TERM
for file in config.yaml config.toml .env auth.json; do
  test ! -f "$HERMES_HOME_PATH/$file" || cp "$HERMES_HOME_PATH/$file" "$canary_home/$file"
done

# Directly exercise the installed request guard so the canary does not rely on
# whether the standalone Hermes CLI imports chat_completion_helpers eagerly.
# This is synthetic and read-only; it never reaches NVIDIA or Meta.
ADMIRA_NVIDIA_REQUEST_DIAGNOSTICS_FILE="$diagnostics" python3 - <<'PY'
import admira_hermes_runtime_patch as runtime
import hermes_bridge

def tool(name):
    tool_name = name if name in {"read_file", "memory_search", "web_search", "vision_analyze"} else "mcp_admira_" + name
    return {"type": "function", "function": {"name": tool_name, "description": name}}

names = sorted(set().union(*runtime.ADMIRA_NVIDIA_TOOL_PROFILES.values()))
names.extend(("read_file", "memory_search", "web_search", "vision_analyze"))
prepared = runtime._nvidia_prepare_request({
    "model": "minimaxai/minimax-m3",
    "messages": [{"role": "user", "content": "Revisa métricas y gasto; no uses ninguna acción."}],
    "tools": [tool(name) for name in names],
    "max_tokens": 65536,
})
estimated = runtime._nvidia_estimated_input_tokens(prepared["messages"], prepared["tools"])
policy = hermes_bridge.inference_runtime_policy({
    "brain": "nvidia_nim",
    "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
    "model": "minimaxai/minimax-m3",
})
if estimated > runtime.ADMIRA_NVIDIA_INPUT_BUDGET_TOKENS:
    raise SystemExit("CANARY FAILED: synthetic input budget exceeded")
if int(prepared.get("max_tokens") or 0) > 12288:
    raise SystemExit("CANARY FAILED: synthetic output budget exceeded")
if len(prepared.get("tools") or []) >= 45:
    raise SystemExit("CANARY FAILED: synthetic Admira tool registry unfiltered")
if int(policy.get("api_max_retries") or 0) != 0 or int(policy.get("stream_retries") or 0) != 0:
    raise SystemExit("CANARY FAILED: NVIDIA retry policy is not zero")
PY

HERMES_HOME="$canary_home" hermes mcp test admira >/dev/null
if ! timeout -k 5 "$AGENT_TIMEOUT_SECONDS" env \
  HERMES_HOME="$canary_home" \
  ADMIRA_NVIDIA_REQUEST_DIAGNOSTICS_FILE="$diagnostics" \
  hermes -z "Reply with exactly NVIDIA_CANARY_OK. Do not call tools, read files, browse, use vision, create campaigns, create media, publish, or mutate any data." --accept-hooks >"$canary_log" 2>&1; then
  echo "CANARY FAILED: bounded no-write Hermes smoke timed out or errored." >&2
  tail -80 "$canary_log" >&2
  exit 1
fi
grep -q NVIDIA_CANARY_OK "$canary_log"
test -s "$diagnostics"

python3 - "$diagnostics" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
rows = [
    json.loads(line)
    for line in path.read_text(encoding="utf-8").splitlines()
    if line.strip()
]
if not rows:
    raise SystemExit("CANARY FAILED: no NVIDIA diagnostics record")
for row in rows:
    if row.get("max_tokens_after", 0) > 12288:
        raise SystemExit("CANARY FAILED: output budget exceeded")
    if row.get("estimated_input_tokens", 0) > row.get("input_budget_tokens", 0):
        raise SystemExit("CANARY FAILED: input budget exceeded")
    if row.get("tools_after", 0) >= 45:
        raise SystemExit("CANARY FAILED: unfiltered Admira tool registry")
    if "content" in row or "api_key" in row or "token" in row:
        raise SystemExit("CANARY FAILED: secret/content diagnostics leak")
print("REMOTE NVIDIA CANARY PASS: bounded request, filtered tools, redacted diagnostics, no-write Hermes smoke")
PY
REMOTE_CANARY
