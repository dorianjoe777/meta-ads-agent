from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
import ast
import types
from unittest.mock import Mock, patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hosted_oauth_tenant_turn", ROOT / "deploy" / "contabo" / "tenant_turn.py"
)
tenant_turn = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(tenant_turn)


class HostedOAuthGateTests(unittest.TestCase):
    def run_gate(self, dashboard, message="listo"):
        tree = ast.parse(tenant_turn.INNER_SCRIPT)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "hosted_meta_oauth_gate")
        namespace = {}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "<gate>", "exec"), namespace)
        modules = {
            "admira_tool_bridge": types.SimpleNamespace(load_dashboard=lambda: dashboard),
            "hermes_bridge": types.SimpleNamespace(_record_bridge_trusted_buyer_turn=lambda payload: {**payload, "message_sequence": 42}),
        }
        with patch.dict(sys.modules, modules):
            return namespace["hosted_meta_oauth_gate"]({"message": message, "language": "es", "chat_id": "123"})

    def dashboard(self, authorization="waiting_for_buyer_selection"):
        dashboard = Mock()
        dashboard.social_oauth_status.return_value = {"connected": True}
        dashboard.social_oauth_workspaces_for_text_selection.return_value = {
            "connected": True, "selection_authorization": {"status": authorization}}
        dashboard._meta_oauth_selection_inventory.return_value = {
            "pages": [{"id": "p"+str(i), "name": "Page "+str(i), "access_token": "private-token"} for i in range(1, 62)],
            "accounts": [{"id": "act_"+str(i), "name": "Account "+str(i)} for i in range(1, 62)]}
        return dashboard

    def test_connected_done_immediately_lists_every_asset_without_model(self):
        dashboard = self.dashboard()
        result = self.run_gate(dashboard)
        self.assertTrue(result["ok"])
        self.assertIn("61. Page 61", result["reply"])
        self.assertIn("61. Account 61", result["reply"])
        self.assertLess(result["reply"].index("PÁGINAS"), result["reply"].index("CUENTAS"))
        self.assertIn("separados por coma", result["reply"])
        self.assertNotIn("private-token", result["reply"])
        dashboard.social_oauth_select.assert_not_called()

    def test_invalid_or_partial_choice_repeats_lists(self):
        for message in ("listo", "1", "elige tu", "mi presupuesto es 1, 2"):
            dashboard = self.dashboard()
            self.assertIn("PÁGINAS", self.run_gate(dashboard, message)["reply"])
            dashboard.social_oauth_select.assert_not_called()

    def test_authorized_choice_persists_before_interview(self):
        dashboard = self.dashboard("authorized_pending_persistence")
        dashboard.social_oauth_select.return_value = {"selected": True, "verified_persisted": True}
        self.assertIsNone(self.run_gate(dashboard, "1, 2"))
        dashboard.social_oauth_select.assert_called_once_with({})

    def test_failed_selection_does_not_continue_interview_or_reconnect(self):
        dashboard = self.dashboard("authorized_pending_persistence")
        dashboard.social_oauth_select.return_value = {"selected": True, "verified_persisted": False}
        self.assertIn("reintentarlo", self.run_gate(dashboard, "1, 2")["reply"])
        dashboard.social_oauth_start.assert_not_called()

    def test_existing_selection_continues_without_reprompt(self):
        dashboard = self.dashboard()
        dashboard.social_oauth_status.return_value = {
            "connected": True, "active_page_id": "p1", "active_ad_account_id": "act_1"}
        self.assertIsNone(self.run_gate(dashboard))
        dashboard.social_oauth_workspaces_for_text_selection.assert_not_called()

    def test_first_hosted_turn_returns_the_broker_url_without_calling_the_model(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "admira_tool_bridge.py").write_text(textwrap.dedent("""
                class Dashboard:
                    def social_oauth_status(self):
                        return {"connected": False}
                    def social_oauth_start(self, payload):
                        assert payload["telegram_chat_id"] == "123"
                        return {"authorization_url": "https://www.facebook.com/v26.0/dialog/oauth?state=one-time"}
                def load_dashboard():
                    return Dashboard()
            """), encoding="utf-8")
            (root / "hermes_bridge.py").write_text("def chat(*_args, **_kwargs):\n    raise AssertionError('model must not run before OAuth')\n", encoding="utf-8")
            (root / "product_config.py").write_text("def load_config():\n    return object()\n", encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "-c", tenant_turn.INNER_SCRIPT.replace(
                    'sys.path.insert(0, "/app/src")', "sys.path.insert(0, " + repr(str(root)) + ")")],
                cwd=root,
                input=json.dumps({"message": "hola", "chat_id": "123", "user_id": "456", "language": "es"}),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=10,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertTrue(result["ok"])
        self.assertIn("https://www.facebook.com/v26.0/dialog/oauth?state=one-time", result["reply"])
        self.assertIn("Antes de continuar", result["reply"])


if __name__ == "__main__":
    unittest.main()
