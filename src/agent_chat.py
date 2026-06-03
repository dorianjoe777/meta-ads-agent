#!/usr/bin/env python3
"""Warm business-manager chat agent for the dashboard."""
import json
import re
import urllib.error
import urllib.request

from agent_runtime import build_system_prompt
from hermes_bridge import chat as hermes_chat


def account_context(payload):
    metrics = payload.get("metrics", {})
    summary = metrics.get("summary", {})
    campaigns = metrics.get("campaigns", [])
    recommendations = payload.get("recommendations", [])
    fatigue = payload.get("fatigue", [])
    pending = payload.get("pending", [])
    audience_strategy = payload.get("audience_strategy", {})
    business_profile = payload.get("business_profile", {})
    brand_guides = payload.get("brand_guides", {})
    return {
        "business_profile": business_profile if isinstance(business_profile, dict) else {},
        "summary": summary,
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
            for c in campaigns[:8]
        ],
        "recommendations": recommendations[:6],
        "fatigue": fatigue[:6],
        "pending_approvals": pending[:6],
        "audience_strategy": audience_strategy if isinstance(audience_strategy, dict) else {},
        "brand_guides": {
            "general_exists": bool(brand_guides.get("general_exists")),
            "product_guides": list(brand_guides.get("product_guides", []))[:20],
        } if isinstance(brand_guides, dict) else {},
    }


def fallback_reply(message, payload):
    summary = payload.get("metrics", {}).get("summary", {})
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


def openai_compatible_chat(config, payload):
    if not config.agent_chat_api_key:
        return {"ok": False, "provider": config.agent_chat_provider, "fallback": True, "reply": fallback_reply(payload.get("message", ""), payload), "error": "AGENT_CHAT_API_KEY is not configured"}

    context = account_context(payload)
    language = payload.get("language", "")
    system_prompt = build_system_prompt(config, language)
    if language:
        system_prompt += f"\n\nRequested dashboard language: {language}"
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
    if config.agent_chat_provider == "hermes":
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
            result.setdefault("tool_request", None)
        return result
    if config.agent_chat_provider in {"minimax", "openai_compatible", "openai"}:
        return openai_compatible_chat(config, payload)
    return {"ok": False, "provider": config.agent_chat_provider, "fallback": True, "reply": fallback_reply(payload.get("message", ""), payload), "error": "Unsupported chat provider"}


def clean_reply(text):
    text = re.sub(r"<think>.*?</think>", "", str(text or ""), flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


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
