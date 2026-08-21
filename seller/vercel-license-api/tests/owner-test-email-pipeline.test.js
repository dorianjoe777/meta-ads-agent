import test from "node:test";
import assert from "node:assert/strict";
import {
  isOwnerTestPurchaseEmailRequest,
  markOwnerTestPurchaseEmailSent,
  ownerTestLicenseKey,
  ownerTestPurchaseEmailRecord
} from "../lib/owner-test-email-pipeline.js";
import { normalizeEntitlements, ownerEmailAllowed } from "../lib/license.js";

test("owner role grants unlimited-style commercial entitlements for the configured owner email", () => {
  const email = "dorianjoe.777@gmail.com";
  const record = ownerTestPurchaseEmailRecord({
    email,
    buyerName: "Dorian",
    body: { role: "owner" },
    now: "2026-06-27T12:00:00.000Z"
  });
  const entitlements = normalizeEntitlements(record);

  assert.equal(ownerEmailAllowed(email), true);
  assert.equal(record.license_key, "MAO-DORI-ANJO-E777-GMAI-LADM-INTE-36DECA");
  assert.equal(record.buyer_email, email);
  assert.equal(record.role, "owner");
  assert.equal(record.plan, "agency");
  assert.equal(entitlements.owner_unlimited, true);
  assert.equal(entitlements.max_devices, 9999);
  assert.equal(entitlements.workspace_limit, 9999);
  assert.deepEqual(record.test_email_pipeline, {
    kind: "commercial_purchase",
    role: "owner",
    unlimited: true,
    buyer_email: email,
    updated_at: "2026-06-27T12:00:00.000Z"
  });
});

test("owner commercial purchase email pipeline allows repeated sends to the same owner license", () => {
  const body = { action: "send_owner_test_purchase_email", buyer_email: "dorianjoe.777@gmail.com", role: "owner" };
  assert.equal(isOwnerTestPurchaseEmailRequest(body), true);
  assert.equal(ownerTestLicenseKey(body.buyer_email, body), "MAO-DORI-ANJO-E777-GMAI-LADM-INTE-36DECA");

  const record = ownerTestPurchaseEmailRecord({
    email: body.buyer_email,
    body,
    now: "2026-06-27T12:00:00.000Z"
  });
  markOwnerTestPurchaseEmailSent(record, { provider: "resend", id: "email_1", sent_at: "2026-06-27T12:01:00.000Z" });
  markOwnerTestPurchaseEmailSent(record, { provider: "resend", id: "email_2", sent_at: "2026-06-27T12:02:00.000Z" });

  assert.equal(record.commercial_purchase_email_count, 2);
  assert.equal(record.test_email_pipeline.unlimited, true);
  assert.equal(record.test_email_pipeline.last_delivery_id, "email_2");
  assert.equal(record.test_email_pipeline.last_sent_at, "2026-06-27T12:02:00.000Z");
});

test("owner commercial purchase email pipeline rejects non-owner emails", () => {
  assert.equal(ownerEmailAllowed("buyer@example.com"), false);
  assert.throws(
    () => ownerTestPurchaseEmailRecord({ email: "buyer@example.com", body: { role: "owner" } }),
    /owner_email_not_allowed/
  );
});
