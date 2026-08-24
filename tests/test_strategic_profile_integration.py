#!/usr/bin/env python3
"""Focused integration checks for the strategic-profile product boundary."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import admira_tool_bridge
from strategic_profile import (
    TOPICS,
    action_eligibility,
    apply_topic_updates,
    confirm_current_revision,
    embed_profile,
    mark_review_presented,
    new_profile,
)


PAGE_A = "1319759131214498"
PAGE_B = "9999999999999999"
NOW_1 = "2026-08-22T12:00:00+00:00"
NOW_2 = "2026-08-22T12:01:00+00:00"
NOW_3 = "2026-08-22T12:02:00+00:00"
BINDING = {"chat_id": "42", "session_id": "telegram:42", "transport": "telegram"}


def confirmed_topic_updates():
    return {
        topic: {
            "value": f"buyer-confirmed {topic}",
            "status": "confirmed",
            "confirmation_state": "buyer_confirmed",
        }
        for topic in TOPICS
    }


def reviewed_profile(page_id=PAGE_A):
    profile = apply_topic_updates(
        new_profile(page_id, now=NOW_1),
        confirmed_topic_updates(),
        page_id=page_id,
        trusted_buyer_confirmation=True,
        evidence={**BINDING, "message_hash": "answers", "message_sequence": 10},
        now=NOW_2,
    )
    profile = mark_review_presented(
        profile,
        page_id=page_id,
        after_buyer_message_sequence=10,
        assistant_message_hash="summary",
        evidence={**BINDING, "message_sequence": 10},
        now=NOW_2,
    )
    return confirm_current_revision(
        profile,
        page_id=page_id,
        trusted_buyer_confirmation=True,
        evidence={**BINDING, "message_hash": "final-review", "message_sequence": 11},
        now=NOW_3,
    )


class FakeDashboard:
    """Minimal dashboard surface proving what reaches product providers."""

    def __init__(self, profile, page_id=PAGE_A):
        self.profile = profile
        self.page_id = page_id
        self.executions = []
        self.oauth_calls = []
        self.read_calls = []
        self.PENDING_FILE = "pending.json"
        self.pending = []

    def read_json(self, _path, default):
        return self.pending if self.pending else default

    def strategic_product_action_eligibility(self, category):
        return action_eligibility(
            self.profile,
            active_page_id=self.page_id,
            action_category=category,
        )

    def execute_agent_tool(self, request, payload):
        self.executions.append((request, payload))
        return {"ok": True, "executed": True, "provider_reached": True}

    def handle_campaign_edit_tool(self, *_args, **_kwargs):
        raise AssertionError("campaign edit provider must not run before onboarding")

    def social_oauth_status(self):
        self.oauth_calls.append("status")
        return {
            "connected": True,
            "active_ad_account_id": "act_123",
            "active_page_id": self.page_id,
            "accounts": [],
            "pages": [],
            "businesses": [],
        }

    def social_oauth_start(self, args):
        self.oauth_calls.append(("start", args))
        return {"ok": True, "authorization_url": "https://example.test/oauth"}

    def social_oauth_select(self, args):
        self.oauth_calls.append(("select", args))
        return {"selected": True}

    def meta_targeting_search(self, args):
        self.read_calls.append(("targeting", args))
        return {"ok": True, "items": []}


class StrategicProfileDashboardIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboard = admira_tool_bridge.load_dashboard()

    def test_legacy_four_fields_do_not_complete_dashboard_readiness(self):
        legacy = {
            "page_id": PAGE_A,
            "main_offer": "Diseño de sonrisa",
            "ideal_customer": "Adultos de Cartagena",
            "current_stage": "Cuenta nueva",
            "what_to_improve": "Captar pacientes",
            "context_complete": True,
            "context_completed_at": NOW_1,
        }

        readiness = self.dashboard.strategic_business_profile_readiness(
            profile=legacy,
            page_id=PAGE_A,
        )

        self.assertEqual(readiness["status"], "collecting")
        self.assertFalse(readiness["complete"])
        self.assertEqual(readiness["resolved_topics"], [])
        self.assertEqual(readiness["confirmed_revision"], None)

    def test_ten_confirmed_topics_require_final_review(self):
        profile = apply_topic_updates(
            new_profile(PAGE_A, now=NOW_1),
            confirmed_topic_updates(),
            page_id=PAGE_A,
            trusted_buyer_confirmation=True,
            evidence={**BINDING, "chat_id": "42", "message_hash": "answers", "message_sequence": 10},
            now=NOW_2,
        )
        business_memory = embed_profile({}, profile)

        readiness = self.dashboard.strategic_business_profile_readiness(
            profile=business_memory,
            page_id=PAGE_A,
        )

        self.assertEqual(len(readiness["resolved_topics"]), 10)
        self.assertEqual(readiness["unresolved_topics"], [])
        self.assertEqual(readiness["revision"], 1)
        self.assertIsNone(readiness["confirmed_revision"])
        self.assertEqual(readiness["status"], "review_required")
        self.assertFalse(readiness["complete"])

    def test_trusted_final_confirmation_completes_current_revision(self):
        business_memory = embed_profile({}, reviewed_profile())

        readiness = self.dashboard.strategic_business_profile_readiness(
            profile=business_memory,
            page_id=PAGE_A,
        )

        self.assertEqual(readiness["status"], "complete")
        self.assertTrue(readiness["complete"])
        self.assertEqual(readiness["revision"], 1)
        self.assertEqual(readiness["confirmed_revision"], 1)

    def test_final_review_accepts_natural_confirmation_but_not_a_correction(self):
        natural_confirmations = (
            "Sí, está todo correcto para seguir",
            "Perfecto, así está bien",
            "Me parece bien el resumen",
            "No cambiaría nada, adelante",
        )
        for message in natural_confirmations:
            with self.subTest(message=message), patch.object(
                self.dashboard,
                "_trusted_buyer_turn",
                return_value={"message": message},
            ):
                confirmed, _turn = self.dashboard.trusted_profile_review_confirmation()
                self.assertTrue(confirmed)
        with patch.object(
            self.dashboard,
            "_trusted_buyer_turn",
            return_value={"message": "Está bien, pero cambia la ciudad a Medellín"},
        ):
            confirmed, _turn = self.dashboard.trusted_profile_review_confirmation()
        self.assertFalse(confirmed)

    def test_correction_invalidates_dashboard_completion(self):
        corrected = apply_topic_updates(
            reviewed_profile(),
            {
                "services": {
                    "value": ["Ortodoncia", "Diseño de sonrisa"],
                    "status": "confirmed",
                    "confirmation_state": "buyer_confirmed",
                }
            },
            page_id=PAGE_A,
            trusted_buyer_confirmation=True,
            evidence={"chat_id": "42", "message_hash": "correction"},
            now="2026-08-22T12:03:00+00:00",
        )

        readiness = self.dashboard.strategic_business_profile_readiness(
            profile=embed_profile({}, corrected),
            page_id=PAGE_A,
        )

        self.assertEqual(readiness["revision"], 2)
        self.assertIsNone(readiness["confirmed_revision"])
        self.assertEqual(readiness["status"], "review_required")
        self.assertFalse(readiness["complete"])

    def test_page_change_fails_closed_without_reinterpreting_business(self):
        business_memory = embed_profile({}, reviewed_profile(PAGE_A))

        readiness = self.dashboard.strategic_business_profile_readiness(
            profile=business_memory,
            page_id=PAGE_B,
        )
        decision = self.dashboard.strategic_product_action_eligibility(
            "campaign_create",
            profile=business_memory,
            page_id=PAGE_B,
        )

        self.assertEqual(readiness["status"], "scope_mismatch")
        self.assertFalse(readiness["complete"])
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["code"], "strategic_profile_scope_mismatch")


class StrategicProfileToolBridgeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.profile = new_profile(PAGE_A, now=NOW_1)
        self.dashboard = FakeDashboard(self.profile)

    def _call(self, tool, arguments):
        with patch.object(admira_tool_bridge, "load_dashboard", return_value=self.dashboard):
            return admira_tool_bridge.call_tool(tool, arguments)

    def test_mutations_are_blocked_before_compiler_or_product_provider(self):
        creator_args = {
            "name": "Must not compile",
            "brief_markdown": "A complete-looking campaign brief",
        }
        blocked_calls = [
            *[(tool, creator_args) for tool in sorted(admira_tool_bridge.CAMPAIGN_CREATION_TOOLS)],
            ("admira_save_ad_brief", {"objective": "MESSAGES"}),
            (
                "admira_codex_image_generate",
                {"request": "Paid ad image", "purpose": "ad_creative"},
            ),
            (
                "admira_codex_creative_plan",
                {"request": "Plan paid creative", "purpose": "paid_image"},
            ),
            (
                "admira_generate_motion_graphic_video",
                {"topic": "Offer", "objective": "Sales", "purpose": "ad_creative"},
            ),
            (
                "admira_edit_campaign",
                {"campaign_reference": "Miami", "change_request": "Change audience"},
            ),
            ("admira_resume_campaign", {"campaign_id": "1201"}),
            (
                "admira_schedule_campaign_activation",
                {"campaign_id": "1201", "scheduled_at": "2026-08-23T09:00:00-05:00"},
            ),
            (
                "admira_stage_budget_change",
                {"campaign_id": "1201", "budget_confirmation": "20 USD"},
            ),
        ]

        with patch.object(
            admira_tool_bridge,
            "compile_campaign_brief",
            side_effect=AssertionError("compiler must not run before onboarding"),
        ):
            for tool, arguments in blocked_calls:
                with self.subTest(tool=tool):
                    result = self._call(tool, arguments)
                    self.assertFalse(result["ok"])
                    self.assertTrue(result["blocked"])
                    self.assertFalse(result["executed"])
                    self.assertEqual(result["reason"], "strategic_profile_required")
                    self.assertEqual(result["profile_status"], "empty")
                    self.assertEqual(result["profile_revision"], 0)
                    self.assertIsNone(result["confirmed_revision"])

        self.assertEqual(self.dashboard.executions, [])

    def test_reads_oauth_onboarding_brand_and_safety_actions_remain_available(self):
        calls = [
            (
                "admira_search_meta_targeting",
                {"kind": "interest", "query": "odontología"},
            ),
            ("admira_get_meta_oauth_workspaces", {}),
            ("admira_start_meta_oauth_connection", {"channel": "telegram"}),
            (
                "admira_save_business_memory",
                {
                    "services": ["Diseño de sonrisa"],
                    "confirmation_state": "buyer_confirmed",
                },
            ),
            (
                "admira_save_product_memory",
                {"name": "Diseño de sonrisa", "benefit": "Mejorar la sonrisa"},
            ),
            (
                "admira_save_ads_onboarding",
                {"campaign_goal": "Captar valoraciones", "success_metrics": ["Leads"]},
            ),
            (
                "admira_save_brand_memory",
                {"brand_name": "Clínica", "tone": "Cercano"},
            ),
            ("admira_pause_campaign", {"campaign_id": "1201"}),
            ("admira_delete_campaign", {"campaign_id": "1201"}),
        ]

        for tool, arguments in calls:
            with self.subTest(tool=tool):
                result = self._call(tool, arguments)
                self.assertTrue(result["ok"])
                self.assertNotEqual(result.get("reason"), "strategic_profile_required")

        self.assertEqual(len(self.dashboard.read_calls), 1)
        self.assertEqual(len(self.dashboard.oauth_calls), 2)
        executed_product_tools = [item[0]["tool"] for item in self.dashboard.executions]
        self.assertIn("save_business_context", executed_product_tools)
        self.assertIn("save_product_guide", executed_product_tools)
        self.assertIn("save_ads_onboarding", executed_product_tools)
        self.assertIn("save_brand_guide", executed_product_tools)
        self.assertIn("pause_campaign", executed_product_tools)
        self.assertIn("delete_campaign", executed_product_tools)

    def test_moodboard_and_organic_media_purposes_are_not_blocked(self):
        calls = [
            (
                "admira_codex_image_generate",
                {"request": "Moodboard visual", "purpose": "moodboard"},
            ),
            (
                "admira_codex_creative_plan",
                {"request": "Explore brand direction", "purpose": "brand_exploration"},
            ),
            (
                "admira_generate_motion_graphic_video",
                {
                    "topic": "Tip de salud oral",
                    "objective": "Educación",
                    "purpose": "organic_social_post",
                },
            ),
        ]

        for tool, arguments in calls:
            with self.subTest(tool=tool):
                result = self._call(tool, arguments)
                self.assertTrue(result["ok"])
                self.assertNotEqual(result.get("reason"), "strategic_profile_required")

        self.assertEqual(len(self.dashboard.executions), 3)
        self.assertEqual(
            [item[0]["tool"] for item in self.dashboard.executions],
            ["codex_image_generate", "codex_creative_plan", "generate_motion_graphic_video"],
        )

    def test_old_paid_approval_cannot_bypass_incomplete_profile(self):
        self.dashboard.pending = [{
            "id": "approval-old-campaign",
            "type": "create_campaign",
            "status": "pending",
            "payload": {"name": "Old draft"},
        }]
        result = self._call(
            "admira_approve_action",
            {"approval_id": "approval-old-campaign"},
        )
        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])
        self.assertEqual(result["reason"], "strategic_profile_required")
        self.assertEqual(self.dashboard.executions, [])

    def test_completed_profile_opens_previously_gated_categories(self):
        complete = reviewed_profile()
        dashboard = FakeDashboard(complete)
        gated_examples = [
            ("admira_create_whatsapp_campaign", {"name": "Campaign"}),
            ("admira_edit_campaign", {"campaign_reference": "Campaign"}),
            ("admira_save_ad_brief", {"objective": "MESSAGES"}),
            ("admira_codex_image_generate", {"purpose": "ad_creative"}),
            ("admira_generate_motion_graphic_video", {"purpose": "ad_creative"}),
            ("admira_resume_campaign", {"campaign_id": "1201"}),
            ("admira_stage_budget_change", {"budget_confirmation": "20 USD"}),
        ]

        for tool, arguments in gated_examples:
            with self.subTest(tool=tool):
                self.assertIsNone(
                    admira_tool_bridge.strategic_profile_gate_result(
                        tool,
                        arguments,
                        dashboard,
                    )
                )


if __name__ == "__main__":
    unittest.main()
