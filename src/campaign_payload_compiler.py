#!/usr/bin/env python3
"""Compile one natural-language campaign brief with a guarded model chain.

The result is candidate data only. Destination contracts and live Meta
verification remain authoritative in ``admira_tool_bridge`` and the campaign
executor.
"""
import json
import os
import re
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from codex_brand_guides import codex_cli_environment, codex_cli_error_message
from product_config import ROOT_DIR, load_config


GEMINI_COMPILER_MODELS = ("gemini-3.5-flash", "gemini-3.6-flash")
TERRA_COMPILER_MODEL = "gpt-5.6-terra"
COMPILER_MODELS = GEMINI_COMPILER_MODELS + (TERRA_COMPILER_MODEL,)
# Backwards-compatible name used by older diagnostics and tests.
COMPILER_MODEL = TERRA_COMPILER_MODEL
GEMINI_COMPILER_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_ATTEMPT_TIMEOUT_SECONDS = 60
COMPILER_DIR = ROOT_DIR / "dashboard" / "data" / "campaign-compiler"
LATEST_BRIEF_FILE = COMPILER_DIR / "latest-campaign.md"
LATEST_PAYLOAD_FILE = COMPILER_DIR / "latest-campaign-payload.json"
CONTRACT_FILE = ROOT_DIR / "agent" / "contracts" / "campaign-payload-compiler.md"
MAX_BRIEF_CHARS = 60_000

DESTINATIONS = {
    "admira_create_whatsapp_campaign": "whatsapp",
    "admira_create_lead_form_campaign": "lead_form",
    "admira_create_website_campaign": "website",
    "admira_create_messaging_campaign": "messaging",
    "admira_create_app_campaign": "app",
    "admira_create_on_meta_campaign": "on_meta",
    "create_whatsapp_campaign": "whatsapp",
    "create_lead_form_campaign": "lead_form",
    "create_website_campaign": "website",
    "create_messaging_campaign": "messaging",
    "create_app_campaign": "app",
    "create_on_meta_campaign": "on_meta",
}

DESTINATION_REQUIRED_FIELDS = {
    "whatsapp": (
        "name", "daily_budget", "budget_confirmation", "locations", "placements",
        "prefilled_message", "creative_decision", "creative_approved",
        "prefilled_message_approved",
    ),
    "lead_form": (
        "name", "daily_budget", "budget_confirmation", "locations", "placements",
        "lead_gen_form_id",
    ),
    "website": (
        "name", "daily_budget", "budget_confirmation", "locations", "placements",
        "landing_url",
    ),
    "messaging": (
        "name", "daily_budget", "budget_confirmation", "locations", "placements",
        "message_destination", "welcome_message",
    ),
    "app": (
        "name", "daily_budget", "budget_confirmation", "locations", "placements",
        "application_id", "object_store_url",
    ),
    "on_meta": (
        "name", "daily_budget", "budget_confirmation", "locations", "placements",
    ),
}


def _string(description=""):
    schema = {"type": "string"}
    if description:
        schema["description"] = description
    return schema


def _number(description=""):
    schema = {"type": "number"}
    if description:
        schema["description"] = description
    return schema


def _boolean(description=""):
    schema = {"type": "boolean"}
    if description:
        schema["description"] = description
    return schema


def destination_brief_schema(tool):
    destination = DESTINATIONS.get(str(tool or ""), "")
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "brief_markdown": {
                "type": "string",
                "minLength": 20,
                "description": (
                    f"Complete latest buyer-approved {destination or 'campaign'} campaign brief in natural Markdown. "
                    "Copy exact budget/currency, audience, placements, creative reference, copy, destination details, "
                    "and approvals from the conversation. Do not construct JSON; Terra compiles it server-side."
                ),
            },
        },
        "required": ["brief_markdown"],
    }


def _location_schema():
    return {
        "type": "array",
        "minItems": 1,
        "items": {
            "oneOf": [
                {"type": "string"},
                {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {
                        "id": _string(), "key": _string(), "name": _string(),
                        "type": _string(), "country_code": _string(),
                    },
                },
            ],
        },
    }


