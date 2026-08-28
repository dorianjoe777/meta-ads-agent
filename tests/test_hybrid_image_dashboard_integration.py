import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from PIL import Image, ImageDraw
except ModuleNotFoundError:  # The production image runtime supplies Pillow.
    Image = ImageDraw = None


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hybrid_dashboard_test", ROOT / "dashboard" / "monitoring-dashboard.py")
dashboard = None
if Image is not None:
    dashboard = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(dashboard)


@unittest.skipIf(Image is None, "Pillow is supplied by the image runtime, not the minimal host test interpreter")
class HybridImageDashboardIntegrationTests(unittest.TestCase):
    def setUp(self):
        safe_root = Path(dashboard.CONTENT_ASSET_FILES_DIR)
        safe_root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=safe_root)
        self.root = Path(self.tmp.name)
        self.photo_a = self.root / "before.png"
        self.photo_b = self.root / "after.png"
        self.logo = self.root / "logo.png"
        Image.new("RGB", (80, 60), (20, 80, 150)).save(self.photo_a)
        Image.new("RGB", (80, 60), (180, 80, 30)).save(self.photo_b)
        Image.new("RGBA", (30, 12), (255, 0, 0, 255)).save(self.logo)
        self.overlay = self.root / "overlay.png"
        canvas = Image.new("RGB", (400, 240), "white")
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((20, 40, 185, 205), fill=(255, 0, 255))
        draw.rectangle((215, 40, 380, 205), fill=(0, 255, 255))
        canvas.save(self.overlay)
        self.library = {
            "items": [
                {"id": "photo-before", "category": "product", "preservation_mode": "pixel_locked", "classification_status": "classified", "approved_for_ads": True, "file_paths": [str(self.photo_a)]},
                {"id": "photo-after", "category": "product", "preservation_mode": "pixel_locked", "classification_status": "classified", "approved_for_ads": True, "file_paths": [str(self.photo_b)]},
                {"id": "style-1", "category": "style_reference", "preservation_mode": "style_only", "classification_status": "classified", "approved_for_ads": True, "file_paths": [str(self.logo)]},
            ]
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_hybrid_composes_photos_and_excludes_logo_from_provider(self):
        calls = []
        prompts = []

        def fake_provider(prompt, **kwargs):
            calls.append(kwargs.get("reference_image_paths"))
            prompts.append(prompt)
            Path(kwargs["output_root"]).mkdir(parents=True, exist_ok=True)
            out = Path(kwargs["output_root"]) / "provider-overlay.png"
            shutil.copy2(self.overlay, out)
            return {"ok": True, "image_path": str(out), "asset_id": "provider-overlay.png"}

        payload = {
            "request": "Crear diseño premium antes y después",
            "purpose": "ad_creative",
            "layout_intent": "before_after",
            "real_media": [
                {"slot_id": "before", "content_asset_id": "photo-before", "role": "before"},
                {"slot_id": "after", "content_asset_id": "photo-after", "role": "after"},
            ],
            "style_reference": {"mode": "none"},
            "include_logo": True,
        }
        with patch.object(dashboard, "load_content_asset_library", return_value=self.library), \
             patch.object(dashboard, "selected_product_guide_for_creative", return_value=("", "test")), \
             patch.object(dashboard, "creative_direct_context", return_value=""), \
             patch.object(dashboard, "creative_strategy_readiness", return_value={"ready": True}), \
             patch.object(dashboard, "official_brand_logo_path", return_value=str(self.logo)), \
             patch.object(dashboard, "call_codex_image_cli", side_effect=fake_provider):
            result = dashboard.codex_image_generate(payload)
        self.assertTrue(result["ok"], result)
        self.assertEqual(calls, [[]])
        self.assertIn("Do not use any saved style reference", prompts[0])
        self.assertTrue(result["hybrid"]["composition"]["pass"])
        self.assertTrue(Path(result["image_path"]).exists())
        self.assertTrue(result["prompt_package"]["real_media_provider_excluded"])
        self.assertEqual(result["output_sha256"], dashboard.content_asset_sha256(Path(result["image_path"])))
        self.assertNotIn(str(self.photo_a), json.dumps(result["hybrid"], ensure_ascii=False))
        self.assertNotIn(str(self.photo_b), json.dumps(result["hybrid"], ensure_ascii=False))

    def test_style_pool_is_opt_in_and_rotates_without_immediate_repeat(self):
        style_b = self.root / "style-b.png"
        Image.new("RGB", (20, 20), (0, 0, 0)).save(style_b)
        self.library["items"].append({"id": "style-2", "category": "style_reference", "preservation_mode": "style_only", "classification_status": "classified", "approved_for_ads": True, "file_paths": [str(style_b)]})
        dashboard.HYBRID_STYLE_SHUFFLE_FILE = self.root / "shuffle.json"
        first, first_evidence = dashboard._hybrid_style_reference({"style_reference": {"mode": "pool"}}, {item["id"]: item for item in self.library["items"]})
        second, second_evidence = dashboard._hybrid_style_reference({"style_reference": {"mode": "pool"}}, {item["id"]: item for item in self.library["items"]})
        self.assertNotEqual(first_evidence["asset_id"], second_evidence["asset_id"])
        self.assertTrue(first and second)
        none, evidence = dashboard._hybrid_style_reference({}, {item["id"]: item for item in self.library["items"]})
        self.assertIsNone(none)
        self.assertEqual(evidence["mode"], "none")

        sequence = []
        for _ in range(6):
            _, evidence = dashboard._hybrid_style_reference({"style_reference": {"mode": "pool"}}, {item["id"]: item for item in self.library["items"]})
            sequence.append(evidence["asset_id"])
        self.assertTrue(all(left != right for left, right in zip(sequence, sequence[1:])))

    def test_layout_counts_and_logo_default_behavior(self):
        payload = {
            "request": "Diseño para el servicio",
            "purpose": "ad_creative",
            "layout_intent": "hero",
            "real_media": [
                {"slot_id": "before", "content_asset_id": "photo-before", "role": "before"},
                {"slot_id": "after", "content_asset_id": "photo-after", "role": "after"},
            ],
        }
        with patch.object(dashboard, "load_content_asset_library", return_value=self.library), \
             patch.object(dashboard, "selected_product_guide_for_creative", return_value=("", "test")), \
             patch.object(dashboard, "creative_direct_context", return_value=""), \
             patch.object(dashboard, "creative_strategy_readiness", return_value={"ready": True}), \
             patch.object(dashboard, "official_brand_logo_path", return_value=None), \
             patch.object(dashboard, "call_codex_image_cli") as provider:
            result = dashboard.codex_image_generate(payload)
        self.assertFalse(result["ok"])
        self.assertIn("hero", result["error"])
        provider.assert_not_called()

        payload["layout_intent"] = "hero"
        payload["include_logo"] = True
        payload["real_media"] = [{"slot_id": "hero", "content_asset_id": "photo-before", "role": "hero"}]
        with patch.object(dashboard, "load_content_asset_library", return_value=self.library), \
             patch.object(dashboard, "selected_product_guide_for_creative", return_value=("", "test")), \
             patch.object(dashboard, "creative_direct_context", return_value=""), \
             patch.object(dashboard, "creative_strategy_readiness", return_value={"ready": True}), \
             patch.object(dashboard, "official_brand_logo_path", return_value=None), \
             patch.object(dashboard, "call_codex_image_cli") as provider:
            result = dashboard.codex_image_generate(payload)
        self.assertFalse(result["ok"])
        self.assertIn("logo", result["error"])
        provider.assert_not_called()

        payload["layout_intent"] = "hero"
        payload.pop("include_logo")
        payload["real_media"] = [{"slot_id": "hero", "content_asset_id": "photo-before", "role": "hero"}]
        def provider_without_logo(prompt, **kwargs):
            out_root = Path(kwargs["output_root"])
            out_root.mkdir(parents=True, exist_ok=True)
            out = out_root / "hybrid-no-logo.png"
            Image.new("RGB", (120, 120), (255, 0, 255)).save(out)
            return {"ok": True, "image_path": str(out)}
        with patch.object(dashboard, "load_content_asset_library", return_value=self.library), \
             patch.object(dashboard, "selected_product_guide_for_creative", return_value=("", "test")), \
             patch.object(dashboard, "creative_direct_context", return_value=""), \
             patch.object(dashboard, "creative_strategy_readiness", return_value={"ready": True}), \
             patch.object(dashboard, "official_brand_logo_path", return_value=None), \
             patch.object(dashboard, "call_codex_image_cli", side_effect=provider_without_logo):
            result = dashboard.codex_image_generate(payload)
        self.assertTrue(result["ok"], result)
        self.assertNotIn("logo", result["hybrid"])

        payload["include_logo"] = True
        payload["logo_color_mode"] = "white"
        with patch.object(dashboard, "load_content_asset_library", return_value=self.library), \
             patch.object(dashboard, "selected_product_guide_for_creative", return_value=("", "test")), \
             patch.object(dashboard, "creative_direct_context", return_value=""), \
             patch.object(dashboard, "creative_strategy_readiness", return_value={"ready": True}), \
             patch.object(dashboard, "official_brand_logo_path", return_value=str(self.logo)), \
             patch.object(dashboard, "call_codex_image_cli") as provider:
            result = dashboard.codex_image_generate(payload)
        self.assertFalse(result["ok"])
        self.assertIn("transparent", result["error"].lower())
        provider.assert_not_called()

    def test_named_green_brand_palette_never_uses_a_green_key(self):
        palette = dashboard._hybrid_rgb_palette(["verde esmeralda, blanco y negro"])
        self.assertIn((0, 138, 100), palette)
        keys = dashboard.choose_key_colors(4, palette)
        import colorsys
        green_hue = colorsys.rgb_to_hsv(0, 138 / 255, 100 / 255)[0]
        for key in keys:
            key_hue = colorsys.rgb_to_hsv(*(channel / 255 for channel in key))[0]
            distance = min(abs(key_hue - green_hue), 1 - abs(key_hue - green_hue)) * 360
            self.assertGreaterEqual(distance, 58)


if __name__ == "__main__":
    unittest.main()
