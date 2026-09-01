from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("tenantctl", ROOT / "deploy" / "contabo" / "tenantctl.py")
tenantctl = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(tenantctl)


class TenantCtlTests(unittest.TestCase):
    def test_strict_slug(self):
        for value in ("ab", "A-valid", "bad_slug", "../escape", "a" * 64):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    tenantctl.validate_tenant_id(value)
        self.assertEqual(tenantctl.validate_tenant_id("client-001"), "client-001")

    def test_runtime_image_defaults_to_r90_and_accepts_exact_hosted_transition_canaries(self):
        self.assertEqual(tenantctl.selected_runtime_image(), "admira-ia:r90")
        for canary in ("admira-ia-hosted:r91-canary-0123456789ab", "admira-ia-hosted:r99-canary-0123456789ab"):
            self.assertEqual(tenantctl.validate_runtime_image(canary), canary)
        for value in ("latest", "admira-ia:r91", "admira-ia-hosted:r90-canary-0123456789ab",
                      "admira-ia-hosted:r91-canary-latest", "admira-ia-hosted:r99-canary-latest",
                      "admira-ia-hosted:r91-canary-aa3313f80bc", "admira-ia-hosted:r99-canary-AA3313F80BCB"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    tenantctl.validate_runtime_image(value)

    def test_operator_can_pin_one_tenant_to_exact_hosted_canary(self):
        canary = "admira-ia-hosted:r99-canary-0123456789ab"
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            tenantctl.provision(base, "client-001", runtime_image=canary)
            compose = (base / "client-001" / "compose.yaml").read_text()
            self.assertIn(f"image: {canary}", compose)
            self.assertIn(f'com.admira.image: "{canary}"', compose)
            tenantctl.provision(base, "client-002")
            self.assertIn("image: admira-ia:r90", (base / "client-002" / "compose.yaml").read_text())

    def test_dry_run_never_writes_or_runs(self):
        with tempfile.TemporaryDirectory() as raw, patch.object(tenantctl, "run") as run:
            base = Path(raw) / "tenants"
            result = tenantctl.provision(base, "client-001", dry_run=True)
            self.assertTrue(result["ok"])
            self.assertFalse(base.exists())
            run.assert_not_called()

    def test_provision_is_idempotent_and_secure(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            tenantctl.provision(base, "client-001")
            tenantctl.provision(base, "client-001")
            root = base / "client-001"
            self.assertEqual({p.name for p in root.iterdir()}, set(tenantctl.DIRS) | {"compose.yaml"})
            runtime_env = root / "runtime" / ".env"
            self.assertEqual(runtime_env.stat().st_mode & 0o777, 0o600)
            env_text = runtime_env.read_text()
            self.assertIn("AGENT_BRAIN_PROVIDER=gemini", env_text)
            self.assertIn("AGENT_CHAT_MODEL=gemini-3.5-flash-lite", env_text)
            self.assertIn(
                f"META_OAUTH_BROKER_URL={tenantctl.DEFAULT_META_OAUTH_BROKER_URL}",
                env_text,
            )
            self.assertNotIn("nvidia", env_text.lower())
            tenantctl.provision(base, "client-001")
            self.assertEqual(runtime_env.read_text(), env_text)
            for name in tenantctl.DIRS:
                self.assertEqual((root / name).stat().st_mode & 0o777, 0o700)
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            text = (root / "compose.yaml").read_text()
            self.assertIn("image: admira-ia:r90", text)
            self.assertIn("name: admira-tenant-client-001", text)
            self.assertIn('restart: "no"', text)
            self.assertIn("cap_drop:", text)
            self.assertIn("cap_add:\n      - DAC_OVERRIDE", text)
            self.assertNotIn("FOWNER", text)
            self.assertNotIn("CHOWN", text)
            self.assertIn("no-new-privileges:true", text)
            self.assertNotIn("read_only: true", text)
            self.assertIn("HERMES_HOME: /app/runtime/hermes", text)
            self.assertIn("CODEX_HOME: /app/runtime/hermes/codex-auth", text)
            self.assertIn("META_OAUTH_BROKER_URL:", text)
            self.assertIn("ADMIRA_HOSTED_TELEGRAM_GATEWAY", text)
            self.assertNotIn("/run/admira-central-image-broker", text)
            self.assertNotIn("/run/admira-central-images", text)
            self.assertNotIn("ADMIRA_CENTRAL_IMAGE_CLIENT_KEY_FILE", text)
            self.assertNotIn("/opt/admira", text)
            self.assertIn("/app/dashboard/data", text)
            self.assertNotIn("docker.sock", text)
            self.assertNotIn("ports:", text)
            self.assertNotIn("API_KEY", text)

    def test_central_image_client_keys_are_private_idempotent_and_tenant_scoped(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw) / "tenants"
            keys = Path(raw) / "broker-keys"
            exchange = Path(raw) / "exchange"
            socket_dir = Path(raw) / "broker-socket"
            keys.mkdir(mode=0o700)
            exchange.mkdir(mode=0o700)
            socket_dir.mkdir(mode=0o750)
            tenantctl.provision(
                base, "client-001", central_image_key_root=keys,
                central_image_exchange_root=exchange, central_image_socket_dir=socket_dir,
            )
            verifier = keys / "client-001"
            client = base / "client-001" / "runtime" / tenantctl.CENTRAL_IMAGE_CLIENT_KEY
            before = verifier.read_bytes()
            self.assertEqual(before, client.read_bytes())
            self.assertEqual(verifier.stat().st_mode & 0o777, 0o600)
            self.assertEqual(client.stat().st_mode & 0o777, 0o600)
            self.assertEqual((exchange / "client-001" / "output").stat().st_mode & 0o777, 0o700)
            compose = (base / "client-001" / "compose.yaml").read_text()
            self.assertIn('group_add:\n      - "${ADMIRA_CENTRAL_IMAGE_GID:-19093}"', compose)
            self.assertIn(f'"{socket_dir}:/run/admira-central-image-broker:ro"', compose)
            self.assertIn(
                "ADMIRA_CENTRAL_CAMPAIGN_COMPILER_SOCKET: /run/admira-central-image-broker/compiler.sock",
                compose,
            )
            self.assertIn(
                f'"{exchange / "client-001" / "output"}:/run/admira-central-images"',
                compose,
            )
            self.assertNotIn(
                f'"{exchange / "client-001"}:/run/admira-central-images"',
                compose,
            )
            tenantctl.provision(
                base, "client-001", central_image_key_root=keys,
                central_image_exchange_root=exchange, central_image_socket_dir=socket_dir,
            )
            self.assertEqual(before, verifier.read_bytes())

    def test_central_image_client_rejects_mismatched_or_public_keys(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw) / "tenants"
            keys = Path(raw) / "broker-keys"
            exchange = Path(raw) / "exchange"
            socket_dir = Path(raw) / "broker-socket"
            keys.mkdir(mode=0o700)
            exchange.mkdir(mode=0o700)
            socket_dir.mkdir(mode=0o750)
            tenantctl.provision(
                base, "client-001", central_image_key_root=keys,
                central_image_exchange_root=exchange, central_image_socket_dir=socket_dir,
            )
            client = base / "client-001" / "runtime" / tenantctl.CENTRAL_IMAGE_CLIENT_KEY
            client.write_text("f" * 64 + "\n", encoding="ascii")
            client.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "does not match"):
                tenantctl.provision(
                    base, "client-001", central_image_key_root=keys,
                    central_image_exchange_root=exchange, central_image_socket_dir=socket_dir,
                )
            client.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "private regular file"):
                tenantctl.provision(
                    base, "client-001", central_image_key_root=keys,
                    central_image_exchange_root=exchange, central_image_socket_dir=socket_dir,
                )

    def test_provision_rejects_tenant_and_exchange_symlinks(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw) / "tenants"
            outside = Path(raw) / "outside"
            base.mkdir(mode=0o700)
            outside.mkdir(mode=0o700)
            (base / "client-001").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "tenant root"):
                tenantctl.provision(base, "client-001")
            self.assertFalse((outside / "compose.yaml").exists())

        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw) / "tenants"
            keys = Path(raw) / "keys"
            exchange = Path(raw) / "exchange"
            socket_dir = Path(raw) / "socket"
            outside = Path(raw) / "outside"
            for directory in (keys, exchange, socket_dir, outside):
                directory.mkdir(mode=0o700)
            (exchange / "client-001").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "tenant central image exchange"):
                tenantctl.provision(
                    base, "client-001", central_image_key_root=keys,
                    central_image_exchange_root=exchange, central_image_socket_dir=socket_dir,
                )
            self.assertFalse((outside / "output").exists())

            (exchange / "client-001").unlink()
            (exchange / "client-001").mkdir(mode=0o700)
            (exchange / "client-001" / "output").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "tenant central image output"):
                tenantctl.provision(
                    base, "client-001", central_image_key_root=keys,
                    central_image_exchange_root=exchange, central_image_socket_dir=socket_dir,
                )

    def test_provision_rejects_tenant_subdirectory_and_file_symlinks(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw) / "tenants"
            root = base / "client-001"
            outside = Path(raw) / "outside"
            root.mkdir(parents=True, mode=0o700)
            outside.mkdir(mode=0o700)
            (root / "runtime").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "tenant runtime"):
                tenantctl.provision(base, "client-001")
            self.assertFalse((outside / ".env").exists())

        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw) / "tenants"
            tenantctl.provision(base, "client-001")
            root = base / "client-001"
            outside = Path(raw) / "outside"
            outside.write_text("unchanged", encoding="utf-8")
            (root / "runtime" / ".env").unlink()
            (root / "runtime" / ".env").symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "runtime environment"):
                tenantctl.provision(base, "client-001")
            self.assertEqual(outside.read_text(encoding="utf-8"), "unchanged")

            (root / "runtime" / ".env").unlink()
            (root / "runtime" / ".env").write_text(tenantctl.INITIAL_RUNTIME_ENV, encoding="utf-8")
            (root / "runtime" / ".env").chmod(0o600)
            (root / "compose.yaml").unlink()
            (root / "compose.yaml").symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "tenant Compose"):
                tenantctl.provision(base, "client-001")
            self.assertEqual(outside.read_text(encoding="utf-8"), "unchanged")

    def test_mount_roots_must_be_absolute(self):
        with self.assertRaisesRegex(ValueError, "tenant base must be absolute"):
            tenantctl.provision(Path("relative-tenants"), "client-001", dry_run=True)
        with self.assertRaisesRegex(ValueError, "central image mount roots must be absolute"):
            tenantctl.compose_text(
                Path("/srv/admira/tenants/client-001"), "client-001",
                central_image_enabled=True,
                central_image_exchange_root=Path("relative-exchange"),
            )
        with self.assertRaisesRegex(ValueError, "tenant_id"):
            tenantctl.compose_text(Path("/srv/admira/tenants/client-001"), "../escape")

    def test_limits_are_configurable_but_validated(self):
        text = tenantctl.compose_text(Path("/srv/admira/tenants/client-001"), "client-001", memory_limit="1g", cpu_limit="2.5", pids_limit=512)
        self.assertIn("mem_limit: 1g", text)
        self.assertIn("cpus: 2.5", text)
        self.assertIn("pids_limit: 512", text)
        with self.assertRaises(ValueError):
            tenantctl.compose_text(Path("/tmp/client-001"), "client-001", memory_limit="${SECRET}")
        with self.assertRaises(ValueError):
            tenantctl.compose_text(Path("/tmp/client-001"), "client-001", pids_limit=0)

    def test_provision_never_seeds_legacy_gemini_key(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw) / "tenants"
            legacy = Path(raw) / "legacy-gemini.key"
            legacy.write_text("a-secure-gemini-key-value-12345\n", encoding="utf-8")
            legacy.chmod(0o600)
            with patch.dict(os.environ, {"ADMIRA_HOSTED_GEMINI_KEY_FILE": str(legacy)}):
                tenantctl.provision(base, "client-001")
            runtime_env = base / "client-001" / "runtime" / ".env"
            self.assertIn("GEMINI_API_KEY=\n", runtime_env.read_text())
            self.assertNotIn("a-secure-gemini", runtime_env.read_text())
            self.assertNotIn("gemini-key-file", tenantctl.parser().format_help())

    def test_lifecycle_uses_argv_and_tenant_compose(self):
        with tempfile.TemporaryDirectory() as raw, patch.object(tenantctl, "run") as run:
            run.return_value = type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
            result = tenantctl.lifecycle(Path(raw), "client-001", "start")
            self.assertTrue(result["ok"])
            run.assert_called_once()
            argv = run.call_args.args[0]
            self.assertEqual(argv[:2], ["docker", "compose"])
            self.assertEqual(argv[-5:], ["up", "-d", "--no-build", "--pull", "never"])
            self.assertIn("-p", argv)
            self.assertIn("admira-tenant-client-001", argv)
            self.assertNotIn("shell=True", argv)

    def test_suspend_removes_only_runtime_container(self):
        with tempfile.TemporaryDirectory() as raw, patch.object(tenantctl, "run") as run:
            run.return_value = type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
            result = tenantctl.lifecycle(Path(raw), "client-001", "suspend")
            self.assertTrue(result["ok"])
            argv = run.call_args.args[0]
            self.assertEqual(argv[-2:], ["down", "--remove-orphans"])
            self.assertNotIn("-v", argv)

    def test_plan_is_machine_readable(self):
        result = tenantctl.plan(Path("/srv/admira/tenants"), "client-001")
        self.assertEqual(result["image"], "admira-ia:r90")
        self.assertFalse(result["isolated"]["network_ports"])


if __name__ == "__main__":
    unittest.main()
