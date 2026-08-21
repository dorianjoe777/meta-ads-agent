#!/usr/bin/env python3
"""Local verified-signal ledger for human-confirmed ad quality outcomes.

This module is intentionally local-first. It does not send anything to Meta.
It stores enough normalized structure for the agent to reason about lead quality,
deduplication, event volume, and future CAPI/CRM sends, while avoiding raw
email/phone storage by default.
"""

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from local_store import now_iso, read_json, write_private_json


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER_FILE = ROOT_DIR / "dashboard" / "data" / "verified_signal_ledger.json"
SCHEMA_VERSION = 1
MAX_EVENTS = 5000

POSITIVE_STAGES = {"contact", "lead", "qualified", "booked", "showed", "purchased", "high_value"}
NEGATIVE_STAGES = {"fake", "confused", "not_interested", "wrong_audience", "bad_fit", "lost", "no_show", "refunded"}
OPEN_FOLLOWUP_STAGES = {"contact", "lead", "qualified", "still_talking"}
FINAL_STAGES = {"purchased", "high_value", "lost", "no_show", "refunded"}

STAGE_ALIASES = {
    "normal": "contact",
    "assumed_normal": "contact",
    "contacted": "contact",
    "real_contact": "contact",
    "interested": "lead",
    "real_lead": "lead",
    "qualified_lead": "qualified",
    "qualified": "qualified",
    "book": "booked",
    "booking": "booked",
    "booked": "booked",
    "reservation": "booked",
    "reserved": "booked",
    "schedule": "booked",
    "scheduled": "booked",
    "appointment": "booked",
    "show": "showed",
    "showed": "showed",
    "showed_up": "showed",
    "attended": "showed",
    "bought": "purchased",
    "purchase": "purchased",
    "purchased": "purchased",
    "sale": "purchased",
    "sold": "purchased",
    "high_value": "high_value",
    "vip": "high_value",
    "fake": "fake",
    "spam": "fake",
    "bot": "fake",
    "confused": "confused",
    "mistake": "confused",
    "not_interested": "not_interested",
    "not interested": "not_interested",
    "no_interesado": "not_interested",
    "wrong_audience": "wrong_audience",
    "wrong audience": "wrong_audience",
    "fuera_de_audiencia": "wrong_audience",
    "bad_fit": "bad_fit",
    "lost": "lost",
    "closed_lost": "lost",
    "no_show": "no_show",
    "noshow": "no_show",
    "refunded": "refunded",
    "refund": "refunded",
    "still_talking": "still_talking",
    "nurturing": "still_talking",
}

META_STANDARD_EVENT_BY_STAGE = {
    "contact": "Contact",
    "lead": "Lead",
    "qualified": "Lead",
    "booked": "Schedule",
    "purchased": "Purchase",
    "high_value": "Purchase",
}

QUALITY_SCORE_BY_STAGE = {
    "fake": -1.0,
    "confused": -0.8,
    "not_interested": -0.7,
    "wrong_audience": -0.9,
    "bad_fit": -0.8,
    "lost": -0.5,
    "no_show": -0.4,
    "refunded": -0.6,
    "contact": 0.35,
    "lead": 0.55,
    "qualified": 0.72,
    "booked": 0.85,
    "showed": 0.9,
    "purchased": 1.0,
    "high_value": 1.0,
    "still_talking": 0.45,
}

HASHED_IDENTIFIER_FIELDS = {
    "email": "email_sha256",
    "phone": "phone_sha256",
    "external_id": "external_id_sha256",
}

RAW_MATCH_ID_FIELDS = {
    "lead_id",
    "source_contact_id",
    "booking_id",
    "order_id",
    "crm_id",
    "event_id",
    "fbp",
    "fbc",
    "fbclid",
    "ctwa_clid",
}


def _clean_text(value, limit=160):
    text = str(value or "").strip()
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text[:limit]


