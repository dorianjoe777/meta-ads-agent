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
from meta_action_metrics import (
    PURCHASE_VALUE_ACTIONS,
    canonical_funnel_values,
    conversion_result_value,
    deduplicated_alias_value,
)
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
    country_name_for_code,
    detailed_targeting_items,
    manual_creative_completion_enabled,
    normalize_age_bounds,
    normalize_budget_plan,
    normalize_location_codes,
    normalize_gender_values,
    normalize_status_plan,
    placeholder_ad_count,
    placeholder_ad_names,
    placeholder_static_ad_enabled,
    validate_detailed_targeting_ids,
    validate_meta_targeting_selection,
)
from social_flow_client import SocialFlowClient, config_snapshot, send_notification


DATA_DIR = ROOT_DIR / "dashboard" / "data"
OUTPUT_DIR = ROOT_DIR / "output"
AD_CONFIG_FILE = ROOT_DIR / "ad-config.json"
METRICS_FILE = DATA_DIR / "metrics.json"
ACTIONS_FILE = DATA_DIR / "actions.json"
PENDING_FILE = DATA_DIR / "pending_approvals.json"
ORGANIC_CONTENT_POSTS_FILE = DATA_DIR / "organic_content_posts.json"
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
            "requires_approval": decision.get("action") != "observe" and not decision.get("shadow_mode", True),
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
    if item.get("type") == "delete_campaign":
        return ["delete", payload.get("target_type", "campaign"), payload.get("target_id", payload.get("campaign_id"))]
    if item.get("type") == "create_campaign":
        return ["create_campaign", payload.get("path")]
    if item.get("type") == "create_lead_form":
        return ["create_lead_form", payload.get("path")]
    if item.get("type") == "creative_upload":
        return ["creative_upload", payload.get("payload_path")]
    if item.get("type") == "publish_social_post":
        return ["publish_social_post", payload]
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


def image_hash_from_result(result):
    """Extract Meta's ad-image hash from either supported response shape."""
    body = social_body_from_result(result)
    image_hash = str(body.get("hash") or "").strip()
    images = body.get("images") if isinstance(body.get("images"), dict) else {}
    if not image_hash and images:
        first = next(iter(images.values()), {})
        if isinstance(first, dict):
            image_hash = str(first.get("hash") or "").strip()
    return image_hash


def published_social_post_for_approval(approval_id):
    ledger = read_json(ORGANIC_CONTENT_POSTS_FILE, {"items": []})
    items = ledger.get("items", []) if isinstance(ledger, dict) else []
    return next(
        (
            item
            for item in items
            if isinstance(item, dict)
            and item.get("approval_id") == approval_id
            and item.get("status") == "published"
            and item.get("post_id")
        ),
        None,
    )


def record_social_post_publication(payload, result):
    ledger = read_json(ORGANIC_CONTENT_POSTS_FILE, {"items": [], "updated_at": ""})
    if not isinstance(ledger, dict):
        ledger = {"items": [], "updated_at": ""}
    items = [item for item in ledger.get("items", []) if isinstance(item, dict)]
    approval_id = str(payload.get("approval_id") or "").strip()
    record = {
        "approval_id": approval_id,
        "draft_id": str(payload.get("draft_id") or "").strip(),
        "name": str(payload.get("name") or "Post orgánico").strip(),
        "page_id": str(payload.get("page_id") or "").strip(),
        "post_id": str(result.get("post_id") or "").strip(),
        "pillar": str(payload.get("pillar") or "").strip(),
        "objective": str(payload.get("objective") or "").strip(),
        "caption": str(payload.get("message") or payload.get("caption") or "").strip()[:4000],
        "image_path": str(payload.get("image_path") or "").strip(),
        "image_url": str(payload.get("image_url") or "").strip(),
        "status": "published" if result.get("ok") else "failed",
        "published_at": now_iso() if result.get("ok") else "",
        "updated_at": now_iso(),
    }
    items = [item for item in items if item.get("approval_id") != approval_id]
    items.insert(0, record)
    write_json(ORGANIC_CONTENT_POSTS_FILE, {"items": items[:250], "updated_at": now_iso()})
    return record


def publish_approved_social_post(payload, client):
    approval_id = str(payload.get("approval_id") or "").strip()
    previous = published_social_post_for_approval(approval_id) if approval_id else None
    if previous:
        return {
            "ok": True,
            "executed": True,
            "idempotent": True,
            "post_id": previous.get("post_id"),
            "page_id": previous.get("page_id"),
            "message": "Este post ya había sido publicado con esta aprobación.",
        }
    result = client.create_page_post(
        str(payload.get("page_id") or "").strip(),
        message=str(payload.get("message") or payload.get("caption") or "").strip(),
        link=str(payload.get("link") or "").strip(),
        image_path=str(payload.get("image_path") or "").strip(),
        image_url=str(payload.get("image_url") or "").strip(),
        unpublished_content_type="",
        cta=str(payload.get("cta") or "LEARN_MORE").strip(),
        published=True,
        approved=True,
    )
    body = social_body_from_result(result)
    ok = bool(result.get("executed") and result.get("returncode") == 0)
    publication = {
        "ok": ok,
        "executed": ok,
        "connector": result.get("connector") or "graph_api",
        "post_id": body.get("post_id") or body.get("id") or "",
        "page_id": body.get("page_id") or payload.get("page_id") or "",
        "page_name": body.get("page_name") or "",
        "provider_result": result,
    }
    record_social_post_publication(payload, publication)
    if ok and payload.get("image_path"):
        mark_asset_files_retained(
            [payload.get("image_path")],
            reason="organic_social_post_published",
            meta={"post_id": publication.get("post_id"), "page_id": publication.get("page_id")},
        )
    return publication


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


def native_campaign_creative_link(campaign, ad_plan, destination, message_destination="", lead_gen_form_id=""):
    """Return the destination used by an inline Meta AdCreative.

    Native forms and click-to-message ads select their real destination in
    the CTA/ad-set fields. Awareness and post-engagement ads can use
    ``photo_data``/``video_data`` without inventing a website URL. Website
    sales and traffic keep the exact buyer/configured destination.
    """
    page_id = str((destination or {}).get("page_id") or "").strip()
    if lead_gen_form_id:
        return SocialFlowClient.default_lead_form_link(page_id)
    if message_destination:
        return SocialFlowClient.default_message_destination_link(message_destination, page_id)
    explicit = str((ad_plan or {}).get("landing_url") or (ad_plan or {}).get("cta_link") or "").strip()
    if explicit:
        return explicit
    outcome = campaign_objective_for_social((campaign or {}).get("objective"), campaign=campaign, ad_plan=ad_plan)
    if outcome == "OUTCOME_APP_PROMOTION":
        return object_store_url_from_plan(ad_plan, campaign)
    if outcome in {"OUTCOME_SALES", "OUTCOME_TRAFFIC", "OUTCOME_APP_PROMOTION"}:
        return str((destination or {}).get("url") or "").strip()
    return ""


def native_campaign_cta(ad_plan, link="", message_destination="", lead_gen_form_id=""):
    if message_destination:
        return SocialFlowClient.message_destination_cta_type(message_destination)
    if lead_gen_form_id:
        return SocialFlowClient.normalize_call_to_action((ad_plan or {}).get("cta") or "SIGN_UP")
    if not link:
        return ""
    return SocialFlowClient.normalize_call_to_action((ad_plan or {}).get("cta") or "LEARN_MORE")


def prepare_native_ad_media(client, ad_plan, approved=False):
    """Resolve local image/video inputs into ad-account media IDs.

    The primary Live Ads app owns these uploads. No Page post is created.
    Returned operations are appended to the campaign audit trail by callers.
    """
    plan = ad_plan if isinstance(ad_plan, dict) else {}
    image_hash = str(plan.get("image_hash") or "").strip()
    video_id = str(plan.get("video_id") or "").strip()
    operations = []
    image_path = str(plan.get("creative_image_path") or "").strip()
    if image_path and not image_hash:
        upload_result = client.upload_image(client.config.ad_account_id, image_path, approved=approved)
        image_hash = image_hash_from_result(upload_result)
        operations.append({"step": "upload_image", "ok": bool(image_hash), "image_hash": image_hash, "result": upload_result})
        if not image_hash:
            return {"ok": False, "failed_step": "upload_image", "image_hash": "", "video_id": video_id, "operations": operations}

    video_path = str(plan.get("video_path") or "").strip()
    video_url = str(plan.get("video_url") or "").strip()
    if (video_path or video_url) and not video_id:
        upload_result = client.upload_video(
            client.config.ad_account_id,
            file_path=video_path,
            file_url=video_url,
            title=str(plan.get("name") or plan.get("headline") or "Admira IA video"),
            approved=approved,
        )
        body = social_body_from_result(upload_result)
        video_id = str(body.get("id") or body.get("video_id") or "").strip()
        operations.append({"step": "upload_video", "ok": bool(video_id), "video_id": video_id, "result": upload_result})
        if not video_id:
            return {"ok": False, "failed_step": "upload_video", "image_hash": image_hash, "video_id": "", "operations": operations}

    has_inline_media = bool(image_hash or plan.get("image_url") or video_id)
    has_explicit_story = bool(plan.get("object_story_spec") or plan.get("object_story_id"))
    if not has_inline_media and not has_explicit_story:
        return {
            "ok": False,
            "failed_step": "prepare_creative_media",
            "image_hash": image_hash,
            "video_id": video_id,
            "operations": operations,
            "missing_requirements": ["creative_image_path_or_image_hash_or_image_url_or_video_path_or_video_url_or_video_id"],
        }
    return {"ok": True, "image_hash": image_hash, "video_id": video_id, "operations": operations}


