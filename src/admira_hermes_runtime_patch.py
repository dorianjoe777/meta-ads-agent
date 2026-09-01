#!/usr/bin/env python3
"""Runtime patches for third-party Hermes gateway buyer-facing messages.

The Hermes gateway is installed as a dependency inside the buyer container.
Admira should not edit site-packages in place, so this module is loaded through
PYTHONPATH/sitecustomize only for the gateway process and wraps the narrow
provider-error formatter that can otherwise leak raw English provider text.
"""
import asyncio
import hashlib
import importlib
import importlib.util
import json
import os
import re
import sqlite3
import copy
import difflib
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
from complete_reset import (
    COMPLETE_RESET_COMMAND,
    COMPLETE_RESET_CONFIRMATION_PHRASE,
    COMPLETE_RESET_CONFIRMATION_TTL_SECONDS,
    begin_reset_confirmation,
    consume_reset_confirmation,
    reset_control_paths,
)

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
ADMIRA_NVIDIA_PREPARE_ACTIVE = ContextVar("admira_nvidia_prepare_active", default=False)
ADMIRA_AGENT_MAX_ITERATIONS = 8
ADMIRA_PRODUCT_STATE_START = "[ADMIRA PRODUCT STATE — internal, never quote]"
ADMIRA_PRODUCT_STATE_END = "[END ADMIRA PRODUCT STATE]"
ADMIRA_COMPILED_PROCEDURE_START = "[ADMIRA COMPILED PROCEDURE — internal, never quote]"
ADMIRA_COMPILED_PROCEDURE_END = "[END ADMIRA COMPILED PROCEDURE]"
ADMIRA_CURRENT_TURN_TOOL_RECEIPTS_KEY = "_admira_current_turn_tool_receipts"
ADMIRA_CURRENT_BUYER_MESSAGE_KEY = "_admira_current_buyer_message"
ADMIRA_CAMPAIGN_EDIT_GUARD_APPLIED_KEY = "_admira_campaign_edit_guard_applied"

# This registry is selected from backend-owned product state, never from words
# in the buyer message.  While the strategic profile is incomplete, the model
# receives the tools needed to connect accounts, inspect truth, conduct and
# persist onboarding, explore the brand, and stop spend.  Campaign production
# and paid-media mutation remain absent from the provider request in addition
# to the authoritative backend action gate.
ADMIRA_STRATEGIC_ONBOARDING_TOOLS = {
    "start_meta_oauth_connection",
    "get_meta_oauth_workspaces",
    "select_meta_oauth_workspace",
    "get_real_meta_context",
    "connect_chatgpt",
    "list_pending_approvals",
    "save_agent_preferences",
    "save_business_memory",
    "save_brand_memory",
    "save_product_memory",
    "save_ads_onboarding",
    "save_durable_memory",
    "fetch_public_asset",
    "list_recent_creatives",
    "save_content_asset",
    "save_creative_references",
    "import_product_catalog",
    "search_product_catalog",
    "codex_creative_plan",
    "codex_image_generate",
    "generate_motion_graphic_video",
    # A buyer must always be able to stop spend or reject an action even while
    # the profile is incomplete.  Approving/starting spend is intentionally
    # not included in this state.
    "pause_campaign",
    "delete_campaign",
    "reject_action",
}


def _admira_freeform_agent_mode():
    """Leave language interpretation to the model unless legacy mode is explicit."""
    configured = str(os.environ.get("ADMIRA_FREEFORM_AGENT_MODE") or "").strip().lower()
    if configured:
        return configured in {"1", "true", "yes", "on", "enabled"}
    root = Path(str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "/app").strip()).expanduser()
    marker = root / "runtime" / "freeform-agent-mode"
    try:
        return marker.read_text(encoding="utf-8").strip().lower() in {
            "1", "true", "yes", "on", "enabled"
        }
    except OSError:
        # Natural conversation is the product default.  A full reset may
        # legitimately remove the old runtime marker; that must not silently
        # reactivate legacy keyword routers and prose-replacement guards.
        return True


