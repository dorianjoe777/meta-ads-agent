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
        self.assertIn("007_trial_provider_lifecycle.sql", text)
        self.assertIn("008_central_image_jobs.sql", text)
        self.assertIn("provider_admin.py", text)
        self.assertIn("gemini_pool_admin.py", text)
        self.assertIn("image_broker.py", text)
        self.assertIn("central_image_service.py", text)
        self.assertIn("prepare-central-image-broker.sh", text)
        self.assertIn("transition_hosted_tenant_to_licensed", text)
        self.assertIn("personal_chatgpt", text)
        self.assertIn("central image service remains fail-closed by default", text)
        self.assertIn("GEMINI_MODELS_URL", text)
        self.assertIn("x-goog-api-client", text)
        self.assertIn("allow-unverified", text)
        self.assertIn("Gemini credential health check is official-endpoint", text)
        self.assertIn("record_metadata=record_metadata", text)
        self.assertIn("cleanup_pending", text)
        self.assertIn("legacy host-wide Gemini key is absent", text)
        self.assertIn("count(*) = 3", text)
        self.assertIn("tenant.status = ''active''", text)
        self.assertIn("p_error_code = ''telegram_rate_limited''", text)
        self.assertIn("ADMIRA_TENANTS_BASE", text)
        self.assertIn("--profile buyers config --quiet", text)
        self.assertIn("--profile central-images config --quiet", text)
        self.assertIn("--profile recovery-email config --quiet", text)
        self.assertIn("recovery_identity.py", text)
        self.assertIn("recovery_service.py", text)
        self.assertIn("recovery_email_worker.py", text)
        self.assertIn("recovery_smtp.py", text)
        self.assertIn("Telegram recovery runtime and email-worker integration is present", text)
        self.assertIn("Telegram recovery must remain disabled by default in .env.example", text)
        self.assertIn("ADMIRA_SMTP_HOST and ADMIRA_SMTP_FROM are required when recovery is enabled", text)
        self.assertIn("recovery-email worker is not running while recovery is enabled", text)
        self.assertIn("recovery secret owner UID must be", text)
        self.assertIn("tenant_recovery_delivery_outbox", text)
        self.assertIn("claim_recovery_email_outbox", text)
        self.assertIn("ack_recovery_email_outbox", text)
        self.assertIn("admira_email_delivery", text)
        self.assertIn("recovery_db_password.txt", text)
        self.assertIn("two canary tenant IDs are required in server mode", text)
        self.assertIn("central Codex auth pool must declare 2-8 unique account IDs", text)
        self.assertIn("central Codex auth.json is missing or empty", text)
        self.assertIn("central Codex auth home must be mode 0700", text)

    def test_recovery_defaults_are_dormant_and_activation_is_fail_closed(self):
        env_example = (SCRIPT.parent / ".env.example").read_text(encoding="utf-8")
        self.assertRegex(env_example, r"(?m)^ADMIRA_TELEGRAM_RECOVERY_READY=false$")
        text = SCRIPT.read_text(encoding="utf-8")
        for secret in (
            "recovery_hmac_key.txt",
            "recovery_delivery_key.txt",
            "recovery_db_password.txt",
            "email_delivery_db_password.txt",
            "smtp_username.txt",
            "smtp_password.txt",
        ):
            self.assertIn(secret, text)
        self.assertIn("ADMIRA_SMTP_SECURITY must be starttls or ssl", text)

    def test_recovery_activation_gate_is_inside_server_path(self):
        text = SCRIPT.read_text(encoding="utf-8")
        runtime_start = text.index("if grep -q 'RecoveryHandler'")
        runtime_end = text.index("if [[ -n \"$TENANT_A\"", runtime_start)
        runtime_block = text[runtime_start:runtime_end]
        self.assertIn('if [[ "$MODE" == server ]]; then', runtime_block)
        self.assertIn('recovery_ready="$(resolve_compose_value', runtime_block)
        self.assertNotIn('recovery_ready="${ADMIRA_TELEGRAM_RECOVERY_READY:-false}"', runtime_block)
        self.assertIn("resolve_compose_value ADMIRA_SMTP_HOST", runtime_block)
        self.assertIn("resolve_compose_value ADMIRA_SERVICE_UID", runtime_block)

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
