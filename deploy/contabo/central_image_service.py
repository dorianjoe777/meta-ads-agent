#!/usr/bin/env python3
"""Fail-closed Unix-socket service for centrally sponsored images.

The service is intentionally small: authentication, tenant entitlement and
artifact validation remain in :mod:`image_broker`; this process only exposes
that contract over a local, permissioned socket.  It never persists prompts or
provider responses.  It is not enabled by the default Compose profile.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import stat
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

try:  # service is copied beside image_broker.py in the container
    from image_broker import ImageBroker
except ImportError:  # package imports used by tests
    from deploy.contabo.image_broker import ImageBroker


MAX_LINE = 128 * 1024
DEFAULT_SOCKET = "/run/admira-central-image-broker/broker.sock"
DEFAULT_TENANTS_ROOT = "/srv/admira/shared/central-image-exchange"
DEFAULT_KEY_ROOT = "/etc/admira/central-image-keys"
DEFAULT_DB_USER = "admira_image_login"


class EntitlementStore:
    """Resolve the durable lifecycle route without retaining request content."""

    def __init__(self, query: Callable[[str], str]):
        self._query = query

    def __call__(self, tenant_id: str, purpose: str) -> str:
        if purpose != "image_generation":
            return "blocked"
        try:
            return str(self._query(tenant_id))
        except Exception:
            return "blocked"


class PostgresCentralImageLedger:
    """Per-operation adapter for durable image-job functions."""

    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def begin(self, runtime_key: str, request_id: str) -> dict[str, Any]:
        row = self._call(
            "SELECT * FROM admira.begin_central_image_job_for_runtime(%s, %s)",
            (runtime_key, uuid.UUID(request_id)),
        )
        return {
            "route": str(row.get("route") or "blocked"),
            "status": str(row.get("status") or ""),
            "job_id": row.get("job_id"),
            # A live lease belonging to another request is deliberately NULL
            # in the SQL response, so it cannot be stolen by a retry.
            "lease_token": row.get("lease_token"),
            "result": {
                "output_ref": row.get("output_ref"),
                "sha256": row.get("output_sha256"),
                "size": row.get("output_size_bytes"),
            },
            "error_code": row.get("error_code"),
        }

    def complete(self, job_id: Any, lease_token: Any, result: Mapping[str, Any]) -> bool:
        suffix = str(result["output_ref"]).rsplit(".", 1)[-1]
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(suffix)
        if mime is None:
            return False
        row = self._call(
            "SELECT admira.complete_central_image_job(%s, %s, %s, %s, %s, %s) AS completed",
            (job_id, lease_token, result["output_ref"], result["sha256"], int(result["size"]), mime),
        )
        return row.get("completed") is True

    def fail(self, job_id: Any, lease_token: Any, error_code: str) -> None:
        safe = {
            "provider_failed", "provider_unavailable", "provider_timeout",
            "output_invalid", "output_too_large", "lease_expired", "internal_error",
        }
        self._call(
            "SELECT * FROM admira.fail_central_image_job(%s, %s, %s)",
            (job_id, lease_token, error_code if error_code in safe else "internal_error"),
        )

    def _call(self, sql: str, params: tuple[Any, ...]) -> dict[str, Any]:
        connection = self._connect()
        try:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(sql, params)
                    row = cursor.fetchone() if cursor.description else None
                    if row is None:
                        return {}
                    if isinstance(row, Mapping):
                        return dict(row)
                    return dict(zip([item.name for item in cursor.description], row))
        finally:
            connection.close()


def _private_password(path: str | Path) -> str:
    target = Path(path)
    details = target.lstat()
    # Docker Compose secrets may be mounted 0444 inside the isolated service;
    # reject writes and links, while permitting those read-only mount modes.
    if target.is_symlink() or not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) & 0o022:
        raise RuntimeError("database_password_file_invalid")
    value = target.read_text(encoding="utf-8").strip()
    if len(value) < 32:
        raise RuntimeError("database_password_missing")
    return value


def postgres_connect_factory_from_env() -> Callable[[], Any]:
    """Build fresh psycopg connections from ADMIRA_DB_* only."""
    import psycopg
    host = os.environ.get("ADMIRA_DB_HOST", "postgres")
    port = int(os.environ.get("ADMIRA_DB_PORT", "5432"))
    dbname = os.environ.get("ADMIRA_DB_NAME", "admira_control")
    user = os.environ.get("ADMIRA_DB_USER", DEFAULT_DB_USER)
    password_file = os.environ.get("ADMIRA_DB_PASSWORD_FILE")
    if not password_file:
        raise RuntimeError("database_password_file_missing")
    password = _private_password(password_file)

    def connect() -> Any:
        return psycopg.connect(host=host, port=port, dbname=dbname, user=user,
                               password=password, connect_timeout=10,
                               application_name="admira-central-image")
    return connect


def central_codex_provider(body: Mapping[str, Any], workdir: Path) -> Path | str:
    """Generate with the central r91 ChatGPT/Codex auth and return its file.

    This function is only loaded by the explicitly enabled central service;
    tenant credentials are not read.  ``call_codex_image_cli_direct`` writes
    the result into the broker-owned temporary work directory.
    """
    try:
        from codex_brand_guides import call_codex_image_cli_direct
    except ImportError as exc:
        raise RuntimeError("provider_unavailable") from exc
    references = [str(item) for item in body.get("references", []) if isinstance(item, str)]
    result = call_codex_image_cli_direct(
        str(body.get("prompt") or ""),
        timeout=270,
        output_root=workdir,
        output_name="central",
        reference_image_paths=references,
        purpose="ad_creative",
    )
    if not isinstance(result, Mapping) or not result.get("ok"):
        raise RuntimeError("provider_failed")
    output = result.get("image_path") or result.get("path")
    if not output:
        raise RuntimeError("provider_failed")
    return Path(str(output))


class CentralImageServer:
    def __init__(self, broker: ImageBroker, socket_path: Path = Path(DEFAULT_SOCKET), *,
                 backlog: int = 16, max_clients: int = 32):
        self.broker = broker
        self.socket_path = Path(socket_path)
        self.backlog = max(1, min(128, int(backlog)))
        self.max_clients = max(1, min(256, int(max_clients)))
        self.stop_event = threading.Event()
        self._listener: socket.socket | None = None
        self._threads: set[threading.Thread] = set()
        self._lock = threading.Lock()
        self._client_slots = threading.BoundedSemaphore(self.max_clients)

    def _bind(self) -> socket.socket:
        self.socket_path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        parent_details = self.socket_path.parent.lstat()
        if self.socket_path.parent.is_symlink() or not stat.S_ISDIR(parent_details.st_mode):
            raise RuntimeError("socket_parent_invalid")
        os.chmod(self.socket_path.parent, 0o750)
        if self.socket_path.exists() or self.socket_path.is_symlink():
            details = self.socket_path.lstat()
            if not stat.S_ISSOCK(details.st_mode):
                raise RuntimeError("socket_path_not_socket")
            # Do not unlink a live listener: that would permit two instances
            # to run while the original still owns the inode.
            try:
                probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                probe.settimeout(0.2)
                probe.connect(str(self.socket_path))
            except OSError:
                pass
            else:
                probe.close()
                raise RuntimeError("socket_already_running")
            try:
                probe.close()
            except UnboundLocalError:
                pass
            self.socket_path.unlink()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(self.socket_path))
            os.chmod(self.socket_path, 0o660)
            listener.listen(self.backlog)
            listener.settimeout(0.5)
            return listener
        except Exception:
            listener.close()
            try:
                self.socket_path.unlink()
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def _safe_response(result: object) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {"ok": False, "error_code": "internal_error"}
        if result.get("ok") is True:
            allowed = {"ok", "tenant_id", "request_id", "output_ref", "size", "sha256"}
            return {key: result[key] for key in allowed if key in result}
        code = str(result.get("error_code") or "internal_error")
        safe = {"invalid_request", "invalid_signature", "expired_request", "replayed_request",
                "entitlement_blocked", "personal_provider_required", "tenant_busy",
                "reference_invalid", "provider_failed", "output_invalid", "output_too_large",
                "tenant_not_found", "internal_error"}
        return {"ok": False, "error_code": code if code in safe else "internal_error"}

    def _handle(self, connection: socket.socket) -> None:
        try:
            connection.settimeout(10)
            data = bytearray()
            while len(data) <= MAX_LINE:
                chunk = connection.recv(min(8192, MAX_LINE + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if b"\n" in chunk:
                    break
            if len(data) > MAX_LINE or b"\n" not in data:
                response = {"ok": False, "error_code": "invalid_request"}
            else:
                line = bytes(data).split(b"\n", 1)[0]
                try:
                    request = json.loads(line.decode("utf-8"))
                    response = self._safe_response(self.broker.submit(request))
                except Exception:
                    response = {"ok": False, "error_code": "invalid_request"}
            connection.sendall(json.dumps(response, separators=(",", ":")).encode() + b"\n")
        except Exception:
            pass
        finally:
            connection.close()

    def serve_forever(self) -> None:
        self._listener = self._bind()
        try:
            while not self.stop_event.is_set():
                try:
                    connection, _ = self._listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self.stop_event.is_set():
                        break
                    raise
                if not self._client_slots.acquire(blocking=False):
                    try:
                        connection.settimeout(1)
                        connection.sendall(b'{"ok":false,"error_code":"tenant_busy"}\n')
                    except OSError:
                        pass
                    finally:
                        connection.close()
                    continue
                thread = threading.Thread(target=self._run_client, args=(connection,), daemon=True)
                with self._lock:
                    self._threads.add(thread)
                try:
                    thread.start()
                except Exception:
                    with self._lock:
                        self._threads.discard(thread)
                    self._client_slots.release()
                    connection.close()
                    raise
        finally:
            self.close()

    def _run_client(self, connection: socket.socket) -> None:
        current = threading.current_thread()
        try:
            self._handle(connection)
        finally:
            with self._lock:
                self._threads.discard(current)
            self._client_slots.release()

    def close(self) -> None:
        self.stop_event.set()
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        try:
            if self.socket_path.is_socket():
                self.socket_path.unlink()
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default=os.environ.get("ADMIRA_CENTRAL_IMAGE_SOCKET", DEFAULT_SOCKET))
    parser.add_argument("--tenants-root", default=os.environ.get("ADMIRA_CENTRAL_IMAGE_EXCHANGE_ROOT", DEFAULT_TENANTS_ROOT))
    parser.add_argument("--key-root", default=os.environ.get("ADMIRA_CENTRAL_IMAGE_KEY_ROOT", DEFAULT_KEY_ROOT))
    args = parser.parse_args(argv)
    connect = postgres_connect_factory_from_env()
    ledger = PostgresCentralImageLedger(connect)
    broker = ImageBroker(Path(args.tenants_root), Path(args.key_root), central_codex_provider,
                         lambda tenant, purpose: "central_sponsored",
                         max_global=int(os.environ.get("ADMIRA_CENTRAL_IMAGE_MAX_GLOBAL", "2")),
                         ledger=ledger)
    server = CentralImageServer(
        broker,
        Path(args.socket),
        max_clients=int(os.environ.get("ADMIRA_CENTRAL_IMAGE_MAX_CLIENTS", "32")),
    )
    signal.signal(signal.SIGTERM, lambda *_: server.close())
    signal.signal(signal.SIGINT, lambda *_: server.close())
    try:
        server.serve_forever()
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
