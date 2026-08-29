"""Static contract tests for the runtime-capacity migration.

These tests intentionally inspect the SQL contract rather than connecting to a
database. They keep the fencing and non-terminal contention invariants visible
in CI while the Contabo database is provisioned separately.
"""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "deploy" / "contabo" / "db" / "migrations" / "006_runtime_capacity_queue.sql"


class CapacityQueueMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8")

    def test_capacity_deferral_is_non_terminal_and_does_not_consume_normal_attempts(self):
        body = self.sql[self.sql.index("CREATE OR REPLACE FUNCTION admira.defer_telegram_update_capacity"):]
        body = body[:body.index("CREATE OR REPLACE FUNCTION admira.claim_idle_runtime")]
        self.assertIn("status = 'retry'", body)
        self.assertNotIn("status = 'dead'", body)
        self.assertRegex(body, r"attempt_count\s*=\s*greatest\(0,\s*attempt_count\s*-\s*1\)")
        self.assertIn("capacity_deferrals = capacity_deferrals + 1", body)

    def test_only_contention_reasons_are_accepted(self):
        self.assertIn("'tenant_busy', 'runtime_capacity_exhausted'", self.sql)
        self.assertIn("'runtime_capacity_exhausted'", self.sql)
        self.assertIn("'tenant_busy'", self.sql)

    def test_idle_claim_has_fencing_and_expiry(self):
        body = self.sql[self.sql.index("CREATE OR REPLACE FUNCTION admira.claim_idle_runtime"):]
        body = body[:body.index("CREATE OR REPLACE FUNCTION admira.complete_idle_runtime")]
        self.assertRegex(body, r"lease_token\s*=\s*gen_random_uuid\(\)")
        self.assertRegex(body, r"holder\s*=\s*claim_holder")
        self.assertRegex(body, r"expires_at\s*=\s*now\(\)\s*\+")
        self.assertRegex(body, r"FOR UPDATE OF (?:l|runtime) SKIP LOCKED")

    def test_stopping_claim_has_recovery_path(self):
        self.assertIn("state = 'stopping'", self.sql)
        self.assertRegex(self.sql, r"expires_at IS NULL OR expires_at < now\(\)")
        self.assertGreaterEqual(self.sql.count("AND expires_at >= now()"), 2)

    def test_scheduler_capacity_is_non_terminal_and_least_privilege(self):
        body = self.sql[self.sql.index("CREATE OR REPLACE FUNCTION admira.defer_scheduled_job_capacity"):]
        body = body[:body.index("CREATE OR REPLACE FUNCTION admira.claim_idle_runtime")]
        self.assertIn("status = 'queued'", body)
        self.assertIn("attempt_count = greatest(0, attempt_count - 1)", body)
        self.assertIn("capacity_deferrals = capacity_deferrals + 1", body)
        self.assertNotIn("enabled = false", body)
        self.assertIn("TO admira_scheduler", self.sql)

    def test_idle_claim_excludes_busy_and_eligible_work(self):
        body = self.sql[self.sql.index("CREATE OR REPLACE FUNCTION admira.claim_idle_runtime"):]
        body = body[:body.index("CREATE OR REPLACE FUNCTION admira.complete_idle_runtime")]
        self.assertRegex(body, r"(?:l|runtime)\.holder IS NULL")
        self.assertRegex(body, r"(?:u|processing_update)\.status = 'processing'")
        self.assertRegex(body, r"(?:u|queued_update)\.status IN \('received', 'retry'\)")
        self.assertRegex(body, r"(?:j|scheduled_job)\.enabled")
        self.assertRegex(body, r"(?:j|scheduled_job)\.leased_until")
        self.assertRegex(body, r"(?:u|queued_update)\.available_at <= now\(\)")

    def test_least_privilege_function_grants(self):
        self.assertIn("REVOKE ALL ON FUNCTION", self.sql)
        self.assertIn("TO admira_runtime", self.sql)
        self.assertNotRegex(self.sql, r"GRANT EXECUTE ON FUNCTION[^;]+ TO PUBLIC")


if __name__ == "__main__":
    unittest.main()
