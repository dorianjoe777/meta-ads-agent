import { storeBackendStatus } from "../lib/store.js";

export default function handler(_request, response) {
  response.status(200).json({ ok: true, service: "admira-ia-license-api", store: storeBackendStatus() });
}
