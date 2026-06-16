#!/usr/bin/env python3
"""MCP server that exposes Admira IA product tools to Hermes."""
import json
import sys
import traceback

from admira_tool_bridge import call_tool

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised in lightweight test envs
    FastMCP = None


SERVER_NAME = "admira"
PROTOCOL_VERSION = "2024-11-05"


TOOL_DEFINITIONS = [
    ("get_real_meta_context", "Read the safe real Meta Ads context. Never returns demo metrics as real."),
    ("run_daily_brief", "Run the daily Meta Ads brief and return the safe result."),
    ("codex_image_generate", "Generate a final Meta Ads image through the buyer's ChatGPT/Codex connection."),
    ("codex_creative_plan", "Create a creative concept or prompt plan through Codex."),
    ("stage_campaign", "Stage a full campaign stack for approval."),
    ("stage_budget_change", "Stage or execute a guarded budget change."),
    ("pause_campaign", "Stage or execute a guarded campaign pause."),
    ("resume_campaign", "Stage or execute a guarded campaign resume."),
    ("list_pending_approvals", "List pending approval cards."),
    ("approve_action", "Approve one exact pending action."),
    ("reject_action", "Reject one exact pending action."),
    ("save_business_memory", "Save durable business context."),
    ("save_brand_memory", "Save the general brand guide."),
    ("save_product_memory", "Save a product or offer guide."),
    ("save_ad_brief", "Save a campaign/ad creative brief."),
    ("save_creative_references", "Save approved creative references."),
]


def tool_schema(name, description):
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "additionalProperties": True,
            "properties": {},
        },
    }


def create_fastmcp_server():
    if FastMCP is None:
        return None
    server = FastMCP(
        SERVER_NAME,
        instructions=(
            "Protected Admira IA product tools. Use these for real Meta Ads context, "
            "approvals, campaign staging, budget actions, creative generation through Codex/Image, "
            "and durable business memory."
        ),
    )

    def _register_tool(tool_name, description):
        def _tool(**kwargs):
            result = call_tool(f"admira_{tool_name}", kwargs or {})
            return json.dumps(result, ensure_ascii=False)

        _tool.__name__ = tool_name
        _tool.__doc__ = description
        try:
            server.add_tool(_tool, name=tool_name, description=description)
        except (AttributeError, TypeError):
            server.tool(name=tool_name, description=description)(_tool)

    for name, description in TOOL_DEFINITIONS:
        _register_tool(name, description)
    return server


def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.decode("utf-8", errors="replace").strip()
        if not line:
            break
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.lower()] = value.strip()
    length = int(headers.get("content-length") or "0")
    if length <= 0:
        return None
    raw = sys.stdin.buffer.read(length)
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def write_message(payload):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def success(request_id, result):
    write_message({"jsonrpc": "2.0", "id": request_id, "result": result})


def failure(request_id, code, message):
    write_message({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def handle_request(request):
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params") or {}
    if request_id is None:
        return
    if method == "initialize":
        return success(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": "1.0.0"},
            },
        )
    if method == "ping":
        return success(request_id, {})
    if method == "tools/list":
        return success(request_id, {"tools": [tool_schema(name, description) for name, description in TOOL_DEFINITIONS]})
    if method == "tools/call":
        name = str(params.get("name") or "").strip()
        arguments = params.get("arguments") or {}
        try:
            result = call_tool(f"admira_{name}", arguments)
            return success(
                request_id,
                {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                    "isError": not bool(result.get("ok")),
                },
            )
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            return success(
                request_id,
                {
                    "content": [{"type": "text", "text": json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)}],
                    "isError": True,
                },
            )
    return failure(request_id, -32601, f"Unsupported MCP method: {method}")


def main():
    fast_server = create_fastmcp_server()
    if fast_server is not None:
        import asyncio

        async def _run():
            await fast_server.run_stdio_async()

        asyncio.run(_run())
        return

    while True:
        message = read_message()
        if message is None:
            break
        handle_request(message)


if __name__ == "__main__":
    main()
