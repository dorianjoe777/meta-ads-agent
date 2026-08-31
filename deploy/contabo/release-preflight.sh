#!/usr/bin/env bash
set -euo pipefail

# Read-only release gate.  This script deliberately never starts Compose,
# creates tenants, touches secrets, or writes to PostgreSQL.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE=local
CHECK_OPERATOR=false
TENANT_BASE="${ADMIRA_TENANTS_BASE:-/srv/admira/tenants}"
TENANT_A=""
TENANT_B=""
FAILURES=0

usage() {
  printf '%s\n' "Usage: $0 [--local|--server] [--operator-dashboard] [--tenant-a ID --tenant-b ID] [--tenant-base PATH]"
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --local) MODE=local; shift ;;
    --server) MODE=server; shift ;;
    --operator-dashboard) CHECK_OPERATOR=true; shift ;;
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

# Compose precedence is environment, then project .env, then the inline
# default. Keep this read-only resolver aligned with the values the server
# will actually receive; do not source .env because it is not shell code.
resolve_compose_value() {
  local key="$1" fallback="$2" config_key config_value
  case "$key" in
    ADMIRA_TELEGRAM_RECOVERY_READY)
      [[ -n "${ADMIRA_TELEGRAM_RECOVERY_READY+x}" ]] && { printf '%s' "$ADMIRA_TELEGRAM_RECOVERY_READY"; return; } ;;
    ADMIRA_SMTP_HOST)
      [[ -n "${ADMIRA_SMTP_HOST+x}" ]] && { printf '%s' "$ADMIRA_SMTP_HOST"; return; } ;;
    ADMIRA_SMTP_FROM)
      [[ -n "${ADMIRA_SMTP_FROM+x}" ]] && { printf '%s' "$ADMIRA_SMTP_FROM"; return; } ;;
    ADMIRA_SMTP_SECURITY)
      [[ -n "${ADMIRA_SMTP_SECURITY+x}" ]] && { printf '%s' "$ADMIRA_SMTP_SECURITY"; return; } ;;
    ADMIRA_SERVICE_UID)
      [[ -n "${ADMIRA_SERVICE_UID+x}" ]] && { printf '%s' "$ADMIRA_SERVICE_UID"; return; } ;;
    ADMIRA_CENTRAL_IMAGE_READY)
      [[ -n "${ADMIRA_CENTRAL_IMAGE_READY+x}" ]] && { printf '%s' "$ADMIRA_CENTRAL_IMAGE_READY"; return; } ;;
    CENTRAL_IMAGE_IMAGE)
      [[ -n "${CENTRAL_IMAGE_IMAGE+x}" ]] && { printf '%s' "$CENTRAL_IMAGE_IMAGE"; return; } ;;
    ADMIRA_CENTRAL_CODEX_AUTH_ROOT)
      [[ -n "${ADMIRA_CENTRAL_CODEX_AUTH_ROOT+x}" ]] && { printf '%s' "$ADMIRA_CENTRAL_CODEX_AUTH_ROOT"; return; } ;;
    ADMIRA_CENTRAL_CODEX_ACCOUNT_IDS)
      [[ -n "${ADMIRA_CENTRAL_CODEX_ACCOUNT_IDS+x}" ]] && { printf '%s' "$ADMIRA_CENTRAL_CODEX_ACCOUNT_IDS"; return; } ;;
    ADMIRA_OPERATOR_SETUP_CIDRS)
      [[ -n "${ADMIRA_OPERATOR_SETUP_CIDRS+x}" ]] && { printf '%s' "$ADMIRA_OPERATOR_SETUP_CIDRS"; return; } ;;
    ADMIRA_PROVISIONER_GID)
      [[ -n "${ADMIRA_PROVISIONER_GID+x}" ]] && { printf '%s' "$ADMIRA_PROVISIONER_GID"; return; } ;;
  esac
  if [[ -r "$ROOT_DIR/.env" ]]; then
    while IFS='=' read -r config_key config_value; do
      config_value="${config_value%$'\r'}"
      if [[ "$config_key" == "$key" ]]; then
        config_value="${config_value#\"}"; config_value="${config_value%\"}"
        config_value="${config_value#\'}"; config_value="${config_value%\'}"
        printf '%s' "$config_value"
        return
      fi
    done < "$ROOT_DIR/.env"
  fi
  printf '%s' "$fallback"
}

for file in compose.yaml Control.Dockerfile app-requirements.txt \
  apply-control-plane.sh runtime_broker.py tenant_turn.py telegram_ingress.py \
  hosted_service.py hosted_worker.py tenant_admin.py tenantctl.py provider_admin.py \
  gemini_pool_admin.py tenant_provisioner.py install-tenant-provisioner.sh TENANT_PROVISIONER.md \
  operator_dashboard.py operator_dashboard.html operator_dashboard.css operator_dashboard.js OPERATOR_DASHBOARD.md open-operator-dashboard.command \
  image_broker.py central_image_service.py central_codex_account_pool.py prepare-central-image-broker.sh \
  recovery_identity.py recovery_service.py recovery_email_worker.py recovery_smtp.py \
  capacity-preflight.sh \
  db/migrations/001_initial_multitenant.sql db/migrations/002_telegram_ingress_control.sql \
  db/migrations/003_hosted_tenant_registration.sql db/migrations/004_active_tenant_runtime_gate.sql \
  db/migrations/005_telegram_rate_limit_retry.sql db/migrations/006_runtime_capacity_queue.sql \
  db/migrations/007_trial_provider_lifecycle.sql db/bootstrap_service_roles.sql \
  db/migrations/008_central_image_jobs.sql db/validate_trial_lifecycle.sql \
  db/validate_central_image_jobs.sql db/migrations/009_telegram_license_recovery.sql \
  db/validate_telegram_license_recovery.sql db/migrations/010_operator_gemini_pool.sql \
  db/validate_operator_gemini_pool.sql db/migrations/011_operator_dashboard.sql \
  db/validate_operator_dashboard.sql db/migrations/012_personal_chatgpt_sponsorship.sql \
  db/validate_personal_chatgpt_sponsorship.sql db/migrations/013_operator_trial_provisioning.sql \
  db/validate_operator_trial_provisioning.sql; do
  need_file "$ROOT_DIR/$file"
