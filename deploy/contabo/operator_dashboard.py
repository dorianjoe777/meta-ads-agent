#!/usr/bin/env python3
"""Private operator API for the hosted Admira control plane.

This is an internal, single-process service, not a public administration API.
Publish its container port on host loopback only and access it through SSH.
Provider credentials never enter responses, database parameters, or logs.
"""
from __future__ import annotations

import base64
import binascii
import fcntl
import hashlib
import hmac
import http.cookies
import ipaddress
import json
import math
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping

try:
    from gemini_pool_admin import _store
    from provider_admin import check_gemini_api_key, validate_gemini_key
except ImportError:
    from .gemini_pool_admin import _store
    from .provider_admin import check_gemini_api_key, validate_gemini_key


DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8791
DEFAULT_GEMINI_ROOT = Path("/etc/admira/gemini-pool")
DEFAULT_CODEX_ROOT = Path("/app/runtime/hermes/codex-auth-pool")
DEFAULT_PASSWORD_FILE = Path("/etc/admira/operator-password.hash")
MAX_BODY = 16 * 1024
MAX_OUTPUT = 8192
MAX_TOTAL_OUTPUT = 128 * 1024
MAX_AUTH_BYTES = 64 * 1024
MAX_PASSWORD_BYTES = 1024
MAX_SESSIONS = 128
MAX_CLIENTS = 1024
PBKDF2_ITERATIONS = 600_000
LOGIN_TTL = 12 * 60 * 60
LOGIN_JOB_TTL = 10 * 60
BOOTSTRAP_TTL = 10 * 60
JOB_RETENTION = 5 * 60
ACCOUNT_IDS = {"primary", "secondary"}
TERMINAL_PHASES = {"completed", "cancelled", "expired", "failed"}
COOKIE_NAME = "admira_operator"
DEVICE_URL = "https://auth.openai.com/codex/device"
ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


