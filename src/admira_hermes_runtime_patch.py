#!/usr/bin/env python3
"""Runtime patches for third-party Hermes gateway buyer-facing messages.

The Hermes gateway is installed as a dependency inside the buyer container.
Admira should not edit site-packages in place, so this module is loaded through
PYTHONPATH/sitecustomize only for the gateway process and wraps the narrow
provider-error formatter that can otherwise leak raw English provider text.
"""
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from admira_rate_limit_messages import gateway_rate_limit_reply, is_rate_limit_text

ADMIRA_MINIMAX_PROVIDER = "admira-minimax"
ADMIRA_MINIMAX_PROVIDER_NAME = "MiniMax M3 oficial"
ADMIRA_MINIMAX_MODEL = "MiniMax-M3"
ADMIRA_MINIMAX_KEY_ENV = "ADMIRA_MINIMAX_API_KEY"
ADMIRA_MINIMAX_DEFAULT_BASE_URL = "https://api.minimax.io/v1"
ADMIRA_MINIMAX_ALIASES = {
    "minimax",
    "minimax m3",
    "minimax-m3",
    "minimax_m3",
    "minimaxm3",
    "minimax-m3-official",
    "minimax m3 official",
    "minimax m3 oficial",
    "minimax-m3-oficial",
    ADMIRA_MINIMAX_MODEL.lower(),
}
ADMIRA_MEDIA_EXTENSIONS = "png|jpe?g|gif|webp"
ADMIRA_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ADMIRA_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
ADMIRA_MEDIA_TAG_RE = re.compile(
    rf"MEDIA:\s*(?P<path>(?:/|~/)\S+?\.(?:{ADMIRA_MEDIA_EXTENSIONS})(?=[\s\"'`,;:)\]]|$))",
    re.IGNORECASE,
)
ADMIRA_OUTPUT_IMAGE_RE = re.compile(
    rf"(?P<path>(?:/|~/)\S*?/output/\S+?\.(?:{ADMIRA_MEDIA_EXTENSIONS})(?=[\s\"'`,;:)\]]|$))",
    re.IGNORECASE,
)
ADMIRA_GENERATED_MEDIA_KEYS = {
    "image_path",
    "media_attachment",
    "generated_image_path",
    "creative_image_path",
}
ADMIRA_RECENT_TURNS_LIMIT = 80
ADMIRA_AUTH_INVALID_PATTERNS = (
    "token_invalidated",
    "authentication token has been invalidated",
    "invalid_grant",
    "refresh token is invalid",
    "refresh token has been revoked",
    "oauth token has been revoked",
)
ADMIRA_PERSISTENCE_CLAIM_RE = re.compile(
    r"(?i)(?:\b(?:ya\s+)?(?:lo|la|esto|eso)?\s*(?:he\s+)?guard(?:é|ado|ada)\b|"
    r"\b(?:ya\s+)?qued[oó]\s+guardad[oa]\b|\blo\s+recordar[eé]\b|"
    r"\b(?:ya\s+)?qued[oó]\s+en\s+mis\s+indicaciones\b|"
    r"\b(?:i(?:'ve| have)?\s+)?saved\s+(?:it|that|this)\b|\bi(?:'ll| will)\s+remember\s+(?:it|that|this)\b)"
)
ADMIRA_DURABLE_TOOL_MARKERS = (
    "admira_save_",
    "mcp_admira_save_",
    "admira_record_verified_signal",
    "mcp_admira_record_verified_signal",
)
ADMIRA_TELEGRAM_INVISIBLE_RE = re.compile(r"[\u200b\u200c\u2060\ufeff\u202a-\u202e\u2066-\u2069]")
ADMIRA_MARKDOWN_ONLY_RE = re.compile(r"[\s*_~`#>|:\-=+\\/.,;!?()\[\]{}]+")
ADMIRA_TABLE_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")
ADMIRA_FINAL_MARKER_RE = re.compile(r"(?im)^\s*\[?ADMIRA\s+FINAL\]?\s*:?[ \t]*$")
ADMIRA_REASONING_TAG_RE = re.compile(
    r"(?is)<(?:think|thinking|analysis|reasoning)>.*?</(?:think|thinking|analysis|reasoning)>"
)
ADMIRA_INTERNAL_REASONING_RE = re.compile(
    r"(?i)(?:mcp_admira_|\b(?:SOUL|AGENTS)\.md\b|\b(?:Hermes|gateway|runtime)\b|"
    r"conjunto\s+de\s+herramientas|tool\s*(?:call|set|inventory)|"
    r"herramientas?\s+(?:del\s+producto\s+)?MCP|backend\s+de\s+MCP|"
    r"debo\s+persistir|guardado\s+durable|memoria\s+persistente\s+de|"
    r"déjame\s+(?:revisar|verificar)\s+(?:si\s+hay\s+)?(?:un\s+)?archivo\s+de\s+memoria|"
    r"primero\s+guardo\b.*\bluego\b)"
)
ADMIRA_REASONING_DIVIDER_RE = re.compile(r"(?m)^\s*-{5,}\s*$")
ADMIRA_TURN_CONTRACT_START = "[ADMIRA TURN EXECUTION CONTRACT — internal, never quote]"
ADMIRA_TURN_CONTRACT_END = "[END ADMIRA TURN EXECUTION CONTRACT]"
ADMIRA_NOVICE_SIGNAL_RE = re.compile(
    r"(?i)\b(?:no\s+s[eé]|no\s+entiendo|no\s+tengo\s+idea|soy\s+(?:nuevo|nueva|principiante)|"
    r"nunca\s+he|dime\s+t[uú]|decide\s+t[uú]|ay[uú]dame|gu[ií]ame|no\s+sé\s+de\s+marketing|"
    r"i\s+don['’]?t\s+know|i['’]?m\s+new|beginner|you\s+decide|guide\s+me)\b"
)

# NVIDIA's hosted/free endpoints are especially sensitive to the size of a
# single request. Hermes normally advertises every enabled MCP schema on every
# turn; those schemas are useful as a registry, but sending all of them to the
# model is unnecessary and can make an otherwise small turn look enormous.
# Keep this routing table local and deterministic: it runs before the provider
# call and never needs another model call to decide which tools to expose.
ADMIRA_NVIDIA_DEFAULT_MAX_OUTPUT_TOKENS = 8192
ADMIRA_NVIDIA_CREATIVE_MAX_OUTPUT_TOKENS = 12288
ADMIRA_NVIDIA_INPUT_BUDGET_TOKENS = 48000
ADMIRA_NVIDIA_TOOL_PROFILES = {
    "core": {
        "get_real_meta_context",
        "preflight_campaign",
        "search_meta_targeting",
        "inspect_adset_targeting",
        "review_signal_quality",
        "list_pending_approvals",
        "save_durable_memory",
        "save_business_memory",
        "save_agent_preferences",
        "search_product_catalog",
    },
    # A recommendation/targeting turn must not carry tools that can create,
    # pause, delete, or generate media.  This is deliberately separate from
    # campaign execution so a business conversation remains lightweight.
    "campaign_strategy": {
        "get_real_meta_context",
        "preflight_campaign",
        "search_meta_targeting",
        "inspect_adset_targeting",
        "review_signal_quality",
        "search_product_catalog",
        "save_agent_preferences",
        "save_ads_onboarding",
        "save_ad_brief",
        "save_durable_memory",
    },
    # This route assumes a buyer asked to materialize or modify a campaign.
    # It intentionally excludes image/video production and form creation.
    "campaign_execution": {
        "get_real_meta_context",
        "preflight_campaign",
        "search_meta_targeting",
        "inspect_adset_targeting",
        "review_signal_quality",
        "stage_campaign",
        "stage_budget_change",
        "pause_campaign",
        "resume_campaign",
        "schedule_campaign_activation",
        "delete_campaign",
        "approve_action",
        "reject_action",
        "save_ads_onboarding",
        "save_ad_brief",
        "set_campaign_metric_priorities",
        "list_pending_approvals",
        "save_durable_memory",
    },
    # Click-to-message has a different Meta payload and must not be diluted
    # by lead-form/video/page-post helpers.  The exact WhatsApp/Messenger/IG
    # identifiers are still resolved server-side from live Meta state.
    "messaging_campaign": {
        "get_real_meta_context",
        "preflight_campaign",
        "search_meta_targeting",
        "inspect_adset_targeting",
        "review_signal_quality",
        "stage_campaign",
        "save_ads_onboarding",
        "save_ad_brief",
        "save_durable_memory",
    },
    # A campaign can be discussed together with a pending creative.  Keep
    # production narrow and safe; the next explicit creation request routes
    # to campaign_execution once the media is ready.
    "campaign_media": {
        "fetch_public_asset",
        "codex_image_generate",
        "codex_creative_plan",
        "search_motion_graphic_recipes",
        "generate_motion_graphic_video",
        "save_content_asset",
        "save_brand_memory",
        "save_product_memory",
        "save_creative_references",
        "save_ad_brief",
        "save_durable_memory",
    },
    # Form creation needs a particularly small, deterministic tool surface.
    # Smaller hosted NIM models otherwise see the entire campaign/creative
    # registry and can emit an empty create_lead_form call, then waste the
    # next turns retrying it.  The handler itself will reject incomplete form
    # details, so exposing unrelated mutating tools cannot help this step.
    "lead_form": {
        "get_real_meta_context",
        "list_lead_forms",
        "create_lead_form",
        "stage_lead_form",
        "save_business_memory",
        "save_product_memory",
        "save_ad_brief",
        "save_durable_memory",
    },
    "creative": {
        "fetch_public_asset",
        "codex_image_generate",
        "codex_creative_plan",
        "search_motion_graphic_recipes",
        "generate_motion_graphic_video",
        "save_content_asset",
        "save_brand_memory",
        "save_product_memory",
        "save_creative_references",
        "save_ad_brief",
    },
    "organic": {
        "fetch_public_asset",
        "codex_image_generate",
        "codex_creative_plan",
        "search_motion_graphic_recipes",
        "generate_motion_graphic_video",
        "stage_organic_social_post",
        "save_daily_social_content_settings",
        "save_content_asset",
        "save_brand_memory",
        "save_product_memory",
        "save_creative_references",
    },
    "insights": {
        "get_real_meta_context",
        "run_daily_brief",
        "review_signal_quality",
        "set_campaign_metric_priorities",
        "list_experiment_reviews",
        "run_due_experiment_reviews",
        "schedule_experiment_review",
        "save_optimization_research",
        "list_optimization_research",
        "get_verified_signal_summary",
        "verified_signal_feedback_prompt",
    },
    "catalog": {
        "import_product_catalog",
        "search_product_catalog",
        "save_product_memory",
        "save_brand_memory",
        "save_content_asset",
        "save_ad_brief",
        "codex_creative_plan",
        "codex_image_generate",
    },
}
ADMIRA_NVIDIA_PROFILE_TERMS = {
    "creative": ("creative", "creativo", "imagen", "image", "video", "vídeo", "codex", "motion", "storyboard", "diseño", "logo"),
    "organic": ("orgánico", "organico", "organic", "post", "publication", "publicación", "publicar", "publish", "contenido diario", "daily content", "redes sociales", "social media"),
    "insights": ("métrica", "metricas", "métricas", "metrics", "insight", "rendimiento", "performance", "gasto", "spend", "ctr", "cpc", "roas", "checkout", "compras", "purchases"),
    "catalog": ("producto", "productos", "product", "products", "catálogo", "catalogo", "catalog", "sku", "oferta", "bundle", "pdf", "excel"),
}
ADMIRA_NVIDIA_LEAD_FORM_TERMS = (
    "formulario", "formularios", "lead form", "lead-form", "instant form",
    "formulario instantáneo", "formulario instantaneo", "clientes potenciales",
    "lead ads", "leadgen",
)
ADMIRA_NVIDIA_CAMPAIGN_TERMS = (
    "campaign", "campaña", "ad set", "conjunto de anuncios", "anuncio", "ads",
    "publicidad", "meta ads",
)
ADMIRA_NVIDIA_CAMPAIGN_ACTION_TERMS = (
    "crear", "crea", "create", "monta", "montar", "lanzar", "lanza", "launch",
    "prepara", "preparar", "duplicar", "duplica", "activar", "activa", "pausar",
    "pausa", "eliminar", "elimina", "delete", "resume", "reanuda",
)
ADMIRA_NVIDIA_CAMPAIGN_STRATEGY_TERMS = (
    "audiencia", "segmentación", "segmentacion", "targeting", "intereses", "interest",
    "ubicación", "ubicacion", "location", "geografía", "geografia", "edad", "género",
    "genero", "advantage", "presupuesto", "budget", "estrategia", "recomienda",
)
ADMIRA_NVIDIA_MESSAGING_CAMPAIGN_TERMS = (
    "whatsapp", "messenger", "instagram direct", "instagram dm", "mensajes",
    "conversaciones", "mensaje prellenado", "mensaje inicial", "prefilled",
)
ADMIRA_NVIDIA_CAMPAIGN_MEDIA_TERMS = (
    "creativo", "creative", "imagen", "image", "video", "vídeo", "image 2",
    "codex", "motion", "storyboard", "render", "reel", "receta",
)
ADMIRA_NVIDIA_MEDIA_PRODUCTION_TERMS = (
    "genera", "generar", "generate", "diseña", "disena", "diseñar", "disenar",
    "design", "produce", "producir", "renderiza", "renderizar", "image 2",
    "codex image", "crear imágenes", "crear imagen", "create images", "create image",
)

