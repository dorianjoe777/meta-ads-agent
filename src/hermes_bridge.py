#!/usr/bin/env python3
"""Hermes Agent bridge for dashboard and Telegram conversations."""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

from agent_runtime import build_system_prompt
from communication_style import ad_experience_from_environment, ad_experience_instruction, communication_style_from_environment, communication_style_instruction
from decision_memory import decision_memory_payload, format_learning_log
from experiment_scheduler import experiment_review_payload
from local_store import read_json
from optimization_engine import load_optimization_state
from optimization_research import load_research
from admira_rate_limit_messages import (
    is_rate_limit_text,
    lighter_model_switch_hint,
    localized_textual_hint,
    retry_delay_hint,
    retry_seconds_from_text,
    textual_retry_hint,
)
from security import redact_payload

try:
    from product_config import normalize_hermes_model
except ImportError:
    def normalize_hermes_model(value):
        model = str(value or "").strip()
        if not model or model.lower() in {"auto", "recommended", "recomendado", "default"}:
            return "gpt-5.5"
        return model


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "dashboard" / "data"
BRAND_GUIDES_DIR = ROOT_DIR / "brand_guides"
AGENT_SKILLS_DIR = ROOT_DIR / "agent" / "skills"
HERMES_WORKSPACE_DIR = DATA_DIR / "hermes-workspace" / "current"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ADMIRA_MINIMAX_KEY_ENV = "ADMIRA_MINIMAX_API_KEY"
ADMIRA_MINIMAX_BASE_URL_ENV = "ADMIRA_MINIMAX_BASE_URL"
ADMIRA_MINIMAX_PROVIDER = "admira-minimax"
ADMIRA_MINIMAX_PROVIDER_NAME = "MiniMax M3 oficial"
BASE_ALLOWED_IMAGE_DIRS = (
    ROOT_DIR / "output",
    ROOT_DIR / "dashboard" / "data" / "uploads",
    ROOT_DIR / "dashboard" / "data" / "hermes-home" / "cache" / "images",
)
IMAGE_PATH_TEXT_KEYS = {
    "request",
    "prompt",
    "image_prompt",
    "reference_image_summary",
    "message",
    "text",
    "description",
    "image_path",
    "photo_path",
    "asset_path",
    "real_photo_path",
    "reference_image_path",
}
EMBEDDED_IMAGE_PATH_RE = re.compile(r"(?P<path>(?:~|/|\.{1,2}/)?(?:[^\s\"'<>|]+/)+[^\s\"'<>|]+\.(?:jpe?g|png|webp|gif))", re.IGNORECASE)
MEMORY_TEXT_LIMIT = 14000
MEMORY_ITEM_LIMIT = 8
RECENT_CONTEXT_LOOKBACK_DAYS = 7
RECENT_CONTEXT_ITEM_LIMIT = 12
BLOCKED_MEMORY_TOKENS = {".env", "license_unlock.json"}
PROFILE_FILES = ("SOUL.md", "USER.md", "AGENTS.md", "TOOLS.md", "SKILLS.md")
SKILL_FILE_NAME = "SKILL.md"
MODEL_USAGE_LIMIT_PATTERNS = (
    r"\b429\b",
    r"too many requests",
    r"rate limit",
    r"rate-limiting",
    r"rate limited",
    r"usage limit",
    r"usage cap",
    r"usage exhausted",
    r"message limit",
    r"limit reached",
    r"reached (?:your|the) limit",
    r"reached (?:your|the) .* cap",
    r"hit (?:your|the) .* limit",
    r"maximum usage",
    r"cap reached",
    r"quota exceeded",
    r"insufficient quota",
    r"temporarily unavailable due to limits",
    r"limite de uso",
    r"límite de uso",
    r"limite temporal",
    r"límite temporal",
    r"cuota excedida",
)


def split_csv(value):
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _quote_yaml(value):
    return json.dumps(str(value or ""), ensure_ascii=False)


def hermes_home_path(config):
    path = Path(str(getattr(config, "hermes_home", "") or DATA_DIR / "hermes-home")).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def _hermes_model_config_lines(brain):
    """Return Hermes model config lines for the selected Admira brain.

    MiniMax M3 must use the official MiniMax OpenAI-compatible endpoint, not
    OpenRouter. Hermes' native MiniMax provider can lag the official model
    catalog, so Admira exposes it as a named custom provider while keeping the
    API key only in the process environment.
    """
    model_provider = brain.get("provider") or "openai-codex"
    model_default = brain.get("model") or normalize_hermes_model("")
    base_url = str(brain.get("base_url") or "").strip().rstrip("/")
    lines = [
        "model:",
        f"  provider: {_quote_yaml(model_provider)}",
        f"  default: {_quote_yaml(model_default)}",
    ]
    if brain.get("brain") == "minimax":
        provider_slug = ADMIRA_MINIMAX_PROVIDER
        provider_name = ADMIRA_MINIMAX_PROVIDER_NAME
        official_base_url = base_url or "https://api.minimax.io/v1"
        lines = [
            "model:",
            f"  provider: {_quote_yaml(provider_slug)}",
            f"  default: {_quote_yaml(model_default)}",
            "providers:",
            f"  {provider_slug}:",
            f"    name: {_quote_yaml(provider_name)}",
            f"    base_url: {_quote_yaml(official_base_url)}",
            f"    key_env: {_quote_yaml(ADMIRA_MINIMAX_KEY_ENV)}",
            "    api_mode: \"chat_completions\"",
            f"    model: {_quote_yaml(model_default)}",
            "    models:",
            f"      {_quote_yaml(model_default)}: {{}}",
            "model_aliases:",
            f"  {_quote_yaml(model_default)}:",
            f"    model: {_quote_yaml(model_default)}",
            f"    provider: {_quote_yaml(provider_slug)}",
            f"    base_url: {_quote_yaml(official_base_url)}",
            "  \"minimax m3\":",
            f"    model: {_quote_yaml(model_default)}",
            f"    provider: {_quote_yaml(provider_slug)}",
            f"    base_url: {_quote_yaml(official_base_url)}",
            "  \"minimax-m3\":",
            f"    model: {_quote_yaml(model_default)}",
            f"    provider: {_quote_yaml(provider_slug)}",
            f"    base_url: {_quote_yaml(official_base_url)}",
            "  \"minimax\":",
            f"    model: {_quote_yaml(model_default)}",
            f"    provider: {_quote_yaml(provider_slug)}",
            f"    base_url: {_quote_yaml(official_base_url)}",
        ]
    return lines


def hermes_cli_provider(brain):
    if brain.get("brain") == "minimax":
        return ADMIRA_MINIMAX_PROVIDER
    return brain.get("provider") or ""


def cli_toolsets(config, payload=None):
    configured = split_csv(getattr(config, "hermes_enabled_toolsets", ""))
    toolsets = configured or ["memory", "skills", "session_search", "vision", "file", "web", "browser"]
    channel = str((payload or {}).get("channel") or "").strip().lower()
    if channel in {"dashboard", "telegram"} or not channel:
        toolsets.append("admira")
    seen = set()
    unique = []
    for toolset in toolsets:
        key = str(toolset or "").strip()
        if key and key not in seen:
            unique.append(key)
            seen.add(key)
    return unique


def _cli_hermes_config_needs_write(config_text, brain):
    if "mcp_servers:" not in config_text or "admira_mcp_server.py" not in config_text:
        return True
    if brain.get("brain") == "minimax":
        lowered = config_text.lower()
        return "admira-minimax" not in config_text or "providers:" not in config_text or "api.minimax.io/v1" not in config_text or "openrouter" in lowered or "custom:admira-minimax" in config_text
    return False


def write_cli_hermes_config(config, workspace_info, payload=None):
    """Ensure Hermes CLI chats have the same safe Admira MCP tools as Telegram.

    The dashboard chat already routes through Hermes, but Hermes only gains
    product "hands" when its home has the Admira MCP server registered. This
    writer is intentionally conservative: if a gateway-generated config already
    has the Admira MCP server, it leaves that richer config untouched.
    """
    home = hermes_home_path(config)
    config_path = home / "config.yaml"
    brain = hermes_brain_settings(config)
    existing = ""
    if config_path.exists():
        try:
            existing = config_path.read_text(encoding="utf-8")
        except OSError:
            existing = ""
    if existing and not _cli_hermes_config_needs_write(existing, brain):
        return {"hermes_home": str(home), "config": str(config_path), "written": False}

    timezone_name = str(getattr(config, "daily_brief_timezone", "UTC") or "UTC")
    workspace_path = str(workspace_info.get("path") or HERMES_WORKSPACE_DIR)
    mcp_server_path = ROOT_DIR / "src" / "admira_mcp_server.py"
    disabled = split_csv(getattr(config, "hermes_disabled_toolsets", ""))
    for protected in ("terminal", "code_execution", "image_gen"):
        if protected not in disabled:
            disabled.append(protected)
    dashboard_toolsets = cli_toolsets(config, {"channel": "dashboard"})
    telegram_toolsets = ["hermes-telegram", *cli_toolsets(config, {"channel": "telegram"})]
    config_yaml = [
        f"timezone: {_quote_yaml(timezone_name)}",
        *_hermes_model_config_lines(brain),
        "agent:",
        f"  max_turns: {max(1, int(getattr(config, 'hermes_max_iterations', 12) or 12))}",
        "  disabled_toolsets:",
        *[f"    - {toolset}" for toolset in disabled],
        "compression:",
        "  enabled: true",
        "  threshold: 0.85",
        "  codex_gpt55_autoraise: false",
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
        f"  cwd: {_quote_yaml(workspace_path)}",
        "telegram:",
        "  gateway_restart_notification: false",
        "  reactions: false",
        "platform_toolsets:",
        "  dashboard:",
        *[f"    - {toolset}" for toolset in dashboard_toolsets],
        "  telegram:",
        *[f"    - {toolset}" for toolset in telegram_toolsets],
        "  cli:",
        *[f"    - {toolset}" for toolset in dashboard_toolsets],
        "streaming:",
        "  enabled: false",
        "hooks_auto_accept: true",
    ]
    config_path.write_text("\n".join(config_yaml).rstrip() + "\n", encoding="utf-8")
    try:
        config_path.chmod(0o600)
    except OSError:
        pass
    return {"hermes_home": str(home), "config": str(config_path), "written": True}


