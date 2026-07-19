#!/usr/bin/env python3
"""MCP server that exposes Admira IA product tools to Hermes."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import traceback

from admira_tool_bridge import call_tool

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised in lightweight test envs
    FastMCP = None


SERVER_NAME = "admira"
PROTOCOL_VERSION = "2024-11-05"
ORIGINAL_CALL_TOOL = call_tool
BRIDGE_PATH = Path(__file__).resolve().parent / "admira_tool_bridge.py"
HEAVY_TOOL_NAMES = {"codex_image_generate", "codex_creative_plan", "admira_codex_image_generate", "admira_codex_creative_plan"}
DEFAULT_HEAVY_TOOL_TIMEOUT_SECONDS = 600


TOOL_DEFINITIONS = [
    ("get_real_meta_context", "Synchronize directly with Meta and read the current campaign/ad set/ad inventory plus performance context. Supports date_preset=maximum|today|last_7d|custom, custom since/until dates, and detail_level=standard|deep; deep includes placement/device, age/gender and country breakdowns. Read-only transient Graph failures are retried once. Inspect live_sync.connection and live_sync.error_details: if connection.reachable=true, do not claim Meta is disconnected or the token expired. Preserve code, subcode and fbtrace_id for support. Treat local memory and approvals only as candidate workflow context: they never prove what currently exists or runs in Meta, and a failed/incomplete empty response never proves the account has no campaigns."),
    ("search_meta_targeting", "Search Meta's live targeting catalog for current interest or location IDs. Use kind=interest with q=<term>, or kind=location. Interest names from memory or web research are only ideas: call this tool and use the returned Meta IDs before staging a targeted audience. Never invent an interest ID."),
    ("inspect_adset_targeting", "Read one exact ad set directly from Meta and verify its persisted interest IDs and Advantage+ audience flag. Pass the numeric adset_id and optionally requested_interest_ids plus advantage_audience. Call this before claiming suggested interests or Advantage+ targeting were applied. It confirms Graph state, not the exact Ads Manager UI wording or placement."),
    ("run_daily_brief", "Run the daily Meta Ads brief and return the safe result."),
    ("schedule_experiment_review", "Schedule adaptive delivery and evidence checkpoints for a real creative test. Requires test budget, target CPA/CPL, and at least two variants with real Meta IDs."),
    ("list_experiment_reviews", "List active creative experiments, current evidence, provisional leaders, and next review dates."),
    ("run_due_experiment_reviews", "Run only creative experiment checkpoints that are due, using real ad-level Meta evidence when available. Never mutates Meta or skips approval guardrails."),
    ("save_optimization_research", "Save one current official, research, expert, forum, or Reddit finding as an expiring test hypothesis. Research can never trigger spend changes."),
    ("list_optimization_research", "List active curated optimization findings, credibility, counterevidence, expiry, and test hypotheses."),
    ("review_signal_quality", "Review Pixel/Dataset, CAPI, Event Match Quality, AEM/event eligibility, event prioritization, correct optimization event, and conversion volume before launching or scaling."),
    ("set_campaign_metric_priorities", "Choose and persist up to six dashboard KPIs for one real Meta campaign. Use after live sync whenever a campaign is new, its objective/event changes, or business context makes the automatic sales/leads/messages/traffic/video/awareness profile incomplete. This changes only dashboard presentation, never spend or Meta delivery."),
    ("preflight_campaign", "Run a read-only expert preflight before campaign staging: account status, policy/rate-limit checks, audiences, existing creatives, placement/device insight availability, signal quality, budget sanity, and dry-run payload preview."),
    ("fetch_public_asset", "Safely inspect or download a buyer-shared public URL, including public Google Drive files, so videos/images/web pages can be used as creative inputs without exposing local networks."),
    ("codex_image_generate", "Generate standalone assets, organic social posts, or approved Meta Ads raster images through Codex/Image. Always send a self-contained request with the exact active topic/offer, content pillar or objective, desired on-image message, format, CTA decision, and latest approved reference when relevant; never send only 'use saved guides'. For organic posts set purpose=daily_social_post or organic_social_post so the backend does not turn educational/trust/community content into a paid ad. Budget is optional for draft/asset-only creatives; require a full ad brief only when the image is launch-ready or campaign-test-ready. Pass buyer-owned real photos in protected_reference_image_paths or content_asset_ids: the backend attaches them with a pixel-by-pixel lock that permits crop/scale/place/frame/overlays but forbids regeneration, retouching, relighting, recoloring, beautification, or changed photo content. Inspiration-only references stay ordinary reference_image_paths. Saved official logos are attached as protected references with an exact-reproduction prompt; exact_composite remains available as fallback."),
    ("codex_creative_plan", "Create a Codex concept or prompt plan from brand, product, reference, or current buyer context. Budget is optional for standalone creative exploration and only informs how many variants to test or launch."),
    ("list_lead_forms", "List existing native Meta Lead Ads / Instant Forms for the connected Facebook Page before creating a duplicate. Use when the buyer wants lead form campaigns or asks what forms already exist."),
    ("stage_lead_form", "Assist the buyer in creating a native Meta Lead Ads / Instant Form from chat. Ask for name, questions/fields, privacy policy URL, optional thank-you/follow-up URL, and stage it for approval; approval creates the form and returns lead_gen_form_id for later campaign staging."),
    ("stage_campaign", "Create or stage a full Meta campaign stack. If the buyer requested a fully PAUSED/no-spend campaign and required details are present, the backend may create the campaign/ad set/ad objects in Meta immediately without a second approval; activation/spend remains approval-protected. Include up to three prioritized success_metrics/key_results/KPIs such as ROAS, cost per purchase, and cost per initiate checkout when known. For image ads, pass use_direct_publishing=true when the buyer/setup should use Publicación directa; if connected, the backend will create an unpublished Page post during paused execution or approval execution and then create the ad from its object_story_id. For video website ads that should be finished in Ads Manager, pass manual_creative_completion=true to create campaign/ad set only, or create_placeholder_ad=true with placeholder_ad_count and placeholder_ad_names to create paused static-placeholder ads that the buyer replaces with video. Never claim Meta supports empty ads without creatives."),
    ("stage_budget_change", "Stage or execute a guarded budget change."),
    ("pause_campaign", "Stage or execute a guarded campaign pause."),
    ("resume_campaign", "Stage or execute a guarded campaign resume."),
    ("schedule_campaign_activation", "Schedule one exact PAUSED Meta campaign to become ACTIVE at an authorized local date/time. Requires the real numeric Meta campaign_id, buyer authorization to spend, confirmation that final creatives are ready, timezone, and scheduled_at. The due action runs deterministically without an inference/model call."),
    ("delete_campaign", "Stage deletion/archival of an exact Meta campaign ID. Use for buyer-approved cleanup of incomplete paused campaigns; never delete active or external campaigns silently."),
    ("list_pending_approvals", "List pending approval cards."),
    ("approve_action", "Approve one exact pending action."),
    ("reject_action", "Reject one exact pending action."),
    ("save_agent_preferences", "Save global operator preferences, including simple/technical wording and the buyer's ads-management experience level."),
    ("save_daily_social_content_settings", "Save the buyer's one-time organic-content decision and, only when branding plus a concrete content strategy are ready, enable or update the recurring Image 2 content cron in the buyer timezone. An early yes is saved as accepted_pending_setup instead of starting an unprepared cron."),
    ("stage_organic_social_post", "Create an exact approval draft for one finished organic Facebook post. Requires the final generated image, exact caption, connected Page, and Publicación directa. This never publishes immediately; explicit buyer approval publishes that exact image and caption as a visible Page post."),
    ("save_content_asset", "Durably save and classify a buyer-shared file, image batch, video link, frame set, or reference for future posts, ads, and strategy. Use preservation_mode=pixel_locked for buyer-owned real photos/logos, style_only for inspiration, pending_classification while unclear, and prohibited for do-not-use assets. Telegram images are pre-archived pending review; classify every file before claiming the batch is organized."),
    ("record_verified_signal", "Save a local verified-signal ledger event or batch: fake/not interested/wrong audience, qualified, booked, showed, purchased, or high-value outcomes. Does not send to Meta."),
    ("get_verified_signal_summary", "Read the local verified-signal ledger summary: stages, open follow-ups, match/privacy readiness, and recent records."),
    ("verified_signal_feedback_prompt", "Generate the daily exception/outcome feedback prompt for verified-signal mode."),
    ("save_business_memory", "Save durable business context."),
    ("save_durable_memory", "Save one confirmed durable decision, preference, fact, blocker, next step, or workflow agreement that does not fit a more specific product memory tool. Never use it for secrets."),
    ("save_ads_onboarding", "Save durable ads/campaign onboarding context, including up to three prioritized success metrics/results such as ROAS, cost per purchase, and cost per initiate checkout."),
    ("save_brand_memory", "Save the general brand guide. Accepts natural aliases such as name, business_name, brand_colors, style, logo_decision, reference_decision, and real_assets. Use this instead of writing brand_guides files manually."),
    ("save_product_memory", "Save a product or offer guide. Accepts natural aliases such as product_name, target_audience, problem, benefit, and main_offer. Use this instead of writing brand_guides files manually."),
    ("import_product_catalog", "Import or update up to 50 products from a buyer-shared PDF, Excel, CSV, TSV, JSON, or a structured products array. Preserve every useful column as product detail, keep each product/offer in its own natural-language guide, and create bundles/combinations as separate child offers with component_products/components instead of overwriting their source products. If a PDF returns needs_agent_structuring=true, read its extracted text and call this tool again with a structured products array before telling the buyer the catalog is ready."),
    ("search_product_catalog", "Search the durable product catalog by product name, SKU, category, tag, benefit, audience, component, or other saved detail. Always use this before answering from memory when a business has multiple products, and use the returned exact product guide for content, creatives, offers, bundles, campaigns, or reporting."),
    ("save_ad_brief", "Save a campaign/ad creative brief. Accepts natural aliases such as brief_name, product_name, budget, variants, creative_formats, and hypothesis. Use this instead of writing brand_guides files manually."),
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


def heavy_tool_timeout_seconds():
    raw = os.environ.get("ADMIRA_HEAVY_TOOL_TIMEOUT_SECONDS", "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_HEAVY_TOOL_TIMEOUT_SECONDS
    return max(60, min(1800, value))


def is_heavy_tool(name):
    normalized = str(name or "").strip()
    if normalized.startswith("mcp_admira_"):
        normalized = normalized.removeprefix("mcp_")
    if normalized.startswith("admira_"):
        without_prefix = normalized.removeprefix("admira_")
        return normalized in HEAVY_TOOL_NAMES or without_prefix in HEAVY_TOOL_NAMES
    return normalized in HEAVY_TOOL_NAMES


def timeout_tool_result(name, seconds):
    normalized = str(name or "").strip()
    if normalized.startswith("mcp_admira_"):
        normalized = "admira_" + normalized.removeprefix("mcp_admira_")
    elif not normalized.startswith("admira_"):
        normalized = f"admira_{normalized}"
    message = (
        "La generación o planificación creativa tardó demasiado y la detuve para que el agente no se quede congelado. "
        "Puedes reintentar con una sola variación, una instrucción más corta o volver a pedirme que retome el creativo. "
        "Si tu cuenta de ChatGPT/Codex muestra el límite semanal de imágenes en 0, espera a que se reinicie ese límite "
        "o conecta una cuenta con capacidad disponible; a veces el proveedor no devuelve ese aviso y solo queda como timeout. "
        "Si estás usando DigitalOcean, usa mínimo 2GB de RAM para trabajar con creativos."
    )
    return {
        "ok": False,
        "tool": normalized,
        "blocked": True,
        "reason": "admira_tool_timeout",
        "error_type": "timeout",
        "timeout_seconds": seconds,
        "reply": message,
        "result": {
            "ok": False,
            "blocked": True,
            "error_type": "timeout",
            "reason": "admira_tool_timeout",
            "error": message,
            "reply": message,
            "retryable": True,
        },
    }


def invalid_subprocess_result(name, stderr=""):
    normalized = str(name or "").strip()
    if not normalized.startswith("admira_") and not normalized.startswith("mcp_admira_"):
        normalized = f"admira_{normalized}"
    message = "No pude leer la respuesta interna de la herramienta creativa. Intenta de nuevo con una solicitud más corta."
    return {
        "ok": False,
        "tool": normalized,
        "blocked": True,
        "reason": "admira_tool_invalid_response",
        "error": message,
        "reply": message,
        "stderr": str(stderr or "")[-1000:],
    }


def call_tool_in_subprocess(name, arguments, timeout_seconds):
    command = [
        sys.executable,
        str(BRIDGE_PATH),
        "call",
        str(name),
        "--json",
        json.dumps(arguments or {}, ensure_ascii=False),
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=5)
        except Exception:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except Exception:
                pass
        return timeout_tool_result(name, timeout_seconds)
    last_json = ""
    for line in reversed((stdout or "").splitlines()):
        if line.strip().startswith("{"):
            last_json = line.strip()
            break
    if not last_json:
        return invalid_subprocess_result(name, stderr)
    try:
        result = json.loads(last_json)
    except json.JSONDecodeError:
        return invalid_subprocess_result(name, stderr)
    if isinstance(result, dict):
        return result
    return invalid_subprocess_result(name, stderr)


def call_tool_guarded(name, arguments):
    # Keep monkeypatched unit tests simple and direct.
    if call_tool is not ORIGINAL_CALL_TOOL:
        return call_tool(name, arguments)
    if is_heavy_tool(name):
        return call_tool_in_subprocess(name, arguments, heavy_tool_timeout_seconds())
    return call_tool(name, arguments)


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
        async def _tool(**kwargs):
            import asyncio

            result = await asyncio.to_thread(call_tool_guarded, f"admira_{tool_name}", kwargs or {})
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
            result = call_tool_guarded(f"admira_{name}", arguments)
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
