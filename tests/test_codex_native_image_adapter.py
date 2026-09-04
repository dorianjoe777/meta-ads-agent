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
import codex_oauth_images as images


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

    def test_bridge_uses_standalone_oauth_images_without_responses_or_cli(self):
        script = brand.HERMES_IMAGE_BRIDGE_SCRIPT
        source = inspect.getsource(images)
        self.assertIn("handle_image_bridge_payload", script)
        self.assertIn("resolve_codex_runtime_credentials", source)
        self.assertIn("prepare_hermes_oauth", source)
        self.assertIn("mirror_back_to_root", source)
        self.assertIn("images/generations", source)
        self.assertIn("images/edits", source)
        self.assertNotIn("/responses", source)
        self.assertNotIn("provider.generate", source)
        self.assertNotIn("call_codex_image_cli_direct", inspect.getsource(brand.call_codex_image_native))

    def test_native_image_limit_never_falls_back_to_cli(self):
        with patch.object(brand, "run_hermes_image_bridge", return_value={
            "success": False, "error": "HTTP 429 usage_limit_reached SECRET", "error_type": "api_error"
        }), patch.object(brand, "call_codex_image_cli_direct") as cli:
            result = brand.call_codex_image_native("Make an image", codex_home="/private/slot")
        self.assertEqual(result["failure_category"], "chatgpt_images_limit")
        self.assertNotIn("SECRET", repr(result))
        cli.assert_not_called()

    def test_generation_request_has_no_host_model_or_responses_envelope(self):
        endpoint, body, tier, count = images._build_request({
            "prompt": "Make a portrait ad",
            "aspect_ratio": "4:5",
            "reference_image_paths": [],
        })
        self.assertEqual(endpoint, "images/generations")
        self.assertEqual(body["model"], "gpt-image-2")
        self.assertEqual(body["quality"], "medium")
        self.assertEqual(body["size"], "1024x1536")
        self.assertEqual(tier, "gpt-image-2-medium")
        self.assertEqual(count, 0)
        self.assertNotIn("tools", body)
        self.assertNotIn("instructions", body)
        self.assertNotIn("input", body)

    def test_direct_http_limit_keeps_only_safe_route_metadata(self):
        with patch.object(images, "_post_json", return_value=(429, {}, {"error": {"message": "secret"}})), \
             patch.object(images, "_first_party_headers", return_value={}), \
             patch.dict("sys.modules", {"hermes_cli.auth": __import__("types").SimpleNamespace(
                 resolve_codex_runtime_credentials=lambda **_kwargs: {"api_key": "not-logged"}
             )}):
            result = images.handle_image_bridge_payload({
                "mode": "generate", "prompt": "private", "aspect_ratio": "1:1"
            })
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "rate_limit")
        self.assertEqual(result["provider"], "openai-codex-images")
        self.assertEqual(result["transport"], "images/generations")
        self.assertEqual(result["model"], "gpt-image-2-medium")
        self.assertNotIn("secret", repr(result))

    def test_reference_request_uses_images_edits_json_contract(self):
        with tempfile.TemporaryDirectory() as root:
            ref = Path(root) / "reference.png"
            ref.write_bytes(b"\x89PNG\r\n\x1a\nreference")
            endpoint, body, _tier, count = images._build_request({
                "prompt": "Keep the reference product",
                "aspect_ratio": "1:1",
                "reference_image_paths": [str(ref)],
            })
        self.assertEqual(endpoint, "images/edits")
        self.assertEqual(count, 1)
        self.assertTrue(body["images"][0]["image_url"].startswith("data:image/png;base64,"))

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
            self.assertEqual(result["backend"], "codex-oauth-images-direct")
            publish.assert_called_once()


if __name__ == "__main__":
    unittest.main()
