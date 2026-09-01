from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import admira_hermes_runtime_patch as runtime_patch


class HostedTelegramOutputTests(unittest.TestCase):
    def test_technical_preamble_is_removed_but_bold_markup_is_preserved(self):
        noisy = (
            "⚠ tirith security scanner enabled but not available — command scanning will use pattern matching only\n"
            "  ┊ review diff\n"
            "a/data/business_profile.json → b/data/business_profile.json\n"
            "@@ -1 +1 @@\n"
            "- old\n"
            "+ new\n"
            "¡Hola! **Pregunta importante**"
        )

        cleaned, metadata = runtime_patch.normalize_telegram_outbound_text(noisy, "es")

        self.assertEqual(cleaned, "¡Hola! **Pregunta importante**")
        self.assertNotIn("tirith", cleaned.lower())
        self.assertNotIn("business_profile", cleaned)
        self.assertIn("technical_preamble_removed", metadata["reasons"])


if __name__ == "__main__":
    unittest.main()
