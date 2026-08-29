#!/usr/bin/env bash
set -euo pipefail

# Read-only release gate.  This script deliberately never starts Compose,
# creates tenants, touches secrets, or writes to PostgreSQL.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE=local
TENANT_BASE="${ADMIRA_TENANTS_BASE:-/srv/admira/tenants}"
TENANT_A=""
TENANT_B=""
FAILURES=0

usage() {
  printf '%s\n' "Usage: $0 [--local|--server] [--tenant-a ID --tenant-b ID] [--tenant-base PATH]"
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --local) MODE=local; shift ;;
    --server) MODE=server; shift ;;
    --tenant-a) TENANT_A="${2:?missing tenant id}"; shift 2 ;;
    --tenant-b) TENANT_B="${2:?missing tenant id}"; shift 2 ;;
    --tenant-base) TENANT_BASE="${2:?missing tenant base}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

ok() { printf 'PASS  %s\n' "$1"; }
warn() { printf 'WARN  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1" >&2; FAILURES=$((FAILURES + 1)); }
need_file() { [[ -f "$1" ]] && ok "file: ${1#$ROOT_DIR/}" || fail "missing file: $1"; }

resolve_runtime_worker_replicas() {
  local resolved="${RUNTIME_WORKER_REPLICAS:-}" config_key config_value
  if [[ -z "$resolved" && -r "$ROOT_DIR/.env" ]]; then
    while IFS='=' read -r config_key config_value; do
      config_value="${config_value%$'\r'}"
      if [[ "$config_key" == "RUNTIME_WORKER_REPLICAS" ]]; then
        resolved="$config_value"
      fi
    done < "$ROOT_DIR/.env"
  fi
  printf '%s' "${resolved:-1}"
}

RUNTIME_WORKER_REPLICAS="$(resolve_runtime_worker_replicas)"
export RUNTIME_WORKER_REPLICAS

for file in compose.yaml Control.Dockerfile app-requirements.txt \
  apply-control-plane.sh runtime_broker.py tenant_turn.py telegram_ingress.py \
  hosted_service.py hosted_worker.py tenant_admin.py tenantctl.py capacity-preflight.sh \
  db/migrations/001_initial_multitenant.sql db/migrations/002_telegram_ingress_control.sql \
  db/migrations/003_hosted_tenant_registration.sql db/migrations/004_active_tenant_runtime_gate.sql \
  db/migrations/005_telegram_rate_limit_retry.sql db/migrations/006_runtime_capacity_queue.sql \
  db/bootstrap_service_roles.sql; do
  need_file "$ROOT_DIR/$file"
done

if python3 - "$ROOT_DIR" <<'PY'
import ast
import pathlib
import sys
root = pathlib.Path(sys.argv[1])
files = [root / name for name in ("runtime_broker.py", "tenant_turn.py", "telegram_ingress.py", "hosted_service.py", "hosted_worker.py", "tenant_admin.py", "tenantctl.py")]
for path in files:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
PY
then ok 'Python syntax'; else fail 'Python syntax'; fi
if bash -n "$ROOT_DIR/bootstrap-control-plane.sh" "$ROOT_DIR/install-runtime-broker.sh" "$ROOT_DIR/apply-control-plane.sh" "$ROOT_DIR/capacity-preflight.sh"; then
  ok 'shell syntax'
else
  fail 'shell syntax'
fi
if [[ "$RUNTIME_WORKER_REPLICAS" =~ ^[1-8]$ ]]; then
  ok "runtime-worker replicas configured: $RUNTIME_WORKER_REPLICAS"
else
  fail 'RUNTIME_WORKER_REPLICAS must be an integer from 1 through 8'
fi

if docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" config --quiet >/dev/null 2>&1 \
    && docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" \
      --profile buyers config --quiet >/dev/null 2>&1; then
  ok 'control-plane and buyers Compose configurations'
else
  fail 'control-plane or buyers Compose configuration (check .env and secret files)'
fi

TOKEN="$ROOT_DIR/secrets/telegram_bot_token.txt"
if [[ -f "$TOKEN" && -s "$TOKEN" ]]; then
  mode=$(stat -c '%a' "$TOKEN" 2>/dev/null || stat -f '%Lp' "$TOKEN")
  if [[ "$mode" =~ ^0*600$|^0*400$ ]]; then ok 'Telegram token is present with private permissions'; else fail 'Telegram token permissions must be 0600 or 0400'; fi
else
  if [[ "$MODE" == server ]]; then fail 'Telegram token is absent or empty'; else warn 'Telegram token is intentionally absent in local preparation'; fi
fi

if [[ "$MODE" == server ]]; then
  if systemctl is-active --quiet admira-runtime-broker.service; then ok 'runtime broker is active'; else fail 'runtime broker is not active'; fi
  if [[ -S /run/admira-runtime-broker/broker.sock ]]; then ok 'runtime broker socket exists'; else fail 'runtime broker socket is missing'; fi
  if [[ -f /etc/admira/runtime-broker.key ]]; then
    key_mode=$(stat -c '%a' /etc/admira/runtime-broker.key 2>/dev/null || stat -f '%Lp' /etc/admira/runtime-broker.key)
    [[ "$key_mode" =~ ^0*600$ ]] && ok 'broker key is private' || fail 'broker key permissions must be 0600'
  else fail 'broker key is missing'; fi
  if docker image inspect admira-ia:r90 >/dev/null 2>&1; then ok 'tenant image admira-ia:r90 is present'; else fail 'tenant image admira-ia:r90 is missing'; fi
  migration_check_sql="SELECT count(*) = 3
FROM pg_proc AS p
JOIN pg_namespace AS n ON n.oid = p.pronamespace
WHERE n.nspname = 'admira'
  AND p.proname IN ('claim_telegram_updates','claim_due_scheduled_jobs','acquire_runtime_lease')
  AND pg_get_functiondef(p.oid) LIKE '%tenant.status = ''active''%';"
  if printf '%s\n' "$migration_check_sql" | \
      docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" exec -T postgres \
      sh -ec 'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; exec psql -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
      2>/dev/null | grep -qx t; then
    ok 'active-tenant migration is visible in PostgreSQL'
  else
    fail 'active-tenant migration is not visible in PostgreSQL'
  fi
  rate_limit_check_sql="SELECT count(*) = 1
FROM pg_proc AS p
JOIN pg_namespace AS n ON n.oid = p.pronamespace
WHERE n.nspname = 'admira'
  AND p.proname = 'ack_telegram_outbox'
  AND pg_get_functiondef(p.oid) LIKE '%p_error_code = ''telegram_rate_limited''%';"
  if printf '%s\n' "$rate_limit_check_sql" | \
      docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" exec -T postgres \
      sh -ec 'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; exec psql -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
      2>/dev/null | grep -qx t; then
    ok 'Telegram rate-limit retry migration is visible in PostgreSQL'
  else
    fail 'Telegram rate-limit retry migration is not visible in PostgreSQL'
  fi
  capacity_check_sql="SELECT
  EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'admira'
      AND table_name = 'tenant_telegram_updates'
      AND column_name = 'capacity_deferrals'
  )
  AND (
    SELECT count(*) = 5
    FROM pg_proc AS p
    JOIN pg_namespace AS n ON n.oid = p.pronamespace
    WHERE n.nspname = 'admira'
      AND p.proname IN (
        'defer_telegram_update_capacity', 'defer_scheduled_job_capacity', 'claim_idle_runtime',
        'complete_idle_runtime', 'release_idle_runtime_claim'
      )
  );"
  if printf '%s\n' "$capacity_check_sql" | \
      docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" exec -T postgres \
      sh -ec 'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; exec psql -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
      2>/dev/null | grep -qx t; then
    ok 'durable capacity queue migration is visible in PostgreSQL'
  else
    fail 'durable capacity queue migration is not visible in PostgreSQL'
  fi
