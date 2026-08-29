from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("tenant_turn", ROOT / "deploy" / "contabo" / "tenant_turn.py")
tenant_turn = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(tenant_turn)


class TenantTurnTests(unittest.TestCase):
    def test_validate_turn_forwards_user_and_normalizes_hosted_command(self):
        result = tenant_turn.validate_turn({
            "message": "/restart@central_bot",
            "chat_id": "123",
            "user_id": "456",
        })
        self.assertEqual(result["user_id"], "456")
        self.assertEqual(result["command"], "restart")

    def test_session_generation_is_chat_scoped_and_increments_only_reset_commands(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "runtime" / "generations.json"
            self.assertEqual(tenant_turn._session_generation(path, "123"), 0)
            self.assertEqual(tenant_turn._session_generation(path, "123", increment=True), 1)
            self.assertEqual(tenant_turn._session_generation(path, "456"), 0)
            self.assertEqual(tenant_turn._session_generation(path, "123"), 1)

    def test_session_rotation_is_idempotent_per_telegram_update(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "runtime" / "generations.json"
            self.assertEqual(
                tenant_turn._session_generation(path, "123", increment=True, update_id=77), 1
            )
            self.assertEqual(
                tenant_turn._session_generation(path, "123", increment=True, update_id=77), 1
            )
            self.assertEqual(
                tenant_turn._session_generation(path, "123", increment=True, update_id=78), 2
            )
            self.assertEqual(tenant_turn._session_generation(path, "123"), 2)

    def test_session_generation_rejects_tenant_symlinks_and_corrupt_values(self):
        with tempfile.TemporaryDirectory() as raw:
            runtime = Path(raw) / "runtime"
            runtime.mkdir()
            outside = Path(raw) / "outside.json"
            outside.write_text('{"123":{"generation":99}}', encoding="utf-8")
            path = runtime / "generations.json"
            path.symlink_to(outside)
            self.assertEqual(tenant_turn._session_generation(path, "123"), 0)
            self.assertEqual(
                tenant_turn._session_generation(path, "123", increment=True, update_id=8), 1
            )
            self.assertEqual(json.loads(outside.read_text())["123"]["generation"], 99)
            path.write_text('{"123":{"generation":"invalid"}}', encoding="utf-8")
            self.assertEqual(tenant_turn._session_generation(path, "123"), 0)

    def test_public_runtime_result_preserves_only_complete_reset_control_action(self):
        result = tenant_turn._public_runtime_result({
            "ok": True,
            "reply": "confirmed",
            "control_action": "complete_reset",
        })
        self.assertEqual(result["control_action"], "complete_reset")
        self.assertNotIn("other_action", tenant_turn._public_runtime_result({
            "ok": True, "reply": "ok", "control_action": "delete_everything",
        }))

    def test_validate_turn_derives_stable_telegram_session(self):
        result = tenant_turn.validate_turn({"message": "Hola", "chat_id": "-100123", "user_id": "456", "update_id": 7})
        self.assertEqual(result["channel"], "telegram")
        self.assertEqual(result["session_key"], "agent:main:telegram:dm:-100123")
        self.assertEqual(result["update_id"], 7)

    def test_rejects_paths_and_malformed_ids(self):
        for payload in (
            {"message": "Hola", "chat_id": "not-an-id", "user_id": "456"},
            {"message": "Hola", "chat_id": "123", "user_id": "456", "image_path": "/tmp/secret"},
            {"message": "Hola", "chat_id": "123", "user_id": "456", "image_paths": ["/etc/passwd"]},
            {"message": "Hola", "chat_id": "123", "user_id": "456", "update_id": -1},
        ):
            with self.assertRaises(ValueError):
                tenant_turn.validate_turn(payload)

    def test_accepts_only_broker_materialized_images(self):
        path = "/app/output/telegram_uploads/a1b2c3d4e5f60718/0011223344556677.png"
        result = tenant_turn.validate_turn({"message": "Mira esto", "chat_id": "123", "user_id": "456", "image_paths": [path]})
        self.assertEqual(result["image_paths"], [path])

    def test_accepts_bounded_broker_attachment_contract(self):
        path = "/app/output/telegram_uploads/a1b2c3d4e5f60718/0011223344556677.pdf"
        result = tenant_turn.validate_turn({
            "message": "Revisa el catálogo",
            "chat_id": "123",
            "user_id": "456",
            "attachments": [{
                "kind": "document",
                "path": path,
                "mime_type": "application/pdf",
                "size": 100,
                "sha256": "a" * 64,
            }],
        })
        self.assertEqual(result["attachments"][0]["path"], path)
        with self.assertRaises(ValueError):
            tenant_turn.validate_turn({
                "message": "Revisa",
                "chat_id": "123",
                "user_id": "456",
                "attachments": [{
                    "kind": "document", "path": "/etc/passwd",
                    "mime_type": "text/plain", "size": 10, "sha256": "b" * 64,
                }],
            })

    def test_run_turn_uses_stdin_and_sanitizes_runtime_errors(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "client-001"
            root.mkdir()
            (root / "compose.yaml").write_text("services:\n  admira:\n    image: admira-ia:r90\n")
            completed = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": json.dumps({"ok": False, "error": "secret provider details", "error_type": "model_usage_limit"}), "stderr": ""},
            )()
            with patch.object(tenant_turn.subprocess, "run", return_value=completed) as run:
                result = tenant_turn.run_turn(Path(raw), "client-001", {"message": "Hola", "chat_id": "123", "user_id": "456"})
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "model_usage_limit")
            self.assertNotIn("secret", json.dumps(result).lower())
            argv = run.call_args.args[0]
            self.assertEqual(argv[:6], ["docker", "compose", "-p", "admira-tenant-client-001", "-f", str(root / "compose.yaml")])
            self.assertEqual(argv[6:9], ["exec", "-T", "admira"])
            self.assertNotIn("Hola", argv)
            self.assertEqual(json.loads(run.call_args.kwargs["input"])["message"], "Hola")

    def test_run_turn_requires_provisioned_tenant(self):
        with tempfile.TemporaryDirectory() as raw:
            result = tenant_turn.run_turn(Path(raw), "client-001", {"message": "Hola", "chat_id": "123", "user_id": "456"})
        self.assertEqual(result, {"ok": False, "error_code": "tenant_not_provisioned"})


if __name__ == "__main__":
    unittest.main()
