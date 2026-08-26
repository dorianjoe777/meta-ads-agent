import json
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import campaign_editing as editing
import admira_hermes_runtime_patch as routing
import daily_agent


CAMPAIGNS = [
    {"id": "120000000000001", "name": "Abogados Cartagena WhatsApp", "status": "PAUSED", "account_id": "77"},
    {"id": "120000000000002", "name": "Abogados Miami WhatsApp", "status": "PAUSED", "account_id": "77"},
]
ADSETS = [
    {"id": "220000000000001", "campaign_id": "120000000000001", "name": "Cartagena empresarios"},
    {"id": "220000000000002", "campaign_id": "120000000000002", "name": "Miami empresarios"},
]


class FakeConfig:
    ad_account_id = "77"
    meta_access_token = "test-token"


class FakeClient:
    def __init__(self, entities):
        self.config = FakeConfig()
        self.entities = deepcopy(entities)
        self.posts = []

    def get_graph(self, endpoint, params=None, access_token=""):
        body = deepcopy(self.entities.get(str(endpoint), {}))
        return {"ok": bool(body), "body": body, "status": 200 if body else 404}

    def post_graph_form(self, endpoint, fields):
        payload = deepcopy(fields)
        payload.pop("access_token", None)
        self.posts.append((str(endpoint), payload))
        current = self.entities[str(endpoint)]
        current.update(payload)
        return {"ok": True, "body": {"success": True}, "status": 200}


class FakeCreativeClient(FakeClient):
    def __init__(self, entities, *, tamper_readback=False):
        super().__init__(entities)
        self.created_specs = {}
        self.tamper_readback = tamper_readback

    def create_creative(self, account_id, name, page_id, *args, object_story_spec=None, **kwargs):
        creative_id = "440000000000002"
        self.created_specs[creative_id] = deepcopy(object_story_spec or {})
        return {"ok": True, "status": 200, "stdout": json.dumps({"id": creative_id})}

    def post_graph_form(self, endpoint, fields):
        result = super().post_graph_form(endpoint, fields)
        creative = fields.get("creative") if isinstance(fields.get("creative"), dict) else {}
        creative_id = str(creative.get("creative_id") or "")
        if creative_id:
            spec = deepcopy(self.created_specs[creative_id])
            if self.tamper_readback:
                container = spec.get("link_data") if isinstance(spec.get("link_data"), dict) else {}
                container["message"] = "Texto distinto devuelto por Meta"
            self.entities[str(endpoint)]["creative"] = {
                "id": creative_id,
                "name": "Replacement creative",
                "object_story_spec": spec,
            }
        return result


