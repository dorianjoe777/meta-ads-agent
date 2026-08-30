import hashlib
import io
import json
import stat
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "deploy" / "contabo"))
import gemini_pool_admin as pool

KEY = "AIza" + "x" * 40
FINGERPRINT = hashlib.sha256(KEY.encode()).hexdigest()
PROJECT_ID = "00000000-0000-0000-0000-000000000001"
CREDENTIAL_ID = "00000000-0000-0000-0000-000000000002"
ASSIGNMENT_ID = "00000000-0000-0000-0000-000000000003"


def args(root, **extra):
    values = dict(pool_root=Path(root), key_file=None, key_kind="auth", project_ref="proj-main",
                  capacity=8, dry_run=False, compose_file=Path("compose.yaml"),
                  postgres_service="postgres", db_user="admira_provisioner_login", db_name="admira_control")
    values.update(extra)
    return SimpleNamespace(**values)


def assignment_row(key_kind="auth", fingerprint=FINGERPRINT):
    return json.dumps({"assignment_id": ASSIGNMENT_ID,
                       "secret_ref": f"file+admira://gemini-pool/{fingerprint}",
                       "fingerprint": fingerprint, "key_kind": key_kind})


class PoolSecurityTests(unittest.TestCase):
    def test_register_requires_explicit_auth_key_assertion(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            pool.build_parser().parse_args(["register", "proj-main", "--capacity", "8"])
        parsed = pool.build_parser().parse_args(
            ["register", "proj-main", "--capacity", "8", "--key-kind", "auth"]
        )
        self.assertEqual(parsed.key_kind, "auth")

    def test_register_one_statement_json_uuids_and_redacts_key(self):
        with tempfile.TemporaryDirectory() as td:
            calls = []

            def runner(command, **kwargs):
                calls.append((command, kwargs))
                return SimpleNamespace(returncode=0, stdout=json.dumps(
                    {"project_id": PROJECT_ID, "credential_id": CREDENTIAL_ID}) + "\n")

            result = pool.register(args(td), stream=io.StringIO(KEY), runner=runner, health_check=lambda _: True)
            self.assertEqual(result["fingerprint"], FINGERPRINT)
            self.assertEqual(len(calls), 1)
            command, kwargs = calls[0]
            self.assertIn("register_gemini_pool_project", kwargs["input"])
            self.assertIn("register_gemini_pool_credential", kwargs["input"])
            self.assertNotIn(KEY, json.dumps(result)); self.assertNotIn(KEY, repr(calls))
            self.assertTrue(any(item == "project_ref=proj-main" for item in command))
            path = Path(td) / (FINGERPRINT + ".key")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(Path(td).stat().st_mode), 0o700)

    def test_register_rejects_invalid_capacity_before_key(self):
        with tempfile.TemporaryDirectory() as td:
            health = mock.Mock(return_value=True)
            with self.assertRaisesRegex(ValueError, "capacity"):
                pool.register(args(td, capacity=0), stream=io.StringIO(KEY), health_check=health)
            health.assert_not_called()
            self.assertFalse(any(Path(td).iterdir()))

    def test_register_rejects_standard_and_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                pool.register(args(td, key_kind="standard"), stream=io.StringIO(KEY), health_check=mock.Mock())
            check = mock.Mock(return_value=True)
            result = pool.register(args(td, dry_run=True), stream=io.StringIO(KEY), health_check=check)
            self.assertTrue(result["dry_run"]); check.assert_not_called()
            self.assertFalse(Path(td).exists() and any(Path(td).iterdir()))

    def test_register_db_failure_keeps_private_file_for_retry(self):
        with tempfile.TemporaryDirectory() as td:
            def failed_runner(_command, **_kwargs):
                return SimpleNamespace(returncode=1, stdout="", stderr="database error")

            with self.assertRaisesRegex(RuntimeError, "registration failed"):
                pool.register(args(td), stream=io.StringIO(KEY), runner=failed_runner, health_check=lambda _: True)
            path = Path(td) / (FINGERPRINT + ".key")
            self.assertTrue(path.exists()); self.assertEqual(pool._private_read(path), KEY)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_symlink_and_traversal_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "bad.key").symlink_to(root / "elsewhere")
            with self.assertRaises(ValueError): pool._private_read(root / "bad.key")
            with self.assertRaises(ValueError): pool._ref(root, "file+admira://gemini-pool/../x")
        with self.assertRaisesRegex(ValueError, "absolute"):
            pool._root(Path("relative-pool"), create=True)

    def _key_root(self, td):
        root = Path(td); root.mkdir(exist_ok=True); root.chmod(0o700)
        path = root / (FINGERPRINT + ".key"); path.write_text(KEY); path.chmod(0o600)
        return root

    def test_assignment_requires_uuid_and_auth_key_kind(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._key_root(td); ns = args(root, runtime_key="client-001", base_dir=root)
            rows = [json.dumps({"assignment_id": "not-a-uuid", "secret_ref": f"file+admira://gemini-pool/{FINGERPRINT}", "fingerprint": FINGERPRINT, "key_kind": "auth"}), assignment_row(key_kind="standard")]
            for row in rows:
                seen = []

                def runner(_command, **kwargs):
                    seen.append(kwargs.get("input", ""))
                    return SimpleNamespace(returncode=0, stdout=row if len(seen) == 1 else "1\n")

                with self.assertRaisesRegex(RuntimeError, "invalid pool assignment"):
                    pool.assign(ns, runner=runner, manage=mock.Mock(), fence=lambda _: True)
                self.assertGreaterEqual(len(seen), 2)
                self.assertTrue(all(KEY not in text for text in seen))

    def test_invalid_fingerprint_attempts_release_without_secret(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._key_root(td); ns = args(root, runtime_key="client-001", base_dir=root); seen = []

            def runner(_command, **kwargs):
                seen.append(kwargs.get("input", ""))
                row = assignment_row(fingerprint="a" * 63 + "z")
                return SimpleNamespace(returncode=0, stdout=row if len(seen) == 1 else "1\n")

            with self.assertRaisesRegex(RuntimeError, "invalid pool assignment"):
                pool.assign(ns, runner=runner, manage=mock.Mock(), fence=lambda _: True)
            self.assertEqual(len(seen), 2); self.assertIn("release_hosted_gemini_trial", seen[1])
            self.assertNotIn(KEY, repr(seen))

    def test_record_metadata_callback_finalizes_before_success(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._key_root(td); ns = args(root, runtime_key="client-001", base_dir=root); events = []

            def runner(_command, **kwargs):
                sql = kwargs.get("input", ""); events.append("finalize" if "finalize_hosted" in sql else "assign")
                return SimpleNamespace(returncode=0, stdout=assignment_row() if len(events) == 1 else "true\n")

            def manage(_base, _runtime, **kwargs):
                events.append("manage"); self.assertEqual(kwargs["source"], "operator_pool")
                kwargs["record_metadata"]({"tenant_id": "client-001"}); events.append("after-callback")
                return {"ok": True}

            result = pool.assign(ns, runner=runner, manage=manage, fence=lambda _: True)
            self.assertTrue(result["ok"]); self.assertEqual(events, ["assign", "manage", "finalize", "after-callback"])

    def test_real_manage_finalization_failure_restores_exact_env_and_releases(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._key_root(td); tenant_runtime = root / "client-001" / "runtime"; tenant_runtime.mkdir(parents=True)
            (root / "client-001").chmod(0o700); tenant_runtime.chmod(0o700)
            env = tenant_runtime / ".env"
            before = "OTHER=value\nGEMINI_API_KEY=old-secret-value-1234567890\nTAIL=kept\n"
            env.write_text(before); env.chmod(0o600)
            ns = args(root, runtime_key="client-001", base_dir=root); calls = []

            def runner(_command, **kwargs):
                sql = kwargs.get("input", ""); calls.append(sql)
                if "assign_hosted" in sql: return SimpleNamespace(returncode=0, stdout=assignment_row())
                if "finalize_hosted" in sql: return SimpleNamespace(returncode=0, stdout="not-a-boolean\n")
                return SimpleNamespace(returncode=0, stdout="1\n")

            with mock.patch.object(pool.provider_admin, "gemini_health_check", return_value=True):
                result = pool.assign(ns, runner=runner, fence=lambda _: True)
            self.assertFalse(result["ok"]); self.assertEqual(result["error_code"], "metadata_record_failed")
            self.assertEqual(env.read_text(), before); self.assertIn("release_hosted_gemini_trial", calls[-1])
            self.assertNotIn(KEY, repr(calls))

    def test_retry_existing_assignment_accepts_idempotent_false_finalization(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._key_root(td)
            tenant_runtime = root / "client-001" / "runtime"; tenant_runtime.mkdir(parents=True)
            (root / "client-001").chmod(0o700); tenant_runtime.chmod(0o700)
            env = tenant_runtime / ".env"
            env.write_text("GEMINI_API_KEY=" + KEY + "\n"); env.chmod(0o600)
            ns = args(root, runtime_key="client-001", base_dir=root); calls = []

            def runner(_command, **kwargs):
                sql = kwargs.get("input", ""); calls.append(sql)
                return SimpleNamespace(returncode=0, stdout=assignment_row() if len(calls) == 1 else "false\n")

            with mock.patch.object(pool.provider_admin, "gemini_health_check", return_value=True):
                result = pool.assign(ns, runner=runner, fence=lambda _: True)
            self.assertTrue(result["ok"])
            self.assertEqual(env.read_text(), "GEMINI_API_KEY=" + KEY + "\n")
            self.assertEqual(len(calls), 2)

    def test_fence_health_db_paths_never_expose_key(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._key_root(td); ns = args(root, runtime_key="client-001", base_dir=root); output = []

            def runner(_command, **kwargs):
                output.append(kwargs.get("input", "")); return SimpleNamespace(returncode=0, stdout=assignment_row())

            result = pool.assign(ns, runner=runner, manage=mock.Mock(return_value={"ok": False, "error_code": "health_check_failed"}), fence=lambda _: True)
            self.assertFalse(result["ok"]); self.assertNotIn(KEY, json.dumps(result)); self.assertNotIn(KEY, repr(output))

    def test_cleanup_pending_is_reported_when_release_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._key_root(td); ns = args(root, runtime_key="client-001", base_dir=root); calls = []

            def runner(_command, **kwargs):
                calls.append(kwargs.get("input", ""))
                return SimpleNamespace(returncode=0 if len(calls) == 1 else 1, stdout=assignment_row() if len(calls) == 1 else "")

            result = pool.assign(ns, runner=runner, manage=mock.Mock(return_value={"ok": False, "error_code": "health_check_failed"}), fence=lambda _: True)
            self.assertFalse(result["ok"]); self.assertTrue(result["cleanup_pending"])

    def test_invalid_runtime_is_rejected_before_db(self):
        with self.assertRaises(ValueError): pool.assign(SimpleNamespace(runtime_key="../escape", dry_run=False))


if __name__ == "__main__":
    unittest.main()
