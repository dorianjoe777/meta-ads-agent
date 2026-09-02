from __future__ import annotations

import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deploy.contabo.central_codex_account_pool import (
    AccountPoolConfigError,
    CentralCodexAccountPool,
)
import codex_brand_guides as brand


class CentralCodexAccountPoolTests(unittest.TestCase):
    def _accounts(self, root: Path, count: int = 2):
        values = []
        for index in range(count):
            home = root / f"account-{index}"
            home.mkdir(mode=0o700)
            (home / "auth.json").write_text("{}", encoding="utf-8")
            os.chmod(home / "auth.json", 0o600)
            values.append({"id": f"account-{index}", "codex_home": str(home)})
        return values

    def test_requires_two_to_eight_private_accounts(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with self.assertRaises(AccountPoolConfigError):
                CentralCodexAccountPool(self._accounts(root, 1))
            root = Path(tempfile.mkdtemp(dir=raw))
            (root / "extra").mkdir()
            with self.assertRaises(AccountPoolConfigError):
                CentralCodexAccountPool(self._accounts(root, 2) + self._accounts(root / "extra", 6))

    def test_rejects_public_auth_and_symlink(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            accounts = self._accounts(root)
            os.chmod(root / "account-0" / "auth.json", 0o644)
            with self.assertRaises(AccountPoolConfigError):
                CentralCodexAccountPool(accounts)
            os.chmod(root / "account-0" / "auth.json", 0o600)
            (root / "account-1" / "auth.json").unlink()
            (root / "account-1" / "auth.json").symlink_to(root / "account-0" / "auth.json")
            with self.assertRaises(AccountPoolConfigError):
                CentralCodexAccountPool(accounts)

    def test_limit_failure_falls_back_once_per_account_without_leaking_result(self):
        with tempfile.TemporaryDirectory() as raw:
            calls = []
            def provider(prompt, **kwargs):
                calls.append(kwargs["codex_home"].name)
                if len(calls) == 1:
                    return {"ok": False, "error_type": "rate_limit", "error": "codex usage limit; SECRET"}
                return {"ok": True, "image_path": "/tmp/result.png", "stdout": "secret", "prompt": prompt}
            pool = CentralCodexAccountPool(self._accounts(Path(raw)), provider=provider, cooldowns={"codex_usage_limit": 60})
            result = pool.generate("private prompt")
            self.assertTrue(result["ok"])
            self.assertEqual(len(calls), 2)
            self.assertNotIn("private prompt", repr(result))
            self.assertNotIn("stdout", result)

    def test_concurrent_requests_never_share_one_account(self):
        with tempfile.TemporaryDirectory() as raw:
            active = 0
            peak = 0
            lock = threading.Lock()
            def provider(prompt, **kwargs):
                nonlocal active, peak
                with lock:
                    active += 1
                    peak = max(peak, active)
                time.sleep(0.04)
                with lock:
                    active -= 1
                return {"ok": True, "image_path": "/tmp/x.png"}
            pool = CentralCodexAccountPool(self._accounts(Path(raw)), provider=provider)
            results = []
            threads = [threading.Thread(target=lambda: results.append(pool.generate("x"))) for _ in range(4)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
            self.assertEqual(peak, 2)
            self.assertEqual(sum(result["ok"] for result in results), 2)
            self.assertEqual(sum(result.get("error_type") == "provider_unavailable" for result in results), 2)

    def test_default_provider_classifies_direct_codex_limit_without_raw_output(self):
        with tempfile.TemporaryDirectory() as raw:
            accounts = self._accounts(Path(raw))
            pool = CentralCodexAccountPool(accounts)
            with patch.object(
                brand, "call_codex_image_cli_direct",
                return_value={"ok": False, "error": "generic usage limit; secret", "error_type": "rate_limit", "stdout": "secret"},
            ):
                result = pool._default_provider(
                    "private prompt", codex_home=Path(accounts[0]["codex_home"]),
                    timeout=1, model=None, output_root=None, output_name="x",
                    reference_image_paths=(), purpose="ad_creative",
                )
            self.assertEqual(result, {"ok": False, "failure_category": "codex_usage_limit"})
            self.assertNotIn("secret", repr(result))

    def test_three_account_pool_attempts_at_most_two_accounts_per_request(self):
        with tempfile.TemporaryDirectory() as raw:
            calls = []
            def provider(prompt, **kwargs):
                calls.append(kwargs["codex_home"].name)
                return {"ok": False, "failure_category": "provider_failed"}
            pool = CentralCodexAccountPool(self._accounts(Path(raw), 3), provider=provider)
            result = pool.generate("x")
            self.assertFalse(result["ok"])
            self.assertEqual(result["attempted_accounts"], 2)
            self.assertEqual(len(calls), 2)

    def test_compile_falls_back_between_accounts_and_returns_safe_contract(self):
        with tempfile.TemporaryDirectory() as raw:
            calls = []
            def compiler(prompt, schema, **kwargs):
                calls.append((prompt, schema, kwargs))
                if len(calls) == 1:
                    return {"ok": False, "error": "secret prompt", "failure_category": "provider_failed"}
                return {"ok": True, "compiled": {"name": "campaign", "count": 2},
                        "stdout": "credential", "prompt": prompt}
            pool = CentralCodexAccountPool(
                self._accounts(Path(raw)), compiler_provider=compiler,
                cooldowns={"provider_failed": 60},
            )
            result = pool.compile("private prompt", {"type": "object"}, timeout=12)
            self.assertEqual(result["compiled"], {"name": "campaign", "count": 2})
            self.assertEqual(result["model"], "gpt-5.6-terra")
            self.assertEqual(result["account_id"], "account-1")
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][0], "private prompt")
            self.assertEqual(calls[0][2]["model"], "gpt-5.6-terra")
            self.assertNotIn("stdout", result)
            self.assertNotIn("credential", repr(result))

    def test_compile_shares_locks_and_cooldowns_with_generate(self):
        with tempfile.TemporaryDirectory() as raw:
            calls = []
            def provider(prompt, **kwargs):
                calls.append(("generate", kwargs["codex_home"].name))
                return {"ok": False, "failure_category": "provider_failed"}
            def compiler(prompt, schema, **kwargs):
                calls.append(("compile", kwargs["codex_home"].name))
                return {"ok": True, "compiled": {"ok": True}}
            pool = CentralCodexAccountPool(
                self._accounts(Path(raw)), provider=provider,
                compiler_provider=compiler, cooldowns={"provider_failed": 60},
            )
            pool.generate("x")
            result = pool.compile("x", {})
            self.assertFalse(result["ok"])
            self.assertEqual(result["failure_category"], "provider_unavailable")
            self.assertEqual(result["attempted_accounts"], 0)
            self.assertEqual([account for kind, account in calls if kind == "compile"], [])

    def test_compile_rejects_invalid_output_without_leaking_sensitive_fields(self):
        with tempfile.TemporaryDirectory() as raw:
            def compiler(prompt, schema, **kwargs):
                return {"ok": True, "compiled": "not-a-mapping", "stderr": "TOKEN", "prompt": prompt}
            pool = CentralCodexAccountPool(self._accounts(Path(raw)), compiler_provider=compiler)
            result = pool.compile("private prompt", {"secret": "schema"})
            self.assertFalse(result["ok"])
            self.assertEqual(result["failure_category"], "unknown")
            self.assertNotIn("private prompt", repr(result))
            self.assertNotIn("schema", repr(result))
            self.assertNotIn("TOKEN", repr(result))
            self.assertNotIn("stderr", result)

    def test_compile_allows_only_terra_model(self):
        with tempfile.TemporaryDirectory() as raw:
            calls = []
            pool = CentralCodexAccountPool(
                self._accounts(Path(raw)),
                compiler_provider=lambda *args, **kwargs: calls.append(True),
            )
            result = pool.compile("x", {}, model="gpt-5.6-sol")
            self.assertFalse(result["ok"])
            self.assertEqual(result["failure_category"], "provider_failed")
            self.assertEqual(calls, [])

    def test_chat_uses_each_slot_once_and_discards_raw_provider_data(self):
        with tempfile.TemporaryDirectory() as raw:
            calls = []
            def conversation(messages, **kwargs):
                calls.append(kwargs["codex_home"].name)
                if len(calls) == 1:
                    return {"ok": False, "failure_category": "provider_limited", "diagnostic": "secret"}
                return {
                    "ok": True,
                    "message": {"role": "assistant", "content": "Listo", "tool_calls": []},
                    "finish_reason": "stop",
                    "diagnostic": "credential",
                }
            pool = CentralCodexAccountPool(
                self._accounts(Path(raw)), conversation_provider=conversation,
                cooldowns={"provider_limited": 60},
            )
            result = pool.chat([{"role": "user", "content": "private"}], timeout=12)
            self.assertTrue(result["ok"])
            self.assertEqual(result["account_id"], "account-1")
            self.assertEqual(len(calls), 2)
            self.assertNotIn("credential", repr(result))
            self.assertNotIn("diagnostic", result)


if __name__ == "__main__":
    unittest.main()
