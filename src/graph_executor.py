#!/usr/bin/env python3
"""Meta Graph API executor for approved creative upload payloads."""
import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from creative_refresh import read_json, write_json
from license import license_status
from product_config import ROOT_DIR, load_config
from security import redact_payload
from social_flow_client import SocialFlowClient


ACTIONS_FILE = ROOT_DIR / "dashboard" / "data" / "actions.json"


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def log_action(action_type, payload, status):
    actions = read_json(ACTIONS_FILE, [])
    record = {"id": f"act_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}", "type": action_type, "status": status, "payload": redact_payload(payload), "created_at": now_iso()}
    actions.insert(0, record)
    write_json(ACTIONS_FILE, actions[:500])
    return record


def validate_payload(payload, config, approved=False):
    missing = list(payload.get("missing_requirements", []))
    if not config.ad_account_id:
        missing.append("META_AD_ACCOUNT_ID")
    if config.live and not config.live_actions_enabled and not approved:
        missing.append("LIVE_ACTIONS_ENABLED")
    if (config.live or approved) and config.meta_connector == "graph_api" and not config.meta_access_token:
        missing.append("META_ACCESS_TOKEN")
    if payload.get("status") == "blocked":
        missing.append("payload status is blocked")
    for upload in payload.get("asset_uploads", []):
        path = upload.get("file_path")
        if not path or not Path(path).exists():
            missing.append(f"asset file missing: {path}")
    return sorted(set(missing))


def graph_url(config, endpoint):
    endpoint = endpoint.lstrip("/")
    return f"https://graph.facebook.com/{config.meta_graph_api_version}/{endpoint}"


