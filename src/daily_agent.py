#!/usr/bin/env python3
"""Daily runner and approval executor for Admira IA."""
import argparse
import json
import struct
import sys
import zlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, str(Path(__file__).parent))

from budget_optimizer import BudgetOptimizer, OptimizationStrategy, PerformanceMetrics
from creative_refresh import campaigns_needing_refresh, generate_creative_refresh, mark_asset_files_retained, recent_creative_refreshes
from decision_memory import load_profitability_rules, recommendation_decision_evidence, record_daily_decision_memory
from experiment_scheduler import experiment_review_payload
from graph_executor import execute_upload_payload
from license import license_status
from local_store import now_iso, read_json, write_json
from meta_insights import aggregate_campaigns as aggregate_meta_campaigns, collect_meta_snapshot, save_meta_snapshot
from meta_upload import recent_uploads, stage_upload
from optimization_engine import (
    anomaly_diagnostics,
    calibrate_conversion_lag,
    funnel_diagnostics,
    load_optimization_state,
    portfolio_recommendations,
    reconcile_business_outcomes,
    record_performance_snapshot,
    record_optimization_action,
    record_shadow_outcomes,
)
from product_config import ROOT_DIR, load_config
from security import redact_payload
from shopify_connector import sync_shopify
from setup_status import build_setup_status
from adset_controls import apply_placement_targeting
from expert_campaign import (
    boolish,
    creative_source_available,
    manual_creative_completion_enabled,
    normalize_budget_plan,
    normalize_status_plan,
    placeholder_ad_count,
    placeholder_ad_names,
    placeholder_static_ad_enabled,
)
from social_flow_client import SocialFlowClient, config_snapshot, send_notification


DATA_DIR = ROOT_DIR / "dashboard" / "data"
OUTPUT_DIR = ROOT_DIR / "output"
AD_CONFIG_FILE = ROOT_DIR / "ad-config.json"
METRICS_FILE = DATA_DIR / "metrics.json"
ACTIONS_FILE = DATA_DIR / "actions.json"
PENDING_FILE = DATA_DIR / "pending_approvals.json"
FATIGUE_LOG = OUTPUT_DIR / "fatigue-log.md"

def money(value):
    return round(float(value or 0), 2)


def pct_change(current, previous):
    current = float(current or 0)
    previous = float(previous or 0)
    if previous == 0:
        return 0.0
    return ((current - previous) / previous) * 100


def local_review_time(value):
    try:
        review_at = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        timezone_name = str(getattr(load_config(), "daily_brief_timezone", "UTC") or "UTC")
        return review_at.astimezone(ZoneInfo(timezone_name)).strftime("%Y-%m-%d %H:%M %Z")
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        return str(value or "")


def load_metrics():
    metrics = read_json(METRICS_FILE, {"timestamp": now_iso(), "campaigns": []})
    metrics["campaigns"] = [enrich_campaign({**c, "data_source": c.get("data_source") or metrics.get("source", "")}) for c in metrics.get("campaigns", [])]
    metrics["summary"] = build_summary(metrics["campaigns"])
    return metrics


def save_metrics(metrics):
    metrics["timestamp"] = now_iso()
    metrics["campaigns"] = [enrich_campaign({**c, "data_source": c.get("data_source") or metrics.get("source", "")}) for c in metrics.get("campaigns", [])]
    metrics["summary"] = build_summary(metrics["campaigns"])
    write_json(METRICS_FILE, metrics)


def enrich_campaign(campaign):
    campaign = dict(campaign)
    spend = float(campaign.get("spend", 0))
    clicks = int(campaign.get("clicks", 0))
    impressions = int(campaign.get("impressions", 0))
    conversions = int(campaign.get("conversions", 0))
    revenue = float(campaign.get("revenue", 0))
    campaign.setdefault("id", campaign.get("campaign_id", campaign.get("name", "unknown")))
    campaign.setdefault("name", campaign.get("id", "Unknown Campaign"))
    campaign.setdefault("status", "active")
    campaign.setdefault("daily_budget", 100)
    campaign.setdefault("target_type", "adset")
    campaign.setdefault("target_id", campaign.get("adset_id", campaign.get("id")))
    campaign.setdefault("frequency", 1.0)
    campaign["ctr"] = (clicks / impressions * 100) if impressions else float(campaign.get("ctr", 0))
    # Unknown is not poor performance. Keep zero-conversion CPA at 0 and let the
    # evidence gate decide when spend/runtime are mature enough to judge.
    campaign["cpa"] = (spend / conversions) if conversions else 0.0
    campaign["cpc"] = (spend / clicks) if clicks else float(campaign.get("cpc", 0))
    campaign["roas"] = (revenue / spend) if spend else float(campaign.get("roas", 0))
    campaign.setdefault("previous_cpa", campaign["cpa"])
    campaign.setdefault("previous_ctr", campaign["ctr"] * 1.05)
    campaign.setdefault("previous_cpc", campaign["cpc"] * 0.92 if campaign["cpc"] else 0)
    campaign["health"] = classify_campaign(campaign)
    return campaign


def classify_campaign(campaign):
    config = load_config()
    rules = load_profitability_rules()
    ctr_drop = pct_change(campaign.get("ctr"), campaign.get("previous_ctr"))
    cpc_rise = pct_change(campaign.get("cpc"), campaign.get("previous_cpc"))
    cpa_rise = pct_change(campaign.get("cpa"), campaign.get("previous_cpa"))
    if str(campaign.get("status") or "").lower() == "paused":
        return "paused"
    deterioration = ctr_drop <= -20 or cpc_rise >= 30 or cpa_rise >= 25
    frequency_with_deterioration = campaign.get("frequency", 0) > 3 and (ctr_drop <= -10 or cpc_rise >= 15 or cpa_rise >= 15)
    if deterioration or frequency_with_deterioration:
        return "fatigue"
    decision = portfolio_recommendations([campaign], rules)[0]
    if decision.get("decision") == "scale":
        return "winning"
    if decision.get("decision") in {"reduce", "pause_candidate"}:
        return "losing"
    return "neutral"


def build_summary(campaigns):
    spend = sum(float(c.get("spend", 0)) for c in campaigns)
    revenue = sum(float(c.get("revenue", 0)) for c in campaigns)
    clicks = sum(int(c.get("clicks", 0)) for c in campaigns)
    impressions = sum(int(c.get("impressions", 0)) for c in campaigns)
    conversions = sum(int(c.get("conversions", 0)) for c in campaigns)
    active = [c for c in campaigns if c.get("status") == "active"]
    return {
        "total_spend": money(spend),
        "total_revenue": money(revenue),
        "total_impressions": impressions,
        "total_clicks": clicks,
        "total_conversions": conversions,
        "overall_roas": round(revenue / spend, 2) if spend else 0,
        "overall_ctr": round(clicks / impressions * 100, 2) if impressions else 0,
        "overall_cpa": money(spend / conversions) if conversions else 0,
        "active_campaigns": len(active),
        "active_budget": money(sum(float(c.get("daily_budget", 0)) for c in active)),
    }


def calculate_recommendations(campaigns):
    config = load_config()
    rules = load_profitability_rules()
    state = load_optimization_state()
    recommendations = []
    campaigns_by_id = {str(c.get("id") or c.get("campaign_id")): c for c in campaigns}
    for decision in portfolio_recommendations(campaigns, rules, state):
        campaign = campaigns_by_id.get(str(decision.get("campaign_id")), {})
        current = float(decision.get("current_budget", 0))
        change_pct = float(decision.get("change_pct", 0))
        recommendation = {
            "id": f"budget_{decision.get('campaign_id')}",
            "type": "budget_change",
            "campaign_id": decision.get("campaign_id"),
            "target_type": decision.get("target_type", "campaign"),
            "target_id": decision.get("target_id"),
            "campaign_name": decision.get("campaign_name"),
            "current_budget": money(current),
            "recommended_budget": money(decision.get("recommended_budget")),
            "change_pct": round(change_pct, 1),
            "proposal_only": decision.get("shadow_mode", True) and decision.get("action") != "observe",
            "requires_approval": decision.get("action") != "observe" and not decision.get("shadow_mode", True) and (
                config.autonomy_mode == "supervised" or abs(change_pct) > config.approval_required_over_pct
            ),
            "reason": decision.get("reason"),
            "health": campaign.get("health"),
            "decision": decision.get("decision"),
            "action": decision.get("action"),
            "objective": decision.get("objective"),
            "evidence_gate": decision.get("evidence_gate"),
            "mutation_allowed": decision.get("mutation_allowed", False),
            "shadow_mode": decision.get("shadow_mode", True),
        }
        recommendation["decision_evidence"] = recommendation_decision_evidence(campaign, recommendation, rules)
        recommendations.append(recommendation)
    return recommendations


def fatigue_items(campaigns):
    items = []
    for campaign in campaigns:
        ctr_drop = pct_change(campaign.get("ctr"), campaign.get("previous_ctr"))
        cpc_rise = pct_change(campaign.get("cpc"), campaign.get("previous_cpc"))
        cpa_rise = pct_change(campaign.get("cpa"), campaign.get("previous_cpa"))
        reasons = []
        deterioration = ctr_drop <= -20 or cpc_rise >= 30 or cpa_rise >= 25
        if campaign.get("frequency", 0) > 3 and deterioration:
            reasons.append(f"frequency {campaign.get('frequency'):.1f}")
        if ctr_drop <= -20:
            reasons.append(f"CTR {abs(ctr_drop):.0f}% down")
        if cpc_rise >= 30:
            reasons.append(f"CPC {cpc_rise:.0f}% up")
        if cpa_rise >= 25:
            reasons.append(f"CPA {cpa_rise:.0f}% up")
        if reasons:
            items.append({"campaign_id": campaign.get("id"), "campaign_name": campaign.get("name"), "reasons": reasons})
    return items


def append_fatigue_log(items):
    if not items:
        return
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(FATIGUE_LOG, "a", encoding="utf-8") as handle:
        handle.write(f"\n## {now_iso()}\n")
        for item in items:
            handle.write(f"- {item['campaign_name']}: {', '.join(item['reasons'])}\n")


