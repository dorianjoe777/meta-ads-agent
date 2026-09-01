#!/usr/bin/env python3
"""Safely manage the provider credential for one hosted tenant.

The credential is deliberately accepted only through stdin or a private file;
it is never a command-line argument, logged, or returned in the JSON result.
The low-level file update remains dependency-free.  The ``gemini-license``
operator command additionally performs the matching PostgreSQL transition via
Compose, with all sensitive values supplied on stdin rather than argv.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, Iterable, TextIO


TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")
DEFAULT_BASE = Path("/srv/admira/tenants")
DEFAULT_COMPOSE_FILE = Path(__file__).resolve().with_name("compose.yaml")
DEFAULT_RECOVERY_HMAC_KEY_FILE = Path(__file__).resolve().with_name("secrets") / "recovery_hmac_key.txt"
ENV_NAME = "GEMINI_API_KEY"
Validator = Callable[[str], object]
HealthCheck = Callable[[Path], object]
MetadataRecorder = Callable[[dict[str, object]], object]
RuntimeFence = Callable[[str], object]
SubprocessRunner = Callable[..., object]
# Kept injectable for offline operator tests; importing runtime_broker eagerly
# would also load its host-runtime dependencies for simple file operations.
BrokerClient: object | None = None
LICENSE_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
# Keep this in lockstep with tenant_provider_credentials_secret_ref_check in
# migration 007: this is metadata identifying where a secret lives, never the
# provider credential itself.
SECRET_REF_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1"
GEMINI_HEALTH_TIMEOUT_SECONDS = 8
GEMINI_HEALTH_MAX_RESPONSE_BYTES = 128 * 1024
PRIVATE_INPUT_MAX_CHARS = 16 * 1024


def _tenant_id(value: str) -> str:
    value = str(value).strip()
    if not TENANT_RE.fullmatch(value):
        raise ValueError("tenant_id must match [a-z0-9][a-z0-9-]{2,62}")
    return value


def _read_private_file(path: Path) -> str:
    """Read a key source through one no-follow descriptor and private mode."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError("key file must be a private regular file") from exc
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) & 0o077:
            raise ValueError("key file must be a private regular file")
        if details.st_size > PRIVATE_INPUT_MAX_CHARS:
            raise ValueError("key file is too large")
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            value = handle.read(PRIVATE_INPUT_MAX_CHARS + 1)
            if len(value) > PRIVATE_INPUT_MAX_CHARS:
                raise ValueError("key file is too large")
            return value
    except UnicodeError as exc:
        raise ValueError("key file must be a private regular file") from exc
    finally:
        if fd >= 0:
            os.close(fd)


def _read_private_text(path: Path) -> str:
    """Read a private regular file without a check-then-open race."""
    return _read_private_file(path)


