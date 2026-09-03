from __future__ import annotations

import inspect
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import codex_brand_guides as brand


class NativeImageOAuthBridgeTests(unittest.TestCase):
    def test_pool_bridge_overrides_dedicated_and_global_homes_only_in_child(self):
        with tempfile.TemporaryDirectory() as root:
            before = dict(os.environ)
            with patch.object(brand, "load_config", return_value=object()), \
                 patch.object(brand, "hermes_python_executable", return_value="/hermes/python"), \
                 patch.object(brand, "hermes_image_environment", return_value={
                     "HERMES_HOME": "/wrong/dedicated", "CODEX_HOME": "/wrong/global"}), \
                 patch.object(brand.subprocess, "run", return_value=subprocess.CompletedProcess(
                     [], 0, '{"success":false}', "")) as run:
                brand.run_hermes_image_bridge({"prompt": "private"}, codex_home=root)
            self.assertEqual(run.call_args.args[0][0], "/hermes/python")
            self.assertEqual(run.call_args.kwargs["env"]["HERMES_HOME"], str(Path(root).resolve()))
            self.assertEqual(run.call_args.kwargs["env"]["CODEX_HOME"], str(Path(root).resolve()))
            payload = json.loads(run.call_args.kwargs["input"])
            self.assertTrue(payload["pool_oauth"])
            self.assertNotIn("pool_native", payload)
            self.assertEqual(dict(os.environ), before)

    def test_bridge_uses_r99_provider_contract_without_the_adapter_or_cli(self):
        script = brand.HERMES_IMAGE_BRIDGE_SCRIPT
        self.assertIn("prepare_hermes_oauth", script)
        self.assertIn("mirror_back_to_root", script)
        self.assertIn("provider.generate(**base_kwargs)", script)
        self.assertNotIn("codex_native_image_adapter", script)
        self.assertNotIn("call_codex_image_cli_direct", inspect.getsource(brand.call_codex_image_native))

    def test_native_failure_never_falls_back_to_cli_or_guesses_quota_type(self):
        with patch.object(brand, "run_hermes_image_bridge", return_value={
            "success": False, "error": "HTTP 429 usage_limit_reached SECRET", "error_type": "api_error"
        }), patch.object(brand, "call_codex_image_cli_direct") as cli:
            result = brand.call_codex_image_native("Make an image", codex_home="/private/slot")
        self.assertEqual(result["failure_category"], "provider_limited")
        self.assertNotIn("SECRET", repr(result))
        cli.assert_not_called()

    def test_native_success_publishes_output_and_keeps_style_reference_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            ref = Path(root) / "style.png"
            ref.write_bytes(b"\x89PNG\r\n\x1a\nreference")
            with patch.object(brand, "run_hermes_image_bridge", return_value={
                "success": True, "image": "/private/cache/image.png", "reference_image_count": 1
            }) as bridge, patch.object(brand, "publish_generated_image", return_value={
                "ok": True, "image_path": str(Path(root) / "final.png")
            }) as publish:
                result = brand.call_codex_image_native("Make a post 1:1", codex_home=root,
                    reference_image_paths=[str(ref)], output_root=root)
            self.assertTrue(result["ok"])
            self.assertEqual(bridge.call_args.args[0]["reference_image_paths"], [str(ref.resolve())])
            self.assertEqual(result["reference_image_count"], 1)
            publish.assert_called_once()


if __name__ == "__main__":
    unittest.main()
