import hashlib
import threading
import unittest

from deploy.contabo.campaign_compiler_broker import CampaignCompilerBroker, MODEL, sign_request


class CampaignCompilerBrokerTests(unittest.TestCase):
    def setUp(self):
        self.key = b"k" * 32
        self.calls = []
        self.broker = CampaignCompilerBroker(
            {"tenant-one": self.key}, lambda tool: {"tool": tool, "type": "object"},
            lambda tenant, purpose: "central_sponsored",
            lambda request, schema: self.calls.append((request, schema)) or {"name": "Q4"},
            max_global=2, freshness_seconds=30,
        )

    def envelope(self, request="request-001", **extra):
        body = {"tenant_id": "tenant-one", "request_id": request,
                "purpose": "campaign_compile", "tool": "create_website_campaign",
                "prompt": "approved brief"}
        body.update(extra)
        return sign_request(self.key, body, timestamp=1000,
                            nonce=hashlib.sha256(request.encode()).hexdigest())

    def test_success_uses_server_model_and_schema(self):
        result = self.broker.submit(self.envelope(), now=1000)
        self.assertEqual(result, {"ok": True, "tenant_id": "tenant-one", "request_id": "request-001",
                                  "model": MODEL, "compiled": {"name": "Q4"}})
        self.assertEqual(self.calls[0][0]["prompt"], "approved brief")

    def test_timeout_seconds_accepts_safe_integer_bounds_and_reaches_provider(self):
        for value in (1, 230):
            with self.subTest(value=value):
                result = self.broker.submit(
                    self.envelope(request="request-timeout-" + str(value), timeout_seconds=value),
                    now=1000,
                )
                self.assertTrue(result["ok"])
                self.assertEqual(self.calls[-1][0]["timeout_seconds"], value)

    def test_timeout_seconds_rejects_non_integer_and_out_of_range_values(self):
        for index, value in enumerate((0, -1, 271, "30", 30.0, True), start=1):
            with self.subTest(value=value):
                result = self.broker.submit(
                    self.envelope(request="request-invalid-timeout-" + str(index), timeout_seconds=value),
                    now=1000,
                )
                self.assertEqual(result["error_code"], "invalid_request")

    def test_cross_signature_tampering_and_replay(self):
        envelope = self.envelope()
        envelope["body"]["prompt"] = "tampered"
        self.assertEqual(self.broker.submit(envelope, now=1000)["error_code"], "invalid_signature")
        good = self.envelope(request="request-002")
        self.assertTrue(self.broker.submit(good, now=1000)["ok"])
        self.assertEqual(self.broker.submit(good, now=1000)["error_code"], "replayed_request")

    def test_authorization_and_limits(self):
        denied = CampaignCompilerBroker({"tenant-one": self.key}, lambda tool: {},
                                         lambda tenant, purpose: "blocked", lambda request, schema: {})
        self.assertEqual(denied.submit(self.envelope(), now=1000)["error_code"], "entitlement_blocked")
        self.assertEqual(self.broker.submit(self.envelope(request="request-003", tool="delete_campaign"), now=1000)["error_code"], "tool_not_allowed")
        gate = threading.Event()
        broker = CampaignCompilerBroker({"tenant-one": self.key}, lambda tool: {},
                                        lambda tenant, purpose: "central_sponsored",
                                        lambda request, schema: gate.wait(1) or {})
        result = []
        thread = threading.Thread(target=lambda: result.append(broker.submit(self.envelope(request="request-004"), now=1000)))
        thread.start()
        while not broker._active:
            pass
        self.assertEqual(broker.submit(self.envelope(request="request-005"), now=1000)["error_code"], "tenant_busy")
        gate.set(); thread.join(2)

    def test_redacts_secret_shapes_and_large_responses(self):
        for index, leaked in enumerate(({"x": "Bearer abcdefghijkl"}, {"x": "sk-abcdefghijkl"},
                       {"x": "eyJhbGciOiJIUzI1NiJ9.payload.signature"}), start=10):
            broker = CampaignCompilerBroker({"tenant-one": self.key}, lambda tool: {},
                                            lambda tenant, purpose: "central_sponsored",
                                            lambda request, schema, leaked=leaked: leaked)
            self.assertEqual(broker.submit(self.envelope(request="request-" + str(index)), now=1000)["error_code"], "compiled_invalid")
        broker = CampaignCompilerBroker({"tenant-one": self.key}, lambda tool: {},
                                        lambda tenant, purpose: "central_sponsored",
                                        lambda request, schema: {"x": "a" * 100}, max_response_bytes=80)
        self.assertEqual(broker.submit(self.envelope(request="request-large"), now=1000)["error_code"], "response_too_large")


if __name__ == "__main__":
    unittest.main()
