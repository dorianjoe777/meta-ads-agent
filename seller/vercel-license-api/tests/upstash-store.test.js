import test from "node:test";
import assert from "node:assert/strict";
import { createUpstashStore } from "../lib/upstash-store.js";
import { migrateLicenseStore } from "../lib/migrate-store.js";

function redisMock() {
  const strings = new Map();
  const sets = new Map();
  const requests = [];
  const fetchImpl = async (url, options) => {
    const [command, key, ...values] = JSON.parse(options.body);
    requests.push({ url, authorization: options.headers.Authorization, command });
    let result = null;
    if (command === "GET") result = strings.has(key) ? strings.get(key) : null;
    if (command === "MGET") result = [key, ...values].map((item) => strings.has(item) ? strings.get(item) : null);
    if (command === "SET") { strings.set(key, values[0]); result = "OK"; }
    if (command === "SADD") { const set = sets.get(key) || new Set(); const before = set.size; for (const value of values) set.add(value); sets.set(key, set); result = set.size - before; }
    if (command === "SREM") { const set = sets.get(key) || new Set(); let removed = 0; for (const value of values) removed += Number(set.delete(value)); sets.set(key, set); result = removed; }
    if (command === "SMEMBERS") result = [...(sets.get(key) || [])];
    if (command === "SCARD") result = (sets.get(key) || new Set()).size;
    if (command === "DEL") { const existed = Number(strings.delete(key) || sets.delete(key)); result = existed; }
    return { ok: true, status: 200, json: async () => ({ result }) };
  };
  return { fetchImpl, requests, strings, sets };
}

function testStore(mock = redisMock()) {
  return {
    mock,
    store: createUpstashStore({
      url: "https://admira-test.upstash.io",
      token: "test-token-with-more-than-twenty-characters",
      fetchImpl: mock.fetchImpl
    })
  };
}

test("stores licenses, registries, releases and device sets without list operations", async () => {
  const { mock, store } = testStore();
  const license = { license_key: "MAO-TEST-KEY", buyer_email: "buyer@example.com", devices: ["device-a"] };
  await store.writeRegistry({ licenses: [license] });
  await store.writeLicense(license);
  await store.writeReleases({ channels: { stable: { version: "v1" } } });
  await store.registerDevice(license.license_key, "device-a");

  assert.deepEqual(await store.readLicense(license.license_key), license);
  assert.equal((await store.readRegistry()).licenses.length, 1);
  assert.equal((await store.readReleases()).channels.stable.version, "v1");
  const devices = await store.deviceRegistrations(license.license_key);
  assert.equal(devices.length, 1);
  assert.equal(store.isRegisteredDevice(devices, license.license_key, "device-a"), true);
  assert.equal(mock.requests.some((request) => request.authorization === "Bearer test-token-with-more-than-twenty-characters"), true);
  assert.equal(mock.requests.some((request) => ["KEYS", "SCAN"].includes(request.command)), false);
});

test("keeps concurrently indexed licenses even when a stale registry document is written", async () => {
  const { store } = testStore();
  const first = { license_key: "MAO-FIRST", buyer_email: "first@example.com" };
  const second = { license_key: "MAO-SECOND", buyer_email: "second@example.com" };
  await store.writeLicense(first);
  await store.writeRegistry({ licenses: [first] });
  await store.writeLicense(second);
  await store.writeRegistry({ licenses: [first] });

  const registry = await store.readRegistry();
  assert.deepEqual(new Set(registry.licenses.map((record) => record.license_key)), new Set(["MAO-FIRST", "MAO-SECOND"]));
});

test("resets device registrations with set cardinality and delete", async () => {
  const { store } = testStore();
  await store.registerDevice("MAO-TEST-KEY", "device-a");
  await store.registerDevice("MAO-TEST-KEY", "device-b");
  assert.equal(await store.resetDeviceRegistrations("MAO-TEST-KEY"), 2);
  assert.equal((await store.deviceRegistrations("MAO-TEST-KEY")).length, 0);
});

test("removes only the requested device registration", async () => {
  const { store } = testStore();
  await store.registerDevice("MAO-TEST-KEY", "device-a");
  await store.registerDevice("MAO-TEST-KEY", "device-b");
  await store.unregisterDevice("MAO-TEST-KEY", "device-a");
  const devices = await store.deviceRegistrations("MAO-TEST-KEY");
  assert.equal(devices.length, 1);
  assert.equal(store.isRegisteredDevice(devices, "MAO-TEST-KEY", "device-b"), true);
});

test("rejects non-Upstash endpoints before network access", () => {
  assert.throws(
    () => createUpstashStore({ url: "https://127.0.0.1/internal", token: "test-token-with-more-than-twenty-characters", fetchImpl: async () => ({}) }),
    /upstash_configuration_invalid/
  );
});

test("migration copies and verifies license, device and release state", async () => {
  const { store } = testStore();
  const records = [
    { license_key: "MAO-ONE", buyer_email: "one@example.com", devices: ["device-one"] },
    { license_key: "MAO-TWO", buyer_email: "two@example.com", devices: [] }
  ];
  const source = {
    readRegistry: async () => ({ licenses: records }),
    readReleases: async () => ({ channels: { stable: { version: "v1" } } }),
    readLicense: async (key) => records.find((record) => record.license_key === key),
    deviceRegistrations: async () => []
  };
  const result = await migrateLicenseStore(source, store);
  assert.deepEqual(result, { licenses: 2, devices: 1, release_channels: 1, verified: true });
  assert.equal((await store.readLicense("MAO-ONE")).buyer_email, "one@example.com");
  assert.equal((await store.deviceRegistrations("MAO-ONE")).length, 1);
});
