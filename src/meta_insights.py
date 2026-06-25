#!/usr/bin/env python3
"""Read-only Meta Graph performance collection with progressive fallbacks."""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from local_store import now_iso, read_json, write_json
from optimization_engine import PERFORMANCE_HISTORY_FILE, MAX_HISTORY_DAYS


CONVERSION_ACTIONS = {
    "purchase", "omni_purchase", "offsite_conversion.fb_pixel_purchase",
    "onsite_conversion.purchase", "lead", "onsite_conversion.lead_grouped",
    "offsite_conversion.fb_pixel_lead", "onsite_conversion.messaging_conversation_started_7d",
}
PURCHASE_VALUE_ACTIONS = {
    "purchase", "omni_purchase", "offsite_conversion.fb_pixel_purchase", "onsite_conversion.purchase",
}
FUNNEL_ACTIONS = {
    "landing_page_views": {"landing_page_view"},
    "view_content": {"view_content", "offsite_conversion.fb_pixel_view_content"},
    "add_to_cart": {"add_to_cart", "offsite_conversion.fb_pixel_add_to_cart"},
    "initiate_checkout": {"initiate_checkout", "offsite_conversion.fb_pixel_initiate_checkout"},
    "purchase": PURCHASE_VALUE_ACTIONS,
    "lead": {"lead", "offsite_conversion.fb_pixel_lead", "onsite_conversion.lead_grouped"},
    "conversation": {"onsite_conversion.messaging_conversation_started_7d"},
}


def number(value, default=0.0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return float(default)


def action_value(rows, names):
    wanted = {str(name).lower() for name in names}
    total = 0.0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        action_type = str(row.get("action_type") or row.get("type") or "").lower()
        if action_type in wanted or any(action_type.endswith(f".{name}") for name in wanted):
            total += number(row.get("value"))
    return total


def safe_graph_error(payload):
    error = payload.get("error") if isinstance(payload, dict) else payload
    if isinstance(error, dict):
        return {
            "type": str(error.get("type") or "GraphAPIError")[:80],
            "code": int(number(error.get("code"))),
            "subcode": int(number(error.get("error_subcode"))),
            "message": str(error.get("message") or "Meta Graph request failed")[:300],
        }
    return {"type": "GraphAPIError", "code": 0, "subcode": 0, "message": str(error or "Meta Graph request failed")[:300]}


def graph_get(path, params, token, version="v24.0", timeout=25):
    if not token:
        return {"ok": False, "error": {"type": "configuration", "message": "Missing Meta access token"}}
    query = urllib.parse.urlencode({**(params or {}), "access_token": token})
    url = f"https://graph.facebook.com/{version}/{str(path).lstrip('/')}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "AdmiraIA/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"ok": True, "data": json.loads(response.read().decode("utf-8"))}
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {"error": {"message": f"Meta Graph HTTP {exc.code}"}}
        return {"ok": False, "error": safe_graph_error(payload)}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "error": {"type": "network", "code": 0, "subcode": 0, "message": str(exc)[:300]}}


def graph_rows(path, params, token, version="v24.0", max_pages=5):
    rows = []
    next_url = ""
    for _ in range(max_pages):
        if next_url:
            parsed = urllib.parse.urlparse(next_url)
            next_params = dict(urllib.parse.parse_qsl(parsed.query))
            # Never trust or persist a paging token as an alternate API secret.
            next_params["access_token"] = token
            result = graph_get(parsed.path.split(f"/{version}/", 1)[-1], next_params, token, version)
        else:
            result = graph_get(path, params, token, version)
        if not result.get("ok"):
            return {"ok": False, "rows": rows, "error": result.get("error")}
        payload = result.get("data") or {}
        page_rows = payload.get("data") or []
        if isinstance(page_rows, list):
            rows.extend(item for item in page_rows if isinstance(item, dict))
        next_url = str((payload.get("paging") or {}).get("next") or "")
        if not next_url:
            break
    return {"ok": True, "rows": rows, "error": None}