def _clean_key(value):
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _sha256(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _normalize_email(value):
    return str(value or "").strip().lower()


def _normalize_phone(value):
    digits = re.sub(r"\D+", "", str(value or ""))
    return digits


def _normalize_identifier(kind, value):
    if kind == "email":
        return _normalize_email(value)
    if kind == "phone":
        return _normalize_phone(value)
    return str(value or "").strip()


def normalize_stage(value):
    key = _clean_key(value)
    return STAGE_ALIASES.get(key, key if key in QUALITY_SCORE_BY_STAGE else "lead")


def canonical_event_time(value=None):
    raw = str(value or "").strip()
    if not raw:
        return now_iso()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone().isoformat(timespec="seconds")
    except ValueError:
        return now_iso()


def _event_date(event_time):
    return str(event_time or "")[:10] or now_iso()[:10]


def _payload_identifiers(payload):
    identifiers = payload.get("identifiers") if isinstance(payload.get("identifiers"), dict) else {}
    merged = dict(identifiers)
    for field in HASHED_IDENTIFIER_FIELDS:
        if payload.get(field) and not merged.get(field):
            merged[field] = payload.get(field)
    for field in RAW_MATCH_ID_FIELDS:
        if payload.get(field) and not merged.get(field):
            merged[field] = payload.get(field)
    return merged


def normalize_match_data(payload):
    identifiers = _payload_identifiers(payload or {})
    hashed = {}
    raw_match_ids = {}
    identifier_presence = []
    for field, output_field in HASHED_IDENTIFIER_FIELDS.items():
        normalized = _normalize_identifier(field, identifiers.get(field))
        if normalized:
            hashed[output_field] = _sha256(normalized)
            identifier_presence.append(field)
    for field in RAW_MATCH_ID_FIELDS:
        value = _clean_text(identifiers.get(field), limit=240)
        if value:
            raw_match_ids[field] = value
            identifier_presence.append(field)
    match_score = min(1.0, round(0.18 * len(identifier_presence), 2))
    if hashed.get("email_sha256") or hashed.get("phone_sha256"):
        match_score = max(match_score, 0.45)
    if raw_match_ids.get("fbc") or raw_match_ids.get("fbclid") or raw_match_ids.get("ctwa_clid"):
        match_score = max(match_score, 0.65)
    if raw_match_ids.get("lead_id") or raw_match_ids.get("order_id") or raw_match_ids.get("booking_id"):
        match_score = max(match_score, 0.75)
    return {
        "hashed": hashed,
        "raw_match_ids": raw_match_ids,
        "identifier_presence": sorted(set(identifier_presence)),
        "match_score": min(1.0, match_score),
        "contains_customer_identifiers": bool(hashed or raw_match_ids),
    }


def _person_key(match_data, payload):
    raw_ids = match_data.get("raw_match_ids") or {}
    hashed = match_data.get("hashed") or {}
    for field in ("lead_id", "order_id", "booking_id", "crm_id", "source_contact_id", "ctwa_clid"):
        if raw_ids.get(field):
            return f"{field}:{raw_ids[field]}"
    for field in ("phone_sha256", "email_sha256", "external_id_sha256"):
        if hashed.get(field):
            return f"{field}:{hashed[field]}"
    label = _clean_text(payload.get("person_label") or payload.get("name") or payload.get("display_name"), limit=80)
    if label:
        return f"label:{_sha256(label.lower())[:24]}"
    return ""


def _dedupe_key(payload, stage, event_time, match_data):
    explicit = _clean_text(payload.get("dedupe_key"), limit=240)
    if explicit:
        return explicit
    raw_ids = match_data.get("raw_match_ids") or {}
    for field in ("event_id", "order_id", "booking_id", "lead_id"):
        if raw_ids.get(field):
            return f"{field}:{raw_ids[field]}:{stage}"
    person_key = _person_key(match_data, payload)
    source = _clean_key(payload.get("source_system") or payload.get("source") or "manual")
    campaign = _clean_text(payload.get("campaign_id"), limit=120)
    ad = _clean_text(payload.get("ad_id"), limit=120)
    if person_key:
        return f"{source}:{person_key}:{stage}:{_event_date(event_time)}:{campaign}:{ad}"
    basis = "|".join([
        source,
        stage,
        _event_date(event_time),
        _clean_text(payload.get("person_label") or payload.get("notes"), limit=80),
        campaign,
        ad,
    ])
    return "generated:" + _sha256(basis)[:32]


def load_ledger(path=DEFAULT_LEDGER_FILE):
    payload = read_json(path, {})
    if not isinstance(payload, dict):
        payload = {}
    events = payload.get("events") if isinstance(payload.get("events"), list) else []
    return {"schema_version": SCHEMA_VERSION, "events": [e for e in events if isinstance(e, dict)][-MAX_EVENTS:]}


def save_ledger(payload, path=DEFAULT_LEDGER_FILE):
    clean = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": now_iso(),
        "events": list((payload or {}).get("events") or [])[-MAX_EVENTS:],
    }
    write_private_json(path, clean, ensure_ascii=False)
    return clean


