#!/usr/bin/env python3
"""Independent semantic classifier for possible campaign-success prose.

This module intentionally receives only the raw assistant response.  It does
not receive Hermes history, MCP tools, Meta evidence, or retry state.  The
classifier describes what the prose claims; the campaign guard remains the
authority for whether Meta actually created anything.
"""
import json
import os

from campaign_payload_compiler import (
    GEMINI_COMPILER_BASE_URL,
    _gemini_api_key,
    _gemini_base_url,
    _gemini_compile,
    _terra_compile,
)
from product_config import ROOT_DIR, load_config


CLAIM_INPUT_MAX_CHARS = 12_000
CLAIM_TIMEOUT_SECONDS = 12.0
CLAIM_RESULT_KEY = "confirmacion_creacion_campana"
CLAIM_ENUM = ("si", "no")
CLAIM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        CLAIM_RESULT_KEY: {
            "type": "string",
            "enum": list(CLAIM_ENUM),
        },
    },
    "required": [CLAIM_RESULT_KEY],
}
EDIT_RESULT_KEY = "confirmacion_edicion_campana"
EDIT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        EDIT_RESULT_KEY: {"type": "string", "enum": list(CLAIM_ENUM)},
    },
    "required": [EDIT_RESULT_KEY],
}

_GEMINI_PROVIDERS = {"gemini", "google", "google-ai-studio", "google-ai-studio-api"}
_CODEX_PROVIDERS = {"openai-codex", "openai_codex", "codex"}


def _runtime_model_state():
    """Read the model actually selected in Telegram without conversation data."""
    path = ROOT_DIR / "dashboard" / "data" / "telegram_model_state.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _provider_name(provider, config):
    value = str(provider or "").strip().lower().replace("_", "-")
    if value:
        return value
    if isinstance(config, dict):
        value = str(config.get("active_provider") or config.get("provider") or "").strip().lower().replace("_", "-")
    else:
        value = str(getattr(config, "agent_brain_provider", "") or "").strip().lower().replace("_", "-")
    if value:
        return value
    return str((config.get("agent_chat_provider") if isinstance(config, dict) else getattr(config, "agent_chat_provider", "")) or "").strip().lower().replace("_", "-")


def _active_model(model, config, provider):
    selected = str(model or "").strip()
    if selected:
        return selected
    if isinstance(config, dict):
        selected = str(config.get("active_model") or config.get("model") or "").strip()
        if selected:
            return selected
    if provider in _CODEX_PROVIDERS:
        return str(
            getattr(config, "agent_chat_model", "")
            or getattr(config, "hermes_model", "")
            or os.environ.get("ADMIRA_CRON_PIN_MODEL", "")
            or "gpt-5.6-luna"
        ).strip()
    return str(
        getattr(config, "agent_chat_model", "")
        or os.environ.get("GEMINI_MODEL", "")
        or "gemini-3.5-flash-lite"
    ).strip()


def _classifier_prompt(raw_response):
    # The response is bounded before interpolation. No session material is
    # accepted by this function, and the delimiter prevents response prose
    # from being mistaken for classifier instructions.
    return (
        "Classify only the semantic claim made by the assistant response below. "
        "Return exactly one JSON object matching the supplied schema. Set "
        f"{CLAIM_RESULT_KEY}=\"si\" only when the assistant explicitly communicates "
        "that a Meta advertising campaign was successfully created/configured/launched "
        "inside Meta as an accomplished outcome. Set it to \"no\" for proposals, plans, questions, "
        "future actions, drafts, pending approvals, or statements that creation failed. "
        "Also return \"no\" when the assistant created only an image, design, creative, ad copy, "
        "brief, campaign structure proposal, or other preparation and merely offers to create or "
        "structure the Meta campaign later. Quoted words from another speaker are not the "
        "assistant's own success claim. "
        "Do not infer execution from the word campaign alone. Do not add keys or prose.\n\n"
        "<assistant_response>\n"
        f"{raw_response}\n"
        "</assistant_response>"
    )


def _edit_classifier_prompt(raw_response):
    return (
        "Classify only the semantic claim made by the assistant response below. "
        "Return exactly one JSON object matching the supplied schema. Set "
        f'{EDIT_RESULT_KEY}="si" only when the assistant explicitly communicates '
        "that a change to an existing Meta advertising campaign, ad set, or ad "
        "was successfully applied inside Meta as an accomplished outcome. Set it "
        'to "no" for greetings, questions, proposals, plans, future actions, drafts, '
        "pending approvals, failed changes, campaign creation, creative/image/copy "
        "work, or any response that merely mentions a campaign. Do not infer an "
        "applied edit from the word campaign alone. Do not add keys or prose.\n\n"
        "<assistant_response>\n"
        f"{raw_response}\n"
        "</assistant_response>"
    )


def _safe_result(*, ok, confirmation=None, provider="", model="", reason=""):
    result = {
        "ok": bool(ok),
        "provider": str(provider or ""),
        "model": str(model or ""),
        "reason": str(reason or ""),
    }
    if ok:
        result["confirmation"] = confirmation
    else:
        # Fail closed for callers that want to branch directly on the public
        # enum, while ``ok`` tells them to use the deterministic fallback.
        result["confirmation"] = "no"
        result["error_type"] = reason or "provider_failed"
    return result


