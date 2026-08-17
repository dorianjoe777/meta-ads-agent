import test from "node:test";
import assert from "node:assert/strict";
import {
  deleteDigitalOceanCloudInstall,
  setCloudNetworkMode,
  writeCloudInstallationIfCurrent
} from "../api/portal/cloud/digitalocean.js";
import {
  buildDigitalOceanCloudInit,
  cloudCleanResetCapability,
  cloudCleanResetStatus,
  requestCloudCleanReset
} from "../lib/digitalocean-cloud.js";

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

test("pending cloud install can be persisted before DigitalOcean returns a Droplet id", async () => {
  const writes = [];
  const original = { license_key: "MAO-PENDING-TEST", buyer_email: "buyer@example.com", cloud_installation: null };
  const pending = {
    provider: "digitalocean",
    install_job_id: "cloud-job-123456",
    droplet_tag: "admira-ia-cloud-job-123456",
    firewall_id: "firewall-pending",
    install_status: "creating",
    install_progress: 12
  };
  const saved = await writeCloudInstallationIfCurrent(original, pending, {}, {
    readLicense: async () => ({ ...original, cloud_installation: null }),
    writeLicense: async (record) => writes.push(record)
  });
  assert.equal(saved, true);
  assert.equal(writes.length, 1);
  assert.equal(writes[0].cloud_installation.install_job_id, "cloud-job-123456");
});

test("a second pending cloud install cannot overwrite an existing job", async () => {
  const writes = [];
  const original = { license_key: "MAO-PENDING-TEST-2", cloud_installation: null };
  const current = { ...original, cloud_installation: { provider: "digitalocean", install_job_id: "cloud-job-existing" } };
  const saved = await writeCloudInstallationIfCurrent(original, {
    provider: "digitalocean",
    install_job_id: "cloud-job-new",
    install_status: "creating"
  }, {}, {
    readLicense: async () => current,
    writeLicense: async (record) => writes.push(record)
  });
  assert.equal(saved, false);
  assert.equal(writes.length, 0);
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

test("cloud clean reset uses the private gate without exposing its secret in the URL", async () => {
  const calls = [];
  const cloud = {
    droplet_ip: "203.0.113.44",
    access_gate_port: "7870",
    cloud_access_secret: "secret-for-reset"
  };
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return { ok: true, status: 202, json: async () => ({ ok: true, status: "queued", job_id: "job-123" }) };
  };
  const result = await requestCloudCleanReset(cloud, { fetchImpl });
  assert.equal(result.status, "queued");
  assert.equal(calls[0].url, "http://203.0.113.44:7870/admin/reset");
  assert.equal(calls[0].options.headers["X-Admira-Cloud-Secret"], "secret-for-reset");
  assert.equal(calls[0].url.includes("secret-for-reset"), false);
  assert.equal(JSON.parse(calls[0].options.body).scope, "clean_installation");
  assert.equal(cloudCleanResetCapability(cloud), true);
});

test("cloud clean reset status proxies through the same private gate", async () => {
  const calls = [];
  const result = await cloudCleanResetStatus({ droplet_ip: "203.0.113.45", cloud_access_secret: "secret" }, {
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      return { ok: true, status: 200, json: async () => ({ ok: true, status: "complete" }) };
    }
  });
  assert.equal(result.status, "complete");
  assert.equal(calls[0].url, "http://203.0.113.45:7870/admin/reset-status");
  assert.equal(calls[0].options.headers["X-Admira-Cloud-Secret"], "secret");
});

