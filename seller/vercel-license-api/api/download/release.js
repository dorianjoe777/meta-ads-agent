import { verifyReleaseGrant } from "../../lib/license.js";
import { get } from "@vercel/blob";

function hostnameAllowed(hostname) {
  const host = String(hostname || "").toLowerCase();
  if (!host || host === "localhost" || host.endsWith(".localhost")) return false;
  if (host === "127.0.0.1" || host === "::1") return false;
  if (/^\d+\.\d+\.\d+\.\d+$/.test(host)) {
    if (host.startsWith("10.") || host.startsWith("127.") || host.startsWith("192.168.")) return false;
    const second = Number(host.split(".")[1] || 0);
    if (host.startsWith("172.") && second >= 16 && second <= 31) return false;
  }
  const allowlist = String(process.env.RELEASE_SOURCE_ALLOWLIST || "")
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
  if (!allowlist.length) {
    return true;
  }
  return allowlist.some((allowed) => host === allowed || host.endsWith(`.${allowed}`));
}

function maxReleaseBytes() {
  return Number(process.env.RELEASE_MAX_BYTES || 300 * 1024 * 1024);
}

function isGitHubAssetUrl(source) {
  const host = String(source?.hostname || "").toLowerCase();
  const path = String(source?.pathname || "");
  return host === "api.github.com" && /^\/repos\/[^/]+\/[^/]+\/releases\/assets\/\d+$/i.test(path);
}

function githubAssetHeaders(source) {
  if (!isGitHubAssetUrl(source)) {
    return {};
  }
  const token = String(process.env.GITHUB_RELEASE_TOKEN || process.env.GITHUB_TOKEN || "").trim();
  if (!token) {
    return null;
  }
  return {
    "Accept": "application/octet-stream",
    "Authorization": `Bearer ${token}`,
    "User-Agent": "miro-ai-license-api",
    "X-GitHub-Api-Version": "2022-11-28"
  };
}

export default async function handler(request, response) {
  if (request.method !== "GET") {
    return response.status(405).json({ ok: false, error: "method_not_allowed" });
  }
  try {
    const grant = verifyReleaseGrant(request.query?.token);
    if (!grant) {
      return response.status(403).json({ ok: false, error: "invalid_or_expired" });
    }
    if (grant.blob_path) {
      const blob = await get(String(grant.blob_path), { access: "private" });
      if (!blob || blob.statusCode !== 200 || !blob.stream) {
        return response.status(404).json({ ok: false, error: "blob_not_found" });
      }
      const contentLength = Number(blob.size || blob.contentLength || 0);
      if (contentLength && contentLength > maxReleaseBytes()) {
        return response.status(413).json({ ok: false, error: "release_too_large" });
      }
      const arrayBuffer = await new Response(blob.stream).arrayBuffer();
      if (arrayBuffer.byteLength > maxReleaseBytes()) {
        return response.status(413).json({ ok: false, error: "release_too_large" });
      }
      response.setHeader("Content-Type", grant.content_type || blob.contentType || "application/octet-stream");
      response.setHeader("Content-Disposition", `attachment; filename="${String(grant.filename || grant.asset_name || "release.bin").replace(/"/g, "")}"`);
      response.setHeader("Content-Length", String(arrayBuffer.byteLength));
      response.setHeader("Cache-Control", "private, no-store");
      return response.status(200).send(Buffer.from(arrayBuffer));
    }
    const source = new URL(String(grant.source_url || ""));
    if (source.protocol !== "https:" || !hostnameAllowed(source.hostname)) {
      return response.status(400).json({ ok: false, error: "source_not_allowed" });
    }
    const githubHeaders = githubAssetHeaders(source);
    if (githubHeaders === null) {
      return response.status(500).json({ ok: false, error: "github_token_missing" });
    }
    const forceProxy = isGitHubAssetUrl(source) || String(process.env.RELEASE_PROXY_DOWNLOADS || "").toLowerCase() === "true";
    if (!forceProxy) {
      response.setHeader("Cache-Control", "private, no-store");
      return response.redirect(302, source.toString());
    }
    const upstream = await fetch(source, { redirect: "follow", headers: githubHeaders });
    if (!upstream.ok || !upstream.body) {
      return response.status(502).json({ ok: false, error: "upstream_failed" });
    }
    const contentLength = upstream.headers.get("content-length");
    if (contentLength && Number(contentLength) > maxReleaseBytes()) {
      return response.status(413).json({ ok: false, error: "release_too_large" });
    }
    response.setHeader("Content-Type", grant.content_type || upstream.headers.get("content-type") || "application/octet-stream");
    response.setHeader("Content-Disposition", `attachment; filename="${String(grant.filename || grant.asset_name || "release.zip").replace(/"/g, "")}"`);
    if (contentLength) {
      response.setHeader("Content-Length", contentLength);
    }
    response.setHeader("Cache-Control", "private, no-store");
    const arrayBuffer = await upstream.arrayBuffer();
    if (arrayBuffer.byteLength > maxReleaseBytes()) {
      return response.status(413).json({ ok: false, error: "release_too_large" });
    }
    return response.status(200).send(Buffer.from(arrayBuffer));
  } catch {
    return response.status(500).json({ ok: false, error: "download_failed" });
  }
}
