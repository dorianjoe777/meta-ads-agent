import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from license import license_status


class HostedLicenseEntitlementTests(unittest.TestCase):
    def _config(self):
        return SimpleNamespace(
            license_key="",
            license_server_url="",
            license_required_for_live=True,
        )

    def _write_claim(self, path, payload, mode=0o600):
        path.write_text(json.dumps(payload), encoding="utf-8")
        path.chmod(mode)

    def _claim(self, lifecycle_state="trial", **marker):
        return {
            "tenant_id": "tenant-001",
            "lifecycle_state": lifecycle_state,
            "route": "central_sponsored",
            "entitlement": "individual",
            "plan": "individual",
            "features": ["campaign_creation"],
            **marker,
        }

    def _status_for(self, claim_path, tenant="tenant-001", **extra_env):
        environment = {
            "ADMIRA_HOSTED_TELEGRAM_GATEWAY": "true",
            "ADMIRA_HOSTED_IMAGE_ACCESS_FILE": str(claim_path),
            "ADMIRA_TENANT_ID": tenant,
            **extra_env,
        }
        with patch.dict(os.environ, environment, clear=False):
            return license_status(self._config())

    def test_accepts_trial_and_licensed_claims_with_either_marker(self):
        cases = (("trial", {"update_id": "telegram-update-42"}),
                 ("licensed", {"request_marker": "request-42"}))
        with tempfile.TemporaryDirectory() as directory:
            claim_path = Path(directory) / "hosted-claim.json"
            for lifecycle_state, marker in cases:
                with self.subTest(lifecycle_state=lifecycle_state, marker=marker):
                    self._write_claim(claim_path, self._claim(lifecycle_state, **marker))
                    result = self._status_for(claim_path)

                    self.assertTrue(result["valid"], result)
                    self.assertEqual(result["plan"], "individual")
                    self.assertTrue(result["is_individual"])
                    self.assertIn("campaign_creation", result["features"])

    def test_missing_claim_preserves_license_key_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            claim_path = Path(directory) / "missing-claim.json"
            result = self._status_for(claim_path)

        self.assertFalse(result["valid"])
        self.assertEqual(result["detail"], "License key missing")

    def test_self_hosted_runtime_cannot_consume_a_hosted_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            claim_path = Path(directory) / "hosted-claim.json"
            self._write_claim(claim_path, self._claim(update_id="telegram-update-42"))
            result = self._status_for(
                claim_path,
                ADMIRA_HOSTED_TELEGRAM_GATEWAY="false",
            )

        self.assertFalse(result["valid"])
        self.assertEqual(result["detail"], "License key missing")

    def test_rejects_claim_with_wrong_tenant_or_invalid_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            claim_path = Path(directory) / "hosted-claim.json"
            for payload, tenant in (
                (self._claim(), "tenant-other"),
                (self._claim("expired", update_id="telegram-update-42"), "tenant-001"),
                (self._claim("trial_expired", update_id="telegram-update-42"), "tenant-001"),
            ):
                with self.subTest(payload=payload, tenant=tenant):
                    self._write_claim(claim_path, payload)
                    result = self._status_for(claim_path, tenant=tenant)
                    self.assertFalse(result["valid"], result)
                    self.assertEqual(result["detail"], "License key missing")

    def test_rejects_claim_without_nonempty_update_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            claim_path = Path(directory) / "hosted-claim.json"
            for marker in ({"update_id": ""}, {"request_marker": ""}, {}):
                with self.subTest(marker=marker):
                    self._write_claim(claim_path, self._claim(**marker))
                    result = self._status_for(claim_path)
                    self.assertFalse(result["valid"], result)
                    self.assertEqual(result["detail"], "License key missing")

    def test_rejects_permissive_claim_file_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            claim_path = Path(directory) / "hosted-claim.json"
            for mode in (0o640, 0o604):
                with self.subTest(mode=oct(mode)):
                    self._write_claim(claim_path, self._claim(update_id="telegram-update-42"), mode)
                    self.assertNotEqual(stat.S_IMODE(claim_path.stat().st_mode), 0o600)
                    result = self._status_for(claim_path)
                    self.assertFalse(result["valid"], result)
                    self.assertEqual(result["detail"], "License key missing")

    def test_rejects_symlink_relative_path_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real_claim = root / "real-claim.json"
            symlink_claim = root / "symlink-claim.json"
            self._write_claim(real_claim, self._claim(update_id="telegram-update-42"))
            symlink_claim.symlink_to(real_claim)
            result = self._status_for(symlink_claim)
            self.assertFalse(result["valid"], result)
            self.assertEqual(result["detail"], "License key missing")

            invalid_claim = root / "invalid-claim.json"
            invalid_claim.write_text("{not-json", encoding="utf-8")
            invalid_claim.chmod(0o600)
            result = self._status_for(invalid_claim)
            self.assertFalse(result["valid"], result)
            self.assertEqual(result["detail"], "License key missing")

            relative_claim = root / "relative-claim.json"
            self._write_claim(relative_claim, self._claim(update_id="telegram-update-42"))
            old_cwd = os.getcwd()
            try:
                os.chdir(root)
                result = self._status_for(Path("relative-claim.json"))
            finally:
                os.chdir(old_cwd)
            self.assertFalse(result["valid"], result)
            self.assertEqual(result["detail"], "License key missing")


if __name__ == "__main__":
    unittest.main()
