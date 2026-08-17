import { sendBuyerLicenseEmail, shouldAutoSendBuyerEmail } from "../../lib/buyer-email.js";
import { handleHotmartWebhook } from "../../lib/hotmart-webhook-handler.js";
import { bearerAllowed, entitlementDefaults, formatLicense, normalizeEntitlements } from "../../lib/license.js";
import { isValidBuyerEmail, normalizeBuyerEmail, updateLicenseBuyerEmail } from "../../lib/license-email.js";
import {
  isOwnerTestPurchaseEmailRequest,
  markOwnerTestPurchaseEmailSent,
  ownerTestLicenseKey,
  ownerTestPurchaseEmailRecord
} from "../../lib/owner-test-email-pipeline.js";
import {
  cloudCleanResetCapability,
  cloudCleanResetStatus,
  requestCloudCleanReset,
  validateDigitalOceanToken
} from "../../lib/digitalocean-cloud.js";
import { setCloudNetworkMode } from "../portal/cloud/digitalocean.js";
import { readLicense, readRegistry, writeLicense, writeRegistry } from "../../lib/store.js";
import { encryptPortalSecret } from "../../lib/secret-vault.js";

function cloudSummary(cloud = {}) {
  const rawNetworkMode = String(cloud?.network_mode || "").trim().toLowerCase();
  // Direct Mac cloud installs historically created a public dashboard before
  // this switch existed. Treat those legacy records as testing so the table
  // reflects the firewall that is actually in place.
  const networkMode = rawNetworkMode === "testing" || (!rawNetworkMode && cloud?.direct_installer) ? "testing" : "strict";
  return {
    installed: Boolean(cloud?.droplet_id),
    status: String(cloud?.install_status || "not_started"),
    droplet_id: String(cloud?.droplet_id || ""),
    droplet_ip: String(cloud?.droplet_ip || ""),
    dashboard_url: String(cloud?.dashboard_url || cloud?.dashboard_http_url || ""),
    network_mode: networkMode,
    testing_mode: networkMode === "testing",
    can_change_network_mode: Boolean(cloud?.droplet_id && cloud?.firewall_id),
    network_mode_updated_at: String(cloud?.network_mode_updated_at || ""),
    can_clean_install: cloudCleanResetCapability(cloud),
    clean_reset_status: String(cloud?.clean_reset_status || ""),
    clean_reset_job_id: String(cloud?.clean_reset_job_id || ""),
    clean_reset_requested_at: String(cloud?.clean_reset_requested_at || ""),
    clean_reset_completed_at: String(cloud?.clean_reset_completed_at || "")
  };
}

function cloudNetworkModeFailure(response, error) {
  const code = String(error?.code || error?.message || "cloud_network_mode_failed");
  const status = code === "digitalocean_token_required" || code === "cloud_network_installation_missing" || code === "cloud_network_strict_ip_missing"
    ? 409
    : (error?.statusCode === 403 ? 502 : 502);
  return response.status(status).json({ ok: false, error: code, detail: String(error?.friendlyDetail || "No pude actualizar el modo de red del dashboard.") });
}

function cloudResetFailure(response, error) {
  const code = String(error?.code || error?.message || "cloud_clean_reset_failed");
  if (code === "cloud_clean_reset_unavailable") {
    return response.status(409).json({ ok: false, error: "cloud_clean_reset_unavailable" });
  }
  if (code === "cloud_clean_reset_timeout") {
    return response.status(504).json({ ok: false, error: "cloud_clean_reset_timeout" });
  }
  return response.status(502).json({ ok: false, error: "cloud_clean_reset_failed" });
}

function findLicenseSummary(registry, licenseKey) {
  return registry.licenses.findIndex((item) => String(item?.license_key || "").trim().toUpperCase() === licenseKey);
}

function validCloudIpv4(value = "") {
  const candidate = String(value || "").trim();
  const parts = candidate.split(".");
  if (parts.length !== 4 || parts.some((part) => !/^\d{1,3}$/.test(part) || Number(part) > 255)) return "";
  return candidate;
}

function validCloudSecret(value = "") {
  const candidate = String(value || "").trim();
  return /^[A-Za-z0-9_-]{32,180}$/.test(candidate) ? candidate : "";
}

function cleanCloudNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? Math.min(100, Math.round(number)) : fallback;
}

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
    const deliveryFilter = String(requestUrl.searchParams.get("delivery") || "").trim().toLowerCase();
    const summaries = current.map(({ license_key, buyer_email, plan = "individual", status, max_devices = 1, workspace_limit = 1, devices = [], created_at, hotmart_transaction = "", buyer_email_delivery = {}, last_buyer_email = {}, cloud_installation = {} }) => ({
      license_key,
      buyer_email,
      plan,
      status,
      max_devices,
      workspace_limit,
      devices: devices.length,
      created_at,
      hotmart_transaction,
      buyer_email_status: last_buyer_email.sent_at ? "sent" : (buyer_email_delivery.status || "pending"),
      cloud: cloudSummary(cloud_installation)
    }));
    return response.status(200).json({
      licenses: deliveryFilter
        ? summaries.filter((record) => record.buyer_email_status === deliveryFilter)
        : summaries
    });
  }
  if (request.method !== "POST") {
    return response.status(405).json({ ok: false, error: "method_not_allowed" });
  }
  const body = request.body || {};
  const action = String(body.action || "").trim().toLowerCase();
  if (action === "adopt_cloud_installation") {
    const licenseKey = String(body.license_key || "").trim().toUpperCase();
    const confirmation = String(body.confirm_license_key || "").trim().toUpperCase();
    if (!licenseKey) return response.status(400).json({ ok: false, error: "license_key_required" });
    if (confirmation !== licenseKey) return response.status(400).json({ ok: false, error: "license_confirmation_required" });
    const summaryIndex = findLicenseSummary(registry, licenseKey);
    if (summaryIndex < 0) return response.status(404).json({ ok: false, error: "license_not_found" });
    const loaded = await readLicense(licenseKey);
    if (!loaded) return response.status(404).json({ ok: false, error: "license_not_found" });
    const dropletId = String(body.droplet_id || "").trim();
    const dropletIp = validCloudIpv4(body.droplet_ip);
    const firewallId = String(body.firewall_id || "").trim();
    const accessSecret = validCloudSecret(body.cloud_access_secret);
    if (!/^\d+$/.test(dropletId) || !dropletIp || !/^[A-Za-z0-9-]{6,128}$/.test(firewallId) || !accessSecret) {
      return response.status(400).json({ ok: false, error: "cloud_install_metadata_invalid" });
    }
    const currentCloud = loaded.cloud_installation || {};
    if (currentCloud.droplet_id && String(currentCloud.droplet_id) !== dropletId) {
      return response.status(409).json({ ok: false, error: "cloud_installation_exists" });
    }
    const mode = String(body.network_mode || "testing").trim().toLowerCase() === "strict" ? "strict" : "testing";
    const now = new Date().toISOString();
    const updatedCloud = {
      ...currentCloud,
      provider: "digitalocean",
      direct_installer: true,
      install_source: "mac-cloud-command-recovered",
      install_job_id: String(currentCloud.install_job_id || `recovered-${dropletId}`).slice(0, 120),
      droplet_id: dropletId,
      droplet_ip: dropletIp,
      droplet_name: String(body.droplet_name || currentCloud.droplet_name || `admira-ia-${dropletId}`).slice(0, 160),
      firewall_id: firewallId,
      ssh_key_id: String(body.ssh_key_id || currentCloud.ssh_key_id || "").slice(0, 80),
      region: String(body.region || currentCloud.region || "").slice(0, 40),
      size: String(body.size || currentCloud.size || "").slice(0, 80),
      dashboard_port: "7871",
      dashboard_url: `http://${dropletIp}:7871/`,
      dashboard_http_url: `http://${dropletIp}:7871/`,
      dashboard_https_url: "",
      cloud_open_url: "",
      cloud_access_secret: accessSecret,
      access_gate_port: "7870",
      network_mode: mode,
      testing_mode: mode === "testing",
      install_status: String(body.install_status || currentCloud.install_status || "ready").slice(0, 40),
      install_progress: cleanCloudNumber(body.install_progress, 100),
      initial_client_ip: validCloudIpv4(body.initial_client_ip || currentCloud.initial_client_ip) || String(currentCloud.initial_client_ip || ""),
      install_started_at: currentCloud.install_started_at || now,
      registered_at: currentCloud.registered_at || now,
      updated_at: now,
      recovered_at: now
    };
    registry.licenses[summaryIndex] = { ...registry.licenses[summaryIndex], cloud_installation: updatedCloud };
    await Promise.all([writeRegistry(registry), writeLicense({ ...loaded, cloud_installation: updatedCloud })]);
    return response.status(200).json({ ok: true, status: "cloud_installation_adopted", cloud: cloudSummary(updatedCloud) });
  }
  if (action === "set_cloud_network_mode") {
    const licenseKey = String(body.license_key || "").trim().toUpperCase();
    const mode = String(body.mode || "").trim().toLowerCase();
    if (!licenseKey) return response.status(400).json({ ok: false, error: "license_key_required" });
    if (!['strict', 'testing'].includes(mode)) return response.status(400).json({ ok: false, error: "cloud_network_mode_invalid" });
    const confirmation = String(body.confirm_license_key || "").trim().toUpperCase();
    if (confirmation !== licenseKey) return response.status(400).json({ ok: false, error: "license_confirmation_required" });
    const summaryIndex = findLicenseSummary(registry, licenseKey);
    if (summaryIndex < 0) return response.status(404).json({ ok: false, error: "license_not_found" });
    const loaded = await readLicense(licenseKey);
    if (!loaded) return response.status(404).json({ ok: false, error: "license_not_found" });
    if (!cloudSummary(loaded.cloud_installation || {}).installed) {
      return response.status(409).json({ ok: false, error: "cloud_installation_not_found" });
    }
    try {
      const suppliedDigitalOceanToken = String(body.digitalocean_token || "").trim();
      const result = await setCloudNetworkMode(loaded, mode, {
        digitalOceanToken: suppliedDigitalOceanToken,
        clientIp: body.client_ip
      });
      const updatedCloud = result.cloud;
      const updatedRecord = validateDigitalOceanToken(suppliedDigitalOceanToken)
        ? { ...loaded, portal_vault: { ...(loaded.portal_vault || {}), digitalocean_token: encryptPortalSecret(suppliedDigitalOceanToken) }, cloud_installation: updatedCloud }
        : { ...loaded, cloud_installation: updatedCloud };
      registry.licenses[summaryIndex] = { ...registry.licenses[summaryIndex], cloud_installation: updatedCloud };
      await Promise.all([writeRegistry(registry), writeLicense(updatedRecord)]);
      return response.status(200).json({
        ok: true,
        status: "cloud_network_mode_updated",
        mode: result.mode,
        public_dashboard: result.public_dashboard,
        dashboard_port: result.dashboard_port,
        strict_ip: result.strict_ip,
        cloud: cloudSummary(updatedCloud)
      });
    } catch (error) {
      return cloudNetworkModeFailure(response, error);
    }
  }
  if (action === "reset_cloud_installation" || action === "cloud_reset_status") {
    const licenseKey = String(body.license_key || "").trim().toUpperCase();
    if (!licenseKey) return response.status(400).json({ ok: false, error: "license_key_required" });
    const summaryIndex = findLicenseSummary(registry, licenseKey);
    if (summaryIndex < 0) return response.status(404).json({ ok: false, error: "license_not_found" });
    const loaded = await readLicense(licenseKey);
    if (!loaded) return response.status(404).json({ ok: false, error: "license_not_found" });
    const cloud = loaded.cloud_installation || {};
    if (!cloudSummary(cloud).installed) {
      return response.status(409).json({ ok: false, error: "cloud_installation_not_found" });
    }
    if (action === "reset_cloud_installation") {
      const confirmation = String(body.confirm_license_key || "").trim().toUpperCase();
      if (!confirmation || confirmation !== licenseKey) {
        return response.status(400).json({ ok: false, error: "license_confirmation_required" });
      }
      if (!cloudCleanResetCapability(cloud)) {
        return response.status(409).json({ ok: false, error: "cloud_clean_reset_unavailable" });
      }
      try {
        const result = await requestCloudCleanReset(cloud);
        const requestedAt = new Date().toISOString();
        const updatedCloud = {
          ...cloud,
          clean_reset_job_id: String(result.job_id || "").slice(0, 120),
          clean_reset_status: String(result.status || "queued").slice(0, 40),
          clean_reset_requested_at: requestedAt,
          clean_reset_detail: String(result.detail || "").slice(0, 240)
        };
        registry.licenses[summaryIndex] = { ...registry.licenses[summaryIndex], cloud_installation: updatedCloud };
        await Promise.all([writeRegistry(registry), writeLicense({ ...loaded, cloud_installation: updatedCloud })]);
        return response.status(202).json({
          ok: true,
          status: "reset_requested",
          reset: {
            job_id: updatedCloud.clean_reset_job_id,
            status: updatedCloud.clean_reset_status,
            detail: updatedCloud.clean_reset_detail,
            preserves: ["NIM/API keys", "ChatGPT/Codex connection for images", "Telegram bot connection"],
            clears: ["Facebook/Meta tokens", "dashboard password", "business data", "generated media", "onboarding state"]
          },
          cloud: cloudSummary(updatedCloud)
        });
      } catch (error) {
        return cloudResetFailure(response, error);
      }
    }
    try {
      const result = await cloudCleanResetStatus(cloud);
      const updatedCloud = {
        ...cloud,
        clean_reset_status: String(result.status || cloud.clean_reset_status || "").slice(0, 40),
        clean_reset_job_id: String(result.job_id || cloud.clean_reset_job_id || "").slice(0, 120),
        clean_reset_detail: String(result.detail || cloud.clean_reset_detail || "").slice(0, 240),
        clean_reset_completed_at: result.status === "complete" ? String(result.updated_at || new Date().toISOString()) : String(cloud.clean_reset_completed_at || "")
      };
      registry.licenses[summaryIndex] = { ...registry.licenses[summaryIndex], cloud_installation: updatedCloud };
      await Promise.all([writeRegistry(registry), writeLicense({ ...loaded, cloud_installation: updatedCloud })]);
      return response.status(200).json({ ok: true, status: "cloud_reset_status", reset: result, cloud: cloudSummary(updatedCloud) });
    } catch (error) {
      return cloudResetFailure(response, error);
    }
  }
  if (String(body.action || "").trim().toLowerCase() === "update_email") {
    const licenseKey = String(body.license_key || "").trim().toUpperCase();
    const nextEmail = normalizeBuyerEmail(body.buyer_email);
    if (!licenseKey) return response.status(400).json({ ok: false, error: "license_key_required" });
    if (!isValidBuyerEmail(nextEmail)) return response.status(400).json({ ok: false, error: "buyer_email_invalid" });
    const summaryIndex = registry.licenses.findIndex((item) => String(item?.license_key || "").trim().toUpperCase() === licenseKey);
    if (summaryIndex < 0) return response.status(404).json({ ok: false, error: "license_not_found" });
    const loaded = await readLicense(licenseKey);
    if (!loaded) return response.status(404).json({ ok: false, error: "license_not_found" });
    const previousEmail = normalizeBuyerEmail(loaded.buyer_email);
    const updated = updateLicenseBuyerEmail(loaded, nextEmail);
    registry.licenses[summaryIndex] = {
      ...registry.licenses[summaryIndex],
      buyer_email: updated.buyer_email,
      buyer_email_aliases: updated.buyer_email_aliases,
      buyer_email_history: updated.buyer_email_history,
      updated_at: updated.updated_at
    };
    // This intentionally does not call any device/cloud reset function.
    await Promise.all([writeRegistry(registry), writeLicense(updated)]);
    return response.status(200).json({
      ok: true,
      license: updated,
      email_change: {
        changed: previousEmail !== updated.buyer_email,
        previous_email: previousEmail,
        buyer_email: updated.buyer_email,
        installation_preserved: true,
        devices_preserved: true,
        cloud_installation_preserved: true
      }
    });
  }
  const email = normalizeBuyerEmail(body.buyer_email);
  if (!isValidBuyerEmail(email)) {
    return response.status(400).json({ ok: false, error: "buyer_email_required" });
  }
  const ownerTestPurchaseEmail = isOwnerTestPurchaseEmailRequest(body);
  const plan = ownerTestPurchaseEmail || body.plan === "agency" ? "agency" : "individual";
  const defaults = entitlementDefaults(plan);
  const entitlements = normalizeEntitlements({
    buyer_email: email,
    role: ownerTestPurchaseEmail ? "owner" : body.role,
    plan,
    max_devices: body.max_devices || defaults.max_devices,
    workspace_limit: body.workspace_limit || defaults.workspace_limit,
    features: body.features || defaults.features
  });
  const licenseKey = body.license_key || (ownerTestPurchaseEmail ? ownerTestLicenseKey(email, body) : formatLicense(`${email}${Date.now()}`));
  const existing = registry.licenses.find((item) => item.license_key === licenseKey);
  if (body.action === "mark_email_sent" && !existing) {
    return response.status(404).json({ ok: false, error: "license_not_found" });
  }
  let record;
  if (ownerTestPurchaseEmail) {
    try {
      record = ownerTestPurchaseEmailRecord({ email, buyerName: body.buyer_name, existing, body });
    } catch (error) {
      if (error?.code === "owner_email_not_allowed") {
        return response.status(403).json({ ok: false, error: "owner_email_not_allowed" });
      }
      throw error;
    }
  } else {
    record = existing || {
      license_key: licenseKey,
      buyer_email: email,
      buyer_name: String(body.buyer_name || ""),
      role: String(body.role || "").trim().toLowerCase() || undefined,
      plan: entitlements.plan,
      status: "active",
      max_devices: entitlements.max_devices,
      workspace_limit: entitlements.workspace_limit,
      features: entitlements.features,
      devices: [],
      buyer_email_delivery: { status: "pending", updated_at: new Date().toISOString() },
      created_at: new Date().toISOString()
    };
  }
  if (existing && (body.plan || body.role || ownerTestPurchaseEmail)) {
    if (body.role || ownerTestPurchaseEmail) record.role = ownerTestPurchaseEmail ? "owner" : String(body.role || "").trim().toLowerCase();
    record.plan = entitlements.plan;
    record.max_devices = entitlements.max_devices;
    record.workspace_limit = entitlements.workspace_limit;
    record.features = entitlements.features;
  }
  if (body.action === "revoke") record.status = "revoked";
  if (body.action === "activate") record.status = "active";
  if (!existing) registry.licenses.push(record);
  await Promise.all([writeRegistry(registry), writeLicense(record)]);

  if (body.action === "mark_email_sent") {
    const sentAt = new Date().toISOString();
    const provider = String(body.provider || "external").trim().slice(0, 80) || "external";
    const id = String(body.delivery_id || "").trim().slice(0, 200);
    record.last_buyer_email = { provider, id, sent_at: sentAt };
    record.buyer_email_delivery = { status: "sent", updated_at: sentAt };
    await Promise.all([writeRegistry(registry), writeLicense(record)]);
    return response.status(200).json({ ok: true, license: record, buyer_email: { ok: true, provider, id, sent_at: sentAt } });
  }

  const wantsBuyerEmail = body.send_buyer_email === true
    || body.email_buyer === true
    || body.action === "send_email"
    || ownerTestPurchaseEmail
    || (!existing && shouldAutoSendBuyerEmail());
  if (!wantsBuyerEmail) {
    return response.status(200).json({ ok: true, license: record });
  }

  try {
    const delivery = await sendBuyerLicenseEmail(record);
    record.last_buyer_email = delivery;
    record.buyer_email_delivery = { status: "sent", updated_at: delivery.sent_at };
    if (ownerTestPurchaseEmail) markOwnerTestPurchaseEmailSent(record, delivery);
    await Promise.all([writeRegistry(registry), writeLicense(record)]);
    return response.status(200).json({ ok: true, license: record, buyer_email: { ok: true, ...delivery } });
  } catch {
    record.buyer_email_delivery = { status: "failed", updated_at: new Date().toISOString() };
    await writeLicense(record).catch(() => {});
    return response.status(502).json({
      ok: false,
      error: "buyer_email_send_failed",
      license: record
    });
  }
}