else
  grep -q 'admira-ia:r90' "$ROOT_DIR/tenantctl.py" && ok 'tenant image pin is admira-ia:r90' || fail 'tenant image pin is not admira-ia:r90'
  grep -q 'status = '\''active'\''' "$ROOT_DIR/db/migrations/004_active_tenant_runtime_gate.sql" && ok 'active-tenant migration contains gate' || fail 'active-tenant migration gate missing'
  grep -q "p_error_code = 'telegram_rate_limited'" "$ROOT_DIR/db/migrations/005_telegram_rate_limit_retry.sql" && ok 'Telegram rate-limit migration preserves retries' || fail 'Telegram rate-limit retry migration gate missing'
  grep -q 'attempt_count = greatest(0, attempt_count - 1)' "$ROOT_DIR/db/migrations/006_runtime_capacity_queue.sql" \
    && grep -q 'FOR UPDATE OF runtime SKIP LOCKED' "$ROOT_DIR/db/migrations/006_runtime_capacity_queue.sql" \
    && ok 'capacity migration preserves failure budget and fences LRU claims' \
    || fail 'capacity migration safety gates missing'
fi

if [[ -n "$TENANT_A" || -n "$TENANT_B" ]]; then
  tenant_ids_valid=true
  if [[ -n "$TENANT_A" && -n "$TENANT_B" && "$TENANT_A" != "$TENANT_B" \
        && "$TENANT_A" =~ ^[a-z0-9][a-z0-9-]{2,62}$ \
        && "$TENANT_B" =~ ^[a-z0-9][a-z0-9-]{2,62}$ ]]; then
    ok 'two distinct valid canary tenant IDs supplied'
  else
    fail 'canary tenant IDs must be two distinct valid tenant slugs'
    tenant_ids_valid=false
  fi
  if [[ "$tenant_ids_valid" == true ]]; then
    for tenant in "$TENANT_A" "$TENANT_B"; do
      path="$TENANT_BASE/$tenant"
      [[ -d "$path" ]] && ok "canary tenant directory exists: $tenant" || fail "canary tenant directory missing: $path"
      [[ -f "$path/compose.yaml" ]] && ok "canary tenant Compose exists: $tenant" || fail "canary tenant Compose missing: $path/compose.yaml"
      [[ -f "$path/runtime/.env" ]] && ok "canary tenant runtime env exists: $tenant" || fail "canary tenant runtime env missing: $path/runtime/.env"
    done
  fi
else
  if [[ "$MODE" == server ]]; then
    fail 'two canary tenant IDs are required in server mode'
  else
    warn 'two-canary checks skipped; supply --tenant-a and --tenant-b'
  fi
fi

if (( FAILURES )); then
  printf 'Preflight failed: %d check(s)\n' "$FAILURES" >&2
  exit 1
fi
printf '%s\n' 'Preflight passed.'
