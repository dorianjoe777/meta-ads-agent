#!/usr/bin/env python3
"""Run one isolated Hermes turn for a tenant.

This is intentionally a host-side bridge, not a Telegram bot. The central
runtime worker has already resolved ``chat_id -> tenant_id`` in PostgreSQL
before passing a JSON message on stdin. The tenant never receives the shared
bot token and the message is not placed in the process list.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# Keep the controller import independent of the caller's working directory;
# the script is also imported directly by its focused unit tests.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tenantctl import DEFAULT_BASE, compose_argv, tenant_path, validate_tenant_id


MESSAGE_LIMIT = 5000
CHAT_ID_RE = re.compile(r"^-?[0-9]{1,32}$")
MEDIA_RE = re.compile(r"(?m)^\s*MEDIA:(/app/output/[^\s]+)\s*$")
INBOUND_IMAGE_RE = re.compile(
    r"^/app/output/telegram_uploads/[a-f0-9]{16,64}/[a-f0-9]{16,64}\.(?:jpg|jpeg|png|webp|gif)$",
    re.IGNORECASE,
)
INNER_SCRIPT = r'''
import json
import sys

sys.path.insert(0, "/app/src")
from hermes_bridge import chat
from product_config import load_config

payload = json.load(sys.stdin)
result = chat(load_config(), payload)
if not isinstance(result, dict):
    result = {"ok": bool(result), "reply": str(result or "")}
print(json.dumps(result, ensure_ascii=False))
'''


def _error(code: str, detail: str = "") -> dict[str, object]:
    result: dict[str, object] = {"ok": False, "error_code": code}
    if detail:
        result["detail"] = detail[:240]
    return result


def validate_turn(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("request must be a JSON object")
    message = str(payload.get("message") or "").strip()
    if not message:
        raise ValueError("message is required")
    if len(message) > MESSAGE_LIMIT:
        raise ValueError(f"message exceeds {MESSAGE_LIMIT} characters")
    chat_id = str(payload.get("chat_id") or "").strip()
    if not CHAT_ID_RE.fullmatch(chat_id):
        raise ValueError("chat_id must be a Telegram numeric ID")
    language = str(payload.get("language") or "es").strip().lower()
    if not re.fullmatch(r"[a-z]{2,12}", language):
        raise ValueError("language must be a short alphabetic code")
    update_id = payload.get("update_id")
    if update_id not in (None, ""):
        try:
            update_id = int(update_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("update_id must be an integer") from exc
        if update_id < 0:
            raise ValueError("update_id must be non-negative")
    if payload.get("image_path") or payload.get("document_path"):
        raise ValueError("singular or document paths are not accepted")
    raw_images = payload.get("image_paths") or []
    if not isinstance(raw_images, list) or len(raw_images) > 4:
        raise ValueError("image_paths must contain at most four images")
    images = []
    for value in raw_images:
        candidate = str(value or "").strip()
        if not INBOUND_IMAGE_RE.fullmatch(candidate):
            raise ValueError("image path is outside the hosted Telegram inbox")
        images.append(candidate)
    request = {
        "message": message,
        "language": language,
        "channel": "telegram",
        "chat_id": chat_id,
        "update_id": update_id,
        "session_key": f"agent:main:telegram:dm:{chat_id}",
        "_admira_trusted_chat_id": f"hosted:telegram:{chat_id}",
        "_admira_trusted_session_id": f"agent:main:telegram:dm:{chat_id}",
    }
    if images:
        request["image_paths"] = images
    return request


def _public_runtime_result(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        return _error("runtime_protocol_error")
    reply = str(raw.get("reply") or raw.get("final_response") or "").strip()
    result: dict[str, object] = {
        "ok": bool(raw.get("ok")) and bool(reply),
        "reply": reply,
        "media_paths": MEDIA_RE.findall(reply),
    }
    if not result["ok"]:
        result["error_code"] = str(raw.get("error_type") or "runtime_turn_failed")[:80]
    return result


def run_turn(base: Path, tenant_id: str, payload: object, *, timeout: int = 330) -> dict[str, object]:
    try:
        tenant_id = validate_tenant_id(tenant_id)
        request = validate_turn(payload)
    except ValueError as exc:
        return _error("invalid_request", str(exc))
    root = tenant_path(base, tenant_id)
    compose_file = root / "compose.yaml"
    if not compose_file.is_file():
        return _error("tenant_not_provisioned")
    timeout = max(30, min(360, int(timeout)))
    command = compose_argv(root, "exec", "-T", "admira", "python3", "-c", INNER_SCRIPT)
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(request, ensure_ascii=False),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _error("runtime_timeout")
    except OSError:
        return _error("docker_unavailable")
    if completed.returncode != 0:
        # Preserve only a short operational classification; provider details
        # and credentials must never cross into Telegram's response channel.
        return _error("runtime_not_ready")
    try:
        raw = json.loads(completed.stdout or "")
    except (TypeError, ValueError):
        return _error("runtime_protocol_error")
    return _public_runtime_result(raw)


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one isolated hosted Admira turn")
    parser.add_argument("tenant_id")
    parser.add_argument("--base-dir", default=str(DEFAULT_BASE), type=Path)
    parser.add_argument("--timeout", default=330, type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        payload = json.load(sys.stdin)
    except (ValueError, json.JSONDecodeError) as exc:
        print(json.dumps(_error("invalid_json", str(exc))), file=sys.stderr)
        return 2
    result = run_turn(args.base_dir, args.tenant_id, payload, timeout=args.timeout)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
