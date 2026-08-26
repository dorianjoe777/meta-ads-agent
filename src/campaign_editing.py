#!/usr/bin/env python3
"""Campaign-scoped natural-language edit planning and execution.

The model may interpret a buyer's wording, but this module owns campaign
identity, draft state, allowlisted diffs, approvals, and Graph read-back.
"""
import hashlib
import json
import re
import shutil
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from adset_controls import normalize_placement_config, placement_targeting_fields
from campaign_payload_compiler import (
    COMPILER_MODELS,
    TERRA_COMPILER_MODEL,
    _gemini_api_key,
    _gemini_base_url,
    _gemini_compile,
    _terra_compile,
)
from local_store import read_json, write_json
from product_config import ROOT_DIR, load_config


EDIT_ROOT = ROOT_DIR / "dashboard" / "data" / "campaign-edit-workflows"
EDIT_INDEX_FILE = EDIT_ROOT / "conversation-index.json"
EDIT_CONTRACT_FILE = ROOT_DIR / "agent" / "contracts" / "campaign-edit-compiler.md"
PENDING_FILE = ROOT_DIR / "dashboard" / "data" / "pending_approvals.json"
MAX_CHANGE_REQUEST_CHARS = 12_000

CAMPAIGN_FIELDS = {"name", "daily_budget", "lifetime_budget", "budget_confirmation"}
ADSET_FIELDS = {
    "name", "daily_budget", "lifetime_budget", "budget_confirmation",
    "start_time", "end_time", "age_min", "age_max", "genders",
    "locations", "interest_ids", "targeting_mode", "placements",
}
AD_FIELDS = {
    "name", "status", "primary_text", "headline", "description",
    "link_url", "call_to_action_type", "image_path", "image_hash", "image_url",
    "video_id", "prefilled_message", "welcome_message",
}
NUMERIC_FIELDS = {"daily_budget", "lifetime_budget", "age_min", "age_max"}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm(value):
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return re.sub(r"\s+", " ", text)


def _safe_key(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:24]


def _atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{_safe_key(_now())}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)


def _conversation_key(conversation_id=""):
    if str(conversation_id or "").strip():
        return str(conversation_id).strip()
    config = load_config()
    return str(getattr(config, "telegram_chat_id", "") or "installation").strip() or "installation"


def _draft_dir(conversation_id, account_id, campaign_id):
    return EDIT_ROOT / _safe_key(f"{conversation_id}:{account_id}") / str(campaign_id)


def _draft_path(conversation_id, account_id, campaign_id):
    return _draft_dir(conversation_id, account_id, campaign_id) / "draft.json"


def _markdown_path(conversation_id, account_id, campaign_id):
    return _draft_dir(conversation_id, account_id, campaign_id) / "latest-edit.md"


def _load_index():
    value = read_json(EDIT_INDEX_FILE, {})
    return value if isinstance(value, dict) else {}


def _save_index(value):
    _atomic(EDIT_INDEX_FILE, value)


def reset_conversation_edit_context(conversation_id):
    """Discard only transient edit scope for one buyer conversation.

    OAuth credentials and the selected Meta workspace live in separate stores
    and are deliberately untouched.  A fresh conversation must not inherit a
    pronoun target, an unfinished edit draft, or an approval from the previous
    conversation.
    """
    conversation_id = _conversation_key(conversation_id)
    index = _load_index()
    scope_keys = set()
    removed_drafts = 0

    if EDIT_ROOT.exists():
        for scope in EDIT_ROOT.iterdir():
            if not scope.is_dir():
                continue
            matched = False
            for draft_path in scope.glob("*/draft.json"):
                draft = _load_draft(draft_path)
                if str(draft.get("conversation_key") or "") == conversation_id:
                    matched = True
                    removed_drafts += 1
            if matched:
                scope_keys.add(scope.name)
                shutil.rmtree(scope)

    changed_index = False
    for key in list(index):
        if key in scope_keys:
            index.pop(key, None)
            changed_index = True
    if changed_index:
        _save_index(index)

    pending = read_json(PENDING_FILE, [])
    cancelled_approvals = 0
    changed_pending = False
    if isinstance(pending, list):
        for item in pending:
            if not isinstance(item, dict) or item.get("type") != "campaign_edit" or item.get("status", "pending") != "pending":
                continue
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            if str(payload.get("conversation_key") or "") != conversation_id:
                continue
            item["status"] = "cancelled_by_conversation_reset"
            item["resolved_at"] = _now()
            cancelled_approvals += 1
            changed_pending = True
        if changed_pending:
            _atomic(PENDING_FILE, pending)

    return {
        "ok": True,
        "conversation_key": conversation_id,
        "removed_drafts": removed_drafts,
        "cancelled_approvals": cancelled_approvals,
        "cleared_active_campaign": bool(scope_keys or changed_index),
    }


def _load_draft(path):
    value = read_json(path, {})
    return value if isinstance(value, dict) else {}


def _save_draft(draft, *, conversation_id, account_id, campaign_id, markdown=""):
    path = _draft_path(conversation_id, account_id, campaign_id)
    _atomic(path, draft)
    if markdown:
        md_path = _markdown_path(conversation_id, account_id, campaign_id)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(markdown, encoding="utf-8")
        md_path.chmod(0o600)
    return path


