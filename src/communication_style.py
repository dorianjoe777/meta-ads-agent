#!/usr/bin/env python3
"""Installation-wide communication detail preference shared by every agent channel."""

import os

COMMUNICATION_STYLES = {"simple", "technical"}


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
            "details unless the buyer asks for them. This preference never overrides security, approval, evidence, or account-safety rules."
        )
    return (
        "Preferencia de comunicación: palabras simples. Empieza por la decisión y el impacto en el negocio, usa lenguaje cotidiano y evita jerga. "
        "Si un término técnico es necesario, explícalo de inmediato en una frase sencilla. No muestres código, comandos ni detalles internos de "
        "implementación salvo que el comprador los pida. Esta preferencia nunca cambia las reglas de seguridad, aprobación, evidencia o cuidado de la cuenta."
    )


def communication_preference(style=None, language="es", default="simple"):
    style = normalize_communication_style(style, default=communication_style_from_environment(default=default))
    return {
        "style": style,
        "instruction": communication_style_instruction(style, language),
    }
