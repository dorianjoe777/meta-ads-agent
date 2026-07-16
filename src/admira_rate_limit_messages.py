#!/usr/bin/env python3
"""Buyer-safe rate-limit messages for Admira IA provider errors."""
import math
import os
import re
import time


RATE_LIMIT_PATTERNS = (
    r"\b429\b",
    r"too many requests",
    r"rate[-\s]?limit",
    r"rate limited",
    r"usage[_\s-]?limit",
    r"usage cap",
    r"message limit",
    r"limit reached",
    r"quota exceeded",
    r"insufficient quota",
    r"l[ií]mite (?:temporal|de uso)",
    r"cuota excedida",
)


def is_rate_limit_text(text):
    value = str(text or "")
    return any(re.search(pattern, value, flags=re.IGNORECASE) for pattern in RATE_LIMIT_PATTERNS)


def _first_positive_int(patterns, text):
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            value = int(float(match.group(1)))
        except (TypeError, ValueError):
            continue
        if value >= 0:
            return value
    return None


def retry_seconds_from_text(text, now=None):
    """Extract a provider reset delay from raw exception text when present."""
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return None
    direct_seconds = _first_positive_int(
        (
            r"['\"]?resets_in_seconds['\"]?\s*[:=]\s*['\"]?(\d+)",
            r"['\"]?retry[_\s-]?after['\"]?\s*[:=]\s*['\"]?(\d+)",
            r"retry-after\s*:?\s*(\d+)",
            r"retry\s+after\s+(\d+)\s*(?:s|sec|secs|seconds?|segundos?)\b",
        ),
        value,
    )
    if direct_seconds is not None:
        return direct_seconds

    reset_at = _first_positive_int(
        (
            r"['\"]?resets_at['\"]?\s*[:=]\s*['\"]?(\d{10,})",
            r"['\"]?reset_at['\"]?\s*[:=]\s*['\"]?(\d{10,})",
            r"['\"]?reset_time['\"]?\s*[:=]\s*['\"]?(\d{10,})",
        ),
        value,
    )
    if reset_at is not None:
        return max(0, int(reset_at - (time.time() if now is None else now)))

    duration_match = re.search(
        r"(?:try again|retry|available|reset(?:s)?|limit reset(?:s)?|wait|intenta|reintenta|vuelve a intentar|reinicia)"
        r"(?:\s+\w+){0,6}\s+(?:in|after|for|en|despu[eé]s de|dentro de)\s+"
        r"(\d+)\s*(seconds?|minutes?|hours?|days?|segundos?|minutos?|horas?|d[ií]as?)",
        value,
        flags=re.IGNORECASE,
    )
    if duration_match:
        amount = int(duration_match.group(1))
        unit = duration_match.group(2).lower()
        if "day" in unit or "día" in unit or "dia" in unit:
            return amount * 86400
        if "hour" in unit or "hora" in unit:
            return amount * 3600
        if "minute" in unit or "minuto" in unit:
            return amount * 60
        return amount
    return None


def duration_label(seconds, language="es"):
    """Format a reset delay as a compact buyer-facing duration."""
    try:
        seconds = max(0, int(seconds))
    except (TypeError, ValueError):
        return ""
    english = str(language or "es").lower().startswith("en")
    if seconds < 60:
        return "less than 1 minute" if english else "menos de 1 minuto"
    total_minutes = max(1, int(math.ceil(seconds / 60)))
    if total_minutes < 60:
        unit = "minute" if total_minutes == 1 else "minutes"
        return f"{total_minutes} {unit}" if english else f"{total_minutes} minuto{'s' if total_minutes != 1 else ''}"
    total_hours = max(1, int(math.ceil(total_minutes / 60)))
    if total_hours < 48:
        unit = "hour" if total_hours == 1 else "hours"
        return f"{total_hours} {unit}" if english else f"{total_hours} hora{'s' if total_hours != 1 else ''}"
    days = total_hours // 24
    hours = total_hours % 24
    if english:
        day_label = f"{days} {'day' if days == 1 else 'days'}"
        if hours:
            return f"{day_label} and {hours} {'hour' if hours == 1 else 'hours'}"
        return day_label
    day_label = f"{days} día{'s' if days != 1 else ''}"
    if hours:
        return f"{day_label} y {hours} hora{'s' if hours != 1 else ''}"
    return day_label


