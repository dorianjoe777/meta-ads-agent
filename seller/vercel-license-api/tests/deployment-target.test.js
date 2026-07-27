import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const target = JSON.parse(
  fs.readFileSync(path.join(root, "deployment-target.json"), "utf8")
);
const deployScript = fs.readFileSync(
  path.join(root, "scripts", "deploy-production-safe.sh"),
  "utf8"
);

test("production deployment target is locked to the buyer domain project", () => {
  assert.deepEqual(target, {
    service: "admira-ia-license-api",
    project_name: "miro-ai-license-api",
    project_id: "prj_7EHTqtYTj4V1wxUeFvU5h4gzKqLX",
    org_id: "team_1dW3qJzfquT0ONCFYEw2GRE1",
    scope: "dorianx",
    production_domain: "admiraia.uboost.lat",
  });
});

test("safe deploy pins, verifies, and health-checks the production target", () => {
  assert.match(deployScript, /deployment-target\.json/);
  assert.match(deployScript, /vercel deploy --prod --yes --scope/);
  assert.match(deployScript, /vercel project inspect/);
  assert.match(deployScript, /vercel inspect "https:\/\/\$EXPECTED_DOMAIN"/);
  assert.match(deployScript, /api\/health/);
  assert.doesNotMatch(deployScript, /\bvercel link\b/);
});
