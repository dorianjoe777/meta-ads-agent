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
        self.assertIn("005_telegram_rate_limit_retry.sql", text)
        self.assertIn("count(*) = 3", text)
        self.assertIn("tenant.status = ''active''", text)
        self.assertIn("p_error_code = ''telegram_rate_limited''", text)
        self.assertIn("ADMIRA_TENANTS_BASE", text)
        self.assertIn("--profile buyers config --quiet", text)
        self.assertIn("two canary tenant IDs are required in server mode", text)

    def test_help_does_not_touch_or_require_runtime(self):
        result = subprocess.run([str(SCRIPT), "--help"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--server", result.stdout)

    def test_local_preflight_reports_token_state_without_printing_value(self):
        result = subprocess.run([str(SCRIPT), "--local"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            "Telegram token is intentionally absent" in result.stdout
            or "Telegram token is present with private permissions" in result.stdout
        )
        token_path = SCRIPT.parent / "secrets" / "telegram_bot_token.txt"
        token = token_path.read_text(encoding="utf-8").strip() if token_path.is_file() else ""
        if token:
            self.assertNotIn(token, result.stdout + result.stderr)
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
