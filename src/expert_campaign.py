#!/usr/bin/env python3
"""Expert campaign configuration helpers.

These functions normalize the richer campaign fields Hermes may propose before
the backend stages or executes a Meta campaign. They intentionally keep Meta
Marketing API controls behind allowlisted, typed structures.
"""
import json
import re
import unicodedata
from datetime import datetime


ACTIVE_STATUSES = {"ACTIVE", "PAUSED"}
BILLING_EVENTS = {"IMPRESSIONS", "LINK_CLICKS", "THRUPLAY", "APP_INSTALLS", "POST_ENGAGEMENT"}
DEFAULT_BILLING_EVENT = "IMPRESSIONS"
BID_STRATEGY_ALIASES = {
    "LOWEST_COST": "LOWEST_COST_WITHOUT_CAP",
    "LOWEST_COST_NO_CAP": "LOWEST_COST_WITHOUT_CAP",
    "WITHOUT_CAP": "LOWEST_COST_WITHOUT_CAP",
    "BID_CAP": "LOWEST_COST_WITH_BID_CAP",
    "CAP": "LOWEST_COST_WITH_BID_CAP",
    "TARGET": "TARGET_COST",
}
BID_AMOUNT_REQUIRED_STRATEGIES = {"LOWEST_COST_WITH_BID_CAP", "TARGET_COST", "COST_CAP"}

TARGETING_LIST_FIELDS = {
    "device_platforms",
    "user_os",
    "user_device",
    "wireless_carrier",
    "publisher_platforms",
    "facebook_positions",
    "instagram_positions",
    "messenger_positions",
    "audience_network_positions",
    "threads_positions",
}


def parse_jsonish(value, default=None):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return default
    return default


