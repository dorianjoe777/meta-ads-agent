import {
  createPrivateKey,
  createHash,
  createHmac,
  randomBytes,
  sign as cryptoSign,
  timingSafeEqual
} from "node:crypto";

const PREFIX = "MAO";
const SALT = "meta-ads-operator-v1";
const INDIVIDUAL_FEATURES = ["dashboard", "chat", "telegram", "campaign_creation", "live_actions"];
const AGENCY_FEATURES = [...INDIVIDUAL_FEATURES, "agency_workspaces", "multi_telegram_profiles"];
const KNOWN_FEATURES = new Set(AGENCY_FEATURES);
const PLAN_DEFAULTS = {
  individual: { max_devices: 1, workspace_limit: 1, features: INDIVIDUAL_FEATURES },
  agency: { max_devices: 4, workspace_limit: 50, features: AGENCY_FEATURES }
};

function clean(value) {
  return String(value || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
}

function checksum(body) {
  return createHash("sha256").update(`${SALT}:${body}`).digest("hex").slice(0, 6).toUpperCase();
}

export function formatLicense(seed = "") {
  const body = clean(seed || randomBytes(12).toString("hex")).slice(0, 24);
  const groups = body.match(/.{1,4}/g).join("-");
  return `${PREFIX}-${groups}-${checksum(body)}`;
}

export function validFormat(key) {
  const parts = String(key || "").trim().toUpperCase().split("-");
  if (parts.length < 4 || parts[0] !== PREFIX) return false;
  const supplied = clean(parts.at(-1));
  const body = clean(parts.slice(1, -1).join(""));
  return supplied.length === 6 && body.length >= 8 && supplied === checksum(body);
}

export function entitlementDefaults(plan = "individual") {
  const normalizedPlan = plan === "agency" ? "agency" : "individual";
  return PLAN_DEFAULTS[normalizedPlan];
}

function numberOrDefault(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}

export function normalizeEntitlements(record = {}) {
  const rawFeatures = Array.isArray(record.features)
    ? record.features
    : String(record.features || "").split(",").map((item) => item.trim()).filter(Boolean);
  const planValue = String(record.plan || "").trim().toLowerCase();
  const requestedPlan = planValue === "agency" || (!planValue && rawFeatures.includes("agency_workspaces")) ? "agency" : "individual";
  const defaults = entitlementDefaults(requestedPlan);
  const features = rawFeatures.length
    ? rawFeatures.filter((feature) => KNOWN_FEATURES.has(feature))
    : [...defaults.features];
  const cleanFeatures = requestedPlan === "individual"
    ? features.filter((feature) => !["agency_workspaces", "multi_telegram_profiles"].includes(feature))
    : Array.from(new Set(features));
  return {
    plan: requestedPlan,
    max_devices: requestedPlan === "individual"
      ? 1
      : numberOrDefault(record.max_devices, defaults.max_devices),
    workspace_limit: requestedPlan === "individual"
      ? 1
      : numberOrDefault(record.workspace_limit, defaults.workspace_limit),
    features: cleanFeatures.length ? cleanFeatures : [...defaults.features]
  };
}

function canonical(payload) {
  const safe = Object.fromEntries(
    Object.entries(payload)
      .filter(([key]) => key !== "signature")
      .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
  );
  return Buffer.from(JSON.stringify(safe), "utf8");
}

export function signedUnlock({ licenseKey, buyerEmail, deviceId, features, plan, maxDevices, workspaceLimit }) {
  const entitlements = normalizeEntitlements({ features, plan, max_devices: maxDevices, workspace_limit: workspaceLimit });
  const hours = Number(process.env.LICENSE_UNLOCK_HOURS || 168);
  const issued = new Date();
  const payload = {
    buyer_email: buyerEmail,
    device_id: deviceId,
    expires_at: new Date(issued.getTime() + hours * 3600000).toISOString(),
    features: entitlements.features,
    issued_at: issued.toISOString(),
    license_key: licenseKey,
    max_devices: entitlements.max_devices,
    plan: entitlements.plan,
    workspace_limit: entitlements.workspace_limit
  };
  const privatePem = Buffer.from(process.env.LICENSE_PRIVATE_KEY_B64 || "", "base64").toString("utf8");
  if (!privatePem) {
    throw new Error("LICENSE_PRIVATE_KEY_B64 is not configured");
  }
  const signature = cryptoSign(null, canonical(payload), createPrivateKey(privatePem));
  return { ...payload, signature: signature.toString("base64url") };
}

export function bearerAllowed(request) {
  const supplied = String(request.headers.authorization || "").replace(/^Bearer\s+/i, "");
  const expected = String(process.env.LICENSE_ADMIN_KEY || "");
  if (!supplied || !expected) return false;
  const suppliedBuffer = Buffer.from(supplied);
  const expectedBuffer = Buffer.from(expected);
  return suppliedBuffer.length === expectedBuffer.length && timingSafeEqual(suppliedBuffer, expectedBuffer);
}

function canonicalForHmac(payload) {
  const safe = Object.fromEntries(
    Object.entries(payload)
      .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
  );
  return JSON.stringify(safe);
}

export function signedReleaseGrant({ licenseKey, buyerEmail, deviceId, channel, assetName, version, filename, contentType, sourceUrl, blobPath, minutes: rawMinutes }) {
  const secret = String(process.env.RELEASE_DOWNLOAD_SECRET || "");
  if (!secret) {
    throw new Error("RELEASE_DOWNLOAD_SECRET is not configured");
  }
  const requestedMinutes = Number(rawMinutes);
  const minutes = Number.isFinite(requestedMinutes) && requestedMinutes > 0
    ? Math.min(Math.floor(requestedMinutes), 360)
    : Number(process.env.RELEASE_TOKEN_MINUTES || 15);
  const payload = {
    asset_name: assetName,
    buyer_email: buyerEmail,
    channel,
    content_type: contentType || "application/octet-stream",
    device_id: deviceId,
    expires_at: new Date(Date.now() + minutes * 60000).toISOString(),
    filename: filename || assetName,
    license_key: licenseKey,
    blob_path: blobPath || "",
    source_url: sourceUrl,
    version: version || "latest"
  };
  const body = Buffer.from(canonicalForHmac(payload), "utf8").toString("base64url");
  const signature = createHmac("sha256", secret).update(body).digest("base64url");
  return {
    ...payload,
    token: `${body}.${signature}`
  };
}

export function signedPortalSession({ licenseKey, buyerEmail, channel = "stable", plan = "individual", minutes: rawMinutes }) {
  const secret = String(process.env.RELEASE_DOWNLOAD_SECRET || "");
  if (!secret) {
    throw new Error("RELEASE_DOWNLOAD_SECRET is not configured");
  }
  const requestedMinutes = Number(rawMinutes || process.env.PORTAL_SESSION_MINUTES || 20);
  const minutes = Math.max(1, Math.min(Math.floor(requestedMinutes), 60 * 24 * 30));
  const payload = {
    buyer_email: buyerEmail,
    channel,
    expires_at: new Date(Date.now() + minutes * 60000).toISOString(),
    license_key: licenseKey,
    plan
  };
  const body = Buffer.from(canonicalForHmac(payload), "utf8").toString("base64url");
  const signature = createHmac("sha256", secret).update(body).digest("base64url");
  return {
    ...payload,
    token: `${body}.${signature}`
  };
}

export function verifyPortalSession(token) {
  const secret = String(process.env.RELEASE_DOWNLOAD_SECRET || "");
  if (!secret || !token || !String(token).includes(".")) {
    return null;
  }
  const [body, supplied] = String(token).split(".", 2);
  const expected = createHmac("sha256", secret).update(body).digest("base64url");
  const suppliedBuffer = Buffer.from(String(supplied || ""));
  const expectedBuffer = Buffer.from(expected);
  if (suppliedBuffer.length !== expectedBuffer.length || !timingSafeEqual(suppliedBuffer, expectedBuffer)) {
    return null;
  }
  try {
    const payload = JSON.parse(Buffer.from(body, "base64url").toString("utf8"));
    if (!payload.expires_at || new Date(payload.expires_at).getTime() < Date.now()) {
      return null;
    }
    return payload;
  } catch {
    return null;
  }
}

export function verifyReleaseGrant(token) {
  const secret = String(process.env.RELEASE_DOWNLOAD_SECRET || "");
  if (!secret || !token || !String(token).includes(".")) {
    return null;
  }
  const [body, supplied] = String(token).split(".", 2);
  const expected = createHmac("sha256", secret).update(body).digest("base64url");
  const suppliedBuffer = Buffer.from(String(supplied || ""));
  const expectedBuffer = Buffer.from(expected);
  if (suppliedBuffer.length !== expectedBuffer.length || !timingSafeEqual(suppliedBuffer, expectedBuffer)) {
    return null;
  }
  try {
    const payload = JSON.parse(Buffer.from(body, "base64url").toString("utf8"));
    if (!payload.expires_at || new Date(payload.expires_at).getTime() < Date.now()) {
      return null;
    }
    return payload;
  } catch {
    return null;
  }
}
