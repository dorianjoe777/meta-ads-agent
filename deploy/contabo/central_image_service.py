#!/usr/bin/env python3
"""Fail-closed Unix-socket service for centrally sponsored Codex work.

The service is intentionally small: authentication, tenant entitlement and
artifact validation remain in :mod:`image_broker`; this process only exposes
that contract over a local, permissioned socket.  It never persists prompts or
provider responses.  It is not enabled by the default Compose profile.
"""

from __future__ import annotations

import argparse
from functools import partial
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
    from image_broker import ImageBroker, _private_key
except ImportError:  # package imports used by tests
    from deploy.contabo.image_broker import ImageBroker, _private_key

try:  # service is copied beside central_codex_account_pool.py in the container
    from central_codex_account_pool import CentralCodexAccountPool
except ImportError:  # package imports used by tests
    from deploy.contabo.central_codex_account_pool import CentralCodexAccountPool

try:  # service is copied beside campaign_compiler_broker.py in the container
    from campaign_compiler_broker import (
        CampaignCompilerBroker,
        MAX_PROVIDER_TIMEOUT_SECONDS,
        MODEL as CENTRAL_COMPILER_MODEL,
    )
except ImportError:  # package imports used by tests
    from deploy.contabo.campaign_compiler_broker import (
        CampaignCompilerBroker,
        MAX_PROVIDER_TIMEOUT_SECONDS,
        MODEL as CENTRAL_COMPILER_MODEL,
    )

try:  # service is copied beside central_conversation_broker.py in the container
    from central_conversation_broker import (
        ConversationBroker,
        MAX_PROVIDER_TIMEOUT_SECONDS as MAX_CONVERSATION_TIMEOUT_SECONDS,
        MODEL as CENTRAL_CONVERSATION_MODEL,
        SAFE_ERRORS as CONVERSATION_SAFE_ERRORS,
    )
except ImportError:  # package imports used by tests
    from deploy.contabo.central_conversation_broker import (
        ConversationBroker,
        MAX_PROVIDER_TIMEOUT_SECONDS as MAX_CONVERSATION_TIMEOUT_SECONDS,
        MODEL as CENTRAL_CONVERSATION_MODEL,
        SAFE_ERRORS as CONVERSATION_SAFE_ERRORS,
    )


MAX_LINE = 128 * 1024
DEFAULT_SOCKET = "/run/admira-central-image-broker/broker.sock"
DEFAULT_COMPILER_SOCKET = "/run/admira-central-image-broker/compiler.sock"
DEFAULT_CONVERSATION_SOCKET = "/run/admira-central-image-broker/conversation.sock"
DEFAULT_TENANTS_ROOT = "/srv/admira/shared/central-image-exchange"
DEFAULT_KEY_ROOT = "/etc/admira/central-image-keys"
DEFAULT_DB_USER = "admira_image_login"
DEFAULT_CODEX_AUTH_ROOT = "/app/runtime/hermes/codex-auth-pool"
DEFAULT_CODEX_ACCOUNT_IDS = "primary,secondary"
COMPILER_RESPONSE_LIMIT = MAX_LINE - 2048
CONVERSATION_RESPONSE_LIMIT = 320 * 1024
CONVERSATION_MAX_LINE = 1024 * 1024


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


class PostgresCentralCampaignCompilerEntitlement:
    """Resolve one central compiler entitlement without retaining request text.

    The tenant client presents a runtime key rather than a database tenant ID.
    PostgreSQL resolves it again at this trust boundary, so an entitlement file
    in a tenant never grants access on its own.
    """

    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def __call__(self, runtime_key: str, purpose: str) -> str:
        if purpose != "campaign_compile":
            return "blocked"
        try:
            connection = self._connect()
            try:
                with connection.transaction():
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT * FROM admira.resolve_central_campaign_compiler_access_for_runtime(%s)",
                            (runtime_key,),
                        )
                        row = cursor.fetchone() if cursor.description else None
                        if row is None:
                            return "blocked"
                        values = dict(row) if isinstance(row, Mapping) else dict(
                            zip([item.name for item in cursor.description], row)
                        )
                        return "central_sponsored" if values.get("route") == "central_sponsored" else "blocked"
            finally:
                connection.close()
        except Exception:
            # Keep database/provider diagnostics on the service boundary. A
            # tenant gets only the stable entitlement-blocked outcome.
            return "blocked"