def number(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def money(value, default=0.0):
    parsed = number(value, default)
    return round(max(parsed or 0.0, 0.0), 2)


def intish(value, default=0):
    parsed = number(value)
    if parsed is None:
        return default
    return int(parsed)


def boolish(value):
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on", "si", "sí"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def clean_status(value, default="PAUSED"):
    status = str(value or default or "PAUSED").strip().upper()
    return status if status in ACTIVE_STATUSES else default


def normalize_status_plan(payload, final_status, active_confirmed):
    default_status = "ACTIVE" if final_status == "ACTIVE" else "PAUSED"
    plan = {
        "campaign": clean_status(payload.get("campaign_status"), default_status),
        "adset": clean_status(payload.get("adset_status") or payload.get("ad_set_status"), default_status),
        "ad": clean_status(payload.get("ad_status"), final_status),
    }
    if not active_confirmed:
        plan = {key: "PAUSED" if value == "ACTIVE" else value for key, value in plan.items()}
    return plan


def requires_active_confirmation(payload, final_status):
    values = [
        final_status,
        payload.get("campaign_status"),
        payload.get("adset_status") or payload.get("ad_set_status"),
        payload.get("ad_status"),
    ]
    return any(clean_status(value, "PAUSED") == "ACTIVE" for value in values)


def normalize_billing_event(value):
    event = str(value or DEFAULT_BILLING_EVENT).strip().upper()
    event = event.replace(" ", "_").replace("-", "_")
    return event if event in BILLING_EVENTS else DEFAULT_BILLING_EVENT


def normalize_bid_strategy(value):
    strategy = str(value or "").strip().upper().replace(" ", "_").replace("-", "_")
    return BID_STRATEGY_ALIASES.get(strategy, strategy)


def sanitize_bidding(bidding):
    bidding = dict(bidding or {}) if isinstance(bidding, dict) else {}
    strategy = normalize_bid_strategy(bidding.get("bid_strategy"))
    bid_amount = intish(bidding.get("bid_amount"), 0)
    clean = {}
    if strategy:
        if strategy in BID_AMOUNT_REQUIRED_STRATEGIES and bid_amount <= 0:
            strategy = "LOWEST_COST_WITHOUT_CAP"
        clean["bid_strategy"] = strategy
    elif bid_amount > 0:
        clean["bid_strategy"] = "LOWEST_COST_WITH_BID_CAP"
    if bid_amount > 0 and clean.get("bid_strategy") in BID_AMOUNT_REQUIRED_STRATEGIES:
        clean["bid_amount"] = bid_amount
    return clean


def normalize_bidding(payload):
    raw = parse_jsonish(payload.get("bidding") or payload.get("bidding_json"), {})
    bidding = dict(raw) if isinstance(raw, dict) else {}
    bid_strategy = normalize_bid_strategy(payload.get("bid_strategy") or payload.get("bid_strategy_type") or bidding.get("bid_strategy"))
    if bid_strategy:
        bidding["bid_strategy"] = bid_strategy
    bid_amount = intish(payload.get("bid_amount") or payload.get("bid_amount_cents") or bidding.get("bid_amount"), 0)
    if bid_amount > 0:
        bidding["bid_amount"] = bid_amount
    return sanitize_bidding(bidding)


def normalize_schedule(payload):
    return {
        "start_time": normalize_iso_time(payload.get("start_time") or payload.get("adset_start_time")),
        "end_time": normalize_iso_time(payload.get("end_time") or payload.get("adset_end_time")),
    }


def normalize_iso_time(value):
    text = str(value or "").strip()
    if not text:
        return ""
    # Accept ISO-ish strings; do not convert timezone here because Meta expects an ISO value.
    candidate = text.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(candidate)
        return text
    except ValueError:
        return ""


def normalize_budget_plan(payload, default_daily=50.0):
    campaign_daily = money(payload.get("daily_budget"), default_daily)
    total_budget = money(payload.get("total_budget"), campaign_daily * 30)
    adset_daily = money(payload.get("adset_daily_budget"), campaign_daily)
    adset_lifetime = money(payload.get("adset_lifetime_budget") or payload.get("lifetime_budget"), 0)
    target_cost = money(payload.get("target_cpa") or payload.get("target_cpl") or payload.get("target_cost_per_result"), 0)
    concurrent = max(intish(payload.get("concurrent_creatives") or payload.get("creative_variations"), 1), 1)
    per_variant_daily = round(campaign_daily / concurrent, 2) if concurrent else campaign_daily
    warnings = []
    if target_cost > 0:
        expected_daily_events = round(campaign_daily / target_cost, 2)
        if expected_daily_events < 1:
            warnings.append(f"Daily budget is below 1 expected result/day at target cost {target_cost:g}.")
        elif expected_daily_events < 2:
            warnings.append(f"Daily budget may learn slowly: about {expected_daily_events:g} expected results/day.")
        if per_variant_daily < target_cost:
            warnings.append(f"Concurrent creative test may be starved: about {per_variant_daily:g} per variant/day.")
    else:
        expected_daily_events = None
    return {
        "campaign_daily": campaign_daily,
        "total_budget": total_budget,
        "adset_daily": adset_daily,
        "adset_lifetime": adset_lifetime,
        "target_cost": target_cost,
        "concurrent_creatives": concurrent,
        "per_variant_daily": per_variant_daily,
        "expected_daily_events": expected_daily_events,
        "warnings": warnings,
    }


SUCCESS_METRIC_ALIASES = {
    "roas": ("roas", "return on ad spend", "retorno", "retorno publicitario"),
    "cost_per_purchase": ("cost per purchase", "costo por compra", "coste por compra", "purchase cost", "cpa compra", "cpa"),
    "cost_per_initiate_checkout": ("cost per initiate checkout", "costo por initiate checkout", "costo por iniciar checkout", "initiate checkout", "iniciar checkout", "checkout"),
    "cost_per_lead": ("cost per lead", "costo por lead", "cpl", "lead cost"),
    "cost_per_qualified_lead": ("qualified lead", "lead calificado", "costo por lead calificado", "qualified contact"),
    "cost_per_message": ("cost per message", "costo por mensaje", "conversation cost", "costo por conversación", "costo por conversacion"),
    "cost_per_booking": ("cost per booking", "costo por reserva", "booking cost", "appointment cost", "costo por cita"),
    "purchase_volume": ("purchase volume", "compras", "ventas", "sales volume"),
}


def normalized_metric_text(value):
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text)


def canonical_success_metric(value):
    text = normalized_metric_text(value)
    for canonical, aliases in SUCCESS_METRIC_ALIASES.items():
        if canonical in text or any(normalized_metric_text(alias) in text for alias in aliases):
            return canonical
    safe = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return safe[:80] or "custom_metric"


def normalize_success_metric_item(item, rank):
    if isinstance(item, dict):
        raw_metric = item.get("metric") or item.get("name") or item.get("label") or item.get("result") or item.get("event")
        target = str(item.get("target") or item.get("goal") or item.get("desired_value") or "").strip()
        notes = str(item.get("notes") or item.get("why") or item.get("description") or "").strip()
    else:
        raw_metric = str(item or "").strip()
        target = ""
        notes = ""
    if not raw_metric:
        return {}
    label = str(raw_metric).strip()
    return {
        "rank": int(rank),
        "metric": canonical_success_metric(label),
        "label": label[:120],
        "target": target[:120],
        "notes": notes[:240],
    }


