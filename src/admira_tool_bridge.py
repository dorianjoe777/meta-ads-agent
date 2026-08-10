#!/usr/bin/env python3
"""Safe product-tool bridge for Hermes MCP calls."""
import argparse
import importlib.util
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DASHBOARD_PATH = ROOT_DIR / "dashboard" / "monitoring-dashboard.py"
SRC_DIR = ROOT_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent_chat import account_context  # noqa: E402
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
    "admira_search_motion_graphic_recipes": "search_motion_graphic_recipes",
    "admira_generate_motion_graphic_video": "generate_motion_graphic_video",
    "admira_list_lead_forms": "list_lead_forms",
    "admira_stage_lead_form": "stage_lead_form",
    "admira_create_lead_form": "create_lead_form",
    "admira_stage_campaign": "create_campaign_stack",
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

PUBLIC_TOOLS = sorted([
    "admira_get_real_meta_context",
    "admira_search_meta_targeting",
    "admira_inspect_adset_targeting",
    "admira_list_pending_approvals",
    *TOOL_MAP.keys(),
])
ARGUMENT_WRAPPER_KEYS = {"arguments", "args", "kwargs", "payload", "fields", "data", "input"}
CREATIVE_IMAGE_TOOLS = {"admira_codex_image_generate", "admira_codex_creative_plan"}
GENERATED_MEDIA_TOOLS = {"admira_codex_image_generate", "admira_generate_motion_graphic_video"}
CAMPAIGN_STAGE_TOOLS = {"admira_stage_campaign"}
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
    "admira_stage_campaign": ("name", "daily_budget", "destination details", "creative source"),
}


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
    return {**nested, **direct}


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
    elif tool == "admira_stage_campaign":
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

    if not args and tool in EMPTY_ARGUMENT_GUARDED_TOOLS:
        return empty_tool_arguments_result(tool)
    args = hydrate_archived_content_asset_paths(tool, args)

    dashboard = load_dashboard()
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

    product_tool = TOOL_MAP[tool]
    product_args = dict(args)
    if tool in CAMPAIGN_STAGE_TOOLS and reference_paths and not any(product_args.get(key) for key in CAMPAIGN_CREATIVE_SOURCE_KEYS):
        product_args["creative_image_path"] = reference_paths[0]
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
