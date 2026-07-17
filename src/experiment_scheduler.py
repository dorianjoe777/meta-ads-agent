#!/usr/bin/env python3
"""Adaptive, persistent review checkpoints for creative experiments."""
import math
import re
from datetime import datetime, timedelta, timezone

from decision_memory import load_profitability_rules
from local_store import now_iso, read_json, write_json
from meta_action_metrics import deduplicated_alias_value
from product_config import ROOT_DIR


DATA_DIR = ROOT_DIR / "dashboard" / "data"
EXPERIMENTS_FILE = DATA_DIR / "creative_experiments.json"
MAX_EXPERIMENTS = 100


def utc_now():
    return datetime.now(timezone.utc)


def parse_iso(value):
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def number(value, default=0.0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return float(default)


def whole(value):
    return int(number(value))


def safe_slug(value, fallback="test"):
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "").strip()).strip("-").lower()
    return (slug or fallback)[:48]


def load_experiments():
    state = read_json(EXPERIMENTS_FILE, {})
    if not isinstance(state, dict):
        state = {}
    experiments = state.get("experiments")
    if not isinstance(experiments, list):
        experiments = []
    return {"updated_at": state.get("updated_at", ""), "experiments": experiments}


def save_experiments(state):
    state = dict(state or {})
    state["updated_at"] = now_iso()
    state["experiments"] = list(state.get("experiments") or [])[:MAX_EXPERIMENTS]
    write_json(EXPERIMENTS_FILE, state, ensure_ascii=False)
    return state


def action_value(row, names):
    actions = row.get("actions") or row.get("conversions") or []
    if not isinstance(actions, list):
        return 0.0
    return deduplicated_alias_value(actions, names)


def normalize_insight_rows(data, level="ad"):
    rows = data.get("data") if isinstance(data, dict) else data
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("ads") or rows.get("campaigns") or []
    if not isinstance(rows, list):
        return []
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        spend = number(row.get("spend") or row.get("amount_spent"))
        conversions = number(row.get("conversions") or row.get("purchases") or row.get("results"))
        if not conversions:
            conversions = action_value(row, ["purchase", "lead", "complete_registration", "omni_purchase"])
        revenue = number(row.get("revenue") or row.get("conversion_value") or row.get("value") or row.get("purchase_roas_value"))
        impressions = whole(row.get("impressions"))
        clicks = whole(row.get("clicks") or row.get("inline_link_clicks"))
        normalized.append({
            "level": level,
            "id": str(row.get(f"{level}_id") or row.get("id") or ""),
            "name": str(row.get(f"{level}_name") or row.get("name") or ""),
            "ad_id": str(row.get("ad_id") or (row.get("id") if level == "ad" else "") or ""),
            "creative_id": str(row.get("creative_id") or ""),
            "adset_id": str(row.get("adset_id") or row.get("ad_set_id") or ""),
            "campaign_id": str(row.get("campaign_id") or (row.get("id") if level == "campaign" else "") or ""),
            "spend": round(spend, 2),
            "impressions": impressions,
            "clicks": clicks,
            "conversions": round(conversions, 2),
            "revenue": round(revenue, 2),
        })
    return normalized


def normalize_campaign_rows(metrics):
    rows = []
    for campaign in (metrics or {}).get("campaigns", []):
        rows.append({
            "level": "campaign",
            "id": str(campaign.get("id") or ""),
            "name": str(campaign.get("name") or ""),
            "ad_id": "",
            "creative_id": "",
            "adset_id": str(campaign.get("adset_id") or ""),
            "campaign_id": str(campaign.get("id") or ""),
            "spend": round(number(campaign.get("spend")), 2),
            "impressions": whole(campaign.get("impressions")),
            "clicks": whole(campaign.get("clicks")),
            "conversions": round(number(campaign.get("conversions")), 2),
            "revenue": round(number(campaign.get("revenue")), 2),
        })
    return rows


