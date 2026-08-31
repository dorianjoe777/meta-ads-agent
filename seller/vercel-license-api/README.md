# Admira IA License API

Seller-only Vercel API for `admiraia.uboost.lat`.

## Safe production deployment

The production target is locked in `deployment-target.json`. Do not run a bare
`vercel deploy`, `vercel --prod`, or `vercel link`, and do not deploy this API
from the repository root. A clean checkout does not contain the ignored
`.vercel/project.json`, so the safe script recreates it from the reviewed
manifest, verifies the exact Vercel project and organization, runs tests, and
checks the public domain after deployment.

Read-only target and health verification:

```bash
./seller/vercel-license-api/scripts/deploy-production-safe.sh --check
```

Production deployment:

```bash
./seller/vercel-license-api/scripts/deploy-production-safe.sh
```

Required environment variables:

- `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` store license, registry, and device state in Upstash Redis.
- `LICENSE_STORE_BACKEND=upstash` selects Upstash in production. `auto` uses Upstash when configured and otherwise falls back to Blob; `dual` reads from Upstash first and Blob second while writing to both for a temporary migration window.
- `LICENSE_PRIVATE_KEY_B64`
- `LICENSE_ADMIN_KEY`
- `LICENSE_UNLOCK_HOURS=168`
- `RELEASE_DOWNLOAD_SECRET`
- `RELEASE_TOKEN_MINUTES=15`
- `PORTAL_SESSION_MINUTES=20`
- `HOTMART_HOTTOK` must match the Hotmart account token sent in the `X-HOTMART-HOTTOK` webhook header.

Optional environment variables:

- `BLOB_READ_WRITE_TOKEN` supports legacy Vercel Blob license records and release assets. It is not required when license state is in Upstash and installers are served from GitHub Releases.
- `RELEASE_SOURCE_ALLOWLIST=downloads.example.com,cdn.example.com`
- `BUYER_ACCESS_URL=https://admiraia.uboost.lat/access` is the buyer portal link included in purchase emails.
- `BUYER_EMAIL_PROVIDER=resend` sends buyer emails through Resend. This is the default.
- `RESEND_API_KEY` is required when buyer email delivery is requested.
- `BUYER_EMAIL_FROM="Admira IA <licenses@admiraia.uboost.lat>"` must use a Resend-verified domain or sender.
- `BUYER_EMAIL_REPLY_TO=support@admiraia.uboost.lat` is optional.
- `BUYER_EMAIL_PRODUCT_NAME="Admira IA"` is optional email copy branding.
- `BUYER_EMAIL_AUTO_SEND=true` sends the buyer access email automatically for every newly created license. Leave unset/false if the checkout webhook will pass `send_buyer_email: true` explicitly.
- `HOTMART_SEND_BUYER_EMAIL=false` is an emergency pause switch for Hotmart-triggered buyer emails. By default, the webhook sends the transactional license/access email after the Upstash license write succeeds.
- `BUYER_EMAIL_PROVIDER=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURE`, `SMTP_USER`, and `SMTP_PASS` remain supported as an optional Spacemail SMTP fallback.
- `HOTMART_PRODUCT_ID` or `HOTMART_PRODUCT_IDS=123,456` restricts processing to specific Hotmart product IDs.
- `HOTMART_PRODUCT_UCODE` or `HOTMART_PRODUCT_UCODES=...` restricts processing to specific Hotmart product UCODEs.
- `HOTMART_DEFAULT_PLAN=individual` controls the plan created from Hotmart purchases unless an agency offer is matched.
- `HOTMART_AGENCY_OFFER_CODES=AGENCY2026` maps specific Hotmart offer codes to the agency plan.
- `GITHUB_RELEASE_TOKEN` for private GitHub release assets registered as `https://api.github.com/repos/OWNER/REPO/releases/assets/ASSET_ID`
- `RELEASE_PROXY_DOWNLOADS=true` to proxy every release source instead of redirecting public storage URLs. Private GitHub asset URLs are always proxied.
- `CLOUD_DASHBOARD_BASE_DOMAIN=cloud.admiraia.uboost.lat` to create one HTTPS subdomain per DigitalOcean install.
- `CLOUD_BOOTSTRAP_BASE_URL=https://admiraia.uboost.lat` lets fresh Droplets download the release and report progress through the stable Admira IA portal URL.
- `DNS_PROVIDER=vercel` is recommended when the domain is managed in Vercel DNS.
- `VERCEL_DNS_TOKEN` and `VERCEL_DNS_DOMAIN=uboost.lat` let the portal create those DNS records automatically while Vercel keeps hosting the access portal.
- `VERCEL_DNS_TEAM_ID` or `VERCEL_DNS_TEAM_SLUG` is optional when the domain belongs to a Vercel team.
- `DNS_PROVIDER=cloudflare`, `CLOUDFLARE_ZONE_ID`, `CLOUDFLARE_API_TOKEN`, and `CLOUDFLARE_DNS_PROXIED=false` remain available if the DNS zone later moves to Cloudflare.

