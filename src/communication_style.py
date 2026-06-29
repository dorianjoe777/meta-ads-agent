#!/usr/bin/env python3
"""Installation-wide operator preferences shared by every agent channel."""

import os

COMMUNICATION_STYLES = {"simple", "technical"}
AD_EXPERIENCE_LEVELS = {"beginner", "intermediate", "advanced"}
AD_EXPERIENCE_ALIASES = {
    "no": "beginner",
    "none": "beginner",
    "nuevo": "beginner",
    "nueva": "beginner",
    "principiante": "beginner",
    "beginner": "beginner",
    "basic": "beginner",
    "basico": "beginner",
    "básico": "beginner",
    "little": "beginner",
    "poco": "beginner",
    "some": "intermediate",
    "algo": "intermediate",
    "intermedio": "intermediate",
    "intermediate": "intermediate",
    "medium": "intermediate",
    "medio": "intermediate",
    "yes": "advanced",
    "si": "advanced",
    "sí": "advanced",
    "experienced": "advanced",
    "advanced": "advanced",
    "avanzado": "advanced",
    "avanzada": "advanced",
    "experto": "advanced",
    "experta": "advanced",
    "professional": "advanced",
    "profesional": "advanced",
}


def normalize_communication_style(value, default="simple"):
    style = str(value or "").strip().lower()
    if style in COMMUNICATION_STYLES:
        return style
    fallback = str(default or "").strip().lower()
    return fallback if fallback in COMMUNICATION_STYLES else ""


def communication_style_from_environment(default="simple"):
    return normalize_communication_style(os.environ.get("AGENT_COMMUNICATION_STYLE"), default=default)


def communication_style_is_configured():
    return str(os.environ.get("AGENT_COMMUNICATION_STYLE") or "").strip().lower() in COMMUNICATION_STYLES


def normalize_ad_experience_level(value, default=""):
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    level = AD_EXPERIENCE_ALIASES.get(raw, raw)
    if level in AD_EXPERIENCE_LEVELS:
        return level
    fallback_raw = str(default or "").strip().lower().replace("-", "_").replace(" ", "_")
    fallback = AD_EXPERIENCE_ALIASES.get(fallback_raw, fallback_raw)
    return fallback if fallback in AD_EXPERIENCE_LEVELS else ""


def ad_experience_from_environment(default=""):
    return normalize_ad_experience_level(os.environ.get("AGENT_AD_EXPERIENCE_LEVEL"), default=default)


def ad_experience_is_configured():
    return normalize_ad_experience_level(os.environ.get("AGENT_AD_EXPERIENCE_LEVEL"), default="") in AD_EXPERIENCE_LEVELS


def communication_style_instruction(style, language="es"):
    normalized = normalize_communication_style(style)
    english = str(language or "").strip().lower().startswith("en")
    if normalized == "technical":
        if english:
            return (
                "Communication preference: technical. Use precise marketing and technical terminology freely when it improves the answer. "
                "Include mechanisms, assumptions, limitations, and implementation detail when useful; do not automatically simplify or omit them. "
                "Stay clear and organized. This preference never overrides security, approval, evidence, or account-safety rules."
            )
        return (
            "Preferencia de comunicación: técnica. Usa libremente terminología precisa de marketing y tecnología cuando mejore la respuesta. "
            "Incluye mecanismos, supuestos, límites y detalles de implementación cuando sean útiles; no los simplifiques ni omitas automáticamente. "
            "Mantén claridad y orden. Esta preferencia nunca cambia las reglas de seguridad, aprobación, evidencia o cuidado de la cuenta."
        )
    if english:
        return (
            "Communication preference: simple words. Lead with the decision and business impact, use everyday language, and avoid jargon. "
            "If a technical term is necessary, explain it immediately in one plain sentence. Do not show code, commands, or internal implementation "
            "details unless the buyer asks for them. Still make expert best-practice recommendations proactively; simply explain the business impact "
            "instead of the machinery. This preference never overrides security, approval, evidence, or account-safety rules."
        )
    return (
        "Preferencia de comunicación: palabras simples. Empieza por la decisión y el impacto en el negocio, usa lenguaje cotidiano y evita jerga. "
        "Si un término técnico es necesario, explícalo de inmediato en una frase sencilla. No muestres código, comandos ni detalles internos de "
        "implementación salvo que el comprador los pida. Aun así, recomienda de forma proactiva las mejores prácticas; solo explica el impacto en negocio "
        "en vez de toda la maquinaria. Esta preferencia nunca cambia las reglas de seguridad, aprobación, evidencia o cuidado de la cuenta."
    )


def ad_experience_instruction(level, language="es"):
    normalized = normalize_ad_experience_level(level, default="")
    english = str(language or "").strip().lower().startswith("en")
    if not normalized:
        if english:
            return (
                "Ad experience preference is not configured yet. Early in onboarding, ask whether the buyer has experience creating/managing ads "
                "and whether they want deep technical details. Save the answer with `mcp_admira_save_agent_preferences` when available."
            )
        return (
            "La experiencia del comprador con anuncios todavía no está configurada. Al inicio del onboarding, pregunta si tiene experiencia creando/"
            "gestionando anuncios y si quiere detalles técnicos profundos. Guarda la respuesta con `mcp_admira_save_agent_preferences` cuando esté disponible."
        )
    if normalized == "advanced":
        if english:
            return (
                "Ad experience: advanced. You may discuss strategic tradeoffs, signal quality, optimization events, audience structure, budget math, "
                "creative-test design, and tool limits in more depth. Stay proactive and challenge weak assumptions kindly."
            )
        return (
            "Experiencia en anuncios: avanzada. Puedes hablar con más profundidad de tradeoffs estratégicos, calidad de señal, eventos de optimización, "
            "estructura de audiencias, matemáticas de presupuesto, diseño de tests creativos y límites de herramientas. Sé proactivo y corrige supuestos débiles con tacto."
        )
    if normalized == "intermediate":
        if english:
            return (
                "Ad experience: intermediate. Use a balanced style: name the important lever, give the practical reason, and include deeper detail only "
                "when it changes the decision."
            )
        return (
            "Experiencia en anuncios: intermedia. Usa un balance: nombra la palanca importante, da la razón práctica e incluye detalle profundo solo "
            "cuando cambie la decisión."
        )
    if english:
        return (
            "Ad experience: beginner. Act like the expert operator: do not make the buyer choose technical Ads Manager knobs unless required. "
            "Recommend the best-practice configuration, explain the money/business reason in plain words, and ask for approval only when spend or real-account change is involved."
        )
    return (
        "Experiencia en anuncios: principiante. Actúa como operador experto: no hagas que el comprador elija perillas técnicas de Ads Manager salvo que sea necesario. "
        "Recomienda la configuración de mejores prácticas, explica la razón de dinero/negocio con palabras simples y pide aprobación solo cuando haya gasto o cambio real de cuenta."
    )


def communication_preference(style=None, language="es", default="simple", ad_experience_level=None, ad_experience_default=""):
    style = normalize_communication_style(style, default=communication_style_from_environment(default=default))
    ad_level = normalize_ad_experience_level(ad_experience_level, default=ad_experience_from_environment(default=ad_experience_default))
    return {
        "style": style,
        "instruction": communication_style_instruction(style, language),
        "ad_experience_level": ad_level,
        "ad_experience_instruction": ad_experience_instruction(ad_level, language),
    }