def create_native_ad_creative(client, creative_args, creative_kwargs):
    """Create one inline AdCreative with the primary Live Ads app.

    A second credential may retry the *same inline payload* only when Meta
    explicitly says the primary app is still in Development and the second
    credential has ads permissions. It never creates a dark post.
    """
    primary_kwargs = dict(creative_kwargs or {})
    primary_kwargs["prefer_publishing_token"] = False
    result = client.create_creative(*creative_args, **primary_kwargs)
    creative_id = social_id_from_result(result)
    token_source = "primary_ads_app"
    fallback_capability = {}
    if not creative_id and creative_blocked_by_development_mode(result):
        if hasattr(client, "publishing_ads_capability"):
            fallback_capability = client.publishing_ads_capability() or {}
        if fallback_capability.get("ok"):
            fallback_kwargs = dict(primary_kwargs)
            fallback_kwargs["prefer_publishing_token"] = True
            result = client.create_creative(*creative_args, **fallback_kwargs)
            creative_id = social_id_from_result(result)
            token_source = "publishing_ads_app_fallback"
    return creative_id, result, token_source, fallback_capability


def execute_multi_adset_native_stack(path, campaign, client, destination, campaign_id,
                                     adset_ids, status_plan, active_confirmed,
                                     approved, campaign_created_this_attempt, steps,
                                     resolved_whatsapp_phone_number=""):
    """Create each requested ad inline with the primary Live Ads app.

    This route supports native website, traffic, instant-form, messaging,
    awareness and engagement image/video creatives. It never creates a Page
    post. ``object_story_id`` remains supported only when the buyer explicitly
    selected an existing Page post.
    """
    adsets = campaign.get("ad_sets") or []
    if len(adsets) != len(adset_ids) or not any((item.get("ads") or []) for item in adsets if isinstance(item, dict)):
        return None
    ad_plan_default = dict(campaign.get("ad") or {})
    all_creative_ids = []
    all_ad_ids = []
    explicit_story_ids = []
    page_id = str((destination or {}).get("page_id") or "").strip()
    if not page_id:
        return campaign_creation_failure_result(
            path, campaign, client, campaign_id, "prepare_creative", steps,
            status_plan, active_confirmed, approved,
            allow_cleanup=cleanup_incomplete_campaign_allowed(campaign, campaign_id, campaign_created_this_attempt, status_plan, active_confirmed),
            adset_ids=adset_ids, reason="missing_page_id_for_multi_ad_stack",
        )

    default_message_destination = message_destination_from_plan(campaign) or message_destination_from_plan(ad_plan_default)
    default_whatsapp_number = (
        str(resolved_whatsapp_phone_number or "").strip()
        or whatsapp_phone_number_id_from_plan(ad_plan_default, campaign, destination)
    )
    expected_ad_count = 0
    for set_index, (adset, adset_id) in enumerate(zip(adsets, adset_ids)):
        if not isinstance(adset, dict):
            continue
        set_is_website = SocialFlowClient.normalize_destination_type(adset.get("destination_type")) == "WEBSITE"
        set_destination = "" if set_is_website else (message_destination_from_plan(adset) or default_message_destination)
        source_ads = adset.get("ads") or [ad_plan_default]
        expected_ad_count += len(source_ads)
        for ad_index, source in enumerate(source_ads):
            ad_plan = dict(ad_plan_default)
            if isinstance(source, dict):
                ad_plan.update({key: value for key, value in source.items() if value not in (None, "")})
            if set_is_website:
                ad_plan["destination_type"] = "WEBSITE"
                ad_plan["message_destination"] = ""
            elif set_destination and not message_destination_from_plan(ad_plan):
                ad_plan["message_destination"] = set_destination
            message_destination = "" if set_is_website else message_destination_from_plan(ad_plan)
            if message_destination == "WHATSAPP" and not whatsapp_phone_number_id_from_plan(ad_plan):
                ad_plan["whatsapp_phone_number_id"] = default_whatsapp_number

            lead_form_id = lead_gen_form_id_from_plan(ad_plan)
            link = native_campaign_creative_link(campaign, ad_plan, destination, message_destination, lead_form_id)
            body_text = str(ad_plan.get("primary_text") or f"Conoce {adset.get('name') or campaign.get('name', 'esta oferta')}.").strip()
            headline = str(ad_plan.get("headline") or adset.get("name") or campaign.get("name", "Nueva oferta")).strip()
            cta = native_campaign_cta(ad_plan, link, message_destination, lead_form_id)
            media = prepare_native_ad_media(client, ad_plan, approved=approved)
            for operation in media.get("operations") or []:
                steps.append({**operation, "adset_index": set_index, "ad_index": ad_index, "route": "native_inline_ads_app"})
            if not media.get("ok"):
                return campaign_creation_failure_result(
                    path, campaign, client, campaign_id, media.get("failed_step") or "prepare_creative_media", steps,
                    status_plan, active_confirmed, approved,
                    allow_cleanup=cleanup_incomplete_campaign_allowed(campaign, campaign_id, campaign_created_this_attempt, status_plan, active_confirmed),
                    adset_ids=adset_ids, creative_ids=[value for value in all_creative_ids if value], ad_ids=[value for value in all_ad_ids if value],
                    missing_requirements=media.get("missing_requirements") or [], adset_index=set_index, ad_index=ad_index,
                )

            existing_story_id = str(ad_plan.get("object_story_id") or "").strip()
            if existing_story_id:
                explicit_story_ids.append(existing_story_id)
            creative_args = (
                client.config.ad_account_id,
                str(ad_plan.get("name") or ad_plan.get("ad_name") or f"{campaign.get('name', 'Campaign')} - {adset.get('name', 'Ad Set')} - {ad_index + 1}"),
                page_id,
                link,
                body_text,
                headline,
                media.get("image_hash") or "",
                cta,
                str((destination or {}).get("instagram_actor_id") or ""),
            )
            creative_kwargs = {
                "object_story_spec": ad_plan.get("object_story_spec") or {},
                "image_url": str(ad_plan.get("image_url") or "").strip(),
                "video_id": media.get("video_id") or "",
                "cta_link": str(ad_plan.get("cta_link") or "").strip(),
                "object_story_id": existing_story_id,
                "lead_gen_form_id": lead_form_id,
                "prefilled_message": str(ad_plan.get("prefilled_message") or "").strip() if message_destination else "",
                "welcome_message": str(ad_plan.get("welcome_message") or ad_plan.get("initial_business_message") or "").strip(),
                "message_destination": message_destination,
                "approved": approved,
            }
            creative_id, creative_result, token_source, fallback_capability = create_native_ad_creative(client, creative_args, creative_kwargs)
            all_creative_ids.append(creative_id)
            steps.append({
                "step": "create_creative", "ok": bool(creative_id), "route": "existing_page_post" if existing_story_id else "native_inline_ads_app",
                "creative_token_source": token_source, "fallback_capability": fallback_capability,
                "adset_index": set_index, "ad_index": ad_index, "adset_id": adset_id,
                "creative_id": creative_id, "object_story_id": existing_story_id, "result": creative_result,
            })
            if not creative_id:
                return campaign_creation_failure_result(
                    path, campaign, client, campaign_id, "create_creative", steps,
                    status_plan, active_confirmed, approved,
                    allow_cleanup=cleanup_incomplete_campaign_allowed(campaign, campaign_id, campaign_created_this_attempt, status_plan, active_confirmed),
                    adset_ids=adset_ids, creative_ids=[value for value in all_creative_ids if value], ad_ids=[value for value in all_ad_ids if value],
                    adset_index=set_index, ad_index=ad_index,
                )
            ad_name = str(ad_plan.get("name") or ad_plan.get("ad_name") or f"{campaign.get('name', 'Campaign')} - {adset.get('name', 'Ad Set')} - Variante {ad_index + 1}").strip()
            ad_result = client.create_ad(adset_id, ad_name, creative_id, "PAUSED", website_url=link, approved=approved)
            ad_id = social_id_from_result(ad_result)
            all_ad_ids.append(ad_id)
            steps.append({
                "step": "create_ad", "ok": bool(ad_id), "route": "native_inline_live_ads_app",
                "adset_index": set_index, "ad_index": ad_index, "adset_id": adset_id,
                "creative_id": creative_id, "ad_id": ad_id, "final_status": "PAUSED", "result": ad_result,
            })
            if not ad_id:
                return campaign_creation_failure_result(
                    path, campaign, client, campaign_id, "create_ad", steps,
                    status_plan, active_confirmed, approved,
                    allow_cleanup=cleanup_incomplete_campaign_allowed(campaign, campaign_id, campaign_created_this_attempt, status_plan, active_confirmed),
                    adset_ids=adset_ids, creative_ids=[value for value in all_creative_ids if value], ad_ids=[value for value in all_ad_ids if value],
                    adset_index=set_index, ad_index=ad_index,
                )

    if not all_ad_ids or len([value for value in all_ad_ids if value]) != expected_ad_count:
        return campaign_creation_failure_result(
            path, campaign, client, campaign_id, "create_ad", steps,
            status_plan, active_confirmed, approved,
            allow_cleanup=cleanup_incomplete_campaign_allowed(campaign, campaign_id, campaign_created_this_attempt, status_plan, active_confirmed),
            adset_ids=adset_ids, creative_ids=[value for value in all_creative_ids if value], ad_ids=[value for value in all_ad_ids if value],
            reason="multi_ad_stack_incomplete",
        )
    return {
        "ok": True, "mode": client.config.mode, "executed": True, "campaign_id": campaign_id,
        "adset_ids": adset_ids, "creative_ids": [value for value in all_creative_ids if value],
        "creative_id": next((value for value in all_creative_ids if value), ""),
        "ad_ids": [value for value in all_ad_ids if value], "ad_id": next((value for value in all_ad_ids if value), ""),
        "object_story_ids": explicit_story_ids, "creative_route": "native_inline_ads_app",
        "final_status": "PAUSED", "status_plan": status_plan, "steps": steps,
    }


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


