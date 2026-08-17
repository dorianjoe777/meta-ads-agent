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
              content_type: "application/zip",
              digest: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
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
          source_url: "https://api.github.com/repos/dorianjoe777/meta-ads-agent/releases/assets/111",
          sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        }
      }
    });
    assert.equal(release.assets["MetaAdsAgent-source.zip"].source_url, "https://api.github.com/repos/dorianjoe777/meta-ads-agent/releases/assets/999");
    assert.equal(release.assets["MetaAdsAgent-source.zip"].sha256, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
  } finally {
    globalThis.fetch = originalFetch;
    if (originalToken === undefined) delete process.env.GITHUB_RELEASE_TOKEN;
    else process.env.GITHUB_RELEASE_TOKEN = originalToken;
  }
});

test("a stale configured GitHub tag cannot downgrade the stable registry version", async () => {
  const originalFetch = globalThis.fetch;
  const originalToken = process.env.GITHUB_RELEASE_TOKEN;
  const originalTag = process.env.RELEASE_GITHUB_TAG;
  process.env.GITHUB_RELEASE_TOKEN = "gh-test-token";
  process.env.RELEASE_GITHUB_TAG = "v1.0.215";
  globalThis.fetch = async (url) => {
    assert.match(String(url), /releases\/tags\/v1\.0\.216$/);
    return { ok: true, async json() { return { assets: [] }; } };
  };
  try {
    const release = await releaseWithDiscoveredAssets({
      version: "v1.0.216",
      github_repo: "dorianjoe777/meta-ads-agent",
      assets: {}
    });
    assert.equal(release.version, "v1.0.216");
    assert.equal(release.github_release_tag, "v1.0.216");
  } finally {
    globalThis.fetch = originalFetch;
    if (originalToken === undefined) delete process.env.GITHUB_RELEASE_TOKEN;
    else process.env.GITHUB_RELEASE_TOKEN = originalToken;
    if (originalTag === undefined) delete process.env.RELEASE_GITHUB_TAG;
    else process.env.RELEASE_GITHUB_TAG = originalTag;
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

test("canonical source asset remains available for legacy updater fallback", () => {
  const release = {
    asset_name: "MetaAdsAgent-source.zip",
    assets: {
      "MetaAdsAgent-source.zip": {
        asset_name: "MetaAdsAgent-source.zip",
        filename: "MetaAdsAgent-source.zip",
        source_url: "https://example.test/current-source.zip"
      }
    }
  };
  const requested = releaseAssetByName(release, "meta-ads-operator-v1.0.105.zip");
  const fallback = requested || releaseAssetByName(release, release.asset_name);
  assert.equal(fallback.filename, "MetaAdsAgent-source.zip");
});
