#!/usr/bin/env python3
"""Expert campaign configuration helpers.

These functions normalize the richer campaign fields Hermes may propose before
the backend stages or executes a Meta campaign. They intentionally keep Meta
Marketing API controls behind allowlisted, typed structures.
"""
import ast
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

LATAM_COUNTRY_CODES = [
    "MX",
    "CO",
    "PE",
    "CL",
    "AR",
    "EC",
    "CR",
    "PA",
    "UY",
    "DO",
    "GT",
    "SV",
    "HN",
    "PY",
    "BO",
]

COUNTRY_CODE_ALIASES = {
    "ARGENTINA": "AR",
    "BOLIVIA": "BO",
    "CHILE": "CL",
    "COLOMBIA": "CO",
    "COSTA RICA": "CR",
    "DOMINICAN REPUBLIC": "DO",
    "REPUBLICA DOMINICANA": "DO",
    "ECUADOR": "EC",
    "EL SALVADOR": "SV",
    "GUATEMALA": "GT",
    "HONDURAS": "HN",
    "MEXICO": "MX",
    "MÉXICO": "MX",
    "PANAMA": "PA",
    "PANAMÁ": "PA",
    "PARAGUAY": "PY",
    "PERU": "PE",
    "PERÚ": "PE",
    "UNITED STATES": "US",
    "ESTADOS UNIDOS": "US",
    "URUGUAY": "UY",
}

LATAM_ALIASES = {
    "LATAM",
    "LATIN AMERICA",
    "LATINOAMERICA",
    "LATINOAMÉRICA",
    "AMERICA LATINA",
    "AMÉRICA LATINA",
}


def _ascii_upper(value):
    text = str(value or "").strip().upper()
    return "".join(
        char for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )


LATAM_ALIAS_KEYS = {_ascii_upper(item) for item in LATAM_ALIASES}
COUNTRY_ALIAS_KEYS = {_ascii_upper(key): value for key, value in COUNTRY_CODE_ALIASES.items()}
COUNTRY_NAME_BY_CODE = {}
for _country_name, _country_code in COUNTRY_CODE_ALIASES.items():
    COUNTRY_NAME_BY_CODE.setdefault(_country_code, _country_name.title())


def country_name_for_code(code):
    return COUNTRY_NAME_BY_CODE.get(str(code or "").strip().upper(), str(code or "").strip().upper())


def normalize_age_bounds(value=None, age_min=None, age_max=None, default_min=18, default_max=65):
    """Normalize all supported age shapes without silently discarding input.

    Hermes may send ``age_range``, ``targeting_age_range``, ``age`` (``25-54``),
    or flat ``min_age``/``max_age`` aliases.  Returning one canonical pair
    prevents the Graph payload from falling back to 18–65 when a valid nested
    value was supplied.
    """
    raw = value
    if isinstance(raw, str):
        text = raw.strip()
        parsed = parse_jsonish(text, None)
        if parsed is not None:
            raw = parsed
        else:
            match = re.match(r"^\s*(\d{1,3})\s*[-–—]\s*(\d{1,3})\s*$", text)
            if match:
                raw = {"min": match.group(1), "max": match.group(2)}
    if isinstance(raw, dict):
        age_min = raw.get("min", raw.get("age_min", raw.get("min_age", age_min)))
        age_max = raw.get("max", raw.get("age_max", raw.get("max_age", age_max)))
    try:
        minimum = int(float(default_min if age_min in (None, "") else age_min))
        maximum = int(float(default_max if age_max in (None, "") else age_max))
    except (TypeError, ValueError):
        return {"ok": False, "age_min": None, "age_max": None, "error": "targeting_age_invalid"}
    if minimum < 13 or maximum > 65 or maximum < minimum:
        return {
            "ok": False,
            "age_min": minimum,
            "age_max": maximum,
            "error": "targeting_age_out_of_range",
        }
    return {"ok": True, "age_min": minimum, "age_max": maximum}


