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
        self.photo_c = self.root / "third.png"
        self.logo = self.root / "logo.png"
        Image.new("RGB", (80, 60), (20, 80, 150)).save(self.photo_a)
        Image.new("RGB", (80, 60), (180, 80, 30)).save(self.photo_b)
        Image.new("RGB", (80, 60), (30, 150, 80)).save(self.photo_c)
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
                {"id": "photo-third", "category": "product", "preservation_mode": "pixel_locked", "classification_status": "classified", "approved_for_ads": True, "file_paths": [str(self.photo_c)]},
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
        self.assertIn("official-logo safe zone in the top-right corner", prompts[0])
        self.assertTrue(result["hybrid"]["composition"]["pass"])
        self.assertTrue(Path(result["image_path"]).exists())
        self.assertTrue(result["prompt_package"]["real_media_provider_excluded"])
        self.assertEqual(result["hybrid"]["logo"]["position"], "top_right")
        self.assertEqual(result["output_sha256"], dashboard.content_asset_sha256(Path(result["image_path"])))
        self.assertFalse((Path(dashboard.CREATIVE_ASSET_ROOT) / "provider-overlay.png").exists())
        self.assertNotIn(str(self.photo_a), json.dumps(result["hybrid"], ensure_ascii=False))
        self.assertNotIn(str(self.photo_b), json.dumps(result["hybrid"], ensure_ascii=False))

    def test_brand_references_are_automatic_and_task_reference_is_added_first(self):
        style_b = self.root / "style-b.png"
        style_task = self.root / "style-task.png"
        Image.new("RGB", (20, 20), (0, 0, 0)).save(style_b)
        Image.new("RGB", (20, 20), (80, 40, 120)).save(style_task)
        self.library["items"][3]["reference_scope"] = "brand"
        self.library["items"].append({"id": "style-2", "category": "style_reference", "preservation_mode": "style_only", "classification_status": "classified", "approved_for_ads": True, "reference_scope": "brand", "file_paths": [str(style_b)]})
        self.library["items"].append({"id": "style-task", "category": "style_reference", "preservation_mode": "style_only", "classification_status": "classified", "approved_for_ads": True, "reference_scope": "task", "file_paths": [str(style_task)]})
        index = {item["id"]: item for item in self.library["items"]}

        automatic, automatic_evidence = dashboard._creative_style_references({}, index)
        self.assertEqual(automatic, [str(self.logo), str(style_b)])
        self.assertEqual(automatic_evidence["mode"], "brand")
        self.assertEqual(automatic_evidence["brand_asset_ids"], ["style-1", "style-2"])

        explicit, explicit_evidence = dashboard._creative_style_references(
            {"style_reference": {"mode": "explicit", "asset_id": "style-task"}}, index
        )
        self.assertEqual(explicit, [str(style_task), str(self.logo), str(style_b)])
        self.assertEqual(explicit_evidence["explicit_asset_id"], "style-task")

        legacy_selected, legacy_evidence = dashboard._creative_style_references(
            {"content_asset_ids": ["style-task"]}, index
        )
        self.assertEqual(legacy_selected, explicit)
        self.assertEqual(legacy_evidence["task_asset_ids"], ["style-task"])

        pooled, pooled_evidence = dashboard._creative_style_references(
            {"style_reference": {"mode": "pool"}}, index
        )
        self.assertEqual(pooled, automatic)
        self.assertEqual(pooled_evidence["brand_asset_ids"], ["style-1", "style-2"])

        none, evidence = dashboard._creative_style_references(
            {"style_reference": {"mode": "none"}}, index
        )
        self.assertEqual(none, [])
        self.assertEqual(evidence["mode"], "none")

    def test_three_photo_collage_attaches_task_style_reference_and_preserves_every_slot(self):
        provider_references = []
        prompts = []

        def provider(prompt, **kwargs):
            prompts.append(prompt)
            provider_references.append(list(kwargs.get("reference_image_paths") or []))
            out = Path(kwargs["output_root"]) / "three-photo-overlay.png"
            canvas = Image.new("RGB", (600, 300), (18, 24, 36))
            draw = ImageDraw.Draw(canvas)
            draw.rectangle((20, 50, 180, 250), fill=(255, 0, 255))
            draw.rectangle((220, 50, 380, 250), fill=(0, 255, 255))
            draw.rectangle((420, 50, 580, 250), fill=(255, 255, 0))
            if len(prompts) == 1:
                draw.rectangle((8, 8, 48, 38), fill=(255, 0, 255))
            canvas.save(out)
            return {"ok": True, "image_path": str(out)}

        payload = {
            "request": "Collage animado con los tres platos, teléfono 0987966452 y bebidas 2x1",
            "purpose": "ad_creative",
            "layout_intent": "collage",
            "real_media": [
                {"slot_id": "cangrejada", "content_asset_id": "photo-before", "role": "collage_item", "label": "Cangrejada"},
                {"slot_id": "encebollado", "content_asset_id": "photo-after", "role": "collage_item", "label": "Encebollado"},
                {"slot_id": "sopa", "content_asset_id": "photo-third", "role": "collage_item", "label": "Sopa marinera"},
            ],
            "style_reference": {"mode": "explicit", "asset_id": "style-1"},
            "text_content": {"promotion": "Bebidas 2x1", "phone": "0987966452"},
            "include_logo": False,
        }
        with patch.object(dashboard, "load_content_asset_library", return_value=self.library), \
             patch.object(dashboard, "selected_product_guide_for_creative", return_value=("", "test")), \
             patch.object(dashboard, "creative_direct_context", return_value=""), \
             patch.object(dashboard, "creative_strategy_readiness", return_value={"ready": True}), \
             patch.object(dashboard, "official_brand_logo_path", return_value=None), \
             patch.object(dashboard, "call_codex_image_cli", side_effect=provider):
            result = dashboard.codex_image_generate(payload)

        self.assertTrue(result["ok"], result)
        self.assertEqual(provider_references, [[str(self.logo)], [str(self.logo)]])
        self.assertNotIn(str(self.photo_a), provider_references[0] + provider_references[1])
        self.assertNotIn(str(self.photo_b), provider_references[0] + provider_references[1])
        self.assertNotIn(str(self.photo_c), provider_references[0] + provider_references[1])
        self.assertEqual(len(prompts), 2)
        self.assertIn("MANDATORY CORRECTION RETRY", prompts[1])
        self.assertEqual(result["hybrid"]["style_reference"]["explicit_asset_id"], "style-1")
        self.assertEqual([slot["slot_id"] for slot in result["hybrid"]["slots"]], ["cangrejada", "encebollado", "sopa"])
        self.assertEqual(result["prompt_package"]["real_media_count"], 3)
        self.assertIn("cangrejada=#FF00FF", prompts[1])
        self.assertIn("encebollado=#00FFFF", prompts[1])
        self.assertIn("sopa=#FFFF00", prompts[1])
        self.assertIn("first attached design reference is explicit inspiration for this task only", prompts[0])
        self.assertIn("0987966452", prompts[0])
        self.assertIn("Bebidas 2x1", prompts[0])

    def test_style_reference_can_never_be_promoted_to_real_background(self):
        self.library["items"][3]["reference_scope"] = "brand"
        captured = {}
        prompt_package = {
            "mode": "fixed", "purpose": "standalone_asset", "seed": "test",
            "variation_count": 1, "variation_ledger": [], "product_guide": "",
            "ad_brief": "", "logo_context": "", "prompts": [{
                "image_prompt": "ordinary prompt", "variant_id": "ordinary",
                "design_axis": "", "composition": "", "experiment": "",
            }],
        }

        def provider(prompt, **kwargs):
            captured["prompt"] = prompt
            captured["references"] = list(kwargs.get("reference_image_paths") or [])
            out = Path(kwargs["output_root"]) / "style-only-output.png"
            Image.new("RGB", (120, 120), (18, 24, 36)).save(out)
            return {"ok": True, "image_path": str(out), "asset_id": "style-only-output.png"}

        with patch.object(dashboard, "load_content_asset_library", return_value=self.library), \
             patch.object(dashboard, "selected_product_guide_for_creative", return_value=("", "test")), \
             patch.object(dashboard, "creative_direct_context", return_value=""), \
             patch.object(dashboard, "creative_strategy_readiness", return_value={"ready": True}), \
             patch.object(dashboard, "build_codex_image_prompt_package", return_value=prompt_package), \
             patch.object(dashboard, "official_brand_logo_path", return_value=None), \
             patch.object(dashboard, "call_codex_image_cli", side_effect=provider):
            result = dashboard.codex_image_generate({
                "request": "usa esta referencia como fondo visual",
                "purpose": "standalone_asset",
                "include_logo": False,
            })

        self.assertTrue(result["ok"], result)
        self.assertEqual(captured["references"], [str(self.logo)])
        self.assertEqual(result["prompt_package"]["protected_reference_image_count"], 0)
        self.assertEqual(result["prompt_package"]["reference_image_role"], "reference")
        self.assertNotIn("MODO FOTO REAL COMO BASE", captured["prompt"])
        self.assertNotIn("ACTIVOS REALES PROTEGIDOS", captured["prompt"])

    def test_failed_hybrid_mask_leaves_no_provider_overlay_or_false_final(self):
        provider_overlay = Path(dashboard.CREATIVE_ASSET_ROOT) / "invalid-provider-overlay.png"
        false_final = provider_overlay.with_name("invalid-provider-overlay-composited.png")
        provider_overlay.unlink(missing_ok=True)
        false_final.unlink(missing_ok=True)

        def invalid_provider(_prompt, **kwargs):
            Path(kwargs["output_root"]).mkdir(parents=True, exist_ok=True)
            canvas = Image.new("RGB", (240, 180), (18, 24, 36))
            canvas.save(provider_overlay)
            return {"ok": True, "image_path": str(provider_overlay)}

        payload = {
            "request": "Diseño con una foto real",
            "purpose": "ad_creative",
            "layout_intent": "hero",
            "real_media": [{"slot_id": "hero", "content_asset_id": "photo-before", "role": "hero"}],
            "style_reference": {"mode": "none"},
            "include_logo": False,
        }
        with patch.object(dashboard, "load_content_asset_library", return_value=self.library), \
             patch.object(dashboard, "selected_product_guide_for_creative", return_value=("", "test")), \
             patch.object(dashboard, "creative_direct_context", return_value=""), \
             patch.object(dashboard, "creative_strategy_readiness", return_value={"ready": True}), \
             patch.object(dashboard, "official_brand_logo_path", return_value=None), \
             patch.object(dashboard, "call_codex_image_cli", side_effect=invalid_provider):
            result = dashboard.codex_image_generate(payload)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason"], "hybrid_overlay_invalid")
        self.assertTrue(result["retryable"])
        self.assertEqual(len(result["hybrid"]["attempts"]), 2)
        self.assertNotIn("key colour missing", json.dumps(result, ensure_ascii=False).lower())
        self.assertFalse(provider_overlay.exists())
        self.assertFalse(false_final.exists())

    def test_first_invalid_overlay_is_deleted_and_second_same_source_succeeds(self):
        calls = []

        def retry_provider(prompt, **kwargs):
            calls.append((prompt, list(kwargs.get("reference_image_paths") or [])))
            out = Path(kwargs["output_root"]) / "retry-overlay.png"
            canvas = Image.new("RGB", (240, 180), (18, 24, 36))
            draw = ImageDraw.Draw(canvas)
            if len(calls) == 1:
                pass
            else:
                draw.rectangle((20, 20, 220, 160), fill=(255, 0, 255))
            canvas.save(out)
            return {"ok": True, "image_path": str(out)}

        payload = {
            "request": "Diseño con una foto real", "purpose": "ad_creative",
            "layout_intent": "hero",
            "real_media": [{"slot_id": "hero", "content_asset_id": "photo-before", "role": "hero"}],
            "style_reference": {"mode": "none"}, "include_logo": False,
        }
        with patch.object(dashboard, "load_content_asset_library", return_value=self.library), \
             patch.object(dashboard, "selected_product_guide_for_creative", return_value=("", "test")), \
             patch.object(dashboard, "creative_direct_context", return_value=""), \
             patch.object(dashboard, "creative_strategy_readiness", return_value={"ready": True}), \
             patch.object(dashboard, "official_brand_logo_path", return_value=None), \
             patch.object(dashboard, "call_codex_image_cli", side_effect=retry_provider):
            result = dashboard.codex_image_generate(payload)
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1], calls[1][1])
        self.assertIn("MANDATORY CORRECTION RETRY", calls[1][0])
        self.assertIn("hero=#FF00FF", calls[1][0])
        self.assertTrue(result["hybrid"]["composition"]["pass"])
        self.assertFalse((self.root / "retry-overlay.png").exists())

    def _hero_payload(self):
        return {
            "request": "Diseño con una foto real", "purpose": "ad_creative",
            "layout_intent": "hero",
            "real_media": [{"slot_id": "hero", "content_asset_id": "photo-before", "role": "hero"}],
            "style_reference": {"mode": "none"}, "include_logo": False,
        }

    def test_extra_component_retries_same_contract_then_fails_closed(self):
        calls = []

        def provider(_prompt, **kwargs):
            calls.append(True)
            out = Path(kwargs["output_root"]) / "extra-component.png"
            canvas = Image.new("RGB", (240, 180), (18, 24, 36))
            draw = ImageDraw.Draw(canvas)
            draw.rectangle((20, 20, 180, 160), fill=(255, 0, 255))
            draw.rectangle((200, 5, 230, 35), fill=(255, 0, 255))
            canvas.save(out)
            return {"ok": True, "image_path": str(out)}

        with patch.object(dashboard, "load_content_asset_library", return_value=self.library), \
             patch.object(dashboard, "selected_product_guide_for_creative", return_value=("", "test")), \
             patch.object(dashboard, "creative_direct_context", return_value=""), \
             patch.object(dashboard, "creative_strategy_readiness", return_value={"ready": True}), \
             patch.object(dashboard, "official_brand_logo_path", return_value=None), \
             patch.object(dashboard, "call_codex_image_cli", side_effect=provider):
            result = dashboard.codex_image_generate(self._hero_payload())
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "hybrid_overlay_invalid")
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(result["retry_contract"]["real_media"]), 1)
        self.assertEqual(result["retry_contract"]["real_media"][0]["content_asset_id"], "photo-before")
        self.assertFalse((self.root / "extra-component.png").exists())

    def test_provider_failure_is_not_retried_or_reclassified(self):
        calls = []

        def provider(_prompt, **_kwargs):
            calls.append(True)
            return {"ok": False, "reason": "provider_quota_exhausted", "error": "quota"}

        with patch.object(dashboard, "load_content_asset_library", return_value=self.library), \
             patch.object(dashboard, "selected_product_guide_for_creative", return_value=("", "test")), \
             patch.object(dashboard, "creative_direct_context", return_value=""), \
             patch.object(dashboard, "creative_strategy_readiness", return_value={"ready": True}), \
             patch.object(dashboard, "official_brand_logo_path", return_value=None), \
             patch.object(dashboard, "call_codex_image_cli", side_effect=provider):
            result = dashboard.codex_image_generate(self._hero_payload())
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "provider_quota_exhausted")
        self.assertEqual(len(calls), 1)
        self.assertNotEqual(result.get("reason"), "hybrid_overlay_invalid")

    def test_missing_then_second_provider_failure_preserves_provider_result(self):
        calls = []

        def provider(_prompt, **kwargs):
            calls.append(True)
            if len(calls) == 1:
                out = Path(kwargs["output_root"]) / "missing-then-provider.png"
                Image.new("RGB", (240, 180), (18, 24, 36)).save(out)
                return {"ok": True, "image_path": str(out)}
            return {"ok": False, "reason": "provider_auth_failed", "error": "auth"}

        with patch.object(dashboard, "load_content_asset_library", return_value=self.library), \
             patch.object(dashboard, "selected_product_guide_for_creative", return_value=("", "test")), \
             patch.object(dashboard, "creative_direct_context", return_value=""), \
             patch.object(dashboard, "creative_strategy_readiness", return_value={"ready": True}), \
             patch.object(dashboard, "official_brand_logo_path", return_value=None), \
             patch.object(dashboard, "call_codex_image_cli", side_effect=provider):
            result = dashboard.codex_image_generate(self._hero_payload())
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "provider_auth_failed")
        self.assertEqual(len(calls), 2)
        self.assertFalse((self.root / "missing-then-provider.png").exists())

    def test_ok_without_png_path_cannot_be_delivered(self):
        calls = []

        def provider(_prompt, **_kwargs):
            calls.append(True)
            return {"ok": True, "image_path": str(self.root / "not-png.jpg")}

        with patch.object(dashboard, "load_content_asset_library", return_value=self.library), \
             patch.object(dashboard, "selected_product_guide_for_creative", return_value=("", "test")), \
             patch.object(dashboard, "creative_direct_context", return_value=""), \
             patch.object(dashboard, "creative_strategy_readiness", return_value={"ready": True}), \
             patch.object(dashboard, "official_brand_logo_path", return_value=None), \
             patch.object(dashboard, "call_codex_image_cli", side_effect=provider):
            result = dashboard.codex_image_generate(self._hero_payload())
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "hybrid_provider_invalid")
        self.assertEqual(len(calls), 1)
        self.assertNotIn("image_path", result)

    def test_hybrid_failure_uses_buyer_safe_localized_tool_reply(self):
        result = {
            "ok": False,
            "blocked": True,
            "reason": "hybrid_overlay_invalid",
            "error": dashboard.HYBRID_OVERLAY_INVALID_MESSAGE_ES,
            "message": dashboard.HYBRID_OVERLAY_INVALID_MESSAGE_ES,
            "message_en": dashboard.HYBRID_OVERLAY_INVALID_MESSAGE_EN,
        }
        with patch.object(dashboard, "codex_image_generate", return_value=result):
            spanish = dashboard.handle_codex_image_generate_tool({}, {"language": "es"}, "codex_image_generate")
            english = dashboard.handle_codex_image_generate_tool({}, {"language": "en"}, "codex_image_generate")
        self.assertEqual(spanish["reply"], dashboard.HYBRID_OVERLAY_INVALID_MESSAGE_ES)
        self.assertEqual(english["reply"], dashboard.HYBRID_OVERLAY_INVALID_MESSAGE_EN)
        for reply in (spanish["reply"], english["reply"]):
            self.assertNotIn("key colour missing", reply.lower())
            self.assertNotIn("otra api", reply.lower())
            self.assertNotIn("/app/", reply)

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

    def test_sparse_hybrid_request_is_enriched_from_exact_brand_offer_and_brief(self):
        prompts = []

        def provider(prompt, **kwargs):
            prompts.append(prompt)
            out = Path(kwargs["output_root"]) / "sparse-enriched-overlay.png"
            Image.new("RGB", (180, 180), (255, 0, 255)).save(out)
            return {"ok": True, "image_path": str(out)}

        brand_library = {
            "general": {"fields": {
                "brand_name": "Rodeo - Car Detailing",
                "colors": "negro mate, gris grafito, naranja cobrizo",
                "typography": "sans serif condensada y contundente",
                "visual_style": "automotriz premium, limpio y moderno",
                "tone": "directo y confiable",
                "avoid_always": "caballos o estética western literal",
            }},
            "products": [{
                "id": "rodeo-premium",
                "name": "Rodeo Premium",
                "guide": "brand_guides/products/rodeo-premium.md",
                "fields": {
                    "name": "Rodeo Premium",
                    "price": "$110.000 COP",
                    "includes": "limpieza profunda y protección con cera",
                    "audience": "propietarios de vehículos en Bogotá norte",
                    "desire": "recuperar una apariencia impecable",
                },
            }],
            "ad_briefs": [{
                "id": "premium-whatsapp",
                "name": "Premium WhatsApp",
                "guide": "brand_guides/ad_briefs/premium-whatsapp.md",
                "fields": {
                    "objective": "Conseguir conversaciones calificadas por WhatsApp",
                    "headline": "Tu carro merece un cuidado premium",
                    "cta": "Agenda por WhatsApp",
                    "formats": "4:5",
                },
            }],
        }
        payload = {
            "request": "Haz algo atractivo con esta foto.",
            "purpose": "ad_creative",
            "product_guide": "rodeo-premium",
            "ad_brief": "premium-whatsapp",
            "layout_intent": "hero",
            "real_media": [{"slot_id": "hero", "content_asset_id": "photo-before", "role": "hero"}],
            "style_reference": {"mode": "none"},
            "include_logo": False,
        }
        with patch.object(dashboard, "load_content_asset_library", return_value=self.library), \
             patch.object(dashboard, "selected_product_guide_for_creative", return_value=("rodeo-premium", "explicit_product_guide")), \
             patch.object(dashboard, "creative_direct_context", return_value=""), \
             patch.object(dashboard, "creative_strategy_readiness", return_value={"ready": True}), \
             patch.object(dashboard, "guide_library", return_value=brand_library), \
             patch.object(dashboard, "official_brand_logo_path", return_value=None), \
             patch.object(dashboard, "call_codex_image_cli", side_effect=provider):
            result = dashboard.codex_image_generate(payload)
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(prompts), 1)
        prompt = prompts[0]
        self.assertIn("Haz algo atractivo con esta foto", prompt)
        self.assertIn("Rodeo Premium", prompt)
        self.assertIn("$110.000 COP", prompt)
        self.assertIn("Conseguir conversaciones calificadas por WhatsApp", prompt)
        self.assertIn("propietarios de vehículos en Bogotá norte", prompt)
        self.assertIn("Rodeo - Car Detailing", prompt)
        self.assertIn("automotriz premium, limpio y moderno", prompt)
        self.assertIn("Output format/aspect ratio: 4:5", prompt)
        self.assertIn("Tu carro merece un cuidado premium", prompt)
        self.assertIn("Agenda por WhatsApp", prompt)
        self.assertIn("Do not use any saved style reference", prompt)
        self.assertNotIn(str(self.photo_a), prompt)

    def test_explicit_hybrid_text_and_extra_direction_are_never_replaced(self):
        context = dashboard._hybrid_semantic_prompt_context(
            {
                "visual_direction": "Añade una insignia discreta y deja aire arriba.",
                "desired_on_image_message": "Mensaje de respaldo que no debe reemplazar el título",
                "cta_decision": "Escríbenos",
                "text_content": {
                    "title": "FULL DETAIL",
                    "bullets": ["Pulido", "Protección"],
                    "cta": "Agenda tu diagnóstico",
                },
            },
            {"general": {"fields": {"brand_name": "Rodeo"}}},
        )
        self.assertEqual(context["text_content"]["title"], "FULL DETAIL")
        self.assertEqual(context["text_content"]["bullets"], ["Pulido", "Protección"])
        self.assertEqual(context["text_content"]["cta"], "Agenda tu diagnóstico")

    def test_minimal_request_uses_only_the_already_selected_offer(self):
        prompts = []

        def provider(prompt, **kwargs):
            prompts.append(prompt)
            out = Path(kwargs["output_root"]) / "minimal-selected-offer-overlay.png"
            Image.new("RGB", (180, 180), (255, 0, 255)).save(out)
            return {"ok": True, "image_path": str(out)}

        library = {
            "general": {"fields": {"brand_name": "Rodeo", "colors": "negro, naranja"}},
            "products": [
                {
                    "id": "rodeo-express",
                    "name": "Rodeo Express",
                    "guide": "brand_guides/products/rodeo-express.md",
                    "fields": {
                        "name": "Rodeo Express",
                        "price": "$45.000 COP",
                        "desire": "lavado rápido",
                        "audience": "conductores con poco tiempo",
                    },
                },
                {
                    "id": "rodeo-premium",
                    "name": "Rodeo Premium",
                    "guide": "brand_guides/products/rodeo-premium.md",
                    "fields": {
                        "name": "Rodeo Premium",
                        "price": "$110.000 COP",
                        "desire": "protección y limpieza profunda",
                        "audience": "propietarios que cuidan cada detalle",
                    },
                },
            ],
            "ad_briefs": [],
        }
        payload = {
            "request": "Haz otro diseño atractivo con esta foto.",
            "purpose": "ad_creative",
            "real_media": [{"slot_id": "hero", "content_asset_id": "photo-before", "role": "hero"}],
        }
        with patch.object(dashboard, "load_content_asset_library", return_value=self.library), \
             patch.object(dashboard, "selected_product_guide_for_creative", return_value=("rodeo-premium", "selected_context")), \
             patch.object(dashboard, "creative_direct_context", return_value=""), \
             patch.object(dashboard, "creative_strategy_readiness", return_value={"ready": True}), \
             patch.object(dashboard, "guide_library", return_value=library), \
             patch.object(dashboard, "official_brand_logo_path", return_value=None), \
             patch.object(dashboard, "call_codex_image_cli", side_effect=provider):
            result = dashboard.codex_image_generate(payload)
        self.assertTrue(result["ok"], result)
        prompt = prompts[0]
        self.assertIn("Rodeo Premium", prompt)
        self.assertIn("$110.000 COP", prompt)
        self.assertIn("protección y limpieza profunda", prompt)
        self.assertNotIn("Rodeo Express", prompt)
        self.assertNotIn("$45.000 COP", prompt)
        self.assertNotIn("lavado rápido", prompt)

    def test_selected_ad_brief_can_resolve_its_exact_product_without_duplicate_field(self):
        library = {
            "general": {"fields": {"brand_name": "Rodeo"}},
            "products": [{
                "id": "rodeo-premium",
                "name": "Rodeo Premium",
                "guide": "brand_guides/products/rodeo-premium.md",
                "fields": {"name": "Rodeo Premium", "price": "$110.000 COP"},
            }],
            "ad_briefs": [{
                "id": "premium-whatsapp",
                "name": "Premium WhatsApp",
                "guide": "brand_guides/ad_briefs/premium-whatsapp.md",
                "fields": {"product_guide": "rodeo-premium", "objective": "Mensajes de WhatsApp"},
            }],
        }
        context = dashboard._hybrid_semantic_prompt_context({"ad_brief": "premium-whatsapp"}, library)
        self.assertIn("Rodeo Premium", context["active_offer"])
        self.assertIn("$110.000 COP", context["active_offer"])
        self.assertEqual(context["objective"], "Mensajes de WhatsApp")

    def test_real_photo_request_can_use_explicit_no_logo_without_creating_global_brand_memory(self):
        brand_library = {
            "general_exists": True,
            "creative_references_exists": False,
            "general": {"fields": {
                "brand_name": "La Esquina de Palmita",
                "offer": "platos de mariscos",
                "colors": "azules",
                "visual_style": "cálido y moderno",
                "tone": "cercano",
            }},
            "products": [],
        }
        payload = {
            "purpose": "ad_creative",
            "include_logo": False,
            "content_asset_ids": ["photo-before"],
            "real_media": [{"slot_id": "hero", "content_asset_id": "photo-before", "role": "hero"}],
        }
        with patch.object(dashboard, "guide_library", return_value=brand_library), \
             patch.object(dashboard, "load_content_asset_library", return_value=self.library):
            readiness = dashboard.branding_creative_readiness(
                require_product=False,
                payload=payload,
                creative_request=True,
                purpose="ad_creative",
            )
        self.assertTrue(readiness["ready"], readiness)
        self.assertEqual(readiness["missing"], [])
        self.assertEqual(readiness["request_evidence"]["asset_ids"], ["photo-before"])
        self.assertTrue(readiness["request_evidence"]["explicit_no_logo"])
        self.assertTrue(readiness["request_evidence"]["selected_real_asset"])
        self.assertNotIn("logo_status", brand_library["general"]["fields"])

    def test_missing_logo_choice_or_unapproved_photo_remains_a_branding_question(self):
        brand_library = {
            "general_exists": True,
            "creative_references_exists": False,
            "general": {"fields": {
                "brand_name": "La Esquina de Palmita",
                "offer": "platos de mariscos",
                "colors": "azules",
                "visual_style": "cálido y moderno",
                "tone": "cercano",
            }},
            "products": [],
        }
        base = {
            "purpose": "ad_creative",
            "content_asset_ids": ["photo-before"],
            "real_media": [{"slot_id": "hero", "content_asset_id": "photo-before", "role": "hero"}],
        }
        with patch.object(dashboard, "guide_library", return_value=brand_library), \
             patch.object(dashboard, "load_content_asset_library", return_value=self.library):
            missing_logo = dashboard.branding_creative_readiness(
                require_product=False, payload=base, creative_request=True, purpose="ad_creative",
            )
        self.assertIn("logo_decision", [item["key"] for item in missing_logo["missing"]])

        unapproved = {"items": [dict(self.library["items"][0], approved_for_ads=False)]}
        with patch.object(dashboard, "guide_library", return_value=brand_library), \
             patch.object(dashboard, "load_content_asset_library", return_value=unapproved):
            missing_asset = dashboard.branding_creative_readiness(
                require_product=False,
                payload={**base, "include_logo": False},
                creative_request=True,
                purpose="ad_creative",
            )
        keys = [item["key"] for item in missing_asset["missing"]]
        self.assertIn("reference_decision", keys)
        self.assertIn("real_asset_decision", keys)

    def test_real_photo_creative_reaches_provider_after_request_scoped_brand_choice(self):
        calls = []
        brand_library = {
            "general_exists": True,
            "creative_references_exists": False,
            "general": {"fields": {
                "brand_name": "La Esquina de Palmita",
                "offer": "platos de mariscos",
                "colors": "azules",
                "visual_style": "cálido y moderno",
                "tone": "cercano",
            }},
            "products": [{"id": "mariscos", "ready": True, "fields": {"name": "Plato de mariscos"}}],
            "ad_briefs": [],
        }

        def provider(_prompt, **kwargs):
            calls.append(kwargs)
            output = Path(kwargs["output_root"])
            output.mkdir(parents=True, exist_ok=True)
            result = output / "real-photo-overlay.png"
            shutil.copy2(self.overlay, result)
            return {"ok": True, "image_path": str(result), "asset_id": "real-photo-overlay.png"}

        payload = {
            "request": "Diseño promocional para el plato de mariscos",
            "purpose": "ad_creative",
            "product_name": "plato de mariscos",
            "layout_intent": "hero",
            "include_logo": False,
            "content_asset_ids": ["photo-before"],
            "real_media": [{"slot_id": "hero", "content_asset_id": "photo-before", "role": "hero"}],
            "style_reference": {"mode": "none"},
        }
        with patch.object(dashboard, "guide_library", return_value=brand_library), \
             patch.object(dashboard, "load_content_asset_library", return_value=self.library), \
             patch.object(dashboard, "selected_product_guide_for_creative", return_value=("mariscos", "test")), \
             patch.object(dashboard, "creative_direct_context", return_value=""), \
             patch.object(dashboard, "official_brand_logo_path", return_value=None), \
             patch.object(dashboard, "call_codex_image_cli", side_effect=provider):
            result = dashboard.codex_image_generate(payload)
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(calls), 1)
        self.assertTrue(Path(result["image_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