def _normalized_admira_mcp_name(tool_name):
    name = str(tool_name or "").strip()
    for prefix in ("mcp_admira_", "admira_"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return ""


def _remove_hermes_personal_state_tools(api_kwargs):
    """Keep product tools while removing Hermes' conflicting private stores."""
    if not isinstance(api_kwargs, dict):
        return api_kwargs
    request = dict(api_kwargs)
    tools = request.get("tools") if isinstance(request.get("tools"), list) else []
    disabled = {"clarify", "memory", "skill_manage", "skill_create", "skill_patch"}
    request["tools"] = [
        tool for tool in tools
        if str(_nvidia_tool_name(tool) or "").strip().lower() not in disabled
    ]
    return request


def _admira_read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


ADMIRA_BUSINESS_PROFILE_TOPICS = (
    "services",
    "ideal_customer",
    "differentiators",
    "markets",
    "capacity",
    "pricing",
    "margins",
    "global_objectives",
    "advertising_experience",
    "branding",
)

ADMIRA_BUSINESS_PROFILE_LABELS = {
    "services": "Services and products",
    "ideal_customer": "Ideal customer",
    "differentiators": "Differentiators and proof",
    "markets": "Markets and locations",
    "capacity": "Capacity and constraints",
    "pricing": "Prices",
    "margins": "Costs and margins",
    "global_objectives": "Global objectives",
    "advertising_experience": "Advertising experience",
    "branding": "Brand and assets",
}


def _admira_profile_topic_context(strategic):
    """Project canonical topic memory into a bounded provider-safe shape.

    The profile JSON remains the only owner of these values. This projection
    deliberately avoids creating duplicate business-name/location state: it
    merely makes the authoritative Page-scoped topics visible at the provider
    boundary, including remembered drafts that must not be asked again.
    """
    strategic = strategic if isinstance(strategic, dict) else {}
    topics = strategic.get("topics") if isinstance(strategic.get("topics"), dict) else {}
    snapshot = {}
    resolved = []
    drafts = []
    unresolved = []
    resolved_statuses = {
        "confirmed", "provisional_confirmed", "unknown", "not_applicable", "withheld",
    }
    for topic in ADMIRA_BUSINESS_PROFILE_TOPICS:
        entry = topics.get(topic) if isinstance(topics.get(topic), dict) else {}
        status = str(entry.get("status") or "").strip().lower()
        value = entry.get("value")
        if status in resolved_statuses:
            snapshot[topic] = {
                "status": status,
                "memory_state": "resolved",
                "value": value,
            }
            resolved.append(topic)
            continue
        draft = entry.get("draft") if isinstance(entry.get("draft"), dict) else {}
        draft_value = draft.get("value")
        # Compatibility with a short-lived writer that wrapped a canonical
        # update inside draft.value. Unwrap only for read-only context.
        if isinstance(draft_value, dict) and "value" in draft_value:
            draft_value = draft_value.get("value")
        if draft_value not in (None, "", [], {}):
            snapshot[topic] = {
                "status": str(draft.get("proposed_status") or "draft").strip().lower(),
                "memory_state": "remembered_draft",
                "value": draft_value,
            }
            drafts.append(topic)
            continue
        unresolved.append(topic)
    return snapshot, resolved, drafts, unresolved


def _admira_active_page_name(oauth, active_page_id):
    oauth = oauth if isinstance(oauth, dict) else {}
    wanted = str(active_page_id or "").strip()
    for page in oauth.get("pages") or []:
        if not isinstance(page, dict):
            continue
        if str(page.get("id") or "").strip() == wanted:
            return re.sub(r"\s+", " ", str(page.get("name") or "")).strip()[:240]
    return ""


def _admira_recent_generated_creatives(*, product_root=None, retention_days=3, limit=8):
    """Project recent generated image files into bounded provider context.

    This is factual continuity only.  A file on disk is not proof that the
    buyer selected or approved it for any campaign.  The provider-bound
    projection exists because weaker brains do not reliably decide to open the
    workspace inventory before answering a buyer who misremembers whether a
    creative was generated.
    """
    root = Path(
        str(product_root or os.environ.get("ADMIRA_PRODUCT_ROOT") or "/app").strip()
    ).expanduser()
    creative_root = root / "output" / "creatives"
    try:
        resolved_root = creative_root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return []
    try:
        retention_seconds = max(1, int(retention_days or 3)) * 86400
        bounded_limit = max(1, min(8, int(limit or 8)))
    except (TypeError, ValueError):
        retention_seconds = 3 * 86400
        bounded_limit = 8
    cutoff = time.time() - retention_seconds
    candidates = []
    for candidate in creative_root.glob("codex-*/*"):
        if not candidate.is_file() or candidate.suffix.lower() not in ADMIRA_IMAGE_EXTENSIONS:
            continue
        try:
            resolved = candidate.resolve(strict=True)
            asset_id = str(resolved.relative_to(resolved_root))
            stat = resolved.stat()
        except (OSError, RuntimeError, ValueError):
            # Exclude broken links and any symlink escaping the product output
            # root; only backend-owned generated files may enter this context.
            continue
        if stat.st_mtime < cutoff:
            continue
        candidates.append((stat.st_mtime, {
            "asset_id": asset_id,
            "file_name": resolved.name,
            "created_at": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(timespec="seconds"),
            "approval_state": "file_exists_only_not_campaign_approval",
        }))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [item for _mtime, item in candidates[:bounded_limit]]


def _admira_strategic_profile_state(*, product_root=None):
    """Read the authoritative strategic-onboarding state owned by Admira.

    The language model cannot set this state through prompt text.  The
    dashboard memory file is the canonical source; the generated Hermes copy
    is only a read-only fallback for startup races.  A Page-scoped profile is
    complete only for the currently bound Page and, when revision metadata is
    present, only for its confirmed current revision.
    """
    root = Path(
        str(product_root or os.environ.get("ADMIRA_PRODUCT_ROOT") or "/app").strip()
    ).expanduser()
    profile = {}
    source = ""
    for candidate in (
        root / "dashboard" / "data" / "business_profile.json",
        root / "dashboard" / "data" / "hermes-workspace" / "current" / "data" / "business_profile.json",
    ):
        profile = _admira_read_json(candidate)
        if profile:
            source = str(candidate)
            break

    strategic = profile.get("strategic_profile") if isinstance(profile, dict) else {}
    if not isinstance(strategic, dict):
        strategic = {}
    status = str(strategic.get("status") or "empty").strip().lower()
    if status not in {"empty", "collecting", "review_required", "complete", "scope_mismatch"}:
        status = "collecting"

    revision = strategic.get("revision")
    confirmed_revision = strategic.get("confirmed_revision")
    review = strategic.get("review") if isinstance(strategic.get("review"), dict) else {}
    if confirmed_revision in (None, ""):
        confirmed_revision = review.get("confirmed_revision")

    oauth = _admira_read_json(root / "dashboard" / "data" / "meta_oauth_connection.json")
    binding = _admira_read_json(root / "dashboard" / "data" / "individual_business_binding.json")
    # OAuth owns the active Meta workspace.  The older individual-business
    # binding remains a startup/migration fallback only, otherwise a recent
    # OAuth Page switch could disagree with the provider-visible tool gate.
    active_page_id = str(oauth.get("active_page_id") or "").strip()
    bound_page_id = active_page_id or str(binding.get("page_id") or "").strip()
    scope = strategic.get("scope") if isinstance(strategic.get("scope"), dict) else {}
    scope_page_id = str(scope.get("page_id") or strategic.get("page_id") or "").strip()
    if bound_page_id and scope_page_id and bound_page_id != scope_page_id:
        status = "scope_mismatch"

    revision_matches = (
        revision not in (None, "")
        and confirmed_revision not in (None, "")
        and str(revision) == str(confirmed_revision)
    )
    scope_matches = bool(scope_page_id) and (
        not bound_page_id or scope_page_id == bound_page_id
    )
    complete = status == "complete" and revision_matches and scope_matches

    # The profile is the onboarding baseline; the strategic plan is a separate
    # Page-scoped artifact.  Keep this read-only projection in the runtime so
    # the model sees the same lifecycle after a restart/provider switch.  The
    # dashboard remains the authority for writing it.
    plans = profile.get("business_master_plans") if isinstance(profile, dict) else {}
    if not isinstance(plans, dict):
        plans = {}
    plan_page_id = str(scope_page_id or bound_page_id or profile.get("active_strategic_page_id") or "").strip()
    plan = plans.get(plan_page_id) if plan_page_id else None
    if not isinstance(plan, dict):
        plan = {}
    plan_status = str(plan.get("status") or "missing").strip().lower()
    if plan_status in {"draft", "proposed", "proposal", "pending", "review_required"}:
        plan_status = "proposed"
    elif plan_status not in {"confirmed", "stale", "missing"}:
        plan_status = "missing"
    required_plan_fields = (
        "advertising_opportunity", "audience_and_message",
        "campaign_and_creative_plan", "budget_and_measurement",
        "next_steps_and_questions",
    )
    selected_plan_content = plan.get("content") if plan_status == "confirmed" else plan.get("draft")
    if plan_status in {"confirmed", "proposed"} and not (
        isinstance(selected_plan_content, dict)
        and all(selected_plan_content.get(field) not in (None, "", [], {}) for field in required_plan_fields)
    ):
        # Current releases never persist partial plans. Treat an old partial
        # record as missing rather than injecting it as final direction.
        plan_status = "missing"
    # profile_revision is provenance only. A newly learned business fact must
    # not silently invalidate an already approved plan. The backend may mark a
    # plan stale explicitly only after the buyer directly requests a plan
    # change/review.
    if not complete:
        lifecycle_state = "onboarding"
    elif plan_status == "confirmed":
        lifecycle_state = "active_with_confirmed_strategic_plan"
    else:
        lifecycle_state = "active_without_confirmed_strategic_plan"
    plan_content = plan.get("content") if plan_status == "confirmed" else plan.get("draft")
    if plan_status == "stale" and not plan_content:
        plan_content = plan.get("content")
    if plan_status == "missing":
        # Never inject an obsolete broad plan after the compact advertising
        # contract ships. The next bound turn atomically replaces it; until
        # then it is treated as missing rather than conversational context.
        plan_content = {}
    if not isinstance(plan_content, dict):
        plan_content = {}
    topic_context, resolved_topics, draft_topics, unresolved_topics = (
        _admira_profile_topic_context(strategic)
    )
    review_ready = strategic.get("review_ready") if isinstance(strategic.get("review_ready"), dict) else {}
    review_presentation = (
        strategic.get("review_presentation")
        if isinstance(strategic.get("review_presentation"), dict)
        else {}
    )
    return {
        "status": status,
        "complete": complete,
        "revision": revision,
        "confirmed_revision": confirmed_revision,
        "scope_page_id": scope_page_id,
        "bound_page_id": bound_page_id,
        "source": source,
        "lifecycle_state": lifecycle_state,
        "master_plan_status": plan_status,
        "master_plan_page_id": plan_page_id,
        "master_plan_revision": plan.get("revision"),
        "master_plan_profile_revision": plan.get("profile_revision"),
        "master_plan": plan_content,
        "active_page_name": _admira_active_page_name(oauth, bound_page_id),
        "business_profile_topics": topic_context,
        "business_profile_resolved_topics": resolved_topics,
        "business_profile_draft_topics": draft_topics,
        "business_profile_unresolved_topics": unresolved_topics,
        "business_profile_review_ready": bool(
            review_ready and str(review_ready.get("revision")) == str(revision)
        ),
        "business_profile_review_presented": bool(
            review_presentation
            and str(review_presentation.get("revision")) == str(revision)
        ),
        "recent_generated_creatives": _admira_recent_generated_creatives(
            product_root=root
        ),
    }


def _admira_render_business_profile(state, *, max_chars=12000):
    """Render known onboarding facts without trusting the model to read files."""
    state = state if isinstance(state, dict) else {}
    topics = state.get("business_profile_topics")
    topics = topics if isinstance(topics, dict) else {}
    active_page_name = re.sub(
        r"\s+", " ", str(state.get("active_page_name") or "")
    ).strip()
    lines = []
    if active_page_name:
        lines.append(f"- Active Meta Page name: {active_page_name}")
    per_topic = max(280, (max_chars - 900) // max(1, len(ADMIRA_BUSINESS_PROFILE_TOPICS)))
    for topic in ADMIRA_BUSINESS_PROFILE_TOPICS:
        entry = topics.get(topic) if isinstance(topics.get(topic), dict) else None
        if not entry:
            continue
        value = entry.get("value")
        rendered = value if isinstance(value, str) else json.dumps(
            value, ensure_ascii=False, sort_keys=True
        )
        rendered = re.sub(r"\s+", " ", str(rendered or "")).strip()
        if len(rendered) > per_topic:
            tail = max(100, per_topic // 4)
            head = max(140, per_topic - tail - 18)
            rendered = f"{rendered[:head].rstrip()} … {rendered[-tail:].lstrip()}"
        lines.append(
            f"- {ADMIRA_BUSINESS_PROFILE_LABELS[topic]} "
            f"[{entry.get('memory_state')}/{entry.get('status')}]: {rendered or '(explicitly unresolved)'}"
        )
    unresolved = state.get("business_profile_unresolved_topics") or []
    drafts = state.get("business_profile_draft_topics") or []
    lines.append(
        "- Genuinely unresolved topics: "
        + (", ".join(str(item) for item in unresolved) if unresolved else "none")
    )
    lines.append(
        "- Remembered draft topics awaiting correction/confirmation (not missing): "
        + (", ".join(str(item) for item in drafts) if drafts else "none")
    )
    return "\n".join(lines) if lines else "(No Page-scoped business facts are stored yet.)"


def _admira_render_master_plan(state, *, max_chars=3600):
    """Render the compact advertising direction within a small context budget."""
    state = state if isinstance(state, dict) else {}
    content = state.get("master_plan") if isinstance(state.get("master_plan"), dict) else {}
    if not content:
        return "(No hay plan estratégico guardado todavía.)"
    labels = {
        "advertising_opportunity": "Oportunidad publicitaria",
        "audience_and_message": "Audiencia y mensaje",
        "campaign_and_creative_plan": "Campaña y conceptos creativos",
        "budget_and_measurement": "Presupuesto y medición",
        "next_steps_and_questions": "Próximos pasos para pulirlo",
    }
    ordered_fields = (
        "advertising_opportunity", "audience_and_message",
        "campaign_and_creative_plan", "budget_and_measurement",
        "next_steps_and_questions",
    )
    # Divide the budget across fields rather than slicing the combined string,
    # so one long section cannot hide the remaining advertising direction.
    per_field = max(420, (max_chars - 900) // len(ordered_fields))

    def bounded(value):
        rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
        rendered = re.sub(r"\s+", " ", str(rendered or "")).strip()
        if len(rendered) <= per_field:
            return rendered
        tail = max(120, per_field // 3)
        head = max(120, per_field - tail - 18)
        return f"{rendered[:head].rstrip()} … {rendered[-tail:].lstrip()}"

    lines = []
    for key in ordered_fields:
        value = content.get(key)
        label = labels.get(str(key), str(key).replace("_", " ").capitalize())
        lines.append(f"- {label}: {bounded(value) if value not in (None, '', [], {}) else '(pendiente)'}")
    text = "\n".join(lines) or "(No hay plan estratégico guardado todavía.)"
    return text


def _admira_render_recent_creatives(state):
    """Render existence evidence without leaking paths or inferring approval."""
    items = (state or {}).get("recent_generated_creatives")
    items = items if isinstance(items, list) else []
    if not items:
        return "- none found in the recent generated-output window"
    lines = []
    for item in items[:8]:
        if not isinstance(item, dict):
            continue
        asset_id = re.sub(r"\s+", " ", str(item.get("asset_id") or "")).strip()
        created_at = re.sub(r"\s+", " ", str(item.get("created_at") or "")).strip()
        if not asset_id:
            continue
        lines.append(
            f"- asset_id={asset_id}; created_at={created_at or 'unknown'}; "
            "approval_state=file_exists_only_not_campaign_approval"
        )
    return "\n".join(lines) or "- none found in the recent generated-output window"


def _admira_constrain_onboarding_media_tool(tool):
    """Keep only non-ad Image planning/production visible during onboarding."""
    if not isinstance(tool, dict):
        return tool
    name = _nvidia_normalize_tool_name(_nvidia_tool_name(tool))
    if name not in {
        "codex_image_generate",
        "codex_creative_plan",
        "generate_motion_graphic_video",
    }:
        return tool
    cloned = copy.deepcopy(tool)
    function = cloned.get("function") if isinstance(cloned.get("function"), dict) else cloned
    parameters = function.get("parameters") if isinstance(function, dict) else None
    properties = parameters.get("properties") if isinstance(parameters, dict) else None
    purpose = properties.get("purpose") if isinstance(properties, dict) else None
    if isinstance(purpose, dict):
        purpose["enum"] = [
            "logo",
            "brand_exploration",
            "moodboard",
            "brand_sample",
        ]
        purpose["description"] = (
            "Only logo candidates, brand exploration, moodboards, or brand samples while onboarding "
            "is incomplete. Organic and paid production remain unavailable until branding is confirmed."
        )
    if isinstance(function, dict):
        existing = str(function.get("description") or "").strip()
        function["description"] = (
            "During onboarding this tool is limited to logo candidates, brand exploration, "
            "moodboards, or brand samples. " + existing
        ).strip()
    return cloned


def _admira_compact_tool_description(tool):
    """Remove the obsolete read-a-skill ceremony from provider schemas."""
    if not isinstance(tool, dict):
        return tool
    cloned = copy.deepcopy(tool)
    function = cloned.get("function") if isinstance(cloned.get("function"), dict) else cloned
    if not isinstance(function, dict):
        return cloned
    description = str(function.get("description") or "")
    if description:
        description = re.sub(
            r"^MANDATORY PRIMARY PROCEDURE:\s*read\s+`skills/[^`]+/SKILL\.md`\s+"
            r"completely before calling this MCP\.\s*Reading it does not itself authorize execution\.\s*",
            "",
            description,
            flags=re.IGNORECASE,
        ).strip()
        function["description"] = description
    parameters = function.get("parameters")
    if isinstance(parameters, dict):
        def compact_schema(value):
            if isinstance(value, list):
                return [compact_schema(item) for item in value]
            if not isinstance(value, dict):
                return value
            result = {}
            for key, item in value.items():
                if key == "description" and isinstance(item, str) and len(item) > 240:
                    result[key] = item[:237].rstrip() + "…"
                else:
                    result[key] = compact_schema(item)
            return result
        function["parameters"] = compact_schema(parameters)
    return cloned


def _admira_route_tools_by_product_state(api_kwargs, *, state=None):
    """Filter every provider's catalog by trusted product state, not wording."""
    if not isinstance(api_kwargs, dict):
        return api_kwargs
    request = dict(api_kwargs)
    tools = request.get("tools") if isinstance(request.get("tools"), list) else []
    state = dict(state or _admira_strategic_profile_state())
    routed = _nvidia_restore_admira_tool_schemas(tools)
    if not state.get("complete"):
        filtered = []
        for tool in routed:
            name = _nvidia_tool_name(tool)
            normalized = _nvidia_normalize_tool_name(name)
            is_admira = name.lower().startswith(("mcp_admira_", "admira_"))
            if not is_admira:
                filtered.append(tool)
            elif normalized in ADMIRA_STRATEGIC_ONBOARDING_TOOLS:
                filtered.append(_admira_constrain_onboarding_media_tool(tool))
        routed = filtered
        # A forced choice can refer to a tool that disappeared with the state
        # transition.  Let the model continue conversationally instead.
        chosen = request.get("tool_choice")
        chosen_name = ""
        if isinstance(chosen, dict):
            chosen_function = chosen.get("function")
            if isinstance(chosen_function, dict):
                chosen_name = _nvidia_normalize_tool_name(chosen_function.get("name"))
        visible_names = {
            _nvidia_normalize_tool_name(_nvidia_tool_name(item)) for item in routed
        }
        if chosen_name and chosen_name not in visible_names:
            request.pop("tool_choice", None)
            request.pop("parallel_tool_calls", None)
    request["tools"] = [_admira_compact_tool_description(tool) for tool in routed]
    if not request["tools"]:
        request.pop("tools", None)
    return request


def _admira_compiled_procedure_instruction(state):
    status = str((state or {}).get("status") or "empty")
    revision = (state or {}).get("revision")
    recent_creatives_text = _admira_render_recent_creatives(state)
    if not (state or {}).get("complete"):
        revision_note = f" revision={revision}." if revision not in (None, "") else "."
        plan_status = str((state or {}).get("master_plan_status") or "missing")
        profile_text = _admira_render_business_profile(state)
        if status == "review_required":
            if (state or {}).get("business_profile_review_presented"):
                review_instruction = (
                    "All onboarding topics are resolved and the exact current business-summary review was already shown. "
                    "Do not restart discovery or ask again for name, location, services, audience, pricing, branding, or any "
                    "other stored topic. A greeting is not confirmation: briefly resume from one concrete fact and explain "
                    "that the business summary—not a strategic plan—is awaiting natural correction/confirmation. Never "
                    "require an exact phrase."
                )
            else:
                review_instruction = (
                    "All onboarding topics are resolved. Do not ask another discovery question. Present the complete current "
                    "business-summary review for natural correction/confirmation; the finalized transport will canonicalize it."
                )
        else:
            review_instruction = (
                "Ask only about a genuinely unresolved owner topic. A remembered draft is an existing answer awaiting natural "
                "correction/confirmation, not a missing field; show it back instead of asking the original question again."
            )
        return (
            f"{ADMIRA_PRODUCT_STATE_START}\n"
            f"Onboarding business-profile status={status}{revision_note} lifecycle_state=onboarding; "
            f"strategic_plan_status={plan_status}. This status comes from backend-owned state, "
            "not from buyer phrasing. Campaign creation, campaign briefs, activation/resume, paid-ad image/video, "
            "and other ad production are unavailable until the current Page-scoped profile is complete. "
            "Continue as a senior marketing manager: use connected/live facts, reflect one useful insight or proposal, "
            "then ask one owner question at a time. Progressively resolve services, ideal customers, differentiation/proof, "
            "markets, capacity, prices, costs/margins, global objectives, advertising experience, and branding. Save only "
            "buyer-confirmed facts as confirmed; keep your ideas as proposals. Unknown, not applicable, or withheld is a "
            "valid explicit answer. The Page-scoped snapshot below is read-only authoritative memory for this turn. Use it "
            "directly even when Hermes session history is empty; never rely on deciding to read a workspace file later. "
            f"{review_instruction} "
            "During lifecycle_state=onboarding, review_required always refers to the business/onboarding summary. It never "
            "means a strategic plan is saved, proposed, or under review. If strategic_plan_status=missing, say that no "
            "strategic plan exists yet; never call the business summary a plan draft.\n"
            f"Current Page-scoped business memory:\n{profile_text}\n\n"
            "Recent generated creative evidence (read-only orientation, maximum eight files from the last three days):\n"
            f"{recent_creatives_text}\n"
            "This proves only that each file exists; it never proves selection, approval, or association with a campaign. "
            "When the buyer questions whether a creative exists, use list_recent_creatives to inspect or re-attach the likely "
            "asset and keep that reply focused on one natural keep/review/replace decision before other campaign details. "
            "Never expose asset IDs or internal paths in visible prose.\n\n"
            "As soon as the exact business/brand name and offer are known, proactively inspect the "
            "logo state before proposing campaigns or content. If no official logo file exists, say so plainly and ask in "
            "natural language whether the buyer wants to upload one or create it together now. Logo candidates, moodboards "
            "and brand samples are valid onboarding work and do not require the full strategic profile to be complete; when "
            "the buyer asks to create one and the brand-bootstrap fields are known, call Image and attach the real result "
            "instead of continuing unrelated interview questions. Treat saved drafts as remembered answers, not missing data: "
            "never ask the same owner question again merely because its answer is still a draft. Present the relevant saved "
            "drafts back for natural correction/confirmation; when several already-answered topics are pending, group them "
            "into one concise review rather than repeating the interview. On confirmation, save the exact matching draft "
            "values together as buyer_confirmed. For every memory save, copy the buyer's complete current message exactly into "
            "buyer_evidence; do not paraphrase it. A short confirmation can promote only the matching draft already shown. "
            "When every topic is resolved, present the complete canonical business-summary review returned by the tool for natural "
            "confirmation/correction; call this the onboarding/business summary, not the strategic plan. Do not omit values or mark it complete yourself.\n"
            f"{ADMIRA_PRODUCT_STATE_END}\n"
            f"{ADMIRA_COMPILED_PROCEDURE_START}\n"
            "The relevant onboarding procedure is precompiled here. Do not call read_file merely to unlock an MCP. "
            "Use ordinary conversational text, never clarify/cards. Use the visible tool schema and backend result "
            "as execution truth. Strategic advice is proactive, but it is not mutation authorization.\n"
            f"{ADMIRA_COMPILED_PROCEDURE_END}"
        )
    lifecycle = str((state or {}).get("lifecycle_state") or "active_without_confirmed_strategic_plan")
    plan_status = str((state or {}).get("master_plan_status") or "missing")
    plan_text = _admira_render_master_plan(state)
    if plan_status == "confirmed":
        plan_instruction = (
            "The compact advertising plan is confirmed and must be actively considered in every turn. Reuse it; never ask to "
            "reconfirm the onboarding business summary or the plan. New services, facts, campaigns, results or ordinary "
            "conversation never modify or invalidate it. Only when the buyer directly asks to update the saved strategic "
            "plan may you open and discuss a revised draft; that revision becomes final only after a later natural confirmation.\n"
        )
    elif plan_status == "proposed":
        plan_instruction = (
            "A compact advertising-plan draft is already saved and visible in this turn. Do not regenerate or demand "
            "confirmation. Discuss it naturally with the buyer and use the normal conversational model to refine only the "
            "parts they directly question or change. It may remain a draft while campaign or creative work continues.\n"
        )
    else:
        plan_instruction = (
            "The onboarding business summary is complete, but no compact advertising-plan draft is stored yet. The initial "
            "proposal belongs to the isolated Sol-low compiler, grounded in relevant confirmed business facts and a fresh "
            "Meta snapshot. Do not draft, abbreviate, save, or present a substitute yourself. If it is temporarily "
            "unavailable, say so briefly and continue the buyer's safe conversational request without calling the business "
            "summary a plan or asking to reconfirm it. Once strategic_plan_status becomes proposed, use the exact canonical "
            "draft supplied by backend state.\n"
        )
    if plan_status == "confirmed":
        foundation_instruction = (
            "Continue with the buyer-confirmed brand foundation before organic or paid production: exact name, approved logo "
            "or explicit no-logo choice, palette, visual style, tone, references and real assets. Image may create real logo "
            "candidates, moodboards and brand samples during this phase; attach the file and save it as official only after "
            "natural buyer approval. Backend brand readiness remains authoritative.\n"
        )
    elif plan_status == "missing":
        foundation_instruction = (
            "The next lifecycle step is for the isolated compiler to materialize the compact advertising proposal and then let the "
            "buyer discuss it. Do not branch into a generic branding or campaign setup interview and do not reproduce the "
            "compiler's job in prose. Branding work can still be handled when the buyer explicitly requests it.\n"
        )
    else:
        foundation_instruction = (
            "The strategic plan may remain a draft without blocking ordinary creative, campaign or analysis work. Continue "
            "with the buyer's current request and the buyer-confirmed brand foundation; do not force another plan review.\n"
        )
    return (
        f"{ADMIRA_PRODUCT_STATE_START}\n"
        f"The current Page-scoped onboarding/business profile is complete; lifecycle_state={lifecycle}, master_plan_status={plan_status}.\n"
        f"{plan_instruction}"
        f"Current compact advertising-plan artifact (read-only context for this turn):\n{plan_text}\n\n"
        "Meta live inventory and performance reads are authoritative for current campaigns, delivery, spend, and results; "
        "saved briefs or plan KPI assumptions never override live Meta data.\n"
        "Recent generated creative evidence (read-only orientation, maximum eight files from the last three days):\n"
        f"{recent_creatives_text}\n"
        "This inventory proves only that each file exists. It never proves selection, approval, or association with the "
        "current campaign. When its relevance is uncertain, use list_recent_creatives to inspect or re-attach the likely "
        "asset, then reconcile it naturally with the buyer before proposing another creative. Never expose asset IDs or "
        "internal paths in visible prose.\n"
        f"{foundation_instruction}"
        f"{ADMIRA_PRODUCT_STATE_END}\n"
        f"{ADMIRA_COMPILED_PROCEDURE_START}\n"
        "Official procedures are precompiled into the root contract and tool descriptions. Do not call read_file merely "
        "to unlock an MCP. Use ordinary conversational text, never clarify/cards. Choose the smallest tool by semantic "
        "outcome, follow its current schema, and treat its result as truth. For each genuinely new paid campaign, do not "
        "inherit another campaign's budget, currency, audience, geography, offer, copy, title, destination message, CTA, "
        "or creative. First develop the commercial direction with the buyer. Before image/video production, show the exact "
        "primary text, distinct title, CTA/destination message, and visual concept for natural correction or approval. "
        "Before campaign creation, the current budget/currency and exact delivered creative must also be resolved and visible. "
        "A campaign request or budget answer alone authorizes none of those missing values. When the buyer questions or "
        "corrects whether a campaign input—especially its creative—already exists, do not accept either the buyer's statement "
        "or old memory blindly. Reconcile the current campaign brief with verifiable recent assets; use list_recent_creatives "
        "when the exact asset is not already visible. Distinguish an existing file from a creative selected and approved for "
        "this exact campaign. If a relevant asset exists, show or re-attach it and ask whether to keep it or prepare another; "
        "if none exists, say so and propose creating one. Resolve that discrepancy before returning to budget, audience, offer, "
        "or execution. Keep that reply focused on the creative evidence and one natural keep/review/replace question; do not "
        "mix budget, audience, service, location, or execution questions into the same reply. Never generate or mutate merely "
        "to settle it. A successful PAUSED creation must "
        "include real campaign/ad-set/ad IDs; activation, spend, publishing, destructive work, and other protected mutations "
        "still follow the backend approval contract.\n"
        f"{ADMIRA_COMPILED_PROCEDURE_END}"
    )


def _admira_attach_compiled_procedure(api_kwargs, *, state=None):
    if not isinstance(api_kwargs, dict):
        return api_kwargs
    request = dict(api_kwargs)
    instruction = _admira_compiled_procedure_instruction(
        state or _admira_strategic_profile_state()
    )
    # Hermes has already converted a Codex/OpenAI subscription request to the
    # Responses API by the time this provider-boundary patch runs.  Such a
    # request contains ``input`` + ``instructions`` and must never receive a
    # Chat Completions-only ``messages`` keyword: openai.responses.create()
    # rejects it before authentication/network I/O.  Preserve the native
    # payload and extend its system instructions instead.
    if "input" in request and "messages" not in request:
        existing = str(request.get("instructions") or "").strip()
        if ADMIRA_PRODUCT_STATE_START not in existing:
            request["instructions"] = f"{existing}\n\n{instruction}".strip()
        return request
    messages = request.get("messages") if isinstance(request.get("messages"), list) else []
    if any(
        ADMIRA_PRODUCT_STATE_START in str(item.get("content") or "")
        for item in messages if isinstance(item, dict)
    ):
        return request
    request["messages"] = _nvidia_append_private_instruction(
        messages,
        instruction,
    )
    return request


def _admira_compact_receipt_payload(value):
    """Retain only durable facts from a tool result already consumed."""
    if not isinstance(value, dict):
        return {}
    keep = {
        "ok", "success", "executed", "status", "reason", "error", "message",
        "selected", "verified_persisted", "changed", "created", "campaign_id",
        "campaign_ids", "adset_id", "adset_ids", "ad_id", "ad_ids",
        "lead_gen_form_id", "page_id", "ad_account_id", "currency", "timezone",
        "image_path", "media_attachment", "video_path", "approval_id", "next_step",
        "campaign_creation_verified", "meta_creation_verified", "final_status",
        "graph_readback_verified", "graph_http_statuses",
    }
    receipt = {key: value[key] for key in keep if key in value}
    nested = value.get("result")
    if isinstance(nested, dict):
        compact_nested = {key: nested[key] for key in keep if key in nested}
        if compact_nested:
            receipt["result"] = compact_nested
    return receipt


def _admira_compact_consumed_observations(messages):
    """Prune old skill dumps and oversized MCP receipts after a buyer turn."""
    if not isinstance(messages, list):
        return messages
    latest_user = max(
        (index for index, item in enumerate(messages)
         if isinstance(item, dict) and str(item.get("role") or "").lower() == "user"),
        default=-1,
    )
    if latest_user <= 0:
        return messages

    calls = {}
    for item in messages[:latest_user]:
        if not isinstance(item, dict) or str(item.get("role") or "").lower() != "assistant":
            continue
        for call in item.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            function = call.get("function") if isinstance(call.get("function"), dict) else {}
            calls[str(call.get("id") or "")] = {
                "name": str(function.get("name") or ""),
                "arguments": str(function.get("arguments") or ""),
            }

    compacted = list(messages)
    for index, item in enumerate(messages[:latest_user]):
        if not isinstance(item, dict) or str(item.get("role") or "").lower() != "tool":
            continue
        call = calls.get(str(item.get("tool_call_id") or ""), {})
        tool_name = str(item.get("name") or item.get("tool_name") or call.get("name") or "")
        arguments = str(call.get("arguments") or "")
        content = item.get("content")
        serialized = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)
        is_skill_read = (
            _nvidia_normalize_tool_name(tool_name) == "read_file" or tool_name == "read_file"
        ) and "SKILL.md" in arguments
        is_admira = tool_name.lower().startswith(("mcp_admira_", "admira_"))
        if is_skill_read:
            replacement = {
                "ok": True,
                "procedure_loaded": Path(arguments.split("SKILL.md", 1)[0]).name or "official-skill",
                "note": "Procedure is represented by the current compiled guidance.",
            }
        elif is_admira and len(serialized) > 1800:
            try:
                parsed = json.loads(serialized)
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = {}
            replacement = _admira_compact_receipt_payload(parsed)
            if not replacement:
                replacement = {
                    "ok": True,
                    "tool": _nvidia_normalize_tool_name(tool_name),
                    "note": "Previous detailed result was consumed; refresh live state if current truth is needed.",
                }
        else:
            continue
        clone = dict(item)
        clone["content"] = json.dumps(replacement, ensure_ascii=False, separators=(",", ":"))
        compacted[index] = clone
    return compacted


def _session_has_read_primary_skill(session_id, skill_path, *, state_db_path=None):
    session = str(session_id or "").strip()
    expected = str(skill_path or "").strip().replace("\\", "/")
    if not session or not expected:
        return False
    if state_db_path is None:
        root = Path(str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "/app").strip()).expanduser()
        state_db_path = root / "runtime" / "hermes" / "state.db"
    connection = None
    try:
        connection = sqlite3.connect(str(state_db_path), timeout=1.0)
        rows = connection.execute(
            "SELECT tool_calls FROM messages "
            "WHERE session_id = ? AND role = 'assistant' AND tool_calls IS NOT NULL "
            "ORDER BY id DESC LIMIT 120",
            (session,),
        ).fetchall()
    except (OSError, sqlite3.Error):
        return False
    finally:
        try:
            if connection is not None:
                connection.close()
        except Exception:
            pass
    for (raw_calls,) in rows:
        try:
            calls = json.loads(raw_calls or "[]")
        except (TypeError, ValueError):
            continue
        for call in calls if isinstance(calls, list) else []:
            function = call.get("function") if isinstance(call, dict) else None
            if not isinstance(function, dict) or function.get("name") != "read_file":
                continue
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except (TypeError, ValueError):
                continue
            path = str(arguments.get("path") or "").replace("\\", "/")
            if path == expected or path.endswith("/" + expected):
                return True
    return False
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
ADMIRA_CHATGPT_LOGIN_PENDING_TTL_SECONDS = 20 * 60
ADMIRA_CHATGPT_LOGIN_CONFIRMATION_RE = re.compile(
    r"(?i)^\s*(?:listo|hecho|ya\s+(?:est[aá]|qued[oó]|lo\s+hice|termin[eé])|"
    r"termin[eé]|complet[eé]|done|finished|completed)\s*[.!✅]*\s*$"
)
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
ADMIRA_CAMPAIGN_CREATION_TOOL_MARKERS = (
    "mcp_admira_create_whatsapp_campaign",
    "mcp_admira_create_lead_form_campaign",
    "mcp_admira_create_website_campaign",
    "mcp_admira_create_messaging_campaign",
    "mcp_admira_create_app_campaign",
    "mcp_admira_create_on_meta_campaign",
    "admira_create_whatsapp_campaign",
    "admira_create_lead_form_campaign",
    "admira_create_website_campaign",
    "admira_create_messaging_campaign",
    "admira_create_app_campaign",
    "admira_create_on_meta_campaign",
)
ADMIRA_CAMPAIGN_EDIT_TOOL_MARKERS = (
    "mcp_admira_edit_campaign",
    "admira_edit_campaign",
    "mcp_admira_stage_budget_change",
    "admira_stage_budget_change",
    "mcp_admira_pause_campaign",
    "admira_pause_campaign",
    "mcp_admira_resume_campaign",
    "admira_resume_campaign",
)
ADMIRA_CAMPAIGN_SUCCESS_CLAIM_RE = re.compile(
    r"(?i)(?:\b(?:cre[eé]|creada|creado|configurad[ao]|qued[oó]|dej[eé])\b.{0,80}\b(?:campa[nñ]a|pausa|paused)\b|"
    r"\b(?:campa[nñ]a|estructura)\b.{0,80}\b(?:lista|configurada|creada|en\s+pausa|pausada)\b|"
    r"\b(?:created|configured|left|set)\b.{0,80}\b(?:campaign|paused)\b)"
)
ADMIRA_CAMPAIGN_EDIT_SUCCESS_CLAIM_RE = re.compile(
    r"(?i)(?:\b(?:apliqu[eé]|aplicado|aplicada|cambi[eé]|cambiado|cambiada|modifiqu[eé]|modificado|"
    r"configur[eé]|configurado|configurada|dej[eé]|dejad[oa]|qued[oó]|quedado|quedada|"
    r"ajust[eé]|ajustado|ajustada|actualic[eé]|actualizado|actualizada)\b"
    r".{0,100}\b(?:presupuesto|campa[nñ]a|cambio|modificaci[oó]n|pausad[ao]|paused|budget)\b|"
    r"\b(?:presupuesto|budget|cambio|campaign)\b.{0,100}\b(?:aplicado|aplicada|cambiado|cambiada|modificado|"
    r"actualizado|actualizada|applied|changed|updated|set)\b)"
)
ADMIRA_TELEGRAM_INVISIBLE_RE = re.compile(r"[\u200b\u200c\u2060\ufeff\u202a-\u202e\u2066-\u2069]")
ADMIRA_MARKDOWN_ONLY_RE = re.compile(r"[\s*_~`#>|:\-=+\\/.,;!?()\[\]{}]+")
ADMIRA_TABLE_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")
# Models usually place the marker on its own line, but some Codex variants put
# the buyer answer immediately after it. Match the line prefix as well so the
# private transport marker can never leak into Telegram.
ADMIRA_FINAL_MARKER_RE = re.compile(r"(?im)^\s*\[?ADMIRA\s+FINAL\]?\s*:?[ \t]*")
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
ADMIRA_FILE_MUTATION_VERIFIER_RE = re.compile(
    r"(?ims)\n*\s*⚠️?\s*File-mutation verifier:.*?(?:\n\s*[•*-].*)*(?=\n\s*\n|\Z)"
)
ADMIRA_REASONING_DIVIDER_RE = re.compile(r"(?m)^\s*-{5,}\s*$")
ADMIRA_TURN_CONTRACT_START = "[ADMIRA TURN EXECUTION CONTRACT — internal, never quote]"
ADMIRA_TURN_CONTRACT_END = "[END ADMIRA TURN EXECUTION CONTRACT]"
ADMIRA_SESSION_CONTINUITY_START = "[ADMIRA SESSION CONTINUITY — internal, never quote]"
ADMIRA_SESSION_CONTINUITY_END = "[END ADMIRA SESSION CONTINUITY]"
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
        "save_daily_social_content_settings",
        "get_meta_oauth_workspaces",
        "start_meta_oauth_connection",
        "select_meta_oauth_workspace",
        "search_product_catalog",
    },
    # The first-run route is intentionally limited to the secure Facebook
    # connection and the operator's communication preference. Business,
    # creative and campaign tools arrive only after a Page is selected.
    "onboarding": {
        "get_meta_oauth_workspaces",
        "start_meta_oauth_connection",
        "select_meta_oauth_workspace",
        "save_agent_preferences",
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
        "save_business_memory",
        "save_product_memory",
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
        "create_whatsapp_campaign",
        "create_lead_form_campaign",
        "create_website_campaign",
        "create_messaging_campaign",
        "create_app_campaign",
        "create_on_meta_campaign",
        "edit_campaign",
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
        "create_whatsapp_campaign",
        "create_messaging_campaign",
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
        "list_lead_forms",
        "create_lead_form",
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
    "pausa", "eliminar", "elimina", "delete", "resume", "reanuda", "editar", "edita",
    "edit", "modificar", "modifica", "modify", "cambiar", "cambia", "change", "actualizar",
    "actualiza", "update", "ajustar", "ajusta", "reemplazar", "reemplaza", "replace",
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
ADMIRA_CAMPAIGN_EDIT_ACTION_TERMS = (
    "editar", "edita", "edit", "modificar", "modifica", "modify", "cambiar", "cambia",
    "change", "actualizar", "actualiza", "update", "ajustar", "ajusta", "replace",
    "reemplazar", "reemplaza", "quita", "quitar", "añade", "anade", "agrega", "sube",
    "baja", "reduce", "aumenta", "pon", "poner", "usa", "usar", "deja", "dejar",
    "cambiale", "cámbiale", "ajustale", "ajústale",
)
ADMIRA_NVIDIA_MEDIA_PRODUCTION_TERMS = (
    "genera", "generar", "generate", "diseña", "disena", "diseñar", "disenar",
    "design", "produce", "producir", "renderiza", "renderizar", "image 2",
    "codex image", "crear imágenes", "crear imagen", "crear creativo", "crear ese creativo",
    "create images", "create image", "create creative",
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
    text = ADMIRA_FILE_MUTATION_VERIFIER_RE.sub("", text)
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


def _strip_technical_preamble(value):
    """Remove leaked local-tool diagnostics before buyer-facing delivery."""
    lines = str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    kept = []
    skipping = False
    removed = False
    for line in lines:
        normalized = line.strip()
        lowered = normalized.lower()
        starts_noise = (
            "tirith security scanner" in lowered
            or lowered in {"┊ review diff", "review diff"}
            or re.match(r"^(a|b)/.+\s(→|->)\s.+$", normalized)
            or normalized.startswith("@@ ")
        )
        if starts_noise:
            removed = True
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
                removed = True
                continue
            skipping = False
        kept.append(line)
    return "\n".join(kept), removed


def _patch_model_aware_compression_threshold():
    """Keep Gemini's quota guard from leaking into Codex subscription chats.

    Hermes reads one global compression threshold from config.yaml even when a
    Telegram session selects a different provider/model. Admira intentionally
    keeps Gemini Flash Lite as the installation default, so without this
    runtime override Luna/Terra inherit Gemini's 6% threshold and summarize a
    272K Codex conversation at roughly 16K tokens.
    """
    try:
        from agent import auxiliary_client
    except Exception:
        return False
    original = getattr(auxiliary_client, "_compression_threshold_for_model", None)
    if not callable(original):
        return False
    if getattr(original, "_admira_model_aware_compression_patch", False):
        return True

    def patched(model, provider=None, *, allow_codex_gpt55_autoraise=True):
        model_id = str(model or "").strip().lower()
        provider_id = str(provider or "").strip().lower().replace("_", "-")
        if provider_id == "openai-codex" and model_id in {
            "gpt-5.6-luna",
            "gpt-5.6-terra",
        }:
            return 0.85
        return original(
            model,
            provider,
            allow_codex_gpt55_autoraise=allow_codex_gpt55_autoraise,
        )

    patched._admira_model_aware_compression_patch = True
    patched._admira_original_compression_threshold = original
    auxiliary_client._compression_threshold_for_model = patched
    return True


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


def _attach_safe_media_paths_leaked_in_visible_text(value, language=None):
    """Turn safe output paths into native attachments without exposing them.

    A model may correctly choose an existing recent creative but repeat the
    tool's private ``/app/output/...`` path in prose. This is a transport
    formatting concern, not an intent router: preserve the surrounding answer,
    replace only verified product-media paths with buyer-readable wording, and
    append the native MEDIA directive Telegram already understands.
    """
    text = str(value or "")
    matches = []
    for match in ADMIRA_OUTPUT_IMAGE_RE.finditer(text):
        safe_path = _safe_generated_media_path(match.group("path"))
        if not safe_path:
            continue
        prefix = text[max(0, match.start() - 6):match.start()].upper()
        already_directive = prefix.endswith("MEDIA:")
        start, end = match.start(), match.end()
        # Remove a Markdown code wrapper together with the private path so the
        # visible sentence says “el archivo adjunto”, not “`el archivo adjunto`”.
        if not already_directive and start > 0 and end < len(text):
            if text[start - 1] == "`" and text[end] == "`":
                start -= 1
                end += 1
        matches.append((start, end, safe_path, already_directive))
    if not matches:
        return text, False

    visible = text
    attachment_label = (
        "the attached media"
        if str(language or "es").lower().startswith("en")
        else "el archivo adjunto"
    )
    for start, end, _path, already_directive in reversed(matches):
        if not already_directive:
            visible = visible[:start] + attachment_label + visible[end:]

    existing_directives = {
        path for _start, _end, path, already_directive in matches if already_directive
    }
    directives = []
    seen = set()
    for _start, _end, path, already_directive in matches:
        if path in seen or path in existing_directives or already_directive:
            continue
        seen.add(path)
        directives.append(f"MEDIA:{path}")
    if directives:
        visible = (visible.rstrip() + "\n" + "\n".join(directives)).strip()
    return visible, visible != text


def _dedupe_native_media_directives(value):
    """Keep only the first native attachment directive for each safe file."""
    text = str(value or "")
    seen = set()
    changed = False

    def replace(match):
        nonlocal changed
        safe_path = _safe_generated_media_path(match.group("path"))
        if not safe_path:
            return match.group(0)
        if safe_path not in seen:
            seen.add(safe_path)
            canonical = f"MEDIA:{safe_path}"
            if canonical != match.group(0):
                changed = True
            return canonical
        changed = True
        return ""

    clean = ADMIRA_MEDIA_TAG_RE.sub(replace, text)
    if changed:
        clean = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", clean)
        clean = re.sub(r"[ \t]+\n", "\n", clean).strip()
    return clean, changed


def normalize_telegram_outbound_text(value, language=None):
    """Return non-empty Telegram-safe text plus delivery diagnostics metadata."""
    original = str(value or "")
    cleaned = ADMIRA_TELEGRAM_INVISIBLE_RE.sub("", original)
    cleaned, context_notice_removed = _strip_internal_context_notices(cleaned)
    cleaned, internal_reasoning_removed = _strip_internal_reasoning(cleaned)
    cleaned, technical_preamble_removed = _strip_technical_preamble(cleaned)
    cleaned, table_changed = _render_markdown_tables_as_text(cleaned)
    cleaned, media_path_attached = _attach_safe_media_paths_leaked_in_visible_text(cleaned, language)
    cleaned, duplicate_media_removed = _dedupe_native_media_directives(cleaned)
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
    if technical_preamble_removed:
        reasons.append("technical_preamble_removed")
    if media_path_attached:
        reasons.append("internal_media_path_attached")
    if duplicate_media_removed:
        reasons.append("duplicate_media_directive_removed")
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


def _continuity_resume_hint(session_key, history=None, message=None):
    """Inject a compact orientation note when a turn could restart onboarding.

    Durable buyer memory is intentionally kept in workspace files, but a new
    Telegram session can reach the model with an empty history before the model
    decides to read those files. Smaller models then restart onboarding even
    though the installation already knows the business. It is also added to a
    short greeting after a restart when a small transcript was rebuilt. It
    contains no authorization and is stripped before the user is persisted.
    """
    visible_message = str(message or "").split("[ADMIRA LIVE META CONTEXT", 1)[0].strip().lower()
    greeting_turn = bool(re.fullmatch(r"(?:hola|hello|hi|buenas(?: tardes| d[ií]as| noches)?)[!,. ]*", visible_message))
    if isinstance(history, list) and history and not greeting_turn:
        return ""
    root = Path(str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "").strip()).expanduser()
    workspace = root / "dashboard" / "data" / "hermes-workspace" / "current"
    status_path = workspace / "memory" / "continuity_status.json"
    workflow_path = workspace / "memory" / "active_workflow.json"
    profile_path = workspace / "data" / "business_profile.json"
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return ""
    if not (
        bool(status.get("has_persistent_memory"))
        or bool(workflow.get("has_active_workflow"))
    ):
        return ""

    # If the caller did not provide history, use the session database as a
    # conservative fallback. Never inject continuity into an established
    # conversation, where the normal transcript is the better source.
    if history is None:
        session_id = ""
        sessions_path = root / "runtime" / "hermes" / "sessions" / "sessions.json"
        try:
            index = json.loads(sessions_path.read_text(encoding="utf-8"))
            entry = index.get(str(session_key or ""), {})
            session_id = str(entry.get("session_id") or "") if isinstance(entry, dict) else ""
        except (OSError, TypeError, ValueError):
            return ""
        if not session_id:
            return ""
        try:
            with sqlite3.connect(str(root / "runtime" / "hermes" / "state.db"), timeout=1.0) as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM messages WHERE session_id = ? AND role IN ('user', 'assistant')",
                    (session_id,),
                ).fetchone()[0]
            if int(count or 0) > 1:
                return ""
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return ""

    strategic_state = _admira_strategic_profile_state(product_root=root)
    goal = str(profile.get("campaign_goal") or "").strip()
    goal = re.sub(r"\s+", " ", goal)[:420]
    phase = str(workflow.get("phase") or "").strip()
    next_step = str(workflow.get("next_step") or "").strip()
    if next_step:
        next_step = re.sub(r"\s+", " ", next_step)[:300]
    if phase:
        phase = re.sub(r"\s+", " ", phase)[:120]
    lines = [ADMIRA_SESSION_CONTINUITY_START]
    if isinstance(history, list) and history:
        lines.append("Es un saludo después de un reinicio, no un comprador nuevo; ya existe conversación y memoria duradera.")
    else:
        lines.extend([
            "Esta es una sesión nueva después de un reinicio/actualización, no un comprador nuevo.",
            "La memoria duradera ya existe.",
        ])
    lines.append("No anuncies ni vuelvas a pedir una conexión o selección Meta que el bloque live marque como ya activa.")
    lines.append("La conexión no salta onboarding: si faltan datos, resume lo que ya se conoce y pide confirmar solo lo que falta; no hagas la pregunta genérica de qué negocio o público tiene.")
    known_excerpt = _admira_render_business_profile(strategic_state, max_chars=2600)
    if known_excerpt and "No Page-scoped business facts" not in known_excerpt:
        lines.append("Memoria Page-scoped ya conocida (no volver a preguntarla):\n" + known_excerpt)
    if goal:
        lines.append(f"Negocio/objetivo ya identificado: {goal}")
    if phase or next_step:
        lines.append(f"Flujo recordado: {phase or 'activo'}. Siguiente orientación: {next_step or 'retomar la conversación reciente'}.")
    lines.extend([
        "Usa esta información solo para orientar la respuesta; no autoriza crear, editar, activar ni gastar.",
        "Lee el bloque live de Meta adjunto y, si es un saludo, responde con una continuidad breve usando una señal concreta; actúa como manager o pide una confirmación específica, nunca reinicies el onboarding de forma genérica.",
        ADMIRA_SESSION_CONTINUITY_END,
    ])
    return "\n".join(lines)


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
            "If Facebook account/Page are selected but the general business profile is empty, strategic business onboarding is the required next stage before producing, staging, or creating a campaign. Do not offer a skip-to-campaign path. Continue as an engaging manager conversation, using live context and asking one useful owner question at a time while saving confirmed facts. "
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
            "Si la cuenta y Página de Facebook están seleccionadas pero el perfil general del negocio está vacío, el onboarding estratégico es la siguiente etapa obligatoria antes de producir, preparar o crear una campaña. No ofrezcas saltarlo para ir directo a campañas. Continúa como una conversación útil de gestor, usando contexto en vivo, guardando lo confirmado y haciendo una pregunta relevante del dueño por turno. "
            "En una campaña nueva, no generes ni selecciones un creativo y no llames a un MCP de creación mientras el cliente no haya visto y resuelto el presupuesto actual, el creativo exacto, el texto principal, el título y el mensaje/destino correspondiente. Una petición de crear campaña no autoriza valores inventados ni el presupuesto de otra campaña; presenta la propuesta y espera su acuerdo natural. Mientras falten el copy o el creativo, tampoco preguntes si desea crearla o dejarla en pausa: presenta primero la propuesta concreta y abre la revisión conjunta. La solicitud visible de aprobación debe incluir el copy completo, el título distinto y el mensaje de destino exactos en texto normal; nunca escondas el copy detrás de una opción genérica de «aprobar y crear». Primero muestra el creativo y la propuesta para que el cliente corrija o apruebe en conjunto. "
            "Si el bloque live confirma oauth_workspace.selection_required=false y contiene active_ad_account_id y active_page_id, la conexión y selección ya son hechos persistentes: no los anuncies como novedad ni pidas elegirlos otra vez. La conexión no salta el onboarding: si aún faltan datos del negocio, resume primero un dato concreto de business_profile, una guía de producto/marca o current_campaigns y pide únicamente confirmar o completar lo que falta; nunca preguntes de forma genérica qué negocio tiene el comprador. Si el contexto ya es suficiente, actúa como manager continuo y usa una señal concreta de Meta. "
            "Avanza ahora todo paso seguro ya autorizado. Antes de preguntar, identifica todos los insumos del dueño necesarios para terminar el siguiente entregable. Haz como máximo una pregunta bloqueante; si faltan varios datos o archivos del dueño estrechamente relacionados, pídelos juntos una sola vez en un paquete breve. "
            "Para un principiante, entrega decisión, una razón o riesgo de negocio y la acción concreta siguiente en máximo 180 palabras. No descargues alternativas ni termines con una invitación tipo «si quieres». "
            "Si recomiendas precio o presupuesto y ya conoces los costos, calcula el margen de contribución y las ventas/leads adicionales aproximados necesarios para recuperar la pauta antes de elegir el test.\n"
            "Para activar inmediatamente una campaña usa la acción de reanudación/activación y espera la confirmación Graph ACTIVE; nunca crees una programación o cronjob para una petición de activación inmediata. Usa schedule_campaign_activation únicamente cuando el cliente haya pedido una fecha u hora futura concreta. Una programación exitosa significa que la campaña permanece PAUSED hasta esa fecha; no la describas como activa.\n"
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
    pending_campaign_workflow = {}
    pending_path = root / "dashboard" / "data" / "pending_campaign_workflow.json"
    try:
        candidate = json.loads(pending_path.read_text(encoding="utf-8"))
        if isinstance(candidate, dict) and candidate.get("status") == "pending":
            pending_campaign_workflow = candidate
    except (OSError, ValueError, TypeError):
        pass
    return {
        "ok": bool(payload.get("ok") and live_sync.get("ok")),
        "metrics_source": context.get("metrics_source") or payload.get("metrics_source") or {},
        "live_sync": live_sync,
        "inventory_counts": context.get("inventory_counts") or {},
        "summary": context.get("summary") or {},
        "metrics_range": context.get("metrics_range") or {},
        "data_quality": context.get("data_quality") or {},
        "oauth_workspace": context.get("oauth_workspace") or {},
        "fetched_at": live_sync.get("fetched_at") or "",
        "campaigns": (context.get("campaigns") or [])[:100],
        "adsets": (context.get("adsets") or [])[:200],
        "ads": (context.get("ads") or [])[:300],
        "campaign_tree": (context.get("campaign_tree") or [])[:100],
        "approval_context_policy": context.get("approval_context_policy") or "",
        "pending_campaign_workflow": pending_campaign_workflow,
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
        + "OAuth workspace state has a separate meaning from live campaign sync. If oauth_workspace.authorized=true and selection_required=true, Facebook permissions succeeded: never claim authorization or ads_read/ads_management is missing, and never request another link. List publishable Pages first and ad accounts second, then require exactly two numbers with no words: Page number first and ad-account number second. Names, confirmations, prose, out-of-range values, and partial replies do not authorize; show both lists again. Only the protected backend may resolve that strict pair before mcp_admira_select_meta_oauth_workspace persists it.\n"
        + "If oauth_workspace.selection_required=false and active account/Page IDs are present, that selection is already persistent: use it silently and never ask the buyer to choose again unless they explicitly request a switch. Never claim a new selection was saved unless mcp_admira_select_meta_oauth_workspace succeeded in this turn.\n"
        + "pending_campaign_workflow is context, not proof or permission. After an explicit conversation reset, act on it only when the current exchange establishes that scope again. A short acknowledgement can authorize an action only when it answers an immediately preceding explicit question in the active conversation; persisted memory alone never supplies that authorization.\n"
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
    # Include a compact view of the current inventory even when campaigns are
    # paused. Active-only context made a test account look empty and nudged
    # the model back into onboarding.
    def project_current(rows, limit, extra=()):
        projected = []
        for row in (rows or [])[:limit]:
            if not isinstance(row, dict):
                continue
            keys = (*common, *extra, *metrics)
            projected.append({key: row.get(key) for key in keys if row.get(key) not in (None, "", [], {})})
        return projected

    current_campaigns = project_current(
        context.get("campaigns"),
        20,
        ("objective", "daily_budget", "priority_metrics", "metric_profile"),
    )
    current_adsets = project_current(
        context.get("adsets"),
        40,
        ("optimization_goal", "billing_event", "daily_budget", "lifetime_budget", "budget_remaining"),
    )
    current_ads = project_current(
        context.get("ads"),
        60,
        ("creative_id", "object_story_id"),
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
        "oauth_workspace": context.get("oauth_workspace") or {},
        "pending_campaign_workflow": context.get("pending_campaign_workflow") or {},
        "active_campaigns": campaigns,
        "active_adsets": adsets,
        "active_ads": ads,
        "current_campaigns": current_campaigns,
        "current_adsets": current_adsets,
        "current_ads": current_ads,
        "snapshot_scope": {
            "active_only": True,
            "current_inventory_included": True,
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
    text = re.sub(
        r"\n*\[ADMIRA SESSION CONTINUITY.*?\[END ADMIRA SESSION CONTINUITY\]\s*",
        "\n",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"\n*\[ADMIRA PRODUCT STATE.*?\[END ADMIRA PRODUCT STATE\]\s*",
        "\n",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"\n*\[ADMIRA COMPILED PROCEDURE.*?\[END ADMIRA COMPILED PROCEDURE\]\s*",
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
        # The small canary VPS can need 10-15 seconds while Codex validates
        # the persisted subscription. A shorter timeout made Telegram report
        # a false failure even though the dashboard completed moments later.
        # Three seconds made explicit Telegram
        # connection requests fall through to the model and hallucinate CLI
        # commands instead of returning the secure device link.
        with urllib.request.urlopen(request, timeout=30) as response:
            if int(getattr(response, "status", 200)) != 200:
                return {}
            payload = json.loads(response.read(64 * 1024).decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError):
        return {}
    result = payload.get("result") if isinstance(payload, dict) else {}
    return result if isinstance(result, dict) else {}


def _automatic_codex_recovery(wait_seconds=12, action="start"):
    if not _internal_recovery_settings()[0]:
        return {}
    result = _request_internal_model_recovery(action)
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


def _chatgpt_login_pending_path():
    configured = str(os.environ.get("ADMIRA_CHATGPT_LOGIN_PENDING_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser()
    # Production containers do not need ADMIRA_PRODUCT_ROOT because /app is
    # the stable, volume-backed product root. Keep the environment override
    # for tests and non-container installations.
    root = str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "/app").strip()
    return Path(root).expanduser() / "dashboard" / "data" / "chatgpt_login_pending.json"


def _chatgpt_login_pending_key(session_key):
    value = re.sub(r"[^A-Za-z0-9:_.-]+", "_", str(session_key or "").strip())[:240]
    return value or "default"


def _read_chatgpt_login_pending():
    path = _chatgpt_login_pending_path()
    if path is None:
        return {}, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        payload = {}
    pending = payload.get("pending") if isinstance(payload, dict) else {}
    if not isinstance(pending, dict):
        pending = {}
    now = time.time()
    clean = {}
    for key, value in pending.items():
        if not isinstance(value, dict):
            continue
        try:
            expires_at = float(value.get("expires_at") or 0)
        except (TypeError, ValueError):
            continue
        if expires_at > now:
            clean[str(key)] = value
    return clean, path


def _write_chatgpt_login_pending(pending, path):
    if path is None:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps({"version": 1, "pending": pending}, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        temporary.replace(path)
        path.chmod(0o600)
        return True
    except OSError:
        return False


def _remember_chatgpt_login_pending(session_key):
    pending, path = _read_chatgpt_login_pending()
    now = time.time()
    pending[_chatgpt_login_pending_key(session_key)] = {
        "started_at": now,
        "expires_at": now + ADMIRA_CHATGPT_LOGIN_PENDING_TTL_SECONDS,
    }
    return _write_chatgpt_login_pending(pending, path)


def _clear_chatgpt_login_pending(session_key):
    pending, path = _read_chatgpt_login_pending()
    pending.pop(_chatgpt_login_pending_key(session_key), None)
    return _write_chatgpt_login_pending(pending, path)


def _chatgpt_login_confirmation_request(text, session_key):
    if not ADMIRA_CHATGPT_LOGIN_CONFIRMATION_RE.fullmatch(str(text or "")):
        return False
    pending, _path = _read_chatgpt_login_pending()
    return _chatgpt_login_pending_key(session_key) in pending


def _chatgpt_login_confirmation_reply(session_key, language="es"):
    english = str(language or "es").lower().startswith("en")
    result = _request_internal_model_recovery("status")
    status = str(result.get("status") or "").strip().lower()
    authenticated = bool(result.get("authenticated"))
    if authenticated or status == "completed":
        _clear_chatgpt_login_pending(session_key)
        return (
            "✅ ChatGPT connected. The new account is ready for Image 2 and the Luna fallback."
            if english
            else "✅ ChatGPT conectado. La nueva cuenta ya está lista para Image 2 y el fallback Luna."
        )
    urls = [_safe_openai_login_url(item) for item in (result.get("urls") or [])]
    login_url = next((item for item in urls if item), "")
    codes = result.get("login_codes") if isinstance(result.get("login_codes"), list) else []
    login_code = str(result.get("login_code") or (codes[0] if codes else "")).strip().upper()
    if login_url and re.fullmatch(r"[A-Z0-9](?:[A-Z0-9-]{4,30})[A-Z0-9]", login_code):
        return (
            f"The ChatGPT login is still waiting. Open {login_url} and enter {login_code}. Then reply Done again."
            if english
            else f"El login de ChatGPT todavía está esperando. Abre {login_url} e ingresa {login_code}. Después responde Listo otra vez."
        )
    if result.get("running") or status in {"browser_login_started", "browser_login_waiting", "needs_login"}:
        return (
            "The ChatGPT login is still waiting for completion. Finish it and reply Done again."
            if english
            else "El login de ChatGPT todavía está esperando que lo completes. Termínalo y responde Listo otra vez."
        )
    return (
        "I could not verify the ChatGPT login yet. Reply Done again in a moment; if it keeps failing, send /conectar_chatgpt for a fresh secure link."
        if english
        else "Todavía no pude verificar el login de ChatGPT. Responde Listo otra vez en un momento; si continúa, envía /conectar_chatgpt para generar un enlace seguro nuevo."
    )


def _chatgpt_connection_request(text):
    """Recognize an explicit buyer request without spending a model turn."""
    value = str(text or "").strip().lower()
    # Telegram/Markdown copies sometimes escape underscores in displayed
    # commands. Treat that presentation artifact as the intended command.
    value = value.replace("\\_", "_")
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    command = value.split(maxsplit=1)[0].split("@", 1)[0] if value else ""
    if command in {
        "/conectar_chatgpt", "/reconectar_chatgpt", "/connect_chatgpt",
    }:
        return True
    tokens = re.findall(r"[a-z0-9]+", value)

    def resembles(token, candidates):
        if not token:
            return False
        for candidate in candidates:
            if token == candidate:
                return True
            # Natural Telegram wording frequently contains a one/two-letter
            # typo. Fuzzy matching is bounded to meaningful words and still
            # requires both a provider and an auth-action family.
            if min(len(token), len(candidate)) >= 5:
                threshold = 0.78 if max(len(token), len(candidate)) <= 9 else 0.82
                if difflib.SequenceMatcher(None, token, candidate).ratio() >= threshold:
                    return True
        return False

    provider = any(resembles(token, {"chatgpt", "codex"}) for token in tokens)
    if not provider and "chat gpt" in value:
        provider = True
    if not provider:
        return False
    action_words = {
        "conectar", "conecta", "conectarme", "reconectar", "reconecta", "cambiar",
        "cambio", "enlace", "link", "url", "login", "autenticar", "vincular", "switch",
    }
    action = any(resembles(token, action_words) for token in tokens)
    account_switch = (
        any(resembles(token, {"otra", "nueva", "diferente"}) for token in tokens)
        and any(resembles(token, {"cuenta", "usuario", "perfil", "conexion", "sesion"}) for token in tokens)
    )
    return bool(action or account_switch)


def _chatgpt_connection_reply(result, language="es"):
    english = str(language or "es").lower().startswith("en")
    if result.get("url") and result.get("code"):
        if english:
            return (
                "🔐 Open this secure ChatGPT login:\n"
                f"{result['url']}\n\nTemporary code: {result['code']}\n\n"
                "Finish the login with the account you want Admira to use for Image 2 and the Luna fallback."
            )
        return (
            "🔐 Abre este login seguro de ChatGPT:\n"
            f"{result['url']}\n\nCódigo temporal: {result['code']}\n\n"
            "Termina el login con la cuenta que quieres que Admira use para Image 2 y el fallback Luna."
        )
    if result.get("device_auth_settings"):
        return (
            "Activa la autorización con códigos de dispositivo para Codex en Seguridad de ChatGPT y vuelve a enviar "
            "`/conectar_chatgpt`."
        )
    return (
        "No pude obtener todavía el enlace de ChatGPT. Espera unos segundos y vuelve a enviar "
        "`/conectar_chatgpt`."
    )


def _patch_gateway_chatgpt_slash_commands():
    """Make the secure ChatGPT reconnect aliases real gateway commands.

    Hermes' slash dispatcher rejects unknown commands before the normal
    buyer-message path runs. The runtime already recognized these aliases in
    its text interceptor, but that interceptor was never reached for a typed
    slash command. Intercept only the three explicit connection aliases at
    the gateway boundary; unrelated commands remain Hermes' responsibility.
    """
    try:
        from gateway.run import GatewayRunner
    except Exception:
        return False
    original = getattr(GatewayRunner, "_handle_message", None)
    if not callable(original):
        return False
    if getattr(original, "_admira_chatgpt_slash_patch", False):
        return True

    async def patched(self, event, _original=original):
        raw = str(getattr(event, "text", "") or "").strip()
        source = getattr(event, "source", None)
        # Capture the exact authorized buyer turn at the stable gateway
        # boundary. Telegram adapters are loaded dynamically after
        # sitecustomize, so adapter-only patching can miss the real class and
        # leave every buyer-confirmed memory save as an unauthorised draft.
        if raw and not bool(getattr(event, "internal", False)) and source is not None:
            try:
                authorized = bool(self._is_user_authorized(source))
            except Exception:
                authorized = False
            if authorized:
                try:
                    session_key = self._session_key_for_source(source)
                except Exception:
                    session_key = ""
                sequence = getattr(event, "message_id", None)
                if sequence is None:
                    sequence = getattr(event, "platform_update_id", None)
                platform = getattr(source, "platform", "gateway")
                transport = str(getattr(platform, "value", platform) or "gateway")
                _record_trusted_buyer_turn(
                    chat_id=getattr(source, "chat_id", None),
                    session_id=session_key,
                    message_sequence=sequence,
                    raw_message=str(getattr(event, "text", "") or ""),
                    transport=transport,
                )
        if _chatgpt_connection_request(raw):
            normalized = raw.lower().replace("\\_", "_")
            command = normalized.split(maxsplit=1)[0].split("@", 1)[0]
            if command in {
                "/conectar_chatgpt", "/reconectar_chatgpt", "/connect_chatgpt",
            }:
                # Let Hermes' normal pairing/authorization response handle an
                # unauthorized sender; do not expose the login recovery path.
                try:
                    if source is not None and not self._is_user_authorized(source):
                        return await _original(self, event)
                except Exception:
                    return await _original(self, event)
                try:
                    session_key = self._session_key_for_source(source)
                except Exception:
                    session_key = ""
                # Device login performs local HTTP and PTY polling. Keep it
                # off the Telegram event loop so typing, commands and polling
                # continue while the secure URL/code is being produced.
                result = await asyncio.to_thread(
                    _automatic_codex_recovery,
                    wait_seconds=15,
                    action="switch",
                )
                if result.get("url") and result.get("code"):
                    _remember_chatgpt_login_pending(session_key)
                language = str(os.environ.get("ADMIRA_GATEWAY_LANGUAGE") or "es")
                return _chatgpt_connection_reply(result, language)
        return await _original(self, event)

    patched._admira_chatgpt_slash_patch = True
    patched._admira_original_handle_message = original
    GatewayRunner._handle_message = patched
    return True


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
    """Classify failures for which an alternate NIM model must not be tried.

    A NIM ``429`` is not necessarily account-wide: NVIDIA can throttle an
    individual hosted model pool while another listed model under the *same*
    key is healthy.  The fallback chain contains at most one, live-catalog
    verified alternate, so a 429 may use that one bounded attempt.  Explicit
    quota, billing and credential failures remain shared-key failures and
    must never rotate models.
    """
    text = _admira_failover_reason_text(reason)
    return any(marker in text for marker in (
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
    narrow guard permits one live-catalog alternate after a model-pool 429,
    while preventing rotation after quota, billing or credential failures.
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
    """Return only the buyer's current request and its active tool loop.

    The assembled system prompt documents every Admira capability (including
    organic content, lead forms and video).  Routing from the whole prompt
    therefore lets unrelated system wording win over the buyer's actual
    request.  Stop at the newest user message and retain only the tool/agent
    messages after it, which are required to recover a current tool error.
    """
    entries = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").lower()
        if role not in {"user", "assistant", "tool"}:
            continue
        content = message.get("content")
        if isinstance(content, list):
            content = " ".join(
                str(item.get("text") or item.get("content") or "")
                for item in content
                if isinstance(item, dict)
            )
        content_text = str(content or "")
        if role == "user":
            content_text = _strip_admira_runtime_injections(content_text)
        entries.append((role, content_text))
    last_user = next((index for index in range(len(entries) - 1, -1, -1) if entries[index][0] == "user"), None)
    if last_user is None:
        # Defensive fallback for malformed provider requests. Still omit the
        # large system prompt rather than routing from product documentation.
        return " ".join(content for _, content in entries[-4:]).lower()

    active = entries[last_user:]
    user_text = entries[last_user][1].lower()
    # A buyer who says only "retry", "again" or "continue" is referring to
    # the immediately preceding tool outcome. Include that narrow prior loop
    # but never earlier user turns or the full system prompt.
    if re.search(
        r"\b(reintenta|reintentar|int[eé]ntalo|again|retry|contin[uú]a|continue|"
        r"hazlo|procede|dale|aprobado|approved|ok|s[ií])\b",
        user_text,
    ):
        prior = []
        prior_user_turns = 0
        for role, content in reversed(entries[:last_user]):
            if content:
                prior.append((role, content))
            if role == "user":
                prior_user_turns += 1
                # Natural confirmations such as "sí, procede" may follow a
                # campaign assembled over two short Telegram messages. Keep
                # exactly those two prior buyer turns and their intervening
                # tool/assistant results, never the entire old session.
                if prior_user_turns >= 2:
                    break
            if len(prior) >= 8:
                break
        active = list(reversed(prior)) + active
    return " ".join(content for _, content in active if content).lower()


def _nvidia_routing_text(messages):
    """Anchor one tool loop to the buyer's latest explicit request.

    Live Meta snapshots can mention images, videos, forms and campaigns in the
    same tool result.  Those incidental capability words must not change the
    request profile between the first provider call and the post-tool call.
    A genuinely generic retry/continue message remains the one exception: it
    needs the narrow prior tool loop supplied by ``_nvidia_message_text``.
    """
    latest_user = ""
    for message in reversed(messages or []):
        if not isinstance(message, dict) or str(message.get("role") or "").lower() != "user":
            continue
        content = message.get("content")
        if isinstance(content, list):
            content = " ".join(
                str(item.get("text") or item.get("content") or "")
                for item in content
                if isinstance(item, dict)
            )
        # Gateway appends live Meta/context contracts to the same user
        # message. Routing must follow only the buyer-visible request; words
        # such as campaign, image, or WhatsApp inside the injected snapshot
        # must never select a mutating tool.
        latest_user = _strip_admira_runtime_injections(str(content or "")).strip().lower()
        break
    if not latest_user:
        return _nvidia_message_text(messages)
    if re.search(
        r"\b(reintenta|reintentar|int[eé]ntalo|again|retry|contin[uú]a|continue|"
        r"hazlo|procede|dale|aprobado|approved|ok|s[ií])\b",
        latest_user,
    ):
        return _nvidia_message_text(messages)
    return latest_user


def _admira_latest_campaign_routing_context():
    """Return a bounded, recent destination/creative handoff for continuations."""
    root = Path(str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "/app").strip())
    path = root / "dashboard" / "data" / "campaign-compiler" / "latest-campaign.md"
    try:
        if time.time() - path.stat().st_mtime > 24 * 60 * 60:
            return ""
        text = path.read_text(encoding="utf-8")[:12_000]
    except (OSError, ValueError):
        return ""
    lines = []
    for line in text.splitlines():
        lowered = line.lower()
        if any(marker in lowered for marker in (
            "destination contract", "whatsapp", "messenger", "instagram direct",
            "landing_url", "sitio web", "lead_gen_form", "formulario",
            "creative", "creativo", "image_path", "imagen",
        )):
            lines.append(line.strip())
        if len(lines) >= 24:
            break
    return " ".join(lines).lower()


def _admira_campaign_continuation_requested(messages):
    text = _nvidia_routing_text(messages)
    return bool(re.search(
        r"\b(procede|contin[uú]a|continue|hazlo|dale|reintenta|int[eé]ntalo|"
        r"no\s+cambies|como\s+(?:acordamos|confirm[eé])|esa\s+campa[nñ]a|"
        r"la\s+campa[nñ]a\s+completa)\b",
        text,
    ))


def _admira_campaign_creation_deferred(messages):
    text = ""
    for message in reversed(messages or []):
        if not isinstance(message, dict) or str(message.get("role") or "").lower() != "user":
            continue
        content = message.get("content")
        if isinstance(content, list):
            content = " ".join(
                str(item.get("text") or item.get("content") or "")
                for item in content if isinstance(item, dict)
            )
        text = _strip_admira_runtime_injections(str(content or "")).strip().lower()
        break
    return bool(re.search(
        r"\b(?:no|sin)\s+(?:crees|crear|ejecutes|ejecutar|publiques|publicar)\b.{0,45}"
        r"\b(?:todav[ií]a|a[uú]n|hasta|espera|confirmaci[oó]n|mensaje\s+final)\b|"
        r"\b(?:todav[ií]a|a[uú]n)\s+no\b.{0,35}\b(?:crees|crear|ejecutes|ejecutar)\b",
        text,
    ))


def _nvidia_explicit_lead_form_creation_requested(messages):
    text = _nvidia_routing_text(messages)
    form = any(marker in text for marker in ADMIRA_NVIDIA_LEAD_FORM_TERMS)
    action = bool(re.search(
        r"\b(crea|crear|créalo|crealo|hazlo|procede|publica|publicar|"
        r"create|build|publish|approved|aprobado)\b",
        text,
    ))
    return form and action


def _admira_explicit_image_generation_requested(messages):
    """Require a real Image call for a direct production request, not advice."""
    text = _nvidia_routing_text(messages)
    if _admira_existing_creative_reuse_requested(messages):
        return False
    if any(marker in text for marker in (
        "video", "reel", "motion", "animación", "animacion", "storyboard",
        "ideas de creativo", "idea de creativo", "conceptos de creativo",
        "plan de creativo", "recomienda un creativo",
    )):
        return False
    creative = any(marker in text for marker in (
        "creativo", "creativa", "imagen", "diseño gráfico", "diseno grafico",
        "ad creative", "static creative",
    ))
    production = bool(re.search(
        r"\b(crea|crear|creemos|cr[eé]alo|genera|generar|haz|produce|producir|"
        r"dije\s+creativo|quiero\s+(?:un|una)|necesito\s+(?:un|una))\b",
        text,
    ))
    return creative and production


def _admira_buyer_requests_clarification(messages):
    """Recognize a repair turn without turning it into a product action."""
    latest = ""
    for message in reversed(messages or []):
        if not isinstance(message, dict) or str(message.get("role") or "").lower() != "user":
            continue
        content = message.get("content")
        if isinstance(content, list):
            content = " ".join(
                str(item.get("text") or item.get("content") or "")
                for item in content if isinstance(item, dict)
            )
        latest = _strip_admira_runtime_injections(str(content or "")).strip().lower()
        break
    if not latest or len(latest) > 120:
        return False
    plain = unicodedata.normalize("NFKD", latest).encode("ascii", "ignore").decode("ascii")
    plain = re.sub(r"\s+", " ", plain).strip()
    return bool(
        re.fullmatch(r"(?:que|what)\s*[?!.,]*", plain)
        or re.match(
            r"^(?:por que dices eso|por que respondes eso|no entiendo|"
            r"eso no tiene sentido|no tiene nada que ver|why did you say that|i do not understand)\b",
            plain,
        )
    )


def _admira_latest_user_text(messages):
    """Return the latest buyer message, excluding agent/system context."""
    for message in reversed(messages or []):
        if not isinstance(message, dict) or str(message.get("role") or "").lower() != "user":
            continue
        content = message.get("content")
        if isinstance(content, list):
            content = " ".join(
                str(item.get("text") or item.get("content") or "")
                for item in content if isinstance(item, dict)
            )
        return _strip_admira_runtime_injections(str(content or "")).strip().lower()
    return ""


def _admira_latest_assistant_text(messages):
    """Return the assistant turn immediately before the latest buyer turn."""
    seen_buyer = False
    for message in reversed(messages or []):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").lower()
        if role == "user":
            seen_buyer = True
            continue
        if seen_buyer and role == "assistant":
            content = message.get("content")
            if isinstance(content, list):
                content = " ".join(
                    str(item.get("text") or item.get("content") or "")
                    for item in content if isinstance(item, dict)
                )
            return _strip_admira_runtime_injections(str(content or "")).strip().lower()
    return ""


def _admira_latest_creative_approval(messages):
    """Return true when the buyer approves an already delivered creative."""
    latest = _admira_latest_user_text(messages)
    if not latest or not re.fullmatch(
        r"(?:s[ií]|si|ok(?:ay)?|adelante|me gusta|aprobado|aprobada|de acuerdo|"
        r"sigamos|contin[uú]a(?:mos)?|hazlo)[.!?\s]*",
        latest,
    ):
        return False
    previous = _admira_latest_assistant_text(messages)
    delivered = bool(re.search(r"(?:media:|adjunt(?:é|e|ado|ada)|imagen\s+(?:generada|creada)|creativo\s+(?:generado|creado))", previous))
    approval_prompt = bool(re.search(r"(?:aprueb|opini[oó]n|te\s+parece|visto\s+bueno|revis(?:a|ar)|confirma)", previous))
    return delivered and approval_prompt


def _admira_latest_media_request_or_approval(messages):
    """Allow media tools only for a direct request or approval of a proposal.

    Campaign context often contains older assistant text such as “creative” or
    “image”. Looking at the whole conversation made a budget/service answer
    look like a new image request. This helper deliberately scopes the decision
    to the latest buyer turn and, for a short “sí”, the immediately preceding
    assistant proposal.
    """
    latest = _admira_latest_user_text(messages)
    if not latest:
        return False
    plain = unicodedata.normalize("NFKD", latest).encode("ascii", "ignore").decode("ascii")
    # A campaign request may mention that it needs a creative. That is still
    # planning context, not an order to render pixels. Require a direct media
    # action whose object is the image/creative itself (or an explicit
    # revision/show request), rather than merely seeing both words anywhere.
    media_object = r"(?:creativ[oa]|imagen|foto|video|diseno\s+grafico|creative|image|photo|video)"
    direct_media = bool(re.search(
        rf"\b(?:crea(?:r|mos)?|genera(?:r|mos)?|haz(?:me)?|produce|producir|redise[nñ]a|"
        rf"dise[nñ]a|edita|revisa|muestra|cambia|ajusta)\s+(?:un[oa]?\s+|el\s+|la\s+|otro\s+|otra\s+|nuevo\s+|nueva\s+)?{media_object}\b",
        plain,
    )) or bool(re.search(
        rf"\b{media_object}\b.{{0,32}}\b(?:redise[nñ]a|edita|revisa|muestra|cambia|ajusta)\b",
        plain,
    ))
    # A buyer's answer to a creative-choice question is also a media
    # direction, even when it is declarative rather than imperative (for
    # example: “un anuncio con un texto grande”). It authorizes a visual draft,
    # not the campaign itself.
    previous = _admira_latest_assistant_text(messages)
    creative_direction = bool(re.search(
        r"\b(?:anuncio|creativ[oa]|imagen|dise[nñ]o|foto|visual)\b",
        plain,
    )) and bool(re.search(
        r"(?:texto\s+(?:grande|visible|claro)|mensaje|titular|dise[nñ]o|foto|imagen|visual)",
        plain,
    )) and (
        bool(re.search(
            r"(?:prefieres|prefiere|que\s+prefieres|tipo\s+de|creativo|imagen|foto|dise[nñ]o).{0,140}(?:\?|elige|utilicemos|usar)",
            previous,
        ))
        or bool(_admira_latest_campaign_routing_context())
    )
    direct_media = direct_media or creative_direction
    if direct_media:
        return True
    if not re.fullmatch(
        r"(?:s[ií]|si|ok(?:ay)?|adelante|me gusta|aprobado|aprobada|de acuerdo|"
        r"sigamos|contin[uú]a(?:mos)?|hazlo)[.!?\s]*",
        latest,
    ):
        return False
    # A short approval authorizes media only when the preceding assistant turn
    # actually presented a concept/copy and asked the buyer to approve it.
    if _admira_latest_creative_approval(messages):
        return False
    return bool(
        re.search(r"(?:concepto|propuesta creativa|idea creativa|angulo|ángulo)", previous)
        and re.search(r"(?:copy|texto principal|t[ií]tulo|headline|creativo|imagen)", previous)
        and re.search(r"(?:aprueb|parece|opini[oó]n|visto bueno|de acuerdo)", previous)
    )


def _admira_budget_detail_turn(messages):
    """Return true when the latest buyer turn only supplies a daily budget."""
    latest = ""
    for message in reversed(messages or []):
        if not isinstance(message, dict) or str(message.get("role") or "").lower() != "user":
            continue
        content = message.get("content")
        if isinstance(content, list):
            content = " ".join(
                str(item.get("text") or item.get("content") or "")
                for item in content if isinstance(item, dict)
            )
        latest = _strip_admira_runtime_injections(str(content or "")).strip().lower()
        break
    if not latest or len(latest) > 180:
        return False
    has_amount = bool(re.search(
        r"\b\d[\d\s.,]*(?:\s*mil)?\s*(?:cop|usd|eur|mxn|"
        r"pesos?|d[oó]lares?|euros?)\b",
        latest,
    ))
    daily = bool(re.search(r"\b(?:al\s+d[ií]a|por\s+d[ií]a|diari[oa]|daily)\b", latest))
    # If the same turn explicitly requests media, it is not budget-only.
    return has_amount and daily and not _admira_latest_media_request_or_approval(messages)


def _admira_existing_creative_reuse_requested(messages):
    """Recognize an explicit reuse decision without constraining normal wording.

    This is only a negative media-production guard.  The destination compiler
    and recent-creative lookup remain available, so a buyer can refer to an
    existing asset naturally instead of supplying an internal ID.
    """
    text = _nvidia_routing_text(messages)
    direct = bool(re.search(
        r"(?:\b(?:reutiliza|reutilizar|reuse|existing\s+(?:image|creative|asset))\b|"
        r"\busa\b.{0,90}\b(?:creativo|imagen|foto|asset)\b.{0,90}"
        r"\b(?:existente|anterior|previo|previa|de\s+hoy|de\s+ayer|que\s+(?:creaste|preparaste|hiciste|generaste))\b|"
        r"\b(?:no|sin)\s+(?:crees|crear|generes|generar|produzcas|producir|hagas|hacer)\b.{0,45}"
        r"\b(?:otra|otro|nueva|nuevo)?\s*(?:imagen|creativo|foto|asset)\b)",
        text,
    ))
    if direct:
        return True
    if not _admira_campaign_continuation_requested(messages):
        return False
    if re.search(r"\b(?:nueva|nuevo|otra|otro)\s+(?:imagen|creativo|foto|asset)\b", text):
        return False
    context = _admira_latest_campaign_routing_context()
    return bool(context and re.search(
        r"(?:creativo\s+reutilizado|creative_decision.{0,60}reuse|"
        r"creative_approved\s*:\s*true|creativo.{0,40}aprobado)",
        context,
    ))


def _nvidia_request_profile(messages):
    text = _nvidia_routing_text(messages)
    campaign_context = any(marker in text for marker in ADMIRA_NVIDIA_CAMPAIGN_TERMS)
    explicit_campaign_stack = any(marker in text for marker in (
        "campaign", "campaña", "ad set", "conjunto de anuncios", "meta ads",
        "campaña publicitaria", "campaign stack",
    ))
    action_requested = any(
        re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", text)
        for marker in ADMIRA_NVIDIA_CAMPAIGN_ACTION_TERMS
    )
    # Treat a buyer introducing their business as onboarding even when they
    # mention a future campaign or destination.  The mandatory first-run
    # sequence is business -> organic proposal -> Facebook -> brand -> Ads;
    # exposing the campaign registry here encourages a premature jump. Do not
    # let an incidental phrase inside approved ad copy/message (for example,
    # "asesoría para mi empresa") override an explicit campaign-creation
    # request.
    business_introduction = any(marker in text for marker in (
        "primera conversación", "primera conversacion", "primera vez",
        "mi negocio es", "mi empresa es", "mi clínica es", "mi clinica es",
        "tengo un negocio", "tengo una empresa", "tengo una clínica", "tengo una clinica",
        "my business is", "my company is", "i run a business", "i own a company",
        "first conversation", "first time",
    ))
    if business_introduction and not (explicit_campaign_stack and action_requested):
        return "onboarding"
    # This must win over the generic campaign profile only when the buyer is
    # creating the form itself. "Campaña de formulario" is instead routed to
    # the destination-specific campaign creator.
    # is a campaign-related task, but its initial creation has a much smaller
    # and safer contract than staging the eventual campaign.
    if (
        "create_lead_form" in text
        or "missing_lead_form_detail" in text
        or any(marker in text for marker in ADMIRA_NVIDIA_LEAD_FORM_TERMS)
    ) and not explicit_campaign_stack:
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
    if campaign_context:
        # Destination-specific Meta payloads deserve their own small tool
        # registry even when the buyer also says "create campaign".
        if any(marker in text for marker in ADMIRA_NVIDIA_MESSAGING_CAMPAIGN_TERMS):
            return "messaging_campaign"
        # Use word boundaries here: substring matching treats the noun/adjective
        # ``campañas activas`` as the command ``activa`` and exposes mutation
        # tools during a read-only status question.
        read_only_requested = any(marker in text for marker in (
            "consulta", "consultar", "revisa", "revisar", "lista", "listar",
            "muestra", "mostrar", "cuántas", "cuantas", "estado", "status",
            "read", "inspect", "check", "show", "list",
        ))
        # "Create a campaign with approved creatives" belongs to execution;
        # media routing is for an explicit request to produce the media.
        if (
            any(marker in text for marker in ADMIRA_NVIDIA_CAMPAIGN_MEDIA_TERMS)
            and any(marker in text for marker in ADMIRA_NVIDIA_MEDIA_PRODUCTION_TERMS)
        ):
            return "campaign_media"
        if action_requested:
            return "campaign_execution"
        if read_only_requested:
            return "insights"
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


ADMIRA_CAMPAIGN_CREATOR_TOOLS = {
    "create_whatsapp_campaign",
    "create_lead_form_campaign",
    "create_website_campaign",
    "create_messaging_campaign",
    "create_app_campaign",
    "create_on_meta_campaign",
}
ADMIRA_CAMPAIGN_EDIT_SUPPORT_TOOLS = {
    "get_real_meta_context", "search_meta_targeting", "inspect_adset_targeting",
    "review_signal_quality", "edit_campaign", "list_pending_approvals",
    "approve_action", "reject_action", "save_ads_onboarding", "save_ad_brief",
    "save_durable_memory", "codex_image_generate", "list_recent_creatives",
    "fetch_public_asset", "save_content_asset",
}


def _admira_campaign_edit_requested(messages):
    text = _nvidia_routing_text(messages)
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")

    def contains_term(marker):
        normalized = unicodedata.normalize("NFKD", str(marker or "")).encode("ascii", "ignore").decode("ascii")
        return bool(normalized and re.search(rf"(?<!\w){re.escape(normalized)}(?!\w)", plain))

    campaign_named = any(contains_term(marker) for marker in ADMIRA_NVIDIA_CAMPAIGN_TERMS)
    action = any(contains_term(marker) for marker in ADMIRA_CAMPAIGN_EDIT_ACTION_TERMS) or bool(re.search(
        r"\b(?:baj|reduc|aument|ajust|modific|cambi|actualiz|reemplaz|quit|agreg|anad|sub)\w*\b",
        plain,
    ))
    if not action:
        return False
    if any(marker in text for marker in ("crear una campaña", "crea una campaña", "create a campaign", "lanzar una campaña")) and not any(marker in text for marker in ("editar", "edit", "modificar", "cambiar una campaña", "change the campaign")):
        return False
    if campaign_named:
        return True

    # A second Telegram message can naturally say only "en la de Miami usa
    # Stories".  It is still an edit when a recent campaign-edit scope exists;
    # transition words such as "ahora" or "otra" are deliberately unnecessary.
    scoped_reference = bool(re.search(
        r"\b(?:en|para|de)\s+(?:la|el)\s+de\s+\w+|"
        r"\b(?:esa|ese|la\s+misma|el\s+mismo|tambien|también)\b",
        text,
    ))
    edit_field = any(marker in plain for marker in (
        "presupuesto", "budget", "usd", "cop", "dolar", "peso", "ubicacion", "location",
        "miami", "cartagena", "edad", "genero", "interest", "interes", "placement",
        "stories", "reels", "facebook", "instagram", "texto", "titular", "headline",
        "enlace", "link", "creativo", "imagen", "video", "mensaje", "whatsapp",
    )) or bool(re.search(r"(?:[$€£]|\b\d+(?:[.,]\d+)?\s*(?:usd|cop|eur|mxn)\b)", plain))
    # "En la de WhatsApp bájame..." is already a complete natural campaign
    # reference even if the buyer omits the noun "campaign". It does not need
    # a magic transition word or an existing server-side conversation file.
    if scoped_reference and edit_field:
        return True

    root = Path(str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "/app").strip())
    index_path = root / "dashboard" / "data" / "campaign-edit-workflows" / "conversation-index.json"
    try:
        recent_scope = time.time() - index_path.stat().st_mtime <= 24 * 60 * 60
    except OSError:
        recent_scope = False
    if not recent_scope:
        return False
    return bool(scoped_reference or edit_field)
ADMIRA_CAMPAIGN_CREATION_SUPPORT_TOOLS = {
    "get_real_meta_context",
    "get_meta_oauth_workspaces",
    "select_meta_oauth_workspace",
    "preflight_campaign",
    "search_meta_targeting",
    "inspect_adset_targeting",
    "review_signal_quality",
    # Campaign work often discovers that the current asset is missing,
    # unsuitable, or needs another variant. Keep creative production and the
    # three-day recovery library available while exposing only one destination
    # campaign creator.
    "fetch_public_asset",
    "codex_image_generate",
    "list_recent_creatives",
    "codex_creative_plan",
    "search_motion_graphic_recipes",
    "generate_motion_graphic_video",
    "save_content_asset",
    "save_business_memory",
    "save_brand_memory",
    "save_product_memory",
    "save_creative_references",
    "save_ads_onboarding",
    "save_ad_brief",
    "save_durable_memory",
}


def _admira_destination_campaign_creator(messages):
    """Return the one campaign creator when the buyer named a destination."""
    text = _nvidia_routing_text(messages)

    def affirmed(marker):
        """Return true when at least one marker occurrence is not negated."""
        for match in re.finditer(re.escape(marker), text):
            prefix = text[max(0, match.start() - 55):match.start()]
            if re.search(
                r"(?:\bno\b|\bsin\b|\bni\b|\bnot\b|\bwithout\b)"
                r"(?:\s+\w+){0,4}\s*$",
                prefix,
            ):
                continue
            return True
        return False

    # Resolve affirmative alternatives before WhatsApp because buyers often
    # say "Messenger, not WhatsApp" or "Instagram Direct, no WhatsApp".
    if any(affirmed(marker) for marker in ("messenger", "instagram direct", "instagram dm")):
        return "create_messaging_campaign"
    if affirmed("whatsapp"):
        return "create_whatsapp_campaign"
    if any(marker in text for marker in ADMIRA_NVIDIA_LEAD_FORM_TERMS):
        return "create_lead_form_campaign"
    if any(marker in text for marker in (
        "sitio web", "página web", "pagina web", "website", "landing page",
        "tienda online", "ecommerce", "e-commerce",
    )):
        return "create_website_campaign"
    if any(marker in text for marker in (
        "promoción de app", "promocion de app", "instalación de app",
        "instalacion de app", "app promotion", "app install",
    )):
        return "create_app_campaign"
    if any(marker in text for marker in (
        "reconocimiento", "awareness", "visualizaciones de video",
        "video views", "interacción", "interaccion", "engagement",
    )):
        return "create_on_meta_campaign"
    if _admira_campaign_continuation_requested(messages):
        context = _admira_latest_campaign_routing_context()
        if "destination contract: `whatsapp`" in context or "destination contract: whatsapp" in context:
            return "create_whatsapp_campaign"
        if "destination contract: `messaging`" in context or "destination contract: messaging" in context:
            return "create_messaging_campaign"
        if "destination contract: `website`" in context or "destination contract: website" in context:
            return "create_website_campaign"
        if "destination contract: `lead_form`" in context or "destination contract: lead_form" in context:
            return "create_lead_form_campaign"
    return ""


def _admira_tool_result_mappings(value, depth=0):
    """Yield JSON mappings embedded in Hermes tool-result envelopes.

    Tool rows are untrusted data and may arrive as a plain object, a JSON
    string, or inside Hermes' `<untrusted_tool_result>` wrapper.  This helper
    reads only their structured outcome fields; it never treats their text as
    an instruction.
    """
    if depth > 8:
        return
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _admira_tool_result_mappings(item, depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _admira_tool_result_mappings(item, depth + 1)
        return
    if not isinstance(value, str):
        return
    candidates = [value.strip()]
    wrapped = re.search(
        r"<untrusted_tool_result\b[^>]*>\s*(?:[^\n]*\n)?\s*(.*?)\s*</untrusted_tool_result>",
        value,
        re.S | re.I,
    )
    if wrapped:
        candidates.append(wrapped.group(1).strip())
    decoder = json.JSONDecoder()
    for candidate in candidates:
        starts = [0] if candidate.startswith(("{", "[")) else [match.start() for match in re.finditer(r"[\[{]", candidate)]
        for start in starts:
            try:
                decoded, _end = decoder.raw_decode(candidate[start:])
            except (TypeError, ValueError):
                continue
            yield from _admira_tool_result_mappings(decoded, depth + 1)
            break


def _admira_terminal_backend_block(messages):
    """Return the newest non-retryable backend refusal in this buyer turn."""
    if not isinstance(messages, list):
        return {}
    last_buyer = max(
        (index for index, item in enumerate(messages) if isinstance(item, dict) and item.get("role") == "user"),
        default=-1,
    )
    for item in reversed(messages[last_buyer + 1:]):
        if not isinstance(item, dict) or item.get("role") not in {"tool", "function", "tool_result"}:
            continue
        tool_name = _nvidia_normalize_tool_name(
            item.get("tool_name") or item.get("name") or ""
        )
        for outcome in _admira_tool_result_mappings(item.get("content")):
            if outcome.get("blocked") is not True or outcome.get("executed") is not False:
                continue
            if outcome.get("retryable") is True:
                continue
            reply = str(outcome.get("reply") or "").strip()
            reason = str(outcome.get("reason") or "").strip()
            if reply and reason:
                return {
                    "tool": tool_name,
                    "reason": reason,
                    "reply": reply[:1800],
                }
    return {}


def _admira_route_request_tools(api_kwargs):
    """Apply one model-independent MCP registry contract before inference.

    JSON Schema remains authoritative. This function only decides which
    already-defined schemas are visible for the buyer's current intent.
    """
    if not isinstance(api_kwargs, dict):
        return api_kwargs
    request = dict(api_kwargs)
    messages = request.get("messages") if isinstance(request.get("messages"), list) else []
    tools = request.get("tools") if isinstance(request.get("tools"), list) else []
    terminal_block = _admira_terminal_backend_block(messages)
    if terminal_block:
        # A tool has already determined that this turn cannot mutate state.
        # Re-executing the same or a related mutating tool cannot discover new
        # buyer authority, and previously caused repeated calls followed by a
        # provider quota failure.  End the loop with the authoritative result
        # instead of using language heuristics or keyword routing.
        request["tools"] = []
        request["tool_choice"] = "none"
        request["parallel_tool_calls"] = False
        request["messages"] = _nvidia_append_private_instruction(
            messages,
            "[INTERNAL BACKEND OUTCOME RULE — never quote] A product tool already returned a terminal, non-retryable block for this buyer turn. Do not call any tool, do not retry the operation, and do not claim it succeeded. Respond only with a concise, faithful buyer-facing explanation of this exact backend outcome: "
            + terminal_block["reply"]
            + " [END INTERNAL BACKEND OUTCOME RULE]",
        )
        return request
    if _admira_freeform_agent_mode():
        # Freeform mode keeps the complete registry for natural-language
        # interpretation, but the two sequencing boundaries remain product
        # invariants: a creative direction gets the image first, and a
        # campaign/detail turn cannot leak image production into the model's
        # tool choices. Otherwise an older generated image can make a later
        # “texto grande” turn jump straight to campaign approval.
        creator = _admira_destination_campaign_creator(messages)
        latest_media_ready = _admira_latest_media_request_or_approval(messages)
        recent_context = _admira_latest_campaign_routing_context()
        if not creator and (latest_media_ready or recent_context):
            if "destination contract: `whatsapp`" in recent_context or "destination contract: whatsapp" in recent_context:
                creator = "create_whatsapp_campaign"
            elif "destination contract: `messaging`" in recent_context or "destination contract: messaging" in recent_context:
                creator = "create_messaging_campaign"
            elif "destination contract: `lead_form`" in recent_context or "destination contract: lead_form" in recent_context:
                creator = "create_lead_form_campaign"
            elif "destination contract: `website`" in recent_context or "destination contract: website" in recent_context:
                creator = "create_website_campaign"
        creative_approval_turn = _admira_latest_creative_approval(messages)
        campaign_in_scope = bool(creator or "destination contract:" in recent_context)
        blocked = set()
        if campaign_in_scope and not creative_approval_turn:
            # A destination mention alone is never enough to expose a creator.
            # The buyer must first see and resolve the copy/title and the
            # delivered creative; this remains true in freeform mode.
            blocked.update(ADMIRA_CAMPAIGN_CREATOR_TOOLS)
        if campaign_in_scope and (not latest_media_ready or creative_approval_turn):
            blocked.update({
                "codex_image_generate", "codex_creative_plan",
                "search_motion_graphic_recipes", "generate_motion_graphic_video",
            })
        filtered = [
            tool for tool in tools
            if _nvidia_normalize_tool_name(_nvidia_tool_name(tool)) not in blocked
        ]
        request["tools"] = _nvidia_restore_admira_tool_schemas(filtered)
        request.pop("tool_choice", None)
        request.pop("parallel_tool_calls", None)
        routed_tools = request.get("tools") if isinstance(request.get("tools"), list) else []
        if latest_media_ready and not creative_approval_turn:
            image_tool_name = next((
                _nvidia_tool_name(tool)
                for tool in routed_tools
                if _nvidia_normalize_tool_name(_nvidia_tool_name(tool)) == "codex_image_generate"
            ), "")
            if image_tool_name:
                request["tool_choice"] = {
                    "type": "function",
                    "function": {"name": image_tool_name},
                }
                request["parallel_tool_calls"] = False
            if campaign_in_scope:
                request["messages"] = _nvidia_append_private_instruction(
                    messages,
                    "[INTERNAL CREATIVE DRAFT HANDOFF RULE — never quote] The buyer has just requested or selected a visual direction. Call only the exposed creative/image tool and deliver the actual generated media in this turn. A textual direction such as 'texto grande' is not the creative asset. Do not call a campaign creator or ask for campaign approval until the buyer has seen and separately approved the attached creative. [END INTERNAL CREATIVE DRAFT HANDOFF RULE]",
                )
        elif campaign_in_scope and creative_approval_turn:
            request["messages"] = _nvidia_append_private_instruction(
                messages,
                _admira_campaign_compiler_instruction(messages, creator),
            )
        elif campaign_in_scope and not latest_media_ready:
            request["messages"] = _nvidia_append_private_instruction(
                messages,
                "[INTERNAL CAMPAIGN STRATEGY-FIRST RULE — never quote] This buyer turn supplies campaign context or a field answer, not an image-production order. Treat a newly mentioned campaign or offer as a new scope. Read live Meta and the saved business/product/ads context, propose the commercial direction, economics, exact copy/title/message and visual concept, and wait for correction/approval. Do not call image/video tools on this turn. [END INTERNAL CAMPAIGN STRATEGY-FIRST RULE]",
            )
        return request
    profile = _nvidia_request_profile(messages)
    direct_profiles = {
        "onboarding", "lead_form", "campaign_strategy", "campaign_execution",
        "messaging_campaign", "campaign_media",
    }
    if profile in direct_profiles:
        allowed = set(ADMIRA_NVIDIA_TOOL_PROFILES[profile])
    else:
        allowed = set(ADMIRA_NVIDIA_TOOL_PROFILES.get("core", set()))
        allowed.update(ADMIRA_NVIDIA_TOOL_PROFILES.get(profile, set()))

    creator = _admira_destination_campaign_creator(messages)
    edit_requested = _admira_campaign_edit_requested(messages)
    deferred = _admira_campaign_creation_deferred(messages)
    clarification_requested = _admira_buyer_requests_clarification(messages)
    if clarification_requested:
        # A short repair such as “¿qué?” asks the agent to explain its previous
        # answer.  It is never permission to retry a campaign or media mutation.
        allowed = {"connect_chatgpt"}
    if deferred:
        allowed.difference_update(ADMIRA_CAMPAIGN_CREATOR_TOOLS)
        allowed.difference_update({
            "codex_image_generate", "codex_creative_plan",
            "generate_motion_graphic_video",
        })
    if not clarification_requested and edit_requested and not deferred and profile in {"campaign_execution", "messaging_campaign"}:
        allowed = set(ADMIRA_CAMPAIGN_EDIT_SUPPORT_TOOLS)
    elif not clarification_requested and creator and not deferred and profile in {"campaign_execution", "messaging_campaign"}:
        # Once destination is explicit, advertise one creator plus read-only
        # preparation/memory helpers—not every campaign mutation in Admira.
        allowed = set(ADMIRA_CAMPAIGN_CREATION_SUPPORT_TOOLS)
        allowed.add(creator)
        if _admira_existing_creative_reuse_requested(messages):
            allowed.difference_update({
                "codex_image_generate", "codex_creative_plan",
                "search_motion_graphic_recipes", "generate_motion_graphic_video",
            })
    # Account authentication is a product action, not campaign intent. Keep
    # its dedicated tool available in every conversational profile so the
    # language model can understand arbitrary wording and request the secure
    # link without inventing terminal commands.
    allowed.add("connect_chatgpt")
    allowed.update(_nvidia_used_tool_names(messages))
    latest_media_ready = _admira_latest_media_request_or_approval(messages)
    creative_approval_turn = _admira_latest_creative_approval(messages)
    if (
        creator
        and profile in {"campaign_execution", "messaging_campaign"}
        and not creative_approval_turn
    ):
        # Do not let a generic “create/leave paused?” turn reach the
        # destination MCP. The model must first present the exact ad package
        # and deliver/review the creative with the buyer.
        allowed.discard(creator)
    if creator and profile in {"campaign_execution", "messaging_campaign"} and latest_media_ready and not creative_approval_turn:
        # A direction or direct request for a new creative is a visual-draft
        # turn. Do not let the campaign creator compete with Image 2 before the
        # buyer has seen and approved the actual generated asset.
        allowed.discard(creator)
    if clarification_requested or _admira_budget_detail_turn(messages) or (
        creator and profile in {"campaign_strategy", "campaign_execution", "messaging_campaign"}
        and not latest_media_ready
    ):
        # Creative production stays available to campaign conversations, but
        # only on the buyer turn that actually asks for it (or approves a
        # concept/copy read-back). A prior Image call, a new service, or a
        # budget/detail follow-up must not leak the mutating media tool into the
        # next turn.
        allowed.difference_update({
            "codex_image_generate", "codex_creative_plan",
            "search_motion_graphic_recipes", "generate_motion_graphic_video",
        })
    if creator and _nvidia_active_tool_call_count(messages, creator) >= 2:
        # One initial compilation plus one corrected full-brief retry is the
        # maximum for a buyer turn. More calls only consume quota and repeat
        # the same contract error; the model must report the precise blocker.
        allowed.discard(creator)

    filtered = []
    for tool in tools:
        name = _nvidia_tool_name(tool)
        normalized = _nvidia_normalize_tool_name(name)
        is_admira = name.lower().startswith(("mcp_admira_", "admira_"))
        if not is_admira or normalized in allowed:
            filtered.append(tool)
    request["tools"] = _nvidia_restore_admira_tool_schemas(filtered)
    if clarification_requested:
        request["messages"] = _nvidia_append_private_instruction(
            messages,
            "[INTERNAL CONVERSATION REPAIR RULE — never quote] The buyer is questioning or "
            "correcting the immediately preceding reply. Explain it naturally and briefly. Do not "
            "call campaign, image, memory, or Meta mutation tools, and do not claim any action ran. "
            "[END INTERNAL CONVERSATION REPAIR RULE]",
        )
    elif deferred:
        request["messages"] = _nvidia_append_private_instruction(
            messages,
            "[INTERNAL DEFERRED CAMPAIGN RULE — never quote] The buyer explicitly said not to create yet. "
            "Acknowledge the supplied details briefly and wait for the final confirmation. Do not ask for "
            "another approval and do not call any campaign or media creation tool. "
            "[END INTERNAL DEFERRED CAMPAIGN RULE]",
        )
    elif edit_requested and profile in {"campaign_execution", "messaging_campaign"}:
        request["messages"] = _nvidia_append_private_instruction(
            messages,
            "[INTERNAL CAMPAIGN EDIT RULE — never quote] Use mcp_admira_edit_campaign for each natural-language edit. Resolve the campaign mentioned in the current message independently against live Meta. If it names a different campaign, create a separate scoped draft even when the buyer does not say 'another' or 'now'. If it has only a pronoun, continue the last unambiguous campaign. Send the buyer's exact current request in change_request; do not invent IDs or assemble a full campaign payload. [END INTERNAL CAMPAIGN EDIT RULE]",
        )
    elif creator and profile in {"campaign_execution", "messaging_campaign"} and latest_media_ready and not creative_approval_turn:
        request["messages"] = _nvidia_append_private_instruction(
            messages,
            "[INTERNAL CREATIVE DRAFT HANDOFF RULE — never quote] The buyer has just requested or selected a visual direction. Call only the exposed creative/image tool with a self-contained active-offer request and deliver the actual generated media in this turn. A textual description such as 'texto grande' is not the creative asset. Do not call any campaign creator, do not ask for campaign approval, and do not claim the campaign is ready until the buyer has seen and separately approved the attached creative. [END INTERNAL CREATIVE DRAFT HANDOFF RULE]",
        )
    elif creator and profile in {"campaign_execution", "messaging_campaign"} and creative_approval_turn:
        request["messages"] = _nvidia_append_private_instruction(
            messages,
            _admira_campaign_compiler_instruction(messages, creator),
        )
    elif creator and profile in {"campaign_execution", "messaging_campaign"} and not latest_media_ready:
        request["messages"] = _nvidia_append_private_instruction(
            messages,
            "[INTERNAL CAMPAIGN STRATEGY-FIRST RULE — never quote] This buyer turn supplies campaign context or a field answer, not an image-production order. Treat a newly mentioned campaign or offer as a new scope: do not activate, resume, or inherit the prior campaign's budget, currency, creative, copy, title, audience, geography, CTA, destination message, or offer. First act as a senior marketing manager: read live Meta plus the saved business/product/ads context; understand the owner's business outcome and time horizon, active offer, ideal customer and trigger, funnel/follow-up, price/cost/capacity and budget currency. Give a concise recommendation with three success signals, break-even logic, and conservative/base/upside test expectations; label unknown figures as assumptions or ranges. Persist stable business facts with save_business_memory, the active offer with save_product_memory, account-wide ads history/defaults only with save_ads_onboarding, and this campaign's goals/KPIs, budget/currency, hypothesis, copy, projection and plan with a uniquely named save_ad_brief. Reuse a returned brief ID only when editing the same campaign; do not reuse another campaign's brief. Treat the brief as planning memory only: for actual spend, delivery, status, CPA/CPL, ROAS, leads, conversations, audience, or learning, use the fresh Meta read and never the brief's estimate. Then propose the exact primary text, distinct title, CTA/message, and concrete visual concept, and ask for the buyer's natural correction or approval. Do not call image/video/creative tools until that concept and copy are approved. Do not call the campaign creator until the current budget/currency and all final ad inputs are resolved. [END INTERNAL CAMPAIGN STRATEGY-FIRST RULE]",
        )
    elif creator and profile in {"campaign_execution", "messaging_campaign"}:
        request["messages"] = _nvidia_append_private_instruction(
            messages,
            _admira_campaign_compiler_instruction(messages, creator),
        )
    routed_tools = request.get("tools") if isinstance(request.get("tools"), list) else tools
    if _admira_latest_media_request_or_approval(messages):
        used = _nvidia_used_tool_names(messages)
        image_tool_name = next((
            _nvidia_tool_name(tool)
            for tool in routed_tools
            if _nvidia_normalize_tool_name(_nvidia_tool_name(tool)) == "codex_image_generate"
        ), "")
        if image_tool_name and "codex_image_generate" not in used:
            request["tool_choice"] = {
                "type": "function",
                "function": {"name": image_tool_name},
            }
            request["parallel_tool_calls"] = False
        elif "codex_image_generate" in used:
            # Compose the buyer reply from this turn's authoritative Image
            # result. Never call it twice or replace the result with memory.
            request["tool_choice"] = "none"
            request["parallel_tool_calls"] = False
    return request


def _admira_gemini_safe_schema(value):
    """Remove OpenAI/JSON-Schema union keywords Gemini native rejects.

    Gemini's native function declaration validator requires every parameter
    branch to be an object with declared properties. Our MCP contracts use
    anyOf/oneOf for backwards-compatible aliases, so retain the declared
    properties while omitting those validator-incompatible union branches.
    The product bridge still performs the authoritative argument validation.
    """
    if isinstance(value, list):
        return [_admira_gemini_safe_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: _admira_gemini_safe_schema(item)
        for key, item in value.items()
        if key not in {"anyOf", "oneOf", "allOf"}
    }


def _admira_gemini_safe_request(api_kwargs, agent):
    provider = str(getattr(agent, "provider", "") or "").strip().lower().replace("_", "-")
    if provider not in {"gemini", "google", "google-ai-studio", "google-ai-studio-api"}:
        return api_kwargs
    if not isinstance(api_kwargs, dict) or not isinstance(api_kwargs.get("tools"), list):
        return api_kwargs
    request = dict(api_kwargs)
    request["tools"] = _admira_gemini_safe_schema(request["tools"])
    return request


def _nvidia_lead_form_retry_instruction(messages):
    """Keep the native-form turn on one strict tool call.

    Hosted NVIDIA models behave reliably with one narrow JSON schema, but can
    emit ``create_lead_form({})`` and start inspecting files when the same turn
    advertises unrelated native and product tools.  The tool handler remains
    the source of truth; this private instruction only prevents an unbounded
    recovery loop and never invents missing buyer data.
    """
    text = _nvidia_message_text(messages)
    retry = " The previous call was incomplete, so this is the only permitted retry." if (
        "missing_lead_form_detail" in text or "empty_tool_arguments" in text
    ) else ""
    return (
        "[INTERNAL LEAD-FORM EXECUTION RULE — never quote] Use only the exposed "
        "lead-form tools. Do not inspect files, search code, browse, or call memory "
        "tools. Call create_lead_form at most once and only with a JSON object that "
        "includes non-empty page_id, name, privacy_policy_url, and a flat questions "
        "array. Never call it with {} or wrap arrays in item/$text objects. Recover "
        "exact values already present in the conversation. If a required value is "
        "genuinely absent, ask one concise combined question instead of calling a tool."
        + retry + " "
        "[END INTERNAL LEAD-FORM RETRY RULE]"
    )


def _nvidia_campaign_retry_instruction(messages):
    """Stop malformed campaign retries from dropping already known fields."""
    text = _nvidia_message_text(messages)
    if not any(marker in text for marker in (
        "missing_campaign_creation_detail",
        "targeting_gender_invalid",
        "targeting_age_invalid",
        "targeting_location",
    )):
        return ""
    return (
        "[INTERNAL CAMPAIGN RETRY RULE — never quote] The previous paused-campaign "
        "brief failed validation. Make at most one corrected call to the same destination-specific "
        "campaign tool, with exactly one argument named brief_markdown. Preserve every confirmed "
        "buyer value from the complete brief; never reduce it to only the fields named by the last "
        "error. If the correction cannot be formed without guessing, report the validation error "
        "instead of looping. "
        "[END INTERNAL CAMPAIGN RETRY RULE]"
    )


def _admira_campaign_compiler_instruction(messages, creator):
    """Give every provider the same one-brief destination contract."""
    reuse = (
        " The buyer explicitly chose an existing creative: do not call any image/video generation "
        "tool. If its exact recent path is not already known, call list_recent_creatives first."
        if _admira_existing_creative_reuse_requested(messages) else ""
    )
    return (
        "[INTERNAL DESTINATION CAMPAIGN COMPILER RULE — never quote] The exposed destination "
        f"creator is {creator}. Call it with exactly one argument: brief_markdown. Write one complete "
        "natural-language Markdown brief copied from the buyer's current message and confirmed context. "
        "It must preserve the exact campaign name, amount and currency wording, destination, geography, "
        "ages, genders, placement decision, creative asset/path, primary text, headline, destination "
        "message or URL/form/app details, and every explicit approval. For WhatsApp, explicitly write "
        "budget_confirmation, creative_decision, creative_approved: true, and "
        "prefilled_message_approved: true when those decisions were confirmed. For a multi-ad-set brief, "
        "write locations, ages, genders, placements, targeting_mode, budget, destination message, and ads "
        "inside every ad set; mixed manual/Advantage+ campaigns require targeting_mode on every set. "
        "Do not construct the final JSON; "
        "the campaign compiler does that privately. Do not split the brief into incremental calls. If a genuinely required "
        "buyer decision is absent, ask one concise question instead of calling the creator. Before the handoff, the saved "
        "brief should also capture the business outcome/time horizon, active offer, ideal customer, funnel/follow-up, "
        "known price/cost/capacity assumptions, three success metrics, break-even logic, test projection, and review plan. "
        "Use save_business_memory for stable business facts, save_product_memory for the active child offer, save_ads_onboarding "
        "only for account-wide history/defaults, and save_ad_brief for this campaign's confirmed goals/KPIs and plan; never "
        "pretend the payload itself is the marketing plan. After a compiler "
        "validation error, retry at most once with the entire corrected brief, never only the missing fields."
        " Image and video tools may remain visible during campaign work, but call them only when the buyer "
        "explicitly asks to create, generate, redesign, or produce a creative. A budget, destination, approval, "
        "or statement that no creative exists is not an image-generation request; ask naturally whether the "
        "buyer wants a new creative instead of calling an image tool with missing arguments."
        + reuse + " [END INTERNAL DESTINATION CAMPAIGN COMPILER RULE]"
    )


def _admira_campaign_verbatim_source(messages, max_user_turns=3, max_chars=20_000):
    """Keep the buyer's recent campaign words authoritative over a summary.

    The destination tool still receives one Markdown argument, but Hermes can
    accidentally omit a placement or Meta ID while rewriting a long Telegram
    exchange.  Capture only the active three buyer turns; never the system
    prompt, assistant prose, or an older campaign.
    """
    turns = []
    for message in reversed(messages or []):
        if not isinstance(message, dict) or str(message.get("role") or "").lower() != "user":
            continue
        content = message.get("content")
        if isinstance(content, list):
            content = " ".join(
                str(item.get("text") or item.get("content") or "")
                for item in content if isinstance(item, dict)
            )
        text = _strip_admira_runtime_injections(str(content or "")).strip()
        if text:
            turns.append(text)
        if len(turns) >= max_user_turns:
            break
    turns.reverse()
    source = "\n\n".join(
        f"### Buyer message {index}\n{text}"
        for index, text in enumerate(turns, 1)
    )
    return source[-max_chars:]


def _admira_attach_verbatim_campaign_source(response, source):
    """Append recent buyer messages to a destination creator's tool brief."""
    source = str(source or "").strip()
    if not source or response is None:
        return response
    choices = response.get("choices") if isinstance(response, dict) else getattr(response, "choices", None)
    for choice in choices or []:
        message = choice.get("message") if isinstance(choice, dict) else getattr(choice, "message", None)
        calls = message.get("tool_calls") if isinstance(message, dict) else getattr(message, "tool_calls", None)
        for call in calls or []:
            function = call.get("function") if isinstance(call, dict) else getattr(call, "function", None)
            name = function.get("name") if isinstance(function, dict) else getattr(function, "name", "")
            if _nvidia_normalize_tool_name(name) not in ADMIRA_CAMPAIGN_CREATOR_TOOLS:
                continue
            raw_arguments = function.get("arguments") if isinstance(function, dict) else getattr(function, "arguments", None)
            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments or {})
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            brief = str(arguments.get("brief_markdown") or "").strip()
            marker = "## Verbatim recent buyer messages (authoritative)"
            if not brief or marker in brief:
                continue
            arguments["brief_markdown"] = f"{brief}\n\n{marker}\n{source}"
            encoded = json.dumps(arguments, ensure_ascii=False)
            if isinstance(function, dict):
                function["arguments"] = encoded
            else:
                try:
                    function.arguments = encoded
                except (AttributeError, TypeError, ValueError):
                    continue
    return response


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


def _nvidia_active_tool_call_count(messages, normalized_name):
    """Count one tool in the current buyer turn without scanning old turns."""
    wanted = _nvidia_normalize_tool_name(normalized_name)
    count = 0
    for message in reversed(messages or []):
        if not isinstance(message, dict):
            continue
        if message.get("role") == "user":
            break
        for call in message.get("tool_calls") or []:
            function = call.get("function") if isinstance(call, dict) else {}
            name = function.get("name") if isinstance(function, dict) else ""
            if _nvidia_normalize_tool_name(name) == wanted:
                count += 1
    return count


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


def _nvidia_restore_admira_tool_schemas(tools):
    """Apply the current product-owned schema to every Admira tool.

    Hermes 0.18 can flatten an MCP ``inputSchema`` or retain an older non-empty
    schema in its persistent registry.  A non-empty stale schema is just as
    unsafe as an empty one after a destination contract migration, so replace
    both with the canonical runtime schema immediately before every provider
    request.  Hermes-native tools and the shared registry remain untouched.
    """
    try:
        from admira_mcp_server import TOOL_INPUT_SCHEMAS
    except Exception:
        return list(tools or [])
    restored = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            restored.append(tool)
            continue
        name = _nvidia_tool_name(tool)
        normalized = _nvidia_normalize_tool_name(name)
        schema = TOOL_INPUT_SCHEMAS.get(normalized)
        function = tool.get("function") if isinstance(tool.get("function"), dict) else None
        if not schema or not name.lower().startswith(("mcp_admira_", "admira_")):
            restored.append(tool)
            continue
        cloned = dict(tool)
        if function is not None:
            cloned_function = dict(function)
            cloned_function["parameters"] = copy.deepcopy(schema)
            cloned["function"] = cloned_function
        else:
            # The Responses API represents functions as a flat object:
            # {type, name, description, parameters, strict}.  Hermes can
            # flatten MCP tools into this shape before the provider hook, so
            # looking only under ``function`` silently leaves an empty schema
            # and lets the model omit required transactional evidence.
            cloned["parameters"] = copy.deepcopy(schema)
        restored.append(cloned)
    return restored


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

    if _admira_freeform_agent_mode():
        request["tools"] = _nvidia_restore_admira_tool_schemas(tools)
        request.pop("tool_choice", None)
        request.pop("parallel_tool_calls", None)
        return request

    before_tools = len(tools)
    profile = _nvidia_request_profile(messages)
    # The specialised campaign workflows are self-contained.  Do not append
    # the generic core registry or a narrow form/strategy/execution request
    # grows back into the previous all-in-one campaign payload.
    direct_profiles = {
        "onboarding", "lead_form", "campaign_strategy", "campaign_execution",
        "messaging_campaign", "campaign_media",
    }
    if profile in direct_profiles:
        allowed = set(ADMIRA_NVIDIA_TOOL_PROFILES[profile])
    else:
        allowed = set(ADMIRA_NVIDIA_TOOL_PROFILES.get("core", set()))
        allowed.update(ADMIRA_NVIDIA_TOOL_PROFILES.get(profile, set()))
    creator = _admira_destination_campaign_creator(messages)
    edit_requested = _admira_campaign_edit_requested(messages)
    deferred = _admira_campaign_creation_deferred(messages)
    clarification_requested = _admira_buyer_requests_clarification(messages)
    if clarification_requested:
        allowed = {"connect_chatgpt"}
    if deferred:
        allowed.difference_update(ADMIRA_CAMPAIGN_CREATOR_TOOLS)
        allowed.difference_update({
            "codex_image_generate", "codex_creative_plan",
            "generate_motion_graphic_video",
        })
    if not clarification_requested and edit_requested and not deferred and profile in {"campaign_execution", "messaging_campaign"}:
        allowed = set(ADMIRA_CAMPAIGN_EDIT_SUPPORT_TOOLS)
    elif not clarification_requested and creator and not deferred and profile in {"campaign_execution", "messaging_campaign"}:
        # Keep fallback/provider routing identical to the model-independent
        # route: one destination creator plus creative production/recovery and
        # workspace-selection support. Otherwise Terra/NIM sees a different
        # product from Gemini after failover.
        allowed = set(ADMIRA_CAMPAIGN_CREATION_SUPPORT_TOOLS)
        allowed.add(creator)
        if _admira_existing_creative_reuse_requested(messages):
            allowed.difference_update({
                "codex_image_generate", "codex_creative_plan",
                "search_motion_graphic_recipes", "generate_motion_graphic_video",
            })
    allowed.add("connect_chatgpt")
    allowed.update(_nvidia_used_tool_names(messages))
    if clarification_requested or _admira_budget_detail_turn(messages):
        allowed.difference_update({
            "codex_image_generate", "codex_creative_plan",
            "search_motion_graphic_recipes", "generate_motion_graphic_video",
        })
    if creator and _nvidia_active_tool_call_count(messages, creator) >= 2:
        allowed.discard(creator)

    filtered = []
    for tool in tools:
        name = _nvidia_tool_name(tool)
        normalized = _nvidia_normalize_tool_name(name)
        if profile == "lead_form" and not name.lower().startswith(("mcp_admira_", "admira_")):
            # A form-creation turn is a bounded transaction. Native file/web/
            # memory tools only give small hosted models an attractive but
            # incorrect escape path after a malformed first call.
            continue
        if profile == "lead_form" and normalized not in allowed:
            continue
        # Hermes-native tools are intentionally preserved. Only the large
        # Admira MCP registry is routed by profile.
        if normalized == "" or not (
            name.lower().startswith(("mcp_admira_", "admira_"))
        ):
            filtered.append(tool)
        elif normalized in allowed:
            filtered.append(tool)
    # An intentionally tool-free profile (the first organic proposal) must
    # actually remove the entire Admira registry.  Keeping the original list
    # when filtering yields zero items silently turns that profile into the
    # old all-tools payload.
    if len(filtered) < before_tools:
        request["tools"] = filtered
    request["tools"] = _nvidia_restore_admira_tool_schemas(request.get("tools") or [])
    # NVIDIA treats an explicit empty tools array differently from a normal
    # text-only request and can return HTTP 404. A tool-free onboarding
    # proposal is valid, so omit the field altogether.
    if not request["tools"]:
        request.pop("tools", None)

    if clarification_requested:
        private_instruction = (
            "[INTERNAL CONVERSATION REPAIR RULE — never quote] The buyer is questioning or "
            "correcting the immediately preceding reply. Explain it naturally and briefly. Do not "
            "call campaign, image, memory, or Meta mutation tools, and do not claim any action ran. "
            "[END INTERNAL CONVERSATION REPAIR RULE]"
        )
    elif profile == "lead_form":
        private_instruction = _nvidia_lead_form_retry_instruction(messages)
    elif edit_requested:
        private_instruction = (
            "[INTERNAL CAMPAIGN EDIT RULE — never quote] Call mcp_admira_edit_campaign with the exact current buyer request. Resolve the current campaign reference independently; a newly named different campaign is a new scope even without transition words. Preserve separate drafts. Do not call a creation tool. [END INTERNAL CAMPAIGN EDIT RULE]"
        )
    elif profile in {"campaign_execution", "messaging_campaign"}:
        private_instruction = _nvidia_campaign_retry_instruction(messages)
    else:
        private_instruction = ""
    prepared_messages = _nvidia_append_private_instruction(messages, private_instruction)
    request["messages"], request["tools"] = _nvidia_compact_request_payload(
        prepared_messages,
        request.get("tools") or [],
    )
    if profile == "lead_form":
        used = _nvidia_used_tool_names(messages)
        create_tool_name = next((
            _nvidia_tool_name(tool)
            for tool in request.get("tools") or []
            if _nvidia_normalize_tool_name(_nvidia_tool_name(tool)) == "create_lead_form"
        ), "")
        if create_tool_name and "create_lead_form" not in used and _nvidia_explicit_lead_form_creation_requested(messages):
            # NVIDIA's hosted MiniMax endpoint fills the strict schema
            # correctly when the function is required; with auto selection it
            # can emit the same function with an empty argument object.
            request["tool_choice"] = {
                "type": "function",
                "function": {"name": create_tool_name},
            }
            request["parallel_tool_calls"] = False
        elif "create_lead_form" in used:
            # The backend already returned the authoritative result. Do not
            # let a hosted model repeat the mutation while composing its final
            # buyer-facing reply.
            request["tool_choice"] = "none"
            request["parallel_tool_calls"] = False

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

    # Nemotron reasoning variants otherwise emit their chain-of-thought in
    # ordinary ``content`` on the hosted endpoint. That is neither useful nor
    # appropriate in a buyer-facing Telegram reply. NVIDIA accepts this
    # template option for these models; keep other NIM payloads untouched.
    model_key = str(request.get("model") or "").strip().lower()
    if "nemotron" in model_key:
        template_kwargs = request.get("chat_template_kwargs")
        template_kwargs = dict(template_kwargs) if isinstance(template_kwargs, dict) else {}
        template_kwargs["enable_thinking"] = False
        request["chat_template_kwargs"] = template_kwargs
        request.pop("reasoning_budget", None)

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
            "estimated_input_tokens": _nvidia_estimated_input_tokens(
                messages, request.get("tools") or []
            ),
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


def _record_nvidia_hook_diagnostic(
    agent,
    api_kwargs,
    *,
    path,
    is_nvidia,
    prepared_profile=None,
    tools_before=None,
):
    """Optionally record that a real Hermes provider seam was reached.

    This is enabled only by the release canary.  It deliberately stores no
    messages, URLs, API keys or tool arguments: the record explains whether a
    third-party Hermes version called the patched seam with a mapping that can
    be normalized before the request goes to NVIDIA.
    """
    path_value = str(os.environ.get("ADMIRA_NVIDIA_HOOK_DIAGNOSTICS_FILE") or "").strip()
    if not path_value:
        return
    try:
        provider = str(getattr(agent, "provider", "") or "").strip().lower().replace("_", "-")
        base_url = str(getattr(agent, "base_url", "") or getattr(agent, "_base_url", "") or "").lower()
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "path": str(path),
            "is_nvidia": bool(is_nvidia),
            "provider": provider,
            "base_url_is_nvidia": "integrate.api.nvidia.com" in base_url,
            "request_is_mapping": isinstance(api_kwargs, dict),
            "request_type": type(api_kwargs).__name__,
            "prepare_already_active": bool(ADMIRA_NVIDIA_PREPARE_ACTIVE.get()),
            "request_diagnostics_configured": bool(
                str(os.environ.get("ADMIRA_NVIDIA_REQUEST_DIAGNOSTICS_FILE") or "").strip()
            ),
        }
        if prepared_profile:
            tools_after = api_kwargs.get("tools") if isinstance(api_kwargs, dict) else []
            schema_summaries = []
            for tool in tools_after or []:
                if not isinstance(tool, dict):
                    continue
                function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
                parameters = function.get("parameters") if isinstance(function.get("parameters"), dict) else {}
                schema_summaries.append({
                    "name": str(function.get("name") or tool.get("name") or ""),
                    "has_parameters": bool(parameters),
                    "required": [str(item) for item in (parameters.get("required") or [])[:16]],
                    "property_names": [str(item) for item in list((parameters.get("properties") or {}).keys())[:32]],
                })
            payload.update({
                "prepared": True,
                "profile": str(prepared_profile),
                "tools_before": int(tools_before or 0),
                "tools_after": len(tools_after or []),
                "estimated_input_tokens": _nvidia_estimated_input_tokens(
                    api_kwargs.get("messages") or [], tools_after or []
                ) if isinstance(api_kwargs, dict) else 0,
                "max_tokens_after": int(api_kwargs.get("max_tokens") or 0)
                if isinstance(api_kwargs, dict) else 0,
                # Schema shape only: no descriptions, values, messages or
                # arguments. This makes canary incompatibilities diagnosable
                # without persisting buyer data or credentials.
                "tool_schema_summaries": schema_summaries,
            })
        diagnostic_path = Path(path_value).expanduser()
        diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
        with diagnostic_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":")) + "\n")
        try:
            diagnostic_path.chmod(0o600)
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
        # Hermes versions disagree on whether a named provider is exposed as
        # ``admira-nvidia``, ``custom:admira-nvidia`` or ``custom``. Inspect
        # every harmless URL representation as well; the URL is the reliable
        # identity and no secret is needed.
        base_urls = [
            getattr(agent, "_base_url_lower", ""),
            getattr(agent, "base_url", ""),
            getattr(agent, "_base_url", ""),
            getattr(agent, "api_base", ""),
        ]
        client = getattr(agent, "client", None)
        if client is not None:
            base_urls.extend([
                getattr(client, "base_url", ""),
                getattr(client, "_base_url", ""),
            ])
        haystack = " ".join(str(value or "") for value in base_urls).strip().lower()
        return (
            provider in {"admira-nvidia", "custom:admira-nvidia", "nvidia", "nvidia-nim"}
            or "integrate.api.nvidia.com" in haystack
        )

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

    def _prepare_call(agent, api_kwargs, *, path):
        """Apply model-independent routing and provider guards exactly once."""
        is_nvidia = _is_nvidia_agent(agent)
        _record_nvidia_hook_diagnostic(agent, api_kwargs, path=path, is_nvidia=is_nvidia)
        token = None
        if not ADMIRA_NVIDIA_PREPARE_ACTIVE.get():
            token = ADMIRA_NVIDIA_PREPARE_ACTIVE.set(True)
            tools_before = len(api_kwargs.get("tools") or []) if isinstance(api_kwargs, dict) else 0
            # Tool-profile filtering was built for the retired constrained NIM
            # transport. Applying its phrase tables to Gemini/Codex made the
            # available product capabilities depend on exact buyer wording.
            # Capable providers receive the official MCP catalog and perform
            # the natural-language interpretation themselves. Backend schemas,
            # authorization and result verification remain deterministic.
            api_kwargs = _remove_hermes_personal_state_tools(api_kwargs)
            if isinstance(api_kwargs, dict) and isinstance(api_kwargs.get("messages"), list):
                api_kwargs = dict(api_kwargs)
                api_kwargs["messages"] = _admira_compact_consumed_observations(
                    api_kwargs["messages"]
                )
            if is_nvidia:
                api_kwargs = _admira_route_request_tools(api_kwargs)
            strategic_state = _admira_strategic_profile_state()
            api_kwargs = _admira_route_tools_by_product_state(
                api_kwargs,
                state=strategic_state,
            )
            api_kwargs = _admira_attach_compiled_procedure(
                api_kwargs,
                state=strategic_state,
            )
            api_kwargs = _admira_gemini_safe_request(api_kwargs, agent)
            _record_nvidia_hook_diagnostic(
                agent,
                api_kwargs,
                path=f"{path}:routed",
                is_nvidia=is_nvidia,
                prepared_profile=_nvidia_request_profile(api_kwargs.get("messages") or [])
                if isinstance(api_kwargs, dict) else None,
                tools_before=tools_before,
            )
            if is_nvidia:
                _reserve(agent)
                api_kwargs = _nvidia_prepare_request(api_kwargs)
                _record_nvidia_hook_diagnostic(
                    agent,
                    api_kwargs,
                    path=f"{path}:prepared",
                    is_nvidia=True,
                    prepared_profile=_nvidia_request_profile(api_kwargs.get("messages") or [])
                    if isinstance(api_kwargs, dict) else None,
                    tools_before=tools_before,
                )
        return api_kwargs, token

    def _finish_prepared_call(token):
        if token is not None:
            ADMIRA_NVIDIA_PREPARE_ACTIVE.reset(token)

    # Hermes' AIAgent methods import the helper functions lazily. Wrapping
    # only ``agent.chat_completion_helpers`` is timing-sensitive: sitecustomize
    # can run before the CLI imports ``run_agent`` and the first request can
    # bypass the filter entirely. Patch the actual forwarders when available;
    # this is the narrowest stable seam across Hermes releases.
    try:
        # Do not import run_agent from sitecustomize: it is the CLI's entry
        # module and eager loading it here can create a circular startup stall.
        # sitecustomize calls this function again after the import completes.
        run_agent = sys.modules.get("run_agent")
        agent_class = getattr(run_agent, "AIAgent", None) if run_agent is not None else None
        if agent_class is not None and not getattr(agent_class, "_admira_nvidia_gate_patch", False):
            original_agent_call = getattr(agent_class, "_interruptible_api_call", None)
            original_agent_streaming = getattr(agent_class, "_interruptible_streaming_api_call", None)

            if callable(original_agent_call):
                def patched_agent_call(agent, api_kwargs):
                    token = None
                    try:
                        verbatim_source = _admira_campaign_verbatim_source(
                            api_kwargs.get("messages") or []
                        ) if isinstance(api_kwargs, dict) else ""
                        api_kwargs, token = _prepare_call(agent, api_kwargs, path="agent_call")
                        response = original_agent_call(agent, api_kwargs)
                        return _admira_attach_verbatim_campaign_source(response, verbatim_source)
                    finally:
                        _finish_prepared_call(token)

                agent_class._admira_original_interruptible_api_call = original_agent_call
                agent_class._interruptible_api_call = patched_agent_call

            if callable(original_agent_streaming):
                def patched_agent_streaming(agent, api_kwargs, *, on_first_delta=None):
                    token = None
                    try:
                        verbatim_source = _admira_campaign_verbatim_source(
                            api_kwargs.get("messages") or []
                        ) if isinstance(api_kwargs, dict) else ""
                        api_kwargs, token = _prepare_call(agent, api_kwargs, path="agent_stream")
                        response = original_agent_streaming(agent, api_kwargs, on_first_delta=on_first_delta)
                        return _admira_attach_verbatim_campaign_source(response, verbatim_source)
                    finally:
                        _finish_prepared_call(token)

                agent_class._admira_original_interruptible_streaming_api_call = original_agent_streaming
                agent_class._interruptible_streaming_api_call = patched_agent_streaming

            if callable(original_agent_call) or callable(original_agent_streaming):
                agent_class._admira_nvidia_gate_patch = True
                return True
    except Exception:
        # Older Hermes builds may not expose run_agent.AIAgent at import time;
        # retain the helper-level compatibility path below.
        pass

    original = getattr(helpers, "interruptible_api_call", None)
    original_streaming = getattr(helpers, "interruptible_streaming_api_call", None)
    patched_any = False

    if callable(original) and not getattr(original, "_admira_nvidia_gate_patch", False):
        def patched_interruptible_api_call(agent, api_kwargs):
            token = None
            try:
                verbatim_source = _admira_campaign_verbatim_source(
                    api_kwargs.get("messages") or []
                ) if isinstance(api_kwargs, dict) else ""
                api_kwargs, token = _prepare_call(agent, api_kwargs, path="helper_call")
                response = original(agent, api_kwargs)
                return _admira_attach_verbatim_campaign_source(response, verbatim_source)
            finally:
                _finish_prepared_call(token)

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
            token = None
            try:
                verbatim_source = _admira_campaign_verbatim_source(
                    api_kwargs.get("messages") or []
                ) if isinstance(api_kwargs, dict) else ""
                api_kwargs, token = _prepare_call(agent, api_kwargs, path="helper_stream")
                response = original_streaming(agent, api_kwargs, on_first_delta=on_first_delta)
                return _admira_attach_verbatim_campaign_source(response, verbatim_source)
            finally:
                _finish_prepared_call(token)

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
        ADMIRA_CURRENT_TURN_TOOL_RECEIPTS_KEY,
    ):
        if key in response:
            sources.append(response.get(key))
    # Hermes returns the complete conversation in ``messages``. A real MCP
    # turn stores the generated path in a role=tool message and then appends a
    # plain role=assistant success reply. Looking only at the newest assistant
    # message therefore drops the attachment even though generation succeeded.
    # Restrict inspection to messages after the latest buyer message so older
    # creatives from session history are never replayed.
    current_messages = _current_turn_messages(response.get("messages"))
    if current_messages:
        sources.extend(
            message
            for message in current_messages
            if isinstance(message, dict)
            and str(message.get("role") or "").strip().lower() in {"assistant", "tool", "function"}
        )
    else:
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


def _current_turn_tool_receipts_from_state(session_key, *, state_db_path=None):
    """Read only the current buyer turn's persisted tool receipts.

    Hermes persists tool calls before ``GatewayRunner._run_agent`` returns,
    while some provider adapters return only the final assistant message in
    the in-memory response.  The outbound truth guards therefore cannot rely
    on ``response['messages']`` alone.  Resolve the current session in the
    state DB, find its latest buyer message, and recover only subsequent tool
    rows.  Older turns are deliberately excluded.
    """
    session = str(session_key or "").strip()
    if not session:
        return []
    if state_db_path is None:
        root = Path(str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "/app").strip()).expanduser()
        state_db_path = root / "runtime" / "hermes" / "state.db"
    connection = None
    try:
        connection = sqlite3.connect(str(state_db_path), timeout=1.0)
        session_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(sessions)").fetchall()
        }
        message_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(messages)").fetchall()
        }
        if "id" not in session_columns or not {"id", "session_id", "role", "content"}.issubset(message_columns):
            return []
        if "session_key" in session_columns:
            order = " ORDER BY started_at DESC" if "started_at" in session_columns else ""
            resolved = connection.execute(
                f"SELECT id FROM sessions WHERE id = ? OR session_key = ?{order} LIMIT 1",
                (session, session),
            ).fetchone()
        else:
            resolved = connection.execute(
                "SELECT id FROM sessions WHERE id = ? LIMIT 1",
                (session,),
            ).fetchone()
        session_id = str(resolved[0] if resolved else session)
        latest_user = connection.execute(
            "SELECT id FROM messages WHERE session_id = ? AND role = 'user' "
            "ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if not latest_user:
            return []
        tool_name_sql = "tool_name" if "tool_name" in message_columns else "''"
        tool_call_id_sql = "tool_call_id" if "tool_call_id" in message_columns else "''"
        active_sql = " AND active = 1" if "active" in message_columns else ""
        rows = connection.execute(
            f"SELECT role, content, {tool_name_sql}, {tool_call_id_sql} FROM messages "
            "WHERE session_id = ? AND id > ? "
            "AND role IN ('tool', 'function', 'tool_result')"
            f"{active_sql} ORDER BY id ASC LIMIT 48",
            (session_id, int(latest_user[0])),
        ).fetchall()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return []
    finally:
        try:
            if connection is not None:
                connection.close()
        except Exception:
            pass
    return [
        {
            "role": str(role or "tool"),
            "name": str(tool_name or ""),
            "tool_name": str(tool_name or ""),
            "tool_call_id": str(tool_call_id or ""),
            "content": content or "",
        }
        for role, content, tool_name, tool_call_id in rows
    ]


def _attach_current_turn_tool_receipts(response, session_key, *, state_db_path=None):
    """Attach private same-turn receipts for outbound verification only."""
    if not isinstance(response, dict):
        return response
    receipts = _current_turn_tool_receipts_from_state(
        session_key,
        state_db_path=state_db_path,
    )
    if not receipts:
        return response
    enriched = dict(response)
    enriched[ADMIRA_CURRENT_TURN_TOOL_RECEIPTS_KEY] = receipts
    return enriched


def _has_confirmed_durable_save(response):
    if not isinstance(response, dict):
        return False
    sources = []
    for key in ("tool_result", "tool_results", "tool_response", "tool_responses", "result", "results", "action_result", "action_results", "mcp_result", "mcp_results", ADMIRA_CURRENT_TURN_TOOL_RECEIPTS_KEY):
        if key in response:
            sources.append(response.get(key))
    sources.extend(_current_turn_messages(response.get("messages")))
    def mappings(value):
        if isinstance(value, dict):
            yield value
            for item in value.values():
                yield from mappings(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from mappings(item)
        elif isinstance(value, str):
            candidate = value.strip()
            if candidate.startswith(("{", "[")):
                try:
                    yield from mappings(json.loads(candidate))
                except (TypeError, ValueError):
                    pass

    try:
        text = json.dumps(sources, ensure_ascii=False, default=str).lower().replace('\\"', '"')
    except (TypeError, ValueError):
        text = str(sources).lower()
    has_save_tool = any(marker in text for marker in ADMIRA_DURABLE_TOOL_MARKERS)
    authoritative_save = any(
        item.get("saved") is True
        and item.get("draft") is not True
        and item.get("blocked") is not True
        for source in sources
        for item in mappings(source)
    )
    return has_save_tool and authoritative_save


def _guard_authoritative_image_outcome(response):
    """Translate the current synchronous Image receipt into buyer truth.

    Image generation has no queued state. A blocked call cannot truthfully be
    described as sent, processing, or about to appear, and a successful call
    is not deliverable unless it contains a real generated media path.
    """
    if not isinstance(response, dict):
        return response
    sources = list(_current_turn_messages(response.get("messages")))
    if not sources:
        for key in ("tool_result", "tool_results", "result", "results", "mcp_result", "mcp_results", ADMIRA_CURRENT_TURN_TOOL_RECEIPTS_KEY):
            if key in response:
                sources.append(response.get(key))
    try:
        evidence = json.dumps(sources, ensure_ascii=False, default=str).replace('\\"', '"')
    except (TypeError, ValueError):
        evidence = str(sources)
    lowered = evidence.lower()
    if "codex_image_generate" not in lowered:
        return response
    blocked = any(marker in lowered for marker in ('"blocked": true', '"blocked":true', '"executed": false', '"executed":false'))
    failed = blocked or any(marker in lowered for marker in ('"ok": false', '"ok":false'))
    if failed:
        error_match = re.search(r'"(?:error|reply)"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', evidence)
        detail = ""
        if error_match:
            try:
                detail = json.loads(f'"{error_match.group(1)}"').strip()
            except (TypeError, ValueError):
                detail = error_match.group(1).strip()
        language = str(os.environ.get("ADMIRA_GATEWAY_LANGUAGE") or "es").lower()
        prefix = (
            "No image was generated or sent in this attempt."
            if language.startswith("en")
            else "No se generó ni se envió ninguna imagen en este intento."
        )
        response["final_response"] = f"{prefix} {detail}".strip()
        return response
    paths = []
    for source in _current_generated_media_sources(response):
        _collect_generated_media_paths(source, paths=paths)
    if not paths:
        language = str(os.environ.get("ADMIRA_GATEWAY_LANGUAGE") or "es").lower()
        response["final_response"] = (
            "The image tool did not return a verifiable file, so I will not report it as generated or sent."
            if language.startswith("en")
            else "La herramienta de imagen no devolvió un archivo verificable, así que no la reportaré como generada ni enviada."
        )
    return response


def _apply_authoritative_tool_result_guards(response):
    """Always enforce tool truth, including in free-form conversation mode."""
    result = response
    for guard in (_guard_unconfirmed_persistence_claim, _guard_authoritative_image_outcome):
        try:
            result = guard(result)
        except Exception:
            pass
    return result


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


def _classify_campaign_creation_claim_semantically(final_response):
    """Classify ambiguous campaign prose outside the Hermes agent loop.

    The classifier decides only what the prose communicates. Current-turn
    campaign-tool evidence remains the sole authority for whether Meta really
    created anything. Provider failures return an unavailable classification
    so the deterministic fail-safe can still protect explicit false claims.
    """
    try:
        from campaign_claim_classifier import classify_campaign_creation_claim

        result = classify_campaign_creation_claim(str(final_response or ""))
    except Exception as exc:
        return {
            "ok": False,
            "confirmation": "",
            "reason": "campaign_claim_classifier_failed",
            "error_type": type(exc).__name__,
        }
    if not isinstance(result, dict):
        return {
            "ok": False,
            "confirmation": "",
            "reason": "campaign_claim_classifier_invalid_result",
        }
    confirmation = str(result.get("confirmation") or "").strip().lower()
    if result.get("ok") is not True or confirmation not in {"si", "no"}:
        return {
            **result,
            "ok": False,
            "confirmation": "",
            "reason": str(result.get("reason") or "campaign_claim_classifier_invalid_result"),
        }
    return {**result, "confirmation": confirmation}


def _known_non_success_campaign_phrase(final_response):
    """Preserve known prospective language if semantic classification fails."""
    return bool(re.search(
        r"(?i)\b(?:quedo|quedamos|i\s+remain|i(?:'m|\s+am)\s+ready)\s+"
        r"(?:atent[oa]s?|pendientes?|list[oa]s?|ready)?\b.{0,120}"
        r"\b(?:crear|estructurar|preparar|armar|configurar|create|structure|prepare|build|configure)\b"
        r".{0,100}\b(?:campa[n\u00f1]a|campaign)\b",
        str(final_response or ""),
    ))


def _verified_campaign_receipt_from_value(value, depth=0):
    """Extract a complete three-level campaign receipt from nested state."""
    if depth > 8 or not isinstance(value, dict):
        return {}
    campaign_id = str(value.get("campaign_id") or "").strip()
    adset_ids = [
        str(item).strip()
        for item in (value.get("adset_ids") or [])
        if str(item).strip()
    ]
    ad_ids = [
        str(item).strip()
        for item in (value.get("ad_ids") or [])
        if str(item).strip()
    ]
    if value.get("executed") is True and campaign_id and adset_ids and ad_ids:
        return {
            "campaign_id": campaign_id,
            "adset_ids": adset_ids,
            "ad_ids": ad_ids,
            "final_status": str(value.get("final_status") or "PAUSED").strip().upper(),
        }
    for key in ("result", "creation", "payload", "execution"):
        found = _verified_campaign_receipt_from_value(value.get(key), depth + 1)
        if found:
            return found
    return {}


def _latest_verified_campaign_action_receipt(*, product_root=None):
    """Return the newest backend-recorded successful campaign mutation."""
    root = Path(
        product_root
        or str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "/app").strip()
    ).expanduser()
    path = root / "dashboard" / "data" / "actions.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    actions = payload if isinstance(payload, list) else payload.get("actions", []) if isinstance(payload, dict) else []
    for action in actions:
        if not isinstance(action, dict):
            continue
        if str(action.get("type") or "") != "create_campaign" or str(action.get("status") or "") != "completed":
            continue
        action_payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
        receipt = _verified_campaign_receipt_from_value(action_payload.get("result"))
        if not receipt:
            continue
        receipt["name"] = str(action_payload.get("name") or "").strip()
        receipt["action_id"] = str(action.get("id") or "").strip()
        return receipt
    return {}


def _normalize_campaign_reference(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _response_references_verified_campaign(final_response, receipt=None):
    """Match a restatement to the exact latest verified campaign receipt."""
    receipt = receipt or _latest_verified_campaign_action_receipt()
    if not receipt:
        return False
    text = str(final_response or "")
    campaign_id = str(receipt.get("campaign_id") or "").strip()
    if campaign_id and campaign_id in text:
        return True
    name = _normalize_campaign_reference(receipt.get("name"))
    response = _normalize_campaign_reference(text)
    return bool(len(name) >= 10 and name in response)


def _guard_unconfirmed_campaign_claim(response):
    """Do not let prose turn a blocked campaign call into a fake success."""
    if not isinstance(response, dict):
        return response
    final_response = str(response.get("final_response") or "")
    if not final_response or not ADMIRA_CAMPAIGN_SUCCESS_CLAIM_RE.search(final_response):
        return response
    # The success regex deliberately catches many phrasings, but a future or
    # capability statement is not an outcome claim. Preserve natural planning
    # such as “puedo dejar la estructura creada en pausa” while still blocking
    # “ya quedó creada” or “la dejé creada”.
    claim_parts = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+|\n+", final_response)
        if ADMIRA_CAMPAIGN_SUCCESS_CLAIM_RE.search(part or "")
    ]
    only_prospective = bool(claim_parts) and all(
        re.search(
            r"(?i)\b(?:puedo|podemos|podr[ií]a(?:mos)?|voy\s+a|vamos\s+a|"
            r"para|antes\s+de|cuando|si\s+(?:quieres|prefieres)|can|could|will|going\s+to)\b"
            r".{0,180}\b(?:crear|configurar|dejar|preparar|armar|create|configure|leave|prepare)\b",
            part,
        )
        and not re.search(
            r"(?i)\b(?:ya|acabo\s+de|acabamos\s+de|he|hemos|"
            r"cre[eé]|dej[eé]|configur[eé]|qued[oó]|created|configured)\b",
            part,
        )
        for part in claim_parts
    )
    if only_prospective:
        return response
    current_messages = _current_turn_messages(response.get("messages"))
    sources = list(current_messages)
    if response.get(ADMIRA_CURRENT_TURN_TOOL_RECEIPTS_KEY):
        sources.append(response.get(ADMIRA_CURRENT_TURN_TOOL_RECEIPTS_KEY))
    # Some Hermes versions expose top-level tool result aggregates for the
    # entire session. Use them only when no current-turn message slice exists;
    # otherwise an old blocked campaign can overwrite unrelated later replies.
    if not current_messages:
        for key in (
            "tool_result", "tool_results", "tool_response", "tool_responses",
            "result", "results", "action_result", "action_results", "mcp_result", "mcp_results",
        ):
            if key in response:
                sources.append(response.get(key))
    try:
        evidence = json.dumps(sources, ensure_ascii=False, default=str).lower().replace('\\"', '"')
    except (TypeError, ValueError):
        evidence = str(sources).lower()
    attempted = any(marker in evidence for marker in ADMIRA_CAMPAIGN_CREATION_TOOL_MARKERS)
    verified = '"campaign_creation_verified": true' in evidence or '"campaign_creation_verified":true' in evidence
    if verified:
        return response
    # A buyer may immediately retry after a successful tool turn.  Hermes can
    # correctly answer that the exact campaign already exists and avoid a
    # duplicate without calling the mutation tool again.  Accept that
    # restatement only when it names (or IDs) the latest backend-recorded
    # three-level success receipt; an unrelated campaign claim is still
    # rejected below.
    if _response_references_verified_campaign(final_response):
        return response
    if re.search(r"(?i)\b(?:no\s+(?:se\s+)?cre[eó]|no\s+fue\s+creada|did\s+not\s+create|was\s+not\s+created)\b", final_response):
        return response

    # The regex above is only a cheap candidate gate. A small independent
    # structured-output request receives the raw assistant prose without
    # history or tools and determines whether it actually claims a completed
    # campaign creation. Semantic "no" preserves natural conversation;
    # semantic "si" continues into the authoritative evidence check below.
    semantic = _classify_campaign_creation_claim_semantically(final_response)
    if semantic.get("ok") is True and semantic.get("confirmation") == "no":
        return response
    if semantic.get("ok") is not True and _known_non_success_campaign_phrase(final_response):
        return response
    if not attempted:
        # This guard validates an outcome, never the buyer's wording. A model
        # may interpret natural language freely, but it cannot report a Meta
        # mutation as completed without current-turn tool evidence.
        language = str(os.environ.get("ADMIRA_GATEWAY_LANGUAGE") or "es").lower()
        response["final_response"] = (
            "I could not verify a Meta creation in this turn because no campaign tool returned real IDs. I will not report it as created."
            if language.startswith("en")
            else "No pude verificar una creación en Meta en este turno porque ninguna herramienta de campaña devolvió IDs reales. No la reportaré como creada."
        )
        return response
    language = str(os.environ.get("ADMIRA_GATEWAY_LANGUAGE") or "es").lower()
    response["final_response"] = (
        "The campaign was not created in Meta. The tool did not verify a PAUSED campaign, ad set, and ad with real IDs. I will keep the exact blocker and will not ask for another approval to create it paused."
        if language.startswith("en")
        else "No se creó la campaña en Meta. La herramienta no verificó una campaña, un conjunto y un anuncio en PAUSED con IDs reales. Conservaré el bloqueo exacto y no pediré otra aprobación para crearla en pausa."
    )
    return response


def _nested_receipt_mappings(value, *, max_depth=10):
    """Decode mappings hidden inside nested/escaped Hermes tool receipts.

    Depending on the provider adapter, an MCP result can arrive as a mapping,
    a JSON string, a JSON string containing another JSON string, or JSON inside
    Hermes' ``<untrusted_tool_result>`` wrapper.  Outcome guards must reason
    over the structured receipt rather than over a fixed number of backslash
    replacements.  Decoding is bounded and read-only because these strings are
    untrusted tool data.
    """
    mappings = []
    seen = set()
    decoder = json.JSONDecoder()

    def visit(item, depth):
        if depth > max_depth:
            return
        if isinstance(item, dict):
            identity = id(item)
            if identity in seen:
                return
            seen.add(identity)
            mappings.append(item)
            for nested in item.values():
                visit(nested, depth + 1)
            return
        if isinstance(item, (list, tuple)):
            identity = id(item)
            if identity in seen:
                return
            seen.add(identity)
            for nested in item:
                visit(nested, depth + 1)
            return
        if isinstance(item, str):
            candidate = item.strip()
            if not candidate:
                return
            wrapper = re.search(
                r"<untrusted_tool_result\b[^>]*>\s*(.*?)\s*</untrusted_tool_result>",
                candidate,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if wrapper:
                visit(wrapper.group(1), depth + 1)
                return
            starts = [0] if candidate[:1] in {'{', '[', '"'} else []
            if not starts:
                starts = sorted(
                    position
                    for position in (candidate.find("{"), candidate.find("["))
                    if position >= 0
                )
            for start in starts:
                try:
                    decoded, _end = decoder.raw_decode(candidate[start:])
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if decoded == item:
                    continue
                visit(decoded, depth + 1)
                break
            return

        # A few Hermes versions expose message objects rather than dicts.
        # Select only receipt-bearing public attributes; never execute methods
        # or serialize the provider object wholesale.
        attributes = {}
        for key in ("role", "name", "tool_name", "content", "result", "results"):
            try:
                nested = getattr(item, key)
            except (AttributeError, TypeError):
                continue
            attributes[key] = nested
        if attributes:
            visit(attributes, depth + 1)

    visit(value, 0)
    return mappings


def _campaign_edit_receipt_state(sources):
    """Return authoritative attempted/staged/applied state for one edit turn."""
    attempted = False
    staged = False
    applied_candidates = []
    staged_campaign_ids = set()

    receipt_sources = []
    for source in sources:
        if isinstance(source, (list, tuple)):
            receipt_sources.extend(source)
        else:
            receipt_sources.append(source)

    records = []
    for source in receipt_sources:
        try:
            source_text = json.dumps(source, ensure_ascii=False, default=str).lower()
        except (TypeError, ValueError):
            source_text = str(source).lower()
        if isinstance(source, dict):
            source_tool_name = str(source.get("name") or source.get("tool_name") or "").strip().lower()
        else:
            source_tool_name = str(
                getattr(source, "name", "") or getattr(source, "tool_name", "") or ""
            ).strip().lower()
        tool_scope = source_tool_name or source_text
        direct_edit_source = any(
            marker in tool_scope for marker in ADMIRA_CAMPAIGN_EDIT_TOOL_MARKERS
        )
        approval_source = "approve_action" in tool_scope
        attempted = attempted or direct_edit_source

        mappings = _nested_receipt_mappings(source)
        if not mappings:
            staged = staged or "campaign_edit_pending_approval" in source_text
            continue

        structured_text = json.dumps(
            mappings,
            ensure_ascii=False,
            default=str,
        ).lower()
        attempted = attempted or any(
            marker in structured_text for marker in ADMIRA_CAMPAIGN_EDIT_TOOL_MARKERS
        )
        source_staged = any(
            item.get("staged") is True
            or str(item.get("reason") or "").strip() == "campaign_edit_pending_approval"
            or str(item.get("status") or "").strip().lower() == "pending"
            for item in mappings
        )
        staged = staged or source_staged
        source_campaign_ids = {
            str(item.get("campaign_id") or "").strip()
            for item in mappings
            if str(item.get("campaign_id") or "").strip()
        }
        if direct_edit_source and source_staged:
            staged_campaign_ids.update(source_campaign_ids)
        requires_verified_readback = "edit_campaign" in tool_scope
        records.append((
            direct_edit_source,
            approval_source,
            requires_verified_readback,
            source_campaign_ids,
            mappings,
        ))

    for direct_edit_source, approval_source, requires_verified_readback, source_campaign_ids, mappings in records:
        for item in mappings:
            if item.get("executed") is not True or item.get("ok") is not True or item.get("blocked") is True:
                continue
            item_campaign_id = str(item.get("campaign_id") or "").strip()
            candidate_campaign_ids = {item_campaign_id} if item_campaign_id else source_campaign_ids
            verification = item.get("verification")
            graph_results = item.get("results")
            verification_ok = (
                isinstance(verification, list)
                and bool(verification)
                and all(
                    isinstance(check, dict)
                    and check.get("ok") is True
                    and 200 <= int(check.get("http_status") or 0) < 300
                    for check in verification
                )
            )
            graph_ok = (
                isinstance(graph_results, list)
                and bool(graph_results)
                and all(
                    isinstance(result, dict)
                    and result.get("ok") is True
                    and 200 <= int(result.get("status") or 0) < 300
                    for result in graph_results
                )
            )
            verified_edit = item.get("verified") is True and verification_ok and graph_ok
            if direct_edit_source and (verified_edit or not requires_verified_readback):
                applied_candidates.append((candidate_campaign_ids, True))
                break
            if approval_source and verified_edit:
                # The outer approval_decision merely records that approval
                # was accepted. Only its nested, read-back edit result proves
                # that Meta contains the requested value.
                applied_candidates.append((candidate_campaign_ids, True))
                break

    applied = any(
        confirmed
        and (
            not staged_campaign_ids
            or bool(staged_campaign_ids.intersection(source_campaign_ids))
        )
        for source_campaign_ids, confirmed in applied_candidates
    )

    return {
        "attempted": attempted,
        "staged": staged,
        "applied": applied,
    }


def _guard_unconfirmed_campaign_edit_claim(response, buyer_message=None):
    """Keep staged/blocked edits from being narrated as already applied."""
    if not isinstance(response, dict):
        return response
    if response.get(ADMIRA_CAMPAIGN_EDIT_GUARD_APPLIED_KEY) is True:
        return response
    final_response = str(response.get("final_response") or "")
    # Stage 1 is intentionally narrow: inspect only the assistant response and
    # do nothing unless it explicitly contains campaign/campaña.
    if not final_response or not re.search(
        r"(?i)\b(?:campa[nñ]a(?:s)?|campaign(?:s)?)\b",
        final_response,
    ):
        return response
    if re.search(r"(?i)\b(?:no\s+(?:apliqu[eé]|modifiqu[eé]|cambi[eé])|todav[ií]a\s+no|awaiting|pending|espera(?:ndo)?\s+aprobaci[oó]n)\b", final_response):
        return response
    # Stage 2 is one isolated structured-output call with only the current
    # buyer turn and raw assistant prose. Unless it explicitly returns
    # semantic "si", preserve the response byte-for-byte and never consult
    # campaign tool evidence.
    # Prefer an explicitly supplied trusted buyer turn. When the caller did
    # not provide one, recover the newest user message from the result if the
    # adapter exposed it; never treat older assistant text as the buyer turn.
    if buyer_message is None:
        buyer_message = response.get("buyer_message") or response.get("current_buyer_message")
    if buyer_message is None:
        messages = response.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                if isinstance(message, dict) and str(message.get("role") or "").strip().lower() == "user":
                    buyer_message = message.get("content") or ""
                    break
    # A semantic relationship cannot be established without the current
    # buyer turn. Do not let an assistant claim from an older turn trigger the
    # edit guard when an adapter omitted that provenance.
    if not isinstance(buyer_message, str) or not buyer_message.strip():
        return response
    try:
        from campaign_claim_classifier import classify_campaign_edit_claim

        semantic = classify_campaign_edit_claim(final_response, buyer_message=buyer_message or "")
    except Exception:
        return response
    if not isinstance(semantic, dict):
        return response
    if semantic.get("ok") is not True or str(semantic.get("confirmation") or "").strip().lower() != "si":
        return response
    sources = list(_current_turn_messages(response.get("messages")))
    if response.get(ADMIRA_CURRENT_TURN_TOOL_RECEIPTS_KEY):
        sources.append(response.get(ADMIRA_CURRENT_TURN_TOOL_RECEIPTS_KEY))
    if not sources:
        for key in ("tool_result", "tool_results", "result", "results", "mcp_result", "mcp_results"):
            if key in response:
                sources.append(response.get(key))
    receipt_state = _campaign_edit_receipt_state(sources)
    attempted = receipt_state["attempted"]
    applied = receipt_state["applied"]
    staged = receipt_state["staged"]
    if applied:
        return response
    language = str(os.environ.get("ADMIRA_GATEWAY_LANGUAGE") or "es").lower()
    if staged:
        response["final_response"] = (
            "The edit was prepared but not applied yet; it is waiting for the exact approval tied to this campaign."
            if language.startswith("en")
            else "Preparé el cambio, pero todavía no lo apliqué en Meta; quedó esperando la aprobación exacta asociada a esta campaña."
        )
    elif attempted:
        response["final_response"] = (
            "I could not verify that the campaign edit was applied, so I will not report it as changed."
            if language.startswith("en")
            else "No pude verificar que el cambio de campaña se aplicara, así que no lo reportaré como modificado."
        )
    else:
        response["final_response"] = (
            "I could not verify a campaign edit in this turn, so I will not report one as applied."
            if language.startswith("en")
            else "No pude verificar una edición de campaña en este turno, así que no la reportaré como aplicada."
        )
    response[ADMIRA_CAMPAIGN_EDIT_GUARD_APPLIED_KEY] = True
    return response


def guard_unverified_campaign_edit_text(value, language="es", pending_edit=None):
    """Conservatively correct unstructured CLI text that claims an edit ran.

    Hermes CLI sessions return only buyer-facing text, not the structured MCP
    evidence available to the Python gateway. A declarative success sentence
    therefore cannot be trusted unless a caller already applied a structured
    result guard. Questions and explicit pending/blocked wording are left
    untouched so normal explanations still read naturally.
    """
    text = str(value or "").strip()
    if not text or "?" in text or "¿" in text:
        return text
    if not ADMIRA_CAMPAIGN_EDIT_SUCCESS_CLAIM_RE.search(text):
        return text
    if re.search(r"(?i)\b(?:no\s+(?:apliqu[eé]|modifiqu[eé]|cambi[eé])|todav[ií]a\s+no|pending|espera(?:ndo)?\s+aprobaci[oó]n)\b", text):
        return text
    if isinstance(pending_edit, dict):
        payload = pending_edit.get("payload") if isinstance(pending_edit.get("payload"), dict) else {}
        campaign_name = str(payload.get("campaign_name") or "la campaña").strip()
        summary = str(payload.get("summary") or "").strip().rstrip(".")
        if str(language or "es").lower().startswith("en"):
            detail = f": {summary}" if summary else ""
            return f"I prepared the edit for {campaign_name}{detail}. I have not applied it in Meta; it is waiting for approval."
        detail = f": {summary}" if summary else ""
        return f"Preparé el cambio para {campaign_name}{detail}. Todavía no lo apliqué en Meta; quedó pendiente de aprobación."
    return (
        "I could not verify that the campaign edit was applied, so I will not report it as changed."
        if str(language or "es").lower().startswith("en")
        else "No pude verificar que el cambio de campaña se aplicara, así que no lo reportaré como modificado."
    )


def _apply_conversational_output_guards(response, buyer_message=None):
    """Apply legacy prose classifiers unless the canary delegates language to the model."""
    if _admira_freeform_agent_mode():
        return response
    if buyer_message is None and isinstance(response, dict):
        buyer_message = response.get(ADMIRA_CURRENT_BUYER_MESSAGE_KEY)
    result = response
    for guard in (
        _guard_unconfirmed_persistence_claim,
        _guard_unconfirmed_campaign_claim,
        lambda value: _guard_unconfirmed_campaign_edit_claim(value, buyer_message=buyer_message),
    ):
        try:
            result = guard(result)
        except Exception:
            pass
    return result


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
        agent_ran = False
        message = kwargs.get("message")
        if message is None and args:
            message = args[0]
        call_args = list(args)
        source = kwargs.get("source")
        if source is None and len(args) > 3:
            source = args[3]
        event_message_id = kwargs.get("event_message_id")
        if event_message_id is None and len(args) > 8:
            event_message_id = args[8]
        session_key = kwargs.get("session_key")
        if session_key is None and len(args) > 5:
            session_key = args[5]
        if not session_key:
            session_id = kwargs.get("session_id")
            if session_id is None and len(args) > 4:
                session_id = args[4]
            session_key = session_id or "default"
        continuity_hint = _continuity_resume_hint(session_key, kwargs.get("history"), message=message)
        if continuity_hint and isinstance(message, str) and ADMIRA_SESSION_CONTINUITY_START not in message:
            message = f"{message}\n\n{continuity_hint}"
            if "message" in kwargs:
                kwargs["message"] = message
            elif call_args:
                call_args[0] = message
        persisted = kwargs.get("persist_user_message")
        clean_persisted = _strip_admira_runtime_injections(
            persisted if persisted is not None else message
        )
        if clean_persisted:
            kwargs["persist_user_message"] = clean_persisted
        if not _admira_freeform_agent_mode() and _chatgpt_connection_request(clean_persisted):
            # This wrapper is installed on GatewayRunner after gateway.run is
            # available, unlike the optional Telegram adapter hook that can be
            # imported too early during sitecustomize startup. Keep explicit
            # ChatGPT connection requests completely outside model inference.
            _append_gateway_turn("user", clean_persisted)
            recovery = _automatic_codex_recovery(wait_seconds=15, action="switch")
            if recovery.get("url") and recovery.get("code"):
                _remember_chatgpt_login_pending(session_key)
            language = str(os.environ.get("ADMIRA_GATEWAY_LANGUAGE") or "es")
            result = {"final_response": _chatgpt_connection_reply(recovery, language), "messages": []}
        elif _chatgpt_login_confirmation_request(clean_persisted, session_key):
            # A short acknowledgement after device login belongs exclusively
            # to the auth flow. Never let "Listo" reach campaign planning or
            # tools while this explicit pending marker is active.
            _append_gateway_turn("user", clean_persisted)
            language = str(os.environ.get("ADMIRA_GATEWAY_LANGUAGE") or "es")
            result = {
                "final_response": _chatgpt_login_confirmation_reply(session_key, language),
                "messages": [],
            }
        else:
            # Resolve a buyer confirmation against the presentation recorded
            # on the previous turn before Hermes builds this turn's prompt.
            # This lets the same model invocation see the newly confirmed
            # onboarding/plan state instead of answering from stale context.
            lifecycle_transition = await asyncio.to_thread(
                _resolve_business_lifecycle_transition,
                session_id=session_key,
                raw_message=clean_persisted,
                target="",
            )
            # A master plan is a backend-owned artefact, not free-form Hermes
            # prose. Generate it once with the isolated high-capability chain
            # before inference. This also recovers a complete profile whose
            # earlier compiler attempt failed: the helper is idempotent and
            # enforces its own lease/backoff/CAS boundary.
            expected_plan_turn = _strategic_plan_expected_turn_for_runtime(
                source=source,
                session_id=session_key,
                raw_message=clean_persisted,
                message_sequence=event_message_id,
            )
            if expected_plan_turn:
                plan_generation = await asyncio.to_thread(
                    _ensure_initial_business_master_plan,
                    expected_turn=expected_plan_turn,
                )
            else:
                plan_generation = {
                    "ok": False,
                    "attempted": False,
                    "created": False,
                    "reason": "strategic_plan_turn_not_bound_to_current_event",
                }
            if plan_generation.get("created"):
                # The finalized-outbound hook below replaces this placeholder
                # with the exact persisted canonical draft and records its
                # presentation. Skipping Hermes prevents a shallow competing
                # plan or an unrelated tool call on the transition turn.
                result = {
                "final_response": "Preparé una propuesta inicial de anuncios para que la pulamos juntos.",
                    "messages": [],
                }
            elif plan_generation.get("attempted") and not plan_generation.get("ok") and str(
                plan_generation.get("reason") or ""
            ) != "strategic_plan_generation_compare_and_swap_failed":
                result = {
                    "final_response": (
                        "El resumen del negocio quedó confirmado, pero no pude preparar todavía la propuesta publicitaria "
                        "con la evidencia necesaria. No voy a inventar una dirección genérica. "
                        "Tu información está guardada y volveré a intentar la compilación de forma segura."
                    ),
                    "messages": [],
                }
            else:
                result = await original(self, *tuple(call_args), **kwargs)
                agent_ran = True
        if agent_ran:
            # Provider adapters do not consistently return tool rows in the
            # in-memory response even though Hermes has already committed them
            # to state.db. Attach the exact same-turn receipts privately so
            # outcome guards see authoritative evidence before Telegram text
            # is finalized.
            result = _attach_current_turn_tool_receipts(result, session_key)
        result = _apply_authoritative_tool_result_guards(result)
        # The semantic campaign-claim arbiter is a tiny independent provider
        # call. Run conversational guards off the Telegram event loop so a
        # slow provider or Codex CLI startup cannot freeze other chats.
        if isinstance(result, dict):
            # Keep the exact, sanitized buyer turn alongside the private
            # receipts while the semantic edit classifier runs. This prevents
            # a stale historical edit claim from being attributed to a new
            # greeting or unrelated turn.
            result[ADMIRA_CURRENT_BUYER_MESSAGE_KEY] = clean_persisted
        result = await asyncio.to_thread(_apply_conversational_output_guards, result)
        try:
            result = _normalize_gateway_outbound_response(result)
        except Exception:
            pass
        try:
            # Normalize first: the model can place MEDIA before its internal
            # [ADMIRA FINAL] marker, and reasoning cleanup intentionally drops
            # everything before that marker. Re-collecting current-turn tool
            # media afterward guarantees the native directive survives at the
            # end of the buyer-visible answer.
            result = _append_generated_media_attachments(result)
        except Exception:
            pass
        try:
            visible_text = (
                result.get("final_response")
                or result.get("response")
                or result.get("message")
                or ""
                if isinstance(result, dict)
                else result
            )
            # Lifecycle hooks are backend-owned and intentionally run outside
            # the Telegram event loop. They may classify a natural buyer
            # confirmation, materialize the next plan/profile artifact, or
            # record that it was actually shown.
            lifecycle_state = _admira_strategic_profile_state()
            lifecycle_target = (
                "business_profile" if not lifecycle_state.get("complete")
                else ("strategic_plan" if lifecycle_state.get("master_plan_status") == "proposed" else "")
            )
            ensured = await asyncio.to_thread(
                _ensure_business_lifecycle_artifact_visible,
                session_id=session_key,
                assistant_text=visible_text,
                target=lifecycle_target,
            )
            if isinstance(ensured, dict) and isinstance(ensured.get("text"), str):
                visible_text = ensured["text"]
                if isinstance(result, dict):
                    result = dict(result)
                    result["final_response"] = visible_text
        except Exception:
            pass
        try:
            if isinstance(result, dict):
                _append_gateway_turn("agent", result.get("final_response") or result.get("response") or result.get("message") or "")
            else:
                _append_gateway_turn("agent", result)
            await asyncio.to_thread(
                _record_business_lifecycle_artifact_presented,
                session_id=session_key,
                assistant_text=visible_text if "visible_text" in locals() else "",
                target=lifecycle_target if "lifecycle_target" in locals() else "",
            )
        except Exception:
            pass
        if isinstance(result, dict):
            # Private verification evidence must never become part of the
            # gateway's public response contract.
            result.pop(ADMIRA_CURRENT_TURN_TOOL_RECEIPTS_KEY, None)
            result.pop(ADMIRA_CURRENT_BUYER_MESSAGE_KEY, None)
            result.pop(ADMIRA_CAMPAIGN_EDIT_GUARD_APPLIED_KEY, None)
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
        # Live Meta synchronization is read-only product grounding, not an
        # intent router or mutation guard. Keep it in freeform mode so the
        # natural-language agent sees current account truth without deciding
        # to call account tools merely to answer an ordinary turn.
        if _message_requires_live_meta_sync(result):
            try:
                import asyncio
                live_context = await asyncio.to_thread(_fetch_live_meta_context_for_turn)
                result = _append_live_meta_context(result, live_context)
            except Exception:
                result = _append_live_meta_context(result, {"ok": False, "reason": "live_meta_sync_failed"})
        try:
            _append_gateway_turn("user", result)
        except Exception:
            pass
        return result

    runner._admira_original_prepare_inbound_message_text = original
    runner._prepare_inbound_message_text = patched_prepare_inbound_message_text
    runner._admira_inbound_video_frame_patch = True
    return True


def _patch_gateway_reset_campaign_scope():
    """Make native Hermes /new and /reset clear Admira's transient edit scope."""
    try:
        from gateway.slash_commands import GatewaySlashCommandsMixin
    except Exception:
        return False
    original = getattr(GatewaySlashCommandsMixin, "_handle_reset_command", None)
    if not callable(original):
        return False
    if getattr(GatewaySlashCommandsMixin, "_admira_reset_campaign_scope_patch", False):
        return True

    async def patched(self, event, *args, **kwargs):
        source = getattr(event, "source", None)
        chat_id = str(getattr(source, "chat_id", "") or "").strip()
        platform = str(getattr(source, "platform", "") or "").lower()
        if chat_id and "telegram" in platform:
            try:
                from campaign_editing import reset_conversation_edit_context
                reset_conversation_edit_context(chat_id)
            except Exception:
                # A product-side cleanup failure must never prevent Hermes
                # from honoring the buyer's explicit conversation reset.
                pass
        return await original(self, event, *args, **kwargs)

    GatewaySlashCommandsMixin._admira_original_handle_reset_command = original
    GatewaySlashCommandsMixin._handle_reset_command = patched
    GatewaySlashCommandsMixin._admira_reset_campaign_scope_patch = True
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


def _telegram_runtime_chat_context_path():
    """Where the native Telegram gateway records the buyer's actual chat ID.

    Hermes keeps its own opaque channel key for authorization. Admira's OAuth
    sender needs the numeric Bot API chat id, which is only available on a real
    incoming update. This small handoff lets the product send the OAuth URL
    later in the same conversation without opening a second Telegram poller.
    """
    root = str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "").strip()
    product_root = Path(root).expanduser() if root else Path(__file__).resolve().parent.parent
    path = product_root / "dashboard" / "data" / "telegram_runtime_chat.json"
    return path if path.parent.exists() else None


def _record_telegram_runtime_chat(chat_id, user_id=""):
    value = str(chat_id or "").strip()
    if not value.lstrip("-").isdigit():
        return False
    path = _telegram_runtime_chat_context_path()
    if not path:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "chat_id": value,
            "user_id": str(user_id or ""),
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }), encoding="utf-8")
        tmp.replace(path)
        path.chmod(0o600)
        return True
    except OSError:
        return False


