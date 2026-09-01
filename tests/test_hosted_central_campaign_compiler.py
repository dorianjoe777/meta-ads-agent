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

from src.hosted_central_campaign_compiler import (
    MODEL,
    _canonical,
    maybe_compile_central_campaign,
)


class CentralCampaignCompilerTests(unittest.TestCase):
    def _access(self, root, **overrides):
        access = {
            "route": "central_sponsored",
            "central_ready": True,
            "tenant_id": "tenant-001",
            "update_id": "42",
        }
        access.update(overrides)
        path = Path(root) / "access.json"
        path.write_text(json.dumps(access))
        path.chmod(0o600)
        return path

    def _env(self, root, access, key, sock):
        return {
            "ADMIRA_HOSTED_IMAGE_ACCESS_FILE": str(access),
            "ADMIRA_CENTRAL_IMAGE_CLIENT_KEY_FILE": str(key),
            "ADMIRA_CENTRAL_CAMPAIGN_COMPILER_SOCKET": str(sock),
            "ADMIRA_TENANT_ID": "tenant-001",
        }

    def test_local_and_do_without_access_file_return_none(self):
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / "does-not-exist.json"
            with patch.dict(os.environ, {
                "ADMIRA_HOSTED_IMAGE_ACCESS_FILE": str(missing),
                "ADMIRA_TENANT_ID": "tenant-001",
            }):
                self.assertIsNone(maybe_compile_central_campaign("create_whatsapp_campaign", "x"))

    def test_blocked_and_not_ready_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for overrides, reason in (
                ({"route": "blocked"}, "entitlement_blocked"),
                ({"central_ready": False}, "central_not_ready"),
            ):
                access = self._access(root, **overrides)
                with patch.dict(os.environ, {
                    "ADMIRA_HOSTED_IMAGE_ACCESS_FILE": str(access),
                    "ADMIRA_TENANT_ID": "tenant-001",
                }):
                    result = maybe_compile_central_campaign("create_whatsapp_campaign", "x")
                self.assertEqual(result, {"ok": False, "reason": reason, "model": MODEL})

    def test_signed_round_trip_validates_request_and_accepts_compiled_result(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            access = self._access(root)
            key = root / "client.key"
            key.write_bytes(b"k" * 32)
            key.chmod(0o600)
            sock_path = root / "compiler.sock"
            observed = {}
            server_error = []
            server_ready = threading.Event()

            def serve():
                try:
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                        server.bind(str(sock_path))
                        server.listen(1)
                        server_ready.set()
                        connection, _ = server.accept()
                        with connection:
                            connection.settimeout(2)
                            envelope = json.loads(connection.recv(65536))
                            observed["envelope"] = envelope
                            expected_signature = hmac.new(
                                b"k" * 32,
                                _canonical({k: v for k, v in envelope.items() if k != "signature"}),
                                hashlib.sha256,
                            ).hexdigest()
                            if not hmac.compare_digest(envelope["signature"], expected_signature):
                                raise AssertionError("invalid request signature")
                            body = envelope["body"]
                            self.assertEqual(body["tenant_id"], "tenant-001")
                            self.assertEqual(body["purpose"], "campaign_compile")
                            self.assertEqual(body["tool"], "create_whatsapp_campaign")
                            self.assertEqual(body["prompt"], "Build a campaign")
                            self.assertEqual(body["update_id"], "42")
                            self.assertEqual(body["timeout_seconds"], 1)
                            connection.sendall((json.dumps({
                                "ok": True,
                                "tenant_id": body["tenant_id"],
                                "request_id": body["request_id"],
                                "model": MODEL,
                                "compiled": {"objective": "OUTCOME_LEADS", "name": "Test"},
                            }) + "\n").encode())
                except Exception as exc:  # surface worker-thread failures in the test
                    server_error.append(exc)

            thread = threading.Thread(target=serve)
            thread.start()
            self.assertTrue(server_ready.wait(2))
            env = self._env(root, access, key, sock_path)
            with patch.dict(os.environ, env):
                result = maybe_compile_central_campaign(
                    "create_whatsapp_campaign", "Build a campaign", now=1, timeout=1
                )
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(server_error, [])
            self.assertEqual(result, {
                "ok": True,
                "compiled": {"objective": "OUTCOME_LEADS", "name": "Test"},
                "model": MODEL,
                "provider": "hosted-central-codex",
            })
            self.assertTrue(observed["envelope"]["nonce"])
            self.assertEqual(observed["envelope"]["timestamp"], 1)

    def test_timeout_budget_is_bounded_below_socket_timeout(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            access = self._access(root)
            key = root / "client.key"
            key.write_bytes(b"k" * 32)
            key.chmod(0o600)
            sock_path = root / "compiler.sock"
            server_ready = threading.Event()
            observed = {}

            def serve():
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                    server.bind(str(sock_path))
                    server.listen(1)
                    server_ready.set()
                    connection, _ = server.accept()
                    with connection:
                        observed["body"] = json.loads(connection.recv(65536))["body"]
                        connection.sendall((json.dumps({
                            "ok": True, "tenant_id": "tenant-001",
                            "request_id": observed["body"]["request_id"],
                            "model": MODEL, "compiled": {"ready": True},
                        }) + "\n").encode())

            thread = threading.Thread(target=serve)
            thread.start()
            self.assertTrue(server_ready.wait(2))
            with patch.dict(os.environ, self._env(root, access, key, sock_path)):
                result = maybe_compile_central_campaign("create_whatsapp_campaign", "x", timeout=300)
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertTrue(result["ok"])
            self.assertEqual(observed["body"]["timeout_seconds"], 230)

    def test_rejects_invalid_tenant_request_model_and_compiled_without_local_fallback(self):
        cases = (
            ("tenant_id", "other-tenant", "output_invalid"),
            ("request_id", "not-the-request", "output_invalid"),
            ("model", "gpt-5.6-sol", "output_invalid"),
            ("compiled", [], "output_invalid"),
        )
        for field, value, reason in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                access = self._access(root)
                key = root / "client.key"
                key.write_bytes(b"k" * 32)
                key.chmod(0o600)
                sock_path = root / "compiler.sock"
                server_ready = threading.Event()

                def serve():
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                        server.bind(str(sock_path))
                        server.listen(1)
                        server_ready.set()
                        connection, _ = server.accept()
                        with connection:
                            connection.settimeout(2)
                            request = json.loads(connection.recv(65536))
                            response = {
                                "ok": True,
                                "tenant_id": request["body"]["tenant_id"],
                                "request_id": request["body"]["request_id"],
                                "model": MODEL,
                                "compiled": {"ok": True},
                            }
                            response[field] = value
                            connection.sendall((json.dumps(response) + "\n").encode())

                thread = threading.Thread(target=serve)
                thread.start()
                self.assertTrue(server_ready.wait(2))
                with patch.dict(os.environ, self._env(root, access, key, sock_path)):
                    with patch("src.hosted_central_campaign_compiler._error", wraps=lambda reason: {
                        "ok": False, "reason": reason, "model": MODEL
                    }) as safe_error:
                        result = maybe_compile_central_campaign(
                            "create_whatsapp_campaign", "Build a campaign", timeout=1
                        )
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())
                self.assertEqual(result["reason"], reason)
                self.assertNotEqual(result.get("provider"), "codex-local")
                self.assertTrue(safe_error.called)


if __name__ == "__main__":
    unittest.main()