META_WHOLE_UNIT_BUDGET_CURRENCIES = {
    # Meta's Marketing API expects whole account-currency units for these
    # currencies instead of the x100 offset used by USD/EUR. COP is verified
    # against live Ads Manager-created ad sets; keep this list explicit so a
    # local-currency budget can never be silently inflated by 100x.
    "CLP", "COP", "CRC", "HUF", "IDR", "ISK", "JPY", "KRW", "PYG", "TWD", "VND",
}


def meta_budget_api_amount(amount, currency=""):
    """Convert a buyer-facing amount into Meta's integer budget unit."""
    try:
        numeric = float(amount or 0)
    except (TypeError, ValueError):
        return 0
    normalized_currency = str(currency or "").strip().upper()
    factor = 1 if normalized_currency in META_WHOLE_UNIT_BUDGET_CURRENCIES else 100
    return max(0, int(round(numeric * factor)))


def meta_campaign_body_has_campaign_budget(body):
    if not isinstance(body, dict):
        return False
    for key in ("daily_budget", "lifetime_budget"):
        try:
            if int(float(str(body.get(key) or 0).replace(",", ""))) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def meta_campaign_has_campaign_budget(client, campaign_id):
    if not campaign_id or not hasattr(client, "campaign_details"):
        return False
    result = client.campaign_details(campaign_id)
    if result.get("returncode") not in {0, None}:
        return False
    return meta_campaign_body_has_campaign_budget(social_body_from_result(result))


def meta_campaign_reuse_check(client, campaign_id):
    """Return whether a previously-created campaign ID is safe to reuse.

    Retries are useful when Meta accepted the campaign but failed later at the
    ad set/creative/ad step. The sharp edge is a cleanup or manual deletion
    between attempts: the old approval result can still carry a campaign_id,
    and blindly reusing it makes Meta fail with "Campaign Deleted". When the
    connector can look up the campaign, use that as the source of truth.
    """
    campaign_id = str(campaign_id or "").strip()
    if not campaign_id:
        return {"checked": False, "reusable": False, "reason": "missing_campaign_id"}
    if not hasattr(client, "campaign_details"):
        return {"checked": False, "reusable": True, "reason": "lookup_not_supported"}
    result = client.campaign_details(campaign_id)
    text = result_debug_text(result)
    body = social_body_from_result(result)
    if result.get("returncode") not in {0, None}:
        return {
            "checked": True,
            "reusable": False,
            "reason": "lookup_failed",
            "campaign_id": campaign_id,
            "result": result,
        }
    status_text = " ".join(
        str(body.get(key) or "")
        for key in ("status", "effective_status", "configured_status")
    ).lower()
    if "deleted" in text or "deleted" in status_text:
        return {
            "checked": True,
            "reusable": False,
            "reason": "campaign_deleted",
            "campaign_id": campaign_id,
            "result": result,
        }
    return {
        "checked": True,
        "reusable": True,
        "reason": "campaign_found",
        "campaign_id": campaign_id,
        "body_has_campaign_budget": meta_campaign_body_has_campaign_budget(body),
        "result": result,
    }


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


def clear_campaign_execution_ids(path, campaign, reason, campaign_id=""):
    try:
        execution_state = dict(campaign.get("execution_state") or {})
        execution_state.pop("campaign_id", None)
        execution_state.pop("adset_ids", None)
        execution_state["stale_campaign_reason"] = reason
        if campaign_id:
            execution_state["stale_campaign_id"] = campaign_id
        execution_state["stale_campaign_cleared_at"] = now_iso()
        campaign["execution_state"] = execution_state
        write_json(Path(path), campaign)
    except Exception:
        pass


def reset_campaign_execution_after_partial_cleanup(path, campaign, campaign_id, cleanup):
    try:
        execution_state = dict(campaign.get("execution_state") or {})
        execution_state.pop("campaign_id", None)
        execution_state.pop("adset_ids", None)
        execution_state["partial_cleanup"] = cleanup
        execution_state["partial_deleted_campaign_id"] = campaign_id
        execution_state["partial_cleanup_at"] = now_iso()
        campaign["execution_state"] = execution_state
        write_json(Path(path), campaign)
    except Exception:
        pass


def safe_for_partial_campaign_cleanup(campaign, status_plan, active_confirmed):
    if bool(campaign.get("disable_auto_cleanup_partial_failures")):
        return False
    if active_confirmed:
        return False
    statuses = list((status_plan or {}).values()) or ["PAUSED"]
    return all(str(status or "PAUSED").strip().upper() == "PAUSED" for status in statuses)


def cleanup_incomplete_campaign_allowed(campaign, campaign_id, campaign_created_this_attempt, status_plan, active_confirmed):
    """Delete incomplete PAUSED campaign stacks even across retries.

    A campaign ID stored from a previous failed attempt is still owned by this
    creation workflow. If a later retry cannot complete the stack, keeping that
    partial campaign makes the next retry dirty and leaves confusing objects in
    Ads Manager. Active/spend-capable flows remain protected by
    `safe_for_partial_campaign_cleanup`.
    """
    if campaign_created_this_attempt:
        return True
    if not campaign_id:
        return False
    return safe_for_partial_campaign_cleanup(campaign, status_plan, active_confirmed)


def cleanup_partial_created_campaign(path, campaign, client, campaign_id, failed_step, steps, status_plan, active_confirmed, approved, allow_cleanup=True):
    if not campaign_id:
        return {"attempted": False, "reason": "missing_campaign_id"}
    if not allow_cleanup:
        return {"attempted": False, "reason": "campaign_not_created_in_this_attempt", "campaign_id": campaign_id}
    if not safe_for_partial_campaign_cleanup(campaign, status_plan, active_confirmed):
        return {"attempted": False, "reason": "not_safe_for_auto_cleanup", "campaign_id": campaign_id}
    if not hasattr(client, "delete"):
        return {"attempted": False, "reason": "delete_not_supported", "campaign_id": campaign_id}
    result = client.delete("campaign", campaign_id, approved=approved)
    ok = result.get("returncode") in {0, None}
    cleanup = {
        "attempted": True,
        "ok": ok,
        "campaign_id": campaign_id,
        "failed_step": failed_step,
        "result": result,
    }
    if ok:
        reset_campaign_execution_after_partial_cleanup(path, campaign, campaign_id, cleanup)
    log_action(
        "cleanup_partial_campaign",
        {
            "campaign_id": campaign_id,
            "campaign_name": campaign.get("name"),
            "failed_step": failed_step,
            "deleted": ok,
            "step_count": len(steps or []),
        },
        "completed" if ok else "failed",
    )
    return cleanup


