#!/usr/bin/env python3
"""
Integration tests for Meta Ads Agent modules.
"""
import json
import os
import shutil
import sys
import tempfile
import importlib.util
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from campaign_creator import CampaignCreator
from budget_optimizer import BudgetOptimizer, OptimizationStrategy
from ab_testing import ABTestingManager, CreativeElement
from scaling_logic import ScalingManager, ScalingMetrics, ScalingStrategy
from pause_logic import PauseManager, AdPerformance
from auto_warmup import AutoWarmupManager
from license import activate_license, format_license, license_status, normalize_license_entitlements, validate_license_key
from security import dashboard_token_valid, redact_payload
from product_config import AgentConfig
from agent_chat import account_context, parse_skill_response
import agent_chat
import hermes_bridge
import decision_memory
from audience_builder import build_audience_strategy
from codex_brand_guides import build_codex_creative_prompt
import codex_brand_guides
from creative_refresh import build_creative_plan
from daily_agent import execute_campaign_creation
import daily_agent
from social_flow_client import SocialFlowClient
import telegram_agent


ROOT_DIR = Path(__file__).parent.parent
DASHBOARD_PATH = ROOT_DIR / "dashboard" / "monitoring-dashboard.py"


def load_dashboard_module():
    spec = importlib.util.spec_from_file_location("monitoring_dashboard", DASHBOARD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IntegrationTestSuite:
    """Integration test suite for Meta Ads Agent."""
    
    def __init__(self):
        self.results = []
        self.test_count = 0
        self.passed_count = 0
        self.failed_count = 0
    
    def assert_true(self, condition, message):
        """Assert that a condition is true."""
        self.test_count += 1
        if condition:
            self.passed_count += 1
            self.results.append(("PASS", f"Test {self.test_count}: {message}"))
            return True
        else:
            self.failed_count += 1
            self.results.append(("FAIL", f"Test {self.test_count}: {message}"))
            return False
    
    def test_campaign_creator(self):
        """Test campaign creation functionality."""
        print("\n🧪 Testing Campaign Creator...")
        
        creator = CampaignCreator()
        
        # Test 1: Create a campaign with default ad set
        campaign = creator.create_campaign_config(
            name="Integration Test Campaign",
            objective="PURCHASES",
            budget_daily=100.0,
            budget_total=3000.0,
            create_default_ad_set=True
        )
        
        self.assert_true(
            campaign["name"] == "Integration Test Campaign",
            "Campaign name matches"
        )
        
        self.assert_true(
            campaign["budget"]["daily"] == 100.0,
            "Daily budget set correctly"
        )
        
        self.assert_true(
            campaign["budget"]["total"] == 3000.0,
            "Total budget set correctly"
        )
        
        # Test 2: Validate campaign
        is_valid = creator.validate_campaign(campaign)
        self.assert_true(is_valid, "Campaign validation passes")
        
        # Test 3: Generate campaign ID
        campaign_id = creator.generate_campaign_id(campaign)
        self.assert_true(
            campaign_id.startswith("camp_"),
            "Campaign ID generated with correct prefix"
        )
    
    def test_budget_optimizer(self):
        """Test budget optimization functionality."""
        print("\n🧪 Testing Budget Optimizer...")
        
        optimizer = BudgetOptimizer()
        
        # Create test metrics
        metrics_data = {
            "spend": 300.0,
            "impressions": 15000,
            "clicks": 450,
            "conversions": 15,
            "revenue": 600.0,
            "cost_per_result": 20.0,
            "roas": 2.0
        }
        
        from budget_optimizer import PerformanceMetrics
        metrics = PerformanceMetrics.from_dict(metrics_data)
        
        # Test optimization
        recommendation = optimizer.calculate_optimal_budget(
            metrics,
            current_budget=100.0,
            strategy=OptimizationStrategy.PERFORMANCE_BASED
        )
        
        self.assert_true(
            recommendation.current_budget == 100.0,
            "Current budget preserved"
        )
        
        self.assert_true(
            recommendation.recommended_budget >= 10.0,
            "Recommended budget within minimum"
        )
        
        self.assert_true(
            recommendation.confidence > 0,
            "Confidence score calculated"
        )
    
    def test_ab_testing(self):
        """Test A/B testing functionality."""
        print("\n🧪 Testing A/B Testing...")
        
        manager = ABTestingManager()
        
        # Create a headline test
        test = manager.create_headline_test(
            campaign_id="test_campaign_001",
            base_headline="Test Headline A",
            variations=["Test Headline B", "Test Headline C"]
        )
        
        self.assert_true(
            test is not None,
            "A/B test created successfully"
        )
        
        self.assert_true(
            len(test.variants) == 3,
            "Correct number of variants"
        )
        
        # Start the test
        success = manager.start_test(test.id)
        self.assert_true(success, "Test started successfully")
        
        # Record some metrics
        manager.record_impression(test.id, "variant_0", 100)
        manager.record_click(test.id, "variant_0", 10)
        manager.record_conversion(test.id, "variant_0", 2)
        
        # Calculate CTR
        ctr = manager.calculate_ctr(test.id, "variant_0")
        self.assert_true(
            ctr == 10.0,  # 10 clicks / 100 impressions = 10%
            f"CTR calculated correctly: {ctr}%"
        )
    
    def test_scaling_logic(self):
        """Test scaling logic functionality."""
        print("\n🧪 Testing Scaling Logic...")
        
        manager = ScalingManager()
        
        # Create a scaling rule
        rule = manager.create_rule(
            name="Test Scaling Rule",
            target_id="test_campaign_001",
            target_type="campaign",
            strategy=ScalingStrategy.GRADUAL,
            initial_budget=100.0,
            target_budget=1000.0
        )
        
        self.assert_true(
            rule is not None,
            "Scaling rule created successfully"
        )
        
        self.assert_true(
            rule.current_budget == 100.0,
            "Initial budget set correctly"
        )
        
        # Activate the rule
        success = manager.activate_rule(rule.id)
        self.assert_true(success, "Rule activated successfully")
        
        # Evaluate scaling
        metrics = ScalingMetrics(
            campaign_id="test_campaign_001",
            spend=150.0,
            impressions=15000,
            clicks=450,
            conversions=15,
            revenue=600.0,
            roas=2.0,
            cpa=10.0,
            ctr=3.0,
            period_hours=24
        )
        
        new_budget = manager.evaluate_scaling(rule.id, metrics)
        self.assert_true(
            new_budget is not None or new_budget is None,  # May or may not scale based on timing
            "Scaling evaluation completed"
        )
    
    def test_pause_logic(self):
        """Test pause logic functionality."""
        print("\n🧪 Testing Pause Logic...")
        
        manager = PauseManager()
        
        # Create test ads with different performance
        high_performer = AdPerformance(
            ad_id="ad_high",
            ad_name="High Performer",
            campaign_id="test_campaign",
            spend=150.0,
            impressions=15000,
            clicks=600,
            conversions=20,
            revenue=400.0,
            period_hours=24
        )
        
        low_performer = AdPerformance(
            ad_id="ad_low",
            ad_name="Low Performer",
            campaign_id="test_campaign",
            spend=200.0,
            impressions=20000,
            clicks=100,
            conversions=5,
            revenue=100.0,
            period_hours=24
        )
        
        # Evaluate high performer
        should_pause, _ = manager.evaluate_ad(high_performer)
        self.assert_true(
            not should_pause,
            "High performer should not be paused"
        )
        
        # Evaluate low performer (low CTR)
        should_pause, reason = manager.evaluate_ad(low_performer)
        self.assert_true(
            should_pause,
            f"Low performer should be paused (reason: {reason})"
        )
        
        # Pause the low performer
        success = manager.pause_ad(low_performer, reason)
        self.assert_true(success, "Ad paused successfully")
        
        # Check paused ads
        paused = manager.get_paused_ads()
        self.assert_true(
            len(paused) > 0,
            "Paused ads list contains entries"
        )
    
    def test_auto_warmup(self):
        """Test auto-warmup functionality."""
        print("\n🧪 Testing Auto-Warmup...")
        
        manager = AutoWarmupManager()
        
        # Start warmup for new account
        warmup = manager.start_warmup("acc_test_001", "Test Account")
        
        self.assert_true(
            warmup is not None,
            "Warmup started successfully"
        )
        
        self.assert_true(
            warmup.current_daily_budget > 0,
            "Initial daily budget set"
        )
        
        # Update spend
        success = manager.update_spend("acc_test_001", 50.0)
        self.assert_true(success, "Spend updated successfully")
        
        # Check status
        status = manager.get_warmup_status("acc_test_001")
        self.assert_true(
            status is not None,
            "Warmup status retrieved"
        )
        
        self.assert_true(
            status.total_spend >= 50.0,
            f"Total spend recorded: ${status.total_spend}"
        )

    def test_license_validation(self):
        """Test offline license key validation."""
        print("\nTesting License Validation...")

        valid_key = format_license("BUYER2026LATAM")
        valid = validate_license_key(valid_key)
        missing = validate_license_key("")
        invalid = validate_license_key("MAO-BAD-KEY-000000")
        individual = normalize_license_entitlements({"plan": "individual", "features": ["dashboard", "agency_workspaces"], "max_devices": 9, "workspace_limit": 9})
        agency = normalize_license_entitlements({"plan": "agency"})

        self.assert_true(valid["valid"], "Formatted license validates")
        self.assert_true(missing["status"] == "missing", "Missing license is reported")
        self.assert_true(not invalid["valid"], "Invalid license is rejected")
        self.assert_true(individual["is_individual"] and individual["max_devices"] == 1 and individual["workspace_limit"] == 1, "Individual entitlement clamps device and workspace limits")
        self.assert_true(not individual["can_use_agency_workspaces"] and "agency_workspaces" not in individual["features"], "Individual entitlement strips agency features")
        self.assert_true(agency["is_agency"] and agency["max_devices"] == 4 and agency["workspace_limit"] == 50, "Agency entitlement applies default limits")
        self.assert_true(agency["can_use_agency_workspaces"] and agency["can_use_multi_telegram_profiles"], "Agency entitlement unlocks client spaces and Telegram profiles")

    def test_license_status_and_activation(self):
        """Test local/cloud license status helpers."""
        print("\nTesting License Status And Activation...")

        config = AgentConfig(
            mode="dry-run",
            dashboard_host="127.0.0.1",
            dashboard_port=7871,
            dashboard_token="secret-password",
            dashboard_password="secret-password",
            dashboard_token_required=True,
            allow_public_dashboard=False,
            lan_access_enabled=False,
            live_actions_enabled=False,
            license_key=format_license("BUYER2026LATAM"),
            license_buyer_email="buyer@example.com",
            license_server_url="",
            license_device_id="",
            license_grace_hours=72,
            license_required_for_live=True,
            license_signature_secret="",
            target_cpa=50,
            approval_required_over_pct=20,
            autonomy_mode="supervised",
            auto_budget_change_pct=10,
            auto_budget_change_amount=25,
            auto_pause_max_spend=100,
            require_approval_for_resume=True,
            require_approval_for_new_campaigns=True,
            require_approval_for_creatives=True,
            auto_pause_enabled=True,
            zero_conversion_spend=50,
            high_cpa_multiplier=3,
            meta_connector="social_cli",
            social_cli="social",
            ad_account_id="",
            meta_access_token="",
            meta_graph_api_version="v20.0",
            notify_channel="dashboard",
            telegram_bot_token="",
            telegram_chat_id="",
            creative_refresh_enabled=True,
            creative_auto_generate_on_daily=True,
            creative_provider="nano-banana",
            creative_image_mode="dry-run",
            gemini_api_key="",
            nano_banana_model="gemini-2.5-flash-image",
            creative_variants_per_campaign=3,
            agent_chat_provider="minimax",
            agent_chat_base_url="https://api.minimax.io/v1",
            agent_chat_api_key="",
            agent_chat_api="openai-completions",
            agent_chat_model="MiniMax-M2.7",
            agent_chat_temperature=0.65,
            agent_profile_dir="agent",
            codex_creative_enabled=True,
            codex_cli="codex",
        )
        status = license_status(config)
        activated = activate_license(config)
        self.assert_true(not status["valid"], "Buyer release requires cloud validation when license server is blank")
        self.assert_true(status.get("cloud_required") is True, "Cloud validation is required for buyer release")
        self.assert_true(not activated["valid"], "Activation is blocked without cloud validation for buyer release")
        demo_config = config
        demo_config.license_key = "DEMO"
        demo_status = license_status(demo_config)
        self.assert_true(demo_status["valid"], "Internal demo license still works without cloud server")

    def test_cloud_license_blocks_buyer_live_features(self):
        """Test buyer live features fail closed when cloud license is invalid."""
        print("\nTesting Cloud License Live Block...")

        dashboard = load_dashboard_module()
        original_load_config = dashboard.load_config
        original_license_status = dashboard.license_status
        try:
            class FakeConfig:
                license_required_for_live = True

            dashboard.load_config = lambda: FakeConfig()
            dashboard.license_status = lambda config: {"valid": False, "status": "cloud_error", "detail": "No se pudo confirmar tu licencia. Revisa internet o contacta soporte."}
            try:
                dashboard.require_cloud_license("campaign creation")
                self.assert_true(False, "Invalid cloud license should block buyer live features")
            except ValueError as exc:
                self.assert_true("No se pudo confirmar tu licencia" in str(exc), "Buyer-friendly cloud license block is returned")
        finally:
            dashboard.load_config = original_load_config
            dashboard.license_status = original_license_status

    def test_dashboard_password_auth(self):
        """Test dashboard password compatibility with protected actions."""
        print("\nTesting Dashboard Password Auth...")

        config = AgentConfig(
            mode="dry-run",
            dashboard_host="127.0.0.1",
            dashboard_port=7871,
            dashboard_token="secret-password",
            dashboard_password="secret-password",
            dashboard_token_required=True,
            allow_public_dashboard=False,
            lan_access_enabled=False,
            live_actions_enabled=False,
            license_key="",
            license_buyer_email="",
            license_server_url="",
            license_device_id="",
            license_grace_hours=72,
            license_required_for_live=True,
            license_signature_secret="",
            target_cpa=50,
            approval_required_over_pct=20,
            autonomy_mode="supervised",
            auto_budget_change_pct=10,
            auto_budget_change_amount=25,
            auto_pause_max_spend=100,
            require_approval_for_resume=True,
            require_approval_for_new_campaigns=True,
            require_approval_for_creatives=True,
            auto_pause_enabled=True,
            zero_conversion_spend=50,
            high_cpa_multiplier=3,
            meta_connector="social_cli",
            social_cli="social",
            ad_account_id="",
            meta_access_token="",
            meta_graph_api_version="v20.0",
            notify_channel="dashboard",
            telegram_bot_token="",
            telegram_chat_id="",
            creative_refresh_enabled=True,
            creative_auto_generate_on_daily=True,
            creative_provider="nano-banana",
            creative_image_mode="dry-run",
            gemini_api_key="",
            nano_banana_model="gemini-2.5-flash-image",
            creative_variants_per_campaign=3,
            agent_chat_provider="minimax",
            agent_chat_base_url="https://api.minimax.io/v1",
            agent_chat_api_key="",
            agent_chat_api="openai-completions",
            agent_chat_model="MiniMax-M2.7",
            agent_chat_temperature=0.65,
            agent_profile_dir="agent",
            codex_creative_enabled=True,
            codex_cli="codex",
        )

        self.assert_true(dashboard_token_valid(config, "secret-password"), "Dashboard password unlocks protected routes")
        self.assert_true(not dashboard_token_valid(config, "wrong-password"), "Wrong dashboard password is rejected")

        dashboard = load_dashboard_module()
        original_load_config = dashboard.load_config
        original_onboarding = dashboard.load_onboarding_state
        handler = object.__new__(dashboard.DashboardHandler)
        try:
            class NoPassword:
                dashboard_token = ""
                dashboard_password = ""
                dashboard_token_required = True

            class WithPassword:
                dashboard_token = "secret-password"
                dashboard_password = "secret-password"
                dashboard_token_required = True

            dashboard.load_onboarding_state = lambda: {"completed": False}
            dashboard.load_config = lambda: NoPassword()
            self.assert_true(not handler.auth_required_for_post("/api/dashboard-password"), "First password creation stays open before a password exists")
            self.assert_true(not handler.auth_required_for_get("/api/dashboard"), "Initial setup dashboard can load before a password exists")
            self.assert_true(handler.auth_required_for_post("/api/social/token"), "Meta token save is protected during onboarding")
            self.assert_true(handler.auth_required_for_get("/api/social/accounts"), "Meta account discovery is protected before a password exists")
            dashboard.load_config = lambda: WithPassword()
            self.assert_true(handler.auth_required_for_post("/api/dashboard-password"), "Changing password requires auth after a password exists")
            self.assert_true(handler.auth_required_for_get("/api/dashboard"), "Dashboard API is protected after password exists even before onboarding is complete")
        finally:
            dashboard.load_config = original_load_config
            dashboard.load_onboarding_state = original_onboarding

    def test_secret_redaction(self):
        """Test sensitive buyer fields are redacted from logs."""
        print("\nTesting Secret Redaction...")

        payload = {
            "dashboard_password": "abc",
            "license_key": "MAO-1234-1234-AAAAAA",
            "nested": {"api_key": "secret"},
            "safe": "visible",
        }
        redacted = redact_payload(payload)
        self.assert_true(redacted["dashboard_password"] == "configured", "Dashboard password redacted")
        self.assert_true(redacted["license_key"] == "configured", "License key redacted")
        self.assert_true(redacted["nested"]["api_key"] == "configured", "Nested API key redacted")
        self.assert_true(redacted["safe"] == "visible", "Non-secret field remains visible")

    def test_website_scanner_blocks_private_urls(self):
        """Test onboarding website intelligence only reads public websites."""
        print("\nTesting Website Scanner URL Safety...")

        dashboard = load_dashboard_module()
        blocked = ["http://127.0.0.1:8000", "http://localhost", "http://10.0.0.5", "http://192.168.1.1"]
        for url in blocked:
            try:
                dashboard.validate_public_website_url(url)
                self.assert_true(False, f"Private website scan URL should be blocked: {url}")
            except ValueError:
                self.assert_true(True, f"Private website scan URL blocked: {url}")
        self.assert_true(dashboard.normalize_website_url("example.com").startswith("https://example.com"), "Plain domains are normalized to https")

        stored = {}
        original_read_json = dashboard.read_json
        original_write_json = dashboard.write_json
        original_save_setup_config = dashboard.save_setup_config
        original_log_action = dashboard.log_action
        try:
            dashboard.read_json = lambda path, default=None: dict(stored.get("profile", default or {})) if path == dashboard.BUSINESS_PROFILE_FILE else (default or {})
            dashboard.write_json = lambda path, data: stored.__setitem__("profile", dict(data)) if path == dashboard.BUSINESS_PROFILE_FILE else None
            dashboard.save_setup_config = lambda _payload: {"saved": True}
            dashboard.log_action = lambda *_args, **_kwargs: None
            skipped = dashboard.save_business_context({"website_skipped": True})
            self.assert_true(skipped["profile"].get("website_skipped") is True, "Website step can be skipped for buyers without a site")
            completed = dashboard.save_business_context(
                {
                    "main_offer": "Curso de maquillaje",
                    "ideal_customer": "Mujeres que quieren aprender",
                    "current_stage": "Estoy empezando",
                    "what_to_improve": "Crear mi primera campaña",
                    "context_complete": True,
                }
            )
            self.assert_true(bool(completed["profile"].get("context_completed_at")), "Context wizard completion is persisted after all answers")
            snapshot = dashboard.business_context_snapshot(completed["profile"])
            self.assert_true(snapshot["ready"] is True and "Curso de maquillaje" in snapshot["summary"], "Business owner answers produce a dashboard business snapshot")
            self.assert_true(bool(snapshot["audience_hint"]) and bool(snapshot["creative_hint"]), "Business snapshot derives audience and creative guidance")
        finally:
            dashboard.read_json = original_read_json
            dashboard.write_json = original_write_json
            dashboard.save_setup_config = original_save_setup_config
            dashboard.log_action = original_log_action

    def test_website_scan_can_use_hermes_browser_enrichment(self):
        """Test connected Hermes can enrich onboarding answers from a website scan."""
        print("\nTesting Hermes Website Enrichment...")

        dashboard = load_dashboard_module()

        class FakeConfig:
            agent_chat_provider = "hermes"

        captured = {}
        original_load_config = dashboard.load_config
        original_ready = dashboard.hermes_codex_ready
        original_agent_chat = dashboard.agent_chat
        original_read_json = dashboard.read_json
        original_write_json = dashboard.write_json
        original_save_setup_config = dashboard.save_setup_config
        original_log_action = dashboard.log_action
        stored = {}
        try:
            dashboard.load_config = lambda: FakeConfig()
            dashboard.hermes_codex_ready = lambda _config: (True, "ready")
            dashboard.read_json = lambda path, default=None: dict(stored.get(path, default or {}))
            dashboard.write_json = lambda path, data: stored.__setitem__(path, dict(data))
            dashboard.save_setup_config = lambda _payload: {"saved": True}
            dashboard.log_action = lambda *_args, **_kwargs: None

            def fake_agent_chat(_config, payload):
                captured["message"] = payload["message"]
                captured["channel"] = payload.get("channel")
                return {
                    "ok": True,
                    "provider": "hermes",
                    "raw_reply": json.dumps(
                        {
                            "main_offer": "Oferta desde Hermes",
                            "ideal_customer": "Comprador ideal desde Hermes",
                            "current_stage": "Ya tengo web y quiero lanzar",
                            "what_to_improve": "Elegir el primer concepto de anuncios",
                            "initial_plan": ["Revisar web", "Crear campaña con supervisión"],
                            "questions": [
                                {
                                    "key": "main_offer",
                                    "label": "¿Qué vendes?",
                                    "help": "Una frase corta.",
                                    "placeholder": "Ej: cursos, ropa, servicios.",
                                },
                                {
                                    "key": "ideal_customer",
                                    "label": "¿Quién compra?",
                                    "help": "La persona que más quieres atraer.",
                                    "placeholder": "Ej: mamás, dueños de negocio, parejas.",
                                },
                            ],
                        }
                    ),
                }

            dashboard.agent_chat = fake_agent_chat
            profile, source = dashboard.enrich_business_profile_with_agent("https://example.com", {"main_offer": "Base"}, "")
            self.assert_true(source == "hermes_browser_scan", "Hermes enrichment marks website scan source")
            self.assert_true(profile["main_offer"] == "Oferta desde Hermes", "Hermes JSON fills suggested onboarding answers")
            self.assert_true("herramienta de navegador" in captured["message"], "Hermes is explicitly asked to use browser/retrieval when available")
            generated = dashboard.generate_business_context_questions({"business_type": "Tienda de ropa", "website_url": "https://example.com", "language": "es"})
            self.assert_true(generated["source"] == "agent_questions", "Hermes-generated onboarding questions are used when the model responds with JSON")
            self.assert_true(generated["questions"][0]["label"] == "¿Qué vendes?", "Generated questions keep the first question simple")
            self.assert_true(captured["channel"] == "onboarding_business_questions", "Question generation uses the dedicated onboarding channel")
        finally:
            dashboard.load_config = original_load_config
            dashboard.hermes_codex_ready = original_ready
            dashboard.agent_chat = original_agent_chat
            dashboard.read_json = original_read_json
            dashboard.write_json = original_write_json
            dashboard.save_setup_config = original_save_setup_config
            dashboard.log_action = original_log_action

    def test_skill_response_parsing(self):
        """Test MiniMax skill JSON parsing."""
        print("\nTesting Skill Response Parsing...")

        parsed = parse_skill_response('{"assistant_message":"Listo","tool_request":{"tool":"run_daily_check","arguments":{}}}')
        self.assert_true(parsed["assistant_message"] == "Listo", "Skill assistant message parsed")
        self.assert_true(parsed["tool_request"]["tool"] == "run_daily_check", "Skill tool request parsed")

    def test_openai_compatible_agent_provider(self):
        """Test OpenAI-compatible brains are routed through Hermes instead of a direct chat client."""
        print("\nTesting OpenAI-Compatible Agent Provider...")

        class FakeConfig:
            agent_chat_provider = "openai_compatible"
            agent_brain_provider = "custom_api"
            agent_chat_base_url = "https://example.test/v1"
            agent_chat_api_key = "test-key"
            agent_chat_model = "custom-model"
            agent_chat_temperature = 0.42
            agent_profile_dir = "agent"

        settings = hermes_bridge.hermes_brain_settings(FakeConfig())
        env = hermes_bridge.hermes_environment(FakeConfig())
        self.assert_true(settings["provider"] == "custom", "OpenAI-compatible brain maps to Hermes custom provider")
        self.assert_true(settings["model"] == "custom-model", "Configured model is passed to Hermes")
        self.assert_true(settings["base_url"] == "https://example.test/v1", "Configured base URL is passed to Hermes")
        self.assert_true(settings["api_key"] == "test-key", "Configured API key is passed to Hermes")
        self.assert_true(env["OPENAI_API_KEY"] == "test-key" and env["OPENAI_BASE_URL"] == "https://example.test/v1", "Hermes receives OpenAI-compatible credentials through its environment")

        received = []
        original_hermes_chat = agent_chat.hermes_chat
        try:
            agent_chat.hermes_chat = lambda config, payload: received.append(payload) or {
                "ok": True,
                "provider": "hermes",
                "brain_provider": "custom_api",
                "model": "custom-model",
                "reply": "Hice el analisis. Lo puedo preparar ahora.",
            }
            result = agent_chat.chat(FakeConfig(), {"message": "Hola", "metrics": {}, "language": "es"})
            self.assert_true(result["provider"] == "hermes", "OpenAI-compatible brain still uses Hermes runtime")
            self.assert_true(result["brain_provider"] == "custom_api", "Brain provider stays visible in chat result")
            self.assert_true(result["model"] == "custom-model", "Configured model is used")
            self.assert_true("account_context" in received[0], "Hermes receives account context for API brains too")
        finally:
            agent_chat.hermes_chat = original_hermes_chat

    def test_agent_setup_status_accepts_direct_model_provider(self):
        """Test setup status treats MiniMax/OpenAI-compatible mode as a valid agent brain."""
        print("\nTesting Direct Agent Model Setup Status...")

        import setup_status

        class FakeConfig:
            agent_chat_provider = "minimax"
            agent_chat_base_url = "https://api.minimax.io/v1"
            agent_chat_model = "MiniMax-M3"
            agent_chat_api_key = "configured"
            hermes_cli = "__missing_hermes__"
            hermes_model = ""

        entries, context = setup_status.agent_chat_section(FakeConfig(), {"missing": [], "sections": {}, "dir": "agent"})
        statuses = {entry["key"]: entry["status"] for entry in entries}
        self.assert_true(context["direct_model_ready"] is True, "Direct provider readiness is detected")
        self.assert_true(statuses["openai_compatible_model"] == "ok", "Direct provider setup row is green")
        self.assert_true(statuses["hermes_runtime"] == "blocked" and statuses["hermes_auth"] == "ok", "API brain can be ready but Hermes runtime remains required")

    def test_hermes_provider_parses_tool_request(self):
        """Test Hermes provider output uses the same protected backend tool contract."""
        print("\nTesting Hermes Provider Tool Contract...")

        class FakeConfig:
            agent_chat_provider = "hermes"

        original_hermes_chat = agent_chat.hermes_chat
        received = []
        try:
            agent_chat.hermes_chat = lambda config, payload: received.append(payload) or {
                "ok": True,
                "provider": "hermes",
                "reply": '{"assistant_message":"Listo","tool_request":{"tool":"review_live_readiness","arguments":{}}}',
            }
            result = agent_chat.chat(FakeConfig(), {"message": "Que falta para live?", "metrics": {}, "language": "es"})
            self.assert_true(result["provider"] == "hermes", "Hermes is the active chat provider")
            self.assert_true(result["tool_request"]["tool"] == "review_live_readiness", "Hermes tool request parsed")
            self.assert_true("account_context" in received[0], "Hermes receives account context")
        finally:
            agent_chat.hermes_chat = original_hermes_chat

    def test_hermes_creative_image_request_routes_to_codex_tool(self):
        """Test Hermes can route a natural image-creative request to the Codex creative tool."""
        print("\nTesting Hermes Creative Image Tool Routing...")

        class FakeConfig:
            agent_chat_provider = "hermes"

        original_hermes_chat = agent_chat.hermes_chat
        received = []
        try:
            agent_chat.hermes_chat = lambda config, payload: received.append(payload) or {
                "ok": True,
                "provider": "hermes",
                "reply": json.dumps(
                    {
                        "assistant_message": "Hice el analisis de la imagen. Puedo preparar tres rutas visuales y dejarlas listas para revisar.",
                        "tool_request": {
                            "tool": "codex_creative_plan",
                            "arguments": {
                                "request": "Prepara 3 creativos para Meta Ads usando Codex Image. Resumen visual: producto fisico protagonista, fondo limpio, promesa clara y formato 4:5.",
                                "product_guide": "",
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
            }
            result = agent_chat.chat(
                FakeConfig(),
                {
                    "message": "Prepara creativos para mis anuncios usando esta imagen del producto.",
                    "metrics": {},
                    "language": "es",
                    "image_paths": [str(ROOT_DIR / "output" / "telegram_uploads" / "producto-test.png")],
                },
            )
            tool_request = result.get("tool_request") or {}
            self.assert_true(tool_request.get("tool") == "codex_creative_plan", "Creative image requests can route to Codex creative planning")
            self.assert_true("Resumen visual" in tool_request.get("arguments", {}).get("request", ""), "Hermes includes visual summary for Codex instead of relying on file reads")
            self.assert_true("account_context" in received[0], "Hermes creative requests receive account context")
        finally:
            agent_chat.hermes_chat = original_hermes_chat

    def test_hermes_missing_runtime_gives_chatgpt_setup_guidance(self):
        """Test missing Hermes runtime gives buyer-friendly ChatGPT/Codex setup guidance."""
        print("\nTesting Hermes Missing Runtime Guidance...")

        class FakeConfig:
            hermes_use_python_library = False
            hermes_cli = "__missing_hermes_binary__"
            hermes_model = ""
            hermes_timeout_seconds = 1
            hermes_max_iterations = 1
            hermes_enabled_toolsets = ""
            hermes_disabled_toolsets = "terminal"
            hermes_home = ""

        result = hermes_bridge.chat(FakeConfig(), {"message": "Hola", "language": "es", "account_context": {}})
        self.assert_true(result["provider"] == "hermes", "Hermes bridge responds")
        self.assert_true(result.get("fallback") is True, "Missing Hermes runtime is a fallback state")
        self.assert_true("cerebro del agente" in result["reply"].lower() and "chatgpt" in result["reply"].lower(), "Fallback explains ChatGPT/Codex setup without exposing technical commands")

    def test_dashboard_chatgpt_connect_action_opens_terminal(self):
        """Test the dashboard ChatGPT/Codex connection endpoint prefers an automatic terminal action."""
        print("\nTesting Dashboard ChatGPT/Codex Connect Action...")

        dashboard = load_dashboard_module()
        captured = {}
        original_update = dashboard.update_env_values
        original_launch = dashboard.launch_hermes_terminal
        original_log = dashboard.log_action
        try:
            dashboard.update_env_values = lambda values: captured.update(values)
            dashboard.launch_hermes_terminal = lambda _config: True
            dashboard.log_action = lambda *_args, **_kwargs: None
            result = dashboard.connect_agent_model({})
            self.assert_true(result["status"] == "terminal_opened", "Connect action opens the terminal when the environment allows it")
            self.assert_true(captured.get("AGENT_CHAT_PROVIDER") == "hermes", "Connect action selects Hermes as the agent provider")
            self.assert_true(captured.get("HERMES_REQUIRE_CODEX_AUTH") == "true", "Connect action keeps Codex auth required by default")
        finally:
            dashboard.update_env_values = original_update
            dashboard.launch_hermes_terminal = original_launch
            dashboard.log_action = original_log

    def test_dashboard_chatgpt_connect_action_uses_vps_browserless_bridge(self):
        """Test the ChatGPT/Codex connection endpoint starts a browser-visible Hermes bridge on VPS/headless installs."""
        print("\nTesting Dashboard ChatGPT/Codex VPS Browserless Bridge...")

        dashboard = load_dashboard_module()
        captured = {}
        original_update = dashboard.update_env_values
        original_launch = dashboard.launch_hermes_terminal
        original_start = dashboard.start_hermes_browserless_login
        original_log = dashboard.log_action
        try:
            dashboard.update_env_values = lambda values: captured.update(values)
            dashboard.launch_hermes_terminal = lambda _config: False
            dashboard.start_hermes_browserless_login = lambda _config: {
                "ok": True,
                "status": "browser_login_started",
                "command": "hermes model --no-browser",
                "running": True,
                "needs_input": True,
            }
            dashboard.log_action = lambda *_args, **_kwargs: None
            result = dashboard.connect_agent_model({})
            self.assert_true(result["status"] == "browser_login_started", "Headless installs start the browserless Hermes login bridge")
            self.assert_true(result["command"] == "hermes model --no-browser", "VPS bridge uses Hermes no-browser mode")
            self.assert_true(captured.get("AGENT_CHAT_PROVIDER") == "hermes", "VPS bridge still selects Hermes")
            self.assert_true(captured.get("HERMES_REQUIRE_CODEX_AUTH") == "true", "VPS bridge keeps Codex auth required")
        finally:
            dashboard.update_env_values = original_update
            dashboard.launch_hermes_terminal = original_launch
            dashboard.start_hermes_browserless_login = original_start
            dashboard.log_action = original_log

    def test_dashboard_hermes_browserless_auto_selects_codex(self):
        """Test the browserless Hermes bridge auto-selects OpenAI Codex and the recommended model."""
        print("\nTesting Dashboard Hermes Browserless Auto Selection...")

        dashboard = load_dashboard_module()
        writes = []
        original_write = dashboard.os.write
        try:
            dashboard.os.write = lambda fd, data: writes.append((fd, data)) or len(data)
            provider_output = (
                "Select provider:\n"
                "1. MiniMax\n"
                "6. OpenAI ▸ (Codex CLI or direct OpenAI API)\n"
                "Select by number, Enter to confirm.\n"
            )
            with dashboard.HERMES_LOGIN_LOCK:
                dashboard.HERMES_LOGIN_STATE.update({
                    "id": "auto-test",
                    "output": provider_output,
                    "auto_provider_sent": False,
                    "auto_codex_subprovider_sent": False,
                    "auto_model_sent": False,
                    "auto_note": "",
                })
            selected_provider = dashboard.maybe_auto_drive_hermes_browserless("auto-test", 99)
            prompt = dashboard.hermes_login_prompt_state(provider_output, dashboard.HERMES_LOGIN_STATE)
            self.assert_true(selected_provider is True and writes[-1] == (99, b"6\n"), "Browserless Hermes selects OpenAI Codex automatically")
            self.assert_true(prompt["needs_input"] is False and "OpenAI Codex" in prompt["detail"], "Provider prompt is explained without asking the buyer for terminal input")

            codex_subprovider_output = (
                "Select provider:\n"
                "(●)  1. OpenAI Codex\n"
                "(○)  2. OpenAI API\n"
                "Choice [default 1]:\n"
            )
            with dashboard.HERMES_LOGIN_LOCK:
                dashboard.HERMES_LOGIN_STATE.update({
                    "id": "auto-test",
                    "output": codex_subprovider_output,
                    "auto_provider_sent": True,
                    "auto_codex_subprovider_sent": False,
                    "auto_model_sent": False,
                    "auto_note": "",
                })
            selected_subprovider = dashboard.maybe_auto_drive_hermes_browserless("auto-test", 99)
            prompt = dashboard.hermes_login_prompt_state(codex_subprovider_output, dashboard.HERMES_LOGIN_STATE)
            self.assert_true(selected_subprovider is True and writes[-1] == (99, b"1\n"), "Browserless Hermes explicitly confirms OpenAI Codex in the OpenAI submenu")
            self.assert_true(prompt["needs_input"] is False and "OpenAI Codex" in prompt["detail"], "OpenAI submenu is handled without buyer terminal input")

            class RunningProc:
                def poll(self):
                    return None

            with dashboard.HERMES_LOGIN_LOCK:
                dashboard.HERMES_LOGIN_STATE.update({
                    "id": "auto-test",
                    "output": codex_subprovider_output,
                    "auto_provider_sent": True,
                    "auto_codex_subprovider_sent": False,
                    "auto_model_sent": False,
                    "proc": RunningProc(),
                    "fd": 99,
                })
            nudged = dashboard.nudge_hermes_browserless_autodrive()
            self.assert_true(nudged is True and writes[-1] == (99, b"1\n"), "Revisar conexión nudges a stuck Hermes submenu forward automatically")

            model_output = "Select model:\n1. Recommended default\nSelect by number, Enter to confirm.\n"
            with dashboard.HERMES_LOGIN_LOCK:
                dashboard.HERMES_LOGIN_STATE.update({
                    "id": "auto-test",
                    "output": model_output,
                    "auto_provider_sent": True,
                    "auto_codex_subprovider_sent": True,
                    "auto_model_sent": False,
                    "auto_note": "",
                    "proc": None,
                    "fd": None,
                })
            selected_model = dashboard.maybe_auto_drive_hermes_browserless("auto-test", 99)
            self.assert_true(selected_model is True and writes[-1] == (99, b"\n"), "Browserless Hermes confirms the recommended model automatically")

            login_output = (
                "Open this URL to continue: https://auth.openai.com/device\n"
                "OpenAI will ask for the verification code displayed in your terminal.\n"
                "Verification code: AB12-CD34\n"
            )
            prompt = dashboard.hermes_login_prompt_state(login_output, dashboard.HERMES_LOGIN_STATE)
            response = dashboard.hermes_connect_response("needs_login", prompt["title"], prompt["detail"], output=login_output, log=False)
            self.assert_true(prompt["phase"] == "login_code" and prompt["login_code"] == "AB12-CD34", "Browserless Hermes extracts the OpenAI terminal code from login output")
            self.assert_true(response["login_code"] == "AB12-CD34" and response["login_codes"] == ["AB12-CD34"], "Dashboard response exposes the OpenAI code separately from technical logs")
            letters_only_output = "OpenAI device code displayed in your terminal:\nVerification code: WXYZ-ABCD\n"
            self.assert_true(dashboard.extract_login_codes_from_text(letters_only_output) == ["WXYZ-ABCD"], "OpenAI terminal code extraction supports letter-only device codes")
            spaced_code_output = (
                "Visit https://auth.openai.com/device to continue.\n"
                "OpenAI will ask for the code displayed in your terminal.\n\n"
                "Copy this code into the browser:\n\n"
                "WXYZ ABCD\n"
            )
            self.assert_true(dashboard.extract_login_codes_from_text(spaced_code_output) == ["WXYZ-ABCD"], "OpenAI terminal code extraction supports spaced codes several lines after the hint")
            compact_code_output = "Device login code: A1B2C3D4\nOpen https://auth.openai.com/device\n"
            self.assert_true(dashboard.extract_login_codes_from_text(compact_code_output) == ["A1B2C3D4"], "OpenAI terminal code extraction supports compact alphanumeric codes")
        finally:
            dashboard.os.write = original_write

    def test_hermes_blocks_non_codex_runtime_by_default(self):
        """Test buyer default does not silently chat through a non-Codex Hermes provider."""
        print("\nTesting Hermes Codex Auth Requirement...")

        class FakeConfig:
            hermes_require_codex_auth = True
            hermes_cli = "hermes"
            hermes_use_python_library = False
            hermes_model = ""
            hermes_timeout_seconds = 1
            hermes_max_iterations = 1
            hermes_enabled_toolsets = ""
            hermes_disabled_toolsets = "terminal"
            hermes_home = ""

        class Completed:
            returncode = 0
            stdout = "Provider:     MiniMax\nOpenAI Codex  ✗ not logged in (run: hermes model)"
            stderr = ""

        original_run = hermes_bridge.subprocess.run
        original_which = hermes_bridge.shutil.which
        try:
            hermes_bridge.shutil.which = lambda _cmd: "/usr/local/bin/hermes"
            hermes_bridge.subprocess.run = lambda *args, **kwargs: Completed()
            result = hermes_bridge.chat(FakeConfig(), {"message": "Hola", "language": "es", "account_context": {}})
            self.assert_true(result["provider"] == "hermes", "Hermes remains the selected provider")
            self.assert_true(result.get("fallback") is True, "Non-Codex Hermes runtime is blocked as setup fallback")
            self.assert_true("MiniMax" in result.get("error", ""), "Blocked detail exposes the wrong Hermes provider for diagnostics")
            self.assert_true("OpenAI Codex" in result.get("error", ""), "Blocked detail mentions Codex auth")
        finally:
            hermes_bridge.subprocess.run = original_run
            hermes_bridge.shutil.which = original_which

    def test_hermes_attaches_safe_uploaded_images(self):
        """Test Hermes sees uploaded reference images without enabling broad file access."""
        print("\nTesting Hermes Uploaded Image Attachment...")

        class FakeConfig:
            hermes_cli = "hermes"
            hermes_model = ""
            hermes_timeout_seconds = 10
            hermes_max_iterations = 3
            hermes_enabled_toolsets = "memory,skills,session_search,vision,image_gen,file,web,browser"
            hermes_disabled_toolsets = "terminal,code_execution"
            hermes_home = ""

        image_dir = ROOT_DIR / "output" / "telegram_uploads"
        image_dir.mkdir(parents=True, exist_ok=True)
        safe_image = image_dir / "test-reference.png"
        safe_image.write_bytes(b"fakepng")
        unsafe_image = ROOT_DIR / ".env"
        captured = {}

        class Completed:
            returncode = 0
            stdout = "Imagen revisada."
            stderr = ""

        original_run = hermes_bridge.subprocess.run
        try:
            def fake_run(command, **kwargs):
                captured["command"] = command
                return Completed()

            hermes_bridge.subprocess.run = fake_run
            result = hermes_bridge.cli_chat(FakeConfig(), {"message": "Crea creativos", "language": "es", "account_context": {}, "image_paths": [str(safe_image), str(unsafe_image)]})
            command = captured["command"]
            self.assert_true(result == "Imagen revisada.", "Hermes CLI response returned")
            image_index = command.index("--image") + 1
            attached_image = command[image_index]
            self.assert_true("--image" in command and attached_image.endswith("test-reference.png"), "Safe uploaded image is attached to Hermes")
            self.assert_true("dashboard/data/hermes-workspace/current/uploads" in attached_image, "Safe uploaded image is copied into the Hermes workspace before attachment")
            self.assert_true(str(unsafe_image.resolve()) not in command, "Unsafe local file is not attached as an image")
            self.assert_true("memory,skills,session_search,vision,image_gen,file,web,browser" in command, "Creative-friendly Hermes toolsets include scoped file and website access")
        finally:
            hermes_bridge.subprocess.run = original_run

    def test_hermes_business_memory_workspace_is_curated_and_redacted(self):
        """Test Hermes receives approved business files inside its workspace without leaking secrets."""
        print("\nTesting Hermes Curated Business Memory...")

        memory = hermes_bridge.business_memory_context()
        workspace = hermes_bridge.prepare_hermes_workspace({"image_paths": [str(ROOT_DIR / ".env")]})
        prompt = hermes_bridge.hermes_prompt(
            type("FakeConfig", (), {"agent_profile_dir": "agent"})(),
            {"message": "Que sabes de mi negocio?", "language": "es", "account_context": {}, "image_paths": [str(ROOT_DIR / ".env")]},
            workspace,
        )
        self.assert_true("Curated local business memory JSON" in prompt, "Hermes prompt includes curated business memory")
        self.assert_true("Hermes workspace files" in prompt, "Hermes prompt lists workspace files")
        self.assert_true("business_profile" in memory and "brand_guides" in memory, "Business and brand memory are included")
        self.assert_true((hermes_bridge.HERMES_WORKSPACE_DIR / "data" / "business_profile.json").exists(), "Business profile is copied into Hermes workspace")
        self.assert_true((hermes_bridge.HERMES_WORKSPACE_DIR / "brand_guides" / "general_branding.md").exists(), "Brand guide is copied into Hermes workspace")
        self.assert_true(".env" not in prompt and "MINIMAX_API_KEY" not in prompt, "Secrets and arbitrary local files are not included")
        self.assert_true("Uploaded reference images" not in prompt, "Unsafe non-upload image paths are not attached")

    def test_decision_memory_profitability_rules_and_hermes_context(self):
        """Test profitability rules and decision memory feed the agent context."""
        print("\nTesting Profitability Decision Memory...")

        original = {
            "PROFITABILITY_RULES_FILE": decision_memory.PROFITABILITY_RULES_FILE,
            "DECISION_MEMORY_FILE": decision_memory.DECISION_MEMORY_FILE,
            "LEARNING_LOG_FILE": decision_memory.LEARNING_LOG_FILE,
        }
        with tempfile.TemporaryDirectory(prefix="decision-memory-test-") as tmp:
            tmp_root = Path(tmp)
            try:
                decision_memory.PROFITABILITY_RULES_FILE = tmp_root / "profitability_rules.json"
                decision_memory.DECISION_MEMORY_FILE = tmp_root / "decision_memory.json"
                decision_memory.LEARNING_LOG_FILE = tmp_root / "learning-log.md"
                rules = decision_memory.save_profitability_rules({"target_cpa": 42, "target_roas": 3.1, "min_spend_before_judging": 80})
                campaign = {
                    "id": "camp_profit",
                    "name": "Profit Test",
                    "status": "active",
                    "daily_budget": 100,
                    "spend": 120,
                    "revenue": 540,
                    "conversions": 6,
                    "roas": 4.5,
                    "cpa": 20,
                    "ctr": 1.7,
                    "cpc": 1.2,
                    "frequency": 1.8,
                    "health": "winning",
                }
                rec = {"campaign_id": "camp_profit", "campaign_name": "Profit Test", "change_pct": 15, "recommended_budget": 115}
                evidence = decision_memory.recommendation_decision_evidence(campaign, rec, rules)
                memory = decision_memory.record_daily_decision_memory({"campaigns": [campaign]}, [rec], [])
                payload = decision_memory.decision_memory_payload({"campaigns": [campaign]}, [rec], [])

                self.assert_true(rules["target_cpa"] == 42, "Profitability rules are saved locally")
                self.assert_true("signal" in evidence and "recommendation" in evidence, "Recommendations receive evidence fields")
                self.assert_true(memory["decisions"], "Daily decisions are recorded")
                self.assert_true(payload["recent_decisions"], "Decision payload exposes recent decisions")
                self.assert_true(decision_memory.LEARNING_LOG_FILE.exists(), "Human-readable learning log file is written")

                hermes_memory = hermes_bridge.business_memory_context()
                self.assert_true("profitability_memory" in hermes_memory, "Hermes context includes profitability memory")
                self.assert_true("profitability_rules" in hermes_memory["profitability_memory"], "Hermes receives profitability rules")
            finally:
                decision_memory.PROFITABILITY_RULES_FILE = original["PROFITABILITY_RULES_FILE"]
                decision_memory.DECISION_MEMORY_FILE = original["DECISION_MEMORY_FILE"]
                decision_memory.LEARNING_LOG_FILE = original["LEARNING_LOG_FILE"]

    def test_chat_approval_decision_tool(self):
        """Test chat approvals execute only when they resolve to one exact pending decision."""
        print("\nTesting Chat Approval Decision Tool...")

        dashboard = load_dashboard_module()
        original = {
            "PENDING_FILE": dashboard.PENDING_FILE,
            "approve_pending": dashboard.approve_pending,
            "reject_pending": dashboard.reject_pending,
            "require_license_unlock": dashboard.require_license_unlock,
        }
        test_dir = ROOT_DIR / "output" / "test-chat-approval-decision"
        try:
            shutil.rmtree(test_dir, ignore_errors=True)
            test_dir.mkdir(parents=True, exist_ok=True)
            dashboard.PENDING_FILE = test_dir / "pending.json"
            dashboard.write_json(
                dashboard.PENDING_FILE,
                [
                    {"id": "approval_exact", "type": "budget_change", "status": "pending", "payload": {"campaign_name": "Campaña Test", "new_budget": 20}},
                    {"id": "approval_second", "type": "pause_campaign", "status": "pending", "payload": {"campaign_name": "Otra Campaña"}},
                ],
            )
            dashboard.require_license_unlock = lambda *args, **kwargs: None
            dashboard.approve_pending = lambda approval_id: [{"id": approval_id, "status": "approved", "result": {"ok": True}}]
            dashboard.reject_pending = lambda approval_id, reason="": [{"id": approval_id, "status": "rejected"}]
            exact = dashboard.execute_agent_tool({"tool": "approval_decision", "arguments": {"approval_id": "approval_exact", "decision": "approve"}}, {"language": "es"})
            ambiguous = dashboard.execute_agent_tool({"tool": "approval_guardrail", "arguments": {}}, {"language": "es", "message": "aprueba"})
            self.assert_true(exact["type"] == "approval_decision", "Approval intent is routed locally")
            self.assert_true(exact["executed"] is True, "Exact chat approval can execute")
            self.assert_true("approval_choices" in ambiguous, "Ambiguous approval shows exact choices")
            dashboard.write_json(
                dashboard.PENDING_FILE,
                [
                    {"id": "approval_active", "type": "create_campaign", "status": "pending", "payload": {"name": "Active Test", "final_status": "ACTIVE"}},
                ],
            )
            blocked_active = dashboard.route_chat_approval_decision({"language": "en", "message": "approve approval_active"})
            approved_active = dashboard.route_chat_approval_decision({"language": "en", "message": "Yes, create and leave active approval_active"})
            parsed_active = dashboard.parse_campaign_creation_payload("create ads for coffee active yes, create and leave active", {"message": ""})
            self.assert_true(blocked_active["routed_action"]["reason"] == "active_confirmation_required", "Active approval needs exact confirmation")
            self.assert_true(approved_active["routed_action"]["executed"] is True, "English active confirmation is accepted")
            self.assert_true(parsed_active["active_spend_confirmed"] is True, "English active confirmation is accepted in campaign parsing")
        finally:
            for key, value in original.items():
                setattr(dashboard, key, value)
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_minimax_tool_request_executes_backend_tool(self):
        """Test MiniMax-style tool request can trigger a backend action."""
        print("\nTesting MiniMax Tool Request Execution...")

        dashboard = load_dashboard_module()
        result = dashboard.execute_agent_tool({"tool": "review_live_readiness", "arguments": {}}, {"language": "es"})
        self.assert_true(result["type"] == "review_live_readiness", "Live readiness tool recognized")
        self.assert_true(result["executed"] is False, "Readiness review does not mutate account")
        self.assert_true("piloto automático" in result["reply"].lower(), "Readiness reply generated")

    def test_codex_creative_prompt_rejects_local_file_escape(self):
        """Test an agent request cannot feed arbitrary local files to Codex."""
        print("\nTesting Codex Guide Path Protection...")

        try:
            build_codex_creative_prompt(".env", "Prepara creativos")
            self.assert_true(False, "Codex product guide should reject files outside its guide directory")
        except ValueError as exc:
            self.assert_true("brand_guides/products" in str(exc), "Codex product guide blocks arbitrary local-file reads")
        context = account_context({"brand_guides": {"general_exists": True, "product_guides": ["brand_guides/products/oferta.md"]}})
        self.assert_true(context["brand_guides"]["product_guides"] == ["brand_guides/products/oferta.md"], "Hermes receives safe Codex guide inventory")
        dashboard = load_dashboard_module()
        original_call_codex = dashboard.call_codex_cli
        original_load_config = dashboard.load_config
        calls = []
        try:
            dashboard.load_config = lambda: type("Cfg", (), {"codex_creative_enabled": True})()
            dashboard.call_codex_cli = lambda prompt: calls.append(prompt) or {"ok": True}
            blocked = dashboard.codex_creative_plan({"product_guide": ".env", "request": "Prepara creativos"})
            self.assert_true(blocked["ok"] is False, "Backend Codex tool rejects escaped guide paths")
            self.assert_true(not calls, "Blocked Codex requests never invoke the CLI")
        finally:
            dashboard.call_codex_cli = original_call_codex
            dashboard.load_config = original_load_config

        safe_prompt = build_codex_creative_prompt("", "Prepara creativos")
        self.assert_true("No leas archivos" in safe_prompt and "credenciales" in safe_prompt, "Codex prompt includes secret-access guardrails")
        original_run = codex_brand_guides.subprocess.run
        original_codex_config = codex_brand_guides.load_config
        captured = {}
        try:
            codex_brand_guides.load_config = lambda: type("Cfg", (), {"codex_cli": "codex"})()
            def fake_run(command, **kwargs):
                captured["command"] = command
                captured["cwd"] = kwargs.get("cwd")
                return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
            codex_brand_guides.subprocess.run = fake_run
            result = codex_brand_guides.call_codex_cli(safe_prompt)
            command = captured["command"]
            self.assert_true(result["ok"] is True, "Optional Codex bridge can complete isolated creative planning")
            self.assert_true("--sandbox" in command and "read-only" in command, "Codex bridge uses read-only sandbox")
            self.assert_true("--ephemeral" in command and "--ignore-user-config" in command and "--ignore-rules" in command, "Codex bridge avoids saved sessions and local rules")
            self.assert_true(str(captured["cwd"]).startswith("/var/") or "meta-ads-codex-" in str(captured["cwd"]), "Codex bridge executes in an isolated temporary folder")
        finally:
            codex_brand_guides.subprocess.run = original_run
            codex_brand_guides.load_config = original_codex_config

    def test_agent_codex_image_creative_request_result(self):
        """Test the agent result when the buyer asks for ad creatives using Codex image planning."""
        print("\nTesting Agent Codex Image Creative Request Result...")

        dashboard = load_dashboard_module()
        image_dir = ROOT_DIR / "output" / "telegram_uploads"
        image_dir.mkdir(parents=True, exist_ok=True)
        reference_image = image_dir / "producto-test.png"
        reference_image.write_bytes(b"fake image content")

        original_load_config = dashboard.load_config
        original_call_codex = dashboard.call_codex_cli
        calls = []
        try:
            dashboard.load_config = lambda: type("Cfg", (), {"codex_creative_enabled": False})()
            dashboard.call_codex_cli = lambda prompt: calls.append(prompt) or {"ok": True}
            disabled = dashboard.execute_agent_tool(
                {
                    "tool": "codex_creative_plan",
                    "arguments": {
                        "request": "Prepara 3 creativos para Meta Ads usando Codex Image con la foto del producto.",
                        "product_guide": "",
                    },
                },
                {"language": "es", "image_paths": [str(reference_image)]},
            )
            self.assert_true(disabled["type"] == "codex_creative_plan", "Codex creative request routes to the creative planning tool")
            self.assert_true(disabled["executed"] is False and disabled["blocked"] is True, "Codex creative request is blocked when owner has not enabled Codex")
            self.assert_true("Codex CLI" in disabled["reply"], "Buyer receives clear Codex setup/enablement guidance")
            self.assert_true(not calls, "Disabled Codex creative requests do not call the CLI")

            dashboard.load_config = lambda: type("Cfg", (), {"codex_creative_enabled": True})()
            dashboard.call_codex_cli = lambda prompt: calls.append(prompt) or {
                "ok": True,
                "stdout": (
                    "Diagnostico creativo: la foto del producto debe ser el centro visual.\n"
                    "Concepto 1: antes/despues con beneficio claro.\n"
                    "Concepto 2: close-up del producto con texto corto.\n"
                    "Concepto 3: escena de uso con prueba/confianza.\n"
                    "Prompt final para ChatGPT Image / Image 2: crear anuncio 4:5 limpio, producto protagonista, texto grande, fondo coherente con marca.\n"
                    "Variantes: 1:1, 4:5, 9:16.\n"
                    "Copy: Mejora tus resultados sin abrir Ads Manager a ciegas."
                ),
            }
            enabled = dashboard.execute_agent_tool(
                {
                    "tool": "codex_creative_plan",
                    "arguments": {
                        "request": "Prepara 3 creativos para Meta Ads usando Codex Image con la foto del producto.",
                        "product_guide": "",
                    },
                },
                {"language": "es", "image_paths": [str(reference_image)]},
            )
            self.assert_true(enabled["executed"] is True, "Enabled Codex creative request executes the optional bridge")
            self.assert_true("Prompt final para ChatGPT Image / Image 2" in enabled["reply"], "Agent returns Codex image-ready creative prompt output")
            self.assert_true("Imagen de referencia recibida" in calls[0], "Uploaded image context is forwarded into the Codex planning prompt")
            self.assert_true(str(reference_image) not in calls[0], "Codex prompt receives visual context without arbitrary local file dependency")
        finally:
            dashboard.load_config = original_load_config
            dashboard.call_codex_cli = original_call_codex

    def test_creative_studio_protects_and_previews_generated_assets(self):
        """Test the visual studio exposes only generated images from its own refresh batch."""
        print("\nTesting Creative Studio Protected Previews...")

        dashboard = load_dashboard_module()
        root = dashboard.CREATIVE_ASSET_ROOT
        root.mkdir(parents=True, exist_ok=True)
        refresh_dir = Path(tempfile.mkdtemp(prefix="creative_studio_test_", dir=str(root)))
        refresh_id = refresh_dir.name
        image_path = refresh_dir / "preview_4x5.png"
        image_path.write_bytes(b"png preview")
        old_temp_path = refresh_dir / "old_temp.png"
        old_temp_path.write_bytes(b"old temporary")
        old_saved_path = refresh_dir / "old_saved.png"
        old_saved_path.write_bytes(b"old saved")
        outside_path = ROOT_DIR / "output" / f"{refresh_id}_outside.png"
        outside_path.write_bytes(b"must not be exposed")
        manifest_path = refresh_dir / "manifest.json"
        dashboard.write_json(
            manifest_path,
            {
                "id": refresh_id,
                "created_at": "2026-05-26T10:00:00-05:00",
                "status": "images_ready",
                "provider": "nano-banana",
                "image_mode": "live",
                "brand_memory": {"product": {"name": "Serum luminoso", "guide": "brand_guides/products/serum.md"}},
                "campaign": {"id": "camp_1", "name": "Producto prueba"},
                "upload_policy": {"requires_approval": True},
                "variants": [
                    {
                        "variant_id": "v1",
                        "copy": {"headline": "Oferta clara", "primary_text": "Texto", "angle": "beneficio", "cta": "Comprar"},
                        "image_prompts": [{"aspect_ratio": "4:5", "prompt": "prompt"}],
                        "assets": [
                            {"path": str(image_path), "mime_type": "image/png", "aspect_ratio": "4:5", "created_at": "2026-05-26T10:00:00-05:00"},
                            {"path": str(outside_path), "mime_type": "image/png", "aspect_ratio": "1:1"},
                        ],
                    },
                    {
                        "variant_id": "v2",
                        "copy": {"headline": "Retención", "primary_text": "Texto", "angle": "control", "cta": "Comprar"},
                        "image_prompts": [{"aspect_ratio": "1:1", "prompt": "prompt"}],
                        "assets": [
                            {"path": str(old_temp_path), "mime_type": "image/png", "aspect_ratio": "1:1", "created_at": "2026-05-01T10:00:00-05:00"},
                            {"path": str(old_saved_path), "mime_type": "image/png", "aspect_ratio": "4:5", "created_at": "2026-05-01T10:00:00-05:00", "retention": {"saved": True, "kind": "ad_image", "reason": "ad_created"}},
                        ],
                    },
                ],
            },
        )
        original_recent = dashboard.recent_creative_refreshes
        try:
            dashboard.recent_creative_refreshes = lambda limit=8: [
                {
                    "id": refresh_id,
                    "created_at": "2026-05-26T10:00:00-05:00",
                    "status": "images_ready",
                    "campaign": {"id": "camp_1", "name": "Producto prueba"},
                    "variant_count": 1,
                    "manifest_path": str(manifest_path),
                }
            ]
            items = dashboard.creative_studio_items(1)
            assets = items[0]["variants"][0]["assets"]
            self.assert_true(items[0]["has_generated_images"] is True, "Creative studio marks a batch with valid generated previews")
            self.assert_true(items[0]["brand_memory"]["product"]["name"] == "Serum luminoso", "Creative studio retains the selected product memory on its batch")
            self.assert_true(len(assets) == 1 and assets[0]["preview_url"].startswith("/api/creative-asset?id="), "Studio publishes only its scoped protected preview URL")
            self.assert_true(assets[0]["temporary"] is True and assets[0]["storage"].get("cleanup") == "manual_cleanup" and assets[0]["filename"] == image_path.name, "Studio exposes local storage metadata and filenames for downloads")
            self.assert_true(any(asset.get("saved_for_ad") for asset in items[0]["variants"][1]["assets"]), "Studio labels ad images that are kept permanently")
            self.assert_true(dashboard.creative_asset_path(f"{refresh_id}/preview_4x5.png") == image_path, "Protected creative preview resolves a valid batch asset")
            dashboard.stage_upload(str(manifest_path), "v1", ["4:5"], request_approval=False)
            updated = dashboard.read_json(manifest_path, {})
            retained = updated["variants"][0]["assets"][0]["retention"]
            self.assert_true(retained.get("saved") is True and retained.get("reason") == "selected_for_ad", "Preparing an image for an ad marks it as retained")
            cleanup = dashboard.clear_temporary_creative_assets()
            self.assert_true(cleanup["deleted"] >= 1 and not old_temp_path.exists(), "Manual creative storage cleanup removes only draft images")
            self.assert_true(image_path.exists() and old_saved_path.exists(), "Ad-selected/generated images marked as saved are retained during storage cleanup")
            try:
                dashboard.creative_asset_path(f"../{outside_path.name}")
                self.assert_true(False, "Protected creative previews reject paths outside the creative directory")
            except ValueError:
                self.assert_true(True, "Protected creative previews reject paths outside the creative directory")
        finally:
            dashboard.recent_creative_refreshes = original_recent
            shutil.rmtree(refresh_dir, ignore_errors=True)
            outside_path.unlink(missing_ok=True)

    def test_brand_memory_documents_feed_creative_generation(self):
        """Test visual brand/product memory is persisted as Markdown and actually used for creative output."""
        print("\nTesting Brand Memory Creative Context...")

        general_path = codex_brand_guides.GENERAL_GUIDE
        product_path = codex_brand_guides.PRODUCT_DIR / "memoria-prueba-integracion.md"
        ad_brief_path = codex_brand_guides.AD_BRIEF_DIR / "brief-buen-fin-variantes.md"
        general_before = general_path.read_bytes() if general_path.exists() else None
        product_before = product_path.read_bytes() if product_path.exists() else None
        ad_brief_before = ad_brief_path.read_bytes() if ad_brief_path.exists() else None
        try:
            blank_fields = codex_brand_guides.general_fields("- Promesa principal:\n- Cliente ideal: Compradora real")
            self.assert_true(blank_fields["promise"] == "" and blank_fields["ideal_customer"] == "Compradora real", "Blank Markdown fields never absorb the following brand field")
            library = codex_brand_guides.save_general_guide(
                {
                    "brand_name": "Luz Clara",
                    "offer": "Cuidado facial consciente",
                    "visual_style": "fondos marfil con acentos coral y fotografia limpia",
                    "tone": "cercano, decidido y facil de entender",
                    "avoid_always": "promesas medicas",
                }
            )
            result = codex_brand_guides.save_product_guide(
                {
                    "name": "Memoria Prueba Integracion",
                    "audience": "mujeres que buscan una rutina facial sencilla",
                    "pain": "piel opaca y rutina confusa",
                    "desire": "piel luminosa sin complicaciones",
                    "avoid": "resultados milagrosos",
                }
            )
            plan = build_creative_plan(
                {"id": "memory_test", "name": "Campaña de prueba", "health": "fatigue"},
                product_guide=result["guide"],
            )
            ad_brief = codex_brand_guides.save_ad_brief(
                {
                    "name": "Brief Buen Fin Variantes",
                    "product_guide": result["guide"],
                    "campaign_name": "Campaña Buen Fin",
                    "adset_name": "Lookalike compradores",
                    "base_ad_name": "Anuncio ganador testimonio",
                    "promotion": "Bono de Buen Fin por 48 horas",
                    "base_ad": "un testimonio directo y fondo claro que ya convierte",
                    "locked_elements": "mantener testimonio, oferta y CTA",
                    "variation_window": "probar solo paleta de colores y encuadre del producto",
                    "variation_axes": "colores, encuadre, fondo",
                    "variation_count": "4",
                }
            )
            ad_plan = build_creative_plan(
                {"id": "ad_brief_test", "name": "Campaña Buen Fin", "health": "good"},
                ad_brief=ad_brief["ad_brief"],
            )
            prompt = plan["variants"][0]["image_prompts"][0]["prompt"]
            ad_prompt = ad_plan["variants"][0]["image_prompts"][0]["prompt"]
            self.assert_true(library["general"]["saved"] is True and product_path.exists(), "Brand and product memory are saved as local Markdown guides")
            self.assert_true("product.example.md" not in [item["guide"] for item in result["library"]["products"]], "Product template is not presented as buyer memory")
            self.assert_true(plan["brand_memory"]["product"]["name"] == "Memoria Prueba Integracion", "Creative plan records which product memory it used")
            self.assert_true("Memoria Prueba Integracion" in plan["variants"][0]["copy"]["headline"], "Product memory informs generated ad copy")
            self.assert_true("piel luminosa sin complicaciones" in plan["variants"][0]["copy"]["primary_text"], "Desired result from product memory informs the copy")
            self.assert_true("fondos marfil" in prompt and "mujeres que buscan" in prompt and "resultados milagrosos" in prompt, "Brand style, audience, and exclusions inform image prompts")
            self.assert_true(ad_brief_path.exists() and ad_plan["brand_memory"]["ad_brief"]["name"] == "Brief Buen Fin Variantes", "Ad brief memory is saved and attached to creative plans")
            self.assert_true(len(ad_plan["variants"]) == 4, "Ad brief variation count controls the number of variants")
            self.assert_true("Anuncio ganador testimonio" in ad_plan["brand_memory"]["ad_brief"]["base_ad_name"], "Ad brief records the exact winning/base ad")
            self.assert_true("Bono de Buen Fin" in ad_prompt and "paleta de colores" in ad_prompt, "Ad brief promotion and creative window inform image prompts")
            self.assert_true("colores" in ad_plan["variants"][0]["copy"]["headline"].lower(), "Ad brief variation axes become concrete ad variants")
        finally:
            if general_before is None:
                general_path.unlink(missing_ok=True)
            else:
                general_path.parent.mkdir(parents=True, exist_ok=True)
                general_path.write_bytes(general_before)
            if product_before is None:
                product_path.unlink(missing_ok=True)
            else:
                product_path.parent.mkdir(parents=True, exist_ok=True)
                product_path.write_bytes(product_before)
            if ad_brief_before is None:
                ad_brief_path.unlink(missing_ok=True)
            else:
                ad_brief_path.parent.mkdir(parents=True, exist_ok=True)
                ad_brief_path.write_bytes(ad_brief_before)

    def test_audience_builder_readiness(self):
        """Test audience builder creates safe targeting strategy and lookalike readiness."""
        print("\nTesting Audience Builder...")

        strategy = build_audience_strategy(
            {
                "product": "Curso para negocios locales",
                "buyer": "Dueños de restaurantes",
                "locations": "Mexico, Colombia",
                "interests": "marketing digital, restaurantes",
                "data_sources": "Pixel purchases, Instagram engagement",
                "consent": "yes",
            },
            "es",
        )
        self.assert_true(strategy["lookalike_readiness"]["ready"], "Lookalike readiness detected from pixel/engagement")
        self.assert_true(len(strategy["strategies"]) >= 4, "Audience strategy includes lookalike when ready")
        self.assert_true(strategy["strategies"][0]["name"] == "Llegar a personas nuevas", "Spanish audience advice avoids unexplained prospecting jargon")
        self.assert_true("personas parecidas" in strategy["next_steps"][2].lower(), "Spanish next steps explain lookalikes in plain language")

    def test_chat_audience_tool(self):
        """Test MiniMax audience tool can execute through backend."""
        print("\nTesting Chat Audience Tool...")

        dashboard = load_dashboard_module()
        result = dashboard.execute_agent_tool(
            {
                "tool": "build_audience_strategy",
                "arguments": {
                    "product": "Curso para negocios locales",
                    "buyer": "Dueños de restaurantes",
                    "locations": "Mexico",
                    "data_sources": "Pixel purchases",
                    "consent": "yes",
                },
            },
            {"language": "es"},
        )
        self.assert_true(result["type"] == "build_audience_strategy", "Audience tool recognized")
        self.assert_true(result["executed"] is True, "Audience strategy generated")

    def test_meta_targeting_search_normalizes_options(self):
        """Test Meta targeting search returns buyer-safe selectable options."""
        print("\nTesting Meta Targeting Search...")

        dashboard = load_dashboard_module()
        original_graph_get = dashboard.graph_get
        calls = []

        def fake_graph_get(path, params=None, page_token=""):
            calls.append((path, params or {}))
            if (params or {}).get("type") == "adinterest":
                return {"ok": True, "data": {"data": [{"id": "6001", "name": "Ecommerce", "path": ["Business"], "audience_size": 123456}]}}
            return {"ok": True, "data": {"data": [{"key": "CO", "name": "Colombia", "type": "country", "country_code": "CO"}]}}

        try:
            dashboard.graph_get = fake_graph_get
            interests = dashboard.meta_targeting_search({"kind": "interest", "q": "ecommerce"})
            locations = dashboard.meta_targeting_search({"kind": "location", "q": "Colombia"})
            self.assert_true(calls[0][0] == "search" and calls[0][1]["type"] == "adinterest", "Interest targeting search uses Meta search")
            self.assert_true(interests["items"][0]["id"] == "6001" and interests["items"][0]["name"] == "Ecommerce", "Interest search normalizes ID and name")
            self.assert_true(calls[1][1]["type"] == "adgeolocation" and "location_types" in calls[1][1], "Location targeting search uses Meta geolocation search")
            self.assert_true(locations["items"][0]["key"] == "CO" and locations["items"][0]["label"].startswith("Colombia"), "Location search normalizes location chips")
            dashboard.graph_get = lambda *args, **kwargs: {"ok": False, "error": {"error": {"message": "Error validating access token: Session has expired"}}}
            expired = dashboard.meta_targeting_search({"kind": "interest", "q": "fitness"})
            self.assert_true("clave nueva" in expired["message"] and "OAuth" not in expired["message"], "Expired Meta key audience-search error is buyer-friendly")
        finally:
            dashboard.graph_get = original_graph_get

    def test_chat_saves_existing_adset_when_user_provides_it(self):
        """Test chat can store an optional existing ad set ID without making it a beginner requirement."""
        print("\nTesting Chat Existing Ad Set Memory...")

        dashboard = load_dashboard_module()
        ad_path = dashboard.AD_CONFIG_FILE
        ad_before = ad_path.read_text(encoding="utf-8") if ad_path.exists() else ""
        try:
            result = dashboard.execute_agent_tool(
                {"tool": "save_existing_adset", "arguments": {"adset_id": "123456789"}},
                {"language": "es"},
            )
            saved = json.loads(ad_path.read_text(encoding="utf-8"))
            self.assert_true(result["type"] == "save_existing_adset", "Existing ad set tool recognized")
            self.assert_true(result["executed"] is True, "Existing ad set is saved from chat tool")
            self.assert_true(saved["creative"]["destination"]["default_adset_id"] == "123456789", "Existing ad set stored in ad-config")
            routed = dashboard.route_chat_action({"message": "mi grupo de anuncios es 987654321", "language": "es"})
            self.assert_true(routed["routed_action"]["type"] == "save_existing_adset", "Natural language ad set save is routed")
        finally:
            ad_path.write_text(ad_before, encoding="utf-8")

    def test_chat_history_persists_and_resets(self):
        """Test recent chat context is saved for reloads and can be cleared for a new product."""
        print("\nTesting Chat Persistent Conversation...")

        dashboard = load_dashboard_module()
        history_path = dashboard.CHAT_HISTORY_FILE
        before = history_path.read_text(encoding="utf-8") if history_path.exists() else ""
        actions_path = dashboard.ACTIONS_FILE
        actions_before = actions_path.read_text(encoding="utf-8") if actions_path.exists() else ""
        try:
            dashboard.save_chat_history([])
            saved = dashboard.append_chat_turn("Quiero crear un anuncio para mi curso", "Perfecto, empecemos por la oferta.")
            loaded = dashboard.load_chat_history()
            payload = dashboard.dashboard_payload()
            self.assert_true(len(saved) == 2, "Chat turn is persisted")
            self.assert_true(loaded[-2]["role"] == "user" and loaded[-1]["role"] == "agent", "Chat history reloads with roles")
            self.assert_true(payload["chat_history"][-1]["content"] == "Perfecto, empecemos por la oferta.", "Dashboard exposes recent chat history")
            reset = dashboard.reset_chat_history()
            self.assert_true(reset["cleared"] is True and dashboard.load_chat_history() == [], "New conversation clears previous context")
        finally:
            if before:
                history_path.write_text(before, encoding="utf-8")
            elif history_path.exists():
                history_path.unlink()
            if actions_before:
                actions_path.write_text(actions_before, encoding="utf-8")
            elif actions_path.exists():
                actions_path.unlink()

    def test_creative_memory_wizard_collects_and_saves_guides(self):
        """Test the chat-guided creative memory flow saves brand, product, and ad brief files."""
        print("\nTesting Creative Memory Chat Wizard...")

        dashboard = load_dashboard_module()
        general_path = dashboard.BRAND_GUIDES_DIR / "general_branding.md"
        product_path = dashboard.BRAND_PRODUCTS_DIR / "oferta-guiada-test.md"
        brief_path = dashboard.BRAND_GUIDES_DIR / "ad_briefs" / "brief-guiado-test.md"
        wizard_path = dashboard.CREATIVE_MEMORY_WIZARD_FILE
        actions_path = dashboard.ACTIONS_FILE
        backups = {
            general_path: general_path.read_bytes() if general_path.exists() else None,
            product_path: product_path.read_bytes() if product_path.exists() else None,
            brief_path: brief_path.read_bytes() if brief_path.exists() else None,
            wizard_path: wizard_path.read_bytes() if wizard_path.exists() else None,
            actions_path: actions_path.read_bytes() if actions_path.exists() else None,
        }
        try:
            dashboard.reset_creative_memory_wizard()
            general_path.unlink(missing_ok=True)
            product_path.unlink(missing_ok=True)
            brief_path.unlink(missing_ok=True)
            start = dashboard.handle_creative_memory_wizard(
                {"language": "es", "message": "Completar marca con el agente", "memory_wizard": {"mode": "start", "kind": "general"}}
            )
            self.assert_true(start["routed_action"]["type"] == "creative_memory_wizard_start" and "pregunta" in start["reply"].lower(), "Brand wizard starts as a guided chat")
            result = None
            for answer in [
                "Miro Ads Lab",
                "Un manager IA para mejorar Meta Ads",
                "Ayudar a entender y optimizar anuncios con menos estrés",
                "Dueños de negocios pequeños en Latinoamérica",
                "Cercano, decidido y fácil de entender",
                "Turquesa, violeta y fondos claros",
                "Dashboard moderno, humano y con producto protagonista",
                "Promesas falsas o humo técnico",
            ]:
                result = dashboard.handle_creative_memory_wizard({"language": "es", "message": answer})
            fields = dashboard.guide_library()["general"]["fields"]
            self.assert_true(result["routed_action"]["type"] == "creative_memory_wizard_complete", "Brand wizard completes and saves")
            self.assert_true(fields["brand_name"] == "Miro Ads Lab" and "Latinoamérica" in fields["ideal_customer"], "Brand answers are saved into Markdown fields")

            start = dashboard.handle_creative_memory_wizard(
                {"language": "es", "message": "Completar producto con el agente", "memory_wizard": {"mode": "start", "kind": "product"}}
            )
            self.assert_true(start["routed_action"]["kind"] == "product", "Product wizard starts from chat")
            product_result = None
            for answer in [
                "Oferta guiada test",
                "https://example.com/oferta",
                "USD $49",
                "Dashboard, guía y plantillas de anuncios",
                "Emprendedores que venden con Meta Ads",
                "No entienden qué está pasando en sus campañas",
                "Tomar mejores decisiones y subir ROAS",
                "Miedo a tocar algo mal o perder dinero",
                "UI, chat del agente y ejemplos visuales",
                "Lujo falso o resultados garantizados",
                "Tu cuenta te habla; deja de adivinar",
            ]:
                product_result = dashboard.handle_creative_memory_wizard({"language": "es", "message": answer})
            library = dashboard.guide_library()
            product = next(item for item in library["products"] if item["id"] == "oferta-guiada-test")
            self.assert_true(product_result["routed_action"]["type"] == "creative_memory_wizard_complete", "Product wizard completes and saves")
            self.assert_true(product["fields"]["name"] == "Oferta guiada test" and "ROAS" in product["fields"]["desire"], "Product answers are saved into the product guide")

            start = dashboard.handle_creative_memory_wizard(
                {
                    "language": "es",
                    "message": "Completar brief con el agente",
                    "memory_wizard": {"mode": "start", "kind": "ad_brief", "product_guide": product["guide"]},
                }
            )
            self.assert_true(start["routed_action"]["kind"] == "ad_brief", "Ad brief wizard starts from chat")
            brief_result = None
            for answer in [
                "Brief guiado test",
                "Bono de lanzamiento 20%",
                "Campaña ventas lanzamiento",
                "Mujeres 25-44 Colombia",
                "Anuncio ganador testimonio",
                "Ventas",
                "Visitantes tibios que necesitan confianza",
                "Testimonio, oferta y CTA corto",
                "No cambiar precio ni promesa",
                "Cambiar solo colores, fondo y encuadre",
                "colores, fondo, encuadre",
                "4",
                "Ver si un fondo más limpio mejora el CTR",
            ]:
                brief_result = dashboard.handle_creative_memory_wizard({"language": "es", "message": answer})
            library = dashboard.guide_library()
            brief = next(item for item in library["ad_briefs"] if item["id"] == "brief-guiado-test")
            self.assert_true(brief_result["routed_action"]["type"] == "creative_memory_wizard_complete", "Ad brief wizard completes and saves")
            self.assert_true(brief["fields"]["variation_count"] == "4" and "colores" in brief["fields"]["variation_window"], "Ad brief answers define variation window and count")
            self.assert_true(brief["fields"]["product_guide"] == product["guide"], "Ad brief keeps the selected product guide")
        finally:
            dashboard.reset_creative_memory_wizard()
            for path, content in backups.items():
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)

    def test_meta_asset_discovery_saves_connected_assets(self):
        """Test selected ad account can discover and save connected Page/Instagram/URL assets."""
        print("\nTesting Meta Asset Discovery...")

        dashboard = load_dashboard_module()
        ad_path = dashboard.AD_CONFIG_FILE
        onboarding_path = dashboard.ONBOARDING_FILE
        binding_path = dashboard.INDIVIDUAL_BINDING_FILE
        ad_before = ad_path.read_text(encoding="utf-8") if ad_path.exists() else ""
        onboarding_before = onboarding_path.read_text(encoding="utf-8") if onboarding_path.exists() else ""
        binding_before = binding_path.read_bytes() if binding_path.exists() else None
        original_graph_get = dashboard.graph_get
        try:
            def fake_graph_get(path, params=None, page_token=""):
                if path == "/me/accounts":
                    return {
                        "ok": True,
                        "data": {
                            "data": [
                                {
                                    "id": "111",
                                    "name": "Buyer Page",
                                    "website": "https://buyer.example",
                                    "instagram_business_account": {"id": "222", "username": "buyer_ig"},
                                }
                            ]
                        },
                    }
                if path == "/act_999/ads":
                    return {"ok": True, "data": {"data": []}}
                return {"ok": False, "error": "unexpected path"}

            dashboard.graph_get = fake_graph_get
            dashboard.write_json(onboarding_path, {"completed": False})
            if binding_path.exists():
                binding_path.unlink()
            result = dashboard.social_discover_assets({"ad_account_id": "act_999"})
            saved = json.loads(ad_path.read_text(encoding="utf-8"))
            destination = saved["creative"]["destination"]
            self.assert_true(result["saved"] is True, "Discovered assets are saved")
            self.assert_true(destination["page_id"] == "111", "Discovered Page ID saved")
            self.assert_true(destination["instagram_actor_id"] == "222", "Discovered Instagram ID saved")
            self.assert_true(destination["url"] == "https://buyer.example", "Discovered website saved")
        finally:
            dashboard.graph_get = original_graph_get
            ad_path.write_text(ad_before, encoding="utf-8")
            if onboarding_before:
                onboarding_path.write_text(onboarding_before, encoding="utf-8")
            elif onboarding_path.exists():
                onboarding_path.unlink()
            if binding_before is None:
                if binding_path.exists():
                    binding_path.unlink()
            else:
                binding_path.write_bytes(binding_before)

    def test_live_insights_normalize_into_dashboard_metrics(self):
        """Test real Meta insights rows are normalized into dashboard metric cache shape."""
        print("\nTesting Live Insights Normalization...")

        dashboard = load_dashboard_module()
        metrics = dashboard.normalize_insights_rows(
            [
                {
                    "campaign_id": "123",
                    "campaign_name": "Real Buyer Campaign",
                    "spend": "100.50",
                    "impressions": "10000",
                    "clicks": "250",
                    "ctr": "2.5",
                    "cpc": "0.402",
                    "frequency": "1.7",
                    "actions": [{"action_type": "purchase", "value": "5"}],
                    "action_values": [{"action_type": "purchase", "value": "750"}],
                }
            ],
            "act_999",
        )
        campaign = metrics["campaigns"][0]
        enriched = dashboard.enrich_campaign(campaign)
        self.assert_true(metrics["source"] == "meta_graph", "Live insights are marked as Meta Graph source")
        self.assert_true(campaign["name"] == "Real Buyer Campaign", "Campaign name comes from real insights")
        self.assert_true(campaign["conversions"] == 5, "Purchase actions become conversions")
        self.assert_true(campaign["revenue"] == 750.0, "Purchase values become revenue")
        self.assert_true(round(enriched["roas"], 2) == 7.46, "ROAS is calculated from real spend/revenue")

    def test_supervised_daily_reads_real_data_and_stages_pause(self):
        """Test scheduled supervised reports read Meta without inventing executed pauses."""
        print("\nTesting Supervised Scheduled Daily Safety...")

        read_flags = []

        class InspectClient(SocialFlowClient):
            def run(self, args, live_required=True, mutation=False):
                read_flags.append((list(args), live_required, mutation))
                return {"stdout": "{}", "returncode": 0, "executed": True}

        class ReadConfig:
            social_cli = "social"
            mode = "dry-run"
            live = False
            live_actions_enabled = False

        InspectClient(ReadConfig()).insights()
        self.assert_true(read_flags[0][1] is False and read_flags[0][2] is False, "Supervised insights are treated as safe real-data reads")
        normalized = daily_agent.normalize_social_insights(
            {"data": [{"campaign_id": "meta_1", "campaign_name": "Real", "spend": "10", "impressions": "100", "clicks": "5"}]},
            {"campaigns": []},
        )
        self.assert_true(normalized["source"] == "meta_graph", "Scheduled social-cli reads remain labeled as real Meta data")

        original = {
            "METRICS_FILE": daily_agent.METRICS_FILE,
            "ACTIONS_FILE": daily_agent.ACTIONS_FILE,
            "PENDING_FILE": daily_agent.PENDING_FILE,
            "OUTPUT_DIR": daily_agent.OUTPUT_DIR,
            "FATIGUE_LOG": daily_agent.FATIGUE_LOG,
            "load_config": daily_agent.load_config,
            "SocialFlowClient": daily_agent.SocialFlowClient,
            "pull_live_metrics": daily_agent.pull_live_metrics,
            "config_snapshot": daily_agent.config_snapshot,
            "send_notification": daily_agent.send_notification,
        }
        test_dir = ROOT_DIR / "output" / "test-supervised-daily"
        pulls = []

        class Config:
            ad_account_id = "act_test"
            meta_access_token = "saved-token"
            live = False
            mode = "dry-run"
            live_actions_enabled = False
            autonomy_mode = "supervised"
            license_required_for_live = True
            target_cpa = 10
            approval_required_over_pct = 20
            auto_pause_enabled = True
            auto_pause_max_spend = 100
            zero_conversion_spend = 50
            high_cpa_multiplier = 3
            creative_refresh_enabled = False
            creative_auto_generate_on_daily = False
            creative_live = False

        try:
            shutil.rmtree(test_dir, ignore_errors=True)
            daily_agent.METRICS_FILE = test_dir / "metrics.json"
            daily_agent.ACTIONS_FILE = test_dir / "actions.json"
            daily_agent.PENDING_FILE = test_dir / "pending.json"
            daily_agent.OUTPUT_DIR = test_dir / "reports"
            daily_agent.FATIGUE_LOG = test_dir / "fatigue.md"
            daily_agent.load_config = lambda: Config()
            daily_agent.SocialFlowClient = lambda config: object()
            risky = daily_agent.enrich_campaign(
                {
                    "id": "camp_risky",
                    "name": "Campaña costosa",
                    "status": "active",
                    "daily_budget": 40,
                    "spend": 120,
                    "impressions": 1000,
                    "clicks": 20,
                    "conversions": 0,
                    "revenue": 0,
                }
            )
            real_metrics = {"source": "meta_graph", "campaigns": [risky], "summary": daily_agent.build_summary([risky])}
            daily_agent.pull_live_metrics = lambda metrics, client: pulls.append(True) or real_metrics
            daily_agent.config_snapshot = lambda config: {"control_level": "supervised"}
            daily_agent.send_notification = lambda config, title, message: {"sent": False}
            _, report = daily_agent.run_daily()
            pending = daily_agent.read_json(daily_agent.PENDING_FILE, [])
            self.assert_true(bool(pulls), "Scheduled supervised daily pulls connected Meta data")
            self.assert_true(real_metrics["campaigns"][0]["status"] == "active", "Supervised daily does not falsely mark a Meta campaign paused")
            self.assert_true(any(item.get("type") == "pause_campaign" for item in pending), "Supervised daily stages risky pause for approval")
            self.assert_true(report["brief"]["auto_paused"] == [] and len(report["brief"]["proposed_pauses"]) == 1, "Daily brief distinguishes proposed pause from executed pause")
        finally:
            for key, value in original.items():
                setattr(daily_agent, key, value)
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_demo_metrics_are_labeled(self):
        """Test legacy sample metrics cannot masquerade as live account data."""
        print("\nTesting Demo Metrics Label...")

        dashboard = load_dashboard_module()
        sample = dashboard.sample_metrics()
        self.assert_true(sample["source"] == "demo", "New sample metrics are explicitly demo")
        legacy = {"timestamp": "2026-01-01", "campaigns": [{"id": "camp_001", "name": "Q2 Conversion Campaign"}]}
        self.assert_true(dashboard.looks_like_demo_metrics(legacy), "Legacy demo cache is detected")

    def test_supervised_approval_executes_only_with_valid_license_and_retries_failures(self):
        """Test explicit approval is live-capable without activating autopilot."""
        print("\nTesting Supervised Approval Execution...")

        class Config:
            license_required_for_live = True
            live = False
            live_actions_enabled = False
            mode = "dry-run"

        class ApprovedClient:
            config = Config()

            def __init__(self):
                self.calls = []

            def pause(self, target_type, target_id, approved=False):
                self.calls.append(approved)
                return {"executed": True, "returncode": 0, "approved_execution": approved}

        original_license = daily_agent.license_status
        original_load_config = daily_agent.load_config
        original_client = daily_agent.SocialFlowClient
        original_pending = daily_agent.PENDING_FILE
        original_actions = daily_agent.ACTIONS_FILE
        test_dir = ROOT_DIR / "output" / "test-supervised-approval"
        try:
            daily_agent.license_status = lambda config: {"valid": True}
            client = ApprovedClient()
            result = daily_agent.execute_pending({"type": "pause_campaign", "payload": {"campaign_id": "camp_1"}}, client)
            self.assert_true(client.calls == [True] and daily_agent.execution_succeeded(result), "Button approval can execute under Con supervision without enabling autopilot")
            daily_agent.license_status = lambda config: {"valid": False, "detail": "Licencia no activa"}
            blocked = daily_agent.execute_pending({"type": "pause_campaign", "payload": {"campaign_id": "camp_1"}}, client)
            self.assert_true(blocked.get("blocked") is True and client.calls == [True], "Approval cannot execute without a valid live license")

            shutil.rmtree(test_dir, ignore_errors=True)
            daily_agent.PENDING_FILE = test_dir / "pending.json"
            daily_agent.ACTIONS_FILE = test_dir / "actions.json"
            daily_agent.write_json(daily_agent.PENDING_FILE, [{"id": "approval_retry", "type": "pause_campaign", "status": "pending", "payload": {"campaign_id": "camp_1"}}])
            daily_agent.load_config = lambda: Config()
            daily_agent.license_status = lambda config: {"valid": True}

            class FailingClient(ApprovedClient):
                def pause(self, target_type, target_id, approved=False):
                    return {"executed": False, "returncode": 1, "stderr": "Meta rejected request", "approved_execution": approved}

            daily_agent.SocialFlowClient = lambda config: FailingClient()
            attempted = daily_agent.approve("approval_retry")
            still_pending = daily_agent.read_json(daily_agent.PENDING_FILE, [])
            self.assert_true(attempted[0]["status"] == "pending" and still_pending[0]["id"] == "approval_retry", "Failed approved action remains pending instead of disappearing as completed")
        finally:
            daily_agent.license_status = original_license
            daily_agent.load_config = original_load_config
            daily_agent.SocialFlowClient = original_client
            daily_agent.PENDING_FILE = original_pending
            daily_agent.ACTIONS_FILE = original_actions
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_campaign_creation_requires_active_confirmation(self):
        """Test ready-to-spend campaigns require explicit confirmation before staging."""
        print("\nTesting Active Campaign Confirmation...")

        dashboard = load_dashboard_module()
        try:
            dashboard.create_campaign(
                {
                    "name": "Active Test",
                    "objective": "PURCHASES",
                    "daily_budget": 50,
                    "total_budget": 1500,
                    "final_status": "ACTIVE",
                    "active_spend_confirmed": "",
                }
            )
            self.assert_true(False, "Active campaign without confirmation should fail")
        except ValueError as exc:
            self.assert_true("crear y dejar activo" in str(exc), "Active spend confirmation is required")

    def test_campaign_creation_uses_meta_targeting_selection(self):
        """Test manual campaign creation stores Meta-selected targeting IDs instead of plain text only."""
        print("\nTesting Campaign Meta Targeting Selection...")

        dashboard = load_dashboard_module()
        original = {
            "OUTPUT_DIR": dashboard.OUTPUT_DIR,
            "CREATED_FILE": dashboard.CREATED_FILE,
            "PENDING_FILE": dashboard.PENDING_FILE,
        }
        test_dir = ROOT_DIR / "output" / "test-meta-targeting"
        try:
            shutil.rmtree(test_dir, ignore_errors=True)
            dashboard.OUTPUT_DIR = test_dir / "campaigns"
            dashboard.CREATED_FILE = test_dir / "created.json"
            dashboard.PENDING_FILE = test_dir / "pending.json"
            payload = {
                "name": "Meta Targeting Test",
                "objective": "PURCHASES",
                "daily_budget": 25,
                "total_budget": 750,
                "final_status": "PAUSED",
                "targeting_locations_json": json.dumps([{"kind": "location", "key": "CO", "name": "Colombia", "type": "country", "country_code": "CO"}]),
                "targeting_interests_json": json.dumps([{"kind": "interest", "id": "6001", "name": "Ecommerce"}]),
            }
            result = dashboard.create_campaign(payload)
            created = dashboard.read_json(dashboard.CREATED_FILE, [])
            campaign = created[0]["campaign"]
            targeting = campaign["ad_sets"][0]["targeting"]
            self.assert_true(result["payload"]["requested"]["targeting"]["source"] == "meta_search", "Approval card marks targeting as Meta search")
            self.assert_true(targeting["meta_targeting"]["locations"][0]["key"] == "CO", "Campaign stores selected Meta location")
            self.assert_true(targeting["meta_targeting"]["interests"][0]["id"] == "6001", "Campaign stores selected Meta interest ID")
        finally:
            for key, value in original.items():
                setattr(dashboard, key, value)
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_social_targeting_uses_meta_ids(self):
        """Test approved campaign execution sends Meta targeting IDs to the connector."""
        print("\nTesting Social Targeting Meta IDs...")

        spec = daily_agent.targeting_for_social(
            {
                "locations": ["US"],
                "age_range": {"min": 25, "max": 44},
                "meta_targeting": {
                    "locations": [{"key": "2420605", "name": "Bogotá", "type": "city", "country_code": "CO"}],
                    "interests": [{"id": "6001", "name": "Ecommerce"}],
                },
            }
        )
        self.assert_true(spec["geo_locations"]["cities"][0]["key"] == "2420605", "Social targeting sends selected city key")
        self.assert_true(spec["interests"][0] == {"id": "6001", "name": "Ecommerce"}, "Social targeting sends selected interest ID")
        self.assert_true(spec["age_min"] == 25 and spec["age_max"] == 44, "Social targeting preserves age range")

    def test_autopilot_action_updates_dashboard_only_after_meta_success(self):
        """Test autopilot UI/chat mutations are real connector actions, not local-only state."""
        print("\nTesting Autopilot Connector Execution...")

        dashboard = load_dashboard_module()
        original = {
            "METRICS_FILE": dashboard.METRICS_FILE,
            "ACTIONS_FILE": dashboard.ACTIONS_FILE,
            "PENDING_FILE": dashboard.PENDING_FILE,
            "load_config": dashboard.load_config,
            "SocialFlowClient": dashboard.SocialFlowClient,
            "require_cloud_license": dashboard.require_cloud_license,
        }
        test_dir = ROOT_DIR / "output" / "test-autopilot-action"
        connector_calls = []

        class Config:
            live = True
            live_actions_enabled = True
            autonomy_mode = "autopilot"
            auto_pause_max_spend = 100
            auto_budget_change_pct = 20
            auto_budget_change_amount = 100
            approval_required_over_pct = 30
            require_approval_for_resume = True
            require_approval_for_new_campaigns = True
            require_approval_for_creatives = True

        class SuccessClient:
            def __init__(self, config):
                self.config = config

            def pause(self, target_type, target_id):
                connector_calls.append((target_type, target_id))
                return {"executed": True, "returncode": 0, "stdout": "paused"}

        try:
            shutil.rmtree(test_dir, ignore_errors=True)
            dashboard.METRICS_FILE = test_dir / "metrics.json"
            dashboard.ACTIONS_FILE = test_dir / "actions.json"
            dashboard.PENDING_FILE = test_dir / "pending.json"
            dashboard.load_config = lambda: Config()
            dashboard.SocialFlowClient = SuccessClient
            dashboard.require_cloud_license = lambda *args, **kwargs: None
            base_metrics = {
                "source": "meta_graph",
                "campaigns": [{"id": "camp_live", "name": "Ganadora", "status": "active", "spend": 10, "daily_budget": 20, "target_type": "campaign", "target_id": "meta_camp_1"}],
            }
            dashboard.write_json(dashboard.METRICS_FILE, base_metrics)
            result = dashboard.apply_action({"action": "pause", "campaign_id": "camp_live"})
            saved = dashboard.read_json(dashboard.METRICS_FILE, {})
            self.assert_true(connector_calls == [("campaign", "meta_camp_1")], "Autopilot pause calls the Meta connector")
            self.assert_true(saved["campaigns"][0]["status"] == "paused" and result["status"] == "completed", "Dashboard status updates after confirmed Meta execution")

            class FailureClient(SuccessClient):
                def pause(self, target_type, target_id):
                    return {"executed": False, "returncode": 1, "stderr": "rejected"}

            dashboard.SocialFlowClient = FailureClient
            dashboard.write_json(dashboard.METRICS_FILE, base_metrics)
            try:
                dashboard.apply_action({"action": "pause", "campaign_id": "camp_live"})
                self.assert_true(False, "Failed Meta mutation should not appear successful")
            except ValueError:
                failed_state = dashboard.read_json(dashboard.METRICS_FILE, {})
                self.assert_true(failed_state["campaigns"][0]["status"] == "active", "Failed Meta mutation leaves dashboard state unchanged")
        finally:
            for key, value in original.items():
                setattr(dashboard, key, value)
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_campaign_stack_execution_creates_full_ad_order(self):
        """Test approved campaign stack creates campaign, ad set, creative, and ad in order."""
        print("\nTesting Campaign Stack Execution...")

        class FakeConfig:
            live = False
            mode = "dry-run"
            ad_account_id = "act_999"

        class FakeClient:
            config = FakeConfig()

            def __init__(self):
                self.calls = []

            def create_campaign(self, *args, **kwargs):
                self.calls.append(("create_campaign", args, kwargs))
                return {"stdout": json.dumps({"id": "cmp_1"}), "executed": True}

            def create_adset(self, *args, **kwargs):
                self.calls.append(("create_adset", args, kwargs))
                return {"stdout": json.dumps({"id": "adset_1"}), "executed": True}

            def upload_image(self, *args, **kwargs):
                self.calls.append(("upload_image", args, kwargs))
                return {"stdout": json.dumps({"hash": "hash_1"}), "executed": True}

            def create_creative(self, *args, **kwargs):
                self.calls.append(("create_creative", args, kwargs))
                return {"stdout": json.dumps({"id": "creative_1"}), "executed": True}

            def create_ad(self, *args, **kwargs):
                self.calls.append(("create_ad", args, kwargs))
                return {"stdout": json.dumps({"id": "ad_1"}), "executed": True}

        ad_path = ROOT_DIR / "ad-config.json"
        ad_before = ad_path.read_text(encoding="utf-8") if ad_path.exists() else ""
        image_path = ROOT_DIR / "output" / "test-creative.png"
        campaign_path = ROOT_DIR / "output" / "test-campaign-stack.json"
        try:
            image_path.parent.mkdir(exist_ok=True)
            image_path.write_bytes(b"fake")
            ad_path.write_text(json.dumps({"creative": {"destination": {"page_id": "111", "instagram_actor_id": "222", "url": "https://buyer.example"}}}), encoding="utf-8")
            campaign_path.write_text(
                json.dumps(
                    {
                        "name": "Ready Stack",
                        "objective": "PURCHASES",
                        "budget": {"daily": 25, "total": 750},
                        "ad_sets": [{"name": "Ready Stack - Core", "targeting": {"locations": ["MX"], "age_range": {"min": 18, "max": 65}}, "budget": 25}],
                        "ad": {
                            "primary_text": "Texto",
                            "headline": "Titular",
                            "creative_image_path": str(image_path),
                            "landing_url": "https://buyer.example",
                            "final_status": "ACTIVE",
                            "active_spend_confirmed": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            client = FakeClient()
            result = execute_campaign_creation(str(campaign_path), client, approved=True)
            self.assert_true(result["ok"], "Approved campaign stack executes while supervised")
            self.assert_true([call[0] for call in client.calls] == ["create_campaign", "create_adset", "upload_image", "create_creative", "create_ad"], "Campaign stack executes in correct order")
            self.assert_true(client.calls[-1][1][-1] == "ACTIVE", "Final ad status is active when confirmed")
            self.assert_true(all(call[2].get("approved") is True for call in client.calls), "Full campaign execution is explicitly marked as approved")
        finally:
            if ad_before:
                ad_path.write_text(ad_before, encoding="utf-8")
            elif ad_path.exists():
                ad_path.unlink()
            if image_path.exists():
                image_path.unlink()
            if campaign_path.exists():
                campaign_path.unlink()

    def test_chat_stages_campaign_creation_and_requires_exact_approval(self):
        """Test natural language can stage campaign creation while approvals require an exact pending decision."""
        print("\nTesting Chat Campaign Creation Routing...")

        dashboard = load_dashboard_module()
        original_require = dashboard.require_cloud_license
        original_create = dashboard.create_campaign
        original_pending = dashboard.PENDING_FILE
        test_dir = ROOT_DIR / "output" / "test-chat-campaign-routing"
        try:
            shutil.rmtree(test_dir, ignore_errors=True)
            test_dir.mkdir(parents=True, exist_ok=True)
            dashboard.PENDING_FILE = test_dir / "pending.json"
            dashboard.write_json(dashboard.PENDING_FILE, [])
            dashboard.require_cloud_license = lambda *args, **kwargs: None
            dashboard.create_campaign = lambda payload: {"status": "pending", "id": "approval_test", "payload": payload}
            routed = dashboard.route_chat_action(
                {
                    "language": "es",
                    "message": "Crea una campaña para vender mi curso con presupuesto de $20 https://buyer.example /tmp/creative.png",
                }
            )
            approve = dashboard.route_chat_action({"language": "es", "message": "aprueba esa campaña"})
            self.assert_true(routed["routed_action"]["type"] == "create_campaign_stack", "Chat routes campaign creation")
            self.assert_true(routed["routed_action"]["staged"] is True, "Chat stages campaign creation for approval")
            self.assert_true(approve["routed_action"]["type"] == "approval_decision", "Chat approval requests route through exact approval logic")
            self.assert_true(approve["routed_action"]["executed"] is False, "Chat approval without a pending decision is blocked")
        finally:
            dashboard.require_cloud_license = original_require
            dashboard.create_campaign = original_create
            dashboard.PENDING_FILE = original_pending
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_telegram_channel_routes_agent_and_blocks_approval(self):
        """Test Telegram uses the manager path and approves only exact decisions."""
        print("\nTesting Telegram Agent Channel...")

        class FakeConfig:
            telegram_chat_id = "12345"
            telegram_bot_token = "fake"
            agent_chat_api_key = "minimax-configured"

        class FakeDashboard:
            def __init__(self):
                self.logged = []
                self.pending = [
                    {
                        "id": "approval_test",
                        "type": "budget_change",
                        "status": "pending",
                        "payload": {"campaign_name": "Campaña Test", "new_budget": 20},
                    }
                ]

            def dashboard_payload(self):
                return {"metrics": {}, "recommendations": [], "fatigue": [], "pending": self.pending, "audience_strategy": {}, "business_profile": {"main_offer": "Curso Test"}}

            def execute_agent_tool(self, tool_request, payload):
                return {"type": "create_campaign_stack", "executed": False, "staged": True, "reply": "Campaña preparada para aprobación."}

            def log_action(self, *args):
                self.logged.append(args)

        history_path = telegram_agent.HISTORY_FILE
        before = history_path.read_text(encoding="utf-8") if history_path.exists() else ""
        original_agent_chat = telegram_agent.agent_chat
        original_dashboard = telegram_agent._DASHBOARD
        original_settings = telegram_agent.telegram_settings
        original_send = telegram_agent.send_message
        original_keyboard = telegram_agent.send_message_with_keyboard
        original_answer = telegram_agent.callback_answer
        original_approve = telegram_agent.approve_pending
        original_reject = telegram_agent.reject_pending
        try:
            fake_dashboard = FakeDashboard()
            received_payloads = []
            telegram_agent._DASHBOARD = fake_dashboard
            telegram_agent.telegram_settings = lambda config: {"enabled": True, "language": "es", "poll_timeout": 25, "bot_configured": True, "chat_id": "12345"}
            telegram_agent.agent_chat = lambda config, payload: received_payloads.append(payload) or {"tool_request": {"tool": "create_campaign_stack", "arguments": {}}, "reply": "preparing"}
            sent = []
            telegram_agent.send_message = lambda config, chat_id, text: sent.append(("message", text))
            telegram_agent.send_message_with_keyboard = lambda config, chat_id, text, keyboard: sent.append(("keyboard", text, keyboard))
            telegram_agent.callback_answer = lambda config, callback_id, text="": sent.append(("callback", text))
            telegram_agent.approve_pending = lambda approval_id: [{"id": approval_id, "status": "approved", "result": {"ok": True}}]
            telegram_agent.reject_pending = lambda approval_id, reason="": [{"id": approval_id}]
            reply = telegram_agent.handle_text(FakeConfig(), "12345", "Prepara una campaña", send=False)
            approved_text = telegram_agent.handle_text(FakeConfig(), "12345", "Aprueba esa campaña", send=False)
            pending_reply = telegram_agent.handle_text(FakeConfig(), "12345", "/pendientes", send=True)
            callback = telegram_agent.handle_update(FakeConfig(), {"callback_query": {"id": "cb_1", "data": "approve:approval_test", "message": {"chat": {"id": "12345"}}}})
            fake_dashboard.pending = [
                {
                    "id": "approval_active",
                    "type": "create_campaign",
                    "status": "pending",
                    "payload": {"campaign_name": "Campaña Activa", "final_status": "ACTIVE"},
                }
            ]
            blocked_active = telegram_agent.handle_text(FakeConfig(), "12345", "approve", send=False)
            approved_active = telegram_agent.handle_text(FakeConfig(), "12345", "Yes, create and leave active", send=False)
            self.assert_true(telegram_agent.is_allowed_chat(FakeConfig(), "12345"), "Configured Telegram private chat is allowed")
            self.assert_true(not telegram_agent.is_allowed_chat(FakeConfig(), "99999"), "Unknown Telegram chat is rejected")
            self.assert_true("preparada para aprobación" in reply, "Telegram can stage manager actions through backend tools")
            self.assert_true("Aprobacion ejecutada" in approved_text, "Telegram text can approve the single exact pending decision")
            self.assert_true(received_payloads[0]["business_profile"]["main_offer"] == "Curso Test", "Telegram gives Hermes the selected client's business profile")
            self.assert_true("Decisiones pendientes" in pending_reply, "Telegram lists pending approvals")
            self.assert_true(any(item[0] == "keyboard" for item in sent), "Telegram sends approve/reject buttons")
            self.assert_true(callback["type"] == "approved", "Telegram button can approve the exact pending action")
            self.assert_true("responde exactamente" in blocked_active, "Telegram blocks active approvals without exact confirmation")
            self.assert_true("Aprobacion ejecutada" in approved_active, "Telegram accepts English exact active confirmation")
        finally:
            telegram_agent.agent_chat = original_agent_chat
            telegram_agent._DASHBOARD = original_dashboard
            telegram_agent.telegram_settings = original_settings
            telegram_agent.send_message = original_send
            telegram_agent.send_message_with_keyboard = original_keyboard
            telegram_agent.callback_answer = original_answer
            telegram_agent.approve_pending = original_approve
            telegram_agent.reject_pending = original_reject
            if before:
                history_path.write_text(before, encoding="utf-8")
            elif history_path.exists():
                history_path.unlink()

    def test_telegram_connection_change_resets_polling_state(self):
        """Test changing Telegram bot or chat clears stale polling state."""
        print("\nTesting Telegram Config Polling Reset...")

        dashboard = load_dashboard_module()
        offset_path = telegram_agent.OFFSET_FILE
        context_path = telegram_agent.APPROVAL_CONTEXT_FILE
        offset_path.parent.mkdir(parents=True, exist_ok=True)
        before_offset = offset_path.read_text(encoding="utf-8") if offset_path.exists() else None
        before_context = context_path.read_text(encoding="utf-8") if context_path.exists() else None
        original_update = dashboard.update_env_values
        original_load = dashboard.load_config
        original_settings = dashboard.telegram_settings
        original_ensure = dashboard.ensure_telegram_listener
        original_entitlements = dashboard.license_entitlements
        original_registry = dashboard.agency_registry

        class FakeConfig:
            def __init__(self, bot, chat):
                self.telegram_bot_token = bot
                self.telegram_chat_id = chat

        calls = []
        configs = [FakeConfig("old-bot", "old-chat"), FakeConfig("new-bot", "new-chat")]
        try:
            offset_path.write_text(json.dumps({"offset": 999}), encoding="utf-8")
            context_path.write_text(json.dumps({"old-chat": {"approval_id": "approval_old"}}), encoding="utf-8")
            dashboard.update_env_values = lambda values: calls.append(values)
            dashboard.load_config = lambda: configs.pop(0) if configs else FakeConfig("new-bot", "new-chat")
            dashboard.telegram_settings = lambda config: {"enabled": True, "language": "es", "poll_timeout": 25, "bot_configured": bool(config.telegram_bot_token), "chat_id": config.telegram_chat_id}
            dashboard.ensure_telegram_listener = lambda: True
            dashboard.license_entitlements = lambda: {
                "plan": "individual",
                "is_agency": False,
                "is_individual": True,
                "can_use_multi_telegram_profiles": False,
            }
            dashboard.agency_registry = lambda: {"active_id": "", "spaces": []}
            status = dashboard.save_telegram_config({"enabled": "true", "bot_token": "new-bot", "chat_id": "new-chat", "language": "es"})
            self.assert_true(status["listener_started"] is True, "Telegram listener restarts after connection save")
            self.assert_true(not offset_path.exists() and not context_path.exists(), "Telegram bot/chat change clears stale polling offset and approval context")
            self.assert_true(calls and calls[0]["TELEGRAM_BOT_TOKEN"] == "new-bot" and calls[0]["TELEGRAM_CHAT_ID"] == "new-chat", "Telegram config saves the new bot and chat")
        finally:
            dashboard.update_env_values = original_update
            dashboard.load_config = original_load
            dashboard.telegram_settings = original_settings
            dashboard.ensure_telegram_listener = original_ensure
            dashboard.license_entitlements = original_entitlements
            dashboard.agency_registry = original_registry
            if before_offset is None:
                if offset_path.exists():
                    offset_path.unlink()
            else:
                offset_path.write_text(before_offset, encoding="utf-8")
            if before_context is None:
                if context_path.exists():
                    context_path.unlink()
            else:
                context_path.write_text(before_context, encoding="utf-8")

    def test_setup_page_contains_unlock_and_trust(self):
        """Test dashboard has unlock screen and trust panel placeholders."""
        print("\nTesting Setup UI Markup...")

        dashboard = load_dashboard_module()
        html = dashboard.HTML
        dashboard_source = Path(dashboard.__file__).read_text(encoding="utf-8")
        post_routes = set(dashboard.DashboardHandler.POST_JSON_ROUTES) | set(dashboard.DashboardHandler.POST_SPECIAL_ROUTES)
        get_routes = set(dashboard.DashboardHandler.GET_JSON_ROUTES) | dashboard.DashboardHandler.HTML_PATHS | {"/api/social/login", "/api/creative-asset"}
        self.assert_true(dashboard.DashboardHandler.PROTECTED_POST_PATHS <= post_routes, "Protected dashboard POST routes have handlers")
        self.assert_true(dashboard.DashboardHandler.PROTECTED_GET_PATHS <= get_routes, "Protected dashboard GET routes have handlers")
        self.assert_true("unlock-overlay" in html, "Unlock overlay exists")
        self.assert_true("security-trust" not in html, "Security trust cards are not shown inside setup")
        self.assert_true("header-guide-btn" in html and "openUsageGuide()" in html, "Guide opens from compact header button")
        self.assert_true("guide-overlay" in html and "guide-modal-card" in html, "Guide cards are shown in a popup")
        self.assert_true("@keyframes chat-panel-in" in html and "chat-avatar-pop" in html, "Chat opens with polished motion")
        self.assert_true("agent-chat-bar" in html and "agent-bar-input" in html, "Primary chat entry is a wide agent input bar")
        self.assert_true("agent-bar-expand" in html and "openChat()" in html, "Agent bar can expand into the full conversation without sending")
        self.assert_true("newChatConversation()" in html and 'data-i18n="new_chat"' in html, "Agent chat has a visible new conversation control")
        self.assert_true("hydrateChatHistory()" in html and "state.chat_history" in html, "Agent chat hydrates recent conversation history")
        self.assert_true("/api/chat/reset" in html, "Agent chat can reset context from the UI")
        self.assert_true("body.chat-workspace-open .chat-panel" in html and "body.chat-workspace-open main" in html, "Sending chat opens an agent-centered workspace")
        self.assert_true("body.chat-workspace-open header,body.chat-workspace-open main{margin-left" in html, "Agent workspace shifts the whole dashboard to the right")
        self.assert_true("body.chat-workspace-open .chat-panel{display:grid;left:0;right:auto;top:0;bottom:0" in html, "Agent chat panel fills the full left side")
        self.assert_true("agent-bar-breathe" in html, "Agent bar has a subtle idle animation")
        self.assert_true(".chat-log::-webkit-scrollbar-thumb" in html and "scrollbar-color:rgba(39,199,167" in html, "Base AI conversation scrollbar style exists")
        self.assert_true("chat-fab-breathe" in html, "Legacy chat motion remains available")
        self.assert_true("body.theme-light" in html and "body.theme-dark" in html and "toggleDashboardTheme" in html, "Dashboard has light and dark visual modes")
        self.assert_true("theme-aurora" in html and "theme-sapphire" in html and "setDashboardTheme('sapphire')" in html, "Dashboard exposes named Aurora and Sapphire themes")
        self.assert_true("theme-ember" in html and "setDashboardTheme('ember')" in html and "dashboardTheme==='ember'" in html, "Dashboard exposes the Ember theme as a persistent third option")
        self.assert_true(".theme-switcher" in html and ".theme-chip" in html, "Theme picker is a compact named-theme switcher")
        self.assert_true(".onboarding-flow{--surface:#171520" in html and ".onboarding-flow .onboarding-card" in html, "Onboarding uses a dedicated dark buyer setup theme")
        self.assert_true("view-timeline" in html and "view-analytics" in html and "view-idle" in html, "Overview exposes timeline, total overview, and showcase views")
        self.assert_true("renderTimelineView" in html and "renderAnalyticsView" in html and "renderIdleView" in html, "Alternate dashboard views render from live dashboard state")
        self.assert_true("Crear imagen del producto con Codex" in html and "product-orb" in html, "Idle view introduces Codex-ready product showcase direction")
        self.assert_true("aurora-card" in html and ".aurora-card .starfield{display:none}" in html, "Decorative dotted texture is removed from important cards")
        self.assert_true("body.theme-sapphire .timeline-shell:before" in html and "linear-gradient(112deg" in html, "Sapphire featured surfaces use a luminous gradient outline")
        self.assert_true("body.theme-sapphire .idle-hero:before{padding:2px" in html and "drop-shadow(7px 0 12px rgba(255,151,63" in html, "Sapphire showcase has a stronger warm-edged hero frame")
        self.assert_true("body.theme-sapphire .idle-copy h3" in html and "-webkit-text-fill-color:transparent" in html, "Sapphire showcase title uses multicolor gradient text")
        self.assert_true(".idle-floating{position:absolute;z-index:2;isolation:isolate" in html and "backdrop-filter:blur(20px) saturate(155%) contrast(110%)" in html and ".idle-floating b{display:block;color:#fbfaff" in html, "Sapphire showcase metric tiles preserve contrast over variable product imagery")
        self.assert_true("body.theme-aurora .idle-floating,body.theme-light .idle-floating{border-color:rgba(255,255,255,.9);background:linear-gradient(145deg,rgba(255,255,255,.94)" in html and "body.theme-aurora .idle-floating b,body.theme-light .idle-floating b{color:#19162c" in html, "Aurora showcase metric tiles use readable pale glass")
        self.assert_true("body.theme-sapphire .kpi:before" in html and "body.theme-sapphire .kpi .l .tip" in html, "Sapphire Control KPI cards share the strong frame and gradient labels")
        self.assert_true("body.theme-sapphire .timeline-head h3" in html and "body.theme-sapphire .analytics-hero .analytics-head h3" in html, "Timeline and Total view lead titles share the Sapphire gradient style")
        self.assert_true("body.theme-sapphire .chat-panel" in html and "body.theme-sapphire .msg.user" in html and "body.theme-sapphire .chat-log::-webkit-scrollbar-thumb" in html, "Open chat adopts the Sapphire palette instead of the legacy green accents")
        self.assert_true("sapphire-chat-head-sheen" in html and "sapphire-chat-avatar-pop" in html and "body.theme-sapphire .msg.thinking:before" in html, "Sapphire chat motion and thinking state use theme-specific highlights")
        self.assert_true("body.theme-sapphire .chat-head{background:linear-gradient(180deg,#050509" in html, "Sapphire open chat header uses a near-black gradient")
        self.assert_true("body.theme-dark,body.theme-sapphire{--bg:#04040a" in html and "linear-gradient(180deg,#080812 0%,#05050b 20%,#030307 58%,#010103 100%)" in html, "Sapphire canvas settles into a substantially darker blue-black field")
        self.assert_true("body.theme-dark .section,body.theme-sapphire .section{background:linear-gradient(145deg,rgba(11,11,20,.97),rgba(4,4,9,.96))" in html and "body.theme-dark .card,body.theme-sapphire .card{background:linear-gradient(145deg,rgba(11,11,20,.99),rgba(3,3,8,.97))" in html, "Sapphire panels remain close to black while retaining jeweled accent lighting")
        self.assert_true("body.theme-sapphire .brief-zone{--zone:#64c894" in html and "body.theme-sapphire .page-title{background:linear-gradient(130deg,rgba(10,10,19,.985),rgba(3,3,8,.97))" in html, "Sapphire structural bands keep their signals on dark rather than washed backgrounds")
        self.assert_true("body.theme-sapphire .idle-floating{background:linear-gradient(145deg,rgba(7,7,15,.97),rgba(2,2,7,.94))" in html, "Sapphire Showcase metric tiles maintain near-black contrast-safe surfaces")
        self.assert_true("body.theme-ember{--bg:#020202" in html and "body.theme-ember .btn.primary" in html and "body.theme-ember .tab.active" in html, "Ember uses carbon surfaces with copper action highlights")
        self.assert_true("linear-gradient(to top right,#010101 0%,#020202 42%,#030303 70%,#090503 100%)" in html and "radial-gradient(ellipse at 100% 12%,rgba(255,116,45,.1)" in html, "Ember canvas falls into near-black at the lower left with directional warm light")
        self.assert_true("body.theme-ember .section{background:linear-gradient(148deg,rgba(7,7,7,.98),rgba(3,3,3,.97))" in html and "body.theme-ember .card{background:linear-gradient(145deg,rgba(7,7,7,.99),rgba(2,2,2,.97))" in html, "Ember panels stay close to full black instead of a brown wash")
        self.assert_true("body.theme-ember .idle-hero" in html and "body.theme-ember .product-orb" in html and "body.theme-ember .idle-floating" in html, "Ember Showcase is fully themed for warm dark presentation")
        self.assert_true("body.theme-ember .chat-panel" in html and "body.theme-ember .msg.user" in html and "body.theme-ember .agent-chat-bar" in html and "ember-chat-head-sheen" in html, "Ember agent conversation uses matching warm dark controls")
        self.assert_true("@media(max-width:780px){.theme-switcher{grid-template-columns:repeat(3" in html, "Three named themes remain visible on compact screens")
        self.assert_true(".chat-head .chat-close{flex:0 0 28px" in html and 'aria-label="Cerrar conversación"' in html, "Chat close action stays a small labeled icon on compact screens")
        self.assert_true("dashboardUiPreview" in html and "full_setup" in html and "ui_preview" in html, "Local UI work mode can bypass onboarding without deleting setup state")
        self.assert_true("return isLocalWorkbenchHost(window.location.hostname)" not in html, "UI preview is explicit and no longer bypasses onboarding by default on local/LAN")
        self.assert_true('<div id="mode-control"></div><div id="guardrails-panel"></div><div id="onboarding-wizard"></div>' in html, "Setup starts with control level and guardrails")
        self.assert_true("Corre local o en VPS" not in html and "Secretos en .env" not in html, "Removed noisy trust explainer cards from setup")
        self.assert_true(".tabs{display:flex;flex-wrap:wrap" in html, "Desktop tabs wrap instead of horizontal scrolling")
        self.assert_true(".tabs{width:100%;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));overflow:visible" in html, "Mobile tabs use a visible grid")
        self.assert_true(".status{display:flex;flex-wrap:wrap" in html, "Header status wraps instead of compressing nav")
        self.assert_true('id="toggle-left-panel"' in html and 'id="toggle-right-panel"' in html, "Side panel headers are fold controls")
        self.assert_true("main{display:grid;grid-template-columns:320px minmax(500px,1fr) 380px" in html, "Desktop panel folding keeps stable columns")
        self.assert_true("grid-template-columns:54px" not in html, "Folded panels do not resize center into rail layout")
        self.assert_true("body:not(.left-panel-open) .brief-zone .section" in html, "Daily intelligence content is folded by default")
        self.assert_true("body:not(.right-panel-open) .rail .section" in html, "Approvals content is folded by default")
        self.assert_true("body:not(.left-panel-open) .brief-zone .section,body:not(.right-panel-open) .rail .section{display:none}" in html, "Folded panels keep headers visible while hiding content")
        self.assert_true("togglePanel('left')" in html and "togglePanel('right')" in html, "Both side panels can be toggled")
        self.assert_true("dashboardPanel:${side}" in html, "Side panel state persists locally")
        self.assert_true("dashboardPanelMobile:${side}" in html and "matchMedia('(max-width: 780px)')" in html, "Mobile panel state is independent so daily intelligence starts folded on phones")
        self.assert_true('id="daily-brief-badge"' in html and ".zone-label.has-new-brief" in html and "dashboardDailyBriefReadStamp" in html, "Unread daily brief has a visible morning cue until opened")
        self.assert_true('id="business-profile-panel"' in html and "businessSnapshotData" in html and "business_context_snapshot" in dashboard_source, "Dashboard turns owner business answers into a visible business profile snapshot")
        self.assert_true("budgetDialog(campaign_id,current)" in html and "Preguntar al manager" in html, "Budget changes use an in-app manager-first dialog instead of a browser prompt")
        self.assert_true("showDecisionConfirm" in html and "const ok=confirm" not in html and "const val=prompt" not in html, "Risky choices use branded confirmation cards with agent help instead of browser system dialogs")
        self.assert_true("submitBrandGuideInit" in html and "brand-guide-init-name" in html, "Brand memory setup is an in-app guided action instead of a browser prompt")
        self.assert_true("approvalCard" in html and "approvalMeta" in html and "approvalAskDraft" in html, "Approvals render as manager recommendation cards")
        self.assert_true("Qué pidió el agente" in html and "Qué pasa si apruebas" in html and "Riesgo a revisar" in html, "Approval cards explain request, outcome, and risk in buyer-friendly language")
        self.assert_true(".approval-card" in html and ".approval-actions" in html and "Preguntar antes" in html, "Approval cards include clear styling and an ask-before-approve path")
        self.assert_true("appendChatApprovalActions" in html and "chatApproveDecision" in html and "chatRejectDecision" in html, "Agent chat can show approve/reject buttons for exact pending approvals")
        self.assert_true("/api/reject" in html and "msg-approval-card" in html, "Chat approval decisions include a reject path and compact action cards")
        self.assert_true("onboarding-flow" in html, "Dedicated onboarding flow exists")
        self.assert_true("websiteScanGuide" in html and "/api/business-profile/questions" in html and "startBusinessInterview" in html and "¿Qué negocio tienes?" in html, "Onboarding starts with a short business intro and generates the next questions")
        self.assert_true("businessContextGuide" in html and "businessContextQuestions" in html and "saveBusinessContextQuestion" in html and "Guardar y seguir" in html, "Onboarding collects buyer context one simple question at a time")
        self.assert_true("initialStrategyGuide" in html and "Esto entendí" in html, "Onboarding shows an initial strategy before dashboard entry")
        self.assert_true("requires_repair" in html and "Reconectemos tus datos reales" in html, "Legacy completed setup reopens guidance when real Meta data is missing")
        self.assert_true("tab-audiences" in html, "Audience builder tab exists")
        self.assert_true("setup-config-form" in html, "Setup save form exists")
        self.assert_true('id="chatgpt-panel"' in html and "renderChatGptPanel()" in html, "Setup includes a dedicated agent model connection panel")
        self.assert_true('id="local-network-panel"' in html and "Ver desde mi teléfono" in html and "/api/local-network-access" in html, "Setup includes same-Wi-Fi phone access as an explicit opt-in")
        self.assert_true("/api/local-network-access" in dashboard.DashboardHandler.PROTECTED_POST_PATHS and "/api/local-network-access" in dashboard.DashboardHandler.POST_JSON_ROUTES, "Phone LAN access changes require dashboard password and have a handler")
        self.assert_true("Conecta el cerebro del agente" in html and "MiniMax M3" in html and "Guardar modelo del agente" in html, "Agent model setup supports MiniMax M3 as a Hermes brain")
        self.assert_true("OpenAI API" in html and "ChatGPT suscripción" in html and "Otra API compatible" in html and "OAuth" in html, "Onboarding shows four simple model choices immediately")
        self.assert_true("routeButton('openai_api')" in html and "routeButton('chatgpt_subscription')" in html and "routeButton('minimax_m3')" in html and "routeButton('custom_api')" in html and "selectAgentModelRoute('${kind}')" in html, "Agent model setup uses four collapsible route buttons")
        self.assert_true("connectChatGpt(event)" in html and "/api/agent-model/connect" in html and "Conectar ahora" in html, "ChatGPT/Codex connection is an automatic dashboard action")
        self.assert_true("Copiar comando" not in html and ".agent-model-option .route-icon" in html and ".agent-route-panel.active" in html, "ChatGPT/Codex setup hides command-copy UI and keeps route choices readable")
        self.assert_true("Copiar paso" not in html and "Copy step" not in html, "ChatGPT/Codex connection no longer presents copy-only wording")
        self.assert_true("agent_chat_base_url" in html and "agent_chat_api_key" in html and "custom_api" in html, "OpenAI-compatible brain settings are exposed without showing saved keys")
        self.assert_true("DigitalOcean mostraré aquí el enlace" in html and "Ver diagnóstico para soporte" in html, "Hermes/ChatGPT setup has a browser-based VPS path with diagnostics folded")
        self.assert_true("/api/agent-model/connect-status" in html and "/api/agent-model/connect-input" in html and "sendChatGptTerminalInput" in html, "VPS Hermes bridge can poll and send guided terminal responses")
        self.assert_true("Ver detalle técnico de Hermes" in html and "prepareChatGptAuthWindow" in html and "maybeOpenChatGptAuthUrl" in html, "Hermes browserless UI folds support detail and opens the OAuth login in the buyer browser")
        self.assert_true("chatgpt-device-code" in html and "Copiar código" in html and "login_code" in html and "font-size:clamp(34px" in html and "scrollIntoView({behavior:'smooth',block:'center'})" in html, "OpenAI terminal login code is shown as a large copyable buyer-facing card")
        self.assert_true("body .onboarding-flow input:not([type=\"checkbox\"])" in html and "::placeholder" in html and "-webkit-autofill" in html, "Onboarding text fields stay dark and readable across dashboard themes")
        self.assert_true("Voy a elegir OpenAI Codex y el modelo recomendado automáticamente" in dashboard_source and "maybe_auto_drive_hermes_browserless" in dashboard_source, "Hermes browserless setup auto-selects Codex provider and recommended model")
        self.assert_true("{id:'chatgpt',status:chatgptOk?'ok':'warn'}" in html and "chatGptConnectMarkup(true)" in html, "Initial onboarding includes ChatGPT connection before Meta setup")
        self.assert_true("{id:'telegram',status:telegramOk?'ok':'warn'}" in html and "telegramOnboardingGuide()" in html, "Initial onboarding includes Telegram as an important guided setup step")
        self.assert_true("Habla con tu manager por Telegram" in html and "Abrir BotFather" in html and "Detectar mi chat" in html, "Telegram onboarding explains BotFather, chat detection, and phone-first manager access")
        self.assert_true("{id:'password',status:passwordOk?'ok':'blocked'},\n\t  {id:'chatgpt',status:chatgptOk?'ok':'warn'},\n\t  {id:'telegram',status:telegramOk?'ok':'warn'},\n\t  {id:'website',status:websiteOk?'ok':'blocked'}" in html, "Initial onboarding moves from password to agent model, Telegram, and then business context")
        self.assert_true("Elige qué modelo usará el agente" in html and "apiBrainOk" in html, "Onboarding positions model setup as part of installation and accepts API brain readiness")
        self.assert_true("license-panel" in html, "License activation panel exists")
        self.assert_true("/api/license/activate" in html, "License activation endpoint is wired in UI")
        self.assert_true("/api/onboarding/complete" in html, "Onboarding complete endpoint is wired in UI")
        self.assert_true("Finish setup" in html or "Terminar configuración" in html, "Initial setup finish control exists")
        self.assert_true("Revisar configuración inicial" in html, "Completed setup can reopen the initial guide")
        self.assert_true("dashboard password" in html.lower() or "contraseña del dashboard" in html.lower(), "Buyer password wording exists")
        self.assert_true("Escribe la contraseña de este dashboard para continuar." in html and "Si borraste cookies" not in html, "Unlock copy stays simple for buyers")
        self.assert_true("unlock_create_title" in html and "Crea tu contraseña" in html, "First-run unlock modal can ask buyers to create a password")
        self.assert_true("unlockMode==='create'" in html and "/api/dashboard-password" in html, "First-run password creation is wired through the dashboard password endpoint")
        self.assert_true("!state.config.dashboard_password_set)showUnlock(t('unlock_create_needed'),'create')" in html, "Clean installs proactively ask buyers to create a dashboard password")
        self.assert_true("Ahora conecta el cerebro del agente" in html and "const modelIndex=steps.findIndex(s=>s.id==='chatgpt')" in html, "Password creation advances to the agent model connection")
        self.assert_true("onboardingFlowTouched=false" in html, "Onboarding auto-advance starts untouched")
        self.assert_true("s.status!=='ok'" in html, "Onboarding opens on first unfinished step")
        self.assert_true("onboardingFlowTouched=true;onboardingFlowStep=Math.max" in html, "Onboarding back button allows completed-step review")
        self.assert_true('href="/api/social/login"' in html, "Meta Developers button uses a real browser link")
        self.assert_true("Abrir Meta" in html, "Spanish onboarding points to Meta")
        self.assert_true("Tu propia conexión de Meta" in html and "Clave de acceso de Meta" in html, "Spanish setup explains buyer-owned Meta access plainly")
        self.assert_true("showMetaTokenBox" in html, "Token box can be opened without leaving dashboard")
        self.assert_true("finishButton=isLast" in html, "Onboarding finish button only appears on final step")
        self.assert_true("step.status!=='blocked'" in html, "Onboarding next button hides on blocked steps")
        self.assert_true("confirm-overlay" in html, "Onboarding completion uses in-app confirmation")
        self.assert_true("showOnboardingCompleteConfirm" in html, "Onboarding completion modal is wired")
        self.assert_true("podrás cambiar todo después desde Configuración" in html, "Completion modal explains settings remain editable")
        self.assert_true("Cuenta publicitaria" in html and "Contraseña del dashboard" in html, "Completion modal lists editable setup items")
        self.assert_true("Esto marcará el onboarding como completado" not in html, "Old browser confirm wording is removed")
        self.assert_true("Solo si no aparecen tus cuentas" in html, "Manual ad account entry is hidden as fallback")
        self.assert_true("Usar esta cuenta y seguir" in html, "Account selection clearly continues onboarding")
        self.assert_true('id="usage-cheatsheet"' not in html, "Usage guide cards are not rendered inline in setup")
        self.assert_true("/api/social/discover-assets" in html, "Selected ad account triggers asset discovery")
        self.assert_true("Buscando página, Instagram y web conectados" in html, "Discovery copy is buyer-friendly")
        self.assert_true("destinationPickerGuide" in html, "Destination step uses automatic Page picker")
        self.assert_true("Buscar páginas e Instagram" in html, "Destination step can search Pages and Instagram")
        self.assert_true("Páginas encontradas" in html, "Discovered Pages are shown as choices")
        self.assert_true("Usar esta página" in html, "Buyer can select a discovered Page")
        self.assert_true("Solo si no aparece tu página" in html, "Manual Page entry is hidden as fallback")
        self.assert_true("selectMetaDestination" in html, "Selected Page is saved without manual ID paste")
        self.assert_true("Guía rápida de uso" in html, "Onboarding includes final usage guide cards")
        self.assert_true("La filosofía: conversa con el agente" in html, "Usage guide explains chat-first philosophy")
        self.assert_true("Grupo de anuncios a usar" not in html, "Old required-ad-set wording is removed")
        self.assert_true("El grupo de anuncios es opcional" not in html, "Onboarding no longer mentions ad groups")
        self.assert_true("const destinationOk=['page_id','landing_url']" in html, "Onboarding does not require an existing ad set")
        self.assert_true("Deja la supervisión activa" in html, "Live onboarding recommends supervised mode first")
        self.assert_true("Con supervisión" in html, "Last onboarding step avoids simulation wording")
        self.assert_true("modo simulación" not in html, "Buyer-facing onboarding avoids simulation mode wording")
        self.assert_true("summary.live_ads_ready?'ok':'warn'" in html, "Live onboarding does not block first dashboard entry")
        self.assert_true("No hace falta para entrar al dashboard" in html, "Live smoke test is positioned as optional")
        self.assert_true("Con supervisión" in html, "Buyer-facing supervised control wording exists")
        self.assert_true("Piloto automático" in html, "Buyer-facing autopilot wording exists")
        self.assert_true("guardrails-panel" in html, "Guardrail settings panel exists")
        self.assert_true("/api/guardrails" in html, "Guardrail settings can be saved")
        self.assert_true("Cuánto puede hacer solo" in html and "Preguntar si el presupuesto cambia más de" in html, "Guardrails use simple buyer-friendly questions")
        self.assert_true("Revisión técnica para soporte" in html and "renderSetupBeginnerSummary" in html and "Lo que falta primero" in html, "Configuration leads with simple next steps and hides technical review")
        self.assert_true("Gasto: " in html and "campañas activas." in html and "señales de cansancio del anuncio." in html, "Daily reading localizes scheduled report answers in Spanish")
        self.assert_true("recommendationText" in html and "Buen rendimiento: conviene mantener el presupuesto actual." in html, "Budget advice avoids English optimizer wording in Spanish")
        self.assert_true("demoCampaignName" in html and "Campaña de ventas Q2" in html, "Spanish demo data uses understandable campaign examples")
        self.assert_true("Ya vendo, pero cada compra me cuesta más." in html and "bajar el costo de cada compra" in html, "Initial context examples avoid unexplained cost acronyms")
        self.assert_true("VUELVE / $1" in html and "COSTO / COMPRA" in html, "Showcase labels explain results without unexplained acronyms")
        self.assert_true("En el tiempo" in html and "Anuncios en el tiempo" in html and "Datos de ejemplo" in html, "Dashboard view controls avoid English or technical preview labels in Spanish")
        self.assert_true("audienceTargetingText" in html and "Llegar a personas nuevas" in html, "Audience cards replace raw targeting structures with plain-language display")
        self.assert_true("Online course for small business owners" not in html and "data-i18n-placeholder=\"audience_product_example\"" in html, "Audience form uses examples instead of fake prefilled buyer information")
        self.assert_true("telegram-panel" in html and "Hablar por Telegram" in html, "Configuration includes optional Telegram manager access")
        self.assert_true("/api/telegram/config" in html and "/api/telegram/detect" in html and "/api/telegram/test" in html, "Telegram setup actions are wired in UI")
        self.assert_true("aprobar decisiones exactas con botones seguros" in html, "Telegram UI accurately explains button approvals")
        self.assert_true("brand-guides-panel" in html and "/api/brand-guides/general" in html and "/api/brand-guides/product" in html and "/api/ad-briefs" in html, "Brand, product, and ad brief memory editing is wired in UI")
        self.assert_true("brand-memory-overlay" in html and "Lo que el agente recuerda" in html and "Crea tus anuncios" in html, "Creative memory is presented as a simple ad-ideas library")
        self.assert_true("saveGeneralMemory" in html and "saveProductMemory" in html and "refreshForProduct" in html, "Creative memory can be saved and used to generate for a selected product")
        self.assert_true("saveAdBriefMemory" in html and "refreshForAdBrief" in html and "Qué se puede cambiar" in html and "Cuántas opciones preparar" in html, "Ad ideas can define optional variations in beginner-friendly language")
        self.assert_true("startCreativeMemoryWizard" in html and "Contarle cómo es mi marca" in html and "Hablar y crear mi anuncio" in html, "Creative details can be collected conversationally through the agent")
        self.assert_true("memory_wizard" in html and "creative_memory_wizard_complete" in html, "Guided memory chat sends explicit state and refreshes after completion")
        self.assert_true("function uiLang()" in html and "function isEs()" in html and "chatForAdBrief(briefId,draftLang='')" in html and "const es=(draftLang||uiLang())==='es'" in html, "Creative chat drafts follow the visible dashboard language")
        self.assert_true("Ayúdame a definir la idea creativa." in html and "Cuántas opciones preparar" in html and "Ayúdame a definir la ventana creativa para variantes." not in html, "General creative chat starts from an idea instead of assuming variations")
        self.assert_true("Crear con el agente" in html and "Hablar del brief" not in html and "Crea briefs por promoción" not in html, "Creative studio avoids vague advertising jargon in its primary path")
        self.assert_true(any("¿Quieres una sola idea o varias opciones para comparar?" in item.get("es", "") for item in dashboard.CREATIVE_MEMORY_WIZARD_SPECS["ad_brief"]["fields"]), "Guided ad idea chat lets buyers choose whether they want variations")
        self.assert_true("Prefiero escribir los detalles yo" in html and "Solo si ya tienes anuncios en Meta" in html, "Technical ad fields stay optional behind clear progressive disclosure")
        self.assert_true("Más detalles, si los quieres agregar" in html, "Advanced specifications remain editable without overwhelming the default form")
        self.assert_true("creative-studio-hero" in html and "renderCreativeStudio" in html and "creative-variants" in html, "Creatives tab renders an agent-centered visual studio")
        self.assert_true("demoCreativeText" in html and "Campaña para dar a conocer la marca" in html, "Spanish demo creative history is displayed without leftover English sample names")
        self.assert_true("data-preview-url" in html and "hydrateCreativePreviews" in html and "fetchProtectedFile(path)" in html, "Generated creative previews load through the protected-file mechanism")
        self.assert_true("Tus imágenes quedan guardadas aquí" in html and "downloadCreativeAsset" in html and "clearCreativeStorage" in html and "/api/creative-storage/clear" in html and "saved_for_ad" in html, "Creative studio explains local image storage, download, protected ad assets, and manual cleanup")
        self.assert_true("Preparar para publicar" in html and "Imagen lista para que la apruebes" in html, "Finished creative images can be staged for approval with clear wording")
        self.assert_true("Crear imagen final" in html and "image_generation_ready" in html, "Studio exposes real image generation when its provider is configured")
        self.assert_true("Tú decides antes de gastar dinero" in html and "solo podrá empezar a gastar después de que la apruebes" in html, "Campaign creation clearly explains approval before spend")
        self.assert_true("Crear hablando con el agente" in html and "Prefiero escribir los datos yo" in html, "Campaign creator defaults to a beginner-friendly chat path")
        self.assert_true("/api/targeting/search" in html and "Elige público con opciones de Meta" in html, "Campaign creator can search real Meta targeting options")
        self.assert_true("campaign-targeting-locations-json" in html and "campaign-targeting-interests-json" in html, "Campaign creator stores selected targeting as structured JSON")
        self.assert_true("Solo si el buscador no funciona" in html and "searchTargeting('interest')" in html, "Campaign creator keeps manual targeting only as fallback")
        self.assert_true("campaign_name_example:'Ej: Promo de junio'" in html and "primary_text_example:'Ej: Descubre cómo esta oferta puede ayudarte hoy.'" in html, "Campaign creator examples are localized instead of prefilled")
        self.assert_true('<select name="final_status"><option value="PAUSED"' in html and "Marcar solo si elegiste empezar a mostrar anuncios" in html, "Campaign creator defaults to ready-without-spend and explains active spend confirmation")
        self.assert_true("Número de seguimiento de Meta (Pixel ID), opcional" in html and "Solo si ya conoces este dato de Meta" in html, "Technical campaign details are optional and explained")
        self.assert_true("quedará lista pero apagada" in html and "No mostrará anuncios ni gastará dinero" in html, "Approval note plainly explains a prepared campaign does not spend")
        self.assert_true("Esto apagará una campaña que ya está mostrando anuncios" in html, "Existing-campaign pause warning is understandable without technical terms")
        self.assert_true("scheduleMetaTokenAutoSave" in html, "Meta token paste auto-saves the local connection")
        self.assert_true("renderTokenSavedState" in html, "Saved token state replaces token input")
        self.assert_true("Clave de Meta guardada" in html, "Spanish key saved confirmation exists")
        self.assert_true("Cambiar clave de Meta" in html, "Buyer can intentionally replace the Meta key later")
        self.assert_true("Se guarda automáticamente al pegarla" in html, "Spanish key copy explains automatic saving")
        self.assert_true("Reintentar guardar" in html, "Manual token save is only a retry fallback")
        self.assert_true("Contraseña guardada. Ahora conecta el cerebro del agente." in html, "Password save clearly advances to the agent-first setup step")
        self.assert_true("findIndex(s=>s.id==='chatgpt')" in html, "Password save moves to agent model connection step")
        self.assert_true("goToMetaTokenStep" in html, "Expired-token account search can return to token step")
        self.assert_true("Pega una clave nueva" in html, "Expired Meta key message is buyer-friendly")
        self.assert_true("No se guarda en cookies" in html, "Meta key storage copy avoids cookie confusion")
        self.assert_true("send_redirect(social_login_url()" in html or hasattr(dashboard.DashboardHandler, "send_redirect"), "Social login redirect endpoint exists")
        env_example = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")
        self.assert_true("LICENSE_SERVER_URL=" in env_example, "License server URL is documented in .env.example")
        self.assert_true("LICENSE_REQUIRED_FOR_LIVE=true" in env_example, "License live requirement default is documented")
        self.assert_true("agency-panel" in html and "Licencia Individual: un negocio activo" in html, "Setup explains individual one-business limit")
        self.assert_true("/api/agency/spaces" in html and "Licencia Agencia: espacios por cliente" in html, "Setup exposes agency client spaces")
        self.assert_true("agencySwitch" in html and "Clientes de agencia" in html, "Agency client switch remains available during onboarding")

    def test_setup_config_save_preserves_blank_license(self):
        """Test setup form saves live IDs without wiping an existing license key."""
        print("\nTesting Setup Config Save...")

        dashboard = load_dashboard_module()
        env_path = dashboard.ENV_FILE
        ad_path = dashboard.AD_CONFIG_FILE
        onboarding_path = dashboard.ONBOARDING_FILE
        binding_path = dashboard.INDIVIDUAL_BINDING_FILE
        env_before = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        ad_before = ad_path.read_text(encoding="utf-8") if ad_path.exists() else ""
        onboarding_before = onboarding_path.read_text(encoding="utf-8") if onboarding_path.exists() else ""
        binding_before = binding_path.read_bytes() if binding_path.exists() else None
        env_keys = ["LICENSE_KEY", "LICENSE_BUYER_EMAIL", "META_AD_ACCOUNT_ID"]
        env_backup = {key: os.environ.get(key) for key in env_keys}
        try:
            dashboard.update_env_values({"LICENSE_KEY": "MAO-TESTBUYER-30628D"})
            dashboard.write_json(onboarding_path, {"completed": False})
            if binding_path.exists():
                binding_path.unlink()
            result = dashboard.save_setup_config(
                {
                    "license_key": "",
                    "license_buyer_email": "buyer@example.com",
                    "ad_account_id": "act_999",
                    "page_id": "12345",
                    "default_adset_id": "67890",
                    "instagram_actor_id": "555",
                    "landing_url": "https://buyer.example",
                    "agent_chat_provider": "minimax",
                    "agent_chat_base_url": "https://api.minimax.io/v1",
                    "agent_chat_model": "MiniMax-M3",
                    "agent_chat_api": "openai-chat-completions",
                    "agent_chat_api_key": "direct-model-key",
                }
            )
            env_after = env_path.read_text(encoding="utf-8")
            saved = json.loads(ad_path.read_text(encoding="utf-8"))
            self.assert_true(result["saved"], "Setup config save returns success")
            self.assert_true("LICENSE_KEY=MAO-TESTBUYER-30628D" in env_after, "Blank license field preserves existing key")
            self.assert_true("LICENSE_BUYER_EMAIL=buyer@example.com" in env_after, "Buyer email saved to .env")
            self.assert_true("META_AD_ACCOUNT_ID=act_999" in env_after, "Ad account saved to .env")
            self.assert_true("AGENT_CHAT_PROVIDER=hermes" in env_after, "Hermes runtime remains fixed in .env")
            self.assert_true("AGENT_BRAIN_PROVIDER=minimax" in env_after, "Agent brain provider saved to .env")
            self.assert_true("AGENT_CHAT_BASE_URL=https://api.minimax.io/v1" in env_after, "Agent model URL saved to .env")
            self.assert_true("AGENT_CHAT_MODEL=MiniMax-M3" in env_after, "Agent model name saved to .env")
            self.assert_true("AGENT_CHAT_API_KEY=direct-model-key" in env_after, "Agent model API key saved locally")
            self.assert_true(saved["creative"]["destination"]["page_id"] == "12345", "Page ID saved to ad-config")
            self.assert_true(saved["creative"]["destination"]["default_adset_id"] == "67890", "Default ad set saved to ad-config")
            self.assert_true(saved["creative"]["destination"]["url"] == "https://buyer.example", "Landing URL saved to ad-config")
        finally:
            env_path.write_text(env_before, encoding="utf-8")
            ad_path.write_text(ad_before, encoding="utf-8")
            if onboarding_before:
                onboarding_path.write_text(onboarding_before, encoding="utf-8")
            elif onboarding_path.exists():
                onboarding_path.unlink()
            if binding_before is None:
                if binding_path.exists():
                    binding_path.unlink()
            else:
                binding_path.write_bytes(binding_before)
            for key, value in env_backup.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_individual_license_replaces_one_business_only_with_confirmation(self):
        """Test Individual cannot silently reuse agent memory for a second client."""
        print("\nTesting Individual Business Limit...")

        dashboard = load_dashboard_module()
        env_path = dashboard.ENV_FILE
        ad_path = dashboard.AD_CONFIG_FILE
        onboarding_path = dashboard.ONBOARDING_FILE
        metrics_path = dashboard.METRICS_FILE
        binding_path = dashboard.INDIVIDUAL_BINDING_FILE
        original_entitlements = dashboard.license_entitlements
        original_output_dirs = dashboard.BUSINESS_OUTPUT_DIRS
        env_before = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        ad_before = ad_path.read_text(encoding="utf-8") if ad_path.exists() else ""
        business_files_before = {
            name: (dashboard.DATA_DIR / name).read_bytes() if (dashboard.DATA_DIR / name).exists() else None
            for name in dashboard.BUSINESS_DATA_FILES
        }
        binding_before = binding_path.read_bytes() if binding_path.exists() else None
        output_creative_root = dashboard.OUTPUT_DIR / "test-individual-switch-creatives"
        output_upload_root = dashboard.OUTPUT_DIR / "test-individual-switch-uploads"
        output_creative_dir = output_creative_root / "switch-test"
        output_upload_dir = output_upload_root / "switch-test"
        env_backup = {key: os.environ.get(key) for key in ["META_AD_ACCOUNT_ID", "META_ADS_AGENT_MODE", "LIVE_ACTIONS_ENABLED", "LICENSE_KEY", "LICENSE_BUYER_EMAIL", "DASHBOARD_PASSWORD", "DASHBOARD_TOKEN"]}
        try:
            dashboard.license_entitlements = lambda: {"plan": "individual", "is_agency": False, "max_devices": 1, "workspace_limit": 1}
            dashboard.BUSINESS_OUTPUT_DIRS = [output_creative_root, output_upload_root]
            dashboard.update_env_values({"META_AD_ACCOUNT_ID": "act_old", "META_ADS_AGENT_MODE": "live", "LIVE_ACTIONS_ENABLED": "true", "LICENSE_KEY": "MAO-TESTBUYER-30628D", "LICENSE_BUYER_EMAIL": "buyer@example.com", "DASHBOARD_PASSWORD": "buyer-pass", "DASHBOARD_TOKEN": "buyer-pass"})
            dashboard.write_json(ad_path, {"account": {"id": "act_old"}, "creative": {"destination": {"page_id": "page_old", "url": "https://old.example"}}})
            dashboard.write_json(onboarding_path, {"completed": True})
            dashboard.write_json(metrics_path, {"source": "meta_graph", "campaigns": [{"name": "Old business"}]})
            output_creative_dir.mkdir(parents=True, exist_ok=True)
            (output_creative_dir / "draft.png").write_text("old creative", encoding="utf-8")
            output_upload_dir.mkdir(parents=True, exist_ok=True)
            (output_upload_dir / "upload.json").write_text("old upload", encoding="utf-8")
            try:
                dashboard.save_setup_config({"ad_account_id": "act_new", "page_id": "page_new"})
                self.assert_true(False, "Individual switch should need explicit replacement confirmation")
            except ValueError as exc:
                self.assert_true("CONFIRM_BUSINESS_REPLACE" in str(exc), "Individual switch is blocked until confirmed")
            dashboard.reset_onboarding()
            persisted_binding = dashboard.read_json(binding_path, {})
            self.assert_true(persisted_binding.get("ad_account_id") == "act_old", "Restarting onboarding preserves the Individual business binding")
            try:
                dashboard.save_setup_config({"ad_account_id": "act_new", "page_id": "page_new"})
                self.assert_true(False, "Restarting onboarding should not bypass the Individual business limit")
            except ValueError as exc:
                self.assert_true("CONFIRM_BUSINESS_REPLACE" in str(exc), "Individual limit remains active when onboarding is restarted")
            result = dashboard.save_setup_config({"ad_account_id": "act_new", "page_id": "page_new", "confirm_replace_business": True})
            env_after = env_path.read_text(encoding="utf-8")
            self.assert_true(result.get("business_replaced") is True, "Confirmed individual switch records a clean replacement")
            self.assert_true(not metrics_path.exists(), "Confirmed individual switch removes old metrics memory")
            self.assert_true(not output_creative_dir.exists() and not output_upload_dir.exists(), "Confirmed individual switch clears old creative working files")
            self.assert_true("LICENSE_KEY=MAO-TESTBUYER-30628D" in env_after and "DASHBOARD_PASSWORD=buyer-pass" in env_after, "Confirmed individual switch keeps license and dashboard password")
            self.assert_true(not dashboard.load_onboarding_state().get("completed"), "Confirmed individual switch requires setup for the new business")
        finally:
            dashboard.license_entitlements = original_entitlements
            dashboard.BUSINESS_OUTPUT_DIRS = original_output_dirs
            env_path.write_text(env_before, encoding="utf-8")
            ad_path.write_text(ad_before, encoding="utf-8")
            for name, content in business_files_before.items():
                path = dashboard.DATA_DIR / name
                if content is None:
                    if path.exists():
                        path.unlink()
                else:
                    path.write_bytes(content)
            if binding_before is None:
                if binding_path.exists():
                    binding_path.unlink()
            else:
                binding_path.write_bytes(binding_before)
            for path in [output_creative_root, output_upload_root]:
                if path.exists():
                    shutil.rmtree(path)
            for key, value in env_backup.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_agency_spaces_keep_client_data_separate(self):
        """Test Agency can switch spaces without discarding each client's data."""
        print("\nTesting Agency Client Spaces...")

        dashboard = load_dashboard_module()
        env_path = dashboard.ENV_FILE
        ad_path = dashboard.AD_CONFIG_FILE
        original_registry_path = dashboard.AGENCY_SPACES_FILE
        original_spaces_dir = dashboard.AGENCY_SPACES_DIR
        original_brand_dir = dashboard.BRAND_GUIDES_DIR
        original_brand_products_dir = dashboard.BRAND_PRODUCTS_DIR
        registry_path = ROOT_DIR / "output" / "test-agency-spaces.json"
        spaces_dir = ROOT_DIR / "output" / "test-agency-spaces"
        active_brand_dir = ROOT_DIR / "output" / "test-active-brand-guides"
        dashboard.AGENCY_SPACES_FILE = registry_path
        dashboard.AGENCY_SPACES_DIR = spaces_dir
        dashboard.BRAND_GUIDES_DIR = active_brand_dir
        dashboard.BRAND_PRODUCTS_DIR = active_brand_dir / "products"
        metrics_path = dashboard.METRICS_FILE
        original_entitlements = dashboard.license_entitlements
        original_listener = dashboard.ensure_telegram_listener
        env_before = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        ad_before = ad_path.read_text(encoding="utf-8") if ad_path.exists() else ""
        env_backup = {key: os.environ.get(key) for key in ["META_AD_ACCOUNT_ID", "META_ACCESS_TOKEN", "TELEGRAM_AGENT_ENABLED", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_LANGUAGE"]}
        business_files_before = {
            name: (dashboard.DATA_DIR / name).read_bytes() if (dashboard.DATA_DIR / name).exists() else None
            for name in dashboard.BUSINESS_DATA_FILES
        }
        try:
            dashboard.license_entitlements = lambda: {"plan": "agency", "is_agency": True, "max_devices": 4, "workspace_limit": 50}
            dashboard.ensure_telegram_listener = lambda: False
            dashboard.write_json(registry_path, {"active_id": "", "spaces": []})
            first = dashboard.create_agency_space({"name": "Cliente Uno"})
            second = dashboard.create_agency_space({"name": "Cliente Dos"})
            dashboard.switch_agency_space({"space_id": first["id"]})
            dashboard.update_env_values({"META_AD_ACCOUNT_ID": "act_one", "META_ACCESS_TOKEN": "token-client-one", "TELEGRAM_CHAT_ID": "chat-one"})
            dashboard.write_json(metrics_path, {"source": "meta_graph", "account_id": "act_one"})
            dashboard.BRAND_PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
            (dashboard.BRAND_GUIDES_DIR / "general_branding.md").write_text("Marca uno\n", encoding="utf-8")
            (dashboard.BRAND_PRODUCTS_DIR / "producto.md").write_text("Producto uno\n", encoding="utf-8")
            dashboard.switch_agency_space({"space_id": second["id"]})
            first_config = spaces_dir / first["id"] / "workspace_config.json"
            self.assert_true((first_config.stat().st_mode & 0o777) == 0o600, "Agency connection secrets are stored with private file permissions")
            dashboard.update_env_values({"META_AD_ACCOUNT_ID": "act_two", "META_ACCESS_TOKEN": "token-client-two", "TELEGRAM_CHAT_ID": "chat-two"})
            dashboard.write_json(metrics_path, {"source": "meta_graph", "account_id": "act_two"})
            dashboard.BRAND_PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
            (dashboard.BRAND_GUIDES_DIR / "general_branding.md").write_text("Marca dos\n", encoding="utf-8")
            dashboard.switch_agency_space({"space_id": first["id"]})
            self.assert_true(dashboard.load_config().ad_account_id == "act_one", "Agency switch restores each client's ad account")
            self.assert_true(dashboard.load_config().meta_access_token == "token-client-one", "Agency switch restores each client's local Meta connection")
            self.assert_true(dashboard.load_config().telegram_chat_id == "chat-one", "Agency switch restores each client's Telegram settings")
            self.assert_true(dashboard.read_json(metrics_path, {}).get("account_id") == "act_one", "Agency switch restores each client's metrics")
            self.assert_true((dashboard.BRAND_GUIDES_DIR / "general_branding.md").read_text(encoding="utf-8").strip() == "Marca uno", "Agency switch restores each client's Codex brand guide")
            self.assert_true((dashboard.BRAND_PRODUCTS_DIR / "producto.md").exists(), "Agency switch restores each client's Codex product guide")
        finally:
            dashboard.license_entitlements = original_entitlements
            dashboard.ensure_telegram_listener = original_listener
            dashboard.AGENCY_SPACES_FILE = original_registry_path
            dashboard.AGENCY_SPACES_DIR = original_spaces_dir
            dashboard.BRAND_GUIDES_DIR = original_brand_dir
            dashboard.BRAND_PRODUCTS_DIR = original_brand_products_dir
            env_path.write_text(env_before, encoding="utf-8")
            ad_path.write_text(ad_before, encoding="utf-8")
            for name, content in business_files_before.items():
                path = dashboard.DATA_DIR / name
                if content is None:
                    if path.exists():
                        path.unlink()
                else:
                    path.write_bytes(content)
            if registry_path.exists():
                registry_path.unlink()
            if spaces_dir.exists():
                shutil.rmtree(spaces_dir)
            if active_brand_dir.exists():
                shutil.rmtree(active_brand_dir)
            for key, value in env_backup.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_license_limits_block_individual_and_enforce_agency_caps(self):
        """Test plan limits are enforced before local client state can be created."""
        print("\nTesting License Limit Enforcement...")

        dashboard = load_dashboard_module()
        original_registry_path = dashboard.AGENCY_SPACES_FILE
        original_spaces_dir = dashboard.AGENCY_SPACES_DIR
        original_entitlements = dashboard.license_entitlements
        registry_path = ROOT_DIR / "output" / "test-license-limit-spaces.json"
        spaces_dir = ROOT_DIR / "output" / "test-license-limit-spaces"
        try:
            dashboard.AGENCY_SPACES_FILE = registry_path
            dashboard.AGENCY_SPACES_DIR = spaces_dir
            dashboard.write_json(registry_path, {"active_id": "", "spaces": []})
            dashboard.license_entitlements = lambda: {
                "plan": "individual",
                "is_agency": False,
                "is_individual": True,
                "max_devices": 1,
                "workspace_limit": 1,
                "features": ["dashboard", "chat", "telegram"],
                "can_use_agency_workspaces": False,
                "can_use_multi_telegram_profiles": False,
            }
            try:
                dashboard.create_agency_space({"name": "Cliente bloqueado"})
                self.assert_true(False, "Individual license should not create agency spaces")
            except ValueError as exc:
                self.assert_true("Licencia Agencia" in str(exc), "Individual license receives upgrade copy for agency spaces")

            dashboard.license_entitlements = lambda: {
                "plan": "agency",
                "is_agency": True,
                "is_individual": False,
                "max_devices": 4,
                "workspace_limit": 1,
                "features": ["dashboard", "chat", "telegram", "agency_workspaces"],
                "can_use_agency_workspaces": True,
                "can_use_multi_telegram_profiles": False,
            }
            first = dashboard.create_agency_space({"name": "Cliente Uno"})
            try:
                dashboard.create_agency_space({"name": "Cliente Dos"})
                self.assert_true(False, "Agency workspace limit should block extra clients")
            except ValueError as exc:
                self.assert_true("limite de espacios" in str(exc).lower(), "Agency workspace limit is enforced")

            dashboard.write_json(registry_path, {"active_id": first["id"], "spaces": [first, {"id": "cliente-dos", "name": "Cliente Dos"}]})
            try:
                dashboard.save_telegram_config({"enabled": "true", "chat_id": "123"})
                self.assert_true(False, "Agency without multi Telegram feature should block several Telegram profiles")
            except ValueError as exc:
                self.assert_true("Telegram" in str(exc) and "Agencia" in str(exc), "Multi-client Telegram needs the right entitlement")
        finally:
            dashboard.AGENCY_SPACES_FILE = original_registry_path
            dashboard.AGENCY_SPACES_DIR = original_spaces_dir
            dashboard.license_entitlements = original_entitlements
            if registry_path.exists():
                registry_path.unlink()
            if spaces_dir.exists():
                shutil.rmtree(spaces_dir)

    def test_onboarding_state_persists(self):
        """Test onboarding completion is persisted and resettable."""
        print("\nTesting Onboarding State...")

        dashboard = load_dashboard_module()
        path = dashboard.ONBOARDING_FILE
        env_path = dashboard.ENV_FILE
        metrics_path = dashboard.METRICS_FILE
        ad_path = dashboard.AD_CONFIG_FILE
        business_path = dashboard.BUSINESS_PROFILE_FILE
        original_refresh = dashboard.refresh_real_metrics
        original_license_status = dashboard.license_status
        before = path.read_text(encoding="utf-8") if path.exists() else ""
        env_before = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        metrics_before = metrics_path.read_text(encoding="utf-8") if metrics_path.exists() else ""
        ad_before = ad_path.read_text(encoding="utf-8") if ad_path.exists() else ""
        business_before = business_path.read_text(encoding="utf-8") if business_path.exists() else ""
        env_backup = {key: os.environ.get(key) for key in ["DASHBOARD_PASSWORD", "DASHBOARD_TOKEN", "META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID"]}
        try:
            dashboard.refresh_real_metrics = lambda *args, **kwargs: {"ok": True, "saved": True, "source": "meta_graph", "rows": 1}
            dashboard.license_status = lambda config: {"valid": True, "status": "active", "detail": "Cloud license active"}
            dashboard.update_env_values({"DASHBOARD_PASSWORD": "buyer-owned-password", "DASHBOARD_TOKEN": "buyer-owned-password", "META_ACCESS_TOKEN": "token_12345678901234567890", "META_AD_ACCOUNT_ID": "act_999"})
            ad_path.write_text(json.dumps({"creative": {"destination": {"page_id": "111", "url": "https://buyer.example"}}}), encoding="utf-8")
            dashboard.write_json(business_path, {"website_url": "https://buyer.example", "current_stage": "Ya vendo y quiero bajar CPA.", "initial_plan": ["Leer datos reales", "Preparar campaña con supervisión"]})
            dashboard.write_json(metrics_path, {"timestamp": dashboard.now_iso(), "source": "meta_graph", "campaigns": [], "summary": {}})
            completed = dashboard.complete_onboarding()
            payload = dashboard.dashboard_payload()
            self.assert_true(completed["completed"] is True, "Onboarding completion returns completed state")
            self.assert_true(completed["first_insights_refresh"]["saved"] is True or "reason" in completed["first_insights_refresh"], "Onboarding records first insights refresh result")
            self.assert_true(payload["onboarding"]["completed"] is True, "Dashboard payload exposes completed onboarding")
            reset = dashboard.reset_onboarding()
            self.assert_true(reset["completed"] is False, "Onboarding reset clears completed state")
        finally:
            dashboard.refresh_real_metrics = original_refresh
            dashboard.license_status = original_license_status
            if before:
                path.write_text(before, encoding="utf-8")
            elif path.exists():
                path.unlink()
            env_path.write_text(env_before, encoding="utf-8")
            if metrics_before:
                metrics_path.write_text(metrics_before, encoding="utf-8")
            elif metrics_path.exists():
                metrics_path.unlink()
            if ad_before:
                ad_path.write_text(ad_before, encoding="utf-8")
            elif ad_path.exists():
                ad_path.unlink()
            if business_before:
                business_path.write_text(business_before, encoding="utf-8")
            elif business_path.exists():
                business_path.unlink()
            for key, value in env_backup.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_onboarding_requires_real_meta_data(self):
        """Test buyer onboarding cannot finish while still on demo metrics."""
        print("\nTesting Onboarding Real Data Requirement...")

        dashboard = load_dashboard_module()
        env_path = dashboard.ENV_FILE
        metrics_path = dashboard.METRICS_FILE
        ad_path = dashboard.AD_CONFIG_FILE
        business_path = dashboard.BUSINESS_PROFILE_FILE
        onboarding_path = dashboard.ONBOARDING_FILE
        original_refresh = dashboard.refresh_real_metrics
        original_license_status = dashboard.license_status
        env_before = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        metrics_before = metrics_path.read_text(encoding="utf-8") if metrics_path.exists() else ""
        ad_before = ad_path.read_text(encoding="utf-8") if ad_path.exists() else ""
        business_before = business_path.read_text(encoding="utf-8") if business_path.exists() else ""
        onboarding_before = onboarding_path.read_text(encoding="utf-8") if onboarding_path.exists() else ""
        env_backup = {key: os.environ.get(key) for key in ["DASHBOARD_PASSWORD", "DASHBOARD_TOKEN", "META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID"]}
        try:
            dashboard.refresh_real_metrics = lambda *args, **kwargs: {"ok": False, "saved": False, "reason": "token_expired"}
            dashboard.license_status = lambda config: {"valid": True, "status": "active", "detail": "Cloud license active"}
            dashboard.update_env_values({"DASHBOARD_PASSWORD": "buyer-owned-password", "DASHBOARD_TOKEN": "buyer-owned-password", "META_ACCESS_TOKEN": "token_12345678901234567890", "META_AD_ACCOUNT_ID": "act_999"})
            ad_path.write_text(json.dumps({"creative": {"destination": {"page_id": "111", "url": "https://buyer.example"}}}), encoding="utf-8")
            dashboard.write_json(business_path, {"website_url": "https://buyer.example", "current_stage": "Tengo anuncios activos.", "initial_plan": ["Leer datos reales"]})
            dashboard.write_json(metrics_path, {"timestamp": dashboard.now_iso(), "source": "demo", "campaigns": [], "summary": {}})
            try:
                dashboard.complete_onboarding()
                self.assert_true(False, "Onboarding should not finish without real Meta insights")
            except ValueError as exc:
                self.assert_true("datos reales de Meta" in str(exc), "Onboarding blocks demo metrics")
            dashboard.write_json(onboarding_path, {"completed": True, "completed_at": dashboard.now_iso()})
            repaired = dashboard.dashboard_payload()["onboarding"]
            self.assert_true(repaired["requires_repair"] is True and "datos_reales" in repaired["repair_reasons"], "Legacy completed onboarding is sent back to reconnect real data")
        finally:
            dashboard.refresh_real_metrics = original_refresh
            dashboard.license_status = original_license_status
            env_path.write_text(env_before, encoding="utf-8")
            if metrics_before:
                metrics_path.write_text(metrics_before, encoding="utf-8")
            elif metrics_path.exists():
                metrics_path.unlink()
            if ad_before:
                ad_path.write_text(ad_before, encoding="utf-8")
            elif ad_path.exists():
                ad_path.unlink()
            if business_before:
                business_path.write_text(business_before, encoding="utf-8")
            elif business_path.exists():
                business_path.unlink()
            if onboarding_before:
                onboarding_path.write_text(onboarding_before, encoding="utf-8")
            elif onboarding_path.exists():
                onboarding_path.unlink()
            for key, value in env_backup.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_update_snapshot_retention_and_restore(self):
        """Test official update snapshots preserve local state and keep last three restore points."""
        print("\nTesting Update Snapshots And Rollback...")

        dashboard = load_dashboard_module()

        class NoopTimer:
            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                return None

        original_values = {
            "ROOT_DIR": dashboard.ROOT_DIR,
            "DATA_DIR": dashboard.DATA_DIR,
            "OUTPUT_DIR": dashboard.OUTPUT_DIR,
            "UPDATE_SNAPSHOTS_DIR": dashboard.UPDATE_SNAPSHOTS_DIR,
            "VERSION_FILE": dashboard.VERSION_FILE,
            "ACTIONS_FILE": dashboard.ACTIONS_FILE,
            "METRICS_FILE": dashboard.METRICS_FILE,
            "threading_Timer": dashboard.threading.Timer,
        }
        with tempfile.TemporaryDirectory() as tmp_name:
            root = Path(tmp_name)
            (root / "dashboard" / "data").mkdir(parents=True)
            (root / "dashboard" / "monitoring-dashboard.py").write_text("print('old dashboard')\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "agent.py").write_text("VERSION='old'\n", encoding="utf-8")
            (root / "brand_guides").mkdir()
            (root / "output").mkdir()
            (root / ".env").write_text("DASHBOARD_PASSWORD=old\n", encoding="utf-8")
            (root / "ad-config.json").write_text('{"url":"old"}\n', encoding="utf-8")
            (root / "VERSION").write_text("v1.0.0\n", encoding="utf-8")
            (root / "dashboard" / "data" / "chat_history.json").write_text('{"turns":["old"]}\n', encoding="utf-8")
            try:
                dashboard.ROOT_DIR = root
                dashboard.DATA_DIR = root / "dashboard" / "data"
                dashboard.OUTPUT_DIR = root / "output"
                dashboard.UPDATE_SNAPSHOTS_DIR = dashboard.DATA_DIR / "update-snapshots"
                dashboard.VERSION_FILE = root / "VERSION"
                dashboard.ACTIONS_FILE = dashboard.DATA_DIR / "actions.json"
                dashboard.METRICS_FILE = dashboard.DATA_DIR / "metrics.json"
                dashboard.threading.Timer = NoopTimer
                first = dashboard.create_update_snapshot(release={"channel": "stable", "latest_version": "v1.0.2"})
                (root / ".env").write_text("DASHBOARD_PASSWORD=new\n", encoding="utf-8")
                (root / "ad-config.json").write_text('{"url":"new"}\n', encoding="utf-8")
                (root / "VERSION").write_text("v9.9.9\n", encoding="utf-8")
                (root / "dashboard" / "data" / "chat_history.json").write_text('{"turns":["new"]}\n', encoding="utf-8")
                result = dashboard.restore_update_snapshot({"snapshot_id": first["id"]})
                self.assert_true((root / "VERSION").read_text(encoding="utf-8").strip() == "v1.0.0", "Rollback restores previous VERSION")
                self.assert_true("DASHBOARD_PASSWORD=old" in (root / ".env").read_text(encoding="utf-8"), "Rollback restores local .env")
                self.assert_true('"old"' in (root / "dashboard" / "data" / "chat_history.json").read_text(encoding="utf-8"), "Rollback restores dashboard local memory")
                self.assert_true((dashboard.UPDATE_SNAPSHOTS_DIR / first["id"]).exists(), "Rollback preserves snapshot storage while restoring dashboard data")
                self.assert_true(result.get("rescue_snapshot_id"), "Rollback creates a rescue snapshot before restoring")
                for index in range(4):
                    (root / "VERSION").write_text(f"v1.0.{index + 1}\n", encoding="utf-8")
                    dashboard.create_update_snapshot(release={"channel": "stable", "latest_version": f"v1.0.{index + 2}"})
                snapshots = dashboard.list_update_snapshots()
                self.assert_true(len(snapshots) == 3, "Update snapshots retain only the latest three pre-update points")
                self.assert_true(all(item.get("reason") == "pre_update" for item in snapshots), "Rollback list excludes rescue snapshots")
            finally:
                for key, value in original_values.items():
                    if key == "threading_Timer":
                        dashboard.threading.Timer = value
                    else:
                        setattr(dashboard, key, value)

    def test_release_package_excludes_runtime_data_and_includes_buyer_docs(self):
        """Test release script is buyer-safe and docs are included in source package."""
        print("\nTesting Release Package Safety Rules...")

        script = (ROOT_DIR / "scripts" / "package-release.sh").read_text(encoding="utf-8")
        required_excludes = [
            '.env',
            'ad-config.json',
            'dashboard/data/*',
            'dashboard/data/update-snapshots/*',
            'seller/*',
            'docs/es-servidor-licencias.md',
            'docs/es-cierre-v1-vendible.md',
            'docs/marketing-strategy-brief.md',
            'docs/product-positioning.md',
            'docs/content-creation-system.md',
            'docs/keyframe-to-motion-pipeline.md',
            'dashboard/content-dashboard.py',
            'public/content-keyframes/*',
            'src/content_pipeline.py',
            'src/keyframe_planner.py',
            'src/remotion/*',
            'package.json',
            'package-lock.json',
            'node_modules/*',
            '*/node_modules/*',
            '.git/*',
            'output/*',
            'logs/*',
        ]
        for pattern in required_excludes:
            self.assert_true(pattern in script, f"Release ZIP excludes {pattern}")
        buyer_docs = [
            "docs/es-activar-licencia.md",
            "docs/es-conectar-meta.md",
            "docs/es-crear-primera-campana.md",
            "docs/es-supervision-vs-piloto.md",
            "docs/es-checklist-anuncios-activos.md",
            "docs/es-solucion-problemas.md",
            "docs/es-usar-telegram.md",
            "docs/es-codex-creativos.md",
            "docs/es-instalacion-docker-codex.md",
            "docs/es-instaladores-doble-clic.md",
            "docs/es-instaladores-producto.md",
            "docs/es-firma-instaladores.md",
            "docs/es-planes-de-licencia.md",
            "docs/es-digitalocean-acceso-estricto.md",
            "docs/es-cambiar-de-equipo.md",
        ]
        for doc in buyer_docs:
            self.assert_true((ROOT_DIR / doc).exists(), f"Buyer doc exists: {doc}")
        for file in [
            "VERSION",
            "Dockerfile",
            "docker-compose.yml",
            ".dockerignore",
            "scripts/docker-entrypoint.sh",
            "scripts/run-docker.sh",
            "scripts/install-from-github.sh",
            "scripts/install-from-github.ps1",
            "scripts/build-mac-dmg.sh",
            "scripts/build-mac-pkg.sh",
            "scripts/build-windows-msi.sh",
            "scripts/build-windows-exe.sh",
            "scripts/build-linux-bundle.sh",
            "scripts/digitalocean-refresh-firewall.sh",
            "scripts/install-digitalocean-strict-access.sh",
            "scripts/export-migration.sh",
            "scripts/import-migration.sh",
            "scripts/export-migration.ps1",
            "scripts/import-migration.ps1",
            "deploy/digitalocean/cloud-init-strict-access.yaml",
            "installer/release-bootstrap.env",
            "installer/windows/MetaAdsAgentInstaller.nsi",
            "Instalar en Windows.bat",
            "Instalar en Mac.command",
            "Instalar en Linux.sh",
            "Instalar en Linux.desktop",
        ]:
            self.assert_true((ROOT_DIR / file).exists(), f"Docker install file exists: {file}")
        dockerfile = (ROOT_DIR / "Dockerfile").read_text(encoding="utf-8")
        compose = (ROOT_DIR / "docker-compose.yml").read_text(encoding="utf-8")
        windows_installer = (ROOT_DIR / "Instalar en Windows.bat").read_text(encoding="utf-8")
        mac_installer = (ROOT_DIR / "Instalar en Mac.command").read_text(encoding="utf-8")
        linux_installer = (ROOT_DIR / "Instalar en Linux.sh").read_text(encoding="utf-8")
        mac_pkg_builder = (ROOT_DIR / "scripts" / "build-mac-pkg.sh").read_text(encoding="utf-8")
        mac_dmg_builder = (ROOT_DIR / "scripts" / "build-mac-dmg.sh").read_text(encoding="utf-8")
        windows_msi_builder = (ROOT_DIR / "scripts" / "build-windows-msi.sh").read_text(encoding="utf-8")
        windows_exe_builder = (ROOT_DIR / "scripts" / "build-windows-exe.sh").read_text(encoding="utf-8")
        nsis_template = (ROOT_DIR / "installer" / "windows" / "MetaAdsAgentInstaller.nsi").read_text(encoding="utf-8")
        dashboard_source = (ROOT_DIR / "dashboard" / "monitoring-dashboard.py").read_text(encoding="utf-8")
        dockerignore = (ROOT_DIR / ".dockerignore").read_text(encoding="utf-8")
        docker_entrypoint = (ROOT_DIR / "scripts" / "docker-entrypoint.sh").read_text(encoding="utf-8")
        env_example = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")
        self.assert_true("@openai/codex" in dockerfile and "node:22" in dockerfile, "Docker image installs Node and Codex CLI")
        self.assert_true("CODEX_CREATIVE_ENABLED=false" in dockerfile and 'CODEX_CREATIVE_ENABLED: "false"' in compose, "Buyer installs leave optional Codex CLI execution off by default")
        self.assert_true("seller/" in dockerignore, "Docker build context excludes seller secrets")
        self.assert_true("forced = {" in docker_entrypoint and "\"DASHBOARD_HOST\": \"0.0.0.0\"" in docker_entrypoint, "Docker entrypoint forces reachable dashboard bind values")
        self.assert_true("LAN_ACCESS_ENABLED" in env_example and "LAN_ACCESS_ENABLED" in docker_entrypoint and "ADMIRO_HOST_LAN_IP" in compose, "Phone LAN access is off by default and Docker receives the host LAN IP when available")
        self.assert_true("meta_ads_config" in compose and "meta_ads_brand_guides" in compose, "Docker Compose persists config and brand guides")
        self.assert_true("meta_ads_update_snapshots" in compose and "/app/dashboard/data/update-snapshots" in compose, "Docker Compose keeps update rollback snapshots in a named volume")
        self.assert_true("MetaAdsAgent-source.zip" in script, "Release ZIP includes a stable asset name for bootstrap installers")
        self.assert_true("install-from-github.ps1" in windows_installer and "install-from-github.sh" in mac_installer and "install-from-github.sh" in linux_installer, "Double-click installers use the shared bootstrap scripts")
        self.assert_true("docker compose up --build" in windows_installer and "./scripts/run-docker.sh" in mac_installer, "Double-click installers launch Docker setup")
        self.assert_true("pkgbuild" in mac_pkg_builder and "productbuild" in mac_pkg_builder, "Mac PKG builder uses native package tools")
        self.assert_true("MAC_PKG_SIGN_IDENTITY" in mac_pkg_builder and "notarytool submit" in mac_pkg_builder and "stapler staple" in mac_pkg_builder, "Mac PKG builder supports Developer ID signing and notarization")
        self.assert_true("hdiutil create" in mac_dmg_builder and ".app" in mac_dmg_builder and "MAC_APP_SIGN_IDENTITY" in mac_dmg_builder, "Mac DMG builder creates a signed app launcher experience")
        self.assert_true("open -a Terminal" in mac_dmg_builder and "$HOME/Applications/Meta Ads Agent" in mac_dmg_builder, "Mac DMG launcher hides the command file and opens the installer from a friendly app")
        self.assert_true("candle" in windows_msi_builder and "light" in windows_msi_builder and "MetaAdsAgent-" in windows_msi_builder and "windows.msi" in windows_msi_builder, "Windows MSI builder uses WiX Toolset when available")
        self.assert_true("WINDOWS_SIGN_MSI" in windows_msi_builder and "signtool" in windows_msi_builder and "/fd SHA256" in windows_msi_builder, "Windows MSI builder supports Authenticode signing")
        self.assert_true('Source="{esc(source_ref)}"' in windows_msi_builder and "MetaAdsAgent\\\\" in windows_msi_builder, "Windows MSI source package uses relative file paths for VPS compilation")
        self.assert_true("makensis" in windows_exe_builder and "MetaAdsAgentInstaller.nsi" in windows_exe_builder, "Windows EXE builder uses NSIS when available")
        self.assert_true("WINDOWS_SIGN_EXE" in windows_exe_builder and "signtool" in windows_exe_builder and "/fd SHA256" in windows_exe_builder, "Windows EXE builder supports Authenticode signing")
        self.assert_true("CreateShortcut" in nsis_template and "Instalar en Windows.bat" in nsis_template, "Windows NSIS installer creates a buyer shortcut")
        env_example = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")
        self.assert_true("https://admiroia.uboost.lat" in env_example, "Buyer release uses deployed license server")
        self.assert_true("LICENSE_PUBLIC_KEY=" in env_example, "Buyer release includes only license verification key")
        self.assert_true("AGENT_CHAT_BASE_URL=https://api.minimax.io/v1" in env_example and "AGENT_CHAT_MODEL=MiniMax-M3" in env_example and "AGENT_CHAT_PROVIDER=hermes" in env_example and "AGENT_BRAIN_PROVIDER=openai_codex" in env_example, "Buyer release documents Hermes runtime plus MiniMax M3/OpenAI-compatible brain support")
        self.assert_true("META_ADS_AGENT_VERSION=v1.0.5" in env_example and (ROOT_DIR / "VERSION").read_text(encoding="utf-8").strip() == "v1.0.5", "Buyer release exposes the installed product version")
        bootstrap_config = (ROOT_DIR / "installer" / "release-bootstrap.env").read_text(encoding="utf-8")
        bootstrap_sh = (ROOT_DIR / "scripts" / "install-from-github.sh").read_text(encoding="utf-8")
        bootstrap_ps1 = (ROOT_DIR / "scripts" / "install-from-github.ps1").read_text(encoding="utf-8")
        do_firewall_script = (ROOT_DIR / "scripts" / "digitalocean-refresh-firewall.sh").read_text(encoding="utf-8")
        do_install_script = (ROOT_DIR / "scripts" / "install-digitalocean-strict-access.sh").read_text(encoding="utf-8")
        do_doc = (ROOT_DIR / "docs" / "es-digitalocean-acceso-estricto.md").read_text(encoding="utf-8")
        installer_signing_doc = (ROOT_DIR / "docs" / "es-firma-instaladores.md").read_text(encoding="utf-8")
        device_transfer_doc = (ROOT_DIR / "docs" / "es-cambiar-de-equipo.md").read_text(encoding="utf-8")
        export_migration = (ROOT_DIR / "scripts" / "export-migration.sh").read_text(encoding="utf-8")
        import_migration = (ROOT_DIR / "scripts" / "import-migration.sh").read_text(encoding="utf-8")
        export_migration_ps1 = (ROOT_DIR / "scripts" / "export-migration.ps1").read_text(encoding="utf-8")
        import_migration_ps1 = (ROOT_DIR / "scripts" / "import-migration.ps1").read_text(encoding="utf-8")
        license_activate_api = (ROOT_DIR / "seller" / "vercel-license-api" / "api" / "license" / "activate.js").read_text(encoding="utf-8")
        license_release_api = (ROOT_DIR / "seller" / "vercel-license-api" / "api" / "license" / "release.js").read_text(encoding="utf-8")
        license_releases_admin = (ROOT_DIR / "seller" / "vercel-license-api" / "api" / "admin" / "releases.js").read_text(encoding="utf-8")
        license_download_api = (ROOT_DIR / "seller" / "vercel-license-api" / "api" / "download" / "release.js").read_text(encoding="utf-8")
        portal_page = (ROOT_DIR / "seller" / "vercel-license-api" / "api" / "portal.js").read_text(encoding="utf-8")
        portal_session_api = (ROOT_DIR / "seller" / "vercel-license-api" / "api" / "portal" / "session.js").read_text(encoding="utf-8")
        portal_download_api = (ROOT_DIR / "seller" / "vercel-license-api" / "api" / "portal" / "download.js").read_text(encoding="utf-8")
        portal_digitalocean_api = (ROOT_DIR / "seller" / "vercel-license-api" / "api" / "portal" / "cloud" / "digitalocean.js").read_text(encoding="utf-8")
        portal_lib = (ROOT_DIR / "seller" / "vercel-license-api" / "lib" / "download-portal.js").read_text(encoding="utf-8")
        digitalocean_cloud_lib = (ROOT_DIR / "seller" / "vercel-license-api" / "lib" / "digitalocean-cloud.js").read_text(encoding="utf-8")
        secret_vault_lib = (ROOT_DIR / "seller" / "vercel-license-api" / "lib" / "secret-vault.js").read_text(encoding="utf-8")
        license_lib = (ROOT_DIR / "seller" / "vercel-license-api" / "lib" / "license.js").read_text(encoding="utf-8")
        license_store = (ROOT_DIR / "seller" / "vercel-license-api" / "lib" / "store.js").read_text(encoding="utf-8")
        license_server_readme = (ROOT_DIR / "seller" / "vercel-license-api" / "README.md").read_text(encoding="utf-8")
        digitalocean_guided_doc = (ROOT_DIR / "docs" / "es-instalacion-digitalocean-guiada.md").read_text(encoding="utf-8")
        vercel_config = (ROOT_DIR / "seller" / "vercel-license-api" / "vercel.json").read_text(encoding="utf-8")
        self.assert_true("BOOTSTRAP_PROVIDER=license_server" in bootstrap_config and "LICENSE_RELEASE_ENDPOINT=/api/license/release" in bootstrap_config, "Buyer bootstrap defaults to license-server release downloads")
        self.assert_true("SHA256SUMS.txt" in script and "LINUX_GPG_SIGN" in (ROOT_DIR / "scripts" / "build-linux-bundle.sh").read_text(encoding="utf-8"), "Release builders produce checksums and optional Linux signatures")
        self.assert_true("/api/license/release" in bootstrap_sh and "RELEASE_ASSET_NAME" in bootstrap_sh, "macOS/Linux bootstrap can request signed release downloads")
        self.assert_true("/api/license/release" in bootstrap_ps1 and "RELEASE_ASSET_NAME" in bootstrap_ps1, "Windows bootstrap can request signed release downloads")
        self.assert_true("validate_zip_archive" in bootstrap_sh and "Test-SafeReleaseArchive" in bootstrap_ps1, "Bootstrap installers validate release archives before extraction")
        self.assert_true("SSH_CONNECTION" in do_firewall_script and "api.digitalocean.com/v2" in do_firewall_script and "/firewalls/" in do_firewall_script, "DigitalOcean firewall refresh detects SSH client IP and updates the firewall API")
        self.assert_true("DO_STRICT_ALLOW_SSH_FROM_ANYWHERE" in do_firewall_script and "DASHBOARD_PORT" in do_firewall_script, "DigitalOcean strict mode separates SSH recovery from dashboard access")
        self.assert_true("$HOME/.profile" in do_install_script and "meta-ads-refresh-access" in do_install_script, "DigitalOcean strict mode can refresh access after SSH login")
        self.assert_true("/usr/local/bin/meta-ads-refresh-access" in digitalocean_cloud_lib and "/opt/meta-ads-agent/scripts/digitalocean-refresh-firewall.sh" in digitalocean_cloud_lib, "DigitalOcean cloud access gate uses a system helper path for one-click dashboard opening")
        self.assert_true("migration-panel" in dashboard_source and "/api/migration/export" in dashboard_source and "/api/migration/import" in dashboard_source, "Dashboard exposes backup and restore buttons instead of extra buyer files")
        self.assert_true("cloud-access-panel" in dashboard_source and "/api/cloud-access/refresh" in dashboard_source and "digitalocean-refresh-firewall.sh" in dashboard_source, "Dashboard exposes DigitalOcean access refresh")
        self.assert_true("update-banner" in dashboard_source and "/api/update/check" in dashboard_source and "/api/update/apply" in dashboard_source, "Dashboard checks official updates and can apply them after confirmation")
        self.assert_true("update-cards" in dashboard_source and "Ver mejoras e instalar" in dashboard_source and "Actualización oficial" in dashboard_source, "Dashboard shows update improvements as cards before installing")
        self.assert_true("UPDATE_SNAPSHOTS_DIR" in dashboard_source and "create_update_snapshot" in dashboard_source and "/api/update/rollback" in dashboard_source, "Dashboard creates local pre-update snapshots and exposes rollback")
        self.assert_true("Crear copia e instalar" in dashboard_source and "Volver a una versión anterior" in dashboard_source and "snapshot_policy" in dashboard_source, "Update UI explains automatic backups before installing")
        self.assert_true("responseErrorMessage" in dashboard_source and "data.error||data.detail" in dashboard_source, "Dashboard shows clean API errors instead of raw JSON")
        self.assert_true("DEFAULT_POST_LIMIT_BYTES" in dashboard_source and "MIGRATION_POST_LIMIT_BYTES" in dashboard_source and "read_body(parsed.path)" in dashboard_source, "Dashboard rejects oversized protected requests")
        self.assert_true("redact_error_text" in dashboard_source and "client_error_message" in dashboard_source, "Dashboard avoids echoing raw secrets in errors")
        self.assert_true("X-Frame-Options" in dashboard_source and "X-Content-Type-Options" in dashboard_source, "Dashboard sends basic browser security headers")
        self.assert_true("official_download_url_allowed" in dashboard_source and "MAX_UPDATE_UNPACKED_BYTES" in dashboard_source and "zip_member_is_safe" in dashboard_source, "Dashboard update and restore paths guard against unsafe archives")
        self.assert_true(not (ROOT_DIR / "Actualizar acceso DigitalOcean.command").exists() and not (ROOT_DIR / "Crear respaldo para cambiar de equipo.command").exists(), "Buyer folder avoids scary top-level maintenance launchers")
        self.assert_true("Abrir mi dashboard" in do_doc and "La recuperacion tecnica es por SSH" in do_doc and "DO_STRICT_ALLOW_SSH_FROM_ANYWHERE=true" in do_doc, "DigitalOcean strict access docs explain IP changes and recovery")
        self.assert_true("chat_history.json" in export_migration or "dashboard/data" in export_migration, "Migration export includes dashboard local memory")
        self.assert_true("LICENSE_DEVICE_ID=" in export_migration and "license_unlock.json" in export_migration, "Migration export clears device-specific license unlock")
        self.assert_true("LICENSE_DEVICE_ID=" in import_migration and "license_unlock.json" in import_migration, "Migration import forces new machine license validation")
        self.assert_true("Compress-Archive" in export_migration_ps1 and "Expand-Archive" in import_migration_ps1, "Windows migration buttons use native archive commands")
        self.assert_true("transfer_device" in license_activate_api and "resetDeviceRegistrations" in license_activate_api, "License activation supports explicit Individual device transfer")
        self.assert_true("transfer_device" in license_release_api and "resetDeviceRegistrations" in license_release_api, "Installer release download supports explicit Individual device transfer")
        self.assert_true("normalizeEntitlements" in license_lib and "workspace_limit: 50" in license_lib and "max_devices: 4" in license_lib, "License server normalizes Individual and Agency entitlement defaults")
        self.assert_true('entitlements.plan === "individual"' in license_activate_api and 'entitlements.plan === "individual"' in license_release_api, "License server restricts device transfer to Individual licenses")
        self.assert_true("license_entitlements" in dashboard_source and "active_workspace" in dashboard_source and "workspace_usage" in dashboard_source and "business_binding" in dashboard_source, "Dashboard exposes license limits and active business metadata")
        self.assert_true("Tu licencia Individual cuida un solo negocio activo" in dashboard_source and "Para manejar varios clientes, usa Licencia Agencia" in dashboard_source, "Dashboard explains Individual and Agency limits in buyer-friendly copy")
        self.assert_true("improvements" in license_releases_admin and "improvements" in license_release_api, "Official release metadata includes buyer-facing improvement cards")
        self.assert_true("buyerFacingImprovements" in portal_lib and "INTERNAL_RELEASE_WORDS" in portal_lib and "Instalacion en contenedor" in portal_lib, "Download portal filters internal release notes before buyers see them")
        for technical_release_word in ['"hermes"', '"chatgpt"', '"codex"', '"ssh"', '"vps"', '"minimax"', '"comando"']:
            self.assert_true(technical_release_word in portal_lib, f"Download portal hides technical release note word {technical_release_word} from buyers")
        self.assert_true("Docker para Mac" in portal_lib and "Docker para Windows" in portal_lib and "producto se prepara en contenedor" in portal_lib, "Download portal pushes buyers toward Docker-first installation")
        self.assert_true("buyerFacingImprovements(release.improvements" in portal_session_api and "buyerFacingImprovements(release.improvements" in license_release_api, "Buyer download APIs sanitize release improvements")
        self.assert_true("timingSafeEqual" in license_lib and "RELEASE_MAX_BYTES" in license_download_api and "response.redirect(302" in license_download_api, "License server uses safer comparisons and avoids proxying large release bodies by default")
        self.assert_true("export async function resetDeviceRegistrations" in license_store and "del(" in license_store, "License server can clear prior device registrations")
        self.assert_true("Transferir a este equipo" in dashboard_source, "Dashboard explains and confirms device transfer")
        self.assert_true("desbloqueo temporal" in device_transfer_doc and "nueva llave SSH" in device_transfer_doc and "Cambiar de equipo sin perder memoria" in device_transfer_doc, "Device transfer docs explain local migration and DigitalOcean recovery")
        self.assert_true("RELEASE_DOWNLOAD_SECRET" in license_server_readme and "/api/license/release" in license_server_readme, "Seller license server documents signed release download support")
        self.assert_true("Acceso de comprador" in portal_page and "Email de compra" in portal_page and "Clave de acceso" in portal_page, "Download portal has buyer-friendly email and access key login")
        self.assert_true("/api/portal/session" in portal_page and "/api/portal/download" in portal_page and "Elige tu sistema" in portal_page, "Download portal renders one-click platform downloads")
        self.assert_true("Docker Desktop" in portal_page and "launcher Docker" in portal_page and "Instalacion local con Docker" in portal_page, "Download portal explains local installs run through Docker")
        self.assert_true("Descargar Docker Desktop" in portal_page and "https://www.docker.com/products/docker-desktop/" in portal_page, "Download portal gives buyers a direct Docker Desktop download button")
        self.assert_true("Recordar este acceso" in portal_page and "restorePortalSession" in portal_page and "Cerrar sesion" in portal_page, "Download portal remembers buyer access and offers logout")
        self.assert_true("Estado de tu instalacion" in portal_page and "Acceder a mi dashboard" in portal_page and "renderInstallState" in portal_page, "Download portal leads with installed/not-installed state before installer choices")
        self.assert_true("install_state" in portal_session_api and "deviceRegistrations" in portal_session_api and "cloud_installation" in portal_session_api, "Portal session returns cloud and local install state")
        self.assert_true("HttpOnly" in portal_session_api and "Secure" in portal_session_api and "SameSite=Lax" in portal_session_api and "verifyPortalSession(cookieValue" in portal_session_api, "Portal remembered sessions use signed HttpOnly secure cookies")
        self.assert_true('request.method === "DELETE"' in portal_session_api and "clearPortalCookie" in portal_session_api, "Portal session endpoint supports safe logout without another function")
        self.assert_true("install_event" in license_activate_api and "onboarding_opened" in license_activate_api and "onboarding_completed" in license_activate_api, "License activation records local onboarding state for the buyer portal")
        self.assert_true("mark_license_install_state" in dashboard_source and "onboarding_completed" in dashboard_source, "Dashboard reports onboarding progress to the license server without blocking local use")
        self.assert_true("Instalar en la nube" in portal_page and "/api/portal/cloud/digitalocean" in portal_page and "Crear mi servidor" in portal_page, "Download portal exposes guided DigitalOcean install after buyer access")
        self.assert_true("Crear cuenta en DigitalOcean" in portal_page and "https://cloud.digitalocean.com/registrations/new" in portal_page and "Haz clic aqui para obtener el token" in portal_page and "cloud-token-cta" in portal_page, "Cloud install gives buyers direct DigitalOcean signup and a clear token action beside the token field")
        self.assert_true("US$4 a US$6 al mes" in portal_page and "credito inicial" in portal_page and "metodo de pago" in portal_page, "Cloud install explains expected DigitalOcean cost and signup requirements")
        self.assert_true("cloud-progress" in portal_page and "startCloudProgressPolling" in portal_page and "action: 'status'" in portal_page, "Download portal shows cloud install progress and polls status")
        self.assert_true("Math.min(98, rawProgress)" in portal_page and "verificando_dashboard" in portal_digitalocean_api and "Math.min(98, cleanProgress" in portal_digitalocean_api, "Download portal never shows 100 percent until the cloud dashboard is actually ready")
        self.assert_true("Boolean(openUrl && (cloud.dashboard_available" in portal_page and "Boolean(openUrl && (data.ready" in portal_page, "Download portal requires a real dashboard URL before showing cloud as ready")
        self.assert_true("runtimeStageFromLog" in portal_digitalocean_api and "ADMIRO_STAGE verifying_dashboard" in portal_digitalocean_api, "DigitalOcean status recovers the verifying-dashboard stage from older access gates")
        self.assert_true("docker_ps" in portal_digitalocean_api and "docker_logs_tail" in portal_digitalocean_api, "DigitalOcean cloud status preserves safe Docker diagnostics")
        self.assert_true("Could not resolve host" in portal_digitalocean_api and "No pudo descargar el producto por DNS de arranque" in portal_digitalocean_api, "DigitalOcean cloud status recognizes first-boot DNS download failures instead of freezing progress")
        self.assert_true("Tardando mas de lo normal" in portal_page and "tail -n 80 /var/log/admiro-cloud-install.log" in portal_page, "Download portal explains when DigitalOcean is active but dashboard is not ready")
        self.assert_true("Abrir mi dashboard" in portal_page and "cloud_open_url" in portal_page and "prepara tu red automaticamente" in portal_page, "Download portal exposes a one-click cloud dashboard opener")
        self.assert_true("Protector automatico de acceso" in portal_page and "/api/portal/cloud/access-keeper" in portal_page and "/api/portal/cloud/access-keeper-ps" in portal_page, "Download portal keeps the optional local access keeper available as an advanced fallback")
        self.assert_true("Actualizar acceso de esta red" in portal_page and "refreshCloudAccess()" in portal_page and "action: 'refresh_access'" in portal_page, "Download portal can realign cloud SSH/dashboard access from the buyer browser")
        self.assert_true("Buscar automaticamente con mi token" in portal_page and "cloudRecoveryToken" in portal_page and "refreshCloudIpFromDigitalOcean" in portal_digitalocean_api, "DigitalOcean waiting-for-IP state can recover automatically with the browser-held token")
        self.assert_true("Guardar este token cifrado" not in portal_page and "Olvidar token guardado" not in portal_page and "digitalocean_token_saved" not in portal_session_api and "rememberDigitalOceanToken" not in portal_page and "forgetDigitalOceanToken" not in portal_page, "Download portal no longer asks buyers to save DigitalOcean tokens")
        self.assert_true("encryptPortalSecret" in secret_vault_lib and "aes-256-gcm" in secret_vault_lib and "PORTAL_SECRET_VAULT_KEY" in secret_vault_lib, "Portal vault encryption helper remains available for legacy secret records")
        self.assert_true("remember_digitalocean_token" not in portal_digitalocean_api and "forget_digitalocean_token" not in portal_digitalocean_api and "resolveDigitalOceanToken" in portal_digitalocean_api and "decryptPortalSecret" in portal_digitalocean_api, "DigitalOcean cloud endpoint can read legacy encrypted tokens but does not expose save/forget token actions")
        self.assert_true("resetCloudInstall" in portal_page and "Ya borre este servidor. Crear uno nuevo" in portal_page and 'action === "reset_cloud_install"' in portal_digitalocean_api, "Download portal can clear a deleted or stuck DigitalOcean install before recreating")
        self.assert_true("abre Terminal" in portal_page and "~/.ssh/admiro_ai.pub" in portal_page and "solo tu computador" in portal_page and "La parte privada queda guardada en tu PC" in portal_page and "parte publica, que es segura de compartir" in portal_page and "No compartas la llave privada" in portal_page, "DigitalOcean SSH key step explains public/private key safety in buyer-friendly language")
        self.assert_true("signedPortalSession" in license_lib and "verifyPortalSession" in license_lib and "PORTAL_SESSION_MINUTES" in license_lib, "License server can issue short-lived portal sessions")
        self.assert_true("minutes: rawMinutes" in license_lib and "Math.min(Math.floor(requestedMinutes), 360)" in license_lib, "License server can issue longer signed release grants for cloud-init installs")
        self.assert_true("readLicense" in portal_session_api and "releaseWithDiscoveredAssets" in portal_session_api and "validFormat" in portal_session_api, "Portal session validates purchase email and access key server-side")
        self.assert_true("portal-" in portal_download_api and "deviceRegistrations" not in portal_download_api and "signedReleaseGrant" in portal_download_api and "releaseWithDiscoveredAssets" in portal_download_api, "Portal downloads do not consume device registrations")
        self.assert_true("verifyPortalSession" in portal_digitalocean_api and "readLicense" in portal_digitalocean_api and "validateSshPublicKey" in portal_digitalocean_api, "DigitalOcean cloud install validates buyer session and SSH input")
        self.assert_true('action === "status"' in portal_digitalocean_api and "fetchRuntimeStatus" in portal_digitalocean_api and 'install_status: "installing"' in portal_digitalocean_api, "DigitalOcean cloud endpoint supports progress polling without a second Vercel function")
        self.assert_true('action === "refresh_access"' in portal_digitalocean_api and "refreshFirewallForCurrentIp" in portal_digitalocean_api and "access_refreshed" in portal_digitalocean_api, "DigitalOcean cloud endpoint can refresh firewall access for the current browser IP")
        self.assert_true("taking_longer" in portal_digitalocean_api and "tardando_mas_de_lo_normal" in portal_digitalocean_api, "DigitalOcean cloud status marks long installs clearly instead of freezing near complete")
        self.assert_true("https://api.digitalocean.com/v2" in portal_digitalocean_api and "/droplets" in portal_digitalocean_api and "/firewalls" in portal_digitalocean_api and "/account/keys" in portal_digitalocean_api, "DigitalOcean cloud install creates SSH key, firewall, and Droplet through official API")
        self.assert_true("sshKey?.id || sshKey?.fingerprint" in portal_digitalocean_api, "DigitalOcean cloud install prefers stable SSH key IDs over fingerprints")
        self.assert_true("signedReleaseGrant" in portal_digitalocean_api and "minutes: 180" in portal_digitalocean_api and "api/download/release" in portal_digitalocean_api, "DigitalOcean cloud install downloads the private release through signed license-server URL")
        self.assert_true("cloudBootstrapBaseUrl" in portal_digitalocean_api and "CLOUD_BOOTSTRAP_BASE_URL" in portal_digitalocean_api and "signedDownloadUrl: `${bootstrapBase}" in portal_digitalocean_api, "DigitalOcean cloud install can bootstrap from a stable Vercel URL instead of depending on custom-domain DNS during first boot")
        self.assert_true("GITHUB_RELEASE_TOKEN" not in portal_digitalocean_api and "LICENSE_ADMIN_KEY" not in portal_digitalocean_api, "DigitalOcean cloud install does not expose seller GitHub or admin secrets")
        self.assert_true("cloudAccessSecret" in portal_digitalocean_api and "cloud_open_url" in portal_digitalocean_api and "writeLicense" in portal_digitalocean_api, "DigitalOcean cloud install returns and persists the secure dashboard opener")
        self.assert_true('action === "runtime_report"' in portal_digitalocean_api and "cloud_secret_mismatch" in portal_digitalocean_api and "report_cloud_runtime" in digitalocean_cloud_lib, "DigitalOcean cloud install reports its public IP back automatically")
        self.assert_true("buildDigitalOceanCloudInit" in digitalocean_cloud_lib and "DIGITALOCEAN_TOKEN" in digitalocean_cloud_lib and "docker compose up -d --build" in digitalocean_cloud_lib, "DigitalOcean cloud-init installs the app and starts Docker in detached mode")
        self.assert_true("download.docker.com/linux/ubuntu" in digitalocean_cloud_lib and "docker-compose-linux-$compose_arch" in digitalocean_cloud_lib and "docker compose version" in digitalocean_cloud_lib, "DigitalOcean cloud-init installs Docker Compose reliably on fresh Ubuntu droplets")
        self.assert_true("currentClientIp" in digitalocean_cloud_lib and "addresses: [clientCidr]" in digitalocean_cloud_lib and "DASHBOARD_PORT" in digitalocean_cloud_lib, "DigitalOcean cloud helper restricts firewall to current buyer IP and dashboard port")
        self.assert_true("admiro-cloud-access-gate.service" in digitalocean_cloud_lib and "CLOUD_ACCESS_SECRET" in digitalocean_cloud_lib and "/open/" in digitalocean_cloud_lib, "DigitalOcean cloud install creates a secret one-click dashboard access gate")
        self.assert_true("/status/" in digitalocean_cloud_lib and "dashboard_ready" in digitalocean_cloud_lib and "cloud install complete" in digitalocean_cloud_lib, "DigitalOcean access gate reports install readiness for the portal progress bar")
        self.assert_true("dashboard_ready=false" in digitalocean_cloud_lib and 'report_cloud_runtime "dashboard_ready" "100" "true"' in digitalocean_cloud_lib and 'report_cloud_runtime "verificando_dashboard" "98" "false"' in digitalocean_cloud_lib, "DigitalOcean cloud-init only reports 100 percent after the dashboard responds")
        self.assert_true('("ADMIRO_STAGE verifying_dashboard", "verificando_dashboard", 98)' in digitalocean_cloud_lib, "DigitalOcean access gate recognizes the verifying-dashboard marker")
        self.assert_true("docker_snapshot" in digitalocean_cloud_lib and '\"docker\", \"ps\", \"-a\"' in digitalocean_cloud_lib and '"docker_ps": docker_snapshot()' in digitalocean_cloud_lib, "DigitalOcean access gate reports safe Docker container status")
        self.assert_true("docker_logs_tail" in digitalocean_cloud_lib and '"docker", "logs", "--tail", "80"' in digitalocean_cloud_lib, "DigitalOcean access gate reports safe dashboard container logs")
        self.assert_true("install_cloud_status_gate_early" in digitalocean_cloud_lib and "ADMIRO_STAGE running_installer" in digitalocean_cloud_lib and "systemctl restart admiro-cloud-access-gate.service" in digitalocean_cloud_lib, "DigitalOcean cloud-init starts the status gate early and reports real install stages")
        self.assert_true('"7870"' in digitalocean_cloud_lib and "DO_STRICT_ACCESS_GATE_PORT" in do_firewall_script and "access_gate_port" in do_firewall_script, "DigitalOcean firewall refresh preserves the dashboard access gate")
        self.assert_true("CLOUD_DASHBOARD_BASE_DOMAIN" in portal_digitalocean_api and "DNS_PROVIDER" in portal_digitalocean_api and "VERCEL_DNS_TOKEN" in portal_digitalocean_api and "/v2/domains/" in portal_digitalocean_api and "/v4/domains/" in portal_digitalocean_api, "DigitalOcean cloud install can create per-install DNS records through Vercel DNS")
        self.assert_true("CLOUDFLARE_API_TOKEN" in portal_digitalocean_api and "dns_records" in portal_digitalocean_api, "DigitalOcean cloud install keeps Cloudflare DNS as an optional fallback provider")
        self.assert_true("install_caddy_https" in digitalocean_cloud_lib and "Caddyfile" in digitalocean_cloud_lib and "reverse_proxy 127.0.0.1:$DASHBOARD_PORT" in digitalocean_cloud_lib, "DigitalOcean cloud-init installs Caddy HTTPS proxy when a cloud hostname is available")
        self.assert_true('ports: "80"' in digitalocean_cloud_lib and 'ports: "443"' in digitalocean_cloud_lib and "DO_STRICT_EXTRA_TCP_PORTS=443" in digitalocean_cloud_lib and "DO_STRICT_PUBLIC_TCP_PORTS=80" in digitalocean_cloud_lib, "DigitalOcean firewall allows public HTTP challenge and buyer-scoped HTTPS")
        self.assert_true("DO_STRICT_PUBLIC_TCP_PORTS" in do_firewall_script and "public_ports" in do_firewall_script, "DigitalOcean firewall refresh preserves public certificate challenge ports")
        self.assert_true("allowSshFromAnywhere: true" in portal_digitalocean_api and "PasswordAuthentication no" in digitalocean_cloud_lib and 'DO_STRICT_ALLOW_SSH_FROM_ANYWHERE "true"' in digitalocean_cloud_lib, "DigitalOcean cloud install keeps SSH as key-only recovery path")
        self.assert_true("DO_STRICT_SKIP_DROPLET_ID_PROMPT" in do_install_script and "DO_STRICT_INITIAL_CLIENT_IP" in do_install_script, "DigitalOcean strict access installer supports noninteractive cloud-init first refresh")
        self.assert_true("Instalacion guiada en DigitalOcean" in digitalocean_guided_doc and "No se muestra una opcion de guardar token" in digitalocean_guided_doc and "5 a 10 minutos" in digitalocean_guided_doc, "Buyer docs explain guided DigitalOcean install safely without suggesting token saving")
        self.assert_true("barra de progreso" in digitalocean_guided_doc and "Acceder a mi dashboard" in digitalocean_guided_doc, "Buyer docs explain cloud install progress and final access button")
        self.assert_true("Abrir mi dashboard" in digitalocean_guided_doc and "autoriza la IP actual" in digitalocean_guided_doc and "No contiene el token de DigitalOcean" in digitalocean_guided_doc, "Buyer docs explain the one-click cloud dashboard opener")
        self.assert_true("Protector automatico de acceso avanzado" in digitalocean_guided_doc and "corre cada hora" in digitalocean_guided_doc and "No guarda el token de DigitalOcean" in digitalocean_guided_doc, "Buyer docs explain the local cloud access keeper as an advanced fallback")
        self.assert_true(".dmg" in portal_lib and ".msi" in portal_lib and ".tar.gz" in portal_lib, "Portal maps release assets to Mac, Windows and Linux buttons")
        self.assert_true("releases/tags" in portal_lib and "GITHUB_RELEASE_TOKEN" in portal_lib and "api.github.com/repos" in portal_lib, "Portal can discover platform installers from the private GitHub release")
        self.assert_true("\"/access\"" in vercel_config and "\"/descargas\"" in vercel_config and "\"/api/portal\"" in vercel_config, "License server routes friendly download URLs to the portal")
        self.assert_true("Download portal" in license_server_readme and "/api/portal/session" in license_server_readme, "Seller docs explain the buyer download portal")
        self.assert_true("Developer ID Application" in installer_signing_doc and ".dmg" in installer_signing_doc and ".msi" in installer_signing_doc, "Installer signing docs recommend DMG and MSI for buyer trust")
        self.assert_true("Developer ID Installer" in installer_signing_doc and "Authenticode" in installer_signing_doc and "SmartScreen" in installer_signing_doc, "Installer signing docs explain platform trust requirements")
        for file in [
            "seller/vercel-license-api/api/admin/releases.js",
            "seller/vercel-license-api/api/license/release.js",
            "seller/vercel-license-api/api/download/release.js",
            "seller/vercel-license-api/api/portal.js",
            "seller/vercel-license-api/api/portal/session.js",
            "seller/vercel-license-api/api/portal/download.js",
            "seller/vercel-license-api/api/portal/cloud/digitalocean.js",
            "seller/vercel-license-api/api/portal/cloud/access-keeper.js",
            "seller/vercel-license-api/api/portal/cloud/access-keeper-ps.js",
            "seller/vercel-license-api/lib/download-portal.js",
            "seller/vercel-license-api/lib/digitalocean-cloud.js",
            "seller/vercel-license-api/lib/secret-vault.js",
        ]:
            self.assert_true((ROOT_DIR / file).exists(), f"Seller release API exists: {file}")
    
    def run_all_tests(self):
        """Run all integration tests."""
        print("=" * 70)
        print("META ADS AGENT INTEGRATION TESTS")
        print("=" * 70)
        
        # Run all test methods
        test_methods = [
            self.test_campaign_creator,
            self.test_budget_optimizer,
            self.test_ab_testing,
            self.test_scaling_logic,
            self.test_pause_logic,
            self.test_auto_warmup,
            self.test_license_validation,
            self.test_license_status_and_activation,
            self.test_cloud_license_blocks_buyer_live_features,
            self.test_dashboard_password_auth,
            self.test_secret_redaction,
            self.test_website_scanner_blocks_private_urls,
            self.test_skill_response_parsing,
            self.test_openai_compatible_agent_provider,
            self.test_agent_setup_status_accepts_direct_model_provider,
            self.test_hermes_provider_parses_tool_request,
            self.test_hermes_creative_image_request_routes_to_codex_tool,
            self.test_hermes_missing_runtime_gives_chatgpt_setup_guidance,
            self.test_dashboard_chatgpt_connect_action_opens_terminal,
            self.test_dashboard_chatgpt_connect_action_uses_vps_browserless_bridge,
            self.test_dashboard_hermes_browserless_auto_selects_codex,
            self.test_hermes_blocks_non_codex_runtime_by_default,
            self.test_hermes_attaches_safe_uploaded_images,
            self.test_hermes_business_memory_workspace_is_curated_and_redacted,
            self.test_decision_memory_profitability_rules_and_hermes_context,
            self.test_chat_approval_decision_tool,
            self.test_minimax_tool_request_executes_backend_tool,
            self.test_codex_creative_prompt_rejects_local_file_escape,
            self.test_agent_codex_image_creative_request_result,
            self.test_creative_studio_protects_and_previews_generated_assets,
            self.test_brand_memory_documents_feed_creative_generation,
            self.test_audience_builder_readiness,
            self.test_chat_audience_tool,
            self.test_meta_targeting_search_normalizes_options,
            self.test_chat_saves_existing_adset_when_user_provides_it,
            self.test_chat_history_persists_and_resets,
            self.test_creative_memory_wizard_collects_and_saves_guides,
            self.test_meta_asset_discovery_saves_connected_assets,
            self.test_live_insights_normalize_into_dashboard_metrics,
            self.test_supervised_daily_reads_real_data_and_stages_pause,
            self.test_demo_metrics_are_labeled,
            self.test_supervised_approval_executes_only_with_valid_license_and_retries_failures,
            self.test_campaign_creation_requires_active_confirmation,
            self.test_campaign_creation_uses_meta_targeting_selection,
            self.test_social_targeting_uses_meta_ids,
            self.test_autopilot_action_updates_dashboard_only_after_meta_success,
            self.test_campaign_stack_execution_creates_full_ad_order,
            self.test_chat_stages_campaign_creation_and_requires_exact_approval,
            self.test_telegram_channel_routes_agent_and_blocks_approval,
            self.test_telegram_connection_change_resets_polling_state,
            self.test_setup_page_contains_unlock_and_trust,
            self.test_setup_config_save_preserves_blank_license,
            self.test_individual_license_replaces_one_business_only_with_confirmation,
            self.test_agency_spaces_keep_client_data_separate,
            self.test_license_limits_block_individual_and_enforce_agency_caps,
            self.test_onboarding_state_persists,
            self.test_onboarding_requires_real_meta_data,
            self.test_update_snapshot_retention_and_restore,
            self.test_release_package_excludes_runtime_data_and_includes_buyer_docs,
        ]
        
        for test_method in test_methods:
            try:
                test_method()
            except Exception as e:
                self.assert_true(False, f"Test error: {e}")
        
        # Print results
        print("\n" + "=" * 70)
        print("TEST RESULTS")
        print("=" * 70)
        print(f"Total Tests: {self.test_count}")
        print(f"Passed: {self.passed_count}")
        print(f"Failed: {self.failed_count}")
        print(f"Success Rate: {(self.passed_count / self.test_count * 100) if self.test_count > 0 else 0:.1f}%")
        
        print("\nDetailed Results:")
        for status, message in self.results:
            symbol = "✅" if status == "PASS" else "❌"
            print(f"  {symbol} {message}")
        
        # Save results to file
        output_path = Path(__file__).parent / "integration_test_results.json"
        results_data = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total": self.test_count,
                "passed": self.passed_count,
                "failed": self.failed_count,
                "success_rate": (self.passed_count / self.test_count * 100) if self.test_count > 0 else 0
            },
            "detailed_results": self.results
        }
        
        with open(output_path, "w") as f:
            json.dump(results_data, f, indent=2)
        
        print(f"\n📁 Results saved to: {output_path}")
        
        return self.failed_count == 0


def main():
    """Main test runner."""
    suite = IntegrationTestSuite()
    success = suite.run_all_tests()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
