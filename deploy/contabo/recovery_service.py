"""Provider-neutral Telegram license recovery service.

The service is deliberately a small boundary around migration 009.  It owns
normalisation, HMAC derivation, and authenticated encryption of the OTP
delivery envelope; a database adapter owns transactions and rate limits.  No
mail provider, Telegram client, or raw recovery factor is persisted here.

``cryptography`` is intentionally an explicit runtime dependency.  Falling
back to home-grown crypto (or unauthenticated encoding) would make recovery
unsafe, so importing/constructing the service fails with a redacted error when
that library is absent.
"""

from __future__ import annotations

import base64
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

try:  # Package import in tests; top-level import in the control image.
    from .recovery_identity import (
        email_digest,
        generate_otp,
        license_digest,
        normalize_email,
        otp_digest,
        read_private_hmac_key,
        validate_license,
    )
except ImportError:  # pragma: no cover - exercised by the container entrypoint
    from recovery_identity import (  # type: ignore
        email_digest,
        generate_otp,
        license_digest,
        normalize_email,
        otp_digest,
        read_private_hmac_key,
        validate_license,
    )


class RecoveryDependencyError(RuntimeError):
    """Required authenticated-encryption dependency is unavailable."""


class RecoveryInputError(ValueError):
    """A malformed request; its message never includes a recovery factor."""


class RecoveryDatabase(Protocol):
    def begin_telegram_recovery(
        self, request_id: uuid.UUID, bot_id: str, chat_id: str, user_id: str,
        email_hmac_hex: str, license_hmac_hex: str, otp_hash_hex: str,
        otp_ciphertext: bytes, delivery_key_version: str,
    ) -> Any: ...

    def confirm_telegram_recovery(
        self, request_id: uuid.UUID, bot_id: str, chat_id: str, user_id: str,
        otp_hash_hex: str,
    ) -> Any: ...

    def enqueue_public_reply(
        self, request_id: uuid.UUID, bot_id: str, chat_id: str, user_id: str,
        template_code: str,
    ) -> Any: ...


@dataclass(frozen=True)
class RecoveryCommand:
    command: str
    argument: str


class RecoveryEnvelopeCipher:
    """Authenticated email-intent envelope without database/HMAC authority."""

    def __init__(self, envelope_key: bytes) -> None:
        if not isinstance(envelope_key, bytes) or len(envelope_key) not in (16, 24, 32):
            raise RecoveryInputError("recovery configuration is invalid")
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:  # pragma: no cover - depends on deployment image
            raise RecoveryDependencyError("authenticated encryption dependency unavailable") from exc
        self._aesgcm = AESGCM(envelope_key)

    def encrypt(self, request_id: uuid.UUID, email: str, otp: str) -> bytes:
        payload = json.dumps({
            "v": 1, "request_id": str(request_id), "email": email, "otp": otp,
        }, separators=(",", ":")).encode("utf-8")
        nonce = __import__("secrets").token_bytes(12)
        ciphertext = self._aesgcm.encrypt(
            nonce, payload, str(request_id).encode("ascii")
        )
        return nonce + ciphertext

    def decrypt(self, request_id: uuid.UUID | str, envelope: bytes) -> dict[str, str]:
        try:
            rid = uuid.UUID(str(request_id))
            if not isinstance(envelope, bytes) or len(envelope) < 29:
                raise ValueError
            raw = self._aesgcm.decrypt(
                envelope[:12], envelope[12:], str(rid).encode("ascii")
            )
            value = json.loads(raw.decode("utf-8"))
            if value.get("v") != 1 or value.get("request_id") != str(rid):
                raise ValueError
            email = value.get("email")
            otp = value.get("otp")
            if not isinstance(email, str) or normalize_email(email) != email:
                raise ValueError
            if not isinstance(otp, str) or not re.fullmatch(r"[0-9]{6}", otp):
                raise ValueError
            return {"request_id": str(rid), "email": email, "otp": otp}
        except Exception as exc:
            raise RecoveryInputError("recovery envelope is invalid") from exc


