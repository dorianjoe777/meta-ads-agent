import json
import tempfile
import unittest
from pathlib import Path

from src.meta_selection_authorization import (
    MetaSelectionAuthorizer,
    SelectionBindingMismatch,
    SelectionIntentNotFound,
    SelectionTicketInvalid,
    inventory_fingerprint,
    resolve_selection_message,
)


INVENTORY = {
    "accounts": [
        {"id": "act_100", "name": "Dorian Principal", "currency": "USD", "access_token": "never-store-account"},
        {"id": "act_200", "name": "DOrian2", "currency": "COP", "access_token": "never-store-account-2"},
    ],
    "pages": [
        {"id": "1319759131214498", "name": "Odontóloga María Flores", "access_token": "never-store-page"},
        {"id": "9988776655443322", "name": "Rodeo Car Detailing", "access_token": "never-store-page-2"},
    ],
}


class MutableClock:
    def __init__(self, value=1_000.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class MetaSelectionAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = MutableClock()
        self.state_path = Path(self.temp.name) / "meta-selection.json"
        self.authorizer = MetaSelectionAuthorizer(
            self.state_path,
            signing_key=b"t" * 32,
            ttl_seconds=60,
            clock=self.clock,
        )

    def tearDown(self):
        self.temp.cleanup()

    def open(self, *, current=None, mode="auto", sequence=10, inventory=INVENTORY):
        return self.authorizer.open_intent(
            chat_id="telegram:123",
            session_id="session-a",
            inventory=inventory,
            current_pair=current or {},
            opened_after_sequence=sequence,
            mode=mode,
        )

    def authorize(self, opened, message, *, sequence=11, current=None, inventory=INVENTORY, chat="telegram:123", session="session-a"):
        return self.authorizer.authorize_message(
            intent_id=opened["intent_id"],
            chat_id=chat,
            session_id=session,
            message_sequence=sequence,
            raw_message=message,
            inventory=inventory,
            current_pair=current or {},
        )

    def consume(self, ticket, *, current=None, inventory=INVENTORY, chat="telegram:123", session="session-a"):
        return self.authorizer.consume_ticket(
            ticket=ticket,
            chat_id=chat,
            session_id=session,
            inventory=inventory,
            current_pair=current or {},
        )

    def test_state_keeps_ordered_public_inventory_but_never_oauth_tokens(self):
        opened = self.open()
        self.assertEqual([item["id"] for item in opened["accounts"]], ["act_100", "act_200"])
        state_text = self.state_path.read_text(encoding="utf-8")
        self.assertNotIn("never-store", state_text)
        stored = json.loads(state_text)
        intent = stored["intents"][opened["intent_id"]]
        self.assertEqual(intent["inventory_hash"], inventory_fingerprint(INVENTORY))
        self.assertEqual([item["ordinal"] for item in intent["inventory"]["pages"]], [1, 2])

    def test_initial_selection_rejects_partial_prose_and_requires_one_numeric_pair(self):
        opened = self.open()
        account_only = self.authorize(opened, "Usa la cuenta 2")
        self.assertEqual(account_only["status"], "rejected")
        self.assertEqual(account_only["reason"], "numeric_pair_required")
        self.assertNotIn("ticket", account_only)

        page_only = self.authorize(opened, "Y la página Odontóloga María Flores", sequence=12)
        self.assertEqual(page_only["status"], "rejected")
        self.assertEqual(page_only["reason"], "numeric_pair_required")
        self.assertNotIn("ticket", page_only)

        authorized = self.authorize(opened, "1, 2", sequence=13)
        self.assertEqual(authorized["status"], "authorized")
        self.assertEqual(
            authorized["selection"],
            {"ad_account_id": "act_200", "page_id": "1319759131214498"},
        )
        consumed = self.consume(authorized["ticket"])
        self.assertTrue(consumed["authorized"])
        self.assertEqual(consumed["selection"], authorized["selection"])

    def test_current_intent_api_authorizes_without_callers_carrying_private_state(self):
        opened = self.open()
        current = self.authorizer.current_intent(chat_id="telegram:123", session_id="session-a")
        self.assertEqual(current["intent_id"], opened["intent_id"])
        self.assertNotIn("inventory", current)
        self.assertNotIn("partial", current)
        result = self.authorizer.authorize_current_message(
            chat_id="telegram:123",
            session_id="session-a",
            message_sequence=11,
            raw_message="1, 2",
            inventory=INVENTORY,
            current_pair={},
        )
        self.assertEqual(result["status"], "authorized")
        self.assertIsNone(self.authorizer.current_intent(chat_id="telegram:123", session_id="session-a"))

    def test_unicode_typos_and_natural_names_require_numeric_pair(self):
        opened = self.open()
        result = self.authorize(
            opened,
            "Quiero la cuetna dos y la páguina Odontloga María Florez",
        )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "numeric_pair_required")
        self.assertNotIn("ticket", result)

    def test_scoped_numeric_prose_requires_bare_numeric_pair(self):
        opened = self.open()
        result = self.authorize(opened, "cuenta 2 y página 1")
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "numeric_pair_required")
        self.assertNotIn("ticket", result)

    def test_supported_numeric_pair_formats_use_page_then_ad_account_order(self):
        for message in ("1,2", "1, 2", "1 2"):
            with self.subTest(message=message):
                result = resolve_selection_message(message, INVENTORY)
                self.assertEqual(result["status"], "resolved")
                self.assertEqual(result["account"]["asset"]["id"], "act_200")
                self.assertEqual(result["page"]["asset"]["id"], "1319759131214498")
                self.assertEqual(result["account"]["evidence"], "canonical_numeric_pair")
                self.assertEqual(result["page"]["evidence"], "canonical_numeric_pair")

    def test_numeric_pair_rejects_extra_tokens_and_out_of_range_ordinals(self):
        opened = self.open()
        for sequence, message in enumerate(
            (
                "1",
                "uno dos",
                "página 1 cuenta 2",
                "1 y 2",
                "1 2 3",
                "1 2 listo",
                "1/2",
                "1.2",
                "-1, 2",
                "1, 2 ✅",
            ),
            start=11,
        ):
            with self.subTest(message=message):
                result = self.authorize(opened, message, sequence=sequence)
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(result["reason"], "numeric_pair_required")
                self.assertNotIn("ticket", result)

        out_of_range = self.authorize(opened, "3, 1", sequence=21)
        self.assertEqual(out_of_range["status"], "rejected")
        self.assertEqual(out_of_range["reason"], "numeric_pair_out_of_range")
        self.assertNotIn("ticket", out_of_range)

    def test_generic_delegation_never_authorizes(self):
        opened = self.open()
        result = self.authorize(opened, "Usa lo que veas, confío en ti")
        self.assertEqual(result, {
            "status": "rejected",
            "reason": "numeric_pair_required",
            "intent_id": opened["intent_id"],
            "expires_at": opened["expires_at"],
        })

    def test_duplicate_names_do_not_participate_in_authorization(self):
        inventory = {
            "accounts": [
                {"id": "act_1", "name": "Mi negocio"},
                {"id": "act_2", "name": "Mi negocio"},
            ],
            "pages": [{"id": "123456789", "name": "Página segura"}],
        }
        result = resolve_selection_message("usa la cuenta Mi negocio", inventory)
        self.assertEqual(result, {"status": "rejected", "reason": "numeric_pair_required"})

    def test_longest_explicit_name_still_requires_numeric_pair(self):
        inventory = {
            "accounts": [
                {"id": "act_1", "name": "Dorian"},
                {"id": "act_2", "name": "Dorian"},
                {"id": "act_8", "name": "Dorian Singularity"},
            ],
            "pages": [{"id": "page_1", "name": "Rodeo - Car Detailing"}],
        }
        result = resolve_selection_message(
            "Usa Dorian Singularity como cuenta y Rodeo como página",
            inventory,
        )
        self.assertEqual(result, {"status": "rejected", "reason": "numeric_pair_required"})

    def test_same_unscoped_name_across_account_and_page_requires_numeric_pair(self):
        inventory = {
            "accounts": [{"id": "act_1", "name": "Acme"}],
            "pages": [{"id": "123456789", "name": "Acme"}],
        }
        result = resolve_selection_message("Acme", inventory)
        self.assertEqual(result, {"status": "rejected", "reason": "numeric_pair_required"})

    def test_scoped_names_never_authorize_either_asset_type(self):
        inventory = {
            "accounts": [{"id": "act_8", "name": "Dorian Singularity"}],
            "pages": [
                {"id": "page_1", "name": "Rodeo - Car Detailing"},
                {"id": "page_8", "name": "Dorian Singularity"},
            ],
        }
        result = resolve_selection_message(
            "Quiero usar la cuenta Dorian Singularity y la página Rodeo - Car Detailing",
            inventory,
        )
        self.assertEqual(result, {"status": "rejected", "reason": "numeric_pair_required"})

        reversed_order = resolve_selection_message(
            "Usa Dorian Singularity como cuenta y Rodeo como página",
            inventory,
        )
        self.assertEqual(reversed_order, {"status": "rejected", "reason": "numeric_pair_required"})

    def test_switch_rejects_scoped_partial_and_requires_full_numeric_pair(self):
        current = {"ad_account_id": "act_100", "page_id": "1319759131214498"}
        opened = self.open(current=current, mode="switch")
        rejected = self.authorize(opened, "Cambia la cuenta a la 2", current=current)
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["reason"], "numeric_pair_required")
        self.assertNotIn("ticket", rejected)

        result = self.authorize(opened, "1, 2", sequence=12, current=current)
        self.assertEqual(result["status"], "authorized")
        self.assertEqual(result["selection"], {"ad_account_id": "act_200", "page_id": current["page_id"]})

    def test_unscoped_switch_name_requires_numeric_pair(self):
        current = {"ad_account_id": "act_100", "page_id": "1319759131214498"}
        opened = self.open(current=current, mode="switch")
        result = self.authorize(opened, "DOrian2", current=current)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "numeric_pair_required")
        self.assertNotIn("ticket", result)

    def test_ticket_rejects_cross_chat_and_cross_session(self):
        opened = self.open()
        result = self.authorize(opened, "1, 2")
        with self.assertRaises(SelectionBindingMismatch):
            self.consume(result["ticket"], chat="telegram:other")
        with self.assertRaises(SelectionBindingMismatch):
            self.consume(result["ticket"], session="session-other")
        self.assertTrue(self.consume(result["ticket"])["authorized"])

    def test_ticket_is_one_use(self):
        opened = self.open()
        result = self.authorize(opened, "1, 2")
        self.assertNotIn(result["ticket"], self.state_path.read_text(encoding="utf-8"))
        self.consume(result["ticket"])
        with self.assertRaisesRegex(SelectionTicketInvalid, "already consumed"):
            self.consume(result["ticket"])

    def test_ticket_transaction_keeps_capability_retryable_on_downstream_failure(self):
        opened = self.open()
        result = self.authorize(opened, "1, 2")
        with self.assertRaisesRegex(RuntimeError, "injected persistence failure"):
            with self.authorizer.ticket_transaction(
                ticket=result["ticket"],
                chat_id="telegram:123",
                session_id="session-a",
                inventory=INVENTORY,
                current_pair={},
            ) as authorized:
                self.assertEqual(authorized["selection"], result["selection"])
                raise RuntimeError("injected persistence failure")

        # The exact same server-issued capability remains valid because the
        # durable operation did not finish.
        consumed = self.consume(result["ticket"])
        self.assertEqual(consumed["selection"], result["selection"])
        with self.assertRaisesRegex(SelectionTicketInvalid, "already consumed"):
            self.consume(result["ticket"])

    def test_intent_and_ticket_expire(self):
        opened = self.open()
        self.clock.advance(61)
        with self.assertRaises(SelectionIntentNotFound):
            self.authorize(opened, "1, 2")

        opened = self.open(sequence=20)
        result = self.authorize(opened, "1, 2", sequence=21)
        self.clock.advance(61)
        with self.assertRaisesRegex(SelectionTicketInvalid, "invalid or expired"):
            self.consume(result["ticket"])

    def test_inventory_order_and_current_pair_are_bound(self):
        current = {"ad_account_id": "act_100", "page_id": "1319759131214498"}
        opened = self.open(current=current, mode="switch")
        reordered = {
            "accounts": list(reversed(INVENTORY["accounts"])),
            "pages": INVENTORY["pages"],
        }
        with self.assertRaisesRegex(SelectionBindingMismatch, "inventory changed"):
            self.authorize(opened, "1, 2", current=current, inventory=reordered)
        changed = {"ad_account_id": "act_200", "page_id": current["page_id"]}
        with self.assertRaisesRegex(SelectionBindingMismatch, "workspace changed"):
            self.authorize(opened, "1, 2", current=changed)

    def test_ticket_rechecks_inventory_and_old_pair_before_execution(self):
        current = {"ad_account_id": "act_100", "page_id": "1319759131214498"}
        opened = self.open(current=current, mode="switch")
        result = self.authorize(opened, "1, 2", current=current)
        changed_inventory = {
            "accounts": INVENTORY["accounts"] + [{"id": "act_300", "name": "Nueva"}],
            "pages": INVENTORY["pages"],
        }
        with self.assertRaisesRegex(SelectionBindingMismatch, "inventory changed"):
            self.consume(result["ticket"], current=current, inventory=changed_inventory)
        with self.assertRaisesRegex(SelectionBindingMismatch, "workspace changed"):
            self.consume(result["ticket"], current={"ad_account_id": "act_200", "page_id": current["page_id"]})
        self.assertTrue(self.consume(result["ticket"], current=current)["authorized"])

    def test_stale_inbound_sequence_is_rejected(self):
        opened = self.open(sequence=10)
        with self.assertRaisesRegex(SelectionBindingMismatch, "stale"):
            self.authorize(opened, "1, 2", sequence=10)

    def test_opening_new_prompt_revokes_an_older_unconsumed_ticket(self):
        opened = self.open()
        result = self.authorize(opened, "1, 2")
        self.open(sequence=20)
        with self.assertRaises(SelectionTicketInvalid):
            self.consume(result["ticket"])

    def test_clear_scope_revokes_pending_intents_and_tickets(self):
        opened = self.open()
        result = self.authorize(opened, "1, 2")
        other = self.authorizer.open_intent(
            chat_id="telegram:other",
            session_id="other-session",
            inventory=INVENTORY,
            current_pair={},
            opened_after_sequence=1,
        )
        removed = self.authorizer.clear(chat_id="telegram:123", session_id="session-a")
        self.assertEqual(removed["tickets"], 1)
        with self.assertRaises(SelectionTicketInvalid):
            self.consume(result["ticket"])
        other_result = self.authorizer.authorize_message(
            intent_id=other["intent_id"],
            chat_id="telegram:other",
            session_id="other-session",
            message_sequence=2,
            raw_message="1, 1",
            inventory=INVENTORY,
            current_pair={},
        )
        self.assertEqual(other_result["status"], "authorized")


if __name__ == "__main__":
    unittest.main()
