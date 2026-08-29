#!/usr/bin/env python3
"""Small, dependency-free controller for isolated Admira tenant runtimes.

The controller deliberately owns only tenant-local files.  It never interpolates
credentials into compose output and all subprocesses are argv lists (no shell).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable


IMAGE = "admira-ia:r90"
TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")
DEFAULT_BASE = "/srv/admira/tenants"
DIRS = ("runtime", "data", "output", "logs", "brand_guides")
DEFAULT_MEMORY_LIMIT = "1g"
DEFAULT_CPU_LIMIT = "1.0"
DEFAULT_PIDS_LIMIT = 256
DEFAULT_GEMINI_KEY_FILE = Path("/etc/admira/hosted-gemini-api-key")
MEMORY_RE = re.compile(r"^[1-9][0-9]*(?:b|k|m|g)?$", re.IGNORECASE)
CPU_RE = re.compile(r"^(?:0\.[1-9][0-9]*|[1-9][0-9]*(?:\.[0-9]+)?)$")
INITIAL_RUNTIME_ENV = """# Admira hosted tenant bootstrap. Buyer credentials are added by onboarding.
META_ADS_AGENT_MODE=dry-run
LIVE_ACTIONS_ENABLED=false
TELEGRAM_AGENT_ENABLED=false
AGENT_BRAIN_PROVIDER=gemini
AGENT_CHAT_PROVIDER=hermes
AGENT_CHAT_BASE_URL=https://generativelanguage.googleapis.com/v1beta
AGENT_CHAT_API=gemini-native
AGENT_CHAT_MODEL=gemini-3.5-flash-lite
GEMINI_API_KEY=
HERMES_HOME=/app/runtime/hermes
CODEX_HOME=/app/runtime/hermes/codex-auth
HERMES_MODEL=gpt-5.6-luna
HERMES_MODEL_USER_SELECTED=false
HERMES_USE_PYTHON_LIBRARY=true
HERMES_REQUIRE_CODEX_AUTH=false
HERMES_RESPONSE_TIMEOUT_SECONDS=300
HERMES_TIMEOUT_SECONDS=300
"""


def _private_secret(path: Path) -> str:
    """Read one optional host secret without ever placing it in Compose."""
    try:
        details = path.lstat()
    except FileNotFoundError:
        return ""
    if not stat.S_ISREG(details.st_mode) or path.is_symlink() or stat.S_IMODE(details.st_mode) & 0o077:
        raise ValueError("hosted Gemini key file must be a private regular file")
    raw = path.read_text(encoding="utf-8")
    value = raw.strip()
    if not value:
        return ""
    if not 20 <= len(value) <= 512 or any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise ValueError("hosted Gemini key file is invalid")
    return value


def _set_env_if_blank(path: Path, key: str, value: str) -> bool:
    if not value:
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    changed = False
    found = False
    for index, line in enumerate(lines):
        if line.startswith(f"{key}="):
            found = True
            if not line.split("=", 1)[1].strip():
                lines[index] = f"{key}={value}"
                changed = True
            break
    if not found:
        lines.append(f"{key}={value}")
        changed = True
    if not changed:
        return False
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines).rstrip() + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return True


def validate_tenant_id(value: str) -> str:
    if not TENANT_RE.fullmatch(value):
        raise ValueError("tenant_id must match [a-z0-9][a-z0-9-]{2,62}")
    return value


def tenant_path(base: Path, tenant_id: str) -> Path:
    validate_tenant_id(tenant_id)
    return base / tenant_id


def _setting(value: str | None, env_name: str, default: str) -> str:
    return str(value if value is not None else os.environ.get(env_name, default))


def compose_text(
    root: Path,
    tenant_id: str,
    *,
    memory_limit: str | None = None,
    cpu_limit: str | None = None,
    pids_limit: int | None = None,
) -> str:
    # Absolute, tenant-specific mounts prevent accidental cross-tenant access.
    memory_limit = _setting(memory_limit, "ADMIRA_TENANT_MEMORY_LIMIT", DEFAULT_MEMORY_LIMIT)
    cpu_limit = _setting(cpu_limit, "ADMIRA_TENANT_CPU_LIMIT", DEFAULT_CPU_LIMIT)
    pids_limit = int(pids_limit if pids_limit is not None else os.environ.get("ADMIRA_TENANT_PIDS_LIMIT", DEFAULT_PIDS_LIMIT))
    if not MEMORY_RE.fullmatch(memory_limit):
        raise ValueError("memory limit must be a positive Docker size such as 1g")
    if not CPU_RE.fullmatch(cpu_limit) or float(cpu_limit) <= 0:
        raise ValueError("cpu limit must be a positive decimal")
    if not 1 <= pids_limit <= 65536:
        raise ValueError("pids limit must be between 1 and 65536")
    mounts = [
        "      - " + json.dumps(f"{root / 'runtime'}:/app/runtime"),
        "      - " + json.dumps(f"{root / 'data'}:/app/dashboard/data"),
        "      - " + json.dumps(f"{root / 'output'}:/app/output"),
        "      - " + json.dumps(f"{root / 'logs'}:/app/logs"),
        "      - " + json.dumps(f"{root / 'brand_guides'}:/app/brand_guides"),
    ]
    return "\n".join(
        [
            f"name: admira-tenant-{tenant_id}",
            "services:",
            "  admira:",
            f"    image: {IMAGE}",
            # The control plane owns wake/suspend.  Docker must not wake every
            # tenant after a host reboot and exhaust an 8 GB starter node.
            '    restart: "no"',
            "    init: true",
            # The r90 entrypoint creates /app/.env and /app/ad-config.json
            # symlinks.  Since those paths are outside the tenant mounts, a
            # read-only root filesystem is not compatible without hiding /app
            # (and therefore the image).  Keep this documented and writable;
            # all mutable application paths are tenant-only mounts below.
            "    security_opt:",
            "      - no-new-privileges:true",
            "    cap_drop:",
            "      - ALL",
            # The image entrypoint runs as UID 0 and creates its runtime
            # layout. Tenant bind mounts are deliberately 0700 and owned by
            # the host service account (uid 1001); DAC_OVERRIDE is the
            # minimum capability needed for that access. Do not add FOWNER,
            # CHOWN, or any broader capability.
            "    cap_add:",
            "      - DAC_OVERRIDE",
            f"    pids_limit: {pids_limit}",
            f"    mem_limit: {memory_limit}",
            f"    cpus: {cpu_limit}",
            "    environment:",
            f"      ADMIRA_TENANT_ID: {tenant_id}",
            "      HERMES_HOME: /app/runtime/hermes",
            "      CODEX_HOME: /app/runtime/hermes/codex-auth",
            "      TELEGRAM_AGENT_ENABLED: \"false\"",
            "    volumes:",
            *mounts,
            "    tmpfs:",
            "      - /tmp:rw,noexec,nosuid,size=64m",
            "    labels:",
            "      com.admira.managed: \"true\"",
            f"      com.admira.tenant: \"{tenant_id}\"",
            f"      com.admira.image: \"{IMAGE}\"",
            "",
        ]
    )


def run(argv: list[str], *, dry_run: bool = False) -> subprocess.CompletedProcess[str] | None:
    if dry_run:
        return None
    return subprocess.run(argv, check=False, text=True, capture_output=True)


def compose_argv(root: Path, *args: str) -> list[str]:
    tenant_id = root.name
    return ["docker", "compose", "-p", f"admira-tenant-{tenant_id}", "-f", str(root / "compose.yaml"), *args]


def plan(base: Path, tenant_id: str) -> dict[str, object]:
    root = tenant_path(base, tenant_id)
    return {
        "tenant_id": tenant_id,
        "root": str(root),
        "image": IMAGE,
        "directories": [str(root / item) for item in DIRS],
        "compose": str(root / "compose.yaml"),
        "actions": ["create tenant directories", "write tenant-local compose", "start runtime"],
        "isolated": {"network_ports": False, "docker_socket": False, "secrets_in_compose": False},
    }


def provision(
    base: Path,
    tenant_id: str,
    *,
    dry_run: bool = False,
    memory_limit: str | None = None,
    cpu_limit: str | None = None,
    pids_limit: int | None = None,
    gemini_key_file: Path | None = None,
) -> dict[str, object]:
    root = tenant_path(base, tenant_id)
    if not dry_run:
        key_path = gemini_key_file or Path(
            os.environ.get("ADMIRA_HOSTED_GEMINI_KEY_FILE", str(DEFAULT_GEMINI_KEY_FILE))
        )
        hosted_gemini_key = _private_secret(key_path)
        root.mkdir(parents=True, exist_ok=True)
        root.chmod(0o700)
        for name in DIRS:
            path = root / name
            path.mkdir(exist_ok=True)
            path.chmod(0o700)
        runtime_env = root / "runtime" / ".env"
        if not runtime_env.exists():
            runtime_env.write_text(INITIAL_RUNTIME_ENV, encoding="utf-8")
            runtime_env.chmod(0o600)
        _set_env_if_blank(runtime_env, "GEMINI_API_KEY", hosted_gemini_key)
        compose = root / "compose.yaml"
        compose.write_text(
            compose_text(
                root,
                tenant_id,
                memory_limit=memory_limit,
                cpu_limit=cpu_limit,
                pids_limit=pids_limit,
            ),
            encoding="utf-8",
        )
        compose.chmod(0o600)
    return {"ok": True, "action": "provision", "tenant_id": tenant_id, "root": str(root), "dry_run": dry_run}


def lifecycle(base: Path, tenant_id: str, action: str, *, dry_run: bool = False) -> dict[str, object]:
    if action not in {"start", "suspend"}:
        raise ValueError("lifecycle action must be start or suspend")
    root = tenant_path(base, tenant_id)
    argv = (
        compose_argv(root, "up", "-d", "--no-build", "--pull", "never")
        if action == "start"
        else compose_argv(root, "down", "--remove-orphans")
    )
    result = run(argv, dry_run=dry_run)
    output = "" if result is None else (result.stdout or result.stderr).strip()
    return {"ok": result is None or result.returncode == 0, "action": action, "tenant_id": tenant_id,
            "command": argv, "dry_run": dry_run, "output": output}


def status(base: Path, tenant_id: str, *, dry_run: bool = False) -> dict[str, object]:
    root = tenant_path(base, tenant_id)
    argv = compose_argv(root, "ps", "--format", "json")
    result = run(argv, dry_run=dry_run)
    output = "" if result is None else (result.stdout or result.stderr).strip()
    return {"ok": result is None or result.returncode == 0, "action": "status", "tenant_id": tenant_id,
            "command": argv, "dry_run": dry_run, "output": output}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Manage isolated Admira tenant runtimes")
    p.add_argument("command", choices=("plan", "provision", "start", "suspend", "status"))
    p.add_argument("tenant_id")
    p.add_argument("--base-dir", default=os.environ.get("ADMIRA_TENANTS_BASE", DEFAULT_BASE), type=Path)
    p.add_argument("--memory-limit", default=None, help=f"per-tenant memory limit (default: {DEFAULT_MEMORY_LIMIT})")
    p.add_argument("--cpu-limit", default=None, help=f"per-tenant CPU limit (default: {DEFAULT_CPU_LIMIT})")
    p.add_argument("--pids-limit", default=None, type=int, help=f"per-tenant PID limit (default: {DEFAULT_PIDS_LIMIT})")
    p.add_argument("--gemini-key-file", default=None, type=Path,
                   help="private host file used only to seed a blank tenant Gemini credential")
    p.add_argument("--dry-run", action="store_true", help="show the operation without writing or running Docker")
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "plan":
            result = plan(args.base_dir, args.tenant_id)
        elif args.command == "provision":
            result = provision(
                args.base_dir,
                args.tenant_id,
                dry_run=args.dry_run,
                memory_limit=args.memory_limit,
                cpu_limit=args.cpu_limit,
                pids_limit=args.pids_limit,
                gemini_key_file=args.gemini_key_file,
            )
        elif args.command in ("start", "suspend"):
            result = lifecycle(args.base_dir, args.tenant_id, args.command, dry_run=args.dry_run)
        else:
            result = status(args.base_dir, args.tenant_id, dry_run=args.dry_run)
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
