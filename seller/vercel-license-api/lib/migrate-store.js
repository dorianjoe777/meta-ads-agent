export async function migrateLicenseStore(source, target) {
  const registry = await source.readRegistry();
  const releases = await source.readReleases();
  const summaries = Array.isArray(registry?.licenses) ? registry.licenses : [];
  const migrated = [];
  let deviceCount = 0;

  for (const summary of summaries) {
    const licenseKey = String(summary?.license_key || "").trim();
    if (!licenseKey) continue;
    const record = await source.readLicense(licenseKey) || summary;
    await target.writeLicense(record);

    const rawDevices = Array.isArray(record.devices) ? record.devices.filter(Boolean) : [];
    for (const deviceId of rawDevices) {
      await target.registerDevice(licenseKey, deviceId);
      deviceCount += 1;
    }
    if (!rawDevices.length && typeof source.deviceRegistrations === "function" && typeof target.importDeviceRegistration === "function") {
      const registrations = await source.deviceRegistrations(licenseKey).catch(() => []);
      for (const registration of registrations) {
        if (!registration?.pathname) continue;
        await target.importDeviceRegistration(licenseKey, registration.pathname);
        deviceCount += 1;
      }
    }
    migrated.push(licenseKey);
  }

  await target.writeReleases(releases || { channels: {} });
  // Registry is written last and acts as the completed migration marker.
  await target.writeRegistry(registry || { licenses: [] });

  const verifiedRegistry = await target.readRegistry();
  const verifiedReleases = await target.readReleases();
  if ((verifiedRegistry?.licenses || []).length !== summaries.length) throw new Error("migration_registry_verification_failed");
  for (const licenseKey of migrated) {
    if (!await target.readLicense(licenseKey)) throw new Error("migration_license_verification_failed");
  }
  return {
    licenses: migrated.length,
    devices: deviceCount,
    release_channels: Object.keys(verifiedReleases?.channels || {}).length,
    verified: true
  };
}
