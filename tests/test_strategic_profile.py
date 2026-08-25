from __future__ import annotations

from contextlib import contextmanager
import re

from strategic_profile import (
    TOPICS,
    StrategicProfileError,
    StrategicProfileNotReady,
    StrategicProfileScopeMismatch,
    action_eligibility,
    apply_topic_updates,
    confirm_current_revision,
    embed_profile,
    mark_review_presented,
    migrate_profile,
    new_profile,
    profile_readiness,
    profile_status,
)


NOW_1 = "2026-08-22T12:00:00+00:00"
NOW_2 = "2026-08-22T12:01:00+00:00"
NOW_3 = "2026-08-22T12:02:00+00:00"
PAGE_A = "1319759131214498"
PAGE_B = "9999999999999999"
BINDING = {"chat_id": "42", "session_id": "telegram:42", "transport": "telegram"}


@contextmanager
def raises(error_type, *, match):
    try:
        yield
    except error_type as exc:
        assert re.search(match, str(exc)), str(exc)
    else:
        raise AssertionError(f"Expected {error_type.__name__}")


def all_resolved_updates():
    updates = {}
    for topic in TOPICS:
        updates[topic] = {
            "status": "confirmed",
            "value": f"confirmed {topic}",
            "confirmation_state": "buyer_confirmed",
        }
    return updates


def present_and_confirm(profile, *, now=NOW_3, confirmation_sequence=12):
    ready_sequence = profile["review_ready"]["ready_after_sequence"]
    profile = mark_review_presented(
        profile,
        page_id=PAGE_A,
        after_buyer_message_sequence=ready_sequence,
        assistant_message_hash="summary-hash",
        evidence={**BINDING, "message_sequence": ready_sequence},
        now=NOW_2,
    )
    return confirm_current_revision(
        profile,
        page_id=PAGE_A,
        trusted_buyer_confirmation=True,
        evidence={**BINDING, "message_sequence": confirmation_sequence},
        now=now,
    )


def test_new_profile_is_empty_and_page_scoped():
    profile = new_profile(PAGE_A, now=NOW_1)

    assert profile["schema_version"] == 2
    assert profile["scope"] == {"page_id": PAGE_A}
    assert profile["revision"] == 0
    assert profile["confirmed_revision"] is None
    assert profile_status(profile, active_page_id=PAGE_A) == "empty"
    assert profile_readiness(profile, active_page_id=PAGE_A)["unresolved_topics"] == list(TOPICS)


def test_finalized_review_atomically_repairs_missing_ready_boundary():
    profile = apply_topic_updates(
        new_profile(PAGE_A, now=NOW_1),
        all_resolved_updates(),
        page_id=PAGE_A,
        trusted_buyer_confirmation=True,
        evidence={**BINDING, "message_sequence": 10},
        now=NOW_2,
    )
    # Reproduce an official cross-store/migrated profile whose topics are all
    # trusted but whose final update did not carry a transport sequence.
    profile["review_ready"] = None

    repaired = mark_review_presented(
        profile,
        page_id=PAGE_A,
        after_buyer_message_sequence=11,
        assistant_message_hash="summary-hash",
        evidence={
            **BINDING,
            "source": "finalized_outbound_transport",
            "message_sequence": 11,
            "trusted_server_evidence": True,
        },
        now=NOW_3,
    )

    assert repaired["review_ready"] == {
        "revision": repaired["revision"],
        "ready_after_sequence": 11,
        "trusted_server_evidence": True,
        "ready_at": NOW_3,
    }
    assert repaired["review_presentation"]["revision"] == repaired["revision"]


def test_legacy_four_fields_and_model_completion_flag_never_complete_profile():
    legacy = {
        "main_offer": "Diseño de sonrisa",
        "ideal_customer": "Adultos de Cartagena",
        "current_stage": "Cuenta nueva",
        "what_to_improve": "Conseguir pacientes",
        "context_complete": True,
        "context_completed_at": NOW_1,
        "page_id": PAGE_A,
    }

    profile = migrate_profile(legacy, page_id=PAGE_A, now=NOW_1)
    readiness = profile_readiness(profile, active_page_id=PAGE_A)

    assert readiness["status"] == "collecting"
    assert readiness["complete"] is False
    assert readiness["resolved_topics"] == []
    assert set(readiness["draft_topics"]) == {
        "services",
        "ideal_customer",
        "advertising_experience",
        "global_objectives",
    }
    assert profile["revision"] == 0


