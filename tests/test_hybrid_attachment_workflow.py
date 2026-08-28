import unittest
import tempfile
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # native lightweight test environments may omit Pillow
    Image = None

from admira_mcp_server import TOOL_INPUT_SCHEMAS, TOOL_DEFINITIONS
import hermes_bridge
from hermes_bridge import _attachment_manifest, _make_hermes_contact_sheet, safe_image_paths


ROOT = Path(__file__).resolve().parents[1]


class HybridAttachmentWorkflowTests(unittest.TestCase):
    """Regression contract for natural attached-photo handoff.

    Hermes owns semantic interpretation. This test only verifies that the
    public MCP/skill contract exposes the required sequence and both common
    mappings, without introducing a keyword classifier.
    """

    def test_hero_attachment_maps_one_saved_asset(self):
        schema = TOOL_INPUT_SCHEMAS["codex_image_generate"]
        media = {"slot_id": "hero", "content_asset_id": "asset-photo", "role": "hero"}
        self.assertEqual(schema["properties"]["layout_intent"]["enum"][0], "hero")
        self.assertEqual(media["role"], "hero")
        self.assertIn("real_media", schema["properties"])

    def test_before_after_attachment_preserves_order(self):
        schema = TOOL_INPUT_SCHEMAS["codex_image_generate"]
        media = [
            {"slot_id": "before", "content_asset_id": "asset-before", "role": "before"},
            {"slot_id": "after", "content_asset_id": "asset-after", "role": "after"},
        ]
        self.assertEqual(schema["properties"]["layout_intent"]["enum"][1], "before_after")
        self.assertEqual([item["role"] for item in media], ["before", "after"])
        self.assertNotEqual(media[0]["content_asset_id"], media[1]["content_asset_id"])

    def test_skill_teaches_semantic_handoff_without_keyword_filter(self):
        skill = (ROOT / "agent/skills/creative-production-codex-image/SKILL.md").read_text(encoding="utf-8").lower()
        self.assertIn("mcp_admira_save_content_asset", skill)
        self.assertIn("mcp_admira_codex_image_generate", skill)
        self.assertIn("pending_agent_review", skill)
        self.assertIn("same turn, or the immediately following tool turn", skill)
        self.assertIn("not a keyword classifier", skill)

    @unittest.skipIf(Image is None, "Pillow is installed in the runtime image, not all native test environments")
    def test_multi_attachment_manifest_is_ordered_and_contact_sheet_is_transport_only(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            paths = []
            for index, color in enumerate(((220, 30, 30), (30, 220, 30), (30, 30, 220)), start=1):
                path = source / f"photo-{index}.png"
                Image.new("RGB", (80, 60), color).save(path)
                paths.append(str(path))
            manifest = _attachment_manifest(paths)
            sheet = Path(directory) / "sheet.png"
            result = _make_hermes_contact_sheet(paths, sheet)
            self.assertEqual([item["index"] for item in manifest], [1, 2, 3])
            self.assertEqual([item["source_path"] for item in manifest], paths)
            self.assertEqual(result, str(sheet))
            self.assertTrue(sheet.exists())
            with Image.open(sheet) as image:
                self.assertGreater(image.width, 80)
                self.assertGreater(image.height, 60)

    @unittest.skipIf(Image is None, "Pillow is installed in the runtime image, not all native test environments")
    def test_single_attachment_does_not_create_contact_sheet(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "photo.png"
            Image.new("RGB", (80, 60), "white").save(path)
            self.assertEqual(_make_hermes_contact_sheet([str(path)], Path(directory) / "unused.png"), str(path))

    def test_cli_uses_contact_sheet_but_keeps_manifest(self):
        class Config:
            hermes_cli = "hermes"
            hermes_max_iterations = 2
            hermes_response_timeout_seconds = 30
            hermes_timeout_seconds = 30
            hermes_require_codex_auth = False

        captured = {}
        original = {
            "_record_bridge_trusted_buyer_turn": hermes_bridge._record_bridge_trusted_buyer_turn,
            "prepare_hermes_workspace": hermes_bridge.prepare_hermes_workspace,
            "write_cli_hermes_config": hermes_bridge.write_cli_hermes_config,
            "hermes_brain_settings": hermes_bridge.hermes_brain_settings,
            "hermes_environment": hermes_bridge.hermes_environment,
        }
        original_subprocess_run = hermes_bridge.subprocess.run
        try:
            sheet = "/workspace/uploads/hermes-attachments-contact-sheet.png"
            originals = ["/workspace/uploads/photo-1.png", "/workspace/uploads/photo-2.png"]
            hermes_bridge._record_bridge_trusted_buyer_turn = lambda payload: payload
            hermes_bridge.prepare_hermes_workspace = lambda payload: {
                "path": "/workspace",
                "hermes_home": "/hermes",
                "files": ["memory/attachment_manifest.json"],
                "image_paths": originals,
                "cli_image_path": sheet,
                "attachment_manifest": _attachment_manifest(originals),
            }
            hermes_bridge.write_cli_hermes_config = lambda *args, **kwargs: {"hermes_home": "/hermes"}
            hermes_bridge.hermes_brain_settings = lambda config: {"provider": "gemini", "model": "test"}
            hermes_bridge.hermes_environment = lambda config: {}

            class Completed:
                returncode = 0
                stdout = "ok"
                stderr = ""

            def fake_run(command, **kwargs):
                captured["command"] = command
                return Completed()

            hermes_bridge.subprocess.run = fake_run
            result = hermes_bridge.cli_chat(Config(), {"channel": "simulated_telegram", "message": "usa ambas"})
            self.assertEqual(result, "ok")
            command = captured["command"]
            self.assertIn(["--image", sheet][0], command)
            self.assertEqual(command[command.index("--image") + 1], sheet)
            self.assertNotIn(originals[0], command)
        finally:
            for name, value in original.items():
                setattr(hermes_bridge, name, value)
            hermes_bridge.subprocess.run = original_subprocess_run


if __name__ == "__main__":
    unittest.main()
