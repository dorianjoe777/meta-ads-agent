#!/usr/bin/env python3
"""Warm business-manager chat agent for the dashboard."""
import json
import re
import urllib.error
import urllib.request

from agent_runtime import build_system_prompt
from communication_style import ad_experience_from_environment, communication_preference, communication_style_from_environment
from hermes_bridge import chat as hermes_chat


DEMO_CAMPAIGN_IDS = {"camp_001", "camp_002", "camp_003", "camp_004"}
DEMO_CAMPAIGN_NAMES = {
    "Q2 Conversion Campaign",
    "Brand Awareness Campaign",
    "Retargeting - Warm Leads",
    "Prospecting - Broad Testing",
}


def looks_like_demo_metrics(metrics):
    if not isinstance(metrics, dict):
        return False
    campaigns = metrics.get("campaigns", [])
    if not isinstance(campaigns, list):
        return False
    ids = {str(c.get("id") or "") for c in campaigns if isinstance(c, dict)}
    names = {str(c.get("name") or "") for c in campaigns if isinstance(c, dict)}
    return bool(DEMO_CAMPAIGN_IDS & ids) or bool(DEMO_CAMPAIGN_NAMES & names)


def metrics_are_real_meta(metrics):
    return isinstance(metrics, dict) and metrics.get("source") == "meta_graph" and not looks_like_demo_metrics(metrics)


def metrics_source_context(metrics):
    if not isinstance(metrics, dict):
        return {
            "source": "missing",
            "source_label": "Sin datos reales de Meta",
            "is_real_meta_data": False,
            "notice": "No hay campañas reales disponibles todavía. No cites campañas, ROAS, CPA, CTR ni presupuestos como si fueran reales.",
        }
    source = str(metrics.get("source") or "unknown")
    if metrics_are_real_meta(metrics):
        return {
            "source": source,
            "source_label": metrics.get("source_label") or "Datos reales de Meta",
            "is_real_meta_data": True,
            "notice": "Puedes usar estas campañas y métricas como datos reales de Meta.",
        }
    label = metrics.get("source_label") or ("Datos de ejemplo" if source == "demo" else "Datos guardados no confirmados")
    return {
        "source": source,
        "source_label": label,
        "is_real_meta_data": False,
        "notice": "No hay campañas reales de Meta confirmadas en esta conversación. No recomiendes ganadoras, perdedoras, retargeting, ROAS, CPA, CTR, presupuesto ni acciones usando datos demo o guardados no confirmados.",
    }


