from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_dashboard():
    spec = importlib.util.spec_from_file_location(
        "trusted_memory_dashboard_test",
        ROOT / "dashboard" / "monitoring-dashboard.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TrustedMemoryAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.dashboard = load_dashboard()
        self.temp = tempfile.TemporaryDirectory()
        data = Path(self.temp.name)
        self.patches = [
            patch.object(self.dashboard, "TRUSTED_BUYER_TURN_FILE", data / "trusted-turn.json"),
            patch.object(self.dashboard, "TRUSTED_BUYER_TURN_LOCK_FILE", data / "trusted-turn.lock"),
            patch.object(self.dashboard, "META_OAUTH_SELECTION_AUTH_FILE", data / "selection-auth.json"),
            patch.object(self.dashboard, "META_OAUTH_SELECTION_KEY_FILE", data / "selection-auth.key"),
            patch.object(self.dashboard, "META_OAUTH_CONNECTION_FILE", data / "connection.json"),
            patch.object(self.dashboard, "BUSINESS_PROFILE_FILE", data / "business-profile.json"),
            patch.object(self.dashboard, "MEMORY_DRAFTS_FILE", data / "memory-drafts.json"),
        ]
        for item in self.patches:
            item.start()
        self.config = SimpleNamespace(
            telegram_chat_id="123",
            telegram_bot_token="bot-token",
            meta_oauth_broker_url="https://admiraia.uboost.lat/api/meta-oauth",
            meta_access_token="",
            meta_access_token_kind="",
        )
        self.common = [
            patch.object(self.dashboard, "load_config", return_value=self.config),
            patch.object(self.dashboard, "active_meta_page_id", return_value="page_1"),
            patch.object(self.dashboard, "write_onboarding_questions_memory", return_value={"status": "pending"}),
            patch.object(self.dashboard, "write_agent_onboarding_plan", return_value={"path": "memory/plan.md"}),
            patch.object(self.dashboard, "log_action"),
        ]
        for item in self.common:
            item.start()

    def tearDown(self):
        for item in reversed(self.common):
            item.stop()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_dashboard_and_simulated_transports_replace_telegram_evidence(self):
        dashboard_turn = self.dashboard.record_trusted_buyer_turn(
            "dashboard:buyer-7",
            "agent:main:dashboard:buyer-7",
            10,
            "Vendemos diseño de sonrisa",
            transport="dashboard",
        )
        self.assertTrue(dashboard_turn["recorded"])
        self.assertEqual(dashboard_turn["transport"], "dashboard")

        simulated_turn = self.dashboard.record_trusted_buyer_turn(
            "simulated_telegram:case-4",
            "agent:main:simulated_telegram:case-4",
            11,
            "Atendemos en Cartagena",
            transport="simulated_telegram",
        )
        self.assertTrue(simulated_turn["recorded"])
        stored = self.dashboard.read_json(self.dashboard.TRUSTED_BUYER_TURN_FILE, {})
        self.assertEqual(stored["transport"], "simulated_telegram")
        self.assertEqual(stored["message"], "Atendemos en Cartagena")

    def test_failed_capture_clears_prior_evidence(self):
        self.dashboard.record_trusted_buyer_turn(
            "123", "agent:main:telegram:dm:123", 20, "Somos una clínica", transport="telegram"
        )
        with self.assertRaises(ValueError):
            self.dashboard.record_trusted_buyer_turn(
                "wrong-prefix",
                "agent:main:dashboard:buyer",
                21,
                "texto nuevo",
                transport="dashboard",
            )
        self.assertEqual(
            self.dashboard.read_json(self.dashboard.TRUSTED_BUYER_TURN_FILE, {}),
            {},
        )

    def test_current_exact_turn_is_one_use_and_replay_becomes_visible_draft(self):
        message = "Ofrecemos diseño de sonrisa y ortodoncia"
        self.dashboard.record_trusted_buyer_turn(
            "123", "agent:main:telegram:dm:123", 30, message, transport="telegram"
        )
        payload = {
            "confirmation_state": "buyer_confirmed",
            "buyer_evidence": message,
            "services": ["Diseño de sonrisa", "Ortodoncia"],
        }
        first = self.dashboard.save_business_context(payload)
        self.assertTrue(first["saved"])
        self.assertFalse(first["draft"])

        replay = self.dashboard.save_business_context(payload)
        self.assertFalse(replay["saved"])
        self.assertTrue(replay["draft"])
        self.assertIn("already_used", replay["reason"])

    def test_greeting_or_mismatched_evidence_cannot_create_official_fact(self):
        self.dashboard.record_trusted_buyer_turn(
            "123", "agent:main:telegram:dm:123", 40, "hola", transport="telegram"
        )
        greeting = self.dashboard.save_business_context({
            "confirmation_state": "buyer_confirmed",
            "buyer_evidence": "hola",
            "services": ["Inventado por el modelo"],
        })
        self.assertFalse(greeting["saved"])
        self.assertTrue(greeting["draft"])
        self.assertEqual(greeting["reason"], "buyer_message_does_not_confirm_memory")

        message = "Vendemos implantes dentales"
        self.dashboard.record_trusted_buyer_turn(
            "123", "agent:main:telegram:dm:123", 41, message, transport="telegram"
        )
        mismatch = self.dashboard.save_business_context({
            "confirmation_state": "buyer_confirmed",
            "buyer_evidence": "Vendemos ortodoncia",
            "services": ["Ortodoncia"],
        })
        self.assertFalse(mismatch["saved"])
        self.assertTrue(mismatch["draft"])
        self.assertEqual(mismatch["reason"], "buyer_evidence_not_exact_current_message")

    def test_short_natural_confirmation_only_promotes_matching_draft(self):
        proposal = {
            "confirmation_state": "agent_proposal",
            "buyer_evidence": "",
            "services": ["Diseño de sonrisa"],
        }
        draft = self.dashboard.save_business_context(proposal)
        self.assertTrue(draft["draft"])

        confirmation = "Sí, está bien"
        self.dashboard.record_trusted_buyer_turn(
            "123", "agent:main:telegram:dm:123", 50, confirmation, transport="telegram"
        )
        approved = self.dashboard.save_business_context({
            "confirmation_state": "buyer_confirmed",
            "buyer_evidence": confirmation,
            "services": ["Diseño de sonrisa"],
        })
        self.assertTrue(approved["saved"])
        self.assertFalse(approved["draft"])

        self.dashboard.record_trusted_buyer_turn(
            "123", "agent:main:telegram:dm:123", 51, "Perfecto", transport="telegram"
        )
        changed = self.dashboard.save_business_context({
            "confirmation_state": "buyer_confirmed",
            "buyer_evidence": "Perfecto",
            "services": ["Servicio distinto no mostrado"],
        })
        self.assertFalse(changed["saved"])
        self.assertTrue(changed["draft"])
        self.assertEqual(changed["reason"], "short_confirmation_has_no_matching_draft")

    def test_review_presentation_requires_every_current_label_status_and_value(self):
        updates = {
            topic: {
                "status": "confirmed",
                "value": f"Valor real {topic}",
                "confirmation_state": "buyer_confirmed",
            }
            for topic in self.dashboard.STRATEGIC_PROFILE_TOPICS
        }
        strategic = self.dashboard.apply_strategic_profile_updates(
            self.dashboard.new_strategic_profile("page_1"),
            updates,
            page_id="page_1",
            trusted_buyer_confirmation=True,
            evidence={
                "chat_id": "123",
                "session_id": "agent:main:telegram:dm:123",
                "transport": "telegram",
                "message_sequence": 60,
            },
        )
        profile = self.dashboard.embed_strategic_profile({}, strategic)
        self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, profile)
        self.dashboard.record_trusted_buyer_turn(
            "123", "agent:main:telegram:dm:123", 60, "Último dato", transport="telegram"
        )

        labels_only = "\n".join(self.dashboard._STRATEGIC_REVIEW_LABELS.values())
        rejected = self.dashboard.record_strategic_review_presented(
            "agent:main:telegram:dm:123", labels_only, chat_id="123"
        )
        self.assertFalse(rejected["recorded"])
        self.assertEqual(rejected["reason"], "review_summary_incomplete")

        canonical = self.dashboard.strategic_profile_review_summary(strategic)
        accepted = self.dashboard.record_strategic_review_presented(
            "agent:main:telegram:dm:123", canonical, chat_id="123"
        )
        self.assertTrue(accepted["recorded"])


if __name__ == "__main__":
    unittest.main()
