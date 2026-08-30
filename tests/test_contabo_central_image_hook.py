from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import codex_brand_guides as brand  # noqa: E402
import hosted_central_image_client as central_client  # noqa: E402


class CentralImageHookTests(unittest.TestCase):
    def _local_patches(self, bridge_result=None):
        config = type("Config", (), {"hermes_home": ""})()
        return (
            patch.object(brand, "load_config", return_value=config),
            patch.object(
                brand,
                "run_hermes_image_bridge",
                return_value=bridge_result or {"success": False, "error": "local fallback"},
            ),
            patch.object(
                brand,
                "publish_generated_image",
                return_value={
                    "ok": True,
                    "image_path": "/tmp/local.png",
                    "asset_id": "codex-local",
                    "preview_url": "/api/creative-asset?id=codex-local",
                },
            ),
        )

    def test_central_result_skips_local_provider(self):
        central_result = {
            "ok": True,
            "image_path": "/tmp/central.png",
            "asset_id": "central-123",
            "preview_url": "/api/creative-asset?id=central-123",
            "backend": "admira-central-image-broker",
        }
        with tempfile.TemporaryDirectory() as raw, patch.object(
            central_client, "maybe_generate_central_image", return_value=central_result
        ) as central, patch.object(brand, "run_hermes_image_bridge") as local:
            result = brand.call_codex_image_cli(
                "Genera una imagen", output_root=Path(raw), output_name="creative"
            )

        self.assertIs(result, central_result)
        central.assert_called_once()
        local.assert_not_called()

    def test_none_from_central_preserves_r90_local_flow(self):
        bridge_result = {
            "success": True,
            "image": "/tmp/generated.png",
            "returncode": 0,
            "provider": "openai-codex",
        }
        with tempfile.TemporaryDirectory() as raw, patch.object(
            central_client, "maybe_generate_central_image", return_value=None
        ) as central:
            patches = self._local_patches(bridge_result)
            with patches[0], patches[1] as local, patches[2]:
                result = brand.call_codex_image_cli(
                    "Genera una imagen", output_root=Path(raw), output_name="creative"
                )

        central.assert_called_once()
        local.assert_called_once()
        self.assertTrue(result["ok"])
        self.assertEqual(result["backend"], "hermes-openai-codex")

    def test_central_fail_closed_error_never_falls_back_local(self):
        blocked = {
            "ok": False,
            "reason": "central_not_ready",
            "error_type": "central_not_ready",
            "error": "La generación central todavía no está habilitada.",
        }
        with tempfile.TemporaryDirectory() as raw, patch.object(
            central_client, "maybe_generate_central_image", return_value=blocked
        ) as central, patch.object(brand, "run_hermes_image_bridge") as local:
            result = brand.call_codex_image_cli(
                "Genera una imagen", output_root=Path(raw), output_name="creative"
            )

        self.assertIs(result, blocked)
        central.assert_called_once()
        local.assert_not_called()


if __name__ == "__main__":
    unittest.main()
