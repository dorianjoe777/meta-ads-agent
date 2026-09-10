"""Durable proposal history, independent from permission to publish on Meta."""
import fcntl
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from local_store import read_json, atomic_write_json as write_json, now_iso


def save_post(path, payload, *, status="proposed", result=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    caption = str(payload.get("caption") or payload.get("message") or "").strip()
    media = {key: str(payload.get(key) or "") for key in ("image_path", "image_url", "video_path", "video_url")}
    recorded_at = now_iso()
    # A deliberate reuse on another day is a new proposal in novelty memory.
    # Retries and publication preserve the explicit draft ID returned earlier.
    identity = {"page_id": payload.get("page_id"), "caption": caption,
                "proposal_date": recorded_at[:10], **media}
    draft_id = str(payload.get("draft_id") or hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20])
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger = read_json(path, {"items": []})
        items = [item for item in ledger.get("items", []) if isinstance(item, dict)]
        previous = next((item for item in items if item.get("draft_id") == draft_id), {})
        preserved_media = {key: media[key] or previous.get(key, "") for key in media}
        record = {**previous, **preserved_media, "draft_id": draft_id, "caption": caption or previous.get("caption", ""),
                  "created_at": previous.get("created_at") or recorded_at, "updated_at": recorded_at,
                  "status": status, "page_id": str(payload.get("page_id") or previous.get("page_id") or "")}
        # Retain conceptual memory when publication results have fewer fields.
        for key in ("approval_id", "name", "pillar", "topic", "offer", "hook", "cta", "visual_concept",
                    "format", "objective", "why_it_fits", "media_type", "vault_name", "content_group", "content_asset_ids"):
            if payload.get(key) not in (None, "", []):
                record[key] = payload[key]
        if previous.get("status") == "published":
            record["status"] = "published"
        if result and result.get("ok"):
            record.update(post_id=str(result.get("post_id") or ""), published_at=now_iso(), status="published")
        items = [item for item in items if item.get("draft_id") != draft_id]
        items.insert(0, record)
        # Keep durable archive; the runtime receives a bounded recent projection.
        write_json(path, {"items": items, "updated_at": now_iso()})
        return record


def recent_posts(ledger, *, days=15, page_id="", now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    items = []
    for item in ledger.get("items", []):
        if not isinstance(item, dict) or (page_id and item.get("page_id") != page_id):
            continue
        try:
            stamp = datetime.fromisoformat(str(item.get("created_at") or item.get("published_at") or item.get("updated_at")).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if cutoff <= stamp <= now:
            items.append({key: value for key, value in item.items() if key not in {"approval_id", "post_id"}})
    return {"window_days": days, "as_of": now.isoformat(), "items": items}
