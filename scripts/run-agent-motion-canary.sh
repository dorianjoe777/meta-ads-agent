#!/usr/bin/env bash
set -euo pipefail

# Exercise the shipped Hermes agent—not a direct MCP caller—with one natural
# language motion-graphics brief.  The workspace and Hermes home are cloned
# into /tmp so no Telegram history, session, buyer-facing message, recurring
# content setting, Meta object, or durable buyer state is changed.
#
# Usage inside an Admira container:
#   scripts/run-agent-motion-canary.sh [hermes-home]

# The gateway-generated home is authoritative. Docker's process environment
# may still advertise the legacy runtime path during/after the migration, so
# never silently prefer it when the Gateway's active home exists.
DEFAULT_SOURCE_HOME="/app/dashboard/data/hermes-home"
if [ ! -f "$DEFAULT_SOURCE_HOME/config.yaml" ]; then
  DEFAULT_SOURCE_HOME="${HERMES_HOME:-/app/runtime/hermes}"
fi
SOURCE_HOME="${1:-$DEFAULT_SOURCE_HOME}"
# This is a release gate, not a long-running buyer task. A provider that has
# emitted no usable agent output for four minutes is a failed canary; leaving
# it alive for fifteen minutes only hides the diagnosis and consumes quota.
TIMEOUT_SECONDS="${ADMIRA_AGENT_MOTION_CANARY_TIMEOUT_SECONDS:-240}"
ROOT="${ADMIRA_PRODUCT_ROOT:-/app}"
RUN_ROOT="$(mktemp -d /tmp/admira-agent-motion-canary.XXXXXX)"
CANARY_HOME="$RUN_ROOT/hermes-home"
CANARY_WORKSPACE="$RUN_ROOT/workspace"
LOG="$RUN_ROOT/agent.log"
# A real canary must coordinate with the live Gateway/cron processes using the
# same provider key.  Tests may override this explicitly, but isolation by
# default would hide concurrent requests and make a quota diagnosis false.
NVIDIA_GATE_STATE="${ADMIRA_NVIDIA_RATE_LIMIT_STATE:-$ROOT/runtime/nvidia-request-gate.json}"

cleanup() {
  # Keep a failed run long enough for a maintainer to inspect its transcript.
  # Successful runs are not buyer artifacts and may be discarded.
  if [ "${KEEP_ADMIRA_AGENT_MOTION_CANARY:-0}" = "1" ] || [ "${CANARY_OK:-0}" != "1" ]; then
    echo "CANARY_ARTIFACTS=$RUN_ROOT" >&2
  else
    rm -rf "$RUN_ROOT"
  fi
}
trap cleanup EXIT INT TERM

# Some freshly-started canary containers have not launched the gateway yet,
# so the persistent Hermes home contains no config.yaml. Bootstrap that home
# from the product's real provider configuration before cloning it. This only
# writes the selected source home; the actual run still uses CANARY_HOME below.
if [ ! -f "$SOURCE_HOME/config.yaml" ]; then
  mkdir -p "$SOURCE_HOME"
  SOURCE_HOME="$SOURCE_HOME" PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY'
import os
import tempfile
from pathlib import Path

import hermes_bridge
from product_config import load_config

source = Path(os.environ["SOURCE_HOME"]).expanduser()
config = load_config()
config.hermes_home = str(source)
hermes_bridge.HERMES_WORKSPACE_DIR = Path(tempfile.mkdtemp(prefix="admira-motion-bootstrap-"))
workspace = hermes_bridge.prepare_hermes_workspace({
    "channel": "telegram",
    "language": "es",
    "account_context": {},
})
written = hermes_bridge.write_cli_hermes_config(config, workspace, {"channel": "telegram"})
if not Path(written["config"]).is_file():
    raise SystemExit("CANARY FAILED: could not bootstrap Hermes config")
print(f"CANARY_BOOTSTRAPPED_HERMES_CONFIG={written['config']}")
PY
fi

# Fail with an actionable canary diagnosis instead of spending provider time
# when the selected Hermes brain or the required Codex/Image 2 session is not
# connected. Image generation cannot be proven through a text-only fallback.
if grep -q 'provider: "admira-nvidia"' "$SOURCE_HOME/config.yaml" && ! grep -q '^providers:' "$SOURCE_HOME/config.yaml"; then
  echo "CANARY BLOCKED: NVIDIA NIM is selected but no NVIDIA provider credentials are configured in this installation." >&2
  exit 77
fi
CODEX_HOME_VALUE="${CODEX_HOME:-}"
if [ -z "$CODEX_HOME_VALUE" ] && [ -f "$ROOT/.env" ]; then
  CODEX_HOME_VALUE="$(sed -n 's/^CODEX_HOME=//p' "$ROOT/.env" | tail -n 1)"