def _text_equal(left: str, right: str) -> bool:
    """compare_digest on bytes also accepts non-ASCII passwords safely."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def _safe_parents(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise RuntimeError("private_path_unavailable")
    for parent in path.parents:
        info = parent.lstat()
        # Permit root-owned system aliases such as macOS /var -> /private/var,
        # but never a caller-controlled symlink or writable non-sticky parent.
        if stat.S_ISLNK(info.st_mode):
            if info.st_uid != 0:
                raise RuntimeError("private_path_unavailable")
            info = parent.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0, os.geteuid()}:
            raise RuntimeError("private_path_unavailable")
        if info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX):
            raise RuntimeError("private_path_unavailable")


def _private_file(path: Path, *, max_bytes: int = 4096) -> str:
    _safe_parents(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError("operator_secret_unavailable") from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077
                or info.st_uid not in {0, os.geteuid()} or info.st_nlink != 1
                or info.st_size > max_bytes):
            raise RuntimeError("operator_secret_unavailable")
        data = os.read(fd, max_bytes + 1)
        if len(data) > max_bytes:
            raise RuntimeError("operator_secret_unavailable")
        return data.decode("utf-8").strip()
    except UnicodeError as exc:
        raise RuntimeError("operator_secret_unavailable") from exc
    finally:
        os.close(fd)


def _password_matches(password: str, encoded: str) -> bool:
    """Verify PBKDF2-SHA256 ``pbkdf2_sha256$iterations$salt$digest`` values."""
    try:
        if not isinstance(password, str) or len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
            return False
        scheme, iterations, salt, expected = encoded.split("$", 3)
        iterations = int(iterations)
        if scheme != "pbkdf2_sha256" or not 100_000 <= iterations <= 2_000_000:
            return False
        salt_b = base64.b64decode(salt.encode("ascii"), altchars=b"-_", validate=True)
        expected_b = base64.b64decode(expected.encode("ascii"), altchars=b"-_", validate=True)
        if not 16 <= len(salt_b) <= 64 or len(expected_b) != 32:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt_b, iterations)
        return hmac.compare_digest(actual, expected_b)
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        return False


def _safe_account(account: str) -> str:
    if not isinstance(account, str) or account not in ACCOUNT_IDS:
        raise ValueError("account_not_allowed")
    return account


def _safe_root(path: Path) -> Path:
    _safe_parents(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise RuntimeError("codex_pool_unavailable")
    if stat.S_IMODE(path.stat().st_mode) & 0o077 or path.stat().st_uid != os.geteuid():
        raise RuntimeError("codex_pool_unavailable")
    return path


def _safe_auth_path(root: Path, account: str) -> tuple[Path, Path]:
    root = _safe_root(root)
    home = root / _safe_account(account)
    if (home.is_symlink() or not home.is_dir() or stat.S_IMODE(home.stat().st_mode) & 0o077
            or home.stat().st_uid != os.geteuid()):
        raise RuntimeError("codex_account_unavailable")
    auth = home / "auth.json"
    if auth.is_symlink() or (auth.exists() and (not auth.is_file()
            or stat.S_IMODE(auth.stat().st_mode) & 0o077 or auth.stat().st_uid != os.geteuid()
            or auth.stat().st_nlink != 1)):
        raise RuntimeError("codex_auth_unavailable")
    return home, auth


@dataclass
class LoginJob:
    job_id: str
    account: str
    process: subprocess.Popen[bytes]
    started: float
    url: str = ""
    code: str = ""
    phase: str = "starting"
    returncode: int | None = None
    buffer: str = field(default="", repr=False)
    output_bytes: int = 0
    finished: float | None = None
    lock_fd: int | None = field(default=None, repr=False)
    reader_done: threading.Event = field(default_factory=threading.Event, repr=False)
    previous_auth: str | None = field(default=None, repr=False)
    auth_finalized: bool = False


class CodexDeviceLoginManager:
    """Manage bounded native device-auth processes, one per account."""

    def __init__(self, root: Path = DEFAULT_CODEX_ROOT, *, cli: str | None = None,
                 clock=time.monotonic):
        self.root = Path(root)
        self.cli = cli or os.environ.get("ADMIRA_CODEX_CLI", "codex")
        self.clock = clock
        self.lock = threading.RLock()
        self.jobs: dict[str, LoginJob] = {}
        self.closed = False

    @staticmethod
    def _extract(text: str) -> tuple[str, str]:
        """Return only the fixed official device URL and a short one-time code.

        Never relay arbitrary CLI text, URL query strings, account identifiers,
        OAuth redirects, or token-looking strings to the browser.
        """
        clean = ANSI_RE.sub("", text)
        official = False
        for candidate in re.findall(r"https://[^\s<>\"']+", clean):
            try:
                url = urllib.parse.urlsplit(candidate.rstrip(".,)"))
                if (url.scheme == "https" and url.netloc == "auth.openai.com"
                        and url.path.rstrip("/") == "/codex/device"):
                    official = True
            except ValueError:
                continue
        if not official:
            return "", ""
        # Native CLI prints a standalone XXXX-XXXXX code following prose.
        # Labeled compact codes are accepted as well, without a greedy match.
        codes = re.findall(r"(?m)^\s*([A-Z0-9]{4,5}-[A-Z0-9]{4,5})\s*$", clean)
        codes += re.findall(r"(?im)\b(?:code|codigo)\s*[:=]\s*([A-Z0-9]{4,5}-[A-Z0-9]{4,5}|[A-Z0-9]{6,10})\s*$", clean)
        return DEVICE_URL, codes[-1] if codes else ""

    @staticmethod
    def _authenticated(root: Path, account: str) -> bool:
        try:
            _home, auth = _safe_auth_path(root, account)
            if not auth.exists():
                return False
            payload = json.loads(_private_file(auth, max_bytes=MAX_AUTH_BYTES))
            tokens = payload.get("tokens") if isinstance(payload, dict) else None
            # File presence alone is not enough; API-key-only auth is not a
            # ChatGPT subscription slot. Never return values from this file.
            return isinstance(tokens, dict) and all(
                isinstance(tokens.get(name), str) and bool(tokens[name].strip())
                for name in ("access_token", "refresh_token", "id_token")
            )
        except (OSError, RuntimeError, ValueError, TypeError, UnicodeError):
            return False

    @staticmethod
    def _identity(root: Path, account: str) -> str:
        """Read only for private equality checks, never return an identity."""
        try:
            _home, auth = _safe_auth_path(root, account)
            payload = json.loads(_private_file(auth, max_bytes=MAX_AUTH_BYTES))
            identity = payload.get("tokens", {}).get("account_id", "")
            return identity.strip() if isinstance(identity, str) and len(identity) <= 256 else ""
        except (OSError, RuntimeError, ValueError, TypeError, AttributeError):
            return ""

    @staticmethod
    def _slot_lock(home: Path) -> int:
        fd = os.open(home / ".operator-device-login.lock", os.O_RDWR | os.O_CREAT
                     | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                    or info.st_uid != os.geteuid() or info.st_nlink != 1):
                raise RuntimeError("codex_account_unavailable")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except Exception:
            os.close(fd)
            raise RuntimeError("codex_login_in_progress") from None

    @staticmethod
    def _prepare_config(home: Path) -> None:
        path = home / "config.toml"
        content = b'cli_auth_credentials_store = "file"\nforced_login_method = "chatgpt"\n'
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError:
            config = tomllib.loads(_private_file(path, max_bytes=MAX_AUTH_BYTES))
            if config.get("cli_auth_credentials_store", "file") != "file" \
                    or config.get("forced_login_method", "chatgpt") != "chatgpt":
                raise RuntimeError("codex_config_unavailable")
        else:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())

    @staticmethod
    def _environment(home: Path) -> dict[str, str]:
        # Allowlist instead of copying provider keys, DB credentials, proxy
        # settings, OpenAI auth overrides, NODE_OPTIONS, or shell hooks.
        env = {name: os.environ[name] for name in ("PATH", "LANG", "LC_ALL", "TZ")
               if name in os.environ}
        env.update({"PATH": env.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                    "HOME": str(home), "CODEX_HOME": str(home),
                    "XDG_CONFIG_HOME": str(home), "XDG_CACHE_HOME": str(home),
                    "NO_COLOR": "1", "TERM": "dumb", "RUST_LOG": "off"})
        return env

    def _finish(self, job: LoginJob, phase: str) -> None:
        job.phase = phase
        job.url = job.code = job.buffer = ""
        job.finished = job.finished if job.finished is not None else self.clock()
        job.returncode = job.process.poll()
        if job.returncode is not None and job.lock_fd is not None:
            try:
                if not job.auth_finalized and phase != "completed":
                    try:
                        self._restore_auth(job)
                    except Exception:
                        # Unsafe/malformed paths remain unauthenticated. Do
                        # not follow them, recurse through _stop(), retain an
                        # old secret in memory, or dump exception contents.
                        job.phase = "failed"
                        print("operator_auth_restore_failed", file=sys.stderr)
            finally:
                job.previous_auth = None
                job.auth_finalized = True
                fd, job.lock_fd = job.lock_fd, None
                try:
                    os.close(fd)
                except OSError:
                    pass

    def _restore_auth(self, job: LoginJob) -> None:
        """An interrupted replacement login must preserve the previous slot."""
        home, auth = _safe_auth_path(self.root, job.account)
        if job.previous_auth is None:
            if auth.exists():
                os.unlink(auth)
            return
        if auth.exists() and _private_file(auth, max_bytes=MAX_AUTH_BYTES) == job.previous_auth:
            return
        fd, temporary = tempfile.mkstemp(prefix=".operator-auth-", dir=home)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(job.previous_auth)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, auth)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _stop(self, job: LoginJob, phase: str) -> None:
        # Called with the manager lock held. Give the entire process group a
        # bounded grace period so a CLI wrapper cannot leave orphan children.
        job.phase = phase
        job.url = job.code = job.buffer = ""
        job.finished = job.finished if job.finished is not None else self.clock()
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if job.process.poll() is not None and job.reader_done.is_set():
                break
            try:
                os.killpg(job.process.pid, sig)
            except ProcessLookupError:
                pass
            try:
                job.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                continue
        self._finish(job, phase)

    def cleanup(self) -> None:
        with self.lock:
            now = self.clock()
            for job_id, job in list(self.jobs.items()):
                if job.phase not in TERMINAL_PHASES:
                    if now - job.started >= LOGIN_JOB_TTL:
                        self._stop(job, "expired")
                    elif job.process.poll() is not None:
                        phase = "completed" if job.process.returncode == 0 and self._authenticated(self.root, job.account) else "failed"
                        self._finish(job, phase)
                if job.finished is not None and now - job.finished >= JOB_RETENTION:
                    if job.process.poll() is None:
                        self._stop(job, job.phase)
                    if job.process.poll() is not None and job.reader_done.is_set():
                        self.jobs.pop(job_id, None)

    def _read(self, job: LoginJob) -> None:
        try:
            assert job.process.stdout is not None
            while True:
                # os.read delivers short interactive output immediately; a
                # buffered read(1024) can wait indefinitely for more bytes.
                chunk = os.read(job.process.stdout.fileno(), 1024)
                if not chunk:
                    break
                with self.lock:
                    if job.phase in TERMINAL_PHASES:
                        continue
                    job.output_bytes += len(chunk)
                    if job.output_bytes > MAX_TOTAL_OUTPUT:
                        self._stop(job, "failed")
                        break
                    job.buffer = (job.buffer + chunk.decode("utf-8", "replace"))[-MAX_OUTPUT:]
                    url, code = self._extract(job.buffer)
                    job.url, job.code = url or job.url, code or job.code
                    job.phase = "waiting_for_operator" if job.url and job.code else "running"
            with self.lock:
                try:
                    job.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self._stop(job, "failed")
                if job.phase not in TERMINAL_PHASES:
                    self._finish(job, "completed" if job.process.returncode == 0
                                 and self._authenticated(self.root, job.account) else "failed")
        except Exception:
            # Exception text can contain CLI output; it must never be logged.
            with self.lock:
                self._stop(job, "failed")
        finally:
            if job.process.stdout is not None:
                job.process.stdout.close()
            job.reader_done.set()

    def start(self, account: str) -> dict[str, Any]:
        account = _safe_account(account)
        with self.lock:
            self.cleanup()
            if self.closed:
                raise RuntimeError("codex_login_unavailable")
            for job in self.jobs.values():
                if job.account == account and job.process.poll() is None:
                    return self.status(job.job_id)
            home, auth = _safe_auth_path(self.root, account)
            executable = shutil.which(self.cli)
            if not executable:
                raise RuntimeError("codex_cli_unavailable")
            slot_fd = self._slot_lock(home)
            try:
                previous_auth = _private_file(auth, max_bytes=MAX_AUTH_BYTES) if auth.exists() else None
                self._prepare_config(home)
                proc = subprocess.Popen(
                    [executable, "login", "--device-auth"],
                    cwd=str(home), env=self._environment(home), stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    shell=False, close_fds=True, start_new_session=True, umask=0o077,
                )
            except Exception:
                os.close(slot_fd)
                raise RuntimeError("codex_login_unavailable") from None
            job = LoginJob(secrets.token_urlsafe(18), account, proc, self.clock(),
                           lock_fd=slot_fd, previous_auth=previous_auth)
            self.jobs[job.job_id] = job
            # Retain only bounded metadata for earlier completed attempts.
            old = [j for j in self.jobs.values() if j.account == account and j.phase in TERMINAL_PHASES]
            for previous in old[:-4]:
                if previous.process.poll() is not None and previous.reader_done.is_set():
                    self.jobs.pop(previous.job_id, None)
            threading.Thread(target=self._read, args=(job,), daemon=True, name=f"codex-login-{account}").start()
            return self.status(job.job_id)

    def status(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            self.cleanup()
            job = self.jobs.get(str(job_id))
            if not job:
                raise ValueError("login_job_not_found")
            remaining = max(0, math.ceil(LOGIN_JOB_TTL - (self.clock() - job.started))) if job.phase not in TERMINAL_PHASES else 0
            return {"ok": True, "job_id": job.job_id, "account": job.account,
                    "phase": job.phase, "url": job.url, "code": job.code,
                    "running": job.process.poll() is None, "returncode": job.returncode,
                    "ttl_seconds": remaining, "expires_in": remaining,
                    "authenticated": job.phase == "completed" and self._authenticated(self.root, job.account)}

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.jobs.get(str(job_id))
            if not job:
                raise ValueError("login_job_not_found")
            if job.process.poll() is None:
                self._stop(job, "cancelled")
            elif job.phase not in TERMINAL_PHASES:
                self._finish(job, "cancelled")
            return self.status(job.job_id)

    def account_status(self) -> list[dict[str, Any]]:
        with self.lock:
            self.cleanup()
            result = []
            authenticated = {account: self._authenticated(self.root, account) for account in ACCOUNT_IDS}
            identities = {account: self._identity(self.root, account) for account in ACCOUNT_IDS}
            duplicate = bool(all(authenticated.values()) and identities["primary"]
                             and _text_equal(identities["primary"], identities["secondary"]))
            for account in sorted(ACCOUNT_IDS):
                current = next((job for job in self.jobs.values()
                                if job.account == account and job.process.poll() is None), None)
                valid = authenticated[account]
                result.append({"account": account, "authenticated": valid,
                               "status": "connecting" if current else "connected" if valid else "disconnected",
                               "job_id": current.job_id if current else None,
                               "duplicate_account": duplicate,
                               "verification": "local_credentials_only"})
            return result

    def disconnect(self, account: str) -> dict[str, Any]:
        """Remove only the selected account's auth file, never expose its contents."""
        account = _safe_account(account)
        with self.lock:
            self.cleanup()
            for job in self.jobs.values():
                if job.account == account and job.process.poll() is None:
                    raise RuntimeError("codex_login_in_progress")
            home, auth = _safe_auth_path(self.root, account)
            slot_fd = self._slot_lock(home)
            try:
                if auth.exists():
                    os.unlink(auth)
                    directory = os.open(home, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
            except OSError:
                raise RuntimeError("codex_disconnect_failed") from None
            finally:
                os.close(slot_fd)
        return {"ok": True, "account": account, "authenticated": False}

    def shutdown(self) -> None:
        with self.lock:
            self.closed = True
            for job in list(self.jobs.values()):
                self._stop(job, "cancelled" if job.phase not in TERMINAL_PHASES else job.phase)


@dataclass
class Session:
    csrf: str
    expires: float
    role: str = "operator"


class OperatorState:
    def __init__(self, *, password_file=DEFAULT_PASSWORD_FILE, gemini_root=DEFAULT_GEMINI_ROOT,
                 codex_root=DEFAULT_CODEX_ROOT, connect=None, clock=time.monotonic):
        self.password_file = Path(password_file)
        self.gemini_root = Path(gemini_root)
        self.sessions: dict[str, Session] = {}
        self.failures: dict[str, tuple[int, float]] = {}
        self.mutations: dict[str, list[float]] = {}
        self.lock = threading.RLock()
        self.provider_lock = threading.Lock()
        self.clock = clock
        self.login = CodexDeviceLoginManager(codex_root, clock=clock)
        self.connect = connect

    def cleanup(self) -> None:
        now = self.clock()
        with self.lock:
            self.sessions = {key: value for key, value in self.sessions.items() if value.expires > now}
            self.failures = {key: value for key, value in self.failures.items() if value[1] + 900 > now}
            self.mutations = {key: [stamp for stamp in values if now - stamp < 60]
                              for key, values in self.mutations.items() if values and now - values[-1] < 60}

    def _new_session(self, role: str, ttl: int) -> tuple[str, str]:
        self.cleanup()
        if len(self.sessions) >= MAX_SESSIONS:
            # Expired entries have already gone; never evict another operator.
            raise RuntimeError("session_capacity_reached")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        self.sessions[token] = Session(csrf, self.clock() + ttl, role)
        return token, csrf

    def bootstrap(self, token: str = "") -> tuple[str, str]:
        with self.lock:
            self.cleanup()
            if not self.setup_required():
                raise PermissionError("setup_unavailable")
            existing = self.sessions.get(token)
            if existing and existing.role == "bootstrap":
                return token, existing.csrf
            return self._new_session("bootstrap", BOOTSTRAP_TTL)

    def allow_mutation(self, ip: str) -> bool:
        """Small in-process limiter; the reverse proxy remains the outer limit."""
        now = self.clock()
        with self.lock:
            self.cleanup()
            if ip not in self.mutations and len(self.mutations) >= MAX_CLIENTS:
                return False
            recent = [stamp for stamp in self.mutations.get(ip, []) if now - stamp < 60]
            if len(recent) >= 30:
                self.mutations[ip] = recent
                return False
            recent.append(now)
            self.mutations[ip] = recent
            return True

    def authenticate(self, password: str, ip: str) -> tuple[str, str]:
        now = self.clock()
        with self.lock:
            self.cleanup()
            count, blocked = self.failures.get(ip, (0, 0.0))
            if blocked > now:
                raise PermissionError("login_backoff")
            try:
                valid = _password_matches(password, _private_file(self.password_file))
            except (OSError, RuntimeError):
                valid = False
            if not valid:
                if ip not in self.failures and len(self.failures) >= MAX_CLIENTS:
                    raise PermissionError("login_backoff")
                count += 1
                delay = min(300.0, 2.0 ** min(count, 8))
                self.failures[ip] = (count, now + delay)
                raise PermissionError("invalid_login")
            self.failures.pop(ip, None)
            return self._new_session("operator", LOGIN_TTL)

    def setup_required(self) -> bool:
        try:
            self.password_file.lstat()
        except FileNotFoundError:
            return True
        # Invalid, empty, or symlinked password files fail closed; they do not
        # reopen first-run account takeover. Recovery is an operator CLI task.
        return False

    def setup(self, password: str, confirmation: str, token: str, csrf: str) -> tuple[str, str]:
        if (not isinstance(password, str) or not isinstance(confirmation, str)
                or len(password) < 16 or len(password.encode("utf-8")) > MAX_PASSWORD_BYTES
                or not _text_equal(password, confirmation)):
            raise ValueError("invalid_setup_password")
        with self.lock:
            bootstrap = self.sessions.get(token)
            if not bootstrap or bootstrap.role != "bootstrap" or bootstrap.expires <= self.clock() \
                    or not _text_equal(bootstrap.csrf, csrf) or not self.setup_required():
                raise PermissionError("setup_unavailable")
            iterations = PBKDF2_ITERATIONS
            salt = secrets.token_bytes(16)
            digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
            encoded = "pbkdf2_sha256$%d$%s$%s\n" % (
                iterations, base64.urlsafe_b64encode(salt).decode(), base64.urlsafe_b64encode(digest).decode())
            _safe_root(self.password_file.parent)
            try:
                fd = os.open(self.password_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o600)
                try:
                    payload = encoded.encode("ascii")
                    offset = 0
                    while offset < len(payload):
                        offset += os.write(fd, payload[offset:])
                    os.fsync(fd)
                finally:
                    os.close(fd)
                directory = os.open(self.password_file.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            except FileExistsError as exc:
                raise PermissionError("setup_unavailable") from exc
            # The public bootstrap session never becomes an authenticated
            # operator. Revoke every setup token and require an explicit login.
            self.sessions.clear()
            return "", ""

    def session(self, token: str) -> Session | None:
        with self.lock:
            self.cleanup()
            value = self.sessions.get(token)
            if value and value.expires > self.clock() and value.role == "operator":
                return value
            return None

    def logout(self, token: str) -> None:
        with self.lock:
            self.sessions.pop(token, None)

    def register_gemini(self, key: str, project_ref: str, capacity: int) -> dict[str, Any]:
        if not isinstance(key, str) or not isinstance(project_ref, str):
            raise ValueError("invalid_gemini_registration")
        key = validate_gemini_key(key)
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{2,199}", project_ref)
                or _text_equal(project_ref, key) or key in project_ref
                or re.match(r"(?i)(?:AIza|sk[-_]|Bearer|eyJ)", project_ref)):
            raise ValueError("invalid_project_ref")
        if type(capacity) is not int or not 1 <= capacity <= 10000:
            raise ValueError("invalid_capacity")
        with self.provider_lock:
            _safe_root(self.gemini_root)
            if not check_gemini_api_key(key):
                raise ValueError("gemini_health_check_failed")
            secret_ref, fingerprint, _created = _store(self.gemini_root, key)
            connect = self.connect or _default_connect
            try:
                with connect() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT admira.register_gemini_pool_project(%s, %s, 'healthy')", (project_ref, capacity))
                        project_id = str(cur.fetchone()[0])
                        cur.execute("SELECT admira.register_gemini_pool_credential(%s, %s, %s, 'healthy', 'auth')", (project_id, secret_ref, fingerprint))
                    conn.commit()
            except Exception:
                # Keep the private file after an ambiguous commit; retrying is
                # idempotent and cannot leave a committed DB ref dangling.
                raise RuntimeError("gemini_registration_failed") from None
        return {"ok": True, "project_ref": project_ref, "fingerprint": fingerprint[:12], "health": "healthy"}

    def gemini_status(self) -> list[dict[str, Any]]:
        connect = self.connect or _default_connect
        try:
            with connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT project_ref, capacity, health, health_checked_at FROM admira.operator_gemini_pool_status() ORDER BY project_ref")
                    rows = cur.fetchall()
        except Exception:
            raise RuntimeError("gemini_status_unavailable") from None
        return [{"project_ref": str(row[0])[:200], "capacity": int(row[1]), "health": str(row[2])[:32],
                 "health_checked_at": row[3].isoformat() if hasattr(row[3], "isoformat") else None} for row in rows[:1000]]

    def sponsorship_status(self) -> list[dict[str, Any]]:
        """Return only the bounded operator projection, never tenant secrets."""
        connect = self.connect or _default_connect
        try:
            with connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT runtime_key, display_name, lifecycle_state, trial_ends_at, "
                        "image_sponsorship_ends_at, effective_sponsorship_ends_at, route "
                        "FROM admira.operator_tenant_sponsorship_status() ORDER BY runtime_key"
                    )
                    rows = cur.fetchall()
        except Exception:
            raise RuntimeError("sponsorship_status_unavailable") from None
        return [{
            "runtime_key": str(row[0])[:63],
            "display_name": str(row[1])[:200],
            "lifecycle_state": str(row[2])[:32],
            "trial_ends_at": row[3].isoformat() if hasattr(row[3], "isoformat") else None,
            "image_sponsorship_ends_at": row[4].isoformat() if hasattr(row[4], "isoformat") else None,
            "effective_sponsorship_ends_at": row[5].isoformat() if hasattr(row[5], "isoformat") else None,
            "route": str(row[6])[:32],
        } for row in rows[:1000]]

    def extend_sponsorship(self, runtime_key: str, ends_at: str) -> dict[str, Any]:
        if (not isinstance(runtime_key, str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,62}", runtime_key)
                or not isinstance(ends_at, str) or not 20 <= len(ends_at) <= 64):
            raise ValueError("invalid_sponsorship_extension")
        try:
            parsed = datetime.fromisoformat(ends_at.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("invalid_sponsorship_extension") from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("invalid_sponsorship_extension")
        connect = self.connect or _default_connect
        try:
            with connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT runtime_key, lifecycle_state, previous_ends_at, "
                        "image_sponsorship_ends_at, route "
                        "FROM admira.operator_set_image_sponsorship_end(%s, %s)",
                        (runtime_key, parsed),
                    )
                    row = cur.fetchone()
                conn.commit()
        except Exception as exc:
            if getattr(exc, "sqlstate", "") in {"22023", "55000"}:
                raise ValueError("invalid_sponsorship_extension") from None
            raise RuntimeError("sponsorship_update_failed") from None
        if not row:
            raise RuntimeError("sponsorship_update_failed")
        return {
            "ok": True,
            "runtime_key": str(row[0])[:63],
            "lifecycle_state": str(row[1])[:32],
            "previous_ends_at": row[2].isoformat() if hasattr(row[2], "isoformat") else None,
            "image_sponsorship_ends_at": row[3].isoformat() if hasattr(row[3], "isoformat") else None,
            "route": str(row[4])[:32],
        }


