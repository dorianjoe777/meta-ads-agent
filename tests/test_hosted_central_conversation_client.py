from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from src.hosted_central_conversation_client import (
    CENTRAL_MODEL,
    MODEL,
    CentralCodexProviderError,
    CentralCodexRuntimeClient,
    central_conversation_route,
)
from src.hosted_central_image_client import _canonical


class HostedCentralConversationClientTests(unittest.TestCase):
    def _access(self, root: Path, *, route="central_sponsored", ready=True):
        path = root / "access.json"
        path.write_text(json.dumps({
            "tenant_id": "tenant-001", "route": route, "central_ready": ready, "update_id": "42",
        }), encoding="utf-8")
        path.chmod(0o600)
        return path

    def _env(self, access: Path, key: Path, socket_path: Path):
        return {
            "ADMIRA_TENANT_ID": "tenant-001",
            "ADMIRA_HOSTED_IMAGE_ACCESS_FILE": str(access),
            "ADMIRA_CENTRAL_IMAGE_CLIENT_KEY_FILE": str(key),
            "ADMIRA_CENTRAL_CONVERSATION_SOCKET": str(socket_path),
        }

    def test_socket_request_is_signed_and_returns_openai_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            access = self._access(root)
            key = root / "key"
            key.write_bytes(b"k" * 32)
            key.chmod(0o600)
            socket_path = root / "conversation.sock"
            ready = threading.Event()
            failures = []

            def serve():
                try:
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                        server.bind(str(socket_path)); server.listen(1); ready.set()
                        connection, _ = server.accept()
                        with connection:
                            raw = connection.recv(1024 * 1024)
                            request = json.loads(raw.split(b"\n", 1)[0])
                            expected = hmac.new(b"k" * 32, _canonical({
                                key: value for key, value in request.items() if key != "signature"
                            }), hashlib.sha256).hexdigest()
                            self.assertTrue(hmac.compare_digest(request["signature"], expected))
                            body = request["body"]
                            self.assertEqual(body["purpose"], "conversation_inference")
                            self.assertEqual(body["messages"], [{"role": "user", "content": "Hola"}])
                            self.assertEqual(body["timeout_seconds"], 1)
                            connection.sendall((json.dumps({
                                "ok": True, "tenant_id": "tenant-001", "request_id": body["request_id"],
                                "model": CENTRAL_MODEL, "finish_reason": "stop",
                                "message": {"role": "assistant", "content": "Respuesta", "tool_calls": []},
                            }) + "\n").encode())
                except Exception as exc:
                    failures.append(exc)

            worker = threading.Thread(target=serve)
            worker.start(); self.assertTrue(ready.wait(2))
            with patch.dict(os.environ, self._env(access, key, socket_path), clear=False):
                result = CentralCodexRuntimeClient().chat.completions.create(
                    model=MODEL, messages=[{"role": "user", "content": "Hola"}], timeout=1,
                )
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(failures, [])
            self.assertEqual(result.choices[0].message.content, "Respuesta")
            self.assertEqual(result.choices[0].message.tool_calls, [])

    def test_route_never_claims_central_for_pool_off_or_not_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / "key"; key.write_bytes(b"k" * 32); key.chmod(0o600)
            socket_path = root / "missing.sock"
            with patch.dict(os.environ, self._env(self._access(root, route="personal_chatgpt"), key, socket_path), clear=False):
                self.assertEqual(central_conversation_route(), "local")
            with patch.dict(os.environ, self._env(self._access(root, ready=False), key, socket_path), clear=False):
                self.assertEqual(central_conversation_route(), "blocked")

    def test_bad_response_has_no_server_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            access = self._access(root)
            key = root / "key"; key.write_bytes(b"k" * 32); key.chmod(0o600)
            socket_path = root / "conversation.sock"
            ready = threading.Event()
            def serve():
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                    server.bind(str(socket_path)); server.listen(1); ready.set()
                    connection, _ = server.accept()
                    with connection:
                        connection.recv(1024 * 1024)
                        connection.sendall(b'{"ok":false,"error_code":"upstream SECRET"}\n')
            worker = threading.Thread(target=serve)
            worker.start(); self.assertTrue(ready.wait(2))
            with patch.dict(os.environ, self._env(access, key, socket_path), clear=False):
                with self.assertRaises(CentralCodexProviderError) as raised:
                    CentralCodexRuntimeClient().chat.completions.create(
                        model=MODEL, messages=[{"role": "user", "content": "Hola"}], timeout=1,
                    )
            worker.join(timeout=2)
            self.assertNotIn("SECRET", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
