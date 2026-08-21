import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { handoffDigest } from "../lib/meta-oauth-store.js";

test("OAuth handoff digest is deterministic and does not expose its secret", () => {
  const secret = "s".repeat(64);
  const digest = handoffDigest(secret);
  assert.equal(digest, handoffDigest(secret));
  assert.match(digest, /^[a-f0-9]{64}$/);
  assert.equal(digest.includes(secret), false);
});

test("buyer OAuth requests business portfolio discovery with a user-token configuration", async () => {
  const source = await readFile(new URL("../lib/meta-oauth-handler.js", import.meta.url), "utf8");
  assert.match(source, /"business_management"/);
  assert.match(source, /me\/businesses\?fields=/);
  assert.match(source, /META_OAUTH_CONFIG_ID/);
  assert.match(source, /User access tokens/);
});