class CampaignReferenceTests(unittest.TestCase):
    def test_current_message_unique_city_selects_different_campaign(self):
        result = editing.resolve_campaign_reference(
            "en la de Miami usa solo Instagram Stories",
            CAMPAIGNS,
            ADSETS,
            active_campaign_id="120000000000001",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["campaign_id"], "120000000000002")

    def test_pronoun_continues_active_campaign(self):
        result = editing.resolve_campaign_reference(
            "en esa sube el presupuesto",
            CAMPAIGNS,
            ADSETS,
            active_campaign_id="120000000000001",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["campaign_id"], "120000000000001")
        self.assertEqual(result["matched_by"], "conversation_context")

    def test_ambiguous_family_name_is_never_guessed(self):
        result = editing.resolve_campaign_reference("la campaña de abogados", CAMPAIGNS, ADSETS)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "ambiguous_campaign")

    def test_draft_paths_are_campaign_scoped(self):
        first = editing._draft_path("chat-1", "77", "120000000000001")
        second = editing._draft_path("chat-1", "77", "120000000000002")
        third = editing._draft_path("chat-1", "77", "120000000000003")
        self.assertNotEqual(first, second)
        self.assertEqual(len({first, second, third}), 3)
        self.assertEqual(first.name, "draft.json")

    def test_reset_discards_only_this_conversations_transient_edit_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "campaign-edit-workflows"
            pending_file = Path(directory) / "pending.json"
            with mock.patch.object(editing, "EDIT_ROOT", root), mock.patch.object(editing, "EDIT_INDEX_FILE", root / "conversation-index.json"), mock.patch.object(editing, "PENDING_FILE", pending_file):
                mine = editing._draft_path("chat-1", "77", CAMPAIGNS[0]["id"])
                other = editing._draft_path("chat-2", "77", CAMPAIGNS[1]["id"])
                editing._atomic(mine, {"conversation_key": "chat-1", "campaign_id": CAMPAIGNS[0]["id"]})
                editing._atomic(other, {"conversation_key": "chat-2", "campaign_id": CAMPAIGNS[1]["id"]})
                editing._atomic(root / "conversation-index.json", {
                    editing._safe_key("chat-1:77"): {"active_campaign_id": CAMPAIGNS[0]["id"]},
                    editing._safe_key("chat-2:77"): {"active_campaign_id": CAMPAIGNS[1]["id"]},
                })
                editing._atomic(pending_file, [
                    {"id": "approval-mine", "type": "campaign_edit", "status": "pending", "payload": {"conversation_key": "chat-1"}},
                    {"id": "approval-other", "type": "campaign_edit", "status": "pending", "payload": {"conversation_key": "chat-2"}},
                ])

                result = editing.reset_conversation_edit_context("chat-1")

                self.assertEqual(result["removed_drafts"], 1)
                self.assertFalse(mine.exists())
                self.assertTrue(other.exists())
                index = editing._load_index()
                self.assertNotIn(editing._safe_key("chat-1:77"), index)
                self.assertIn(editing._safe_key("chat-2:77"), index)
                pending = editing.read_json(pending_file, [])
                self.assertEqual(pending[0]["status"], "cancelled_by_conversation_reset")
                self.assertEqual(pending[1]["status"], "pending")


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            "campaign": CAMPAIGNS[0],
            "ad_sets": [ADSETS[0]],
            "ads": [{"id": "320000000000001", "campaign_id": CAMPAIGNS[0]["id"], "name": "Anuncio uno"}],
        }

    def test_unknown_entity_id_is_rejected(self):
        operations, errors = editing._validate_operations(
            {"operations": [{"entity_type": "adset", "entity_id": "999999999999999", "changes": {"age_min": 25}}]},
            self.snapshot,
        )
        self.assertIsNone(operations)
        self.assertIn("operations[0].entity_id", errors)

    def test_unknown_field_is_rejected(self):
        operations, errors = editing._validate_operations(
            {"operations": [{"entity_type": "campaign", "entity_id": CAMPAIGNS[0]["id"], "changes": {"objective": "OUTCOME_SALES"}}]},
            self.snapshot,
        )
        self.assertIsNone(operations)
        self.assertIn("operations[0].changes.objective", errors)


class ApprovalLifecycleTests(unittest.TestCase):
    def test_rejecting_campaign_edit_marks_its_draft_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            pending_file = Path(directory) / "pending.json"
            pending_file.write_text(json.dumps([{
                "id": "approval-edit-1",
                "type": "campaign_edit",
                "status": "pending",
                "payload": {"draft_path": str(Path(directory) / "draft.json")},
            }]), encoding="utf-8")
            with mock.patch.object(daily_agent, "PENDING_FILE", pending_file), \
                 mock.patch.object(daily_agent, "log_action"), \
                 mock.patch.object(daily_agent, "mark_draft_status") as mark_status:
                rejected = daily_agent.reject("approval-edit-1", "Buyer rejected")
            self.assertEqual(len(rejected), 1)
            mark_status.assert_called_once()
            self.assertEqual(mark_status.call_args.args[1], "rejected")