def normalize_signal_record(payload):
    payload = payload if isinstance(payload, dict) else {}
    stage = normalize_stage(payload.get("stage") or payload.get("outcome") or payload.get("status") or "lead")
    event_time = canonical_event_time(payload.get("event_time") or payload.get("timestamp"))
    match_data = normalize_match_data(payload)
    standard_event = _clean_text(payload.get("meta_event_name") or payload.get("event_name"), limit=80)
    if not standard_event:
        standard_event = META_STANDARD_EVENT_BY_STAGE.get(stage, "")
    source = _clean_key(payload.get("source_system") or payload.get("source") or "manual")
    privacy_confirmed = bool(payload.get("privacy_confirmed") or payload.get("privacy_notice_confirmed") or False)
    record = {
        "id": "vsl_" + _sha256(f"{_dedupe_key(payload, stage, event_time, match_data)}:{event_time}")[:24],
        "dedupe_key": _dedupe_key(payload, stage, event_time, match_data),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "event_time": event_time,
        "event_date": _event_date(event_time),
        "source_system": source,
        "source_type": _clean_key(payload.get("source_type") or ""),
        "stage": stage,
        "quality_score": QUALITY_SCORE_BY_STAGE.get(stage, 0.0),
        "meta_event_name": standard_event,
        "meta_send_eligible": bool(standard_event and stage in POSITIVE_STAGES),
        "meta_send_status": "not_ready",
        "privacy_notice_confirmed": privacy_confirmed,
        "person_label": _clean_text(payload.get("person_label") or payload.get("name") or payload.get("display_name"), limit=120),
        "campaign_id": _clean_text(payload.get("campaign_id"), limit=120),
        "adset_id": _clean_text(payload.get("adset_id"), limit=120),
        "ad_id": _clean_text(payload.get("ad_id"), limit=120),
        "creative_id": _clean_text(payload.get("creative_id"), limit=120),
        "value": _numeric_or_none(payload.get("value")),
        "currency": _clean_text(payload.get("currency") or "USD", limit=12).upper(),
        "notes": _clean_text(payload.get("notes"), limit=500),
        "match": match_data,
        "human_confirmed": bool(payload.get("human_confirmed", True)),
        "confidence": _confidence(stage, match_data, privacy_confirmed),
        "seen_count": 1,
    }
    if record["meta_send_eligible"] and privacy_confirmed and match_data.get("contains_customer_identifiers"):
        record["meta_send_status"] = "ready"
    return record


def _numeric_or_none(value):
    if value in (None, ""):
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _confidence(stage, match_data, privacy_confirmed):
    base = 0.35
    if stage in POSITIVE_STAGES or stage in NEGATIVE_STAGES:
        base = 0.55
    base += float(match_data.get("match_score") or 0) * 0.35
    if privacy_confirmed:
        base += 0.05
    return min(1.0, round(base, 2))


def public_record(record, include_match=False):
    public = {
        "id": record.get("id"),
        "dedupe_key": record.get("dedupe_key"),
        "event_time": record.get("event_time"),
        "event_date": record.get("event_date"),
        "source_system": record.get("source_system"),
        "stage": record.get("stage"),
        "quality_score": record.get("quality_score"),
        "meta_event_name": record.get("meta_event_name"),
        "meta_send_eligible": record.get("meta_send_eligible"),
        "meta_send_status": record.get("meta_send_status"),
        "privacy_notice_confirmed": record.get("privacy_notice_confirmed"),
        "person_label": record.get("person_label"),
        "campaign_id": record.get("campaign_id"),
        "adset_id": record.get("adset_id"),
        "ad_id": record.get("ad_id"),
        "creative_id": record.get("creative_id"),
        "value": record.get("value"),
        "currency": record.get("currency"),
        "notes": record.get("notes"),
        "human_confirmed": record.get("human_confirmed"),
        "confidence": record.get("confidence"),
        "seen_count": record.get("seen_count", 1),
    }
    if include_match:
        match = record.get("match") if isinstance(record.get("match"), dict) else {}
        public["match"] = {
            "identifier_presence": match.get("identifier_presence", []),
            "match_score": match.get("match_score", 0),
            "contains_customer_identifiers": bool(match.get("contains_customer_identifiers")),
            "hashed_identifier_count": len(match.get("hashed") or {}),
            "raw_match_id_count": len(match.get("raw_match_ids") or {}),
        }
    return public