# Hermes versions pinned by existing Admira releases can mark the wrong
# OpenAI/Codex pool entry as exhausted after a 429. Keep the exact key that
# actually failed in task-local state so concurrent Telegram turns cannot
# contaminate one another while the upstream recovery helper rotates entries.
_ADMIRA_FAILED_CREDENTIAL_API_KEY = ContextVar("admira_failed_credential_api_key", default="")


def _strip_internal_context_notices(value):
    """Remove Hermes/Codex context housekeeping that buyers must never see."""
    kept = []
    removed = False
    for line in str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        lowered = line.strip().lower()
        internal = (
            ("context file" in lowered and "truncated" in lowered)
            or ("codex" in lowered and "caps context at" in lowered and "auto-compaction" in lowered)
            or "compression.codex_gpt55_autoraise" in lowered
            or lowered.startswith("opt back out: hermes config set compression.")
            or ("context compression" in lowered and ("aborted" in lowered or "failed" in lowered or "timed out" in lowered))
            or ("context length exceeded" in lowered and ("compressing" in lowered or "cannot compress" in lowered))
            or "cannot compress further" in lowered
        )
        if internal:
            removed = True
            continue
        kept.append(line)
    return "\n".join(kept), removed


def _strip_internal_reasoning(value):
    """Keep private planning and tool narration out of buyer-facing Telegram."""
    text = str(value or "")
    original = text
    text = ADMIRA_REASONING_TAG_RE.sub("", text)
    marker_matches = list(ADMIRA_FINAL_MARKER_RE.finditer(text))
    if marker_matches:
        text = text[marker_matches[-1].end():]
    else:
        segments = ADMIRA_REASONING_DIVIDER_RE.split(text)
        if len(segments) > 1 and any(ADMIRA_INTERNAL_REASONING_RE.search(segment or "") for segment in segments[:-1]):
            text = segments[-1]
        paragraphs = re.split(r"\n\s*\n", text)
        text = "\n\n".join(
            paragraph
            for paragraph in paragraphs
            if paragraph.strip() and not ADMIRA_INTERNAL_REASONING_RE.search(paragraph)
        )
    cleaned = text.strip()
    return cleaned, cleaned != original.strip()


def _is_codex_pool_quota_error(text):
    value = str(text or "").lower()
    return (
        "openai codex" in value or "openai-codex" in value
    ) and (
        "could not resolve credentials" in value
        or "credentials are still valid" in value
    ) and (
        "quota exhausted" in value
        or "usage_limit_reached" in value
        or "rate limit" in value
        or "429" in value
    )


def _reset_openai_codex_pool_statuses():
    """Clear only local cooldown flags; never remove OAuth credentials."""
    try:
        from agent.credential_pool import load_pool

        return int(load_pool("openai-codex").reset_statuses() or 0)
    except Exception:
        return 0


def _telegram_delivery_diagnostics_path():
    configured = str(os.environ.get("ADMIRA_TELEGRAM_DELIVERY_DIAGNOSTICS_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser()
    root = str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "").strip()
    if not root:
        return None
    return Path(root).expanduser() / "logs" / "hermes-telegram-delivery.jsonl"


def _markdown_table_cells(line):
    value = str(line or "").strip()
    if "|" not in value:
        return []
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]
    return [cell.strip() for cell in value.split("|")]


def _is_markdown_table_separator(line):
    cells = _markdown_table_cells(line)
    return len(cells) >= 2 and all(ADMIRA_TABLE_SEPARATOR_CELL_RE.fullmatch(cell.replace(" ", "")) for cell in cells)


def _render_markdown_tables_as_text(value):
    """Turn Markdown tables into Telegram-safe, readable bullets.

    Hermes' Telegram renderer can evolve independently from Admira. Converting
    tables before platform rendering keeps projections readable even when a
    model ignores the buyer-facing instruction to avoid Markdown tables.
    """
    lines = str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    rendered = []
    index = 0
    in_code_fence = False
    changed = False
    while index < len(lines):
        line = lines[index]
        if line.strip().startswith("```"):
            in_code_fence = not in_code_fence
            rendered.append(line)
            index += 1
            continue
        if (
            not in_code_fence
            and index + 1 < len(lines)
            and len(_markdown_table_cells(line)) >= 2
            and _is_markdown_table_separator(lines[index + 1])
        ):
            headers = _markdown_table_cells(line)
            row_index = index + 2
            rows = []
            while row_index < len(lines):
                cells = _markdown_table_cells(lines[row_index])
                if len(cells) < 2 or _is_markdown_table_separator(lines[row_index]):
                    break
                rows.append(cells)
                row_index += 1
            if rows:
                for number, cells in enumerate(rows, start=1):
                    padded = cells + [""] * max(0, len(headers) - len(cells))
                    first = padded[0].strip() or f"Fila {number}"
                    rendered.append(f"• {first}")
                    for column, header in enumerate(headers[1:], start=1):
                        cell = padded[column].strip() if column < len(padded) else ""
                        if cell:
                            rendered.append(f"  - {(header or f'Columna {column + 1}').strip()}: {cell}")
                changed = True
                index = row_index
                continue
        rendered.append(line)
        index += 1
    return "\n".join(rendered), changed


def _has_visible_telegram_content(value):
    text = str(value or "")
    if ADMIRA_MEDIA_TAG_RE.search(text):
        return True
    candidate = ADMIRA_MARKDOWN_ONLY_RE.sub("", text)
    return any(character.isalnum() or unicodedata.category(character).startswith("S") for character in candidate)


def normalize_telegram_outbound_text(value, language=None):
    """Return non-empty Telegram-safe text plus delivery diagnostics metadata."""
    original = str(value or "")
    cleaned = ADMIRA_TELEGRAM_INVISIBLE_RE.sub("", original)
    cleaned, context_notice_removed = _strip_internal_context_notices(cleaned)
    cleaned, internal_reasoning_removed = _strip_internal_reasoning(cleaned)
    cleaned, table_changed = _render_markdown_tables_as_text(cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned).strip()
    fallback = False
    suppressed = context_notice_removed and not _has_visible_telegram_content(cleaned)
    if suppressed:
        # Hermes recognizes this exact marker as intentional silence and will
        # not replace it with its generic empty-response warning.
        cleaned = "NO_REPLY"
    if not suppressed and not _has_visible_telegram_content(cleaned):
        fallback = True
        language = str(language or os.environ.get("ADMIRA_GATEWAY_LANGUAGE", "es")).lower()
        cleaned = (
            "I could not display the previous answer correctly. Ask me to repeat the last analysis and I will send it as plain text."
            if language.startswith("en")
            else "No pude mostrar correctamente la respuesta anterior. Pídeme repetir el último análisis y lo enviaré en texto simple."
        )
    reasons = []
    if table_changed:
        reasons.append("markdown_table_converted")
    if context_notice_removed:
        reasons.append("internal_context_notice_removed")
    if internal_reasoning_removed:
        reasons.append("internal_reasoning_removed")
    if ADMIRA_TELEGRAM_INVISIBLE_RE.search(original):
        reasons.append("invisible_characters_removed")
    if fallback:
        reasons.append("empty_or_format_only_fallback")
    return cleaned, {
        "original_length": len(original),
        "delivered_length": len(cleaned),
        "changed": cleaned != original,
        "fallback": fallback,
        "suppressed": suppressed,
        "reasons": reasons,
        "content_sha256": hashlib.sha256(original.encode("utf-8", errors="replace")).hexdigest()[:16],
    }


def _record_telegram_delivery_diagnostic(metadata, delivered_text):
    path = _telegram_delivery_diagnostics_path()
    if not path or not isinstance(metadata, dict):
        return False
    event = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        **metadata,
        "safe_preview": _redact_turn_text(delivered_text)[:300],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return True
    except OSError:
        return False


def _normalize_gateway_outbound_response(response):
    if isinstance(response, str):
        cleaned, metadata = normalize_telegram_outbound_text(response)
        _record_telegram_delivery_diagnostic(metadata, cleaned)
        return cleaned
    if not isinstance(response, dict):
        return response
    response_key = next((key for key in ("final_response", "response", "message") if key in response), None)
    if response_key is None:
        return response
    cleaned, metadata = normalize_telegram_outbound_text(response.get(response_key))
    response[response_key] = cleaned
    _record_telegram_delivery_diagnostic({**metadata, "response_key": response_key}, cleaned)
    return response


def _recent_turns_path():
    configured = str(os.environ.get("ADMIRA_TELEGRAM_RECENT_TURNS_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser()
    root = str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "").strip()
    if not root:
        return None
    return Path(root).expanduser() / "dashboard" / "data" / "hermes_gateway_recent_turns.json"


def _redact_turn_text(value):
    text = str(value or "")
    if not text:
        return ""
    lower = text.lower()
    if "código temporal para conectar chatgpt" in lower or "temporary code to connect chatgpt" in lower:
        return "Se inició una reconexión segura de ChatGPT/Codex. Los datos temporales de acceso no se guardaron."
    clean = re.sub(r"\[ADMIRA LIVE META CONTEXT.*?\[END ADMIRA LIVE META CONTEXT\]", "[live Meta context synchronized]", text, flags=re.DOTALL)
    clean = re.sub(r"\[ADMIRA TURN EXECUTION CONTRACT.*?\[END ADMIRA TURN EXECUTION CONTRACT\]", "", clean, flags=re.DOTALL)
    clean = re.sub(r"MEDIA:\s*(?:/|~/)\S+", "MEDIA:[attached]", clean)
    product_root = str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "").strip().rstrip("/")
    if product_root:
        clean = clean.replace(product_root, "[internal-path]")
    clean = re.sub(r"(?:/app|/Users|/root)(?:/[^\s\"'`]+)+", "[internal-path]", clean)
    clean = re.sub(r"\b(?:EA[A-Za-z0-9_-]{40,}|EAA[A-Za-z0-9_-]{40,})\b", "[redacted-token]", clean)
    clean = re.sub(r"\bdop_v1_[A-Za-z0-9_-]{40,}\b", "[redacted-token]", clean)
    clean = re.sub(r"\bsk-[A-Za-z0-9_-]{24,}\b", "[redacted-token]", clean)
    clean = re.sub(r"(?i)\b(passphrase|password|contraseña|token|api key|access token)\s*[:=]\s*\S+", r"\1: [redacted]", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:5000]


def _message_requires_live_meta_sync(value):
    text = str(value or "").strip()
    if not text or "[ADMIRA LIVE META CONTEXT" in text:
        return False
    # Slash commands are gateway controls rather than buyer conversations.
    # Every ordinary buyer message receives a fresh Meta snapshot, even when
    # the visible topic is branding, creative work, onboarding, or something
    # unrelated to performance. This keeps the manager continuously oriented
    # without forcing the buyer to ask for a refresh.
    if re.match(r"^/(?:start|help|model|reset|resume|stop|status|new)(?:\s|$)", text, re.IGNORECASE):
        return False
    return True


