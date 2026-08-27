from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("tenantctl", ROOT / "deploy" / "contabo" / "tenantctl.py")
tenantctl = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(tenantctl)


class TenantCtlTests(unittest.TestCase):
    def test_strict_slug(self):
        for value in ("ab", "A-valid", "bad_slug", "../escape", "a" * 64):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    tenantctl.validate_tenant_id(value)
        self.assertEqual(tenantctl.validate_tenant_id("client-001"), "client-001")

    def test_dry_run_never_writes_or_runs(self):
        with tempfile.TemporaryDirectory() as raw, patch.object(tenantctl, "run") as run:
            base = Path(raw) / "tenants"
            result = tenantctl.provision(base, "client-001", dry_run=True)
            self.assertTrue(result["ok"])
            self.assertFalse(base.exists())
            run.assert_not_called()

    def test_provision_is_idempotent_and_secure(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            tenantctl.provision(base, "client-001")
            tenantctl.provision(base, "client-001")
            root = base / "client-001"
            self.assertEqual({p.name for p in root.iterdir()}, set(tenantctl.DIRS) | {"compose.yaml"})
            for name in tenantctl.DIRS:
                self.assertEqual((root / name).stat().st_mode & 0o777, 0o700)
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            text = (root / "compose.yaml").read_text()
            self.assertIn("image: admira-ia:r90", text)
            self.assertIn("name: admira-tenant-client-001", text)
            self.assertIn('restart: "no"', text)
            self.assertIn("cap_drop:", text)
            self.assertIn("cap_add:\n      - DAC_OVERRIDE", text)
            self.assertNotIn("FOWNER", text)
            self.assertNotIn("CHOWN", text)
            self.assertIn("no-new-privileges:true", text)
            self.assertNotIn("read_only: true", text)
            self.assertIn("HERMES_HOME: /app/runtime/hermes", text)
            self.assertIn("CODEX_HOME: /app/runtime/hermes/codex-auth", text)
            self.assertNotIn("/opt/admira", text)
            self.assertIn("/app/dashboard/data", text)
            self.assertNotIn("docker.sock", text)
            self.assertNotIn("ports:", text)
            self.assertNotIn("API_KEY", text)

    def test_limits_are_configurable_but_validated(self):
        text = tenantctl.compose_text(Path("/srv/admira/tenants/client-001"), "client-001", memory_limit="1g", cpu_limit="2.5", pids_limit=512)
        self.assertIn("mem_limit: 1g", text)
        self.assertIn("cpus: 2.5", text)
        self.assertIn("pids_limit: 512", text)
        with self.assertRaises(ValueError):
            tenantctl.compose_text(Path("/tmp/client-001"), "client-001", memory_limit="${SECRET}")
        with self.assertRaises(ValueError):
            tenantctl.compose_text(Path("/tmp/client-001"), "client-001", pids_limit=0)

    def test_lifecycle_uses_argv_and_tenant_compose(self):
        with tempfile.TemporaryDirectory() as raw, patch.object(tenantctl, "run") as run:
            run.return_value = type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
            result = tenantctl.lifecycle(Path(raw), "client-001", "start")
            self.assertTrue(result["ok"])
            run.assert_called_once()
            argv = run.call_args.args[0]
            self.assertEqual(argv[:2], ["docker", "compose"])
            self.assertEqual(argv[-5:], ["up", "-d", "--no-build", "--pull", "never"])
            self.assertIn("-p", argv)
            self.assertIn("admira-tenant-client-001", argv)
            self.assertNotIn("shell=True", argv)

    def test_suspend_removes_only_runtime_container(self):
        with tempfile.TemporaryDirectory() as raw, patch.object(tenantctl, "run") as run:
            run.return_value = type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
            result = tenantctl.lifecycle(Path(raw), "client-001", "suspend")
            self.assertTrue(result["ok"])
            argv = run.call_args.args[0]
            self.assertEqual(argv[-2:], ["down", "--remove-orphans"])
            self.assertNotIn("-v", argv)

    def test_plan_is_machine_readable(self):
        result = tenantctl.plan(Path("/srv/admira/tenants"), "client-001")
        self.assertEqual(result["image"], "admira-ia:r90")
        self.assertFalse(result["isolated"]["network_ports"])


if __name__ == "__main__":
    unittest.main()