def allowed_image_dirs():
    roots = [*BASE_ALLOWED_IMAGE_DIRS, HERMES_WORKSPACE_DIR / "uploads"]
    hermes_home = str(os.environ.get("HERMES_HOME") or "").strip()
    if hermes_home:
        roots.append(Path(hermes_home).expanduser() / "cache" / "images")
    return roots


def embedded_image_paths_from_text(value):
    paths = []
    for match in EMBEDDED_IMAGE_PATH_RE.finditer(str(value or "")):
        candidate = match.group("path").strip().rstrip(").,;:]}'\"")
        if candidate:
            paths.append(candidate)
    return paths


def image_path_candidates(value, scan_all_strings=False):
    candidates = []
    if isinstance(value, dict):
        for key in ("image_paths", "reference_image_paths", "images", "files"):
            candidates.extend(image_path_candidates(value.get(key), scan_all_strings=True))
        for key, item in value.items():
            lowered = str(key or "").strip().lower()
            should_scan = scan_all_strings or lowered in IMAGE_PATH_TEXT_KEYS or "image" in lowered or "photo" in lowered
            if should_scan:
                candidates.extend(image_path_candidates(item, scan_all_strings=True))
        return candidates
    if isinstance(value, (list, tuple, set)):
        for item in value:
            candidates.extend(image_path_candidates(item, scan_all_strings=scan_all_strings))
        return candidates
    if isinstance(value, str):
        text = value.strip()
        if text:
            candidates.append(text)
            candidates.extend(embedded_image_paths_from_text(text))
    return candidates


def safe_image_paths(payload):
    safe = []
    seen = set()
    for raw_path in image_path_candidates(payload):
        try:
            path = Path(str(raw_path)).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if str(path) in seen:
            continue
        if path.suffix.lower() not in IMAGE_EXTENSIONS or not path.exists() or not path.is_file():
            continue
        allowed = False
        for root in allowed_image_dirs():
            try:
                path.relative_to(root.resolve())
                allowed = True
                break
            except ValueError:
                continue
        if allowed:
            seen.add(str(path))
            safe.append(str(path))
    return safe[:4]

def read_text(path, limit=MEMORY_TEXT_LIMIT):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return ""
    return text[:limit]


def scrub_memory(payload):
    if isinstance(payload, dict):
        clean = {}
        for key, value in payload.items():
            lowered = str(key or "").lower()
            if lowered in {"product_guide", "file", "filename", "path", "payload_path"} and any(token in str(value).lower() for token in BLOCKED_MEMORY_TOKENS):
                clean[key] = "redacted"
            else:
                clean[key] = scrub_memory(value)
        return clean
    if isinstance(payload, list):
        return [scrub_memory(item) for item in payload]
    if isinstance(payload, str):
        clean = payload
        for token in BLOCKED_MEMORY_TOKENS:
            clean = clean.replace(token, "redacted")
        return clean
    return payload


def write_workspace_file(relative_path, content):
    workspace_root = HERMES_WORKSPACE_DIR.resolve()
    target = (HERMES_WORKSPACE_DIR / relative_path).resolve()
    target.relative_to(workspace_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, (dict, list)):
        target.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        target.write_text(str(content or ""), encoding="utf-8")
    return str(target.relative_to(workspace_root))


def read_agent_profile_file(name):
    path = ROOT_DIR / "agent" / name
    return read_text(path, MEMORY_TEXT_LIMIT)


def memory_display_path(path):
    path = Path(path)
    for root in (ROOT_DIR, BRAND_GUIDES_DIR.parent):
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return path.name


def combined_agent_rules():
    sections = []
    for name in PROFILE_FILES:
        content = read_agent_profile_file(name)
        if content:
            sections.append(f"\n\n# Product Agent File: {name}\n\n{content.strip()}")
    sections.append(
        """

# Runtime Workspace Contract

Hermes is the agentic runtime and conversation owner. The product backend is only the transport, safety, and execution layer.

Business interview, brand, creative direction, and previous campaign questions are handled by the agent conversation. They are not dashboard setup blockers. Do not tell the buyer "Completa la configuración para ver datos reales" or similar because those interview items are pending. Only describe setup as missing when the current context or a product tool confirms a real technical requirement is missing: license, Meta connection, ad account, destination, real Meta data, ChatGPT/Codex, or Telegram.

For each turn, read the buyer message normally. If you need live account context, use the local files in this workspace:

- `CURRENT_CONTEXT.json`: current dashboard/account snapshot for this turn.
- `memory/Conversation continuity.md`, `memory/continuity_status.json`, `memory/latest_day_context.md`, and `memory/active_workflow.json`: mandatory resume brief after history cleanup, gateway restart, update, or a fresh runtime session.
- `data/business_profile.json`: business memory.
- `data/audience_strategy.json`: audience strategy.
- `data/business_binding.json`: selected Meta account/page binding.
- `memory/Agent onboarding plan.md`: current onboarding phase.
- `memory/Ads campaign onboarding.md`: prior ads/campaign context.
- `memory/recent_actions.json`: recent protected actions and tool outcomes when present.
- `memory/pending_approvals.json`: pending protected decisions when present.
- `memory/profitability_rules.json`, `memory/decision_memory.json`, `memory/learning_log.md`: decision memory.
- `memory/creative_experiments.json`: adaptive creative-test checkpoints, evidence, provisional leaders, and next review dates.
- `brand_guides/`: brand, product, ad brief, and creative reference memory.
- `skills/`: focused product skills. Read `core-agent-behavior` before every reply, `session-continuity` after cleanup/restart/update/fresh sessions, and the relevant specialist skill before taking product actions.

Do not expect the backend to paste the whole conversation history into the prompt. Hermes session memory is useful, but it is cache; durable workspace files are the source of truth. At the start of a fresh/restarted Telegram session, after a history cleanup, or after an update/gateway restart, first read `skills/session-continuity/SKILL.md`, `memory/Conversation continuity.md`, `memory/continuity_status.json`, `memory/latest_day_context.md`, `memory/active_workflow.json`, `CURRENT_CONTEXT.json`, `data/business_profile.json`, `memory/Agent onboarding plan.md`, `memory/Ads campaign onboarding.md`, `memory/recent_actions.json`, `memory/pending_approvals.json`, `memory/creative_experiments.json`, and relevant `brand_guides/` files. If `has_persistent_memory` or `has_active_workflow` is true, do not introduce yourself as first time, do not restart onboarding, and do not repeat the initial ads-experience/technical-style question unless the files prove it is still missing. Resume with a short "retomo donde quedamos" style message when natural, mention one concrete remembered item, and continue from the next missing/actionable step. If needed, use session search to inspect previous Telegram sessions, but do not block the buyer when durable workspace memory is enough. If the buyer's short answer is still ambiguous, ask one clear follow-up.

# Turn Orientation Before Every Reply

Read `skills/core-agent-behavior/SKILL.md`. Before answering, silently determine the buyer's immediate goal, the current workflow phase, what is already done/saved/created/attempted, what remains missing or blocked, and the next safest useful action. Do not respond as if the latest message is disconnected from the ongoing setup, creative, campaign, or optimization work. Keep this checklist private; in the visible reply, continue naturally and move the work forward.

# Buyer-facing content boundary

Internal workspace files are private memory/tooling, not the buyer's workspace. Do not expose internal paths such as `/app/...`, `dashboard/data/...`, `hermes-workspace/...`, `brand_guides/...`, `memory/...`, or `CURRENT_CONTEXT.json` unless support explicitly asks for technical diagnostics. Do not present `MEDIA:/...` as a buyer-facing link or file address. If a generated image/file must be delivered, use `MEDIA:<local_path>` only as the platform's native attachment directive, and make the visible reply say the file is attached. If the buyer asks for a prompt, copy, plan, script, checklist, or explanation, paste the useful content directly in the chat. Do not reply only with "lo guardé en este archivo" or ask them to open an internal path they cannot access. You may save the content internally too, but the buyer-facing answer must stand on its own.

# Native Product Tools

The product exposes protected backend actions through Hermes MCP. Tool names appear with the `mcp_admira_` prefix inside Hermes, for example `mcp_admira_codex_image_generate`.

Use these MCP tools for real product actions instead of inventing results, running arbitrary shell commands, or using Hermes internal image generation:

- `mcp_admira_get_real_meta_context`
- `mcp_admira_run_daily_brief`
- `mcp_admira_schedule_experiment_review`
- `mcp_admira_list_experiment_reviews`
- `mcp_admira_run_due_experiment_reviews`
- `mcp_admira_review_signal_quality`
- `mcp_admira_preflight_campaign`
- `mcp_admira_fetch_public_asset`
- `mcp_admira_codex_image_generate`
- `mcp_admira_codex_creative_plan`
- `mcp_admira_stage_campaign`
- `mcp_admira_stage_budget_change`
- `mcp_admira_pause_campaign`
- `mcp_admira_resume_campaign`
- `mcp_admira_list_pending_approvals`
- `mcp_admira_approve_action`
- `mcp_admira_reject_action`
- `mcp_admira_save_agent_preferences`
- `mcp_admira_record_verified_signal`
- `mcp_admira_get_verified_signal_summary`
- `mcp_admira_verified_signal_feedback_prompt`
- `mcp_admira_save_business_memory`
- `mcp_admira_save_ads_onboarding`
- `mcp_admira_save_brand_memory`
- `mcp_admira_save_product_memory`
- `mcp_admira_save_ad_brief`
- `mcp_admira_save_creative_references`

If the MCP tool is unavailable, say the action cannot be executed yet and explain what must be connected. Do not fall back to fake campaign data or uncontrolled terminal commands.

Dashboard chat and Telegram are buyer-facing product surfaces, not terminals. Never tell the buyer you cannot create, prepare, or stage a campaign because you lack CLI/terminal access. Product actions must go through MCP tools in Telegram or the JSON tool-request contract in dashboard chat. If details are missing, ask the next missing business detail; if a protected action is ready, prepare it for approval.

When the buyer shares a public URL and asks you to review, understand, use, or create ads from it, first use `mcp_admira_fetch_public_asset` for buyer-shared assets/pages, especially Google Drive videos/images or creative references. It safely inspects public pages and downloads public image/video assets to the product workspace. If it returns a video asset, use its returned `video_url`/`direct_url` when staging a video creative. If it returns `video_frame_paths`/`video_preview_frame_paths`, use those extracted image frames with vision to understand the MP4/MOV visually; do not try to inspect the raw video file directly and do not tell the buyer you cannot review video merely because a low-level viewer only accepts images. If frame extraction fails, explain that precise limitation and ask for public access, a direct upload, or 2-4 key screenshots. Use the available `web`/`browser` retrieval tools as a secondary path for general research. Do not immediately claim you cannot access links. If access fails because the link is private, requires login, is too large, times out, or resolves to a private/local network, explain that specific limitation in simple words and ask the buyer to make it public or upload the file directly in Telegram.

Brand, product, ad-brief, and creative-reference files are backend-owned memory. The `brand_guides/` files inside the Hermes workspace are read-only context snapshots, not the source of truth for production readiness. Never manually create, edit, or write `brand_guides/*.md`, `/app/brand_guides/*.md`, or workspace brand-guide files to unblock creative production. Use `mcp_admira_save_brand_memory`, `mcp_admira_save_product_memory`, `mcp_admira_save_ad_brief`, and `mcp_admira_save_creative_references`. If a save tool rejects natural wording, retry once with canonical fields such as `brand_name`, `offer`, `colors`, `visual_style`, `tone`, `logo_notes`, `references`, `asset_notes`, `name`, `product_guide`, `variation_count`, `concurrent_variations`, `formats`, and `creative_hypothesis`.

Never call `mcp_admira_codex_creative_plan` as a replacement for the branding interview. Before using it for serious ad strategy or launch-ready assets, the workspace should have brand name/offer, colors, visual style, tone, logo decision, reference decision, real-asset decision, and product/offer. Budget helps size tests and launch decisions, but it must not block a standalone image/asset the buyer simply wants to create. If an important brand/offer item is missing, ask the exact next branding question or pass the buyer's current product context in the tool request instead of claiming Codex generated something.

# Global Expert Configurator Posture

The buyer may or may not know Meta Ads. You do. Be proactive across every high-impact lever the product exposes: measurement/event setup, optimization event, promoted object, budget and schedule, audience/exclusions, placement strategy, creative format, signal-quality diagnostics, preflight checks, approvals, and experiment follow-ups. Do not wait for the buyer to name a technical setting when it clearly affects wasted spend or campaign learning. Explain the business impact at the buyer's preferred detail level, and keep protected spend/account changes behind approval.

# Verified Signal Mode

When the buyer provides lead-quality or outcome feedback, save it with `mcp_admira_record_verified_signal`. The local ledger is automatic-first: the agent should organize, deduplicate, map, and score available leads/messages/bookings/purchases before asking the buyer. The daily question should ask only for exceptions and meaningful outcomes: fake/confused/not-interested/wrong-audience people, booked/showed/purchased/high-value outcomes, and stage changes from previous days. This tool only stores local truth; it does not send events to Meta.
"""
    )
    style = communication_style_from_environment()
    ad_experience = ad_experience_from_environment()
    sections.append(
        "\n\n# Buyer Operator Preferences\n\n"
        + communication_style_instruction(style, "en")
        + "\n"
        + ad_experience_instruction(ad_experience, "en")
        + "\nTreat these explicit preferences as overriding the default buyer-profile wording level, but never as overriding product safety rules."
    )
    return "\n".join(sections).strip() + "\n"