def check_gemini_api_key(value: str, *, opener: Callable[..., object] | None = None) -> bool:
    """Verify one Gemini key using only the official models endpoint."""
    key = validate_gemini_key(value)
    request = urllib.request.Request(
        GEMINI_MODELS_URL,
        headers={
            "x-goog-api-key": key,
            "x-goog-api-client": "admira-hosted/r99",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        open_url = opener or urllib.request.urlopen
        response = open_url(request, timeout=GEMINI_HEALTH_TIMEOUT_SECONDS)
        with response:
            raw = response.read(GEMINI_HEALTH_MAX_RESPONSE_BYTES + 1)
        if len(raw) > GEMINI_HEALTH_MAX_RESPONSE_BYTES:
            return False
        payload = json.loads(raw.decode("utf-8"))
        return isinstance(payload, dict) and isinstance(payload.get("models"), list) and bool(payload["models"])
    except Exception:
        # Never expose provider response bodies, URLs with credentials, or
        # transport details through the operator CLI.
        return False


def gemini_health_check(env_path: Path) -> bool:
    """Read the just-written private tenant env and validate its Gemini key."""
    try:
        existing = _existing_key(_read_private_text(env_path))
        return bool(existing) and check_gemini_api_key(existing)
    except Exception:
        return False


def validate_gemini_key(value: str) -> str:
    """Perform local, provider-independent validation of a Gemini API key."""
    value = str(value).strip()
    if not 20 <= len(value) <= 512 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise ValueError("Gemini key format is invalid")
    return value


def _validate_license(value: str) -> str:
    value = str(value).strip()
    if not LICENSE_RE.fullmatch(value):
        raise ValueError("license format is invalid")
    return value


def _validate_secret_ref(value: str) -> str:
    """Validate an opaque external-secret reference, not a raw credential."""
    value = str(value)
    if (
        not 8 <= len(value) <= 512
        or not SECRET_REF_SCHEME_RE.match(value)
        or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError("secret reference format is invalid")
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
    try:
        base_details = base.lstat()
    except FileNotFoundError as exc:
        raise FileNotFoundError("tenant runtime is not provisioned") from exc
    if base.is_symlink() or not stat.S_ISDIR(base_details.st_mode):
        raise ValueError("tenant base must be a private regular directory")
    root = base / tenant_id
    runtime = root / "runtime"
    env_path = runtime / ".env"
    if not root.exists() or root.is_symlink() or not root.is_dir() or runtime.is_symlink() or not runtime.is_dir():
        raise FileNotFoundError("tenant runtime is not provisioned")
    if stat.S_IMODE(root.stat().st_mode) & 0o077 or stat.S_IMODE(runtime.stat().st_mode) & 0o077:
        raise ValueError("tenant runtime directories must be private")
    if env_path.exists() or env_path.is_symlink():
        details = env_path.lstat()
        if env_path.is_symlink() or not stat.S_ISREG(details.st_mode):
            raise ValueError("tenant runtime environment must be a private regular file")
        if stat.S_IMODE(details.st_mode) & 0o077:
            raise ValueError("tenant runtime environment must be a private regular file")
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


def _existing_key(text: str) -> str | None:
    """Return the sole existing key, rejecting ambiguous duplicate entries."""
    prefix = f"{ENV_NAME}="
    found: str | None = None
    for line in text.splitlines():
        if line.startswith(prefix):
            if found is not None:
                raise ValueError("tenant runtime environment contains duplicate Gemini keys")
            found = line[len(prefix):]
    return found


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
    replace: bool = False,
    validator: Validator | None = None,
    health_check: HealthCheck | None = None,
    allow_unverified: bool = False,
    record_metadata: MetadataRecorder | None = None,
    runtime_fence: RuntimeFence | None = None,
) -> dict[str, object]:
    """Set or clear one tenant key, returning metadata but never the secret."""
    if source not in {"operator_pool", "customer"}:
        raise ValueError("source must be operator_pool or customer")
    path = _runtime_env(Path(base), tenant_id)
    old_existed = path.exists()
    old = _read_private_text(path) if old_existed else ""
    old_mode = stat.S_IMODE(path.stat().st_mode) if old_existed else 0o600
    if value is None:
        new_value = ""
        fingerprint = None
    else:
        new_value = _validated(value, validator)
        fingerprint = hashlib.sha256(new_value.encode("utf-8")).hexdigest()
    existing = _existing_key(old)
    if existing and existing != new_value and not replace:
        raise ValueError("existing Gemini key differs; pass --replace to change it")
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
    if runtime_fence is not None:
        try:
            if runtime_fence(_tenant_id(tenant_id)) is False:
                return {"ok": False, "error_code": "runtime_fence_failed", "tenant_id": _tenant_id(tenant_id), "source": source}
        except Exception:
            # Fencing is fail-closed: do not write env or invoke DB callback.
            return {"ok": False, "error_code": "runtime_fence_failed", "tenant_id": _tenant_id(tenant_id), "source": source}
    def rollback(failure_code: str) -> dict[str, object]:
        try:
            if old_existed:
                _atomic_write(path, old)
                os.chmod(path, old_mode)
            else:
                path.unlink(missing_ok=True)
                directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except OSError as rollback_error:
            raise RuntimeError(f"{failure_code}; rollback failed") from rollback_error
        return {"ok": False, "error_code": failure_code, "tenant_id": _tenant_id(tenant_id), "source": source}

    try:
        _atomic_write(path, new_text)
    except OSError:
        # os.replace may already have published the new value before a later
        # durability operation fails. Restore the exact prior state instead of
        # letting callers release DB ownership while the new key remains live.
        return rollback("environment_write_failed")

    try:
        effective_health_check = health_check or gemini_health_check
        if value is not None and not allow_unverified and effective_health_check(path) is False:
            return rollback("health_check_failed")
    except Exception:
        return rollback("health_check_failed")
    if record_metadata is not None:
        metadata = {"tenant_id": _tenant_id(tenant_id), "source": source, "action": result["action"], "fingerprint": fingerprint}
        try:
            record_metadata(metadata)
        except Exception:
            return rollback("metadata_record_failed")
    return result


def _psql_copy_value(value: str, label: str) -> str:
    """Validate a value transported through psql COPY input (never SQL text)."""
    value = str(value)
    if not value or "\t" in value or "\r" in value or "\n" in value or "\\" in value:
        raise ValueError(f"{label} contains unsupported characters")
    return value


def transition_hosted_tenant_to_licensed(
    runtime_key: str,
    license_id: str,
    secret_ref: str,
    fingerprint: str,
    actor: str,
    *,
    compose_file: Path = DEFAULT_COMPOSE_FILE,
    postgres_service: str = "postgres",
    db_user: str = "admira_provisioner_login",
    db_name: str = "admira_control",
    email_hmac_hex: str | None = None,
    license_hmac_hex: str | None = None,
    delivery_ref: str | None = None,
    runner: SubprocessRunner | None = None,
) -> None:
    """Call the license transition with all values supplied as psql COPY input.

    No credential or license is placed in argv.  The psql input is a fixed
    statement plus one tab-separated data row; values are validated so they
    cannot alter the COPY stream or SQL statement.
    """
    runtime_key = _psql_copy_value(runtime_key, "runtime key")
    license_id = _psql_copy_value(_validate_license(license_id), "license")
    secret_ref = _psql_copy_value(_validate_secret_ref(secret_ref), "secret reference")
    fingerprint = _psql_copy_value(fingerprint, "fingerprint")
    actor = _psql_copy_value(actor, "actor")
    has_contact = any(value is not None for value in (email_hmac_hex, license_hmac_hex, delivery_ref))
    if has_contact and not all(value is not None for value in (email_hmac_hex, license_hmac_hex, delivery_ref)):
        raise ValueError("recovery contact is incomplete")
    if has_contact:
        if not re.fullmatch(r"[a-f0-9]{64}", str(email_hmac_hex)) or not re.fullmatch(r"[a-f0-9]{64}", str(license_hmac_hex)):
            raise ValueError("recovery contact is invalid")
        delivery_ref = _psql_copy_value(str(delivery_ref), "delivery reference")
        if delivery_ref != "sealed-envelope://v1":
            raise ValueError("recovery delivery reference is invalid")
    shell = (
        'export PGPASSWORD="$(cat /run/secrets/provisioner_db_password)"; '
        'exec psql -X -v ON_ERROR_STOP=1 -U "$1" -d "$2"'
    )
    command = [
        "docker", "compose", "-f", str(compose_file), "exec", "-T", postgres_service,
        "sh", "-ec", shell, "admira-license", db_user, db_name,
    ]
    payload = (
        "BEGIN;\n"
        "CREATE TEMP TABLE _admira_license_args (runtime_key text, license_id text, secret_ref text, fingerprint text, actor text, email_hmac_hex text, license_hmac_hex text, delivery_ref text);\n"
        "COPY _admira_license_args FROM STDIN;\n"
        f"{runtime_key}\t{license_id}\t{secret_ref}\t{fingerprint}\t{actor}\t{email_hmac_hex or ''}\t{license_hmac_hex or ''}\t{delivery_ref or ''}\n"
        "\\.\n"
        "CREATE TEMP TABLE _admira_license_result AS\n"
        "SELECT licensed.tenant_id FROM _admira_license_args a\n"
        "CROSS JOIN LATERAL admira.transition_hosted_tenant_to_licensed(a.runtime_key, a.license_id, a.secret_ref, a.fingerprint, a.actor) AS licensed;\n"
        "SELECT CASE WHEN NULLIF(a.email_hmac_hex, '') IS NULL THEN true ELSE admira.register_verified_license_contact(r.tenant_id, a.email_hmac_hex, a.license_hmac_hex, a.delivery_ref, now(), a.actor) END\n"
        "FROM _admira_license_args a CROSS JOIN _admira_license_result r;\n"
        "COMMIT;\n"
    )
    completed = (runner or subprocess.run)(command, input=payload, text=True, capture_output=True, check=False)
    if getattr(completed, "returncode", 1) != 0:
        # Deliberately discard stderr: psql may include SQL values in errors.
        raise RuntimeError("license transition failed")


def make_license_metadata_recorder(
    tenant_id: str,
    license_id: str,
    *,
    actor: str = "operator",
    secret_ref: str | None = None,
    email_hmac_hex: str | None = None,
    license_hmac_hex: str | None = None,
    delivery_ref: str | None = None,
    transition: Callable[..., object] | None = None,
) -> MetadataRecorder:
    """Build the metadata callback used by ``gemini-license``."""
    tenant_id = _tenant_id(tenant_id)
    license_id = _validate_license(license_id)
    actor = _psql_copy_value(actor, "actor")
    ref = _validate_secret_ref(secret_ref or f"tenant-env://{tenant_id}/GEMINI_API_KEY")

    def recorder(metadata: dict[str, object]) -> None:
        fingerprint = str(metadata.get("fingerprint") or "")
        args = (tenant_id, license_id, ref, fingerprint, actor)
        if email_hmac_hex is None and license_hmac_hex is None and delivery_ref is None:
            (transition or transition_hosted_tenant_to_licensed)(*args)
        else:
            (transition or transition_hosted_tenant_to_licensed)(
                *args, email_hmac_hex=email_hmac_hex, license_hmac_hex=license_hmac_hex,
                delivery_ref=delivery_ref,
            )

    return recorder


def _input_key(args: argparse.Namespace, stream: TextIO) -> str:
    if args.key_file is not None:
        return _read_private_file(args.key_file)
    value = stream.read(PRIVATE_INPUT_MAX_CHARS + 1)
    if len(value) > PRIVATE_INPUT_MAX_CHARS:
        raise ValueError("key input is too large")
    return value


def _input_license(args: argparse.Namespace) -> str:
    if args.license_file is not None:
        return _validate_license(_read_private_file(args.license_file))
    return _validate_license(secrets.token_urlsafe(24))


def _recovery_primitives():
    """Load recovery hashing without making provider_admin a package import."""
    try:
        from recovery_identity import (  # type: ignore
            email_digest, license_digest, normalize_email, read_private_hmac_key,
        )
        return email_digest, license_digest, normalize_email, read_private_hmac_key
    except ImportError:
        spec = importlib.util.spec_from_file_location(
            "_admira_recovery_identity", Path(__file__).with_name("recovery_identity.py")
        )
        if spec is None or spec.loader is None:
            raise ValueError("recovery configuration is invalid")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.email_digest, module.license_digest, module.normalize_email, module.read_private_hmac_key


def _broker_runtime_fence(args: argparse.Namespace) -> RuntimeFence:
    """Build a callback for the authenticated host runtime broker."""
    broker_type = BrokerClient
    try:
        if broker_type is None:
            from runtime_broker import BrokerClient as broker_type  # type: ignore
    except Exception as exc:
        def unavailable(_tenant_id: str) -> bool:
            raise RuntimeError("runtime broker unavailable") from exc
        return unavailable
    client = broker_type(args.broker_socket, args.broker_key_file)  # type: ignore[operator]

    def fence(tenant_id: str) -> bool:
        response = client.request({"action": "suspend", "tenant_id": tenant_id})
        return bool(response.get("ok"))

    return fence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage one hosted tenant Gemini credential")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("gemini-set", "gemini-clear", "gemini-license"):
        command = commands.add_parser(name)
        command.add_argument("tenant_id")
        command.add_argument("--source", required=True, choices=("operator_pool", "customer"))
        command.add_argument("--base-dir", type=Path, default=DEFAULT_BASE)
        command.add_argument("--key-file", type=Path, help="private regular file; otherwise read key from stdin")
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--replace", action="store_true", help="explicitly replace a different existing key")
        command.add_argument(
            "--allow-unverified", action="store_true",
            help="explicitly skip the live Gemini health check (operator emergency only)",
        )
        command.add_argument(
            "--runtime-already-stopped", action="store_true",
            help="explicitly bypass the host runtime suspend fence",
        )
        command.add_argument(
            "--broker-socket", type=Path,
            default=Path(os.environ.get("ADMIRA_BROKER_SOCKET", "/run/admira-runtime-broker/broker.sock")),
        )
        command.add_argument(
            "--broker-key-file", type=Path,
            default=Path(os.environ.get("ADMIRA_BROKER_KEY_FILE", "/etc/admira/runtime-broker.key")),
        )
        if name == "gemini-license":
            command.add_argument("--license-file", type=Path, help="private regular file; otherwise generate a license")
            command.add_argument("--email-file", type=Path, help="private mode-0600 recovery email file")
            command.add_argument(
                "--recovery-hmac-key-file", type=Path,
                default=DEFAULT_RECOVERY_HMAC_KEY_FILE,
                help="private mode-0600 recovery HMAC key file",
            )
            command.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
            command.add_argument("--postgres-service", default="postgres")
            # Use the narrowly granted provisioner login, not the database
            # owner. Deployments that rename it must pass the matching value.
            command.add_argument("--db-user", default="admira_provisioner_login")
            command.add_argument("--db-name", default="admira_control")
            command.add_argument("--actor", default="operator")
    return parser


def main(argv: Iterable[str] | None = None, *, stdin: TextIO | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        value = None if args.command == "gemini-clear" else _input_key(args, stdin or sys.stdin)
        if args.command == "gemini-license":
            if args.source != "customer":
                raise ValueError("gemini-license requires --source customer")
            license_id = _input_license(args)
            if args.email_file is None:
                raise ValueError("gemini-license requires a private recovery email file")
            email_digest, license_digest, normalize_email, read_private_hmac_key = _recovery_primitives()
            # The email is consumed only in memory and never enters argv,
            # stdout, SQL, or exception text.
            email = normalize_email(_read_private_text(args.email_file))
            hmac_key = read_private_hmac_key(args.recovery_hmac_key_file)
            email_hmac_hex = email_digest(hmac_key, email).hex()
            license_hmac_hex = license_digest(hmac_key, license_id).hex()
            delivery_ref = "sealed-envelope://v1"
            transition = lambda runtime_key, license_value, secret_ref, fingerprint, actor, **contact: transition_hosted_tenant_to_licensed(
                runtime_key, license_value, secret_ref, fingerprint, actor,
                compose_file=args.compose_file, postgres_service=args.postgres_service,
                db_user=args.db_user, db_name=args.db_name,
                **contact,
            )
            recorder = make_license_metadata_recorder(
                args.tenant_id, license_id, actor=args.actor, transition=transition,
                email_hmac_hex=email_hmac_hex, license_hmac_hex=license_hmac_hex,
                delivery_ref=delivery_ref,
            )
            result = manage_gemini_key(
                args.base_dir, args.tenant_id, value=value, source=args.source,
                dry_run=args.dry_run, replace=args.replace, record_metadata=recorder,
                allow_unverified=args.allow_unverified,
                runtime_fence=None if args.runtime_already_stopped else _broker_runtime_fence(args),
            )
            if result.get("ok"):
                # The operator needs this one-time value to issue to the customer.
                result["license_id"] = license_id
        else:
            result = manage_gemini_key(
                args.base_dir, args.tenant_id, value=value, source=args.source,
                dry_run=args.dry_run, replace=args.replace,
                allow_unverified=args.allow_unverified,
                runtime_fence=None if args.runtime_already_stopped else _broker_runtime_fence(args),
            )
    except (OSError, ValueError) as exc:
        result = {"ok": False, "error_code": "invalid_gemini_credential", "detail": str(exc)}
    except RuntimeError:
        result = {"ok": False, "error_code": "gemini_credential_update_failed"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