def account_context(payload):
    metrics = payload.get("metrics", {})
    source_context = metrics_source_context(metrics)
    has_real_metrics = source_context["is_real_meta_data"]
    summary = metrics.get("summary", {})
    campaigns = metrics.get("campaigns", [])
    adsets = metrics.get("adsets", [])
    ads = metrics.get("ads", [])
    campaign_tree = metrics.get("campaign_tree", [])
    recommendations = payload.get("recommendations", [])
    fatigue = payload.get("fatigue", [])
    pending = payload.get("pending", [])
    audience_strategy = payload.get("audience_strategy", {})
    business_profile = payload.get("business_profile", {})
    brand_guides = payload.get("brand_guides", {})
    agent_onboarding_phase = payload.get("agent_onboarding_phase", {})
    optimization = payload.get("optimization", {})
    verified_signals = payload.get("verified_signals", {})
    communication = communication_preference(
        communication_style_from_environment(),
        payload.get("language") or "es",
        ad_experience_level=ad_experience_from_environment(),
    )
    return {
        "communication_preference": communication,
        "agent_onboarding_phase": agent_onboarding_phase if isinstance(agent_onboarding_phase, dict) else {},
        "business_profile": business_profile if isinstance(business_profile, dict) else {},
        "metrics_source": source_context,
        "inventory_counts": {
            "campaigns": len(campaigns) if isinstance(campaigns, list) else 0,
            "adsets": len(adsets) if isinstance(adsets, list) else 0,
            "ads": len(ads) if isinstance(ads, list) else 0,
            "campaigns_returned": min(len(campaigns), 100) if isinstance(campaigns, list) and has_real_metrics else 0,
            "adsets_returned": min(len(adsets), 300) if isinstance(adsets, list) and has_real_metrics else 0,
            "ads_returned": min(len(ads), 500) if isinstance(ads, list) and has_real_metrics else 0,
        },
        "summary": summary if has_real_metrics else {},
        "campaigns": [
            {
                "id": c.get("id"),
                "name": c.get("name"),
                "health": c.get("health"),
                "status": c.get("status"),
                "spend": c.get("spend"),
                "roas": c.get("roas"),
                "cpa": c.get("cpa"),
                "ctr": c.get("ctr"),
                "frequency": c.get("frequency"),
                "daily_budget": c.get("daily_budget"),
            }
            for c in (campaigns[:100] if has_real_metrics else [])
        ],
        "adsets": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "campaign_id": item.get("campaign_id"),
                "status": item.get("status"),
                "effective_status": item.get("effective_status"),
                "optimization_goal": item.get("optimization_goal"),
                "billing_event": item.get("billing_event"),
                "daily_budget": item.get("daily_budget"),
            }
            for item in (adsets[:300] if has_real_metrics and isinstance(adsets, list) else [])
        ],
        "ads": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "campaign_id": item.get("campaign_id"),
                "adset_id": item.get("adset_id"),
                "status": item.get("status"),
                "effective_status": item.get("effective_status"),
                "creative_id": (item.get("creative") or {}).get("id") if isinstance(item.get("creative"), dict) else None,
                "object_story_id": (item.get("creative") or {}).get("object_story_id") if isinstance(item.get("creative"), dict) else None,
            }
            for item in (ads[:500] if has_real_metrics and isinstance(ads, list) else [])
        ],
        "campaign_tree": [
            {
                "id": c.get("id"),
                "name": c.get("name"),
                "status": c.get("status"),
                "effective_status": c.get("effective_status"),
                "adsets": [
                    {
                        "id": adset.get("id"),
                        "name": adset.get("name"),
                        "status": adset.get("status"),
                        "effective_status": adset.get("effective_status"),
                        "ads": [
                            {
                                "id": ad.get("id"),
                                "name": ad.get("name"),
                                "status": ad.get("status"),
                                "effective_status": ad.get("effective_status"),
                            }
                            for ad in (adset.get("ads") or [])[:10]
                            if isinstance(ad, dict)
                        ],
                    }
                    for adset in (c.get("adsets") or [])[:10]
                    if isinstance(adset, dict)
                ],
                "ads": [
                    {
                        "id": ad.get("id"),
                        "name": ad.get("name"),
                        "status": ad.get("status"),
                        "effective_status": ad.get("effective_status"),
                    }
                    for ad in (c.get("ads") or [])[:10]
                    if isinstance(ad, dict)
                ],
            }
            for c in (campaign_tree[:100] if has_real_metrics and isinstance(campaign_tree, list) else [])
            if isinstance(c, dict)
        ],
        "recommendations": recommendations[:6] if has_real_metrics else [],
        "fatigue": fatigue[:6] if has_real_metrics else [],
        "pending_approvals": pending[:6],
        "audience_strategy": audience_strategy if isinstance(audience_strategy, dict) else {},
        "brand_guides": {
            "general_exists": bool(brand_guides.get("general_exists")),
            "product_guides": list(brand_guides.get("product_guides", []))[:20],
            "creative_references_exists": bool(brand_guides.get("creative_references_exists")),
            "creative_references": brand_guides.get("creative_references", ""),
        } if isinstance(brand_guides, dict) else {},
        "optimization": optimization if isinstance(optimization, dict) else {},
        "verified_signals": verified_signals if isinstance(verified_signals, dict) else {},
    }


