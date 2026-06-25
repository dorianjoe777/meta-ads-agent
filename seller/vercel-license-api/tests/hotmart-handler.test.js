import test from "node:test";
import assert from "node:assert/strict";
import { createHotmartWebhookHandler } from "../lib/hotmart-webhook-handler.js";

const approvedPayload = {
  id: "event-approved",
  event: "PURCHASE_APPROVED",
  data: {
    product: { id: 123456, ucode: "admira-product", name: "Admira IA" },
    buyer: { email: "Buyer@Example.com", name: "Buyer Name" },
    purchase: {
      transaction: "HP-TEST-TRANSACTION",
      status: "APPROVED",
      offer: { code: "INDIVIDUAL" }
    }
  }
};

function mockResponse() {
  return {
    headers: {},
    statusCode: 0,
    body: null,
    setHeader(name, value) { this.headers[name] = value; },
    status(value) { this.statusCode = value; return this; },
    json(value) { this.body = value; return this; }
  };
}

function memoryStore() {
  const state = { registry: { licenses: [] }, records: new Map() };
  return {
    state,
    readRegistry: async () => state.registry,
    writeRegistry: async (registry) => { state.registry = registry; },
    writeLicense: async (record) => { state.records.set(record.license_key, record); }
  };
}

async function withHotmartToken(callback) {
  const previous = process.env.HOTMART_HOTTOK;
  process.env.HOTMART_HOTTOK = "test-hottok";
  try {
    await callback();
  } finally {
    if (previous === undefined) delete process.env.HOTMART_HOTTOK;
    else process.env.HOTMART_HOTTOK = previous;
  }
}

function request(body) {
  return { method: "POST", headers: { "x-hotmart-hottok": "test-hottok" }, body };
}

test("approved Hotmart purchases create one pending license and retries are idempotent", async () => {
  await withHotmartToken(async () => {
    const store = memoryStore();
    const handler = createHotmartWebhookHandler({
      ...store,
      shouldSendBuyerEmail: () => false,
      sendBuyerLicenseEmail: async () => { throw new Error("email must stay decoupled"); }
    });

    const first = mockResponse();
    await handler(request(approvedPayload), first);
    assert.equal(first.statusCode, 200);
    assert.equal(first.body.action, "license_created");
    assert.equal(first.body.buyer_email, "pending");
    assert.equal(store.state.registry.licenses.length, 1);
    const created = store.state.registry.licenses[0];
    assert.equal(created.buyer_email, "buyer@example.com");
    assert.equal(created.status, "active");
    assert.equal(created.buyer_email_delivery.status, "pending");
    assert.equal(created.hotmart_transaction, "HP-TEST-TRANSACTION");

    const retry = mockResponse();
    await handler(request({ ...approvedPayload, id: "event-approved-retry" }), retry);
    assert.equal(retry.statusCode, 200);
    assert.equal(retry.body.action, "license_existing");
    assert.equal(store.state.registry.licenses.length, 1);
    assert.equal(store.state.registry.licenses[0].license_key, created.license_key);
  });
});

test("refund notifications revoke the matching Hotmart license", async () => {
  await withHotmartToken(async () => {
    const store = memoryStore();
    const handler = createHotmartWebhookHandler({ ...store, shouldSendBuyerEmail: () => false });
    await handler(request(approvedPayload), mockResponse());

    const refunded = mockResponse();
    await handler(request({
      id: "event-refunded",
      event: "PURCHASE_REFUNDED",
      data: { purchase: { transaction: "HP-TEST-TRANSACTION", status: "REFUNDED" } }
    }), refunded);
    assert.equal(refunded.statusCode, 200);
    assert.equal(refunded.body.action, "license_revoked");
    assert.equal(store.state.registry.licenses[0].status, "revoked");
  });
});

test("storage failures return a safe retryable response", async () => {
  await withHotmartToken(async () => {
    const handler = createHotmartWebhookHandler({
      readRegistry: async () => { throw new Error("secret dependency detail"); },
      shouldSendBuyerEmail: () => false
    });
    const response = mockResponse();
    await handler(request(approvedPayload), response);
    assert.equal(response.statusCode, 503);
    assert.deepEqual(response.body, { ok: false, error: "license_store_unavailable", retryable: true });
    assert.equal(response.headers["Retry-After"], "5");
    assert.equal(JSON.stringify(response.body).includes("secret dependency detail"), false);
  });
});