def _placement_schema():
    return {
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "automatic": _boolean(),
                    "manual": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["automatic"],
            },
            {"type": "array", "minItems": 1, "items": {"type": "string"}},
        ],
    }


def destination_payload_properties(destination):
    properties = {
        "name": _string("Exact campaign name."),
        "objective": _string("Destination-compatible objective."),
        "daily_budget": _number("Major account-currency units; never Meta minor units."),
        "budget_confirmation": _string("Exact amount and currency phrase copied from the buyer."),
        "budget_level": _string(),
        "creative_image_path": _string(),
        "creative_asset_id": _string(),
        "content_asset_id": _string(),
        "content_asset_ids": {"type": "array", "items": {"type": "string"}},
        "object_story_id": _string(),
        "video_path": _string(),
        "video_url": _string(),
        "video_id": _string(),
        "ads": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        "ad_sets": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        "locations": _location_schema(),
        "countries": {"type": "array", "items": {"type": "string"}},
        "age_min": {"type": "integer"},
        "age_max": {"type": "integer"},
        "genders": {"type": "array", "items": {"type": "integer"}},
        "gender": _string(),
        "placements": _placement_schema(),
        "interest_ids": {"type": "array", "items": {"type": "string"}},
        "targeting_mode": _string(),
        "primary_text": _string(),
        "headline": _string(),
        "success_metrics": {"type": "array", "items": {"type": "string"}},
    }
    extras = {
        "whatsapp": {
            "prefilled_message": _string(),
            "creative_decision": _string(),
            "creative_approved": _boolean(),
            "prefilled_message_approved": _boolean(),
        },
        "lead_form": {"lead_gen_form_id": _string()},
        "website": {"landing_url": _string()},
        "messaging": {"message_destination": _string(), "welcome_message": _string()},
        "app": {"application_id": _string(), "object_store_url": _string()},
        "on_meta": {},
    }
    properties.update(extras.get(destination, {}))
    return properties


def compiler_output_schema(tool):
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "ready": {"type": "boolean"},
            "missing_fields": {"type": "array", "items": {"type": "string"}},
            "payload_json": _string(
                "A JSON-encoded object containing only the compiled destination payload. Use '{}' when ready is false."
            ),
        },
        "required": ["ready", "missing_fields", "payload_json"],
    }


def _atomic_private_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(str(text), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)


def persist_latest_brief(tool, brief_markdown):
    destination = DESTINATIONS.get(str(tool or ""), "unknown")
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    body = (
        "# Latest campaign brief\n\n"
        f"- Destination contract: `{destination}`\n"
        f"- Received at: `{timestamp}`\n"
        "- State requested from compiler: `PAUSED`\n\n"
        "## Buyer-approved natural-language brief\n\n"
        f"{str(brief_markdown or '').strip()}\n"
    )
    _atomic_private_text(LATEST_BRIEF_FILE, body)
    return LATEST_BRIEF_FILE


def _missing_required_fields(destination, payload):
    ad_sets = payload.get("ad_sets") if isinstance(payload.get("ad_sets"), list) else []

    def supplied_per_ad_set(field):
        return bool(ad_sets) and all(
            isinstance(ad_set, dict) and ad_set.get(field) not in (None, "", [], (), {})
            for ad_set in ad_sets
        )

    missing = []
    for field in DESTINATION_REQUIRED_FIELDS.get(destination, ()):
        value = payload.get(field)
        per_set_field = field in {"locations", "placements"}
        if destination == "whatsapp" and field == "prefilled_message":
            per_set_field = True
        if value in (None, "", [], (), {}) and not (per_set_field and supplied_per_ad_set(field)):
            missing.append(field)
    return missing


