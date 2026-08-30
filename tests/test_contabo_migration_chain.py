import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "deploy/contabo/db/validate_migration_chain.sh"


class MigrationChainValidationTests(unittest.TestCase):
    def test_read_only_chain_check_passes(self):
        result = subprocess.run(
            [str(CHECK)], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("Migration chain 007-010 passed read-only checks", result.stdout)
        self.assertIn("no database was changed", result.stdout)

    def test_checker_is_explicitly_non_mutating(self):
        source = CHECK.read_text(encoding="utf-8")
        self.assertIn("never connects to PostgreSQL and never applies SQL", source)
        self.assertNotIn("docker compose", source)

    def test_checker_uses_portable_host_tools_and_standalone_env_path(self):
        source = CHECK.read_text(encoding="utf-8")
        self.assertNotIn(" rg ", source)
        self.assertIn('if [[ -f "$ROOT_DIR/.env.example" ]]', source)


if __name__ == "__main__":
    unittest.main()
