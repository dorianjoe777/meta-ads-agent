import hashlib
import hmac
import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
from operator_dashboard import ProvisionerClient


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class ProvisionerSocketContractTests(unittest.TestCase):
    def test_client_request_matches_host_protocol_and_accepts_response(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            os.chmod(root, 0o700)
            key = b"socket-contract-test-key-that-is-at-least-32-bytes"
            key_file = root / "tenant-provisioner.key"
            key_file.write_bytes(key)
            os.chmod(key_file, 0o600)
            socket_path = root / "provisioner.sock"
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(socket_path))
            os.chmod(socket_path, 0o600)
            received = {}

            def serve_once():
                connection, _ = server.accept()
                try:
                    wire = connection.recv(16 * 1024)
                    received["envelope"] = json.loads(wire.rstrip(b"\n").decode("utf-8"))
                    envelope = received["envelope"]
                    signature = envelope.pop("signature")
                    expected = hmac.new(key, canonical(envelope), hashlib.sha256).hexdigest()
                    received["valid_signature"] = hmac.compare_digest(signature, expected)
                    connection.sendall(b'{"ok":true,"claim":{"telegram_url":"https://t.me/admiraia_bot?start=test"}}\n')
                finally:
                    connection.close()

            server.listen(1)
            worker = threading.Thread(target=serve_once)
            worker.start()
            try:
                result = ProvisionerClient(socket_path, key_file, timeout=2).request({
                    "action": "create_trial",
                    "tenant_key": "customer-001",
                })
            finally:
                worker.join(timeout=2)
                server.close()

            self.assertEqual(result["ok"], True)
            self.assertTrue(received["valid_signature"])
            envelope = received["envelope"]
            self.assertEqual(envelope["body"]["action"], "create_trial")
            self.assertRegex(envelope["nonce"], r"^[a-f0-9]{32}$")
            self.assertIsInstance(envelope["timestamp"], int)


if __name__ == "__main__":
    unittest.main()