fi
CODEX_AUTH_FOUND=0
# Hermes' own auth.json proves only that the Hermes runtime is configured; it
# is not evidence that the Codex/Image OAuth session can generate an image.
# Prefer the real CLI status probe and only use the direct Codex auth cache as
# a fallback on hosts where the CLI does not expose ``login status``.
CODEX_HOMES=()
for candidate_home in "$CODEX_HOME_VALUE" "${CODEX_IMAGE_HERMES_HOME:-}"; do
  [ -n "$candidate_home" ] || continue
  CODEX_HOMES+=("$candidate_home")
done
if [ -f "/app/runtime/.env" ]; then
  for env_name in CODEX_IMAGE_HERMES_HOME CODEX_HOME; do
    env_home="$(sed -n "s/^${env_name}=//p" /app/runtime/.env | tail -n 1)"
    [ -n "$env_home" ] || continue
    CODEX_HOMES+=("$env_home")
  done
fi
CODEX_HOMES+=("/root/.codex")
if command -v codex >/dev/null 2>&1; then
  for codex_home in "${CODEX_HOMES[@]}"; do
    [ -s "$codex_home/auth.json" ] || continue
    if CODEX_HOME="$codex_home" timeout 20 codex login status >/tmp/admira-codex-motion-canary-status.txt 2>&1; then
      CODEX_AUTH_FOUND=1
      break
    fi
  done
fi
if [ "$CODEX_AUTH_FOUND" -ne 1 ]; then
  for codex_home in "${CODEX_HOMES[@]}"; do
    auth_file="$codex_home/auth.json"
    if [ -s "$auth_file" ]; then
      CODEX_AUTH_FOUND=1
      break
    fi
  done
fi
if [ "$CODEX_AUTH_FOUND" -ne 1 ]; then
  echo "CANARY BLOCKED: Codex/Image 2 authentication is not present in this installation; connect Codex before running the per-scene image canary." >&2
  exit 77
fi

mkdir -p "$CANARY_HOME"
for file in config.yaml config.toml .env auth.json; do
  [ ! -f "$SOURCE_HOME/$file" ] || cp "$SOURCE_HOME/$file" "$CANARY_HOME/$file"
done
test -f "$CANARY_HOME/config.yaml"

# A persistent Hermes home may have been generated before the current NIM
# policy.  Normalize only the disposable canary copy so this release gate
# actually tests the no-retry policy; production homes are rewritten by the
# normal config writer when the product update is installed.
if grep -q 'provider: "admira-nvidia"' "$CANARY_HOME/config.yaml"; then
  sed -E -i 's/^  api_max_retries: [0-9]+$/  api_max_retries: 0/' "$CANARY_HOME/config.yaml"
  echo "CANARY_NVIDIA_API_MAX_RETRIES=$(sed -n 's/^  api_max_retries: //p' "$CANARY_HOME/config.yaml" | head -1)"
fi

# A canary may deliberately exercise an already-configured fallback after the
# primary hosted model has shown a bounded no-stream stall. This never changes
# the buyer's actual model selection because it edits only the copied config.
if [ -n "${ADMIRA_AGENT_MOTION_CANARY_MODEL:-}" ]; then
  CANARY_MODEL="$ADMIRA_AGENT_MOTION_CANARY_MODEL" CANARY_HOME="$CANARY_HOME" python3 - <<'PY'
import os
from pathlib import Path

path = Path(os.environ["CANARY_HOME"]) / "config.yaml"
model = os.environ["CANARY_MODEL"].replace('"', '\\"')
text = path.read_text(encoding="utf-8")
text = text.replace('"z-ai/glm-5.2"', f'"{model}"')
path.write_text(text, encoding="utf-8")
PY
fi

# Build the current product workspace from source, but redirect the generated
# snapshots to this disposable path. This is the same builder Telegram uses.
CANARY_WORKSPACE="$CANARY_WORKSPACE" PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY'
import os
from pathlib import Path

import hermes_bridge

hermes_bridge.HERMES_WORKSPACE_DIR = Path(os.environ["CANARY_WORKSPACE"])
result = hermes_bridge.prepare_hermes_workspace({
    "channel": "telegram",
    "language": "es",
    "account_context": {},
})
profile = hermes_bridge.HERMES_WORKSPACE_DIR / "AGENTS.md"
print(f"CANARY_WORKSPACE={result['path']}")
print(f"CANARY_AGENTS_CHARS={profile.stat().st_size}")
PY

# The copied config is buyer-authenticated, but its terminal workspace must be
# isolated. Do not mutate the real Gateway config to run a canary.
CANARY_HOME="$CANARY_HOME" CANARY_WORKSPACE="$CANARY_WORKSPACE" python3 - <<'PY'
import os
from pathlib import Path