def normalized_variants(raw_variants):
    if not isinstance(raw_variants, list):
        return []
    variants = []
    for index, raw in enumerate(raw_variants[:12], start=1):
        if isinstance(raw, str):
            raw = {"name": raw, "ad_id": raw}
        if not isinstance(raw, dict):
            continue
        variant_id = str(raw.get("id") or raw.get("ad_id") or raw.get("creative_id") or f"variant_{index}").strip()
        variants.append({
            "id": variant_id,
            "name": str(raw.get("name") or f"Creative {index}").strip(),
            "ad_id": str(raw.get("ad_id") or "").strip(),
            "creative_id": str(raw.get("creative_id") or "").strip(),
            "adset_id": str(raw.get("adset_id") or raw.get("ad_set_id") or "").strip(),
            "campaign_id": str(raw.get("campaign_id") or "").strip(),
        })
    return variants


def review_plan(daily_budget, target_cpa, variant_count, rules=None):
    rules = rules or load_profitability_rules()
    budget = max(0.01, number(daily_budget))
    target = max(0.01, number(target_cpa) or number(rules.get("target_cpa")) or 50.0)
    rule_floor = number(rules.get("min_spend_before_judging"))
    required_spend = round(max(rule_floor, target * 0.75), 2)
    estimated_hours = (required_spend * max(2, int(variant_count)) / budget) * 24
    evidence_hours = int(round(max(24, min(168, estimated_hours))))
    return {
        "delivery_check_hours": 6,
        "evidence_check_hours": evidence_hours,
        "required_spend_per_variant": required_spend,
        "min_total_conversions": max(2, int(number(rules.get("min_conversions_before_scaling"), 3))),
        "calculation_note": "Heuristic based on test budget, target CPA, concurrent variants, and saved profitability rules; it is not a performance guarantee.",
    }


def row_for_variant(variant, rows, allow_campaign=False):
    for key in ("ad_id", "creative_id", "adset_id"):
        wanted = str(variant.get(key) or "")
        if not wanted:
            continue
        match = next((row for row in rows if str(row.get(key) or "") == wanted), None)
        if match:
            return match
    wanted_id = str(variant.get("id") or "")
    match = next((row for row in rows if wanted_id and str(row.get("id") or "") == wanted_id), None)
    if match:
        return match
    if allow_campaign and variant.get("campaign_id"):
        return next((row for row in rows if str(row.get("campaign_id") or "") == str(variant.get("campaign_id"))), None)
    return None


def metric_snapshot(row):
    if not row:
        return {"available": False, "spend": 0.0, "impressions": 0, "clicks": 0, "conversions": 0.0, "revenue": 0.0}
    return {
        "available": True,
        "level": row.get("level", ""),
        "spend": round(number(row.get("spend")), 2),
        "impressions": whole(row.get("impressions")),
        "clicks": whole(row.get("clicks")),
        "conversions": round(number(row.get("conversions")), 2),
        "revenue": round(number(row.get("revenue")), 2),
    }


def variant_metrics(experiment, insight_rows=None, campaign_metrics=None):
    rows = list(insight_rows or [])
    campaign_rows = normalize_campaign_rows(campaign_metrics or {})
    campaign_counts = {}
    for variant in experiment.get("variants", []):
        campaign_id = variant.get("campaign_id")
        if campaign_id:
            campaign_counts[campaign_id] = campaign_counts.get(campaign_id, 0) + 1
    baselines = experiment.get("baseline") or {}
    output = []
    for variant in experiment.get("variants", []):
        row = row_for_variant(variant, rows)
        if not row and variant.get("campaign_id") and campaign_counts.get(variant.get("campaign_id")) == 1:
            row = row_for_variant(variant, campaign_rows, allow_campaign=True)
        current = metric_snapshot(row)
        baseline = baselines.get(variant.get("id")) or {}
        measured = {"available": bool(current.get("available")), "level": current.get("level", "")}
        for key in ("spend", "impressions", "clicks", "conversions", "revenue"):
            measured[key] = max(0, number(current.get(key)) - number(baseline.get(key)))
            if key in {"impressions", "clicks"}:
                measured[key] = int(measured[key])
            else:
                measured[key] = round(measured[key], 2)
        measured["ctr"] = round((measured["clicks"] / measured["impressions"] * 100) if measured["impressions"] else 0, 2)
        measured["cpa"] = round((measured["spend"] / measured["conversions"]) if measured["conversions"] else 0, 2)
        measured["roas"] = round((measured["revenue"] / measured["spend"]) if measured["spend"] else 0, 2)
        output.append({**variant, "metrics": measured})
    return output


