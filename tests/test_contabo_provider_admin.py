from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("provider_admin", ROOT / "deploy" / "contabo" / "provider_admin.py")
provider_admin = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(provider_admin)


class ProviderAdminTests(unittest.TestCase):
    def setUp(self):
        # Existing filesystem/rollback tests must remain offline. Dedicated
        # tests below exercise the real health-check transport with a mock.
        self.health_patch = patch.object(provider_admin, "gemini_health_check", return_value=True)
        self.health_patch.start()

    def tearDown(self):
        self.health_patch.stop()

    def test_license_defaults_to_compose_file_next_to_admin_script(self):
        args = provider_admin.build_parser().parse_args(
            ["gemini-license", "client-001", "--source", "customer"]
        )
        self.assertEqual(args.compose_file, provider_admin.DEFAULT_COMPOSE_FILE)
        self.assertEqual(args.compose_file.name, "compose.yaml")
        self.assertEqual(args.db_user, "admira_provisioner_login")
        self.assertEqual(args.recovery_hmac_key_file, provider_admin.DEFAULT_RECOVERY_HMAC_KEY_FILE)

    def tenant(self, raw: str) -> tuple[Path, Path]:
        base = Path(raw) / "tenants"
        runtime = base / "client-001" / "runtime"
        runtime.mkdir(parents=True)
        base.chmod(0o700)
        (base / "client-001").chmod(0o700)
        runtime.chmod(0o700)
        env = runtime / ".env"
        env.write_text("OTHER=value\nGEMINI_API_KEY=old-key-value-1234567890\nTAIL=kept\n", encoding="utf-8")
        env.chmod(0o600)
        return base, env

    def test_set_reads_key_without_placing_it_in_result_or_argv(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            key = "new-gemini-key-value-1234567890"
            result = provider_admin.manage_gemini_key(base, "client-001", value=key, source="operator_pool", replace=True)
            self.assertTrue(result["ok"])
            self.assertNotIn(key, json.dumps(result))
            self.assertIn("OTHER=value\nGEMINI_API_KEY=" + key + "\nTAIL=kept\n", env.read_text())
            self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o600)

    def test_different_existing_key_requires_explicit_replace(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            before = env.read_text()
            with self.assertRaisesRegex(ValueError, "--replace"):
                provider_admin.manage_gemini_key(
                    base, "client-001", value="different-gemini-key-value-1234567890", source="operator_pool"
                )
            self.assertEqual(env.read_text(), before)
            result = provider_admin.manage_gemini_key(
                base, "client-001", value="different-gemini-key-value-1234567890", source="operator_pool", replace=True
            )
            self.assertTrue(result["ok"])
            self.assertIn("GEMINI_API_KEY=different-gemini-key-value-1234567890", env.read_text())

    def test_existing_environment_must_be_private_regular_file(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            env.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "private regular file"):
                provider_admin.manage_gemini_key(base, "client-001", value="replacement-key-value-1234567890", source="operator_pool", replace=True)
            env.unlink()
            env.mkdir()
            with self.assertRaisesRegex(ValueError, "private regular file"):
                provider_admin.manage_gemini_key(base, "client-001", value="replacement-key-value-1234567890", source="operator_pool", replace=True)

    def test_private_file_and_injectable_validator(self):
        with tempfile.TemporaryDirectory() as raw:
            base, _ = self.tenant(raw)
            source = Path(raw) / "key"
            source.write_text("valid-key-value-1234567890\n", encoding="utf-8")
            source.chmod(0o600)
            seen: list[str] = []
            output = io.StringIO()
            with redirect_stdout(output):
                result = provider_admin.main(
                    ["gemini-set", "client-001", "--source", "customer", "--key-file", str(source), "--base-dir", str(base), "--replace", "--runtime-already-stopped"],
                    stdin=io.StringIO("argv-must-not-be-used"),
                )
            self.assertEqual(result, 0)
            self.assertNotIn("valid-key-value-1234567890", output.getvalue())
            self.assertIn("GEMINI_API_KEY=valid-key-value-1234567890", (base / "client-001/runtime/.env").read_text())
            provider_admin.manage_gemini_key(base, "client-001", value="another-valid-key-value-1234567890", source="customer", replace=True, validator=lambda value: seen.append(value) or True)
            self.assertEqual(seen, ["another-valid-key-value-1234567890"])
            source.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "private regular file"):
                provider_admin._read_private_file(source)

    def test_key_inputs_are_size_bounded_without_echoing_content(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            before = env.read_text()
            oversized = "s" * (provider_admin.PRIVATE_INPUT_MAX_CHARS + 1)
            source = Path(raw) / "oversized-key"
            source.write_text(oversized, encoding="utf-8")
            source.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "too large"):
                provider_admin._read_private_file(source)

            output = io.StringIO()
            with redirect_stdout(output):
                code = provider_admin.main(
                    ["gemini-set", "client-001", "--source", "customer", "--base-dir", str(base)],
                    stdin=io.StringIO(oversized),
                )
            self.assertEqual(code, 1)
            self.assertNotIn(oversized, output.getvalue())
            self.assertEqual(env.read_text(), before)

    def test_dry_run_and_clear_do_not_touch_other_files(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            other = env.parent / "keep.txt"
            other.write_text("unchanged", encoding="utf-8")
            before = env.read_text()
            result = provider_admin.manage_gemini_key(base, "client-001", value="dry-run-key-value-1234567890", source="operator_pool", dry_run=True, replace=True)
            self.assertTrue(result["dry_run"])
            self.assertEqual(env.read_text(), before)
            provider_admin.manage_gemini_key(base, "client-001", value=None, source="customer", replace=True)
            self.assertIn("GEMINI_API_KEY=\n", env.read_text())
            self.assertEqual(other.read_text(), "unchanged")

    def test_health_failure_rolls_back_exact_old_env(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            before = env.read_text()
            result = provider_admin.manage_gemini_key(
                base, "client-001", value="replacement-key-value-1234567890", source="operator_pool",
                health_check=lambda _: False, replace=True,
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "health_check_failed")
            self.assertEqual(env.read_text(), before)
            self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o600)

    def test_write_failure_after_replace_rolls_back_exact_old_env(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            before = env.read_text()
            calls = []
            original_write = provider_admin._atomic_write

            def fail_after_first_replace(path, text):
                calls.append(text)
                original_write(path, text)
                if len(calls) == 1:
                    raise OSError("simulated directory fsync failure")

            with patch.object(provider_admin, "_atomic_write", side_effect=fail_after_first_replace):
                result = provider_admin.manage_gemini_key(
                    base, "client-001", value="write-failure-key-value-1234567890",
                    source="operator_pool", replace=True,
                    health_check=lambda _path: self.fail("health check must not run"),
                    record_metadata=lambda _metadata: self.fail("metadata must not run"),
                )
            self.assertEqual(result["error_code"], "environment_write_failed")
            self.assertEqual(env.read_text(), before)
            self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o600)
            self.assertEqual(len(calls), 2)

    def test_metadata_failure_rolls_back_without_exposing_secret(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            before = env.read_text()
            secret = "metadata-failure-secret-key-value-1234567890"

            def recorder(_metadata):
                raise RuntimeError(secret)

            result = provider_admin.manage_gemini_key(
                base, "client-001", value=secret, source="customer", replace=True, record_metadata=recorder
            )
            self.assertEqual(result, {"ok": False, "error_code": "metadata_record_failed", "tenant_id": "client-001", "source": "customer"})
            self.assertEqual(env.read_text(), before)
            self.assertNotIn(secret, json.dumps(result))

    def test_failed_first_write_restores_missing_environment(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            env.unlink()
            result = provider_admin.manage_gemini_key(
                base, "client-001", value="first-key-value-that-is-long-enough-123", source="operator_pool",
                health_check=lambda _: False,
            )
            self.assertEqual(result["error_code"], "health_check_failed")
            self.assertFalse(env.exists())

    def test_tenant_directories_and_base_must_not_be_shared_or_symlinked(self):
        with tempfile.TemporaryDirectory() as raw:
            base, _env = self.tenant(raw)
            (base / "client-001" / "runtime").chmod(0o755)
            with self.assertRaisesRegex(ValueError, "directories must be private"):
                provider_admin.manage_gemini_key(
                    base, "client-001", value="replacement-key-value-1234567890", source="operator_pool", replace=True
                )
            linked = Path(raw) / "linked-tenants"
            linked.symlink_to(base, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "tenant base"):
                provider_admin.manage_gemini_key(
                    linked, "client-001", value="replacement-key-value-1234567890", source="operator_pool", replace=True
                )

    def test_cli_json_captures_safe_error_without_secret(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            secret = "cli-secret-key-value-1234567890"
            output = io.StringIO()
            with redirect_stdout(output):
                code = provider_admin.main(
                    ["gemini-set", "client-001", "--source", "operator_pool", "--base-dir", str(base)],
                    stdin=io.StringIO(secret),
                )
            self.assertEqual(code, 1)
            self.assertNotIn(secret, output.getvalue())
            self.assertEqual(env.read_text(), "OTHER=value\nGEMINI_API_KEY=old-key-value-1234567890\nTAIL=kept\n")

    def test_invalid_key_and_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            with self.assertRaises(ValueError):
                provider_admin.manage_gemini_key(base, "client-001", value="short", source="operator_pool")
            outside = Path(raw) / "outside"
            outside.write_text("OTHER=value\n", encoding="utf-8")
            env.unlink()
            env.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "private regular file"):
                provider_admin.manage_gemini_key(base, "client-001", value="replacement-key-value-1234567890", source="operator_pool")

    def test_gemini_health_check_uses_official_endpoint_and_headers_only(self):
        calls = []

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return None
            def read(self, _limit): return b'{"models":[{"name":"models/gemini-test"}]}'

        def opener(request, **kwargs):
            calls.append((request, kwargs))
            return Response()

        key = "health-check-key-value-1234567890"
        self.assertTrue(provider_admin.check_gemini_api_key(key, opener=opener))
        request, kwargs = calls[0]
        self.assertEqual(request.full_url, provider_admin.GEMINI_MODELS_URL)
        self.assertNotIn(key, request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), key)
        self.assertEqual(request.get_header("X-goog-api-client"), "admira-hosted/r99")
        self.assertEqual(kwargs["timeout"], provider_admin.GEMINI_HEALTH_TIMEOUT_SECONDS)

    def test_gemini_health_check_rejects_empty_or_invalid_model_response(self):
        class Response:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *_args): return None
            def read(self, _limit): return self.body

        key = "health-check-key-value-1234567890"
        self.assertFalse(provider_admin.check_gemini_api_key(key, opener=lambda *_args, **_kwargs: Response(b'{"models":[]}')))
        self.assertFalse(provider_admin.check_gemini_api_key(key, opener=lambda *_args, **_kwargs: Response(b'not-json')))

    def test_default_health_failure_rolls_back_and_does_not_expose_key(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            before = env.read_text()
            self.health_patch.stop()
            try:
                with patch.object(provider_admin, "gemini_health_check", return_value=False):
                    result = provider_admin.manage_gemini_key(
                        base, "client-001", value="health-failure-key-value-1234567890",
                        source="customer", replace=True,
                    )
            finally:
                self.health_patch.start()
            self.assertEqual(result["error_code"], "health_check_failed")
            self.assertEqual(env.read_text(), before)
            self.assertNotIn("health-failure-key-value-1234567890", json.dumps(result))

    def test_dry_run_and_explicit_bypass_do_not_call_health_transport(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            with patch.object(provider_admin, "gemini_health_check", side_effect=AssertionError("network")):
                dry = provider_admin.manage_gemini_key(
                    base, "client-001", value="dry-health-key-value-1234567890", source="customer",
                    dry_run=True, replace=True,
                )
                bypass = provider_admin.manage_gemini_key(
                    base, "client-001", value="bypass-health-key-value-1234567890", source="customer",
                    allow_unverified=True, replace=True,
                )
            self.assertTrue(dry["dry_run"])
            self.assertTrue(bypass["ok"])
            self.assertIn("bypass-health-key-value-1234567890", env.read_text())

    def test_license_transition_uses_psql_input_not_argv(self):
        calls = []

        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stderr="")

        provider_admin.transition_hosted_tenant_to_licensed(
            "client-001", "LIC-test-license-123456", "tenant-env://client-001/GEMINI_API_KEY", "a" * 64, "operator", runner=runner
        )
        argv, kwargs = calls[0]
        self.assertNotIn("LIC-test-license-123456", argv)
        self.assertNotIn("a" * 64, argv)
        self.assertIn("LIC-test-license-123456", kwargs["input"])
        self.assertIn("tenant-env://client-001/GEMINI_API_KEY", kwargs["input"])
        self.assertNotIn("raw-gemini-key-value", kwargs["input"])
        self.assertEqual(kwargs["text"], True)
        self.assertEqual(kwargs["capture_output"], True)
        self.assertEqual(kwargs["check"], False)
        self.assertIn("admira_provisioner_login", argv)
        self.assertIn("provisioner_db_password", " ".join(argv))
        self.assertNotIn("admira_control_owner", argv)

    def test_license_transition_registers_contact_in_same_psql_transaction(self):
        calls = []

        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stderr="")

        provider_admin.transition_hosted_tenant_to_licensed(
            "client-001", "LIC-test-license-123456", "tenant-env://client-001/GEMINI_API_KEY", "a" * 64,
            "operator", email_hmac_hex="b" * 64, license_hmac_hex="c" * 64,
            delivery_ref="sealed-envelope://v1", runner=runner,
        )
        payload = calls[0][1]["input"]
        self.assertIn("BEGIN;", payload)
        self.assertIn("register_verified_license_contact", payload)
        self.assertIn("CROSS JOIN LATERAL admira.transition_hosted_tenant_to_licensed", payload)
        self.assertNotIn("(r.result).tenant_id", payload)
        self.assertIn("sealed-envelope://v1", payload)
        self.assertIn("b" * 64, payload)
        self.assertIn("c" * 64, payload)
        self.assertLess(payload.index("BEGIN;"), payload.index("COMMIT;"))

    def test_license_contact_cli_hashes_private_email_and_key_without_logging_factors(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            email_file = Path(raw) / "email"
            email_file.write_text("Customer@Example.com\n", encoding="utf-8")
            email_file.chmod(0o600)
            hmac_file = Path(raw) / "recovery-hmac"
            hmac_file.write_bytes(b"h" * 32)
            hmac_file.chmod(0o600)
            key = "licensed-gemini-key-value-1234567890"
            captured = []
            with patch.object(provider_admin, "transition_hosted_tenant_to_licensed", side_effect=lambda *a, **kw: captured.append((a, kw))):
                output = io.StringIO()
                with redirect_stdout(output):
                    code = provider_admin.main([
                        "gemini-license", "client-001", "--source", "customer", "--base-dir", str(base),
                        "--email-file", str(email_file), "--recovery-hmac-key-file", str(hmac_file),
                        "--replace", "--runtime-already-stopped",
                    ], stdin=io.StringIO(key))
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertNotIn("Customer@Example.com", rendered)
            self.assertNotIn("h" * 32, rendered)
            self.assertNotIn(key, rendered)
            self.assertEqual(captured[0][1]["delivery_ref"], "sealed-envelope://v1")
            self.assertRegex(captured[0][1]["email_hmac_hex"], r"^[a-f0-9]{64}$")
            self.assertRegex(captured[0][1]["license_hmac_hex"], r"^[a-f0-9]{64}$")

    def test_license_contact_rejects_non_private_email_file_without_touching_env(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            before = env.read_text()
            email_file = Path(raw) / "email"
            email_file.write_text("user@example.com", encoding="utf-8")
            email_file.chmod(0o644)
            hmac_file = Path(raw) / "recovery-hmac"
            hmac_file.write_bytes(b"h" * 32)
            hmac_file.chmod(0o600)
            output = io.StringIO()
            with redirect_stdout(output):
                code = provider_admin.main([
                    "gemini-license", "client-001", "--source", "customer", "--base-dir", str(base),
                    "--email-file", str(email_file), "--recovery-hmac-key-file", str(hmac_file),
                    "--replace", "--runtime-already-stopped",
                ], stdin=io.StringIO("licensed-gemini-key-value-1234567890"))
            self.assertEqual(code, 1)
            self.assertEqual(env.read_text(), before)
            self.assertNotIn("user@example.com", output.getvalue())

    def test_gemini_license_requires_recovery_email_before_touching_env(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            before = env.read_text()
            output = io.StringIO()
            with redirect_stdout(output):
                code = provider_admin.main([
                    "gemini-license", "client-001", "--source", "customer",
                    "--base-dir", str(base), "--replace", "--runtime-already-stopped",
                ], stdin=io.StringIO("licensed-gemini-key-value-1234567890"))
            self.assertEqual(code, 1)
            self.assertEqual(env.read_text(), before)
            self.assertIn("requires a private recovery email file", output.getvalue())

    def test_license_metadata_uses_sql_compatible_opaque_secret_reference(self):
        captured = []
        recorder = provider_admin.make_license_metadata_recorder(
            "client-001", "LIC-test-license-123456",
            transition=lambda *args: captured.append(args),
        )
        recorder({"fingerprint": "b" * 64})
        self.assertEqual(captured[0][2], "tenant-env://client-001/GEMINI_API_KEY")
        self.assertRegex(captured[0][2], r"^[A-Za-z][A-Za-z0-9+.-]*://")
        self.assertNotIn("licensed-gemini-key", captured[0][2])
        self.assertNotIn("GEMINI_API_KEY=", captured[0][2])

    def test_license_metadata_rejects_non_reference_secret_value(self):
        with self.assertRaisesRegex(ValueError, "secret reference format"):
            provider_admin.make_license_metadata_recorder(
                "client-001", "LIC-test-license-123456",
                secret_ref="raw-gemini-key-value-1234567890",
            )

    def test_gemini_license_rejects_operator_pool_source(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            before = env.read_text()
            secret = "operator-pool-key-value-1234567890"
            output = io.StringIO()
            with redirect_stdout(output):
                code = provider_admin.main(
                    ["gemini-license", "client-001", "--source", "operator_pool", "--base-dir", str(base), "--replace"],
                    stdin=io.StringIO(secret),
                )
            self.assertEqual(code, 1)
            self.assertEqual(env.read_text(), before)
            self.assertNotIn(secret, output.getvalue())
            self.assertEqual(json.loads(output.getvalue())["error_code"], "invalid_gemini_credential")

    def test_license_db_failure_rolls_back_exact_environment(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            before = env.read_text()

            def failed_transition(*_args):
                raise RuntimeError("database failure with hidden values")

            result = provider_admin.manage_gemini_key(
                base, "client-001", value="licensed-gemini-key-value-1234567890", source="customer",
                replace=True, record_metadata=provider_admin.make_license_metadata_recorder(
                    "client-001", "LIC-test-license-123456", transition=failed_transition
                ),
            )
            self.assertEqual(result["error_code"], "metadata_record_failed")
            self.assertEqual(env.read_text(), before)
            self.assertNotIn("licensed-gemini-key-value-1234567890", json.dumps(result))
            self.assertNotIn("LIC-test-license-123456", json.dumps(result))

    def test_gemini_license_success_shows_license_once_and_not_key(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            key = "licensed-gemini-key-value-1234567890"
            license_id = "LIC-test-license-123456"
            email_file = Path(raw) / "email"
            email_file.write_text("buyer@example.com\n", encoding="utf-8")
            email_file.chmod(0o600)
            hmac_file = Path(raw) / "recovery-hmac"
            hmac_file.write_bytes(b"h" * 32)
            hmac_file.chmod(0o600)
            called = []
            original = provider_admin.transition_hosted_tenant_to_licensed
            provider_admin.transition_hosted_tenant_to_licensed = lambda *args, **kwargs: called.append((args, kwargs))
            try:
                output = io.StringIO()
                with redirect_stdout(output):
                    code = provider_admin.main(
                        ["gemini-license", "client-001", "--source", "customer", "--base-dir", str(base),
                         "--email-file", str(email_file), "--recovery-hmac-key-file", str(hmac_file),
                         "--replace", "--runtime-already-stopped"],
                        stdin=io.StringIO(key),
                    )
                rendered = output.getvalue()
            finally:
                provider_admin.transition_hosted_tenant_to_licensed = original
            self.assertEqual(code, 0)
            self.assertEqual(rendered.count(license_id), 0)  # generated license is not predictable
            parsed = json.loads(rendered)
            self.assertTrue(parsed["license_id"])
            self.assertEqual(rendered.count(parsed["license_id"]), 1)
            self.assertNotIn(key, rendered)
            self.assertEqual(len(called), 1)
            self.assertIn("GEMINI_API_KEY=" + key, env.read_text())

    def test_gemini_license_dry_run_does_not_call_database_or_write(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            before = env.read_text()
            license_file = Path(raw) / "license"
            license_file.write_text("LIC-test-license-123456\n", encoding="utf-8")
            license_file.chmod(0o600)
            email_file = Path(raw) / "email"
            email_file.write_text("buyer@example.com\n", encoding="utf-8")
            email_file.chmod(0o600)
            hmac_file = Path(raw) / "recovery-hmac"
            hmac_file.write_bytes(b"h" * 32)
            hmac_file.chmod(0o600)
            called = []
            original = provider_admin.transition_hosted_tenant_to_licensed
            provider_admin.transition_hosted_tenant_to_licensed = lambda *args, **kwargs: called.append(args)
            try:
                output = io.StringIO()
                with redirect_stdout(output):
                    code = provider_admin.main(
                        ["gemini-license", "client-001", "--source", "customer", "--base-dir", str(base),
                         "--license-file", str(license_file), "--email-file", str(email_file),
                         "--recovery-hmac-key-file", str(hmac_file), "--dry-run", "--replace"],
                        stdin=io.StringIO("dry-run-gemini-key-value-1234567890"),
                    )
                parsed = json.loads(output.getvalue())
            finally:
                provider_admin.transition_hosted_tenant_to_licensed = original
            self.assertEqual(code, 0)
            self.assertTrue(parsed["dry_run"])
            self.assertEqual(parsed["license_id"], "LIC-test-license-123456")
            self.assertFalse(called)
            self.assertEqual(env.read_text(), before)

    def test_runtime_fence_happens_before_write_health_and_metadata(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            events = []
            result = provider_admin.manage_gemini_key(
                base, "client-001", value="ordered-key-value-1234567890", source="customer",
                replace=True, runtime_fence=lambda tenant: events.append(("suspend", tenant)) or True,
                health_check=lambda path: events.append(("health", path.read_text())) or True,
                record_metadata=lambda metadata: events.append(("db", metadata)),
            )
            self.assertTrue(result["ok"])
            self.assertEqual([event[0] for event in events], ["suspend", "health", "db"])
            self.assertEqual(events[0][1], "client-001")
            self.assertIn("ordered-key-value-1234567890", events[1][1])

    def test_runtime_fence_failure_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            before = env.read_text()
            result = provider_admin.manage_gemini_key(
                base, "client-001", value="fenced-key-value-1234567890", source="customer",
                replace=True, runtime_fence=lambda _tenant: False,
                record_metadata=lambda _metadata: self.fail("database must not run"),
            )
            self.assertEqual(result["error_code"], "runtime_fence_failed")
            self.assertEqual(env.read_text(), before)

    def test_cli_runtime_already_stopped_is_only_bypass(self):
        with tempfile.TemporaryDirectory() as raw:
            base, env = self.tenant(raw)
            with patch.object(provider_admin, "_broker_runtime_fence", side_effect=AssertionError("must bypass")):
                output = io.StringIO()
                with redirect_stdout(output):
                    code = provider_admin.main(
                        ["gemini-set", "client-001", "--source", "customer", "--base-dir", str(base),
                         "--replace", "--runtime-already-stopped"],
                        stdin=io.StringIO("bypass-cli-key-value-1234567890"),
                    )
            self.assertEqual(code, 0)
            self.assertIn("bypass-cli-key-value-1234567890", env.read_text())


if __name__ == "__main__":
    unittest.main()
