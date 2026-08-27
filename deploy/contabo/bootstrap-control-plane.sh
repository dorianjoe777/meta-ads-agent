#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_DIR="$ROOT_DIR/secrets"

umask 077
install -d -m 700 "$SECRETS_DIR"

if [[ ! -s "$SECRETS_DIR/postgres_password.txt" ]]; then
  openssl rand -base64 48 | tr -d '\n' > "$SECRETS_DIR/postgres_password.txt"
  printf '\n' >> "$SECRETS_DIR/postgres_password.txt"
fi

if [[ ! -s "$SECRETS_DIR/redis_users.acl" ]]; then
  redis_password="$(openssl rand -base64 48 | tr -d '\n')"
  printf 'user default on >%s ~* &* +@all\n' "$redis_password" > "$SECRETS_DIR/redis_users.acl"
  unset redis_password
fi

chmod 600 "$SECRETS_DIR/postgres_password.txt" "$SECRETS_DIR/redis_users.acl"

if [[ ! -f "$ROOT_DIR/.env" ]]; then
  install -m 600 "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
fi

docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" config --quiet
printf '%s\n' 'Control-plane configuration and private secrets are ready.'