def campaign_creation_failure_result(path, campaign, client, campaign_id, failed_step, steps, status_plan, active_confirmed, approved, allow_cleanup=True, **extra):
    result = {
        "ok": False,
        "mode": client.config.mode,
        "executed": True,
        "failed_step": failed_step,
        "steps": steps,
        **extra,
    }
    if campaign_id:
        result.setdefault("campaign_id", campaign_id)
        cleanup = cleanup_partial_created_campaign(path, campaign, client, campaign_id, failed_step, steps, status_plan, active_confirmed, approved, allow_cleanup=allow_cleanup)
        if cleanup.get("attempted"):
            result["cleanup"] = cleanup
            result["cleanup_attempted"] = True
            result["partial_campaign_deleted"] = bool(cleanup.get("ok"))
    return result


def campaign_objective_for_social(objective, campaign=None, ad_plan=None):
    """Map durable campaign intent to Meta's current outcome enum.

    Native lead-form plans must stay leads all the way to the campaign
    endpoint. Older/model payloads sometimes left SALES on the campaign while
    putting LEAD_GENERATION only on the ad set, which Meta rejects.
    """
    campaign = campaign if isinstance(campaign, dict) else {}
    ad_plan = ad_plan if isinstance(ad_plan, dict) else {}
    lead_form_id = lead_gen_form_id_from_plan(ad_plan)
    raw_values = (
        objective,
        campaign.get("campaign_objective"),
        campaign.get("goal"),
        ad_plan.get("campaign_objective"),
        ad_plan.get("objective"),
    )
    normalized = {str(value or "").strip().upper().replace("-", "_") for value in raw_values}
    if lead_form_id or normalized.intersection({
        "LEADS", "LEAD", "LEAD_GENERATION", "LEAD_FORM", "LEAD_FORMS",
        "INSTANT_FORM", "INSTANT_FORMS", "FORMS", "FORMULARIOS", "OUTCOME_LEADS",
        "OUTCOME_LEAD_GENERATION",
    }):
        # OUTCOME_LEADS is Meta's current Graph campaign objective. The ad-set
        # optimization goal remains LEAD_GENERATION.
        return "OUTCOME_LEADS"
    mapping = {
        "OUTCOME_SALES": "OUTCOME_SALES",
        "OUTCOME_TRAFFIC": "OUTCOME_TRAFFIC",
        "OUTCOME_ENGAGEMENT": "OUTCOME_ENGAGEMENT",
        "OUTCOME_AWARENESS": "OUTCOME_AWARENESS",
        "OUTCOME_APP_PROMOTION": "OUTCOME_APP_PROMOTION",
        "PURCHASES": "OUTCOME_SALES",
        "CONVERSIONS": "OUTCOME_SALES",
        "SALES": "OUTCOME_SALES",
        "SALE": "OUTCOME_SALES",
        "VENTAS": "OUTCOME_SALES",
        "VENTA": "OUTCOME_SALES",
        "COMPRAS": "OUTCOME_SALES",
        "COMPRA": "OUTCOME_SALES",
        # Meta's current campaign objective enum is OUTCOME_LEADS.  The
        # ad-set optimization goal remains LEAD_GENERATION; these are
        # different Graph fields and must not be conflated.
        "LEADS": "OUTCOME_LEADS",
        "LEAD_GENERATION": "OUTCOME_LEADS",
        "LEAD_FORM": "OUTCOME_LEADS",
        "LEAD_FORMS": "OUTCOME_LEADS",
        "INSTANT_FORM": "OUTCOME_LEADS",
        "INSTANT_FORMS": "OUTCOME_LEADS",
        "FORMS": "OUTCOME_LEADS",
        "FORMULARIOS": "OUTCOME_LEADS",
        "MESSAGES": "OUTCOME_ENGAGEMENT",
        "MESSAGE": "OUTCOME_ENGAGEMENT",
        "CONVERSATIONS": "OUTCOME_ENGAGEMENT",
        "WHATSAPP": "OUTCOME_ENGAGEMENT",
        "MESSENGER": "OUTCOME_ENGAGEMENT",
        "ENGAGEMENT": "OUTCOME_ENGAGEMENT",
        "INTERACTION": "OUTCOME_ENGAGEMENT",
        "INTERACTIONS": "OUTCOME_ENGAGEMENT",
        "INTERACCION": "OUTCOME_ENGAGEMENT",
        "INTERACCIONES": "OUTCOME_ENGAGEMENT",
        "INTERACCIÓN": "OUTCOME_ENGAGEMENT",
        "POST_ENGAGEMENT": "OUTCOME_ENGAGEMENT",
        "VIDEO": "OUTCOME_ENGAGEMENT",
        "VIDEO_VIEWS": "OUTCOME_ENGAGEMENT",
        "THRUPLAY": "OUTCOME_ENGAGEMENT",
        "AWARENESS": "OUTCOME_AWARENESS",
        "REACH": "OUTCOME_AWARENESS",
        "BRAND_AWARENESS": "OUTCOME_AWARENESS",
        "APP_INSTALLS": "OUTCOME_APP_PROMOTION",
        "APP_PROMOTION": "OUTCOME_APP_PROMOTION",
        # Explicit link-to-WhatsApp fallbacks use a real website destination
        # (wa.me). Keep that buyer-approved fallback aligned with
        # LINK_CLICKS/LANDING_PAGE_VIEWS; never select it merely because the
        # Page number comes from the WhatsApp Business mobile app.
        "TRAFFIC": "OUTCOME_TRAFFIC",
        "LINK_CLICKS": "OUTCOME_TRAFFIC",
        "LANDING_PAGE_VIEWS": "OUTCOME_TRAFFIC",
    }
    return mapping.get(str(objective or "").upper(), "OUTCOME_SALES")


def lead_gen_form_id_from_plan(ad_plan):
    for key in ("lead_gen_form_id", "lead_form_id", "instant_form_id", "meta_lead_form_id", "form_id"):
        value = str((ad_plan or {}).get(key) or "").strip()
        if value:
            return value
    return ""


def message_destination_from_plan(ad_plan):
    # An explicit website destination wins over heuristic URL detection. A
    # buyer-approved wa.me fallback remains a website URL at the Graph API
    # boundary. Without this guard the URL heuristic would turn a deliberate
    # LINK_CLICKS/WEBSITE fallback back into a CONVERSATIONS/WHATSAPP ad set.
    explicit_destination = str((ad_plan or {}).get("destination_type") or "").strip()
    if explicit_destination and SocialFlowClient.normalize_destination_type(explicit_destination) == "WEBSITE":
        return ""
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


def whatsapp_phone_number_id_from_plan(*plans):
    """Return Meta's numeric WhatsApp promoted-object identifier.

    Depending on how WhatsApp was connected, Meta can expose either a Graph
    phone-number ID or the E.164 digits used by native Ads Manager ad sets.
    Both are numeric and accepted in ``promoted_object.whatsapp_phone_number``.
    Never forward labels or formatted free text here.
    """
    keys = (
        "whatsapp_phone_number_id",
        "whatsapp_number_id",
        "phone_number_id",
        "whatsapp_phone_id",
    )
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        candidates = [plan]
        for nested_key in ("destination", "whatsapp", "whatsapp_business", "messaging"):
            nested = plan.get(nested_key)
            if isinstance(nested, dict):
                candidates.append(nested)
        for candidate in candidates:
            for key in keys:
                value = str(candidate.get(key) or "").strip()
                if value.isdigit():
                    return value
    return ""


def application_id_from_plan(*plans):
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        for candidate in (plan, plan.get("app") if isinstance(plan.get("app"), dict) else {}):
            for key in ("application_id", "app_id", "meta_application_id"):
                value = str(candidate.get(key) or "").strip()
                if value:
                    return value
    return ""


def object_store_url_from_plan(*plans):
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        for candidate in (plan, plan.get("app") if isinstance(plan.get("app"), dict) else {}):
            for key in ("object_store_url", "app_store_url", "play_store_url", "store_url"):
                value = str(candidate.get(key) or "").strip()
                if value.startswith(("http://", "https://")):
                    return value
    return ""


