from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy.contabo.central_image_service import CentralImageServer
from deploy.contabo.image_broker import ImageBroker
from src.hosted_central_image_client import maybe_generate_central_image


PNG = b"\x89PNG\r\n\x1a\n" + b"fake-central-image"


class CentralImageEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="admira-central-e2e-")
        self.root = Path(self.temp.name)
        self.host_exchange = self.root / "host-exchange"
        self.key_root = self.root / "keys"
        self.output = self.host_exchange / "tenant-one" / "output"
        self.input_dir = self.root / "input"
        self.socket = self.root / "run" / "broker.sock"
        self.access_file = self.root / "runtime" / "hosted_image_access.json"
        self.client_key = self.root / "tenant-runtime" / "central_image_client.key"
        for directory in (self.output, self.key_root, self.input_dir, self.access_file.parent, self.client_key.parent):
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o700)

        key = b"k" * 64
        (self.key_root / "tenant-one").write_bytes(key + b"\n")
        (self.key_root / "tenant-one").chmod(0o600)
        self.client_key.write_bytes(key + b"\n")
        self.client_key.chmod(0o600)
        self.access_file.write_text(
            json.dumps({
                "tenant_id": "tenant-one",
                "route": "central_sponsored",
                "central_ready": True,
                "update_id": "update-42",
            }) + "\n",
            encoding="utf-8",
        )
        self.access_file.chmod(0o600)

        self.provider_calls: list[dict[str, object]] = []

        def provider(body, workdir):
            references = list(body.get("references") or [])
            self.provider_calls.append({"body": dict(body), "workdir": Path(workdir)})
            for reference in references:
                reference_path = Path(reference)
                self.assertTrue(reference_path.is_file())
                self.assertTrue(reference_path.resolve().is_relative_to(Path(workdir).resolve()))
                self.assertFalse(reference_path.resolve().is_relative_to(self.output.resolve()))
                self.assertEqual(stat.S_IMODE(reference_path.stat().st_mode), 0o600)
            self.provider_calls[-1]["reference_bytes"] = [
                Path(reference).read_bytes() for reference in references
            ]
            return PNG

        self.broker = ImageBroker(
            self.host_exchange,
            self.key_root,
            provider,
            lambda tenant_id, purpose: "central_sponsored"
            if tenant_id == "tenant-one" and purpose == "image_generation"
            else "blocked",
            max_global=2,
        )
        self.server = CentralImageServer(self.broker, self.socket)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 2
        while not self.socket.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.socket.exists())

        self.env = {
            "ADMIRA_TENANT_ID": "tenant-one",
            "ADMIRA_HOSTED_IMAGE_ACCESS_FILE": str(self.access_file),
            "ADMIRA_CENTRAL_IMAGE_CLIENT_KEY_FILE": str(self.client_key),
            "ADMIRA_CENTRAL_IMAGE_SOCKET": str(self.socket),
            # This is the corrected bind-mount simulation: both client and
            # broker address the tenant's output directory, not its parent.
            "ADMIRA_CENTRAL_IMAGE_EXCHANGE_ROOT": str(self.output),
        }

    def tearDown(self) -> None:
        self.server.close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def _generate(self, *, references=None, update_id=42):
        with patch.dict(os.environ, self.env, clear=False):
            return maybe_generate_central_image(
                "Create a clean square product image",
                output_root=self.output,
                output_name="creative",
                reference_image_paths=references or [],
                purpose="ad_creative",
                update_id=update_id,
                timeout=5,
            )

    def test_generates_without_reference_and_copies_only_to_tenant_output(self) -> None:
        result = self._generate()

        self.assertTrue(result["ok"], result)
        image = Path(result["image_path"])
        self.assertTrue(image.is_file())
        self.assertEqual(image.read_bytes(), PNG)
        self.assertTrue(image.resolve().is_relative_to(self.output.resolve()))
        self.assertEqual(result["backend"], "hosted-central-image")
        self.assertEqual(len(self.provider_calls), 1)
        self.assertEqual(self.provider_calls[0]["body"]["tenant_id"], "tenant-one")
        self.assertEqual(self.provider_calls[0]["body"]["request_id"], result["request_id"])
        self.assertEqual(self.provider_calls[0]["body"]["references"], [])
        self.assertFalse(any(path.name == "tenant-two" for path in self.host_exchange.iterdir()))

    def test_generates_with_reference_using_private_broker_snapshot(self) -> None:
        reference = self.input_dir / "buyer-reference.png"
        reference.write_bytes(PNG + b"-reference")
        reference.chmod(0o600)

        result = self._generate(references=[reference], update_id=43)

        self.assertTrue(result["ok"], result)
        image = Path(result["image_path"])
        self.assertEqual(image.read_bytes(), PNG)
        self.assertTrue(image.resolve().is_relative_to(self.output.resolve()))
        self.assertEqual(len(self.provider_calls), 1)
        request_body = self.provider_calls[0]["body"]
        self.assertEqual(request_body["tenant_id"], "tenant-one")
        self.assertEqual(request_body["request_id"], result["request_id"])
        references = request_body["references"]
        self.assertEqual(len(references), 1)
        self.assertTrue(
            Path(references[0]).resolve().is_relative_to(
                self.provider_calls[0]["workdir"].resolve()
            )
        )
        self.assertFalse(Path(references[0]).resolve().is_relative_to(self.output.resolve()))
        self.assertEqual(self.provider_calls[0]["reference_bytes"], [reference.read_bytes()])
        self.assertFalse(Path(references[0]).resolve().is_relative_to(self.input_dir.resolve()))


if __name__ == "__main__":
    unittest.main()
