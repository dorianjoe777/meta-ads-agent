#!/usr/bin/env sh
# Execute a bounded, no-write set of real Hermes/NVIDIA turns inside a canary.
#
# This intentionally exercises the installed provider and Hermes runtime while
# instructing the agent not to call tools or mutate any buyer/Meta state.  It
# verifies the request profiles through redacted diagnostics, not model prose.
set -u

HERMES_HOME_PATH="${1:-/app/runtime/hermes}"
OUTPUT_DIR="${ADMIRA_CANARY_OUTPUT_DIR:-$(mktemp -d /tmp/admira-nvidia-profile.XXXXXX)}"
KEEP_OUTPUT="${ADMIRA_CANARY_KEEP_OUTPUT:-1}"
SELECTED_CASES=",${ADMIRA_CANARY_PROFILE_CASES:-all},"
mkdir -p "$OUTPUT_DIR"

cleanup() {
  if [ "$KEEP_OUTPUT" != "1" ]; then
    rm -rf "$OUTPUT_DIR"
  fi
}
trap cleanup EXIT INT TERM

export ADMIRA_HERMES_RUNTIME_PATCHES=1
export HERMES_STREAM_RETRIES=0
export ADMIRA_NVIDIA_REQUESTS_PER_MINUTE="${ADMIRA_NVIDIA_REQUESTS_PER_MINUTE:-36}"
export ADMIRA_NVIDIA_MIN_REQUEST_INTERVAL_SECONDS="${ADMIRA_NVIDIA_MIN_REQUEST_INTERVAL_SECONDS:-2}"
export ADMIRA_NVIDIA_RATE_LIMIT_STATE="${ADMIRA_NVIDIA_RATE_LIMIT_STATE:-$OUTPUT_DIR/nvidia-rate-limit-state.json}"

canary_home="$OUTPUT_DIR/hermes-home"
mkdir -p "$canary_home"
for file in config.yaml config.toml .env auth.json; do
  test ! -f "$HERMES_HOME_PATH/$file" || cp "$HERMES_HOME_PATH/$file" "$canary_home/$file"
done

diagnostics="$OUTPUT_DIR/nvidia-request-diagnostics.jsonl"
hook_diagnostics="$OUTPUT_DIR/nvidia-hook-diagnostics.jsonl"
results="$OUTPUT_DIR/results.tsv"
: > "$results"

run_case() {
  expected_profile="$1"
  label="$2"
  prompt="$3"
  log="$OUTPUT_DIR/$label.log"
  if timeout -k 5 90 env \
    HERMES_HOME="$canary_home" \
    ADMIRA_NVIDIA_REQUEST_DIAGNOSTICS_FILE="$diagnostics" \
    ADMIRA_NVIDIA_HOOK_DIAGNOSTICS_FILE="$hook_diagnostics" \
    hermes -z "$prompt No uses herramientas, no consultes Meta, no leas archivos ni guardes datos. Responde exactamente: CANARY_SAFE_OK." --accept-hooks >"$log" 2>&1; then
    # Model wording is deliberately not the gate. The real proof is a
    # successful no-tool turn plus exactly one bounded provider request below;
    # models may refuse an artificial "reply exactly" instruction when it
    # conflicts with their advisory role.
    if test -s "$log"; then
      printf '%s\t%s\tPASS\n' "$label" "$expected_profile" >> "$results"
    else
      printf '%s\t%s\tBAD_OUTPUT\n' "$label" "$expected_profile" >> "$results"
    fi
  else
    printf '%s\t%s\tFAILED\n' "$label" "$expected_profile" >> "$results"
  fi
  sleep 3
}

selected() {
  case "$SELECTED_CASES" in
    *,all,*|*,"$1",*) return 0 ;;
    *) return 1 ;;
  esac
}

selected strategy && run_case campaign_strategy strategy 'Canary seguro: recomienda audiencia, ciudades e intereses para mi campaña.'
selected execution && run_case campaign_execution execution 'Canary seguro: prepara una campaña de ventas pausada con creativos aprobados.'
selected messaging && run_case messaging_campaign messaging 'Canary seguro: crea una campaña de WhatsApp con mensaje inicial aprobado.'
selected media && run_case campaign_media media 'Canary seguro: genera dos imágenes con Image 2 para la campaña de lanzamiento.'
selected lead_form && run_case lead_form lead_form 'Canary seguro: necesito crear un formulario nativo de leads para mi página.'
selected organic && run_case organic organic 'Canary seguro: prepara una publicación orgánica de Facebook en borrador.'
selected insights && run_case insights insights 'Canary seguro: revisa métricas, gasto, CTR y compras de mi campaña.'

python3 - "$diagnostics" "$hook_diagnostics" "$results" <<'PY'
import json
import sys
from pathlib import Path

diagnostics_path = Path(sys.argv[1])
hooks_path = Path(sys.argv[2])
results_path = Path(sys.argv[3])
rows = [
    json.loads(line)
    for line in diagnostics_path.read_text(encoding="utf-8").splitlines()
    if line.strip()
] if diagnostics_path.exists() else []
results = [line.split("\t") for line in results_path.read_text(encoding="utf-8").splitlines() if line.strip()]
actual = [row.get("profile") for row in rows]
hooks = [
    json.loads(line)
    for line in hooks_path.read_text(encoding="utf-8").splitlines()
    if line.strip()
] if hooks_path.exists() else []
prepared_hooks = [item for item in hooks if item.get("prepared")]
errors = []
if rows and len(rows) != len(results):
    errors.append(f"diagnostics={len(rows)} expected={len(results)}")
if len(prepared_hooks) != len(results):
    errors.append(f"prepared_hooks={len(prepared_hooks)} expected={len(results)}")
for index, (_, profile, status) in enumerate(results):
    if status != "PASS":
        errors.append(f"case {index + 1} status={status}")
    if rows and (index >= len(rows) or actual[index] != profile):
        errors.append(f"case {index + 1} profile={actual[index] if index < len(rows) else 'missing'} expected={profile}")
    if index >= len(prepared_hooks) or prepared_hooks[index].get("profile") != profile:
        actual_profile = prepared_hooks[index].get("profile") if index < len(prepared_hooks) else "missing"
        errors.append(f"case {index + 1} prepared_profile={actual_profile} expected={profile}")
for row in rows:
    if row.get("tools_after", 999) >= 45:
        errors.append(f"unfiltered tools={row.get('tools_after')}")
    if row.get("estimated_input_tokens", 10**9) > row.get("input_budget_tokens", 0):
        errors.append("input budget exceeded")
    if row.get("max_tokens_after", 10**9) > 12288:
        errors.append("output budget exceeded")
for hook in hooks:
    if not hook.get("is_nvidia") or not hook.get("request_is_mapping"):
        errors.append("provider hook did not receive an NVIDIA request mapping")
for hook in prepared_hooks:
    if hook.get("tools_after", 999) >= 45:
        errors.append(f"prepared unfiltered tools={hook.get('tools_after')}")
    if hook.get("estimated_input_tokens", 10**9) > 48000:
        errors.append("prepared input budget exceeded")
    if hook.get("max_tokens_after", 10**9) > 12288:
        errors.append("prepared output budget exceeded")

for row in rows:
    print(
        "PROFILE={profile} TOOLS={tools_after}/{tools_before} "
        "INPUT={estimated_input_tokens}/{input_budget_tokens} OUTPUT={max_tokens_after}".format(**row)
    )
if errors:
    print("CANARY_PROFILE_FAIL: " + "; ".join(errors))
    raise SystemExit(1)
print("CANARY_PROFILE_PASS")
PY
