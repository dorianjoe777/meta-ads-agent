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

for secret_name in ingress_db_password runtime_db_password delivery_db_password scheduler_db_password provisioner_db_password image_db_password recovery_db_password email_delivery_db_password runtime_broker_key recovery_hmac_key; do
  secret_path="$SECRETS_DIR/${secret_name}.txt"
  if [[ ! -s "$secret_path" ]]; then
    openssl rand -base64 48 | tr -d '\n' > "$secret_path"
    printf '\n' >> "$secret_path"
  fi
done

# AES-256-GCM key, stored as strict base64 so the Python boundary can validate
# exact key length before constructing the recovery envelope cipher.
if [[ ! -s "$SECRETS_DIR/recovery_delivery_key.txt" ]]; then
  openssl rand -base64 32 | tr -d '\n' > "$SECRETS_DIR/recovery_delivery_key.txt"
  printf '\n' >> "$SECRETS_DIR/recovery_delivery_key.txt"
fi

# Buyer traffic is deliberately disabled until this file contains the shared
# bot token and the Compose `buyers` profile is explicitly started.
touch "$SECRETS_DIR/telegram_bot_token.txt"
# Real SMTP credentials are operator-supplied only. Empty files keep Compose
# configuration renderable without pretending that email delivery is ready.
touch "$SECRETS_DIR/smtp_username.txt" "$SECRETS_DIR/smtp_password.txt"
chmod 600 "$SECRETS_DIR"/*.txt "$SECRETS_DIR/redis_users.acl"

if [[ ! -f "$ROOT_DIR/.env" ]]; then
  install -m 600 "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
fi

docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/compose.yaml" config --quiet
printf '%s\n' 'Control-plane configuration and private secrets are ready.'