def log_action(action_type, payload, status="completed"):
    actions = read_json(ACTIONS_FILE, [])
    record = {"id": f"act_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}", "type": action_type, "status": status, "payload": redact_payload(payload), "created_at": now_iso()}
    actions.insert(0, record)
    write_json(ACTIONS_FILE, actions[:500])
    return record


def add_pending(action_type, payload):
    pending = read_json(PENDING_FILE, [])
    approval_id = payload.get("approval_id") or f"approval_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    if any(item.get("id") == approval_id for item in pending):
        return None
    record = {"id": approval_id, "type": action_type, "status": "pending", "payload": payload, "created_at": now_iso()}
    pending.insert(0, record)
    write_json(PENDING_FILE, pending[:250])
    log_action(action_type, payload, "pending_approval")
    return record


def command_for_pending(item):
    payload = item.get("payload", {})
    if item.get("type") == "budget_change":
        budget_cents = int(float(payload.get("recommended_budget", payload.get("new_budget", 0))) * 100)
        return ["set_budget", payload.get("target_type", "adset"), payload.get("target_id", payload.get("campaign_id")), budget_cents]
    if item.get("type") == "resume_campaign":
        return ["resume", payload.get("target_type", "adset"), payload.get("target_id", payload.get("campaign_id"))]
    if item.get("type") == "pause_campaign":
        return ["pause", payload.get("target_type", "campaign"), payload.get("target_id", payload.get("campaign_id"))]
    if item.get("type") == "create_campaign":
        return ["create_campaign", payload.get("path")]
    if item.get("type") == "create_lead_form":
        return ["create_lead_form", payload.get("path")]
    if item.get("type") == "creative_upload":
        return ["creative_upload", payload.get("payload_path")]
    return None


def social_id_from_result(result):
    try:
        body = json.loads(result.get("stdout") or "{}")
    except json.JSONDecodeError:
        body = {}
    if isinstance(body, dict):
        return body.get("id") or body.get("campaign_id") or body.get("adset_id")
    return None


def lead_form_id_from_result(result):
    try:
        body = json.loads(result.get("stdout") or "{}")
    except json.JSONDecodeError:
        body = {}
    if isinstance(body, dict):
        return body.get("lead_gen_form_id") or body.get("id")
    return ""


def social_body_from_result(result):
    try:
        body = json.loads(result.get("stdout") or "{}")
    except (TypeError, json.JSONDecodeError):
        body = {}
    return body if isinstance(body, dict) else {}


def result_debug_text(result):
    """Collect provider error text without exposing it directly to buyers."""
    if not isinstance(result, dict):
        return str(result or "")
    parts = []
    for key in ("stderr", "stdout", "error", "message"):
        value = result.get(key)
        if value:
            parts.append(str(value))
    body = social_body_from_result(result)
    if body:
        parts.append(json.dumps(body, ensure_ascii=False))
    return "\n".join(parts).lower()


def creative_blocked_by_development_mode(result):
    text = result_debug_text(result)
    return (
        "development mode" in text
        or "must be in public" in text
        or ("error_subcode" in text and "1885183" in text)
    )


def direct_publishing_preference(ad_plan):
    for key in ("use_direct_publishing", "direct_publishing", "create_as_unpublished_post", "unpublished_post"):
        parsed = boolish(ad_plan.get(key))
        if parsed is not None:
            return parsed
    strategy = str(ad_plan.get("creative_creation_strategy") or ad_plan.get("publishing_strategy") or "").strip().lower()
    if strategy in {"direct", "direct_publishing", "native_post", "page_post", "dark_post", "unpublished_post"}:
        return True
    if strategy in {"direct_creative", "inline_creative", "image_hash", "legacy"}:
        return False
    return None


def direct_publishing_missing_requirements(ad_plan, destination, client, video_id=""):
    missing = []
    if not destination.get("page_id"):
        missing.append("Facebook Page ID")
    if not getattr(client.config, "meta_publishing_access_token", ""):
        missing.append("META_PUBLISHING_ACCESS_TOKEN")
    has_page_post_asset = bool(ad_plan.get("creative_image_path") or ad_plan.get("image_url") or ad_plan.get("video_url"))
    if video_id and not ad_plan.get("video_url"):
        missing.append("video_url")
    if not has_page_post_asset:
        missing.append("creative_image_path_or_image_url_or_video_url")
    if not hasattr(client, "create_page_post"):
        missing.append("create_page_post capability")
    return missing


def create_native_page_post_for_ad(client, destination, ad_plan, link, body_text, headline, approved=False):
    page_post_result = client.create_page_post(
        destination.get("page_id", ""),
        message="\n\n".join([part for part in [body_text, headline] if part]),
        link=link,
        image_path=ad_plan.get("creative_image_path") or "",
        image_url=ad_plan.get("image_url") or "",
        video_url=ad_plan.get("video_url") or "",
        unpublished_content_type="ADS_POST",
        cta=ad_plan.get("cta", "LEARN_MORE"),
        message_destination=message_destination_from_plan(ad_plan),
        approved=approved,
    )
    object_story_id = ""
    try:
        body = json.loads(page_post_result.get("stdout") or page_post_result.get("stderr") or "{}")
        if isinstance(body, dict):
            object_story_id = str(body.get("object_story_id") or body.get("post_id") or "").strip()
    except json.JSONDecodeError:
        pass
    return object_story_id, page_post_result


def direct_page_video_story_spec(destination, ad_plan, link, body_text, headline, page_post_body):
    """Build a website-aware video story spec from a Page video created by Publicación directa.

    Promoting a Page video post by `object_story_id` can pass creative creation
    but still fail at final ad validation with "website URL required" because
    Meta does not always treat the Page post CTA as the ad destination. When we
    already have the Page video ID, create the ad creative as explicit
    `video_data` with the landing URL in the CTA.
    """
    if not isinstance(page_post_body, dict):
        return {}
    if not ad_plan.get("video_url"):
        return {}
    if message_destination_from_plan(ad_plan) or ad_plan.get("lead_gen_form_id"):
        return {}
    page_id = str((destination or {}).get("page_id") or "").strip()
    video_id = str(page_post_body.get("video_id") or page_post_body.get("id") or "").strip()
    target = str(link or ad_plan.get("cta_link") or "").strip()
    if not (page_id and video_id and target.startswith(("http://", "https://"))):
        return {}
    video_data = {
        "video_id": video_id,
        "message": body_text or "",
        "title": headline or "",
        "call_to_action": {
            "type": SocialFlowClient.normalize_call_to_action(ad_plan.get("cta", "LEARN_MORE")),
            "value": {"link": target},
        },
    }
    thumbnail = str(page_post_body.get("thumbnail_url") or page_post_body.get("picture") or "").strip()
    if thumbnail:
        video_data["image_url"] = thumbnail
    story = {"page_id": page_id, "video_data": video_data}
    instagram_actor_id = str((destination or {}).get("instagram_actor_id") or "").strip()
    if instagram_actor_id:
        story["instagram_actor_id"] = instagram_actor_id
    return story


def static_creative_source_available(ad_plan):
    return any(ad_plan.get(key) for key in ("creative_image_path", "image_hash", "image_url", "object_story_spec", "object_story_id"))