class RoutingTests(unittest.TestCase):
    def test_paused_creation_is_not_misread_as_usa_edit(self):
        messages = [{"role": "user", "content": "Crea la campaña pausada con creativos aprobados."}]
        self.assertFalse(routing._admira_campaign_edit_requested(messages))

    def test_explicit_edit_routes_to_campaign_editing(self):
        messages = [{"role": "user", "content": "Edita la campaña de Miami y usa solo Instagram Stories."}]
        self.assertTrue(routing._admira_campaign_edit_requested(messages))

    def test_followup_scope_does_not_require_transition_words(self):
        previous = os.environ.get("ADMIRA_PRODUCT_ROOT")
        try:
            with tempfile.TemporaryDirectory() as directory:
                index = Path(directory) / "dashboard/data/campaign-edit-workflows/conversation-index.json"
                index.parent.mkdir(parents=True)
                index.write_text(json.dumps({"chat": {"active_campaign_id": "1"}}), encoding="utf-8")
                os.environ["ADMIRA_PRODUCT_ROOT"] = directory
                messages = [{"role": "user", "content": "En la de Miami usa solo Instagram Stories."}]
                self.assertTrue(routing._admira_campaign_edit_requested(messages))
        finally:
            if previous is None:
                os.environ.pop("ADMIRA_PRODUCT_ROOT", None)
            else:
                os.environ["ADMIRA_PRODUCT_ROOT"] = previous


