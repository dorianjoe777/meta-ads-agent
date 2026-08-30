import unittest
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "deploy/contabo/db/migrations/010_operator_gemini_pool.sql").read_text()
VALIDATOR = (ROOT / "deploy/contabo/db/validate_operator_gemini_pool.sql").read_text()


class OperatorGeminiPoolMigrationTests(unittest.TestCase):
    def test_is_forward_only_and_project_quota_is_explicit(self):
        self.assertIn("BEGIN;", SQL)
        self.assertIn("COMMIT;", SQL)
        self.assertNotIn("DROP TABLE", SQL)
        self.assertIn("max_trial_assignments integer", SQL)
        self.assertIn("project_id uuid NOT NULL", SQL)
        self.assertIn("health_checked_at timestamptz", SQL)

    def test_stores_only_secret_reference_and_fingerprint(self):
        self.assertIn("secret_ref text", SQL)
        self.assertIn("fingerprint text", SQL)
        self.assertIn("key_kind text NOT NULL", SQL)
        self.assertIn("UNIQUE (fingerprint)", SQL)
        self.assertIn("FOREIGN KEY (project_id, credential_id)", SQL)
        self.assertNotIn("api_key text", SQL.lower())
        self.assertNotIn("raw_key", SQL.lower())
        self.assertIn("secret references and fingerprints", SQL)

    def test_atomic_assignment_and_release_triggers(self):
        self.assertIn("FOR UPDATE SKIP LOCKED", SQL)
        self.assertIn("CASE WHEN health = 'healthy' THEN 0 ELSE 1 END", SQL)
        self.assertIn("c.key_kind = 'auth'", SQL)
        self.assertIn("active_count >= project_row.max_trial_assignments", SQL)
        self.assertIn("ON CONFLICT DO NOTHING", SQL)
        self.assertIn("AFTER UPDATE OF lifecycle_state", SQL)
        self.assertIn("AFTER UPDATE OF status", SQL)
        self.assertIn("release_gemini_trial(tenant_id_value, release_reason_value)", SQL)

    def test_runtime_key_provisioner_lifecycle_adapters(self):
        self.assertIn("CREATE OR REPLACE FUNCTION admira.assign_hosted_gemini_trial(p_runtime_key text)", SQL)
        self.assertIn("CREATE OR REPLACE FUNCTION admira.finalize_hosted_gemini_trial(", SQL)
        self.assertIn("CREATE OR REPLACE FUNCTION admira.release_hosted_gemini_trial(", SQL)
        self.assertIn("RETURNS TABLE (\n  assignment_id uuid, project_id uuid, credential_id uuid, secret_ref text,\n  fingerprint text, key_kind text", SQL)
        self.assertIn("record_tenant_provider_credential(", SQL)
        self.assertIn("'operator_pool'", SQL)
        self.assertIn("assignment_tenant <> resolved_tenant", SQL)
        self.assertIn("REVOKE ALL ON FUNCTION admira.assign_hosted_gemini_trial(text) FROM PUBLIC", SQL)
        self.assertIn("admira.release_hosted_gemini_trial(text, text)", SQL)
        self.assertNotIn("admira.assign_gemini_trial(uuid), admira.release_gemini_trial(uuid, text)", SQL)
        self.assertIn("cannot release finalized hosted Gemini trial", SQL)
        self.assertIn("has_function_privilege('admira_provisioner', 'admira.assign_gemini_trial(uuid)', 'EXECUTE')", VALIDATOR)
        self.assertIn("has_function_privilege('admira_provisioner', 'admira.release_gemini_trial(uuid,text)', 'EXECUTE')", VALIDATOR)

    def test_rls_and_provisioner_only_grants(self):
        self.assertGreaterEqual(SQL.count("ENABLE ROW LEVEL SECURITY"), 4)
        self.assertGreaterEqual(SQL.count("FORCE ROW LEVEL SECURITY"), 4)
        self.assertIn("USING (false) WITH CHECK (false)", SQL)
        self.assertIn("TO admira_provisioner", SQL)
        self.assertNotRegex(SQL, r"GRANT .* ON TABLE .* TO admira_")

    def test_validator_covers_capacity_release_and_least_privilege(self):
        self.assertIn("pool capacity was over-assigned", VALIDATOR)
        self.assertIn("licensed transition did not release Gemini assignment", VALIDATOR)
        self.assertIn("pool roles are not least privilege", VALIDATOR)
        self.assertIn("operator_gemini_pool_validation=passed", VALIDATOR)
        self.assertIn("assign_hosted_gemini_trial", VALIDATOR)
        self.assertIn("finalize_hosted_gemini_trial", VALIDATOR)
        self.assertIn("release_hosted_gemini_trial", VALIDATOR)
        self.assertIn("assign_hosted_gemini_trial('gemini-pool-cycle-002')", VALIDATOR)
        self.assertIn("tenant_runtime_leases", VALIDATOR)

    def test_validator_do_blocks_use_database_lookups_not_psql_variables(self):
        for block in re.findall(r"DO \$\$(.*?)\$\$;", VALIDATOR, flags=re.DOTALL):
            self.assertNotIn(":'", block)


if __name__ == "__main__":
    unittest.main()