path = Path(os.environ["CANARY_HOME"]) / "config.yaml"
workspace = os.environ["CANARY_WORKSPACE"].replace("\\", "\\\\").replace('"', '\\"')
text = path.read_text(encoding="utf-8")
needle = "terminal:\n  cwd: "
if needle not in text:
    raise SystemExit("CANARY FAILED: Hermes config has no terminal cwd")
head, tail = text.split(needle, 1)
rest = tail.split("\n", 1)
text = head + needle + f'"{workspace}"' + ("\n" + rest[1] if len(rest) == 2 else "\n")
path.write_text(text, encoding="utf-8")
PY

PROMPT=$(cat <<'EOF'
Crea ahora un único video orgánico de preview, vertical 9:16 y de unos 20 segundos, para Uboost (Admira IA). El mensaje central es: “No necesitas otra agencia para entender tus anuncios.” Audiencia: dueños de negocio y agencias pequeñas de Latinoamérica que ya usan Meta Ads y se sienten perdidos entre métricas, agencias y decisiones manuales.

Usa la guía de marca y el producto Uboost guardados. Decide tú un storyboard editorial claro y moderno; no quiero una plantilla de tarjetas repetida. La historia debe tener al menos tres momentos visuales distintos y no puede reutilizar la misma imagen durante todo el video. Para esta prueba usa Image 2 de forma comprobable: crea una imagen de escena completa con fondo normal y un elemento de historia con fondo verde, conviértelo en PNG transparente y vincula ambos a las escenas correctas. El PNG transparente debe entrar en `layer_asset_paths`. En la llamada de render establece `require_visual_assets: true`, `minimum_visual_assets: 2` y `require_transparent_story_element: true`. Revisa los resultados reales de esos assets y adapta la composición antes de renderizar. Usa recetas distintas del catálogo de Shotcraft cuando la narrativa lo justifique, con ritmo y lectura cómodos en móvil. No inventes testimonios, cifras ni promesas garantizadas. No publiques nada, no crees campañas y no cambies la estrategia recurrente de contenido. Renderiza y entrega el MP4 de preview en esta misma respuesta, explicando brevemente qué creaste.
EOF
)

set +e
timeout -k 15 "$TIMEOUT_SECONDS" env \
  HERMES_HOME="$CANARY_HOME" \
  PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" \
  ADMIRA_PRODUCT_ROOT="$ROOT" \
  ADMIRA_NVIDIA_RATE_LIMIT_STATE="$NVIDIA_GATE_STATE" \
  HERMES_STREAM_RETRIES="0" \
  ADMIRA_HERMES_RUNTIME_PATCHES=1 \
  hermes -z "$PROMPT" --accept-hooks >"$LOG" 2>&1
STATUS=$?
set -e

cat "$LOG"
if [ -f "$NVIDIA_GATE_STATE" ]; then
  REQUEST_COUNT="$(python3 -c 'import json,sys; p=json.load(open(sys.argv[1])); print(len(p.get("starts", [])))' "$NVIDIA_GATE_STATE" 2>/dev/null || echo 0)"
  echo "CANARY_NVIDIA_RESERVED_REQUESTS=$REQUEST_COUNT"
fi
if [ "$STATUS" -ne 0 ]; then
  echo "CANARY FAILED: Hermes exited with $STATUS" >&2
  exit "$STATUS"
fi
MP4="$(find "$ROOT/output/motion-graphics" -type f -name '*.mp4' -newer "$LOG" -print | tail -n 1 || true)"
if [ -z "$MP4" ]; then
  echo "CANARY FAILED: Agent returned without a newly rendered MP4" >&2
  exit 1
fi
SPEC="$(dirname "$MP4")/motion-spec.json"
if ! MP4="$MP4" SPEC="$SPEC" python3 - <<'PY'
import json
import os
from pathlib import Path

spec_path = Path(os.environ["SPEC"])
if not spec_path.is_file():
    raise SystemExit("CANARY FAILED: rendered MP4 has no motion-spec.json")
spec = json.loads(spec_path.read_text(encoding="utf-8"))
contract = spec.get("visual_asset_contract") or {}
scenes = spec.get("scenes") or []
has_full_scene = any(scene.get("media_src") for scene in scenes)
has_layer = any(scene.get("layer_media") for scene in scenes)
if not contract.get("required") or contract.get("explicitly_bound_assets", 0) < 2 or not has_full_scene or not has_layer:
    raise SystemExit(
        "CANARY FAILED: agent rendered without the required full-scene and transparent-layer assets "
        f"(contract={contract!r}, has_full_scene={has_full_scene}, has_layer={has_layer})"
    )
print(f"CANARY_VIDEO={os.environ['MP4']}")
print(f"CANARY_VISUAL_CONTRACT={contract}")
PY
then
  exit 1
fi
CANARY_OK=1
echo "CANARY PASS: Hermes planned, bound Image 2 assets to scenes, and rendered the preview through official MCP tools."