def _append_turn_execution_contract(value):
    """Put the manager-led response contract at the model's recency edge.

    SOUL and skills remain the durable policy. This short per-turn reminder is
    deliberately appended after live account context because long gateway
    prompts can otherwise make smaller models regress into lectures, passive
    checklists, or generic permission questions.
    """
    text = str(value or "").strip()
    if not text or ADMIRA_TURN_CONTRACT_START in text:
        return value
    if re.match(r"^/(?:start|help|model|reset|resume|stop|status|new)(?:\s|$)", text, re.IGNORECASE):
        return value
    style = str(os.environ.get("AGENT_COMMUNICATION_STYLE") or "simple").strip().lower()
    experience = str(os.environ.get("AGENT_AD_EXPERIENCE_LEVEL") or "").strip().lower()
    novice = experience == "beginner" or bool(ADMIRA_NOVICE_SIGNAL_RE.search(text))
    if style != "simple" and not novice:
        return text
    language = str(os.environ.get("ADMIRA_GATEWAY_LANGUAGE") or "es").strip().lower()
    if language.startswith("en"):
        contract = (
            f"{ADMIRA_TURN_CONTRACT_START}\n"
            "This buyer-facing turn must feel led by a senior manager, not by a form or a course. "
            "Silently identify the immediate business goal, inspect live Meta/tools/files before asking for anything discoverable, and choose one recommended path. "
            "Advance every safe, already-authorized step now. Before asking, identify all owner-only inputs needed to finish the next deliverable. Ask at most one concise blocking question; if several tightly related owner facts or uploads are essential, request them together once in one compact packet. "
            "For a beginner, state the decision, one business reason or risk, and the concrete next action in at most 180 words. Do not dump alternatives or end with an 'if you want' invitation. "
            "When recommending price or ad budget and costs are known, calculate contribution margin and the approximate incremental sales/leads needed to recover ad spend before choosing the test.\n"
            f"{ADMIRA_TURN_CONTRACT_END}"
        )
    else:
        contract = (
            f"{ADMIRA_TURN_CONTRACT_START}\n"
            "Este turno debe sentirse guiado por un manager senior, no por un formulario ni una clase. "
            "Identifica en silencio el objetivo inmediato, consulta Meta/herramientas/archivos antes de preguntar cualquier dato descubrible y elige una sola ruta recomendada. "
            "Avanza ahora todo paso seguro ya autorizado. Antes de preguntar, identifica todos los insumos del dueño necesarios para terminar el siguiente entregable. Haz como máximo una pregunta bloqueante; si faltan varios datos o archivos del dueño estrechamente relacionados, pídelos juntos una sola vez en un paquete breve. "
            "Para un principiante, entrega decisión, una razón o riesgo de negocio y la acción concreta siguiente en máximo 180 palabras. No descargues alternativas ni termines con una invitación tipo «si quieres». "
            "Si recomiendas precio o presupuesto y ya conoces los costos, calcula el margen de contribución y las ventas/leads adicionales aproximados necesarios para recuperar la pauta antes de elegir el test.\n"
            f"{ADMIRA_TURN_CONTRACT_END}"
        )
    return f"{text}\n\n{contract}"


def _fetch_live_meta_context_for_turn():
    root = Path(str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "").strip()).expanduser()
    bridge = root / "src" / "admira_tool_bridge.py"
    if not root.is_dir() or not bridge.is_file():
        return {"ok": False, "reason": "product_bridge_unavailable"}
    try:
        completed = subprocess.run(
            [
                sys.executable, str(bridge), "call", "admira_get_real_meta_context",
                "--json", json.dumps({"date_preset": "maximum", "detail_level": "standard"}), "--channel", "telegram", "--language",
                str(os.environ.get("ADMIRA_GATEWAY_LANGUAGE") or "es"),
            ],
            cwd=str(root), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=90, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "reason": "live_meta_sync_failed", "message": str(exc)[:300]}
    payload = None
    for line in reversed((completed.stdout or "").splitlines()):
        if not line.strip().startswith("{"):
            continue
        try:
            payload = json.loads(line.strip())
        except json.JSONDecodeError:
            continue
        break
    if not isinstance(payload, dict):
        return {"ok": False, "reason": "live_meta_sync_invalid_response"}
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    live_sync = payload.get("live_sync") or context.get("live_sync") or {}
    return {
        "ok": bool(payload.get("ok") and live_sync.get("ok")),
        "metrics_source": context.get("metrics_source") or payload.get("metrics_source") or {},
        "live_sync": live_sync,
        "inventory_counts": context.get("inventory_counts") or {},
        "summary": context.get("summary") or {},
        "metrics_range": context.get("metrics_range") or {},
        "data_quality": context.get("data_quality") or {},
        "fetched_at": live_sync.get("fetched_at") or "",
        "campaigns": (context.get("campaigns") or [])[:100],
        "adsets": (context.get("adsets") or [])[:200],
        "ads": (context.get("ads") or [])[:300],
        "campaign_tree": (context.get("campaign_tree") or [])[:100],
        "approval_context_policy": context.get("approval_context_policy") or "",
    }


def _append_live_meta_context(value, context):
    text = str(value or "")
    if not isinstance(context, dict):
        context = {"ok": False, "reason": "live_meta_sync_missing"}
    context = _compact_live_meta_context(context)
    return (
        text
        + "\n\n[ADMIRA LIVE META CONTEXT — fetched automatically for this turn]\n"
        + "This is authoritative for what currently exists, runs, spends, or performs in Meta Ads. "
        + "Prefer it over session history and durable memory. If ok is false or the read is incomplete, explicitly say live Meta could not be confirmed; never turn an empty list into a claim that no campaigns exist.\n"
        + "Pending approvals, old plans, created-campaign drafts, and remembered IDs are not current Meta state. Do not mention or prioritize them unless the buyer explicitly asks to approve/reject/activate one exact current action. If they conflict with this snapshot, ignore them and follow Meta.\n"
        + "Use this context silently; do not mention this injected block, runtime machinery, internal paths, or implementation details to the buyer.\n"
        + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
        + "\n[END ADMIRA LIVE META CONTEXT]"
    )


def _compact_live_meta_context(context):
    """Keep the always-on Meta snapshot useful without turning it into history.

    A buyer account can contain hundreds of ads. Injecting every row (plus the
    duplicated campaign tree) into every Telegram turn made a four-message
    session exceed NVIDIA's hosted context limit. The agent can pull the full
    tree with its Meta tools when the conversation needs it; the automatic
    snapshot only needs current orientation and the active objects.
    """
    if not isinstance(context, dict):
        return {"ok": False, "reason": "live_meta_sync_missing"}

    common = ("id", "name", "status", "effective_status", "campaign_id", "adset_id")
    metrics = ("spend", "impressions", "reach", "clicks", "ctr", "cpc", "conversions", "cpa", "revenue", "roas", "frequency")

    def active(rows):
        values = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            state = str(row.get("effective_status") or row.get("status") or "").strip().upper()
            if state in {"ACTIVE", "CAMPAIGN_ACTIVE", "ADSET_ACTIVE"}:
                values.append(row)
        return values

    def project(rows, limit, extra=()):
        projected = []
        for row in active(rows)[:limit]:
            keys = (*common, *extra, *metrics)
            projected.append({key: row.get(key) for key in keys if row.get(key) not in (None, "", [], {})})
        return projected

    campaigns = project(
        context.get("campaigns"),
        20,
        ("objective", "daily_budget", "priority_metrics", "metric_profile"),
    )
    campaign_ids = {str(row.get("id") or "") for row in campaigns}
    adsets_source = [
        row for row in (context.get("adsets") or [])
        if not campaign_ids or str((row or {}).get("campaign_id") or "") in campaign_ids
    ]
    adsets = project(
        adsets_source,
        40,
        ("optimization_goal", "billing_event", "daily_budget", "lifetime_budget"),
    )
    adset_ids = {str(row.get("id") or "") for row in adsets}
    ads_source = [
        row for row in (context.get("ads") or [])
        if not adset_ids or str((row or {}).get("adset_id") or "") in adset_ids
    ]
    ads = project(ads_source, 60, ("creative_id", "object_story_id"))
    return {
        "ok": bool(context.get("ok")),
        "fetched_at": context.get("fetched_at") or "",
        "metrics_source": context.get("metrics_source") or {},
        "live_sync": context.get("live_sync") or {},
        "inventory_counts": context.get("inventory_counts") or {},
        "summary": context.get("summary") or {},
        "metrics_range": context.get("metrics_range") or {},
        "data_quality": context.get("data_quality") or {},
        "active_campaigns": campaigns,
        "active_adsets": adsets,
        "active_ads": ads,
        "snapshot_scope": {
            "active_only": True,
            "campaign_limit": 20,
            "adset_limit": 40,
            "ad_limit": 60,
            "full_live_detail_tool": "mcp_admira_get_real_meta_context",
        },
        "reason": context.get("reason") or "",
    }


def _strip_admira_runtime_injections(value):
    """Return only buyer-authored text for durable Hermes history."""
    text = str(value or "")
    text = re.sub(
        r"\n*\[ADMIRA LIVE META CONTEXT.*?\[END ADMIRA LIVE META CONTEXT\]\s*",
        "\n",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"\n*\[ADMIRA TURN EXECUTION CONTRACT.*?\[END ADMIRA TURN EXECUTION CONTRACT\]\s*",
        "\n",
        text,
        flags=re.DOTALL,
    )
    return text.strip()


