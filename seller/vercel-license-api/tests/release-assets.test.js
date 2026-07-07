import assert from "node:assert/strict";
import test from "node:test";

import { releaseAssetByName, releaseWithDiscoveredAssets } from "../lib/download-portal.js";

test("discovered GitHub release assets override stale registry entries with the same filename", async () => {
  const originalFetch = globalThis.fetch;
  const originalToken = process.env.GITHUB_RELEASE_TOKEN;
  process.env.GITHUB_RELEASE_TOKEN = "gh-test-token";
  globalThis.fetch = async (url) => {
    assert.match(String(url), /releases\/tags\/v1\.0\.105$/);
    return {
      ok: true,
      async json() {
        return {
          assets: [
            {
              name: "MetaAdsAgent-source.zip",
              url: "https://api.github.com/repos/dorianjoe777/meta-ads-agent/releases/assets/999",
              content_type: "application/zip"
            }
          ]
        };
      }
    };
  };
  try {
    const release = await releaseWithDiscoveredAssets({
      version: "v1.0.105",
      assets: {
        "MetaAdsAgent-source.zip": {
          asset_name: "MetaAdsAgent-source.zip",
          filename: "MetaAdsAgent-source.zip",
          source_url: "https://api.github.com/repos/dorianjoe777/meta-ads-agent/releases/assets/111"
        }
      }
    });
    assert.equal(release.assets["MetaAdsAgent-source.zip"].source_url, "https://api.github.com/repos/dorianjoe777/meta-ads-agent/releases/assets/999");
  } finally {
    globalThis.fetch = originalFetch;
    if (originalToken === undefined) delete process.env.GITHUB_RELEASE_TOKEN;
    else process.env.GITHUB_RELEASE_TOKEN = originalToken;
  }
});

test("releaseAssetByName resolves assets by key, asset_name, name, or filename", () => {
  const release = {
    assets: {
      universal: {
        name: "MetaAdsAgent-source.zip",
        filename: "MetaAdsAgent-source.zip",
        source_url: "https://example.test/source.zip"
      }
    }
  };
  assert.equal(releaseAssetByName(release, "MetaAdsAgent-source.zip").source_url, "https://example.test/source.zip");
});
