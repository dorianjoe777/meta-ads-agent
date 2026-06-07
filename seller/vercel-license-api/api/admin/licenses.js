import { sendBuyerLicenseEmail, shouldAutoSendBuyerEmail } from "../../lib/buyer-email.js";
import { handleHotmartWebhook } from "../../lib/hotmart-webhook-handler.js";
import { bearerAllowed, entitlementDefaults, formatLicense, normalizeEntitlements } from "../../lib/license.js";
import { readLicense, readRegistry, writeLicense, writeRegistry } from "../../lib/store.js";

export default async function handler(request, response) {
  const requestUrl = new URL(request.url || "/", `https://${request.headers.host || "localhost"}`);
  if (requestUrl.searchParams.get("webhook") === "hotmart") {
    return handleHotmartWebhook(request, response);
  }

  if (!bearerAllowed(request)) {
    return response.status(401).json({ ok: false, error: "unauthorized" });
  }
  const registry = await readRegistry();
  if (request.method === "GET") {
    const current = await Promise.all(registry.licenses.map(async (record) => (await readLicense(record.license_key)) || record));
    return response.status(200).json({
      licenses: current.map(({ license_key, buyer_email, plan = "individual", status, max_devices = 1, workspace_limit = 1, devices = [], created_at }) => ({
        license_key,
        buyer_email,
        plan,
        status,
        max_devices,
        workspace_limit,
        devices: devices.length,
        created_at
      }))
    });
  }
  if (request.method !== "POST") {
    return response.status(405).json({ ok: false, error: "method_not_allowed" });
  }
  const body = request.body || {};
  const email = String(body.buyer_email || "").trim().toLowerCase();
  if (!email.includes("@")) {
    return response.status(400).json({ ok: false, error: "buyer_email_required" });
  }
  const plan = body.plan === "agency" ? "agency" : "individual";
  const defaults = entitlementDefaults(plan);
  const entitlements = normalizeEntitlements({
    plan,
    max_devices: body.max_devices || defaults.max_devices,
    workspace_limit: body.workspace_limit || defaults.workspace_limit,
    features: body.features || defaults.features
  });
  const licenseKey = body.license_key || formatLicense(`${email}${Date.now()}`);
  const existing = registry.licenses.find((item) => item.license_key === licenseKey);
  const record = existing || {
    license_key: licenseKey,
    buyer_email: email,
    buyer_name: String(body.buyer_name || ""),
    plan: entitlements.plan,
    status: "active",
    max_devices: entitlements.max_devices,
    workspace_limit: entitlements.workspace_limit,
    features: entitlements.features,
    devices: [],
    created_at: new Date().toISOString()
  };
  if (existing && body.plan) {
    record.plan = entitlements.plan;
    record.max_devices = entitlements.max_devices;
    record.workspace_limit = entitlements.workspace_limit;
    record.features = entitlements.features;
  }
  if (body.action === "revoke") record.status = "revoked";
  if (body.action === "activate") record.status = "active";
  if (!existing) registry.licenses.push(record);
  await Promise.all([writeRegistry(registry), writeLicense(record)]);

  const wantsBuyerEmail = body.send_buyer_email === true
    || body.email_buyer === true
    || body.action === "send_email"
    || (!existing && shouldAutoSendBuyerEmail());
  if (!wantsBuyerEmail) {
    return response.status(200).json({ ok: true, license: record });
  }

  try {
    const delivery = await sendBuyerLicenseEmail(record);
    record.last_buyer_email = delivery;
    await writeLicense(record);
    return response.status(200).json({ ok: true, license: record, buyer_email: { ok: true, ...delivery } });
  } catch (error) {
    return response.status(502).json({
      ok: false,
      error: "buyer_email_send_failed",
      detail: error.message,
      license: record
    });
  }
}
