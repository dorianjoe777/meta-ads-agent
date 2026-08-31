#!/usr/bin/env python3
"""Narrow host boundary for the private Admira operator dashboard.

The dashboard has no Docker socket, tenant filesystem, provisioner database
password, Gemini pool secret, or hosted-license bridge credential.  It can
only send a signed, bounded request to this host-side service.  This service
owns the existing allowlisted tenant/provisioner helpers and returns a small,
secret-free result object.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import socketserver
import stat
import subprocess
import tempfile
import threading
import time
import urllib.request
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parent
DEFAULT_SOCKET = Path("/run/admira-tenant-provisioner/provisioner.sock")
DEFAULT_KEY_FILE = Path("/etc/admira/tenant-provisioner.key")
DEFAULT_REPLAY_STATE = Path("/var/lib/admira/tenant-provisioner/replay-nonces.json")
DEFAULT_LICENSE_KEY_FILE = Path("/etc/admira/hosted-license-bridge.key")
DEFAULT_LICENSE_URL = "https://admiraia.uboost.lat/api/admin/licenses"
DEFAULT_BOT_USERNAME = "admiraia_bot"
DEFAULT_BASE = Path("/srv/admira/tenants")
MAX_WIRE_BYTES = 64 * 1024
MAX_LICENSE_RESPONSE_BYTES = 64 * 1024
MAX_REPLAY_ENTRIES = 4096
TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")
BOT_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")
ACTOR_RE = re.compile(r"^[A-Za-z0-9._:-]{3,200}$")
SAFE_CODE = re.compile(r"^[a-z0-9_]{3,80}$")
LICENSE_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
ALLOWED = frozenset({"create_trial", "reissue_trial_claim", "extend_trial", "expire_trial", "license_trial"})


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _load_private_bytes(path: Path, *, minimum: int = 1, maximum: int = 4096) -> bytes:
    """Read one regular private file without following a caller-controlled link."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError("private_key_unavailable") from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077
                or info.st_nlink != 1 or info.st_size > maximum):
            raise ValueError("private_key_unavailable")
        value = os.read(fd, maximum + 1).strip()
    finally:
        os.close(fd)
    if not minimum <= len(value) <= maximum:
        raise ValueError("private_key_unavailable")
    return value


def _load_key(path: Path) -> bytes:
    return _load_private_bytes(path, minimum=32, maximum=512)


def sign_body(key: bytes, body: dict[str, object], *, now: int | None = None,
              nonce: str | None = None) -> dict[str, object]:
    """Return the exact HMAC envelope consumed by the Unix-socket server."""
    envelope: dict[str, object] = {
        "timestamp": int(now if now is not None else time.time()),
        "nonce": nonce or secrets.token_hex(16),
        "body": body,
    }
    envelope["signature"] = hmac.new(key, _canonical(envelope), hashlib.sha256).hexdigest()
    return envelope


