import hashlib
import tempfile
import unittest
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - product image runtime supplies Pillow
    Image = None

if Image is not None:
    from hybrid_image_compositor import (
        build_overlay_prompt,
        choose_key_colors,
        compose_overlay,
        composite_logo,
        HybridMaskMissingError,
        prepare_logo,
    )


@unittest.skipIf(Image is None, "Pillow is required by the image runtime")
class HybridImageCompositorTests(unittest.TestCase):
    def test_missing_mask_uses_stable_typed_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            overlay = root / "overlay.png"
            source = root / "source.png"
            Image.new("RGB", (20, 20), "white").save(overlay)
            Image.new("RGB", (10, 10), "red").save(source)
            with self.assertRaises(HybridMaskMissingError) as caught:
                compose_overlay(overlay, [{"slot_id": "hero", "source": source, "key_rgb": (255, 0, 255)}], root / "out.png")
            self.assertEqual(caught.exception.code, "composition_mask_missing")

    def test_key_selection_excludes_green_brand_and_supports_six(self):
        keys = choose_key_colors(6, [(20, 180, 40), (255, 255, 255), (20, 20, 20)])
        self.assertEqual(len(keys), 6)
        brand_hue = __import__("colorsys").rgb_to_hsv(20 / 255, 180 / 255, 40 / 255)[0]
        for key in keys:
            hue = __import__("colorsys").rgb_to_hsv(*(v / 255 for v in key))[0]
            distance = min(abs(hue - brand_hue), 1 - abs(hue - brand_hue)) * 360
            self.assertGreaterEqual(distance, 58)

    def _prompt(self, mode="none"):
        return build_overlay_prompt(
            layout="before_after",
            slots=[
                {"slot_id": "before", "label": "ANTES", "key_rgb": (255, 0, 255)},
                {"slot_id": "after", "label": "DESPUÉS", "key_rgb": (0, 255, 255)},
            ],
            visual_direction="editorial asymmetric composition",
            text_content={"headline": "Detailing Premium"},
            style_reference_mode=mode,
        )
    def test_prompt_has_exact_slots_and_reference_is_opt_in(self):
        prompt = self._prompt()
        self.assertIn("slot_id=before", prompt)
        self.assertIn("#FF00FF", prompt)
        self.assertIn("Do not use any saved style reference", prompt)
        self.assertIn("Never draw, recreate, infer, stylize, retouch, or reconstruct the real subject", prompt)
        self.assertIn("pixel-locked", prompt)
        self.assertIn("FINAL OUTPUT CHECK", prompt)
        self.assertIn("never render a substitute subject", prompt)
        self.assertIn("Detailing Premium", prompt)
        self.assertIn("Do not place any text, letters, numbers, labels", prompt)
        self.assertIn("fully outside the slot", prompt)

    def test_prompt_reserves_named_logo_zone_without_asking_image2_to_draw_it(self):
        prompt = build_overlay_prompt(
            layout="hero",
            slots=[{"slot_id": "hero", "label": "Servicio", "key_rgb": (255, 0, 255)}],
            visual_direction="Diseño premium",
            logo_safe_zone="top_right",
        )
        self.assertIn("official-logo safe zone in the top-right corner", prompt)
        self.assertIn("place the exact official transparent logo programmatically", prompt)
        self.assertIn("Do not draw a logo", prompt)

    def test_prompt_reference_modes_are_explicit(self):
        self.assertIn("all attached persistent brand design references", self._prompt("pool"))
        self.assertIn("first attached design reference is explicit inspiration for this task only", self._prompt("explicit"))
        self.assertIn("confirmed brand rules and exact current-offer facts always have priority", self._prompt("explicit"))
        self.assertIn("all attached persistent brand design references", self._prompt("brand"))
        with self.assertRaises(ValueError):
            self._prompt("sometimes")

    def test_sparse_request_receives_brand_offer_and_safe_copy_refinement(self):
        prompt = build_overlay_prompt(
            layout="hero",
            slots=[{"slot_id": "hero", "label": "SERVICIO PREMIUM", "key_rgb": (255, 0, 255)}],
            visual_direction="Haz algo atractivo con esta foto.",
            active_offer="Rodeo Premium; Precio confirmado: 110.000 COP; Incluye: limpieza profunda",
            objective="Conseguir conversaciones calificadas por WhatsApp",
            audience="Propietarios de vehículos en Bogotá norte",
            format_hint="4:5",
            brand_palette=["negro mate", "gris grafito", "naranja cobrizo"],
            brand_context={
                "brand_name": "Rodeo - Car Detailing",
                "visual_style": "automotriz premium, limpio y moderno",
                "typography": "sans serif condensada y contundente",
                "avoid_always": "caballos o estética western literal",
            },
        )
        self.assertIn("Treat a short buyer request as intent to refine", prompt)
        self.assertIn("Haz algo atractivo con esta foto", prompt)
        self.assertIn("Output format/aspect ratio: 4:5", prompt)
        self.assertIn("Rodeo Premium", prompt)
        self.assertIn("Rodeo - Car Detailing", prompt)
        self.assertIn("naranja cobrizo", prompt)
        self.assertIn("single media window as the visual hero", prompt)
        self.assertIn("Never invent a price, discount, guarantee", prompt)
        self.assertIn("Choose a fresh visual solution", prompt)

    def test_each_layout_family_keeps_dynamic_not_fixed_guidance(self):
        cases = {
            "hero": (1, "full-bleed, offset, framed, arched"),
            "before_after": (2, "equal split, diagonal comparison"),
            "services": (2, "dynamic card system, editorial split"),
            "collage": (3, "one visual anchor with supporting images"),
            "freeform": (1, "Resolve the freeform layout"),
        }
        for layout, (count, expected) in cases.items():
            slots = []
            for index in range(count):
                role = "before" if layout == "before_after" and index == 0 else "after" if layout == "before_after" else "service"
                slots.append({
                    "slot_id": f"slot-{index}",
                    "label": role.upper(),
                    "role": role,
                    "key_rgb": ((255, 0, 255), (0, 255, 255), (255, 128, 0))[index],
                })
            prompt = build_overlay_prompt(layout=layout, slots=slots, visual_direction="Dirección libre")
            self.assertIn(expected, prompt)
            self.assertIn("do not use a fixed template", prompt)

    def test_composition_maps_two_sources_and_emits_hash_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay = Image.new("RGB", (300, 180), (18, 24, 36))
            draw = ImageDraw.Draw(overlay)
            draw.rectangle((10, 30, 140, 160), fill=(255, 0, 255))
            draw.rectangle((160, 30, 290, 160), fill=(0, 255, 255))
            overlay_path = root / "overlay.png"
            overlay.save(overlay_path)
            sources = []
            for color, name in [((220, 20, 20), "before"), ((20, 20, 220), "after")]:
                source = Image.new("RGB", (80, 60), color)
                path = root / f"{name}.png"
                source.save(path)
                sources.append(path)
            output = root / "composite.png"
            evidence = compose_overlay(overlay_path, [
                {"slot_id": "before", "label": "ANTES", "key_rgb": (255, 0, 255), "source": sources[0]},
                {"slot_id": "after", "label": "DESPUÉS", "key_rgb": (0, 255, 255), "source": sources[1]},
            ], output)
            self.assertTrue(evidence["pass"], evidence)
            self.assertEqual(evidence["slots"][0]["source_sha256"], hashlib.sha256(sources[0].read_bytes()).hexdigest())
            self.assertEqual(Image.open(output).getpixel((50, 80))[:3], (220, 20, 20))
            self.assertEqual(Image.open(output).getpixel((220, 80))[:3], (20, 20, 220))

    def test_tiny_key_speckle_is_ignored_but_meaningful_extra_component_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            Image.new("RGB", (20, 20), (30, 140, 220)).save(source)
            def run(extra_box, name):
                overlay = Image.new("RGB", (200, 120), (15, 20, 30))
                draw = ImageDraw.Draw(overlay)
                draw.rectangle((20, 20, 150, 100), fill=(255, 0, 255))
                if extra_box:
                    draw.rectangle(extra_box, fill=(255, 0, 255))
                path = root / f"{name}.png"
                overlay.save(path)
                return compose_overlay(path, [{"slot_id": "hero", "key_rgb": (255, 0, 255), "source": source}], root / f"{name}-out.png")
            tiny = run((180, 5, 180, 5), "tiny")
            self.assertTrue(tiny["pass"], tiny)
            self.assertEqual(tiny["slots"][0]["meaningful_extra_component_count"], 0)
            large = run((175, 5, 190, 20), "large")
            self.assertFalse(large["pass"])
            self.assertEqual(large["slots"][0]["meaningful_extra_component_count"], 1)

    def test_chromatic_key_drift_and_enclosed_text_hole_are_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            Image.new("RGB", (30, 20), (220, 20, 20)).save(source)
            overlay = Image.new("RGB", (140, 100), (15, 20, 30))
            draw = ImageDraw.Draw(overlay)
            # Image 2's magenta has drifted to (245, 7, 215).  The black
            # mark is an enclosed text-like hole in the otherwise flat slot.
            draw.rectangle((20, 20, 120, 80), fill=(245, 7, 215))
            # A one-pixel dark chroma fringe can appear when Image 2 blends
            # the magenta key edge with the surrounding charcoal artwork.
            # It is adjacent to the valid slot but too dark for ordinary key
            # drift matching.
            draw.line((19, 20, 19, 80), fill=(111, 9, 120))
            draw.line((121, 20, 121, 80), fill=(111, 9, 120))
            draw.line((18, 20, 18, 80), fill=(140, 55, 5))
            draw.rectangle((54, 40, 86, 60), fill=(0, 0, 0))
            overlay_path = root / "overlay.png"
            overlay.save(overlay_path)
            output = root / "composite.png"
            evidence = compose_overlay(overlay_path, [{
                "slot_id": "hero", "key_rgb": (255, 0, 255), "source": source,
            }], output)
            self.assertTrue(evidence["pass"], evidence)
            composed = Image.open(output)
            self.assertEqual(composed.getpixel((70, 50))[:3], (220, 20, 20))
            self.assertEqual(composed.getpixel((19, 50))[:3], (220, 20, 20))
            self.assertEqual(composed.getpixel((121, 50))[:3], (220, 20, 20))
            self.assertEqual(composed.getpixel((18, 50))[:3], (140, 55, 5))

    def test_failed_validation_does_not_write_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            Image.new("RGB", (20, 20), (220, 20, 20)).save(source)
            overlay = Image.new("RGB", (160, 100), (15, 20, 30))
            draw = ImageDraw.Draw(overlay)
            draw.rectangle((10, 20, 100, 80), fill=(255, 0, 255))
            draw.rectangle((120, 5, 140, 25), fill=(255, 0, 255))
            overlay_path = root / "invalid.png"
            overlay.save(overlay_path)
            output = root / "must-not-exist.png"
            evidence = compose_overlay(overlay_path, [{
                "slot_id": "hero", "key_rgb": (255, 0, 255), "source": source,
            }], output)
            self.assertFalse(evidence["pass"], evidence)
            self.assertIsNone(evidence["output_sha256"])
            self.assertFalse(output.exists())

    def test_logo_variants_keep_alpha_and_auto_contrast_has_no_plate(self):
        base = Image.new("RGB", (300, 200), (245, 245, 245))
        logo = Image.new("RGBA", (80, 40), (0, 0, 0, 0))
        ImageDraw.Draw(logo).rectangle((10, 10, 70, 30), fill=(15, 20, 30, 255))
        white = prepare_logo(logo, "white")
        self.assertEqual(white.getpixel((0, 0))[3], 0)
        self.assertEqual(white.getpixel((30, 20))[:3], (255, 255, 255))
        result = composite_logo(base, logo, mode="auto_contrast", position="top_left")
        self.assertEqual(result.getpixel((5, 5))[:3], (245, 245, 245))
        self.assertNotEqual(result.getpixel((30, 40))[:3], (245, 245, 245))

        dark = Image.new("RGB", (300, 200), (20, 20, 20))
        auto = composite_logo(dark, logo, mode="auto_contrast", position="auto", margin=24)
        self.assertEqual(auto.size, dark.size)
        named = composite_logo(base, logo, mode="auto_contrast", position="bottom_right", margin=24)
        self.assertEqual(named.size, base.size)
        # The transparent canvas remains untouched and logo placement is fully
        # inside the image even when the requested margin is larger than it.
        bounded = composite_logo(base, logo, mode="white", position="top_right", margin=500)
        self.assertEqual(bounded.size, base.size)

        opaque = Image.new("RGB", (80, 40), (20, 30, 40))
        with self.assertRaisesRegex(ValueError, "transparent PNG"):
            prepare_logo(opaque, "white")
        self.assertEqual(prepare_logo(opaque, "original").getpixel((0, 0))[:3], (20, 30, 40))

    def test_logo_auto_position_avoids_text_like_clutter(self):
        base = Image.new("RGB", (420, 300), (95, 95, 95))
        draw = ImageDraw.Draw(base)
        # High-contrast text-like strokes make the top-left visually occupied.
        for y in range(28, 108, 12):
            draw.rectangle((24, y, 112, y + 5), fill=(245, 245, 245))
        # A clean dark corner should win despite both regions supporting white.
        draw.rectangle((278, 188, 396, 276), fill=(28, 28, 28))
        logo = Image.new("RGBA", (100, 50), (0, 0, 0, 0))
        ImageDraw.Draw(logo).rectangle((8, 8, 92, 42), fill=(20, 25, 30, 255))

        result = composite_logo(base, logo, mode="auto_contrast", position="auto", margin=24)

        # The cluttered top-left remains untouched while the clean bottom-right
        # receives the exact solid logo variant.
        self.assertEqual(result.getpixel((55, 45))[:3], base.getpixel((55, 45)))
        self.assertNotEqual(result.getpixel((330, 250))[:3], base.getpixel((330, 250)))

    def test_logo_auto_position_prefers_uniform_field_over_clutter_with_same_luminance(self):
        base = Image.new("RGB", (420, 300), (120, 120, 120))
        draw = ImageDraw.Draw(base)
        draw.rectangle((24, 24, 142, 112), fill=(30, 30, 30))
        draw.rectangle((278, 188, 396, 276), fill=(30, 30, 30))
        for x in range(282, 394, 10):
            draw.line((x, 190, x, 274), fill=(210, 210, 210), width=4)
        logo = Image.new("RGBA", (100, 50), (0, 0, 0, 0))
        ImageDraw.Draw(logo).ellipse((8, 8, 92, 42), fill=(20, 25, 30, 255))

        result = composite_logo(base, logo, mode="auto_contrast", position="auto", margin=24)

        self.assertNotEqual(result.getpixel((70, 50))[:3], base.getpixel((70, 50)))
        self.assertEqual(result.getpixel((330, 250))[:3], base.getpixel((330, 250)))


if __name__ == "__main__":
    unittest.main()
