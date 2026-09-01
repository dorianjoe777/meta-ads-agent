from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hosted_oauth_tenant_turn", ROOT / "deploy" / "contabo" / "tenant_turn.py"
)
tenant_turn = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(tenant_turn)


class HostedOAuthGateTests(unittest.TestCase):
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
                [sys.executable, "-c", tenant_turn.INNER_SCRIPT],
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
