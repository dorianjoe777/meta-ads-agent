import unittest
from unittest.mock import patch
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deploy.contabo import central_campaign_compiler_canary as canary


class CentralCampaignCompilerCanaryTests(unittest.TestCase):
    def test_canary_is_transport_only_and_reports_no_configuration(self):
        self.assertIn("never invokes a campaign MCP", canary.__doc__)
        with patch.object(canary, "maybe_compile_central_campaign", return_value=None):
            result = canary.run_real_canary(timeout=5)
        self.assertEqual(result["status"], "not_configured")
        self.assertFalse(result["ok"])

    def test_canary_accepts_only_terra_structured_non_ready_output(self):
        with patch.object(canary, "maybe_compile_central_campaign", return_value={
            "ok": True,
            "model": "gpt-5.6-terra",
            "compiled": {"ready": False, "missing_fields": ["canary"], "payload_json": "{}"},
        }) as compile_call:
            result = canary.run_real_canary(timeout=5)
        self.assertEqual(result, {
            "mode": "real", "ok": True, "status": "provider_verified", "model": "gpt-5.6-terra",
        })
        self.assertEqual(compile_call.call_args.args, (canary.CANARY_TOOL, canary.CANARY_PROMPT))

    def test_canary_rejects_ready_or_malformed_output(self):
        for compiled in ({"ready": True}, [], None):
            with self.subTest(compiled=compiled), patch.object(
                canary, "maybe_compile_central_campaign", return_value={"ok": True, "compiled": compiled}
            ):
                self.assertEqual(canary.run_real_canary(timeout=5)["status"], "invalid_output")


if __name__ == "__main__":
    unittest.main()
