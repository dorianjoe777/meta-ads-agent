import test from "node:test";
import assert from "node:assert/strict";
import { ensureDeviceBinding } from "../lib/device-binding.js";

function memoryStore(initial = []) {
  const registered = new Set(initial);
  return {
    registered,
    async deviceRegistrations() {
      return [...registered].map((device_id) => ({ device_id }));
    },
    isRegisteredDevice(rows, _licenseKey, deviceId) {
      return rows.some((row) => row.device_id === deviceId);
    },
    async registerDevice(_licenseKey, deviceId) {
      registered.add(deviceId);
    },
    async unregisterDevice(_licenseKey, deviceId) {
      registered.delete(deviceId);
    },
    async resetDeviceRegistrations() {
      const count = registered.size;
      registered.clear();
      return count;
    }
  };
}

const individual = { plan: "individual", max_devices: 1 };

test("failed first install reservation can move without an explicit transfer", async () => {
  const record = { devices: [] };
  const store = memoryStore();
  const first = await ensureDeviceBinding({
    record,
    licenseKey: "MAO-TEST",
    deviceId: "container-a",
    entitlements: individual,
    store,
    now: "2026-07-27T10:00:00.000Z"
  });
  assert.equal(first.provisional, true);
  assert.deepEqual([...store.registered], ["container-a"]);

  const retry = await ensureDeviceBinding({
    record,
    licenseKey: "MAO-TEST",
    deviceId: "container-b",
    entitlements: individual,
    store,
    now: "2026-07-27T10:05:00.000Z"
  });
  assert.equal(retry.ok, true);
  assert.equal(retry.replaced_provisional, true);
  assert.deepEqual([...store.registered], ["container-b"]);
  assert.deepEqual(record.devices, ["container-b"]);
});

test("completed onboarding confirms the device and prevents silent replacement", async () => {
  const record = { devices: [] };
  const store = memoryStore();
  await ensureDeviceBinding({
    record,
    licenseKey: "MAO-TEST",
    deviceId: "container-a",
    entitlements: individual,
    store
  });
  const confirmed = await ensureDeviceBinding({
    record,
    licenseKey: "MAO-TEST",
    deviceId: "container-a",
    entitlements: individual,
    installEvent: "onboarding_completed",
    store
  });
  assert.equal(confirmed.device_binding, "confirmed");
  assert.equal(record.install_state.local.onboarding_completed_at.length > 0, true);

  const another = await ensureDeviceBinding({
    record,
    licenseKey: "MAO-TEST",
    deviceId: "container-b",
    entitlements: individual,
    store
  });
  assert.equal(another.ok, false);
  assert.equal(another.status, "device_limit");
  assert.deepEqual([...store.registered], ["container-a"]);
});

test("legacy registered devices remain confirmed for backwards compatibility", async () => {
  const record = { devices: ["legacy-device"] };
  const store = memoryStore(["legacy-device"]);
  const existing = await ensureDeviceBinding({
    record,
    licenseKey: "MAO-TEST",
    deviceId: "legacy-device",
    entitlements: individual,
    store
  });
  assert.equal(existing.device_binding, "confirmed");
  assert.equal(existing.provisional, false);
});

test("agency retry replaces only a provisional slot and preserves confirmed devices", async () => {
  const record = {
    devices: ["confirmed-a", "provisional-b"],
    device_bindings: [
      { device_id: "confirmed-a", status: "confirmed" },
      { device_id: "provisional-b", status: "provisional" }
    ]
  };
  const store = memoryStore(["confirmed-a", "provisional-b"]);
  const result = await ensureDeviceBinding({
    record,
    licenseKey: "MAO-AGENCY",
    deviceId: "retry-c",
    entitlements: { plan: "agency", max_devices: 2 },
    store
  });
  assert.equal(result.ok, true);
  assert.deepEqual(new Set(store.registered), new Set(["confirmed-a", "retry-c"]));
  assert.equal(record.device_bindings.find((row) => row.device_id === "confirmed-a").status, "confirmed");
});
