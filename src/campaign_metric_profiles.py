#!/usr/bin/env python3
"""Adaptive campaign KPI profiles for the Admira IA dashboard and agent."""

from copy import deepcopy


METRIC_DEFINITIONS = {
    "spend": {"label": "Spend", "label_es": "Gasto", "format": "currency"},
    "results": {"label": "Results", "label_es": "Resultados", "format": "number"},
    "purchase": {"label": "Purchases", "label_es": "Compras", "format": "number"},
    "cost_per_purchase": {"label": "Cost per purchase", "label_es": "Costo por compra", "format": "currency"},
    "revenue": {"label": "Revenue", "label_es": "Ingresos", "format": "currency"},
    "roas": {"label": "ROAS", "label_es": "ROAS", "format": "ratio"},
    "initiate_checkout": {"label": "Checkouts started", "label_es": "Checkouts iniciados", "format": "number"},
    "cost_per_initiate_checkout": {"label": "Cost per checkout", "label_es": "Costo por checkout", "format": "currency"},
    "lead": {"label": "Leads", "label_es": "Leads", "format": "number"},
    "cost_per_lead": {"label": "Cost per lead", "label_es": "Costo por lead", "format": "currency"},
    "conversation": {"label": "Conversations", "label_es": "Conversaciones", "format": "number"},
    "cost_per_conversation": {"label": "Cost per conversation", "label_es": "Costo por conversación", "format": "currency"},
    "landing_page_views": {"label": "Landing page views", "label_es": "Visitas reales a la página", "format": "number"},
    "cost_per_landing_page_view": {"label": "Cost per landing view", "label_es": "Costo por visita real", "format": "currency"},
    "clicks": {"label": "Clicks", "label_es": "Clics", "format": "number"},
    "cpc": {"label": "CPC", "label_es": "Costo por clic", "format": "currency"},
    "ctr": {"label": "CTR", "label_es": "CTR", "format": "percent"},
    "impressions": {"label": "Impressions", "label_es": "Impresiones", "format": "number"},
    "reach": {"label": "Reach", "label_es": "Alcance", "format": "number"},
    "cpm": {"label": "CPM", "label_es": "Costo por mil", "format": "currency"},
    "frequency": {"label": "Frequency", "label_es": "Frecuencia", "format": "decimal"},
    "thruplay": {"label": "ThruPlays", "label_es": "Reproducciones ThruPlay", "format": "number"},
    "cost_per_thruplay": {"label": "Cost per ThruPlay", "label_es": "Costo por ThruPlay", "format": "currency"},
    "video_3s_views": {"label": "3-second video views", "label_es": "Vistas de video de 3 s", "format": "number"},
    "completed_video_views": {"label": "Completed video views", "label_es": "Videos completados", "format": "number"},
    "cost_per_completed_video_view": {"label": "Cost per completed view", "label_es": "Costo por video completado", "format": "currency"},
    "app_install": {"label": "App installs", "label_es": "Instalaciones", "format": "number"},
    "cost_per_app_install": {"label": "Cost per install", "label_es": "Costo por instalación", "format": "currency"},
    "post_engagement": {"label": "Engagements", "label_es": "Interacciones", "format": "number"},
    "cost_per_engagement": {"label": "Cost per engagement", "label_es": "Costo por interacción", "format": "currency"},
    "active_campaigns": {"label": "Active campaigns", "label_es": "Campañas activas", "format": "number"},
}

PROFILE_DEFAULTS = {
    "sales": ["spend", "purchase", "cost_per_purchase", "roas", "initiate_checkout", "cost_per_initiate_checkout"],
    "leads": ["spend", "lead", "cost_per_lead", "landing_page_views", "ctr", "cpc"],
    "messages": ["spend", "conversation", "cost_per_conversation", "clicks", "ctr", "cpc"],
    "traffic": ["spend", "landing_page_views", "cost_per_landing_page_view", "clicks", "cpc", "ctr"],
    "awareness": ["spend", "reach", "impressions", "cpm", "frequency", "ctr"],
    "video": ["spend", "thruplay", "cost_per_thruplay", "completed_video_views", "cost_per_completed_video_view", "video_3s_views"],
    "app": ["spend", "app_install", "cost_per_app_install", "clicks", "cpc", "ctr"],
    "engagement": ["spend", "post_engagement", "cost_per_engagement", "reach", "cpm", "frequency"],
    "general": ["spend", "results", "cpa", "clicks", "ctr", "frequency"],
}

