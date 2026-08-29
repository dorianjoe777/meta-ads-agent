from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "deploy" / "contabo" / "db" / "migrations" / "005_telegram_rate_limit_retry.sql"


class TelegramRateLimitRetryMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8")

    def test_rate_limit_is_retryable_beyond_normal_attempt_budget(self):
        self.assertIn("FUNCTION admira.ack_telegram_outbox", self.sql)
        self.assertIn("WHEN p_error_code = 'telegram_rate_limited' THEN 'retry'", self.sql)
        self.assertIn("WHEN p_error_code = 'telegram_rate_limited'", self.sql)
        self.assertIn("THEN now() + make_interval(secs => p_retry_after_seconds)", self.sql)

    def test_fencing_and_retry_bounds_are_preserved(self):
        self.assertIn("p_retry_after_seconds NOT BETWEEN 1 AND 86400", self.sql)
        self.assertIn("p_max_attempts NOT BETWEEN 1 AND 20", self.sql)
        self.assertIn("status = 'sending' AND lease_token = p_lease_token", self.sql)

    def test_replacement_function_remains_least_privilege(self):
        signature = "admira.ack_telegram_outbox(uuid, uuid, boolean, bigint, text, integer, integer)"
        self.assertIn(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC", self.sql)
        self.assertIn(f"GRANT EXECUTE ON FUNCTION {signature}", self.sql)
        self.assertIn(f"ALTER FUNCTION {signature}", self.sql)
        self.assertIn("OWNER TO admira_control_owner", self.sql)


if __name__ == "__main__":
    unittest.main()
