import { normalizeEntitlements, ownerEmailAllowed, ownerLicenseKeyForEmail } from "./license.js";

const OWNER_TEST_ACTIONS = new Set([
  "send_owner_test_purchase_email",
  "send_owner_commercial_purchase_email",
  "send_commercial_purchase_email"
]);

function text(value) {
  return String(value || "").trim();
}

export function isOwnerTestPurchaseEmailRequest(body = {}) {
  const action = text(body.action).toLowerCase();
  const role = text(body.role).toLowerCase();
  return OWNER_TEST_ACTIONS.has(action) || (role === "owner" && body.commercial_purchase_email === true);
}

export function ownerTestLicenseKey(email = "", body = {}) {
  return text(body.license_key).toUpperCase() || ownerLicenseKeyForEmail(email);
}

export function ownerTestPurchaseEmailRecord({ email, buyerName = "", existing = null, body = {}, now = new Date().toISOString() }) {
  const buyerEmail = text(email).toLowerCase();
  if (!ownerEmailAllowed(buyerEmail)) {
    const error = new Error("owner_email_not_allowed");
    error.code = "owner_email_not_allowed";
    throw error;
  }

  const record = existing || {
    license_key: ownerTestLicenseKey(buyerEmail, body),
    devices: [],
    created_at: now
  };
  const entitlements = normalizeEntitlements({
    ...record,
    buyer_email: buyerEmail,
    role: "owner",
    plan: "agency",
    max_devices: body.max_devices,
    workspace_limit: body.workspace_limit,
    features: body.features
  });

  record.buyer_email = buyerEmail;
  record.buyer_name = text(buyerName || body.buyer_name || record.buyer_name || "Dorian");
  record.role = "owner";
  record.plan = entitlements.plan;
  record.status = "active";
  record.max_devices = entitlements.max_devices;
  record.workspace_limit = entitlements.workspace_limit;
  record.features = entitlements.features;
  record.buyer_email_delivery ||= { status: "pending", updated_at: now };
  record.test_email_pipeline = {
    ...(record.test_email_pipeline || {}),
    kind: "commercial_purchase",
    role: "owner",
    unlimited: true,
    buyer_email: buyerEmail,
    updated_at: now
  };
  return record;
}

export function markOwnerTestPurchaseEmailSent(record, delivery) {
  const count = Number(record.commercial_purchase_email_count || 0);
  record.commercial_purchase_email_count = Number.isFinite(count) ? count + 1 : 1;
  record.test_email_pipeline = {
    ...(record.test_email_pipeline || {}),
    kind: "commercial_purchase",
    role: "owner",
    unlimited: true,
    last_provider: delivery.provider || "",
    last_delivery_id: delivery.id || "",
    last_sent_at: delivery.sent_at,
    updated_at: delivery.sent_at
  };
  return record;
}
