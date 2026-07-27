import { normalizeEntitlements, signedReleaseGrant, validFormat } from "../../lib/license.js";
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
  writeLicense
} from "../../lib/store.js";

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
