import types
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


SRC = Path(__file__).parents[1].joinpath("src")
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class OAuthFirstSetupTests(TestCase):
    def _config(self, broker="https://admiraia.uboost.lat/api/meta-oauth", token=""):
        return types.SimpleNamespace(
            meta_oauth_broker_url=broker,
            meta_access_token=token,
            meta_access_token_kind="",
            meta_access_token_saved_at="",
            meta_publishing_access_token="",
            meta_connector="graph_api",
            live=True,
            ad_account_id="",
        )

    def test_oauth_first_status_does_not_expose_legacy_token_rows(self):
        import setup_status

        with patch.object(setup_status, "read_json", return_value={"connected": False}):
            entries = setup_status.meta_section(self._config(), {"page_id": "", "url": ""})
        keys = {entry["key"] for entry in entries}
        self.assertIn("facebook_oauth", keys)
        self.assertNotIn("access_token", keys)
        self.assertNotIn("publishing_token", keys)
        self.assertNotIn("access_token_renewal", keys)

    def test_legacy_install_keeps_token_compatibility(self):
        import setup_status

        with patch.object(setup_status, "read_json", return_value={}):
            entries = setup_status.meta_section(self._config(broker="", token="ads-token"), {"page_id": "", "url": ""})
        keys = {entry["key"] for entry in entries}
        self.assertIn("access_token", keys)
        self.assertIn("publishing_token", keys)

    def test_compact_onboarding_uses_oauth_and_has_no_meta_token_input(self):
        source = Path(__file__).parents[1].joinpath("public", "dashboard", "dashboard.js").read_text()
        start = source.index("function compactMetaSetup()")
        end = source.index("function compactAgentSetup()", start)
        compact = source[start:end]
        self.assertIn("return metaConnectionGuide();", compact)
        self.assertNotIn("meta-token-input", compact)

    def test_dashboard_does_not_offer_facebook_connection_controls(self):
        source = Path(__file__).parents[1].joinpath("public", "dashboard", "dashboard.js").read_text()
        start = source.index("function metaConnectionGuide()")
        end = source.index("function accountPickerGuide()", start)
        guide = source[start:end]
        self.assertIn("No hay botones ni campos de Facebook", guide)
        self.assertNotIn("data-action-code=\"startMetaOAuth()\"", guide)
        self.assertNotIn("data-action-code=\"pollMetaOAuth()\"", guide)

        start = source.index("function renderMetaConnectionPanel()")
        end = source.index("function renderSetupConfig()", start)
        panel = source[start:end]
        self.assertNotIn("openMetaSettingsGuide", panel)
        self.assertNotIn("Conectar Facebook", panel)


if __name__ == "__main__":
    import unittest

    unittest.main()
