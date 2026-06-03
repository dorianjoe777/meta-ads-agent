# Admiro AI License API

Seller-only Vercel API for `admiroia.uboost.lat`.

Required environment variables:

- `BLOB_READ_WRITE_TOKEN`
- `LICENSE_PRIVATE_KEY_B64`
- `LICENSE_ADMIN_KEY`
- `LICENSE_UNLOCK_HOURS=168`
- `RELEASE_DOWNLOAD_SECRET`
- `RELEASE_TOKEN_MINUTES=15`
- `PORTAL_SESSION_MINUTES=20`

Optional environment variables:

- `RELEASE_SOURCE_ALLOWLIST=downloads.example.com,cdn.example.com`
- `GITHUB_RELEASE_TOKEN` for private GitHub release assets registered as `https://api.github.com/repos/OWNER/REPO/releases/assets/ASSET_ID`
- `RELEASE_PROXY_DOWNLOADS=true` to proxy every release source instead of redirecting public storage URLs. Private GitHub asset URLs are always proxied.

Routes:

- `GET /health`
- `GET /` download portal landing page
- `GET /access` buyer download portal landing page
- `GET /descargas` legacy download portal alias
- `POST /api/portal/session`
- `POST /api/portal/download`
- `POST /api/portal/cloud/digitalocean`
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

Download portal:

- The buyer enters purchase email + access key.
- The access key is the license key sent after purchase, shown to the buyer as a friendlier password-like phrase.
- The portal returns Mac, Windows and Linux buttons from the currently published stable release assets.
- The portal also returns install state: cloud dashboard ready, local install activated, onboarding opened, and onboarding completed. Local install state is updated through `/api/license/activate`.
- The portal can remember a buyer in the same browser using a signed, HttpOnly, Secure, SameSite=Lax cookie. The frontend never stores the license key in localStorage.
- Portal downloads do not register a device; device limits are enforced later during install/onboarding.
- Release URLs are still short-lived signed grants served through `/api/download/release`.

DigitalOcean guided install:

- The buyer enters purchase email + access key, then chooses `Instalar en la nube`.
- The portal asks for a DigitalOcean API token and an SSH public key.
- The API token is used only to create the SSH key, tag, firewall and Droplet. The portal does not store it.
- The generated Droplet uses cloud-init to download the private source release through a signed `/api/download/release` URL.
- The Droplet stores the buyer's DigitalOcean token locally so the dashboard can refresh strict firewall access later.
- The Droplet also runs a tiny secret access gate on port `7870`; the portal shows `Abrir mi dashboard`, which asks the Droplet to authorize the buyer's current IP and then redirects to the dashboard on port `7871`.
- The direct dashboard port remains restricted to the last authorized buyer IP. SSH remains key-only recovery, not the main buyer flow.
- Recommended scoped DigitalOcean token permissions: Droplets create/read, Firewalls create/read/update, SSH Keys create/read, Tags create/read.