def _default_connect():
    import psycopg
    password_file = os.environ.get("ADMIRA_OPERATOR_DB_PASSWORD_FILE", "/run/secrets/operator_db_password")
    password = _private_file(Path(password_file), max_bytes=4096)
    return psycopg.connect(host=os.environ.get("ADMIRA_DB_HOST", "postgres"),
                           port=int(os.environ.get("ADMIRA_DB_PORT", "5432")),
                           dbname=os.environ.get("ADMIRA_DB_NAME", "admira_control"),
                           user=os.environ.get("ADMIRA_DB_USER", "admira_operator_login"),
                           password=password, connect_timeout=10, application_name="admira-operator-dashboard",
                           options="-c statement_timeout=15000 -c lock_timeout=5000")


class RequestError(Exception):
    def __init__(self, code: str, status: int):
        self.code, self.status = code, status


class OperatorHandler(BaseHTTPRequestHandler):
    state: OperatorState
    cookie_secure = True
    allowed_hosts = frozenset({"localhost", "127.0.0.1", "::1"})
    setup_networks = (ipaddress.ip_network("127.0.0.1/32"), ipaddress.ip_network("::1/128"))
    server_version = "AdmiraOperator"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def _headers(self, content_type: str, length: int, *, cookie="", static=False, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        policy = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if static:
            policy += "; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'"
        self.send_header("Content-Security-Policy", policy)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        if status == 429:
            self.send_header("Retry-After", "60")
        # A rejected request body must never be parsed as the next request.
        self.close_connection = True
        self.send_header("Connection", "close")
        self.send_header("Content-Length", str(length))
        self.end_headers()

    def _json(self, value: Mapping[str, Any], status=200, *, cookie=""):
        body = json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self._headers("application/json; charset=utf-8", len(body), cookie=cookie, status=status)
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, code: str, status: int):
        self._json({"ok": False, "error_code": code}, status)

    def send_error(self, code, message=None, explain=None):
        # BaseHTTPRequestHandler otherwise interpolates request data into HTML.
        self._error("invalid_request" if code < 500 else "operator_unavailable", code)

    def _cookie(self, token="", *, ttl=LOGIN_TTL):
        flags = "HttpOnly; SameSite=Strict; Path=/" + ("; Secure" if self.cookie_secure else "")
        return f"{COOKIE_NAME}={token}; Max-Age={ttl if token else 0}; {flags}"

    def _static(self, path: str) -> bool:
        files = {
            "/": ("operator_dashboard.html", "text/html; charset=utf-8"),
            "/operator_dashboard.html": ("operator_dashboard.html", "text/html; charset=utf-8"),
            "/operator_dashboard.css": ("operator_dashboard.css", "text/css; charset=utf-8"),
            "/operator_dashboard.js": ("operator_dashboard.js", "text/javascript; charset=utf-8"),
        }
        entry = files.get(path)
        if not entry:
            return False
        path = Path(__file__).resolve().with_name(entry[0])
        if path.is_symlink() or not path.is_file():
            raise RequestError("not_found", 404)
        body = path.read_bytes()
        self._headers(entry[1], len(body), static=True)
        self.wfile.write(body)
        return True

    @staticmethod
    def _authority(value: str) -> tuple[str, int | None]:
        if not value or len(value) > 255 or any(ord(c) <= 32 or ord(c) >= 127 for c in value):
            raise ValueError("invalid_authority")
        parsed = urllib.parse.urlsplit("//" + value)
        if (not parsed.hostname or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment or "\\" in value):
            raise ValueError("invalid_authority")
        return parsed.hostname.lower(), parsed.port

    def _request_path(self) -> str:
        try:
            hosts = self.headers.get_all("Host", [])
            if len(hosts) != 1:
                raise ValueError("invalid_host")
            host, port = self._authority(hosts[0])
            if host not in self.allowed_hosts:
                raise ValueError("invalid_host")
            fetch_site = self.headers.get("Sec-Fetch-Site", "")
            if fetch_site and fetch_site not in {"same-origin", "none"}:
                raise ValueError("cross_origin_request")
            origins = self.headers.get_all("Origin", [])
            if origins:
                if len(origins) != 1:
                    raise ValueError("invalid_origin")
                origin = urllib.parse.urlsplit(origins[0])
                if origin.scheme not in {"http", "https"} or origin.path or origin.query or origin.fragment:
                    raise ValueError("invalid_origin")
                origin_host, origin_port = self._authority(origin.netloc)
                default_port = 443 if origin.scheme == "https" else 80
                if origin_host != host or (origin_port or default_port) != (port or default_port):
                    raise ValueError("invalid_origin")
            if (not self.path.startswith("/") or self.path.startswith("//") or len(self.path) > 512
                    or any(ord(c) <= 32 or ord(c) >= 127 for c in self.path)
                    or any(c in self.path for c in ("?", "#", "%", "\\"))):
                raise ValueError("invalid_path")
        except (ValueError, UnicodeError):
            raise RequestError("request_not_allowed", 403) from None
        return self.path

    def _setup_allowed(self) -> bool:
        try:
            peer = ipaddress.ip_address(self.client_address[0])
            return any(peer in network for network in self.setup_networks)
        except ValueError:
            return False

    def _cookies(self):
        try:
            raw = self.headers.get("Cookie", "")
            if len(raw) > 4096:
                return {}
            parsed = http.cookies.SimpleCookie(raw)
            return {key: morsel.value for key, morsel in parsed.items()}
        except http.cookies.CookieError:
            return {}

    def _token(self) -> str:
        return self._cookies().get(COOKIE_NAME, "")

    def _auth(self, *, write=False) -> Session:
        session = self.state.session(self._token())
        if not session:
            raise RequestError("authentication_required", 401)
        if write and not _text_equal(self.headers.get("X-CSRF-Token", ""), session.csrf):
            raise RequestError("csrf_required", 403)
        return session

    @staticmethod
    def _object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate_json_key")
            value[key] = item
        return value

    def _body(self):
        if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Encoding"):
            raise RequestError("invalid_body", 400)
        if self.headers.get_content_type() != "application/json":
            raise RequestError("json_required", 415)
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", lengths[0]):
            raise RequestError("invalid_body", 400)
        length = int(lengths[0])
        if length > MAX_BODY:
            raise RequestError("body_too_large", 413)
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("incomplete_body")
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=self._object,
                               parse_constant=lambda _value: (_ for _ in ()).throw(ValueError())) if raw else {}
            if not isinstance(value, dict):
                raise ValueError("invalid_body")
            return value
        except (ValueError, UnicodeError, RecursionError):
            raise RequestError("invalid_body", 400) from None

    @staticmethod
    def _string(body, key, default="") -> str:
        value = body.get(key, default)
        if not isinstance(value, str):
            raise RequestError("invalid_body", 400)
        return value

    def _limit(self):
        if not self.state.allow_mutation(self.client_address[0]):
            raise RequestError("rate_limited", 429)

    def _get(self, path: str):
        if self._static(path):
            return
        if path == "/api/operator/session":
            if self.state.setup_required():
                if not self._setup_allowed():
                    raise RequestError("setup_unavailable", 403)
                self._limit()
                token, csrf = self.state.bootstrap(self._token())
                self._json({"ok": True, "authenticated": False, "setup_required": True, "csrf_token": csrf},
                           cookie=self._cookie(token, ttl=BOOTSTRAP_TTL))
                return
            session = self.state.session(self._token())
            result = {"ok": True, "authenticated": bool(session), "setup_required": False}
            if session:
                result.update(role=session.role, csrf_token=session.csrf)
            self._json(result)
            return
        self._auth()
        if path == "/api/operator/gemini/status":
            self._json({"ok": True, "projects": self.state.gemini_status()})
        elif path == "/api/operator/sponsorship/status":
            try:
                tenants = self.state.sponsorship_status()
            except RuntimeError:
                raise RequestError("sponsorship_status_unavailable", 503) from None
            self._json({"ok": True, "tenants": tenants})
        elif path == "/api/operator/codex/status":
            self._json({"ok": True, "accounts": self.state.login.account_status(), "broker_ready": False})
        elif match := re.fullmatch(r"/api/operator/codex/(primary|secondary)/status", path):
            self._json({"ok": True, **next(item for item in self.state.login.account_status() if item["account"] == match[1])})
        elif match := re.fullmatch(r"/api/operator/codex/login/([A-Za-z0-9_-]{1,128})", path):
            try:
                self._json(self.state.login.status(match[1]))
            except ValueError:
                raise RequestError("login_job_not_found", 404) from None
        else:
            raise RequestError("not_found", 404)

    def _post(self, path: str):
        if path in {"/api/operator/login", "/api/operator/setup"}:
            self._limit()
            body = self._body()
            if path.endswith("/login"):
                try:
                    token, csrf = self.state.authenticate(self._string(body, "password"), self.client_address[0])
                except (PermissionError, RuntimeError):
                    raise RequestError("login_failed", 401) from None
                self.state.logout(self._token())
                self._json({"ok": True, "authenticated": True, "csrf_token": csrf, "role": "operator"}, cookie=self._cookie(token))
            else:
                if not self._setup_allowed():
                    raise RequestError("setup_unavailable", 403)
                confirmation = body.get("confirmation", body.get("password_confirm", body.get("confirm_password", "")))
                try:
                    self.state.setup(self._string(body, "password"), confirmation, self._token(), self.headers.get("X-CSRF-Token", ""))
                except (PermissionError, ValueError, RuntimeError, OSError):
                    raise RequestError("setup_unavailable", 403) from None
                self._json({"ok": True, "authenticated": False, "setup_required": False}, cookie=self._cookie())
            return
        self._auth(write=True)
        self._limit()
        body = self._body()
        if path == "/api/operator/logout":
            self.state.logout(self._token())
            self._json({"ok": True, "authenticated": False}, cookie=self._cookie())
            return
        if path == "/api/operator/gemini/register":
            result = self.state.register_gemini(self._string(body, "api_key", body.get("key", "")),
                                                self._string(body, "project_ref"), body.get("capacity", 1))
        elif path == "/api/operator/sponsorship/extend":
            try:
                result = self.state.extend_sponsorship(
                    self._string(body, "runtime_key"), self._string(body, "ends_at")
                )
            except ValueError:
                raise RequestError("invalid_sponsorship_extension", 400) from None
            except RuntimeError:
                raise RequestError("sponsorship_update_failed", 503) from None
        elif path == "/api/operator/codex/login":
            result = self.state.login.start(self._string(body, "account", body.get("slot", "")))
        elif match := re.fullmatch(r"/api/operator/codex/(primary|secondary)/login", path):
            result = self.state.login.start(match[1])
        elif match := re.fullmatch(r"/api/operator/codex/login/([A-Za-z0-9_-]{1,128})/cancel", path):
            try:
                result = self.state.login.cancel(match[1])
            except ValueError:
                raise RequestError("login_job_not_found", 404) from None
        elif path == "/api/operator/codex/disconnect":
            result = self.state.login.disconnect(self._string(body, "account", body.get("slot", "")))
        elif match := re.fullmatch(r"/api/operator/codex/(primary|secondary)/disconnect", path):
            result = self.state.login.disconnect(match[1])
        else:
            raise RequestError("not_found", 404)
        self._json(result)

    def _dispatch(self, method):
        try:
            method(self._request_path())
        except RequestError as exc:
            self._error(exc.code, exc.status)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except (ValueError, TypeError, UnicodeError, OverflowError):
            self._error("operator_operation_failed", 400)
        except RuntimeError as exc:
            if str(exc) == "codex_login_in_progress":
                self._error("codex_login_in_progress", 409)
            else:
                self._error("operator_unavailable", 503)
        except Exception:
            # Do not log request bodies, exception strings, or tracebacks.
            self._error("operator_unavailable", 503)

    def do_GET(self):
        self._dispatch(self._get)

    def do_POST(self):
        self._dispatch(self._post)

    def log_message(self, _format, *_args):
        return


