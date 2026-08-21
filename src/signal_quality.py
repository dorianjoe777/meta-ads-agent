#!/usr/bin/env python3
"""Signal-quality diagnostics for Meta Ads event setup and optimization choice.

This module is deliberately read-only. It separates what Admira can safely set
inside a staged campaign draft from what must be fixed in Meta Events Manager,
the website/server integration, or the commerce/CRM stack.
"""
from datetime import datetime, timezone


SALES_EVENTS = ["Purchase", "InitiateCheckout", "AddToCart", "ViewContent"]
LEAD_EVENTS = ["Lead", "CompleteRegistration", "Contact"]
MESSAGE_EVENTS = ["MessagingConversationStarted"]
TRAFFIC_EVENTS = ["LandingPageView", "ViewContent"]

OBJECTIVE_RULES = {
    "sales": {
        "label": "ventas",
        "primary_event": "Purchase",
        "fallback_events": SALES_EVENTS[1:],
        "valid_events": set(SALES_EVENTS),
        "optimization_goal": "OFFSITE_CONVERSIONS",
        "volume_label": "compras",
    },
    "leads": {
        "label": "leads",
        "primary_event": "Lead",
        "fallback_events": LEAD_EVENTS[1:],
        "valid_events": set(LEAD_EVENTS),
        "optimization_goal": "LEAD_GENERATION",
        "volume_label": "leads",
    },
    "messages": {
        "label": "mensajes",
        "primary_event": "MessagingConversationStarted",
        "fallback_events": [],
        "valid_events": set(MESSAGE_EVENTS),
        "optimization_goal": "CONVERSATIONS",
        "volume_label": "conversaciones",
    },
    "traffic": {
        "label": "tráfico",
        "primary_event": "LandingPageView",
        "fallback_events": ["ViewContent"],
        "valid_events": set(TRAFFIC_EVENTS),
        "optimization_goal": "LANDING_PAGE_VIEWS",
        "volume_label": "visitas de calidad",
    },
    "engagement": {
        "label": "interacción",
        "primary_event": "PostEngagement",
        "fallback_events": [],
        "valid_events": {"PostEngagement"},
        "optimization_goal": "POST_ENGAGEMENT",
        "volume_label": "interacciones",
    },
    "awareness": {
        "label": "reconocimiento",
        "primary_event": "Reach",
        "fallback_events": ["Impressions"],
        "valid_events": {"Reach", "Impressions"},
        "optimization_goal": "REACH",
        "volume_label": "personas alcanzadas",
    },
    "video": {
        "label": "reproducciones de video",
        "primary_event": "ThruPlay",
        "fallback_events": ["VideoView"],
        "valid_events": {"ThruPlay", "VideoView"},
        "optimization_goal": "THRUPLAY",
        "volume_label": "reproducciones",
    },
    "app_promotion": {
        "label": "instalaciones de aplicación",
        "primary_event": "AppInstall",
        "fallback_events": ["AppActivation"],
        "valid_events": {"AppInstall", "AppActivation"},
        "optimization_goal": "APP_INSTALLS",
        "volume_label": "instalaciones",
    },
}

EVENT_ALIASES = {
    "purchase": "Purchase",
    "purchases": "Purchase",
    "compra": "Purchase",
    "compras": "Purchase",
    "omni_purchase": "Purchase",
    "offsite_conversion.fb_pixel_purchase": "Purchase",
    "initiatecheckout": "InitiateCheckout",
    "initiatedcheckout": "InitiateCheckout",
    "initiate_checkout": "InitiateCheckout",
    "initiated_checkout": "InitiateCheckout",
    "offsite_conversion.fb_pixel_initiate_checkout": "InitiateCheckout",
    "offsite_conversion.fb_pixel_initiated_checkout": "InitiateCheckout",
    "checkout": "InitiateCheckout",
    "inicio de pago": "InitiateCheckout",
    "addtocart": "AddToCart",
    "add_to_cart": "AddToCart",
    "offsite_conversion.fb_pixel_add_to_cart": "AddToCart",
    "carrito": "AddToCart",
    "agregar al carrito": "AddToCart",
    "viewcontent": "ViewContent",
    "view_content": "ViewContent",
    "offsite_conversion.fb_pixel_view_content": "ViewContent",
    "ver contenido": "ViewContent",
    "landingpageview": "LandingPageView",
    "landing_page_view": "LandingPageView",
    "visita": "LandingPageView",
    "lead": "Lead",
    "leads": "Lead",
    "offsite_conversion.fb_pixel_lead": "Lead",
    "contacto": "Lead",
    "complete registration": "CompleteRegistration",
    "complete_registration": "CompleteRegistration",
    "completeregistration": "CompleteRegistration",
    "registro": "CompleteRegistration",
    "contact": "Contact",
    "mensaje": "MessagingConversationStarted",
    "mensajes": "MessagingConversationStarted",
    "message": "MessagingConversationStarted",
    "messages": "MessagingConversationStarted",
    "conversation": "MessagingConversationStarted",
    "conversacion": "MessagingConversationStarted",
    "conversación": "MessagingConversationStarted",
    "onsite_conversion.messaging_conversation_started_7d": "MessagingConversationStarted",
}

