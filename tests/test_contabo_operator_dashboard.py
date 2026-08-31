import ast
import base64
import hashlib
import http.client
import ipaddress
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "contabo"
sys.path.insert(0, str(DEPLOY))
import operator_dashboard as dashboard

PASSWORD = "fixture-password-with-entropy"
KEY = "AIza" + "x" * 40


def write_private(path, value):
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)


def password_hash(password=PASSWORD):
    salt = b"operator-test-salt-32-bytes-long!!"
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return "pbkdf2_sha256$100000$%s$%s\n" % (
        base64.urlsafe_b64encode(salt).decode(), base64.urlsafe_b64encode(digest).decode())


class PrivateFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="admira-operator-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.now = 100.0
        self.clock = lambda: self.now
        self.password_root = self.root / "password"
        self.gemini_root = self.root / "gemini"
        self.codex_root = self.root / "codex"
        for path in (self.password_root, self.gemini_root, self.codex_root,
                     self.codex_root / "primary", self.codex_root / "secondary"):
            path.mkdir(mode=0o700)
        self.password_file = self.password_root / "password.hash"
        self.state = dashboard.OperatorState(password_file=self.password_file,
                                             gemini_root=self.gemini_root,
                                             codex_root=self.codex_root, clock=self.clock)
        self.addCleanup(self.state.login.shutdown)

    def configured_password(self):
        write_private(self.password_file, password_hash())

    def auth_file(self, account="primary"):
        path = self.codex_root / account / "auth.json"
        write_private(path, json.dumps({"tokens": {"access_token": "private-access-value",
                      "refresh_token": "private-refresh-value", "id_token": "private-id-value"}}))
        return path


class ContaboOperatorDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compose = (DEPLOY / "compose.yaml").read_text(encoding="utf-8")
        cls.bootstrap = (DEPLOY / "bootstrap-control-plane.sh").read_text(encoding="utf-8")
        cls.preflight = (DEPLOY / "release-preflight.sh").read_text(encoding="utf-8")
        cls.dashboard = (DEPLOY / "operator_dashboard.py").read_text(encoding="utf-8")

    def test_operator_profile_is_loopback_and_isolated(self):
        service = self.compose.split("  operator-dashboard:\n", 1)[1].split("\n  telegram-poller:\n", 1)[0]
        self.assertIn('profiles: ["operator-dashboard"]', service)
        self.assertIn("image: ${CENTRAL_IMAGE_IMAGE", service)
        self.assertIn('"127.0.0.1:${ADMIRA_OPERATOR_PORT:-8791}:8791"', service)
        self.assertIn("operator_db_password", service)
        self.assertIn("./secrets/operator-password", service)
        self.assertIn("/var/lib/admira/operator-password/password.hash", service)
        self.assertNotIn("operator_password_hash", service)
        self.assertIn("/etc/admira/gemini-pool", service)
        self.assertIn("central-codex-auth", service)
        self.assertIn("read_only: true", service)
        self.assertIn("cap_drop:\n      - ALL", service)
        self.assertIn("no-new-privileges:true", service)
        self.assertNotIn("docker.sock", service)
        self.assertIn("mode=0700,uid=${ADMIRA_SERVICE_UID:-1001},gid=${ADMIRA_SERVICE_GID:-1001}", service)
        self.assertIn('max-size: "10m"', service)
        for forbidden in ("telegram_bot_token", "runtime_broker_key", "provisioner_db_password", "/srv/admira/tenants"):
            self.assertNotIn(forbidden, service)

    def test_operator_has_only_dedicated_private_and_provider_networks(self):
        service = self.compose.split("  operator-dashboard:\n", 1)[1].split("\n  telegram-poller:\n", 1)[0]
        networks = service.split("    networks:\n", 1)[1].split("\n    security_opt:", 1)[0].splitlines()
        self.assertEqual(networks, ["      - operator_private", "      - operator_provider_egress"])
        self.assertNotIn("telegram_egress", service)
        self.assertIn("  operator_private:\n    internal: true", self.compose)

    def test_dashboard_uses_safe_device_login_and_cookie_csrf_controls(self):
        tree = ast.parse(self.dashboard)
        self.assertIn("shell=False", self.dashboard)
        self.assertIn("X-CSRF-Token", self.dashboard)
        self.assertIn("HttpOnly; SameSite=Strict", self.dashboard)
        self.assertIn("login_backoff", self.dashboard)
        self.assertIn("MAX_BODY = 16 * 1024", self.dashboard)
        self.assertIsNotNone(tree)

    def test_bootstrap_prepares_private_storage_without_password(self):
        self.assertIn("--prepare-operator-host-dirs", self.bootstrap)
        self.assertIn('OPERATOR_PASSWORD_DIR="$SECRETS_DIR/operator-password"', self.bootstrap)
        self.assertIn('chmod 0700 "$OPERATOR_PASSWORD_DIR"', self.bootstrap)
        self.assertIn('[[ -L "$OPERATOR_PASSWORD_DIR"', self.bootstrap)
        self.assertIn('[[ -L "$secret_path"', self.bootstrap)
        self.assertNotIn("--set-operator-password", self.bootstrap)
        self.assertNotIn("pbkdf2_hmac", self.bootstrap)
        self.assertNotIn('touch "$OPERATOR_PASSWORD_DIR/password.hash"', self.bootstrap)
        self.assertIn("must be completed through the SSH tunnel", self.bootstrap)

    def test_preflight_checks_operator_hash_without_disclosing_it(self):
        self.assertIn("secrets/operator-password/password.hash", self.preflight)
        self.assertIn("operator secret is private and service-owned", self.preflight)
        self.assertIn("operator first-run password setup is pending", self.preflight)
        self.assertNotIn('cat "$operator_secret"', self.preflight)

    def test_migration_uses_dedicated_execute_only_role(self):
        migration = (DEPLOY / "db/migrations/011_operator_dashboard.sql").read_text()
        validator = (DEPLOY / "db/validate_operator_dashboard.sql").read_text()
        roles = (DEPLOY / "db/bootstrap_service_roles.sql").read_text()
        self.assertIn("CREATE ROLE admira_operator NOLOGIN NOBYPASSRLS", migration)
        self.assertIn("pg_advisory_xact_lock", migration)
        self.assertIn("BEGIN;", migration)
        self.assertIn("COMMIT;", migration)
        self.assertIn("STABLE SECURITY DEFINER SET search_path = admira, pg_catalog", migration)
        self.assertIn("REVOKE ALL ON ALL TABLES IN SCHEMA admira FROM admira_operator", migration)
        self.assertIn("REVOKE admira_provisioner FROM admira_operator_login", roles)
        self.assertIn("'admira_operator_login','admira_operator'", roles)
        self.assertNotRegex(migration, r"GRANT\s+(?:SELECT|INSERT|UPDATE|DELETE)")
        self.assertNotIn("DROP TABLE", migration)
        self.assertIn("operator can read pool credentials directly", validator)
        self.assertIn("operator can assign tenant credentials", validator)
        self.assertIn("operator pool RLS was weakened", validator)
        self.assertIn("ROLLBACK;", validator)
        projection = migration.split("RETURNS TABLE (", 1)[1].split(")", 1)[0]
        for forbidden in ("secret_ref", "fingerprint", "tenant_id", "api_key"):
            self.assertNotIn(forbidden, projection)

    @unittest.skipUnless(shutil.which("docker"), "Docker Compose CLI unavailable")
    def test_rendered_compose_preserves_loopback_and_dormant_boundaries(self):
        result = subprocess.run(["docker", "compose", "--project-directory", str(DEPLOY),
                                 "-f", str(DEPLOY / "compose.yaml"), "--profile", "*",
                                 "config", "--format", "json"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(result.stdout)
        services = config["services"]
        service = services["operator-dashboard"]
        self.assertEqual(service["profiles"], ["operator-dashboard"])
        self.assertEqual(service["ports"][0]["host_ip"], "127.0.0.1")
        self.assertEqual(service["ports"][0]["target"], 8791)
        self.assertEqual(len(service["ports"]), 1)
        self.assertTrue(all(not item.get("ports") for name, item in services.items() if name != "operator-dashboard"))
        for network, expected in (("operator_private", {"postgres", "operator-dashboard"}),
                                  ("operator_provider_egress", {"operator-dashboard"})):
            self.assertEqual({name for name, item in services.items() if network in item.get("networks", {})}, expected)
        self.assertEqual(set(service["networks"]), {"operator_private", "operator_provider_egress"})
        self.assertTrue(config["networks"]["operator_private"]["internal"])
        self.assertEqual({item["source"] for item in service["secrets"]}, {"operator_db_password"})
        mounts = {item["target"]: item for item in service["volumes"]}
        for target in ("/etc/admira/gemini-pool", "/app/runtime/hermes/codex-auth-pool", "/var/lib/admira/operator-password"):
            self.assertFalse(mounts[target].get("read_only", False))
            self.assertFalse(mounts[target]["bind"]["create_host_path"])
        self.assertEqual(services["central-image-broker"]["profiles"], ["central-images"])
        self.assertEqual(services["runtime-worker"]["environment"]["ADMIRA_CENTRAL_IMAGE_READY"], "false")
        self.assertEqual(service["environment"]["ADMIRA_OPERATOR_COOKIE_SECURE"], "false")
        self.assertEqual(service["environment"]["ADMIRA_OPERATOR_ALLOWED_HOSTS"], "localhost,127.0.0.1,::1")
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertRegex(dockerfile, r"ARG CODEX_CLI_VERSION=\d+\.\d+\.\d+")
        self.assertIn('npm install -g "@openai/codex@${CODEX_CLI_VERSION}"', dockerfile)
        self.assertIn("COPY . .", dockerfile)

    @unittest.skipIf(os.geteuid() == 0, "secret bootstrap deliberately requires a non-root service user")
    def test_bootstrap_creates_only_private_generated_secrets_and_preserves_existing(self):
        with tempfile.TemporaryDirectory(prefix="admira-bootstrap-test-") as temporary:
            root = Path(temporary)
            shutil.copy2(DEPLOY / "bootstrap-control-plane.sh", root / "bootstrap-control-plane.sh")
            shutil.copy2(DEPLOY / ".env.example", root / ".env.example")
            tools = root / "bin"
            tools.mkdir()
            docker = tools / "docker"
            docker.write_text("#!/bin/sh\nexit 0\n")
            docker.chmod(0o700)
            environment = {**os.environ, "PATH": str(tools) + os.pathsep + os.environ["PATH"]}
            command = ["bash", str(root / "bootstrap-control-plane.sh")]
            first = subprocess.run(command, env=environment, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            secret = root / "secrets/operator_db_password.txt"
            generated = secret.read_text()
            self.assertGreaterEqual(len(generated.strip()), 32)
            self.assertEqual(stat.S_IMODE(secret.stat().st_mode), 0o600)
            directory = root / "secrets/operator-password"
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            self.assertFalse((directory / "password.hash").exists())
            second = subprocess.run(command, env=environment, capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(secret.read_text(), generated)
            self.assertNotIn(generated.strip(), first.stdout + first.stderr + second.stdout + second.stderr)

    @unittest.skipIf(os.geteuid() == 0, "secret bootstrap deliberately requires a non-root service user")
    def test_bootstrap_refuses_secret_symlink_without_changing_target(self):
        with tempfile.TemporaryDirectory(prefix="admira-bootstrap-test-") as temporary:
            root = Path(temporary)
            shutil.copy2(DEPLOY / "bootstrap-control-plane.sh", root / "bootstrap-control-plane.sh")
            (root / "secrets").mkdir(mode=0o700)
            target = root / "must-preserve.txt"
            write_private(target, "fixture-do-not-change")
            (root / "secrets/operator_db_password.txt").symlink_to(target)
            result = subprocess.run(["bash", str(root / "bootstrap-control-plane.sh")],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing unsafe", result.stderr)
            self.assertEqual(target.read_text(), "fixture-do-not-change")


class OperatorPasswordTests(PrivateFixture):
    def test_first_setup_creates_private_hash_revokes_bootstrap_and_requires_login(self):
        token, csrf = self.state.bootstrap()
        self.assertIsNone(self.state.session(token))
        self.state.setup(PASSWORD, PASSWORD, token, csrf)
        encoded = self.password_file.read_text()
        self.assertNotIn(PASSWORD, encoded)
        self.assertEqual(stat.S_IMODE(self.password_file.stat().st_mode), 0o600)
        self.assertTrue(dashboard._password_matches(PASSWORD, encoded.strip()))
        self.assertFalse(self.state.setup_required())
        self.assertIsNone(self.state.session(token))
        login, _csrf = self.state.authenticate(PASSWORD, "127.0.0.1")
        self.assertIsNotNone(self.state.session(login))
        with self.assertRaises(PermissionError):
            self.state.setup(PASSWORD, PASSWORD, token, csrf)

    def test_first_setup_requires_csrf_strong_matching_password_and_fresh_token(self):
        token, csrf = self.state.bootstrap()
        for password, confirmation in (("short", "short"), (PASSWORD, PASSWORD + "wrong")):
            with self.assertRaises(ValueError):
                self.state.setup(password, confirmation, token, csrf)
        with self.assertRaises(PermissionError):
            self.state.setup(PASSWORD, PASSWORD, token, "wrong-csrf")
        self.now += dashboard.BOOTSTRAP_TTL + 1
        with self.assertRaises(PermissionError):
            self.state.setup(PASSWORD, PASSWORD, token, csrf)
        self.assertFalse(self.password_file.exists())

    def test_existing_invalid_hash_does_not_reopen_setup(self):
        write_private(self.password_file, "")
        self.assertFalse(self.state.setup_required())
        with self.assertRaises(PermissionError):
            self.state.authenticate(PASSWORD, "127.0.0.1")
        with self.assertRaises(PermissionError):
            self.state.bootstrap()

    def test_password_file_cannot_be_symlink_world_readable_or_hardlink(self):
        self.configured_password()
        link = self.password_root / "linked.hash"
        link.symlink_to(self.password_file)
        with self.assertRaises(RuntimeError):
            dashboard._private_file(link)
        self.password_file.chmod(0o644)
        with self.assertRaises(RuntimeError):
            dashboard._private_file(self.password_file)
        self.password_file.chmod(0o600)
        os.link(self.password_file, self.password_root / "hardlink.hash")
        with self.assertRaises(RuntimeError):
            dashboard._private_file(self.password_file)

    def test_login_backoff_session_expiry_logout_and_mutation_rate_limit(self):
        self.configured_password()
        with self.assertRaisesRegex(PermissionError, "invalid_login"):
            self.state.authenticate("wrong", "127.0.0.1")
        with self.assertRaisesRegex(PermissionError, "login_backoff"):
            self.state.authenticate(PASSWORD, "127.0.0.1")
        self.now += 3
        token, _csrf = self.state.authenticate(PASSWORD, "127.0.0.1")
        self.now += dashboard.LOGIN_TTL + 1
        self.assertIsNone(self.state.session(token))
        token, _csrf = self.state.authenticate(PASSWORD, "127.0.0.1")
        self.state.logout(token)
        self.assertIsNone(self.state.session(token))
        self.assertTrue(all(self.state.allow_mutation("127.0.0.1") for _ in range(30)))
        self.assertFalse(self.state.allow_mutation("127.0.0.1"))
        self.now += 61
        self.assertTrue(self.state.allow_mutation("127.0.0.1"))


class OperatorProviderTests(PrivateFixture):
    def test_gemini_key_is_stored_privately_never_passed_to_database_or_response(self):
        cursor = mock.MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.fetchone.return_value = ("00000000-0000-0000-0000-000000000001",)
        connection = mock.MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor
        self.state.connect = lambda: connection
        with mock.patch.object(dashboard, "check_gemini_api_key", return_value=True):
            response = self.state.register_gemini(KEY, "fixture-project", 2)
        self.assertNotIn(KEY, json.dumps(response))
        self.assertNotIn(KEY, repr(cursor.execute.call_args_list))
        self.assertEqual(cursor.execute.call_count, 2)
        self.assertIn("register_gemini_pool_project", cursor.execute.call_args_list[0].args[0])
        self.assertIn("register_gemini_pool_credential", cursor.execute.call_args_list[1].args[0])
        stored = list(self.gemini_root.glob("*.key"))
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].read_text(), KEY)
        self.assertEqual(stat.S_IMODE(stored[0].stat().st_mode), 0o600)
        connection.commit.assert_called_once()

    def test_gemini_health_failure_never_stores_or_registers(self):
        self.state.connect = mock.Mock()
        with mock.patch.object(dashboard, "check_gemini_api_key", return_value=False):
            with self.assertRaises(ValueError):
                self.state.register_gemini(KEY, "fixture-project", 2)
        self.assertEqual(list(self.gemini_root.iterdir()), [])
        self.state.connect.assert_not_called()

    def test_gemini_status_reads_security_definer_projection_only(self):
        cursor = mock.MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.fetchall.return_value = [("fixture-project", 2, "healthy", datetime.now(timezone.utc))]
        connection = mock.MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor
        self.state.connect = lambda: connection
        result = self.state.gemini_status()
        self.assertIn("admira.operator_gemini_pool_status()", cursor.execute.call_args.args[0])
        self.assertNotIn("FROM admira.gemini_pool_projects", cursor.execute.call_args.args[0])
        self.assertEqual(set(result[0]), {"project_ref", "capacity", "health", "health_checked_at"})

    def test_codex_status_requires_real_private_token_shape_not_file_presence(self):
        path = self.auth_file()
        result = self.state.login.account_status()
        self.assertTrue(result[0]["authenticated"])
        self.assertNotIn("private-access-value", json.dumps(result))
        write_private(path, "{}")
        self.assertFalse(self.state.login.account_status()[0]["authenticated"])
        write_private(path, '{"OPENAI_API_KEY":"secret-api-key"}')
        self.assertFalse(self.state.login.account_status()[0]["authenticated"])

    def test_disconnect_preserves_other_slot_and_non_auth_files(self):
        primary, secondary = self.auth_file("primary"), self.auth_file("secondary")
        keep = self.codex_root / "primary" / "keep.txt"
        write_private(keep, "keep")
        self.state.login.disconnect("primary")
        self.assertFalse(primary.exists())
        self.assertTrue(secondary.exists())
        self.assertTrue(keep.exists())
        primary.symlink_to(secondary)
        with self.assertRaises(RuntimeError):
            self.state.login.disconnect("primary")
        self.assertTrue(secondary.exists())

    def test_device_output_is_allowlisted_and_query_tokens_are_not_relayed(self):
        text = "https://auth.openai.com/codex/device?token=private-token\n\x1b[1mABCD-EFGHI\x1b[0m\n"
        self.assertEqual(dashboard.CodexDeviceLoginManager._extract(text), (dashboard.DEVICE_URL, "ABCD-EFGHI"))
        for text in ("https://auth.openai.com.evil.test/codex/device\nABCD-EFGHI",
                     "https://auth.openai.com/authorize?token=private-token\nABCD-EFGHI",
                     "https://evil.test/codex/device\nABCD-EFGHI"):
            self.assertEqual(dashboard.CodexDeviceLoginManager._extract(text), ("", ""))

    def test_device_command_is_fixed_shell_false_and_credential_env_is_stripped(self):
        process = mock.MagicMock()
        process.poll.return_value = None
        process.returncode = None
        with mock.patch.object(dashboard.shutil, "which", return_value="/usr/local/bin/codex"), \
             mock.patch.object(dashboard.subprocess, "Popen", return_value=process) as popen, \
             mock.patch.object(dashboard.threading, "Thread"), \
             mock.patch.dict(os.environ, {"OPENAI_API_KEY": "private-openai", "GEMINI_API_KEY": KEY,
                                          "NODE_OPTIONS": "unsafe", "HTTP_PROXY": "unsafe"}):
            result = self.state.login.start("primary")
            repeated = self.state.login.start("primary")
            self.assertEqual(result["job_id"], repeated["job_id"])
            popen.assert_called_once()
            args, kwargs = popen.call_args
            self.assertEqual(args[0], ["/usr/local/bin/codex", "login", "--device-auth"])
            self.assertIs(kwargs["shell"], False)
            self.assertTrue(kwargs["start_new_session"])
            self.assertEqual(kwargs["umask"], 0o077)
            self.assertEqual(kwargs["env"]["CODEX_HOME"], str(self.codex_root / "primary"))
            for forbidden in ("OPENAI_API_KEY", "GEMINI_API_KEY", "NODE_OPTIONS", "HTTP_PROXY"):
                self.assertNotIn(forbidden, kwargs["env"])
            for invalid in ("../primary", "primary;id", "PRIMARY", "third", ["primary"]):
                with self.assertRaises(ValueError):
                    self.state.login.start(invalid)
        process.poll.return_value = 0
        process.returncode = 0
        for job in self.state.login.jobs.values():
            job.reader_done.set()
        self.state.login.cleanup()

    def test_device_expiry_kills_process_group_and_clears_code_without_polling_request(self):
        process = mock.MagicMock()
        process.pid = 12345678
        process.returncode = None
        process.poll.side_effect = lambda: process.returncode
        process.wait.side_effect = lambda **_kwargs: setattr(process, "returncode", -15)
        job = dashboard.LoginJob("job-fixture", "primary", process, self.now,
                                 url=dashboard.DEVICE_URL, code="ABCD-EFGHI", buffer="private-cli-output")
        job.reader_done.set()
        self.state.login.jobs[job.job_id] = job
        self.now += dashboard.LOGIN_JOB_TTL + 1
        with mock.patch.object(dashboard.os, "killpg") as killpg:
            self.state.login.cleanup()
        killpg.assert_called_once()
        result = self.state.login.status(job.job_id)
        self.assertEqual(result["phase"], "expired")
        self.assertEqual(result["ttl_seconds"], 0)
        self.assertFalse(result["running"])
        self.assertEqual((job.url, job.code, job.buffer), ("", "", ""))


class OperatorHTTPTests(PrivateFixture):
    def setUp(self):
        super().setUp()
        self.server = dashboard.create_server(self.state, host="127.0.0.1", port=0, cookie_secure=False)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        payload = json.dumps(body).encode() if body is not None else None
        request_headers = {"Content-Type": "application/json", **(headers or {})}
        connection.request(method, path, body=payload, headers=request_headers)
        response = connection.getresponse()
        result = (response.status, dict(response.getheaders()), response.read())
        connection.close()
        return result

    def login(self):
        self.configured_password()
        status, headers, body = self.request("POST", "/api/operator/login", {"password": PASSWORD})
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0], json.loads(body)["csrf_token"]

    def test_first_run_setup_is_cookie_csrf_protected_and_never_logs_in_bootstrap(self):
        status, headers, body = self.request("GET", "/api/operator/session")
        self.assertEqual(status, 200)
        session = json.loads(body)
        self.assertTrue(session["setup_required"])
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        for flag in ("HttpOnly", "SameSite=Strict", "Max-Age="):
            self.assertIn(flag, headers["Set-Cookie"])
        status, _headers, _body = self.request("POST", "/api/operator/setup",
                                              {"password": PASSWORD, "confirmation": PASSWORD}, {"Cookie": cookie})
        self.assertEqual(status, 403)
        self.assertFalse(self.password_file.exists())
        status, headers, body = self.request("POST", "/api/operator/setup",
                                            {"password": PASSWORD, "confirmation": PASSWORD},
                                            {"Cookie": cookie, "X-CSRF-Token": session["csrf_token"]})
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["authenticated"])
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        self.assertNotIn(PASSWORD, body.decode())
        status, _headers, _body = self.request("GET", "/api/operator/codex/status", headers={"Cookie": cookie})
        self.assertEqual(status, 401)
        status, _headers, _body = self.request("POST", "/api/operator/setup",
                                              {"password": PASSWORD, "confirmation": PASSWORD},
                                              {"Cookie": cookie, "X-CSRF-Token": session["csrf_token"]})
        self.assertEqual(status, 403)

    def test_mutations_require_login_csrf_same_origin_and_revoke_on_logout(self):
        status, _headers, _body = self.request("POST", "/api/operator/codex/login", {"account": "primary"})
        self.assertEqual(status, 401)
        cookie, csrf = self.login()
        status, _headers, _body = self.request("POST", "/api/operator/logout", {}, {"Cookie": cookie})
        self.assertEqual(status, 403)
        status, _headers, _body = self.request("POST", "/api/operator/logout", {},
            {"Cookie": cookie, "X-CSRF-Token": csrf, "Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        status, headers, _body = self.request("POST", "/api/operator/logout", {},
            {"Cookie": cookie, "X-CSRF-Token": csrf, "Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual(status, 200)
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        status, _headers, _body = self.request("GET", "/api/operator/codex/status", headers={"Cookie": cookie})
        self.assertEqual(status, 401)

    def test_host_and_fetch_site_reject_dns_rebinding_and_cross_site_requests(self):
        for headers in ({"Host": "attacker.example"}, {"Host": "127.0.0.1.evil.example"},
                        {"Sec-Fetch-Site": "cross-site"}, {"Origin": "null"}):
            status, _headers, body = self.request("GET", "/api/operator/session", headers=headers)
            self.assertEqual(status, 403)
            self.assertNotIn("csrf_token", body.decode())
        self.assertEqual(self.state.sessions, {})

    def test_setup_uses_actual_peer_and_never_trusts_forwarded_headers(self):
        self.server.RequestHandlerClass.setup_networks = (ipaddress.ip_network("192.0.2.1/32"),)
        status, _headers, body = self.request("GET", "/api/operator/session",
                                             headers={"X-Forwarded-For": "192.0.2.1", "X-Real-IP": "192.0.2.1"})
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error_code"], "setup_unavailable")
        self.assertEqual(self.state.sessions, {})

    def test_secure_cookie_option_and_security_headers(self):
        self.server.RequestHandlerClass.cookie_secure = True
        self.configured_password()
        status, headers, body = self.request("POST", "/api/operator/login", {"password": PASSWORD})
        self.assertEqual(status, 200)
        self.assertIn("; Secure", headers["Set-Cookie"])
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotIn(PASSWORD, body.decode())

    def test_api_failures_and_rate_limits_never_expose_provider_secret(self):
        cookie, csrf = self.login()
        with mock.patch.object(self.state, "register_gemini", side_effect=RuntimeError(KEY)):
            status, _headers, body = self.request("POST", "/api/operator/gemini/register",
                {"api_key": KEY, "project_ref": "fixture", "capacity": 2},
                {"Cookie": cookie, "X-CSRF-Token": csrf})
        self.assertEqual(status, 503)
        self.assertNotIn(KEY, body.decode())
        with mock.patch.object(self.state, "allow_mutation", return_value=False):
            status, headers, body = self.request("POST", "/api/operator/login", {"password": PASSWORD})
        self.assertEqual(status, 429)
        self.assertEqual(headers["Retry-After"], "60")
        self.assertNotIn(PASSWORD, body.decode())

    def test_json_request_body_is_bounded_and_static_routes_cannot_read_secrets(self):
        status, _headers, body = self.request("POST", "/api/operator/login",
                                             {"password": "X" * (dashboard.MAX_BODY + 1)})
        self.assertEqual(status, 413)
        self.assertNotIn("XXXX", body.decode())
        status, _headers, _body = self.request("POST", "/api/operator/login", {"password": PASSWORD},
                                              {"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        self.configured_password()
        for path in ("/../secrets/operator_db_password.txt", "/auth.json", "/%2e%2e/password.hash"):
            status, _headers, body = self.request("GET", path)
            self.assertIn(status, {401, 403, 404})
            self.assertNotIn(PASSWORD, body.decode())


if __name__ == "__main__":
    unittest.main()
