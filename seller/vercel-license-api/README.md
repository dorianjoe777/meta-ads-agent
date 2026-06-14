# Admira IA License API

Seller-only Vercel API for `admiroia.uboost.lat`.

Required environment variables:

- `BLOB_READ_WRITE_TOKEN`
- `LICENSE_PRIVATE_KEY_B64`
- `LICENSE_ADMIN_KEY`
- `LICENSE_UNLOCK_HOURS=168`
- `RELEASE_DOWNLOAD_SECRET`
- `RELEASE_TOKEN_MINUTES=15`
- `PORTAL_SESSION_MINUTES=20`
- `HOTMART_HOTTOK` must match the Hotmart account token sent in the `X-HOTMART-HOTTOK` webhook header.

Optional environment variables:

- `RELEASE_SOURCE_ALLOWLIST=downloads.example.com,cdn.example.com`
- `BUYER_ACCESS_URL=https://admiroia.uboost.lat/access` is the buyer portal link included in purchase emails.
- `BUYER_EMAIL_PROVIDER=resend` sends buyer emails through Resend. This is the default.
- `RESEND_API_KEY` is required when buyer email delivery is requested.
- `BUYER_EMAIL_FROM="Admira IA <licenses@admiroia.uboost.lat>"` must use a Resend-verified domain or sender.
- `BUYER_EMAIL_REPLY_TO=support@admiroia.uboost.lat` is optional.
- `BUYER_EMAIL_PRODUCT_NAME="Admira IA"` is optional email copy branding.
- `BUYER_EMAIL_AUTO_SEND=true` sends the buyer access email automatically for every newly created license. Leave unset/false if the checkout webhook will pass `send_buyer_email: true` explicitly.
- `HOTMART_SEND_BUYER_EMAIL=true` sends the license/access email when Hotmart confirms an approved purchase. Set to `false` only for dry runs.
- `BUYER_EMAIL_PROVIDER=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURE`, `SMTP_USER`, and `SMTP_PASS` remain supported as an optional Spacemail SMTP fallback.
- `HOTMART_PRODUCT_ID` or `HOTMART_PRODUCT_IDS=123,456` restricts processing to specific Hotmart product IDs.
- `HOTMART_PRODUCT_UCODE` or `HOTMART_PRODUCT_UCODES=...` restricts processing to specific Hotmart product UCODEs.
- `HOTMART_DEFAULT_PLAN=individual` controls the plan created from Hotmart purchases unless an agency offer is matched.
- `HOTMART_AGENCY_OFFER_CODES=AGENCY2026` maps specific Hotmart offer codes to the agency plan.
- `GITHUB_RELEASE_TOKEN` for private GitHub release assets registered as `https://api.github.com/repos/OWNER/REPO/releases/assets/ASSET_ID`
- `RELEASE_PROXY_DOWNLOADS=true` to proxy every release source instead of redirecting public storage URLs. Private GitHub asset URLs are always proxied.
- `CLOUD_DASHBOARD_BASE_DOMAIN=cloud.admiroia.uboost.lat` to create one HTTPS subdomain per DigitalOcean install.
- `CLOUD_BOOTSTRAP_BASE_URL=https://miro-ai-license-api.vercel.app` lets fresh Droplets download the release and report progress through Vercel's stable project URL instead of depending on custom-domain DNS during first boot.
- `DNS_PROVIDER=vercel` is recommended when the domain is managed in Vercel DNS.
- `VERCEL_DNS_TOKEN` and `VERCEL_DNS_DOMAIN=uboost.lat` let the portal create those DNS records automatically while Vercel keeps hosting the access portal.
- `VERCEL_DNS_TEAM_ID` or `VERCEL_DNS_TEAM_SLUG` is optional when the domain belongs to a Vercel team.
- `DNS_PROVIDER=cloudflare`, `CLOUDFLARE_ZONE_ID`, `CLOUDFLARE_API_TOKEN`, and `CLOUDFLARE_DNS_PROXIED=false` remain available if the DNS zone later moves to Cloudflare.

Routes:

- `GET /health`
- `GET /` download portal landing page
- `GET /access` buyer download portal landing page
- `GET /descargas` legacy download portal alias
- `POST /api/portal/session`
- `POST /api/portal/download`
- `POST /api/portal/cloud/digitalocean`
- `POST /api/webhooks/hotmart`
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

Buyer purchase email:

- Create a license and send the buyer email in one protected admin call:

```bash
curl -X POST "https://admiroia.uboost.lat/api/admin/licenses" \
  -H "Authorization: Bearer $LICENSE_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "buyer_email": "buyer@example.com",
    "buyer_name": "Buyer Name",
    "plan": "individual",
    "send_buyer_email": true
  }'
```

- Resend an existing buyer access email with the same license key:

```bash
curl -X POST "https://admiroia.uboost.lat/api/admin/licenses" \
  -H "Authorization: Bearer $LICENSE_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "buyer_email": "buyer@example.com",
    "license_key": "MAO-...",
    "action": "send_email"
  }'
```

- The email includes the purchase email, license/access key, plan, and `https://admiroia.uboost.lat/access`.
- If email delivery fails, the API returns `502 buyer_email_send_failed` and still includes the created license in the response so the buyer can be recovered manually.
- Resend is the recommended production path for this project because delivery uses HTTPS from Vercel and gives clearer delivery logs.
- If using the SMTP fallback on Vercel, use authenticated submission on port `465` or `587`, never port `25`, and the function waits for the send to finish before responding.

Hotmart webhook:

- Paste this URL into Hotmart's `URL para envio de dados` field:

```text
https://admiroia.uboost.lat/api/webhooks/hotmart
```

- Configure Hotmart to send purchase events, especially `PURCHASE_APPROVED`.
- The endpoint validates `X-HOTMART-HOTTOK` against `HOTMART_HOTTOK`.
- On `PURCHASE_APPROVED` / `APPROVED`, it creates or reuses one license for the Hotmart transaction and sends the buyer access email.
- Hotmart retries are idempotent by `purchase.transaction`, so the same sale will not create duplicate licenses.
- On refunded, chargeback, canceled/cancelled, or blocked notifications, a matching license is marked `revoked`.

Download portal:

- The buyer enters purchase email + access key.
- The access key is the license key sent after purchase, shown to the buyer as a friendlier password-like phrase.
- The portal returns Mac, Windows and Linux buttons from the currently published stable release assets.
- The main local release path uses private Vercel Blob assets, not public GitHub links. Publish the Docker-first installers after building them:

```bash
./scripts/build-mac-dmg.sh
./scripts/build-windows-exe.sh
./scripts/build-linux-bundle.sh
./scripts/package-release.sh

cd seller/vercel-license-api
npm run publish:release-assets -- v1.0.11
```

- The current buyer-facing local assets are `MetaAdsAgent-vX.Y.Z-mac.dmg`, `MetaAdsAgent-vX.Y.Z-windows.exe`, and `MetaAdsAgent-vX.Y.Z-linux.tar.gz`. The source ZIP remains available for cloud installs and support, but it is not the normal Mac/Windows download button.
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
- If `CLOUD_DASHBOARD_BASE_DOMAIN` and DNS provider credentials are configured, the portal creates a per-install subdomain and the Droplet installs Caddy with a free Let's Encrypt certificate. The access gate then redirects to the HTTPS dashboard.
- The direct dashboard port remains restricted to the last authorized buyer IP. SSH remains key-only recovery, not the main buyer flow.
- Recommended scoped DigitalOcean token permissions: Droplets create/read, Firewalls create/read/update, SSH Keys create/read, Tags create/read.
