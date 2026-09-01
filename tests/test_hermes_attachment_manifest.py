import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hermes_bridge_manifest", ROOT / "src" / "hermes_bridge.py")
hermes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hermes)


class HermesAttachmentManifestTests(unittest.TestCase):
    def test_query_carries_backend_ordered_original_manifest_and_sheet_role(self):
        query = hermes.hermes_user_query(
            {"message": "usa estas dos fotos"},
            {
                "cli_image_path": "/tmp/hermes-attachments-contact-sheet-1234567890abcdef.png",
                "attachment_manifest": [
                    {"index": 1, "source_path": "/workspace/uploads/before.jpg", "basename": "before.jpg"},
                    {"index": 2, "source_path": "/workspace/uploads/after.jpg", "basename": "after.jpg"},
                ],
            },
        )
        self.assertIn("ADMIRA_BACKEND_ATTACHMENT_METADATA_JSON", query)
        marker = "[ADMIRA_BACKEND_ATTACHMENT_METADATA_JSON]\n"
        metadata = json.loads(query.split(marker, 1)[1].split("\n[/ADMIRA_BACKEND_ATTACHMENT_METADATA_JSON]", 1)[0])
        self.assertEqual([item["basename"] for item in metadata["ordered_originals"]], ["before.jpg", "after.jpg"])
        self.assertNotIn("/workspace/", query)
        self.assertTrue(metadata["contact_sheet"])
        self.assertEqual(metadata["contact_sheet_role"], "transport_only")


if __name__ == "__main__":
    unittest.main()