def _append_gateway_turn(role, content):
    path = _recent_turns_path()
    text = _redact_turn_text(content)
    if not path or not text:
        return False
    try:
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        else:
            existing = []
        existing.append(
            {
                "role": "agent" if str(role or "").lower() in {"agent", "assistant"} else "user",
                "content": text,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source": "hermes_gateway",
            }
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing[-ADMIRA_RECENT_TURNS_LIMIT:], ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return True
    except Exception:
        return False


def _runtime_model_state_path():
    configured = str(os.environ.get("ADMIRA_TELEGRAM_MODEL_STATE_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser()
    root = str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "").strip()
    if not root:
        return None
    return Path(root).expanduser() / "dashboard" / "data" / "telegram_model_state.json"


def _model_switch_succeeded(result):
    if isinstance(result, dict):
        if result.get("success") is False or result.get("ok") is False:
            return False
        if str(result.get("status") or "").strip().lower() in {"failed", "error", "cancelled", "canceled"}:
            return False
    return True


def _write_runtime_model_state(provider, model, base_url="", source="telegram_model_command"):
    path = _runtime_model_state_path()
    if not path:
        return False
    provider = str(provider or "").strip()
    model = str(model or "").strip()
    if not (provider or model):
        return False
    payload = {
        "provider": provider,
        "model": model,
        "base_url": str(base_url or "").strip(),
        "source": source,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return True
    except OSError:
        return False


def is_authentication_error_text(text):
    lowered = str(text or "").lower()
    if any(pattern in lowered for pattern in ADMIRA_AUTH_INVALID_PATTERNS):
        return True
    return any(
        pattern in lowered
        for pattern in (
            "provider authentication failed",
            "authentication failed",
            "authenticationerror",
            "unauthorized provider",
        )
    )


def _dashboard_recovery_link():
    raw = str(os.environ.get("ADMIRA_DASHBOARD_RECOVERY_URL") or "").strip()
    if not raw:
        return "", ""
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError:
        return "", ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return "", ""
    safe = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))
    kind = "portal" if str(os.environ.get("ADMIRA_DASHBOARD_RECOVERY_KIND") or "").lower() == "portal" else "dashboard"
    return safe, kind


def _safe_openai_login_url(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError:
        return ""
    hostname = str(parsed.hostname or "").lower().rstrip(".")
    allowed = hostname in {"openai.com", "chatgpt.com"} or hostname.endswith(".openai.com") or hostname.endswith(".chatgpt.com")
    if parsed.scheme != "https" or not allowed or parsed.username or parsed.password:
        return ""
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _internal_recovery_settings():
    raw_url = str(os.environ.get("ADMIRA_INTERNAL_MODEL_RECOVERY_URL") or "").strip()
    token_path = str(os.environ.get("ADMIRA_INTERNAL_MODEL_RECOVERY_TOKEN_FILE") or "").strip()
    if not raw_url or not token_path:
        return "", ""
    try:
        parsed = urllib.parse.urlsplit(raw_url)
    except ValueError:
        return "", ""
    if parsed.scheme != "http" or str(parsed.hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
        return "", ""
    try:
        token = Path(token_path).expanduser().read_text(encoding="utf-8").strip()
    except OSError:
        return "", ""
    if len(token) < 32:
        return "", ""
    return raw_url, token


def _request_internal_model_recovery(action):
    url, token = _internal_recovery_settings()
    if not url:
        return {}
    body = json.dumps({"action": str(action or "status")}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Admira-Internal-Recovery": token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            if int(getattr(response, "status", 200)) != 200:
                return {}
            payload = json.loads(response.read(64 * 1024).decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError):
        return {}
    result = payload.get("result") if isinstance(payload, dict) else {}
    return result if isinstance(result, dict) else {}


def _automatic_codex_recovery(wait_seconds=12):
    if not _internal_recovery_settings()[0]:
        return {}
    result = _request_internal_model_recovery("start")
    deadline = time.monotonic() + max(0, min(float(wait_seconds), 15))
    while time.monotonic() < deadline:
        urls = [_safe_openai_login_url(item) for item in (result.get("urls") or [])]
        login_url = next((item for item in urls if item), "")
        codes = result.get("login_codes") if isinstance(result.get("login_codes"), list) else []
        login_code = str(result.get("login_code") or (codes[0] if codes else "")).strip()
        login_code = login_code if re.fullmatch(r"[A-Z0-9](?:[A-Z0-9-]{4,30})[A-Z0-9]", login_code.upper()) else ""
        if login_url and login_code:
            return {"url": login_url, "code": login_code.upper()}
        if str(result.get("phase") or "") == "device_auth_settings":
            return {"device_auth_settings": True}
        if result and not result.get("running") and str(result.get("status") or "") not in {"browser_login_started", "browser_login_waiting", "needs_login"}:
            break
        time.sleep(0.65)
        result = _request_internal_model_recovery("status")
    return {}


def gateway_authentication_reply(text, language=None):
    language = str(language or os.environ.get("ADMIRA_GATEWAY_LANGUAGE", "es")).lower()
    lowered = str(text or "").lower()
    codex_session = any(
        marker in lowered
        for marker in (
            "token_invalidated",
            "authentication token has been invalidated",
            "openai-codex",
            "chatgpt.com/backend-api/codex",
        )
    )
    codex_session = codex_session or "codex" in str(os.environ.get("ADMIRA_GATEWAY_PROVIDER") or "").lower()
    recovery_url, recovery_kind = _dashboard_recovery_link()
    automatic = _automatic_codex_recovery() if codex_session else {}
    if language.startswith("en"):
        if codex_session:
            intro = "🔐 The ChatGPT/Codex connection expired or was closed."
            if automatic.get("url") and automatic.get("code"):
                return (
                    f"{intro}\n\nI opened a new secure login for you:\n"
                    f"1. Open: {automatic['url']}\n"
                    f"2. Enter this temporary code to connect ChatGPT: {automatic['code']}\n"
                    "3. Finish the ChatGPT login and then message me again.\n\n"
                    "The code expires shortly. Your saved business memory and work are safe."
                )
            if recovery_url:
                first_step = f"1. Open your Admira access page and then open the dashboard: {recovery_url}" if recovery_kind == "portal" else f"1. Open the dashboard: {recovery_url}"
                return (
                    f"{intro}\n\nTo reconnect it:\n{first_step}\n"
                    "2. Open Setup.\n3. Find Agent model.\n4. Open ChatGPT subscription.\n"
                    "5. Click connect/reconnect and finish the secure ChatGPT login.\n\n"
                    "Your saved business memory and work are safe."
                )
            return f"{intro} Open Setup → Agent model → ChatGPT subscription and reconnect the account. Your saved business memory and work are safe."
        return (
            "🔐 The agent model connection is no longer valid. Open Settings → Agent model and reconnect "
            "the selected provider. Your saved business memory and work are safe."
        )
    if codex_session:
        intro = "🔐 La conexión de ChatGPT/Codex venció o fue cerrada."
        if automatic.get("url") and automatic.get("code"):
            return (
                f"{intro}\n\nYa abrí un login seguro nuevo:\n"
                f"1. Abre: {automatic['url']}\n"
                f"2. Escribe este código temporal para conectar ChatGPT: {automatic['code']}\n"
                "3. Termina el login de ChatGPT y luego vuelve a escribirme.\n\n"
                "El código vence pronto. La memoria y el trabajo guardado no se pierden."
            )
        if recovery_url:
            first_step = f"1. Abre tu acceso de Admira y luego abre el dashboard: {recovery_url}" if recovery_kind == "portal" else f"1. Abre el dashboard: {recovery_url}"
            return (
                f"{intro}\n\nPara reconectarla:\n{first_step}\n"
                "2. Entra a Configuración.\n3. Busca Modelo del agente.\n4. Abre ChatGPT suscripción.\n"
                "5. Toca conectar/reconectar y completa el login seguro de ChatGPT.\n\n"
                "La memoria y el trabajo guardado no se pierden."
            )
        return f"{intro} Abre Configuración → Modelo del agente → ChatGPT suscripción y vuelve a conectar la cuenta. La memoria y el trabajo guardado no se pierden."
    return (
        "🔐 La conexión del modelo dejó de ser válida. Abre Configuración → Modelo del agente y vuelve a "
        "conectar el proveedor seleccionado. La memoria y el trabajo guardado no se pierden."
    )


def provider_error_reply(text, language=None, original=None):
    if _is_codex_pool_quota_error(text):
        _reset_openai_codex_pool_statuses()
        english = str(language or os.environ.get("ADMIRA_GATEWAY_LANGUAGE", "es")).lower().startswith("en")
        if english:
            return (
                "♻️ Admira cleared a stale local ChatGPT/Codex limit state. "
                "Send your message again. If it persists, open /model and select the model once more."
            )
        return (
            "♻️ Admira limpió un estado local desactualizado del límite de ChatGPT/Codex. "
            "Envía tu mensaje otra vez. Si persiste, abre /model y elige el modelo una vez más."
        )
    if is_rate_limit_text(text):
        return gateway_rate_limit_reply(text, language or os.environ.get("ADMIRA_GATEWAY_LANGUAGE", "es"))
    if is_authentication_error_text(text):
        return gateway_authentication_reply(text, language)
    if callable(original):
        return original(text)
    return str(text or "")


def _patch_credential_pool_failure_assignment():
    """Ensure Hermes marks the credential that actually produced the error.

    Older Hermes recovery code calls ``mark_exhausted_and_rotate`` without the
    available ``api_key_hint``. If another process already rotated the pool,
    Hermes can therefore mark the next healthy account as exhausted and report
    a bogus multi-week cooldown. This narrow runtime patch mirrors the upstream
    fix while keeping the vendored dependency untouched.
    """
    try:
        import agent.agent_runtime_helpers as runtime_helpers
        import agent.credential_pool as credential_pool
    except Exception:
        return False

    patched_any = False
    pool_class = getattr(credential_pool, "CredentialPool", None)
    original_mark = getattr(pool_class, "mark_exhausted_and_rotate", None) if pool_class else None
    if callable(original_mark) and not getattr(pool_class, "_admira_exact_failure_assignment_patch", False):
        def patched_mark_exhausted_and_rotate(self, *args, **kwargs):
            if not kwargs.get("api_key_hint"):
                hint = str(_ADMIRA_FAILED_CREDENTIAL_API_KEY.get() or "").strip()
                if hint:
                    kwargs["api_key_hint"] = hint
            return original_mark(self, *args, **kwargs)

        pool_class._admira_original_mark_exhausted_and_rotate = original_mark
        pool_class.mark_exhausted_and_rotate = patched_mark_exhausted_and_rotate
        pool_class._admira_exact_failure_assignment_patch = True
        patched_any = True

    original_recover = getattr(runtime_helpers, "recover_with_credential_pool", None)
    if callable(original_recover) and not getattr(runtime_helpers, "_admira_exact_failure_assignment_patch", False):
        def patched_recover_with_credential_pool(agent, *args, **kwargs):
            failed_key = str(getattr(agent, "api_key", "") or "").strip()
            token = _ADMIRA_FAILED_CREDENTIAL_API_KEY.set(failed_key)
            try:
                return original_recover(agent, *args, **kwargs)
            finally:
                _ADMIRA_FAILED_CREDENTIAL_API_KEY.reset(token)

        runtime_helpers._admira_original_recover_with_credential_pool = original_recover
        runtime_helpers.recover_with_credential_pool = patched_recover_with_credential_pool
        runtime_helpers._admira_exact_failure_assignment_patch = True
        patched_any = True

    return patched_any or bool(getattr(runtime_helpers, "_admira_exact_failure_assignment_patch", False))


def _admira_failover_reason_text(reason):
    value = getattr(reason, "value", reason)
    return f"{value or ''} {reason or ''}".strip().lower()


def _admira_same_nvidia_fallback_blocked(reason):
    """Classify failures that are shared by every model under one NIM key.

    A model-specific timeout/5xx/empty response may be recoverable by trying a
    different NIM pool.  A quota, upstream rate limit, authentication, or
    billing failure is not: rotating models with the same key only creates more
    requests and can make the provider impose a longer cooldown.
    """
    text = _admira_failover_reason_text(reason)
    return any(marker in text for marker in (
        "rate_limit",
        "rate limit",
        "upstream_rate_limit",
        "upstream rate limit",
        "billing",
        "quota",
        "auth",
        "authentication",
        "unauthorized",
        "forbidden",
    ))


def _admira_provider_name(value):
    if isinstance(value, dict):
        value = value.get("provider") or value.get("slug") or value.get("name")
    else:
        value = getattr(value, "provider", value)
    return str(value or "").strip().lower().replace("_", "-")


def _patch_same_nvidia_model_failover_guard():
    """Skip same-key NIM entries only for shared quota/auth failures.

    The actual fallback selection remains Hermes' own implementation.  This
    narrow guard prevents a same-NIM candidate from following a 429 while
    preserving it for model-specific transport/provider failures.
    """
    try:
        import agent.chat_completion_helpers as helpers
    except Exception:
        return False
    original = getattr(helpers, "try_activate_fallback", None)
    if not callable(original):
        return False
    if getattr(original, "_admira_same_nvidia_guard", False):
        return True

    def patched_try_activate_fallback(agent, reason=None, *args, **kwargs):
        current_provider = _admira_provider_name(getattr(agent, "provider", ""))
        if current_provider == "admira-nvidia" and _admira_same_nvidia_fallback_blocked(reason):
            chain = list(getattr(agent, "_fallback_chain", []) or [])
            index = int(getattr(agent, "_fallback_index", 0) or 0)
            while index < len(chain):
                candidate = chain[index]
                if _admira_provider_name(candidate) != "admira-nvidia":
                    break
                index += 1
            try:
                agent._fallback_index = index
            except Exception:
                pass
        return original(agent, reason, *args, **kwargs)

    patched_try_activate_fallback._admira_same_nvidia_guard = True
    patched_try_activate_fallback._admira_original_try_activate_fallback = original
    helpers.try_activate_fallback = patched_try_activate_fallback
    return True


def _nvidia_tool_name(tool):
    """Return a provider-tool name without assuming one SDK schema shape."""
    if not isinstance(tool, dict):
        return ""
    function = tool.get("function")
    if isinstance(function, dict) and function.get("name"):
        return str(function.get("name") or "").strip()
    return str(tool.get("name") or "").strip()


def _nvidia_normalize_tool_name(name):
    value = str(name or "").strip().lower()
    for prefix in ("mcp_admira_", "admira_", "mcp_"):
        if value.startswith(prefix):
            return value[len(prefix):]
    return value


def _nvidia_message_text(messages):
    parts = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, list):
            content = " ".join(
                str(item.get("text") or item.get("content") or "")
                for item in content
                if isinstance(item, dict)
            )
        if content:
            parts.append(str(content))
    return " ".join(parts[-12:]).lower()


def _nvidia_request_profile(messages):
    text = _nvidia_message_text(messages)
    # This must win over the generic campaign profile.  A native instant form
    # is a campaign-related task, but its initial creation has a much smaller
    # and safer contract than staging the eventual campaign.
    if (
        "create_lead_form" in text
        or "missing_lead_form_detail" in text
        or any(marker in text for marker in ADMIRA_NVIDIA_LEAD_FORM_TERMS)
    ):
        return "lead_form"
    # Organic requests commonly mention both image and video. Those words
    # overlap with a campaign brief, so recognize the explicit destination
    # before campaign/media routing.
    if (
        "orgánico" in text
        or "organico" in text
        or "organic" in text
    ) and any(marker in text for marker in ("facebook", "publicación", "publicacion", "publication", "post", "borrador", "draft", "publish")):
        return "organic"
    campaign_context = any(marker in text for marker in ADMIRA_NVIDIA_CAMPAIGN_TERMS)
    if campaign_context:
        # Destination-specific Meta payloads deserve their own small tool
        # registry even when the buyer also says "create campaign".
        if any(marker in text for marker in ADMIRA_NVIDIA_MESSAGING_CAMPAIGN_TERMS):
            return "messaging_campaign"
        action_requested = any(marker in text for marker in ADMIRA_NVIDIA_CAMPAIGN_ACTION_TERMS)
        # "Create a campaign with approved creatives" belongs to execution;
        # media routing is for an explicit request to produce the media.
        if (
            any(marker in text for marker in ADMIRA_NVIDIA_CAMPAIGN_MEDIA_TERMS)
            and any(marker in text for marker in ADMIRA_NVIDIA_MEDIA_PRODUCTION_TERMS)
        ):
            return "campaign_media"
        if action_requested:
            return "campaign_execution"
        if any(marker in text for marker in ADMIRA_NVIDIA_PROFILE_TERMS["insights"]):
            return "insights"
        if any(marker in text for marker in ADMIRA_NVIDIA_CAMPAIGN_STRATEGY_TERMS):
            return "campaign_strategy"
        # A bare "campaign" generally means the buyer wants the next
        # concrete preparation step, not an open-ended lesson.
        return "campaign_execution"
    scores = {
        profile: sum(1 for term in terms if term in text)
        for profile, terms in ADMIRA_NVIDIA_PROFILE_TERMS.items()
    }
    best = max(scores, key=scores.get) if scores else ""
    return best if scores.get(best, 0) else "core"


def _nvidia_lead_form_retry_instruction(messages):
    """Add a private recovery rule after the backend rejected empty form args.

    A model must either supply all four fields in one call or ask the one
    missing owner question.  Repeating ``create_lead_form({})`` is never a
    useful retry and needlessly consumes a hosted-provider request.
    """
    text = _nvidia_message_text(messages)
    if "missing_lead_form_detail" not in text:
        return ""
    return (
        "[INTERNAL LEAD-FORM RETRY RULE — never quote] The previous native-form "
        "call was rejected because its arguments were incomplete. Do not call "
        "create_lead_form again unless this one call includes non-empty page_id, "
        "name, privacy_policy_url, and questions. Recover exact values from the "
        "conversation or saved context. If any is genuinely absent, ask one concise "
        "combined question for the missing fields; never retry with {}. "
        "[END INTERNAL LEAD-FORM RETRY RULE]"
    )


def _nvidia_append_private_instruction(messages, instruction):
    """Attach a bounded internal instruction to the latest request message."""
    if not instruction or not isinstance(messages, list):
        return messages
    updated = list(messages)
    for index in range(len(updated) - 1, -1, -1):
        item = updated[index]
        if not isinstance(item, dict) or item.get("role") not in {"user", "system"}:
            continue
        clone = dict(item)
        content = clone.get("content")
        if isinstance(content, str):
            clone["content"] = f"{content}\n\n{instruction}"
            updated[index] = clone
            return updated
    updated.append({"role": "system", "content": instruction})
    return updated


def _nvidia_used_tool_names(messages):
    """Keep only tools from the currently active tool loop available.

    Earlier versions scanned the full session and carried every historical
    tool into every later request.  That defeats routing on longer chats.  A
    tool is active only after Hermes has issued it and before the next buyer
    message; once a buyer sends a new message, the new profile is authoritative.
    """
    used = set()
    for message in reversed(messages or []):
        if not isinstance(message, dict):
            continue
        if message.get("role") == "user":
            break
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            function = call.get("function") or {}
            name = function.get("name") if isinstance(function, dict) else ""
            normalized = _nvidia_normalize_tool_name(name)
            if normalized:
                used.add(normalized)
        name = message.get("name") or message.get("tool_name")
        normalized = _nvidia_normalize_tool_name(name)
        if normalized:
            used.add(normalized)
    return used


def _nvidia_estimated_input_tokens(messages, tools):
    try:
        serialized = json.dumps(
            {"messages": messages or [], "tools": tools or []},
            ensure_ascii=False,
            default=str,
        )
    except (TypeError, ValueError):
        serialized = str({"messages": messages or [], "tools": tools or []})
    return max(0, len(serialized) // 4)


def _nvidia_trim_value(value, max_string_chars):
    """Trim only oversized serialized strings while preserving JSON shape."""
    if isinstance(value, str):
        if len(value) <= max_string_chars:
            return value
        return value[:max_string_chars] + "…[NVIDIA context trimmed]"
    if isinstance(value, list):
        return [_nvidia_trim_value(item, max_string_chars) for item in value]
    if isinstance(value, dict):
        return {key: _nvidia_trim_value(item, max_string_chars) for key, item in value.items()}
    return value


def _nvidia_compact_request_payload(messages, tools):
    """Last-resort bounded window after normal Hermes compression.

    This is intentionally conservative and only runs when the *complete*
    request (including tool schemas) exceeds the operational input budget.
    The first system message and the latest ten turns are retained; normal
    Hermes compression remains responsible for producing the durable summary.
    """
    if not isinstance(messages, list):
        return messages, tools
    compacted_messages = list(messages)
    compacted_tools = list(tools or []) if isinstance(tools, list) else tools
    if _nvidia_estimated_input_tokens(compacted_messages, compacted_tools) <= ADMIRA_NVIDIA_INPUT_BUDGET_TOKENS:
        return compacted_messages, compacted_tools

    head = (
        compacted_messages[:1]
        if isinstance(compacted_messages[0], dict) and compacted_messages[0].get("role") == "system"
        else []
    )
    tail = compacted_messages[-10:]
    compacted_messages = head + [item for item in tail if item not in head]
    # A single tool result can be very large. Drop older turns until the
    # complete request, not just the chat history, fits the NIM budget.
    while (
        len(compacted_messages) > 2
        and _nvidia_estimated_input_tokens(compacted_messages, compacted_tools) > ADMIRA_NVIDIA_INPUT_BUDGET_TOKENS
    ):
        first_tail_index = 1 if head else 0
        compacted_messages.pop(first_tail_index)

    if _nvidia_estimated_input_tokens(compacted_messages, compacted_tools) > ADMIRA_NVIDIA_INPUT_BUDGET_TOKENS:
        # Preserve the protocol shape and the newest turn, but bound giant
        # tool arguments/results and verbose system text. This is only a last
        # resort after Hermes' normal summarizer and the sliding window.
        for max_chars in (16384, 8192, 4096, 2048, 1024, 512, 256):
            candidate_messages = _nvidia_trim_value(compacted_messages, max_chars)
            candidate_tools = _nvidia_trim_value(compacted_tools, max_chars)
            if _nvidia_estimated_input_tokens(candidate_messages, candidate_tools) <= ADMIRA_NVIDIA_INPUT_BUDGET_TOKENS:
                return candidate_messages, candidate_tools
        # The final fallback is intentionally tiny and deterministic. It
        # avoids sending an oversized request even if an SDK injects a very
        # large opaque field that cannot be trimmed structurally.
        latest = compacted_messages[-1:] or [{"role": "user", "content": "Continúa con el último paso."}]
        return head[-1:] + _nvidia_trim_value(latest, 128), []

    return compacted_messages, compacted_tools


def _nvidia_compact_request_messages(messages, tools):
    """Compatibility wrapper retained for callers/tests that need messages."""
    compacted, _ = _nvidia_compact_request_payload(messages, tools)
    return compacted


def _nvidia_prepare_request(api_kwargs):
    """Bound an outgoing NIM request without changing non-NVIDIA providers.

    Hermes' compression protects conversation messages, while this preflight
    protects the complete provider payload: MCP schemas and output budget are
    part of the request too. The function returns a shallow copy so callers do
    not mutate Hermes' session history or retry payload.
    """
    if not isinstance(api_kwargs, dict):
        return api_kwargs
    request = dict(api_kwargs)
    messages = request.get("messages") if isinstance(request.get("messages"), list) else []
    tools = request.get("tools") if isinstance(request.get("tools"), list) else []

    before_tools = len(tools)
    profile = _nvidia_request_profile(messages)
    # The specialised campaign workflows are self-contained.  Do not append
    # the generic core registry or a narrow form/strategy/execution request
    # grows back into the previous all-in-one campaign payload.
    direct_profiles = {
        "lead_form", "campaign_strategy", "campaign_execution",
        "messaging_campaign", "campaign_media",
    }
    if profile in direct_profiles:
        allowed = set(ADMIRA_NVIDIA_TOOL_PROFILES[profile])
    else:
        allowed = set(ADMIRA_NVIDIA_TOOL_PROFILES.get("core", set()))
        allowed.update(ADMIRA_NVIDIA_TOOL_PROFILES.get(profile, set()))
    allowed.update(_nvidia_used_tool_names(messages))

    filtered = []
    for tool in tools:
        name = _nvidia_tool_name(tool)
        normalized = _nvidia_normalize_tool_name(name)
        # Hermes-native tools are intentionally preserved. Only the large
        # Admira MCP registry is routed by profile.
        if normalized in {"", "get_real_meta_context"} or not (
            name.lower().startswith(("mcp_admira_", "admira_"))
        ):
            filtered.append(tool)
        elif normalized in allowed:
            filtered.append(tool)
    if filtered and len(filtered) < before_tools:
        request["tools"] = filtered

    private_instruction = _nvidia_lead_form_retry_instruction(messages) if profile == "lead_form" else ""
    prepared_messages = _nvidia_append_private_instruction(messages, private_instruction)
    request["messages"], request["tools"] = _nvidia_compact_request_payload(
        prepared_messages,
        request.get("tools") or [],
    )

    current_max = request.get("max_tokens")
    try:
        current_max = int(current_max)
    except (TypeError, ValueError):
        current_max = ADMIRA_NVIDIA_DEFAULT_MAX_OUTPUT_TOKENS
    output_cap = (
        ADMIRA_NVIDIA_CREATIVE_MAX_OUTPUT_TOKENS
        if profile in {"creative", "organic", "campaign_media"}
        else ADMIRA_NVIDIA_DEFAULT_MAX_OUTPUT_TOKENS
    )
    request["max_tokens"] = max(256, min(current_max, output_cap))

    _record_nvidia_request_diagnostic(
        request,
        profile=profile,
        before_tools=before_tools,
        after_tools=len(request.get("tools") or []),
        before_max_tokens=current_max,
    )
    return request


def _record_nvidia_request_diagnostic(request, *, profile, before_tools, after_tools, before_max_tokens):
    """Write bounded request metadata only when diagnostics are configured."""
    path_value = str(os.environ.get("ADMIRA_NVIDIA_REQUEST_DIAGNOSTICS_FILE") or "").strip()
    if not path_value:
        return
    try:
        messages = request.get("messages") or []
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": str(request.get("model") or ""),
            "profile": profile,
            "tools_before": int(before_tools),
            "tools_after": int(after_tools),
            "messages": len(messages),
            "estimated_input_tokens": len(json.dumps(
                {"messages": messages, "tools": request.get("tools") or []},
                ensure_ascii=False,
                default=str,
            )) // 4,
            "input_budget_tokens": ADMIRA_NVIDIA_INPUT_BUDGET_TOKENS,
            "max_tokens_before": int(before_max_tokens),
            "max_tokens_after": int(request.get("max_tokens") or 0),
        }
        path = Path(path_value).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except (OSError, TypeError, ValueError):
        pass


def _patch_nvidia_request_gate():
    """Throttle NIM calls across all Hermes sessions in this installation."""
    try:
        import agent.chat_completion_helpers as helpers
    except Exception:
        return False

    def _is_nvidia_agent(agent):
        provider = str(getattr(agent, "provider", "") or "").strip().lower().replace("_", "-")
        # Hermes keeps both the normalized and original URL on the agent.  Do
        # not require the API key in the environment: credentials can be
        # loaded from Hermes' provider config/.env before the request starts.
        base_url = str(
            getattr(agent, "_base_url_lower", "")
            or getattr(agent, "base_url", "")
            or ""
        ).strip().lower()
        return provider == "admira-nvidia" or "integrate.api.nvidia.com" in base_url

    def _reserve(agent):
        if not _is_nvidia_agent(agent):
            return
        try:
            from nvidia_request_gate import acquire_request

            acquire_request(provider="admira-nvidia")
        except Exception:
            # The gate is defensive: a local state-file problem must not
            # turn a healthy provider into a buyer-facing failure.
            pass

    original = getattr(helpers, "interruptible_api_call", None)
    original_streaming = getattr(helpers, "interruptible_streaming_api_call", None)
    patched_any = False

    if callable(original) and not getattr(original, "_admira_nvidia_gate_patch", False):
        def patched_interruptible_api_call(agent, api_kwargs):
            _reserve(agent)
            if _is_nvidia_agent(agent):
                api_kwargs = _nvidia_prepare_request(api_kwargs)
            return original(agent, api_kwargs)

        patched_interruptible_api_call._admira_nvidia_gate_patch = True
        patched_interruptible_api_call._admira_original_interruptible_api_call = original
        helpers.interruptible_api_call = patched_interruptible_api_call
        patched_any = True
    elif getattr(original, "_admira_nvidia_gate_patch", False):
        patched_any = True

    # Hermes sends normal chat-completions through the streaming helper.  The
    # previous patch only guarded the non-streaming fallback, so the primary
    # request could still burst past NIM's hosted endpoint quota.
    if callable(original_streaming) and not getattr(original_streaming, "_admira_nvidia_gate_patch", False):
        def patched_interruptible_streaming_api_call(agent, api_kwargs, *, on_first_delta=None):
            _reserve(agent)
            if _is_nvidia_agent(agent):
                api_kwargs = _nvidia_prepare_request(api_kwargs)
            return original_streaming(agent, api_kwargs, on_first_delta=on_first_delta)

        patched_interruptible_streaming_api_call._admira_nvidia_gate_patch = True
        patched_interruptible_streaming_api_call._admira_original_interruptible_streaming_api_call = original_streaming
        helpers.interruptible_streaming_api_call = patched_interruptible_streaming_api_call
        patched_any = True
    elif getattr(original_streaming, "_admira_nvidia_gate_patch", False):
        patched_any = True

    return patched_any


def _nvidia_runtime_identity(runtime):
    """Return whether a Hermes runtime descriptor points at NVIDIA NIM."""
    if not isinstance(runtime, dict):
        return False
    provider = str(runtime.get("provider") or runtime.get("provider_name") or "").strip().lower().replace("_", "-")
    endpoint = " ".join(
        str(runtime.get(key) or "")
        for key in ("base_url", "api_base", "endpoint")
    ).lower()
    return provider in {"admira-nvidia", "custom:admira-nvidia", "nvidia", "nvidia-nim"} or "integrate.api.nvidia.com" in endpoint


def _patch_nvidia_auxiliary_title_generation():
    """Do not spend a hosted NIM call naming an internal session.

    Hermes starts this best-effort task in a background thread after a first
    exchange.  On a free hosted endpoint it can race the buyer's next turn,
    producing an avoidable 429.  Session titles are cosmetic and must never
    compete with the actual manager response.  Other brain providers keep
    Hermes' native title behaviour.
    """
    title_generator = sys.modules.get("agent.title_generator")
    if title_generator is None:
        try:
            import agent.title_generator as title_generator
        except ImportError:
            return False
    original = getattr(title_generator, "maybe_auto_title", None)
    if not callable(original):
        return False
    if getattr(original, "_admira_nvidia_title_patch", False):
        return True

    def patched_maybe_auto_title(*args, **kwargs):
        runtime = kwargs.get("main_runtime")
        if _nvidia_runtime_identity(runtime):
            return None
        return original(*args, **kwargs)

    patched_maybe_auto_title._admira_nvidia_title_patch = True
    patched_maybe_auto_title._admira_original_maybe_auto_title = original
    title_generator.maybe_auto_title = patched_maybe_auto_title
    return True


def _path_within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _admira_generated_media_roots():
    roots = []
    product_root = str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "").strip()
    if product_root:
        roots.append(Path(product_root).expanduser() / "output")
    roots.append(Path("/app/output"))
    extra_roots = str(os.environ.get("HERMES_MEDIA_ALLOW_DIRS") or "")
    for chunk in extra_roots.split(os.pathsep):
        raw = chunk.strip()
        if raw:
            roots.append(Path(raw).expanduser())
    normalized = []
    seen = set()
    for root in roots:
        try:
            resolved = root.resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            continue
        key = str(resolved)
        if key not in seen:
            seen.add(key)
            normalized.append(resolved)
    return normalized


def _safe_generated_media_path(raw_path):
    value = str(raw_path or "").strip()
    if value.startswith("MEDIA:"):
        value = value.split("MEDIA:", 1)[1].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "`\"'":
        value = value[1:-1].strip()
    value = value.lstrip("`\"'").rstrip("`\"',.;:)}]")
    if not value:
        return ""
    candidate = Path(os.path.expanduser(value))
    if not candidate.is_absolute():
        return ""
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return ""
    if not resolved.is_file() or not re.search(rf"\.(?:{ADMIRA_MEDIA_EXTENSIONS})$", resolved.name, re.IGNORECASE):
        return ""
    for root in _admira_generated_media_roots():
        if _path_within(resolved, root):
            return str(resolved)
    return ""


def _collect_generated_media_paths(value, key_hint="", paths=None, depth=0):
    paths = paths if paths is not None else []
    if depth > 12:
        return paths
    if isinstance(value, dict):
        for key, item in value.items():
            _collect_generated_media_paths(item, str(key or ""), paths, depth + 1)
        return paths
    if isinstance(value, (list, tuple, set)):
        for item in value:
            _collect_generated_media_paths(item, key_hint, paths, depth + 1)
        return paths
    if not isinstance(value, str):
        return paths
    text = value.strip()
    if not text:
        return paths
    if key_hint in ADMIRA_GENERATED_MEDIA_KEYS:
        safe_path = _safe_generated_media_path(text)
        if safe_path:
            paths.append(safe_path)
    for pattern in (ADMIRA_MEDIA_TAG_RE, ADMIRA_OUTPUT_IMAGE_RE):
        for match in pattern.finditer(text):
            safe_path = _safe_generated_media_path(match.group("path"))
            if safe_path:
                paths.append(safe_path)
    return paths


def _latest_assistant_message(messages):
    """Return only the newest assistant/tool message to avoid replaying old media."""
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        if role in {"assistant", "tool"}:
            return message
    return None


def _current_generated_media_sources(response):
    """Collect media-bearing fields from the current turn, not the whole session history."""
    sources = []
    final_response = str(response.get("final_response") or "")
    if final_response:
        sources.append(final_response)
    for key in ADMIRA_GENERATED_MEDIA_KEYS:
        if key in response:
            sources.append({key: response.get(key)})
    for key in (
        "tool_result",
        "tool_results",
        "tool_response",
        "tool_responses",
        "result",
        "results",
        "action_result",
        "action_results",
        "mcp_result",
        "mcp_results",
    ):
        if key in response:
            sources.append(response.get(key))
    latest_message = _latest_assistant_message(response.get("messages"))
    if latest_message:
        sources.append(latest_message)
    return sources


def _current_turn_messages(messages):
    if not isinstance(messages, list):
        return []
    start = 0
    for index, message in enumerate(messages):
        if isinstance(message, dict) and str(message.get("role") or "").strip().lower() == "user":
            start = index + 1
    return messages[start:]


def _has_confirmed_durable_save(response):
    if not isinstance(response, dict):
        return False
    sources = []
    for key in ("tool_result", "tool_results", "tool_response", "tool_responses", "result", "results", "action_result", "action_results", "mcp_result", "mcp_results"):
        if key in response:
            sources.append(response.get(key))
    sources.extend(_current_turn_messages(response.get("messages")))
    try:
        text = json.dumps(sources, ensure_ascii=False, default=str).lower()
    except (TypeError, ValueError):
        text = str(sources).lower()
    # Tool content may itself be a JSON string inside the outer response JSON.
    text = text.replace('\\"', '"')
    has_save_tool = any(marker in text for marker in ADMIRA_DURABLE_TOOL_MARKERS)
    has_success = any(
        marker in text
        for marker in (
            '"saved": true',
            '"saved":true',
            '"ok": true',
            '"ok":true',
            '"executed": true',
            '"executed":true',
            '"status": "completed"',
            '"status":"completed"',
        )
    )
    return has_save_tool and has_success


def _guard_unconfirmed_persistence_claim(response):
    """Prevent a model from promising memory when no save tool succeeded."""
    if not isinstance(response, dict):
        return response
    final_response = str(response.get("final_response") or "")
    if not final_response or not ADMIRA_PERSISTENCE_CLAIM_RE.search(final_response):
        return response
    if _has_confirmed_durable_save(response):
        return response
    parts = re.split(r"(?<=[.!?])\s+|\n+", final_response)
    cleaned = " ".join(part.strip() for part in parts if part.strip() and not ADMIRA_PERSISTENCE_CLAIM_RE.search(part))
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip(" \n-—:;,.\t")
    if not cleaned:
        language = str(os.environ.get("ADMIRA_GATEWAY_LANGUAGE") or "es").lower()
        cleaned = "Understood." if language.startswith("en") else "Entendido."
    # Persistence misses are diagnostics, not buyer-facing content. A later
    # turn can retry through the official store without exposing runtime
    # mechanics or making the buyer think their business data was lost.
    response["final_response"] = cleaned
    return response


def _append_generated_media_attachments(response):
    """Append native MEDIA directives for generated images in any result shape."""
    if not isinstance(response, dict):
        return response
    final_response = str(response.get("final_response") or "")
    paths = []
    for source in _current_generated_media_sources(response):
        _collect_generated_media_paths(source, paths=paths)
    if not paths:
        return response
    existing_media_paths = {
        safe_path
        for match in ADMIRA_MEDIA_TAG_RE.finditer(final_response)
        for safe_path in [_safe_generated_media_path(match.group("path"))]
        if safe_path
    }
    seen = set()
    tags = []
    for path in paths:
        tag = f"MEDIA:{path}"
        if path in seen or path in existing_media_paths or tag in final_response:
            continue
        seen.add(path)
        tags.append(tag)
    if not tags:
        return response
    response["final_response"] = (final_response.rstrip() + "\n" + "\n".join(tags)).strip()
    return response


def _event_video_paths(event):
    video_paths = []
    media_urls = list(getattr(event, "media_urls", None) or [])
    media_types = list(getattr(event, "media_types", None) or [])
    for index, raw_path in enumerate(media_urls):
        media_type = str(media_types[index] if index < len(media_types) else "").lower()
        try:
            path = Path(str(raw_path or "")).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            continue
        if media_type.startswith("video/") or path.suffix.lower() in ADMIRA_VIDEO_EXTENSIONS:
            video_paths.append(str(path))
    return video_paths


def _event_image_paths(event):
    image_paths = []
    media_urls = list(getattr(event, "media_urls", None) or [])
    media_types = list(getattr(event, "media_types", None) or [])
    for index, raw_path in enumerate(media_urls):
        media_type = str(media_types[index] if index < len(media_types) else "").lower()
        try:
            path = Path(str(raw_path or "")).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            continue
        if media_type.startswith("image/") or path.suffix.lower() in ADMIRA_IMAGE_EXTENSIONS:
            image_paths.append(str(path))
    return image_paths[:24]


ADMIRA_PRODUCT_DOCUMENT_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".csv", ".tsv", ".json"}


def _event_product_document_paths(event):
    document_paths = []
    media_urls = list(getattr(event, "media_urls", None) or [])
    media_types = list(getattr(event, "media_types", None) or [])
    for index, raw_path in enumerate(media_urls):
        media_type = str(media_types[index] if index < len(media_types) else "").lower()
        try:
            path = Path(str(raw_path or "")).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            continue
        if path.suffix.lower() in ADMIRA_PRODUCT_DOCUMENT_EXTENSIONS or media_type in {
            "application/pdf",
            "application/json",
            "text/csv",
            "text/tab-separated-values",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }:
            document_paths.append(str(path))
    return document_paths[:10]


def _append_product_document_contract(event):
    document_paths = _event_product_document_paths(event)
    if not document_paths:
        return event
    internal_paths = "\n".join(f"- {path}" for path in document_paths)
    note = (
        "[ADMIRA PRODUCT DOCUMENT — internal, never quote paths to the buyer]\n"
        "The buyer attached one or more PDF/Excel/CSV/JSON documents. If they contain products, services, offers, prices, "
        "catalog details, bundles, or inventory, call mcp_admira_import_product_catalog in this turn with these file_paths. "
        "Do not summarize the file and leave it ephemeral. Import every identifiable product as its own child guide, preserve "
        "unmapped details, and keep combinations/bundles as separate offers linked through components. If the tool returns "
        "needs_agent_structuring=true, use the extracted text and call the importer again with a structured products array before "
        "claiming the catalog is ready. For later recall, call mcp_admira_search_product_catalog rather than relying on chat memory.\n"
        f"Document paths:\n{internal_paths}\n"
        "[END ADMIRA PRODUCT DOCUMENT]"
    )
    original_text = str(getattr(event, "text", "") or "")
    event.text = (note + ("\n\n" + original_text if original_text else "")).strip()
    return event


def _persist_inbound_image_batch(image_paths):
    """Persist buyer images before inference so a reset cannot lose the batch."""
    root = Path(str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "").strip()).expanduser()
    bridge = root / "src" / "admira_tool_bridge.py"
    if not image_paths or not root.is_dir() or not bridge.is_file():
        return {"ok": False, "reason": "product_bridge_unavailable"}
    payload = {
        "category": "other",
        "purpose": "Tanda de imágenes enviada por el comprador; pendiente de clasificación visual y propósito confirmado.",
        "image_paths": list(image_paths)[:24],
        "classification_status": "pending_agent_review",
        "preservation_mode": "pending_classification",
        "approved_for_daily_content": False,
        "approved_for_ads": False,
        "source": "telegram_upload_batch",
    }
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(bridge),
                "call",
                "admira_save_content_asset",
                "--json",
                json.dumps(payload, ensure_ascii=False),
                "--channel",
                "telegram",
                "--language",
                str(os.environ.get("ADMIRA_GATEWAY_LANGUAGE") or "es"),
            ],
            cwd=str(root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "reason": "asset_ingest_failed", "message": str(exc)[:300]}
    result = None
    for line in reversed((completed.stdout or "").splitlines()):
        if not line.strip().startswith("{"):
            continue
        try:
            result = json.loads(line.strip())
        except json.JSONDecodeError:
            continue
        break
    if not isinstance(result, dict):
        return {"ok": False, "reason": "asset_ingest_invalid_response"}
    nested = result.get("result") if isinstance(result.get("result"), dict) else {}
    tool_result = nested.get("result") if isinstance(nested.get("result"), dict) else nested
    assets = tool_result.get("assets") if isinstance(tool_result, dict) else []
    stored_paths = []
    asset_ids = []
    for asset in assets or []:
        if not isinstance(asset, dict):
            continue
        asset_ids.append(str(asset.get("id") or ""))
        stored_paths.extend(str(path) for path in (asset.get("file_paths") or []) if str(path).strip())
    complete = len(stored_paths) == len(image_paths)
    return {
        "ok": bool(result.get("ok") and complete),
        "saved_asset_count": len(asset_ids),
        "asset_ids": asset_ids,
        "stored_paths": stored_paths,
        "reason": (result.get("reason") or "") if complete else "asset_batch_incomplete",
    }


