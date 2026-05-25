#!/usr/bin/env python3
"""Build upload-ready Meta ad payloads from creative refresh manifests."""
import json
from datetime import datetime, timezone
from pathlib import Path

from creative_refresh import load_ad_config, read_json, write_json
from product_config import ROOT_DIR, load_config
from security import redact_payload


UPLOAD_DIR = ROOT_DIR / "output" / "uploads"
UPLOAD_INDEX_FILE = UPLOAD_DIR / "upload_index.json"
PENDING_FILE = ROOT_DIR / "dashboard" / "data" / "pending_approvals.json"
ACTIONS_FILE = ROOT_DIR / "dashboard" / "data" / "actions.json"


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def find_manifest(refresh_id_or_path):
    candidate = Path(refresh_id_or_path)
    if candidate.exists():
        return candidate
    matches = list((ROOT_DIR / "output" / "creatives").glob(f"{refresh_id_or_path}/manifest.json"))
    if matches:
        return matches[0]
    raise FileNotFoundError(f"Creative manifest not found: {refresh_id_or_path}")


def pick_variant(plan, variant_id):
    for variant in plan.get("variants", []):
        if variant.get("variant_id") == variant_id:
            return variant
    raise ValueError(f"Variant not found: {variant_id}")


def first_asset_for_ratio(variant, aspect_ratio):
    for asset in variant.get("assets", []):
        if asset.get("aspect_ratio") == aspect_ratio and asset.get("path"):
            return asset
    return None


def build_asset_feed_spec(variant, image_hash_by_ratio):
    copy = variant.get("copy", {})
    bodies = [{"text": copy.get("primary_text", "")}]
    titles = [{"text": copy.get("headline", "")}]
    call_to_action_types = [copy.get("cta", "LEARN_MORE").upper().replace(" ", "_")]
    images = []
    for ratio, image_hash in image_hash_by_ratio.items():
        if image_hash:
            images.append({"hash": image_hash, "adlabels": [{"name": ratio.replace(":", "x")}]})
    return {
        "bodies": bodies,
        "titles": titles,
        "images": images,
        "call_to_action_types": call_to_action_types,
    }


def build_upload_payload(manifest_path, variant_id, selected_ratios=None):
    config = load_config()
    ad_config = load_ad_config()
    manifest_path = find_manifest(str(manifest_path))
    plan = read_json(manifest_path, {})
    variant = pick_variant(plan, variant_id)
    creative_cfg = ad_config.get("creative", {})
    destination = creative_cfg.get("destination", {})
    selected_ratios = selected_ratios or creative_cfg.get("default_aspect_ratios", ["1:1"])
    missing = []
    image_hash_by_ratio = {}
    asset_uploads = []
    for ratio in selected_ratios:
        asset = first_asset_for_ratio(variant, ratio)
        if not asset:
            missing.append(f"generated image asset for {ratio}")
            image_hash_by_ratio[ratio] = ""
            continue
        asset_uploads.append({
            "endpoint": f"/{config.ad_account_id}/adimages",
            "method": "POST",
            "file_path": asset["path"],
            "expected_result": "image_hash",
            "aspect_ratio": ratio,
        })
        image_hash_by_ratio[ratio] = f"DRY_RUN_HASH_{ratio.replace(':', 'x')}"
    for key in ["page_id", "default_adset_id", "url"]:
        if not destination.get(key):
            missing.append(f"creative.destination.{key}")
    if not config.ad_account_id:
        missing.append("META_AD_ACCOUNT_ID")
    asset_feed_spec = build_asset_feed_spec(variant, image_hash_by_ratio)
    ad_name = f"{plan.get('campaign', {}).get('name', 'Campaign')} - {variant_id} - refresh"
    payload = {
        "id": f"upload_{plan.get('id')}_{variant_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "created_at": now_iso(),
        "status": "blocked" if missing else "ready_for_approval",
        "mode": config.mode,
        "manifest_path": str(manifest_path),
        "refresh_id": plan.get("id"),
        "campaign": plan.get("campaign", {}),
        "variant_id": variant_id,
        "selected_ratios": selected_ratios,
        "missing_requirements": missing,
        "asset_uploads": asset_uploads,
        "graph_payloads": {
            "adcreative": {
                "endpoint": f"/{config.ad_account_id}/adcreatives",
                "method": "POST",
                "payload": {
                    "name": f"{ad_name} creative",
                    "object_story_spec": {
                        "page_id": destination.get("page_id", ""),
                        "instagram_actor_id": destination.get("instagram_actor_id", ""),
                    },
                    "asset_feed_spec": asset_feed_spec,
                    "url_tags": "",
                },
            },
            "ad": {
                "endpoint": f"/{config.ad_account_id}/ads",
                "method": "POST",
                "payload": {
                    "name": ad_name,
                    "adset_id": destination.get("default_adset_id", ""),
                    "creative": {"creative_id": "CREATIVE_ID_FROM_PREVIOUS_STEP"},
                    "status": "PAUSED",
                    "tracking_specs": [],
                },
            },
        },
        "review": {
            "headline": variant.get("copy", {}).get("headline", ""),
            "primary_text": variant.get("copy", {}).get("primary_text", ""),
            "cta": variant.get("copy", {}).get("cta", ""),
            "destination_url": destination.get("url", ""),
        },
    }
    return payload


