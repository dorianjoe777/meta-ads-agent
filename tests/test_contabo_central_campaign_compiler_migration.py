import re
import unittest
from pathlib import Path


SQL_PATH = Path(__file__).parents[1] / "deploy/contabo/db/migrations/016_central_campaign_compiler.sql"


class CentralCampaignCompilerMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = SQL_PATH.read_text()

    def test_is_transactional_and_idempotent(self):
        self.assertIn("BEGIN;", self.sql)
        self.assertIn("COMMIT;", self.sql)
        self.assertIn("CREATE OR REPLACE FUNCTION admira.resolve_central_campaign_compiler_access_for_runtime(", self.sql)
        self.assertIn("ALTER FUNCTION admira.resolve_central_campaign_compiler_access_for_runtime(text)", self.sql)

    def test_runtime_key_uses_active_tenant_and_canonical_resolver(self):
        self.assertIn("p_runtime_key text", self.sql)
        self.assertIn("RETURNS TABLE (lifecycle_state text, route text)", self.sql)
        self.assertIn("runtime.runtime_key = btrim(p_runtime_key)", self.sql)
        self.assertIn("JOIN admira.tenants AS tenant ON tenant.id = runtime.tenant_id", self.sql)
        self.assertIn("tenant.status = 'active'", self.sql)
        self.assertIn("admira.resolve_tenant_image_access(tenant.id)", self.sql)
        self.assertIn("SELECT access.lifecycle_state, access.route", self.sql)

    def test_security_definer_fixed_path_and_least_privilege(self):
        block_start = self.sql.index("CREATE OR REPLACE FUNCTION admira.resolve_central_campaign_compiler_access_for_runtime")
        block = self.sql[block_start:self.sql.index("$$", block_start)]
        self.assertIn("SECURITY DEFINER", block)
        self.assertIn("SET search_path = admira, pg_catalog", block)
        self.assertIn("REVOKE ALL ON FUNCTION admira.resolve_central_campaign_compiler_access_for_runtime(text)\n  FROM PUBLIC", self.sql)
        self.assertIn("REVOKE ALL ON ALL TABLES IN SCHEMA admira FROM admira_image", self.sql)
        self.assertIn("GRANT USAGE ON SCHEMA admira TO admira_image", self.sql)
        self.assertIn("GRANT EXECUTE ON FUNCTION admira.resolve_central_campaign_compiler_access_for_runtime(text)\n  TO admira_image", self.sql)
        self.assertNotRegex(self.sql, r"GRANT\s+.*ON\s+TABLE\s+.*TO\s+admira_image", re.S | re.I)

    def test_does_not_persist_prompts_results_or_secrets(self):
        executable = re.sub(r"--[^\n]*|/\*.*?\*/", "", self.sql, flags=re.S)
        self.assertNotRegex(executable.lower(), r"prompt|result|secret|api[_ -]?key|insert\s+into|update\s+|delete\s+from")


if __name__ == "__main__":
    unittest.main()
