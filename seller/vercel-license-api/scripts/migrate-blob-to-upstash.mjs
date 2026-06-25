import * as blob from "../lib/blob-store.js";
import * as upstash from "../lib/upstash-store.js";
import { migrateLicenseStore } from "../lib/migrate-store.js";

if (!process.env.BLOB_READ_WRITE_TOKEN) throw new Error("BLOB_READ_WRITE_TOKEN is required for migration.");
if (!process.env.UPSTASH_REDIS_REST_URL || !process.env.UPSTASH_REDIS_REST_TOKEN) {
  throw new Error("UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN are required for migration.");
}

const result = await migrateLicenseStore(blob, upstash);
console.log(JSON.stringify(result));
