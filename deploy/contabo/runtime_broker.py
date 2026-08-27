#!/usr/bin/env python3
"""Narrow host broker for isolated Admira tenant runtimes.

The Telegram-facing services never receive the Docker socket.  A dedicated
host service owns lifecycle/turn execution and exposes only this authenticated
Unix-socket protocol.  The shared Telegram token is never passed to this
process.  Requests and responses are one bounded JSON line each.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import socket
import socketserver
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tenant_turn import MEDIA_RE, run_turn
from tenantctl import DEFAULT_BASE, compose_argv, lifecycle, status, tenant_path, validate_tenant_id


DEFAULT_SOCKET = Path("/run/admira-runtime-broker/broker.sock")
DEFAULT_KEY_FILE = Path("/etc/admira/runtime-broker.key")
DEFAULT_SPOOL = Path("/srv/admira/shared/telegram-spool")
MAX_WIRE_BYTES = 524_288
MAX_MEDIA_BYTES = 50 * 1024 * 1024
MEDIA_REF_RE = re.compile(r"^[a-f0-9]{32,64}\.(?:jpg|jpeg|png|webp|gif|mp4|mov|pdf|bin)$", re.IGNORECASE)
JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_SUFFIXES = {".mp4", ".mov"}
ALLOWED_SUFFIXES = IMAGE_SUFFIXES | VIDEO_SUFFIXES | {".pdf", ".bin"}

CRON_RUN_SCRIPT = r'''
import json
import sys

from cron.jobs import advance_next_run, claim_dispatch, get_job, list_jobs, mark_job_run, save_job_output
from cron.scheduler import run_job

job_id = str(json.load(sys.stdin).get("job_id") or "")
job = get_job(job_id)
if not job:
    print(json.dumps({"ok": False, "error_code": "cron_job_not_found"}))
    raise SystemExit(0)
if not claim_dispatch(job_id):
    print(json.dumps({"ok": True, "reply": "", "cron_jobs": list_jobs(include_disabled=True)}))
    raise SystemExit(0)
advance_next_run(job_id)
success, output_doc, final_response, error = run_job(job)
if output_doc:
    save_job_output(job_id, output_doc)
mark_job_run(job_id, success, error)
print(json.dumps({
    "ok": bool(success),
    "reply": str(final_response or ""),
    "error_code": "" if success else "cron_execution_failed",
    "cron_jobs": list_jobs(include_disabled=True),
}, ensure_ascii=False))
'''


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _load_key(path: Path) -> bytes:
    key = path.read_bytes().strip()
    if len(key) < 32:
        raise ValueError("runtime broker key is missing or too short")
    return key


def sign_body(key: bytes, body: dict[str, object], *, now: int | None = None, nonce: str | None = None) -> dict[str, object]:
    envelope: dict[str, object] = {
        "timestamp": int(now if now is not None else time.time()),
        "nonce": nonce or secrets.token_hex(16),
        "body": body,
    }
    envelope["signature"] = hmac.new(key, _canonical(envelope), hashlib.sha256).hexdigest()
    return envelope


class ReplayWindow:
    def __init__(self) -> None:
        self._seen: dict[str, int] = {}
        self._lock = threading.Lock()

    def verify(self, envelope: object, key: bytes, *, now: int | None = None) -> dict[str, object]:
        if not isinstance(envelope, dict):
            raise ValueError("invalid_envelope")
        timestamp = int(envelope.get("timestamp") or 0)
        current = int(now if now is not None else time.time())
        if abs(current - timestamp) > 90:
            raise ValueError("expired_request")
        nonce = str(envelope.get("nonce") or "")
        signature = str(envelope.get("signature") or "")
        body = envelope.get("body")
        if not re.fullmatch(r"[a-f0-9]{32}", nonce) or not isinstance(body, dict):
            raise ValueError("invalid_envelope")
        unsigned = {"timestamp": timestamp, "nonce": nonce, "body": body}
        expected = hmac.new(key, _canonical(unsigned), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid_signature")
        with self._lock:
            self._seen = {item: seen_at for item, seen_at in self._seen.items() if seen_at >= current - 180}
            if nonce in self._seen:
                raise ValueError("replayed_request")
            self._seen[nonce] = current
        return body


def _safe_ref(value: object) -> str:
    ref = str(value or "").strip().lower()
    if not MEDIA_REF_RE.fullmatch(ref):
        raise ValueError("invalid_media_ref")
    return ref


def _regular_file(path: Path, root: Path, *, limit: int = MAX_MEDIA_BYTES) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("media_path_escape") from exc
    details = resolved.lstat()
    if not stat.S_ISREG(details.st_mode) or path.is_symlink() or details.st_size > limit:
        raise ValueError("invalid_media_file")
    return resolved


def _cron_snapshot(root: Path) -> list[dict[str, object]]:
    jobs_file = root / "runtime" / "hermes" / "cron" / "jobs.json"
    try:
        raw = json.loads(jobs_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    result: list[dict[str, object]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not JOB_ID_RE.fullmatch(str(item.get("id") or "")):
            continue
        result.append({
            "id": str(item["id"]),
            "name": str(item.get("name") or "")[:200],
            "enabled": bool(item.get("enabled", True)),
            "next_run_at": str(item.get("next_run_at") or ""),
            "schedule_display": str(item.get("schedule_display") or "")[:200],
            "timezone": str(item.get("timezone") or "UTC")[:100],
        })
    return result[:100]


class BrokerCore:
    def __init__(self, *, tenants_base: Path = Path(DEFAULT_BASE), spool_base: Path = DEFAULT_SPOOL) -> None:
        self.tenants_base = tenants_base
        self.spool_base = spool_base
        self.inbound = spool_base / "inbound"
        self.outbound = spool_base / "outbound"
        for directory in (self.inbound, self.outbound):
            directory.mkdir(parents=True, exist_ok=True)
            # Poller/delivery run with the dedicated spool supplementary
            # group. Preserve group access instead of silently undoing the
            # permissions established by install-runtime-broker.sh.
            directory.chmod(0o770)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock_for(self, tenant_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(tenant_id, threading.Lock())

    def _ensure_running(self, tenant_id: str) -> Path:
        root = tenant_path(self.tenants_base, tenant_id)
        if not (root / "compose.yaml").is_file():
            raise ValueError("tenant_not_provisioned")
        result = lifecycle(self.tenants_base, tenant_id, "start")
        if not result.get("ok"):
            raise RuntimeError("runtime_start_failed")
        return root

    def _prepare_inbound(self, root: Path, media: object, update_id: object) -> list[str]:
        if not isinstance(media, list) or len(media) > 8:
            raise ValueError("invalid_inbound_media")
        token = hashlib.sha256(f"{update_id}:{secrets.token_hex(8)}".encode()).hexdigest()[:32]
        target_dir = root / "output" / "telegram_uploads" / token
        target_dir.mkdir(parents=True, exist_ok=True)
        target_dir.chmod(0o700)
        images: list[str] = []
        for item in media:
            if not isinstance(item, dict):
                raise ValueError("invalid_inbound_media")
            ref = _safe_ref(item.get("ref"))
            source = _regular_file(self.inbound / ref, self.inbound)
            suffix = source.suffix.lower()
            if suffix not in ALLOWED_SUFFIXES:
                raise ValueError("unsupported_media_type")
            target_name = hashlib.sha256(ref.encode()).hexdigest()[:32] + suffix
            target = target_dir / target_name
            shutil.copyfile(source, target)
            target.chmod(0o600)
            if suffix in IMAGE_SUFFIXES and len(images) < 4:
                images.append(f"/app/output/telegram_uploads/{token}/{target_name}")
        return images

    def _stage_outbound(self, root: Path, media_paths: object) -> list[dict[str, str]]:
        staged: list[dict[str, str]] = []
        output_root = root / "output"
        for raw in list(media_paths or [])[:8]:
            path = str(raw or "").strip()
            if not path.startswith("/app/output/"):
                continue
            relative = path.removeprefix("/app/output/")
            source = _regular_file(output_root / relative, output_root)
            suffix = source.suffix.lower()
            if suffix not in ALLOWED_SUFFIXES:
                continue
            ref = f"{secrets.token_hex(24)}{suffix}"
            temporary = self.outbound / f".{ref}.tmp"
            destination = self.outbound / ref
            digest = hashlib.sha256()
            with source.open("rb") as reader, temporary.open("xb") as writer:
                while chunk := reader.read(1024 * 1024):
                    digest.update(chunk)
                    writer.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            temporary.chmod(0o660)
            os.replace(temporary, destination)
            kind = "photo" if suffix in IMAGE_SUFFIXES else "video" if suffix in VIDEO_SUFFIXES else "document"
            staged.append({"kind": kind, "ref": ref, "sha256": digest.hexdigest(), "caption": ""})
        return staged

    def _turn(self, tenant_id: str, request: dict[str, object]) -> dict[str, object]:
        root = self._ensure_running(tenant_id)
        turn = request.get("turn")
        if not isinstance(turn, dict):
            raise ValueError("invalid_turn")
        payload = dict(turn)
        images = self._prepare_inbound(root, request.get("media") or [], payload.get("update_id"))
        if images:
            payload["image_paths"] = images
        result: dict[str, object] = {"ok": False, "error_code": "runtime_not_ready"}
        for attempt in range(10):
            result = run_turn(self.tenants_base, tenant_id, payload)
            if result.get("error_code") != "runtime_not_ready":
                break
            if attempt < 9:
                time.sleep(2)
        reply = str(result.get("reply") or "")
        staged = self._stage_outbound(root, result.get("media_paths") or [])
        visible = MEDIA_RE.sub("", reply).strip()
        return {
            "ok": bool(result.get("ok")) or bool(visible) or bool(staged),
            "reply": visible,
            "media": staged,
            "error_code": str(result.get("error_code") or "")[:80],
            "cron_jobs": _cron_snapshot(root),
        }

    def _run_job(self, tenant_id: str, request: dict[str, object]) -> dict[str, object]:
        root = self._ensure_running(tenant_id)
        job_id = str(request.get("job_id") or "")
        if not JOB_ID_RE.fullmatch(job_id):
            raise ValueError("invalid_job_id")
        command = compose_argv(root, "exec", "-T", "admira", "python3", "-c", CRON_RUN_SCRIPT)
        try:
            completed = subprocess.run(
                command, input=json.dumps({"job_id": job_id}), text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("cron_timeout") from exc
        if completed.returncode != 0:
            raise RuntimeError("cron_runtime_failed")
        try:
            raw = json.loads(completed.stdout or "")
        except ValueError as exc:
            raise RuntimeError("cron_protocol_error") from exc
        reply = str(raw.get("reply") or "")
        media_paths = MEDIA_RE.findall(reply)
        staged = self._stage_outbound(root, media_paths)
        return {
            "ok": bool(raw.get("ok")),
            "reply": MEDIA_RE.sub("", reply).strip(),
            "media": staged,
            "error_code": str(raw.get("error_code") or "")[:80],
            "cron_jobs": _cron_snapshot(root),
        }

    def handle(self, request: object) -> dict[str, object]:
        if not isinstance(request, dict):
            raise ValueError("invalid_request")
        action = str(request.get("action") or "")
        tenant_id = validate_tenant_id(str(request.get("tenant_id") or ""))
        with self._lock_for(tenant_id):
            if action == "turn":
                return self._turn(tenant_id, request)
            if action == "run_job":
                return self._run_job(tenant_id, request)
            if action == "sync_jobs":
                root = tenant_path(self.tenants_base, tenant_id)
                return {"ok": True, "cron_jobs": _cron_snapshot(root)}
            if action == "suspend":
                result = lifecycle(self.tenants_base, tenant_id, "suspend")
                return {"ok": bool(result.get("ok")), "error_code": "" if result.get("ok") else "runtime_suspend_failed"}
            if action == "status":
                result = status(self.tenants_base, tenant_id)
                return {"ok": bool(result.get("ok")), "running": bool(result.get("output"))}
        raise ValueError("unsupported_action")


class BrokerClient:
    def __init__(self, socket_path: Path = DEFAULT_SOCKET, key_file: Path = DEFAULT_KEY_FILE, *, timeout: float = 920.0) -> None:
        self.socket_path, self.key_file, self.timeout = socket_path, key_file, timeout

    def request(self, body: dict[str, object]) -> dict[str, object]:
        wire = _canonical(sign_body(_load_key(self.key_file), body)) + b"\n"
        if len(wire) > MAX_WIRE_BYTES:
            raise ValueError("broker_request_too_large")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(self.timeout)
            client.connect(str(self.socket_path))
            client.sendall(wire)
            response = b""
            while not response.endswith(b"\n"):
                chunk = client.recv(min(65536, MAX_WIRE_BYTES + 1 - len(response)))
                if not chunk:
                    break
                response += chunk
                if len(response) > MAX_WIRE_BYTES:
                    raise RuntimeError("broker_response_too_large")
        try:
            parsed = json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError("broker_protocol_error") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("broker_protocol_error")
        return parsed


class _ThreadingUnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        line = self.rfile.readline(MAX_WIRE_BYTES + 1)
        if not line or len(line) > MAX_WIRE_BYTES:
            self._send({"ok": False, "error_code": "invalid_request"})
            return
        try:
            envelope = json.loads(line.decode("utf-8"))
            body = self.server.replay.verify(envelope, self.server.key)  # type: ignore[attr-defined]
            response = self.server.core.handle(body)  # type: ignore[attr-defined]
        except (ValueError, OSError) as exc:
            code = str(exc) if re.fullmatch(r"[a-z0-9_]{3,80}", str(exc)) else "invalid_request"
            response = {"ok": False, "error_code": code}
        except Exception:
            response = {"ok": False, "error_code": "broker_failure"}
        self._send(response)

    def _send(self, response: dict[str, object]) -> None:
        wire = _canonical(response)
        if len(wire) > MAX_WIRE_BYTES:
            wire = _canonical({"ok": False, "error_code": "broker_response_too_large"})
        self.wfile.write(wire + b"\n")


def serve(*, socket_path: Path, key_file: Path, tenants_base: Path, spool_base: Path, socket_gid: int | None = None) -> None:
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.parent.chmod(0o750)
    if socket_path.exists():
        if not stat.S_ISSOCK(socket_path.lstat().st_mode):
            raise RuntimeError("refusing to replace non-socket broker path")
        socket_path.unlink()
    server = _ThreadingUnixServer(str(socket_path), _Handler)
    server.key = _load_key(key_file)  # type: ignore[attr-defined]
    server.replay = ReplayWindow()  # type: ignore[attr-defined]
    server.core = BrokerCore(tenants_base=tenants_base, spool_base=spool_base)  # type: ignore[attr-defined]
    os.chmod(socket_path, 0o660)
    if socket_gid is not None:
        os.chown(socket_path, -1, socket_gid)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        if socket_path.exists() and stat.S_ISSOCK(socket_path.lstat().st_mode):
            socket_path.unlink()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Admira isolated runtime broker")
    result.add_argument("command", choices=("serve", "call"))
    result.add_argument("--socket", type=Path, default=Path(os.environ.get("ADMIRA_BROKER_SOCKET", DEFAULT_SOCKET)))
    result.add_argument("--key-file", type=Path, default=Path(os.environ.get("ADMIRA_BROKER_KEY_FILE", DEFAULT_KEY_FILE)))
    result.add_argument("--tenants-base", type=Path, default=Path(os.environ.get("ADMIRA_TENANTS_BASE", DEFAULT_BASE)))
    result.add_argument("--spool-base", type=Path, default=Path(os.environ.get("ADMIRA_TELEGRAM_SPOOL", DEFAULT_SPOOL)))
    result.add_argument("--socket-gid", type=int, default=None)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "serve":
        serve(socket_path=args.socket, key_file=args.key_file, tenants_base=args.tenants_base,
              spool_base=args.spool_base, socket_gid=args.socket_gid)
        return 0
    try:
        body = json.load(sys.stdin)
        result = BrokerClient(args.socket, args.key_file).request(body)
    except Exception as exc:
        result = {"ok": False, "error_code": str(exc) if re.fullmatch(r"[a-z0-9_]{3,80}", str(exc)) else "broker_client_failed"}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