# Legacy/general aliases that can still be selected by the agent.
METRIC_DEFINITIONS["cpa"] = {"label": "Cost per result", "label_es": "Costo por resultado", "format": "currency"}

OBJECTIVE_TYPES = set(PROFILE_DEFAULTS)


def number(value, default=0.0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return float(default)


def normalize_metric_keys(value, limit=6):
    if isinstance(value, str):
        value = [part.strip() for part in value.replace(";", ",").split(",")]
    result = []
    for key in value or []:
        key = str(key or "").strip().lower().replace(" ", "_").replace("-", "_")
        if key in METRIC_DEFINITIONS and key not in result:
            result.append(key)
        if len(result) >= limit:
            break
    return result


def campaign_adsets(campaign_id, adsets):
    return [item for item in adsets or [] if str(item.get("campaign_id") or "") == str(campaign_id or "")]


def infer_objective_type(campaign, adsets=None, override=None):
    requested = str((override or {}).get("objective_type") or "").strip().lower()
    if requested in OBJECTIVE_TYPES:
        return requested
    related = campaign_adsets(campaign.get("id") or campaign.get("campaign_id"), adsets)
    objective = str(campaign.get("objective") or "").upper()
    optimization = " ".join(str(item.get("optimization_goal") or "").upper() for item in related)
    events = " ".join(
        str((item.get("promoted_object") or {}).get("custom_event_type") or "").upper()
        for item in related if isinstance(item.get("promoted_object"), dict)
    )
    strongest = f"{events} {objective} {optimization}"
    if any(word in strongest for word in ("MESSAGE", "CONVERSATION", "WHATSAPP", "MESSENGER")):
        return "messages"
    if any(word in events for word in ("LEAD", "QUALIFIED_LEAD")) or "LEAD_GENERATION" in optimization or "OUTCOME_LEADS" in objective:
        return "leads"
    if any(word in events for word in ("PURCHASE", "INITIATED_CHECKOUT", "ADD_TO_CART")) or any(word in strongest for word in ("OUTCOME_SALES", "VALUE", "OFFSITE_CONVERSIONS")):
        return "sales"
    if any(word in strongest for word in ("THRUPLAY", "VIDEO_VIEW")):
        return "video"
    if "APP_INSTALL" in strongest or "OUTCOME_APP" in strongest:
        return "app"
    if any(word in strongest for word in ("LINK_CLICKS", "LANDING_PAGE_VIEWS", "OUTCOME_TRAFFIC")):
        return "traffic"
    if any(word in strongest for word in ("OUTCOME_AWARENESS", "REACH", "IMPRESSIONS", "AD_RECALL")):
        return "awareness"
    if any(word in strongest for word in ("OUTCOME_ENGAGEMENT", "POST_ENGAGEMENT", "EVENT_RESPONSES", "ENGAGED_USERS")):
        return "engagement"
    return "general"


def ratio_cost(spend, result):
    return round(spend / result, 4) if result > 0 else None


def metric_values(campaign):
    funnel = campaign.get("funnel") if isinstance(campaign.get("funnel"), dict) else {}
    spend = number(campaign.get("spend"))
    impressions = number(campaign.get("impressions"))
    clicks = number(campaign.get("clicks"))
    results = number(campaign.get("conversions"))
    purchase = number(funnel.get("purchase"))
    lead = number(funnel.get("lead"))
    conversation = number(funnel.get("conversation"))
    checkout = number(funnel.get("initiate_checkout"))
    landing_views = number(funnel.get("landing_page_views"))
    thruplay = number(funnel.get("thruplay"))
    completed = number(funnel.get("completed_video_views"))
    app_install = number(funnel.get("app_install"))
    engagement = number(funnel.get("post_engagement"))
    return {
        "spend": spend,
        "results": results,
        "cpa": ratio_cost(spend, results),
        "purchase": purchase,
        "cost_per_purchase": ratio_cost(spend, purchase),
        "revenue": number(campaign.get("revenue")),
        "roas": number(campaign.get("roas")) if spend > 0 else None,
        "initiate_checkout": checkout,
        "cost_per_initiate_checkout": ratio_cost(spend, checkout),
        "lead": lead,
        "cost_per_lead": ratio_cost(spend, lead),
        "conversation": conversation,
        "cost_per_conversation": ratio_cost(spend, conversation),
        "landing_page_views": landing_views,
        "cost_per_landing_page_view": ratio_cost(spend, landing_views),
        "clicks": clicks,
        "cpc": ratio_cost(spend, clicks),
        "ctr": round(clicks / impressions * 100, 4) if impressions > 0 else None,
        "impressions": impressions,
        "reach": number(campaign.get("reach")),
        "cpm": round(spend / impressions * 1000, 4) if impressions > 0 else None,
        "frequency": number(campaign.get("frequency")) if impressions > 0 else None,
        "thruplay": thruplay,
        "cost_per_thruplay": ratio_cost(spend, thruplay),
        "video_3s_views": number(funnel.get("video_3s_views")),
        "completed_video_views": completed,
        "cost_per_completed_video_view": ratio_cost(spend, completed),
        "app_install": app_install,
        "cost_per_app_install": ratio_cost(spend, app_install),
        "post_engagement": engagement,
        "cost_per_engagement": ratio_cost(spend, engagement),
        "active_campaigns": number(campaign.get("active_campaigns")),
    }


def priority_metric_rows(campaign, keys):
    values = metric_values(campaign)
    rows = []
    for priority, key in enumerate(normalize_metric_keys(keys), start=1):
        definition = METRIC_DEFINITIONS[key]
        value = values.get(key)
        rows.append({
            "key": key,
            "label": definition["label"],
            "label_es": definition["label_es"],
            "format": definition["format"],
            "value": value,
            "available": value is not None,
            "priority": priority,
        })
    return rows


def attach_campaign_metric_profiles(campaigns, adsets=None, overrides=None):
    overrides = overrides if isinstance(overrides, dict) else {}
    result = []
    for original in campaigns or []:
        campaign = deepcopy(original)
        campaign_id = str(campaign.get("id") or campaign.get("campaign_id") or "")
        override = overrides.get(campaign_id) if isinstance(overrides.get(campaign_id), dict) else {}
        objective_type = infer_objective_type(campaign, adsets, override)
        requested = normalize_metric_keys(override.get("metric_keys"))
        keys = requested or PROFILE_DEFAULTS[objective_type]
        campaign["metric_profile"] = {
            "objective_type": objective_type,
            "metric_keys": list(keys),
            "source": "agent" if requested else "inferred",
            "rationale": str(override.get("rationale") or ""),
            "updated_at": str(override.get("updated_at") or ""),
        }
        campaign["priority_metrics"] = priority_metric_rows(campaign, keys)
        result.append(campaign)
    return result


def account_priority_metrics(campaigns):
    active = [item for item in campaigns or [] if str(item.get("status") or item.get("effective_status") or "").lower() in {"active", "enabled"}]
    selected = active or list(campaigns or [])
    if not selected:
        return []
    objective_types = {str((item.get("metric_profile") or {}).get("objective_type") or "general") for item in selected}
    funnel = {}
    aggregate = {
        "spend": sum(number(item.get("spend")) for item in selected),
        "revenue": sum(number(item.get("revenue")) for item in selected),
        "impressions": sum(number(item.get("impressions")) for item in selected),
        "clicks": sum(number(item.get("clicks")) for item in selected),
        "conversions": sum(number(item.get("conversions")) for item in selected),
        "reach": sum(number(item.get("reach")) for item in selected),
        "frequency": 0,
        "active_campaigns": len(active),
    }
    for item in selected:
        for key, value in (item.get("funnel") or {}).items():
            funnel[key] = funnel.get(key, 0) + number(value)
    aggregate["funnel"] = funnel
    aggregate["roas"] = round(aggregate["revenue"] / aggregate["spend"], 4) if aggregate["spend"] else 0
    aggregate["frequency"] = round(aggregate["impressions"] / aggregate["reach"], 4) if aggregate["reach"] else 0
    if len(objective_types) == 1:
        objective_type = next(iter(objective_types))
        keys = PROFILE_DEFAULTS.get(objective_type, PROFILE_DEFAULTS["general"])[:4]
    else:
        keys = ["spend", "active_campaigns", "impressions", "clicks"]
    return priority_metric_rows(aggregate, keys)


def public_metric_catalog():
    return {key: dict(value) for key, value in METRIC_DEFINITIONS.items()}
