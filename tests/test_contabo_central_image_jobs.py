import re
import unittest
from pathlib import Path


SQL_PATH = Path(__file__).parents[1] / "deploy/contabo/db/migrations/008_central_image_jobs.sql"


class CentralImageJobsMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = SQL_PATH.read_text()

    def test_is_transactional_and_idempotent(self):
        self.assertIn("BEGIN;", self.sql)
        self.assertIn("COMMIT;", self.sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS admira.central_image_jobs", self.sql)
        self.assertIn("central_image_jobs_tenant_request_uq UNIQUE (tenant_id, request_id)", self.sql)
        self.assertIn("ON CONFLICT ON CONSTRAINT central_image_jobs_tenant_request_uq DO NOTHING", self.sql)
        self.assertIn("CREATE INDEX IF NOT EXISTS", self.sql)
        self.assertGreaterEqual(self.sql.count("CREATE OR REPLACE FUNCTION"), 3)

    def test_opaque_artifact_and_safe_error_constraints(self):
        self.assertIn("output_ref ~ '^[a-f0-9]{32,64}\\.(png|jpg|jpeg|webp)$'", self.sql)
        self.assertRegex(self.sql, r"output_sha256.*\^\[a-f0-9\]\{64\}\$", re.S)
        self.assertIn("output_mime IN ('image/png', 'image/jpeg', 'image/webp')", self.sql)
        self.assertIn("error_code IN ('provider_failed', 'provider_unavailable'", self.sql)
        executable = re.sub(r"--[^\n]*|/\*.*?\*/", "", self.sql, flags=re.S)
        self.assertNotRegex(executable.lower(), r"prompt|provider_response|secret_value|api[_ -]?key")

    def test_runtime_boundary_is_keyed_and_entitlement_gated(self):
        fn = self.sql[self.sql.index("CREATE OR REPLACE FUNCTION admira.begin_central_image_job_for_runtime"):]
        self.assertIn("p_runtime_key text, p_request_id uuid", fn)
        self.assertIn("p_lease_seconds integer", fn)
        self.assertIn("^[a-z0-9][a-z0-9-]{2,62}$", fn)
        self.assertIn("runtime.runtime_key = p_runtime_key", fn)
        self.assertIn("t.status = 'active'", fn)
        self.assertIn("resolve_tenant_image_access(resolved_tenant)", fn)
        self.assertIn("IF route IS DISTINCT FROM 'central_sponsored' THEN", fn)
        self.assertIn("INSERT INTO admira.central_image_jobs", fn)
        self.assertIn("existing.status = 'queued' AND existing.available_at > now()", fn)
        self.assertIn("TO admira_image", self.sql)
        self.assertNotIn("TO admira_runtime", self.sql)

    def test_claims_are_locked_fairly_and_reclaim_crashed_workers(self):
        self.assertIn("FOR UPDATE", self.sql)
        self.assertIn("existing.status = 'running' AND existing.leased_until > now()", self.sql)
        self.assertIn("existing.attempt_count >= existing.max_attempts", self.sql)
        self.assertIn("error_code = 'lease_expired'", self.sql)
        self.assertIn("lease_token = NULL", self.sql)
        self.assertIn("status = 'running' AND lease_token = p_lease_token", self.sql)

    def test_security_definer_search_path_and_minimal_grants(self):
        functions = re.findall(
            r"CREATE OR REPLACE FUNCTION (admira\.[a-z_]+)\((.*?)\).*?\$\$",
            self.sql,
            re.S,
        )
        self.assertGreaterEqual(len(functions), 3)
        for name, _args in functions:
            block_start = self.sql.index("CREATE OR REPLACE FUNCTION " + name)
            block = self.sql[block_start:self.sql.index("$$", block_start)]
            self.assertIn("SECURITY DEFINER", block, name)
            self.assertIn("SET search_path = admira, pg_catalog", block, name)
        self.assertIn("REVOKE ALL ON TABLE admira.central_image_jobs FROM PUBLIC", self.sql)
        self.assertIn("ALTER TABLE admira.central_image_jobs OWNER TO admira_control_owner", self.sql)
        self.assertIn("GRANT USAGE ON SCHEMA admira TO admira_image", self.sql)
        self.assertIn("REVOKE ALL ON FUNCTION admira.begin_central_image_job_for_runtime", self.sql)

    def test_no_untrusted_direct_worker_table_access(self):
        grant_section = self.sql[self.sql.index("REVOKE ALL ON TABLE"):]
        self.assertNotRegex(grant_section, r"GRANT .* ON TABLE .* TO admira_image")
        self.assertNotRegex(grant_section, r"GRANT .* ON TABLE .* TO admira_runtime")
        self.assertIn("admira_image_login", (Path(__file__).parents[1] / "deploy/contabo/db/bootstrap_service_roles.sql").read_text())
        bootstrap = (Path(__file__).parents[1] / "deploy/contabo/db/bootstrap_service_roles.sql").read_text()
        self.assertIn("'admira_image',    '/run/admira-db-secrets/image_db_password'", bootstrap)


if __name__ == "__main__":
    unittest.main()
