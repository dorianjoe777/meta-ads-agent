#!/usr/bin/env python3
"""Small, provider-neutral SMTP transport for the recovery email worker.

This module is deliberately only a transport boundary.  It does not decrypt
recovery envelopes or retain addresses.  SMTP credentials are read from
operator-owned mode-0600 files immediately before a delivery and are never
included in an exception.
"""

from __future__ import annotations

import os
import smtplib
import socket
import ssl
import stat
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path
from typing import Callable

try:
    from .recovery_email_worker import ProviderError
except ImportError:  # pragma: no cover - container entrypoint import
    from recovery_email_worker import ProviderError  # type: ignore


_MAX_CREDENTIAL_BYTES = 4096
_SECURITY = frozenset(("starttls", "ssl"))


def _read_private_credential(path: str | os.PathLike[str]) -> str:
    """Read one bounded regular 0600 file without symlink/TOCTOU exposure."""
    target = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(target, flags)
    except OSError as exc:
        raise ValueError("SMTP credential file is invalid") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("SMTP credential file is invalid")
        if not 1 <= info.st_size <= _MAX_CREDENTIAL_BYTES:
            raise ValueError("SMTP credential file is invalid")
        value = os.read(fd, _MAX_CREDENTIAL_BYTES + 1)
        if len(value) > _MAX_CREDENTIAL_BYTES:
            raise ValueError("SMTP credential file is invalid")
        # Newline-terminated secret files are conventional; do not strip any
        # other byte, and reject NUL because it cannot be an SMTP credential.
        value = value.rstrip(b"\r\n")
        if not value or b"\x00" in value:
            raise ValueError("SMTP credential file is invalid")
        return value.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError("SMTP credential file is invalid") from exc
    finally:
        os.close(fd)


def _retry_after(exc: BaseException) -> int | None:
    value = getattr(exc, "retry_after", None)
    return value if isinstance(value, int) and value > 0 else None


def _provider_error(exc: BaseException) -> ProviderError:
    """Convert all SMTP failures to stable, redacted worker classifications."""
    retry_after = _retry_after(exc)
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return ProviderError("timeout", retry_after)
    if isinstance(exc, (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused)):
        return ProviderError("provider_rejected", retry_after)
    if isinstance(exc, smtplib.SMTPResponseException):
        code = getattr(exc, "smtp_code", 0)
        if isinstance(code, int) and code >= 500:
            return ProviderError("provider_rejected", retry_after)
        if isinstance(code, int) and 400 <= code < 500:
            return ProviderError("provider_unavailable", retry_after)
        return ProviderError("provider_unavailable", retry_after)
    if isinstance(exc, (OSError, smtplib.SMTPException)):
        return ProviderError("provider_unavailable", retry_after)
    return ProviderError("provider_unavailable", retry_after)


class SMTPRecoveryEmailTransport:
    """Send the worker's already-rendered UTF-8 text through SMTP.

    ``security`` is mandatory so an accidental plaintext SMTP configuration is
    impossible.  Credentials must be supplied together, or omitted together.
    ``smtp_factory`` is an injectable constructor for tests only.
    """

    def __init__(
        self,
        host: str,
        port: int,
        from_address: str,
        *,
        security: str,
        username_file: str | os.PathLike[str] | None = None,
        password_file: str | os.PathLike[str] | None = None,
        timeout: float = 20.0,
        tls_context: ssl.SSLContext | None = None,
        smtp_factory: Callable[..., smtplib.SMTP] | None = None,
    ) -> None:
        if not isinstance(host, str) or not host or any(ord(c) < 0x20 for c in host):
            raise ValueError("SMTP configuration is invalid")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError("SMTP configuration is invalid")
        if not isinstance(from_address, str) or not from_address or any(ord(c) < 0x20 for c in from_address):
            raise ValueError("SMTP configuration is invalid")
        if security not in _SECURITY:
            raise ValueError("SMTP security must be starttls or ssl")
        if (username_file is None) != (password_file is None):
            raise ValueError("SMTP credentials must be supplied together")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("SMTP configuration is invalid")
        self.host = host
        self.port = port
        self.from_address = from_address
        self.security = security
        self.username_file = username_file
        self.password_file = password_file
        self.timeout = float(timeout)
        self.tls_context = tls_context or ssl.create_default_context()
        self.smtp_factory = smtp_factory

    def send(self, recipient: str, subject: str, text: str) -> None:
        """Send one fixed worker message; all failures are redacted."""
        if not isinstance(recipient, str) or not recipient or any(ord(c) < 0x20 for c in recipient):
            raise ProviderError("provider_rejected")
        if not isinstance(subject, str) or not subject or any(ord(c) < 0x20 for c in subject):
            raise ProviderError("provider_rejected")
        if not isinstance(text, str):
            raise ProviderError("provider_rejected")
        smtp = None
        try:
            username = password = None
            if self.username_file is not None:
                username = _read_private_credential(self.username_file)
                password = _read_private_credential(self.password_file)  # type: ignore[arg-type]
            factory = self.smtp_factory
            if self.security == "ssl":
                smtp = (factory or smtplib.SMTP_SSL)(
                    self.host, self.port, timeout=self.timeout, context=self.tls_context
                )
            else:
                smtp = (factory or smtplib.SMTP)(self.host, self.port, timeout=self.timeout)
                smtp.ehlo()
                smtp.starttls(context=self.tls_context)
                smtp.ehlo()
            if username is not None:
                smtp.login(username, password)
            message = EmailMessage(policy=SMTP)
            message["From"] = self.from_address
            message["To"] = recipient
            message["Subject"] = subject
            message.set_content(text, charset="utf-8")
            smtp.send_message(message)
        except Exception as exc:
            if isinstance(exc, ProviderError):
                raise
            if isinstance(exc, ValueError):
                # Operator configuration errors are actionable locally and do
                # not represent a provider delivery attempt.
                raise
            raise _provider_error(exc) from None
        finally:
            if smtp is not None:
                try:
                    smtp.quit()
                except Exception:
                    pass


__all__ = ["SMTPRecoveryEmailTransport"]
