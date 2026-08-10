#!/usr/bin/env python3
"""Configure and run Admira IA through Hermes' native Telegram gateway."""
import json
import os
import hashlib
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from communication_style import (
    ad_experience_from_environment,
    ad_experience_instruction,
    communication_preference,
    communication_style_from_environment,
    communication_style_instruction,
)
from hermes_bridge import (
    ADMIRA_MINIMAX_KEY_ENV,
    ADMIRA_MINIMAX_PROVIDER,
    ADMIRA_MINIMAX_PROVIDER_NAME,
    ADMIRA_NVIDIA_DEFAULT_BASE_URL,
    ADMIRA_NVIDIA_KEY_ENV,
    ADMIRA_NVIDIA_PROVIDER,
    ADMIRA_NVIDIA_PROVIDER_NAME,
    HERMES_CONTEXT_FILE_SAFE_MAX_CHARS,
    ADMIRA_CUSTOM_PROVIDER,
    ADMIRA_OPENAI_PROVIDER,
    admira_connected_model_config_lines,
    admira_fallback_config_lines,
    hermes_compression_config_lines,
    inference_runtime_policy,
    admira_minimax_credentials,
    enforce_official_skill_catalog,
    hermes_brain_settings,
    hermes_environment,
    prepare_hermes_workspace,
)
from local_store import now_iso, read_json, write_private_json
from product_config import ROOT_DIR, agent_model_connections, env_bool, env_int

try:
    from product_config import normalize_hermes_model
except ImportError:
    def normalize_hermes_model(value):
        model = str(value or "").strip()
        if not model or model.lower() in {"auto", "recommended", "recomendado", "default"}:
            return "gpt-5.4-mini"
        return model


DATA_DIR = ROOT_DIR / "dashboard" / "data"
LOGS_DIR = ROOT_DIR / "logs"
GATEWAY_STATE_FILE = DATA_DIR / "hermes_gateway_state.json"
TELEGRAM_MODEL_STATE_FILE = DATA_DIR / "telegram_model_state.json"
TELEGRAM_RECENT_TURNS_FILE = DATA_DIR / "hermes_gateway_recent_turns.json"
TELEGRAM_UPDATE_INSTALL_REQUEST_FILE = DATA_DIR / "telegram_update_install_request.json"
INTERNAL_MODEL_RECOVERY_TOKEN_FILE = DATA_DIR / "internal_model_recovery.token"
DAILY_BRIEF_PROMPT_FILE = DATA_DIR / "hermes_daily_brief_prompt.md"
DAILY_SOCIAL_CONTENT_PROMPT_FILE = DATA_DIR / "hermes_daily_social_content_prompt.md"
POST_INSTALL_ORGANIC_INTRO_PROMPT_FILE = DATA_DIR / "hermes_post_install_organic_intro_prompt.md"
POST_INSTALL_ORGANIC_INTRO_STATE_FILE = DATA_DIR / "post_install_organic_intro_cron.json"
RESEARCH_PROMPT_FILE = DATA_DIR / "hermes_optimization_research_prompt.md"

_GATEWAY_PROCESS = None
_GATEWAY_FINGERPRINT = None
_GATEWAY_PROCESS_KIND = "admira_hermes_gateway_supervisor"
_GATEWAY_LOCK = threading.RLock()


def telegram_settings(config):
    return {
        "enabled": env_bool("TELEGRAM_AGENT_ENABLED", False),
        "mode": os.environ.get("TELEGRAM_AGENT_MODE", "hermes_gateway").strip().lower() or "hermes_gateway",
        "language": os.environ.get("TELEGRAM_LANGUAGE", "es").strip().lower() or "es",
        "poll_timeout": max(5, min(50, env_int("TELEGRAM_POLL_TIMEOUT", 25))),
        "bot_configured": bool(config.telegram_bot_token),
        "chat_id": str(config.telegram_chat_id or "").strip(),
        "hermes_home": str(getattr(config, "hermes_home", "") or ""),
    }


def hermes_home(config):
    path = Path(str(getattr(config, "hermes_home", "") or DATA_DIR / "hermes-home")).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def gateway_workspace(config):
    language = os.environ.get("TELEGRAM_LANGUAGE", "es")
    workspace_info = prepare_hermes_workspace(
        {
            "channel": "telegram",
            "language": language,
            "account_context": {
                "note": "Native Hermes Gateway workspace for Admira IA Telegram conversations.",
                "metrics_source": "read CURRENT_CONTEXT.json only if present and real.",
                "communication_preference": communication_preference(
                    communication_style_from_environment(),
                    language,
                    ad_experience_level=ad_experience_from_environment(),
                ),
            },
        }
    )
    return Path(workspace_info["path"])


def _quote_yaml(value):
    return json.dumps(str(value or ""), ensure_ascii=False)


def _env_value(value):
    return str(value or "").replace("\r", "\n").split("\n", 1)[0].strip()


def _gateway_media_allow_dirs():
    """Directories whose generated files Hermes may deliver as native media."""
    return [
        str((ROOT_DIR / "output").resolve()),
    ]


def _safe_dashboard_url(value):
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urllib.parse.urlsplit(text)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return ""
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def ensure_internal_model_recovery_token():
    """Create the private shared secret used only between dashboard and Gateway."""
    path = INTERNAL_MODEL_RECOVERY_TOKEN_FILE
    try:
        existing = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    except OSError:
        existing = ""
    if len(existing) >= 32:
        return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(48)
    path.write_text(token + "\n", encoding="utf-8")
    path.chmod(0o600)
    return token


def internal_model_recovery_url(config):
    try:
        port = int(getattr(config, "dashboard_port", 0) or os.environ.get("DASHBOARD_PORT") or 7871)
    except (TypeError, ValueError):
        port = 7871
    if port < 1 or port > 65535:
        port = 7871
    return f"http://127.0.0.1:{port}/api/internal/model-recovery"


def dashboard_action_link(config, action=""):
    """Return the safest buyer-facing dashboard/portal route for an action."""
    action = str(action or "").strip().lower()
    query_key = "open_update" if action == "update" else "reconnect_model"
    explicit = _safe_dashboard_url(
        os.environ.get("ADMIRA_DASHBOARD_URL")
        or os.environ.get("CLOUD_DASHBOARD_HTTPS_URL")
    )
    if not explicit:
        hostname = str(os.environ.get("CLOUD_DASHBOARD_HOSTNAME") or "").strip().lower().rstrip(".")
        hostname_is_valid = bool(
            hostname
            and len(hostname) <= 253
            and "." in hostname
            and all(
                label
                and len(label) <= 63
                and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
                for label in hostname.split(".")
            )
        )
        if hostname_is_valid:
            explicit = f"https://{hostname}/"
    if explicit:
        parsed = urllib.parse.urlsplit(explicit)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        query = [(key, value) for key, value in query if key not in {"reconnect_model", "open_update"}]
        query.append((query_key, "1"))
        return {
            "url": urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", urllib.parse.urlencode(query), "")),
            "kind": "dashboard",
        }
    cloud_install = bool(
        os.environ.get("CLOUD_ACCESS_SECRET")
        or os.environ.get("DIGITALOCEAN_TOKEN")
        or os.environ.get("DIGITALOCEAN_DROPLET_ID")
    )
    if cloud_install:
        return {"url": "https://admiraia.uboost.lat/access", "kind": "portal"}
    try:
        port = int(getattr(config, "dashboard_port", 0) or os.environ.get("DASHBOARD_PORT") or 7871)
    except (TypeError, ValueError):
        port = 7871
    if port < 1 or port > 65535:
        port = 7871
    return {"url": f"http://127.0.0.1:{port}/?{query_key}=1", "kind": "dashboard"}


def dashboard_recovery_link(config):
    """Return the safest buyer-facing route back to model settings."""
    return dashboard_action_link(config, "reconnect_model")


def dashboard_update_link(config):
    """Return the safest buyer-facing route to the update review."""
    return dashboard_action_link(config, "update")


def _telegram_model_provider_for_brain(brain):
    if (brain or {}).get("brain") == "minimax":
        return ADMIRA_MINIMAX_PROVIDER
    if (brain or {}).get("brain") == "nvidia_nim":
        return ADMIRA_NVIDIA_PROVIDER
    if (brain or {}).get("brain") == "openai_api":
        return ADMIRA_OPENAI_PROVIDER
    if (brain or {}).get("brain") == "custom_api":
        return ADMIRA_CUSTOM_PROVIDER
    return str((brain or {}).get("provider") or "openai-codex").strip() or "openai-codex"


def _telegram_model_label(provider, model):
    provider_raw = str(provider or "").strip()
    provider_key = provider_raw.lower().replace("_", "-")
    model_name = str(model or "").strip()
    if provider_key in {"admira-minimax", "minimax"}:
        return f"MiniMax M3 · {model_name or 'MiniMax-M3'}"
    if provider_key in {"admira-nvidia", "nvidia", "nvidia-nim"}:
        return f"NVIDIA NIM · {model_name or 'z-ai/glm-5.2'}"
    if provider_key in {"openai-codex", "openai_codex", "codex"}:
        return f"ChatGPT/Codex · {model_name or 'gpt-5.4-mini'}"
    if provider_key in {"admira-openai", "openai", "openai-api"}:
        return f"OpenAI API · {model_name or 'modelo configurado'}"
    if provider_key in {"admira-custom", "custom", "custom-api"}:
        return f"API compatible · {model_name or 'modelo configurado'}"
    if provider_key in {"custom", "openai", "openai-api"}:
        return model_name or provider_raw or "API compatible"
    return model_name or provider_raw or "Modelo configurado"


def configured_telegram_model_state(config):
    brain = hermes_brain_settings(config)
    provider = _telegram_model_provider_for_brain(brain)
    model = str(brain.get("model") or "").strip()
    return {
        "provider": provider,
        "model": model,
        "base_url": str(brain.get("base_url") or "").strip(),
        "label": _telegram_model_label(provider, model),
        "source": "configured_primary",
        "updated_at": "",
    }


def write_configured_telegram_model_state(config):
    payload = configured_telegram_model_state(config)
    payload["updated_at"] = now_iso()
    try:
        TELEGRAM_MODEL_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        TELEGRAM_MODEL_STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            TELEGRAM_MODEL_STATE_FILE.chmod(0o600)
        except OSError:
            pass
    except OSError:
        return False
    return True


