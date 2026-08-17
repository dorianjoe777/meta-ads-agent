const INSTALL_EVENTS = new Set(["local_activated", "onboarding_opened", "onboarding_completed"]);

function normalizedBindings(record = {}) {
  const rows = Array.isArray(record.device_bindings) ? record.device_bindings : [];
  const bindings = rows
    .filter((row) => row && typeof row === "object" && String(row.device_id || "").trim())
    .map((row) => ({
      ...row,
      device_id: String(row.device_id).trim(),
      status: row.status === "provisional" ? "provisional" : "confirmed"
    }));
  const known = new Set(bindings.map((row) => row.device_id));
  // Devices created before provisional binding existed are kept confirmed.
  for (const deviceId of Array.isArray(record.devices) ? record.devices : []) {
    const cleanDeviceId = String(deviceId || "").trim();
    if (cleanDeviceId && !known.has(cleanDeviceId)) {
      bindings.push({ device_id: cleanDeviceId, status: "confirmed", migrated_legacy: true });
      known.add(cleanDeviceId);
    }
  }
  return bindings;
}

function upsertBinding(bindings, deviceId, status, now) {
  const index = bindings.findIndex((row) => row.device_id === deviceId);
  const existing = index >= 0 ? bindings[index] : {};
  const next = {
    ...existing,
    device_id: deviceId,
    status,
    reserved_at: existing.reserved_at || now,
    last_seen_at: now
  };
  if (status === "confirmed") next.confirmed_at = existing.confirmed_at || now;
  if (index >= 0) bindings[index] = next;
  else bindings.push(next);
}

function updateInstallState(record, deviceId, installEvent, bindingStatus, now) {
  record.last_activation_at = now;
  const localInstall = { ...(record.install_state?.local || {}) };
  localInstall.activated_at ||= now;
  localInstall.last_activation_seen_at = now;
  if (installEvent === "onboarding_opened") {
    localInstall.onboarding_opened_at ||= now;
    localInstall.last_onboarding_opened_at = now;
  }
  if (installEvent === "onboarding_completed") {
    localInstall.onboarding_completed_at = now;
  }
  localInstall.last_event = INSTALL_EVENTS.has(installEvent) ? installEvent : "local_activated";
  localInstall.last_event_at = now;
  localInstall.device_id = deviceId;
  localInstall.device_binding = bindingStatus;
  record.install_state = { ...(record.install_state || {}), local: localInstall };
}

export async function ensureDeviceBinding({
  record,
  licenseKey,
  deviceId,
  entitlements,
  transferDevice = false,
  installEvent = "",
  store,
  now = new Date().toISOString()
}) {
  const cleanDeviceId = String(deviceId || "").trim();
  if (!cleanDeviceId || cleanDeviceId.length > 200) {
    return { ok: false, status: "device_required", detail: "No pude identificar este equipo." };
  }
  const registrations = await store.deviceRegistrations(licenseKey);
  let registered = store.isRegisteredDevice(registrations, licenseKey, cleanDeviceId);
  const wasRegistered = registered;
  let bindings = normalizedBindings(record);
  let replacedProvisional = "";

  if (!registered && registrations.length >= entitlements.max_devices) {
    const canTransfer = transferDevice && entitlements.plan === "individual" && entitlements.max_devices === 1;
    if (canTransfer) {
      await store.resetDeviceRegistrations(licenseKey);
      record.devices = [];
      bindings = [];
      record.last_device_transfer_at = now;
    } else {
      const replaceable = bindings.find(
        (row) => row.status === "provisional"
          && store.isRegisteredDevice(registrations, licenseKey, row.device_id)
      );
      if (!replaceable) {
        return {
          ok: false,
          status: "device_limit",
          transfer_available: entitlements.plan === "individual" && entitlements.max_devices === 1,
          detail: entitlements.plan === "individual" && entitlements.max_devices === 1
            ? "Esta licencia ya está activa en otro equipo. Puedes transferirla si ya no usarás el anterior."
            : "Esta licencia ya alcanzó el límite de equipos. Contacta soporte."
        };
      }
      await store.unregisterDevice(licenseKey, replaceable.device_id);
      replacedProvisional = replaceable.device_id;
      bindings = bindings.filter((row) => row.device_id !== replaceable.device_id);
      record.devices = (Array.isArray(record.devices) ? record.devices : [])
        .filter((value) => String(value) !== replaceable.device_id);
    }
  }

  if (!registered) {
    await store.registerDevice(licenseKey, cleanDeviceId);
    registered = true;
  }
  record.devices = Array.isArray(record.devices) ? record.devices : [];
  if (!record.devices.includes(cleanDeviceId)) record.devices.push(cleanDeviceId);

  let existing = bindings.find((row) => row.device_id === cleanDeviceId);
  if (wasRegistered && !existing) {
    existing = { device_id: cleanDeviceId, status: "confirmed", migrated_legacy: true };
    bindings.push(existing);
  }
  const bindingStatus = installEvent === "onboarding_completed"
    ? "confirmed"
    : (existing?.status || "provisional");
  upsertBinding(bindings, cleanDeviceId, bindingStatus, now);
  record.device_bindings = bindings;
  updateInstallState(record, cleanDeviceId, installEvent, bindingStatus, now);
  return {
    ok: true,
    status: "active",
    device_binding: bindingStatus,
    provisional: bindingStatus === "provisional",
    replaced_provisional: Boolean(replacedProvisional)
  };
}
