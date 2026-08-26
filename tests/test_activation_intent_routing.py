import json
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from activation_intent_classifier import classify_activation_intent


def load_dashboard():
    spec = importlib.util.spec_from_file_location(
        "activation_intent_dashboard_test", ROOT / "dashboard" / "monitoring-dashboard.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ActivationIntentRoutingTest(unittest.TestCase):
    def setUp(self):
        self.dashboard = load_dashboard()
        self.temp = tempfile.TemporaryDirectory()
        data = Path(self.temp.name)
        self.patches = [
            patch.object(self.dashboard, "METRICS_FILE", data / "metrics.json"),
            patch.object(self.dashboard, "TRUSTED_BUYER_TURN_FILE", data / "trusted-turn.json"),
            patch.object(self.dashboard, "TRUSTED_BUYER_TURN_LOCK_FILE", data / "trusted-turn.lock"),
            patch.object(
                self.dashboard,
                "load_config",
                return_value=SimpleNamespace(
                    ad_account_id="act_123",
                    telegram_chat_id="123",
                    license_required_for_live=False,
                ),
            ),
        ]
        for item in self.patches:
            item.start()
        (data / "metrics.json").write_text(json.dumps({"campaigns": []}), encoding="utf-8")

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def _turn(self, message, sequence=1):
        return self.dashboard.record_trusted_buyer_turn(
            "123", "session-1", sequence, message, transport="telegram"
        )

    def _resume_client(self):
        dashboard = self.dashboard

        class FakeClient:
            details_calls = []
            graph_calls = []
            resume_calls = []

            def __init__(self, _config):
                pass

            def campaign_details(self, campaign_id):
                self.__class__.details_calls.append(str(campaign_id))
                status = "PAUSED" if len(self.__class__.details_calls) == 1 else "ACTIVE"
                body = {"id": str(campaign_id), "name": "Campaña exacta", "status": status}
                return {
                    "ok": True,
                    "returncode": 0,
                    "status": 200,
                    "stdout": json.dumps(body),
                    "body": body,
                }

            def get_graph(self, endpoint, params=None, access_token=""):
                self.__class__.graph_calls.append((str(endpoint), dict(params or {})))
                return {"ok": True, "status": 200, "body": {"id": str(endpoint), "account_id": "act_123"}}

            def resume(self, target_type, target_id, approved=False):
                self.__class__.resume_calls.append((target_type, str(target_id), approved))
                return {
                    "ok": True,
                    "executed": True,
                    "returncode": 0,
                    "status": 200,
                    "body": {"id": str(target_id), "status": "ACTIVE"},
                }

        return FakeClient

    def test_empty_cache_exact_id_trusted_immediate_resumes_once_and_reads_active(self):
        fake = self._resume_client()
        self._turn("Si actívala")
        with patch.object(self.dashboard, "SocialFlowClient", fake), patch.object(
            self.dashboard, "classify_activation_intent", return_value={"ok": True, "intent": "immediate"}
        ):
            result = self.dashboard.handle_campaign_mutation_tool(
                {"campaign_id": "120000000000001", "active_spend_confirmed": True}, {}, "resume_campaign"
            )

        self.assertTrue(result["executed"])
        self.assertEqual(fake.resume_calls, [("campaign", "120000000000001", True)])
        self.assertEqual(fake.details_calls, ["120000000000001", "120000000000001"])
        self.assertEqual(fake.graph_calls, [("120000000000001", {"fields": "id,name,account_id"})])
        self.assertEqual(result["receipt"]["configured_status"], "ACTIVE")

    def test_campaign_from_different_account_is_blocked_without_resume(self):
        fake = self._resume_client()

        class WrongAccountClient(fake):
            def get_graph(self, endpoint, params=None, access_token=""):
                self.__class__.graph_calls.append((str(endpoint), dict(params or {})))
                return {"ok": True, "status": 200, "body": {"id": str(endpoint), "account_id": "act_other"}}

        self._turn("Si actívala")
        with patch.object(self.dashboard, "SocialFlowClient", WrongAccountClient), patch.object(
            self.dashboard, "classify_activation_intent", return_value={"ok": True, "intent": "immediate"}
        ):
            result = self.dashboard.handle_campaign_mutation_tool(
                {"campaign_id": "120000000000001", "active_spend_confirmed": True}, {}, "resume_campaign"
            )
        self.assertFalse(result["executed"])
        self.assertEqual(result["reason"], "campaign_not_in_active_ad_account")
        self.assertEqual(WrongAccountClient.resume_calls, [])

    def test_future_or_unknown_classifier_blocks_resume(self):
        for intent, message in (("future", "Actívala mañana"), ("unknown", "sí")):
            with self.subTest(intent=intent):
                fake = self._resume_client()
                self._turn(message, sequence=2 if intent == "unknown" else 1)
                with patch.object(self.dashboard, "SocialFlowClient", fake), patch.object(
                    self.dashboard, "classify_activation_intent", return_value={"ok": True, "intent": intent}
                ):
                    result = self.dashboard.handle_campaign_mutation_tool(
                        {"campaign_id": "120000000000001", "active_spend_confirmed": True}, {}, "resume_campaign"
                    )
                self.assertFalse(result["executed"])
                self.assertEqual(result["reason"], "activation_intent_not_immediate")
                self.assertEqual(fake.resume_calls, [])

    def test_schedule_with_immediate_turn_never_calls_scheduler(self):
        self._turn("Si actívala")
        with patch.object(self.dashboard, "classify_activation_intent", return_value={"ok": True, "intent": "immediate"}), patch.object(
            self.dashboard, "schedule_campaign_activation"
        ) as scheduler:
            result = self.dashboard.handle_schedule_campaign_activation_tool(
                {"schedule_request_evidence": "Si actívala"}, {}, "schedule_campaign_activation"
            )
        self.assertFalse(result["executed"])
        scheduler.assert_not_called()

    def test_schedule_with_invented_evidence_never_calls_scheduler(self):
        self._turn("Actívala mañana a las 9")
        with patch.object(self.dashboard, "classify_activation_intent", return_value={"ok": True, "intent": "future"}), patch.object(
            self.dashboard, "schedule_campaign_activation"
        ) as scheduler:
            result = self.dashboard.handle_schedule_campaign_activation_tool(
                {"schedule_request_evidence": "Actívala el viernes a las 9"}, {}, "schedule_campaign_activation"
            )
        self.assertFalse(result["executed"])
        scheduler.assert_not_called()

    def test_future_turn_with_literal_evidence_calls_scheduler_once(self):
        message = "Actívala mañana a las 9"
        self._turn(message)
        with patch.object(self.dashboard, "classify_activation_intent", return_value={"ok": True, "intent": "future"}), patch.object(
            self.dashboard, "telegram_settings", return_value={"chat_id": "123", "hermes_home": "/tmp/hermes"}
        ), patch.object(
            self.dashboard,
            "schedule_campaign_activation",
            return_value={"ok": True, "campaign_name": "Campaña exacta", "scheduled_at": "2026-08-27T09:00:00"},
        ) as scheduler:
            result = self.dashboard.handle_schedule_campaign_activation_tool(
                {
                    "campaign_id": "120000000000001",
                    "scheduled_at": "2026-08-27T09:00:00",
                    "schedule_request_evidence": message,
                    "buyer_authorized": True,
                    "creative_ready_confirmed": True,
                },
                {},
                "schedule_campaign_activation",
            )
        self.assertTrue(result["executed"])
        scheduler.assert_called_once()
    def test_natural_immediate_language(self):
        result = classify_activation_intent("Si actívala", config={"llm": lambda *a, **k: {"intent": "immediate"}})
        self.assertEqual(result["intent"], "immediate")

    def test_explicit_future_language(self):
        result = classify_activation_intent("Actívala en la fecha acordada", config={"llm": lambda *a, **k: {"intent": "future"}})
        self.assertEqual(result["intent"], "future")

    def test_bare_or_conflicting_language_fails_closed(self):
        result = classify_activation_intent("sí", config={"llm": lambda *a, **k: {"intent": "unknown"}})
        self.assertEqual(result["intent"], "unknown")
        malformed = classify_activation_intent("sí", config={"llm": lambda *a, **k: {"intent": "bogus"}})
        self.assertFalse(malformed["ok"])


if __name__ == "__main__":
    unittest.main()