def validate_meta_targeting_selection(interests=None, locations=None, age_min=18, age_max=65, live_search=None, verify_locations=True):
    """Validate Meta audience selections before any campaign mutation.

    ``live_search`` is optional for dry-run validation and must return either
    normalized ``{"ok": True, "items": [...]}`` data or a failed result. When
    present, every selected interest/location is checked against Meta's live
    catalog immediately before staging/execution. No synthetic IDs, list-shaped
    country values, or silent US/65 fallbacks are accepted.
    """
    errors = []
    normalized_interests = []
    normalized_locations = []
    for item in interests or []:
        if not isinstance(item, dict):
            errors.append({"field": "interests", "code": "targeting_interest_invalid_shape"})
            continue
        interest_id = str(item.get("id") or item.get("key") or "").strip()
        name = str(item.get("name") or "").strip()
        if not re.fullmatch(r"[0-9]+", interest_id):
            errors.append({
                "field": "interests",
                "code": "targeting_interest_invalid_id",
                "id": interest_id,
                "message": "Meta interest IDs must be numeric IDs returned by the live catalog.",
            })
            continue
        if live_search and not name:
            errors.append({
                "field": "interests",
                "code": "targeting_interest_missing_name",
                "id": interest_id,
                "message": "Re-search this interest in Meta before staging it.",
            })
            continue
        normalized = {"id": interest_id}
        if name:
            normalized["name"] = name
        if live_search:
            result = live_search("interest", name)
            if not isinstance(result, dict) or not result.get("ok"):
                errors.append({"field": "interests", "code": "targeting_catalog_unavailable", "id": interest_id})
                continue
            rows = result.get("items") or []
            match = next((row for row in rows if str(row.get("id") or "").strip() == interest_id), None)
            if not match:
                errors.append({
                    "field": "interests",
                    "code": "targeting_interest_not_current",
                    "id": interest_id,
                    "name": name,
                    "message": "Meta no longer returned this ID for the selected interest.",
                })
                continue
            normalized["name"] = str(match.get("name") or name).strip()
        normalized_interests.append(normalized)

    for item in locations or []:
        if not isinstance(item, dict):
            errors.append({"field": "locations", "code": "targeting_location_invalid_shape"})
            continue
        key = str(item.get("key") or item.get("id") or "").strip()
        name = str(item.get("name") or item.get("label") or key).strip()
        location_type = str(item.get("type") or item.get("location_type") or "").strip().lower()
        country_code = str(item.get("country_code") or item.get("country") or "").strip().upper()
        if location_type == "country" or (len(key) == 2 and key.isalpha()):
            country_code = (country_code or key).upper()
            if not re.fullmatch(r"[A-Z]{2}", country_code):
                errors.append({"field": "locations", "code": "targeting_country_invalid", "value": country_code})
                continue
            key = country_code
            location_type = "country"
        elif not key or any(char in key for char in "[]{}'\""):
            errors.append({"field": "locations", "code": "targeting_location_invalid_id", "value": key})
            continue
        normalized = {"key": key, "name": name, "type": location_type or "location"}
        if country_code:
            normalized["country_code"] = country_code
        if live_search and verify_locations:
            query = name if name and name != key else (country_code or key)
            result = live_search("location", query)
            if not isinstance(result, dict) or not result.get("ok"):
                errors.append({"field": "locations", "code": "targeting_catalog_unavailable", "value": key})
                continue
            rows = result.get("items") or []
            def location_matches(row):
                row_key = str(row.get("key") or row.get("id") or "").strip()
                row_country = str(row.get("country_code") or "").strip().upper()
                return row_key == key or (country_code and row_country == country_code)
            if not any(location_matches(row) for row in rows):
                errors.append({
                    "field": "locations",
                    "code": "targeting_location_not_current",
                    "value": key,
                    "name": name,
                    "message": "Meta no longer returned this location in the live catalog.",
                })
                continue
        normalized_locations.append(normalized)

    ages = normalize_age_bounds(age_min=age_min, age_max=age_max)
    if not ages.get("ok"):
        errors.append({
            "field": "age_range",
            "code": ages.get("error") or "targeting_age_invalid",
            "age_min": ages.get("age_min"),
            "age_max": ages.get("age_max"),
        })
    return {
        "ok": not errors,
        "errors": errors,
        "interests": normalized_interests,
        "locations": normalized_locations,
        "age_min": ages.get("age_min"),
        "age_max": ages.get("age_max"),
    }