def encode_multipart(fields, files):
    boundary = f"----metaadsagent{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    chunks = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    for name, path in files.items():
        file_path = Path(path)
        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"; filename="{file_path.name}"\r\n'.encode("utf-8"))
        chunks.append(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
        with open(file_path, "rb") as handle:
            chunks.append(handle.read())
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return boundary, b"".join(chunks)


def post_form(config, endpoint, fields):
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        graph_url(config, endpoint),
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    return perform_request(request)


def post_multipart(config, endpoint, fields, files):
    boundary, body = encode_multipart(fields, files)
    request = urllib.request.Request(
        graph_url(config, endpoint),
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    return perform_request(request)


def perform_request(request):
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return {"ok": True, "status": response.status, "body": json.loads(response.read().decode("utf-8"))}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = raw[:1000]
        return {"ok": False, "status": exc.code, "body": body}
    except Exception as exc:
        return {"ok": False, "status": None, "body": str(exc)}


def dry_run_result(payload, missing):
    return {
        "ok": not missing,
        "mode": "dry-run",
        "executed": False,
        "missing_requirements": missing,
        "steps": [
            {"step": "upload_images", "planned": len(payload.get("asset_uploads", []))},
            {"step": "create_adcreative", "endpoint": payload.get("graph_payloads", {}).get("adcreative", {}).get("endpoint")},
            {"step": "create_paused_ad", "endpoint": payload.get("graph_payloads", {}).get("ad", {}).get("endpoint")},
        ],
    }


def parse_json_stdout(result):
    try:
        return json.loads(result.get("stdout") or "{}")
    except json.JSONDecodeError:
        return {}


def extract_social_image_hash(result):
    body = parse_json_stdout(result)
    if body.get("hash"):
        return body["hash"]
    images = body.get("images", {}) if isinstance(body, dict) else {}
    if images:
        first = next(iter(images.values()))
        return first.get("hash")
    return None


def extract_social_id(result):
    body = parse_json_stdout(result)
    return body.get("id") if isinstance(body, dict) else None


def execute_with_social_cli(payload_path, payload, missing, config, approved=False):
    if not config.live and not approved:
        result = dry_run_result(payload, missing)
        result["connector"] = "social_cli"
        log_action("creative_upload_execute", {"payload_path": str(payload_path), "result": result}, "dry_run")
        return result
    if missing:
        result = {"ok": False, "connector": "social_cli", "mode": "live", "executed": False, "missing_requirements": missing}
        log_action("creative_upload_execute", {"payload_path": str(payload_path), "result": result}, "blocked")
        return result

    client = SocialFlowClient(config)
    destination = payload["graph_payloads"]["adcreative"]["payload"]["object_story_spec"]
    ad_payload = payload["graph_payloads"]["ad"]["payload"]
    review = payload.get("review", {})
    steps = []
    image_hash = ""

    for upload in payload.get("asset_uploads", []):
        upload_result = client.upload_image(config.ad_account_id, upload["file_path"], approved=approved)
        image_hash = extract_social_image_hash(upload_result)
        steps.append({"step": "social_upload_image", "ok": bool(image_hash), "image_hash": image_hash, "result": upload_result})
        if not image_hash:
            final = {"ok": False, "connector": "social_cli", "mode": "live", "executed": True, "failed_step": "upload_image", "steps": steps}
            log_action("creative_upload_execute", {"payload_path": str(payload_path), "result": final}, "failed")
            return final
        break

    creative_result = client.create_creative(
        config.ad_account_id,
        payload["graph_payloads"]["adcreative"]["payload"]["name"],
        destination.get("page_id", ""),
        review.get("destination_url", ""),
        review.get("primary_text", ""),
        review.get("headline", ""),
        image_hash,
        review.get("cta", "LEARN_MORE").upper().replace(" ", "_"),
        destination.get("instagram_actor_id", ""),
        approved=approved,
    )
    creative_id = extract_social_id(creative_result)
    steps.append({"step": "social_create_creative", "ok": bool(creative_id), "creative_id": creative_id, "result": creative_result})
    if not creative_id:
        final = {"ok": False, "connector": "social_cli", "mode": "live", "executed": True, "failed_step": "create_creative", "steps": steps}
        log_action("creative_upload_execute", {"payload_path": str(payload_path), "result": final}, "failed")
        return final

    ad_result = client.create_ad(ad_payload["adset_id"], ad_payload["name"], creative_id, "PAUSED", approved=approved)
    ad_id = extract_social_id(ad_result)
    steps.append({"step": "social_create_paused_ad", "ok": bool(ad_id), "ad_id": ad_id, "result": ad_result})
    final = {"ok": bool(ad_id), "connector": "social_cli", "mode": "live", "executed": True, "creative_id": creative_id, "ad_id": ad_id, "steps": steps}
    log_action("creative_upload_execute", {"payload_path": str(payload_path), "result": final}, "completed" if final["ok"] else "failed")
    return final


def extract_image_hash(result):
    body = result.get("body", {})
    images = body.get("images", {}) if isinstance(body, dict) else {}
    if images:
        first = next(iter(images.values()))
        return first.get("hash")
    return None


def execute_upload_payload(payload_path, approved=False):
    config = load_config()
    payload = read_json(Path(payload_path), {})
    missing = validate_payload(payload, config, approved=approved)
    if config.license_required_for_live and (approved or config.live or config.live_actions_enabled):
        status = license_status(config)
        if not status.get("valid"):
            result = {"ok": False, "mode": config.mode, "executed": False, "blocked": True, "missing_requirements": missing, "error": f"License unlock required before creative upload: {status.get('detail')}"}
            log_action("creative_upload_execute", {"payload_path": str(payload_path), "result": result}, "blocked")
            return result
    if config.meta_connector == "social_cli":
        return execute_with_social_cli(payload_path, payload, missing, config, approved=approved)
    if not config.live and not approved:
        result = dry_run_result(payload, missing)
        result["connector"] = "graph_api"
        log_action("creative_upload_execute", {"payload_path": str(payload_path), "result": result}, "dry_run")
        return result
    if missing:
        result = {"ok": False, "mode": "live", "executed": False, "missing_requirements": missing}
        log_action("creative_upload_execute", {"payload_path": str(payload_path), "result": result}, "blocked")
        return result

    image_hash_by_ratio = {}
    steps = []
    for upload in payload.get("asset_uploads", []):
        fields = {"access_token": config.meta_access_token}
        result = post_multipart(config, upload["endpoint"], fields, {"filename": upload["file_path"]})
        image_hash = extract_image_hash(result)
        image_hash_by_ratio[upload.get("aspect_ratio")] = image_hash
        steps.append({"step": "upload_image", "aspect_ratio": upload.get("aspect_ratio"), "ok": result.get("ok"), "status": result.get("status"), "image_hash": image_hash, "body": result.get("body")})
        if not result.get("ok") or not image_hash:
            final = {"ok": False, "mode": "live", "executed": True, "failed_step": "upload_image", "steps": steps}
            log_action("creative_upload_execute", {"payload_path": str(payload_path), "result": final}, "failed")
            return final

    adcreative = payload["graph_payloads"]["adcreative"]
    creative_payload = dict(adcreative["payload"])
    asset_feed_spec = creative_payload.get("asset_feed_spec", {})
    for image in asset_feed_spec.get("images", []):
        label = image.get("adlabels", [{}])[0].get("name", "").replace("x", ":")
        if image_hash_by_ratio.get(label):
            image["hash"] = image_hash_by_ratio[label]
    creative_fields = {"access_token": config.meta_access_token, **{k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in creative_payload.items()}}
    creative_result = post_form(config, adcreative["endpoint"], creative_fields)
    creative_id = creative_result.get("body", {}).get("id") if isinstance(creative_result.get("body"), dict) else None
    steps.append({"step": "create_adcreative", "ok": creative_result.get("ok"), "status": creative_result.get("status"), "creative_id": creative_id, "body": creative_result.get("body")})
    if not creative_result.get("ok") or not creative_id:
        final = {"ok": False, "mode": "live", "executed": True, "failed_step": "create_adcreative", "steps": steps}
        log_action("creative_upload_execute", {"payload_path": str(payload_path), "result": final}, "failed")
        return final

    ad = payload["graph_payloads"]["ad"]
    ad_payload = dict(ad["payload"])
    ad_payload["creative"] = {"creative_id": creative_id}
    ad_fields = {"access_token": config.meta_access_token, **{k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in ad_payload.items()}}
    ad_result = post_form(config, ad["endpoint"], ad_fields)
    ad_id = ad_result.get("body", {}).get("id") if isinstance(ad_result.get("body"), dict) else None
    steps.append({"step": "create_paused_ad", "ok": ad_result.get("ok"), "status": ad_result.get("status"), "ad_id": ad_id, "body": ad_result.get("body")})
    final = {"ok": bool(ad_result.get("ok") and ad_id), "mode": "live", "executed": True, "creative_id": creative_id, "ad_id": ad_id, "steps": steps}
    log_action("creative_upload_execute", {"payload_path": str(payload_path), "result": final}, "completed" if final["ok"] else "failed")
    return final
