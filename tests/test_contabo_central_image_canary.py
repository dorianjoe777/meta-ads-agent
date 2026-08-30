import unittest

from deploy.contabo.central_image_canary import run_synthetic_canary


class CentralImageCanaryHarnessTests(unittest.TestCase):
    def test_synthetic_canary_verifies_isolation_and_idempotency(self):
        result = run_synthetic_canary()
        self.assertEqual(result["mode"], "synthetic")
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider_calls"], 2)
        self.assertTrue(result["distinct_tenant_keys_verified"])
        self.assertTrue(result["cross_tenant_key_rejected"])
        self.assertTrue(result["reference_snapshots_verified"])
        self.assertTrue(result["idempotency_verified"])
        self.assertTrue(result["account_pool_fallback_verified"])
        self.assertEqual(result["account_pool_size_verified"], 2)
        self.assertFalse(result["external_provider_verified"])


if __name__ == "__main__":
    unittest.main()