def _brief_targeting_mode(brief):
    """Extract explicit audience-automation decisions from the brief.

    Audience automation and placement automation are separate Meta controls.
    This intentionally ignores bare "Advantage+ placements" wording. A
    multi-ad-set brief may intentionally contain both manual and Advantage+
    audiences; ``mixed`` tells the candidate validator to require an explicit
    mode on every ad set instead of forcing one campaign-wide value.
    """
    text = str(brief or "").strip().lower()
    manual_patterns = (
        r"\bsegmentaci[oó]n\b.{0,35}\bmanual\b",
        r"\bmanual\s+(?:audience|targeting)\b",
        r"\b(?:no|sin)\s+(?:uses?|usar|actives?|activar|expansi[oó]n)\b.{0,45}\badvantage\+?\s+(?:de\s+)?(?:audience|audiencia|p[uú]blico)\b",
        r"\b(?:audience|audiencia|p[uú]blico)\b.{0,45}\b(?:sin|no)\b.{0,20}\badvantage\+?\b",
        r"\btargeting[\s_-]*mode\s*[:=]\s*(?:manual|original|off|disabled)\b",
        r"\badvantage[\s_-]*audience\s*[:=]\s*(?:false|0|no|off)\b",
    )
    has_manual = any(re.search(pattern, text) for pattern in manual_patterns)
    advantage_patterns = (
        r"\badvantage\+?\s+(?:audience|audiencia|p[uú]blico)\b",
        r"\b(?:audience|audiencia|p[uú]blico)\s+advantage\+?\b",
    )
    explicit_advantage_patterns = (
        r"\b(?:activa|activar|activado|habilita|habilitar|habilitado|enable|enabled|usa|usar)\b.{0,55}\badvantage\+?\b.{0,30}\b(?:audience|audiencia|p[uú]blico)\b",
        r"\b(?:activa|activar|activado|habilita|habilitar|habilitado|enable|enabled|usa|usar)\b.{0,30}\b(?:audience|audiencia|p[uú]blico)\b.{0,30}\badvantage\+?\b",
        r"\badvantage\+?\s+(?:audience|audiencia|p[uú]blico)\b.{0,25}\b(?:activad[oa]|habilitad[oa]|enabled|on)\b",
        r"\btargeting[\s_-]*mode\s*[:=]\s*advantage(?:[\s_-]*plus)(?:[\s_-]*audience)?\b",
        r"\badvantage[\s_-]*audience\s*[:=]\s*(?:true|1|yes|si|sí|on)\b",
    )
    has_advantage_mention = any(re.search(pattern, text) for pattern in advantage_patterns)
    has_explicit_advantage = any(re.search(pattern, text) for pattern in explicit_advantage_patterns)
    if has_manual and has_explicit_advantage:
        return "mixed"
    if has_manual:
        return "manual"
    if has_explicit_advantage or has_advantage_mention:
        return "advantage_plus"
    return ""


def _normalize_manual_placement(value):
    token = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    aliases = {
        "facebook_stories": "facebook_story",
        "instagram_stories": "instagram_story",
        "fb_feed": "facebook_feed",
        "fb_story": "facebook_story",
        "fb_stories": "facebook_story",
        "facebook_video_feed": "facebook_video_feeds",
        "fb_video_feed": "facebook_video_feeds",
        "fb_video_feeds": "facebook_video_feeds",
        "ig_feed": "instagram_feed",
        "ig_story": "instagram_story",
        "ig_stories": "instagram_story",
        "ig_reel": "instagram_reels",
    }
    return aliases.get(token, token)


def _expand_compiled_manual_placements(values):
    """Canonicalize structured-output placement shorthand per ad set."""
    values = values if isinstance(values, list) else [values]
    normalized = [_normalize_manual_placement(value) for value in values if str(value or "").strip()]
    direct = [
        value for value in normalized
        if value in {
            "facebook_feed", "facebook_story", "facebook_reels", "facebook_video_feeds",
            "instagram_feed", "instagram_story", "instagram_reels",
            "messenger_inbox", "audience_network",
        }
    ]
    platform_aliases = {"facebook": "facebook", "fb": "facebook", "instagram": "instagram", "ig": "instagram"}
    position_aliases = {
        "feed": "feed", "feeds": "feed", "story": "story", "stories": "story",
        "reel": "reels", "reels": "reels",
    }
    platforms = [platform_aliases[value] for value in normalized if value in platform_aliases]
    positions = [position_aliases[value] for value in normalized if value in position_aliases]
    for platform in dict.fromkeys(platforms):
        for position in dict.fromkeys(positions):
            direct.append(f"{platform}_{position}")
    return list(dict.fromkeys(direct))


