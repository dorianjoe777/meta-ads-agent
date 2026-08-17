import { normalizeEntitlements, signedCloudInstallRegistrationGrant, signedReleaseGrant, validFormat, verifyCloudInstallRegistrationGrant } from "../../lib/license.js";
import { licenseEmailMatches } from "../../lib/license-email.js";
import { buyerFacingImprovements, releaseAssetByName, releaseWithDiscoveredAssets } from "../../lib/download-portal.js";
import { ensureDeviceBinding } from "../../lib/device-binding.js";
import {
  deviceRegistrations,
  isRegisteredDevice,
  readLicense,
  readReleases,
  registerDevice,
  resetDeviceRegistrations,
  unregisterDevice,
  writeLicense,
  readRegistry,
  writeRegistry
} from "../../lib/store.js";

function baseUrl(request) {
  const host = String(request.headers["x-forwarded-host"] || request.headers.host || "").trim();
  const proto = String(request.headers["x-forwarded-proto"] || "https").trim() || "https";
  return `${proto}://${host}`;
}

function friendlyFailure(response, status, detail) {
  return response.status(200).json({ valid: false, status, detail });
}

function cleanCloudValue(value, max = 180) {
  return String(value || "").trim().slice(0, max);
}

function validCloudIpv4(value) {
  const candidate = String(value || "").trim();
  const parts = candidate.split(".");
  return parts.length === 4 && parts.every((part) => /^\d{1,3}$/.test(part) && Number(part) <= 255) ? candidate : "";
}

async function registerCloudInstallation(request, response, body) {
  const grant = verifyCloudInstallRegistrationGrant(body.cloud_install_token);
  if (!grant) return response.status(403).json({ ok: false, error: "invalid_or_expired_cloud_install_token" });
  const licenseKey = String(grant.license_key || "").trim().toUpperCase();
  const buyerEmail = String(grant.buyer_email || "").trim().toLowerCase();
  const deviceId = String(grant.device_id || "").trim();
  if (!validFormat(licenseKey) || !buyerEmail || !buyerEmail.includes("@") || !deviceId) {
    return response.status(403).json({ ok: false, error: "invalid_cloud_install_claims" });
  }
  if (String(body.license_key || "").trim().toUpperCase() !== licenseKey
    || String(body.buyer_email || "").trim().toLowerCase() !== buyerEmail
    || String(body.device_id || "").trim() !== deviceId) {
    return response.status(403).json({ ok: false, error: "cloud_install_claim_mismatch" });
  }
  const record = await readLicense(licenseKey);
  if (!record || record.status !== "active" || !licenseEmailMatches(record, buyerEmail)) {
    return response.status(403).json({ ok: false, error: "license_not_active" });
  }
  const dropletId = cleanCloudValue(body.droplet_id, 32);
  const dropletIp = validCloudIpv4(body.droplet_ip);
  const firewallId = cleanCloudValue(body.firewall_id, 160);
  const accessSecret = cleanCloudValue(body.cloud_access_secret, 180);
  const accessGatePort = Number(body.access_gate_port || 7870);
  if (!/^\d+$/.test(dropletId) || !dropletIp || !firewallId || accessGatePort !== 7870 || !/^[A-Za-z0-9_-]{32,180}$/.test(accessSecret)) {
    return response.status(400).json({ ok: false, error: "cloud_install_metadata_invalid" });
  }
  const existing = record.cloud_installation || {};
  if (existing.droplet_id && String(existing.droplet_id) !== dropletId) {
    return response.status(409).json({ ok: false, error: "cloud_installation_exists" });
  }
  const now = new Date().toISOString();
  const cloud = {
    ...existing,
    provider: "digitalocean",
    direct_installer: true,
    install_source: "mac-cloud-command",
    install_job_id: cleanCloudValue(body.install_job_id, 120) || `mac-${deviceId}-${dropletId}`,
    droplet_id: dropletId,
    droplet_name: cleanCloudValue(body.droplet_name, 160),
    droplet_ip: dropletIp,
    firewall_id: firewallId,
    ssh_key_id: cleanCloudValue(body.ssh_key_id, 80),
    region: cleanCloudValue(body.region, 40),
    size: cleanCloudValue(body.size, 80),
    dashboard_port: "7871",
    dashboard_url: `http://${dropletIp}:7871/`,
    dashboard_http_url: `http://${dropletIp}:7871/`,
    dashboard_https_url: "",
    cloud_open_url: "",
    cloud_access_secret: accessSecret,
    access_gate_port: String(accessGatePort),
    // The Mac command installer creates a public dashboard firewall so the
    // owner can hand the URL to a trial client immediately. The admin table
    // can switch this same installation back to strict mode later.
    network_mode: "testing",
    testing_mode: true,
    install_status: cleanCloudValue(body.install_status, 40) || "installing",
    install_progress: Math.max(0, Math.min(100, Number(body.install_progress || 88) || 88)),
    install_started_at: existing.install_started_at || now,
    registered_at: existing.registered_at || now,
    updated_at: now
  };
  const registry = await readRegistry();
  const index = registry.licenses.findIndex((item) => String(item?.license_key || "").trim().toUpperCase() === licenseKey);
  if (index < 0) return response.status(404).json({ ok: false, error: "license_not_found" });
  registry.licenses[index] = { ...registry.licenses[index], cloud_installation: cloud };
  await Promise.all([
    writeLicense({ ...record, cloud_installation: cloud }),
    writeRegistry(registry)
  ]);
  return response.status(200).json({ ok: true, status: cloud.install_status, droplet_id: dropletId, droplet_ip: dropletIp, dashboard_url: cloud.dashboard_url, registered: true });
}