def telegram_runtime_model_state(config):
    configured = configured_telegram_model_state(config)
    state = {}
    if TELEGRAM_MODEL_STATE_FILE.exists():
        try:
            state = json.loads(TELEGRAM_MODEL_STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
    provider = str(state.get("provider") or configured["provider"]).strip()
    model = str(state.get("model") or configured["model"]).strip()
    base_url = str(state.get("base_url") or configured.get("base_url") or "").strip()
    source = str(state.get("source") or configured["source"]).strip()
    runtime = {
        **configured,
        **state,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "source": source,
        "label": _telegram_model_label(provider, model),
        "configured_provider": configured["provider"],
        "configured_model": configured["model"],
        "configured_label": configured["label"],
    }
    runtime["is_configured_primary"] = (
        provider.lower().replace("_", "-") == configured["provider"].lower().replace("_", "-")
        and model.lower() == configured["model"].lower()
    )
    return runtime


def _gateway_model_config_lines(brain):
    """Return Hermes model config lines for the selected Admira brain.

    Admira's MiniMax M3 setup is configured as an OpenAI-compatible endpoint
    in the dashboard. Hermes' built-in ``minimax`` provider is Anthropic-wire
    oriented and its static picker/catalog can lag behind newer MiniMax models,
    so the Telegram gateway should expose MiniMax M3 as a named custom
    OpenAI-compatible provider. The API key stays in the process environment.
    """
    model_provider = brain.get("provider") or "openai-codex"
    model_default = brain.get("model") or normalize_hermes_model(getattr(brain, "hermes_model", ""))
    base_url = str(brain.get("base_url") or "").strip().rstrip("/")
    lines = [
        "model:",
        f"  provider: {_quote_yaml(model_provider)}",
        f"  default: {_quote_yaml(model_default)}",
    ]
    if brain.get("brain") == "minimax":
        provider_slug = ADMIRA_MINIMAX_PROVIDER
        provider_name = ADMIRA_MINIMAX_PROVIDER_NAME
        lines = [
            "model:",
            f"  provider: {_quote_yaml(provider_slug)}",
            f"  default: {_quote_yaml(model_default)}",
            "providers:",
            f"  {provider_slug}:",
            f"    name: {_quote_yaml(provider_name)}",
            f"    base_url: {_quote_yaml(base_url or 'https://api.minimax.io/v1')}",
            f"    key_env: {_quote_yaml(ADMIRA_MINIMAX_KEY_ENV)}",
            "    api_mode: \"chat_completions\"",
            f"    model: {_quote_yaml(model_default)}",
            "    models:",
            f"      {_quote_yaml(model_default)}: {{}}",
            "model_aliases:",
            f"  {_quote_yaml(model_default)}:",
            f"    model: {_quote_yaml(model_default)}",
            f"    provider: {_quote_yaml(provider_slug)}",
            f"    base_url: {_quote_yaml(base_url or 'https://api.minimax.io/v1')}",
            "  \"minimax m3\":",
            f"    model: {_quote_yaml(model_default)}",
            f"    provider: {_quote_yaml(provider_slug)}",
            f"    base_url: {_quote_yaml(base_url or 'https://api.minimax.io/v1')}",
            "  \"minimax-m3\":",
            f"    model: {_quote_yaml(model_default)}",
            f"    provider: {_quote_yaml(provider_slug)}",
            f"    base_url: {_quote_yaml(base_url or 'https://api.minimax.io/v1')}",
            "  \"minimax\":",
            f"    model: {_quote_yaml(model_default)}",
            f"    provider: {_quote_yaml(provider_slug)}",
            f"    base_url: {_quote_yaml(base_url or 'https://api.minimax.io/v1')}",
        ]
    elif brain.get("brain") == "nvidia_nim":
        provider_slug = ADMIRA_NVIDIA_PROVIDER
        official_base_url = base_url or ADMIRA_NVIDIA_DEFAULT_BASE_URL
        lines = [
            "model:",
            f"  provider: {_quote_yaml(provider_slug)}",
            f"  default: {_quote_yaml(model_default)}",
            *([f"  context_length: {int(brain['context_length'])}"] if brain.get("context_length") else []),
            "providers:",
            f"  {provider_slug}:",
            f"    name: {_quote_yaml(ADMIRA_NVIDIA_PROVIDER_NAME)}",
            f"    base_url: {_quote_yaml(official_base_url)}",
            f"    key_env: {_quote_yaml(ADMIRA_NVIDIA_KEY_ENV)}",
            "    api_mode: \"chat_completions\"",
            f"    model: {_quote_yaml(model_default)}",
            "    models:",
            f"      {_quote_yaml(model_default)}: {{}}",
            "model_aliases:",
            f"  {_quote_yaml(model_default)}:",
            f"    model: {_quote_yaml(model_default)}",
            f"    provider: {_quote_yaml(provider_slug)}",
            f"    base_url: {_quote_yaml(official_base_url)}",
            "  \"nvidia\":",
            f"    model: {_quote_yaml(model_default)}",
            f"    provider: {_quote_yaml(provider_slug)}",
            f"    base_url: {_quote_yaml(official_base_url)}",
            "  \"nvidia nim\":",
            f"    model: {_quote_yaml(model_default)}",
            f"    provider: {_quote_yaml(provider_slug)}",
            f"    base_url: {_quote_yaml(official_base_url)}",
        ]
    return lines


def _gateway_fingerprint(config, status, files):
    token_hash = hashlib.sha256(str(config.telegram_bot_token or "").encode("utf-8")).hexdigest()[:16]
    timezone_name = str(getattr(config, "daily_brief_timezone", "UTC") or "UTC")
    communication_style = communication_style_from_environment()
    ad_experience = ad_experience_from_environment()
    brain = hermes_brain_settings(config)
    minimax_credentials = admira_minimax_credentials(config, brain)
    connections = agent_model_connections(config, include_secrets=True)
    brain_fingerprint = {
        "brain": brain.get("brain", ""),
        "provider": brain.get("provider", ""),
        "model": brain.get("model", ""),
        "base_url": brain.get("base_url", ""),
        "api_key_set": bool(brain.get("api_key")),
        "minimax_api_key_set": bool(minimax_credentials.get("api_key")),
        "minimax_model": minimax_credentials.get("model", ""),
        "minimax_base_url": minimax_credentials.get("base_url", ""),
        "saved_connections": {
            provider: {
                "configured": bool(connection.get("configured")),
                "model": connection.get("model", ""),
                "base_url": connection.get("base_url", ""),
            }
            for provider, connection in connections.items()
        },
        "requires_codex_auth": bool(brain.get("requires_codex_auth")),
    }
    brain_hash = hashlib.sha256(json.dumps(brain_fingerprint, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"{token_hash}:{status['chat_id']}:{files['hermes_home']}:{timezone_name}:{communication_style}:{ad_experience}:{brain_hash}"


def gateway_prompt(language="es", communication_style="simple", ad_experience_level=""):
    style_instruction = communication_style_instruction(communication_style, language)
    experience_instruction = ad_experience_instruction(ad_experience_level, language)
    if str(language or "es").lower().startswith("en"):
        return (
            "You are Admira IA, the buyer's private Meta Ads manager. Your customer-facing identity is only Admira IA. "
            "Tool calls, planning, memory checks, drafts, and self-talk are private: never narrate them or place them in buyer-facing text. Emit exactly one finished answer, beginning on its own line with `[ADMIRA FINAL]`; do not use dashed separators between private work and the answer. "
            "Never mention Hermes, gateway/runtime details, MCP/tool names, internal commands, or `/help` command suggestions to the buyer unless support explicitly asks for diagnostics. "
            "Do not expose internal file paths such as `/app/...`, `dashboard/data/...`, `hermes-workspace/...`, `brand_guides/...`, `memory/...`, or `CURRENT_CONTEXT.json` to buyers unless support explicitly asks for technical diagnostics. "
            "After an image or creative tool succeeds, never paste `MEDIA:/...` or a local path as the deliverable. If a native attachment directive is needed, use `MEDIA:<local_path>` only as internal delivery syntax at the end of the response, while the visible message says the image is attached and summarizes what is ready. "
            "If the buyer asks for a prompt, copy, plan, script, diagnosis, or useful content, paste it directly in the chat; do not reply only with “I saved it in this file” or ask them to open an internal path. "
            "Internal workspace files are your private memory/tooling; the buyer's usable workspace is the conversation. You may say you saved something internally only after giving the requested content in the same reply. "
            "Use only the official versioned skills under this workspace's `skills/` directory. They are immutable universal product guidance and must never contain one buyer's facts, decisions, action history, outcomes, or self-improvement patches. For specialist work, read the matching `memory/currently-decided/*-currently-decided.md` companion; it is generated buyer state. Never edit either layer directly and never use, create, patch, or consult Hermes personal/global skills. Before ending every turn, check whether the buyer confirmed a durable fact, decision, preference, outcome, blocker, next step, or workflow agreement; save it with the narrowest `mcp_admira_save_*` tool named in the companion, using `mcp_admira_save_durable_memory` only as fallback. Never claim something was saved unless that tool confirmed success. "
            "Before every buyer-facing reply, read `skills/core-agent-behavior/SKILL.md`. Before any first-time greeting or onboarding question, also read `skills/session-continuity/SKILL.md`, `memory/Conversation continuity.md`, `memory/continuity_status.json`, `memory/latest_day_context.md`, `memory/active_workflow.json`, `CURRENT_CONTEXT.json`, `data/business_profile.json`, `memory/Agent onboarding plan.md`, `memory/Ads campaign onboarding.md`, `memory/recent_actions.json`, `memory/creative_experiments.json`, and relevant `brand_guides/` files in the workspace. Do not read pending approvals as ambient continuity; inspect them only after an explicit request to approve, reject, or activate one exact action. "
            "If the continuity status says persistent memory exists or active_workflow says work is active, treat history cleanup, gateway restart, updates, or a fresh runtime session as a resume event: do not introduce yourself as first time, do not restart onboarding, and do not repeat the initial ads-experience/technical-detail question unless those files prove it is still missing. "
            "Resume with a short continuation message that mentions one concrete remembered item and continue from the next useful step. Use session search for prior Telegram sessions only as a helper; durable workspace files are enough to keep moving. "
            "When the buyer shares a public URL, Google Drive link, video, image, landing page, or creative reference, use `mcp_admira_fetch_public_asset` before saying you cannot access it. If it returns a video, use its returned video_url/direct_url when preparing a video creative. If it returns video_frame_paths/video_preview_frame_paths, inspect those extracted image frames with vision to understand the video visually; do not try to inspect the raw MP4 directly and do not tell the buyer you cannot review video just because one low-level viewer only accepts images. "
            "Use your memory and workspace files before asking repeated questions. Every ordinary buyer message receives an automatically fetched live Meta context before you reason. Read it silently first on every turn, even when the visible topic is branding, creative work, onboarding, or something unrelated. That live snapshot is authoritative for current campaigns, ad sets, ads, status, budget, delivery, and performance; memory, action logs, plans, drafts, and approvals are never current Meta evidence. If they conflict, follow Meta. Do not cite ROAS, CPA, CTR, winners, losers, or campaign names unless that current live context confirms real Meta data. Do not bring up old approvals unless the buyer explicitly asks to approve/reject/activate one exact action. "
            "After every live Meta synchronization, audit each active campaign's metric_profile against its real objective, optimization goal, promoted event, and buyer priorities. Use mcp_admira_set_campaign_metric_priorities when the inferred scorecard is generic, wrong, or incomplete; this changes dashboard display only and needs no spend approval. Creating a full campaign/ad structure in PAUSED status may run after the buyer asks for it; "
            "activation, active publishing, budget increases, resumes, customer-data sends, or spend-capable changes must be prepared for approval. Approval IDs are private routing metadata: never show them to the buyer. A normal `approved` is valid only when the current proposal/card (or a direct reply to it) is available in this channel; if the buyer says they cannot see it, do not guess a pending item and do not execute or bypass the guardrail—show the proposal again and ask them to reply to it. For campaign activation/resume ask for the exact short phrase `Yes, activate`, then use the hidden ID internally. "
            "Never claim execution unless a product tool result confirms it. Business interview, brand, creatives, and previous campaign "
            "questions are handled by this Telegram conversation and are not dashboard setup blockers. Never tell the buyer setup is incomplete "
            "for those reasons; only say setup is missing when license, Meta connection, ad account, destination, real Meta data, ChatGPT/Codex, "
            "or Telegram itself is actually missing in CURRENT_CONTEXT.json or a product tool result. In Telegram, do not use Markdown tables; "
            "use short headings and bullet lists so the buyer always sees a readable message on mobile. Only when the continuity status shows no persistent memory, use the first onboarding message to explain "
            "the journey before asking: first understand the business, then define visual brand and creative style, then turn that into offers, "
            "ad briefs, strategy, and campaigns. In that first-run case, also ask whether the buyer has experience creating/managing ads and whether they want deep technical details only if that operator preference is not already saved; "
            "save that operator preference with `mcp_admira_save_agent_preferences` when the tool is available. Before using Codex for launch-ready creative planning or ad production, explicitly ask about colors, design references/uploads, official logo usage, "
            "Before creating or staging a campaign, ask for the buyer's three most important success metrics/results in priority order, not only the single optimization event; examples include ROAS, cost per purchase, cost per initiate checkout, cost per qualified lead, booked appointments, or cost per real WhatsApp conversation. Save and pass them as success_metrics/key_results when staging. "
            "For WhatsApp, Messenger, or Instagram Direct campaigns, ask what initial message or welcome text should appear, or propose 2-3 concise options if the buyer is unsure. For WhatsApp, prefer a buyer-sent prefilled_message; for Messenger/Instagram, use welcome_message and quick_replies only when supported by the connected messaging flow. Never imply Admira can send unsolicited first messages from the ad. For native WhatsApp, let the product resolve the Page-linked number from live Meta state; WhatsApp Business App numbers are supported and Cloud API/WABA is not mandatory. If Meta returns 1487246, treat it as a wrong or stale number and resolve again instead of silently changing the campaign objective. All supported campaign creatives and organic Page posts use the same primary Live Meta app/token; it must have Ads and Page permissions. Never ask the buyer for a second publishing token or request a dark/unpublished Page post as an intermediate. Offer a WEBSITE/TRAFFIC wa.me fallback only when the buyer explicitly accepts the optimization tradeoff. "
            "For native Meta Lead Ads / Instant Forms, first use `mcp_admira_list_lead_forms` to avoid duplicates when possible. If the buyer needs a new form, help design its name, fields/questions, privacy policy URL, optional thank-you/follow-up URL, and intent, then use `mcp_admira_create_lead_form` to create it through the connected Page token and verify the exact live lead_gen_form_id. Form creation is no-spend and does not need a second approval; pass the verified ID directly to the paused campaign. If Meta denies lookup or creation because the Page token lacks permission, use `mcp_admira_stage_lead_form` as the manual Ads Manager fallback, then list the live forms again after the buyer creates it. Pass the verified form ID directly into the native inline image/video creative; no external landing URL or Page post is required. If a tool result says the Page must accept Meta Lead Ads Terms, stop retries and send the buyer the direct URL https://www.facebook.com/ads/leadgen/tos. Tell them in the chat to open Telegram Desktop, keep Facebook open with full control of that Page, accept the terms at that link, and return with “terms accepted”; do not hide the URL or claim the campaign can continue before confirmation. "
            "real photos/assets, and the test budget when a real test/launch is being planned. If any brand item is missing, ask that question instead of claiming a final ad is ready. For a standalone image/asset/draft, do not block on budget or a complete brief; pass the current offer context and mark it as asset-only. Recommend a multi-format portfolio and several meaningful hypotheses sized to the budget when budget exists; Image 2 "
            "is only one production tool, never the strategy. Do not claim a launch-ready final ad until the brand and test brief are ready. After a real multi-creative launch, "
            "schedule adaptive experiment reviews with real Meta IDs, budget, and target CPA; never call an early signal a winner. Ask one clear question only when its answer truly blocks the next step; otherwise close with the decision or scheduled follow-up."
            " For optimization, distinguish sales, leads, and messages; treat zero-conversion CPA as unknown until runtime, spend, attribution lag, learning status, freshness, and edit cooldown are mature. "
            "Use Shopify aggregates as business truth when connected. Respect optimizer shadow mode and account/test-budget caps. Official research outranks community anecdotes; research may propose controlled tests but never spend actions."
            " Be globally proactive as an expert ad configurator across measurement, event setup, budgets, schedules, placements, audiences, creative format, diagnostics, and approval flow; do not limit that posture to placements."
            f" {style_instruction} {experience_instruction}"
        )
    return (
        "Eres Admira IA, el manager privado de Meta Ads del comprador. Tu identidad de cara al cliente es solo Admira IA. "
        "Las llamadas a herramientas, planificación, comprobaciones de memoria, borradores y diálogo interno son privados: nunca los narres ni los incluyas en el texto visible. Emite exactamente una respuesta terminada, comenzando en una línea propia con `[ADMIRA FINAL]`; no uses separadores de guiones entre trabajo privado y respuesta. "
        "Nunca menciones Hermes, gateway/runtime, nombres de herramientas MCP, comandos internos ni sugerencias de comandos como `/help` al comprador, salvo que soporte pida diagnóstico explícitamente. "
        "No muestres rutas internas como `/app/...`, `dashboard/data/...`, `hermes-workspace/...`, `brand_guides/...`, `memory/...` o `CURRENT_CONTEXT.json` al comprador, salvo que soporte pida diagnóstico técnico explícitamente. "
        "Después de que una herramienta de imagen o creativo genere un archivo, nunca pegues `MEDIA:/...` ni una ruta local como entregable. Si necesitas adjuntar el archivo, usa `MEDIA:<ruta_local>` solo como sintaxis interna de entrega al final de la respuesta; el mensaje visible debe decir que la imagen va adjunta y resumir qué quedó listo. "
        "Si el comprador pide un prompt, copy, plan, guion, diagnóstico o contenido útil, entrégalo directamente en el chat; no respondas solo “lo guardé en este archivo” ni le pidas abrir una ruta interna. "
        "Los archivos internos son tu memoria/herramienta privada; el workspace útil del comprador es la conversación. Puedes decir que algo quedó guardado internamente solo después de dar el contenido solicitado en el mismo mensaje. "
        "Usa únicamente las skills oficiales versionadas dentro de `skills/` en este workspace. Son guía universal e inmutable del producto: nunca guardes allí hechos, decisiones, historial de acciones, resultados ni parches de autoaprendizaje de un comprador. Para trabajo especializado, lee el companion correspondiente `memory/currently-decided/*-currently-decided.md`, que contiene el estado generado del comprador. Nunca edites directamente ninguna de las dos capas ni uses, crees, parches o consultes skills personales/globales de Hermes. Antes de terminar cada turno, revisa si el comprador confirmó un hecho, decisión, preferencia, resultado, bloqueo, siguiente paso o acuerdo de trabajo que deba sobrevivir un reset; guárdalo con la herramienta `mcp_admira_save_*` más específica nombrada en el companion y usa `mcp_admira_save_durable_memory` solo como respaldo. Nunca digas que algo quedó guardado si la herramienta no confirmó éxito. "
        "Antes de cada respuesta al comprador, lee `skills/core-agent-behavior/SKILL.md`. Antes de saludar como si fuera la primera vez o hacer preguntas de onboarding, lee también `skills/session-continuity/SKILL.md`, `memory/Conversation continuity.md`, `memory/continuity_status.json`, `memory/latest_day_context.md`, `memory/active_workflow.json`, `CURRENT_CONTEXT.json`, `data/business_profile.json`, `memory/Agent onboarding plan.md`, `memory/Ads campaign onboarding.md`, `memory/recent_actions.json`, `memory/creative_experiments.json` y los archivos relevantes de `brand_guides/` en el workspace. No leas aprobaciones pendientes como continuidad ambiental; revísalas solo después de una petición explícita para aprobar, rechazar o activar una acción exacta. "
        "Si el estado de continuidad dice que existe memoria persistente o active_workflow dice que hay trabajo activo, trata una limpieza de historial, reinicio del gateway, actualización o sesión nueva del runtime como una reanudación: no te presentes como primera vez, no reinicies el onboarding y no repitas la pregunta inicial de experiencia en anuncios/detalle técnico salvo que esos archivos demuestren que todavía falta. "
        "Retoma con un mensaje corto que mencione un dato concreto recordado y sigue con el siguiente paso útil. Usa búsqueda de sesiones anteriores de Telegram solo como ayuda; los archivos durables del workspace bastan para continuar. "
        "Cuando el comprador comparta una URL pública, enlace de Google Drive, video, imagen, landing page o referencia creativa, usa `mcp_admira_fetch_public_asset` antes de decir que no puedes acceder. Si devuelve un video, usa su video_url/direct_url al preparar un creativo de video. Si devuelve video_frame_paths/video_preview_frame_paths, revisa esas capturas extraídas con visión para entender visualmente el video; no intentes inspeccionar el MP4 crudo directamente ni le digas al comprador que no puedes revisar video solo porque un visor interno acepte imágenes. "
        "Usa tu memoria y los archivos de este workspace antes de repetir preguntas. Cada mensaje conversacional del comprador recibe automáticamente contexto live consultado en Meta antes de que razones. Léelo en silencio primero en cada turno, aunque el tema visible sea branding, creativos, onboarding u otra cosa. Ese snapshot live manda para campañas, conjuntos, anuncios, estados, presupuestos, entrega y rendimiento actuales; memoria, acciones, planes, borradores y aprobaciones nunca son evidencia del estado actual de Meta. Si discrepan, sigue Meta. No cites ROAS, CPA, CTR, ganadoras, perdedoras ni campañas si ese contexto live actual no confirma datos reales de Meta. No traigas aprobaciones antiguas salvo que el comprador pida explícitamente aprobar, rechazar o activar una acción exacta. "
        "Después de cada sincronización real con Meta, audita el metric_profile de cada campaña activa contra su objetivo, optimization goal, evento promovido y prioridades del comprador. Usa mcp_admira_set_campaign_metric_priorities cuando el scorecard inferido sea genérico, incorrecto o incompleto; esto solo cambia la vista del dashboard y no requiere aprobación de gasto. Crear una estructura completa de campaña/anuncios en estado PAUSED puede ejecutarse después de que el comprador lo pida; "
        "activar, publicar activo, subir presupuesto, reanudar, enviar datos de clientes o cualquier cambio capaz de gastar se prepara para aprobación. Los IDs de aprobación son metadatos privados de enrutamiento: nunca los muestres al comprador. Un `aprobado` normal solo vale si la propuesta/tarjeta actual (o una respuesta directa a ella) está disponible en este canal; si el comprador dice que no la ve, no adivines una aprobación pendiente ni ejecutes o saltes el guardrail: vuelve a mostrar la propuesta y pídele responder a ese mensaje. Para activar o reanudar una campaña pide la frase corta exacta `Sí, activar` y usa el ID oculto internamente. Nunca digas que ejecutaste algo si una herramienta del producto no lo confirmó. La entrevista del negocio, marca, "
        "creativos y campañas previas se completan conversando por Telegram y no bloquean la configuración inicial del dashboard. No le digas "
        "al comprador que falta completar configuración por esas razones; solo menciona que falta configurar algo si CURRENT_CONTEXT.json o una "
        "herramienta del producto confirma que falta licencia, conexión de Meta, cuenta publicitaria, destino, datos reales de Meta, ChatGPT/Codex "
        "o Telegram. En Telegram no uses tablas Markdown; usa títulos cortos y listas con viñetas para que el comprador siempre vea el mensaje "
        "bien en el celular. Solo cuando el estado de continuidad indique que no hay memoria persistente, usa el primer mensaje del onboarding para explicar el camino antes de preguntar: primero entenderemos el negocio, "
        "después definiremos la marca visual y el estilo creativo, y luego convertiremos eso en ofertas, briefs, estrategia y campañas. "
        "En ese caso de primera ejecución, también pregunta si el comprador tiene experiencia creando/gestionando anuncios y si quiere detalles técnicos profundos solo si esa preferencia de operador no está guardada; guarda esa preferencia de operador con `mcp_admira_save_agent_preferences` cuando la herramienta esté disponible. "
        "Antes de crear o preparar una campaña, pregunta por los 3 resultados más importantes para juzgarla, en orden de prioridad, no solo por el evento de optimización. Ejemplos: ROAS, costo por compra, costo por iniciar checkout, costo por lead calificado, reservas o costo por conversación real de WhatsApp. Guárdalos y pásalos como success_metrics/key_results al preparar campañas. "
        "Antes de preparar la campaña, haz una lectura final del contrato: objetivo/outcome, género y edad, placements automáticos/Advantage+ o manuales, copy aprobado de cada anuncio (texto principal, titular y CTA) y el mensaje prellenado exacto de WhatsApp o bienvenida de Messenger/Instagram deben coincidir con lo pedido. Si falta algo o entra en conflicto, corrige los argumentos antes de llamar a Meta; nunca uses copy genérico, género por defecto ni placements por defecto. "
        "Para campañas de WhatsApp, Messenger o Instagram Direct, pregunta qué mensaje inicial o texto de bienvenida debe aparecer, o propone 2-3 opciones cortas si el comprador no sabe. Para WhatsApp, prefiere un prefilled_message enviado por el comprador; para Messenger/Instagram, usa welcome_message y quick_replies solo cuando el flujo de mensajería conectado lo soporte. Nunca sugieras que Admira puede enviar primeros mensajes no solicitados desde el anuncio. "
        "Para campañas nativas de Meta Lead Ads / Instant Forms, usa primero `mcp_admira_list_lead_forms` para evitar duplicados cuando sea posible. Si el comprador necesita uno nuevo, ayúdale a diseñar nombre, campos/preguntas, URL de política de privacidad, URL opcional de gracias/seguimiento e intención; luego usa `mcp_admira_create_lead_form` para crearlo mediante el Page token conectado y verificar el lead_gen_form_id real. Crear el formulario no gasta dinero ni requiere una segunda aprobación; pasa el ID verificado directamente a la campaña en pausa. Si Meta rechaza la consulta o creación por permisos del Page token, usa `mcp_admira_stage_lead_form` como fallback manual y vuelve a listar los formularios cuando el comprador lo cree. Pasa ese ID directamente al creativo inline nativo; no requiere landing externa ni dark post. Si el resultado de una herramienta indica que la Página debe aceptar las Condiciones de Lead Ads de Meta, detén los reintentos y envía el enlace directo https://www.facebook.com/ads/leadgen/tos. Indica en el chat que abra Telegram Desktop, mantenga abierta su cuenta de Facebook con control total de esa Página, acepte las condiciones en ese enlace y vuelva con «condiciones aceptadas»; no ocultes el enlace ni afirmes que se puede continuar antes de confirmarlo. "
        "Antes de usar Codex para planear o producir creativos, pregunta de forma explícita por colores, referencias o diseños para subir, uso del logo oficial, fotos/activos reales "
        "y presupuesto de prueba. Si falta cualquier pieza de marca, pregunta eso en vez de llamar Codex. Recomienda un portafolio de varios formatos e hipótesis realmente distintas que quepan en ese presupuesto; Image 2 "
        "es solo una herramienta de producción, nunca la estrategia. No generes un anuncio final hasta completar la marca y el brief de prueba. "
        "Después de lanzar una prueba real con varios creativos, programa revisiones adaptativas con IDs reales de Meta, presupuesto y CPA objetivo; "
        "nunca llames ganador a una señal temprana. Haz una sola pregunta clara únicamente cuando su respuesta bloquee de verdad el siguiente paso; de lo contrario, cierra con la decisión o el seguimiento programado."
        " Para optimizar, distingue ventas, leads y mensajes; un CPA con cero conversiones es desconocido hasta madurar tiempo, gasto, atribución, aprendizaje, frescura y cooldown de cambios. "
        "Usa agregados de Shopify como verdad del negocio cuando estén conectados. Respeta el modo observación del optimizador y los topes/reserva de tests. La guía oficial tiene prioridad; una anécdota comunitaria solo puede proponer un test controlado, nunca una acción de gasto."
        " Sé proactivo globalmente como configurador experto de anuncios en medición, evento correcto, presupuesto, calendario, ubicaciones, audiencias, formato creativo, diagnósticos y aprobaciones; no limites esa postura a placements."
        f" {style_instruction} {experience_instruction}"
    )


def write_gateway_files(config):
    home = hermes_home(config)
    enforce_official_skill_catalog(home)
    workspace = gateway_workspace(config)
    status = telegram_settings(config)
    timezone_name = str(getattr(config, "daily_brief_timezone", "UTC") or "UTC")
    env_path = home / ".env"
    # Hermes cron jobs are separate processes. Upstream reloads HERMES_HOME/.env
    # immediately before every scheduled run, so credentials that only exist in
    # the long-lived Telegram gateway process are unavailable to cron. Keep a
    # private (0600), buyer-local copy of saved provider connections here.
    provider_env = {
        "minimax": (ADMIRA_MINIMAX_KEY_ENV, "ADMIRA_MINIMAX_BASE_URL", "ADMIRA_MINIMAX_MODEL"),
        "nvidia_nim": (ADMIRA_NVIDIA_KEY_ENV, "ADMIRA_NVIDIA_BASE_URL", "ADMIRA_NVIDIA_MODEL"),
        "openai_api": ("ADMIRA_OPENAI_API_KEY", "ADMIRA_OPENAI_BASE_URL", "ADMIRA_OPENAI_MODEL"),
        "custom_api": ("ADMIRA_CUSTOM_API_KEY", "ADMIRA_CUSTOM_BASE_URL", "ADMIRA_CUSTOM_MODEL"),
    }
    managed_provider_keys = {
        env_key
        for env_names in provider_env.values()
        for env_key in env_names
    }
    managed_env_keys = {
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USERS",
        "TELEGRAM_HOME_CHANNEL",
        "HERMES_TIMEZONE",
        "HERMES_MEDIA_ALLOW_DIRS",
        "ADMIRA_PRODUCT_ROOT",
        "ADMIRA_TELEGRAM_RECENT_TURNS_FILE",
        "ADMIRA_TELEGRAM_UPDATE_INSTALL_REQUEST_FILE",
        "ADMIRA_DASHBOARD_RECOVERY_URL",
        "ADMIRA_DASHBOARD_RECOVERY_KIND",
        "ADMIRA_GATEWAY_PROVIDER",
        "ADMIRA_CRON_PIN_PROVIDER",
        "ADMIRA_CRON_PIN_MODEL",
        # Used only as a process-local compatibility bridge for the NVIDIA
        # auxiliary compressor; never leave a stale value from a prior brain.
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "HERMES_CRON_MAX_PARALLEL",
        "ADMIRA_INTERNAL_MODEL_RECOVERY_URL",
        "ADMIRA_INTERNAL_MODEL_RECOVERY_TOKEN_FILE",
        *managed_provider_keys,
    }
    env_lines = []
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            key = line.split("=", 1)[0].strip() if "=" in line else ""
            if key not in managed_env_keys:
                env_lines.append(line)
    if config.telegram_bot_token:
        env_lines.append(f"TELEGRAM_BOT_TOKEN={_env_value(config.telegram_bot_token)}")
    if status["chat_id"]:
        env_lines.append(f"TELEGRAM_ALLOWED_USERS={_env_value(status['chat_id'])}")
        env_lines.append(f"TELEGRAM_HOME_CHANNEL={_env_value(status['chat_id'])}")
    env_lines.append(f"HERMES_TIMEZONE={_env_value(timezone_name)}")
    env_lines.append(f"HERMES_MEDIA_ALLOW_DIRS={_env_value(os.pathsep.join(_gateway_media_allow_dirs()))}")
    env_lines.append(f"ADMIRA_PRODUCT_ROOT={_env_value(str(ROOT_DIR))}")
    env_lines.append(f"ADMIRA_TELEGRAM_RECENT_TURNS_FILE={_env_value(str(TELEGRAM_RECENT_TURNS_FILE))}")
    env_lines.append(f"ADMIRA_TELEGRAM_UPDATE_INSTALL_REQUEST_FILE={_env_value(str(TELEGRAM_UPDATE_INSTALL_REQUEST_FILE))}")
    recovery_link = dashboard_recovery_link(config)
    env_lines.append(f"ADMIRA_DASHBOARD_RECOVERY_URL={_env_value(recovery_link['url'])}")
    env_lines.append(f"ADMIRA_DASHBOARD_RECOVERY_KIND={_env_value(recovery_link['kind'])}")
    active_brain = hermes_brain_settings(config)
    inference_policy = inference_runtime_policy(active_brain)
    if inference_policy["model_context_length"]:
        active_brain = {**active_brain, "context_length": inference_policy["model_context_length"]}
    active_provider = _telegram_model_provider_for_brain(active_brain)
    active_model = str(active_brain.get("model") or "").strip()
    env_lines.append(f"ADMIRA_GATEWAY_PROVIDER={_env_value(active_provider)}")
    env_lines.append(f"ADMIRA_CRON_PIN_PROVIDER={_env_value(active_provider)}")
    env_lines.append(f"ADMIRA_CRON_PIN_MODEL={_env_value(active_model)}")
    for provider, connection in agent_model_connections(config, include_secrets=True).items():
        if not connection.get("configured"):
            continue
        key_env, base_env, model_env = provider_env[provider]
        env_lines.append(f"{key_env}={_env_value(connection.get('api_key'))}")
        env_lines.append(f"{base_env}={_env_value(connection.get('base_url'))}")
        env_lines.append(f"{model_env}={_env_value(connection.get('model'))}")
    if active_brain.get("brain") == "nvidia_nim" and active_brain.get("api_key"):
        # Auxiliary compression uses Hermes' generic custom endpoint for
        # compatibility with older Hermes builds. The key stays in the
        # private gateway .env (mode 0600), never in config.yaml/workspace.
        env_lines.append(f"OPENAI_API_KEY={_env_value(active_brain.get('api_key'))}")
    if inference_policy["cron_max_parallel"]:
        # Prevent several due summaries from consuming a small hosted NVIDIA
        # allowance at once. Buyer Telegram messages are already sequential
        # per chat in Hermes; this controls scheduled-job bursts.
        env_lines.append(f"HERMES_CRON_MAX_PARALLEL={_env_value(inference_policy['cron_max_parallel'])}")
    env_lines.append(f"ADMIRA_INTERNAL_MODEL_RECOVERY_URL={_env_value(internal_model_recovery_url(config))}")
    env_lines.append(f"ADMIRA_INTERNAL_MODEL_RECOVERY_TOKEN_FILE={_env_value(str(INTERNAL_MODEL_RECOVERY_TOKEN_FILE))}")
    env_path.write_text("\n".join(env_lines).rstrip() + "\n", encoding="utf-8")
    env_path.chmod(0o600)

    allowed = status["chat_id"]
    communication_style = communication_style_from_environment()
    ad_experience = ad_experience_from_environment()
    prompt = gateway_prompt(status["language"], communication_style, ad_experience)
    brain = active_brain
    toolsets = ["hermes-telegram", "memory", "session_search", "vision", "file", "web", "browser", "admira"]
    mcp_server_path = ROOT_DIR / "src" / "admira_mcp_server.py"
    config_yaml = [
        f"timezone: {_quote_yaml(timezone_name)}",
        *admira_connected_model_config_lines(config, brain),
        *admira_fallback_config_lines(config, brain),
        f"context_file_max_chars: {inference_policy['context_file_max_chars']}",
        "agent:",
        f"  max_turns: {inference_policy['max_turns']}",
        f"  api_max_retries: {inference_policy['api_max_retries']}",
        "  gateway_timeout: 1800",
        "  gateway_timeout_warning: 900",
        "  clarify_timeout: 600",
        "  disabled_toolsets:",
        "    - terminal",
        "    - code_execution",
        "    - image_gen",
        "    - skills",
        *(["    - delegation"] if inference_policy["disable_delegation"] else []),
        "skills:",
        "  creation_nudge_interval: 0",
        "display:",
        "  memory_notifications: off",
        "session_reset:",
        "  mode: both",
        "  at_hour: 4",
        "  idle_minutes: 1440",
        "  notify: false",
        *hermes_compression_config_lines(config, brain, inference_policy),
        "mcp_servers:",
        "  admira:",
        "    enabled: true",
        f"    command: {_quote_yaml(sys.executable)}",
        "    args:",
        f"      - {_quote_yaml(str(mcp_server_path))}",
        "    env:",
        f"      PYTHONPATH: {_quote_yaml(str(ROOT_DIR / 'src'))}",
        f"      ADMIRA_PRODUCT_ROOT: {_quote_yaml(str(ROOT_DIR))}",
        "    timeout: 900",
        "    connect_timeout: 45",
        "    keepalive_interval: 1200",
        "terminal:",
        f"  cwd: {_quote_yaml(str(workspace))}",
        "telegram:",
        "  gateway_restart_notification: false",
        "  reactions: false",
        "  extra:",
        "    rich_messages: false",
        f"  allowed_chats: {_quote_yaml(allowed)}",
        "  channel_prompts:",
    ]
    if allowed:
        config_yaml.extend([f"    {_quote_yaml(allowed)}: |", *[f"      {line}" for line in prompt.splitlines()]])
    else:
        config_yaml.append("    {}")
    config_yaml.extend(["platform_toolsets:", "  telegram:"])
    config_yaml.extend([f"    - {toolset}" for toolset in toolsets])
    config_yaml.extend(["streaming:", "  enabled: false", "hooks_auto_accept: true"])
    config_path = home / "config.yaml"
    config_path.write_text("\n".join(config_yaml).rstrip() + "\n", encoding="utf-8")
    config_path.chmod(0o600)
    return {"hermes_home": str(home), "workspace": str(workspace), "config": str(config_path), "env": str(env_path)}


def gateway_status(config):
    global _GATEWAY_PROCESS, _GATEWAY_FINGERPRINT
    status = telegram_settings(config)
    running = bool(_GATEWAY_PROCESS and _GATEWAY_PROCESS.poll() is None)
    payload = {
        **status,
        "direct_hermes": True,
        "process_running": running,
        "pid": _GATEWAY_PROCESS.pid if running else None,
        "fingerprint": _GATEWAY_FINGERPRINT or "",
    }
    if GATEWAY_STATE_FILE.exists():
        try:
            payload["last_state"] = json.loads(GATEWAY_STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload["last_state"] = {}
    return payload


def _pid_cmdline(pid):
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return ""
    if pid_int <= 0:
        return ""
    proc_cmdline = Path(f"/proc/{pid_int}/cmdline")
    try:
        if proc_cmdline.exists():
            raw = proc_cmdline.read_bytes()
            return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    except OSError:
        return ""
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid_int), "-o", "command="],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
        return (result.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _looks_like_gateway_process(command):
    text = str(command or "")
    return _GATEWAY_PROCESS_KIND in text or "hermes gateway run" in text


def _pid_is_running(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def _terminate_pid_group(pid):
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    terminated = False
    try:
        if hasattr(os, "killpg"):
            try:
                os.killpg(pid_int, signal.SIGTERM)
            except OSError:
                os.kill(pid_int, signal.SIGTERM)
            terminated = True
        else:
            os.kill(pid_int, signal.SIGTERM)
            terminated = True
    except ProcessLookupError:
        return True
    except OSError:
        return False
    deadline = time.time() + 4
    while time.time() < deadline:
        if not _pid_is_running(pid_int):
            return True
        time.sleep(0.1)
    try:
        if hasattr(os, "killpg"):
            try:
                os.killpg(pid_int, signal.SIGKILL)
            except OSError:
                os.kill(pid_int, signal.SIGKILL)
        else:
            os.kill(pid_int, signal.SIGKILL)
        terminated = True
    except ProcessLookupError:
        return True
    except OSError:
        pass
    return terminated


def _terminate_process(process):
    if not process:
        return
    pid = getattr(process, "pid", None)
    terminated_by_group = bool(pid and _terminate_pid_group(pid))
    try:
        process.terminate()
        process.wait(timeout=1 if terminated_by_group else 6)
        return
    except subprocess.TimeoutExpired:
        pass
    except (OSError, AttributeError):
        if terminated_by_group:
            return
    if terminated_by_group:
        return
    try:
        process.kill()
    except (OSError, AttributeError):
        return
    try:
        process.wait(timeout=1)
    except Exception:
        pass


def _terminate_stale_gateway_from_state(skip_pid=None):
    if not GATEWAY_STATE_FILE.exists():
        return
    try:
        state = json.loads(GATEWAY_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    pid = state.get("pid")
    try:
        pid_int = int(pid)
        skip_int = int(skip_pid) if skip_pid else None
    except (TypeError, ValueError):
        return
    if skip_int and pid_int == skip_int:
        return
    command = _pid_cmdline(pid_int)
    if command and not _looks_like_gateway_process(command):
        return
    if command:
        _terminate_pid_group(pid_int)


def stop_gateway():
    global _GATEWAY_PROCESS, _GATEWAY_FINGERPRINT
    with _GATEWAY_LOCK:
        if _GATEWAY_PROCESS and _GATEWAY_PROCESS.poll() is None:
            _terminate_process(_GATEWAY_PROCESS)
        _terminate_stale_gateway_from_state(getattr(_GATEWAY_PROCESS, "pid", None))
        _GATEWAY_PROCESS = None
        _GATEWAY_FINGERPRINT = None


def reset_openai_codex_credential_status(config, files=None):
    """Clear stale Hermes cooldown metadata without disconnecting ChatGPT.

    Hermes stores OAuth credentials and their local exhausted/dead status in
    the same auth store. ``auth reset`` changes only the status metadata; it
    does not remove the account or its refresh token.
    """
    brain = hermes_brain_settings(config)
    if _telegram_model_provider_for_brain(brain) != "openai-codex":
        return {"ok": True, "reset": 0, "skipped": True, "reason": "provider_not_codex"}
    hermes_cli = shutil.which(getattr(config, "hermes_cli", "hermes") or "hermes")
    if not hermes_cli:
        return {"ok": False, "reset": 0, "reason": "hermes_not_installed"}
    files = files or write_gateway_files(config)
    env = hermes_environment(config)
    env["HERMES_HOME"] = files["hermes_home"]
    try:
        result = subprocess.run(
            [hermes_cli, "auth", "reset", "openai-codex"],
            cwd=files["workspace"],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "reset": 0, "reason": "codex_status_reset_failed", "error": str(exc)}
    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    match = re.search(r"Reset status on\s+(\d+)\s+openai-codex", output, flags=re.IGNORECASE)
    reset_count = int(match.group(1)) if match else 0
    return {
        "ok": result.returncode == 0,
        "reset": reset_count,
        "reason": "codex_status_reset" if result.returncode == 0 else "codex_status_reset_failed",
        "error": "" if result.returncode == 0 else output[-500:],
    }


def reconcile_cron_inference_pins(config, files=None):
    """Pin agent cron jobs to the currently selected brain.

    Hermes intentionally skips unpinned jobs when the global model changes. Admira
    treats a dashboard model change as an intentional migration, so existing
    non-script jobs must move with that selection instead of silently stopping.
    """
    files = files or write_gateway_files(config)
    brain = hermes_brain_settings(config)
    provider = _telegram_model_provider_for_brain(brain)
    model = str(brain.get("model") or "").strip()
    if not provider or not model:
        return {"ok": False, "updated": 0, "reason": "model_not_configured"}
    env = hermes_environment(config)
    env["HERMES_HOME"] = files["hermes_home"]
    env["ADMIRA_CRON_PIN_PROVIDER"] = provider
    env["ADMIRA_CRON_PIN_MODEL"] = model
    code = """
import json, os
from cron.jobs import list_jobs, update_job
provider = os.environ['ADMIRA_CRON_PIN_PROVIDER']
model = os.environ['ADMIRA_CRON_PIN_MODEL']
updated = []
for job in list_jobs(include_disabled=True):
    if getattr(job, 'no_agent', False):
        continue
    if getattr(job, 'provider', None) == provider and getattr(job, 'model', None) == model:
        continue
    update_job(job.id, {'provider': provider, 'model': model})
    updated.append(job.id)
print(json.dumps({'ok': True, 'updated': len(updated), 'job_ids': updated}))
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=files["workspace"], env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=20, check=False,
        )
    except Exception as exc:
        return {"ok": False, "updated": 0, "reason": "cron_pin_reconciliation_failed", "error": str(exc)}
    if result.returncode != 0:
        return {"ok": False, "updated": 0, "reason": "cron_pin_reconciliation_failed", "error": (result.stderr or result.stdout or "")[-500:]}
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {"ok": True, "updated": 0}


def _start_gateway_locked(config):
    global _GATEWAY_PROCESS, _GATEWAY_FINGERPRINT
    status = telegram_settings(config)
    if status["mode"] == "legacy":
        return {"started": False, "mode": "legacy", "detail": "Legacy Telegram bot mode selected."}
    if not (status["enabled"] and status["bot_configured"] and status["chat_id"]):
        stop_gateway()
        return {"started": False, "mode": "hermes_gateway", "detail": "Telegram no está completo todavía."}
    hermes_cli = shutil.which(getattr(config, "hermes_cli", "hermes") or "hermes")
    if not hermes_cli:
        return {"started": False, "mode": "hermes_gateway", "detail": "Hermes no está instalado en esta instalación."}
    files = write_gateway_files(config)
    credential_status_reset = reset_openai_codex_credential_status(config, files)
    fingerprint = _gateway_fingerprint(config, status, files)
    if (
        _GATEWAY_PROCESS
        and _GATEWAY_PROCESS.poll() is None
        and _GATEWAY_FINGERPRINT == fingerprint
        and not credential_status_reset.get("reset")
    ):
        reconcile_cron_inference_pins(config, files)
        return {"started": True, "mode": "hermes_gateway", "pid": _GATEWAY_PROCESS.pid, "credential_status_reset": credential_status_reset, **files}
    stop_gateway()
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "hermes-gateway.log"
    env = hermes_environment(config)
    env["HERMES_HOME"] = files["hermes_home"]
    env["HERMES_ACCEPT_HOOKS"] = "1"
    existing_pythonpath = env.get("PYTHONPATH", "")
    source_path = str(ROOT_DIR / "src")
    env["PYTHONPATH"] = source_path if not existing_pythonpath else f"{source_path}{os.pathsep}{existing_pythonpath}"
    env["ADMIRA_HERMES_RUNTIME_PATCHES"] = "1"
    env["ADMIRA_GATEWAY_LANGUAGE"] = status["language"]
    env["HERMES_MEDIA_ALLOW_DIRS"] = os.pathsep.join(_gateway_media_allow_dirs())
    env["ADMIRA_PRODUCT_ROOT"] = str(ROOT_DIR)
    env["ADMIRA_TELEGRAM_MODEL_STATE_FILE"] = str(TELEGRAM_MODEL_STATE_FILE)
    env["ADMIRA_TELEGRAM_RECENT_TURNS_FILE"] = str(TELEGRAM_RECENT_TURNS_FILE)
    env["ADMIRA_TELEGRAM_UPDATE_INSTALL_REQUEST_FILE"] = str(TELEGRAM_UPDATE_INSTALL_REQUEST_FILE)
    recovery_link = dashboard_recovery_link(config)
    env["ADMIRA_DASHBOARD_RECOVERY_URL"] = recovery_link["url"]
    env["ADMIRA_DASHBOARD_RECOVERY_KIND"] = recovery_link["kind"]
    env["ADMIRA_GATEWAY_PROVIDER"] = _telegram_model_provider_for_brain(hermes_brain_settings(config))
    active_brain = hermes_brain_settings(config)
    env["ADMIRA_CRON_PIN_PROVIDER"] = _telegram_model_provider_for_brain(active_brain)
    env["ADMIRA_CRON_PIN_MODEL"] = str(active_brain.get("model") or "").strip()
    ensure_internal_model_recovery_token()
    env["ADMIRA_INTERNAL_MODEL_RECOVERY_URL"] = internal_model_recovery_url(config)
    env["ADMIRA_INTERNAL_MODEL_RECOVERY_TOKEN_FILE"] = str(INTERNAL_MODEL_RECOVERY_TOKEN_FILE)
    write_configured_telegram_model_state(config)
    try:
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"\n[{now_iso()}] Starting Hermes Gateway for Admira IA\n")
            log_file.flush()
            supervisor_script = "\n".join(
                [
                    f"# {_GATEWAY_PROCESS_KIND}",
                    "while :; do",
                    f"  if ! {shlex.quote(hermes_cli)} mcp test admira >/dev/null 2>&1; then",
                    "    echo \"[$(date -Is)] Admira tool contract unavailable; retrying before Gateway startup\"",
                    "    sleep 15",
                    "    continue",
                    "  fi",
                    f"  {shlex.quote(hermes_cli)} gateway run --replace --accept-hooks",
                    "  code=$?",
                    "  echo \"[$(date -Is)] Hermes Gateway exited with code ${code}; restarting in 3s\"",
                    "  sleep 3",
                    "done",
                ]
            )
            _GATEWAY_PROCESS = subprocess.Popen(
                ["/bin/sh", "-c", supervisor_script],
                cwd=files["workspace"],
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
    except (OSError, ValueError) as exc:
        state = {"started_at": now_iso(), "mode": "hermes_gateway", "error": str(exc), **files}
        GATEWAY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        GATEWAY_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        _GATEWAY_PROCESS = None
        _GATEWAY_FINGERPRINT = None
        return {"started": False, "mode": "hermes_gateway", "detail": "No pude iniciar Hermes Gateway.", "error": str(exc), "log": str(log_path), **files}
    _GATEWAY_FINGERPRINT = fingerprint
    state = {"started_at": now_iso(), "pid": _GATEWAY_PROCESS.pid, "process_kind": _GATEWAY_PROCESS_KIND, "mode": "hermes_gateway", **files}
    GATEWAY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    GATEWAY_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    reconcile_cron_inference_pins(config, files)
    time.sleep(0.3)
    started = _GATEWAY_PROCESS.poll() is None
    response = {"started": started, "mode": "hermes_gateway", "pid": _GATEWAY_PROCESS.pid, "log": str(log_path), "credential_status_reset": credential_status_reset, **files}
    if not started:
        response["detail"] = "Hermes Gateway se cerró al iniciar. Revisa el diagnóstico técnico."
    return response


def start_gateway(config):
    """Start or reuse exactly one Gateway process across concurrent HTTP requests."""
    with _GATEWAY_LOCK:
        return _start_gateway_locked(config)


def daily_brief_prompt():
    return """Buenos días. Revisa la cuenta de Meta Ads con datos reales y memoria reciente.

Incluye contexto de los últimos días y fluctuaciones importantes. Responde corto y útil:

1. qué cambió
2. qué campaña o creativo necesita atención
3. qué se ve sano
4. qué prepararías para aprobación
5. qué test creativo sigue esperando evidencia, cuál es su líder provisional si existe y cuándo será la próxima revisión
6. calidad y frescura de datos, conciliación Shopify/Meta, bloqueos por aprendizaje/cooldown, anomalías y progreso del modo observación

No declares una ganadora si el seguimiento dice que la evidencia todavía es insuficiente.
No conviertas cero conversiones en un CPA artificial. No recomiendes cambios por datos del día incompleto, aprendizaje, atribución inmadura, datos viejos o cooldown activo.

Termina exactamente con: ¿Tienes alguna pregunta?

Si todavía no hay Datos reales de Meta, dilo claramente y explica qué falta conectar. No uses datos demo.
"""


def daily_social_content_prompt(posts_per_day=1, interval_days=1, content_formats="image", video_interval_days=7):
    count = max(1, min(5, int(posts_per_day or 1)))
    interval = max(1, min(30, int(interval_days or 1)))
    plural = "post" if count == 1 else "posts"
    cadence = "diario" if interval == 1 else f"cada {interval} días"
    normalized_formats = {
        item.strip().lower()
        for item in str(content_formats or "image").replace(";", ",").split(",")
        if item.strip()
    }
    allowed_formats = [item for item in ("image", "motion_video") if item in normalized_formats] or ["image"]
    format_label = "imágenes y motion videos" if len(allowed_formats) > 1 else ("motion videos" if allowed_formats == ["motion_video"] else "imágenes")
    video_interval = max(1, min(30, int(video_interval_days or 7)))
    return f"""Prepara el lote de contenido orgánico {cadence} de Admira IA para este negocio.

Objetivo: dejar {count} {plural} de {format_label} listo(s) para que el comprador los revise/apruebe desde Telegram. No publiques automáticamente.
Formatos autorizados por la estrategia: {', '.join(allowed_formats)}. Cadencia orientativa de motion video: uno cada {video_interval} día(s).

Antes de crear nada:
1. Lee `skills/core-agent-behavior/SKILL.md`, `skills/session-continuity/SKILL.md`, `skills/brand-and-assets/SKILL.md`, `skills/product-catalog-management/SKILL.md`, `skills/organic-content-strategy/SKILL.md`, `skills/creative-strategy/SKILL.md`, `skills/creative-production-codex-image/SKILL.md` y `skills/motion-graphics-video/SKILL.md`.
2. Lee `memory/content_asset_library.json`, `memory/content_strategy.md`, `memory/organic_content_posts.json`, `brand_guides/general_branding.md`, `brand_guides/creative_references.md`, productos/briefs y memoria reciente.
3. Confirma que `memory/content_strategy.md` contiene una estrategia aceptada y que marca/logo/colores/tono/assets ya están claros. Si no, no improvises una tanda: continúa el onboarding que falta y vuelve a guardar la configuración con `mcp_admira_save_daily_social_content_settings` cuando quede lista.

Cuando haya marca suficiente:
- Respeta estrictamente los formatos autorizados arriba. Si solo está autorizada imagen, no generes un video; puedes proponer añadirlo a la estrategia cuando una idea realmente lo merezca. Si están autorizados ambos, elige deliberadamente el formato que mejor explica la idea y evita repetir motion video antes de su cadencia salvo petición directa del comprador.
- Para imagen, usa Codex/Image mediante `mcp_admira_codex_image_generate`.
- Usa propósito `daily_social_post` o `organic_social_post`, no `standalone_creative` ni campaña pagada.
- En cada llamada envía un `request` autosuficiente con: tema/oferta activa exacta, pilar (educación, prueba, comunidad, objeción, detrás de cámaras o promoción), objetivo, texto principal visible, formato 4:5, decisión de CTA y referencia aprobada que debe seguir. Está prohibido enviar solo “usa las guías guardadas”.
- Si hay varios productos, llama `mcp_admira_search_product_catalog` y selecciona deliberadamente el producto, categoría o combinación que corresponde a la estrategia. No uses por defecto el último producto recordado ni mezcles detalles entre fichas.
- No conviertas automáticamente cada post en anuncio de respuesta directa. Precio, descuento, urgencia y CTA comercial solo aparecen si el pilar elegido es promoción.
- Si hay varias referencias, prioriza la aprobada más recientemente sobre notas genéricas antiguas cuando exista conflicto.
- Usa el logo oficial cuando exista y exige `pixel-level accurate` para no alterarlo.
- Si hay fotos/videos/assets compartidos por el cliente, selecciona solo items `classified` y aprobados para contenido diario. Nunca uses `pending_agent_review`, `pending_classification`, `do_not_use` o `prohibited`.
- Para fotos reales del comprador con `preservation_mode=pixel_locked`, pasa sus rutas en `protected_reference_image_paths` o sus IDs en `content_asset_ids`. El request debe exigir literalmente `pixel by pixel accuracy`, `pixel-level accurate reproduction` y `pixel-faithful`: puede recortar, escalar, posicionar, enmarcar, enmascarar bordes o superponer diseño, pero no retocar, embellecer, reiluminar, recolorear, regenerar ni cambiar personas, productos, textos, objetos, arquitectura o fondo.
- Las `style_reference` con `preservation_mode=style_only` van como referencias normales y solo guían el estilo; no las mezcles con fotos reales protegidas.
- Si un asset sigue sin propósito claro, haz una sola pregunta agrupada para clasificar la tanda antes de basar la estrategia en ella.
- Mantén los diseños alineados con colores, tono, referencias y restricciones de marca.
- Para motion video, primero define el propósito narrativo y busca recetas con `mcp_admira_search_motion_graphic_recipes`; después genera con Image 2 únicamente los fondos, sujetos o elementos faltantes y crea el MP4 con `mcp_admira_generate_motion_graphic_video`. Usa la marca principal y la oferta exacta, revisa el resultado real y reajusta el storyboard si hace falta. No conviertas una idea estática simple en video solo por variar.

Entrega en Telegram:
- Adjunta/envía la imagen o el MP4 generado; no pegues rutas internas.
- Incluye copy/caption sugerido, objetivo del post, pilar de contenido y por qué encaja.
- Después de cada pieza final, llama `mcp_admira_stage_organic_social_post` con `image_path` o `video_path`, caption exacto, pilar, objetivo y la Página guardada. Esa herramienta debe devolver una aprobación exacta; no inventes un ID.
- Presenta tres decisiones simples: responder `aprobado` para publicar, pedir cambios o descartar. Nunca muestres el ID interno de aprobación.
- Conserva internamente el approval_id exacto devuelto. Si el comprador aprueba esa pieza, llama `mcp_admira_approve_action` con el ID oculto. Solo esa aprobación puede publicar el post visible en Facebook.
- Si Publicación directa no está conectada, envía igualmente la pieza para revisión y explica el paso de conexión; nunca afirmes que quedó publicada.
"""


def post_install_organic_intro_prompt():
    return """Haz una invitación única y breve para activar la estrategia de contenido orgánico.

Contexto: esta instalación ya quedó andando. Este mensaje ocurre una sola vez unas horas después de la primera instalación para ofrecer ayuda proactiva, no para vender agresivamente.

Antes de escribir:
1. Lee `skills/core-agent-behavior/SKILL.md`, `skills/session-continuity/SKILL.md`, `skills/business-onboarding/SKILL.md`, `skills/brand-and-assets/SKILL.md` y `skills/organic-content-strategy/SKILL.md`.
2. Lee `memory/Branding onboarding.md`, `brand_guides/general_branding.md`, `brand_guides/Offer map.md`, `brand_guides/creative_references.md`, `memory/content_asset_library.json` y `memory/content_strategy.md`.
3. No repitas onboarding si ya hay memoria. Retoma con un dato concreto.

Mensaje deseado:
- Si branding todavía no está claro, empieza por branding: logo, colores, referencias, fotos/videos reales, tono o fuentes. Di que para crear posts bonitos primero conviene dejar esa base clara.
- Si branding ya está razonablemente claro, ofrece preparar una estrategia de contenido orgánico: pilares, temas por oferta/servicio/producto, frecuencia diaria o cada X días, y una mezcla recomendada de imágenes con Image 2 y motion videos cuando el mensaje gane claridad o atención con movimiento. No impongas video; propón una frecuencia razonable y deja que el comprador la confirme.
- Explica que el comprador puede compartir fotos, videos, testimonios, referencias o productos; Admira los guarda/categoriza y los usa inteligentemente.
- No actives un cron ni publiques nada todavía. Solo pregunta si quiere que lo armen juntos ahora.
- Mantén la respuesta corta, cálida y en español simple.
"""


def _parse_state_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ensure_post_install_organic_intro_cron(config):
    decision = str(getattr(config, "daily_social_content_decision", "") or "").strip().lower()
    if decision in {"enabled", "declined", "accepted_pending_setup"}:
        return {
            "configured": False,
            "needed": False,
            "exists": False,
            "state": decision,
            "detail": "La decisión sobre contenido orgánico ya fue guardada; no se repetirá la invitación.",
        }
    status = telegram_settings(config)
    if not (status["enabled"] and status["bot_configured"] and status["chat_id"]):
        return {"configured": False, "needed": False, "detail": "Telegram no está completo todavía."}
    state = read_json(POST_INSTALL_ORGANIC_INTRO_STATE_FILE, {})
    if not isinstance(state, dict):
        state = {}
    if state.get("done") or state.get("scheduled"):
        return {
            "configured": bool(state.get("scheduled") or state.get("done")),
            "needed": False,
            "exists": True,
            "name": state.get("name", "Admira IA - invitación contenido orgánico"),
            "schedule": state.get("due_at", ""),
            "state": "done" if state.get("done") else "scheduled",
        }
    hermes_cli = shutil.which(getattr(config, "hermes_cli", "hermes") or "hermes")
    if not hermes_cli:
        return {"configured": False, "needed": True, "detail": "Hermes no está instalado."}
    files = write_gateway_files(config)
    env = hermes_environment(config)
    env["HERMES_HOME"] = files["hermes_home"]
    timezone_name = str(getattr(config, "daily_brief_timezone", "UTC") or "UTC")
    env["HERMES_TIMEZONE"] = timezone_name
    env["TZ"] = timezone_name
    now = datetime.now(timezone.utc)
    first_seen = _parse_state_datetime(state.get("first_install_seen_at")) or now
    due = first_seen + timedelta(hours=3)
    if due <= now:
        due = now + timedelta(minutes=1)
    due_iso = due.isoformat(timespec="seconds")
    name = "Admira IA - invitación contenido orgánico"
    prompt = post_install_organic_intro_prompt()
    POST_INSTALL_ORGANIC_INTRO_PROMPT_FILE.write_text(prompt, encoding="utf-8")
    try:
        list_result = subprocess.run([hermes_cli, "cron", "list"], cwd=files["workspace"], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        write_private_json(
            POST_INSTALL_ORGANIC_INTRO_STATE_FILE,
            {**state, "first_install_seen_at": first_seen.isoformat(timespec="seconds"), "last_error": str(exc), "updated_at": now_iso()},
            ensure_ascii=False,
        )
        return {"configured": False, "needed": True, "detail": "No pude revisar la invitación orgánica post-instalación.", "error": str(exc), **files}
    output = (list_result.stdout or "") + (list_result.stderr or "")
    existing = _cron_job(output, name)
    if existing or name in output:
        write_private_json(
            POST_INSTALL_ORGANIC_INTRO_STATE_FILE,
            {
                **state,
                "first_install_seen_at": first_seen.isoformat(timespec="seconds"),
                "scheduled": True,
                "name": name,
                "job_id": (existing or {}).get("id", ""),
                "due_at": (existing or {}).get("schedule") or due_iso,
                "updated_at": now_iso(),
            },
            ensure_ascii=False,
        )
        return {"configured": True, "needed": False, "exists": True, "name": name, "job_id": (existing or {}).get("id", ""), "schedule": (existing or {}).get("schedule") or due_iso, "timezone": timezone_name, **files}
    try:
        result = subprocess.run(
            [
                hermes_cli,
                "cron",
                "create",
                "--name",
                name,
                "--deliver",
                f"telegram:{status['chat_id']}",
                "--repeat",
                "1",
                "--workdir",
                files["workspace"],
                due_iso,
                prompt,
            ],
            cwd=files["workspace"],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        write_private_json(
            POST_INSTALL_ORGANIC_INTRO_STATE_FILE,
            {**state, "first_install_seen_at": first_seen.isoformat(timespec="seconds"), "due_at": due_iso, "last_error": str(exc), "updated_at": now_iso()},
            ensure_ascii=False,
        )
        return {"configured": False, "needed": True, "detail": "No pude programar la invitación orgánica post-instalación.", "error": str(exc), "name": name, "schedule": due_iso, **files}
    ok = result.returncode == 0
    write_private_json(
        POST_INSTALL_ORGANIC_INTRO_STATE_FILE,
        {
            **state,
            "first_install_seen_at": first_seen.isoformat(timespec="seconds"),
            "scheduled": ok,
            "name": name,
            "due_at": due_iso,
            "scheduled_at": now_iso() if ok else "",
            "stdout": (result.stdout or "")[-500:],
            "stderr": (result.stderr or "")[-500:],
        },
        ensure_ascii=False,
    )
    return {
        "configured": ok,
        "needed": True,
        "exists": False,
        "name": name,
        "schedule": due_iso,
        "timezone": timezone_name,
        "stdout": (result.stdout or "")[-500:],
        "stderr": (result.stderr or "")[-500:],
        **files,
    }


def optimization_research_prompt():
    return """Haz la revisión semanal de estrategias actuales para Meta Ads.

1. Busca primero documentación oficial de Meta sobre entrega, aprendizaje, medición, Conversions API, presupuesto y creativos.
2. Después revisa fuentes expertas recientes y discusiones actuales de Reddit/foros para detectar problemas o tácticas que valga la pena probar.
3. No conviertas una opinión comunitaria en regla. Registra contradicciones y exige corroboración.
4. Por cada hallazgo útil llama `mcp_admira_save_optimization_research` con URL HTTPS, título, source_type, fecha publicada/observada, claim, counterevidence y testable_hypothesis.
5. Ningún hallazgo puede ejecutar cambios de gasto. Solo puede proponer un experimento que respete presupuesto, evidencia madura y aprobaciones.
6. Descarta fuentes expiradas, contenido sin fecha útil y afirmaciones que prometen resultados garantizados.

Al terminar, resume máximo tres hipótesis nuevas y di claramente qué proviene de Meta y qué es anecdótico. Sin tablas Markdown.
"""


def ensure_weekly_research_cron(config):
    status = telegram_settings(config)
    if not (status["enabled"] and status["bot_configured"] and status["chat_id"]):
        return {"configured": False, "detail": "Telegram no está completo todavía."}
    hermes_cli = shutil.which(getattr(config, "hermes_cli", "hermes") or "hermes")
    if not hermes_cli:
        return {"configured": False, "detail": "Hermes no está instalado."}
    files = write_gateway_files(config)
    prompt = optimization_research_prompt()
    RESEARCH_PROMPT_FILE.write_text(prompt, encoding="utf-8")
    env = hermes_environment(config)
    env["HERMES_HOME"] = files["hermes_home"]
    timezone_name = str(getattr(config, "daily_brief_timezone", "UTC") or "UTC")
    env["HERMES_TIMEZONE"] = timezone_name
    env["TZ"] = timezone_name
    name = "Admira IA - investigación semanal"
    schedule = "0 3 * * 0"
    try:
        listed = subprocess.run([hermes_cli, "cron", "list"], cwd=files["workspace"], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"configured": False, "detail": "No pude revisar la investigación semanal.", "error": str(exc), **files}
    output = (listed.stdout or "") + (listed.stderr or "")
    existing = _cron_job(output, name)
    delivery = f"telegram:{status['chat_id']}"
    command = None
    if existing and (existing.get("schedule") != schedule or existing.get("deliver") != delivery):
        command = [hermes_cli, "cron", "edit", existing["id"], "--schedule", schedule, "--prompt", prompt, "--deliver", delivery, "--workdir", files["workspace"]]
    elif not existing and name not in output:
        command = [hermes_cli, "cron", "create", "--name", name, "--deliver", delivery, "--workdir", files["workspace"], schedule, prompt]
    if command:
        try:
            result = subprocess.run(command, cwd=files["workspace"], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"configured": False, "detail": "No pude programar la investigación semanal.", "error": str(exc), **files}
        return {"configured": result.returncode == 0, "name": name, "schedule": schedule, "timezone": timezone_name, "stdout": (result.stdout or "")[-500:], "stderr": (result.stderr or "")[-500:], **files}
    return {"configured": True, "exists": True, "name": name, "job_id": (existing or {}).get("id", ""), "schedule": schedule, "timezone": timezone_name, **files}


def ensure_daily_social_content_cron(config):
    if not bool(getattr(config, "daily_social_content_enabled", False)):
        hermes_cli = shutil.which(getattr(config, "hermes_cli", "hermes") or "hermes")
        if not hermes_cli:
            return {"configured": False, "needed": False, "detail": "La generación diaria de posts está desactivada."}
        files = write_gateway_files(config)
        env = hermes_environment(config)
        env["HERMES_HOME"] = files["hermes_home"]
        name = "Admira IA - posts diarios"
        try:
            listed = subprocess.run([hermes_cli, "cron", "list"], cwd=files["workspace"], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
            output = (listed.stdout or "") + (listed.stderr or "")
            existing = _cron_job(output, name)
            if existing and existing.get("id"):
                removed = subprocess.run([hermes_cli, "cron", "remove", existing["id"]], cwd=files["workspace"], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
                return {
                    "configured": False,
                    "needed": False,
                    "removed": removed.returncode == 0,
                    "name": name,
                    "job_id": existing["id"],
                    "detail": "La generación recurrente de posts está desactivada y su horario fue eliminado." if removed.returncode == 0 else "La preferencia está desactivada, pero no pude eliminar el horario anterior.",
                    **files,
                }
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"configured": False, "needed": False, "detail": "La generación diaria de posts está desactivada.", "error": str(exc), **files}
        return {"configured": False, "needed": False, "detail": "La generación diaria de posts está desactivada.", **files}
    status = telegram_settings(config)
    if not (status["enabled"] and status["bot_configured"] and status["chat_id"]):
        return {"configured": False, "needed": True, "detail": "Telegram no está completo todavía."}
    hermes_cli = shutil.which(getattr(config, "hermes_cli", "hermes") or "hermes")
    if not hermes_cli:
        return {"configured": False, "needed": True, "detail": "Hermes no está instalado."}
    files = write_gateway_files(config)
    posts_per_day = max(1, min(5, int(getattr(config, "daily_social_content_posts_per_day", 1) or 1)))
    interval_days = max(1, min(30, int(getattr(config, "daily_social_content_interval_days", 1) or 1)))
    content_formats = str(getattr(config, "daily_social_content_formats", "image") or "image")
    video_interval_days = max(1, min(30, int(getattr(config, "daily_social_content_video_interval_days", 7) or 7)))
    prompt = daily_social_content_prompt(posts_per_day, interval_days, content_formats, video_interval_days)
    DAILY_SOCIAL_CONTENT_PROMPT_FILE.write_text(prompt, encoding="utf-8")
    env = hermes_environment(config)
    env["HERMES_HOME"] = files["hermes_home"]
    timezone_name = str(getattr(config, "daily_brief_timezone", "UTC") or "UTC")
    env["HERMES_TIMEZONE"] = timezone_name
    env["TZ"] = timezone_name
    name = "Admira IA - posts diarios"
    try:
        hour, minute = str(getattr(config, "daily_social_content_time", "10:00") or "10:00").split(":", 1)
        schedule = f"{int(minute)} {int(hour)} * * *" if interval_days == 1 else f"{int(minute)} {int(hour)} */{interval_days} * *"
    except (TypeError, ValueError):
        schedule = "0 10 * * *"
    try:
        list_result = subprocess.run([hermes_cli, "cron", "list"], cwd=files["workspace"], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"configured": False, "needed": True, "detail": "No pude revisar los horarios de posts diarios.", "error": str(exc), **files}
    list_output = (list_result.stdout or "") + (list_result.stderr or "")
    existing = _cron_job(list_output, name)
    desired_delivery = f"telegram:{status['chat_id']}"
    if existing:
        if existing.get("schedule") == schedule and existing.get("deliver") == desired_delivery:
            return {"configured": True, "needed": True, "exists": True, "name": name, "job_id": existing["id"], "schedule": schedule, "timezone": timezone_name, "posts_per_day": posts_per_day, "interval_days": interval_days, "content_formats": content_formats, "video_interval_days": video_interval_days, **files}
        try:
            edit_result = subprocess.run(
                [
                    hermes_cli,
                    "cron",
                    "edit",
                    existing["id"],
                    "--schedule",
                    schedule,
                    "--prompt",
                    prompt,
                    "--deliver",
                    desired_delivery,
                    "--workdir",
                    files["workspace"],
                ],
                cwd=files["workspace"],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"configured": False, "needed": True, "detail": "No pude actualizar el horario de posts diarios.", "error": str(exc), "name": name, "schedule": schedule, "timezone": timezone_name, **files}
        return {
            "configured": edit_result.returncode == 0,
            "needed": True,
            "exists": True,
            "updated": edit_result.returncode == 0,
            "name": name,
            "job_id": existing["id"],
            "schedule": schedule,
            "timezone": timezone_name,
            "posts_per_day": posts_per_day,
            "interval_days": interval_days,
            "content_formats": content_formats,
            "video_interval_days": video_interval_days,
            "stdout": (edit_result.stdout or "")[-500:],
            "stderr": (edit_result.stderr or "")[-500:],
            **files,
        }
    if name in list_output:
        return {"configured": True, "needed": True, "exists": True, "name": name, "schedule": schedule, "timezone": timezone_name, "posts_per_day": posts_per_day, "interval_days": interval_days, "content_formats": content_formats, "video_interval_days": video_interval_days, **files}
    try:
        result = subprocess.run(
            [
                hermes_cli,
                "cron",
                "create",
                "--name",
                name,
                "--deliver",
                desired_delivery,
                "--workdir",
                files["workspace"],
                schedule,
                prompt,
            ],
            cwd=files["workspace"],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"configured": False, "needed": True, "detail": "No pude crear el cron de posts diarios.", "error": str(exc), "name": name, "schedule": schedule, "timezone": timezone_name, **files}
    return {
        "configured": result.returncode == 0,
        "needed": True,
        "exists": False,
        "name": name,
        "schedule": schedule,
        "timezone": timezone_name,
        "posts_per_day": posts_per_day,
        "interval_days": interval_days,
        "content_formats": content_formats,
        "video_interval_days": video_interval_days,
        "stdout": (result.stdout or "")[-500:],
        "stderr": (result.stderr or "")[-500:],
        **files,
    }


def _cron_job(output, name):
    ansi = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
    lines = ansi.sub("", str(output or "")).splitlines()
    current = None
    jobs = []
    for line in lines:
        job_match = re.match(r"^\s*([0-9a-fA-F]{8,})\s+\[(active|paused)\]\s*$", line)
        if job_match:
            current = {"id": job_match.group(1), "status": job_match.group(2), "name": "", "schedule": "", "deliver": ""}
            jobs.append(current)
            continue
        if current is None:
            continue
        field_match = re.match(r"^\s*(Name|Schedule|Deliver):\s*(.*?)\s*$", line)
        if field_match:
            current[field_match.group(1).lower()] = field_match.group(2)
    return next((job for job in jobs if job.get("name") == name), None)


def _daily_brief_job(output, name):
    return _cron_job(output, name)


def experiment_review_prompt(experiment):
    experiment_id = str((experiment or {}).get("id") or "").strip()
    return f"""Revisa el experimento creativo `{experiment_id}` en Admira IA.

1. Llama `mcp_admira_run_due_experiment_reviews` con `experiment_id: {experiment_id}`.
2. Usa únicamente la evidencia real devuelta por la herramienta.
3. Si falta evidencia, explica en palabras simples qué falta y menciona la próxima fecha de revisión.
4. Si hay líder, llámala provisional y explica la evidencia. Propón pausar, refrescar o escalar solo cuando la herramienta lo recomiende.
5. Nunca ejecutes cambios protegidos sin la aprobación normal del comprador.

Responde en español, corto y sin tablas Markdown.
"""


def experiment_review_cron_name(experiment):
    experiment_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", str((experiment or {}).get("id") or "experiment"))[:42]
    due = re.sub(r"[^0-9]+", "", str((experiment or {}).get("next_review_at") or ""))[:14]
    return f"Admira IA - experimento {experiment_id} - {due or 'review'}"


def ensure_experiment_review_cron(config, experiment):
    next_review_at = str((experiment or {}).get("next_review_at") or "").strip()
    if not next_review_at or (experiment or {}).get("status") in {"completed", "cancelled", "decision_ready"}:
        return {"configured": False, "needed": False, "detail": "El experimento no tiene otra revisión pendiente."}
    status = telegram_settings(config)
    if not (status["enabled"] and status["bot_configured"] and status["chat_id"]):
        return {"configured": False, "needed": True, "detail": "Telegram no está completo todavía."}
    hermes_cli = shutil.which(getattr(config, "hermes_cli", "hermes") or "hermes")
    if not hermes_cli:
        return {"configured": False, "needed": True, "detail": "Hermes no está instalado."}
    files = write_gateway_files(config)
    env = hermes_environment(config)
    env["HERMES_HOME"] = files["hermes_home"]
    timezone_name = str(getattr(config, "daily_brief_timezone", "UTC") or "UTC")
    env["HERMES_TIMEZONE"] = timezone_name
    env["TZ"] = timezone_name
    name = experiment_review_cron_name(experiment)
    schedule = next_review_at
    try:
        list_result = subprocess.run(
            [hermes_cli, "cron", "list"],
            cwd=files["workspace"],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"configured": False, "needed": True, "detail": "No pude revisar los seguimientos de Hermes.", "error": str(exc), **files}
    list_output = (list_result.stdout or "") + (list_result.stderr or "")
    existing = _cron_job(list_output, name)
    if existing or name in list_output:
        return {
            "configured": True,
            "needed": True,
            "exists": True,
            "name": name,
            "job_id": (existing or {}).get("id", ""),
            "schedule": schedule,
            "next_review_at": next_review_at,
            "timezone": timezone_name,
            **files,
        }
    try:
        result = subprocess.run(
            [
                hermes_cli,
                "cron",
                "create",
                "--name",
                name,
                "--deliver",
                f"telegram:{status['chat_id']}",
                "--repeat",
                "1",
                "--workdir",
                files["workspace"],
                schedule,
                experiment_review_prompt(experiment),
            ],
            cwd=files["workspace"],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"configured": False, "needed": True, "detail": "No pude programar la revisión del experimento.", "error": str(exc), "name": name, **files}
    return {
        "configured": result.returncode == 0,
        "needed": True,
        "exists": False,
        "name": name,
        "schedule": schedule,
        "next_review_at": next_review_at,
        "timezone": timezone_name,
        "stdout": (result.stdout or "")[-500:],
        "stderr": (result.stderr or "")[-500:],
        **files,
    }


def ensure_experiment_review_crons(config):
    try:
        from experiment_scheduler import load_experiments
        experiments = load_experiments().get("experiments", [])
    except (ImportError, OSError, ValueError):
        experiments = []
    results = []
    for experiment in experiments:
        if experiment.get("next_review_at") and experiment.get("status") not in {"completed", "cancelled", "decision_ready"}:
            results.append(ensure_experiment_review_cron(config, experiment))
    return {"count": len(results), "configured": len([item for item in results if item.get("configured")]), "items": results}


def ensure_daily_brief_cron(config):
    status = telegram_settings(config)
    if not (status["enabled"] and status["bot_configured"] and status["chat_id"]):
        return {"configured": False, "detail": "Telegram no está completo todavía."}
    hermes_cli = shutil.which(getattr(config, "hermes_cli", "hermes") or "hermes")
    if not hermes_cli:
        return {"configured": False, "detail": "Hermes no está instalado."}
    files = write_gateway_files(config)
    DAILY_BRIEF_PROMPT_FILE.write_text(daily_brief_prompt(), encoding="utf-8")
    env = hermes_environment(config)
    env["HERMES_HOME"] = files["hermes_home"]
    timezone_name = str(getattr(config, "daily_brief_timezone", "UTC") or "UTC")
    env["HERMES_TIMEZONE"] = timezone_name
    env["TZ"] = timezone_name
    name = "Admira IA - lectura diaria"
    try:
        hour, minute = str(getattr(config, "daily_brief_time", "08:00") or "08:00").split(":", 1)
        schedule = f"{int(minute)} {int(hour)} * * *"
    except (TypeError, ValueError):
        schedule = "0 8 * * *"
    try:
        list_result = subprocess.run([hermes_cli, "cron", "list"], cwd=files["workspace"], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"configured": False, "detail": "No pude revisar los horarios de Hermes.", "error": str(exc), **files}
    list_output = (list_result.stdout or "") + (list_result.stderr or "")
    existing = _daily_brief_job(list_output, name)
    if existing:
        desired_delivery = f"telegram:{status['chat_id']}"
        if existing.get("schedule") == schedule and existing.get("deliver") == desired_delivery:
            return {"configured": True, "exists": True, "name": name, "job_id": existing["id"], "schedule": schedule, "timezone": timezone_name, **files}
        try:
            edit_result = subprocess.run(
                [
                    hermes_cli,
                    "cron",
                    "edit",
                    existing["id"],
                    "--schedule",
                    schedule,
                    "--prompt",
                    DAILY_BRIEF_PROMPT_FILE.read_text(encoding="utf-8"),
                    "--deliver",
                    desired_delivery,
                    "--workdir",
                    files["workspace"],
                ],
                cwd=files["workspace"],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"configured": False, "detail": "No pude actualizar la hora de la lectura diaria.", "error": str(exc), "name": name, "schedule": schedule, "timezone": timezone_name, **files}
        return {
            "configured": edit_result.returncode == 0,
            "exists": True,
            "updated": edit_result.returncode == 0,
            "name": name,
            "job_id": existing["id"],
            "schedule": schedule,
            "timezone": timezone_name,
            "stdout": (edit_result.stdout or "")[-500:],
            "stderr": (edit_result.stderr or "")[-500:],
            **files,
        }
    if name in list_output:
        return {"configured": True, "exists": True, "name": name, "schedule": schedule, "timezone": timezone_name, **files}
    try:
        result = subprocess.run(
            [
                hermes_cli,
                "cron",
                "create",
                "--name",
                name,
                "--deliver",
                f"telegram:{status['chat_id']}",
                "--workdir",
                files["workspace"],
                schedule,
                DAILY_BRIEF_PROMPT_FILE.read_text(encoding="utf-8"),
            ],
            cwd=files["workspace"],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"configured": False, "detail": "No pude crear la lectura diaria en Hermes.", "error": str(exc), "name": name, "schedule": schedule, **files}
    return {
        "configured": result.returncode == 0,
        "exists": False,
        "name": name,
        "schedule": schedule,
        "timezone": timezone_name,
        "stdout": (result.stdout or "")[-500:],
        "stderr": (result.stderr or "")[-500:],
        **files,
    }