def capture_baseline(variants, insight_rows=None, campaign_metrics=None):
    experiment = {"variants": variants, "baseline": {}}
    captured = {}
    for item in variant_metrics(experiment, insight_rows, campaign_metrics):
        captured[item["id"]] = {key: item["metrics"].get(key) for key in ("available", "level", "spend", "impressions", "clicks", "conversions", "revenue")}
    return captured


def schedule_experiment(payload, insight_rows=None, campaign_metrics=None, now=None):
    payload = payload if isinstance(payload, dict) else {}
    variants = normalized_variants(payload.get("variants"))
    if len(variants) < 2:
        raise ValueError("A creative experiment needs at least two named variants with their real Meta IDs.")
    variants_without_ids = [variant["name"] for variant in variants if not (variant.get("ad_id") or variant.get("creative_id"))]
    if variants_without_ids:
        raise ValueError(f"Each launched variant needs a real ad_id or creative_id. Missing: {', '.join(variants_without_ids)}.")
    comparison_ids = [variant.get("ad_id") or variant.get("creative_id") for variant in variants]
    if len(set(comparison_ids)) != len(comparison_ids):
        raise ValueError("Each creative variant needs a different real Meta ad or creative ID.")
    daily_budget = number(payload.get("daily_budget"))
    if daily_budget <= 0:
        raise ValueError("A positive daily test budget is required before scheduling reviews.")
    rules = load_profitability_rules()
    target_cpa = number(payload.get("target_cpa") or payload.get("target_cpl") or rules.get("target_cpa"))
    if target_cpa <= 0:
        raise ValueError("A target CPA or CPL is required to estimate a responsible evidence window.")
    current_time = now or utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    start_at = parse_iso(payload.get("start_at")) or current_time.astimezone(timezone.utc)
    name = str(payload.get("name") or payload.get("campaign_name") or "Creative test").strip()
    experiment_id = str(payload.get("experiment_id") or "").strip()
    if not experiment_id:
        experiment_id = f"experiment_{start_at.strftime('%Y%m%d%H%M%S')}_{safe_slug(name)}"
    plan = review_plan(daily_budget, target_cpa, len(variants), rules)
    next_review = start_at + timedelta(hours=plan["delivery_check_hours"])
    experiment = {
        "id": experiment_id,
        "name": name,
        "campaign_id": str(payload.get("campaign_id") or "").strip(),
        "campaign_name": str(payload.get("campaign_name") or name).strip(),
        "hypothesis": str(payload.get("hypothesis") or "").strip(),
        "primary_metric": str(payload.get("primary_metric") or "cpa").strip().lower(),
        "daily_budget": round(daily_budget, 2),
        "target_cpa": round(target_cpa, 2),
        "status": "observing",
        "phase": "delivery",
        "start_at": start_at.isoformat(timespec="seconds"),
        "created_at": current_time.isoformat(timespec="seconds"),
        "updated_at": current_time.isoformat(timespec="seconds"),
        "next_review_at": next_review.isoformat(timespec="seconds"),
        "plan": plan,
        "variants": variants,
        "baseline": capture_baseline(variants, insight_rows, campaign_metrics),
        "history": [],
        "latest_review": {},
    }
    state = load_experiments()
    existing = [item for item in state["experiments"] if item.get("id") != experiment_id]
    state["experiments"] = [experiment, *existing]
    save_experiments(state)
    return experiment


def rank_variants(items, primary_metric):
    candidates = [item for item in items if item.get("metrics", {}).get("available")]
    if primary_metric in {"cpa", "cpl", "cost_per_result"}:
        candidates = [item for item in candidates if number(item.get("metrics", {}).get("conversions")) > 0]
        return sorted(candidates, key=lambda item: number(item["metrics"].get("cpa")))
    if primary_metric == "ctr":
        return sorted(candidates, key=lambda item: number(item["metrics"].get("ctr")), reverse=True)
    return sorted(candidates, key=lambda item: number(item["metrics"].get("roas")), reverse=True)


def adaptive_wait_hours(experiment, items):
    plan = experiment.get("plan") or {}
    required = number(plan.get("required_spend_per_variant"))
    missing_spend = sum(max(0, required - number(item.get("metrics", {}).get("spend"))) for item in items)
    budget = max(0.01, number(experiment.get("daily_budget")))
    estimated = (missing_spend / budget) * 24
    return int(round(max(12, min(72, estimated or 24))))


