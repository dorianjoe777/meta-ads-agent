import { createHmac } from "node:crypto";
import { entitlementDefaults, formatLicense, normalizeEntitlements } from "./license.js";

export function hostedTenantReference(value = "") {
  const reference = String(value || "").trim();
  return /^[A-Za-z0-9][A-Za-z0-9._:-]{2,119}$/.test(reference) ? reference : "";
}

export function hostedTenantName(value = "") {
  return String(value || "").trim().replace(/[\u0000-\u001f\u007f]/g, "").slice(0, 160);
}

// The tenant reference is the durable identity of a hosted customer. Keep
// its license key deterministic so retries (including retries that race in
// separate serverless invocations) address the same Upstash record instead
// of minting another key for the same tenant. Derive it with the bridge
// secret, rather than from a visible runtime key: a license code is itself a
// credential and must not be guessable from the tenant identifier.
export function hostedTenantLicenseKey({ tenantReference, bridgeKey }) {
  const reference = hostedTenantReference(tenantReference);
  const secret = String(bridgeKey || "").trim();
  if (!reference) throw new Error("external_customer_id_invalid");
  if (secret.length < 32 || secret.length > 512) throw new Error("hosted_bridge_key_invalid");
  const seed = createHmac("sha256", secret)
    .update(`admira-hosted-license:v1\u0000${reference}`, "utf8")
    .digest("hex");
  return formatLicense(seed);
}

export function buildHostedTenantLicense({
  tenantReference,
  displayName = "",
  plan = "individual",
  bridgeKey,
  now = new Date().toISOString()
}) {
  const reference = hostedTenantReference(tenantReference);
  const requestedPlan = String(plan || "individual").trim().toLowerCase();
  if (!reference) throw new Error("external_customer_id_invalid");
  if (!["individual", "agency"].includes(requestedPlan)) throw new Error("plan_invalid");
  const defaults = entitlementDefaults(requestedPlan);
  const entitlements = normalizeEntitlements({ plan: requestedPlan, ...defaults });
  return {
    license_key: hostedTenantLicenseKey({ tenantReference: reference, bridgeKey }),
    buyer_email: "",
    buyer_name: hostedTenantName(displayName),
    plan: entitlements.plan,
    status: "active",
    license_kind: "hosted_tenant",
    hosted_tenant_reference: reference,
    buyer_email_deferred: true,
    max_devices: entitlements.max_devices,
    workspace_limit: entitlements.workspace_limit,
    features: entitlements.features,
    devices: [],
    buyer_email_delivery: { status: "deferred", updated_at: now },
    created_at: now
  };
}
