#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
import secrets
import subprocess
import time
import urllib.parse

SECRET = os.environ.get("CLOUD_ACCESS_SECRET", "").strip()
PORT = int(os.environ.get("CLOUD_ACCESS_PORT", "7870") or "7870")
STATE_DIR = os.environ.get("ADMIRA_CLOUD_STATE_DIR", "/var/lib/admira-cloud-access-gate")
STATE_FILE = f"{STATE_DIR}/reset-state.json"
RESET_COMMAND = os.environ.get("RESET_COMMAND", "/usr/local/bin/admira-cloud-clean-reset")

def read_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {"status": "idle"}
    except (OSError, ValueError):
        return {"status": "idle"}

def write_state(payload):
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    temporary = f"{STATE_FILE}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.chmod(temporary, 0o600)
    os.replace(temporary, STATE_FILE)

def authorized(handler):
    supplied = str(handler.headers.get("X-Admira-Cloud-Secret", "")).strip()
    return bool(SECRET and supplied and hmac.compare_digest(supplied, SECRET))

def start_reset():
    current = read_state()
    if current.get("status") in {"queued", "running"}:
        return current
    queued = {
        "ok": True,
        "job_id": secrets.token_urlsafe(18),
        "status": "queued",
        "detail": "La limpieza se iniciara en el servidor.",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    write_state(queued)
    try:
        subprocess.Popen(
            [RESET_COMMAND, queued["job_id"]],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except Exception:
        failed = {**queued, "status": "failed", "detail": "No pude iniciar la limpieza del servidor."}
        write_state(failed)
        return failed
    return queued

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def send_json(self, code, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if path != "/admin/reset-status" or not authorized(self):
            self.send_json(404, {"ok": False, "error": "not_found"})
            return
        self.send_json(200, {"ok": True, **read_state()})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path != "/admin/reset" or not authorized(self):
            self.send_json(404, {"ok": False, "error": "not_found"})
            return
        self.send_json(202, start_reset())

if __name__ == "__main__":
    if not SECRET:
        raise SystemExit("CLOUD_ACCESS_SECRET is required")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

