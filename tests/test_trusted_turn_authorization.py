#!/usr/bin/env python3
"""Focused regressions for transport-bound, one-use buyer evidence."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import admira_tool_bridge
from strategic_profile import TOPICS, apply_topic_updates, new_profile


PAGE = "1319759131214498"


class _NoIntentAuthorizer:
    def current_intent(self, **_kwargs):
        return None


class TrustedTurnAuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboard = admira_tool_bridge.load_dashboard()

    def setUp(self):
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        self.patchers = [
            patch.object(self.dashboard, "TRUSTED_BUYER_TURN_FILE", root / "turn.json"),
            patch.object(self.dashboard, "TRUSTED_BUYER_TURN_LOCK_FILE", root / "turn.lock"),
            patch.object(self.dashboard, "MEMORY_DRAFTS_FILE", root / "drafts.json"),
            patch.object(self.dashboard, "_meta_oauth_selection_authorizer", return_value=_NoIntentAuthorizer()),
        ]
        for item in self.patchers:
            item.start()

    def tearDown(self):
        for item in reversed(self.patchers):
            item.stop()
        self.temp.cleanup()

    def _record(self, message, sequence=1):
        return self.dashboard.record_trusted_buyer_turn(
            "dashboard:owner",
            "agent:main:dashboard:owner",
            sequence,
            message,
            transport="dashboard",
        )

    def test_failed_new_capture_clears_stale_evidence(self):
        self._record("Ofrecemos implantes dentales")
        self.assertTrue(self.dashboard._trusted_buyer_turn())
        with self.assertRaises(ValueError):
            self.dashboard.record_trusted_buyer_turn(
                "wrong-prefix",
                "agent:main:dashboard:owner",
                2,
                "otro mensaje",
                transport="dashboard",
            )
        self.assertEqual(self.dashboard._trusted_buyer_turn(), {})

    def test_store_capability_is_one_use_but_other_store_is_independent(self):
        message = "Mi clínica ofrece implantes y atiende adultos en Cartagena"
        self._record(message)
        business = {
            "confirmation_state": "buyer_confirmed",
            "buyer_evidence": message,
            "services": ["Implantes"],
        }
        with self.dashboard._trusted_memory_capability(
            "business", business, scope=PAGE, profile={}
        ) as authorization:
            self.assertTrue(authorization["authorized"])
            authorization["commit"] = True
        with self.dashboard._trusted_memory_capability(
            "business", business, scope=PAGE, profile={}
        ) as reused:
            self.assertFalse(reused["authorized"])
            self.assertEqual(reused["reason"], "trusted_turn_capability_already_used")
        brand = {
            "confirmation_state": "buyer_confirmed",
            "buyer_evidence": message,
            "brand_name": "Mi clínica",
        }
        with self.dashboard._trusted_memory_capability(
            "brand", brand, scope=PAGE
        ) as independent:
            self.assertTrue(independent["authorized"])

    def test_short_confirmation_promotes_only_exact_matching_draft(self):
        scope = PAGE
        draft = {"confirmation_state": "agent_proposal", "brand_name": "Clínica Azul"}
        self.dashboard.save_memory_draft("brand", draft, scope=scope)
        self._record("Sí", sequence=2)
        matching = {
            "confirmation_state": "buyer_confirmed",
            "buyer_evidence": "Sí",
            "brand_name": "Clínica Azul",
        }
        with self.dashboard._trusted_memory_capability("brand", matching, scope=scope) as accepted:
            self.assertTrue(accepted["authorized"])
        changed = {**matching, "brand_name": "Marca inventada"}
        with self.dashboard._trusted_memory_capability("product", changed, scope=scope) as rejected:
            self.assertFalse(rejected["authorized"])
            self.assertEqual(rejected["reason"], "short_confirmation_has_no_matching_draft")

    def test_summary_coverage_requires_each_actual_value(self):
        updates = {
            topic: {
                "status": "confirmed",
                "value": f"valor real {topic}",
                "confirmation_state": "buyer_confirmed",
            }
            for topic in TOPICS
        }
        profile = apply_topic_updates(
            new_profile(PAGE),
            updates,
            page_id=PAGE,
            trusted_buyer_confirmation=True,
            evidence={"message_sequence": 10},
        )
        summary = self.dashboard.strategic_profile_review_summary(profile)
        self.assertTrue(
            self.dashboard._assistant_summary_covers_strategic_profile(profile, summary)
        )
        self.assertFalse(
            self.dashboard._assistant_summary_covers_strategic_profile(
                profile,
                summary.replace("valor real pricing", "otro valor", 1),
            )
        )


if __name__ == "__main__":
    unittest.main()
