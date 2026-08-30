import random
import unittest

from deploy.contabo.recovery_email_worker import (
    DELIVERY_REF, TEMPLATE_CODE, ProviderError, RecoveryEmailItem,
    RecoveryEmailWorker,
)


class Store:
    def __init__(self, item):
        self.item, self.acks = item, []
        self.claims = []
    def claim_recovery_email_outbox(self, **kwargs):
        self.claims.append(kwargs)
        return [self.item] if self.item else []
    def ack_recovery_email_outbox(self, item, **kwargs):
        self.acks.append(kwargs)
        return False if getattr(self, "lose_lease", False) else True


class Transport:
    def __init__(self): self.calls = []
    def send(self, recipient, subject, text): self.calls.append((recipient, subject, text))


def item(**changes):
    value = dict(outbox="o1", challenge="c1",
                 request_id="123e4567-e89b-12d3-a456-426614174000",
                 delivery_ref=DELIVERY_REF,
                 template=TEMPLATE_CODE, ciphertext=b"sealed", key_version="v1",
                 attempts=1, lease="lease-1")
    value.update(changes)
    return RecoveryEmailItem(**value)


class RecoveryEmailWorkerTests(unittest.TestCase):
    def worker(self, value=None, transport=None, decrypt=None):
        store = Store(value or item())
        transport = transport or Transport()
        decrypt = decrypt or (lambda request_id, ciphertext: {
            "request_id": "123e4567-e89b-12d3-a456-426614174000",
            "email": "cliente@example.com", "otp": "123456"})
        return RecoveryEmailWorker(store, transport, decrypt, rng=random.Random(4)), store, transport

    def test_success_renders_spanish_command_and_ack_is_fenced(self):
        worker, store, transport = self.worker()
        self.assertEqual(worker.process_once(), {"sent": 1, "retried": 0, "rejected": 0})
        recipient, subject, text = transport.calls[0]
        self.assertEqual(recipient, "cliente@example.com")
        self.assertIn("/codigo 123e4567-e89b-12d3-a456-426614174000 123456", text)
        self.assertEqual(store.acks, [{"success": True}])

    def test_corrupt_envelope_is_terminal_and_redacted(self):
        secret = "private@example.com"
        worker, store, transport = self.worker(decrypt=lambda *_: (_ for _ in ()).throw(ValueError(secret)))
        self.assertEqual(worker.process_once(), {"sent": 0, "retried": 0, "rejected": 1})
        self.assertEqual(store.acks[0]["error_code"], "internal_error")
        self.assertEqual(store.acks[0]["max_attempts"], 1)
        self.assertFalse(transport.calls)
        self.assertNotIn(secret, repr(store.acks))

    def test_metadata_key_version_and_template_are_rejected(self):
        for changed in ({"delivery_ref": "secret://wrong"}, {"key_version": "v2"}, {"template": "other"}):
            worker, store, transport = self.worker(item(**changed))
            self.assertEqual(worker.process_once()["rejected"], 1)
            self.assertEqual(store.acks[0]["max_attempts"], 1)
            self.assertFalse(transport.calls)

    def test_decrypted_request_must_match_claimed_request(self):
        worker, store, transport = self.worker(decrypt=lambda *_: {
            "request_id": "223e4567-e89b-12d3-a456-426614174000",
            "email": "cliente@example.com", "otp": "123456",
        })
        self.assertEqual(worker.process_once()["rejected"], 1)
        self.assertEqual(store.acks[0]["max_attempts"], 1)
        self.assertFalse(transport.calls)

    def test_provider_failure_and_rate_limit_retry_with_allowed_code(self):
        for exception in (ProviderError("provider_unavailable"), ProviderError("rate_limited", 17)):
            transport = Transport()
            def send(*args, exc=exception): raise exc
            transport.send = send
            worker, store, _ = self.worker(transport=transport)
            self.assertEqual(worker.process_once(), {"sent": 0, "retried": 1, "rejected": 0})
            self.assertEqual(store.acks[0]["error_code"], "provider_unavailable")
            if exception.retry_after:
                self.assertEqual(store.acks[0]["retry_after_seconds"], 17)

    def test_lost_lease_is_not_reported_as_sent(self):
        worker, store, _ = self.worker()
        store.lose_lease = True
        self.assertEqual(worker.process_once(), {"sent": 0, "retried": 0, "rejected": 1})


if __name__ == "__main__": unittest.main()
