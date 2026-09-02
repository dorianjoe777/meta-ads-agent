import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_oauth_session import mirror_back_to_root, prepare_hermes_oauth


class CodexOAuthSessionTests(unittest.TestCase):
    def test_prepare_uses_root_slot_and_preserves_provider_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            auth = home / "auth.json"
            auth.write_text(json.dumps({
                "tokens": {"access_token": "root-access", "refresh_token": "root-refresh"},
                "last_refresh": "root-refresh-time",
                "providers": {
                    "openai-codex": {"account_id": "account-1", "other": "keep"},
                    "otherprovider": {"tokens": {"access_token": "other", "refresh_token": "other"}},
                },
            }))
            auth.chmod(0o600)
            with patch.dict(os.environ, {"HERMES_HOME": str(home)}, clear=False):
                self.assertEqual(prepare_hermes_oauth(), auth)
                state = json.loads(auth.read_text())
                mode = stat.S_IMODE(auth.stat().st_mode)

        self.assertEqual(state["providers"]["openai-codex"]["tokens"], {
            "access_token": "root-access", "refresh_token": "root-refresh",
        })
        self.assertEqual(state["providers"]["openai-codex"]["account_id"], "account-1")
        self.assertEqual(state["providers"]["openai-codex"]["other"], "keep")
        self.assertIn("otherprovider", state["providers"])
        self.assertEqual(mode, 0o600)

    def test_mirror_refreshes_expired_root_tokens_and_keeps_other_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            auth = Path(directory) / "auth.json"
            auth.write_text(json.dumps({
                "tokens": {"access_token": "expired", "refresh_token": "old-refresh"},
                "last_refresh": "old-time",
                "providers": {
                    "openai-codex": {
                        "tokens": {"access_token": "fresh", "refresh_token": "new-refresh"},
                        "last_refresh": "new-time",
                        "account_id": "account-1",
                    },
                    "otherprovider": {"setting": True},
                },
            }))
            auth.chmod(0o600)
            mirror_back_to_root(auth)
            state = json.loads(auth.read_text())
            mode = stat.S_IMODE(auth.stat().st_mode)

        self.assertEqual(state["tokens"], {"access_token": "fresh", "refresh_token": "new-refresh"})
        self.assertEqual(state["last_refresh"], "new-time")
        self.assertEqual(state["providers"]["openai-codex"]["account_id"], "account-1")
        self.assertEqual(state["providers"]["otherprovider"], {"setting": True})
        self.assertEqual(mode, 0o600)

    def test_malformed_auth_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "auth.json").write_text("not-json")
            with patch.dict(os.environ, {"HERMES_HOME": str(home)}, clear=False):
                with self.assertRaisesRegex(RuntimeError, "^provider_auth$"):
                    prepare_hermes_oauth()


if __name__ == "__main__":
    unittest.main()
