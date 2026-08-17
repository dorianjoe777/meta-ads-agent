#!/usr/bin/env python3
"""Evidence-gated, objective-aware decisions for Meta Ads optimization.

The engine deliberately separates a diagnosis from permission to mutate Meta.
No metric sentinel values are used: an unknown CPA remains unknown, and weak or
immature evidence produces a hold instead of a destructive recommendation.
"""
from datetime import datetime, timedelta, timezone
from statistics import median

from local_store import now_iso, read_json, write_json
from product_config import ROOT_DIR


DATA_DIR = ROOT_DIR / "dashboard" / "data"
OPTIMIZATION_STATE_FILE = DATA_DIR / "optimization_state.json"
PERFORMANCE_HISTORY_FILE = DATA_DIR / "performance_history.json"
BUSINESS_OUTCOMES_FILE = DATA_DIR / "business_outcomes.json"
MAX_HISTORY_DAYS = 180


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def parse_iso(value):
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def utc_now():
    return datetime.now(timezone.utc)


def default_optimization_state(now=None):
    current = now or utc_now()
    return {
        "version": 1,
        "mode": "shadow",
        "shadow_started_at": current.isoformat(timespec="seconds"),
        "buyer_confirmed_unlock": False,
        "matured_outcomes": 0,
        "unlock_requirements": {"minimum_days": 14, "minimum_matured_outcomes": 10},
        "cooldown_hours": 48,
        "low_volume_cooldown_hours": 72,
        "conversion_lag_hours": 24,
        "minimum_runtime_hours": 24,
        "scale_step_pct": 10,
        "maximum_scale_step_pct": 20,
        "test_budget_percent": 20,
        "account_daily_budget_cap": 0,
        "last_actions": {},
        "proposal_outcomes": [],
        "updated_at": now_iso(),
    }


def load_optimization_state(now=None):
    defaults = default_optimization_state(now)
    saved = read_json(OPTIMIZATION_STATE_FILE, {})
    if isinstance(saved, dict):
        for key, value in saved.items():
            if value is not None:
                defaults[key] = value
    if defaults.get("mode") not in {"shadow", "unlocked"}:
        defaults["mode"] = "shadow"
    defaults.setdefault("last_actions", {})
    defaults.setdefault("proposal_outcomes", [])
    return defaults


def save_optimization_state(payload):
    current = load_optimization_state()
    allowed_numeric = {
        "cooldown_hours": (12, 168),
        "low_volume_cooldown_hours": (24, 240),
        "conversion_lag_hours": (1, 168),
        "minimum_runtime_hours": (6, 168),
        "scale_step_pct": (1, 20),
        "maximum_scale_step_pct": (1, 30),
        "test_budget_percent": (5, 40),
        "account_daily_budget_cap": (0, 10000000),
    }
    for key, (minimum, maximum) in allowed_numeric.items():
        if key in (payload or {}):
            current[key] = max(minimum, min(maximum, number(payload.get(key), current.get(key))))
    current["updated_at"] = now_iso()
    write_json(OPTIMIZATION_STATE_FILE, current, ensure_ascii=False)
    return current


def unlock_status(state=None, now=None):
    state = state or load_optimization_state(now)
    current = now or utc_now()
    started = parse_iso(state.get("shadow_started_at")) or current
    requirements = state.get("unlock_requirements") or {}
    minimum_days = int(number(requirements.get("minimum_days"), 14))
    minimum_outcomes = int(number(requirements.get("minimum_matured_outcomes"), 10))
    elapsed_days = max(0, (current - started).days)
    matured = int(number(state.get("matured_outcomes"), 0))
    confirmed = bool(state.get("buyer_confirmed_unlock"))
    eligible = elapsed_days >= minimum_days and matured >= minimum_outcomes
    return {
        "mode": state.get("mode", "shadow"),
        "eligible": eligible,
        "buyer_confirmed": confirmed,
        "can_unlock": eligible and confirmed,
        "elapsed_days": elapsed_days,
        "minimum_days": minimum_days,
        "matured_outcomes": matured,
        "minimum_matured_outcomes": minimum_outcomes,
    }