done

if python3 - "$ROOT_DIR" <<'PY'
import ast
import pathlib
import sys
root = pathlib.Path(sys.argv[1])
names = ("runtime_broker.py", "tenant_turn.py", "telegram_ingress.py", "hosted_service.py", "hosted_worker.py", "tenant_admin.py", "tenantctl.py", "provider_admin.py", "gemini_pool_admin.py", "tenant_provisioner.py", "operator_dashboard.py", "image_broker.py", "central_image_service.py", "central_codex_account_pool.py", "recovery_identity.py", "recovery_service.py", "recovery_email_worker.py", "recovery_smtp.py")
files = [root / name for name in names]
for path in files:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
PY
then ok 'Python syntax'; else fail 'Python syntax'; fi
if bash -n "$ROOT_DIR/bootstrap-control-plane.sh" "$ROOT_DIR/install-runtime-broker.sh" "$ROOT_DIR/install-tenant-provisioner.sh" "$ROOT_DIR/prepare-central-image-broker.sh" "$ROOT_DIR/apply-control-plane.sh" "$ROOT_DIR/capacity-preflight.sh" "$ROOT_DIR/open-operator-dashboard.command"; then
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
      --profile buyers config --quiet >/dev/null 2>&1 \
    && docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" \
      --profile central-images config --quiet >/dev/null 2>&1; then
  ok 'control-plane, buyers and dormant central-image Compose configurations'
else
  fail 'control-plane, buyers or central-image Compose configuration (check .env and secret files)'
fi
if docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" \
    --profile recovery-email config --quiet >/dev/null 2>&1; then
  ok 'opt-in recovery-email Compose configuration'
else
  fail 'recovery-email Compose configuration (check .env and private secret files)'
fi
if docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" \
    --profile operator-dashboard config --quiet >/dev/null 2>&1; then
  ok 'opt-in operator-dashboard Compose configuration'
else
  fail 'operator-dashboard Compose configuration (check .env and private bind sources)'
fi
# Inspect the rendered topology, not only YAML spelling. No secret contents
# are present in Compose config and the JSON is never printed.
if docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" \
    --profile '*' config --format json 2>/dev/null | python3 -c '
