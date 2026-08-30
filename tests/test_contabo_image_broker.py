import hashlib
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy.contabo.image_broker import ImageBroker, sign_request


PNG = b"\x89PNG\r\n\x1a\n" + b"payload"

class FakeLedger:
    def __init__(self, status="running"):
        self.status = status; self.route = "central_sponsored"; self.result = None; self.complete_calls = []; self.fail_calls = []
    def begin(self, tenant_id, request_id):
        if self.status == "succeeded": return {"route":self.route, "status":"succeeded", "result":self.result}
        if self.status == "busy": return {"route":self.route, "status":"running"}
        return {"route":self.route, "status":self.status, "lease":"lease-1", "job_id":"job-1"}
    def complete(self, job_id, lease, result):
        self.complete_calls.append((job_id, lease, result)); self.result=dict(result)
        if getattr(self, "fence", False): return False
        if getattr(self, "complete_error", False):
            raise RuntimeError("database connection lost after commit attempt")
        self.status = "succeeded"; return True
    def fail(self, job_id, lease, error): self.fail_calls.append((job_id, lease, error))


class ImageBrokerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.tenants = root / "tenants"
        self.keys = root / "keys"
        self.tenants.mkdir()
        self.keys.mkdir()
        self.keys.chmod(0o700)
        self.key = b"k" * 32
        for tenant in ("tenant-one", "tenant-two"):
            output = self.tenants / tenant / "output"
            output.mkdir(parents=True)
            (self.keys / tenant).write_bytes(self.key)
            (self.keys / tenant).chmod(0o600)
        self.broker = ImageBroker(self.tenants, self.keys, lambda body, work: PNG,
                                  lambda tenant, purpose: "central_sponsored",
                                  max_per_tenant=2, max_global=2, freshness_seconds=30)

    def tearDown(self):
        self.tmp.cleanup()

    def envelope(self, tenant="tenant-one", request="request-001", **overrides):
        body = {"tenant_id": tenant, "request_id": request, "prompt": "a test",
                "purpose": "image_generation", "aspect": "square", "references": []}
        body.update(overrides)
        return sign_request(self.key, body, timestamp=1000,
                            nonce=hashlib.sha256(request.encode()).hexdigest())

    def test_success_is_opaque_and_has_digest(self):
        result = self.broker.submit(self.envelope(), now=1000)
        self.assertTrue(result["ok"])
        self.assertNotIn("/", result["output_ref"])
        self.assertEqual(result["size"], len(PNG))
        self.assertEqual(result["sha256"], hashlib.sha256(PNG).hexdigest())
        output = self.tenants / "tenant-one" / "output" / result["output_ref"]
        self.assertEqual(output.read_bytes(), PNG)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_idempotency_with_new_nonce(self):
        first = self.broker.submit(self.envelope(), now=1000)
        second = self.broker.submit(sign_request(self.key, self.envelope()["body"],
                                                  timestamp=1000, nonce="b" * 32), now=1000)
        self.assertEqual(first, second)

    def test_replay_and_freshness_and_signature(self):
        env = self.envelope()
        self.assertEqual(self.broker.submit(env, now=1000)["ok"], True)
        self.assertEqual(self.broker.submit(env, now=1000)["error_code"], "replayed_request")
        expired = self.envelope(request="request-002")
        self.assertEqual(self.broker.submit(expired, now=1031)["error_code"], "expired_request")
        bad = self.envelope(request="request-003")
        bad["signature"] = "0" * 64
        self.assertEqual(self.broker.submit(bad, now=1000)["error_code"], "invalid_signature")

    def test_entitlement_is_server_side(self):
        for decision, expected in (("blocked", "entitlement_blocked"),
                                   ("personal_chatgpt", "personal_provider_required"),
                                   ("unexpected", "entitlement_blocked")):
            broker = ImageBroker(self.tenants, self.keys, lambda body, work: PNG,
                                 lambda tenant, purpose, d=decision: d)
            result = broker.submit(self.envelope(request="req-" + decision), now=1000)
            self.assertEqual(result["error_code"], expected)

    def test_relative_reference_and_traversal_and_symlink_rejected(self):
        output = self.tenants / "tenant-one" / "output"
        (output / "input.png").write_bytes(PNG)
        good = self.broker.submit(self.envelope(request="request-ref1", references=["input.png"]), now=1000)
        self.assertTrue(good["ok"])
        for index, ref in enumerate(("../input.png", "/etc/passwd", "missing.png")):
            result = self.broker.submit(self.envelope(request=f"request-ref-{index + 2:02d}", references=[ref]), now=1000)
            self.assertEqual(result["error_code"], "reference_invalid")
        outside = Path(self.tmp.name) / "outside"
        outside.write_bytes(PNG)
        (output / "link.png").symlink_to(outside)
        result = self.broker.submit(self.envelope(request="request-link1", references=["link.png"]), now=1000)
        self.assertEqual(result["error_code"], "reference_invalid")

    def test_reference_limit_is_cumulative(self):
        output = self.tenants / "tenant-one" / "output"
        (output / "one.png").write_bytes(PNG)
        (output / "two.png").write_bytes(PNG)
        import deploy.contabo.image_broker as module
        original = module.MAX_REFERENCE_BYTES
        module.MAX_REFERENCE_BYTES = len(PNG) + 1
        try:
            result = self.broker.submit(
                self.envelope(request="request-total", references=["one.png", "two.png"]), now=1000
            )
        finally:
            module.MAX_REFERENCE_BYTES = original
        self.assertEqual(result["error_code"], "reference_invalid")

    def test_provider_receives_private_reference_snapshot(self):
        output = self.tenants / "tenant-one" / "output"
        (output / "input.png").write_bytes(PNG)
        seen = []

        def provider(body, work):
            reference = Path(body["references"][0])
            seen.append((reference, stat.S_IMODE(reference.stat().st_mode), reference.read_bytes()))
            return PNG

        broker = ImageBroker(self.tenants, self.keys, provider,
                             lambda tenant, purpose: "central_sponsored")
        result = broker.submit(self.envelope(request="request-snapshot", references=["input.png"]), now=1000)
        self.assertTrue(result["ok"])
        reference, mode, contents = seen[0]
        self.assertEqual(contents, PNG)
        self.assertEqual(mode, 0o600)
        self.assertFalse(str(reference).startswith(str(self.tenants)))
        self.assertTrue(reference.is_absolute())

    def test_reference_swap_at_snapshot_boundary_cannot_escape(self):
        output = self.tenants / "tenant-one" / "output"
        reference = output / "input.png"
        reference.write_bytes(PNG)
        outside = Path(self.tmp.name) / "outside.png"
        outside.write_bytes(b"not the tenant input")
        import deploy.contabo.image_broker as module
        original = module._snapshot_references

        def snapshot_then_swap(root, refs, work):
            snapshots = original(root, refs, work)
            reference.unlink()
            reference.symlink_to(outside)
            return snapshots

        seen = []
        broker = ImageBroker(
            self.tenants, self.keys,
            lambda body, work: seen.append(Path(body["references"][0]).read_bytes()) or PNG,
            lambda tenant, purpose: "central_sponsored",
        )
        try:
            module._snapshot_references = snapshot_then_swap
            result = broker.submit(self.envelope(request="request-swap", references=["input.png"]), now=1000)
        finally:
            module._snapshot_references = original
        self.assertTrue(result["ok"])
        self.assertEqual(seen, [PNG])

    def test_reference_swapped_to_symlink_before_secure_open_is_rejected(self):
        output = self.tenants / "tenant-one" / "output"
        reference = output / "input.png"
        reference.write_bytes(PNG)
        outside = Path(self.tmp.name) / "outside.png"
        outside.write_bytes(b"cross-tenant-bytes-must-not-be-read")
        import deploy.contabo.image_broker as module
        secure_open = module._open_output_reference
        provider_called = []

        def swap_then_open(root, relative):
            reference.unlink()
            reference.symlink_to(outside)
            return secure_open(root, relative)

        broker = ImageBroker(
            self.tenants, self.keys,
            lambda body, work: provider_called.append(True) or PNG,
            lambda tenant, purpose: "central_sponsored",
        )
        with patch.object(module, "_open_output_reference", side_effect=swap_then_open):
            result = broker.submit(
                self.envelope(request="request-open-race", references=["input.png"]),
                now=1000,
            )
        self.assertEqual(result["error_code"], "reference_invalid")
        self.assertEqual(provider_called, [])

    def test_provider_workdir_is_not_tenant_visible(self):
        seen = []
        broker = ImageBroker(
            self.tenants, self.keys,
            lambda body, work: seen.append(work) or PNG,
            lambda tenant, purpose: "central_sponsored",
        )
        self.assertTrue(broker.submit(self.envelope(request="request-private-work"), now=1000)["ok"])
        self.assertFalse(str(seen[0]).startswith(str(self.tenants)))

    def test_provider_path_must_stay_inside_workdir(self):
        outside = Path(self.tmp.name) / "outside.png"
        outside.write_bytes(PNG)
        broker = ImageBroker(self.tenants, self.keys, lambda body, work: outside,
                             lambda tenant, purpose: "central_sponsored")
        result = broker.submit(self.envelope(request="request-out1"), now=1000)
        self.assertEqual(result["error_code"], "output_invalid")

    def test_bad_magic_and_size_are_safe_errors(self):
        for data, expected in ((b"not image", "output_invalid"), (PNG + b"x", "output_too_large")):
            broker = ImageBroker(self.tenants, self.keys, lambda body, work, d=data: d,
                                 lambda tenant, purpose: "central_sponsored", max_image_bytes=len(PNG) if expected == "output_too_large" else 100)
            result = broker.submit(self.envelope(request="request-bad" + expected[-2:]), now=1000)
            self.assertEqual(result["error_code"], expected)

    def test_global_provider_limit_applies_across_tenants(self):
        active = 0
        peak = 0
        lock = threading.Lock()
        release = threading.Event()

        def provider(body, work):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            release.wait(2)
            with lock:
                active -= 1
            return PNG

        broker = ImageBroker(self.tenants, self.keys, provider,
                             lambda tenant, purpose: "central_sponsored",
                             max_per_tenant=2, max_global=2)
        results = []
        threads = [threading.Thread(target=lambda t=t, i=i: results.append(
            broker.submit(self.envelope(tenant=t, request=f"request-{i:04d}"), now=1000)))
                   for i, t in enumerate(("tenant-one", "tenant-one", "tenant-two", "tenant-two"))]
        for thread in threads:
            thread.start()
        time.sleep(.15)
        self.assertLessEqual(peak, 2)
        release.set()
        for thread in threads:
            thread.join(2)
        self.assertEqual(len(results), 4)
        self.assertTrue(all(result.get("ok") for result in results))

    def test_waiting_tenants_are_dispatched_round_robin(self):
        started: list[str] = []
        release_first = threading.Event()
        release_rest = threading.Event()

        def provider(body, work):
            started.append(str(body["request_id"]))
            if len(started) == 1:
                release_first.wait(2)
            else:
                release_rest.wait(2)
            return PNG

        broker = ImageBroker(self.tenants, self.keys, provider,
                             lambda tenant, purpose: "central_sponsored",
                             max_per_tenant=1, max_global=1)
        requests = [
            ("tenant-one", "tenant1-a"),
            ("tenant-one", "tenant1-b"),
            ("tenant-two", "tenant2-a"),
        ]
        threads = [threading.Thread(target=lambda t=t, r=r: broker.submit(
            self.envelope(tenant=t, request=r), now=1000)) for t, r in requests]
        threads[0].start()
        while len(started) < 1:
            time.sleep(.01)
        threads[1].start()
        time.sleep(.02)
        threads[2].start()
        time.sleep(.05)
        release_first.set()
        deadline = time.time() + 1
        while len(started) < 2 and time.time() < deadline:
            time.sleep(.01)
        self.assertEqual(started[:2], ["tenant1-a", "tenant2-a"])
        release_rest.set()
        for thread in threads:
            thread.join(2)
        self.assertEqual(started, ["tenant1-a", "tenant2-a", "tenant1-b"])

    def test_durable_ledger_idempotency_after_restart(self):
        ledger = FakeLedger()
        broker = ImageBroker(self.tenants, self.keys, lambda body, work: PNG,
                              lambda tenant, purpose: "central_sponsored", ledger=ledger)
        result = broker.submit(self.envelope(request="durable-001"), now=1000)
        self.assertTrue(result["ok"])
        restarted = ImageBroker(self.tenants, self.keys, lambda body, work: (_ for _ in ()).throw(AssertionError()),
                                lambda tenant, purpose: "central_sponsored", ledger=ledger)
        self.assertEqual(restarted.submit(self.envelope(request="durable-001"), now=1000), result)

    def test_durable_busy_does_not_call_provider(self):
        ledger = FakeLedger("busy")
        broker = ImageBroker(self.tenants, self.keys, lambda body, work: (_ for _ in ()).throw(AssertionError()),
                             lambda tenant, purpose: "central_sponsored", ledger=ledger)
        self.assertEqual(broker.submit(self.envelope(request="durable-002"), now=1000)["error_code"], "tenant_busy")

    def test_durable_ledger_route_is_authoritative(self):
        ledger = FakeLedger("running")
        ledger.route = "personal_chatgpt"
        broker = ImageBroker(
            self.tenants, self.keys,
            lambda body, work: (_ for _ in ()).throw(AssertionError()),
            # A permissive process-local callback must not override the DB
            # route returned by the durable begin operation.
            lambda tenant, purpose: "central_sponsored", ledger=ledger,
        )
        result = broker.submit(self.envelope(request="durable-route"), now=1000)
        self.assertEqual(result["error_code"], "personal_provider_required")

    def test_durable_fencing_deletes_output_and_fail_is_safe(self):
        ledger = FakeLedger("running"); ledger.fence = True
        broker = ImageBroker(self.tenants, self.keys, lambda body, work: PNG,
                             lambda tenant, purpose: "central_sponsored", ledger=ledger)
        result = broker.submit(self.envelope(request="durable-003"), now=1000)
        self.assertEqual(result["error_code"], "provider_failed")
        self.assertEqual(len(ledger.complete_calls), 1)
        self.assertEqual(list((self.tenants / "tenant-one" / "output").iterdir()), [])
        ledger.status = "running"
        bad = ImageBroker(self.tenants, self.keys, lambda body, work: b"bad",
                          lambda tenant, purpose: "central_sponsored", ledger=ledger)
        self.assertEqual(bad.submit(self.envelope(request="durable-004"), now=1000)["error_code"], "output_invalid")
        self.assertEqual(ledger.fail_calls[-1][2], "output_invalid")

    def test_durable_complete_exception_never_leaves_uncommitted_output(self):
        ledger = FakeLedger("running")
        ledger.complete_error = True
        broker = ImageBroker(self.tenants, self.keys, lambda body, work: PNG,
                             lambda tenant, purpose: "central_sponsored", ledger=ledger)
        result = broker.submit(self.envelope(request="durable-db-error"), now=1000)
        self.assertEqual(result, {"ok": False, "error_code": "provider_failed"})
        self.assertEqual(list((self.tenants / "tenant-one" / "output").iterdir()), [])

    def test_durable_result_is_not_reused_after_fenced_attempt(self):
        ledger = FakeLedger("running")
        ledger.fence = True
        broker = ImageBroker(self.tenants, self.keys, lambda body, work: PNG,
                             lambda tenant, purpose: "central_sponsored", ledger=ledger)
        first = broker.submit(self.envelope(request="durable-fenced-retry"), now=1000)
        self.assertEqual(first["error_code"], "provider_failed")
        self.assertEqual(list((self.tenants / "tenant-one" / "output").iterdir()), [])
        # A later durable lookup with no committed output must fail closed;
        # it cannot expose a previous tenant/request's image.
        ledger.status = "succeeded"
        ledger.result = {"output_ref": "a" * 32 + ".png", "sha256": "0" * 64, "size": len(PNG)}
        retry = broker.submit(sign_request(self.key, self.envelope(request="durable-fenced-retry")["body"],
                                           timestamp=1000, nonce="c" * 32), now=1000)
        self.assertEqual(retry["error_code"], "output_invalid")


if __name__ == "__main__":
    unittest.main()