def write_product_skill_workspace_files():
    written = []
    if not AGENT_SKILLS_DIR.exists():
        return written
    skill_names = []
    for skill_dir in sorted(path for path in AGENT_SKILLS_DIR.iterdir() if path.is_dir()):
        source = skill_dir / SKILL_FILE_NAME
        if not source.exists():
            continue
        content = read_text(source, MEMORY_TEXT_LIMIT)
        if not content:
            continue
        target = f"skills/{skill_dir.name}/{SKILL_FILE_NAME}"
        written.append(write_workspace_file(target, content))
        skill_names.append(skill_dir.name)
    if skill_names:
        routing = [
            "",
            "## Mandatory first reads",
            "",
            "- `core-agent-behavior/SKILL.md` before every buyer-facing reply.",
            "- `session-continuity/SKILL.md` before any first greeting, onboarding question, or response after cleanup/restart/update.",
            "",
            "## Routing",
            "",
            "- Business discovery: `business-onboarding/SKILL.md`.",
            "- Brand/logo/assets: `brand-and-assets/SKILL.md`.",
            "- Creative ideas/tests: `creative-strategy/SKILL.md`.",
            "- Codex/Image production: `creative-production-codex-image/SKILL.md`.",
            "- Campaign planning: `campaign-strategy/SKILL.md`.",
            "- Meta Graph execution, direct publishing, lead forms: `meta-campaign-execution/SKILL.md`.",
            "- Results, budgets, experiments, daily brief, feedback loop: `measurement-optimization/SKILL.md`.",
            "- Failures, rate limits, access/update issues: `support-recovery/SKILL.md`.",
            "- Legacy compatibility shims: `branding-creatives-creation`, `campaign-creation`, `creative-codex-image`.",
            "",
            "## Available skill files",
            "",
        ]
        written.append(
            write_workspace_file(
                "skills/README.md",
                "# Admira IA Product Skills\n\n"
                "Use the most relevant skill before taking product actions.\n"
                + "\n".join(routing)
                + "\n".join(f"- `{name}/SKILL.md`" for name in skill_names)
                + "\n",
            )
        )
    return written


def write_agent_profile_workspace_files():
    written = []
    for name in PROFILE_FILES:
        content = read_agent_profile_file(name)
        if content:
            if name == "AGENTS.md":
                written.append(write_workspace_file("profile/AGENTS.source.md", content))
            else:
                written.append(write_workspace_file(name, content))
    written.append(write_workspace_file("AGENTS.md", combined_agent_rules()))
    written.extend(write_product_skill_workspace_files())
    return written


def copy_workspace_file(source_path, relative_dir):
    source = Path(source_path).resolve()
    target_dir = (HERMES_WORKSPACE_DIR / relative_dir).resolve()
    target_dir.relative_to(HERMES_WORKSPACE_DIR.resolve())
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    shutil.copy2(source, target)
    return str(target)


def business_memory_files():
    files = {
        "business_profile": DATA_DIR / "business_profile.json",
        "onboarding_questions": DATA_DIR / "Onboarding questions.md",
        "onboarding_plan": DATA_DIR / "Agent onboarding plan.md",
        "ads_onboarding": DATA_DIR / "Ads campaign onboarding.md",
        "audience_strategy": DATA_DIR / "audience_strategy.json",
        "individual_business_binding": DATA_DIR / "individual_business_binding.json",
        "general_branding": BRAND_GUIDES_DIR / "general_branding.md",
        "creative_references": BRAND_GUIDES_DIR / "creative_references.md",
    }
    product_guides = []
    products_dir = BRAND_GUIDES_DIR / "products"
    if products_dir.exists():
        for path in sorted(products_dir.glob("*.md"))[:MEMORY_ITEM_LIMIT]:
            if path.name == "product.example.md":
                continue
            product_guides.append(path)
    ad_briefs = []
    ad_briefs_dir = BRAND_GUIDES_DIR / "ad_briefs"
    if ad_briefs_dir.exists():
        for path in sorted(ad_briefs_dir.glob("*.md"))[:MEMORY_ITEM_LIMIT]:
            if path.name == "ad_brief.example.md":
                continue
            ad_briefs.append(path)
    return files, product_guides, ad_briefs


def business_memory_context():
    files, product_guides, ad_briefs = business_memory_files()
    memory = {
        "business_profile": redact_payload(read_json(files["business_profile"], {})),
        "audience_strategy": redact_payload(read_json(files["audience_strategy"], {})),
        "business_binding": redact_payload(read_json(files["individual_business_binding"], {})),
        "onboarding_questions": read_text(files["onboarding_questions"]),
        "onboarding_plan": read_text(files["onboarding_plan"]),
        "ads_onboarding": read_text(files["ads_onboarding"]),
        "creative_references": read_text(files["creative_references"]),
        "brand_guides": {
            "general_branding": read_text(files["general_branding"]),
            "products": [
                {"path": memory_display_path(path), "content": read_text(path, 5000)}
                for path in product_guides
            ],
            "ad_briefs": [
                {"path": memory_display_path(path), "content": read_text(path, 5000)}
                for path in ad_briefs
            ],
        },
        "recent_history": {
            "chat": scrub_memory(redact_payload(read_json(DATA_DIR / "chat_history.json", [])[-MEMORY_ITEM_LIMIT:])),
            "telegram_legacy": scrub_memory(redact_payload(read_json(DATA_DIR / "telegram_chat_history.json", {}))),
            "telegram_gateway": scrub_memory(redact_payload(read_json(DATA_DIR / "hermes_gateway_recent_turns.json", [])[-(MEMORY_ITEM_LIMIT * 4):])),
            "actions": scrub_memory(redact_payload(read_json(DATA_DIR / "actions.json", [])[-MEMORY_ITEM_LIMIT:])),
            "pending_approvals": scrub_memory(redact_payload(read_json(DATA_DIR / "pending_approvals.json", [])[-MEMORY_ITEM_LIMIT:])),
            "creative_refreshes": scrub_memory(redact_payload(read_json(ROOT_DIR / "output" / "creatives" / "index.json", [])[-MEMORY_ITEM_LIMIT:])),
        },
        "profitability_memory": scrub_memory(redact_payload(decision_memory_payload())),
        "creative_experiments": scrub_memory(redact_payload(experiment_review_payload())),
        "optimization_state": scrub_memory(redact_payload(load_optimization_state())),
        "business_outcomes": scrub_memory(redact_payload(read_json(DATA_DIR / "business_outcomes.json", {}))),
        "optimization_research": scrub_memory(redact_payload(load_research())),
    }
    memory["latest_day_context"] = latest_day_context_payload(memory)
    memory["active_workflow"] = active_workflow_payload(memory, memory["latest_day_context"])
    return memory


def has_meaningful_memory(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float, bool)):
        return bool(value)
    if isinstance(value, list):
        return any(has_meaningful_memory(item) for item in value)
    if isinstance(value, dict):
        return any(has_meaningful_memory(item) for item in value.values())
    return True


def _text_excerpt(value, limit=900):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _json_excerpt(value, limit=1600):
    clean = scrub_memory(redact_payload(value))
    try:
        text = json.dumps(clean, ensure_ascii=False, indent=2)
    except TypeError:
        text = str(clean)
    return _text_excerpt(text, limit)


