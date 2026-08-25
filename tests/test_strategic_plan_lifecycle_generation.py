from __future__ import annotations

import importlib.util
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, patch


ROOT = Path(__file__).resolve().parents[1]


def load_dashboard():
    spec = importlib.util.spec_from_file_location(
        "strategic_plan_generation_dashboard_test",
        ROOT / "dashboard" / "monitoring-dashboard.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StrategicPlanLifecycleGenerationTests(unittest.TestCase):
    def setUp(self):
        self.dashboard = load_dashboard()
        self.real_business_source = self.dashboard._strategic_plan_business_source
        self.real_live_meta_source = self.dashboard._strategic_plan_live_meta_source
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.root = root
        self.file_patches = [
            patch.object(self.dashboard, "BUSINESS_PROFILE_FILE", root / "business.json"),
            patch.object(self.dashboard, "TRUSTED_BUYER_TURN_FILE", root / "turn.json"),
            patch.object(self.dashboard, "TRUSTED_BUYER_TURN_LOCK_FILE", root / "turn.lock"),
            patch.object(self.dashboard, "STRATEGIC_PLAN_GENERATION_STATE_FILE", root / "plan-generation.json"),
            patch.object(self.dashboard, "ADS_ONBOARDING_FILE", root / "ads-onboarding.md"),
            patch.object(self.dashboard, "AUDIENCE_FILE", root / "audience.json"),
        ]
        for item in self.file_patches:
            item.start()
        self.common_patches = [
            patch.object(self.dashboard, "active_meta_page_id", return_value="page-1"),
            patch.object(self.dashboard, "current_configured_ad_account_id", return_value="act_1"),
            patch.object(
                self.dashboard,
                "load_config",
                return_value=SimpleNamespace(telegram_chat_id="123"),
            ),
            patch.object(self.dashboard, "write_onboarding_questions_memory", return_value={"status": "pending"}),
            patch.object(self.dashboard, "write_agent_onboarding_plan", return_value={}),
            patch.object(self.dashboard, "log_action"),
            patch.object(
                self.dashboard,
                "_strategic_plan_business_source",
                return_value={"business": "Rodeo", "margin": "75%"},
            ),
            patch.object(
                self.dashboard,
                "_strategic_plan_live_meta_source",
                return_value={
                    "verified": True,
                    "partial": False,
                    "account_id": "act_1",
                    "fetched_at": "2026-08-25T10:00:00+00:00",
                    "inventory_totals": {"campaigns": 3},
                    "campaigns": [{"name": "Paused", "status": "PAUSED"}],
                },
            ),
        ]
        for item in self.common_patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.common_patches):
            item.stop()
        for item in reversed(self.file_patches):
            item.stop()
        self.temp.cleanup()

    def _complete_profile(self):
        strategic = self.dashboard.new_strategic_profile("page-1")
        strategic = self.dashboard.apply_strategic_profile_updates(
            strategic,
            {
                topic: {
                    "status": "confirmed",
                    "value": f"confirmed-{topic}",
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
        strategic = self.dashboard.mark_strategic_profile_review_presented(
            strategic,
            page_id="page-1",
            after_buyer_message_sequence=10,
            assistant_message_hash="summary",
            evidence={
                "source": "finalized_outbound_transport",
                "chat_id": "123",
                "session_id": "session-1",
                "transport": "telegram",
                "message_sequence": 10,
                "trusted_server_evidence": True,
            },
        )
        strategic = self.dashboard.confirm_strategic_profile_revision(
            strategic,
            page_id="page-1",
            trusted_buyer_confirmation=True,
            evidence={
                "chat_id": "123",
                "session_id": "session-1",
                "transport": "telegram",
                "message_sequence": 11,
            },
        )
        return self.dashboard.embed_strategic_profile({}, strategic)

    def _turn(self, sequence, message):
        return self.dashboard.record_trusted_buyer_turn(
            "123", "session-1", sequence, message, transport="telegram"
        )

    def _expected(
        self,
        sequence,
        message,
        *,
        chat_id="123",
        session_id="session-1",
        transport="telegram",
    ):
        return {
            "chat_id": chat_id,
            "session_id": session_id,
            "transport": transport,
            "raw_message": message,
            "message_sequence": sequence,
        }

    def _plan(self):
        return {
            field: (
                f"{field}: decisión específica sustentada en precios, costos, margen, capacidad y evidencia Meta.\n"
                "- Acción priorizada con responsable conceptual, medición y criterio de decisión."
            )
            for field in self.dashboard._MASTER_PLAN_FIELDS
        }

    def test_compiles_once_and_stores_a_bound_canonical_proposal(self):
        self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, self._complete_profile())
        message = "Sí, el resumen del negocio está correcto"
        turn = self._turn(20, message)
        plan = self._plan()
        with patch.object(
            self.dashboard,
            "compile_strategic_plan",
            return_value={
                "ok": True,
                "plan": plan,
                "provider": "openai-codex",
                "model": "gpt-5.6-sol",
                "attempts": [{
                    "provider": "openai-codex", "model": "gpt-5.6-sol",
                    "ok": True, "reason": "", "elapsed_ms": 123,
                }],
            },
        ) as compiler:
            result = self.dashboard.ensure_initial_business_master_plan(
                expected_turn=self._expected(20, message)
            )
            replay = self.dashboard.ensure_initial_business_master_plan(
                expected_turn=self._expected(20, message)
            )

        self.assertTrue(result["created"])
        self.assertFalse(replay["created"])
        compiler.assert_called_once_with(
            {"business": "Rodeo", "margin": "75%"},
            ANY,
            config=ANY,
            timeout=ANY,
        )
        self.dashboard._strategic_plan_business_source.assert_called_once_with(
            ANY, ANY, "page-1", account_id="act_1"
        )
        self.dashboard._strategic_plan_live_meta_source.assert_called_once_with(
            account_id="act_1", timeout=90.0
        )
        stored = self.dashboard.read_json(self.dashboard.BUSINESS_PROFILE_FILE, {})
        record = stored["business_master_plans"]["page-1"]
        self.assertEqual(record["status"], "proposed")
        self.assertEqual(record["draft"], plan)
        self.assertEqual(record["proposal_turn"]["message_hash"], turn["message_hash"])
        self.assertEqual(record["generator"]["model"], "gpt-5.6-sol")
        self.assertTrue(record["generator"]["meta_verified"])

        visible = self.dashboard.ensure_business_lifecycle_artifact_visible(
            "Preparando una respuesta", "strategic_plan",
            session_id="session-1", chat_id="123",
        )
        self.assertIn("Preparé esta propuesta inicial de anuncios", visible)
        self.assertIn("1. Oportunidad publicitaria", visible)
        self.assertIn("5. Próximos pasos para pulirlo", visible)
        self.assertNotIn('{"', visible)

    def test_provider_failure_leaves_plan_missing_and_enforces_cooldown(self):
        self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, self._complete_profile())
        message = "Sí, está correcto"
        self._turn(20, message)
        with patch.object(
            self.dashboard,
            "compile_strategic_plan",
            return_value={
                "ok": False,
                "reason": "strategic_plan_provider_failed",
                "attempts": [{
                    "provider": "openai-codex", "model": "gpt-5.6-sol",
                    "ok": False, "reason": "provider_failed", "elapsed_ms": 100,
                }],
            },
        ) as compiler:
            failed = self.dashboard.ensure_initial_business_master_plan(
                expected_turn=self._expected(20, message)
            )
            cooldown = self.dashboard.ensure_initial_business_master_plan(
                expected_turn=self._expected(20, message)
            )

        self.assertTrue(failed["attempted"])
        self.assertFalse(failed["ok"])
        self.assertFalse(cooldown["attempted"])
        self.assertEqual(cooldown["reason"], "strategic_plan_generation_cooldown")
        self.assertEqual(compiler.call_count, 1)
        stored = self.dashboard.read_json(self.dashboard.BUSINESS_PROFILE_FILE, {})
        self.assertFalse((stored.get("business_master_plans") or {}).get("page-1"))

    def test_legacy_partial_plan_is_replaced_instead_of_stranding_upgrade(self):
        profile = self._complete_profile()
        profile["business_master_plans"] = {
            "page-1": {
                "status": "proposed",
                "draft": {"diagnosis": "legacy partial record"},
            }
        }
        self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, profile)
        message = "Sí, el resumen está correcto"
        self._turn(20, message)
        with patch.object(
            self.dashboard,
            "compile_strategic_plan",
            return_value={
                "ok": True,
                "plan": self._plan(),
                "provider": "openai-codex",
                "model": "gpt-5.6-sol",
                "attempts": [],
            },
        ):
            result = self.dashboard.ensure_initial_business_master_plan(
                expected_turn=self._expected(20, message)
            )

        self.assertTrue(result["created"])
        stored = self.dashboard.read_json(self.dashboard.BUSINESS_PROFILE_FILE, {})
        self.assertEqual(
            set(stored["business_master_plans"]["page-1"]["draft"]),
            set(self.dashboard._MASTER_PLAN_FIELDS),
        )

    def test_ad_account_change_rejects_commit_and_releases_own_lease(self):
        self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, self._complete_profile())
        message = "Sí, el resumen está correcto"
        self._turn(20, message)
        with patch.object(
            self.dashboard,
            "current_configured_ad_account_id",
            side_effect=["act_1", "act_2"],
        ), patch.object(
            self.dashboard,
            "compile_strategic_plan",
            return_value={
                "ok": True,
                "plan": self._plan(),
                "provider": "openai-codex",
                "model": "gpt-5.6-sol",
                "attempts": [],
            },
        ):
            result = self.dashboard.ensure_initial_business_master_plan(
                expected_turn=self._expected(20, message)
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "strategic_plan_generation_compare_and_swap_failed")
        state = self.dashboard.read_json(
            self.dashboard.STRATEGIC_PLAN_GENERATION_STATE_FILE, {}
        )
        self.assertNotIn("page-1", state)
        stored = self.dashboard.read_json(self.dashboard.BUSINESS_PROFILE_FILE, {})
        self.assertFalse((stored.get("business_master_plans") or {}).get("page-1"))

    def test_live_meta_read_has_a_real_wall_clock_bound(self):
        release = threading.Event()

        def blocked_read(*_args, **_kwargs):
            release.wait(1)
            return {"ok": True, "account_id": "act_1", "metrics": {}}

        started = time.monotonic()
        try:
            with patch.object(self.dashboard, "refresh_real_metrics", side_effect=blocked_read):
                result = self.real_live_meta_source(
                    account_id="act_1", timeout=0.02
                )
        finally:
            release.set()

        self.assertLess(time.monotonic() - started, 0.25)
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "live_meta_sync_timeout")

    def test_business_source_includes_single_business_memory(self):
        profile = self._complete_profile()
        profile["meta_page_profile"] = {"id": "page-1", "name": "Rodeo"}
        profile["campaign_goal"] = "Reservas por WhatsApp"
        strategic = self.dashboard.strategic_profile_for_page(
            profile, page_id="page-1", activate=False
        )
        self.dashboard.write_json(
            self.dashboard.AUDIENCE_FILE,
            {"audience": "Propietarios de vehículos"},
        )
        self.dashboard.ADS_ONBOARDING_FILE.write_text(
            "# Ads campaign onboarding\nMeta principal: Reservas por WhatsApp\n",
            encoding="utf-8",
        )
        library = {
            "general": {"saved": True, "fields": {"brand_name": "Rodeo", "colors": "black"}},
            "products": [
                {"id": "premium", "name": "Premium", "fields": {"name": "Detailing", "price": "$110.000 COP"}},
            ],
            "ad_briefs": [
                {"id": "brief", "name": "Brief", "fields": {"campaign_name": "Rodeo"}},
            ],
        }
        with patch.object(self.dashboard, "guide_library", return_value=library), \
                patch.object(
                    self.dashboard,
                    "decision_memory_payload",
                    return_value={"margin": "20%"},
                ):
            source = self.real_business_source(
                profile, strategic, "page-1", account_id="act_1"
            )

        self.assertEqual([item["id"] for item in source["official_products_and_services"]], ["premium"])
        self.assertEqual([item["id"] for item in source["existing_campaign_briefs"]], ["brief"])
        self.assertEqual(source["saved_audience_strategy"], {"audience": "Propietarios de vehículos"})
        self.assertEqual(source["saved_profitability_context"], {"margin": "20%"})
        self.assertIn("Reservas por WhatsApp", source["ads_onboarding"])

    def test_changed_trusted_turn_loses_compare_and_swap(self):
        self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, self._complete_profile())
        message = "Sí, está correcto"
        self._turn(20, message)

        def concurrent_turn(*_args, **_kwargs):
            self._turn(21, "Un turno concurrente distinto")
            return {
                "ok": True,
                "plan": self._plan(),
                "provider": "openai-codex",
                "model": "gpt-5.6-sol",
                "attempts": [],
            }

        with patch.object(self.dashboard, "compile_strategic_plan", side_effect=concurrent_turn):
            result = self.dashboard.ensure_initial_business_master_plan(
                expected_turn=self._expected(20, message)
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "strategic_plan_generation_compare_and_swap_failed")
        stored = self.dashboard.read_json(self.dashboard.BUSINESS_PROFILE_FILE, {})
        self.assertFalse((stored.get("business_master_plans") or {}).get("page-1"))
        lease = self.dashboard.read_json(
            self.dashboard.STRATEGIC_PLAN_GENERATION_STATE_FILE, {}
        )
        self.assertNotIn("page-1", lease)

    def test_cron_event_cannot_reuse_the_last_telegram_turn(self):
        self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, self._complete_profile())
        self._turn(20, "Sí, el resumen está correcto")
        with patch.object(self.dashboard, "compile_strategic_plan") as compiler:
            result = self.dashboard.ensure_initial_business_master_plan(expected_turn={
                "chat_id": "cron:daily-read",
                "session_id": "agent:main:cron:daily-read",
                "transport": "cron",
                "raw_message": "ejecuta la lectura diaria",
                "message_sequence": 20,
            })

        self.assertFalse(result["attempted"])
        self.assertEqual(result["reason"], "strategic_plan_turn_not_bound_to_current_event")
        compiler.assert_not_called()
        self.assertFalse(self.dashboard.STRATEGIC_PLAN_GENERATION_STATE_FILE.exists())

    def test_compiler_exception_releases_the_generation_lease(self):
        self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, self._complete_profile())
        message = "Sí, el resumen está correcto"
        self._turn(20, message)
        with patch.object(
            self.dashboard,
            "compile_strategic_plan",
            side_effect=RuntimeError("provider process crashed"),
        ):
            result = self.dashboard.ensure_initial_business_master_plan(
                expected_turn=self._expected(20, message)
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "strategic_plan_compiler_exception")
        state = self.dashboard.read_json(
            self.dashboard.STRATEGIC_PLAN_GENERATION_STATE_FILE, {}
        )
        self.assertNotIn("page-1", state)

    def test_live_meta_exception_releases_the_generation_lease(self):
        self.dashboard.write_json(self.dashboard.BUSINESS_PROFILE_FILE, self._complete_profile())
        message = "Sí, el resumen está correcto"
        self._turn(20, message)
        with patch.object(
            self.dashboard,
            "_strategic_plan_live_meta_source",
            side_effect=RuntimeError("graph reader crashed"),
        ):
            result = self.dashboard.ensure_initial_business_master_plan(
                expected_turn=self._expected(20, message)
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "strategic_plan_compiler_exception")
        state = self.dashboard.read_json(
            self.dashboard.STRATEGIC_PLAN_GENERATION_STATE_FILE, {}
        )
        self.assertNotIn("page-1", state)

if __name__ == "__main__":
    unittest.main()