_ADMIRA_DASHBOARD_MODULE = None


def _admira_dashboard_module():
    """Load the product dashboard lazily for the OAuth URL handoff."""
    global _ADMIRA_DASHBOARD_MODULE
    if _ADMIRA_DASHBOARD_MODULE is not None:
        return _ADMIRA_DASHBOARD_MODULE
    root = str(os.environ.get("ADMIRA_PRODUCT_ROOT") or "").strip()
    product_root = Path(root).expanduser() if root else Path(__file__).resolve().parent.parent
    path = product_root / "dashboard" / "monitoring-dashboard.py"
    if not path or not path.exists():
        raise RuntimeError("Admira dashboard unavailable")
    spec = importlib.util.spec_from_file_location("admira_runtime_dashboard", path)
    if not spec or not spec.loader:
        raise RuntimeError("Admira dashboard unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _ADMIRA_DASHBOARD_MODULE = module
    return module


def _record_trusted_buyer_turn(
    *, chat_id, session_id, message_sequence, raw_message, transport="telegram"
):
    """Hand one authorized inbound buyer turn to the selection authorizer.

    The raw message is captured at the transport boundary, before model
    inference, so a model-authored paraphrase can never become evidence for a
    Meta account/Page selection.  Older dashboards do not expose the hook;
    during a rolling update they continue normally without weakening the
    backend authorization required by the selection tool.
    """
    raw = raw_message if isinstance(raw_message, str) else str(raw_message or "")
    session = str(session_id or "").strip()
    chat = str(chat_id or "").strip()
    try:
        sequence = int(message_sequence)
    except (TypeError, ValueError):
        return False
    if not raw or not chat or not session or sequence < 0:
        return False
    try:
        dashboard = _admira_dashboard_module()
        recorder = getattr(dashboard, "record_trusted_buyer_turn", None)
        if not callable(recorder):
            return False
        recorder(
            chat_id=chat,
            session_id=session,
            message_sequence=sequence,
            raw_message=raw,
            transport=transport,
        )
        return True
    except Exception:
        # Selection remains fail-closed in the backend if evidence could not
        # be recorded.  A recorder problem must not silence ordinary chat.
        try:
            dashboard = _admira_dashboard_module()
            clearer = getattr(dashboard, "clear_trusted_buyer_turn", None)
            if callable(clearer):
                clearer()
        except Exception:
            pass
        return False


def _record_strategic_review_presented(*, session_id, assistant_text, chat_id=""):
    """Record a fully covered finalized answer; ordinary replies are ignored."""
    try:
        dashboard = _admira_dashboard_module()
        recorder = getattr(dashboard, "record_strategic_review_presented", None)
        if not callable(recorder):
            return False
        result = recorder(
            session_id=str(session_id or ""),
            assistant_text=str(assistant_text or ""),
            chat_id=str(chat_id or ""),
        )
        return bool(isinstance(result, dict) and result.get("recorded"))
    except Exception:
        return False


def _resolve_business_lifecycle_transition(*, session_id="", chat_id="", raw_message="", assistant_text="", target=""):
    """Best-effort bridge to backend lifecycle resolution hooks.

    The classifier/persistence implementation belongs to the dashboard.  The
    runtime only forwards the already-recorded turn and tolerates older
    dashboards during rolling updates.
    """
    try:
        dashboard = _admira_dashboard_module()
        resolver = getattr(dashboard, "resolve_pending_business_lifecycle_transition", None)
        if not callable(resolver):
            return {}
        payload = {
            "session_id": str(session_id or ""),
            "chat_id": str(chat_id or ""),
            "raw_message": str(raw_message or ""),
            "assistant_text": str(assistant_text or ""),
            "target": str(target or ""),
        }
        try:
            result = resolver(**payload)
        except TypeError:
            result = resolver(target=payload["target"] or "business_profile")
        if not payload["target"] and isinstance(result, dict) and not result.get("transitioned"):
            # A fresh buyer turn can be confirming either artifact. The
            # dashboard verifies presentation binding before accepting either,
            # so probing both targets is safe and avoids relying on wording or
            # the post-response lifecycle snapshot.
            for candidate in ("strategic_plan", "business_profile"):
                try:
                    candidate_result = resolver(target=candidate)
                except Exception:
                    continue
                if isinstance(candidate_result, dict) and candidate_result.get("transitioned"):
                    return candidate_result
        return result if isinstance(result, dict) else {"resolved": bool(result)}
    except Exception:
        return {}


def _runtime_source_value(source, key):
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None) if source is not None else None


