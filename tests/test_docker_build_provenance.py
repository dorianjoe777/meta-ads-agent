from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DockerBuildProvenanceTests(unittest.TestCase):
    def test_release_metadata_does_not_invalidate_dependency_layers(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        browser_layer = dockerfile.index("npx remotion browser ensure")
        release_args = dockerfile.index("ARG ADMIRA_BUILD_VERSION=unknown")
        source_copy = dockerfile.index("COPY . .")
        provenance_write = dockerfile.index("> /app/source-manifest.sha256")

        self.assertLess(browser_layer, release_args)
        self.assertLess(release_args, source_copy)
        self.assertLess(source_copy, provenance_write)
        self.assertIn(
            'org.opencontainers.image.source-manifest="${ADMIRA_SOURCE_MANIFEST}"',
            dockerfile,
        )


if __name__ == "__main__":
    unittest.main()
