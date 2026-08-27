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
    def test_validate_turn_derives_stable_telegram_session(self):
        result = tenant_turn.validate_turn({"message": "Hola", "chat_id": "-100123", "update_id": 7})
        self.assertEqual(result["channel"], "telegram")
        self.assertEqual(result["session_key"], "agent:main:telegram:dm:-100123")
        self.assertEqual(result["update_id"], 7)

    def test_rejects_paths_and_malformed_ids(self):
        for payload in (
            {"message": "Hola", "chat_id": "not-an-id"},
            {"message": "Hola", "chat_id": "123", "image_path": "/tmp/secret"},
            {"message": "Hola", "chat_id": "123", "update_id": -1},
        ):
            with self.assertRaises(ValueError):
                tenant_turn.validate_turn(payload)

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
                result = tenant_turn.run_turn(Path(raw), "client-001", {"message": "Hola", "chat_id": "123"})
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
            result = tenant_turn.run_turn(Path(raw), "client-001", {"message": "Hola", "chat_id": "123"})
        self.assertEqual(result, {"ok": False, "error_code": "tenant_not_provisioned"})


if __name__ == "__main__":
    unittest.main()
