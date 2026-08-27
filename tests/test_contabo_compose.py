from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy" / "contabo" / "compose.yaml"


class ContaboComposeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = COMPOSE.read_text(encoding="utf-8")

    def test_control_plane_is_not_published_to_the_host(self):
        self.assertNotIn("ports:", self.text)
        self.assertIn("internal: true", self.text)
        self.assertIn("no-new-privileges:true", self.text)

    def test_postgres_migration_directory_matches_repository(self):
        self.assertIn("./db/migrations:/docker-entrypoint-initdb.d:ro", self.text)
        self.assertTrue((COMPOSE.parent / "db" / "migrations" / "001_initial_multitenant.sql").is_file())

    def test_redis_has_only_privilege_drop_bootstrap_capabilities(self):
        redis = self.text.split("  redis:\n", 1)[1].split("\nnetworks:\n", 1)[0]
        self.assertIn("cap_drop:\n      - ALL", redis)
        for capability in ("CHOWN", "SETGID", "SETUID"):
            self.assertIn(f"      - {capability}", redis)
        for forbidden in ("SYS_ADMIN", "NET_ADMIN", "DAC_READ_SEARCH"):
            self.assertNotIn(forbidden, redis)


if __name__ == "__main__":
    unittest.main()