_CHAT_ID = re.compile(r"^-?[0-9]{1,32}$")
_USER_ID = re.compile(r"^[0-9]{1,32}$")
_BOT_ID = re.compile(r"^[0-9]{1,32}$")
_COMMAND = re.compile(r"^/(recuperar|codigo)(?:@[A-Za-z0-9_]{1,64})?(?:[ \t]+([^\r\n]*))?$")
_REQUEST_NAMESPACE = uuid.UUID("692f71a8-b146-4f79-9e4f-c81d3987d04b")


def parse_recovery_command(text: str) -> RecoveryCommand | None:
    """Parse only the two recovery commands, never arbitrary bot input."""
    if not isinstance(text, str):
        return None
    match = _COMMAND.fullmatch(text.strip())
    if not match:
        return None
    argument = (match.group(2) or "").strip()
    if any(ord(char) < 0x20 or ord(char) == 0x7f for char in argument):
        return None
    return RecoveryCommand("/" + match.group(1), argument)


def _safe_id(value: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value.strip()):
        raise RecoveryInputError("recovery request is invalid")
    return value.strip()


def read_private_envelope_key(path: str) -> bytes:
    """Read one mode-0600 base64 AES key without following symlinks."""
    try:
        encoded = read_private_hmac_key(path)
        decoded = base64.b64decode(encoded, validate=True)
        if len(decoded) != 32:
            raise ValueError
        return decoded
    except Exception as exc:
        raise RecoveryInputError("recovery configuration is invalid") from exc


