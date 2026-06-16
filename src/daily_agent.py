#!/usr/bin/env python3
"""Daily runner and approval executor for Admira IA."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from budget_optimizer import BudgetOptimizer, OptimizationStrategy, PerformanceMetrics
from creative_refresh import campaigns_needing_refresh, generate_creative_refresh, mark_asset_files_retained, recent_creative_refreshes
from decision_memory import load_profitability_rules, recommendation_decision_evidence, record_daily_decision_memory
from graph_executor import execute_upload_payload
from license import license_status
from local_store import now_iso, read_json, write_json
from meta_upload import recent_uploads, stage_upload
from product_config import ROOT_DIR, load_config
from security import redact_payload
from setup_status import build_setup_status
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


def load_metrics():
    metrics = read_json(METRICS_FILE, {"timestamp": now_iso(), "campaigns": []})
    metrics["campaigns"] = [enrich_campaign(c) for c in metrics.get("campaigns", [])]
    metrics["summary"] = build_summary(metrics["campaigns"])
    return metrics


def save_metrics(metrics):
    metrics["timestamp"] = now_iso()
    metrics["campaigns"] = [enrich_campaign(c) for c in metrics.get("campaigns", [])]
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
    campaign["cpa"] = (spend / conversions) if conversions else float(campaign.get("cpa", 0) or 9999)
    campaign["cpc"] = (spend / clicks) if clicks else float(campaign.get("cpc", 0))
    campaign["roas"] = (revenue / spend) if spend else float(campaign.get("roas", 0))
    campaign.setdefault("previous_ctr", campaign["ctr"] * 1.05)
    campaign.setdefault("previous_cpc", campaign["cpc"] * 0.92 if campaign["cpc"] else 0)
    campaign["health"] = classify_campaign(campaign)
    return campaign


def classify_campaign(campaign):
    config = load_config()
    ctr_drop = pct_change(campaign.get("ctr"), campaign.get("previous_ctr"))
    cpc_rise = pct_change(campaign.get("cpc"), campaign.get("previous_cpc"))
    if campaign.get("status") == "paused":
        return "paused"
    if campaign.get("frequency", 0) > 3 or ctr_drop <= -20 or cpc_rise >= 30:
        return "fatigue"
    if campaign.get("roas", 0) >= 3 and campaign.get("cpa", 9999) <= config.target_cpa:
        return "winning"
    if campaign.get("roas", 0) < 1.2 or campaign.get("cpa", 0) > config.target_cpa * config.high_cpa_multiplier:
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
    optimizer = BudgetOptimizer()
    recommendations = []
    for campaign in campaigns:
        metrics = PerformanceMetrics(
            spend=float(campaign.get("spend", 0)),
            impressions=int(campaign.get("impressions", 0)),
            clicks=int(campaign.get("clicks", 0)),
            conversions=int(campaign.get("conversions", 0)),
            revenue=float(campaign.get("revenue", 0)),
            cost_per_result=float(campaign.get("cpa", 0)),
            roas=float(campaign.get("roas", 0)),
        )
        current = float(campaign.get("daily_budget", 100))
        rec = optimizer.calculate_optimal_budget(metrics, current, OptimizationStrategy.PERFORMANCE_BASED)
        change = rec.recommended_budget - current
        change_pct = (change / current * 100) if current else 100
        recommendation = {
            "id": f"budget_{campaign.get('id')}",
            "type": "budget_change",
            "campaign_id": campaign.get("id"),
            "target_type": campaign.get("target_type", "adset"),
            "target_id": campaign.get("target_id", campaign.get("id")),
            "campaign_name": campaign.get("name"),
            "current_budget": money(current),
            "recommended_budget": money(rec.recommended_budget),
            "change_pct": round(change_pct, 1),
            "requires_approval": abs(change_pct) > config.approval_required_over_pct,
            "reason": rec.reasoning,
            "health": campaign.get("health"),
        }
        recommendation["decision_evidence"] = recommendation_decision_evidence(campaign, recommendation, rules)
        recommendations.append(recommendation)
    return recommendations


def fatigue_items(campaigns):
    items = []
    for campaign in campaigns:
        ctr_drop = pct_change(campaign.get("ctr"), campaign.get("previous_ctr"))
        cpc_rise = pct_change(campaign.get("cpc"), campaign.get("previous_cpc"))
        reasons = []
        if campaign.get("frequency", 0) > 3:
            reasons.append(f"frequency {campaign.get('frequency'):.1f}")
        if ctr_drop <= -20:
            reasons.append(f"CTR {abs(ctr_drop):.0f}% down")
        if cpc_rise >= 30:
            reasons.append(f"CPC {cpc_rise:.0f}% up")
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


def campaign_objective_for_social(objective):
    mapping = {
        "PURCHASES": "OUTCOME_SALES",
        "CONVERSIONS": "OUTCOME_SALES",
        "SALES": "OUTCOME_SALES",
        "LEADS": "LEAD_GENERATION",
        "LEAD_GENERATION": "LEAD_GENERATION",
    }
    return mapping.get(str(objective or "").upper(), "OUTCOME_SALES")


def targeting_for_social(targeting):
    targeting = targeting or {}
    age_range = targeting.get("age_range") or {}
    countries = [str(item).upper() for item in targeting.get("locations", ["US"]) if item]
    meta_targeting = targeting.get("meta_targeting") or {}
    geo_locations = {"countries": countries or ["US"]}
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
    return spec


def execute_campaign_creation(path, client, approved=False):
    campaign = read_json(Path(path), {})
    if not campaign:
        return {"ok": False, "error": "Campaign file missing or empty", "path": path}
    ad_config = read_json(AD_CONFIG_FILE, {})
    destination = ad_config.get("creative", {}).get("destination", {})
    ad_plan = campaign.get("ad") or {}
    final_status = str(ad_plan.get("final_status") or "PAUSED").upper()
    if final_status not in {"PAUSED", "ACTIVE"}:
        final_status = "PAUSED"
    missing = []
    if not client.config.ad_account_id:
        missing.append("META_AD_ACCOUNT_ID")
    if not destination.get("page_id"):
        missing.append("Facebook Page ID")
    if not (ad_plan.get("landing_url") or destination.get("url")):
        missing.append("landing URL")
    if not ad_plan.get("creative_image_path"):
        missing.append("creative image path")
    elif not Path(ad_plan.get("creative_image_path")).exists():
        missing.append(f"creative image file missing: {ad_plan.get('creative_image_path')}")
    if final_status == "ACTIVE" and not ad_plan.get("active_spend_confirmed"):
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
                "will_create_ad": True,
            },
        }
    campaign_result = client.create_campaign(
        client.config.ad_account_id,
        campaign.get("name", "New Campaign"),
        campaign_objective_for_social(campaign.get("objective")),
        int(float(campaign.get("budget", {}).get("daily", 0) or 0) * 100),
        "PAUSED",
        approved=approved,
    )
    campaign_id = social_id_from_result(campaign_result)
    steps = [{"step": "create_campaign_paused", "ok": bool(campaign_id), "campaign_id": campaign_id, "result": campaign_result}]
    if not campaign_id:
        return {"ok": False, "mode": client.config.mode, "executed": True, "failed_step": "create_campaign", "steps": steps}
    adset_ids = []
    for adset in campaign.get("ad_sets", []):
        daily_budget = int(float(adset.get("budget", 0) or campaign.get("budget", {}).get("daily", 0) or 0) * 100)
        result = client.create_adset(campaign_id, adset.get("name", "Ad Set"), targeting_for_social(adset.get("targeting")), daily_budget, "PAUSED", approved=approved)
        adset_id = social_id_from_result(result)
        adset_ids.append(adset_id)
        steps.append({"step": "create_adset_paused", "ok": bool(adset_id), "adset_id": adset_id, "result": result})
        if not adset_id:
            return {"ok": False, "mode": client.config.mode, "executed": True, "campaign_id": campaign_id, "failed_step": "create_adset", "steps": steps}
    target_adset_id = adset_ids[0] if adset_ids else ""
    upload_result = client.upload_image(client.config.ad_account_id, ad_plan.get("creative_image_path"), approved=approved)
    image_hash = None
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

    creative_result = client.create_creative(
        client.config.ad_account_id,
        f"{campaign.get('name', 'New Campaign')} - Creative",
        destination.get("page_id", ""),
        ad_plan.get("landing_url") or destination.get("url", ""),
        ad_plan.get("primary_text") or f"Conoce {campaign.get('name', 'esta oferta')}.",
        ad_plan.get("headline") or campaign.get("name", "Nueva oferta"),
        image_hash,
        ad_plan.get("cta", "LEARN_MORE"),
        destination.get("instagram_actor_id", ""),
        approved=approved,
    )
    creative_id = social_id_from_result(creative_result)
    steps.append({"step": "create_creative", "ok": bool(creative_id), "creative_id": creative_id, "result": creative_result})
    if not creative_id:
        return {"ok": False, "mode": client.config.mode, "executed": True, "campaign_id": campaign_id, "adset_ids": adset_ids, "failed_step": "create_creative", "steps": steps}

    ad_result = client.create_ad(target_adset_id, f"{campaign.get('name', 'New Campaign')} - Ad", creative_id, final_status, approved=approved)
    ad_id = social_id_from_result(ad_result)
    steps.append({"step": "create_ad", "ok": bool(ad_id), "ad_id": ad_id, "final_status": final_status, "result": ad_result})
    final = {"ok": bool(ad_id), "mode": client.config.mode, "executed": True, "campaign_id": campaign_id, "adset_ids": adset_ids, "creative_id": creative_id, "ad_id": ad_id, "final_status": final_status, "steps": steps}
    if final["ok"]:
        mark_asset_files_retained(
            [ad_plan.get("creative_image_path")],
            reason="campaign_ad_created",
            meta={"campaign_id": campaign_id, "creative_id": creative_id, "ad_id": ad_id, "final_status": final_status},
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
        result = execute_campaign_creation(command[1], client, approved=True)
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
        "connector": "social_cli",
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


def build_manager_message(metrics, winners, losers, fatigue, proposed_pauses, action_summary, trend_context):
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


def build_brief(metrics, recommendations, auto_paused, fatigue, proposed_pauses=None, creative_refreshes=None):
    summary = metrics.get("summary", {})
    campaigns = metrics.get("campaigns", [])
    proposed_pauses = proposed_pauses or []
    winners = sorted([c for c in campaigns if c.get("health") == "winning"], key=lambda c: c.get("roas", 0), reverse=True)
    losers = sorted([c for c in campaigns if c.get("health") == "losing"], key=lambda c: c.get("roas", 0))
    approval_count = len(read_json(PENDING_FILE, []))
    action_summary = build_action_summary(recommendations, auto_paused, proposed_pauses, fatigue, creative_refreshes)
    trend_context = build_trend_context(metrics)
    message = build_manager_message(metrics, winners, losers, fatigue, proposed_pauses, action_summary, trend_context)
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
    ]
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
    return {
        "generated_at": now_iso(),
        "summary": summary,
        "five_questions": {
            "am_i_on_track": lines[0],
            "whats_running": f"{summary.get('active_campaigns', 0)} campañas activas",
            "hows_performance": f"{summary.get('overall_roas', 0):.2f}x retorno, {format_metric_value('overall_cpa', summary.get('overall_cpa', 0))} costo por resultado",
            "winning_losing": lines[-1] if winners or losers else "Todavía no hay ganadora o perdedora clara.",
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
    }


def run_daily():
    config = load_config()
    client = SocialFlowClient(config)
    metrics = load_metrics()
    if config.ad_account_id or config.meta_access_token:
        metrics = pull_live_metrics(metrics, client)

    recommendations = calculate_recommendations(metrics.get("campaigns", []))
    auto_paused = []
    proposed_pauses = []
    if config.auto_pause_enabled:
        for campaign in metrics.get("campaigns", []):
            should_pause = campaign.get("status") == "active" and (
                campaign.get("cpa", 0) > config.target_cpa * config.high_cpa_multiplier
                or (campaign.get("spend", 0) > config.zero_conversion_spend and campaign.get("conversions", 0) == 0)
            )
            if not should_pause:
                continue
            item = {
                "approval_id": f"approval_pause_{campaign.get('id')}",
                "campaign_id": campaign.get("id"),
                "target_type": campaign.get("target_type", "adset"),
                "target_id": campaign.get("target_id", campaign.get("id")),
                "name": campaign.get("name"),
                "spend": campaign.get("spend", 0),
                "reason": "high CPA or spend with zero conversions",
            }
            may_execute = (
                config.autonomy_mode == "autopilot"
                and config.live
                and config.live_actions_enabled
                and float(campaign.get("spend", 0) or 0) <= config.auto_pause_max_spend
            )
            if may_execute and config.license_required_for_live and not license_status(config).get("valid"):
                may_execute = False
                item["guardrail_reason"] = "license_required_for_live"
            if not may_execute:
                item.setdefault("guardrail_reason", "supervised_or_outside_autopilot_rules")
                if add_pending("pause_campaign", item):
                    proposed_pauses.append(item)
                continue
            result = client.pause(item["target_type"], item["target_id"])
            item["result"] = result
            if result.get("executed") and result.get("returncode") == 0:
                campaign["status"] = "paused"
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
            creative_refreshes.append({"id": plan["id"], "campaign": plan["campaign"], "manifest_path": str(manifest_path)})
        if creative_refreshes:
            log_action("creative_refresh", {"items": creative_refreshes}, "generated")

    for rec in recommendations:
        if rec.get("requires_approval"):
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
    brief = build_brief(metrics, recommendations, auto_paused, fatigue, proposed_pauses, creative_refreshes)
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
    sub.add_parser("status", help="Show agent configuration and social-cli status")
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
