#!/usr/bin/env python3
"""Small, fail-closed pool for operator-owned Codex image accounts.

The pool deliberately knows nothing about tenants or Telegram.  Each logical
account owns an isolated ``CODEX_HOME`` and can run at most one provider job at
a time.  Provider errors are reduced to safe categories before they leave this
module; prompts, credentials and CLI output are never retained or returned.
"""

from __future__ import annotations

import inspect
import os
import re
import stat
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


_ACCOUNT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_CATEGORIES = {
    "codex_usage_limit", "chatgpt_images_limit", "provider_auth",
    "provider_unavailable", "provider_timeout", "provider_failed", "unknown",
}
_DEFAULT_COOLDOWNS = {
    "codex_usage_limit": 300.0,
    "chatgpt_images_limit": 900.0,
    "provider_auth": 300.0,
    "provider_unavailable": 30.0,
    "provider_timeout": 30.0,
    "provider_failed": 15.0,
    "unknown": 15.0,
}
_SAFE_RESULT_KEYS = {"image_path", "path", "asset_id", "preview_url", "output_ref", "sha256", "size"}


class AccountPoolConfigError(ValueError):
    """Raised when an account definition is unsafe or outside pool limits."""


@dataclass(frozen=True)
class CodexAccount:
    account_id: str
    codex_home: Path
    auth_path: Path


@dataclass
class _Slot:
    account: CodexAccount
    lock: threading.Lock = field(default_factory=threading.Lock)
    cooldown_until: dict[str, float] = field(default_factory=dict)
    last_used: float = 0.0


def _reject_symlink_components(path: Path) -> None:
    """Reject the configured target when it is a symlink.

    Parent directories may be platform aliases (for example macOS's ``/var``
    link); rejecting those would make otherwise private absolute homes
    unusable.  The security boundary is the configured home and auth inode.
    """
    try:
        details = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(details.st_mode):
        raise AccountPoolConfigError("account_path_symlink")


def _private_file(path: Path, *, expected_parent: Path | None = None) -> None:
    _reject_symlink_components(path)
    details = path.lstat()
    if not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) & 0o077:
        raise AccountPoolConfigError("auth_file_not_private")
    if expected_parent is not None and path.parent != expected_parent:
        raise AccountPoolConfigError("auth_file_outside_home")


def _private_home(path: Path) -> None:
    _reject_symlink_components(path)
    details = path.lstat()
    if not stat.S_ISDIR(details.st_mode) or stat.S_IMODE(details.st_mode) & 0o077:
        raise AccountPoolConfigError("codex_home_not_private")


def validate_account_definition(raw: Mapping[str, Any]) -> CodexAccount:
    """Validate one account without reading ``auth.json`` contents."""
    if not isinstance(raw, Mapping):
        raise AccountPoolConfigError("account_definition_invalid")
    account_id = str(raw.get("id") or raw.get("account_id") or "")
    if not _ACCOUNT_ID.fullmatch(account_id):
        raise AccountPoolConfigError("account_id_invalid")
    raw_home = str(raw.get("codex_home") or raw.get("home") or "").strip()
    if not raw_home or not os.path.isabs(raw_home):
        raise AccountPoolConfigError("codex_home_must_be_absolute")
    home = Path(raw_home)
    _private_home(home)
    auth_raw = str(raw.get("auth_path") or (home / "auth.json")).strip()
    auth = Path(auth_raw)
    if not auth.is_absolute():
        raise AccountPoolConfigError("auth_path_must_be_absolute")
    _private_file(auth, expected_parent=home)
    return CodexAccount(account_id, home, auth)


def _category(result: object) -> str:
    if isinstance(result, Mapping):
        value = result.get("failure_category") or result.get("category")
        if isinstance(value, str) and value in _CATEGORIES:
            return value
        error_type = str(result.get("error_type") or "").lower()
        error = str(result.get("error") or "").lower()
        if "timeout" in error_type or "timeout" in error:
            return "provider_timeout"
        if "auth" in error_type or "unauthorized" in error or "not authenticated" in error:
            return "provider_auth"
        if "chatgpt" in error and "limit" in error:
            return "chatgpt_images_limit"
        if "codex" in error and ("limit" in error or "quota" in error):
            return "codex_usage_limit"
        if "unavailable" in error or "connection" in error:
            return "provider_unavailable"
    return "unknown"


def _retry_hint(result: object) -> float | None:
    if not isinstance(result, Mapping):
        return None
    for key in ("retry_after_seconds", "retry_seconds", "retry_after"):
        value = result.get(key)
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            continue
        if 0 <= seconds <= 86400:
            return seconds
    return None


