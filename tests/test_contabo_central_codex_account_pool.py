from __future__ import annotations

import os
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path

from deploy.contabo.central_codex_account_pool import (
    AccountPoolConfigError,
    CentralCodexAccountPool,
)


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


if __name__ == "__main__":
    unittest.main()
