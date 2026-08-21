import test from "node:test";
import assert from "node:assert/strict";

import { mergeReleaseRegistries } from "../lib/store.js";

test("release registry reconciliation selects the newest stable version across stores", () => {
  const upstash = {
    channels: {
      stable: { version: "v1.0.215", published_at: "2026-08-04T10:00:00Z" }
    }
  };
  const blob = {
    channels: {
      stable: { version: "v1.0.216", published_at: "2026-08-05T10:00:00Z" }
    }
  };

  const merged = mergeReleaseRegistries(upstash, blob);

  assert.equal(merged.channels.stable.version, "v1.0.216");
});

test("r releases outrank legacy v1.0 markers during store reconciliation", () => {
  const upstash = { channels: { stable: { version: "r59", published_at: "2026-08-21T03:36:00Z" } } };
  const blob = { channels: { stable: { version: "v1.0.205", published_at: "2026-08-20T03:36:00Z" } } };

  const merged = mergeReleaseRegistries(upstash, blob);

  assert.equal(merged.channels.stable.version, "r59");
});

test("release registry reconciliation preserves independent channels and same-version assets", () => {
  const upstash = {
    channels: {
      stable: {
        version: "v1.0.216",
        published_at: "2026-08-05T10:00:00Z",
        assets: { "MetaAdsAgent-source.zip": { sha256: "source" } }
      },
      candidate: { version: "v1.0.217-rc1" }
    }
  };
  const blob = {
    channels: {
      stable: {
        version: "v1.0.216",
        published_at: "2026-08-05T10:00:00Z",
        assets: { "MetaAdsAgent-windows.exe": { sha256: "windows" } }
      }
    }
  };

  const merged = mergeReleaseRegistries(upstash, blob);

  assert.equal(merged.channels.candidate.version, "v1.0.217-rc1");
  assert.deepEqual(Object.keys(merged.channels.stable.assets).sort(), [
    "MetaAdsAgent-source.zip",
    "MetaAdsAgent-windows.exe"
  ]);
});
