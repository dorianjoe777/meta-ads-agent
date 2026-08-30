import os
import stat
import tempfile
import unittest
from pathlib import Path

from deploy.contabo.recovery_identity import (
    email_digest,
    generate_otp,
    license_digest,
    normalize_email,
    otp_digest,
    read_private_hmac_key,
    validate_license,
    verify_otp,
)


class RecoveryIdentityTests(unittest.TestCase):
    KEY = b"k" * 64

    def test_email_v1_normalizes_nfkc_ascii_local_and_idna_domain(self):
        self.assertEqual(normalize_email("  User@BÜCHER.Example  "), "user@xn--bcher-kva.example")
        self.assertEqual(normalize_email("ＡＬＩＣＥ@Example.COM"), "alice@example.com")

    def test_email_rejects_malformed_boundary_unicode_and_control_values(self):
        valid = "a" * 64 + "@" + "b" * 63 + ".com"
        self.assertEqual(normalize_email(valid), valid)
        for value in (
            "",
            "a" * 65 + "@example.com",
            "a..b@example.com",
            ".a@example.com",
            "a.@example.com",
            "a b@example.com",
            "a\u0000@example.com",
            "a@@example.com",
            "a@",
            "a@example",
            "a@-example.com",
            "a@example-.com",
            "a@" + "b" * 64 + ".com",
            "a@a..com",
            "a@example.com\nextra",
        ):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    normalize_email(value)

    def test_license_matches_provider_admin_format_without_echoing_input(self):
        self.assertEqual(validate_license("A" + "_" * 15), "A" + "_" * 15)
        self.assertEqual(validate_license("z" * 128), "z" * 128)
        for value in ("short", "a" * 129, "license with spaces", "é" * 16, ""):
            with self.assertRaisesRegex(ValueError, "recovery identity is invalid") as raised:
                validate_license(value)
            if value:
                self.assertNotIn(value, str(raised.exception))

    def test_private_key_requires_exact_0600_regular_file_and_no_symlink(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            key = root / "key"
            key.write_bytes(self.KEY)
            key.chmod(0o600)
            self.assertEqual(read_private_hmac_key(key), self.KEY)
            key.chmod(0o640)
            with self.assertRaises(ValueError):
                read_private_hmac_key(key)
            key.chmod(0o600)
            public = root / "public"
            public.write_bytes(self.KEY)
            public.chmod(0o644)
            with self.assertRaises(ValueError):
                read_private_hmac_key(public)
            link = root / "link"
            link.symlink_to(key)
            with self.assertRaises(ValueError):
                read_private_hmac_key(link)

    def test_digests_are_32_bytes_deterministic_and_domain_separated(self):
        self.assertEqual(len(email_digest(self.KEY, "User@Example.com")), 32)
        self.assertEqual(len(license_digest(self.KEY, "A" + "b" * 15)), 32)
        self.assertEqual(email_digest(self.KEY, "User@Example.com"), email_digest(self.KEY, "user@example.com"))
        self.assertNotEqual(email_digest(self.KEY, "user@example.com"), license_digest(self.KEY, "a" + "b" * 15))

    def test_otp_is_fixed_width_request_scoped_and_constant_time_verified(self):
        values = {generate_otp() for _ in range(100)}
        self.assertTrue(values)
        self.assertTrue(all(len(value) == 6 and value.isascii() and value.isdecimal() for value in values))
        otp = next(iter(values))
        first = otp_digest(self.KEY, "request-1", otp)
        self.assertEqual(len(first), 32)
        self.assertTrue(verify_otp(self.KEY, "request-1", otp, first))
        self.assertFalse(verify_otp(self.KEY, "request-2", otp, first))
        self.assertFalse(verify_otp(self.KEY, "request-1", "000000", first))
        with self.assertRaises(ValueError):
            otp_digest(self.KEY, "request-1", otp + "0")


if __name__ == "__main__":
    unittest.main()
