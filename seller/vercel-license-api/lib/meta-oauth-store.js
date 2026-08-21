import { createHash } from "node:crypto";
import { del, get, put } from "@vercel/blob";

// OAuth exchanges are deliberately short lived.  The browser never receives a
// Meta access token from this service; the local installation polls using a
// one-time handoff secret and receives it over HTTPS.
const PREFIX = "meta-oauth/v1";

function safeId(value = "") {
  const id = String(value || "").trim();
  if (!/^[A-Za-z0-9_-]{32,160}$/.test(id)) throw new Error("invalid_oauth_request");
  return id;
}

function pathFor(requestId) {
  return `${PREFIX}/${safeId(requestId)}.json`;
}

export function handoffDigest(secret = "") {
  return createHash("sha256").update(String(secret || "")).digest("hex");
}

export async function readMetaOAuthRequest(requestId) {
  const result = await get(pathFor(requestId), { access: "private" });
  if (!result || result.statusCode !== 200) return null;
  try {
    return JSON.parse(await new Response(result.stream).text());
  } catch {
    return null;
  }
}

export async function writeMetaOAuthRequest(requestId, value) {
  await put(pathFor(requestId), JSON.stringify(value), {
    access: "private",
    contentType: "application/json",
    allowOverwrite: true,
    cacheControlMaxAge: 60,
  });
}

export async function deleteMetaOAuthRequest(requestId) {
  await del(pathFor(requestId));
}
