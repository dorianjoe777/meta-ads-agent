import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class NvidiaProtectionCanaryTests(unittest.TestCase):
    def test_local_matrix_is_no_write_and_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "report.json"
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "nvidia_protection_canary.py"), "--output", str(report_path)],
                cwd=str(ROOT),
                env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(report["passed"])
            self.assertEqual(report["provider_calls"], 0)
            self.assertEqual(report["meta_calls"], 0)
            self.assertFalse(report["secrets_recorded"])
            self.assertGreaterEqual(len(report["rows"]), 6)
            self.assertEqual(report["fallback"]["primary"], "minimaxai/minimax-m3")
            self.assertEqual(report["fallback"]["first_model_specific_alternate"], "deepseek-ai/deepseek-v4-flash-0731")
            self.assertTrue(report["fallback"]["same_key_429_blocked"])
            self.assertEqual(report["fallback"]["api_max_retries"], 0)

    def test_remote_canary_is_explicitly_no_write_and_bounded(self):
        script = (ROOT / "scripts" / "run-remote-nvidia-protection-canary.sh").read_text(encoding="utf-8")
        self.assertIn("Do not call tools", script)
        self.assertIn("HERMES_STREAM_RETRIES=0", script)
        self.assertIn("ADMIRA_NVIDIA_REQUESTS_PER_MINUTE=36", script)
        self.assertIn("ADMIRA_NVIDIA_REQUEST_DIAGNOSTICS_FILE", script)
        self.assertIn("max_tokens_after", script)
        self.assertIn("estimated_input_tokens", script)
        self.assertIn("REMOTE NVIDIA CANARY PASS", script)
        self.assertNotIn("stage_campaign", script)
        self.assertNotIn("create_campaign", script)


if __name__ == "__main__":
    unittest.main()