def success_metric_candidates_from_text(text):
    lowered = normalized_metric_text(text)
    candidates = []
    ordered_patterns = [
        ("ROAS", ("roas", "retorno")),
        ("cost per purchase", ("cost per purchase", "costo por compra", "coste por compra", "cpa")),
        ("cost per initiate checkout", ("initiate checkout", "iniciar checkout", "checkout")),
        ("cost per lead", ("cost per lead", "costo por lead", "cpl")),
        ("cost per qualified lead", ("qualified lead", "lead calificado")),
        ("cost per message", ("cost per message", "costo por mensaje", "costo por conversación", "costo por conversacion")),
        ("cost per booking", ("cost per booking", "costo por reserva", "costo por cita")),
    ]
    for label, tokens in ordered_patterns:
        if any(normalized_metric_text(token) in lowered for token in tokens) and label not in candidates:
            candidates.append(label)
    return candidates


def inferred_success_metrics_for_objective(objective):
    normalized = normalized_metric_text(objective)
    if any(token in normalized for token in ("lead", "contact", "formulario")):
        defaults = ["cost per qualified lead", "cost per lead", "lead-to-booking rate"]
    elif any(token in normalized for token in ("message", "mensaje", "whatsapp", "conversation")):
        defaults = ["cost per qualified conversation", "cost per booking", "conversation-to-purchase rate"]
    else:
        defaults = ["ROAS", "cost per purchase", "cost per initiate checkout"]
    return [
        {**normalize_success_metric_item(item, index), "source": "inferred", "needs_confirmation": True}
        for index, item in enumerate(defaults, start=1)
    ]


def normalize_success_metrics(payload):
    raw = None
    for key in (
        "success_metrics",
        "success_metrics_json",
        "priority_metrics",
        "priority_results",
        "key_results",
        "important_results",
        "main_results",
        "desired_results",
        "top_results",
        "top_3_results",
        "kpis",
        "primary_metrics",
        "conversion_results",
    ):
        if payload.get(key):
            raw = parse_jsonish(payload.get(key), payload.get(key))
            break
    if raw in (None, ""):
        scalar_items = [
            payload.get("primary_success_metric") or payload.get("primary_kpi") or payload.get("primary_result"),
            payload.get("secondary_success_metric") or payload.get("secondary_kpi") or payload.get("secondary_result"),
            payload.get("tertiary_success_metric") or payload.get("tertiary_kpi") or payload.get("tertiary_result"),
        ]
        raw = [item for item in scalar_items if str(item or "").strip()]
    if isinstance(raw, str):
        candidates = success_metric_candidates_from_text(raw)
        raw = candidates or [part.strip() for part in re.split(r"[\n,;]+", raw) if part.strip()]
    if isinstance(raw, dict):
        raw = list(raw.values())
    metrics = []
    seen = set()
    for item in raw if isinstance(raw, list) else []:
        normalized = normalize_success_metric_item(item, len(metrics) + 1)
        metric = normalized.get("metric")
        if not metric or metric in seen:
            continue
        normalized["source"] = "buyer"
        normalized["needs_confirmation"] = False
        metrics.append(normalized)
        seen.add(metric)
        if len(metrics) >= 3:
            break
    if metrics:
        return {"items": metrics, "source": "buyer", "needs_confirmation": False}
    inferred = inferred_success_metrics_for_objective(payload.get("objective") or payload.get("campaign_objective") or payload.get("goal"))
    return {"items": inferred, "source": "inferred", "needs_confirmation": True}


def id_objects(value):
    raw = parse_jsonish(value, value)
    if raw in (None, ""):
        return []
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",") if part.strip()]
    result = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict):
            item_id = str(item.get("id") or item.get("audience_id") or "").strip()
            name = str(item.get("name") or "").strip()
        else:
            item_id = str(item or "").strip()
            name = ""
        if item_id:
            entry = {"id": item_id}
            if name:
                entry["name"] = name
            result.append(entry)
    return result


def string_list(value):
    raw = parse_jsonish(value, value)
    if raw in (None, ""):
        return []
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",") if part.strip()]
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item or "").strip()]