import json, sys
try:
    config = json.load(sys.stdin)
    services = config["services"]
    operator = services["operator-dashboard"]
    ports = operator.get("ports", [])
    assert len(ports) == 1 and ports[0]["host_ip"] == "127.0.0.1" and ports[0]["target"] == 8791
    assert set(operator["networks"]) == {"operator_private", "operator_provider_egress"}
    assert config["networks"]["operator_private"]["internal"] is True
    assert not config["networks"]["operator_provider_egress"].get("internal", False)
    assert {name for name, svc in services.items() if "operator_private" in svc.get("networks", {})} == {"postgres", "operator-dashboard"}
    assert {name for name, svc in services.items() if "operator_provider_egress" in svc.get("networks", {})} == {"operator-dashboard"}
    assert all(not svc.get("ports") for name, svc in services.items() if name != "operator-dashboard")
    assert operator["read_only"] is True and operator["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in operator["security_opt"] and operator.get("tmpfs")
    assert {entry["source"] for entry in operator["secrets"]} == {"operator_db_password"}
    assert operator["environment"]["ADMIRA_DB_USER"] == "admira_operator_login"
    assert operator["environment"]["ADMIRA_PROVISIONER_SOCKET"] == "/run/admira-tenant-provisioner/provisioner.sock"
    assert operator["environment"]["ADMIRA_PROVISIONER_KEY_FILE"] == "/run/admira-tenant-provisioner/tenant-provisioner.key"
    mounts = {mount.get("source", "") for mount in operator["volumes"]}
    assert "/run/admira-tenant-provisioner" in mounts
    assert "/etc/admira/tenant-provisioner.key" in mounts
    assert "19094" in {str(item) for item in operator.get("group_add", [])}
    assert all("docker.sock" not in source and "/srv/admira/tenants" not in source for source in mounts)
except (KeyError, TypeError, ValueError, AssertionError):
    sys.exit(1)
'; then
  ok 'operator dashboard is loopback-published, network-isolated and least-privilege'
else
  fail 'operator dashboard rendered security boundary is invalid'
fi
if [[ -r "$ROOT_DIR/.env.example" ]] && grep -Eq '^ADMIRA_TELEGRAM_RECOVERY_READY=false$' "$ROOT_DIR/.env.example"; then
  ok 'Telegram recovery is disabled by default in .env.example'
else
  fail 'Telegram recovery must remain disabled by default in .env.example'
fi
CENTRAL_IMAGE_PLACEHOLDER='admira-ia-hosted:r91-canary-000000000000'
CENTRAL_IMAGE_IMAGE="$(resolve_compose_value CENTRAL_IMAGE_IMAGE "$CENTRAL_IMAGE_PLACEHOLDER")"
CENTRAL_IMAGE_READY="$(resolve_compose_value ADMIRA_CENTRAL_IMAGE_READY false | tr '[:upper:]' '[:lower:]')"
CENTRAL_CODEX_ACCOUNT_IDS="$(resolve_compose_value ADMIRA_CENTRAL_CODEX_ACCOUNT_IDS 'primary,secondary')"
CENTRAL_CODEX_AUTH_ROOT="$(resolve_compose_value ADMIRA_CENTRAL_CODEX_AUTH_ROOT '/app/runtime/hermes/codex-auth-pool')"
IFS=',' read -r -a CENTRAL_CODEX_ACCOUNTS <<< "$CENTRAL_CODEX_ACCOUNT_IDS"
central_codex_pool_valid=true
central_codex_seen=','
if (( ${#CENTRAL_CODEX_ACCOUNTS[@]} < 2 || ${#CENTRAL_CODEX_ACCOUNTS[@]} > 8 )); then
  central_codex_pool_valid=false
else
  for account_id in "${CENTRAL_CODEX_ACCOUNTS[@]}"; do
    if [[ ! "$account_id" =~ ^[a-z0-9][a-z0-9_-]{0,31}$ || "$central_codex_seen" == *",$account_id,"* ]]; then
      central_codex_pool_valid=false
    fi
    central_codex_seen="$central_codex_seen$account_id,"
  done
fi
if [[ "$central_codex_pool_valid" == true ]]; then
  ok "central Codex auth pool declares ${#CENTRAL_CODEX_ACCOUNTS[@]} accounts"
elif [[ "$MODE" == server && "$CENTRAL_IMAGE_READY" == true ]]; then
  fail 'central Codex auth pool must declare 2-8 unique account IDs when central images are enabled'
else
  warn 'central Codex auth pool must declare 2-8 unique account IDs before activation'
fi
if [[ "$MODE" == server && "$CENTRAL_IMAGE_READY" == true ]]; then
  # The Compose variable is the in-container mount. On the host, the bind
  # source is fixed and private; never accept a caller-selected path here.
  central_codex_host_root="/srv/admira/shared/central-codex-auth"
  central_codex_service_uid="$(resolve_compose_value ADMIRA_SERVICE_UID 1001)"
  if [[ "$CENTRAL_CODEX_AUTH_ROOT" != "/app/runtime/hermes/codex-auth-pool" ]]; then
    fail 'ADMIRA_CENTRAL_CODEX_AUTH_ROOT must be /app/runtime/hermes/codex-auth-pool'
  fi
  if [[ -L "$central_codex_host_root" || ! -d "$central_codex_host_root" ]]; then
    fail "central Codex auth pool root is missing: $central_codex_host_root"
  else
    pool_mode=$(stat -c '%a' "$central_codex_host_root" 2>/dev/null || stat -f '%Lp' "$central_codex_host_root")
    pool_owner=$(stat -c '%u' "$central_codex_host_root" 2>/dev/null || stat -f '%u' "$central_codex_host_root")
    [[ "$pool_mode" =~ ^0*700$ && "$pool_owner" == "$central_codex_service_uid" ]] \
      && ok 'central Codex auth pool root is private and service-owned' \
      || fail 'central Codex auth pool root must be mode 0700 and service-owned'
    if [[ "$central_codex_pool_valid" == true ]]; then
      for account_id in "${CENTRAL_CODEX_ACCOUNTS[@]}"; do
        account_home="$central_codex_host_root/$account_id"
        auth_json="$account_home/auth.json"
        if [[ -L "$account_home" || ! -d "$account_home" ]]; then
          fail "central Codex auth home is missing: $account_id"
        else
          home_mode=$(stat -c '%a' "$account_home" 2>/dev/null || stat -f '%Lp' "$account_home")
          home_owner=$(stat -c '%u' "$account_home" 2>/dev/null || stat -f '%u' "$account_home")
          [[ "$home_mode" =~ ^0*700$ && "$home_owner" == "$central_codex_service_uid" ]] \
            && ok "central Codex auth home is private: $account_id" \
            || fail "central Codex auth home must be mode 0700 and service-owned: $account_id"
          if [[ -L "$auth_json" || ! -f "$auth_json" || ! -s "$auth_json" ]]; then
            fail "central Codex auth.json is missing or empty: $account_id"
          else
            auth_mode=$(stat -c '%a' "$auth_json" 2>/dev/null || stat -f '%Lp' "$auth_json")
            auth_owner=$(stat -c '%u' "$auth_json" 2>/dev/null || stat -f '%u' "$auth_json")
            [[ "$auth_mode" =~ ^(0*600|0*400)$ && "$auth_owner" == "$central_codex_service_uid" ]] \
              && ok "central Codex auth.json is private: $account_id" \
              || fail "central Codex auth.json must be mode 0600/0400 and service-owned: $account_id"
          fi
        fi
      done
    fi
  fi
elif [[ "$central_codex_pool_valid" == true ]]; then
  warn 'central Codex auth homes are checked only when central images are enabled in server mode'
fi
if [[ "$CENTRAL_IMAGE_IMAGE" == "$CENTRAL_IMAGE_PLACEHOLDER" && "$CENTRAL_IMAGE_READY" == true ]]; then
  fail 'central images cannot be enabled with the all-zero image placeholder'
elif [[ "$CENTRAL_IMAGE_IMAGE" == "$CENTRAL_IMAGE_PLACEHOLDER" ]]; then
  warn 'central image uses the dormant all-zero placeholder; install the clean canary tag before activation'
elif [[ "$CENTRAL_IMAGE_IMAGE" =~ ^admira-ia-hosted:r91-canary-[0-9a-f]{12}$ ]]; then
  ok "central image is pinned to exact hosted canary tag: $CENTRAL_IMAGE_IMAGE"
else
  fail 'CENTRAL_IMAGE_IMAGE must be an exact admira-ia-hosted:r91-canary-<12 lowercase commit hex> tag'
fi

if [[ "$MODE" == server ]] && docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" \
    --profile operator-dashboard ps --status running --services 2>/dev/null | grep -qx operator-dashboard; then
  CHECK_OPERATOR=true
fi
if [[ "$CHECK_OPERATOR" == true && "$CENTRAL_IMAGE_IMAGE" == "$CENTRAL_IMAGE_PLACEHOLDER" ]]; then
  fail 'operator dashboard requires a real pinned CENTRAL_IMAGE_IMAGE, not the dormant placeholder'
fi
operator_setup_cidrs="$(resolve_compose_value ADMIRA_OPERATOR_SETUP_CIDRS '127.0.0.1/32,::1/128')"
if python3 - "$operator_setup_cidrs" <<'PY'
import ipaddress, sys
try:
    networks = [ipaddress.ip_network(value.strip(), strict=True) for value in sys.argv[1].split(',')]
    assert 1 <= len(networks) <= 8
    assert all(net.prefixlen == net.max_prefixlen and not net.network_address.is_unspecified for net in networks)
except (ValueError, AssertionError):
    sys.exit(1)
PY
then ok 'operator setup source allowlist contains exact IPs only'; else fail 'ADMIRA_OPERATOR_SETUP_CIDRS must contain only exact /32 or /128 addresses'; fi
if [[ "$MODE" == server && "$CHECK_OPERATOR" == true ]]; then
  operator_uid="$(resolve_compose_value ADMIRA_SERVICE_UID 1001)"
  for operator_dir in "$ROOT_DIR/secrets/operator-password" /etc/admira/gemini-pool /srv/admira/shared/central-codex-auth /srv/admira/shared/central-codex-auth/primary /srv/admira/shared/central-codex-auth/secondary; do
    if [[ -L "$operator_dir" || ! -d "$operator_dir" ]]; then
      fail "operator private directory is absent or unsafe: $operator_dir"
      continue
    fi
    operator_mode=$(stat -c '%a' "$operator_dir" 2>/dev/null || stat -f '%Lp' "$operator_dir")
    operator_owner=$(stat -c '%u' "$operator_dir" 2>/dev/null || stat -f '%u' "$operator_dir")
    [[ "$operator_mode" =~ ^0*700$ && "$operator_owner" == "$operator_uid" ]] \
      && ok "operator private directory is service-owned: $operator_dir" \
      || fail "operator private directory must be mode 0700 and service-owned: $operator_dir"
  done
  for operator_secret in "$ROOT_DIR/secrets/operator_db_password.txt" "$ROOT_DIR/secrets/operator-password/password.hash"; do
    if [[ "$operator_secret" == */password.hash && ! -e "$operator_secret" && ! -L "$operator_secret" ]]; then
      warn 'operator first-run password setup is pending; complete it through the SSH tunnel'
      continue
    fi
    if [[ -L "$operator_secret" || ! -f "$operator_secret" || ! -s "$operator_secret" ]]; then
      fail 'operator secret is absent, empty or unsafe'
      continue
    fi
    operator_mode=$(stat -c '%a' "$operator_secret" 2>/dev/null || stat -f '%Lp' "$operator_secret")
    operator_owner=$(stat -c '%u' "$operator_secret" 2>/dev/null || stat -f '%u' "$operator_secret")
    [[ "$operator_mode" =~ ^(0*600|0*400)$ && "$operator_owner" == "$operator_uid" ]] \
      && ok 'operator secret is private and service-owned' \
      || fail 'operator secret must be mode 0600/0400 and service-owned'
  done
  provisioner_gid="$(resolve_compose_value ADMIRA_PROVISIONER_GID 19094)"
  if systemctl is-active --quiet admira-tenant-provisioner.service; then
    ok 'tenant provisioner is active'
  else
    fail 'tenant provisioner is not active'
  fi
  provisioner_write_paths="$(systemctl show admira-tenant-provisioner.service -p ReadWritePaths --value 2>/dev/null || true)"
  if [[ "$provisioner_write_paths" == *"/srv/admira/tenants"* \
     && "$provisioner_write_paths" == *"/etc/admira/gemini-pool"* \
     && "$provisioner_write_paths" == *"/etc/admira/central-image-keys"* \
     && "$provisioner_write_paths" == *"/srv/admira/shared/central-image-exchange"* ]]; then
    ok 'tenant provisioner sandbox permits only required tenant and provider roots'
  else
    fail 'tenant provisioner sandbox is missing a required lifecycle write root'
  fi
  if [[ -S /run/admira-tenant-provisioner/provisioner.sock ]]; then
    provisioner_socket_group="$(stat -c '%g' /run/admira-tenant-provisioner/provisioner.sock 2>/dev/null || stat -f '%g' /run/admira-tenant-provisioner/provisioner.sock)"
    [[ "$provisioner_socket_group" == "$provisioner_gid" ]] \
      && ok 'tenant provisioner socket uses the dashboard-only group' \
      || fail 'tenant provisioner socket group does not match ADMIRA_PROVISIONER_GID'
  else
    fail 'tenant provisioner socket is missing'
  fi
  for provisioner_secret in /etc/admira/tenant-provisioner.key /etc/admira/hosted-license-bridge.key; do
    if [[ -L "$provisioner_secret" || ! -f "$provisioner_secret" || ! -s "$provisioner_secret" ]]; then
      fail 'tenant provisioner private key is absent or unsafe'
      continue
    fi
    provisioner_mode="$(stat -c '%a' "$provisioner_secret" 2>/dev/null || stat -f '%Lp' "$provisioner_secret")"
    provisioner_owner="$(stat -c '%u' "$provisioner_secret" 2>/dev/null || stat -f '%u' "$provisioner_secret")"
    [[ "$provisioner_mode" =~ ^0*600$ && "$provisioner_owner" == "$operator_uid" ]] \
      && ok 'tenant provisioner private key is service-owned' \
      || fail 'tenant provisioner private key must be mode 0600 and service-owned'
  done
elif [[ "$CHECK_OPERATOR" != true ]]; then
  warn 'operator profile remains opt-in; use --operator-dashboard for its host readiness gate'
fi

TOKEN="$ROOT_DIR/secrets/telegram_bot_token.txt"
if [[ -f "$TOKEN" && -s "$TOKEN" ]]; then
  mode=$(stat -c '%a' "$TOKEN" 2>/dev/null || stat -f '%Lp' "$TOKEN")
  if [[ "$mode" =~ ^0*600$|^0*400$ ]]; then ok 'Telegram token is present with private permissions'; else fail 'Telegram token permissions must be 0600 or 0400'; fi
else
  if [[ "$MODE" == server ]]; then fail 'Telegram token is absent or empty'; else warn 'Telegram token is intentionally absent in local preparation'; fi
fi

LEGACY_GEMINI_SOURCE="$ROOT_DIR/secrets/hosted_gemini_api_key.txt"
if [[ -e "$LEGACY_GEMINI_SOURCE" ]]; then
  if [[ "$MODE" == server ]]; then
    fail 'legacy hosted Gemini seed file must be migrated to the audited pool and removed'
  else
    warn 'legacy hosted Gemini seed file exists; it is ignored and must not ship'
  fi
fi

if [[ "$MODE" == server ]]; then
  if systemctl is-active --quiet admira-runtime-broker.service; then ok 'runtime broker is active'; else fail 'runtime broker is not active'; fi
  if [[ -S /run/admira-runtime-broker/broker.sock ]]; then ok 'runtime broker socket exists'; else fail 'runtime broker socket is missing'; fi
  if [[ -f /etc/admira/runtime-broker.key ]]; then
    key_mode=$(stat -c '%a' /etc/admira/runtime-broker.key 2>/dev/null || stat -f '%Lp' /etc/admira/runtime-broker.key)
    [[ "$key_mode" =~ ^0*600$ ]] && ok 'broker key is private' || fail 'broker key permissions must be 0600'
  else fail 'broker key is missing'; fi
  if [[ -e /etc/admira/hosted-gemini-api-key ]]; then
    fail 'legacy host-wide Gemini key must be migrated to /etc/admira/gemini-pool and removed'
  else
    ok 'legacy host-wide Gemini key is absent'
  fi
  if docker image inspect admira-ia:r90 >/dev/null 2>&1; then ok 'tenant image admira-ia:r90 is present'; else fail 'tenant image admira-ia:r90 is missing'; fi
  if [[ "$CENTRAL_IMAGE_IMAGE" == "$CENTRAL_IMAGE_PLACEHOLDER" ]]; then
    warn 'pinned central canary image is not selected; central images remain dormant'
  elif docker image inspect "$CENTRAL_IMAGE_IMAGE" >/dev/null 2>&1; then
    ok "pinned central canary image is present: $CENTRAL_IMAGE_IMAGE"
  elif [[ "$CENTRAL_IMAGE_READY" == true || "$CHECK_OPERATOR" == true ]]; then
    fail "pinned central canary image is missing while central images or operator dashboard are requested: $CENTRAL_IMAGE_IMAGE"
  else
    warn "pinned central canary image is not installed; central images remain dormant: $CENTRAL_IMAGE_IMAGE"
  fi
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
  lifecycle_check_sql="SELECT
  EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'admira' AND table_name = 'tenant_entitlements'
      AND column_name = 'image_sponsorship_ends_at'
  )
  AND to_regclass('admira.tenant_provider_credentials') IS NOT NULL
  AND (
    SELECT count(*) = 4
    FROM pg_proc AS p
    JOIN pg_namespace AS n ON n.oid = p.pronamespace
    WHERE n.nspname = 'admira'
      AND p.proname IN (
        'resolve_tenant_image_access', 'expire_due_trials',
        'record_tenant_provider_credential', 'transition_hosted_tenant_to_licensed'
      )
  )
  AND EXISTS (
    SELECT 1 FROM pg_proc AS p JOIN pg_namespace AS n ON n.oid = p.pronamespace
    WHERE n.nspname = 'admira' AND p.proname = 'resolve_tenant_image_access'
      AND pg_get_functiondef(p.oid) LIKE '%personal_chatgpt%'
      AND pg_get_functiondef(p.oid) LIKE '%t.status <> ''active''%'
  );"
  if printf '%s\n' "$lifecycle_check_sql" | \
      docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" exec -T postgres \
      sh -ec 'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; exec psql -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
      2>/dev/null | grep -qx t; then
    ok 'trial, licensing and sponsored-image lifecycle is visible in PostgreSQL'
  else
    fail 'trial/licensing lifecycle migration is not visible in PostgreSQL'
  fi
  central_image_check_sql="SELECT
  to_regclass('admira.central_image_jobs') IS NOT NULL
  AND (
    SELECT count(*) = 3
    FROM pg_proc AS p JOIN pg_namespace AS n ON n.oid = p.pronamespace
    WHERE n.nspname = 'admira'
      AND p.proname IN (
        'begin_central_image_job_for_runtime',
        'complete_central_image_job',
        'fail_central_image_job'
      )
  )
  AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admira_image')
  AND NOT has_table_privilege('admira_image', 'admira.central_image_jobs', 'SELECT');"
  if printf '%s\n' "$central_image_check_sql" | \
      docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" exec -T postgres \
      sh -ec 'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; exec psql -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
      2>/dev/null | grep -qx t; then
    ok 'durable central-image ledger and least-privilege role are visible in PostgreSQL'
  else
    fail 'central-image ledger migration is not visible in PostgreSQL'
  fi
  recovery_check_sql="SELECT
  to_regclass('admira.tenant_license_contacts') IS NOT NULL
  AND to_regclass('admira.tenant_recovery_challenges') IS NOT NULL
  AND to_regclass('admira.telegram_recovery_chat_outbox') IS NOT NULL
  AND to_regclass('admira.tenant_recovery_delivery_outbox') IS NOT NULL
  AND (
    SELECT count(*) = 6
    FROM pg_proc AS p JOIN pg_namespace AS n ON n.oid = p.pronamespace
    WHERE n.nspname = 'admira'
      AND p.proname IN (
        'register_verified_license_contact', 'begin_telegram_recovery',
        'confirm_telegram_recovery', 'claim_recovery_chat_outbox',
        'claim_recovery_email_outbox', 'ack_recovery_email_outbox'
      )
  )
  AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admira_recovery')
  AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admira_email_delivery')
  AND NOT has_table_privilege('admira_ingress', 'admira.tenant_license_contacts', 'SELECT')
  AND NOT has_table_privilege('admira_email_delivery', 'admira.tenant_recovery_delivery_outbox', 'SELECT');"
  if printf '%s\n' "$recovery_check_sql" | \
      docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" exec -T postgres \
      sh -ec 'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; exec psql -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
      2>/dev/null | grep -qx t; then
    ok 'Telegram license-recovery schema and least-privilege role are visible in PostgreSQL'
  else
    fail 'Telegram license-recovery migration is not visible in PostgreSQL'
  fi
  pool_check_sql="SELECT
  to_regclass('admira.gemini_pool_projects') IS NOT NULL
  AND to_regclass('admira.gemini_pool_credentials') IS NOT NULL
  AND to_regclass('admira.gemini_pool_assignments') IS NOT NULL
  AND (
    SELECT count(*) = 3
    FROM pg_proc AS p JOIN pg_namespace AS n ON n.oid = p.pronamespace
    WHERE n.nspname = 'admira'
      AND p.proname IN ('assign_hosted_gemini_trial', 'finalize_hosted_gemini_trial', 'release_hosted_gemini_trial')
  );"
  if printf '%s\n' "$pool_check_sql" | \
      docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" exec -T postgres \
      sh -ec 'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; exec psql -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
      2>/dev/null | grep -qx t; then
    ok 'Gemini operator pool migration and hosted assignment functions are visible in PostgreSQL'
  else
    fail 'Gemini operator pool migration is not visible in PostgreSQL'
  fi
  operator_check_sql="SELECT
  to_regprocedure('admira.operator_gemini_pool_status()') IS NOT NULL
  AND to_regprocedure('admira.operator_tenant_sponsorship_status()') IS NOT NULL
  AND to_regprocedure('admira.operator_set_image_sponsorship_end(text,timestamp with time zone)') IS NOT NULL
  AND to_regprocedure('admira.operator_trial_accounts()') IS NOT NULL
  AND to_regprocedure('admira.operator_licensed_accounts()') IS NOT NULL
  AND to_regprocedure('admira.operator_create_trial(text,text,text)') IS NOT NULL
  AND to_regprocedure('admira.operator_extend_trial(text,timestamp with time zone,text)') IS NOT NULL
  AND to_regprocedure('admira.operator_expire_trial(text,text)') IS NOT NULL
  AND to_regprocedure('admira.issue_trial_telegram_claim(text,text,integer)') IS NOT NULL
  AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admira_operator' AND NOT rolcanlogin AND NOT rolsuper AND NOT rolbypassrls)
  AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admira_operator_login' AND rolcanlogin AND NOT rolsuper AND NOT rolbypassrls)
  AND pg_has_role('admira_operator_login', 'admira_operator', 'MEMBER')
  AND NOT pg_has_role('admira_operator_login', 'admira_provisioner', 'MEMBER')
  AND has_function_privilege('admira_operator', 'admira.operator_gemini_pool_status()', 'EXECUTE')
  AND has_function_privilege('admira_operator', 'admira.register_gemini_pool_project(text,integer,text)', 'EXECUTE')
  AND has_function_privilege('admira_operator', 'admira.register_gemini_pool_credential(uuid,text,text,text,text)', 'EXECUTE')
  AND has_function_privilege('admira_operator', 'admira.operator_tenant_sponsorship_status()', 'EXECUTE')
  AND has_function_privilege('admira_operator', 'admira.operator_set_image_sponsorship_end(text,timestamp with time zone)', 'EXECUTE')
  AND has_function_privilege('admira_operator', 'admira.operator_trial_accounts()', 'EXECUTE')
  AND has_function_privilege('admira_operator', 'admira.operator_licensed_accounts()', 'EXECUTE')
  AND NOT has_function_privilege('admira_operator', 'admira.operator_create_trial(text,text,text)', 'EXECUTE')
  AND NOT has_function_privilege('admira_operator', 'admira.operator_extend_trial(text,timestamp with time zone,text)', 'EXECUTE')
  AND NOT has_function_privilege('admira_operator', 'admira.operator_expire_trial(text,text)', 'EXECUTE')
  AND has_function_privilege('admira_provisioner', 'admira.operator_create_trial(text,text,text)', 'EXECUTE')
  AND has_function_privilege('admira_provisioner', 'admira.operator_extend_trial(text,timestamp with time zone,text)', 'EXECUTE')
  AND has_function_privilege('admira_provisioner', 'admira.operator_expire_trial(text,text)', 'EXECUTE')
  AND has_function_privilege('admira_provisioner', 'admira.issue_trial_telegram_claim(text,text,integer)', 'EXECUTE')
  AND NOT has_function_privilege('admira_operator', 'admira.assign_hosted_gemini_trial(text)', 'EXECUTE')
  AND NOT has_table_privilege('admira_operator', 'admira.gemini_pool_projects', 'SELECT,INSERT,UPDATE,DELETE')
  AND NOT has_table_privilege('admira_operator', 'admira.tenant_entitlements', 'SELECT,INSERT,UPDATE,DELETE')
  AND NOT has_table_privilege('admira_operator', 'admira.tenant_license_contacts', 'SELECT');"
  if printf '%s\n' "$operator_check_sql" | \
      docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" exec -T postgres \
      sh -ec 'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; exec psql -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
      2>/dev/null | grep -qx t; then
    ok 'operator dashboard migration and dedicated least-privilege login are visible in PostgreSQL'
  else
    fail 'operator dashboard migration or dedicated login boundary is missing'
  fi
else
  grep -q 'admira-ia:r90' "$ROOT_DIR/tenantctl.py" && ok 'tenant image pin is admira-ia:r90' || fail 'tenant image pin is not admira-ia:r90'
  grep -q 'status = '\''active'\''' "$ROOT_DIR/db/migrations/004_active_tenant_runtime_gate.sql" && ok 'active-tenant migration contains gate' || fail 'active-tenant migration gate missing'
  grep -q "p_error_code = 'telegram_rate_limited'" "$ROOT_DIR/db/migrations/005_telegram_rate_limit_retry.sql" && ok 'Telegram rate-limit migration preserves retries' || fail 'Telegram rate-limit retry migration gate missing'
  grep -q 'attempt_count = greatest(0, attempt_count - 1)' "$ROOT_DIR/db/migrations/006_runtime_capacity_queue.sql" \
    && grep -q 'FOR UPDATE OF runtime SKIP LOCKED' "$ROOT_DIR/db/migrations/006_runtime_capacity_queue.sql" \
    && ok 'capacity migration preserves failure budget and fences LRU claims' \
    || fail 'capacity migration safety gates missing'
  grep -q "e.trial_ends_at > now()" "$ROOT_DIR/db/migrations/007_trial_provider_lifecycle.sql" \
    && grep -q "CASE WHEN e.licensed_at IS NULL" "$ROOT_DIR/db/migrations/007_trial_provider_lifecycle.sql" \
    && grep -q "coalesce(e.image_sponsorship_ends_at, e.trial_ends_at, now_value)" "$ROOT_DIR/db/migrations/007_trial_provider_lifecycle.sql" \
    && grep -q "THEN 'personal_chatgpt'" "$ROOT_DIR/db/migrations/007_trial_provider_lifecycle.sql" \
    && grep -q "t.status <> 'active' THEN 'blocked'" "$ROOT_DIR/db/migrations/007_trial_provider_lifecycle.sql" \
    && ok 'trial/licensing migration preserves one five-day sponsorship and personal ChatGPT boundaries' \
    || fail 'trial/licensing migration safety gates missing'
  grep -q 'ADMIRA_CENTRAL_IMAGE_READY.*:-false' "$ROOT_DIR/compose.yaml" \
    && ok 'central image service remains fail-closed by default' \
    || fail 'central image service default must remain false'
  grep -q 'begin_central_image_job_for_runtime' "$ROOT_DIR/db/migrations/008_central_image_jobs.sql" \
    && grep -q 'TO admira_image' "$ROOT_DIR/db/migrations/008_central_image_jobs.sql" \
    && grep -q "existing.available_at > now()" "$ROOT_DIR/db/migrations/008_central_image_jobs.sql" \
    && ok 'central image ledger is runtime-keyed, fenced and backoff-aware' \
    || fail 'central image ledger safety gates missing'
  grep -q 'CREATE TABLE IF NOT EXISTS admira.tenant_license_contacts' "$ROOT_DIR/db/migrations/009_telegram_license_recovery.sql" \
    && grep -q 'CREATE TABLE IF NOT EXISTS admira.tenant_recovery_challenges' "$ROOT_DIR/db/migrations/009_telegram_license_recovery.sql" \
    && grep -q 'CREATE TABLE IF NOT EXISTS admira.telegram_recovery_chat_outbox' "$ROOT_DIR/db/migrations/009_telegram_license_recovery.sql" \
    && grep -q 'CREATE OR REPLACE FUNCTION admira.begin_telegram_recovery' "$ROOT_DIR/db/migrations/009_telegram_license_recovery.sql" \
    && grep -q 'CREATE OR REPLACE FUNCTION admira.confirm_telegram_recovery' "$ROOT_DIR/db/migrations/009_telegram_license_recovery.sql" \
    && grep -q 'GRANT EXECUTE ON FUNCTION admira.begin_telegram_recovery' "$ROOT_DIR/db/migrations/009_telegram_license_recovery.sql" \
    && grep -q "'recovery_pending'" "$ROOT_DIR/db/migrations/009_telegram_license_recovery.sql" \
    && ok 'Telegram recovery migration and database boundaries are present' \
    || fail 'Telegram recovery migration safety gates missing'
  if grep -q 'CREATE TABLE IF NOT EXISTS admira.gemini_pool_projects' "$ROOT_DIR/db/migrations/010_operator_gemini_pool.sql" \
    && grep -q 'key_kind.*auth' "$ROOT_DIR/db/migrations/010_operator_gemini_pool.sql" \
    && grep -q 'assign_hosted_gemini_trial' "$ROOT_DIR/db/migrations/010_operator_gemini_pool.sql" \
    && grep -q 'finalize_hosted_gemini_trial' "$ROOT_DIR/db/migrations/010_operator_gemini_pool.sql" \
    && grep -q 'release_hosted_gemini_trial' "$ROOT_DIR/db/migrations/010_operator_gemini_pool.sql" \
    && grep -q 'project-fixture' "$ROOT_DIR/db/validate_operator_gemini_pool.sql"; then
    ok 'Gemini operator pool migration and disposable validator are present'
  else
    fail 'Gemini operator pool safety gates missing'
  fi
  if grep -q 'CREATE ROLE admira_operator NOLOGIN NOBYPASSRLS' "$ROOT_DIR/db/migrations/011_operator_dashboard.sql" \
    && grep -q 'operator_gemini_pool_status' "$ROOT_DIR/db/migrations/011_operator_dashboard.sql" \
    && grep -q 'operator_set_image_sponsorship_end' "$ROOT_DIR/db/migrations/012_personal_chatgpt_sponsorship.sql" \
    && grep -q 'sponsorship cannot be shortened' "$ROOT_DIR/db/migrations/012_personal_chatgpt_sponsorship.sql" \
    && grep -q 'REVOKE admira_provisioner FROM admira_operator_login' "$ROOT_DIR/db/bootstrap_service_roles.sql" \
    && grep -q 'operator_dashboard_validation=passed' "$ROOT_DIR/db/validate_operator_dashboard.sql" \
    && grep -q 'personal_chatgpt_sponsorship_validation=passed' "$ROOT_DIR/db/validate_personal_chatgpt_sponsorship.sql" \
    && grep -q 'operator_create_trial' "$ROOT_DIR/db/migrations/013_operator_trial_provisioning.sql" \
    && grep -q 'issue_trial_telegram_claim' "$ROOT_DIR/db/migrations/013_operator_trial_provisioning.sql" \
    && grep -q 'operator_trial_provisioning_validation=passed' "$ROOT_DIR/db/validate_operator_trial_provisioning.sql"; then
    ok 'operator dashboard, customer lifecycle, sponsorship policy and disposable validators are present'
  else
    fail 'operator dashboard database boundary is missing'
  fi
  grep -q 'assign_hosted_gemini_trial' "$ROOT_DIR/gemini_pool_admin.py" \
    && grep -q 'runtime_fence' "$ROOT_DIR/gemini_pool_admin.py" \
    && grep -q 'record_metadata=record_metadata' "$ROOT_DIR/gemini_pool_admin.py" \
    && grep -q 'cleanup_pending' "$ROOT_DIR/gemini_pool_admin.py" \
    && grep -q 'explicit operator assertion' "$ROOT_DIR/gemini_pool_admin.py" \
    && ok 'operator pool CLI enforces hosted assignment, runtime fence, DB finalization and cleanup reporting' \
    || fail 'operator pool CLI safety gates missing'
  if grep -q 'GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1"' "$ROOT_DIR/provider_admin.py" \
    && grep -q 'x-goog-api-client.*admira-hosted/r91' "$ROOT_DIR/provider_admin.py" \
    && grep -q 'x-goog-api-key' "$ROOT_DIR/provider_admin.py" \
    && grep -q 'allow-unverified' "$ROOT_DIR/provider_admin.py" \
    && grep -q 'effective_health_check = health_check or gemini_health_check' "$ROOT_DIR/provider_admin.py"; then
    ok 'Gemini credential health check is official-endpoint, header-only and required by default'
  else
    fail 'Gemini credential health-check gate is missing'
  fi
  if grep -q 'class ProvisionerClient' "$ROOT_DIR/operator_dashboard.py" \
    && grep -q 'class ProvisionerCore' "$ROOT_DIR/tenant_provisioner.py" \
    && grep -q 'license_trial' "$ROOT_DIR/tenant_provisioner.py" \
    && grep -q 'tenant_provisioner_key' "$ROOT_DIR/bootstrap-control-plane.sh" \
    && grep -q 'SupplementaryGroups=docker' "$ROOT_DIR/install-tenant-provisioner.sh" \
    && grep -q '/etc/admira/central-image-keys' "$ROOT_DIR/install-tenant-provisioner.sh" \
    && grep -q '/srv/admira/shared/central-image-exchange' "$ROOT_DIR/install-tenant-provisioner.sh" \
    && grep -q 'ADMIRA_PROVISIONER_SOCKET' "$ROOT_DIR/compose.yaml" \
    && ! grep -q '/var/run/docker.sock' "$ROOT_DIR/compose.yaml"; then
    ok 'customer lifecycle uses the signed host provisioner without dashboard Docker access'
  else
    fail 'customer lifecycle host boundary is incomplete'
  fi
fi

if grep -q 'RecoveryHandler' "$ROOT_DIR/telegram_ingress.py" \
  && grep -q 'handle_unbound' "$ROOT_DIR/telegram_ingress.py" \
  && grep -q 'recovery_email' "$ROOT_DIR/hosted_service.py"; then
  ok 'Telegram recovery runtime and email-worker integration is present'
else
  fail 'Telegram recovery runtime or email-worker integration is missing'
fi

if [[ "$MODE" == server ]]; then
  recovery_ready="$(resolve_compose_value ADMIRA_TELEGRAM_RECOVERY_READY false | tr '[:upper:]' '[:lower:]')"
  case "$recovery_ready" in
    false|0|no|off|'')
      warn 'Telegram recovery is dormant; enable only after SMTP/domain and recovery canaries pass'
      ;;
    true|1|yes|on)
      ok 'Telegram recovery readiness flag is explicitly enabled'
      recovery_smtp_host="$(resolve_compose_value ADMIRA_SMTP_HOST '')"
      recovery_smtp_from="$(resolve_compose_value ADMIRA_SMTP_FROM '')"
      recovery_smtp_security="$(resolve_compose_value ADMIRA_SMTP_SECURITY starttls)"
      if [[ -n "$recovery_smtp_host" && -n "$recovery_smtp_from" ]]; then
        ok 'recovery SMTP host and sender are configured'
      else
        fail 'ADMIRA_SMTP_HOST and ADMIRA_SMTP_FROM are required when recovery is enabled'
      fi
      case "$recovery_smtp_security" in
        starttls|ssl) ok 'recovery SMTP transport requires encrypted security' ;;
        *) fail 'ADMIRA_SMTP_SECURITY must be starttls or ssl when recovery is enabled' ;;
      esac
      recovery_service_uid="$(resolve_compose_value ADMIRA_SERVICE_UID 1001)"
      if [[ "$recovery_service_uid" =~ ^[0-9]+$ ]]; then
        ok "recovery service UID configured: $recovery_service_uid"
      else
        fail 'ADMIRA_SERVICE_UID must be a numeric UID when recovery is enabled'
      fi
      for recovery_secret in recovery_hmac_key.txt recovery_delivery_key.txt recovery_db_password.txt email_delivery_db_password.txt smtp_username.txt smtp_password.txt; do
        recovery_secret_path="$ROOT_DIR/secrets/$recovery_secret"
        if [[ -s "$recovery_secret_path" ]]; then
          recovery_secret_mode=$(stat -c '%a' "$recovery_secret_path" 2>/dev/null || stat -f '%Lp' "$recovery_secret_path")
          if [[ "$recovery_secret_mode" =~ ^0*600$ ]]; then
            ok "recovery secret is present with mode 0600: $recovery_secret"
          else
            fail "recovery secret permissions must be exactly 0600: $recovery_secret"
          fi
          recovery_secret_owner=$(stat -c '%u' "$recovery_secret_path" 2>/dev/null || stat -f '%u' "$recovery_secret_path")
          if [[ "$recovery_secret_owner" == "$recovery_service_uid" ]]; then
            ok "recovery secret owner matches service UID: $recovery_secret"
          else
            fail "recovery secret owner UID must be $recovery_service_uid: $recovery_secret"
          fi
        else
          fail "recovery secret is absent or empty: $recovery_secret"
        fi
      done
      # The worker and SMTP are prepared and running before the readiness flag
      # is flipped. Then rerun preflight with true, recreate the poller, and
      # only after that perform the end-to-end recovery canary.
      if docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" \
          --profile recovery-email ps --status running --services 2>/dev/null | grep -qx 'recovery-email'; then
        ok 'recovery-email worker is running while recovery is enabled'
      else
        fail 'recovery-email worker is not running while recovery is enabled'
      fi
      ;;
    *) fail 'ADMIRA_TELEGRAM_RECOVERY_READY must be false or true' ;;
  esac
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