DETAILED_TARGETING_ID_KEYS = {
    "interests",
    "behaviors",
    "demographics",
    "life_events",
    "industries",
    "work_positions",
    "education_statuses",
    "family_statuses",
    "relationship_statuses",
    "excluded_interests",
}


def validate_detailed_targeting_ids(value):
    """Reject fabricated IDs in interests/demographic-like targeting fields."""
    errors = []

    def walk(node, field="targeting"):
        if isinstance(node, dict):
            for key, child in node.items():
                key_text = str(key or "").strip().lower()
                if key_text in DETAILED_TARGETING_ID_KEYS:
                    entries = child if isinstance(child, list) else [child]
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        item_id = str(entry.get("id") or entry.get("key") or "").strip()
                        if item_id and not re.fullmatch(r"[0-9]+", item_id):
                            errors.append({
                                "field": key_text,
                                "code": "targeting_detail_invalid_id",
                                "id": item_id,
                                "message": "Detailed-targeting IDs must be numeric IDs returned by Meta.",
                            })
                walk(child, key_text or field)
        elif isinstance(node, list):
            for child in node:
                walk(child, field)

    walk(value)
    return {"ok": not errors, "errors": errors}


def detailed_targeting_items(value):
    """Extract Meta detailed-targeting IDs with their live catalog type."""
    items = []
    seen = set()

    def walk(node):
        if isinstance(node, dict):
            for key, child in node.items():
                key_text = str(key or "").strip().lower()
                if key_text in DETAILED_TARGETING_ID_KEYS:
                    entries = child if isinstance(child, list) else [child]
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        item_id = str(entry.get("id") or entry.get("key") or "").strip()
                        if not item_id:
                            continue
                        identity = (key_text, item_id)
                        if identity in seen:
                            continue
                        seen.add(identity)
                        items.append({"id": item_id, "type": key_text})
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return items


def normalize_location_codes(value, default=None):
    """Normalize loose country/location input into Meta country codes.

    Hermes and the dashboard may send locations as lists, comma-separated text,
    Python-list-looking strings such as "['US']", country names, or broad
    market labels like LATAM. Keep the output as plain country code strings so
    Meta never receives a serialized list as one invalid country value.
    """
    codes = []

    def add(raw):
        if raw in (None, ""):
            return
        if isinstance(raw, (list, tuple, set)):
            for item in raw:
                add(item)
            return
        text = str(raw or "").strip()
        if not text:
            return
        if text.startswith("[") and text.endswith("]"):
            for parser in (json.loads, ast.literal_eval):
                try:
                    parsed = parser(text)
                except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
                    continue
                if parsed != text:
                    add(parsed)
                    return
        for part in re.split(r"[,;/|]+", text):
            cleaned = part.strip().strip("[](){}'\" ")
            if not cleaned:
                continue
            cleaned_upper = cleaned.upper()
            ascii_upper = _ascii_upper(cleaned)
            if cleaned_upper in LATAM_ALIASES or ascii_upper in LATAM_ALIAS_KEYS:
                for code in LATAM_COUNTRY_CODES:
                    add(code)
            elif len(cleaned_upper) == 2 and cleaned_upper.isalpha():
                codes.append(cleaned_upper)
            elif cleaned_upper in COUNTRY_CODE_ALIASES:
                codes.append(COUNTRY_CODE_ALIASES[cleaned_upper])
            elif ascii_upper in COUNTRY_ALIAS_KEYS:
                codes.append(COUNTRY_ALIAS_KEYS[ascii_upper])

    add(value)
    deduped = []
    seen = set()
    for code in codes:
        code = str(code or "").strip().upper()
        if len(code) == 2 and code.isalpha() and code not in seen:
            seen.add(code)
            deduped.append(code)
    if deduped:
        return deduped
    return list(default or [])


