import unittest
import uuid
import os
import tempfile
from pathlib import Path

from deploy.contabo.recovery_service import (
    RecoveryDependencyError,
    RecoveryInputError,
    TelegramRecoveryService,
    parse_recovery_command,
    read_private_envelope_key,
)


class FakeRecoveryDb:
    def __init__(self):
        self.begin_calls = []
        self.confirm_calls = []
        self.used = set()
        self.expired = set()
        self.public_replies = []

    def begin_telegram_recovery(self, *args):
        self.begin_calls.append(args)
        return {"public_outcome": "recovery_pending"}

    def confirm_telegram_recovery(self, request_id, bot, chat, user, otp_hash):
        self.confirm_calls.append((request_id, bot, chat, user, otp_hash))
        if request_id in self.expired or request_id in self.used:
            return {"completed": False, "public_outcome": "recovery_failed"}
        self.used.add(request_id)
        return {"completed": True, "public_outcome": "recovery_completed"}

    def enqueue_public_reply(self, *args):
        self.public_replies.append(args)
        return {"public_outcome": args[-1]}


@unittest.skipUnless(__import__("importlib").util.find_spec("cryptography"), "cryptography is a deployment dependency")
class RecoveryServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeRecoveryDb()
        self.service = TelegramRecoveryService(self.db, b"h" * 32, b"e" * 32)

    def test_commands_are_narrow_and_unbound_safe(self):
        self.assertEqual(parse_recovery_command("/recuperar" ).command, "/recuperar")
        self.assertEqual(parse_recovery_command("/codigo 123456").argument, "123456")
        self.assertEqual(parse_recovery_command("/recuperar@admiraia_bot").command, "/recuperar")
        self.assertIsNone(parse_recovery_command("/start"))
        self.assertIsNone(parse_recovery_command("/recuperar extra\nforged"))

    def test_unbound_orchestration_is_idempotent_and_never_returns_factors(self):
        first = self.service.handle_unbound(
            update_id=77, bot_id="123", chat_id="44", user_id="9",
            text="/recuperar User@Example.com Axxxxxxxxxxxxxxx",
        )
        second = self.service.handle_unbound(
            update_id=77, bot_id="123", chat_id="44", user_id="9",
            text="/recuperar User@Example.com Axxxxxxxxxxxxxxx",
        )
        self.assertEqual(first["request_id"], second["request_id"])
        self.assertNotIn("example.com", repr(first))
        self.assertNotIn("Axxxxxxxxxxxxxxx", repr(first))
        self.assertIsNone(self.service.handle_unbound(
            update_id=78, bot_id="123", chat_id="44", user_id="9", text="hola",
        ))

    def test_incomplete_and_malformed_commands_queue_only_safe_public_replies(self):
        instructions = self.service.handle_unbound(
            update_id=80, bot_id="123", chat_id="44", user_id="9", text="/recuperar",
        )
        failed = self.service.handle_unbound(
            update_id=81, bot_id="123", chat_id="44", user_id="9", text="/codigo nope 123456",
        )
        self.assertEqual(instructions["public_outcome"], "recovery_instructions")
        self.assertEqual(failed["public_outcome"], "recovery_failed")
        self.assertEqual([row[-1] for row in self.db.public_replies], [
            "recovery_instructions", "recovery_failed",
        ])

    def test_begin_encrypts_otp_and_only_sends_hmacs_to_adapter(self):
        rid = uuid.uuid4()
        result = self.service.begin(request_id=rid, bot_id="123", chat_id="-44", user_id="9",
                                    email=" User@Example.COM ", license_id="A" + "x" * 15)
        self.assertEqual(result, {"request_id": str(rid), "public_outcome": "recovery_pending"})
        call = self.db.begin_calls[0]
        self.assertEqual(call[0:4], (rid, "123", "-44", "9"))
        self.assertTrue(all(isinstance(value, str) for value in call[4:7]))
        self.assertNotIn("example.com", repr(call))
        self.assertNotIn("Axxxxxxxxxxxxxxx", repr(call))
        delivery = self.service.decrypt_delivery_envelope(rid, call[7])
        self.assertEqual(delivery["email"], "user@example.com")
        otp = delivery["otp"]
        self.assertRegex(otp, r"^[0-9]{6}$")
        self.assertNotIn(otp, repr(result))

    def test_confirm_is_request_scoped_and_adapter_controls_expiry_and_replay(self):
        rid = uuid.uuid4()
        self.service.begin(request_id=rid, bot_id="123", chat_id="-44", user_id="9",
                           email="u@example.com", license_id="A" + "x" * 15)
        otp = self.service.decrypt_delivery_envelope(rid, self.db.begin_calls[0][7])["otp"]
        self.assertTrue(self.service.confirm(request_id=rid, bot_id="123", chat_id="-44", user_id="9", otp=otp)["completed"])
        self.assertFalse(self.service.confirm(request_id=rid, bot_id="123", chat_id="-44", user_id="9", otp=otp)["completed"])
        expired = uuid.uuid4()
        self.service.begin(request_id=expired, bot_id="123", chat_id="-44", user_id="9",
                           email="u@example.com", license_id="A" + "x" * 15)
        expired_otp = self.service.decrypt_delivery_envelope(expired, self.db.begin_calls[-1][7])["otp"]
        self.db.expired.add(expired)
        self.assertFalse(self.service.confirm(request_id=expired, bot_id="123", chat_id="-44", user_id="9", otp=expired_otp)["completed"])

    def test_invalid_inputs_are_redacted(self):
        secret_email = "private-person@example.com"
        secret_license = "Z" * 16
        with self.assertRaises(RecoveryInputError) as ctx:
            self.service.begin(bot_id="bad", chat_id="-44", user_id="9", email=secret_email, license_id=secret_license)
        self.assertNotIn(secret_email, str(ctx.exception))
        self.assertNotIn(secret_license, str(ctx.exception))
        with self.assertRaises(RecoveryInputError):
            self.service.confirm(request_id="not-a-uuid", bot_id="123", chat_id="-44", user_id="9", otp="123456")
        with self.assertRaises(RecoveryInputError):
            self.service.decrypt_delivery_envelope(uuid.uuid4(), b"tampered")

    def test_envelope_key_requires_private_base64_32_bytes(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "key"
            path.write_bytes(__import__("base64").b64encode(b"k" * 32) + b"\n")
            os.chmod(path, 0o600)
            self.assertEqual(read_private_envelope_key(str(path)), b"k" * 32)
            os.chmod(path, 0o644)
            with self.assertRaises(RecoveryInputError):
                read_private_envelope_key(str(path))


if __name__ == "__main__":
    unittest.main()
