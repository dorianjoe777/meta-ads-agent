from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "contabo" / "build-hosted-runtime.sh"


class HostedRuntimeBuildContractTests(unittest.TestCase):
    def test_script_is_valid_shell(self):
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_script_enforces_clean_provenance_and_separate_hosted_tag(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("git diff --quiet", source)
        self.assertIn("git ls-files --others --exclude-standard", source)
        self.assertIn("ADMIRA_HOSTED_IMAGE_REPOSITORY:-admira-ia-hosted", source)
        self.assertIn('tag="${version}-canary-${short_sha}"', source)
        self.assertNotIn("ADMIRA_HOSTED_TAG", source)
        self.assertNotIn("ADMIRA_HOSTED_CHANNEL", source)
        self.assertIn('actual_channel', source)
        self.assertIn('[[ "$actual_channel" == canary ]]', source)
        self.assertIn("hosted-shared-vps", source)
        self.assertIn("ADMIRA_SOURCE_MANIFEST=${manifest}", source)
        self.assertIn("org.opencontainers.image.source-manifest", source)
        self.assertIn("same committed r99 product source and Dockerfile", source)
        self.assertIn('[[ "$version" == r99 ]]', source)
        self.assertIn("Hosted r99 builder requires VERSION=r99", source)
        self.assertIn('if [[ "$inspect_only" != true ]]; then', source)
        self.assertIn("provenance contract inspected (Docker build not run)", source)


if __name__ == "__main__":
    unittest.main()