def comparison_confidence(ranked, primary_metric):
    """Approximate probability that the observed leader beats the runner-up.

    Conversion metrics use a smoothed Poisson rate per dollar; CTR uses a
    two-proportion normal approximation. The output is diagnostic—not a promise.
    """
    if len(ranked) < 2:
        return {"probability_best": 0.0, "expected_lift": 0.0, "method": "insufficient_variants"}
    first = ranked[0]["metrics"]
    second = ranked[1]["metrics"]
    metric = str(primary_metric or "cpa").lower()
    if metric == "ctr":
        n1, n2 = number(first.get("impressions")), number(second.get("impressions"))
        x1, x2 = number(first.get("clicks")), number(second.get("clicks"))
        if n1 <= 0 or n2 <= 0:
            return {"probability_best": 0.0, "expected_lift": 0.0, "method": "ctr_two_proportion"}
        p1, p2 = x1 / n1, x2 / n2
        pooled = (x1 + x2) / (n1 + n2)
        se = math.sqrt(max(1e-12, pooled * (1 - pooled) * (1 / n1 + 1 / n2)))
        z = (p1 - p2) / se
        probability = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        lift = (p1 / p2 - 1) if p2 > 0 else 1.0
        return {"probability_best": round(probability, 4), "expected_lift": round(lift, 4), "method": "ctr_two_proportion"}

    c1, c2 = number(first.get("conversions")) + 0.5, number(second.get("conversions")) + 0.5
    s1, s2 = max(0.01, number(first.get("spend"))), max(0.01, number(second.get("spend")))
    rate1, rate2 = c1 / s1, c2 / s2
    z = math.log(max(1e-12, rate1 / rate2)) / math.sqrt((1 / c1) + (1 / c2))
    probability = 0.5 * (1 + math.erf(z / math.sqrt(2)))
    if metric in {"cpa", "cpl", "cost_per_result"}:
        v1, v2 = number(first.get("cpa")), number(second.get("cpa"))
        lift = (v2 / v1 - 1) if v1 > 0 and v2 > 0 else (1.0 if c1 > c2 else 0.0)
    else:
        v1, v2 = number(first.get("roas")), number(second.get("roas"))
        lift = (v1 / v2 - 1) if v2 > 0 else (1.0 if v1 > 0 else 0.0)
    return {"probability_best": round(probability, 4), "expected_lift": round(lift, 4), "method": "smoothed_poisson_conversion_rate"}


