import unittest
from pathlib import Path

import admira_tool_bridge
from admira_tool_bridge import normalize_tool_arguments
from expert_campaign import validate_meta_targeting_selection


class ToolArgumentNormalizationTests(unittest.TestCase):
    def test_bridge_product_root_resolves_real_dashboard(self):
        self.assertEqual(admira_tool_bridge.ROOT_DIR, Path(__file__).resolve().parents[1])
        self.assertTrue(admira_tool_bridge.DASHBOARD_PATH.exists())

    def test_nim_item_wrappers_become_campaign_arrays(self):
        payload = normalize_tool_arguments({
            "name": "Canary",
            "adsets": {
                "item": {
                    "name": "Core",
                    "geo_locations": {"countries": {"item": "CO"}},
                    "genders": {"item": "all"},
                    "ads": {
                        "item": {
                            "name": "Static",
                            "image_path": "/tmp/canary.png",
                        },
                    },
                },
            },
        })

        self.assertIsInstance(payload["adsets"], list)
        self.assertEqual(payload["adsets"][0]["geo_locations"]["countries"], ["CO"])
        self.assertEqual(payload["adsets"][0]["genders"], ["all"])
        self.assertEqual(payload["adsets"][0]["ads"][0]["name"], "Static")

    def test_mixed_item_mapping_is_not_destructively_unwrapped(self):
        payload = normalize_tool_arguments({
            "context_card": {
                "item": {"title": "A"},
                "style": "LIST_STYLE",
            },
        })
        self.assertEqual(payload["context_card"]["style"], "LIST_STYLE")
        self.assertEqual(payload["context_card"]["item"]["title"], "A")

    def test_nim_item_wrapper_ignores_redundant_xml_text_node(self):
        payload = normalize_tool_arguments({
            "questions": {
                "item": [
                    {"type": "FULL_NAME"},
                    {"type": "EMAIL"},
                    {"type": "PHONE"},
                ],
                "$text": "FULL_NAME",
            },
        })
        self.assertEqual(
            [item["type"] for item in payload["questions"]],
            ["FULL_NAME", "EMAIL", "PHONE"],
        )

    def test_empty_lead_form_call_is_stopped_before_product_execution(self):
        result = admira_tool_bridge.call_tool("admira_create_lead_form", {})
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "empty_tool_arguments")
        self.assertEqual(
            result["result"]["missing"],
            ["page_id", "name", "privacy_policy_url", "questions"],
        )

    def test_destination_shape_recovers_nested_gemini_campaign(self):
        payload = {
            "campaign": {
                "name": "Buffete - WhatsApp Cartagena",
                "objective": "OUTCOME_ENGAGEMENT",
                "status": "PAUSED",
            },
            "adsets": [{
                "name": "Cartagena",
                "daily_budget": 5,
                "age_min": 25,
                "age_max": 65,
                "geo_locations": {
                    "cities": [{"key": "459428", "name": "Cartagena", "country_code": "CO"}],
                },
                "placements": {"automatic": True},
            }],
            "creatives": [{
                "name": "Ejecutivo",
                "body": "Texto aprobado",
                "title": "Asesoría laboral",
                "image_path": "/app/output/approved.png",
            }],
            "budget_confirmation": "5 USD",
            "primary_text": "Texto aprobado",
            "headline": "Asesoría laboral",
            "primary_text_approved": True,
            "headline_approved": True,
            "prefilled_message": "Hola, quiero una asesoría.",
            "creative_decision": "Usar el creativo que acabo de aprobar.",
            "creative_approved": True,
            "prefilled_message_approved": True,
        }
        normalized, error = admira_tool_bridge.destination_campaign_arguments(
            "admira_create_whatsapp_campaign",
            payload,
            budget_contract=lambda quote: {"ok": True, "amount": 5, "currency": "USD"},
        )
        self.assertEqual(error, "")
        self.assertEqual(normalized["name"], "Buffete - WhatsApp Cartagena")
        self.assertEqual(normalized["objective"], "MESSAGES")
        self.assertEqual(normalized["daily_budget"], 5.0)
        self.assertEqual(normalized["placements"], {"automatic": True})
        self.assertEqual(normalized["targeting_locations"][0]["key"], "459428")
        self.assertEqual(normalized["targeting_locations"][0]["type"], "city")
        self.assertEqual(normalized["creative_image_path"], "/app/output/approved.png")
        self.assertEqual(normalized["ad_sets"][0]["ads"][0]["body"], "Texto aprobado")
        self.assertEqual(normalized["final_status"], "PAUSED")

    def test_whatsapp_contract_blocks_unapproved_creative_and_message(self):
        base = {
            "name": "WhatsApp",
            "objective": "MESSAGES",
            "daily_budget": 5,
            "budget_confirmation": "5 USD",
            "locations": ["CO"],
            "placements": {"automatic": True},
            "primary_text": "Escríbenos para recibir información.",
            "headline": "Conoce más",
            "primary_text_approved": True,
            "headline_approved": True,
            "prefilled_message": "Hola, quiero información.",
        }
        normalized, error = admira_tool_bridge.destination_campaign_arguments(
            "admira_create_whatsapp_campaign",
            base,
            budget_contract=lambda quote: {"ok": True, "amount": 5, "currency": "USD"},
        )
        self.assertIsNone(normalized)
        self.assertEqual(error, "missing_creative_decision")

        base.update({"creative_decision": "Crear uno nuevo", "creative_approved": True})
        normalized, error = admira_tool_bridge.destination_campaign_arguments(
            "admira_create_whatsapp_campaign",
            base,
            budget_contract=lambda quote: {"ok": True, "amount": 5, "currency": "USD"},
        )
        self.assertIsNone(normalized)
        self.assertEqual(error, "prefilled_message_not_approved")

    def test_destination_shape_preserves_distinct_complete_per_adset_placements(self):
        normalized, error = admira_tool_bridge.canonicalize_destination_campaign_shape({
            "adsets": [
                {"placements": {"automatic": True}},
                {"placements": {"automatic": False, "manual": ["facebook_feed"]}},
            ],
        })
        self.assertEqual(error, "")
        self.assertNotIn("placements", normalized)
        self.assertTrue(normalized["ad_sets"][0]["placements"]["automatic"])
        self.assertEqual(
            normalized["ad_sets"][1]["placements"]["manual"],
            ["facebook_feed"],
        )

    def test_city_location_requires_exact_live_meta_key(self):
        def live_search(kind, query):
            self.assertEqual(kind, "location")
            self.assertEqual(query, "Cartagena")
            return {
                "ok": True,
                "items": [
                    {"key": "459428", "name": "Cartagena", "type": "city", "country_code": "CO"},
                ],
            }

        invalid = validate_meta_targeting_selection(
            [],
            [{"key": "130001", "name": "Cartagena", "type": "city", "country_code": "CO"}],
            live_search=live_search,
            verify_locations=True,
        )
        valid = validate_meta_targeting_selection(
            [],
            [{"key": "459428", "name": "Cartagena", "type": "city", "country_code": "CO"}],
            live_search=live_search,
            verify_locations=True,
        )
        self.assertFalse(invalid["ok"])
        self.assertEqual(invalid["errors"][0]["code"], "targeting_location_not_current")
        self.assertTrue(valid["ok"])

    def test_country_code_location_searches_live_catalog_by_country_name(self):
        seen = []
        def live_search(kind, query):
            seen.append((kind, query))
            return {
                "ok": True,
                "items": [{"key": "CO", "name": "Colombia", "type": "country", "country_code": "CO"}],
            }

        result = validate_meta_targeting_selection(
            [],
            [{"id": "CO"}],
            live_search=live_search,
            verify_locations=True,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(seen, [("location", "Colombia")])


if __name__ == "__main__":
    unittest.main()