def fallback_reply(message, payload):
    metrics = payload.get("metrics", {})
    if not metrics_are_real_meta(metrics):
        return (
            "Todavía no tengo campañas reales de Meta para analizar en esta instalación. "
            "Lo correcto ahora es conectar o actualizar los datos reales de Facebook/Meta Ads. "
            "Cuando entren esos datos, sí puedo decirte qué campaña va mejor, cuál conviene pausar y qué movería primero."
        )
    summary = metrics.get("summary", {})
    roas = float(summary.get("overall_roas") or 0)
    cpa = float(summary.get("overall_cpa") or 0)
    budget = float(summary.get("active_budget") or 0)
    pending = len(payload.get("pending", []))
    text = (message or "").lower()
    if any(word in text for word in ["presupuesto", "budget"]):
        return "Hice una lectura rápida del presupuesto. Mi sugerencia es escalar solo lo que ya está ganando y proteger presupuesto donde haya fatiga o CPA alto. Lo puedo preparar ahora para aprobación si me dices qué campaña quieres mover."
    if any(word in text for word in ["fatiga", "creative", "creativo"]):
        return "La fatiga se debe revisar por frecuencia alta, caída de CTR o subida de CPC. Si aparece, lo más sano es crear nuevos ángulos creativos antes de subir presupuesto."
    if any(word in text for word in ["audiencia", "segmentación", "segmentacion", "targeting", "lookalike", "retargeting"]):
        return "Para segmentación, empezaría simple: una campaña amplia/Advantage+, una prueba de intereses si el nicho es claro, y retargeting separado si ya hay tráfico. Lookalike solo cuando exista una fuente semilla limpia, como pixel, engagement o lista de clientes con consentimiento."
    return f"Catch-up rápido: ROAS {roas:.2f}x, CPA ${cpa:,.2f}, presupuesto activo ${budget:,.2f} y {pending} aprobación(es) pendiente(s). Mi sugerencia es revisar presupuesto y fatiga antes de escalar. Lo puedo preparar ahora; dime qué acción quieres que deje lista."


def reply_uses_unverified_performance(reply, metrics):
    if metrics_are_real_meta(metrics):
        return False
    text = str(reply or "")
    lowered = text.lower()
    if any(name.lower() in lowered for name in DEMO_CAMPAIGN_NAMES):
        return True
    if any(campaign_id.lower() in lowered for campaign_id in DEMO_CAMPAIGN_IDS):
        return True
    metric_claim = re.search(r"\b(roas|cpa|ctr|cpc|frecuencia|conversiones|presupuesto|spend)\b[^\n]{0,80}\d", lowered, flags=re.IGNORECASE)
    performance_claim = re.search(r"\b(ganadora|mejor rindiendo|mejor esta rindiendo|pausar|escalar|retargeting|warm leads)\b", lowered, flags=re.IGNORECASE)
    return bool(metric_claim and performance_claim)


def openai_compatible_chat(config, payload):
    if not config.agent_chat_api_key:
        return {"ok": False, "provider": config.agent_chat_provider, "fallback": True, "reply": fallback_reply(payload.get("message", ""), payload), "error": "AGENT_CHAT_API_KEY is not configured"}

    context = account_context(payload)
    language = payload.get("language", "")
    system_prompt = build_system_prompt(config, language)
    if language:
        system_prompt += f"\n\nRequested dashboard language: {language}"
    system_prompt += f"\n\n{context['communication_preference']['instruction']}"
    messages = [
        {
            "role": "system",
            "content": system_prompt
            + "\n\nCurrent account context JSON:\n"
            + json.dumps(context, ensure_ascii=False)
            + "\n\nIf the user's request requires a product action, use the SKILLS.md response contract exactly. Otherwise answer normally.",
        },
    ]
    for item in payload.get("history", [])[-10:]:
        role = "assistant" if item.get("role") == "agent" else "user"
        content = str(item.get("content", "")).strip()
        if content:
            messages.append({"role": role, "content": content[:3000]})
    if payload.get("message"):
        messages.append({"role": "user", "content": str(payload["message"])[:5000]})

    body = {
        "model": config.agent_chat_model,
        "messages": messages,
        "temperature": config.agent_chat_temperature,
    }
    base_url = str(config.agent_chat_base_url or "").rstrip("/")
    if not base_url:
        return {"ok": False, "provider": config.agent_chat_provider, "fallback": True, "reply": fallback_reply(payload.get("message", ""), payload), "error": "AGENT_CHAT_BASE_URL is not configured"}
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.agent_chat_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
        reply = clean_reply(data.get("choices", [{}])[0].get("message", {}).get("content", ""))
        parsed = parse_skill_response(reply)
        if parsed is not None:
            return {
                "ok": True,
                "provider": config.agent_chat_provider,
                "model": config.agent_chat_model,
                "reply": parsed.get("assistant_message") or fallback_reply(payload.get("message", ""), payload),
                "tool_request": parsed.get("tool_request"),
                "raw_reply": reply,
            }
        return {"ok": True, "provider": config.agent_chat_provider, "model": config.agent_chat_model, "reply": reply or fallback_reply(payload.get("message", ""), payload), "tool_request": None}
    except urllib.error.HTTPError as exc:
        error = exc.read().decode("utf-8")[:1000]
        return {"ok": False, "provider": config.agent_chat_provider, "fallback": True, "reply": fallback_reply(payload.get("message", ""), payload), "error": error}
    except Exception as exc:
        return {"ok": False, "provider": config.agent_chat_provider, "fallback": True, "reply": fallback_reply(payload.get("message", ""), payload), "error": str(exc)}


