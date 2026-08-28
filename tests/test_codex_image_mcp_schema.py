import unittest

from admira_mcp_server import TOOL_INPUT_SCHEMAS, TOOL_DEFINITIONS


class CodexImageMcpSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = TOOL_INPUT_SCHEMAS["codex_image_generate"]
        self.description = dict(TOOL_DEFINITIONS)["codex_image_generate"]

    def test_backward_compatible_request_and_purpose_remain_required(self):
        self.assertEqual(self.schema["required"], ["request", "purpose"])
        self.assertIn("request", self.schema["properties"])
        self.assertIn("purpose", self.schema["properties"])

    def test_hybrid_layout_and_structured_text_contract(self):
        props = self.schema["properties"]
        self.assertEqual(
            props["layout_intent"]["enum"],
            ["hero", "before_after", "services", "collage", "freeform"],
        )
        self.assertEqual(props["text_content"]["type"], "object")
        self.assertIn("title", props["text_content"]["properties"])
        self.assertIn("bullets", props["text_content"]["properties"])
        self.assertIn("cta", props["text_content"]["properties"])

    def test_real_media_is_ordered_and_limited_to_six_slots(self):
        media = self.schema["properties"]["real_media"]
        item = media["items"]
        self.assertEqual(media["type"], "array")
        self.assertEqual(media["maxItems"], 6)
        self.assertEqual(item["required"], ["slot_id"])
        self.assertIn("content_asset_id", item["properties"])
        self.assertIn("asset_id", item["properties"])
        self.assertIn("file_path", item["properties"])
        self.assertEqual(
            item["properties"]["role"]["enum"],
            ["hero", "before", "after", "service", "collage_item", "supporting"],
        )
        self.assertEqual(len(item["anyOf"]), 3)

    def test_attached_photo_handoff_is_explicitly_classify_then_hybrid(self):
        codex = self.description.lower()
        save_description = dict(TOOL_DEFINITIONS)["save_content_asset"].lower()
        # These are semantic operating instructions for Hermes, not a
        # conversational keyword gate. They prevent an attachment that was
        # archived as pending_agent_review from being silently routed through
        # ordinary Image 2 generation.
        self.assertIn("first inspect the batch", codex)
        self.assertIn("save_content_asset", codex)
        self.assertIn("returned asset ids", codex)
        self.assertIn("pending review", save_description)
        self.assertIn("real_media", save_description)
        self.assertIn("this or the next tool turn", codex)

    def test_style_reference_is_opt_in_and_supports_pool_or_explicit(self):
        ref = self.schema["properties"]["style_reference"]
        self.assertEqual(ref["properties"]["mode"]["enum"], ["none", "pool", "explicit"])
        self.assertEqual(ref["required"], ["mode"])
        description = ref["description"].lower()
        self.assertIn("defaults to none", description)
        self.assertIn("never keyword inference", description)
        self.assertIn("main model's natural-language understanding", self.description)

    def test_logo_and_brand_keying_controls_are_exposed(self):
        props = self.schema["properties"]
        self.assertEqual(props["brand_colors"]["items"]["type"], "string")
        self.assertEqual(props["include_logo"]["type"], "boolean")
        self.assertEqual(
            props["logo_color_mode"]["enum"],
            ["original", "white", "black", "brand_primary", "brand_secondary", "auto_contrast"],
        )
        self.assertIn("logo_position", props)


if __name__ == "__main__":
    unittest.main()