def confirm_and_unlock(confirm=False, now=None):
    state = load_optimization_state(now)
    state["buyer_confirmed_unlock"] = bool(confirm)
    status = unlock_status(state, now)
    if confirm and not status["eligible"]:
        raise ValueError("Shadow mode still needs 14 days and 10 matured recommendation outcomes before it can be unlocked.")
    if confirm:
        state["mode"] = "unlocked"
        state["unlocked_at"] = (now or utc_now()).isoformat(timespec="seconds")
    else:
        state["mode"] = "shadow"
        state.pop("unlocked_at", None)
    state["updated_at"] = now_iso()
    write_json(OPTIMIZATION_STATE_FILE, state, ensure_ascii=False)
    return {"state": state, "unlock": unlock_status(state, now)}


def campaign_objective(campaign):
    raw = " ".join(
        str(campaign.get(key) or "")
        for key in ("objective", "objective_type", "optimization_goal", "result_type", "buying_type")
    ).lower()
    if any(term in raw for term in ("lead", "registration", "instant_form")):
        return "leads"
    if any(term in raw for term in ("message", "conversation", "whatsapp", "messenger")):
        return "messages"
    return "sales"


def objective_targets(campaign, rules):
    objective = campaign_objective(campaign)
    margin_pct = number(rules.get("contribution_margin_pct"), 0)
    break_even_roas = (100 / margin_pct) if margin_pct > 0 else 0
    if objective == "leads":
        target_cost = number(rules.get("target_cpl") or rules.get("target_cpa"), 0)
    elif objective == "messages":
        target_cost = number(rules.get("target_cost_per_conversation") or rules.get("target_cpa"), 0)
    else:
        target_cost = number(rules.get("target_cpa"), 0)
    return {
        "objective": objective,
        "target_cost_per_result": target_cost,
        "target_roas": max(number(rules.get("target_roas"), 0), break_even_roas) if objective == "sales" else 0,
        "break_even_roas": round(break_even_roas, 3) if objective == "sales" else 0,
        "contribution_margin_pct": margin_pct if objective == "sales" else 0,
        "minimum_spend": number(rules.get("min_spend_before_judging"), 0),
        "minimum_conversions": int(number(rules.get("min_conversions_before_scaling"), 3)),
        "max_cpa_multiplier": max(1, number(rules.get("max_cpa_multiplier"), 3)),
    }


def _campaign_age_hours(campaign, now):
    started = None
    for key in ("start_time", "started_at", "created_time", "created_at"):
        started = parse_iso(campaign.get(key))
        if started:
            break
    return None if not started else max(0, (now - started).total_seconds() / 3600)


def _freshness_hours(campaign, now):
    updated = parse_iso(campaign.get("updated_at") or campaign.get("data_through"))
    return None if not updated else max(0, (now - updated).total_seconds() / 3600)


