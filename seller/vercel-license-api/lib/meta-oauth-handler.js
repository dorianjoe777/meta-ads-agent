import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { decryptPortalSecret, encryptPortalSecret } from "./secret-vault.js";
import {
  deleteMetaOAuthRequest,
  handoffDigest,
  readMetaOAuthRequest,
  writeMetaOAuthRequest,
} from "./meta-oauth-store.js";

const GRAPH_VERSION = String(process.env.META_GRAPH_API_VERSION || "v26.0").replace(/^v?/i, "v");
const MAX_AGE_MS = 15 * 60 * 1000;

// The browser must never receive Graph payloads, OAuth codes, or tokens.  A
// short phase code is enough to make an OAuth failure diagnosable from Vercel
// logs and lets the local installation discard a spent handoff safely.
function oauthFailureCode(error) {
  const value = String(error?.message || "oauth_callback_failed").toLowerCase();
  if (value.includes("expired")) return "request_expired";
  if (value.includes("token_exchange")) return "token_exchange";
  if (value.includes("vault")) return "credential_vault";
  if (value.includes("asset_discovery")) return "asset_discovery";
  return "callback_failed";
}

function noStore(response) {
  response.setHeader("Cache-Control", "no-store, private");
  response.setHeader("X-Content-Type-Options", "nosniff");
  response.setHeader("Referrer-Policy", "no-referrer");
}

function json(response, status, payload) {
  noStore(response);
  return response.status(status).json(payload);
}

function html(response, status, body) {
  noStore(response);
  response.setHeader("Content-Type", "text/html; charset=utf-8");
  response.setHeader("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'");
  return response.status(status).send(`<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Admira IA</title><style>body{font-family:system-ui,sans-serif;background:#111827;color:#f8fafc;margin:0;padding:10vh 8%;line-height:1.5}main{max-width:42rem;margin:auto;background:#1f2937;border-radius:18px;padding:28px}h1{margin-top:0}</style><main>${body}</main>`);
}

function configured() {
  return Boolean(
    process.env.META_OAUTH_APP_ID
      && process.env.META_OAUTH_APP_SECRET
      && process.env.META_OAUTH_REDIRECT_URI
      // encryptPortalSecret supports the release secret as a compatibility
      // key. Reuse it for existing production installs rather than making
      // OAuth unavailable until a second vault key is provisioned.
      && (process.env.PORTAL_SECRET_VAULT_KEY || process.env.RELEASE_DOWNLOAD_SECRET),
  );
}

function validSecret(value = "") {
  return /^[A-Za-z0-9_-]{32,200}$/.test(String(value || ""));
}

function sameDigest(left, right) {
  if (!left || !right || left.length !== right.length) return false;
  return timingSafeEqual(Buffer.from(left), Buffer.from(right));
}

function callbackUrl() {
  const value = new URL(process.env.META_OAUTH_REDIRECT_URI);
  value.searchParams.set("flow", "callback");
  return value.toString();
}

function authorizeUrl(requestId) {
  const value = new URL("https://www.facebook.com/v26.0/dialog/oauth");
  value.searchParams.set("client_id", process.env.META_OAUTH_APP_ID);
  value.searchParams.set("redirect_uri", callbackUrl());
  value.searchParams.set("state", requestId);
  value.searchParams.set("response_type", "code");
  value.searchParams.set("auth_type", "rerequest");
  // User access tokens inherit the user's current Page and business access.
  // A Facebook Login for Business configuration can still define the user
  // token's requested permissions. Its asset picker stays disabled for this
  // token type, by design; Admira discovers/selects business assets after the
  // redirect instead of requiring a System User configuration.
  // Each buyer must be an app role while the app is in development, or the
  // app must be reviewed.
  // business_management lets the user-token flow discover assets in business
  // portfolios where the buyer is an administrator.  This is deliberately a
  // user OAuth permission, not a System User configuration: buyers still
  // authenticate with their own Facebook account and explicitly choose the
  // workspace inside Admira after the redirect.
  const configId = String(process.env.META_OAUTH_CONFIG_ID || "").trim();
  if (/^\d{8,32}$/.test(configId)) value.searchParams.set("config_id", configId);
  value.searchParams.set("scope", ["ads_management", "ads_read", "business_management", "pages_show_list", "pages_manage_ads", "pages_manage_posts", "pages_read_engagement"].join(","));
  return value.toString();
}

