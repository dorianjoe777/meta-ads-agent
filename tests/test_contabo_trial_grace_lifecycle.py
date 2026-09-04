from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "deploy/contabo/db/migrations/018_trial_grace_lifecycle.sql").read_text(encoding="utf-8")
PREFLIGHT = (ROOT / "deploy/contabo/release-preflight.sh").read_text(encoding="utf-8")


class TrialGraceLifecycleMigrationTests(unittest.TestCase):
    def test_migration_has_explicit_grace_retention_and_notification_state(self):
        for column in (
            "grace_started_at", "grace_expires_at", "grace_next_notification_at",
            "grace_notification_sequence", "grace_runtime_suspended_at",
        ):
            self.assertIn(column, SQL)
        self.assertIn("interval '30 days'", SQL)
        self.assertIn("interval '3 days'", SQL)
        self.assertIn("tenant_grace_reminders", SQL)
        self.assertIn("UNIQUE (tenant_id, reminder_no)", SQL)

    def test_migration_exposes_explicit_extension_and_cleanup_boundaries(self):
        self.assertIn("lifecycle_state = 'grace'", SQL)
        self.assertIn("SET plan = 'trial', lifecycle_state = 'trial'", SQL)
        self.assertIn("trial_extended_from_grace", SQL)
        self.assertIn("grace_runtime_candidates", SQL)
        self.assertIn("grace_deletion_candidates", SQL)
        self.assertIn("delete_grace_tenant", SQL)
        self.assertIn("GRANT EXECUTE ON FUNCTION admira.enqueue_due_trial_grace_reminders()", SQL)

    def test_scheduler_owner_can_access_reminder_ledger_and_preflight_enforces_it(self):
        self.assertIn(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE admira.tenant_grace_reminders\n  TO admira_control_owner",
            SQL,
        )
        self.assertIn(
            "has_table_privilege(\n    'admira_control_owner',\n"
            "    'admira.tenant_grace_reminders',\n    'SELECT,INSERT,UPDATE,DELETE'",
            PREFLIGHT,
        )


if __name__ == "__main__":
    unittest.main()