def _strategic_plan_expected_turn_for_runtime(
    *, source=None, session_id="", raw_message="", message_sequence=None
):
    """Describe the current real buyer event without trusting stale state."""
    platform = _runtime_source_value(source, "platform")
    platform = getattr(platform, "value", platform)
    transport = str(platform or _runtime_source_value(source, "transport") or "")
    transport = transport.strip().lower().replace("-", "_")
    chat_id = str(_runtime_source_value(source, "chat_id") or "").strip()
    session_id = str(session_id or "").strip()
    raw_message = str(raw_message or "").strip()
    if (
        transport not in {"telegram", "dashboard", "simulated_telegram", "legacy_telegram"}
        or not chat_id
        or not session_id
        or not raw_message
    ):
        return {}
    expected = {
        "chat_id": chat_id,
        "session_id": session_id,
        "transport": transport,
        "raw_message": raw_message,
    }
    if message_sequence not in (None, ""):
        expected["message_sequence"] = message_sequence
    return expected


def _ensure_initial_business_master_plan(*, expected_turn=None):
    """Ask the backend to materialize the first plan outside Hermes."""
    try:
        dashboard = _admira_dashboard_module()
        ensure = getattr(dashboard, "ensure_initial_business_master_plan", None)
        if not callable(ensure):
            return {"ok": False, "attempted": False, "reason": "strategic_plan_compiler_unavailable"}
        result = ensure(expected_turn=expected_turn)
        return result if isinstance(result, dict) else {
            "ok": bool(result), "attempted": bool(result), "created": bool(result)
        }
    except Exception:
        return {"ok": False, "attempted": True, "created": False, "reason": "strategic_plan_compiler_failed"}


