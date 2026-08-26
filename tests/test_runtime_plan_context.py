"""Offline contracts for runtime lifecycle context and daily-plan guidance."""

import importlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "src", ROOT / "dashboard"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

runtime = importlib.import_module("admira_hermes_runtime_patch")
gateway = importlib.import_module("hermes_gateway")


class RuntimePlanContextTests(unittest.TestCase):
    PLAN_FIELDS = (
        "advertising_opportunity", "audience_and_message",
        "campaign_and_creative_plan", "budget_and_measurement",
        "next_steps_and_questions",
    )

    def _root(self, profile):
        root = Path(tempfile.mkdtemp())
        data = root / "dashboard" / "data"
        data.mkdir(parents=True)
        (data / "business_profile.json").write_text(json.dumps(profile), encoding="utf-8")
        return root

    @classmethod
    def _profile(cls, plan=None):
        if isinstance(plan, dict):
            plan = dict(plan)
            content_key = "content" if str(plan.get("status")) == "confirmed" else "draft"
            if isinstance(plan.get(content_key), dict):
                content = dict(plan[content_key])
                for field in cls.PLAN_FIELDS:
                    content.setdefault(field, f"value-{field}")
                plan[content_key] = content
        return {
            "strategic_profile": {
                "status": "complete", "revision": 2, "confirmed_revision": 2,
                "scope": {"page_id": "page-1"},
            },
            "active_strategic_page_id": "page-1",
            "business_master_plans": ({"page-1": plan} if plan is not None else {}),
        }

    def test_lifecycle_without_plan_is_active_without_confirmed_plan(self):
        root = self._root(self._profile())
        state = runtime._admira_strategic_profile_state(product_root=root)
        self.assertEqual(state["lifecycle_state"], "active_without_confirmed_strategic_plan")
        self.assertEqual(state["master_plan_status"], "missing")

    def test_missing_plan_is_reserved_for_isolated_compiler_not_hermes_prose(self):
        root = self._root(self._profile())
        state = runtime._admira_strategic_profile_state(product_root=root)

        text = runtime._admira_compiled_procedure_instruction(state)

        self.assertIn("isolated Sol-low compiler", text)
        self.assertIn("Do not draft, abbreviate, save, or present a substitute", text)
        self.assertIn("do not reproduce the compiler's job in prose", text)

    def test_legacy_partial_confirmed_plan_is_not_injected_as_final(self):
        profile = self._profile()
        profile["business_master_plans"] = {"page-1": {
            "status": "confirmed",
            "content": {"diagnosis": "Registro parcial antiguo"},
        }}
        root = self._root(profile)
        state = runtime._admira_strategic_profile_state(product_root=root)
        self.assertEqual(state["master_plan_status"], "missing")
        self.assertEqual(state["lifecycle_state"], "active_without_confirmed_strategic_plan")
        self.assertNotIn("Registro parcial antiguo", runtime._admira_compiled_procedure_instruction(state))

    def test_confirmed_plan_is_injected_and_live_meta_has_authority(self):
        root = self._root(self._profile({
            "status": "confirmed", "revision": 1, "profile_revision": 2,
            "content": {"advertising_opportunity": "Prioridad WhatsApp", "next_steps_and_questions": "Prueba y optimiza"},
        }))
        state = runtime._admira_strategic_profile_state(product_root=root)
        self.assertEqual(state["lifecycle_state"], "active_with_confirmed_strategic_plan")
        text = runtime._admira_compiled_procedure_instruction(state)
        self.assertIn("Prioridad WhatsApp", text)
        self.assertIn("Meta live", text)
        self.assertIn("never ask to reconfirm", text)

    def test_maximum_size_plan_retains_every_section_and_tail_markers(self):
        content = {
            field: f"HEAD-{field}-" + ("x" * 5000) + f"-TAIL-{field}"
            for field in self.PLAN_FIELDS
        }
        state = runtime._admira_strategic_profile_state(product_root=self._root(self._profile({
            "status": "confirmed", "revision": 1, "profile_revision": 2,
            "content": content,
        })))

        rendered = runtime._admira_render_master_plan(state)

        for field in self.PLAN_FIELDS:
            self.assertIn(f"HEAD-{field}", rendered)
            self.assertIn(f"TAIL-{field}", rendered)
        self.assertIn("Próximos pasos para pulirlo", rendered)

    def test_confirmed_plan_reaches_responses_and_chat_completion_payloads(self):
        plan = {field: f"live-{field}" for field in self.PLAN_FIELDS}
        state = runtime._admira_strategic_profile_state(product_root=self._root(self._profile({
            "status": "confirmed", "revision": 1, "profile_revision": 2,
            "content": plan,
        })))
        responses = runtime._admira_attach_compiled_procedure(
            {"input": [{"role": "user", "content": "hola"}], "instructions": "Eres Admira."},
            state=state,
        )
        chat = runtime._admira_attach_compiled_procedure(
            {"messages": [{"role": "user", "content": "hola"}]},
            state=state,
        )

        self.assertIn("live-advertising_opportunity", responses["instructions"])
        serialized_chat = json.dumps(chat["messages"], ensure_ascii=False)
        self.assertIn("live-advertising_opportunity", serialized_chat)
        self.assertIn("live-next_steps_and_questions", serialized_chat)

    def test_recent_generated_creative_reaches_provider_context_without_approval(self):
        root = self._root(self._profile({
            "status": "confirmed", "revision": 1, "profile_revision": 2,
            "content": {"advertising_opportunity": "Full Detail por WhatsApp"},
        }))
        recent = root / "output" / "creatives" / "codex-full-detail" / "fixed-01.png"
        recent.parent.mkdir(parents=True)
        recent.write_bytes(b"image")
        old = root / "output" / "creatives" / "codex-old" / "fixed-02.png"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"old")
        old_time = time.time() - (5 * 86400)
        os.utime(old, (old_time, old_time))

        state = runtime._admira_strategic_profile_state(product_root=root)
        text = runtime._admira_compiled_procedure_instruction(state)

        self.assertEqual(len(state["recent_generated_creatives"]), 1)
        self.assertEqual(
            state["recent_generated_creatives"][0]["asset_id"],
            "codex-full-detail/fixed-01.png",
        )
        self.assertEqual(
            state["recent_generated_creatives"][0]["approval_state"],
            "file_exists_only_not_campaign_approval",
        )
        self.assertIn("codex-full-detail/fixed-01.png", text)
        self.assertIn("proves only that each file exists", text)
        self.assertNotIn("codex-old/fixed-02.png", text)
        self.assertNotIn(str(root), text)

    def test_recent_generated_creative_also_reaches_onboarding_context(self):
        profile = {
            "strategic_profile": {
                "status": "collecting", "revision": 1,
                "scope": {"page_id": "page-1"}, "topics": {},
            }
        }
        root = self._root(profile)
        recent = root / "output" / "creatives" / "codex-logo" / "fixed-01.png"
        recent.parent.mkdir(parents=True)
        recent.write_bytes(b"image")

        state = runtime._admira_strategic_profile_state(product_root=root)
        text = runtime._admira_compiled_procedure_instruction(state)

        self.assertFalse(state["complete"])
        self.assertIn("codex-logo/fixed-01.png", text)
        self.assertIn("use list_recent_creatives to inspect or re-attach", text)
        self.assertIn("never proves selection, approval", text)

    def test_confirmed_plan_keeps_status_when_profile_revision_changes(self):
        root = self._root(self._profile({
            "status": "confirmed", "revision": 1, "profile_revision": 1,
            "content": {"advertising_opportunity": "Plan antiguo"},
        }))
        profile = json.loads((root / "dashboard" / "data" / "business_profile.json").read_text())
        profile["strategic_profile"]["revision"] = 2
        profile["strategic_profile"]["confirmed_revision"] = 2
        (root / "dashboard" / "data" / "business_profile.json").write_text(json.dumps(profile))
        state = runtime._admira_strategic_profile_state(product_root=root)
        self.assertEqual(state["master_plan_status"], "confirmed")
        self.assertEqual(state["lifecycle_state"], "active_with_confirmed_strategic_plan")

    def test_proposed_plan_is_draft_and_never_reopens_onboarding(self):
        root = self._root(self._profile({
            "status": "proposed", "revision": 1, "profile_revision": 2,
            "draft": {"advertising_opportunity": "Falta seguimiento"},
        }))
        state = runtime._admira_strategic_profile_state(product_root=root)
        self.assertEqual(state["lifecycle_state"], "active_without_confirmed_strategic_plan")
        text = runtime._admira_compiled_procedure_instruction(state)
        self.assertIn("compact advertising-plan draft is already saved", text)
        self.assertIn("directly question or change", text)
        self.assertIn("without blocking ordinary creative, campaign or analysis work", text)

    def test_incomplete_profile_is_onboarding_even_with_plan_record(self):
        profile = self._profile({"status": "confirmed", "content": {"advertising_opportunity": "x"}})
        profile["strategic_profile"]["status"] = "review_required"
        root = self._root(profile)
        state = runtime._admira_strategic_profile_state(product_root=root)
        self.assertEqual(state["lifecycle_state"], "onboarding")
        self.assertEqual(state["master_plan_status"], "confirmed")

    def test_review_required_injects_known_business_facts_without_inventing_plan(self):
        profile = {
            "strategic_profile": {
                "status": "review_required",
                "revision": 7,
                "confirmed_revision": None,
                "scope": {"page_id": "page-1"},
                "review_ready": {"revision": 7},
                "review_presentation": {"revision": 7},
                "topics": {
                    "services": {"status": "confirmed", "value": ["Rodeo Premium"]},
                    "markets": {"status": "confirmed", "value": ["Bogotá Norte"]},
                    "branding": {
                        "status": "confirmed",
                        "value": "Marca: Rodeo - Car Detailing; logo oficial aprobado",
                    },
                },
            },
            "business_master_plans": {},
        }
        root = self._root(profile)
        (root / "dashboard" / "data" / "meta_oauth_connection.json").write_text(
            json.dumps({"active_page_id": "page-1", "pages": [
                {"id": "page-1", "name": "Rodeo - Car Detailing"}
            ]}),
            encoding="utf-8",
        )

        state = runtime._admira_strategic_profile_state(product_root=root)
        text = runtime._admira_compiled_procedure_instruction(state)

        self.assertEqual(state["lifecycle_state"], "onboarding")
        self.assertEqual(state["master_plan_status"], "missing")
        self.assertTrue(state["business_profile_review_presented"])
        self.assertIn("Rodeo - Car Detailing", text)
        self.assertIn("Bogotá Norte", text)
        self.assertIn("strategic_plan_status=missing", text)
        self.assertIn("Do not restart discovery", text)
        self.assertIn("never call the business summary a plan draft", text)

    def test_collecting_profile_distinguishes_drafts_from_missing_topics(self):
        profile = {
            "strategic_profile": {
                "status": "collecting", "revision": 3,
                "scope": {"page_id": "page-1"},
                "topics": {
                    "services": {"status": "confirmed", "value": ["Detailing"]},
                    "markets": {"draft": {
                        "value": ["Bogotá"], "proposed_status": "confirmed"
                    }},
                },
            }
        }
        state = runtime._admira_strategic_profile_state(product_root=self._root(profile))
        text = runtime._admira_compiled_procedure_instruction(state)

        self.assertEqual(state["business_profile_draft_topics"], ["markets"])
        self.assertIn("Bogotá", text)
        self.assertIn("remembered_draft", text)
        self.assertIn("not a missing field", text)
        self.assertIn("ideal_customer", state["business_profile_unresolved_topics"])

    def test_single_plan_for_other_page_is_not_injected(self):
        profile = self._profile({
            "status": "confirmed", "page_id": "page-other", "revision": 2,
            "profile_revision": 2, "content": {"advertising_opportunity": "Otro negocio"},
        })
        profile["business_master_plans"] = {"page-other": profile["business_master_plans"]["page-1"]}
        root = self._root(profile)
        state = runtime._admira_strategic_profile_state(product_root=root)
        self.assertEqual(state["master_plan_status"], "missing")
        self.assertNotIn("Otro negocio", runtime._admira_compiled_procedure_instruction(state))

    def test_pending_plan_state_prioritizes_plan_over_branding(self):
        root = self._root(self._profile({
            "status": "proposed", "revision": 1, "profile_revision": 2,
            "draft": {"advertising_opportunity": "Prioridad"},
        }))
        state = runtime._admira_strategic_profile_state(product_root=root)
        text = runtime._admira_compiled_procedure_instruction(state)
        self.assertIn("compact advertising-plan draft is already saved", text)
        self.assertIn("Continue with the buyer's current request", text)
        self.assertNotIn("Continue with the buyer-confirmed brand foundation before", text)

    def test_daily_prompt_mentions_draft_and_live_authority(self):
        text = gateway.daily_brief_prompt()
        self.assertIn("borrador", text)
        self.assertIn("datos live de Meta", text)
        self.assertIn("business-profile en review_required", text)
        self.assertIn("strategic_plan_status=missing", text)
        self.assertIn("no es un plan estratégico", text)

    def test_existing_daily_cron_refreshes_changed_prompt_once(self):
        root = Path(tempfile.mkdtemp())
        prompt_file = root / "daily.md"
        prompt_state = root / "prompt-hashes.json"
        config = SimpleNamespace(
            telegram_bot_token="123:token", telegram_chat_id="12345",
            hermes_cli="hermes", daily_brief_time="08:00",
            daily_brief_timezone="America/Bogota",
        )

        class Completed:
            def __init__(self, stdout="", returncode=0, stderr=""):
                self.stdout = stdout
                self.returncode = returncode
                self.stderr = stderr

        job = """  abcdef123456 [active]
    Name:      Admira IA - lectura diaria
    Schedule:  0 8 * * *
    Deliver:   telegram:12345
"""
        calls = []

        def fake_run(command, **_kwargs):
            calls.append(command)
            if command[:3] == ["/usr/local/bin/hermes", "cron", "list"]:
                return Completed(stdout=job)
            return Completed(stdout="updated")

        with patch.object(gateway, "CRON_PROMPT_STATE_FILE", prompt_state), patch.object(
            gateway, "DAILY_BRIEF_PROMPT_FILE", prompt_file
        ), patch.object(
            gateway, "telegram_settings", return_value={
                "enabled": True, "bot_configured": True, "chat_id": "12345"
            }
        ), patch.object(
            gateway.shutil, "which", return_value="/usr/local/bin/hermes"
        ), patch.object(
            gateway, "write_gateway_files", return_value={
                "workspace": str(root), "hermes_home": str(root / "home")
            }
        ), patch.object(
            gateway, "hermes_environment", return_value={}
        ), patch.object(
            gateway, "_cron_timezone_changed", return_value=False
        ), patch.object(gateway.subprocess, "run", side_effect=fake_run):
            first = gateway.ensure_daily_brief_cron(config)
            first_edits = [call for call in calls if call[:3] == ["/usr/local/bin/hermes", "cron", "edit"]]
            calls.clear()
            second = gateway.ensure_daily_brief_cron(config)
            second_edits = [call for call in calls if call[:3] == ["/usr/local/bin/hermes", "cron", "edit"]]

        self.assertTrue(first["prompt_updated"])
        self.assertEqual(len(first_edits), 1)
        self.assertTrue(second["configured"] and second["exists"])
        self.assertEqual(second_edits, [])

    def test_lifecycle_hooks_are_optional_for_older_dashboard(self):
        with patch.object(runtime, "_admira_dashboard_module", return_value=object()):
            self.assertEqual(runtime._resolve_business_lifecycle_transition(raw_message="ok"), {})
            self.assertEqual(runtime._ensure_business_lifecycle_artifact_visible(assistant_text="hola"), {})
            self.assertFalse(runtime._record_business_lifecycle_artifact_presented(assistant_text="hola"))


if __name__ == "__main__":
    unittest.main()
