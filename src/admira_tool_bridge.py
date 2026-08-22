#!/usr/bin/env python3
"""Safe product-tool bridge for Hermes MCP calls."""
import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(
    os.environ.get("ADMIRA_PRODUCT_ROOT")
    or Path(__file__).resolve().parent.parent
).expanduser().resolve()
DASHBOARD_PATH = ROOT_DIR / "dashboard" / "monitoring-dashboard.py"
SRC_DIR = ROOT_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent_chat import account_context  # noqa: E402
from campaign_payload_compiler import compile_campaign_brief  # noqa: E402
from hermes_bridge import safe_image_paths  # noqa: E402
from security import redact_payload  # noqa: E402


TOOL_MAP = {
    "admira_run_daily_brief": "run_daily_check",
    "admira_schedule_experiment_review": "schedule_experiment_review",
    "admira_list_experiment_reviews": "list_experiment_reviews",
    "admira_run_due_experiment_reviews": "run_due_experiment_reviews",
    "admira_save_optimization_research": "save_optimization_research",
    "admira_list_optimization_research": "list_optimization_research",
    "admira_review_signal_quality": "review_signal_quality",
    "admira_set_campaign_metric_priorities": "set_campaign_metric_priorities",
    "admira_preflight_campaign": "preflight_campaign",
    "admira_fetch_public_asset": "fetch_public_asset",
    "admira_codex_image_generate": "codex_image_generate",
    "admira_codex_creative_plan": "codex_creative_plan",
    "admira_list_recent_creatives": "list_recent_creatives",
    "admira_search_motion_graphic_recipes": "search_motion_graphic_recipes",
    "admira_generate_motion_graphic_video": "generate_motion_graphic_video",
    "admira_list_lead_forms": "list_lead_forms",
    "admira_stage_lead_form": "stage_lead_form",
    "admira_create_lead_form": "create_lead_form",
    "admira_stage_campaign": "create_campaign_stack",
    "admira_create_whatsapp_campaign": "create_campaign_stack",
    "admira_create_lead_form_campaign": "create_campaign_stack",
    "admira_create_website_campaign": "create_campaign_stack",
    "admira_create_messaging_campaign": "create_campaign_stack",
    "admira_create_app_campaign": "create_campaign_stack",
    "admira_create_on_meta_campaign": "create_campaign_stack",
    "admira_edit_campaign": "edit_campaign",
    "admira_connect_chatgpt": "connect_chatgpt",
    "admira_stage_budget_change": "set_budget",
    "admira_pause_campaign": "pause_campaign",
    "admira_resume_campaign": "resume_campaign",
    "admira_schedule_campaign_activation": "schedule_campaign_activation",
    "admira_delete_campaign": "delete_campaign",
    "admira_approve_action": "approval_decision",
    "admira_reject_action": "approval_decision",
    "admira_save_agent_preferences": "save_agent_preferences",
    "admira_save_daily_social_content_settings": "save_daily_social_content_settings",
    "admira_stage_organic_social_post": "stage_organic_social_post",
    "admira_save_content_asset": "save_content_asset",
    "admira_record_verified_signal": "record_verified_signal",
    "admira_get_verified_signal_summary": "get_verified_signal_summary",
    "admira_verified_signal_feedback_prompt": "verified_signal_feedback_prompt",
    "admira_save_business_memory": "save_business_context",
    "admira_save_durable_memory": "save_durable_memory",
    "admira_save_ads_onboarding": "save_ads_onboarding",
    "admira_save_brand_memory": "save_brand_guide",
    "admira_save_product_memory": "save_product_guide",
    "admira_import_product_catalog": "import_product_catalog",
    "admira_search_product_catalog": "search_product_catalog",
    "admira_save_ad_brief": "save_ad_brief",
    "admira_save_creative_references": "save_creative_references",
}

LEGACY_PRIVATE_TOOLS = {"admira_stage_campaign"}
PUBLIC_TOOLS = sorted([
    "admira_get_real_meta_context",
    "admira_start_meta_oauth_connection",
    "admira_get_meta_oauth_workspaces",
    "admira_select_meta_oauth_workspace",
    "admira_search_meta_targeting",
    "admira_inspect_adset_targeting",
    "admira_list_pending_approvals",
    *(tool for tool in TOOL_MAP if tool not in LEGACY_PRIVATE_TOOLS),
])
ARGUMENT_WRAPPER_KEYS = {"arguments", "args", "kwargs", "payload", "fields", "data", "input"}
CREATIVE_IMAGE_TOOLS = {"admira_codex_image_generate", "admira_codex_creative_plan"}
GENERATED_MEDIA_TOOLS = {"admira_codex_image_generate", "admira_generate_motion_graphic_video"}
CAMPAIGN_CREATION_TOOLS = {
    "admira_create_whatsapp_campaign",
    "admira_create_lead_form_campaign",
    "admira_create_website_campaign",
    "admira_create_messaging_campaign",
    "admira_create_app_campaign",
    "admira_create_on_meta_campaign",
}
CAMPAIGN_EDIT_TOOLS = {"admira_edit_campaign"}
CAMPAIGN_STAGE_TOOLS = {"admira_stage_campaign", *CAMPAIGN_CREATION_TOOLS}
CAMPAIGN_CREATIVE_SOURCE_KEYS = {
    "creative_image_path",
    "image_hash",
    "image_url",
    "video_path",
    "video_url",
    "video_id",
    "object_story_spec",
    "object_story_spec_json",
    "object_story_id",
    "page_post_id",
    "post_id",
}
PENDING_CAMPAIGN_WORKFLOW_FILE = ROOT_DIR / "dashboard" / "data" / "pending_campaign_workflow.json"
WORKSPACE_IMAGE_TRIGGER_WORDS = (
    "adjunta",
    "adjunto",
    "base visual",
    "esta foto",
    "esta imagen",
    "foto",
    "fondo",
    "imagen",
    "local",
    "photo",
    "recepcion",
    "recepción",
    "reference",
    "referencia",
    "subida",
    "subido",
    "uploaded",
)
IMAGE_OUTPUT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_OUTPUT_EXTENSIONS = {".mp4"}
EMPTY_ARGUMENT_GUARDED_TOOLS = {
    "admira_save_content_asset": ("file_path or file_paths", "category", "purpose", "preservation_mode"),
    "admira_save_brand_memory": ("brand_name or offer", "colors", "visual_style", "tone"),
    "admira_save_product_memory": ("name", "target_audience", "benefit or main_offer"),
    "admira_save_ads_onboarding": ("campaign_goal or objective or success_metrics",),
    "admira_codex_image_generate": ("request", "purpose"),
    "admira_generate_motion_graphic_video": ("topic", "objective", "aspect_ratio"),
    **{tool: ("name", "objective", "daily_budget", "destination details", "creative source") for tool in CAMPAIGN_CREATION_TOOLS},
    "admira_create_lead_form": ("page_id", "name", "privacy_policy_url", "questions"),
    "admira_edit_campaign": ("campaign_reference or campaign_id", "change_request"),
}