def _ensure_business_lifecycle_artifact_visible(*, session_id="", chat_id="", assistant_text="", target=""):
    """Allow the backend to append/refresh the current lifecycle artifact."""
    try:
        dashboard = _admira_dashboard_module()
        ensure = getattr(dashboard, "ensure_business_lifecycle_artifact_visible", None)
        if not callable(ensure):
            return {}
        payload = {
            "session_id": str(session_id or ""),
            "chat_id": str(chat_id or ""),
            "assistant_text": str(assistant_text or ""),
            "target": str(target or ""),
        }
        try:
            result = ensure(**payload)
        except TypeError:
            result = ensure(payload["assistant_text"], target=payload["target"] or None)
        return {"text": result} if isinstance(result, str) else (result if isinstance(result, dict) else {"ensured": bool(result)})
    except Exception:
        return {}


def _record_business_lifecycle_artifact_presented(*, session_id="", chat_id="", assistant_text="", target=""):
    """Record the final buyer-visible lifecycle artifact, if supported."""
    try:
        dashboard = _admira_dashboard_module()
        recorder = getattr(dashboard, "record_business_lifecycle_artifact_presented", None)
        if not callable(recorder):
            return False
        payload = {
            "session_id": str(session_id or ""),
            "chat_id": str(chat_id or ""),
            "assistant_text": str(assistant_text or ""),
            "target": str(target or ""),
        }
        try:
            result = recorder(**payload)
        except TypeError:
            result = recorder(payload["session_id"], payload["assistant_text"], target=payload["target"] or None)
        return bool(result.get("recorded")) if isinstance(result, dict) else bool(result)
    except Exception:
        return False


