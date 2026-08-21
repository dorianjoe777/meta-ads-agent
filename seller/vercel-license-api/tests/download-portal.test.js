import assert from "node:assert/strict";
import test from "node:test";

import { platformAsset, platformCards } from "../lib/download-portal.js";

test("Windows waits for its real installer instead of presenting the source ZIP", () => {
  const release = {
    assets: {
      "MetaAdsAgent-source.zip": {
        filename: "MetaAdsAgent-source.zip",
        source_url: "https://example.test/MetaAdsAgent-source.zip"
      }
    }
  };

  const windows = platformCards(release).find((card) => card.id === "windows");

  assert.equal(windows.available, false);
  assert.equal(windows.universal_fallback, false);
  assert.equal(windows.filename, "");
  assert.equal(windows.button, "Descargar para Windows");
  assert.match(windows.description, /instalador oficial de Windows/i);
  assert.equal(platformAsset(release, "windows"), null);
});

test("Mac waits for its real installer instead of presenting the source ZIP", () => {
  const release = {
    assets: {
      "MetaAdsAgent-source.zip": {
        filename: "MetaAdsAgent-source.zip",
        source_url: "https://example.test/MetaAdsAgent-source.zip"
      }
    }
  };

  const mac = platformCards(release).find((card) => card.id === "mac");

  assert.equal(mac.available, false);
  assert.equal(mac.universal_fallback, false);
  assert.equal(mac.filename, "");
  assert.equal(mac.button, "Descargar para Mac");
  assert.match(mac.description, /instalador oficial de Mac/i);
  assert.equal(platformAsset(release, "mac"), null);
});

test("native Windows and Mac installers remain selectable", () => {
  const release = {
    assets: {
      "MetaAdsAgent-windows.exe": {
        filename: "MetaAdsAgent-windows.exe",
        source_url: "https://example.test/MetaAdsAgent-windows.exe"
      },
      "MetaAdsAgent-mac.dmg": {
        filename: "MetaAdsAgent-mac.dmg",
        source_url: "https://example.test/MetaAdsAgent-mac.dmg"
      }
    }
  };

  assert.equal(platformAsset(release, "windows")?.asset_name, "MetaAdsAgent-windows.exe");
  assert.equal(platformAsset(release, "mac")?.asset_name, "MetaAdsAgent-mac.dmg");
});
