import test from "node:test";
import assert from "node:assert/strict";
import {
  deleteDigitalOceanCloudInstall,
  writeCloudInstallationIfCurrent
} from "../api/portal/cloud/digitalocean.js";

const loadedRecord = {
  license_key: "MAO-RESET-TEST",
  buyer_email: "buyer@example.com",
  cloud_installation: {
    droplet_id: 12345,
    firewall_id: "firewall-123",
    provider: "digitalocean",
    cloud_access_secret: "cloud-secret",
    install_status: "installing"
  }
};

test("a stale cloud status response cannot restore a buyer-reset Droplet", async () => {
  const writes = [];
  const currentAfterReset = {
    ...loadedRecord,
    cloud_installation: null,
    cloud_installation_reset_at: "2026-06-24T12:00:00.000Z"
  };
  const saved = await writeCloudInstallationIfCurrent(
    loadedRecord,
    { ...loadedRecord.cloud_installation, install_status: "ready" },
    {},
    {
      readLicense: async () => currentAfterReset,
      writeLicense: async (record) => writes.push(record)
    }
  );
  assert.equal(saved, false);
  assert.equal(writes.length, 0);
});

test("cloud status persists when it still belongs to the current Droplet", async () => {
  const writes = [];
  const current = { ...loadedRecord, support_note: "keep-me" };
  const updatedCloud = { ...loadedRecord.cloud_installation, install_status: "ready", install_progress: 100 };
  const saved = await writeCloudInstallationIfCurrent(
    loadedRecord,
    updatedCloud,
    {},
    {
      readLicense: async () => current,
      writeLicense: async (record) => writes.push(record)
    }
  );
  assert.equal(saved, true);
  assert.equal(writes.length, 1);
  assert.equal(writes[0].cloud_installation.install_status, "ready");
  assert.equal(writes[0].support_note, "keep-me");
});

test("buyer delete removes the saved DigitalOcean Droplet before clearing portal state", async () => {
  const calls = [];
  const clearedReasons = [];
  const result = await deleteDigitalOceanCloudInstall(
    loadedRecord,
    `dop_v1_${"a".repeat(45)}`,
    {
      doRequest: async (token, path, options = {}) => {
        calls.push({ token, path, method: options.method || "GET" });
        return {};
      },
      clearCloudInstallation: async (_record, reason) => {
        clearedReasons.push(reason);
        return { valid: true, cloud_installation: null, install_state: { cloud: {}, local: {} } };
      }
    }
  );
  assert.equal(result.valid, true);
  assert.equal(result.status, "cloud_deleted");
  assert.equal(result.deleted_cloud, true);
  assert.equal(result.droplet_deleted, true);
  assert.equal(calls[0].path, "/droplets/12345");
  assert.equal(calls[0].method, "DELETE");
  assert.equal(calls[1].path, "/firewalls/firewall-123");
  assert.equal(clearedReasons[0], "buyer_deleted_droplet_from_portal");
});

test("buyer delete treats an already missing Droplet as a successful portal cleanup", async () => {
  const calls = [];
  const missing = new Error("not found");
  missing.statusCode = 404;
  const result = await deleteDigitalOceanCloudInstall(
    loadedRecord,
    `dop_v1_${"b".repeat(45)}`,
    {
      doRequest: async (_token, path, options = {}) => {
        calls.push({ path, method: options.method || "GET" });
        if (path.startsWith("/droplets/")) throw missing;
        return {};
      },
      clearCloudInstallation: async (_record, reason) => ({
        valid: true,
        cleanup_reason: reason,
        cloud_installation: null,
        install_state: { cloud: {}, local: {} }
      })
    }
  );
  assert.equal(result.valid, true);
  assert.equal(result.status, "cloud_deleted");
  assert.equal(result.droplet_was_missing, true);
  assert.equal(result.cleanup_reason, "buyer_delete_requested_droplet_already_missing");
  assert.equal(calls[0].path, "/droplets/12345");
});
