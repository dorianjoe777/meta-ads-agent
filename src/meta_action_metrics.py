#!/usr/bin/env python3
"""Canonical Meta Insights action metrics shared by every reporting path.

Meta can report one event through aggregate aliases (generic, ``omni`` and
web/app/store rollups) as well as source-specific aliases. Aggregate aliases
must not be added to their own breakdowns, while genuinely disjoint sources
must still be added when no encompassing rollup is present.

The normalization contract is therefore:

* sum fragments of the same exact ``action_type`` (breakdown pagination);
* collapse aliases with identical source coverage by keeping the largest;
* prefer one aggregate rollup over its overlapping source breakdowns;
* add only aliases whose source coverage is disjoint; and
* keep different business events as different canonical metrics.
"""

from math import isclose


OFFSITE_WEB = "offsite_web"
ONSITE_WEB = "onsite_web"
MOBILE_APP = "mobile_app"
ONSITE_APP = "onsite_app"
IN_STORE = "in_store"
ALL_CONVERSION_SOURCES = frozenset({
    OFFSITE_WEB,
    ONSITE_WEB,
    MOBILE_APP,
    ONSITE_APP,
    IN_STORE,
})
WEB_SOURCES = frozenset({OFFSITE_WEB, ONSITE_WEB})
ONSITE_SOURCES = frozenset({ONSITE_WEB, ONSITE_APP})