def _archive_inbound_image_batch_for_agent(event):
    image_paths = _event_image_paths(event)
    if not image_paths:
        return event
    result = _persist_inbound_image_batch(image_paths)
    if not result.get("ok"):
        return event
    stored_paths = result.get("stored_paths") or []
    internal_paths = "\n".join(f"- {path}" for path in stored_paths)
    note = (
        "[ADMIRA INBOUND ASSET BATCH — internal, never quote paths to the buyer]\n"
        f"Admira durably archived {int(result.get('saved_asset_count') or len(stored_paths))} buyer image(s) before this reply.\n"
        "Analyze every attached image with vision now. Infer its purpose from the buyer's caption when clear; otherwise ask one short grouped question. "
        "Then call mcp_admira_save_content_asset with the stored path(s), grouped by the correct category. "
        "Use preservation_mode=pixel_locked for buyer-owned real photos or the official logo, style_only only for inspiration/reference images, "
        "and prohibited for do-not-use assets. A pixel_locked photo may be cropped/positioned/framed or receive overlays, but any used photo content must remain pixel by pixel accurate in Image 2.\n"
        f"Stored paths for the classification tool call:\n{internal_paths}\n"
        "[END ADMIRA INBOUND ASSET BATCH]"
    )
    original_text = str(getattr(event, "text", "") or "")
    event.text = (note + ("\n\n" + original_text if original_text else "")).strip()
    return event


