"""Single source of truth for routing public Admira MCPs to operating skills."""

MCP_PRIMARY_SKILL = {
    "get_real_meta_context": "meta-account-connection",
    "start_meta_oauth_connection": "meta-account-connection",
    "get_meta_oauth_workspaces": "meta-account-connection",
    "select_meta_oauth_workspace": "meta-account-connection",
    "search_meta_targeting": "campaign-strategy",
    "inspect_adset_targeting": "campaign-strategy",
    "run_daily_brief": "daily-brief",
    "schedule_experiment_review": "measurement-optimization",
    "list_experiment_reviews": "measurement-optimization",
    "run_due_experiment_reviews": "measurement-optimization",
    "save_optimization_research": "measurement-optimization",
    "list_optimization_research": "measurement-optimization",
    "review_signal_quality": "measurement-optimization",
    "set_campaign_metric_priorities": "measurement-optimization",
    "preflight_campaign": "meta-campaign-execution",
    "fetch_public_asset": "brand-and-assets",
    "codex_image_generate": "creative-production-codex-image",
    "list_recent_creatives": "creative-production-codex-image",
    "codex_creative_plan": "creative-production-codex-image",
    "search_motion_graphic_recipes": "motion-graphics-video",
    "generate_motion_graphic_video": "motion-graphics-video",
    "list_lead_forms": "lead-form-management",
    "stage_lead_form": "lead-form-management",
    "create_lead_form": "lead-form-management",
    "create_whatsapp_campaign": "meta-campaign-execution",
    "create_lead_form_campaign": "meta-campaign-execution",
    "create_website_campaign": "meta-campaign-execution",
    "create_messaging_campaign": "meta-campaign-execution",
    "create_app_campaign": "meta-campaign-execution",
    "create_on_meta_campaign": "meta-campaign-execution",
    "edit_campaign": "campaign-editing",
    "connect_chatgpt": "chatgpt-connection",
    "stage_budget_change": "campaign-editing",
    "pause_campaign": "campaign-editing",
    "resume_campaign": "campaign-editing",
    "schedule_campaign_activation": "campaign-editing",
    "delete_campaign": "campaign-editing",
    "list_pending_approvals": "telegram-approvals",
    "approve_action": "telegram-approvals",
    "reject_action": "telegram-approvals",
    "save_agent_preferences": "business-onboarding",
    "save_daily_social_content_settings": "organic-content-strategy",
    "stage_organic_social_post": "organic-content-strategy",
    "save_content_asset": "brand-and-assets",
    "record_verified_signal": "measurement-optimization",
    "get_verified_signal_summary": "measurement-optimization",
    "verified_signal_feedback_prompt": "measurement-optimization",
    "save_business_memory": "business-onboarding",
    "save_durable_memory": "business-onboarding",
    "save_ads_onboarding": "business-onboarding",
    "save_brand_memory": "brand-and-assets",
    "save_product_memory": "brand-and-assets",
    "import_product_catalog": "product-catalog-management",
    "search_product_catalog": "product-catalog-management",
    "save_ad_brief": "brand-and-assets",
    "save_creative_references": "brand-and-assets",
}


def skill_path_for_mcp(name):
    skill = MCP_PRIMARY_SKILL.get(str(name or "").strip())
    return f"skills/{skill}/SKILL.md" if skill else ""


def tool_description_with_skill(name, description):
    path = skill_path_for_mcp(name)
    if not path:
        return str(description or "")
    return (
        f"MANDATORY PRIMARY PROCEDURE: read `{path}` completely before calling this MCP. "
        "Reading it does not itself authorize execution. "
        + str(description or "")
    )
