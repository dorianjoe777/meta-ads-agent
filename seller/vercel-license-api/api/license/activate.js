import { normalizeEntitlements, signedUnlock, validFormat } from "../../lib/license.js";
import { deviceRegistrations, isRegisteredDevice, readLicense, registerDevice, resetDeviceRegistrations, writeLicense } from "../../lib/store.js";

export default async function handler(request, response) {
  if (request.method !== "POST") {
    return response.status(405).json({ valid: false, status: "method_not_allowed" });
  }
  try {
    const { license_key: key = "", buyer_email: rawEmail = "", device_id: deviceId = "", transfer_device: transferDevice = false } = request.body || {};
    const licenseKey = String(key).trim().toUpperCase();
    const buyerEmail = String(rawEmail).trim().toLowerCase();
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
    if (String(record.buyer_email).toLowerCase() !== buyerEmail) {
      return response.status(200).json({ valid: false, status: "email_mismatch", detail: "El email no coincide con esta licencia." });
    }
    const entitlements = normalizeEntitlements(record);
    record.plan = entitlements.plan;
    record.max_devices = entitlements.max_devices;
    record.workspace_limit = entitlements.workspace_limit;
    record.features = entitlements.features;
    const registrations = await deviceRegistrations(licenseKey);
    if (!isRegisteredDevice(registrations, licenseKey, deviceId)) {
      if (registrations.length >= entitlements.max_devices) {
        if (transferDevice && entitlements.plan === "individual" && entitlements.max_devices === 1) {
          await resetDeviceRegistrations(licenseKey);
          record.devices = [];
          record.last_device_transfer_at = new Date().toISOString();
        } else {
          return response.status(200).json({
            valid: false,
            status: "device_limit",
            transfer_available: entitlements.plan === "individual" && entitlements.max_devices === 1,
            detail: entitlements.plan === "individual" && entitlements.max_devices === 1
              ? "Esta licencia ya esta activa en otro equipo. Puedes transferirla a este equipo si ya no usaras el anterior."
              : "Esta licencia ya alcanzó el límite de equipos. Contacta soporte."
          });
        }
      }
      await registerDevice(licenseKey, deviceId);
    }
    record.devices ||= [];
    if (!record.devices.includes(deviceId)) record.devices.push(deviceId);
    record.last_activation_at = new Date().toISOString();
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
    return response.status(200).json({ ...unlock, valid: true, status: "active", detail: "Licencia activa." });
  } catch (error) {
    return response.status(500).json({ valid: false, status: "server_error", detail: "No se pudo confirmar tu licencia. Contacta soporte." });
  }
}