class ReplayWindow:
    """Reject duplicate signed requests, including across a service restart."""

    def __init__(self, state_file: Path | None = None) -> None:
        self._state_file = Path(state_file) if state_file else None
        self._seen: dict[str, int] = {}
        self._lock = threading.Lock()
        if self._state_file:
            self._seen = self._read_state()

    def _read_state(self) -> dict[str, int]:
        path = self._state_file
        assert path is not None
        try:
            info = path.lstat()
        except FileNotFoundError:
            return {}
        if path.is_symlink() or not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077 \
                or info.st_size > MAX_WIRE_BYTES:
            raise ValueError("replay_state_unavailable")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("replay_state_unavailable") from exc
        if not isinstance(data, dict) or len(data) > MAX_REPLAY_ENTRIES:
            raise ValueError("replay_state_unavailable")
        result: dict[str, int] = {}
        for nonce, timestamp in data.items():
            if not isinstance(nonce, str) or not re.fullmatch(r"[a-f0-9]{32}", nonce) \
                    or isinstance(timestamp, bool) or not isinstance(timestamp, int):
                raise ValueError("replay_state_unavailable")
            result[nonce] = timestamp
        return result

    def _persist(self) -> None:
        path = self._state_file
        if path is None:
            return
        parent = path.parent
        if parent.is_symlink() or not parent.is_dir() or stat.S_IMODE(parent.stat().st_mode) & 0o027:
            raise ValueError("replay_state_unavailable")
        payload = _canonical(self._seen)
        temporary = ""
        try:
            fd, temporary = tempfile.mkstemp(prefix=".replay-", dir=str(parent))
            try:
                os.fchmod(fd, 0o600)
                offset = 0
                while offset < len(payload):
                    offset += os.write(fd, payload[offset:])
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(temporary, path)
            directory = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError as exc:
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
            raise ValueError("replay_state_unavailable") from exc

    def verify(self, envelope: object, key: bytes, *, now: int | None = None) -> dict[str, object]:
        if not isinstance(envelope, dict):
            raise ValueError("invalid_envelope")
        try:
            timestamp = int(envelope.get("timestamp") or 0)
        except (TypeError, ValueError):
            raise ValueError("invalid_envelope") from None
        current = int(now if now is not None else time.time())
        if abs(current - timestamp) > 90:
            raise ValueError("expired_request")
        nonce = str(envelope.get("nonce") or "")
        signature = str(envelope.get("signature") or "")
        body = envelope.get("body")
        if not re.fullmatch(r"[a-f0-9]{32}", nonce) \
                or not re.fullmatch(r"[a-f0-9]{64}", signature) \
                or not isinstance(body, dict):
            raise ValueError("invalid_envelope")
        expected = hmac.new(
            key, _canonical({"timestamp": timestamp, "nonce": nonce, "body": body}), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid_signature")
        with self._lock:
            self._seen = {item: seen_at for item, seen_at in self._seen.items() if seen_at >= current - 180}
            if nonce in self._seen:
                raise ValueError("replayed_request")
            if len(self._seen) >= MAX_REPLAY_ENTRIES:
                raise ValueError("replay_window_full")
            self._seen[nonce] = current
            # Persist before executing a mutation. If the disk is unhealthy,
            # fail closed rather than permit a restart replay window.
            self._persist()
        return body


def _tenant(value: object) -> str:
    result = str(value or "").strip().lower()
    if not TENANT_RE.fullmatch(result):
        raise ValueError("invalid_tenant_key")
    return result


def _display(value: object) -> str:
    result = str(value or "").strip()
    if not result or len(result) > 200 or any(ord(char) < 32 or ord(char) == 127 for char in result):
        raise ValueError("invalid_display_name")
    return result


def _actor(value: object) -> str:
    result = str(value or "operator-dashboard").strip()
    if not ACTOR_RE.fullmatch(result):
        raise ValueError("invalid_actor")
    return result


def _bot_username(value: object) -> str:
    result = str(value or "").strip().removeprefix("@")
    if not BOT_RE.fullmatch(result):
        raise ValueError("invalid_bot_username")
    return result


def _ends_at(value: object) -> str:
    raw = str(value or "").strip()
    if not 20 <= len(raw) <= 64:
        raise ValueError("invalid_trial_extension")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid_trial_extension") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("invalid_trial_extension")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _customer_gemini_key(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid_customer_gemini_key")
    try:
        try:
            from provider_admin import validate_gemini_key
        except ImportError:
            from .provider_admin import validate_gemini_key  # type: ignore
        return validate_gemini_key(value)
    except Exception as exc:
        raise ValueError("invalid_customer_gemini_key") from exc