def merge_expert_targeting(audience, payload):
    targeting = dict(audience or {})
    custom = id_objects(payload.get("custom_audiences") or payload.get("custom_audiences_json"))
    if custom:
        targeting["custom_audiences"] = custom
    excluded_custom = id_objects(payload.get("excluded_custom_audiences") or payload.get("excluded_custom_audiences_json"))
    if excluded_custom:
        targeting["excluded_custom_audiences"] = excluded_custom
    excluded_interests = id_objects(payload.get("excluded_interests") or payload.get("excluded_interests_json"))
    if excluded_interests:
        targeting["excluded_interests"] = excluded_interests
    raw_exclusions = parse_jsonish(payload.get("exclusions") or payload.get("exclusions_json"), {})
    if isinstance(raw_exclusions, dict) and raw_exclusions:
        targeting["exclusions"] = raw_exclusions
    flexible_spec = parse_jsonish(payload.get("flexible_spec") or payload.get("flexible_spec_json"), [])
    if isinstance(flexible_spec, list) and flexible_spec:
        targeting["flexible_spec"] = flexible_spec
    genders = string_list(payload.get("genders"))
    if genders:
        numeric = [int(item) for item in genders if str(item).isdigit()]
        targeting["genders"] = numeric or genders
    for key in TARGETING_LIST_FIELDS:
        values = string_list(payload.get(key))
        if values:
            targeting[key] = values
    return targeting


def normalize_creative_controls(payload):
    object_story_spec = parse_jsonish(payload.get("object_story_spec") or payload.get("object_story_spec_json"), {})
    return {
        "object_story_spec": object_story_spec if isinstance(object_story_spec, dict) and object_story_spec else {},
        "image_hash": str(payload.get("image_hash") or "").strip(),
        "image_url": str(payload.get("image_url") or "").strip(),
        "video_url": str(payload.get("video_url") or "").strip(),
        "cta_link": str(payload.get("cta_link") or payload.get("call_to_action_link") or "").strip(),
        "format": str(payload.get("creative_format") or payload.get("format") or "").strip().lower(),
    }


def creative_source_available(ad_plan):
    return any(
        ad_plan.get(key)
        for key in ("creative_image_path", "image_hash", "image_url", "video_url", "object_story_spec")
    )


def creative_format_review(ad_plan, placement_config):
    placements = []
    if isinstance(placement_config, dict):
        placements = placement_config.get("manual") or []
    selected = {str(item).upper() for item in placements}
    fmt = str(ad_plan.get("format") or ad_plan.get("creative_format") or "").lower()
    has_vertical = bool(ad_plan.get("video_url")) or "vertical" in fmt or "reel" in fmt or "story" in fmt or "9:16" in fmt
    warnings = []
    if any("REELS" in item or "STORIES" in item or "STORY" in item for item in selected) and not has_vertical:
        warnings.append("Stories/Reels placements need a vertical-friendly asset; prepare a 9:16 variant before relying on them.")
    if any("FEED" in item for item in selected) and "vertical_only" in fmt:
        warnings.append("Feed placements may need a square/feed-safe crop or separate feed asset.")
    status = "warn" if warnings else "ok"
    return {"status": status, "warnings": warnings, "format": fmt or "unspecified", "placements": list(selected)}


def campaign_preview(campaign):
    ad_sets = campaign.get("ad_sets") or []
    ad_set = ad_sets[0] if ad_sets else {}
    ad = campaign.get("ad") or {}
    return {
        "campaign": {
            "name": campaign.get("name"),
            "objective": campaign.get("objective"),
            "budget": campaign.get("budget"),
            "budget_currency": campaign.get("budget_currency"),
            "budget_currency_warning": campaign.get("budget_currency_warning"),
            "status": campaign.get("status"),
            "success_metrics": campaign.get("success_metrics"),
        },
        "adset": {
            "name": ad_set.get("name"),
            "budget": ad_set.get("budget"),
            "lifetime_budget": ad_set.get("lifetime_budget"),
            "optimization_goal": ad_set.get("optimization_goal"),
            "billing_event": ad_set.get("billing_event"),
            "promoted_object": ad_set.get("promoted_object"),
            "placements": ad_set.get("placements"),
            "bidding": ad_set.get("bidding"),
            "schedule": {"start_time": ad_set.get("start_time"), "end_time": ad_set.get("end_time")},
            "status": ad_set.get("status"),
        },
        "creative": {
            "has_object_story_spec": bool(ad.get("object_story_spec")),
            "has_image_hash": bool(ad.get("image_hash")),
            "has_image_url": bool(ad.get("image_url")),
            "has_video_url": bool(ad.get("video_url")),
            "cta": ad.get("cta"),
            "cta_link": ad.get("cta_link"),
            "status": ad.get("final_status"),
        },
    }
