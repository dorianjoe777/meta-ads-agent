#!/usr/bin/env python3
"""Small, provider-neutral broker for centrally sponsored tenant images.

This module deliberately has no network/provider implementation.  A caller
authenticates a tenant request, the injected provider writes/returns one image,
and the broker validates and atomically places that image in that tenant's
output directory.  The optional injected ledger fences provider work and makes
completed request IDs durable across process restarts.  Without that adapter,
idempotency and queues remain process-local for isolated tests/canaries only.
The Contabo deployment still keeps the service disabled until its r91 canary.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import tempfile
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Callable, Mapping


TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")
REQUEST_RE = re.compile(r"^[A-Za-z0-9_-]{8,96}$")
NONCE_RE = re.compile(r"^[a-f0-9]{32,128}$")
MAX_PROMPT = 10_000
MAX_REFERENCES = 8
MAX_REFERENCE_BYTES = 50 * 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024
ALLOWED_PURPOSES = {"image_generation"}
ALLOWED_ASPECTS = {"square", "portrait", "landscape", "wide"}
SAFE_ERRORS = {
    "invalid_request", "invalid_signature", "expired_request", "replayed_request",
    "entitlement_blocked", "personal_provider_required", "tenant_busy",
    "reference_invalid", "provider_failed", "output_invalid", "output_too_large",
    "tenant_not_found", "internal_error",
}
SAFE_PROVIDER_FAILURE_CATEGORIES = frozenset({
    "codex_usage_limit", "chatgpt_images_limit", "provider_limited",
    "provider_auth", "provider_timeout", "provider_unavailable", "provider_failed",
})


class SafeProviderFailure(RuntimeError):
    """Provider failure carrying only a bounded, non-sensitive category."""

    def __init__(self, failure_category: object = "provider_failed"):
        category = str(failure_category or "provider_failed").strip().lower()
        if category not in SAFE_PROVIDER_FAILURE_CATEGORIES:
            category = "provider_failed"
        super().__init__("provider_failed")
        self.failure_category = category


def validate_tenant_id(value: object) -> str:
    text = str(value or "")
    if not TENANT_RE.fullmatch(text):
        raise ValueError("invalid_request")
    return text


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sign_request(key: bytes, body: Mapping[str, Any], *, timestamp: int | None = None,
                 nonce: str | None = None) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "timestamp": int(time.time() if timestamp is None else timestamp),
        "nonce": nonce or secrets.token_hex(16),
        "body": dict(body),
    }
    envelope["signature"] = hmac.new(key, _canonical(envelope), hashlib.sha256).hexdigest()
    return envelope


def _private_key(root: Path, tenant_id: str) -> bytes:
    try:
        root_details = root.lstat()
        if root.is_symlink() or not stat.S_ISDIR(root_details.st_mode) or stat.S_IMODE(root_details.st_mode) & 0o022:
            raise OSError
        path = root / tenant_id
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            details = os.fstat(fd)
            if (not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) & 0o077
                    or details.st_size < 32 or details.st_size > 512):
                raise OSError
            key = os.read(fd, 513).strip()
        finally:
            os.close(fd)
    except OSError as exc:
        raise ValueError("tenant_not_found") from exc
    if len(key) < 32 or len(key) > 512:
        raise ValueError("tenant_not_found")
    return key


def _magic(data: bytes) -> bool:
    return (
        data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith(b"\xff\xd8\xff")
        or (data.startswith(b"RIFF") and data[8:12] == b"WEBP")
    )


def _extension(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    return ".webp"


def _open_output_reference(output: Path, relative: Path) -> int:
    """Open one tenant output ref without following any path symlink.

    The tenant root and output directory are opened from a stable descriptor
    chain.  This matters because a path that was safe during validation can
    otherwise be replaced by a tenant process before the provider reads it.
    """
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_flags = flags | getattr(os, "O_DIRECTORY", 0)
    fds: list[int] = []
    try:
        # Open the known tenant hierarchy component-by-component.  In
        # particular, do not let a replaced tenant directory turn this into
        # an escape through a symlink in the parent path.
        current = os.open(output.parent.parent, directory_flags)
        fds.append(current)
        for part in (output.parent.name, output.name):
            child = os.open(part, directory_flags, dir_fd=current)
            fds.append(child)
            os.close(current)
            fds.pop(-2)
            current = child
        for index, part in enumerate(relative.parts):
            is_last = index == len(relative.parts) - 1
            next_flags = flags if is_last else directory_flags
            child = os.open(part, next_flags, dir_fd=current)
            fds.append(child)
            os.close(current)
            fds.pop(-2)
            current = child
        return current
    except OSError:
        for fd in reversed(fds):
            try:
                os.close(fd)
            except OSError:
                pass
        raise


def _snapshot_references(output: Path, refs: list[Path], work: Path) -> list[str]:
    """Copy refs through no-follow descriptors into private provider inputs."""
    snapshot_dir = work / "references"
    snapshot_dir.mkdir(mode=0o700)
    snapshots: list[str] = []
    total = 0
    for index, relative in enumerate(refs):
        try:
            fd = _open_output_reference(output, relative)
        except OSError as exc:
            # A tenant may replace the validated entry before this descriptor
            # walk.  Treat that race like any other invalid reference; never
            # leak host filesystem details through a provider/internal error.
            raise ValueError("reference_invalid") from exc
        try:
            details = os.fstat(fd)
            if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_REFERENCE_BYTES:
                raise ValueError("reference_invalid")
            total += details.st_size
            if total > MAX_REFERENCE_BYTES:
                raise ValueError("reference_invalid")
            name = f"{index:02d}-{relative.name}"
            target = snapshot_dir / name
            out_fd = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                remaining = details.st_size
                with os.fdopen(out_fd, "wb") as handle:
                    out_fd = -1
                    while remaining:
                        chunk = os.read(fd, min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError("reference_invalid")
                        handle.write(chunk)
                        remaining -= len(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
                after = os.fstat(fd)
                if after.st_size != details.st_size:
                    raise ValueError("reference_invalid")
            finally:
                if out_fd >= 0:
                    os.close(out_fd)
            os.chmod(target, 0o600)
            snapshots.append(str(target))
        finally:
            os.close(fd)
    return snapshots


Provider = Callable[[Mapping[str, Any], Path], bytes | bytearray | memoryview | str | Path]


def _ledger_result(output: Path, tenant_id: str, request_id: str, result: Mapping[str, Any],
                   max_image_bytes: int) -> dict[str, Any] | None:
    """Revalidate a durable result before returning it after a restart."""
    ref = result.get("output_ref")
    if not isinstance(ref, str) or not re.fullmatch(r"[a-f0-9]{32,64}\.(?:png|jpe?g|webp)", ref):
        return None
    try:
        path = output / ref
        resolved = path.resolve(strict=True)
        resolved.relative_to(output.resolve(strict=True))
        details = resolved.lstat()
        if path.is_symlink() or not stat.S_ISREG(details.st_mode) or details.st_size > max_image_bytes:
            return None
        data = resolved.read_bytes()
    except (OSError, ValueError):
        return None
    digest = hashlib.sha256(data).hexdigest()
    if not _magic(data) or result.get("sha256") != digest or result.get("size") not in (None, len(data)):
        return None
    return {"ok": True, "tenant_id": tenant_id, "request_id": request_id,
            "output_ref": ref, "size": len(data), "sha256": digest}


class ImageBroker:
    def __init__(self, tenants_root: Path, key_root: Path, provider: Provider,
                 entitlement: Callable[[str, str], str], *, max_per_tenant: int = 1,
                 max_global: int = 4, freshness_seconds: int = 90,
                 max_image_bytes: int = MAX_IMAGE_BYTES, ledger: Any = None) -> None:
        self.tenants_root = Path(tenants_root)
        self.key_root = Path(key_root)
        self.provider = provider
        self.entitlement = entitlement
        if max_per_tenant < 1 or max_global < 1 or max_image_bytes < 1:
            raise ValueError("invalid_request")
        self.max_per_tenant = max_per_tenant
        self.max_global = max_global
        self.freshness_seconds = max(1, freshness_seconds)
        self.max_image_bytes = max_image_bytes
        self.ledger = ledger
        self._seen: dict[tuple[str, str], int] = {}
        self._results: dict[tuple[str, str], dict[str, Any]] = {}
        self._queues: defaultdict[str, deque[str]] = defaultdict(deque)
        # A tenant appears once in this round-robin ring while it has queued
        # work.  Dispatching one request moves that tenant to the tail, so a
        # noisy tenant cannot continuously jump ahead of another tenant.
        self._tenant_order: deque[str] = deque()
        self._active: defaultdict[str, int] = defaultdict(int)
        self._global_active = 0
        self._last_tenant: str | None = None
        self._condition = threading.Condition()

    def _authenticate(self, envelope: object, tenant_id: str, *, now: int | None = None) -> dict[str, Any]:
        if not isinstance(envelope, dict):
            raise ValueError("invalid_request")
        try:
            timestamp = int(envelope["timestamp"])
            nonce = str(envelope["nonce"])
            body = envelope["body"]
            signature = str(envelope["signature"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid_request") from exc
        current = int(time.time() if now is None else now)
        if abs(current - timestamp) > self.freshness_seconds:
            raise ValueError("expired_request")
        if not NONCE_RE.fullmatch(nonce) or not isinstance(body, dict):
            raise ValueError("invalid_request")
        if str(body.get("tenant_id") or "") != tenant_id:
            raise ValueError("invalid_signature")
        expected = hmac.new(_private_key(self.key_root, tenant_id), _canonical({"timestamp": timestamp, "nonce": nonce, "body": body}), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid_signature")
        request_id = str(body.get("request_id") or "")
        if not REQUEST_RE.fullmatch(request_id):
            raise ValueError("invalid_request")
        with self._condition:
            cutoff = current - self.freshness_seconds * 2
            self._seen = {item: seen for item, seen in self._seen.items() if seen >= cutoff}
            seen_key = (tenant_id, nonce)
            if seen_key in self._seen:
                raise ValueError("replayed_request")
            self._seen[seen_key] = current
        return body

    def _validate(self, body: Mapping[str, Any]) -> tuple[str, str, list[Path]]:
        prompt = body.get("prompt")
        purpose = str(body.get("purpose") or "")
        aspect = str(body.get("aspect") or "")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT:
            raise ValueError("invalid_request")
        if purpose not in ALLOWED_PURPOSES or aspect not in ALLOWED_ASPECTS:
            raise ValueError("invalid_request")
        tenant_id = validate_tenant_id(body.get("tenant_id"))
        output = self.tenants_root / tenant_id / "output"
        try:
            for component in (self.tenants_root, self.tenants_root / tenant_id):
                details = component.lstat()
                if component.is_symlink() or not stat.S_ISDIR(details.st_mode):
                    raise OSError
            output_details = output.lstat()
            if output.is_symlink() or not stat.S_ISDIR(output_details.st_mode):
                raise OSError
            root = output.resolve(strict=True)
        except OSError as exc:
            raise ValueError("tenant_not_found") from exc
        refs: list[Path] = []
        reference_bytes = 0
        raw_refs = body.get("references", [])
        if not isinstance(raw_refs, list) or len(raw_refs) > MAX_REFERENCES:
            raise ValueError("reference_invalid")
        for raw in raw_refs:
            try:
                if not isinstance(raw, str) or not raw or Path(raw).is_absolute():
                    raise ValueError
                candidate = Path(raw)
                if any(part in {"", ".", ".."} for part in candidate.parts):
                    raise ValueError
                # Walk every component without following symlinks.  References
                # are tenant-local relative names, never host paths.
                current = root
                for part in candidate.parts:
                    current = current / part
                    details = current.lstat()
                    if current.is_symlink():
                        raise ValueError
                if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_REFERENCE_BYTES:
                    raise ValueError
                reference_bytes += details.st_size
                if reference_bytes > MAX_REFERENCE_BYTES:
                    raise ValueError
            except (OSError, ValueError) as exc:
                raise ValueError("reference_invalid") from exc
            # Retain the validated relative name; the secure descriptor walk
            # below re-opens it immediately before provider execution.
            refs.append(candidate)
        return tenant_id, str(output), refs

    def _enter(self, tenant_id: str, request_id: str) -> None:
        with self._condition:
            queue = self._queues[tenant_id]
            was_empty = not queue
            queue.append(request_id)
            if was_empty:
                self._tenant_order.append(tenant_id)
            while (self._active[tenant_id] >= self.max_per_tenant
                   or self._global_active >= self.max_global
                   or self._next_tenant() != tenant_id
                   or not queue or queue[0] != request_id):
                self._condition.wait()
            queue.popleft()
            self._tenant_order.remove(tenant_id)
            if queue:
                self._tenant_order.append(tenant_id)
            self._active[tenant_id] += 1
            self._global_active += 1
            self._last_tenant = tenant_id
            # More global capacity may still be available for the next tenant.
            self._condition.notify_all()

    def _next_tenant(self) -> str | None:
        """Return the next round-robin tenant that is below its own limit."""
        if self._global_active >= self.max_global:
            return None
        eligible = [
            tenant_id for tenant_id in self._tenant_order
            if self._active[tenant_id] < self.max_per_tenant and self._queues[tenant_id]
        ]
        if not eligible:
            return None
        return next((tenant_id for tenant_id in eligible if tenant_id != self._last_tenant), eligible[0])

    def _leave(self, tenant_id: str) -> None:
        with self._condition:
            self._active[tenant_id] -= 1
            self._global_active -= 1
            self._condition.notify_all()

    def submit(self, envelope: object, *, now: int | None = None) -> dict[str, Any]:
        """Return only safe result codes and a tenant-local opaque output name."""
        try:
            if not isinstance(envelope, dict) or not isinstance(envelope.get("body"), dict):
                raise ValueError("invalid_request")
            raw_tenant = envelope["body"].get("tenant_id")
            tenant_id = validate_tenant_id(raw_tenant)
            body = self._authenticate(envelope, tenant_id, now=now)
            request_id = str(body["request_id"])
            cache_key = (tenant_id, request_id)
            if self.ledger is None:
                with self._condition:
                    existing = self._results.get(cache_key)
                    if existing is not None:
                        return dict(existing)
            tenant_id, output_text, refs = self._validate(body)
            if self.ledger is None:
                decision = str(self.entitlement(tenant_id, str(body["purpose"])))
                if decision == "blocked":
                    return {"ok": False, "error_code": "entitlement_blocked"}
                if decision == "personal_chatgpt":
                    return {"ok": False, "error_code": "personal_provider_required"}
                if decision != "central_sponsored":
                    return {"ok": False, "error_code": "entitlement_blocked"}
            self._enter(tenant_id, request_id)
            lease = None
            job_id = None
            final_output: Path | None = None
            try:
                if self.ledger is not None:
                    durable = self.ledger.begin(tenant_id, request_id)
                    if not isinstance(durable, Mapping):
                        return {"ok": False, "error_code": "internal_error"}
                    route = str(durable.get("route") or "blocked")
                    if route == "personal_chatgpt":
                        return {"ok": False, "error_code": "personal_provider_required"}
                    if route != "central_sponsored":
                        return {"ok": False, "error_code": "entitlement_blocked"}
                    status = str(durable.get("status") or "")
                    if status == "succeeded":
                        stored = durable.get("result")
                        stored = stored if isinstance(stored, Mapping) else durable
                        recovered = _ledger_result(Path(output_text), tenant_id, request_id,
                                                   stored, self.max_image_bytes)
                        return recovered or {"ok": False, "error_code": "output_invalid"}
                    if status == "running":
                        lease = durable.get("lease") or durable.get("lease_token")
                        job_id = durable.get("job_id")
                        if not lease or not job_id:
                            return {"ok": False, "error_code": "tenant_busy"}
                    elif status == "queued":
                        return {"ok": False, "error_code": "tenant_busy"}
                    else:
                        return {"ok": False, "error_code": "provider_failed"}
                else:
                    with self._condition:
                        existing = self._results.get(cache_key)
                        if existing is not None:
                            return dict(existing)
                output = Path(output_text)
                output.mkdir(mode=0o700, parents=True, exist_ok=True)
                # Provider scratch space stays in the central service's
                # private tmpfs. A tenant can write its own exchange mount but
                # can never race or replace the provider's in-progress files.
                with tempfile.TemporaryDirectory(prefix=f"admira-image-{request_id[:12]}-") as work:
                    try:
                        snapshots = _snapshot_references(Path(output_text), refs, Path(work))
                        provider_body = dict(body, references=snapshots)
                        generated = self.provider(provider_body, Path(work))
                        if isinstance(generated, (str, Path)):
                            source = Path(generated)
                            if not source.is_absolute():
                                source = Path(work) / source
                            work_root = Path(work).resolve(strict=True)
                            try:
                                source.resolve(strict=True).relative_to(work_root)
                            except (OSError, ValueError) as exc:
                                raise ValueError("output_invalid") from exc
                            details = source.lstat()
                            if source.is_symlink() or not stat.S_ISREG(details.st_mode):
                                raise ValueError("output_invalid")
                            if details.st_size > self.max_image_bytes:
                                raise ValueError("output_too_large")
                            data = source.read_bytes()
                        else:
                            data = bytes(generated)
                        if len(data) > self.max_image_bytes:
                            raise ValueError("output_too_large")
                        if not _magic(data):
                            raise ValueError("output_invalid")
                        name = f"{secrets.token_hex(16)}{_extension(data)}"
                        fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=str(output))
                        try:
                            with os.fdopen(fd, "wb") as handle:
                                handle.write(data)
                                handle.flush()
                                os.fsync(handle.fileno())
                            os.chmod(temporary, 0o600)
                            final = output / name
                            os.replace(temporary, final)
                            # Keep the committed path until the durable ledger
                            # acknowledges it.  Any later filesystem/DB error
                            # must remove it so an uncommitted image cannot be
                            # observed or accidentally reused by a retry.
                            final_output = final
                            directory_fd = os.open(output, os.O_RDONLY)
                            try:
                                os.fsync(directory_fd)
                            finally:
                                os.close(directory_fd)
                        finally:
                            try:
                                os.unlink(temporary)
                            except FileNotFoundError:
                                pass
                    except ValueError as exc:
                        if final_output is not None:
                            try:
                                final_output.unlink()
                            except OSError:
                                pass
                        code = str(exc) if str(exc) in {
                            "reference_invalid", "output_invalid", "output_too_large"
                        } else "provider_failed"
                        if self.ledger is not None and job_id is not None and lease is not None:
                            try:
                                self.ledger.fail(job_id, lease, code)
                            except Exception:
                                pass
                        return {"ok": False, "error_code": code}
                    except SafeProviderFailure as exc:
                        if final_output is not None:
                            try:
                                final_output.unlink()
                            except OSError:
                                pass
                        if self.ledger is not None and job_id is not None and lease is not None:
                            try:
                                self.ledger.fail(job_id, lease, "provider_failed")
                            except Exception:
                                pass
                        return {"ok": False, "error_code": "provider_failed",
                                "failure_category": exc.failure_category}
                    except Exception:
                        if final_output is not None:
                            try:
                                final_output.unlink()
                            except OSError:
                                pass
                        if self.ledger is not None and job_id is not None and lease is not None:
                            try:
                                self.ledger.fail(job_id, lease, "provider_failed")
                            except Exception:
                                pass
                        return {"ok": False, "error_code": "provider_failed"}
                    result = {"ok": True, "tenant_id": tenant_id, "request_id": request_id,
                              "output_ref": name, "size": len(data),
                              "sha256": hashlib.sha256(data).hexdigest()}
                if self.ledger is not None:
                    try:
                        completed = bool(self.ledger.complete(job_id, lease, result))
                    except Exception:
                        completed = False
                    if not completed:
                        try:
                            if final_output is not None:
                                final_output.unlink()
                        except OSError:
                            pass
                        return {"ok": False, "error_code": "provider_failed"}
                with self._condition:
                    self._results[cache_key] = result
                return dict(result)
            finally:
                self._leave(tenant_id)
        except ValueError as exc:
            code = str(exc) if str(exc) in SAFE_ERRORS else "invalid_request"
            return {"ok": False, "error_code": code}
        except Exception:
            return {"ok": False, "error_code": "internal_error"}
