import assert from "node:assert/strict";
import test from "node:test";

import { platformAsset, platformCards } from "../lib/download-portal.js";

test("Windows falls back to the stable source ZIP when its EXE is not published", () => {
  const release = {
    assets: {
      "MetaAdsAgent-source.zip": {
        filename: "MetaAdsAgent-source.zip",
        source_url: "https://example.test/MetaAdsAgent-source.zip"
      }
    }
  };

  const windows = platformCards(release).find((card) => card.id === "windows");

  assert.equal(windows.available, true);
  assert.equal(windows.universal_fallback, true);
  assert.equal(windows.filename, "MetaAdsAgent-source.zip");
  assert.equal(windows.button, "Descargar ZIP para Windows");
  assert.match(windows.description, /Instalar en Windows\.bat/);
  assert.equal(platformAsset(release, "windows")?.asset_name, "MetaAdsAgent-source.zip");
});

test("Mac falls back to the stable source ZIP when its DMG is not published", () => {
  const release = {
    assets: {
      "MetaAdsAgent-source.zip": {
        filename: "MetaAdsAgent-source.zip",
        source_url: "https://example.test/MetaAdsAgent-source.zip"
      }
    }
  };

  const mac = platformCards(release).find((card) => card.id === "mac");

  assert.equal(mac.available, true);
  assert.equal(mac.universal_fallback, true);
  assert.equal(mac.filename, "MetaAdsAgent-source.zip");
  assert.equal(mac.button, "Descargar ZIP para Mac");
  assert.match(mac.description, /Instalar en Mac\.command/);
  assert.equal(platformAsset(release, "mac")?.asset_name, "MetaAdsAgent-source.zip");
});