def test_untrusted_model_claim_is_only_a_draft():
    profile = apply_topic_updates(
        new_profile(PAGE_A, now=NOW_1),
        {
            "services": {
                "value": ["Diseño de sonrisa"],
                "status": "confirmed",
                "confirmation_state": "buyer_confirmed",
            }
        },
        page_id=PAGE_A,
        trusted_buyer_confirmation=False,
        now=NOW_2,
    )

    assert profile["revision"] == 0
    assert "status" not in profile["topics"]["services"]
    assert profile["topics"]["services"]["draft"]["confirmation_state"] == "inferred"
    assert profile_readiness(profile, active_page_id=PAGE_A)["resolved_topics"] == []


def test_agent_proposals_and_inferences_do_not_count_as_confirmed():
    profile = new_profile(PAGE_A, now=NOW_1)
    profile = apply_topic_updates(
        profile,
        {
            "branding": {
                "value": "Azul y dorado",
                "confirmation_state": "agent_proposal",
            },
            "pricing": {
                "value": "COP 2.000.000",
                "confirmation_state": "inferred",
            },
        },
        page_id=PAGE_A,
        now=NOW_2,
    )

    readiness = profile_readiness(profile, active_page_id=PAGE_A)
    assert readiness["status"] == "collecting"
    assert readiness["resolved_topics"] == []
    assert set(readiness["draft_topics"]) == {"branding", "pricing"}


def test_all_topics_resolved_requires_review_before_complete():
    profile = apply_topic_updates(
        new_profile(PAGE_A, now=NOW_1),
        all_resolved_updates(),
        page_id=PAGE_A,
        trusted_buyer_confirmation=True,
        evidence={**BINDING, "message_hash": "abc", "message_sequence": 10},
        now=NOW_2,
    )

    readiness = profile_readiness(profile, active_page_id=PAGE_A)
    assert profile["revision"] == 1
    assert readiness["status"] == "review_required"
    assert readiness["review_required"] is True
    assert readiness["complete"] is False
    assert readiness["unresolved_topics"] == []


def test_unknown_and_withheld_are_explicit_resolutions():
    updates = all_resolved_updates()
    updates["margins"] = {
        "status": "withheld",
        "value": None,
        "confirmation_state": "buyer_confirmed",
    }
    updates["advertising_experience"] = {
        "status": "unknown",
        "value": None,
        "confirmation_state": "buyer_confirmed",
    }

    profile = apply_topic_updates(
        new_profile(PAGE_A, now=NOW_1),
        updates,
        page_id=PAGE_A,
        trusted_buyer_confirmation=True,
        evidence={**BINDING, "message_sequence": 10},
        now=NOW_2,
    )

    assert profile_status(profile, active_page_id=PAGE_A) == "review_required"


def test_explicit_review_confirmation_binds_current_revision():
    profile = apply_topic_updates(
        new_profile(PAGE_A, now=NOW_1),
        all_resolved_updates(),
        page_id=PAGE_A,
        trusted_buyer_confirmation=True,
        evidence={**BINDING, "message_sequence": 10},
        now=NOW_2,
    )
    profile = present_and_confirm(profile)

    assert profile["review_confirmation"]["revision"] == 1
    assert profile["confirmed_revision"] == 1
    assert profile["review_confirmation"]["trusted_server_evidence"] is True
    assert profile_status(profile, active_page_id=PAGE_A) == "complete"


def test_review_cannot_be_asserted_by_model_or_before_readiness():
    empty = new_profile(PAGE_A, now=NOW_1)
    with raises(StrategicProfileError, match="trusted server-owned"):
        confirm_current_revision(
            empty,
            page_id=PAGE_A,
            trusted_buyer_confirmation=False,
            now=NOW_2,
        )
    with raises(StrategicProfileNotReady, match="unresolved topics"):
        confirm_current_revision(
            empty,
            page_id=PAGE_A,
            trusted_buyer_confirmation=True,
            evidence={**BINDING, "message_sequence": 1},
            now=NOW_2,
        )


