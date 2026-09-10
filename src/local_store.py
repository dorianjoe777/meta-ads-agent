"""Small shared helpers for local JSON state files."""
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def read_json(path, fallback):
    path = Path(path)
    if not path.exists():
        return fallback
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return fallback


def write_json(path, payload, *, ensure_ascii=True, indent=2):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=indent, ensure_ascii=ensure_ascii)


def write_private_json(path, payload, *, ensure_ascii=True, indent=2):
    write_json(path, payload, ensure_ascii=ensure_ascii, indent=indent)
    try:
        Path(path).chmod(0o600)
    except OSError:
        pass


def atomic_write_json(path, payload):
    """Replace shared cache/ledger state without exposing a half-written JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="." + path.name + ".", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
