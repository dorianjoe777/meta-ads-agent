#!/usr/bin/env python3
"""MCP server that exposes Admira IA product tools to Hermes."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import traceback

from admira_tool_bridge import call_tool
from campaign_payload_compiler import destination_brief_schema
from mcp_skill_registry import MCP_PRIMARY_SKILL, tool_description_with_skill

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised in lightweight test envs
    FastMCP = None


SERVER_NAME = "admira"
PROTOCOL_VERSION = "2024-11-05"
ORIGINAL_CALL_TOOL = call_tool
BRIDGE_PATH = Path(__file__).resolve().parent / "admira_tool_bridge.py"
HEAVY_TOOL_NAMES = {"codex_image_generate", "codex_creative_plan", "generate_motion_graphic_video", "admira_codex_image_generate", "admira_codex_creative_plan", "admira_generate_motion_graphic_video"}
DEFAULT_HEAVY_TOOL_TIMEOUT_SECONDS = 300
_STDIO_FRAMING = "content-length"
_WRITE_LOCK = threading.Lock()


TOOL_DEFINITIONS = [
    ("get_real_meta_context", "Synchronize directly with Meta and read the current campaign/ad set/ad inventory plus performance context. Supports date_preset=maximum|today|last_7d|custom, custom since/until dates, and detail_level=standard|deep; deep includes placement/device, age/gender and country breakdowns. Read-only transient Graph failures are retried once. Inspect live_sync.connection and live_sync.error_details: if connection.reachable=true, do not claim Meta is disconnected or the token expired. Preserve code, subcode and fbtrace_id for support. Treat local memory and approvals only as candidate workflow context: they never prove what currently exists or runs in Meta, and a failed/incomplete empty response never proves the account has no campaigns."),
    ("start_meta_oauth_connection", "Send the buyer a short-lived secure Facebook OAuth URL as ordinary visible text in their connected Telegram chat. Use as the first technical setup step when get_meta_oauth_workspaces says Facebook is not connected. Never depend on an inline button. Do not ask for a Meta token, System User, or app. This is setup only and never spends money."),
    ("get_meta_oauth_workspaces", "List the buyer's Facebook OAuth connection plus every publishable Page and ad account it discovered. Tokens are never returned. Present Pages first and ad accounts second as ordinary numbered chat text, never through clarify or a choice card. Ask for exactly two bare numbers: Page first, ad account second (example: 1, 8)."),
    ("select_meta_oauth_workspace", "Persist the exact Page/ad-account pair authorized by the buyer's latest strict numeric reply. The only accepted buyer format is two bare numbers in the displayed order: Page first, ad account second. Names, confirmations, partial choices, recommendations, budgets, or model-supplied IDs do not authorize selection. Success includes selected=true and verified_persisted=true after durable backend read-back."),
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
    ("codex_image_generate", "Generate logo candidates, brand explorations, moodboards, brand samples, standalone assets, organic social posts, approved Meta Ads raster images, or storyboard media through Codex/Image only when the buyer semantically asks to create or revise image media. During branding, use purpose=logo, brand_exploration, moodboard, or brand_sample and show the actual result for natural approval before saving it as official. Organic and paid production require durable buyer-confirmed branding. A campaign goal, budget, destination, unanswered creative-choice question, statement that no creative exists, or the model's own offer to generate one is not a generation request. For a paid campaign, first present and obtain natural correction/approval of the commercial angle, exact primary text, distinct title, CTA/destination message, and visual concept; pass the exact active child offer in product_guide or ad_brief. Always send a self-contained request with the exact active topic/offer, desired composition, format, CTA decision, and reference when relevant. Pass buyer-owned real photos in protected_reference_image_paths or content_asset_ids; saved official logos remain protected exact references."),
    ("list_recent_creatives", "List generated image creatives from the buyer's short three-day recovery window by natural date such as today or yesterday. Use this when the buyer says 'the ones you created yesterday/Monday'; return choices by preview/date and never ask them to remember an asset ID. Expired unreferenced files are pruned automatically."),
    ("codex_creative_plan", "Create a Codex concept or prompt plan from brand, product, reference, or current buyer context. Budget is optional for standalone creative exploration and only informs how many variants to test or launch."),
    ("search_motion_graphic_recipes", "Search Admira's complete vendored Video Shotcraft catalog before storyboarding. Use narrative constraints such as role, message type, tone, energy, tempo, impact, and category; it returns exact existing card/style names plus trusted Markdown and TSX provenance. Use it to choose motion by communication purpose instead of visual novelty, then read only the selected card/demo references."),
    ("generate_motion_graphic_video", "Create and render a finished brand-aware motion-graphics MP4 locally with Remotion. Use for educational, explainer, promotional, tutorial, social-proof, announcement, or awareness videos in any niche. Resolve the exact active child product/service/offer before calling. Send either a clear topic plus key_points for an automatic storyboard, or explicit scenes using hook, statement, list, steps, stat, comparison, quote, media, and cta. The complete vendored Video Shotcraft library is available: 152 cards and 209 styles. Each scene may compose compatible exact card/style names through shot_recipes and may use one main media_path plus up to six generated/approved layer_asset_paths; compiled recipes address those layers through ProtectedMedia assetIndex. When this video uses or promises Image 2 visuals, set require_visual_assets=true and explicitly bind every intended generated asset to a scene; the renderer rejects an empty/generic storyboard under that contract. Parameterized recipes render directly; any other catalog recipe requires a bounded compiled_recipe_source adapted from its exact trusted card and TSX demo. The backend validates and isolates that source inside the one render job. The local renderer inherits parent-brand identity, applies child-offer overrides, preserves PNG transparency, and preserves buyer-owned media byte-for-byte. Rendering does not publish or spend and does not require approval."),
    ("list_lead_forms", "List existing native Meta Lead Ads / Instant Forms for the connected Facebook Page before creating a duplicate. Use when the buyer wants lead form campaigns or asks what forms already exist."),
    ("stage_lead_form", "Manual fallback for a native Meta Lead Ads / Instant Form. Use only after create_lead_form returns a real Meta permission or capability blocker. It saves the approved blueprint and returns exact Ads Manager steps; after the buyer publishes it, list forms again and verify the real lead_gen_form_id."),
    ("create_lead_form", "Create a native Meta Lead Ads / Instant Form directly through the connected Facebook Page, then read it back and return the verified lead_gen_form_id. First list forms to avoid duplicates. Collect the name, approved questions, and privacy-policy URL; use the active selected Page automatically unless an exact page_id is supplied. This creates no campaign and spends no money. Never call it with {} or partial arguments; ask one concise combined question only for genuinely missing values. Use stage_lead_form only if Meta returns a real permission/capability blocker."),
    ("create_whatsapp_campaign", "Create a complete click-to-WhatsApp Meta campaign in PAUSED/no-spend state once the buyer has explicitly resolved the current budget, exact creative, primary text, title, and WhatsApp opener. A campaign request alone does not approve model-invented values. This contract always uses the native WHATSAPP destination; never substitute wa.me website traffic. Supply the approved prefilled_message and creative. The backend resolves the live WhatsApp/Page identifiers. Success is returned only after Meta provides real campaign, ad-set, and ad IDs. Activation/spend remains separately approval-protected."),
    ("create_lead_form_campaign", "Create a complete native Meta Instant Form campaign in PAUSED/no-spend state once the buyer has explicitly resolved the current budget, exact creative, primary text, and title. A campaign request alone does not approve model-invented values. Supply a verified lead_gen_form_id returned by list_lead_forms/create_lead_form; no website URL is accepted or required. Success is returned only after Meta provides real campaign, ad-set, and ad IDs. Activation/spend remains separately approval-protected."),
    ("create_website_campaign", "Create a complete website-destination Meta campaign in PAUSED/no-spend state once the buyer has explicitly resolved the current budget, exact creative, primary text, and title. A campaign request alone does not approve model-invented values. A real final landing_url is mandatory. Do not use this contract for native WhatsApp, Messenger, Instagram Direct, lead-form, app, or on-Meta destinations. Success is returned only after Meta provides real campaign, ad-set, and ad IDs. Activation/spend remains separately approval-protected."),
    ("create_messaging_campaign", "Create a complete native Messenger or Instagram Direct campaign in PAUSED/no-spend state once the buyer has explicitly resolved the current budget, exact creative, primary text, title, and welcome opener. A campaign request alone does not approve model-invented values. message_destination must be MESSENGER or INSTAGRAM_DIRECT and welcome_message must contain the approved conversation opener. Success is returned only after Meta provides real campaign, ad-set, and ad IDs. Activation/spend remains separately approval-protected."),
    ("create_app_campaign", "Create a complete app-promotion Meta campaign in PAUSED/no-spend state once the buyer has explicitly resolved the current budget, exact creative, primary text, and title. A campaign request alone does not approve model-invented values. application_id and the exact App Store or Google Play object_store_url are mandatory. Success is returned only after Meta provides real campaign, ad-set, and ad IDs. Activation/spend remains separately approval-protected."),
    ("create_on_meta_campaign", "Create a complete awareness, video-view, engagement, or existing-Page-post campaign whose destination stays inside Meta, in PAUSED/no-spend state once the buyer has explicitly resolved the current budget, exact creative, primary text, and title. A campaign request alone does not approve model-invented values. Do not use it for websites, messaging, lead forms, or apps. Success is returned only after Meta provides real campaign, ad-set, and ad IDs. Activation/spend remains separately approval-protected."),
    ("edit_campaign", "Prepare an edit for one existing Meta campaign from ordinary buyer language. Resolve the campaign reference against the current live inventory before doing anything. Every call is campaign-scoped: a newly mentioned different campaign starts a separate draft even without words like 'another' or 'now'; pronouns such as 'esa', 'la misma' or 'también' continue the previous scope. Preserve unspecified fields, stage the exact diff for approval, and never claim success until Meta is updated and read back."),
    ("connect_chatgpt", "Start or switch the ChatGPT/Codex subscription and return the secure OpenAI device URL and code in chat. Never give terminal commands."),
    ("stage_budget_change", "Stage a guarded budget change using the exact buyer-facing amount and currency. The backend verifies the live ad-account currency, uses the same currency-unit engine as campaign creation, and rereads Meta after approval before reporting success."),
    ("pause_campaign", "Stage or execute a guarded campaign pause."),
    ("resume_campaign", "Stage or execute a guarded campaign resume."),
    ("schedule_campaign_activation", "Schedule one exact PAUSED Meta campaign to become ACTIVE at an authorized local date/time. Requires the real numeric Meta campaign_id, buyer authorization to spend, confirmation that final creatives are ready, timezone, and scheduled_at. The due action runs deterministically without an inference/model call."),
    ("delete_campaign", "Stage deletion/archival of an exact Meta campaign ID. Use for buyer-approved cleanup of incomplete paused campaigns; never delete active or external campaigns silently."),
    ("list_pending_approvals", "List pending approval cards."),
    ("approve_action", "Approve one exact pending action."),
    ("reject_action", "Reject one exact pending action."),
    ("save_agent_preferences", "Save global operator preferences, including simple/technical wording and the buyer's ads-management experience level."),
    ("save_daily_social_content_settings", "Save the buyer's one-time organic-content decision and, only when branding plus a concrete content strategy are ready, enable or update the recurring organic content cron in the buyer timezone. The strategy may allow images, motion videos, or an adaptive mix. An early yes is saved as accepted_pending_setup instead of starting an unprepared cron."),
    ("stage_organic_social_post", "Create an exact approval draft for one finished organic Facebook piece. Requires one final generated image or motion video, exact caption, connected Page, and Publicación directa. This never publishes immediately; explicit buyer approval publishes that exact media and caption as a visible Page post/video."),
    ("save_content_asset", "Durably save and classify a buyer-shared file, image batch, video link, frame set, or reference for future posts, ads, and strategy. Use preservation_mode=pixel_locked for buyer-owned real photos/logos, style_only for inspiration, pending_classification while unclear, and prohibited for do-not-use assets. Telegram images are pre-archived pending review; classify every file before claiming the batch is organized."),
    ("record_verified_signal", "Save a local verified-signal ledger event or batch: fake/not interested/wrong audience, qualified, booked, showed, purchased, or high-value outcomes. Does not send to Meta."),
    ("get_verified_signal_summary", "Read the local verified-signal ledger summary: stages, open follow-ups, match/privacy readiness, and recent records."),
    ("verified_signal_feedback_prompt", "Generate the daily exception/outcome feedback prompt for verified-signal mode."),
    ("save_business_memory", "Save Page-scoped strategic business context. Copy the complete current buyer message exactly into buyer_evidence; never paraphrase it. Every value must declare whether it came from the buyer, is an agent proposal, or is inferred. The backend—not the model—computes readiness across services, ideal customer, differentiators, markets, capacity, pricing, margins, global objectives, advertising experience, and branding. When the tool reports review_required, show its canonical review_summary completely; only a later natural buyer confirmation can confirm that actually delivered revision."),
    ("save_durable_memory", "Save one confirmed durable decision, preference, fact, blocker, next step, or workflow agreement that does not fit a more specific product memory tool. Never use it for secrets."),
    ("save_ads_onboarding", "Save durable ads/campaign onboarding context, including up to three prioritized success metrics/results. Copy the buyer's complete current message exactly into buyer_evidence. A short confirmation can promote only the matching draft already shown."),
    ("save_brand_memory", "Save the general brand guide. Copy the buyer's complete current message exactly into buyer_evidence. A short confirmation can promote the matching draft already shown or idempotently acknowledge the exact official brand already saved. One successful save also resolves the Page-scoped strategic branding topic, so never request a second confirmation through business memory. Accepts natural aliases such as name, business_name, brand_colors, style, logo_decision, reference_decision, and real_assets."),
    ("save_product_memory", "Save a product or offer guide. Copy the buyer's complete current message exactly into buyer_evidence. A short confirmation can promote only the matching draft already shown. Accepts natural aliases such as product_name, target_audience, problem, benefit, and main_offer."),
    ("import_product_catalog", "Import or update up to 50 products from a buyer-shared PDF, Excel, CSV, TSV, JSON, or a structured products array. Preserve every useful column as product detail, keep each product/offer in its own natural-language guide, and create bundles/combinations as separate child offers with component_products/components instead of overwriting their source products. If a PDF returns needs_agent_structuring=true, read its extracted text and call this tool again with a structured products array before telling the buyer the catalog is ready."),
    ("search_product_catalog", "Search the durable product catalog by product name, SKU, category, tag, benefit, audience, component, or other saved detail. Always use this before answering from memory when a business has multiple products, and use the returned exact product guide for content, creatives, offers, bundles, campaigns, or reporting."),
    ("save_ad_brief", "Save one campaign/ad creative brief and its commercial plan. Accepts natural aliases such as brief_name, product_name, budget, currency, variants, creative_formats, hypothesis, success_metrics, business_outcome, time_horizon, ideal_customer, funnel_follow_up, economics, projection, measurement_plan, primary_text, headline, and destination_message. The KPIs/projection are planning targets and assumptions, never observed Meta performance. Use a unique brief name for each new campaign and reuse its returned ID only for edits to that same campaign. Use this instead of writing brand_guides files manually; save the active offer separately with save_product_memory and use save_ads_onboarding only for account-wide ads history/defaults."),
    ("save_creative_references", "Save approved creative references."),
]

_defined_tool_names = {name for name, _description in TOOL_DEFINITIONS}
if _defined_tool_names != set(MCP_PRIMARY_SKILL):
    missing = sorted(_defined_tool_names - set(MCP_PRIMARY_SKILL))
    stale = sorted(set(MCP_PRIMARY_SKILL) - _defined_tool_names)
    raise RuntimeError(f"MCP skill registry mismatch: missing={missing}, stale={stale}")
TOOL_DEFINITIONS = [
    (name, tool_description_with_skill(name, description))
    for name, description in TOOL_DEFINITIONS
]


def _string(description, *, enum=None):
    schema = {"type": "string", "description": description}
    if enum:
        schema["enum"] = list(enum)
    return schema


def _boolean(description):
    return {"type": "boolean", "description": description}


def _number(description):
    return {"type": "number", "description": description}


def _strings(description):
    return {"type": "array", "description": description, "items": {"type": "string"}}


# Hermes relies on the MCP input schema when deciding which arguments belong in
# a tool call.  An empty `properties` object made long/compacted sessions much
# more likely to emit `{}` even when the buyer had supplied every detail.  Keep
# aliases open for backwards compatibility, but make the canonical contract
# explicit for the high-value memory, creative, and campaign tools.
TOOL_INPUT_SCHEMAS = {
    "start_meta_oauth_connection": {"type": "object", "additionalProperties": False, "properties": {}},
    "get_meta_oauth_workspaces": {"type": "object", "additionalProperties": False, "properties": {}},
    "select_meta_oauth_workspace": {
        "type": "object", "additionalProperties": False,
        "properties": {"ad_account_id": _string("One ad account ID returned by get_meta_oauth_workspaces."), "page_id": _string("One Facebook Page ID returned by get_meta_oauth_workspaces.")},
        "required": ["ad_account_id", "page_id"],
    },
    "get_real_meta_context": {
        "type": "object", "additionalProperties": True,
        "properties": {
            "date_preset": _string("maximum, today, last_7d, or custom.", enum=("maximum", "today", "last_7d", "custom")),
            "since": _string("YYYY-MM-DD start date when date_preset=custom."),
            "until": _string("YYYY-MM-DD end date when date_preset=custom."),
            "detail_level": _string("standard or deep live inventory/insight detail.", enum=("standard", "deep")),
        },
    },
    "search_meta_targeting": {
        "type": "object", "additionalProperties": True,
        "properties": {"kind": _string("interest or location.", enum=("interest", "location")), "q": _string("Human search term to resolve against Meta's current catalog.")},
        "required": ["kind", "q"],
    },
    "inspect_adset_targeting": {
        "type": "object", "additionalProperties": True,
        "properties": {"adset_id": _string("Exact numeric Meta ad-set ID."), "requested_interest_ids": _strings("Expected live Meta interest IDs."), "advantage_audience": _boolean("Expected Advantage+ audience flag.")},
        "required": ["adset_id"],
    },
    "review_signal_quality": {
        "type": "object", "additionalProperties": True,
        "properties": {"objective": _string("Campaign objective."), "pixel_id": _string("Exact Pixel/Dataset ID."), "optimization_event": _string("Economic outcome or primary result event.")},
    },
    "schedule_experiment_review": {
        "type": "object", "additionalProperties": True,
        "properties": {"campaign_id": _string("Exact real Meta campaign ID."), "test_budget": _number("Authorized test budget in account currency."), "target_cost": _number("Target CPA or CPL."), "variants": {"type": "array", "description": "At least two variants with real Meta ad/creative IDs.", "items": {"type": "object", "additionalProperties": True}}, "timezone": _string("Buyer timezone.")},
        "required": ["campaign_id", "test_budget", "target_cost", "variants"],
    },
    "save_optimization_research": {
        "type": "object", "additionalProperties": True,
        "properties": {"title": _string("Concise finding title."), "source_url": _string("Official/research/expert/forum source URL."), "source_type": _string("official, research, expert, forum, or reddit."), "finding": _string("What the source suggests."), "credibility": _string("Credibility and limitations."), "counterevidence": _string("Contrary evidence or caveats."), "test_hypothesis": _string("Safe evidence-gathering experiment, never an automatic spend change."), "expires_at": _string("Expiry/review date.")},
        "required": ["title", "source_url", "finding", "test_hypothesis"],
    },
    "set_campaign_metric_priorities": {
        "type": "object", "additionalProperties": True,
        "properties": {"campaign_id": _string("Exact real Meta campaign ID."), "metrics": _strings("Up to six prioritized dashboard KPIs."), "reason": _string("Why these KPIs best explain this campaign.")},
        "required": ["campaign_id", "metrics"],
    },
    "preflight_campaign": {
        "type": "object", "additionalProperties": True,
        "properties": {"name": _string("Proposed campaign name."), "objective": _string("Campaign objective."), "daily_budget": _number("Budget in the connected account currency."), "pixel_id": _string("Pixel/Dataset ID when applicable."), "optimization_event": _string("Primary event/result."), "countries": _strings("Exact country codes.")},
    },
    "fetch_public_asset": {
        "type": "object", "additionalProperties": True,
        "properties": {"url": _string("Buyer-shared public URL to inspect or download."), "purpose": _string("How the asset will be used.")},
        "required": ["url"],
    },
    "save_content_asset": {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "file_path": _string("One exact local path supplied by the product for the buyer-shared asset."),
            "file_paths": _strings("All exact local paths in the buyer-shared batch that share this classification."),
            "url": _string("Public asset URL when the source is a link instead of an uploaded file."),
            "urls": _strings("Public asset URLs that share this classification."),
            "category": _string(
                "Confirmed asset category. Use other only while genuinely pending review.",
                enum=("official_logo", "product", "location", "team_founder", "customer_testimonial", "ugc", "offer_promo", "social_proof", "brand_graphic_element", "motion_graphic_element", "story_element", "decorative_element", "style_reference", "do_not_use", "other"),
            ),
            "purpose": _string("What the buyer said this asset is for and how it may be used."),
            "notes": _string("Useful visual/context notes for future content and campaign work."),
            "preservation_mode": _string(
                "pixel_locked for buyer-owned real photos/logos; style_only for inspiration; pending_classification if unclear; prohibited when it must not be used.",
                enum=("pixel_locked", "style_only", "pending_classification", "prohibited"),
            ),
            "approved_for_ads": _boolean("Whether the buyer approved this exact asset for paid ads."),
            "approved_for_daily_content": _boolean("Whether this asset may be reused in recurring organic content."),
            "product_scope": _string("Exact product/service/offer this reusable element belongs to; blank means parent brand."),
            "visual_role": _string("How it should be composed, such as background, foreground cutout, badge, texture, divider, icon, or transition element."),
            "reusable": _boolean("Whether this classified element should be considered for future videos/content."),
        },
        "anyOf": [
            {"required": ["file_path"]},
            {"required": ["file_paths"]},
            {"required": ["url"]},
            {"required": ["urls"]},
        ],
    },
    "record_verified_signal": {
        "type": "object", "additionalProperties": True,
        "properties": {"stage": _string("Verified outcome: fake, not_interested, wrong_audience, qualified, booked, showed, purchased, or high_value."), "person_label": _string("Non-sensitive local label for the contact."), "campaign_id": _string("Related real campaign ID when known."), "ad_id": _string("Related real ad ID when known."), "value": _number("Purchase/high-value amount when applicable."), "currency": _string("ISO currency code."), "notes": _string("Verified business context."), "items": {"type": "array", "items": {"type": "object", "additionalProperties": True}}},
        "anyOf": [{"required": ["stage"]}, {"required": ["items"]}],
    },
    "save_brand_memory": {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "confirmation_state": _string("buyer_confirmed for facts stated/approved in this current buyer turn; agent_proposal or inferred are retained only as drafts.", enum=("buyer_confirmed", "agent_proposal", "inferred")),
            "buyer_evidence": _string("Copy the buyer's complete current message exactly, including their natural wording and typos. Never paraphrase it. The backend binds it to a one-use transport turn."),
            "brand_name": _string("Exact brand or business name confirmed by the buyer."),
            "offer": _string("Short description of what the brand sells or provides."),
            "colors": _string("Confirmed brand palette, including color names or codes when known."),
            "visual_style": _string("Confirmed visual direction, references, typography, and composition preferences."),
            "tone": _string("Brand voice and communication tone."),
            "logo_path": _string("Exact local path supplied by the product for the official logo."),
            "logo_notes": _string("Whether the official logo exists and rules for reproducing it exactly."),
            "references": _string("Approved style/reference guidance."),
            "asset_notes": _string("Known real photos, products, locations, people, and usage decisions."),
            "what_to_avoid": _string("Visual or verbal elements the brand must avoid."),
        },
        "required": ["confirmation_state", "buyer_evidence"],
        "anyOf": [{"required": ["brand_name"]}, {"required": ["offer"]}],
    },
    "save_product_memory": {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "confirmation_state": _string("buyer_confirmed for facts stated/approved in this current buyer turn; agent_proposal or inferred are retained only as drafts.", enum=("buyer_confirmed", "agent_proposal", "inferred")),
            "buyer_evidence": _string("Copy the buyer's complete current message exactly; do not correct or paraphrase it."),
            "name": _string("Exact product, service, offer, or bundle name."),
            "target_audience": _string("Who this specific offer is for."),
            "problem": _string("Problem or desire this offer addresses."),
            "benefit": _string("Primary outcome or benefit."),
            "main_offer": _string("Price, package, inclusion, promise, or commercial offer."),
            "details": _string("Other confirmed details that distinguish this offer from the brand's other offers."),
            "visual_colors": _string("Offer-specific palette overrides compatible with the parent brand."),
            "visual_typography": _string("Offer-specific typography direction."),
            "visual_style": _string("Offer-specific visual system."),
            "motion_style": _string("Confirmed motion language for this offer."),
            "motion_pacing": _string("Confirmed motion pace and energy for this offer."),
            "motion_show": _string("Elements motion videos for this offer should always show."),
            "motion_avoid": _string("Motion/video elements this offer must avoid."),
        },
        "required": ["name", "confirmation_state", "buyer_evidence"],
    },
    "save_ads_onboarding": {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "confirmation_state": _string("buyer_confirmed for account-wide facts stated/approved in this current buyer turn; agent_proposal or inferred are retained only as drafts.", enum=("buyer_confirmed", "agent_proposal", "inferred")),
            "buyer_evidence": _string("Copy the buyer's complete current message exactly; do not correct or paraphrase it."),
            "campaign_goal": _string("The business result the buyer wants from ads."),
            "objective": _string("Recommended or confirmed Meta campaign objective."),
            "success_metrics": _strings("Up to three prioritized business KPIs, ordered most important first."),
            "budget": _number("Confirmed daily or test budget in the ad account currency."),
            "budget_level": _string("Where budget is controlled.", enum=("campaign", "adset")),
            "countries": _strings("Exact ISO country codes confirmed or recommended for this campaign."),
            "optimization_event": _string("Economic outcome or campaign result Meta should optimize for."),
            "notes": _string("Other confirmed campaign decisions and constraints."),
        },
        "required": ["confirmation_state", "buyer_evidence"],
        "anyOf": [{"required": ["campaign_goal"]}, {"required": ["objective"]}, {"required": ["success_metrics"]}],
    },
    "codex_image_generate": {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "request": _string("Self-contained image request with exact active offer/topic, visual concept, desired message, format, and CTA decision."),
            "purpose": _string("Use logo for a logo candidate; brand_exploration, moodboard, or brand_sample while defining branding; ad_creative for paid ads; daily_social_post or organic_social_post for organic content; and standalone_asset for other images.", enum=("logo", "brand_exploration", "moodboard", "brand_sample", "ad_creative", "daily_social_post", "organic_social_post", "standalone_asset", "motion_graphic_asset")),
            "active_topic": _string("Exact current topic or offer; do not rely only on general brand memory."),
            "product_guide": _string("Exact saved child product/service/offer guide for this image. Required when several offers exist."),
            "ad_brief": _string("Exact saved campaign/ad brief containing the approved commercial direction and creative hypothesis."),
            "content_pillar": _string("Organic content pillar when applicable."),
            "objective": _string("What this image should make the audience understand or do."),
            "desired_on_image_message": _string("Exact or near-exact text intended to appear inside the image."),
            "format": _string("Requested output format/aspect ratio, for example 1:1 1080x1080 or 4:5 1080x1350."),
            "cta_decision": _string("Exact CTA, or explicitly no CTA on image."),
            "reference_image_paths": _strings("Inspiration-only image paths supplied by the product."),
            "protected_reference_image_paths": _strings("Buyer-owned real photo/logo paths that must remain pixel-accurate."),
            "content_asset_ids": _strings("Durable content-library asset IDs selected for this image."),
            "variation_count": {"type": "integer", "minimum": 1, "maximum": 8, "description": "Number of requested variants."},
            "background_removal": _string("none or green_screen. green_screen asks Image 2 for a flat #00FF00 plate and converts it to transparent PNG deterministically.", enum=("none", "green_screen")),
            "asset_role": _string("Intended storyboard role, such as full_frame, background, foreground_cutout, story_subject, story_prop, badge, icon, texture, decorative_shape, or transition_element."),
            "narrative_role": _string("What this exact element communicates or does in the story scene, such as embody the problem, demonstrate the action, represent the customer, reveal the solution, or create a visual metaphor."),
            "scene_intent": _string("Alias for narrative_role when describing the exact scene meaning."),
            "reusable_asset": _boolean("Save the generated result into the durable content library for future brand/product videos."),
            "reusable_category": _string("Durable generated-asset category. One-off story elements normally stay unsaved unless they are genuinely reusable.", enum=("brand_graphic_element", "motion_graphic_element", "story_element", "decorative_element")),
            "product_scope": _string("Exact product/service/offer this element belongs to; blank means reusable parent-brand element."),
            "asset_purpose": _string("Concise future-use description for the durable library."),
            "asset_notes": _string("Composition restrictions, safe zones, color variants, and reuse notes."),
            "brand_name": _string("Exact brand name for logo/brand exploration during onboarding."),
            "business_category": _string("What the business offers; use for logo/brand exploration when the general guide is not complete yet."),
            "colors": _string("Confirmed or buyer-requested palette for logo/brand exploration."),
            "visual_style": _string("Confirmed visual direction for logo/brand exploration."),
            "tone": _string("How the brand should feel and communicate."),
        },
        "required": ["request", "purpose"],
    },
    "codex_creative_plan": {
        "type": "object", "additionalProperties": True,
        "properties": {"request": _string("Self-contained creative planning request for the exact active offer/topic."), "purpose": _string("ad_creative, organic_social_post, or standalone_asset."), "formats": _strings("Requested formats."), "variation_count": {"type": "integer", "minimum": 1, "maximum": 12}, "reference_image_paths": _strings("Approved inspiration paths."), "protected_reference_image_paths": _strings("Real photos/logos that must remain pixel-accurate.")},
        "required": ["request", "purpose"],
    },
    "list_recent_creatives": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "when": _string("Natural recent period.", enum=("today", "yesterday", "last_3_days")),
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
    },
    "generate_motion_graphic_video": {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "purpose": _string(
                "Use ad_motion_graphics for a paid-ad video, organic_social_post or daily_social_post "
                "for organic content, and standalone_asset, moodboard, or brand_exploration for "
                "non-paid visual exploration. The backend uses this purpose to enforce strategic readiness."
            ),
            "topic": _string("Exact subject or promise the video should explain."),
            "objective": _string("Video purpose.", enum=("educational", "explainer", "promotional", "tutorial", "social_proof", "announcement", "awareness")),
            "product_guide": _string("Exact saved child product/service/offer guide. Required when several offers could match."),
            "audience": _string("Exact intended audience for this video."),
            "aspect_ratio": _string("9:16, 4:5, 1:1, or 16:9.", enum=("9:16", "4:5", "1:1", "16:9")),
            "template": _string("Optional coordinated storyboard family. adaptive chooses by scene and branding; ink-press uses the paper/ink 2.5D sequence.", enum=("adaptive", "ink-press", "cinematic-product", "educational-cards", "data-story", "social-vertical")),
            "quality": _string("preview for a faster draft or final for delivery.", enum=("preview", "draft", "final")),
            "key_points": _strings("Important points in the exact order they should be taught."),
            "cta": _string("Final next step or explicitly no CTA."),
            "scenes": {
                "type": "array",
                "minItems": 1,
                "maxItems": 12,
                "description": "Optional exact storyboard. Each scene communicates one idea and includes its own duration.",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {
                        "type": _string("Scene recipe.", enum=("hook", "statement", "list", "steps", "stat", "comparison", "quote", "media", "cta")),
                        "eyebrow": _string("Short scene label."),
                        "title": _string("Main readable scene title."),
                        "body": _string("Supporting copy."),
                        "items": _strings("List or step items, maximum six."),
                        "stat": _string("Hero number or fact."),
                        "left": _string("First side of a comparison."),
                        "right": _string("Second side of a comparison."),
                        "quote": _string("Verified quote only; never invent testimonials."),
                        "attribution": _string("Verified quote attribution."),
                        "media_path": _string("Safe buyer image/video path to show without altering its content."),
                        "layer_asset_paths": _strings("Up to six safe generated or buyer-owned assets to layer independently in this scene. In compiled_recipe_source use ProtectedMedia assetIndex=0..5; transparent PNGs preserve their alpha channel."),
                        "media_fit": _string("cover may crop boundaries; contain preserves the whole frame.", enum=("cover", "contain")),
                        "duration_seconds": _number("Scene duration from 1.5 to 15 seconds."),
                        "motion": _string("Optional curated motion recipe such as editorial-reveal, card-cascade, stat-focus, split-compare, spotlight-media, step-stack, quote-frame, or cta-lockup."),
                        "shot_recipes": _strings("One to four exact Video Shotcraft card names or style keys from the complete 152-card/209-style catalog. Compose one dominant camera/UI/data/opening recipe, optional typography/emphasis, and at most one transition."),
                        "compiled_recipe_source": _string("For catalog recipes outside Admira's parameterized fast path: the bounded per-scene JSX function body adapted from the exact card and demo. Must return JSX and use only the safe bindings documented in motion-graphics-video/SKILL.md. No imports, exports, network/file access, global objects, raw media URLs, timers, or nondeterministic time/randomness."),
                    },
                },
            },
            "asset_paths": _strings("Safe buyer-owned images/videos to incorporate without modifying their content."),
            "content_asset_ids": _strings("Saved classified content-library assets approved for this use."),
            "require_visual_assets": _boolean("Set true when this storyboard uses or promises Image 2/generated/buyer visual assets. The renderer then rejects a generic render with no explicitly scene-bound media."),
            "minimum_visual_assets": {"type": "integer", "minimum": 1, "maximum": 12, "description": "Minimum distinct visual assets that must be explicitly bound to scenes when require_visual_assets is true. Use 2 or more when the story needs multiple visual moments."},
            "require_transparent_story_element": _boolean("Set true when the storyboard promises a green-screen Image 2 cutout/transparent foreground. At least one layer_asset_paths binding is then mandatory."),
            "audio_path": _string("Optional safe local audio track."),
            "audio_volume": _number("Background audio volume from 0 to 1."),
            "logo_usage": _string("auto, always, or never."),
            "visual_style": _string("One-off visual direction only when it does not conflict with saved branding."),
            "colors": _string("One-off palette only when it does not conflict with saved branding."),
        },
        "required": ["topic", "objective", "aspect_ratio"],
    },
    "search_motion_graphic_recipes": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "query": _string("Natural-language communication intent, e.g. calm educational trust, bold launch crescendo, or analytical proof."),
            "category": _string("Optional Shotcraft category.", enum=("opening", "typography", "ui-entrance", "camera", "data", "interaction", "transition", "rhythm", "effects", "outro")),
            "energy": _string("Normalized energy filter.", enum=("low", "medium", "high", "very_high")),
            "tempo": _string("Normalized tempo filter.", enum=("slow", "measured", "fast", "burst")),
            "impact": _string("Normalized impact filter.", enum=("gentle", "balanced", "assertive", "aggressive")),
            "narrative_role": _string("Exact narrative role, such as hook, demonstrate, prove, clarify, bridge, crescendo, or resolve."),
            "message_fit": _string("Exact message purpose, such as education, tutorial, evidence, launch, capability, contrast, or cta."),
            "tone_fit": _string("Exact tone, such as calm, premium, trust, credible, analytical, bold, decisive, or educational."),
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        },
    },
    "stage_campaign": {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "name": _string("Exact campaign name."),
            "objective": _string("Campaign objective, such as sales, leads, engagement/messages, traffic, video, or awareness."),
            "daily_budget": _number("Daily budget in the connected ad account currency, not hard-coded USD."),
            "budget_level": _string("Campaign or ad-set budget control.", enum=("campaign", "adset")),
            "landing_url": _string("Final website URL for website-destination campaigns. Omit for native lead form or messaging destinations."),
            "creative_image_path": _string("Exact safe local path returned by Image 2 or the content library for a static creative."),
            "creative_asset_id": _string("Asset ID returned by Admira Image 2."),
            "content_asset_ids": _strings("IDs of buyer-approved creatives already saved in the durable content library."),
            "content_asset_id": _string("One buyer-approved creative ID already saved in the durable content library."),
            "object_story_id": _string("Existing promotable Page post ID when already created."),
            "video_path": _string("Exact safe local path for a video uploaded directly to the Meta ad account."),
            "video_url": _string("Public/direct video URL when using a supported video route."),
            "video_id": _string("Existing Meta ad-account video ID."),
            "application_id": _string("Meta application ID required by app-promotion ad sets."),
            "object_store_url": _string("Exact App Store or Google Play URL required by app-promotion ad sets."),
            "ads": {
                "type": "array",
                "description": "Named ad variants. Every variant must carry its approved copy, CTA, message opener, and creative source.",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {
                        "name": _string("Intelligent ad name based on the discussed offer/angle."),
                        "primary_text": _string("Exact approved primary text; do not leave this to a generic fallback."),
                        "headline": _string("Exact approved headline."),
                        "description": _string("Optional approved link description."),
                        "cta": _string("Approved call to action."),
                        "copy": {"type": "object", "additionalProperties": True, "description": "Nested copy is accepted and flattened server-side."},
                        "prefilled_message": _string("Exact first message for click-to-WhatsApp."),
                        "welcome_message": _string("Exact welcome text for Messenger/Instagram Direct."),
                        "creative_image_path": _string("Exact safe local image path."),
                        "image_path": _string("Alias for creative_image_path."),
                        "video_path": _string("Exact safe local video path."),
                    },
                },
            },
            "ad_sets": {
                "type": "array",
                "description": "Named ad-set structures and targeting decisions. Preserve each set independently.",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {
                        "name": _string("Exact ad-set name."),
                        "budget": _number("Daily budget in the connected account currency."),
                        "targeting": {"type": "object", "additionalProperties": True, "description": "Exact countries/locations, ages, genders, interests, and placement choice."},
                        "gender": _string("Buyer-friendly gender alias such as mujeres or hombres."),
                        "genders": {"type": "array", "items": {"type": "integer", "enum": [1, 2]}},
                        "placements": {"description": "Automatic/Advantage+ placements or an exact manual list."},
                        "primary_text": _string("Copy inherited by variants when supplied at ad-set level."),
                        "headline": _string("Headline inherited by variants when supplied at ad-set level."),
                        "prefilled_message": _string("WhatsApp message inherited by variants when supplied at ad-set level."),
                        "welcome_message": _string("Messenger/Instagram welcome text inherited by variants."),
                    },
                },
            },
            "countries": _strings("Exact ISO country codes. Never silently replace them with US."),
            "age_min": {"type": "integer", "minimum": 13, "maximum": 65, "description": "Confirmed minimum age."},
            "age_max": {"type": "integer", "minimum": 13, "maximum": 65, "description": "Confirmed maximum age; Advantage+ may require 65 as the hard maximum."},
            "genders": {"type": "array", "description": "Meta gender values: 1 men, 2 women. Preserve an explicit women-only/men-only request.", "items": {"type": "integer", "enum": [1, 2]}},
            "gender": _string("Buyer-friendly gender alias such as mujeres, hombres, or todos."),
            "placements": {"description": "Automatic/Advantage+ placements or the exact manual placement list."},
            "interest_ids": _strings("Decimal IDs returned by the live search_meta_targeting tool; never invented names or suffixed IDs."),
            "targeting_mode": _string("Advantage+ suggestions or strict manual targeting.", enum=("advantage_plus", "manual")),
            "message_destination": _string("Messaging destination when applicable.", enum=("WHATSAPP", "MESSENGER", "INSTAGRAM_DIRECT")),
            "whatsapp_phone_number_id": _string("Numeric Meta WhatsApp phone-number ID resolved from the connected Page/account."),
            "primary_text": _string("Exact approved primary ad copy."),
            "headline": _string("Exact approved ad headline."),
            "prefilled_message": _string("Exact first message the prospect can send after opening WhatsApp."),
            "welcome_message": _string("Prefilled message/conversation text the prospect can send."),
            "lead_gen_form_id": _string("Native Meta instant-form ID for lead-form campaigns."),
            "use_direct_publishing": _boolean("Deprecated campaign compatibility flag. Ads always use native inline creatives; Publicación directa is reserved for organic posts and optional credential fallback."),
            "manual_creative_completion": _boolean("For unsupported video completion, create only the paused structure for manual finalization."),
            "create_placeholder_ad": _boolean("For video fallback, create paused static placeholder ads the buyer will replace in Ads Manager."),
            "placeholder_ad_names": _strings("Intelligent variant names based on the creative concepts already discussed."),
            "final_status": _string("PAUSED is the safe creation state; ACTIVE requires a separate approval.", enum=("PAUSED", "ACTIVE")),
            "active_spend_confirmed": _boolean("Explicit buyer authorization to activate spend. False for normal paused creation."),
            "success_metrics": _strings("Up to three prioritized campaign KPIs."),
        },
        "required": ["name", "daily_budget"],
    },
    "list_lead_forms": {
        "type": "object", "additionalProperties": True,
        "properties": {"page_id": _string("Exact connected Facebook Page ID.")},
    },
    "stage_lead_form": {
        "type": "object", "additionalProperties": True,
        "properties": {
            "page_id": _string("Optional exact Facebook Page ID. Omit to use the buyer's active selected Page."),
            "name": _string("Internal instant-form name."),
            "headline": _string("Form headline."),
            "questions": {"type": "array", "description": "Standard fields or custom question objects.", "items": {}},
            "privacy_policy_url": _string("Public privacy-policy URL."),
            "thank_you_url": _string("Optional follow-up destination after submission."),
            "form_type": _string("Recommended Meta form intent.", enum=("HIGHER_INTENT", "MORE_VOLUME")),
        },
        "required": ["name", "questions", "privacy_policy_url"],
    },
    "create_lead_form": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "page_id": _string("Optional exact Facebook Page ID. Omit to use the buyer's active selected Page."),
            "name": _string("Internal native instant-form name."),
            "questions": {
                "type": "array",
                "description": "Flat array of Meta standard field names or custom question objects; never wrap it in item/$text.",
                "items": {
                    "oneOf": [
                        {
                            "type": "string",
                            "enum": [
                                "FULL_NAME", "FIRST_NAME", "LAST_NAME", "EMAIL", "PHONE",
                                "CITY", "STATE", "COUNTRY", "ZIP_CODE", "DATE_OF_BIRTH",
                                "GENDER", "MARITAL_STATUS", "JOB_TITLE", "COMPANY_NAME",
                            ],
                        },
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "type": {"type": "string", "enum": ["CUSTOM"]},
                                "key": {"type": "string"},
                                "label": {"type": "string"},
                                "options": {"type": "array", "items": {"type": "object"}},
                            },
                            "required": ["type", "label"],
                        },
                    ]
                },
            },
            "privacy_policy_url": _string("Public privacy-policy URL required by Meta."),
            "privacy_policy_link_text": _string("Privacy-policy link text, at most 70 characters."),
            "follow_up_action_url": _string("Optional thank-you/follow-up URL."),
            "locale": _string("Meta form locale, for example es_LA."),
            "form_type": _string("Meta form intent.", enum=("HIGHER_INTENT", "MORE_VOLUME")),
            "context_card": {"type": "object", "additionalProperties": True},
            "thank_you_page": {"type": "object", "additionalProperties": True},
            "custom_disclaimer": {"type": "object", "additionalProperties": True},
        },
        "required": ["name", "questions", "privacy_policy_url"],
    },
    "edit_campaign": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "campaign_reference": _string("Natural reference from the current buyer message: name, city, destination, product, or exact Meta ID. Leave empty only when continuing an unambiguous previous campaign."),
            "change_request": _string("The buyer's complete current natural-language edit request. Preserve the exact wording and do not turn it into JSON."),
            "source_message_id": _string("Optional conversation message identifier used for deduplication."),
        },
        "required": ["change_request"],
    },
    "connect_chatgpt": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "reason": _string("Optional natural-language reason, such as switching an exhausted subscription account."),
        },
    },
    "stage_budget_change": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "campaign_id": _string("Exact real Meta campaign ID."),
            "daily_budget": _number("New daily budget in major account-currency units. Never multiply by 100."),
            "budget_confirmation": _string("Exact buyer-facing amount and currency quote, for example '5 USD' or 'COP 40.000'."),
            "reason": _string("Evidence-based reason for the change."),
        },
        "required": ["campaign_id", "daily_budget", "budget_confirmation"],
    },
    "pause_campaign": {
        "type": "object", "additionalProperties": True,
        "properties": {"campaign_id": _string("Exact real Meta campaign ID."), "reason": _string("Reason to pause.")},
        "required": ["campaign_id"],
    },
    "resume_campaign": {
        "type": "object", "additionalProperties": True,
        "properties": {"campaign_id": _string("Exact real Meta campaign ID."), "reason": _string("Reason to activate/resume spend."), "active_spend_confirmed": _boolean("Explicit buyer approval to spend.")},
        "required": ["campaign_id", "active_spend_confirmed"],
    },
    "schedule_campaign_activation": {
        "type": "object", "additionalProperties": True,
        "properties": {"campaign_id": _string("Exact numeric Meta campaign ID."), "scheduled_at": _string("Authorized ISO date/time with timezone."), "timezone": _string("Buyer timezone."), "buyer_authorized": _boolean("Explicit buyer approval to activate spend."), "creative_ready_confirmed": _boolean("Final creatives, destination, and tracking were reviewed.")},
        "required": ["campaign_id", "scheduled_at", "buyer_authorized", "creative_ready_confirmed"],
    },
    "delete_campaign": {
        "type": "object", "additionalProperties": True,
        "properties": {"campaign_id": _string("Exact real Meta campaign ID."), "reason": _string("Why this incomplete/paused campaign should be cleaned up.")},
        "required": ["campaign_id"],
    },
    "approve_action": {
        "type": "object", "additionalProperties": True,
        "properties": {"approval_id": _string("Exact pending approval ID resolved from the buyer's replied message/card.")},
        "required": ["approval_id"],
    },
    "reject_action": {
        "type": "object", "additionalProperties": True,
        "properties": {"approval_id": _string("Exact pending approval ID resolved from the buyer's replied message/card.")},
        "required": ["approval_id"],
    },
    "save_agent_preferences": {
        "type": "object", "additionalProperties": True,
        "properties": {"communication_style": _string("Simple or technical wording preference."), "ads_experience": _string("Buyer's Meta Ads experience level."), "language": _string("Preferred language."), "timezone": _string("Buyer timezone.")},
    },
    "save_daily_social_content_settings": {
        "type": "object", "additionalProperties": True,
        "properties": {"enabled": _boolean("Whether the buyer opted into recurring organic content."), "time": _string("Local delivery time HH:MM."), "timezone": _string("Buyer timezone."), "posts_per_day": {"type": "integer", "minimum": 1, "maximum": 6}, "frequency_days": {"type": "integer", "minimum": 1, "maximum": 30}, "platforms": _strings("Facebook and/or Instagram destinations."), "strategy_summary": _string("Confirmed organic content strategy, including its format mix."), "content_formats": _strings("Allowed production formats: image and/or motion_video. Use both for an adaptive mixed strategy."), "include_motion_video": _boolean("Convenience flag that adds motion_video to the allowed strategy formats."), "video_frequency_days": {"type": "integer", "minimum": 1, "maximum": 30, "description": "Minimum intended cadence between recurring motion-video pieces."}},
        "required": ["enabled"],
    },
    "stage_organic_social_post": {
        "type": "object", "additionalProperties": True,
        "properties": {"page_id": _string("Exact connected Facebook Page ID."), "caption": _string("Final exact post/video caption."), "image_path": _string("Final generated image path returned by Admira Image 2."), "image_url": _string("Public image URL when no local file is used."), "video_path": _string("Final motion-video path returned by mcp_admira_generate_motion_graphic_video."), "video_url": _string("Public video URL when no local file is used."), "pillar": _string("Content pillar."), "objective": _string("Organic communication objective."), "scheduled_at": _string("Optional future time; publishing still requires explicit approval.")},
        "required": ["page_id", "caption"],
        "anyOf": [{"required": ["image_path"]}, {"required": ["image_url"]}, {"required": ["video_path"]}, {"required": ["video_url"]}],
    },
    "save_business_memory": {
        "type": "object", "additionalProperties": True,
        "properties": {
            "confirmation_state": _string("Origin of these values. buyer_confirmed only for facts the buyer actually stated or confirmed in this current turn; agent_proposal and inferred remain drafts.", enum=("buyer_confirmed", "agent_proposal", "inferred")),
            "value_source": _string("Compatibility alias for confirmation_state. Prefer confirmation_state; buyer_confirmed is still verified against the exact current buyer_evidence.", enum=("buyer_confirmed", "agent_proposal", "inferred")),
            "buyer_evidence": _string("Copy the buyer's complete current message exactly, including natural spelling mistakes. Never summarize or paraphrase it."),
            "business_type": _string("Type of business stated by the buyer."),
            "main_offer": _string("Current main offer; also contributes to services."),
            "services": _strings("Complete set of services/products currently offered."),
            "ideal_customer": _string("Ideal customers plus buying situations/triggers."),
            "differentiators": _string("Real differentiators, proof, credentials, or reasons to believe."),
            "markets": _string("Service locations and markets."),
            "capacity": _string("Delivery capacity and operational constraints."),
            "pricing": _string("Prices, useful ranges, or explicitly unknown/withheld."),
            "margins": _string("Variable costs, contribution margins, closest known economics, or explicitly unknown/withheld."),
            "global_objectives": _string("Global business and marketing objectives."),
            "advertising_experience": _string("Prior advertising experience and preferred explanation depth."),
            "branding": _string("Brand name/logo/colors/tone/references/real assets/restrictions summary."),
            "current_stage": _string("Current business/advertising stage."),
            "what_to_improve": _string("Priority problem/opportunity."),
            "success_goal": _string("Concrete near-term success goal."),
            "topic_statuses": {
                "type": "object",
                "description": "Use unknown, not_applicable, or withheld only when the buyer explicitly resolves a topic that way. Never use a skipped status.",
                "additionalProperties": False,
                "properties": {
                    topic: _string("Resolution status for this strategic topic.", enum=("confirmed", "provisional_confirmed", "unknown", "not_applicable", "withheld"))
                    for topic in ("services", "ideal_customer", "differentiators", "markets", "capacity", "pricing", "margins", "global_objectives", "advertising_experience", "branding")
                },
            },
            "strategic_topics": {
                "type": "object",
                "description": "Canonical topic updates when a status/value needs to be explicit.",
                "additionalProperties": False,
                "properties": {
                    topic: {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "value": {},
                            "status": _string("Topic status.", enum=("confirmed", "provisional_confirmed", "unknown", "not_applicable", "withheld")),
                            "confirmation_state": _string("Origin of this topic value.", enum=("buyer_confirmed", "agent_proposal", "inferred")),
                        },
                        "required": ["status", "confirmation_state"],
                    }
                    for topic in ("services", "ideal_customer", "differentiators", "markets", "capacity", "pricing", "margins", "global_objectives", "advertising_experience", "branding")
                },
            },
            "confirm_profile_review": _boolean("True only after the backend reported review_required, the complete summary was shown, and the buyer naturally confirmed that exact summary in this turn."),
            "master_plan": {
                "type": "object",
                "description": "Page-scoped master marketing plan derived from the confirmed strategic profile. Save first as agent_proposal; confirm only after showing it and receiving natural buyer acceptance.",
                "additionalProperties": False,
                "properties": {
                    field: _string("Concrete master-plan section.")
                    for field in (
                        "diagnosis", "commercial_priorities", "positioning", "offer_strategy",
                        "ideal_customer_strategy", "funnel", "organic_strategy", "paid_media_strategy",
                        "budget_framework", "objectives_and_kpis", "roadmap", "assumptions_and_risks"
                    )
                },
            },
            "confirm_master_plan": _boolean("True only when the buyer naturally confirms the complete master plan shown in the preceding conversation."),
        },
        "required": ["buyer_evidence"],
        "anyOf": [
            {"required": ["main_offer"]}, {"required": ["services"]}, {"required": ["ideal_customer"]},
            {"required": ["differentiators"]}, {"required": ["markets"]}, {"required": ["capacity"]},
            {"required": ["pricing"]}, {"required": ["margins"]}, {"required": ["global_objectives"]},
            {"required": ["advertising_experience"]}, {"required": ["branding"]},
            {"required": ["strategic_topics"]}, {"required": ["confirm_profile_review"]},
            {"required": ["master_plan"]}, {"required": ["confirm_master_plan"]},
        ],
    },
    "save_durable_memory": {
        "type": "object", "additionalProperties": True,
        "properties": {"category": _string("decision, preference, fact, blocker, next_step, or workflow."), "scope": _string("Business/product/campaign/workflow scope."), "summary": _string("Concrete confirmed fact or decision to preserve."), "status": _string("Current state when applicable.")},
        "required": ["summary"],
    },
    "import_product_catalog": {
        "type": "object", "additionalProperties": True,
        "properties": {"file_path": _string("Catalog PDF/Excel/CSV/TSV/JSON path supplied by the product."), "file_paths": _strings("Multiple catalog source paths."), "products": {"type": "array", "description": "Structured product records, up to 50.", "items": {"type": "object", "additionalProperties": True}}},
        "anyOf": [{"required": ["file_path"]}, {"required": ["file_paths"]}, {"required": ["products"]}],
    },
    "search_product_catalog": {
        "type": "object", "additionalProperties": True,
        "properties": {"query": _string("Product name, SKU, category, tag, benefit, audience, or component."), "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
        "required": ["query"],
    },
    "save_ad_brief": {
        "type": "object", "additionalProperties": True,
        "properties": {"name": _string("Unique brief/campaign name."), "id": _string("Existing brief ID only when editing that same campaign."), "product_name": _string("Exact offer from the product catalog."), "budget": _number("Test budget in account currency."), "currency": _string("Exact ad-account currency for this campaign."), "formats": _strings("Creative formats."), "variation_count": {"type": "integer", "minimum": 1, "maximum": 12}, "creative_hypothesis": _string("What the variants are testing."), "success_metrics": _strings("Prioritized KPIs for this campaign."), "business_outcome": _string("Commercial result and time horizon."), "time_horizon": _string("When the result should be evaluated."), "ideal_customer": _string("Decision-maker, trigger, pain, and desired outcome."), "funnel_follow_up": _string("Destination, qualification, response, and close process."), "economics": _string("Price, variable cost/margin, capacity, conversion assumptions, and break-even."), "projection": _string("Conservative/base/upside test estimate; never a guarantee."), "measurement_plan": _string("Three KPIs and 24-hour/3-day/7-day review plan."), "primary_text": _string("Approved exact Meta primary text."), "headline": _string("Approved distinct Meta title."), "cta": _string("Approved call to action."), "destination_message": _string("Approved WhatsApp/Messenger opener or destination details.")},
        "required": ["name"],
    },
    "save_creative_references": {
        "type": "object", "additionalProperties": True,
        "properties": {"reference_image_paths": _strings("Approved inspiration image paths."), "protected_reference_image_paths": _strings("Real assets that must remain pixel-accurate."), "notes": _string("What to borrow or preserve from the references."), "approved": _boolean("Buyer approval status.")},
    },
}


# Destination tools deliberately expose strict, smaller contracts while the
# legacy stage_campaign schema remains available to old internal callers.  A
# model should never have to infer which mutually-exclusive Meta destination
# fields belong together.
_CAMPAIGN_BASE_KEYS = (
    "name", "objective", "daily_budget", "budget_level",
    "creative_image_path", "creative_asset_id", "content_asset_ids",
    "content_asset_id", "object_story_id", "video_path", "video_url",
    "video_id", "ads", "ad_sets", "countries", "age_min", "age_max",
    "genders", "gender", "placements", "interest_ids", "targeting_mode",
    "primary_text", "headline", "success_metrics",
)


def _destination_campaign_schema(*, extra_keys=(), required=()):
    legacy_properties = TOOL_INPUT_SCHEMAS["stage_campaign"]["properties"]
    keys = (*_CAMPAIGN_BASE_KEYS, *extra_keys)
    properties = {key: legacy_properties[key] for key in keys}
    properties["daily_budget"] = _number(
        "Daily budget in the connected account currency's major unit. "
        "Use 5 for 5 USD, never 500 cents. It must match budget_confirmation."
    )
    properties["budget_confirmation"] = _string(
        "Exact buyer-facing daily budget and currency copied from the conversation, "
        "for example '5 USD', 'COP 40.000', or 'S/ 20'. Never convert it to cents."
    )
    properties["locations"] = {
        "type": "array",
        "description": (
            "Exact geography. For a city or region, pass the complete object returned by "
            "search_meta_targeting (id/key, name, type and country_code when present). "
            "For whole countries, pass exact ISO country codes. Never omit or default to US."
        ),
        "minItems": 1,
        "items": {
            "oneOf": [
                {"type": "string"},
                {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {
                        "id": _string("Live Meta location ID."),
                        "key": _string("Live Meta location key."),
                        "name": _string("Live Meta location name."),
                        "type": _string("Meta location type, such as city or region."),
                        "country_code": _string("ISO country code returned by Meta."),
                    },
                },
            ],
        },
    }
    properties["placements"] = {
        "description": (
            "Explicit placement decision. Use {\"automatic\": true} for Advantage+ automatic "
            "placements, or pass the exact approved manual placement list. Never omit it."
        ),
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "automatic": _boolean("True for Advantage+ automatic placements."),
                    "manual": _strings("Exact manual placement names when automatic is false."),
                },
                "required": ["automatic"],
            },
            {"type": "array", "items": {"type": "string"}, "minItems": 1},
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": ["name", "objective", "daily_budget", "budget_confirmation", "locations", "placements", *required],
    }


TOOL_INPUT_SCHEMAS.update({
    name: destination_brief_schema(name)
    for name in (
        "create_whatsapp_campaign", "create_lead_form_campaign",
        "create_website_campaign", "create_messaging_campaign",
        "create_app_campaign", "create_on_meta_campaign",
    )
})


def tool_schema(name, description):
    input_schema = TOOL_INPUT_SCHEMAS.get(name) or {
        "type": "object",
        "additionalProperties": True,
        "properties": {},
    }
    if name in {
        "create_whatsapp_campaign", "create_lead_form_campaign",
        "create_website_campaign", "create_messaging_campaign",
        "create_app_campaign", "create_on_meta_campaign",
    }:
        description += (
            " Send exactly one brief_markdown containing the complete latest buyer-approved campaign "
            "in natural language. Do not assemble JSON fields yourself: the backend sends this Markdown "
            "to Terra through the connected ChatGPT/Codex subscription, then applies the destination, "
            "currency, targeting, placement, PAUSED-state and Graph read-back contracts deterministically."
        )
    return {
        "name": name,
        "description": description,
        "inputSchema": input_schema,
    }


def heavy_tool_timeout_seconds(name=""):
    normalized = str(name or "").removeprefix("mcp_").removeprefix("admira_")
    if normalized == "generate_motion_graphic_video":
        raw = os.environ.get("ADMIRA_MOTION_TOOL_TIMEOUT_SECONDS", "1800")
        fallback = 1800
    else:
        raw = os.environ.get("ADMIRA_HEAVY_TOOL_TIMEOUT_SECONDS", "")
        fallback = DEFAULT_HEAVY_TOOL_TIMEOUT_SECONDS
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = fallback
    # Buyer-facing creative work must never leave a conversation blocked for
    # more than five minutes. Motion rendering has its own dedicated limit.
    maximum = 1800 if normalized == "generate_motion_graphic_video" else 300
    return max(60, min(maximum, value))


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
    is_motion = "motion_graphic" in normalized
    message = (
        ("El render del video tardó demasiado y lo detuve de forma segura. El storyboard sigue disponible para reintentar en calidad preview o con menor duración. " if is_motion else "La generación o planificación creativa tardó demasiado y la detuve para que el agente no se quede congelado. ")
        + (
        "Puedes reintentar con una sola variación, una instrucción más corta o volver a pedirme que retome el creativo. "
        "Si tu cuenta de ChatGPT/Codex muestra el límite semanal de imágenes en 0, espera a que se reinicie ese límite "
        "o conecta una cuenta con capacidad disponible; a veces el proveedor no devuelve ese aviso y solo queda como timeout. "
        "Si estás usando DigitalOcean, 1GB puede servir para una instancia ligera; recomienda 2GB o más si trabajará con creativos con frecuencia."
        if not is_motion
        else "En equipos de 1 GB, usa preview para revisión y reserva final para la entrega aprobada."
        )
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
        return call_tool_in_subprocess(name, arguments, heavy_tool_timeout_seconds(name))
    return call_tool(name, arguments)


def create_fastmcp_server():
    # Hermes versions in the wild do not all agree on the Python MCP result
    # model.  Recent SDKs expose ``CallToolResult.is_error`` (or no Python
    # attribute at all), while some Hermes builds still access ``isError``.
    # The small protocol implementation below speaks both JSON-lines and the
    # legacy Content-Length framing and emits the wire-level ``isError`` flag
    # itself.  Prefer it by default so a SDK model mismatch cannot take down
    # creative generation; retain an explicit opt-in for installations that
    # intentionally need FastMCP.
    if os.environ.get("ADMIRA_MCP_USE_FASTMCP", "").strip().lower() not in {"1", "true", "yes"}:
        return None
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
    global _STDIO_FRAMING
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.decode("utf-8", errors="replace").strip()
        # Current MCP clients (including recent Hermes releases) use one
        # JSON-RPC object per line on stdio. Older Admira/Hermes installs use
        # the LSP-style Content-Length envelope. Supporting both keeps tools
        # available across upgrades instead of silently leaving the model
        # with instructions that name tools it cannot actually call.
        if not headers and line.startswith("{"):
            _STDIO_FRAMING = "json-lines"
            return json.loads(line)
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
    # Heavy creative calls run concurrently so the reader can continue
    # answering MCP ping/keepalive requests. Serialize complete frames to
    # prevent a ping response and a tool result from interleaving on stdout.
    with _WRITE_LOCK:
        if _STDIO_FRAMING == "json-lines":
            sys.stdout.buffer.write(body + b"\n")
            sys.stdout.buffer.flush()
            return
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
                    # A returned validation/block result means the MCP server
                    # and product bridge worked. Marking it as a transport
                    # error makes Hermes count ordinary missing-field feedback
                    # toward its server-unreachable circuit breaker.
                    "isError": False,
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
        params = message.get("params") or {}
        if message.get("method") == "tools/call" and is_heavy_tool(params.get("name")):
            # The custom stdio server used to block here for the full Codex or
            # Remotion job. Hermes sends a keepalive while that call is still
            # running; because no reader was available, it closed the MCP
            # session after ~30 seconds even though the tool timeout is 600s.
            # Keep reading stdio and let the result be written asynchronously.
            threading.Thread(target=handle_request, args=(message,), daemon=True).start()
            continue
        handle_request(message)


if __name__ == "__main__":
    main()