class PostgresCentralConversationEntitlement:
    """Recheck central-pool eligibility for a live fallback request.

    The durable lifecycle function already represents both trial sponsorship
    and the licensed-pool dashboard switch.  Reusing it at this independent
    trust boundary means a tenant-side access file can never grant OAuth
    access after the operator has disabled that switch.
    """

    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def __call__(self, runtime_key: str, purpose: str) -> str:
        if purpose != "conversation_inference":
            return "blocked"
        try:
            connection = self._connect()
            try:
                with connection.transaction():
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT * FROM admira.resolve_central_campaign_compiler_access_for_runtime(%s)",
                            (runtime_key,),
                        )
                        row = cursor.fetchone() if cursor.description else None
                        if row is None:
                            return "blocked"
                        values = dict(row) if isinstance(row, Mapping) else dict(
                            zip([item.name for item in cursor.description], row)
                        )
                        return "central_sponsored" if values.get("route") == "central_sponsored" else "blocked"
            finally:
                connection.close()
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


def central_codex_account_pool_from_env(*, compiler_provider: Callable[..., object] | None = None,
                                        conversation_provider: Callable[..., object] | None = None) -> CentralCodexAccountPool:
    """Build the central account pool once, failing closed on unsafe homes."""
    root = Path(os.environ.get("ADMIRA_CENTRAL_CODEX_AUTH_ROOT", DEFAULT_CODEX_AUTH_ROOT))
    if not root.is_absolute():
        raise RuntimeError("central_codex_pool_invalid")
    try:
        details = root.lstat()
    except OSError as exc:
        raise RuntimeError("central_codex_pool_invalid") from exc
    if root.is_symlink() or not stat.S_ISDIR(details.st_mode) or stat.S_IMODE(details.st_mode) & 0o077:
        raise RuntimeError("central_codex_pool_invalid")
    account_ids = os.environ.get("ADMIRA_CENTRAL_CODEX_ACCOUNT_IDS", DEFAULT_CODEX_ACCOUNT_IDS).split(",")
    accounts = [{"id": account_id, "codex_home": str(root / account_id)} for account_id in account_ids]
    try:
        return CentralCodexAccountPool(
            accounts,
            compiler_provider=compiler_provider,
            conversation_provider=conversation_provider,
        )
    except Exception as exc:
        # Configuration details are deliberately not copied into service or
        # tenant responses. The activation preflight reports the exact slot.
        raise RuntimeError("central_codex_pool_invalid") from exc


