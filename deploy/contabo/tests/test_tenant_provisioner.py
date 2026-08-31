import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from tenant_provisioner import ProvisionerCore, ReplayWindow, sign_body


class FakeProvisioner(ProvisionerCore):
    def __init__(self, events, *, pool_ok=True, suspend_ok=True):
        self.events = events
        self.pool_ok = pool_ok
        self.suspend_ok = suspend_ok
        super().__init__(
            Path(tempfile.mkdtemp()),
            provision=lambda _base, tenant: self._event("provision", tenant),
            suspend=lambda _base, tenant: self._event("suspend", tenant, ok=suspend_ok),
            assign_pool=lambda tenant: self._event("pool", tenant, ok=pool_ok),
            create_license=lambda tenant, name: self._license_event(tenant, name),
            install_license=lambda tenant, license_key, key, actor: self._install_event(tenant, license_key, key, actor),
        )

    def _event(self, action, tenant, *, ok=True):
        self.events.append((action, tenant))
        return {"ok": ok}

    def _db_create_trial(self, tenant, display_name, actor):
        self.events.append(("db_create", tenant, display_name, actor))
        return {"ok": True, "data": {"lifecycle_state": "trial"}}

    def _db_extend_trial(self, tenant, ends_at, actor):
        self.events.append(("db_extend", tenant, ends_at, actor))
        return {"ok": True, "data": {"lifecycle_state": "trial", "trial_ends_at": ends_at}}

    def _db_expire_trial(self, tenant, actor):
        self.events.append(("db_expire", tenant, actor))
        return {"ok": True, "data": {"lifecycle_state": "trial_expired", "expired_at": "2026-08-31T00:00:00+00:00"}}

    def _claim_action(self, tenant):
        self.events.append(("claim", tenant))
        return {"ok": True, "claim": {"telegram_url": "https://t.me/admiraia_bot?start=temporary", "expires_at": "2026-08-31T00:30:00+00:00"}}

    def _license_event(self, tenant, display_name):
        self.events.append(("license_bridge", tenant, display_name))
        return {"ok": True, "license_key": "AdmiraHostedLicenseKey_123456789", "created": True}

    def _install_event(self, tenant, license_key, gemini_key, actor):
        self.events.append(("install_license", tenant, license_key, actor, len(gemini_key)))
        return {"ok": True}


class ProvisionerContractTests(unittest.TestCase):
    def test_signed_request_is_single_use_and_survives_restart(self):
        key = b"x" * 32
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "replay.json"
            envelope = sign_body(key, {"action": "expire_trial", "tenant_key": "customer-001"}, now=100, nonce="a" * 32)
            replay = ReplayWindow(state_file)
            self.assertEqual(replay.verify(envelope, key, now=100)["action"], "expire_trial")
            with self.assertRaisesRegex(ValueError, "replayed_request"):
                ReplayWindow(state_file).verify(envelope, key, now=100)

    def test_bad_signature_and_stale_request_rejected(self):
        key = b"x" * 32
        envelope = sign_body(key, {"action": "expire_trial", "tenant_key": "customer-001"}, now=100, nonce="b" * 32)
        with self.assertRaisesRegex(ValueError, "invalid_signature"):
            ReplayWindow().verify(envelope, b"y" * 32, now=100)
        with self.assertRaisesRegex(ValueError, "expired_request"):
            ReplayWindow().verify(envelope, key, now=191)

    def test_create_assigns_gemini_before_issuing_claim(self):
        events = []
        result = FakeProvisioner(events).handle({
            "action": "create_trial", "tenant_key": "customer-001", "display_name": "Customer One",
        })
        self.assertTrue(result["ok"])
        self.assertIn("telegram_url", result["claim"])
        self.assertEqual([item[0] for item in events], ["provision", "db_create", "pool", "claim"])

    def test_pool_failure_never_issues_a_claim(self):
        events = []
        result = FakeProvisioner(events, pool_ok=False).handle({
            "action": "create_trial", "tenant_key": "customer-001", "display_name": "Customer One",
        })
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "gemini_pool_unavailable")
        self.assertEqual([item[0] for item in events], ["provision", "db_create", "pool"])

    def test_extension_is_an_exact_timestamp_and_expiry_suspends_runtime(self):
        events = []
        core = FakeProvisioner(events)
        extended = core.handle({
            "action": "extend_trial", "tenant_key": "customer-001", "ends_at": "2026-09-10T14:30:00-05:00",
        })
        self.assertTrue(extended["ok"])
        self.assertEqual(events[-1][2], "2026-09-10T19:30:00+00:00")
        expired = core.handle({"action": "expire_trial", "tenant_key": "customer-001"})
        self.assertTrue(expired["ok"])
        self.assertEqual([item[0] for item in events[-2:]], ["db_expire", "suspend"])

    def test_license_creates_once_and_never_returns_customer_gemini_key(self):
        events = []
        raw_key = "A" * 32
        result = FakeProvisioner(events).handle({
            "action": "license_trial", "tenant_key": "customer-001", "display_name": "Customer One",
            "gemini_api_key": raw_key,
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["license_key"], "AdmiraHostedLicenseKey_123456789")
        self.assertNotIn("gemini_api_key", result)
        self.assertNotIn(raw_key, repr(result))
        self.assertEqual([item[0] for item in events], ["license_bridge", "install_license"])

    def test_input_bounds(self):
        core = FakeProvisioner([])
        with self.assertRaisesRegex(ValueError, "invalid_tenant_key"):
            core.handle({"action": "expire_trial", "tenant_key": "../escape"})
        with self.assertRaisesRegex(ValueError, "invalid_trial_extension"):
            core.handle({"action": "extend_trial", "tenant_key": "customer-001", "ends_at": "tomorrow"})
        with self.assertRaisesRegex(ValueError, "invalid_customer_gemini_key"):
            core.handle({"action": "license_trial", "tenant_key": "customer-001", "display_name": "Customer", "gemini_api_key": "short"})


if __name__ == "__main__":
    unittest.main()
