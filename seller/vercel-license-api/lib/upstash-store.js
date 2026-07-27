import { createHash } from "node:crypto";

const KEY_PREFIX = "admira:license-api:v1";
const REGISTRY_KEY = `${KEY_PREFIX}:licenses:registry`;
const LICENSE_INDEX_KEY = `${KEY_PREFIX}:licenses:index`;
const RELEASES_KEY = `${KEY_PREFIX}:releases:registry`;

function licenseId(licenseKey) {
  return createHash("sha256").update(String(licenseKey || "")).digest("hex");
}

function deviceIdHash(deviceId) {
  return createHash("sha256").update(String(deviceId || "")).digest("hex");
}

function recordKey(licenseKey) {
  return `${KEY_PREFIX}:license:${licenseId(licenseKey)}`;
}

function deviceKey(licenseKey) {
  return `${KEY_PREFIX}:devices:${licenseId(licenseKey)}`;
}

function devicePath(licenseKey, deviceId) {
  return `licenses/devices/${licenseId(licenseKey)}/${deviceIdHash(deviceId)}.json`;
}

function safeEndpoint(value) {
  let parsed;
  try {
    parsed = new URL(String(value || ""));
  } catch {
    throw new Error("upstash_configuration_invalid");
  }
  if (parsed.protocol !== "https:" || !parsed.hostname.endsWith(".upstash.io") || parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error("upstash_configuration_invalid");
  }
  return parsed.origin;
}

function safeDependencyError(status, retryable = false) {
  const error = new Error("upstash_dependency_failed");
  error.code = "upstash_dependency_failed";
  error.status = Number(status || 0);
  error.retryable = Boolean(retryable);
  return error;
}

export function createUpstashStore(options = {}) {
  const url = safeEndpoint(options.url || process.env.UPSTASH_REDIS_REST_URL);
  const token = String(options.token || process.env.UPSTASH_REDIS_REST_TOKEN || "").trim();
  const fetchImpl = options.fetchImpl || fetch;
  if (token.length < 20) throw new Error("upstash_configuration_invalid");

  async function command(...args) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetchImpl(url, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify(args),
        signal: controller.signal
      });
      if (!response.ok) throw safeDependencyError(response.status, response.status === 429 || response.status >= 500);
      const payload = await response.json();
      if (payload?.error) throw safeDependencyError(502, false);
      return payload?.result;
    } catch (error) {
      if (error?.code === "upstash_dependency_failed") throw error;
      throw safeDependencyError(0, true);
    } finally {
      clearTimeout(timeout);
    }
  }

  async function readJson(key, fallback) {
    const value = await command("GET", key);
    if (value === null || value === undefined || value === "") return fallback;
    try {
      return typeof value === "string" ? JSON.parse(value) : value;
    } catch {
      return fallback;
    }
  }

  return {
    async readRegistry() {
      const registry = await readJson(REGISTRY_KEY, { licenses: [] });
      const indexedLicenseKeys = await command("SMEMBERS", LICENSE_INDEX_KEY);
      if (!Array.isArray(indexedLicenseKeys) || !indexedLicenseKeys.length) return registry;
      const storedRecords = await command("MGET", ...indexedLicenseKeys.map(recordKey));
      const merged = new Map(
        (Array.isArray(registry?.licenses) ? registry.licenses : [])
          .filter((record) => record?.license_key)
          .map((record) => [record.license_key, record])
      );
      for (const value of Array.isArray(storedRecords) ? storedRecords : []) {
        try {
          const record = typeof value === "string" ? JSON.parse(value) : value;
          if (record?.license_key) merged.set(record.license_key, record);
        } catch {
          // A malformed indexed record is ignored; other licenses remain available.
        }
      }
      return { ...(registry || {}), licenses: [...merged.values()] };
    },
    async writeRegistry(registry) {
      await command("SET", REGISTRY_KEY, JSON.stringify(registry));
      const licenseKeys = [...new Set(
        (Array.isArray(registry?.licenses) ? registry.licenses : [])
          .map((record) => String(record?.license_key || "").trim())
          .filter(Boolean)
      )];
      if (licenseKeys.length) await command("SADD", LICENSE_INDEX_KEY, ...licenseKeys);
    },
    async readReleases() {
      return readJson(RELEASES_KEY, { channels: {} });
    },
    async writeReleases(registry) {
      await command("SET", RELEASES_KEY, JSON.stringify(registry));
    },
    async readLicense(licenseKey) {
      const direct = await readJson(recordKey(licenseKey), null);
      if (direct) return direct;
      const registry = await readJson(REGISTRY_KEY, { licenses: [] });
      return registry.licenses.find((item) => item.license_key === licenseKey) || null;
    },
    async writeLicense(record) {
      await command("SET", recordKey(record.license_key), JSON.stringify(record));
      await command("SADD", LICENSE_INDEX_KEY, record.license_key);
    },
    async deviceRegistrations(licenseKey) {
      const members = await command("SMEMBERS", deviceKey(licenseKey));
      return (Array.isArray(members) ? members : []).map((pathname) => ({ pathname }));
    },
    async registerDevice(licenseKey, deviceId) {
      const pathname = devicePath(licenseKey, deviceId);
      await command("SADD", deviceKey(licenseKey), pathname);
      return pathname;
    },
    async unregisterDevice(licenseKey, deviceId) {
      const pathname = devicePath(licenseKey, deviceId);
      await command("SREM", deviceKey(licenseKey), pathname);
      return true;
    },
    async importDeviceRegistration(licenseKey, pathname) {
      const prefix = `licenses/devices/${licenseId(licenseKey)}/`;
      const normalized = String(pathname || "");
      if (!normalized.startsWith(prefix) || !/^[a-f0-9]{64}\.json$/.test(normalized.slice(prefix.length))) {
        throw new Error("invalid_device_registration");
      }
      await command("SADD", deviceKey(licenseKey), normalized);
      return normalized;
    },
    async resetDeviceRegistrations(licenseKey) {
      const count = Number(await command("SCARD", deviceKey(licenseKey)) || 0);
      if (count) await command("DEL", deviceKey(licenseKey));
      return count;
    },
    isRegisteredDevice(blobs, licenseKey, deviceId) {
      return blobs.some((blob) => blob.pathname === devicePath(licenseKey, deviceId));
    },
    backendStatus() {
      return { backend: "upstash", configured: true };
    }
  };
}

let singleton;
function store() {
  singleton ||= createUpstashStore();
  return singleton;
}

export const readRegistry = (...args) => store().readRegistry(...args);
export const writeRegistry = (...args) => store().writeRegistry(...args);
export const readReleases = (...args) => store().readReleases(...args);
export const writeReleases = (...args) => store().writeReleases(...args);
export const readLicense = (...args) => store().readLicense(...args);
export const writeLicense = (...args) => store().writeLicense(...args);
export const deviceRegistrations = (...args) => store().deviceRegistrations(...args);
export const registerDevice = (...args) => store().registerDevice(...args);
export const unregisterDevice = (...args) => store().unregisterDevice(...args);
export const importDeviceRegistration = (...args) => store().importDeviceRegistration(...args);
export const resetDeviceRegistrations = (...args) => store().resetDeviceRegistrations(...args);
export const isRegisteredDevice = (...args) => store().isRegisteredDevice(...args);
export const backendStatus = () => ({ backend: "upstash", configured: Boolean(process.env.UPSTASH_REDIS_REST_URL && process.env.UPSTASH_REDIS_REST_TOKEN) });
