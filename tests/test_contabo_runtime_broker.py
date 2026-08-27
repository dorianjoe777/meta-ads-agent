from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy" / "contabo"))
SPEC = importlib.util.spec_from_file_location("runtime_broker", ROOT / "deploy" / "contabo" / "runtime_broker.py")
broker = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(broker)


KEY = b"k" * 32


class RuntimeBrokerTests(unittest.TestCase):
    def test_signed_envelope_verifies_and_replay_is_rejected(self):
        envelope = broker.sign_body(KEY, {"action": "status", "tenant_id": "client-001"}, now=1000, nonce="a" * 32)
        replay = broker.ReplayWindow()
        self.assertEqual(replay.verify(envelope, KEY, now=1000), envelope["body"])
        with self.assertRaisesRegex(ValueError, "replayed_request"):
            replay.verify(envelope, KEY, now=1000)

    def test_signature_tamper_expiry_and_nonce_are_rejected(self):
        envelope = broker.sign_body(KEY, {"action": "status", "tenant_id": "client-001"}, now=1000, nonce="b" * 32)
        tampered = dict(envelope)
        tampered["body"] = {"action": "suspend", "tenant_id": "client-001"}
        with self.assertRaisesRegex(ValueError, "invalid_signature"):
            broker.ReplayWindow().verify(tampered, KEY, now=1000)
        with self.assertRaisesRegex(ValueError, "expired_request"):
            broker.ReplayWindow().verify(envelope, KEY, now=1091)
        malformed = dict(envelope, nonce="not-a-valid-nonce")
        with self.assertRaisesRegex(ValueError, "invalid_envelope"):
            broker.ReplayWindow().verify(malformed, KEY, now=1000)

    def test_safe_media_ref_and_regular_file_reject_escape_symlink_and_oversize(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "inbound"
            root.mkdir()
            good = root / ("a" * 32 + ".png")
            good.write_bytes(b"image")
            self.assertEqual(broker._safe_ref(good.name), good.name)
            self.assertEqual(broker._regular_file(good, root), good.resolve())
            with self.assertRaisesRegex(ValueError, "invalid_media_ref"):
                broker._safe_ref("../../etc/passwd")
            outside = Path(raw) / "outside.bin"
            outside.write_bytes(b"secret")
            link = root / ("b" * 32 + ".png")
            link.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "media_path_escape"):
                broker._regular_file(link, root)
            large = root / ("c" * 32 + ".bin")
            large.write_bytes(b"1234")
            with self.assertRaisesRegex(ValueError, "invalid_media_file"):
                broker._regular_file(large, root, limit=3)

    def test_prepare_inbound_copies_media_to_opaque_tenant_output(self):
        with tempfile.TemporaryDirectory() as raw:
            base, spool = Path(raw) / "tenants", Path(raw) / "spool"
            root = base / "client-001"
            (root / "output").mkdir(parents=True)
            (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
            inbound = spool / "inbound"
            inbound.mkdir(parents=True)
            photo_ref = "a" * 32 + ".jpg"
            video_ref = "b" * 32 + ".mp4"
            (inbound / photo_ref).write_bytes(b"photo-bytes")
            (inbound / video_ref).write_bytes(b"video-bytes")
            core = broker.BrokerCore(tenants_base=base, spool_base=spool)
            self.assertEqual(stat.S_IMODE((spool / "inbound").stat().st_mode), 0o770)
            self.assertEqual(stat.S_IMODE((spool / "outbound").stat().st_mode), 0o770)
            image_paths = core._prepare_inbound(
                root,
                [{"ref": photo_ref}, {"ref": video_ref}],
                17,
            )
            self.assertEqual(len(image_paths), 1)
            self.assertTrue(image_paths[0].startswith("/app/output/telegram_uploads/"))
            materialized = root / "output" / Path(image_paths[0]).relative_to("/app/output")
            self.assertEqual(materialized.read_bytes(), b"photo-bytes")
            self.assertEqual(stat.S_IMODE(materialized.stat().st_mode), 0o600)

    def test_stage_outbound_returns_opaque_ref_kind_and_sha256(self):
        with tempfile.TemporaryDirectory() as raw:
            base, spool = Path(raw) / "tenants", Path(raw) / "spool"
            root = base / "client-001"
            output = root / "output" / "generated"
            output.mkdir(parents=True)
            (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
            source = output / "creative.png"
            source.write_bytes(b"generated-image")
            outside = base / "outside.txt"
            outside.write_bytes(b"not-an-output")
            core = broker.BrokerCore(tenants_base=base, spool_base=spool)
            result = core._stage_outbound(root, ["/app/output/generated/creative.png"])
            self.assertEqual(len(result), 1)
            item = result[0]
            self.assertEqual(item["kind"], "photo")
            self.assertRegex(item["ref"], r"^[a-f0-9]{48}\.png$")
            self.assertEqual(item["sha256"], hashlib.sha256(b"generated-image").hexdigest())
            staged = spool / "outbound" / item["ref"]
            self.assertEqual(staged.read_bytes(), b"generated-image")
            self.assertEqual(stat.S_IMODE(staged.stat().st_mode), 0o660)
            with self.assertRaisesRegex(ValueError, "media_path_escape"):
                core._stage_outbound(root, ["/app/output/../../outside.txt"])

    def test_turn_strips_media_directive_and_returns_staged_media(self):
        with tempfile.TemporaryDirectory() as raw:
            base, spool = Path(raw) / "tenants", Path(raw) / "spool"
            root = base / "client-001"
            (root / "output").mkdir(parents=True)
            (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
            generated = root / "output" / "result.png"
            generated.write_bytes(b"result")
            core = broker.BrokerCore(tenants_base=base, spool_base=spool)
            run_result = {
                "ok": True,
                "reply": "Listo\nMEDIA:/app/output/result.png",
                "media_paths": ["/app/output/result.png"],
                "error_code": "",
            }
            with patch.object(broker, "lifecycle", return_value={"ok": True}), patch.object(
                broker, "run_turn", return_value=run_result
            ):
                result = core.handle({"action": "turn", "tenant_id": "client-001", "turn": {"message": "hola", "chat_id": "1", "update_id": 1}, "media": []})
            self.assertTrue(result["ok"])
            self.assertEqual(result["reply"], "Listo")
            # This assertion intentionally guards against duplicate delivery entries.
            self.assertEqual(len(result["media"]), 1)
            self.assertEqual(result["media"][0]["kind"], "photo")
            self.assertNotIn("MEDIA:", result["reply"])

    def test_handle_rejects_unsupported_action_and_status_uses_mock_lifecycle(self):
        with tempfile.TemporaryDirectory() as raw:
            base, spool = Path(raw) / "tenants", Path(raw) / "spool"
            root = base / "client-001"
            root.mkdir(parents=True)
            with patch.object(broker, "status", return_value={"ok": True, "output": "running"}):
                result = broker.BrokerCore(tenants_base=base, spool_base=spool).handle(
                    {"action": "status", "tenant_id": "client-001"}
                )
            self.assertEqual(result, {"ok": True, "running": True})
            with patch.object(broker, "status", return_value={"ok": False, "output": "missing compose file"}):
                result = broker.BrokerCore(tenants_base=base, spool_base=spool).handle(
                    {"action": "status", "tenant_id": "client-001"}
                )
            self.assertEqual(result, {"ok": False, "running": False})
            with self.assertRaisesRegex(ValueError, "unsupported_action"):
                broker.BrokerCore(tenants_base=base, spool_base=spool).handle(
                    {"action": "delete_everything", "tenant_id": "client-001"}
                )

    def test_client_signs_request_and_parses_mock_broker_response(self):
        class FakeKeyFile:
            def read_bytes(self):
                return KEY

        class FakeSocket:
            def __init__(self):
                self.sent = b""

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def settimeout(self, _timeout):
                pass

            def connect(self, _path):
                pass

            def sendall(self, wire):
                self.sent += wire

            def recv(self, _size):
                return json.dumps({"ok": True, "running": True}).encode() + b"\n"

        fake = FakeSocket()
        with patch.object(broker, "_load_key", return_value=KEY), patch.object(
            broker.socket, "socket", return_value=fake
        ):
            result = broker.BrokerClient(Path("/tmp/broker.sock"), Path("/tmp/key")).request(
                {"action": "status", "tenant_id": "client-001"}
            )
        self.assertEqual(result, {"ok": True, "running": True})
        envelope = json.loads(fake.sent.decode())
        self.assertEqual(broker.ReplayWindow().verify(envelope, KEY, now=envelope["timestamp"]),
                         {"action": "status", "tenant_id": "client-001"})



if __name__ == "__main__":
    unittest.main()
