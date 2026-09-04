import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from PIL import Image
except ModuleNotFoundError:  # production image runtime supplies Pillow
    Image = None

import admira_tool_bridge as bridge


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("asset_transaction_dashboard", ROOT / "dashboard" / "monitoring-dashboard.py")
if Image is not None:
    dashboard = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(dashboard)
else:
    dashboard = None


class ContentAssetTransactionTests(unittest.TestCase):
    def test_style_reference_defaults_to_task_and_requires_explicit_brand_scope_for_reuse(self):
        if Image is None:
            self.skipTest("Pillow is supplied by the image runtime, not the minimal host test interpreter")
        with tempfile.TemporaryDirectory(dir=ROOT / "output") as temp:
            root = Path(temp)
            source = root / "reference.png"
            Image.new("RGB", (32, 20), (20, 80, 150)).save(source)
            library_file = root / "library.json"
            library_file.write_text(json.dumps({"items": []}), encoding="utf-8")
            with patch.object(dashboard, "CONTENT_ASSET_LIBRARY_FILE", library_file), \
                 patch.object(dashboard, "CONTENT_ASSET_FILES_DIR", root / "stored"), \
                 patch.object(dashboard, "write_agent_onboarding_plan", lambda: None):
                task_result = dashboard.save_content_asset_memory({
                    "file_path": str(source),
                    "category": "style_reference",
                    "purpose": "solo para este diseño",
                    "preservation_mode": "style_only",
                    "approved_for_ads": True,
                    "reusable": True,
                })
                self.assertEqual(task_result["asset"]["reference_scope"], "task")
                self.assertFalse(task_result["asset"]["reusable"])

                brand_result = dashboard.save_content_asset_memory({
                    "file_path": str(source),
                    "category": "style_reference",
                    "purpose": "referencia aprobada durante branding",
                    "preservation_mode": "style_only",
                    "reference_scope": "brand",
                })
                attempted_downgrade = dashboard.save_content_asset_memory({
                    "file_path": str(source),
                    "category": "style_reference",
                    "purpose": "una tarea posterior no debe degradar branding",
                    "preservation_mode": "style_only",
                    "reference_scope": "task",
                })
            self.assertEqual(brand_result["asset_id"], task_result["asset_id"])
            self.assertEqual(brand_result["asset"]["reference_scope"], "brand")
            self.assertTrue(brand_result["asset"]["reusable"])
            self.assertTrue(brand_result["asset"]["approved_for_ads"])
            self.assertTrue(brand_result["asset"]["approved_for_daily_content"])
            self.assertEqual(attempted_downgrade["asset"]["reference_scope"], "brand")
            self.assertTrue(attempted_downgrade["asset"]["reusable"])

    def test_legacy_style_reference_migrates_to_safe_task_scope(self):
        if Image is None:
            self.skipTest("Pillow is supplied by the image runtime, not the minimal host test interpreter")
        with tempfile.TemporaryDirectory(dir=ROOT / "output") as temp:
            root = Path(temp)
            stored = root / "stored"
            stored.mkdir()
            source = stored / "legacy.png"
            Image.new("RGB", (32, 20), (20, 80, 150)).save(source)
            library_file = root / "library.json"
            library_file.write_text(json.dumps({"items": [{
                "id": "legacy-style",
                "category": "style_reference",
                "preservation_mode": "style_only",
                "classification_status": "classified",
                "approved_for_ads": True,
                "approved_for_daily_content": True,
                "reusable": True,
                "file_paths": [str(source)],
            }]}), encoding="utf-8")
            with patch.object(dashboard, "CONTENT_ASSET_LIBRARY_FILE", library_file), \
                 patch.object(dashboard, "CONTENT_ASSET_FILES_DIR", stored):
                library = dashboard.load_content_asset_library()
            self.assertEqual(library["items"][0]["reference_scope"], "task")
            self.assertFalse(library["items"][0]["reusable"])

    def test_save_returns_public_ids_and_resolves_transient_path(self):
        if Image is None:
            self.skipTest("Pillow is supplied by the image runtime, not the minimal host test interpreter")
        with tempfile.TemporaryDirectory(dir=ROOT / "output") as temp:
            root = Path(temp)
            durable = root / "stored" / "abc12345-before.jpg"
            durable.parent.mkdir()
            Image.new("RGB", (32, 20), (20, 80, 150)).save(durable)
            library_file = root / "library.json"
            source_hash = dashboard.content_asset_sha256(durable)
            library_file.write_text(json.dumps({"items": [{
                "id": "asset-before",
                "source_file_name": "before.jpg",
                "source_sha256": source_hash,
                "file_paths": [str(durable)],
                "category": "product",
                "preservation_mode": "pixel_locked",
                "classification_status": "pending_agent_review",
            }]}), encoding="utf-8")
            with patch.object(dashboard, "CONTENT_ASSET_LIBRARY_FILE", library_file), \
                 patch.object(dashboard, "CONTENT_ASSET_FILES_DIR", root / "stored"), \
                 patch.object(dashboard, "write_agent_onboarding_plan", lambda: None):
                result = dashboard.save_content_asset_memory({
                    "file_path": "hermes-workspace/current/uploads/before.jpg",
                    "category": "product",
                    "purpose": "foto real before",
                })
            self.assertEqual(result["asset_id"], "asset-before")
            self.assertEqual(result["asset_ids"], ["asset-before"])
            self.assertEqual(result["saved_asset_count"], 1)
            self.assertEqual(result["asset"]["file_paths"], [str(durable.resolve())])

    def test_unresolved_explicit_file_never_claims_saved_asset(self):
        if Image is None:
            self.skipTest("Pillow is supplied by the image runtime, not the minimal host test interpreter")
        with tempfile.TemporaryDirectory(dir=ROOT / "output") as temp:
            root = Path(temp)
            library_file = root / "library.json"
            library_file.write_text(json.dumps({"items": []}), encoding="utf-8")
            with patch.object(dashboard, "CONTENT_ASSET_LIBRARY_FILE", library_file), \
                 patch.object(dashboard, "CONTENT_ASSET_FILES_DIR", root / "stored"), \
                 patch.object(dashboard, "write_agent_onboarding_plan", lambda: None):
                with self.assertRaisesRegex(ValueError, "resolver todos los archivos"):
                    dashboard.save_content_asset_memory({
                        "file_paths": ["hermes-workspace/current/uploads/missing.jpg"],
                        "category": "product",
                        "purpose": "foto real",
                    })
            self.assertEqual(json.loads(library_file.read_text(encoding="utf-8"))["items"], [])

    def test_multi_file_save_is_atomic_when_one_explicit_path_is_missing(self):
        if Image is None:
            self.skipTest("Pillow is supplied by the image runtime, not the minimal host test interpreter")
        with tempfile.TemporaryDirectory(dir=ROOT / "output") as temp:
            root = Path(temp)
            durable = root / "stored" / "abc12345-before.jpg"
            durable.parent.mkdir()
            Image.new("RGB", (32, 20), (20, 80, 150)).save(durable)
            library_file = root / "library.json"
            original_library = {"items": [{
                "id": "asset-before",
                "source_file_name": "before.jpg",
                "source_sha256": dashboard.content_asset_sha256(durable),
                "file_paths": [str(durable)],
                "category": "product",
                "preservation_mode": "pixel_locked",
                "classification_status": "pending_agent_review",
                "approved_for_daily_content": False,
                "approved_for_ads": False,
            }]}
            library_file.write_text(json.dumps(original_library), encoding="utf-8")
            with patch.object(dashboard, "CONTENT_ASSET_LIBRARY_FILE", library_file), \
                 patch.object(dashboard, "CONTENT_ASSET_FILES_DIR", root / "stored"), \
                 patch.object(dashboard, "write_agent_onboarding_plan", lambda: None):
                with self.assertRaisesRegex(ValueError, "lote parcial"):
                    dashboard.save_content_asset_memory({
                        "file_paths": [
                            "hermes-workspace/current/uploads/before.jpg",
                            "hermes-workspace/current/uploads/missing.jpg",
                        ],
                        "category": "product",
                        "purpose": "before and after",
                    })
            self.assertEqual(json.loads(library_file.read_text(encoding="utf-8")), original_library)

    def test_ambiguous_explicit_basename_fails_closed(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "output") as temp:
            root = Path(temp)
            first = root / "one" / "same.jpg"
            second = root / "two" / "same.jpg"
            first.parent.mkdir(); second.parent.mkdir()
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            with patch.object(bridge, "content_asset_library_items", return_value=[
                {"id": "one", "source_file_name": "same.jpg", "file_paths": [str(first)]},
                {"id": "two", "source_file_name": "same.jpg", "file_paths": [str(second)]},
            ]):
                self.assertEqual(bridge.resolve_archived_content_asset_paths(["uploads/same.jpg"]), [])

    def test_compacted_receipt_exposes_public_asset_ids(self):
        compacted = bridge.compact_agent_tool_result("admira_save_content_asset", {
            "saved": True,
            "asset_id": "asset-hero",
            "asset_ids": ["asset-hero", "asset-after"],
            "assets": [{"id": "asset-hero"}, {"id": "asset-after"}],
        })
        receipt = compacted["result"]
        self.assertEqual(receipt["asset_id"], "asset-hero")
        self.assertEqual(receipt["asset_ids"], ["asset-hero", "asset-after"])

    def test_bridge_resolves_hero_and_ordered_before_after_ids(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "output") as temp:
            root = Path(temp)
            before = root / "before.jpg"
            after = root / "after.jpg"
            before.write_bytes(b"before")
            after.write_bytes(b"after")
            items = [
                {"id": "asset-before", "source_file_name": "before.jpg", "file_paths": [str(before)]},
                {"id": "asset-after", "source_file_name": "after.jpg", "file_paths": [str(after)]},
            ]
            with patch.object(bridge, "content_asset_library_items", return_value=items):
                resolved = bridge.resolve_archived_content_asset_paths([
                    "hermes-workspace/current/uploads/before.jpg",
                    "hermes-workspace/current/uploads/after.jpg",
                ])
            self.assertEqual(resolved, [str(before.resolve()), str(after.resolve())])

    def test_bridge_never_hydrates_only_part_of_an_explicit_batch(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "output") as temp:
            root = Path(temp)
            before = root / "before.jpg"
            before.write_bytes(b"before")
            items = [{"id": "asset-before", "source_file_name": "before.jpg", "file_paths": [str(before)]}]
            original_args = {
                "file_paths": ["uploads/before.jpg", "uploads/missing.jpg"],
                "category": "product",
                "purpose": "before and after",
            }
            with patch.object(bridge, "content_asset_library_items", return_value=items):
                resolved = bridge.resolve_archived_content_asset_paths(original_args["file_paths"])
                hydrated = bridge.hydrate_archived_content_asset_paths(
                    "admira_save_content_asset", dict(original_args)
                )
            self.assertEqual(resolved, [])
            self.assertEqual(hydrated, original_args)


if __name__ == "__main__":
    unittest.main()