META_CUSTOM_EVENT_TYPES = {
    "Purchase": "PURCHASE",
    "InitiateCheckout": "INITIATED_CHECKOUT",
    "AddToCart": "ADD_TO_CART",
    "ViewContent": "VIEW_CONTENT",
    "Lead": "LEAD",
    "CompleteRegistration": "COMPLETE_REGISTRATION",
    "Contact": "CONTACT",
}

TRUTHY = {"1", "true", "yes", "si", "sí", "on", "configured", "ready", "ok", "connected"}
FALSY = {"0", "false", "no", "off", "missing", "not_configured", "none"}


def number(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def boolish(value):
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in TRUTHY:
        return True
    if text in FALSY:
        return False
    return None


def normalize_objective(value):
    raw = str(value or "").strip().lower()
    if any(term in raw for term in ("message", "conversation", "whatsapp", "messenger", "mensaje")):
        return "messages"
    if any(term in raw for term in ("lead", "contact", "registration", "form", "cliente potencial", "registro")):
        return "leads"
    if any(term in raw for term in ("awareness", "reach", "reconocimiento", "alcance", "notoriedad")):
        return "awareness"
    if any(term in raw for term in ("video", "thruplay", "reproducción", "reproduccion", "views", "video views")):
        return "video"
    if any(term in raw for term in ("app promotion", "app_promotion", "app install", "instalación de app", "instalacion de app")):
        return "app_promotion"
    if any(term in raw for term in ("engagement", "interaction", "interacción", "interaccion", "post engagement", "participación", "participacion")):
        return "engagement"
    if any(term in raw for term in ("traffic", "landing", "link", "visita", "tráfico", "trafico")):
        return "traffic"
    if any(term in raw for term in ("purchase", "conversion", "sales", "sale", "compra", "venta", "ventas", "purchases")):
        return "sales"
    return "sales"


def normalize_event(value):
    text = str(value or "").strip()
    if not text:
        return ""
    key = text.lower().replace("-", "_").strip()
    compact = key.replace(" ", "").replace("_", "")
    if key in EVENT_ALIASES:
        return EVENT_ALIASES[key]
    if compact in EVENT_ALIASES:
        return EVENT_ALIASES[compact]
    for canonical in set().union(*(rule["valid_events"] for rule in OBJECTIVE_RULES.values())):
        if compact == canonical.lower():
            return canonical
    return text[:80]


def meta_custom_event_type(value):
    event = normalize_event(value)
    if event in META_CUSTOM_EVENT_TYPES:
        return META_CUSTOM_EVENT_TYPES[event]
    text = str(value or "").strip().upper()
    return text[:80]


def first_value(payload, keys):
    for key in keys:
        value = (payload or {}).get(key)
        if value is not None and value != "":
            return value
    return None


def parse_emq(value):
    numeric = number(value)
    if numeric is not None:
        return numeric
    text = str(value or "").strip().lower()
    if text in {"great", "excelente", "alto", "high"}:
        return 8.0
    if text in {"good", "bueno"}:
        return 6.0
    if text in {"poor", "bajo", "low"}:
        return 3.0
    return None


def recent_metric_volume(metrics, payload):
    if not isinstance(metrics, dict):
        return None
    wanted_id = str(first_value(payload, ["campaign_id", "adset_id", "target_id"]) or "").strip()
    rows = metrics.get("campaigns") or []
    if wanted_id:
        for row in rows:
            if str(row.get("id") or row.get("campaign_id") or row.get("adset_id") or "") == wanted_id:
                value = number(row.get("conversions"))
                if value is not None:
                    return value
    summary = metrics.get("summary") or {}
    return number(summary.get("total_conversions"))


def explicit_or_estimated_weekly_volume(payload, metrics=None):
    explicit = first_value(
        payload,
        [
            "weekly_event_volume",
            "weekly_conversions",
            "recent_weekly_events",
            "recent_event_count",
            "event_volume",
            "conversion_volume",
        ],
    )
    value = number(explicit)
    if value is not None:
        return round(value, 2), "provided"

    metric_volume = recent_metric_volume(metrics, payload)
    if metric_volume is not None:
        return round(metric_volume, 2), "meta_metrics"

    daily_budget = number(first_value(payload, ["daily_budget", "budget_daily"]))
    target_cost = number(first_value(payload, ["target_cpa", "target_cpl", "target_cost_per_result"]))
    if daily_budget and target_cost and target_cost > 0:
        return round((daily_budget * 7) / target_cost, 2), "budget_estimate"

    return None, "unknown"


def add_check(checks, key, label, status, detail, *, can_auto=False, action="", owner="agent"):
    checks.append(
        {
            "key": key,
            "label": label,
            "status": status,
            "detail": detail,
            "can_auto_optimize": bool(can_auto),
            "recommended_action": action,
            "owner": owner,
        }
    )


def choose_recommended_event(rule, selected_event, weekly_volume):
    primary = rule["primary_event"]
    if weekly_volume is None:
        return selected_event if selected_event in rule["valid_events"] else primary
    if weekly_volume >= 50:
        return primary
    if selected_event in rule["valid_events"] and selected_event != primary:
        return selected_event
    fallback = (rule.get("fallback_events") or [primary])[0]
    return fallback


def event_requires_dataset(event):
    return event not in {
        "MessagingConversationStarted",
        "LandingPageView",
        "PostEngagement",
        "Reach",
        "Impressions",
        "ThruPlay",
        "VideoView",
        "AppInstall",
        "AppActivation",
    }


def review_signal_quality(payload=None, metrics=None, language="es"):
    payload = dict(payload or {})
    objective = normalize_objective(first_value(payload, ["objective", "campaign_objective", "goal", "result_type"]))
    rule = OBJECTIVE_RULES[objective]
    selected_event = normalize_event(first_value(payload, ["optimization_event", "conversion_event", "event_name", "custom_event_type"]))
    weekly_volume, volume_source = explicit_or_estimated_weekly_volume(payload, metrics)
    recommended_event = choose_recommended_event(rule, selected_event, weekly_volume)
    if not selected_event:
        selected_event = recommended_event

    pixel_id = str(first_value(payload, ["pixel_id", "dataset_id", "data_set_id"]) or "").strip()
    capi = boolish(first_value(payload, ["capi_configured", "conversions_api_configured", "conversion_api", "capi"]))
    aem = boolish(first_value(payload, ["aem_configured", "aggregated_event_measurement_configured", "aem"]))
    prioritized = boolish(first_value(payload, ["event_prioritized", "event_priority_configured", "event_prioritization_configured"]))
    emq = parse_emq(first_value(payload, ["event_match_quality", "emq", "emq_score"]))

    checks = []
    valid = selected_event in rule["valid_events"]
    if valid and selected_event == recommended_event:
        add_check(checks, "correct_optimization_event", "Correct optimization event", "ok", f"Use {recommended_event} for a {rule['label']} objective.", can_auto=True, action=f"Set optimization_event={recommended_event}.")
    elif valid:
        add_check(checks, "correct_optimization_event", "Correct optimization event", "warn", f"{selected_event} matches the objective, but current volume suggests testing {recommended_event} before forcing {rule['primary_event']}.", can_auto=True, action=f"Prepare {recommended_event} as the draft optimization event unless the buyer confirms {selected_event}.")
    else:
        add_check(checks, "correct_optimization_event", "Correct optimization event", "blocked", f"{selected_event or 'No event'} does not match a {rule['label']} objective.", can_auto=True, action=f"Change the staged optimization event to {recommended_event}.")

    if event_requires_dataset(recommended_event):
        if pixel_id:
            add_check(checks, "pixel_or_dataset", "Pixel/Dataset selected", "ok", "A Pixel/Dataset ID is available for the conversion event.", can_auto=True, action="Attach it to the promoted_object/event configuration.")
        else:
            add_check(checks, "pixel_or_dataset", "Pixel/Dataset selected", "blocked", "A web conversion event needs the correct Pixel/Dataset before launch.", action="Ask for the Pixel/Dataset ID or guide the buyer to connect it.", owner="buyer_or_setup")
    else:
        add_check(checks, "pixel_or_dataset", "Pixel/Dataset selected", "ok", f"{recommended_event} can be optimized without a web Pixel event.", can_auto=True, action="Use the objective-native event.")

    if capi is True:
        add_check(checks, "conversions_api", "Conversions API", "ok", "CAPI is marked as configured; keep Pixel/CAPI deduplication healthy.", action="Verify event_id deduplication during QA.", owner="buyer_or_setup")
    elif capi is False:
        add_check(checks, "conversions_api", "Conversions API", "warn", "CAPI is not configured. Meta can still run, but attribution and matching are weaker.", action="Set up server events with event_id deduplication, fbp/fbc, IP, user agent, and hashed identifiers where consent allows.", owner="buyer_or_setup")
    else:
        add_check(checks, "conversions_api", "Conversions API", "warn", "CAPI status is unknown.", action="Check Events Manager or the ecommerce/CRM integration before scaling.", owner="buyer_or_setup")

    if emq is None:
        add_check(checks, "event_match_quality", "Event Match Quality", "warn", "Event Match Quality is unknown.", action="Check Dataset/Event Manager diagnostics and improve customer parameters if the score is weak.", owner="buyer_or_setup")
    elif emq >= 6:
        add_check(checks, "event_match_quality", "Event Match Quality", "ok", f"EMQ score {emq:g} is usable for optimization.", action="Keep sending high-quality, consent-safe match parameters.", owner="buyer_or_setup")
    elif emq >= 4:
        add_check(checks, "event_match_quality", "Event Match Quality", "warn", f"EMQ score {emq:g} is only moderate.", action="Improve email/phone/external_id/fbp/fbc/IP/user-agent coverage before scaling.", owner="buyer_or_setup")
    else:
        add_check(checks, "event_match_quality", "Event Match Quality", "warn", f"EMQ score {emq:g} is weak; Meta may struggle to match events to people.", action="Fix server/browser event parameters before spending heavily.", owner="buyer_or_setup")

    if aem is True:
        add_check(checks, "aem_configuration", "AEM configuration", "ok", "AEM/event eligibility is marked as configured.", action="Keep the destination and event source aligned.", owner="buyer_or_setup")
    elif aem is False:
        add_check(checks, "aem_configuration", "AEM configuration", "warn", "AEM/event eligibility is not confirmed.", action="Review Events Manager for web/app event eligibility and domain/destination alignment where applicable.", owner="buyer_or_setup")
    else:
        add_check(checks, "aem_configuration", "AEM configuration", "warn", "AEM/event eligibility is unknown.", action="Verify it in Events Manager before relying on iOS/web conversion optimization.", owner="buyer_or_setup")

    if prioritized is True:
        add_check(checks, "event_prioritization", "Event prioritization", "ok", f"{recommended_event} is marked as prioritized/eligible.", action="Keep the highest-value event aligned with the offer.", owner="buyer_or_setup")
    elif prioritized is False:
        add_check(checks, "event_prioritization", "Event prioritization", "warn", f"{recommended_event} is not confirmed as prioritized/eligible.", action="Make sure the chosen event is the event Meta can optimize/report for this destination.", owner="buyer_or_setup")
    else:
        add_check(checks, "event_prioritization", "Event prioritization", "warn", "Event priority/eligibility is unknown.", action="Check Events Manager before launch or scaling.", owner="buyer_or_setup")

    if weekly_volume is None:
        add_check(checks, "conversion_volume", "Enough conversion volume", "warn", "Recent weekly event volume is unknown.", action="Ask for recent event volume or run a real Meta/Events Manager read before deciding the final event.", owner="agent")
    elif weekly_volume >= 50:
        add_check(checks, "conversion_volume", "Enough conversion volume", "ok", f"About {weekly_volume:g} weekly {rule['volume_label']} is enough to try the primary event.", action=f"Optimize for {rule['primary_event']} if the economics are good.", owner="agent")
    elif weekly_volume >= 15:
        add_check(checks, "conversion_volume", "Enough conversion volume", "warn", f"About {weekly_volume:g} weekly {rule['volume_label']} is workable but still learning-limited risk.", action=f"Start cautiously; consider {recommended_event} if {rule['primary_event']} delivery stays thin.", owner="agent")
    else:
        add_check(checks, "conversion_volume", "Enough conversion volume", "warn", f"Only about {weekly_volume:g} weekly {rule['volume_label']} is too thin for stable optimization.", action=f"Use a higher-volume event such as {recommended_event}, fix funnel tracking, or increase qualified volume before scaling.", owner="agent")

    statuses = {check["status"] for check in checks}
    status = "blocked" if "blocked" in statuses else ("needs_attention" if "warn" in statuses else "ready")
    active_safe = status == "ready"
    auto_optimizations = [check for check in checks if check.get("can_auto_optimize")]
    manual_actions = [check for check in checks if not check.get("can_auto_optimize")]
    promoted_object = {}
    if pixel_id and event_requires_dataset(recommended_event):
        promoted_object = {"pixel_id": pixel_id, "custom_event_type": meta_custom_event_type(recommended_event)}

    campaign_patch = {
        "optimization_goal": rule["optimization_goal"],
        "optimization_event": recommended_event,
        "promoted_object": promoted_object,
    }
    questions = []
    if not pixel_id and event_requires_dataset(recommended_event):
        questions.append("¿Cuál es el Pixel/Dataset correcto para este evento?")
    if capi is None:
        questions.append("¿Conversions API ya está activo para este Pixel/Dataset?")
    if emq is None:
        questions.append("¿Qué Event Match Quality muestra Events Manager para el evento principal?")
    if weekly_volume is None:
        questions.append(f"¿Cuántos eventos {rule['volume_label']} reales hubo en los últimos 7 días?")

    if language == "en":
        summary = (
            f"Signal review: {status}. Recommended event: {recommended_event}. "
            f"{'Safe to launch actively.' if active_safe else 'Do not scale or launch actively until the warnings are addressed.'}"
        )
    else:
        summary = (
            f"Revisión de señal: {status}. Evento recomendado: {recommended_event}. "
            f"{'Se puede lanzar con más confianza.' if active_safe else 'No conviene escalar o dejar activo sin revisar estas señales.'}"
        )

    return {
        "status": status,
        "safe_to_launch_active": active_safe,
        "objective_type": objective,
        "objective_label": rule["label"],
        "selected_event": selected_event,
        "recommended_event": recommended_event,
        "primary_event": rule["primary_event"],
        "weekly_event_volume": weekly_volume,
        "weekly_event_volume_source": volume_source,
        "checks": checks,
        "auto_optimizations": auto_optimizations,
        "manual_actions": manual_actions,
        "campaign_patch": campaign_patch,
        "questions": questions,
        "summary": summary,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }


def apply_signal_quality_to_adset(adset, review):
    adset = dict(adset or {})
    patch = (review or {}).get("campaign_patch") or {}
    if patch.get("optimization_goal"):
        adset["optimization_goal"] = patch["optimization_goal"]
    if patch.get("optimization_event"):
        adset["optimization_event"] = patch["optimization_event"]
    if patch.get("promoted_object"):
        adset["promoted_object"] = dict(patch["promoted_object"])
    return adset


def signal_quality_reply(review, language="es"):
    review = review or {}
    status = review.get("status")
    event = review.get("recommended_event") or "evento"
    blockers = [item for item in review.get("checks", []) if item.get("status") == "blocked"]
    warnings = [item for item in review.get("checks", []) if item.get("status") == "warn"]
    first = blockers[0] if blockers else (warnings[0] if warnings else None)
    if language == "en":
        if status == "ready":
            return f"Signal setup looks usable. I would optimize this campaign for {event} and keep monitoring volume and attribution."
        detail = first.get("detail") if first else "some signal checks need attention"
        return f"I reviewed the signal setup. I would not scale or launch actively yet. Main point: {detail}"
    if status == "ready":
        return f"La señal se ve usable. Optimizaría esta campaña para {event} y seguiría vigilando volumen y atribución."
    detail = first.get("detail") if first else "hay señales que revisar"
    return f"Revisé la señal de optimización. No escalaría ni dejaría esto activo todavía. Punto principal: {detail}"
