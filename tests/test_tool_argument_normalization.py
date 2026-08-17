import unittest
from pathlib import Path

import admira_tool_bridge
from admira_tool_bridge import normalize_tool_arguments


class ToolArgumentNormalizationTests(unittest.TestCase):
    def test_bridge_product_root_resolves_real_dashboard(self):
        self.assertEqual(admira_tool_bridge.ROOT_DIR, Path(__file__).resolve().parents[1])
        self.assertTrue(admira_tool_bridge.DASHBOARD_PATH.exists())

    def test_nim_item_wrappers_become_campaign_arrays(self):
        payload = normalize_tool_arguments({
            "name": "Canary",
            "adsets": {
                "item": {
                    "name": "Core",
                    "geo_locations": {"countries": {"item": "CO"}},
                    "genders": {"item": "all"},
                    "ads": {
                        "item": {
                            "name": "Static",
                            "image_path": "/tmp/canary.png",
                        },
                    },
                },
            },
        })

        self.assertIsInstance(payload["adsets"], list)
        self.assertEqual(payload["adsets"][0]["geo_locations"]["countries"], ["CO"])
        self.assertEqual(payload["adsets"][0]["genders"], ["all"])
        self.assertEqual(payload["adsets"][0]["ads"][0]["name"], "Static")

    def test_mixed_item_mapping_is_not_destructively_unwrapped(self):
        payload = normalize_tool_arguments({
            "context_card": {
                "item": {"title": "A"},
                "style": "LIST_STYLE",
            },
        })
        self.assertEqual(payload["context_card"]["style"], "LIST_STYLE")
        self.assertEqual(payload["context_card"]["item"]["title"], "A")

    def test_nim_item_wrapper_ignores_redundant_xml_text_node(self):
        payload = normalize_tool_arguments({
            "questions": {
                "item": [
                    {"type": "FULL_NAME"},
                    {"type": "EMAIL"},
                    {"type": "PHONE"},
                ],
                "$text": "FULL_NAME",
            },
        })
        self.assertEqual(
            [item["type"] for item in payload["questions"]],
            ["FULL_NAME", "EMAIL", "PHONE"],
        )

    def test_empty_lead_form_call_is_stopped_before_product_execution(self):
        result = admira_tool_bridge.call_tool("admira_create_lead_form", {})
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "empty_tool_arguments")
        self.assertEqual(
            result["result"]["missing"],
            ["page_id", "name", "privacy_policy_url", "questions"],
        )


if __name__ == "__main__":
    unittest.main()