class CentralCodexAccountPool:
    """Thread-safe account selector with bounded, one-attempt-per-slot jobs."""

    def __init__(self, accounts: Sequence[Mapping[str, Any] | CodexAccount], *,
                 provider: Callable[..., object] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 cooldowns: Mapping[str, float] | None = None):
        if not 2 <= len(accounts) <= 8:
            raise AccountPoolConfigError("account_count_must_be_between_2_and_8")
        parsed: list[CodexAccount] = []
        seen: set[str] = set()
        for raw in accounts:
            account = raw if isinstance(raw, CodexAccount) else validate_account_definition(raw)
            if account.account_id in seen:
                raise AccountPoolConfigError("duplicate_account_id")
            seen.add(account.account_id)
            parsed.append(account)
        self._slots = [_Slot(account) for account in parsed]
        self._provider = provider or self._default_provider
        self._clock = clock
        self._cooldowns = {**_DEFAULT_COOLDOWNS, **dict(cooldowns or {})}
        self._selection_lock = threading.Lock()
        self._cursor = 0

    @property
    def accounts(self) -> tuple[CodexAccount, ...]:
        return tuple(slot.account for slot in self._slots)

    def _default_provider(self, prompt: str, *, codex_home: Path, timeout: int,
                          model: str | None, output_root: Path | None,
                          output_name: str, reference_image_paths: Sequence[str],
                          purpose: str) -> object:
        from codex_brand_guides import call_codex_image_cli_direct, classify_image_failure
        result = call_codex_image_cli_direct(
            prompt, timeout=timeout, model=model, output_root=output_root,
            output_name=output_name, reference_image_paths=reference_image_paths,
            purpose=purpose, codex_home=codex_home,
        )
        if isinstance(result, Mapping) and result.get("ok") is not True:
            # Reduce the provider response immediately.  In particular, do
            # not hand stdout/stderr/prompt-shaped error text to the pool or
            # any caller.  The classifier sees it only transiently.
            category = classify_image_failure(
                result.get("error", ""), result.get("error_type", ""),
                backend="codex-cli-direct", provider=result.get("provider", ""),
            )
            safe: dict[str, Any] = {"ok": False, "failure_category": category}
            for key in ("retry_after_seconds", "retry_seconds", "retry_after"):
                if key in result:
                    safe[key] = result[key]
                    break
            return safe
        return result

    def _ordered_slots(self, now: float) -> list[_Slot]:
        with self._selection_lock:
            start = self._cursor
            self._cursor = (self._cursor + 1) % len(self._slots)
        return [self._slots[(start + offset) % len(self._slots)] for offset in range(len(self._slots))]

    def generate(self, prompt: str, *, timeout: int = 270, model: str | None = None,
                 output_root: Path | None = None, output_name: str = "creative",
                 reference_image_paths: Sequence[str] = (), purpose: str = "ad_creative") -> dict[str, Any]:
        """Try each account at most once; usage-limit failures also fall back."""
        started = self._clock()
        attempted = 0
        last_category = "provider_unavailable"
        for slot in self._ordered_slots(started):
            if not slot.lock.acquire(blocking=False):
                continue
            try:
                now = self._clock()
                # A slot's cooldown is category-specific. Unknown failures do
                # not suppress a different category's future attempt.
                if any(until > now for until in slot.cooldown_until.values()):
                    continue
                attempted += 1
                slot.last_used = now
                try:
                    result = self._provider(
                        prompt, codex_home=slot.account.codex_home, timeout=timeout,
                        model=model, output_root=output_root, output_name=output_name,
                        reference_image_paths=tuple(reference_image_paths), purpose=purpose,
                    )
                except Exception:
                    result = None
                if isinstance(result, Mapping) and result.get("ok") is True:
                    safe = {key: result[key] for key in _SAFE_RESULT_KEYS if key in result}
                    safe.update({"ok": True, "account_id": slot.account.account_id,
                                 "duration_ms": int(max(0.0, (self._clock() - started) * 1000))})
                    return safe
                last_category = _category(result)
                hint = _retry_hint(result)
                slot.cooldown_until[last_category] = self._clock() + (
                    hint if hint is not None else max(0.0, float(self._cooldowns.get(last_category, 15.0)))
                )
            finally:
                slot.lock.release()
        return {
            "ok": False,
            "error_type": last_category,
            "failure_category": last_category,
            "attempted_accounts": attempted,
            "duration_ms": int(max(0.0, (self._clock() - started) * 1000)),
        }


__all__ = ["AccountPoolConfigError", "CodexAccount", "CentralCodexAccountPool", "validate_account_definition"]