def _append_video_frame_inputs_to_event(event):
    """Convert cached inbound videos into frame image inputs before Hermes processes them."""
    video_paths = _event_video_paths(event)
    if not video_paths:
        return event
    try:
        from public_asset_fetcher import extract_video_preview_frames
    except Exception:
        return event
    media_urls = list(getattr(event, "media_urls", None) or [])
    media_types = list(getattr(event, "media_types", None) or [])
    existing = {str(Path(str(path)).expanduser()) for path in media_urls}
    notes = []
    for video_path in video_paths[:3]:
        frame_dir = Path(video_path).parent / f"{Path(video_path).stem}_admira_frames"
        frame_result = extract_video_preview_frames(video_path, output_dir=frame_dir)
        frames = frame_result.get("frames") or []
        if frames:
            added = 0
            for frame_path in frames:
                normalized = str(Path(frame_path).expanduser())
                if normalized in existing:
                    continue
                media_urls.append(normalized)
                media_types.append("image/jpeg")
                existing.add(normalized)
                added += 1
            duration = frame_result.get("duration_seconds") or 0
            duration_note = f" Duration: about {duration:g} seconds." if duration else ""
            notes.append(
                f"[Admira prepared {added or len(frames)} representative frames from the user's uploaded video for visual review.{duration_note} "
                "Use those attached frames to understand the video; the raw MP4 remains the original video creative asset.]"
            )
        else:
            reason = frame_result.get("reason") or "frame_extraction_failed"
            notes.append(f"[The user uploaded a video, but Admira could not extract preview frames automatically: {reason}.]")
    if media_urls != list(getattr(event, "media_urls", None) or []):
        event.media_urls = media_urls
        event.media_types = media_types
    if notes:
        original_text = str(getattr(event, "text", "") or "")
        event.text = ("\n".join(notes) + ("\n\n" + original_text if original_text else "")).strip()
    return event