test("testing mode publishes only dashboard and HTTPS firewall ports", async () => {
  const calls = [];
  const cloud = {
    ...loadedRecord.cloud_installation,
    droplet_id: 12345,
    firewall_id: "firewall-123",
    initial_client_ip: "203.0.113.44",
    dashboard_port: "7871",
    network_mode: "strict"
  };
  const result = await setCloudNetworkMode({ ...loadedRecord, cloud_installation: cloud }, "testing", {
    digitalOceanToken: `dop_v1_${"c".repeat(45)}`,
    doRequest: async (_token, path, options = {}) => {
      calls.push({ path, options });
      if (!options.method || options.method === "GET") {
        return { firewall: {
          name: "admira-firewall",
          inbound_rules: [
            { protocol: "tcp", ports: "22", sources: { addresses: ["0.0.0.0/0"] } },
            { protocol: "tcp", ports: "7871", sources: { addresses: ["203.0.113.44/32"] } },
            { protocol: "tcp", ports: "443", sources: { addresses: ["203.0.113.44/32"] } }
          ],
          outbound_rules: [],
          tags: ["admira"]
        } };
      }
      return {};
    }
  });
  assert.equal(result.mode, "testing");
  assert.equal(result.public_dashboard, true);
  assert.equal(calls[1].path, "/firewalls/firewall-123");
  const ports = calls[1].options.body.inbound_rules.filter((rule) => ["7871", "443"].includes(rule.ports));
  assert.deepEqual(ports.flatMap((rule) => rule.sources.addresses), ["0.0.0.0/0", "::/0", "0.0.0.0/0", "::/0"]);
  assert.equal(calls[1].options.body.inbound_rules.some((rule) => rule.ports === "22"), true);
});

test("strict mode restores the saved authorized IPv4 without changing SSH", async () => {
  const calls = [];
  const result = await setCloudNetworkMode({ ...loadedRecord, cloud_installation: {
    ...loadedRecord.cloud_installation,
    initial_client_ip: "198.51.100.7",
    dashboard_port: "7871"
  } }, "strict", {
    digitalOceanToken: `dop_v1_${"d".repeat(45)}`,
    doRequest: async (_token, path, options = {}) => {
      calls.push({ path, options });
      if (!options.method) return { firewall: {
        inbound_rules: [
          { protocol: "tcp", ports: "22", sources: { addresses: ["0.0.0.0/0"] } },
          { protocol: "tcp", ports: "7871", sources: { addresses: ["0.0.0.0/0"] } },
          { protocol: "tcp", ports: "443", sources: { addresses: ["0.0.0.0/0"] } }
        ], outbound_rules: []
      } };
      return {};
    }
  });
  assert.equal(result.mode, "strict");
  const inbound = calls[1].options.body.inbound_rules;
  assert.deepEqual(inbound.find((rule) => rule.ports === "7871").sources.addresses, ["198.51.100.7/32"]);
  assert.deepEqual(inbound.find((rule) => rule.ports === "22").sources.addresses, ["0.0.0.0/0"]);
});

test("new cloud init contains the guarded clean reset command and endpoint", () => {
  const script = buildDigitalOceanCloudInit({
    signedDownloadUrl: "https://example.com/release.zip",
    licenseKey: "MAO-RESET-CLOUD-TEST",
    buyerEmail: "buyer@example.com",
    deviceId: "device-123",
    licenseServerUrl: "https://admira.example.com",
    digitalOceanToken: `dop_v1_${"a".repeat(45)}`,
    firewallId: "firewall-123",
    initialClientIp: "203.0.113.1"
  });
  assert.ok(script.includes("/usr/local/bin/admira-cloud-clean-reset"));
  assert.ok(script.includes("/admin/reset-status"));
  assert.ok(script.includes("META_ACCESS_TOKEN"));
  assert.ok(script.includes("ChatGPT/Codex"));
});

test("cloud clean reset is a fresh workspace while preserving provider auth and license identity", () => {
  const script = buildDigitalOceanCloudInit({
    signedDownloadUrl: "https://example.com/release.zip",
    licenseKey: "MAO-RESET-FRESH-TEST",
    buyerEmail: "buyer@example.com",
    deviceId: "device-fresh",
    licenseServerUrl: "https://admira.example.com",
    digitalOceanToken: `dop_v1_${"b".repeat(45)}`,
    firewallId: "firewall-fresh",
    initialClientIp: "203.0.113.2"
  });
  assert.ok(script.includes('preserve=("hermes-home", "hermes-image-home", "license_unlock.json", "update-snapshots")'));
  assert.ok(script.includes("reset_state_home(runtime / \"hermes\")"));
  assert.ok(script.includes("reset_state_home(runtime / \"codex\")"));
  assert.ok(script.includes("ad-config.example.json"));
  assert.ok(script.includes('"TELEGRAM_BOT_TOKEN"') === false, "the Telegram bot token is not a reset key");
  assert.ok(script.includes('"META_AD_ACCOUNT_ID"'));
  assert.ok(script.includes('"DAILY_SOCIAL_CONTENT_ENABLED"'));
  assert.ok(script.includes('"auth.json"'));
});