class ExecutionTests(unittest.TestCase):
    def test_ad_read_does_not_request_budget_fields(self):
        class RecordingClient:
            params = None

            def get_graph(self, endpoint, params=None, access_token=""):
                self.params = params
                return {"ok": True, "body": {"id": endpoint, "status": "PAUSED"}, "status": 200}

        client = RecordingClient()
        editing._read_entity(client, "ad", "320000000000001")
        fields = str((client.params or {}).get("fields") or "")
        self.assertIn("creative", fields)
        self.assertNotIn("daily_budget", fields)
        self.assertNotIn("lifetime_budget", fields)

    def test_exact_diff_is_applied_and_read_back(self):
        entity_id = CAMPAIGNS[0]["id"]
        current = {"id": entity_id, "name": "Old", "status": "PAUSED", "daily_budget": "500"}
        client = FakeClient({entity_id: current})
        payload = {
            "campaign_id": entity_id,
            "account_id": "77",
            "account_currency": "USD",
            "operations": [{
                "entity_type": "campaign",
                "entity_id": entity_id,
                "changes": {"name": "New", "daily_budget": 12.0, "_daily_budget_api": 1200},
            }],
            # Dashboard snapshots use major currency units while Graph reads
            # return minor units and are normalized by _read_entity.
            "preconditions": {entity_id: editing._fingerprint({**current, "daily_budget": 5.0})},
        }
        result = editing.execute_campaign_edit(payload, client)
        self.assertTrue(result["ok"])
        self.assertTrue(result["verified"])
        self.assertEqual(client.entities[entity_id]["name"], "New")
        self.assertEqual(client.entities[entity_id]["daily_budget"], 1200)

    def test_primary_text_edit_requires_graph_200_and_exact_readback(self):
        entity_id = "320000000000001"
        current = {
            "id": entity_id,
            "name": "Anuncio Full Detail",
            "status": "PAUSED",
            "creative": {
                "id": "440000000000001",
                "name": "Original creative",
                "object_story_spec": {
                    "page_id": "1201206426419368",
                    "link_data": {"message": "Texto anterior"},
                },
            },
        }
        client = FakeCreativeClient({entity_id: current})
        _result, live = editing._read_entity(client, "ad", entity_id)
        requested = "Nuevo texto exacto aprobado por el cliente."
        result = editing.execute_campaign_edit({
            "campaign_id": CAMPAIGNS[0]["id"],
            "account_id": "77",
            "operations": [{
                "entity_type": "ad",
                "entity_id": entity_id,
                "changes": {"primary_text": requested},
            }],
            "preconditions": {entity_id: editing._fingerprint(live)},
        }, client)

        self.assertTrue(result["ok"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["verification"], [{
            "target_id": entity_id,
            "ok": True,
            "http_status": 200,
        }])
        self.assertEqual(
            client.entities[entity_id]["creative"]["object_story_spec"]["link_data"]["message"],
            requested,
        )

    def test_primary_text_edit_rejects_graph_200_with_wrong_value(self):
        entity_id = "320000000000001"
        current = {
            "id": entity_id,
            "name": "Anuncio Full Detail",
            "status": "PAUSED",
            "creative": {
                "id": "440000000000001",
                "name": "Original creative",
                "object_story_spec": {
                    "page_id": "1201206426419368",
                    "link_data": {"message": "Texto anterior"},
                },
            },
        }
        client = FakeCreativeClient({entity_id: current}, tamper_readback=True)
        _result, live = editing._read_entity(client, "ad", entity_id)
        result = editing.execute_campaign_edit({
            "campaign_id": CAMPAIGNS[0]["id"],
            "account_id": "77",
            "operations": [{
                "entity_type": "ad",
                "entity_id": entity_id,
                "changes": {"primary_text": "Nuevo texto exacto aprobado por el cliente."},
            }],
            "preconditions": {entity_id: editing._fingerprint(live)},
        }, client)

        self.assertFalse(result["ok"])
        self.assertFalse(result["verified"])
        self.assertIn("creative.primary_text", result["verification"][0]["mismatches"])

    def test_edit_rejects_non_2xx_post_even_when_client_sets_ok_true(self):
        class ContradictoryClient(FakeClient):
            def post_graph_form(self, endpoint, fields):
                result = super().post_graph_form(endpoint, fields)
                result["ok"] = True
                result["status"] = 500
                return result

        entity_id = CAMPAIGNS[0]["id"]
        current = {"id": entity_id, "name": "Old", "status": "PAUSED"}
        client = ContradictoryClient({entity_id: current})
        _result, live = editing._read_entity(client, "campaign", entity_id)
        result = editing.execute_campaign_edit({
            "campaign_id": entity_id,
            "account_id": "77",
            "operations": [{
                "entity_type": "campaign",
                "entity_id": entity_id,
                "changes": {"name": "New"},
            }],
            "preconditions": {entity_id: editing._fingerprint(live)},
        }, client)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "campaign_edit_graph_update_failed")

    def test_stale_snapshot_blocks_before_write(self):
        entity_id = CAMPAIGNS[0]["id"]
        client = FakeClient({entity_id: {"id": entity_id, "name": "Changed elsewhere", "status": "PAUSED"}})
        result = editing.execute_campaign_edit({
            "campaign_id": entity_id,
            "account_id": "77",
            "operations": [{"entity_type": "campaign", "entity_id": entity_id, "changes": {"name": "New"}}],
            "preconditions": {entity_id: editing._fingerprint({"id": entity_id, "name": "Old", "status": "PAUSED"})},
        }, client)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "campaign_edit_stale_snapshot")
        self.assertEqual(client.posts, [])

    def test_activation_cannot_hide_inside_edit(self):
        entity_id = "320000000000001"
        current = {"id": entity_id, "name": "Ad", "status": "PAUSED", "creative": {"id": "44"}}
        client = FakeClient({entity_id: current})
        result = editing.execute_campaign_edit({
            "campaign_id": CAMPAIGNS[0]["id"],
            "account_id": "77",
            "operations": [{"entity_type": "ad", "entity_id": entity_id, "changes": {"status": "ACTIVE"}}],
            "preconditions": {entity_id: editing._fingerprint(current)},
        }, client)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "activation_requires_separate_approval")
        self.assertEqual(client.posts, [])


if __name__ == "__main__":
    unittest.main()
