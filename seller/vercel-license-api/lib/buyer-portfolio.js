function text(value) {
  return String(value || "").trim();
}

function cloudStatus(cloud = {}) {
  if (!cloud || !Object.keys(cloud).length) return "not_started";
  if (text(cloud.install_status)) return text(cloud.install_status);
  if (cloud.cloud_open_url || cloud.dashboard_url) return "ready";
  return cloud.droplet_id ? "installing" : "not_started";
}

export function maskedLicenseHint(licenseKey = "") {
  const clean = text(licenseKey).toUpperCase();
  return clean ? `...${clean.replace(/[^A-Z0-9]/g, "").slice(-6)}` : "";
}

export function portfolioCard(record = {}, options = {}) {
  const cloud = record.cloud_installation || {};
  const local = record.install_state?.local || {};
  const status = cloudStatus(cloud);
  const cloudReady = Boolean((cloud.cloud_open_url || cloud.dashboard_url) && status === "ready");
  const locallyActivated = Boolean(record.last_activation_at || local.activated_at);
  const recordStatus = text(record.status) || "active";
  const fallbackNumber = Number(options.position || 0) + 1;
  const label = text(record.installation_label)
    || text(record.business_name)
    || text(record.brand_name)
    || (cloud.droplet_name ? `Admira IA · ${cloud.droplet_name}` : `Negocio ${fallbackNumber}`);
  return {
    id: text(options.id),
    label: label.slice(0, 80),
    license_hint: maskedLicenseHint(record.license_key),
    plan: text(record.plan) || "individual",
    status: recordStatus,
    selected: Boolean(options.selected),
    switch_token: text(options.switchToken),
    installation: cloudReady ? "cloud_ready" : (cloud.droplet_id ? status : (locallyActivated ? "local_active" : "not_started")),
    dashboard_url: cloudReady && recordStatus === "active" ? text(cloud.cloud_open_url || cloud.dashboard_url) : "",
    created_at: text(record.created_at)
  };
}

export function normalizeInstallationLabel(value = "") {
  return text(value).replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, 80);
}
