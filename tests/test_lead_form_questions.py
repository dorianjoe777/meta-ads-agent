import json
import sys
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from social_flow_client import SocialFlowClient


class LeadFormQuestionNormalizationTests(unittest.TestCase):
    def test_unwraps_mcp_item_envelope_and_drops_unknown_keys(self):
        questions = SocialFlowClient.normalize_lead_form_questions([
            {"item": {"type": "CUSTOM", "label": "¿Qué servicio necesitas?", "key": "service"}},
            {"item": {"type": "PHONE"}, "required": True, "internal_note": "do not send"},
        ])

        self.assertEqual(
            questions,
            [
                {"type": "CUSTOM", "label": "¿Qué servicio necesitas?", "key": "service"},
                {"type": "PHONE"},
            ],
        )
        wire = json.dumps(questions, ensure_ascii=False)
        self.assertNotIn('"item"', wire)
        self.assertNotIn("internal_note", wire)

    def test_custom_question_gets_canonical_key_and_prefilled_question_stays_minimal(self):
        questions = SocialFlowClient.normalize_lead_form_questions([
            {"item": {"type": "custom", "question": "¿Cuál es tu presupuesto?", "options": ["A", "B"]}},
            {"type": "full_name", "label": "Nombre que no debe cambiar la field question"},
        ])

        self.assertEqual(questions[0]["type"], "CUSTOM")
        self.assertEqual(questions[0]["key"], "cual_es_tu_presupuesto")
        self.assertEqual(questions[0]["label"], "¿Cuál es tu presupuesto?")
        self.assertEqual(questions[0]["options"], ["A", "B"])
        self.assertEqual(questions[1], {"type": "FULL_NAME", "label": "Nombre que no debe cambiar la field question"})

    def test_create_lead_form_wire_payload_never_contains_item_key(self):
        class Response:
            status = 200
            headers = {}

            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(self.body).encode("utf-8")

        requests = []

        def fake_urlopen(request, timeout=90):
            requests.append(request)
            if "/me/accounts" in request.full_url:
                return Response({"data": [{"id": "page_1", "name": "Test Page", "access_token": "page-token"}]})
            if request.data is not None:
                fields = urllib.parse.parse_qs(request.data.decode("utf-8"))
                questions = json.loads(fields["questions"][0])
                assert all("item" not in question for question in questions)
                assert questions[0] == {"type": "CUSTOM", "label": "¿Qué necesitas?", "key": "que_necesitas"}
                return Response({"id": "form_123"})
            return Response({"data": [{"id": "form_existing"}]})

        original_urlopen = urllib.request.urlopen
        urllib.request.urlopen = fake_urlopen
        try:
            config = SimpleNamespace(
                mode="live",
                live=True,
                live_actions_enabled=True,
                meta_connector="graph_api",
                meta_access_token="ads-token",
                meta_publishing_access_token="",
                meta_graph_api_version="v24.0",
                ad_account_id="act_999",
            )
            result = SocialFlowClient(config).create_lead_form(
                "page_1",
                "Formulario de prueba",
                questions=[{"item": {"type": "CUSTOM", "question": "¿Qué necesitas?"}, "required": True}],
                privacy_policy_url="https://example.com/privacy",
                approved=True,
            )
            self.assertEqual(json.loads(result["stdout"])["lead_gen_form_id"], "form_123")
        finally:
            urllib.request.urlopen = original_urlopen


if __name__ == "__main__":
    unittest.main()