def normalize_campaign_edit_arguments(arguments):
    """Accept equivalent natural-request wrappers emitted by capable models.

    The product contract remains campaign_reference + change_request. Some
    providers reuse the campaign-creation key ``brief_markdown`` even while
    correctly selecting the edit MCP. Preserve the model's natural text and
    let the server resolve live IDs; never reinterpret it as a payload here.
    """
    args = dict(arguments or {})
    request = str(
        args.get("change_request")
        or args.get("brief_markdown")
        or args.get("edit_request")
        or args.get("instructions")
        or args.get("instruction")
        or args.get("request")
        or args.get("message")
        or ""
    ).strip()
    reference = str(
        args.get("campaign_reference")
        or args.get("campaign_query")
        or args.get("campaign_id")
        or args.get("campaign_name")
        or args.get("query")
        or ""
    ).strip()
    if request:
        args["change_request"] = request
        if not reference:
            # resolve_campaign_reference safely extracts an exact Meta ID or
            # unique natural name from the same buyer-authored text.
            reference = request
    if reference:
        args["campaign_reference"] = reference
    for alias in (
        "brief_markdown", "edit_request", "instructions", "instruction", "request",
        "campaign_query", "campaign_id", "campaign_name", "query",
    ):
        args.pop(alias, None)
    return args