def _campaign_documents(campaigns, adsets):
    grouped = {}
    for item in adsets or []:
        if not isinstance(item, dict):
            continue
        grouped.setdefault(str(item.get("campaign_id") or ""), []).append(item)
    documents = []
    for campaign in campaigns or []:
        if not isinstance(campaign, dict):
            continue
        campaign_id = str(campaign.get("id") or campaign.get("campaign_id") or "").strip()
        if not campaign_id:
            continue
        children = grouped.get(campaign_id, [])
        aliases = [campaign.get("name"), campaign.get("objective"), campaign.get("destination")]
        aliases.extend(item.get("name") for item in children)
        documents.append({
            "id": campaign_id,
            "name": str(campaign.get("name") or campaign_id),
            "aliases": [str(value).strip() for value in aliases if str(value or "").strip()],
            "objective": str(campaign.get("objective") or ""),
            "status": str(campaign.get("effective_status") or campaign.get("status") or ""),
            "adset_names": [str(item.get("name") or "") for item in children if item.get("name")],
            "raw": campaign,
        })
    return documents


def resolve_campaign_reference(reference, campaigns, adsets, *, active_campaign_id=""):
    """Resolve one natural reference, never silently choosing on a tie."""
    raw = str(reference or "").strip()
    text = _norm(raw)
    documents = _campaign_documents(campaigns, adsets)
    if not documents:
        return {"ok": False, "reason": "no_campaigns", "candidates": []}

    ids = set(re.findall(r"\b\d{6,}\b", raw))
    for document in documents:
        if document["id"] in ids or document["id"] == raw:
            return {"ok": True, "campaign": document["raw"], "campaign_id": document["id"], "matched_by": "id"}

    pronoun = not text or bool(re.search(r"\b(esa|ese|la misma|el mismo|tambien|también|that one|same one|it)\b", text))
    if pronoun and active_campaign_id:
        for document in documents:
            if document["id"] == str(active_campaign_id):
                return {"ok": True, "campaign": document["raw"], "campaign_id": document["id"], "matched_by": "conversation_context"}

    if not text:
        return {"ok": False, "reason": "campaign_reference_missing", "candidates": []}

    exact = []
    for document in documents:
        name = _norm(document["name"])
        if text == name or text in name or (len(text) >= 8 and name in text):
            exact.append(document)
    if len(exact) == 1:
        return {"ok": True, "campaign": exact[0]["raw"], "campaign_id": exact[0]["id"], "matched_by": "name"}
    if len(exact) > 1:
        return {"ok": False, "reason": "ambiguous_campaign", "candidates": [item["raw"] for item in exact]}

    stop = {
        "campana", "campaña", "campaign", "la", "de", "del", "the", "en", "in",
        "para", "with", "con", "ads", "anuncios", "usa", "usar", "pon", "poner",
        "cambia", "cambiar", "modifica", "modificar", "ajusta", "ajustar", "deja",
        "dejar", "solo", "solamente", "quiero", "necesito", "please", "por", "favor",
    }
    query_tokens = {token for token in text.split() if len(token) >= 3 and token not in stop}
    scored = []
    token_owners = {}
    for document in documents:
        alias_tokens = set()
        for alias in document["aliases"]:
            alias_tokens.update(token for token in _norm(alias).split() if len(token) >= 3 and token not in stop)
        for token in query_tokens & alias_tokens:
            token_owners.setdefault(token, []).append(document)
        overlap = len(query_tokens & alias_tokens)
        if overlap:
            score = overlap / max(1, len(query_tokens))
            scored.append((score, overlap, document))
    # Natural edit sentences contain many command words, so a place/product
    # token can be only a small fraction of the full sentence. A token that
    # exists in exactly one current campaign is still a safe discriminator.
    uniquely_identified = {
        owners[0]["id"]: owners[0]
        for token, owners in token_owners.items()
        if len(token) >= 4 and len(owners) == 1
    }
    if len(uniquely_identified) == 1:
        document = next(iter(uniquely_identified.values()))
        return {"ok": True, "campaign": document["raw"], "campaign_id": document["id"], "matched_by": "unique_natural_token"}
    if len(uniquely_identified) > 1:
        return {"ok": False, "reason": "ambiguous_campaign", "candidates": [item["raw"] for item in uniquely_identified.values()]}
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]) and scored[0][0] >= 0.5:
        return {"ok": True, "campaign": scored[0][2]["raw"], "campaign_id": scored[0][2]["id"], "matched_by": "natural_reference"}
    candidates = [item[2]["raw"] for item in scored[:5]]
    return {"ok": False, "reason": "ambiguous_campaign" if candidates else "campaign_not_found", "candidates": candidates}


def _snapshot_for(campaign, adsets, ads):
    campaign_id = str(campaign.get("id") or campaign.get("campaign_id") or "")
    return {
        "campaign": dict(campaign),
        "ad_sets": [dict(item) for item in (adsets or []) if str(item.get("campaign_id") or "") == campaign_id],
        "ads": [dict(item) for item in (ads or []) if str(item.get("campaign_id") or "") == campaign_id],
    }


def _fingerprint(item):
    if not isinstance(item, dict):
        return ""
    creative = item.get("creative") if isinstance(item.get("creative"), dict) else {}
    def fingerprint_budget(field):
        value = item.get(field)
        try:
            number = float(value)
        except (TypeError, ValueError):
            return ""
        if item.get("_meta_graph_minor_units"):
            number /= 100
        # Meta may omit zero budgets while the dashboard stores 0.0.
        return "" if number == 0 else str(number)

    canonical = {
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or ""),
        # Dashboard inventory can expose effective_status while a direct
        # entity read exposes configured status. Prefer configured/status so
        # both sources describe the same editable state.
        "status": str(item.get("configured_status") or item.get("status") or item.get("effective_status") or "").lower(),
        "daily_budget": fingerprint_budget("daily_budget"),
        "lifetime_budget": fingerprint_budget("lifetime_budget"),
        "start_time": str(item.get("start_time") or ""),
        "end_time": str(item.get("end_time") or ""),
        # Dashboard inventory intentionally omits the large targeting object,
        # while the direct pre-write Graph read includes it. Targeting edits
        # merge against that fresh Graph value and are verified after writing,
        # so it must not create a false stale-snapshot mismatch here.
        "targeting": {},
        "creative_id": str(creative.get("id") or item.get("creative_id") or ""),
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _preconditions(snapshot):
    result = {}
    for collection in ("campaign", "ad_sets", "ads"):
        values = snapshot.get(collection) if collection == "campaign" else snapshot.get(collection) or []
        values = [values] if collection == "campaign" and isinstance(values, dict) else values
        for item in values:
            if isinstance(item, dict) and item.get("id"):
                result[str(item["id"])] = _fingerprint(item)
    return result


