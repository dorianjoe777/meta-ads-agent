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
import os
import re
import stat
import subprocess
import sys
import tempfile
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
INBOUND_ATTACHMENT_RE = re.compile(
    r"^/app/output/telegram_uploads/[a-f0-9]{16,64}/[a-f0-9]{16,64}\.(?:jpg|jpeg|png|webp|gif|mp4|mov|pdf|bin)$",
    re.IGNORECASE,
)
ATTACHMENT_KINDS = {"photo", "video", "document"}
ATTACHMENT_LIMIT = 8
ATTACHMENT_SIZE_LIMIT = 50 * 1024 * 1024
INNER_SCRIPT = r'''
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/app/src")
from hermes_bridge import chat
from product_config import load_config

# Every hosted tenant runs its own dashboard process and owns its own durable
# recovery token under /app/dashboard/data.  Point the injected command bridge
# at that same-container loopback endpoint; no central credential or token is
# shared between tenants.
os.environ["ADMIRA_INTERNAL_MODEL_RECOVERY_URL"] = (
    "http://127.0.0.1:7871/api/internal/model-recovery"
)
os.environ["ADMIRA_INTERNAL_MODEL_RECOVERY_TOKEN_FILE"] = (
    "/app/dashboard/data/internal_model_recovery.token"
)


def personal_connection_ready_reply(reply, access, language):
    english = str(language or "es").lower().startswith("en")
    ready = access.get("central_ready") is True
    lifecycle = str(access.get("lifecycle_state") or "")
    ends_at = str(access.get("image_sponsorship_ends_at") or "").strip()
    if lifecycle == "trial":
        period = "during your free trial" if english else "durante tu prueba gratis"
    elif ends_at:
        period = (f"until {ends_at}" if english else f"hasta {ends_at}")
    else:
        period = "during your sponsored period" if english else "durante tu período patrocinado"
    sponsored = (
        f" Admira will still use its sponsored image accounts {period}"
        + ("." if ready else ", although that central service is still being enabled.")
        if english else
        f" Admira seguirá usando sus cuentas patrocinadas para imágenes {period}"
        + ("." if ready else ", aunque ese servicio central todavía se está habilitando.")
    )
    return str(reply or "").rstrip() + sponsored


def current_personal_chatgpt_copy(reply):
    """Normalize legacy r90 handoff copy to the hosted Luna fallback policy."""
    return (
        str(reply or "")
        .replace("Terra fallback", "Luna fallback")
        .replace("fallback Terra", "fallback Luna")
    )


def hosted_command(payload):
    """Handle commands which cannot be delegated to the language model."""
    command = str(payload.get("command") or "").strip().lower()
    text = str(payload.get("message") or "").strip()
    language = str(payload.get("language") or "es").lower()
    session_key = str(payload.get("session_key") or "")
    chat_id = str(payload.get("chat_id") or "")
    user_id = str(payload.get("user_id") or "")
    english = language.startswith("en")
    image_access = payload.get("image_access") if isinstance(payload.get("image_access"), dict) else {}
    image_route = str(image_access.get("route") or "legacy")
    reset_commands = {"nuevo", "new", "reset", "restart"}
    chatgpt_commands = {"conectar_chatgpt", "reconectar_chatgpt", "connect_chatgpt"}
    complete_reset_phrase = "Si quiero resetear completamente"
    try:
        from admira_hermes_runtime_patch import (
            _automatic_codex_recovery, _chatgpt_connection_reply,
            _chatgpt_connection_request, _chatgpt_login_confirmation_request,
            _chatgpt_login_confirmation_reply, _remember_chatgpt_login_pending,
        )
        from complete_reset import (
            COMPLETE_RESET_CONFIRMATION_PHRASE,
            COMPLETE_RESET_CONFIRMATION_TTL_SECONDS,
            begin_reset_confirmation,
            consume_reset_confirmation,
            write_private_json,
        )
    except Exception:
        if command in chatgpt_commands | {"resetear_completamente"} or text == complete_reset_phrase:
            return {"ok": True, "reply": (
                "I could not open that protected connection/reset flow right now. Nothing was changed; please try again." if english
                else "No pude abrir ese flujo protegido de conexión o reinicio en este momento. No cambié nada; inténtalo otra vez."
            )}
        if command in reset_commands:
            return {"ok": True, "reply": (
                "Done. I started a fresh conversation; your Meta connections, accounts, Page, and saved work remain." if english
                else "Listo. Reinicié solo el contexto de esta conversación; tus conexiones de Meta, cuentas, Página y trabajo guardado siguen intactos."
            )}
        return None
    paths = {
        "confirmation": Path("/app/runtime/telegram_hosted_reset_confirmation.json"),
        "request": Path("/app/runtime/telegram_hosted_reset_request.json"),
    }
    if command == "resetear_completamente":
        pending = begin_reset_confirmation(paths["confirmation"], paths["request"], chat_id, user_id)
        if pending.get("status") == "already_running":
            return {"ok": True, "reply": "Ya hay un reinicio completo en curso. Espera a que Admira vuelva a conectarse."}
        minutes = max(1, COMPLETE_RESET_CONFIRMATION_TTL_SECONDS // 60)
        return {"ok": True, "reply": (
            f"⚠️ Este reinicio es permanente y borra la configuración y memoria de este espacio, pero no las campañas ya existentes en Meta.\n\nResponde exactamente dentro de {minutes} minutos:\n{COMPLETE_RESET_CONFIRMATION_PHRASE}"
        )}
    # Any response other than the exact phrase cancels a pending destructive
    # reset before another native command or a model turn is allowed to run.
    result = consume_reset_confirmation(paths["confirmation"], paths["request"], text, chat_id, user_id)
    if result.get("matched") and result.get("status") == "confirmed":
        # Bind the destructive broker request to this exact durable Telegram
        # update.  The host validates all three identity fields independently
        # before it is allowed to stop or reset the tenant.
        request = result.get("request") if isinstance(result.get("request"), dict) else {}
        request["hosted_update_id"] = payload.get("update_id")
        write_private_json(paths["request"], request)
        return {"ok": True, "control_action": "complete_reset", "reply": "✅ Confirmación válida. Prepararé el reinicio completo de este espacio."}
    if result.get("matched"):
        return {"ok": True, "reply": "La confirmación venció o fue cancelada; no borré nada."}
    try:
        pending = json.loads(paths["request"].read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        pending = {}
    if (
        isinstance(pending, dict)
        and pending.get("status") == "pending"
        and str(pending.get("chat_id") or "") == chat_id
        and str(pending.get("user_id") or "") == user_id
        and str(pending.get("hosted_update_id")) == str(payload.get("update_id"))
    ):
        # A broker restart after confirmation must resume the same reset
        # instead of sending the confirmation phrase to the model.
        return {"ok": True, "control_action": "complete_reset", "reply": "✅ Confirmación válida. Prepararé el reinicio completo de este espacio."}
    if command in reset_commands:
        try:
            from campaign_editing import reset_conversation_edit_context
            reset_conversation_edit_context(chat_id)
        except Exception:
            pass
        return {"ok": True, "reply": (
            "Done. I started a fresh conversation; your Meta connections, accounts, Page, and saved work remain." if english
            else "Listo. Reinicié solo el contexto de esta conversación; tus conexiones de Meta, cuentas, Página y trabajo guardado siguen intactos."
        )}
    if command in chatgpt_commands or _chatgpt_connection_request(text):
        # Personal authentication is tenant-local and independent from Admira's
        # sponsored image entitlement.  A buyer may connect on day one and use
        # an account-advertised Codex model through /model while central images
        # continue to use the sponsored pool until its durable end timestamp.
        recovery = _automatic_codex_recovery(wait_seconds=15, action="switch")
        if recovery.get("url") and recovery.get("code"):
            _remember_chatgpt_login_pending(session_key)
        # Existing r90 tenant images still carry an older Terra label. The
        # hosted routing contract uses Luna, so normalize that legacy copy at
        # the host boundary until every tenant is upgraded to r91 or newer.
        reply = current_personal_chatgpt_copy(_chatgpt_connection_reply(recovery, language))
        if image_route == "central_sponsored":
            reply = personal_connection_ready_reply(reply, image_access, language)
        return {"ok": True, "reply": reply}
    if _chatgpt_login_confirmation_request(text, session_key):
        return {
            "ok": True,
            "reply": current_personal_chatgpt_copy(
                _chatgpt_login_confirmation_reply(session_key, language)
            ),
        }
    return None

def prepare_attachments(payload):
    """Turn hosted videos/documents into useful, bounded Hermes context."""
    attachments = payload.get("attachments") if isinstance(payload.get("attachments"), list) else []
    if not attachments:
        return payload
    images = list(payload.get("image_paths") or [])[:4]
    notes = []
    documents = []
    for item in attachments[:8]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        path = str(item.get("path") or "")
        if kind == "video":
            try:
                from public_asset_fetcher import extract_video_preview_frames
                preview = extract_video_preview_frames(path, output_dir=Path(path).parent / f"{Path(path).stem}_admira_frames", max_frames=4)
            except Exception:
                preview = {"frames": [], "reason": "frame_extraction_failed"}
            frames = [str(value) for value in (preview.get("frames") or []) if str(value).strip()]
            for frame in frames:
                if frame not in images and len(images) < 4:
                    images.append(frame)
            if frames:
                duration = preview.get("duration_seconds") or 0
                notes.append(
                    f"[ADMIRA HOSTED VIDEO — internal] The buyer attached a video. "
                    f"Admira extracted {len(frames)} representative frames for visual review"
                    + (f" from about {duration:g} seconds" if duration else "")
                    + ". Review every attached frame; the MP4/MOV remains the original creative asset. [END HOSTED VIDEO]"
                )
            else:
                notes.append("[ADMIRA HOSTED VIDEO — internal] The buyer attached a video, but representative frames could not be extracted. Ask them to resend the video or a few screenshots if visual inspection is essential. [END HOSTED VIDEO]")
        elif kind == "document" and Path(path).suffix.lower() == ".pdf":
            documents.append(path)
        elif kind == "document":
            notes.append("[ADMIRA HOSTED DOCUMENT — internal] The buyer attached a document whose format is not directly inspectable. Ask for a PDF, CSV, spreadsheet, or images if its contents are needed. [END HOSTED DOCUMENT]")
    if documents:
        listed = "\n".join(f"- {path}" for path in documents)
        notes.append(
            "[ADMIRA HOSTED PRODUCT DOCUMENT — internal, never quote paths] The buyer attached PDF document(s). "
            "If they contain products, services, prices, offers, bundles, or catalog information, call "
            "mcp_admira_import_product_catalog in this turn with these file_paths. Otherwise inspect only as needed and answer the buyer naturally.\n"
            f"{listed}\n[END HOSTED PRODUCT DOCUMENT]"
        )
    if images:
        payload["image_paths"] = images[:4]
    if notes:
        payload["message"] = ("\n\n".join(notes) + "\n\n" + str(payload.get("message") or "")).strip()
    return payload

payload = json.load(sys.stdin)
result = hosted_command(payload)
if result is None:
    result = chat(load_config(), prepare_attachments(payload))
    if (
        isinstance(result, dict)
        and not result.get("ok")
        and "hermes brain is not ready" in str(result.get("error") or "").lower()
    ):
        language = str(payload.get("language") or "es").lower()
        result = {"ok": True, "reply": (
            "I could not start Admira's text model yet. Your workspace and history are safe; try again shortly or contact Admira support. You may connect your own ChatGPT account at any time with /conectar_chatgpt."
            if language.startswith("en") else
            "Todavía no pude iniciar el modelo de texto de Admira. Tu espacio y tu historial están seguros; inténtalo de nuevo en un momento o contacta a soporte. Puedes conectar tu propia cuenta de ChatGPT en cualquier momento con /conectar_chatgpt."
        )}
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
    user_id = str(payload.get("user_id") or "").strip()
    if not CHAT_ID_RE.fullmatch(user_id):
        raise ValueError("user_id must be a Telegram numeric ID")
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
        "user_id": user_id,
        "command": _command_name(message),
        "update_id": update_id,
        "session_key": f"agent:main:telegram:dm:{chat_id}",
        "_admira_trusted_chat_id": f"hosted:telegram:{chat_id}",
        "_admira_trusted_session_id": f"agent:main:telegram:dm:{chat_id}",
    }
    raw_image_access = payload.get("image_access") or {}
    if not isinstance(raw_image_access, dict):
        raise ValueError("image_access must be an object")
    if raw_image_access:
        route = str(raw_image_access.get("route") or "").strip()
        lifecycle_state = str(raw_image_access.get("lifecycle_state") or "").strip()
        if route not in {"central_sponsored", "personal_chatgpt", "blocked"}:
            raise ValueError("image access route is invalid")
        if lifecycle_state not in {
            "pending_claim", "trial", "trial_expired", "licensed", "suspended", "cancelled"
        }:
            raise ValueError("image access lifecycle state is invalid")
        sponsorship_ends_at = str(raw_image_access.get("image_sponsorship_ends_at") or "").strip()
        if len(sponsorship_ends_at) > 64 or sponsorship_ends_at and not re.fullmatch(r"[0-9T:+.Z-]{10,64}", sponsorship_ends_at):
            raise ValueError("image sponsorship timestamp is invalid")
        request["image_access"] = {
            "route": route,
            "lifecycle_state": lifecycle_state,
            "image_sponsorship_ends_at": sponsorship_ends_at,
            "central_ready": raw_image_access.get("central_ready") is True,
        }
    if images:
        request["image_paths"] = images
    raw_attachments = payload.get("attachments") or []
    if not isinstance(raw_attachments, list) or len(raw_attachments) > ATTACHMENT_LIMIT:
        raise ValueError(f"attachments must contain at most {ATTACHMENT_LIMIT} items")
    attachments = []
    for item in raw_attachments:
        if not isinstance(item, dict):
            raise ValueError("attachment must be an object")
        kind = str(item.get("kind") or "").strip().lower()
        path = str(item.get("path") or "").strip()
        mime_type = str(item.get("mime_type") or "").strip().lower()
        digest = str(item.get("sha256") or "").strip().lower()
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("attachment size must be an integer") from exc
        if kind not in ATTACHMENT_KINDS or not INBOUND_ATTACHMENT_RE.fullmatch(path):
            raise ValueError("attachment is outside the hosted Telegram inbox")
        if not 0 <= size <= ATTACHMENT_SIZE_LIMIT:
            raise ValueError("attachment exceeds the hosted size limit")
        if mime_type and (len(mime_type) > 120 or not re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", mime_type)):
            raise ValueError("attachment MIME type is invalid")
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("attachment digest is invalid")
        attachments.append({
            "kind": kind,
            "path": path,
            "mime_type": mime_type,
            "size": size,
            "sha256": digest,
        })
    if attachments:
        request["attachments"] = attachments
    return request


def _command_name(message: str) -> str:
    if not message.startswith("/"):
        return ""
    token = message.split(maxsplit=1)[0].lower()
    return token[1:].split("@", 1)[0]


def _session_generation(
    path: Path,
    chat_id: str,
    *,
    increment: bool = False,
    update_id: int | None = None,
) -> int:
    try:
        details = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(details.st_mode)
            or details.st_size > 256 * 1024
        ):
            raise ValueError("invalid session generation ledger")
        values = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        values = {}
    if not isinstance(values, dict):
        values = {}
    key = str(chat_id)
    stored = values.get(key)
    if isinstance(stored, dict):
        raw_generation = stored.get("generation") or 0
        last_reset_update_id = stored.get("last_reset_update_id")
    else:
        raw_generation = stored or 0
        last_reset_update_id = None
    try:
        generation = int(raw_generation)
    except (TypeError, ValueError):
        generation = 0
    if generation < 0 or generation > 1_000_000_000:
        generation = 0
    if last_reset_update_id is not None:
        try:
            last_reset_update_id = int(last_reset_update_id)
        except (TypeError, ValueError):
            last_reset_update_id = None
    if increment:
        # Broker and database retries may execute the same Telegram update more
        # than once. Rotate the conversation exactly once per durable update,
        # while retaining compatibility with support/CLI calls that have no ID.
        if update_id is None or last_reset_update_id != update_id:
            generation += 1
        values[key] = {
            "generation": generation,
            "last_reset_update_id": update_id,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(values, handle, separators=(",", ":"))
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
    return generation


def _public_runtime_result(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        return _error("runtime_protocol_error")
    reply = str(raw.get("reply") or raw.get("final_response") or "").strip()
    result: dict[str, object] = {
        "ok": bool(raw.get("ok")) and bool(reply),
        "reply": reply,
        "media_paths": MEDIA_RE.findall(reply),
    }
    if raw.get("control_action") == "complete_reset":
        result["control_action"] = "complete_reset"
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
    generation_file = root / "runtime" / "telegram_session_generations.json"
    command_name = str(request.get("command") or "")
    generation = _session_generation(
        generation_file,
        str(request["chat_id"]),
        increment=command_name in {"nuevo", "new", "reset", "restart"},
        update_id=request.get("update_id") if isinstance(request.get("update_id"), int) else None,
    )
    request["session_key"] = f"agent:main:telegram:dm:{request['chat_id']}:g{generation}"
    request["_admira_trusted_session_id"] = request["session_key"]
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