def _ensure_canonical_strategic_review_visible(result):
    """Keep natural prose while making a requested profile review complete."""
    dashboard = _admira_dashboard_module()
    ensure_visible = getattr(
        dashboard, "ensure_canonical_strategic_review_visible", None
    )
    if not callable(ensure_visible):
        return result
    if isinstance(result, dict):
        for key in ("final_response", "response", "message"):
            if key in result and isinstance(result.get(key), str):
                updated = ensure_visible(result.get(key))
                if updated != result.get(key):
                    result = dict(result)
                    result[key] = updated
                break
        return result
    if isinstance(result, str):
        return ensure_visible(result)
    return result


def _record_trusted_telegram_buyer_turn(**kwargs):
    """Backward-compatible transport-named alias for focused runtime tests."""
    return _record_trusted_buyer_turn(**kwargs)


def _telegram_adapter_classes():
    classes = []
    for module_name in (
        "hermes_plugins.telegram_platform.adapter",
        "plugins.platforms.telegram.adapter",
    ):
        try:
            module = importlib.import_module(module_name)
            adapter_class = getattr(module, "TelegramAdapter", None)
        except ImportError:
            continue
        if adapter_class is not None and all(adapter_class is not item for item in classes):
            classes.append(adapter_class)
    return classes


def _patch_telegram_runtime_chat_capture():
    """Persist the real authorized Telegram chat ID before Hermes batches text."""
    patched_any = False
    for adapter_class in _telegram_adapter_classes():
        original = getattr(adapter_class, "_handle_text_message", None)
        if not callable(original):
            continue
        if getattr(original, "_admira_runtime_chat_capture", False):
            patched_any = True
            continue

        async def patched(self, update, context, _original=original):
            try:
                message = self._effective_update_message(update)
                if message is not None and self._is_user_authorized_from_message(message):
                    chat = getattr(message, "chat", None)
                    sender = getattr(message, "from_user", None)
                    _record_telegram_runtime_chat(getattr(chat, "id", None), getattr(sender, "id", None))
                    incoming = str(getattr(message, "text", "") or "")
                    chat_id = getattr(chat, "id", None)
                    chat_type = "dm" if str(getattr(chat, "type", "") or "").lower() == "private" else "group"
                    pending_key = f"agent:main:telegram:{chat_type}:{chat_id}"
                    message_sequence = getattr(message, "message_id", None)
                    if message_sequence is None:
                        message_sequence = getattr(update, "update_id", None)
                    _record_trusted_buyer_turn(
                        chat_id=chat_id,
                        session_id=pending_key,
                        message_sequence=message_sequence,
                        raw_message=incoming,
                        transport="telegram",
                    )
                    if not _admira_freeform_agent_mode() and _chatgpt_connection_request(incoming):
                        result = _automatic_codex_recovery(wait_seconds=15, action="switch")
                        if result.get("url") and result.get("code"):
                            _remember_chatgpt_login_pending(pending_key)
                        language = str(os.environ.get("ADMIRA_GATEWAY_LANGUAGE") or "es")
                        await message.reply_text(_chatgpt_connection_reply(result, language))
                        return None
                    if _chatgpt_login_confirmation_request(incoming, pending_key):
                        language = str(os.environ.get("ADMIRA_GATEWAY_LANGUAGE") or "es")
                        await message.reply_text(_chatgpt_login_confirmation_reply(pending_key, language))
                        return None
            except Exception:
                pass
            return await _original(self, update, context)

        patched._admira_runtime_chat_capture = True
        patched._admira_original_handle_text_message = original
        adapter_class._handle_text_message = patched
        patched_any = True
    return patched_any