async function metaJson(url, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload?.error) {
      const error = new Error("meta_oauth_exchange_failed");
      error.meta = payload?.error?.message || "Meta rejected the connection.";
      throw error;
    }
    return payload;
  } finally {
    clearTimeout(timer);
  }
}

async function optionalMetaJson(url, options = {}) {
  try {
    return await metaJson(url, options);
  } catch {
    // Business portfolio visibility differs by role. A portfolio lookup that
    // Meta declines must not invalidate an otherwise usable OAuth connection.
    return { data: [] };
  }
}

function safePage(row) {
  if (!row?.id) return null;
  return {
    id: String(row.id),
    name: String(row.name || "Página sin nombre").slice(0, 180),
    category: String(row.category || "").slice(0, 180),
    access_token: row.access_token ? String(row.access_token) : "",
    can_publish: Boolean(row.access_token),
    sources: Array.isArray(row.sources) ? row.sources.map(String) : [],
    business_ids: Array.isArray(row.business_ids) ? row.business_ids.map(String) : [],
    instagram: row.instagram_business_account?.id ? { id: String(row.instagram_business_account.id), username: String(row.instagram_business_account.username || "") } : null,
  };
}

function safeAccount(row) {
  if (!row?.id) return null;
  return { id: String(row.id), account_id: String(row.account_id || ""), name: String(row.name || "Cuenta sin nombre").slice(0, 180), currency: String(row.currency || ""), account_status: Number(row.account_status || 0), sources: Array.isArray(row.sources) ? row.sources.map(String) : [], business_ids: Array.isArray(row.business_ids) ? row.business_ids.map(String) : [] };
}

function rows(value) {
  return Array.isArray(value?.data) ? value.data : [];
}

function mergeAssets(items, normalizer) {
  const merged = new Map();
  for (const raw of items) {
    const item = normalizer(raw);
    if (!item) continue;
    const existing = merged.get(item.id);
    // Keep a Page access token if any valid route returned one. Meta's
    // business asset edges often omit it even when the user can obtain it by
    // direct Page lookup.
    merged.set(item.id, {
      ...existing,
      ...item,
      access_token: item.access_token || existing?.access_token || "",
      can_publish: Boolean(item.access_token || existing?.access_token),
      sources: [...new Set([...(existing?.sources || []), ...(item.sources || [])])],
      business_ids: [...new Set([...(existing?.business_ids || []), ...(item.business_ids || [])])],
    });
  }
  return [...merged.values()];
}

function collectBusinessAssets(businessRows) {
  const accounts = [];
  const pages = [];
  const businesses = [];
  for (const business of businessRows) {
    if (!business?.id) continue;
    const id = String(business.id);
    const name = String(business.name || "Negocio sin nombre").slice(0, 180);
    businesses.push({ id, name });
    for (const field of ["owned_ad_accounts", "client_ad_accounts"]) {
      for (const account of rows(business[field])) accounts.push({ ...account, sources: [field], business_ids: [id] });
    }
    for (const field of ["owned_pages", "client_pages"]) {
      for (const page of rows(business[field])) pages.push({ ...page, sources: [field], business_ids: [id] });
    }
  }
  return { businesses, accounts: mergeAssets(accounts, safeAccount), pages: mergeAssets(pages, safePage) };
}

async function enrichBusinessPages(pageItems, userToken, graphBase) {
  const enriched = [];
  // A bounded fan-out is intentionally used here: this is a one-time OAuth
  // discovery flow, but a buyer may administer dozens of Pages. It should not
  // produce a burst that looks like an abusive Graph API client.
  for (let index = 0; index < pageItems.length; index += 6) {
    const batch = pageItems.slice(index, index + 6);
    const found = await Promise.all(batch.map(async (page) => {
      const details = await optionalMetaJson(`${graphBase}/${encodeURIComponent(page.id)}?fields=id,name,category,access_token,instagram_business_account{id,username}&access_token=${encodeURIComponent(userToken)}`);
      return { ...page, ...(details || {}) };
    }));
    enriched.push(...found);
  }
  return enriched;
}

