from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import codex_brand_guides as brand
import codex_native_image_adapter as adapter


class NativeImageAdapterTests(unittest.TestCase):
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
            self.assertTrue(json.loads(run.call_args.kwargs["input"])["pool_native"])
            self.assertEqual(dict(os.environ), before)

    def test_native_failure_never_falls_back_to_cli_or_guesses_quota_type(self):
        with patch.object(brand, "run_hermes_image_bridge", return_value={
            "success": False, "error": "HTTP 429 usage_limit_reached SECRET", "error_type": "api_error"
        }), patch.object(brand, "call_codex_image_cli_direct") as cli:
            result = brand.call_codex_image_native("Make an image", codex_home="/private/slot")
        self.assertEqual(result["failure_category"], "provider_limited")
        self.assertNotIn("SECRET", repr(result))
        cli.assert_not_called()

    def test_native_success_publishes_output_and_keeps_references(self):
        with tempfile.TemporaryDirectory() as root:
            ref = Path(root) / "photo.png"
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

    def _provider(self, events=None):
        module = types.ModuleType("fake_native_image_provider")
        module._read_codex_access_token = Mock(return_value="wrong-global-token")
        module._build_responses_payload = lambda **kwargs: {
            "input": [{"role": "user", "content": [{"type": "input_text", "text": kwargs["prompt"]}]}]
        }
        module._iter_sse_json = lambda response: iter(events or [{"type": "response.completed"}])
        captured = {}
        def generate(self, *, prompt, aspect_ratio):
            captured["token"] = module._read_codex_access_token()
            captured["body"] = module._build_responses_payload(prompt=prompt)
            captured["events"] = list(module._iter_sse_json(None))
            return {"success": True, "image": "/private/cache/image.png"}
        provider_type = type("Provider", (), {"__module__": module.__name__, "generate": generate})
        auth = types.ModuleType("hermes_cli.auth")
        auth.resolve_codex_runtime_credentials = Mock(return_value={"api_key": "selected-slot-token"})
        session = types.ModuleType("codex_oauth_session")
        session.prepare_hermes_oauth = Mock(return_value="/private/slot/auth.json")
        session.mirror_back_to_root = Mock()
        return module, provider_type(), auth, session, captured

    def test_photo_bytes_enter_native_request_and_slot_auth_is_restored(self):
        module, provider, auth, session, captured = self._provider()
        original_reader = module._read_codex_access_token
        with tempfile.TemporaryDirectory() as root:
            photo = Path(root) / "photo.jpg"
            data = b"\xff\xd8\xffreal-photo-bytes"
            photo.write_bytes(data)
            with patch.dict(sys.modules, {module.__name__: module, "hermes_cli.auth": auth,
                                         "codex_oauth_session": session}):
                result = adapter.generate_pool_image(provider, prompt="photo post", aspect_ratio="1:1",
                                                     reference_paths=[photo])
        self.assertTrue(result["success"])
        self.assertEqual(result["reference_image_count"], 1)
        self.assertEqual(captured["token"], "selected-slot-token")
        content = captured["body"]["input"][0]["content"]
        self.assertEqual(content[1]["type"], "input_image")
        self.assertEqual(base64.b64decode(content[1]["image_url"].split(",", 1)[1]), data)
        self.assertIs(module._read_codex_access_token, original_reader)
        self.assertEqual(session.mirror_back_to_root.call_count, 2)
        session.mirror_back_to_root.assert_called_with("/private/slot/auth.json")

    def test_stream_error_cannot_return_a_partial_image_as_success(self):
        module, provider, auth, session, captured = self._provider([
            {"type": "response.image_generation_call.partial_image", "partial_image_b64": "partial"},
            {"type": "response.failed", "response": {"error": {"code": "usage_limit_reached"}}},
        ])
        original_reader = module._read_codex_access_token
        with patch.dict(sys.modules, {module.__name__: module, "hermes_cli.auth": auth,
                                     "codex_oauth_session": session}):
            with self.assertRaisesRegex(RuntimeError, "usage_limit_reached"):
                adapter.generate_pool_image(provider, prompt="post", aspect_ratio="1:1", reference_paths=[])
        self.assertIs(module._read_codex_access_token, original_reader)
        self.assertEqual(session.mirror_back_to_root.call_count, 2)

    def test_invalid_or_symlink_reference_is_rejected_before_provider_request(self):
        with tempfile.TemporaryDirectory() as root:
            photo = Path(root) / "bad.png"
            photo.write_text("not an image")
            with self.assertRaises(ValueError):
                adapter._reference_parts([photo])
            alias = Path(root) / "alias.png"
            alias.symlink_to(photo)
            with self.assertRaises(ValueError):
                adapter._reference_parts([alias])


if __name__ == "__main__":
    unittest.main()
