#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_DIR="$ROOT_DIR/secrets"

usage() {
  printf '%s\n' 'Usage: bootstrap-control-plane.sh [--prepare-operator-host-dirs]'
}

# Host bind sources cannot be allowed to spring into existence as root-owned
# Docker-created directories. This explicit root-only mode prepares only the
# dashboard's existing provider pools and exits before touching release-local
# secrets. It never creates a password or auth.json.
if [[ "${1:-}" == "--prepare-operator-host-dirs" ]]; then
  shift
  if [[ $# -gt 0 ]]; then usage >&2; exit 2; fi
  if [[ "$(id -u)" -ne 0 ]]; then
    printf '%s\n' 'Run --prepare-operator-host-dirs with sudo.' >&2
    exit 1
  fi
  service_uid="${ADMIRA_SERVICE_UID:-1001}"
  service_gid="${ADMIRA_SERVICE_GID:-1001}"
  central_image_gid="${ADMIRA_CENTRAL_IMAGE_GID:-19093}"
  for numeric_id in "$service_uid" "$service_gid" "$central_image_gid"; do
    if [[ ! "$numeric_id" =~ ^[1-9][0-9]{0,4}$ || "$numeric_id" -gt 65534 ]]; then
      printf 'Invalid operator host-directory UID/GID: %s\n' "$numeric_id" >&2
      exit 1
    fi
  done

  ensure_parent_directory() {
    local path="$1" mode="$2" owner="$3" group="$4"
    if [[ -L "$path" || ( -e "$path" && ! -d "$path" ) ]]; then
      printf 'Refusing unsafe operator parent path: %s\n' "$path" >&2
      exit 1
    fi
    if [[ ! -d "$path" ]]; then
      install -d -m "$mode" -o "$owner" -g "$group" "$path"
    fi
  }
  prepare_private_directory() {
    local path="$1" owner="$2" group="$3" actual_owner
    if [[ -L "$path" || ( -e "$path" && ! -d "$path" ) ]]; then
      printf 'Refusing unsafe operator private path: %s\n' "$path" >&2
      exit 1
    fi
    if [[ -d "$path" ]]; then
      actual_owner="$(stat -c '%u' "$path" 2>/dev/null || stat -f '%u' "$path")"
      if [[ "$actual_owner" != "$owner" ]]; then
        printf 'Operator private path has unexpected owner: %s\n' "$path" >&2
        exit 1
      fi
      chmod 0700 "$path"
    else
      install -d -m 0700 -o "$owner" -g "$group" "$path"
    fi
  }

  # Create missing parents only. Existing deployment roots retain their
  # ownership/mode; only the final private directories are normalized.
  ensure_parent_directory /etc/admira 0700 "$service_uid" "$service_gid"
  ensure_parent_directory /srv/admira 0755 0 0
  ensure_parent_directory /srv/admira/shared 0750 "$service_uid" "$service_gid"
  prepare_private_directory /etc/admira/gemini-pool "$service_uid" "$service_gid"
  prepare_private_directory /srv/admira/shared/central-codex-auth "$service_uid" "$central_image_gid"
  prepare_private_directory /srv/admira/shared/central-codex-auth/primary "$service_uid" "$central_image_gid"
  prepare_private_directory /srv/admira/shared/central-codex-auth/secondary "$service_uid" "$central_image_gid"
  printf '%s\n' 'Private operator provider directories are ready; no password or provider credential was created.'
  exit 0
fi
if [[ $# -gt 0 ]]; then usage >&2; exit 2; fi
if [[ "$(id -u)" -eq 0 ]]; then
  printf '%s\n' 'Run secret bootstrap as the configured non-root service user, not sudo.' >&2
  exit 1
fi

umask 077
if [[ -L "$SECRETS_DIR" || ( -e "$SECRETS_DIR" && ! -d "$SECRETS_DIR" ) ]]; then
  printf '%s\n' 'Refusing unsafe secrets directory.' >&2
  exit 1
fi
install -d -m 700 "$SECRETS_DIR"
for existing_secret in "$SECRETS_DIR"/*.txt "$SECRETS_DIR/redis_users.acl"; do
  if [[ -L "$existing_secret" || ( -e "$existing_secret" && ! -f "$existing_secret" ) ]]; then
    printf '%s\n' 'Refusing unsafe existing secret file.' >&2
    exit 1
  fi
  if [[ -f "$existing_secret" ]]; then
    existing_owner="$(stat -c '%u' "$existing_secret" 2>/dev/null || stat -f '%u' "$existing_secret")"
    existing_links="$(stat -c '%h' "$existing_secret" 2>/dev/null || stat -f '%l' "$existing_secret")"
    if [[ "$existing_owner" != "$(id -u)" || "$existing_links" != 1 ]]; then
      printf '%s\n' 'Existing secrets must be service-owned files with one link.' >&2
      exit 1
    fi
  fi
done

if [[ ! -s "$SECRETS_DIR/postgres_password.txt" ]]; then
  openssl rand -base64 48 | tr -d '\n' > "$SECRETS_DIR/postgres_password.txt"
  printf '\n' >> "$SECRETS_DIR/postgres_password.txt"
fi

if [[ ! -s "$SECRETS_DIR/redis_users.acl" ]]; then
  redis_password="$(openssl rand -base64 48 | tr -d '\n')"
  printf 'user default on >%s ~* &* +@all\n' "$redis_password" > "$SECRETS_DIR/redis_users.acl"
  unset redis_password
fi

for secret_name in ingress_db_password runtime_db_password delivery_db_password scheduler_db_password provisioner_db_password image_db_password recovery_db_password email_delivery_db_password operator_db_password runtime_broker_key recovery_hmac_key; do
  secret_path="$SECRETS_DIR/${secret_name}.txt"
  if [[ -L "$secret_path" || ( -e "$secret_path" && ! -f "$secret_path" ) ]]; then
    printf 'Refusing unsafe service secret file: %s\n' "$secret_name" >&2
    exit 1
  fi
  if [[ ! -s "$secret_path" ]]; then
    openssl rand -base64 48 | tr -d '\n' > "$secret_path"
    printf '\n' >> "$secret_path"
  fi
done

# The dashboard creates password.hash exactly once through loopback-only
# first-run setup. Bootstrap owns only the enclosing persistent directory and
# must never seed a default, empty hash, or plaintext password.
OPERATOR_PASSWORD_DIR="$SECRETS_DIR/operator-password"
if [[ -L "$OPERATOR_PASSWORD_DIR" || ( -e "$OPERATOR_PASSWORD_DIR" && ! -d "$OPERATOR_PASSWORD_DIR" ) ]]; then
  printf '%s\n' 'Refusing unsafe operator password directory.' >&2
  exit 1
fi
install -d -m 0700 "$OPERATOR_PASSWORD_DIR"
operator_password_owner="$(stat -c '%u' "$OPERATOR_PASSWORD_DIR" 2>/dev/null || stat -f '%u' "$OPERATOR_PASSWORD_DIR")"
if [[ "$operator_password_owner" != "$(id -u)" ]]; then
  printf '%s\n' 'Operator password directory must be owned by the service user.' >&2
  exit 1
fi
chmod 0700 "$OPERATOR_PASSWORD_DIR"

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
printf '%s\n' 'Control-plane secrets and the private password-hash directory are ready.'
if [[ ! -s "$OPERATOR_PASSWORD_DIR/password.hash" ]]; then
  printf '%s\n' 'Operator first-run password setup is pending and must be completed through the SSH tunnel.'
fi
