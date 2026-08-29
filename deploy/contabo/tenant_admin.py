#!/usr/bin/env python3
"""Register a provisioned tenant with the central Telegram control plane.

This host-only command creates tenant-local files first and then atomically
registers the public Telegram identifiers. It never reads the shared bot token
and never starts buyer traffic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import subprocess
from pathlib import Path
from typing import Iterable

from tenantctl import DEFAULT_BASE, provision, validate_tenant_id


ROOT = Path(__file__).resolve().parent
COMPOSE = ROOT / "compose.yaml"
ID_RE = re.compile(r"^-?[0-9]{1,32}$")
BOT_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")


def _identifier(value: str, label: str, *, allow_negative: bool) -> str:
    text = str(value).strip()
    pattern = ID_RE if allow_negative else re.compile(r"^[0-9]{1,32}$")
    if not pattern.fullmatch(text):
        raise ValueError(f"{label} must be a Telegram numeric ID")
    return text


def register(
    base: Path,
    tenant_key: str,
    display_name: str,
    bot_id: str,
    chat_id: str,
    user_id: str,
    *,
    dry_run: bool = False,
) -> dict[str, object]:
    tenant_key = validate_tenant_id(tenant_key)
    display_name = str(display_name).strip()
    if not display_name or len(display_name) > 200 or any(ord(char) < 32 for char in display_name):
        raise ValueError("display_name must contain 1 to 200 printable characters")
    bot_id = _identifier(bot_id, "bot_id", allow_negative=False)
    chat_id = _identifier(chat_id, "chat_id", allow_negative=True)
    user_id = _identifier(user_id, "user_id", allow_negative=False)

    filesystem = provision(base, tenant_key, dry_run=dry_run)
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "tenant_key": tenant_key,
            "root": filesystem["root"],
            "telegram_binding": {"bot_id": bot_id, "chat_id": chat_id, "user_id": user_id},
        }

    sql = (
        "SELECT json_build_object('tenant_id', tenant_id, 'runtime_key', runtime_key) "
        "FROM admira.register_hosted_tenant(:'runtime_key', :'display_name', :'bot_id', :'chat_id', :'user_id');"
    )
    shell = (
        'export PGPASSWORD="$(cat /run/secrets/provisioner_db_password)"; '
        'exec psql -v ON_ERROR_STOP=1 -X -qAt -U admira_provisioner_login -d "$POSTGRES_DB" '
        '-v runtime_key="$1" -v display_name="$2" -v bot_id="$3" -v chat_id="$4" -v user_id="$5"'
    )
    command = [
        "docker", "compose", "--project-directory", str(ROOT), "-f", str(COMPOSE),
        "exec", "-T", "postgres", "sh", "-ec", shell, "admira-register",
        tenant_key, display_name, bot_id, chat_id, user_id,
    ]
    # psql does not interpolate :'variables' inside a -c argument. Feed the
    # reviewed statement over stdin so psql performs safe variable quoting and
    # the SQL never appears in the process list.
    completed = subprocess.run(
        command, input=sql, check=False, text=True, capture_output=True
    )
    if completed.returncode != 0:
        return {
            "ok": False,
            "error_code": "tenant_registration_failed",
            "tenant_key": tenant_key,
            "filesystem_ready": True,
        }
    try:
        registered = json.loads(completed.stdout.strip())
    except (TypeError, ValueError):
        return {
            "ok": False,
            "error_code": "tenant_registration_protocol_error",
            "tenant_key": tenant_key,
            "filesystem_ready": True,
        }
    return {
        "ok": True,
        "tenant_key": tenant_key,
        "tenant_id": str(registered["tenant_id"]),
        "runtime_key": str(registered["runtime_key"]),
        "root": filesystem["root"],
        "buyer_traffic_started": False,
    }


def issue_claim(
    base: Path,
    tenant_key: str,
    display_name: str,
    *,
    ttl_seconds: int = 1800,
    bot_username: str = "",
    dry_run: bool = False,
) -> dict[str, object]:
    tenant_key = validate_tenant_id(tenant_key)
    display_name = str(display_name).strip()
    if not display_name or len(display_name) > 200 or any(ord(char) < 32 for char in display_name):
        raise ValueError("display_name must contain 1 to 200 printable characters")
    if not 300 <= int(ttl_seconds) <= 86400:
        raise ValueError("ttl_seconds must be between 300 and 86400")
    bot_username = str(bot_username or "").strip().removeprefix("@")
    if bot_username and not BOT_USERNAME_RE.fullmatch(bot_username):
        raise ValueError("bot_username is invalid")
    filesystem = provision(base, tenant_key, dry_run=dry_run)
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "tenant_key": tenant_key,
            "root": filesystem["root"],
            "claim_would_expire_in_seconds": int(ttl_seconds),
        }

    raw_token = secrets.token_urlsafe(24)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    sql = (
        "SELECT json_build_object('tenant_id', tenant_id, 'expires_at', expires_at) "
        "FROM admira.issue_telegram_tenant_claim(:'runtime_key', :'display_name', :'token_hash', :'ttl_seconds');"
    )
    shell = (
        'export PGPASSWORD="$(cat /run/secrets/provisioner_db_password)"; '
        'exec psql -v ON_ERROR_STOP=1 -X -qAt -U admira_provisioner_login -d "$POSTGRES_DB" '
        '-v runtime_key="$1" -v display_name="$2" -v token_hash="$3" -v ttl_seconds="$4"'
    )
    command = [
        "docker", "compose", "--project-directory", str(ROOT), "-f", str(COMPOSE),
        "exec", "-T", "postgres", "sh", "-ec", shell, "admira-claim",
        tenant_key, display_name, token_hash, str(int(ttl_seconds)),
    ]
    completed = subprocess.run(
        command, input=sql, check=False, text=True, capture_output=True
    )
    if completed.returncode != 0:
        return {
            "ok": False,
            "error_code": "tenant_claim_failed",
            "tenant_key": tenant_key,
            "filesystem_ready": True,
        }
    try:
        registered = json.loads(completed.stdout.strip())
    except (TypeError, ValueError):
        return {
            "ok": False,
            "error_code": "tenant_claim_protocol_error",
            "tenant_key": tenant_key,
            "filesystem_ready": True,
        }
    result: dict[str, object] = {
        "ok": True,
        "tenant_key": tenant_key,
        "tenant_id": str(registered["tenant_id"]),
        "claim_token": raw_token,
        "start_parameter": raw_token,
        "expires_at": str(registered["expires_at"]),
        "root": filesystem["root"],
        "buyer_traffic_started": False,
    }
    if bot_username:
        result["telegram_url"] = f"https://t.me/{bot_username}?start={raw_token}"
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Register one isolated Admira hosted tenant")
    commands = result.add_subparsers(dest="command", required=True)
    claim = commands.add_parser("claim", help="issue a one-time Telegram deep-link claim")
    claim.add_argument("tenant_key")
    claim.add_argument("display_name")
    claim.add_argument("--ttl-seconds", type=int, default=1800)
    claim.add_argument("--bot-username", default="")
    bind = commands.add_parser("bind", help="bind known public Telegram IDs manually")
    bind.add_argument("tenant_key")
    bind.add_argument("display_name")
    bind.add_argument("bot_id")
    bind.add_argument("chat_id")
    bind.add_argument("user_id")
    for command in (claim, bind):
        command.add_argument("--base-dir", type=Path, default=Path(DEFAULT_BASE))
        command.add_argument("--dry-run", action="store_true")
    return result


def main(argv: Iterable[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "claim":
            result = issue_claim(
                args.base_dir, args.tenant_key, args.display_name,
                ttl_seconds=args.ttl_seconds, bot_username=args.bot_username, dry_run=args.dry_run,
            )
        else:
            result = register(
                args.base_dir, args.tenant_key, args.display_name, args.bot_id,
                args.chat_id, args.user_id, dry_run=args.dry_run,
            )
    except (OSError, ValueError) as exc:
        result = {"ok": False, "error_code": "invalid_registration", "detail": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