def number(value, default=0.0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return float(default)


def _alias(value):
    return str(value or "").strip().lower()


def _standard_event_scopes(event_name, extra_scopes=None):
    """Return each standard-event alias and the sources it covers."""
    event = _alias(event_name)
    scopes = {
        event: ALL_CONVERSION_SOURCES,
        f"omni_{event}": ALL_CONVERSION_SOURCES,
        f"offsite_conversion.fb_pixel_{event}": frozenset({OFFSITE_WEB}),
        f"onsite_conversion.{event}": ONSITE_SOURCES,
        f"onsite_web_{event}": frozenset({ONSITE_WEB}),
        f"onsite_web_app_{event}": ONSITE_SOURCES,
        f"web_in_store_{event}": WEB_SOURCES | {IN_STORE},
        f"web_app_in_store_{event}": ALL_CONVERSION_SOURCES,
        f"mobile_app_{event}": frozenset({MOBILE_APP}),
        f"app_custom_event.fb_mobile_{event}": frozenset({MOBILE_APP}),
        f"offline_conversion.{event}": frozenset({IN_STORE}),
        f"offline_{event}": frozenset({IN_STORE}),
        f"in_store_{event}": frozenset({IN_STORE}),
    }
    for name, coverage in (extra_scopes or {}).items():
        scopes[_alias(name)] = frozenset(coverage)
    return scopes


def _equivalent_alias_scopes(canonical, *aliases):
    """Return aliases that are naming variants, not source breakdowns."""
    coverage = frozenset({f"logical:{canonical}"})
    return {_alias(name): coverage for name in aliases}


# A scope map is more precise than a flat alias set: it lets the product
# collapse Meta rollups without erasing genuinely separate web/app/store
# results. Composite metrics (for example purchase-plus-call rollups) do not
# belong here because they are not equivalent to one standard event.
ACTION_ALIAS_SCOPES = {
    "landing_page_views": _standard_event_scopes(
        "landing_page_view",
        {"landing_page_views": ALL_CONVERSION_SOURCES},
    ),
    "view_content": _standard_event_scopes("view_content"),
    "search": _standard_event_scopes("search"),
    "add_to_wishlist": _standard_event_scopes("add_to_wishlist"),
    "add_to_cart": _standard_event_scopes("add_to_cart"),
    "initiate_checkout": _standard_event_scopes(
        "initiate_checkout",
        {
            "initiated_checkout": ALL_CONVERSION_SOURCES,
            "omni_initiated_checkout": ALL_CONVERSION_SOURCES,
            "offsite_conversion.fb_pixel_initiated_checkout": {OFFSITE_WEB},
            "onsite_conversion.initiated_checkout": ONSITE_SOURCES,
            "onsite_web_initiated_checkout": {ONSITE_WEB},
            "onsite_web_app_initiated_checkout": ONSITE_SOURCES,
            "web_in_store_initiated_checkout": WEB_SOURCES | {IN_STORE},
            "web_app_in_store_initiated_checkout": ALL_CONVERSION_SOURCES,
            "mobile_app_initiated_checkout": {MOBILE_APP},
            "app_custom_event.fb_mobile_initiated_checkout": {MOBILE_APP},
        },
    ),
    "add_payment_info": _standard_event_scopes("add_payment_info"),
    "purchase": _standard_event_scopes(
        "purchase",
        {"offsite_purchase": {OFFSITE_WEB}},
    ),
    "lead": _standard_event_scopes(
        "lead",
        {
            "onsite_conversion.lead_grouped": ONSITE_SOURCES,
            "leadgen_grouped": ONSITE_SOURCES,
        },
    ),
    "complete_registration": _standard_event_scopes("complete_registration"),
    "contact": _standard_event_scopes("contact"),
    "customize_product": _standard_event_scopes("customize_product"),
    "donate": _standard_event_scopes("donate"),
    "find_location": _standard_event_scopes("find_location"),
    "schedule": _standard_event_scopes("schedule"),
    "start_trial": _standard_event_scopes("start_trial"),
    "submit_application": _standard_event_scopes("submit_application"),
    "subscribe": _standard_event_scopes("subscribe"),
    "conversation": _equivalent_alias_scopes(
        "conversation",
        "messaging_conversation_started",
        "messaging_conversation_started_7d",
        "onsite_conversion.messaging_conversation_started",
        "onsite_conversion.messaging_conversation_started_7d",
    ),
    "thruplay": _equivalent_alias_scopes(
        "thruplay",
        "video_thruplay_watched_actions",
        "video_thruplay_watched_action",
        "thruplay",
    ),
    "video_3s_views": _equivalent_alias_scopes(
        "video_3s_views",
        "video_view",
        "video_3_sec_watched_actions",
        "video_3s_views",
    ),
    "completed_video_views": _equivalent_alias_scopes(
        "completed_video_views",
        "video_p100_watched_actions",
        "completed_video_view",
        "completed_video_views",
    ),
    "app_install": _equivalent_alias_scopes(
        "app_install",
        "app_install",
        "mobile_app_install",
        "omni_app_install",
        "app_custom_event.fb_mobile_install",
    ),
    "post_engagement": _equivalent_alias_scopes("post_engagement", "post_engagement"),
    "page_engagement": _equivalent_alias_scopes("page_engagement", "page_engagement"),
    "event_response": _equivalent_alias_scopes("event_response", "event_response", "rsvp"),
}

ACTION_ALIASES = {
    canonical: frozenset(scopes)
    for canonical, scopes in ACTION_ALIAS_SCOPES.items()
}
FUNNEL_ACTIONS = {key: frozenset(value) for key, value in ACTION_ALIASES.items()}
PURCHASE_VALUE_ACTIONS = FUNNEL_ACTIONS["purchase"]

# When objective context is unavailable, these are possible result families.
# They must not be added together: one person can Lead, Contact and Purchase in
# the same funnel. ``conversion_result_value`` therefore selects the strongest
# single family, while callers that explicitly request independent outcomes can
# still use ``deduplicated_alias_value``.
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
ALIAS_TO_SCOPE = {}
for _canonical, _scopes in ACTION_ALIAS_SCOPES.items():
    for _name, _coverage in _scopes.items():
        previous = ALIAS_TO_CANONICAL.setdefault(_name, _canonical)
        if previous != _canonical:
            raise RuntimeError(f"Meta action alias {_name!r} belongs to two canonical metrics")
        ALIAS_TO_SCOPE[_name] = frozenset(_coverage)


def normalize_action_type(value):
    return _alias(value)


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


def _best_non_overlapping_total(scoped_values):
    """Choose the most authoritative set of non-overlapping source totals.

    Candidate combinations are ranked by source coverage first, then by the
    fewest aliases (an aggregate is preferable to its details), and finally by
    value. The candidate count is tiny for Meta's standard events, so an
    exhaustive search is both deterministic and easier to audit.
    """
    by_scope = {}
    for coverage, value in scoped_values:
        scope = frozenset(coverage)
        by_scope[scope] = max(by_scope.get(scope, 0.0), number(value))
    # Meta normally omits zero-value aliases. If a stale zero rollup is
    # returned beside positive source detail, it must not erase real results.
    candidates = [(scope, value) for scope, value in by_scope.items() if value > 0]
    if not candidates:
        return 0.0
    best_score = (-1, float("-inf"), float("-inf"))
    best_total = 0.0

    def visit(index, covered, total, count):
        nonlocal best_score, best_total
        if index >= len(candidates):
            score = (len(covered), -count, total)
            if score > best_score:
                best_score = score
                best_total = total
            return
        visit(index + 1, covered, total, count)
        scope, value = candidates[index]
        if covered.isdisjoint(scope):
            visit(index + 1, covered | scope, total + value, count + 1)

    visit(0, frozenset(), 0.0, 0)
    return best_total


def canonical_action_totals(rows):
    """Return one value per event, respecting Meta rollups and source scopes."""
    candidates = {}
    unknown = {}
    for action_type, total in exact_action_totals(rows).items():
        canonical = ALIAS_TO_CANONICAL.get(action_type)
        if canonical is None:
            unknown[action_type] = total
            continue
        candidates.setdefault(canonical, []).append((ALIAS_TO_SCOPE[action_type], total))
    totals = dict(unknown)
    totals.update({
        canonical: _best_non_overlapping_total(values)
        for canonical, values in candidates.items()
    })
    return totals


def canonical_action_value(rows, action):
    return canonical_action_totals(rows).get(canonical_action_key(action), 0.0)


def canonical_funnel_values(rows):
    """Return canonical values for every dashboard-supported event family."""
    totals = canonical_action_totals(rows)
    return {
        key: totals[key]
        for key in FUNNEL_ACTIONS
        if key in totals
    }


def deduplicated_alias_value(rows, names):
    """Sum explicitly requested logical events, counting each family once."""
    totals = canonical_action_totals(rows)
    requested = {canonical_action_key(name) for name in names or [] if normalize_action_type(name)}
    return sum(totals.get(canonical, 0.0) for canonical in requested)


def conversion_result_value(rows):
    """Return one safe generic result total when the campaign objective is absent."""
    totals = canonical_action_totals(rows)
    return max((totals.get(key, 0.0) for key in CONVERSION_RESULT_KEYS), default=0.0)


def reporting_contract():
    """Deterministic release invariants for aliases, rollups and source totals."""
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
    disjoint_sources = canonical_action_value(
        [
            {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "3"},
            {"action_type": "onsite_web_purchase", "value": "2"},
            {"action_type": "mobile_app_purchase", "value": "4"},
            {"action_type": "offline_conversion.purchase", "value": "1"},
        ],
        "purchase",
    )
    rollup_plus_app = canonical_action_value(
        [
            {"action_type": "web_in_store_purchase", "value": "6"},
            {"action_type": "mobile_app_purchase", "value": "2"},
        ],
        "purchase",
    )
    zero_rollup_fallback = canonical_action_value(
        [
            {"action_type": "omni_purchase", "value": "0"},
            {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "5"},
        ],
        "purchase",
    )
    mixed_results = hotmart_actions + [{"action_type": "lead", "value": "4"}]
    return {
        "hotmart_purchase": canonical_action_value(hotmart_actions, "purchase"),
        "hotmart_revenue": canonical_action_value(hotmart_values, "purchase"),
        "every_family_once": every_family_once,
        "repeated_fragments": repeated_fragments,
        "disjoint_sources": disjoint_sources,
        "rollup_plus_app": rollup_plus_app,
        "zero_rollup_fallback": zero_rollup_fallback,
        "generic_result": conversion_result_value(mixed_results),
        "explicit_distinct_results": deduplicated_alias_value(
            mixed_results,
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
        "disjoint_sources": 10.0,
        "rollup_plus_app": 8.0,
        "zero_rollup_fallback": 5.0,
        "generic_result": 4.0,
        "explicit_distinct_results": 5.0,
    }
    failures = {
        key: {"expected": expected[key], "actual": value}
        for key, value in result.items()
        if value != expected[key]
    }
    if failures:
        raise AssertionError(f"Meta action reporting contract failed: {failures}")
    return result
