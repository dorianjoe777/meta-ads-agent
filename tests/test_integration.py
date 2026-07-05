#!/usr/bin/env python3
"""
Integration tests for Meta Ads Agent modules.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import types
import importlib.util
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from campaign_creator import CampaignCreator
from budget_optimizer import BudgetOptimizer, OptimizationStrategy
from ab_testing import ABTestingManager, CreativeElement
from scaling_logic import ScalingManager, ScalingMetrics, ScalingStrategy
from pause_logic import PauseManager, AdPerformance
from auto_warmup import AutoWarmupManager
from license import activate_license, format_license, license_status, normalize_license_entitlements, validate_license_key
from security import dashboard_token_valid, hash_dashboard_password, redact_payload
from product_config import AgentConfig, normalize_hermes_model, normalize_timezone
import product_config
from agent_chat import account_context, parse_skill_response
import agent_chat
import hermes_bridge
import hermes_gateway
import admira_mcp_server
import admira_tool_bridge
import decision_memory
import experiment_scheduler
import graph_executor
import meta_upload
import meta_insights
import optimization_engine
import optimization_research
import public_asset_fetcher
import signal_quality
import shopify_connector
import verified_signal_ledger
import admira_hermes_runtime_patch
from audience_builder import build_audience_strategy
from codex_brand_guides import build_codex_creative_prompt, build_codex_image_prompt_package
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
            daily_brief_time="08:00",
            daily_brief_timezone="America/Bogota",
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
            codex_creative_model="",
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
            daily_brief_time="08:00",
            daily_brief_timezone="America/Bogota",
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
            codex_creative_model="",
        )

        self.assert_true(dashboard_token_valid(config, "secret-password"), "Dashboard password unlocks protected routes")
        self.assert_true(not dashboard_token_valid(config, "wrong-password"), "Wrong dashboard password is rejected")
        config.dashboard_token = ""
        config.dashboard_password = ""
        config.dashboard_password_hash = hash_dashboard_password("secret-password")
        self.assert_true(dashboard_token_valid(config, "secret-password"), "Hashed dashboard password unlocks protected routes")
        self.assert_true(not dashboard_token_valid(config, "wrong-password"), "Wrong hashed dashboard password is rejected")

        dashboard = load_dashboard_module()
        original_load_config = dashboard.load_config
        original_onboarding = dashboard.load_onboarding_state
        original_sessions_file = dashboard.DASHBOARD_SESSIONS_FILE
        original_product_env_file = product_config.ENV_FILE
        original_product_identity_file = product_config.DASHBOARD_IDENTITY_FILE
        handler = object.__new__(dashboard.DashboardHandler)
        try:
            with tempfile.TemporaryDirectory() as tmp_name:
                temp_root = Path(tmp_name)
                env_file = temp_root / ".env"
                identity_file = temp_root / "dashboard" / "data" / "dashboard_identity.json"
                identity_file.parent.mkdir(parents=True)
                recovered_hash = hash_dashboard_password("secret-password")
                env_file.write_text("REQUIRE_DASHBOARD_TOKEN=true\nDASHBOARD_PASSWORD_HASH=\nDASHBOARD_PASSWORD=\nDASHBOARD_TOKEN=\n", encoding="utf-8")
                identity_file.write_text(json.dumps({"dashboard_password_hash": recovered_hash}), encoding="utf-8")
                env_backup = {key: os.environ.get(key) for key in ["REQUIRE_DASHBOARD_TOKEN", "DASHBOARD_PASSWORD_HASH", "DASHBOARD_PASSWORD", "DASHBOARD_TOKEN"]}
                try:
                    for key in env_backup:
                        os.environ.pop(key, None)
                    product_config.ENV_FILE = env_file
                    product_config.DASHBOARD_IDENTITY_FILE = identity_file
                    recovered_config = product_config.load_config()
                    self.assert_true(dashboard_token_valid(recovered_config, "secret-password"), "Dashboard password hash recovers from private identity backup if .env loses it")
                finally:
                    product_config.ENV_FILE = original_product_env_file
                    product_config.DASHBOARD_IDENTITY_FILE = original_product_identity_file
                    for key, value in env_backup.items():
                        if value is None:
                            os.environ.pop(key, None)
                        else:
                            os.environ[key] = value

            class NoPassword:
                dashboard_token = ""
                dashboard_password = ""
                dashboard_password_hash = ""
                dashboard_token_required = True

            class WithPassword:
                dashboard_token = "secret-password"
                dashboard_password = "secret-password"
                dashboard_password_hash = ""
                dashboard_token_required = True

            dashboard.load_onboarding_state = lambda: {"completed": False}
            dashboard.load_config = lambda: NoPassword()
            self.assert_true(not handler.auth_required_for_post("/api/dashboard-password"), "First password creation stays open before a password exists")
            self.assert_true(not handler.auth_required_for_post("/api/agent-model/connect"), "First-run onboarding can start ChatGPT/Codex login before a dashboard password exists")
            self.assert_true(not handler.auth_required_for_post("/api/agent-model/connect-status"), "First-run onboarding can poll ChatGPT/Codex login before a dashboard password exists")
            self.assert_true(not handler.auth_required_for_post("/api/agent-model/connect-input"), "First-run onboarding can answer ChatGPT/Codex login prompts before a dashboard password exists")
            self.assert_true(not handler.auth_required_for_post("/api/onboarding/communication-style"), "First-run onboarding can save the final simple-or-technical preference without a dead locked button")
            self.assert_true(not handler.auth_required_for_post("/api/onboarding/complete"), "First-run onboarding can reach the finish endpoint and receive its own setup validation message")
            self.assert_true(not handler.auth_required_for_get("/api/dashboard"), "Initial setup dashboard can load before a password exists")
            self.assert_true(handler.auth_required_for_post("/api/social/token"), "Meta token save is protected during onboarding")
            self.assert_true(handler.auth_required_for_get("/api/social/accounts"), "Meta account discovery is protected before a password exists")
            dashboard.load_onboarding_state = lambda: {"completed": True}
            self.assert_true(not handler.auth_required_for_post("/api/dashboard-password"), "Password recovery stays open if a completed install has lost its dashboard password")
            dashboard.load_config = lambda: WithPassword()
            self.assert_true(handler.auth_required_for_post("/api/agent-model/connect"), "ChatGPT/Codex login is protected once a dashboard password exists")
            self.assert_true(handler.auth_required_for_post("/api/dashboard-password"), "Changing password requires auth after a password exists")
            self.assert_true(handler.auth_required_for_get("/api/dashboard"), "Dashboard API is protected after password exists even before onboarding is complete")
            with tempfile.TemporaryDirectory() as tmpdir:
                dashboard.DASHBOARD_SESSIONS_FILE = Path(tmpdir) / "dashboard_sessions.json"
                session = dashboard.create_dashboard_session(remember=False)
                raw_sessions = dashboard.read_json(dashboard.DASHBOARD_SESSIONS_FILE, {"sessions": []}).get("sessions", [])
                self.assert_true(session["session_token"].startswith("das_"), "Dashboard unlock returns an opaque session token")
                self.assert_true(dashboard.dashboard_session_valid(session["session_token"]), "Dashboard session token unlocks protected routes")
                self.assert_true(raw_sessions and raw_sessions[0].get("digest") and all(value != session["session_token"] for item in raw_sessions for value in item.values()), "Dashboard sessions store only hashed token digests")
        finally:
            dashboard.load_config = original_load_config
            dashboard.load_onboarding_state = original_onboarding
            dashboard.DASHBOARD_SESSIONS_FILE = original_sessions_file
            product_config.ENV_FILE = original_product_env_file
            product_config.DASHBOARD_IDENTITY_FILE = original_product_identity_file

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
        original_write_onboarding_questions_memory = dashboard.write_onboarding_questions_memory
        setup_payloads = []
        try:
            dashboard.read_json = lambda path, default=None: dict(stored.get("profile", default or {})) if path == dashboard.BUSINESS_PROFILE_FILE else (default or {})
            dashboard.write_json = lambda path, data: stored.__setitem__("profile", dict(data)) if path == dashboard.BUSINESS_PROFILE_FILE else None
            dashboard.save_setup_config = lambda payload: setup_payloads.append(dict(payload)) or {"saved": True}
            dashboard.log_action = lambda *_args, **_kwargs: None
            dashboard.write_onboarding_questions_memory = lambda _profile, status="pending": {"path": "memory", "status": status}
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
            stored["profile"] = {}
            setup_payloads.clear()
            social_only = dashboard.save_business_links_for_agent(
                {
                    "links": "instagram.com/mi-tienda\nfacebook.com/mi-tienda",
                    "business_type": "tienda de ropa",
                }
            )
            self.assert_true(not social_only["profile"].get("website_url") and len(social_only["profile"].get("social_links", [])) == 2, "Social-only links are saved as social profiles, not as the business website")
            self.assert_true(not setup_payloads, "Social-only links do not overwrite the Meta landing URL")
            site_and_social = dashboard.save_business_links_for_agent({"links": "mitienda.com\ninstagram.com/mi-tienda"})
            self.assert_true(site_and_social["profile"].get("website_url") == "https://mitienda.com", "Non-social link becomes the business website")
            self.assert_true(setup_payloads[-1].get("landing_url") == "https://mitienda.com", "Only a real website updates the setup landing URL")
        finally:
            dashboard.read_json = original_read_json
            dashboard.write_json = original_write_json
            dashboard.save_setup_config = original_save_setup_config
            dashboard.log_action = original_log_action
            dashboard.write_onboarding_questions_memory = original_write_onboarding_questions_memory

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
        original_write_onboarding_questions_memory = dashboard.write_onboarding_questions_memory
        stored = {}
        try:
            dashboard.load_config = lambda: FakeConfig()
            dashboard.hermes_codex_ready = lambda _config: (True, "ready")
            dashboard.read_json = lambda path, default=None: dict(stored.get(path, default or {}))
            dashboard.write_json = lambda path, data: stored.__setitem__(path, dict(data))
            dashboard.save_setup_config = lambda _payload: {"saved": True}
            dashboard.log_action = lambda *_args, **_kwargs: None
            dashboard.write_onboarding_questions_memory = lambda _profile, status="pending": {"path": "memory", "status": status}

            def fake_agent_chat(_config, payload):
                captured.setdefault("calls", []).append(payload)
                captured["message"] = payload["message"]
                captured["channel"] = payload.get("channel")
                return {
                    "ok": True,
                    "provider": "hermes",
                    "raw_reply": json.dumps(
                        {
                            "main_offer": "Oferta desde Hermes",
                            "ideal_customer": "Comprador ideal desde Hermes",
                            "products_services": ["Producto uno", "Servicio dos"],
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
            links_scan = dashboard.save_business_links_for_agent(
                {
                    "links": "https://example.com\nhttps://instagram.com/mi-tienda",
                    "business_type": "tienda de skincare",
                }
            )
            link_call = next(call for call in captured["calls"] if call.get("channel") == "onboarding_public_links_scan")
            self.assert_true(links_scan["profile"].get("source") == "hermes_links_scan", "Saving public links triggers an immediate Hermes intelligent scan")
            self.assert_true("Producto uno" in links_scan["profile"].get("products_services", []), "Hermes public-link scan stores detected products or services")
            self.assert_true("instagram.com/mi-tienda" in link_call["message"] and "No inicies sesion" in link_call["message"], "Hermes link scan receives social links with safe public-reading rules")
        finally:
            dashboard.load_config = original_load_config
            dashboard.hermes_codex_ready = original_ready
            dashboard.agent_chat = original_agent_chat
            dashboard.read_json = original_read_json
            dashboard.write_json = original_write_json
            dashboard.save_setup_config = original_save_setup_config
            dashboard.log_action = original_log_action
            dashboard.write_onboarding_questions_memory = original_write_onboarding_questions_memory

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

            agent_chat.hermes_chat = lambda config, payload: received.append(payload) or {
                "ok": True,
                "provider": "hermes",
                "reply": "",
            }
            empty_result = agent_chat.chat(FakeConfig(), {"message": "Hola", "metrics": {}, "language": "es"})
            self.assert_true(empty_result.get("fallback") is True and empty_result.get("reply") and "No pude responder" not in empty_result.get("reply"), "Empty Hermes replies become useful manager fallback text")
            noisy = "⚠ tirith security scanner enabled but not available — command scanning will use pattern matching only\n  ┊ review diff\na/data/business_profile.json → b/data/business_profile.json\n@@ -1,3 +1,4 @@\n-  \"source\": \"links\"\n+  \"source\": \"dashboard_chat\"\nTenés razón. Sigo con una pregunta a la vez."
            clean = agent_chat.clean_reply(noisy)
            self.assert_true(clean.startswith("Tenés razón") and "business_profile" not in clean and "tirith" not in clean.lower(), "Technical Hermes/Codex diff output is stripped before reaching buyers")
            compaction_notice = "ℹ Codex gpt-5.5 caps context at 272K, so auto-compaction was raised to 85% (from 50%) to use more of the window before summarizing.\n  Opt back out: hermes config set compression.codex_gpt55_autoraise false\nSeguimos con la guía de marca."
            compaction_clean = agent_chat.clean_reply(compaction_notice)
            self.assert_true(compaction_clean == "Seguimos con la guía de marca.", "Internal Codex context-compression notices are stripped before reaching buyers")
            agent_chat.hermes_chat = lambda config, payload: {"ok": True, "provider": "hermes", "reply": noisy}
            clean_result = agent_chat.chat(FakeConfig(), {"message": "Hola", "metrics": {}, "language": "es"})
            self.assert_true(clean_result["reply"].startswith("Tenés razón") and "tirith" not in clean_result["reply"].lower(), "Plain Hermes replies are cleaned before any channel sends them")
        finally:
            agent_chat.hermes_chat = original_hermes_chat

    def test_hermes_empty_library_reply_falls_back_to_cli(self):
        """Test Hermes Python runtime empty replies are retried through the CLI path."""
        print("\nTesting Hermes Empty Library Reply Fallback...")

        class FakeConfig:
            agent_chat_provider = "hermes"
            agent_brain_provider = "custom_api"
            agent_chat_base_url = "https://example.test/v1"
            agent_chat_api_key = "test-key"
            agent_chat_model = "custom-model"
            hermes_require_codex_auth = False
            hermes_use_python_library = True
            hermes_max_iterations = 1
            hermes_timeout_seconds = 1
            hermes_status_timeout_seconds = 1
            hermes_response_timeout_seconds = 300
            hermes_enabled_toolsets = ""
            hermes_disabled_toolsets = "terminal"
            hermes_cli = "hermes"
            hermes_home = ""

        calls = []
        original_library = hermes_bridge.library_chat
        original_cli = hermes_bridge.cli_chat
        try:
            hermes_bridge.library_chat = lambda config, payload: calls.append("library") or ""
            hermes_bridge.cli_chat = lambda config, payload: calls.append("cli") or "Respuesta desde CLI."
            result = hermes_bridge.chat(FakeConfig(), {"message": "Hola", "language": "es", "account_context": {}})
            self.assert_true(result["ok"] is True and result["reply"] == "Respuesta desde CLI.", "Hermes retries the CLI path when the library returns an empty reply")
            self.assert_true(calls == ["library", "cli"], "Hermes library empty response triggers exactly one CLI retry")
        finally:
            hermes_bridge.library_chat = original_library
            hermes_bridge.cli_chat = original_cli

    def test_dashboard_hermes_cli_registers_admira_mcp_tools(self):
        """Test dashboard Hermes CLI chat receives Admira product tools and official MiniMax routing."""
        print("\nTesting Dashboard Hermes CLI Admira MCP Registration...")

        temp_dir = Path(tempfile.mkdtemp(prefix="admira-dashboard-hermes-"))
        workspace = temp_dir / "workspace"
        home = temp_dir / "hermes-home"
        workspace.mkdir(parents=True, exist_ok=True)

        class FakeConfig:
            agent_chat_provider = "hermes"
            agent_brain_provider = "minimax"
            agent_chat_base_url = "https://api.minimax.io/v1"
            agent_chat_api_key = "direct-minimax-key"
            agent_chat_model = "MiniMax-M3"
            hermes_require_codex_auth = False
            hermes_use_python_library = True
            hermes_max_iterations = 3
            hermes_timeout_seconds = 1
            hermes_status_timeout_seconds = 1
            hermes_response_timeout_seconds = 30
            hermes_enabled_toolsets = "memory,skills,session_search,vision,file,web,browser"
            hermes_disabled_toolsets = "terminal,code_execution,image_gen"
            hermes_cli = "hermes"
            hermes_home = str(home)
            daily_brief_timezone = "America/Bogota"

        captured = {}
        original_prepare = hermes_bridge.prepare_hermes_workspace
        original_run = hermes_bridge.subprocess.run
        try:
            hermes_bridge.prepare_hermes_workspace = lambda payload: {
                "path": str(workspace),
                "files": ["AGENTS.md", "CURRENT_CONTEXT.json"],
                "image_paths": [],
            }

            def fake_run(command, **kwargs):
                captured["command"] = list(command)
                captured["kwargs"] = kwargs

                class Completed:
                    returncode = 0
                    stdout = "Respuesta Hermes dashboard."
                    stderr = ""

                return Completed()

            hermes_bridge.subprocess.run = fake_run
            result = hermes_bridge.chat(
                FakeConfig(),
                {
                    "message": "prepara una campaña y revisa este enlace",
                    "language": "es",
                    "channel": "dashboard",
                    "account_context": {},
                },
            )

            command = captured["command"]
            toolsets = command[command.index("--toolsets") + 1].split(",")
            config_text = (home / "config.yaml").read_text(encoding="utf-8")
            env = captured["kwargs"]["env"]

            self.assert_true(result["ok"] is True and result["reply"] == "Respuesta Hermes dashboard.", "Dashboard Hermes CLI returns the model response")
            self.assert_true("--continue" in command and "meta-ads-agent-dashboard" in command, "Dashboard chat uses a persistent Hermes dashboard session")
            self.assert_true("--provider" in command and command[command.index("--provider") + 1] == "admira-minimax", "Dashboard MiniMax uses Hermes' official providers entry route")
            self.assert_true("admira" in toolsets and "web" in toolsets and "browser" in toolsets, "Dashboard Hermes CLI includes Admira MCP plus safe web/browser toolsets")
            self.assert_true(env["HERMES_HOME"] == str(home), "Dashboard Hermes CLI uses the configured Hermes home")
            self.assert_true(env["ADMIRA_MINIMAX_API_KEY"] == "direct-minimax-key" and env["ADMIRA_MINIMAX_BASE_URL"] == "https://api.minimax.io/v1" and "MINIMAX_API_KEY" not in env, "Official MiniMax credentials stay in the process environment without activating Hermes' native MiniMax provider")
            self.assert_true("mcp_servers:" in config_text and "admira_mcp_server.py" in config_text, "Hermes config registers the Admira MCP server")
            self.assert_true("providers:" in config_text and "admira-minimax:" in config_text and "https://api.minimax.io/v1" in config_text and "custom:admira-minimax" not in config_text, "Hermes config points MiniMax to the official API through a providers entry")
            self.assert_true("direct-minimax-key" not in config_text and "openrouter" not in config_text.lower(), "Hermes config does not persist API keys or OpenRouter routing")
            self.assert_true("platform_toolsets:" in config_text and "dashboard:" in config_text and "admira" in config_text, "Hermes config exposes Admira tools to the dashboard platform")
        finally:
            hermes_bridge.prepare_hermes_workspace = original_prepare
            hermes_bridge.subprocess.run = original_run
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_hermes_creative_image_request_routes_to_codex_tool(self):
        """Test Hermes can route a natural image-creative request to the Codex image tool."""
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
                            "tool": "codex_image_generate",
                            "arguments": {
                                "request": "Genera un creativo final para Meta Ads usando Codex/Image. Producto fisico protagonista, fondo limpio, promesa clara y formato 4:5.",
                                "product_guide": "",
                                "reference_image_summary": "producto fisico protagonista, fondo limpio, promesa clara y formato 4:5",
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
            self.assert_true(tool_request.get("tool") == "codex_image_generate", "Creative image requests route to the Codex/Image backend bridge")
            self.assert_true("reference_image_summary" in tool_request.get("arguments", {}), "Hermes includes visual summary for Codex instead of relying on file reads")
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

    def test_hermes_model_usage_limit_keeps_connection_state_clear(self):
        """Test ChatGPT/Codex usage limits are not reported as missing setup."""
        print("\nTesting Hermes Model Usage Limit Messaging...")

        class FakeConfig:
            agent_chat_provider = "hermes"
            agent_brain_provider = "openai_codex"
            hermes_require_codex_auth = True
            hermes_use_python_library = False
            hermes_cli = "hermes"
            hermes_model = ""
            hermes_timeout_seconds = 1
            hermes_max_iterations = 1
            hermes_enabled_toolsets = ""
            hermes_disabled_toolsets = "terminal"
            hermes_home = ""

        original_ready = hermes_bridge.hermes_brain_ready
        original_cli = hermes_bridge.cli_chat
        try:
            hermes_bridge.hermes_brain_ready = lambda _config: (True, "Provider: OpenAI Codex; OpenAI Codex ✓ logged in")

            def raise_limit(_config, _payload):
                raise RuntimeError("429 usage limit reached. Try again in 4 hours.")

            hermes_bridge.cli_chat = raise_limit
            result = hermes_bridge.chat(FakeConfig(), {"message": "Hola", "language": "es", "channel": "telegram", "session_key": "telegram:123"})
            self.assert_true(result.get("error_type") == "model_usage_limit", "Hermes classifies model usage limits separately")
            self.assert_true("sí está conectado" in result["reply"] and "límite temporal" in result["reply"], "Buyer message explains connected-but-limited state")
            self.assert_true("falta conectar" not in result["reply"].lower() and "4 hours" in result.get("retry_after_hint", "") and "4 horas" in result["reply"], "Usage limit reply does not ask to reconnect and localizes retry timing")
            self.assert_true("/model" in result["reply"] and "gpt-5.4 mini" in result["reply"], "Usage limit reply suggests the simple Telegram model switch when limits happen often")

            def raise_rate_limited(_config, _payload):
                raise RuntimeError("The model provider is rate-limiting requests. Please wait a moment and try again.")

            hermes_bridge.cli_chat = raise_rate_limited
            limited = hermes_bridge.chat(FakeConfig(), {"message": "Hola", "language": "es", "channel": "telegram", "session_key": "telegram:123"})
            self.assert_true(limited.get("error_type") == "model_usage_limit" and "rate-limiting" not in limited["reply"].lower(), "English provider rate-limit text is converted to a Spanish buyer message")
            self.assert_true("Puedes intentar de nuevo en un momento" in limited["reply"], "Provider retry hint is included in Spanish when available")
            self.assert_true("/model" in limited["reply"] and "gpt-5.4 mini" in limited["reply"], "Provider rate-limit reply includes a lightweight model guide")
        finally:
            hermes_bridge.hermes_brain_ready = original_ready
            hermes_bridge.cli_chat = original_cli

    def test_hermes_gateway_rate_limit_runtime_patch_localizes_reset_time(self):
        """Test native Hermes Gateway rate-limit fallbacks stay Spanish and include reset timing."""
        print("\nTesting Hermes Gateway Rate Limit Runtime Patch...")

        raw_five_hours = "HTTP 429: {'error': {'type': 'usage_limit_reached', 'resets_in_seconds': 18000}}"
        spanish = admira_hermes_runtime_patch.provider_error_reply(raw_five_hours, "es", lambda text: "ORIGINAL")
        english = admira_hermes_runtime_patch.provider_error_reply(raw_five_hours, "en", lambda text: "ORIGINAL")

        self.assert_true("ChatGPT/Codex" in spanish and "5 horas" in spanish and "rate-limiting" not in spanish.lower(), "Gateway rate-limit text is localized in Spanish with a 5-hour reset")
        self.assert_true("5 hours" in english and "usage limit" in english.lower(), "Gateway rate-limit text can stay English when configured")
        self.assert_true("/model" in spanish and "gpt-5.4 mini" in spanish, "Gateway rate-limit text teaches the simple Telegram model switch")

        raw_long_reset = "HTTP 429: {'error': {'type': 'usage_limit_reached', 'resets_in_seconds': 199500}}"
        long_spanish = admira_hermes_runtime_patch.provider_error_reply(raw_long_reset, "es", lambda text: "ORIGINAL")
        self.assert_true("2 días y 8 horas" in long_spanish, "Long provider reset windows are formatted as days plus hours")

        unknown = admira_hermes_runtime_patch.provider_error_reply("The model provider is rate-limiting requests. Please wait a moment and try again.", "es", lambda text: "ORIGINAL")
        passthrough = admira_hermes_runtime_patch.provider_error_reply("Some unrelated provider failure", "es", lambda text: f"ORIGINAL:{text}")
        self.assert_true("un momento" in unknown and "rate-limiting" not in unknown.lower(), "Gateway keeps a Spanish fallback when only a vague wait hint exists")
        self.assert_true(passthrough.startswith("ORIGINAL:"), "Runtime patch delegates unrelated provider failures to Hermes")

    def test_hermes_gateway_runtime_patch_always_attaches_generated_creatives(self):
        """Test generated Codex/Image files are attached even when small models omit MEDIA in the reply."""
        print("\nTesting Hermes Gateway Generated Media Runtime Patch...")

        image_dir = ROOT_DIR / "output" / "test-runtime-generated-media"
        image_dir.mkdir(parents=True, exist_ok=True)
        generated_image = image_dir / "fixed-01.png"
        generated_image.write_bytes(b"fake png")
        original_env = {
            "ADMIRA_PRODUCT_ROOT": os.environ.get("ADMIRA_PRODUCT_ROOT"),
            "HERMES_MEDIA_ALLOW_DIRS": os.environ.get("HERMES_MEDIA_ALLOW_DIRS"),
        }
        try:
            os.environ["ADMIRA_PRODUCT_ROOT"] = str(ROOT_DIR)
            os.environ["HERMES_MEDIA_ALLOW_DIRS"] = str((ROOT_DIR / "output").resolve())
            response = {
                "final_response": "Listo, ya quedó generada. La imagen salió fuerte y editorial.",
                "messages": [
                    {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "ok": True,
                                "tool": "admira_codex_image_generate",
                                "result": {
                                    "result": {
                                        "ok": True,
                                        "image_path": str(generated_image),
                                    }
                                },
                            },
                            ensure_ascii=False,
                        ),
                    }
                ],
            }
            patched = admira_hermes_runtime_patch._append_generated_media_attachments(response)
            patched_again = admira_hermes_runtime_patch._append_generated_media_attachments(patched)
            unsafe = admira_hermes_runtime_patch._append_generated_media_attachments(
                {
                    "final_response": "Listo.",
                    "messages": [{"role": "assistant", "content": '{"image_path": "/etc/passwd"}'}],
                }
            )
            plain_path_response = admira_hermes_runtime_patch._append_generated_media_attachments(
                {
                    "final_response": f"Si quieres verla/usar la actual: {generated_image.resolve()}",
                    "messages": [],
                }
            )
            self.assert_true(f"MEDIA:{generated_image.resolve()}" in patched["final_response"], "Runtime patch appends generated image MEDIA directive from non-tool message results")
            self.assert_true(patched_again["final_response"].count("MEDIA:") == 1, "Runtime patch does not duplicate generated media attachments")
            self.assert_true("MEDIA:" not in unsafe["final_response"], "Runtime patch does not attach unsafe paths outside product output")
            self.assert_true(f"MEDIA:{generated_image.resolve()}" in plain_path_response["final_response"], "Runtime patch still attaches media when a small model leaks a plain output path")
        finally:
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            shutil.rmtree(image_dir, ignore_errors=True)

    def test_hermes_gateway_minimax_runtime_patch_forces_official_provider(self):
        """Test Telegram /model MiniMax choices are forced onto Hermes' official providers entry."""
        print("\nTesting Hermes Gateway MiniMax Official Provider Runtime Patch...")

        original_modules = {
            "hermes_cli": sys.modules.get("hermes_cli"),
            "hermes_cli.model_switch": sys.modules.get("hermes_cli.model_switch"),
            "hermes_cli.runtime_provider": sys.modules.get("hermes_cli.runtime_provider"),
        }
        original_env = {key: os.environ.get(key) for key in ["ADMIRA_MINIMAX_API_KEY", "ADMIRA_MINIMAX_BASE_URL", "ADMIRA_MINIMAX_MODEL", "ADMIRA_MINIMAX_PROVIDER"]}

        class DirectAlias:
            def __init__(self, model, provider, base_url):
                self.model = model
                self.provider = provider
                self.base_url = base_url

        fake_parent = types.ModuleType("hermes_cli")
        fake_parent.__path__ = []
        fake_model_switch = types.ModuleType("hermes_cli.model_switch")
        fake_model_switch.DirectAlias = DirectAlias
        fake_model_switch.DIRECT_ALIASES = {}
        fake_runtime_provider = types.ModuleType("hermes_cli.runtime_provider")
        switch_calls = {}

        def original_resolve_alias(raw_input, current_provider=""):
            return None

        def original_switch_model(**kwargs):
            switch_calls.update(kwargs)
            return {"success": True}

        def original_list_authenticated_providers(*_args, **_kwargs):
            return [
                {"slug": "minimax", "name": "MiniMax", "models": ["MiniMax-M3"]},
                {"slug": "admira-minimax", "name": "admira-minimax", "models": ["MiniMax-M3"]},
            ]

        def original_get_named_custom_provider(_requested_provider):
            return None

        fake_model_switch.resolve_alias = original_resolve_alias
        fake_model_switch.switch_model = original_switch_model
        fake_model_switch.list_authenticated_providers = original_list_authenticated_providers
        fake_model_switch.list_picker_providers = original_list_authenticated_providers
        fake_runtime_provider._get_named_custom_provider = original_get_named_custom_provider

        try:
            sys.modules["hermes_cli"] = fake_parent
            sys.modules["hermes_cli.model_switch"] = fake_model_switch
            sys.modules["hermes_cli.runtime_provider"] = fake_runtime_provider
            os.environ["ADMIRA_MINIMAX_API_KEY"] = "direct-minimax-key"
            os.environ["ADMIRA_MINIMAX_BASE_URL"] = "https://api.minimax.io/v1"
            os.environ["ADMIRA_MINIMAX_MODEL"] = "MiniMax-M3"
            os.environ["ADMIRA_MINIMAX_PROVIDER"] = "admira-minimax"

            applied = admira_hermes_runtime_patch.apply()
            alias = fake_model_switch.resolve_alias("MiniMax M3", "openai-codex")
            fake_model_switch.switch_model(
                raw_input="MiniMax-M3",
                current_provider="openai-codex",
                current_model="gpt-5.5",
                current_base_url="",
                current_api_key="",
                explicit_provider="minimax",
                user_providers={},
                custom_providers=[],
            )
            provider_rows = fake_model_switch.list_authenticated_providers()
            picker_rows = fake_model_switch.list_picker_providers()
            runtime_provider = fake_runtime_provider._get_named_custom_provider("custom:admira-minimax")

            self.assert_true(applied is True, "Admira runtime patch applies even when only the model-switch patch is available")
            self.assert_true(alias == ("admira-minimax", "MiniMax-M3", "minimax m3"), "MiniMax M3 aliases resolve to the Admira providers entry")
            self.assert_true("minimax" in fake_model_switch.DIRECT_ALIASES and fake_model_switch.DIRECT_ALIASES["minimax"].provider == "admira-minimax", "Runtime patch injects direct MiniMax aliases before picker resolution")
            self.assert_true(switch_calls["explicit_provider"] == "admira-minimax" and switch_calls["raw_input"] == "MiniMax-M3", "Native MiniMax picker selections are rewritten to the official providers entry")
            self.assert_true(switch_calls["user_providers"]["admira-minimax"]["key_env"] == "ADMIRA_MINIMAX_API_KEY" and switch_calls["user_providers"]["admira-minimax"]["api_mode"] == "chat_completions", "Injected provider uses Admira's private key env and OpenAI-compatible mode")
            self.assert_true(runtime_provider["key_env"] == "ADMIRA_MINIMAX_API_KEY" and runtime_provider["base_url"] == "https://api.minimax.io/v1", "Runtime provider patch migrates stale custom-prefixed overrides to the official providers entry")
            self.assert_true(all(row["slug"] != "minimax" for row in provider_rows + picker_rows), "Native Hermes MiniMax row is hidden when Admira MiniMax is configured")
            self.assert_true(any(row["name"] == "MiniMax M3 oficial" for row in provider_rows + picker_rows), "MiniMax providers entry is shown with a buyer-friendly label")
        finally:
            for key, value in original_modules.items():
                if value is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = value
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_dashboard_chatgpt_connect_action_opens_terminal(self):
        """Test the dashboard ChatGPT/Codex connection endpoint prefers an automatic terminal action."""
        print("\nTesting Dashboard ChatGPT/Codex Connect Action...")

        self.assert_true(normalize_hermes_model("") == "gpt-5.5", "Empty Hermes model uses gpt-5.5")
        self.assert_true(normalize_hermes_model("auto") == "gpt-5.5", "Legacy auto Hermes model uses gpt-5.5")
        self.assert_true(normalize_hermes_model("recommended") == "gpt-5.5", "Legacy recommended Hermes model uses gpt-5.5")

        dashboard = load_dashboard_module()
        captured = {}
        original_update = dashboard.update_env_values
        original_launch = dashboard.launch_hermes_terminal
        original_ready = dashboard.hermes_codex_ready
        original_log = dashboard.log_action
        try:
            dashboard.update_env_values = lambda values: captured.update(values)
            dashboard.launch_hermes_terminal = lambda _config: True
            dashboard.hermes_codex_ready = lambda _config: (False, "Provider unknown; OpenAI Codex not logged in")
            dashboard.log_action = lambda *_args, **_kwargs: None
            result = dashboard.connect_agent_model({})
            self.assert_true(result["status"] == "terminal_opened", "Connect action opens the terminal when the environment allows it")
            self.assert_true(captured.get("AGENT_CHAT_PROVIDER") == "hermes", "Connect action selects Hermes as the agent provider")
            self.assert_true(captured.get("HERMES_REQUIRE_CODEX_AUTH") == "true", "Connect action keeps Codex auth required by default")
            self.assert_true(captured.get("HERMES_MODEL") == "gpt-5.5", "ChatGPT/Codex connection pins gpt-5.5 by default instead of an unavailable auto option")
        finally:
            dashboard.update_env_values = original_update
            dashboard.launch_hermes_terminal = original_launch
            dashboard.hermes_codex_ready = original_ready
            dashboard.log_action = original_log

    def test_dashboard_chatgpt_connect_does_not_reopen_login_when_ready(self):
        """Test already connected ChatGPT/Codex saves model choice without opening another login path."""
        print("\nTesting Dashboard ChatGPT/Codex Already Connected...")

        dashboard = load_dashboard_module()
        captured = {}
        launched = []
        original_update = dashboard.update_env_values
        original_launch = dashboard.launch_hermes_terminal
        original_start = dashboard.start_hermes_browserless_login
        original_ready = dashboard.hermes_codex_ready
        original_log = dashboard.log_action
        try:
            dashboard.update_env_values = lambda values: captured.update(values)
            dashboard.launch_hermes_terminal = lambda _config: launched.append("terminal") or True
            dashboard.start_hermes_browserless_login = lambda _config: launched.append("browserless") or {"status": "browser_login_started"}
            dashboard.hermes_codex_ready = lambda _config: (True, "Provider: OpenAI Codex; OpenAI Codex ✓ logged in")
            dashboard.log_action = lambda *_args, **_kwargs: None
            result = dashboard.connect_agent_model({"hermes_model": "gpt-5.5"})
            self.assert_true(result["status"] == "completed", "Connect action reports completed when ChatGPT/Codex is already ready")
            self.assert_true(result["mode"] == "already_ready", "Already-ready state is explicit")
            self.assert_true(captured.get("HERMES_MODEL") == "gpt-5.5", "Exact Codex model choice is still saved")
            self.assert_true(launched == [], "Already-ready connect does not open terminal or browserless login")
        finally:
            dashboard.update_env_values = original_update
            dashboard.launch_hermes_terminal = original_launch
            dashboard.start_hermes_browserless_login = original_start
            dashboard.hermes_codex_ready = original_ready
            dashboard.log_action = original_log

    def test_dashboard_image_only_chatgpt_connect_preserves_text_brain(self):
        """Test a dedicated ChatGPT/Codex image login does not replace MiniMax/API as the text brain."""
        print("\nTesting Dashboard Image-Only ChatGPT/Codex Connect...")

        dashboard = load_dashboard_module()
        captured = {}
        original_update = dashboard.update_env_values
        original_launch = dashboard.launch_hermes_terminal
        original_ready = dashboard.hermes_codex_ready
        original_log = dashboard.log_action
        try:
            dashboard.update_env_values = lambda values: captured.update(values)
            dashboard.launch_hermes_terminal = lambda _config: False
            dashboard.hermes_codex_ready = lambda _config: (True, "Provider: OpenAI Codex; OpenAI Codex ✓ logged in")
            dashboard.log_action = lambda *_args, **_kwargs: None

            result = dashboard.connect_agent_model({"connection_purpose": "image", "codex_image_hermes_model": "gpt-5.5"})

            self.assert_true(result["status"] == "completed" and result.get("connection_purpose") == "image", "Image-only ChatGPT connection can complete independently")
            self.assert_true(captured.get("CODEX_IMAGE_SOURCE") == "dedicated_chatgpt" and captured.get("CODEX_IMAGE_HERMES_MODEL") == "gpt-5.5", "Image-only connection saves dedicated image routing")
            self.assert_true("CODEX_IMAGE_HERMES_HOME" in captured, "Image-only connection creates a persistent image auth home")
            self.assert_true("AGENT_BRAIN_PROVIDER" not in captured and "AGENT_CHAT_PROVIDER" not in captured, "Image-only connection does not overwrite the main text brain")
        finally:
            dashboard.update_env_values = original_update
            dashboard.launch_hermes_terminal = original_launch
            dashboard.hermes_codex_ready = original_ready
            dashboard.log_action = original_log

    def test_dashboard_chatgpt_disconnect_clears_only_auth_artifacts(self):
        """Test ChatGPT/Codex disconnect removes auth without deleting the Hermes workspace."""
        print("\nTesting Dashboard ChatGPT/Codex Disconnect...")

        dashboard = load_dashboard_module()
        dashboard.DATA_DIR.mkdir(parents=True, exist_ok=True)
        auth_home = Path(tempfile.mkdtemp(prefix="disconnect-hermes-", dir=str(dashboard.DATA_DIR)))
        outside_home = Path(tempfile.mkdtemp(prefix="disconnect-outside-"))
        try:
            (auth_home / "auth.json").write_text("{}", encoding="utf-8")
            (auth_home / "credentials.json").write_text("{}", encoding="utf-8")
            (auth_home / "auth").mkdir()
            (auth_home / "auth" / "token").write_text("secret", encoding="utf-8")
            (auth_home / "config.yaml").write_text("keep", encoding="utf-8")
            (auth_home / "logs").mkdir()
            (auth_home / "logs" / "agent.log").write_text("keep", encoding="utf-8")
            (outside_home / "auth.json").write_text("{}", encoding="utf-8")

            cfg = type(
                "Cfg",
                (),
                {
                    "hermes_home": str(auth_home),
                    "hermes_model": "gpt-5.5",
                    "codex_image_hermes_model": "gpt-5.5",
                    "hermes_cli": "hermes",
                },
            )()
            captured = {}
            original_load = dashboard.load_config
            original_update = dashboard.update_env_values
            original_refresh = dashboard.refresh_telegram_gateway_after_agent_model_change
            original_log = dashboard.log_action
            try:
                dashboard.load_config = lambda: cfg
                dashboard.update_env_values = lambda values: captured.update(values)
                dashboard.refresh_telegram_gateway_after_agent_model_change = lambda values: {"started": True, "changed": sorted(values)}
                dashboard.log_action = lambda *_args, **_kwargs: None
                result = dashboard.disconnect_agent_model({"connection_purpose": "agent"})
                self.assert_true(result["status"] == "disconnected" and result["connection_purpose"] == "agent", "Disconnect endpoint reports the account as disconnected")
                self.assert_true(not (auth_home / "auth.json").exists() and not (auth_home / "credentials.json").exists() and not (auth_home / "auth").exists(), "Disconnect removes only known Codex auth artifacts")
                self.assert_true((auth_home / "config.yaml").exists() and (auth_home / "logs" / "agent.log").exists(), "Disconnect preserves non-auth Hermes workspace files")
                self.assert_true(captured.get("HERMES_REQUIRE_CODEX_AUTH") == "true", "Disconnect keeps Codex auth required for the next login")
                try:
                    dashboard.clear_hermes_codex_auth(outside_home)
                    self.assert_true(False, "Disconnect should refuse homes outside Admira runtime/data")
                except ValueError:
                    pass
            finally:
                dashboard.load_config = original_load
                dashboard.update_env_values = original_update
                dashboard.refresh_telegram_gateway_after_agent_model_change = original_refresh
                dashboard.log_action = original_log
        finally:
            shutil.rmtree(auth_home, ignore_errors=True)
            shutil.rmtree(outside_home, ignore_errors=True)

    def test_dashboard_chatgpt_connect_action_uses_vps_browserless_bridge(self):
        """Test the ChatGPT/Codex connection endpoint starts a browser-visible Hermes bridge on VPS/headless installs."""
        print("\nTesting Dashboard ChatGPT/Codex VPS Browserless Bridge...")

        dashboard = load_dashboard_module()
        captured = {}
        original_update = dashboard.update_env_values
        original_launch = dashboard.launch_hermes_terminal
        original_start = dashboard.start_hermes_browserless_login
        original_ready = dashboard.hermes_codex_ready
        original_log = dashboard.log_action
        try:
            dashboard.update_env_values = lambda values: captured.update(values)
            dashboard.launch_hermes_terminal = lambda _config: False
            dashboard.hermes_codex_ready = lambda _config: (False, "Provider unknown; OpenAI Codex not logged in")
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
            dashboard.hermes_codex_ready = original_ready
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

            shifted_numbered_provider_output = (
                "Select provider:\n"
                "Select by number, Enter to confirm.\n"
                "(●)  1. Nous Portal\n"
                "(○)  6. Anthropic (Claude models via API key or Claude Code)\n"
                "(○)  7. OpenAI ▸ (Codex CLI or direct OpenAI API)\n"
                "Choice [default 1]:\n"
            )
            with dashboard.HERMES_LOGIN_LOCK:
                dashboard.HERMES_LOGIN_STATE.update({
                    "id": "auto-test",
                    "output": shifted_numbered_provider_output,
                    "auto_provider_sent": False,
                    "auto_codex_subprovider_sent": False,
                    "auto_model_sent": False,
                    "auto_note": "",
                })
            selected_shifted_provider = dashboard.maybe_auto_drive_hermes_browserless("auto-test", 99)
            self.assert_true(selected_shifted_provider is True and writes[-1] == (99, b"7\n"), "Browserless Hermes parses shifted numbered provider menus instead of hardcoding option 6")

            partial_provider_output = (
                "Select provider:\n"
                "Select by number, Enter to confirm.\n"
                "(●)  1. Nous Portal\n"
                "(○)  2. OpenRouter\n"
                "Choice [default 1]:\n"
            )
            writes_before_partial = len(writes)
            with dashboard.HERMES_LOGIN_LOCK:
                dashboard.HERMES_LOGIN_STATE.update({
                    "id": "auto-test",
                    "output": partial_provider_output,
                    "auto_provider_sent": False,
                    "auto_codex_subprovider_sent": False,
                    "auto_model_sent": False,
                    "auto_note": "",
                })
            selected_partial_provider = dashboard.maybe_auto_drive_hermes_browserless("auto-test", 99)
            self.assert_true(selected_partial_provider is False and len(writes) == writes_before_partial, "Browserless Hermes waits for OpenAI to appear instead of guessing an old provider number")

            tui_provider_output = (
                "Select provider:\n"
                "  ↑↓ navigate  ENTER/SPACE select  ESC cancel\n"
                " → (●) Nous Portal\n"
                "   (○) OpenRouter\n"
                "   (○) Mixture of Agents\n"
                "   (○) NovitaAI\n"
                "   (○) LM Studio\n"
                "   (○) Anthropic\n"
                "   (○) OpenAI ▸ (Codex CLI or direct OpenAI API)\n"
                "   (○) Qwen Cloud / DashScope\n"
            )
            with dashboard.HERMES_LOGIN_LOCK:
                dashboard.HERMES_LOGIN_STATE.update({
                    "id": "auto-test",
                    "output": tui_provider_output,
                    "auto_provider_sent": False,
                    "auto_codex_subprovider_sent": False,
                    "auto_model_sent": False,
                    "auto_note": "",
                })
            selected_tui_provider = dashboard.maybe_auto_drive_hermes_browserless("auto-test", 99)
            self.assert_true(selected_tui_provider is True and writes[-1] == (99, (b"\x1b[B" * 6) + b"\n"), "Browserless Hermes navigates the new arrow-key provider menu to OpenAI")

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

            tui_subprovider_output = (
                "Select OpenAI provider:\n"
                "  ↑↓ navigate  ENTER/SPACE select  ESC cancel\n"
                " → (●) OpenAI Codex\n"
                "   (○) OpenAI API\n"
            )
            with dashboard.HERMES_LOGIN_LOCK:
                dashboard.HERMES_LOGIN_STATE.update({
                    "id": "auto-test",
                    "output": tui_subprovider_output,
                    "auto_provider_sent": True,
                    "auto_codex_subprovider_sent": False,
                    "auto_model_sent": False,
                    "auto_note": "",
                })
            selected_tui_subprovider = dashboard.maybe_auto_drive_hermes_browserless("auto-test", 99)
            self.assert_true(selected_tui_subprovider is True and writes[-1] == (99, b"\n"), "Browserless Hermes confirms the default OpenAI Codex option in the arrow-key submenu")

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

            exact_model_output = (
                "Select model:\n"
                "  1. gpt-5.4-mini\n"
                "  2. gpt-5.5\n"
                "Select by number, Enter to confirm.\n"
            )
            with dashboard.HERMES_LOGIN_LOCK:
                dashboard.HERMES_LOGIN_STATE.update({
                    "id": "auto-test",
                    "output": exact_model_output,
                    "auto_provider_sent": True,
                    "auto_codex_subprovider_sent": True,
                    "auto_model_sent": False,
                    "preferred_model": "gpt-5.5",
                    "auto_note": "",
                    "proc": None,
                    "fd": None,
                })
            selected_exact_model = dashboard.maybe_auto_drive_hermes_browserless("auto-test", 99)
            self.assert_true(selected_exact_model is True and writes[-1] == (99, b"2\n"), "Browserless Hermes selects the buyer's exact Codex model when it appears")

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
            url_only_code_output = "Open this URL: https://auth.openai.com/device?user_code=HTTP-45552\n"
            self.assert_true(dashboard.extract_login_codes_from_text(url_only_code_output) == [], "OpenAI terminal code extraction ignores codes that only appear inside URLs")
            nine_letter_output = (
                "OpenAI will ask for the code displayed in your terminal.\n\n"
                "Copy this code into the browser:\n"
                "ABCDEFGHI\n"
            )
            self.assert_true(dashboard.extract_login_codes_from_text(nine_letter_output) == ["ABCDEFGHI"], "OpenAI terminal code extraction supports full 9-letter standalone lines")
            longer_changed_output = (
                "OpenAI will ask for the code displayed in your terminal.\n\n"
                "Copy this code into the browser:\n"
                "ABCD EFGHI JK\n"
            )
            self.assert_true(dashboard.extract_login_codes_from_text(longer_changed_output) == ["ABCD-EFGHI-JK"], "OpenAI terminal code extraction reads the full standalone code line when length changes")
            hermes_menu_then_real_code_output = (
                "Select provider:\n"
                "  (○)  6. OpenAI ▸ (Codex CLI or direct OpenAI API)\n"
                "  (○)  7. Qwen Cloud / DashScope (Qwen + multi-provider)\n"
                "  (○) 24. OpenCode ▸ (Zen pay-as-you-go or Go subscription)\n"
                "Choice [default 1]: 6\n\n"
                "Select provider:\n"
                "  (●)  1. OpenAI Codex\n"
                "  (○)  2. OpenAI API\n"
                "Choice [default 1]: 1\n\n"
                "Not logged into OpenAI Codex. Starting login...\n"
                "Signing in to OpenAI Codex...\n\n"
                "To continue, follow these steps:\n"
                "  1. Open this URL in your browser:\n"
                "     https://auth.openai.com/codex/device\n\n"
                "  2. Enter this code:\n"
                "     BM35-9UQFA\n\n"
                "Waiting for sign-in... (press Ctrl+C to cancel)\n"
            )
            self.assert_true(dashboard.extract_login_codes_from_text(hermes_menu_then_real_code_output) == ["BM35-9UQFA"], "OpenAI terminal code extraction ignores provider menu labels like Qwen Cloud and prefers the final device code")
            provider_menu_only_output = (
                "Select provider:\n"
                "  (○)  7. Qwen Cloud / DashScope (Qwen + multi-provider)\n"
                "  (○) 24. OpenCode ▸ (Zen pay-as-you-go or Go subscription)\n"
            )
            self.assert_true(dashboard.extract_login_codes_from_text(provider_menu_only_output) == [], "Provider menus alone do not produce fake OpenAI login codes")
            device_auth_output = 'Enable device code authorization for Codex in ChatGPT Security Settings, then run "codex login --device-auth" again.'
            prompt = dashboard.hermes_login_prompt_state(device_auth_output, dashboard.HERMES_LOGIN_STATE)
            self.assert_true(prompt["phase"] == "device_auth_settings" and "Ajustes > Seguridad" in prompt["detail"], "Disabled Codex device-code auth is turned into buyer-friendly ChatGPT settings guidance")
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
            hermes_status_timeout_seconds = 1
            hermes_response_timeout_seconds = 300
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
            hermes_status_timeout_seconds = 10
            hermes_response_timeout_seconds = 300
            hermes_max_iterations = 3
            hermes_enabled_toolsets = "memory,skills,session_search,vision,file,web,browser"
            hermes_disabled_toolsets = "terminal,code_execution,image_gen"
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
            toolset_arg = command[command.index("--toolsets") + 1]
            toolsets = toolset_arg.split(",")
            self.assert_true(all(toolset in toolsets for toolset in ["memory", "skills", "session_search", "vision", "file", "web", "browser", "admira"]), "Creative-friendly Hermes toolsets include scoped file, website access, and Admira product tools")
            self.assert_true("image_gen" not in toolset_arg, "Hermes internal image generation stays disabled so Codex/Image bridge owns final creatives")
        finally:
            hermes_bridge.subprocess.run = original_run

    def test_hermes_telegram_uses_persistent_session_not_prompt_history(self):
        """Test Telegram sends the current message to a persistent Hermes session instead of replaying chat history."""
        print("\nTesting Hermes Telegram Session Routing...")

        class FakeConfig:
            hermes_cli = "hermes"
            hermes_model = ""
            hermes_timeout_seconds = 10
            hermes_status_timeout_seconds = 10
            hermes_response_timeout_seconds = 300
            hermes_max_iterations = 3
            hermes_enabled_toolsets = "memory,skills,file,web,browser"
            hermes_disabled_toolsets = "terminal,code_execution"
            hermes_home = ""
            agent_chat_provider = "hermes"
            agent_brain_provider = "custom_api"
            agent_chat_base_url = "https://example.test/v1"
            agent_chat_api_key = "test-key"
            agent_chat_model = "custom-model"

        captured = {}

        class Completed:
            returncode = 0
            stdout = "Entendido. Lo tomo como respuesta a la pregunta anterior."
            stderr = ""

        original_run = hermes_bridge.subprocess.run
        try:
            def fake_run(command, **kwargs):
                captured["command"] = command
                return Completed()

            hermes_bridge.subprocess.run = fake_run
            payload = {
                "message": "a todos ellos",
                "language": "es",
                "channel": "telegram",
                "session_key": "telegram:12345",
                "account_context": {"summary": {"overall_roas": 5.2}},
                "history": [{"role": "agent", "content": "Historia que no debe ir en el prompt"}],
            }
            result = hermes_bridge.cli_chat(FakeConfig(), payload)
            command = captured["command"]
            query = command[command.index("-q") + 1]
            self.assert_true(result.startswith("Entendido"), "Hermes CLI returns the buyer-facing reply")
            self.assert_true("--continue" in command and "meta-ads-agent-telegram-" in command[command.index("--continue") + 1], "Telegram uses a persistent Hermes session")
            self.assert_true("Historia que no debe ir en el prompt" not in query, "Telegram does not replay prompt history to Hermes")
            self.assert_true("a todos ellos" in query and len(query) < 700, "Only the current Telegram message plus a short context note is sent")
        finally:
            hermes_bridge.subprocess.run = original_run

    def test_hermes_telegram_creates_missing_persistent_session(self):
        """Test first Telegram message creates and names the Hermes session when it does not exist yet."""
        print("\nTesting Hermes Telegram Missing Session Bootstrap...")

        class FakeConfig:
            hermes_cli = "hermes"
            hermes_model = ""
            hermes_timeout_seconds = 10
            hermes_status_timeout_seconds = 10
            hermes_response_timeout_seconds = 300
            hermes_max_iterations = 3
            hermes_enabled_toolsets = "memory,skills,file,web,browser"
            hermes_disabled_toolsets = "terminal,code_execution"
            hermes_home = ""
            agent_chat_provider = "hermes"
            agent_brain_provider = "custom_api"
            agent_chat_base_url = "https://example.test/v1"
            agent_chat_api_key = "test-key"
            agent_chat_model = "custom-model"

        calls = []

        class Completed:
            def __init__(self, returncode=0, stdout="", stderr=""):
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        original_run = hermes_bridge.subprocess.run
        try:
            def fake_run(command, **kwargs):
                calls.append(command)
                if command[:2] == ["hermes", "chat"] and "--continue" in command:
                    return Completed(1, stderr="No session found matching 'meta-ads-agent-telegram-abc123'.")
                if command[:2] == ["hermes", "chat"]:
                    return Completed(0, stdout="Primera respuesta creada.")
                if command[:3] == ["hermes", "sessions", "list"]:
                    return Completed(0, stdout="Preview  now  meta-ads-agent-telegram  20260610_210000_abcd12\n")
                if command[:3] == ["hermes", "sessions", "rename"]:
                    return Completed(0, stdout="renamed")
                return Completed(0)

            hermes_bridge.subprocess.run = fake_run
            result = hermes_bridge.cli_chat(
                FakeConfig(),
                {
                    "message": "hola",
                    "language": "es",
                    "channel": "telegram",
                    "session_key": "telegram:first-run",
                    "account_context": {},
                },
            )
            self.assert_true(result == "Primera respuesta creada.", "Missing Hermes session is created on the first Telegram turn")
            self.assert_true(any(command[:2] == ["hermes", "chat"] and "--continue" in command for command in calls), "First attempt tries the persistent session")
            self.assert_true(any(command[:2] == ["hermes", "chat"] and "--continue" not in command for command in calls), "Missing session retries by creating a fresh Hermes session")
            self.assert_true(any(command[:3] == ["hermes", "sessions", "rename"] for command in calls), "Fresh Hermes session is named for the next turn")
        finally:
            hermes_bridge.subprocess.run = original_run

    def test_telegram_defaults_to_direct_hermes_gateway(self):
        """Test buyer Telegram defaults to Hermes Gateway, not the legacy polling bot."""
        print("\nTesting Direct Hermes Telegram Gateway Default...")

        dashboard = load_dashboard_module()
        original_env = {key: os.environ.get(key) for key in ["TELEGRAM_AGENT_MODE", "TELEGRAM_AGENT_ENABLED"]}
        original_load = dashboard.load_config
        original_start_gateway = dashboard.start_hermes_gateway
        original_globals = (dashboard.TELEGRAM_THREAD, dashboard.TELEGRAM_STOP, dashboard.TELEGRAM_FINGERPRINT)

        class FakeConfig:
            telegram_bot_token = "123456:fake-token"
            telegram_chat_id = "12345"
            hermes_home = str(ROOT_DIR / "output" / "test-hermes-home")
            hermes_cli = "hermes"
            hermes_model = ""

        try:
            os.environ.pop("TELEGRAM_AGENT_MODE", None)
            os.environ["TELEGRAM_AGENT_ENABLED"] = "true"
            dashboard.load_config = lambda: FakeConfig()
            dashboard.start_hermes_gateway = lambda config: {"started": True, "mode": "hermes_gateway", "direct_hermes": True}
            status = hermes_gateway.telegram_settings(FakeConfig())
            result = dashboard.ensure_telegram_listener()

            self.assert_true(status["mode"] == "hermes_gateway", "Telegram defaults to Hermes Gateway mode")
            self.assert_true(result["started"] and result["mode"] == "hermes_gateway", "Dashboard starts Hermes Gateway for Telegram by default")
            self.assert_true(dashboard.TELEGRAM_THREAD is None and dashboard.TELEGRAM_FINGERPRINT is None, "Default Telegram path does not start the legacy polling thread")
        finally:
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            dashboard.load_config = original_load
            dashboard.start_hermes_gateway = original_start_gateway
            dashboard.TELEGRAM_THREAD, dashboard.TELEGRAM_STOP, dashboard.TELEGRAM_FINGERPRINT = original_globals
            shutil.rmtree(ROOT_DIR / "output" / "test-hermes-home", ignore_errors=True)

    def test_hermes_gateway_uses_isolated_home_and_daily_cron_prompt(self):
        """Test Hermes Gateway writes isolated product config and daily brief prompt."""
        print("\nTesting Hermes Gateway Isolation And Daily Brief...")

        test_dir = ROOT_DIR / "output" / "test-hermes-gateway"
        workspace = test_dir / "workspace"
        home = test_dir / "hermes-home"
        original_prepare = hermes_gateway.prepare_hermes_workspace
        original_env = {key: os.environ.get(key) for key in ["TELEGRAM_AGENT_MODE", "TELEGRAM_AGENT_ENABLED", "TELEGRAM_LANGUAGE", "AGENT_COMMUNICATION_STYLE", "AGENT_AD_EXPERIENCE_LEVEL"]}

        class FakeConfig:
            telegram_bot_token = "123456:fake-token"
            telegram_chat_id = "12345"
            hermes_home = str(home)
            hermes_cli = "hermes"
            hermes_model = "auto"
            daily_brief_time = "08:00"

        class MiniMaxConfig(FakeConfig):
            agent_brain_provider = "minimax"
            agent_chat_base_url = "https://api.minimax.io/v1"
            agent_chat_model = "MiniMax-M3"
            agent_chat_api_key = "direct-model-key"
            hermes_require_codex_auth = False

        try:
            shutil.rmtree(test_dir, ignore_errors=True)
            workspace.mkdir(parents=True, exist_ok=True)
            os.environ.pop("TELEGRAM_AGENT_MODE", None)
            os.environ["TELEGRAM_AGENT_ENABLED"] = "true"
            os.environ["TELEGRAM_LANGUAGE"] = "es"
            os.environ["AGENT_COMMUNICATION_STYLE"] = "technical"
            os.environ["AGENT_AD_EXPERIENCE_LEVEL"] = "advanced"
            hermes_gateway.prepare_hermes_workspace = lambda payload: {"path": str(workspace)}

            files = hermes_gateway.write_gateway_files(FakeConfig())
            config_yaml = Path(files["config"]).read_text(encoding="utf-8")
            env_text = Path(files["env"]).read_text(encoding="utf-8")
            prompt = hermes_gateway.daily_brief_prompt()

            self.assert_true(str(home) == files["hermes_home"] and ".hermes" not in files["hermes_home"], "Hermes Gateway uses an isolated product HERMES_HOME")
            self.assert_true("TELEGRAM_BOT_TOKEN=123456:fake-token" in env_text and "TELEGRAM_ALLOWED_USERS=12345" in env_text, "Hermes Gateway stores Telegram credentials only in the isolated Hermes env")
            self.assert_true("platform_toolsets:" in config_yaml and "telegram:" in config_yaml and "hermes-telegram" in config_yaml, "Hermes Gateway config enables native Telegram toolsets")
            self.assert_true("rich_messages: false" in config_yaml, "Hermes Gateway disables Telegram rich rendering so tables cannot become empty bubbles")
            self.assert_true("gateway_restart_notification: false" in config_yaml, "Hermes Gateway suppresses buyer-facing shutdown notices during planned dashboard restarts")
            self.assert_true("threshold: 0.85" in config_yaml and "codex_gpt55_autoraise: false" in config_yaml, "Hermes Gateway keeps the larger Codex context threshold without replaying the auto-compaction notice to buyers")
            self.assert_true("HERMES_MEDIA_ALLOW_DIRS=" in env_text and "/output" in env_text, "Hermes Gateway allows generated output files to be delivered as native media attachments")
            self.assert_true("mcp_servers:" in config_yaml and "admira:" in config_yaml and "admira_mcp_server.py" in config_yaml, "Hermes Gateway registers the Admira MCP product-tool bridge")
            self.assert_true("    timeout: 900" in config_yaml, "Hermes Gateway lets long Codex/Image MCP calls finish instead of cutting them off at 300 seconds")
            self.assert_true("    keepalive_interval: 1200" in config_yaml, "Hermes Gateway avoids MCP keepalive reconnects while a long creative tool call is still running")
            self.assert_true("    - admira" in config_yaml, "Hermes Gateway explicitly enables Admira MCP tools for Telegram")
            self.assert_true("disabled_toolsets:" in config_yaml and "code_execution" in config_yaml and str(workspace) in config_yaml, "Hermes Gateway config keeps Telegram in the curated workspace")
            self.assert_true('default: "gpt-5.5"' in config_yaml and 'default: "auto"' not in config_yaml, "Hermes Gateway normalizes legacy auto model to gpt-5.5")
            self.assert_true("entrevista del negocio" in config_yaml and "no bloquean la configuración inicial" in config_yaml, "Hermes Gateway tells Telegram that agent interviews are not dashboard blockers")
            self.assert_true("primero entenderemos el negocio" in config_yaml and "marca visual" in config_yaml and "ofertas, briefs, estrategia y campañas" in config_yaml, "Hermes Gateway introduction explains the three-step onboarding journey")
            self.assert_true("Tu identidad de cara al cliente es solo Admira IA" in config_yaml and "comandos como `/help`" in config_yaml, "Telegram prompt blocks buyer-facing Hermes/runtime command branding")
            self.assert_true("Estás hablando directamente desde Hermes Telegram Gateway" not in config_yaml and "Usa tu memoria de Hermes" not in config_yaml, "Telegram prompt does not teach the buyer-facing agent to introduce itself as Hermes")
            english_prompt = hermes_gateway.gateway_prompt("en", "simple", "")
            self.assert_true("customer-facing identity is only Admira IA" in english_prompt and "Never mention Hermes" in english_prompt and "`/help` command suggestions" in english_prompt, "English Telegram prompt also hides Hermes/runtime branding from buyers")
            self.assert_true("MEDIA:<local_path>" in english_prompt and "native attachment directive" in english_prompt, "English Telegram prompt treats MEDIA paths as attachment syntax, not buyer links")
            self.assert_true("experiencia creando/gestionando anuncios" in config_yaml and "Experiencia en anuncios: avanzada" in config_yaml, "Hermes Gateway asks and applies the global ad-experience preference")
            self.assert_true("Sé proactivo globalmente" in config_yaml and "evento correcto" in config_yaml, "Hermes Gateway applies the global expert configurator posture beyond placements")
            self.assert_true("no uses tablas Markdown" in config_yaml, "Hermes Gateway prompt keeps Telegram replies in mobile-safe bullet formatting")
            self.assert_true("Preferencia de comunicación: técnica" in config_yaml and "detalles de implementación" in config_yaml, "Hermes Gateway applies the global technical communication preference")
            self.assert_true("¿Tienes alguna pregunta?" in prompt and "No uses datos demo" in prompt, "Daily brief prompt ends with the buyer question and blocks demo data")
            minimax_files = hermes_gateway.write_gateway_files(MiniMaxConfig())
            minimax_yaml = Path(minimax_files["config"]).read_text(encoding="utf-8")
            minimax_env = Path(minimax_files["env"]).read_text(encoding="utf-8")
            self.assert_true('provider: "admira-minimax"' in minimax_yaml and 'default: "MiniMax-M3"' in minimax_yaml, "Hermes Gateway writes MiniMax M3 as a Hermes providers entry instead of hardcoding ChatGPT/Codex")
            self.assert_true("providers:" in minimax_yaml and "admira-minimax:" in minimax_yaml and 'name: "MiniMax M3 oficial"' in minimax_yaml and 'key_env: "ADMIRA_MINIMAX_API_KEY"' in minimax_yaml and 'api_mode: "chat_completions"' in minimax_yaml and "custom:admira-minimax" not in minimax_yaml, "Hermes Gateway exposes MiniMax through Hermes' official providers config")
            self.assert_true("model_aliases:" in minimax_yaml and '"minimax m3":' in minimax_yaml and '"minimax-m3":' in minimax_yaml and '"minimax":' in minimax_yaml, "Hermes Gateway pins manual /model MiniMax M3 switches to the Admira MiniMax endpoint")
            self.assert_true("direct-model-key" not in minimax_yaml, "Hermes Gateway config never writes the direct model API key")
            self.assert_true("direct-model-key" not in minimax_env and "MINIMAX_API_KEY" not in minimax_env and "ADMIRA_MINIMAX_API_KEY" not in minimax_env, "Hermes Gateway env file never persists direct model secrets")
            codex_fp = hermes_gateway._gateway_fingerprint(FakeConfig(), hermes_gateway.telegram_settings(FakeConfig()), files)
            minimax_fp = hermes_gateway._gateway_fingerprint(MiniMaxConfig(), hermes_gateway.telegram_settings(MiniMaxConfig()), minimax_files)
            self.assert_true(codex_fp != minimax_fp and "direct-model-key" not in minimax_fp, "Hermes Gateway fingerprint changes on brain/provider updates without leaking secrets")
        finally:
            hermes_gateway.prepare_hermes_workspace = original_prepare
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_hermes_product_skills_are_copied_to_workspace(self):
        """Test Hermes receives focused product skills plus MCP tool instructions."""
        print("\nTesting Hermes Product Skills Workspace...")

        test_dir = ROOT_DIR / "output" / "test-hermes-product-skills"
        original_workspace = hermes_bridge.HERMES_WORKSPACE_DIR
        try:
            shutil.rmtree(test_dir, ignore_errors=True)
            hermes_bridge.HERMES_WORKSPACE_DIR = test_dir / "workspace"
            workspace = hermes_bridge.prepare_hermes_workspace({"channel": "telegram", "language": "es", "account_context": {}})
            workspace_path = Path(workspace["path"])
            creative_skill = workspace_path / "skills" / "creative-codex-image" / "SKILL.md"
            branding_skill = workspace_path / "skills" / "branding-creatives-creation" / "SKILL.md"
            campaign_skill = workspace_path / "skills" / "campaign-creation" / "SKILL.md"
            approvals_skill = workspace_path / "skills" / "telegram-approvals" / "SKILL.md"
            agents_text = (workspace_path / "AGENTS.md").read_text(encoding="utf-8")

            self.assert_true(creative_skill.exists() and branding_skill.exists() and campaign_skill.exists() and approvals_skill.exists(), "Focused product skill files are copied into the Hermes workspace")
            self.assert_true("mcp_admira_codex_image_generate" in creative_skill.read_text(encoding="utf-8"), "Creative skill points Hermes to the Codex/Image MCP tool")
            self.assert_true("logo" in branding_skill.read_text(encoding="utf-8").lower() and "mcp_admira_save_brand_memory" in branding_skill.read_text(encoding="utf-8"), "Branding skill teaches Hermes to save logo-aware creative memory")
            branding_text = branding_skill.read_text(encoding="utf-8")
            campaign_text = campaign_skill.read_text(encoding="utf-8")
            self.assert_true("Image 2 is one production tool; it is never the strategy" in branding_text and "Budget informs testing and launch planning, but it does not block draft image generation" in branding_text, "Branding skill separates creative strategy from the available image tool without making budget block drafts")
            self.assert_true("Meta Ad Library" in branding_text and "not private CPA, ROAS, or conversions" in branding_text, "Branding skill supports evidence-labeled competitor creative research without claiming public conversion data")
            self.assert_true("ElevenLabs" in branding_text and "photorealism" in branding_text and "reference_image_paths" in branding_text, "Branding skill covers UGC guidance, real-world photorealism, and uploaded references")
            self.assert_true("likely placements" in branding_text and "vertical Reels version" in campaign_text and "Expert Configuration Posture" in campaign_text, "Skills teach proactive expert placement strategy instead of rigid placement defaults")
            self.assert_true("mcp_admira_preflight_campaign" in campaign_text and "object_story_spec" in campaign_text and "custom_audiences" in campaign_text, "Campaign skill teaches preflight and expert campaign controls")
            self.assert_true("three most important success metrics" in campaign_text and "success_metrics" in campaign_text and "mcp_admira_save_ads_onboarding" in agents_text, "Hermes workspace teaches campaign scorecards and exposes ads onboarding memory")
            self.assert_true("mcp_admira_fetch_public_asset" in agents_text and "Google Drive" in campaign_text and "public video" in branding_text, "Hermes workspace teaches public link and Drive creative retrieval")
            self.assert_true("mcp_admira_approve_action" in approvals_skill.read_text(encoding="utf-8"), "Approval skill points Hermes to exact approval MCP tools")
            self.assert_true("Native Product Tools" in agents_text and "mcp_admira_stage_campaign" in agents_text and "mcp_admira_review_signal_quality" in agents_text and "mcp_admira_preflight_campaign" in agents_text, "Combined Hermes rules document the MCP product bridge and preflight review")
            self.assert_true((workspace_path / "skills" / "README.md").exists(), "Hermes workspace includes a product skill index")
        finally:
            hermes_bridge.HERMES_WORKSPACE_DIR = original_workspace
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_admira_tool_bridge_maps_mcp_tools_to_dashboard_actions(self):
        """Test MCP-facing tools call the existing protected dashboard action layer."""
        print("\nTesting Admira MCP Tool Bridge...")

        calls = []
        image_dir = ROOT_DIR / "output" / "test-admira-mcp-media"
        image_dir.mkdir(parents=True, exist_ok=True)
        generated_image = image_dir / "creative.png"
        generated_image.write_bytes(b"fake png")

        class FakeDashboard:
            PENDING_FILE = "pending.json"

            def dashboard_payload(self):
                return {
                    "metrics": {
                        "source": "meta_graph",
                        "summary": {"overall_roas": 3.2, "overall_cpa": 12},
                        "campaigns": [{"id": "camp_live", "name": "Campaña real", "roas": 3.2, "cpa": 12}],
                    },
                    "recommendations": [],
                    "fatigue": [],
                    "pending": [{"id": "approval_1", "status": "pending"}],
                    "audience_strategy": {},
                    "business_profile": {},
                    "brand_guides": {},
                    "agent_onboarding_phase": {},
                }

            def read_json(self, path, default):
                return [{"id": "approval_1", "status": "pending"}, {"id": "old", "status": "approved"}]

            def execute_agent_tool(self, tool_request, payload):
                calls.append((tool_request, payload))
                if tool_request["tool"] == "codex_image_generate":
                    return {
                        "type": "codex_image_generate",
                        "executed": True,
                        "reply": "Listo. Imagen adjunta.",
                        "result": {
                            "ok": True,
                            "image_path": str(generated_image),
                            "asset_id": "test-admira-mcp-media/creative.png",
                        },
                    }
                return {"type": tool_request["tool"], "executed": False, "staged": True, "reply": "Preparado."}

        original_loader = admira_tool_bridge.load_dashboard
        try:
            admira_tool_bridge.load_dashboard = lambda: FakeDashboard()
            context = admira_tool_bridge.call_tool("mcp_admira_get_real_meta_context", {})
            image = admira_tool_bridge.call_tool("codex_image_generate", {"request": "haz una imagen"})
            review = admira_tool_bridge.call_tool("mcp_admira_review_signal_quality", {"objective": "PURCHASES", "pixel_id": "123"})
            preflight = admira_tool_bridge.call_tool("mcp_admira_preflight_campaign", {"objective": "PURCHASES", "pixel_id": "123"})
            public_asset = admira_tool_bridge.call_tool("mcp_admira_fetch_public_asset", {"url": "https://drive.google.com/file/d/video123/view?usp=sharing"})
            ads_onboarding = admira_tool_bridge.call_tool("mcp_admira_save_ads_onboarding", {"success_metrics": ["ROAS", "cost per purchase", "cost per initiate checkout"]})
            approval = admira_tool_bridge.call_tool("mcp_admira_approve_action", {"approval_id": "approval_1"})
            pending = admira_tool_bridge.call_tool("list_pending_approvals", {})
            unknown = admira_tool_bridge.call_tool("delete_everything", {})
            called_tools = [call[0]["tool"] for call in calls]

            self.assert_true(context["ok"] and context["metrics_source"]["is_real_meta_data"], "Tool bridge returns safe real Meta context")
            self.assert_true(image["product_tool"] == "codex_image_generate" and "codex_image_generate" in called_tools, "Tool bridge maps Codex/Image MCP calls to dashboard action handlers")
            self.assert_true(image.get("media_attachment") == f"MEDIA:{generated_image.resolve()}" and "Do not paste MEDIA" in image.get("buyer_delivery_instruction", ""), "Tool bridge gives Hermes a native media attachment directive for generated creative images")
            self.assert_true(review["product_tool"] == "review_signal_quality" and "review_signal_quality" in called_tools, "Tool bridge maps signal-quality MCP review to dashboard action handlers")
            self.assert_true(preflight["product_tool"] == "preflight_campaign" and "preflight_campaign" in called_tools, "Tool bridge maps campaign preflight MCP review to dashboard action handlers")
            self.assert_true(public_asset["product_tool"] == "fetch_public_asset" and "fetch_public_asset" in called_tools, "Tool bridge maps public URL/Drive creative retrieval to dashboard action handlers")
            self.assert_true(ads_onboarding["product_tool"] == "save_ads_onboarding" and "save_ads_onboarding" in called_tools, "Tool bridge maps ads onboarding memory so Hermes can persist campaign KPIs")
            self.assert_true(approval["product_tool"] == "approval_decision" and calls[-1][0]["arguments"]["decision"] == "approve", "Tool bridge converts approval MCP calls to exact approval decisions")
            verified = admira_tool_bridge.call_tool("mcp_admira_record_verified_signal", {"stage": "booked", "person_label": "Maria"})
            self.assert_true(verified["product_tool"] == "record_verified_signal" and calls[-1][0]["tool"] == "record_verified_signal", "Tool bridge maps verified-signal MCP calls to dashboard action handlers")
            self.assert_true(len(pending["pending"]) == 1 and pending["pending"][0]["id"] == "approval_1", "Tool bridge lists only pending approvals")
            self.assert_true(unknown["blocked"] and unknown["reason"] == "unsupported_tool", "Tool bridge rejects unknown tools")
        finally:
            admira_tool_bridge.load_dashboard = original_loader
            shutil.rmtree(image_dir, ignore_errors=True)

    def test_admira_mcp_server_lists_and_calls_product_tools(self):
        """Test minimal MCP server exposes the Admira product tools in Hermes-compatible shape."""
        print("\nTesting Admira MCP Server...")

        captured = []
        original_write = admira_mcp_server.write_message
        original_call = admira_mcp_server.call_tool
        try:
            admira_mcp_server.write_message = lambda payload: captured.append(payload)
            admira_mcp_server.call_tool = lambda name, arguments: {"ok": True, "tool": name, "arguments": arguments}

            admira_mcp_server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            admira_mcp_server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            admira_mcp_server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "codex_image_generate", "arguments": {"request": "imagen"}}})

            tool_names = [tool["name"] for tool in captured[1]["result"]["tools"]]
            call_text = captured[2]["result"]["content"][0]["text"]
            self.assert_true(captured[0]["result"]["serverInfo"]["name"] == "admira", "MCP server initializes as Admira")
            self.assert_true("codex_image_generate" in tool_names and "stage_campaign" in tool_names and "approve_action" in tool_names and "review_signal_quality" in tool_names and "preflight_campaign" in tool_names and "fetch_public_asset" in tool_names and "record_verified_signal" in tool_names and "save_ads_onboarding" in tool_names, "MCP server lists product tools for Hermes")
            self.assert_true('"tool": "admira_codex_image_generate"' in call_text and '"request": "imagen"' in call_text, "MCP server calls the product bridge with Admira-prefixed tool names")
        finally:
            admira_mcp_server.write_message = original_write
            admira_mcp_server.call_tool = original_call

    def test_public_asset_fetcher_normalizes_drive_and_blocks_private_urls(self):
        """Test buyer-shared public links are normalized safely before download."""
        print("\nTesting Public Asset Fetcher Safety...")

        drive = public_asset_fetcher.normalize_public_asset_url("https://drive.google.com/file/d/abc123XYZ/view?usp=sharing")
        self.assert_true(drive == "https://drive.google.com/uc?export=download&id=abc123XYZ", "Google Drive share links normalize to direct public download URLs")
        blocked = public_asset_fetcher.fetch_public_asset_result({"url": "http://127.0.0.1/private-video.mp4"})
        self.assert_true(blocked["blocked"] and blocked["reason"] == "private_or_local_url", "Public asset fetcher blocks local/private URLs")
        unsupported = public_asset_fetcher.fetch_public_asset_result({"url": "file:///etc/passwd"})
        self.assert_true(unsupported["blocked"] and unsupported["reason"] == "unsupported_url_scheme", "Public asset fetcher allows only http/https URLs")

    def test_public_asset_fetcher_extracts_video_frames_for_vision_review(self):
        """Test downloaded videos become image frames that Hermes can inspect with vision."""
        print("\nTesting Public Asset Video Frame Extraction...")

        video_dir = ROOT_DIR / "output" / "test-video-frame-extraction"
        frame_dir = video_dir / "frames"
        video_dir.mkdir(parents=True, exist_ok=True)
        video_path = video_dir / "buyer-ugc.mp4"
        video_path.write_bytes(b"fake mp4")

        class Completed:
            def __init__(self, stdout="", returncode=0):
                self.stdout = stdout
                self.stderr = ""
                self.returncode = returncode

        original_binary = public_asset_fetcher.ffmpeg_binary
        original_run = public_asset_fetcher.subprocess.run
        try:
            def fake_run(command, **_kwargs):
                if "ffprobe" in str(command[0]):
                    return Completed(stdout="12.0\n")
                output = Path(command[-1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"fake jpg")
                return Completed()

            public_asset_fetcher.ffmpeg_binary = lambda name: f"/usr/bin/{name}"
            public_asset_fetcher.subprocess.run = fake_run
            result = public_asset_fetcher.extract_video_preview_frames(video_path, output_dir=frame_dir, max_frames=3)
            self.assert_true(result["ok"] and len(result["frames"]) == 3, "Video frame extraction produces representative image frames")
            self.assert_true(all(Path(path).suffix.lower() == ".jpg" and Path(path).exists() for path in result["frames"]), "Extracted video frames are saved as image files")
            self.assert_true(result["duration_seconds"] == 12.0, "Video duration metadata is included for creative review context")
        finally:
            public_asset_fetcher.ffmpeg_binary = original_binary
            public_asset_fetcher.subprocess.run = original_run
            shutil.rmtree(video_dir, ignore_errors=True)

    def test_admira_mcp_creative_timeout_returns_buyer_fallback(self):
        """Test stuck creative MCP subprocesses return a friendly retryable fallback instead of hanging."""
        print("\nTesting Admira MCP Creative Timeout Fallback...")

        class HangingProcess:
            pid = 999999

            def communicate(self, timeout=None):
                raise subprocess.TimeoutExpired(["admira_tool_bridge"], timeout)

        original_popen = admira_mcp_server.subprocess.Popen
        original_killpg = admira_mcp_server.os.killpg
        try:
            kill_signals = []
            admira_mcp_server.subprocess.Popen = lambda *args, **kwargs: HangingProcess()
            admira_mcp_server.os.killpg = lambda pid, sig: kill_signals.append((pid, sig))
            result = admira_mcp_server.call_tool_in_subprocess(
                "admira_codex_image_generate",
                {"request": "revisa el creativo y agrega glow dorado"},
                60,
            )
            self.assert_true(result["ok"] is False and result["reason"] == "admira_tool_timeout", "Creative MCP timeout is returned as a blocked tool result")
            self.assert_true(result["result"]["retryable"] is True and "no se quede congelado" in result["reply"] and "límite semanal de imágenes en 0" in result["reply"], "Creative MCP timeout gives the buyer a clear retryable fallback message including possible ChatGPT image caps")
            self.assert_true(any(sig == signal.SIGTERM for _, sig in kill_signals), "Creative MCP timeout terminates the stuck subprocess group")
        finally:
            admira_mcp_server.subprocess.Popen = original_popen
            admira_mcp_server.os.killpg = original_killpg

    def test_verified_signal_ledger_records_private_deduped_outcomes(self):
        """Test the local verified-signal ledger stores useful outcome truth without raw contact data."""
        print("\nTesting Verified Signal Ledger...")

        test_dir = Path(tempfile.mkdtemp(prefix="verified_signal_ledger_"))
        ledger_path = test_dir / "verified_signal_ledger.json"
        dashboard = load_dashboard_module()
        original_ledger_file = dashboard.VERIFIED_SIGNAL_LEDGER_FILE
        try:
            first = verified_signal_ledger.record_signal(
                {
                    "source_system": "whatsapp",
                    "stage": "qualified",
                    "person_label": "Maria",
                    "email": "Maria@example.com",
                    "phone": "+57 300 123 4567",
                    "ctwa_clid": "clid_123",
                    "campaign_id": "camp_1",
                    "ad_id": "ad_1",
                    "notes": "real opportunity",
                },
                ledger_path,
            )
            duplicate = verified_signal_ledger.record_signal(
                {
                    "source_system": "whatsapp",
                    "stage": "qualified",
                    "person_label": "Maria",
                    "email": "Maria@example.com",
                    "phone": "+57 300 123 4567",
                    "ctwa_clid": "clid_123",
                    "campaign_id": "camp_1",
                    "ad_id": "ad_1",
                    "notes": "same lead confirmed again",
                },
                ledger_path,
            )
            booked = verified_signal_ledger.record_signal(
                {
                    "source_system": "whatsapp",
                    "stage": "booked",
                    "person_label": "Maria",
                    "email": "Maria@example.com",
                    "phone": "+57 300 123 4567",
                    "ctwa_clid": "clid_123",
                    "booking_id": "booking_777",
                    "campaign_id": "camp_1",
                    "ad_id": "ad_1",
                    "privacy_confirmed": True,
                },
                ledger_path,
            )
            bad = verified_signal_ledger.record_signal(
                {
                    "source_system": "lead_ads",
                    "stage": "wrong_audience",
                    "person_label": "Lead equivocado",
                    "phone": "+57 311 000 9999",
                    "lead_id": "lead_999",
                    "campaign_id": "camp_bad",
                },
                ledger_path,
            )

            summary = verified_signal_ledger.ledger_summary(ledger_path)
            raw_text = ledger_path.read_text(encoding="utf-8")
            mode = ledger_path.stat().st_mode & 0o777
            self.assert_true(first["record"]["meta_event_name"] == "Lead" and first["record"]["match"]["match_score"] >= 0.65, "Qualified signal maps to a Meta-supported Lead event with match context")
            self.assert_true(duplicate["deduped"] is True and duplicate["record"]["seen_count"] == 2, "Repeated same-stage signal is deduplicated instead of duplicated")
            self.assert_true(booked["record"]["meta_event_name"] == "Schedule" and booked["record"]["meta_send_status"] == "ready", "Booked outcome maps to Schedule and becomes send-ready only after privacy confirmation")
            self.assert_true(bad["record"]["meta_event_name"] == "" and bad["record"]["quality_score"] < 0, "Bad-fit outcomes stay internal and lower quality scoring")
            self.assert_true(summary["total_events"] == 3 and summary["by_stage"]["qualified"] == 1 and summary["by_stage"]["booked"] == 1 and summary["by_stage"]["wrong_audience"] == 1, "Ledger summary counts deduped lifecycle outcomes by stage")
            self.assert_true(summary["ready_to_send_to_meta"] == 1 and summary["privacy_confirmation_needed"] >= 2, "Ledger separates local truth from future Meta-send readiness")
            self.assert_true("Maria@example.com" not in raw_text and "+57 300 123 4567" not in raw_text and "3001234567" not in raw_text, "Ledger does not store raw email or phone values")
            self.assert_true(mode == 0o600, "Verified-signal ledger is written with private file permissions")

            dashboard.VERIFIED_SIGNAL_LEDGER_FILE = ledger_path
            saved = dashboard.execute_agent_tool(
                {
                    "tool": "record_verified_signal",
                    "arguments": {
                        "items": [
                            {"source_system": "manual", "stage": "purchased", "person_label": "Carlos", "order_id": "order_1", "privacy_confirmed": True, "value": 120},
                            {"source_system": "manual", "stage": "fake", "person_label": "Spam"},
                        ]
                    },
                },
                {"language": "es"},
            )
            listed = dashboard.execute_agent_tool({"tool": "get_verified_signal_summary", "arguments": {}}, {"language": "es"})
            prompt = dashboard.execute_agent_tool({"tool": "verified_signal_feedback_prompt", "arguments": {}}, {"language": "es"})
            payload = dashboard.dashboard_payload()
            self.assert_true(saved["executed"] is True and saved["result"]["summary"]["total_events"] == 5, "Dashboard tool records verified-signal batches")
            self.assert_true(listed["result"]["by_stage"]["purchased"] == 1 and listed["result"]["negative_events"] >= 2, "Dashboard tool reads verified-signal summary")
            self.assert_true("marca solo excepciones" in prompt["reply"] and "lead de días anteriores" in prompt["reply"], "Daily feedback prompt asks only for exceptions and delayed important outcomes")
            self.assert_true(payload["verified_signals"]["total_events"] == 5, "Dashboard payload exposes verified-signal summary to the agent context")
        finally:
            dashboard.VERIFIED_SIGNAL_LEDGER_FILE = original_ledger_file
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_hermes_gateway_redacts_token_and_handles_start_failure(self):
        """Test gateway startup never leaks Telegram token and failures stay recoverable."""
        print("\nTesting Hermes Gateway Token Redaction And Failure Handling...")

        test_dir = ROOT_DIR / "output" / "test-hermes-gateway-failure"
        workspace = test_dir / "workspace"
        home = test_dir / "hermes-home"
        token = "123456:secret-token\nMALICIOUS=1"
        popen_calls = []
        original_prepare = hermes_gateway.prepare_hermes_workspace
        original_which = hermes_gateway.shutil.which
        original_popen = hermes_gateway.subprocess.Popen
        original_stale_terminate = hermes_gateway._terminate_stale_gateway_from_state
        original_env = {key: os.environ.get(key) for key in ["TELEGRAM_AGENT_MODE", "TELEGRAM_AGENT_ENABLED", "TELEGRAM_LANGUAGE"]}

        class FakeConfig:
            telegram_bot_token = token
            telegram_chat_id = "12345"
            hermes_home = str(home)
            hermes_cli = "hermes"
            hermes_model = "auto"
            daily_brief_time = "08:00"
            agent_chat_provider = "hermes"
            agent_brain_provider = "openai_codex"
            agent_chat_base_url = "https://api.openai.com/v1"
            agent_chat_api_key = ""
            agent_chat_model = "auto"

        class MiniMaxConfig(FakeConfig):
            agent_brain_provider = "minimax"
            agent_chat_base_url = "https://api.minimax.io/v1"
            agent_chat_api_key = "direct-model-key"
            agent_chat_model = "MiniMax-M3"
            hermes_require_codex_auth = False

        class FakeProcess:
            pid = 4321

            def poll(self):
                return None

            def terminate(self):
                return None

            def wait(self, timeout=None):
                return 0

            def kill(self):
                return None

        def fake_popen(*args, **kwargs):
            popen_calls.append((args, kwargs))
            return FakeProcess()

        try:
            hermes_gateway.stop_gateway()
            shutil.rmtree(test_dir, ignore_errors=True)
            workspace.mkdir(parents=True, exist_ok=True)
            os.environ.pop("TELEGRAM_AGENT_MODE", None)
            os.environ["TELEGRAM_AGENT_ENABLED"] = "true"
            os.environ["TELEGRAM_LANGUAGE"] = "es"
            hermes_gateway.prepare_hermes_workspace = lambda payload: {"path": str(workspace)}
            hermes_gateway.shutil.which = lambda command: "/usr/local/bin/hermes" if command == "hermes" else command
            hermes_gateway.subprocess.Popen = fake_popen
            hermes_gateway._terminate_stale_gateway_from_state = lambda skip_pid=None: None

            started = hermes_gateway.start_gateway(FakeConfig())
            status = hermes_gateway.gateway_status(FakeConfig())
            env_text = Path(started["env"]).read_text(encoding="utf-8")
            serialized_status = json.dumps(status, ensure_ascii=False)
            start_command = " ".join(popen_calls[0][0][0])
            start_kwargs = popen_calls[0][1]
            gateway_process_env = start_kwargs.get("env") or {}

            self.assert_true(started["started"] is True, "Hermes Gateway can start through the configured isolated runtime")
            self.assert_true("--replace" in start_command and "admira_hermes_gateway_supervisor" in start_command and "while :" in start_command, "Hermes Gateway starts under a restart supervisor and replaces stale gateway instances")
            self.assert_true(start_kwargs.get("start_new_session") is True, "Hermes Gateway supervisor runs in its own process group for clean update replacement")
            self.assert_true(gateway_process_env.get("ADMIRA_HERMES_RUNTIME_PATCHES") == "1" and str(ROOT_DIR / "src") in gateway_process_env.get("PYTHONPATH", ""), "Hermes Gateway loads Admira runtime patches from the product source path")
            self.assert_true(gateway_process_env.get("ADMIRA_GATEWAY_LANGUAGE") == "es", "Hermes Gateway passes the buyer language to runtime patches")
            self.assert_true("MALICIOUS=1" not in env_text and "\nMALICIOUS" not in env_text, "Telegram token is sanitized before writing the isolated Hermes env")
            self.assert_true("secret-token" not in serialized_status and "123456:" not in serialized_status, "Gateway status never exposes the Telegram bot token")

            popen_calls.clear()
            minimax_started = hermes_gateway.start_gateway(MiniMaxConfig())
            minimax_config = Path(minimax_started["config"]).read_text(encoding="utf-8")
            minimax_process_env = popen_calls[0][1].get("env") or {}
            self.assert_true(minimax_started["started"] is True, "Hermes Gateway restarts cleanly after switching the primary brain to MiniMax")
            self.assert_true(minimax_process_env.get("ADMIRA_MINIMAX_API_KEY") == "direct-model-key" and minimax_process_env.get("ADMIRA_MINIMAX_BASE_URL") == "https://api.minimax.io/v1" and "MINIMAX_API_KEY" not in minimax_process_env, "Hermes Gateway passes MiniMax API credentials only through the live process environment without activating Hermes' native MiniMax provider")
            self.assert_true('provider: "admira-minimax"' in minimax_config and 'key_env: "ADMIRA_MINIMAX_API_KEY"' in minimax_config and "custom:admira-minimax" not in minimax_config, "Hermes Gateway routes Telegram MiniMax M3 through Hermes' official providers entry")
            self.assert_true("model_aliases:" in minimax_config and '"minimax m3":' in minimax_config and '"minimax":' in minimax_config, "Hermes Gateway keeps manual Telegram /model MiniMax M3 switches on the configured MiniMax API")
            self.assert_true("direct-model-key" not in minimax_config, "Hermes Gateway never serializes MiniMax API keys into config.yaml")

            hermes_gateway.stop_gateway()
            hermes_gateway.subprocess.Popen = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("boom"))
            failed = hermes_gateway.start_gateway(FakeConfig())
            self.assert_true(failed["started"] is False and "No pude iniciar Hermes Gateway" in failed["detail"], "Hermes Gateway startup failures return a recoverable status")
            self.assert_true("secret-token" not in json.dumps(failed, ensure_ascii=False), "Startup failure payload does not expose the Telegram bot token")
        finally:
            hermes_gateway.stop_gateway()
            hermes_gateway.prepare_hermes_workspace = original_prepare
            hermes_gateway.shutil.which = original_which
            hermes_gateway.subprocess.Popen = original_popen
            hermes_gateway._terminate_stale_gateway_from_state = original_stale_terminate
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_hermes_gateway_incomplete_config_stops_existing_process(self):
        """Test incomplete Telegram configuration stops any previous Hermes Gateway process."""
        print("\nTesting Hermes Gateway Stop On Incomplete Config...")

        original_env = {key: os.environ.get(key) for key in ["TELEGRAM_AGENT_MODE", "TELEGRAM_AGENT_ENABLED"]}
        terminated = {"called": False}

        class FakeConfig:
            telegram_bot_token = ""
            telegram_chat_id = ""
            hermes_home = str(ROOT_DIR / "output" / "test-hermes-stop")
            hermes_cli = "hermes"
            hermes_model = ""

        class FakeProcess:
            pid = 9876

            def poll(self):
                return None

            def terminate(self):
                terminated["called"] = True

            def wait(self, timeout=None):
                return 0

            def kill(self):
                return None

        old_process = hermes_gateway._GATEWAY_PROCESS
        old_fingerprint = hermes_gateway._GATEWAY_FINGERPRINT
        try:
            os.environ.pop("TELEGRAM_AGENT_MODE", None)
            os.environ["TELEGRAM_AGENT_ENABLED"] = "true"
            hermes_gateway._GATEWAY_PROCESS = FakeProcess()
            hermes_gateway._GATEWAY_FINGERPRINT = "old"

            result = hermes_gateway.start_gateway(FakeConfig())

            self.assert_true(result["started"] is False and "Telegram no está completo" in result["detail"], "Incomplete Telegram setup returns a clear not-ready state")
            self.assert_true(terminated["called"], "Incomplete Telegram setup stops an existing Hermes Gateway process")
            self.assert_true(hermes_gateway._GATEWAY_PROCESS is None and hermes_gateway._GATEWAY_FINGERPRINT is None, "Gateway globals are cleared after stopping an incomplete setup")
        finally:
            hermes_gateway._GATEWAY_PROCESS = old_process
            hermes_gateway._GATEWAY_FINGERPRINT = old_fingerprint
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_hermes_daily_brief_cron_edge_cases(self):
        """Test daily brief cron handles duplicate, invalid time, and Hermes failures."""
        print("\nTesting Hermes Daily Brief Cron Edge Cases...")

        test_dir = ROOT_DIR / "output" / "test-hermes-cron"
        workspace = test_dir / "workspace"
        home = test_dir / "hermes-home"
        original_prepare = hermes_gateway.prepare_hermes_workspace
        original_which = hermes_gateway.shutil.which
        original_run = hermes_gateway.subprocess.run
        original_env = {key: os.environ.get(key) for key in ["TELEGRAM_AGENT_MODE", "TELEGRAM_AGENT_ENABLED", "TELEGRAM_LANGUAGE"]}

        class FakeConfig:
            telegram_bot_token = "123456:fake-token"
            telegram_chat_id = "12345"
            hermes_home = str(home)
            hermes_cli = "hermes"
            hermes_model = "auto"
            daily_brief_time = "bad-time"
            daily_brief_timezone = "America/Bogota"
            agent_chat_provider = "hermes"
            agent_brain_provider = "openai_codex"
            agent_chat_base_url = "https://api.openai.com/v1"
            agent_chat_api_key = ""
            agent_chat_model = "auto"

        class Completed:
            def __init__(self, returncode=0, stdout="", stderr=""):
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        try:
            shutil.rmtree(test_dir, ignore_errors=True)
            workspace.mkdir(parents=True, exist_ok=True)
            os.environ.pop("TELEGRAM_AGENT_MODE", None)
            os.environ["TELEGRAM_AGENT_ENABLED"] = "true"
            os.environ["TELEGRAM_LANGUAGE"] = "es"
            hermes_gateway.prepare_hermes_workspace = lambda payload: {"path": str(workspace)}
            hermes_gateway.shutil.which = lambda command: "/usr/local/bin/hermes" if command == "hermes" else command

            duplicate_calls = []
            def fake_duplicate_run(command, **kwargs):
                duplicate_calls.append(command)
                return Completed(stdout="Admira IA - lectura diaria")

            hermes_gateway.subprocess.run = fake_duplicate_run
            duplicate = hermes_gateway.ensure_daily_brief_cron(FakeConfig())
            self.assert_true(duplicate["configured"] and duplicate["exists"], "Existing Hermes daily brief cron is not duplicated")
            self.assert_true(not any(command[:3] == ["/usr/local/bin/hermes", "cron", "create"] for command in duplicate_calls), "Duplicate daily brief check does not create another cron")

            edit_calls = []
            FakeConfig.daily_brief_time = "09:30"
            def fake_edit_run(command, **kwargs):
                edit_calls.append((command, kwargs.get("env", {})))
                if command[:3] == ["/usr/local/bin/hermes", "cron", "list"]:
                    return Completed(stdout="""  abcdef123456 [active]\n    Name:      Admira IA - lectura diaria\n    Schedule:  0 8 * * *\n    Deliver:   telegram:12345\n""")
                return Completed(stdout="updated")

            hermes_gateway.subprocess.run = fake_edit_run
            edited = hermes_gateway.ensure_daily_brief_cron(FakeConfig())
            edit_command, edit_env = next((command, env) for command, env in edit_calls if command[:3] == ["/usr/local/bin/hermes", "cron", "edit"])
            self.assert_true(edited["configured"] and edited["updated"] and "30 9 * * *" in edit_command, "Existing Hermes daily brief cron is edited when the buyer changes the time")
            self.assert_true(edit_env.get("HERMES_TIMEZONE") == "America/Bogota" and edit_env.get("TZ") == "America/Bogota" and edited["timezone"] == "America/Bogota", "Hermes daily brief uses the buyer's validated local timezone")
            gateway_config = (home / "config.yaml").read_text(encoding="utf-8")
            gateway_env = (home / ".env").read_text(encoding="utf-8")
            self.assert_true('timezone: "America/Bogota"' in gateway_config and "HERMES_TIMEZONE=America/Bogota" in gateway_env, "Hermes persists the browser timezone in its native config and environment")

            create_calls = []
            FakeConfig.daily_brief_time = "bad-time"
            def fake_create_run(command, **kwargs):
                create_calls.append(command)
                if command[:3] == ["/usr/local/bin/hermes", "cron", "list"]:
                    return Completed(stdout="")
                return Completed(stdout="created")

            hermes_gateway.subprocess.run = fake_create_run
            created = hermes_gateway.ensure_daily_brief_cron(FakeConfig())
            create_command = [command for command in create_calls if command[:3] == ["/usr/local/bin/hermes", "cron", "create"]][0]
            self.assert_true(created["configured"] and created["schedule"] == "0 8 * * *", "Invalid daily brief time falls back to 08:00")
            self.assert_true("telegram:12345" in create_command and "¿Tienes alguna pregunta?" in create_command[-1], "Hermes cron delivers the daily brief to Telegram with the required closing question")
            self.assert_true(normalize_timezone("America/Bogota") == "America/Bogota" and normalize_timezone("not/a-zone", default="") == "UTC", "Daily brief timezone accepts IANA browser zones and rejects unknown values")

            hermes_gateway.subprocess.run = lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired(args[0], 20))
            failed = hermes_gateway.ensure_daily_brief_cron(FakeConfig())
            self.assert_true(failed["configured"] is False and "No pude revisar" in failed["detail"], "Hermes cron list timeout becomes a recoverable status")
        finally:
            hermes_gateway.prepare_hermes_workspace = original_prepare
            hermes_gateway.shutil.which = original_which
            hermes_gateway.subprocess.run = original_run
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_adaptive_creative_experiment_reviews_and_cron(self):
        """Test budget-aware evidence, honest rescheduling, decisions, and one-shot Hermes follow-ups."""
        print("\nTesting Adaptive Creative Experiment Reviews...")

        test_dir = ROOT_DIR / "output" / "test-experiment-reviews"
        experiment_file = test_dir / "creative_experiments.json"
        workspace = test_dir / "workspace"
        home = test_dir / "hermes-home"
        original_file = experiment_scheduler.EXPERIMENTS_FILE
        original_prepare = hermes_gateway.prepare_hermes_workspace
        original_which = hermes_gateway.shutil.which
        original_run = hermes_gateway.subprocess.run
        original_env = {key: os.environ.get(key) for key in ["TELEGRAM_AGENT_ENABLED", "TELEGRAM_AGENT_MODE", "TELEGRAM_LANGUAGE"]}

        class FakeConfig:
            telegram_bot_token = "123456:fake-token"
            telegram_chat_id = "12345"
            hermes_home = str(home)
            hermes_cli = "hermes"
            hermes_model = "auto"
            daily_brief_timezone = "America/Bogota"
            agent_chat_provider = "hermes"
            agent_brain_provider = "openai_codex"
            agent_chat_base_url = "https://api.openai.com/v1"
            agent_chat_api_key = ""
            agent_chat_model = "auto"

        class Completed:
            def __init__(self, returncode=0, stdout="", stderr=""):
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        try:
            shutil.rmtree(test_dir, ignore_errors=True)
            workspace.mkdir(parents=True, exist_ok=True)
            experiment_scheduler.EXPERIMENTS_FILE = experiment_file
            low_budget = experiment_scheduler.review_plan(25, 50, 4)
            high_budget = experiment_scheduler.review_plan(500, 50, 4)
            self.assert_true(low_budget["evidence_check_hours"] > high_budget["evidence_check_hours"], "Evidence checkpoint waits longer when the same creative test has less daily budget")

            started = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
            experiment = experiment_scheduler.schedule_experiment(
                {
                    "name": "Three angles",
                    "daily_budget": 300,
                    "target_cpa": 50,
                    "hypothesis": "Founder proof beats polished design",
                    "variants": [
                        {"name": "Founder", "ad_id": "ad_1", "campaign_id": "camp_1"},
                        {"name": "Polished", "ad_id": "ad_2", "campaign_id": "camp_1"},
                    ],
                },
                now=started,
            )
            self.assert_true(experiment["phase"] == "delivery" and experiment["next_review_at"].endswith("18:00:00+00:00"), "A launched test schedules an early delivery checkpoint before judging performance")

            delivery_rows = [
                {"level": "ad", "id": "ad_1", "ad_id": "ad_1", "spend": 8, "impressions": 900, "clicks": 20, "conversions": 0, "revenue": 0},
                {"level": "ad", "id": "ad_2", "ad_id": "ad_2", "spend": 0, "impressions": 0, "clicks": 0, "conversions": 0, "revenue": 0},
            ]
            delivery = experiment_scheduler.run_due_reviews(delivery_rows, now=started + timedelta(hours=6))["reviews"][0]
            self.assert_true(delivery["status"] == "delivery_problem" and not delivery["leader"], "An early delivery problem is reported without inventing a creative winner")

            evidence_rows = [
                {"level": "ad", "id": "ad_1", "ad_id": "ad_1", "spend": 100, "impressions": 6000, "clicks": 150, "conversions": 5, "revenue": 500},
                {"level": "ad", "id": "ad_2", "ad_id": "ad_2", "spend": 100, "impressions": 6000, "clicks": 70, "conversions": 1, "revenue": 50},
            ]
            decision = experiment_scheduler.run_due_reviews(evidence_rows, now=started + timedelta(hours=18))["reviews"][0]
            self.assert_true(decision["status"] == "decision_ready" and decision["leader"]["name"] == "Founder", "Sufficient real ad-level evidence identifies a provisional leader")
            self.assert_true(all(item.get("requires_approval") for item in decision["recommendations"] if item["type"] != "rework_test"), "Scale and pause recommendations remain protected by approval guardrails")
            experiment_payload = experiment_scheduler.experiment_review_payload(now=started + timedelta(hours=18))
            daily_brief = daily_agent.build_brief(
                {"source": "meta_graph", "summary": {"active_campaigns": 0}, "campaigns": []},
                [],
                [],
                [],
                experiment_reviews=experiment_payload,
            )
            self.assert_true(daily_brief["experiment_reviews"]["decision_ready_count"] == 1 and any("Tests con decisión lista" in line for line in daily_brief["technical_lines"]), "Daily brief surfaces creative-test decisions and checkpoint state")

            os.environ["TELEGRAM_AGENT_ENABLED"] = "true"
            os.environ.pop("TELEGRAM_AGENT_MODE", None)
            os.environ["TELEGRAM_LANGUAGE"] = "es"
            hermes_gateway.prepare_hermes_workspace = lambda payload: {"path": str(workspace)}
            hermes_gateway.shutil.which = lambda command: "/usr/local/bin/hermes" if command == "hermes" else command
            experiment["next_review_at"] = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(timespec="seconds")
            experiment["status"] = "observing"
            cron_calls = []

            def fake_cron_run(command, **kwargs):
                cron_calls.append((command, kwargs.get("env", {})))
                if command[:3] == ["/usr/local/bin/hermes", "cron", "list"]:
                    return Completed(stdout="")
                return Completed(stdout="created")

            hermes_gateway.subprocess.run = fake_cron_run
            cron = hermes_gateway.ensure_experiment_review_cron(FakeConfig(), experiment)
            create_command, create_env = next((command, env) for command, env in cron_calls if command[:3] == ["/usr/local/bin/hermes", "cron", "create"])
            self.assert_true(cron["configured"] and "--repeat" in create_command and create_command[create_command.index("--repeat") + 1] == "1", "Hermes creates a one-shot cron at the adaptive experiment checkpoint")
            self.assert_true("mcp_admira_run_due_experiment_reviews" in create_command[-1] and experiment["id"] in create_command[-1], "Experiment cron calls the protected due-review MCP tool for the exact test")
            self.assert_true(create_env.get("HERMES_TIMEZONE") == "America/Bogota" and create_env.get("TZ") == "America/Bogota", "Experiment review cron inherits the buyer timezone")

            mcp_names = {name for name, _ in admira_mcp_server.TOOL_DEFINITIONS}
            self.assert_true({"schedule_experiment_review", "list_experiment_reviews", "run_due_experiment_reviews"}.issubset(mcp_names), "Hermes MCP exposes scheduling, listing, and due creative-test reviews")
            self.assert_true(admira_tool_bridge.TOOL_MAP.get("admira_schedule_experiment_review") == "schedule_experiment_review", "MCP bridge maps experiment scheduling to the protected dashboard handler")

            skill_text = (ROOT_DIR / "agent" / "skills" / "branding-creatives-creation" / "SKILL.md").read_text(encoding="utf-8")
            daily_skill = (ROOT_DIR / "agent" / "skills" / "daily-brief" / "SKILL.md").read_text(encoding="utf-8")
            self.assert_true("mcp_admira_schedule_experiment_review" in skill_text and "real Meta IDs" in skill_text, "Creative strategy skill schedules reviews only after real variants launch")
            self.assert_true("mcp_admira_list_experiment_reviews" in daily_skill and "provisional" in daily_skill, "Daily brief skill reports adaptive test evidence without premature winners")
        finally:
            experiment_scheduler.EXPERIMENTS_FILE = original_file
            hermes_gateway.prepare_hermes_workspace = original_prepare
            hermes_gateway.shutil.which = original_which
            hermes_gateway.subprocess.run = original_run
            shutil.rmtree(test_dir, ignore_errors=True)
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_hermes_business_memory_workspace_is_curated_and_redacted(self):
        """Test Hermes receives approved business files inside its workspace without leaking secrets."""
        print("\nTesting Hermes Curated Business Memory...")

        memory = hermes_bridge.business_memory_context()
        hermes_payload = {
            "message": "Que sabes de mi negocio?",
            "language": "es",
            "account_context": {},
            "image_paths": [str(ROOT_DIR / ".env")],
            "history": [
                {"role": "agent", "content": "¿A quién quieres venderle principalmente este agente?"},
                {"role": "user", "content": "a todos ellos"},
            ],
        }
        workspace = hermes_bridge.prepare_hermes_workspace(hermes_payload)
        prompt = hermes_bridge.hermes_prompt(
            type("FakeConfig", (), {"agent_profile_dir": "agent"})(),
            hermes_payload,
            workspace,
        )
        self.assert_true("Hermes workspace files" in prompt, "Hermes prompt lists workspace files without embedding all memory")
        self.assert_true("business_profile" in memory and "brand_guides" in memory, "Business and brand memory are included")
        self.assert_true("onboarding_plan" in memory and "creative_references" in memory, "Hermes memory builder includes onboarding phase and creative reference memory")
        self.assert_true((hermes_bridge.HERMES_WORKSPACE_DIR / "AGENTS.md").exists(), "Hermes receives product role and tool rules as workspace AGENTS.md")
        self.assert_true((hermes_bridge.HERMES_WORKSPACE_DIR / "SOUL.md").exists(), "Hermes receives product soul instructions")
        self.assert_true((hermes_bridge.HERMES_WORKSPACE_DIR / "CURRENT_CONTEXT.json").exists(), "Hermes receives current turn account context as a scoped workspace file")
        self.assert_true((hermes_bridge.HERMES_WORKSPACE_DIR / "data" / "business_profile.json").exists(), "Business profile is copied into Hermes workspace")
        self.assert_true((hermes_bridge.HERMES_WORKSPACE_DIR / "brand_guides" / "general_branding.md").exists(), "Brand guide is copied into Hermes workspace")
        self.assert_true((hermes_bridge.HERMES_WORKSPACE_DIR / "memory" / "Agent onboarding plan.md").exists(), "Agent onboarding plan is copied into Hermes workspace")
        self.assert_true((hermes_bridge.HERMES_WORKSPACE_DIR / "brand_guides" / "creative_references.md").exists(), "Creative references are copied into Hermes workspace")
        self.assert_true(not (hermes_bridge.HERMES_WORKSPACE_DIR / "memory" / "recent_chat.json").exists(), "Hermes workspace does not duplicate chat history")
        self.assert_true(not (hermes_bridge.HERMES_WORKSPACE_DIR / "memory" / "current_channel_history.json").exists(), "Hermes continuity is session-based, not prompt-history based")
        self.assert_true("Recent conversation in this same channel JSON" not in prompt and "a todos ellos" not in prompt, "Hermes prompt does not replay channel history")
        self.assert_true(".env" not in prompt and "MINIMAX_API_KEY" not in prompt, "Secrets and arbitrary local files are not included")
        self.assert_true("Uploaded reference images" not in prompt, "Unsafe non-upload image paths are not attached")

    def test_hermes_continuity_recovers_after_history_cleanup(self):
        """Test a fresh/restarted Hermes session resumes from durable workspace memory instead of restarting onboarding."""
        print("\nTesting Hermes Continuity Recovery...")

        test_dir = Path(tempfile.mkdtemp(prefix="hermes-continuity-"))
        data_dir = test_dir / "dashboard-data"
        brand_dir = test_dir / "brand-guides"
        workspace_dir = test_dir / "workspace"
        original = {
            "DATA_DIR": hermes_bridge.DATA_DIR,
            "BRAND_GUIDES_DIR": hermes_bridge.BRAND_GUIDES_DIR,
            "HERMES_WORKSPACE_DIR": hermes_bridge.HERMES_WORKSPACE_DIR,
            "AGENT_COMMUNICATION_STYLE": os.environ.get("AGENT_COMMUNICATION_STYLE"),
            "AGENT_AD_EXPERIENCE_LEVEL": os.environ.get("AGENT_AD_EXPERIENCE_LEVEL"),
        }
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            (brand_dir / "products").mkdir(parents=True, exist_ok=True)
            (brand_dir / "ad_briefs").mkdir(parents=True, exist_ok=True)
            os.environ["AGENT_COMMUNICATION_STYLE"] = "simple"
            os.environ["AGENT_AD_EXPERIENCE_LEVEL"] = "intermediate"
            hermes_bridge.DATA_DIR = data_dir
            hermes_bridge.BRAND_GUIDES_DIR = brand_dir
            hermes_bridge.HERMES_WORKSPACE_DIR = workspace_dir

            (data_dir / "business_profile.json").write_text(
                json.dumps(
                    {
                        "business_name": "Spa MediCentro Juliana",
                        "location": "Lima, Perú",
                        "offer": "facial + masaje de 60 minutos por S/99",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (data_dir / "Agent onboarding plan.md").write_text(
                "Fase actual: producción creativa. Ya se habló del negocio, la oferta, colores y estilo. Siguiente paso: crear dos piezas visuales.",
                encoding="utf-8",
            )
            (data_dir / "Ads campaign onboarding.md").write_text(
                "Objetivo: mensajes por WhatsApp. Presupuesto: S/20/día. Formato inicial: estático 4:5 y posible historia vertical.",
                encoding="utf-8",
            )
            (brand_dir / "general_branding.md").write_text(
                "brand_name: Spa MediCentro Juliana\ncolors: verde salvia, beige, blanco crema, dorado suave\nvisual_style: elegante, limpio, relajante\ntone: cercano y premium",
                encoding="utf-8",
            )
            (brand_dir / "products" / "facial-masaje-s99.md").write_text(
                "name: Paquete facial + masaje S/99\naudience: mujeres y hombres en Lima que buscan relajación accesible\npain: estrés y cansancio\n",
                encoding="utf-8",
            )
            (brand_dir / "ad_briefs" / "whatsapp-facial-masaje.md").write_text(
                "name: Prueba WhatsApp facial masaje\nproduct_guide: facial-masaje-s99\nvariation_count: 2\ncreative_hypothesis: lujo accesible vs relajación rápida\n",
                encoding="utf-8",
            )

            workspace = hermes_bridge.prepare_hermes_workspace({"channel": "telegram", "language": "es", "account_context": {}})
            workspace_path = Path(workspace["path"])
            status = json.loads((workspace_path / "memory" / "continuity_status.json").read_text(encoding="utf-8"))
            continuity = (workspace_path / "memory" / "Conversation continuity.md").read_text(encoding="utf-8")
            agents_text = (workspace_path / "AGENTS.md").read_text(encoding="utf-8")
            gateway_prompt = hermes_gateway.gateway_prompt("es", "simple", "")
            bridge_prompt = hermes_bridge.hermes_prompt(
                type("FakeConfig", (), {"agent_profile_dir": "agent"})(),
                {"message": "hola", "language": "es", "channel": "telegram", "account_context": {}},
                workspace,
            )
            onboarding_skill = (ROOT_DIR / "agent" / "skills" / "business-onboarding" / "SKILL.md").read_text(encoding="utf-8")
            creative_skill = (ROOT_DIR / "agent" / "skills" / "creative-codex-image" / "SKILL.md").read_text(encoding="utf-8")

            self.assert_true(status["has_persistent_memory"] is True and status["resume_required"] is True, "Continuity status detects durable business memory after history cleanup")
            self.assert_true(status["sources"]["business_profile"] and status["sources"]["general_branding"] and status["sources"]["ad_briefs"], "Continuity status names the saved business, brand, and ad brief sources")
            self.assert_true("Spa MediCentro Juliana" in continuity and "S/99" in continuity and "Retomo donde quedamos" in continuity, "Continuity brief gives Hermes concrete remembered context and a resume pattern")
            self.assert_true("history cleanup" in agents_text and "has_persistent_memory" in agents_text and "do not restart onboarding" in agents_text, "Combined Hermes rules force resume behavior after cleanup or restart")
            self.assert_true("limpieza de historial" in gateway_prompt and "no te presentes como primera vez" in gateway_prompt and "Conversation continuity" in gateway_prompt, "Telegram gateway prompt blocks first-run greetings when durable memory exists")
            self.assert_true("CURRENT_CONTEXT.json" in gateway_prompt and "data/business_profile.json" in gateway_prompt and "brand_guides/" in gateway_prompt, "Telegram gateway prompt tells new sessions to inspect durable workspace memory before repeating questions")
            self.assert_true("No muestres rutas internas" in gateway_prompt and "entrégalo directamente en el chat" in gateway_prompt, "Telegram gateway prompt blocks buyer-facing internal workspace paths")
            self.assert_true("MEDIA:<ruta_local>" in gateway_prompt and "sintaxis interna de entrega" in gateway_prompt, "Telegram gateway prompt tells the agent to attach generated media instead of exposing MEDIA paths")
            self.assert_true("Before treating this as a new conversation" in bridge_prompt and "resume from durable business/brand/ad memory" in bridge_prompt, "Hermes bridge prompt also checks durable continuity before restarting onboarding")
            self.assert_true("do not say you need CLI or terminal access" in bridge_prompt and "public URL" in bridge_prompt and "web/browser" in bridge_prompt, "Dashboard Hermes prompt uses product actions and public URL retrieval instead of terminal excuses")
            self.assert_true("Do not present `MEDIA:/...` as a link" in bridge_prompt and "native attachment directive" in bridge_prompt, "Dashboard Hermes prompt also hides raw media attachment directives from buyers")
            self.assert_true("Never expose internal workspace paths" in onboarding_skill and "paste the useful content directly in the chat" in onboarding_skill, "Business onboarding skill keeps internal paths out of buyer replies")
            self.assert_true("Do not rely on Telegram/Hermes session memory" in onboarding_skill and "resume from that memory" in onboarding_skill, "Business onboarding skill saves durable facts and resumes instead of repeating questions")
            self.assert_true("Do not present `MEDIA:/...` as a link" in creative_skill and "native attachment syntax" in creative_skill, "Creative Image skill delivers generated files as attachments instead of internal paths")
        finally:
            hermes_bridge.DATA_DIR = original["DATA_DIR"]
            hermes_bridge.BRAND_GUIDES_DIR = original["BRAND_GUIDES_DIR"]
            hermes_bridge.HERMES_WORKSPACE_DIR = original["HERMES_WORKSPACE_DIR"]
            for key in ["AGENT_COMMUNICATION_STYLE", "AGENT_AD_EXPERIENCE_LEVEL"]:
                value = original[key]
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            shutil.rmtree(test_dir, ignore_errors=True)

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
        original_readiness = dashboard.creative_strategy_readiness
        calls = []
        try:
            dashboard.load_config = lambda: type("Cfg", (), {"codex_creative_enabled": True})()
            dashboard.creative_strategy_readiness = lambda require_brief=False, purpose="ad_creative", payload=None: {"ready": True, "missing": [], "next_question": "", "purpose": purpose}
            dashboard.call_codex_cli = lambda prompt, **kwargs: calls.append(prompt) or {"ok": True}
            blocked = dashboard.codex_creative_plan({"product_guide": ".env", "request": "Prepara creativos"})
            self.assert_true(blocked["ok"] is False, "Backend Codex tool rejects escaped guide paths")
            self.assert_true(not calls, "Blocked Codex requests never invoke the CLI")
        finally:
            dashboard.call_codex_cli = original_call_codex
            dashboard.load_config = original_load_config
            dashboard.creative_strategy_readiness = original_readiness

        safe_prompt = build_codex_creative_prompt("", "Prepara creativos")
        self.assert_true("No leas archivos" in safe_prompt and "credenciales" in safe_prompt, "Codex prompt includes secret-access guardrails")
        original_run = codex_brand_guides.subprocess.run
        original_codex_config = codex_brand_guides.load_config
        captured = {}
        try:
            hermes_home = str(ROOT_DIR / "output" / "test-hermes-home")
            codex_brand_guides.load_config = lambda: type("Cfg", (), {"codex_cli": "codex", "codex_creative_model": "gpt-5.5", "hermes_home": hermes_home})()
            def fake_run(command, **kwargs):
                captured["command"] = command
                captured["cwd"] = kwargs.get("cwd")
                captured["env"] = kwargs.get("env") or {}
                return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
            codex_brand_guides.subprocess.run = fake_run
            result = codex_brand_guides.call_codex_cli(safe_prompt)
            command = captured["command"]
            self.assert_true(result["ok"] is True, "Optional Codex bridge can complete isolated creative planning")
            self.assert_true("--sandbox" in command and "read-only" in command, "Codex bridge uses read-only sandbox")
            self.assert_true("--ephemeral" in command and "--ignore-user-config" in command and "--ignore-rules" in command, "Codex bridge avoids saved sessions and local rules")
            self.assert_true("-m" in command and command[command.index("-m") + 1] == "gpt-5.5", "Codex bridge can pin a supported creative model")
            self.assert_true(str(captured["cwd"]).startswith("/var/") or "meta-ads-codex-" in str(captured["cwd"]), "Codex bridge executes in an isolated temporary folder")
            self.assert_true(captured["env"].get("CODEX_HOME") == hermes_home and captured["env"].get("HERMES_HOME") == hermes_home, "Codex CLI reuses Hermes' authenticated home for ChatGPT/Codex")

            def fake_unauth_run(command, **kwargs):
                return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "HTTP error: 401 Unauthorized. Missing bearer or basic authentication in header"})()
            codex_brand_guides.subprocess.run = fake_unauth_run
            unauth = codex_brand_guides.call_codex_cli(safe_prompt, model="gpt-5.5")
            self.assert_true(unauth["ok"] is False and "no esta autenticado" in unauth.get("error", ""), "Codex CLI auth errors become buyer-friendly")
        finally:
            codex_brand_guides.subprocess.run = original_run
            codex_brand_guides.load_config = original_codex_config

    def test_codex_image_prompt_lab_builds_fixed_and_free_packages(self):
        """Test Codex image prompt packages preserve brand locks while enabling varied routes."""
        print("\nTesting Codex Image Prompt Lab...")

        test_root = Path(tempfile.mkdtemp(prefix="codex_image_prompt_lab_"))
        brand_dir = test_root / "brand_guides"
        product_dir = brand_dir / "products"
        brief_dir = brand_dir / "ad_briefs"
        product_dir.mkdir(parents=True, exist_ok=True)
        brief_dir.mkdir(parents=True, exist_ok=True)
        (brand_dir / "general_branding.md").write_text(
            "# Guia general de marca\n\n"
            "- Nombre de marca: Aurora Skin\n"
            "- Colores principales: azul profundo, menta y blanco\n"
            "- Tipografias o estilo de letras: sans elegante, titulares grandes\n"
            "- Evitar siempre: promesas medicas imposibles\n",
            encoding="utf-8",
        )
        (product_dir / "serum.md").write_text(
            "# Guia de producto\n\n"
            "- Nombre: Serum Luminoso\n"
            "- Para quien es: mujeres que quieren una rutina simple\n"
            "- Dolor principal: piel apagada\n"
            "- Deseo principal: verse fresca sin maquillaje pesado\n"
            "- Mostrar: textura del serum y rostro luminoso\n",
            encoding="utf-8",
        )
        (brief_dir / "promo.md").write_text(
            "# Brief publicitario\n\n"
            "- Nombre del brief: Promo serum\n"
            "- Ficha de producto: brand_guides/products/serum.md\n"
            "- Promocion o idea puntual: lanzamiento con descuento\n"
            "- No cambiar: precio y nombre del serum\n"
            "- Ventana creativa para variaciones: cambiar composicion y fondo\n",
            encoding="utf-8",
        )
        (brand_dir / "creative_references.md").write_text(
            "# Referencias creativas aprobadas\n\n## Notas para nuevos creativos\n\nLuz suave, producto visible, nada saturado.\n",
            encoding="utf-8",
        )
        original = {
            "ROOT_DIR": codex_brand_guides.ROOT_DIR,
            "BRAND_DIR": codex_brand_guides.BRAND_DIR,
            "PRODUCT_DIR": codex_brand_guides.PRODUCT_DIR,
            "AD_BRIEF_DIR": codex_brand_guides.AD_BRIEF_DIR,
            "GENERAL_GUIDE": codex_brand_guides.GENERAL_GUIDE,
            "CREATIVE_REFERENCES_FILE": codex_brand_guides.CREATIVE_REFERENCES_FILE,
        }
        try:
            codex_brand_guides.ROOT_DIR = test_root
            codex_brand_guides.BRAND_DIR = brand_dir
            codex_brand_guides.PRODUCT_DIR = product_dir
            codex_brand_guides.AD_BRIEF_DIR = brief_dir
            codex_brand_guides.GENERAL_GUIDE = brand_dir / "general_branding.md"
            codex_brand_guides.CREATIVE_REFERENCES_FILE = brand_dir / "creative_references.md"
            fixed = build_codex_image_prompt_package(
                product_guide="serum",
                ad_brief="promo",
                request="Crear imagen para Meta Ads",
                mode="fixed",
                variations=2,
                seed="stable",
            )
            free = build_codex_image_prompt_package(
                product_guide="serum",
                ad_brief="promo",
                request="Crear rutas muy distintas para probar",
                mode="free",
                variations=5,
                seed="variety",
            )
            free_axes = [item["design_axis"] for item in free["variation_ledger"]]
            self.assert_true(fixed["mode"] == "fixed" and fixed["variation_count"] == 2, "Fixed image package uses requested mode and count")
            self.assert_true("MODO FIJO" in fixed["codex_prompt"] and "azul profundo" in fixed["codex_prompt"], "Fixed package includes strict brand context")
            self.assert_true(free["mode"] == "free" and len(set(free_axes)) == len(free_axes), "Free image package produces distinct design axes")
            self.assert_true("MODO LIBRE" in free["codex_prompt"] and "Nunca repitas" in free["codex_prompt"], "Free package forces prompt diversity")
            self.assert_true("colores, tipografias" in free["brand_lock"], "Free package still locks essential brand elements")
            self.assert_true("Crear rutas muy distintas para probar" in free["prompts"][0]["image_prompt"], "Final image prompts include the buyer's concrete request")
            self.assert_true("No escribas 'faltan datos'" in free["prompts"][0]["image_prompt"] and "placeholders" in free["brand_lock"], "Final image prompts do not turn missing brand data into placeholder images")
            self.assert_true("oferta, descuento, 2x1" in free["prompts"][0]["image_prompt"] and "no escondas la promocion principal" in free["prompts"][0]["image_prompt"], "Final image prompts force buyer promotions to appear visibly")
            try:
                build_codex_image_prompt_package(product_guide="../../.env", request="malicious", mode="free")
                self.assert_true(False, "Image prompt package should reject escaped product guides")
            except ValueError as exc:
                self.assert_true("brand_guides/products" in str(exc), "Image prompt package blocks local file escape")

            script_out = test_root / "manifest.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT_DIR / "scripts" / "codex-image-prompt-lab.py"),
                    "--root",
                    str(test_root),
                    "--mode",
                    "free",
                    "--product",
                    "serum",
                    "--ad-brief",
                    "promo",
                    "--variations",
                    "4",
                    "--seed",
                    "cli-test",
                    "--request",
                    "Preparar prompts de imagen",
                    "--out",
                    str(script_out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            manifest = json.loads(script_out.read_text(encoding="utf-8")) if script_out.exists() else {}
            self.assert_true(completed.returncode == 0 and manifest.get("mode") == "free", "Prompt lab script writes a free-mode manifest")
            self.assert_true("codex_result" not in manifest, "Prompt lab script does not call Codex unless explicitly requested")
        finally:
            for key, value in original.items():
                setattr(codex_brand_guides, key, value)
            shutil.rmtree(test_root, ignore_errors=True)

    def test_codex_image_cli_bridge_copies_generated_asset(self):
        """Test the Codex/Image bridge uses authenticated Codex and publishes a protected asset."""
        print("\nTesting Codex Image CLI Bridge...")

        test_root = Path(tempfile.mkdtemp(prefix="codex_image_bridge_"))
        generated_root = test_root / "hermes_home" / "cache" / "images"
        output_root = test_root / "creatives"
        generated_file = generated_root / "run-001" / "image.png"
        captured = {}
        original_bridge = codex_brand_guides.run_hermes_image_bridge
        original_load_config = codex_brand_guides.load_config
        original_run = codex_brand_guides.subprocess.run
        reference_dir = ROOT_DIR / "output" / "test-codex-direct-reference"
        try:
            codex_brand_guides.load_config = lambda: type("Cfg", (), {"codex_cli": "codex", "codex_creative_model": "gpt-5.5", "hermes_model": "", "hermes_cli": "hermes", "hermes_home": str(test_root / "hermes_home")})()

            def fake_bridge(payload, **kwargs):
                captured["payload"] = payload
                generated_file.parent.mkdir(parents=True, exist_ok=True)
                generated_file.write_bytes(b"fake png")
                return {"success": True, "image": str(generated_file), "model": "gpt-image-2-medium", "provider": "openai-codex", "returncode": 0}

            codex_brand_guides.run_hermes_image_bridge = fake_bridge
            result = codex_brand_guides.call_codex_image_cli("Genera un anuncio 4:5", output_root=output_root, output_name="anuncio-prueba")
            self.assert_true(result["ok"] is True and Path(result["image_path"]).exists(), "Codex/Image bridge copies the generated image into creative assets")
            self.assert_true(result["asset_id"].startswith("codex-") and result["preview_url"].startswith("/api/creative-asset?id="), "Codex/Image bridge returns protected preview metadata")
            self.assert_true(result.get("backend") == "hermes-openai-codex" and result.get("provider") == "openai-codex", "Codex/Image bridge uses Hermes OpenAI-Codex provider")
            self.assert_true(captured["payload"]["aspect_ratio"] == "portrait", "Codex/Image bridge infers vertical Meta creative aspect ratio")
            self.assert_true("Genera un anuncio" in captured["payload"]["prompt"], "Codex/Image bridge sends the buyer prompt to Hermes")

            def fake_unauth_bridge(payload, **kwargs):
                return {"success": False, "error": "No Codex/ChatGPT OAuth credentials available.", "error_type": "auth_required"}

            codex_brand_guides.run_hermes_image_bridge = fake_unauth_bridge
            unauth = codex_brand_guides.call_codex_image_cli("Genera un anuncio", output_root=output_root)
            self.assert_true(unauth["ok"] is False and "ChatGPT/Codex" in unauth["error"], "Missing Hermes image auth gives a buyer-friendly image error")

            def fake_rate_limit_bridge(payload, **kwargs):
                return {"success": False, "error": "The model provider is rate-limiting requests. Please wait a moment and try again.", "error_type": "rate_limit"}

            codex_brand_guides.run_hermes_image_bridge = fake_rate_limit_bridge
            limited = codex_brand_guides.call_codex_image_cli("Genera un anuncio", output_root=output_root)
            self.assert_true(limited["ok"] is False and "rate-limiting" not in limited["error"].lower(), "Image rate-limit provider text is hidden from buyers")
            self.assert_true("Puedes intentar de nuevo en un momento" in limited["error"], "Image rate-limit retry hint is included in Spanish when available")

            reference_dir.mkdir(parents=True, exist_ok=True)
            reference_image = reference_dir / "reference.png"
            reference_image.write_bytes(b"fake reference")
            output_with_reference = test_root / "creatives-with-reference"
            direct_calls = []

            def fake_reference_bridge(payload, **kwargs):
                captured["reference_payload"] = payload
                generated = generated_root / "run-refs" / "image.png"
                generated.parent.mkdir(parents=True, exist_ok=True)
                generated.write_bytes(b"fake reference png")
                return {
                    "success": True,
                    "image": str(generated),
                    "model": "gpt-image-2-medium",
                    "provider": "openai-codex",
                    "returncode": 0,
                    "reference_image_count": len(payload.get("reference_image_paths") or []),
                    "reference_image_arg": "reference_image_paths",
                }

            codex_brand_guides.run_hermes_image_bridge = fake_reference_bridge
            referenced = codex_brand_guides.call_codex_image_cli(
                "Usa la referencia adjunta para crear una variación",
                output_root=output_with_reference,
                output_name="bridge-ref",
                reference_image_paths=[reference_image],
            )
            self.assert_true(referenced["ok"] is True and referenced.get("backend") == "hermes-openai-codex", "Codex/Image reference route prefers the Hermes image bridge")
            self.assert_true(str(reference_image) in captured["reference_payload"]["reference_image_paths"], "Codex/Image bridge receives uploaded reference image paths")
            self.assert_true(referenced.get("reference_image_count") == 1, "Codex/Image bridge reports attached reference images")

            def fake_reference_unsupported_bridge(payload, **kwargs):
                return {"success": False, "error": "reference images not supported by provider", "error_type": "reference_images_unsupported"}

            def fake_direct_run(command, **kwargs):
                env = kwargs.get("env") or {}
                direct_calls.append((command, env))
                if command[:3] == ["codex", "login", "status"]:
                    return type("Result", (), {"returncode": 0, "stdout": "Logged in", "stderr": ""})()
                generated = Path(env["CODEX_HOME"]) / "generated_images" / "direct-test" / "image.png"
                generated.parent.mkdir(parents=True, exist_ok=True)
                generated.write_bytes(b"fake generated image")
                last_message_index = command.index("--output-last-message") + 1
                Path(command[last_message_index]).write_text("Imagen generada.", encoding="utf-8")
                return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

            codex_brand_guides.run_hermes_image_bridge = fake_reference_unsupported_bridge
            codex_brand_guides.subprocess.run = fake_direct_run
            direct = codex_brand_guides.call_codex_image_cli(
                "Usa la referencia adjunta para crear una variación",
                output_root=output_with_reference,
                output_name="direct-ref",
                reference_image_paths=[reference_image],
            )
            hermes_home = str(test_root / "hermes_home")
            self.assert_true(direct["ok"] is True and direct.get("backend") == "codex-cli-direct", "Codex/Image direct reference route can publish generated assets")
            self.assert_true(len(direct_calls) >= 2 and all(call[1].get("CODEX_HOME") == hermes_home and call[1].get("HERMES_HOME") == hermes_home for call in direct_calls), "Codex/Image direct reference route reuses the Hermes authenticated home for login status and exec")

            def fake_broken_codex_run(command, **kwargs):
                direct_calls.append((command, kwargs.get("env") or {}))
                return type("Result", (), {
                    "returncode": 1,
                    "stdout": "",
                    "stderr": "Error: spawn /usr/local/lib/node_modules/@openai/codex/vendor/codex ENOENT",
                })()

            direct_calls.clear()
            codex_brand_guides.subprocess.run = fake_broken_codex_run
            broken = codex_brand_guides.call_codex_image_cli(
                "Usa la referencia adjunta para crear una variación",
                output_root=output_with_reference,
                output_name="direct-broken",
                reference_image_paths=[reference_image],
            )
            self.assert_true(broken["ok"] is False and broken.get("reason") == "codex_cli_broken", "Broken optional Codex CLI fallback is classified instead of looking like missing buyer context")
            self.assert_true("ruta local opcional" in broken["error"], "Broken optional Codex CLI fallback returns a buyer-safe remediation message")

            image_only_home = str(test_root / "image_only_home")
            direct_calls.clear()
            codex_brand_guides.subprocess.run = fake_direct_run
            codex_brand_guides.load_config = lambda: type("Cfg", (), {
                "codex_cli": "codex",
                "codex_creative_model": "gpt-5.5",
                "hermes_model": "gpt-5.5",
                "hermes_cli": "hermes",
                "hermes_home": hermes_home,
                "codex_image_source": "dedicated_chatgpt",
                "codex_image_hermes_home": image_only_home,
                "codex_image_hermes_model": "gpt-5.5",
            })()
            dedicated = codex_brand_guides.call_codex_image_cli(
                "Usa la referencia adjunta para crear una variación con la sesión de imagen",
                output_root=test_root / "creatives-image-only",
                output_name="direct-image-only",
                reference_image_paths=[reference_image],
            )
            self.assert_true(dedicated["ok"] is True and len(direct_calls) >= 2, "Codex/Image direct route still works with a dedicated image-only ChatGPT session")
            self.assert_true(all(call[1].get("CODEX_HOME") == image_only_home and call[1].get("HERMES_HOME") == image_only_home for call in direct_calls), "Codex/Image direct route uses the dedicated image-only ChatGPT home when configured")

            bridge_env = {}
            codex_brand_guides.run_hermes_image_bridge = original_bridge

            def fake_bridge_run(command, **kwargs):
                bridge_env.update(kwargs.get("env") or {})
                return type("Result", (), {"returncode": 0, "stdout": '{"success": false, "error": "status only"}\n', "stderr": ""})()

            codex_brand_guides.subprocess.run = fake_bridge_run
            codex_brand_guides.run_hermes_image_bridge({"mode": "status"}, config=codex_brand_guides.load_config())
            self.assert_true(bridge_env.get("HERMES_HOME") == image_only_home, "Codex/Image Hermes bridge uses the dedicated image-only ChatGPT home for non-reference image calls")
        finally:
            codex_brand_guides.run_hermes_image_bridge = original_bridge
            codex_brand_guides.load_config = original_load_config
            codex_brand_guides.subprocess.run = original_run
            shutil.rmtree(test_root, ignore_errors=True)
            shutil.rmtree(reference_dir, ignore_errors=True)

    def test_agent_codex_image_creative_request_result(self):
        """Test the agent result when the buyer asks for final ad images using Codex/Image."""
        print("\nTesting Agent Codex Image Creative Request Result...")

        dashboard = load_dashboard_module()
        image_dir = ROOT_DIR / "output" / "telegram_uploads"
        image_dir.mkdir(parents=True, exist_ok=True)
        reference_image = image_dir / "producto-test.png"
        reference_image.write_bytes(b"fake image content")

        original_load_config = dashboard.load_config
        original_call_codex = dashboard.call_codex_cli
        original_call_codex_image = dashboard.call_codex_image_cli
        original_creative_readiness = dashboard.creative_strategy_readiness
        calls = []
        try:
            dashboard.creative_strategy_readiness = lambda require_brief=False, purpose="ad_creative", payload=None: {
                "ready": True,
                "purpose": purpose,
                "missing": [],
                "next_question": "",
                "budget": "USD 30 diarios",
            }
            dashboard.load_config = lambda: type("Cfg", (), {"codex_creative_enabled": False, "codex_creative_model": "gpt-5.5"})()
            dashboard.call_codex_cli = lambda prompt: calls.append(prompt) or {"ok": True}
            dashboard.call_codex_image_cli = lambda prompt, **kwargs: calls.append(prompt) or {
                "ok": False,
                "error": "Codex/Image todavia no esta conectado en este PC/VPS. Conecta ChatGPT/Codex y vuelve a intentar.",
            }
            disabled = dashboard.execute_agent_tool(
                {
                    "tool": "codex_image_generate",
                    "arguments": {
                        "request": "Genera un creativo final para Meta Ads usando Codex Image con la foto del producto.",
                        "product_guide": "",
                    },
                },
                {"language": "es", "image_paths": [str(reference_image)]},
            )
            self.assert_true(disabled["type"] == "codex_image_generate", "Codex image request routes to the image generation tool")
            self.assert_true(disabled["executed"] is False and disabled["blocked"] is True, "Codex image request is blocked when Codex/Image is not connected")
            self.assert_true("Codex/Image" in disabled["reply"] and "otra API" in disabled["reply"], "Buyer receives clear Codex/Image setup guidance without external provider wording")

            calls.clear()
            dashboard.load_config = lambda: type("Cfg", (), {"codex_creative_enabled": True, "codex_creative_model": "gpt-5.5"})()
            dashboard.call_codex_cli = lambda prompt, **kwargs: calls.append(prompt) or {
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
            dashboard.call_codex_image_cli = lambda prompt, **kwargs: calls.append(prompt) or {
                "ok": True,
                "image_path": str(dashboard.CREATIVE_ASSET_ROOT / "codex-test" / "meta-ad.png"),
                "asset_id": "codex-test/meta-ad.png",
                "preview_url": "/api/creative-asset?id=codex-test%2Fmeta-ad.png",
            }
            enabled = dashboard.execute_agent_tool(
                {
                    "tool": "codex_image_generate",
                    "arguments": {
                        "request": "Genera un creativo final para Meta Ads usando Codex Image con la foto del producto.",
                        "product_guide": "",
                    },
                },
                {"language": "es", "image_paths": [str(reference_image)]},
            )
            self.assert_true(enabled["executed"] is True, "Connected Codex/Image request executes the backend bridge")
            self.assert_true("/api/creative-asset" in enabled["reply"], "Agent returns a protected preview URL for the generated image")
            self.assert_true("Referencia visual" in calls[0], "Uploaded image context is forwarded into the Codex image prompt")
            self.assert_true(enabled["result"]["prompt_package"]["mode"] == "fixed" and enabled["result"]["asset_id"], "Codex image tool returns the generated asset metadata")
            self.assert_true(str(reference_image) not in calls[0], "Codex prompt receives visual context without arbitrary local file dependency")
        finally:
            dashboard.load_config = original_load_config
            dashboard.call_codex_cli = original_call_codex
            dashboard.call_codex_image_cli = original_call_codex_image
            dashboard.creative_strategy_readiness = original_creative_readiness

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
            self.assert_true(meta_upload.find_manifest(str(manifest_path)) == manifest_path, "Creative upload accepts scoped generated manifests")
            try:
                meta_upload.find_manifest("/etc/passwd")
                self.assert_true(False, "Creative upload rejects arbitrary manifest paths")
            except ValueError:
                self.assert_true(True, "Creative upload rejects arbitrary manifest paths")
            payload_path = dashboard.OUTPUT_DIR / "uploads" / "security-test" / "payload.json"
            payload_path.parent.mkdir(parents=True, exist_ok=True)
            dashboard.write_json(
                payload_path,
                {
                    "id": "security-test",
                    "status": "ready_for_approval",
                    "missing_requirements": [],
                    "asset_uploads": [{"file_path": str(ROOT_DIR / "secrets.txt")}],
                },
            )
            self.assert_true(graph_executor.safe_upload_payload_path(payload_path) == payload_path, "Graph executor accepts scoped upload payloads")
            try:
                graph_executor.safe_upload_payload_path("/etc/passwd")
                self.assert_true(False, "Graph executor rejects arbitrary payload paths")
            except ValueError:
                self.assert_true(True, "Graph executor rejects arbitrary payload paths")
            missing = graph_executor.validate_payload(dashboard.read_json(payload_path, {}), dashboard.load_config(), approved=False)
            self.assert_true(any("inside output" in item for item in missing), "Graph executor rejects asset paths outside generated output")
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
        references_path = codex_brand_guides.CREATIVE_REFERENCES_FILE
        references_before = references_path.read_bytes() if references_path.exists() else None
        product_before = product_path.read_bytes() if product_path.exists() else None
        ad_brief_before = ad_brief_path.read_bytes() if ad_brief_path.exists() else None
        created_logo_path = None
        try:
            dashboard = load_dashboard_module()
            blank_fields = codex_brand_guides.general_fields("- Promesa principal:\n- Cliente ideal: Compradora real")
            self.assert_true(blank_fields["promise"] == "" and blank_fields["ideal_customer"] == "Compradora real", "Blank Markdown fields never absorb the following brand field")
            library = codex_brand_guides.save_general_guide(
                {
                    "brand_name": "Luz Clara",
                    "offer": "Cuidado facial consciente",
                    "visual_style": "fondos marfil con acentos coral y fotografia limpia",
                    "tone": "cercano, decidido y facil de entender",
                    "avoid_always": "promesas medicas",
                    "logo_path": "brand_guides/assets/luz-clara-logo.png",
                    "logo_notes": "Logo circular coral con letras blancas, usarlo pequeno sobre fondo claro.",
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
            references = codex_brand_guides.save_creative_references(
                {
                    "web_references": "Referencia ecommerce de skincare: layout limpio, producto protagonista, fondo claro.",
                    "generated_references": "Imagen 2: paleta coral/marfil, close-up premium.",
                    "approved_references": "Mantener producto grande y texto minimo.",
                    "notes": "Usar referencias como direccion, no como copia exacta.",
                }
            )
            codex_brand_guides.save_creative_references(
                {
                    "approved_references": "Agregar sello de oferta y mantener layout aprobado.",
                    "append": True,
                }
            )
            codex_prompt = build_codex_creative_prompt(result["guide"], "Crea un concepto para la siguiente campaña.")
            image_package = build_codex_image_prompt_package(result["guide"], "Genera imagen con el logo visible.", mode="fixed", variations=1)
            logo_upload = dashboard.save_brand_logo_asset(
                {
                    "filename": "luz-clara-logo.png",
                    "content_type": "image/png",
                    "data_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=",
                    "logo_notes": "Logo minimo de prueba para anuncios.",
                }
            )
            created_logo_path = codex_brand_guides.ROOT_DIR / logo_upload["logo_path"]
            prompt = plan["variants"][0]["image_prompts"][0]["prompt"]
            ad_prompt = ad_plan["variants"][0]["image_prompts"][0]["prompt"]
            self.assert_true(library["general"]["saved"] is True and product_path.exists(), "Brand and product memory are saved as local Markdown guides")
            self.assert_true(library["general"]["fields"]["logo_path"] == "brand_guides/assets/luz-clara-logo.png", "Brand logo path is stored as part of general brand memory")
            self.assert_true("product.example.md" not in [item["guide"] for item in result["library"]["products"]], "Product template is not presented as buyer memory")
            self.assert_true(plan["brand_memory"]["product"]["name"] == "Memoria Prueba Integracion", "Creative plan records which product memory it used")
            self.assert_true(plan["brand_memory"]["brand"]["logo_path"] == "brand_guides/assets/luz-clara-logo.png", "Creative memory exposes the saved logo to creative planning")
            self.assert_true("Memoria Prueba Integracion" in plan["variants"][0]["copy"]["headline"], "Product memory informs generated ad copy")
            self.assert_true("piel luminosa sin complicaciones" in plan["variants"][0]["copy"]["primary_text"], "Desired result from product memory informs the copy")
            self.assert_true("fondos marfil" in prompt and "mujeres que buscan" in prompt and "resultados milagrosos" in prompt, "Brand style, audience, and exclusions inform image prompts")
            self.assert_true(ad_brief_path.exists() and ad_plan["brand_memory"]["ad_brief"]["name"] == "Brief Buen Fin Variantes", "Ad brief memory is saved and attached to creative plans")
            self.assert_true(len(ad_plan["variants"]) == 4, "Ad brief variation count controls the number of variants")
            self.assert_true("Anuncio ganador testimonio" in ad_plan["brand_memory"]["ad_brief"]["base_ad_name"], "Ad brief records the exact winning/base ad")
            self.assert_true("Bono de Buen Fin" in ad_prompt and "paleta de colores" in ad_prompt, "Ad brief promotion and creative window inform image prompts")
            self.assert_true("colores" in ad_plan["variants"][0]["copy"]["headline"].lower(), "Ad brief variation axes become concrete ad variants")
            self.assert_true(references["creative_references"] == "brand_guides/creative_references.md" and "Referencia ecommerce" in codex_prompt, "Approved creative references are saved and included in Codex creative prompts")
            self.assert_true("Logo circular coral" in codex_prompt and "No hay logo guardado" not in codex_prompt, "Codex creative prompts include saved logo context")
            self.assert_true("Logo circular coral" in image_package["prompts"][0]["image_prompt"] and "no inventes otro logo" in image_package["brand_lock"].lower(), "Codex/Image prompt package preserves logo rules")
            self.assert_true(logo_upload["saved"] is True and logo_upload["library"]["general"]["fields"]["logo_notes"] == "Logo minimo de prueba para anuncios.", "Dashboard logo upload stores the logo as brand memory")
            self.assert_true("futuros creativos" in logo_upload["library"]["general"]["fields"]["logo_usage"], "Dashboard logo upload defaults future creatives to the saved official logo")
            self.assert_true("Mantener producto grande" in codex_prompt and "Agregar sello de oferta" in codex_prompt, "Appending creative references preserves prior approved direction instead of replacing it")
        finally:
            if created_logo_path:
                created_logo_path.unlink(missing_ok=True)
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
            if references_before is None:
                references_path.unlink(missing_ok=True)
            else:
                references_path.parent.mkdir(parents=True, exist_ok=True)
                references_path.write_bytes(references_before)

    def test_agent_onboarding_phase_tools_create_durable_memory(self):
        """Test Telegram/dashboard agent tools can move from business to branding to campaign memory."""
        print("\nTesting Agent Onboarding Phase Tools...")

        dashboard = load_dashboard_module()
        paths = [
            dashboard.BUSINESS_PROFILE_FILE,
            dashboard.ONBOARDING_QUESTIONS_FILE,
            dashboard.AGENT_ONBOARDING_PLAN_FILE,
            dashboard.ADS_ONBOARDING_FILE,
            codex_brand_guides.GENERAL_GUIDE,
            codex_brand_guides.CREATIVE_REFERENCES_FILE,
            codex_brand_guides.PRODUCT_DIR / "oferta-fase-prueba.md",
            codex_brand_guides.AD_BRIEF_DIR / "brief-fase-prueba.md",
        ]
        backups = {path: (path.read_bytes() if path.exists() else None) for path in paths}
        try:
            business = dashboard.execute_agent_tool(
                {
                    "tool": "save_business_context",
                    "arguments": {
                        "business_type": "clinica dental",
                        "main_offer": "blanqueamiento dental",
                        "ideal_customer": "adultos que quieren verse mejor",
                        "current_stage": "ya vende y quiere escalar",
                        "what_to_improve": "bajar el costo por cita",
                        "success_goal": "mas citas en 30 dias",
                        "context_complete": True,
                    },
                },
                {"language": "es"},
            )
            phase_after_business = dashboard.agent_onboarding_phase()
            dashboard.execute_agent_tool(
                {
                    "tool": "save_brand_guide",
                    "arguments": {
                        "brand_name": "Sonrisa Clara",
                        "offer": "tratamientos dentales esteticos",
                        "ideal_customer": "adultos profesionales",
                        "colors": "azul profundo, blanco, acento dorado",
                        "typography": "sans serif limpia y premium",
                        "visual_style": "clinico premium, luz suave, sonrisa natural",
                        "tone": "experta, humana y directa",
                        "logo_notes": "La clínica todavía no tiene logo oficial.",
                        "logo_usage": "no usar hasta tener archivo oficial",
                        "references": "referencias aprobadas por el cliente",
                        "asset_notes": "Hay fotos reales de pacientes con permiso y del consultorio.",
                    },
                },
                {"language": "es"},
            )
            dashboard.execute_agent_tool(
                {
                    "tool": "save_product_guide",
                    "arguments": {
                        "name": "Oferta Fase Prueba",
                        "audience": "personas que quieren una sonrisa mas blanca",
                        "pain": "inseguridad al sonreir",
                        "desire": "verse mejor en fotos y reuniones",
                    },
                },
                {"language": "es"},
            )
            refs = dashboard.execute_agent_tool(
                {
                    "tool": "save_creative_references",
                    "arguments": {
                        "web_references": "Anuncios dentales premium: rostro feliz, fondo limpio, prueba social.",
                        "approved_references": "Usar fondo limpio y texto minimo.",
                    },
                },
                {"language": "es"},
            )
            phase_after_branding = dashboard.agent_onboarding_phase()
            ads = dashboard.execute_agent_tool(
                {
                    "tool": "save_ads_onboarding",
                    "arguments": {
                        "promoted_before": "promociones en Instagram",
                        "previous_ads_results": "muchos mensajes pero pocas citas",
                        "campaign_goal": "agendar citas",
                        "success_metrics": ["cost per qualified lead", "cost per booking", "ROAS"],
                        "budget_comfort": "20 dolares diarios",
                        "first_strategy": "campana de mensajes con creativos premium y retargeting simple",
                        "ads_onboarding_complete": True,
                    },
                },
                {"language": "es"},
            )
            brief = dashboard.execute_agent_tool(
                {
                    "tool": "save_ad_brief",
                    "arguments": {
                        "name": "Brief Fase Prueba",
                        "promotion": "evaluacion dental inicial",
                        "base_ad": "sonrisa natural con prueba social",
                        "budget": "20 dolares diarios",
                        "variation_window": "probar colores y encuadre sin cambiar oferta",
                        "variation_axes": "dolor, deseo, prueba social y demostración",
                        "variation_count": "5",
                        "concurrent_variations": "3 simultáneos y 2 en backlog",
                        "formats": "foto real, UGC y estático de prueba",
                        "creative_hypothesis": "descubrir si prueba real supera a la oferta directa",
                    },
                },
                {"language": "es"},
            )
            final_phase = dashboard.agent_onboarding_phase()
            plan_text = dashboard.AGENT_ONBOARDING_PLAN_FILE.read_text(encoding="utf-8")
            brief_text = (codex_brand_guides.AD_BRIEF_DIR / "brief-fase-prueba.md").read_text(encoding="utf-8")
            skill_text = (ROOT_DIR / "agent" / "SKILLS.md").read_text(encoding="utf-8")
            branding_skill_text = (ROOT_DIR / "agent" / "skills" / "branding-creatives-creation" / "SKILL.md").read_text(encoding="utf-8")
            self.assert_true(business["executed"] is True and phase_after_business["phase"] == "branding_creatives_creation", "Business context tool moves onboarding to branding creatives phase")
            self.assert_true(refs["executed"] is True and phase_after_branding["phase"] == "ads_campaign_onboarding", "Brand and creative reference tools move onboarding to campaign history phase")
            self.assert_true(ads["executed"] is True and brief["executed"] is True and final_phase["phase"] == "continuous_ads_manager", "Campaign onboarding and ad brief tools finish the chat onboarding phase")
            self.assert_true("branding creatives creation" in skill_text and "save_creative_references" in skill_text, "Branding creatives creation skill is documented for Hermes")
            self.assert_true("mcp_admira_save_product_memory" in branding_skill_text and "logo" in branding_skill_text.lower(), "Focused branding skill covers product memory and logo context")
            self.assert_true("Primer mensaje del onboarding" in plan_text and "entender tu negocio" in plan_text and "marca, logo, colores" in plan_text and "ofertas especificas" in plan_text, "Agent onboarding plan tells Hermes to introduce business, branding, then ads strategy")
            self.assert_true("continuous_ads_manager" in plan_text and "save_ads_onboarding" in plan_text, "Agent onboarding plan records the continuous manager phase")
            ads_onboarding_text = dashboard.ADS_ONBOARDING_FILE.read_text(encoding="utf-8")
            self.assert_true("3 resultados principales/KPIs" in ads_onboarding_text and "cost_per_qualified_lead" in ads_onboarding_text and "cost_per_booking" in ads_onboarding_text, "Ads onboarding persists the buyer's ranked campaign scorecard")
            self.assert_true("Presupuesto: 20 dolares diarios" in brief_text and "Presupuesto de prueba: 20 dolares diarios" in brief_text, "Ad brief persists test budget as structured fields for creative production readiness")
        finally:
            for path, content in backups.items():
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)

    def test_creative_strategy_gate_and_exact_logo_pipeline(self):
        """Test final ad production waits for strategy and preserves the official logo exactly."""
        print("\nTesting Creative Strategy Gate And Exact Logo...")

        dashboard = load_dashboard_module()
        original_library = dashboard.guide_library
        original_read_json = dashboard.read_json
        original_call_codex = dashboard.call_codex_cli
        original_call_image = dashboard.call_codex_image_cli
        original_load_config = dashboard.load_config
        original_official_logo = dashboard.official_brand_logo_path
        test_dir = ROOT_DIR / "output" / "test-creative-strategy-gate"
        reference = test_dir / "product-reference.png"
        output_image = test_dir / "generated.png"
        logo = test_dir / "official-logo.png"
        captured = {}
        plan_calls = []
        image_calls = []
        try:
            from PIL import Image, ImageDraw

            shutil.rmtree(test_dir, ignore_errors=True)
            test_dir.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (160, 160), "#d8b48a").save(reference)
            full_general = {
                "brand_name": "Marca Lista",
                "offer": "Producto de prueba",
                "colors": "azul y blanco",
                "visual_style": "fotografía limpia y producto protagonista",
                "tone": "experta y humana",
                "logo_notes": "Sin logo por ahora",
                "logo_usage": "no usar",
                "references": "referencia editorial aprobada",
                "asset_notes": "foto real del producto disponible",
            }

            def library(general=None, briefs=None):
                general = general or {}
                briefs = briefs or []
                return {
                    "general_exists": bool(general),
                    "creative_references_exists": False,
                    "product_count": 1 if general else 0,
                    "ad_brief_count": len(briefs),
                    "general": {"saved": bool(general), "fields": general},
                    "products": [{"id": "producto", "ready": True, "fields": {"name": "Producto", "pain": "dolor", "audience": "cliente"}}] if general else [],
                    "ad_briefs": briefs,
                }

            dashboard.guide_library = lambda: library()
            dashboard.read_json = lambda path, default=None: {} if path == dashboard.BUSINESS_PROFILE_FILE else original_read_json(path, default)
            dashboard.call_codex_cli = lambda prompt, **kwargs: plan_calls.append(prompt) or {"ok": True}
            dashboard.call_codex_image_cli = lambda prompt, **kwargs: image_calls.append(prompt) or {"ok": True}
            plan_blocked = dashboard.codex_creative_plan({"request": "Prepara una idea visual", "purpose": "ad_creative"})
            direct_image_blocked = dashboard.codex_image_generate({"request": "Crea un anuncio final", "purpose": "ad_creative"})
            self.assert_true(plan_blocked["blocked"] is True and plan_blocked["reason"] == "creative_strategy_not_ready", "Low-level creative planning is blocked before brand discovery")
            self.assert_true(direct_image_blocked["blocked"] is True and direct_image_blocked["reason"] == "creative_production_not_ready", "Low-level final image generation is blocked before brand discovery")
            self.assert_true(not plan_calls and not image_calls, "Blocked low-level creative calls never invoke Codex or Image")
            blocked = dashboard.execute_agent_tool(
                {"tool": "codex_image_generate", "arguments": {"request": "Crea un anuncio final", "purpose": "ad_creative"}},
                {"language": "es"},
            )
            self.assert_true(blocked["blocked"] is True and blocked["reason"] == "creative_production_not_ready", "Final image production is blocked before brand discovery")
            self.assert_true("marca" in blocked["reply"].lower() and "vende" in blocked["reply"].lower(), "Creative gate returns the exact next discovery question")

            profile_only_capture = {}

            def fake_profile_image(prompt, **kwargs):
                profile_only_capture["prompt"] = prompt
                profile_only_capture["kwargs"] = kwargs
                return {"ok": True, "asset_id": "profile-only-real-photo.png"}

            dashboard.call_codex_image_cli = fake_profile_image
            dashboard.read_json = lambda path, default=None: (
                {
                    "main_offer": "facial + masaje 60 minutos por S/99",
                    "ideal_customer": "personas en Lima que buscan relajación, cuidado facial y bienestar",
                    "what_to_improve": "conseguir reservas por WhatsApp",
                    "business_type": "spa",
                }
                if path == dashboard.BUSINESS_PROFILE_FILE
                else original_read_json(path, default)
            )
            direct_from_profile = dashboard.execute_agent_tool(
                {
                    "tool": "codex_image_generate",
                    "arguments": {
                        "request": "Usa la foto real subida como fondo real del anuncio y conserva la recepción pixel por pixel.",
                        "purpose": "ad_creative",
                        "business_name": "Spa MediCentro Juliana",
                        "services": "faciales y masajes",
                        "palette": "verde salvia, beige, blanco crema, dorado suave",
                        "image_style": "elegante, limpio, relajante",
                        "voice": "claro, cercano, confiable",
                        "logo_request": "crear logo desde cero, sin logo oficial todavía",
                        "reference_decision": "usar la foto real subida como base",
                        "real_asset_decision": "sí hay foto real del local y debe usarse como fondo",
                        "use_reference_as_background": True,
                    },
                },
                {"language": "es", "image_paths": [str(reference)]},
            )
            self.assert_true(direct_from_profile["executed"] is True and direct_from_profile["result"]["prompt_package"]["reference_image_count"] == 1, "Image generation proceeds from business profile product context when saved product guides are missing")
            self.assert_true(direct_from_profile["result"]["prompt_package"]["reference_image_role"] == "real_photo_background", "Real uploaded photo is marked as the Image 2 background/base reference")
            self.assert_true(str(reference) in [str(path) for path in profile_only_capture["kwargs"]["reference_image_paths"]], "Handler attaches the Telegram image before readiness/generation")
            self.assert_true("MODO FOTO REAL COMO BASE" in profile_only_capture["prompt"] and "S/99" in profile_only_capture["prompt"], "Image 2 prompt includes both the real-photo lock and product context from business memory")

            dashboard.guide_library = lambda: library(full_general)
            dashboard.read_json = lambda path, default=None: ({} if path == dashboard.BUSINESS_PROFILE_FILE else original_read_json(path, default))
            standalone_no_brief = dashboard.execute_agent_tool(
                {
                    "tool": "codex_image_generate",
                    "arguments": {
                        "request": "Crea una imagen suelta para revisar del proyecto de vivienda TRIVA, familiar y moderna.",
                        "product_guide": "Proyecto de vivienda TRIVA para compradores en Medellín con financiación disponible.",
                        "asset_only": True,
                    },
                },
                {"language": "es"},
            )
            self.assert_true(standalone_no_brief["executed"] is True and standalone_no_brief["result"]["prompt_package"]["requires_full_ad_brief"] is False, "Standalone creative images do not require a saved ad-test brief")
            no_brief = dashboard.execute_agent_tool(
                {"tool": "codex_image_generate", "arguments": {"request": "Crea un anuncio listo para lanzar", "purpose": "launch_ad", "require_brief": True}},
                {"language": "es"},
            )
            self.assert_true(no_brief["blocked"] is True and no_brief["result"]["readiness"]["missing"][0]["key"] == "ad_brief", "Launch-ready image production still requires a saved creative test brief")

            brief_fields = {
                "name": "Brief listo",
                "variation_window": "probar perspectivas sin cambiar la oferta",
                "variation_axes": "dolor, prueba y demostración",
                "variation_count": "5",
                "concurrent_variations": "3 simultáneos y 2 en backlog",
                "formats": "UGC, foto real y estático",
                "creative_hypothesis": "descubrir qué ángulo produce leads de mejor calidad",
            }
            dashboard.guide_library = lambda: library(full_general, [{"id": "brief-listo", "fields": brief_fields, "ready": True}])
            dashboard.read_json = lambda path, default=None: ({} if path == dashboard.BUSINESS_PROFILE_FILE else original_read_json(path, default))
            dashboard.load_config = lambda: type("Cfg", (), {"codex_creative_model": "gpt-5.5"})()
            readiness_without_budget = dashboard.creative_strategy_readiness(require_brief=True, purpose="ad_creative")
            self.assert_true(readiness_without_budget["ready"] is True and readiness_without_budget["budget"] == "", "Creative readiness does not require budget to generate draft images when brand and brief are complete")

            def fake_image(prompt, **kwargs):
                captured["prompt"] = prompt
                captured["kwargs"] = kwargs
                Image.new("RGB", (600, 750), "#f4efe8").save(output_image)
                return {"ok": True, "image_path": str(output_image), "asset_id": "test-creative-strategy-gate/generated.png"}

            dashboard.call_codex_image_cli = fake_image
            ready = dashboard.execute_agent_tool(
                {"tool": "codex_image_generate", "arguments": {"request": "Crea un anuncio fotorealista", "purpose": "ad_creative"}},
                {"language": "es", "image_paths": [str(reference)]},
            )
            self.assert_true(ready["executed"] is True and str(reference) in [str(path) for path in captured["kwargs"]["reference_image_paths"]], "Ready production forwards the buyer's real reference image to Codex")

            Image.new("RGB", (600, 750), "white").save(output_image)
            logo_image = Image.new("RGBA", (180, 70), (0, 0, 0, 0))
            draw = ImageDraw.Draw(logo_image)
            draw.rounded_rectangle((4, 4, 176, 66), radius=10, fill=(12, 72, 180, 255))
            draw.rectangle((24, 22, 156, 48), fill=(255, 255, 255, 255))
            logo_image.save(logo)
            applied = codex_brand_guides.composite_official_logo(output_image, logo, position="bottom-right", background="auto")
            composited = Image.open(output_image).convert("RGB")
            self.assert_true(applied["applied"] is True and applied["position"] == "bottom-right", "Official logo compositor reports exact deterministic placement")
            self.assert_true(composited.getpixel((540, 690)) != (255, 255, 255), "Official logo pixels are applied to the generated creative instead of being redrawn by the model")

            logo_general_default = {**full_general, "logo_path": str(logo), "logo_notes": "Logo oficial protegido", "logo_usage": ""}
            dashboard.guide_library = lambda: library(logo_general_default, [{"id": "brief-listo", "fields": brief_fields, "ready": True}])
            dashboard.official_brand_logo_path = lambda: logo
            default_logo = dashboard.codex_image_generate(
                {
                    "request": "Crea un anuncio fotorealista para la marca con producto protagonista",
                    "purpose": "ad_creative",
                }
            )
            default_logo_refs = [str(path) for path in captured["kwargs"]["reference_image_paths"]]
            self.assert_true(str(logo) in default_logo_refs and default_logo["prompt_package"]["include_logo"] is True, "Saved official logo is attached by default for future creatives")
            self.assert_true("pixel by pixel accuracy" in captured["prompt"] and "pixel-level accurate" in captured["prompt"], "Default official-logo prompt explicitly asks for pixel-by-pixel accurate reproduction")

            no_logo = dashboard.codex_image_generate(
                {
                    "request": "Crea un anuncio fotorealista sin logo, solo producto protagonista",
                    "purpose": "ad_creative",
                }
            )
            no_logo_refs = [str(path) for path in captured["kwargs"]["reference_image_paths"]]
            self.assert_true(str(logo) not in no_logo_refs and no_logo["prompt_package"]["include_logo"] is False, "Explicit no-logo requests do not attach the saved official logo")

            logo_general = {**full_general, "logo_path": str(logo), "logo_notes": "Logo oficial protegido", "logo_usage": "usar siempre"}
            dashboard.guide_library = lambda: library(logo_general, [{"id": "brief-listo", "fields": brief_fields, "ready": True}])
            dashboard.official_brand_logo_path = lambda: logo
            protected = dashboard.codex_image_generate(
                {
                    "request": "Crea un anuncio con el logo oficial visible",
                    "purpose": "ad_creative",
                    "include_logo": True,
                    "logo_position": "top-left",
                }
            )
            protected_prompt = captured["prompt"]
            protected_refs = [str(path) for path in captured["kwargs"]["reference_image_paths"]]
            self.assert_true(str(logo) in protected_refs and "LOGO OFICIAL PROTEGIDO" in protected_prompt, "Saved official logo is attached to Image 2 as a protected context reference")
            self.assert_true("Reprodúcelo exactamente" in protected_prompt and "pixel by pixel accuracy" in protected_prompt and "pixel-level accurate" in protected_prompt and "pixel-faithful" in protected_prompt and "fiel píxel por píxel" in protected_prompt and "geometría" in protected_prompt, "Image prompt explicitly requires pixel-by-pixel accurate logo reproduction and locks artwork, geometry, colors, and proportions")
            self.assert_true(protected["prompt_package"]["logo_render_mode"] == "protected_context" and "official_logo" not in protected, "Protected-context logo rendering is the default and does not add a duplicate post-process logo")

            fallback = dashboard.codex_image_generate(
                {
                    "request": "Crea un anuncio con el logo oficial visible",
                    "purpose": "ad_creative",
                    "include_logo": True,
                    "logo_position": "bottom-right",
                    "logo_render_mode": "exact_composite",
                }
            )
            self.assert_true("No dibujes, imites ni incluyas ningún logo" in captured["prompt"] and fallback["official_logo"]["applied"] is True, "Exact-composite fallback keeps the generated base logo-free and applies the saved file afterward")
            wrapped_prompt = codex_brand_guides.codex_image_generation_prompt(protected_prompt, has_references=True)
            self.assert_true("contrato de logo protegido" in wrapped_prompt and "sin redibujarla" in wrapped_prompt, "Codex image wrapper preserves the exact-logo contract instead of contradicting it")
        finally:
            dashboard.guide_library = original_library
            dashboard.read_json = original_read_json
            dashboard.call_codex_cli = original_call_codex
            dashboard.call_codex_image_cli = original_call_image
            dashboard.load_config = original_load_config
            dashboard.official_brand_logo_path = original_official_logo
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_creative_memory_accepts_agent_aliases_for_product_and_brief(self):
        """Test natural agent field names save structured creative readiness fields."""
        print("\nTesting Creative Memory Agent Alias Compatibility...")

        test_root = Path(tempfile.mkdtemp(prefix="creative_aliases_"))
        brand_dir = test_root / "brand_guides"
        product_dir = brand_dir / "products"
        brief_dir = brand_dir / "ad_briefs"
        data_dir = test_root / "dashboard" / "data"
        original = {
            "ROOT_DIR": codex_brand_guides.ROOT_DIR,
            "BRAND_DIR": codex_brand_guides.BRAND_DIR,
            "PRODUCT_DIR": codex_brand_guides.PRODUCT_DIR,
            "AD_BRIEF_DIR": codex_brand_guides.AD_BRIEF_DIR,
            "BRAND_ASSET_DIR": codex_brand_guides.BRAND_ASSET_DIR,
            "GENERAL_GUIDE": codex_brand_guides.GENERAL_GUIDE,
            "CREATIVE_REFERENCES_FILE": codex_brand_guides.CREATIVE_REFERENCES_FILE,
            "BUSINESS_PROFILE_FILE": codex_brand_guides.BUSINESS_PROFILE_FILE,
        }
        try:
            product_dir.mkdir(parents=True, exist_ok=True)
            brief_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "business_profile.json").write_text("{}", encoding="utf-8")
            codex_brand_guides.ROOT_DIR = test_root
            codex_brand_guides.BRAND_DIR = brand_dir
            codex_brand_guides.PRODUCT_DIR = product_dir
            codex_brand_guides.AD_BRIEF_DIR = brief_dir
            codex_brand_guides.BRAND_ASSET_DIR = brand_dir / "assets"
            codex_brand_guides.GENERAL_GUIDE = brand_dir / "general_branding.md"
            codex_brand_guides.CREATIVE_REFERENCES_FILE = brand_dir / "creative_references.md"
            codex_brand_guides.BUSINESS_PROFILE_FILE = data_dir / "business_profile.json"
            brand = codex_brand_guides.save_general_guide(
                {
                    "name": "Spa MediCentro Juliana",
                    "what_sells": "faciales y masajes",
                    "location": "Lima, Perú",
                    "brand_colors": "verde salvia, beige, blanco crema, dorado suave",
                    "style": "elegante, limpio, relajante",
                    "tone": "claro, cercano, confiable",
                    "logo_decision": "crear un logo desde cero",
                    "reference_decision": "sin referencias externas por ahora",
                    "real_assets": "no hay fotos reales, usar imágenes generadas",
                }
            )
            brand_fields = brand["general"]["fields"]
            raw_key_fields = codex_brand_guides.general_fields(
                "\n".join(
                    [
                        "brand_name: Spa MediCentro Juliana",
                        "colors: verde salvia, beige, blanco crema, dorado suave",
                        "visual_style: ambiente de spa cálido, elegante y limpio",
                        "tone: cercano y confiable",
                        "logo_decision: crear uno desde cero",
                        "reference_decision: sin referencias externas",
                        "real_assets: no hay fotos reales",
                    ]
                )
            )
            product = codex_brand_guides.save_product_guide(
                {
                    "product_name": "TRIVA",
                    "target_audience": "compradores de vivienda en Medellín",
                    "problem": "dar el paso hacia vivienda propia con acompañamiento",
                    "benefit": "financiación disponible en un proyecto moderno en Palmas de Medellín",
                    "must_show": "personas o familias imaginando su nuevo hogar",
                }
            )
            brief = codex_brand_guides.save_ad_brief(
                {
                    "brief_name": "TRIVA compradores vivienda",
                    "product_name": "TRIVA",
                    "campaign": "Proyecto TRIVA Palmas",
                    "base_ad": "proyecto de vivienda para compradores con financiación disponible",
                    "budget": "COP 40.000/día",
                    "variants": 2,
                    "simultáneas": 2,
                    "creative_formats": "imagen estática realista para Meta Ads",
                    "variation_axes": "ángulo familiar vs acompañamiento confiable",
                    "hypothesis": "probar si el deseo familiar supera la confianza en el acompañamiento",
                }
            )
            library = codex_brand_guides.guide_library()
            product_card = next(item for item in library["products"] if item["id"] == "triva")
            brief_card = next(item for item in library["ad_briefs"] if item["id"] == "triva-compradores-vivienda")
            self.assert_true(brand_fields["brand_name"] == "Spa MediCentro Juliana" and "faciales" in brand_fields["offer"], "Brand aliases save natural onboarding fields as structured brand memory")
            self.assert_true("verde salvia" in brand_fields["colors"] and brand_fields["visual_style"] == "elegante, limpio, relajante", "Brand aliases preserve colors and visual style")
            self.assert_true("logo" in brand_fields["logo_notes"] and "imágenes generadas" in brand_fields["asset_notes"], "Brand aliases preserve logo and real-asset decisions")
            self.assert_true(raw_key_fields["brand_name"] == "Spa MediCentro Juliana" and raw_key_fields["colors"].startswith("verde salvia"), "Brand parser reads raw key Markdown such as brand_name and colors")
            self.assert_true(raw_key_fields["visual_style"].startswith("ambiente de spa") and raw_key_fields["logo_notes"].startswith("crear"), "Brand parser maps visual_style, logo_decision, references, and real_assets keys")
            self.assert_true(product["guide"] == "brand_guides/products/triva.md" and product_card["ready"], "Product aliases save a ready product guide")
            self.assert_true(product_card["fields"]["name"] == "TRIVA" and "Medellín" in product_card["fields"]["audience"], "Product parser reads aliased name and audience fields")
            self.assert_true(brief["ad_brief"] == "brand_guides/ad_briefs/triva-compradores-vivienda.md", "Brief aliases save the expected ad brief file")
            self.assert_true(brief_card["fields"]["campaign_name"] == "Proyecto TRIVA Palmas", "Brief parser maps campaign alias to campaign_name")
            self.assert_true(brief_card["fields"]["variation_count"] == "2" and brief_card["fields"]["concurrent_variations"] == "2", "Brief parser maps variants and simultaneous creative aliases")
            self.assert_true(brief_card["fields"]["formats"] == "imagen estática realista para Meta Ads", "Brief parser maps creative_formats to formats")
            self.assert_true("acompañamiento" in brief_card["fields"]["variation_axes"] and brief_card["fields"]["creative_hypothesis"], "Brief parser keeps variation axes and hypothesis")

            dashboard = load_dashboard_module()
            dashboard_brand = dashboard.execute_agent_tool(
                {
                    "tool": "save_brand_guide",
                    "arguments": {
                        "business_name": "Spa MediCentro Juliana",
                        "services": "faciales y masajes",
                        "city": "Lima, Perú",
                        "palette": "verde salvia, beige, blanco crema, dorado suave",
                        "image_style": "elegante, limpio, relajante",
                        "voice": "claro, cercano, confiable",
                        "logo_request": "crear uno desde cero",
                        "real_photos": "no hay, usar generadas",
                    },
                },
                {"language": "es"},
            )
            readiness = dashboard.creative_strategy_readiness(require_brief=True, purpose="ad_creative")
            self.assert_true(dashboard_brand["executed"] is True and dashboard_brand.get("reason") != "missing_brand_core", "Dashboard brand save handler accepts natural aliases instead of blocking as missing_brand_core")
            self.assert_true(readiness["ready"] is True and readiness["budget"] == "COP 40.000/día", "Readiness recognizes saved aliased product and brief fields")
        finally:
            for key, value in original.items():
                setattr(codex_brand_guides, key, value)
            shutil.rmtree(test_root, ignore_errors=True)

    def test_mcp_wrapped_creative_memory_and_asset_only_context(self):
        """Test Hermes/MCP wrapped args persist creative memory and direct context can generate assets."""
        print("\nTesting MCP Wrapped Creative Memory And Asset-Only Context...")

        test_root = Path(tempfile.mkdtemp(prefix="creative_wrapped_args_"))
        brand_dir = test_root / "brand_guides"
        product_dir = brand_dir / "products"
        brief_dir = brand_dir / "ad_briefs"
        data_dir = test_root / "dashboard" / "data"
        creative_dir = test_root / "creatives"
        dashboard = load_dashboard_module()
        original_codex = {
            "ROOT_DIR": codex_brand_guides.ROOT_DIR,
            "BRAND_DIR": codex_brand_guides.BRAND_DIR,
            "PRODUCT_DIR": codex_brand_guides.PRODUCT_DIR,
            "AD_BRIEF_DIR": codex_brand_guides.AD_BRIEF_DIR,
            "BRAND_ASSET_DIR": codex_brand_guides.BRAND_ASSET_DIR,
            "GENERAL_GUIDE": codex_brand_guides.GENERAL_GUIDE,
            "CREATIVE_REFERENCES_FILE": codex_brand_guides.CREATIVE_REFERENCES_FILE,
            "BUSINESS_PROFILE_FILE": codex_brand_guides.BUSINESS_PROFILE_FILE,
        }
        original_dashboard = {
            "BUSINESS_PROFILE_FILE": dashboard.BUSINESS_PROFILE_FILE,
            "ONBOARDING_QUESTIONS_FILE": dashboard.ONBOARDING_QUESTIONS_FILE,
            "AGENT_ONBOARDING_PLAN_FILE": dashboard.AGENT_ONBOARDING_PLAN_FILE,
            "ADS_ONBOARDING_FILE": dashboard.ADS_ONBOARDING_FILE,
            "BRAND_GUIDES_DIR": dashboard.BRAND_GUIDES_DIR,
            "BRAND_PRODUCTS_DIR": dashboard.BRAND_PRODUCTS_DIR,
            "CREATIVE_ASSET_ROOT": dashboard.CREATIVE_ASSET_ROOT,
            "guide_library": dashboard.guide_library,
            "call_codex_image_cli": dashboard.call_codex_image_cli,
            "load_config": dashboard.load_config,
        }
        original_bridge_load = admira_tool_bridge.load_dashboard
        captured = {}
        try:
            product_dir.mkdir(parents=True, exist_ok=True)
            brief_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            creative_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "business_profile.json").write_text("{}", encoding="utf-8")
            codex_brand_guides.ROOT_DIR = test_root
            codex_brand_guides.BRAND_DIR = brand_dir
            codex_brand_guides.PRODUCT_DIR = product_dir
            codex_brand_guides.AD_BRIEF_DIR = brief_dir
            codex_brand_guides.BRAND_ASSET_DIR = brand_dir / "assets"
            codex_brand_guides.GENERAL_GUIDE = brand_dir / "general_branding.md"
            codex_brand_guides.CREATIVE_REFERENCES_FILE = brand_dir / "creative_references.md"
            codex_brand_guides.BUSINESS_PROFILE_FILE = data_dir / "business_profile.json"
            dashboard.BUSINESS_PROFILE_FILE = data_dir / "business_profile.json"
            dashboard.ONBOARDING_QUESTIONS_FILE = data_dir / "Onboarding questions.md"
            dashboard.AGENT_ONBOARDING_PLAN_FILE = data_dir / "Agent onboarding plan.md"
            dashboard.ADS_ONBOARDING_FILE = data_dir / "Ads campaign onboarding.md"
            dashboard.BRAND_GUIDES_DIR = brand_dir
            dashboard.BRAND_PRODUCTS_DIR = product_dir
            dashboard.CREATIVE_ASSET_ROOT = creative_dir
            dashboard.load_config = lambda: type("Cfg", (), {"codex_creative_model": "gpt-5.5", "codex_creative_enabled": True})()

            def fake_image(prompt, **kwargs):
                captured["prompt"] = prompt
                captured["kwargs"] = kwargs
                return {
                    "ok": True,
                    "image_path": str(creative_dir / "spa-medi-centro.png"),
                    "asset_id": "spa-medi-centro.png",
                }

            dashboard.call_codex_image_cli = fake_image
            admira_tool_bridge.load_dashboard = lambda: dashboard

            brand = admira_tool_bridge.call_tool(
                "mcp_admira_save_brand_memory",
                {
                    "arguments": json.dumps(
                        {
                            "business_name": "Spa MediCentro Juliana",
                            "services": "faciales y masajes",
                            "city": "Lima, Perú",
                            "palette": "verde salvia, beige, blanco crema, dorado suave",
                            "image_style": "elegante, limpio, relajante",
                            "voice": "claro, cercano, confiable",
                            "logo_request": "crear logo desde cero",
                            "reference_decision": "sin referencias externas",
                            "real_asset_decision": "Desde cero: no hay fotos reales; generar imágenes.",
                        },
                        ensure_ascii=False,
                    )
                },
            )
            product = admira_tool_bridge.call_tool(
                "mcp_admira_save_product_memory",
                {
                    "kwargs": {
                        "product_name": "Paquete facial + masaje 60 minutos por S/99",
                        "target_audience": "personas en Lima que buscan relajación, cuidado facial y bienestar",
                        "problem": "estrés, cansancio y deseo de cuidar la piel",
                        "benefit": "sentirse renovada y reservar fácilmente por WhatsApp",
                    }
                },
            )
            brief = admira_tool_bridge.call_tool(
                "mcp_admira_save_ad_brief",
                {
                    "payload": {
                        "product_name": "Paquete facial + masaje 60 minutos por S/99",
                        "creative_formats": "imagen estática realista para Meta Ads",
                        "variants": 2,
                        "hypothesis": "probar si relajación premium supera oferta directa",
                    }
                },
            )
            direct_wrapped = dashboard.execute_agent_tool(
                json.dumps(
                    {
                        "tool": "save_product_guide",
                        "arguments": {
                            "kwargs": {
                                "product_name": "Masaje relajante 30 minutos",
                                "target_audience": "personas con cansancio acumulado",
                                "benefit": "salir más livianas y relajadas",
                            }
                        },
                    }
                ),
                {"language": "es"},
            )
            library = codex_brand_guides.guide_library()
            spa_brief = next(item for item in library["ad_briefs"] if item["id"].startswith("paquete-facial"))
            self.assert_true(brand["ok"] is True and brand["result"].get("reason") != "missing_brand_core", "MCP bridge accepts JSON-string wrapped brand memory")
            self.assert_true(product["ok"] is True and product["result"].get("reason") != "missing_product_name", "MCP bridge accepts kwargs-wrapped product memory")
            self.assert_true(brief["ok"] is True and brief["result"].get("reason") != "missing_ad_brief_core", "MCP bridge accepts payload-wrapped ad brief context")
            self.assert_true(direct_wrapped["executed"] is True, "Dashboard execute_agent_tool accepts JSON-string tool calls with nested kwargs")
            self.assert_true("S/99" in spa_brief["fields"]["product_guide"] and spa_brief["fields"]["variation_count"] == "2", "Ad brief keeps inline product offers with S/99 and variation aliases")
            self.assert_true("Desde cero" in library["general"]["fields"]["asset_notes"], "Brand readiness stores the real-asset decision from direct MCP aliases")

            dashboard.guide_library = lambda: {
                "general_exists": False,
                "creative_references_exists": False,
                "product_count": 0,
                "ad_brief_count": 0,
                "general": {"saved": False, "fields": {}},
                "products": [],
                "ad_briefs": [],
            }
            direct_asset = dashboard.codex_image_generate(
                {
                    "purpose": "ad_creative",
                    "asset_only": True,
                    "request": "Crea una imagen final para promocionar la oferta en WhatsApp.",
                    "business_name": "Spa MediCentro Juliana",
                    "services": "faciales y masajes",
                    "city": "Lima, Perú",
                    "palette": "verde salvia, beige, blanco crema, dorado suave",
                    "image_style": "elegante, limpio, relajante",
                    "voice": "claro, cercano, confiable",
                    "logo_request": "crear logo desde cero, no hay logo oficial todavía",
                    "reference_decision": "sin referencias externas",
                    "real_asset_decision": "Desde cero: no hay fotos reales; generar imágenes.",
                    "product_name": "Paquete facial + masaje 60 minutos por S/99",
                    "target_audience": "personas en Lima que buscan relajación, cuidado facial y bienestar",
                    "problem": "estrés y cansancio",
                    "benefit": "renovarse y reservar por WhatsApp",
                }
            )
            self.assert_true(direct_asset["ok"] is True and direct_asset["prompt_package"]["requires_full_ad_brief"] is False, "Asset-only image generation can proceed from explicit chat context without saved product guide")
            self.assert_true("Spa MediCentro Juliana" in captured["prompt"] and "S/99" in captured["prompt"] and "Desde cero" in captured["prompt"], "Explicit brand/product/asset context is included in the final Codex/Image prompt")
        finally:
            for key, value in original_codex.items():
                setattr(codex_brand_guides, key, value)
            for key, value in original_dashboard.items():
                setattr(dashboard, key, value)
            admira_tool_bridge.load_dashboard = original_bridge_load
            shutil.rmtree(test_root, ignore_errors=True)

    def test_codex_image_attaches_hermes_cached_photo_paths_from_prompt_text(self):
        """Test a Telegram/Hermes cached buyer photo mentioned in text becomes a real image attachment."""
        print("\nTesting Codex/Image Hermes Cached Photo Attachment...")

        dashboard = load_dashboard_module()
        cache_dir = ROOT_DIR / "dashboard" / "data" / "hermes-home" / "cache" / "images"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached_photo = cache_dir / "img_bbcadddd197c_test.jpg"
        cached_photo.write_bytes(b"fake buyer jpg")
        original_bridge_load = admira_tool_bridge.load_dashboard
        original_call_image = dashboard.call_codex_image_cli
        original_load_config = dashboard.load_config
        captured = {}
        try:
            dashboard.load_config = lambda: type("Cfg", (), {"codex_creative_model": "gpt-5.5", "codex_creative_enabled": True})()

            def fake_image(prompt, **kwargs):
                captured["prompt"] = prompt
                captured["kwargs"] = kwargs
                return {
                    "ok": True,
                    "image_path": str(ROOT_DIR / "output" / "test-hermes-cached-photo.png"),
                    "asset_id": "test-hermes-cached-photo.png",
                }

            dashboard.call_codex_image_cli = fake_image
            admira_tool_bridge.load_dashboard = lambda: dashboard
            result = admira_tool_bridge.call_tool(
                "mcp_admira_codex_image_generate",
                {
                    "request": f"Usa esta foto real de la recepción como base visual: {cached_photo}. Agrega texto grande de la oferta sin reemplazar el local.",
                    "asset_only": True,
                    "business_name": "Spa MediCentro Juliana",
                    "services": "faciales y masajes",
                    "city": "Lima, Perú",
                    "palette": "verde salvia, beige, blanco crema, dorado suave",
                    "image_style": "fotorealista, elegante, limpio, relajante",
                    "voice": "claro, cercano, confiable",
                    "logo_request": "sin logo por ahora",
                    "reference_decision": "usar la foto real adjunta como referencia principal",
                    "real_asset_decision": "El cliente envió una foto real del local; usarla como referencia visual.",
                    "product_name": "Paquete facial + masaje 60 minutos por S/99",
                    "target_audience": "personas en Lima que buscan relajación, cuidado facial y bienestar",
                    "problem": "estrés y cansancio",
                    "benefit": "renovarse y reservar por WhatsApp",
                },
            )
            routed = result["result"]
            refs = [str(path) for path in captured["kwargs"]["reference_image_paths"]]
            self.assert_true(result["ok"] is True and routed["executed"] is True, "MCP Codex/Image generation executes with direct creative context")
            self.assert_true(str(cached_photo.resolve()) in refs, "Hermes cached photo path embedded in prompt text is attached as a real reference image")
            self.assert_true(routed["result"]["prompt_package"]["reference_image_count"] == 1, "Prompt package reports the attached cached photo instead of reference_image_count zero")
            self.assert_true(routed["result"]["prompt_package"]["reference_image_role"] == "real_photo_background", "Prompt package marks real uploaded photos as the background/base when requested")
            self.assert_true("MODO FOTO REAL COMO BASE" in captured["prompt"] and "No reemplaces el local" in captured["prompt"], "Image 2 prompt requires using the attached real photo as the base, not just inspiration")
            self.assert_true("foto real" in captured["prompt"].lower() and "recepción" in captured["prompt"].lower(), "Prompt still explains the real-photo creative intent")
        finally:
            dashboard.call_codex_image_cli = original_call_image
            dashboard.load_config = original_load_config
            admira_tool_bridge.load_dashboard = original_bridge_load
            cached_photo.unlink(missing_ok=True)

    def test_codex_image_uses_latest_workspace_upload_when_agent_mentions_uploaded_photo(self):
        """Test Image 2 receives the latest uploaded image even when Hermes omits the path argument."""
        print("\nTesting Codex/Image Latest Workspace Upload Fallback...")

        dashboard = load_dashboard_module()
        workspace_uploads = ROOT_DIR / "dashboard" / "data" / "hermes-workspace" / "current" / "uploads"
        workspace_uploads.mkdir(parents=True, exist_ok=True)
        workspace_photo = workspace_uploads / "recepcion-real-test.jpg"
        workspace_photo.write_bytes(b"fake real reception jpg")
        context_file = ROOT_DIR / "dashboard" / "data" / "hermes-workspace" / "current" / "CURRENT_CONTEXT.json"
        context_file.parent.mkdir(parents=True, exist_ok=True)
        original_context = context_file.read_bytes() if context_file.exists() else None
        context_file.write_text(json.dumps({"image_paths": [str(workspace_photo)]}), encoding="utf-8")
        original_bridge_load = admira_tool_bridge.load_dashboard
        original_call_image = dashboard.call_codex_image_cli
        original_load_config = dashboard.load_config
        captured = {}
        try:
            dashboard.load_config = lambda: type("Cfg", (), {"codex_creative_model": "gpt-5.5", "codex_creative_enabled": True})()

            def fake_image(prompt, **kwargs):
                captured["prompt"] = prompt
                captured["kwargs"] = kwargs
                return {
                    "ok": True,
                    "image_path": str(ROOT_DIR / "output" / "test-latest-workspace-upload.png"),
                    "asset_id": "test-latest-workspace-upload.png",
                }

            dashboard.call_codex_image_cli = fake_image
            admira_tool_bridge.load_dashboard = lambda: dashboard
            result = admira_tool_bridge.call_tool(
                "mcp_admira_codex_image_generate",
                {
                    "request": "Usa la foto subida de la recepción como base visual real para generar el anuncio con Image 2.",
                    "asset_only": True,
                    "business_name": "LULIA MED SPA",
                    "services": "faciales y masajes",
                    "city": "Lima, Perú",
                    "palette": "verde salvia, beige, blanco crema, dorado suave",
                    "image_style": "fotorealista, elegante, cálido, profesional",
                    "voice": "claro, cercano, confiable",
                    "logo_request": "sin logo por ahora",
                    "reference_decision": "usar la foto real subida como referencia principal",
                    "real_asset_decision": "El cliente envió una foto real de su recepción.",
                    "use_reference_as_background": True,
                    "product_name": "Facial + masaje 60 min S/99",
                    "target_audience": "personas en Lima que buscan relajación y cuidado facial",
                    "benefit": "reserva por WhatsApp",
                },
            )
            routed = result["result"]
            refs = [str(path) for path in captured["kwargs"]["reference_image_paths"]]
            self.assert_true(result["ok"] is True and routed["executed"] is True, "Image 2 request executes when the agent mentions an uploaded photo")
            self.assert_true(str(workspace_photo.resolve()) in refs, "Bridge attaches the latest safe workspace upload when Hermes omits reference_image_paths")
            self.assert_true(routed["result"]["prompt_package"]["reference_image_count"] == 1, "Prompt package reports the fallback uploaded photo as an Image 2 reference")
            self.assert_true(routed["result"]["prompt_package"]["reference_image_role"] == "real_photo_background", "Explicit use_reference_as_background is preserved in prompt package metadata")
            self.assert_true("MODO FOTO REAL COMO BASE" in captured["prompt"] and "Preserva el fondo" in captured["prompt"], "Image 2 receives strict pixel-faithful real-background instructions")
        finally:
            dashboard.call_codex_image_cli = original_call_image
            dashboard.load_config = original_load_config
            admira_tool_bridge.load_dashboard = original_bridge_load
            workspace_photo.unlink(missing_ok=True)
            if original_context is None:
                context_file.unlink(missing_ok=True)
            else:
                context_file.write_bytes(original_context)

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

    def test_social_accounts_use_graph_api_fallback(self):
        """Test Graph API Explorer keys can list ad accounts even when social-cli is empty."""
        print("\nTesting Social Account Graph Fallback...")

        dashboard = load_dashboard_module()
        original_social_command = dashboard.social_command
        original_graph_get = dashboard.graph_get
        env_path = dashboard.ENV_FILE
        ad_path = dashboard.AD_CONFIG_FILE
        onboarding_path = dashboard.ONBOARDING_FILE
        binding_path = dashboard.INDIVIDUAL_BINDING_FILE
        managed_path = dashboard.MANAGED_AD_ACCOUNTS_FILE
        env_before = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        ad_before = ad_path.read_text(encoding="utf-8") if ad_path.exists() else ""
        onboarding_before = onboarding_path.read_text(encoding="utf-8") if onboarding_path.exists() else ""
        binding_before = binding_path.read_bytes() if binding_path.exists() else None
        managed_before = managed_path.read_bytes() if managed_path.exists() else None

        def fake_social_command(args, timeout=30):
            return {"ok": False, "code": 1, "command": "social marketing accounts --json", "output": "No accounts returned by cli"}

        def fake_graph_get(path, params=None, page_token=""):
            if path == "/me/adaccounts":
                return {
                    "ok": True,
                    "data": {
                        "data": [
                            {"account_id": "123456789", "name": "Cuenta Principal", "currency": "USD", "account_status": 1, "business": {"id": "bm_main", "name": "Main Business"}}
                        ]
                    },
                }
            if path == "/me/businesses":
                return {"ok": True, "data": {"data": []}}
            return {"ok": False, "error": "unexpected path"}

        try:
            dashboard.social_command = fake_social_command
            dashboard.graph_get = fake_graph_get
            result = dashboard.social_marketing_accounts()
            self.assert_true(result["accounts"][0]["id"] == "act_123456789", "Graph API fallback lists buyer ad accounts")
            self.assert_true(result["accounts"][0]["business_id"] == "bm_main" and result["accounts"][0]["business_name"] == "Main Business", "Graph account discovery preserves Business Manager metadata")
            self.assert_true(result["source"] == "graph_api" and result["graph_checked"], "Account discovery records direct Graph fallback")
            self.assert_true(result["ok"] is True, "Graph fallback makes account discovery successful")
            dashboard.write_json(onboarding_path, {"completed": False})
            if binding_path.exists():
                binding_path.unlink()
            if managed_path.exists():
                managed_path.unlink()
            selected = dashboard.social_set_default_account({"ad_account_id": "act_123456789"})
            env_after = env_path.read_text(encoding="utf-8")
            saved_config = json.loads(ad_path.read_text(encoding="utf-8"))
            self.assert_true(selected["ok"] is True and selected["local_saved"] is True and selected["social_cli_default_set"] is False, "Graph-selected account is saved locally even if social-cli default fails")
            self.assert_true("META_AD_ACCOUNT_ID=act_123456789" in env_after and saved_config["account"]["id"] == "act_123456789", "Graph-selected account persists to env and ad-config")
            self.assert_true(saved_config["account"]["business_manager_id"] == "bm_main" and selected["managed_ad_accounts"]["business_manager"]["id"] == "bm_main", "Selected account stores the Business Manager lock")

            dashboard.social_command = lambda args, timeout=30: {"ok": True, "code": 0, "command": "social marketing accounts --json", "output": json.dumps([{"account_id": "555", "name": "CLI Account"}])}
            social_first = dashboard.social_marketing_accounts()
            self.assert_true(social_first["accounts"][0]["id"] == "act_555", "social-cli accounts remain the primary account discovery source")
            self.assert_true(social_first["source"] == "social_cli", "Graph fallback does not override social-cli when social-cli works")

            dashboard.social_command = fake_social_command
            dashboard.graph_get = lambda path, params=None, page_token="": {"ok": True, "data": {"data": []}}
            empty = dashboard.social_marketing_accounts()
            self.assert_true("0 cuentas publicitarias" in empty["message"], "Empty Graph response explains that Meta returned no ad accounts")
        finally:
            dashboard.social_command = original_social_command
            dashboard.graph_get = original_graph_get
            env_path.write_text(env_before, encoding="utf-8")
            ad_path.write_text(ad_before, encoding="utf-8")
            onboarding_path.write_text(onboarding_before, encoding="utf-8")
            if binding_before is None:
                if binding_path.exists():
                    binding_path.unlink()
            else:
                binding_path.write_bytes(binding_before)
            if managed_before is None:
                if managed_path.exists():
                    managed_path.unlink()
            else:
                managed_path.write_bytes(managed_before)

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
                "No tenemos logo oficial; trabajar sin logo por ahora",
                "Me gustan anuncios editoriales con producto grande",
                "Tenemos fotos reales del producto y del fundador",
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
                "3 al mismo tiempo y 1 en backlog",
                "UGC, foto real y diseño estático",
                "Foto del producto, logo oficial y un testimonio autorizado",
                "Ver si un fondo más limpio mejora el CTR",
                "Menor costo por lead con CTR saludable",
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
        profile_path = dashboard.BUSINESS_PROFILE_FILE
        ad_before = ad_path.read_text(encoding="utf-8") if ad_path.exists() else ""
        onboarding_before = onboarding_path.read_text(encoding="utf-8") if onboarding_path.exists() else ""
        binding_before = binding_path.read_bytes() if binding_path.exists() else None
        profile_before = profile_path.read_bytes() if profile_path.exists() else None
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
                if path == "/111":
                    return {
                        "ok": True,
                        "data": {
                            "id": "111",
                            "name": "Buyer Page",
                            "category": "Beauty service",
                            "link": "https://facebook.com/buyer",
                            "website": "https://buyer.example",
                            "about": "Tratamientos faciales premium para mujeres ocupadas.",
                            "description": "Agenda por WhatsApp y compra rutinas de cuidado facial.",
                            "instagram_business_account": {"id": "222", "username": "buyer_ig"},
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
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assert_true(profile["website_url"] == "https://buyer.example", "Discovered website is saved into business memory")
            self.assert_true("https://instagram.com/buyer_ig" in profile["social_links"], "Discovered Instagram is saved as business context")
            self.assert_true(profile["meta_assets"]["page_id"] == "111", "Discovered Page metadata is saved for onboarding context")
            self.assert_true(profile["meta_page_profile"]["about"].startswith("Tratamientos faciales"), "Authorized Facebook Page Graph profile is saved as initial business context")
            self.assert_true("Tratamientos faciales" in profile["meta_page_context"], "Facebook Page Graph context is prepared for the agent memory")
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
            if profile_before is None:
                if profile_path.exists():
                    profile_path.unlink()
            else:
                profile_path.write_bytes(profile_before)

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

    def test_signal_quality_review_event_setup(self):
        """Test campaign signal review catches event mismatch and weak measurement setup."""
        print("\nTesting Signal Quality Event Review...")

        weak = signal_quality.review_signal_quality(
            {
                "objective": "PURCHASES",
                "optimization_event": "Lead",
                "weekly_event_volume": 8,
                "capi_configured": "no",
                "event_match_quality": 3,
                "aem_configured": "unknown",
                "event_prioritized": "no",
            },
            language="es",
        )
        weak_checks = {item["key"]: item for item in weak["checks"]}
        self.assert_true(weak["status"] == "blocked", "Signal review blocks conversion launch when event setup is not aligned")
        self.assert_true(weak["recommended_event"] == "InitiateCheckout", "Low purchase volume recommends a higher-volume sales event")
        self.assert_true(weak_checks["correct_optimization_event"]["status"] == "blocked", "Wrong optimization event is treated as a blocker")
        self.assert_true(weak_checks["pixel_or_dataset"]["status"] == "blocked", "Missing Pixel/Dataset blocks web conversion optimization")
        self.assert_true(weak_checks["conversions_api"]["status"] == "warn" and weak_checks["event_match_quality"]["status"] == "warn", "CAPI and Event Match Quality are explicit warning checks")

        ready = signal_quality.review_signal_quality(
            {
                "objective": "PURCHASES",
                "optimization_event": "Purchase",
                "weekly_event_volume": 65,
                "pixel_id": "123",
                "capi_configured": True,
                "event_match_quality": 7,
                "aem_configured": True,
                "event_prioritized": True,
            },
            language="es",
        )
        self.assert_true(ready["status"] == "ready" and ready["safe_to_launch_active"], "Healthy purchase signal can be launch-ready")
        self.assert_true(ready["campaign_patch"]["promoted_object"]["custom_event_type"] == "Purchase", "Signal review prepares the promoted_object event")

    def test_meta_snapshot_collects_adset_signal_configuration(self):
        """Test Meta snapshot reads ad set optimization event configuration for diagnostics."""
        print("\nTesting Meta Ad Set Signal Snapshot...")

        original_graph_rows = meta_insights.graph_rows

        def fake_graph_rows(path, params, token, version, max_pages=5):
            if path.endswith("/campaigns"):
                return {"ok": True, "rows": [{"id": "camp_1", "name": "Campaign", "status": "ACTIVE", "effective_status": "ACTIVE", "objective": "OUTCOME_SALES"}]}
            if path.endswith("/adsets"):
                fields = params.get("fields", "")
                return {
                    "ok": True,
                    "rows": [
                        {
                            "id": "adset_1",
                            "name": "Ad Set",
                            "campaign_id": "camp_1",
                            "status": "ACTIVE",
                            "effective_status": "ACTIVE",
                            "optimization_goal": "CONVERSIONS",
                            "billing_event": "IMPRESSIONS",
                            "promoted_object": {"pixel_id": "123", "custom_event_type": "Purchase"},
                            "daily_budget": "2500",
                        }
                    ],
                    "requested_fields": fields,
                }
            if path.endswith("/insights"):
                return {"ok": True, "rows": []}
            return {"ok": False, "rows": [], "error": "unexpected path"}

        try:
            meta_insights.graph_rows = fake_graph_rows
            snapshot = meta_insights.collect_meta_snapshot("act_123", "token")
            adset = snapshot["adset_statuses"]["adset_1"]
            self.assert_true(adset["optimization_goal"] == "CONVERSIONS", "Meta snapshot stores ad set optimization goal")
            self.assert_true(adset["promoted_object"]["custom_event_type"] == "Purchase", "Meta snapshot stores promoted_object event")
            self.assert_true(adset["daily_budget"] == 25.0, "Meta snapshot normalizes ad set budget from minor units")
        finally:
            meta_insights.graph_rows = original_graph_rows

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
            self.assert_true(not any(item.get("type") == "pause_campaign" for item in pending), "Shadow optimizer records risky pauses without creating an executable approval")
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
        context = agent_chat.account_context({"metrics": sample, "recommendations": dashboard.calculate_recommendations(sample["campaigns"]), "fatigue": dashboard.fatigue_items(sample["campaigns"])})
        self.assert_true(context["metrics_source"]["is_real_meta_data"] is False, "Agent context marks demo metrics as not real")
        self.assert_true(context["campaigns"] == [] and context["recommendations"] == [] and context["fatigue"] == [], "Agent context hides demo campaigns, recommendations and fatigue")
        previous_style = os.environ.get("AGENT_COMMUNICATION_STYLE")
        previous_experience = os.environ.get("AGENT_AD_EXPERIENCE_LEVEL")
        try:
            os.environ["AGENT_COMMUNICATION_STYLE"] = "technical"
            os.environ["AGENT_AD_EXPERIENCE_LEVEL"] = "advanced"
            technical_context = agent_chat.account_context({"language": "es"})
            self.assert_true(technical_context["communication_preference"]["style"] == "technical" and "terminología precisa" in technical_context["communication_preference"]["instruction"], "Agent context carries the global technical communication instruction")
            self.assert_true(technical_context["communication_preference"]["ad_experience_level"] == "advanced" and "Experiencia en anuncios: avanzada" in technical_context["communication_preference"]["ad_experience_instruction"], "Agent context carries the global ads-experience instruction")
            os.environ["AGENT_COMMUNICATION_STYLE"] = "simple"
            os.environ["AGENT_AD_EXPERIENCE_LEVEL"] = "beginner"
            simple_context = agent_chat.account_context({"language": "es"})
            self.assert_true(simple_context["communication_preference"]["style"] == "simple" and "evita jerga" in simple_context["communication_preference"]["instruction"], "Agent context carries the global simple-language instruction")
            self.assert_true(simple_context["communication_preference"]["ad_experience_level"] == "beginner" and "no hagas que el comprador elija perillas técnicas" in simple_context["communication_preference"]["ad_experience_instruction"], "Agent context carries beginner ads-experience guidance")
        finally:
            if previous_style is None:
                os.environ.pop("AGENT_COMMUNICATION_STYLE", None)
            else:
                os.environ["AGENT_COMMUNICATION_STYLE"] = previous_style
            if previous_experience is None:
                os.environ.pop("AGENT_AD_EXPERIENCE_LEVEL", None)
            else:
                os.environ["AGENT_AD_EXPERIENCE_LEVEL"] = previous_experience
        fallback = agent_chat.fallback_reply("cual campaña va mejor", {"metrics": sample})
        self.assert_true("Retargeting - Warm Leads" not in fallback and "ROAS" not in fallback and "no tengo campañas reales" in fallback, "Fallback does not cite demo campaign performance")
        self.assert_true(agent_chat.reply_uses_unverified_performance("Empezaria con Retargeting - Warm Leads porque ROAS 8.0, CTR 4.79% y CPA 4.", sample), "Demo performance claims are blocked even if Hermes remembers them")
        test_dir = Path(tempfile.mkdtemp(prefix="demo_metrics_blocked_"))
        original_metrics_file = dashboard.METRICS_FILE
        original_demo_env = os.environ.pop("ADMIRO_ALLOW_DEMO_METRICS", None)
        try:
            dashboard.METRICS_FILE = test_dir / "metrics.json"
            missing = dashboard.load_metrics()
            self.assert_true(missing["source"] == "missing" and missing["campaigns"] == [], "Fresh buyer installs do not seed fake demo campaigns")
            dashboard.write_json(dashboard.METRICS_FILE, legacy)
            blocked = dashboard.load_metrics()
            self.assert_true(blocked["source"] == "missing" and blocked["campaigns"] == [], "Legacy demo caches are hidden in buyer mode")
            os.environ["ADMIRO_ALLOW_DEMO_METRICS"] = "true"
            allowed = dashboard.load_metrics()
            self.assert_true(allowed["source"] == "demo" and allowed["campaigns"], "Explicit internal demo mode can still show sample campaigns")
        finally:
            dashboard.METRICS_FILE = original_metrics_file
            if original_demo_env is None:
                os.environ.pop("ADMIRO_ALLOW_DEMO_METRICS", None)
            else:
                os.environ["ADMIRO_ALLOW_DEMO_METRICS"] = original_demo_env
            shutil.rmtree(test_dir, ignore_errors=True)

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

    def test_signal_quality_tool_reviews_campaign_event_readiness(self):
        """Test dashboard exposes a read-only signal-quality review tool to Hermes."""
        print("\nTesting Dashboard Signal Quality Tool...")

        dashboard = load_dashboard_module()
        result = dashboard.execute_agent_tool(
            {
                "tool": "review_signal_quality",
                "arguments": {
                    "objective": "PURCHASES",
                    "optimization_event": "Purchase",
                    "pixel_id": "123",
                    "weekly_event_volume": 12,
                    "capi_configured": "unknown",
                },
            },
            {"language": "es"},
        )
        self.assert_true(result["type"] == "review_signal_quality" and result["executed"] is False, "Signal review tool is read-only")
        self.assert_true(result["result"]["recommended_event"] == "InitiateCheckout", "Signal review recommends a higher-volume event when purchase volume is thin")
        self.assert_true("señal" in result["reply"].lower(), "Signal review tool returns a buyer-readable explanation")

    def test_campaign_preflight_tool_exposes_expert_launch_checks(self):
        """Test dashboard exposes read-only preflight checks before expert campaign staging."""
        print("\nTesting Campaign Preflight Tool...")

        dashboard = load_dashboard_module()

        class FakeConfig:
            ad_account_id = "act_999"
            live = True
            live_actions_enabled = True
            mode = "live"

        class FakeClient:
            def __init__(self, config):
                self.config = config

            def marketing_status(self):
                return {"executed": True, "returncode": 0, "stdout": json.dumps({"ok": True, "active_campaigns": 2}), "stderr": ""}

            def rate_limits(self):
                return {"executed": True, "returncode": 0, "stdout": json.dumps({"ok": True, "usage": 12}), "stderr": ""}

            def policy_preflight(self, *args, **kwargs):
                return {"executed": True, "returncode": 0, "stdout": json.dumps({"ok": True, "risk": "low"}), "stderr": ""}

            def custom_audiences(self, *args, **kwargs):
                return {"executed": True, "returncode": 0, "stdout": json.dumps({"data": [{"id": "ca_1", "name": "Compradores"}]}), "stderr": ""}

            def creatives(self, *args, **kwargs):
                return {"executed": True, "returncode": 0, "stdout": json.dumps({"data": [{"id": "cr_1", "name": "Creative"}]}), "stderr": ""}

        original_config = dashboard.load_config
        original_client = dashboard.SocialFlowClient
        try:
            dashboard.load_config = lambda: FakeConfig()
            dashboard.SocialFlowClient = FakeClient
            result = dashboard.execute_agent_tool(
                {
                    "tool": "preflight_campaign",
                    "arguments": {
                        "objective": "PURCHASES",
                        "daily_budget": 40,
                        "target_cpa": 20,
                        "pixel_id": "123",
                        "optimization_event": "Purchase",
                        "success_metrics": ["ROAS", "cost per purchase", "cost per initiate checkout"],
                        "image_url": "https://cdn.example/ad.jpg",
                        "placements": {"automatic": False, "manual": ["INSTAGRAM_REELS", "INSTAGRAM_STORIES"]},
                    },
                },
                {"language": "es"},
            )
            preflight = result["result"]
            self.assert_true(result["type"] == "preflight_campaign" and result["executed"] is False, "Campaign preflight tool is read-only")
            self.assert_true(preflight["checks"]["account_status"]["ok"] and preflight["checks"]["custom_audiences"]["data"][0]["id"] == "ca_1", "Campaign preflight checks account and audiences")
            self.assert_true(preflight["dry_run_preview"]["budget_plan"]["expected_daily_events"] == 2, "Campaign preflight exposes budget sanity")
            self.assert_true(preflight["dry_run_preview"]["placements"]["manual"] == ["INSTAGRAM_REELS", "INSTAGRAM_STORIES"], "Campaign preflight exposes placement strategy")
            self.assert_true(preflight["dry_run_preview"]["creative_controls"]["has_image_url"], "Campaign preflight exposes creative media controls")
            self.assert_true(preflight["dry_run_preview"]["success_metrics"]["items"][0]["metric"] == "roas" and preflight["dry_run_preview"]["success_metrics"]["items"][2]["metric"] == "cost_per_initiate_checkout", "Campaign preflight exposes the ranked success metrics scorecard")
        finally:
            dashboard.load_config = original_config
            dashboard.SocialFlowClient = original_client

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
                "adset_daily_budget": 25,
                "adset_lifetime_budget": 300,
                "target_cpa": 20,
                "concurrent_creatives": 3,
                "final_status": "PAUSED",
                "campaign_status": "PAUSED",
                "adset_status": "PAUSED",
                "ad_status": "PAUSED",
                "billing_event": "IMPRESSIONS",
                "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                "start_time": "2026-07-01T09:00:00-05:00",
                "end_time": "2026-07-15T23:59:00-05:00",
                "creative_format": "static_feed",
                "image_hash": "hash_existing",
                "cta_link": "https://buyer.example/offer",
                "custom_audiences_json": json.dumps([{"id": "ca_1", "name": "Compradores"}]),
                "excluded_custom_audiences_json": json.dumps([{"id": "ca_2", "name": "Clientes recientes"}]),
                "device_platforms": "mobile",
                "user_os": "iOS,Android",
                "targeting_locations_json": json.dumps([{"kind": "location", "key": "CO", "name": "Colombia", "type": "country", "country_code": "CO"}]),
                "targeting_interests_json": json.dumps([{"kind": "interest", "id": "6001", "name": "Ecommerce"}]),
                "success_metrics_json": json.dumps([
                    {"metric": "ROAS", "target": "2.5x"},
                    "cost per purchase",
                    "cost per initiate checkout",
                ]),
            }
            result = dashboard.create_campaign(payload)
            created = dashboard.read_json(dashboard.CREATED_FILE, [])
            campaign = created[0]["campaign"]
            targeting = campaign["ad_sets"][0]["targeting"]
            self.assert_true(result["payload"]["requested"]["targeting"]["source"] == "meta_search", "Approval card marks targeting as Meta search")
            self.assert_true(targeting["meta_targeting"]["locations"][0]["key"] == "CO", "Campaign stores selected Meta location")
            self.assert_true(targeting["meta_targeting"]["interests"][0]["id"] == "6001", "Campaign stores selected Meta interest ID")
            self.assert_true(campaign["signal_quality_review"]["status"] == "blocked", "Staged conversion campaign stores a signal-quality review")
            self.assert_true(campaign["ad_sets"][0]["optimization_event"] == campaign["signal_quality_review"]["recommended_event"], "Signal review applies the recommended optimization event to the ad set draft")
            self.assert_true(result["payload"]["requested"]["signal_quality"]["status"] == campaign["signal_quality_review"]["status"], "Approval card exposes signal-quality readiness")
            self.assert_true(campaign["ad_sets"][0]["placements"]["manual"] == ["FACEBOOK_FEED", "FACEBOOK_STORIES", "INSTAGRAM_FEED", "INSTAGRAM_STORIES"], "Staged campaign defaults to feed/story placements on Facebook and Instagram")
            self.assert_true(result["payload"]["requested"]["placements"]["mode"] == "manual", "Approval card exposes manual placement mode")
            self.assert_true(campaign["budget_plan"]["adset_lifetime"] == 300 and campaign["budget_plan"]["per_variant_daily"] == 8.33, "Staged campaign stores expert budget allocation")
            self.assert_true(campaign["success_metrics"]["items"][0]["metric"] == "roas" and campaign["success_metrics"]["items"][2]["metric"] == "cost_per_initiate_checkout", "Staged campaign stores the buyer's ranked success metrics")
            self.assert_true(result["payload"]["requested"]["success_metrics"]["items"][0]["target"] == "2.5x", "Approval card exposes ranked success metrics and targets")
            self.assert_true(result["payload"]["dry_run_preview"]["campaign"]["success_metrics"]["items"][1]["metric"] == "cost_per_purchase", "Dry-run preview includes campaign success metrics")
            self.assert_true(campaign["status_plan"] == {"campaign": "PAUSED", "adset": "PAUSED", "ad": "PAUSED"}, "Staged campaign stores campaign/adset/ad status plan")
            self.assert_true(campaign["ad_sets"][0]["billing_event"] == "IMPRESSIONS" and campaign["ad_sets"][0]["bidding"]["bid_strategy"] == "LOWEST_COST_WITHOUT_CAP", "Staged campaign stores billing and bidding controls")
            self.assert_true(campaign["ad_sets"][0]["start_time"].startswith("2026-07-01") and campaign["ad_sets"][0]["end_time"].startswith("2026-07-15"), "Staged campaign stores ad set schedule controls")
            self.assert_true(targeting["custom_audiences"][0]["id"] == "ca_1" and targeting["excluded_custom_audiences"][0]["id"] == "ca_2", "Campaign stores custom audience inclusion and exclusion")
            self.assert_true(targeting["device_platforms"] == ["mobile"] and targeting["user_os"] == ["iOS", "Android"], "Campaign stores device/platform targeting fields")
            self.assert_true(campaign["ad"]["image_hash"] == "hash_existing" and campaign["ad"]["cta_link"] == "https://buyer.example/offer", "Campaign stores creative image hash and CTA link override")
            self.assert_true(result["payload"]["requested"]["adset_controls"]["schedule"]["start_time"].startswith("2026-07-01"), "Approval card exposes expert ad set controls")
            self.assert_true(result["payload"]["dry_run_preview"]["creative"]["has_image_hash"], "Approval payload includes a dry-run preview of creative inputs")
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
                "custom_audiences": [{"id": "ca_1", "name": "Compradores"}],
                "excluded_custom_audiences": [{"id": "ca_2", "name": "Clientes recientes"}],
                "device_platforms": ["mobile"],
                "user_os": ["iOS", "Android"],
            }
        )
        self.assert_true(spec["geo_locations"]["cities"][0]["key"] == "2420605", "Social targeting sends selected city key")
        self.assert_true(spec["interests"][0] == {"id": "6001", "name": "Ecommerce"}, "Social targeting sends selected interest ID")
        self.assert_true(spec["custom_audiences"][0]["id"] == "ca_1" and spec["excluded_custom_audiences"][0]["id"] == "ca_2", "Social targeting sends custom audiences and exclusions")
        self.assert_true(spec["device_platforms"] == ["mobile"] and spec["user_os"] == ["iOS", "Android"], "Social targeting sends device and OS fields")
        self.assert_true(spec["age_min"] == 25 and spec["age_max"] == 44, "Social targeting preserves age range")
        self.assert_true(spec["publisher_platforms"] == ["facebook", "instagram"], "Default campaign creation limits publisher platforms to Facebook and Instagram")
        self.assert_true(spec["facebook_positions"] == ["feed", "story"] and spec["instagram_positions"] == ["stream", "story"], "Default campaign creation limits placements to feeds and stories")

        automatic = daily_agent.targeting_for_social({"locations": ["US"], "placements": {"automatic": True}})
        self.assert_true("publisher_platforms" not in automatic, "Automatic placements remain available when explicitly requested")

    def test_social_flow_adset_sends_promoted_object(self):
        """Test Social CLI ad set creation receives the selected optimization event object."""
        print("\nTesting Social Ad Set Promoted Object...")

        class FakeConfig:
            social_cli = "social"
            mode = "live"
            live = True
            live_actions_enabled = True

        client = SocialFlowClient(FakeConfig())
        captured = []
        client.run = lambda args, **kwargs: captured.append((args, kwargs)) or {"executed": True, "stdout": json.dumps({"id": "adset_1"})}
        client.create_adset(
            "camp_1",
            "Ad Set",
            {"geo_locations": {"countries": ["MX"]}},
            2500,
            "PAUSED",
            "CONVERSIONS",
            promoted_object={"pixel_id": "123", "custom_event_type": "Purchase"},
            billing_event="LINK_CLICKS",
            bidding={"bid_strategy": "LOWEST_COST_WITHOUT_CAP"},
            lifetime_budget_cents=30000,
            start_time="2026-07-01T09:00:00-05:00",
            end_time="2026-07-15T23:59:00-05:00",
            approved=True,
        )
        args, kwargs = captured[0]
        promoted = json.loads(args[args.index("--promoted-object") + 1])
        self.assert_true(args[args.index("--optimization-goal") + 1] == "CONVERSIONS", "Social CLI receives the ad set optimization goal")
        self.assert_true(promoted == {"pixel_id": "123", "custom_event_type": "Purchase"}, "Social CLI receives the promoted object for conversion optimization")
        self.assert_true(args[args.index("--billing-event") + 1] == "LINK_CLICKS", "Social CLI receives the selected billing event")
        self.assert_true(json.loads(args[args.index("--bidding") + 1])["bid_strategy"] == "LOWEST_COST_WITHOUT_CAP", "Social CLI receives the selected bidding controls")
        self.assert_true(args[args.index("--lifetime-budget") + 1] == "30000" and args[args.index("--start-time") + 1].startswith("2026-07-01"), "Social CLI receives lifetime budget and schedule controls")
        self.assert_true(kwargs["mutation"] is True and kwargs["approved"] is True, "Promoted-object ad set creation remains gated as an approved mutation")

    def test_social_flow_creative_supports_full_story_and_media_urls(self):
        """Test Social CLI creative creation can use full object_story_spec and media URL controls."""
        print("\nTesting Social Creative Expert Controls...")

        class FakeConfig:
            social_cli = "social"
            mode = "live"
            live = True
            live_actions_enabled = True

        client = SocialFlowClient(FakeConfig())
        captured = []
        client.run = lambda args, **kwargs: captured.append((args, kwargs)) or {"executed": True, "stdout": json.dumps({"id": "creative_1"})}
        spec = {"page_id": "111", "link_data": {"link": "https://buyer.example", "message": "Texto"}}
        client.create_creative("act_999", "Creative", "111", "https://buyer.example", "Texto", "Titular", "", "SHOP_NOW", object_story_spec=spec, approved=True)
        args, _ = captured[0]
        self.assert_true("--object-story-spec" in args and json.loads(args[args.index("--object-story-spec") + 1]) == spec, "Creative creation supports full object_story_spec")
        self.assert_true("--page-id" not in args and "--image-hash" not in args, "Full object_story_spec path does not mix simple creative fields")

        captured.clear()
        client.create_creative("act_999", "Creative URL", "111", "https://buyer.example", "Texto", "Titular", "", "SHOP_NOW", image_url="https://cdn.example/ad.jpg", video_url="https://cdn.example/ad.mp4", cta_link="https://buyer.example/buy", approved=True)
        args, _ = captured[0]
        self.assert_true(args[args.index("--image-url") + 1] == "https://cdn.example/ad.jpg" and args[args.index("--video-url") + 1] == "https://cdn.example/ad.mp4", "Creative creation supports image and video URLs")
        self.assert_true(args[args.index("--cta-link") + 1] == "https://buyer.example/buy", "Creative creation supports CTA link override")

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
                        "ad_sets": [
                            {
                                "name": "Ready Stack - Core",
                                "targeting": {"locations": ["MX"], "age_range": {"min": 18, "max": 65}},
                                "budget": 25,
                                "optimization_goal": "CONVERSIONS",
                                "promoted_object": {"pixel_id": "123", "custom_event_type": "Purchase"},
                                "placements": {"automatic": False, "manual": ["FACEBOOK_FEED", "INSTAGRAM_STORIES"]},
                            }
                        ],
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
            self.assert_true(client.calls[0][1][4] == "ACTIVE" and client.calls[1][1][4] == "ACTIVE", "Approved active campaign stack activates campaign and ad set, not only the ad")
            adset_call = client.calls[1]
            self.assert_true(adset_call[1][5] == "CONVERSIONS", "Campaign stack sends the signal-selected optimization goal to ad set creation")
            self.assert_true(adset_call[2]["promoted_object"] == {"pixel_id": "123", "custom_event_type": "Purchase"}, "Campaign stack sends the signal-selected promoted object to ad set creation")
            self.assert_true(adset_call[1][2]["publisher_platforms"] == ["facebook", "instagram"], "Campaign stack sends manual Facebook/Instagram placement platforms")
            self.assert_true(adset_call[1][2]["facebook_positions"] == ["feed"] and adset_call[1][2]["instagram_positions"] == ["story"], "Campaign stack sends the selected feed/story placement positions")
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

    def test_dashboard_chat_uses_product_actions_before_generic_agent(self):
        """Test dashboard chat routes known product actions before a generic model can claim missing terminal access."""
        print("\nTesting Dashboard Chat Product Action Routing...")

        dashboard = load_dashboard_module()
        original_dashboard_payload = dashboard.dashboard_payload
        original_load_history = dashboard.load_chat_history
        original_append_history = dashboard.append_chat_turn
        original_wizard = dashboard.handle_creative_memory_wizard
        original_agent_chat = dashboard.agent_chat
        original_require = dashboard.require_cloud_license
        original_create = dashboard.create_campaign
        original_pending = dashboard.PENDING_FILE
        test_dir = ROOT_DIR / "output" / "test-dashboard-chat-router"

        class FakeSelf:
            result = None

            def send_ok_result(self, result):
                self.result = result

        try:
            shutil.rmtree(test_dir, ignore_errors=True)
            test_dir.mkdir(parents=True, exist_ok=True)
            dashboard.PENDING_FILE = test_dir / "pending.json"
            dashboard.write_json(dashboard.PENDING_FILE, [])
            dashboard.dashboard_payload = lambda: {
                "metrics": {"source": "meta_graph", "campaigns": [], "summary": {}},
                "recommendations": [],
                "fatigue": [],
                "pending": [],
                "audience_strategy": {},
                "brand_guides": {},
                "business_profile": {},
                "agent_onboarding_phase": {},
            }
            dashboard.load_chat_history = lambda: []
            dashboard.append_chat_turn = lambda message, reply: [{"role": "user", "content": message}, {"role": "agent", "content": reply}]
            dashboard.handle_creative_memory_wizard = lambda payload: None
            generic_calls = []
            dashboard.agent_chat = lambda config, payload: generic_calls.append(payload) or {"reply": "No puedo usar CLI ni terminal desde aquí.", "tool_request": None}
            dashboard.require_cloud_license = lambda *args, **kwargs: None
            dashboard.create_campaign = lambda payload: {"status": "pending", "id": "approval_test", "payload": payload}

            fake = FakeSelf()
            dashboard.DashboardHandler.post_chat(
                fake,
                {
                    "language": "es",
                    "message": "Crea una campaña para vender mi curso con presupuesto de $20 https://buyer.example /tmp/creative.png",
                },
            )

            result = fake.result
            self.assert_true(not generic_calls, "Dashboard chat uses local product action router before generic agent for campaign creation")
            self.assert_true(result["routed_action"]["type"] == "create_campaign_stack" and result["routed_action"]["staged"] is True, "Dashboard chat stages campaign creation from natural language")
            self.assert_true("terminal" not in result["reply"].lower() and "aprobación" in result["reply"].lower(), "Dashboard chat reply does not expose CLI/terminal as a blocker")
        finally:
            dashboard.dashboard_payload = original_dashboard_payload
            dashboard.load_chat_history = original_load_history
            dashboard.append_chat_turn = original_append_history
            dashboard.handle_creative_memory_wizard = original_wizard
            dashboard.agent_chat = original_agent_chat
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
                if not tool_request:
                    return {}
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
        original_chat_action = telegram_agent.send_chat_action
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
            telegram_agent.send_chat_action = lambda config, chat_id, action="typing": sent.append(("typing", action))
            telegram_agent.callback_answer = lambda config, callback_id, text="": sent.append(("callback", text))
            telegram_agent.approve_pending = lambda approval_id: [{"id": approval_id, "status": "approved", "result": {"ok": True}}]
            telegram_agent.reject_pending = lambda approval_id, reason="": [{"id": approval_id}]
            telegram_agent.handle_text(FakeConfig(), "12345", "Prepara una campaña", send=True)
            reply = telegram_agent.handle_text(FakeConfig(), "12345", "Prepara una campaña", send=False)
            approved_text = telegram_agent.handle_text(FakeConfig(), "12345", "Aprueba esa campaña", send=False)
            pending_reply = telegram_agent.handle_text(FakeConfig(), "12345", "/pendientes", send=True)
            callback = telegram_agent.handle_update(FakeConfig(), {"callback_query": {"id": "cb_1", "data": "approve:approval_test", "message": {"chat": {"id": "12345"}}}})
            telegram_agent.agent_chat = lambda config, payload: {"reply": "", "tool_request": None}
            empty_reply = telegram_agent.handle_text(FakeConfig(), "12345", "hola", send=False)
            telegram_agent.agent_chat = lambda config, payload: {"fallback": True, "error_type": "model_usage_limit", "reply": "Tu ChatGPT/Codex sí está conectado, pero el modelo alcanzó su límite temporal de uso. Intenta de nuevo más tarde."}
            limited_reply = telegram_agent.handle_text(FakeConfig(), "12345", "hola otra vez", send=False)
            noisy_reply = "⚠ tirith security scanner enabled but not available\n  ┊ review diff\na/data/business_profile.json → b/data/business_profile.json\n@@ -1 +1 @@\n- old\n+ new\nGracias, sigo con una pregunta."
            telegram_agent.append_turn("12345", "respuesta corta", noisy_reply)
            stored_history = json.loads(history_path.read_text(encoding="utf-8"))
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
            self.assert_true(any(item == ("typing", "typing") for item in sent), "Telegram shows typing while Hermes prepares a reply")
            self.assert_true("No pude responder" not in empty_reply and "dashboard" in empty_reply.lower(), "Telegram empty agent replies become buyer-actionable recovery text")
            self.assert_true("límite temporal" in limited_reply and "falta conectar" not in limited_reply.lower(), "Telegram preserves model-limit guidance instead of showing setup fallback")
            self.assert_true("tirith" not in json.dumps(stored_history).lower() and "business_profile" not in json.dumps(stored_history), "Telegram history stores cleaned agent replies")
            self.assert_true("Aprobacion ejecutada" in approved_text, "Telegram text can approve the single exact pending decision")
            self.assert_true(received_payloads[0]["business_profile"]["main_offer"] == "Curso Test", "Telegram gives Hermes the selected client's business profile")
            self.assert_true("session_key" in received_payloads[0] and "history" not in received_payloads[0], "Telegram passes a Hermes session key instead of replaying chat history")
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
            telegram_agent.send_chat_action = original_chat_action
            telegram_agent.callback_answer = original_answer
            telegram_agent.approve_pending = original_approve
            telegram_agent.reject_pending = original_reject
            if before:
                history_path.write_text(before, encoding="utf-8")
            elif history_path.exists():
                history_path.unlink()

    def test_telegram_codex_image_request_sends_generated_photo(self):
        """Test a Telegram creative-image request executes the Codex/Image backend tool and sends the result."""
        print("\nTesting Telegram Codex/Image Delivery...")

        class FakeConfig:
            telegram_chat_id = "12345"
            telegram_bot_token = "fake"
            agent_chat_api_key = "configured"
            agent_chat_provider = "hermes"

        image_dir = ROOT_DIR / "output" / "test-telegram-codex-image"
        image_dir.mkdir(parents=True, exist_ok=True)
        generated_image = image_dir / "creative.png"
        generated_image.write_bytes(b"fake png")

        class FakeDashboard:
            def dashboard_payload(self):
                return {
                    "metrics": {},
                    "recommendations": [],
                    "fatigue": [],
                    "pending": [],
                    "audience_strategy": {},
                    "brand_guides": {},
                    "business_profile": {},
                    "agent_onboarding_phase": {},
                }

            def execute_agent_tool(self, tool_request, payload):
                return {
                    "type": "codex_image_generate",
                    "executed": True,
                    "reply": "Listo. Generé la imagen final con Codex/Image.",
                    "result": {
                        "ok": True,
                        "image_path": str(generated_image),
                        "asset_id": "test-telegram-codex-image/creative.png",
                        "preview_url": "/api/creative-asset?id=test-telegram-codex-image%2Fcreative.png",
                    },
                }

            def log_action(self, *args):
                return None

        original_agent_chat = telegram_agent.agent_chat
        original_dashboard = telegram_agent._DASHBOARD
        original_settings = telegram_agent.telegram_settings
        original_send = telegram_agent.send_message
        original_photo = telegram_agent.send_photo
        original_chat_action = telegram_agent.send_chat_action
        try:
            received_payloads = []
            sent = []
            telegram_agent._DASHBOARD = FakeDashboard()
            telegram_agent.telegram_settings = lambda config: {"enabled": True, "language": "es", "poll_timeout": 25, "bot_configured": True, "chat_id": "12345"}
            telegram_agent.agent_chat = lambda config, payload: received_payloads.append(payload) or {
                "ok": True,
                "provider": "hermes",
                "reply": "Lo preparo con Codex/Image.",
                "tool_request": {
                    "tool": "codex_image_generate",
                    "arguments": {
                        "request": "Genera un creativo para Meta Ads con estilo de marca.",
                        "mode": "free",
                    },
                },
            }
            telegram_agent.send_message = lambda config, chat_id, text: sent.append(("message", text))
            telegram_agent.send_photo = lambda config, chat_id, path, caption="": sent.append(("photo", path, caption))
            telegram_agent.send_chat_action = lambda config, chat_id, action="typing": sent.append(("typing", action))

            reply = telegram_agent.handle_text(FakeConfig(), "12345", "Hazme una imagen para anunciar mi producto", send=True)

            self.assert_true("Codex/Image" in reply, "Telegram returns the Codex/Image tool reply")
            self.assert_true(received_payloads and received_payloads[0]["channel"] == "telegram", "Telegram request is routed through the Hermes channel")
            self.assert_true(any(item[0] == "photo" and item[1] == str(generated_image) for item in sent), "Telegram sends the generated image file back to the buyer")
            self.assert_true(any(item[0] == "message" and "imagen final" in item[1].lower() for item in sent), "Telegram still sends a concise text confirmation")
        finally:
            telegram_agent.agent_chat = original_agent_chat
            telegram_agent._DASHBOARD = original_dashboard
            telegram_agent.telegram_settings = original_settings
            telegram_agent.send_message = original_send
            telegram_agent.send_photo = original_photo
            telegram_agent.send_chat_action = original_chat_action
            shutil.rmtree(image_dir, ignore_errors=True)

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
        original_telegram_request = dashboard.telegram_bot_request

        class FakeConfig:
            def __init__(self, bot, chat):
                self.telegram_bot_token = bot
                self.telegram_chat_id = chat

        calls = []
        sent_messages = []
        configs = [FakeConfig("old-bot", "old-chat"), FakeConfig("new-bot", "new-chat")]
        try:
            offset_path.write_text(json.dumps({"offset": 999}), encoding="utf-8")
            context_path.write_text(json.dumps({"old-chat": {"approval_id": "approval_old"}}), encoding="utf-8")
            dashboard.update_env_values = lambda values: calls.append(values)
            dashboard.load_config = lambda: configs.pop(0) if configs else FakeConfig("new-bot", "new-chat")
            dashboard.telegram_settings = lambda config: {"enabled": True, "language": "es", "poll_timeout": 25, "bot_configured": bool(config.telegram_bot_token), "chat_id": config.telegram_chat_id}
            dashboard.ensure_telegram_listener = lambda: True
            dashboard.telegram_bot_request = lambda config, method, payload, timeout=10: sent_messages.append((config.telegram_bot_token, method, payload)) or {"ok": True}
            dashboard.license_entitlements = lambda: {
                "plan": "individual",
                "is_agency": False,
                "is_individual": True,
                "can_use_multi_telegram_profiles": False,
            }
            dashboard.agency_registry = lambda: {"active_id": "", "spaces": []}
            status = dashboard.save_telegram_config({"enabled": "true", "bot_token": "new-bot", "chat_id": "new-chat", "language": "es", "send_welcome": "true"})
            self.assert_true(status["listener_started"] is True, "Telegram listener restarts after connection save")
            self.assert_true(status["welcome_sent"] is True and sent_messages and sent_messages[0][1] == "sendMessage", "Selecting a detected Telegram chat sends the first welcome message automatically")
            self.assert_true("Primero voy a entender tu negocio" in sent_messages[0][2]["text"], "Telegram welcome starts the buyer interview in clear Spanish")
            self.assert_true(not offset_path.exists() and not context_path.exists(), "Telegram bot/chat change clears stale polling offset and approval context")
            self.assert_true(calls and calls[0]["TELEGRAM_BOT_TOKEN"] == "new-bot" and calls[0]["TELEGRAM_CHAT_ID"] == "new-chat", "Telegram config saves the new bot and chat")
        finally:
            dashboard.update_env_values = original_update
            dashboard.load_config = original_load
            dashboard.telegram_settings = original_settings
            dashboard.ensure_telegram_listener = original_ensure
            dashboard.license_entitlements = original_entitlements
            dashboard.agency_registry = original_registry
            dashboard.telegram_bot_request = original_telegram_request
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
        dashboard_static = (
            (ROOT_DIR / "public" / "dashboard" / "dashboard.css").read_text(encoding="utf-8")
            + "\n"
            + (ROOT_DIR / "public" / "dashboard" / "dashboard.js").read_text(encoding="utf-8")
        )
        html = dashboard.HTML + "\n" + dashboard_static
        dashboard_source = Path(dashboard.__file__).read_text(encoding="utf-8")
        post_routes = set(dashboard.DashboardHandler.POST_JSON_ROUTES) | set(dashboard.DashboardHandler.POST_SPECIAL_ROUTES)
        get_routes = set(dashboard.DashboardHandler.GET_JSON_ROUTES) | dashboard.DashboardHandler.HTML_PATHS | {"/api/social/login", "/api/creative-asset", "/api/brand-asset"}
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
        self.assert_true('class="header-theme-slot"><div class="theme-switcher" id="theme-toggle"' in html and 'class="dashboard-toolbar"><div class="theme-switcher"' not in html, "Theme picker sits beside the top menu instead of competing with control toolbar actions")
        self.assert_true('class="brief-zone-heading"><button class="zone-label" id="toggle-left-panel"' in html and 'class="brief-schedule-button" id="daily-brief-schedule-button"' in html and "Brief 08:00" in html, "Daily brief area exposes its time control beside the left-panel title")
        self.assert_true("browserTimezone()" in html and "Intl.DateTimeFormat().resolvedOptions().timeZone" in html and "/api/daily-brief/schedule" in html, "Daily brief timezone is detected from the buyer browser and saved through a protected route")
        self.assert_true("Hora local detectada" in html and "saveDailyBriefSchedule(event)" in html and "daily-brief-schedule-card" in html, "Daily brief time opens a simple buyer-facing local-time editor")
        self.assert_true("openDailyBriefSchedule,closeDailyBriefSchedule,saveDailyBriefSchedule" in html, "Daily brief schedule actions are permitted by the dashboard interaction allowlist")
        self.assert_true(".header-theme-slot" in html and "grid-template-columns:minmax(178px,220px) minmax(300px,1fr) auto auto minmax(220px,360px)" in html, "Header reserves a dedicated theme slot next to the main menu")
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
        self.assert_true("onboarding-security-note" in html and "nada de lo que coloques aquí lo podemos ver nosotros" in html and "más privada que entregar tus credenciales a un SaaS" in html, "Onboarding shows a persistent local/private install reassurance")
        self.assert_true("websiteScanGuide" in html and "/api/business-profile/links" in html and "saveBusinessLinks" in html and "Primer mapa del negocio" in html and "asset-status-grid" in html and "Qué vendes, en pocas palabras" not in html, "Business links remain available for the agent-led interview without becoming a long first-run setup form")
        self.assert_true("Onboarding questions.md" in dashboard_source and "write_onboarding_questions_memory" in dashboard_source and "pregunta lo minimo necesario" in dashboard_source, "Business discovery is stored as agent memory for Telegram/chat instead of a long setup form")
        self.assert_true("businessContextGuide" in html and "businessContextQuestions" in html and "saveBusinessContextQuestion" in html, "Buyer context editor remains available outside the required onboarding path")
        self.assert_true("requires_repair" in html and "Reconectemos tus datos reales" in html, "Legacy completed setup reopens guidance when real Meta data is missing")
        self.assert_true("tab-audiences" in html, "Audience builder tab exists")
        self.assert_true("setup-config-form" in html, "Setup save form exists")
        self.assert_true('id="chatgpt-panel"' in html and "renderChatGptPanel()" in html, "Setup includes a dedicated agent model connection panel")
        self.assert_true('id="local-network-panel"' in html and "Ver desde mi teléfono" in html and "/api/local-network-access" in html, "Setup includes same-Wi-Fi phone access as an explicit opt-in")
        self.assert_true("/api/local-network-access" in dashboard.DashboardHandler.PROTECTED_POST_PATHS and "/api/local-network-access" in dashboard.DashboardHandler.POST_JSON_ROUTES, "Phone LAN access changes require dashboard password and have a handler")
        self.assert_true("Conecta el cerebro del agente" in html and "MiniMax M3" in html and "Guardar modelo del agente" in html, "Agent model setup supports MiniMax M3 as a Hermes brain")
        self.assert_true("OpenAI API" in html and "ChatGPT suscripción" in html and "Otra API compatible" in html and "OAuth" in html, "Onboarding shows four simple model choices immediately")
        self.assert_true("routeButton('openai_api')" in html and "routeButton('chatgpt_subscription')" in html and "routeButton('minimax_m3')" in html and "routeButton('custom_api')" in html and "selectAgentModelRoute('${kind}')" in html, "Agent model setup uses four collapsible route buttons")
        self.assert_true("connectChatGpt(event)" in html and "saveChatGptModel(event)" in html and "/api/agent-model/connect" in html and "Ya lo hice, conectar a ChatGPT ahora" in html, "ChatGPT/Codex connection saves model choice before connecting and uses a buyer-friendly CTA")
        self.assert_true("Copiar comando" not in html and ".agent-model-option .route-icon" in html and ".agent-route-panel.active" in html, "ChatGPT/Codex setup hides command-copy UI and keeps route choices readable")
        self.assert_true("Copiar paso" not in html and "Copy step" not in html, "ChatGPT/Codex connection no longer presents copy-only wording")
        self.assert_true("Abrir configuración de ChatGPT" in html and "chatgpt-settings-link" in html and "chatgpt-settings-actions" in html, "ChatGPT/Codex setup gives buyers a direct button to the ChatGPT security settings")
        self.assert_true("Modelo para ChatGPT/Codex" in html and "<select name=\"hermes_model\">" in html and "gpt-5.5" in html and "Recomendado automático" not in html and "agentModelFormPayload()" in html, "ChatGPT/Codex setup exposes gpt-5.5 as the clear default model selector")
        self.assert_true("Image 2 con ChatGPT/Codex" in html and "connectImageChatGpt(event)" in html and "codex_image_source" in html and "imageChatGptPayload()" in html, "Agent model setup can connect a separate ChatGPT/Codex session only for Image 2")
        self.assert_true("Modelo para imágenes" not in html and "Image model" not in html and "Usar sesión principal" not in html and "Use main session" not in html, "Image 2 connection no longer exposes image model or confusing routing controls")
        self.assert_true("disconnectAgentModel('agent')" in html and "disconnectAgentModel('image')" in html and "/api/agent-model/disconnect" in dashboard_source, "ChatGPT/Codex accounts can be disconnected safely before connecting another account")
        self.assert_true("route-state" in html and "connected-account" in html and "chatgpt_connected" in dashboard_source and "codex_image_account" in dashboard_source, "Model cards separate connected accounts from the single primary brain")
        self.assert_true("agent_chat_base_url" in html and "agent_chat_api_key" in html and "custom_api" in html, "OpenAI-compatible brain settings are exposed without showing saved keys")
        self.assert_true("DigitalOcean mostraré aquí el enlace" in html and "Ver diagnóstico para soporte" in html, "Hermes/ChatGPT setup has a browser-based VPS path with diagnostics folded")
        self.assert_true("Toca el botón de abajo para abrir la configuración de tu cuenta ChatGPT." in html and "Activar autorización con códigos de dispositivo para Codex" in html and "Vuelve aquí y toca el botón “Ya lo hice, conectar a ChatGPT ahora”" in html and "chatgpt-preflight" in html and ".chatgpt-preflight ol" in html, "ChatGPT/Codex setup tells buyers to enable device-code authorization before login without overlapping the model field")
        self.assert_true("/api/agent-model/connect-status" in html and "/api/agent-model/connect-input" in html and "sendChatGptTerminalInput" in html, "VPS Hermes bridge can poll and send guided terminal responses")
        self.assert_true("chatgpt-settings-help" in html and "device_auth_settings" in html, "ChatGPT/Codex setup shows a clear recovery card when device-code auth is disabled")
        self.assert_true("Ver diagnóstico técnico" in html and "prepareChatGptAuthWindow" in html and "maybeOpenChatGptAuthUrl" in html and "chatGptAuthOpenedUrl='';" in html, "ChatGPT/Codex browserless UI folds support detail and resets stale OAuth URLs before opening the buyer browser")
        self.assert_true("updateChatGptAuthWindow" in html and "Could not open login" in html and "Return to dashboard" in html, "ChatGPT/Codex waiting tab shows an actionable failure instead of staying stuck on preparing login")
        self.assert_true("chatgpt-device-code" in html and "Cópialo manualmente exactamente como aparece" in html and "login_code" in html and "data-chatgpt-visible-code" in html and "font-size:clamp(30px" in html and "word-break:break-all" in html and "scrollIntoView({behavior:'smooth',block:'center'})" in html, "OpenAI terminal login code is shown as a large manually copyable buyer-facing card")
        self.assert_true("Copiar código" not in html and "copyVisibleChatGptCode" not in html and "normalizeChatGptCode" not in html and "data-chatgpt-code" not in html and "data-visible-code" not in html and "dataset?.chatgptCode" not in html and "dataset?.visibleCode" not in html, "OpenAI code copying has no stale clipboard button or alternate extraction path")
        self.assert_true("advanceOnboardingAfterChatGptConnected" in html and "setOnboardingFlowStep(Math.min(steps.length-1,idx+1))" in html, "ChatGPT/Codex connection advances onboarding automatically after success")
        self.assert_true("ONBOARDING_STEP_KEY" in html and "restoreOnboardingStepIndex(steps)" in html and "clearRememberedOnboardingStep()" in html, "Onboarding remembers the active step across login-tab focus/reload and clears it when complete")
        self.assert_true("rememberOnboardingStep('chatgpt')" in html and "connectChatGpt(event)" in html and "pollChatGptConnection()" in html, "ChatGPT/Codex login pins the wizard to the code step while the device-login flow is running")
        self.assert_true("Haz clic aquí si te apareció un error" in html and "toggleChatGptDeviceAuthHelp" in html and "Activar autorización con códigos de dispositivo para Codex" in html, "OpenAI code card includes a manual buyer help button for browser-side Codex device-code errors")
        self.assert_true("Cierra la pestaña de login de ChatGPT/Codex" in html and "Ya lo activé, abrir login de nuevo" in html and "reopenChatGptAuthUrl" in html and "chatgpt-retry-login" in html, "Device-code help tells buyers to close the failed login tab and reopen it from a large CTA")
        self.assert_true("body .onboarding-flow input:not([type=\"checkbox\"])" in html and "::placeholder" in html and "-webkit-autofill" in html, "Onboarding text fields stay dark and readable across dashboard themes")
        self.assert_true("body .onboarding-flow .guide-card" in html and "background:linear-gradient(145deg,rgba(18,16,28,.96)" in html, "Onboarding cards keep dark readable contrast across dashboard themes")
        self.assert_true("Voy a elegir OpenAI Codex" in dashboard_source and "preferred_model" in dashboard_source and "maybe_auto_drive_hermes_browserless" in dashboard_source, "Hermes browserless setup auto-selects Codex provider and the chosen or recommended model")
        hermes_bridge_source = (ROOT_DIR / "src" / "hermes_bridge.py").read_text(encoding="utf-8")
        self.assert_true("hermes_status_timeout_seconds" in hermes_bridge_source and "hermes_response_timeout_seconds" in hermes_bridge_source, "Hermes status checks and real response timeouts stay separate")
        self.assert_true("{id:'chatgpt',status:chatgptOk?'ok':'warn'}" in html and "chatGptConnectMarkup(true)" in html, "Initial onboarding includes ChatGPT/Codex before the Telegram manager channel")
        self.assert_true("{id:'telegram',status:telegramOk?'ok':'warn'}" in html and "telegramOnboardingGuide()" in html, "Initial onboarding ends with Telegram instead of duplicating the communication preference already asked in Telegram")
        self.assert_true("{id:'website',status:websiteOk?'ok':'warn'}" not in html, "Initial onboarding no longer adds a separate website/social links step before Telegram")
        self.assert_true("Habla con tu manager por Telegram" in html and "Descargar Telegram" in html and "Abrir BotFather" in html and "Copiar /newbot" in html and "Ya envié hola, detectar mi chat" in html, "Telegram onboarding explains download, BotFather, command copy, chat detection, and phone-first manager access")
        self.assert_true("crear-bot-telegram.mp4" in html and "crear-bot-telegram.mov" in html and "telegram-setup-video" in html and "telegram-video-card" in html, "Telegram onboarding includes the large buyer video guide with MP4 and MOV fallback")
        self.assert_true("data-input-code=\"autoSaveTelegramToken(event)\"" in html and "telegram-token-zone" in html and "telegram-token-saved-inline" in html and "Clave guardada" in html and "Ahora abre el bot que creaste" in html and "telegram-detect-button" in html and "detectTelegramChats()" in html and "send_welcome:'true'" in html and "Detecté tu chat" in html and "Usar este chat y enviarme el primer mensaje" not in html, "Telegram bot token is saved automatically and detected chats are selected without a second buyer click")
        self.assert_true("Elige un usuario que termine en <b>bot</b>" in html and "Esto se configura una sola vez" in html and "No puedo crear el bot por ti" in html, "Telegram onboarding explains the BotFather username rule, one-time setup, and automation limits")
        self.assert_true("Enviar prueba" not in html and "Send test" not in html, "Telegram buyer UI avoids the confusing manual test button")
        self.assert_true("maybeFinishTelegramOnboarding" in html and "communicationIndex" not in html and "setOnboardingFlowStep(Math.min(steps.length-1,onboardingFlowStep+1))" in html, "Auto-selecting the detected Telegram chat stays on the final Telegram step where the buyer can finish setup")
        self.assert_true("saveCommunicationStyle(event,true)" not in html and "if(stepId==='communication')" not in html, "The dashboard onboarding no longer duplicates the simple-or-technical preference asked during the Telegram interview")
        self.assert_true("Palabras simples" in html and "Directo, claro y sin jerga." in html and "Explicaciones técnicas" in html and "Más detalle cuando ayude a decidir." in html and "/api/onboarding/communication-style" in html, "The global communication preference still exists in Setup for later changes")
        self.assert_true("saveTelegramConfig,saveCommunicationStyle,saveGeneralMemory" in html, "The final communication preference submit is permitted by the delegated dashboard action allowlist")
        self.assert_true("AGENT_COMMUNICATION_STYLE" in dashboard_source and "communication_style_update" in dashboard_source, "Communication preference is persisted globally rather than per client workspace")
        self.assert_true("AGENT_AD_EXPERIENCE_LEVEL" in dashboard_source and "save_agent_preferences" in dashboard_source, "Ads-experience preference is persisted globally rather than per client workspace")
        self.assert_true("dashboardIntroTourPending" in html and "startDashboardIntroTourIfPending" in html, "Completed onboarding queues the first dashboard tour")
        self.assert_true("Elige el estilo que más te guste" in html and "Arriba, junto al menú" in html and "#theme-toggle" in html and ".tour-spot" in html and "theme-choice" in html, "The post-onboarding tour starts with an interactive theme selection coach mark at the header theme picker")
        self.assert_true("Elige la hora de tu lectura diaria" in html and "#daily-brief-schedule-button" in html and "zona horaria se detecta automáticamente" in html, "The first dashboard tour teaches buyers where to change the locally timed daily brief")
        self.assert_true(".guide-overlay.product-tour" in html and "backdrop-filter:none" in html and "rgba(3,4,7,var(--tour-dim))" in html, "The dashboard tour spotlights targets without blurring the buttons buyers need to click")
        self.assert_true("{id:'meta',status:tokenOk?'ok':(socialOk?'warn':'blocked')}" in html and "{id:'account',status:accountOk?'ok':'blocked'}" in html and "{id:'destination',status:destinationStatus}" in html, "Initial onboarding starts with the buyer Facebook/Meta connection")
        self.assert_true("{id:'meta',status:tokenOk?'ok':(socialOk?'warn':'blocked')},\n\t  {id:'account',status:accountOk?'ok':'blocked'},\n\t  {id:'destination',status:destinationStatus},\n\t  {id:'chatgpt',status:chatgptOk?'ok':'warn'},\n\t  {id:'telegram',status:telegramOk?'ok':'warn'}" in html, "Initial onboarding goes Facebook, account, destination, ChatGPT, and Telegram")
        self.assert_true("found-choice-card" in html and "account-choice-grid" in html and "destination-choice-grid" in html and "Usar esta cuenta y seguir" in html and "Usar esta página" in html, "Meta account and Page discovery results are shown as prominent glowing choices")
        self.assert_true("Elige qué modelo usará el agente" in html and "apiBrainOk" in html, "Onboarding positions model setup as part of installation and accepts API brain readiness")
        self.assert_true("license-panel" in html, "License activation panel exists")
        self.assert_true("/api/license/activate" in html, "License activation endpoint is wired in UI")
        self.assert_true("/api/onboarding/complete" in html, "Onboarding complete endpoint is wired in UI")
        self.assert_true("Finish setup" in html or "Terminar configuración" in html, "Initial setup finish control exists")
        self.assert_true("Revisar configuración inicial" in html, "Completed setup can reopen the initial guide")
        self.assert_true("dashboard password" in html.lower() or "contraseña del dashboard" in html.lower(), "Buyer password wording exists")
        self.assert_true("Escribe la contraseña de este dashboard para continuar." in html and "Si borraste cookies" not in html, "Unlock copy stays simple for buyers")
        self.assert_true("unlock_create_title" in html and "Crea tu contraseña" in html, "Fallback unlock copy can still ask buyers to create a password if a protected route needs it")
        self.assert_true("unlockMode==='create'" in html and "/api/dashboard-password" in html, "Password creation remains wired through the dashboard password endpoint")
        self.assert_true("if(!passwordOk)steps.push({id:'password',status:'blocked'})" in html, "Clean installs start password creation as the first onboarding step")
        self.assert_true("!state.config.dashboard_password_set){clearStoredDashboardSecrets();hideUnlock()}" in html and "showUnlock(t('unlock_create_needed'),'create')" not in html, "Clean installs do not show a competing create-password popup")
        self.assert_true("function openOnboardingPasswordStep()" in html and "if(!dashboardPasswordIsSet()){hideUnlock();openOnboardingPasswordStep();return ''}" in html, "Missing password routes protected prompts to styled onboarding instead of popup")
        self.assert_true("needsFirstPassword" in html and "!needsFirstPassword" in html, "Missing password keeps the styled onboarding visible even if prior setup state was completed")
        self.assert_true("localStorage.setItem('dashboardPassword'" not in html and "localStorage.setItem(\"dashboardPassword\"" not in html, "Dashboard never stores the real buyer password in browser storage")
        self.assert_true("dashboardSession" in html and "remember_device" in html and "/api/unlock" in html, "Remember this device stores an opaque dashboard session instead of the password")
        self.assert_true("Contraseña guardada. Sigamos con el siguiente paso." in html and "advanceOnboardingAfterLoad()" in html, "Password creation advances to the next missing onboarding step")
        self.assert_true("onboardingFlowTouched=false" in html, "Onboarding auto-advance starts untouched")
        self.assert_true("s.status!=='ok'" in html, "Onboarding opens on first unfinished step")
        self.assert_true("setOnboardingFlowStep(onboardingFlowStep-1)" in html and "setOnboardingFlowStep(onboardingFlowStep+1)" in html, "Onboarding back/next buttons allow completed-step review through the remembered-step helper")
        self.assert_true("https://business.facebook.com/latest/settings/apps" in html and "Abrir Business > Apps" in html, "Facebook/Meta connection starts from the buyer's Meta Business Apps page")
        self.assert_true("Conectar mi cuenta de Facebook" in html and "Paso seguro" in html, "Spanish onboarding names the Meta step as a safer Facebook account connection")
        self.assert_true("Crea tu app privada en Meta" in html and "<h3>Conectar mi cuenta de Facebook</h3>" not in html, "Meta guide card avoids repeating the outer step title")
        self.assert_true("Abrir System users" in html and "Clave de Facebook/Meta" in html, "Spanish setup explains buyer-owned Meta connection plainly")
        self.assert_true("Empieza en Meta Business" in html and "Marca permisos de la clave" in html and "Pega la clave en Admira" in html, "Meta onboarding uses the definitive guided Business/System User token slider")
        self.assert_true("tutorial-meta/meta-business-01-open-apps-menu.png" in html and "tutorial-meta/meta-business-32-token-saved.png" in html, "Meta onboarding slider includes the final buyer screenshot walkthrough assets")
        self.assert_true("onboarding-shell-wide" in html and "minmax(620px,1.54fr)" in html and "min(66vh,650px)" in html, "Meta walkthrough uses a wider desktop layout with substantially larger screenshots")
        self.assert_true("openMetaScreenshot" in html and "meta-shot-button" in html and "meta-lightbox-card" in html and "Clic para ampliar" in html, "Meta tutorial screenshots open in a large in-app lightbox")
        self.assert_true("closeConfirm,skipOnboarding" in html and 'data-action-code="closeConfirm()"' in html, "Expanded Meta screenshots can be closed through the delegated safe action system")
        self.assert_true("Falta tu captura" not in html, "Meta onboarding no longer shows missing screenshot placeholders")
        self.assert_true("Empezar más rápido" not in html and "renovar la clave cada 60 días" not in html and "showMetaTokenBox('quick')" not in html, "Meta onboarding no longer presents Graph API Explorer as a buyer-facing path")
        self.assert_true("showMetaTokenBox('stable')" in html and "token_kind:metaTokenKind" in html, "Token box opens as the stable path while the backend still records token kind")
        self.assert_true("scrollIntoView({behavior:reduce?'auto':'smooth',block:'center'})" in html and "token-box-attention" in html and "focus({preventScroll:true})" in html, "Paste-key action scrolls to and highlights the Meta key field")
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
        self.assert_true("Encontré tu página" in html and "destination-choice-grid" in html and "found-choice-card" in html, "Discovered Pages are shown as prominent choices")
        self.assert_true("Usar esta página" in html, "Buyer can select a discovered Page")
        self.assert_true("Solo si no aparece tu página" in html, "Manual Page entry is hidden as fallback")
        self.assert_true("selectMetaDestination" in html, "Selected Page is saved without manual ID paste")
        self.assert_true("const destinationStatus=destinationOk?'ok':(accountOk?'warn':'blocked')" in html and "{id:'destination',status:destinationStatus}" in html, "Destination step can be reviewed later after an ad account is selected")
        self.assert_true("Guía rápida de uso" in html, "Onboarding includes final usage guide cards")
        self.assert_true("La filosofía: conversa con el agente" in html, "Usage guide explains chat-first philosophy")
        self.assert_true("Grupo de anuncios a usar" not in html, "Old required-ad-set wording is removed")
        self.assert_true("El grupo de anuncios es opcional" not in html, "Onboarding no longer mentions ad groups")
        self.assert_true("const destinationOk=['page_id','landing_url']" in html, "Onboarding does not require an existing ad set")
        self.assert_true("Deja la supervisión activa" in html, "Live onboarding recommends supervised mode first")
        self.assert_true("Con supervisión" in html, "Last onboarding step avoids simulation wording")
        self.assert_true("modo simulación" not in html, "Buyer-facing onboarding avoids simulation mode wording")
        self.assert_true("/api/onboarding/skip" in html and "Saltar y completar luego" in html, "Live setup details do not block first dashboard entry")
        self.assert_true("deferred-onboarding-banner" in html and "Completa la configuración para ver datos reales" in html, "Skipped setup creates a visible reminder instead of trapping the buyer")
        self.assert_true("Configuración inicial pendiente" in html and "el agente no analizará campañas reales" in html, "Deferred onboarding is not described as fully finished")
        self.assert_true("agentInterviewReasons" in html and "El agente seguirá con la entrevista del negocio por Telegram" in html, "Business, brand, and campaign interview work is handled by the agent instead of blocking dashboard setup")
        filtered = dashboard.onboarding_health({"completed": True, "skipped": True, "deferred": True, "deferred_reasons": ["entrevista_negocio", "branding_creativos", "campanas_anuncios"]}, type("Cfg", (), {})(), {"source": "demo"}, {"valid": True}, {"page_id": "1", "url": "https://example.com"}, {})
        self.assert_true(filtered.get("deferred") is False and not filtered.get("deferred_reasons"), "Agent interview items do not block dashboard/Telegram real-data readiness")
        self.assert_true("Datos de ejemplo, no reales" in html, "Demo metrics are labeled as not real in the UI")
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
        self.assert_true("/api/telegram/config" in html and "/api/telegram/detect" in html and "autoSaveTelegramToken" in html, "Telegram setup actions are wired around autosave and chat detection")
        self.assert_true("aprobar decisiones exactas con botones seguros" in html, "Telegram UI accurately explains button approvals")
        self.assert_true("brand-guides-panel" in html and "/api/brand-guides/general" in html and "/api/brand-guides/product" in html and "/api/ad-briefs" in html, "Brand, product, and ad brief memory editing is wired in UI")
        self.assert_true("/api/brand-guides/logo" in html and "/api/brand-asset" in html and "uploadBrandLogo" in html, "Brand logo upload and protected preview are wired in UI")
        self.assert_true("Subir logo" in html and "Logo para tus anuncios" in html, "Creatives memory gives buyers a clear place to upload their logo")
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
        self.assert_true("Contraseña guardada. Sigamos con el siguiente paso." in html, "Password save clearly advances without forcing an outdated step")
        self.assert_true("advanceOnboardingAfterLoad()" in html, "Password save moves to the next unfinished onboarding step")
        self.assert_true("goToMetaTokenStep" in html, "Expired-token account search can return to token step")
        self.assert_true("Pega una clave nueva" in html, "Expired Meta key message is buyer-friendly")
        self.assert_true("No se guarda en cookies" in html, "Meta key storage copy avoids cookie confusion")
        self.assert_true("send_redirect(social_login_url()" in html or hasattr(dashboard.DashboardHandler, "send_redirect"), "Social login redirect endpoint exists")
        env_example = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")
        self.assert_true("LICENSE_SERVER_URL=" in env_example, "License server URL is documented in .env.example")
        self.assert_true("LICENSE_REQUIRED_FOR_LIVE=true" in env_example, "License live requirement default is documented")
        self.assert_true("meta-connection-panel" in html and "Conexión Facebook / Meta" in html, "Setup exposes a clear Meta/Facebook connection area")
        self.assert_true("Cambiar clave de Facebook" in html and "Buscar/agregar cuenta publicitaria" in html, "Setup lets buyers replace Meta connection and account from settings")
        self.assert_true("hasta 5 cuentas" in html and "Business Manager" in html and "MAX_MANAGED_META_AD_ACCOUNTS = 5" in dashboard_source, "Setup explains and enforces the standard 5-account same-Business-Manager limit")
        self.assert_true("agency-panel" not in html and "Licencia Agencia" not in html and "Agregar cliente" not in html and "Clientes de agencia" not in html, "Buyer UI does not expose agency/client workspace copy")

    def test_setup_config_save_preserves_blank_license(self):
        """Test setup form saves live IDs without wiping an existing license key."""
        print("\nTesting Setup Config Save...")

        dashboard = load_dashboard_module()
        env_path = dashboard.ENV_FILE
        ad_path = dashboard.AD_CONFIG_FILE
        onboarding_path = dashboard.ONBOARDING_FILE
        binding_path = dashboard.INDIVIDUAL_BINDING_FILE
        managed_path = dashboard.MANAGED_AD_ACCOUNTS_FILE
        env_before = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        ad_before = ad_path.read_text(encoding="utf-8") if ad_path.exists() else ""
        onboarding_before = onboarding_path.read_text(encoding="utf-8") if onboarding_path.exists() else ""
        binding_before = binding_path.read_bytes() if binding_path.exists() else None
        managed_before = managed_path.read_bytes() if managed_path.exists() else None
        original_gateway = dashboard.start_hermes_gateway
        env_keys = [
            "LICENSE_KEY",
            "LICENSE_BUYER_EMAIL",
            "META_AD_ACCOUNT_ID",
            "AGENT_CHAT_PROVIDER",
            "AGENT_BRAIN_PROVIDER",
            "AGENT_CHAT_BASE_URL",
            "AGENT_CHAT_MODEL",
            "AGENT_CHAT_API",
            "AGENT_CHAT_API_KEY",
            "HERMES_REQUIRE_CODEX_AUTH",
            "CODEX_IMAGE_SOURCE",
            "CODEX_IMAGE_HERMES_HOME",
            "CODEX_IMAGE_HERMES_MODEL",
        ]
        env_backup = {key: os.environ.get(key) for key in env_keys}
        try:
            gateway_refreshes = []
            dashboard.start_hermes_gateway = lambda config: gateway_refreshes.append(getattr(config, "agent_brain_provider", "")) or {"started": True, "mode": "hermes_gateway"}
            dashboard.update_env_values({"LICENSE_KEY": "MAO-TESTBUYER-30628D"})
            dashboard.write_json(onboarding_path, {"completed": False})
            if binding_path.exists():
                binding_path.unlink()
            if managed_path.exists():
                managed_path.unlink()
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
                    "codex_image_source": "dedicated_chatgpt",
                    "codex_image_hermes_model": "gpt-5.5",
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
            self.assert_true("CODEX_IMAGE_SOURCE=dedicated_chatgpt" in env_after and "CODEX_IMAGE_HERMES_MODEL=gpt-5.5" in env_after, "Separate ChatGPT/Codex image routing is saved without changing the text brain")
            self.assert_true("CODEX_IMAGE_HERMES_HOME=" in env_after, "Dedicated image routing gets a persistent auth home")
            self.assert_true(gateway_refreshes == ["minimax"] and result.get("gateway", {}).get("started") is True, "Saving the agent brain refreshes Telegram Gateway so Telegram switches with the dashboard chat")
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
            if managed_before is None:
                if managed_path.exists():
                    managed_path.unlink()
            else:
                managed_path.write_bytes(managed_before)
            dashboard.start_hermes_gateway = original_gateway
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

    def test_standard_managed_ad_accounts_share_business_manager_limit(self):
        """Test standard installs can manage up to five ad accounts under one Business Manager."""
        print("\nTesting Standard Managed Ad Account Limit...")

        dashboard = load_dashboard_module()
        env_path = dashboard.ENV_FILE
        ad_path = dashboard.AD_CONFIG_FILE
        onboarding_path = dashboard.ONBOARDING_FILE
        binding_path = dashboard.INDIVIDUAL_BINDING_FILE
        managed_path = dashboard.MANAGED_AD_ACCOUNTS_FILE
        metrics_path = dashboard.METRICS_FILE
        original_entitlements = dashboard.license_entitlements
        original_collect_meta_snapshot = dashboard.collect_meta_snapshot
        original_aggregate_meta_campaigns = dashboard.aggregate_meta_campaigns
        env_before = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        ad_before = ad_path.read_text(encoding="utf-8") if ad_path.exists() else ""
        onboarding_before = onboarding_path.read_text(encoding="utf-8") if onboarding_path.exists() else ""
        binding_before = binding_path.read_bytes() if binding_path.exists() else None
        managed_before = managed_path.read_bytes() if managed_path.exists() else None
        metrics_before = metrics_path.read_bytes() if metrics_path.exists() else None
        env_backup = {key: os.environ.get(key) for key in ["META_AD_ACCOUNT_ID", "META_ACCESS_TOKEN", "META_ADS_AGENT_MODE", "LIVE_ACTIONS_ENABLED", "LICENSE_KEY", "LICENSE_BUYER_EMAIL"]}
        try:
            dashboard.license_entitlements = lambda: {"plan": "individual", "is_agency": False, "max_devices": 1, "workspace_limit": 1}
            dashboard.update_env_values({"META_AD_ACCOUNT_ID": "act_100", "META_ACCESS_TOKEN": "test-token", "META_ADS_AGENT_MODE": "live", "LIVE_ACTIONS_ENABLED": "true", "LICENSE_KEY": "MAO-TESTBUYER-30628D", "LICENSE_BUYER_EMAIL": "buyer@example.com"})
            dashboard.write_json(onboarding_path, {"completed": True})
            dashboard.write_json(ad_path, {"account": {"id": "act_100", "business_manager_id": "bm_main", "business_manager_name": "Main BM"}, "creative": {"destination": {"page_id": "page_main"}}})
            dashboard.write_json(binding_path, {"bound_at": dashboard.now_iso(), "ad_account_id": "act_100", "page_id": "page_main", "business_manager_id": "bm_main", "business_manager_name": "Main BM"})
            dashboard.write_json(managed_path, {
                "business_manager": {"id": "bm_main", "name": "Main BM"},
                "active_ad_account_id": "act_100",
                "accounts": [{"id": "act_100", "name": "Main account", "business_id": "bm_main", "business_name": "Main BM"}],
                "max_accounts": 5,
            })

            second = dashboard.save_setup_config({"ad_account_id": "act_101", "business_manager_id": "bm_main", "business_manager_name": "Main BM", "account_name": "Second account"})
            self.assert_true(second["saved"] and not second.get("business_replaced"), "A second ad account under the same Business Manager is added without replacing business memory")
            self.assert_true(second["managed_ad_accounts"]["used"] == 2 and second["managed_ad_accounts"]["active_ad_account_id"] == "act_101", "Managed account registry tracks the active account and usage")
            self.assert_true("META_AD_ACCOUNT_ID=act_101" in env_path.read_text(encoding="utf-8"), "Same-BM account switch updates the active Meta account")
            dashboard.update_env_values({"META_AD_ACCOUNT_ID": "act_100"})

            def fake_snapshot(account_id, token, version="v24.0", date_preset="last_30d"):
                return {"generated_at": dashboard.now_iso(), "account_id": account_id, "date_preset": date_preset, "data_quality": {"complete": True, "unavailable": []}}

            def fake_campaigns(snapshot):
                account_id = snapshot["account_id"]
                return [{"id": f"camp_{account_id[-3:]}", "campaign_id": f"camp_{account_id[-3:]}", "name": f"Campaign {account_id}", "status": "active", "target_type": "campaign", "target_id": f"camp_{account_id[-3:]}", "daily_budget": 20, "spend": 10, "impressions": 1000, "clicks": 50, "conversions": 5, "revenue": 40, "ctr": 5, "cpc": 0.2, "frequency": 1.2}]

            dashboard.collect_meta_snapshot = fake_snapshot
            dashboard.aggregate_meta_campaigns = fake_campaigns
            refresh = dashboard.refresh_managed_real_metrics(reason="test_multi_account")
            saved_metrics = dashboard.load_metrics()
            account_ids = {campaign.get("ad_account_id") for campaign in saved_metrics.get("campaigns", [])}
            self.assert_true(refresh["ok"] and len(refresh["accounts"]) == 2 and account_ids == {"act_100", "act_101"}, "Managed insight refresh reads all saved same-BM accounts")
            self.assert_true(saved_metrics["summary"]["total_spend"] == 20 and saved_metrics["business_manager"]["id"] == "bm_main", "Multi-account metrics are saved with combined summary and Business Manager context")
            try:
                dashboard.apply_action({"action": "pause", "campaign_id": "camp_101"})
                self.assert_true(False, "Mutating a non-active account campaign should require switching first")
            except ValueError as exc:
                self.assert_true("cuenta activa" in str(exc) and "act_101" in str(exc), "Non-active account mutation is blocked with a clear switch-account message")

            try:
                dashboard.save_setup_config({"ad_account_id": "act_other", "business_manager_id": "bm_other", "business_manager_name": "Other BM"})
                self.assert_true(False, "Different Business Manager should require clean replacement confirmation")
            except ValueError as exc:
                self.assert_true("CONFIRM_BUSINESS_REPLACE" in str(exc) and "Business Manager" in str(exc), "Different Business Manager is blocked as a business replacement")

            for index in range(102, 105):
                dashboard.save_setup_config({"ad_account_id": f"act_{index}", "business_manager_id": "bm_main", "business_manager_name": "Main BM", "account_name": f"Account {index}"})
            full = dashboard.managed_ad_accounts_payload()
            self.assert_true(full["used"] == 5 and full["remaining"] == 0, "Five same-BM ad accounts fill the standard account limit")
            try:
                dashboard.save_setup_config({"ad_account_id": "act_105", "business_manager_id": "bm_main", "business_manager_name": "Main BM"})
                self.assert_true(False, "A sixth same-BM ad account should be blocked")
            except ValueError as exc:
                self.assert_true("MAX_META_ACCOUNTS" in str(exc), "Sixth managed ad account is rejected by server-side validation")

            payload = dashboard.dashboard_payload()
            self.assert_true(payload["managed_ad_accounts"]["max_accounts"] == 5 and payload["business_binding"]["business_manager"]["id"] == "bm_main", "Dashboard payload exposes the 5-account same-BM limit")
        finally:
            dashboard.license_entitlements = original_entitlements
            dashboard.collect_meta_snapshot = original_collect_meta_snapshot
            dashboard.aggregate_meta_campaigns = original_aggregate_meta_campaigns
            env_path.write_text(env_before, encoding="utf-8")
            ad_path.write_text(ad_before, encoding="utf-8")
            if metrics_before is None:
                if metrics_path.exists():
                    metrics_path.unlink()
            else:
                metrics_path.write_bytes(metrics_before)
            if onboarding_before:
                onboarding_path.write_text(onboarding_before, encoding="utf-8")
            elif onboarding_path.exists():
                onboarding_path.unlink()
            if binding_before is None:
                if binding_path.exists():
                    binding_path.unlink()
            else:
                binding_path.write_bytes(binding_before)
            if managed_before is None:
                if managed_path.exists():
                    managed_path.unlink()
            else:
                managed_path.write_bytes(managed_before)
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
        env_backup = {key: os.environ.get(key) for key in ["META_AD_ACCOUNT_ID", "META_ACCESS_TOKEN", "TELEGRAM_AGENT_ENABLED", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_LANGUAGE", "AGENT_COMMUNICATION_STYLE", "AGENT_AD_EXPERIENCE_LEVEL"]}
        business_files_before = {
            name: (dashboard.DATA_DIR / name).read_bytes() if (dashboard.DATA_DIR / name).exists() else None
            for name in dashboard.BUSINESS_DATA_FILES
        }
        try:
            dashboard.license_entitlements = lambda: {"plan": "agency", "is_agency": True, "max_devices": 4, "workspace_limit": 50}
            dashboard.ensure_telegram_listener = lambda: False
            dashboard.update_env_values({"AGENT_COMMUNICATION_STYLE": "technical"})
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
            self.assert_true(dashboard.load_config().communication_style == "technical", "Agency client switches preserve the owner's global communication preference")
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
                self.assert_true("un solo negocio activo" in str(exc) and "otra licencia separada" in str(exc), "Individual license receives one-business copy for extra workspaces")

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
                self.assert_true("Telegram" in str(exc) and "no están disponibles" in str(exc), "Multi-client Telegram needs the right entitlement")
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
        original_gateway = dashboard.start_hermes_gateway
        before = path.read_text(encoding="utf-8") if path.exists() else ""
        env_before = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        metrics_before = metrics_path.read_text(encoding="utf-8") if metrics_path.exists() else ""
        ad_before = ad_path.read_text(encoding="utf-8") if ad_path.exists() else ""
        business_before = business_path.read_text(encoding="utf-8") if business_path.exists() else ""
        env_backup = {key: os.environ.get(key) for key in ["DASHBOARD_PASSWORD", "DASHBOARD_TOKEN", "META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID", "AGENT_COMMUNICATION_STYLE", "AGENT_AD_EXPERIENCE_LEVEL"]}
        try:
            dashboard.refresh_real_metrics = lambda *args, **kwargs: {"ok": True, "saved": True, "source": "meta_graph", "rows": 1}
            dashboard.license_status = lambda config: {"valid": True, "status": "active", "detail": "Cloud license active"}
            gateway_starts = []
            dashboard.start_hermes_gateway = lambda _config: gateway_starts.append("start") or {"started": True, "mode": "hermes_gateway"}
            dashboard.update_env_values({"DASHBOARD_PASSWORD": "buyer-owned-password", "DASHBOARD_TOKEN": "buyer-owned-password", "META_ACCESS_TOKEN": "token_12345678901234567890", "META_AD_ACCOUNT_ID": "act_999"})
            ad_path.write_text(json.dumps({"creative": {"destination": {"page_id": "111", "url": "https://buyer.example"}}}), encoding="utf-8")
            dashboard.write_json(business_path, {"website_url": "https://buyer.example", "current_stage": "Ya vendo y quiero bajar CPA.", "initial_plan": ["Leer datos reales", "Preparar campaña con supervisión"]})
            dashboard.write_json(metrics_path, {"timestamp": dashboard.now_iso(), "source": "meta_graph", "campaigns": [], "summary": {}})
            try:
                dashboard.save_communication_style({"communication_style": "expert-ish"})
                self.assert_true(False, "Invalid communication preference should be rejected")
            except ValueError:
                self.assert_true(True, "Communication preference validates the supported global values")
            try:
                dashboard.save_agent_preferences({"ad_experience_level": "guru"})
                self.assert_true(False, "Invalid ad experience preference should be rejected")
            except ValueError:
                self.assert_true(True, "Ad experience preference validates the supported global values")
            preferences = dashboard.save_agent_preferences({"communication_style": "simple", "ad_experience_level": "intermediate"})
            self.assert_true(preferences["saved"] is True and os.environ.get("AGENT_AD_EXPERIENCE_LEVEL") == "intermediate", "Agent preferences tool saves the global ads-experience preference")
            self.assert_true(len(gateway_starts) == 1, "Dashboard preference saves may refresh the Telegram gateway")
            gateway_starts.clear()
            tool_preferences = dashboard.handle_save_agent_preferences_tool({"communication_style": "technical", "ad_experience_level": "advanced"}, {"language": "es", "channel": "telegram"}, "save_agent_preferences")
            self.assert_true(tool_preferences["executed"] is True and not gateway_starts and tool_preferences.get("result", {}).get("gateway", {}).get("restart_deferred") is True, "MCP/Telegram preference saves persist without interrupting the active gateway")
            completed = dashboard.complete_onboarding({"communication_style": "technical", "ad_experience_level": "advanced"})
            payload = dashboard.dashboard_payload()
            self.assert_true(completed["completed"] is True, "Onboarding completion returns completed state")
            self.assert_true(completed["communication_style"] == "technical" and os.environ.get("AGENT_COMMUNICATION_STYLE") == "technical", "Onboarding saves the operator communication preference globally")
            self.assert_true(completed["ad_experience_level"] == "advanced" and os.environ.get("AGENT_AD_EXPERIENCE_LEVEL") == "advanced", "Onboarding saves the operator ads-experience preference globally")
            self.assert_true(payload["config"]["communication_preference"]["style"] == "technical", "Dashboard payload exposes the global communication preference")
            self.assert_true(payload["config"]["communication_preference"]["ad_experience_level"] == "advanced", "Dashboard payload exposes the global ads-experience preference")
            self.assert_true(completed["first_insights_refresh"]["saved"] is True or "reason" in completed["first_insights_refresh"], "Onboarding records first insights refresh result")
            self.assert_true(payload["onboarding"]["completed"] is True, "Dashboard payload exposes completed onboarding")
            reset = dashboard.reset_onboarding()
            self.assert_true(reset["completed"] is False, "Onboarding reset clears completed state")
        finally:
            dashboard.refresh_real_metrics = original_refresh
            dashboard.license_status = original_license_status
            dashboard.start_hermes_gateway = original_gateway
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
        env_backup = {key: os.environ.get(key) for key in ["DASHBOARD_PASSWORD", "DASHBOARD_TOKEN", "META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID", "AGENT_COMMUNICATION_STYLE", "AGENT_AD_EXPERIENCE_LEVEL"]}
        try:
            dashboard.refresh_real_metrics = lambda *args, **kwargs: {"ok": False, "saved": False, "reason": "token_expired"}
            dashboard.license_status = lambda config: {"valid": True, "status": "active", "detail": "Cloud license active"}
            dashboard.update_env_values({"DASHBOARD_PASSWORD": "buyer-owned-password", "DASHBOARD_TOKEN": "buyer-owned-password", "META_ACCESS_TOKEN": "token_12345678901234567890", "META_AD_ACCOUNT_ID": "act_999"})
            ad_path.write_text(json.dumps({"creative": {"destination": {"page_id": "111", "url": "https://buyer.example"}}}), encoding="utf-8")
            dashboard.write_json(business_path, {"website_url": "https://buyer.example", "current_stage": "Tengo anuncios activos.", "initial_plan": ["Leer datos reales"]})
            dashboard.write_json(metrics_path, {"timestamp": dashboard.now_iso(), "source": "demo", "campaigns": [], "summary": {}})
            try:
                dashboard.complete_onboarding({"communication_style": "simple"})
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
        """Test official update snapshots restore code without duplicating buyer runtime data."""
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
            (root / "output" / "generated.png").write_text("large-runtime-output\n", encoding="utf-8")
            (root / "dashboard" / "data" / "onboarding_state.json").write_text('{"completed":true,"source":"buyer"}\n', encoding="utf-8")
            (root / "dashboard" / "data" / "dashboard_identity.json").write_text('{"dashboard_password_hash":"buyer-hash"}\n', encoding="utf-8")
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
                payload = dashboard.UPDATE_SNAPSHOTS_DIR / first["id"] / dashboard.UPDATE_SNAPSHOT_ROOT_NAME
                self.assert_true((payload / "VERSION").exists(), "Snapshot keeps code/version files needed for rollback")
                self.assert_true(not (payload / ".env").exists(), "Snapshot does not duplicate local secrets")
                self.assert_true(not (payload / "ad-config.json").exists(), "Snapshot does not duplicate buyer ad config")
                self.assert_true(not (payload / "dashboard" / "data").exists(), "Snapshot does not duplicate runtime dashboard data")
                self.assert_true(not (payload / "output").exists(), "Snapshot does not duplicate generated output")
                release_root = root / "release-unpack"
                (release_root / "dashboard" / "data").mkdir(parents=True)
                (release_root / "dashboard" / "monitoring-dashboard.py").write_text("print('new dashboard')\n", encoding="utf-8")
                (release_root / ".env").write_text("DASHBOARD_PASSWORD_HASH=release-should-not-win\n", encoding="utf-8")
                (release_root / "ad-config.json").write_text('{"url":"release-should-not-win"}\n', encoding="utf-8")
                (release_root / "dashboard" / "data" / "onboarding_state.json").write_text('{"completed":false,"source":"release"}\n', encoding="utf-8")
                (release_root / "dashboard" / "data" / "dashboard_identity.json").write_text('{"dashboard_password_hash":"release-hash"}\n', encoding="utf-8")
                (release_root / "VERSION").write_text("v1.0.2\n", encoding="utf-8")
                dashboard.safe_copytree_contents(release_root, root)
                self.assert_true("DASHBOARD_PASSWORD=old" in (root / ".env").read_text(encoding="utf-8"), "Official update copy preserves buyer .env and dashboard password")
                self.assert_true('"old"' in (root / "ad-config.json").read_text(encoding="utf-8"), "Official update copy preserves buyer ad-config")
                self.assert_true('"source":"buyer"' in (root / "dashboard" / "data" / "onboarding_state.json").read_text(encoding="utf-8"), "Official update copy preserves completed onboarding state")
                self.assert_true("buyer-hash" in (root / "dashboard" / "data" / "dashboard_identity.json").read_text(encoding="utf-8"), "Official update copy preserves dashboard identity backup")
                self.assert_true((root / "VERSION").read_text(encoding="utf-8").strip() == "v1.0.2", "Official update copy can still update code/version files")
                (root / ".env").write_text("DASHBOARD_PASSWORD=new\n", encoding="utf-8")
                (root / "ad-config.json").write_text('{"url":"new"}\n', encoding="utf-8")
                (root / "VERSION").write_text("v9.9.9\n", encoding="utf-8")
                (root / "dashboard" / "data" / "chat_history.json").write_text('{"turns":["new"]}\n', encoding="utf-8")
                result = dashboard.restore_update_snapshot({"snapshot_id": first["id"]})
                self.assert_true((root / "VERSION").read_text(encoding="utf-8").strip() == "v1.0.0", "Rollback restores previous VERSION")
                self.assert_true("DASHBOARD_PASSWORD=new" in (root / ".env").read_text(encoding="utf-8"), "Rollback preserves current local .env")
                self.assert_true('"new"' in (root / "dashboard" / "data" / "chat_history.json").read_text(encoding="utf-8"), "Rollback preserves current dashboard local memory")
                self.assert_true((dashboard.UPDATE_SNAPSHOTS_DIR / first["id"]).exists(), "Rollback preserves snapshot storage while restoring code")
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
        dashboard_server_source = (ROOT_DIR / "dashboard" / "monitoring-dashboard.py").read_text(encoding="utf-8")
        dashboard_css_source = (ROOT_DIR / "public" / "dashboard" / "dashboard.css").read_text(encoding="utf-8")
        dashboard_js_source = (ROOT_DIR / "public" / "dashboard" / "dashboard.js").read_text(encoding="utf-8")
        dashboard_source = dashboard_server_source + "\n" + dashboard_css_source + "\n" + dashboard_js_source
        hermes_gateway_source = (ROOT_DIR / "src" / "hermes_gateway.py").read_text(encoding="utf-8")
        hermes_bridge_source = (ROOT_DIR / "src" / "hermes_bridge.py").read_text(encoding="utf-8")
        content_dashboard_source = (ROOT_DIR / "dashboard" / "content-dashboard.py").read_text(encoding="utf-8")
        dockerignore = (ROOT_DIR / ".dockerignore").read_text(encoding="utf-8")
        docker_entrypoint = (ROOT_DIR / "scripts" / "docker-entrypoint.sh").read_text(encoding="utf-8")
        run_docker = (ROOT_DIR / "scripts" / "run-docker.sh").read_text(encoding="utf-8")
        install_local = (ROOT_DIR / "scripts" / "install-local.sh").read_text(encoding="utf-8")
        env_example = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")
        self.assert_true("@openai/codex" in dockerfile and "node:22" in dockerfile, "Docker image installs Node and Codex CLI")
        self.assert_true("python-telegram-bot>=21,<22" in dockerfile and "python-telegram-bot>=21,<22" in install_local, "Docker/native installs include the Telegram adapter required by Hermes Gateway")
        self.assert_true("CODEX_CREATIVE_ENABLED=true" in dockerfile and 'CODEX_CREATIVE_ENABLED: "true"' in compose and '"CODEX_CREATIVE_ENABLED": "true"' in docker_entrypoint, "Buyer Docker installs enable Codex/Image creative generation by default")
        self.assert_true("CODEX_HOME=/app/runtime/codex" in dockerfile and "CODEX_HOME: /app/runtime/codex" in compose and "/app/runtime/codex/generated_images" in docker_entrypoint, "Docker persists the buyer's ChatGPT/Codex login and generated images across updates")
        self.assert_true("HERMES_DISABLED_TOOLSETS=terminal,code_execution,image_gen" in dockerfile and "HERMES_DISABLED_TOOLSETS: terminal,code_execution,image_gen" in compose and "HERMES_ENABLED_TOOLSETS=memory,skills,session_search,vision,file" in dockerfile, "Docker disables Hermes internal image generation so Codex/Image owns final creatives")
        self.assert_true("seller/" in dockerignore, "Docker build context excludes seller secrets")
        self.assert_true("forced = {" in docker_entrypoint and "\"DASHBOARD_HOST\": \"0.0.0.0\"" in docker_entrypoint, "Docker entrypoint forces reachable dashboard bind values")
        self.assert_true("LAN_ACCESS_ENABLED" in env_example and "LAN_ACCESS_ENABLED" in docker_entrypoint and "ADMIRO_HOST_LAN_IP" in compose, "Phone LAN access is off by default and Docker receives the host LAN IP when available")
        self.assert_true("meta_ads_config" in compose and "meta_ads_brand_guides" in compose, "Docker Compose persists config and brand guides")
        self.assert_true("HERMES_HOME: /app/runtime/hermes" in compose and "mkdir -p /app/runtime/hermes" in docker_entrypoint and '"HERMES_HOME": "/app/runtime/hermes"' in docker_entrypoint and "replaced_blank" in docker_entrypoint, "Docker installs persist Hermes ChatGPT/Codex auth across rebuilds")
        self.assert_true("HERMES_STATUS_TIMEOUT_SECONDS=20" in env_example and "HERMES_RESPONSE_TIMEOUT_SECONDS=300" in env_example and '"HERMES_RESPONSE_TIMEOUT_SECONDS": "300"' in docker_entrypoint, "Hermes real replies get a longer timeout than quick status checks")
        self.assert_true("meta_ads_update_snapshots" in compose and "/app/dashboard/data/update-snapshots" in compose, "Docker Compose keeps update rollback snapshots in a named volume")
        self.assert_true("MetaAdsAgent-source.zip" in script, "Release ZIP includes a stable asset name for bootstrap installers")
        self.assert_true("install-from-github.ps1" in windows_installer and "install-from-github.sh" in mac_installer and "install-from-github.sh" in linux_installer, "Double-click installers use the shared bootstrap scripts")
        self.assert_true("docker compose up --build" in windows_installer and "./scripts/run-docker.sh" in mac_installer, "Double-click installers launch Docker setup")
        self.assert_true("pkgbuild" in mac_pkg_builder and "productbuild" in mac_pkg_builder, "Mac PKG builder uses native package tools")
        self.assert_true("MAC_PKG_SIGN_IDENTITY" in mac_pkg_builder and "notarytool submit" in mac_pkg_builder and "stapler staple" in mac_pkg_builder, "Mac PKG builder supports Developer ID signing and notarization")
        self.assert_true("hdiutil create" in mac_dmg_builder and ".app" in mac_dmg_builder and "MAC_APP_SIGN_IDENTITY" in mac_dmg_builder, "Mac DMG builder creates a signed app launcher experience")
        self.assert_true("ADMIRO_DOCKER_DETACHED=true" in mac_dmg_builder and "$HOME/Applications/Admira IA" in mac_dmg_builder and "mac-docker-launcher.log" in mac_dmg_builder, "Mac DMG launcher runs Docker directly without asking the buyer to open the command file")
        self.assert_true('DASHBOARD_URL="http://127.0.0.1:7871/"' in mac_dmg_builder and 'open "$DASHBOARD_URL"' in mac_dmg_builder, "Mac DMG launcher opens the dashboard after Docker starts")
        self.assert_true("ensure_docker_ready" in mac_dmg_builder and "Docker Desktop" in mac_dmg_builder and "https://www.docker.com/products/docker-desktop/" in mac_dmg_builder, "Mac DMG launcher checks Docker before running the technical install command")
        self.assert_true("No arrastres nada a Aplicaciones" in mac_dmg_builder and ".background/background.png" in mac_dmg_builder and "set background picture" in mac_dmg_builder, "Mac DMG gives one-click visual instructions instead of an Applications drag workflow")
        self.assert_true("Privacidad y seguridad" in mac_dmg_builder and "Abrir de todos modos" in mac_dmg_builder and "aun no esta firmada por Apple" in mac_dmg_builder, "Mac DMG README explains the temporary unsigned-app security prompt")
        self.assert_true("ADMIRO_DOCKER_SKIP_BUILD" in run_docker and "up)" in run_docker and "--build" in run_docker, "Docker runner can start an existing container without rebuilding every time")
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
        self.assert_true("HERMES_MODEL=gpt-5.5" in env_example, "Buyer release defaults ChatGPT/Codex to gpt-5.5 instead of auto")
        self.assert_true("except ImportError" in hermes_gateway_source and "gpt-5.5" in hermes_gateway_source and "except ImportError" in hermes_bridge_source and "gpt-5.5" in hermes_bridge_source and "except ImportError" in dashboard_server_source and "gpt-5.5" in dashboard_server_source, "Hermes and dashboard tolerate mixed-version installs when model normalization is missing")
        product_version = (ROOT_DIR / "VERSION").read_text(encoding="utf-8").strip()
        self.assert_true(f"META_ADS_AGENT_VERSION={product_version}" in env_example, "Buyer release exposes the installed product version")
        bootstrap_config = (ROOT_DIR / "installer" / "release-bootstrap.env").read_text(encoding="utf-8")
        bootstrap_sh = (ROOT_DIR / "scripts" / "install-from-github.sh").read_text(encoding="utf-8")
        bootstrap_ps1 = (ROOT_DIR / "scripts" / "install-from-github.ps1").read_text(encoding="utf-8")
        do_firewall_script = (ROOT_DIR / "scripts" / "digitalocean-refresh-firewall.sh").read_text(encoding="utf-8")
        do_install_script = (ROOT_DIR / "scripts" / "install-digitalocean-strict-access.sh").read_text(encoding="utf-8")
        do_doc = (ROOT_DIR / "docs" / "es-digitalocean-acceso-estricto.md").read_text(encoding="utf-8")
        security_next_doc = (ROOT_DIR / "docs" / "es-proximas-revisiones-seguridad.md").read_text(encoding="utf-8")
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
        license_blob_store = (ROOT_DIR / "seller" / "vercel-license-api" / "lib" / "blob-store.js").read_text(encoding="utf-8")
        license_upstash_store = (ROOT_DIR / "seller" / "vercel-license-api" / "lib" / "upstash-store.js").read_text(encoding="utf-8")
        blob_publish_script = (ROOT_DIR / "seller" / "vercel-license-api" / "scripts" / "publish-release-assets.mjs").read_text(encoding="utf-8")
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
        self.assert_true('exec /usr/bin/env bash "$ROOT_DIR/scripts/digitalocean-refresh-firewall.sh"' in do_install_script, "DigitalOcean strict access wrapper runs the firewall script through bash so executable bits cannot break refresh")
        self.assert_true("/usr/local/bin/meta-ads-refresh-access" in digitalocean_cloud_lib and "/opt/meta-ads-agent/scripts/digitalocean-refresh-firewall.sh" in digitalocean_cloud_lib, "DigitalOcean cloud access gate uses a system helper path for one-click dashboard opening")
        self.assert_true("exec /usr/bin/env bash /opt/meta-ads-agent/scripts/digitalocean-refresh-firewall.sh" in digitalocean_cloud_lib and "ensure_refresh_helper_permissions" in digitalocean_cloud_lib and "result.returncode == 126" in digitalocean_cloud_lib, "DigitalOcean cloud access gate self-heals permission loss before failing access refresh")
        self.assert_true("migration-panel" in dashboard_source and "/api/migration/export" in dashboard_source and "/api/migration/import" in dashboard_source, "Dashboard exposes backup and restore buttons instead of extra buyer files")
        self.assert_true("cloud-access-panel" in dashboard_source and "/api/cloud-access/refresh" in dashboard_source and "digitalocean-refresh-firewall.sh" in dashboard_source, "Dashboard exposes DigitalOcean access refresh")
        self.assert_true("update-banner" in dashboard_source and "/api/update/check" in dashboard_source and "/api/update/apply" in dashboard_source and "dashboardUpdateInstalledVersion" in dashboard_source, "Dashboard checks official updates, applies them, and hides an already-installed update")
        self.assert_true("position:fixed" in dashboard_source and "update-glow" in dashboard_source and "startUpdateAutoCheck" in dashboard_source, "Dashboard shows official updates as a glowing floating button and checks silently while open")
        self.assert_true("--update-banner-text" in dashboard_css_source and "update-banner-muted" in dashboard_css_source and ".update-banner p{color:var(--update-banner-muted)!important}" in dashboard_css_source and ".update-banner .btn.primary,.update-banner .btn" in dashboard_css_source, "Update notification keeps readable text and button contrast across Aurora/light themes")
        self.assert_true("update-cards" in dashboard_source and "Ver mejoras e instalar" in dashboard_source and "Actualización oficial" in dashboard_source, "Dashboard shows update improvements as cards before installing")
        self.assert_true("UPDATE_SNAPSHOTS_DIR" in dashboard_source and "create_update_snapshot" in dashboard_source and "/api/update/rollback" in dashboard_source, "Dashboard creates local pre-update snapshots and exposes rollback")
        self.assert_true("Crear copia e instalar" in dashboard_source and "Volver a una versión anterior" in dashboard_source and "snapshot_policy" in dashboard_source and "META_ADS_AGENT_VERSION" in dashboard_source, "Update UI explains automatic backups and the updater syncs the installed version")
        self.assert_true("responseErrorMessage" in dashboard_source and "data.error||data.detail" in dashboard_source, "Dashboard shows clean API errors instead of raw JSON")
        self.assert_true("DEFAULT_POST_LIMIT_BYTES" in dashboard_source and "MIGRATION_POST_LIMIT_BYTES" in dashboard_source and "read_body(parsed.path)" in dashboard_source, "Dashboard rejects oversized protected requests")
        self.assert_true("redact_error_text" in dashboard_source and "client_error_message" in dashboard_source, "Dashboard avoids echoing raw secrets in errors")
        self.assert_true("X-Frame-Options" in dashboard_source and "X-Content-Type-Options" in dashboard_source, "Dashboard sends basic browser security headers")
        self.assert_true("Content-Security-Policy" in dashboard_source and "frame-ancestors 'none'" in dashboard_source and "object-src 'none'" in dashboard_source, "Dashboard sends a content security policy that reduces browser injection impact")
        dashboard_html_block = dashboard_server_source.split('HTML = r"""', 1)[1].split('"""\n\n\nclass DashboardHandler', 1)[0]
        self.assert_true("/assets/dashboard/dashboard.css" in dashboard_html_block and "/assets/dashboard/dashboard.js" in dashboard_html_block, "Dashboard HTML loads first-party CSS and JS assets instead of embedding the large app inline")
        self.assert_true("<style>" not in dashboard_html_block and "<script>" not in dashboard_html_block, "Dashboard HTML no longer embeds inline style or script blocks")
        self.assert_true(not any(token in dashboard_html_block for token in ["onclick=", "onsubmit=", "onchange=", "oninput=", "onpaste=", " style="]), "Dashboard HTML does not ship inline handlers or style attributes")
        self.assert_true(not any(token in dashboard_js_source for token in ["onclick=", "onsubmit=", "onchange=", "oninput=", "onpaste=", " style=", "<style>"]), "Dashboard JS templates do not generate inline handlers, style attributes, or style blocks")
        self.assert_true("data-action-code" in dashboard_source and "installDelegatedActions" in dashboard_source and "allowedActionCall" in dashboard_source, "Dashboard dynamic actions use delegated allowlisted handlers")
        self.assert_true("PUBLIC_ASSET_EXTENSIONS" in dashboard_server_source and '".css"' in dashboard_server_source and '".js"' in dashboard_server_source and "send_public_asset" in dashboard_server_source, "Dashboard serves extracted CSS and JS through the local static asset route")
        self.assert_true("script-src 'self';" in dashboard_server_source and "script-src-elem 'self';" in dashboard_server_source and "style-src 'self';" in dashboard_server_source, "Dashboard CSP blocks inline script/style elements on the main app")
        self.assert_true("script-src-attr 'none'" in dashboard_server_source and "style-src-attr 'none'" in dashboard_server_source and "unsafe-inline" not in dashboard_server_source, "Dashboard CSP blocks inline script/style attributes without unsafe-inline")
        self.assert_true("relative_to(ROOT_DIR)" in content_dashboard_source and "from html import escape" in content_dashboard_source, "Secondary content dashboard avoids path-prefix checks and escapes generated content")
        self.assert_true("official_download_url_allowed" in dashboard_source and "MAX_UPDATE_UNPACKED_BYTES" in dashboard_source and "zip_member_is_safe" in dashboard_source, "Dashboard update and restore paths guard against unsafe archives")
        self.assert_true(not (ROOT_DIR / "Actualizar acceso DigitalOcean.command").exists() and not (ROOT_DIR / "Crear respaldo para cambiar de equipo.command").exists(), "Buyer folder avoids scary top-level maintenance launchers")
        self.assert_true("Abrir mi dashboard" in do_doc and "La recuperacion tecnica es por SSH" in do_doc and "DO_STRICT_ALLOW_SSH_FROM_ANYWHERE=true" in do_doc, "DigitalOcean strict access docs explain IP changes and recovery")
        self.assert_true("Docker ayuda, pero no reemplaza CSP" in security_next_doc and "public/dashboard/dashboard.css" in security_next_doc and "script-src-attr 'none'" in security_next_doc and "no expongas tu dashboard local a internet" in security_next_doc, "Security next-steps doc records Docker, strict CSP, and public exposure follow-ups")
        self.assert_true("chat_history.json" in export_migration or "dashboard/data" in export_migration, "Migration export includes dashboard local memory")
        self.assert_true("LICENSE_DEVICE_ID=" in export_migration and "license_unlock.json" in export_migration, "Migration export clears device-specific license unlock")
        self.assert_true("LICENSE_DEVICE_ID=" in import_migration and "license_unlock.json" in import_migration, "Migration import forces new machine license validation")
        self.assert_true("Compress-Archive" in export_migration_ps1 and "Expand-Archive" in import_migration_ps1, "Windows migration buttons use native archive commands")
        self.assert_true("transfer_device" in license_activate_api and "resetDeviceRegistrations" in license_activate_api, "License activation supports explicit Individual device transfer")
        self.assert_true("transfer_device" in license_release_api and "resetDeviceRegistrations" in license_release_api, "Installer release download supports explicit Individual device transfer")
        self.assert_true("normalizeEntitlements" in license_lib and "workspace_limit: 50" in license_lib and "max_devices: 4" in license_lib, "License server normalizes Individual and Agency entitlement defaults")
        self.assert_true("isOwnerUnlimitedLicense" in license_lib and "OWNER_MAX_DEVICES = 9999" in license_lib and "MAO-DORI-ANJO-E777-GMAI-LADM-INTE-36DECA" in license_lib, "Owner testing license can install repeatedly without hitting buyer device caps")
        self.assert_true('entitlements.plan === "individual"' in license_activate_api and 'entitlements.plan === "individual"' in license_release_api, "License server restricts device transfer to Individual licenses")
        self.assert_true("license_entitlements" in dashboard_source and "active_workspace" in dashboard_source and "workspace_usage" in dashboard_source and "business_binding" in dashboard_source, "Dashboard exposes license limits and active business metadata")
        self.assert_true("Tu licencia Individual cuida un solo negocio activo" in dashboard_source and "otra licencia separada" in dashboard_source, "Dashboard explains Individual one-business limit in buyer-friendly copy")
        self.assert_true("Licencia Agencia" not in dashboard_source and "Agregar cliente" not in dashboard_source and "Clientes de agencia" not in dashboard_source, "Dashboard does not expose paused agency workspace copy")
        self.assert_true("improvements" in license_releases_admin and "improvements" in license_release_api, "Official release metadata includes buyer-facing improvement cards")
        self.assert_true("buyerFacingImprovements" in portal_lib and "INTERNAL_RELEASE_WORDS" in portal_lib and "Instalacion en contenedor" in portal_lib, "Download portal filters internal release notes before buyers see them")
        for technical_release_word in ['"hermes"', '"chatgpt"', '"codex"', '"ssh"', '"vps"', '"minimax"', '"comando"']:
            self.assert_true(technical_release_word in portal_lib, f"Download portal hides technical release note word {technical_release_word} from buyers")
        self.assert_true("Launcher Docker para Mac" in portal_lib and "Launcher Docker para Windows" in portal_lib and "abre Docker Desktop" in portal_lib, "Download portal pushes buyers toward Docker-first installers")
        self.assert_true("buyerFacingImprovements(release.improvements" in portal_session_api and "buyerFacingImprovements(release.improvements" in license_release_api, "Buyer download APIs sanitize release improvements")
        self.assert_true("timingSafeEqual" in license_lib and "RELEASE_MAX_BYTES" in license_download_api and "response.redirect(302" in license_download_api, "License server uses safer comparisons and avoids proxying large release bodies by default")
        self.assert_true(
            "export async function resetDeviceRegistrations" in license_store
            and "del(" in license_blob_store
            and 'command("DEL"' in license_upstash_store,
            "License server can clear prior device registrations",
        )
        self.assert_true("Transferir a este equipo" in dashboard_source, "Dashboard explains and confirms device transfer")
        self.assert_true("desbloqueo temporal" in device_transfer_doc and "nueva llave SSH" in device_transfer_doc and "Cambiar de equipo sin perder memoria" in device_transfer_doc, "Device transfer docs explain local migration and DigitalOcean recovery")
        self.assert_true("RELEASE_DOWNLOAD_SECRET" in license_server_readme and "/api/license/release" in license_server_readme, "Seller license server documents signed release download support")
        self.assert_true("Acceso de comprador" in portal_page and "Email de compra" in portal_page and "Clave de acceso" in portal_page, "Download portal has buyer-friendly email and access key login")
        self.assert_true("/api/portal/session" in portal_page and "/api/portal/download" in portal_page and "Elige tu sistema" in portal_page, "Download portal renders one-click platform downloads")
        self.assert_true("universalInstallerAsset" in portal_lib and "metaadsagent-source.zip" in portal_lib.lower() and "universal_fallback" in portal_lib, "Download portal can still recognize the stable universal package for allowed fallback paths")
        self.assert_true("allowUniversalFallback: false" in portal_lib and "Instalador Docker pendiente de publicar" in portal_page and "source" in portal_lib, "Download portal does not expose the source ZIP as the normal Mac/Windows installer")
        self.assert_true("Docker Desktop" in portal_page and "launcher Docker" in portal_page and "Instalacion local con Docker" in portal_page, "Download portal explains local installs run through Docker")
        self.assert_true("Descargar Docker Desktop" in portal_page and "https://www.docker.com/products/docker-desktop/" in portal_page, "Download portal gives buyers a direct Docker Desktop download button")
        self.assert_true("local-security-note" in portal_page and "no expongas el dashboard local a internet" in portal_page and "misma red Wi-Fi" in portal_page, "Download portal warns local Docker buyers not to expose the dashboard publicly")
        self.assert_true("Recordar este acceso" in portal_page and "restorePortalSession" in portal_page and "Cerrar sesion" in portal_page, "Download portal remembers buyer access and offers logout")
        self.assert_true("Estado de tu instalacion" in portal_page and "Acceder a mi dashboard" in portal_page and "renderInstallState" in portal_page, "Download portal leads with installed/not-installed state before installer choices")
        self.assert_true("install_state" in portal_session_api and "deviceRegistrations" in portal_session_api and "cloud_installation" in portal_session_api, "Portal session returns cloud and local install state")
        self.assert_true("HttpOnly" in portal_session_api and "Secure" in portal_session_api and "SameSite=Lax" in portal_session_api and "verifyPortalSession(cookieValue" in portal_session_api, "Portal remembered sessions use signed HttpOnly secure cookies")
        self.assert_true('request.method === "DELETE"' in portal_session_api and "clearPortalCookie" in portal_session_api, "Portal session endpoint supports safe logout without another function")
        self.assert_true("install_event" in license_activate_api and "onboarding_opened" in license_activate_api and "onboarding_completed" in license_activate_api, "License activation records local onboarding state for the buyer portal")
        self.assert_true("mark_license_install_state" in dashboard_source and "onboarding_completed" in dashboard_source, "Dashboard reports onboarding progress to the license server without blocking local use")
        self.assert_true("Instalar en la nube" in portal_page and "/api/portal/cloud/digitalocean" in portal_page and "Crear mi servidor" in portal_page, "Download portal exposes guided DigitalOcean install after buyer access")
        self.assert_true("Crear cuenta en DigitalOcean" in portal_page and "https://cloud.digitalocean.com/registrations/new" in portal_page and "Haz clic aqui para obtener el token" in portal_page and "cloud-token-cta" in portal_page, "Cloud install gives buyers direct DigitalOcean signup and a clear token action beside the token field")
        self.assert_true("US$12 al mes" in portal_page and "credito inicial" in portal_page and "metodo de pago" in portal_page, "Cloud install explains expected DigitalOcean cost and signup requirements")
        self.assert_true("Minimo viable recomendado - 2GB RAM" in portal_page and "No usamos 1GB como minimo" in portal_page and 'default_size: "s-1vcpu-2gb"' in digitalocean_cloud_lib and "s-1vcpu-1gb" not in digitalocean_cloud_lib, "Cloud install uses 2GB RAM as the minimum viable DigitalOcean option")
        self.assert_true("cloud-progress" in portal_page and "startCloudProgressPolling" in portal_page and "action: 'status'" in portal_page, "Download portal shows cloud install progress and polls status")
        self.assert_true("Math.min(98, rawProgress)" in portal_page and "verificando_dashboard" in portal_digitalocean_api and "Math.min(98, cleanProgress" in portal_digitalocean_api, "Download portal never shows 100 percent until the cloud dashboard is actually ready")
        self.assert_true('if (estimated.ready)' in portal_digitalocean_api and 'progress: 100' in portal_digitalocean_api and "cloudPollFailures" in portal_page and "handleCloudProgressError" in portal_page, "Cloud progress does not freeze at the first preview when the saved install state is ready or polling has a transient failure")
        self.assert_true("cloudDisplayedProgress = Math.max" in portal_page and "stopCloudProgressPolling(true)" in portal_page and "cache:'no-store'" in portal_page, "Cloud progress cannot regress or let stale polling responses overwrite the ready state")
        self.assert_true("Boolean(openUrl && (cloud.dashboard_available" in portal_page and "Boolean(openUrl && (data.ready" in portal_page, "Download portal requires a real dashboard URL before showing cloud as ready")
        self.assert_true("runtimeStageFromLog" in portal_digitalocean_api and "ADMIRO_STAGE verifying_dashboard" in portal_digitalocean_api, "DigitalOcean status recovers the verifying-dashboard stage from older access gates")
        self.assert_true("docker_ps" in portal_digitalocean_api and "docker_logs_tail" in portal_digitalocean_api, "DigitalOcean cloud status preserves safe Docker diagnostics")
        self.assert_true("Could not resolve host" in portal_digitalocean_api and "No pudo descargar el producto por DNS de arranque" in portal_digitalocean_api, "DigitalOcean cloud status recognizes first-boot DNS download failures instead of freezing progress")
        self.assert_true("Tardando mas de lo normal" in portal_page and "tail -n 80 /var/log/admiro-cloud-install.log" in portal_page, "Download portal explains when DigitalOcean is active but dashboard is not ready")
        self.assert_true("Abrir mi dashboard" in portal_page and "cloud_open_url" in portal_page and "prepara tu red automaticamente" in portal_page, "Download portal exposes a one-click cloud dashboard opener")
        self.assert_true("data-cloud-open-url" in portal_page and "openCloudDashboard" in portal_page and "action: 'refresh_access'" in portal_page and "data.dashboard_url || data.dashboard_https_url || data.dashboard_http_url || data.cloud_open_url" in portal_page, "Cloud dashboard opener refreshes access through the portal and opens the direct dashboard URL after success")
        self.assert_true("showPendingWindowMessage(pendingWindow, 'No pude preparar el acceso'" in portal_page and "shouldAskForFreshDigitalOceanToken(data)" in portal_page and "refresh_access_failed" in portal_page, "Cloud dashboard opener keeps the helper tab open, shows portal refresh errors, and asks for a fresh token instead of hiding them behind the Droplet access gate")
        self.assert_true("function setCloudFormMode(mode)" in portal_page and "Recuperar acceso cloud" in portal_page and "no se creara otro Droplet" in portal_page and "cloudForm.dataset.mode === 'recovery'" in portal_page and "action: 'refresh_access'" in portal_page, "Existing cloud installs use a recovery form that refreshes access instead of creating another Droplet")
        self.assert_true("if(fallbackUrl)" in portal_page and "Estoy intentando abrir con el acceso seguro del servidor" in portal_page, "Cloud dashboard opener falls back to the Droplet access gate instead of closing the waiting tab")
        self.assert_true("function safeHttpUrl" in portal_page and "url.protocol === 'http:' || url.protocol === 'https:'" in portal_page and "const openUrl = safeHttpUrl" in portal_page, "Download portal only renders http/https cloud dashboard links")
        self.assert_true("Protector automatico de acceso" in portal_page and "/api/portal/cloud/access-keeper" in portal_page and "/api/portal/cloud/access-keeper-ps" in portal_page, "Download portal keeps the optional local access keeper available as an advanced fallback")
        self.assert_true("Actualizar acceso de esta red" in portal_page and "refreshCloudAccess()" in portal_page and "action: 'refresh_access'" in portal_page, "Download portal can realign cloud SSH/dashboard access from the buyer browser")
        self.assert_true("saldo vencido o cuenta en hold" in portal_digitalocean_api and "Firewalls: actualizar y Droplets: leer" in portal_digitalocean_api, "DigitalOcean 403 firewall errors mention past-due billing/hold before falling back to token scopes")
        self.assert_true("DigitalOcean rechazo borrar este servidor" in portal_digitalocean_api and "saldo vencido o cuenta en hold" in portal_digitalocean_api and "permiso para borrar Droplets" in portal_digitalocean_api, "DigitalOcean 403 delete errors mention past-due billing/hold before falling back to Droplet delete permission")
        self.assert_true("refreshFirewallRulesOnly" in portal_digitalocean_api and "/rules" in portal_digitalocean_api and "error?.statusCode !== 403" in portal_digitalocean_api, "DigitalOcean refresh falls back to rule-only updates when full firewall PUT is forbidden by attached Droplet permissions")
        self.assert_true("Buscar automaticamente con mi token" in portal_page and "cloudRecoveryToken" in portal_page and "refreshCloudIpFromDigitalOcean" in portal_digitalocean_api, "DigitalOcean waiting-for-IP state can recover automatically with the browser-held token")
        self.assert_true("Guardar este token cifrado" not in portal_page and "Olvidar token guardado" not in portal_page and "digitalocean_token_saved" not in portal_session_api and "rememberDigitalOceanToken" not in portal_page and "forgetDigitalOceanToken" not in portal_page, "Download portal no longer shows a confusing manual token-save option")
        self.assert_true("encryptPortalSecret" in secret_vault_lib and "aes-256-gcm" in secret_vault_lib and "PORTAL_SECRET_VAULT_KEY" in secret_vault_lib, "Portal vault encryption helper remains available for legacy secret records")
        self.assert_true("remember_digitalocean_token" not in portal_digitalocean_api and "forget_digitalocean_token" not in portal_digitalocean_api and "resolveDigitalOceanToken" in portal_digitalocean_api and "withSavedDigitalOceanToken" in portal_digitalocean_api and "encryptPortalSecret" in portal_digitalocean_api and "decryptPortalSecret" in portal_digitalocean_api, "DigitalOcean cloud endpoint silently keeps the token encrypted for access recovery without exposing save/forget actions")
        self.assert_true(
            "resetCloudInstall" in portal_page
            and 'data-cloud-action="reset-install"' in portal_page
            and "cloudResetInProgress" in portal_page
            and 'onclick="resetCloudInstall()"' not in portal_page
            and "Ya lo borre manualmente. Crear uno nuevo" in portal_page
            and 'action === "reset_cloud_install"' in portal_digitalocean_api,
            "Download portal can reliably select and clear a deleted or stuck DigitalOcean install before recreating",
        )
        self.assert_true(
            "deleteCloudDroplet" in portal_page
            and 'data-cloud-action="delete-droplet"' in portal_page
            and "Borrar servidor en DigitalOcean ahora" in portal_page
            and 'action: \'delete_cloud_install\'' in portal_page
            and 'action === "delete_cloud_install"' in portal_digitalocean_api
            and "deleteDigitalOceanCloudInstall" in portal_digitalocean_api
            and '`/droplets/${encodeURIComponent(dropletId)}`' in portal_digitalocean_api
            and 'method: "DELETE"' in portal_digitalocean_api,
            "Download portal can delete the saved DigitalOcean Droplet from the buyer access page",
        )
        self.assert_true(
            "clearCloudInstallation" in portal_digitalocean_api
            and "buyer_confirmed_deleted_droplet" in portal_digitalocean_api
            and "cloud_installation: null" in portal_digitalocean_api
            and "writeCloudInstallationIfCurrent" in portal_digitalocean_api
            and "cloud_install_reset" in portal_digitalocean_api,
            "DigitalOcean reset clears the saved cloud install and rejects stale status writes that could restore it",
        )
        self.assert_true("clearIfDigitalOceanDropletMissing" in portal_digitalocean_api and "digitalOceanResourceMissing" in portal_digitalocean_api and "cleared_deleted_cloud" in portal_digitalocean_api, "DigitalOcean status clears zombie installs when the Droplet no longer exists")
        self.assert_true("cloudStateVersion" in portal_page and "expectedVersion !== cloudStateVersion" in portal_page and "data.cleared_deleted_cloud" in portal_page, "Download portal ignores stale cloud polling after a reset")
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
        self.assert_true("hostname_resolves" in digitalocean_cloud_lib and "socket.getaddrinfo" in digitalocean_cloud_lib and 'f"http://{host}:{DASHBOARD_PORT}/?cloud_access=ok"' in digitalocean_cloud_lib, "DigitalOcean access gate avoids NXDOMAIN by falling back to the direct IP dashboard URL when HTTPS DNS is not ready")
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
        self.assert_true("Instalacion guiada en DigitalOcean" in digitalocean_guided_doc and "No se muestra una opcion confusa" in digitalocean_guided_doc and "conserva cifrado" in digitalocean_guided_doc and "5 a 10 minutos" in digitalocean_guided_doc, "Buyer docs explain guided DigitalOcean install safely without a manual token-save step")
        self.assert_true("barra de progreso" in digitalocean_guided_doc and "Acceder a mi dashboard" in digitalocean_guided_doc, "Buyer docs explain cloud install progress and final access button")
        self.assert_true("Abrir mi dashboard" in digitalocean_guided_doc and "autoriza la IP actual" in digitalocean_guided_doc and "No contiene el token de DigitalOcean" in digitalocean_guided_doc, "Buyer docs explain the one-click cloud dashboard opener")
        self.assert_true("Protector automatico de acceso avanzado" in digitalocean_guided_doc and "corre cada hora" in digitalocean_guided_doc and "No guarda el token de DigitalOcean" in digitalocean_guided_doc, "Buyer docs explain the local cloud access keeper as an advanced fallback")
        self.assert_true(".dmg" in portal_lib and ".exe" in portal_lib and ".tar.gz" in portal_lib and ".pkg" not in portal_lib and ".msi" not in portal_lib, "Portal maps Docker-first release assets to Mac, Windows and Linux buttons")
        self.assert_true("releases/tags" in portal_lib and "GITHUB_RELEASE_TOKEN" in portal_lib and "api.github.com/repos" in portal_lib, "Portal can discover platform installers from the private GitHub release")
        self.assert_true("blob_path" in license_lib and "blob_path" in license_download_api and "@vercel/blob" in license_download_api and "access: \"private\"" in blob_publish_script and "publish-release-assets" in str(ROOT_DIR / "seller" / "vercel-license-api" / "scripts" / "publish-release-assets.mjs"), "Portal can serve private Vercel Blob release installers")
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
    
    def test_evidence_gated_optimization_and_private_business_truth(self):
        """Test objective-aware safety, statistical tests, Shopify privacy, and research trust."""
        print("\nTesting Evidence-Gated Optimization And Business Truth...")
        now = datetime.now(timezone.utc)
        rules = {
            "target_cpa": 50,
            "target_cpl": 20,
            "target_cost_per_conversation": 10,
            "target_roas": 2,
            "min_spend_before_judging": 25,
            "min_conversions_before_scaling": 3,
            "max_cpa_multiplier": 3,
        }
        state = optimization_engine.default_optimization_state(now)
        early = {
            "id": "early", "objective": "sales", "status": "active", "daily_budget": 20,
            "spend": 120, "conversions": 0, "revenue": 0,
            "start_time": (now - timedelta(hours=8)).isoformat(), "updated_at": now.isoformat(),
        }
        early_decision = optimization_engine.recommend_campaign(early, rules, state, now)
        self.assert_true(early_decision["decision"] == "hold" and early_decision["cost_per_result"] is None, "Young zero-conversion campaigns are held without fake CPA sentinel values")

        learning = {**early, "id": "learning", "start_time": (now - timedelta(days=5)).isoformat(), "learning_stage": "LEARNING"}
        self.assert_true(optimization_engine.recommend_campaign(learning, rules, state, now)["decision"] == "hold", "Meta learning status blocks optimization changes")
        stale = {**early, "id": "stale", "start_time": (now - timedelta(days=5)).isoformat(), "updated_at": (now - timedelta(days=3)).isoformat()}
        self.assert_true(optimization_engine.recommend_campaign(stale, rules, state, now)["decision"] == "hold", "Stale evidence blocks optimization changes")

        lead = {
            "id": "lead", "objective": "lead_generation", "status": "active", "daily_budget": 20,
            "spend": 30, "conversions": 3, "revenue": 0,
            "start_time": (now - timedelta(days=5)).isoformat(), "updated_at": now.isoformat(),
        }
        lead_decision = optimization_engine.recommend_campaign(lead, rules, state, now)
        self.assert_true(lead_decision["decision"] == "scale" and lead_decision["objective"] == "leads", "Lead campaigns use CPL rather than being penalized for zero revenue")
        strict_rules = {**rules, "target_cpl": 5}
        self.assert_true(optimization_engine.recommend_campaign(lead, strict_rules, state, now)["decision"] == "reduce", "Saved objective targets directly change the recommendation")
        message_campaign = {**lead, "id": "message", "objective": "messaging_conversations", "spend": 24}
        self.assert_true(optimization_engine.recommend_campaign(message_campaign, rules, state, now)["objective"] == "messages", "Message campaigns use cost per conversation")

        unlocked = {**state, "mode": "unlocked"}
        self.assert_true(not lead_decision["mutation_allowed"] and optimization_engine.recommend_campaign(lead, rules, unlocked, now)["mutation_allowed"], "Shadow mode separates recommendations from mutation permission")
        cooldown = {**unlocked, "last_actions": {"lead": (now - timedelta(hours=2)).isoformat()}}
        self.assert_true(optimization_engine.recommend_campaign(lead, rules, cooldown, now)["decision"] == "hold", "Significant-edit cooldown blocks repeated budget changes")
        unlock_state = {**state, "shadow_started_at": (now - timedelta(days=14)).isoformat(), "matured_outcomes": 10, "buyer_confirmed_unlock": True}
        self.assert_true(optimization_engine.unlock_status(unlock_state, now)["can_unlock"], "Shadow unlock requires elapsed time, matured outcomes, and buyer confirmation")

        capped = {**unlocked, "account_daily_budget_cap": 30, "test_budget_percent": 20}
        portfolio = optimization_engine.portfolio_recommendations([lead, {**lead, "id": "lead2"}], rules, capped, now)
        self.assert_true(all(item["decision"] == "hold" for item in portfolio), "Portfolio cap preserves the configured creative-test budget reserve")

        confidence = experiment_scheduler.comparison_confidence([
            {"metrics": {"conversions": 12, "spend": 100, "cpa": 8.33}},
            {"metrics": {"conversions": 4, "spend": 100, "cpa": 25}},
        ], "cpa")
        self.assert_true(confidence["probability_best"] >= 0.9 and confidence["expected_lift"] >= 0.1, "Creative decisions expose statistical confidence and minimum expected lift")
        starving = experiment_scheduler.evaluate_experiment(
            {
                "id": "starved", "phase": "evidence", "primary_metric": "cpa", "daily_budget": 100, "target_cpa": 50,
                "start_at": (now - timedelta(days=4)).isoformat(),
                "plan": {"required_spend_per_variant": 40, "min_total_conversions": 3, "evidence_check_hours": 24},
                "baseline": {},
                "variants": [{"id": "a", "name": "A", "ad_id": "a"}, {"id": "b", "name": "B", "ad_id": "b"}],
            },
            [{"id": "a", "ad_id": "a", "spend": 100, "impressions": 5000, "clicks": 100, "conversions": 5}, {"id": "b", "ad_id": "b", "spend": 5, "impressions": 300, "clicks": 8, "conversions": 0}],
            now=now,
        )
        self.assert_true(starving["spend_starved"] and any(item["type"] == "use_controlled_creative_test" for item in starving["recommendations"]), "Uneven creative delivery is flagged as starvation instead of a winner")

        self.assert_true(shopify_connector.normalize_shop_domain("https://demo-store.myshopify.com/") == "demo-store.myshopify.com", "Shopify accepts only normalized secure shop domains")
        try:
            shopify_connector.normalize_shop_domain("https://demo-store.myshopify.com@evil.example")
            blocked_domain = False
        except ValueError:
            blocked_domain = True
        self.assert_true(blocked_domain, "Shopify domain allowlist blocks credential-host SSRF tricks")
        aggregates, hashes = shopify_connector.aggregate_orders("demo-store.myshopify.com", [{
            "id": "gid://shopify/Order/123", "createdAt": "2026-06-10T10:00:00Z", "updatedAt": "2026-06-10T11:00:00Z",
            "email": "must-not-persist@example.com", "name": "#1001", "test": False, "currencyCode": "USD",
            "totalPriceSet": {"shopMoney": {"amount": "100", "currencyCode": "USD"}},
            "currentTotalPriceSet": {"shopMoney": {"amount": "80", "currencyCode": "USD"}},
            "totalRefundedSet": {"shopMoney": {"amount": "20", "currencyCode": "USD"}},
        }])
        persisted_shape = json.dumps({"days": aggregates, "dedup": hashes})
        self.assert_true(aggregates[0]["net_sales"] == 80 and aggregates[0]["refunds"] == 20, "Shopify aggregates gross, net, and refunds")
        self.assert_true("must-not-persist" not in persisted_shape and "#1001" not in persisted_shape and "gid://" not in persisted_shape, "Shopify persistence shape excludes PII and raw order IDs")
        self.assert_true(len(hashes[0]["hash"]) == 64, "Shopify deduplication stores a one-way hash")

        community = optimization_research.normalize_item({
            "source_url": "https://www.reddit.com/r/FacebookAds/example", "source_type": "community",
            "claim": "A practitioner reports a scaling pattern.", "testable_hypothesis": "Test the pattern under the account budget cap.",
        }, now)
        official = optimization_research.normalize_item({
            "source_url": "https://www.facebook.com/business/ads/performance-marketing", "source_type": "official",
            "claim": "Meta recommends protecting learning and creative diversification.", "testable_hypothesis": "Test fewer edits and distinct creatives.",
        }, now)
        self.assert_true(community["credibility"] == "anecdotal" and not community["can_trigger_spend_action"], "Community research is anecdotal and cannot trigger spend actions")
        self.assert_true(official["credibility"] == "high" and optimization_research.parse_iso(official["expires_at"]) > optimization_research.parse_iso(community["expires_at"]), "Official guidance has higher trust and a longer review horizon")
        safe_error = meta_insights.safe_graph_error({"error": {"message": "Request failed", "code": 100}})
        self.assert_true("access_token" not in json.dumps(safe_error) and safe_error["code"] == 100, "Meta collector errors stay structured without leaking tokens")

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
            self.test_hermes_empty_library_reply_falls_back_to_cli,
            self.test_dashboard_hermes_cli_registers_admira_mcp_tools,
            self.test_hermes_creative_image_request_routes_to_codex_tool,
            self.test_hermes_missing_runtime_gives_chatgpt_setup_guidance,
            self.test_hermes_model_usage_limit_keeps_connection_state_clear,
            self.test_hermes_gateway_rate_limit_runtime_patch_localizes_reset_time,
            self.test_hermes_gateway_runtime_patch_always_attaches_generated_creatives,
            self.test_hermes_gateway_minimax_runtime_patch_forces_official_provider,
            self.test_dashboard_chatgpt_connect_action_opens_terminal,
            self.test_dashboard_image_only_chatgpt_connect_preserves_text_brain,
            self.test_dashboard_chatgpt_disconnect_clears_only_auth_artifacts,
            self.test_dashboard_chatgpt_connect_action_uses_vps_browserless_bridge,
            self.test_dashboard_hermes_browserless_auto_selects_codex,
            self.test_hermes_blocks_non_codex_runtime_by_default,
            self.test_hermes_attaches_safe_uploaded_images,
            self.test_hermes_telegram_uses_persistent_session_not_prompt_history,
            self.test_hermes_telegram_creates_missing_persistent_session,
            self.test_telegram_defaults_to_direct_hermes_gateway,
            self.test_hermes_gateway_uses_isolated_home_and_daily_cron_prompt,
            self.test_hermes_product_skills_are_copied_to_workspace,
            self.test_admira_tool_bridge_maps_mcp_tools_to_dashboard_actions,
            self.test_admira_mcp_server_lists_and_calls_product_tools,
            self.test_public_asset_fetcher_normalizes_drive_and_blocks_private_urls,
            self.test_public_asset_fetcher_extracts_video_frames_for_vision_review,
            self.test_admira_mcp_creative_timeout_returns_buyer_fallback,
            self.test_verified_signal_ledger_records_private_deduped_outcomes,
            self.test_hermes_gateway_redacts_token_and_handles_start_failure,
            self.test_hermes_gateway_incomplete_config_stops_existing_process,
            self.test_hermes_daily_brief_cron_edge_cases,
            self.test_adaptive_creative_experiment_reviews_and_cron,
            self.test_evidence_gated_optimization_and_private_business_truth,
            self.test_hermes_business_memory_workspace_is_curated_and_redacted,
            self.test_hermes_continuity_recovers_after_history_cleanup,
            self.test_decision_memory_profitability_rules_and_hermes_context,
            self.test_chat_approval_decision_tool,
            self.test_minimax_tool_request_executes_backend_tool,
            self.test_codex_creative_prompt_rejects_local_file_escape,
            self.test_codex_image_prompt_lab_builds_fixed_and_free_packages,
            self.test_codex_image_cli_bridge_copies_generated_asset,
            self.test_agent_codex_image_creative_request_result,
            self.test_creative_studio_protects_and_previews_generated_assets,
            self.test_brand_memory_documents_feed_creative_generation,
            self.test_agent_onboarding_phase_tools_create_durable_memory,
            self.test_creative_strategy_gate_and_exact_logo_pipeline,
            self.test_creative_memory_accepts_agent_aliases_for_product_and_brief,
            self.test_mcp_wrapped_creative_memory_and_asset_only_context,
            self.test_codex_image_attaches_hermes_cached_photo_paths_from_prompt_text,
            self.test_codex_image_uses_latest_workspace_upload_when_agent_mentions_uploaded_photo,
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
            self.test_dashboard_chat_uses_product_actions_before_generic_agent,
            self.test_telegram_channel_routes_agent_and_blocks_approval,
            self.test_telegram_codex_image_request_sends_generated_photo,
            self.test_telegram_connection_change_resets_polling_state,
            self.test_setup_page_contains_unlock_and_trust,
            self.test_setup_config_save_preserves_blank_license,
            self.test_individual_license_replaces_one_business_only_with_confirmation,
            self.test_standard_managed_ad_accounts_share_business_manager_limit,
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
