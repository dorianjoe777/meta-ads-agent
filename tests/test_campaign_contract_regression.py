import importlib.util
import sys
import unittest
from pathlib import Path


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
        from adset_controls import normalize_placement_config
        from daily_agent import (
            adset_optimization_goal_for_campaign,
            campaign_objective_for_social,
            targeting_for_social,
        )
        cls.normalize_placement_config = staticmethod(normalize_placement_config)
        cls.adset_optimization_goal_for_campaign = staticmethod(adset_optimization_goal_for_campaign)
        cls.campaign_objective_for_social = staticmethod(campaign_objective_for_social)
        cls.targeting_for_social = staticmethod(targeting_for_social)

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


if __name__ == "__main__":
    unittest.main()
