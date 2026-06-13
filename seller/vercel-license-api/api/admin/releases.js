import { bearerAllowed } from "../../lib/license.js";
import { readReleases, writeReleases } from "../../lib/store.js";

function normalizeAsset(body = {}) {
  const assetName = String(body.asset_name || "").trim();
  const sourceUrl = String(body.source_url || "").trim();
  const blobPath = String(body.blob_path || "").trim();
  if (!assetName || (!sourceUrl && !blobPath)) {
    return null;
  }
  return {
    asset_name: assetName,
    filename: String(body.filename || assetName).trim(),
    content_type: String(body.content_type || "application/octet-stream").trim(),
    blob_path: blobPath,
    source_url: sourceUrl
  };
}

function normalizeImprovements(value = []) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.slice(0, 12).map((item) => {
    if (typeof item === "string") {
      return { title: item.slice(0, 120), body: "", impact: "Mejora incluida" };
    }
    return {
      title: String(item?.title || item?.name || "Mejora incluida").slice(0, 120),
      body: String(item?.body || item?.description || "").slice(0, 420),
      impact: String(item?.impact || item?.area || "Optimización").slice(0, 120)
    };
  });
}

export default async function handler(request, response) {
  if (!bearerAllowed(request)) {
    return response.status(401).json({ ok: false, error: "unauthorized" });
  }
  const releases = await readReleases();
  if (request.method === "GET") {
    return response.status(200).json(releases);
  }
  if (request.method !== "POST") {
    return response.status(405).json({ ok: false, error: "method_not_allowed" });
  }
  const body = request.body || {};
  const channel = String(body.channel || "stable").trim() || "stable";
  const version = String(body.version || "").trim();
  const asset = normalizeAsset(body);
  if (!version) {
    return response.status(400).json({ ok: false, error: "version_required" });
  }
  if (!asset) {
    return response.status(400).json({ ok: false, error: "asset_required" });
  }
  releases.channels ||= {};
  const current = releases.channels[channel] || { assets: {} };
  current.version = version;
  current.published_at = new Date().toISOString();
  current.improvements = normalizeImprovements(body.improvements);
  current.assets ||= {};
  current.assets[asset.asset_name] = asset;
  releases.channels[channel] = current;
  await writeReleases(releases);
  return response.status(200).json({ ok: true, channel, release: current });
}
