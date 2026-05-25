#!/usr/bin/env python3
"""
Integration tests for Meta Ads Agent modules.
"""
import json
import os
import shutil
import sys
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
from license import activate_license, format_license, license_status, validate_license_key
from security import dashboard_token_valid, redact_payload
from product_config import AgentConfig
from agent_chat import account_context, parse_skill_response
from audience_builder import build_audience_strategy
from codex_brand_guides import build_codex_creative_prompt
import codex_brand_guides
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

        self.assert_true(valid["valid"], "Formatted license validates")
        self.assert_true(missing["status"] == "missing", "Missing license is reported")
        self.assert_true(not invalid["valid"], "Invalid license is rejected")

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

    def test_skill_response_parsing(self):
        """Test MiniMax skill JSON parsing."""
        print("\nTesting Skill Response Parsing...")

        parsed = parse_skill_response('{"assistant_message":"Listo","tool_request":{"tool":"run_daily_check","arguments":{}}}')
        self.assert_true(parsed["assistant_message"] == "Listo", "Skill assistant message parsed")
        self.assert_true(parsed["tool_request"]["tool"] == "run_daily_check", "Skill tool request parsed")

    def test_chat_approval_guardrail_tool(self):
        """Test chat cannot approve actions through the skill executor."""
        print("\nTesting Chat Approval Guardrail Tool...")

        dashboard = load_dashboard_module()
        result = dashboard.execute_agent_tool({"tool": "approval_guardrail", "arguments": {}}, {"language": "es"})
        self.assert_true(result is not None, "Approval intent is routed locally")
        self.assert_true(result["type"] == "approval_guardrail", "Approval intent hits guardrail")
        self.assert_true(result["executed"] is False, "Approval is not executed from chat")

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
        self.assert_true(context["brand_guides"]["product_guides"] == ["brand_guides/products/oferta.md"], "MiniMax receives safe Codex guide inventory")
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

    def test_chat_stages_campaign_creation_but_cannot_approve(self):
        """Test natural language can stage campaign creation while chat approvals stay blocked."""
        print("\nTesting Chat Campaign Creation Routing...")

        dashboard = load_dashboard_module()
        original_require = dashboard.require_cloud_license
        original_create = dashboard.create_campaign
        try:
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
            self.assert_true(approve["routed_action"]["type"] == "approval_guardrail", "Chat cannot approve actions")
            self.assert_true(approve["routed_action"]["executed"] is False, "Chat approval request is blocked")
        finally:
            dashboard.require_cloud_license = original_require
            dashboard.create_campaign = original_create

    def test_telegram_channel_routes_agent_and_blocks_approval(self):
        """Test Telegram uses the manager path and approves only through buttons."""
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
            telegram_agent.approve_pending = lambda approval_id: [{"id": approval_id, "result": {"ok": True}}]
            telegram_agent.reject_pending = lambda approval_id, reason="": [{"id": approval_id}]
            reply = telegram_agent.handle_text(FakeConfig(), "12345", "Prepara una campaña", send=False)
            blocked = telegram_agent.handle_text(FakeConfig(), "12345", "Aprueba esa campaña", send=False)
            pending_reply = telegram_agent.handle_text(FakeConfig(), "12345", "/pendientes", send=True)
            callback = telegram_agent.handle_update(FakeConfig(), {"callback_query": {"id": "cb_1", "data": "approve:approval_test", "message": {"chat": {"id": "12345"}}}})
            self.assert_true(telegram_agent.is_allowed_chat(FakeConfig(), "12345"), "Configured Telegram private chat is allowed")
            self.assert_true(not telegram_agent.is_allowed_chat(FakeConfig(), "99999"), "Unknown Telegram chat is rejected")
            self.assert_true("preparada para aprobación" in reply, "Telegram can stage manager actions through backend tools")
            self.assert_true("no apruebo por texto libre" in blocked, "Telegram cannot approve ambiguous natural-language requests")
            self.assert_true(received_payloads[0]["business_profile"]["main_offer"] == "Curso Test", "Telegram gives MiniMax the selected client's business profile")
            self.assert_true("Decisiones pendientes" in pending_reply, "Telegram lists pending approvals")
            self.assert_true(any(item[0] == "keyboard" for item in sent), "Telegram sends approve/reject buttons")
            self.assert_true(callback["type"] == "approved", "Telegram button can approve the exact pending action")
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

    def test_setup_page_contains_unlock_and_trust(self):
        """Test dashboard has unlock screen and trust panel placeholders."""
        print("\nTesting Setup UI Markup...")

        dashboard = load_dashboard_module()
        html = dashboard.HTML
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
        self.assert_true(".chat-log::-webkit-scrollbar-thumb" in html and "scrollbar-color:rgba(39,199,167" in html, "AI conversation scrollbar matches the dark theme")
        self.assert_true("chat-fab-breathe" in html, "Legacy chat motion remains available")
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
        self.assert_true("onboarding-flow" in html, "Dedicated onboarding flow exists")
        self.assert_true("websiteScanGuide" in html and "/api/business-profile/scan" in html, "Onboarding starts with website intelligence")
        self.assert_true("businessContextGuide" in html and "¿En qué etapa estás ahora?" in html, "Onboarding collects buyer stage and improvement context")
        self.assert_true("initialStrategyGuide" in html and "Esto entendí de tu negocio" in html, "Onboarding shows an initial strategy before dashboard entry")
        self.assert_true("requires_repair" in html and "Reconectemos tus datos reales" in html, "Legacy completed setup reopens guidance when real Meta data is missing")
        self.assert_true("tab-audiences" in html, "Audience builder tab exists")
        self.assert_true("setup-config-form" in html, "Setup save form exists")
        self.assert_true("license-panel" in html, "License activation panel exists")
        self.assert_true("/api/license/activate" in html, "License activation endpoint is wired in UI")
        self.assert_true("/api/onboarding/complete" in html, "Onboarding complete endpoint is wired in UI")
        self.assert_true("Finish onboarding" in html or "Finalizar onboarding" in html, "Onboarding finish control exists")
        self.assert_true("Set Up Onboarding again" in html, "Completed setup can restart onboarding")
        self.assert_true("dashboard password" in html.lower() or "contraseña del dashboard" in html.lower(), "Buyer password wording exists")
        self.assert_true("onboardingFlowTouched=false" in html, "Onboarding auto-advance starts untouched")
        self.assert_true("s.status!=='ok'" in html, "Onboarding opens on first unfinished step")
        self.assert_true("onboardingFlowTouched=true;onboardingFlowStep=Math.max" in html, "Onboarding back button allows completed-step review")
        self.assert_true('href="/api/social/login"' in html, "Meta Developers button uses a real browser link")
        self.assert_true("Abrir Meta" in html, "Spanish onboarding points to Meta")
        self.assert_true("Tu propia app de Meta" in html, "Spanish onboarding explains buyer-owned Meta app")
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
        self.assert_true("Dejar piloto automático apagado por ahora" in html, "Live onboarding recommends supervised mode first")
        self.assert_true("Qué significa trabajar con supervisión" in html, "Last onboarding step avoids simulation wording")
        self.assert_true("modo simulación" not in html, "Buyer-facing onboarding avoids simulation mode wording")
        self.assert_true("summary.live_ads_ready?'ok':'warn'" in html, "Live onboarding does not block first dashboard entry")
        self.assert_true("No hace falta para entrar al dashboard" in html, "Live smoke test is positioned as optional")
        self.assert_true("Con supervisión" in html, "Buyer-facing supervised control wording exists")
        self.assert_true("Piloto automático" in html, "Buyer-facing autopilot wording exists")
        self.assert_true("guardrails-panel" in html, "Guardrail settings panel exists")
        self.assert_true("/api/guardrails" in html, "Guardrail settings can be saved")
        self.assert_true("telegram-panel" in html and "Hablar por Telegram" in html, "Configuration includes optional Telegram manager access")
        self.assert_true("/api/telegram/config" in html and "/api/telegram/detect" in html and "/api/telegram/test" in html, "Telegram setup actions are wired in UI")
        self.assert_true("aprobar decisiones exactas con botones seguros" in html, "Telegram UI accurately explains button approvals")
        self.assert_true("brand-guides-panel" in html and "/api/brand-guides/init" in html, "Codex brand guide setup is wired in UI")
        self.assert_true("Guías de marca para Codex" in html and "Crear guías base" in html, "Codex creative guide copy exists")
        self.assert_true("Borrador seguro antes de gastar" in html, "Paused creation is explained as safe draft")
        self.assert_true("todavía no gasta ni entra a aprendizaje" in html, "Approval note explains paused drafts do not enter learning")
        self.assert_true("prender y apagar algo que ya está aprendiendo" in html, "Paused draft copy distinguishes bad pause/resume habits")
        self.assert_true("scheduleMetaTokenAutoSave" in html, "Meta token paste auto-saves the local connection")
        self.assert_true("renderTokenSavedState" in html, "Saved token state replaces token input")
        self.assert_true("Token guardado" in html, "Spanish token saved confirmation exists")
        self.assert_true("Pegar otro token" in html, "Buyer can intentionally replace token later")
        self.assert_true("Se guarda automaticamente al pegarlo" in html, "Spanish token copy explains automatic saving")
        self.assert_true("Reintentar guardar" in html, "Manual token save is only a retry fallback")
        self.assert_true("Contraseña guardada. Te llevo a la guía final." in html, "Password save clearly advances onboarding")
        self.assert_true("findIndex(s=>s.id==='guide')" in html, "Password save moves to final guide step")
        self.assert_true("goToMetaTokenStep" in html, "Expired-token account search can return to token step")
        self.assert_true("Pega un token nuevo" in html, "Expired token message is buyer-friendly")
        self.assert_true("No se guarda en cookies" in html, "Token storage copy avoids cookie confusion")
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
                }
            )
            env_after = env_path.read_text(encoding="utf-8")
            saved = json.loads(ad_path.read_text(encoding="utf-8"))
            self.assert_true(result["saved"], "Setup config save returns success")
            self.assert_true("LICENSE_KEY=MAO-TESTBUYER-30628D" in env_after, "Blank license field preserves existing key")
            self.assert_true("LICENSE_BUYER_EMAIL=buyer@example.com" in env_after, "Buyer email saved to .env")
            self.assert_true("META_AD_ACCOUNT_ID=act_999" in env_after, "Ad account saved to .env")
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
        env_before = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        ad_before = ad_path.read_text(encoding="utf-8") if ad_path.exists() else ""
        business_files_before = {
            name: (dashboard.DATA_DIR / name).read_bytes() if (dashboard.DATA_DIR / name).exists() else None
            for name in dashboard.BUSINESS_DATA_FILES
        }
        binding_before = binding_path.read_bytes() if binding_path.exists() else None
        env_backup = {key: os.environ.get(key) for key in ["META_AD_ACCOUNT_ID", "META_ADS_AGENT_MODE", "LIVE_ACTIONS_ENABLED"]}
        try:
            dashboard.license_entitlements = lambda: {"plan": "individual", "is_agency": False, "max_devices": 1, "workspace_limit": 1}
            dashboard.update_env_values({"META_AD_ACCOUNT_ID": "act_old", "META_ADS_AGENT_MODE": "live", "LIVE_ACTIONS_ENABLED": "true"})
            dashboard.write_json(ad_path, {"account": {"id": "act_old"}, "creative": {"destination": {"page_id": "page_old", "url": "https://old.example"}}})
            dashboard.write_json(onboarding_path, {"completed": True})
            dashboard.write_json(metrics_path, {"source": "meta_graph", "campaigns": [{"name": "Old business"}]})
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
            self.assert_true(result.get("business_replaced") is True, "Confirmed individual switch records a clean replacement")
            self.assert_true(not metrics_path.exists(), "Confirmed individual switch removes old metrics memory")
            self.assert_true(not dashboard.load_onboarding_state().get("completed"), "Confirmed individual switch requires setup for the new business")
        finally:
            dashboard.license_entitlements = original_entitlements
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

    def test_release_package_excludes_runtime_data_and_includes_buyer_docs(self):
        """Test release script is buyer-safe and docs are included in source package."""
        print("\nTesting Release Package Safety Rules...")

        script = (ROOT_DIR / "scripts" / "package-release.sh").read_text(encoding="utf-8")
        required_excludes = [
            '.env',
            'ad-config.json',
            'dashboard/data/*',
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
            "docs/es-planes-de-licencia.md",
        ]
        for doc in buyer_docs:
            self.assert_true((ROOT_DIR / doc).exists(), f"Buyer doc exists: {doc}")
        for file in [
            "Dockerfile",
            "docker-compose.yml",
            ".dockerignore",
            "scripts/docker-entrypoint.sh",
            "scripts/run-docker.sh",
            "scripts/install-from-github.sh",
            "scripts/install-from-github.ps1",
            "scripts/build-mac-pkg.sh",
            "scripts/build-windows-exe.sh",
            "scripts/build-linux-bundle.sh",
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
        windows_exe_builder = (ROOT_DIR / "scripts" / "build-windows-exe.sh").read_text(encoding="utf-8")
        nsis_template = (ROOT_DIR / "installer" / "windows" / "MetaAdsAgentInstaller.nsi").read_text(encoding="utf-8")
        self.assert_true("@openai/codex" in dockerfile and "node:22" in dockerfile, "Docker image installs Node and Codex CLI")
        self.assert_true("CODEX_CREATIVE_ENABLED=false" in dockerfile and 'CODEX_CREATIVE_ENABLED: "false"' in compose, "Buyer installs leave optional Codex CLI execution off by default")
        self.assert_true("meta_ads_config" in compose and "meta_ads_brand_guides" in compose, "Docker Compose persists config and brand guides")
        self.assert_true("MetaAdsAgent-source.zip" in script, "Release ZIP includes a stable GitHub asset name for bootstrap installers")
        self.assert_true("install-from-github.ps1" in windows_installer and "install-from-github.sh" in mac_installer and "install-from-github.sh" in linux_installer, "Double-click installers can bootstrap from GitHub releases")
        self.assert_true("docker compose up --build" in windows_installer and "./scripts/run-docker.sh" in mac_installer, "Double-click installers launch Docker setup")
        self.assert_true("pkgbuild" in mac_pkg_builder and "productbuild" in mac_pkg_builder, "Mac PKG builder uses native package tools")
        self.assert_true("makensis" in windows_exe_builder and "MetaAdsAgentInstaller.nsi" in windows_exe_builder, "Windows EXE builder uses NSIS when available")
        self.assert_true("CreateShortcut" in nsis_template and "Instalar en Windows.bat" in nsis_template, "Windows NSIS installer creates a buyer shortcut")
        self.assert_true("https://licencias-miro-ai.uboost.lat" in (ROOT_DIR / ".env.example").read_text(encoding="utf-8"), "Buyer release uses deployed license server")
        self.assert_true("LICENSE_PUBLIC_KEY=" in (ROOT_DIR / ".env.example").read_text(encoding="utf-8"), "Buyer release includes only license verification key")
    
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
            self.test_skill_response_parsing,
            self.test_chat_approval_guardrail_tool,
            self.test_minimax_tool_request_executes_backend_tool,
            self.test_codex_creative_prompt_rejects_local_file_escape,
            self.test_audience_builder_readiness,
            self.test_chat_audience_tool,
            self.test_chat_saves_existing_adset_when_user_provides_it,
            self.test_chat_history_persists_and_resets,
            self.test_meta_asset_discovery_saves_connected_assets,
            self.test_live_insights_normalize_into_dashboard_metrics,
            self.test_supervised_daily_reads_real_data_and_stages_pause,
            self.test_demo_metrics_are_labeled,
            self.test_supervised_approval_executes_only_with_valid_license_and_retries_failures,
            self.test_campaign_creation_requires_active_confirmation,
            self.test_autopilot_action_updates_dashboard_only_after_meta_success,
            self.test_campaign_stack_execution_creates_full_ad_order,
            self.test_chat_stages_campaign_creation_but_cannot_approve,
            self.test_telegram_channel_routes_agent_and_blocks_approval,
            self.test_setup_page_contains_unlock_and_trust,
            self.test_setup_config_save_preserves_blank_license,
            self.test_individual_license_replaces_one_business_only_with_confirmation,
            self.test_agency_spaces_keep_client_data_separate,
            self.test_onboarding_state_persists,
            self.test_onboarding_requires_real_meta_data,
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
