#!/usr/bin/env python3
"""Regression tests for bounded MCP receipts sent back to the model."""

import json
import unittest

import admira_tool_bridge as bridge


class CompactToolReceiptTests(unittest.TestCase):
    def test_oauth_inventory_never_returns_credentials_or_business_dump(self):
        result = bridge.compact_oauth_workspace_result({
            "connected": True,
            "active_ad_account_id": "",
            "active_page_id": "",
            "user_token": "secret-user-token",
            "accounts": [{
                "id": "act_1", "name": "Cuenta", "currency": "COP",
                "access_token": "secret-account-token",
            }],
            "pages": [{
                "id": "page_1", "name": "Página", "can_publish": True,
                "access_token": "secret-page-token",
            }],
            "businesses": [{"id": "biz_1", "name": "Very large duplicate"}],
            "selection_intent_open": True,
        })
        serialized = json.dumps(result)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("businesses", result)
        self.assertTrue(result["selection_required"])
        self.assertEqual(result["accounts"][0]["currency"], "COP")
        self.assertTrue(result["selection_intent_open"])

    def test_standard_live_context_is_bounded_and_drops_duplicate_private_context(self):
        context = {
            "metrics_source": {"is_real_meta_data": True},
            "inventory_counts": {"campaigns": 500, "adsets": 1000, "ads": 2000},
            "campaigns": [{"id": str(index), "name": "x" * 100} for index in range(500)],
            "adsets": [{"id": str(index)} for index in range(1000)],
            "ads": [{"id": str(index)} for index in range(2000)],
            "campaign_tree": [{"id": str(index), "payload": "x" * 500} for index in range(500)],
            "breakdowns": {"placement": [{"payload": "x" * 500} for _ in range(500)]},
            "business_profile": {"private_notes": "x" * 100_000},
            "oauth_workspace": {
                "authorized": True,
                "selection_required": False,
                "active_ad_account_id": "act_1",
                "active_page_id": "page_1",
                "accounts": [{"access_token": "secret"}],
            },
        }
        compact = bridge.compact_meta_context(context, "standard")
        self.assertEqual(len(compact["campaigns"]), 40)
        self.assertEqual(len(compact["adsets"]), 80)
        self.assertEqual(len(compact["ads"]), 120)
        self.assertNotIn("campaign_tree", compact)
        self.assertNotIn("breakdowns", compact)
        self.assertNotIn("business_profile", compact)
        self.assertNotIn("accounts", compact["oauth_workspace"])
        self.assertLess(len(json.dumps(compact)), 60_000)

    def test_memory_receipt_keeps_readiness_but_not_full_profile(self):
        result = bridge.compact_agent_tool_result("admira_save_business_memory", {
            "type": "save_business_context",
            "executed": True,
            "reply": "saved",
            "result": {
                "saved": True,
                "profile": {"large": "x" * 100_000},
                "strategic_profile": {
                    "status": "review_required",
                    "revision": 4,
                    "confirmed_revision": None,
                    "complete": False,
                },
            },
        })
        self.assertNotIn("profile", result["result"])
        self.assertEqual(result["result"]["strategic_profile"]["revision"], 4)
        self.assertLess(len(json.dumps(result)), 1_000)

    def test_media_receipt_preserves_attachment_path(self):
        result = bridge.compact_agent_tool_result("admira_codex_image_generate", {
            "type": "codex_image_generate",
            "executed": True,
            "result": {
                "ok": True,
                "image_path": "/app/output/image.png",
                "preview_url": "/api/preview/image.png",
                "guide_library": {"large": "x" * 100_000},
            },
        })
        self.assertEqual(result["result"]["image_path"], "/app/output/image.png")
        self.assertNotIn("guide_library", result["result"])

    def test_campaign_receipt_keeps_real_meta_ids(self):
        result = bridge.compact_agent_tool_result("admira_create_whatsapp_campaign", {
            "type": "create_campaign_stack",
            "executed": True,
            "result": {
                "status": "created_paused",
                "executed": True,
                "result": {
                    "executed": True,
                    "campaign_id": "1201",
                    "adset_ids": ["2201", "2202"],
                    "ad_ids": ["3201", "3202"],
                    "graph_verification": {
                        "ok": True,
                        "objects": [
                            {"http_status": 200},
                            {"http_status": 200},
                            {"http_status": 200},
                            {"http_status": 200},
                            {"http_status": 200},
                        ],
                    },
                    "raw_graph": {"large": "x" * 100_000},
                },
            },
        })
        self.assertEqual(result["result"]["status"], "created_paused")
        self.assertEqual(result["result"]["campaign_id"], "1201")
        self.assertEqual(result["result"]["adset_ids"], ["2201", "2202"])
        self.assertNotIn("raw_graph", result["result"])


if __name__ == "__main__":
    unittest.main()
