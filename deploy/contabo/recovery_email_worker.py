#!/usr/bin/env python3
"""Provider-neutral worker for the recovery email outbox.

The database contains only an opaque, authenticated ciphertext.  Decryption
and transport are injected so this module has no SMTP implementation,
provider SDK, or credential handling.  In particular, recovery addresses and
OTPs are never included in logs, exceptions, or result objects.
"""

from __future__ import annotations

import random
import re
import uuid
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol, Sequence


TEMPLATE_CODE = "telegram_recovery_otp"
DELIVERY_REF = "sealed-envelope://v1"
ALLOWED_ERROR_CODES = frozenset({
    "provider_unavailable", "provider_rejected", "timeout", "internal_error",
})


@dataclass(frozen=True)
class RecoveryEmailItem:
    """One leased row returned by ``claim_recovery_email_outbox``."""

    outbox: str
    challenge: str
    request_id: str
    delivery_ref: str
    template: str
    ciphertext: bytes
    key_version: str
    attempts: int
    lease: str


class RecoveryEmailStore(Protocol):
    def claim_recovery_email_outbox(self, *, worker_id: str, limit: int) -> Sequence[RecoveryEmailItem]: ...

    def ack_recovery_email_outbox(
        self, item: RecoveryEmailItem, *, success: bool,
        error_code: str = "", retry_after_seconds: int = 60,
        max_attempts: int = 5,
    ) -> bool: ...


class RecoveryEmailTransport(Protocol):
    def send(self, recipient: str, subject: str, text: str) -> object: ...


class RecoveryEmailError(RuntimeError):
    """A redacted, non-sensitive processing failure."""


class ProviderError(Exception):
    """Optional transport exception contract for stable retry classification."""

    def __init__(self, code: str = "provider_unavailable", retry_after: int | None = None) -> None:
        super().__init__("recovery email provider failure")
        self.error_code = code
        self.retry_after = retry_after


_REQUEST_ID = re.compile(r"^[0-9a-fA-F-]{36}$")
_OTP = re.compile(r"^[0-9]{6}$")


def _retry_delay(attempts: int, *, rng: random.Random | None = None) -> int:
    maximum = min(900, 5 * (2 ** min(max(0, attempts), 20)))
    return max(1, int((rng or random).uniform(0, maximum)))


def _decode_result(value: Mapping[str, object]) -> tuple[str, str, str]:
    """Validate the decryptor result while keeping all invalid values private."""
    try:
        request_id = value["request_id"]
        email = value["email"]
        otp = value["otp"]
        if (
            not isinstance(request_id, str)
            or not _REQUEST_ID.fullmatch(request_id)
            or str(uuid.UUID(request_id)) != request_id.lower()
        ):
            raise ValueError
        if not isinstance(email, str) or not email or any(ord(c) < 0x20 for c in email):
            raise ValueError
        if not isinstance(otp, str) or not _OTP.fullmatch(otp):
            raise ValueError
        return request_id, email, otp
    except Exception as exc:
        raise RecoveryEmailError("recovery envelope is invalid") from exc


def recovery_email_text(request_id: str, otp: str) -> str:
    """Render the fixed Spanish template; the request id is not user identity."""
    return (
        "Hola,\n\n"
        "Recibimos una solicitud para recuperar tu espacio privado de Admira IA.\n"
        "Escribe este comando en Telegram para continuar:\n\n"
        f"/codigo {request_id} {otp}\n\n"
        "Este código vence pronto y solo puede usarse una vez. Si no hiciste "
        "esta solicitud, ignora este mensaje."
    )


class RecoveryEmailWorker:
    def __init__(
        self,
        store: RecoveryEmailStore,
        transport: RecoveryEmailTransport,
        decrypt_delivery: Callable[[str, bytes], Mapping[str, object]],
        *,
        worker_id: str = "recovery-email-worker",
        expected_key_version: str = "v1",
        rng: random.Random | None = None,
        max_attempts: int = 5,
    ) -> None:
        if not worker_id or not isinstance(expected_key_version, str) or not expected_key_version:
            raise ValueError("invalid recovery email worker configuration")
        if max_attempts < 1 or max_attempts > 20:
            raise ValueError("invalid recovery email worker configuration")
        self.store = store
        self.transport = transport
        self.decrypt_delivery = decrypt_delivery
        self.worker_id = worker_id
        self.expected_key_version = expected_key_version
        self.rng = rng
        self.max_attempts = max_attempts

    def _ack_failure(self, item: RecoveryEmailItem, code: str, delay: int, *, terminal: bool = False) -> bool:
        # The SQL function accepts only this closed set; malformed envelopes
        # are made terminal by max_attempts=1 rather than retried forever.
        if code not in ALLOWED_ERROR_CODES:
            code = "internal_error"
        return self.store.ack_recovery_email_outbox(
            item, success=False, error_code=code,
            retry_after_seconds=max(1, min(86400, int(delay))),
            max_attempts=1 if terminal else self.max_attempts,
        )

    def process_once(self, *, limit: int = 1) -> dict[str, int]:
        sent = retried = rejected = 0
        for item in self.store.claim_recovery_email_outbox(worker_id=self.worker_id, limit=limit):
            try:
                if item.delivery_ref != DELIVERY_REF or item.template != TEMPLATE_CODE:
                    raise RecoveryEmailError("recovery email envelope metadata is invalid")
                if item.key_version != self.expected_key_version:
                    raise RecoveryEmailError("recovery email key version is invalid")
                try:
                    decrypted = self.decrypt_delivery(item.request_id, item.ciphertext)
                except Exception as exc:
                    raise RecoveryEmailError("recovery envelope is invalid") from exc
                request_id, recipient, otp = _decode_result(decrypted)
                if request_id.lower() != item.request_id.lower():
                    raise RecoveryEmailError("recovery envelope is invalid")
                self.transport.send(
                    recipient,
                    "Código para recuperar tu Admira IA",
                    recovery_email_text(request_id, otp),
                )
                if not self.store.ack_recovery_email_outbox(item, success=True):
                    raise RecoveryEmailError("recovery email lease lost")
                sent += 1
            except RecoveryEmailError:
                try:
                    self._ack_failure(item, "internal_error", 1, terminal=True)
                except Exception:
                    pass
                rejected += 1
            except Exception as exc:
                code = getattr(exc, "error_code", "")
                if code in {"rate_limited", "provider_rate_limited", "telegram_rate_limited"}:
                    code = "provider_unavailable"
                if code not in ALLOWED_ERROR_CODES:
                    code = "provider_unavailable"
                retry_after = getattr(exc, "retry_after", None)
                delay = retry_after if isinstance(retry_after, int) and retry_after > 0 else _retry_delay(item.attempts, rng=self.rng)
                try:
                    acked = self._ack_failure(item, code, delay)
                except Exception:
                    acked = False
                if acked:
                    retried += 1
        return {"sent": sent, "retried": retried, "rejected": rejected}


__all__ = [
    "ALLOWED_ERROR_CODES", "DELIVERY_REF", "ProviderError", "RecoveryEmailItem",
    "RecoveryEmailStore", "RecoveryEmailTransport", "RecoveryEmailWorker",
    "TEMPLATE_CODE", "recovery_email_text",
]
