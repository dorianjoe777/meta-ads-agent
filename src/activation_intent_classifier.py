"""Classify buyer-authorized campaign activation timing in one isolated call.

The classifier receives only the current trusted buyer turn. It has no Hermes
history, tools, campaign data, or authority to mutate Meta. Language remains
semantic: there is no phrase list or regex router.
"""
import json

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
from product_config import load_config


INTENTS = ("immediate", "future", "unknown")
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"intent": {"type": "string", "enum": list(INTENTS)}},
    "required": ["intent"],
}
INPUT_MAX_CHARS = 8_000
DEFAULT_TIMEOUT_SECONDS = 12.0


def _result(ok, intent="unknown", *, provider="", model="", reason=""):
    return {
        "ok": bool(ok),
        "intent": intent if intent in INTENTS else "unknown",
        "provider": str(provider or ""),
        "model": str(model or ""),
        "reason": str(reason or ""),
    }


def _prompt(message):
    return (
        "Classify only whether this buyer actually requests or authorizes a Meta "
        "campaign activation, and when. Return exactly one JSON object matching "
        "the supplied schema, with no prose or extra keys. Use intent=immediate "
        "only when the buyer affirmatively wants the campaign activated now or as "
        "soon as possible. Use intent=future only when the buyer affirmatively wants "
        "activation at a later time or asks to schedule it. Use intent=unknown for "
        "denials, questions, corrections, mentions, ambiguous timing, or a bare "
        "affirmation that contains no activation request. Understand natural wording, "
        "synonyms, and spelling mistakes semantically; do not require fixed phrases. "
        "Do not use tools or infer missing conversation context.\n\n"
        "<buyer_turn>\n"
        f"{message}\n"
        "</buyer_turn>"
    )


def classify_activation_intent(message, *, provider="", model="", timeout=None, config=None):
    if not isinstance(message, str) or not message.strip():
        return _result(False, reason="empty_message")
    if config is None:
        try:
            config = load_config()
        except Exception:
            return _result(False, reason="config_unavailable")

    runtime = _runtime_model_state()
    selected_provider = _provider_name(provider or runtime.get("provider"), config)
    selected_model = _active_model(model or runtime.get("model"), config, selected_provider)
    try:
        limit = DEFAULT_TIMEOUT_SECONDS if timeout is None else float(timeout)
    except (TypeError, ValueError):
        limit = DEFAULT_TIMEOUT_SECONDS
    limit = max(1.0, min(20.0, limit))
    prompt = _prompt(message.strip()[:INPUT_MAX_CHARS])

    try:
        injected = config.get("llm") if isinstance(config, dict) else None
        if callable(injected):
            candidate = injected(
                prompt,
                provider=selected_provider,
                model=selected_model,
                schema=SCHEMA,
                timeout=limit,
            )
        elif selected_provider in _GEMINI_PROVIDERS:
            key = _gemini_api_key(config)
            if not key:
                return _result(False, provider=selected_provider, model=selected_model, reason="missing_credentials")
            candidate = _gemini_compile(
                selected_model,
                prompt,
                SCHEMA,
                api_key=key,
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
        else:
            return _result(False, provider=selected_provider, model=selected_model, reason="unsupported_provider")
    except TimeoutError:
        return _result(False, provider=selected_provider, model=selected_model, reason="timeout")
    except Exception:
        return _result(False, provider=selected_provider, model=selected_model, reason="provider_error")

    if isinstance(candidate, str):
        try:
            candidate = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            return _result(False, provider=selected_provider, model=selected_model, reason="malformed_json")
    if isinstance(candidate, dict) and isinstance(candidate.get("compiled"), dict):
        candidate = candidate["compiled"]
    if not isinstance(candidate, dict) or set(candidate) != {"intent"}:
        return _result(False, provider=selected_provider, model=selected_model, reason="invalid_output")
    intent = candidate.get("intent")
    if intent not in INTENTS:
        return _result(False, provider=selected_provider, model=selected_model, reason="invalid_output")
    return _result(True, intent, provider=selected_provider, model=selected_model, reason="classified")