class OperatorHTTPServer(ThreadingHTTPServer):
    """Bound HTTP concurrency and reap sessions/jobs without browser polling."""
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, handler):
        self.request_slots = threading.BoundedSemaphore(16)
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self.request_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.request_slots.release()

    def handle_error(self, request, client_address):
        # The default implementation dumps exception values and tracebacks.
        print("operator_request_failed", file=sys.stderr)

    def service_actions(self):
        try:
            self.RequestHandlerClass.state.cleanup()
            self.RequestHandlerClass.state.login.cleanup()
        except Exception:
            print("operator_cleanup_failed", file=sys.stderr)


def create_server(state: OperatorState, *, host=DEFAULT_BIND, port=DEFAULT_PORT,
                  cookie_secure=True, allowed_hosts=("localhost", "127.0.0.1", "::1"),
                  setup_cidrs=("127.0.0.1/32", "::1/128")) -> OperatorHTTPServer:
    hosts = frozenset(str(value).lower().strip() for value in allowed_hosts)
    if not hosts or any(not value or (value != "::1" and not re.fullmatch(r"[a-z0-9.-]+", value)) for value in hosts):
        raise ValueError("invalid_allowed_hosts")
    if not cookie_secure and not hosts.issubset({"localhost", "127.0.0.1", "::1"}):
        raise ValueError("secure_cookies_required")
    networks = tuple(ipaddress.ip_network(value.strip(), strict=True) for value in setup_cidrs if value.strip())
    if not 1 <= len(networks) <= 8 or any(network.prefixlen != network.max_prefixlen for network in networks):
        raise ValueError("invalid_setup_networks")
    handler = type("BoundOperatorHandler", (OperatorHandler,), {
        "state": state, "cookie_secure": bool(cookie_secure), "allowed_hosts": hosts,
        "setup_networks": networks,
    })
    return OperatorHTTPServer((host, int(port)), handler)


