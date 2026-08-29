from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timezone
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
    def test_handler_preserves_safe_runtime_errors_but_masks_unexpected_failures(self):
        class FakeServer:
            replay = broker.ReplayWindow()
            key = KEY

            def __init__(self, failure):
                self.core = type("Core", (), {"handle": lambda _self, _body: (_ for _ in ()).throw(failure)})()

        class FakeHandler:
            def __init__(self, failure):
                self.rfile = io.BytesIO(
                    json.dumps(broker.sign_body(KEY, {"action": "status", "tenant_id": "client-001"})).encode()
                    + b"\n"
                )
                self.server = FakeServer(failure)
                self.response = None

            def _send(self, response):
                self.response = response

        for failure, expected in (
            (RuntimeError("runtime_start_failed"), "runtime_start_failed"),
            (RuntimeError("provider stderr must stay private"), "broker_failure"),
            (ValueError("runtime_capacity_exhausted"), "runtime_capacity_exhausted"),
            (Exception("unexpected"), "broker_failure"),
        ):
            handler = FakeHandler(failure)
            broker._Handler.handle(handler)
            self.assertEqual(handler.response, {"ok": False, "error_code": expected})

    def test_cron_snapshot_rejects_tenant_symlink(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "client-001"
            cron = root / "runtime" / "hermes" / "cron"
            cron.mkdir(parents=True)
            outside = Path(raw) / "outside.json"
            outside.write_text('[{"id":"leak","name":"host data"}]', encoding="utf-8")
            (cron / "jobs.json").symlink_to(outside)
            self.assertEqual(broker._cron_snapshot(root), [])

    def test_single_broker_process_lock_rejects_a_second_instance(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "broker.lock"
            first = broker._acquire_instance_lock(path)
            try:
                with self.assertRaisesRegex(RuntimeError, "broker_already_running"):
                    broker._acquire_instance_lock(path)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            finally:
                broker.fcntl.flock(first.fileno(), broker.fcntl.LOCK_UN)
                first.close()

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
            inbound = core._prepare_inbound(
                root,
                [{"ref": photo_ref, "kind": "photo", "mime_type": "image/jpeg"},
                 {"ref": video_ref, "kind": "video", "mime_type": "video/mp4"}],
                17,
            )
            self.assertEqual(len(inbound["image_paths"]), 1)
            self.assertEqual([item["kind"] for item in inbound["attachments"]], ["photo", "video"])
            self.assertEqual(inbound["attachments"][1]["mime_type"], "video/mp4")
            self.assertTrue(inbound["image_paths"][0].startswith("/app/output/telegram_uploads/"))
            materialized = root / "output" / Path(inbound["image_paths"][0]).relative_to("/app/output")
            self.assertEqual(materialized.read_bytes(), b"photo-bytes")
            self.assertEqual(stat.S_IMODE(materialized.stat().st_mode), 0o600)

    def test_turn_forwards_bounded_inbound_attachment_contract(self):
        with tempfile.TemporaryDirectory() as raw:
            base, spool = Path(raw) / "tenants", Path(raw) / "spool"
            root = base / "client-001"
            (root / "output").mkdir(parents=True)
            (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
            inbound = spool / "inbound"
            inbound.mkdir(parents=True)
            ref = "a" * 32 + ".pdf"
            (inbound / ref).write_bytes(b"pdf-bytes")
            core = broker.BrokerCore(tenants_base=base, spool_base=spool)
            seen = {}
            def fake_turn(_base, _tenant, payload):
                seen["payload"] = payload
                return {"ok": True, "reply": "ok"}
            with patch.object(core, "_active_managed_tenants", return_value={}), \
                 patch.object(broker, "lifecycle", return_value={"ok": True}), \
                 patch.object(broker, "run_turn", side_effect=fake_turn):
                result = core.handle({"action": "turn", "tenant_id": "client-001", "turn": {"message": "analiza", "chat_id": "1", "update_id": 1}, "media": [{"ref": ref, "kind": "document", "mime_type": "application/pdf"}]})
            self.assertTrue(result["ok"])
            self.assertNotIn("image_paths", seen["payload"])
            attachment = seen["payload"]["attachments"][0]
            self.assertEqual(attachment["kind"], "document")
            self.assertEqual(attachment["mime_type"], "application/pdf")
            self.assertTrue(str(attachment["path"]).startswith("/app/output/telegram_uploads/"))
            self.assertEqual(list((root / "output" / "telegram_uploads").iterdir()), [])

    def test_capacity_guard_allows_existing_and_rejects_new_tenant(self):
        with tempfile.TemporaryDirectory() as raw, patch.dict(os.environ, {"ADMIRA_MAX_ACTIVE_TENANTS": "2"}):
            base, spool = Path(raw) / "tenants", Path(raw) / "spool"
            root = base / "client-001"
            (root / "output").mkdir(parents=True)
            (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
            other = base / "client-003"
            (other / "output").mkdir(parents=True)
            (other / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
            core = broker.BrokerCore(tenants_base=base, spool_base=spool)
            with patch.object(core, "_active_managed_tenants", return_value={"client-001", "client-002"}), \
                 patch.object(broker, "lifecycle") as start:
                core._ensure_running("client-001")
                start.assert_not_called()
                with self.assertRaisesRegex(RuntimeError, "runtime_capacity_exhausted"):
                    core._ensure_running("client-003")

    def test_candidate_capacity_uses_six_normal_slots(self):
        with patch.dict(os.environ, {
            "ADMIRA_NORMAL_ACTIVE_TENANTS": "6",
            "ADMIRA_HARD_MAX_ACTIVE_TENANTS": "8",
            "ADMIRA_BURST_MIN_AVAILABLE_MB": "2048",
        }, clear=True):
            self.assertEqual(broker.BrokerCore._capacity_config(), (6, 8, 2048))

    def test_unconfigured_broker_keeps_safe_starter_capacity(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(broker.BrokerCore._capacity_config(), (4, 4, 2048))

    def test_burst_slots_require_memavailable_headroom(self):
        with patch.dict(os.environ, {
            "ADMIRA_NORMAL_ACTIVE_TENANTS": "6",
            "ADMIRA_HARD_MAX_ACTIVE_TENANTS": "8",
            "ADMIRA_BURST_MIN_AVAILABLE_MB": "2048",
        }, clear=True), patch.object(broker.BrokerCore, "_mem_available_bytes", return_value=3 * 1024**3):
            self.assertTrue(broker.BrokerCore._capacity_allows(6))
        with patch.dict(os.environ, {
            "ADMIRA_NORMAL_ACTIVE_TENANTS": "6",
            "ADMIRA_HARD_MAX_ACTIVE_TENANTS": "8",
            "ADMIRA_BURST_MIN_AVAILABLE_MB": "2048",
        }, clear=True), patch.object(broker.BrokerCore, "_mem_available_bytes", return_value=1024**3):
            self.assertFalse(broker.BrokerCore._capacity_allows(6))

    def test_unreadable_memavailable_rejects_only_burst_capacity(self):
        with patch.dict(os.environ, {
            "ADMIRA_NORMAL_ACTIVE_TENANTS": "6",
            "ADMIRA_HARD_MAX_ACTIVE_TENANTS": "8",
        }, clear=True), patch.object(
            broker.BrokerCore, "_mem_available_bytes",
            side_effect=RuntimeError("memory_headroom_unavailable"),
        ):
            self.assertIsNone(broker.BrokerCore._capacity_rejection(5))
            self.assertEqual(
                broker.BrokerCore._capacity_rejection(6),
                "runtime_capacity_headroom_low",
            )

    def test_capacity_hard_ceiling_and_bad_config_fail_closed(self):
        with patch.dict(os.environ, {
            "ADMIRA_NORMAL_ACTIVE_TENANTS": "6",
            "ADMIRA_HARD_MAX_ACTIVE_TENANTS": "8",
        }, clear=True):
            self.assertFalse(broker.BrokerCore._capacity_allows(8))
        with patch.dict(os.environ, {"ADMIRA_NORMAL_ACTIVE_TENANTS": "bad"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "capacity_config_invalid"):
                broker.BrokerCore._capacity_config()
        with patch.dict(os.environ, {
            "ADMIRA_NORMAL_ACTIVE_TENANTS": "7",
            "ADMIRA_HARD_MAX_ACTIVE_TENANTS": "6",
        }, clear=True):
            with self.assertRaisesRegex(RuntimeError, "capacity_config_invalid"):
                broker.BrokerCore._capacity_config()

    def test_capacity_check_failure_is_retryable_and_does_not_start(self):
        with tempfile.TemporaryDirectory() as raw:
            base, spool = Path(raw) / "tenants", Path(raw) / "spool"
            root = base / "client-001"
            (root / "output").mkdir(parents=True)
            (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
            core = broker.BrokerCore(tenants_base=base, spool_base=spool)
            with patch.object(core, "_active_managed_tenants", side_effect=RuntimeError("runtime_capacity_check_failed")), \
                 patch.object(broker, "lifecycle") as start:
                with self.assertRaisesRegex(RuntimeError, "runtime_capacity_check_failed"):
                    core._ensure_running("client-001")
                start.assert_not_called()

    def test_capacity_admission_does_not_restart_an_active_tenant(self):
        with tempfile.TemporaryDirectory() as raw:
            base, spool = Path(raw) / "tenants", Path(raw) / "spool"
            root = base / "client-001"
            root.mkdir(parents=True)
            (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
            core = broker.BrokerCore(tenants_base=base, spool_base=spool)
            with patch.object(core, "_active_managed_tenants", return_value={"client-001"}), \
                 patch.object(broker, "lifecycle") as lifecycle:
                self.assertEqual(core._ensure_running("client-001"), root)
                lifecycle.assert_not_called()

    def test_complete_reset_requires_fresh_private_request_and_restarts_pinned_runtime(self):
        with tempfile.TemporaryDirectory() as raw:
            base, spool = Path(raw) / "tenants", Path(raw) / "spool"
            root = base / "client-001"
            (root / "runtime").mkdir(parents=True)
            (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
            request = root / "runtime" / broker.HOSTED_RESET_REQUEST
            request.write_text(json.dumps({
                "status": "pending",
                "chat_id": "123",
                "user_id": "456",
                "requested_at": datetime.now(timezone.utc).isoformat(),
                "hosted_update_id": 99,
            }), encoding="utf-8")
            request.chmod(0o600)
            core = broker.BrokerCore(tenants_base=base, spool_base=spool)
            completed = type("Completed", (), {"returncode": 0, "stdout": '{"ok": true}', "stderr": ""})()
            with patch.object(core, "_active_managed_tenants", return_value={"client-001"}), \
                 patch.object(broker.subprocess, "run", return_value=completed) as run, \
                 patch.object(broker, "lifecycle", side_effect=[{"ok": True}, {"ok": True}]) as lifecycle:
                core._perform_complete_reset(
                    root, {"chat_id": "123", "user_id": "456", "update_id": 99}
                )
            self.assertIn("run", run.call_args.args[0])
            self.assertIn("--pull", run.call_args.args[0])
            self.assertEqual(run.call_args.args[0][-3:-1], ["admira", "-c"])
            self.assertEqual([call.args[2] for call in lifecycle.call_args_list], ["suspend", "start"])
            receipt = root / broker.HOSTED_RESET_RECEIPT
            self.assertEqual(json.loads(receipt.read_text(encoding="utf-8"))["update_id"], 99)
            self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)

            request.write_text(json.dumps({
                "status": "pending", "chat_id": "123", "user_id": "456",
                "requested_at": "2020-01-01T00:00:00+00:00", "hosted_update_id": 99,
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hosted_reset_not_authorized"):
                core._validated_reset_request(
                    root, {"chat_id": "123", "user_id": "456", "update_id": 99}
                )

            request.write_text(json.dumps({
                "status": "pending", "chat_id": "123", "user_id": "456",
                "requested_at": datetime.now(timezone.utc).isoformat(), "hosted_update_id": 99,
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hosted_reset_not_authorized"):
                core._validated_reset_request(
                    root, {"chat_id": "123", "user_id": "999", "update_id": 99}
                )

    def test_turn_executes_only_whitelisted_complete_reset_action(self):
        with tempfile.TemporaryDirectory() as raw:
            base, spool = Path(raw) / "tenants", Path(raw) / "spool"
            root = base / "client-001"
            (root / "output").mkdir(parents=True)
            (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
            core = broker.BrokerCore(tenants_base=base, spool_base=spool)
            run_result = {"ok": True, "reply": "confirmed", "control_action": "complete_reset"}
            with patch.object(core, "_active_managed_tenants", return_value={"client-001"}), \
                 patch.object(broker, "run_turn", return_value=run_result), \
                 patch.object(core, "_perform_complete_reset") as reset:
                result = core.handle({
                    "action": "turn", "tenant_id": "client-001",
                    "turn": {"message": "confirm", "chat_id": "123", "user_id": "456", "update_id": 1},
                    "media": [],
                })
            reset.assert_called_once_with(
                root, {"message": "confirm", "chat_id": "123", "user_id": "456", "update_id": 1}
            )
            self.assertTrue(result["ok"])
            self.assertIn("Reinicié completamente", result["reply"])

    def test_completed_reset_receipt_replays_success_without_model(self):
        with tempfile.TemporaryDirectory() as raw:
            base, spool = Path(raw) / "tenants", Path(raw) / "spool"
            root = base / "client-001"
            root.mkdir(parents=True)
            (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
            core = broker.BrokerCore(tenants_base=base, spool_base=spool)
            turn = {"message": "Si quiero resetear completamente", "chat_id": "123", "user_id": "456", "update_id": 77, "language": "en"}
            core._write_reset_receipt(root, turn)
            with patch.object(core, "_active_managed_tenants", return_value={"client-001"}), \
                 patch.object(broker, "run_turn") as run_turn:
                result = core.handle({"action": "turn", "tenant_id": "client-001", "turn": turn, "media": []})
            run_turn.assert_not_called()
            self.assertTrue(result["ok"])
            self.assertIn("completely reset", result["reply"])

    def test_completed_reset_replay_bypasses_full_capacity(self):
        with tempfile.TemporaryDirectory() as raw:
            base, spool = Path(raw) / "tenants", Path(raw) / "spool"
            root = base / "client-001"
            root.mkdir(parents=True)
            (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
            core = broker.BrokerCore(tenants_base=base, spool_base=spool)
            turn = {"message": "confirm", "chat_id": "123", "user_id": "456", "update_id": 80}
            core._write_reset_receipt(root, turn)
            with patch.object(core, "_active_managed_tenants") as active, \
                 patch.object(broker, "run_turn") as run_turn, \
                 patch.object(broker, "lifecycle") as lifecycle:
                result = core.handle({
                    "action": "turn", "tenant_id": "client-001", "turn": turn, "media": []
                })
            active.assert_not_called()
            run_turn.assert_not_called()
            lifecycle.assert_not_called()
            self.assertTrue(result["ok"])

    def test_in_progress_reset_receipt_resumes_without_model_or_request_file(self):
        with tempfile.TemporaryDirectory() as raw:
            base, spool = Path(raw) / "tenants", Path(raw) / "spool"
            root = base / "client-001"
            root.mkdir(parents=True)
            (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
            core = broker.BrokerCore(tenants_base=base, spool_base=spool)
            turn = {
                "message": "Si quiero resetear completamente",
                "chat_id": "123", "user_id": "456", "update_id": 78,
            }
            core._write_reset_receipt(root, turn, status_value="in_progress")
            completed = type(
                "Completed", (), {"returncode": 0, "stdout": '{"ok": true}', "stderr": ""}
            )()
            with patch.object(core, "_active_managed_tenants", return_value={"client-001"}), \
                 patch.object(broker, "run_turn") as run_turn, \
                 patch.object(broker.subprocess, "run", return_value=completed), \
                 patch.object(broker, "lifecycle", side_effect=[{"ok": True}, {"ok": True}]):
                result = core.handle({
                    "action": "turn", "tenant_id": "client-001", "turn": turn, "media": []
                })
            run_turn.assert_not_called()
            self.assertTrue(result["ok"])
            receipt = json.loads((root / broker.HOSTED_RESET_RECEIPT).read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "completed")

    def test_in_progress_reset_finishes_but_stays_asleep_when_capacity_is_full(self):
        with tempfile.TemporaryDirectory() as raw, patch.dict(
            os.environ, {"ADMIRA_MAX_ACTIVE_TENANTS": "2"}
        ):
            base, spool = Path(raw) / "tenants", Path(raw) / "spool"
            root = base / "client-001"
            root.mkdir(parents=True)
            (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
            core = broker.BrokerCore(tenants_base=base, spool_base=spool)
            turn = {"message": "confirm", "chat_id": "123", "user_id": "456", "update_id": 81}
            core._write_reset_receipt(root, turn, status_value="in_progress")
            completed = type(
                "Completed", (), {"returncode": 0, "stdout": '{"ok": true}', "stderr": ""}
            )()
            with patch.object(core, "_active_managed_tenants", return_value={"client-002", "client-003"}), \
                 patch.object(broker.subprocess, "run", return_value=completed), \
                 patch.object(broker, "run_turn") as run_turn, \
                 patch.object(broker, "lifecycle", return_value={"ok": True}) as lifecycle:
                result = core.handle({
                    "action": "turn", "tenant_id": "client-001", "turn": turn, "media": []
                })
            run_turn.assert_not_called()
            self.assertTrue(result["ok"])
            self.assertEqual([call.args[2] for call in lifecycle.call_args_list], ["suspend"])
            receipt = json.loads((root / broker.HOSTED_RESET_RECEIPT).read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "completed")

    def test_failed_reset_keeps_in_progress_receipt_for_safe_retry(self):
        with tempfile.TemporaryDirectory() as raw:
            base, spool = Path(raw) / "tenants", Path(raw) / "spool"
            root = base / "client-001"
            (root / "runtime").mkdir(parents=True)
            (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
            turn = {"chat_id": "123", "user_id": "456", "update_id": 79}
            request = root / "runtime" / broker.HOSTED_RESET_REQUEST
            request.write_text(json.dumps({
                "status": "pending", "chat_id": "123", "user_id": "456",
                "hosted_update_id": 79,
                "requested_at": datetime.now(timezone.utc).isoformat(),
            }), encoding="utf-8")
            request.chmod(0o600)
            core = broker.BrokerCore(tenants_base=base, spool_base=spool)
            failed = type(
                "Completed", (), {"returncode": 1, "stdout": "", "stderr": "reset failed"}
            )()
            with patch.object(core, "_active_managed_tenants", return_value={"client-001"}), \
                 patch.object(broker.subprocess, "run", return_value=failed), \
                 patch.object(broker, "lifecycle", side_effect=[{"ok": True}, {"ok": True}]):
                with self.assertRaisesRegex(RuntimeError, "hosted_reset_failed"):
                    core._perform_complete_reset(root, turn)
            receipt = json.loads((root / broker.HOSTED_RESET_RECEIPT).read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "in_progress")

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
            with patch.object(core, "_active_managed_tenants", return_value=set()), patch.object(broker, "lifecycle", return_value={"ok": True}), patch.object(
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
