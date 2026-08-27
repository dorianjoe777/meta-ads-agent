from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "contabo"
sys.path.insert(0, str(DEPLOY))
SPEC = importlib.util.spec_from_file_location("tenant_admin", DEPLOY / "tenant_admin.py")
tenant_admin = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(tenant_admin)


class TenantAdminTests(unittest.TestCase):
    def test_dry_run_validates_and_does_not_call_postgres(self):
        with tempfile.TemporaryDirectory() as raw, patch.object(tenant_admin.subprocess, "run") as run:
            result = tenant_admin.register(Path(raw), "buyer-001", "Buyer One", "1234", "5678", "5678", dry_run=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        run.assert_not_called()

    def test_register_uses_provisioner_secret_inside_postgres(self):
        response = json.dumps({"tenant_id": "00000000-0000-0000-0000-000000000001", "runtime_key": "buyer-001"})
        completed = type("Completed", (), {"returncode": 0, "stdout": response, "stderr": ""})()
        with tempfile.TemporaryDirectory() as raw, patch.object(tenant_admin.subprocess, "run", return_value=completed) as run:
            result = tenant_admin.register(Path(raw), "buyer-001", "Buyer One", "1234", "5678", "5678")
        self.assertTrue(result["ok"])
        self.assertFalse(result["buyer_traffic_started"])
        command = run.call_args.args[0]
        self.assertIn("admira_provisioner_login", " ".join(command))
        self.assertNotIn("telegram_bot_token", " ".join(command))
        self.assertNotIn("postgres_password", " ".join(command))

    def test_rejects_invalid_identifiers_before_writes(self):
        with tempfile.TemporaryDirectory() as raw, patch.object(tenant_admin, "provision") as provision:
            with self.assertRaises(ValueError):
                tenant_admin.register(Path(raw), "buyer-001", "Buyer", "token:secret", "1", "1")
            provision.assert_not_called()

    def test_issue_claim_sends_only_hash_to_postgres(self):
        response = json.dumps({"tenant_id": "00000000-0000-0000-0000-000000000001", "expires_at": "2026-08-27T20:00:00+00:00"})
        completed = type("Completed", (), {"returncode": 0, "stdout": response, "stderr": ""})()
        with tempfile.TemporaryDirectory() as raw, \
             patch.object(tenant_admin.secrets, "token_urlsafe", return_value="A" * 32), \
             patch.object(tenant_admin.subprocess, "run", return_value=completed) as run:
            result = tenant_admin.issue_claim(
                Path(raw), "buyer-001", "Buyer One", bot_username="AdmiraCentralBot"
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["claim_token"], "A" * 32)
        self.assertIn("?start=" + "A" * 32, result["telegram_url"])
        command = run.call_args.args[0]
        self.assertNotIn("A" * 32, command)
        self.assertIn(tenant_admin.hashlib.sha256(("A" * 32).encode()).hexdigest(), command)


if __name__ == "__main__":
    unittest.main()
