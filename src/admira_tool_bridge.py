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
    "admira_codex_image_generate": "codex_image_generate",
    "admira_codex_creative_plan": "codex_creative_plan",
    "admira_stage_campaign": "create_campaign_stack",
    "admira_stage_budget_change": "set_budget",
    "admira_pause_campaign": "pause_campaign",
    "admira_resume_campaign": "resume_campaign",
    "admira_approve_action": "approval_decision",
    "admira_reject_action": "approval_decision",
    "admira_save_agent_preferences": "save_agent_preferences",
    "admira_record_verified_signal": "record_verified_signal",
    "admira_get_verified_signal_summary": "get_verified_signal_summary",
    "admira_verified_signal_feedback_prompt": "verified_signal_feedback_prompt",
    "admira_save_business_memory": "save_business_context",
    "admira_save_brand_memory": "save_brand_guide",
    "admira_save_product_memory": "save_product_guide",
    "admira_save_ad_brief": "save_ad_brief",
    "admira_save_creative_references": "save_creative_references",
}

PUBLIC_TOOLS = sorted(["admira_get_real_meta_context", "admira_list_pending_approvals", *TOOL_MAP.keys()])


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


def normalize_tool_name(name):
    tool = str(name or "").strip()
    if tool in PUBLIC_TOOLS:
        return tool
    if tool.startswith("mcp_admira_"):
        return "admira_" + tool.removeprefix("mcp_admira_")
    if not tool.startswith("admira_"):
        return "admira_" + tool
    return tool


def call_tool(name, arguments=None, channel="telegram", language="es"):
    tool = normalize_tool_name(name)
    args = arguments if isinstance(arguments, dict) else {}
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
    reference_paths = args.get("reference_image_paths") or args.get("image_paths") or []
    if isinstance(reference_paths, str):
        reference_paths = [reference_paths]
    if isinstance(reference_paths, list):
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
    if tool == "admira_approve_action":
        product_args["decision"] = "approve"
    elif tool == "admira_reject_action":
        product_args["decision"] = "reject"

    result = dashboard.execute_agent_tool({"tool": product_tool, "arguments": product_args}, payload)
    return redact_payload(
        {
            "ok": result_ok(result),
            "tool": tool,
            "product_tool": product_tool,
            "result": result,
        }
    )


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
