import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hybrid_capability_dashboard", ROOT / "dashboard" / "monitoring-dashboard.py")
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)


class HybridTurnAssetCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "output")
        self.root = Path(self.temp.name)
        self.asset_path = self.root / "hero.jpg"
        Image.new("RGB", (40, 30), (30, 60, 90)).save(self.asset_path)
        self.library_file = self.root / "content_asset_library.json"
        self.capability_file = self.root / "hybrid_turn_asset_capability.json"
        self.capability_lock = self.root / "hybrid_turn_asset_capability.lock"
        self.context_file = self.root / "CURRENT_CONTEXT.json"
        self.turn = {
            "chat_id": "-1001",
            "session_id": "session-a",
            "transport": "telegram",
            "message_sequence": 7,
            "message_hash": "hash-a",
        }
        self.library_file.write_text(json.dumps({"items": [{
            "id": "asset-hero",
            "file_paths": [str(self.asset_path)],
            "category": "product",
            "preservation_mode": "pixel_locked",
            "classification_status": "classified",
            "approved_for_ads": False,
            "approved_for_daily_content": True,
        }]}), encoding="utf-8")
        self.patches = [
            patch.object(dashboard, "HYBRID_TURN_ASSET_CAPABILITY_FILE", self.capability_file),
            patch.object(dashboard, "HYBRID_TURN_ASSET_CAPABILITY_LOCK_FILE", self.capability_lock),
            patch.object(dashboard, "CONTENT_ASSET_LIBRARY_FILE", self.library_file),
            patch.object(dashboard, "HERMES_CURRENT_CONTEXT_FILE", self.context_file),
            patch.object(dashboard, "_trusted_buyer_turn", lambda max_age_seconds=300: dict(self.turn)),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def _payload(self, *ids):
        return {"real_media": [
            {"slot_id": f"slot-{index}", "content_asset_id": asset_id, "role": "hero"}
            for index, asset_id in enumerate(ids, 1)
        ]}

    def test_omitted_ads_approval_allows_only_immediate_exact_hybrid_use(self):
        recorded = dashboard._record_hybrid_turn_asset_capability(["asset-hero"])
        self.assertTrue(recorded["recorded"])
        slots, _ = dashboard._hybrid_real_media(
            self._payload("asset-hero"), turn_capability=dashboard._hybrid_turn_asset_capability_for_ids(["asset-hero"])
        )
        self.assertEqual([slot["asset_id"] for slot in slots], ["asset-hero"])
        self.assertFalse(json.loads(self.library_file.read_text(encoding="utf-8"))["items"][0]["approved_for_ads"])

    def test_mismatched_order_or_session_fails_closed(self):
        dashboard._record_hybrid_turn_asset_capability(["asset-hero"])
        self.assertIsNone(dashboard._hybrid_turn_asset_capability_for_ids(["other-id"]))
        with patch.object(dashboard, "_trusted_buyer_turn", lambda max_age_seconds=300: dict(self.turn, session_id="other")):
            self.assertIsNone(dashboard._hybrid_turn_asset_capability_for_ids(["asset-hero"]))

    def test_receipt_is_reusable_after_provider_failure_and_consumed_after_success(self):
        dashboard._record_hybrid_turn_asset_capability(["asset-hero"])
        cap = dashboard._hybrid_turn_asset_capability_for_ids(["asset-hero"])
        self.assertIsNotNone(cap)
        stored = json.loads(self.capability_file.read_text(encoding="utf-8"))["receipts"]
        self.assertTrue(stored)
        self.assertTrue(all(not item["used"] for item in stored))
        self.assertTrue(dashboard._consume_hybrid_turn_asset_capability(["asset-hero"]))
        self.assertIsNone(dashboard._hybrid_turn_asset_capability_for_ids(["asset-hero"]))

    def test_separate_same_turn_saves_keep_individual_and_ordered_batch_receipts(self):
        second_path = self.root / "after.jpg"
        Image.new("RGB", (40, 30), (90, 60, 30)).save(second_path)
        library = json.loads(self.library_file.read_text(encoding="utf-8"))
        library["items"].append({
            "id": "asset-after",
            "file_paths": [str(second_path)],
            "category": "product",
            "preservation_mode": "pixel_locked",
            "classification_status": "classified",
            "approved_for_ads": False,
            "approved_for_daily_content": True,
        })
        self.library_file.write_text(json.dumps(library), encoding="utf-8")
        dashboard._record_hybrid_turn_asset_capability(["asset-hero"])
        dashboard._record_hybrid_turn_asset_capability(["asset-after"])
        self.assertIsNotNone(dashboard._hybrid_turn_asset_capability_for_ids(["asset-hero"]))
        self.assertIsNotNone(dashboard._hybrid_turn_asset_capability_for_ids(["asset-after"]))
        combined = dashboard._hybrid_turn_asset_capability_for_ids(["asset-hero", "asset-after"])
        self.assertIsNotNone(combined)
        slots, _ = dashboard._hybrid_real_media(
            {
                "real_media": [
                    {"slot_id": "before", "content_asset_id": "asset-hero", "role": "before"},
                    {"slot_id": "after", "content_asset_id": "asset-after", "role": "after"},
                ]
            },
            turn_capability=combined,
        )
        self.assertEqual([slot["asset_id"] for slot in slots], ["asset-hero", "asset-after"])
        self.assertTrue(dashboard._consume_hybrid_turn_asset_capability(["asset-hero", "asset-after"]))
        self.assertIsNone(dashboard._hybrid_turn_asset_capability_for_ids(["asset-hero"]))
        self.assertIsNone(dashboard._hybrid_turn_asset_capability_for_ids(["asset-after"]))

    def test_consuming_one_separate_save_does_not_revoke_the_other(self):
        dashboard._record_hybrid_turn_asset_capability(["asset-hero"])
        dashboard._record_hybrid_turn_asset_capability(["asset-after"])
        self.assertTrue(dashboard._consume_hybrid_turn_asset_capability(["asset-hero"]))
        self.assertIsNone(dashboard._hybrid_turn_asset_capability_for_ids(["asset-hero"]))
        self.assertIsNotNone(dashboard._hybrid_turn_asset_capability_for_ids(["asset-after"]))

    def test_more_than_six_or_duplicate_ids_are_rejected(self):
        self.assertFalse(dashboard._record_hybrid_turn_asset_capability(["x"] * 2)["recorded"])
        self.assertFalse(dashboard._record_hybrid_turn_asset_capability([str(i) for i in range(7)])["recorded"])

    def test_contact_sheet_save_expands_ordered_originals_and_never_saves_sheet(self):
        uploads = self.root / "uploads"
        uploads.mkdir()
        before = uploads / "before.jpg"
        after = uploads / "after.jpg"
        Image.new("RGB", (40, 30), (200, 10, 10)).save(before)
        Image.new("RGB", (40, 30), (10, 20, 200)).save(after)
        sheet = uploads / "hermes-attachments-contact-sheet-1234567890abcdef.png"
        Image.new("RGB", (80, 30), (20, 20, 20)).save(sheet)
        self.context_file.write_text(json.dumps({"cli_image_path": str(sheet), "attachment_manifest": [
            {"index": 1, "source_path": str(before), "basename": "before.jpg"},
            {"index": 2, "source_path": str(after), "basename": "after.jpg"},
        ]}), encoding="utf-8")
        saved = dashboard.save_content_asset_memory({
            "file_path": str(sheet), "category": "product", "purpose": "fotos reales antes y despues",
            "preservation_mode": "pixel_locked", "classification_status": "classified",
        })
        self.assertEqual(saved["saved_asset_count"], 2)
        self.assertEqual([Path(item["file_paths"][0]).name.split("-", 1)[-1] for item in saved["assets"]], ["before.jpg", "after.jpg"])
        self.assertEqual(len({item["source_sha256"] for item in saved["assets"]}), 2)
        self.assertFalse(any(Path(item["file_paths"][0]).name.startswith("hermes-attachments-contact-sheet-") for item in saved["assets"]))

    def test_same_basename_outside_current_uploads_fails_closed(self):
        uploads = self.root / "uploads"
        uploads.mkdir()
        before = uploads / "before.jpg"
        after = uploads / "after.jpg"
        trusted_sheet = uploads / "hermes-attachments-contact-sheet-1234567890abcdef.png"
        impostor = self.root / "hermes-attachments-contact-sheet-1234567890abcdef.png"
        for path, colour in ((before, (200, 10, 10)), (after, (10, 20, 200)),
                             (trusted_sheet, (20, 20, 20)), (impostor, (40, 40, 40))):
            Image.new("RGB", (40, 30), colour).save(path)
        self.context_file.write_text(json.dumps({"cli_image_path": str(trusted_sheet), "attachment_manifest": [
            {"index": 1, "source_path": str(before)},
            {"index": 2, "source_path": str(after)},
        ]}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "no coincide"):
            dashboard.save_content_asset_memory({"file_path": str(impostor), "purpose": "prueba"})

    def test_manifest_source_outside_current_uploads_fails_closed(self):
        uploads = self.root / "uploads"
        uploads.mkdir()
        trusted_sheet = uploads / "hermes-attachments-contact-sheet-1234567890abcdef.png"
        outside = self.root / "outside.jpg"
        Image.new("RGB", (40, 30), (20, 20, 20)).save(trusted_sheet)
        Image.new("RGB", (40, 30), (200, 10, 10)).save(outside)
        self.context_file.write_text(json.dumps({"cli_image_path": str(trusted_sheet), "attachment_manifest": [
            {"index": 1, "source_path": str(outside)},
        ]}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "no pertenece"):
            dashboard.save_content_asset_memory({"file_path": str(trusted_sheet), "purpose": "prueba"})

    def test_stale_current_context_fails_closed(self):
        uploads = self.root / "uploads"
        uploads.mkdir()
        before = uploads / "before.jpg"
        sheet = uploads / "hermes-attachments-contact-sheet-1234567890abcdef.png"
        Image.new("RGB", (40, 30), (200, 10, 10)).save(before)
        Image.new("RGB", (40, 30), (20, 20, 20)).save(sheet)
        self.context_file.write_text(json.dumps({"cli_image_path": str(sheet), "attachment_manifest": [
            {"index": 1, "source_path": str(before)},
        ]}), encoding="utf-8")
        old = self.context_file.stat().st_mtime - 601
        os.utime(self.context_file, (old, old))
        with self.assertRaisesRegex(ValueError, "vencido"):
            dashboard.save_content_asset_memory({"file_path": str(sheet), "purpose": "prueba"})

    def test_provider_failure_does_not_consume_but_successful_composition_does(self):
        dashboard._record_hybrid_turn_asset_capability(["asset-hero"])
        payload = {
            "request": "Diseño publicitario premium usando esta foto real",
            "purpose": "ad_creative",
            "layout_intent": "hero",
            "real_media": [{"slot_id": "hero", "content_asset_id": "asset-hero", "role": "hero"}],
            "style_reference": {"mode": "none"},
            "include_logo": False,
        }
        common = [
            patch.object(dashboard, "CREATIVE_ASSET_ROOT", self.root / "creatives"),
            patch.object(dashboard, "selected_product_guide_for_creative", return_value=("", "test")),
            patch.object(dashboard, "creative_direct_context", return_value=""),
            patch.object(dashboard, "creative_strategy_readiness", return_value={"ready": True}),
            patch.object(dashboard, "official_brand_logo_path", return_value=None),
            patch.object(dashboard, "guide_library", return_value={"general": {"fields": {}}}),
            patch.object(dashboard, "choose_key_colors", return_value=[(255, 0, 255)]),
            patch.object(dashboard, "recent_generated_creatives", return_value={"retention_days": 3, "expired_removed": 0}),
            patch.object(dashboard, "log_action", lambda *args, **kwargs: None),
        ]
        for item in common:
            item.start()
        try:
            with patch.object(dashboard, "call_codex_image_cli", return_value={"ok": False, "error": "temporary provider failure"}):
                failed = dashboard.codex_image_generate(payload)
            self.assertFalse(failed["ok"])
            self.assertIsNotNone(dashboard._hybrid_turn_asset_capability_for_ids(["asset-hero"]))

            def successful_provider(_prompt, **kwargs):
                output_root = Path(kwargs["output_root"])
                output_root.mkdir(parents=True, exist_ok=True)
                overlay_path = output_root / "overlay.png"
                overlay = Image.new("RGB", (220, 180), (18, 24, 36))
                ImageDraw.Draw(overlay).rectangle((20, 20, 200, 160), fill=(255, 0, 255))
                overlay.save(overlay_path)
                return {"ok": True, "image_path": str(overlay_path)}

            with patch.object(dashboard, "call_codex_image_cli", side_effect=successful_provider):
                succeeded = dashboard.codex_image_generate(payload)
            self.assertTrue(succeeded["ok"], succeeded)
            self.assertTrue(succeeded["hybrid"]["composition"]["pass"])
            self.assertIsNone(dashboard._hybrid_turn_asset_capability_for_ids(["asset-hero"]))
            self.assertFalse(json.loads(self.library_file.read_text(encoding="utf-8"))["items"][0]["approved_for_ads"])
        finally:
            for item in reversed(common):
                item.stop()

    def test_same_turn_explicit_pixel_locked_asset_is_promoted_to_hybrid(self):
        dashboard._record_hybrid_turn_asset_capability(["asset-hero"])
        normalized, asset_ids = dashboard._recover_implicit_hybrid_real_media({
            "request": "Crear diseño usando la foto real",
            "purpose": "ad_creative",
            "content_asset_ids": ["asset-hero"],
            "reference_image_paths": [str(self.asset_path)],
        }, purpose="ad_creative")
        self.assertEqual(asset_ids, ["asset-hero"])
        self.assertEqual(normalized["reference_image_paths"], [])
        self.assertEqual(normalized["real_media"], [{
            "slot_id": "hero", "content_asset_id": "asset-hero", "role": "hero",
        }])

    def test_other_turn_ordinary_request_remains_compatible(self):
        dashboard._record_hybrid_turn_asset_capability(["asset-hero"])
        prompt_package = {
            "mode": "fixed", "purpose": "ad_creative", "seed": "test",
            "variation_count": 1, "variation_ledger": [], "product_guide": "",
            "ad_brief": "", "logo_context": "", "prompts": [{
                "image_prompt": "ordinary prompt", "variant_id": "ordinary",
                "design_axis": "", "composition": "", "experiment": "",
            }],
        }
        with patch.object(dashboard, "_trusted_buyer_turn", lambda max_age_seconds=300: dict(self.turn, message_sequence=8)), \
             patch.object(dashboard, "selected_product_guide_for_creative", return_value=("", "test")), \
             patch.object(dashboard, "creative_direct_context", return_value=""), \
             patch.object(dashboard, "creative_strategy_readiness", return_value={"ready": True}), \
             patch.object(dashboard, "build_codex_image_prompt_package", return_value=prompt_package), \
             patch.object(dashboard, "official_brand_logo_path", return_value=None), \
             patch.object(dashboard, "guide_library", return_value={"general": {"fields": {}}}), \
             patch.object(dashboard, "load_config", return_value=SimpleNamespace(codex_creative_model="gpt-image-2")), \
             patch.object(dashboard, "recent_generated_creatives", return_value={"retention_days": 3, "expired_removed": 0}), \
             patch.object(dashboard, "log_action", lambda *args, **kwargs: None), \
             patch.object(dashboard, "call_codex_image_cli", return_value={"ok": True, "asset_id": "ordinary.png"}) as provider:
            result = dashboard.codex_image_generate({
                "request": "Crear una variación ordinaria",
                "purpose": "ad_creative",
                "content_asset_ids": ["asset-hero"],
            })
        self.assertTrue(result["ok"], result)
        self.assertNotEqual(result.get("reason"), "hybrid_required")
        provider.assert_called_once()


if __name__ == "__main__":
    unittest.main()
