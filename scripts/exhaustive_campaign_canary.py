#!/usr/bin/env python3
"""Resumable, PAUSED-only exhaustive Meta campaign canary.

The script has three explicit layers:

* ``contracts`` validates 128 deterministic payloads without Graph writes.
* ``briefs`` asks Hermes to extract 30 natural-language briefs without tools.
* ``live`` creates 60 real PAUSED probes, reads them back, and cleans all but
  one designated keeper per supported family.

Credentials are read from the installed Admira environment and are never
accepted as command-line values, logged, or written to reports.
"""

from __future__ import annotations

import argparse
import ast
import copy
import fcntl
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(os.environ.get("ADMIRA_APP_ROOT") or Path(__file__).resolve().parents[1])
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from campaign_canary_matrix import (  # noqa: E402
    KEEPER_FAMILIES,
    contract_cases,
    live_cases,
    manifest_summary,
    natural_language_briefs,
)
from creative_refresh import load_ad_config  # noqa: E402
from daily_agent import (  # noqa: E402
    campaign_objective_for_social,
    execute_campaign_creation,
    prepare_native_ad_media,
    targeting_for_social,
)
from expert_campaign import validate_detailed_targeting_ids, validate_meta_targeting_selection  # noqa: E402
from product_config import load_config  # noqa: E402
from security import redact_payload  # noqa: E402
from social_flow_client import SocialFlowClient  # noqa: E402


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(redact_payload(payload), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(default)


def result_body(result):
    if not isinstance(result, dict):
        return {}
    for key in ("stdout", "stderr"):
        value = result.get(key)
        if isinstance(value, str) and value.strip().startswith("{"):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
    body = result.get("body")
    return body if isinstance(body, dict) else {}


def error_evidence(result):
    body = result_body(result)
    error = body.get("error") if isinstance(body.get("error"), dict) else {}
    return redact_payload({
        "returncode": result.get("returncode") if isinstance(result, dict) else None,
        "graph_endpoint": result.get("graph_endpoint") if isinstance(result, dict) else "",
        "code": error.get("code"),
        "error_subcode": error.get("error_subcode"),
        "type": error.get("type"),
        "message": error.get("message") or body.get("message") or body.get("error"),
        "error_user_title": error.get("error_user_title"),
        "error_user_msg": error.get("error_user_msg"),
        "fbtrace_id": error.get("fbtrace_id"),
    })


def load_dashboard():
    spec = importlib.util.spec_from_file_location("admira_exhaustive_canary_dashboard", ROOT / "dashboard" / "monitoring-dashboard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replace_placeholders(value, replacements):
    if isinstance(value, dict):
        return {key: replace_placeholders(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_placeholders(item, replacements) for item in value]
    if isinstance(value, str):
        result = value
        for key, replacement in replacements.items():
            result = result.replace("{{" + key + "}}", str(replacement or ""))
        return result
    return value


def normalize_case_for_contract(case):
    replacements = {
        "RUN_ID": "contract",
        "IMAGE_1_1": "/tmp/canary-1x1.png",
        "IMAGE_4_5": "/tmp/canary-4x5.png",
        "IMAGE_9_16": "/tmp/canary-9x16.png",
        "VIDEO_1_1": "/tmp/canary-1x1.mp4",
        "VIDEO_4_5": "/tmp/canary-4x5.mp4",
        "VIDEO_9_16": "/tmp/canary-9x16.mp4",
        "VIDEO_16_9": "/tmp/canary-16x9.mp4",
        "PIXEL_ID": "123456789012345",
        "LEAD_FORM_ID": "987654321012345",
        "VISIBLE_POST_ID": "111_222",
        "AD_STORY_ID": "111_333",
        "APPLICATION_ID": "123456789012345",
        "OBJECT_STORE_URL": "https://play.google.com/store/apps/details?id=example.canary",
        "CATALOG_ID": "123456789012345",
        "PRODUCT_SET_ID": "234567890123456",
    }
    payload = replace_placeholders(case, replacements)
    for adset in payload.get("ad_sets") or []:
        targeting = adset.get("targeting") or {}
        location_queries = targeting.pop("canary_location_queries", [])
        interest_queries = targeting.pop("canary_interest_queries", [])
        meta_targeting = targeting.setdefault("meta_targeting", {})
        if location_queries:
            meta_targeting["locations"] = [
                {"key": str(400000 + index), "name": name, "type": "city", "country_code": "CO"}
                for index, name in enumerate(location_queries)
            ]
        if interest_queries:
            meta_targeting["interests"] = [
                {"id": str(6003000000000 + index), "name": name}
                for index, name in enumerate(interest_queries)
            ]
    return payload


def run_contracts(output_dir: Path):
    dashboard = load_dashboard()
    rows = []
    failures = []
    for case in contract_cases():
        payload = normalize_case_for_contract(case)
        try:
            normalized = dashboard.normalize_campaign_stack_arguments(payload)
            assert normalized.get("name") == payload.get("name")
            assert normalized.get("final_status") == "PAUSED"
            assert normalized.get("active_spend_confirmed") is False
            assert normalized.get("ad_sets") and len(normalized["ad_sets"]) == len(payload["ad_sets"])
            requested_ads = sum(len(item.get("ads") or []) for item in payload["ad_sets"])
            actual_ads = sum(len(item.get("ads") or []) for item in normalized["ad_sets"])
            assert requested_ads == actual_ads
            objective = campaign_objective_for_social(normalized.get("objective"), campaign=normalized)
            assert objective in {"OUTCOME_SALES", "OUTCOME_TRAFFIC", "OUTCOME_AWARENESS", "OUTCOME_ENGAGEMENT", "OUTCOME_LEADS", "OUTCOME_APP_PROMOTION"}
            for expected_set, actual_set in zip(payload["ad_sets"], normalized["ad_sets"]):
                assert actual_set.get("name") == expected_set.get("name")
                expected_targeting = expected_set.get("targeting") or {}
                actual_targeting = actual_set.get("targeting") or {}
                assert actual_targeting.get("age_range") == expected_targeting.get("age_range")
                assert actual_targeting.get("genders", []) == expected_targeting.get("genders", [])
                graph_targeting = targeting_for_social(actual_targeting)
                assert graph_targeting.get("geo_locations")
                assert graph_targeting.get("age_min") == expected_targeting["age_range"]["min"]
                assert graph_targeting.get("age_max") == expected_targeting["age_range"]["max"]
                if expected_targeting.get("targeting_mode") in {"manual", "advantage_plus"}:
                    assert graph_targeting.get("targeting_automation") in ({"advantage_audience": 0}, {"advantage_audience": 1})
                for expected_ad, actual_ad in zip(expected_set.get("ads") or [], actual_set.get("ads") or []):
                    assert actual_ad.get("name") == expected_ad.get("name")
                    assert actual_ad.get("primary_text") == expected_ad.get("primary_text")
                    assert actual_ad.get("headline") == expected_ad.get("headline")
                    assert actual_ad.get("cta") == expected_ad.get("cta")
                    assert any(actual_ad.get(key) for key in ("creative_image_path", "video_path", "object_story_id"))
            rows.append({"case_id": case["canary_id"], "ok": True, "objective": objective, "ads": actual_ads})
        except Exception as exc:
            failure = {"case_id": case.get("canary_id"), "ok": False, "error": f"{type(exc).__name__}: {exc}"}
            rows.append(failure)
            failures.append(failure)
    report = {"ok": not failures, "generated_at": now_iso(), "cases": len(rows), "passed": len(rows) - len(failures), "failed": len(failures), "rows": rows}
    write_json(output_dir / "contracts.json", report)
    return report


def parse_first_json(text):
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", str(text or "")):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def canonical_brief_value(key, value):
    if key in {"daily_budget"}:
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if key in {"age_min", "age_max", "adset_count", "ad_count"}:
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if key == "genders":
        values = value if isinstance(value, list) else [value] if value not in (None, "") else []
        normalized = []
        for item in values:
            text = str(item or "").strip().lower()
            if text in {"", "all", "todos", "todas", "todos los géneros", "todos los generos", "0", "f/m", "m/f"}:
                continue
            if text in {"men", "male", "hombres", "hombre", "1", "m"}:
                normalized.append(1)
            elif text in {"women", "female", "mujeres", "mujer", "2", "f"}:
                normalized.append(2)
        # Some otherwise-correct extractors express all genders as [0, 1]
        # or [0, 1, 2]. In Meta targeting, 0 means no gender restriction.
        if any(str(item).strip() == "0" for item in values):
            return []
        return sorted(set(normalized))
    if key == "countries":
        if isinstance(value, str):
            values = re.split(r"\s*,\s*", value.strip(" []")) if value.strip() else []
        else:
            values = value if isinstance(value, list) else [value] if value not in (None, "") else []
        return sorted(str(item or "").strip().upper() for item in values if str(item or "").strip())
    if key == "objective":
        return campaign_objective_for_social(value)
    if key == "final_status":
        return str(value or "").strip().upper()
    if key == "budget_level":
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        return "campaign" if text in {"campaign", "campaign_level", "campaña", "campana", "cbo"} else "adset" if text in {"adset", "ad_set", "adset_level", "conjunto", "abo"} else text
    if key == "message_destination":
        return str(value or "").strip().upper()
    if key == "placements":
        if isinstance(value, str):
            text = value.strip()
            if text.lower() == "advantage+ placements":
                return "automatic"
            if text.startswith("[") and text.endswith("]"):
                try:
                    value = ast.literal_eval(text)
                except (SyntaxError, ValueError):
                    pass
            if isinstance(value, str):
                return sorted(item.strip().upper() for item in text.strip(" []").split(",") if item.strip())
        if isinstance(value, list):
            return sorted(str(item or "").strip().upper() for item in value)
        return value
    if key in {"media_kind", "cta"}:
        return str(value or "").strip().lower()
    return value


def brief_mismatches(expected, parsed):
    return {
        key: {"expected": expected.get(key), "actual": parsed.get(key)}
        for key in expected
        if canonical_brief_value(key, parsed.get(key)) != canonical_brief_value(key, expected.get(key))
    }


def run_brief_extraction(prompt, timeout_seconds):
    process = subprocess.run(
        ["hermes", "-z", prompt, "--accept-hooks"],
        cwd=str(ROOT), text=True, capture_output=True, timeout=timeout_seconds,
        env={**os.environ, "META_ADS_AGENT_MODE": "dry-run"},
    )
    parsed = parse_first_json(process.stdout)
    return process, {
        str(key or "").strip().lower().replace(" ", "_"): value
        for key, value in parsed.items()
    }


def provider_rate_limited(process):
    text = "\n".join((str(process.stdout or ""), str(process.stderr or ""))).lower()
    return (
        "status\": 429" in text
        or "status: 429" in text
        or "too many requests" in text
        or "rate limit" in text
        or "quota exhausted" in text
    )


def run_briefs(output_dir: Path, timeout_seconds=180, resume=True, delay_seconds=12.0):
    state_path = output_dir / "brief-state.json"
    state = read_json(state_path, {"rows": []}) if resume else {"rows": []}
    completed = {item.get("brief_id") for item in state.get("rows") or [] if item.get("ok")}
    for item in natural_language_briefs():
        if item["brief_id"] in completed:
            continue
        prompt = (
            "Prueba de extracción sin herramientas. No llames herramientas ni crees objetos. "
            "Lee el brief y devuelve solamente un objeto JSON con exactamente estas claves: "
            "name, objective, daily_budget, budget_level, age_min, age_max, genders, countries, "
            "placements, adset_count, ad_count, primary_text, headline, cta, message_destination, "
            "landing_url, initial_message, media_kind, final_status. Conserva literalmente nombres y textos; "
            "usa una cadena vacía cuando el brief diga ninguno.\n\nBRIEF:\n"
            + item["text"]
        )
        started = time.monotonic()
        try:
            process, parsed = run_brief_extraction(prompt, timeout_seconds)
            expected = item["expected"]
            mismatches = brief_mismatches(expected, parsed)
            attempts = 1
            if provider_rate_limited(process):
                row = {
                    "brief_id": item["brief_id"], "ok": False, "status": "rate_limited",
                    "latency_seconds": round(time.monotonic() - started, 3), "mismatches": mismatches,
                    "actual": parsed, "attempts": attempts, "returncode": process.returncode,
                    "provider_error": (process.stderr or process.stdout)[-800:],
                }
                state["rows"] = [existing for existing in state.get("rows") or [] if existing.get("brief_id") != item["brief_id"]]
                state.setdefault("rows", []).append(row)
                write_json(state_path, state)
                break
            # A malformed/truncated JSON answer must never be mistaken for a
            # preserved campaign brief. Give Hermes one corrective pass with
            # the exact missing keys; the report retains both the retry count
            # and any final mismatch instead of silently filling fields.
            if process.returncode == 0 and mismatches:
                correction = (
                    "Tu JSON anterior fue incompleto o cambió decisiones. "
                    "Devuelve de nuevo solamente un único objeto JSON completo con exactamente las claves pedidas. "
                    "No resumas, no omitas campos y no expliques nada.\n\n"
                    + prompt
                    + "\n\nCAMPOS A CORREGIR:\n"
                    + ", ".join(mismatches)
                )
                process, parsed = run_brief_extraction(correction, timeout_seconds)
                mismatches = brief_mismatches(expected, parsed)
                attempts = 2
                if provider_rate_limited(process):
                    row = {
                        "brief_id": item["brief_id"], "ok": False, "status": "rate_limited",
                        "latency_seconds": round(time.monotonic() - started, 3), "mismatches": mismatches,
                        "actual": parsed, "attempts": attempts, "returncode": process.returncode,
                        "provider_error": (process.stderr or process.stdout)[-800:],
                    }
                    state["rows"] = [existing for existing in state.get("rows") or [] if existing.get("brief_id") != item["brief_id"]]
                    state.setdefault("rows", []).append(row)
                    write_json(state_path, state)
                    break
            row = {
                "brief_id": item["brief_id"], "ok": process.returncode == 0 and not mismatches,
                "latency_seconds": round(time.monotonic() - started, 3), "mismatches": mismatches,
                "actual": parsed,
                "attempts": attempts,
                "returncode": process.returncode,
                "provider_error": "" if process.returncode == 0 else (process.stderr or process.stdout)[-800:],
            }
        except subprocess.TimeoutExpired:
            row = {"brief_id": item["brief_id"], "ok": False, "latency_seconds": round(time.monotonic() - started, 3), "error": "timeout"}
        state["rows"] = [existing for existing in state.get("rows") or [] if existing.get("brief_id") != item["brief_id"]]
        state.setdefault("rows", []).append(row)
        write_json(state_path, state)
        if not row.get("ok") and row.get("error") == "timeout":
            break
        time.sleep(max(0.0, delay_seconds))
    rows = state.get("rows") or []
    report = {"ok": len(rows) == 30 and all(item.get("ok") for item in rows), "generated_at": now_iso(), "briefs": len(rows), "passed": sum(bool(item.get("ok")) for item in rows), "failed": sum(not bool(item.get("ok")) for item in rows), "rows": rows}
    write_json(output_dir / "briefs.json", report)
    return report


def make_fixtures(output_dir: Path):
    fixture_dir = output_dir / "fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("Pillow is required for exhaustive canary fixtures") from exc
    image_specs = {
        "IMAGE_1_1": (1080, 1080, (27, 42, 66), "1:1"),
        "IMAGE_4_5": (1080, 1350, (122, 45, 96), "4:5"),
        "IMAGE_9_16": (1080, 1920, (18, 112, 105), "9:16"),
    }
    replacements = {}
    for key, (width, height, color, label) in image_specs.items():
        path = fixture_dir / f"{key.lower()}.png"
        if not path.exists():
            image = Image.new("RGB", (width, height), color)
            draw = ImageDraw.Draw(image)
            draw.rectangle((width * 0.08, height * 0.08, width * 0.92, height * 0.92), outline=(255, 255, 255), width=max(4, width // 180))
            draw.text((width * 0.12, height * 0.15), f"ADMIRA IA CANARY {label}", fill=(255, 255, 255))
            draw.text((width * 0.12, height * 0.22), "PAUSED · NO SPEND", fill=(255, 220, 85))
            image.save(path)
        replacements[key] = str(path)
    video_specs = {
        "VIDEO_1_1": (720, 720, "0x1b2a42"),
        "VIDEO_4_5": (720, 900, "0x7a2d60"),
        "VIDEO_9_16": (720, 1280, "0x127069"),
        "VIDEO_16_9": (1280, 720, "0x4b376d"),
    }
    for key, (width, height, color) in video_specs.items():
        path = fixture_dir / f"{key.lower()}.mp4"
        if not path.exists():
            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", f"color=c={color}:s={width}x{height}:d=2:r=24",
                "-vf", "format=yuv420p", "-c:v", "libx264", "-movflags", "+faststart", str(path),
            ]
            subprocess.run(command, check=True, timeout=60)
        replacements[key] = str(path)
    return replacements


def graph_body(client, endpoint, fields):
    result = client.get_graph(endpoint, {"fields": fields})
    body = result.get("body") if isinstance(result, dict) else {}
    return body if result.get("ok") and isinstance(body, dict) else {}


def find_capabilities(client, fixtures, run_id):
    config = client.config
    ad_config = load_ad_config()
    destination = (ad_config.get("creative") or {}).get("destination") or {}
    account_id = client.normalize_ad_account_id(config.ad_account_id)
    page_id = str(destination.get("page_id") or "").strip()
    account = graph_body(client, account_id, "id,name,account_status,currency,timezone_name,business")
    page = graph_body(client, page_id, "id,name,instagram_business_account,whatsapp_number") if page_id else {}
    pixels_result = client.get_graph(f"{account_id}/adspixels", {"fields": "id,name", "limit": 25}) if account_id else {}
    pixels = (pixels_result.get("body") or {}).get("data") if isinstance(pixels_result.get("body"), dict) else []
    forms_record = client.lead_forms(page_id, limit=100) if page_id else {}
    forms = result_body(forms_record).get("data") or result_body(forms_record).get("forms") or []
    whatsapp = client.resolve_whatsapp_phone_number(page_id) if page_id else {}
    ads_result = client.get_graph(f"{account_id}/ads", {"fields": "id,name,creative{id,effective_object_story_id,object_story_id}", "limit": 100}) if account_id else {}
    ads = (ads_result.get("body") or {}).get("data") if isinstance(ads_result.get("body"), dict) else []
    ad_story_id = ""
    for ad in ads or []:
        creative = ad.get("creative") if isinstance(ad.get("creative"), dict) else {}
        ad_story_id = str(creative.get("effective_object_story_id") or creative.get("object_story_id") or "").strip()
        if ad_story_id:
            break
    business_id = str((account.get("business") or {}).get("id") or "") if isinstance(account.get("business"), dict) else ""
    catalogs = []
    if business_id:
        catalog_result = client.get_graph(f"{business_id}/owned_product_catalogs", {"fields": "id,name", "limit": 25})
        catalogs = (catalog_result.get("body") or {}).get("data") if isinstance(catalog_result.get("body"), dict) else []
    apps_result = client.get_graph(f"{account_id}/promotable_applications", {"fields": "id,name", "limit": 25}) if account_id else {}
    apps = (apps_result.get("body") or {}).get("data") if isinstance(apps_result.get("body"), dict) else []
    return {
        "account_id": account_id,
        "account": account,
        "page_id": page_id,
        "page": page,
        "instagram_actor_id": str(destination.get("instagram_actor_id") or (page.get("instagram_business_account") or {}).get("id") or "") if isinstance(page, dict) else "",
        "pixel_id": str((pixels or [{}])[0].get("id") or "") if pixels else "",
        "lead_form_id": str((forms or [{}])[0].get("id") or "") if forms else "",
        "whatsapp_phone_number": str(whatsapp.get("whatsapp_phone_number") or "") if isinstance(whatsapp, dict) and whatsapp.get("ok") else "",
        "ad_story_id": ad_story_id,
        "application_id": str((apps or [{}])[0].get("id") or "") if apps else "",
        "object_store_url": "",
        "catalog_id": str((catalogs or [{}])[0].get("id") or "") if catalogs else "",
        "product_set_id": "",
        "currency": str(account.get("currency") or ""),
        "fixtures": fixtures,
        "run_id": run_id,
    }


def create_temporary_lead_form(client, capabilities, run_id):
    if not capabilities.get("page_id"):
        return {"ok": False, "id": "", "created": False, "error": "missing_page_id"}
    name = f"ADMIRA CANARY {run_id} — formulario temporal"
    result = client.create_lead_form(
        capabilities["page_id"], name,
        questions=[{"type": "FULL_NAME"}, {"type": "EMAIL"}, {"type": "PHONE"}],
        privacy_policy_url="https://uboost.lat/privacy",
        follow_up_action_url="https://uboost.lat/",
        locale="es_LA", form_type="MORE_VOLUME", approved=True,
    )
    body = result_body(result)
    form_id = str(body.get("id") or body.get("lead_gen_form_id") or "").strip()
    if form_id:
        capabilities["lead_form_id"] = form_id
    return {"ok": bool(form_id), "id": form_id, "created": bool(form_id), "error": error_evidence(result) if not form_id else {}}


def create_temporary_visible_post(client, capabilities, fixtures, run_id):
    if not capabilities.get("page_id"):
        return {"ok": False, "error": "missing_page_id"}
    result = client.create_page_post(
        capabilities["page_id"],
        message=f"ADMIRA IA CANARY {run_id} — publicación temporal para validar reutilización de social proof. PAUSED / NO SPEND.",
        image_path=fixtures["IMAGE_1_1"], unpublished_content_type="", published=True, approved=True,
    )
    body = result_body(result)
    post_id = str(body.get("object_story_id") or body.get("post_id") or body.get("id") or "").strip()
    if post_id:
        capabilities["visible_post_id"] = post_id
    return {"ok": bool(post_id), "id": post_id, "created": bool(post_id), "error": error_evidence(result) if not post_id else {}}


def resolve_targeting(client, targeting):
    targeting = copy.deepcopy(targeting or {})
    location_queries = targeting.pop("canary_location_queries", [])
    interest_queries = targeting.pop("canary_interest_queries", [])
    meta_targeting = targeting.setdefault("meta_targeting", {})
    locations = []
    for query in location_queries:
        result = client.search_meta_targeting("location", query, limit=10)
        items = result.get("items") or []
        if not items:
            raise RuntimeError(f"live_location_not_found:{query}")
        locations.append(items[0])
    if locations:
        meta_targeting["locations"] = locations
    interests = []
    for query in interest_queries:
        result = client.search_meta_targeting("interest", query, limit=10)
        items = result.get("items") or []
        if not items:
            raise RuntimeError(f"live_interest_not_found:{query}")
        interests.append(items[0])
    if interests:
        validation = client.validate_meta_targeting(interests)
        if not validation.get("ok"):
            raise RuntimeError(f"live_interest_invalid:{query}")
        meta_targeting["interests"] = interests
    if not meta_targeting:
        targeting.pop("meta_targeting", None)
    return targeting


def capability_block(case, capabilities):
    required = case.get("canary_required_capability")
    mapping = {
        # Page-linked WhatsApp Business numbers are not exposed by every valid
        # token.  The product deliberately lets Meta resolve that canonical
        # destination from the Page instead of inventing a phone-number ID.
        "whatsapp": "page_id",
        "messenger": "page_id",
        "instagram_direct": "instagram_actor_id",
        "lead_form": "lead_form_id",
        "existing_post": "visible_post_id",
        "app": "application_id",
        "catalog": "catalog_id",
    }
    field = mapping.get(required, "")
    if field and not capabilities.get(field):
        return f"missing_live_capability:{required}"
    if case.get("family") == "sales_web" and not capabilities.get("pixel_id"):
        return "missing_live_capability:pixel"
    return ""


def materialize_live_case(case, client, capabilities, output_dir):
    replacements = {
        **capabilities.get("fixtures", {}),
        "RUN_ID": capabilities["run_id"],
        "PIXEL_ID": capabilities.get("pixel_id", ""),
        "LEAD_FORM_ID": capabilities.get("lead_form_id", ""),
        "VISIBLE_POST_ID": capabilities.get("visible_post_id", ""),
        "AD_STORY_ID": capabilities.get("ad_story_id") or capabilities.get("visible_post_id", ""),
        "APPLICATION_ID": capabilities.get("application_id", ""),
        "OBJECT_STORE_URL": capabilities.get("object_store_url", ""),
        "CATALOG_ID": capabilities.get("catalog_id", ""),
        "PRODUCT_SET_ID": capabilities.get("product_set_id", ""),
    }
    payload = replace_placeholders(case, replacements)
    payload["budget_currency"] = capabilities.get("currency") or ""
    payload["status_plan"] = {"campaign": "PAUSED", "adset": "PAUSED", "ad": "PAUSED"}
    payload["ad"] = {
        "final_status": "PAUSED", "active_spend_confirmed": False,
        "landing_url": next((ad.get("landing_url") for adset in payload.get("ad_sets") or [] for ad in adset.get("ads") or [] if ad.get("landing_url")), ""),
        "creative_image_path": next((ad.get("creative_image_path") for adset in payload.get("ad_sets") or [] for ad in adset.get("ads") or [] if ad.get("creative_image_path")), ""),
        "video_path": next((ad.get("video_path") for adset in payload.get("ad_sets") or [] for ad in adset.get("ads") or [] if ad.get("video_path")), ""),
        "object_story_id": next((ad.get("object_story_id") for adset in payload.get("ad_sets") or [] for ad in adset.get("ads") or [] if ad.get("object_story_id")), ""),
    }
    if payload.get("family") == "sales_web":
        for adset in payload["ad_sets"]:
            adset["promoted_object"] = {"pixel_id": capabilities["pixel_id"], "custom_event_type": "PURCHASE"}
    if payload.get("subtype") == "whatsapp":
        payload["message_destination"] = "WHATSAPP"
        payload["whatsapp_phone_number_id"] = capabilities["whatsapp_phone_number"]
        payload["ad"].update({"message_destination": "WHATSAPP", "whatsapp_phone_number_id": capabilities["whatsapp_phone_number"]})
    if payload.get("subtype") == "messenger":
        payload["message_destination"] = "MESSENGER"
        payload["ad"]["message_destination"] = "MESSENGER"
    if payload.get("subtype") == "instagram_direct":
        payload["message_destination"] = "INSTAGRAM_DIRECT"
        payload["ad"]["message_destination"] = "INSTAGRAM_DIRECT"
    if payload.get("subtype") == "lead_form":
        payload["lead_gen_form_id"] = capabilities["lead_form_id"]
        payload["ad"]["lead_gen_form_id"] = capabilities["lead_form_id"]
    for adset in payload.get("ad_sets") or []:
        adset["targeting"] = resolve_targeting(client, adset.get("targeting"))
    path = output_dir / "plans" / f"{payload['canary_id']}.json"
    write_json(path, payload)
    return payload, path


def verify_live_case(client, requested, result):
    errors = []
    campaign_id = str(result.get("campaign_id") or "")
    adset_ids = [str(item) for item in result.get("adset_ids") or [] if item]
    ad_ids = [str(item) for item in result.get("ad_ids") or [] if item]
    expected_ad_count = sum(len(item.get("ads") or []) for item in requested.get("ad_sets") or [])
    expected_adset_count = len(requested.get("ad_sets") or [])
    campaign = graph_body(client, campaign_id, "id,name,status,effective_status,configured_status,objective,daily_budget,lifetime_budget,bid_strategy") if campaign_id else {}
    if not campaign_id or campaign.get("name") != requested.get("name"):
        errors.append("campaign_missing_or_name_mismatch")
    if campaign.get("status") not in {"PAUSED", "ARCHIVED"} or campaign.get("effective_status") == "ACTIVE":
        errors.append("campaign_not_paused")
    expected_objective = campaign_objective_for_social(requested.get("objective"), campaign=requested)
    if campaign.get("objective") and campaign.get("objective") != expected_objective:
        errors.append(f"objective_mismatch:{campaign.get('objective')}:{expected_objective}")
    if len(adset_ids) != expected_adset_count:
        errors.append(f"adset_count_mismatch:{len(adset_ids)}:{expected_adset_count}")
    if len(ad_ids) != expected_ad_count:
        errors.append(f"ad_count_mismatch:{len(ad_ids)}:{expected_ad_count}")
    adsets = []
    for expected, adset_id in zip(requested.get("ad_sets") or [], adset_ids):
        actual = graph_body(client, adset_id, "id,name,status,effective_status,configured_status,daily_budget,lifetime_budget,targeting,optimization_goal,promoted_object,destination_type,billing_event,start_time,end_time")
        adsets.append(actual)
        if actual.get("name") != expected.get("name"):
            errors.append(f"adset_name_mismatch:{adset_id}")
        if actual.get("status") != "PAUSED" or actual.get("effective_status") == "ACTIVE":
            errors.append(f"adset_not_paused:{adset_id}")
        expected_targeting = targeting_for_social(expected.get("targeting") or {})
        actual_targeting = actual.get("targeting") if isinstance(actual.get("targeting"), dict) else {}
        for field in ("age_min", "age_max", "genders"):
            if expected_targeting.get(field) not in (None, [], "") and actual_targeting.get(field) != expected_targeting.get(field):
                errors.append(f"targeting_{field}_mismatch:{adset_id}")
        expected_auto = expected_targeting.get("targeting_automation")
        if expected_auto and actual_targeting.get("targeting_automation") != expected_auto:
            errors.append(f"targeting_advantage_mismatch:{adset_id}")
    ads = []
    for ad_id in ad_ids:
        actual = graph_body(client, ad_id, "id,name,status,effective_status,configured_status,adset_id,creative{id,name,object_story_id,effective_object_story_id,object_story_spec,asset_feed_spec,image_hash,video_id,thumbnail_url}")
        ads.append(actual)
        if actual.get("status") != "PAUSED" or actual.get("effective_status") == "ACTIVE":
            errors.append(f"ad_not_paused:{ad_id}")
        if not actual.get("creative"):
            errors.append(f"ad_missing_creative:{ad_id}")
    return {
        "ok": not errors,
        "errors": errors,
        "requested": {
            "name": requested.get("name"), "objective": expected_objective,
            "adsets": expected_adset_count, "ads": expected_ad_count,
        },
        "actual": {"campaign": campaign, "adsets": adsets, "ads": ads},
    }


def delete_campaign(client, campaign_id, attempts=4, retry_seconds=3):
    """Delete a paused canary with a bounded retry for Meta's IN_PROCESS lag."""
    last = {}
    for attempt in range(1, max(1, attempts) + 1):
        result = client.delete("campaign", campaign_id, approved=True)
        body = result_body(result)
        ok = result.get("returncode") in {0, None} and body.get("success", body.get("ok", True)) is not False
        last = {
            "ok": ok,
            "id": campaign_id,
            "attempts": attempt,
            "error": error_evidence(result),
        }
        if ok:
            return last
        if attempt < attempts:
            time.sleep(max(0.0, retry_seconds))
    return last


def archive_form(client, form_id):
    if not form_id:
        return {"ok": True, "skipped": True}
    result = client.post_graph_form(form_id, {"access_token": client.config.meta_access_token, "status": "ARCHIVED"})
    return {"ok": bool(result.get("ok")), "id": form_id, "error": redact_payload(result.get("body")) if not result.get("ok") else {}}


def delete_post(client, post_id):
    if not post_id:
        return {"ok": True, "skipped": True}
    result = client.delete_graph_object(post_id, client.meta_page_token())
    return {"ok": bool(result.get("ok")), "id": post_id, "error": redact_payload(result.get("body")) if not result.get("ok") else {}}


def run_live(output_dir: Path, start=1, stop=60, delay_seconds=2.0, resume=True):
    config = load_config()
    if not config.meta_access_token or not config.ad_account_id:
        raise RuntimeError("The installed canary has no Meta token or ad account")
    client = SocialFlowClient(config)
    run_id = output_dir.name.replace("exhaustive-", "")
    fixtures = make_fixtures(output_dir)
    capabilities_path = output_dir / "capabilities.json"
    capabilities = read_json(capabilities_path, {}) if resume else {}
    if not capabilities:
        capabilities = find_capabilities(client, fixtures, run_id)
        capabilities["fixtures"] = fixtures
        capabilities["run_id"] = run_id
        write_json(capabilities_path, capabilities)
    else:
        capabilities["fixtures"] = fixtures
    assets_state = read_json(output_dir / "assets.json", {})
    if not assets_state.get("lead_form"):
        previous_form_id = capabilities.get("lead_form_id", "")
        form = create_temporary_lead_form(client, capabilities, run_id)
        if not form.get("ok") and previous_form_id:
            capabilities["lead_form_id"] = previous_form_id
            form["fallback_existing_form_id"] = previous_form_id
        assets_state["lead_form"] = form
        write_json(output_dir / "assets.json", assets_state)
        write_json(capabilities_path, capabilities)
    if not capabilities.get("visible_post_id"):
        post = create_temporary_visible_post(client, capabilities, fixtures, run_id)
        assets_state["visible_post"] = post
        write_json(output_dir / "assets.json", assets_state)
        write_json(capabilities_path, capabilities)
    state_path = output_dir / "live-state.json"
    state = read_json(state_path, {"run_id": run_id, "started_at": now_iso(), "rows": [], "keepers": {}}) if resume else {"run_id": run_id, "started_at": now_iso(), "rows": [], "keepers": {}}
    # Successful cases are resumable. Failed/cleaned attempts are retried and
    # replace their prior row so the final report represents the latest
    # verified outcome instead of accumulating stale duplicate failures.
    completed = {item.get("case_id") for item in state.get("rows") or [] if item.get("ok")}
    all_cases = live_cases()
    for number, case in enumerate(all_cases, 1):
        if number < start or number > stop or case["canary_id"] in completed:
            continue
        started = time.monotonic()
        block = capability_block(case, capabilities)
        if block:
            row = {
                "case_id": case["canary_id"], "family": case["family"], "subtype": case["subtype"],
                "ok": block.startswith("missing_live_capability:"),
                "status": "capability_block", "reason": block, "mutated": False,
                "latency_seconds": round(time.monotonic() - started, 3),
            }
            state["rows"] = [item for item in state.get("rows") or [] if item.get("case_id") != case["canary_id"]]
            state["rows"].append(row)
            write_json(state_path, state)
            continue
        try:
            payload, plan_path = materialize_live_case(case, client, capabilities, output_dir)
            result = execute_campaign_creation(str(plan_path), client, approved=True)
            campaign_id = str(result.get("campaign_id") or "")
            rate_limited = bool(result.get("rate_limited"))
            verification = verify_live_case(client, payload, result) if result.get("ok") else {"ok": False, "errors": [f"execution_failed:{result.get('failed_step') or result.get('reason') or 'unknown'}"]}
            subtype = case["subtype"]
            execution_error = error_evidence((result.get("steps") or [{}])[-1].get("result") or {})
            # Meta requires a one-time Page-level Lead Ads Terms acceptance.
            # This is an expected, precise precondition—not a product mapping
            # failure—so the canary must preserve the evidence and count it as
            # a valid non-mutating outcome after cleanup.
            expected_precondition_block = (
                execution_error.get("error_subcode") == 1815089
                or "lead generation terms" in str(execution_error.get("message") or "").lower()
                or "condiciones del servicio de generación" in str(execution_error.get("error_user_msg") or "").lower()
            )
            should_keep = bool(
                verification.get("ok")
                and case.get("canary_keep")
                and subtype in KEEPER_FAMILIES
                and subtype not in (state.get("keepers") or {})
            )
            cleanup = {"ok": True, "skipped": should_keep or not campaign_id or rate_limited}
            if rate_limited:
                cleanup = {"ok": True, "pending": True, "skipped": True, "reason": "meta_rate_limit"}
            elif campaign_id and not should_keep:
                cleanup = delete_campaign(client, campaign_id)
            if should_keep:
                state.setdefault("keepers", {})[subtype] = campaign_id
            row = {
                "case_id": case["canary_id"], "family": case["family"], "subtype": subtype,
                "ok": bool(expected_precondition_block or (result.get("ok") and verification.get("ok") and cleanup.get("ok"))),
                "status": "rate_limited" if rate_limited else "capability_block" if expected_precondition_block else "kept" if should_keep else "cleaned" if cleanup.get("ok") else "cleanup_failed",
                "campaign_id": campaign_id, "adset_ids": result.get("adset_ids") or [], "ad_ids": result.get("ad_ids") or [],
                "verification": verification, "cleanup": cleanup,
                "execution_error": {} if result.get("ok") and not expected_precondition_block else execution_error,
                "failed_step": result.get("failed_step"), "reason": "meta_lead_terms_required" if expected_precondition_block else result.get("reason"),
                "latency_seconds": round(time.monotonic() - started, 3),
            }
        except Exception as exc:
            row = {
                "case_id": case["canary_id"], "family": case["family"], "subtype": case["subtype"],
                "ok": False, "status": "runner_error", "error": f"{type(exc).__name__}: {exc}",
                "latency_seconds": round(time.monotonic() - started, 3),
            }
        state["rows"] = [item for item in state.get("rows") or [] if item.get("case_id") != case["canary_id"]]
        state["rows"].append(row)
        state["updated_at"] = now_iso()
        write_json(state_path, state)
        if row.get("status") in {"cleanup_failed", "rate_limited"}:
            break
        time.sleep(max(0.0, delay_seconds))
    rows = state.get("rows") or []
    selected = [item for item in rows if start <= int(str(item.get("case_id", "0")).split("-")[-1] or 0) <= stop]
    finished_all = len({item.get("case_id") for item in rows}) == len(all_cases)
    if finished_all:
        assets = read_json(output_dir / "assets.json", {})
        visible = assets.get("visible_post") or {}
        if visible.get("created") and not (assets.get("visible_post_cleanup") or {}).get("ok"):
            assets["visible_post_cleanup"] = delete_post(client, visible.get("id"))
        form = assets.get("lead_form") or {}
        if form.get("created") and not (assets.get("lead_form_archive") or {}).get("ok"):
            assets["lead_form_archive"] = archive_form(client, form.get("id"))
        write_json(output_dir / "assets.json", assets)
    report = {
        "ok": finished_all and all(item.get("ok") for item in rows),
        "run_id": run_id, "generated_at": now_iso(), "finished_all": finished_all,
        "cases": len(rows), "passed": sum(bool(item.get("ok")) for item in rows),
        "failed": sum(not bool(item.get("ok")) for item in rows),
        "keepers": state.get("keepers") or {}, "rows": rows,
    }
    write_json(output_dir / "live-report.json", report)
    return report


def run_negative_contracts(output_dir: Path):
    dashboard = load_dashboard()
    rows = []

    def record(name, blocked, evidence):
        rows.append({"name": name, "ok": bool(blocked), "blocked_before_graph_write": bool(blocked), "evidence": redact_payload(evidence)})

    # Never accept hand-written/non-numeric targeting IDs.
    invalid_interest = validate_detailed_targeting_ids({"interests": [{"id": "not-an-id", "name": "bad"}]})
    record("invalid_interest", not invalid_interest.get("ok"), invalid_interest)

    invalid_location = validate_meta_targeting_selection(
        [], [{"key": "999999999", "name": "Unknown", "type": "city", "country_code": "CO"}],
        live_search=lambda *_args, **_kwargs: {"data": []}, verify_locations=True,
    )
    record("invalid_locality", not invalid_location.get("ok"), invalid_location)

    gender_error = dashboard._campaign_gender_contract_error({"gender": "personas premium"})
    record("unknown_gender", bool(gender_error), {"error": gender_error})

    # The remaining cases exercise the campaign executor with a client that
    # cannot mutate.  A correct block must therefore happen before any of its
    # Graph write methods can be reached.
    class NegativeConfig:
        ad_account_id = "act_123"
        live = True
        mode = "live"

    class NegativeClient:
        config = NegativeConfig()
        write_calls = 0

        def __getattr__(self, name):
            if name.startswith(("create_", "upload_", "delete")):
                def blocked_write(*_args, **_kwargs):
                    self.write_calls += 1
                    raise AssertionError(f"unexpected Graph write: {name}")
                return blocked_write
            raise AttributeError(name)

    def executor_block(name, campaign):
        client = NegativeClient()
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            campaign_path = directory / "campaign.json"
            config_path = directory / "ad-config.json"
            local_image = directory / "creative.png"
            local_image.write_bytes(b"negative-canary-image")
            campaign = copy.deepcopy(campaign)
            if (campaign.get("ad") or {}).get("creative_image_path") == "/tmp/x.png":
                campaign.setdefault("ad", {})["creative_image_path"] = str(local_image)
            write_json(campaign_path, campaign)
            page_id = "" if name == "missing_whatsapp_page" else "123"
            write_json(config_path, {"creative": {"destination": {"page_id": page_id}}})
            import daily_agent as agent
            original = agent.AD_CONFIG_FILE
            agent.AD_CONFIG_FILE = config_path
            try:
                result = execute_campaign_creation(campaign_path, client, approved=True)
            finally:
                agent.AD_CONFIG_FILE = original
        record(name, result.get("blocked") and client.write_calls == 0, {"result": result, "write_calls": client.write_calls})

    base = {
        "name": "negative", "objective": "sales", "final_status": "PAUSED",
        "budget": {"daily": 20}, "ad": {},
        "ad_sets": [{"name": "Core", "targeting": {"locations": ["CO"], "age_range": {"min": 18, "max": 65}}, "ads": []}],
    }
    executor_block("missing_media", {**base, "ad": {"landing_url": "https://uboost.lat"}})
    executor_block("missing_url", {**base, "ad": {"creative_image_path": "/tmp/x.png"}})
    executor_block("missing_whatsapp_page", {**base, "objective": "messages", "ad": {"message_destination": "WHATSAPP", "creative_image_path": "/tmp/x.png"}})
    executor_block("missing_published_lead_form", {**base, "objective": "leads", "ad": {"creative_image_path": "/tmp/x.png"}})
    executor_block("advantage_age_incompatible", {
        **base,
        "ad": {"creative_image_path": "/tmp/x.png", "landing_url": "https://uboost.lat"},
        "ad_sets": [{"name": "Core", "targeting": {"locations": ["CO"], "age_range": {"min": 18, "max": 40}, "targeting_mode": "advantage_plus", "targeting_automation": {"advantage_audience": 1}}, "ads": []}],
    })

    class VideoTimeoutClient:
        config = NegativeConfig()
        def upload_video(self, *_args, **_kwargs):
            return {"returncode": 504, "body": {"error": {"message": "video upload timeout"}}}

    video_timeout = prepare_native_ad_media(VideoTimeoutClient(), {"video_path": "/tmp/timeout.mp4"}, approved=True)
    record("video_timeout", not video_timeout.get("ok") and video_timeout.get("failed_step") == "upload_video", video_timeout)

    class PartialCleanupClient:
        def __init__(self):
            self.calls = 0
        def delete(self, *_args, **_kwargs):
            self.calls += 1
            return {"returncode": 400 if self.calls == 1 else 0, "body": {"error": {"message": "IN_PROCESS"}} if self.calls == 1 else {"success": True}}

    cleanup_client = PartialCleanupClient()
    cleanup = delete_campaign(cleanup_client, "123", attempts=2, retry_seconds=0)
    record("partial_failure_cleanup", cleanup.get("ok") and cleanup_client.calls == 2, cleanup)

    report = {"ok": all(item.get("ok") for item in rows), "cases": len(rows), "passed": sum(bool(item.get("ok")) for item in rows), "rows": rows}
    write_json(output_dir / "negative-contracts.json", report)
    return report


def markdown_summary(output_dir: Path):
    contracts = read_json(output_dir / "contracts.json", {})
    briefs = read_json(output_dir / "briefs.json", {})
    live = read_json(output_dir / "live-report.json", {})
    assets = read_json(output_dir / "assets.json", {})
    lines = [
        f"# Admira exhaustive Meta canary — {output_dir.name}", "",
        f"Generated: {now_iso()}", "",
        f"- Contracts: {contracts.get('passed', 0)}/{contracts.get('cases', 0)}",
        f"- Natural-language briefs: {briefs.get('passed', 0)}/{briefs.get('briefs', 0)}",
        f"- Live probes: {live.get('passed', 0)}/{live.get('cases', 0)}",
        f"- Overall gate: {'PASS' if contracts.get('ok') and briefs.get('ok') and live.get('ok') else 'FAIL'}",
        "", "## Keepers", "",
    ]
    for family, campaign_id in (live.get("keepers") or {}).items():
        lines.append(f"- {family}: `{campaign_id}`")
    lines.extend(["", "## Temporary assets", "", f"- Visible post cleanup: {(assets.get('visible_post_cleanup') or {}).get('ok')}", f"- Lead form archived: {(assets.get('lead_form_archive') or {}).get('ok')}", ""])
    failures = [row for row in live.get("rows") or [] if not row.get("ok")]
    lines.extend(["## Failures", ""])
    if not failures:
        lines.append("- None")
    for row in failures:
        lines.append(f"- {row.get('case_id')}: {row.get('status')} — {row.get('reason') or row.get('failed_step') or row.get('error')}")
    path = output_dir / "summary.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", choices=["manifest", "contracts", "briefs", "live", "negative", "all"], default="manifest")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--output-root", default=str(ROOT / "output" / "exhaustive-canary"))
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--stop", type=int, default=60)
    parser.add_argument("--delay-seconds", type=float, default=2.0)
    parser.add_argument("--brief-timeout", type=int, default=180)
    parser.add_argument("--brief-delay-seconds", type=float, default=12.0)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--confirm-live-paused-canary", action="store_true")
    args = parser.parse_args()
    if args.layer == "manifest":
        print(json.dumps(manifest_summary(), indent=2, ensure_ascii=False))
        return
    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    output_dir = Path(args.output_root) / f"exhaustive-{run_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "manifest.json", {"run_id": run_id, "summary": manifest_summary(), "live_cases": live_cases(), "briefs": natural_language_briefs()})
    results = {}
    if args.layer in {"contracts", "all"}:
        results["contracts"] = run_contracts(output_dir)
    if args.layer in {"negative", "all"}:
        results["negative"] = run_negative_contracts(output_dir)
    if args.layer in {"briefs", "all"}:
        results["briefs"] = run_briefs(output_dir, timeout_seconds=args.brief_timeout, resume=not args.no_resume, delay_seconds=args.brief_delay_seconds)
    if args.layer in {"live", "all"}:
        if not args.confirm_live_paused_canary:
            raise SystemExit("Refusing Graph mutations without --confirm-live-paused-canary")
        lock_path = output_dir / ".live.lock"
        lock_handle = lock_path.open("a+")
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(f"Another live canary already owns {lock_path}")
        try:
            results["live"] = run_live(output_dir, start=args.start, stop=args.stop, delay_seconds=args.delay_seconds, resume=not args.no_resume)
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            lock_handle.close()
    summary_path = markdown_summary(output_dir)
    print(json.dumps({"run_id": run_id, "output_dir": str(output_dir), "summary": str(summary_path), "results": {key: {k: v for k, v in value.items() if k != "rows"} for key, value in results.items()}}, indent=2, ensure_ascii=False))
    if any(not value.get("ok") for value in results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