class ProvisionerCore:
    """Host adapter with injectable seams for safe unit tests."""

    def __init__(
        self,
        base: Path = DEFAULT_BASE,
        *,
        bot_username: str = DEFAULT_BOT_USERNAME,
        license_url: str = DEFAULT_LICENSE_URL,
        license_key_file: Path = DEFAULT_LICENSE_KEY_FILE,
        provision: Callable[[Path, str], dict[str, object]] | None = None,
        suspend: Callable[[Path, str], dict[str, object]] | None = None,
        assign_pool: Callable[[str], dict[str, object]] | None = None,
        create_license: Callable[[str, str], dict[str, object]] | None = None,
        install_license: Callable[[str, str, str, str], dict[str, object]] | None = None,
    ) -> None:
        self.base = Path(base)
        self.bot_username = _bot_username(bot_username)
        self.license_url = self._trusted_license_url(license_url)
        self.license_key_file = Path(license_key_file)
        self._provision_impl = provision
        self._suspend_impl = suspend
        self._assign_pool_impl = assign_pool
        self._create_license_impl = create_license
        self._install_license_impl = install_license

    @staticmethod
    def _trusted_license_url(value: str) -> str:
        try:
            from urllib.parse import urlsplit
            parsed = urlsplit(str(value))
        except ValueError as exc:
            raise ValueError("license_bridge_unavailable") from exc
        if (parsed.scheme != "https" or parsed.hostname != "admiraia.uboost.lat"
                or parsed.port not in {None, 443} or parsed.path != "/api/admin/licenses"
                or parsed.query or parsed.fragment or parsed.username or parsed.password):
            raise ValueError("license_bridge_unavailable")
        return "https://admiraia.uboost.lat/api/admin/licenses"

    def handle(self, request: dict[str, object]) -> dict[str, object]:
        action = str(request.get("action") or "")
        if action not in ALLOWED:
            raise ValueError("unsupported_action")
        tenant_key = _tenant(request.get("tenant_key"))
        actor = _actor(request.get("actor_id", "operator-dashboard"))
        if action == "create_trial":
            display_name = _display(request.get("display_name"))
            provisioned = self._provision_tenant(tenant_key)
            if not provisioned.get("ok"):
                return {"ok": False, "action": action, "tenant_key": tenant_key, "error_code": "tenant_provision_failed"}
            created = self._db_create_trial(tenant_key, display_name, actor)
            if not created.get("ok"):
                return {"ok": False, "action": action, "tenant_key": tenant_key, "error_code": "trial_create_failed"}
            assigned = self._ensure_trial_pool(tenant_key)
            if not assigned.get("ok"):
                return {"ok": False, "action": action, "tenant_key": tenant_key, "error_code": "gemini_pool_unavailable"}
            return self._issue_claim_response(action, tenant_key)
        if action == "reissue_trial_claim":
            assigned = self._ensure_trial_pool(tenant_key)
            if not assigned.get("ok"):
                return {"ok": False, "action": action, "tenant_key": tenant_key, "error_code": "gemini_pool_unavailable"}
            return self._issue_claim_response(action, tenant_key)
        if action == "extend_trial":
            result = self._db_extend_trial(tenant_key, _ends_at(request.get("ends_at")), actor)
            return self._safe_db_result(result, action, tenant_key, "trial_update_failed")
        if action == "expire_trial":
            result = self._db_expire_trial(tenant_key, actor)
            response = self._safe_db_result(result, action, tenant_key, "trial_expire_failed")
            if not response.get("ok"):
                return response
            suspended = self._suspend_tenant(tenant_key)
            if not suspended.get("ok"):
                return {"ok": False, "action": action, "tenant_key": tenant_key, "error_code": "runtime_suspend_pending"}
            return response
        # The raw key remains inside this function and is never appended to a
        # command, database argument, response, exception, or audit payload.
        display_name = _display(request.get("display_name"))
        gemini_key = _customer_gemini_key(request.get("gemini_api_key"))
        try:
            return self._license_trial(tenant_key, display_name, gemini_key, actor)
        finally:
            gemini_key = ""

    @staticmethod
    def _safe_db_result(result: dict[str, object], action: str, tenant_key: str,
                        failure: str) -> dict[str, object]:
        if not result.get("ok"):
            return {"ok": False, "action": action, "tenant_key": tenant_key, "error_code": failure}
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        output: dict[str, object] = {"ok": True, "action": action, "tenant_key": tenant_key}
        for name in ("lifecycle_state", "previous_trial_ends_at", "trial_ends_at", "expired_at"):
            value = data.get(name)
            if value is not None:
                output[name] = str(value)[:64]
        return output

    def _issue_claim_response(self, action: str, tenant_key: str) -> dict[str, object]:
        claim = self._claim_action(tenant_key)
        if not claim.get("ok"):
            return {"ok": False, "action": action, "tenant_key": tenant_key, "error_code": "claim_unavailable"}
        return {"ok": True, "action": action, "tenant_key": tenant_key, "claim": claim["claim"]}

    def _provision_tenant(self, tenant_key: str) -> dict[str, object]:
        try:
            if self._provision_impl is not None:
                result = self._provision_impl(self.base, tenant_key)
            else:
                from tenantctl import provision
                result = provision(self.base, tenant_key)
            return result if isinstance(result, dict) else {"ok": False}
        except Exception:
            return {"ok": False}

    def _suspend_tenant(self, tenant_key: str) -> dict[str, object]:
        try:
            if self._suspend_impl is not None:
                result = self._suspend_impl(self.base, tenant_key)
            else:
                from tenantctl import lifecycle
                result = lifecycle(self.base, tenant_key, "suspend")
            return result if isinstance(result, dict) else {"ok": False}
        except Exception:
            return {"ok": False}

    def _ensure_trial_pool(self, tenant_key: str) -> dict[str, object]:
        try:
            if self._assign_pool_impl is not None:
                result = self._assign_pool_impl(tenant_key)
            else:
                from gemini_pool_admin import assign
                result = assign(Namespace(
                    runtime_key=tenant_key, base_dir=self.base,
                    pool_root=Path(os.environ.get("ADMIRA_GEMINI_POOL_ROOT", "/etc/admira/gemini-pool")),
                    compose_file=ROOT / "compose.yaml", postgres_service="postgres",
                    db_user="admira_provisioner_login", db_name=os.environ.get("POSTGRES_DB", "admira_control"),
                    dry_run=False,
                    broker_socket=Path(os.environ.get("ADMIRA_BROKER_SOCKET", "/run/admira-runtime-broker/broker.sock")),
                    broker_key_file=Path(os.environ.get("ADMIRA_BROKER_KEY_FILE", "/etc/admira/runtime-broker.key")),
                ))
            return result if isinstance(result, dict) else {"ok": False}
        except Exception:
            return {"ok": False}

    def _db_call(self, sql: str, tenant_key: str, *, display_name: str = "", token_hash: str = "",
                 ends_at: str = "", actor: str = "operator-dashboard") -> dict[str, object]:
        """Run a fixed query with psql variables; no secret is transported here."""
        shell = (
            'export PGPASSWORD="$(cat /run/secrets/provisioner_db_password)"; '
            'exec psql -v ON_ERROR_STOP=1 -X -qAt -U admira_provisioner_login '
            '-d "$POSTGRES_DB" -v tenant_key="$1" -v display_name="$2" '
            '-v token_hash="$3" -v ends_at="$4" -v actor_id="$5"'
        )
        command = [
            "docker", "compose", "--project-directory", str(ROOT), "-f", str(ROOT / "compose.yaml"),
            "exec", "-T", "postgres", "sh", "-ec", shell, "admira-provisioner",
            tenant_key, display_name, token_hash, ends_at, actor,
        ]
        try:
            completed = subprocess.run(command, input=sql, text=True, capture_output=True, check=False, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return {"ok": False}
        if completed.returncode != 0:
            # stderr can include database values: intentionally discard it.
            return {"ok": False}
        try:
            lines = [line for line in completed.stdout.splitlines() if line.strip()]
            value = json.loads(lines[-1])
        except (IndexError, TypeError, ValueError, json.JSONDecodeError):
            return {"ok": False}
        return {"ok": True, "data": value} if isinstance(value, dict) else {"ok": False}

    def _db_create_trial(self, tenant_key: str, display_name: str, actor: str) -> dict[str, object]:
        return self._db_call(
            "SELECT row_to_json(result) FROM (SELECT * FROM admira.operator_create_trial(:'tenant_key', :'display_name', :'actor_id')) AS result;\n",
            tenant_key, display_name=display_name, actor=actor,
        )

    def _db_extend_trial(self, tenant_key: str, ends_at: str, actor: str) -> dict[str, object]:
        return self._db_call(
            "SELECT row_to_json(result) FROM (SELECT * FROM admira.operator_extend_trial(:'tenant_key', :'ends_at'::timestamptz, :'actor_id')) AS result;\n",
            tenant_key, ends_at=ends_at, actor=actor,
        )

    def _db_expire_trial(self, tenant_key: str, actor: str) -> dict[str, object]:
        return self._db_call(
            "SELECT row_to_json(result) FROM (SELECT * FROM admira.operator_expire_trial(:'tenant_key', :'actor_id')) AS result;\n",
            tenant_key, actor=actor,
        )

    def _claim_action(self, tenant_key: str) -> dict[str, object]:
        raw = secrets.token_urlsafe(24)
        token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        result = self._db_call(
            "SELECT row_to_json(result) FROM (SELECT * FROM admira.issue_trial_telegram_claim(:'tenant_key', :'token_hash')) AS result;\n",
            tenant_key, token_hash=token_hash,
        )
        if not result.get("ok"):
            return {"ok": False}
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        claim: dict[str, object] = {"start_parameter": raw, "expires_at": str(data.get("expires_at") or "")[:64]}
        claim["telegram_url"] = f"https://t.me/{self.bot_username}?start={raw}"
        return {"ok": True, "claim": claim}

    def _create_hosted_license(self, tenant_key: str, display_name: str) -> dict[str, object]:
        if self._create_license_impl is not None:
            try:
                result = self._create_license_impl(tenant_key, display_name)
            except Exception:
                return {"ok": False, "error_code": "license_bridge_unavailable"}
            return result if isinstance(result, dict) else {"ok": False, "error_code": "license_bridge_unavailable"}
        bridge_key = ""
        try:
            bridge_key = _load_key(self.license_key_file).decode("ascii")
            payload = _canonical({
                "action": "create_hosted_tenant_license", "external_customer_id": tenant_key,
                "display_name": display_name, "plan": "individual",
            })
            request = urllib.request.Request(
                self.license_url, data=payload, method="POST",
                headers={"Authorization": f"Bearer {bridge_key}", "Content-Type": "application/json", "Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read(MAX_LICENSE_RESPONSE_BYTES + 1)
            if len(raw) > MAX_LICENSE_RESPONSE_BYTES:
                raise ValueError("license_bridge_rejected")
            payload_json = json.loads(raw.decode("utf-8"))
            license_key = str(payload_json.get("license", {}).get("license_key") or "")
            if not payload_json.get("ok") or not LICENSE_RE.fullmatch(license_key):
                raise ValueError("license_bridge_rejected")
            return {"ok": True, "license_key": license_key, "created": bool(payload_json.get("created"))}
        except ValueError as exc:
            code = str(exc)
            return {"ok": False, "error_code": code if code == "license_bridge_rejected" else "license_bridge_unavailable"}
        except Exception:
            return {"ok": False, "error_code": "license_bridge_unavailable"}
        finally:
            # Do not keep a decoded server-to-server secret around after the
            # bounded HTTPS request, including an error/retry path.
            bridge_key = ""

    def _install_customer_gemini(self, tenant_key: str, license_key: str, gemini_key: str,
                                 actor: str) -> dict[str, object]:
        if self._install_license_impl is not None:
            try:
                result = self._install_license_impl(tenant_key, license_key, gemini_key, actor)
            except Exception:
                return {"ok": False, "error_code": "license_transition_failed"}
            return result if isinstance(result, dict) else {"ok": False, "error_code": "license_transition_failed"}
        try:
            from provider_admin import _broker_runtime_fence, make_license_metadata_recorder, manage_gemini_key
            args = Namespace(
                broker_socket=Path(os.environ.get("ADMIRA_BROKER_SOCKET", "/run/admira-runtime-broker/broker.sock")),
                broker_key_file=Path(os.environ.get("ADMIRA_BROKER_KEY_FILE", "/etc/admira/runtime-broker.key")),
            )
            recorder = make_license_metadata_recorder(tenant_key, license_key, actor=actor)
            result = manage_gemini_key(
                self.base, tenant_key, value=gemini_key, source="customer", replace=True,
                runtime_fence=_broker_runtime_fence(args), record_metadata=recorder,
            )
        except Exception:
            return {"ok": False, "error_code": "license_transition_failed"}
        if not isinstance(result, dict) or not result.get("ok"):
            return {"ok": False, "error_code": "license_transition_failed"}
        return {"ok": True}

    def _license_trial(self, tenant_key: str, display_name: str, gemini_key: str,
                       actor: str) -> dict[str, object]:
        created = self._create_hosted_license(tenant_key, display_name)
        if not created.get("ok"):
            return {"ok": False, "action": "license_trial", "tenant_key": tenant_key,
                    "error_code": str(created.get("error_code") or "license_bridge_unavailable")}
        license_key = str(created.get("license_key") or "")
        if not LICENSE_RE.fullmatch(license_key):
            return {"ok": False, "action": "license_trial", "tenant_key": tenant_key,
                    "error_code": "license_bridge_rejected"}
        installed = self._install_customer_gemini(tenant_key, license_key, gemini_key, actor)
        if not installed.get("ok"):
            return {"ok": False, "action": "license_trial", "tenant_key": tenant_key,
                    "error_code": "license_transition_failed"}
        # The generated key is intentionally returned once to this authenticated
        # dashboard request. It is never persisted by this service or browser.
        return {"ok": True, "action": "license_trial", "tenant_key": tenant_key,
                "license_key": license_key, "created": bool(created.get("created"))}


class _Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        line = self.rfile.readline(MAX_WIRE_BYTES + 1)
        response: dict[str, object]
        try:
            if not line or len(line) > MAX_WIRE_BYTES:
                raise ValueError("invalid_request")
            body = self.server.replay.verify(json.loads(line.decode("utf-8")), self.server.key)  # type: ignore[attr-defined]
            response = self.server.core.handle(body)  # type: ignore[attr-defined]
        except (ValueError, OSError) as exc:
            code = str(exc)
            response = {"ok": False, "error_code": code if SAFE_CODE.fullmatch(code) else "invalid_request"}
        except Exception:
            response = {"ok": False, "error_code": "provisioner_failure"}
        wire = _canonical(response)
        self.wfile.write((wire if len(wire) <= MAX_WIRE_BYTES else _canonical({"ok": False, "error_code": "response_too_large"})) + b"\n")


def serve(socket_path: Path, key_file: Path, base: Path, *, socket_gid: int | None = None,
          replay_state: Path = DEFAULT_REPLAY_STATE, bot_username: str = DEFAULT_BOT_USERNAME,
          license_url: str = DEFAULT_LICENSE_URL, license_key_file: Path = DEFAULT_LICENSE_KEY_FILE) -> None:
    parent = socket_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        if not stat.S_ISSOCK(socket_path.lstat().st_mode):
            raise RuntimeError("refusing_non_socket_path")
        socket_path.unlink()
    server = _Server(str(socket_path), _Handler)
    try:
        server.key = _load_key(key_file)  # type: ignore[attr-defined]
        server.replay = ReplayWindow(replay_state)  # type: ignore[attr-defined]
        server.core = ProvisionerCore(  # type: ignore[attr-defined]
            base, bot_username=bot_username, license_url=license_url, license_key_file=license_key_file,
        )
        os.chmod(socket_path, 0o660)
        if socket_gid is not None:
            os.chown(socket_path, -1, socket_gid)
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        if socket_path.exists() and stat.S_ISSOCK(socket_path.lstat().st_mode):
            socket_path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("serve",))
    parser.add_argument("--socket", type=Path, default=Path(os.environ.get("ADMIRA_PROVISIONER_SOCKET", DEFAULT_SOCKET)))
    parser.add_argument("--key-file", type=Path, default=Path(os.environ.get("ADMIRA_PROVISIONER_KEY_FILE", DEFAULT_KEY_FILE)))
    parser.add_argument("--base", type=Path, default=Path(os.environ.get("ADMIRA_TENANTS_BASE", DEFAULT_BASE)))
    parser.add_argument("--socket-gid", type=int, default=None)
    parser.add_argument("--replay-state", type=Path, default=Path(os.environ.get("ADMIRA_PROVISIONER_REPLAY_STATE", DEFAULT_REPLAY_STATE)))
    parser.add_argument("--bot-username", default=os.environ.get("ADMIRA_TELEGRAM_BOT_USERNAME", DEFAULT_BOT_USERNAME))
    parser.add_argument("--license-url", default=os.environ.get("ADMIRA_LICENSE_API_URL", DEFAULT_LICENSE_URL))
    parser.add_argument("--license-key-file", type=Path,
                        default=Path(os.environ.get("ADMIRA_LICENSE_BRIDGE_KEY_FILE", DEFAULT_LICENSE_KEY_FILE)))
    args = parser.parse_args(argv)
    serve(args.socket, args.key_file, args.base, socket_gid=args.socket_gid, replay_state=args.replay_state,
          bot_username=args.bot_username, license_url=args.license_url, license_key_file=args.license_key_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