def _admira_minimax_model():
    return os.environ.get("ADMIRA_MINIMAX_MODEL", ADMIRA_MINIMAX_MODEL).strip() or ADMIRA_MINIMAX_MODEL


def _admira_minimax_base_url():
    return (
        os.environ.get("ADMIRA_MINIMAX_BASE_URL")
        or os.environ.get("MINIMAX_BASE_URL")
        or ADMIRA_MINIMAX_DEFAULT_BASE_URL
    ).strip().rstrip("/") or ADMIRA_MINIMAX_DEFAULT_BASE_URL


def _admira_minimax_provider():
    return os.environ.get("ADMIRA_MINIMAX_PROVIDER", ADMIRA_MINIMAX_PROVIDER).strip() or ADMIRA_MINIMAX_PROVIDER


def _is_admira_minimax_value(value):
    normalized = str(value or "").strip().lower().replace("_", "-")
    compact = normalized.replace(" ", "").replace("-", "")
    model = _admira_minimax_model().lower().replace("_", "-")
    model_compact = model.replace(" ", "").replace("-", "")
    return normalized in ADMIRA_MINIMAX_ALIASES or compact in {"minimax", "minimaxm3"} or compact == model_compact


def _is_admira_minimax_provider(value):
    normalized = str(value or "").strip().lower()
    return normalized in {
        "minimax",
        "custom:admira-minimax",
        "admira-minimax",
        _admira_minimax_provider().lower(),
    }


def _admira_minimax_provider_entry():
    model = _admira_minimax_model()
    return {
        "name": ADMIRA_MINIMAX_PROVIDER_NAME,
        "base_url": _admira_minimax_base_url(),
        "key_env": ADMIRA_MINIMAX_KEY_ENV,
        "api_mode": "chat_completions",
        "model": model,
        "models": {model: {}},
    }


def _ensure_admira_minimax_user_provider(user_providers):
    providers = dict(user_providers or {}) if isinstance(user_providers, dict) else {}
    provider_key = _admira_minimax_provider()
    existing = providers.get(provider_key)
    wanted = _admira_minimax_provider_entry()
    if isinstance(existing, dict):
        merged = {**wanted, **existing}
        merged.setdefault("key_env", ADMIRA_MINIMAX_KEY_ENV)
        merged.setdefault("api_mode", "chat_completions")
        merged.setdefault("model", wanted["model"])
        models = merged.get("models")
        if not isinstance(models, dict):
            merged["models"] = {wanted["model"]: {}}
        elif wanted["model"] not in models:
            models[wanted["model"]] = {}
        providers[provider_key] = merged
    else:
        providers[provider_key] = wanted
    return providers


def _patch_minimax_model_switch():
    try:
        import hermes_cli.model_switch as model_switch
    except Exception:
        return False
    if getattr(model_switch, "_admira_minimax_official_patch", False):
        return True

    direct_alias = getattr(model_switch, "DirectAlias", None)
    aliases = getattr(model_switch, "DIRECT_ALIASES", None)
    if isinstance(aliases, dict) and direct_alias is not None:
        for alias in ADMIRA_MINIMAX_ALIASES:
            aliases.setdefault(
                alias,
                direct_alias(
                    model=_admira_minimax_model(),
                    provider=_admira_minimax_provider(),
                    base_url=_admira_minimax_base_url(),
                ),
            )

    original_resolve_alias = getattr(model_switch, "resolve_alias", None)
    if callable(original_resolve_alias):
        def patched_resolve_alias(raw_input, current_provider=""):
            if _is_admira_minimax_value(raw_input):
                return (_admira_minimax_provider(), _admira_minimax_model(), str(raw_input or "").strip().lower())
            return original_resolve_alias(raw_input, current_provider)

        model_switch._admira_original_resolve_alias = original_resolve_alias
        model_switch.resolve_alias = patched_resolve_alias

    original_switch_model = getattr(model_switch, "switch_model", None)
    if callable(original_switch_model):
        def patched_switch_model(
            raw_input,
            current_provider,
            current_model,
            current_base_url="",
            current_api_key="",
            is_global=False,
            explicit_provider="",
            user_providers=None,
            custom_providers=None,
        ):
            requested_minimax = _is_admira_minimax_value(raw_input)
            native_minimax_provider = _is_admira_minimax_provider(explicit_provider)
            if requested_minimax or native_minimax_provider:
                raw_input = _admira_minimax_model()
                explicit_provider = _admira_minimax_provider()
                user_providers = _ensure_admira_minimax_user_provider(user_providers)
            result = original_switch_model(
                raw_input=raw_input,
                current_provider=current_provider,
                current_model=current_model,
                current_base_url=current_base_url,
                current_api_key=current_api_key,
                is_global=is_global,
                explicit_provider=explicit_provider,
                user_providers=user_providers,
                custom_providers=custom_providers,
            )
            if _model_switch_succeeded(result):
                result_provider = result.get("provider") if isinstance(result, dict) else ""
                result_model = result.get("model") if isinstance(result, dict) else ""
                result_base_url = result.get("base_url") if isinstance(result, dict) else ""
                selected_provider = result_provider or explicit_provider or current_provider
                selected_model = result_model or raw_input or current_model
                selected_base_url = result_base_url or (
                    _admira_minimax_base_url() if _is_admira_minimax_provider(selected_provider) else current_base_url
                )
                _write_runtime_model_state(selected_provider, selected_model, selected_base_url)
            return result

        model_switch._admira_original_switch_model = original_switch_model
        model_switch.switch_model = patched_switch_model

    original_list_authenticated = getattr(model_switch, "list_authenticated_providers", None)
    if callable(original_list_authenticated):
        def patched_list_authenticated_providers(*args, **kwargs):
            # Opening /model is also an explicit recovery action. Clear only
            # Hermes' local cooldown flags so a healthy newly-connected Codex
            # account remains selectable even after another account hit 429.
            _reset_openai_codex_pool_statuses()
            rows = list(original_list_authenticated(*args, **kwargs) or [])
            # Hide Hermes' native MiniMax row in Admira installs. MiniMax M3 is
            # intentionally exposed through the official OpenAI-compatible
            # custom provider, not Hermes' native provider transport.
            if os.environ.get(ADMIRA_MINIMAX_KEY_ENV):
                rows = [row for row in rows if str((row or {}).get("slug") or "").strip().lower() != "minimax"]
            for row in rows:
                slug = str((row or {}).get("slug") or "").strip().lower()
                if slug == "admira-minimax":
                    row["name"] = "MiniMax M3 oficial"
            return rows

        model_switch._admira_original_list_authenticated_providers = original_list_authenticated
        model_switch.list_authenticated_providers = patched_list_authenticated_providers

    original_list_picker = getattr(model_switch, "list_picker_providers", None)
    if callable(original_list_picker):
        def patched_list_picker_providers(*args, **kwargs):
            _reset_openai_codex_pool_statuses()
            rows = list(original_list_picker(*args, **kwargs) or [])
            if os.environ.get(ADMIRA_MINIMAX_KEY_ENV):
                rows = [row for row in rows if str((row or {}).get("slug") or "").strip().lower() != "minimax"]
            for row in rows:
                slug = str((row or {}).get("slug") or "").strip().lower()
                if slug == "admira-minimax":
                    row["name"] = "MiniMax M3 oficial"
            return rows

        model_switch._admira_original_list_picker_providers = original_list_picker
        model_switch.list_picker_providers = patched_list_picker_providers

    model_switch._admira_minimax_official_patch = True
    return True


def _patch_minimax_runtime_provider():
    try:
        import hermes_cli.runtime_provider as runtime_provider
    except Exception:
        return False
    if getattr(runtime_provider, "_admira_minimax_official_patch", False):
        return True
    original_get_named = getattr(runtime_provider, "_get_named_custom_provider", None)
    if not callable(original_get_named):
        return False

    def patched_get_named_custom_provider(requested_provider):
        found = original_get_named(requested_provider)
        if found:
            return found
        if _is_admira_minimax_provider(requested_provider):
            entry = _admira_minimax_provider_entry()
            return {
                "name": entry["name"],
                "base_url": entry["base_url"],
                "api_key": os.getenv(ADMIRA_MINIMAX_KEY_ENV, "").strip(),
                "key_env": ADMIRA_MINIMAX_KEY_ENV,
                "model": entry["model"],
                "api_mode": entry["api_mode"],
            }
        return None

    runtime_provider._admira_original_get_named_custom_provider = original_get_named
    runtime_provider._get_named_custom_provider = patched_get_named_custom_provider
    runtime_provider._admira_minimax_official_patch = True
    return True


