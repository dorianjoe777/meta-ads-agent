from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "deploy" / "contabo" / "db" / "migrations" / "001_initial_multitenant.sql"


class ContaboSchemaTests(unittest.TestCase):
    """Static invariants for the initial migration (no PostgreSQL required)."""

    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8")

    def test_migration_is_transactional_and_idempotent(self):
        self.assertIn("BEGIN;", self.sql)
        self.assertIn("COMMIT;", self.sql)
        self.assertGreaterEqual(self.sql.count("CREATE TABLE IF NOT EXISTS"), 7)
        self.assertIn("CREATE SCHEMA IF NOT EXISTS admira", self.sql)

    def test_required_entities_and_tenant_foreign_keys_exist(self):
        names = (
            "tenants", "tenant_telegram_bindings", "tenant_telegram_updates", "tenant_entitlements",
            "tenant_runtime_leases", "tenant_scheduled_jobs",
            "tenant_scheduled_job_runs", "tenant_audit_events",
        )
        for name in names:
            self.assertRegex(self.sql, rf"CREATE TABLE IF NOT EXISTS admira\.{name}\s*\(")
        scoped = names[1:]
        for name in scoped:
            block = self._table_block(name)
            self.assertRegex(block, r"tenant_id\s+uuid\s+(?:NOT NULL|PRIMARY KEY)")
            self.assertRegex(block, r"REFERENCES admira\.tenants\(id\)")

    def test_scheduled_runs_cannot_cross_tenants(self):
        self.assertIn("FOREIGN KEY (tenant_id, job_id)", self.sql)
        self.assertIn("REFERENCES admira.tenant_scheduled_jobs (tenant_id, id)", self.sql)
        self.assertIn("tenant_scheduled_jobs_tenant_id_id_uq", self.sql)

        unique_pos = self.sql.index("tenant_scheduled_jobs_tenant_id_id_uq")
        runs_pos = self.sql.index("CREATE TABLE IF NOT EXISTS admira.tenant_scheduled_job_runs")
        self.assertLess(unique_pos, runs_pos)

    def test_telegram_updates_are_durable_and_deduplicated(self):
        block = self._table_block("tenant_telegram_updates")
        self.assertRegex(block, r"tenant_id\s+uuid\s+NOT NULL")
        self.assertRegex(block, r"update_id\s+bigint\s+NOT NULL")
        self.assertIn("UNIQUE (bot_id, update_id)", block)
        self.assertIn("REFERENCES admira.tenants(id)", block)
        self.assertIn("tenant_telegram_updates_tenant_received_idx", self.sql)

    def test_rls_is_enabled_for_every_scoped_table_and_fails_closed(self):
        scoped = (
            "tenant_telegram_bindings", "tenant_entitlements",
            "tenant_runtime_leases", "tenant_scheduled_jobs",
            "tenant_scheduled_job_runs", "tenant_audit_events",
        )
        for name in scoped:
            self.assertIn(f"'{name}'", self.sql)
        self.assertIn("ENABLE ROW LEVEL SECURITY", self.sql)
        self.assertIn("FORCE ROW LEVEL SECURITY", self.sql)
        self.assertIn("current_setting(''admira.tenant_id'', true)", self.sql)
        self.assertIn("tenant_id::text = NULLIF", self.sql)
        self.assertIn("WITH CHECK", self.sql)
        self.assertIn("ALTER TABLE admira.tenants ENABLE ROW LEVEL SECURITY", self.sql)
        self.assertIn("id::text = NULLIF(current_setting(''admira.tenant_id'', true)", self.sql)

    def test_critical_indexes_and_lifecycle_constraints_exist(self):
        for marker in (
            "tenant_telegram_bindings_tenant_idx",
            "tenant_runtime_leases_state_expiry_idx",
            "tenant_scheduled_job_runs_lookup_idx",
            "tenant_audit_events_tenant_created_idx",
            "CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)",
            "CHECK (expires_at IS NULL OR acquired_at IS NULL OR expires_at >= acquired_at)",
        ):
            self.assertIn(marker, self.sql)

    def _table_block(self, name: str) -> str:
        match = re.search(
            rf"CREATE TABLE IF NOT EXISTS admira\.{name}\s*\((.*?)\n\);",
            self.sql,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match, name)
        return match.group(1)


if __name__ == "__main__":
    unittest.main()
