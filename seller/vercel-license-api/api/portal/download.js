import { signedReleaseGrant, verifyPortalSession } from "../../lib/license.js";
import { platformAsset, releaseWithDiscoveredAssets } from "../../lib/download-portal.js";
import { readLicense, readReleases } from "../../lib/store.js";

function baseUrl(request) {
  const host = String(request.headers["x-forwarded-host"] || request.headers.host || "").trim();
  const proto = String(request.headers["x-forwarded-proto"] || "https").trim() || "https";
  return `${proto}://${host}`;
}

function json(response, status, payload) {
  response.setHeader("Cache-Control", "private, no-store");
  response.setHeader("X-Content-Type-Options", "nosniff");
  return response.status(status).json(payload);
}

function friendlyFailure(response, status, detail) {
  return json(response, 200, { valid: false, status, detail });
}

export default async function handler(request, response) {
  if (request.method !== "POST") {
    return json(response, 405, { valid: false, status: "method_not_allowed", detail: "Metodo no permitido." });
  }
  try {
    const { portal_token: token = "", platform: rawPlatform = "" } = request.body || {};
    const session = verifyPortalSession(token);
    if (!session) {
      return friendlyFailure(response, "session_expired", "Tu acceso vencio. Vuelve a ingresar tu email y clave.");
    }
    const platform = String(rawPlatform).trim().toLowerCase();
    if (!["mac", "windows", "linux"].includes(platform)) {
      return friendlyFailure(response, "platform_required", "Elige Mac, Windows o Linux.");
    }
    const record = await readLicense(session.license_key);
    if (!record || record.status !== "active" || String(record.buyer_email || "").toLowerCase() !== session.buyer_email) {
      return friendlyFailure(response, "access_revoked", "No pude confirmar esta compra. Contacta soporte.");
    }
    const releases = await readReleases();
    const release = await releaseWithDiscoveredAssets(releases.channels?.[session.channel || "stable"]);
    const selected = platformAsset(release, platform);
    if (!release || !selected) {
      return friendlyFailure(response, "release_missing", "Todavia no hay instalador publicado para este sistema.");
    }
    const asset = release.assets?.[selected.asset_name];
    const grant = signedReleaseGrant({
      licenseKey: session.license_key,
      buyerEmail: session.buyer_email,
      deviceId: `portal-${platform}`,
      channel: session.channel || "stable",
      assetName: selected.asset_name,
      version: release.version,
      filename: asset.filename,
      contentType: asset.content_type,
      blobPath: asset.blob_path,
      sourceUrl: asset.source_url
    });
    return json(response, 200, {
      valid: true,
      status: "ready",
      detail: "Descarga lista.",
      version: release.version,
      platform,
      filename: asset.filename,
      expires_at: grant.expires_at,
      download_url: `${baseUrl(request)}/api/download/release?token=${encodeURIComponent(grant.token)}`
    });
  } catch {
    return json(response, 500, { valid: false, status: "server_error", detail: "No pude preparar la descarga. Intenta otra vez o contacta soporte." });
  }
}
