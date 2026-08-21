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

        legacy_oauth = {
            "enabled": False,
            "connected": False,
            "accounts": [],
            "pages": [],
            "active_ad_account_id": "",
            "active_page_id": "",
        }
        with patch.object(setup_status, "meta_oauth_summary", return_value=legacy_oauth):
            entries = setup_status.meta_section(self._config(broker="", token="ads-token"), {"page_id": "", "url": ""})
        keys = {entry["key"] for entry in entries}
        self.assertIn("access_token", keys)
        self.assertIn("publishing_token", keys)

    def test_compact_onboarding_has_no_facebook_section_or_token_input(self):
        source = Path(__file__).parents[1].joinpath("public", "dashboard", "dashboard.js").read_text()
        start = source.index("function compactMetaSetup()")
        end = source.index("function compactAgentSetup()", start)
        compact = source[start:end]
        self.assertIn("return '';", compact)
        self.assertNotIn("meta-token-input", compact)

    def test_dashboard_does_not_offer_facebook_connection_controls(self):
        source = Path(__file__).parents[1].joinpath("public", "dashboard", "dashboard.js").read_text()
        start = source.index("function onboardingSteps()")
        end = source.index("function renderOnboarding()", start)
        steps = source[start:end]
        self.assertNotIn("{id:'meta'", steps)

        start = source.index("function renderOnboardingFlow()")
        end = source.index("function maybeAutoDiscoverDestination", start)
        flow = source[start:end]
        self.assertNotIn("Conecta Meta", flow)
        self.assertNotIn("compactMetaSetup()", flow)
        self.assertIn("Elige el modelo", flow)
        self.assertIn("Conecta Telegram", flow)

        start = source.index("function maybeAutoDiscoverCompactSetup()")
        end = source.index("function renderOnboardingFlow()", start)
        discovery = source[start:end]
        self.assertIn("return;", discovery)
        self.assertNotIn("renderMetaOAuthChoices()", discovery)

        start = source.index("function renderMetaConnectionPanel()")
        end = source.index("function renderSetupConfig()", start)
        panel = source[start:end]
        self.assertIn("box.hidden=true", panel)
        self.assertIn("box.innerHTML=''", panel)

        start = source.index("function renderSetupConfig()")
        end = source.index("function renderPublishingPanel()", start)
        setup_config = source[start:end]
        self.assertIn("const metaFields=''", setup_config)
        self.assertNotIn("name=\"ad_account_id\"", setup_config)
        self.assertNotIn("name=\"page_id\"", setup_config)
        self.assertNotIn("name=\"instagram_actor_id\"", setup_config)

        self.assertIn("function onboardingFormFor(stepId)", source)
        self.assertIn("if(stepId==='meta')return '';", source)

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
