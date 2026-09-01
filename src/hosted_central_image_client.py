"""Opt-in client for the hosted central image broker (r91).

The client is intentionally inert unless the control-plane writes a private,
per-turn entitlement file.  It is safe to import from the existing image
bridge before the broker is deployed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import socket
import stat
import tempfile
import time
import uuid
import re
from pathlib import Path
from typing import Any, Mapping

TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")
OUTPUT_REF_RE = re.compile(r"^[a-f0-9]{32,64}\.(?:png|jpe?g|webp)$")
MAX_PROMPT = 10000
MAX_REFS = 8
MAX_REF_BYTES = 50 * 1024 * 1024
MAX_RESPONSE = 64 * 1024
MAX_IMAGE = 20 * 1024 * 1024
VALID_ASPECTS = {"square", "portrait", "landscape", "wide"}


def _tenant(value: object) -> str:
    value = str(value or "")
    if not TENANT_RE.fullmatch(value):
        raise ValueError("invalid_request")
    return value


def _read_private_regular(path: Path, minimum: int = 1, maximum: int = 1024 * 1024) -> bytes:
    """Read a private regular file without a symlink-following TOCTOU gap."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError("disabled") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("disabled")
        if info.st_size > maximum:
            raise ValueError("disabled")
        chunks: list[bytes] = []
        size = 0
        while size <= maximum:
            chunk = os.read(fd, min(65536, maximum + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > maximum:
            raise ValueError("disabled")
        data = b"".join(chunks).strip()
    except OSError as exc:
        raise ValueError("disabled") from exc
    finally:
        os.close(fd)
    if len(data) < minimum:
        raise ValueError("disabled")
    return data


def _private_file(path: Path, minimum: int = 1) -> bytes:
    try:
        return _read_private_regular(path, minimum=minimum)
    except ValueError as exc:
        # Preserve the client's existing safe provider-failure behavior for a
        # missing or malformed key; the reason must not distinguish key state.
        raise OSError("private_file_invalid") from exc


def _json_file(path: Path) -> Mapping[str, Any] | None:
    try:
        value = json.loads(_read_private_regular(path).decode("utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
        return None


def _snapshot_reference(source: Path, target: Path) -> tuple[str, int, str]:
    """Copy one reference through an open descriptor into a private snapshot."""
    suffix = source.suffix.lower()[:10]
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        source_fd = os.open(source, flags)
    except OSError as exc:
        raise ValueError("reference_invalid") from exc
    target_fd = -1
    try:
        info = os.fstat(source_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_REF_BYTES:
            raise ValueError("reference_invalid")
        target_fd = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        total = 0
        digest = hashlib.sha256()
        while total <= MAX_REF_BYTES:
            chunk = os.read(source_fd, min(65536, MAX_REF_BYTES + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_REF_BYTES:
                raise ValueError("reference_invalid")
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(target_fd, view)
                if written <= 0:
                    raise OSError("reference_snapshot_write_failed")
                view = view[written:]
        os.fchmod(target_fd, 0o600)
        return digest.hexdigest(), total, suffix
    except OSError as exc:
        raise ValueError("reference_invalid") from exc
    finally:
        if target_fd >= 0:
            os.close(target_fd)
        os.close(source_fd)


def _magic(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "webp"
    return None


def _safe_name(value: object) -> str:
    name = Path(str(value or "creative")).name
    if not name or name in {".", ".."} or name != str(value or "creative") or len(name) > 120:
        raise ValueError("invalid_request")
    return name


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _error(reason: str) -> dict[str, Any]:
    return {"ok": False, "reason": reason, "error": "No se pudo generar la imagen central."}


def _request_uuid(tenant_id: str, update_id: str, prompt: str, purpose: str, aspect: str,
                  references: list[dict[str, object]]) -> str:
    digest = hashlib.sha256(_canonical({
        "tenant_id": tenant_id,
        "update_id": update_id,
        "prompt": prompt,
        "creative_purpose": purpose,
        "aspect": aspect,
        "references": references,
    })).hexdigest()
    return str(uuid.UUID(hex=digest[:32]))


def maybe_generate_central_image(prompt: str, *, output_root: str | Path, output_name: str = "creative",
                                 reference_image_paths: list[str | Path] | None = None,
                                 purpose: str = "image_generation", aspect: str | None = None,
                                 update_id: object = None,
                                 timeout: float = 270, now: float | None = None) -> dict[str, Any] | None:
    """Call r91 only for an explicitly entitled central-sponsored turn.

    Returns ``None`` for disabled/personal/blocked routes so the caller may
    select its normal local path.  A central-not-ready entitlement returns a
    safe blocking error and must not fall back to a personal/local provider.
    """
    auth_path = Path(os.environ.get("ADMIRA_HOSTED_IMAGE_ACCESS_FILE", "/app/runtime/hosted_image_access.json"))
    access = _json_file(auth_path)
    if not access:
        return None
    route = str(access.get("route") or "")
    if route in {"disabled", "personal_chatgpt", "legacy", ""}:
        return None
    if route == "blocked":
        return _error("entitlement_blocked")
    if route != "central_sponsored":
        return _error("entitlement_blocked")
    if access.get("central_ready") is not True:
        return _error("central_not_ready")
    try:
        expected_tenant = _tenant(os.environ.get("ADMIRA_TENANT_ID"))
    except ValueError:
        # A filtered child environment is a safe central-route failure, never
        # a reason to throw into the conversational tool runner or fall back
        # to a different tenant/account.
        return _error("invalid_request")
    if access.get("tenant_id") != expected_tenant:
        return _error("invalid_request")
    request_tenant = expected_tenant
    prompt = str(prompt or "").strip()
    if not prompt or len(prompt) > MAX_PROMPT:
        return _error("invalid_request")
    try:
        name = _safe_name(output_name)
        raw_root = Path(output_root)
        root_details = raw_root.lstat()
        if raw_root.is_symlink() or not stat.S_ISDIR(root_details.st_mode):
            raise ValueError("invalid_request")
        root = raw_root.resolve(strict=True)
        refs = list(reference_image_paths or [])
        if len(refs) > MAX_REFS:
            raise ValueError("reference_invalid")
        exchange_root = Path(os.environ.get("ADMIRA_CENTRAL_IMAGE_EXCHANGE_ROOT", "/run/admira-central-images"))
        socket_path = Path(os.environ.get("ADMIRA_CENTRAL_IMAGE_SOCKET", "/run/admira-central-image-broker/broker.sock"))
        key_path = Path(os.environ.get("ADMIRA_CENTRAL_IMAGE_CLIENT_KEY_FILE", "/app/runtime/central_image_client.key"))
        key = _private_file(key_path, 32)
        exchange_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        exchange_details = exchange_root.lstat()
        if exchange_root.is_symlink() or not stat.S_ISDIR(exchange_details.st_mode) or stat.S_IMODE(exchange_details.st_mode) & 0o077:
            raise ValueError("disabled")
        with tempfile.TemporaryDirectory(prefix=f"{request_tenant}-", dir=exchange_root) as temp:
            exchange = Path(temp).resolve()
            ref_meta: list[dict[str, object]] = []
            ref_names: list[str] = []
            total = 0
            for index, source in enumerate(refs):
                source = Path(source)
                target = exchange / f"reference-{index}{source.suffix.lower()[:10]}"
                digest, size, suffix = _snapshot_reference(source, target)
                total += size
                if total > MAX_REF_BYTES:
                    raise ValueError("reference_invalid")
                ref_meta.append({"sha256": digest, "bytes": size, "suffix": suffix})
                ref_names.append(f"{exchange.name}/{target.name}")
            turn_update_id = str(update_id if update_id not in (None, "") else access.get("update_id") or "")
            creative_purpose = str(purpose or "image_generation").strip()[:80]
            requested_aspect = str(aspect or "").strip().lower()
            if not requested_aspect:
                requested_aspect = "portrait" if any(token in prompt.lower() for token in ("4:5", "9:16", "portrait")) else (
                    "landscape" if any(token in prompt.lower() for token in ("16:9", "landscape")) else "square"
                )
            if requested_aspect not in VALID_ASPECTS:
                raise ValueError("invalid_request")
            request_id = _request_uuid(request_tenant, turn_update_id, prompt, creative_purpose, requested_aspect, ref_meta)
            body = {
                "tenant_id": request_tenant,
                "request_id": request_id,
                "prompt": prompt,
                "purpose": "image_generation",
                "creative_purpose": creative_purpose,
                "aspect": requested_aspect,
                "update_id": turn_update_id,
                "references": ref_names,
                "reference_metadata": ref_meta,
            }
            envelope = {"timestamp": int(time.time() if now is None else now), "nonce": secrets.token_hex(16), "body": body}
            envelope["signature"] = hmac.new(key, _canonical(envelope), hashlib.sha256).hexdigest()
            line = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
            if len(line) > MAX_RESPONSE:
                return _error("invalid_request")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(max(0.1, min(float(timeout), 300.0)))
                sock.connect(str(socket_path))
                sock.sendall(line)
                chunks = []
                size = 0
                while size < MAX_RESPONSE:
                    chunk = sock.recv(min(8192, MAX_RESPONSE - size))
                    if not chunk:
                        break
                    chunks.append(chunk); size += len(chunk)
                    if b"\n" in chunk:
                        break
            raw_response = b"".join(chunks)
            if b"\n" not in raw_response:
                return _error("provider_failed")
            response = json.loads(raw_response.split(b"\n", 1)[0])
            if not isinstance(response, dict) or response.get("ok") is not True:
                safe_reason = str(response.get("error_code") or "provider_failed") if isinstance(response, dict) else "provider_failed"
                if safe_reason not in {
                    "entitlement_blocked", "personal_provider_required", "tenant_busy",
                    "provider_failed", "output_invalid", "output_too_large",
                    "central_not_ready", "internal_error",
                }:
                    safe_reason = "provider_failed"
                return _error(safe_reason)
            if response.get("tenant_id") != request_tenant or response.get("request_id") != body["request_id"]:
                return _error("invalid_response")
            ref = response.get("output_ref")
            if not isinstance(ref, str) or not OUTPUT_REF_RE.fullmatch(ref):
                return _error("output_invalid")
            generated = (exchange_root / ref).resolve()
            try:
                generated.relative_to(exchange_root.resolve(strict=True))
                generated_details = generated.lstat()
            except (OSError, ValueError):
                return _error("output_invalid")
            if generated.is_symlink() or not stat.S_ISREG(generated_details.st_mode):
                return _error("output_invalid")
            data = generated.read_bytes()
            extension = _magic(data)
            if len(data) > MAX_IMAGE or not extension:
                return _error("output_invalid")
            digest = hashlib.sha256(data).hexdigest()
            if response.get("sha256") != digest or response.get("size") not in (None, len(data)):
                return _error("output_invalid")
            stem = Path(name).stem or "creative"
            target_dir = root / f"central-{body['request_id'][:12]}"
            target_dir.mkdir(mode=0o755, exist_ok=True)
            if target_dir.is_symlink() or not target_dir.is_dir():
                return _error("output_invalid")
            # ``root`` is the tenant's private 0700 output mount.  The host
            # runtime broker must be able to traverse this generated child in
            # order to stage the verified file into Telegram's private spool;
            # it is not a cross-tenant share.  Repair an idempotent directory
            # from an older attempt as well as creating new ones correctly.
            target_dir.chmod(0o755)
            destination = target_dir / f"{stem}.{extension}"
            fd, temporary = tempfile.mkstemp(prefix=f".{stem}.", dir=str(target_dir))
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                # The enclosing tenant output mount remains private.  This
                # file mode grants the host-side delivery broker read access
                # for the one-way Telegram staging handoff.
                os.chmod(temporary, 0o644)
                os.replace(temporary, destination)
                directory_fd = os.open(target_dir, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
            asset_id = str(destination.relative_to(root))
            return {
                "ok": True,
                "image_path": str(destination),
                "asset_id": asset_id,
                "preview_url": f"/api/creative-asset?id={asset_id}",
                "backend": "hosted-central-image",
                "request_id": body["request_id"],
            }
    except ValueError as exc:
        reason = str(exc)
        return _error(reason if reason in {"invalid_request", "reference_invalid", "disabled"} else "provider_failed")
    except (OSError, socket.timeout, socket.error, json.JSONDecodeError):
        return _error("provider_failed")