def update_upload_index(payload, payload_path):
    index = read_json(UPLOAD_INDEX_FILE, [])
    summary = {
        "id": payload["id"],
        "created_at": payload["created_at"],
        "status": payload["status"],
        "campaign": payload["campaign"],
        "variant_id": payload["variant_id"],
        "payload_path": str(payload_path),
        "missing_count": len(payload.get("missing_requirements", [])),
    }
    index = [item for item in index if item.get("id") != payload["id"]]
    index.insert(0, summary)
    write_json(UPLOAD_INDEX_FILE, index[:100])


def log_action(action_type, payload, status):
    actions = read_json(ACTIONS_FILE, [])
    record = {"id": f"act_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}", "type": action_type, "status": status, "payload": redact_payload(payload), "created_at": now_iso()}
    actions.insert(0, record)
    write_json(ACTIONS_FILE, actions[:500])
    return record


def add_pending_upload(payload, payload_path):
    pending = read_json(PENDING_FILE, [])
    approval_id = f"approval_{payload['id']}"
    if any(item.get("id") == approval_id for item in pending):
        return None
    record = {
        "id": approval_id,
        "type": "creative_upload",
        "status": "pending",
        "payload": {
            "upload_id": payload["id"],
            "campaign_name": payload.get("campaign", {}).get("name"),
            "variant_id": payload.get("variant_id"),
            "payload_path": str(payload_path),
            "missing_requirements": payload.get("missing_requirements", []),
        },
        "created_at": now_iso(),
    }
    pending.insert(0, record)
    write_json(PENDING_FILE, pending[:250])
    return record


def stage_upload(manifest_path, variant_id="v1", selected_ratios=None, request_approval=True):
    payload = build_upload_payload(manifest_path, variant_id, selected_ratios)
    upload_dir = UPLOAD_DIR / payload["id"]
    upload_dir.mkdir(parents=True, exist_ok=True)
    payload_path = upload_dir / "payload.json"
    write_json(payload_path, payload)
    update_upload_index(payload, payload_path)
    approval = None
    if request_approval and payload["status"] == "ready_for_approval":
        approval = add_pending_upload(payload, payload_path)
    log_action("creative_upload_stage", {"payload_path": str(payload_path), "approval": approval}, payload["status"])
    return payload, payload_path, approval


def recent_uploads(limit=10):
    return read_json(UPLOAD_INDEX_FILE, [])[:limit]