def evidence_gate(campaign, rules, state=None, now=None):
    state = state or load_optimization_state(now)
    current = now or utc_now()
    targets = objective_targets(campaign, rules)
    spend = number(campaign.get("spend"))
    conversions = number(campaign.get("conversions"))
    age_hours = _campaign_age_hours(campaign, current)
    freshness = _freshness_hours(campaign, current)
    status = str(campaign.get("effective_status") or campaign.get("delivery_status") or campaign.get("status") or "").lower()
    learning = str(campaign.get("learning_stage") or campaign.get("delivery_info") or "").lower()
    minimum_runtime = number(state.get("minimum_runtime_hours"), 24)
    observed_lag = state.get("observed_conversion_lag_hours")
    conversion_lag = number(observed_lag if observed_lag is not None else state.get("conversion_lag_hours"), 24)
    reasons = []

    data_source = str(campaign.get("data_source") or campaign.get("source") or "").lower()
    if data_source in {"demo", "cached", "manual", "missing", "unknown"}:
        reasons.append("data source is not a fresh confirmed Meta read")

    if any(term in status or term in learning for term in ("preparing", "learning", "in_review", "pending_review")):
        reasons.append("Meta delivery is preparing or learning")
    if age_hours is not None and age_hours < minimum_runtime:
        reasons.append(f"campaign has only {age_hours:.0f}h of runtime")
    if freshness is not None and freshness > 36:
        reasons.append(f"performance data is {freshness:.0f}h old")
    if bool(campaign.get("is_partial_day")):
        reasons.append("current-day data is incomplete")

    campaign_id = str(campaign.get("id") or campaign.get("campaign_id") or "")
    last_action = parse_iso((state.get("last_actions") or {}).get(campaign_id))
    cooldown_hours = number(state.get("cooldown_hours"), 48)
    if conversions < targets["minimum_conversions"]:
        cooldown_hours = max(cooldown_hours, number(state.get("low_volume_cooldown_hours"), 72))
    if last_action:
        since_action = (current - last_action).total_seconds() / 3600
        if since_action < cooldown_hours:
            reasons.append(f"significant edit cooldown has {cooldown_hours - since_action:.0f}h remaining")
    external_edit = parse_iso(campaign.get("last_significant_edit_at") or campaign.get("updated_time"))
    if external_edit:
        since_edit = (current - external_edit).total_seconds() / 3600
        if 0 <= since_edit < cooldown_hours:
            reasons.append(f"Meta reports a recent edit; cooldown has {cooldown_hours - since_edit:.0f}h remaining")

    min_spend = max(targets["minimum_spend"], targets["target_cost_per_result"] * 0.75)
    # Unknown age is not permission to pause. It needs stronger spend evidence to
    # compensate for the missing runtime signal and the normal attribution lag.
    zero_conversion_floor = max(min_spend, targets["target_cost_per_result"] * 1.5)
    if age_hours is None:
        zero_conversion_floor = max(zero_conversion_floor, targets["target_cost_per_result"] * 2)
    mature_zero = conversions <= 0 and spend >= zero_conversion_floor
    enough_spend = spend >= min_spend
    enough_conversions = conversions >= max(1, targets["minimum_conversions"])

    if reasons:
        return {"ready": False, "state": "hold", "reasons": reasons, "targets": targets, "age_hours": age_hours, "freshness_hours": freshness}
    if not (mature_zero or enough_spend or enough_conversions):
        return {
            "ready": False,
            "state": "observe",
            "reasons": ["minimum spend or conversion evidence has not matured"],
            "targets": targets,
            "age_hours": age_hours,
            "freshness_hours": freshness,
        }
    if conversions <= 0 and age_hours is not None and age_hours < minimum_runtime + conversion_lag:
        return {
            "ready": False,
            "state": "hold",
            "reasons": ["zero-conversion result is still inside the attribution-lag window"],
            "targets": targets,
            "age_hours": age_hours,
            "freshness_hours": freshness,
        }
    return {"ready": True, "state": "mature", "reasons": [], "targets": targets, "age_hours": age_hours, "freshness_hours": freshness, "mature_zero": mature_zero}


def calibrated_scale_step(state):
    base = number(state.get("scale_step_pct"), 10)
    maximum = number(state.get("maximum_scale_step_pct"), 20)
    evaluated = [item.get("directionally_correct") for item in state.get("proposal_outcomes", []) if item.get("directionally_correct") is not None][:20]
    if len(evaluated) < 5:
        return {"step_pct": min(base, maximum), "evaluated": len(evaluated), "accuracy": None, "reason": "Conservative configured step; not enough matured outcomes to calibrate."}
    accuracy = sum(1 for item in evaluated if item) / len(evaluated)
    adjustment = 2 if accuracy >= 0.7 else (-3 if accuracy < 0.4 else 0)
    step = max(5, min(maximum, base + adjustment))
    return {"step_pct": step, "evaluated": len(evaluated), "accuracy": round(accuracy, 3), "reason": "Step calibrated from matured local recommendation outcomes, not a universal scaling rule."}