def adset_optimization_goal_for_campaign(adset, campaign, lead_gen_form_id="", message_destination=""):
    objective = str((campaign or {}).get("objective") or "").upper()
    if lead_gen_form_id or objective in {"LEADS", "LEAD_GENERATION", "LEAD_FORM", "LEAD_FORMS", "INSTANT_FORM", "INSTANT_FORMS", "FORMS", "FORMULARIOS", "OUTCOME_LEADS", "OUTCOME_LEAD_GENERATION"}:
        return "LEAD_GENERATION"
    # A stale conversion goal in an old draft must never override a
    # click-to-message destination. Meta's Graph API uses CONVERSATIONS for
    # these ad sets; WHATSAPP_MESSAGES is not a valid generic optimization
    # goal enum for the current Marketing API.
    if message_destination:
        return "CONVERSATIONS"
    explicit = str((adset or {}).get("optimization_goal") or "").strip()
    if explicit:
        return SocialFlowClient.normalize_optimization_goal(explicit)
    if objective in {"SALES", "SALE", "PURCHASES", "COMPRAS", "COMPRA", "CONVERSIONS", "OUTCOME_SALES", "VENTAS", "VENTA"}:
        return "OFFSITE_CONVERSIONS"
    if objective in {"AWARENESS", "REACH", "BRAND_AWARENESS"}:
        return "REACH"
    if objective in {"VIDEO", "VIDEO_VIEWS", "THRUPLAY"}:
        return "THRUPLAY"
    if objective in {"ENGAGEMENT", "POST_ENGAGEMENT", "INTERACTION", "INTERACTIONS", "INTERACCION", "INTERACCIONES", "INTERACCIÓN"}:
        return "POST_ENGAGEMENT"
    if objective in {"APP_INSTALLS", "APP_PROMOTION"}:
        return "APP_INSTALLS"
    return "LINK_CLICKS"


def targeting_for_social(targeting):
    targeting = targeting or {}
    if isinstance(targeting.get("geo_locations"), dict):
        geo_locations = dict(targeting["geo_locations"])
    else:
        geo_locations = None
    age_range = targeting.get("age_range") or {}
    countries = normalize_location_codes(targeting.get("locations"), default=["US"])
    meta_targeting = targeting.get("meta_targeting") or {}
    if isinstance(geo_locations, dict) and "countries" in geo_locations:
        normalized_geo_countries = normalize_location_codes(geo_locations.get("countries"), default=[])
        if normalized_geo_countries:
            geo_locations["countries"] = normalized_geo_countries
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
    if not selected_interests and isinstance(targeting.get("interests"), list):
        # Only structured Meta catalog selections are authoritative here. A
        # free-form interest name is an idea, not a current Meta interest ID.
        selected_interests = targeting.get("interests")
    interests = []
    if isinstance(selected_interests, list):
        for item in selected_interests:
            if not isinstance(item, dict):
                continue
            interest_id = str(item.get("id") or "").strip()
            name = str(item.get("name") or "").strip()
            if interest_id:
                normalized = {"id": interest_id}
                if name:
                    normalized["name"] = name
                interests.append(normalized)
        if interests:
            spec["interests"] = interests
    flexible_interest_present = False
    for group in (targeting.get("flexible_spec") or []) if isinstance(targeting.get("flexible_spec"), list) else []:
        if not isinstance(group, dict):
            continue
        if any(isinstance(item, dict) and str(item.get("id") or "").strip() for item in (group.get("interests") or [])):
            flexible_interest_present = True
            break
    if not flexible_interest_present and isinstance(meta_targeting, dict):
        for group in (meta_targeting.get("flexible_spec") or []) if isinstance(meta_targeting.get("flexible_spec"), list) else []:
            if not isinstance(group, dict):
                continue
            if any(isinstance(item, dict) and str(item.get("id") or "").strip() for item in (group.get("interests") or [])):
                flexible_interest_present = True
                break
    automation = targeting.get("targeting_automation")
    if not isinstance(automation, dict) and isinstance(meta_targeting, dict):
        automation = meta_targeting.get("targeting_automation")
    targeting_mode = str(targeting.get("targeting_mode") or "").strip().lower()
    advantage_value = None
    if isinstance(automation, dict) and "advantage_audience" in automation:
        enabled = boolish(automation.get("advantage_audience"))
        if enabled is not None:
            advantage_value = 1 if enabled else 0
    if targeting_mode in {"advantage", "advantage+", "advantage_plus", "advantage_plus_audience", "suggested", "suggestions"}:
        advantage_value = 1
    elif targeting_mode in {"manual", "strict", "detailed", "detailed_targeting"}:
        advantage_value = 0
    elif advantage_value is None and (interests or flexible_interest_present):
        # Meta requires an explicit Advantage+ audience flag when detailed
        # interest targeting is sent. In the absence of an explicit strict
        # request, treat the interests as suggestions (the better default for
        # cold prospecting and small tests) and let Meta expand beyond them.
        advantage_value = 1
    if advantage_value is not None:
        spec["targeting_automation"] = {"advantage_audience": advantage_value}
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
    if not spec.get("genders"):
        genders = normalize_gender_values(
            targeting.get("gender") or targeting.get("targeting_gender") or targeting.get("targeting_genders")
        )
        if genders:
            spec["genders"] = genders
    return apply_placement_targeting(spec, targeting.get("placements") or targeting.get("placement_preset"))


def targeting_interest_ids(targeting):
    """Return persisted interest IDs from direct or flexible targeting."""
    if not isinstance(targeting, dict):
        return []
    values = []
    for item in targeting.get("interests") or []:
        if isinstance(item, dict) and item.get("id"):
            values.append(str(item.get("id")))
    for group in targeting.get("flexible_spec") or []:
        if not isinstance(group, dict):
            continue
        for item in group.get("interests") or []:
            if isinstance(item, dict) and item.get("id"):
                values.append(str(item.get("id")))
    return list(dict.fromkeys(values))


def targeting_advantage_value(targeting):
    automation = targeting.get("targeting_automation") if isinstance(targeting, dict) else {}
    if not isinstance(automation, dict) or "advantage_audience" not in automation:
        return None
    enabled = boolish(automation.get("advantage_audience"))
    return (1 if enabled else 0) if enabled is not None else None


def targeting_needs_live_verification(targeting):
    return bool(targeting_interest_ids(targeting)) or targeting_advantage_value(targeting) is not None


def verify_adset_targeting_result(requested_targeting, result):
    body = social_body_from_result(result)
    actual = body.get("targeting") or {}
    if isinstance(actual, str):
        try:
            actual = json.loads(actual)
        except json.JSONDecodeError:
            actual = {}
    if not isinstance(actual, dict):
        actual = {}
    requested_ids = targeting_interest_ids(requested_targeting)
    actual_ids = targeting_interest_ids(actual)
    missing_ids = [value for value in requested_ids if value not in actual_ids]
    requested_advantage = targeting_advantage_value(requested_targeting)
    actual_advantage = targeting_advantage_value(actual)
    read_ok = result.get("returncode") in {0, None} and bool(body.get("id") or actual)
    advantage_matches = requested_advantage is None or requested_advantage == actual_advantage
    confirmed = bool(read_ok and not missing_ids and advantage_matches)
    return {
        "ok": confirmed,
        "confirmed": confirmed,
        "source": "meta_live",
        "requested_interest_ids": requested_ids,
        "persisted_interest_ids": actual_ids,
        "missing_interest_ids": missing_ids,
        "requested_advantage_audience": requested_advantage,
        "persisted_advantage_audience": actual_advantage,
        "advantage_audience_matches": advantage_matches,
        "ui_confirmation": False,
        "ui_note": "Confirma el targeting persistido por Graph; no garantiza la ubicación o el texto exacto mostrado por Ads Manager.",
        "result": result,
    }


