import { chmod, writeFile } from "node:fs/promises";

const email = String(process.env.UPSTASH_ACCOUNT_EMAIL || "").trim().toLowerCase();
const apiKey = String(process.env.UPSTASH_MANAGEMENT_API_KEY || "").trim();
const outputPath = String(process.env.UPSTASH_ENV_OUTPUT || ".env.upstash.local");
const databaseName = String(process.env.UPSTASH_DATABASE_NAME || "admira-license-store").trim();
if (!email || !email.includes("@") || apiKey.length < 20) throw new Error("Upstash account email and management API key are required.");

const authorization = `Basic ${Buffer.from(`${email}:${apiKey}`).toString("base64")}`;
async function management(path, options = {}) {
  const response = await fetch(`https://api.upstash.com/v2${path}`, {
    ...options,
    headers: { Authorization: authorization, "Content-Type": "application/json", ...(options.headers || {}) }
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`Upstash management request failed (${response.status}).`);
  return payload;
}

const existing = await management("/redis/databases");
let database = (Array.isArray(existing) ? existing : []).find((item) => item.database_name === databaseName);
let created = false;
if (!database) {
  database = await management("/redis/database", {
    method: "POST",
    body: JSON.stringify({
      database_name: databaseName,
      platform: "aws",
      primary_region: "us-east-1",
      read_regions: [],
      plan: "free",
      eviction: false,
      tls: true
    })
  });
  created = true;
}

const details = await management(`/redis/database/${encodeURIComponent(database.database_id)}`);
const endpoint = String(details.endpoint || database.endpoint || "").replace(/^https?:\/\//, "").replace(/\/$/, "");
const restToken = String(details.rest_token || details.restToken || "");
if (!endpoint || !restToken) throw new Error("Upstash created the database but did not return its REST credentials.");
const restUrl = `https://${endpoint.endsWith(".upstash.io") ? endpoint : `${endpoint}.upstash.io`}`;
await writeFile(outputPath, `UPSTASH_REDIS_REST_URL=${restUrl}\nUPSTASH_REDIS_REST_TOKEN=${restToken}\n`, { encoding: "utf8", mode: 0o600 });
await chmod(outputPath, 0o600);
console.log(JSON.stringify({ created, database_id: details.database_id, database_name: details.database_name, type: details.type, state: details.state, credentials_file: outputPath }));