async function finalizeCallback(requestId, code) {
  const pending = await readMetaOAuthRequest(requestId);
  if (!pending || pending.status !== "pending" || Date.now() - Date.parse(pending.created_at || "") > MAX_AGE_MS) {
    if (pending) await deleteMetaOAuthRequest(requestId).catch(() => {});
    throw new Error("oauth_request_expired");
  }
  const tokenUrl = new URL(`https://graph.facebook.com/${GRAPH_VERSION}/oauth/access_token`);
  tokenUrl.searchParams.set("client_id", process.env.META_OAUTH_APP_ID);
  tokenUrl.searchParams.set("client_secret", process.env.META_OAUTH_APP_SECRET);
  tokenUrl.searchParams.set("redirect_uri", callbackUrl());
  tokenUrl.searchParams.set("code", code);
  const shortToken = await metaJson(tokenUrl).catch((error) => {
    const failure = new Error("meta_oauth_token_exchange_failed");
    failure.cause = error;
    throw failure;
  });
  const exchangeUrl = new URL(`https://graph.facebook.com/${GRAPH_VERSION}/oauth/access_token`);
  exchangeUrl.searchParams.set("grant_type", "fb_exchange_token");
  exchangeUrl.searchParams.set("client_id", process.env.META_OAUTH_APP_ID);
  exchangeUrl.searchParams.set("client_secret", process.env.META_OAUTH_APP_SECRET);
  exchangeUrl.searchParams.set("fb_exchange_token", shortToken.access_token);
  const longToken = await metaJson(exchangeUrl).catch(() => shortToken);
  const userToken = String(longToken.access_token || shortToken.access_token || "");
  if (!userToken) throw new Error("meta_oauth_exchange_failed");
  const graphBase = `https://graph.facebook.com/${GRAPH_VERSION}`;
  const [profile, accounts, pages, permissions, businessesResult] = await Promise.all([
    metaJson(`${graphBase}/me?fields=id,name&access_token=${encodeURIComponent(userToken)}`),
    metaJson(`${graphBase}/me/adaccounts?fields=id,account_id,name,currency,account_status&limit=100&access_token=${encodeURIComponent(userToken)}`),
    metaJson(`${graphBase}/me/accounts?fields=id,name,category,access_token,instagram_business_account{id,username}&limit=100&access_token=${encodeURIComponent(userToken)}`),
    metaJson(`${graphBase}/me/permissions?access_token=${encodeURIComponent(userToken)}`),
    optionalMetaJson(`${graphBase}/me/businesses?fields=id,name,owned_ad_accounts.limit(100){id,account_id,name,currency,account_status},client_ad_accounts.limit(100){id,account_id,name,currency,account_status},owned_pages.limit(100){id,name,category,instagram_business_account{id,username}},client_pages.limit(100){id,name,category,instagram_business_account{id,username}}&limit=100&access_token=${encodeURIComponent(userToken)}`),
  ]).catch((error) => {
    const failure = new Error("meta_oauth_asset_discovery_failed");
    failure.cause = error;
    throw failure;
  });
  const businessAssets = collectBusinessAssets(rows(businessesResult));
  const initialPages = mergeAssets([
    ...rows(pages).map((item) => ({ ...item, sources: ["me/accounts"], business_ids: [] })),
    ...businessAssets.pages,
  ], safePage);
  const discoveredPages = await enrichBusinessPages(initialPages, userToken, graphBase);
  const mergedPages = mergeAssets(discoveredPages, safePage);
  const mergedAccounts = mergeAssets([
    ...rows(accounts).map((item) => ({ ...item, sources: ["me/adaccounts"], business_ids: [] })),
    ...businessAssets.accounts,
  ], safeAccount);
  const credentials = encryptPortalSecret(JSON.stringify({
    user_token: userToken,
    expires_at: Number(longToken.expires_in || shortToken.expires_in || 0) ? new Date(Date.now() + Number(longToken.expires_in || shortToken.expires_in) * 1000).toISOString() : "",
    user: { id: String(profile.id || ""), name: String(profile.name || "") },
    accounts: mergedAccounts,
    pages: mergedPages,
    businesses: businessAssets.businesses,
    granted_permissions: (permissions.data || []).filter((item) => item && typeof item.permission === "string" && item.status === "granted").map((item) => item.permission),
  }));
  if (!credentials) throw new Error("oauth_vault_unavailable");
  await writeMetaOAuthRequest(requestId, { ...pending, status: "connected", connected_at: new Date().toISOString(), credentials });
}