def _obsolete_admira_skill_unlock_block(tool_name, message):
    """Identify only the retired read-SKILL-then-retry MCP ceremony."""
    name = str(tool_name or "").strip().lower()
    if not name.startswith(("mcp_admira_", "admira_")):
        return False
    text = re.sub(r"\s+", " ", str(message or "")).strip().lower()
    if not text:
        return False
    mentions_skill = "skill.md" in text or "read skill" in text or "leer skill" in text
    requires_unlock = any(marker in text for marker in (
        "before calling this mcp",
        "before calling the mcp",
        "before retrying",
        "then retry",
        "retry the tool",
        "retry this tool",
        "read the required skill",
        "read that primary skill",
        "lee el skill requerido",
    ))
    return mentions_skill and requires_unlock


def _patch_mcp_primary_skill_gate():
    """Preserve Hermes middleware without a failed-MCP/read/retry ceremony.

    Relevant procedure guidance is compiled into each provider request before
    inference.  Blocking a valid MCP merely to make the model call ``read_file``
    added two inference cycles per domain and copied a large skill into context.
    Product-state eligibility, tool schemas, and backend authorization remain
    authoritative; the original Hermes middleware may still block for its own
    independent reasons.
    """
    try:
        from hermes_cli import plugins
    except Exception:
        return False
    original = getattr(plugins, "get_pre_tool_call_block_message", None)
    if not callable(original) or getattr(original, "_admira_primary_skill_gate", False):
        return False

    def patched(
        tool_name,
        args,
        task_id="",
        session_id="",
        tool_call_id="",
        turn_id="",
        api_request_id="",
        middleware_trace=None,
    ):
        block_message = original(
            tool_name,
            args,
            task_id=task_id,
            session_id=session_id,
            tool_call_id=tool_call_id,
            turn_id=turn_id,
            api_request_id=api_request_id,
            middleware_trace=middleware_trace,
        )
        if _obsolete_admira_skill_unlock_block(tool_name, block_message):
            return None
        return block_message

    patched._admira_primary_skill_gate = True
    patched._admira_compiled_procedure_gate = True
    patched._admira_original = original
    plugins.get_pre_tool_call_block_message = patched
    return True


