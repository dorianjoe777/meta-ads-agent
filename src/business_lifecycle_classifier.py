#!/usr/bin/env python3
"""Independent semantic gate for business-lifecycle transitions.

This is deliberately a small, stateless call outside the Hermes runtime.  It
does not receive conversation history, tools, or provider retries.  It only
answers whether the buyer's current message accepts an artefact that was
already presented.  Persistence and ordering remain authoritative elsewhere.
"""

from __future__ import annotations

import json
import os

from campaign_claim_classifier import (
    _CODEX_PROVIDERS,
    _GEMINI_PROVIDERS,
    _active_model,
    _provider_name,
    _runtime_model_state,
)
from campaign_payload_compiler import (
    GEMINI_COMPILER_BASE_URL,
    _gemini_api_key,
    _gemini_base_url,
    _gemini_compile,
    _terra_compile,
)
from product_config import ROOT_DIR, load_config


LIFECYCLE_INPUT_MAX_CHARS = 8_000
LIFECYCLE_TIMEOUT_SECONDS = 12.0
TRANSITION_KEY = "confirmacion_transicion"
TARGETS = ("business_profile", "strategic_plan")
ENUM = ("si", "no")
PLAN_UPDATE_KEY = "solicitud_actualizacion_plan"
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {TRANSITION_KEY: {"type": "string", "enum": list(ENUM)}},
    "required": [TRANSITION_KEY],
}
PLAN_UPDATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {PLAN_UPDATE_KEY: {"type": "string", "enum": list(ENUM)}},
    "required": [PLAN_UPDATE_KEY],
}


def _prompt(target: str, artifact: str, buyer_message: str) -> str:
    label = "business profile" if target == "business_profile" else "strategic plan"
    return (
        "Classify only whether the buyer's current message accepts the already "
        f"presented {label} as current/final, or accepts moving forward from it. "
        f'Return exactly {{"{TRANSITION_KEY}": "si"}} or '
        f'{{"{TRANSITION_KEY}": "no"}} and no other keys or prose. '
        "Return si only when the artefact was presented immediately before and "
        "the current buyer message clearly approves it, accepts it as final, or "
        "clearly agrees to continue from it (including natural wording such as "
        "'me parece genial, podemos seguir'). Return no for corrections, questions, "
        "requests for changes, ambiguity, greetings, unrelated content, or a bare "
        "affirmation that has no presented artefact to anchor it. Do not infer an "
        "approval from information merely repeating or adding business facts. "
        "This is classification only; do not save anything and do not use tools.\n\n"
        "<presented_artifact>\n"
        f"{artifact}\n"
        "</presented_artifact>\n"
        "<current_buyer_message>\n"
        f"{buyer_message}\n"
        "</current_buyer_message>"
    )


def _safe(*, ok: bool, confirmation: str = "no", provider: str = "", model: str = "", reason: str = ""):
    return {
        "ok": bool(ok),
        "confirmation": confirmation if confirmation in ENUM else "no",
        "provider": str(provider or ""),
        "model": str(model or ""),
        "reason": str(reason or ""),
        **({} if ok else {"error_type": reason or "provider_failed"}),
    }