def textual_retry_hint(text):
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    patterns = (
        r"(?:try again|retry|available|reset(?:s)?|limit reset(?:s)?)(?:\s+\w+){0,4}\s+(?:in|at|after|on|until)\s+([^.;\n]{2,90})",
        r"(?:please\s+)?wait\s+(?:for\s+)?([^.;\n]{2,60}?)(?:\s+and\s+try\s+again|$)",
        r"(?:intenta|vuelve a intentar|reintenta|reinicia|disponible)(?:\s+\w+){0,5}\s+(?:en|a las|despues de|después de|hasta)\s+([^.;\n]{2,90})",
        r"(?:after|in)\s+(\d+\s*(?:seconds?|minutes?|hours?|days?|segundos?|minutos?|horas?|d[ií]as?))",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            hint = match.group(1).strip(" .,:;")
            if hint:
                return hint[:90]
    return ""


def localized_textual_hint(hint, language="es"):
    value = str(hint or "").strip(" .,:;")
    if not value:
        return ""
    if str(language or "es").lower().startswith("en"):
        return value
    translated = value.lower()
    replacements = [
        (r"\ban hour\b", "1 hora"),
        (r"\ba minute\b", "1 minuto"),
        (r"\ba second\b", "1 segundo"),
        (r"\ba moment\b", "un momento"),
        (r"\bfew moments\b", "unos momentos"),
        (r"\bseconds?\b", "segundos"),
        (r"\bminutes?\b", "minutos"),
        (r"\bhours?\b", "horas"),
        (r"\bdays?\b", "días"),
        (r"\band\b", "y"),
    ]
    for pattern, replacement in replacements:
        translated = re.sub(pattern, replacement, translated, flags=re.IGNORECASE)
    return translated.strip(" .,:;")


def retry_delay_hint(text, language="es"):
    seconds = retry_seconds_from_text(text)
    if seconds is not None:
        return duration_label(seconds, language)
    hint = textual_retry_hint(text)
    if hint:
        return localized_textual_hint(hint, language)
    return ""


def codex_plan_type_from_text(text):
    """Return the ChatGPT plan reported by the Codex backend, when present."""
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    match = re.search(r"['\"]?plan_type['\"]?\s*[:=]\s*['\"]?([a-z0-9_-]+)", value, re.IGNORECASE)
    return match.group(1).strip().lower() if match else ""


def codex_go_limit_reply(text, language="es"):
    """Explain an account-wide ChatGPT Go Codex limit without false model advice."""
    english = str(language or "es").lower().startswith("en")
    hint = retry_delay_hint(text, "en" if english else "es")
    if english:
        reset = f" The account reports a reset in about {hint}." if hint else ""
        return (
            "⏱️ The Codex allowance included with ChatGPT Go has been used up."
            f"{reset} Switching between ChatGPT models will not reset this account allowance. "
            "To continue now, open Settings > Agent model and connect a ChatGPT Plus account, "
            "or use MiniMax or another official API for higher text volume."
        )
    reset = f" La cuenta indica que se reinicia en aprox. {hint}." if hint else ""
    return (
        "⏱️ Se agotó la cuota de Codex incluida en ChatGPT Go."
        f"{reset} Cambiar entre modelos de ChatGPT no restablece esta cuota de la cuenta. "
        "Para continuar ahora, abre Configuración > Modelo del agente y conecta una cuenta ChatGPT Plus, "
        "o usa MiniMax u otra API oficial si necesitas más volumen de texto."
    )


def lighter_model_switch_hint(language="es"):
    """Short buyer-facing hint for repeated ChatGPT/Codex text-model limits."""
    english = str(language or "es").lower().startswith("en")
    if english:
        return (
            "If this happens often, send /model in Telegram and choose a lighter option such as gpt-5.4 mini if it appears. "
            "That usually uses less of the heavy-model limit than gpt-5.5."
        )
    return (
        "Si esto pasa muy seguido, escribe /model en Telegram y elige una opción más ligera como gpt-5.4 mini si aparece. "
        "Suele gastar menos límite que gpt-5.5 para conversaciones normales."
    )


def gateway_rate_limit_reply(text, language="es"):
    """Return a concise Telegram-safe gateway notification for provider limits."""
    english = str(language or "es").lower().startswith("en")
    provider = str(os.environ.get("ADMIRA_GATEWAY_PROVIDER") or "").strip().lower().replace("_", "-")
    hint = retry_delay_hint(text, "en" if english else "es")
    if "nvidia" in provider:
        if english:
            base = "⏱️ NVIDIA NIM reached a temporary hosted-API limit."
            reset = f" Try again in about {hint}." if hint else " Try again later; NVIDIA did not send an exact reset time."
            return base + reset + " Your memory and work are safe; you can choose another NVIDIA model or another provider in Settings."
        base = "⏱️ NVIDIA NIM alcanzó un límite temporal de su API alojada."
        reset = f" Intenta de nuevo en aprox. {hint}." if hint else " Intenta de nuevo más tarde; NVIDIA no indicó una hora exacta."
        return base + reset + " Tu memoria y trabajo están seguros; puedes elegir otro modelo NVIDIA u otro proveedor en Configuración."
    if codex_plan_type_from_text(text) == "go":
        return codex_go_limit_reply(text, "en" if english else "es")
    model_hint = lighter_model_switch_hint("en" if english else "es")
    if english:
        base = "⏱️ ChatGPT/Codex hit a temporary usage limit."
        if hint:
            return f"{base} Try again in about {hint}. {model_hint}"
        return f"{base} Try again later; the provider did not send an exact reset time. {model_hint}"
    base = "⏱️ ChatGPT/Codex alcanzó un límite temporal de uso."
    if hint:
        return f"{base} Intenta de nuevo en aprox. {hint}. {model_hint}"
    return f"{base} Intenta de nuevo más tarde; el proveedor no dio una hora exacta de reinicio. {model_hint}"