def infer_location_codes_from_context(*values):
    text = " ".join(str(value or "") for value in values)
    ascii_text = _ascii_upper(text)
    if "LATAM" in ascii_text or "LATIN AMERICA" in ascii_text or "AMERICA LATINA" in ascii_text:
        return list(LATAM_COUNTRY_CODES)
    return []


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
    raw_budget_level = str(
        payload.get("budget_level")
        or payload.get("budget_mode")
        or payload.get("budget_strategy")
        or ""
    ).strip().lower().replace("-", "_").replace(" ", "_")
    campaign_budget_flag = str(
        payload.get("campaign_budget_optimization")
        or payload.get("advantage_campaign_budget")
        or payload.get("cbo")
        or ""
    ).strip().lower()
    campaign_budget_enabled = raw_budget_level in {"campaign", "campaign_budget", "cbo", "advantage", "advantage_plus", "advantage_campaign_budget"} or campaign_budget_flag in {"1", "true", "yes", "si", "sí", "on", "enabled"}
    budget_level = "campaign" if campaign_budget_enabled else "adset"
    raw_sharing = None
    for key in ("is_adset_budget_sharing_enabled", "adset_budget_sharing_enabled", "ad_set_budget_sharing_enabled", "budget_sharing_enabled"):
        raw_sharing = boolish(payload.get(key))
        if raw_sharing is not None:
            break
    adset_budget_sharing_enabled = None if budget_level == "campaign" else bool(raw_sharing) if raw_sharing is not None else False
    campaign_daily = money(payload.get("campaign_daily_budget") or payload.get("daily_budget"), default_daily)
    total_budget = money(payload.get("total_budget"), campaign_daily * 30)
    adset_daily = 0 if budget_level == "campaign" else money(payload.get("adset_daily_budget"), campaign_daily)
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
        "budget_level": budget_level,
        "is_adset_budget_sharing_enabled": adset_budget_sharing_enabled,
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
    targeting_automation = parse_jsonish(
        payload.get("targeting_automation") or payload.get("targeting_automation_json"),
        {},
    )
    if isinstance(targeting_automation, dict) and "advantage_audience" in targeting_automation:
        enabled = boolish(targeting_automation.get("advantage_audience"))
        if enabled is not None:
            targeting["targeting_automation"] = {"advantage_audience": 1 if enabled else 0}
    targeting_mode = str(
        payload.get("targeting_mode")
        or payload.get("audience_mode")
        or payload.get("detailed_targeting_mode")
        or ""
    ).strip().lower()
    if targeting_mode:
        targeting["targeting_mode"] = targeting_mode
        if targeting_mode in {
            "advantage",
            "advantage+",
            "advantage_plus",
            "advantage_plus_audience",
            "suggested",
            "suggestions",
        }:
            targeting["targeting_automation"] = {"advantage_audience": 1}
        elif targeting_mode in {"manual", "strict", "detailed", "detailed_targeting"}:
            targeting["targeting_automation"] = {"advantage_audience": 0}
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
    manual_completion = manual_creative_completion_enabled(payload)
    placeholder_static = placeholder_static_ad_enabled(payload)
    placeholder_names = placeholder_ad_names(payload)
    placeholder_count = placeholder_ad_count(payload, default=len(placeholder_names) or 1) if placeholder_static else 0
    direct_preference = None
    for key in ("use_direct_publishing", "direct_publishing", "create_as_unpublished_post", "unpublished_post"):
        direct_preference = boolish(payload.get(key))
        if direct_preference is not None:
            break
    strategy = str(payload.get("creative_creation_strategy") or payload.get("publishing_strategy") or "").strip().lower()
    if direct_preference is None and strategy in {"direct", "direct_publishing", "native_post", "page_post", "dark_post", "unpublished_post"}:
        direct_preference = True
    if direct_preference is None and strategy in {"direct_creative", "inline_creative", "image_hash", "legacy"}:
        direct_preference = False
    return {
        "object_story_spec": object_story_spec if isinstance(object_story_spec, dict) and object_story_spec else {},
        "object_story_id": str(payload.get("object_story_id") or payload.get("page_post_id") or payload.get("post_id") or "").strip(),
        "image_hash": str(payload.get("image_hash") or "").strip(),
        "image_url": str(payload.get("image_url") or "").strip(),
        "video_path": str(payload.get("video_path") or "").strip(),
        "video_url": str(payload.get("video_url") or "").strip(),
        "video_id": str(payload.get("video_id") or "").strip(),
        "lead_gen_form_id": str(payload.get("lead_gen_form_id") or payload.get("lead_form_id") or payload.get("instant_form_id") or payload.get("meta_lead_form_id") or payload.get("form_id") or "").strip(),
        "cta_link": str(payload.get("cta_link") or payload.get("call_to_action_link") or "").strip(),
        "format": str(payload.get("creative_format") or payload.get("format") or "").strip().lower(),
        "use_direct_publishing": direct_preference,
        "manual_creative_completion": manual_completion,
        "create_placeholder_ad": placeholder_static,
        "placeholder_ad_count": placeholder_count,
        "placeholder_ad_names": placeholder_names[:placeholder_count] if placeholder_count else [],
        "creative_creation_strategy": str(payload.get("creative_creation_strategy") or payload.get("publishing_strategy") or "").strip().lower(),
    }