def recommend_campaign(campaign, rules, state=None, now=None):
    state = state or load_optimization_state(now)
    gate = evidence_gate(campaign, rules, state, now)
    targets = gate["targets"]
    spend = number(campaign.get("spend"))
    conversions = number(campaign.get("conversions"))
    revenue = number(campaign.get("revenue"))
    cpr = spend / conversions if conversions > 0 else None
    roas = revenue / spend if spend > 0 and revenue > 0 else None
    current_budget = max(0, number(campaign.get("daily_budget"), 0))
    result = {
        "decision": gate["state"],
        "action": "observe",
        "ready": bool(gate["ready"]),
        "reason": "; ".join(gate["reasons"]) or "Evidence is mature.",
        "current_budget": round(current_budget, 2),
        "recommended_budget": round(current_budget, 2),
        "change_pct": 0.0,
        "cost_per_result": None if cpr is None else round(cpr, 2),
        "roas": None if roas is None else round(roas, 2),
        "objective": targets["objective"],
        "evidence_gate": gate,
        "mutation_allowed": False,
        "shadow_mode": state.get("mode") != "unlocked",
    }
    if not gate["ready"]:
        return result

    target_cost = targets["target_cost_per_result"]
    target_roas = targets["target_roas"]
    minimum_conversions = targets["minimum_conversions"]
    calibration = calibrated_scale_step(state)
    step = number(calibration.get("step_pct"), 10)
    result["scale_calibration"] = calibration
    if conversions <= 0:
        result.update({"decision": "pause_candidate", "action": "pause_candidate", "reason": "Mature spend has produced no attributed results; review tracking and offer before pausing."})
    elif cpr is not None and target_cost > 0 and cpr > target_cost * targets["max_cpa_multiplier"]:
        result.update({"decision": "pause_candidate", "action": "pause_candidate", "reason": "Mature cost per result is far above the saved business target."})
    elif cpr is not None and target_cost > 0 and cpr > target_cost * 1.25:
        result.update({"decision": "reduce", "action": "decrease_budget", "reason": "Mature cost per result is above the saved business target."})
    else:
        roas_ok = targets["objective"] != "sales" or roas is None or target_roas <= 0 or roas >= target_roas
        cost_ok = target_cost <= 0 or (cpr is not None and cpr <= target_cost)
        if conversions >= minimum_conversions and cost_ok and roas_ok:
            result.update({"decision": "scale", "action": "increase_budget", "reason": "Cost and outcome evidence meet the saved objective targets."})
        else:
            result.update({"decision": "observe", "action": "observe", "reason": "Evidence is mature but does not justify a budget change yet."})

    if result["decision"] == "scale" and current_budget > 0:
        result["change_pct"] = round(step, 1)
        result["recommended_budget"] = round(current_budget * (1 + step / 100), 2)
    elif result["decision"] == "reduce" and current_budget > 0:
        result["change_pct"] = round(-step, 1)
        result["recommended_budget"] = round(current_budget * (1 - step / 100), 2)
    result["mutation_allowed"] = state.get("mode") == "unlocked" and result["action"] in {"increase_budget", "decrease_budget", "pause_candidate"}
    return result


def portfolio_recommendations(campaigns, rules, state=None, now=None):
    state = state or load_optimization_state(now)
    items = []
    for campaign in campaigns or []:
        decision = recommend_campaign(campaign, rules, state, now)
        decision.update({
            "campaign_id": campaign.get("id") or campaign.get("campaign_id"),
            "campaign_name": campaign.get("name") or "Campaign",
            "target_type": campaign.get("target_type", "campaign"),
            "target_id": campaign.get("target_id") or campaign.get("id") or campaign.get("campaign_id"),
        })
        items.append(decision)

    cap = number(state.get("account_daily_budget_cap"), 0)
    reserve_pct = number(state.get("test_budget_percent"), 20)
    if cap > 0:
        production_cap = cap * (1 - reserve_pct / 100)
        proposed_total = sum(number(item.get("recommended_budget")) for item in items)
        if proposed_total > production_cap:
            for item in items:
                if item["decision"] == "scale":
                    item.update({
                        "decision": "hold",
                        "action": "observe",
                        "recommended_budget": item["current_budget"],
                        "change_pct": 0.0,
                        "mutation_allowed": False,
                        "reason": f"Held to protect the {reserve_pct:.0f}% test reserve and account budget cap.",
                    })
    return items


def reconcile_business_outcomes(metrics, days=30):
    outcomes = read_json(BUSINESS_OUTCOMES_FILE, {})
    rows = list(outcomes.get("days") or [])[: max(1, int(days))]
    shop_orders = sum(int(number(row.get("orders"))) for row in rows)
    shop_net = round(sum(number(row.get("net_sales")) for row in rows), 2)
    shop_refunds = round(sum(number(row.get("refunds")) for row in rows), 2)
    summary = (metrics or {}).get("summary") or {}
    meta_conversions = number(summary.get("total_conversions"))
    meta_revenue = number(summary.get("total_revenue"))
    conversion_gap_pct = round((meta_conversions - shop_orders) / shop_orders * 100, 1) if shop_orders else None
    revenue_gap_pct = round((meta_revenue - shop_net) / shop_net * 100, 1) if shop_net else None
    status = "not_connected" if not outcomes.get("source") else "aligned"
    if status == "aligned" and (
        (conversion_gap_pct is not None and abs(conversion_gap_pct) >= 25)
        or (revenue_gap_pct is not None and abs(revenue_gap_pct) >= 25)
    ):
        status = "investigate"
    return {
        "status": status,
        "window_days": days,
        "shopify_orders": shop_orders,
        "shopify_net_sales": shop_net,
        "shopify_refunds": shop_refunds,
        "meta_conversions": meta_conversions,
        "meta_revenue": meta_revenue,
        "conversion_gap_pct": conversion_gap_pct,
        "revenue_gap_pct": revenue_gap_pct,
        "note": "Shopify is business truth; Meta remains attribution evidence, so timing and attribution windows can legitimately differ.",
    }