def main() -> int:
    cookie_secure = os.environ.get("ADMIRA_OPERATOR_COOKIE_SECURE", "true").lower() not in {"0", "false", "no"}
    state = OperatorState(
        password_file=Path(os.environ.get("ADMIRA_OPERATOR_PASSWORD_FILE", DEFAULT_PASSWORD_FILE)),
        gemini_root=Path(os.environ.get("ADMIRA_GEMINI_POOL_ROOT", DEFAULT_GEMINI_ROOT)),
        codex_root=Path(os.environ.get("ADMIRA_CENTRAL_CODEX_AUTH_ROOT", DEFAULT_CODEX_ROOT)),
    )
    server = create_server(state, host=os.environ.get("ADMIRA_OPERATOR_BIND", DEFAULT_BIND),
                           port=int(os.environ.get("ADMIRA_OPERATOR_PORT", DEFAULT_PORT)), cookie_secure=cookie_secure,
                           allowed_hosts=os.environ.get("ADMIRA_OPERATOR_ALLOWED_HOSTS", "localhost,127.0.0.1,::1").split(","),
                           setup_cidrs=os.environ.get("ADMIRA_OPERATOR_SETUP_CIDRS", "127.0.0.1/32,::1/128").split(","))
    def stop(_signum, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        state.login.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
