import json
import tempfile
import unittest
from pathlib import Path

import admira_hermes_runtime_patch
import hermes_bridge
import hermes_gateway


class NvidiaInferencePolicyTests(unittest.TestCase):
    def test_nvidia_uses_one_attempt_and_serial_crons(self):
        policy = hermes_bridge.inference_runtime_policy({
            "brain": "nvidia_nim",
            "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
            "model": "z-ai/glm-5.2",
        })
        self.assertEqual(policy["api_max_retries"], 1)
        self.assertEqual(policy["max_turns"], 10)
        self.assertEqual(policy["cron_max_parallel"], 1)
        self.assertEqual(policy["model_context_length"], 80000)
        self.assertEqual(policy["compression_threshold"], 0.45)
        self.assertEqual(policy["compression_hard_message_limit"], 24)
        self.assertEqual(policy["compression_provider"], "custom")
        self.assertEqual(policy["compression_abort_on_failure"], False)
        self.assertEqual(policy["compression_timeout"], 45)
        self.assertEqual(policy["compression_base_url"], hermes_bridge.ADMIRA_NVIDIA_DEFAULT_BASE_URL)
        self.assertEqual(policy["context_file_max_chars"], 30000)

    def test_nvidia_compression_uses_compatible_custom_endpoint_and_safe_fallback(self):
        policy = hermes_bridge.inference_runtime_policy({
            "brain": "nvidia_nim",
            "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
            "model": "z-ai/glm-5.2",
            "base_url": hermes_bridge.ADMIRA_NVIDIA_DEFAULT_BASE_URL,
        })
        original_chain = hermes_bridge.admira_inference_fallback_chain
        try:
            hermes_bridge.admira_inference_fallback_chain = lambda _config, _brain: [
                {"provider": "admira-minimax", "model": "MiniMax-M3"},
                {"provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER, "model": "meta/llama"},
            ]
            lines = hermes_bridge.hermes_compression_config_lines(object(), {
                "brain": "nvidia_nim",
                "model": "z-ai/glm-5.2",
                "base_url": hermes_bridge.ADMIRA_NVIDIA_DEFAULT_BASE_URL,
            }, policy)
            text = "\n".join(lines)
            self.assertIn('abort_on_summary_failure: false', text)
            self.assertIn('provider: "custom"', text)
            self.assertIn('base_url: "https://integrate.api.nvidia.com/v1"', text)
            self.assertIn('fallback_chain:', text)
            self.assertIn('provider: "admira-minimax"', text)
            self.assertNotIn('meta/llama', text)
        finally:
            hermes_bridge.admira_inference_fallback_chain = original_chain

    def test_nvidia_model_config_has_operational_context_cap(self):
        policy = hermes_bridge.inference_runtime_policy({"brain": "nvidia_nim"})
        brain = {
            "brain": "nvidia_nim",
            "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
            "model": "z-ai/glm-5.2",
            "base_url": hermes_bridge.ADMIRA_NVIDIA_DEFAULT_BASE_URL,
            "context_length": policy["model_context_length"],
        }
        bridge_config = "\n".join(hermes_bridge._hermes_model_config_lines(brain))
        gateway_config = "\n".join(hermes_gateway._gateway_model_config_lines(brain))
        self.assertIn("context_length: 80000", bridge_config)
        self.assertIn("context_length: 80000", gateway_config)

    def test_connected_model_catalog_keeps_primary_context_cap(self):
        original_connections = hermes_bridge.agent_model_connections
        try:
            hermes_bridge.agent_model_connections = lambda _config, include_secrets=False: {
                "nvidia_nim": {
                    "configured": True,
                    "base_url": hermes_bridge.ADMIRA_NVIDIA_DEFAULT_BASE_URL,
                    "model": "z-ai/glm-5.2",
                }
            }
            lines = hermes_bridge.admira_connected_model_config_lines(
                object(),
                {
                    "brain": "nvidia_nim",
                    "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
                    "model": "z-ai/glm-5.2",
                    "context_length": 80000,
                },
            )
            self.assertIn("  context_length: 80000", lines)
        finally:
            hermes_bridge.agent_model_connections = original_connections

    def test_always_on_meta_context_is_compact_and_not_persisted(self):
        metric_row = {
            "id": "1",
            "name": "Active item",
            "status": "ACTIVE",
            "effective_status": "ACTIVE",
            "campaign_id": "1",
            "adset_id": "1",
            "spend": 12.5,
            "impressions": 1000,
            "clicks": 20,
            "ctr": 2,
            "funnel": {"large_duplicate_payload": "x" * 5000},
        }
        raw = {
            "ok": True,
            "campaigns": [{**metric_row, "id": str(index)} for index in range(100)],
            "adsets": [{**metric_row, "id": str(index)} for index in range(200)],
            "ads": [{**metric_row, "id": str(index)} for index in range(400)],
            "campaign_tree": [{"duplicate": "x" * 10000}] * 100,
        }
        compact = admira_hermes_runtime_patch._compact_live_meta_context(raw)
        serialized = json.dumps(compact, ensure_ascii=False)
        self.assertLess(len(serialized), 50000)
        self.assertNotIn("campaign_tree", compact)
        enriched = admira_hermes_runtime_patch._append_live_meta_context("hola", raw)
        persisted = admira_hermes_runtime_patch._strip_admira_runtime_injections(enriched)
        self.assertEqual(persisted, "hola")

    def test_independent_provider_precedes_same_nvidia_key(self):
        original_connections = hermes_bridge.agent_model_connections
        original_nvidia_catalog = hermes_bridge.NVIDIA_MODEL_CATALOG_FILE
        original_codex_catalog = hermes_bridge.CODEX_MODEL_CATALOG_FILE
        original_codex_health = hermes_bridge.codex_credential_health
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
                hermes_bridge.codex_credential_health = lambda _config: {"state": "stored", "reauth_required": False}
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
            hermes_bridge.codex_credential_health = original_codex_health

    def test_unconnected_codex_catalog_is_not_a_cron_fallback(self):
        original_connections = hermes_bridge.agent_model_connections
        original_catalog = hermes_bridge.CODEX_MODEL_CATALOG_FILE
        original_codex_health = hermes_bridge.codex_credential_health
        try:
            with tempfile.TemporaryDirectory() as directory:
                catalog = Path(directory) / "codex.json"
                catalog.write_text(json.dumps({"models": ["gpt-5.4-mini"]}), encoding="utf-8")
                hermes_bridge.CODEX_MODEL_CATALOG_FILE = catalog
                hermes_bridge.agent_model_connections = lambda _config, include_secrets=False: {}
                hermes_bridge.codex_credential_health = lambda _config: {"state": "missing", "reauth_required": False}
                chain = hermes_bridge.admira_inference_fallback_chain(object(), {
                    "brain": "nvidia_nim",
                    "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
                    "model": "z-ai/glm-5.2",
                })
                self.assertFalse(any(item["provider"] == "openai-codex" for item in chain))
        finally:
            hermes_bridge.agent_model_connections = original_connections
            hermes_bridge.CODEX_MODEL_CATALOG_FILE = original_catalog
            hermes_bridge.codex_credential_health = original_codex_health

    def test_nvidia_primary_has_bounded_m3_then_deepseek_fallback_without_catalog(self):
        original_catalog = hermes_bridge.NVIDIA_MODEL_CATALOG_FILE
        original_connections = hermes_bridge.agent_model_connections
        original_codex_health = hermes_bridge.codex_credential_health
        try:
            with tempfile.TemporaryDirectory() as directory:
                hermes_bridge.NVIDIA_MODEL_CATALOG_FILE = Path(directory) / "missing-nvidia.json"
                hermes_bridge.agent_model_connections = lambda _config, include_secrets=False: {}
                hermes_bridge.codex_credential_health = lambda _config: {"state": "missing", "reauth_required": False}
                chain = hermes_bridge.admira_inference_fallback_chain(object(), {
                    "brain": "nvidia_nim",
                    "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
                    "model": "z-ai/glm-5.2",
                    "base_url": hermes_bridge.ADMIRA_NVIDIA_DEFAULT_BASE_URL,
                })
                self.assertEqual(
                    [(item["provider"], item["model"]) for item in chain],
                    [
                        (hermes_bridge.ADMIRA_NVIDIA_PROVIDER, "minimaxai/minimax-m3"),
                        (hermes_bridge.ADMIRA_NVIDIA_PROVIDER, "deepseek-ai/deepseek-v4-flash"),
                    ],
                )
        finally:
            hermes_bridge.NVIDIA_MODEL_CATALOG_FILE = original_catalog
            hermes_bridge.agent_model_connections = original_connections
            hermes_bridge.codex_credential_health = original_codex_health


if __name__ == "__main__":
    unittest.main()
