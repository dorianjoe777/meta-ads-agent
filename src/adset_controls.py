#!/usr/bin/env python3
"""Ad set delivery controls shared by staging and live execution."""

DEFAULT_MANUAL_PLACEMENTS = [
    "FACEBOOK_FEED",
    "FACEBOOK_STORIES",
    "INSTAGRAM_FEED",
    "INSTAGRAM_STORIES",
]

PLACEMENT_TO_TARGETING = {
    "FACEBOOK_FEED": ("facebook", "facebook_positions", "feed"),
    "FACEBOOK_STORY": ("facebook", "facebook_positions", "story"),
    "FACEBOOK_STORIES": ("facebook", "facebook_positions", "story"),
    "FACEBOOK_REELS": ("facebook", "facebook_positions", "facebook_reels"),
    "FACEBOOK_VIDEO_FEEDS": ("facebook", "facebook_positions", "video_feeds"),
    "INSTAGRAM_FEED": ("instagram", "instagram_positions", "stream"),
    "INSTAGRAM_STORY": ("instagram", "instagram_positions", "story"),
    "INSTAGRAM_STORIES": ("instagram", "instagram_positions", "story"),
    "INSTAGRAM_REELS": ("instagram", "instagram_positions", "reels"),
    "INSTAGRAM_PROFILE_FEED": ("instagram", "instagram_positions", "profile_feed"),
    "MESSENGER": ("messenger", "messenger_positions", "messenger_home"),
    "AUDIENCE_NETWORK": ("audience_network", "audience_network_positions", "classic"),
}

DEPRECATED_MANUAL_PLACEMENTS = {
    # Meta Graph rejects this placement in the current Marketing API even
    # though older Ads Manager/API versions exposed it.
    "INSTAGRAM_EXPLORE",
}

PLACEMENT_TARGETING_KEYS = [
    "publisher_platforms",
    "facebook_positions",
    "instagram_positions",
    "messenger_positions",
    "audience_network_positions",
    "threads_positions",
]


def _dedupe(items):
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _normalize_manual_placement(value):
    text = str(value or "").strip()
    if not text:
        return ""
    return text.upper().replace("-", "_").replace(" ", "_")


def deprecated_manual_placements(value=None):
    """Return explicitly requested placements Meta no longer accepts."""
    if isinstance(value, dict):
        value = value.get("manual") or value.get("placements") or value.get("include") or []
    elif isinstance(value, str):
        value = [part.strip() for part in value.split(",") if part.strip()]
    if not isinstance(value, (list, tuple, set)):
        return []
    requested = {_normalize_manual_placement(item) for item in value}
    return sorted(requested & DEPRECATED_MANUAL_PLACEMENTS)


def normalize_placement_config(value=None):
    """Return a product-level placement config.

    Default is intentionally narrow: Facebook + Instagram feeds/stories. Buyers
    can still choose automatic/Advantage+ placements or a custom manual list.
    """
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {
            "automatic", "automatic placements", "automatic_placements", "auto",
            "advantage", "advantage+", "advantage_plus", "advantage placements",
            "advantage+ placements", "advantage_plus_placements", "all",
            "ubicaciones automaticas", "ubicaciones automáticas",
            "ubicaciones advantage", "ubicaciones advantage+",
        }:
            return {"automatic": True, "manual": []}
        if lowered in {"feed_stories", "feeds_stories", "default", "meta_feed_stories"}:
            return {"automatic": False, "manual": list(DEFAULT_MANUAL_PLACEMENTS)}
        value = [part.strip() for part in value.split(",") if part.strip()]

    if isinstance(value, dict):
        if value.get("automatic") is True:
            return {"automatic": True, "manual": []}
        manual = value.get("manual") or value.get("placements") or value.get("include")
        if not manual:
            manual = DEFAULT_MANUAL_PLACEMENTS
        normalized = [_normalize_manual_placement(item) for item in manual]
        normalized = [item for item in normalized if item in PLACEMENT_TO_TARGETING]
        if "INSTAGRAM_PROFILE_FEED" in normalized and "INSTAGRAM_FEED" not in normalized:
            normalized.insert(0, "INSTAGRAM_FEED")
        return {"automatic": False, "manual": _dedupe(normalized or DEFAULT_MANUAL_PLACEMENTS)}

    if isinstance(value, (list, tuple, set)):
        normalized = [_normalize_manual_placement(item) for item in value]
        normalized = [item for item in normalized if item in PLACEMENT_TO_TARGETING]
        if "INSTAGRAM_PROFILE_FEED" in normalized and "INSTAGRAM_FEED" not in normalized:
            normalized.insert(0, "INSTAGRAM_FEED")
        return {"automatic": False, "manual": _dedupe(normalized or DEFAULT_MANUAL_PLACEMENTS)}

    return {"automatic": False, "manual": list(DEFAULT_MANUAL_PLACEMENTS)}


def placement_targeting_fields(placement_config=None):
    config = normalize_placement_config(placement_config)
    if config.get("automatic"):
        return {}

    fields = {}
    platforms = []
    for placement in config.get("manual") or DEFAULT_MANUAL_PLACEMENTS:
        platform, position_key, position = PLACEMENT_TO_TARGETING.get(placement, (None, None, None))
        if not platform or not position_key:
            continue
        platforms.append(platform)
        fields.setdefault(position_key, []).append(position)

    if platforms:
        fields["publisher_platforms"] = _dedupe(platforms)
    for key, values in list(fields.items()):
        if isinstance(values, list):
            fields[key] = _dedupe(values)
    return fields


def apply_placement_targeting(targeting_spec, placement_config=None):
    spec = dict(targeting_spec or {})
    if any(spec.get(key) for key in PLACEMENT_TARGETING_KEYS):
        return spec
    spec.update(placement_targeting_fields(placement_config))
    return spec


def placement_config_summary(placement_config=None):
    config = normalize_placement_config(placement_config)
    if config.get("automatic"):
        return {"mode": "automatic", "manual": []}
    return {"mode": "manual", "manual": list(config.get("manual") or DEFAULT_MANUAL_PLACEMENTS)}
