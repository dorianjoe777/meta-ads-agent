import os
import socket
import smtplib
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from deploy.contabo.recovery_email_worker import ProviderError
from deploy.contabo.recovery_smtp import SMTPRecoveryEmailTransport


class SMTPRecoveryTransportTests(unittest.TestCase):
    def files(self, username="user", password="secret"):
        directory = tempfile.TemporaryDirectory()
        user = Path(directory.name) / "user"
        secret = Path(directory.name) / "password"
        user.write_text(username)
        secret.write_text(password)
        user.chmod(0o600)
        secret.chmod(0o600)
        self.addCleanup(directory.cleanup)
        return user, secret

    def transport(self, **kwargs):
        return SMTPRecoveryEmailTransport("smtp.example", 587, "Admira <no-reply@example.com>", security="starttls", **kwargs)

    def test_starttls_precedes_login_and_send(self):
        user, password = self.files()
        smtp = Mock()
        smtp_factory = Mock(return_value=smtp)
        transport = self.transport(username_file=user, password_file=password, smtp_factory=smtp_factory)
        transport.send("client@example.com", "Asunto", "áé texto")
        calls = [call[0] for call in smtp.method_calls]
        self.assertEqual(calls, ["ehlo", "starttls", "ehlo", "login", "send_message", "quit"])
        smtp.starttls.assert_called_once()
        self.assertIsInstance(smtp.starttls.call_args.kwargs["context"], ssl.SSLContext)
        smtp.login.assert_called_once_with("user", "secret")
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message.get_content_charset(), "utf-8")
        self.assertIn("áé texto", message.get_content())

    def test_ssl_uses_tls_constructor_and_does_not_starttls(self):
        smtp = Mock()
        factory = Mock(return_value=smtp)
        transport = SMTPRecoveryEmailTransport("smtp.example", 465, "from@example.com", security="ssl", smtp_factory=factory)
        transport.send("to@example.com", "Subject", "text")
        factory.assert_called_once()
        self.assertIn("context", factory.call_args.kwargs)
        smtp.starttls.assert_not_called()
        smtp.login.assert_not_called()

    def test_rejection_is_stable_and_redacted(self):
        smtp = Mock()
        smtp.send_message.side_effect = smtplib.SMTPDataError(550, b"recipient secret@example.com rejected")
        transport = self.transport(smtp_factory=Mock(return_value=smtp))
        with self.assertRaises(ProviderError) as raised:
            transport.send("secret@example.com", "Subject", "private body")
        self.assertEqual(raised.exception.error_code, "provider_rejected")
        self.assertNotIn("secret", repr(raised.exception))
        self.assertNotIn("private", repr(raised.exception))

    def test_timeout_classification(self):
        smtp = Mock()
        smtp.send_message.side_effect = socket.timeout("private timeout")
        with self.assertRaises(ProviderError) as raised:
            self.transport(smtp_factory=Mock(return_value=smtp)).send("to@example.com", "Subject", "text")
        self.assertEqual(raised.exception.error_code, "timeout")
        self.assertNotIn("private", repr(raised.exception))

    def test_retry_after_is_preserved_without_response_text(self):
        smtp = Mock()
        error = smtplib.SMTPResponseException(421, b"try later recipient@example.com")
        error.retry_after = 37
        smtp.send_message.side_effect = error
        with self.assertRaises(ProviderError) as raised:
            self.transport(smtp_factory=Mock(return_value=smtp)).send("to@example.com", "Subject", "body")
        self.assertEqual((raised.exception.error_code, raised.exception.retry_after), ("provider_unavailable", 37))
        self.assertNotIn("recipient", repr(raised.exception))

    def test_credentials_require_exact_private_files_and_no_symlink(self):
        user, password = self.files()
        password.chmod(0o644)
        with self.assertRaises(ValueError) as raised:
            self.transport(username_file=user, password_file=password, smtp_factory=Mock()).send("to@example.com", "s", "t")
        self.assertNotIn(str(password), str(raised.exception))
        password.chmod(0o600)
        link = Path(password.parent) / "link"
        link.symlink_to(password)
        with self.assertRaises(ValueError):
            self.transport(username_file=user, password_file=link).send("to@example.com", "s", "t")

    def test_security_is_mandatory(self):
        with self.assertRaises(ValueError):
            SMTPRecoveryEmailTransport("smtp.example", 25, "from@example.com", security="none")


if __name__ == "__main__":
    unittest.main()