def normalize_insight_row(row, level):
    spend = number(row.get("spend"))
    impressions = int(number(row.get("impressions")))
    clicks = int(number(row.get("clicks") or row.get("inline_link_clicks")))
    conversions = action_value(row.get("actions"), CONVERSION_ACTIONS)
    revenue = action_value(row.get("action_values"), PURCHASE_VALUE_ACTIONS)
    item = {
        "level": level,
        "id": str(row.get(f"{level}_id") or row.get("id") or ""),
        "name": str(row.get(f"{level}_name") or row.get("name") or ""),
        "campaign_id": str(row.get("campaign_id") or ""),
        "adset_id": str(row.get("adset_id") or ""),
        "ad_id": str(row.get("ad_id") or ""),
        "date_start": str(row.get("date_start") or ""),
        "date_stop": str(row.get("date_stop") or ""),
        "spend": round(spend, 2),
        "impressions": impressions,
        "clicks": clicks,
        "conversions": round(conversions, 2),
        "revenue": round(revenue, 2),
        "ctr": round(clicks / impressions * 100, 3) if impressions else 0,
        "cpc": round(spend / clicks, 2) if clicks else 0,
        "cpa": round(spend / conversions, 2) if conversions else 0,
        "roas": round(revenue / spend, 3) if spend else 0,
        "frequency": round(number(row.get("frequency")), 2),
        "funnel": {key: round(action_value(row.get("actions"), names), 2) for key, names in FUNNEL_ACTIONS.items()},
    }
    for key in ("publisher_platform", "platform_position", "impression_device", "device_platform", "country", "region", "age", "gender"):
        if row.get(key) not in {None, ""}:
            item[key] = row.get(key)
    return item


def fetch_insights(account_id, token, version="v24.0", date_preset="last_30d", level="campaign", time_increment=1, breakdowns=""):
    account = str(account_id or "").strip()
    if account and not account.startswith("act_"):
        account = f"act_{account}"
    identity_fields = {
        "campaign": "campaign_id,campaign_name",
        "adset": "campaign_id,campaign_name,adset_id,adset_name",
        "ad": "campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name",
    }.get(level, "campaign_id,campaign_name")
    params = {
        "level": level,
        "date_preset": date_preset,
        "time_increment": time_increment,
        "fields": f"{identity_fields},date_start,date_stop,spend,impressions,clicks,inline_link_clicks,frequency,actions,action_values",
        "action_report_time": "conversion",
        "limit": 500,
    }
    if breakdowns:
        params["breakdowns"] = breakdowns
    result = graph_rows(f"/{account}/insights", params, token, version)
    if not result.get("ok"):
        fallback = dict(params)
        fallback["fields"] = f"{identity_fields},date_start,date_stop,spend,impressions,clicks,actions,action_values"
        result = graph_rows(f"/{account}/insights", fallback, token, version)
        result["fallback_used"] = bool(result.get("ok"))
    result["rows"] = [normalize_insight_row(row, level) for row in result.get("rows", [])]
    return result


def fetch_campaign_statuses(account_id, token, version="v24.0"):
    account = str(account_id or "").strip()
    if account and not account.startswith("act_"):
        account = f"act_{account}"
    result = graph_rows(
        f"/{account}/campaigns",
        {"fields": "id,name,status,effective_status,objective,start_time,stop_time,created_time,updated_time,daily_budget,lifetime_budget,budget_remaining", "limit": 500},
        token,
        version,
    )
    if not result.get("ok"):
        return result
    result["rows"] = [
        {
            "id": str(row.get("id") or ""), "name": row.get("name") or "",
            "status": str(row.get("status") or "").lower(),
            "effective_status": str(row.get("effective_status") or "").lower(),
            "objective": str(row.get("objective") or "").lower(),
            "start_time": row.get("start_time") or "", "stop_time": row.get("stop_time") or "",
            "created_time": row.get("created_time") or "", "updated_time": row.get("updated_time") or "",
            "daily_budget": round(number(row.get("daily_budget")) / 100, 2),
            "lifetime_budget": round(number(row.get("lifetime_budget")) / 100, 2),
            "budget_remaining": round(number(row.get("budget_remaining")) / 100, 2),
        }
        for row in result["rows"]
    ]
    return result


