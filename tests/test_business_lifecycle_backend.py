from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_dashboard():
    spec = importlib.util.spec_from_file_location("business_lifecycle_dashboard_test", ROOT / "dashboard" / "monitoring-dashboard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BusinessLifecycleBackendTests(unittest.TestCase):
    def setUp(self):
        self.dashboard = load_dashboard()
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.files = [
            patch.object(self.dashboard, "BUSINESS_PROFILE_FILE", root / "business.json"),
            patch.object(self.dashboard, "TRUSTED_BUYER_TURN_FILE", root / "turn.json"),
            patch.object(self.dashboard, "TRUSTED_BUYER_TURN_LOCK_FILE", root / "turn.lock"),
        ]
        for item in self.files:
            item.start()
        self.common = [
            patch.object(self.dashboard, "active_meta_page_id", return_value="page-1"),
            patch.object(self.dashboard, "load_config", return_value=SimpleNamespace(telegram_chat_id="123")),
            patch.object(self.dashboard, "write_onboarding_questions_memory", return_value={"status": "pending"}),
            patch.object(self.dashboard, "write_agent_onboarding_plan", return_value={}),
            patch.object(self.dashboard, "log_action"),
        ]
        for item in self.common:
            item.start()

    def tearDown(self):
        for item in reversed(self.common):
            item.stop()
        for item in reversed(self.files):
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
            {topic: {"status": "confirmed", "value": topic, "confirmation_state": "buyer_confirmed"} for topic in self.dashboard.STRATEGIC_PROFILE_TOPICS},
            page_id="page-1", trusted_buyer_confirmation=True,
            evidence={"chat_id": "123", "session_id": "session-1", "transport": "telegram", "message_sequence": 10},
        )
        profile = self.dashboard.mark_strategic_profile_review_presented(
            profile, page_id="page-1", after_buyer_message_sequence=10,
            assistant_message_hash="review", evidence={
                "source": "finalized_outbound_transport", "chat_id": "123",
                "session_id": "session-1", "transport": "telegram", "message_sequence": 10,
                "trusted_server_evidence": True,
            },
        )
        profile = self.dashboard.confirm_strategic_profile_revision(
            profile, page_id="page-1", trusted_buyer_confirmation=True,
            evidence={"chat_id": "123", "session_id": "session-1", "transport": "telegram", "message_sequence": 11},
        )
        return self.dashboard.embed_strategic_profile({}, profile)

    def test_current_review_is_named_business_summary_and_partial_artifact_is_replaced(self):
        profile = self._complete_profile()
        # A fresh complete imported profile can still need a review boundary.
        strategic = self.dashboard.strategic_profile_for_page(profile, "page-1")
        strategic["review_confirmation"] = None
        strategic["confirmed_revision"] = None
        strategic["status"] = "review_required"
        profile = self.dashboard.embed_strategic_profile({}, strategic)
        self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, profile)
        text = "Resumen estratégico de Rodeo. ¿Confirmas estos datos?"
        output = self.dashboard.ensure_canonical_strategic_review_visible(text)
        self.assertIn("Resumen del negocio — revisión", output)
        self.assertNotIn("Resumen estratégico de Rodeo", output)

    def test_lifecycle_states_are_explicit(self):
        self.assertEqual(self.dashboard.business_lifecycle_state({}, "page-1"), "onboarding")
        profile = self._complete_profile()
        self.assertEqual(self.dashboard.business_lifecycle_state(profile, "page-1"), "active_without_confirmed_strategic_plan")
        profile["business_master_plans"] = {"page-1": {
            "status": "confirmed", "profile_revision": 1, "revision": 1,
            "content": {field: f"value-{field}" for field in self.dashboard._MASTER_PLAN_FIELDS},
        }}
        self.assertEqual(self.dashboard.business_lifecycle_state(profile, "page-1"), "active_with_confirmed_strategic_plan")

    def test_new_business_fact_does_not_invalidate_confirmed_plan(self):
        profile = self._complete_profile()
        profile["business_master_plans"] = {"page-1": {
            "status": "confirmed", "profile_revision": 1, "revision": 1,
            "content": {field: f"value-{field}" for field in self.dashboard._MASTER_PLAN_FIELDS},
        }}
        strategic = self.dashboard.strategic_profile_for_page(profile, "page-1")
        strategic = self.dashboard.apply_strategic_profile_updates(
            strategic,
            {"services": {
                "status": "confirmed", "value": ["Servicio nuevo"],
                "confirmation_state": "buyer_confirmed",
            }},
            page_id="page-1", trusted_buyer_confirmation=True,
            evidence={"chat_id": "123", "session_id": "session-1", "transport": "telegram", "message_sequence": 30},
        )
        profile = self.dashboard.embed_strategic_profile(profile, strategic)

        readiness = self.dashboard.business_master_plan_readiness(profile, "page-1")

        self.assertEqual(readiness["status"], "confirmed")
        self.assertTrue(readiness["ready"])
        self.assertEqual(profile["business_master_plans"]["page-1"]["profile_revision"], 1)

    def test_partial_plan_cannot_become_ready(self):
        profile = self._complete_profile()
        profile["business_master_plans"] = {"page-1": {
            "status": "confirmed", "profile_revision": 1, "revision": 1,
            "content": {"diagnosis": "Solo diagnóstico"},
        }}

        readiness = self.dashboard.business_master_plan_readiness(profile, "page-1")

        self.assertFalse(readiness["ready"])
        self.assertIn("next_steps_and_questions", readiness["missing_fields"])

    def test_plan_submission_is_always_proposed_and_same_turn_cannot_confirm(self):
        profile = self._complete_profile()
        self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, profile)
        self._turn(20, "Quiero guardar este plan")
        payload = {"master_plan": {field: f"value-{field}" for field in self.dashboard._MASTER_PLAN_FIELDS}, "confirmation_state": "buyer_confirmed", "buyer_evidence": "Quiero guardar este plan"}
        result = self.dashboard.save_business_context(payload)
        self.assertEqual(result["master_plan"]["status"], "proposed")
        self.assertFalse(result["master_plan"]["ready"])

    def test_plan_presentation_then_natural_later_confirmation_is_idempotent(self):
        profile = self._complete_profile()
        self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, profile)
        self._turn(20, "Propongo este plan")
        plan = {field: f"value-{field}" for field in self.dashboard._MASTER_PLAN_FIELDS}
        self.dashboard.save_business_context({"master_plan": plan, "confirmation_state": "agent_proposal"})
        self._turn(21, "Lo revisé; me parece genial, podemos seguir")
        stored = self.dashboard.read_json(self.dashboard.BUSINESS_PROFILE_FILE, {})
        rendered = self.dashboard.render_business_strategic_plan(stored["business_master_plans"]["page-1"])
        shown = self.dashboard.record_business_lifecycle_artifact_presented("session-1", rendered, "123", "strategic_plan")
        self.assertTrue(shown["recorded"])
        self._turn(22, "Sí, confirmo y sigamos con esto")
        transitioned = self.dashboard.resolve_pending_business_lifecycle_transition(target="strategic_plan")
        self.assertTrue(transitioned["transitioned"])
        replay = self.dashboard.resolve_pending_business_lifecycle_transition(target="strategic_plan")
        self.assertFalse(replay["transitioned"])
        self.assertEqual(self.dashboard.business_lifecycle_state(self.dashboard.read_json(self.dashboard.BUSINESS_PROFILE_FILE, {}), "page-1"), "active_with_confirmed_strategic_plan")

    def test_correction_does_not_transition_and_classifier_failure_fails_closed(self):
        with patch.object(self.dashboard, "classify_lifecycle_transition", side_effect=RuntimeError("down")):
            confirmed, reason = self.dashboard._lifecycle_confirmation("strategic_plan", "plan", "Me gusta, pero cambia el presupuesto")
        self.assertFalse(confirmed)
        self.assertIn(reason, {"classifier_error", "not_confirmed"})

    def test_render_includes_all_master_plan_fields(self):
        rendered = self.dashboard.render_business_strategic_plan({"status": "proposed", "draft": {field: field for field in self.dashboard._MASTER_PLAN_FIELDS}})
        for field in self.dashboard._MASTER_PLAN_FIELDS:
            self.assertIn(self.dashboard._MASTER_PLAN_LABELS[field], rendered)

    def test_new_fact_and_spontaneous_model_plan_do_not_change_confirmed_plan(self):
        profile = self._complete_profile()
        original = {field: f"original-{field}" for field in self.dashboard._MASTER_PLAN_FIELDS}
        profile["business_master_plans"] = {"page-1": {
            "status": "confirmed", "profile_revision": 1, "revision": 3,
            "content": original,
        }}
        self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, profile)
        self._turn(30, "También comenzamos a ofrecer lavado de motor")
        changed = {field: f"changed-{field}" for field in self.dashboard._MASTER_PLAN_FIELDS}
        with patch.object(
            self.dashboard,
            "classify_strategic_plan_update_request",
            return_value={"confirmation": "no", "reason": "classified"},
        ):
            result = self.dashboard.save_business_context({
                "master_plan": changed,
                "confirmation_state": "agent_proposal",
            })

        stored = self.dashboard.read_json(self.dashboard.BUSINESS_PROFILE_FILE, {})
        self.assertEqual(result["master_plan_operation_reason"], "strategic_plan_update_not_requested")
        self.assertEqual(stored["business_master_plans"]["page-1"]["status"], "confirmed")
        self.assertEqual(stored["business_master_plans"]["page-1"]["content"], original)
        self.assertNotIn("draft", stored["business_master_plans"]["page-1"])

    def test_direct_plan_update_opens_revision_but_preserves_last_confirmed_content(self):
        profile = self._complete_profile()
        original = {field: f"original-{field}" for field in self.dashboard._MASTER_PLAN_FIELDS}
        profile["business_master_plans"] = {"page-1": {
            "status": "confirmed", "profile_revision": 1, "revision": 3,
            "content": original,
        }}
        self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, profile)
        message = "Actualiza nuestro plan estratégico para incluir el nuevo servicio de motor"
        self._turn(31, message)
        changed = {field: f"changed-{field}" for field in self.dashboard._MASTER_PLAN_FIELDS}
        with patch.object(
            self.dashboard,
            "classify_strategic_plan_update_request",
            return_value={"confirmation": "si", "reason": "classified"},
        ):
            result = self.dashboard.save_business_context({
                "master_plan": changed,
                "confirmation_state": "agent_proposal",
            })

        stored = self.dashboard.read_json(self.dashboard.BUSINESS_PROFILE_FILE, {})
        revised = stored["business_master_plans"]["page-1"]
        self.assertEqual(result["master_plan_operation_reason"], "explicit_buyer_plan_update_request")
        self.assertEqual(revised["status"], "proposed")
        self.assertEqual(revised["draft"], changed)
        self.assertEqual(revised["content"], original)

    def test_one_buyer_turn_cannot_authorize_multiple_different_plan_revisions(self):
        profile = self._complete_profile()
        original = {field: f"original-{field}" for field in self.dashboard._MASTER_PLAN_FIELDS}
        profile["business_master_plans"] = {"page-1": {
            "status": "confirmed", "profile_revision": 1, "revision": 3,
            "content": original,
        }}
        self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, profile)
        message = "Actualiza el plan estratégico para priorizar el servicio Premium"
        self._turn(33, message)
        first = {field: f"first-{field}" for field in self.dashboard._MASTER_PLAN_FIELDS}
        second = {field: f"second-{field}" for field in self.dashboard._MASTER_PLAN_FIELDS}
        with patch.object(
            self.dashboard,
            "classify_strategic_plan_update_request",
            return_value={"confirmation": "si", "reason": "classified"},
        ):
            accepted = self.dashboard.save_business_context({
                "master_plan": first, "confirmation_state": "agent_proposal",
            })
            rejected = self.dashboard.save_business_context({
                "master_plan": second, "confirmation_state": "agent_proposal",
            })

        stored = self.dashboard.read_json(self.dashboard.BUSINESS_PROFILE_FILE, {})
        revised = stored["business_master_plans"]["page-1"]
        self.assertEqual(accepted["master_plan_operation_reason"], "explicit_buyer_plan_update_request")
        self.assertEqual(rejected["master_plan_operation_reason"], "strategic_plan_update_not_requested")
        self.assertEqual(revised["draft"], first)
        self.assertEqual(revised["content"], original)

    def test_external_plan_classifier_cannot_revert_concurrent_profile_write(self):
        profile = self._complete_profile()
        original = {field: f"original-{field}" for field in self.dashboard._MASTER_PLAN_FIELDS}
        profile["business_master_plans"] = {"page-1": {
            "status": "confirmed", "profile_revision": 1, "revision": 3,
            "content": original,
        }}
        self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, profile)
        self._turn(34, "Actualiza el plan estratégico para incluir fidelización")
        changed = {field: f"changed-{field}" for field in self.dashboard._MASTER_PLAN_FIELDS}

        def concurrent_write(*_args, **_kwargs):
            latest = self.dashboard.read_json(self.dashboard.BUSINESS_PROFILE_FILE, {})
            latest["concurrent_marker"] = "must-survive"
            self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, latest)
            return {"confirmation": "si", "reason": "classified"}

        with patch.object(
            self.dashboard,
            "classify_strategic_plan_update_request",
            side_effect=concurrent_write,
        ):
            self.dashboard.save_business_context({
                "master_plan": changed, "confirmation_state": "agent_proposal",
            })

        stored = self.dashboard.read_json(self.dashboard.BUSINESS_PROFILE_FILE, {})
        self.assertEqual(stored["concurrent_marker"], "must-survive")
        self.assertEqual(stored["business_master_plans"]["page-1"]["draft"], changed)

    def test_incomplete_initial_plan_is_not_persisted(self):
        profile = self._complete_profile()
        self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, profile)
        self._turn(32, "Muéstrame tu propuesta de plan")
        result = self.dashboard.save_business_context({
            "master_plan": {"advertising_opportunity": "Oportunidad solamente"},
            "confirmation_state": "agent_proposal",
        })
        stored = self.dashboard.read_json(self.dashboard.BUSINESS_PROFILE_FILE, {})
        self.assertTrue(result["master_plan_operation_reason"].startswith("strategic_plan_incomplete:"))
        self.assertFalse((stored.get("business_master_plans") or {}).get("page-1"))

    def test_transition_compare_and_swap_rejects_changed_turn(self):
        profile = self._complete_profile()
        plan = {field: f"value-{field}" for field in self.dashboard._MASTER_PLAN_FIELDS}
        profile["business_master_plans"] = {"page-1": {
            "status": "proposed", "profile_revision": 1,
            "draft": plan, "draft_hash": self.dashboard._plan_content_hash(plan),
            "draft_revision": 1,
            "presentation": {
                "draft_hash": self.dashboard._plan_content_hash(plan),
                "draft_revision": 1,
                "after_buyer_message_sequence": 40,
                "chat_id": "123", "session_id": "session-1", "transport": "telegram",
            },
        }}
        self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, profile)
        self._turn(41, "El plan presentado refleja exactamente lo que acordamos y podemos continuar")

        def replace_turn(*args, **kwargs):
            self._turn(42, "Mensaje posterior distinto")
            return {"confirmation": "si", "reason": "classified"}

        with patch.object(self.dashboard, "classify_lifecycle_transition", side_effect=replace_turn):
            result = self.dashboard.resolve_pending_business_lifecycle_transition(target="strategic_plan")
        stored = self.dashboard.read_json(self.dashboard.BUSINESS_PROFILE_FILE, {})
        self.assertFalse(result["transitioned"])
        self.assertEqual(result["reason"], "lifecycle_compare_and_swap_failed")
        self.assertEqual(stored["business_master_plans"]["page-1"]["status"], "proposed")


if __name__ == "__main__":
    unittest.main()
