import { sendBuyerLicenseEmail } from "./buyer-email.js";
import { entitlementDefaults, formatLicense, normalizeEntitlements } from "./license.js";
import {
  hotmartProductAllowed,
  hotmartSummary,
  hotmartTokenAllowed,
  isHotmartPurchaseApproved,
  isHotmartPurchaseRevoked,
  parseHotmartPayload,
  planForHotmartPurchase,
  shouldSendHotmartBuyerEmail
} from "./hotmart-webhook.js";
import { readRegistry, writeLicense, writeRegistry } from "./store.js";

function safeError(response, status, error, detail = "") {
  return response.status(status).json({
    ok: false,
    error,
    ...(detail ? { detail } : {})
  });
}

function findByHotmartTransaction(registry, transaction) {
  return (registry.licenses || []).find((record) => {
    return record?.hotmart?.transaction === transaction || record?.hotmart_transaction === transaction;
  });
}

function metadataFor(summary, previous = {}) {
  const now = new Date().toISOString();
  return {
    ...(previous || {}),
    event_id: summary.event_id || previous.event_id || "",
    event: summary.event,
    transaction: summary.transaction,
    status: summary.status,
    product_id: summary.product_id,
    product_ucode: summary.product_ucode,
    product_name: summary.product_name,
    offer_code: summary.offer_code,
    approved_date: summary.approved_date || previous.approved_date || null,
    first_received_at: previous.first_received_at || now,
    last_received_at: now
  };
}

function licenseForApprovedPurchase({ existing, summary }) {
  const plan = existing?.plan || planForHotmartPurchase(summary);
  const defaults = entitlementDefaults(plan);
  const entitlements = normalizeEntitlements({
    plan,
    max_devices: existing?.max_devices || defaults.max_devices,
    workspace_limit: existing?.workspace_limit || defaults.workspace_limit,
    features: existing?.features || defaults.features
  });
  const record = existing || {
    license_key: formatLicense(`${summary.transaction}${summary.buyer_email}`),
    buyer_email: summary.buyer_email,
    buyer_name: summary.buyer_name,
    plan: entitlements.plan,
    status: "active",
    max_devices: entitlements.max_devices,
    workspace_limit: entitlements.workspace_limit,
    features: entitlements.features,
    devices: [],
    created_at: new Date().toISOString()
  };

  record.buyer_email = record.buyer_email || summary.buyer_email;
  record.buyer_name = record.buyer_name || summary.buyer_name;
  record.plan = entitlements.plan;
  record.status = "active";
  record.max_devices = entitlements.max_devices;
  record.workspace_limit = entitlements.workspace_limit;
  record.features = entitlements.features;
  record.hotmart = metadataFor(summary, record.hotmart);
  record.hotmart_transaction = summary.transaction;
  return record;
}

export async function handleHotmartWebhook(request, response) {
  response.setHeader("Cache-Control", "no-store");

  if (request.method !== "POST") {
    return safeError(response, 405, "method_not_allowed");
  }
  if (!hotmartTokenAllowed(request.headers)) {
    return safeError(response, 401, "unauthorized");
  }

  const payload = parseHotmartPayload(request.body);
  if (!payload) {
    return safeError(response, 400, "invalid_payload");
  }

  const summary = hotmartSummary(payload);
  if (!hotmartProductAllowed(summary)) {
    return response.status(200).json({ ok: true, ignored: true, reason: "product_mismatch" });
  }

  const registry = await readRegistry();
  const existing = summary.transaction ? findByHotmartTransaction(registry, summary.transaction) : null;

  if (isHotmartPurchaseRevoked(summary)) {
    if (!existing) {
      return response.status(200).json({ ok: true, ignored: true, reason: "no_matching_license" });
    }
    existing.status = "revoked";
    existing.hotmart = metadataFor(summary, existing.hotmart);
    await Promise.all([writeRegistry(registry), writeLicense(existing)]);
    return response.status(200).json({ ok: true, processed: true, action: "license_revoked" });
  }

  if (!isHotmartPurchaseApproved(summary)) {
    return response.status(200).json({ ok: true, ignored: true, reason: "not_approved_purchase", status: summary.status, event: summary.event });
  }
  if (!summary.buyer_email || !summary.buyer_email.includes("@")) {
    return safeError(response, 400, "buyer_email_required");
  }
  if (!summary.transaction) {
    return safeError(response, 400, "transaction_required");
  }

  const record = licenseForApprovedPurchase({ existing, summary });
  if (!existing) {
    registry.licenses ||= [];
    registry.licenses.push(record);
  }
  await Promise.all([writeRegistry(registry), writeLicense(record)]);

  const shouldEmail = shouldSendHotmartBuyerEmail() && !record.last_buyer_email?.sent_at;
  if (!shouldEmail) {
    return response.status(200).json({
      ok: true,
      processed: true,
      action: existing ? "license_existing" : "license_created",
      buyer_email: "skipped"
    });
  }

  try {
    const delivery = await sendBuyerLicenseEmail(record);
    record.last_buyer_email = delivery;
    record.hotmart = {
      ...record.hotmart,
      buyer_email_sent_at: delivery.sent_at
    };
    await Promise.all([writeRegistry(registry), writeLicense(record)]);
    return response.status(200).json({
      ok: true,
      processed: true,
      action: existing ? "license_existing_email_sent" : "license_created_email_sent",
      buyer_email: { ok: true, provider: delivery.provider, id: delivery.id }
    });
  } catch (error) {
    return safeError(response, 502, "buyer_email_send_failed", error.message);
  }
}
