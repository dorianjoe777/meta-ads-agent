#!/usr/bin/env python3
"""Pure parsing/routing boundary for the shared hosted Telegram bot.

Ingress never calls Hermes. It resolves the private chat, stages attachments
through an injected token-owning adapter, and durably enqueues one sanitized
update. Runtime work and Telegram delivery happen in separate workers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Protocol, Sequence

MAX_INPUT_TEXT = 5000
MAX_MEDIA_BYTES = 50 * 1024 * 1024
ID_RE = re.compile(r"^-?[0-9]{1,32}$")
FILE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,256}$")
SAFE_FILE_RE = re.compile(r"^[^/\\\x00]{1,180}$")


@dataclass(frozen=True)
class IncomingMedia:
    kind: str
    file_id: str
    file_name: str = ""
    mime_type: str = ""
    file_size: int = 0


@dataclass(frozen=True)
class StagedMedia:
    kind: str
    ref: str
    file_name: str
    mime_type: str
    size: int
    sha256: str


@dataclass(frozen=True)
class TelegramMessage:
    update_id: int
    bot_id: str
    chat_id: str
    user_id: str
    text: str
    command: str | None = None
    command_args: str = ""
    media: tuple[IncomingMedia, ...] = ()


class TenantResolver(Protocol):
    def resolve(self, *, bot_id: str, chat_id: str, user_id: str) -> str | None: ...
    def claim(self, *, bot_id: str, chat_id: str, user_id: str, token: str) -> str | None: ...


class MediaStager(Protocol):
    def stage(self, media: IncomingMedia) -> StagedMedia: ...


class InboxStore(Protocol):
    def ingest(self, *, message: TelegramMessage, tenant_id: str, payload: dict[str, object]) -> bool: ...


def _numeric(value: Any, label: str) -> str:
    text = str(value).strip()
    if not ID_RE.fullmatch(text):
        raise ValueError(f"{label} must be a Telegram numeric ID")
    return text


def _command(text: str) -> tuple[str | None, str]:
    if not text.startswith("/"):
        return None, ""
    token, _, args = text.partition(" ")
    name = token[1:].split("@", 1)[0].lower()
    if not re.fullmatch(r"[a-z0-9_]{1,64}", name):
        return None, ""
    return name, args.strip()


def _media(kind: str, raw: object, *, default_name: str = "") -> IncomingMedia | None:
    if not isinstance(raw, dict) or not raw.get("file_id"):
        return None
    file_id = str(raw.get("file_id") or "")
    if not FILE_ID_RE.fullmatch(file_id):
        raise ValueError("invalid Telegram file_id")
    size = int(raw.get("file_size") or 0)
    if size < 0 or size > MAX_MEDIA_BYTES:
        raise ValueError("Telegram media exceeds the hosted limit")
    name = str(raw.get("file_name") or default_name).strip()
    if name and not SAFE_FILE_RE.fullmatch(name):
        name = default_name
    mime = str(raw.get("mime_type") or "")[:120]
    return IncomingMedia(kind, file_id, name[:180], mime, size)


def parse_update(raw: object, *, bot_id: str) -> TelegramMessage | None:
    if not isinstance(raw, dict):
        raise ValueError("update must be a JSON object")
    try:
        update_id = int(raw["update_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("update_id must be a non-negative integer") from exc
    if update_id < 0:
        raise ValueError("update_id must be non-negative")
    message = raw.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    sender = message.get("from")
    if not isinstance(chat, dict) or not isinstance(sender, dict):
        raise ValueError("message chat and sender are required")
    # One buyer owns one private workspace. Group chats would let another
    # member drive that buyer's Meta account, so they are never routed.
    if str(chat.get("type") or "") != "private":
        return None
    chat_id = _numeric(chat.get("id"), "chat_id")
    user_id = _numeric(sender.get("id"), "user_id")
    text = str(message.get("text") or message.get("caption") or "").strip()
    if len(text) > MAX_INPUT_TEXT:
        raise ValueError(f"text exceeds {MAX_INPUT_TEXT} characters")
    media: list[IncomingMedia] = []
    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        candidate = _media("photo", photos[-1], default_name="telegram-photo.jpg")
        if candidate:
            media.append(candidate)
    for kind in ("video", "animation", "document"):
        candidate = _media("video" if kind in {"video", "animation"} else "document", message.get(kind), default_name=f"telegram-{kind}.bin")
        if candidate:
            media.append(candidate)
    if len(media) > 4:
        raise ValueError("too many Telegram attachments")
    if not text and not media:
        return None
    command, args = _command(text)
    return TelegramMessage(update_id, str(bot_id), chat_id, user_id, text, command, args, tuple(media))


def sanitized_payload(message: TelegramMessage, staged: Sequence[StagedMedia]) -> dict[str, object]:
    return {
        "message": message.text,
        "language": "es",
        "command": message.command or "",
        "command_args": message.command_args,
        "media": [asdict(item) for item in staged],
    }


class TelegramIngress:
    def __init__(self, resolver: TenantResolver, inbox: InboxStore, media: MediaStager):
        self.resolver, self.inbox, self.media = resolver, inbox, media

    def handle_update(self, raw: object, *, bot_id: str) -> dict[str, object]:
        message = parse_update(raw, bot_id=bot_id)
        if message is None:
            return {"status": "ignored"}
        tenant_id = self.resolver.resolve(bot_id=message.bot_id, chat_id=message.chat_id, user_id=message.user_id)
        if not tenant_id and message.command == "start" and message.command_args:
            # The database consumes this one-time deep-link token. It is never
            # persisted in the inbox or exposed to the tenant model.
            tenant_id = self.resolver.claim(
                bot_id=message.bot_id,
                chat_id=message.chat_id,
                user_id=message.user_id,
                token=message.command_args,
            )
            if tenant_id:
                return {"status": "claimed", "tenant_id": tenant_id, "update_id": message.update_id}
        if not tenant_id:
            return {"status": "unbound", "update_id": message.update_id}
        staged: list[StagedMedia] = []
        try:
            for item in message.media:
                staged.append(self.media.stage(item))
            inserted = self.inbox.ingest(
                message=message,
                tenant_id=tenant_id,
                payload=sanitized_payload(message, staged),
            )
        except Exception as exc:
            return {
                "status": "failed", "tenant_id": tenant_id,
                "update_id": message.update_id, "error_code": type(exc).__name__[:80],
            }
        return {
            "status": "queued" if inserted else "duplicate",
            "tenant_id": tenant_id,
            "update_id": message.update_id,
        }
