import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "contabo"
MIGRATION = (DEPLOY / "db/migrations/012_personal_chatgpt_sponsorship.sql").read_text()
VALIDATOR = (DEPLOY / "db/validate_personal_chatgpt_sponsorship.sql").read_text()


class PersonalChatGPTSponsorshipMigrationTests(unittest.TestCase):
    def test_migration_is_transactional_forward_only_and_replay_safe(self):
        self.assertTrue(MIGRATION.startswith("-- Separate tenant-local ChatGPT authentication"))
        self.assertIn("BEGIN;", MIGRATION)
        self.assertIn("COMMIT;", MIGRATION)
        self.assertIn("pg_advisory_xact_lock", MIGRATION)
        self.assertNotRegex(MIGRATION, r"\bDROP\s+(TABLE|COLUMN)\b")

    def test_licensing_preserves_the_original_five_day_clock(self):
        transition = MIGRATION.split("FUNCTION admira.transition_tenant_to_licensed", 1)[1]
        transition = transition.split("CREATE OR REPLACE FUNCTION", 1)[0]
        self.assertIn("coalesce(e.image_sponsorship_ends_at, e.trial_ends_at, now_value)", transition)
        self.assertNotIn("interval '30 days'", transition)
        self.assertIn("CASE WHEN e.licensed_at IS NULL", transition)

    def test_extension_is_exact_idempotent_audited_and_cannot_shorten(self):
        function = MIGRATION.split("FUNCTION admira.operator_set_image_sponsorship_end", 1)[1]
        self.assertIn("p_ends_at > now_value + interval '365 days'", function)
        self.assertIn("p_ends_at < prior_end", function)
        self.assertIn("IS DISTINCT FROM p_ends_at", function)
        self.assertIn("image_sponsorship_extended", function)
        self.assertIn("WHERE changed = 1", function)
        self.assertNotIn("license_id", function.split("ALTER FUNCTION", 1)[0])

    def test_operator_boundary_is_execute_only_and_secret_free(self):
        self.assertIn("SECURITY DEFINER", MIGRATION)
        self.assertIn("TO admira_operator", MIGRATION)
        self.assertNotRegex(MIGRATION, r"GRANT\s+(?:SELECT|INSERT|UPDATE|DELETE)")
        projection = MIGRATION.split("FUNCTION admira.operator_tenant_sponsorship_status", 1)[1]
        projection = projection.split("CREATE OR REPLACE FUNCTION", 1)[0]
        for forbidden in ("secret_ref", "fingerprint", "license_id", "telegram_chat_id"):
            self.assertNotIn(forbidden, projection)
        self.assertIn("personal_chatgpt_sponsorship_validation=passed", VALIDATOR)
        self.assertIn("operator shortened an active sponsorship", VALIDATOR)
        self.assertIn("operator sponsorship grants are too broad", VALIDATOR)


if __name__ == "__main__":
    unittest.main()