export default async function handleMetaOAuth(request, response) {
  const flow = String(request.query?.flow || request.body?.flow || "").trim().toLowerCase();
  if (request.method === "GET" && flow === "callback") {
    if (!configured()) return html(response, 503, "<h1>Conexión no disponible</h1><p>La conexión Meta aún no está configurada por soporte.</p>");
    const state = String(request.query?.state || "");
    const code = String(request.query?.code || "");
    if (request.query?.error || !state || !code) return html(response, 400, "<h1>Conexión cancelada</h1><p>No se recibió autorización de Facebook. Puedes cerrar esta ventana y volver a intentar desde Telegram.</p>");
    try {
      await finalizeCallback(state, code);
      return html(response, 200, "<h1>Facebook conectado</h1><p>Ya puedes volver a Telegram. Admira te mostrará las cuentas y páginas disponibles.</p>");
    } catch (error) {
      const failureCode = oauthFailureCode(error);
      // Keep server logs useful to support, without logging OAuth codes or
      // access tokens.  Meta's own detailed response stays server-side.
      console.error("meta_oauth_callback_failed", { failureCode, message: String(error?.message || "") });
      // Mark the one-time request as failed so the polling installation drops
      // it and a buyer never gets told to open the same spent link again.
      try {
        const pending = await readMetaOAuthRequest(state);
        if (pending) await writeMetaOAuthRequest(state, { ...pending, status: "failed", failed_at: new Date().toISOString(), failure_code: failureCode });
      } catch {
        // The public response still remains safe if storage is unavailable.
      }
      return html(response, 400, `<h1>No se pudo completar la conexión</h1><p>La autorización llegó, pero falló el paso <strong>${failureCode}</strong>. Vuelve a Telegram y solicita un enlace nuevo; no reutilices este enlace.</p>`);
    }
  }
  if (request.method !== "POST") return json(response, 405, { ok: false, error: "method_not_allowed" });
  if (!configured()) return json(response, 503, { ok: false, error: "oauth_not_configured" });
  try {
    if (flow === "start") {
      const handoffSecret = String(request.body?.handoff_secret || "");
      if (!validSecret(handoffSecret)) return json(response, 400, { ok: false, error: "invalid_handoff" });
      const requestId = randomBytes(32).toString("base64url");
      await writeMetaOAuthRequest(requestId, { status: "pending", created_at: new Date().toISOString(), handoff_digest: handoffDigest(handoffSecret), installation_digest: createHash("sha256").update(String(request.body?.installation_id || "")).digest("hex") });
      return json(response, 200, { ok: true, request_id: requestId, authorization_url: authorizeUrl(requestId), expires_in_seconds: Math.floor(MAX_AGE_MS / 1000) });
    }
    if (flow === "poll") {
      const requestId = String(request.body?.request_id || "");
      const handoffSecret = String(request.body?.handoff_secret || "");
      const pending = await readMetaOAuthRequest(requestId);
      if (!pending || !validSecret(handoffSecret) || !sameDigest(String(pending.handoff_digest || ""), handoffDigest(handoffSecret))) return json(response, 404, { ok: false, error: "oauth_request_not_found" });
      if (Date.now() - Date.parse(pending.created_at || "") > MAX_AGE_MS) { await deleteMetaOAuthRequest(requestId); return json(response, 410, { ok: false, error: "oauth_request_expired" }); }
      if (pending.status === "failed") {
        await deleteMetaOAuthRequest(requestId);
        return json(response, 409, { ok: false, error: "oauth_callback_failed", failure_code: String(pending.failure_code || "callback_failed") });
      }
      if (pending.status !== "connected") return json(response, 200, { ok: true, status: pending.status || "pending" });
      const raw = decryptPortalSecret(pending.credentials);
      if (!raw) return json(response, 500, { ok: false, error: "oauth_result_unavailable" });
      const credentials = JSON.parse(raw);
      await deleteMetaOAuthRequest(requestId);
      return json(response, 200, { ok: true, status: "connected", credentials });
    }
    return json(response, 400, { ok: false, error: "invalid_oauth_flow" });
  } catch (error) {
    return json(response, 502, { ok: false, error: "oauth_connection_failed" });
  }
}
