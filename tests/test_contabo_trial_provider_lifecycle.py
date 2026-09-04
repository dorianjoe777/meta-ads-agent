import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "deploy/contabo/db/migrations/007_trial_provider_lifecycle.sql").read_text()


class TrialProviderLifecycleMigrationTests(unittest.TestCase):
    def test_transactional_forward_only_and_idempotent_ddl(self):
        self.assertTrue(SQL.startswith("-- Trial/licensed provider lifecycle"))
        self.assertIn("BEGIN;", SQL)
        self.assertIn("COMMIT;", SQL)
        self.assertIn("ADD COLUMN IF NOT EXISTS", SQL)
        self.assertIn("CREATE TABLE IF NOT EXISTS admira.tenant_provider_credentials", SQL)
        self.assertNotRegex(SQL, r"\bDROP\s+(TABLE|COLUMN)\b")

    def test_lifecycle_constraint_preserves_states_added_by_later_migrations(self):
        constraint = SQL.split(
            "ADD CONSTRAINT tenant_entitlements_lifecycle_state_check", 1
        )[1].split(";", 1)[0]
        self.assertIn("'grace'", constraint)

    def test_all_tenants_get_entitlement_and_new_tenants_are_pending(self):
        self.assertIn("INSERT INTO admira.tenant_entitlements (tenant_id, plan, lifecycle_state)", SQL)
        self.assertIn("FROM admira.tenants AS t", SQL)
        self.assertIn("VALUES (resolved_tenant, 'trial', 'pending_claim')", SQL)
        self.assertIn("FROM admira.tenant_telegram_bindings AS b", SQL)
        self.assertIn("leaving it in\n-- pending_claim would grant an unbounded trial", SQL)
        ensure = SQL.split("FUNCTION admira._ensure_hosted_tenant", 1)[1]
        ensure = ensure.split("CREATE OR REPLACE FUNCTION", 1)[0]
        self.assertNotIn("status = 'active'", ensure)
        self.assertIn("tenant has already been activated", ensure)

    def test_trial_starts_once_on_claim_or_registration(self):
        self.assertIn("PERFORM admira._start_trial_once(claim.tenant_id)", SQL)
        self.assertIn("PERFORM admira._start_trial_once(resolved_tenant)", SQL)
        start = SQL.split("CREATE OR REPLACE FUNCTION admira._start_trial_once", 1)[1]
        start = start.split("CREATE OR REPLACE FUNCTION", 1)[0]
        self.assertIn("interval '5 days'", start)
        self.assertIn("WHERE tenant_id = p_tenant_id AND lifecycle_state = 'pending_claim'", start)

    def test_expiration_suspends_and_license_reactivates(self):
        self.assertIn("CREATE OR REPLACE FUNCTION admira.expire_due_trials()", SQL)
        self.assertIn("lifecycle_state = 'trial_expired'", SQL)
        self.assertIn("SET status = 'suspended'", SQL)
        transition = SQL.split("FUNCTION admira.transition_tenant_to_licensed", 1)[1]
        self.assertIn("SET status = 'active'", transition)
        self.assertNotIn("interval '30 days'", transition)
        self.assertIn("coalesce(e.image_sponsorship_ends_at, e.trial_ends_at, now_value)", transition)

    def test_license_sponsorship_does_not_extend_on_retry(self):
        transition = SQL.split("FUNCTION admira.transition_tenant_to_licensed", 1)[1]
        self.assertIn("CASE WHEN e.licensed_at IS NULL", transition)
        self.assertIn("Buying never restarts the sponsored-image clock", transition)
        self.assertNotIn("greatest(coalesce(image_sponsorship_ends_at", transition)
        self.assertIn("WHERE NOT EXISTS (SELECT 1 FROM admira.tenant_audit_events", transition)
        self.assertIn("tenant already has a different license", transition)
        self.assertIn("PERFORM admira.record_tenant_provider_credential", transition)
        self.assertNotIn("jsonb_build_object('license_id'", transition)
        self.assertIn("FUNCTION admira.transition_hosted_tenant_to_licensed", SQL)

    def test_image_route_allows_connect_command_after_sponsorship(self):
        route = SQL.split("FUNCTION admira.resolve_tenant_image_access", 1)[1]
        route = route.split("CREATE OR REPLACE FUNCTION admira.transition_tenant_to_licensed", 1)[0]
        self.assertIn("central_sponsored", route)
        self.assertIn("t.status <> 'active' THEN 'blocked'", route)
        self.assertIn("e.trial_ends_at > now()", route)
        self.assertIn("coalesce(e.image_sponsorship_ends_at, e.trial_ends_at) > now()", route)
        self.assertIn("THEN 'personal_chatgpt'", route)
        self.assertIn("ELSE 'blocked'", route)
        self.assertNotIn("EXISTS (SELECT 1 FROM admira.tenant_provider_credentials", route)

    def test_provider_metadata_is_secret_free_and_retired_history_is_unlimited(self):
        block = SQL.split("CREATE TABLE IF NOT EXISTS admira.tenant_provider_credentials", 1)[1]
        block = block.split("COMMENT ON TABLE", 1)[0]
        self.assertIn("secret_ref text", block)
        self.assertIn("fingerprint text", block)
        self.assertIn("origin text", block)
        self.assertNotRegex(block, r"(api[_ ]?key|secret[_ ]?value|token|credential)\s+(text|json|bytea)")
        self.assertIn("WHERE status = 'active'", block)
        self.assertIn("status = 'retired'", SQL)
        self.assertIn("record_tenant_provider_credential", SQL)
        self.assertIn("fingerprint ~ '^[a-f0-9]{64}$'", SQL)
        self.assertIn("secret_ref !~ '[[:space:][:cntrl:]]'", SQL)
        self.assertIn("LIKE 'UNIQUE (tenant_id, provider, purpose, status)%'", SQL)
        constraint_loop = SQL.split("FOR c IN SELECT conname FROM pg_constraint", 1)[1].split("LOOP", 1)[0]
        self.assertIn("pg_get_constraintdef(oid)", constraint_loop)
        self.assertIn("tenant_id, provider, purpose, status", constraint_loop)

    def test_rls_least_privilege_and_function_grants(self):
        self.assertIn("ENABLE ROW LEVEL SECURITY", SQL)
        self.assertIn("FORCE ROW LEVEL SECURITY", SQL)
        self.assertIn("current_setting('admira.tenant_id', true)", SQL)
        self.assertIn("REVOKE ALL ON TABLE admira.tenant_provider_credentials FROM PUBLIC", SQL)
        self.assertIn("GRANT EXECUTE ON FUNCTION admira.claim_telegram_tenant", SQL)
        self.assertIn("GRANT EXECUTE ON FUNCTION admira.expire_due_trials() TO admira_runtime, admira_scheduler", SQL)
        self.assertIn("ALTER FUNCTION admira.record_tenant_provider_credential", SQL)
        self.assertIn("GRANT SELECT, INSERT, UPDATE, DELETE ON admira.tenant_provider_credentials", SQL)
        self.assertIn("GRANT EXECUTE ON FUNCTION admira.transition_hosted_tenant_to_licensed", SQL)


if __name__ == "__main__":
    unittest.main()
