import assert from "node:assert/strict";
import test from "node:test";

import { maskedLicenseHint, normalizeInstallationLabel, portfolioCard } from "../lib/buyer-portfolio.js";

test("portfolio cards never expose the full license and identify separate installs", () => {
  const card = portfolioCard({
    license_key: "MAO-HP34-3426-1052-NISA-STOR-ES20-14B01D",
    buyer_email: "buyer@example.com",
    status: "active",
    installation_label: "Tienda Norte",
    cloud_installation: {
      install_status: "ready",
      cloud_open_url: "https://cloud.example.com/open/secret"
    }
  }, { id: "installation-2", position: 1, selected: true, switchToken: "signed-selection" });

  assert.equal(card.label, "Tienda Norte");
  assert.equal(card.selected, true);
  assert.equal(card.installation, "cloud_ready");
  assert.equal(card.switch_token, "signed-selection");
  assert.equal(card.license_hint, "...14B01D");
  assert.equal(JSON.stringify(card).includes("MAO-HP34"), false);
});

test("inactive licenses do not expose dashboard access", () => {
  const card = portfolioCard({
    license_key: "MAO-AAAA-BBBB-CCCC-1A2B3C",
    status: "refunded",
    cloud_installation: { install_status: "ready", cloud_open_url: "https://example.com/private" }
  }, { position: 0 });
  assert.equal(card.dashboard_url, "");
  assert.equal(card.status, "refunded");
});

test("buyer labels are short and stripped of control characters", () => {
  assert.equal(normalizeInstallationLabel("  Tienda\n Principal\u0000  "), "Tienda Principal");
  assert.equal(normalizeInstallationLabel("x".repeat(200)).length, 80);
  assert.equal(maskedLicenseHint("MAO-AAAA-BBBB-CCCC-123456"), "...123456");
});
