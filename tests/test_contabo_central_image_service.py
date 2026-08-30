import json
import hashlib
import inspect
import os
import socket
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from deploy.contabo.central_image_service import (CentralImageServer, EntitlementStore,
    PostgresCentralImageLedger, _private_password, central_codex_account_pool_from_env,
    central_codex_provider, postgres_connect_factory_from_env)
from deploy.contabo.central_codex_account_pool import CentralCodexAccountPool
from deploy.contabo.image_broker import ImageBroker, sign_request


PNG = b"\x89PNG\r\n\x1a\ncentral"


class CentralImageServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.tenants = root / "tenants"
        self.keys = root / "keys"
        self.tenants.mkdir()
        self.keys.mkdir(mode=0o700)
        self.key = b"k" * 32
        (self.tenants / "tenant-one" / "output").mkdir(parents=True)
        (self.keys / "tenant-one").write_bytes(self.key)
        (self.keys / "tenant-one").chmod(0o600)
        self.socket_path = root / "run" / "broker.sock"
        self.broker = ImageBroker(self.tenants, self.keys, lambda body, work: PNG,
                                  lambda tenant, purpose: "central_sponsored",
                                  max_global=2, freshness_seconds=30)
        self.server = CentralImageServer(self.broker, self.socket_path)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        for _ in range(100):
            if self.socket_path.exists():
                break
            time.sleep(0.01)

    def tearDown(self):
        self.server.close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    def envelope(self, request="request-001"):
        return sign_request(self.key, {
            "tenant_id": "tenant-one", "request_id": request, "prompt": "a test",
            "purpose": "image_generation", "aspect": "square", "references": [],
        }, timestamp=int(time.time()), nonce=hashlib.sha256(request.encode()).hexdigest())

    def request(self, payload):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(str(self.socket_path))
            client.sendall(json.dumps(payload).encode() + b"\n")
            return json.loads(client.makefile("rb").readline())

    def central_accounts(self):
        root = Path(self.tmp.name) / "central-auth"
        root.mkdir(mode=0o700, exist_ok=True)
        accounts = []
        for account_id in ("primary", "secondary"):
            home = root / account_id
            home.mkdir(mode=0o700, exist_ok=True)
            auth = home / "auth.json"
            auth.write_text("{}", encoding="utf-8")
            auth.chmod(0o600)
            accounts.append({"id": account_id, "codex_home": str(home)})
        return root, accounts

    def test_socket_permissions_and_success(self):
        self.assertTrue(stat.S_ISSOCK(self.socket_path.stat().st_mode))
        self.assertEqual(self.socket_path.stat().st_mode & 0o777, 0o660)
        result = self.request(self.envelope())
        self.assertTrue(result["ok"])
        self.assertNotIn("prompt", result)
        self.assertNotIn("stdout", result)

    def test_malformed_and_provider_errors_are_safe(self):
        self.assertEqual(self.request({}),
                         {"ok": False, "error_code": "invalid_request"})
        broker = ImageBroker(self.tenants, self.keys, lambda body, work: (_ for _ in ()).throw(RuntimeError("secret")),
                             lambda tenant, purpose: "central_sponsored")
        server = CentralImageServer(broker, self.socket_path.with_name("other.sock"))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        for _ in range(100):
            if server.socket_path.exists(): break
            time.sleep(0.01)
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(str(server.socket_path))
                client.sendall(json.dumps(self.envelope("request-err")).encode() + b"\n")
                result = json.loads(client.makefile("rb").readline())
            self.assertEqual(result, {"ok": False, "error_code": "provider_failed"})
            self.assertNotIn("secret", json.dumps(result))
        finally:
            server.close(); worker.join(timeout=2)

    def test_shutdown_removes_socket(self):
        self.server.close()
        self.thread.join(timeout=2)
        self.assertFalse(self.socket_path.exists())

    def test_connection_threads_are_bounded_and_overflow_fails_fast(self):
        entered = threading.Event()
        release = threading.Event()

        def slow_provider(body, work):
            entered.set()
            self.assertTrue(release.wait(timeout=2))
            return PNG

        broker = ImageBroker(
            self.tenants,
            self.keys,
            slow_provider,
            lambda tenant, purpose: "central_sponsored",
            freshness_seconds=30,
        )
        server = CentralImageServer(
            broker,
            self.socket_path.with_name("bounded.sock"),
            max_clients=1,
        )
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        for _ in range(100):
            if server.socket_path.exists():
                break
            time.sleep(0.01)

        first_result = []

        def first_request():
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(3)
                client.connect(str(server.socket_path))
                client.sendall(json.dumps(self.envelope("request-slow")).encode() + b"\n")
                first_result.append(json.loads(client.makefile("rb").readline()))

        first = threading.Thread(target=first_request)
        first.start()
        self.assertTrue(entered.wait(timeout=1))
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1)
                client.connect(str(server.socket_path))
                client.sendall(json.dumps(self.envelope("request-overflow")).encode() + b"\n")
                overflow = json.loads(client.makefile("rb").readline())
            self.assertEqual(overflow, {"ok": False, "error_code": "tenant_busy"})
            self.assertLessEqual(len(server._threads), 1)
        finally:
            release.set()
            first.join(timeout=3)
            server.close()
            worker.join(timeout=2)
        self.assertEqual(len(first_result), 1)
        self.assertTrue(first_result[0]["ok"])

    def test_entitlement_store_fails_closed(self):
        self.assertEqual(EntitlementStore(lambda tenant: "central_sponsored")("x", "image_generation"), "central_sponsored")
        self.assertEqual(EntitlementStore(lambda tenant: (_ for _ in ()).throw(RuntimeError()))("x", "image_generation"), "blocked")
        self.assertEqual(EntitlementStore(lambda tenant: "central_sponsored")("x", "other"), "blocked")

    def test_ledger_uses_durable_functions_and_closes_each_connection(self):
        calls = []
        class Tx:
            def __enter__(self): return self
            def __exit__(self, *args): pass
        class Cursor:
            description = []
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def execute(self, sql, params): calls.append((sql, params))
            def fetchone(self): return None
        class Conn:
            closed = False
            def transaction(self): return Tx()
            def cursor(self): return Cursor()
            def close(self): self.closed = True
        conns = []
        def connect():
            conn = Conn(); conns.append(conn); return conn
        ledger = PostgresCentralImageLedger(connect)
        ledger.begin("tenant-one", "12345678-1234-4234-8234-123456789012")
        ledger.fail("job", "lease", "provider_failed")
        self.assertEqual(len(conns), 2)
        self.assertTrue(all(conn.closed for conn in conns))
        self.assertIn("begin_central_image_job_for_runtime", calls[0][0])
        self.assertNotIn("central image", calls[0][0].lower())
        self.assertEqual(calls[0][1][0], "tenant-one")

    def test_ledger_maps_persisted_result_and_fencing_boolean(self):
        responses = iter([
            {
                "route": "central_sponsored", "status": "succeeded",
                "job_id": "job-1", "lease_token": None,
                "output_ref": "a" * 32 + ".jpg", "output_sha256": "b" * 64,
                "output_size_bytes": 42, "error_code": None,
            },
            {"completed": True},
        ])
        calls = []

        class Tx:
            def __enter__(self): return self
            def __exit__(self, *_): return False
        class Cursor:
            description = [object()]
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def execute(self, sql, params): calls.append((sql, params))
            def fetchone(self): return next(responses)
        class Connection:
            def transaction(self): return Tx()
            def cursor(self): return Cursor()
            def close(self): pass

        ledger = PostgresCentralImageLedger(Connection)
        recovered = ledger.begin("tenant-one", "12345678-1234-4234-8234-123456789012")
        self.assertEqual(recovered["status"], "succeeded")
        self.assertEqual(recovered["result"]["output_ref"], "a" * 32 + ".jpg")
        self.assertTrue(ledger.complete("job-1", "lease-1", {
            "output_ref": "c" * 32 + ".jpg", "sha256": "d" * 64, "size": 43,
        }))
        self.assertEqual(calls[-1][1][-1], "image/jpeg")

    def test_main_wires_ledger_inside_broker_once(self):
        from deploy.contabo import central_image_service as module
        source = inspect.getsource(module.main)
        self.assertIn("ledger=ledger", source)
        self.assertIn("central_codex_account_pool_from_env()", source)
        self.assertIn("partial(central_codex_provider, pool=account_pool)", source)
        self.assertNotIn("CentralImageServer(broker, Path(args.socket), ledger=", source)

    def test_pool_from_env_requires_two_private_authenticated_homes(self):
        root, _ = self.central_accounts()
        old = dict(os.environ)
        try:
            os.environ["ADMIRA_CENTRAL_CODEX_AUTH_ROOT"] = str(root)
            os.environ["ADMIRA_CENTRAL_CODEX_ACCOUNT_IDS"] = "primary,secondary"
            pool = central_codex_account_pool_from_env()
            self.assertEqual([item.account_id for item in pool.accounts], ["primary", "secondary"])
            os.environ["ADMIRA_CENTRAL_CODEX_ACCOUNT_IDS"] = "primary"
            with self.assertRaisesRegex(RuntimeError, "central_codex_pool_invalid"):
                central_codex_account_pool_from_env()
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_production_provider_falls_back_without_exposing_account(self):
        _, accounts = self.central_accounts()
        calls = []

        def provider(prompt, **kwargs):
            calls.append(kwargs["codex_home"].name)
            if len(calls) == 1:
                return {"ok": False, "failure_category": "chatgpt_images_limit", "stderr": "secret"}
            output = kwargs["output_root"] / "central.png"
            output.write_bytes(PNG)
            return {"ok": True, "image_path": str(output), "account_id": "must-not-escape"}

        pool = CentralCodexAccountPool(accounts, provider=provider)
        result = central_codex_provider({"prompt": "x", "references": []}, Path(self.tmp.name), pool=pool)
        self.assertEqual(Path(result).read_bytes(), PNG)
        self.assertEqual(calls, ["primary", "secondary"])
        self.assertNotIn("primary", str(result))
        self.assertNotIn("secondary", str(result))

    def test_password_file_is_private_and_database_url_is_not_used(self):
        password = Path(self.tmp.name) / "db-password"
        password.write_text("s" * 48 + "\n")
        password.chmod(0o444)
        self.assertEqual(_private_password(password), "s" * 48)
        password.chmod(0o666)
        with self.assertRaisesRegex(RuntimeError, "database_password_file_invalid"):
            _private_password(password)
        password.chmod(0o444)
        old = dict(os.environ)
        old_psycopg = sys.modules.get("psycopg")
        class FakePsycopg:
            @staticmethod
            def connect(**kwargs): return kwargs
        try:
            sys.modules["psycopg"] = FakePsycopg
            os.environ.update({"ADMIRA_DB_PASSWORD_FILE": str(password), "ADMIRA_DB_USER": "admira_image_login",
                               "DATABASE_URL": "postgresql://should-not-be-read"})
            factory = postgres_connect_factory_from_env()
            self.assertTrue(callable(factory))
        finally:
            if old_psycopg is None: sys.modules.pop("psycopg", None)
            else: sys.modules["psycopg"] = old_psycopg
            os.environ.clear(); os.environ.update(old)

    def test_production_provider_does_not_leak_provider_exception(self):
        class FakeCodex:
            @staticmethod
            def call_codex_image_cli_direct(*args, **kwargs):
                raise RuntimeError("provider secret")
        previous = sys.modules.get("codex_brand_guides")
        sys.modules["codex_brand_guides"] = FakeCodex
        try:
            _, accounts = self.central_accounts()
            pool = CentralCodexAccountPool(accounts)
            with self.assertRaises(RuntimeError) as raised:
                central_codex_provider({"prompt": "x", "references": []}, Path(self.tmp.name), pool=pool)
            self.assertEqual(str(raised.exception), "provider_failed")
        finally:
            if previous is None:
                sys.modules.pop("codex_brand_guides", None)
            else:
                sys.modules["codex_brand_guides"] = previous


if __name__ == "__main__":
    unittest.main()
