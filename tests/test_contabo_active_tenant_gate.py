from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "deploy" / "contabo" / "db" / "migrations" / "004_active_tenant_runtime_gate.sql"


class ActiveTenantRuntimeGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8")

    def test_runtime_update_and_scheduler_claims_require_active_tenant(self):
        self.assertIn("FUNCTION admira.claim_telegram_updates", self.sql)
        self.assertIn("FUNCTION admira.claim_due_scheduled_jobs", self.sql)
        self.assertGreaterEqual(self.sql.count("tenant.status = 'active'"), 3)

    def test_runtime_lease_cannot_be_acquired_for_inactive_tenant(self):
        lease = self.sql.split("FUNCTION admira.acquire_runtime_lease", 1)[1]
        self.assertIn("EXISTS (", lease)
        self.assertIn("tenant.id = p_tenant_id AND tenant.status = 'active'", lease)

    def test_replacement_functions_remain_least_privilege(self):
        for signature in (
            "admira.claim_telegram_updates(text, integer, integer)",
            "admira.claim_due_scheduled_jobs(text, integer, integer)",
            "admira.acquire_runtime_lease(uuid, text, integer)",
        ):
            self.assertIn(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC", self.sql)
            self.assertIn(f"ALTER FUNCTION {signature} OWNER TO admira_control_owner", self.sql)


if __name__ == "__main__":
    unittest.main()
