import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "contabo"
MIGRATION = (DEPLOY / "db/migrations/017_licensed_central_image_pool_switch.sql").read_text()
VALIDATOR = (DEPLOY / "db/validate_licensed_central_image_pool_switch.sql").read_text()
CENTRAL_VALIDATOR = (DEPLOY / "db/validate_central_image_jobs.sql").read_text()


class LicensedCentralImagePoolSwitchTests(unittest.TestCase):
    def test_migration_is_transactional_replay_safe_and_secret_free(self):
        self.assertTrue(MIGRATION.startswith("-- Keep the temporary trial benefit"))
        self.assertIn("BEGIN;", MIGRATION)
        self.assertIn("COMMIT;", MIGRATION)
        self.assertIn("pg_advisory_xact_lock", MIGRATION)
        self.assertIn("ADD COLUMN IF NOT EXISTS licensed_central_image_pool_enabled boolean NOT NULL DEFAULT false", MIGRATION)
        self.assertIn("existing_type <> 'boolean'::regtype", MIGRATION)
        self.assertIn("licensed central image pool switch has incompatible type", MIGRATION)
        self.assertIn("silently re-enable a license an operator deliberately removed", MIGRATION)
        self.assertNotIn("SET licensed_central_image_pool_enabled = true", MIGRATION)
        self.assertNotRegex(MIGRATION, r"\bDROP\s+(TABLE|COLUMN)\b")
        self.assertNotRegex(MIGRATION, r"(api[_ ]?key|access[_ ]?token|refresh[_ ]?token)\s+(text|json|bytea)")

    def test_trial_is_automatic_and_licensed_route_requires_explicit_opt_in(self):
        resolver = MIGRATION.split("FUNCTION admira.resolve_tenant_image_access", 1)[1]
        resolver = resolver.split("CREATE OR REPLACE FUNCTION admira.operator_set_image_sponsorship_end", 1)[0]
        self.assertIn("entitlement.lifecycle_state = 'trial'", resolver)
        self.assertIn("entitlement.licensed_central_image_pool_enabled", resolver)
        self.assertLess(
            resolver.index("entitlement.lifecycle_state = 'trial'"),
            resolver.index("entitlement.lifecycle_state = 'licensed'\n                AND entitlement.licensed_central_image_pool_enabled"),
        )
        self.assertIn("WHEN entitlement.lifecycle_state = 'licensed' THEN 'personal_chatgpt'", resolver)
        self.assertNotIn("tenant_provider_credentials", resolver)

    def test_operator_switch_is_licensed_only_audited_and_execute_only(self):
        function = MIGRATION.split("FUNCTION admira.operator_set_licensed_central_image_pool", 1)[1]
        function = function.split("CREATE OR REPLACE FUNCTION admira.operator_tenant_sponsorship_status", 1)[0]
        self.assertIn("SECURITY DEFINER", function)
        self.assertIn("resolved_state <> 'licensed'", function)
        self.assertIn("licensed_central_image_pool_changed", function)
        self.assertIn("WHERE changed = 1", function)
        self.assertIn("p_enabled IS NULL", function)
        self.assertIn("TO admira_operator", MIGRATION)
        self.assertNotRegex(MIGRATION, r"GRANT\s+(?:SELECT|INSERT|UPDATE|DELETE)")

    def test_legacy_timestamp_control_cannot_bypass_licensed_switch(self):
        extension = MIGRATION.split("FUNCTION admira.operator_set_image_sponsorship_end", 1)[1]
        extension = extension.split("CREATE OR REPLACE FUNCTION admira.operator_set_licensed_central_image_pool", 1)[0]
        self.assertIn("resolved_state <> 'trial'", extension)
        self.assertIn("tenant trial is not eligible for sponsorship", extension)

    def test_disposable_validators_cover_both_image_and_campaign_access(self):
        self.assertIn("new licensed tenant was not personal by default", VALIDATOR)
        self.assertIn("resolve_central_campaign_compiler_access_for_runtime", VALIDATOR)
        self.assertIn("licensed_central_image_pool_changed", VALIDATOR)
        self.assertIn("licensed_central_image_pool_switch_validation=passed", VALIDATOR)
        self.assertIn("operator_set_licensed_central_image_pool", CENTRAL_VALIDATOR)


if __name__ == "__main__":
    unittest.main()
