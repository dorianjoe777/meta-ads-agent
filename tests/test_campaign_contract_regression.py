import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def load_dashboard():
    spec = importlib.util.spec_from_file_location(
        "monitoring_dashboard_campaign_contract",
        ROOT / "dashboard" / "monitoring-dashboard.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CampaignContractRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboard = load_dashboard()
        from adset_controls import deprecated_manual_placements, normalize_placement_config
        from daily_agent import (
            adset_optimization_goal_for_campaign,
            campaign_objective_for_social,
            native_destination_type_for_adset,
            meta_rate_limit_guidance_from_steps,
            targeting_for_social,
            validate_campaign_targeting_before_meta,
        )
        from social_flow_client import SocialFlowClient
        cls.deprecated_manual_placements = staticmethod(deprecated_manual_placements)
        cls.normalize_placement_config = staticmethod(normalize_placement_config)
        cls.adset_optimization_goal_for_campaign = staticmethod(adset_optimization_goal_for_campaign)
        cls.campaign_objective_for_social = staticmethod(campaign_objective_for_social)
        cls.native_destination_type_for_adset = staticmethod(native_destination_type_for_adset)
        cls.meta_rate_limit_guidance_from_steps = staticmethod(meta_rate_limit_guidance_from_steps)
        cls.targeting_for_social = staticmethod(targeting_for_social)
        cls.validate_campaign_targeting_before_meta = staticmethod(validate_campaign_targeting_before_meta)
        cls.SocialFlowClient = SocialFlowClient

    def test_nested_campaign_contract_preserves_copy_gender_placements_and_message(self):
        normalized = self.dashboard.normalize_campaign_stack_arguments({
            "name": "Johana — Armonización Facial",
            "objective": "ventas",
            "daily_budget": 20000,
            "ad_sets": [{
                "name": "Pereira — mujeres 30 a 58",
                "targeting": {
                    "locations": ["CO"],
                    "age_range": {"min": 30, "max": 58},
                    "gender": "mujeres",
                    "placement_strategy": "advantage+ placements",
                },
                "ads": [{
                    "name": "Glow Party — Variante 1",
                    "copy": {
                        "primary_text": "Descubre Glow Party y reserva tu valoración.",
                        "headline": "Glow Party",
                        "cta": "WHATSAPP_MESSAGE",
                    },
                    "prefilled_message": "Hola, quiero información sobre Glow Party",
                    "creative_image_path": "/tmp/glow-party.png",
                }],
            }],
        })
        adset = normalized["ad_sets"][0]
        ad = adset["ads"][0]

        self.assertEqual(normalized["objective"], "ventas")
        self.assertEqual(adset["targeting"]["genders"], [2])
        self.assertEqual(adset["targeting"]["age_range"], {"min": 30, "max": 58})
        self.assertEqual(adset["placements"], "advantage+ placements")
        self.assertEqual(ad["primary_text"], "Descubre Glow Party y reserva tu valoración.")
        self.assertEqual(ad["headline"], "Glow Party")
        self.assertEqual(ad["prefilled_message"], "Hola, quiero información sobre Glow Party")
        self.assertEqual(
            self.dashboard._campaign_gender_contract_error(normalized),
            "",
        )

        targeting = self.targeting_for_social(adset["targeting"])
        self.assertEqual(targeting["genders"], [2])
        self.assertEqual(targeting["age_min"], 30)
        self.assertEqual(targeting["age_max"], 58)
        self.assertNotIn("publisher_platforms", targeting)
        self.assertEqual(self.campaign_objective_for_social("ventas"), "OUTCOME_SALES")
        self.assertEqual(
            self.adset_optimization_goal_for_campaign(adset, normalized),
            "OFFSITE_CONVERSIONS",
        )
        self.assertEqual(
            self.normalize_placement_config("advantage+ placements"),
            {"automatic": True, "manual": []},
        )
        self.assertEqual(
            self.normalize_placement_config(["INSTAGRAM_PROFILE_FEED"])["manual"],
            ["INSTAGRAM_FEED", "INSTAGRAM_PROFILE_FEED"],
        )

    def test_explicit_unknown_gender_is_not_silently_broadened(self):
        normalized = self.dashboard.normalize_campaign_stack_arguments({
            "name": "No adivinar audiencia",
            "objective": "ventas",
            "daily_budget": 20,
            "ad_sets": [{"targeting": {"gender": "solo clientes premium"}}],
        })
        error = self.dashboard._campaign_gender_contract_error(normalized)
        self.assertTrue(error.startswith("targeting_gender_invalid:"))

    def test_adset_brief_is_materialized_on_each_variant(self):
        normalized = self.dashboard.normalize_campaign_stack_arguments({
            "name": "Brief heredado",
            "objective": "mensajes",
            "daily_budget": 20,
            "ad_sets": [{
                "name": "Glow Party",
                "primary_text": "Reserva tu valoración por WhatsApp.",
                "headline": "Glow Party",
                "prefilled_message": "Hola, quiero información sobre Glow Party",
                "ads": [
                    {"name": "Variante 1", "creative_image_path": "/tmp/one.png"},
                    {"name": "Variante 2", "creative_image_path": "/tmp/two.png"},
                ],
            }],
        })
        variants = normalized["ad_sets"][0]["ads"]
        self.assertEqual([item["primary_text"] for item in variants], [
            "Reserva tu valoración por WhatsApp.",
            "Reserva tu valoración por WhatsApp.",
        ])
        self.assertEqual([item["prefilled_message"] for item in variants], [
            "Hola, quiero información sobre Glow Party",
            "Hola, quiero información sobre Glow Party",
        ])

    def test_spanish_objective_aliases_map_to_meta_outcomes(self):
        self.assertEqual(self.campaign_objective_for_social("interacción"), "OUTCOME_ENGAGEMENT")
        self.assertEqual(self.campaign_objective_for_social("ventas"), "OUTCOME_SALES")
        self.assertEqual(self.campaign_objective_for_social("formularios"), "OUTCOME_LEADS")

    def test_every_audience_sends_required_advantage_flag(self):
        broad = self.targeting_for_social({
            "locations": ["CO"], "age_range": {"min": 18, "max": 65}, "targeting_mode": "broad",
        })
        narrow = self.targeting_for_social({
            "locations": ["CO"], "age_range": {"min": 30, "max": 58},
        })
        self.assertEqual(broad["targeting_automation"], {"advantage_audience": 1})
        self.assertEqual(narrow["targeting_automation"], {"advantage_audience": 0})

    def test_scalar_nested_targeting_preserves_age_and_countries(self):
        """Nested ad-set drafts use scalar fields after normalization."""
        targeting = self.targeting_for_social({
            "countries": ["CO"],
            "age_min": 30,
            "age_max": 58,
            "genders": [2],
            "targeting_mode": "manual",
        })
        self.assertEqual(targeting["geo_locations"]["countries"], ["CO"])
        self.assertEqual(targeting["age_min"], 30)
        self.assertEqual(targeting["age_max"], 58)
        self.assertEqual(targeting["genders"], [2])
        self.assertEqual(targeting["targeting_automation"], {"advantage_audience": 0})

    def test_advantage_age_and_deprecated_placement_block_before_graph(self):
        class NoGraphClient:
            pass

        age = self.validate_campaign_targeting_before_meta({"ad_sets": [{"targeting": {
            "locations": ["CO"], "age_range": {"min": 30, "max": 65},
            "targeting_mode": "advantage_plus",
        }}]}, NoGraphClient())
        self.assertFalse(age["ok"])
        self.assertEqual(
            age["validations"][0]["errors"][0]["code"],
            "advantage_audience_age_min_maximum_25",
        )

        placement = self.validate_campaign_targeting_before_meta({"ad_sets": [{
            "placements": ["FACEBOOK_FEED", "INSTAGRAM_EXPLORE"],
            "targeting": {"locations": ["CO"]},
        }]}, NoGraphClient())
        self.assertFalse(placement["ok"])
        self.assertEqual(placement["validations"][0]["errors"][0]["code"], "placement_deprecated")
        self.assertEqual(self.deprecated_manual_placements(["INSTAGRAM_EXPLORE"]), ["INSTAGRAM_EXPLORE"])

    def test_current_interest_search_can_confirm_false_legacy_validation(self):
        client = object.__new__(self.SocialFlowClient)
        client.config = SimpleNamespace(ad_account_id="act_123")
        client.get_graph = lambda endpoint, params: {
            "ok": True,
            "body": {"data": [{"id": "6003020834693", "valid": False}]},
        }
        client.search_meta_targeting = lambda kind, query, limit=25: {
            "ok": True,
            "items": [{"kind": "interest", "id": "6003020834693", "name": "Música"}],
        }
        result = client.validate_meta_targeting([{"id": "6003020834693", "name": "Música"}])
        self.assertTrue(result["ok"])
        self.assertEqual(result["validation_source"], "live_adinterest_exact_id_fallback")

    def test_engagement_performance_goals_supply_required_destination(self):
        self.assertEqual(
            self.native_destination_type_for_adset({}, {}, optimization_goal="POST_ENGAGEMENT", campaign_outcome="OUTCOME_ENGAGEMENT"),
            "ON_POST",
        )
        self.assertEqual(
            self.native_destination_type_for_adset({}, {}, optimization_goal="THRUPLAY", campaign_outcome="OUTCOME_ENGAGEMENT"),
            "ON_VIDEO",
        )

    def test_meta_rate_limit_is_recognized_without_retrying_mutations(self):
        guidance = self.meta_rate_limit_guidance_from_steps([
            {"result": {"body": {"error": {"code": 80004, "error_subcode": 2446079, "message": "There have been too many calls to this ad-account."}}}}
        ])
        self.assertTrue(guidance["rate_limited"])
        self.assertEqual(guidance["retry_after_seconds"], 300)


if __name__ == "__main__":
    unittest.main()