def classify_campaign_creation_claim(
    raw_response,
    *,
    provider="",
    model="",
    timeout=None,
    config=None,
    claim_type="creation",
):
    """Classify one raw assistant response with one independent LLM call.

    The returned object never contains provider diagnostics, request bodies,
    credentials, or raw response text.  Provider failures are represented by
    ``ok=False`` so the caller can use its conservative deterministic fallback.
    """
    if not isinstance(raw_response, str) or not raw_response.strip():
        return _safe_result(ok=False, reason="empty_response")
    if config is None:
        try:
            config = load_config()
        except Exception:
            return _safe_result(ok=False, reason="config_unavailable")
    value = raw_response.strip()
    if len(value) > CLAIM_INPUT_MAX_CHARS:
        half = CLAIM_INPUT_MAX_CHARS // 2
        value = f"{value[:half]}\n[...response truncated...]\n{value[-half:]}"
    runtime_state = _runtime_model_state()
    selected_provider = _provider_name(provider or runtime_state.get("provider"), config)
    selected_model = _active_model(model or runtime_state.get("model"), config, selected_provider)
    try:
        configured_timeout = os.environ.get("ADMIRA_CAMPAIGN_CLAIM_CLASSIFIER_TIMEOUT_SECONDS", "")
        limit = (
            float(configured_timeout)
            if timeout is None and str(configured_timeout).strip()
            else CLAIM_TIMEOUT_SECONDS if timeout is None else float(timeout)
        )
    except (TypeError, ValueError):
        limit = CLAIM_TIMEOUT_SECONDS
    limit = max(1.0, min(20.0, limit))
    is_edit = str(claim_type or "").strip().lower() == "edit"
    result_key = EDIT_RESULT_KEY if is_edit else CLAIM_RESULT_KEY
    result_schema = EDIT_SCHEMA if is_edit else CLAIM_SCHEMA
    prompt = _edit_classifier_prompt(value) if is_edit else _classifier_prompt(value)

    # Tests and local embedders may inject one callable. This remains one
    # provider request, with no history/tools/retry, and is also useful for
    # deterministic contract tests without network access.
    injected = config.get("llm") if isinstance(config, dict) else None
    if callable(injected):
        try:
            candidate = injected(
                prompt,
                provider=selected_provider,
                model=selected_model,
                schema=result_schema,
                timeout=limit,
            )
        except TimeoutError:
            return _safe_result(ok=False, provider=selected_provider, model=selected_model, reason="timeout")
        except Exception as exc:
            status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
            reason = "rate_limit" if status == 429 else "provider_error"
            return _safe_result(ok=False, provider=selected_provider, model=selected_model, reason=reason)
        if isinstance(candidate, str):
            try:
                candidate = {"ok": True, "compiled": json.loads(candidate)}
            except (TypeError, ValueError, json.JSONDecodeError):
                return _safe_result(ok=False, provider=selected_provider, model=selected_model, reason="malformed_json")
        elif isinstance(candidate, dict) and result_key in candidate and "compiled" not in candidate:
            candidate = {"ok": True, "compiled": candidate}
        if not isinstance(candidate, dict) or not candidate.get("ok"):
            return _safe_result(ok=False, provider=selected_provider, model=selected_model, reason="provider_error")
    elif selected_provider in _GEMINI_PROVIDERS:
        api_key = _gemini_api_key(config)
        if not api_key:
            return _safe_result(ok=False, provider=selected_provider, model=selected_model, reason="missing_credentials")
        try:
            candidate = _gemini_compile(
                selected_model,
                prompt,
                result_schema,
                api_key=api_key,
                base_url=_gemini_base_url(config) or GEMINI_COMPILER_BASE_URL,
                timeout=limit,
            )
        except Exception:
            return _safe_result(ok=False, provider=selected_provider, model=selected_model, reason="provider_exception")
    elif selected_provider in _CODEX_PROVIDERS:
        try:
            candidate = _terra_compile(
                prompt,
                result_schema,
                config=config,
                timeout=limit,
                model=selected_model,
            )
        except Exception:
            return _safe_result(ok=False, provider="openai-codex", model=selected_model, reason="provider_exception")
    else:
        return _safe_result(ok=False, provider=selected_provider, model=selected_model, reason="unsupported_provider")

    if not isinstance(candidate, dict) or not candidate.get("ok"):
        reason = str(candidate.get("reason") or "provider_failed") if isinstance(candidate, dict) else "provider_failed"
        return _safe_result(ok=False, provider=selected_provider, model=selected_model, reason=reason)
    compiled = candidate.get("compiled")
    if not isinstance(compiled, dict) or set(compiled) != {result_key}:
        return _safe_result(ok=False, provider=selected_provider, model=selected_model, reason="invalid_schema")
    confirmation = compiled.get(result_key)
    if confirmation not in CLAIM_ENUM:
        return _safe_result(ok=False, provider=selected_provider, model=selected_model, reason="invalid_enum")
    return _safe_result(
        ok=True,
        confirmation=confirmation,
        provider=selected_provider,
        model=selected_model,
        reason="classified",
    )


def classify_campaign_edit_claim(raw_response, **kwargs):
    """Classify only whether raw assistant prose claims an applied Meta edit."""
    return classify_campaign_creation_claim(raw_response, claim_type="edit", **kwargs)