def write_solid_placeholder_png(path, width=1080, height=1080, color=(250, 250, 247)):
    """Create a simple local PNG placeholder without external imaging deps."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    raw_row = bytes([0]) + bytes(color) * width
    raw = raw_row * height
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    return str(path)


def ensure_placeholder_image(campaign):
    safe_name = "".join(char.lower() if char.isalnum() else "-" for char in str(campaign.get("name") or "campaign"))[:80].strip("-")
    safe_name = safe_name or "campaign"
    placeholder_dir = OUTPUT_DIR / "manual-creative-placeholders"
    placeholder_path = placeholder_dir / f"{safe_name}-replace-with-video.png"
    if not placeholder_path.exists():
        write_solid_placeholder_png(placeholder_path)
    return str(placeholder_path)


def manual_creative_completion_task(campaign, ad_plan, campaign_id, adset_ids, link, body_text, headline, placeholder_ad_ids=None, placeholder_image_path=""):
    adsets = campaign.get("ad_sets") or []
    placements = adsets[0].get("placements") if adsets and isinstance(adsets[0], dict) else {}
    video_url = str(ad_plan.get("deferred_video_url") or ad_plan.get("video_url") or "").strip()
    names = placeholder_ad_names(ad_plan)
    return {
        "type": "ads_manager_video_creative_completion",
        "reason": "Meta requires an ad creative before an ad can exist. For video website ads, Admira can prepare the paused structure and, when requested, paused placeholder ads so the buyer only replaces the media in Ads Manager.",
        "campaign_id": campaign_id,
        "adset_ids": [value for value in adset_ids if value],
        "ad_ids": [value for value in (placeholder_ad_ids or []) if value],
        "ad_names": names,
        "placeholder_ads_created": bool(placeholder_ad_ids),
        "placeholder_image_path": placeholder_image_path,
        "landing_url": link,
        "video_url": video_url,
        "primary_text": body_text,
        "headline": headline,
        "cta": SocialFlowClient.normalize_call_to_action(ad_plan.get("cta", "LEARN_MORE")),
        "placements": placements,
        "dimension_guidance": [
            "Review 1:1 feed preview if the video will appear in feeds.",
            "Review 4:5 feed preview for stronger mobile feed usage.",
            "Review 9:16 Stories/Reels preview before enabling vertical placements.",
        ],
        "checklist": [
            "Open Meta Ads Manager and find the paused campaign/ad set IDs shown here.",
            "Open each paused placeholder ad, or create a new ad inside the prepared ad set if no placeholder ads were created.",
            "Replace the temporary static image with the final video.",
            "Keep or paste the saved primary text, headline, CTA, and website URL.",
            "Check feed, stories, and reels previews before turning anything on.",
            "Leave the campaign paused until the final video creative is reviewed and approved.",
        ],
        "buyer_warning": "Do not activate the placeholder image. It exists only to save setup time before replacing the media with the real video.",
    }


def placeholder_ad_name(campaign, ad_plan, index, total):
    names = placeholder_ad_names(ad_plan)
    if index < len(names):
        return names[index]
    suffix = f" {index + 1}" if total > 1 else ""
    return f"{campaign.get('name', 'New Campaign')} - Ad{suffix}"


def campaign_budget_level_from_plan(campaign, budget_plan):
    plan = budget_plan if isinstance(budget_plan, dict) else {}
    raw = str(plan.get("budget_level") or campaign.get("budget_level") or "").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"campaign", "campaign_budget", "cbo", "advantage", "advantage_plus", "advantage_campaign_budget"}:
        return "campaign"
    return "adset"


def meta_campaign_has_campaign_budget(client, campaign_id):
    if not campaign_id or not hasattr(client, "campaign_details"):
        return False
    result = client.campaign_details(campaign_id)
    if result.get("returncode") not in {0, None}:
        return False
    body = social_body_from_result(result)
    for key in ("daily_budget", "lifetime_budget"):
        try:
            if int(float(str(body.get(key) or 0).replace(",", ""))) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def prior_meta_id(prior_result, key, step_name):
    if not isinstance(prior_result, dict):
        return ""
    direct = str(prior_result.get(key) or "").strip()
    if direct:
        return direct
    for step in prior_result.get("steps") or []:
        if not isinstance(step, dict) or step.get("step") != step_name:
            continue
        value = str(step.get(key) or "").strip()
        if value:
            return value
    return ""


def prior_result_missing_website_url(prior_result):
    if not isinstance(prior_result, dict):
        return False
    text = json.dumps(prior_result, ensure_ascii=False).lower()
    return "website url" in text and ("required" in text or "missing" in text or "falta" in text)


def persist_campaign_execution_state(path, campaign, updates):
    try:
        execution_state = dict(campaign.get("execution_state") or {})
        cleaned = {}
        for key, value in (updates or {}).items():
            if value is None or value == "":
                continue
            cleaned[key] = value
        execution_state.update(cleaned)
        campaign["execution_state"] = execution_state
        write_json(Path(path), campaign)
    except Exception:
        pass


def campaign_objective_for_social(objective):
    mapping = {
        "PURCHASES": "OUTCOME_SALES",
        "CONVERSIONS": "OUTCOME_SALES",
        "SALES": "OUTCOME_SALES",
        "LEADS": "LEAD_GENERATION",
        "LEAD_GENERATION": "LEAD_GENERATION",
        "LEAD_FORM": "LEAD_GENERATION",
        "LEAD_FORMS": "LEAD_GENERATION",
        "INSTANT_FORM": "LEAD_GENERATION",
        "INSTANT_FORMS": "LEAD_GENERATION",
        "FORMS": "LEAD_GENERATION",
        "MESSAGES": "OUTCOME_ENGAGEMENT",
        "MESSAGE": "OUTCOME_ENGAGEMENT",
        "CONVERSATIONS": "OUTCOME_ENGAGEMENT",
        "WHATSAPP": "OUTCOME_ENGAGEMENT",
        "MESSENGER": "OUTCOME_ENGAGEMENT",
        "ENGAGEMENT": "OUTCOME_ENGAGEMENT",
    }
    return mapping.get(str(objective or "").upper(), "OUTCOME_SALES")


def lead_gen_form_id_from_plan(ad_plan):
    for key in ("lead_gen_form_id", "lead_form_id", "instant_form_id", "meta_lead_form_id", "form_id"):
        value = str((ad_plan or {}).get(key) or "").strip()
        if value:
            return value
    return ""


def message_destination_from_plan(ad_plan):
    for key in ("message_destination", "messaging_destination", "messaging_app", "click_to_message_destination", "conversation_destination"):
        value = str((ad_plan or {}).get(key) or "").strip()
        if value:
            return SocialFlowClient.normalize_message_destination(value)
    text = " ".join(
        str((ad_plan or {}).get(key) or "")
        for key in ("destination_type", "objective", "goal", "sales_channel", "conversion_location", "cta", "landing_url")
    ).lower()
    if "whatsapp" in text or "wa.me" in text or "api.whatsapp.com" in text:
        return "WHATSAPP"
    if "messenger" in text or "m.me/" in text:
        return "MESSENGER"
    if "instagram" in text and ("direct" in text or "dm" in text or "mensaje" in text or "message" in text):
        return "INSTAGRAM_DIRECT"
    return ""


def adset_optimization_goal_for_campaign(adset, campaign, lead_gen_form_id="", message_destination=""):
    explicit = str((adset or {}).get("optimization_goal") or "").strip()
    if explicit:
        return SocialFlowClient.normalize_optimization_goal(explicit)
    objective = str((campaign or {}).get("objective") or "").upper()
    if lead_gen_form_id or objective in {"LEADS", "LEAD_GENERATION", "LEAD_FORM", "LEAD_FORMS", "INSTANT_FORM", "INSTANT_FORMS", "FORMS"}:
        return "LEAD_GENERATION"
    if message_destination:
        return "CONVERSATIONS"
    return "LINK_CLICKS"


def targeting_for_social(targeting):
    targeting = targeting or {}
    if isinstance(targeting.get("geo_locations"), dict):
        geo_locations = targeting["geo_locations"]
    else:
        geo_locations = None
    age_range = targeting.get("age_range") or {}
    countries = [str(item).upper() for item in targeting.get("locations", ["US"]) if item]
    meta_targeting = targeting.get("meta_targeting") or {}
    geo_locations = geo_locations or {"countries": countries or ["US"]}
    selected_locations = meta_targeting.get("locations") if isinstance(meta_targeting, dict) else []
    if isinstance(selected_locations, list) and selected_locations:
        geo_locations = {}
        for item in selected_locations:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or item.get("id") or "").strip()
            location_type = str(item.get("type") or "").lower()
            country_code = str(item.get("country_code") or "").strip().upper()
            if location_type == "country" or (len(key) == 2 and key.isalpha()):
                geo_locations.setdefault("countries", []).append(key.upper() if key else country_code)
            elif location_type == "city" and key:
                geo_locations.setdefault("cities", []).append({"key": key})
            elif location_type == "region" and key:
                geo_locations.setdefault("regions", []).append({"key": key})
            elif country_code:
                geo_locations.setdefault("countries", []).append(country_code)
        if not geo_locations:
            geo_locations = {"countries": countries or ["US"]}
    spec = {
        "geo_locations": geo_locations,
        "age_min": int(age_range.get("min", 18)),
        "age_max": int(age_range.get("max", 65)),
    }
    selected_interests = meta_targeting.get("interests") if isinstance(meta_targeting, dict) else []
    if isinstance(selected_interests, list):
        interests = []
        for item in selected_interests:
            if not isinstance(item, dict):
                continue
            interest_id = str(item.get("id") or "").strip()
            name = str(item.get("name") or "").strip()
            if interest_id and name:
                interests.append({"id": interest_id, "name": name})
        if interests:
            spec["interests"] = interests
    for key in ("publisher_platforms", "facebook_positions", "instagram_positions", "messenger_positions", "audience_network_positions", "threads_positions"):
        if targeting.get(key):
            spec[key] = targeting.get(key)
    for key in (
        "custom_audiences",
        "excluded_custom_audiences",
        "excluded_interests",
        "exclusions",
        "flexible_spec",
        "device_platforms",
        "user_os",
        "user_device",
        "wireless_carrier",
        "genders",
    ):
        if targeting.get(key):
            spec[key] = targeting.get(key)
    return apply_placement_targeting(spec, targeting.get("placements") or targeting.get("placement_preset"))


def execute_lead_form_creation(path, client, approved=False):
    payload = read_json(Path(path), {})
    if not isinstance(payload, dict) or not payload:
        return {"ok": False, "error": "invalid_lead_form_payload", "path": path}
    result = client.create_lead_form(
        payload.get("page_id") or "",
        payload.get("name") or payload.get("form_name") or "Nuevo formulario",
        questions=payload.get("questions") or [],
        privacy_policy_url=payload.get("privacy_policy_url") or "",
        privacy_policy_link_text=payload.get("privacy_policy_link_text") or "Política de privacidad",
        follow_up_action_url=payload.get("follow_up_action_url") or "",
        locale=payload.get("locale") or "",
        form_type=payload.get("form_type") or "",
        context_card=payload.get("context_card") or {},
        thank_you_page=payload.get("thank_you_page") or {},
        custom_disclaimer=payload.get("custom_disclaimer") or {},
        approved=approved,
    )
    form_id = lead_form_id_from_result(result)
    return {
        "ok": bool(form_id),
        "executed": True,
        "lead_gen_form_id": form_id,
        "page_id": payload.get("page_id") or "",
        "name": payload.get("name") or "",
        "path": str(path),
        "result": result,
    }


def execute_campaign_creation(path, client, approved=False, prior_result=None):
    campaign = read_json(Path(path), {})
    if not campaign:
        return {"ok": False, "error": "Campaign file missing or empty", "path": path}
    ad_config = read_json(AD_CONFIG_FILE, {})
    destination = ad_config.get("creative", {}).get("destination", {})
    ad_plan = dict(campaign.get("ad") or {})
    lead_gen_form_id = lead_gen_form_id_from_plan(ad_plan)
    message_destination = message_destination_from_plan(ad_plan)
    manual_completion = manual_creative_completion_enabled(ad_plan)
    placeholder_static = placeholder_static_ad_enabled(ad_plan)
    final_status = str(ad_plan.get("final_status") or "PAUSED").upper()
    if final_status not in {"PAUSED", "ACTIVE"}:
        final_status = "PAUSED"
    active_confirmed = bool(ad_plan.get("active_spend_confirmed"))
    status_plan = campaign.get("status_plan") or normalize_status_plan({}, final_status, active_confirmed)
    if manual_completion or placeholder_static:
        final_status = "PAUSED"
        active_confirmed = False
        status_plan = {"campaign": "PAUSED", "adset": "PAUSED", "ad": "PAUSED"}
    if not active_confirmed:
        status_plan = {key: ("PAUSED" if str(value).upper() == "ACTIVE" else value) for key, value in status_plan.items()}
    missing = []
    if not client.config.ad_account_id:
        missing.append("META_AD_ACCOUNT_ID")
    if not destination.get("page_id") and not ad_plan.get("object_story_id"):
        missing.append("Facebook Page ID")
    if not (ad_plan.get("landing_url") or destination.get("url") or ad_plan.get("object_story_spec") or ad_plan.get("object_story_id") or message_destination or lead_gen_form_id):
        missing.append("landing URL")
    if not creative_source_available(ad_plan) and not (manual_completion or placeholder_static):
        missing.append("creative image path, image hash, image URL, video URL, object_story_spec, or object_story_id")
    elif ad_plan.get("creative_image_path") and not Path(ad_plan.get("creative_image_path")).exists():
        missing.append(f"creative image file missing: {ad_plan.get('creative_image_path')}")
    if final_status == "ACTIVE" and not active_confirmed:
        missing.append("active spend confirmation")
    if missing:
        return {"ok": False, "mode": client.config.mode, "executed": False, "blocked": True, "missing_requirements": missing, "path": path}
    if not client.config.live and not approved:
        return {
            "ok": True,
            "mode": "dry-run",
            "executed": False,
            "path": path,
            "planned": {
                "campaign": campaign.get("name"),
                "ad_sets": [adset.get("name") for adset in campaign.get("ad_sets", [])],
                "final_status": final_status,
                "will_create_ad": not manual_completion or placeholder_static,
                "manual_creative_completion": manual_completion,
                "create_placeholder_ad": placeholder_static,
                "status_plan": status_plan,
            },
        }
    budget_plan = campaign.get("budget_plan") or normalize_budget_plan({}, float(campaign.get("budget", {}).get("daily", 0) or 0))
    budget_level = campaign_budget_level_from_plan(campaign, budget_plan)
    execution_state = campaign.get("execution_state") if isinstance(campaign.get("execution_state"), dict) else {}
    campaign_id = str(
        execution_state.get("campaign_id")
        or campaign.get("meta_campaign_id")
        or prior_meta_id(prior_result, "campaign_id", "create_campaign")
        or ""
    ).strip()
    steps = []
    if campaign_id:
        steps.append({"step": "create_campaign", "ok": True, "campaign_id": campaign_id, "status": status_plan.get("campaign", "PAUSED"), "reused": True})
        if meta_campaign_has_campaign_budget(client, campaign_id):
            budget_level = "campaign"
            if hasattr(client, "update_campaign_bid_strategy"):
                bid_result = client.update_campaign_bid_strategy(campaign_id, "LOWEST_COST_WITHOUT_CAP", approved=approved)
                bid_ok = bid_result.get("returncode") in {0, None}
                steps.append({"step": "update_campaign_bid_strategy", "ok": bid_ok, "campaign_id": campaign_id, "result": bid_result})
                if not bid_ok:
                    return {"ok": False, "mode": client.config.mode, "executed": True, "campaign_id": campaign_id, "failed_step": "update_campaign_bid_strategy", "steps": steps}
    else:
        campaign_daily_budget = int(float(campaign.get("budget", {}).get("daily", 0) or 0) * 100) if budget_level == "campaign" else 0
        campaign_adset_budget_sharing = False if budget_level == "adset" else None
        campaign_result = client.create_campaign(
            client.config.ad_account_id,
            campaign.get("name", "New Campaign"),
            campaign_objective_for_social(campaign.get("objective")),
            campaign_daily_budget,
            status_plan.get("campaign", "PAUSED"),
            approved=approved,
            bid_strategy="LOWEST_COST_WITHOUT_CAP" if campaign_daily_budget else "",
            is_adset_budget_sharing_enabled=campaign_adset_budget_sharing,
        )
        campaign_id = social_id_from_result(campaign_result)
        steps.append({"step": "create_campaign", "ok": bool(campaign_id), "campaign_id": campaign_id, "status": status_plan.get("campaign", "PAUSED"), "result": campaign_result})
        if campaign_id:
            persist_campaign_execution_state(path, campaign, {"campaign_id": campaign_id, "budget_level": budget_level})
    if not campaign_id:
        return {"ok": False, "mode": client.config.mode, "executed": True, "failed_step": "create_campaign", "steps": steps}
    adset_ids = []
    for adset in campaign.get("ad_sets", []):
        if budget_level == "campaign":
            daily_budget = 0
            lifetime_budget = 0
        else:
            daily_budget = int(float(adset.get("budget", 0) or budget_plan.get("adset_daily") or campaign.get("budget", {}).get("daily", 0) or 0) * 100)
            lifetime_budget = int(float(adset.get("lifetime_budget", 0) or budget_plan.get("adset_lifetime") or 0) * 100)
        adset_budget_sharing = adset.get("is_adset_budget_sharing_enabled")
        if budget_level == "campaign":
            adset_budget_sharing = None
        elif adset_budget_sharing is None:
            adset_budget_sharing = False
        adset_targeting = dict(adset.get("targeting") or {})
        if adset.get("placements") is not None and not adset_targeting.get("placements"):
            adset_targeting["placements"] = adset.get("placements")
        promoted_object = SocialFlowClient.normalize_promoted_object(adset.get("promoted_object") or {})
        if lead_gen_form_id and destination.get("page_id") and not promoted_object.get("page_id"):
            promoted_object = {**promoted_object, "page_id": destination.get("page_id")}
        result = client.create_adset(
            campaign_id,
            adset.get("name", "Ad Set"),
            targeting_for_social(adset_targeting),
            daily_budget,
            status_plan.get("adset", adset.get("status", "PAUSED")),
            adset_optimization_goal_for_campaign(adset, campaign, lead_gen_form_id, message_destination),
            promoted_object=promoted_object,
            billing_event=adset.get("billing_event") or "IMPRESSIONS",
            bidding=SocialFlowClient.normalize_bidding_config(adset.get("bidding") or {}),
            lifetime_budget_cents=lifetime_budget,
            start_time=adset.get("start_time") or "",
            end_time=adset.get("end_time") or "",
            is_adset_budget_sharing_enabled=adset_budget_sharing,
            destination_type=adset.get("destination_type") or ad_plan.get("destination_type") or SocialFlowClient.destination_type_for_message_destination(message_destination),
            approved=approved,
        )
        adset_id = social_id_from_result(result)
        adset_ids.append(adset_id)
        steps.append({"step": "create_adset", "ok": bool(adset_id), "adset_id": adset_id, "status": status_plan.get("adset", "PAUSED"), "result": result})
        if adset_id:
            persist_campaign_execution_state(path, campaign, {"campaign_id": campaign_id, "adset_ids": [value for value in adset_ids if value]})
        if not adset_id:
            return {"ok": False, "mode": client.config.mode, "executed": True, "campaign_id": campaign_id, "failed_step": "create_adset", "steps": steps}
    target_adset_id = adset_ids[0] if adset_ids else ""
    image_hash = ad_plan.get("image_hash") or ""
    video_id = ad_plan.get("video_id") or ""
    message_destination_link = SocialFlowClient.default_message_destination_link(message_destination, destination.get("page_id", ""))
    lead_form_link = SocialFlowClient.default_lead_form_link(destination.get("page_id", "")) if lead_gen_form_id else ""
    link = ad_plan.get("landing_url") or message_destination_link or lead_form_link or destination.get("url", "")
    body_text = ad_plan.get("primary_text") or f"Conoce {campaign.get('name', 'esta oferta')}."
    headline = ad_plan.get("headline") or campaign.get("name", "Nueva oferta")
    if manual_completion and not placeholder_static:
        task = manual_creative_completion_task(campaign, ad_plan, campaign_id, adset_ids, link, body_text, headline)
        steps.append({"step": "manual_creative_completion", "ok": True, "completed_step": "adset", "task": task})
        return {
            "ok": True,
            "mode": client.config.mode,
            "executed": True,
            "campaign_id": campaign_id,
            "adset_ids": adset_ids,
            "creative_id": "",
            "ad_id": "",
            "ad_ids": [],
            "manual_completion_required": True,
            "completed_step": "adset",
            "final_status": "PAUSED",
            "status_plan": status_plan,
            "manual_creative_task": task,
            "steps": steps,
        }
    placeholder_image_path = ""
    if placeholder_static:
        ad_plan["deferred_video_url"] = ad_plan.get("deferred_video_url") or ad_plan.get("video_url") or ""
        ad_plan["video_url"] = ""
        ad_plan["final_status"] = "PAUSED"
        ad_plan["active_spend_confirmed"] = False
        if not static_creative_source_available(ad_plan):
            placeholder_image_path = ensure_placeholder_image(campaign)
            ad_plan["creative_image_path"] = placeholder_image_path
        elif ad_plan.get("creative_image_path"):
            placeholder_image_path = ad_plan.get("creative_image_path")
    reuse_prior_object_story_id = not prior_result_missing_website_url(prior_result)
    object_story_id = str(
        ad_plan.get("object_story_id")
        or (prior_meta_id(prior_result, "object_story_id", "create_page_post") if reuse_prior_object_story_id else "")
        or (prior_meta_id(prior_result, "object_story_id", "create_page_post_fallback") if reuse_prior_object_story_id else "")
        or ""
    ).strip()
    page_post_body = {}
    direct_preference = direct_publishing_preference(ad_plan)
    direct_missing = direct_publishing_missing_requirements(ad_plan, destination, client, video_id)
    should_create_native_page_post = (
        not object_story_id
        and not lead_gen_form_id
        and not direct_missing
        and direct_preference is not False
        and bool(getattr(client.config, "meta_publishing_access_token", ""))
    )
    if direct_preference is True and not object_story_id and direct_missing:
        steps.append({
            "step": "create_page_post",
            "ok": False,
            "direct_publishing_requested": True,
            "missing_requirements": direct_missing,
        })
        return {
            "ok": False,
            "mode": client.config.mode,
            "executed": True,
            "campaign_id": campaign_id,
            "adset_ids": adset_ids,
            "failed_step": "create_page_post",
            "direct_publishing_required": True,
            "missing_requirements": direct_missing,
            "steps": steps,
        }
    if should_create_native_page_post:
        object_story_id, page_post_result = create_native_page_post_for_ad(
            client,
            destination,
            ad_plan,
            link,
            body_text,
            headline,
            approved=approved,
        )
        page_post_body = social_body_from_result(page_post_result)
        steps.append({"step": "create_page_post", "ok": bool(object_story_id), "object_story_id": object_story_id, "result": page_post_result})
        if not object_story_id:
            return {"ok": False, "mode": client.config.mode, "executed": True, "campaign_id": campaign_id, "adset_ids": adset_ids, "failed_step": "create_page_post", "steps": steps}

    if ad_plan.get("creative_image_path") and not object_story_id:
        upload_result = client.upload_image(client.config.ad_account_id, ad_plan.get("creative_image_path"), approved=approved)
        try:
            body = json.loads(upload_result.get("stdout") or "{}")
            if isinstance(body, dict):
                image_hash = body.get("hash")
                images = body.get("images", {})
                if not image_hash and isinstance(images, dict) and images:
                    image_hash = next(iter(images.values())).get("hash")
        except json.JSONDecodeError:
            pass
        steps.append({"step": "upload_image", "ok": bool(image_hash), "image_hash": image_hash, "result": upload_result})
        if not image_hash:
            return {"ok": False, "mode": client.config.mode, "executed": True, "campaign_id": campaign_id, "adset_ids": adset_ids, "failed_step": "upload_image", "steps": steps}
    if ad_plan.get("video_url") and not video_id and not object_story_id:
        upload_result = client.upload_video(
            client.config.ad_account_id,
            file_url=ad_plan.get("video_url"),
            title=f"{campaign.get('name', 'New Campaign')} - Video",
            approved=approved,
        )
        try:
            body = json.loads(upload_result.get("stdout") or "{}")
            if isinstance(body, dict):
                video_id = body.get("id") or body.get("video_id") or ""
        except json.JSONDecodeError:
            pass
        steps.append({"step": "upload_video", "ok": bool(video_id), "video_id": video_id, "result": upload_result})
        if not video_id:
            return {"ok": False, "mode": client.config.mode, "executed": True, "campaign_id": campaign_id, "adset_ids": adset_ids, "failed_step": "upload_video", "steps": steps}

    direct_video_story_spec = direct_page_video_story_spec(destination, ad_plan, link, body_text, headline, page_post_body)
    creative_object_story_id = "" if direct_video_story_spec else object_story_id
    creative_object_story_spec = direct_video_story_spec or ({} if object_story_id else (ad_plan.get("object_story_spec") or {}))

    creative_result = client.create_creative(
        client.config.ad_account_id,
        f"{campaign.get('name', 'New Campaign')} - Creative",
        destination.get("page_id", ""),
        link,
        body_text,
        headline,
        image_hash,
        ad_plan.get("cta", "LEARN_MORE"),
        destination.get("instagram_actor_id", ""),
        object_story_spec=creative_object_story_spec,
        image_url=ad_plan.get("image_url") or "",
        video_url=ad_plan.get("video_url") or "",
        video_id=video_id,
        cta_link=ad_plan.get("cta_link") or "",
        object_story_id=creative_object_story_id,
        lead_gen_form_id=lead_gen_form_id,
        prefer_publishing_token=bool(direct_video_story_spec),
        approved=approved,
    )
    creative_id = social_id_from_result(creative_result)
    steps.append({"step": "create_creative", "ok": bool(creative_id), "creative_id": creative_id, "result": creative_result})
    if not creative_id and direct_video_story_spec and object_story_id and creative_blocked_by_development_mode(creative_result):
        creative_result = client.create_creative(
            client.config.ad_account_id,
            f"{campaign.get('name', 'New Campaign')} - Creative",
            destination.get("page_id", ""),
            link,
            body_text,
            headline,
            "",
            ad_plan.get("cta", "LEARN_MORE"),
            destination.get("instagram_actor_id", ""),
            object_story_spec={},
            image_url="",
            video_url="",
            video_id="",
            cta_link=ad_plan.get("cta_link") or "",
            object_story_id=object_story_id,
            lead_gen_form_id=lead_gen_form_id,
            approved=approved,
        )
        creative_id = social_id_from_result(creative_result)
        steps.append({"step": "create_creative_retry_object_story_id", "ok": bool(creative_id), "creative_id": creative_id, "result": creative_result})
    if not creative_id and not creative_object_story_id and not direct_video_story_spec and creative_blocked_by_development_mode(creative_result):
        fallback_missing = direct_publishing_missing_requirements(ad_plan, destination, client, video_id)
        if not fallback_missing:
            object_story_id, page_post_result = create_native_page_post_for_ad(
                client,
                destination,
                ad_plan,
                link,
                body_text,
                headline,
                approved=approved,
            )
            page_post_body = social_body_from_result(page_post_result)
            steps.append({"step": "create_page_post_fallback", "ok": bool(object_story_id), "object_story_id": object_story_id, "result": page_post_result})
            if object_story_id:
                retry_video_story_spec = direct_page_video_story_spec(destination, ad_plan, link, body_text, headline, page_post_body)
                creative_result = client.create_creative(
                    client.config.ad_account_id,
                    f"{campaign.get('name', 'New Campaign')} - Creative",
                    destination.get("page_id", ""),
                    link,
                    body_text,
                    headline,
                    "",
                    ad_plan.get("cta", "LEARN_MORE"),
                    destination.get("instagram_actor_id", ""),
                    object_story_spec=retry_video_story_spec,
                    image_url="",
                    video_url="",
                    video_id="",
                    cta_link=ad_plan.get("cta_link") or "",
                    object_story_id="" if retry_video_story_spec else object_story_id,
                    lead_gen_form_id=lead_gen_form_id,
                    prefer_publishing_token=bool(retry_video_story_spec),
                    approved=approved,
                )
                creative_id = social_id_from_result(creative_result)
                steps.append({"step": "create_creative_retry_object_story_id", "ok": bool(creative_id), "creative_id": creative_id, "result": creative_result})
        if not creative_id:
            return {
                "ok": False,
                "mode": client.config.mode,
                "executed": True,
                "campaign_id": campaign_id,
                "adset_ids": adset_ids,
                "failed_step": "create_creative",
                "recovery": {
                    "direct_publishing_required": True,
                    "missing_requirements": fallback_missing,
                    "message": "Meta blocked direct creative creation because the ads app is in development mode. Connect Publicación directa or provide an original image path/URL so the backend can create a native unpublished Page post first.",
                },
                "steps": steps,
            }
    if not creative_id:
        return {"ok": False, "mode": client.config.mode, "executed": True, "campaign_id": campaign_id, "adset_ids": adset_ids, "failed_step": "create_creative", "steps": steps}

    ad_ids = []
    names = placeholder_ad_names(ad_plan)
    create_count = max(placeholder_ad_count(ad_plan, default=len(names) or 1), len(names)) if placeholder_static else 1
    for index in range(create_count):
        ad_result = client.create_ad(
            target_adset_id,
            placeholder_ad_name(campaign, ad_plan, index, create_count),
            creative_id,
            "PAUSED" if placeholder_static else status_plan.get("ad", final_status),
            website_url=link,
            approved=approved,
        )
        ad_id = social_id_from_result(ad_result)
        ad_ids.append(ad_id)
        steps.append({"step": "create_ad", "ok": bool(ad_id), "ad_id": ad_id, "final_status": "PAUSED" if placeholder_static else status_plan.get("ad", final_status), "result": ad_result})
        if not ad_id:
            return {"ok": False, "mode": client.config.mode, "executed": True, "campaign_id": campaign_id, "adset_ids": adset_ids, "creative_id": creative_id, "ad_ids": [value for value in ad_ids if value], "failed_step": "create_ad", "steps": steps}
    ad_id = ad_ids[0] if ad_ids else ""
    final = {"ok": bool(ad_id), "mode": client.config.mode, "executed": True, "campaign_id": campaign_id, "adset_ids": adset_ids, "creative_id": creative_id, "ad_id": ad_id, "ad_ids": ad_ids, "final_status": "PAUSED" if placeholder_static else status_plan.get("ad", final_status), "status_plan": status_plan, "steps": steps}
    if placeholder_static:
        task = manual_creative_completion_task(campaign, ad_plan, campaign_id, adset_ids, link, body_text, headline, placeholder_ad_ids=ad_ids, placeholder_image_path=placeholder_image_path)
        steps.append({"step": "manual_creative_completion", "ok": True, "completed_step": "paused_placeholder_ads", "task": task})
        final.update({
            "manual_completion_required": True,
            "placeholder_ads_created": True,
            "manual_creative_task": task,
        })
    if final["ok"]:
        mark_asset_files_retained(
            [ad_plan.get("creative_image_path")],
            reason="placeholder_ads_created" if placeholder_static else "campaign_ad_created",
            meta={"campaign_id": campaign_id, "creative_id": creative_id, "ad_id": ad_id, "ad_ids": ad_ids, "final_status": final["final_status"]},
        )
    return final


def execute_pending(item, client):
    if client.config.license_required_for_live:
        status = license_status(client.config)
        if not status.get("valid"):
            return {"ok": False, "blocked": True, "error": f"License unlock required before live approval execution: {status.get('detail')}"}
    command = command_for_pending(item)
    if not command:
        return {"ok": False, "error": "No executable command for pending item"}
    if command[0] == "set_budget":
        result = client.set_budget(command[1], command[2], command[3], approved=True)
    elif command[0] == "resume":
        result = client.resume(command[1], command[2], approved=True)
    elif command[0] == "pause":
        result = client.pause(command[1], command[2], approved=True)
    elif command[0] == "create_campaign":
        result = execute_campaign_creation(command[1], client, approved=True, prior_result=item.get("result"))
    elif command[0] == "create_lead_form":
        result = execute_lead_form_creation(command[1], client, approved=True)
    elif command[0] == "creative_upload":
        result = execute_upload_payload(command[1], approved=True)
    else:
        result = {"ok": False, "error": "Unsupported command"}
    return result


def execution_succeeded(result):
    if not isinstance(result, dict) or result.get("blocked"):
        return False
    if "ok" in result:
        return bool(result.get("ok")) and result.get("executed", True) is not False
    return bool(result.get("executed")) and result.get("returncode") in {0, None}


def approve(approval_id, all_items=False):
    config = load_config()
    client = SocialFlowClient(config)
    pending = read_json(PENDING_FILE, [])
    attempted = []
    remaining = []
    for item in pending:
        should_apply = all_items or item.get("id") == approval_id
        if not should_apply:
            remaining.append(item)
            continue
        result = execute_pending(item, client)
        item["result"] = result
        if execution_succeeded(result):
            item["status"] = "approved"
            item["approved_at"] = now_iso()
            log_action(item.get("type", "approval"), item, "approved")
        else:
            item["status"] = "pending"
            item["last_attempt_at"] = now_iso()
            remaining.append(item)
            log_action(item.get("type", "approval"), item, "failed")
        attempted.append(item)
    write_json(PENDING_FILE, remaining)
    return attempted


def reject(approval_id, reason=""):
    pending = read_json(PENDING_FILE, [])
    rejected = []
    remaining = []
    for item in pending:
        if item.get("id") != approval_id:
            remaining.append(item)
            continue
        item["status"] = "rejected"
        item["rejected_at"] = now_iso()
        item["rejection_reason"] = reason or "Rejected by buyer"
        rejected.append(item)
        log_action(item.get("type", "approval"), item, "rejected")
    write_json(PENDING_FILE, remaining)
    return rejected


def pull_live_metrics(metrics, client):
    result = client.insights("last_7d", "campaign")
    if result.get("data"):
        normalized = normalize_social_insights(result.get("data"), metrics)
        if normalized:
            metrics = normalized
            save_metrics(metrics)
        log_action("live_insights_pull", {"result": result, "normalized_campaigns": len(metrics.get("campaigns", []))}, "completed")
    else:
        config = load_config()
        if config.meta_access_token and config.ad_account_id:
            snapshot = collect_meta_snapshot(
                config.ad_account_id,
                config.meta_access_token,
                config.meta_graph_api_version or "v24.0",
                date_preset="last_30d",
            )
            campaigns = aggregate_meta_campaigns(snapshot)
            if campaigns:
                metrics = {
                    "timestamp": now_iso(), "source": "meta_graph", "source_label": "Meta Ads real data",
                    "account_id": config.ad_account_id, "date_preset": "last_30d", "campaigns": campaigns,
                    "data_quality": snapshot.get("data_quality"),
                }
                save_metrics(metrics)
                save_meta_snapshot(snapshot)
                log_action("live_insights_pull", {"source": "meta_graph_fallback", "normalized_campaigns": len(campaigns), "data_quality": snapshot.get("data_quality")}, "completed")
                return metrics
        log_action("live_insights_pull", {"result": result}, "failed" if result.get("returncode") not in {0, None} else "no_json")
    return metrics


def nested_number(payload, keys, default=0):
    if not isinstance(payload, dict):
        return default
    for key in keys:
        if key in payload and payload[key] not in {None, ""}:
            try:
                return float(payload[key])
            except (TypeError, ValueError):
                pass
    return default


def action_value(row, action_names):
    values = row.get("actions") or row.get("conversions") or []
    if not isinstance(values, list):
        return 0
    wanted = {str(name).lower() for name in action_names}
    total = 0
    for item in values:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("action_type") or item.get("type") or "").lower()
        if action_type in wanted:
            try:
                total += float(item.get("value", 0))
            except (TypeError, ValueError):
                pass
    return total


def normalize_social_insights(data, previous_metrics):
    rows = data.get("data") if isinstance(data, dict) else data
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("campaigns") or []
    if not isinstance(rows, list) or not rows:
        return None

    previous_by_id = {str(c.get("id")): c for c in previous_metrics.get("campaigns", [])}
    campaigns = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        campaign_id = str(row.get("campaign_id") or row.get("id") or row.get("campaignId") or "").strip()
        if not campaign_id:
            continue
        prev = previous_by_id.get(campaign_id, {})
        spend = nested_number(row, ["spend", "amount_spent"])
        impressions = int(nested_number(row, ["impressions"]))
        clicks = int(nested_number(row, ["clicks", "inline_link_clicks"]))
        conversions = int(nested_number(row, ["conversions", "purchases", "results"]) or action_value(row, ["purchase", "lead", "complete_registration", "omni_purchase"]))
        revenue = nested_number(row, ["revenue", "purchase_roas_value", "conversion_value", "value"]) or float(prev.get("revenue", 0) or 0)
        campaign = {
            **prev,
            "id": campaign_id,
            "name": row.get("campaign_name") or row.get("name") or prev.get("name") or campaign_id,
            "status": str(row.get("status") or prev.get("status") or "active").lower(),
            "daily_budget": float(row.get("daily_budget") or prev.get("daily_budget") or 100),
            "spend": spend,
            "impressions": impressions,
            "clicks": clicks,
            "conversions": conversions,
            "revenue": revenue,
            "frequency": nested_number(row, ["frequency"], prev.get("frequency", 1.0)),
            "target_type": prev.get("target_type", "campaign"),
            "target_id": prev.get("target_id", campaign_id),
            "updated_at": now_iso(),
        }
        campaigns.append(enrich_campaign(campaign))
    if not campaigns:
        return None
    return {
        "timestamp": now_iso(),
        "source": "meta_graph",
        "source_label": "Meta Ads real data",
        "connector": "graph_api",
        "campaigns": campaigns,
        "summary": build_summary(campaigns),
    }


def build_action_summary(recommendations, auto_paused, proposed_pauses, fatigue, creative_refreshes=None):
    creative_refreshes = creative_refreshes or []
    proposed_pauses = proposed_pauses or []
    approval_budget = [rec for rec in recommendations if rec.get("requires_approval")]
    next_budget = [
        rec
        for rec in recommendations
        if not rec.get("requires_approval") and abs(float(rec.get("change_pct", 0) or 0)) >= 1
    ]
    already_done = []
    waiting_for_approval = []
    recommended_next = []
    watching = []

    if auto_paused:
        already_done.append({
            "type": "auto_pause",
            "label": f"Paused {len(auto_paused)} clear bleeder(s) under autopilot rules.",
            "items": auto_paused[:5],
        })
    if creative_refreshes:
        already_done.append({
            "type": "creative_refresh",
            "label": f"Prepared {len(creative_refreshes)} creative refresh draft(s).",
            "items": creative_refreshes[:5],
        })
    if proposed_pauses:
        waiting_for_approval.append({
            "type": "pause_campaign",
            "label": f"{len(proposed_pauses)} pause decision(s) need buyer approval.",
            "items": proposed_pauses[:5],
        })
    if approval_budget:
        waiting_for_approval.append({
            "type": "budget_change",
            "label": f"{len(approval_budget)} budget move(s) need buyer approval.",
            "items": approval_budget[:5],
        })
    if next_budget:
        recommended_next.append({
            "type": "budget_change",
            "label": f"{len(next_budget)} smaller budget move(s) are worth reviewing.",
            "items": next_budget[:5],
        })
    if fatigue:
        recommended_next.append({
            "type": "creative_refresh",
            "label": f"{len(fatigue)} fatigue signal(s) should feed the next creative test.",
            "items": fatigue[:5],
        })
    if not already_done and not waiting_for_approval and not recommended_next:
        watching.append({
            "type": "monitoring",
            "label": "No strong action signal yet. Keep watching pacing, CPA, ROAS, CTR, and frequency.",
        })
    return {
        "already_done": already_done,
        "waiting_for_approval": waiting_for_approval,
        "recommended_next": recommended_next,
        "watching": watching,
    }


def is_real_meta_metrics(metrics):
    return str((metrics or {}).get("source") or "").strip().lower() == "meta_graph"


def recent_daily_reports(limit=6):
    reports = []
    if not OUTPUT_DIR.exists():
        return reports
    for path in sorted(OUTPUT_DIR.glob("daily_brief_*.json"), reverse=True):
        payload = read_json(path, {})
        brief = payload.get("brief", {}) if isinstance(payload, dict) else {}
        snapshot = brief.get("metrics_snapshot") if isinstance(brief, dict) else {}
        summary = (snapshot or {}).get("summary") or brief.get("summary") or {}
        if not isinstance(summary, dict) or not summary:
            continue
        reports.append({
            "path": str(path),
            "generated_at": brief.get("generated_at", ""),
            "source": (snapshot or {}).get("source", ""),
            "summary": summary,
        })
        if len(reports) >= limit:
            break
    return reports


def metric_number(summary, key):
    try:
        return float((summary or {}).get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def format_metric_value(key, value):
    if key in {"total_spend", "total_revenue", "overall_cpa", "active_budget"}:
        return f"${money(value):,.2f}"
    if key == "overall_roas":
        return f"{float(value or 0):.2f}x"
    if key == "overall_ctr":
        return f"{float(value or 0):.2f}%"
    return f"{int(float(value or 0)):,}"


def metric_delta_sentence(summary, previous, key, label):
    current = metric_number(summary, key)
    old = metric_number(previous, key)
    if old <= 0:
        return ""
    delta = pct_change(current, old)
    if abs(delta) < 5:
        return f"{label} se mantuvo parecido: {format_metric_value(key, current)}."
    direction = "subió" if delta > 0 else "bajó"
    return f"{label} {direction} {abs(delta):.0f}%: de {format_metric_value(key, old)} a {format_metric_value(key, current)}."


def build_trend_context(metrics, recent_reports=None):
    summary = metrics.get("summary", {})
    reports = recent_reports if recent_reports is not None else recent_daily_reports()
    previous = (reports[0].get("summary") if reports else {}) or {}
    observations = []
    if not is_real_meta_metrics(metrics):
        observations.append("Aún no tengo una lectura real de Meta para comparar fluctuaciones.")
        return {"days_compared": 0, "previous_summary": previous, "observations": observations}
    if not previous:
        observations.append("Hoy queda como primer punto de comparación; desde mañana podré decirte qué cambió.")
        return {"days_compared": 1, "previous_summary": previous, "observations": observations}
    roas_sentence = metric_delta_sentence(summary, previous, "overall_roas", "El retorno")
    cpa_sentence = metric_delta_sentence(summary, previous, "overall_cpa", "El costo por compra/resultado")
    spend_sentence = metric_delta_sentence(summary, previous, "total_spend", "El gasto")
    conversions_sentence = metric_delta_sentence(summary, previous, "total_conversions", "Las conversiones")
    for sentence in (roas_sentence, cpa_sentence, spend_sentence, conversions_sentence):
        if sentence:
            observations.append(sentence)
    if not observations:
        observations.append("Los números se movieron poco frente a la lectura anterior; hoy conviene mirar señales de fatiga y presupuesto antes de tocar algo.")
    roas_current = metric_number(summary, "overall_roas")
    roas_previous = metric_number(previous, "overall_roas")
    cpa_current = metric_number(summary, "overall_cpa")
    cpa_previous = metric_number(previous, "overall_cpa")
    if roas_previous and cpa_previous:
        if roas_current < roas_previous and cpa_current > cpa_previous:
            observations.append("La eficiencia viene más débil: conviene reducir desperdicio o refrescar creativos antes de subir presupuesto.")
        elif roas_current > roas_previous and cpa_current < cpa_previous:
            observations.append("La eficiencia viene mejorando: las campañas sanas se pueden cuidar o escalar con calma.")
    return {"days_compared": min(len(reports) + 1, 7), "previous_summary": previous, "observations": observations[:4]}


def top_campaign_line(prefix, campaign, metric_key, metric_label):
    if not campaign:
        return ""
    return f"{prefix}: {campaign.get('name')} ({format_metric_value(metric_key, campaign.get(metric_key, 0))} {metric_label})."


def build_manager_message(metrics, winners, losers, fatigue, proposed_pauses, action_summary, trend_context, experiment_reviews=None):
    if not is_real_meta_metrics(metrics):
        return (
            "Buenos días. Todavía no tengo datos reales de Meta suficientes para hacer una lectura responsable.\n\n"
            "Lo importante hoy es esto:\n"
            "Primero necesitamos actualizar la conexión con Meta.\n"
            "Cuando entren datos reales, compararé gasto, retorno, costo por resultado y señales de fatiga.\n"
            "Puedo ayudarte a terminar esa conexión desde Configuración.\n\n"
            "¿Tienes alguna pregunta?"
        )

    lines = ["Buenos días. Ya revisé tu cuenta.", "", "Lo importante hoy es esto:"]
    decisions = []
    experiment_reviews = experiment_reviews or {}
    experiments = experiment_reviews.get("experiments") or []
    decision_ready = next((item for item in experiments if item.get("status") == "decision_ready"), None)
    watching_experiment = next((item for item in experiments if item.get("next_review_at")), None)
    if decision_ready:
        decisions.append(f"El test {decision_ready.get('name')} ya tiene una decisión para revisar: {decision_ready.get('summary')}")
    elif watching_experiment:
        decisions.append(
            f"El test {watching_experiment.get('name')} sigue en observación. "
            f"Próxima revisión: {local_review_time(watching_experiment.get('next_review_at'))}."
        )
    if proposed_pauses:
        first = proposed_pauses[0]
        decisions.append(f"{first.get('name', 'Una campaña')} está consumiendo sin suficiente resultado; puedo dejar la pausa lista para aprobación.")
    elif losers:
        decisions.append(f"{losers[0].get('name')} está consumiendo sin suficiente resultado.")
    if winners:
        decisions.append(f"{winners[0].get('name')} todavía se ve sana.")
    if fatigue:
        decisions.append(f"Hay una señal de fatiga en creativos: {fatigue[0].get('campaign_name')}.")
    waiting = action_summary.get("waiting_for_approval") or []
    next_moves = action_summary.get("recommended_next") or []
    if waiting:
        decisions.append("Hay cambios preparados que necesitan tu aprobación antes de tocar dinero real.")
    elif next_moves:
        decisions.append(next_moves[0].get("label", "Tengo un siguiente movimiento recomendado para revisar."))
    if not decisions:
        decisions.append("No veo una señal fuerte para tocar presupuesto hoy.")
        decisions.append("Conviene observar un poco más antes de hacer cambios grandes.")
    lines.extend(decisions[:4])

    observations = [item for item in (trend_context or {}).get("observations", []) if item]
    if observations:
        lines.extend(["", "Contexto de los últimos días:"])
        lines.extend(observations[:3])

    lines.extend(["", "Puedo preparar los cambios para aprobación.", "", "¿Tienes alguna pregunta?"])
    return "\n".join(lines)


def metrics_snapshot(metrics):
    return {
        "source": metrics.get("source", ""),
        "source_label": metrics.get("source_label", ""),
        "timestamp": metrics.get("timestamp", ""),
        "summary": metrics.get("summary", {}),
        "campaigns": [
            {
                "id": campaign.get("id"),
                "name": campaign.get("name"),
                "status": campaign.get("status"),
                "spend": campaign.get("spend", 0),
                "revenue": campaign.get("revenue", 0),
                "conversions": campaign.get("conversions", 0),
                "roas": campaign.get("roas", 0),
                "cpa": campaign.get("cpa", 0),
                "ctr": campaign.get("ctr", 0),
                "frequency": campaign.get("frequency", 0),
                "health": campaign.get("health", ""),
            }
            for campaign in metrics.get("campaigns", [])[:50]
        ],
    }


def build_brief(metrics, recommendations, auto_paused, fatigue, proposed_pauses=None, creative_refreshes=None, experiment_reviews=None, optimization=None):
    summary = metrics.get("summary", {})
    campaigns = metrics.get("campaigns", [])
    proposed_pauses = proposed_pauses or []
    experiment_reviews = experiment_reviews or {"active_count": 0, "decision_ready_count": 0, "experiments": []}
    optimization = optimization or {}
    winners = sorted([c for c in campaigns if c.get("health") == "winning"], key=lambda c: c.get("roas", 0), reverse=True)
    losers = sorted([c for c in campaigns if c.get("health") == "losing"], key=lambda c: c.get("roas", 0))
    approval_count = len(read_json(PENDING_FILE, []))
    action_summary = build_action_summary(recommendations, auto_paused, proposed_pauses, fatigue, creative_refreshes)
    trend_context = build_trend_context(metrics)
    message = build_manager_message(metrics, winners, losers, fatigue, proposed_pauses, action_summary, trend_context, experiment_reviews)
    reconciliation = optimization.get("reconciliation") or {}
    unlock = optimization.get("unlock") or {}
    optimization_notes = []
    if optimization.get("mode") == "shadow":
        optimization_notes.append(
            f"El optimizador sigue en modo observación: {unlock.get('elapsed_days', 0)}/{unlock.get('minimum_days', 14)} días y "
            f"{unlock.get('matured_outcomes', 0)}/{unlock.get('minimum_matured_outcomes', 10)} decisiones maduras. No tocará presupuesto solo."
        )
    if reconciliation.get("status") == "investigate":
        optimization_notes.append(
            f"Shopify y Meta no coinciden todavía (ventas {reconciliation.get('conversion_gap_pct')}%, ingresos {reconciliation.get('revenue_gap_pct')}%); "
            "conviene revisar atribución, Pixel/CAPI y retrasos antes de decidir."
        )
    elif reconciliation.get("status") == "aligned":
        optimization_notes.append("Shopify está conectado como verdad del negocio y la conciliación no muestra una diferencia material.")
    if optimization.get("anomalies"):
        labels = ", ".join(item.get("label", item.get("metric", "")) for item in optimization["anomalies"][:3])
        optimization_notes.append(f"Detecté un cambio fuera de lo normal en: {labels}. Lo trato como diagnóstico, no como permiso para actuar.")
    if optimization_notes:
        message += "\n\nControl de optimización:\n" + "\n".join(optimization_notes)
    lines = [
        f"Gasto: {format_metric_value('total_spend', summary.get('total_spend', 0))}",
        f"Ingresos: {format_metric_value('total_revenue', summary.get('total_revenue', 0))}",
        f"Retorno: {format_metric_value('overall_roas', summary.get('overall_roas', 0))}",
        f"Costo por resultado: {format_metric_value('overall_cpa', summary.get('overall_cpa', 0))}",
        f"Campañas activas: {summary.get('active_campaigns', 0)}",
        f"Pausas automáticas: {len(auto_paused)}",
        f"Pausas por aprobar: {len(proposed_pauses)}",
        f"Señales de fatiga: {len(fatigue)}",
        f"Decisiones pendientes: {approval_count}",
        f"Tests creativos en seguimiento: {experiment_reviews.get('active_count', 0)}",
    ]
    if optimization.get("mode"):
        lines.append(f"Modo del optimizador: {optimization.get('mode')}")
    if reconciliation.get("status"):
        lines.append(f"Conciliación Shopify/Meta: {reconciliation.get('status')}")
    if optimization.get("anomalies"):
        lines.append(f"Anomalías para investigar: {len(optimization.get('anomalies', []))}")
    if experiment_reviews.get("decision_ready_count"):
        lines.append(f"Tests con decisión lista: {experiment_reviews.get('decision_ready_count')}")
    elif experiment_reviews.get("next_review_at"):
        lines.append(f"Próxima revisión de creativos: {local_review_time(experiment_reviews.get('next_review_at'))}")
    if winners:
        lines.append(f"Campaña más sana: {winners[0]['name']} ({winners[0]['roas']:.2f}x retorno)")
    if losers:
        lines.append(f"Campaña a revisar: {losers[0]['name']} ({losers[0]['roas']:.2f}x retorno)")
    if action_summary["already_done"]:
        lines.append(f"Hecho: {action_summary['already_done'][0]['label']}")
    if action_summary["waiting_for_approval"]:
        lines.append(f"Esperando aprobación: {len(action_summary['waiting_for_approval'])} grupo(s) de acciones")
    if action_summary["recommended_next"]:
        lines.append(f"Siguiente movimiento: {action_summary['recommended_next'][0]['label']}")
    if winners:
        winner_loser_answer = f"La más sana es {winners[0]['name']}."
        if losers:
            winner_loser_answer += f" La que necesita revisión es {losers[0]['name']}."
    elif losers:
        winner_loser_answer = f"La que necesita revisión es {losers[0]['name']}."
    else:
        winner_loser_answer = "Todavía no hay ganadora o perdedora clara."
    return {
        "generated_at": now_iso(),
        "summary": summary,
        "five_questions": {
            "am_i_on_track": lines[0],
            "whats_running": f"{summary.get('active_campaigns', 0)} campañas activas",
            "hows_performance": f"{summary.get('overall_roas', 0):.2f}x retorno, {format_metric_value('overall_cpa', summary.get('overall_cpa', 0))} costo por resultado",
            "winning_losing": winner_loser_answer,
            "fatigue": f"{len(fatigue)} señal(es) de fatiga",
        },
        "message": message,
        "technical_lines": lines,
        "trend_context": trend_context,
        "metrics_snapshot": metrics_snapshot(metrics),
        "winners": winners[:5],
        "losers": losers[:5],
        "auto_paused": auto_paused,
        "proposed_pauses": proposed_pauses,
        "fatigue": fatigue,
        "recommendations": recommendations,
        "action_summary": action_summary,
        "experiment_reviews": experiment_reviews,
        "optimization": optimization,
    }


def run_daily():
    config = load_config()
    client = SocialFlowClient(config)
    if getattr(config, "shopify_shop_domain", "") and getattr(config, "shopify_admin_token", ""):
        shopify_result = sync_shopify(config.shopify_shop_domain, config.shopify_admin_token, getattr(config, "shopify_api_version", "2026-04"))
        log_action(
            "shopify_sync",
            {key: value for key, value in shopify_result.items() if key != "outcomes"},
            "completed" if shopify_result.get("ok") else "blocked",
        )
    metrics = load_metrics()
    if config.ad_account_id or config.meta_access_token:
        metrics = pull_live_metrics(metrics, client)

    lag_calibration = calibrate_conversion_lag()

    recommendations = calculate_recommendations(metrics.get("campaigns", []))
    recommendations_by_campaign = {str(item.get("campaign_id")): item for item in recommendations}
    auto_paused = []
    proposed_pauses = []
    if config.auto_pause_enabled:
        for campaign in metrics.get("campaigns", []):
            recommendation = recommendations_by_campaign.get(str(campaign.get("id") or campaign.get("campaign_id")), {})
            should_pause = str(campaign.get("status") or "").lower() == "active" and recommendation.get("decision") == "pause_candidate"
            if not should_pause:
                continue
            item = {
                "approval_id": f"approval_pause_{campaign.get('id')}",
                "campaign_id": campaign.get("id"),
                "target_type": campaign.get("target_type", "adset"),
                "target_id": campaign.get("target_id", campaign.get("id")),
                "name": campaign.get("name"),
                "spend": campaign.get("spend", 0),
                "reason": recommendation.get("reason") or "mature evidence requires a pause review",
                "evidence_gate": recommendation.get("evidence_gate"),
                "shadow_mode": recommendation.get("shadow_mode", True),
            }
            may_execute = (
                config.autonomy_mode == "autopilot"
                and config.live
                and config.live_actions_enabled
                and float(campaign.get("spend", 0) or 0) <= config.auto_pause_max_spend
                and recommendation.get("mutation_allowed")
            )
            if may_execute and config.license_required_for_live and not license_status(config).get("valid"):
                may_execute = False
                item["guardrail_reason"] = "license_required_for_live"
            if not may_execute:
                item.setdefault("guardrail_reason", "shadow_mode" if recommendation.get("shadow_mode", True) else "supervised_or_outside_autopilot_rules")
                if recommendation.get("shadow_mode", True):
                    proposed_pauses.append(item)
                    log_action("shadow_pause_proposal", item, "observing")
                elif add_pending("pause_campaign", item):
                    proposed_pauses.append(item)
                continue
            result = client.pause(item["target_type"], item["target_id"])
            item["result"] = result
            if result.get("executed") and result.get("returncode") == 0:
                campaign["status"] = "paused"
                record_optimization_action(campaign.get("id") or campaign.get("campaign_id"))
                auto_paused.append(item)
                log_action("auto_pause", item, "completed")
            else:
                log_action("auto_pause", item, "blocked")
        if auto_paused:
            save_metrics(metrics)

    fatigue = fatigue_items(metrics.get("campaigns", []))
    append_fatigue_log(fatigue)

    creative_refreshes = []
    if config.creative_refresh_enabled and config.creative_auto_generate_on_daily:
        for campaign in campaigns_needing_refresh(metrics.get("campaigns", [])):
            plan, manifest_path = generate_creative_refresh(campaign, generate_images=config.creative_live)
            creative_refreshes.append({
                "id": plan["id"],
                "campaign": plan["campaign"],
                "manifest_path": str(manifest_path),
                "social_publishing": plan.get("social_publishing", {}),
            })
        if creative_refreshes:
            log_action("creative_refresh", {"items": creative_refreshes}, "generated")

    for rec in recommendations:
        if rec.get("requires_approval") and not rec.get("shadow_mode") and rec.get("action") in {"increase_budget", "decrease_budget"}:
            rec["approval_id"] = f"approval_budget_{rec['campaign_id']}"
            add_pending("budget_change", rec)

    decision_memory = record_daily_decision_memory(
        metrics,
        recommendations,
        fatigue,
        proposed_pauses=proposed_pauses,
        auto_paused=auto_paused,
        creative_refreshes=creative_refreshes,
    )
    record_performance_snapshot(metrics)
    shadow = record_shadow_outcomes(metrics, recommendations)
    optimization = {
        "mode": shadow.get("state", {}).get("mode", "shadow"),
        "unlock": shadow.get("unlock", {}),
        "reconciliation": reconcile_business_outcomes(metrics),
        "anomalies": anomaly_diagnostics(metrics),
        "funnel": funnel_diagnostics(),
        "data_quality": metrics.get("data_quality", {}),
        "conversion_lag_calibration": lag_calibration,
        "recent_shadow_outcomes": shadow.get("recent", [])[:5],
    }
    experiment_reviews = experiment_review_payload(metrics)
    brief = build_brief(metrics, recommendations, auto_paused, fatigue, proposed_pauses, creative_refreshes, experiment_reviews, optimization)
    brief["creative_refreshes"] = creative_refreshes
    brief["decision_memory"] = {
        "recent_decisions": decision_memory.get("decisions", [])[:6],
        "learning_log": decision_memory.get("learning_log", [])[:6],
    }
    report = {"config": config_snapshot(config), "brief": brief}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / f"daily_brief_{datetime.now().strftime('%Y-%m-%d')}.json"
    write_json(report_path, report)
    notification = send_notification(config, "Admira IA - Resumen diario", brief["message"])
    log_action("daily_agent_run", {"report_path": str(report_path), "notification": notification}, "completed")
    return report_path, report


def list_pending():
    return read_json(PENDING_FILE, [])


def main():
    parser = argparse.ArgumentParser(description="Admira IA daily runner")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("daily", help="Run the daily agent loop")
    sub.add_parser("pending", help="List pending approvals")
    approve_parser = sub.add_parser("approve", help="Approve and execute one pending item")
    approve_parser.add_argument("approval_id")
    reject_parser = sub.add_parser("reject", help="Reject one pending item")
    reject_parser.add_argument("approval_id")
    sub.add_parser("approve-all", help="Approve and execute all pending items")
    sub.add_parser("status", help="Show agent configuration and Meta Graph status")
    refresh_parser = sub.add_parser("creative-refresh", help="Generate creative refresh drafts for matching campaigns")
    refresh_parser.add_argument("--campaign-id", default="", help="Only refresh one campaign")
    refresh_parser.add_argument("--all", action="store_true", help="Generate drafts for all campaigns")
    upload_parser = sub.add_parser("stage-upload", help="Build a Meta upload payload from a creative manifest")
    upload_parser.add_argument("manifest", help="Creative manifest path or refresh id")
    upload_parser.add_argument("--variant-id", default="v1")
    upload_parser.add_argument("--ratios", default="1:1", help="Comma-separated aspect ratios")
    execute_upload_parser = sub.add_parser("execute-upload", help="Execute or dry-run an upload payload")
    execute_upload_parser.add_argument("payload_path")
    args = parser.parse_args()

    if args.command == "daily":
        path, report = run_daily()
        print(json.dumps({"report_path": str(path), "brief": report["brief"]["message"]}, indent=2))
        return 0
    if args.command == "pending":
        print(json.dumps(list_pending(), indent=2))
        return 0
    if args.command == "approve":
        print(json.dumps(approve(args.approval_id), indent=2))
        return 0
    if args.command == "reject":
        print(json.dumps(reject(args.approval_id), indent=2))
        return 0
    if args.command == "approve-all":
        print(json.dumps(approve(None, all_items=True), indent=2))
        return 0
    if args.command == "status":
        config = load_config()
        client = SocialFlowClient(config)
        print(json.dumps({"config": config_snapshot(config), "setup": build_setup_status(), "auth": client.auth_status(), "marketing": client.marketing_status()}, indent=2))
        return 0
    if args.command == "creative-refresh":
        metrics = load_metrics()
        campaigns = metrics.get("campaigns", [])
        if args.campaign_id:
            campaigns = [campaign for campaign in campaigns if campaign.get("id") == args.campaign_id]
        elif args.all:
            campaigns = campaigns
        else:
            campaigns = campaigns_needing_refresh(campaigns)
        config = load_config()
        results = []
        for campaign in campaigns:
            plan, manifest_path = generate_creative_refresh(campaign, generate_images=config.creative_live)
            results.append({"id": plan["id"], "campaign": plan["campaign"], "manifest_path": str(manifest_path)})
        print(json.dumps({"generated": results, "recent": recent_creative_refreshes()}, indent=2))
        return 0
    if args.command == "stage-upload":
        ratios = [item.strip() for item in args.ratios.split(",") if item.strip()]
        payload, payload_path, approval = stage_upload(args.manifest, args.variant_id, ratios)
        print(json.dumps({"payload_path": str(payload_path), "status": payload["status"], "missing_requirements": payload["missing_requirements"], "approval": approval, "recent": recent_uploads()}, indent=2))
        return 0
    if args.command == "execute-upload":
        print(json.dumps(execute_upload_payload(args.payload_path), indent=2))
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