def record_signal(payload, path=DEFAULT_LEDGER_FILE):
    ledger = load_ledger(path)
    record = normalize_signal_record(payload)
    events = list(ledger.get("events") or [])
    deduped = False
    for index, existing in enumerate(events):
        if existing.get("dedupe_key") == record["dedupe_key"]:
            merged = {**existing, **record}
            merged["id"] = existing.get("id") or record["id"]
            merged["created_at"] = existing.get("created_at") or record["created_at"]
            merged["seen_count"] = int(existing.get("seen_count") or 1) + 1
            merged["updated_at"] = now_iso()
            events[index] = merged
            record = merged
            deduped = True
            break
    if not deduped:
        events.append(record)
    saved = save_ledger({"events": events}, path)
    return {
        "saved": True,
        "deduped": deduped,
        "record": public_record(record, include_match=True),
        "summary": ledger_summary(path, saved),
    }


def record_signal_batch(items, path=DEFAULT_LEDGER_FILE):
    results = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict):
            results.append(record_signal(item, path))
    return {
        "saved": True,
        "count": len(results),
        "deduped_count": sum(1 for result in results if result.get("deduped")),
        "records": [result.get("record") for result in results],
        "summary": ledger_summary(path),
    }


def ledger_summary(path=DEFAULT_LEDGER_FILE, ledger=None):
    ledger = ledger if isinstance(ledger, dict) else load_ledger(path)
    events = [event for event in ledger.get("events", []) if isinstance(event, dict)]
    by_stage = {}
    by_meta_event = {}
    by_campaign = {}
    ready_to_send = 0
    privacy_needed = 0
    matched_events = 0
    open_followups = 0
    for event in events:
        stage = event.get("stage") or "unknown"
        by_stage[stage] = by_stage.get(stage, 0) + 1
        meta_event = event.get("meta_event_name") or "internal_only"
        by_meta_event[meta_event] = by_meta_event.get(meta_event, 0) + 1
        campaign = event.get("campaign_id") or "unknown"
        by_campaign[campaign] = by_campaign.get(campaign, 0) + 1
        match = event.get("match") if isinstance(event.get("match"), dict) else {}
        if match.get("contains_customer_identifiers"):
            matched_events += 1
            if not event.get("privacy_notice_confirmed"):
                privacy_needed += 1
        if event.get("meta_send_status") == "ready":
            ready_to_send += 1
        if stage in OPEN_FOLLOWUP_STAGES:
            open_followups += 1
    return {
        "schema_version": SCHEMA_VERSION,
        "total_events": len(events),
        "by_stage": by_stage,
        "by_meta_event": by_meta_event,
        "by_campaign": by_campaign,
        "positive_events": sum(by_stage.get(stage, 0) for stage in POSITIVE_STAGES),
        "negative_events": sum(by_stage.get(stage, 0) for stage in NEGATIVE_STAGES),
        "open_followups": open_followups,
        "matched_events": matched_events,
        "privacy_confirmation_needed": privacy_needed,
        "ready_to_send_to_meta": ready_to_send,
        "recent": [public_record(event, include_match=True) for event in events[-20:]][::-1],
    }


def feedback_prompt(path=DEFAULT_LEDGER_FILE, language="es"):
    summary = ledger_summary(path)
    total = summary.get("total_events", 0)
    open_followups = summary.get("open_followups", 0)
    if str(language or "es").lower().startswith("en"):
        message = (
            f"I organized {total} verified-signal records locally. "
            "For today's quality check, mark only exceptions and important outcomes: fake/confused/not-interested/wrong-audience people, "
            "and anyone who booked, showed up, purchased, or became high value. "
            f"Also tell me if any previous lead moved forward today. Open follow-ups: {open_followups}."
        )
    else:
        message = (
            f"Organicé {total} señales verificadas en el registro local. "
            "Para la revisión de hoy, marca solo excepciones y resultados importantes: personas falsas/confundidas/no interesadas/fuera de audiencia, "
            "y cualquiera que reservó, asistió, compró o fue de alto valor. "
            f"También dime si algún lead de días anteriores avanzó hoy. Seguimientos abiertos: {open_followups}."
        )
    return {"message": message, "summary": summary}
