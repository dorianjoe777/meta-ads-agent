"""Provider-neutral recovery identity primitives.

This module deliberately does not send mail, encrypt data, select a provider,
or retain raw recovery factors.  ``email-v1`` is the canonical identity form:
Unicode NFKC is applied, surrounding whitespace is trimmed, the local part is
restricted to common ASCII mailbox syntax, and the domain is lower-cased after
IDNA conversion.  Control characters, internal whitespace, empty/consecutive
dots, invalid labels, and lengths beyond the usual mailbox limits are rejected.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import stat
import unicodedata
from pathlib import Path


LICENSE_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
OTP_RE = re.compile(r"^[0-9]{6}$")
_LOCAL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+$")
_CONTROL_OR_SPACE = re.compile(r"[\x00-\x20\x7f]|\s")
_MAX_KEY_BYTES = 512
_MIN_KEY_BYTES = 32
_OTP_DIGITS = 6
_DOMAIN_EMAIL = b"admira/recovery/email-v1\0"
_DOMAIN_LICENSE = b"admira/recovery/license-v1\0"
_DOMAIN_OTP = b"admira/recovery/otp-v1\0"


def _invalid() -> ValueError:
    """Return an error that never contains the rejected secret/factor."""
    return ValueError("recovery identity is invalid")


def normalize_email(value: str) -> str:
    """Return the canonical ``email-v1`` form or raise a redacted error."""
    try:
        text = unicodedata.normalize("NFKC", str(value)).strip()
    except Exception as exc:
        raise _invalid() from exc
    if not text or len(text) > 254 or _CONTROL_OR_SPACE.search(text):
        raise _invalid()
    if text.count("@") != 1:
        raise _invalid()
    local, domain = text.rsplit("@", 1)
    if not 1 <= len(local) <= 64 or not _LOCAL_RE.fullmatch(local):
        raise _invalid()
    if local.startswith(".") or local.endswith(".") or ".." in local:
        raise _invalid()
    try:
        ascii_domain = domain.encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError) as exc:
        raise _invalid() from exc
    labels = ascii_domain.split(".")
    if not ascii_domain or len(ascii_domain) > 253 or len(labels) < 2 or any(
        not 1 <= len(label) <= 63
        or label.startswith("-")
        or label.endswith("-")
        or not re.fullmatch(r"[a-z0-9-]+", label)
        for label in labels
    ):
        raise _invalid()
    return f"{local.lower()}@{ascii_domain}"


def validate_license(value: str) -> str:
    """Validate the exact provider-admin license format, without echoing it."""
    try:
        text = str(value).strip()
    except Exception as exc:
        raise _invalid() from exc
    if not LICENSE_RE.fullmatch(text):
        raise _invalid()
    return text


def read_private_hmac_key(path: str | Path) -> bytes:
    """Read a bounded mode-0600 regular key without following symlinks."""
    target = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(target, flags)
    except OSError as exc:
        raise _invalid() from exc
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or not _MIN_KEY_BYTES <= info.st_size <= _MAX_KEY_BYTES
        ):
            raise _invalid()
        data = os.read(fd, _MAX_KEY_BYTES + 1).strip()
        if not _MIN_KEY_BYTES <= len(data) <= _MAX_KEY_BYTES:
            raise _invalid()
        return data
    except OSError as exc:
        raise _invalid() from exc
    finally:
        os.close(fd)


def _hmac_digest(key: bytes, domain: bytes, *parts: str) -> bytes:
    if not isinstance(key, bytes) or not _MIN_KEY_BYTES <= len(key) <= _MAX_KEY_BYTES:
        raise _invalid()
    # Length-prefix each field so concatenation cannot create cross-field
    # collisions (for example, scope="ab", otp="c" vs scope="a", otp="bc").
    payload = bytearray(domain)
    for part in parts:
        encoded = str(part).encode("utf-8")
        payload.extend(len(encoded).to_bytes(4, "big"))
        payload.extend(encoded)
    return hmac.new(key, bytes(payload), hashlib.sha256).digest()


def email_digest(key: bytes, email: str) -> bytes:
    return _hmac_digest(key, _DOMAIN_EMAIL, normalize_email(email))


def license_digest(key: bytes, license_id: str) -> bytes:
    return _hmac_digest(key, _DOMAIN_LICENSE, validate_license(license_id))


def generate_otp() -> str:
    return f"{secrets.randbelow(10 ** _OTP_DIGITS):0{_OTP_DIGITS}d}"


def otp_digest(key: bytes, request_scope: str, otp: str) -> bytes:
    if not isinstance(request_scope, str) or not request_scope or _CONTROL_OR_SPACE.search(request_scope):
        raise _invalid()
    if not isinstance(otp, str) or not OTP_RE.fullmatch(otp):
        raise _invalid()
    return _hmac_digest(key, _DOMAIN_OTP, request_scope, otp)


def verify_otp(key: bytes, request_scope: str, otp: str, expected_digest: bytes) -> bool:
    """Constant-time verify an OTP for exactly one request scope."""
    try:
        candidate = otp_digest(key, request_scope, otp)
        return isinstance(expected_digest, bytes) and hmac.compare_digest(candidate, expected_digest)
    except (TypeError, ValueError):
        return False


__all__ = [
    "email_digest",
    "generate_otp",
    "license_digest",
    "normalize_email",
    "otp_digest",
    "read_private_hmac_key",
    "validate_license",
    "verify_otp",
]
