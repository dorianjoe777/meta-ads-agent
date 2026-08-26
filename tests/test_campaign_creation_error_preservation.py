#!/usr/bin/env python3
"""Focused regressions for truthful campaign failure receipts and retry state."""

import json
import tempfile
import unittest
from pathlib import Path

import admira_tool_bridge as bridge


class CampaignCreationErrorPreservationTests(unittest.TestCase):
    def test_failure_receipt_keeps_step_meta_error_and_cleanup(self):
        result = {
            "status": "failed",
            "executed": True,
            "result": {
                "failed_step": "create_creative",
                "result": {
                    "error": {"code": 100, "message": "Creative rejected by Meta"},
                },
                "partial_cleanup": {
                    "attempted": True,
                    "ok": True,
                    "failed_step": "create_creative",
                    "result": {"mode": "live", "executed": True, "returncode": 0},
                },
            },
        }
        receipt = bridge.campaign_creation_failure_receipt(result)
        self.assertEqual(receipt["failed_step"], "create_creative")
        self.assertEqual(receipt["error_code"], "100")
        self.assertEqual(receipt["error_message"], "Creative rejected by Meta")
        self.assertEqual(receipt["cleanup"]["mode"], "live")
        self.assertTrue(receipt["cleanup"]["ok"])

    def test_failure_receipt_parses_real_graph_stderr_and_cleanup_shape(self):
        result = {
            "executed": True,
            "failed_step": "create_creative",
            "steps": [
                {
                    "step": "resolve_whatsapp_phone_number",
                    "ok": False,
                    "result": {"reason": "no_page_linked_whatsapp_number_found"},
                },
                {
                    "step": "create_creative",
                    "ok": False,
                    "result": {
                        "returncode": 400,
                        "stderr": json.dumps({
                            "error": {
                                "message": "(#100) Your message title must be shorter than 80 characters.",
                                "type": "OAuthException",
                                "code": 100,
                            }
                        }),
                    },
                },
            ],
            "cleanup": {
                "attempted": True,
                "ok": True,
                "campaign_id": "120250875379410425",
                "failed_step": "create_creative",
                "result": {"mode": "live", "executed": True, "returncode": 0},
            },
            "partial_campaign_deleted": True,
        }
        receipt = bridge.campaign_creation_failure_receipt(result)
        self.assertEqual(receipt["failed_step"], "create_creative")
        self.assertEqual(receipt["error_code"], "100")
        self.assertIn("shorter than 80 characters", receipt["error_message"])
        self.assertTrue(receipt["cleanup"]["ok"])
        self.assertTrue(receipt["cleanup"]["partial_campaign_deleted"])
        self.assertEqual(receipt["cleanup"]["campaign_id"], "120250875379410425")

    def test_pending_workflow_preserves_brief_approvals_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            prior = bridge.PENDING_CAMPAIGN_WORKFLOW_FILE
            bridge.PENDING_CAMPAIGN_WORKFLOW_FILE = Path(directory) / "pending.json"
            try:
                args = {
                    "name": "Full Detail",
                    "daily_budget": 10,
                    "primary_text": "approved copy",
                    "headline": "approved title",
                    "primary_text_approved": True,
                    "headline_approved": True,
                    "creative_decision": "/app/output/creative.png",
                    "creative_approved": True,
                    "prefilled_message": "Hola, quiero reservar mi Full Detail.",
                    "prefilled_message_approved": True,
                }
                result = {
                    "failed_step": "create_creative",
                    "error": {"code": 100, "message": "Creative rejected by Meta"},
                    "partial_cleanup": {"attempted": True, "ok": True, "deleted": True},
                }
                brief = "# Complete buyer-approved proposal\n\nAll approved fields stay unchanged."
                self.assertTrue(
                    bridge.persist_pending_campaign_workflow(
                        "admira_create_whatsapp_campaign",
                        args,
                        "campaign_creation_not_verified",
                        result=result,
                        proposal_markdown=brief,
                    )
                )
                payload = json.loads(bridge.PENDING_CAMPAIGN_WORKFLOW_FILE.read_text())
                self.assertEqual(payload["blocker"], "campaign_creation_not_verified")
                self.assertEqual(payload["campaign_contract"]["primary_text_approved"], True)
                self.assertEqual(payload["campaign_contract"]["creative_approved"], True)
                self.assertEqual(payload["proposal_brief_markdown"], brief)
                self.assertIn("create_creative", json.dumps(payload, ensure_ascii=False))
                self.assertIn("Creative rejected by Meta", json.dumps(payload, ensure_ascii=False))
            finally:
                bridge.PENDING_CAMPAIGN_WORKFLOW_FILE = prior

    def test_message_validation_blocks_all_nested_campaign_messages_before_execution(self):
        args = {
            "prefilled_message": "Hola",
            "ad_sets": [{"ads": [{"prefilled_message": "A" * 81}]}],
            "ads": [{"welcome_message": "Hola"}],
        }
        validation = bridge.validate_campaign_customer_messages(args)
        self.assertFalse(validation["ok"])
        self.assertEqual(validation["reason"], "meta_page_welcome_message_too_long")
        self.assertEqual(validation["location"], "campaign.ad_sets[0].ads[0]")
        self.assertEqual(validation["validation"]["length"], 81)
        self.assertEqual(validation["validation"]["safe_short_proposal"], "Hola, quiero más información.")


if __name__ == "__main__":
    unittest.main()
