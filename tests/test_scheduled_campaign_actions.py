#!/usr/bin/env python3
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import scheduled_campaign_actions as scheduled
import hermes_gateway


class ScheduledCampaignActionsTest(unittest.TestCase):
    def test_activation_is_exact_and_no_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            actions_file = base / "actions.json"
            scheduled_file = base / "scheduled.json"
            metrics_file = base / "metrics.json"
            actions_file.write_text(json.dumps([{
                "status": "completed",
                "payload": {
                    "name": "Campaña lista",
                    "result": {"executed": True, "campaign_id": "120250293867690096"},
                },
            }]), encoding="utf-8")
            metrics_file.write_text('{"campaigns": []}', encoding="utf-8")

            class FakeClient:
                def __init__(self, _config):
                    pass
                def campaign_details(self, _campaign_id):
                    return {"returncode": 0, "stdout": json.dumps({"id": "120250293867690096", "name": "Campaña lista", "status": "PAUSED"})}

            command = []
            def fake_run(args, **_kwargs):
                command.extend(args)
                return SimpleNamespace(returncode=0, stdout="Created job abcdef123456", stderr="")

            due = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            with patch.object(scheduled, "ACTIONS_FILE", actions_file), \
                 patch.object(scheduled, "SCHEDULED_ACTIONS_FILE", scheduled_file), \
                 patch.object(scheduled, "METRICS_FILE", metrics_file), \
                 patch.object(scheduled, "SocialFlowClient", FakeClient), \
                 patch.object(scheduled, "load_config", lambda: SimpleNamespace()), \
                 patch.object(scheduled.shutil, "which", lambda _name: "/usr/local/bin/hermes"), \
                 patch.object(scheduled.subprocess, "run", fake_run):
                result = scheduled.schedule_campaign_activation({
                    "campaign_name": "Campaña lista",
                    "scheduled_at": due,
                    "timezone": "America/Bogota",
                    "buyer_authorized": True,
                    "creative_ready_confirmed": True,
                }, base / "hermes-home", "12345")

            stored = json.loads(scheduled_file.read_text(encoding="utf-8"))["actions"][0]
            self.assertTrue(result["ok"])
            self.assertEqual(stored["campaign_id"], "120250293867690096")
            self.assertIn("--no-agent", command)
            self.assertIn("--script", command)
            self.assertNotIn("Campaña lista", command[-1])

    def test_activation_requires_authorization_and_final_creatives(self):
        self.assertEqual(scheduled.schedule_campaign_activation({}, "/tmp/none", "1")["reason"], "activation_authorization_required")
        self.assertEqual(scheduled.schedule_campaign_activation({"buyer_authorized": True}, "/tmp/none", "1")["reason"], "creative_readiness_confirmation_required")

    def test_due_activation_verifies_active_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            scheduled_file = base / "scheduled.json"
            actions_file = base / "actions.json"
            scheduled_file.write_text(json.dumps({"actions": [{
                "id": "scheduled_activation_test",
                "type": "activate_campaign",
                "status": "scheduled",
                "campaign_id": "120250293867690096",
                "campaign_name": "Campaña lista",
            }]}), encoding="utf-8")

            class FakeClient:
                calls = 0
                def __init__(self, _config):
                    pass
                def campaign_details(self, _campaign_id):
                    self.__class__.calls += 1
                    status = "PAUSED" if self.__class__.calls == 1 else "ACTIVE"
                    return {"returncode": 0, "stdout": json.dumps({"id": "120250293867690096", "name": "Campaña lista", "status": status})}
                def resume(self, target_type, target_id, approved=False):
                    self.last_resume = (target_type, target_id, approved)
                    return {"executed": True, "returncode": 0}

            config = SimpleNamespace(license_required_for_live=False)
            with patch.object(scheduled, "SCHEDULED_ACTIONS_FILE", scheduled_file), \
                 patch.object(scheduled, "ACTIONS_FILE", actions_file), \
                 patch.object(scheduled, "SocialFlowClient", FakeClient), \
                 patch.object(scheduled, "load_config", lambda: config):
                code = scheduled.run_scheduled_activation("scheduled_activation_test")

            record = json.loads(scheduled_file.read_text(encoding="utf-8"))["actions"][0]
            audit = json.loads(actions_file.read_text(encoding="utf-8"))[0]
            self.assertEqual(code, 0)
            self.assertEqual(record["status"], "completed")
            self.assertEqual(record["verified_status"], "ACTIVE")
            self.assertEqual(audit["status"], "completed")

    def test_cron_jobs_are_repinned_to_selected_model(self):
        captured = {}
        class Config:
            hermes_model = "gpt-5.6-luna"
            agent_brain_provider = "openai_codex"
            agent_chat_provider = "hermes"
            agent_chat_model = "gpt-5.6-luna"
            agent_chat_base_url = ""
            agent_chat_api_key = ""

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["env"] = kwargs["env"]
            return SimpleNamespace(returncode=0, stdout='{"ok":true,"updated":2}', stderr="")

        with patch.object(hermes_gateway, "hermes_brain_settings", lambda _config: {"brain": "chatgpt", "provider": "openai-codex", "model": "gpt-5.6-luna"}), \
             patch.object(hermes_gateway, "hermes_environment", lambda _config: os.environ.copy()), \
             patch.object(hermes_gateway.subprocess, "run", fake_run):
            result = hermes_gateway.reconcile_cron_inference_pins(Config(), {"hermes_home": "/tmp/hermes", "workspace": "/tmp/workspace"})

        self.assertEqual(result["updated"], 2)
        self.assertEqual(captured["env"]["ADMIRA_CRON_PIN_MODEL"], "gpt-5.6-luna")
        self.assertEqual(captured["env"]["ADMIRA_CRON_PIN_PROVIDER"], "openai-codex")
        self.assertIn("update_job", captured["command"][-1])


if __name__ == "__main__":
    unittest.main()
