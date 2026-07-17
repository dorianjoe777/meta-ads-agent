#!/usr/bin/env python3
"""Canonical Meta Insights action metrics shared by every reporting path.

Meta can expose one logical result through multiple reporting aliases in the
same Insights row (generic, pixel/offsite, onsite, omni, app and in-store).
Adding those aliases inflates results. This module aggregates fragments of the
same exact ``action_type`` first, then keeps the largest equivalent alias as
the canonical value. Distinct business events remain distinct.
"""

from math import isclose


def number(value, default=0.0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return float(default)


def _standard_event_aliases(event_name, *extra):
    """Return known Insights wrappers for one Meta standard event."""
    event = str(event_name or "").strip().lower()
    return frozenset({
        event,
        f"omni_{event}",
        f"offsite_conversion.fb_pixel_{event}",
        f"onsite_conversion.{event}",
        f"onsite_web_{event}",
        f"onsite_web_app_{event}",
        f"web_in_store_{event}",
        f"web_app_in_store_{event}",
        f"mobile_app_{event}",
        f"app_custom_event.fb_mobile_{event}",
        *(str(item or "").strip().lower() for item in extra),
    })


# Only names that represent the same logical result belong in one set. Adding
# a new ad objective means adding its result family here, not summing every
# vaguely related action returned by Meta.
ACTION_ALIASES = {
    "landing_page_views": _standard_event_aliases("landing_page_view", "landing_page_views"),
    "view_content": _standard_event_aliases("view_content"),
    "search": _standard_event_aliases("search"),
    "add_to_wishlist": _standard_event_aliases("add_to_wishlist"),
    "add_to_cart": _standard_event_aliases("add_to_cart"),
    "initiate_checkout": _standard_event_aliases(
        "initiate_checkout",
        "initiated_checkout",
        "omni_initiated_checkout",
        "offsite_conversion.fb_pixel_initiated_checkout",
        "onsite_web_initiated_checkout",
    ),
    "add_payment_info": _standard_event_aliases("add_payment_info"),
    "purchase": _standard_event_aliases(
        "purchase",
        "onsite_conversion.purchase",
        "offsite_purchase",
        "offsite_purchase_add_20_s_calls",
    ),
    "lead": _standard_event_aliases(
        "lead",
        "onsite_conversion.lead_grouped",
        "leadgen_grouped",
    ),
    "complete_registration": _standard_event_aliases("complete_registration"),
    "contact": _standard_event_aliases("contact"),
    "customize_product": _standard_event_aliases("customize_product"),
    "donate": _standard_event_aliases("donate"),
    "find_location": _standard_event_aliases("find_location"),
    "schedule": _standard_event_aliases("schedule"),
    "start_trial": _standard_event_aliases("start_trial"),
    "submit_application": _standard_event_aliases("submit_application"),
    "subscribe": _standard_event_aliases("subscribe"),
    "conversation": frozenset({
        "messaging_conversation_started",
        "messaging_conversation_started_7d",
        "onsite_conversion.messaging_conversation_started",
        "onsite_conversion.messaging_conversation_started_7d",
    }),
    "thruplay": frozenset({
        "video_thruplay_watched_actions",
        "video_thruplay_watched_action",
        "thruplay",
    }),
    "video_3s_views": frozenset({
        "video_view",
        "video_3_sec_watched_actions",
        "video_3s_views",
    }),
    "completed_video_views": frozenset({
        "video_p100_watched_actions",
        "completed_video_view",
        "completed_video_views",
    }),
    "app_install": frozenset({
        "app_install",
        "mobile_app_install",
        "omni_app_install",
        "offsite_conversion.fb_pixel_app_install",
    }),
    # Page engagement is a broader reporting view that can include the same
    # post engagement. Max-across-aliases avoids adding the nested totals.
    "post_engagement": frozenset({"post_engagement", "page_engagement"}),
    "event_response": frozenset({"event_response", "rsvp"}),
}

FUNNEL_ACTIONS = {key: frozenset(value) for key, value in ACTION_ALIASES.items()}
PURCHASE_VALUE_ACTIONS = FUNNEL_ACTIONS["purchase"]

# These are independent business outcomes. They may be added for a generic
# conversion total, while aliases inside each family are still counted once.
CONVERSION_RESULT_KEYS = (
    "purchase",
    "lead",
    "complete_registration",
    "contact",
    "donate",
    "find_location",
    "schedule",
    "start_trial",
    "submit_application",
    "subscribe",
    "conversation",
    "app_install",
)


ALIAS_TO_CANONICAL = {}
for _canonical, _aliases in ACTION_ALIASES.items():
    for _alias in _aliases:
        previous = ALIAS_TO_CANONICAL.setdefault(_alias, _canonical)
        if previous != _canonical:
            raise RuntimeError(f"Meta action alias {_alias!r} belongs to two canonical metrics")


def normalize_action_type(value):
    return str(value or "").strip().lower()


def canonical_action_key(action_type):
    """Map a known reporting alias to its logical metric; keep custom events exact."""
    normalized = normalize_action_type(action_type)
    return ALIAS_TO_CANONICAL.get(normalized, normalized)


def exact_action_totals(rows):
    """Sum fragments only when Meta repeats the same exact action type."""
    totals = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        action_type = normalize_action_type(row.get("action_type") or row.get("type"))
        if not action_type:
            continue
        totals[action_type] = totals.get(action_type, 0.0) + number(row.get("value"))
    return totals


def canonical_action_totals(rows):
    """Return one value per logical event, deduplicated across Meta aliases."""
    candidates = {}
    for action_type, total in exact_action_totals(rows).items():
        canonical = canonical_action_key(action_type)
        candidates.setdefault(canonical, []).append(total)
    return {
        canonical: max(values, default=0.0)
        for canonical, values in candidates.items()
    }


def canonical_action_value(rows, action):
    return canonical_action_totals(rows).get(canonical_action_key(action), 0.0)


def deduplicated_alias_value(rows, names):
    """Sum requested logical events while counting each alias family once."""
    totals = canonical_action_totals(rows)
    requested = {canonical_action_key(name) for name in names or [] if normalize_action_type(name)}
    return sum(totals.get(canonical, 0.0) for canonical in requested)


def conversion_result_value(rows):
    totals = canonical_action_totals(rows)
    return sum(totals.get(key, 0.0) for key in CONVERSION_RESULT_KEYS)


def reporting_contract():
    """Deterministic release invariant for the duplicate-alias regression."""
    hotmart_actions = [
        {"action_type": action_type, "value": "1"}
        for action_type in (
            "purchase",
            "omni_purchase",
            "offsite_conversion.fb_pixel_purchase",
            "onsite_web_purchase",
            "onsite_web_app_purchase",
            "web_in_store_purchase",
            "web_app_in_store_purchase",
        )
    ]
    hotmart_values = [
        {"action_type": action_type, "value": "41.89"}
        for action_type in (
            "purchase",
            "omni_purchase",
            "offsite_conversion.fb_pixel_purchase",
            "onsite_web_purchase",
        )
    ]
    every_family_once = all(
        isclose(
            canonical_action_value(
                [{"action_type": alias, "value": "2"} for alias in aliases],
                canonical,
            ),
            2.0,
        )
        for canonical, aliases in ACTION_ALIASES.items()
    )
    repeated_fragments = canonical_action_value(
        [
            {"action_type": "purchase", "value": "1"},
            {"action_type": "purchase", "value": "2"},
            {"action_type": "omni_purchase", "value": "3"},
        ],
        "purchase",
    )
    return {
        "hotmart_purchase": canonical_action_value(hotmart_actions, "purchase"),
        "hotmart_revenue": canonical_action_value(hotmart_values, "purchase"),
        "every_family_once": every_family_once,
        "repeated_fragments": repeated_fragments,
        "distinct_results": deduplicated_alias_value(
            hotmart_actions + [{"action_type": "lead", "value": "4"}],
            {"purchase", "lead", "omni_purchase"},
        ),
    }


def assert_reporting_contract():
    result = reporting_contract()
    expected = {
        "hotmart_purchase": 1.0,
        "hotmart_revenue": 41.89,
        "every_family_once": True,
        "repeated_fragments": 3.0,
        "distinct_results": 5.0,
    }
    failures = {
        key: {"expected": expected[key], "actual": value}
        for key, value in result.items()
        if value != expected[key]
    }
    if failures:
        raise AssertionError(f"Meta action reporting contract failed: {failures}")
    return result
