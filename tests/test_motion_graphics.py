from __future__ import annotations

import hashlib
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import motion_graphics as motion
import codex_brand_guides as brand
import hermes_bridge
from motion_recipe_compiler import MotionRecipeCompileError, validate_recipe_component_source
from shotcraft_catalog import (
    EXPECTED_CARD_COUNT,
    EXPECTED_STYLE_COUNT,
    SHOTCRAFT_ROOT,
    load_shotcraft_catalog,
    resolve_shotcraft_recipe,
    search_shotcraft_recipes,
)
from admira_mcp_server import TOOL_DEFINITIONS, TOOL_INPUT_SCHEMAS
from admira_tool_bridge import generated_media_attachment_for_result


BRAND = {
    "brand_name": "Serena Studio",
    "colors": "#173F35, #D5B47A, #F7F1E8",
    "visual_style": "editorial premium, natural y limpio",
    "typography": "sans serif moderna",
    "tone": "claro, tranquilo y experto",
    "logo_usage": "auto",
}
PRODUCT = {
    "name": "Ritual Serena",
    "audience": "mujeres profesionales que cuidan su piel",
    "pain": "rutinas confusas",
    "desire": "una rutina simple y constante",
    "visual_colors": "#6B3346, #F3D8DE",
    "visual_style": "editorial cálido y delicado",
    "motion_style": "movimiento suave y preciso",
    "motion_pacing": "calmado",
}


def payload(**overrides):
    value = {
        "topic": "Tres hábitos para cuidar tu piel",
        "objective": "educational",
        "aspect_ratio": "9:16",
        "quality": "preview",
        "key_points": ["Limpia con suavidad", "Hidrata", "Protege del sol"],
        "cta": "Guarda esta guía",
    }
    value.update(overrides)
    return value


