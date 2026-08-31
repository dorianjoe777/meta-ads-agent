import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from operator_dashboard import OperatorActionError, OperatorState


class FakeCursor:
    def __init__(self, rows, calls):
        self.rows = rows
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, _params=None):
        self.calls.append(query)

    def fetchall(self):
        return list(self.rows)


class FakeConnection:
    def __init__(self, rows, calls):
        self.rows = rows
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return FakeCursor(self.rows, self.calls)


class FakeProvisioner:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def request(self, body):
        self.requests.append(dict(body))
        return dict(self.response)


def trial_row(key="customer-001", name="Customer One"):
    created = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
    return (key, name, "trial", created, created, created + timedelta(days=5), None, True)


class CustomerLifecycleStateTests(unittest.TestCase):
    def make_state(self, rows, provisioner):
        calls = []
        return OperatorState(
            connect=lambda: FakeConnection(rows, calls), provisioner=provisioner,
        ), calls

    def test_trial_projection_is_secret_free(self):
        state, calls = self.make_state([trial_row()], FakeProvisioner({"ok": True}))
        items = state.trial_accounts()
        self.assertEqual(items[0]["runtime_key"], "customer-001")
        self.assertEqual(items[0]["lifecycle_state"], "trial")
        self.assertTrue(items[0]["gemini_pool_ready"])
        self.assertNotIn("tenant_id", items[0])
        self.assertNotIn("api_key", repr(items[0]).lower())
        self.assertIn("admira.operator_trial_accounts()", calls[0])

    def test_create_trial_returns_only_safe_deep_link(self):
        fake = FakeProvisioner({
            "ok": True,
            "claim": {"telegram_url": "https://t.me/admiraia_bot?start=abcdefghijklmnopqrstuvwxyz_123456"},
        })
        state, _calls = self.make_state([], fake)
        result = state.create_trial("customer-001", "Customer One")
        self.assertEqual(result["claim_url"], "https://t.me/admiraia_bot?start=abcdefghijklmnopqrstuvwxyz_123456")
        self.assertEqual(fake.requests[0], {
            "action": "create_trial", "tenant_key": "customer-001", "display_name": "Customer One",
            "actor_id": "operator-dashboard",
        })

    def test_provisioner_failure_uses_safe_status(self):
        state, _calls = self.make_state([], FakeProvisioner({"ok": False, "error_code": "gemini_pool_unavailable"}))
        with self.assertRaises(OperatorActionError) as raised:
            state.create_trial("customer-001", "Customer One")
        self.assertEqual(raised.exception.code, "gemini_pool_unavailable")
        self.assertEqual(raised.exception.status, 503)

    def test_license_looks_up_display_name_and_does_not_return_gemini_key(self):
        fake = FakeProvisioner({"ok": True, "license_key": "AdmiraHostedLicenseKey_123456789"})
        state, _calls = self.make_state([trial_row()], fake)
        raw_key = "A" * 32
        result = state.license_trial("customer-001", raw_key)
        self.assertEqual(result["license_key"], "AdmiraHostedLicenseKey_123456789")
        self.assertNotIn(raw_key, repr(result))
        self.assertEqual(fake.requests[0]["display_name"], "Customer One")
        self.assertEqual(fake.requests[0]["gemini_api_key"], raw_key)

    def test_license_maps_a_trial_lookup_outage_to_a_safe_retryable_error(self):
        def unavailable_connection():
            raise OSError("database is unavailable")

        state = OperatorState(
            connect=unavailable_connection,
            provisioner=FakeProvisioner({"ok": True, "license_key": "AdmiraHostedLicenseKey_123456789"}),
        )
        with self.assertRaises(OperatorActionError) as raised:
            state.license_trial("customer-001", "A" * 32)
        self.assertEqual(raised.exception.code, "trial_accounts_unavailable")
        self.assertEqual(raised.exception.status, 503)

    def test_trial_extension_rejects_naive_and_too_distant_timestamps(self):
        state, _calls = self.make_state([], FakeProvisioner({"ok": True}))
        with self.assertRaises(OperatorActionError) as naive:
            state.extend_trial("customer-001", "2026-09-10T12:00:00")
        self.assertEqual(naive.exception.code, "invalid_trial_extension")
        far = (datetime.now(timezone.utc) + timedelta(days=366)).isoformat()
        with self.assertRaises(OperatorActionError) as distant:
            state.extend_trial("customer-001", far)
        self.assertEqual(distant.exception.code, "invalid_trial_extension")


if __name__ == "__main__":
    unittest.main()
