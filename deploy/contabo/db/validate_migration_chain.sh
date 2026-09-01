#!/usr/bin/env bash
set -euo pipefail

# Read-only release gate for the hosted control-plane migration chain.
# It never connects to PostgreSQL and never applies SQL.  Run this before the
# separate backup -> disposable clone -> apply procedure documented in the
# Contabo operations runbook.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATIONS_DIR="$ROOT_DIR/migrations"
failures=0

pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1" >&2; failures=$((failures + 1)); }

expected=(007_trial_provider_lifecycle.sql 008_central_image_jobs.sql 009_telegram_license_recovery.sql 010_operator_gemini_pool.sql 011_operator_dashboard.sql 012_personal_chatgpt_sponsorship.sql 013_operator_trial_provisioning.sql 014_telegram_typing_indicator.sql 015_telegram_typing_retry_continuity.sql 016_central_campaign_compiler.sql 017_licensed_central_image_pool_switch.sql)
for name in "${expected[@]}"; do
  path="$MIGRATIONS_DIR/$name"
  if [[ -f "$path" && -s "$path" ]]; then pass "present: $name"; else fail "missing or empty: $name"; fi
done

previous="006_runtime_capacity_queue.sql"
for name in "${expected[@]}"; do
  path="$MIGRATIONS_DIR/$name"
  [[ -f "$path" ]] || continue
  if [[ "$name" > "$previous" ]]; then
    pass "ordered after: $previous -> $name"
  else
    fail "migration order is not strictly increasing at $name"
  fi
  previous="$name"
done

for name in "${expected[@]}"; do
  path="$MIGRATIONS_DIR/$name"
  [[ -f "$path" ]] || continue
  content="$(<"$path")"
  [[ "$content" == *$'BEGIN;'* && "$content" == *$'COMMIT;'* ]] \
    && pass "transaction wrapper: $name" \
    || fail "transaction wrapper missing: $name"
  [[ "$content" == *"pg_advisory_xact_lock(hashtextextended('admira:"* ]] \
    && pass "advisory lock: $name" \
    || fail "advisory lock missing: $name"
  if printf '%s' "$content" | grep -Eqi '(api[_ -]?key|bearer[[:space:]]+token|secret[_ -]?value)[[:space:]]+(text|json|bytea)'; then
    fail "possible provider secret column in: $name"
  else
    pass "no provider secret column pattern: $name"
  fi
done

# 009 creates recovery schema but must not be the switch that activates it.
if [[ -f "$ROOT_DIR/.env.example" ]]; then
  env_example="$ROOT_DIR/.env.example"
else
  env_example="$ROOT_DIR/../.env.example"
fi
if [[ -f "$env_example" ]] && grep -Eq '^ADMIRA_TELEGRAM_RECOVERY_READY=false$' "$env_example"; then
  pass 'recovery remains dormant by default'
else
  fail 'recovery default must remain ADMIRA_TELEGRAM_RECOVERY_READY=false'
fi

# A real database verification is deliberately separate: operators must point
# psql at a disposable clone, never at the live database, and run the
# lifecycle validators there after applying 001-017.
if (( failures > 0 )); then
  exit 1
fi
printf '%s\n' 'Migration chain 007-017 passed read-only checks; no database was changed.'