def _redact_text(value):
    text = str(value or "")
    if not text:
        return ""
    replacements = [
        (r"\b(?:EA[A-Za-z0-9_-]{40,}|EAA[A-Za-z0-9_-]{40,})\b", "[redacted-token]"),
        (r"\bdop_v1_[A-Za-z0-9_-]{40,}\b", "[redacted-token]"),
        (r"\bsk-[A-Za-z0-9_-]{24,}\b", "[redacted-token]"),
        (r"(?i)\b(passphrase|password|contraseña|token|api key|access token)\s*[:=]\s*\S+", r"\1: [redacted]"),
    ]
    clean = text
    for pattern, replacement in replacements:
        clean = re.sub(pattern, replacement, clean)
    return clean


def _continuity_timezone():
    raw = (
        os.environ.get("HERMES_TIMEZONE")
        or os.environ.get("DAILY_BRIEF_TIMEZONE")
        or os.environ.get("META_DAILY_BRIEF_TIMEZONE")
        or os.environ.get("TZ")
        or "UTC"
    )
    name = str(raw or "UTC").strip() or "UTC"
    if ZoneInfo is not None:
        try:
            return name, ZoneInfo(name)
        except Exception:
            pass
    return "UTC", timezone.utc


def _parse_datetime(value):
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00") if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _append_timeline_item(items, source, role, content, created_at="", kind="message", extra=None):
    text = _redact_text(_text_excerpt(content, 1400))
    if not text:
        return
    dt = _parse_datetime(created_at) or datetime.now(timezone.utc)
    timezone_name, tz = _continuity_timezone()
    local_dt = dt.astimezone(tz)
    items.append(
        {
            "source": source,
            "role": role,
            "kind": kind,
            "content": text,
            "created_at": dt.isoformat(),
            "local_date": local_dt.date().isoformat(),
            "local_time": local_dt.strftime("%H:%M"),
            "timezone": timezone_name,
            **(extra or {}),
        }
    )


def _history_list_items(raw, source):
    items = []
    if isinstance(raw, dict):
        iterable = []
        for chat_id, history in raw.items():
            if isinstance(history, list):
                for item in history:
                    if isinstance(item, dict):
                        iterable.append({**item, "_chat_id": str(chat_id)})
    elif isinstance(raw, list):
        iterable = [item for item in raw if isinstance(item, dict)]
    else:
        iterable = []
    for item in iterable:
        role = "agent" if str(item.get("role") or "").lower() in {"agent", "assistant"} else "user"
        content = item.get("content") or item.get("message") or item.get("text") or item.get("reply") or ""
        _append_timeline_item(
            items,
            source=source,
            role=role,
            content=content,
            created_at=item.get("created_at") or item.get("updated_at") or item.get("timestamp"),
            extra={"chat_id": item.get("_chat_id", "")} if item.get("_chat_id") else None,
        )
    return items


def _activity_items(memory):
    recent = memory.get("recent_history") or {}
    items = []
    items.extend(_history_list_items(recent.get("chat"), "dashboard_chat"))
    items.extend(_history_list_items(recent.get("telegram_legacy"), "telegram_legacy"))
    items.extend(_history_list_items(recent.get("telegram_gateway"), "telegram_gateway"))
    for action in recent.get("actions") or []:
        if not isinstance(action, dict):
            continue
        summary = {
            "type": action.get("type") or action.get("action") or action.get("tool"),
            "status": action.get("status"),
            "payload": action.get("payload") or action.get("request") or action.get("result") or {},
        }
        _append_timeline_item(
            items,
            source="protected_actions",
            role="system",
            kind="action",
            content=_json_excerpt(summary, 1200),
            created_at=action.get("created_at") or action.get("timestamp") or action.get("updated_at"),
        )
    for approval in recent.get("pending_approvals") or []:
        if not isinstance(approval, dict):
            continue
        _append_timeline_item(
            items,
            source="pending_approvals",
            role="system",
            kind="approval",
            content=_json_excerpt(approval, 1200),
            created_at=approval.get("created_at") or approval.get("updated_at") or approval.get("timestamp"),
        )
    for creative in recent.get("creative_refreshes") or []:
        if not isinstance(creative, dict):
            continue
        _append_timeline_item(
            items,
            source="creative_outputs",
            role="system",
            kind="creative",
            content=_json_excerpt(creative, 1200),
            created_at=creative.get("created_at") or creative.get("updated_at") or creative.get("timestamp"),
        )
    return sorted(items, key=lambda item: item.get("created_at") or "")


def latest_day_context_payload(memory, lookback_days=RECENT_CONTEXT_LOOKBACK_DAYS):
    timezone_name, tz = _continuity_timezone()
    items = _activity_items(memory)
    recent = memory.get("recent_history") or {}
    today = datetime.now(timezone.utc).astimezone(tz).date()
    selected_date = ""
    selected_items = []
    for offset in range(max(1, int(lookback_days))):
        candidate = (today - timedelta(days=offset)).isoformat()
        matches = [item for item in items if item.get("local_date") == candidate]
        if matches:
            selected_date = candidate
            selected_items = matches[-RECENT_CONTEXT_ITEM_LIMIT:]
            break
    if not selected_items and items:
        recent_cutoff = today - timedelta(days=max(1, int(lookback_days)) - 1)
        recent_items = [item for item in items if item.get("local_date", "0000-00-00") >= recent_cutoff.isoformat()]
        if recent_items:
            selected_date = recent_items[-1].get("local_date") or ""
            selected_items = [item for item in recent_items if item.get("local_date") == selected_date][-RECENT_CONTEXT_ITEM_LIMIT:]
    return {
        "selected_date": selected_date,
        "timezone": timezone_name,
        "lookback_days": lookback_days,
        "items": selected_items,
        "item_count": len(selected_items),
        "source_counts": {
            "dashboard_chat": len(recent.get("chat") or []),
            "telegram_legacy": sum(len(value) for value in (recent.get("telegram_legacy") or {}).values()) if isinstance(recent.get("telegram_legacy"), dict) else len(recent.get("telegram_legacy") or []),
            "telegram_gateway": len(recent.get("telegram_gateway") or []),
            "actions": len(recent.get("actions") or []),
            "pending_approvals": len(recent.get("pending_approvals") or []),
            "creative_outputs": len(recent.get("creative_refreshes") or []),
        },
    }


def _latest_by_role(items, role):
    for item in reversed(items or []):
        if item.get("role") == role:
            return item
    return {}


def _infer_next_step(memory, latest_context, blocker=""):
    recent = memory.get("recent_history") or {}
    pending = recent.get("pending_approvals") or []
    onboarding_plan = str(memory.get("onboarding_plan") or "")
    if pending:
        return "Revisar la aprobación pendiente más reciente y permitir aprobar/rechazar desde Telegram."
    if blocker:
        return "Retomar el bloqueo técnico o de datos más reciente y explicar el siguiente intento seguro."
    match = re.search(r"Siguiente paso\s*:\s*([^\n.]+)", onboarding_plan, re.IGNORECASE)
    if match:
        return _text_excerpt(match.group(1), 260)
    last_agent = _latest_by_role(latest_context.get("items") or [], "agent")
    if str(last_agent.get("content") or "").strip().endswith("?"):
        return "Responder la última pregunta pendiente antes de avanzar."
    if memory.get("brand_guides", {}).get("ad_briefs"):
        return "Continuar desde el brief guardado y preparar la siguiente acción creativa o de campaña."
    if memory.get("brand_guides", {}).get("general_branding"):
        return "Continuar desde la marca guardada y completar producto/oferta, brief o campaña según el pedido."
    if has_meaningful_memory(memory.get("business_profile")):
        return "Continuar el onboarding desde la memoria de negocio ya guardada."
    return ""


def active_workflow_payload(memory, latest_context):
    items = latest_context.get("items") or []
    recent = memory.get("recent_history") or {}
    pending = recent.get("pending_approvals") or []
    blockers = [
        item
        for item in reversed(items)
        if re.search(r"(?i)\b(error|fall[óo]|bloque|missing|falta|rate limit|timeout|not logged|page_not_found|creative_production_not_ready)\b", item.get("content") or "")
    ]
    blocker = blockers[0] if blockers else {}
    brand = memory.get("brand_guides") or {}
    if pending:
        phase = "approval"
    elif blocker:
        phase = "blocked_or_retrying"
    elif recent.get("creative_refreshes"):
        phase = "creative_review"
    elif brand.get("ad_briefs"):
        phase = "creative_or_campaign_brief"
    elif brand.get("general_branding"):
        phase = "brand_ready"
    elif has_meaningful_memory(memory.get("business_profile")):
        phase = "business_onboarding"
    else:
        phase = ""
    next_step = _infer_next_step(memory, latest_context, blocker.get("content", ""))
    return {
        "has_active_workflow": bool(phase or items or pending),
        "phase": phase,
        "last_day_context_date": latest_context.get("selected_date", ""),
        "last_user_message": _latest_by_role(items, "user"),
        "last_agent_message": _latest_by_role(items, "agent"),
        "recent_blocker": blocker,
        "pending_approval_count": len(pending),
        "next_step": next_step,
        "resume_instruction": "If has_active_workflow is true, resume this workflow before greeting or restarting onboarding.",
    }


