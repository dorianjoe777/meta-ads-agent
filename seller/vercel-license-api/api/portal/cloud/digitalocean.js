import { signedReleaseGrant, verifyPortalSession } from "../../../lib/license.js";
import { releaseWithDiscoveredAssets } from "../../../lib/download-portal.js";
import { readLicense, readReleases, writeLicense } from "../../../lib/store.js";
import { decryptPortalSecret, encryptPortalSecret } from "../../../lib/secret-vault.js";
import {
  buildDigitalOceanCloudInit,
  cloudAccessSecret,
  currentClientIp,
  digitalOceanFirewallPayload,
  dropletIpv4,
  installId,
  normalizeChoice,
  publicCloudOptions,
  validateDigitalOceanToken,
  validateSshPublicKey
} from "../../../lib/digitalocean-cloud.js";

const DO_API = "https://api.digitalocean.com/v2";
const CLOUD_ACCESS_PORT = "7870";
const CLOUD_HTTPS_PORT = "443";
const CLOUD_HTTP_CHALLENGE_PORT = "80";
const CLOUDFLARE_API = "https://api.cloudflare.com/client/v4";
const VERCEL_API = "https://api.vercel.com";

function baseUrl(request) {
  const host = String(request.headers["x-forwarded-host"] || request.headers.host || "").trim();
  const proto = String(request.headers["x-forwarded-proto"] || "https").trim() || "https";
  return `${proto}://${host}`;
}

function safePublicHttpsBaseUrl(value = "") {
  try {
    const url = new URL(String(value || "").trim());
    const host = url.hostname.toLowerCase();
    if (url.protocol !== "https:" || !host || host === "localhost" || host.endsWith(".localhost")) return "";
    if (host === "127.0.0.1" || host === "::1" || /^\d+\.\d+\.\d+\.\d+$/.test(host)) return "";
    return `https://${host}`;
  } catch {
    return "";
  }
}

function cloudBootstrapBaseUrl(request) {
  const configured = safePublicHttpsBaseUrl(process.env.CLOUD_BOOTSTRAP_BASE_URL || process.env.LICENSE_BOOTSTRAP_URL);
  if (configured) return configured;
  const vercelHost = String(process.env.VERCEL_PROJECT_PRODUCTION_URL || process.env.VERCEL_URL || "").trim();
  const vercelUrl = safePublicHttpsBaseUrl(vercelHost.startsWith("http") ? vercelHost : `https://${vercelHost}`);
  return vercelUrl || baseUrl(request);
}

function json(response, status, payload) {
  response.setHeader("Cache-Control", "private, no-store");
  response.setHeader("X-Content-Type-Options", "nosniff");
  return response.status(status).json(payload);
}

function friendlyFailure(response, status, detail) {
  return json(response, 200, { valid: false, status, detail });
}

async function doRequest(token, path, { method = "GET", body = null } = {}) {
  const upstream = await fetch(`${DO_API}${path}`, {
    method,
    headers: {
      "Authorization": `Bearer ${token}`,
      "Content-Type": "application/json",
      "Accept": "application/json",
      "User-Agent": "admiro-ai-cloud-installer"
    },
    body: body ? JSON.stringify(body) : undefined
  });
  const data = await upstream.json().catch(() => ({}));
  if (!upstream.ok) {
    const id = data?.id || data?.error || "digitalocean_error";
    const message = data?.message || "DigitalOcean rechazo la solicitud.";
    const error = new Error(`${id}: ${message}`);
    error.statusCode = upstream.status;
    error.doStatus = String(id);
    error.doMethod = method;
    error.doPath = path;
    throw error;
  }
  return data;
}

