import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


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


def authoritative_buyer_brief(message):
    return f"## Verbatim recent buyer messages (authoritative)\n\n{message}"


class CampaignContractRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboard = load_dashboard()
        from adset_controls import deprecated_manual_placements, normalize_placement_config
        from daily_agent import (
            adset_optimization_goal_for_campaign,
            campaign_objective_for_social,
            native_campaign_creative_link,
            native_campaign_cta,
            instagram_direct_identity_missing,
            native_destination_type_for_adset,
            meta_rate_limit_guidance_from_steps,
            targeting_for_social,
            validate_campaign_targeting_before_meta,
            verify_adset_targeting_result,
        )
        from social_flow_client import SocialFlowClient
        cls.deprecated_manual_placements = staticmethod(deprecated_manual_placements)
        cls.normalize_placement_config = staticmethod(normalize_placement_config)
        cls.adset_optimization_goal_for_campaign = staticmethod(adset_optimization_goal_for_campaign)
        cls.campaign_objective_for_social = staticmethod(campaign_objective_for_social)
        cls.native_campaign_creative_link = staticmethod(native_campaign_creative_link)
        cls.native_campaign_cta = staticmethod(native_campaign_cta)
        cls.instagram_direct_identity_missing = staticmethod(instagram_direct_identity_missing)
        cls.native_destination_type_for_adset = staticmethod(native_destination_type_for_adset)
        cls.meta_rate_limit_guidance_from_steps = staticmethod(meta_rate_limit_guidance_from_steps)
        cls.targeting_for_social = staticmethod(targeting_for_social)
        cls.validate_campaign_targeting_before_meta = staticmethod(validate_campaign_targeting_before_meta)
        cls.verify_adset_targeting_result = staticmethod(verify_adset_targeting_result)
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
        self.assertEqual(adset["placements"], {"automatic": True, "manual": []})
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
        self.assertEqual(
            self.deprecated_manual_placements(["FACEBOOK_VIDEO_FEEDS"]),
            ["FACEBOOK_VIDEO_FEEDS"],
        )
        self.assertEqual(
            self.normalize_placement_config(["facebook", "feed", "story"])["manual"],
            ["FACEBOOK_FEED", "FACEBOOK_STORIES"],
        )
        self.assertEqual(
            self.normalize_placement_config(["instagram", "feed", "stories"])["manual"],
            ["INSTAGRAM_FEED", "INSTAGRAM_STORIES"],
        )

    def test_explicit_unknown_gender_is_not_silently_broadened(self):
        self.assertEqual(self.dashboard.normalize_gender_values("hombres y mujeres"), [1, 2])
        self.assertEqual(self.dashboard.normalize_gender_values("todos los géneros"), [1, 2])
        self.assertEqual(self.dashboard.normalize_gender_values("women and men"), [1, 2])
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

    def test_simple_messenger_campaign_keeps_welcome_message_in_durable_ad(self):
        """The one-ad path must not drop the native Messenger opener."""
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            output_dir.mkdir()
            created_file = Path(tmp) / "created.json"
            config = SimpleNamespace(meta_access_token="", mode="dry-run")
            with (
                mock.patch.object(self.dashboard, "OUTPUT_DIR", output_dir),
                mock.patch.object(self.dashboard, "CREATED_FILE", created_file),
                mock.patch.object(self.dashboard, "log_action"),
                mock.patch.object(self.dashboard, "load_config", return_value=config),
                mock.patch.object(self.dashboard, "load_metrics", return_value={"campaigns": []}),
                mock.patch.object(self.dashboard, "configured_ad_account_currency", return_value="USD"),
                mock.patch.object(
                    self.dashboard,
                    "paused_campaign_setup_missing_requirements",
                    return_value=["test_without_meta_write"],
                ),
            ):
                result = self.dashboard.create_campaign({
                    "name": "Messenger welcome regression",
                    "objective": "MESSAGES",
                    "daily_budget": 5,
                    "budget_confirmation": "5 USD",
                    "budget_currency": "USD",
                    "locations": ["CO"],
                    "age_min": 25,
                    "age_max": 55,
                    "targeting_mode": "manual",
                    "placements": {"automatic": True},
                    "creative_image_path": "/app/output/test.png",
                    "primary_text": "Escríbenos.",
                    "headline": "Hablemos",
                    "message_destination": "MESSENGER",
                    "welcome_message": "Hola, cuéntanos qué necesitas.",
                    "final_status": "PAUSED",
                    "active_spend_confirmed": False,
                })

            campaign = json.loads(Path(result["path"]).read_text())
            self.assertEqual(
                campaign["ad"]["welcome_message"],
                "Hola, cuéntanos qué necesitas.",
            )

    def test_messenger_welcome_without_prefilled_message_reaches_graph_payload(self):
        payload = self.SocialFlowClient.page_welcome_message_payload(
            "",
            "Hola, cuéntanos qué necesitas.",
        )
        message = payload["text_format"]["message"]
        self.assertEqual(message["text"], "Hola, cuéntanos qué necesitas.")
        self.assertEqual(
            message["ice_breakers"][0]["title"],
            "Hola, cuéntanos qué necesitas.",
        )

    def test_on_meta_image_uses_page_link_to_preserve_headline_without_cta(self):
        ad = {"on_meta_destination": True, "headline": "Tu empresa, bien respaldada", "cta": ""}
        link = self.native_campaign_creative_link(
            {"objective": "AWARENESS"},
            ad,
            {"page_id": "page_123"},
        )
        self.assertEqual(link, "https://www.facebook.com/page_123")
        self.assertEqual(self.native_campaign_cta(ad, link), "")

    def test_instagram_direct_requires_professional_actor_before_graph(self):
        self.assertTrue(self.instagram_direct_identity_missing(
            "INSTAGRAM_DIRECT",
            {"page_id": "page_123", "instagram_actor_id": ""},
        ))
        self.assertFalse(self.instagram_direct_identity_missing(
            "INSTAGRAM_DIRECT",
            {"page_id": "page_123", "instagram_actor_id": "ig_456"},
        ))
        self.assertFalse(self.instagram_direct_identity_missing(
            "MESSENGER",
            {"page_id": "page_123", "instagram_actor_id": ""},
        ))

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

    def test_structured_meta_location_is_accepted_under_plain_locations_key(self):
        source = self.dashboard.campaign_location_selection_source({
            "locations": [{"id": "457644", "name": "Barranquilla, Colombia"}],
        })
        selected = self.dashboard.parse_targeting_items(source, "location")
        self.assertEqual(selected[0]["key"], "457644")
        self.assertEqual(selected[0]["name"], "Barranquilla, Colombia")
        enriched = self.dashboard.enrich_campaign_location_selections(
            selected,
            search=lambda request: {
                "ok": True,
                "items": [{
                    "key": "457644",
                    "id": "457644",
                    "name": "Barranquilla",
                    "type": "city",
                    "country_code": "CO",
                }],
            },
        )
        self.assertEqual(enriched[0]["type"], "city")
        self.assertEqual(enriched[0]["country_code"], "CO")

    def test_structured_city_never_falls_back_to_us_and_readback_must_match(self):
        """A live city object must survive nested model payloads and Graph verification."""
        requested = self.targeting_for_social({
            "countries": ["CO"],
            "locations": [{"id": "459425", "name": "Cartagena de Indias", "type": "city"}],
            "age_min": 25,
            "age_max": 65,
            "targeting_mode": "manual",
            "placements": {"automatic": True},
        })
        self.assertEqual(requested["geo_locations"], {"cities": [{"key": "459425"}]})
        self.assertNotIn("US", requested["geo_locations"].get("countries", []))

        correct = self.verify_adset_targeting_result(requested, {
            "returncode": 0,
            "stdout": json.dumps({
                "id": "120250000000000001",
                "targeting": {
                    "geo_locations": {"cities": [{"key": "459425"}]},
                    "targeting_automation": {"advantage_audience": 0},
                },
            }),
        })
        self.assertTrue(correct["confirmed"])
        self.assertTrue(correct["geo_locations_match"])

        wrong_country = self.verify_adset_targeting_result(requested, {
            "returncode": 0,
            "stdout": json.dumps({
                "id": "120250000000000001",
                "targeting": {
                    "geo_locations": {"countries": ["US"]},
                    "targeting_automation": {"advantage_audience": 0},
                },
            }),
        })
        self.assertFalse(wrong_country["confirmed"])
        self.assertFalse(wrong_country["geo_locations_match"])
        self.assertEqual(wrong_country["persisted_geo_locations"], {"countries": ["US"]})

        class CatalogClient:
            def search_meta_targeting(self, kind, query, limit=25):
                return {"ok": True, "items": [{
                    "id": "459425", "key": "459425", "name": "Cartagena de Indias",
                    "type": "city", "country_code": "CO",
                }]}

        preflight = self.validate_campaign_targeting_before_meta({"ad_sets": [{"targeting": {
            "locations": [{"id": "459425", "name": "Cartagena de Indias", "type": "city"}],
            "age_min": 25,
            "age_max": 65,
            "targeting_mode": "manual",
        }}]}, CatalogClient())
        self.assertTrue(preflight["ok"])

        missing = self.validate_campaign_targeting_before_meta({"ad_sets": [{"targeting": {
            "age_min": 25, "age_max": 65,
        }}]}, CatalogClient())
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["validations"][0]["errors"][0]["code"], "targeting_location_missing")

        incomplete_city = self.validate_campaign_targeting_before_meta({"ad_sets": [{"targeting": {
            "locations": [{"id": "459425"}],
            "countries": ["CO"],
            "age_min": 25,
            "age_max": 65,
        }}]}, CatalogClient())
        self.assertFalse(incomplete_city["ok"])
        self.assertEqual(
            incomplete_city["validations"][0]["errors"][0]["code"],
            "targeting_location_structure_incomplete",
        )

    def test_multi_adset_durable_plan_prefers_city_and_canonicalizes_placements(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            output_dir.mkdir()
            created_file = Path(tmp) / "created.json"
            config = SimpleNamespace(meta_access_token="", mode="dry-run")
            with (
                mock.patch.object(self.dashboard, "OUTPUT_DIR", output_dir),
                mock.patch.object(self.dashboard, "CREATED_FILE", created_file),
                mock.patch.object(self.dashboard, "log_action"),
                mock.patch.object(self.dashboard, "load_config", return_value=config),
                mock.patch.object(self.dashboard, "load_metrics", return_value={"campaigns": []}),
                mock.patch.object(self.dashboard, "configured_ad_account_currency", return_value="USD"),
                mock.patch.object(
                    self.dashboard,
                    "paused_campaign_setup_missing_requirements",
                    return_value=["test_without_meta_write"],
                ),
            ):
                result = self.dashboard.create_campaign({
                    "name": "Exact nested targeting",
                    "objective": "TRAFFIC",
                    "daily_budget": 5,
                    "budget_confirmation": "5 USD",
                    "budget_currency": "USD",
                    "locations": ["CO"],
                    "placements": {"automatic": True},
                    "landing_url": "https://example.com",
                    "creative_image_path": "/app/output/test.png",
                    "primary_text": "Prueba exacta.",
                    "headline": "Exacta",
                    "final_status": "PAUSED",
                    "active_spend_confirmed": False,
                    "ad_sets": [{
                        "name": "Cartagena — Facebook",
                        "targeting": {
                            "locations": [{
                                "id": "459425", "key": "459425",
                                "name": "Cartagena de Indias", "type": "city",
                                "country_code": "CO",
                            }],
                            "countries": ["CO"],
                            "age_min": 25,
                            "age_max": 39,
                            "targeting_mode": "manual",
                        },
                        "placements": {"automatic": False, "manual": ["facebook", "feed", "story"]},
                        "ads": [{"name": "A1", "creative_image_path": "/app/output/test.png"}],
                    }],
                })

            campaign = json.loads(Path(result["path"]).read_text())
            stored = campaign["ad_sets"][0]
            self.assertNotIn("countries", stored["targeting"])
            self.assertEqual(
                stored["targeting"]["meta_targeting"]["locations"][0]["id"],
                "459425",
            )
            self.assertEqual(
                stored["placements"],
                {"automatic": False, "manual": ["FACEBOOK_FEED", "FACEBOOK_STORIES"]},
            )

    def test_natural_city_query_survives_repeated_implicit_adset_normalization(self):
        raw = {
            "name": "Cartagena exacta",
            "objective": "MESSAGES",
            "daily_budget": 5,
            "locations": ["Cartagena de Indias, Colombia"],
            "age_min": 25,
            "age_max": 65,
            "placements": {"automatic": True},
            "ads": [{"creative_image_path": "/tmp/cafe.png"}],
        }
        once = self.dashboard.normalize_campaign_stack_arguments(raw)
        twice = self.dashboard.normalize_campaign_stack_arguments(once)
        targeting = twice["ad_sets"][0]["targeting"]
        self.assertEqual(targeting["locations"], ["CO"])
        self.assertEqual(targeting["targeting_location_queries"], ["Cartagena de Indias"])

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

    def test_terra_compiler_uses_one_markdown_brief_and_persists_private_artifacts(self):
        import campaign_payload_compiler as compiler

        public_schema = compiler.destination_brief_schema("create_whatsapp_campaign")
        self.assertEqual(public_schema["required"], ["brief_markdown"])
        self.assertEqual(set(public_schema["properties"]), {"brief_markdown"})

        compiled_output = {
            "ready": True,
            "missing_fields": [],
            "payload_json": json.dumps({
                "name": "Canary Café",
                "objective": "MESSAGES",
                "daily_budget": 5,
                "budget_confirmation": "5 USD",
                "creative_image_path": "/app/output/cafe.png",
                "locations": [{"key": "459425", "name": "Cartagena de Indias", "type": "city", "country_code": "CO"}],
                "age_min": 25,
                "age_max": 65,
                "genders": [1, 2],
                "placements": {"automatic": True},
                "primary_text": "Reserva tu café hoy.",
                "headline": "Canary Café",
                "primary_text_approved": True,
                "headline_approved": True,
                "prefilled_message": "Hola, quiero reservar.",
                "creative_decision": "Reutilizar el creativo aprobado",
                "creative_approved": True,
                "prefilled_message_approved": True,
            }),
        }

        class FakeProcess:
            def __init__(self, command, **kwargs):
                self.command = command
                self.returncode = 0
                self.pid = os.getpid()

            def communicate(self, prompt, timeout=None):
                output_path = Path(self.command[self.command.index("-o") + 1])
                output_path.write_text(json.dumps(compiled_output), encoding="utf-8")
                self.prompt = prompt
                return "", ""

        original = {
            "LATEST_BRIEF_FILE": compiler.LATEST_BRIEF_FILE,
            "LATEST_PAYLOAD_FILE": compiler.LATEST_PAYLOAD_FILE,
            "CONTRACT_FILE": compiler.CONTRACT_FILE,
            "Popen": compiler.subprocess.Popen,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            try:
                compiler.LATEST_BRIEF_FILE = root / "latest-campaign.md"
                compiler.LATEST_PAYLOAD_FILE = root / "latest-campaign-payload.json"
                compiler.CONTRACT_FILE = root / "contract.md"
                compiler.CONTRACT_FILE.write_text("Never guess campaign values.", encoding="utf-8")
                compiler.subprocess.Popen = FakeProcess
                config = SimpleNamespace(codex_cli="codex", hermes_home=str(root / "hermes"))
                result = compiler.compile_campaign_brief(
                    "create_whatsapp_campaign",
                    authoritative_buyer_brief(
                        "Confirmo 5 USD diarios para Cartagena. Apruebo reutilizar la imagen "
                        "/app/output/cafe.png, el texto principal: ‘Reserva tu café hoy.’, "
                        "el título: ‘Canary Café’ y el mensaje inicial: ‘Hola, quiero reservar.’"
                    ),
                    config=config,
                )
                self.assertTrue(result["ok"])
                self.assertEqual(result["model"], "gpt-5.6-terra")
                self.assertEqual(result["payload"]["daily_budget"], 5)
                self.assertEqual(oct(compiler.LATEST_BRIEF_FILE.stat().st_mode & 0o777), "0o600")
                self.assertEqual(oct(compiler.LATEST_PAYLOAD_FILE.stat().st_mode & 0o777), "0o600")
            finally:
                compiler.LATEST_BRIEF_FILE = original["LATEST_BRIEF_FILE"]
                compiler.LATEST_PAYLOAD_FILE = original["LATEST_PAYLOAD_FILE"]
                compiler.CONTRACT_FILE = original["CONTRACT_FILE"]
                compiler.subprocess.Popen = original["Popen"]

    def test_terra_incomplete_result_reports_only_semantic_missing_facts(self):
        import campaign_payload_compiler as compiler

        class IncompleteProcess:
            def __init__(self, command, **kwargs):
                self.command = command
                self.returncode = 0
                self.pid = os.getpid()

            def communicate(self, prompt, timeout=None):
                self.prompt = prompt
                output_path = Path(self.command[self.command.index("-o") + 1])
                output_path.write_text(json.dumps({
                    "ready": False,
                    "missing_fields": ["approved creative asset path"],
                    "payload_json": "{}",
                }), encoding="utf-8")
                return "", ""

        original = {
            "LATEST_BRIEF_FILE": compiler.LATEST_BRIEF_FILE,
            "LATEST_PAYLOAD_FILE": compiler.LATEST_PAYLOAD_FILE,
            "CONTRACT_FILE": compiler.CONTRACT_FILE,
            "Popen": compiler.subprocess.Popen,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            try:
                compiler.LATEST_BRIEF_FILE = root / "latest-campaign.md"
                compiler.LATEST_PAYLOAD_FILE = root / "latest-campaign-payload.json"
                compiler.CONTRACT_FILE = root / "contract.md"
                compiler.CONTRACT_FILE.write_text("Never guess campaign values.", encoding="utf-8")
                compiler.subprocess.Popen = IncompleteProcess
                result = compiler.compile_campaign_brief(
                    "create_whatsapp_campaign",
                    authoritative_buyer_brief(
                        "Confirmo 5 USD diarios para Cartagena. Apruebo que generes una imagen, "
                        "el texto principal: ‘Reserva tu café hoy.’, el título: ‘Canary Café’ y "
                        "el mensaje inicial: ‘Hola, quiero reservar.’"
                    ),
                    config=SimpleNamespace(codex_cli="codex", hermes_home=str(root / "hermes")),
                )
                self.assertFalse(result["ok"])
                self.assertEqual(result["missing_fields"], ["approved creative asset path"])
            finally:
                compiler.LATEST_BRIEF_FILE = original["LATEST_BRIEF_FILE"]
                compiler.LATEST_PAYLOAD_FILE = original["LATEST_PAYLOAD_FILE"]
                compiler.CONTRACT_FILE = original["CONTRACT_FILE"]
                compiler.subprocess.Popen = original["Popen"]

    def test_campaign_compiler_prefers_gemini_35(self):
        import campaign_payload_compiler as compiler

        payload = {
            "name": "Canary Café",
            "daily_budget": 5,
            "budget_confirmation": "5 USD",
            "creative_image_path": "/app/output/cafe.png",
            "locations": ["Cartagena"],
            "placements": {"automatic": True},
            "primary_text": "Reserva tu café hoy.",
            "headline": "Canary Café",
            "primary_text_approved": True,
            "headline_approved": True,
            "prefilled_message": "Hola, quiero reservar.",
            "creative_decision": "Usar el creativo aprobado",
            "creative_approved": True,
            "prefilled_message_approved": True,
        }
        calls = []

        def fake_gemini(model, prompt, schema, **kwargs):
            calls.append(model)
            return {
                "ok": True,
                "model": model,
                "compiled": {"ready": True, "missing_fields": [], "payload_json": json.dumps(payload)},
            }

        def fail_terra(*args, **kwargs):
            raise AssertionError("Terra must not run after a valid Gemini 3.5 result")

        original = {
            "LATEST_BRIEF_FILE": compiler.LATEST_BRIEF_FILE,
            "LATEST_PAYLOAD_FILE": compiler.LATEST_PAYLOAD_FILE,
            "CONTRACT_FILE": compiler.CONTRACT_FILE,
            "gemini": compiler._gemini_compile,
            "terra": compiler._terra_compile,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            try:
                compiler.LATEST_BRIEF_FILE = root / "latest-campaign.md"
                compiler.LATEST_PAYLOAD_FILE = root / "latest-campaign-payload.json"
                compiler.CONTRACT_FILE = root / "contract.md"
                compiler.CONTRACT_FILE.write_text("Never guess.", encoding="utf-8")
                compiler._gemini_compile = fake_gemini
                compiler._terra_compile = fail_terra
                config = SimpleNamespace(
                    gemini_api_key="test-key",
                    agent_chat_base_url="https://generativelanguage.googleapis.com/v1beta",
                )
                result = compiler.compile_campaign_brief(
                    "create_whatsapp_campaign",
                    authoritative_buyer_brief(
                        "Confirmo 5 USD diarios para Cartagena. Apruebo usar la imagen "
                        "/app/output/cafe.png, el texto principal: ‘Reserva tu café hoy.’, "
                        "el título: ‘Canary Café’ y el mensaje inicial: ‘Hola, quiero reservar.’"
                    ),
                    config=config,
                )
                self.assertTrue(result["ok"])
                self.assertEqual(result["model"], "gemini-3.5-flash")
                self.assertEqual(calls, ["gemini-3.5-flash"])
            finally:
                compiler.LATEST_BRIEF_FILE = original["LATEST_BRIEF_FILE"]
                compiler.LATEST_PAYLOAD_FILE = original["LATEST_PAYLOAD_FILE"]
                compiler.CONTRACT_FILE = original["CONTRACT_FILE"]
                compiler._gemini_compile = original["gemini"]
                compiler._terra_compile = original["terra"]

    def test_campaign_compiler_falls_back_in_order_on_provider_and_contract_failures(self):
        import campaign_payload_compiler as compiler

        calls = []
        terra_payload = {
            "name": "Canary Café",
            "daily_budget": 5,
            "budget_confirmation": "5 USD",
            "creative_image_path": "/app/output/cafe.png",
            "locations": ["Cartagena"],
            "placements": {"automatic": True},
            "primary_text": "Reserva tu café hoy.",
            "headline": "Canary Café",
            "primary_text_approved": True,
            "headline_approved": True,
            "prefilled_message": "Hola, quiero reservar.",
            "creative_decision": "Usar el creativo aprobado",
            "creative_approved": True,
            "prefilled_message_approved": True,
        }

        def fake_gemini(model, prompt, schema, **kwargs):
            calls.append(model)
            if model == "gemini-3.5-flash":
                return {"ok": False, "model": model, "reason": "campaign_compiler_provider_failed"}
            return {
                "ok": True,
                "model": model,
                "compiled": {
                    "ready": True,
                    "missing_fields": [],
                    "payload_json": json.dumps({"name": "Dropped required fields"}),
                },
            }

        def fake_terra(prompt, schema, **kwargs):
            calls.append("gpt-5.6-terra")
            return {
                "ok": True,
                "model": "gpt-5.6-terra",
                "compiled": {"ready": True, "missing_fields": [], "payload_json": json.dumps(terra_payload)},
            }

        original = {
            "LATEST_BRIEF_FILE": compiler.LATEST_BRIEF_FILE,
            "LATEST_PAYLOAD_FILE": compiler.LATEST_PAYLOAD_FILE,
            "CONTRACT_FILE": compiler.CONTRACT_FILE,
            "gemini": compiler._gemini_compile,
            "terra": compiler._terra_compile,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            try:
                compiler.LATEST_BRIEF_FILE = root / "latest-campaign.md"
                compiler.LATEST_PAYLOAD_FILE = root / "latest-campaign-payload.json"
                compiler.CONTRACT_FILE = root / "contract.md"
                compiler.CONTRACT_FILE.write_text("Never guess.", encoding="utf-8")
                compiler._gemini_compile = fake_gemini
                compiler._terra_compile = fake_terra
                config = SimpleNamespace(
                    gemini_api_key="test-key",
                    agent_chat_base_url="https://generativelanguage.googleapis.com/v1beta",
                )
                result = compiler.compile_campaign_brief(
                    "create_whatsapp_campaign",
                    authoritative_buyer_brief(
                        "Confirmo 5 USD diarios para Cartagena. Apruebo usar la imagen "
                        "/app/output/cafe.png, el texto principal: ‘Reserva tu café hoy.’, "
                        "el título: ‘Canary Café’ y el mensaje inicial: ‘Hola, quiero reservar.’"
                    ),
                    config=config,
                )
                self.assertTrue(result["ok"])
                self.assertEqual(result["model"], "gpt-5.6-terra")
                self.assertEqual(calls, ["gemini-3.5-flash", "gemini-3.6-flash", "gpt-5.6-terra"])
                self.assertEqual([item["model"] for item in result["compiler_attempts"]], calls)
            finally:
                compiler.LATEST_BRIEF_FILE = original["LATEST_BRIEF_FILE"]
                compiler.LATEST_PAYLOAD_FILE = original["LATEST_PAYLOAD_FILE"]
                compiler.CONTRACT_FILE = original["CONTRACT_FILE"]
                compiler._gemini_compile = original["gemini"]
                compiler._terra_compile = original["terra"]

    def test_campaign_compiler_does_not_fallback_after_valid_ambiguity_refusal(self):
        import campaign_payload_compiler as compiler

        calls = []

        def fake_gemini(model, prompt, schema, **kwargs):
            calls.append(model)
            return {
                "ok": True,
                "model": model,
                "compiled": {
                    "ready": False,
                    "missing_fields": ["daily_budget", "locations"],
                    "payload_json": "{}",
                },
            }

        def fail_terra(*args, **kwargs):
            raise AssertionError("A valid ambiguity refusal must be terminal")

        original = {
            "LATEST_BRIEF_FILE": compiler.LATEST_BRIEF_FILE,
            "LATEST_PAYLOAD_FILE": compiler.LATEST_PAYLOAD_FILE,
            "CONTRACT_FILE": compiler.CONTRACT_FILE,
            "gemini": compiler._gemini_compile,
            "terra": compiler._terra_compile,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            try:
                compiler.LATEST_BRIEF_FILE = root / "latest-campaign.md"
                compiler.LATEST_PAYLOAD_FILE = root / "latest-campaign-payload.json"
                compiler.CONTRACT_FILE = root / "contract.md"
                compiler.CONTRACT_FILE.write_text("Never guess.", encoding="utf-8")
                compiler._gemini_compile = fake_gemini
                compiler._terra_compile = fail_terra
                config = SimpleNamespace(
                    gemini_api_key="test-key",
                    agent_chat_base_url="https://generativelanguage.googleapis.com/v1beta",
                )
                result = compiler.compile_campaign_brief(
                    "create_whatsapp_campaign",
                    authoritative_buyer_brief(
                        "Usa 5 o 10 USD y escoge tú una ciudad conveniente. Apruebo usar la imagen "
                        "/app/output/cafe.png, el texto principal: ‘Reserva tu café hoy.’, "
                        "el título: ‘Canary Café’ y el mensaje inicial: ‘Hola, quiero reservar.’"
                    ),
                    config=config,
                )
                self.assertFalse(result["ok"])
                self.assertEqual(result["reason"], "campaign_brief_incomplete")
                self.assertEqual(result["missing_fields"], ["daily_budget", "locations"])
                self.assertEqual(calls, ["gemini-3.5-flash"])
            finally:
                compiler.LATEST_BRIEF_FILE = original["LATEST_BRIEF_FILE"]
                compiler.LATEST_PAYLOAD_FILE = original["LATEST_PAYLOAD_FILE"]
                compiler.CONTRACT_FILE = original["CONTRACT_FILE"]
                compiler._gemini_compile = original["gemini"]
                compiler._terra_compile = original["terra"]

    def test_campaign_compiler_requires_explicit_audience_automation_decision(self):
        import campaign_payload_compiler as compiler

        approved_ad_material = {
            "primary_text": "Reserva hoy.",
            "headline": "Reserva ahora",
            "primary_text_approved": True,
            "headline_approved": True,
            "creative_decision": "Reutilizar /app/output/existing.png",
            "creative_approved": True,
        }

        self.assertEqual(
            compiler._brief_targeting_mode(
                "Activa audiencia Advantage+ y usa placements automáticos Advantage+."
            ),
            "advantage_plus",
        )
        self.assertEqual(
            compiler._brief_targeting_mode(
                "Segmentación manual, sin expansión Advantage+ de audiencia."
            ),
            "manual",
        )
        self.assertEqual(
            compiler._brief_targeting_mode("Usa placements automáticos Advantage+."),
            "",
        )
        self.assertEqual(
            compiler._brief_targeting_mode(
                "Conjunto A: targeting_mode: manual. Conjunto B: Advantage+ Audience activado."
            ),
            "mixed",
        )
        self.assertEqual(
            compiler._brief_targeting_mode(
                "Conjunto A: Targeting mode: manual; advantage audience: false. "
                "Conjunto B: advantage_audience: true."
            ),
            "mixed",
        )

        candidate = {
            "ok": True,
            "model": "gemini-3.5-flash",
            "compiled": {
                "ready": True,
                "missing_fields": [],
                "payload_json": json.dumps({
                    **approved_ad_material,
                    "name": "Canary Web",
                    "daily_budget": 9,
                    "budget_confirmation": "9 USD",
                    "locations": ["Bogotá"],
                    "placements": {"automatic": True},
                    "landing_url": "https://example.com",
                }),
            },
        }
        rejected = compiler._validate_compiled_candidate(
            "website",
            candidate,
            expected_targeting_mode="advantage_plus",
        )
        self.assertFalse(rejected["terminal"])
        self.assertEqual(rejected["missing_fields"], ["targeting_mode"])

        mixed_candidate = {
            "ok": True,
            "model": "gemini-3.6-flash",
            "compiled": {
                "ready": True,
                "missing_fields": [],
                "payload_json": json.dumps({
                    **approved_ad_material,
                    "name": "Canary Mixed",
                    "daily_budget": 8,
                    "budget_confirmation": "8 USD",
                    "locations": ["CO"],
                    "placements": {"automatic": True},
                    "landing_url": "https://example.com",
                    "ad_sets": [
                        {"name": "Manual", "targeting_mode": "manual"},
                        {"name": "Advantage", "targeting_mode": "advantage_plus"},
                    ],
                }),
            },
        }
        accepted_mixed = compiler._validate_compiled_candidate(
            "website", mixed_candidate, expected_targeting_mode="mixed"
        )
        self.assertTrue(accepted_mixed["terminal"])
        self.assertTrue(accepted_mixed["ok"])

        mixed_candidate["compiled"]["payload_json"] = json.dumps({
            **approved_ad_material,
            "name": "Canary Mixed",
            "daily_budget": 8,
            "budget_confirmation": "8 USD",
            "locations": ["CO"],
            "placements": {"automatic": True},
            "landing_url": "https://example.com",
            "ad_sets": [
                {"name": "Manual", "targeting_mode": "manual"},
                {"name": "Dropped", "targeting_mode": "manual"},
            ],
        })
        rejected_mixed = compiler._validate_compiled_candidate(
            "website", mixed_candidate, expected_targeting_mode="mixed"
        )
        self.assertFalse(rejected_mixed["terminal"])
        self.assertEqual(rejected_mixed["missing_fields"], ["ad_sets[].targeting_mode"])

        mixed_candidate["compiled"]["payload_json"] = json.dumps({
            **approved_ad_material,
            "name": "Canary Mixed",
            "daily_budget": 8,
            "budget_confirmation": "8 USD",
            "locations": ["CO"],
            "placements": {"automatic": True},
            "landing_url": "https://example.com",
            "ad_sets": [
                {"name": "Manual", "advantage_audience": False},
                {"name": "Advantage", "advantage_audience": True},
            ],
        })
        normalized_mixed = compiler._validate_compiled_candidate(
            "website", mixed_candidate, expected_targeting_mode="mixed"
        )
        self.assertTrue(normalized_mixed["ok"])
        self.assertEqual(
            [item["targeting_mode"] for item in normalized_mixed["payload"]["ad_sets"]],
            ["manual", "advantage_plus"],
        )

        refusal = {
            "ok": True,
            "model": "gpt-5.6-terra",
            "compiled": {
                "ready": False,
                "missing_fields": ["creative_approved"],
                "payload_json": "{}",
            },
        }
        refused_mixed = compiler._validate_compiled_candidate(
            "whatsapp", refusal, expected_targeting_mode="mixed"
        )
        self.assertTrue(refused_mixed["terminal"])
        self.assertEqual(refused_mixed["reason"], "campaign_brief_incomplete")
        self.assertEqual(refused_mixed["missing_fields"], ["creative_approved"])

        placement_candidate = {
            "ok": True,
            "model": "gpt-5.6-terra",
            "compiled": {
                "ready": True,
                "missing_fields": [],
                "payload_json": json.dumps({
                    **approved_ad_material,
                    "name": "Placement Matrix",
                    "daily_budget": 8,
                    "budget_confirmation": "8 USD",
                    "locations": ["CO"],
                    "placements": {"automatic": True},
                    "landing_url": "https://example.com",
                    "ad_sets": [
                        {"name": "A", "placements": {"automatic": True}},
                        {"name": "B", "placements": {"automatic": True}},
                    ],
                }),
            },
        }
        dropped_placements = compiler._validate_compiled_candidate(
            "website",
            placement_candidate,
            expected_manual_placements={"facebook_feed", "instagram_story"},
        )
        self.assertFalse(dropped_placements["terminal"])
        self.assertIn("manual_placements:", dropped_placements["missing_fields"][0])

        self.assertEqual(
            compiler._brief_manual_placements(
                "Conjunto B: solo Facebook Feed y Stories.\n"
                "Conjunto C: solo Instagram Feed y Stories.\n"
                "Conjunto D: Facebook Feed, Stories, Facebook Video Feeds y Facebook Reels."
            ),
            {"facebook_feed", "facebook_story", "facebook_video_feeds", "facebook_reels", "instagram_feed", "instagram_story"},
        )
        placement_candidate["compiled"]["payload_json"] = json.dumps({
            **approved_ad_material,
            "name": "Placement Matrix",
            "daily_budget": 8,
            "budget_confirmation": "8 USD",
            "locations": ["CO"],
            "placements": {"automatic": True},
            "landing_url": "https://example.com",
            "ad_sets": [
                {"name": "B", "placements": {"automatic": False, "manual": ["facebook", "feed", "story"]}},
                {"name": "C", "placements": {"automatic": False, "manual": ["instagram", "feed", "story"]}},
            ],
        })
        canonical_placements = compiler._validate_compiled_candidate(
            "website",
            placement_candidate,
            expected_manual_placements={"facebook_feed", "facebook_story", "instagram_feed", "instagram_story"},
        )
        self.assertTrue(canonical_placements["ok"])
        self.assertEqual(
            canonical_placements["payload"]["ad_sets"][0]["placements"]["manual"],
            ["facebook_feed", "facebook_story"],
        )
        self.assertEqual(
            canonical_placements["payload"]["ad_sets"][1]["placements"]["manual"],
            ["instagram_feed", "instagram_story"],
        )

        placement_candidate["compiled"]["payload_json"] = json.dumps({
            **approved_ad_material,
            "name": "Placement arrays",
            "daily_budget": 8,
            "budget_confirmation": "8 USD",
            "locations": ["CO"],
            "placements": {"automatic": True},
            "landing_url": "https://example.com",
            "ad_sets": [{
                "name": "D",
                "placements": ["facebook_feed", "facebook_story", "facebook_video_feeds"],
            }],
        })
        canonical_array_placements = compiler._validate_compiled_candidate(
            "website",
            placement_candidate,
            expected_manual_placements={"facebook_feed", "facebook_story", "facebook_video_feeds"},
        )
        self.assertTrue(canonical_array_placements["ok"])
        self.assertEqual(
            canonical_array_placements["payload"]["ad_sets"][0]["placements"],
            {"automatic": False, "manual": ["facebook_feed", "facebook_story", "facebook_video_feeds"]},
        )

        placement_candidate["compiled"]["payload_json"] = json.dumps({
            **approved_ad_material,
            "name": "Incomplete city",
            "daily_budget": 8,
            "budget_confirmation": "8 USD",
            "locations": ["CO"],
            "placements": {"automatic": True},
            "landing_url": "https://example.com",
            "ad_sets": [{
                "name": "Cartagena",
                "locations": [{"id": "459425"}],
                "placements": {"automatic": True},
            }],
        })
        incomplete_compiled_city = compiler._validate_compiled_candidate(
            "website", placement_candidate
        )
        self.assertFalse(incomplete_compiled_city["terminal"])
        self.assertEqual(
            incomplete_compiled_city["missing_fields"],
            ["ad_sets[0].locations[0].type"],
        )

        self.assertEqual(
            compiler._brief_explicit_meta_location_ids(
                "Cartagena, Meta city ID 459425; Pereira con ID de ciudad 476114."
            ),
            {"459425", "476114"},
        )
        placement_candidate["compiled"]["payload_json"] = json.dumps({
            **approved_ad_material,
            "name": "Dropped exact ID",
            "daily_budget": 8,
            "budget_confirmation": "8 USD",
            "locations": ["CO"],
            "placements": {"automatic": True},
            "landing_url": "https://example.com",
            "ad_sets": [{
                "name": "Cartagena",
                "locations": ["Cartagena"],
                "placements": {"automatic": True},
            }],
        })
        dropped_exact_id = compiler._validate_compiled_candidate(
            "website", placement_candidate, expected_location_ids={"459425"}
        )
        self.assertFalse(dropped_exact_id["terminal"])
        self.assertEqual(dropped_exact_id["missing_fields"], ["meta_location_id:459425"])

        whatsapp_matrix = {
            **approved_ad_material,
            "name": "WA Matrix",
            "daily_budget": 8,
            "budget_confirmation": "8 USD diarios",
            "creative_decision": "Reutilizar /app/output/existing.png",
            "creative_approved": True,
            "prefilled_message_approved": True,
            "ad_sets": [
                {
                    "name": "A",
                    "locations": ["Cartagena"],
                    "placements": {"automatic": True},
                    "prefilled_message": "Hola desde Cartagena",
                },
                {
                    "name": "B",
                    "locations": ["Pereira"],
                    "placements": {"automatic": False, "manual": ["facebook_feed"]},
                    "prefilled_message": "Hola desde Pereira",
                },
            ],
        }
        self.assertEqual(compiler._missing_required_fields("whatsapp", whatsapp_matrix), [])

        from admira_tool_bridge import destination_campaign_arguments
        normalized_wa, wa_error = destination_campaign_arguments(
            "admira_create_whatsapp_campaign",
            whatsapp_matrix,
            budget_parser=lambda _text, default=None: 8,
        )
        self.assertEqual(wa_error, "")
        self.assertEqual(len(normalized_wa["ad_sets"]), 2)
        self.assertTrue(normalized_wa["ad_sets"][0]["placements"]["automatic"])
        self.assertEqual(
            normalized_wa["ad_sets"][1]["placements"]["manual"],
            ["facebook_feed"],
        )

    def test_website_destination_without_explicit_objective_defaults_to_traffic(self):
        from admira_tool_bridge import destination_campaign_arguments

        approved_ad_material = {
            "primary_text": "Reserva hoy.",
            "headline": "Reserva ahora",
            "primary_text_approved": True,
            "headline_approved": True,
            "creative_decision": "Usar /app/output/example.png",
            "creative_approved": True,
        }

        arguments, error = destination_campaign_arguments(
            "admira_create_website_campaign",
            {
                **approved_ad_material,
                "name": "Canary Web",
                "daily_budget": 9,
                "budget_confirmation": "9 USD",
                "locations": ["Bogotá"],
                "placements": {"automatic": True},
                "landing_url": "https://example.com",
                "creative_image_path": "/app/output/example.png",
            },
            budget_parser=lambda _text, default=None: 9,
        )
        self.assertEqual(error, "")
        self.assertEqual(arguments["objective"], "TRAFFIC")

        explicit, error = destination_campaign_arguments(
            "admira_create_website_campaign",
            {
                **approved_ad_material,
                "name": "Canary Sales",
                "objective": "OUTCOME_SALES",
                "daily_budget": 9,
                "budget_confirmation": "9 USD",
                "locations": ["Bogotá"],
                "placements": {"automatic": True},
                "landing_url": "https://example.com",
                "creative_image_path": "/app/output/example.png",
            },
            budget_parser=lambda _text, default=None: 9,
        )
        self.assertEqual(error, "")
        self.assertEqual(explicit["objective"], "OUTCOME_SALES")


if __name__ == "__main__":
    unittest.main()
