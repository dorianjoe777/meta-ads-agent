from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "deploy" / "contabo" / filename
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


tenantctl = load("contabo_ready_tenantctl", "tenantctl.py")
sys.modules.setdefault("tenantctl", tenantctl)
tenant_turn = load("contabo_ready_tenant_turn", "tenant_turn.py")


class ContaboReadyExperienceTests(unittest.TestCase):
    def test_two_buyers_get_distinct_persistent_roots_and_sessions(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw) / "tenants"
            # Gemini credentials are intentionally absent at tenant creation;
            # the operator pool/licensing workflow installs them later.
            tenantctl.provision(base, "buyer-one")
            tenantctl.provision(base, "buyer-two")

            first = base / "buyer-one"
            second = base / "buyer-two"
            for root in (first, second):
                self.assertEqual(root.stat().st_mode & 0o777, 0o700)
                for directory in tenantctl.DIRS:
                    self.assertTrue((root / directory).is_dir())
                    self.assertEqual((root / directory).stat().st_mode & 0o777, 0o700)
                self.assertEqual((root / "runtime" / ".env").stat().st_mode & 0o777, 0o600)

            first_compose = (first / "compose.yaml").read_text(encoding="utf-8")
            second_compose = (second / "compose.yaml").read_text(encoding="utf-8")
            self.assertIn("name: admira-tenant-buyer-one", first_compose)
            self.assertIn("name: admira-tenant-buyer-two", second_compose)
            self.assertNotIn(str(second), first_compose)
            self.assertNotIn(str(first), second_compose)
            self.assertNotIn("telegram_bot_token", first_compose.lower())
            self.assertNotIn("telegram_bot_token", second_compose.lower())

            # Even if Telegram IDs happened to be equal, each tenant owns a
            # separate generation ledger and therefore a separate Hermes home.
            chat_id = "123456"
            first_ledger = first / "runtime" / "telegram_session_generations.json"
            second_ledger = second / "runtime" / "telegram_session_generations.json"
            self.assertEqual(
                tenant_turn._session_generation(first_ledger, chat_id, increment=True), 1
            )
            self.assertEqual(tenant_turn._session_generation(second_ledger, chat_id), 0)
            self.assertEqual(tenant_turn._session_generation(first_ledger, chat_id), 1)

    def test_runtime_env_is_consumed_without_exposing_it_in_compose(self):
        entrypoint = (ROOT / "scripts" / "docker-entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn("ln -sf /app/runtime/.env /app/.env", entrypoint)
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw) / "tenants"
            tenantctl.provision(base, "buyer-env")
            compose = (base / "buyer-env" / "compose.yaml").read_text(encoding="utf-8")
            self.assertIn(":/app/runtime", compose)
            self.assertNotIn("env_file:", compose)
            self.assertNotIn("GEMINI_API_KEY", compose)


if __name__ == "__main__":
    unittest.main()
