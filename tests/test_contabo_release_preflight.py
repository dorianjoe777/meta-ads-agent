from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "contabo" / "release-preflight.sh"


class ReleasePreflightTests(unittest.TestCase):
    def test_script_is_executable_and_read_only_by_contract(self):
        self.assertTrue(SCRIPT.stat().st_mode & 0o111)
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("Read-only release gate", text)
        self.assertNotIn("docker compose.* up", text)
        self.assertNotIn("CREATE TENANT", text)
        self.assertIn("admira-ia:r90", text)
        self.assertIn("004_active_tenant_runtime_gate.sql", text)
        self.assertIn("count(*) = 3", text)
        self.assertIn("tenant.status = ''active''", text)
        self.assertIn("ADMIRA_TENANTS_BASE", text)
        self.assertIn("--profile buyers config --quiet", text)
        self.assertIn("two canary tenant IDs are required in server mode", text)

    def test_help_does_not_touch_or_require_runtime(self):
        result = subprocess.run([str(SCRIPT), "--help"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--server", result.stdout)

    def test_local_preflight_reports_missing_token_without_printing_value(self):
        result = subprocess.run([str(SCRIPT), "--local"], text=True, capture_output=True)
        # Local preparation is allowed to omit the real bot token, but all
        # structural checks should remain green.
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Telegram token is intentionally absent", result.stdout)
        self.assertNotIn("BOT_TOKEN", result.stdout)

    def test_invalid_canary_ids_are_rejected_without_path_inspection(self):
        result = subprocess.run(
            [str(SCRIPT), "--local", "--tenant-a", "../../etc", "--tenant-b", "buyer-two"],
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("valid tenant slugs", result.stderr)
        self.assertNotIn("/etc/compose.yaml", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