def _patch_product_prompt_guidance():
    """Replace coding-agent autonomy with buyer-conversation action semantics."""
    try:
        from agent import prompt_builder
    except Exception:
        return False
    try:
        from agent import coding_context
    except Exception:
        coding_context = None
    try:
        from tools import memory_tool
    except Exception:
        memory_tool = None
    prompt_builder.TOOL_USE_ENFORCEMENT_GUIDANCE = (
        "# Buyer-conversation tool discipline\n"
        "Tools execute buyer outcomes; they are not a requirement for every reply. "
        "Use a tool only when the buyer's current conversational intent requests "
        "that outcome or when a read-only lookup is materially necessary to answer. "
        "A goal, idea, strategy discussion, missing input, or answer to a question "
        "does not authorize a new action. Your own proposal or promise never creates "
        "authorization. Recommend, explain, and ask one natural blocking question "
        "without tool calls when that is the correct next step. When the buyer does "
        "request an executable outcome and its required facts are ready, use the "
        "official tool and report only verified results.\n"
        "For a new campaign, the creative and ad wording are a joint review with "
        "the buyer. Conduct that review entirely through ordinary conversational "
        "text: show the exact full primary text/copy, a distinct title, the exact "
        "destination or WhatsApp message, and the delivered creative. Never call "
        "the native clarification tool or create a question/approval/selection card; "
        "interpret the buyer's free-form response naturally."
    )
    prompt_builder.TASK_COMPLETION_GUIDANCE = (
        "# Complete the buyer's actual request\n"
        "Complete the outcome the buyer requested, not a larger adjacent workflow. "
        "For advice or planning, a useful answer is completion. For a requested tool "
        "action, require its real result before claiming completion. Never fabricate "
        "results, expand planning into execution, or retry by inventing buyer choices."
    )
    prompt_builder.GOOGLE_MODEL_OPERATIONAL_GUIDANCE = (
        "# Google model conversation directives\n"
        "Interpret the full buyer conversation naturally. Tool availability does not "
        "imply tool necessity. Read the mapped product skill before an MCP, preserve "
        "the buyer's exact values, and stop for a genuinely missing owner decision. "
        "Do not turn proactive advice into an unrequested account or media action."
    )
    prompt_builder.OPENAI_MODEL_EXECUTION_GUIDANCE = (
        "# Product execution discipline\n"
        "Use tools for the exact buyer-requested outcome and necessary grounding. "
        "Do not broaden advice, planning, field collection, or a correction into an "
        "account mutation. Verify real actions, preserve scope, and stop rather than "
        "inventing missing authorization or values."
    )
    if isinstance(getattr(prompt_builder, "PLATFORM_HINTS", None), dict):
        prompt_builder.PLATFORM_HINTS["cli"] = (
            "You are answering through an Admira buyer-facing chat transport, not a "
            "developer terminal. Use concise mobile-friendly language. Deliver generated "
            "media with MEDIA:/absolute/path so the transport attaches it; never expose "
            "internal implementation details unless support explicitly asks."
        )
    product_context = (
        "You are the buyer-facing Admira Meta Ads agent, not a coding agent. "
        "The workspace contains read-only product context and operating skills. "
        "Do not edit code, inspect repositories, use terminal workflows, or discuss "
        "developer mechanics unless support explicitly requests diagnostics."
    )
    if coding_context is not None:
        coding_context.CODING_AGENT_GUIDANCE = product_context
    coding_profile = getattr(coding_context, "CODING_PROFILE", None) if coding_context else None
    replacement_profile = None
    if coding_context is not None and coding_profile is not None:
        try:
            replacement_profile = coding_context.ContextProfile(
                name=coding_profile.name,
                toolset=coding_profile.toolset,
                guidance=product_context,
                model_hint=coding_profile.model_hint,
                memory_policy=coding_profile.memory_policy,
                compact_skill_categories=coding_profile.compact_skill_categories,
            )
            coding_context.CODING_PROFILE = replacement_profile
        except Exception:
            replacement_profile = None
    profiles = getattr(coding_context, "_PROFILES", None) if coding_context else None
    if isinstance(profiles, dict) and profiles.get("coding") is not None:
        if replacement_profile is not None:
            profiles["coding"] = replacement_profile
    memory_store_class = getattr(memory_tool, "MemoryStore", None) if memory_tool else None
    format_memory = getattr(memory_store_class, "format_for_system_prompt", None)
    if memory_store_class is not None and not getattr(
        format_memory, "_admira_official_memory_only", False
    ):
        def no_personal_memory_prompt(self, target):
            return None

        no_personal_memory_prompt._admira_official_memory_only = True
        memory_store_class.format_for_system_prompt = no_personal_memory_prompt
    prompt_builder._admira_product_prompt_guidance = True
    return True


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


def _patch_telegram_complete_reset_command_menu():
    """Keep Admira's destructive reset visible without editing Hermes itself."""
    try:
        import hermes_cli.commands as command_registry
    except ImportError:
        return False
    original = getattr(command_registry, "telegram_menu_commands", None)
    if not callable(original):
        return False
    if getattr(original, "_admira_complete_reset_menu_patch", False):
        return True

    def patched(max_commands=100):
        commands, hidden = original(max_commands=max_commands)
        name = COMPLETE_RESET_COMMAND.lstrip("/")
        item = (name, "Reinstalar Admira IA y borrar los datos guardados")
        filtered = [entry for entry in commands if entry[0] != name]
        combined = [item, *filtered]
        limit = max(1, int(max_commands or 100))
        trimmed = max(0, len(combined) - limit)
        return combined[:limit], int(hidden or 0) + trimmed

    patched._admira_complete_reset_menu_patch = True
    patched._admira_original_telegram_menu_commands = original
    command_registry.telegram_menu_commands = patched
    return True


def _complete_reset_message_identity(message):
    chat = getattr(message, "chat", None)
    sender = getattr(message, "from_user", None)
    chat_id = getattr(message, "chat_id", None) or getattr(chat, "id", None)
    user_id = getattr(sender, "id", None)
    return str(chat_id or ""), str(user_id or "")


def _patch_telegram_complete_reset_command():
    """Intercept the reset command and exact confirmation before any LLM turn."""
    patched_any = False
    command_pattern = re.compile(r"^/resetear_completamente(?:@[A-Za-z0-9_]+)?\s*$", re.IGNORECASE)
    for adapter_class in _telegram_adapter_classes():
        original_command = getattr(adapter_class, "_handle_command", None)
        original_text = getattr(adapter_class, "_handle_text_message", None)
        if not callable(original_command) or not callable(original_text):
            continue
        if getattr(original_command, "_admira_complete_reset_command_patch", False):
            patched_any = True
            continue

        async def patched_command(self, update, context, _original=original_command):
            message = self._effective_update_message(update)
            text = str(getattr(message, "text", "") or "") if message is not None else ""
            if message is None or not text or not self._is_user_authorized_from_message(message):
                return await _original(self, update, context)
            chat_id, user_id = _complete_reset_message_identity(message)
            paths = reset_control_paths()
            if not command_pattern.fullmatch(text):
                cancelled = consume_reset_confirmation(
                    paths["confirmation"], paths["request"], text, chat_id, user_id
                )
                if not cancelled.get("matched"):
                    return await _original(self, update, context)
                _record_telegram_runtime_chat(chat_id, user_id)
                if cancelled.get("status") == "expired":
                    await message.reply_text(
                        "La confirmación venció y no borré nada. Usa /resetear_completamente para iniciar de nuevo."
                    )
                else:
                    await message.reply_text(
                        "No reinicié Admira IA porque la respuesta no coincidió exactamente. La solicitud quedó cancelada."
                    )
                return None
            _record_telegram_runtime_chat(chat_id, user_id)
            pending = begin_reset_confirmation(paths["confirmation"], paths["request"], chat_id, user_id)
            if pending.get("status") == "already_running":
                await message.reply_text("Ya hay un reinicio completo en curso. Espera a que Admira IA vuelva a conectarse.")
                return None
            minutes = max(1, COMPLETE_RESET_CONFIRMATION_TTL_SECONDS // 60)
            await message.reply_text(
                "⚠️ Este reinicio es permanente. Borrará la conexión de Facebook/Meta, el negocio, la memoria, "
                "sesiones, briefs, creativos locales y cronjobs. No borrará las campañas que ya existen dentro de Meta.\n\n"
                "Conservaré la licencia, este Telegram, el modelo principal conectado y ChatGPT/Codex para Image 2. "
                "Después descargaré y reinstalaré la última versión estable oficial.\n\n"
                f"Para confirmar, responde exactamente dentro de {minutes} minutos:\n{COMPLETE_RESET_CONFIRMATION_PHRASE}\n\n"
                "Cualquier otra respuesta cancelará el reinicio."
            )
            return None

        async def patched_text(self, update, context, _original=original_text):
            message = self._effective_update_message(update)
            if message is None or not getattr(message, "text", None):
                return await _original(self, update, context)
            if not self._is_user_authorized_from_message(message):
                return await _original(self, update, context)
            chat_id, user_id = _complete_reset_message_identity(message)
            paths = reset_control_paths()
            result = consume_reset_confirmation(
                paths["confirmation"], paths["request"], message.text, chat_id, user_id
            )
            if not result.get("matched"):
                return await _original(self, update, context)
            _record_telegram_runtime_chat(chat_id, user_id)
            if result.get("status") == "confirmed":
                await message.reply_text(
                    "✅ Confirmación válida. Prepararé la última versión estable y reiniciaré Admira IA desde cero. "
                    "El bot se desconectará unos minutos y volverá a avisarte cuando termine."
                )
                return None
            if result.get("status") == "expired":
                await message.reply_text(
                    "La confirmación venció y no borré nada. Usa /resetear_completamente para iniciar de nuevo."
                )
                return None
            await message.reply_text(
                "No reinicié Admira IA porque la respuesta no coincidió exactamente. La solicitud quedó cancelada."
            )
            return None

        patched_command._admira_complete_reset_command_patch = True
        patched_command._admira_original_handle_command = original_command
        patched_text._admira_complete_reset_text_patch = True
        patched_text._admira_original_handle_text_message = original_text
        adapter_class._handle_command = patched_command
        adapter_class._handle_text_message = patched_text
        patched_any = True
    return patched_any


def _patch_gateway_complete_reset_command():
    """Handle complete reset before Hermes rejects unknown slash commands."""
    try:
        import gateway.run as gateway_run
    except Exception:
        return False
    runner = getattr(gateway_run, "GatewayRunner", None)
    original = getattr(runner, "_handle_message", None) if runner is not None else None
    if not callable(original):
        return False
    if getattr(original, "_admira_complete_reset_gateway_patch", False):
        return True

    command_pattern = re.compile(r"^/resetear_completamente(?:@[A-Za-z0-9_]+)?\s*$", re.IGNORECASE)

    async def patched(self, event, _original=original):
        text = str(getattr(event, "text", "") or "").strip()
        source = getattr(event, "source", None)
        platform = str(getattr(getattr(source, "platform", None), "value", getattr(source, "platform", "")) or "").lower()
        if platform != "telegram":
            return await _original(self, event)
        chat_id = str(getattr(source, "chat_id", "") or "")
        user_id = str(getattr(source, "user_id", "") or "")
        paths = reset_control_paths()

        if command_pattern.fullmatch(text):
            _record_telegram_runtime_chat(chat_id, user_id)
            pending = begin_reset_confirmation(paths["confirmation"], paths["request"], chat_id, user_id)
            if pending.get("status") == "already_running":
                return "Ya hay un reinicio completo en curso. Espera a que Admira IA vuelva a conectarse."
            minutes = max(1, COMPLETE_RESET_CONFIRMATION_TTL_SECONDS // 60)
            return (
                "⚠️ Este reinicio es permanente. Borrará la conexión de Facebook/Meta, el negocio, la memoria, "
                "sesiones, briefs, creativos locales y cronjobs. No borrará las campañas que ya existen dentro de Meta.\n\n"
                "Conservaré la licencia, este Telegram, el modelo principal conectado y ChatGPT/Codex para Image 2. "
                "Después descargaré y reinstalaré la última versión estable oficial.\n\n"
                f"Para confirmar, responde exactamente dentro de {minutes} minutos:\n{COMPLETE_RESET_CONFIRMATION_PHRASE}\n\n"
                "Cualquier otra respuesta cancelará el reinicio."
            )

        result = consume_reset_confirmation(
            paths["confirmation"], paths["request"], text, chat_id, user_id
        )
        if not result.get("matched"):
            return await _original(self, event)
        _record_telegram_runtime_chat(chat_id, user_id)
        if result.get("status") == "confirmed":
            return (
                "✅ Confirmación válida. Prepararé la última versión estable y reiniciaré Admira IA desde cero. "
                "El bot se desconectará unos minutos y volverá a avisarte cuando termine."
            )
        if result.get("status") == "expired":
            return "La confirmación venció y no borré nada. Usa /resetear_completamente para iniciar de nuevo."
        return "No reinicié Admira IA porque la respuesta no coincidió exactamente. La solicitud quedó cancelada."

    patched._admira_complete_reset_gateway_patch = True
    patched._admira_original_handle_message = original
    runner._handle_message = patched
    return True


def _patch_telegram_update_install_callback():
    """Route Admira's install button through Hermes' *existing* callback loop.

    We intentionally wrap the native Telegram adapter rather than opening a
    second getUpdates consumer.  The gateway acknowledges the tap immediately
    then the dashboard process performs the package update independently.
    """
    patched_any = False
    for adapter_class in _telegram_adapter_classes():
        original = getattr(adapter_class, "_handle_callback_query", None)
        if not callable(original):
            continue
        if getattr(original, "_admira_update_install_patch", False):
            patched_any = True
            continue

        async def patched(self, update, context, _original=original):
            query = getattr(update, "callback_query", None)
            data = str(getattr(query, "data", "") or "")
            if data.startswith(("meta_account:", "meta_page:")):
                message = getattr(query, "message", None)
                chat = getattr(message, "chat", None)
                chat_id = getattr(message, "chat_id", None)
                user = getattr(query, "from_user", None)
                user_id = str(getattr(user, "id", "") or "")
                if not self._is_callback_user_authorized(
                    user_id,
                    chat_id=chat_id,
                    chat_type=str(getattr(chat, "type", "") or "") or None,
                    thread_id=str(getattr(message, "message_thread_id", "") or "") or None,
                    user_name=getattr(user, "first_name", None),
                ):
                    await query.answer(text="No tienes permiso para elegir esta cuenta.")
                    return
                _record_telegram_runtime_chat(chat_id, user_id)
                await query.answer(text="Este selector anterior fue retirado.")
                await message.reply_text(
                    "Ese selector anterior ya no se usa. Pídeme la lista y responde únicamente con dos números: primero Página y después cuenta publicitaria, por ejemplo: 1, 8."
                )
                return
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
    compression_patched = _patch_model_aware_compression_threshold()
    product_prompt_patched = _patch_product_prompt_guidance()
    chatgpt_slash_patched = _patch_gateway_chatgpt_slash_commands()
    rate_limit_patched = _patch_gateway_rate_limit_reply()
    credential_pool_patched = _patch_credential_pool_failure_assignment()
    same_nvidia_guard_patched = _patch_same_nvidia_model_failover_guard()
    nvidia_gate_patched = _patch_nvidia_request_gate()
    nvidia_title_patched = _patch_nvidia_auxiliary_title_generation()
    mcp_result_patched = _patch_mcp_call_result_compatibility()
    mcp_skill_gate_patched = _patch_mcp_primary_skill_gate()
    minimax_patched = _patch_minimax_model_switch()
    runtime_patched = _patch_minimax_runtime_provider()
    media_patched = _patch_gateway_generated_media_delivery()
    video_patched = _patch_gateway_inbound_video_frames()
    reset_scope_patched = _patch_gateway_reset_campaign_scope()
    cron_create_patched = _patch_cron_job_creation()
    cron_run_patched = _patch_cron_job_execution()
    context_patched = _patch_context_truncation_notifications()
    telegram_chat_capture_patched = _patch_telegram_runtime_chat_capture()
    telegram_reset_menu_patched = _patch_telegram_complete_reset_command_menu()
    telegram_complete_reset_patched = _patch_telegram_complete_reset_command()
    gateway_complete_reset_patched = _patch_gateway_complete_reset_command()
    telegram_update_patched = _patch_telegram_update_install_callback()
    return bool(compression_patched or product_prompt_patched or chatgpt_slash_patched or rate_limit_patched or credential_pool_patched or same_nvidia_guard_patched or nvidia_gate_patched or nvidia_title_patched or mcp_result_patched or mcp_skill_gate_patched or minimax_patched or runtime_patched or media_patched or video_patched or reset_scope_patched or cron_create_patched or cron_run_patched or context_patched or telegram_chat_capture_patched or telegram_reset_menu_patched or telegram_complete_reset_patched or gateway_complete_reset_patched or telegram_update_patched)
