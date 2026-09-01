from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "verify-canary-integrity.sh"


class CanaryIntegrityCheckerTests(unittest.TestCase):
    """Regression checks for portable mount parsing and exact tag provenance."""

    def test_six_named_mounts_parse_from_tab_delimited_docker_output(self):
        mounts = [
            ("/app/runtime", "meta_ads_test_config"),
            ("/app/dashboard/data", "meta_ads_test_data"),
            ("/app/dashboard/data/update-snapshots", "meta_ads_test_update_snapshots"),
            ("/app/output", "meta_ads_test_output"),
            ("/app/logs", "meta_ads_test_logs"),
            ("/app/brand_guides", "meta_ads_test_brand_guides"),
        ]
        docker_inspect_output = "".join(f"{destination}\t{name}\n" for destination, name in mounts)
        awk = "awk -F '\\t' -v wanted=DEST '$1 == wanted { print $2; exit }'"
        for destination, expected in mounts:
            result = subprocess.run(
                ["sh", "-c", awk.replace("DEST", destination)],
                input=docker_inspect_output,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertEqual(result.stdout.strip(), expected)
            self.assertNotIn("warning", result.stderr.lower())

    def test_wrong_mount_is_detectable(self):
        output = "/app/output\twrong_volume\n"
        result = subprocess.run(
            ["awk", "-F", "\t", "-v", "wanted=/app/output", "$1 == wanted { print $2; exit }"],
            input=output,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(result.stdout.strip(), "wrong_volume")
        self.assertNotEqual(result.stdout.strip(), "meta_ads_test_output")

    def test_checker_requires_tag_commit_to_equal_head(self):
        text = CHECKER.read_text(encoding="utf-8")
        self.assertIn('refs/tags/$version^{commit}', text)
        self.assertIn('[[ "$tag_commit" == "$commit_sha" ]]', text)

    def test_checker_uses_tabulated_mount_output(self):
        text = CHECKER.read_text(encoding="utf-8")
        self.assertIn('printf "%s\\t%s\\n" .Destination .Name', text)
        self.assertIn("awk -F '\\t'", text)
        self.assertNotIn("awk -F ' \\| '", text)

    def test_checker_requires_active_image_tag_to_match_version(self):
        text = CHECKER.read_text(encoding="utf-8")
        self.assertIn('image_without_digest="${image%@*}"', text)
        self.assertIn('image_leaf="${image_without_digest##*/}"', text)
        self.assertIn('[[ "$image_leaf" == *:* ]]', text)
        self.assertIn('[[ "$image_tag" == "$version" ]]', text)
        self.assertIn("active image tag", text)


if __name__ == "__main__":
    unittest.main()