def edit_output_schema():
    operation = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "entity_type": {"type": "string", "enum": ["campaign", "adset", "ad"]},
            "entity_id": {"type": "string"},
            "changes": {"type": "object", "additionalProperties": True},
            "reason": {"type": "string"},
        },
        "required": ["entity_type", "entity_id", "changes"],
    }
    return {
        "type": "object", "additionalProperties": False,
        "properties": {
            "ready": {"type": "boolean"},
            "missing_fields": {"type": "array", "items": {"type": "string"}},
            "operations_json": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": ["ready", "missing_fields", "operations_json", "summary"],
    }


def _validate_operations(raw, snapshot):
    try:
        decoded = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        return None, ["operations_json_invalid"]
    operations = decoded.get("operations") if isinstance(decoded, dict) else decoded
    if not isinstance(operations, list) or not operations:
        return None, ["operations"]
    known = {"campaign": set(), "adset": set(), "ad": set()}
    campaign_id = str((snapshot.get("campaign") or {}).get("id") or "")
    if campaign_id:
        known["campaign"].add(campaign_id)
    known["adset"] = {str(item.get("id")) for item in snapshot.get("ad_sets") or [] if item.get("id")}
    known["ad"] = {str(item.get("id")) for item in snapshot.get("ads") or [] if item.get("id")}
    validated = []
    errors = []
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            errors.append(f"operations[{index}]")
            continue
        # Compilers can express the same valid operation with harmless key
        # aliases. Normalize those shapes before enforcing the canonical
        # allowlist; semantic validation, live IDs and approvals remain owned
        # by the server.
        entity_type = str(
            operation.get("entity_type")
            or operation.get("object_type")
            or operation.get("target_type")
            or operation.get("entity")
            or operation.get("type")
            or ""
        ).strip().lower()
        entity_type = {
            "ad_set": "adset",
            "ad-set": "adset",
            "ad set": "adset",
            "advertisement": "ad",
        }.get(entity_type, entity_type)
        entity_id = str(
            operation.get("entity_id")
            or operation.get("target_id")
            or operation.get("object_id")
            or operation.get("id")
            or ""
        ).strip()
        changes = operation.get("changes")
        if not isinstance(changes, dict) and isinstance(operation.get("fields"), dict):
            changes = operation.get("fields")
        if not isinstance(changes, dict):
            metadata_keys = {
                "entity_type", "object_type", "target_type", "entity", "type",
                "entity_id", "target_id", "object_id", "id", "reason", "changes", "fields",
            }
            changes = {
                key: value for key, value in operation.items()
                if key not in metadata_keys
            }
        allowed = {"campaign": CAMPAIGN_FIELDS, "adset": ADSET_FIELDS, "ad": AD_FIELDS}.get(entity_type)
        # The model interprets wording; the server owns real IDs. Once the
        # campaign is resolved, an omitted ID is safe to fill for that parent
        # or for a sole child. Never replace a wrong non-empty ID or guess
        # among multiple ad sets/ads.
        if len(known.get(entity_type, set())) == 1 and (
            not entity_id or not re.fullmatch(r"\d{6,}", entity_id)
        ):
            entity_id = next(iter(known[entity_type]))
        if entity_type not in known or entity_id not in known.get(entity_type, set()):
            errors.append(f"operations[{index}].entity_id")
            continue
        if not isinstance(changes, dict) or not changes:
            errors.append(f"operations[{index}].changes")
            continue
        unknown = sorted(set(changes) - allowed)
        if unknown:
            errors.extend(f"operations[{index}].changes.{field}" for field in unknown)
            continue
        clean = {"entity_type": entity_type, "entity_id": entity_id, "changes": dict(changes)}
        if operation.get("reason"):
            clean["reason"] = str(operation["reason"])[:500]
        for field, value in changes.items():
            if field in NUMERIC_FIELDS:
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    errors.append(f"operations[{index}].changes.{field}")
                    continue
                if field in {"age_min", "age_max"} and (number < 13 or number > 65):
                    errors.append(f"operations[{index}].changes.{field}")
                if field in {"daily_budget", "lifetime_budget"} and number <= 0:
                    errors.append(f"operations[{index}].changes.{field}")
                if field in {"age_min", "age_max"}:
                    clean["changes"][field] = int(number)
                else:
                    clean["changes"][field] = number
            if field == "status" and str(value).upper() not in {"PAUSED", "ACTIVE"}:
                errors.append(f"operations[{index}].changes.status")
            if field == "placements" and not isinstance(value, (dict, list, str)):
                errors.append(f"operations[{index}].changes.placements")
        validated.append(clean)
    return (validated if not errors else None), errors


def _edit_prompt(snapshot, requests, campaign_reference):
    contract = EDIT_CONTRACT_FILE.read_text(encoding="utf-8") if EDIT_CONTRACT_FILE.exists() else ""
    return f"""You are Admira's deterministic campaign edit compiler.
Resolve and plan only the explicitly requested differences for the already selected campaign.
Never create a new campaign, never invent an ID, and never modify fields absent from the buyer requests.
Requests are chronological: for the same target field, the latest explicit request wins; preserve unrelated earlier requested differences.
If the request is ambiguous, unsupported, or missing the exact target ad set/ad, set ready=false and list missing_fields.
Return the wrapper JSON schema exactly. operations_json must be a JSON object with an operations array.
Campaign edits may change only name or budget. Ad-set edits may change name, budget, dates, age, genders,
locations, interest_ids, targeting_mode, or placements. Ad edits may change name, PAUSED/ACTIVE status, or
creative text/link/media fields. Do not change objective, destination, account, Page, conversion event, or
campaign budget level; mark those unsupported in missing_fields. A status ACTIVE request must be listed as
missing_fields `activation_requires_separate_approval` rather than emitted as an operation.
For a budget change, preserve the buyer's exact amount and currency in `budget_confirmation`.
For targeting, emit only the requested high-level fields; the server merges them with the current targeting.
For locations/interests, preserve exact Meta IDs if the buyer supplied them. Do not guess IDs.

<current_campaign_snapshot>
{json.dumps(snapshot, ensure_ascii=False, indent=2)[:80_000]}
</current_campaign_snapshot>

<campaign_reference>
{campaign_reference}
</campaign_reference>

<accumulated_buyer_edit_requests>
{json.dumps(requests, ensure_ascii=False, indent=2)[:20_000]}
</accumulated_buyer_edit_requests>

<edit_contract>
{contract}
</edit_contract>
"""


def compile_edit_plan(snapshot, requests, campaign_reference, *, config=None, timeout=180):
    config = config or load_config()
    prompt = _edit_prompt(snapshot, requests, campaign_reference)
    schema = edit_output_schema()
    deadline = __import__("time").monotonic() + max(30, min(int(timeout or 180), 240))
    providers = []
    if _gemini_api_key(config):
        providers.extend(("gemini", model) for model in COMPILER_MODELS[:2])
    providers.append(("terra", TERRA_COMPILER_MODEL))
    attempts = []
    last = None
    for provider, model in providers:
        remaining = int(deadline - __import__("time").monotonic())
        if remaining < 1:
            break
        if provider == "gemini":
            candidate = _gemini_compile(model, prompt, schema, api_key=_gemini_api_key(config), base_url=_gemini_base_url(config), timeout=min(60, remaining))
        else:
            candidate = _terra_compile(prompt, schema, config=config, timeout=remaining)
        attempts.append({"model": model, "ok": bool(candidate.get("ok")), "reason": candidate.get("reason", "")})
        if not candidate.get("ok"):
            last = candidate
            continue
        compiled = candidate.get("compiled") or {}
        if compiled.get("ready") is not True:
            return {"ok": False, "reason": "campaign_edit_incomplete", "missing_fields": compiled.get("missing_fields") or ["campaign_edit_details"], "compiler_model": model, "compiler_attempts": attempts}
        operations, errors = _validate_operations(compiled.get("operations_json"), snapshot)
        if errors:
            last = {"reason": "campaign_edit_contract_violation", "missing_fields": errors, "compiler_model": model}
            continue
        return {"ok": True, "operations": operations, "summary": str(compiled.get("summary") or "Cambios preparados."), "compiler_model": model, "compiler_attempts": attempts}
    return {"ok": False, "reason": (last or {}).get("reason", "campaign_edit_compiler_failed"), "missing_fields": (last or {}).get("missing_fields") or [], "compiler_attempts": attempts}


def _target_id(item):
    return str((item or {}).get("id") or (item or {}).get("campaign_id") or "").strip()


def _clean_account_id(value):
    text = str(value or "").strip()
    return text[4:] if text.startswith("act_") else text


def _resolve_location(client, value):
    if isinstance(value, dict):
        key = str(value.get("key") or value.get("id") or "").strip()
        kind = str(value.get("type") or value.get("location_type") or "").strip().lower()
        if key and kind in {"country", "city", "region"}:
            return {"key": key, "id": key, "name": str(value.get("name") or key), "type": kind, "country_code": str(value.get("country_code") or value.get("country") or "").upper()}
    query = str(value or "").strip()
    if not query:
        return None
    if len(query) == 2 and query.isalpha():
        return {"key": query.upper(), "id": query.upper(), "name": query.upper(), "type": "country", "country_code": query.upper()}
    result = client.search_meta_targeting("location", query, limit=10)
    rows = result.get("items") if isinstance(result, dict) and result.get("ok") else []
    normalized = _norm(query)
    exact = [row for row in rows if _norm(row.get("name") or row.get("label")) == normalized]
    chosen = exact[0] if len(exact) == 1 else rows[0] if len(rows) == 1 else None
    if not chosen:
        return None
    key = str(chosen.get("key") or chosen.get("id") or "").strip()
    kind = str(chosen.get("type") or chosen.get("location_type") or "").strip().lower()
    return {"key": key, "id": key, "name": str(chosen.get("name") or query), "type": kind, "country_code": str(chosen.get("country_code") or "").upper()}


def _build_targeting(client, current, changes):
    targeting = dict(current or {})
    if "locations" in changes:
        locations = changes.get("locations")
        locations = locations if isinstance(locations, list) else [locations]
        resolved = [_resolve_location(client, item) for item in locations]
        if not resolved or any(item is None for item in resolved):
            return None, "targeting_location_ambiguous"
        geo = {}
        for item in resolved:
            kind = item.get("type")
            if kind == "country":
                geo.setdefault("countries", []).append(item["key"].upper())
            elif kind in {"city", "region"}:
                geo.setdefault(f"{kind}s", []).append({"key": item["key"]})
        if not geo:
            return None, "targeting_location_invalid"
        targeting["geo_locations"] = geo
    if "age_min" in changes:
        targeting["age_min"] = int(changes["age_min"])
    if "age_max" in changes:
        targeting["age_max"] = int(changes["age_max"])
    if "genders" in changes:
        targeting["genders"] = changes["genders"]
    if "interest_ids" in changes:
        ids = changes.get("interest_ids") or []
        targeting["interests"] = [{"id": str(item.get("id") if isinstance(item, dict) else item)} for item in ids]
    if "targeting_mode" in changes:
        mode = _norm(changes["targeting_mode"]).replace(" ", "_")
        if mode in {"advantage", "advantage_plus", "advantage_plus_audience", "automatic"}:
            targeting["targeting_automation"] = {"advantage_audience": 1}
        elif mode in {"manual", "original", "strict", "disabled", "off"}:
            targeting["targeting_automation"] = {"advantage_audience": 0}
        else:
            return None, "targeting_mode_invalid"
    if "placements" in changes:
        for key in ("publisher_platforms", "facebook_positions", "instagram_positions", "messenger_positions", "audience_network_positions", "threads_positions"):
            targeting.pop(key, None)
        placement = normalize_placement_config(changes["placements"])
        targeting.update(placement_targeting_fields(placement))
    return targeting, ""


def _graph_fields(item, *, client):
    return {"id": _target_id(item), "name": item.get("name"), "status": item.get("status"), "configured_status": item.get("configured_status"), "daily_budget": item.get("daily_budget"), "lifetime_budget": item.get("lifetime_budget"), "start_time": item.get("start_time"), "end_time": item.get("end_time"), "targeting": item.get("targeting"), "creative": item.get("creative")}


def _read_entity(client, entity_type, entity_id):
    # Meta Graph exposes ``start_time`` on campaigns, and the dashboard keeps
    # it in the live snapshot used for optimistic locking. ``end_time`` is not
    # a campaign field, however; requesting that field on the parent makes a
    # valid edit fail before it can be read.
    fields = "id,name,status,configured_status"
    if entity_type == "campaign":
        fields += ",daily_budget,lifetime_budget,start_time"
    elif entity_type == "adset":
        fields += ",daily_budget,lifetime_budget,start_time,end_time,targeting"
    elif entity_type == "ad":
        fields += ",creative{id,name,object_story_spec}"
    result = client.get_graph(entity_id, {"fields": fields})
    body = result.get("body") if isinstance(result, dict) and isinstance(result.get("body"), dict) else {}
    if isinstance(body, dict):
        # Graph returns budget fields in minor units; retain the raw values
        # for write/read-back checks and mark them for snapshot fingerprint
        # normalization against the dashboard's major-unit inventory.
        body = dict(body)
        body["_meta_graph_minor_units"] = True
    return result, body


def _canonical_graph_value(value):
    if isinstance(value, dict):
        return {key: _canonical_graph_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        normalized = [_canonical_graph_value(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
    return value


def _creative_story_container(creative):
    """Return the live Graph story container that owns ad copy fields."""
    creative = creative if isinstance(creative, dict) else {}
    spec = creative.get("object_story_spec") if isinstance(creative.get("object_story_spec"), dict) else {}
    for key in ("link_data", "photo_data", "video_data", "template_data"):
        container = spec.get(key)
        if isinstance(container, dict):
            return container
    return {}


def _creative_change_mismatches(changes, creative):
    """Compare buyer-requested creative fields with the independent Graph GET."""
    changes = changes if isinstance(changes, dict) else {}
    container = _creative_story_container(creative)
    mismatches = []
    mapping = {
        "primary_text": "message",
        "headline": "name",
        "description": "description",
        "link_url": "link",
        "image_hash": "image_hash",
        "video_id": "video_id",
    }
    for requested_field, graph_field in mapping.items():
        if requested_field not in changes:
            continue
        if str(container.get(graph_field) or "") != str(changes.get(requested_field) or ""):
            mismatches.append(f"creative.{requested_field}")
    if "call_to_action_type" in changes:
        call_to_action = container.get("call_to_action") if isinstance(container.get("call_to_action"), dict) else {}
        if str(call_to_action.get("type") or "").upper() != str(changes.get("call_to_action_type") or "").upper():
            mismatches.append("creative.call_to_action_type")
    return mismatches


def _parse_stdout_id(result):
    try:
        body = json.loads(result.get("stdout") or "{}")
    except (TypeError, json.JSONDecodeError):
        body = {}
    # Meta's image upload endpoint returns ``hash`` while creative/ad
    # creation returns ``id``.  Keep both forms so an image edit can proceed
    # through the same replacement-creative path as text edits.
    value = body.get("id") or body.get("creative_id") or body.get("hash") or body.get("image_hash")
    if not value and isinstance(body.get("images"), dict):
        first = next(iter(body["images"].values()), {})
        if isinstance(first, dict):
            value = first.get("hash") or first.get("id")
    return str(value or "").strip()


def _budget_amount(changes, currency, dashboard_contract=None):
    if "daily_budget" not in changes and "lifetime_budget" not in changes:
        return changes, ""
    changes = dict(changes)
    for field in ("daily_budget", "lifetime_budget"):
        if field not in changes:
            continue
        confirmation = changes.get("budget_confirmation")
        if isinstance(confirmation, dict):
            try:
                declared_amount = float(confirmation.get("amount"))
                requested_amount = float(changes[field])
            except (TypeError, ValueError):
                return None, "budget_currency_mismatch"
            declared_currency = str(confirmation.get("currency") or "").strip().upper()
            if not declared_currency or abs(declared_amount - requested_amount) > 1e-9:
                return None, "budget_currency_mismatch"
            phrase = f"{declared_amount:g} {declared_currency}"
        else:
            phrase = str(confirmation or f"{changes[field]} {currency}").strip()
        if callable(dashboard_contract):
            checked = dashboard_contract(phrase, account_currency=currency)
            if not checked.get("ok"):
                return None, "budget_currency_mismatch"
            changes[field] = checked.get("amount")
            changes[f"_{field}_api"] = checked.get("api_amount")
        else:
            changes[field] = float(changes[field])
    return changes, ""


def _make_creative_patch(client, account_id, ad, changes, approved=True):
    creative = ad.get("creative") if isinstance(ad.get("creative"), dict) else {}
    spec = creative.get("object_story_spec") if isinstance(creative.get("object_story_spec"), dict) else {}
    spec = json.loads(json.dumps(spec)) if spec else {}
    container = spec.get("link_data") or spec.get("photo_data") or spec.get("video_data")
    if not isinstance(container, dict):
        container = spec.setdefault("link_data", {})
    if "primary_text" in changes:
        container["message"] = changes["primary_text"]
    if "headline" in changes:
        container["name"] = changes["headline"]
    if "description" in changes:
        container["description"] = changes["description"]
    if "link_url" in changes:
        container["link"] = changes["link_url"]
    if "call_to_action_type" in changes:
        container["call_to_action"] = {"type": str(changes["call_to_action_type"]).upper(), "value": {"link": changes.get("link_url") or container.get("link")}}
    if "image_hash" in changes:
        container["image_hash"] = changes["image_hash"]
    if "image_path" in changes:
        upload = client.upload_image(account_id, changes["image_path"], approved=approved)
        image_hash = _parse_stdout_id(upload)
        if not image_hash:
            return None, "creative_image_upload_failed", ""
        container["image_hash"] = image_hash
    if "image_url" in changes:
        container["image_url"] = changes["image_url"]
    if "video_id" in changes:
        container["video_id"] = changes["video_id"]
    page_id = str(spec.get("page_id") or container.get("page_id") or "").strip()
    if not page_id:
        return None, "creative_page_id_missing", ""
    if account_id and not account_id.startswith("act_"):
        account_id = f"act_{account_id}"
    result = client.create_creative(
        account_id,
        f"EDIT - {ad.get('name') or ad.get('id')}",
        page_id,
        "", "", "", "", "",
        object_story_spec=spec,
        prefilled_message=str(changes.get("prefilled_message") or ""),
        welcome_message=str(changes.get("welcome_message") or ""),
        approved=approved,
    )
    creative_id = _parse_stdout_id(result)
    if not creative_id:
        return None, "creative_replacement_failed", ""
    return {"creative": {"creative_id": creative_id}}, "", creative_id


def execute_campaign_edit(payload, client, *, dashboard_contract=None):
    """Apply a prevalidated edit plan and verify every changed entity."""
    operations = payload.get("operations") if isinstance(payload, dict) else []
    if not isinstance(operations, list) or not operations:
        return {"ok": False, "blocked": True, "error": "campaign_edit_operations_missing"}
    account_id = str(payload.get("account_id") or getattr(client.config, "ad_account_id", "") or "").strip()
    before = payload.get("preconditions") if isinstance(payload.get("preconditions"), dict) else {}
    snapshots = {}
    for operation in operations:
        entity_type = operation.get("entity_type")
        entity_id = operation.get("entity_id")
        if entity_id in snapshots:
            continue
        live_result, live = _read_entity(client, entity_type, entity_id)
        if not live_result.get("ok"):
            return {"ok": False, "blocked": True, "error": "campaign_edit_target_read_failed", "target_id": entity_id, "result": live_result}
        snapshots[entity_id] = live
        expected = before.get(str(entity_id))
        if expected and expected != _fingerprint(live):
            return {"ok": False, "blocked": True, "error": "campaign_edit_stale_snapshot", "target_id": entity_id}
    applied = []
    results = []
    expected_graph = {}
    currency = str(payload.get("account_currency") or "").strip().upper()
    for operation in operations:
        entity_type = operation["entity_type"]
        entity_id = operation["entity_id"]
        changes = dict(operation.get("changes") or {})
        normalized, budget_error = _budget_amount(changes, currency, dashboard_contract)
        if normalized is None:
            return {"ok": False, "blocked": True, "error": budget_error, "applied": applied}
        changes = normalized
        old = snapshots[entity_id]
        graph_fields = {}
        creative_id = ""
        if entity_type == "adset" and any(key in changes for key in ("locations", "age_min", "age_max", "genders", "interest_ids", "targeting_mode", "placements")):
            current_targeting = old.get("targeting") if isinstance(old.get("targeting"), dict) else {}
            targeting, targeting_error = _build_targeting(client, current_targeting, changes)
            if targeting is None:
                return {"ok": False, "blocked": True, "error": targeting_error, "applied": applied}
            graph_fields["targeting"] = targeting
        for field in ("name", "start_time", "end_time", "status"):
            if field in changes:
                if field == "status" and str(changes[field]).upper() == "ACTIVE":
                    return {"ok": False, "blocked": True, "error": "activation_requires_separate_approval", "applied": applied}
                graph_fields[field] = changes[field]
        for field in ("daily_budget", "lifetime_budget"):
            if field in changes:
                graph_fields[field] = changes.get(f"_{field}_api", changes[field])
        if entity_type == "ad" and any(field in changes for field in AD_FIELDS if field not in {"name", "status"}):
            creative_fields = {key: value for key, value in changes.items() if key in AD_FIELDS and key not in {"name", "status"}}
            creative_patch, creative_error, creative_id = _make_creative_patch(client, account_id, old, creative_fields, approved=True)
            if not creative_patch:
                return {"ok": False, "blocked": True, "error": creative_error, "applied": applied}
            graph_fields.update(creative_patch)
        if not graph_fields:
            continue
        graph_fields["access_token"] = getattr(client.config, "meta_access_token", "")
        result = client.post_graph_form(entity_id, graph_fields)
        try:
            mutation_status = int(result.get("status") or 0)
        except (TypeError, ValueError):
            mutation_status = 0
        if not result.get("ok") or not 200 <= mutation_status < 300:
            return {"ok": False, "blocked": True, "error": "campaign_edit_graph_update_failed", "target_id": entity_id, "result": result, "applied": applied}
        expected_graph.setdefault(entity_id, {}).update({
            key: value for key, value in graph_fields.items() if key != "access_token"
        })
        applied.append({"entity_type": entity_type, "entity_id": entity_id, "fields": [key for key in graph_fields if key != "access_token"], "creative_id": creative_id})
        results.append(result)
    verification = []
    for operation in operations:
        entity_type = operation["entity_type"]
        entity_id = operation["entity_id"]
        live_result, live = _read_entity(client, entity_type, entity_id)
        if not live_result.get("ok"):
            return {"ok": False, "blocked": True, "error": "campaign_edit_readback_failed", "target_id": entity_id, "applied": applied}
        try:
            readback_status = int(live_result.get("status") or 0)
        except (TypeError, ValueError):
            readback_status = 0
        checks = {
            "target_id": entity_id,
            "ok": 200 <= readback_status < 300,
            "http_status": readback_status,
        }
        if not checks["ok"]:
            checks.setdefault("mismatches", []).append("graph_get_http_status")
        changes = operation.get("changes") or {}
        for field in ("name", "status", "start_time", "end_time"):
            if field in changes and str(live.get(field) or "") != str(changes[field] or ""):
                checks["ok"] = False
                checks.setdefault("mismatches", []).append(field)
        for field in ("daily_budget", "lifetime_budget"):
            if field in changes:
                try:
                    actual = int(live.get(field))
                    expected = int(changes.get(f"_{field}_api") or changes[field])
                except (TypeError, ValueError):
                    actual, expected = -1, -2
                if actual != expected:
                    checks["ok"] = False
                    checks.setdefault("mismatches", []).append(field)
        expected = expected_graph.get(entity_id) or {}
        if isinstance(expected.get("targeting"), dict):
            actual_targeting = live.get("targeting") if isinstance(live.get("targeting"), dict) else {}
            targeting_fields = []
            mapping = {
                "locations": ("geo_locations",), "age_min": ("age_min",), "age_max": ("age_max",),
                "genders": ("genders",), "interest_ids": ("interests",),
                "targeting_mode": ("targeting_automation",),
                "placements": (
                    "publisher_platforms", "facebook_positions", "instagram_positions",
                    "messenger_positions", "audience_network_positions", "threads_positions",
                ),
            }
            for requested_field, graph_names in mapping.items():
                if requested_field in changes:
                    targeting_fields.extend(graph_names)
            for field in dict.fromkeys(targeting_fields):
                wanted = expected["targeting"].get(field)
                actual = actual_targeting.get(field)
                if field == "targeting_automation" and wanted == {"advantage_audience": 0} and actual in (None, {}, {"advantage_audience": 0}):
                    continue
                if _canonical_graph_value(wanted) != _canonical_graph_value(actual):
                    checks["ok"] = False
                    checks.setdefault("mismatches", []).append(f"targeting.{field}")
        expected_creative = expected.get("creative") if isinstance(expected.get("creative"), dict) else {}
        if expected_creative.get("creative_id"):
            actual_creative = live.get("creative") if isinstance(live.get("creative"), dict) else {}
            if str(actual_creative.get("id") or "") != str(expected_creative["creative_id"]):
                checks["ok"] = False
                checks.setdefault("mismatches", []).append("creative.id")
            creative_mismatches = _creative_change_mismatches(changes, actual_creative)
            if creative_mismatches:
                checks["ok"] = False
                checks.setdefault("mismatches", []).extend(creative_mismatches)
        verification.append(checks)
    ok = all(item.get("ok") for item in verification)
    return {"ok": ok, "executed": True, "verified": ok, "campaign_id": payload.get("campaign_id"), "applied": applied, "verification": verification, "results": results}


def supersede_pending_edit(edit_id):
    pending = read_json(PENDING_FILE, [])
    if not isinstance(pending, list):
        return 0
    kept = []
    removed = 0
    for item in pending:
        if isinstance(item, dict) and item.get("type") == "campaign_edit" and str((item.get("payload") or {}).get("edit_id") or "") == str(edit_id):
            removed += 1
            continue
        kept.append(item)
    if removed:
        write_json(PENDING_FILE, kept)
    return removed


def mark_draft_status(draft_path, status, *, result=None):
    draft = _load_draft(draft_path)
    if not draft:
        return False
    draft["status"] = status
    draft["updated_at"] = _now()
    if result is not None:
        draft["last_result"] = result
    _atomic(draft_path, draft)
    return True


def prepare_campaign_edit(arguments, live_metrics, *, account_id="", conversation_id="", budget_contract=None):
    arguments = arguments if isinstance(arguments, dict) else {}
    reference = str(arguments.get("campaign_reference") or "").strip()
    request = str(arguments.get("change_request") or arguments.get("message") or "").strip()
    if len(request) < 5:
        return {"ok": False, "blocked": True, "reason": "campaign_edit_request_missing", "reply": "Necesito saber qué cambio quieres hacer en la campaña."}
    if len(request) > MAX_CHANGE_REQUEST_CHARS:
        return {"ok": False, "blocked": True, "reason": "campaign_edit_request_too_large"}
    metrics = live_metrics if isinstance(live_metrics, dict) else {}
    campaigns = metrics.get("campaigns") or []
    adsets = metrics.get("adsets") or []
    ads = metrics.get("ads") or []
    conversation_id = _conversation_key(conversation_id)
    account_id = str(account_id or metrics.get("account_id") or "").strip()
    index = _load_index()
    index_key = _safe_key(f"{conversation_id}:{account_id}")
    active = (index.get(index_key) or {}).get("active_campaign_id") if isinstance(index.get(index_key), dict) else ""
    resolution = resolve_campaign_reference(reference or request, campaigns, adsets, active_campaign_id=active)
    if not resolution.get("ok"):
        candidates = resolution.get("candidates") or []
        labels = [f"{item.get('name') or item.get('id')} ({item.get('id')})" for item in candidates[:5] if isinstance(item, dict)]
        if labels:
            reply = "Encontré más de una campaña posible: " + "; ".join(labels) + ". Indícame cuál quieres editar."
        elif resolution.get("reason") == "campaign_reference_missing":
            reply = "¿Cuál campaña quieres editar? Puedes mencionar su nombre, ciudad, destino o ID."
        else:
            reply = "No encontré una campaña única con esa referencia. Menciona el nombre, ciudad, destino o ID tal como aparece en Meta."
        return {"ok": False, "blocked": True, "reason": resolution.get("reason"), "candidates": candidates, "reply": reply}
    campaign_id = resolution["campaign_id"]
    campaign = resolution["campaign"]
    campaign_account = _clean_account_id(campaign.get("ad_account_id") or campaign.get("account_id"))
    active_account = _clean_account_id(account_id)
    if campaign_account and active_account and campaign_account != active_account:
        return {
            "ok": False,
            "blocked": True,
            "reason": "campaign_outside_active_account",
            "campaign_id": campaign_id,
            "campaign_name": campaign.get("name") or campaign_id,
            "reply": "Esa campaña pertenece a otra cuenta publicitaria. Primero selecciona esa cuenta de Meta; no preparé ningún cambio.",
        }
    snapshot = _snapshot_for(campaign, adsets, ads)
    path = _draft_path(conversation_id, account_id, campaign_id)
    draft = _load_draft(path)
    if not draft or draft.get("status") in {"applied", "rejected", "failed"}:
        draft = {
            "edit_id": f"edit-{campaign_id}-{_safe_key(_now())}",
            "campaign_id": campaign_id,
            "campaign_name": campaign.get("name") or campaign_id,
            "account_id": account_id,
            "conversation_key": conversation_id,
            "created_at": _now(),
            "status": "collecting",
            "requests": [],
        }
    elif draft.get("status") == "pending_approval":
        draft["status"] = "collecting"
    source_id = str(arguments.get("source_message_id") or _safe_key(request)).strip()
    if not any(str(item.get("source_message_id") or "") == source_id for item in draft.get("requests") or [] if isinstance(item, dict)):
        draft.setdefault("requests", []).append({"source_message_id": source_id, "reference": reference, "text": request, "received_at": _now()})
    compiled = compile_edit_plan(snapshot, draft.get("requests") or [], reference or request)
    if not compiled.get("ok"):
        draft["status"] = "collecting"
        draft["last_error"] = compiled
        _save_draft(draft, conversation_id=conversation_id, account_id=account_id, campaign_id=campaign_id, markdown=request)
        missing = ", ".join(str(value) for value in compiled.get("missing_fields") or [])
        return {"ok": False, "blocked": True, "reason": compiled.get("reason"), "campaign_id": campaign_id, "campaign_name": campaign.get("name") or campaign_id, "missing_fields": compiled.get("missing_fields") or [], "reply": f"No apliqué cambios a {campaign.get('name') or campaign_id}. Necesito precisar: {missing or 'el cambio solicitado'}."}
    operations = compiled.get("operations") or []
    account_currency = str(metrics.get("account_currency") or "").strip().upper()
    for operation in operations:
        normalized, budget_error = _budget_amount(dict(operation.get("changes") or {}), account_currency, budget_contract)
        if normalized is None:
            draft["status"] = "collecting"
            draft["last_error"] = {"reason": budget_error}
            _save_draft(draft, conversation_id=conversation_id, account_id=account_id, campaign_id=campaign_id, markdown=request)
            return {"ok": False, "blocked": True, "reason": budget_error, "campaign_id": campaign_id, "campaign_name": campaign.get("name") or campaign_id, "reply": "No preparé el cambio porque el monto o la moneda no coincide con la cuenta publicitaria."}
        operation["changes"] = normalized
    draft.update({"status": "ready", "revision": int(draft.get("revision") or 0) + 1, "snapshot": snapshot, "preconditions": _preconditions(snapshot), "operations": operations, "summary": compiled.get("summary"), "compiler_model": compiled.get("compiler_model"), "updated_at": _now()})
    markdown = "# Campaign edit\n\n" + "\n".join(f"- {item.get('text')}" for item in draft.get("requests") or []) + "\n"
    draft_path = _save_draft(draft, conversation_id=conversation_id, account_id=account_id, campaign_id=campaign_id, markdown=markdown)
    index[index_key] = {"active_campaign_id": campaign_id, "updated_at": _now()}
    _save_index(index)
    payload = {
        "edit_id": draft["edit_id"], "draft_path": str(draft_path), "campaign_id": campaign_id,
        "campaign_name": campaign.get("name") or campaign_id, "account_id": account_id,
        "account_currency": account_currency,
        "operations": operations, "preconditions": draft["preconditions"], "summary": compiled.get("summary"),
        "conversation_key": conversation_id, "revision": draft["revision"],
    }
    return {"ok": True, "staged": True, "campaign_id": campaign_id, "campaign_name": campaign.get("name") or campaign_id, "edit_id": draft["edit_id"], "summary": compiled.get("summary") or "Cambios preparados.", "pending_payload": payload, "draft": draft}
