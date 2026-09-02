"""Shared private Codex OAuth session handling for Hermes bridges."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path


def private_write(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=".auth.json.", dir=str(path.parent))
    try:
        os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        try:
            directory = os.open(str(path.parent), os.O_RDONLY)
        except OSError:
            directory = None
        if directory is not None:
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def auth_file():
    return Path(os.environ.get("HERMES_HOME", "")).expanduser() / "auth.json"


def load_auth():
    path = auth_file()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return path, {}
    return path, value if isinstance(value, dict) else {}


def valid_tokens(value):
    return (
        isinstance(value, dict)
        and isinstance(value.get("access_token"), str)
        and bool(value["access_token"].strip())
        and isinstance(value.get("refresh_token"), str)
        and bool(value["refresh_token"].strip())
    )


def prepare_hermes_oauth():
    path, state = load_auth()
    providers = state.get("providers")
    if not isinstance(providers, dict):
        providers = {}
        state["providers"] = providers
    root_tokens = state.get("tokens")
    provider = providers.get("openai-codex")
    if valid_tokens(root_tokens):
        # The root Codex session is canonical for a pooled slot.  Copying it
        # into Hermes' provider namespace lets the OAuth client read it
        # without using the Codex CLI, while preserving the root fields for
        # image jobs that still use their own isolated runtime.
        provider = dict(provider) if isinstance(provider, dict) else {}
        provider["tokens"] = dict(root_tokens)
        provider["last_refresh"] = state.get("last_refresh")
        providers["openai-codex"] = provider
        private_write(path, state)
        return path
    if isinstance(provider, dict) and valid_tokens(provider.get("tokens")):
        return path
    raise RuntimeError("provider_auth")


def mirror_back_to_root(path):
    try:
        state = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(state, dict):
        return
    providers = state.get("providers")
    provider = providers.get("openai-codex") if isinstance(providers, dict) else None
    tokens = provider.get("tokens") if isinstance(provider, dict) else None
    if not valid_tokens(tokens):
        return
    state["tokens"] = dict(tokens)
    state["last_refresh"] = provider.get("last_refresh") or state.get("last_refresh")
    private_write(path, state)


__all__ = [
    "auth_file",
    "load_auth",
    "mirror_back_to_root",
    "prepare_hermes_oauth",
    "private_write",
    "valid_tokens",
]
