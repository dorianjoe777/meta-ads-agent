import { normalizeEntitlements, signedReleaseGrant, validFormat } from "../../lib/license.js";
import { buyerFacingImprovements, releaseAssetByName, releaseWithDiscoveredAssets } from "../../lib/download-portal.js";
import { deviceRegistrations, isRegisteredDevice, readLicense, readReleases, registerDevice, resetDeviceRegistrations, writeLicense } from "../../lib/store.js";

function baseUrl(request) {
  const host = String(request.headers["x-forwarded-host"] || request.headers.host || "").trim();
  const proto = String(request.headers["x-forwarded-proto"] || "https").trim() || "https";
  return `${proto}://${host}`;
}

function friendlyFailure(response, status, detail) {
  return response.status(200).json({ valid: false, status, detail });
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
      transfer_device: transferDevice = false
    } = request.body || {};
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
    if (String(record.buyer_email).toLowerCase() !== buyerEmail) {
      return friendlyFailure(response, "email_mismatch", "El email no coincide con esta licencia.");
    }
    const entitlements = normalizeEntitlements(record);
    record.plan = entitlements.plan;
    record.max_devices = entitlements.max_devices;
    record.workspace_limit = entitlements.workspace_limit;
    record.features = entitlements.features;
    const registrations = await deviceRegistrations(licenseKey);
    if (!isRegisteredDevice(registrations, licenseKey, deviceId)) {
      if (registrations.length >= entitlements.max_devices) {
        if (transferDevice && entitlements.plan === "individual" && entitlements.max_devices === 1) {
          await resetDeviceRegistrations(licenseKey);
          record.devices = [];
          record.last_device_transfer_at = new Date().toISOString();
        } else {
          return response.status(200).json({
            valid: false,
            status: "device_limit",
            transfer_available: entitlements.plan === "individual" && entitlements.max_devices === 1,
            detail: entitlements.plan === "individual" && entitlements.max_devices === 1
              ? "Esta licencia ya esta activa en otro equipo. Puedes transferirla a este equipo si ya no usaras el anterior."
              : "Esta licencia ya alcanzo el limite de equipos. Contacta soporte."
          });
        }
      }
      await registerDevice(licenseKey, deviceId);
    }
    record.devices ||= [];
    if (!record.devices.includes(deviceId)) record.devices.push(deviceId);
    record.last_activation_at = new Date().toISOString();
    const localInstall = { ...(record.install_state?.local || {}) };
    localInstall.activated_at ||= record.last_activation_at;
    localInstall.last_activation_seen_at = record.last_activation_at;
    localInstall.last_event = "local_activated";
    localInstall.last_event_at = record.last_activation_at;
    record.install_state = { ...(record.install_state || {}), local: localInstall };
    await writeLicense(record);

    const releases = await readReleases();
    const rawRelease = releases.channels?.[channel];
    const release = rawRelease ? await releaseWithDiscoveredAssets(rawRelease) : null;
    const asset = releaseAssetByName(release, assetName);
    if (!release || !asset) {
      return friendlyFailure(response, "release_missing", "No encontre la descarga publicada para este instalador. Contacta soporte.");
    }
    const grant = signedReleaseGrant({
      licenseKey,
      buyerEmail,
      deviceId,
      channel,
      assetName,
      version: release.version,
      filename: asset.filename,
      contentType: asset.content_type,
      blobPath: asset.blob_path,
      sourceUrl: asset.source_url
    });
    return response.status(200).json({
      valid: true,
      status: "active",
      detail: "Descarga lista.",
      version: release.version,
      asset_name: assetName,
      filename: asset.filename,
      improvements: buyerFacingImprovements(release.improvements || []),
      expires_at: grant.expires_at,
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
