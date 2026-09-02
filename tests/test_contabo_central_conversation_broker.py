from __future__ import annotations

import json
import time
import unittest

from deploy.contabo.central_conversation_broker import (
    ConversationBroker,
    MODEL,
    PURPOSE,
    sign_request,
)


class CentralConversationBrokerTests(unittest.TestCase):
    def setUp(self):
        self.key = b"k" * 32
        self.calls = []

        def provider(messages, *, tools, tool_choice, timeout):
            self.calls.append((messages, tools, tool_choice, timeout))
            return {
                "ok": True,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "Listo.", "tool_calls": []},
            }

        self.broker = ConversationBroker(
            {"tenant-one": self.key},
            lambda tenant, purpose: "central_sponsored",
            provider,
            freshness_seconds=30,
        )

    def envelope(self, *, nonce="a" * 32, messages=None, tools=None, tool_choice=None):
        return sign_request(self.key, {
            "tenant_id": "tenant-one",
            "request_id": "conversation-001",
            "purpose": PURPOSE,
            "messages": messages or [{"role": "user", "content": "Hola"}],
            "tools": tools or [],
            "tool_choice": tool_choice,
            "timeout_seconds": 10,
        }, timestamp=int(time.time()), nonce=nonce)

    def test_signed_request_returns_only_normalized_model_response(self):
        result = self.broker.submit(self.envelope())
        self.assertTrue(result["ok"])
        self.assertEqual(result["model"], MODEL)
        self.assertEqual(result["message"], {"role": "assistant", "content": "Listo.", "tool_calls": []})
        self.assertEqual(self.calls[0][0], [{"role": "user", "content": "Hola"}])
        self.assertNotIn("account_id", result)

    def test_replay_bad_signature_and_non_text_input_fail_closed(self):
        first = self.envelope(nonce="b" * 32)
        self.assertTrue(self.broker.submit(first)["ok"])
        self.assertEqual(self.broker.submit(first)["error_code"], "replayed_request")
        tampered = self.envelope(nonce="c" * 32)
        tampered["signature"] = "0" * 64
        self.assertEqual(self.broker.submit(tampered)["error_code"], "invalid_signature")
        non_text = self.envelope(nonce="d" * 32, messages=[{"role": "user", "content": [{"type": "text"}]}])
        self.assertEqual(self.broker.submit(non_text)["error_code"], "invalid_request")

    def test_tool_response_is_limited_to_advertised_functions(self):
        def provider(_messages, *, tools, tool_choice, timeout):
            return {
                "ok": True,
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "call_1", "type": "function",
                        "function": {"name": "other_tool", "arguments": "{}"},
                    }],
                },
            }

        broker = ConversationBroker({"tenant-one": self.key}, lambda *_: "central_sponsored", provider)
        tool = {"type": "function", "function": {"name": "allowed_tool", "parameters": {"type": "object"}}}
        result = broker.submit(self.envelope(nonce="e" * 32, tools=[tool]))
        self.assertEqual(result["error_code"], "response_invalid")

    def test_provider_secret_is_never_returned(self):
        def provider(*_args, **_kwargs):
            return {"ok": True, "message": {"role": "assistant", "content": "Bearer abcdefghijklmnop", "tool_calls": []}}

        broker = ConversationBroker({"tenant-one": self.key}, lambda *_: "central_sponsored", provider)
        result = broker.submit(self.envelope(nonce="f" * 32))
        self.assertEqual(result["error_code"], "response_invalid")
        self.assertNotIn("Bearer", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