def build_latest_day_context(latest_context, active_workflow):
    lines = [
        "# Latest day context",
        "",
        "This file summarizes the most recent local day with buyer activity. Use it after history cleanup, gateway restart, update, or a fresh runtime session.",
        f"Timezone: {latest_context.get('timezone', 'UTC')}",
        f"Lookback days: {latest_context.get('lookback_days', RECENT_CONTEXT_LOOKBACK_DAYS)}",
        f"Latest local activity day: {latest_context.get('selected_date') or 'none'}",
        "",
    ]
    if latest_context.get("items"):
        lines.extend(["## Timeline", ""])
        for item in latest_context.get("items", []):
            role = item.get("role", "system")
            source = item.get("source", "")
            when = f"{item.get('local_date', '')} {item.get('local_time', '')}".strip()
            lines.append(f"- {when} [{source}/{role}]: {_text_excerpt(item.get('content'), 420)}")
        lines.append("")
    else:
        lines.extend(["## Timeline", "", "- No chat/action activity found in the recent lookback window.", ""])
    lines.extend(
        [
            "## Active workflow",
            "",
            f"- Phase: {active_workflow.get('phase') or 'none'}",
            f"- Pending approvals: {active_workflow.get('pending_approval_count', 0)}",
            f"- Next step: {active_workflow.get('next_step') or 'Use durable business/brand memory and ask one necessary question.'}",
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def conversation_continuity_status(memory):
    brand = memory.get("brand_guides") or {}
    recent = memory.get("recent_history") or {}
    latest_context = memory.get("latest_day_context") or {}
    active_workflow = memory.get("active_workflow") or {}
    communication_style = communication_style_from_environment()
    ad_experience = ad_experience_from_environment()
    operator_preference_saved = bool(str(os.environ.get("AGENT_COMMUNICATION_STYLE") or "").strip()) or bool(ad_experience)
    sources = {
        "business_profile": has_meaningful_memory(memory.get("business_profile")),
        "onboarding_questions": has_meaningful_memory(memory.get("onboarding_questions")),
        "onboarding_plan": has_meaningful_memory(memory.get("onboarding_plan")),
        "ads_campaign_onboarding": has_meaningful_memory(memory.get("ads_onboarding")),
        "audience_strategy": has_meaningful_memory(memory.get("audience_strategy")),
        "general_branding": has_meaningful_memory(brand.get("general_branding")),
        "creative_references": has_meaningful_memory(memory.get("creative_references")),
        "product_guides": has_meaningful_memory(brand.get("products")),
        "ad_briefs": has_meaningful_memory(brand.get("ad_briefs")),
        "latest_day_context": bool(latest_context.get("selected_date")),
        "active_workflow": bool(active_workflow.get("has_active_workflow")),
        "telegram_gateway_turns": has_meaningful_memory(recent.get("telegram_gateway")),
        "telegram_legacy_history": has_meaningful_memory(recent.get("telegram_legacy")),
        "recent_actions": has_meaningful_memory(recent.get("actions")),
        "pending_approvals": has_meaningful_memory(recent.get("pending_approvals")),
        "recent_creative_outputs": has_meaningful_memory(recent.get("creative_refreshes")),
        "creative_experiments": has_meaningful_memory(memory.get("creative_experiments")),
        "business_outcomes": has_meaningful_memory(memory.get("business_outcomes")),
        "operator_preferences": operator_preference_saved,
    }
    resume_sources = {key: value for key, value in sources.items() if key != "operator_preferences"}
    has_persistent_memory = any(resume_sources.values())
    return {
        "has_persistent_memory": has_persistent_memory,
        "has_saved_operator_preferences": operator_preference_saved,
        "resume_required": has_persistent_memory,
        "session_history_is_cache": True,
        "instructions": {
            "on_history_cleanup_or_gateway_restart": "read durable workspace files before greeting; resume from latest-day context, active workflow, saved business, brand, brief, actions, and experiment memory",
            "if_has_persistent_memory": "do not restart onboarding, do not introduce yourself as first time, and do not repeat the ads-experience question unless it is genuinely missing after checking memory",
            "if_no_persistent_memory": "a first onboarding greeting is acceptable",
        },
        "sources": sources,
        "counts": {
            "product_guides": len(brand.get("products") or []),
            "ad_briefs": len(brand.get("ad_briefs") or []),
            "recent_actions": len(recent.get("actions") or []),
            "telegram_gateway_turns": len(recent.get("telegram_gateway") or []),
            "pending_approvals": len(recent.get("pending_approvals") or []),
            "recent_creative_outputs": len(recent.get("creative_refreshes") or []),
        },
        "latest_day_context": {
            "selected_date": latest_context.get("selected_date", ""),
            "timezone": latest_context.get("timezone", ""),
            "item_count": latest_context.get("item_count", 0),
        },
        "active_workflow": {
            "has_active_workflow": bool(active_workflow.get("has_active_workflow")),
            "phase": active_workflow.get("phase", ""),
            "next_step": active_workflow.get("next_step", ""),
        },
        "operator_preferences": {
            "communication_style": communication_style,
            "ad_experience_level": ad_experience,
        },
    }


def build_conversation_continuity(memory, status=None):
    status = status or conversation_continuity_status(memory)
    brand = memory.get("brand_guides") or {}
    recent = memory.get("recent_history") or {}
    latest_context = memory.get("latest_day_context") or {}
    active_workflow = memory.get("active_workflow") or {}
    lines = [
        "# Conversation continuity",
        "",
        "This file is the recovery brief for Telegram/Hermes history cleanup, gateway restarts, updates, or a brand-new runtime session.",
        f"Persistent memory found: {'yes' if status.get('has_persistent_memory') else 'no'}",
        "",
    ]
    if status.get("has_persistent_memory"):
        lines.extend(
            [
                "## Resume behavior",
                "",
                "- Treat Telegram/Hermes session history as cache. These durable workspace files are the source of truth after cleanup or updates.",
                "- Before sending a first message, read this file plus `memory/latest_day_context.md`, `memory/active_workflow.json`, `CURRENT_CONTEXT.json`, `data/business_profile.json`, `memory/Agent onboarding plan.md`, `memory/Ads campaign onboarding.md`, `memory/recent_actions.json`, `memory/pending_approvals.json`, `memory/creative_experiments.json`, and relevant `brand_guides/` files.",
                "- Do not restart onboarding, do not introduce yourself as if this were the first conversation, and do not repeat the initial ads-experience/technical-style question if it is already configured or implied by saved memory.",
                "- If the current Hermes session is empty but this file says memory exists, say briefly that you are resuming and continue from the next missing or active item.",
                "- If needed, use session search to look for the previous Telegram session, but never block the buyer on that search when durable workspace memory is enough to continue.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## First-run behavior",
                "",
                "- No durable business/brand/ad memory was found. A normal first onboarding greeting is acceptable.",
                "",
            ]
        )
    lines.extend(
        [
            "## Source checklist",
            "",
            *[f"- {name}: {'yes' if found else 'no'}" for name, found in (status.get("sources") or {}).items()],
            "",
        ]
    )
    if latest_context.get("selected_date"):
        lines.extend(
            [
                "## Latest day context",
                "",
                f"- Latest local activity day: {latest_context.get('selected_date')} ({latest_context.get('timezone', 'UTC')})",
                f"- Activity items in that day: {latest_context.get('item_count', 0)}",
                "",
            ]
        )
    if active_workflow.get("has_active_workflow"):
        last_user = active_workflow.get("last_user_message") or {}
        last_agent = active_workflow.get("last_agent_message") or {}
        lines.extend(
            [
                "## Active workflow",
                "",
                f"- Phase: {active_workflow.get('phase') or 'unknown'}",
                f"- Next step: {active_workflow.get('next_step') or 'continue from saved memory'}",
            ]
        )
        if last_user.get("content"):
            lines.append(f"- Last buyer message: {_text_excerpt(last_user.get('content'), 500)}")
        if last_agent.get("content"):
            lines.append(f"- Last agent message: {_text_excerpt(last_agent.get('content'), 500)}")
        lines.append("")
    if has_meaningful_memory(memory.get("business_profile")):
        lines.extend(["## Known business profile", "", "```json", _json_excerpt(memory.get("business_profile"), 2200), "```", ""])
    if has_meaningful_memory(memory.get("onboarding_plan")):
        lines.extend(["## Last known onboarding plan", "", _text_excerpt(memory.get("onboarding_plan"), 1800), ""])
    if has_meaningful_memory(memory.get("ads_onboarding")):
        lines.extend(["## Ads/campaign onboarding memory", "", _text_excerpt(memory.get("ads_onboarding"), 1800), ""])
    if has_meaningful_memory(brand.get("general_branding")):
        lines.extend(["## Brand memory", "", _text_excerpt(brand.get("general_branding"), 1800), ""])
    if has_meaningful_memory(memory.get("creative_references")):
        lines.extend(["## Creative references", "", _text_excerpt(memory.get("creative_references"), 1200), ""])
    products = brand.get("products") or []
    if products:
        lines.extend(["## Product guides", ""])
        for product in products[:MEMORY_ITEM_LIMIT]:
            lines.append(f"- `{product.get('path', 'product')}`: {_text_excerpt(product.get('content'), 700)}")
        lines.append("")
    ad_briefs = brand.get("ad_briefs") or []
    if ad_briefs:
        lines.extend(["## Ad briefs", ""])
        for ad_brief in ad_briefs[:MEMORY_ITEM_LIMIT]:
            lines.append(f"- `{ad_brief.get('path', 'ad_brief')}`: {_text_excerpt(ad_brief.get('content'), 700)}")
        lines.append("")
    if has_meaningful_memory(recent.get("actions")):
        lines.extend(["## Recent protected actions", "", "```json", _json_excerpt(recent.get("actions"), 2200), "```", ""])
    if has_meaningful_memory(recent.get("pending_approvals")):
        lines.extend(["## Pending approvals", "", "```json", _json_excerpt(recent.get("pending_approvals"), 1800), "```", ""])
    if has_meaningful_memory(recent.get("creative_refreshes")):
        lines.extend(["## Recent creative outputs", "", "```json", _json_excerpt(recent.get("creative_refreshes"), 2200), "```", ""])
    if has_meaningful_memory(memory.get("creative_experiments")):
        lines.extend(["## Creative experiment checkpoints", "", "```json", _json_excerpt(memory.get("creative_experiments"), 2200), "```", ""])
    lines.extend(
        [
            "## Safe next-message pattern",
            "",
            "When memory exists, start with something like: “Retomo donde quedamos: ya tengo [one concrete remembered item]. Lo siguiente es [next useful step].” Then ask only one clear question if needed.",
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def prepare_hermes_workspace(payload):
    memory = business_memory_context()
    continuity_status = conversation_continuity_status(memory)
    if HERMES_WORKSPACE_DIR.exists():
        shutil.rmtree(HERMES_WORKSPACE_DIR)
    HERMES_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    written = write_agent_profile_workspace_files()
    written.append(
        write_workspace_file(
            "README.md",
            """# Hermes Workspace

This folder is the only workspace Hermes should read for this product turn.
It contains curated business memory, brand guides, recent activity, and uploaded reference images.

Hermes owns the conversation and should use its own session memory. The backend does not paste the whole chat history into the prompt.
Before every buyer-facing turn, read `skills/core-agent-behavior/SKILL.md`. If session memory was cleaned, the gateway restarted, or an update created a fresh runtime session, also read `skills/session-continuity/SKILL.md`, `memory/Conversation continuity.md`, `memory/continuity_status.json`, `memory/latest_day_context.md`, `memory/active_workflow.json`, `CURRENT_CONTEXT.json`, `data/business_profile.json`, `memory/Agent onboarding plan.md`, `memory/Ads campaign onboarding.md`, and relevant `brand_guides/` files before greeting.

Never expose this workspace's internal paths to the buyer. If the buyer asks for a prompt, plan, script, copy, or diagnosis, paste the useful content directly in the chat instead of pointing them to `/app/...`, `dashboard/data/...`, `hermes-workspace/...`, `brand_guides/...`, `memory/...`, or `CURRENT_CONTEXT.json`.

Do not request files outside this workspace. If something is missing, ask the buyer or request a backend tool.

Product actions are exposed as Hermes MCP tools with names starting with `mcp_admira_`.
Read `skills/README.md`, then the relevant `skills/*/SKILL.md` file before acting.
""",
        )
    )
    written.append(
        write_workspace_file(
            "CURRENT_CONTEXT.json",
            scrub_memory(
                redact_payload(
                    {
                        "channel": payload.get("channel") or "dashboard",
                        "language": payload.get("language") or "",
                        "account_context": payload.get("account_context") or {},
                        "image_paths": safe_image_paths(payload),
                    }
                )
            ),
        )
    )
    written.append(write_workspace_file("data/business_profile.json", memory["business_profile"]))
    written.append(write_workspace_file("memory/continuity_status.json", continuity_status))
    written.append(write_workspace_file("memory/Conversation continuity.md", build_conversation_continuity(memory, continuity_status)))
    written.append(write_workspace_file("memory/latest_day_context.md", build_latest_day_context(memory["latest_day_context"], memory["active_workflow"])))
    written.append(write_workspace_file("memory/active_workflow.json", memory["active_workflow"]))
    written.append(write_workspace_file("memory/Onboarding questions.md", memory.get("onboarding_questions", "")))
    written.append(write_workspace_file("memory/Agent onboarding plan.md", memory.get("onboarding_plan", "")))
    written.append(write_workspace_file("memory/Ads campaign onboarding.md", memory.get("ads_onboarding", "")))
    written.append(write_workspace_file("data/audience_strategy.json", memory["audience_strategy"]))
    written.append(write_workspace_file("data/business_binding.json", memory["business_binding"]))
    written.append(write_workspace_file("memory/recent_actions.json", memory["recent_history"]["actions"]))
    written.append(write_workspace_file("memory/recent_telegram_gateway_turns.json", memory["recent_history"].get("telegram_gateway", [])))
    written.append(write_workspace_file("memory/pending_approvals.json", memory["recent_history"].get("pending_approvals", [])))
    written.append(write_workspace_file("memory/creative_refreshes.json", memory["recent_history"]["creative_refreshes"]))
    written.append(write_workspace_file("memory/profitability_rules.json", memory["profitability_memory"].get("profitability_rules", {})))
    written.append(write_workspace_file("memory/decision_memory.json", memory["profitability_memory"]))
    written.append(write_workspace_file("memory/creative_experiments.json", memory["creative_experiments"]))
    written.append(write_workspace_file("memory/optimization_state.json", memory["optimization_state"]))
    written.append(write_workspace_file("memory/business_outcomes.json", memory["business_outcomes"]))
    written.append(write_workspace_file("memory/optimization_research.json", memory["optimization_research"]))
    written.append(write_workspace_file("memory/learning_log.md", format_learning_log()))
    written.append(write_workspace_file("brand_guides/general_branding.md", memory["brand_guides"]["general_branding"]))
    written.append(write_workspace_file("brand_guides/creative_references.md", memory.get("creative_references", "")))
    for product in memory["brand_guides"]["products"]:
        name = Path(product["path"]).name
        written.append(write_workspace_file(f"brand_guides/products/{name}", product["content"]))
    for ad_brief in memory["brand_guides"].get("ad_briefs", []):
        name = Path(ad_brief["path"]).name
        written.append(write_workspace_file(f"brand_guides/ad_briefs/{name}", ad_brief["content"]))
    workspace_images = []
    for image_path in safe_image_paths(payload):
        workspace_images.append(copy_workspace_file(image_path, "uploads"))
    return {
        "path": str(HERMES_WORKSPACE_DIR),
        "files": written,
        "image_paths": workspace_images,
        "memory": memory,
        "continuity_status": continuity_status,
        "active_workflow": memory["active_workflow"],
        "latest_day_context": memory["latest_day_context"],
    }


def hermes_session_name(payload):
    if not payload.get("channel"):
        return ""
    channel = str(payload.get("channel") or "").strip().lower()
    if channel == "telegram":
        raw_key = str(payload.get("session_key") or "default")
        digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:12]
        return f"meta-ads-agent-telegram-{digest}"
    if channel == "dashboard":
        return "meta-ads-agent-dashboard"
    return ""


def hermes_session_source(payload):
    channel = str(payload.get("channel") or "").strip().lower()
    if channel == "telegram":
        return "meta-ads-agent-telegram"
    if channel == "dashboard":
        return "meta-ads-agent-dashboard"
    return "meta-ads-agent"


def hermes_user_query(payload, workspace_info):
    message = str(payload.get("message") or "").strip()
    if not message:
        return ""
    channel = str(payload.get("channel") or "dashboard").strip().lower()
    if channel in {"telegram", "dashboard"}:
        return (
            f"{message}\n\n"
            "Nota de sistema del producto: el contexto actual de la cuenta está en `CURRENT_CONTEXT.json`. "
            "Usa ese archivo y tu memoria de sesión solo si hace falta para responder o preparar una acción. "
            "Si el mensaje incluye una URL pública o un enlace de Google Drive para usar como creativo, usa mcp_admira_fetch_public_asset antes de decir que no puedes acceder; después usa web/browser si hace falta investigación adicional. "
            "Si el comprador pide crear o preparar campaña, usa las herramientas MCP de Admira cuando estén disponibles. "
            "Si estás en un contexto sin MCP, devuelve el JSON tool_request del producto. No digas que necesitas terminal o CLI."
        )
    return (
        f"{message}\n\n"
        "Nota de sistema del producto: usa solo los archivos de este workspace y las reglas de `AGENTS.md`. "
        "No necesitas historial acumulado para esta tarea puntual."
    )


def hermes_environment(config):
    env = os.environ.copy()
    timezone_name = str(getattr(config, "daily_brief_timezone", "UTC") or "UTC")
    # Hermes' scheduler resolves wall-clock time from HERMES_TIMEZONE. TZ is
    # also set for child processes and third-party tools launched by Hermes.
    env["HERMES_TIMEZONE"] = timezone_name
    env["TZ"] = timezone_name
    hermes_home = getattr(config, "hermes_home", "") or DATA_DIR / "hermes-home"
    if hermes_home:
        path = Path(str(hermes_home)).expanduser()
        if not path.is_absolute():
            path = ROOT_DIR / path
        env["HERMES_HOME"] = str(path)
        # Keep Codex/ChatGPT auth isolated to the same buyer-specific home.
        # Some Codex paths still consult CODEX_HOME; inheriting the container's
        # global value can keep an old account alive after the dashboard says it
        # was disconnected.
        env["CODEX_HOME"] = str(path)
    settings = hermes_brain_settings(config)
    minimax_settings = admira_minimax_credentials(config, settings)
    if minimax_settings.get("api_key"):
        # Do not expose Admira's official MiniMax key as MINIMAX_API_KEY.
        # Hermes treats that variable as a signal to show/use its native
        # MiniMax provider, whose transport can differ from MiniMax's official
        # OpenAI-compatible endpoint. Admira registers MiniMax M3 as a named
        # custom provider instead, so keep the key under an Admira-only env var.
        env.pop("MINIMAX_API_KEY", None)
        env[ADMIRA_MINIMAX_KEY_ENV] = minimax_settings["api_key"]
        if minimax_settings.get("base_url"):
            env[ADMIRA_MINIMAX_BASE_URL_ENV] = minimax_settings["base_url"]
        env["ADMIRA_MINIMAX_PROVIDER"] = ADMIRA_MINIMAX_PROVIDER
        env["ADMIRA_MINIMAX_MODEL"] = minimax_settings.get("model") or "MiniMax-M3"
    if settings.get("provider") == "custom" and settings.get("api_key"):
        env["OPENAI_API_KEY"] = settings["api_key"]
        if settings.get("base_url"):
            env["OPENAI_BASE_URL"] = settings["base_url"]
    return env


def admira_minimax_credentials(config, primary_settings=None):
    """Return MiniMax credentials that should be available to Hermes /model.

    MiniMax may be the primary text brain, or it may be a saved secondary API
    credential the buyer wants to select manually from Telegram with /model.
    In both cases the key must be available under Admira's custom provider env,
    otherwise Hermes can list/select MiniMax and then fail provider auth.
    """
    settings = dict(primary_settings or {})
    if settings.get("provider") == "minimax" and settings.get("api_key"):
        return {
            "api_key": str(settings.get("api_key") or "").strip(),
            "base_url": str(settings.get("base_url") or "https://api.minimax.io/v1").strip().rstrip("/"),
            "model": str(settings.get("model") or "MiniMax-M3").strip(),
        }
    api_key = str(getattr(config, "agent_chat_api_key", "") or "").strip()
    base_url = str(getattr(config, "agent_chat_base_url", "") or "").strip().rstrip("/")
    model = str(getattr(config, "agent_chat_model", "") or "").strip()
    brain = str(getattr(config, "agent_brain_provider", "") or "").strip().lower().replace("-", "_")
    looks_like_minimax = (
        brain in {"minimax", "minimax_m3"}
        or "minimax" in base_url.lower()
        or "minimax" in model.lower()
    )
    if api_key and looks_like_minimax:
        return {
            "api_key": api_key,
            "base_url": base_url or "https://api.minimax.io/v1",
            "model": model or "MiniMax-M3",
        }
    env_key = os.environ.get(ADMIRA_MINIMAX_KEY_ENV, "").strip()
    if env_key:
        return {
            "api_key": env_key,
            "base_url": os.environ.get(ADMIRA_MINIMAX_BASE_URL_ENV, "https://api.minimax.io/v1").strip().rstrip("/") or "https://api.minimax.io/v1",
            "model": os.environ.get("ADMIRA_MINIMAX_MODEL", "MiniMax-M3").strip() or "MiniMax-M3",
        }
    return {}


def hermes_brain_settings(config):
    brain = str(getattr(config, "agent_brain_provider", "") or "").strip().lower().replace("-", "_")
    if not brain:
        legacy = str(getattr(config, "agent_chat_provider", "") or "").strip().lower().replace("-", "_")
        if legacy == "minimax":
            brain = "minimax"
        elif legacy in {"openai", "openai_compatible"}:
            base = str(getattr(config, "agent_chat_base_url", "") or "")
            brain = "openai_api" if "api.openai.com" in base else "custom_api"
        else:
            brain = "openai_codex"
    if brain in {"chatgpt", "chatgpt_subscription", "codex", "openai_codex", "hermes"}:
        return {
            "brain": "openai_codex",
            "provider": "openai-codex",
            "model": normalize_hermes_model(getattr(config, "hermes_model", "")),
            "base_url": "",
            "api_key": "",
            "requires_codex_auth": True,
        }
    if brain in {"minimax", "minimax_m3"}:
        return {
            "brain": "minimax",
            "provider": "minimax",
            "model": str(getattr(config, "agent_chat_model", "") or "MiniMax-M3").strip(),
            "base_url": str(getattr(config, "agent_chat_base_url", "") or "https://api.minimax.io/v1").strip().rstrip("/"),
            "api_key": str(getattr(config, "agent_chat_api_key", "") or "").strip(),
            "requires_codex_auth": False,
        }
    if brain in {"openai", "openai_api"}:
        return {
            "brain": "openai_api",
            "provider": "custom",
            "model": str(getattr(config, "agent_chat_model", "") or "gpt-4.1-mini").strip(),
            "base_url": str(getattr(config, "agent_chat_base_url", "") or "https://api.openai.com/v1").strip().rstrip("/"),
            "api_key": str(getattr(config, "agent_chat_api_key", "") or "").strip(),
            "requires_codex_auth": False,
        }
    return {
        "brain": "custom_api",
        "provider": "custom",
        "model": str(getattr(config, "agent_chat_model", "") or "").strip(),
        "base_url": str(getattr(config, "agent_chat_base_url", "") or "").strip().rstrip("/"),
        "api_key": str(getattr(config, "agent_chat_api_key", "") or "").strip(),
        "requires_codex_auth": False,
    }


def hermes_brain_ready(config):
    settings = hermes_brain_settings(config)
    if settings["requires_codex_auth"]:
        ready, detail = hermes_codex_ready(config)
        return ready, detail
    missing = []
    if not settings.get("api_key"):
        missing.append("API key")
    if not settings.get("model"):
        missing.append("model")
    if settings.get("provider") == "custom" and not settings.get("base_url"):
        missing.append("base URL")
    if missing:
        return False, "Missing " + ", ".join(missing)
    label = settings["brain"].replace("_", " ")
    return True, f"{label} configured inside Hermes"


def setup_reply(language="es"):
    if language == "es":
        return (
            "Todavia falta conectar el cerebro del agente. Abre Configuracion > Conectar ChatGPT o modelo API "
            "para terminar el paso guiado. En PC/Mac se abre la terminal; en VPS/DigitalOcean el dashboard "
            "muestra el login desde el navegador."
        )
    return (
        "The agent brain is not connected yet. Open Setup > Connect ChatGPT or API model for guided steps. "
        "On desktop it can open a terminal; on VPS/DigitalOcean the dashboard shows the login in the browser."
    )


def model_usage_limit_error(error_text):
    return is_rate_limit_text(error_text)


def model_usage_limit_retry_hint(error_text):
    seconds = retry_seconds_from_text(error_text)
    if seconds is not None:
        return retry_delay_hint(error_text, "en")
    return textual_retry_hint(error_text)


def localized_retry_hint(hint, language="es"):
    return localized_textual_hint(hint, language)


def model_usage_limit_reply(language="es", error_text=""):
    hint = retry_delay_hint(error_text, language)
    if language == "en":
        base = (
            "ChatGPT/Codex is connected, but the model hit a temporary usage limit. "
            "I will not invent an answer or execute actions while the brain cannot respond."
        )
        model_hint = lighter_model_switch_hint("en")
        if hint:
            return f"{base} Try again after: {localized_retry_hint(hint, 'en')}. {model_hint}"
        return f"{base} Try again later; the provider did not send me an exact reset time. {model_hint}"
    base = (
        "Tu ChatGPT/Codex sí está conectado, pero el modelo alcanzó su límite temporal de uso. "
        "No voy a inventar una respuesta ni ejecutar acciones mientras el cerebro no pueda responder."
    )
    model_hint = lighter_model_switch_hint("es")
    if hint:
        return f"{base} Puedes intentar de nuevo en {localized_retry_hint(hint, 'es')}. {model_hint}"
    return f"{base} Intenta de nuevo más tarde; el proveedor no me dio una hora exacta de reinicio. {model_hint}"


def extract_codex_account_identity(text):
    """Best-effort extraction of the connected ChatGPT/Codex account label."""
    raw = str(text or "")
    email_match = re.search(r"[\w.!#$%&'*+/=?^_`{|}~-]+@[\w-]+(?:\.[\w-]+)+", raw)
    email = email_match.group(0) if email_match else ""
    if email:
        return {"email": email, "label": email, "visible": True}
    for pattern in (
        r"(?:logged\s+in\s+as|signed\s+in\s+as|account)\s*[:=-]?\s*([^\n;]+)",
        r"(?:usuario|cuenta)\s*[:=-]?\s*([^\n;]+)",
    ):
        match = re.search(pattern, raw, re.IGNORECASE)
        if match:
            label = re.sub(r"\s+", " ", match.group(1)).strip(" .;:-")
            if label and "unknown" not in label.lower() and "not logged" not in label.lower():
                return {"email": "", "label": label[:140], "visible": True}
    return {"email": "", "label": "", "visible": False}


CODEX_AUTH_NEGATIVE_PARTS = (
    "not logged",
    "logged out",
    "auth unknown",
    "unknown",
    "login required",
    "missing",
    "unauthorized",
    "401",
    "error:",
    "failed",
)
CODEX_AUTH_POSITIVE_PARTS = ("logged in", "signed in", "authenticated")
CODEX_AUTH_POSITIVE_MARKS = ("\u2713", "\u2714", "✅")


def codex_auth_line_is_logged_in(line):
    """Return True only for a positive OpenAI Codex auth signal."""
    text = str(line or "").strip()
    lower = text.lower()
    if not text or "openai codex" not in lower:
        return False
    if any(part in lower for part in CODEX_AUTH_NEGATIVE_PARTS):
        return False
    return any(part in lower for part in CODEX_AUTH_POSITIVE_PARTS) or any(mark in text for mark in CODEX_AUTH_POSITIVE_MARKS)


def codex_auth_line_from_status(output):
    lines = [line.strip() for line in str(output or "").splitlines() if line.strip()]
    explicit = next((line for line in lines if "openai codex" in line.lower() and "provider:" not in line.lower()), "")
    if explicit:
        return explicit
    provider_line = next((line for line in lines if "provider:" in line.lower() and "openai codex" in line.lower()), "")
    return provider_line if codex_auth_line_is_logged_in(provider_line) else ""


def hermes_codex_session_status(config, timeout=None):
    hermes_cli = shutil.which(getattr(config, "hermes_cli", "hermes") or "hermes")
    if not hermes_cli:
        return {"ready": False, "detail": "Hermes not installed", "identity": extract_codex_account_identity("")}
    if timeout is None:
        status_timeout = max(8, min(45, int(getattr(config, "hermes_status_timeout_seconds", 20) or 20)))
    else:
        try:
            status_timeout = max(1, min(45, int(timeout)))
        except (TypeError, ValueError):
            status_timeout = 5
    try:
        completed = subprocess.run(
            [hermes_cli, "status"],
            cwd=str(ROOT_DIR),
            env=hermes_environment(config),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=status_timeout,
            check=False,
        )
    except Exception as exc:
        detail = f"Could not check Hermes status: {exc}"
        return {"ready": False, "detail": detail, "identity": extract_codex_account_identity(detail)}
    output = (completed.stdout or "") + "\n" + (completed.stderr or "")
    provider_line = next((line.strip() for line in output.splitlines() if "Provider:" in line), "")
    codex_line = codex_auth_line_from_status(output)
    provider_ok = "codex" in provider_line.lower() or "openai codex" in provider_line.lower()
    codex_ok = codex_auth_line_is_logged_in(codex_line)
    detail = f"{provider_line or 'Provider unknown'}; {codex_line or 'OpenAI Codex auth unknown'}"
    return {
        "ready": provider_ok and codex_ok,
        "authenticated": codex_ok,
        "provider_ready": provider_ok and codex_ok,
        "detail": detail,
        "identity": extract_codex_account_identity(output or detail),
        "returncode": completed.returncode,
    }


def hermes_codex_ready(config):
    status = hermes_codex_session_status(config)
    return bool(status.get("ready")), status.get("detail", "")


def hermes_prompt(config, payload, workspace_info=None):
    language = payload.get("language", "")
    context = payload.get("account_context") or {}
    workspace_info = workspace_info or prepare_hermes_workspace(payload)
    images = workspace_info.get("image_paths") or []
    image_note = ""
    if images:
        image_note = (
            "\n\nUploaded reference images:\n"
            + "\n".join(f"- {path}" for path in images)
            + "\nThe first image is attached to Hermes directly when the CLI supports it. Use vision to understand the image. "
            + "If you request `codex_creative_plan` or `codex_image_generate`, include a concise visual summary in the request arguments; do not rely on Codex reading arbitrary local files."
        )
    system_prompt = build_system_prompt(config, language)
    return (
        system_prompt
        + "\n\nHermes workspace path:\n"
        + str(workspace_info.get("path", ""))
        + "\n\nHermes workspace files:\n"
        + "\n".join(f"- {path}" for path in workspace_info.get("files", []))
        + "\n\nRead product rules from AGENTS.md/SOUL.md and business files only inside this workspace. Do not read arbitrary local files. If a needed file is missing, ask the buyer or request a backend tool."
        + "\n\nTurn orientation before every reply: read `skills/core-agent-behavior/SKILL.md`, then silently identify the buyer's immediate goal, where we were in the current workflow, what has already been done/saved/attempted, what is still missing or blocked, and the next safest useful action. Do not answer isolated from the previous context; continue the active work unless the buyer clearly changes topic."
        + "\n\nBefore treating this as a new conversation, read `skills/session-continuity/SKILL.md`, `memory/Conversation continuity.md`, `memory/continuity_status.json`, `memory/latest_day_context.md`, `memory/active_workflow.json`, `CURRENT_CONTEXT.json`, `data/business_profile.json`, `memory/Agent onboarding plan.md`, `memory/Ads campaign onboarding.md`, `memory/recent_actions.json`, `memory/pending_approvals.json`, and relevant `brand_guides/` files. If persistent memory or active workflow exists, resume from durable business/brand/ad memory and latest-day context instead of restarting onboarding or repeating first-time preference questions."
        + "\n\nNever expose internal workspace paths to the buyer. Do not present `MEDIA:/...` as a link or address. If a generated image/file must be delivered, use `MEDIA:<local_path>` only as a native attachment directive and keep the visible reply focused on the attached file. If the buyer asks for a prompt, plan, script, copy, or diagnosis, paste it directly in the chat instead of pointing them to `/app/...`, `dashboard/data/...`, `hermes-workspace/...`, `brand_guides/...`, `memory/...`, or `CURRENT_CONTEXT.json`."
        + "\n\nDashboard action boundary: do not say you need CLI or terminal access to create or prepare campaigns. If MCP tools are available, use the `mcp_admira_*` tools directly. If MCP is unavailable in the current runtime, use the JSON tool_request contract below or ask the next missing detail. In dashboard chat, the backend executes supported product actions and keeps spend behind approval."
        + "\n\nPublic URL/video handling: if the buyer provides a public URL, especially a Google Drive/video/image link for a creative, call mcp_admira_fetch_public_asset first. If it returns a video asset, use its video_url/direct_url for video creative staging. If it returns video_frame_paths/video_preview_frame_paths, inspect those extracted image frames with vision to understand the video visually; do not try to inspect the MP4 directly and do not say you cannot review video merely because one viewer accepts only images. Use web/browser retrieval as a secondary path for general research. If access fails because of login, private URL, robots, timeout, private/local network, size limit, or tool unavailability, say that precise reason and ask the buyer to make it public, upload it directly, or paste page text/screenshots."
        + "\n\nCurrent account context JSON:\n"
        + json.dumps(context, ensure_ascii=False)
        + image_note
        + "\n\nDo not expect full conversation history here. Hermes session memory helps continuity, but durable workspace memory is the fallback after cleanup/update/restart. Return normal helpful text for explanations. If the user asks for a product action, return this JSON contract only:\n"
        + '{"assistant_message":"short user-facing reply","tool_request":{"tool":"tool_name","arguments":{}}}\n'
        + "Approvals are allowed only when the buyer asks to approve or reject one exact pending approval ID already present in context. Use `approval_decision` with that exact ID. If ambiguous, ask which decision or show choices; never invent approval IDs.\n"
        + "If a tool stages an action for approval, tell the buyer they can approve/reject directly in Telegram with the exact approval ID or the buttons shown there. Do not say the dashboard Approvals UI is required; it is only a backup. For actions that can leave ads active and spend real money, preserve the exact active-spend confirmation phrase required by the backend.\n\n"
        + f"User message:\n{str(payload.get('message') or '')[:5000]}"
    )


def library_chat(config, payload):
    from run_agent import AIAgent

    workspace_info = prepare_hermes_workspace(payload)
    brain = hermes_brain_settings(config)
    kwargs = {
        "quiet_mode": True,
        "platform": payload.get("channel") or "dashboard",
        "max_iterations": max(1, int(getattr(config, "hermes_max_iterations", 12) or 12)),
    }
    if brain.get("provider"):
        kwargs["provider"] = brain["provider"]
    if brain.get("base_url"):
        kwargs["base_url"] = brain["base_url"]
    if brain.get("api_key"):
        kwargs["api_key"] = brain["api_key"]
    if brain.get("model"):
        kwargs["model"] = brain["model"]
    enabled = split_csv(getattr(config, "hermes_enabled_toolsets", ""))
    disabled = split_csv(getattr(config, "hermes_disabled_toolsets", ""))
    if enabled:
        kwargs["enabled_toolsets"] = enabled
    if disabled:
        kwargs["disabled_toolsets"] = disabled

    env = hermes_environment(config)
    old_home = os.environ.get("HERMES_HOME")
    old_cwd = os.getcwd()
    if "HERMES_HOME" in env:
        os.environ["HERMES_HOME"] = env["HERMES_HOME"]
    try:
        os.chdir(workspace_info["path"])
        agent = AIAgent(**kwargs)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = agent.run_conversation(
                user_message=str(payload.get("message") or "")[:5000],
                system_message=hermes_prompt(config, payload, workspace_info),
            )
        if isinstance(result, dict):
            return str(result.get("final_response") or result.get("response") or "").strip()
        return str(result or "").strip()
    finally:
        os.chdir(old_cwd)
        if old_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = old_home


def cli_chat(config, payload):
    workspace_info = prepare_hermes_workspace(payload)
    hermes_files = write_cli_hermes_config(config, workspace_info, payload)
    query = hermes_user_query(payload, workspace_info)
    images = workspace_info.get("image_paths") or []
    brain = hermes_brain_settings(config)
    hermes_cli = getattr(config, "hermes_cli", "hermes") or "hermes"
    source = hermes_session_source(payload)
    session_name = hermes_session_name(payload)

    def build_command(use_continue):
        command = [
            hermes_cli,
            "chat",
            "--quiet",
            "--source",
            source,
            "--max-turns",
            str(max(1, int(getattr(config, "hermes_max_iterations", 12) or 12))),
            "-q",
            query,
        ]
        if use_continue and session_name:
            command.extend(["--continue", session_name])
        provider = hermes_cli_provider(brain)
        if provider:
            command.extend(["--provider", provider])
        if brain.get("model"):
            command.extend(["--model", brain["model"]])
        enabled = ",".join(cli_toolsets(config, payload))
        if enabled:
            command.extend(["--toolsets", enabled])
        if images:
            command.extend(["--image", images[0]])
        return command

    def run_command(command):
        env = hermes_environment(config)
        env["HERMES_HOME"] = hermes_files["hermes_home"]
        return subprocess.run(
            command,
            cwd=workspace_info["path"],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(30, int(getattr(config, "hermes_response_timeout_seconds", getattr(config, "hermes_timeout_seconds", 300)) or 300)),
            check=False,
        )

    command = build_command(use_continue=bool(session_name))
    completed = run_command(command)
    if completed.returncode != 0 and session_name and "No session found matching" in ((completed.stderr or "") + (completed.stdout or "")):
        completed = run_command(build_command(use_continue=False))
        if completed.returncode == 0:
            name_latest_session(config, source, session_name)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "Hermes command failed").strip()[:1000])
    return (completed.stdout or "").strip()


def name_latest_session(config, source, title):
    if not title:
        return False
    hermes_cli = getattr(config, "hermes_cli", "hermes") or "hermes"
    env = hermes_environment(config)
    try:
        listed = subprocess.run(
            [hermes_cli, "sessions", "list", "--source", source, "--limit", "1"],
            cwd=str(ROOT_DIR),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
    except Exception:
        return False
    if listed.returncode != 0:
        return False
    match = re.search(r"\b(\d{8}_\d{6}_[0-9a-f]+)\b", listed.stdout or "")
    if not match:
        return False
    session_id = match.group(1)
    try:
        renamed = subprocess.run(
            [hermes_cli, "sessions", "rename", session_id, title],
            cwd=str(ROOT_DIR),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
    except Exception:
        return False
    return renamed.returncode == 0


def chat(config, payload):
    language = payload.get("language", "es")
    try:
        brain = hermes_brain_settings(config)
        if getattr(config, "hermes_require_codex_auth", True) or brain.get("requires_codex_auth"):
            ready, detail = hermes_brain_ready(config)
            if not ready:
                return {
                    "ok": False,
                    "provider": "hermes",
                    "fallback": True,
                    "reply": setup_reply(language),
                    "error": f"Hermes brain is not ready: {detail}",
                }
        elif not brain.get("requires_codex_auth"):
            ready, detail = hermes_brain_ready(config)
            if not ready:
                return {
                    "ok": False,
                    "provider": "hermes",
                    "fallback": True,
                    "reply": setup_reply(language),
                    "error": f"Hermes brain is not ready: {detail}",
                }
        images = safe_image_paths(payload)
        if images:
            reply = cli_chat(config, payload)
        elif hermes_session_name(payload):
            reply = cli_chat(config, payload)
        elif getattr(config, "hermes_use_python_library", True):
            try:
                reply = library_chat(config, payload)
            except (ImportError, ModuleNotFoundError):
                reply = cli_chat(config, payload)
            if not str(reply or "").strip():
                reply = cli_chat(config, payload)
        else:
            reply = cli_chat(config, payload)
        if not str(reply or "").strip():
            return {
                "ok": False,
                "provider": "hermes",
                "fallback": True,
                "reply": "",
                "error": "Hermes returned an empty reply",
            }
        return {"ok": True, "provider": "hermes", "brain_provider": brain.get("brain"), "model": brain.get("model") or "configured-in-hermes", "reply": reply}
    except (ImportError, ModuleNotFoundError) as exc:
        return {"ok": False, "provider": "hermes", "fallback": True, "reply": setup_reply(language), "error": f"Hermes Python library is not installed: {exc}"}
    except FileNotFoundError as exc:
        return {"ok": False, "provider": "hermes", "fallback": True, "reply": setup_reply(language), "error": f"Hermes CLI is not installed: {exc}"}
    except Exception as exc:
        error_text = str(exc)
        if model_usage_limit_error(error_text):
            return {
                "ok": False,
                "provider": "hermes",
                "fallback": True,
                "error_type": "model_usage_limit",
                "retry_after_hint": model_usage_limit_retry_hint(error_text),
                "reply": model_usage_limit_reply(language, error_text),
                "error": error_text,
            }
        return {"ok": False, "provider": "hermes", "fallback": True, "reply": setup_reply(language), "error": error_text}