def classify_lifecycle_transition(
    target: str,
    presented_artifact: str,
    buyer_message: str,
    *,
    provider: str = "",
    model: str = "",
    timeout=None,
    config=None,
):
    """Classify one transition with exactly one independent model request.

    ``presented_artifact`` and ``buyer_message`` are bounded raw strings; no
    Hermes state is loaded other than the selected provider/model routing.
    Provider errors, malformed JSON, and unsupported inputs fail closed.
    """
    if target not in TARGETS:
        return _safe(ok=False, reason="invalid_target")
    if not isinstance(presented_artifact, str) or not presented_artifact.strip():
        return _safe(ok=False, reason="artifact_not_presented")
    if not isinstance(buyer_message, str) or not buyer_message.strip():
        return _safe(ok=False, reason="empty_buyer_message")
    if config is None:
        try:
            config = load_config()
        except Exception:
            return _safe(ok=False, reason="config_unavailable")

    def bound(value):
        value = value.strip()
        if len(value) <= LIFECYCLE_INPUT_MAX_CHARS:
            return value
        half = LIFECYCLE_INPUT_MAX_CHARS // 2
        return f"{value[:half]}\n[...truncated...]\n{value[-half:]}"

    runtime = _runtime_model_state()
    selected_provider = _provider_name(provider or runtime.get("provider"), config)
    selected_model = _active_model(model or runtime.get("model"), config, selected_provider)
    try:
        configured = os.environ.get("ADMIRA_LIFECYCLE_CLASSIFIER_TIMEOUT_SECONDS", "")
        limit = float(configured) if timeout is None and configured.strip() else (
            LIFECYCLE_TIMEOUT_SECONDS if timeout is None else float(timeout)
        )
    except (TypeError, ValueError):
        limit = LIFECYCLE_TIMEOUT_SECONDS
    limit = max(1.0, min(20.0, limit))
    prompt = _prompt(target, bound(presented_artifact), bound(buyer_message))

    injected = config.get("llm") if isinstance(config, dict) else None
    try:
        if callable(injected):
            candidate = injected(
                prompt,
                provider=selected_provider,
                model=selected_model,
                schema=SCHEMA,
                timeout=limit,
            )
        elif selected_provider in _GEMINI_PROVIDERS:
            api_key = _gemini_api_key(config)
            if not api_key:
                return _safe(ok=False, provider=selected_provider, model=selected_model, reason="missing_credentials")
            candidate = _gemini_compile(
                selected_model,
                prompt,
                SCHEMA,
                api_key=api_key,
                base_url=_gemini_base_url(config) or GEMINI_COMPILER_BASE_URL,
                timeout=limit,
            )
        elif selected_provider in _CODEX_PROVIDERS:
            candidate = _terra_compile(
                prompt,
                SCHEMA,
                config=config,
                timeout=limit,
                model=selected_model,
            )
            selected_provider = "openai-codex"
        else:
            return _safe(ok=False, provider=selected_provider, model=selected_model, reason="unsupported_provider")
    except TimeoutError:
        return _safe(ok=False, provider=selected_provider, model=selected_model, reason="timeout")
    except Exception as exc:
        status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        reason = "rate_limit" if status == 429 else "provider_error"
        return _safe(ok=False, provider=selected_provider, model=selected_model, reason=reason)

    if isinstance(candidate, str):
        try:
            candidate = {"ok": True, "compiled": json.loads(candidate)}
        except (TypeError, ValueError, json.JSONDecodeError):
            return _safe(ok=False, provider=selected_provider, model=selected_model, reason="malformed_json")
    elif isinstance(candidate, dict) and TRANSITION_KEY in candidate and "compiled" not in candidate:
        candidate = {"ok": True, "compiled": candidate}
    if not isinstance(candidate, dict) or not candidate.get("ok"):
        return _safe(ok=False, provider=selected_provider, model=selected_model, reason="provider_error")
    compiled = candidate.get("compiled")
    if not isinstance(compiled, dict) or set(compiled) != {TRANSITION_KEY}:
        return _safe(ok=False, provider=selected_provider, model=selected_model, reason="invalid_schema")
    value = compiled.get(TRANSITION_KEY)
    if value not in ENUM:
        return _safe(ok=False, provider=selected_provider, model=selected_model, reason="invalid_enum")
    return _safe(ok=True, confirmation=value, provider=selected_provider, model=selected_model, reason="classified")