def _patch_gateway_rate_limit_reply():
    try:
        import gateway.run as gateway_run
    except Exception:
        return False
    original = getattr(gateway_run, "_gateway_provider_error_reply", None)
    if not callable(original):
        return False
    if getattr(gateway_run, "_admira_rate_limit_reply_patch", False):
        return True

    def patched_gateway_provider_error_reply(text):
        return provider_error_reply(text, os.environ.get("ADMIRA_GATEWAY_LANGUAGE", "es"), original)

    gateway_run._admira_original_gateway_provider_error_reply = original
    gateway_run._gateway_provider_error_reply = patched_gateway_provider_error_reply
    gateway_run._admira_rate_limit_reply_patch = True
    return True


def _patch_gateway_generated_media_delivery():
    try:
        import gateway.run as gateway_run
    except Exception:
        return False
    runner = getattr(gateway_run, "GatewayRunner", None)
    original = getattr(runner, "_run_agent", None) if runner is not None else None
    if not callable(original):
        return False
    if getattr(runner, "_admira_generated_media_delivery_patch", False):
        return True

    async def patched_run_agent(self, *args, **kwargs):
        message = kwargs.get("message")
        if message is None and args:
            message = args[0]
        persisted = kwargs.get("persist_user_message")
        clean_persisted = _strip_admira_runtime_injections(
            persisted if persisted is not None else message
        )
        if clean_persisted:
            kwargs["persist_user_message"] = clean_persisted
        result = await original(self, *args, **kwargs)
        try:
            result = _guard_unconfirmed_persistence_claim(result)
        except Exception:
            pass
        try:
            result = _append_generated_media_attachments(result)
        except Exception:
            pass
        try:
            result = _normalize_gateway_outbound_response(result)
        except Exception:
            pass
        try:
            if isinstance(result, dict):
                _append_gateway_turn("agent", result.get("final_response") or result.get("response") or result.get("message") or "")
            else:
                _append_gateway_turn("agent", result)
        except Exception:
            pass
        return result

    runner._admira_original_run_agent = original
    runner._run_agent = patched_run_agent
    runner._admira_generated_media_delivery_patch = True
    return True


def _patch_gateway_inbound_video_frames():
    try:
        import gateway.run as gateway_run
    except Exception:
        return False
    runner = getattr(gateway_run, "GatewayRunner", None)
    original = getattr(runner, "_prepare_inbound_message_text", None) if runner is not None else None
    if not callable(original):
        return False
    if getattr(runner, "_admira_inbound_video_frame_patch", False):
        return True

    async def patched_prepare_inbound_message_text(self, *args, **kwargs):
        event = kwargs.get("event")
        if event is None and args:
            # _prepare_inbound_message_text is keyword-only in current Hermes,
            # but this makes the patch tolerant if the signature changes.
            event = args[0]
        if event is not None:
            try:
                _append_product_document_contract(event)
            except Exception:
                pass
            try:
                _archive_inbound_image_batch_for_agent(event)
            except Exception:
                pass
            try:
                _append_video_frame_inputs_to_event(event)
            except Exception:
                pass
        result = await original(self, *args, **kwargs)
        if _message_requires_live_meta_sync(result):
            try:
                import asyncio
                live_context = await asyncio.to_thread(_fetch_live_meta_context_for_turn)
                result = _append_live_meta_context(result, live_context)
            except Exception:
                result = _append_live_meta_context(result, {"ok": False, "reason": "live_meta_sync_failed"})
        try:
            result = _append_turn_execution_contract(result)
        except Exception:
            pass
        try:
            _append_gateway_turn("user", result)
        except Exception:
            pass
        return result

    runner._admira_original_prepare_inbound_message_text = original
    runner._prepare_inbound_message_text = patched_prepare_inbound_message_text
    runner._admira_inbound_video_frame_patch = True
    return True


def _patch_cron_job_creation():
    """Make newly-created reasoning crons explicitly follow the active model."""
    try:
        import cron.jobs as cron_jobs
    except ImportError:
        return False
    original = getattr(cron_jobs, "create_job", None)
    if not callable(original) or getattr(original, "_admira_cron_pin_patch", False):
        return False

    def patched_create_job(*args, **kwargs):
        if not kwargs.get("no_agent") and not kwargs.get("provider") and not kwargs.get("model"):
            active_provider = str(os.environ.get("ADMIRA_CRON_PIN_PROVIDER") or "").strip()
            active_model = str(os.environ.get("ADMIRA_CRON_PIN_MODEL") or "").strip()
            if active_provider and active_model:
                kwargs["provider"] = active_provider
                kwargs["model"] = active_model
            resolver = getattr(cron_jobs, "_compute_provider_model_snapshots", None)
            if not kwargs.get("provider") and not kwargs.get("model") and callable(resolver):
                try:
                    provider, model = resolver(None, None)
                    if provider and model:
                        kwargs["provider"] = provider
                        kwargs["model"] = model
                except Exception:
                    pass
        return original(*args, **kwargs)

    patched_create_job._admira_cron_pin_patch = True
    patched_create_job._admira_original_create_job = original
    cron_jobs.create_job = patched_create_job
    return True


def _patch_cron_job_execution():
    """Make every Admira reasoning cron follow the buyer's current brain.

    Hermes' upstream drift guard is correct for generic autonomous jobs. In
    Admira, changing the primary brain in the dashboard is an explicit buyer
    choice and should migrate all reasoning crons. Script-only/no-agent jobs
    remain untouched.
    """
    try:
        import cron.scheduler as cron_scheduler
    except ImportError:
        return False
    original = getattr(cron_scheduler, "run_job", None)
    if not callable(original) or getattr(original, "_admira_current_brain_patch", False):
        return bool(getattr(original, "_admira_current_brain_patch", False))

    def patched_run_job(job, *args, **kwargs):
        provider = str(os.environ.get("ADMIRA_CRON_PIN_PROVIDER") or "").strip()
        model = str(os.environ.get("ADMIRA_CRON_PIN_MODEL") or "").strip()
        effective_job = job
        if isinstance(job, dict) and not job.get("no_agent") and provider and model:
            effective_job = dict(job)
            effective_job["provider"] = provider
            effective_job["model"] = model
            effective_job.pop("provider_snapshot", None)
            effective_job.pop("model_snapshot", None)
        return original(effective_job, *args, **kwargs)

    patched_run_job._admira_current_brain_patch = True
    patched_run_job._admira_original_run_job = original
    cron_scheduler.run_job = patched_run_job
    return True


def _patch_mcp_call_result_compatibility():
    """Bridge the MCP SDK's Python field rename without editing Hermes.

    Recent MCP SDKs expose ``CallToolResult.is_error`` while Hermes 0.18 still
    reads the old camelCase Python attribute ``isError``.  The wire protocol
    remains camelCase, so give the installed model a read-only compatibility
    alias before Hermes imports/uses it.  This keeps every Admira MCP tool
    usable across the supported SDK range.
    """
    try:
        from mcp.types import CallToolResult
    except ImportError:
        return False
    if hasattr(CallToolResult, "isError"):
        return True

    def _legacy_is_error(self):
        return bool(getattr(self, "is_error", False))

    try:
        setattr(CallToolResult, "isError", property(_legacy_is_error))
    except (AttributeError, TypeError):
        return False
    return hasattr(CallToolResult, "isError")


def _patch_context_truncation_notifications():
    """Keep context-size diagnostics in logs and out of buyer conversations."""
    try:
        import agent.prompt_builder as prompt_builder
    except ImportError:
        return False
    original = getattr(prompt_builder, "drain_truncation_warnings", None)
    if not callable(original) or getattr(original, "_admira_silent_context_patch", False):
        return bool(getattr(original, "_admira_silent_context_patch", False))

    def patched_drain_truncation_warnings():
        original()
        return []

    patched_drain_truncation_warnings._admira_silent_context_patch = True
    patched_drain_truncation_warnings._admira_original_drain = original
    prompt_builder.drain_truncation_warnings = patched_drain_truncation_warnings
    return True


def _telegram_update_install_request_path():
    configured = str(os.environ.get("ADMIRA_TELEGRAM_UPDATE_INSTALL_REQUEST_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser()
    root = str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "").strip()
    return Path(root).expanduser() / "dashboard" / "data" / "telegram_update_install_request.json" if root else None


def _write_telegram_update_install_request(payload):
    """Persist one authorized Telegram update click for the dashboard worker."""
    path = _telegram_update_install_request_path()
    if not path:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        path.chmod(0o600)
        return True
    except OSError:
        return False


def _patch_telegram_update_install_callback():
    """Route Admira's install button through Hermes' *existing* callback loop.

    We intentionally wrap the native Telegram adapter rather than opening a
    second getUpdates consumer.  The gateway acknowledges the tap immediately
    then the dashboard process performs the package update independently.
    """
    adapter_classes = []
    for module_name in (
        # Hermes 0.18+ runtime path.
        "hermes_plugins.telegram_platform.adapter",
        # Older/compatibility runtime path.
        "plugins.platforms.telegram.adapter",
    ):
        try:
            module = importlib.import_module(module_name)
            adapter_class = getattr(module, "TelegramAdapter", None)
        except ImportError:
            continue
        if adapter_class is not None and all(adapter_class is not item for item in adapter_classes):
            adapter_classes.append(adapter_class)

    patched_any = False
    for adapter_class in adapter_classes:
        original = getattr(adapter_class, "_handle_callback_query", None)
        if not callable(original):
            continue
        if getattr(original, "_admira_update_install_patch", False):
            patched_any = True
            continue

        async def patched(self, update, context, _original=original):
            query = getattr(update, "callback_query", None)
            data = str(getattr(query, "data", "") or "")
            if not data.startswith("au:"):
                return await _original(self, update, context)
            version = data.split(":", 1)[1].strip()
            if not version or len(version) > 40 or not re.fullmatch(r"v?\d+(?:\.\d+){1,4}(?:[-+][A-Za-z0-9._-]+)?", version):
                await query.answer(text="Esta actualización ya no es válida.")
                return
            message = getattr(query, "message", None)
            chat = getattr(message, "chat", None)
            chat_id = getattr(message, "chat_id", None)
            chat_type = getattr(chat, "type", None)
            thread_id = getattr(message, "message_thread_id", None)
            user = getattr(query, "from_user", None)
            user_id = str(getattr(user, "id", "") or "")
            user_name = getattr(user, "first_name", None)
            if not self._is_callback_user_authorized(
                user_id,
                chat_id=chat_id,
                chat_type=str(chat_type) if chat_type is not None else None,
                thread_id=str(thread_id) if thread_id is not None else None,
                user_name=user_name,
            ):
                await query.answer(text="No tienes permiso para instalar actualizaciones.")
                return
            path = _telegram_update_install_request_path()
            existing = {}
            if path and path.exists():
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    existing = {}
            if existing.get("status") in {"pending", "installing"}:
                await query.answer(text="La actualización ya se está preparando.")
                return
            accepted = _write_telegram_update_install_request({
                "status": "pending",
                "version": version,
                "chat_id": str(chat_id or ""),
                "user_id": user_id,
                "requested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "notified": False,
            })
            if not accepted:
                await query.answer(text="No pude preparar la actualización. Intenta de nuevo.")
                return
            await query.answer(text="Actualización confirmada. Preparándola ahora…")
            try:
                await query.edit_message_text(
                    text=self.format_message("✅ *Actualización confirmada*\n\nGuardé tu clic y la instalaré ahora con copia de seguridad. El agente se reconectará solo al terminar."),
                    parse_mode="MarkdownV2",
                    reply_markup=None,
                )
            except Exception:
                pass
            return None

        patched._admira_update_install_patch = True
        patched._admira_original_update_callback = original
        adapter_class._handle_callback_query = patched
        patched_any = True
    return patched_any


def apply():
    rate_limit_patched = _patch_gateway_rate_limit_reply()
    credential_pool_patched = _patch_credential_pool_failure_assignment()
    same_nvidia_guard_patched = _patch_same_nvidia_model_failover_guard()
    nvidia_gate_patched = _patch_nvidia_request_gate()
    nvidia_title_patched = _patch_nvidia_auxiliary_title_generation()
    mcp_result_patched = _patch_mcp_call_result_compatibility()
    minimax_patched = _patch_minimax_model_switch()
    runtime_patched = _patch_minimax_runtime_provider()
    media_patched = _patch_gateway_generated_media_delivery()
    video_patched = _patch_gateway_inbound_video_frames()
    cron_create_patched = _patch_cron_job_creation()
    cron_run_patched = _patch_cron_job_execution()
    context_patched = _patch_context_truncation_notifications()
    telegram_update_patched = _patch_telegram_update_install_callback()
    return bool(rate_limit_patched or credential_pool_patched or same_nvidia_guard_patched or nvidia_gate_patched or nvidia_title_patched or mcp_result_patched or minimax_patched or runtime_patched or media_patched or video_patched or cron_create_patched or cron_run_patched or context_patched or telegram_update_patched)
