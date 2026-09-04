from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import codex_brand_guides as brand  # noqa: E402
import codex_oauth_images as oauth_images  # noqa: E402
import hosted_central_image_client as central_client  # noqa: E402


class CentralImageHookTests(unittest.TestCase):
    def test_image_bridge_maps_product_ratios_to_direct_images_sizes(self):
        self.assertEqual(brand.infer_image_aspect_ratio("Crear un anuncio 4:5"), "4:5")
        self.assertEqual(brand.infer_image_aspect_ratio("Crear una historia 9:16"), "9:16")
        self.assertEqual(brand.infer_image_aspect_ratio("Crear una historia vertical"), "4:5")
        self.assertEqual(brand.infer_image_aspect_ratio("Crear un banner 16:9"), "16:9")
        self.assertEqual(brand.infer_image_aspect_ratio("Crear una imagen cuadrada"), "1:1")
        self.assertEqual(oauth_images._size_for_aspect("4:5"), "1024x1536")
        self.assertEqual(oauth_images._size_for_aspect("9:16"), "1024x1536")
        self.assertEqual(oauth_images._size_for_aspect("16:9"), "1536x1024")
        self.assertEqual(oauth_images._size_for_aspect("1:1"), "1024x1024")

    def test_image_failure_classifier_is_conservative_and_product_specific(self):
        self.assertEqual(
            brand.classify_image_failure("Codex usage limit reached after 5 hours", provider="openai-codex"),
            "codex_usage_limit",
        )
        self.assertEqual(
            brand.classify_image_failure("ChatGPT image generation limit reached", provider="openai-codex"),
            "chatgpt_images_limit",
        )
        self.assertEqual(
            brand.classify_image_failure("usage limit reached", error_type="rate_limit", backend="codex-cli-direct"),
            "codex_usage_limit",
        )
        self.assertEqual(
            brand.classify_image_failure("usage limit reached", error_type="rate_limit", backend="codex-oauth-images-direct"),
            "chatgpt_images_limit",
        )
        self.assertEqual(brand.classify_image_failure("usage limit reached", provider="openai-codex"), "unknown")
        self.assertEqual(brand.classify_image_failure("401 unauthorized", error_type="auth_required"), "provider_auth")
        self.assertEqual(brand.classify_image_failure("connection refused"), "provider_unavailable")
        self.assertEqual(brand.classify_image_failure("timed out", error_type="timeout"), "provider_timeout")

    def test_failure_metadata_contains_no_raw_provider_content(self):
        metadata = brand._image_failure_metadata(
            "secret-token prompt text usage limit reached", "model_usage_limit",
            backend="hermes-openai-codex", provider="openai-codex",
        )
        self.assertEqual(metadata["backend"], "hermes-openai-codex")
        self.assertEqual(metadata["failure_category"], "unknown")
        self.assertNotIn("secret-token", repr(metadata))
        self.assertNotIn("prompt text", repr(metadata))

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
            "provider": "openai-codex-images",
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
        self.assertEqual(result["backend"], "codex-oauth-images-direct")

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

    def test_explicit_central_codex_home_never_falls_back_to_main_home(self):
        config = type("Config", (), {"hermes_home": "/main/hermes"})()
        with patch.dict(
            brand.os.environ,
            {"ADMIRA_CODEX_AUTH_HOME": "/main/hermes/codex-auth"},
            clear=False,
        ), patch.object(brand, "image_codex_config", return_value=config), patch.object(
            brand, "codex_auth_artifact_present", return_value=False
        ):
            env = brand.codex_cli_environment(
                config, use_image_home=True, codex_home="/pool/slot-a"
            )
        self.assertEqual(env["CODEX_HOME"], "/pool/slot-a")


if __name__ == "__main__":
    unittest.main()