def validate_campaign_targeting_before_meta(campaign, client):
    """Resolve and validate every ad-set audience before create_campaign.

    This is deliberately before the first Graph mutation. A stale/synthetic
    interest ID or a malformed location therefore cannot leave an orphaned
    campaign behind while the ad set fails later.
    """
    validations = []
    for index, adset in enumerate(campaign.get("ad_sets") or []):
        targeting = dict((adset or {}).get("targeting") or {})
        detailed_id_validation = validate_detailed_targeting_ids(targeting)
        if not detailed_id_validation.get("ok"):
            validations.append({
                "adset_index": index,
                "ok": False,
                "errors": detailed_id_validation.get("errors") or [],
            })
            return {
                "ok": False,
                "code": "targeting_preflight_failed",
                "validations": validations,
                "message": "La segmentación detallada contiene un ID sintético o inválido; no se creó ningún objeto.",
            }
        detailed_items = detailed_targeting_items(targeting)
        if detailed_items and hasattr(client, "validate_meta_targeting"):
            live_detail_validation = client.validate_meta_targeting(detailed_items)
            if not isinstance(live_detail_validation, dict) or not live_detail_validation.get("ok"):
                validations.append({
                    "adset_index": index,
                    "ok": False,
                    "errors": [{
                        "field": "detailed_targeting",
                        "code": "targeting_detail_not_current",
                        "details": (live_detail_validation or {}).get("error") if isinstance(live_detail_validation, dict) else "targeting_validation_failed",
                    }],
                })
                return {
                    "ok": False,
                    "code": "targeting_preflight_failed",
                    "validations": validations,
                    "message": "Meta no confirmó la segmentación detallada actual; no se creó ningún objeto.",
                }
        meta_targeting = targeting.get("meta_targeting") if isinstance(targeting.get("meta_targeting"), dict) else {}
        interests = meta_targeting.get("interests") or targeting.get("interests") or []
        selected_locations = meta_targeting.get("locations") or []
        if selected_locations:
            locations = selected_locations
        else:
            raw_locations = targeting.get("locations")
            normalized_locations = normalize_location_codes(raw_locations, default=[])
            locations = [
                {
                    "key": code,
                    "name": country_name_for_code(code),
                    "type": "country",
                    "country_code": code,
                }
                for code in normalized_locations
            ]
        age_range = targeting.get("age_range") or {}
        age_bounds = normalize_age_bounds(
            age_range,
            age_min=targeting.get("age_min", targeting.get("min_age", 18)),
            age_max=targeting.get("age_max", targeting.get("max_age", 65)),
        )
        if not age_bounds.get("ok"):
            validations.append({
                "adset_index": index,
                "ok": False,
                "errors": [{"field": "age_range", "code": age_bounds.get("error") or "targeting_age_invalid"}],
            })
            continue

        # Meta treats a lower maximum age as a suggestion when Advantage+
        # audience is enabled; it rejects an ad set that tries to enforce
        # age_max below 65. Stop before the first Graph mutation so the agent
        # can choose between a flexible 18-65 Advantage+ audience or a strict
        # manual audience with advantage_audience=0.
        requested_social_targeting = targeting_for_social(targeting)
        requested_advantage = targeting_advantage_value(requested_social_targeting)
        if requested_advantage == 1 and age_bounds["age_max"] < 65:
            validations.append({
                "adset_index": index,
                "ok": False,
                "errors": [{
                    "field": "age_range.max",
                    "code": "advantage_audience_age_max_requires_65",
                    "requested_age_max": age_bounds["age_max"],
                    "effective_age_max": 65,
                    "message": "Con Advantage+ audience, Meta exige age_max=65; una edad menor solo puede enviarse como sugerencia. Usa 65 para mantener Advantage+ o targeting_mode=manual/advantage_audience=0 para imponer el límite.",
                }],
            })
            return {
                "ok": False,
                "code": "targeting_preflight_failed",
                "validations": validations,
                "message": "Meta no permite un límite máximo menor de 65 con Advantage+ audience. Puedo mantener la edad como sugerencia o desactivar Advantage+ para aplicar el límite estricto.",
            }

        live_search = None
        if hasattr(client, "search_meta_targeting"):
            def live_search(kind, query):
                return client.search_meta_targeting(kind, query, limit=25)

        checked = validate_meta_targeting_selection(
            interests,
            locations,
            age_min=age_bounds["age_min"],
            age_max=age_bounds["age_max"],
            live_search=live_search,
            verify_locations=bool(selected_locations),
        )
        validations.append({"adset_index": index, **checked})
        if not checked.get("ok"):
            return {
                "ok": False,
                "code": "targeting_preflight_failed",
                "validations": validations,
                "message": "La segmentación ya no coincide con el catálogo live de Meta; no se creó ningún objeto.",
            }
    return {"ok": True, "code": "targeting_preflight_passed", "validations": validations}


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
    # A staged link-to-WhatsApp fallback deliberately uses ``wa.me`` as a
    # website URL. Do not let the URL heuristic turn it back into a native
    # WhatsApp ad after normalization has already selected WEBSITE on the
    # ad set. That would send CONVERSATIONS to a TRAFFIC campaign and Meta
    # rejects the ad set before any creative is attempted.
    has_explicit_website_adset = any(
        isinstance(stored_adset, dict)
        and SocialFlowClient.normalize_destination_type(stored_adset.get("destination_type")) == "WEBSITE"
        for stored_adset in (campaign.get("ad_sets") or [])
    )
    message_destination = "" if has_explicit_website_adset else message_destination_from_plan(ad_plan)
    if has_explicit_website_adset:
        ad_plan["message_destination"] = ""
        ad_plan["destination_type"] = "WEBSITE"
    if not message_destination and not has_explicit_website_adset:
        # Older campaign files stored the messaging destination on the ad set
        # or campaign object. Recover it before choosing the optimization
        # goal, rather than silently falling back to web conversions.
        message_destination = message_destination_from_plan(campaign)
        if not message_destination:
            for stored_adset in campaign.get("ad_sets", []):
                message_destination = message_destination_from_plan(stored_adset)
                if message_destination:
                    break
    explicit_whatsapp_phone_number = whatsapp_phone_number_id_from_plan(ad_plan, campaign, destination)
    whatsapp_number_resolution = {}
    resolved_whatsapp_phone_number = ""
    if message_destination == "WHATSAPP" and hasattr(client, "resolve_whatsapp_phone_number"):
        whatsapp_number_resolution = client.resolve_whatsapp_phone_number(destination.get("page_id", "")) or {}
        if whatsapp_number_resolution.get("ok"):
            resolved_whatsapp_phone_number = str(whatsapp_number_resolution.get("whatsapp_phone_number") or "").strip()
    # Meta live state wins over a stale or guessed conversational value. A
    # mobile-app-linked number may be visible only in existing native ad sets,
    # even while Page.whatsapp_number is empty for the connected token.
    whatsapp_phone_number_id = resolved_whatsapp_phone_number or explicit_whatsapp_phone_number
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
    has_external_destination = bool(
        ad_plan.get("landing_url")
        or destination.get("url")
        or object_store_url_from_plan(ad_plan, campaign)
    )
    mapped_objective = campaign_objective_for_social(campaign.get("objective"), campaign=campaign, ad_plan=ad_plan)
    requires_external_destination = mapped_objective in {"OUTCOME_SALES", "OUTCOME_TRAFFIC", "OUTCOME_APP_PROMOTION"}
    if requires_external_destination and not (
        has_external_destination
        or ad_plan.get("object_story_spec")
        or ad_plan.get("object_story_id")
        or message_destination
    ):
        missing.append("landing URL")
    if mapped_objective == "OUTCOME_APP_PROMOTION":
        if not application_id_from_plan(ad_plan, campaign):
            missing.append("application_id")
        if not object_store_url_from_plan(ad_plan, campaign):
            missing.append("object_store_url")
    matrix_has_creative = any(
        isinstance(item, dict)
        and any(
            isinstance(ad, dict) and creative_source_available(ad)
            for ad in (item.get("ads") or [])
        )
        for item in (campaign.get("ad_sets") or [])
    )
    if not creative_source_available(ad_plan) and not matrix_has_creative and not (manual_completion or placeholder_static):
        missing.append("creative image path, image hash, image URL, video URL, object_story_spec, or object_story_id")
    elif ad_plan.get("creative_image_path") and not Path(ad_plan.get("creative_image_path")).exists():
        missing.append(f"creative image file missing: {ad_plan.get('creative_image_path')}")
    # A Page-linked WhatsApp Business number is resolved by Meta when the ad
    # set is created.  The Page ID is the durable promoted object; the phone
    # number ID is not exposed by every valid Page/system-user token (and is
    # often absent for numbers connected through Business Suite).  Do not
    # block a real WhatsApp attempt merely because the optional lookup is
    # empty.  Meta will return the authoritative, actionable error if the
    # Page is still linked to a personal number or has no WhatsApp Business
    # account.  This also lets newly-connected WABA numbers work immediately.
    if message_destination == "WHATSAPP" and not destination.get("page_id") and not (manual_completion or placeholder_static):
        missing.append("Facebook Page ID for WhatsApp destination")
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
    targeting_preflight = validate_campaign_targeting_before_meta(campaign, client)
    if not targeting_preflight.get("ok"):
        return {
            "ok": False,
            "mode": client.config.mode,
            "executed": False,
            "blocked": True,
            "failed_step": "validate_targeting",
            "reason": targeting_preflight.get("code") or "targeting_preflight_failed",
            "message": targeting_preflight.get("message") or "La segmentación no pasó la verificación previa.",
            "targeting_preflight": targeting_preflight,
            "path": path,
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
    if message_destination == "WHATSAPP":
        steps.append({
            "step": "resolve_whatsapp_phone_number",
            "ok": bool(whatsapp_phone_number_id),
            "whatsapp_phone_number": whatsapp_phone_number_id,
            "source": whatsapp_number_resolution.get("source") or ("request" if explicit_whatsapp_phone_number else "unresolved"),
            "result": whatsapp_number_resolution,
        })
    campaign_created_this_attempt = False
    reuse_check = {}
    if campaign_id:
        reuse_check = meta_campaign_reuse_check(client, campaign_id)
        steps.append({"step": "reuse_campaign_check", "ok": bool(reuse_check.get("reusable")), "campaign_id": campaign_id, "result": reuse_check})
        if not reuse_check.get("reusable"):
            clear_campaign_execution_ids(path, campaign, str(reuse_check.get("reason") or "campaign_not_reusable"), campaign_id)
            campaign_id = ""
        else:
            steps.append({"step": "create_campaign", "ok": True, "campaign_id": campaign_id, "status": status_plan.get("campaign", "PAUSED"), "reused": True})
        campaign_has_budget = bool(reuse_check.get("body_has_campaign_budget"))
        if campaign_id and not reuse_check.get("checked"):
            campaign_has_budget = meta_campaign_has_campaign_budget(client, campaign_id)
        if campaign_id and campaign_has_budget:
            budget_level = "campaign"
            if hasattr(client, "update_campaign_bid_strategy"):
                bid_result = client.update_campaign_bid_strategy(campaign_id, "LOWEST_COST_WITHOUT_CAP", approved=approved)
                bid_ok = bid_result.get("returncode") in {0, None}
                steps.append({"step": "update_campaign_bid_strategy", "ok": bid_ok, "campaign_id": campaign_id, "result": bid_result})
                if not bid_ok:
                    return campaign_creation_failure_result(
                        path,
                        campaign,
                        client,
                        campaign_id,
                        "update_campaign_bid_strategy",
                        steps,
                        status_plan,
                        active_confirmed,
                        approved,
                        allow_cleanup=cleanup_incomplete_campaign_allowed(campaign, campaign_id, campaign_created_this_attempt, status_plan, active_confirmed),
                    )
    if not campaign_id:
        budget_currency = str(campaign.get("budget_currency") or "").strip().upper()
        campaign_daily_budget = meta_budget_api_amount(campaign.get("budget", {}).get("daily", 0), budget_currency) if budget_level == "campaign" else 0
        campaign_adset_budget_sharing = False if budget_level == "adset" else None
        campaign_result = client.create_campaign(
            client.config.ad_account_id,
            campaign.get("name", "New Campaign"),
            campaign_objective_for_social(campaign.get("objective"), campaign=campaign, ad_plan=ad_plan),
            campaign_daily_budget,
            status_plan.get("campaign", "PAUSED"),
            approved=approved,
            bid_strategy="LOWEST_COST_WITHOUT_CAP" if campaign_daily_budget else "",
            is_adset_budget_sharing_enabled=campaign_adset_budget_sharing,
        )
        campaign_id = social_id_from_result(campaign_result)
        steps.append({"step": "create_campaign", "ok": bool(campaign_id), "campaign_id": campaign_id, "status": status_plan.get("campaign", "PAUSED"), "result": campaign_result})
        if campaign_id:
            campaign_created_this_attempt = True
            persist_campaign_execution_state(path, campaign, {"campaign_id": campaign_id, "budget_level": budget_level})
    if not campaign_id:
        return {"ok": False, "mode": client.config.mode, "executed": True, "failed_step": "create_campaign", "steps": steps}
    adset_ids = []
    for adset in campaign.get("ad_sets", []):
        if budget_level == "campaign":
            daily_budget = 0
            lifetime_budget = 0
        else:
            budget_currency = str(campaign.get("budget_currency") or "").strip().upper()
            daily_budget = meta_budget_api_amount(adset.get("budget", 0) or budget_plan.get("adset_daily") or campaign.get("budget", {}).get("daily", 0), budget_currency)
            lifetime_budget = meta_budget_api_amount(adset.get("lifetime_budget", 0) or budget_plan.get("adset_lifetime") or 0, budget_currency)
        adset_budget_sharing = adset.get("is_adset_budget_sharing_enabled")
        if budget_level == "campaign":
            adset_budget_sharing = None
        elif adset_budget_sharing is None:
            adset_budget_sharing = False
        adset_targeting = dict(adset.get("targeting") or {})
        if adset.get("placements") is not None and not adset_targeting.get("placements"):
            adset_targeting["placements"] = adset.get("placements")
        nested_ads = [item for item in (adset.get("ads") or []) if isinstance(item, dict)]
        nested_ad = nested_ads[0] if nested_ads else {}
        adset_lead_form_id = (
            lead_gen_form_id_from_plan(adset)
            or lead_gen_form_id_from_plan(nested_ad)
            or lead_gen_form_id
        )
        adset_message_destination = (
            message_destination_from_plan(adset)
            or message_destination_from_plan(nested_ad)
            or message_destination
        )
        adset_phone_number_id = resolved_whatsapp_phone_number or whatsapp_phone_number_id_from_plan(adset, ad_plan, campaign, destination) or whatsapp_phone_number_id
        adset_application_id = application_id_from_plan(adset, nested_ad, ad_plan, campaign)
        adset_object_store_url = object_store_url_from_plan(adset, nested_ad, ad_plan, campaign)
        promoted_object = SocialFlowClient.normalize_promoted_object(adset.get("promoted_object") or {})
        if adset_message_destination:
            # Do not carry a pixel/custom event from a stale web-conversion
            # draft into a messaging ad set. Preserve only messaging object
            # fields and add the connected Page/WhatsApp number explicitly.
            # Meta's current promoted-object schema does not accept the
            # human-facing ``whatsapp_phone_number_id`` key on an ad set
            # (Graph returns "Invalid keys ... were found").  The Business
            # SDK exposes the canonical field as ``whatsapp_phone_number``.
            # Keep the product-facing name for compatibility, but translate
            # it exactly once at the Graph boundary.
            promoted_object = {
                key: value
                for key, value in promoted_object.items()
                if key in {"page_id", "whatsapp_phone_number", "whatsapp_phone_number_id", "instagram_profile_id"}
            }
            if promoted_object.get("whatsapp_phone_number_id") and not promoted_object.get("whatsapp_phone_number"):
                promoted_object["whatsapp_phone_number"] = promoted_object.pop("whatsapp_phone_number_id")
            if destination.get("page_id") and not promoted_object.get("page_id"):
                promoted_object["page_id"] = destination.get("page_id")
            if adset_message_destination == "WHATSAPP" and adset_phone_number_id:
                promoted_object["whatsapp_phone_number"] = adset_phone_number_id
            if adset_message_destination == "INSTAGRAM_DIRECT" and destination.get("instagram_actor_id"):
                promoted_object["instagram_profile_id"] = destination.get("instagram_actor_id")
        elif adset_lead_form_id and destination.get("page_id") and not promoted_object.get("page_id"):
            promoted_object = {**promoted_object, "page_id": destination.get("page_id")}
        elif campaign_objective_for_social(campaign.get("objective"), campaign=campaign, ad_plan=nested_ad or ad_plan) == "OUTCOME_APP_PROMOTION":
            promoted_object = {
                **promoted_object,
                "application_id": adset_application_id,
                "object_store_url": adset_object_store_url,
            }
        elif (
            campaign_objective_for_social(campaign.get("objective"), campaign=campaign, ad_plan=nested_ad or ad_plan)
            in {"OUTCOME_ENGAGEMENT", "OUTCOME_AWARENESS"}
            and destination.get("page_id")
            and not promoted_object.get("page_id")
        ):
            # Meta requires an object related to the selected outcome for
            # native engagement/awareness ads.  A connected Page is the
            # canonical promoted object; omitting it lets campaign/ad-set
            # creation succeed but rejects the final ad with subcode 1885154.
            promoted_object = {**promoted_object, "page_id": destination.get("page_id")}
        requested_targeting = targeting_for_social(adset_targeting)
        result = client.create_adset(
            campaign_id,
            adset.get("name", "Ad Set"),
            requested_targeting,
            daily_budget,
            status_plan.get("adset", adset.get("status", "PAUSED")),
            adset_optimization_goal_for_campaign(adset, campaign, adset_lead_form_id, adset_message_destination),
            promoted_object=promoted_object,
            billing_event=adset.get("billing_event") or "IMPRESSIONS",
            bidding=SocialFlowClient.normalize_bidding_config(adset.get("bidding") or {}),
            lifetime_budget_cents=lifetime_budget,
            start_time=adset.get("start_time") or "",
            end_time=adset.get("end_time") or "",
            is_adset_budget_sharing_enabled=adset_budget_sharing,
            # Meta lead-form creatives are an on-ad destination. If this is
            # omitted, Meta may create the campaign/ad set and creative but
            # reject the final ad with "lead form ... ON_AD destination".
            destination_type=(
                adset.get("destination_type")
                or ad_plan.get("destination_type")
                or (
                    "ON_AD"
                    if adset_lead_form_id
                    else "APP"
                    if adset_application_id
                    else SocialFlowClient.destination_type_for_message_destination(adset_message_destination)
                )
            ),
            approved=approved,
        )
        adset_id = social_id_from_result(result)
        adset_ids.append(adset_id)
        steps.append({"step": "create_adset", "ok": bool(adset_id), "adset_id": adset_id, "status": status_plan.get("adset", "PAUSED"), "result": result})
        if adset_id:
            persist_campaign_execution_state(path, campaign, {"campaign_id": campaign_id, "adset_ids": [value for value in adset_ids if value]})
        if not adset_id:
            return campaign_creation_failure_result(path, campaign, client, campaign_id, "create_adset", steps, status_plan, active_confirmed, approved, allow_cleanup=cleanup_incomplete_campaign_allowed(campaign, campaign_id, campaign_created_this_attempt, status_plan, active_confirmed))
        if targeting_needs_live_verification(requested_targeting):
            if hasattr(client, "adset_details"):
                verification_result = client.adset_details(adset_id)
                verification = verify_adset_targeting_result(requested_targeting, verification_result)
            else:
                verification = {
                    "ok": False,
                    "confirmed": False,
                    "source": "meta_live",
                    "reason": "adset_targeting_read_not_supported",
                    "requested_interest_ids": targeting_interest_ids(requested_targeting),
                    "requested_advantage_audience": targeting_advantage_value(requested_targeting),
                    "ui_confirmation": False,
                }
            steps.append({"step": "verify_adset_targeting", "ok": bool(verification.get("confirmed")), "adset_id": adset_id, "verification": verification})
            if not verification.get("confirmed"):
                return campaign_creation_failure_result(
                    path,
                    campaign,
                    client,
                    campaign_id,
                    "verify_adset_targeting",
                    steps,
                    status_plan,
                    active_confirmed,
                    approved,
                    allow_cleanup=cleanup_incomplete_campaign_allowed(campaign, campaign_id, campaign_created_this_attempt, status_plan, active_confirmed),
                    adset_ids=[value for value in adset_ids if value],
                    targeting_verification=verification,
                )
    # A campaign with explicit nested ads must execute that full matrix now.
    # The legacy code below is intentionally retained for one-ad campaigns;
    # this branch prevents it from silently binding every creative to the
    # first ad set.
    explicit_ad_matrix = any(
        isinstance(item, dict) and len(item.get("ads") or []) > 0
        for item in (campaign.get("ad_sets") or [])
    )
    if explicit_ad_matrix and (
        len(campaign.get("ad_sets") or []) > 1
        or sum(len(item.get("ads") or []) for item in campaign.get("ad_sets") if isinstance(item, dict)) > 1
    ):
        multi_result = execute_multi_adset_native_stack(
            path,
            campaign,
            client,
            destination,
            campaign_id,
            adset_ids,
            status_plan,
            active_confirmed,
            approved,
            campaign_created_this_attempt,
            steps,
            resolved_whatsapp_phone_number=resolved_whatsapp_phone_number,
        )
        if multi_result is not None:
            if multi_result.get("ok"):
                mark_asset_files_retained(
                    [
                        ad.get("creative_image_path")
                        for stored_set in (campaign.get("ad_sets") or [])
                        for ad in (stored_set.get("ads") or [])
                        if isinstance(ad, dict)
                    ],
                    reason="multi_ad_campaign_created",
                    meta={"campaign_id": campaign_id, "ad_ids": multi_result.get("ad_ids", []), "final_status": "PAUSED"},
                )
            return multi_result

    target_adset_id = adset_ids[0] if adset_ids else ""
    prefilled_message = str(ad_plan.get("prefilled_message") or "").strip() if message_destination else ""
    welcome_message = str(ad_plan.get("welcome_message") or ad_plan.get("initial_business_message") or "").strip()
    link = native_campaign_creative_link(campaign, ad_plan, destination, message_destination, lead_gen_form_id)
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
        ad_plan["deferred_video_path"] = ad_plan.get("deferred_video_path") or ad_plan.get("video_path") or ""
        ad_plan["video_url"] = ""
        ad_plan["video_path"] = ""
        ad_plan["video_id"] = ""
        ad_plan["final_status"] = "PAUSED"
        ad_plan["active_spend_confirmed"] = False
        if not static_creative_source_available(ad_plan):
            placeholder_image_path = ensure_placeholder_image(campaign)
            ad_plan["creative_image_path"] = placeholder_image_path
        elif ad_plan.get("creative_image_path"):
            placeholder_image_path = ad_plan.get("creative_image_path")
    # Existing Page posts remain supported only when the buyer explicitly
    # selected one. Admira never creates a dark/unpublished post for an ad.
    object_story_id = str(ad_plan.get("object_story_id") or "").strip()
    media = prepare_native_ad_media(client, ad_plan, approved=approved)
    steps.extend({**operation, "route": "native_inline_ads_app"} for operation in (media.get("operations") or []))
    if not media.get("ok"):
        return campaign_creation_failure_result(
            path, campaign, client, campaign_id, media.get("failed_step") or "prepare_creative_media", steps,
            status_plan, active_confirmed, approved,
            allow_cleanup=cleanup_incomplete_campaign_allowed(campaign, campaign_id, campaign_created_this_attempt, status_plan, active_confirmed),
            adset_ids=adset_ids, missing_requirements=media.get("missing_requirements") or [],
        )

    creative_args = (
        client.config.ad_account_id,
        f"{campaign.get('name', 'New Campaign')} - Creative",
        destination.get("page_id", ""),
        link,
        body_text,
        headline,
        media.get("image_hash") or "",
        native_campaign_cta(ad_plan, link, message_destination, lead_gen_form_id),
        destination.get("instagram_actor_id", ""),
    )
    creative_kwargs = dict(
        object_story_spec=ad_plan.get("object_story_spec") or {},
        image_url=ad_plan.get("image_url") or "",
        video_id=media.get("video_id") or "",
        cta_link=ad_plan.get("cta_link") or "",
        object_story_id=object_story_id,
        lead_gen_form_id=lead_gen_form_id,
        prefilled_message=prefilled_message,
        welcome_message=welcome_message,
        message_destination=message_destination,
        approved=approved,
    )
    creative_id, creative_result, creative_token_source, fallback_capability = create_native_ad_creative(
        client, creative_args, creative_kwargs
    )
    steps.append({
        "step": "create_creative", "ok": bool(creative_id), "creative_id": creative_id,
        "route": "existing_page_post" if object_story_id else "native_inline_ads_app",
        "creative_token_source": creative_token_source, "fallback_capability": fallback_capability,
        "result": creative_result,
    })
    if not creative_id:
        return campaign_creation_failure_result(path, campaign, client, campaign_id, "create_creative", steps, status_plan, active_confirmed, approved, allow_cleanup=cleanup_incomplete_campaign_allowed(campaign, campaign_id, campaign_created_this_attempt, status_plan, active_confirmed), adset_ids=adset_ids)

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
            object_story_id=object_story_id,
            prefer_object_story_ad=(not has_explicit_website_adset and not message_destination and bool(object_story_id)),
        )
        ad_id = social_id_from_result(ad_result)
        ad_ids.append(ad_id)
        steps.append({"step": "create_ad", "ok": bool(ad_id), "ad_id": ad_id, "final_status": "PAUSED" if placeholder_static else status_plan.get("ad", final_status), "result": ad_result})
        if not ad_id:
            return campaign_creation_failure_result(path, campaign, client, campaign_id, "create_ad", steps, status_plan, active_confirmed, approved, allow_cleanup=cleanup_incomplete_campaign_allowed(campaign, campaign_id, campaign_created_this_attempt, status_plan, active_confirmed), adset_ids=adset_ids, creative_id=creative_id, ad_ids=[value for value in ad_ids if value])
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
    elif command[0] == "delete":
        result = client.delete(command[1], command[2], approved=True)
    elif command[0] == "create_campaign":
        result = execute_campaign_creation(command[1], client, approved=True, prior_result=item.get("result"))
    elif command[0] == "create_lead_form":
        result = execute_lead_form_creation(command[1], client, approved=True)
    elif command[0] == "creative_upload":
        result = execute_upload_payload(command[1], approved=True)
    elif command[0] == "publish_social_post":
        result = publish_approved_social_post(command[1], client)
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
        actions = row.get("actions") if isinstance(row.get("actions"), list) else []
        if not actions and isinstance(row.get("conversions"), list):
            actions = row.get("conversions")
        action_values = row.get("action_values") if isinstance(row.get("action_values"), list) else []
        explicit_conversions = nested_number(row, ["conversions", "purchases", "results"])
        conversions = int(conversion_result_value(actions) if actions else explicit_conversions)
        explicit_revenue = nested_number(row, ["revenue", "purchase_roas_value", "conversion_value", "value"])
        revenue = (
            deduplicated_alias_value(action_values, PURCHASE_VALUE_ACTIONS)
            if action_values
            else explicit_revenue or float(prev.get("revenue", 0) or 0)
        )
        funnel = canonical_funnel_values(actions) if actions else prev.get("funnel", {})
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
            "funnel": funnel,
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
            "label": f"Paused {len(auto_paused)} clear bleeder(s) after approval.",
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
            may_execute = False
            if may_execute and config.license_required_for_live and not license_status(config).get("valid"):
                may_execute = False
                item["guardrail_reason"] = "license_required_for_live"
            if not may_execute:
                item.setdefault("guardrail_reason", "shadow_mode" if recommendation.get("shadow_mode", True) else "approval_required")
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