def manual_creative_completion_enabled(payload):
    """Return true when the campaign should stop at campaign/ad set creation.

    Meta's Marketing API requires a creative before an ad can be created. For
    some video website ads, Admira can still prepare the paused campaign/ad set
    and hand the buyer a precise Ads Manager completion checklist.
    """
    payload = payload or {}
    for key in (
        "manual_creative_completion",
        "defer_creative",
        "manual_video_completion",
        "manual_ads_manager_completion",
        "complete_creative_in_ads_manager",
        "ads_manager_creative_completion",
    ):
        parsed = boolish(payload.get(key))
        if parsed is not None:
            return parsed
    strategy = str(payload.get("creative_creation_strategy") or payload.get("publishing_strategy") or "").strip().lower()
    return strategy in {
        "manual_creative_completion",
        "manual_video_completion",
        "manual_video_ads_manager",
        "ads_manager_video_completion",
        "ads_manager_creative_completion",
        "defer_creative",
        "campaign_adset_only",
    }


def placeholder_static_ad_enabled(payload):
    """Return true when Admira should create paused static-placeholder ads.

    This is useful for video website ads that the buyer will finish in Ads
    Manager. The API-created ads stay paused and use a safe static placeholder
    creative, so the buyer can open each ad and replace the media with video.
    """
    payload = payload or {}
    for key in (
        "create_placeholder_ad",
        "placeholder_static_ad",
        "static_placeholder_ad",
        "placeholder_creative",
        "placeholder_creative_for_video",
        "video_placeholder_ad",
        "create_paused_placeholder_ads",
    ):
        parsed = boolish(payload.get(key))
        if parsed is not None:
            return parsed
    strategy = str(payload.get("creative_creation_strategy") or payload.get("publishing_strategy") or "").strip().lower()
    return strategy in {
        "placeholder_static_ad",
        "static_placeholder_ad",
        "video_placeholder_ad",
        "placeholder_creative_for_video",
        "paused_placeholder_ads",
    }


