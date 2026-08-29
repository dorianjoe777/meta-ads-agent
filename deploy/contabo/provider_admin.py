#!/usr/bin/env python3
"""Safely manage the provider credential for one hosted tenant.

The credential is deliberately accepted only through stdin or a private file;
it is never a command-line argument, logged, or returned in the JSON result.
This module has no database or subprocess dependency.  Callers may inject a
metadata recorder and a post-write health check when those services exist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Callable, Iterable, TextIO


TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")
DEFAULT_BASE = Path("/srv/admira/tenants")
ENV_NAME = "GEMINI_API_KEY"
Validator = Callable[[str], object]
HealthCheck = Callable[[Path], object]
MetadataRecorder = Callable[[dict[str, object]], object]


def _tenant_id(value: str) -> str:
    value = str(value).strip()
    if not TENANT_RE.fullmatch(value):
        raise ValueError("tenant_id must match [a-z0-9][a-z0-9-]{2,62}")
    return value


def _read_private_file(path: Path) -> str:
    """Read a key source without accepting links or group/world-readable files."""
    details = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(details.st_mode):
        raise ValueError("key file must be a private regular file")
    if stat.S_IMODE(details.st_mode) & 0o077:
        raise ValueError("key file must be a private regular file")
    return path.read_text(encoding="utf-8")


def validate_gemini_key(value: str) -> str:
    """Perform local, provider-independent validation of a Gemini API key."""
    value = str(value).strip()
    if not 20 <= len(value) <= 512 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise ValueError("Gemini key format is invalid")
    return value


def _validated(value: str, validator: Validator | None) -> str:
    value = validate_gemini_key(value)
    if validator is not None:
        try:
            verdict = validator(value)
        except Exception as exc:  # do not expose provider/client details
            raise ValueError("Gemini key format is invalid") from exc
        if verdict is False:
            raise ValueError("Gemini key format is invalid")
    return value


def _runtime_env(base: Path, tenant_id: str) -> Path:
    tenant_id = _tenant_id(tenant_id)
    root = base / tenant_id
    runtime = root / "runtime"
    env_path = runtime / ".env"
    if not root.exists() or root.is_symlink() or not root.is_dir() or runtime.is_symlink() or not runtime.is_dir():
        raise FileNotFoundError("tenant runtime is not provisioned")
    if env_path.is_symlink():
        raise ValueError("tenant runtime environment must not be a symlink")
    return env_path


def _replace_key(text: str, value: str) -> str:
    lines = text.splitlines(keepends=True)
    found = False
    output: list[str] = []
    for line in lines:
        body = line.rstrip("\r\n")
        newline = line[len(body):]
        if body.startswith(f"{ENV_NAME}="):
            if found:
                # Multiple credentials are ambiguous and unsafe to update.
                raise ValueError("tenant runtime environment contains duplicate Gemini keys")
            output.append(f"{ENV_NAME}={value}{newline or chr(10)}")
            found = True
        else:
            output.append(line)
    if not found:
        if output and not output[-1].endswith(("\n", "\r")):
            output.append("\n")
        output.append(f"{ENV_NAME}={value}\n")
    return "".join(output)


def _atomic_write(path: Path, text: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
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


def manage_gemini_key(
    base: Path,
    tenant_id: str,
    *,
    value: str | None,
    source: str,
    dry_run: bool = False,
    validator: Validator | None = None,
    health_check: HealthCheck | None = None,
    record_metadata: MetadataRecorder | None = None,
) -> dict[str, object]:
    """Set or clear one tenant key, returning metadata but never the secret."""
    if source not in {"operator_pool", "customer"}:
        raise ValueError("source must be operator_pool or customer")
    path = _runtime_env(Path(base), tenant_id)
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    old_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    if value is None:
        new_value = ""
        fingerprint = None
    else:
        new_value = _validated(value, validator)
        fingerprint = hashlib.sha256(new_value.encode("utf-8")).hexdigest()
    new_text = _replace_key(old, new_value)
    result: dict[str, object] = {
        "ok": True,
        "dry_run": bool(dry_run),
        "tenant_id": _tenant_id(tenant_id),
        "source": source,
        "action": "clear" if value is None else "set",
        "fingerprint": fingerprint,
    }
    if dry_run:
        return result
    _atomic_write(path, new_text)
    try:
        if health_check is not None and health_check(path) is False:
            raise RuntimeError("post-write health check failed")
    except Exception:
        try:
            _atomic_write(path, old)
            os.chmod(path, old_mode)
        except OSError as rollback_error:
            raise RuntimeError("post-write health check failed; rollback failed") from rollback_error
        return {"ok": False, "error_code": "health_check_failed", "tenant_id": _tenant_id(tenant_id), "source": source}
    if record_metadata is not None:
        metadata = {"tenant_id": _tenant_id(tenant_id), "source": source, "action": result["action"], "fingerprint": fingerprint}
        record_metadata(metadata)
    return result


def _input_key(args: argparse.Namespace, stream: TextIO) -> str:
    if args.key_file is not None:
        return _read_private_file(args.key_file)
    return stream.read()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage one hosted tenant Gemini credential")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("gemini-set", "gemini-clear"):
        command = commands.add_parser(name)
        command.add_argument("tenant_id")
        command.add_argument("--source", required=True, choices=("operator_pool", "customer"))
        command.add_argument("--base-dir", type=Path, default=DEFAULT_BASE)
        command.add_argument("--key-file", type=Path, help="private regular file; otherwise read key from stdin")
        command.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None, *, stdin: TextIO | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        value = None if args.command == "gemini-clear" else _input_key(args, stdin or sys.stdin)
        result = manage_gemini_key(args.base_dir, args.tenant_id, value=value, source=args.source, dry_run=args.dry_run)
    except (OSError, ValueError) as exc:
        result = {"ok": False, "error_code": "invalid_gemini_credential", "detail": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
