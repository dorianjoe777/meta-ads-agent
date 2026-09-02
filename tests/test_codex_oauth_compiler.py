"""Regression tests for the direct Hermes/Codex OAuth campaign compiler."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import codex_oauth_compiler as compiler
import codex_oauth_chat as chat


class CodexOAuthCompilerTests(unittest.TestCase):
    def test_runs_hermes_python_bridge_with_private_profile_not_codex_cli(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"ok":true,"compiled":{"ready":false,"missing_fields":[],"payload_json":"{}"}}\n',
            stderr="",
        )
        with mock.patch.object(compiler.subprocess, "run", return_value=completed) as run:
            result = compiler.compile_with_codex_oauth(
                "approved campaign brief",
                {"type": "object"},
                model="gpt-5.6-terra",
                timeout=20,
                hermes_home="/private/oauth-slot",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "openai-codex-oauth")
        command = run.call_args.args[0]
        self.assertEqual(command[:2], [sys.executable, "-c"])
        self.assertNotEqual(command[0], "codex")
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["HERMES_HOME"], "/private/oauth-slot")
        self.assertEqual(environment["CODEX_HOME"], "/private/oauth-slot")

    def test_provider_diagnostics_cannot_escape_bridge_result(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout='{"ok":false,"failure_category":"provider_auth","diagnostic":"secret token"}\n',
            stderr="secret token",
        )
        with mock.patch.object(compiler.subprocess, "run", return_value=completed):
            result = compiler.compile_with_codex_oauth(
                "approved campaign brief",
                {"type": "object"},
                model="gpt-5.6-terra",
                timeout=20,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["failure_category"], "provider_auth")
        self.assertNotIn("secret token", repr(result))
        self.assertNotIn("diagnostic", result)

    def test_malformed_bridge_output_fails_closed(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="not-json", stderr="")
        with mock.patch.object(compiler.subprocess, "run", return_value=completed):
            result = compiler.compile_with_codex_oauth(
                "approved campaign brief",
                {"type": "object"},
                model="gpt-5.6-terra",
                timeout=20,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "campaign_compiler_provider_failed")
        self.assertNotIn("not-json", repr(result))

    def test_chat_uses_the_same_hermes_oauth_transport_not_codex_cli(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"ok":true,"finish_reason":"stop","message":{"role":"assistant","content":"Listo","tool_calls":[]}}\n',
            stderr="",
        )
        with mock.patch.object(chat.subprocess, "run", return_value=completed) as run:
            result = chat.chat_with_codex_oauth(
                [{"role": "user", "content": "Hola"}],
                tools=[], model="gpt-5.6-terra", timeout=20,
                hermes_home="/private/oauth-slot",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["message"]["content"], "Listo")
        command = run.call_args.args[0]
        self.assertEqual(command[:2], [sys.executable, "-c"])
        self.assertNotEqual(command[0], "codex")
        self.assertEqual(run.call_args.kwargs["env"]["HERMES_HOME"], "/private/oauth-slot")

    def test_chat_diagnostics_cannot_escape_bridge_result(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout='{"ok":false,"failure_category":"provider_auth","diagnostic":"secret token"}\n',
            stderr="secret token",
        )
        with mock.patch.object(chat.subprocess, "run", return_value=completed):
            result = chat.chat_with_codex_oauth(
                [{"role": "user", "content": "Hola"}],
                tools=[], model="gpt-5.6-terra", timeout=20,
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure_category"], "provider_auth")
        self.assertNotIn("secret token", repr(result))


if __name__ == "__main__":
    unittest.main()
