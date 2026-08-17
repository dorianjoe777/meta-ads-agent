import { normalizeEntitlements, signedUnlock, validFormat } from "../../lib/license.js";
import { licenseEmailMatches } from "../../lib/license-email.js";
import { ensureDeviceBinding } from "../../lib/device-binding.js";
import {
  deviceRegistrations,
  isRegisteredDevice,
  readLicense,
  registerDevice,
  resetDeviceRegistrations,
  unregisterDevice,
  writeLicense
} from "../../lib/store.js";

export default async function handler(request, response) {
  if (request.method !== "POST") {
    return response.status(405).json({ valid: false, status: "method_not_allowed" });
  }
  try {
    const { license_key: key = "", buyer_email: rawEmail = "", device_id: deviceId = "", transfer_device: transferDevice = false, install_event: rawInstallEvent = "" } = request.body || {};
    const licenseKey = String(key).trim().toUpperCase();
    const buyerEmail = String(rawEmail).trim().toLowerCase();
    const installEvent = String(rawInstallEvent || "").trim().toLowerCase();
    if (!validFormat(licenseKey)) {
      return response.status(200).json({ valid: false, status: "invalid", detail: "Licencia inválida." });
    }
    if (!buyerEmail || !buyerEmail.includes("@")) {
      return response.status(200).json({ valid: false, status: "email_required", detail: "Ingresa el email de compra." });
    }
    if (!deviceId) {
      return response.status(200).json({ valid: false, status: "device_required", detail: "No pude identificar este equipo." });
    }
    const record = await readLicense(licenseKey);
    if (!record) {
      return response.status(200).json({ valid: false, status: "not_found", detail: "No encontramos esta licencia. Contacta soporte." });
    }
    if (record.status !== "active") {
      return response.status(200).json({ valid: false, status: record.status, detail: "Esta licencia no está activa. Contacta soporte." });
    }
    if (!licenseEmailMatches(record, buyerEmail)) {
      return response.status(200).json({ valid: false, status: "email_mismatch", detail: "El email no coincide con esta licencia." });
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
      installEvent,
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
    const unlock = signedUnlock({
      licenseKey,
      buyerEmail,
      deviceId,
      features: entitlements.features,
      plan: entitlements.plan,
      maxDevices: entitlements.max_devices,
      workspaceLimit: entitlements.workspace_limit
    });
    return response.status(200).json({
      ...unlock,
      valid: true,
      status: "active",
      detail: binding.provisional
        ? "Licencia reservada para completar la instalación."
        : "Licencia activa.",
      device_binding: binding.device_binding,
      provisional: binding.provisional,
      replaced_provisional: binding.replaced_provisional
    });
  } catch (error) {
    return response.status(500).json({ valid: false, status: "server_error", detail: "No se pudo confirmar tu licencia. Contacta soporte." });
  }
}
