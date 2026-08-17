import { del, get, list, put } from "@vercel/blob";
import { createHash } from "node:crypto";

const REGISTRY_PATH = "licenses/registry.json";
const RELEASES_PATH = "releases/registry.json";

function recordPath(licenseKey) {
  const id = createHash("sha256").update(String(licenseKey || "")).digest("hex");
  return `licenses/by-key/${id}.json`;
}

function licenseId(licenseKey) {
  return createHash("sha256").update(String(licenseKey || "")).digest("hex");
}

function devicePrefix(licenseKey) {
  return `licenses/devices/${licenseId(licenseKey)}/`;
}

function devicePath(licenseKey, deviceId) {
  const id = createHash("sha256").update(String(deviceId || "")).digest("hex");
  return `${devicePrefix(licenseKey)}${id}.json`;
}

async function readJson(pathname, fallback) {
  const result = await get(pathname, { access: "private" });
  if (!result || result.statusCode !== 200) return fallback;
  const text = await new Response(result.stream).text();
  try {
    return JSON.parse(text);
  } catch {
    return fallback;
  }
}

export async function readRegistry() {
  return readJson(REGISTRY_PATH, { licenses: [] });
}

export async function writeRegistry(registry) {
  await put(REGISTRY_PATH, JSON.stringify(registry, null, 2), {
    access: "private", contentType: "application/json", allowOverwrite: true, cacheControlMaxAge: 60
  });
}

export async function readReleases() {
  return readJson(RELEASES_PATH, { channels: {} });
}

export async function writeReleases(registry) {
  await put(RELEASES_PATH, JSON.stringify(registry, null, 2), {
    access: "private", contentType: "application/json", allowOverwrite: true, cacheControlMaxAge: 60
  });
}

export async function readLicense(licenseKey) {
  const direct = await readJson(recordPath(licenseKey), null);
  if (direct) return direct;
  const registry = await readRegistry();
  return registry.licenses.find((item) => item.license_key === licenseKey) || null;
}

export async function writeLicense(record) {
  await put(recordPath(record.license_key), JSON.stringify(record, null, 2), {
    access: "private", contentType: "application/json", allowOverwrite: true, cacheControlMaxAge: 60
  });
}

export async function deviceRegistrations(licenseKey) {
  const result = await list({ prefix: devicePrefix(licenseKey), limit: 1000 });
  return result.blobs || [];
}

export async function registerDevice(licenseKey, deviceId) {
  const pathname = devicePath(licenseKey, deviceId);
  await put(pathname, JSON.stringify({ registered_at: new Date().toISOString() }), {
    access: "private", contentType: "application/json", allowOverwrite: true, cacheControlMaxAge: 60
  });
  return pathname;
}

export async function unregisterDevice(licenseKey, deviceId) {
  await del(devicePath(licenseKey, deviceId));
  return true;
}

export async function resetDeviceRegistrations(licenseKey) {
  const registrations = await deviceRegistrations(licenseKey);
  if (!registrations.length) return 0;
  await del(registrations.map((blob) => blob.pathname));
  return registrations.length;
}

export function isRegisteredDevice(blobs, licenseKey, deviceId) {
  return blobs.some((blob) => blob.pathname === devicePath(licenseKey, deviceId));
}

export function backendStatus() {
  return { backend: "blob", configured: Boolean(process.env.BLOB_READ_WRITE_TOKEN) };
}
