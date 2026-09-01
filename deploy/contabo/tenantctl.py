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
import secrets
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable


DEFAULT_IMAGE = "admira-ia:r90"
# Hosted candidates are deliberately accepted only when their tag contains
# the exact 12-character commit prefix emitted by build-hosted-runtime.sh.
# This keeps r90 the normal path while allowing an operator to pin one tenant
# to one immutable r91/r99 canary with ADMIRA_TENANT_IMAGE or --runtime-image.
HOSTED_CANARY_IMAGE_RE = re.compile(r"^admira-ia-hosted:r(?:91|99)-canary-[0-9a-f]{12}$")
IMAGE = DEFAULT_IMAGE  # compatibility for callers that imported the old name
TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")
DEFAULT_BASE = "/srv/admira/tenants"
DIRS = ("runtime", "data", "output", "logs", "brand_guides")
DEFAULT_MEMORY_LIMIT = "1g"
DEFAULT_CPU_LIMIT = "1.0"
DEFAULT_PIDS_LIMIT = 256
DEFAULT_CENTRAL_IMAGE_KEY_ROOT = Path("/etc/admira/central-image-keys")
DEFAULT_CENTRAL_IMAGE_EXCHANGE_ROOT = Path("/srv/admira/shared/central-image-exchange")
DEFAULT_CENTRAL_IMAGE_SOCKET_DIR = Path("/run/admira-central-image-broker")
DEFAULT_CENTRAL_IMAGE_GID = 19093
CENTRAL_IMAGE_CLIENT_KEY = "central_image_client.key"
DEFAULT_META_OAUTH_BROKER_URL = "https://admiraia.uboost.lat/api/meta-oauth"
MEMORY_RE = re.compile(r"^[1-9][0-9]*(?:b|k|m|g)?$", re.IGNORECASE)
CPU_RE = re.compile(r"^(?:0\.[1-9][0-9]*|[1-9][0-9]*(?:\.[0-9]+)?)$")


def validate_runtime_image(value: str) -> str:
    """Allow only the live r90 image or an exact hosted r91/r99 canary tag."""
    if value == DEFAULT_IMAGE or HOSTED_CANARY_IMAGE_RE.fullmatch(value):
        return value
    raise ValueError(
        "runtime image must be admira-ia:r90 or "
        "admira-ia-hosted:r91-canary-<12 lowercase commit hex> or "
        "admira-ia-hosted:r99-canary-<12 lowercase commit hex>"
    )