def collect_meta_snapshot(account_id, token, version="v24.0", date_preset="last_30d"):
    levels = {}
    unavailable = []
    for level in ("campaign", "adset", "ad"):
        result = fetch_insights(account_id, token, version, date_preset, level, 1)
        levels[level] = result.get("rows", [])
        if not result.get("ok"):
            unavailable.append({"view": level, "reason": result.get("error")})

    breakdowns = {}
    for name, fields in {
        "placement_device": "publisher_platform,platform_position,impression_device",
        "age_gender": "age,gender",
        "country": "country",
    }.items():
        result = fetch_insights(account_id, token, version, date_preset, "ad", 1, fields)
        breakdowns[name] = result.get("rows", [])
        if not result.get("ok"):
            unavailable.append({"view": name, "reason": result.get("error")})

    statuses = fetch_campaign_statuses(account_id, token, version)
    if not statuses.get("ok"):
        unavailable.append({"view": "delivery_status", "reason": statuses.get("error")})
    status_by_id = {item["id"]: item for item in statuses.get("rows", [])}
    return {
        "generated_at": now_iso(),
        "account_id": str(account_id or ""),
        "date_preset": date_preset,
        "levels": levels,
        "breakdowns": breakdowns,
        "campaign_statuses": status_by_id,
        "data_quality": {
            "complete": not unavailable,
            "unavailable": unavailable,
            "source": "meta_graph_read_only",
        },
    }


def aggregate_campaigns(snapshot):
    status_by_id = snapshot.get("campaign_statuses") or {}
    totals = {}
    for row in (snapshot.get("levels") or {}).get("campaign", []):
        campaign_id = str(row.get("id") or row.get("campaign_id") or "")
        item = totals.setdefault(campaign_id, {
            "id": campaign_id, "campaign_id": campaign_id, "name": row.get("name") or campaign_id,
            "spend": 0.0, "impressions": 0, "clicks": 0, "conversions": 0.0, "revenue": 0.0,
        })
        for key in ("spend", "conversions", "revenue"):
            item[key] += number(row.get(key))
        for key in ("impressions", "clicks"):
            item[key] += int(number(row.get(key)))
    for campaign_id, item in totals.items():
        status = status_by_id.get(campaign_id, {})
        item.update(status)
        item["id"] = campaign_id
        item["campaign_id"] = campaign_id
        item["target_type"] = "campaign"
        item["target_id"] = campaign_id
        item["frequency"] = max((number(row.get("frequency")) for row in (snapshot.get("levels") or {}).get("campaign", []) if str(row.get("id")) == campaign_id), default=0)
        item["updated_at"] = snapshot.get("generated_at")
        item["data_through"] = max((str(row.get("date_stop") or "") for row in (snapshot.get("levels") or {}).get("campaign", []) if str(row.get("id")) == campaign_id), default="")
    return list(totals.values())


def save_meta_snapshot(snapshot, now=None):
    current = now or datetime.now(timezone.utc)
    history = read_json(PERFORMANCE_HISTORY_FILE, {"days": []})
    if not isinstance(history, dict) or not isinstance(history.get("days"), list):
        history = {"days": []}
    date_key = current.date().isoformat()
    existing = next((day for day in history["days"] if day.get("date") == date_key), {"date": date_key})
    existing["recorded_at"] = current.isoformat(timespec="seconds")
    existing["meta"] = {
        "account_id": snapshot.get("account_id"),
        "date_preset": snapshot.get("date_preset"),
        "levels": snapshot.get("levels"),
        "breakdowns": snapshot.get("breakdowns"),
        "campaign_statuses": snapshot.get("campaign_statuses"),
        "data_quality": snapshot.get("data_quality"),
    }
    history["days"] = [existing] + [day for day in history["days"] if day.get("date") != date_key]
    history["days"] = history["days"][:MAX_HISTORY_DAYS]
    history["updated_at"] = now_iso()
    write_json(PERFORMANCE_HISTORY_FILE, history, ensure_ascii=False)
    return history
