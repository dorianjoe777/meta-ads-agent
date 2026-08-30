import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackageReleaseSecretGuardsTests(unittest.TestCase):
    def test_dockerignore_excludes_operational_secrets_but_keeps_examples(self):
        ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        for pattern in (
            "deploy/contabo/.env",
            "deploy/contabo/secrets/",
            "auth.json",
            "credentials.json",
            "token.json",
            "service-account.json",
            "client_secret.json",
            "*.pem",
            "*.key",
            "*.p8",
            "*.p12",
            "*.pfx",
            "*.crt",
            "*.cer",
            "*.der",
            "*.csr",
            "*.jks",
            "*.keystore",
            "*.mobileprovision",
        ):
            self.assertIn(pattern, ignore)
        self.assertNotIn(".env.example", ignore)

    def test_package_release_has_explicit_exclusions_and_staged_secret_scan(self):
        script = (ROOT / "scripts" / "package-release.sh").read_text(encoding="utf-8")
        for pattern in (
            '--exclude "deploy/contabo/.env"',
            '--exclude "deploy/contabo/secrets"',
            '--exclude "auth.json"',
            '--exclude "credentials.json"',
            '--exclude "token.json"',
            '--exclude "service-account.json"',
            '--exclude "client_secret.json"',
            '--exclude "*.pem"',
            '--exclude "*.key"',
            "private_key",
            "telegram_token",
            "gemini_key",
            "path.name.endswith(\".example\")",
        ):
            self.assertIn(pattern, script)


if __name__ == "__main__":
    unittest.main()
