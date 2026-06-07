import { normalizeEntitlements, signedPortalSession, validFormat, verifyPortalSession } from "../../lib/license.js";
import { buyerFacingImprovements, platformCards, releaseWithDiscoveredAssets } from "../../lib/download-portal.js";
import { deviceRegistrations, readLicense, readReleases } from "../../lib/store.js";

const PORTAL_COOKIE = "admiro_portal_session";

function json(response, status, payload) {
  response.setHeader("Cache-Control", "private, no-store");
  response.setHeader("X-Content-Type-Options", "nosniff");
  return response.status(status).json(payload);
}

function friendlyFailure(response, status, detail) {
  return json(response, 200, { valid: false, status, detail });
}

function cloudInstallStatus(cloudInstallation) {
  if (!cloudInstallation) return "not_started";
  if (!cloudInstallation.cloud_open_url && !cloudInstallation.dashboard_url && cloudInstallation.droplet_id) {
    return "waiting_for_ip";
  }
  if (cloudInstallation.install_status) return cloudInstallation.install_status;
  const created = Date.parse(String(cloudInstallation.created_at || ""));
  if (Number.isFinite(created) && Date.now() - created < 12 * 60 * 1000) {
    return "installing";
  }
  return "ready";
}

function portalCookieMaxAge() {
  const days = Math.max(1, Math.min(Number(process.env.PORTAL_REMEMBER_DAYS || 14), 30));
  return Math.floor(days * 24 * 60 * 60);
}

function setPortalCookie(response, token) {
  response.setHeader(
    "Set-Cookie",
    `${PORTAL_COOKIE}=${encodeURIComponent(token)}; Max-Age=${portalCookieMaxAge()}; Path=/; HttpOnly; Secure; SameSite=Lax`
  );
}

function clearPortalCookie(response) {
  response.setHeader("Set-Cookie", `${PORTAL_COOKIE}=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Lax`);
}

function cookieValue(request, name) {
  const cookie = String(request.headers.cookie || "");
  for (const item of cookie.split(";")) {
    const [rawKey, ...rest] = item.trim().split("=");
    if (rawKey === name) {
      return decodeURIComponent(rest.join("=") || "");
    }
  }
  return "";
}

async function portalPayload({ request, response, licenseKey, buyerEmail, channel, remember = false, detail = "Acceso confirmado." }) {
    const record = await readLicense(licenseKey);
    if (!record) {
      return friendlyFailure(response, "not_found", "No encontramos esta compra. Revisa el email o contacta soporte.");
    }
    if (record.status !== "active") {
      return friendlyFailure(response, record.status, "Esta compra no esta activa. Contacta soporte.");
    }
    if (String(record.buyer_email || "").toLowerCase() !== buyerEmail) {
      return friendlyFailure(response, "email_mismatch", "El email no coincide con esta compra.");
    }

    const releases = await readReleases();
    const release = releases.channels?.[channel];
    if (!release) {
      return friendlyFailure(response, "release_missing", "Todavia no hay una version publicada para descargar. Contacta soporte.");
    }
    const fullRelease = await releaseWithDiscoveredAssets(release);
    const entitlements = normalizeEntitlements(record);
    const registrations = await deviceRegistrations(licenseKey).catch(() => []);
    const cloudInstallation = record.cloud_installation || null;
    const cloudStatus = cloudInstallStatus(cloudInstallation);
    const localState = record.install_state?.local || {};
    const installState = {
      cloud: {
        installed: Boolean(cloudInstallation),
        provider: cloudInstallation?.provider || "",
        droplet_id: cloudInstallation?.droplet_id || "",
        created_at: cloudInstallation?.created_at || "",
        dashboard_available: Boolean((cloudInstallation?.cloud_open_url || cloudInstallation?.dashboard_url) && cloudStatus === "ready"),
        progress: cloudStatus === "ready" ? 100 : Number(cloudInstallation?.install_progress || 18),
        status: cloudStatus
      },
      local: {
        activated: registrations.length > 0 || Boolean(record.last_activation_at || localState.activated_at),
        device_count: registrations.length,
        last_activation_at: record.last_activation_at || localState.activated_at || "",
        onboarding_opened_at: localState.onboarding_opened_at || "",
        onboarding_completed_at: localState.onboarding_completed_at || "",
        last_event: localState.last_event || ""
      }
    };
    const session = signedPortalSession({
      licenseKey,
      buyerEmail,
      channel,
      plan: entitlements.plan
    });
    if (remember) {
      const remembered = signedPortalSession({
        licenseKey,
        buyerEmail,
        channel,
        plan: entitlements.plan,
        minutes: portalCookieMaxAge() / 60
      });
      setPortalCookie(response, remembered.token);
    } else {
      clearPortalCookie(response);
    }
    return json(response, 200, {
      valid: true,
      status: "active",
      detail,
      version: release.version,
      portal_token: session.token,
      expires_at: session.expires_at,
      plan: entitlements.plan,
      improvements: buyerFacingImprovements(release.improvements || []),
      platforms: platformCards(fullRelease),
      install_state: installState,
      cloud_installation: cloudInstallation,
      cloud_secrets: {}
    });
}

export default async function handler(request, response) {
  if (request.method === "DELETE") {
    clearPortalCookie(response);
    return json(response, 200, { valid: true, status: "signed_out", detail: "Sesion cerrada." });
  }
  if (request.method === "GET") {
    try {
      const remembered = verifyPortalSession(cookieValue(request, PORTAL_COOKIE));
      if (!remembered) {
        return friendlyFailure(response, "no_session", "No hay una sesion guardada.");
      }
      return portalPayload({
        request,
        response,
        licenseKey: remembered.license_key,
        buyerEmail: String(remembered.buyer_email || "").toLowerCase(),
        channel: remembered.channel || "stable",
        remember: true,
        detail: "Acceso restaurado."
      });
    } catch {
      clearPortalCookie(response);
      return json(response, 500, { valid: false, status: "server_error", detail: "No pude restaurar la sesion." });
    }
  }
  if (request.method !== "POST") {
    return json(response, 405, { valid: false, status: "method_not_allowed", detail: "Metodo no permitido." });
  }
  try {
    const {
      buyer_email: rawEmail = "",
      access_password: rawPassword = "",
      channel: rawChannel = "stable",
      remember_access: rememberAccess = true
    } = request.body || {};
    const buyerEmail = String(rawEmail).trim().toLowerCase();
    const licenseKey = String(rawPassword).trim().toUpperCase();
    const channel = String(rawChannel).trim() || "stable";
    if (!buyerEmail || !buyerEmail.includes("@")) {
      return friendlyFailure(response, "email_required", "Ingresa el email de compra.");
    }
    if (!validFormat(licenseKey)) {
      return friendlyFailure(response, "invalid_password", "La clave de acceso no es valida.");
    }
    return portalPayload({
      request,
      response,
      licenseKey,
      buyerEmail,
      channel,
      remember: rememberAccess !== false
    });
  } catch {
    return json(response, 500, { valid: false, status: "server_error", detail: "No pude abrir el portal. Intenta otra vez o contacta soporte." });
  }
}