function cloudDashboardBaseDomain() {
  const raw = String(process.env.CLOUD_DASHBOARD_BASE_DOMAIN || process.env.CLOUD_DASHBOARD_DOMAIN || "").trim().toLowerCase();
  const cleaned = raw.replace(/^https?:\/\//, "").replace(/\/.*$/, "").replace(/^\.+|\.+$/g, "");
  return /^[a-z0-9.-]{4,253}$/.test(cleaned) && cleaned.includes(".") ? cleaned : "";
}

function cloudDnsProvider() {
  const configured = String(process.env.DNS_PROVIDER || process.env.CLOUD_DASHBOARD_DNS_PROVIDER || "").trim().toLowerCase();
  if (configured === "vercel" || configured === "cloudflare") return configured;
  if (String(process.env.VERCEL_DNS_TOKEN || "").trim()) return "vercel";
  if (String(process.env.CLOUDFLARE_API_TOKEN || "").trim()) return "cloudflare";
  return "";
}

function cloudDnsAutomationConfigured() {
  const provider = cloudDnsProvider();
  if (!cloudDashboardBaseDomain()) return false;
  if (provider === "vercel") {
    return Boolean(String(process.env.VERCEL_DNS_TOKEN || "").trim() && vercelDnsDomain());
  }
  if (provider === "cloudflare") {
    return Boolean(String(process.env.CLOUDFLARE_API_TOKEN || "").trim() && String(process.env.CLOUDFLARE_ZONE_ID || "").trim());
  }
  return false;
}

function cloudHostnameForInstall(id = "") {
  if (!cloudDnsAutomationConfigured()) return "";
  const base = cloudDashboardBaseDomain();
  const safeId = String(id || "").trim().toLowerCase().replace(/[^a-z0-9-]/g, "");
  return base && safeId ? `${safeId}.${base}` : "";
}

function cloudDashboardHttpsUrl(hostname = "") {
  const host = String(hostname || "").trim().toLowerCase();
  return host ? `https://${host}` : "";
}

function dashboardUrls({ ip = "", dashboardPort = "7871", accessGatePort = CLOUD_ACCESS_PORT, accessSecret = "", hostname = "", dnsActive = false } = {}) {
  const httpUrl = ip ? `http://${ip}:${dashboardPort}` : "";
  const httpsUrl = hostname && dnsActive ? cloudDashboardHttpsUrl(hostname) : "";
  return {
    dashboard_url: httpsUrl || httpUrl,
    dashboard_http_url: httpUrl,
    dashboard_https_url: httpsUrl,
    cloud_open_url: ip && accessSecret ? `http://${ip}:${accessGatePort}/open/${accessSecret}` : ""
  };
}

async function ensureCloudflareDnsRecord(hostname = "", ip = "") {
  const host = String(hostname || "").trim().toLowerCase();
  const content = validIpv4(ip);
  if (!host || !content) {
    return { status: "not_needed" };
  }
  const token = String(process.env.CLOUDFLARE_API_TOKEN || "").trim();
  const zoneId = String(process.env.CLOUDFLARE_ZONE_ID || "").trim();
  if (!token || !zoneId) {
    return { status: "not_configured", detail: "DNS cloud no configurado en el servidor de licencias." };
  }
  const headers = {
    "Authorization": `Bearer ${token}`,
    "Content-Type": "application/json",
    "Accept": "application/json"
  };
  const listUrl = `${CLOUDFLARE_API}/zones/${encodeURIComponent(zoneId)}/dns_records?type=A&name=${encodeURIComponent(host)}&per_page=1`;
  const listed = await fetch(listUrl, { headers });
  const listData = await listed.json().catch(() => ({}));
  if (!listed.ok || listData.success === false) {
    return { status: "failed", detail: "No pude revisar el DNS cloud." };
  }
  const existing = Array.isArray(listData.result) ? listData.result[0] : null;
  const body = {
    type: "A",
    name: host,
    content,
    ttl: 120,
    proxied: String(process.env.CLOUDFLARE_DNS_PROXIED || "false").toLowerCase() === "true"
  };
  const writeUrl = existing?.id
    ? `${CLOUDFLARE_API}/zones/${encodeURIComponent(zoneId)}/dns_records/${encodeURIComponent(existing.id)}`
    : `${CLOUDFLARE_API}/zones/${encodeURIComponent(zoneId)}/dns_records`;
  const written = await fetch(writeUrl, {
    method: existing?.id ? "PUT" : "POST",
    headers,
    body: JSON.stringify(body)
  });
  const writeData = await written.json().catch(() => ({}));
  if (!written.ok || writeData.success === false) {
    return { status: "failed", detail: "No pude crear el DNS cloud." };
  }
  return {
    status: "active",
    provider: "cloudflare",
    hostname: host,
    record_id: writeData.result?.id || existing?.id || "",
    proxied: body.proxied
  };
}

function vercelDnsDomain() {
  const raw = String(process.env.VERCEL_DNS_DOMAIN || process.env.VERCEL_DOMAIN || "").trim().toLowerCase();
  const cleaned = raw.replace(/^https?:\/\//, "").replace(/\/.*$/, "").replace(/^\.+|\.+$/g, "");
  return /^[a-z0-9.-]{4,253}$/.test(cleaned) && cleaned.includes(".") ? cleaned : "";
}

function vercelRecordName(hostname = "", domain = "") {
  const host = String(hostname || "").trim().toLowerCase().replace(/^\.+|\.+$/g, "");
  const zone = String(domain || "").trim().toLowerCase().replace(/^\.+|\.+$/g, "");
  if (!host || !zone || host === zone || !host.endsWith(`.${zone}`)) return "";
  const relative = host.slice(0, -(zone.length + 1));
  return /^[a-z0-9._-]{1,253}$/.test(relative) ? relative : "";
}

function withVercelTeamParams(path = "") {
  const url = new URL(`${VERCEL_API}${path}`);
  const teamId = String(process.env.VERCEL_DNS_TEAM_ID || process.env.VERCEL_TEAM_ID || "").trim();
  const slug = String(process.env.VERCEL_DNS_TEAM_SLUG || process.env.VERCEL_TEAM_SLUG || "").trim();
  if (teamId) url.searchParams.set("teamId", teamId);
  if (slug) url.searchParams.set("slug", slug);
  return url.toString();
}

async function vercelRequest(path, { method = "GET", body = null } = {}) {
  const token = String(process.env.VERCEL_DNS_TOKEN || "").trim();
  if (!token) {
    return { ok: false, status: 401, data: {}, detail: "Token DNS de Vercel no configurado." };
  }
  const upstream = await fetch(withVercelTeamParams(path), {
    method,
    headers: {
      "Authorization": `Bearer ${token}`,
      "Content-Type": "application/json",
      "Accept": "application/json"
    },
    body: body ? JSON.stringify(body) : undefined
  });
  const data = await upstream.json().catch(() => ({}));
  return {
    ok: upstream.ok,
    status: upstream.status,
    data,
    detail: data?.error?.message || data?.message || ""
  };
}

async function ensureVercelDnsRecord(hostname = "", ip = "") {
  const host = String(hostname || "").trim().toLowerCase();
  const content = validIpv4(ip);
  const domain = vercelDnsDomain();
  const name = vercelRecordName(host, domain);
  if (!host || !content) return { status: "not_needed" };
  if (!domain || !name) {
    return { status: "not_configured", provider: "vercel", detail: "DNS cloud de Vercel no configurado para este dominio." };
  }
  const listed = await vercelRequest(`/v4/domains/${encodeURIComponent(domain)}/records?limit=100`);
  if (!listed.ok) {
    return { status: "failed", provider: "vercel", detail: listed.detail || "No pude revisar el DNS en Vercel." };
  }
  const records = Array.isArray(listed.data?.records)
    ? listed.data.records
    : (Array.isArray(listed.data?.dnsRecords) ? listed.data.dnsRecords : []);
  const existing = records.find((record) => {
    const recordName = String(record.name || "").trim().toLowerCase();
    const recordType = String(record.type || record.recordType || "").trim().toUpperCase();
    return recordName === name && recordType === "A";
  });
  const body = {
    name,
    type: "A",
    value: content,
    ttl: 60,
    comment: "Admira IA cloud dashboard"
  };
  const existingValue = String(existing?.value || existing?.content || existing?.data || "").trim();
  if (existing && existingValue === content) {
    return {
      status: "active",
      provider: "vercel",
      hostname: host,
      record_id: existing.id || existing.uid || ""
    };
  }
  if (existing?.id || existing?.uid) {
    const recordId = existing.id || existing.uid;
    const updated = await vercelRequest(`/v1/domains/records/${encodeURIComponent(recordId)}`, {
      method: "PATCH",
      body
    });
    if (!updated.ok) {
      return { status: "failed", provider: "vercel", detail: updated.detail || "No pude actualizar el DNS en Vercel." };
    }
    return {
      status: "active",
      provider: "vercel",
      hostname: host,
      record_id: updated.data?.id || updated.data?.uid || recordId
    };
  }
  const created = await vercelRequest(`/v2/domains/${encodeURIComponent(domain)}/records`, {
    method: "POST",
    body
  });
  if (!created.ok) {
    return { status: "failed", provider: "vercel", detail: created.detail || "No pude crear el DNS en Vercel." };
  }
  return {
    status: "active",
    provider: "vercel",
    hostname: host,
    record_id: created.data?.uid || created.data?.id || ""
  };
}

async function ensureCloudDnsRecord(hostname = "", ip = "") {
  const provider = cloudDnsProvider();
  if (provider === "vercel") {
    return ensureVercelDnsRecord(hostname, ip);
  }
  if (provider === "cloudflare") {
    return ensureCloudflareDnsRecord(hostname, ip);
  }
  return { status: "not_configured", provider: "", detail: "DNS cloud no configurado en el servidor de licencias." };
}

async function ensureSshKey(token, name, publicKey) {
  try {
    const created = await doRequest(token, "/account/keys", {
      method: "POST",
      body: { name, public_key: publicKey }
    });
    return created.ssh_key;
  } catch (error) {
    if (error.statusCode !== 422) {
      throw error;
    }
    const listed = await doRequest(token, "/account/keys?per_page=200");
    const existing = (listed.ssh_keys || []).find((key) => String(key.public_key || "").trim() === publicKey);
    if (!existing) {
      throw error;
    }
    return existing;
  }
}

async function createTag(token, tag) {
  try {
    await doRequest(token, "/tags", { method: "POST", body: { name: tag } });
  } catch (error) {
    if (error.statusCode !== 409 && error.statusCode !== 422) {
      throw error;
    }
  }
}

function sourceZipAsset(release = {}) {
  const assets = release.assets || {};
  const version = String(release.version || "").toLowerCase();
  const candidates = Object.entries(assets).map(([name, asset]) => {
    const filename = String(asset?.filename || name).toLowerCase();
    const sourceZip = filename === "metaadsagent-source.zip" || filename.endsWith("-source.zip");
    let score = sourceZip ? 10 : -1;
    if (sourceZip && version && filename.includes(version)) score += 50;
    if (sourceZip && filename === "metaadsagent-source.zip") score += 30;
    if (sourceZip && asset?.blob_path) score += 20;
    if (sourceZip && asset?.source_url) score -= 5;
    return { entry: [name, asset], score };
  });
  return candidates
    .filter((candidate) => candidate.score >= 0)
    .sort((left, right) => right.score - left.score)[0]?.entry || null;
}

function digitalOceanErrorDetail(error) {
  const status = String(error?.doStatus || "");
  const statusLower = status.toLowerCase();
  if (statusLower.includes("forbidden") || error?.statusCode === 403) {
    return "El token de DigitalOcean esta activo, pero no tiene permiso para modificar el firewall. Crea o pega un token con permiso de escritura para Firewalls y Droplets, y vuelve a abrir el dashboard.";
  }
  if (statusLower.includes("unauthorized") || error?.statusCode === 401) {
    return "DigitalOcean no acepto ese token. Revisa que este activo y tenga permisos para Droplets, Firewalls, Tags y SSH Keys.";
  }
  if (status.includes("unprocessable") || error?.statusCode === 422) {
    return "DigitalOcean no pudo crear el servidor con esos datos. Revisa la region, el tamano y la llave SSH.";
  }
  return "No pude crear el servidor en DigitalOcean. Revisa el token o intenta otra vez.";
}

function digitalOceanDeleteErrorDetail(error) {
  const status = String(error?.doStatus || "");
  const statusLower = status.toLowerCase();
  if (statusLower.includes("forbidden") || error?.statusCode === 403) {
    return "El token de DigitalOcean esta activo, pero no tiene permiso para borrar este servidor. Pega un token con permiso de escritura para Droplets.";
  }
  if (statusLower.includes("unauthorized") || error?.statusCode === 401) {
    return "DigitalOcean no acepto ese token. Pega un token activo con permiso para borrar Droplets.";
  }
  if (digitalOceanResourceMissing(error)) {
    return "Ese Droplet ya no existe en DigitalOcean. Limpie el portal para que puedas crear uno nuevo.";
  }
  return "No pude borrar el Droplet en DigitalOcean. Revisa el token o intenta otra vez.";
}

function digitalOceanResourceMissing(error) {
  const status = String(error?.doStatus || "").toLowerCase();
  return error?.statusCode === 404 || status.includes("not_found") || status.includes("not found");
}

async function clearCloudInstallation(record = {}, reason = "buyer_reset") {
  const installState = { ...(record.install_state || {}) };
  const clearedAt = new Date().toISOString();
  await writeLicense({
    ...record,
    cloud_installation: null,
    cloud_installation_reset_at: clearedAt,
    cloud_installation_reset_reason: reason,
    install_state: {
      ...installState,
      cloud: {
        installed: false,
        status: "not_started",
        progress: 0,
        dashboard_available: false,
        cleared_at: clearedAt,
        reset_reason: reason
      }
    }
  });
  return {
    valid: true,
    status: "not_started",
    ready: false,
    progress: 0,
    stage: "sin_instalacion",
    cloud_installation: null,
    install_state: { cloud: {}, local: installState.local || {} },
    detail: "Listo. Ya puedes crear un servidor nuevo."
  };
}

async function clearIfDigitalOceanDropletMissing(record = {}, digitalOceanToken = "") {
  const cloud = record.cloud_installation || null;
  if (!cloud?.droplet_id || !validateDigitalOceanToken(digitalOceanToken)) {
    return null;
  }
  if (minutesSince(cloud.created_at || cloud.install_started_at) < 1) {
    return null;
  }
  try {
    await doRequest(digitalOceanToken, `/droplets/${cloud.droplet_id}`);
    return null;
  } catch (error) {
    if (!digitalOceanResourceMissing(error)) {
      return null;
    }
    return clearCloudInstallation(record, "droplet_missing_in_digitalocean");
  }
}

export async function deleteDigitalOceanCloudInstall(record = {}, digitalOceanToken = "", dependencies = {}) {
  const requestDigitalOcean = dependencies.doRequest || doRequest;
  const clearInstallation = dependencies.clearCloudInstallation || clearCloudInstallation;
  const cloud = record.cloud_installation || null;
  const provider = String(cloud?.provider || "digitalocean").trim().toLowerCase();
  const dropletId = String(cloud?.droplet_id || "").trim();
  const firewallId = String(cloud?.firewall_id || "").trim();
  if (!cloud || !dropletId) {
    return clearInstallation(record, "buyer_delete_requested_no_saved_droplet");
  }
  if (provider && provider !== "digitalocean") {
    const error = new Error("cloud_provider_not_supported");
    error.friendlyDetail = "Este boton solo puede borrar servidores creados en DigitalOcean.";
    throw error;
  }
  if (!/^\d+$/.test(dropletId)) {
    const error = new Error("invalid_droplet_id");
    error.friendlyDetail = "No pude confirmar el ID del Droplet guardado. Borralo en DigitalOcean y marca que ya lo borraste manualmente.";
    throw error;
  }
  if (!validateDigitalOceanToken(digitalOceanToken)) {
    const error = new Error("digitalocean_token_required");
    error.friendlyDetail = "Pega tu token de DigitalOcean para borrar este servidor.";
    throw error;
  }
  let dropletDeleted = false;
  let dropletWasMissing = false;
  let firewallDeleted = false;
  let firewallWarning = "";
  try {
    await requestDigitalOcean(digitalOceanToken, `/droplets/${encodeURIComponent(dropletId)}`, { method: "DELETE" });
    dropletDeleted = true;
  } catch (error) {
    if (!digitalOceanResourceMissing(error)) {
      error.friendlyDetail = digitalOceanDeleteErrorDetail(error);
      throw error;
    }
    dropletWasMissing = true;
  }
  if (firewallId && /^[A-Za-z0-9-]{6,128}$/.test(firewallId)) {
    try {
      await requestDigitalOcean(digitalOceanToken, `/firewalls/${encodeURIComponent(firewallId)}`, { method: "DELETE" });
      firewallDeleted = true;
    } catch (error) {
      if (!digitalOceanResourceMissing(error)) {
        firewallWarning = "Borre el Droplet, pero no pude limpiar el firewall asociado. No deberia generar cobro, pero puedes revisarlo en DigitalOcean.";
      }
    }
  }
  const cleared = await clearInstallation(
    record,
    dropletWasMissing ? "buyer_delete_requested_droplet_already_missing" : "buyer_deleted_droplet_from_portal"
  );
  return {
    ...cleared,
    status: "cloud_deleted",
    deleted_cloud: true,
    droplet_deleted: dropletDeleted,
    droplet_was_missing: dropletWasMissing,
    firewall_deleted: firewallDeleted,
    firewall_warning: firewallWarning,
    detail: firewallWarning || (dropletWasMissing
      ? "Ese Droplet ya no existia en DigitalOcean. Limpie el portal para que puedas crear uno nuevo."
      : "Listo. Borre el Droplet en DigitalOcean y limpie el portal para que puedas crear uno nuevo.")
  };
}

async function refreshFirewallForCurrentIp(record = {}, digitalOceanToken = "", request = null) {
  const cloud = record.cloud_installation || null;
  if (!cloud?.firewall_id || !cloud?.droplet_id) {
    const error = new Error("cloud_firewall_missing");
    error.friendlyDetail = "No encontre el firewall de este servidor cloud. Si ya borraste el Droplet, empieza una instalacion nueva.";
    throw error;
  }
  const clientIp = currentClientIp(request);
  if (!clientIp) {
    const error = new Error("client_ip_required");
    error.friendlyDetail = "No pude detectar tu IP actual para autorizar esta red.";
    throw error;
  }
  const firewall = (await doRequest(digitalOceanToken, `/firewalls/${cloud.firewall_id}`)).firewall || {};
  const dashboardPort = cleanPort(cloud.dashboard_port, "7871");
  const accessGatePort = cleanPort(cloud.access_gate_port, CLOUD_ACCESS_PORT);
  const clientCidr = `${clientIp}/32`;
  const outboundRules = firewall.outbound_rules || [
    { protocol: "tcp", ports: "0", destinations: { addresses: ["0.0.0.0/0", "::/0"] } },
    { protocol: "udp", ports: "0", destinations: { addresses: ["0.0.0.0/0", "::/0"] } },
    { protocol: "icmp", ports: "0", destinations: { addresses: ["0.0.0.0/0", "::/0"] } }
  ];
  const inboundRules = [
    { protocol: "tcp", ports: "22", sources: { addresses: ["0.0.0.0/0", "::/0"] } },
    { protocol: "tcp", ports: dashboardPort, sources: { addresses: [clientCidr] } },
    { protocol: "tcp", ports: CLOUD_HTTP_CHALLENGE_PORT, sources: { addresses: ["0.0.0.0/0", "::/0"] } },
    { protocol: "tcp", ports: CLOUD_HTTPS_PORT, sources: { addresses: [clientCidr] } },
    { protocol: "tcp", ports: accessGatePort, sources: { addresses: ["0.0.0.0/0", "::/0"] } }
  ];
  await doRequest(digitalOceanToken, `/firewalls/${cloud.firewall_id}`, {
    method: "PUT",
    body: {
      name: firewall.name || cloud.firewall_name || `admiro-ai-${cloud.droplet_id}-strict`,
      inbound_rules: inboundRules,
      outbound_rules: outboundRules,
      droplet_ids: [Number(cloud.droplet_id)].filter((id) => Number.isFinite(id)),
      tags: firewall.tags || []
    }
  });
  const updatedCloud = {
    ...cloud,
    dashboard_port: dashboardPort,
    access_gate_port: accessGatePort,
    access_refreshed_at: new Date().toISOString(),
    access_refreshed_ip: clientIp,
    install_progress: Math.max(Number(cloud.install_progress || 0), 38)
  };
  await writeCloudInstallationIfCurrent(record, updatedCloud).catch(() => false);
  return {
    cloud: updatedCloud,
    clientIp,
    dashboardPort,
    accessGatePort
  };
}

function minutesSince(value) {
  const timestamp = Date.parse(String(value || ""));
  if (!Number.isFinite(timestamp)) return 0;
  return Math.max(0, Math.floor((Date.now() - timestamp) / 60000));
}

export async function writeCloudInstallationIfCurrent(record = {}, updatedCloud = {}, recordUpdates = {}, dependencies = {}) {
  const readCurrent = dependencies.readLicense || readLicense;
  const writeCurrent = dependencies.writeLicense || writeLicense;
  const current = await readCurrent(record.license_key);
  const expectedCloud = record.cloud_installation || {};
  const currentCloud = current?.cloud_installation || {};
  const expectedDroplet = String(expectedCloud.droplet_id || "");
  const currentDroplet = String(currentCloud.droplet_id || "");
  if (!current || !expectedDroplet || currentDroplet !== expectedDroplet) return false;
  const expectedSecret = parseCloudAccessSecret(expectedCloud);
  const currentSecret = parseCloudAccessSecret(currentCloud);
  if (expectedSecret && currentSecret !== expectedSecret) return false;
  await writeCurrent({ ...current, ...recordUpdates, cloud_installation: updatedCloud });
  return true;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function validIpv4(value = "") {
  const raw = String(value || "").trim();
  const parts = raw.split(".");
  if (parts.length !== 4) return "";
  const numbers = parts.map((part) => Number(part));
  if (numbers.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) return "";
  return raw;
}

function digitalOceanTokenFromRecord(record = {}) {
  const token = decryptPortalSecret(record.portal_vault?.digitalocean_token);
  return validateDigitalOceanToken(token) ? token : "";
}

function resolveDigitalOceanToken(record = {}, suppliedToken = "") {
  const token = String(suppliedToken || "").trim();
  if (validateDigitalOceanToken(token)) {
    return { token, source: "typed" };
  }
  const saved = digitalOceanTokenFromRecord(record);
  if (saved) {
    return { token: saved, source: "saved" };
  }
  return { token: "", source: "" };
}

function withSavedDigitalOceanToken(record = {}, token = "") {
  if (!validateDigitalOceanToken(token)) return record;
  return {
    ...record,
    portal_vault: {
      ...(record.portal_vault || {}),
      digitalocean_token: encryptPortalSecret(token)
    }
  };
}

function parseCloudAccessSecret(cloud = {}) {
  if (cloud.cloud_access_secret) return String(cloud.cloud_access_secret);
  try {
    const openUrl = new URL(String(cloud.cloud_open_url || ""));
    return decodeURIComponent(openUrl.pathname.replace(/^\/open\//, ""));
  } catch {
    return "";
  }
}

function cleanPort(value = "", fallback = "7871") {
  const raw = String(value || "").trim();
  return /^\d{2,5}$/.test(raw) ? raw : fallback;
}

function cleanProgress(value, fallback = 18) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(0, Math.min(100, Math.round(number)));
}

async function waitForDropletIpv4(token, dropletId) {
  if (!dropletId) return "";
  for (let attempt = 0; attempt < 5; attempt += 1) {
    if (attempt > 0) {
      await sleep(1200);
    }
    const data = await doRequest(token, `/droplets/${dropletId}`).catch(() => null);
    const ip = dropletIpv4(data?.droplet || {});
    if (ip) return ip;
  }
  return "";
}

async function refreshCloudIpFromDigitalOcean(record, digitalOceanToken = "") {
  const cloud = record.cloud_installation || null;
  const resolved = resolveDigitalOceanToken(record, digitalOceanToken);
  if (!cloud?.droplet_id || cloud.dashboard_url || cloud.cloud_open_url || !resolved.token) {
    return null;
  }
  const ip = await waitForDropletIpv4(resolved.token, cloud.droplet_id).catch(() => "");
  if (!ip) {
    return null;
  }
  const accessSecret = parseCloudAccessSecret(cloud);
  const accessGatePort = cleanPort(cloud.access_gate_port, CLOUD_ACCESS_PORT);
  const dashboardPort = cleanPort(cloud.dashboard_port, "7871");
  const cloudHostname = String(cloud.cloud_hostname || cloud.cloud_dashboard_hostname || "").trim().toLowerCase();
  const dns = cloudHostname ? await ensureCloudDnsRecord(cloudHostname, ip).catch((error) => ({ status: "failed", detail: String(error?.message || error) })) : { status: "not_needed" };
  const urls = dashboardUrls({
    ip,
    dashboardPort,
    accessGatePort,
    accessSecret,
    hostname: cloudHostname,
    dnsActive: dns.status === "active"
  });
  const updatedCloud = {
    ...cloud,
    ...urls,
    cloud_hostname: cloudHostname,
    dns_status: dns.status,
    dns_provider: dns.provider || cloud.dns_provider || cloudDnsProvider() || "",
    dns_record_id: dns.record_id || cloud.dns_record_id || "",
    dns_error: dns.status === "failed" ? dns.detail || "No pude crear el DNS cloud." : "",
    cloud_access_secret: accessSecret || cloud.cloud_access_secret || "",
    access_gate_port: accessGatePort,
    dashboard_port: dashboardPort,
    droplet_ip: ip,
    install_status: "installing",
    install_progress: Math.max(Number(cloud.install_progress || 0), 38),
    ip_discovered_at: new Date().toISOString()
  };
  await writeCloudInstallationIfCurrent(record, updatedCloud).catch(() => false);
  return updatedCloud;
}

async function runtimeReport(body = {}, response) {
  const licenseKey = String(body.license_key || "").trim().toUpperCase();
  const buyerEmail = String(body.buyer_email || "").trim().toLowerCase();
  const suppliedSecret = String(body.cloud_access_secret || "").trim();
  const ip = validIpv4(body.droplet_ip || body.public_ip || "");
  if (!licenseKey || !suppliedSecret || !ip) {
    return friendlyFailure(response, "runtime_report_missing", "No pude confirmar el servidor cloud.");
  }
  const record = await readLicense(licenseKey);
  if (!record || record.status !== "active") {
    return friendlyFailure(response, "runtime_report_unknown", "No pude confirmar esta compra.");
  }
  if (buyerEmail && String(record.buyer_email || "").toLowerCase() !== buyerEmail) {
    return friendlyFailure(response, "runtime_report_email_mismatch", "No pude confirmar esta compra.");
  }
  const cloud = record.cloud_installation || null;
  const expectedSecret = parseCloudAccessSecret(cloud || {});
  if (!cloud?.droplet_id || !expectedSecret || expectedSecret !== suppliedSecret) {
    return friendlyFailure(response, "cloud_secret_mismatch", "No pude confirmar este servidor.");
  }
  const dashboardPort = cleanPort(body.dashboard_port, "7871");
  const accessGatePort = cleanPort(cloud.access_gate_port, CLOUD_ACCESS_PORT);
  const cloudHostname = String(body.cloud_dashboard_hostname || body.cloud_hostname || cloud.cloud_hostname || "").trim().toLowerCase();
  const dns = cloudHostname ? await ensureCloudDnsRecord(cloudHostname, ip).catch((error) => ({ status: "failed", detail: String(error?.message || error) })) : { status: "not_needed" };
  const urls = dashboardUrls({
    ip,
    dashboardPort,
    accessGatePort,
    accessSecret: expectedSecret,
    hostname: cloudHostname,
    dnsActive: dns.status === "active"
  });
  const ready = body.ready === true || String(body.ready || "").toLowerCase() === "true";
  const progress = ready ? 100 : Math.min(98, cleanProgress(body.progress, Math.max(Number(cloud.install_progress || 0), 38)));
  const installStatus = ready ? "ready" : (String(body.install_status || body.status || cloud.install_status || "installing").trim() || "installing");
  const updatedCloud = {
    ...cloud,
    ...urls,
    cloud_hostname: cloudHostname,
    dns_status: dns.status,
    dns_provider: dns.provider || cloud.dns_provider || cloudDnsProvider() || "",
    dns_record_id: dns.record_id || cloud.dns_record_id || "",
    dns_error: dns.status === "failed" ? dns.detail || "No pude crear el DNS cloud." : "",
    cloud_access_secret: expectedSecret,
    access_gate_port: accessGatePort,
    dashboard_port: dashboardPort,
    droplet_ip: ip,
    runtime_stage: String(body.stage || ""),
    runtime_reported_at: new Date().toISOString(),
    install_status: installStatus,
    install_progress: progress,
    ...(ready ? { install_completed_at: new Date().toISOString() } : {})
  };
  const saved = await writeCloudInstallationIfCurrent(record, updatedCloud).catch(() => false);
  if (!saved) {
    return friendlyFailure(response, "cloud_install_reset", "Este servidor ya fue retirado del portal.");
  }
  return json(response, 200, {
    valid: true,
    status: installStatus,
    ready,
    progress,
    stage: ready ? "dashboard_ready" : (String(body.stage || "") === "dashboard_ready" ? "verificando_dashboard" : (body.stage || "ip_reported")),
    detail: ready ? "Tu dashboard ya esta listo." : "Servidor conectado automaticamente. Sigo revisando la instalacion.",
    dashboard_url: urls.dashboard_url,
    dashboard_http_url: urls.dashboard_http_url,
    dashboard_https_url: urls.dashboard_https_url,
    cloud_open_url: urls.cloud_open_url,
    cloud_hostname: cloudHostname,
    dns_status: dns.status,
    dns_provider: dns.provider || cloudDnsProvider() || "",
    droplet_ip: ip,
    ssh_command: `ssh root@${ip}`
  });
}

function statusUrlFor(cloud = {}) {
  try {
    const openUrl = new URL(String(cloud.cloud_open_url || ""));
    openUrl.pathname = openUrl.pathname.replace(/^\/open\//, "/status/");
    return openUrl.toString();
  } catch {
    return "";
  }
}

function estimatedCloudStatus(cloud = {}) {
  const elapsed = minutesSince(cloud.created_at || cloud.install_started_at);
  const missingIp = Boolean(cloud.droplet_id && !cloud.dashboard_url && !cloud.cloud_open_url);
  const savedReady = cloud.install_status === "ready";
  const takingLonger = cloud.install_status !== "ready" && elapsed >= 15;
  const progress = Math.max(
    Number(cloud.install_progress || 0),
    missingIp ? 28 : takingLonger ? 89 : elapsed >= 12 ? 86 : elapsed >= 8 ? 76 : elapsed >= 5 ? 58 : elapsed >= 2 ? 38 : 18
  );
  if (missingIp) {
    return {
      valid: true,
      status: "waiting_for_ip",
      ready: false,
      taking_longer: elapsed >= 10,
      progress: Math.min(36, progress),
      stage: "esperando_ip",
      detail: cloud.cloud_access_secret
        ? "DigitalOcean creo el servidor, pero no devolvio la IP publica a tiempo. Copia el IPv4 del Droplet en DigitalOcean y pegalo aqui para seguir."
        : "DigitalOcean creo el servidor, pero esta instalacion no guardo el enlace seguro. Pega el IPv4 para revisar acceso directo o recrea el servidor con la version actualizada.",
      dashboard_url: "",
      dashboard_http_url: "",
      dashboard_https_url: "",
      cloud_open_url: "",
      cloud_hostname: cloud.cloud_hostname || "",
      dns_status: cloud.dns_status || "",
      dns_provider: cloud.dns_provider || "",
      droplet_id: cloud.droplet_id || "",
      droplet_name: cloud.droplet_name || "",
      can_attach_ip: Boolean(cloud.cloud_access_secret),
      ssh_command: "",
      created_at: cloud.created_at || ""
    };
  }
  if (savedReady) {
    return {
      valid: true,
      status: "ready",
      ready: true,
      taking_longer: false,
      progress: 100,
      stage: "dashboard_ready",
      detail: "Tu dashboard ya esta listo.",
      dashboard_url: cloud.dashboard_url || "",
      dashboard_http_url: cloud.dashboard_http_url || "",
      dashboard_https_url: cloud.dashboard_https_url || "",
      cloud_open_url: cloud.cloud_open_url || "",
      cloud_hostname: cloud.cloud_hostname || "",
      dns_status: cloud.dns_status || "",
      dns_provider: cloud.dns_provider || "",
      droplet_id: cloud.droplet_id || "",
      droplet_name: cloud.droplet_name || "",
      can_attach_ip: Boolean(cloud.cloud_access_secret),
      direct_open_only: Boolean(cloud.dashboard_url && !cloud.cloud_open_url),
      droplet_ip: cloud.droplet_ip || String(cloud.dashboard_http_url || cloud.dashboard_url || "").replace(/^https?:\/\//, "").split(":")[0],
      ssh_command: (cloud.droplet_ip || cloud.dashboard_http_url || cloud.dashboard_url) ? `ssh root@${cloud.droplet_ip || String(cloud.dashboard_http_url || cloud.dashboard_url || "").replace(/^https?:\/\//, "").split(":")[0]}` : "",
      created_at: cloud.created_at || ""
    };
  }
  return {
    valid: true,
    status: takingLonger ? "taking_longer" : (cloud.install_status || "installing"),
    ready: cloud.install_status === "ready",
    taking_longer: takingLonger,
    progress: Math.min(takingLonger ? 89 : 95, progress),
    stage: takingLonger ? "tardando_mas_de_lo_normal" : (cloud.install_status || (elapsed >= 8 ? "finalizando" : elapsed >= 2 ? "instalando" : "creando_servidor")),
    detail: takingLonger
      ? "El Droplet puede aparecer activo en DigitalOcean aunque el producto siga instalándose. Esto esta tardando mas de lo normal; revisa la consola del Droplet o intenta abrir el dashboard en unos minutos."
      : (elapsed >= 8 ? "Estamos haciendo las ultimas verificaciones." : "DigitalOcean esta instalando el dashboard."),
    dashboard_url: cloud.dashboard_url || "",
    dashboard_http_url: cloud.dashboard_http_url || "",
    dashboard_https_url: cloud.dashboard_https_url || "",
    cloud_open_url: cloud.cloud_open_url || "",
    cloud_hostname: cloud.cloud_hostname || "",
    dns_status: cloud.dns_status || "",
    dns_provider: cloud.dns_provider || "",
    droplet_id: cloud.droplet_id || "",
    droplet_name: cloud.droplet_name || "",
    can_attach_ip: Boolean(cloud.cloud_access_secret),
    direct_open_only: Boolean(cloud.dashboard_url && !cloud.cloud_open_url),
    droplet_ip: cloud.droplet_ip || String(cloud.dashboard_http_url || cloud.dashboard_url || "").replace(/^https?:\/\//, "").split(":")[0],
    ssh_command: (cloud.droplet_ip || cloud.dashboard_http_url || cloud.dashboard_url) ? `ssh root@${cloud.droplet_ip || String(cloud.dashboard_http_url || cloud.dashboard_url || "").replace(/^https?:\/\//, "").split(":")[0]}` : "",
    created_at: cloud.created_at || ""
  };
}

async function fetchRuntimeStatus(cloud = {}) {
  const statusUrl = statusUrlFor(cloud);
  if (!statusUrl) return null;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 4500);
  try {
    const upstream = await fetch(statusUrl, {
      method: "GET",
      headers: { "Accept": "application/json", "User-Agent": "admiro-ai-cloud-status" },
      signal: controller.signal
    });
    const data = await upstream.json().catch(() => ({}));
    if (!upstream.ok || !data?.ok) return null;
    return data;
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

function runtimeInstallFailed(runtime = {}) {
  const logTail = String(runtime.log_tail || "");
  const dockerLogsTail = String(runtime.docker_logs_tail || "");
  const dockerPsTail = Array.isArray(runtime.docker_ps) ? runtime.docker_ps.join("\n") : "";
  const combinedLogs = `${logTail}\n${dockerLogsTail}`;
  return (
    dockerPsTail.includes("Restarting") ||
    /\nE:\s/.test(combinedLogs) ||
    combinedLogs.includes("Unable to locate package") ||
    combinedLogs.includes("Release too large") ||
    combinedLogs.includes("Unsafe release archive") ||
    combinedLogs.includes("Could not resolve host") ||
    combinedLogs.includes("curl: (6)") ||
    combinedLogs.includes("command not found") ||
    combinedLogs.includes("Traceback (most recent call last)") ||
    combinedLogs.includes("ModuleNotFoundError") ||
    combinedLogs.includes("ImportError")
  );
}

function runtimeFailureCopy(runtime = {}) {
  const combinedLogs = `${String(runtime.log_tail || "")}\n${String(runtime.docker_logs_tail || "")}`;
  if (combinedLogs.includes("Could not resolve host") || combinedLogs.includes("curl: (6)")) {
    return {
      detail: "La instalacion se detuvo al descargar el producto por un problema temporal de DNS. Ya corregimos el instalador; borra este Droplet y crea uno nuevo desde aqui.",
      error_summary: "No pudo descargar el producto por DNS de arranque."
    };
  }
  return {
    detail: "La instalacion se detuvo al arrancar el dashboard. Ya tengo logs de diagnostico para corregirlo; borra este Droplet y crea uno nuevo cuando publiquemos el arreglo.",
    error_summary: "El contenedor del dashboard no pudo quedar encendido."
  };
}

function runtimeStageFromLog(logTail = "") {
  const markers = [
    ["ADMIRO_STAGE verifying_dashboard", "verificando_dashboard", 98],
    ["Admira IA cloud install complete", "verificando_dashboard", 98],
    ["ADMIRO_STAGE starting_dashboard", "iniciando_dashboard", 92],
    ["ADMIRO_STAGE app_installed", "preparando_dashboard", 86],
    ["ADMIRO_STAGE running_installer", "instalando_dependencias", 72],
    ["ADMIRO_STAGE unpacked_release", "preparando_archivos", 56],
    ["ADMIRO_STAGE downloading_release", "descargando_producto", 44],
    ["ADMIRO_STAGE packages_ready", "paquetes_listos", 34],
    ["ADMIRO_STAGE package_install", "instalando_paquetes", 24],
    ["ADMIRO_STAGE bootstrap", "arrancando_servidor", 12]
  ];
  return markers.find(([marker]) => String(logTail || "").includes(marker)) || null;
}

async function cloudInstallStatus(record, response, options = {}) {
  const cloud = record.cloud_installation || null;
  if (!cloud) {
    const payload = {
      valid: true,
      status: "not_started",
      ready: false,
      progress: 0,
      stage: "sin_instalacion",
      detail: "Todavia no has creado un servidor cloud."
    };
    return options.returnPayload ? payload : json(response, 200, payload);
  }
  const estimated = estimatedCloudStatus(cloud);
  if (estimated.ready) {
    return options.returnPayload ? estimated : json(response, 200, estimated);
  }
  const runtime = await fetchRuntimeStatus(cloud);
  if (!runtime) {
    return options.returnPayload ? estimated : json(response, 200, estimated);
  }
  const ready = Boolean(runtime.ready);
  const failed = !ready && runtimeInstallFailed(runtime);
  const failureCopy = failed ? runtimeFailureCopy(runtime) : null;
  const logStage = runtimeStageFromLog(runtime.log_tail || "");
  const logProgress = logStage ? Number(logStage[2] || 0) : 0;
  const progress = ready ? 100 : Math.min(98, cleanProgress(Math.max(Number(runtime.progress || 0), logProgress), cleanProgress(estimated.progress, 0)));
  const status = ready ? "ready" : (failed ? "failed" : "installing");
  const runtimeStage = logStage ? String(logStage[1] || "") : String(runtime.stage || "");
  const runtimeTakingLonger = estimated.taking_longer && !ready && !failed && progress < 100;
  const payload = {
    ...estimated,
    status: runtimeTakingLonger ? "taking_longer" : status,
    ready,
    progress,
    taking_longer: runtimeTakingLonger,
    failed,
    stage: failed ? "instalacion_detenida" : (runtimeTakingLonger ? "tardando_mas_de_lo_normal" : (runtimeStage === "dashboard_ready" && !ready ? "verificando_dashboard" : (runtimeStage || (ready ? "dashboard_ready" : "instalando")))),
    detail: ready
      ? "Tu dashboard ya esta listo."
      : (failed ? failureCopy.detail : (runtimeTakingLonger ? estimated.detail : "El servidor ya responde y esta terminando la instalacion.")),
    error_summary: failed ? failureCopy.error_summary : "",
    docker_ps: Array.isArray(runtime.docker_ps) ? runtime.docker_ps.slice(-8) : [],
    docker_logs_tail: String(runtime.docker_logs_tail || "").slice(-5000),
    checked_at: runtime.checked_at || new Date().toISOString()
  };
  if (ready && cloud.install_status !== "ready") {
    await writeCloudInstallationIfCurrent(record, {
      ...cloud,
      install_status: "ready",
      install_progress: 100,
      install_completed_at: new Date().toISOString()
    }).catch(() => false);
  }
  return options.returnPayload ? payload : json(response, 200, payload);
}

export default async function handler(request, response) {
  if (request.method !== "POST") {
    return json(response, 405, { valid: false, status: "method_not_allowed", detail: "Metodo no permitido." });
  }
  try {
    const {
      portal_token: token = "",
      action: rawAction = "create",
      digitalocean_token: rawDigitalOceanToken = "",
      ssh_public_key: rawSshPublicKey = "",
      region: rawRegion = "",
      size: rawSize = ""
    } = request.body || {};
    const action = String(rawAction || "create").trim().toLowerCase();
    if (action === "runtime_report") {
      return runtimeReport(request.body || {}, response);
    }
    const session = verifyPortalSession(token);
    if (!session) {
      return friendlyFailure(response, "session_expired", "Tu acceso vencio. Vuelve a ingresar tu email y clave.");
    }
    const record = await readLicense(session.license_key);
    if (!record || record.status !== "active" || String(record.buyer_email || "").toLowerCase() !== session.buyer_email) {
      return friendlyFailure(response, "access_revoked", "No pude confirmar esta compra. Contacta soporte.");
    }
    if (action === "status") {
      const resolvedDigitalOceanToken = resolveDigitalOceanToken(record, rawDigitalOceanToken);
      const clearedMissingDroplet = await clearIfDigitalOceanDropletMissing(record, resolvedDigitalOceanToken.token);
      if (clearedMissingDroplet) {
        return json(response, 200, {
          ...clearedMissingDroplet,
          cleared_deleted_cloud: true,
          detail: "No encontre ese Droplet en DigitalOcean. Limpie el portal para que puedas crear uno nuevo."
        });
      }
      const recoveredCloud = await refreshCloudIpFromDigitalOcean(record, String(rawDigitalOceanToken || "").trim());
      if (recoveredCloud) {
        return cloudInstallStatus({ ...record, cloud_installation: recoveredCloud }, response);
      }
      return cloudInstallStatus(record, response);
    }
    if (action === "reset_cloud_install") {
      const cleared = await clearCloudInstallation(record, "buyer_confirmed_deleted_droplet");
      return json(response, 200, { ...cleared, status: "cloud_reset" });
    }
    if (action === "delete_cloud_install") {
      const resolvedDigitalOceanToken = resolveDigitalOceanToken(record, rawDigitalOceanToken);
      try {
        const deleted = await deleteDigitalOceanCloudInstall(record, resolvedDigitalOceanToken.token);
        return json(response, 200, deleted);
      } catch (error) {
        const status = error.message === "digitalocean_token_required" ? "digitalocean_token_required" : "delete_cloud_failed";
        return friendlyFailure(response, status, error.friendlyDetail || digitalOceanDeleteErrorDetail(error));
      }
    }
    if (action === "refresh_access") {
      const resolvedDigitalOceanToken = resolveDigitalOceanToken(record, rawDigitalOceanToken);
      if (!validateDigitalOceanToken(resolvedDigitalOceanToken.token)) {
        return friendlyFailure(response, "digitalocean_token_required", "Pega tu token de DigitalOcean para actualizar el acceso de esta red.");
      }
      try {
        const refreshed = await refreshFirewallForCurrentIp(record, resolvedDigitalOceanToken.token, request);
        const statusPayload = await cloudInstallStatus({ ...record, cloud_installation: refreshed.cloud }, response, { returnPayload: true });
        if (validateDigitalOceanToken(rawDigitalOceanToken)) {
          const tokenRecord = withSavedDigitalOceanToken(record, rawDigitalOceanToken);
          await writeCloudInstallationIfCurrent(record, refreshed.cloud, { portal_vault: tokenRecord.portal_vault }).catch(() => false);
        }
        return json(response, 200, {
          ...statusPayload,
          valid: true,
          access_refreshed: true,
          allowed_ip: `${refreshed.clientIp}/32`,
          detail: "Listo. Autorice esta red para SSH y dashboard. Sigo revisando si el dashboard ya responde."
        });
      } catch (error) {
        return friendlyFailure(response, "refresh_access_failed", error.friendlyDetail || digitalOceanErrorDetail(error));
      }
    }
    if (action === "attach_ip") {
      const cloud = record.cloud_installation || null;
      const ip = validIpv4(request.body?.droplet_ip || "");
      if (!cloud?.droplet_id) {
        return friendlyFailure(response, "cloud_install_missing", "No encontre un servidor cloud para esta compra.");
      }
      if (!ip) {
        return friendlyFailure(response, "droplet_ip_required", "Pega el IPv4 publico del Droplet. Se ve como 123.45.67.89.");
      }
      const accessSecret = parseCloudAccessSecret(cloud);
      const cloudHostname = String(cloud.cloud_hostname || "").trim().toLowerCase();
      const dns = cloudHostname ? await ensureCloudDnsRecord(cloudHostname, ip).catch((error) => ({ status: "failed", detail: String(error?.message || error) })) : { status: "not_needed" };
      const urls = dashboardUrls({
        ip,
        dashboardPort: "7871",
        accessGatePort: CLOUD_ACCESS_PORT,
        accessSecret,
        hostname: cloudHostname,
        dnsActive: dns.status === "active"
      });
      if (!accessSecret) {
        await writeCloudInstallationIfCurrent(record, {
          ...cloud,
          ...urls,
          cloud_hostname: cloudHostname,
          dns_status: dns.status,
          dns_provider: dns.provider || cloud.dns_provider || cloudDnsProvider() || "",
          dns_record_id: dns.record_id || cloud.dns_record_id || "",
          dns_error: dns.status === "failed" ? dns.detail || "No pude crear el DNS cloud." : "",
          droplet_ip: ip,
          install_status: "installing",
          install_progress: Math.max(Number(cloud.install_progress || 0), 38),
          attached_ip_at: new Date().toISOString()
        }).catch(() => false);
        return json(response, 200, {
          valid: true,
          status: "installing",
          ready: false,
          progress: 38,
          stage: "ip_guardada_sin_gate",
          detail: "Guarde el IP como enlace directo. Esta instalacion se creo antes de guardar el boton seguro; si no abre, recrea el servidor con la version actualizada.",
          dashboard_url: urls.dashboard_url,
          dashboard_http_url: urls.dashboard_http_url,
          dashboard_https_url: urls.dashboard_https_url,
          cloud_open_url: "",
          cloud_hostname: cloudHostname,
          dns_status: dns.status,
          dns_provider: dns.provider || cloudDnsProvider() || "",
          direct_open_only: true,
          droplet_ip: ip,
          droplet_id: cloud.droplet_id,
          droplet_name: cloud.droplet_name || "",
          ssh_command: `ssh root@${ip}`
        });
      }
      const updatedCloud = {
        ...cloud,
        ...urls,
        cloud_hostname: cloudHostname,
        dns_status: dns.status,
        dns_provider: dns.provider || cloud.dns_provider || cloudDnsProvider() || "",
        dns_record_id: dns.record_id || cloud.dns_record_id || "",
        dns_error: dns.status === "failed" ? dns.detail || "No pude crear el DNS cloud." : "",
        cloud_access_secret: accessSecret,
        access_gate_port: CLOUD_ACCESS_PORT,
        droplet_ip: ip,
        install_status: "installing",
        install_progress: Math.max(Number(cloud.install_progress || 0), 38),
        attached_ip_at: new Date().toISOString()
      };
      const tokenRecord = withSavedDigitalOceanToken(record, rawDigitalOceanToken);
      const tokenUpdates = tokenRecord.portal_vault ? { portal_vault: tokenRecord.portal_vault } : {};
      await writeCloudInstallationIfCurrent(record, updatedCloud, tokenUpdates).catch(() => false);
      return json(response, 200, {
        ...estimatedCloudStatus(updatedCloud),
        valid: true,
        status: "installing",
        detail: "IP guardado. Ahora puedo revisar si el dashboard termina de instalar.",
        dashboard_url: urls.dashboard_url,
        dashboard_http_url: urls.dashboard_http_url,
        dashboard_https_url: urls.dashboard_https_url,
        cloud_open_url: urls.cloud_open_url,
        cloud_hostname: cloudHostname,
        dns_status: dns.status,
        dns_provider: dns.provider || cloudDnsProvider() || "",
        droplet_ip: ip,
        ssh_command: `ssh root@${ip}`
      });
    }
    const resolvedDigitalOceanToken = resolveDigitalOceanToken(record, rawDigitalOceanToken);
    const digitalOceanToken = resolvedDigitalOceanToken.token;
    const sshPublicKey = String(rawSshPublicKey || "").trim();
    if (!validateDigitalOceanToken(digitalOceanToken)) {
      return friendlyFailure(response, "digitalocean_token_required", "Pega un token valido de DigitalOcean.");
    }
    if (!validateSshPublicKey(sshPublicKey)) {
      return friendlyFailure(response, "ssh_key_required", "Pega tu llave publica SSH. Debe empezar por ssh-ed25519 o ssh-rsa.");
    }
    const clientIp = currentClientIp(request);
    if (!clientIp) {
      return friendlyFailure(response, "client_ip_required", "No pude detectar tu IP actual para cerrar el firewall.");
    }

    const cloudOptions = publicCloudOptions();
    const region = normalizeChoice(rawRegion, cloudOptions.regions, cloudOptions.default_region);
    const size = normalizeChoice(rawSize, cloudOptions.sizes, cloudOptions.default_size);
    const releases = await readReleases();
    const release = await releaseWithDiscoveredAssets(releases.channels?.[session.channel || "stable"]);
    const source = sourceZipAsset(release);
    if (!release || !source) {
      return friendlyFailure(response, "release_missing", "Todavia no hay paquete fuente publicado para instalar en la nube.");
    }
    const [assetName, asset] = source;
    const id = installId();
    const deviceId = `do-${id}`;
    const tag = `admiro-ai-${id}`;
    const dropletName = `admiro-ai-${id}`;
    const firewallName = `admiro-ai-${id}-strict`;
    const keyName = `Admira IA ${id}`;
    const accessSecret = cloudAccessSecret();
    const cloudHostname = cloudHostnameForInstall(id);
    const grant = signedReleaseGrant({
      licenseKey: session.license_key,
      buyerEmail: session.buyer_email,
      deviceId,
      channel: session.channel || "stable",
      assetName,
      version: release.version,
      filename: asset.filename,
      contentType: asset.content_type,
      blobPath: asset.blob_path,
      sourceUrl: asset.source_url,
      minutes: 180
    });

    await createTag(digitalOceanToken, tag);
    const sshKey = await ensureSshKey(digitalOceanToken, keyName, sshPublicKey);
    const firewall = await doRequest(digitalOceanToken, "/firewalls", {
      method: "POST",
      body: digitalOceanFirewallPayload({
        name: firewallName,
        tag,
        clientIp,
        allowSshFromAnywhere: true,
        accessGatePort: CLOUD_ACCESS_PORT
      })
    });
    const firewallId = firewall.firewall?.id;
    if (!firewallId) {
      return friendlyFailure(response, "firewall_failed", "DigitalOcean no devolvio el firewall creado.");
    }

    try {
      const bootstrapBase = cloudBootstrapBaseUrl(request);
      const cloudInit = buildDigitalOceanCloudInit({
        signedDownloadUrl: `${bootstrapBase}/api/download/release?token=${encodeURIComponent(grant.token)}`,
        licenseKey: session.license_key,
        buyerEmail: session.buyer_email,
        deviceId,
        licenseServerUrl: bootstrapBase,
        digitalOceanToken,
        firewallId,
        initialClientIp: clientIp,
        dashboardPort: "7871",
        cloudAccessSecret: accessSecret,
        cloudAccessPort: CLOUD_ACCESS_PORT,
        cloudDashboardHostname: cloudHostname
      });
      const dropletResponse = await doRequest(digitalOceanToken, "/droplets", {
        method: "POST",
        body: {
          name: dropletName,
          region,
          size,
          image: "ubuntu-24-04-x64",
          ssh_keys: [sshKey?.id || sshKey?.fingerprint].filter(Boolean),
          backups: false,
          ipv6: false,
          monitoring: true,
          tags: [tag],
          user_data: cloudInit
        }
      });
      const droplet = dropletResponse.droplet || {};
      const ipv4 = dropletIpv4(droplet) || await waitForDropletIpv4(digitalOceanToken, droplet.id);
      const dns = ipv4 && cloudHostname ? await ensureCloudDnsRecord(cloudHostname, ipv4).catch((error) => ({ status: "failed", detail: String(error?.message || error) })) : { status: cloudHostname ? "pending_ip" : "not_configured" };
      const urls = dashboardUrls({
        ip: ipv4,
        dashboardPort: "7871",
        accessGatePort: CLOUD_ACCESS_PORT,
        accessSecret,
        hostname: cloudHostname,
        dnsActive: dns.status === "active"
      });
      await writeLicense({
        ...withSavedDigitalOceanToken(record, digitalOceanToken),
        cloud_installation: {
          provider: "digitalocean",
          droplet_id: droplet.id,
          droplet_name: droplet.name || dropletName,
          firewall_id: firewallId,
          region,
          size,
          ...urls,
          cloud_hostname: cloudHostname,
          dns_status: dns.status,
          dns_provider: dns.provider || cloudDnsProvider() || "",
          dns_record_id: dns.record_id || "",
          dns_error: dns.status === "failed" ? dns.detail || "No pude crear el DNS cloud." : "",
          cloud_access_secret: accessSecret,
          access_gate_port: CLOUD_ACCESS_PORT,
          dashboard_port: "7871",
          droplet_ip: ipv4 || "",
          install_status: ipv4 ? "installing" : "waiting_for_ip",
          install_progress: ipv4 ? 18 : 28,
          install_started_at: new Date().toISOString(),
          created_at: new Date().toISOString()
        }
      }).catch(() => {});
      return json(response, 200, {
        valid: true,
        status: "creating",
        detail: "Servidor creado. La instalacion tarda unos minutos.",
        version: release.version,
        droplet_id: droplet.id,
        droplet_name: droplet.name || dropletName,
        firewall_id: firewallId,
        region,
        size,
        allowed_ip: `${clientIp}/32`,
        droplet_ip: ipv4,
        dashboard_url: urls.dashboard_url,
        dashboard_http_url: urls.dashboard_http_url,
        dashboard_https_url: urls.dashboard_https_url,
        cloud_open_url: urls.cloud_open_url,
        cloud_hostname: cloudHostname,
        dns_status: dns.status,
        dns_provider: dns.provider || cloudDnsProvider() || "",
        ready: false,
        progress: ipv4 ? 18 : 28,
        install_status: ipv4 ? "installing" : "waiting_for_ip",
        stage: ipv4 ? "creando_servidor" : "esperando_ip",
        ssh_command: ipv4 ? `ssh root@${ipv4}` : "",
        can_attach_ip: true,
        next_step: ipv4 ? "Espera 5 a 10 minutos y abre el dashboard cuando el servidor termine de instalar." : "DigitalOcean creo el servidor, pero aun no devolvio la IP. Si aparece en DigitalOcean, pegala aqui para continuar."
      });
    } catch (error) {
      await doRequest(digitalOceanToken, `/firewalls/${firewallId}`, { method: "DELETE" }).catch(() => {});
      throw error;
    }
  } catch (error) {
    return friendlyFailure(response, "digitalocean_error", digitalOceanErrorDetail(error));
  }
}