License store migration:

```bash
# Management credentials are used only to provision the database locally.
UPSTASH_ACCOUNT_EMAIL=you@example.com \
UPSTASH_MANAGEMENT_API_KEY=... \
npm run provision:upstash

# Load the generated .env.upstash.local and the existing Blob token, then copy
# and verify all licenses, device registrations, registries, and release state.
npm run migrate:upstash
```

- `.env.upstash.local` contains only database-scoped runtime credentials and must remain uncommitted.
- The migration writes the license registry last and verifies the copied counts and every license before succeeding.
- Do not delete the old Blob license records until Upstash has run successfully in production through a rollback window.
- If Vercel has suspended Blob before migration can read it, seed verified license records from a trusted local/admin source and register the current GitHub Release in Upstash; never cut over to an empty registry.

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
- `POST /api/license/release` with `action: cloud_install` (one-time registration from the internal Mac cloud installer)
- `GET /api/download/release?token=...`
- `GET /api/admin/licenses` with `Authorization: Bearer ...`
- `POST /api/admin/licenses` with `Authorization: Bearer ...`
- `/admin/licenses` opens the protected browser table for reviewing licenses and changing the associated buyer email.

Hosted tenant bridge (server-to-server only):

- `POST /api/admin/licenses` with `Authorization: Bearer $LICENSE_HOSTED_BRIDGE_KEY` and `{ "action": "create_hosted_tenant_license", "external_customer_id": "tenant_01", "display_name": "Client", "plan": "individual" }` creates one active Upstash-backed license for a Contabo tenant.
- `external_customer_id` is the idempotency key; repeating the request returns the same record with `created: false` instead of creating a second license. Its stable license code is derived with the private bridge key, never from a visible tenant identifier.
- This action intentionally stores `buyer_email: ""`, marks `buyer_email_deferred: true`, leaves delivery as `deferred`, and never sends an email. Attach the real buyer email later through the protected `update_email` action before normal `/api/license/activate` use.
- It returns the generated `license_key` only to the authenticated bridge response. Configure `LICENSE_HOSTED_BRIDGE_KEY`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`, and do not use the bridge key in browser code. The endpoint rejects this action when Upstash is not configured.
- `GET /api/admin/releases` with `Authorization: Bearer ...`
- `POST /api/admin/releases` with `Authorization: Bearer ...`

Device transfer:

- Individual licenses have one active device by default.
- A brand-new installation reserves its device provisionally until onboarding is completed.
- If an incomplete install is retried with a different container identity, the new attempt replaces only the provisional reservation instead of consuming another device or requiring support.
- `install_event: "onboarding_completed"` confirms the device. Confirmed and legacy device registrations keep the normal device-limit protection.
- `POST /api/license/activate` and `POST /api/license/release` accept `transfer_device: true`.
- When the license has `max_devices=1`, transfer clears prior device registrations and registers the new `device_id`.
- `LICENSE_UNLOCK_HOURS` is only the refresh interval for the signed verification proof; it is not the commercial license term.
- A previously verified lifetime license remains usable during network/server outages. The next successful online verification applies authoritative revocation, refund, transfer, or device-limit state.

Buyer purchase email:

- Create a license and send the buyer email in one protected admin call:

```bash
curl -X POST "https://admiraia.uboost.lat/api/admin/licenses" \
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
curl -X POST "https://admiraia.uboost.lat/api/admin/licenses" \
  -H "Authorization: Bearer $LICENSE_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "buyer_email": "buyer@example.com",
    "license_key": "MAO-...",
    "action": "send_email"
  }'
