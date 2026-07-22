import json
import tempfile
import unittest
from pathlib import Path

import hermes_bridge


class NvidiaInferencePolicyTests(unittest.TestCase):
    def test_nvidia_uses_one_attempt_and_serial_crons(self):
        policy = hermes_bridge.inference_runtime_policy({
            "brain": "nvidia_nim",
            "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
            "model": "z-ai/glm-5.2",
        })
        self.assertEqual(policy["api_max_retries"], 1)
        self.assertEqual(policy["max_turns"], 24)
        self.assertEqual(policy["cron_max_parallel"], 1)

    def test_independent_provider_precedes_same_nvidia_key(self):
        original_connections = hermes_bridge.agent_model_connections
        original_nvidia_catalog = hermes_bridge.NVIDIA_MODEL_CATALOG_FILE
        original_codex_catalog = hermes_bridge.CODEX_MODEL_CATALOG_FILE
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                hermes_bridge.NVIDIA_MODEL_CATALOG_FILE = root / "nvidia.json"
                hermes_bridge.CODEX_MODEL_CATALOG_FILE = root / "codex.json"
                hermes_bridge.NVIDIA_MODEL_CATALOG_FILE.write_text(json.dumps({"models": ["z-ai/glm-5.2", "meta/llama-3.1-8b-instruct"]}), encoding="utf-8")
                hermes_bridge.CODEX_MODEL_CATALOG_FILE.write_text(json.dumps({"models": ["gpt-5.4-mini"]}), encoding="utf-8")
                hermes_bridge.agent_model_connections = lambda _config, include_secrets=False: {
                    "minimax": {"configured": True, "base_url": "https://api.minimax.io/v1", "model": "MiniMax-M3"}
                }
                chain = hermes_bridge.admira_inference_fallback_chain(object(), {
                    "brain": "nvidia_nim",
                    "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
                    "model": "z-ai/glm-5.2",
                    "base_url": hermes_bridge.ADMIRA_NVIDIA_DEFAULT_BASE_URL,
                })
                self.assertEqual(chain[0]["provider"], hermes_bridge.ADMIRA_MINIMAX_PROVIDER)
                self.assertEqual(chain[1]["provider"], "openai-codex")
                self.assertEqual(chain[-1]["provider"], hermes_bridge.ADMIRA_NVIDIA_PROVIDER)
        finally:
            hermes_bridge.agent_model_connections = original_connections
            hermes_bridge.NVIDIA_MODEL_CATALOG_FILE = original_nvidia_catalog
            hermes_bridge.CODEX_MODEL_CATALOG_FILE = original_codex_catalog


if __name__ == "__main__":
    unittest.main()