def anomaly_diagnostics(metrics, history=None):
    history = history or read_json(PERFORMANCE_HISTORY_FILE, {"days": []})
    days = list(history.get("days") or [])
    latest = (metrics or {}).get("summary") or {}
    diagnostics = []
    for key, label in (("total_spend", "spend"), ("total_conversions", "conversions"), ("overall_cpa", "CPA"), ("overall_roas", "ROAS")):
        values = [number((day.get("summary") or {}).get(key)) for day in days[1:29] if (day.get("summary") or {}).get(key) not in {None, ""}]
        if len(values) < 5:
            continue
        center = median(values)
        deviations = [abs(value - center) for value in values]
        mad = median(deviations)
        current = number(latest.get(key))
        robust_z = 0 if mad == 0 else 0.6745 * (current - center) / mad
        if abs(robust_z) >= 3.5:
            diagnostics.append({"metric": key, "label": label, "current": current, "baseline_median": round(center, 2), "robust_z": round(robust_z, 2), "severity": "high"})
    return diagnostics


def funnel_diagnostics(history=None):
    history = history or read_json(PERFORMANCE_HISTORY_FILE, {"days": []})
    latest = next((day for day in history.get("days", []) if (day.get("meta") or {}).get("levels")), {})
    rows = ((latest.get("meta") or {}).get("levels") or {}).get("campaign", [])
    totals = {key: 0.0 for key in ("landing_page_views", "view_content", "add_to_cart", "initiate_checkout", "purchase", "lead", "conversation")}
    for row in rows:
        for key in totals:
            totals[key] += number((row.get("funnel") or {}).get(key))
    diagnostics = []
    steps = [("view_content", "add_to_cart"), ("add_to_cart", "initiate_checkout"), ("initiate_checkout", "purchase")]
    for earlier, later in steps:
        if totals[earlier] >= 20:
            rate = totals[later] / totals[earlier]
            if rate < 0.1:
                diagnostics.append({"from": earlier, "to": later, "rate_pct": round(rate * 100, 1), "severity": "high", "note": "Investigate the offer, landing/checkout experience, event tracking, and audience fit before blaming the creative."})
    return {"available": any(totals.values()), "totals": {key: round(value, 2) for key, value in totals.items()}, "diagnostics": diagnostics}


def calibrate_conversion_lag(now=None):
    history = read_json(PERFORMANCE_HISTORY_FILE, {"days": []})
    latest = next((day for day in history.get("days", []) if (day.get("meta") or {}).get("levels")), {})
    meta_rows = ((latest.get("meta") or {}).get("levels") or {}).get("campaign", [])
    outcomes = read_json(BUSINESS_OUTCOMES_FILE, {})
    shop_by_date = {str(row.get("date")): number(row.get("orders")) for row in outcomes.get("days", [])}
    meta_by_date = {}
    for row in meta_rows:
        date_key = str(row.get("date_start") or "")[:10]
        if date_key:
            meta_by_date[date_key] = meta_by_date.get(date_key, 0) + number(row.get("conversions"))
    if len(shop_by_date) < 7 or len(meta_by_date) < 7:
        return {"calibrated": False, "reason": "At least seven overlapping daily Shopify and Meta observations are required."}
    scores = []
    for lag_days in range(4):
        errors = []
        for date_key, orders in shop_by_date.items():
            try:
                compare_date = (datetime.fromisoformat(date_key) + timedelta(days=lag_days)).date().isoformat()
            except ValueError:
                continue
            if compare_date in meta_by_date:
                errors.append(abs(meta_by_date[compare_date] - orders) / max(1, orders))
        if len(errors) >= 7:
            scores.append((sum(errors) / len(errors), lag_days, len(errors)))
    if not scores:
        return {"calibrated": False, "reason": "The daily series do not overlap enough to estimate attribution delay."}
    score, lag_days, samples = min(scores)
    state = load_optimization_state(now)
    state["observed_conversion_lag_hours"] = lag_days * 24
    state["conversion_lag_calibration"] = {"samples": samples, "mean_normalized_error": round(score, 3), "updated_at": (now or utc_now()).isoformat(timespec="seconds")}
    state["updated_at"] = now_iso()
    write_json(OPTIMIZATION_STATE_FILE, state, ensure_ascii=False)
    return {"calibrated": True, "hours": lag_days * 24, "samples": samples, "mean_normalized_error": round(score, 3)}