def central_codex_provider(body: Mapping[str, Any], workdir: Path, *,
                           pool: CentralCodexAccountPool | None = None) -> Path | str:
    """Generate through the isolated central account pool and return its file.

    This function is only loaded by the explicitly enabled central service;
    tenant credentials are not read. The pool writes the result into the
    broker-owned temporary work directory and tries each account at most once.
    """
    selected_pool = pool or central_codex_account_pool_from_env()
    references = [str(item) for item in body.get("references", []) if isinstance(item, str)]
    result = selected_pool.generate(
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


def _compiler_failure_category(result: object) -> str:
    """Reduce a local Codex result before it reaches the shared pool."""
    if not isinstance(result, Mapping):
        return "provider_failed"
    reported = str(result.get("failure_category") or "").strip().lower()
    if reported == "provider_limited":
        return "codex_usage_limit"
    if reported in {"provider_auth", "provider_timeout", "provider_unavailable", "provider_failed"}:
        return reported
    detail = " ".join(
        str(result.get(key) or "")
        for key in ("reason", "error", "diagnostic", "error_type")
    ).lower()
    if "timeout" in detail:
        return "provider_timeout"
    if any(token in detail for token in ("auth", "not logged", "unauthorized", "missing bearer")):
        return "provider_auth"
    if any(token in detail for token in ("usage limit", "rate limit", "quota", "limit reached")):
        return "codex_usage_limit"
    if "unavailable" in detail or "connection" in detail:
        return "provider_unavailable"
    return "provider_failed"


def central_codex_campaign_compiler_provider(
    prompt: str,
    schema: Mapping[str, Any],
    *,
    codex_home: Path,
    timeout: int,
    model: str,
) -> dict[str, Any]:
    """Run Terra through the slot's Hermes/Codex OAuth session.

    The private slot remains in the central broker and the tenant never sees
    its credential.  Unlike the legacy deployment path this does not spawn
    ``codex exec``: Hermes' Responses transport speaks directly to the
    already-authorized Codex OAuth session.
    """
    try:
        from codex_oauth_compiler import compile_with_codex_oauth
        result = compile_with_codex_oauth(
            prompt,
            schema,
            timeout=max(1, min(int(timeout), 300)),
            model=model,
            hermes_home=codex_home,
        )
    except Exception:
        return {"ok": False, "failure_category": "provider_failed"}
    compiled = result.get("compiled") if isinstance(result, Mapping) else None
    if isinstance(result, Mapping) and result.get("ok") is True and isinstance(compiled, Mapping):
        return {"ok": True, "compiled": dict(compiled)}
    return {"ok": False, "failure_category": _compiler_failure_category(result)}


def central_codex_conversation_provider(
    messages: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    *,
    tools: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    tool_choice: object,
    codex_home: Path,
    timeout: int,
    model: str,
) -> dict[str, Any]:
    """Run one Terra turn through a central slot's Hermes OAuth transport."""
    try:
        from codex_oauth_chat import chat_with_codex_oauth
        result = chat_with_codex_oauth(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            timeout=max(1, min(int(timeout), MAX_CONVERSATION_TIMEOUT_SECONDS)),
            model=model,
            hermes_home=codex_home,
        )
    except Exception:
        return {"ok": False, "failure_category": "provider_failed"}
    message = result.get("message") if isinstance(result, Mapping) else None
    if isinstance(result, Mapping) and result.get("ok") is True and isinstance(message, Mapping):
        return {
            "ok": True,
            "message": dict(message),
            "finish_reason": str(result.get("finish_reason") or "stop"),
        }
    return {"ok": False, "failure_category": _compiler_failure_category(result)}


def central_campaign_compiler_schema(tool: str) -> Mapping[str, Any]:
    """Select the output schema on the central side, not from a tenant."""
    from campaign_payload_compiler import compiler_output_schema
    schema = compiler_output_schema(tool)
    if not isinstance(schema, Mapping):
        raise ValueError("schema_failed")
    return schema


def central_campaign_compiler_provider(
    request: Mapping[str, Any], schema: Mapping[str, Any], *, pool: CentralCodexAccountPool
) -> Mapping[str, Any]:
    """Use the same slots/locks/cooldowns as central image generation."""
    requested_timeout = request.get("timeout_seconds", MAX_PROVIDER_TIMEOUT_SECONDS)
    if isinstance(requested_timeout, bool) or not isinstance(requested_timeout, int):
        raise RuntimeError("provider_failed")
    result = pool.compile(
        str(request.get("prompt") or ""),
        schema,
        timeout=max(1, min(requested_timeout, MAX_PROVIDER_TIMEOUT_SECONDS)),
    )
    compiled = result.get("compiled") if isinstance(result, Mapping) else None
    if not isinstance(result, Mapping) or result.get("ok") is not True or not isinstance(compiled, Mapping):
        # The broker deliberately maps this to one stable provider code. Do
        # not let account IDs, CLI diagnostics, or raw provider categories
        # cross the Unix-socket boundary.
        raise RuntimeError("provider_failed")
    return dict(compiled)


def central_conversation_provider(
    messages: list[Mapping[str, Any]], *, tools: list[Mapping[str, Any]],
    tool_choice: object, timeout: int, pool: CentralCodexAccountPool,
) -> Mapping[str, Any]:
    """Use the same two isolated OAuth slots for the final text fallback."""
    result = pool.chat(
        messages,
        tools=tools,
        tool_choice=tool_choice,
        timeout=max(1, min(int(timeout), MAX_CONVERSATION_TIMEOUT_SECONDS)),
    )
    message = result.get("message") if isinstance(result, Mapping) else None
    if not isinstance(result, Mapping) or result.get("ok") is not True or not isinstance(message, Mapping):
        raise RuntimeError("provider_failed")
    return {
        "ok": True,
        "message": dict(message),
        "finish_reason": str(result.get("finish_reason") or "stop"),
    }


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
        self.max_line = MAX_LINE

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
            while len(data) <= self.max_line:
                chunk = connection.recv(min(8192, self.max_line + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if b"\n" in chunk:
                    break
            if len(data) > self.max_line or b"\n" not in data:
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

    def bind(self) -> socket.socket:
        if self._listener is None:
            self._listener = self._bind()
        return self._listener

    def serve_forever(self) -> None:
        self.bind()
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


class CentralCampaignCompilerServer(CentralImageServer):
    """Serve only the small structured campaign-compiler protocol."""

    @staticmethod
    def _safe_response(result: object) -> dict[str, Any]:
        if not isinstance(result, Mapping):
            return {"ok": False, "error_code": "internal_error"}
        if result.get("ok") is True:
            tenant_id = result.get("tenant_id")
            request_id = result.get("request_id")
            model = result.get("model")
            compiled = result.get("compiled")
            if not all(isinstance(item, str) and item for item in (tenant_id, request_id, model)) \
                    or model != CENTRAL_COMPILER_MODEL \
                    or not isinstance(compiled, Mapping):
                return {"ok": False, "error_code": "compiled_invalid"}
            response = {
                "ok": True,
                "tenant_id": tenant_id,
                "request_id": request_id,
                "model": model,
                "compiled": dict(compiled),
            }
            try:
                encoded = json.dumps(response, separators=(",", ":")).encode()
            except (TypeError, ValueError):
                return {"ok": False, "error_code": "compiled_invalid"}
            if len(encoded) > COMPILER_RESPONSE_LIMIT:
                return {"ok": False, "error_code": "response_too_large"}
            return response
        code = str(result.get("error_code") or "internal_error")
        safe = {
            "invalid_request", "invalid_signature", "expired_request", "replayed_request",
            "entitlement_blocked", "tool_not_allowed", "tenant_busy", "global_busy",
            "schema_failed", "provider_failed", "compiled_invalid", "response_too_large",
            "tenant_not_found", "internal_error",
        }
        return {"ok": False, "error_code": code if code in safe else "internal_error"}


class CentralConversationServer(CentralImageServer):
    """Serve normalized text/tool responses from central Terra only."""

    def __init__(self, broker: ConversationBroker, socket_path: Path, **kwargs: Any):
        super().__init__(broker, socket_path, **kwargs)
        self.max_line = CONVERSATION_MAX_LINE

    @staticmethod
    def _safe_response(result: object) -> dict[str, Any]:
        if not isinstance(result, Mapping):
            return {"ok": False, "error_code": "internal_error"}
        if result.get("ok") is True:
            tenant_id = result.get("tenant_id")
            request_id = result.get("request_id")
            model = result.get("model")
            message = result.get("message")
            finish_reason = result.get("finish_reason")
            if (not all(isinstance(item, str) and item for item in (tenant_id, request_id, model, finish_reason))
                    or model != CENTRAL_CONVERSATION_MODEL or finish_reason not in {"stop", "tool_calls"}
                    or not isinstance(message, Mapping)):
                return {"ok": False, "error_code": "response_invalid"}
            response = {
                "ok": True,
                "tenant_id": tenant_id,
                "request_id": request_id,
                "model": model,
                "finish_reason": finish_reason,
                "message": dict(message),
            }
            try:
                if len(json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode()) > CONVERSATION_RESPONSE_LIMIT:
                    return {"ok": False, "error_code": "response_too_large"}
            except (TypeError, ValueError):
                return {"ok": False, "error_code": "response_invalid"}
            return response
        code = str(result.get("error_code") or "internal_error")
        return {"ok": False, "error_code": code if code in CONVERSATION_SAFE_ERRORS else "internal_error"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default=os.environ.get("ADMIRA_CENTRAL_IMAGE_SOCKET", DEFAULT_SOCKET))
    parser.add_argument(
        "--compiler-socket",
        default=os.environ.get("ADMIRA_CENTRAL_CAMPAIGN_COMPILER_SOCKET", DEFAULT_COMPILER_SOCKET),
    )
    parser.add_argument(
        "--conversation-socket",
        default=os.environ.get("ADMIRA_CENTRAL_CONVERSATION_SOCKET", DEFAULT_CONVERSATION_SOCKET),
    )
    parser.add_argument("--tenants-root", default=os.environ.get("ADMIRA_CENTRAL_IMAGE_EXCHANGE_ROOT", DEFAULT_TENANTS_ROOT))
    parser.add_argument("--key-root", default=os.environ.get("ADMIRA_CENTRAL_IMAGE_KEY_ROOT", DEFAULT_KEY_ROOT))
    args = parser.parse_args(argv)
    connect = postgres_connect_factory_from_env()
    ledger = PostgresCentralImageLedger(connect)
    account_pool = central_codex_account_pool_from_env(
        compiler_provider=central_codex_campaign_compiler_provider,
        conversation_provider=central_codex_conversation_provider,
    )
    provider = partial(central_codex_provider, pool=account_pool)
    max_global = min(
        int(os.environ.get("ADMIRA_CENTRAL_IMAGE_MAX_GLOBAL", "2")),
        len(account_pool.accounts),
    )
    broker = ImageBroker(Path(args.tenants_root), Path(args.key_root), provider,
                         lambda tenant, purpose: "central_sponsored",
                         max_global=max_global,
                         ledger=ledger)
    server = CentralImageServer(
        broker,
        Path(args.socket),
        max_clients=int(os.environ.get("ADMIRA_CENTRAL_IMAGE_MAX_CLIENTS", "32")),
    )
    compiler_broker = CampaignCompilerBroker(
        lambda tenant: _private_key(Path(args.key_root), tenant),
        central_campaign_compiler_schema,
        PostgresCentralCampaignCompilerEntitlement(connect),
        partial(central_campaign_compiler_provider, pool=account_pool),
        max_global=max_global,
        max_response_bytes=COMPILER_RESPONSE_LIMIT,
    )
    compiler_server = CentralCampaignCompilerServer(
        compiler_broker,
        Path(args.compiler_socket),
        max_clients=int(os.environ.get("ADMIRA_CENTRAL_COMPILER_MAX_CLIENTS", "16")),
    )
    conversation_broker = ConversationBroker(
        lambda tenant: _private_key(Path(args.key_root), tenant),
        PostgresCentralConversationEntitlement(connect),
        partial(central_conversation_provider, pool=account_pool),
        max_global=max_global,
    )
    conversation_server = CentralConversationServer(
        conversation_broker,
        Path(args.conversation_socket),
        max_clients=int(os.environ.get("ADMIRA_CENTRAL_CONVERSATION_MAX_CLIENTS", "16")),
    )

    # Bind both listeners before exposing either. A partial activation would
    # make an entitled tenant fall back to a local credential that it must not
    # possess, so a socket failure stops the central service as a whole.
    compiler_server.bind()
    conversation_server.bind()
    server.bind()
    auxiliary_failed = threading.Event()

    def serve_compiler() -> None:
        try:
            compiler_server.serve_forever()
        except Exception:
            auxiliary_failed.set()
            conversation_server.close()
            server.close()

    def serve_conversation() -> None:
        try:
            conversation_server.serve_forever()
        except Exception:
            auxiliary_failed.set()
            compiler_server.close()
            server.close()

    compiler_thread = threading.Thread(
        target=serve_compiler,
        name="admira-central-campaign-compiler",
        daemon=True,
    )
    compiler_thread.start()
    conversation_thread = threading.Thread(
        target=serve_conversation,
        name="admira-central-conversation",
        daemon=True,
    )
    conversation_thread.start()

    def close_servers(*_args: object) -> None:
        compiler_server.close()
        conversation_server.close()
        server.close()

    signal.signal(signal.SIGTERM, close_servers)
    signal.signal(signal.SIGINT, close_servers)
    try:
        server.serve_forever()
    finally:
        close_servers()
        compiler_thread.join(timeout=5)
        conversation_thread.join(timeout=5)
    return 1 if auxiliary_failed.is_set() else 0


if __name__ == "__main__":
    raise SystemExit(main())
