import test from "node:test";
import assert from "node:assert/strict";
import {
  hotmartSummary,
  hotmartTokenAllowed,
  isHotmartPurchaseApproved,
  isHotmartPurchaseRevoked,
  parseHotmartPayload
} from "../lib/hotmart-webhook.js";

const approvedPayload = {
  id: "event_123",
  event: "PURCHASE_APPROVED",
  version: "2.0.0",
  data: {
    product: {
      id: 123456,
      ucode: "product-ucode",
      name: "Admiro AI"
    },
    buyer: {
      email: "Buyer@Example.com",
      name: "Buyer Name"
    },
    purchase: {
      transaction: "HP17715690036014",
      status: "APPROVED",
      approved_date: 1760000000000,
      offer: {
        code: "INDIVIDUAL"
      }
    }
  }
};

test("validates Hotmart hottok header with constant-time comparison", () => {
  assert.equal(
    hotmartTokenAllowed({ "X-HOTMART-HOTTOK": "secret-token" }, "secret-token"),
    true
  );
  assert.equal(
    hotmartTokenAllowed({ "X-HOTMART-HOTTOK": "wrong-token" }, "secret-token"),
    false
  );
});

test("parses Hotmart purchase payload summary", () => {
  const payload = parseHotmartPayload(JSON.stringify(approvedPayload));
  const summary = hotmartSummary(payload);

  assert.equal(summary.event_id, "event_123");
  assert.equal(summary.event, "PURCHASE_APPROVED");
  assert.equal(summary.buyer_email, "buyer@example.com");
  assert.equal(summary.buyer_name, "Buyer Name");
  assert.equal(summary.transaction, "HP17715690036014");
  assert.equal(summary.status, "APPROVED");
  assert.equal(summary.product_id, "123456");
  assert.equal(summary.product_ucode, "product-ucode");
  assert.equal(summary.offer_code, "INDIVIDUAL");
});

test("classifies approved and revoked purchase notifications", () => {
  assert.equal(isHotmartPurchaseApproved(hotmartSummary(approvedPayload)), true);
  assert.equal(
    isHotmartPurchaseRevoked(hotmartSummary({
      event: "PURCHASE_REFUNDED",
      data: { purchase: { status: "REFUNDED" } }
    })),
    true
  );
});