def evaluate_experiment(experiment, insight_rows=None, campaign_metrics=None, now=None):
    current_time = now or utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    items = variant_metrics(experiment, insight_rows, campaign_metrics)
    available = [item for item in items if item["metrics"].get("available")]
    delivered = [item for item in available if item["metrics"].get("impressions") or item["metrics"].get("spend")]
    plan = experiment.get("plan") or review_plan(experiment.get("daily_budget"), experiment.get("target_cpa"), len(items))
    required_spend = number(plan.get("required_spend_per_variant"))
    min_conversions = int(number(plan.get("min_total_conversions"), 2))
    total_conversions = sum(number(item["metrics"].get("conversions")) for item in items)
    spends = [number(item["metrics"].get("spend")) for item in items if item["metrics"].get("available")]
    spend_starved = bool(spends and max(spends) >= required_spend and min(spends) < max(spends) * 0.25)
    every_variant_funded = bool(items) and all(number(item["metrics"].get("spend")) >= required_spend for item in items)
    enough_zero_conversion_spend = bool(items) and all(number(item["metrics"].get("spend")) >= required_spend * 1.5 for item in items)
    evidence_sufficient = len(available) >= 2 and every_variant_funded and (total_conversions >= min_conversions or enough_zero_conversion_spend)
    phase = str(experiment.get("phase") or "delivery")
    evidence_due = (parse_iso(experiment.get("start_at")) or current_time) + timedelta(hours=int(plan.get("evidence_check_hours") or 24))
    recommendations = []
    leader = None
    confidence = "insufficient"
    confidence_detail = {"probability_best": 0.0, "expected_lift": 0.0, "method": "insufficient_evidence"}

    if phase == "delivery":
        if len(available) < 2:
            status = "waiting_for_variant_data"
            summary = "No hay desglose real por creativo suficiente todavía; no voy a inventar un ganador."
            next_review = min(evidence_due, current_time + timedelta(hours=24))
        elif len(delivered) < len(items) or spend_starved:
            status = "delivery_problem"
            missing = [item["name"] for item in items if item not in delivered]
            if spend_starved:
                summary = "Meta está concentrando el gasto en una variante. No es una comparación limpia; conviene usar Creative Testing nativo o un test controlado."
                recommendations.append({"type": "use_controlled_creative_test", "reason": "Spend starvation makes the current comparison biased.", "requires_approval": False})
            else:
                summary = f"Hay variantes sin entrega ({', '.join(missing)}). Conviene revisar publicación, aprobación y distribución antes de juzgar rendimiento."
                recommendations.append({"type": "inspect_delivery", "variants": missing, "requires_approval": False})
            next_review = current_time + timedelta(hours=12)
        else:
            status = "collecting_evidence"
            summary = "Todas las variantes están entregando. Aún es pronto para elegir ganadora."
            next_review = max(current_time + timedelta(hours=12), evidence_due)
        next_phase = "evidence"
    elif not evidence_sufficient:
        status = "collecting_evidence"
        missing_names = [item["name"] for item in items if number(item["metrics"].get("spend")) < required_spend]
        if spend_starved:
            summary = "La distribución de gasto está demasiado desequilibrada para declarar ganadora. Recomiendo un test creativo controlado; no forzaré presupuestos automáticamente."
            recommendations.append({"type": "use_controlled_creative_test", "requires_approval": False})
        elif len(available) < 2:
            summary = "Sigue faltando rendimiento real desglosado por creativo; no hay base para comparar variantes."
        else:
            summary = (
                f"Todavía no hay evidencia suficiente: se necesitan cerca de ${required_spend:.2f} por variante"
                + (f" y faltan datos en {', '.join(missing_names)}." if missing_names else ".")
            )
        next_review = current_time + timedelta(hours=adaptive_wait_hours(experiment, items))
        next_phase = "evidence"
    else:
        ranked = rank_variants(items, experiment.get("primary_metric", "cpa"))
        leader = ranked[0] if ranked else None
        confidence_detail = comparison_confidence(ranked, experiment.get("primary_metric", "cpa"))
        probability = number(confidence_detail.get("probability_best"))
        lift = number(confidence_detail.get("expected_lift"))
        confidence = "decision_ready" if probability >= 0.90 and lift >= 0.10 else ("provisional" if probability >= 0.80 else "inconclusive")
        target_cpa = number(experiment.get("target_cpa"))
        if leader:
            leader_metrics = leader["metrics"]
            summary = (
                f"{leader['name']} es la líder provisional con CPA ${number(leader_metrics.get('cpa')):.2f}, "
                f"{number(leader_metrics.get('conversions')):.0f} resultados y ROAS {number(leader_metrics.get('roas')):.2f}x."
            )
            scalable = (
                confidence == "decision_ready"
                and
                number(leader_metrics.get("conversions")) >= min_conversions
                and (not target_cpa or (leader_metrics.get("cpa") and number(leader_metrics.get("cpa")) <= target_cpa))
            )
            if experiment.get("primary_metric", "cpa") == "ctr":
                scalable = False
                summary += " El CTR es solo una señal de atención; no convierte a esta variante en ganadora de ventas."
                recommendations.append({"type": "continue_to_conversion_outcome", "variant_id": leader.get("id"), "requires_approval": False})
            elif scalable:
                recommendations.append({
                    "type": "consider_scaling_winner",
                    "variant_id": leader.get("id"),
                    "variant_name": leader.get("name"),
                    "reason": "Enough conversion evidence and CPA is at or below target.",
                    "requires_approval": True,
                })
            for item in items:
                if item.get("id") == leader.get("id"):
                    continue
                metrics = item["metrics"]
                clearly_weak = confidence == "decision_ready" and (
                    number(metrics.get("spend")) >= required_spend
                    and (number(metrics.get("conversions")) == 0 or (target_cpa and number(metrics.get("cpa")) > target_cpa * 1.5))
                )
                if clearly_weak:
                    recommendations.append({
                        "type": "consider_pausing_or_refresh",
                        "variant_id": item.get("id"),
                        "variant_name": item.get("name"),
                        "reason": "Funded enough to judge and materially behind the provisional leader.",
                        "requires_approval": True,
                    })
        else:
            summary = "El test ya gastó suficiente, pero ninguna variante produjo una señal ganadora. Conviene revisar oferta, ángulo o ejecución antes de añadir presupuesto."
            recommendations.append({"type": "rework_test", "requires_approval": False})
        actionable = [item for item in recommendations if item.get("requires_approval")]
        if actionable:
            status = "decision_ready"
            next_review = None
            next_phase = "awaiting_decision"
        else:
            status = "collecting_evidence"
            next_review = current_time + timedelta(hours=24)
            next_phase = "evidence"

    return {
        "reviewed_at": current_time.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "status": status,
        "phase": next_phase,
        "summary": summary,
        "evidence_sufficient": evidence_sufficient,
        "confidence": confidence,
        "confidence_detail": confidence_detail,
        "spend_starved": spend_starved,
        "leader": ({"id": leader.get("id"), "name": leader.get("name"), "metrics": leader.get("metrics")} if leader else None),
        "variants": items,
        "recommendations": recommendations,
        "next_review_at": next_review.astimezone(timezone.utc).isoformat(timespec="seconds") if next_review else "",
        "guardrail": "Recommendations never mutate Meta automatically; protected changes still require the existing approval flow.",
    }


