#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" up -d postgres redis

ready=false
for _attempt in $(seq 1 30); do
  if docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" exec -T postgres \
    sh -ec 'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; psql -qAt -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT 1"' \
    2>/dev/null | grep -qx 1; then
    ready=true
    break
  fi
  sleep 2
done
if [[ "$ready" != true ]]; then
  printf '%s\n' 'PostgreSQL did not become ready in time.' >&2
  exit 1
fi

docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" exec -T postgres \
  sh -ec 'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; for migration in /docker-entrypoint-initdb.d/*.sql; do psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "$migration"; done'

# Feed this file over stdin instead of bind-mounting one inode. Atomic release
# copies may replace the host inode while a long-lived PostgreSQL container
# still sees the former file through its original bind mount.
docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" exec -T postgres \
  sh -ec 'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < "$ROOT_DIR/db/bootstrap_service_roles.sql"

printf '%s\n' 'Control-plane migrations and least-privilege service roles are current.'
