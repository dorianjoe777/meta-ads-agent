import * as blob from "./blob-store.js";
import * as upstash from "./upstash-store.js";

function upstashConfigured() {
  return Boolean(process.env.UPSTASH_REDIS_REST_URL && process.env.UPSTASH_REDIS_REST_TOKEN);
}

function selectedBackend() {
  const requested = String(process.env.LICENSE_STORE_BACKEND || "auto").trim().toLowerCase();
  if (["blob", "upstash", "dual"].includes(requested)) return requested;
  return upstashConfigured() ? "upstash" : "blob";
}

async function dualRead(upstashRead, blobRead, usable) {
  try {
    const primary = await upstashRead();
    if (usable(primary)) return primary;
  } catch {
    // During migration, Blob remains a read fallback. Never leak dependency details.
  }
  return blobRead();
}

async function dualWrite(upstashWrite, blobWrite) {
  await upstashWrite();
  await blobWrite().catch(() => {});
}

export async function readRegistry() {
  const backend = selectedBackend();
  if (backend === "blob") return blob.readRegistry();
  if (backend === "upstash") return upstash.readRegistry();
  return dualRead(upstash.readRegistry, blob.readRegistry, (value) => Array.isArray(value?.licenses) && value.licenses.length > 0);
}

export async function writeRegistry(registry) {
  const backend = selectedBackend();
  if (backend === "blob") return blob.writeRegistry(registry);
  if (backend === "upstash") return upstash.writeRegistry(registry);
  return dualWrite(() => upstash.writeRegistry(registry), () => blob.writeRegistry(registry));
}

export async function readReleases() {
  // Release assets are published to private Blob storage. Keep their registry
  // there as the source of truth even when licenses themselves live in Upstash;
  // otherwise the portal can offer a stale platform installer after a release.
  if (Boolean(process.env.BLOB_READ_WRITE_TOKEN)) {
    try {
      const releases = await blob.readReleases();
      if (releases?.channels && Object.keys(releases.channels).length > 0) return releases;
    } catch {
      // Preserve the configured store as a fallback during a Blob outage.
    }
  }
  const backend = selectedBackend();
  if (backend === "blob") return blob.readReleases();
  if (backend === "upstash") return upstash.readReleases();
  return dualRead(upstash.readReleases, blob.readReleases, (value) => value?.channels && Object.keys(value.channels).length > 0);
}

export async function writeReleases(registry) {
  const backend = selectedBackend();
  if (backend === "blob") return blob.writeReleases(registry);
  if (backend === "upstash") {
    if (Boolean(process.env.BLOB_READ_WRITE_TOKEN)) {
      return dualWrite(() => upstash.writeReleases(registry), () => blob.writeReleases(registry));
    }
    return upstash.writeReleases(registry);
  }
  return dualWrite(() => upstash.writeReleases(registry), () => blob.writeReleases(registry));
}

export async function readLicense(licenseKey) {
  const backend = selectedBackend();
  if (backend === "blob") return blob.readLicense(licenseKey);
  if (backend === "upstash") return upstash.readLicense(licenseKey);
  return dualRead(() => upstash.readLicense(licenseKey), () => blob.readLicense(licenseKey), Boolean);
}

export async function writeLicense(record) {
  const backend = selectedBackend();
  if (backend === "blob") return blob.writeLicense(record);
  if (backend === "upstash") return upstash.writeLicense(record);
  return dualWrite(() => upstash.writeLicense(record), () => blob.writeLicense(record));
}

export async function deviceRegistrations(licenseKey) {
  const backend = selectedBackend();
  if (backend === "blob") return blob.deviceRegistrations(licenseKey);
  if (backend === "upstash") return upstash.deviceRegistrations(licenseKey);
  return dualRead(() => upstash.deviceRegistrations(licenseKey), () => blob.deviceRegistrations(licenseKey), (value) => Array.isArray(value) && value.length > 0);
}

export async function registerDevice(licenseKey, deviceId) {
  const backend = selectedBackend();
  if (backend === "blob") return blob.registerDevice(licenseKey, deviceId);
  if (backend === "upstash") return upstash.registerDevice(licenseKey, deviceId);
  let pathname = "";
  await dualWrite(async () => { pathname = await upstash.registerDevice(licenseKey, deviceId); }, () => blob.registerDevice(licenseKey, deviceId));
  return pathname;
}

export async function unregisterDevice(licenseKey, deviceId) {
  const backend = selectedBackend();
  if (backend === "blob") return blob.unregisterDevice(licenseKey, deviceId);
  if (backend === "upstash") return upstash.unregisterDevice(licenseKey, deviceId);
  await dualWrite(
    () => upstash.unregisterDevice(licenseKey, deviceId),
    () => blob.unregisterDevice(licenseKey, deviceId)
  );
  return true;
}

export async function resetDeviceRegistrations(licenseKey) {
  const backend = selectedBackend();
  if (backend === "blob") return blob.resetDeviceRegistrations(licenseKey);
  if (backend === "upstash") return upstash.resetDeviceRegistrations(licenseKey);
  let count = 0;
  await dualWrite(async () => { count = await upstash.resetDeviceRegistrations(licenseKey); }, () => blob.resetDeviceRegistrations(licenseKey));
  return count;
}

export function isRegisteredDevice(blobs, licenseKey, deviceId) {
  return selectedBackend() === "blob" ? blob.isRegisteredDevice(blobs, licenseKey, deviceId) : upstash.isRegisteredDevice(blobs, licenseKey, deviceId);
}

export function storeBackendStatus() {
  return { backend: selectedBackend(), upstash_configured: upstashConfigured(), blob_configured: Boolean(process.env.BLOB_READ_WRITE_TOKEN) };
}