class TelegramRecoveryService:
    """Create and confirm one-time recovery challenges through an adapter."""

    def __init__(self, db: RecoveryDatabase, hmac_key: bytes, envelope_key: bytes,
                 *, envelope_key_version: str = "v1") -> None:
        if not isinstance(hmac_key, bytes) or len(hmac_key) < 32:
            raise RecoveryInputError("recovery configuration is invalid")
        if not isinstance(envelope_key_version, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", envelope_key_version):
            raise RecoveryInputError("recovery configuration is invalid")
        self._envelopes = RecoveryEnvelopeCipher(envelope_key)
        self._db = db
        self._hmac_key = hmac_key
        self._key_version = envelope_key_version

    @staticmethod
    def _public_result(value: Any, request_id: uuid.UUID) -> dict[str, Any]:
        """Reduce adapter output to non-sensitive fields only."""
        outcome = "recovery_pending"
        if isinstance(value, dict) and value.get("public_outcome") == "recovery_pending":
            outcome = "recovery_pending"
        return {"request_id": str(request_id), "public_outcome": outcome}

    def _encrypt_delivery(self, request_id: uuid.UUID, email: str, otp: str) -> bytes:
        # The normalized address is included only inside the authenticated
        # envelope. PostgreSQL receives ciphertext; a matching contact HMAC is
        # required before migration 009 queues it for the email worker.
        return self._envelopes.encrypt(request_id, email, otp)

    def decrypt_delivery_envelope(self, request_id: uuid.UUID | str, envelope: bytes) -> dict[str, str]:
        """Decrypt one email intent for the delivery worker.

        The returned mapping is an in-memory provider input. Callers must not
        log or persist it and must bind it to the claimed request id.
        """
        return self._envelopes.decrypt(request_id, envelope)

    def begin(self, *, request_id: uuid.UUID | None = None, bot_id: str,
              chat_id: str, user_id: str, email: str, license_id: str) -> dict[str, Any]:
        bot = _safe_id(bot_id, _BOT_ID)
        chat = _safe_id(chat_id, _CHAT_ID)
        user = _safe_id(user_id, _USER_ID)
        try:
            canonical_email = normalize_email(email)
            canonical_license = validate_license(license_id)
        except ValueError as exc:
            raise RecoveryInputError("recovery request is invalid") from exc
        rid = request_id or uuid.uuid4()
        if not isinstance(rid, uuid.UUID):
            raise RecoveryInputError("recovery request is invalid")
        otp = generate_otp()
        encrypted = self._encrypt_delivery(rid, canonical_email, otp)
        self._db.begin_telegram_recovery(
            rid, bot, chat, user,
            email_digest(self._hmac_key, canonical_email).hex(),
            license_digest(self._hmac_key, canonical_license).hex(),
            otp_digest(self._hmac_key, str(rid), otp).hex(),
            encrypted, self._key_version,
        )
        return self._public_result({}, rid)

    def confirm(self, *, request_id: uuid.UUID | str, bot_id: str, chat_id: str,
                user_id: str, otp: str) -> dict[str, Any]:
        try:
            rid = uuid.UUID(str(request_id))
            if not isinstance(otp, str) or not re.fullmatch(r"[0-9]{6}", otp):
                raise ValueError
        except (ValueError, TypeError, AttributeError) as exc:
            raise RecoveryInputError("recovery request is invalid") from exc
        bot = _safe_id(bot_id, _BOT_ID)
        chat = _safe_id(chat_id, _CHAT_ID)
        user = _safe_id(user_id, _USER_ID)
        result = self._db.confirm_telegram_recovery(
            rid, bot, chat, user, otp_digest(self._hmac_key, str(rid), otp).hex()
        )
        completed = bool(isinstance(result, dict) and result.get("completed") is True)
        return {"completed": completed, "public_outcome": "recovery_completed" if completed else "recovery_failed"}

    @staticmethod
    def request_id_for_update(bot_id: str, update_id: int) -> uuid.UUID:
        """Return an idempotency key stable across Telegram poll retries."""
        bot = _safe_id(bot_id, _BOT_ID)
        if not isinstance(update_id, int) or isinstance(update_id, bool) or update_id < 0:
            raise RecoveryInputError("recovery request is invalid")
        return uuid.uuid5(_REQUEST_NAMESPACE, f"{bot}:{update_id}")

    def _public_reply(self, request_id: uuid.UUID, *, bot_id: str, chat_id: str,
                      user_id: str, template_code: str) -> dict[str, Any]:
        self._db.enqueue_public_reply(request_id, bot_id, chat_id, user_id, template_code)
        return {"request_id": str(request_id), "public_outcome": template_code}

    def handle_unbound(self, *, update_id: int, bot_id: str, chat_id: str,
                       user_id: str, text: str) -> dict[str, Any] | None:
        """Handle only recovery commands from one unbound private chat.

        Structurally invalid factors produce a durable generic instruction or
        failure reply. Database failures propagate so the Telegram cursor is
        not advanced before the response/challenge is durable.
        """
        command = parse_recovery_command(text)
        if command is None:
            return None
        bot = _safe_id(bot_id, _BOT_ID)
        chat = _safe_id(chat_id, _CHAT_ID)
        user = _safe_id(user_id, _USER_ID)
        event_id = self.request_id_for_update(bot, update_id)
        parts = command.argument.split()
        if command.command == "/recuperar":
            if len(parts) != 2:
                return self._public_reply(
                    event_id, bot_id=bot, chat_id=chat, user_id=user,
                    template_code="recovery_instructions",
                )
            try:
                return self.begin(
                    request_id=event_id, bot_id=bot, chat_id=chat, user_id=user,
                    email=parts[0], license_id=parts[1],
                )
            except RecoveryInputError:
                return self._public_reply(
                    event_id, bot_id=bot, chat_id=chat, user_id=user,
                    template_code="recovery_instructions",
                )
        if len(parts) != 2:
            return self._public_reply(
                event_id, bot_id=bot, chat_id=chat, user_id=user,
                template_code="recovery_failed",
            )
        try:
            return self.confirm(
                request_id=parts[0], bot_id=bot, chat_id=chat, user_id=user,
                otp=parts[1],
            )
        except RecoveryInputError:
            return self._public_reply(
                event_id, bot_id=bot, chat_id=chat, user_id=user,
                template_code="recovery_failed",
            )


__all__ = [
    "RecoveryCommand", "RecoveryDatabase", "RecoveryDependencyError",
    "RecoveryEnvelopeCipher", "RecoveryInputError", "TelegramRecoveryService",
    "parse_recovery_command", "read_private_envelope_key",
]