def classify_strategic_plan_update_request(
    current_plan: str,
    buyer_message: str,
    *,
    provider: str = "",
    model: str = "",
    timeout=None,
    config=None,
):
    """Detect an explicit request to modify the saved strategic plan.

    A confirmed plan remains confirmed when the buyer merely adds a product,
    asks for a campaign, or discusses strategy informally.  This independent
    classifier returns ``si`` only for a direct request to change, add to, or
    remove something from the saved plan; persistence code decides what to do
    with that signal.
    """
    if not isinstance(current_plan, str) or not current_plan.strip():
        return _safe(ok=False, reason="plan_not_presented")
    if not isinstance(buyer_message, str) or not buyer_message.strip():
        return _safe(ok=False, reason="empty_buyer_message")
    if config is None:
        try:
            config = load_config()
        except Exception:
            return _safe(ok=False, reason="config_unavailable")

    def bound(value):
        value = value.strip()
        if len(value) <= LIFECYCLE_INPUT_MAX_CHARS:
            return value
        half = LIFECYCLE_INPUT_MAX_CHARS // 2
        return f"{value[:half]}\n[...truncated...]\n{value[-half:]}"

    runtime = _runtime_model_state()
    selected_provider = _provider_name(provider or runtime.get("provider"), config)
    selected_model = _active_model(model or runtime.get("model"), config, selected_provider)
    prompt = (
        "Classify only whether the buyer explicitly requests a change to the "
        "already saved strategic plan. Return exactly one JSON object with only "
        f'{{"{PLAN_UPDATE_KEY}": "si"}} or '
        f'{{"{PLAN_UPDATE_KEY}": "no"}}. Return si only for a direct request to '
        "modify, add, remove, replace, or update the saved strategic plan itself. "
        "Return no when the buyer merely shares a new service/fact, requests a "
        "campaign or creative, discusses an informal strategy idea, asks a question, "
        "greets, or provides information without requesting that the saved plan be "
        "changed. Do not use tools, history, or Hermes context. Do not save anything.\n\n"
        "<saved_strategic_plan>\n"
        f"{bound(current_plan)}\n"
        "</saved_strategic_plan>\n"
        "<current_buyer_message>\n"
        f"{bound(buyer_message)}\n"
        "</current_buyer_message>"
    )
    try:
        configured = os.environ.get("ADMIRA_LIFECYCLE_CLASSIFIER_TIMEOUT_SECONDS", "")
        limit = float(configured) if timeout is None and configured.strip() else (
            LIFECYCLE_TIMEOUT_SECONDS if timeout is None else float(timeout)
        )
    except (TypeError, ValueError):
        limit = LIFECYCLE_TIMEOUT_SECONDS
    limit = max(1.0, min(20.0, limit))

    injected = config.get("llm") if isinstance(config, dict) else None
    try:
        if callable(injected):
            candidate = injected(
                prompt,
                provider=selected_provider,
                model=selected_model,
                schema=PLAN_UPDATE_SCHEMA,
                timeout=limit,
            )
        elif selected_provider in _GEMINI_PROVIDERS:
            api_key = _gemini_api_key(config)
            if not api_key:
                return _safe(ok=False, provider=selected_provider, model=selected_model, reason="missing_credentials")
            candidate = _gemini_compile(
                selected_model, prompt, PLAN_UPDATE_SCHEMA,
                api_key=api_key,
                base_url=_gemini_base_url(config) or GEMINI_COMPILER_BASE_URL,
                timeout=limit,
            )
        elif selected_provider in _CODEX_PROVIDERS:
            candidate = _terra_compile(
                prompt, PLAN_UPDATE_SCHEMA, config=config, timeout=limit, model=selected_model
            )
            selected_provider = "openai-codex"
        else:
            return _safe(ok=False, provider=selected_provider, model=selected_model, reason="unsupported_provider")
    except TimeoutError:
        return _safe(ok=False, provider=selected_provider, model=selected_model, reason="timeout")
    except Exception as exc:
        status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        return _safe(
            ok=False, provider=selected_provider, model=selected_model,
            reason="rate_limit" if status == 429 else "provider_error",
        )

    if isinstance(candidate, str):
        try:
            candidate = {"ok": True, "compiled": json.loads(candidate)}
        except (TypeError, ValueError, json.JSONDecodeError):
            return _safe(ok=False, provider=selected_provider, model=selected_model, reason="malformed_json")
    elif isinstance(candidate, dict) and PLAN_UPDATE_KEY in candidate and "compiled" not in candidate:
        candidate = {"ok": True, "compiled": candidate}
    if not isinstance(candidate, dict) or not candidate.get("ok"):
        return _safe(ok=False, provider=selected_provider, model=selected_model, reason="provider_error")
    compiled = candidate.get("compiled")
    if not isinstance(compiled, dict) or set(compiled) != {PLAN_UPDATE_KEY}:
        return _safe(ok=False, provider=selected_provider, model=selected_model, reason="invalid_schema")
    value = compiled.get(PLAN_UPDATE_KEY)
    if value not in ENUM:
        return _safe(ok=False, provider=selected_provider, model=selected_model, reason="invalid_enum")
    return _safe(ok=True, confirmation=value, provider=selected_provider, model=selected_model, reason="classified")
