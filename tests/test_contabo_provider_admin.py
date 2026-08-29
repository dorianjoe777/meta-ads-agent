from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("provider_admin", ROOT / "deploy" / "contabo" / "provider_admin.py")
provider_admin = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(provider_admin)


class ProviderAdminTests(unittest.TestCase):
    def tenant(self, raw: str) -> tuple[Path, Path]:
        base = Path(raw) / "tenants"
        runtime = base / "client-001" / "runtime"
        runtime.mkdir(parents=True)
        env = runtime / ".env"
        env.write_text("OTHER=value\nGEMINI_API_KEY=old-key-value-1234567890\nTAIL=kept\n", encoding="utf-8")
        env.chmod(0o600)
        return base, env

    def test_set_reads_key_without_placing_it_in_result_or_argv(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            key = "new-gemini-key-value-1234567890"
            result = provider_admin.manage_gemini_key(base, "client-001", value=key, source="operator_pool")
            self.assertTrue(result["ok"])
            self.assertNotIn(key, json.dumps(result))
            self.assertIn("OTHER=value\nGEMINI_API_KEY=" + key + "\nTAIL=kept\n", env.read_text())
            self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o600)

    def test_private_file_and_injectable_validator(self):
        with tempfile.TemporaryDirectory() as raw:
            base, _ = self.tenant(raw)
            source = Path(raw) / "key"
            source.write_text("valid-key-value-1234567890\n", encoding="utf-8")
            source.chmod(0o600)
            seen: list[str] = []
            result = provider_admin.main(
                ["gemini-set", "client-001", "--source", "customer", "--key-file", str(source), "--base-dir", str(base)],
                stdin=io.StringIO("argv-must-not-be-used"),
            )
            self.assertEqual(result, 0)
            self.assertIn("GEMINI_API_KEY=valid-key-value-1234567890", (base / "client-001/runtime/.env").read_text())
            provider_admin.manage_gemini_key(base, "client-001", value="another-valid-key-value-1234567890", source="customer", validator=lambda value: seen.append(value) or True)
            self.assertEqual(seen, ["another-valid-key-value-1234567890"])
            source.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "private regular file"):
                provider_admin._read_private_file(source)

    def test_dry_run_and_clear_do_not_touch_other_files(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            other = env.parent / "keep.txt"
            other.write_text("unchanged", encoding="utf-8")
            before = env.read_text()
            result = provider_admin.manage_gemini_key(base, "client-001", value="dry-run-key-value-1234567890", source="operator_pool", dry_run=True)
            self.assertTrue(result["dry_run"])
            self.assertEqual(env.read_text(), before)
            provider_admin.manage_gemini_key(base, "client-001", value=None, source="customer")
            self.assertIn("GEMINI_API_KEY=\n", env.read_text())
            self.assertEqual(other.read_text(), "unchanged")

    def test_health_failure_rolls_back_exact_old_env(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            before = env.read_text()
            result = provider_admin.manage_gemini_key(
                base, "client-001", value="replacement-key-value-1234567890", source="operator_pool",
                health_check=lambda _: False,
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "health_check_failed")
            self.assertEqual(env.read_text(), before)
            self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o600)

    def test_invalid_key_and_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            with self.assertRaises(ValueError):
                provider_admin.manage_gemini_key(base, "client-001", value="short", source="operator_pool")
            outside = Path(raw) / "outside"
            outside.write_text("OTHER=value\n", encoding="utf-8")
            env.unlink()
            env.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "symlink"):
                provider_admin.manage_gemini_key(base, "client-001", value="replacement-key-value-1234567890", source="operator_pool")


if __name__ == "__main__":
    unittest.main()