def _compiled_location_contract_errors(payload):
    """Reject location objects that cannot encode an exact Graph geography."""
    roots = [("locations", payload)]
    for index, ad_set in enumerate(payload.get("ad_sets") or []):
        if not isinstance(ad_set, dict):
            continue
        roots.append((f"ad_sets[{index}].locations", ad_set))
        if isinstance(ad_set.get("targeting"), dict):
            roots.append((f"ad_sets[{index}].targeting.locations", ad_set["targeting"]))
    errors = []
    for path, root in roots:
        values = root.get("locations") if isinstance(root, dict) else None
        values = values if isinstance(values, list) else ([values] if values else [])
        for item_index, item in enumerate(values):
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or item.get("id") or "").strip()
            location_type = str(item.get("type") or item.get("location_type") or "").strip().lower()
            country_code = str(item.get("country_code") or item.get("country") or "").strip().upper()
            if not key and len(country_code) == 2 and country_code.isalpha():
                key = country_code
                item["id"] = key
            if not location_type and len(key) == 2 and key.isalpha():
                location_type = "country"
                item["type"] = "country"
                item.setdefault("country_code", key.upper())
            if not key:
                errors.append(f"{path}[{item_index}].id")
            if location_type not in {"country", "city", "region"}:
                errors.append(f"{path}[{item_index}].type")
    return errors


def _brief_explicit_meta_location_ids(brief):
    """Return catalog IDs the buyer explicitly attached to a place."""
    text = str(brief or "")
    patterns = (
        r"\b(?:meta\s+)?(?:city|region|location)\s+id\s*[:#-]?\s*([0-9]{4,})\b",
        r"\bid\s+(?:de\s+)?(?:ciudad|regi[oó]n|ubicaci[oó]n)(?:\s+de\s+meta)?\s*[:#-]?\s*([0-9]{4,})\b",
    )
    return {
        match
        for pattern in patterns
        for match in re.findall(pattern, text, flags=re.IGNORECASE)
    }


def _compiled_meta_location_ids(payload):
    ids = set()
    roots = [payload]
    for ad_set in payload.get("ad_sets") or []:
        if not isinstance(ad_set, dict):
            continue
        roots.append(ad_set)
        if isinstance(ad_set.get("targeting"), dict):
            roots.append(ad_set["targeting"])
    for root in roots:
        location_values = []
        for key in ("locations", "targeting_locations"):
            value = root.get(key) if isinstance(root, dict) else None
            location_values.extend(value if isinstance(value, list) else ([value] if value else []))
        meta = root.get("meta_targeting") if isinstance(root, dict) and isinstance(root.get("meta_targeting"), dict) else {}
        value = meta.get("locations")
        location_values.extend(value if isinstance(value, list) else ([value] if value else []))
        for item in location_values:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or item.get("id") or "").strip()
            if key:
                ids.add(key)
    return ids


def _brief_manual_placements(brief):
    text = str(brief or "").lower()
    expected = set()
    patterns = {
        "facebook_feed": r"\b(?:facebook|fb)[\s_-]+feed\b",
        "facebook_story": r"\b(?:facebook|fb)[\s_-]+stor(?:y|ies)\b",
        "facebook_reels": r"\b(?:facebook|fb)[\s_-]+reels?\b",
        "facebook_video_feeds": r"\b(?:facebook|fb)[\s_-]+video[\s_-]+feeds?\b",
        "instagram_feed": r"\b(?:instagram|ig)[\s_-]+feed\b",
        "instagram_story": r"\b(?:instagram|ig)[\s_-]+stor(?:y|ies)\b",
        "instagram_reels": r"\b(?:instagram|ig)[\s_-]+reels?\b",
        "messenger_inbox": r"\bmessenger[\s_-]+inbox\b",
    }
    for token, pattern in patterns.items():
        if re.search(pattern, text):
            expected.add(token)
    # Natural phrases often name a platform once and then coordinate its
    # positions: "Facebook Feed y Stories". Parse each line as one scope so
    # the compiler cannot silently omit the second placement.
    for line in text.splitlines():
        platform = "facebook" if re.search(r"\b(?:facebook|fb)\b", line) else "instagram" if re.search(r"\b(?:instagram|ig)\b", line) else ""
        if not platform:
            continue
        if re.search(r"\bfeeds?\b", line):
            expected.add(f"{platform}_feed")
        if re.search(r"\bstor(?:y|ies)\b", line):
            expected.add(f"{platform}_story")
        if platform == "facebook" and re.search(r"\bvideo\s+feeds?\b", line):
            expected.add("facebook_video_feeds")
        if re.search(r"\breels?\b", line):
            expected.add(f"{platform}_reels")
    return expected


