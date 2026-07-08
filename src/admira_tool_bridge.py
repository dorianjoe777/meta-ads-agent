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
    "admira_preflight_campaign": "preflight_campaign",
    "admira_fetch_public_asset": "fetch_public_asset",
    "admira_codex_image_generate": "codex_image_generate",
    "admira_codex_creative_plan": "codex_creative_plan",
    "admira_list_lead_forms": "list_lead_forms",
    "admira_stage_lead_form": "stage_lead_form",
    "admira_stage_campaign": "create_campaign_stack",
    "admira_stage_budget_change": "set_budget",
    "admira_pause_campaign": "pause_campaign",
    "admira_resume_campaign": "resume_campaign",
    "admira_delete_campaign": "delete_campaign",
    "admira_approve_action": "approval_decision",
    "admira_reject_action": "approval_decision",
    "admira_save_agent_preferences": "save_agent_preferences",
    "admira_save_daily_social_content_settings": "save_daily_social_content_settings",
    "admira_save_content_asset": "save_content_asset",
    "admira_record_verified_signal": "record_verified_signal",
    "admira_get_verified_signal_summary": "get_verified_signal_summary",
    "admira_verified_signal_feedback_prompt": "verified_signal_feedback_prompt",
    "admira_save_business_memory": "save_business_context",
    "admira_save_ads_onboarding": "save_ads_onboarding",
    "admira_save_brand_memory": "save_brand_guide",
    "admira_save_product_memory": "save_product_guide",
    "admira_save_ad_brief": "save_ad_brief",
    "admira_save_creative_references": "save_creative_references",
}

PUBLIC_TOOLS = sorted(["admira_get_real_meta_context", "admira_list_pending_approvals", *TOOL_MAP.keys()])
ARGUMENT_WRAPPER_KEYS = {"arguments", "args", "kwargs", "payload", "fields", "data", "input"}
CREATIVE_IMAGE_TOOLS = {"admira_codex_image_generate", "admira_codex_creative_plan"}
CAMPAIGN_STAGE_TOOLS = {"admira_stage_campaign"}
CAMPAIGN_CREATIVE_SOURCE_KEYS = {
    "creative_image_path",
    "image_hash",
    "image_url",
    "video_url",
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
    if tool != "admira_codex_image_generate" or not result_ok(result):
        return ""
    nested = (result or {}).get("result") if isinstance(result, dict) else {}
    if not isinstance(nested, dict):
        return ""
    raw_path = nested.get("image_path")
    if not raw_path:
        return ""
    try:
        path = Path(str(raw_path)).expanduser().resolve()
        path.relative_to((ROOT_DIR / "output").resolve())
    except (OSError, RuntimeError, ValueError):
        return ""
    if path.suffix.lower() not in IMAGE_OUTPUT_EXTENSIONS or not path.exists() or not path.is_file():
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
    safe = safe_image_paths({"image_paths": candidates})
    return safe[:limit]


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

    dashboard = load_dashboard()
    payload = chat_payload(channel, language)
    reference_paths = safe_image_paths(args)
    if not reference_paths and tool in CREATIVE_IMAGE_TOOLS and creative_args_mentions_uploaded_image(args):
        reference_paths = latest_workspace_image_paths()
    if not reference_paths and tool in CAMPAIGN_STAGE_TOOLS and creative_args_mentions_uploaded_image(args):
        reference_paths = latest_workspace_image_paths(limit=1)
    if reference_paths:
        payload["image_paths"] = reference_paths[:4]

    if tool == "admira_get_real_meta_context":
        dashboard_data = dashboard.dashboard_payload()
        context = account_context(dashboard_data)
        return redact_payload(
            {
                "ok": True,
                "tool": tool,
                "metrics_source": context.get("metrics_source", {}),
                "context": context,
            }
        )

    if tool == "admira_list_pending_approvals":
        pending = dashboard.read_json(dashboard.PENDING_FILE, [])
        pending = [item for item in pending if isinstance(item, dict) and item.get("status", "pending") == "pending"]
        return redact_payload({"ok": True, "tool": tool, "pending": pending[:20]})

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
            "Native attachment prepared. In the visible buyer reply, say the image is attached here. "
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
