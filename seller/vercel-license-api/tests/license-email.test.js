import assert from "node:assert/strict";
import test from "node:test";
import {
  isValidBuyerEmail,
  licenseEmailMatches,
  updateLicenseBuyerEmail
} from "../lib/license-email.js";

test("email transfer keeps the existing installation identity and adds the old email as an alias", () => {
  const original = {
    license_key: "MAO-TRIAL-KEY-123456",
    buyer_email: "dorian1@uboost.lat",
    devices: ["device-a"],
    cloud_installation: { droplet_id: 123 },
    buyer_email_aliases: []
  };
  const updated = updateLicenseBuyerEmail(original, "Client@Example.com", "2026-08-14T12:00:00.000Z");

  assert.equal(updated.buyer_email, "client@example.com");
  assert.deepEqual(updated.buyer_email_aliases, ["dorian1@uboost.lat"]);
  assert.deepEqual(updated.devices, original.devices);
  assert.deepEqual(updated.cloud_installation, original.cloud_installation);
  assert.equal(licenseEmailMatches(updated, "client@example.com"), true);
  assert.equal(licenseEmailMatches(updated, "dorian1@uboost.lat"), true);
  assert.equal(licenseEmailMatches(updated, "other@example.com"), false);
  assert.deepEqual(updated.buyer_email_history, [{
    from: "dorian1@uboost.lat",
    to: "client@example.com",
    changed_at: "2026-08-14T12:00:00.000Z"
  }]);
});

test("buyer email validation rejects malformed or overlong values", () => {
  assert.equal(isValidBuyerEmail("dorian1@uboost.lat"), true);
  assert.equal(isValidBuyerEmail("not-an-email"), false);
  assert.equal(isValidBuyerEmail(`${"a".repeat(250)}@example.com`), false);
});