```

- The email includes the purchase email, license/access key, plan, and `https://admiraia.uboost.lat/access`.
- If email delivery fails, the API returns `502 buyer_email_send_failed` and still includes the created license in the response so the buyer can be recovered manually.
- Resend is the recommended production path for this project because delivery uses HTTPS from Vercel and gives clearer delivery logs.
- If using the SMTP fallback on Vercel, use authenticated submission on port `465` or `587`, never port `25`, and the function waits for the send to finish before responding.

License email transfer:

- Open `https://admiraia.uboost.lat/admin/licenses`, enter `LICENSE_ADMIN_KEY`, and choose **Guardar** beside a license.
- The protected action is `POST /api/admin/licenses` with `{ "action": "update_email", "license_key": "MAO-...", "buyer_email": "new-owner@example.com" }`.
- The API changes only the owner email, records a bounded audit history, and keeps the old email as a technical alias. Device registrations, the license key, and `cloud_installation` are preserved, so an already-installed client can continue updating while the new owner uses the new email.
- The alias is intentional for continuity. Remove it later only as a separate, explicit access-revocation operation.

Cloud clean handoff:

- The same protected table can trigger `POST /api/admin/licenses` with `{ "action": "reset_cloud_installation", "license_key": "MAO-...", "confirm_license_key": "MAO-..." }` for a completed DigitalOcean install.
- The protected table can also switch a completed cloud installation with `{ "action": "set_cloud_network_mode", "license_key": "MAO-...", "mode": "testing" | "strict", "confirm_license_key": "MAO-..." }`. Testing mode publishes only the dashboard/HTTPS ports so a client can complete Meta onboarding; the dashboard password, SSH rules and private admin/reset gate remain protected. Switching back to `strict` restores the original authorized IPv4 rule.
- The request is accepted only after the admin key and exact license confirmation are valid, then updates the saved DigitalOcean firewall token directly. It keeps the Droplet and preserves provider/API credentials, the ChatGPT/Codex connection used for images, and Telegram.
- The remote reset clears Facebook/Meta tokens, the dashboard password, business/onboarding data, generated media, logs, ad configuration, Hermes memory/history/sessions, and mutable personal skills. It recreates the provider-independent base files while retaining only the license identity, provider/API credentials, and ChatGPT/Codex authentication artifacts needed for images. The next person sees the initial password step and must connect Facebook again.
- Older cloud installations without the current access gate return `cloud_clean_reset_unavailable`; use the full Droplet delete/reinstall flow for those instances.
- New installations created by the internal Mac `.command` cloud installer register the same protected gate automatically, so they also appear in the table and can be handed to a client without recreating the Droplet.

Owner commercial purchase email test pipeline:

- Protected by the same `Authorization: Bearer $LICENSE_ADMIN_KEY` admin auth.
- Only the configured owner email is allowed by default: `dorianjoe.777@gmail.com`.
- Creates or reuses the owner license `MAO-DORI-ANJO-E777-GMAI-LADM-INTE-36DECA`.
- Stores `role: "owner"` and unlimited-style commercial entitlements in Upstash.
- Sends the Spanish purchase/access email every time the action is called, so repeated email tests are allowed without creating duplicate licenses.