def chat(config, payload):
    hermes_payload = dict(payload)
    hermes_payload["account_context"] = account_context(payload)
    result = hermes_chat(config, hermes_payload)
    raw_reply = result.get("reply", "")
    parsed = parse_skill_response(raw_reply)
    if parsed is not None:
        result["reply"] = parsed.get("assistant_message") or fallback_reply(payload.get("message", ""), payload)
        result["tool_request"] = parsed.get("tool_request")
        result["raw_reply"] = result.get("raw_reply") or raw_reply
    else:
        result["reply"] = clean_reply(raw_reply)
        result.setdefault("tool_request", None)
    if not str(result.get("reply") or "").strip():
        result["fallback"] = True
        result["reply"] = fallback_reply(payload.get("message", ""), payload)
        result["error"] = result.get("error") or "Hermes returned an empty reply"
    elif reply_uses_unverified_performance(result.get("reply", ""), payload.get("metrics", {})):
        result["fallback"] = True
        result["reply"] = fallback_reply(payload.get("message", ""), payload)
        result["error"] = result.get("error") or "Agent reply used unverified performance data"
    return result


def clean_reply(text):
    text = re.sub(r"<think>.*?</think>", "", str(text or ""), flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"```(?:diff|patch)\s+.*?```", "", text, flags=re.DOTALL | re.IGNORECASE)
    return strip_technical_preamble(text).strip()


def strip_technical_preamble(text):
    lines = str(text or "").splitlines()
    cleaned = []
    skipping = False
    for line in lines:
        normalized = line.strip()
        lowered = normalized.lower()
        internal_runtime_notice = (
            ("codex" in lowered and "caps context at" in lowered and "auto-compaction" in lowered)
            or "compression.codex_gpt55_autoraise" in lowered
        )
        if internal_runtime_notice:
            continue
        starts_noise = (
            "tirith security scanner" in lowered
            or lowered in {"┊ review diff", "review diff"}
            or re.match(r"^(a|b)/.+\s(→|->)\s.+$", normalized)
            or normalized.startswith("@@ ")
        )
        if starts_noise:
            skipping = True
            continue
        if skipping:
            diff_like = (
                not normalized
                or normalized.startswith(("+", "-", "@@"))
                or re.match(r'^[+\- ]*["{}\[\],]', line)
                or re.match(r"^[+\-]?\}?\]?[,]?$", normalized)
                or re.match(r"^(a|b)/", normalized)
            )
            if diff_like:
                continue
            skipping = False
        cleaned.append(line)
    return "\n".join(cleaned)


def parse_skill_response(text):
    clean = clean_reply(text)
    if not clean:
        return None
    candidates = [clean]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1))
    if "{" in clean and "}" in clean:
        candidates.append(clean[clean.find("{") : clean.rfind("}") + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and ("assistant_message" in parsed or "tool_request" in parsed):
            parsed.setdefault("assistant_message", "")
            parsed.setdefault("tool_request", None)
            return parsed
    return None
