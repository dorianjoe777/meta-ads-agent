# Miro AI License API

Seller-only Vercel API for `licencias-miro-ai.uboost.lat`.

Required environment variables:

- `BLOB_READ_WRITE_TOKEN`
- `LICENSE_PRIVATE_KEY_B64`
- `LICENSE_ADMIN_KEY`
- `LICENSE_UNLOCK_HOURS=168`
- `RELEASE_DOWNLOAD_SECRET`
- `RELEASE_TOKEN_MINUTES=15`

Optional environment variables:

- `RELEASE_SOURCE_ALLOWLIST=downloads.example.com,cdn.example.com`
- `GITHUB_RELEASE_TOKEN` for private GitHub release assets registered as `https://api.github.com/repos/OWNER/REPO/releases/assets/ASSET_ID`
- `RELEASE_PROXY_DOWNLOADS=true` to proxy every release source instead of redirecting public storage URLs. Private GitHub asset URLs are always proxied.

Routes:

- `GET /health`
- `POST /api/license/activate`
- `POST /api/license/release`
- `GET /api/download/release?token=...`
- `GET /api/admin/licenses` with `Authorization: Bearer ...`
- `POST /api/admin/licenses` with `Authorization: Bearer ...`
- `GET /api/admin/releases` with `Authorization: Bearer ...`
- `POST /api/admin/releases` with `Authorization: Bearer ...`

Device transfer:

- Individual licenses have one active device by default.
- `POST /api/license/activate` and `POST /api/license/release` accept `transfer_device: true`.
- When the license has `max_devices=1`, transfer clears prior device registrations and registers the new `device_id`.
- Existing offline unlocks can remain valid until their signed unlock/grace period expires.