def record_shadow_outcomes(metrics, recommendations, now=None):
    current = now or utc_now()
    state = load_optimization_state(current)
    outcomes = list(state.get("proposal_outcomes") or [])
    campaigns = {str(item.get("id") or item.get("campaign_id")): item for item in (metrics or {}).get("campaigns", [])}
    matured_now = 0
    for outcome in outcomes:
        if outcome.get("status") != "observing":
            continue
        created = parse_iso(outcome.get("created_at")) or current
        if current - created < timedelta(hours=72):
            continue
        campaign = campaigns.get(str(outcome.get("campaign_id")))
        if not campaign:
            outcome.update({"status": "matured_unavailable", "matured_at": current.isoformat(timespec="seconds")})
        else:
            spend = number(campaign.get("spend"))
            conversions = number(campaign.get("conversions"))
            current_cpa = spend / conversions if conversions else None
            baseline_cpa = outcome.get("baseline_cpa")
            direction = outcome.get("action")
            improved = None
            if baseline_cpa not in {None, 0} and current_cpa is not None:
                improved = current_cpa <= number(baseline_cpa) if direction == "increase_budget" else current_cpa < number(baseline_cpa)
            outcome.update({"status": "matured", "matured_at": current.isoformat(timespec="seconds"), "observed_cpa": None if current_cpa is None else round(current_cpa, 2), "directionally_correct": improved})
        matured_now += 1

    date_key = current.date().isoformat()
    existing_keys = {(str(item.get("campaign_id")), item.get("action"), str(item.get("created_at", ""))[:10]) for item in outcomes}
    for recommendation in recommendations or []:
        action = recommendation.get("action")
        if action not in {"increase_budget", "decrease_budget", "pause_candidate"} or not recommendation.get("shadow_mode", True):
            continue
        campaign_id = str(recommendation.get("campaign_id") or "")
        key = (campaign_id, action, date_key)
        if key in existing_keys:
            continue
        campaign = campaigns.get(campaign_id, {})
        spend = number(campaign.get("spend"))
        conversions = number(campaign.get("conversions"))
        outcomes.insert(0, {
            "campaign_id": campaign_id,
            "campaign_name": recommendation.get("campaign_name"),
            "action": action,
            "created_at": current.isoformat(timespec="seconds"),
            "status": "observing",
            "baseline_cpa": round(spend / conversions, 2) if conversions else None,
            "baseline_roas": number(campaign.get("roas")),
            "evaluate_after_hours": 72,
        })
    state["proposal_outcomes"] = outcomes[:250]
    state["matured_outcomes"] = int(number(state.get("matured_outcomes"))) + matured_now
    state["updated_at"] = now_iso()
    write_json(OPTIMIZATION_STATE_FILE, state, ensure_ascii=False)
    return {"state": state, "unlock": unlock_status(state, current), "matured_now": matured_now, "recent": outcomes[:10]}


def record_optimization_action(campaign_id, now=None):
    state = load_optimization_state(now)
    state.setdefault("last_actions", {})[str(campaign_id or "")] = (now or utc_now()).isoformat(timespec="seconds")
    state["updated_at"] = now_iso()
    write_json(OPTIMIZATION_STATE_FILE, state, ensure_ascii=False)
    return state


def record_performance_snapshot(metrics, now=None):
    current = now or utc_now()
    history = read_json(PERFORMANCE_HISTORY_FILE, {"days": []})
    if not isinstance(history, dict) or not isinstance(history.get("days"), list):
        history = {"days": []}
    date_key = current.date().isoformat()
    snapshot = {
        "date": date_key,
        "recorded_at": current.isoformat(timespec="seconds"),
        "source": metrics.get("source", ""),
        "summary": metrics.get("summary", {}),
        "campaigns": [
            {
                "id": item.get("id"), "objective": campaign_objective(item),
                "spend": number(item.get("spend")), "conversions": number(item.get("conversions")),
                "revenue": number(item.get("revenue")), "impressions": int(number(item.get("impressions"))),
                "clicks": int(number(item.get("clicks"))),
            }
            for item in metrics.get("campaigns", [])
        ],
    }
    history["days"] = [snapshot] + [day for day in history["days"] if day.get("date") != date_key]
    history["days"] = history["days"][:MAX_HISTORY_DAYS]
    history["updated_at"] = now_iso()
    write_json(PERFORMANCE_HISTORY_FILE, history, ensure_ascii=False)
    return history