def review_is_due(experiment, now=None):
    current_time = now or utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    due = parse_iso(experiment.get("next_review_at"))
    return bool(due and due <= current_time.astimezone(timezone.utc) and experiment.get("status") not in {"completed", "cancelled", "decision_ready"})


def run_due_reviews(insight_rows=None, campaign_metrics=None, experiment_id="", now=None):
    state = load_experiments()
    reviewed = []
    for experiment in state["experiments"]:
        if experiment_id and str(experiment.get("id")) != str(experiment_id):
            continue
        if not review_is_due(experiment, now):
            continue
        review = evaluate_experiment(experiment, insight_rows, campaign_metrics, now)
        experiment["status"] = review["status"]
        experiment["phase"] = review["phase"]
        experiment["next_review_at"] = review["next_review_at"]
        experiment["latest_review"] = review
        experiment["updated_at"] = review["reviewed_at"]
        experiment.setdefault("history", []).insert(0, review)
        experiment["history"] = experiment["history"][:30]
        reviewed.append({"experiment_id": experiment.get("id"), "name": experiment.get("name"), **review})
    if reviewed:
        save_experiments(state)
    return {"reviewed_count": len(reviewed), "reviews": reviewed, "experiments": state["experiments"]}


def experiment_review_payload(campaign_metrics=None, now=None):
    state = load_experiments()
    current_time = now or utc_now()
    summaries = []
    for experiment in state["experiments"][:30]:
        latest = experiment.get("latest_review") or {}
        summaries.append({
            "id": experiment.get("id"),
            "name": experiment.get("name"),
            "status": experiment.get("status"),
            "phase": experiment.get("phase"),
            "daily_budget": experiment.get("daily_budget"),
            "target_cpa": experiment.get("target_cpa"),
            "next_review_at": experiment.get("next_review_at", ""),
            "due": review_is_due(experiment, current_time),
            "summary": latest.get("summary") or "Primera revisión de entrega programada.",
            "leader": latest.get("leader"),
            "confidence": latest.get("confidence", "insufficient"),
            "recommendations": latest.get("recommendations", []),
        })
    active = [item for item in summaries if item.get("status") not in {"completed", "cancelled"}]
    next_dates = [parse_iso(item.get("next_review_at")) for item in active if parse_iso(item.get("next_review_at"))]
    return {
        "active_count": len(active),
        "due_count": len([item for item in active if item.get("due")]),
        "decision_ready_count": len([item for item in active if item.get("status") == "decision_ready"]),
        "next_review_at": min(next_dates).isoformat(timespec="seconds") if next_dates else "",
        "experiments": summaries,
        "storage_file": str(EXPERIMENTS_FILE.relative_to(ROOT_DIR)),
    }