export default async function handler(request, response) {
  if (request.method !== "POST") {
    return response.status(405).json({ valid: false, status: "method_not_allowed" });
  }
  try {
    const {
      license_key: key = "",
      buyer_email: rawEmail = "",
      device_id: deviceId = "",
      asset_name: rawAsset = "MetaAdsAgent-source.zip",
      channel: rawChannel = "stable",
      transfer_device: transferDevice = false,
      action = ""
    } = request.body || {};
    if (String(action || "").trim().toLowerCase() === "cloud_install") {
      return registerCloudInstallation(request, response, request.body || {});
    }
    const licenseKey = String(key).trim().toUpperCase();
    const buyerEmail = String(rawEmail).trim().toLowerCase();
    const assetName = String(rawAsset).trim() || "MetaAdsAgent-source.zip";
    const channel = String(rawChannel).trim() || "stable";
    if (!validFormat(licenseKey)) {
      return friendlyFailure(response, "invalid", "Licencia invalida.");
    }
    if (!buyerEmail || !buyerEmail.includes("@")) {
      return friendlyFailure(response, "email_required", "Ingresa el email de compra.");
    }
    if (!deviceId) {
      return friendlyFailure(response, "device_required", "No pude identificar este equipo.");
    }
    const record = await readLicense(licenseKey);
    if (!record) {
      return friendlyFailure(response, "not_found", "No encontramos esta licencia. Contacta soporte.");
    }
    if (record.status !== "active") {
      return friendlyFailure(response, record.status, "Esta licencia no esta activa. Contacta soporte.");
    }
    if (!licenseEmailMatches(record, buyerEmail)) {
      return friendlyFailure(response, "email_mismatch", "El email no coincide con esta licencia.");
    }
    const entitlements = normalizeEntitlements(record);
    record.plan = entitlements.plan;
    record.max_devices = entitlements.max_devices;
    record.workspace_limit = entitlements.workspace_limit;
    record.features = entitlements.features;
    const binding = await ensureDeviceBinding({
      record,
      licenseKey,
      deviceId,
      entitlements,
      transferDevice,
      store: {
        deviceRegistrations,
        isRegisteredDevice,
        registerDevice,
        unregisterDevice,
        resetDeviceRegistrations
      }
    });
    if (!binding.ok) return response.status(200).json({ valid: false, ...binding });
    await writeLicense(record);

    const releases = await readReleases();
    const rawRelease = releases.channels?.[channel];
    const release = rawRelease ? await releaseWithDiscoveredAssets(rawRelease) : null;
    const canonicalAssetName = String(release?.asset_name || "MetaAdsAgent-source.zip").trim();
    // Older installers can keep an asset filename that no longer exists in
    // the current release registry.  The updater always consumes the
    // universal source package, so fall back to the channel's canonical
    // package instead of stranding an otherwise valid lifetime license.
    const asset = releaseAssetByName(release, assetName)
      || releaseAssetByName(release, canonicalAssetName)
      || releaseAssetByName(release, "MetaAdsAgent-source.zip");
    const grantedAssetName = asset
      ? String(asset.asset_name || asset.name || canonicalAssetName || assetName).trim()
      : assetName;
    if (!release || !asset) {
      return friendlyFailure(response, "release_missing", "No encontre la descarga publicada para este instalador. Contacta soporte.");
    }
    const grant = signedReleaseGrant({
      licenseKey,
      buyerEmail,
      deviceId,
      channel,
      assetName: grantedAssetName,
      version: release.version,
      filename: asset.filename,
      contentType: asset.content_type,
      blobPath: asset.blob_path,
      sourceUrl: asset.source_url
    });
    const cloudInstallGrant = signedCloudInstallRegistrationGrant({
      licenseKey,
      buyerEmail,
      deviceId,
      minutes: Number(process.env.CLOUD_INSTALL_REGISTRATION_TOKEN_MINUTES || 360)
    });
    return response.status(200).json({
      valid: true,
      status: "active",
      detail: "Descarga lista.",
      device_binding: binding.device_binding,
      provisional: binding.provisional,
      replaced_provisional: binding.replaced_provisional,
      version: release.version,
      asset_name: grantedAssetName,
      filename: asset.filename,
      sha256: String(asset.sha256 || release.sha256 || "").trim().toLowerCase(),
      improvements: buyerFacingImprovements(release.improvements || []),
      expires_at: grant.expires_at,
      cloud_install_token: cloudInstallGrant.token,
      download_url: `${baseUrl(request)}/api/download/release?token=${encodeURIComponent(grant.token)}`
    });
  } catch (error) {
    console.error("license release failed", {
      name: error?.name || "Error",
      message: error?.message || "unknown_error"
    });
    return response.status(500).json({ valid: false, status: "server_error", detail: "No se pudo preparar tu descarga. Contacta soporte." });
  }
}
