import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import hermes_bridge


class HermesMcpEnvironmentTests(unittest.TestCase):
    def test_hosted_central_image_routes_are_forwarded_and_rewrite_stale_config(self):
        environment = {
            "ADMIRA_TENANT_ID": "canary-two",
            "ADMIRA_HOSTED_IMAGE_ACCESS_FILE": "/app/runtime/hosted_image_access.json",
            "ADMIRA_CENTRAL_IMAGE_SOCKET": "/run/admira-central-image-broker/broker.sock",
            "ADMIRA_CENTRAL_CAMPAIGN_COMPILER_SOCKET": "/run/admira-central-image-broker/compiler.sock",
            "ADMIRA_CENTRAL_IMAGE_CLIENT_KEY_FILE": "/app/runtime/central_image_client.key",
            "ADMIRA_CENTRAL_IMAGE_EXCHANGE_ROOT": "/run/admira-central-images",
        }
        policy = {
            "model_context_length": 0,
            "max_turns": 8,
            "api_max_retries": 0,
            "context_file_max_chars": hermes_bridge.HERMES_CONTEXT_FILE_SAFE_MAX_CHARS,
            "disable_delegation": False,
        }
        brain = {"brain": "custom", "provider": "custom", "model": "test-model"}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, environment):
            home = Path(directory) / "hermes"
            config = SimpleNamespace(
                hermes_home=str(home), daily_brief_timezone="UTC",
                hermes_disabled_toolsets="", hermes_enabled_toolsets="",
                codex_image_hermes_model="gpt-5.6-luna", hermes_model="gpt-5.6-luna",
                hermes_max_iterations=8,
            )
            with patch.object(hermes_bridge, "hermes_brain_settings", return_value=brain), \
                 patch.object(hermes_bridge, "inference_runtime_policy", return_value=policy), \
                 patch.object(hermes_bridge, "admira_connected_model_config_lines", return_value=["model: {}"]), \
                 patch.object(hermes_bridge, "admira_fallback_config_lines", return_value=["fallback_providers: []"]), \
                 patch.object(hermes_bridge, "hermes_compression_config_lines", return_value=[]), \
                 patch.object(hermes_bridge, "cli_toolsets", return_value=[]):
                first = hermes_bridge.write_cli_hermes_config(config, {"path": str(home / "workspace")})
                config_path = Path(first["config"])
                generated = config_path.read_text(encoding="utf-8")
                for name, value in environment.items():
                    self.assertIn(f'{name}: "{value}"', generated)

                config_path.write_text(generated.replace('      ADMIRA_TENANT_ID: "canary-two"\n', ""), encoding="utf-8")
                rewritten = hermes_bridge.write_cli_hermes_config(config, {"path": str(home / "workspace")})
                rewritten_config = config_path.read_text(encoding="utf-8")

        self.assertTrue(rewritten["written"])
        self.assertIn('ADMIRA_TENANT_ID: "canary-two"', rewritten_config)


if __name__ == "__main__":
    unittest.main()