def placeholder_ad_count(payload, default=1, maximum=10):
    payload = payload or {}
    for key in (
        "placeholder_ad_count",
        "paused_placeholder_ad_count",
        "manual_completion_ad_count",
        "ads_to_prepare",
        "ad_count",
        "number_of_ads",
    ):
        parsed = intish(payload.get(key), 0)
        if parsed > 0:
            return max(1, min(parsed, maximum))
    return max(1, min(int(default or 1), maximum))


def placeholder_ad_names(payload, maximum=10):
    payload = payload or {}
    raw = None
    for key in (
        "placeholder_ad_names",
        "paused_placeholder_ad_names",
        "manual_completion_ad_names",
        "ad_names",
        "ads_to_prepare",
        "ad_variants",
        "creative_variants",
        "video_variants",
        "variation_names",
    ):
        if payload.get(key):
            raw = parse_jsonish(payload.get(key), payload.get(key))
            break
    if raw in (None, ""):
        return []
    if isinstance(raw, dict):
        raw = raw.get("items") or raw.get("ads") or raw.get("variants") or list(raw.values())
    if isinstance(raw, str):
        raw = [part.strip() for part in re.split(r"[\n;]+", raw) if part.strip()]
        if len(raw) == 1 and "," in raw[0]:
            raw = [part.strip() for part in raw[0].split(",") if part.strip()]
    names = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict):
            value = (
                item.get("name")
                or item.get("ad_name")
                or item.get("title")
                or item.get("label")
                or item.get("angle")
                or item.get("hook")
                or item.get("hypothesis")
                or item.get("concept")
            )
        else:
            value = item
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if text and text not in names:
            names.append(text[:120])
        if len(names) >= maximum:
            break
    return names


def creative_source_available(ad_plan):
    return any(
        ad_plan.get(key)
        for key in ("creative_image_path", "image_hash", "image_url", "video_path", "video_url", "video_id", "object_story_spec", "object_story_id")
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
    direct_plan = ad.get("direct_publishing_plan") if isinstance(ad.get("direct_publishing_plan"), dict) else {}
    manual_completion = manual_creative_completion_enabled(ad)
    placeholder_static = placeholder_static_ad_enabled(ad)
    placeholder_names = placeholder_ad_names(ad)
    will_create_object_story_id = bool(ad.get("object_story_id"))
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
            "is_adset_budget_sharing_enabled": ad_set.get("is_adset_budget_sharing_enabled"),
            "schedule": {"start_time": ad_set.get("start_time"), "end_time": ad_set.get("end_time")},
            "status": ad_set.get("status"),
        },
        "creative": {
            "has_object_story_spec": bool(ad.get("object_story_spec")),
            "has_object_story_id": bool(ad.get("object_story_id")),
            "will_create_object_story_id": will_create_object_story_id,
            "has_image_hash": bool(ad.get("image_hash")),
            "has_image_url": bool(ad.get("image_url")),
            "has_video_url": bool(ad.get("video_url")),
            "use_direct_publishing": ad.get("use_direct_publishing"),
            "manual_creative_completion": manual_completion,
            "create_placeholder_ad": placeholder_static,
            "placeholder_ad_count": placeholder_ad_count(ad, default=len(placeholder_names) or 1) if placeholder_static else 0,
            "placeholder_ad_names": placeholder_names,
            "will_create_ad": not manual_completion or placeholder_static,
            "creative_route": (
                "paused_static_placeholder_ads"
                if placeholder_static
                else "manual_ads_manager_completion"
                if manual_completion
                else direct_plan.get("creative_route") or ("existing_object_story_id" if ad.get("object_story_id") else "direct_creative")
            ),
            "direct_publishing_plan": ad.get("direct_publishing_plan"),
            "cta": ad.get("cta"),
            "cta_link": ad.get("cta_link"),
            "status": ad.get("final_status"),
        },
    }
