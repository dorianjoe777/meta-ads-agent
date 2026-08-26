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

    def test_remote_canary_runbook_requires_safe_remote_gate(self):
        script = (ROOT / "scripts" / "run-remote-canary-release.sh").read_text(encoding="utf-8")
        local_script = (ROOT / "scripts" / "run-canary-release.sh").read_text(encoding="utf-8")
        runbook = (ROOT / "docs" / "release-canary-runbook.md").read_text(encoding="utf-8")
        for candidate in (script, local_script):
            self.assertIn("hermes mcp test admira", candidate)
            self.assertIn("CANARY_AGENT_OK", candidate)
            self.assertIn("timeout -k 5", candidate)
            self.assertIn("canary_home=", candidate)
            self.assertIn("mktemp -d", candidate)
            self.assertNotIn("mcp_admira_preflight_campaign exactly once", candidate)
        self.assertIn('HERMES_HOME_PATH="${2:-/app/runtime/hermes}"', local_script)
        self.assertNotIn('HERMES_HOME_PATH="${2:-/app/dashboard/data/hermes-home}"', local_script)
        self.assertIn("not** a stable", runbook)
        self.assertIn("Only after the remote canary passes", runbook)


if __name__ == "__main__":
    unittest.main()
