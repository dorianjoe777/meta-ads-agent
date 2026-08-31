import assert from "node:assert/strict";
import test from "node:test";
import {
  buildHostedTenantLicense,
  hostedTenantLicenseKey,
  hostedTenantReference
} from "../lib/hosted-license.js";
import { validFormat } from "../lib/license.js";

const bridgeKey = "hosted-license-unit-test-key-that-is-long-enough";

test("hosted tenant references are strict and bounded", () => {
  assert.equal(hostedTenantReference("tenant_01:telegram"), "tenant_01:telegram");
  assert.equal(hostedTenantReference("ab"), "");
  assert.equal(hostedTenantReference("tenant/with/slash"), "");
  assert.equal(hostedTenantReference(`tenant-${"x".repeat(120)}`), "");
});

test("hosted license has no fake email and is deferred for later email attachment", () => {
  const record = buildHostedTenantLicense({
    tenantReference: "tenant_01",
    displayName: "Client\u0000 One",
    plan: "individual",
    bridgeKey,
    now: "2026-08-31T15:00:00.000Z"
  });
  assert.equal(validFormat(record.license_key), true);
  assert.equal(record.license_kind, "hosted_tenant");
  assert.equal(record.hosted_tenant_reference, "tenant_01");
  assert.equal(record.buyer_email, "");
  assert.equal(record.buyer_email_deferred, true);
  assert.equal(record.buyer_email_delivery.status, "deferred");
  assert.equal(record.buyer_name, "Client One");
  assert.equal(record.status, "active");
});

test("hosted license does not weaken plan validation", () => {
  assert.throws(
    () => buildHostedTenantLicense({ tenantReference: "tenant_01", plan: "enterprise", bridgeKey }),
    /plan_invalid/
  );
});

test("hosted idempotency keys are stable but not derivable from a tenant reference alone", () => {
  const first = hostedTenantLicenseKey({ tenantReference: "tenant_01", bridgeKey });
  const retry = hostedTenantLicenseKey({ tenantReference: "tenant_01", bridgeKey });
  const otherBridge = hostedTenantLicenseKey({
    tenantReference: "tenant_01",
    bridgeKey: "a-different-hosted-license-test-secret-12345"
  });
  assert.equal(first, retry);
  assert.notEqual(first, otherBridge);
  assert.equal(validFormat(first), true);
  assert.throws(
    () => hostedTenantLicenseKey({ tenantReference: "tenant_01", bridgeKey: "short" }),
    /hosted_bridge_key_invalid/
  );
});