def _gemini_api_key(config):
    key = str(getattr(config, "gemini_api_key", "") or "").strip()
    if key:
        return key
    api = str(getattr(config, "agent_chat_api", "") or "").strip().lower()
    base_url = str(getattr(config, "agent_chat_base_url", "") or "").strip().lower()
    if api == "gemini-native" or "generativelanguage.googleapis.com" in base_url:
        return str(getattr(config, "agent_chat_api_key", "") or "").strip()
    return ""


def _gemini_base_url(config):
    configured = str(getattr(config, "agent_chat_base_url", "") or "").strip().rstrip("/")
    if "generativelanguage.googleapis.com" in configured.lower():
        return configured
    return str(os.environ.get("ADMIRA_CAMPAIGN_COMPILER_GEMINI_BASE_URL") or GEMINI_COMPILER_BASE_URL).rstrip("/")


def _gemini_compile(model, prompt, schema, *, api_key, base_url, timeout):
    request_payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
        },
    }
    request = urllib.request.Request(
        f"{base_url}/models/{model}:generateContent",
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        diagnostic = exc.read().decode("utf-8", errors="replace")[-2000:]
        return {
            "ok": False,
            "reason": "campaign_compiler_provider_failed",
            "model": model,
            "status": getattr(exc, "code", None),
            "diagnostic": diagnostic,
        }
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "reason": "campaign_compiler_provider_failed",
            "model": model,
            "diagnostic": str(exc)[-2000:],
        }

    try:
        parts = body["candidates"][0]["content"]["parts"]
        text = "".join(str(part.get("text") or "") for part in parts)
        return {"ok": True, "compiled": json.loads(text), "model": model}
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "reason": "campaign_compiler_invalid_json",
            "model": model,
            "diagnostic": str(exc)[-2000:],
        }


