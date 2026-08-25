"""Server-owned strategic onboarding profile state.

This module intentionally contains no model or transport code.  It gives the
dashboard and tool bridge one canonical, JSON-serialisable state machine for
strategic onboarding.  In particular, callers must derive
``trusted_buyer_confirmation`` from server-owned turn metadata; that value must
never be copied from an MCP/model argument.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping


SCHEMA_VERSION = 2

TOPICS = (
    "services",
    "ideal_customer",
    "differentiators",
    "markets",
    "capacity",
    "pricing",
    "margins",
    "global_objectives",
    "advertising_experience",
    "branding",
)

TOPIC_STATUSES = frozenset(
    {
        "confirmed",
        "provisional_confirmed",
        "unknown",
        "not_applicable",
        "withheld",
    }
)

PROFILE_STATUSES = frozenset(
    {"empty", "collecting", "review_required", "complete", "scope_mismatch"}
)

CLAIMED_CONFIRMATION_STATES = frozenset(
    {"buyer_confirmed", "agent_proposal", "inferred"}
)

# These categories may never mutate or start paid delivery before the current
# Page's strategic profile is complete.
READINESS_REQUIRED_ACTIONS = frozenset(
    {
        "campaign_create",
        "campaign_brief",
        "paid_creative",
        "ad_motion_graphics",
        "campaign_activate",
        "spend_increase",
    }
)

# These operations remain available during onboarding.  Pause/stop/reject are
# deliberately safe so a missing profile can never prevent limiting spend.
ONBOARDING_SAFE_ACTIONS = frozenset(
    {
        "conversation",
        "meta_read",
        "diagnostics",
        "oauth",
        "chatgpt_connection",
        "onboarding_read",
        "onboarding_save",
        "public_asset_read",
        "brand_exploration",
        "creative_moodboard",
        "campaign_pause",
        "campaign_stop",
        "campaign_reject",
        "campaign_delete",
        "spend_decrease",
    }
)

_ACTION_ALIASES = {
    "create_campaign": "campaign_create",
    "campaign_creation": "campaign_create",
    "save_ad_brief": "campaign_brief",
    "image_for_ad": "paid_creative",
    "paid_image": "paid_creative",
    "motion_for_ad": "ad_motion_graphics",
    "activate_campaign": "campaign_activate",
    "increase_budget": "spend_increase",
    "read_meta": "meta_read",
    "pause": "campaign_pause",
    "stop": "campaign_stop",
}

_LEGACY_TOPIC_FIELDS = {
    "main_offer": "services",
    "ideal_customer": "ideal_customer",
    "current_stage": "advertising_experience",
    "what_to_improve": "global_objectives",
    "success_goal": "global_objectives",
}


class StrategicProfileError(ValueError):
    """Base error for invalid strategic-profile transitions."""


class StrategicProfileScopeMismatch(StrategicProfileError):
    """Raised when an update targets a different Page than the profile."""


class StrategicProfileNotReady(StrategicProfileError):
    """Raised when review is confirmed before every topic is resolved."""


def _timestamp(now: Any = None) -> str:
    if now is None:
        value = datetime.now(timezone.utc)
    elif isinstance(now, datetime):
        value = now
    else:
        text = str(now).strip()
        if not text:
            value = datetime.now(timezone.utc)
        else:
            return text
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _clean_page_id(value: Any) -> str:
    return str(value or "").strip()


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _blank_topic() -> dict[str, Any]:
    # Absence of ``status`` means unresolved.  ``unknown`` and ``withheld`` are
    # explicit, buyer-confirmed resolutions and therefore cannot be defaults.
    return {}


def new_profile(page_id: Any, *, now: Any = None) -> dict[str, Any]:
    """Return an empty schema-v2 profile scoped to one Meta Page."""

    return {
        "schema_version": SCHEMA_VERSION,
        "scope": {"page_id": _clean_page_id(page_id)},
        "revision": 0,
        "confirmed_revision": None,
        "status": "empty",
        "topics": {topic: _blank_topic() for topic in TOPICS},
        # ``review_ready`` is created only by a trusted official topic update
        # that resolves the final missing topic. ``review_presentation`` is
        # created later by the outbound transport after it verifies that the
        # assistant actually showed every current value. Neither field is a
        # model-controlled completion flag.
        "review_ready": None,
        "review_presentation": None,
        "review_confirmation": None,
        # This durable latch is set only after the first fully presented and
        # buyer-confirmed business review. Later buyer-confirmed business
        # facts may revise the baseline, but never invalidate its separate
        # strategic plan or send the buyer back through initial onboarding.
        "onboarding_completed_at": None,
        "created_at": _timestamp(now),
        "updated_at": _timestamp(now),
    }


def _legacy_page_id(payload: Mapping[str, Any], fallback: Any = None) -> str:
    scope = payload.get("scope")
    if isinstance(scope, Mapping) and _clean_page_id(scope.get("page_id")):
        return _clean_page_id(scope.get("page_id"))
    for key in ("page_id", "selected_page_id", "facebook_page_id"):
        if _clean_page_id(payload.get(key)):
            return _clean_page_id(payload.get(key))
    return _clean_page_id(fallback)


def _normalise_draft(value: Any, *, source: str, now: Any = None) -> dict[str, Any]:
    claimed = source if source in CLAIMED_CONFIRMATION_STATES else "inferred"
    if claimed == "buyer_confirmed":
        # Untrusted legacy/model data is never promoted merely because it says
        # it was confirmed.
        claimed = "inferred"
    return {
        "value": deepcopy(value),
        "confirmation_state": claimed,
        "updated_at": _timestamp(now),
    }


def migrate_profile(payload: Any, *, page_id: Any = None, now: Any = None) -> dict[str, Any]:
    """Migrate a profile or old business-memory object to canonical schema v2.

    Old ``context_complete``/``context_completed_at`` flags are ignored.  Old
    four-field onboarding values are preserved as inferred drafts, so migration
    can never silently complete onboarding.
    """

    source = deepcopy(payload) if isinstance(payload, Mapping) else {}
    nested = source.get("strategic_profile")
    if isinstance(nested, Mapping):
        source = deepcopy(nested)

    scoped_page_id = _legacy_page_id(source, page_id)
    result = new_profile(scoped_page_id, now=now)

    try:
        incoming_schema_version = int(source.get("schema_version") or 0)
    except (TypeError, ValueError):
        incoming_schema_version = 0

    if incoming_schema_version == SCHEMA_VERSION:
        try:
            incoming_revision = int(source.get("revision") or 0)
        except (TypeError, ValueError):
            incoming_revision = 0
        result["revision"] = max(0, incoming_revision)
        result["created_at"] = str(source.get("created_at") or result["created_at"])
        result["updated_at"] = str(source.get("updated_at") or result["updated_at"])
        if str(source.get("onboarding_completed_at") or "").strip():
            result["onboarding_completed_at"] = str(source["onboarding_completed_at"])

        incoming_topics = source.get("topics")
        if isinstance(incoming_topics, Mapping):
            for topic in TOPICS:
                incoming = incoming_topics.get(topic)
                if not isinstance(incoming, Mapping):
                    continue
                canonical: dict[str, Any] = {}
                topic_status = str(incoming.get("status") or "").strip()
                confirmation_state = str(incoming.get("confirmation_state") or "").strip()
                if (
                    topic_status in TOPIC_STATUSES
                    and confirmation_state == "buyer_confirmed"
                    and incoming.get("trusted_server_evidence") is True
                    and (
                        topic_status in {"unknown", "not_applicable", "withheld"}
                        or _has_value(incoming.get("value"))
                    )
                ):
                    canonical = {
                        "status": topic_status,
                        "value": deepcopy(incoming.get("value")),
                        "confirmation_state": "buyer_confirmed",
                        "trusted_server_evidence": True,
                        "updated_at": str(incoming.get("updated_at") or _timestamp(now)),
                    }
                    if isinstance(incoming.get("evidence"), Mapping):
                        canonical["evidence"] = deepcopy(incoming["evidence"])

                draft = incoming.get("draft")
                if isinstance(draft, Mapping) and _has_value(draft.get("value")):
                    canonical["draft"] = _normalise_draft(
                        draft.get("value"),
                        source=str(draft.get("confirmation_state") or "inferred"),
                        now=draft.get("updated_at") or now,
                    )
                    if str(draft.get("proposed_status") or "") in TOPIC_STATUSES:
                        canonical["draft"]["proposed_status"] = str(draft["proposed_status"])
                result["topics"][topic] = canonical

        ready = source.get("review_ready")
        if isinstance(ready, Mapping):
            ready_revision = _as_int(ready.get("revision"), -1)
            ready_sequence = _as_int(ready.get("ready_after_sequence"), -1)
            if (
                ready_revision == result["revision"]
                and ready_sequence >= 0
                and ready.get("trusted_server_evidence") is True
            ):
                result["review_ready"] = {
                    "revision": ready_revision,
                    "ready_after_sequence": ready_sequence,
                    "trusted_server_evidence": True,
                    "ready_at": str(ready.get("ready_at") or _timestamp(now)),
                }

        presentation = source.get("review_presentation")
        if isinstance(presentation, Mapping):
            presented_revision = _as_int(presentation.get("revision"), -1)
            after_sequence = _as_int(
                presentation.get("after_buyer_message_sequence"), -1
            )
            if (
                presented_revision == result["revision"]
                and after_sequence >= 0
                and presentation.get("trusted_server_evidence") is True
                and result.get("review_ready")
            ):
                result["review_presentation"] = {
                    "revision": presented_revision,
                    "after_buyer_message_sequence": after_sequence,
                    "assistant_message_hash": str(
                        presentation.get("assistant_message_hash") or ""
                    ),
                    "trusted_server_evidence": True,
                    "presented_at": str(
                        presentation.get("presented_at") or _timestamp(now)
                    ),
                    "evidence": deepcopy(presentation.get("evidence") or {}),
                }

        review = source.get("review_confirmation")
        if isinstance(review, Mapping):
            try:
                reviewed_revision = int(review.get("revision"))
            except (TypeError, ValueError):
                reviewed_revision = -1
            standard_review = bool(result.get("review_ready") and result.get("review_presentation"))
            maintenance_review = bool(
                result.get("onboarding_completed_at")
                and review.get("transition") == "post_onboarding_fact_update"
            )
            if (
                reviewed_revision == result["revision"]
                and review.get("confirmation_state") == "buyer_confirmed"
                and review.get("trusted_server_evidence") is True
                and (standard_review or maintenance_review)
            ):
                result["review_confirmation"] = {
                    "revision": reviewed_revision,
                    "confirmation_state": "buyer_confirmed",
                    "trusted_server_evidence": True,
                    "confirmed_at": str(review.get("confirmed_at") or _timestamp(now)),
                    "evidence": deepcopy(review.get("evidence") or {}),
                }
                if maintenance_review:
                    result["review_confirmation"]["transition"] = "post_onboarding_fact_update"
                result["confirmed_revision"] = reviewed_revision
                if not result.get("onboarding_completed_at"):
                    result["onboarding_completed_at"] = result["review_confirmation"]["confirmed_at"]
    else:
        # Preserve useful old answers, but only as drafts.  The old model-owned
        # completion flag had insufficient coverage and cannot be trusted.
        legacy_source = source
        for old_field, topic in _LEGACY_TOPIC_FIELDS.items():
            value = legacy_source.get(old_field)
            if not _has_value(value):
                continue
            existing = result["topics"][topic].get("draft")
            if existing and topic == "global_objectives":
                combined = [existing.get("value"), deepcopy(value)]
                result["topics"][topic]["draft"] = _normalise_draft(
                    combined, source="inferred", now=now
                )
            else:
                result["topics"][topic]["draft"] = _normalise_draft(
                    value, source="inferred", now=now
                )

    result["status"] = _computed_status(result)
    return result


def _resolved_topics(profile: Mapping[str, Any]) -> list[str]:
    topics = profile.get("topics") if isinstance(profile.get("topics"), Mapping) else {}
    resolved = []
    for topic in TOPICS:
        entry = topics.get(topic)
        if not isinstance(entry, Mapping):
            continue
        if (
            entry.get("status") in TOPIC_STATUSES
            and entry.get("confirmation_state") == "buyer_confirmed"
            and entry.get("trusted_server_evidence") is True
        ):
            resolved.append(topic)
    return resolved


def _has_progress(profile: Mapping[str, Any]) -> bool:
    topics = profile.get("topics") if isinstance(profile.get("topics"), Mapping) else {}
    return any(bool(topics.get(topic)) for topic in TOPICS)


def _computed_status(profile: Mapping[str, Any], active_page_id: Any = None) -> str:
    scoped_page = _clean_page_id((profile.get("scope") or {}).get("page_id"))
    active_page = _clean_page_id(active_page_id)
    if active_page and scoped_page and active_page != scoped_page:
        return "scope_mismatch"

    resolved = _resolved_topics(profile)
    if len(resolved) == len(TOPICS):
        review = profile.get("review_confirmation")
        ready = profile.get("review_ready")
        presentation = profile.get("review_presentation")
        revision = _as_int(profile.get("revision"), 0)
        standard_review = bool(
            isinstance(review, Mapping)
            and isinstance(ready, Mapping)
            and isinstance(presentation, Mapping)
            and ready.get("trusted_server_evidence") is True
            and presentation.get("trusted_server_evidence") is True
            and _as_int(ready.get("revision"), -1) == revision
            and _as_int(presentation.get("revision"), -1) == revision
            and review.get("confirmation_state") == "buyer_confirmed"
            and review.get("trusted_server_evidence") is True
            and _as_int(review.get("revision"), -1)
            == revision
            and _as_int(profile.get("confirmed_revision"), -1)
            == revision
        )
        maintenance_review = bool(
            isinstance(review, Mapping)
            and profile.get("onboarding_completed_at")
            and review.get("transition") == "post_onboarding_fact_update"
            and review.get("confirmation_state") == "buyer_confirmed"
            and review.get("trusted_server_evidence") is True
            and _as_int(review.get("revision"), -1) == revision
            and _as_int(profile.get("confirmed_revision"), -1) == revision
        )
        if standard_review or maintenance_review:
            return "complete"
        return "review_required"
    return "collecting" if _has_progress(profile) else "empty"


def profile_status(profile: Any, *, active_page_id: Any = None) -> str:
    canonical = migrate_profile(profile, page_id=active_page_id)
    return _computed_status(canonical, active_page_id)


def profile_readiness(profile: Any, *, active_page_id: Any = None) -> dict[str, Any]:
    canonical = migrate_profile(profile, page_id=active_page_id)
    status = _computed_status(canonical, active_page_id)
    resolved = _resolved_topics(canonical)
    draft_topics = [
        topic
        for topic in TOPICS
        if isinstance(canonical["topics"].get(topic), Mapping)
        and isinstance(canonical["topics"][topic].get("draft"), Mapping)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "page_id": _clean_page_id(canonical.get("scope", {}).get("page_id")),
        "revision": int(canonical.get("revision") or 0),
        "confirmed_revision": canonical.get("confirmed_revision"),
        "status": status,
        "complete": status == "complete",
        "resolved_topics": resolved,
        "unresolved_topics": [topic for topic in TOPICS if topic not in resolved],
        "draft_topics": draft_topics,
        "review_required": status == "review_required",
        "review_ready": bool(
            isinstance(canonical.get("review_ready"), Mapping)
            and _as_int(canonical["review_ready"].get("revision"), -1)
            == _as_int(canonical.get("revision"), 0)
        ),
        "review_presented": bool(
            isinstance(canonical.get("review_presentation"), Mapping)
            and _as_int(canonical["review_presentation"].get("revision"), -1)
            == _as_int(canonical.get("revision"), 0)
        ),
        "onboarding_completed": bool(canonical.get("onboarding_completed_at")),
        "onboarding_completed_at": canonical.get("onboarding_completed_at"),
    }


def _require_scope(profile: Mapping[str, Any], page_id: Any) -> None:
    scoped = _clean_page_id((profile.get("scope") or {}).get("page_id"))
    requested = _clean_page_id(page_id)
    if scoped and requested and scoped != requested:
        raise StrategicProfileScopeMismatch(
            f"Strategic profile belongs to Page {scoped}, not Page {requested}."
        )


def _normalise_update(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    return {"value": deepcopy(value)}


def apply_topic_updates(
    profile: Any,
    updates: Mapping[str, Any],
    *,
    page_id: Any,
    trusted_buyer_confirmation: bool = False,
    evidence: Mapping[str, Any] | None = None,
    now: Any = None,
) -> dict[str, Any]:
    """Apply one buyer turn's topic updates as one canonical revision.

    ``trusted_buyer_confirmation`` is a server-owned capability.  When false,
    even an update claiming ``buyer_confirmed`` is retained only as an inferred
    or proposed draft and cannot satisfy readiness.
    """

    if not isinstance(updates, Mapping):
        raise StrategicProfileError("Topic updates must be a mapping.")

    canonical = migrate_profile(profile, page_id=page_id, now=now)
    _require_scope(canonical, page_id)
    if not _clean_page_id(canonical["scope"].get("page_id")):
        canonical["scope"]["page_id"] = _clean_page_id(page_id)

    was_onboarding_complete = bool(canonical.get("onboarding_completed_at")) or (
        _computed_status(canonical, page_id) == "complete"
    )
    official_changed = False
    any_changed = False
    timestamp = _timestamp(now)

    for topic, raw_update in updates.items():
        if topic not in TOPICS:
            raise StrategicProfileError(f"Unknown strategic-profile topic: {topic}")
        update = _normalise_update(raw_update)
        claimed_state = str(update.get("confirmation_state") or "inferred").strip()
        if claimed_state not in CLAIMED_CONFIRMATION_STATES:
            raise StrategicProfileError(
                f"Invalid confirmation_state for {topic}: {claimed_state}"
            )
        requested_status = str(update.get("status") or "confirmed").strip()
        if requested_status not in TOPIC_STATUSES:
            raise StrategicProfileError(
                f"Invalid topic status for {topic}: {requested_status}"
            )
        value = deepcopy(update.get("value"))
        if requested_status in {"confirmed", "provisional_confirmed"} and not _has_value(
            value
        ):
            raise StrategicProfileError(
                f"Topic {topic} requires a value when status is {requested_status}."
            )

        current = deepcopy(canonical["topics"].get(topic) or {})
        can_confirm = trusted_buyer_confirmation and claimed_state == "buyer_confirmed"
        if can_confirm:
            replacement: dict[str, Any] = {
                "status": requested_status,
                "value": value,
                "confirmation_state": "buyer_confirmed",
                "trusted_server_evidence": True,
                "updated_at": timestamp,
            }
            topic_evidence = update.get("evidence") or evidence
            if isinstance(topic_evidence, Mapping):
                replacement["evidence"] = deepcopy(dict(topic_evidence))

            semantic_current = {
                "status": current.get("status"),
                "value": current.get("value"),
                "confirmation_state": current.get("confirmation_state"),
                "trusted_server_evidence": current.get("trusted_server_evidence"),
            }
            semantic_replacement = {
                "status": replacement.get("status"),
                "value": replacement.get("value"),
                "confirmation_state": replacement.get("confirmation_state"),
                "trusted_server_evidence": replacement.get("trusted_server_evidence"),
            }
            if semantic_current != semantic_replacement:
                canonical["topics"][topic] = replacement
                official_changed = True
                any_changed = True
            continue

        draft_source = claimed_state
        if draft_source == "buyer_confirmed":
            draft_source = "inferred"
        replacement_draft = _normalise_draft(value, source=draft_source, now=timestamp)
        replacement_draft["proposed_status"] = requested_status
        if current.get("draft") != replacement_draft:
            current["draft"] = replacement_draft
            canonical["topics"][topic] = current
            any_changed = True

    if official_changed:
        canonical["revision"] = int(canonical.get("revision") or 0) + 1
        canonical["review_ready"] = None
        canonical["review_presentation"] = None
        canonical["review_confirmation"] = None
        canonical["confirmed_revision"] = None
        # Once the initial business review has completed, a later fact stated
        # by the buyer is an active-profile maintenance update, not a return to
        # onboarding. The exact trusted turn already authorizes that fact. The
        # new profile revision becomes current immediately. Strategic plans are
        # separate artifacts and remain untouched unless the buyer directly
        # asks to revise the plan itself.
        if was_onboarding_complete and len(_resolved_topics(canonical)) == len(TOPICS):
            canonical["onboarding_completed_at"] = str(
                canonical.get("onboarding_completed_at") or timestamp
            )
            canonical["confirmed_revision"] = int(canonical["revision"])
            canonical["review_confirmation"] = {
                "revision": int(canonical["revision"]),
                "confirmation_state": "buyer_confirmed",
                "trusted_server_evidence": True,
                "transition": "post_onboarding_fact_update",
                "confirmed_at": timestamp,
                "evidence": deepcopy(dict(evidence or {})),
            }
    if any_changed:
        canonical["updated_at"] = timestamp
    canonical["status"] = _computed_status(canonical)
    if official_changed and canonical["status"] == "review_required":
        sequence = _as_int((evidence or {}).get("message_sequence"), -1)
        if sequence >= 0:
            canonical["review_ready"] = {
                "revision": int(canonical.get("revision") or 0),
                "ready_after_sequence": sequence,
                "trusted_server_evidence": True,
                "ready_at": timestamp,
            }
    return canonical


def mark_review_presented(
    profile: Any,
    *,
    page_id: Any,
    after_buyer_message_sequence: Any,
    assistant_message_hash: Any,
    evidence: Mapping[str, Any] | None = None,
    now: Any = None,
) -> dict[str, Any]:
    """Record a fully covered summary at the finalized outbound boundary.

    Callers must verify summary coverage before invoking this function.  The
    state machine still verifies that the summary belongs to the current
    revision and to a trusted finalized outbound turn.

    A fully resolved profile can legitimately lack ``review_ready`` when its
    final topic was synchronized by another official store (for example, an
    already-approved brand migrated into the Page-scoped profile).  In that
    case the finalized outbound boundary is the first server-owned moment at
    which the complete revision can be reviewed.  Establish ``review_ready``
    and ``review_presentation`` together instead of leaving the revision in an
    impossible state that no later buyer confirmation can complete.
    """

    canonical = migrate_profile(profile, page_id=page_id, now=now)
    _require_scope(canonical, page_id)
    if _computed_status(canonical, page_id) != "review_required":
        raise StrategicProfileNotReady(
            "Strategic profile is not waiting for a current revision review."
        )
    revision = _as_int(canonical.get("revision"), 0)
    sequence = _as_int(after_buyer_message_sequence, -1)
    if sequence < 0:
        raise StrategicProfileNotReady(
            "Review presentation requires a trusted buyer-turn sequence."
        )
    ready = canonical.get("review_ready")
    if not isinstance(ready, Mapping) or ready.get("trusted_server_evidence") is not True:
        boundary_evidence = evidence if isinstance(evidence, Mapping) else {}
        evidence_sequence = _as_int(boundary_evidence.get("message_sequence"), -1)
        binding_complete = all(
            str(boundary_evidence.get(key) or "").strip()
            for key in ("chat_id", "session_id", "transport")
        )
        if (
            boundary_evidence.get("source") != "finalized_outbound_transport"
            or boundary_evidence.get("trusted_server_evidence") is not True
            or evidence_sequence != sequence
            or not binding_complete
        ):
            raise StrategicProfileNotReady(
                "Current revision has no trusted review-ready boundary."
            )
        canonical["review_ready"] = {
            "revision": revision,
            "ready_after_sequence": sequence,
            "trusted_server_evidence": True,
            "ready_at": _timestamp(now),
        }
        ready = canonical["review_ready"]
    if _as_int(ready.get("revision"), -1) != revision:
        raise StrategicProfileNotReady(
            "Review-ready evidence belongs to another revision."
        )
    if sequence < _as_int(ready.get("ready_after_sequence"), -1):
        raise StrategicProfileNotReady(
            "Review summary cannot precede the turn that completed the revision."
        )
    message_hash = str(assistant_message_hash or "").strip()
    if not message_hash:
        raise StrategicProfileError("Review presentation requires an assistant message hash.")
    timestamp = _timestamp(now)
    canonical["review_presentation"] = {
        "revision": revision,
        "after_buyer_message_sequence": sequence,
        "assistant_message_hash": message_hash,
        "trusted_server_evidence": True,
        "presented_at": timestamp,
        "evidence": deepcopy(dict(evidence or {})),
    }
    canonical["updated_at"] = timestamp
    canonical["status"] = _computed_status(canonical)
    return canonical


def confirm_current_revision(
    profile: Any,
    *,
    page_id: Any,
    trusted_buyer_confirmation: bool,
    evidence: Mapping[str, Any] | None = None,
    now: Any = None,
) -> dict[str, Any]:
    """Bind explicit, trusted buyer review to the profile's current revision."""

    canonical = migrate_profile(profile, page_id=page_id, now=now)
    _require_scope(canonical, page_id)
    if not trusted_buyer_confirmation:
        raise StrategicProfileError(
            "Review confirmation requires trusted server-owned buyer evidence."
        )
    readiness = profile_readiness(canonical, active_page_id=page_id)
    if readiness["unresolved_topics"]:
        raise StrategicProfileNotReady(
            "Strategic profile still has unresolved topics: "
            + ", ".join(readiness["unresolved_topics"])
        )
    ready = canonical.get("review_ready")
    if (
        not isinstance(ready, Mapping)
        or ready.get("trusted_server_evidence") is not True
        or _as_int(ready.get("revision"), -1)
        != _as_int(canonical.get("revision"), 0)
    ):
        raise StrategicProfileNotReady(
            "Current revision has no trusted review-ready boundary."
        )
    presentation = canonical.get("review_presentation")
    if (
        not isinstance(presentation, Mapping)
        or presentation.get("trusted_server_evidence") is not True
        or _as_int(presentation.get("revision"), -1)
        != _as_int(canonical.get("revision"), 0)
    ):
        raise StrategicProfileNotReady(
            "The current revision summary was not verified at the outbound boundary."
        )
    confirmation_sequence = _as_int((evidence or {}).get("message_sequence"), -1)
    presented_after = _as_int(
        presentation.get("after_buyer_message_sequence"), -1
    )
    if confirmation_sequence <= presented_after:
        raise StrategicProfileNotReady(
            "Review confirmation must come from a later buyer turn."
        )
    presentation_evidence = (
        presentation.get("evidence")
        if isinstance(presentation.get("evidence"), Mapping)
        else {}
    )
    confirmation_evidence = evidence if isinstance(evidence, Mapping) else {}
    for binding in ("chat_id", "session_id", "transport"):
        presented_value = str(presentation_evidence.get(binding) or "").strip()
        confirmed_value = str(confirmation_evidence.get(binding) or "").strip()
        if not presented_value or presented_value != confirmed_value:
            raise StrategicProfileNotReady(
                f"Review confirmation {binding} does not match the presented revision."
            )
    timestamp = _timestamp(now)
    canonical["review_confirmation"] = {
        "revision": int(canonical.get("revision") or 0),
        "confirmation_state": "buyer_confirmed",
        "trusted_server_evidence": True,
        "confirmed_at": timestamp,
        "evidence": deepcopy(dict(evidence or {})),
    }
    canonical["confirmed_revision"] = int(canonical.get("revision") or 0)
    canonical["onboarding_completed_at"] = str(
        canonical.get("onboarding_completed_at") or timestamp
    )
    canonical["updated_at"] = timestamp
    canonical["status"] = _computed_status(canonical)
    return canonical