def test_resolved_revision_without_review_ready_cannot_complete():
    profile = apply_topic_updates(
        new_profile(PAGE_A, now=NOW_1),
        all_resolved_updates(),
        page_id=PAGE_A,
        trusted_buyer_confirmation=True,
        now=NOW_2,
    )
    assert profile["review_ready"] is None
    with raises(StrategicProfileNotReady, match="review-ready"):
        confirm_current_revision(
            profile,
            page_id=PAGE_A,
            trusted_buyer_confirmation=True,
            evidence={**BINDING, "message_sequence": 11},
            now=NOW_3,
        )


def test_review_confirmation_cannot_cross_session_or_transport():
    profile = apply_topic_updates(
        new_profile(PAGE_A, now=NOW_1),
        all_resolved_updates(),
        page_id=PAGE_A,
        trusted_buyer_confirmation=True,
        evidence={**BINDING, "message_sequence": 10},
        now=NOW_2,
    )
    profile = mark_review_presented(
        profile,
        page_id=PAGE_A,
        after_buyer_message_sequence=10,
        assistant_message_hash="summary",
        evidence={**BINDING, "message_sequence": 10},
        now=NOW_2,
    )
    for mismatch in (
        {**BINDING, "session_id": "telegram:other", "message_sequence": 11},
        {**BINDING, "transport": "dashboard", "message_sequence": 11},
        {**BINDING, "chat_id": "99", "message_sequence": 11},
    ):
        with raises(StrategicProfileNotReady, match="does not match"):
            confirm_current_revision(
                profile,
                page_id=PAGE_A,
                trusted_buyer_confirmation=True,
                evidence=mismatch,
                now=NOW_3,
            )


def test_correction_increments_revision_and_invalidates_review():
    profile = apply_topic_updates(
        new_profile(PAGE_A, now=NOW_1),
        all_resolved_updates(),
        page_id=PAGE_A,
        trusted_buyer_confirmation=True,
        evidence={**BINDING, "message_sequence": 10},
        now=NOW_1,
    )
    profile = present_and_confirm(profile, now=NOW_2)
    assert profile_status(profile, active_page_id=PAGE_A) == "complete"

    corrected = apply_topic_updates(
        profile,
        {
            "services": {
                "value": ["Ortodoncia", "Diseño de sonrisa"],
                "confirmation_state": "buyer_confirmed",
            }
        },
        page_id=PAGE_A,
        trusted_buyer_confirmation=True,
        now=NOW_3,
    )

    assert corrected["revision"] == 2
    assert corrected["confirmed_revision"] is None
    assert corrected["review_confirmation"] is None
    assert profile_status(corrected, active_page_id=PAGE_A) == "review_required"


def test_identical_confirmed_update_does_not_invalidate_review():
    profile = apply_topic_updates(
        new_profile(PAGE_A, now=NOW_1),
        all_resolved_updates(),
        page_id=PAGE_A,
        trusted_buyer_confirmation=True,
        evidence={**BINDING, "message_sequence": 10},
        now=NOW_1,
    )
    profile = present_and_confirm(profile, now=NOW_2)
    unchanged = apply_topic_updates(
        profile,
        {"services": all_resolved_updates()["services"]},
        page_id=PAGE_A,
        trusted_buyer_confirmation=True,
        now=NOW_3,
    )

    assert unchanged["revision"] == 1
    assert unchanged["confirmed_revision"] == 1
    assert unchanged["review_confirmation"] == profile["review_confirmation"]
    assert profile_status(unchanged, active_page_id=PAGE_A) == "complete"


def test_page_mismatch_is_reported_and_mutation_is_rejected():
    profile = new_profile(PAGE_A, now=NOW_1)

    assert profile_status(profile, active_page_id=PAGE_B) == "scope_mismatch"
    with raises(StrategicProfileScopeMismatch, match=PAGE_A):
        apply_topic_updates(
            profile,
            {"services": {"value": "Otro negocio"}},
            page_id=PAGE_B,
            now=NOW_2,
        )
    assert profile["scope"]["page_id"] == PAGE_A