def _terra_compile(prompt, schema, *, config, timeout):
    executable = str(getattr(config, "codex_cli", "codex") or "codex")
    environment = codex_cli_environment(config)
    with tempfile.TemporaryDirectory(prefix="admira-campaign-compiler-") as isolated:
        isolated_path = Path(isolated)
        schema_path = isolated_path / "output-schema.json"
        output_path = isolated_path / "compiled-payload.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
        command = [
            executable, "exec",
            "--sandbox", "read-only",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "-C", isolated,
            "-m", TERRA_COMPILER_MODEL,
            "--output-schema", str(schema_path),
            "-o", str(output_path),
            "-",
        ]
        try:
            process = subprocess.Popen(
                command,
                cwd=isolated,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            stdout, stderr = process.communicate(prompt, timeout=timeout)
        except FileNotFoundError:
            return {"ok": False, "reason": "codex_cli_missing", "model": TERRA_COMPILER_MODEL}
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.communicate(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            return {"ok": False, "reason": "campaign_compiler_timeout", "model": TERRA_COMPILER_MODEL}

        if process.returncode != 0:
            return {
                "ok": False,
                "reason": "campaign_compiler_provider_failed",
                "error": codex_cli_error_message(stderr, stdout) or "Terra no pudo compilar el briefing.",
                "returncode": process.returncode,
                "diagnostic": (stderr or stdout or "")[-2000:],
                "model": TERRA_COMPILER_MODEL,
            }
        try:
            return {
                "ok": True,
                "compiled": json.loads(output_path.read_text(encoding="utf-8")),
                "model": TERRA_COMPILER_MODEL,
            }
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "ok": False,
                "reason": "campaign_compiler_invalid_json",
                "model": TERRA_COMPILER_MODEL,
                "diagnostic": str(exc)[-2000:],
            }


def _validate_compiled_candidate(
    destination,
    candidate,
    *,
    expected_targeting_mode="",
    expected_manual_placements=None,
    expected_location_ids=None,
):
    model = str(candidate.get("model") or "")
    compiled = candidate.get("compiled")
    if not isinstance(compiled, dict):
        return {"terminal": False, "reason": "campaign_compiler_invalid_json", "model": model}
    raw_payload = compiled.get("payload_json")
    try:
        payload = json.loads(raw_payload) if isinstance(raw_payload, str) else {}
    except json.JSONDecodeError:
        return {"terminal": False, "reason": "campaign_compiler_invalid_json", "model": model}
    if not isinstance(payload, dict):
        return {"terminal": False, "reason": "campaign_compiler_invalid_json", "model": model}

    missing = [str(value).strip() for value in (compiled.get("missing_fields") or []) if str(value).strip()]
    if compiled.get("ready") is not True:
        # A valid refusal is authoritative. Check it before candidate payload
        # invariants: ready=false deliberately carries an empty payload, so a
        # targeting check here would hide the actual missing buyer decisions.
        return {
            "terminal": True,
            "ok": False,
            "reason": "campaign_brief_incomplete",
            "missing_fields": missing or ["campaign_details"],
            "model": model,
        }

    unknown_fields = sorted(set(payload) - set(destination_payload_properties(destination)))
    if unknown_fields:
        return {
            "terminal": False,
            "reason": "campaign_compiler_contract_violation",
            "unknown_fields": unknown_fields,
            "model": model,
        }

    # Structured-output models sometimes split a natural placement phrase
    # into platform and position fragments. Canonicalize that harmless shape
    # before contract comparison and before the payload is persisted.
    placement_containers = [payload]
    placement_containers.extend(
        ad_set for ad_set in (payload.get("ad_sets") or []) if isinstance(ad_set, dict)
    )
    for container in placement_containers:
        placements = container.get("placements")
        if isinstance(placements, list):
            expanded = _expand_compiled_manual_placements(placements)
            if expanded:
                container["placements"] = {"automatic": False, "manual": expanded}
            continue
        if not isinstance(placements, dict) or placements.get("automatic") is True:
            continue
        manual = placements.get("manual") or []
        expanded = _expand_compiled_manual_placements(manual)
        if expanded:
            container["placements"] = {"automatic": False, "manual": expanded}

    location_contract_errors = _compiled_location_contract_errors(payload)
    if location_contract_errors:
        return {
            "terminal": False,
            "reason": "campaign_compiler_contract_violation",
            "missing_fields": location_contract_errors,
            "model": model,
        }
    missing_location_ids = sorted(set(expected_location_ids or ()) - _compiled_meta_location_ids(payload))
    if missing_location_ids:
        return {
            "terminal": False,
            "reason": "campaign_compiler_contract_violation",
            "missing_fields": [f"meta_location_id:{value}" for value in missing_location_ids],
            "model": model,
        }

    if expected_targeting_mode == "mixed":
        ad_sets = payload.get("ad_sets")
        modes = []
        if isinstance(ad_sets, list):
            for ad_set in ad_sets:
                if not isinstance(ad_set, dict):
                    modes.append("")
                    continue
                mode = str(ad_set.get("targeting_mode") or "").strip().lower().replace("+", "_plus")
                if not mode and isinstance(ad_set.get("targeting"), dict):
                    mode = str(ad_set["targeting"].get("targeting_mode") or "").strip().lower().replace("+", "_plus")
                explicit_advantage = ad_set.get("advantage_audience")
                if explicit_advantage is None and isinstance(ad_set.get("targeting"), dict):
                    explicit_advantage = ad_set["targeting"].get("advantage_audience")
                if not mode and isinstance(explicit_advantage, bool):
                    mode = "advantage_plus" if explicit_advantage else "manual"
                    ad_set["targeting_mode"] = mode
                normalized = {
                    "advantage": "advantage_plus",
                    "automatic": "advantage_plus",
                    "original": "manual",
                    "off": "manual",
                    "disabled": "manual",
                }.get(mode, mode)
                modes.append(normalized)
        if not modes or any(mode not in {"manual", "advantage_plus"} for mode in modes) or set(modes) != {"manual", "advantage_plus"}:
            return {
                "terminal": False,
                "reason": "campaign_compiler_contract_violation",
                "missing_fields": ["ad_sets[].targeting_mode"],
                "expected_targeting_mode": "mixed",
                "model": model,
            }
    elif expected_targeting_mode:
        actual_mode = str(payload.get("targeting_mode") or "").strip().lower().replace("+", "_plus")
        accepted = {
            "advantage_plus": {"advantage_plus", "advantage", "automatic"},
            "manual": {"manual", "original", "off", "disabled"},
        }.get(expected_targeting_mode, {expected_targeting_mode})
        if actual_mode not in accepted:
            return {
                "terminal": False,
                "reason": "campaign_compiler_contract_violation",
                "missing_fields": ["targeting_mode"],
                "expected_targeting_mode": expected_targeting_mode,
                "model": model,
            }

    expected_manual_placements = set(expected_manual_placements or ())
    if expected_manual_placements:
        actual_manual_placements = set()
        placement_values = []
        if isinstance(payload.get("placements"), dict):
            placement_values.extend(payload["placements"].get("manual") or [])
        for ad_set in payload.get("ad_sets") or []:
            if not isinstance(ad_set, dict) or not isinstance(ad_set.get("placements"), dict):
                continue
            placement_values.extend(ad_set["placements"].get("manual") or [])
        actual_manual_placements.update(
            _normalize_manual_placement(value) for value in placement_values if str(value or "").strip()
        )
        missing_placements = sorted(expected_manual_placements - actual_manual_placements)
        if missing_placements:
            return {
                "terminal": False,
                "reason": "campaign_compiler_contract_violation",
                "missing_fields": [f"manual_placements:{','.join(missing_placements)}"],
                "model": model,
            }

    missing.extend(field for field in _missing_required_fields(destination, payload) if field not in missing)
    if missing:
        # The model claimed readiness but dropped required facts. That is a
        # compiler contract miss, so a later compiler may retry safely.
        return {
            "terminal": False,
            "reason": "campaign_compiler_contract_violation",
            "missing_fields": missing,
            "model": model,
        }
    return {"terminal": True, "ok": True, "payload": payload, "model": model}


def compile_campaign_brief(tool, brief_markdown, *, timeout=240, config=None):
    destination = DESTINATIONS.get(str(tool or ""), "")
    brief = str(brief_markdown or "").strip()
    if not destination:
        return {"ok": False, "reason": "unsupported_campaign_destination"}
    if len(brief) < 20:
        return {"ok": False, "reason": "campaign_brief_too_short", "missing_fields": ["brief_markdown"]}
    if len(brief) > MAX_BRIEF_CHARS:
        return {"ok": False, "reason": "campaign_brief_too_large"}

    brief_path = persist_latest_brief(tool, brief)
    contract = CONTRACT_FILE.read_text(encoding="utf-8") if CONTRACT_FILE.exists() else ""
    schema = compiler_output_schema(tool)
    config = config or load_config()
    timeout = max(30, min(int(timeout or 240), 300))

    prompt = f"""You are Admira's deterministic campaign payload compiler.
Compile the latest natural-language brief for destination `{destination}` into the supplied JSON output schema.
Do not call tools, do not create or edit media, do not contact Meta, and do not invent missing buyer decisions.
If a required fact is missing or ambiguous, set ready=false, list it in missing_fields, and set payload_json to '{{}}'.
If ready=true, copy exact buyer values and put one valid JSON object string in payload_json. The decoded payload may use only these fields: {', '.join(destination_payload_properties(destination))}.
Required semantic fields for this destination are: {', '.join(DESTINATION_REQUIRED_FIELDS.get(destination, ()))}.
Interpret ordinary natural language, not only key:value syntax. A fact is present when the Markdown states it unambiguously in a sentence or bullet.
The selected destination itself supplies its contract-defined objective; for WhatsApp use a messaging/engagement objective and never ask the buyer to choose between those implementation labels.
Audience automation and placement automation are different controls. If the brief explicitly says Advantage+ Audience, set targeting_mode to advantage_plus. If it explicitly disables Advantage+ Audience or requests manual/original audience targeting, set targeting_mode to manual. For a multi-ad-set brief with different audience modes, set targeting_mode inside every ad_sets item and preserve each item's decision; do not force one campaign-wide mode. Never infer either decision from placement wording.
For multi-ad-set campaigns, locations, placements, prefilled_message/welcome_message, budgets, ages, genders, creative references, and ad copy may differ per item. Preserve those values inside each ad_sets item. Do not require a fake campaign-wide default when every ad set supplies the field.
Every structured Meta location must preserve its `id`/`key` and its exact `type` (`city`, `region`, or `country`). Preserve `name` and `country_code` when supplied. Never emit an object containing only an ID; if exact structure is uncertain, preserve the buyer's natural city/region string so the backend resolves it live.
For WhatsApp, an explicit instruction to create now with one exact existing creative path and exact prefilled messages is the buyer's approved creative/message decision: encode creative_decision as reuse of that exact path and set creative_approved and prefilled_message_approved true. This is copying the buyer's creation authorization, not inventing approval.
When the buyer instructed creation with an exact amount and currency, copy that wording into budget_confirmation; do not require a second sentence containing the word confirm.
Obey every contract below. Output the supplied wrapper JSON only.

<payload_field_contract>
{json.dumps(destination_payload_properties(destination), ensure_ascii=False)}
</payload_field_contract>

<compiler_contract>
{contract}
</compiler_contract>

<latest_campaign_markdown>
{brief_path.read_text(encoding="utf-8")}
</latest_campaign_markdown>
"""

    deadline = time.monotonic() + timeout
    attempts = []
    expected_targeting_mode = _brief_targeting_mode(brief)
    expected_manual_placements = _brief_manual_placements(brief)
    expected_location_ids = _brief_explicit_meta_location_ids(brief)
    api_key = _gemini_api_key(config)
    base_url = _gemini_base_url(config)
    providers = []
    if api_key:
        providers.extend(("gemini", model) for model in GEMINI_COMPILER_MODELS)
    providers.append(("terra", TERRA_COMPILER_MODEL))

    final_failure = None
    payload = None
    selected_model = ""
    for provider, model in providers:
        remaining = int(deadline - time.monotonic())
        if remaining < 1:
            final_failure = {"reason": "campaign_compiler_timeout", "model": model}
            break
        started = time.monotonic()
        if provider == "gemini":
            candidate = _gemini_compile(
                model,
                prompt,
                schema,
                api_key=api_key,
                base_url=base_url,
                timeout=max(1, min(GEMINI_ATTEMPT_TIMEOUT_SECONDS, remaining)),
            )
        else:
            candidate = _terra_compile(prompt, schema, config=config, timeout=max(1, remaining))
        attempts.append({
            "model": model,
            "ok": bool(candidate.get("ok")),
            "reason": str(candidate.get("reason") or ""),
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        })
        if not candidate.get("ok"):
            final_failure = candidate
            continue
        validated = _validate_compiled_candidate(
            destination,
            candidate,
            expected_targeting_mode=expected_targeting_mode,
            expected_manual_placements=expected_manual_placements,
            expected_location_ids=expected_location_ids,
        )
        attempts[-1]["ok"] = bool(validated.get("ok"))
        attempts[-1]["reason"] = str(validated.get("reason") or "")
        if not validated.get("terminal"):
            final_failure = validated
            continue
        if not validated.get("ok"):
            validated.update({"brief_path": str(brief_path), "compiler_attempts": attempts})
            return validated
        payload = validated["payload"]
        selected_model = validated["model"]
        break

    if payload is None:
        failure = dict(final_failure or {"reason": "campaign_compiler_failed"})
        failure.update({
            "ok": False,
            "brief_path": str(brief_path),
            "compiler_attempts": attempts,
        })
        return failure

    _atomic_private_text(LATEST_PAYLOAD_FILE, json.dumps({
        "compiled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": selected_model,
        "compiler_attempts": attempts,
        "destination": destination,
        "payload": payload,
    }, ensure_ascii=False, indent=2) + "\n")
    return {
        "ok": True,
        "payload": payload,
        "brief_path": str(brief_path),
        "payload_path": str(LATEST_PAYLOAD_FILE),
        "model": selected_model,
        "compiler_attempts": attempts,
        "destination": destination,
    }
