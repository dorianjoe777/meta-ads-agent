#!/usr/bin/env python3
"""Curated optimization research memory with trust and expiry controls."""
import hashlib
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

from local_store import now_iso, read_json, write_json
from product_config import ROOT_DIR


RESEARCH_FILE = ROOT_DIR / "dashboard" / "data" / "optimization_research.json"
MAX_ITEMS = 200
SOURCE_TYPES = {"official", "research", "expert", "community"}
TRUST = {"official": "high", "research": "high", "expert": "medium", "community": "anecdotal"}


def parse_iso(value):
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def safe_url(value):
    url = str(value or "").strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Research sources must use a public HTTPS URL.")
    return url[:1000]


def research_id(url, claim):
    digest = hashlib.sha256(f"{url}|{claim}".encode("utf-8")).hexdigest()[:16]
    return f"research_{digest}"


def normalize_item(payload, now=None):
    current = now or datetime.now(timezone.utc)
    source_type = str(payload.get("source_type") or "community").strip().lower()
    if source_type not in SOURCE_TYPES:
        raise ValueError("source_type must be official, research, expert, or community.")
    url = safe_url(payload.get("source_url"))
    claim = re.sub(r"\s+", " ", str(payload.get("claim") or "").strip())[:1000]
    hypothesis = re.sub(r"\s+", " ", str(payload.get("testable_hypothesis") or "").strip())[:1000]
    if not claim or not hypothesis:
        raise ValueError("Research needs both a claim and a testable hypothesis.")
    observed = parse_iso(payload.get("observed_at")) or current
    published = parse_iso(payload.get("published_at"))
    expiry_days = int(payload.get("expiry_days") or (180 if source_type in {"official", "research"} else 60 if source_type == "expert" else 30))
    expiry_days = max(7, min(365, expiry_days))
    corroborating = []
    for item in payload.get("corroborating_urls") or []:
        try:
            corroborating.append(safe_url(item))
        except ValueError:
            continue
    credibility = TRUST[source_type]
    if source_type == "community" and corroborating:
        credibility = "low"
    return {
        "id": str(payload.get("id") or research_id(url, claim)),
        "source_url": url,
        "source_title": str(payload.get("source_title") or urllib.parse.urlparse(url).hostname or "Source")[:200],
        "source_type": source_type,
        "credibility": credibility,
        "published_at": published.isoformat(timespec="seconds") if published else "",
        "observed_at": observed.isoformat(timespec="seconds"),
        "expires_at": (observed + timedelta(days=expiry_days)).isoformat(timespec="seconds"),
        "claim": claim,
        "counterevidence": re.sub(r"\s+", " ", str(payload.get("counterevidence") or "").strip())[:1000],
        "testable_hypothesis": hypothesis,
        "corroborating_urls": corroborating[:5],
        "allowed_use": "propose_experiment_only",
        "can_trigger_spend_action": False,
    }


def load_research(now=None, include_expired=False):
    current = now or datetime.now(timezone.utc)
    state = read_json(RESEARCH_FILE, {"items": []})
    if not isinstance(state, dict) or not isinstance(state.get("items"), list):
        state = {"items": []}
    items = []
    for item in state["items"]:
        if not isinstance(item, dict):
            continue
        expired = bool(parse_iso(item.get("expires_at")) and parse_iso(item.get("expires_at")) < current)
        item = {**item, "expired": expired, "can_trigger_spend_action": False, "allowed_use": "propose_experiment_only"}
        if include_expired or not expired:
            items.append(item)
    return {"updated_at": state.get("updated_at", ""), "items": items}


def save_research_item(payload, now=None):
    item = normalize_item(payload if isinstance(payload, dict) else {}, now)
    state = load_research(now, include_expired=True)
    state["items"] = [item] + [existing for existing in state["items"] if existing.get("id") != item["id"]]
    state["items"] = state["items"][:MAX_ITEMS]
    state["updated_at"] = now_iso()
    write_json(RESEARCH_FILE, state, ensure_ascii=False)
    return item


def seed_current_research(now=None):
    current = now or datetime.now(timezone.utc)
    seeds = [
        {
            "source_url": "https://www.facebook.com/business/ads/performance-marketing",
            "source_title": "Meta Performance 5",
            "source_type": "official",
            "claim": "Account simplification, fewer learning-phase changes, creative diversification, stronger data quality and result validation are core performance practices.",
            "testable_hypothesis": "A simpler structure with protected learning windows and several materially distinct creatives improves stable cost per result versus frequent manual edits.",
            "counterevidence": "The appropriate structure and number of creatives still depend on budget, objective and delivery volume.",
            "expiry_days": 180,
        },
        {
            "source_url": "https://www.facebook.com/business/help/AboutConversionsAPI",
            "source_title": "Meta Conversions API",
            "source_type": "official",
            "claim": "Conversions API can improve the reliability of event data when implemented alongside browser events and appropriate deduplication.",
            "testable_hypothesis": "Reconciling Shopify outcomes with correctly deduplicated Pixel and CAPI purchase events reduces unexplained Meta-versus-store reporting gaps.",
            "counterevidence": "CAPI does not remove attribution-window differences or guarantee performance improvement.",
            "expiry_days": 180,
        },
        {
            "source_url": "https://www.jonloomer.com/meta-creative-testing/",
            "source_title": "Jon Loomer: Meta Creative Testing",
            "source_type": "expert",
            "claim": "Creative tests should use meaningfully different variants and enough controlled delivery to avoid mistaking uneven allocation or small samples for a winner.",
            "testable_hypothesis": "A controlled 2-to-5 variant test with a capped test budget produces a clearer conversion winner than reading CTR from an unconstrained ad set.",
            "counterevidence": "Expert guidance is not an official guarantee and small-budget accounts may need longer evidence windows.",
            "expiry_days": 60,
        },
        {
            "source_url": "https://www.reddit.com/r/FacebookAds/comments/1suack4/how_do_you_guys_structure_testing_vs_scaling_in/",
            "source_title": "Reddit practitioner discussion: testing versus scaling",
            "source_type": "community",
            "claim": "Practitioners report both CBO and ABO success, while uneven creative delivery and premature scaling are recurring concerns.",
            "testable_hypothesis": "For this account, compare controlled creative testing against normal campaign allocation and measure conversion confidence, not community preference.",
            "counterevidence": "The discussion is contradictory and anecdotal; it must not become an automatic account rule.",
            "expiry_days": 30,
        },
        {
            "source_url": "https://www.reddit.com/r/FacebookAds/comments/1pi5ogx/delayed_conversion_reporting/",
            "source_title": "Reddit practitioner discussion: delayed conversion reporting",
            "source_type": "community",
            "claim": "Practitioners report that conversions can appear after initial delivery, making same-day decisions risky.",
            "testable_hypothesis": "A 24-to-72-hour maturity hold reduces false pauses compared with same-day zero-conversion decisions in this account.",
            "counterevidence": "The exact lag depends on event setup, attribution and sales cycle; Shopify reconciliation should calibrate it.",
            "expiry_days": 30,
        },
    ]
    saved = []
    for seed in seeds:
        seed["observed_at"] = current.isoformat(timespec="seconds")
        saved.append(save_research_item(seed, current))
    return {"items": saved}