def load_dashboard():
    spec = importlib.util.spec_from_file_location("admira_monitoring_dashboard", DASHBOARD_PATH)
    if not spec or not spec.loader:
        raise RuntimeError("No pude cargar el dashboard local.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def chat_payload(channel="telegram", language="es"):
    return {
        "channel": channel or "telegram",
        "language": language or "es",
        "message": "Hermes MCP tool call",
    }


def result_ok(result):
    if not isinstance(result, dict):
        return bool(result)
    if result.get("blocked") or result.get("error"):
        return False
    if "ok" in result:
        return bool(result.get("ok"))
    return True


def generated_media_attachment_for_result(tool, result):
    """Return an internal MEDIA directive for generated creative files."""
    if tool not in GENERATED_MEDIA_TOOLS or not result_ok(result):
        return ""
    nested = (result or {}).get("result") if isinstance(result, dict) else {}
    if not isinstance(nested, dict):
        return ""
    raw_path = nested.get("image_path") if tool == "admira_codex_image_generate" else nested.get("video_path")
    if not raw_path:
        return ""
    try:
        path = Path(str(raw_path)).expanduser().resolve()
        path.relative_to((ROOT_DIR / "output").resolve())
    except (OSError, RuntimeError, ValueError):
        return ""
    allowed_extensions = IMAGE_OUTPUT_EXTENSIONS if tool == "admira_codex_image_generate" else VIDEO_OUTPUT_EXTENSIONS
    if path.suffix.lower() not in allowed_extensions or not path.exists() or not path.is_file():
        return ""
    return f"MEDIA:{path}"


def normalize_tool_name(name):
    tool = str(name or "").strip()
    if tool in PUBLIC_TOOLS:
        return tool
    if tool.startswith("mcp_admira_"):
        return "admira_" + tool.removeprefix("mcp_admira_")
    if not tool.startswith("admira_"):
        return "admira_" + tool
    return tool


def parse_argument_mapping(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def normalize_model_collection_wrappers(value, depth=0):
    """Recover array values emitted as ``{"item": ...}`` by some NIM models.

    Hermes advertises ordinary JSON-schema arrays, but OpenAI-compatible
    hosted models can still serialize an XML-style collection wrapper.  Letting
    that wrapper reach campaign validation turns a complete request into
    repeated missing-field/gender errors.  A mapping whose sole key is
    ``item`` is unambiguously a collection; mixed mappings remain objects and
    are only normalized recursively.
    """
    if depth > 12:
        return value
    if isinstance(value, list):
        return [normalize_model_collection_wrappers(item, depth + 1) for item in value]
    if not isinstance(value, dict):
        return value
    # Some OpenAI-compatible XML adapters add a redundant text node beside
    # the item collection. It is serialization residue, not a second field.
    if "item" in value and set(value).issubset({"item", "$text", "#text"}):
        item = normalize_model_collection_wrappers(value.get("item"), depth + 1)
        return item if isinstance(item, list) else [item]
    return {
        key: normalize_model_collection_wrappers(item, depth + 1)
        for key, item in value.items()
    }


def normalize_tool_arguments(arguments, depth=0):
    values = parse_argument_mapping(arguments)
    if not values or depth > 4:
        return values
    nested = {}
    direct = {}
    for key, value in values.items():
        if key in ARGUMENT_WRAPPER_KEYS:
            parsed = parse_argument_mapping(value)
            if parsed:
                nested.update(normalize_tool_arguments(parsed, depth + 1))
                continue
        direct[key] = value
    return normalize_model_collection_wrappers({**nested, **direct})


def creative_args_mentions_uploaded_image(args):
    if str((args or {}).get("use_last_uploaded_image") or "").strip().lower() in {"1", "true", "yes", "si", "sí", "on"}:
        return True
    try:
        text = json.dumps(args or {}, ensure_ascii=False).lower()
    except (TypeError, ValueError):
        text = str(args or "").lower()
    return any(word in text for word in WORKSPACE_IMAGE_TRIGGER_WORDS)


def latest_workspace_image_paths(limit=4):
    workspace = ROOT_DIR / "dashboard" / "data" / "hermes-workspace" / "current"
    candidates = []
    context_path = workspace / "CURRENT_CONTEXT.json"
    try:
        context = json.loads(context_path.read_text(encoding="utf-8")) if context_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        context = {}
    if isinstance(context, dict):
        candidates.extend(context.get("image_paths") or [])
    upload_dir = workspace / "uploads"
    if upload_dir.exists():
        try:
            files = [path for path in upload_dir.iterdir() if path.is_file()]
            files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        except OSError:
            files = []
        candidates.extend(str(path) for path in files)
    safe = safe_image_paths({"image_paths": candidates}, limit=max(1, int(limit or 4)))
    return safe[:limit]


def content_asset_library_items():
    path = ROOT_DIR / "dashboard" / "data" / "content_asset_library.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        return []
    items = payload.get("items") if isinstance(payload, dict) else []
    return [item for item in (items or []) if isinstance(item, dict)]


def latest_content_asset_batch(*, pending_only=False, approved_for_ads=False, limit=32):
    """Return one recent archived buyer batch without guessing its meaning.

    Telegram ingestion archives files before the model classifies them. If a
    compacted session drops the path arguments, this lets the bridge surface
    the exact durable paths back to the model instead of pretending the files
    disappeared. Files are grouped by their creation minute, which matches the
    atomic Telegram batch ingestion used by the product.
    """
    candidates = []
    for item in content_asset_library_items():
        if pending_only and str(item.get("classification_status") or "") != "pending_agent_review":
            continue
        if approved_for_ads and not bool(item.get("approved_for_ads")):
            continue
        if approved_for_ads and str(item.get("classification_status") or "classified") != "classified":
            continue
        if approved_for_ads and str(item.get("preservation_mode") or "").strip().lower() == "prohibited":
            continue
        paths = safe_image_paths({"image_paths": item.get("file_paths") or []}, limit=32)
        if not paths:
            continue
        # Use the latest durable update as the batch key.  A buyer may upload
        # the two creatives for one campaign a minute apart; after the agent
        # classifies/approves them together, grouping by the original upload
        # timestamp would recover only the newest one and silently drop the
        # other creative after context compaction.
        created_at = str(item.get("updated_at") or item.get("created_at") or "")
        candidates.append((created_at, item, paths))
    if not candidates:
        return {"paths": [], "asset_ids": []}
    candidates.sort(key=lambda row: row[0], reverse=True)
    newest_bucket = candidates[0][0][:16]
    selected = [row for row in candidates if row[0][:16] == newest_bucket] if newest_bucket else candidates[:1]
    paths = []
    asset_ids = []
    for _, item, item_paths in selected:
        for path in item_paths:
            if path not in paths:
                paths.append(path)
        asset_id = str(item.get("id") or "").strip()
        if asset_id and asset_id not in asset_ids:
            asset_ids.append(asset_id)
    return {"paths": paths[:limit], "asset_ids": asset_ids[:limit]}


def empty_tool_arguments_result(tool):
    required = list(EMPTY_ARGUMENT_GUARDED_TOOLS.get(tool) or ())
    recovered = {}
    if tool == "admira_save_content_asset":
        recovered = latest_content_asset_batch(pending_only=True)
    elif tool == "admira_codex_image_generate":
        recovered = latest_content_asset_batch()
    elif tool in CAMPAIGN_STAGE_TOOLS:
        # A campaign may only suggest assets explicitly approved for ads.
        recovered = latest_content_asset_batch(approved_for_ads=True, limit=8)
    product_tool = TOOL_MAP.get(tool, tool.removeprefix("admira_"))
    if tool == "admira_save_content_asset" and recovered.get("paths"):
        reply = (
            "La llamada llegó sin clasificación, pero recuperé el lote archivado. "
            "Reintenta una sola vez agrupando estas rutas por category, purpose y preservation_mode; "
            "no digas que quedó organizado hasta que el guardado responda ok."
        )
    else:
        reply = (
            "La herramienta llegó sin argumentos. Reintenta una sola vez con los campos canónicos indicados "
            "y los datos ya confirmados en la conversación; no inventes valores ni afirmes que se guardó o ejecutó."
        )
    result = {
        "type": product_tool,
        "executed": False,
        "blocked": True,
        "reason": "empty_tool_arguments",
        "missing": required,
        "retryable": True,
        "retry_limit": 1,
        "recovered_context": recovered,
        "reply": reply,
    }
    return {
        "ok": False,
        "tool": tool,
        "product_tool": product_tool,
        "blocked": True,
        "reason": "empty_tool_arguments",
        "result": result,
    }


def hydrate_archived_content_asset_paths(tool, args):
    """Restore a just-archived Telegram batch when classification args exist.

    This is deliberately limited to the non-spending content-asset save tool.
    Campaigns, brand facts, products, and image prompts are never invented from
    ambient memory when their tool call arrives empty.
    """
    if tool != "admira_save_content_asset" or not args:
        return args
    if safe_image_paths(args, limit=1):
        return args
    if any(str(args.get(key) or "").strip() for key in ("url", "asset_url", "source_url", "public_url", "video_url", "direct_url")):
        return args
    if not any(str(args.get(key) or "").strip() for key in ("category", "purpose", "notes", "preservation_mode")):
        return args
    recovered = latest_content_asset_batch(pending_only=True)
    if not recovered.get("paths"):
        return args
    hydrated = dict(args)
    hydrated["file_paths"] = recovered["paths"]
    hydrated["recovered_archived_batch"] = True
    return hydrated


def _nonempty(value):
    return value not in (None, "", [], (), {})


def _as_mapping_list(value):
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _nested_geo_locations(value):
    """Return the narrowest explicit geography from a model-style ad set."""
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []
    for key, location_type in (("cities", "city"), ("regions", "region")):
        raw_items = value.get(key)
        if not _nonempty(raw_items):
            continue
        items = raw_items if isinstance(raw_items, list) else [raw_items]
        normalized = []
        for item in items:
            if isinstance(item, dict):
                clean = dict(item)
                clean.setdefault("type", location_type)
                normalized.append(clean)
            elif str(item or "").strip():
                # A name is a query, never an ID. The campaign engine resolves
                # it against Meta immediately before creating anything.
                normalized.append(str(item).strip())
        if normalized:
            return normalized
    countries = value.get("countries")
    if _nonempty(countries):
        return countries if isinstance(countries, list) else [countries]
    return []


def canonicalize_destination_campaign_shape(arguments):
    """Recover common nested campaign/ad-set/creative shapes without guessing.

    Destination policy remains enforced by ``destination_campaign_arguments``
    and live Meta targeting validation. This adapter only promotes values when
    one unambiguous value exists across the submitted structure.
    """
    args = dict(arguments or {})
    campaign = args.get("campaign")
    if isinstance(campaign, dict):
        for key, aliases in {
            "name": ("name", "campaign_name", "title"),
            "objective": ("objective", "campaign_objective", "goal"),
            "daily_budget": ("daily_budget", "budget", "budget_daily"),
            "budget_level": ("budget_level",),
        }.items():
            if _nonempty(args.get(key)):
                continue
            for alias in aliases:
                if _nonempty(campaign.get(alias)):
                    args[key] = campaign[alias]
                    break
        args.pop("campaign", None)

    ad_sets = _as_mapping_list(args.get("ad_sets") or args.get("adsets"))
    top_creatives = _as_mapping_list(args.get("creatives"))
    if ad_sets:
        args.pop("adsets", None)
        if top_creatives:
            if len(ad_sets) != 1:
                return None, "ambiguous_top_level_creatives"
            if not _nonempty(ad_sets[0].get("ads")) and not _nonempty(ad_sets[0].get("creatives")):
                ad_sets[0] = {**ad_sets[0], "ads": top_creatives}
            args.pop("creatives", None)
        args["ad_sets"] = ad_sets

        if not _nonempty(args.get("daily_budget")):
            budgets = [item.get("daily_budget") or item.get("budget") for item in ad_sets]
            budgets = [value for value in budgets if _nonempty(value)]
            if budgets and len({str(value) for value in budgets}) == 1:
                args["daily_budget"] = budgets[0]

        for field in ("age_min", "age_max", "genders", "gender", "targeting_mode"):
            if _nonempty(args.get(field)):
                continue
            values = [item.get(field) for item in ad_sets if _nonempty(item.get(field))]
            if values and len({json.dumps(value, sort_keys=True, ensure_ascii=False) for value in values}) == 1:
                args[field] = values[0]

        if not _nonempty(args.get("placements")):
            values = [item.get("placements") for item in ad_sets if _nonempty(item.get("placements"))]
            unique = {json.dumps(value, sort_keys=True, ensure_ascii=False) for value in values}
            # Different complete placements are valid per-ad-set overrides.
            # Promote only one common value; otherwise preserve every set and
            # let the destination guard verify that none is missing.
            if len(unique) == 1 and values:
                args["placements"] = values[0]

        if not _nonempty(args.get("locations")) and not _nonempty(args.get("countries")):
            location_values = []
            for item in ad_sets:
                targeting = item.get("targeting") if isinstance(item.get("targeting"), dict) else {}
                direct = (
                    item.get("locations") or item.get("targeting_locations")
                    or targeting.get("locations") or targeting.get("targeting_locations")
                )
                geo = item.get("geo_locations") or targeting.get("geo_locations")
                resolved = direct if _nonempty(direct) else _nested_geo_locations(geo)
                if _nonempty(resolved):
                    location_values.append(resolved)
            unique = {json.dumps(value, sort_keys=True, ensure_ascii=False) for value in location_values}
            if len(unique) == 1 and location_values:
                args["locations"] = location_values[0]

    creative_candidates = top_creatives
    if not creative_candidates and len(ad_sets) == 1:
        creative_candidates = _as_mapping_list(ad_sets[0].get("ads") or ad_sets[0].get("creatives"))
    if creative_candidates and not any(args.get(key) for key in CAMPAIGN_CREATIVE_SOURCE_KEYS):
        first = creative_candidates[0]
        for source, target in (
            ("image_path", "creative_image_path"),
            ("creative_image_path", "creative_image_path"),
            ("image_url", "image_url"),
            ("video_path", "video_path"),
            ("video_url", "video_url"),
            ("video_id", "video_id"),
            ("object_story_id", "object_story_id"),
        ):
            if _nonempty(first.get(source)):
                args[target] = first[source]
                break
    return args, ""


def destination_campaign_arguments(tool, arguments, *, budget_parser=None, budget_contract=None):
    """Apply immutable destination policy before the shared campaign engine."""
    args, shape_error = canonicalize_destination_campaign_shape(arguments)
    if shape_error:
        return None, shape_error
    budget_confirmation = str(args.pop("budget_confirmation", "") or "").strip()
    if not budget_confirmation:
        return None, "missing_budget_confirmation"
    if callable(budget_contract):
        contract = budget_contract(budget_confirmation)
        if not isinstance(contract, dict) or not contract.get("ok"):
            return None, str((contract or {}).get("reason") or "invalid_budget_confirmation")
        confirmed_budget = contract.get("amount")
        account_currency = str(contract.get("currency") or "").strip().upper()
    elif not callable(budget_parser):
        return None, "budget_parser_unavailable"
    else:
        confirmed_budget = budget_parser(budget_confirmation, default=None)
        account_currency = ""
    try:
        confirmed_budget = float(confirmed_budget)
    except (TypeError, ValueError):
        confirmed_budget = 0.0
    if confirmed_budget <= 0:
        return None, "invalid_budget_confirmation"
    # The buyer-facing quote is authoritative. Models sometimes convert a
    # major-unit amount such as 5 USD into Meta's 500 minor units. The shared
    # campaign engine performs that API conversion later, so preserve 5 here.
    args["daily_budget"] = confirmed_budget
    args["daily_budget_raw"] = budget_confirmation
    if account_currency:
        args["account_currency"] = account_currency
        args["ad_account_currency"] = account_currency
    ad_sets = args.get("ad_sets") if isinstance(args.get("ad_sets"), list) else []

    def every_ad_set_has(field):
        return bool(ad_sets) and all(
            isinstance(item, dict) and _nonempty(item.get(field))
            for item in ad_sets
        )

    locations = args.get("locations")
    if (
        locations in (None, "", [], ())
        and args.get("countries") in (None, "", [], ())
        and not every_ad_set_has("locations")
    ):
        return None, "missing_targeting_locations"
    if isinstance(locations, list) and any(isinstance(item, dict) for item in locations):
        # The dashboard treats live city/region selections as
        # targeting_locations; leaving them under the loose locations alias
        # used to erase the IDs and silently fall back to US.
        args["targeting_locations"] = locations
        args.pop("locations", None)
    placements = args.get("placements")
    if placements in (None, "", [], ()):
        if not every_ad_set_has("placements"):
            return None, "missing_placements_confirmation"
    if isinstance(placements, str):
        normalized_placement_text = placements.strip().lower()
        if "automatic" in normalized_placement_text or "advantage" in normalized_placement_text:
            args["placements"] = {"automatic": True}
        else:
            args["placements"] = [placements]
    elif isinstance(placements, dict):
        normalized_placements = {
            str(key or "").strip().strip("\"'").lower(): value
            for key, value in placements.items()
        }
        if "automatic" not in normalized_placements:
            return None, "invalid_placements_confirmation"
        automatic = normalized_placements.get("automatic")
        if isinstance(automatic, str):
            automatic = automatic.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}
        manual = normalized_placements.get("manual")
        if bool(automatic):
            args["placements"] = {"automatic": True}
        elif isinstance(manual, list) and manual:
            args["placements"] = {"automatic": False, "manual": manual}
        else:
            return None, "invalid_placements_confirmation"
    elif placements not in (None, "", [], ()) and not isinstance(placements, list):
        return None, "invalid_placements_confirmation"
    for key in ("status_plan", "status", "desired_status", "campaign_status", "adset_status", "ad_set_status", "ad_status"):
        args.pop(key, None)
    args["final_status"] = "PAUSED"
    args["active_spend_confirmed"] = False
    # A campaign request is not approval for model-invented ad material.  Keep
    # this close to the destination boundary so direct tool callers cannot
    # bypass the compiler's buyer-evidence check.
    if tool in CAMPAIGN_CREATION_TOOLS:
        if not str(args.get("primary_text") or "").strip():
            return None, "missing_primary_text"
        if not str(args.get("headline") or "").strip():
            return None, "missing_headline"
        if args.get("primary_text_approved") is not True:
            return None, "primary_text_not_approved"
        if args.get("headline_approved") is not True:
            return None, "headline_not_approved"
        if not str(args.get("creative_decision") or "").strip():
            return None, "missing_creative_decision"
        if args.get("creative_approved") is not True:
            return None, "creative_not_approved"
    external_keys = {
        "landing_url", "message_destination", "whatsapp_phone_number_id",
        "lead_gen_form_id", "lead_form_id", "instant_form_id",
        "application_id", "object_store_url", "prefilled_message",
        "welcome_message",
    }
    if tool == "admira_create_whatsapp_campaign":
        creative_decision = str(args.get("creative_decision") or "").strip()
        if not str(args.get("prefilled_message") or "").strip() and not every_ad_set_has("prefilled_message"):
            return None, "missing_prefilled_message"
        if args.get("prefilled_message_approved") is not True:
            return None, "prefilled_message_not_approved"
        args.pop("landing_url", None)
        args["objective"] = "MESSAGES"
        args["message_destination"] = "WHATSAPP"
    elif tool == "admira_create_lead_form_campaign":
        for key in ("landing_url", "message_destination", "application_id", "object_store_url"):
            args.pop(key, None)
        args["objective"] = "LEADS"
    elif tool == "admira_create_website_campaign":
        for key in external_keys - {"landing_url"}:
            args.pop(key, None)
        # A bare website destination does not prove that a Pixel/Dataset or
        # conversion event exists. Default safely to traffic/landing-page
        # views; preserve an explicit buyer-selected sales/conversion
        # objective so the normal promoted-object preflight can validate it.
        if not str(args.get("objective") or "").strip():
            args["objective"] = "TRAFFIC"
    elif tool == "admira_create_messaging_campaign":
        args.pop("landing_url", None)
        args["objective"] = "MESSAGES"
        destination = str(args.get("message_destination") or "").strip().upper()
        if destination not in {"MESSENGER", "INSTAGRAM_DIRECT"}:
            return None, "message_destination_must_be_messenger_or_instagram_direct"
        args["message_destination"] = destination
    elif tool == "admira_create_app_campaign":
        for key in external_keys - {"application_id", "object_store_url"}:
            args.pop(key, None)
        args["objective"] = "APP_PROMOTION"
        args["app_destination"] = True
    elif tool == "admira_create_on_meta_campaign":
        for key in external_keys:
            args.pop(key, None)
        objective = str(args.get("objective") or "").strip().upper()
        allowed = {
            "AWARENESS", "OUTCOME_AWARENESS", "ENGAGEMENT", "OUTCOME_ENGAGEMENT",
            "VIDEO", "VIDEO_VIEWS", "THRUPLAY", "POST_ENGAGEMENT",
        }
        if objective not in allowed:
            return None, "on_meta_objective_must_be_awareness_video_or_engagement"
        args["on_meta_destination"] = True
    for collection_key in ("ad_sets", "ads"):
        collection = args.get(collection_key)
        if not isinstance(collection, list):
            continue
        normalized = []
        for item in collection:
            if not isinstance(item, dict):
                normalized.append(item)
                continue
            clean = dict(item)
            for key in ("status", "final_status", "campaign_status", "adset_status", "ad_status"):
                clean[key] = "PAUSED"
            normalized.append(clean)
        args[collection_key] = normalized
    return args, ""


def _campaign_blocker_details(value, details=None, depth=0):
    details = details if details is not None else []
    if depth > 10:
        return details
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"reason", "error", "message", "missing", "missing_requirements"} and item not in (None, "", [], {}):
                rendered = json.dumps(item, ensure_ascii=False) if not isinstance(item, str) else item
                if rendered not in details:
                    details.append(rendered[:1000])
            _campaign_blocker_details(item, details, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _campaign_blocker_details(item, details, depth + 1)
    return details[:12]


def persist_pending_campaign_workflow(tool, args, reason, *, result=None, status="pending"):
    """Keep one structured buyer workflow across /reset without claiming Meta creation."""
    if tool not in CAMPAIGN_CREATION_TOOLS:
        return False
    source = args if isinstance(args, dict) else {}
    allowed = (
        "name", "objective", "daily_budget", "daily_budget_raw", "budget_confirmation",
        "account_currency", "locations", "targeting_locations", "countries", "placements",
        "age_min", "age_max", "genders", "gender", "targeting_mode", "primary_text",
        "headline", "primary_text_approved", "headline_approved", "prefilled_message",
        "creative_decision", "creative_approved",
        "prefilled_message_approved", "creative_asset_id", "content_asset_id",
        "content_asset_ids", "creative_image_path", "video_path", "video_url", "object_story_id",
        "success_metrics",
    )
    contract = {key: source.get(key) for key in allowed if source.get(key) not in (None, "", [], {})}
    destination = tool.removeprefix("admira_create_").removesuffix("_campaign")
    next_step_by_reason = {
        "missing_creative_decision": "Ask once whether to create a new creative, reuse a recent creative, or use a buyer upload.",
        "creative_not_approved": "Finish and show the exact creative, then obtain the buyer's approval for that asset.",
        "missing_verified_creative": "Create, recover, or receive the exact creative before retrying campaign creation.",
        "missing_prefilled_message": "Propose the exact WhatsApp prefilled message and show it to the buyer.",
        "prefilled_message_not_approved": "Show the exact WhatsApp prefilled message and obtain explicit approval.",
    }
    payload = {
        "status": status,
        "destination": destination,
        "tool": tool,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "campaign_contract": contract,
        "blocker": str(reason or "campaign_creation_not_verified"),
        "blocker_details": _campaign_blocker_details(result),
        "next_step": next_step_by_reason.get(str(reason or ""), "Resolve the exact blocker and resume this campaign; do not restart onboarding."),
        "meta_creation_verified": status == "completed",
    }
    proposal_brief = str(source.get("brief_markdown") or "").strip()
    if proposal_brief:
        # Keep the exact held proposal private so a later short “sí” can
        # approve what was shown, without treating an empty pending blocker as
        # permission to invent a fresh budget or creative.
        payload["proposal_brief_markdown"] = proposal_brief[:60000]
    try:
        PENDING_CAMPAIGN_WORKFLOW_FILE.parent.mkdir(parents=True, exist_ok=True)
        PENDING_CAMPAIGN_WORKFLOW_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            PENDING_CAMPAIGN_WORKFLOW_FILE.chmod(0o600)
        except OSError:
            pass
        return True
    except OSError:
        return False


def campaign_has_verified_creative(args, reference_paths=()):
    if reference_paths:
        return True
    if not isinstance(args, dict):
        return False
    if args.get("manual_creative_completion") or args.get("create_placeholder_ad"):
        return True
    return any(
        args.get(key)
        for key in ("image_hash", "image_url", "video_url", "video_id", "object_story_id")
    )


def verified_paused_campaign_result(result):
    """Require a materialized PAUSED campaign, ad set and ad from Meta."""
    if not isinstance(result, dict) or not result.get("executed"):
        return False
    creation = result.get("result")
    if not isinstance(creation, dict):
        return False
    execution = creation.get("result")
    if not isinstance(execution, dict):
        return False
    campaign_id = str(execution.get("campaign_id") or "").strip()
    adset_ids = [str(value).strip() for value in (execution.get("adset_ids") or []) if str(value).strip()]
    ad_ids = [str(value).strip() for value in (execution.get("ad_ids") or []) if str(value).strip()]
    return bool(
        creation.get("status") == "created_paused"
        and creation.get("executed") is True
        and execution.get("executed") is True
        and campaign_id and adset_ids and ad_ids
    )


def call_tool(name, arguments=None, channel="telegram", language="es"):
    tool = normalize_tool_name(name)
    args = normalize_tool_arguments(arguments)
    if tool not in PUBLIC_TOOLS:
        return {
            "ok": False,
            "tool": tool,
            "blocked": True,
            "reason": "unsupported_tool",
            "reply": "Esa herramienta no está disponible para Admira IA.",
        }

    if tool in CAMPAIGN_EDIT_TOOLS:
        args = normalize_campaign_edit_arguments(args)
    if not args and tool in EMPTY_ARGUMENT_GUARDED_TOOLS:
        return empty_tool_arguments_result(tool)
    args = hydrate_archived_content_asset_paths(tool, args)
    dashboard = load_dashboard()
    if tool in CAMPAIGN_EDIT_TOOLS:
        return redact_payload(dashboard.handle_campaign_edit_tool(args, chat_payload(channel, language), tool))
    campaign_compilation = None
    if tool in CAMPAIGN_CREATION_TOOLS:
        original_campaign_args = dict(args)
        brief_markdown = str(args.get("brief_markdown") or "").strip()
        if brief_markdown:
            campaign_compilation = compile_campaign_brief(tool, brief_markdown)
            if not campaign_compilation.get("ok"):
                reason = str(campaign_compilation.get("reason") or "campaign_compiler_failed")
                persist_pending_campaign_workflow(tool, original_campaign_args, reason)
                missing = campaign_compilation.get("missing_fields") or []
                if reason == "campaign_brief_incomplete":
                    labels = {
                        "budget_confirmation": "el presupuesto diario exacto y su moneda",
                        "creative_approval": "la elección y aprobación del creativo exacto",
                        "primary_text_approval": "la aprobación del texto principal del anuncio",
                        "headline_approval": "la aprobación del título del anuncio",
                        "prefilled_message_approval": "la aprobación del mensaje inicial de WhatsApp",
                    }
                    detail = ", ".join(labels.get(str(value), str(value)) for value in missing) or "datos de campaña"
                    reply = f"No se creó nada en Meta: el briefing aún necesita confirmar {detail}."
                else:
                    reply = str(campaign_compilation.get("error") or "Terra no pudo compilar el briefing de campaña. Intenta de nuevo sin cambiar los datos aprobados.")
                return {
                    "ok": False,
                    "tool": tool,
                    "product_tool": "create_campaign_stack",
                    "blocked": True,
                    "executed": False,
                    "reason": reason,
                    "missing_fields": missing,
                    "compiler_model": campaign_compilation.get("model") or "gpt-5.6-terra",
                    "reply": reply,
                }
            args = dict(campaign_compilation.get("payload") or {})
        args, destination_error = destination_campaign_arguments(
            tool,
            args,
            budget_parser=getattr(dashboard, "parse_money_like", None),
            budget_contract=getattr(dashboard, "confirmed_budget_contract", None),
        )
        if destination_error:
            persist_pending_campaign_workflow(tool, original_campaign_args, destination_error)
            replies = {
                "missing_creative_decision": "No se creó nada en Meta: primero pregunta si el cliente quiere crear un creativo nuevo, reutilizar uno reciente o usar una imagen subida.",
                "creative_not_approved": "No se creó nada en Meta: falta terminar y aprobar el creativo exacto que llevará el anuncio.",
                "missing_primary_text": "No se creó nada en Meta: falta el texto principal exacto del anuncio.",
                "missing_headline": "No se creó nada en Meta: falta el título exacto del anuncio.",
                "primary_text_not_approved": "No se creó nada en Meta: muestra el texto principal exacto y espera la aprobación o edición del cliente.",
                "headline_not_approved": "No se creó nada en Meta: muestra el título exacto y espera la aprobación o edición del cliente.",
                "missing_prefilled_message": "No se creó nada en Meta: falta definir el mensaje exacto que aparecerá al abrir WhatsApp.",
                "prefilled_message_not_approved": "No se creó nada en Meta: muestra el mensaje exacto de WhatsApp y obtén la aprobación del cliente.",
            }
            return {
                "ok": False,
                "tool": tool,
                "product_tool": "create_campaign_stack",
                "blocked": True,
                "executed": False,
                "reason": destination_error,
                "reply": replies.get(destination_error) or (
                    "No se creó nada en Meta: falta confirmar el presupuesto diario exacto en moneda principal."
                    if "budget" in destination_error
                    else "No se creó nada en Meta: falta una ubicación o decisión de ubicaciones explícita."
                    if "location" in destination_error
                    else "No se creó nada en Meta: falta indicar ubicaciones automáticas o la lista manual exacta."
                    if "placement" in destination_error
                    else "No se creó nada en Meta: el destino no coincide con el contrato de esta campaña."
                ),
            }
    if tool == "admira_stage_budget_change":
        budget_confirmation = str(args.get("budget_confirmation") or "").strip()
        budget_contract = getattr(dashboard, "confirmed_budget_contract", None)
        contract = budget_contract(budget_confirmation) if callable(budget_contract) else {"ok": False, "reason": "budget_contract_unavailable"}
        if not contract.get("ok"):
            return {
                "ok": False,
                "tool": tool,
                "product_tool": "set_budget",
                "blocked": True,
                "executed": False,
                "reason": contract.get("reason") or "invalid_budget_confirmation",
                "reply": "No preparé el cambio: el monto y la moneda deben coincidir exactamente con la cuenta publicitaria seleccionada.",
            }
        args["new_budget"] = float(contract["amount"])
        args["daily_budget"] = float(contract["amount"])
        args["budget_confirmation"] = budget_confirmation
        args["account_currency"] = contract["currency"]
    payload = chat_payload(channel, language)
    # Telegram can lose the file path/asset ID while Hermes compacts a long
    # turn. A PAUSED campaign still needs a real static source, so recover the
    # newest buyer-approved classified batch instead of returning the generic
    # missing_creative_image_path error. This is deliberately not applied to
    # video/manual-placeholder flows or to any spend-capable action.
    if tool in CAMPAIGN_STAGE_TOOLS and not any(args.get(key) for key in CAMPAIGN_CREATIVE_SOURCE_KEYS):
        controls_text = json.dumps(args or {}, ensure_ascii=False).lower()
        manual_completion = bool(args.get("manual_creative_completion") or args.get("create_placeholder_ad"))
        video_requested = bool(args.get("video_url")) or any(token in controls_text for token in ("video", "video_url", "video_creative"))
        if not manual_completion and not video_requested:
            recovered = latest_content_asset_batch(approved_for_ads=True, limit=8)
            if recovered.get("paths"):
                args = dict(args)
                args["content_asset_ids"] = recovered.get("asset_ids") or []
                args["image_paths"] = recovered["paths"][:8]
                args["recovered_approved_content_batch"] = True
                payload["image_paths"] = recovered["paths"][:8]
    reference_paths = safe_image_paths(args, limit=8 if tool in CREATIVE_IMAGE_TOOLS else 4)
    if not reference_paths and tool in CREATIVE_IMAGE_TOOLS and creative_args_mentions_uploaded_image(args):
        reference_paths = latest_workspace_image_paths()
    if not reference_paths and tool in CAMPAIGN_STAGE_TOOLS and creative_args_mentions_uploaded_image(args):
        reference_paths = latest_workspace_image_paths(limit=1)
    if reference_paths:
        payload["image_paths"] = reference_paths[:8]

    if tool == "admira_get_real_meta_context":
        date_preset = str(args.get("date_preset") or args.get("range") or "maximum").strip().lower()
        detail_level = str(args.get("detail_level") or "deep").strip().lower()
        include_breakdowns = detail_level in {"deep", "full", "breakdowns"}
        live_sync = dashboard.refresh_managed_real_metrics(
            reason="agent_live_context",
            date_preset=date_preset,
            since=str(args.get("since") or "").strip(),
            until=str(args.get("until") or "").strip(),
            persist=False,
            include_breakdowns=include_breakdowns,
        )
        dashboard_data = dashboard.dashboard_payload()
        cached_metrics = dashboard_data.get("metrics") if isinstance(dashboard_data.get("metrics"), dict) else {}
        cached_confirmed_at = str(cached_metrics.get("timestamp") or "")
        if isinstance(live_sync.get("metrics"), dict):
            # The model sees the just-fetched read-only snapshot. The dashboard
            # keeps its own buyer-selected date range and is not silently reset
            # by background Telegram synchronization.
            dashboard_data["metrics"] = live_sync["metrics"]
        context = account_context(dashboard_data)
        oauth = dashboard.social_oauth_status()
        oauth_accounts = oauth.get("accounts") or []
        oauth_pages = oauth.get("pages") or []
        oauth_businesses = oauth.get("businesses") or []
        oauth_authorized = bool(oauth.get("connected"))
        workspace_selected = bool(oauth.get("active_ad_account_id")) and bool(oauth.get("active_page_id"))
        context["oauth_workspace"] = {
            "authorized": oauth_authorized,
            "selection_required": bool(oauth_authorized and not workspace_selected),
            "active_ad_account_id": str(oauth.get("active_ad_account_id") or ""),
            "active_page_id": str(oauth.get("active_page_id") or ""),
            "account_count": len(oauth_accounts),
            "page_count": len(oauth_pages),
            "publishable_page_count": sum(1 for page in oauth_pages if page.get("can_publish")),
            "business_count": len(oauth_businesses),
            "accounts": oauth_accounts[:25],
            "pages": oauth_pages[:25],
            "businesses": oauth_businesses[:25],
        }
        context["live_sync"] = {
            "ok": bool(live_sync.get("ok")),
            "rows": int(live_sync.get("rows") or 0),
            "accounts": live_sync.get("accounts") or [],
            "errors": live_sync.get("errors") or [],
            "partial": bool(live_sync.get("partial")),
            "reason": live_sync.get("reason") or "",
            "category": live_sync.get("category") or "",
            "message": live_sync.get("message") or "",
            "error_details": live_sync.get("raw") or live_sync.get("errors") or [],
            "connection": live_sync.get("connection") or {},
            "data_quality": live_sync.get("data_quality") or (live_sync.get("metrics") or {}).get("data_quality") or {},
            "fetched_at": (live_sync.get("metrics") or {}).get("timestamp") or "",
            "cached_confirmed_at": cached_confirmed_at,
            "date_preset": date_preset,
            "detail_level": detail_level,
        }
        if context["oauth_workspace"]["selection_required"] and context["live_sync"]["reason"] == "missing_account":
            context["live_sync"].update({
                "reason": "workspace_selection_required",
                "message": "Facebook OAuth is authorized; choose an ad account and Page before live campaign synchronization.",
                "connection": {
                    "oauth_authorized": True,
                    "workspace_selected": False,
                },
            })
        live_metrics = live_sync.get("metrics") if isinstance(live_sync.get("metrics"), dict) else {}
        context["breakdowns"] = {
            name: rows[:300]
            for name, rows in (live_metrics.get("breakdowns") or {}).items()
            if isinstance(rows, list)
        }
        context["approval_context_policy"] = (
            "Pending approvals are intentionally excluded from ambient account state. "
            "Read them only after an explicit buyer approval/rejection/activation request; "
            "they never prove what currently exists or runs in Meta."
        )
        if not live_sync.get("ok"):
            context["metrics_source"].update({
                "fresh": False,
                "live_sync_ok": False,
                "last_confirmed_at": cached_confirmed_at,
                "notice": (
                    "La sincronización live con Meta falló. Los datos mostrados son el último estado confirmado, no el estado actual. "
                    "No interpretes una lista vacía como ausencia de campañas ni culpes a la credencial cuando connection.reachable sea true."
                ),
            })
            if context["oauth_workspace"]["selection_required"]:
                context["metrics_source"]["notice"] = (
                    "Facebook ya está autorizado y los activos OAuth están disponibles. "
                    "Falta únicamente que el comprador elija la cuenta publicitaria y Página activas; no solicites permisos ni otro enlace."
                )
        elif live_sync.get("partial"):
            context["metrics_source"].update({
                "fresh": False,
                "live_sync_ok": True,
                "partial": True,
                "last_confirmed_at": context["live_sync"].get("fetched_at") or cached_confirmed_at,
                "notice": (
                    "Meta respondió parcialmente. Usa solamente los objetos que sí fueron verificados; una sección faltante no equivale a cero."
                ),
            })
        else:
            context["metrics_source"].update({
                "fresh": True,
                "live_sync_ok": True,
                "partial": False,
                "last_confirmed_at": context["live_sync"].get("fetched_at"),
            })
        return redact_payload(
            {
                "ok": True,
                "tool": tool,
                "metrics_source": context.get("metrics_source", {}),
                "live_sync": context.get("live_sync", {}),
                "context": context,
            }
        )

    if tool == "admira_get_meta_oauth_workspaces":
        result = dashboard.social_oauth_status()
        return redact_payload({"ok": bool(result.get("connected")), "tool": tool, "result": result})

    if tool == "admira_start_meta_oauth_connection":
        # This sends the buyer's own short-lived Facebook authorization link to
        # the configured Telegram chat.  It is connection setup only: it never
        # creates ads, changes an account, or exposes a token to Hermes.
        result = dashboard.social_oauth_start(args)
        return redact_payload({"ok": bool(result.get("ok")), "tool": tool, "result": result})

    if tool == "admira_select_meta_oauth_workspace":
        result = dashboard.social_oauth_select(args)
        return redact_payload({"ok": bool(result.get("selected")), "tool": tool, "result": result})

    if tool == "admira_list_pending_approvals":
        pending = dashboard.read_json(dashboard.PENDING_FILE, [])
        pending = [item for item in pending if isinstance(item, dict) and item.get("status", "pending") == "pending"]
        return redact_payload({"ok": True, "tool": tool, "pending": pending[:20]})

    if tool == "admira_search_meta_targeting":
        result = dashboard.meta_targeting_search(args)
        return redact_payload({"ok": bool(result.get("ok")), "tool": tool, "source": "meta_live", "result": result})

    if tool == "admira_inspect_adset_targeting":
        result = dashboard.meta_adset_targeting_status(args)
        return redact_payload({"ok": bool(result.get("ok")), "tool": tool, "source": "meta_live", "result": result})

    if tool == "admira_list_recent_creatives":
        result = dashboard.recent_generated_creatives(
            when=args.get("when") or "last_3_days",
            limit=args.get("limit") or 24,
            cleanup=True,
        )
        return redact_payload({"ok": bool(result.get("ok")), "tool": tool, "result": result})

    product_tool = TOOL_MAP[tool]
    product_args = dict(args)
    if tool in CAMPAIGN_STAGE_TOOLS and reference_paths and not any(product_args.get(key) for key in CAMPAIGN_CREATIVE_SOURCE_KEYS):
        product_args["creative_image_path"] = reference_paths[0]
    if tool in CAMPAIGN_CREATION_TOOLS and not campaign_has_verified_creative(product_args, reference_paths):
        persist_pending_campaign_workflow(tool, product_args, "missing_verified_creative")
        return redact_payload({
            "ok": False,
            "tool": tool,
            "product_tool": "create_campaign_stack",
            "blocked": True,
            "executed": False,
            "reason": "missing_verified_creative",
            "reply": (
                "No se creó nada en Meta: la imagen o video indicado no existe o no fue verificado. "
                "Primero crea, recupera o recibe el creativo exacto y muéstraselo al cliente; después reintenta con ese archivo aprobado."
            ),
        })
    if tool == "admira_approve_action":
        product_args["decision"] = "approve"
    elif tool == "admira_reject_action":
        product_args["decision"] = "reject"

    result = dashboard.execute_agent_tool({"tool": product_tool, "arguments": product_args}, payload)
    response = {
        "ok": result_ok(result),
        "tool": tool,
        "product_tool": product_tool,
        "result": result,
    }
    if tool in CAMPAIGN_CREATION_TOOLS:
        if campaign_compilation:
            response["payload_compiler"] = {
                "model": campaign_compilation.get("model"),
                "destination": campaign_compilation.get("destination"),
                "brief_persisted": True,
                "payload_persisted": True,
            }
        verified = verified_paused_campaign_result(result)
        response["campaign_creation_verified"] = verified
        if not verified:
            response["ok"] = False
            response["blocked"] = True
            response["executed"] = False
            response["reason"] = (
                result.get("reason") if isinstance(result, dict) and result.get("reason")
                else "campaign_creation_not_verified"
            )
            response["reply"] = (
                "No se creó la campaña en Meta. La herramienta no confirmó una campaña, "
                "un conjunto y un anuncio PAUSED con IDs reales; conserva el error exacto "
                "y no digas que quedó preparada, configurada ni en pausa."
            )
            persist_pending_campaign_workflow(tool, product_args, response["reason"], result=result)
        else:
            persist_pending_campaign_workflow(tool, product_args, "", result=result, status="completed")
    if tool == "admira_save_business_memory" and result_ok(result):
        profile = result.get("profile") if isinstance(result, dict) else {}
        if isinstance(profile, dict) and profile.get("context_completed_at"):
            # Business discovery deliberately transitions to a proactive
            # organic-content proposal first.  OAuth is requested only after
            # the buyer accepts or adjusts that strategy, so onboarding feels
            # like useful marketing work rather than connection paperwork.
            response["organic_content_strategy_required"] = True
            response["next_onboarding_phase"] = "organic_content_strategy"
    media_attachment = generated_media_attachment_for_result(tool, result)
    if media_attachment:
        response["media_attachment"] = media_attachment
        response["buyer_delivery_instruction"] = (
            "Native attachment prepared. In the visible buyer reply, say the generated media is attached here. "
            "Do not paste MEDIA:/... or local file paths as links."
        )
    return redact_payload(response)


def cli(argv=None):
    parser = argparse.ArgumentParser(description="Admira IA product tool bridge")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    call = sub.add_parser("call")
    call.add_argument("tool")
    call.add_argument("--json", default="{}")
    call.add_argument("--channel", default="telegram")
    call.add_argument("--language", default="es")
    args = parser.parse_args(argv)
    if args.command == "list":
        print(json.dumps({"tools": PUBLIC_TOOLS}, ensure_ascii=False))
        return 0
    try:
        payload = json.loads(args.json or "{}")
        if not isinstance(payload, dict):
            raise ValueError("JSON payload must be an object")
        result = call_tool(args.tool, payload, channel=args.channel, language=args.language)
    except Exception as exc:
        result = {"ok": False, "error": str(exc), "tool": getattr(args, "tool", "")}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(cli())
