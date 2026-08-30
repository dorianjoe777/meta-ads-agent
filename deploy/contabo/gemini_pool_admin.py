#!/usr/bin/env python3
"""Operator CLI for the Gemini trial-key pool.

Provider keys are accepted only on stdin/private files and are kept outside
the repository.  PostgreSQL stores an opaque reference and fingerprint only.
The command is intentionally small and injectable so its security properties
can be tested without a live VPS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Callable, Iterable, TextIO

import provider_admin

DEFAULT_POOL_ROOT = Path("/etc/admira/gemini-pool")
DEFAULT_COMPOSE = Path(__file__).resolve().with_name("compose.yaml")
MAX_KEY_BYTES = 8 * 1024
RUNTIME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,199}$")
FINGERPRINT_RE = re.compile(r"^[a-f0-9]{64}$")
SECRET_REF_RE = re.compile(r"^file\+admira://gemini-pool/([a-f0-9]{64})$")


def _runtime(value: str) -> str:
    value = str(value).strip()
    if not RUNTIME_RE.fullmatch(value):
        raise ValueError("runtime key is invalid")
    return value


def _project(value: str) -> str:
    value = str(value).strip()
    if not PROJECT_RE.fullmatch(value):
        raise ValueError("project reference is invalid")
    return value


def _uuid(value: object, label: str) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} is invalid") from exc
    return str(parsed)


def _private_read(path: Path, *, max_bytes: int = MAX_KEY_BYTES) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError("key source must be a private regular file") from exc
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) & 0o077:
            raise ValueError("key source must be a private regular file")
        if details.st_size > max_bytes:
            raise ValueError("key source is too large")
        data = os.read(fd, max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("key source is too large")
        return data.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("key source is not valid text") from exc
    finally:
        os.close(fd)


def _stdin_read(stream: TextIO) -> str:
    data = stream.read(MAX_KEY_BYTES + 1)
    if len(data.encode("utf-8", "replace")) > MAX_KEY_BYTES:
        raise ValueError("key source is too large")
    return data


def _key(args: argparse.Namespace, stream: TextIO) -> str:
    raw = _private_read(args.key_file) if args.key_file else _stdin_read(stream)
    return provider_admin.validate_gemini_key(raw)


def _root(root: Path, *, create: bool) -> Path:
    root = Path(root)
    if not root.is_absolute():
        raise ValueError("pool root must be an absolute private directory")
    if root.exists() or root.is_symlink():
        if root.is_symlink() or not root.is_dir() or stat.S_IMODE(root.stat().st_mode) & 0o077:
            raise ValueError("pool root must be a private regular directory")
    elif create:
        root.mkdir(parents=True, mode=0o700)
    else:
        raise ValueError("pool root does not exist")
    os.chmod(root, 0o700)
    return root


def _ref(root: Path, secret_ref: str) -> tuple[Path, str]:
    match = SECRET_REF_RE.fullmatch(str(secret_ref))
    if not match:
        raise ValueError("pool secret reference is invalid")
    fingerprint = match.group(1)
    candidate = _root(root, create=False) / f"{fingerprint}.key"
    # The canonical format and a lexical containment check prevent traversal.
    if candidate.parent != Path(root):
        raise ValueError("pool secret reference is invalid")
    return candidate, fingerprint


def _stored_key(root: Path, secret_ref: str, fingerprint: str) -> str:
    path, expected = _ref(root, secret_ref)
    if expected != fingerprint or not FINGERPRINT_RE.fullmatch(fingerprint):
        raise ValueError("pool fingerprint mismatch")
    key = provider_admin.validate_gemini_key(_private_read(path))
    if hashlib.sha256(key.encode()).hexdigest() != fingerprint:
        raise ValueError("pool fingerprint mismatch")
    return key


def _store(root: Path, key: str) -> tuple[str, str, bool]:
    root = _root(root, create=True)
    fingerprint = hashlib.sha256(key.encode()).hexdigest()
    path = root / f"{fingerprint}.key"
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError("existing pool key file is unsafe")
        if _private_read(path) != key:
            raise ValueError("existing pool key file conflicts")
        return f"file+admira://gemini-pool/{fingerprint}", fingerprint, False
    fd, temporary = tempfile.mkstemp(prefix=".gemini-", dir=str(root))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(key)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        dfd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return f"file+admira://gemini-pool/{fingerprint}", fingerprint, True


Runner = Callable[..., object]


def _psql(args: argparse.Namespace, sql: str, payload: str = "", *, runner: Runner | None = None,
          variables: dict[str, str] | None = None) -> str:
    # Password is supplied by the Compose secret inside the container, never argv.
    shell = ('export PGPASSWORD="$(cat /run/secrets/provisioner_db_password)"; '
             'db_user="$1"; db_name="$2"; shift 2; '
             'exec psql -X -qAt -v ON_ERROR_STOP=1 -U "$db_user" -d "$db_name" "$@"')
    command = ["docker", "compose", "-f", str(args.compose_file), "exec", "-T", args.postgres_service,
               "sh", "-ec", shell, "admira-pool", args.db_user, args.db_name]
    for name, value in (variables or {}).items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", name) or "\n" in value or "\r" in value:
            raise ValueError("invalid database variable")
        command.extend(["-v", f"{name}={value}"])
    completed = (runner or subprocess.run)(command, input=sql + payload, text=True, capture_output=True, check=False)
    if getattr(completed, "returncode", 1) != 0:
        raise RuntimeError("database operation failed")
    return str(getattr(completed, "stdout", "")).strip()


def register(args: argparse.Namespace, *, stream: TextIO = sys.stdin, runner: Runner | None = None,
             health_check: Callable[[str], bool] | None = None) -> dict[str, object]:
    if args.key_kind != "auth":
        raise ValueError("commercial pool credentials must be auth keys")
    project = _project(args.project_ref)
    if not 1 <= int(args.capacity) <= 10000:
        raise ValueError("project capacity is invalid")
    key = _key(args, stream)
    if args.dry_run:
        return {"ok": True, "dry_run": True, "project_ref": project, "key_kind": "auth"}
    healthy = (health_check or provider_admin.check_gemini_api_key)(key)
    if not healthy:
        raise ValueError("Gemini health check failed")
    secret_ref, fingerprint, _created = _store(args.pool_root, key)
    try:
        # Both metadata changes are one PostgreSQL statement/transaction.  A
        # transport failure can be commit-ambiguous, so keep the private key
        # file and make retries idempotent instead of risking a dangling DB ref.
        registration_sql = (
            "WITH project AS (\n"
            "  SELECT admira.register_gemini_pool_project(:'project_ref', :'capacity'::integer, 'healthy') AS id\n"
            ")\n"
            "SELECT json_build_object(\n"
            "  'project_id', project.id,\n"
            "  'credential_id', admira.register_gemini_pool_credential(\n"
            "    project.id, :'secret_ref', :'fingerprint', 'healthy', 'auth')\n"
            ") FROM project;\n"
        )
        raw = _psql(
            args, registration_sql, runner=runner,
            variables={
                "project_ref": project,
                "capacity": str(args.capacity),
                "secret_ref": secret_ref,
                "fingerprint": fingerprint,
            },
        )
        registered = json.loads(raw.splitlines()[-1])
        _uuid(registered["project_id"], "project identifier")
        _uuid(registered["credential_id"], "credential identifier")
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError, RuntimeError):
        raise RuntimeError("pool registration failed")
    return {"ok": True, "project_ref": project, "fingerprint": fingerprint, "secret_ref": secret_ref}


def _release_unfinalized(args: argparse.Namespace, runtime: str, *, runner: Runner | None) -> bool:
    try:
        raw = _psql(
            args,
            "SELECT admira.release_hosted_gemini_trial(:'runtime_key', 'operator');\n",
            runner=runner,
            variables={"runtime_key": runtime},
        )
        return raw.splitlines()[-1] in {"0", "1"}
    except Exception:
        # The DB function itself refuses to release a finalized active trial.
        return False


def assign(args: argparse.Namespace, *, runner: Runner | None = None,
           manage: Callable[..., dict[str, object]] | None = None,
           fence: Callable[[str], bool] | None = None) -> dict[str, object]:
    runtime = _runtime(args.runtime_key)
    if args.dry_run:
        return {"ok": True, "dry_run": True, "runtime_key": runtime}
    row = _psql(args, "SELECT row_to_json(x) FROM admira.assign_hosted_gemini_trial(:'runtime_key') x;\n",
                payload="", runner=runner, variables={"runtime_key": runtime})
    if not row:
        raise RuntimeError("no eligible Gemini pool assignment")
    try:
        metadata = json.loads(row.splitlines()[-1])
        if not isinstance(metadata, dict) or metadata.get("key_kind") != "auth":
            raise ValueError("invalid assignment metadata")
        assignment_id = _uuid(metadata["assignment_id"], "assignment identifier")
        key = _stored_key(args.pool_root, str(metadata["secret_ref"]), str(metadata["fingerprint"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        _release_unfinalized(args, runtime, runner=runner)
        raise RuntimeError("invalid pool assignment response") from exc
    manage_fn = manage or provider_admin.manage_gemini_key
    if fence is None:
        fence = provider_admin._broker_runtime_fence(args)
    finalized = False
    finalize = "SELECT admira.finalize_hosted_gemini_trial(:'runtime_key', :'assignment_id'::uuid);\n"

    def record_metadata(_metadata: dict[str, object]) -> None:
        nonlocal finalized
        raw = _psql(
            args, finalize, runner=runner,
            variables={"runtime_key": runtime, "assignment_id": assignment_id},
        )
        if raw.splitlines()[-1].lower() not in {"t", "f", "true", "false"}:
            raise RuntimeError("invalid finalization response")
        finalized = True

    try:
        result = manage_fn(
            args.base_dir, runtime, value=key, source="operator_pool", replace=True,
            health_check=provider_admin.gemini_health_check,
            runtime_fence=fence, record_metadata=record_metadata,
        )
    except Exception:
        cleaned = _release_unfinalized(args, runtime, runner=runner)
        return {
            "ok": False, "error_code": "assignment_failed", "runtime_key": runtime,
            "cleanup_pending": not cleaned,
        }
    if not result.get("ok"):
        # manage_gemini_key has already restored the previous env on failure.
        cleaned = _release_unfinalized(args, runtime, runner=runner)
        return {
            "ok": False,
            "error_code": str(result.get("error_code", "assignment_failed")),
            "runtime_key": runtime,
            "cleanup_pending": not cleaned,
        }
    if not finalized:
        # Guard the injectable seam: a successful credential writer must have
        # called the durable metadata recorder before success is accepted.
        cleaned = _release_unfinalized(args, runtime, runner=runner)
        return {
            "ok": False, "error_code": "finalize_failed", "runtime_key": runtime,
            "cleanup_pending": not cleaned,
        }
    return {"ok": True, "runtime_key": runtime, "assignment_id": assignment_id,
            "fingerprint": metadata["fingerprint"]}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Manage the Admira Gemini trial pool")
    p.add_argument("--pool-root", type=Path, default=DEFAULT_POOL_ROOT)
    p.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE)
    p.add_argument("--postgres-service", default="postgres")
    p.add_argument("--db-user", default="admira_provisioner_login")
    p.add_argument("--db-name", default="admira_control")
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("register"); r.add_argument("project_ref"); r.add_argument("--capacity", type=int, required=True)
    r.add_argument("--key-kind", choices=("auth", "standard", "unknown"), required=True,
                   help="explicit operator assertion; the commercial pool accepts only auth")
    r.add_argument("--key-file", type=Path); r.add_argument("--dry-run", action="store_true")
    a = sub.add_parser("assign"); a.add_argument("runtime_key"); a.add_argument("--base-dir", type=Path, default=provider_admin.DEFAULT_BASE); a.add_argument("--dry-run", action="store_true")
    a.add_argument("--broker-socket", type=Path, default=Path(os.environ.get("ADMIRA_BROKER_SOCKET", "/run/admira-runtime-broker/broker.sock")))
    a.add_argument("--broker-key-file", type=Path, default=Path(os.environ.get("ADMIRA_BROKER_KEY_FILE", "/etc/admira/runtime-broker.key")))
    return p


def main(argv: Iterable[str] | None = None, *, stdin: TextIO | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = register(args, stream=stdin or sys.stdin) if args.command == "register" else assign(args)
    except (OSError, ValueError):
        result = {"ok": False, "error_code": "invalid_pool_request"}
    except RuntimeError as exc:
        result = {"ok": False, "error_code": str(exc) if str(exc) in {"finalize_failed", "assignment_failed"} else "pool_operation_failed"}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