def action_eligibility(
    profile: Any,
    *,
    active_page_id: Any,
    action_category: Any,
) -> dict[str, Any]:
    """Return a fail-closed onboarding decision for a product action category."""

    category = str(action_category or "").strip().lower()
    category = _ACTION_ALIASES.get(category, category)
    readiness = profile_readiness(profile, active_page_id=active_page_id)

    if category in ONBOARDING_SAFE_ACTIONS:
        allowed = True
        code = "safe_during_onboarding"
    elif readiness["complete"]:
        allowed = True
        code = "strategic_profile_complete"
    else:
        # Unknown categories fail closed while onboarding is incomplete.  This
        # prevents a newly added paid mutation from silently bypassing the gate.
        allowed = False
        code = (
            "strategic_profile_scope_mismatch"
            if readiness["status"] == "scope_mismatch"
            else "strategic_profile_required"
        )

    return {
        "allowed": allowed,
        "code": code,
        "action_category": category,
        "profile_status": readiness["status"],
        "page_id": readiness["page_id"],
        "revision": readiness["revision"],
        "confirmed_revision": readiness["confirmed_revision"],
        "unresolved_topics": readiness["unresolved_topics"],
    }


def embed_profile(container: Any, profile: Any) -> dict[str, Any]:
    """Return a copy of business memory with one canonical profile embedded."""

    result = deepcopy(container) if isinstance(container, Mapping) else {}
    result["strategic_profile"] = migrate_profile(profile)
    # Remove obsolete model-owned completion flags so no caller can read them
    # accidentally after migration.
    result.pop("context_complete", None)
    result.pop("context_completed_at", None)
    return result
