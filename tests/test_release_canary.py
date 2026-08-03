#!/usr/bin/env python3
"""Regression coverage for the no-write Admira release canary."""
import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class ReleaseCanaryTest(unittest.TestCase):
    def test_release_canary_validates_product_mcp_contract(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src")
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "release_canary.py")],
            cwd=str(ROOT),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CANARY PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
