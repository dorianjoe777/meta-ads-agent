#!/usr/bin/env python3
"""Persistent profitability rules and decision memory for the ads manager."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from local_store import now_iso, read_json, write_json
from product_config import ROOT_DIR, load_config
from security import redact_payload


DATA_DIR = ROOT_DIR / "dashboard" / "data"
OUTPUT_DIR = ROOT_DIR / "output"
PROFITABILITY_RULES_FILE = DATA_DIR / "profitability_rules.json"
DECISION_MEMORY_FILE = DATA_DIR / "decision_memory.json"
LEARNING_LOG_FILE = OUTPUT_DIR / "learning-log.md"
MAX_DECISIONS = 250


def parse_iso(value):
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def utc_now():
    return datetime.now(timezone.utc)


def money(value):
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def pct_change(current, previous):
    current = float(current or 0)
    previous = float(previous or 0)
    if previous == 0:
        return 0.0
    return round(((current - previous) / previous) * 100, 1)


def default_profitability_rules():
    config = load_config()
    return {
        "target_cpa": money(getattr(config, "target_cpa", 50) or 50),
        "target_roas": 2.5,
        "min_spend_before_judging": money(getattr(config, "zero_conversion_spend", 50) or 50),
        "min_conversions_before_scaling": 3,
        "max_frequency_before_refresh": 3.0,
        "min_ctr_pct": 0.8,
        "max_cpa_multiplier": float(getattr(config, "high_cpa_multiplier", 3) or 3),
        "follow_up_windows_hours": [24, 72, 168],
        "notes": "Estas reglas ayudan al agente a explicar, decidir y revisar resultados sin inventar criterios.",
    }


def load_profitability_rules():
    rules = default_profitability_rules()
    saved = read_json(PROFITABILITY_RULES_FILE, {})
    if isinstance(saved, dict):
        for key, value in saved.items():
            if value is None or value == "":
                continue
            rules[key] = value
    rules["target_cpa"] = money(rules.get("target_cpa"))
    rules["target_roas"] = float(rules.get("target_roas") or 0)
    rules["min_spend_before_judging"] = money(rules.get("min_spend_before_judging"))
    rules["min_conversions_before_scaling"] = int(float(rules.get("min_conversions_before_scaling") or 0))
    rules["max_frequency_before_refresh"] = float(rules.get("max_frequency_before_refresh") or 0)
    rules["min_ctr_pct"] = float(rules.get("min_ctr_pct") or 0)
    rules["max_cpa_multiplier"] = float(rules.get("max_cpa_multiplier") or 0)
    windows = rules.get("follow_up_windows_hours")
    if not isinstance(windows, list) or not windows:
        windows = [24, 72, 168]
    rules["follow_up_windows_hours"] = [int(float(item)) for item in windows[:4] if float(item) > 0]
    return rules


def save_profitability_rules(payload):
    current = load_profitability_rules()
    numeric = {
        "target_cpa",
        "target_roas",
        "min_spend_before_judging",
        "min_conversions_before_scaling",
        "max_frequency_before_refresh",
        "min_ctr_pct",
        "max_cpa_multiplier",
    }
    next_rules = dict(current)
    for key in numeric:
        if key in payload:
            try:
                value = float(payload.get(key))
                next_rules[key] = int(value) if key == "min_conversions_before_scaling" else value
            except (TypeError, ValueError):
                pass
    if "notes" in payload:
        next_rules["notes"] = str(payload.get("notes") or "")[:600]
    if "follow_up_windows_hours" in payload:
        raw = payload.get("follow_up_windows_hours")
        if isinstance(raw, str):
            raw = [item.strip() for item in raw.split(",")]
        if isinstance(raw, list):
            windows = []
            for item in raw:
                try:
                    value = int(float(item))
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    windows.append(value)
            if windows:
                next_rules["follow_up_windows_hours"] = windows[:4]
    next_rules["updated_at"] = now_iso()
    write_json(PROFITABILITY_RULES_FILE, next_rules, ensure_ascii=False)
    return next_rules


def campaign_snapshot(campaign):
    return {
        "campaign_id": campaign.get("id") or campaign.get("campaign_id") or "",
        "campaign_name": campaign.get("name") or "",
        "status": campaign.get("status") or "",
        "spend": money(campaign.get("spend")),
        "revenue": money(campaign.get("revenue")),
        "conversions": int(float(campaign.get("conversions", 0) or 0)),
        "roas": round(float(campaign.get("roas", 0) or 0), 2),
        "cpa": money(campaign.get("cpa")),
        "ctr": round(float(campaign.get("ctr", 0) or 0), 2),
        "cpc": money(campaign.get("cpc")),
        "frequency": round(float(campaign.get("frequency", 0) or 0), 2),
        "daily_budget": money(campaign.get("daily_budget")),
        "health": campaign.get("health") or "",
    }


def evidence_for_campaign(campaign, action, rules=None):
    rules = rules or load_profitability_rules()
    snap = campaign_snapshot(campaign)
    target_cpa = float(rules.get("target_cpa") or 0)
    target_roas = float(rules.get("target_roas") or 0)
    max_cpa = target_cpa * float(rules.get("max_cpa_multiplier") or 3)
    signals = []
    if snap["roas"] >= target_roas and snap["cpa"] <= target_cpa:
        signals.append("gana dinero frente a tus reglas")
    if snap["roas"] < 1.2:
        signals.append("ROAS bajo")
    if target_cpa and snap["cpa"] > max_cpa:
        signals.append("CPA demasiado alto")
    if snap["spend"] >= float(rules.get("min_spend_before_judging") or 0) and snap["conversions"] == 0:
        signals.append("gastó sin compras")
    if snap["frequency"] >= float(rules.get("max_frequency_before_refresh") or 0):
        signals.append("posible cansancio por frecuencia")
    if snap["ctr"] and snap["ctr"] < float(rules.get("min_ctr_pct") or 0):
        signals.append("CTR bajo")
    if not signals:
        signals.append("se mantiene dentro de una zona de observación")

    if action == "increase_budget":
        diagnosis = "La campaña muestra señales para probar más presupuesto sin perder el control."
        recommendation = "Subir poco a poco y revisar otra vez antes de escalar más."
        risk = "Si el presupuesto sube demasiado rápido, el CPA puede subir."
        expected = "Más volumen manteniendo CPA y ROAS cerca de la línea actual."
    elif action == "decrease_budget":
        diagnosis = "La campaña no justifica el gasto actual con las reglas de rentabilidad."
        recommendation = "Bajar presupuesto o dejarla en observación corta antes de pausar."
        risk = "Bajar demasiado puede cortar ventas que aún estaban aprendiendo."
        expected = "Menos gasto desperdiciado mientras se confirma si recupera rendimiento."
    elif action == "pause":
        diagnosis = "La campaña está quemando presupuesto o mostrando fatiga clara."
        recommendation = "Pausar o preparar un reemplazo creativo antes de seguir gastando."
        risk = "Pausar puede cortar aprendizaje si el volumen de datos todavía es bajo."
        expected = "Proteger presupuesto y enfocar atención en mejores opciones."
    elif action == "creative_refresh":
        diagnosis = "El anuncio necesita una versión nueva para reducir fatiga o recuperar atención."
        recommendation = "Crear nuevas variantes manteniendo la oferta y cambiando el ángulo visual."
        risk = "Una variante nueva puede tardar en aprender; conviene compararla con la anterior."
        expected = "Mejor CTR o menor CPA si el problema era cansancio creativo."
    else:
        diagnosis = "La campaña requiere seguimiento antes de tocar dinero."
        recommendation = "Observar con la misma regla y volver a revisar en la próxima lectura."
        risk = "Actuar sin suficiente evidencia puede empeorar el resultado."
        expected = "Decidir con más claridad cuando haya más datos."

    return {
        "signal": "; ".join(signals),
        "diagnosis": diagnosis,
        "recommendation": recommendation,
        "risk": risk,
        "expected_impact": expected,
        "follow_up": "Revisar en 24h, 3 días y 7 días.",
        "baseline": snap,
    }


def recommendation_action(recommendation):
    change = float(recommendation.get("change_pct", 0) or 0)
    if change > 2:
        return "increase_budget"
    if change < -2:
        return "decrease_budget"
    return "observe"


def recommendation_decision_evidence(campaign, recommendation, rules=None):
    action = recommendation_action(recommendation)
    evidence = evidence_for_campaign(campaign, action, rules)
    evidence["suggested_action"] = action
    evidence["decision_type"] = "budget_change"
    return evidence


def fatigue_decision_evidence(campaign, fatigue_item, rules=None):
    evidence = evidence_for_campaign(campaign, "creative_refresh", rules)
    evidence["signal"] = "; ".join(fatigue_item.get("reasons") or []) or evidence["signal"]
    evidence["suggested_action"] = "creative_refresh"
    evidence["decision_type"] = "creative_refresh"
    return evidence


def load_decision_memory():
    memory = read_json(DECISION_MEMORY_FILE, {})
    if not isinstance(memory, dict):
        memory = {}
    memory.setdefault("updated_at", "")
    memory.setdefault("decisions", [])
    memory.setdefault("learning_log", [])
    return memory


def save_decision_memory(memory):
    memory["updated_at"] = now_iso()
    memory["decisions"] = list(memory.get("decisions", []))[:MAX_DECISIONS]
    memory["learning_log"] = list(memory.get("learning_log", []))[:MAX_DECISIONS]
    write_json(DECISION_MEMORY_FILE, redact_payload(memory), ensure_ascii=False)
    write_learning_log(memory)
    return memory


def due_check_schedule(created_at, windows):
    base = parse_iso(created_at) or utc_now()
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    checks = []
    for hours in windows:
        checks.append({
            "window_hours": int(hours),
            "due_at": (base + timedelta(hours=int(hours))).isoformat(timespec="seconds"),
            "status": "pending",
        })
    return checks


def decision_id(kind, campaign_id, created_at):
    date = (parse_iso(created_at) or utc_now()).strftime("%Y%m%d")
    safe_campaign = str(campaign_id or "account").replace(" ", "_")[:80]
    return f"decision_{date}_{kind}_{safe_campaign}"


def build_decision_record(kind, campaign, evidence, payload=None):
    created_at = now_iso()
    baseline = evidence.get("baseline") or campaign_snapshot(campaign)
    return {
        "id": decision_id(kind, baseline.get("campaign_id"), created_at),
        "kind": kind,
        "status": "observing",
        "created_at": created_at,
        "campaign_id": baseline.get("campaign_id"),
        "campaign_name": baseline.get("campaign_name"),
        "signal": evidence.get("signal"),
        "diagnosis": evidence.get("diagnosis"),
        "recommendation": evidence.get("recommendation"),
        "risk": evidence.get("risk"),
        "expected_impact": evidence.get("expected_impact"),
        "suggested_action": evidence.get("suggested_action"),
        "baseline": baseline,
        "payload": redact_payload(payload or {}),
        "checks": due_check_schedule(created_at, load_profitability_rules().get("follow_up_windows_hours", [24, 72, 168])),
    }


def find_campaign(metrics, campaign_id):
    for campaign in metrics.get("campaigns", []):
        if str(campaign.get("id")) == str(campaign_id):
            return campaign
    return None


def update_due_outcomes(memory, metrics):
    if not metrics:
        return memory
    now = utc_now()
    learning = list(memory.get("learning_log", []))
    for decision in memory.get("decisions", []):
        campaign = find_campaign(metrics, decision.get("campaign_id"))
        if not campaign:
            continue
        current = campaign_snapshot(campaign)
        for check in decision.get("checks", []):
            if check.get("status") == "done":
                continue
            due = parse_iso(check.get("due_at"))
            if not due:
                continue
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            if due > now:
                continue
            baseline = decision.get("baseline") or {}
            roas_delta = pct_change(current.get("roas"), baseline.get("roas"))
            cpa_delta = pct_change(current.get("cpa"), baseline.get("cpa"))
            spend_delta = pct_change(current.get("spend"), baseline.get("spend"))
            if roas_delta > 5 or cpa_delta < -5:
                outcome = "improved"
            elif roas_delta < -5 or cpa_delta > 5:
                outcome = "worse"
            else:
                outcome = "flat"
            check.update({
                "status": "done",
                "checked_at": now.isoformat(timespec="seconds"),
                "outcome": outcome,
                "current": current,
                "deltas": {"roas_pct": roas_delta, "cpa_pct": cpa_delta, "spend_pct": spend_delta},
            })
            learning.insert(0, {
                "created_at": now_iso(),
                "decision_id": decision.get("id"),
                "campaign_name": decision.get("campaign_name"),
                "window_hours": check.get("window_hours"),
                "outcome": outcome,
                "summary": outcome_summary(decision, check),
            })
    memory["learning_log"] = learning[:MAX_DECISIONS]
    return memory


def outcome_summary(decision, check):
    deltas = check.get("deltas") or {}
    label = {
        "improved": "mejoró frente al punto inicial",
        "worse": "empeoró frente al punto inicial",
        "flat": "quedó casi igual",
    }.get(check.get("outcome"), "quedó en observación")
    return (
        f"{decision.get('campaign_name')}: {label}. "
        f"ROAS {deltas.get('roas_pct', 0)}%, CPA {deltas.get('cpa_pct', 0)}%, gasto {deltas.get('spend_pct', 0)}%."
    )


def record_daily_decision_memory(metrics, recommendations, fatigue, proposed_pauses=None, auto_paused=None, creative_refreshes=None):
    rules = load_profitability_rules()
    memory = update_due_outcomes(load_decision_memory(), metrics)
    existing = {item.get("id") for item in memory.get("decisions", [])}
    campaigns_by_id = {str(c.get("id")): c for c in metrics.get("campaigns", [])}
    new_records = []
    for rec in recommendations[:12]:
        campaign = campaigns_by_id.get(str(rec.get("campaign_id")))
        if not campaign:
            continue
        evidence = rec.get("decision_evidence") or recommendation_decision_evidence(campaign, rec, rules)
        record = build_decision_record("budget_change", campaign, evidence, rec)
        if record["id"] not in existing:
            new_records.append(record)
            existing.add(record["id"])
    for item in fatigue[:8]:
        campaign = campaigns_by_id.get(str(item.get("campaign_id")))
        if not campaign:
            continue
        evidence = fatigue_decision_evidence(campaign, item, rules)
        record = build_decision_record("creative_refresh", campaign, evidence, item)
        if record["id"] not in existing:
            new_records.append(record)
            existing.add(record["id"])
    for item in (proposed_pauses or []) + (auto_paused or []):
        campaign = campaigns_by_id.get(str(item.get("campaign_id")))
        if not campaign:
            continue
        evidence = evidence_for_campaign(campaign, "pause", rules)
        record = build_decision_record("pause", campaign, evidence, item)
        if record["id"] not in existing:
            new_records.append(record)
            existing.add(record["id"])
    memory["decisions"] = new_records + list(memory.get("decisions", []))
    memory["recent_creative_refreshes"] = creative_refreshes or []
    return save_decision_memory(memory)


def decision_cards(metrics=None, recommendations=None, fatigue=None):
    metrics = metrics or {}
    recommendations = recommendations or []
    fatigue = fatigue or []
    campaigns_by_id = {str(c.get("id")): c for c in metrics.get("campaigns", [])}
    rules = load_profitability_rules()
    cards = []
    for rec in recommendations[:6]:
        campaign = campaigns_by_id.get(str(rec.get("campaign_id")))
        if not campaign:
            continue
        evidence = rec.get("decision_evidence") or recommendation_decision_evidence(campaign, rec, rules)
        cards.append({
            "type": "budget_change",
            "campaign_id": rec.get("campaign_id"),
            "campaign_name": rec.get("campaign_name"),
            "title": "Presupuesto con evidencia",
            "signal": evidence.get("signal"),
            "diagnosis": evidence.get("diagnosis"),
            "recommendation": evidence.get("recommendation"),
            "risk": evidence.get("risk"),
            "expected_impact": evidence.get("expected_impact"),
            "requires_approval": bool(rec.get("requires_approval")),
        })
    for item in fatigue[:4]:
        campaign = campaigns_by_id.get(str(item.get("campaign_id")))
        if not campaign:
            continue
        evidence = fatigue_decision_evidence(campaign, item, rules)
        cards.append({
            "type": "creative_refresh",
            "campaign_id": item.get("campaign_id"),
            "campaign_name": item.get("campaign_name"),
            "title": "Cansancio creativo",
            "signal": evidence.get("signal"),
            "diagnosis": evidence.get("diagnosis"),
            "recommendation": evidence.get("recommendation"),
            "risk": evidence.get("risk"),
            "expected_impact": evidence.get("expected_impact"),
            "requires_approval": False,
        })
    return cards[:8]


def decision_memory_payload(metrics=None, recommendations=None, fatigue=None):
    memory = update_due_outcomes(load_decision_memory(), metrics or {})
    save_decision_memory(memory)
    pending_checks = []
    for decision in memory.get("decisions", [])[:40]:
        for check in decision.get("checks", []):
            if check.get("status") == "pending":
                pending_checks.append({
                    "decision_id": decision.get("id"),
                    "campaign_name": decision.get("campaign_name"),
                    "window_hours": check.get("window_hours"),
                    "due_at": check.get("due_at"),
                })
    return {
        "profitability_rules": load_profitability_rules(),
        "cards": decision_cards(metrics, recommendations, fatigue),
        "recent_decisions": memory.get("decisions", [])[:12],
        "learning_log": memory.get("learning_log", [])[:12],
        "pending_checks": pending_checks[:12],
        "memory_file": safe_display_path(DECISION_MEMORY_FILE),
        "learning_log_file": safe_display_path(LEARNING_LOG_FILE),
    }


def safe_display_path(path):
    path = Path(path)
    try:
        return str(path.relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def write_learning_log(memory):
    lines = ["# Learning Log", "", "What the agent recommended, what happened later, and what it should remember.", ""]
    for item in list(memory.get("learning_log", []))[:80]:
        lines.append(f"- {item.get('created_at', '')}: {item.get('summary', '')}")
    LEARNING_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LEARNING_LOG_FILE.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def format_learning_log(memory=None, limit=12):
    memory = memory or load_decision_memory()
    lines = []
    for item in list(memory.get("learning_log", []))[:limit]:
        lines.append(f"- {item.get('summary', '')}")
    return "\n".join(lines) or "No hay aprendizajes cerrados todavía."