def test_incoming_complete_status_without_trusted_review_is_ignored():
    forged = new_profile(PAGE_A, now=NOW_1)
    forged["status"] = "complete"
    forged["review_confirmation"] = {
        "revision": 0,
        "confirmation_state": "buyer_confirmed",
    }

    canonical = migrate_profile(forged, page_id=PAGE_A, now=NOW_2)
    assert canonical["status"] == "empty"
    assert canonical["review_confirmation"] is None


def test_forged_buyer_confirmed_topic_without_server_evidence_is_unresolved():
    forged = new_profile(PAGE_A, now=NOW_1)
    forged["topics"]["services"] = {
        "status": "confirmed",
        "value": ["Diseño de sonrisa"],
        "confirmation_state": "buyer_confirmed",
    }

    canonical = migrate_profile(forged, page_id=PAGE_A, now=NOW_2)
    assert canonical["topics"]["services"] == {}
    assert profile_readiness(canonical, active_page_id=PAGE_A)["resolved_topics"] == []


def test_action_gate_allows_safe_actions_and_blocks_paid_mutations_until_complete():
    profile = new_profile(PAGE_A, now=NOW_1)

    for category in (
        "conversation",
        "meta_read",
        "oauth",
        "campaign_pause",
        "campaign_delete",
        "spend_decrease",
    ):
        assert action_eligibility(
            profile, active_page_id=PAGE_A, action_category=category
        )["allowed"] is True

    for category in (
        "campaign_create",
        "save_ad_brief",
        "paid_creative",
        "ad_motion_graphics",
        "campaign_activate",
        "spend_increase",
        "future_paid_mutation",
    ):
        decision = action_eligibility(
            profile, active_page_id=PAGE_A, action_category=category
        )
        assert decision["allowed"] is False
        assert decision["code"] == "strategic_profile_required"


def test_action_gate_rejects_scope_mismatch_but_keeps_safety_actions_available():
    profile = new_profile(PAGE_A, now=NOW_1)

    blocked = action_eligibility(
        profile, active_page_id=PAGE_B, action_category="campaign_create"
    )
    safe = action_eligibility(
        profile, active_page_id=PAGE_B, action_category="campaign_pause"
    )
    assert blocked["allowed"] is False
    assert blocked["code"] == "strategic_profile_scope_mismatch"
    assert safe["allowed"] is True


def test_action_gate_opens_after_reviewed_profile_is_complete():
    profile = apply_topic_updates(
        new_profile(PAGE_A, now=NOW_1),
        all_resolved_updates(),
        page_id=PAGE_A,
        trusted_buyer_confirmation=True,
        evidence={**BINDING, "message_sequence": 10},
        now=NOW_2,
    )
    profile = present_and_confirm(profile)

    assert action_eligibility(
        profile, active_page_id=PAGE_A, action_category="campaign_create"
    )["allowed"] is True
    assert action_eligibility(
        profile, active_page_id=PAGE_A, action_category="future_paid_mutation"
    )["allowed"] is True


def test_embed_profile_removes_obsolete_completion_flags():
    memory = {
        "business_name": "Clínica",
        "context_complete": True,
        "context_completed_at": NOW_1,
    }
    embedded = embed_profile(memory, new_profile(PAGE_A, now=NOW_1))

    assert embedded["business_name"] == "Clínica"
    assert embedded["strategic_profile"]["schema_version"] == 2
    assert "context_complete" not in embedded
    assert "context_completed_at" not in embedded


def test_unknown_topics_are_rejected():
    for topic in ("unsupported", ""):
        with raises(StrategicProfileError, match="Unknown"):
            apply_topic_updates(
                new_profile(PAGE_A, now=NOW_1),
                {topic: {"value": "x"}},
                page_id=PAGE_A,
            )


if __name__ == "__main__":
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"{len(tests)} strategic-profile tests passed")
