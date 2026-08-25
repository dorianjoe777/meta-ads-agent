from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_dashboard():
    spec = importlib.util.spec_from_file_location(
        "business_lifecycle_invariants_dashboard_test",
        ROOT / "dashboard" / "monitoring-dashboard.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BusinessLifecycleInvariantTests(unittest.TestCase):
    """Regression coverage for the server-owned lifecycle boundaries.

    These tests deliberately exercise the dashboard module's public lifecycle
    helpers with the same trusted-turn/file helpers used by the gateway.  A
    model's wording must not be able to bypass the presentation binding,
    onboarding boundary, or direct-only plan-update rule.
    """

    def setUp(self):
        self.dashboard = load_dashboard()
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.file_patches = [
            patch.object(self.dashboard, "BUSINESS_PROFILE_FILE", root / "business.json"),
            patch.object(self.dashboard, "TRUSTED_BUYER_TURN_FILE", root / "turn.json"),
            patch.object(self.dashboard, "TRUSTED_BUYER_TURN_LOCK_FILE", root / "turn.lock"),
        ]
        for item in self.file_patches:
            item.start()
        self.common_patches = [
            patch.object(self.dashboard, "active_meta_page_id", return_value="page-1"),
            patch.object(self.dashboard, "load_config", return_value=SimpleNamespace(telegram_chat_id="123")),
            patch.object(self.dashboard, "write_onboarding_questions_memory", return_value={"status": "pending"}),
            patch.object(self.dashboard, "write_agent_onboarding_plan", return_value={}),
            patch.object(self.dashboard, "log_action"),
        ]
        for item in self.common_patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.common_patches):
            item.stop()
        for item in reversed(self.file_patches):
            item.stop()
        self.temp.cleanup()

    def _turn(self, sequence, message, session="session-1", chat="123"):
        return self.dashboard.record_trusted_buyer_turn(
            chat, session, sequence, message, transport="telegram"
        )

    def _complete_profile(self):
        profile = self.dashboard.new_strategic_profile("page-1")
        profile = self.dashboard.apply_strategic_profile_updates(
            profile,
            {
                topic: {
                    "status": "confirmed",
                    "value": topic,
                    "confirmation_state": "buyer_confirmed",
                }
                for topic in self.dashboard.STRATEGIC_PROFILE_TOPICS
            },
            page_id="page-1",
            trusted_buyer_confirmation=True,
            evidence={
                "chat_id": "123",
                "session_id": "session-1",
                "transport": "telegram",
                "message_sequence": 10,
            },
        )
        profile = self.dashboard.mark_strategic_profile_review_presented(
            profile,
            page_id="page-1",
            after_buyer_message_sequence=10,
            assistant_message_hash="review",
            evidence={
                "source": "finalized_outbound_transport",
                "chat_id": "123",
                "session_id": "session-1",
                "transport": "telegram",
                "message_sequence": 10,
                "trusted_server_evidence": True,
            },
        )
        profile = self.dashboard.confirm_strategic_profile_revision(
            profile,
            page_id="page-1",
            trusted_buyer_confirmation=True,
            evidence={
                "chat_id": "123",
                "session_id": "session-1",
                "transport": "telegram",
                "message_sequence": 11,
            },
        )
        return self.dashboard.embed_strategic_profile({}, profile)

    def _full_plan(self, value_prefix="value", nested=False):
        if nested:
            return {
                field: {"items": [f"{value_prefix}-{field}"], "enabled": True}
                for field in self.dashboard._MASTER_PLAN_FIELDS
            }
        return {
            field: f"{value_prefix}-{field}"
            for field in self.dashboard._MASTER_PLAN_FIELDS
        }

    def _proposed_plan(self, draft=None, *, presentation=None, status="proposed"):
        draft = draft or self._full_plan()
        presentation = presentation if presentation is not None else {}
        return {
            "status": status,
            "profile_revision": 1,
            "revision": 2,
            "draft": draft,
            "draft_hash": self.dashboard._plan_content_hash(draft),
            "draft_revision": 4,
            "presentation": presentation,
        }

    def _presented_plan(self, draft=None, *, sequence=20, draft_revision=4, draft_hash=None):
        draft = draft or self._full_plan()
        return self._proposed_plan(
            draft,
            presentation={
                "draft_hash": draft_hash or self.dashboard._plan_content_hash(draft),
                "draft_revision": draft_revision,
                "after_buyer_message_sequence": sequence,
                "chat_id": "123",
                "session_id": "session-1",
                "transport": "telegram",
            },
        )

    def _write_profile_with_plan(self, profile, plan):
        profile.setdefault("business_master_plans", {})["page-1"] = plan
        self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, profile)

    def test_revised_proposed_plan_renders_draft_not_old_confirmed_content(self):
        old = self._full_plan("old")
        new = self._full_plan("new")
        plan = self._proposed_plan(new)
        plan["content"] = old

        rendered = self.dashboard.render_business_strategic_plan(plan)

        self.assertIn("new-diagnosis", rendered)
        self.assertIn("new-roadmap", rendered)
        self.assertNotIn("old-diagnosis", rendered)
        self.assertNotIn("old-roadmap", rendered)

    def test_stale_or_mismatched_presentation_hash_or_revision_cannot_confirm(self):
        for mismatch in ("hash", "revision"):
            with self.subTest(mismatch=mismatch):
                profile = self._complete_profile()
                draft = self._full_plan()
                presented_hash = (
                    "stale-hash"
                    if mismatch == "hash"
                    else self.dashboard._plan_content_hash(draft)
                )
                presented_revision = 3 if mismatch == "revision" else 4
                plan = self._presented_plan(
                    draft,
                    sequence=20,
                    draft_revision=presented_revision,
                    draft_hash=presented_hash,
                )
                self._write_profile_with_plan(profile, plan)
                self._turn(21, "Sí, confirmo este plan")
                with patch.object(
                    self.dashboard,
                    "classify_lifecycle_transition",
                    return_value={"confirmation": "si", "reason": "test"},
                ):
                    result = self.dashboard.resolve_pending_business_lifecycle_transition(
                        target="strategic_plan"
                    )

                stored = self.dashboard.read_json(self.dashboard.BUSINESS_PROFILE_FILE, {})
                self.assertFalse(result["transitioned"])
                self.assertEqual(
                    stored["business_master_plans"]["page-1"]["status"],
                    "proposed",
                )

    def test_incomplete_draft_cannot_confirm(self):
        profile = self._complete_profile()
        draft = {"diagnosis": "Only one section"}
        plan = self._presented_plan(draft)
        self._write_profile_with_plan(profile, plan)
        self._turn(21, "Sí, confirmo este plan")
        with patch.object(
            self.dashboard,
            "classify_lifecycle_transition",
            return_value={"confirmation": "si", "reason": "test"},
        ):
            result = self.dashboard.resolve_pending_business_lifecycle_transition(
                target="strategic_plan"
            )

        self.assertFalse(result["transitioned"])
        self.assertEqual(
            self.dashboard.read_json(self.dashboard.BUSINESS_PROFILE_FILE, {})[
                "business_master_plans"
            ]["page-1"]["status"],
            "proposed",
        )

    def test_plan_cannot_confirm_before_onboarding_completes(self):
        profile = self.dashboard.new_strategic_profile("page-1")
        self._write_profile_with_plan(profile, self._presented_plan())
        self._turn(21, "Sí, confirmo este plan")
        with patch.object(
            self.dashboard,
            "classify_lifecycle_transition",
            return_value={"confirmation": "si", "reason": "test"},
        ):
            result = self.dashboard.resolve_pending_business_lifecycle_transition(
                target="strategic_plan"
            )

        self.assertFalse(result["transitioned"])
        self.assertEqual(result["state"], "onboarding")

    def test_completed_onboarding_cannot_be_reconfirmed_from_old_presentation(self):
        profile = self._complete_profile()
        self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, profile)
        self._turn(20, "Sí, confirmo el resumen otra vez")
        with patch.object(
            self.dashboard,
            "classify_lifecycle_transition",
            return_value={"confirmation": "si", "reason": "test"},
        ):
            result = self.dashboard.resolve_pending_business_lifecycle_transition(
                target="business_profile"
            )

        self.assertFalse(result["transitioned"])
        self.assertEqual(result["state"], "active_without_confirmed_strategic_plan")

    def test_structured_dict_list_plan_cannot_be_recorded_from_hola(self):
        profile = self._complete_profile()
        plan = self._proposed_plan(self._full_plan(nested=True))
        self._write_profile_with_plan(profile, plan)
        self._turn(20, "Propongo este plan estratégico")

        result = self.dashboard.record_business_lifecycle_artifact_presented(
            "session-1", "hola", "123", "strategic_plan"
        )

        self.assertFalse(result["recorded"])
        self.assertEqual(result["reason"], "plan_presentation_incomplete")

    def test_unrelated_budget_confirmation_with_media_is_not_replaced_by_plan(self):
        profile = self._complete_profile()
        plan = self._proposed_plan(self._full_plan())
        plan["update_authorization"] = {
            "buyer_message_hash": "a-different-turn",
            "chat_id": "123",
            "session_id": "session-1",
            "transport": "telegram",
        }
        self._write_profile_with_plan(profile, plan)
        self._turn(20, "¿Confirmar presupuesto diario de 50 USD?")
        output = "Confirmar presupuesto diario de 50 USD.\nMEDIA:/tmp/creative.png"

        result = self.dashboard.ensure_business_lifecycle_artifact_visible(
            output, "strategic_plan"
        )

        self.assertEqual(result, output)
        self.assertIn("MEDIA:/tmp/creative.png", result)
        self.assertNotIn("Plan estratégico del negocio", result)

    def test_same_turn_plan_proposal_is_canonicalized_once(self):
        profile = self._complete_profile()
        plan = self._proposed_plan(self._full_plan())
        turn = self._turn(20, "Prepara una propuesta de plan estratégico")
        plan["update_authorization"] = {
            "buyer_message_hash": turn["message_hash"],
            "chat_id": turn["chat_id"],
            "session_id": turn["session_id"],
            "transport": turn["transport"],
        }
        self._write_profile_with_plan(profile, plan)
        model_text = "Te presento una propuesta de plan estratégico para revisar."

        first = self.dashboard.ensure_business_lifecycle_artifact_visible(
            model_text, "strategic_plan"
        )
        second = self.dashboard.ensure_business_lifecycle_artifact_visible(
            first, "strategic_plan"
        )

        self.assertEqual(first, second)
        self.assertEqual(first.count("Esta es una propuesta inicial"), 1)
        self.assertEqual(first.count("Plan estratégico del negocio"), 1)
        self.assertIn("value-diagnosis", first)


if __name__ == "__main__":
    unittest.main()