def selected_runtime_image(value: str | None = None) -> str:
    return validate_runtime_image(value or os.environ.get("ADMIRA_TENANT_IMAGE", DEFAULT_IMAGE))
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
META_OAUTH_BROKER_URL=https://admiraia.uboost.lat/api/meta-oauth
"""


def _atomic_private_write(path: Path, data: bytes) -> None:
    """Atomically install one private regular file and fsync its directory."""
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _private_regular_bytes(path: Path) -> bytes:
    details = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) & 0o077:
        raise ValueError("central image key must be a private regular file")
    value = path.read_bytes().strip()
    if len(value) < 32 or len(value) > 512:
        raise ValueError("central image key is invalid")
    return value


def provision_central_image_client(
    root: Path,
    tenant_id: str,
    *,
    key_root: Path = DEFAULT_CENTRAL_IMAGE_KEY_ROOT,
    exchange_root: Path = DEFAULT_CENTRAL_IMAGE_EXCHANGE_ROOT,
    socket_dir: Path = DEFAULT_CENTRAL_IMAGE_SOCKET_DIR,
) -> bool:
    """Create matching host/client HMAC keys without exposing the host copy.

    The installer creates ``key_root`` when the central broker is available.
    Until then this is a deliberate no-op, which keeps existing r90 tenants
    usable while ``ADMIRA_CENTRAL_IMAGE_READY`` remains false.
    """
    tenant_id = validate_tenant_id(tenant_id)
    key_root = Path(key_root)
    exchange_root = Path(exchange_root)
    socket_dir = Path(socket_dir)
    for directory, label in (
        (key_root, "central image key root"),
        (exchange_root, "central image exchange root"),
        (socket_dir, "central image socket root"),
    ):
        if not directory.is_absolute():
            raise ValueError(f"{label} must be absolute")
    # Never let a tenant Compose invocation create these host boundaries as
    # root. They must already have been installed by the dedicated, audited
    # preparation script before a tenant receives any central-image mounts.
    if not key_root.exists() or not exchange_root.exists() or not socket_dir.exists():
        return False
    for directory, label in ((key_root, "central image key root"), (exchange_root, "central image exchange root")):
        if directory.exists():
            details = directory.lstat()
            if directory.is_symlink() or not stat.S_ISDIR(details.st_mode):
                raise ValueError(f"{label} must be a private regular directory")
        else:
            directory.mkdir(parents=True, mode=0o700)
        directory.chmod(0o700)
    socket_details = socket_dir.lstat()
    if socket_dir.is_symlink() or not stat.S_ISDIR(socket_details.st_mode):
        raise ValueError("central image socket root must be a regular directory")

    tenant_exchange = exchange_root / tenant_id
    if tenant_exchange.exists() or tenant_exchange.is_symlink():
        tenant_details = tenant_exchange.lstat()
        if tenant_exchange.is_symlink() or not stat.S_ISDIR(tenant_details.st_mode):
            raise ValueError("tenant central image exchange must be a regular directory")
    else:
        tenant_exchange.mkdir(mode=0o700)
    output = tenant_exchange / "output"
    if output.exists() or output.is_symlink():
        output_details = output.lstat()
        if output.is_symlink() or not stat.S_ISDIR(output_details.st_mode):
            raise ValueError("tenant central image output must be a regular directory")
    else:
        output.mkdir(mode=0o700)
    tenant_exchange.chmod(0o700)
    output.chmod(0o700)

    verifier = key_root / tenant_id
    client = root / "runtime" / CENTRAL_IMAGE_CLIENT_KEY
    verifier_value = _private_regular_bytes(verifier) if verifier.exists() or verifier.is_symlink() else b""
    client_value = _private_regular_bytes(client) if client.exists() or client.is_symlink() else b""
    if verifier_value and client_value and not secrets.compare_digest(verifier_value, client_value):
        raise ValueError("central image client key does not match verifier")
    if verifier_value:
        value = verifier_value
    elif client_value:
        # The tenant-mounted copy is not authoritative; refusing prevents a
        # compromised runtime from registering a key of its own choosing.
        raise ValueError("central image verifier key is missing")
    else:
        value = secrets.token_hex(32).encode("ascii")
        _atomic_private_write(verifier, value + b"\n")
    if not client_value:
        _atomic_private_write(client, value + b"\n")
    return True


def validate_tenant_id(value: str) -> str:
    if not TENANT_RE.fullmatch(value):
        raise ValueError("tenant_id must match [a-z0-9][a-z0-9-]{2,62}")
    return value


def tenant_path(base: Path, tenant_id: str) -> Path:
    validate_tenant_id(tenant_id)
    base = Path(base)
    if not base.is_absolute():
        raise ValueError("tenant base must be absolute")
    if base.exists() or base.is_symlink():
        base_details = base.lstat()
        if base.is_symlink() or not stat.S_ISDIR(base_details.st_mode):
            raise ValueError("tenant base must be a regular directory")
    root = base / tenant_id
    if root.exists() or root.is_symlink():
        root_details = root.lstat()
        if root.is_symlink() or not stat.S_ISDIR(root_details.st_mode):
            raise ValueError("tenant root must be a regular directory")
    return root


def _setting(value: str | None, env_name: str, default: str) -> str:
    return str(value if value is not None else os.environ.get(env_name, default))


def compose_text(
    root: Path,
    tenant_id: str,
    *,
    memory_limit: str | None = None,
    cpu_limit: str | None = None,
    pids_limit: int | None = None,
    central_image_enabled: bool = False,
    runtime_image: str | None = None,
    central_image_exchange_root: Path = DEFAULT_CENTRAL_IMAGE_EXCHANGE_ROOT,
    central_image_socket_dir: Path = DEFAULT_CENTRAL_IMAGE_SOCKET_DIR,
) -> str:
    # Absolute, tenant-specific mounts prevent accidental cross-tenant access.
    tenant_id = validate_tenant_id(tenant_id)
    root = Path(root)
    if not root.is_absolute():
        raise ValueError("tenant root must be absolute")
    memory_limit = _setting(memory_limit, "ADMIRA_TENANT_MEMORY_LIMIT", DEFAULT_MEMORY_LIMIT)
    cpu_limit = _setting(cpu_limit, "ADMIRA_TENANT_CPU_LIMIT", DEFAULT_CPU_LIMIT)
    pids_limit = int(pids_limit if pids_limit is not None else os.environ.get("ADMIRA_TENANT_PIDS_LIMIT", DEFAULT_PIDS_LIMIT))
    runtime_image = selected_runtime_image(runtime_image)
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
    central_security: list[str] = []
    central_environment: list[str] = []
    if central_image_enabled:
        if not Path(central_image_exchange_root).is_absolute() or not Path(central_image_socket_dir).is_absolute():
            raise ValueError("central image mount roots must be absolute")
        mounts.extend([
            "      - " + json.dumps(
                f"{Path(central_image_socket_dir)}:/run/admira-central-image-broker:ro"
            ),
            "      - " + json.dumps(
                f"{Path(central_image_exchange_root) / tenant_id / 'output'}:/run/admira-central-images"
            ),
        ])
        central_security = [
            "    group_add:",
            f'      - "${{ADMIRA_CENTRAL_IMAGE_GID:-{DEFAULT_CENTRAL_IMAGE_GID}}}"',
        ]
        central_environment = [
            "      ADMIRA_CENTRAL_IMAGE_SOCKET: /run/admira-central-image-broker/broker.sock",
            "      ADMIRA_CENTRAL_IMAGE_CLIENT_KEY_FILE: /app/runtime/central_image_client.key",
            "      ADMIRA_CENTRAL_IMAGE_EXCHANGE_ROOT: /run/admira-central-images",
        ]
    return "\n".join(
        [
            f"name: admira-tenant-{tenant_id}",
            "services:",
            "  admira:",
            f"    image: {runtime_image}",
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
            *central_security,
            f"    pids_limit: {pids_limit}",
            f"    mem_limit: {memory_limit}",
            f"    cpus: {cpu_limit}",
            "    environment:",
            f"      ADMIRA_TENANT_ID: {tenant_id}",
            "      HERMES_HOME: /app/runtime/hermes",
            "      CODEX_HOME: /app/runtime/hermes/codex-auth",
            "      TELEGRAM_AGENT_ENABLED: \"false\"",
            # This is a public broker URL, not an app secret. The host may
            # override it for a future broker migration without putting any
            # credential in the tenant compose file.
            f'      META_OAUTH_BROKER_URL: "${{ADMIRA_META_OAUTH_BROKER_URL:-{DEFAULT_META_OAUTH_BROKER_URL}}}"',
            "      ADMIRA_HOSTED_TELEGRAM_GATEWAY: \"true\"",
            *central_environment,
            "      ADMIRA_HOSTED_IMAGE_ACCESS_FILE: /app/runtime/hosted_image_access.json",
            "    volumes:",
            *mounts,
            "    tmpfs:",
            "      - /tmp:rw,noexec,nosuid,size=64m",
            "    labels:",
            "      com.admira.managed: \"true\"",
            f"      com.admira.tenant: \"{tenant_id}\"",
            f"      com.admira.image: \"{runtime_image}\"",
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


def plan(base: Path, tenant_id: str, *, runtime_image: str | None = None) -> dict[str, object]:
    root = tenant_path(base, tenant_id)
    return {
        "tenant_id": tenant_id,
        "root": str(root),
        "image": selected_runtime_image(runtime_image),
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
    central_image_key_root: Path | None = None,
    central_image_exchange_root: Path | None = None,
    central_image_socket_dir: Path | None = None,
    runtime_image: str | None = None,
) -> dict[str, object]:
    root = tenant_path(base, tenant_id)
    runtime_image = selected_runtime_image(runtime_image)
    if not dry_run:
        root.mkdir(parents=True, exist_ok=True)
        root.chmod(0o700)
        for name in DIRS:
            path = root / name
            if path.exists() or path.is_symlink():
                details = path.lstat()
                if path.is_symlink() or not stat.S_ISDIR(details.st_mode):
                    raise ValueError(f"tenant {name} must be a regular directory")
            else:
                path.mkdir(mode=0o700)
            path.chmod(0o700)
        runtime_env = root / "runtime" / ".env"
        if runtime_env.exists() or runtime_env.is_symlink():
            env_details = runtime_env.lstat()
            if (runtime_env.is_symlink() or not stat.S_ISREG(env_details.st_mode)
                    or stat.S_IMODE(env_details.st_mode) & 0o077):
                raise ValueError("tenant runtime environment must be a private regular file")
        else:
            _atomic_private_write(runtime_env, INITIAL_RUNTIME_ENV.encode("utf-8"))
        selected_key_root = central_image_key_root or Path(
            os.environ.get("ADMIRA_CENTRAL_IMAGE_KEY_ROOT", str(DEFAULT_CENTRAL_IMAGE_KEY_ROOT))
        )
        selected_exchange_root = central_image_exchange_root or Path(
            os.environ.get("ADMIRA_CENTRAL_IMAGE_EXCHANGE_ROOT", str(DEFAULT_CENTRAL_IMAGE_EXCHANGE_ROOT))
        )
        selected_socket_dir = central_image_socket_dir or Path(
            os.environ.get("ADMIRA_CENTRAL_IMAGE_SOCKET_DIR", str(DEFAULT_CENTRAL_IMAGE_SOCKET_DIR))
        )
        central_image_enabled = provision_central_image_client(
            root,
            tenant_id,
            key_root=selected_key_root,
            exchange_root=selected_exchange_root,
            socket_dir=selected_socket_dir,
        )
        compose = root / "compose.yaml"
        if compose.exists() or compose.is_symlink():
            compose_details = compose.lstat()
            if (compose.is_symlink() or not stat.S_ISREG(compose_details.st_mode)
                    or stat.S_IMODE(compose_details.st_mode) & 0o077):
                raise ValueError("tenant Compose must be a private regular file")
        compose_payload = compose_text(
                root,
                tenant_id,
                memory_limit=memory_limit,
                cpu_limit=cpu_limit,
                pids_limit=pids_limit,
                central_image_enabled=central_image_enabled,
                runtime_image=runtime_image,
                central_image_exchange_root=selected_exchange_root,
                central_image_socket_dir=selected_socket_dir,
        )
        _atomic_private_write(compose, compose_payload.encode("utf-8"))
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
    p.add_argument("--runtime-image", default=None, help="optional exact hosted r91/r99 canary tag for this tenant; default is r90")
    p.add_argument("--dry-run", action="store_true", help="show the operation without writing or running Docker")
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "plan":
            result = plan(args.base_dir, args.tenant_id, runtime_image=args.runtime_image)
        elif args.command == "provision":
            result = provision(
                args.base_dir,
                args.tenant_id,
                dry_run=args.dry_run,
                memory_limit=args.memory_limit,
                cpu_limit=args.cpu_limit,
                pids_limit=args.pids_limit,
                runtime_image=args.runtime_image,
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