class MotionGraphicContractTests(unittest.TestCase):
    def setUp(self):
        self.resolve = mock.patch.object(motion, "_resolve_brand_and_product", return_value=(BRAND, PRODUCT, ROOT / "brand_guides/products/ritual-serena.md"))
        self.logo = mock.patch.object(motion, "official_brand_logo_path", return_value=None)
        self.resolve.start()
        self.logo.start()

    def tearDown(self):
        self.logo.stop()
        self.resolve.stop()

    def test_all_objective_and_aspect_ratio_pairs_build(self):
        for objective in sorted(motion.OBJECTIVES):
            for aspect_ratio, dimensions in motion.FORMAT_DIMENSIONS.items():
                with self.subTest(objective=objective, aspect_ratio=aspect_ratio):
                    prepared = motion.build_motion_graphic_spec(payload(objective=objective, aspect_ratio=aspect_ratio))
                    spec = prepared["spec"]
                    self.assertEqual(spec["objective"], objective)
                    self.assertEqual((spec["width"], spec["height"]), dimensions)
                    self.assertEqual(spec["product"]["name"], PRODUCT["name"])
                    self.assertEqual(spec["brand"]["palette"]["primary"], "#6B3346")
                    shutil.rmtree(prepared["job_dir"], ignore_errors=True)

    def test_palette_uses_wcag_safe_copy_colors_for_dark_and_light_brands(self):
        for source in (
            "#211B1B #D3A26A #F5E9DF",  # premium dark spa palette
            "#081B33 #2CC6B9 #EAF7F6",  # dark technical palette
            "#F8EFD9 #D1613A #27231F",  # predominantly light palette
        ):
            with self.subTest(source=source):
                palette = motion.parse_palette(source)
                self.assertGreaterEqual(motion.contrast_ratio(palette["text"], palette["background"]), 4.5)
                self.assertGreaterEqual(motion.contrast_ratio(palette["mutedText"], palette["background"]), 5.45)
                self.assertGreaterEqual(motion.contrast_ratio(palette["surfaceText"], palette["surface"]), 4.5)
                self.assertGreaterEqual(motion.contrast_ratio(palette["surfaceMutedText"], palette["surface"]), 5.45)
                self.assertGreaterEqual(motion.contrast_ratio(palette["primaryText"], palette["primary"]), 4.5)
                self.assertGreaterEqual(motion.contrast_ratio(palette["highlightText"], palette["highlight"]), 4.5)

    def test_low_contrast_brand_highlight_falls_back_for_copy(self):
        palette = motion.parse_palette("#211B1B #D3A26A #6E583E")
        self.assertGreaterEqual(motion.contrast_ratio(palette["emphasisText"], palette["background"]), 4.5)

    def test_green_screen_storyboard_element_becomes_transparent_png(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable")
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "element.png"
            image = Image.new("RGB", (24, 24), (0, 255, 0))
            for x in range(7, 17):
                for y in range(6, 18):
                    image.putpixel((x, y), (224, 48, 72))
            image.save(source)
            result = brand.remove_green_screen_background(source)
            self.assertTrue(result["applied"])
            transparent = Image.open(result["image_path"]).convert("RGBA")
            self.assertEqual(transparent.getpixel((0, 0))[3], 0)
            self.assertEqual(transparent.getpixel((12, 12))[3], 255)

    def test_motion_asset_prompt_is_not_routed_as_finished_ad(self):
        package = brand.build_codex_image_prompt_package(
            request="Crear una medusa 3D completa para colocar en primer plano",
            purpose="motion_graphic_asset",
            variations=1,
        )
        prompt = package["prompts"][0]["image_prompt"].lower()
        self.assertIn("storyboard", prompt)
        self.assertNotIn("debe verse como anuncio profesional", prompt)

        generation_prompt = brand.codex_image_generation_prompt(
            "Crear una forma orgánica dorada para primer plano",
            purpose="motion_graphic_asset",
        ).lower()
        self.assertIn("storyboard de motion graphics", generation_prompt)
        self.assertIn("no un anuncio terminado", generation_prompt)

    def test_image_tool_exposes_reusable_motion_asset_contract(self):
        schema = TOOL_INPUT_SCHEMAS["codex_image_generate"]
        properties = schema["properties"]
        self.assertTrue(
            {"background_removal", "asset_role", "narrative_role", "scene_intent", "reusable_asset", "reusable_category", "product_scope"}.issubset(properties)
        )
        self.assertIn("story_element", properties["reusable_category"]["enum"])

    def test_every_scene_recipe_is_normalized_and_bounded(self):
        scenes = [
            {"type": "hook", "title": "Hook"},
            {"type": "statement", "title": "Statement"},
            {"type": "list", "title": "List", "items": ["A", "B"]},
            {"type": "steps", "title": "Steps", "items": ["A", "B"]},
            {"type": "stat", "title": "Stat", "stat": "73%"},
            {"type": "comparison", "title": "Compare", "left": "Antes", "right": "Después"},
            {"type": "quote", "quote": "Cita verificada", "attribution": "Cliente"},
            {"type": "media", "title": "Media"},
            {"type": "cta", "title": "CTA"},
        ]
        prepared = motion.build_motion_graphic_spec(payload(scenes=scenes))
        recipes = {scene["motion"] for scene in prepared["spec"]["scenes"]}
        self.assertEqual(recipes, motion.LEGACY_MOTION_RECIPES)
        self.assertTrue(all(1.5 <= scene["duration_seconds"] <= 15 for scene in prepared["spec"]["scenes"]))
        shutil.rmtree(prepared["job_dir"], ignore_errors=True)

    def test_scene_combines_one_dominant_accents_and_transition(self):
        prepared = motion.build_motion_graphic_spec(
            payload(
                scenes=[
                    {
                        "type": "media",
                        "title": "Recorrido",
                        "shot_recipes": [
                            "page-cam-2.5d",
                            "scanline-annotate-focus",
                            "spotlight-sweep",
                            "flash-cut",
                        ],
                    }
                ]
            )
        )
        try:
            scene = prepared["spec"]["scenes"][0]
            # No image was supplied, so the media-dependent dominant layer is
            # safely replaced while compatible accent/transition layers remain.
            self.assertEqual(scene["shot_recipe"], "paper-title-card")
            self.assertEqual(
                scene["shot_recipes"],
                ["paper-title-card", "scanline-annotate-focus", "spotlight-sweep", "flash-cut"],
            )
            self.assertEqual(scene["transition"], "flash-cut")
        finally:
            shutil.rmtree(prepared["job_dir"], ignore_errors=True)

    def test_incompatible_full_screen_recipes_are_not_stacked(self):
        prepared = motion.build_motion_graphic_spec(
            payload(
                scenes=[
                    {
                        "type": "hook",
                        "title": "Una idea",
                        "shot_recipes": ["brand-ink-open", "card-stack", "brand-frame-snap", "whip-pan"],
                    }
                ]
            )
        )
        try:
            self.assertEqual(
                prepared["spec"]["scenes"][0]["shot_recipes"],
                ["brand-ink-open", "brand-frame-snap", "whip-pan"],
            )
        finally:
            shutil.rmtree(prepared["job_dir"], ignore_errors=True)

    def test_ink_press_builds_coordinated_recipe_storyboard(self):
        prepared = motion.build_motion_graphic_spec(payload(template="ink-press"))
        try:
            spec = prepared["spec"]
            self.assertEqual(spec["template"], "ink-press")
            self.assertGreaterEqual(len(spec["scenes"]), 5)
            self.assertEqual(spec["scenes"][0]["shot_recipe"], "brand-ink-open")
            self.assertIn("marker-underline-title", spec["scenes"][1]["shot_recipes"])
            self.assertEqual(spec["scenes"][-1]["shot_recipe"], "cta-ink-lockup")
        finally:
            shutil.rmtree(prepared["job_dir"], ignore_errors=True)

    def test_every_declared_shot_recipe_has_a_bounded_layer(self):
        self.assertGreaterEqual(len(motion.SHOT_RECIPE_CATALOG), 24)
        for name, metadata in motion.SHOT_RECIPE_CATALOG.items():
            with self.subTest(name=name):
                self.assertIn(metadata["layer"], {"base", "camera", "typography", "accent", "transition"})
                self.assertIsInstance(metadata["requires_media"], bool)

    def test_complete_shotcraft_catalog_is_available(self):
        catalog = load_shotcraft_catalog()
        self.assertEqual(catalog["card_count"], EXPECTED_CARD_COUNT)
        self.assertEqual(catalog["style_count"], EXPECTED_STYLE_COUNT)
        self.assertEqual(len(catalog["by_card"]), 152)
        self.assertEqual(len(catalog["by_style"]), 209)
        for card in catalog["cards"]:
            with self.subTest(card=card["name"]):
                self.assertTrue((SHOTCRAFT_ROOT / card["source"]).is_file())
                self.assertTrue(card["styles"])
                for style in card["styles"]:
                    self.assertTrue(style["demo_source"])
                    self.assertTrue((SHOTCRAFT_ROOT / style["demo_source"]).is_file())

    def test_card_and_style_names_resolve_to_same_recipe(self):
        card = resolve_shotcraft_recipe("beat-cut-moves", "paparazzi-flash")
        style = resolve_shotcraft_recipe("paparazzi-flash")
        self.assertEqual(card["card"], "beat-cut-moves")
        self.assertEqual(card["style"], "paparazzi-flash")
        self.assertEqual(style, card)

    def test_every_style_has_storytelling_vocabulary(self):
        vocabulary_path = (
            ROOT
            / "agent"
            / "skills"
            / "motion-graphics-video"
            / "references"
            / "shotcraft-storytelling-vocabulary.json"
        )
        vocabulary = json.loads(vocabulary_path.read_text(encoding="utf-8"))
        catalog = load_shotcraft_catalog()
        self.assertEqual(vocabulary["catalog_revision"], catalog["revision"])
        self.assertEqual(vocabulary["card_count"], 152)
        self.assertEqual(vocabulary["style_count"], 209)
        self.assertEqual(len(vocabulary["styles"]), 209)
        for item in vocabulary["styles"]:
            with self.subTest(style=item["style"]):
                self.assertIn(item["energy"], {"low", "medium", "high", "very_high"})
                self.assertIn(item["tempo"], {"slow", "measured", "fast", "burst"})
                self.assertIn(item["impact"], {"gentle", "balanced", "assertive", "aggressive"})
                self.assertTrue(item["narrative_roles"])
                self.assertTrue(item["message_fit"])
                self.assertTrue(item["combine_with"])

    def test_recipe_search_uses_narrative_filters_across_full_catalog(self):
        calm = search_shotcraft_recipes(
            {"query": "calm educational trust", "tempo": "slow", "tone_fit": "trust", "limit": 7}
        )
        self.assertTrue(calm["ok"])
        self.assertEqual(calm["style_count"], 209)
        self.assertTrue(calm["matches"])
        self.assertTrue(all(item["tempo"] == "slow" for item in calm["matches"]))
        self.assertTrue(all("trust" in item["tone_fit"] for item in calm["matches"]))

        launch = search_shotcraft_recipes(
            {"query": "bold launch crescendo", "energy": "high", "message_fit": "launch", "limit": 7}
        )
        self.assertTrue(launch["matches"])
        self.assertTrue(all(item["energy"] == "high" for item in launch["matches"]))
        self.assertTrue(all("launch" in item["message_fit"] for item in launch["matches"]))
        self.assertTrue(any("crescendo" in item["narrative_roles"] for item in launch["matches"]))

    def test_full_catalog_recipe_requires_a_validated_adaptation(self):
        with self.assertRaisesRegex(motion.MotionGraphicError, "compiled_recipe_source"):
            motion.build_motion_graphic_spec(
                payload(scenes=[{"type": "hook", "title": "Producto", "shot_recipes": ["text-as-mask"]}])
            )

    def test_full_catalog_combination_builds_job_scoped_entrypoint(self):
        source = (
            'const p = interpolate(frame, [0, 20], [0, 1]); '
            'return (<AbsoluteFill style={{background: palette.background, justifyContent: "center", alignItems: "center"}}>'
            '<div style={{opacity: p, color: palette.text, fontSize: width * 0.1}}>{scene.title}</div>'
            '</AbsoluteFill>);'
        )
        prepared = motion.build_motion_graphic_spec(
            payload(
                scenes=[
                    {
                        "type": "hook",
                        "title": "Producto",
                        "shot_recipes": ["text-as-mask", "spotlight-sweep", "flash-cut"],
                        "compiled_recipe_source": source,
                    }
                ]
            )
        )
        try:
            spec = prepared["spec"]
            self.assertEqual(spec["shotcraft_catalog"]["card_count"], 152)
            self.assertEqual(spec["shotcraft_catalog"]["style_count"], 209)
            self.assertEqual(spec["scenes"][0]["shot_recipes"], ["text-as-mask", "spotlight-sweep", "flash-cut"])
            self.assertEqual([item["category"] for item in spec["scenes"][0]["shot_recipe_refs"]], ["opening", "effects", "transition"])
            entrypoint = prepared["job_dir"] / spec["generated_entrypoint"]
            self.assertTrue(entrypoint.is_file())
            self.assertNotIn(str(entrypoint), (ROOT / "src").as_posix())
            self.assertTrue(spec["compiled_recipe_hash"])
        finally:
            shutil.rmtree(prepared["job_dir"], ignore_errors=True)

    def test_unsafe_compiled_recipe_source_is_rejected(self):
        unsafe = 'const value = fetch("https://example.com"); return (<div>{value}</div>);'
        with self.assertRaises(MotionRecipeCompileError):
            validate_recipe_component_source(unsafe)
        with self.assertRaises(MotionRecipeCompileError):
            validate_recipe_component_source('while (true) {} return (<div />);')
        with self.assertRaises(MotionRecipeCompileError):
            validate_recipe_component_source(
                'const particles = Array.from({length: 999999999}); return (<div>{particles.length}</div>);'
            )

    def test_hermes_workspace_receives_nested_catalog_and_exact_demo(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            hermes_bridge, "HERMES_WORKSPACE_DIR", Path(temporary)
        ):
            hermes_bridge.write_product_skill_workspace_files()
            workspace = Path(temporary) / "skills" / "motion-graphics-video" / "references" / "shotcraft"
            library = workspace / "gallery" / "api" / "library.json"
            demo = workspace / "demos" / "opening" / "text-as-mask" / "TextAsMask.tsx"
            vocabulary = (
                Path(temporary)
                / "skills"
                / "motion-graphics-video"
                / "references"
                / "shotcraft-storytelling-vocabulary.json"
            )
            self.assertTrue(library.is_file())
            self.assertTrue(demo.is_file())
            self.assertTrue(vocabulary.is_file())
            copied = json.loads(library.read_text(encoding="utf-8"))
            self.assertEqual(copied["stats"]["cardCount"], 152)
            self.assertEqual(copied["stats"]["styleCount"], 209)
            copied_vocabulary = json.loads(vocabulary.read_text(encoding="utf-8"))
            self.assertEqual(len(copied_vocabulary["styles"]), 209)

    def test_unknown_recipe_falls_back_to_curated_recipe(self):
        prepared = motion.build_motion_graphic_spec(payload(scenes=[{"type": "stat", "stat": "10", "motion": "run arbitrary js"}]))
        self.assertEqual(prepared["spec"]["scenes"][0]["motion"], "stat-focus")
        shutil.rmtree(prepared["job_dir"], ignore_errors=True)

    def test_hidden_macos_metadata_is_not_treated_as_a_product(self):
        with tempfile.TemporaryDirectory() as temporary:
            product_dir = Path(temporary)
            template = product_dir / "product.example.md"
            metadata = product_dir / "._product.example.md"
            template.write_text("# Template\n", encoding="utf-8")
            metadata.write_bytes(b"\x00\xa3macOS metadata")
            with mock.patch.object(brand, "PRODUCT_DIR", product_dir), mock.patch.object(
                brand, "PRODUCT_EXAMPLE", template
            ), mock.patch.object(motion, "PRODUCT_DIR", product_dir):
                self.assertEqual(brand.product_guide_paths(), [])
                self.assertEqual(brand.read_text(metadata, ""), "")

    def test_child_offer_motion_pacing_changes_real_render_tokens(self):
        calm = motion.motion_profile("calmado", "editorial suave")
        energetic = motion.motion_profile("muy energético", "cyber bold")
        self.assertEqual(calm["preset"], "calm")
        self.assertEqual(energetic["preset"], "energetic")
        self.assertGreater(calm["entry_seconds"], energetic["entry_seconds"])
        prepared = motion.build_motion_graphic_spec(payload())
        try:
            self.assertEqual(prepared["spec"]["brand"]["motion_profile"]["preset"], "calm")
            self.assertEqual(prepared["spec"]["brand"]["motion_style"], PRODUCT["motion_style"])
        finally:
            shutil.rmtree(prepared["job_dir"], ignore_errors=True)

    def test_dense_storyboard_is_limited_to_twelve_scenes(self):
        prepared = motion.build_motion_graphic_spec(payload(scenes=[{"title": f"Scene {i}", "seconds": 1.5} for i in range(30)]))
        self.assertEqual(len(prepared["spec"]["scenes"]), 12)
        shutil.rmtree(prepared["job_dir"], ignore_errors=True)

    def test_duration_outside_contract_is_blocked(self):
        with self.assertRaises(motion.MotionGraphicError):
            motion.build_motion_graphic_spec(payload(scenes=[{"title": "Too long", "seconds": 15} for _ in range(7)]))

    def test_invalid_audio_volume_is_safely_defaulted(self):
        prepared = motion.build_motion_graphic_spec(payload(audio_volume="not-a-number"))
        self.assertEqual(prepared["spec"]["audio"]["volume"], 0.0)
        shutil.rmtree(prepared["job_dir"], ignore_errors=True)

    def test_real_asset_is_copied_byte_for_byte(self):
        fixture_dir = motion.OUTPUT_ROOT / "test-fixtures"
        fixture_dir.mkdir(parents=True, exist_ok=True)
        fixture = fixture_dir / "real-photo.png"
        fixture.write_bytes(b"\x89PNG\r\n\x1a\n" + b"pixel-locked-test" * 20)
        before = hashlib.sha256(fixture.read_bytes()).hexdigest()
        prepared = motion.build_motion_graphic_spec(payload(asset_paths=[str(fixture)], scenes=[{"type": "media", "title": "Real photo", "media_path": str(fixture)}]))
        copied = prepared["public_dir"] / prepared["spec"]["scenes"][0]["media_src"]
        self.assertEqual(hashlib.sha256(copied.read_bytes()).hexdigest(), before)
        self.assertEqual(prepared["spec"]["assets"][0]["preservation"], "pixel_locked")
        shutil.rmtree(prepared["job_dir"], ignore_errors=True)
        shutil.rmtree(fixture_dir, ignore_errors=True)

    def test_scene_only_asset_is_recorded_in_preservation_manifest(self):
        fixture_dir = motion.OUTPUT_ROOT / "test-scene-fixtures"
        fixture_dir.mkdir(parents=True, exist_ok=True)
        fixture = fixture_dir / "scene-only.png"
        fixture.write_bytes(b"\x89PNG\r\n\x1a\n" + b"scene-only-pixel-lock" * 20)
        prepared = motion.build_motion_graphic_spec(
            payload(scenes=[{"type": "media", "title": "Producto", "media_path": str(fixture)}])
        )
        try:
            self.assertEqual(len(prepared["spec"]["assets"]), 1)
            self.assertEqual(prepared["spec"]["assets"][0]["src"], prepared["spec"]["scenes"][0]["media_src"])
            self.assertEqual(prepared["spec"]["assets"][0]["preservation"], "pixel_locked")
        finally:
            shutil.rmtree(prepared["job_dir"], ignore_errors=True)
            shutil.rmtree(fixture_dir, ignore_errors=True)

    def test_scene_can_layer_six_generated_or_approved_assets(self):
        fixture_dir = motion.OUTPUT_ROOT / "test-layer-fixtures"
        fixture_dir.mkdir(parents=True, exist_ok=True)
        layers = []
        for index in range(7):
            path = fixture_dir / f"layer-{index}.png"
            path.write_bytes(b"\x89PNG\r\n\x1a\n" + f"layer-{index}".encode() * 24)
            layers.append(str(path))
        source = (
            'return (<AbsoluteFill>'
            '<ProtectedMedia assetIndex={0} fit="contain" style={{position: "absolute", left: 0, width: "50%"}} />'
            '<ProtectedMedia assetIndex={1} fit="contain" style={{position: "absolute", right: 0, width: "50%"}} />'
            '</AbsoluteFill>);'
        )
        prepared = motion.build_motion_graphic_spec(
            payload(
                scenes=[{
                    "type": "media",
                    "title": "Composición por capas",
                    "layer_asset_paths": layers,
                    "shot_recipes": ["text-as-mask"],
                    "compiled_recipe_source": source,
                }]
            )
        )
        try:
            scene = prepared["spec"]["scenes"][0]
            self.assertEqual(len(scene["layer_media"]), 6)
            self.assertEqual(len(prepared["spec"]["assets"]), 6)
            entrypoint = (prepared["job_dir"] / prepared["spec"]["generated_entrypoint"]).read_text(encoding="utf-8")
            self.assertIn("assetIndex?: number", entrypoint)
            self.assertIn("scene.layer_media?.[assetIndex!]", entrypoint)
        finally:
            shutil.rmtree(prepared["job_dir"], ignore_errors=True)
            shutil.rmtree(fixture_dir, ignore_errors=True)

    def test_external_file_is_not_accepted_as_media(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as outside:
            self.assertIsNone(motion.safe_motion_media_path(outside.name))

    def test_missing_branding_returns_buyer_correctable_block(self):
        with mock.patch.object(motion, "_resolve_brand_and_product", return_value=({}, {}, None)):
            result = motion.generate_motion_graphic_video(payload())
        self.assertTrue(result["blocked"])
        self.assertEqual(result["reason"], "motion_graphic_request_incomplete")
        self.assertIn("branding", result["error"].lower())

    def test_mcp_contract_and_video_attachment(self):
        names = {name for name, _ in TOOL_DEFINITIONS}
        self.assertIn("generate_motion_graphic_video", names)
        self.assertIn("search_motion_graphic_recipes", names)
        schema = TOOL_INPUT_SCHEMAS["generate_motion_graphic_video"]
        self.assertIn("scenes", schema["properties"])
        self.assertIn("template", schema["properties"])
        self.assertIn("shot_recipes", schema["properties"]["scenes"]["items"]["properties"])
        self.assertIn("compiled_recipe_source", schema["properties"]["scenes"]["items"]["properties"])
        self.assertIn("layer_asset_paths", schema["properties"]["scenes"]["items"]["properties"])
        organic_settings = TOOL_INPUT_SCHEMAS["save_daily_social_content_settings"]
        self.assertIn("content_formats", organic_settings["properties"])
        self.assertIn("video_frequency_days", organic_settings["properties"])
        organic_draft = TOOL_INPUT_SCHEMAS["stage_organic_social_post"]
        self.assertIn("video_path", organic_draft["properties"])
        self.assertTrue(any(item.get("required") == ["video_path"] for item in organic_draft["anyOf"]))
        search_schema = TOOL_INPUT_SCHEMAS["search_motion_graphic_recipes"]
        self.assertEqual(search_schema["properties"]["energy"]["enum"], ["low", "medium", "high", "very_high"])
        video = motion.OUTPUT_ROOT / "attachment-test.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"0" * 2048)
        try:
            result = {"ok": True, "result": {"video_path": str(video)}}
            attachment = generated_media_attachment_for_result("admira_generate_motion_graphic_video", result)
            self.assertEqual(attachment, f"MEDIA:{video.resolve()}")
        finally:
            video.unlink(missing_ok=True)

    def test_all_remotion_packages_are_pinned_together(self):
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        versions = {value for key, value in package["dependencies"].items() if key == "remotion" or key.startswith("@remotion/")}
        self.assertEqual(versions, {"4.0.507"})
        self.assertEqual(package["overrides"]["fast-uri"], "3.1.5")
        self.assertEqual(package["overrides"]["nanoid"], "3.3.18")
        self.assertEqual(package["overrides"]["postcss"], "8.5.26")

    def test_docker_includes_official_remotion_chrome_runtime(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        for dependency in ("libnss3", "libdbus-1-3", "libatk1.0-0", "libgbm-dev", "libasound2", "libxrandr2", "libxkbcommon-dev", "libxfixes3", "libxcomposite1", "libxdamage1", "libatk-bridge2.0-0", "libpango-1.0-0", "libcairo2", "libcups2"):
            self.assertIn(dependency, dockerfile)
        renderer = (ROOT / "scripts" / "render-motion-graphic.mjs").read_text(encoding="utf-8")
        self.assertIn("enableMultiProcessOnLinux", renderer)


@unittest.skipUnless(os.getenv("ADMIRA_RUN_MOTION_RENDER_TESTS") == "1", "Set ADMIRA_RUN_MOTION_RENDER_TESTS=1 for real Remotion renders")
class MotionGraphicRenderTests(unittest.TestCase):
    def test_real_render_with_two_independent_storyboard_layers(self):
        if not (ROOT / "node_modules" / "@remotion" / "renderer").exists():
            self.skipTest("npm dependencies not installed")
        fixture_dir = motion.OUTPUT_ROOT / "render-layer-fixtures"
        fixture_dir.mkdir(parents=True, exist_ok=True)
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAF/gL+XigzWQAAAABJRU5ErkJggg==")
        first = fixture_dir / "shape-a.png"
        second = fixture_dir / "shape-b.png"
        first.write_bytes(png)
        second.write_bytes(png)
        source = (
            'const p = spring({frame, fps, config: {damping: 18, stiffness: 120}}); '
            'return (<AbsoluteFill style={{background: palette.background}}>'
            '<ProtectedMedia assetIndex={0} fit="contain" style={{position: "absolute", left: "8%", top: "12%", width: "38%", height: "76%", opacity: p}} />'
            '<ProtectedMedia assetIndex={1} fit="contain" style={{position: "absolute", right: "8%", top: "12%", width: "38%", height: "76%", opacity: p}} />'
            '</AbsoluteFill>);'
        )
        try:
            with mock.patch.object(
                motion,
                "_resolve_brand_and_product",
                return_value=(BRAND, PRODUCT, ROOT / "brand_guides/products/ritual-serena.md"),
            ), mock.patch.object(motion, "official_brand_logo_path", return_value=None):
                result = motion.generate_motion_graphic_video(
                    payload(
                        aspect_ratio="1:1",
                        scenes=[{
                            "type": "media",
                            "title": "Capas independientes",
                            "duration_seconds": 3,
                            "layer_asset_paths": [str(first), str(second)],
                            "shot_recipes": ["text-as-mask"],
                            "compiled_recipe_source": source,
                        }],
                    )
                )
            self.assertTrue(result.get("ok"), result)
            spec = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(len(spec["scenes"][0]["layer_media"]), 2)
            self.assertTrue(Path(result["video_path"]).is_file())
        finally:
            shutil.rmtree(fixture_dir, ignore_errors=True)

    def test_real_full_catalog_combination_with_camera_motion_blur(self):
        if not (ROOT / "node_modules" / "@remotion" / "renderer").exists():
            self.skipTest("npm dependencies not installed")
        source = (
            'const p = spring({frame, fps, config: {damping: 18, stiffness: 130}}); '
            'const scale = interpolate(p, [0, 1], [0.82, 1]); '
            'return (<CameraMotionBlur shutterAngle={120} samples={4}>'
            '<AbsoluteFill style={{background: palette.background, justifyContent: "center", alignItems: "center"}}>'
            '<div style={{transform: `scale(${scale})`, color: palette.text, fontSize: width * 0.105, '
            'fontWeight: 850, textAlign: "center", maxWidth: "82%"}}>{scene.title}</div>'
            '</AbsoluteFill></CameraMotionBlur>);'
        )
        with mock.patch.object(
            motion,
            "_resolve_brand_and_product",
            return_value=(BRAND, PRODUCT, ROOT / "brand_guides/products/ritual-serena.md"),
        ), mock.patch.object(motion, "official_brand_logo_path", return_value=None):
            result = motion.generate_motion_graphic_video(
                payload(
                    aspect_ratio="1:1",
                    scenes=[
                        {
                            "type": "hook",
                            "title": "Una rutina que sí puedes sostener",
                            "seconds": 3,
                            "shot_recipes": ["text-as-mask", "spotlight-sweep", "flash-cut"],
                            "compiled_recipe_source": source,
                        }
                    ],
                )
            )
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(Path(result["video_path"]).is_file())
        spec = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(spec["scenes"][0]["shot_recipes"], ["text-as-mask", "spotlight-sweep", "flash-cut"])
        self.assertTrue(spec["generated_entrypoint"].endswith(".tsx"))
        self.assertTrue(spec["compiled_recipe_hash"])

    def test_real_render_matrix(self):
        if not (ROOT / "node_modules" / "@remotion" / "renderer").exists():
            self.skipTest("npm dependencies not installed")
        with mock.patch.object(motion, "_resolve_brand_and_product", return_value=(BRAND, PRODUCT, ROOT / "brand_guides/products/ritual-serena.md")), mock.patch.object(motion, "official_brand_logo_path", return_value=None):
            for aspect_ratio in motion.FORMAT_DIMENSIONS:
                with self.subTest(aspect_ratio=aspect_ratio):
                    result = motion.generate_motion_graphic_video(
                        payload(
                            aspect_ratio=aspect_ratio,
                            scenes=[
                                {"type": "hook", "title": "Cuida tu piel", "seconds": 1.5},
                                {"type": "cta", "title": "Guarda esta guía", "seconds": 1.5},
                            ],
                        )
                    )
                    self.assertTrue(result.get("ok"), result)
                    self.assertTrue(Path(result["video_path"]).is_file())
                    self.assertTrue(Path(result["poster_path"]).is_file())
                    stream = (result.get("probe", {}).get("streams") or [{}])[0]
                    width, height = motion.FORMAT_DIMENSIONS[aspect_ratio]
                    self.assertEqual((stream.get("width"), stream.get("height")), (motion.even_render_dimension(width * 0.5), motion.even_render_dimension(height * 0.5)))

    def test_real_image_and_video_media_render(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        fixture_dir = motion.OUTPUT_ROOT / "render-media-fixtures"
        fixture_dir.mkdir(parents=True, exist_ok=True)
        image = fixture_dir / "buyer-product.png"
        video = fixture_dir / "buyer-footage.mp4"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=#6B3346:s=640x640:d=1", "-frames:v", "1", "-y", str(image)],
            check=True,
        )
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=640x640:r=30:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(video)],
            check=True,
        )
        try:
            with mock.patch.object(motion, "_resolve_brand_and_product", return_value=(BRAND, PRODUCT, ROOT / "brand_guides/products/ritual-serena.md")), mock.patch.object(motion, "official_brand_logo_path", return_value=None):
                result = motion.generate_motion_graphic_video(
                    payload(
                        aspect_ratio="1:1",
                        asset_paths=[str(image), str(video)],
                        scenes=[
                            {"type": "media", "title": "Producto real", "media_path": str(image), "media_fit": "contain", "seconds": 2},
                            {"type": "media", "title": "Video real", "media_path": str(video), "media_fit": "cover", "seconds": 2},
                        ],
                    )
                )
            self.assertTrue(result.get("ok"), result)
            spec = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual([scene["media_kind"] for scene in spec["scenes"]], ["image", "video"])
            self.assertTrue(all(item["preservation"] == "pixel_locked" for item in spec["assets"]))
        finally:
            shutil.rmtree(fixture_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