```bash
curl -X POST "https://admiraia.uboost.lat/api/admin/licenses" \
  -H "Authorization: Bearer $LICENSE_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "action": "send_owner_test_purchase_email",
    "buyer_email": "dorianjoe.777@gmail.com",
    "buyer_name": "Dorian",
    "role": "owner"
  }'
```

Hotmart webhook:

- Paste this URL into Hotmart's `URL para envio de dados` field:

```text
https://admiraia.uboost.lat/api/webhooks/hotmart
```

- Configure Hotmart to send purchase events, especially `PURCHASE_APPROVED`.
- The endpoint validates `X-HOTMART-HOTTOK` against `HOTMART_HOTTOK`.
- On `PURCHASE_APPROVED` / `APPROVED`, it creates or reuses an active license directly in Upstash using the purchaser email and Hotmart transaction, then sends the transactional license/access email through the configured buyer email provider.
- Hotmart retries are idempotent by `purchase.transaction`, so the same sale will not create duplicate licenses.
- On refunded, chargeback, canceled/cancelled, or blocked notifications, a matching license is marked `revoked`.
- Concurrent purchases are indexed independently in Redis, so a stale registry write cannot hide another buyer's license.
- If `HOTMART_SEND_BUYER_EMAIL=false` is set, the webhook still creates the Upstash license but leaves buyer email delivery pending. A protected server-side email worker can list pending deliveries with `GET /api/admin/licenses?delivery=pending` and `Authorization: Bearer $LICENSE_ADMIN_KEY`; each result includes the buyer email, license key, plan, Hotmart transaction, and delivery status.
- After an external workflow sends a pending license email, use the protected admin API to send/record delivery rather than exposing `LICENSE_ADMIN_KEY` in a browser or client-side automation.

```bash
curl -X POST "https://admiraia.uboost.lat/api/admin/licenses" \
  -H "Authorization: Bearer $LICENSE_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "buyer_email": "buyer@example.com",
    "license_key": "MAO-...",
    "action": "mark_email_sent",
    "provider": "your-email-workflow",
    "delivery_id": "optional-provider-id"
  }'
```

- Configure `HOTMART_PRODUCT_ID(S)` or `HOTMART_PRODUCT_UCODE(S)` before using the same Hotmart account for unrelated products, so only Admira purchases issue licenses.
- Temporary Upstash failures return `503 license_store_unavailable` with `retryable: true`, allowing Hotmart to retry without losing the purchase.

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
# Facebook OAuth for buyer onboarding

New Admira installations connect Facebook from a button delivered to the
buyer's already-connected Telegram chat. They do **not** paste a Meta token or
create a System User. Before enabling this release in production, configure
the following Vercel Production environment variables (never commit values):

```text
META_OAUTH_APP_ID=<your Live/test Meta app ID>
META_OAUTH_APP_SECRET=<your Meta app secret>
META_OAUTH_REDIRECT_URI=https://admiraia.uboost.lat/api/meta-oauth
# Optional: Facebook Login for Business configuration for User access tokens
META_OAUTH_CONFIG_ID=<your user-token configuration ID>
PORTAL_SECRET_VAULT_KEY=<existing strong vault key>
```

In the Meta app, add this exact Valid OAuth Redirect URI:

```text
https://admiraia.uboost.lat/api/meta-oauth?flow=callback
```

For pilot/tester users, invite the buyer as an app role before they open the
link. The broker keeps only an encrypted, one-time OAuth handoff for 15
minutes. It deletes the handoff after the local installation retrieves it.
Do not print tokens, callback codes, or secrets in logs, tickets, or chat.

The OAuth request includes `business_management` in addition to Ads and Page
permissions. This lets Admira discover ad accounts and Pages in business
portfolios where the buyer is an administrator, not only the buyer's personal
portfolio. A Page remains selectable only when Meta also returns its Page
publishing access token; discovery never fabricates access to an asset.
