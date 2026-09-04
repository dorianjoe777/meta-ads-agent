# Admira hosted runtime foundation

This directory is the initial control-plane foundation for hosted Admira IA.
It deliberately preserves the proven r90 product boundary: one immutable image
is shared by the host, while every buyer receives a separate process,
environment and persistent filesystem.

## Current product scope

This deployment is the hosted Telegram experience only. Buyers interact with
one central bot in a private DM; the control plane resolves that Telegram
identity to one private tenant runtime. There is no buyer dashboard, public
API, CRM/booking/ecommerce integration layer, webhook product, customer CLI or
official MCP service in this phase. Those possible SaaS surfaces are explicitly
outside this job.

Operator-only tooling for trial capacity, licensing and provider-secret rotation
is part of the control-plane work; it is not a buyer SaaS dashboard. The
recovery core is now prepared: the poller can route `/recuperar email licencia`
and `/codigo request_id otp`, and the recovery database/outbox and SMTP worker
are implemented. It remains deliberately dormant: `ADMIRA_TELEGRAM_RECOVERY_READY=false`
and the `recovery-email` Compose profile is opt-in, so this is not a live
recovery service until the provider, domain, secrets, second Telegram identity
and canary gates are complete. Its scope and remaining work are documented in
[`TRIAL_LICENSING_DESIGN.md`](./TRIAL_LICENSING_DESIGN.md).

The intended experience is nevertheless the complete Admira/Hermes experience:
each buyer keeps their own model connection, Meta connection, memory, sessions,
files, brand state and scheduled work as though they had a dedicated server.
Group chats are rejected because one private Telegram identity controls one
private workspace.

## Isolation boundary

Each tenant owns an exclusive directory below `/srv/admira/tenants/<tenant>`:

- `runtime/` for `HERMES_HOME` and `CODEX_HOME`
- `data/` for business memory, OAuth state and product state
- `output/` for generated and uploaded media materializations
- `brand_guides/` for the buyer's approved brand assets
- `logs/` for that runtime only

The host also owns that tenant's private `compose.yaml` and, only after a
complete reset, a 0600 idempotency receipt outside every container mount.

New tenants select Gemini 3.5 Flash Lite as the initial text-brain configuration,
with live Meta actions disabled. For a dashboard-created account, the host
provisioner assigns one registered, private, host-funded Gemini-pool entry when
the five-day trial is created. On licensing, the customer's Gemini credential
replaces only that tenant's assignment; the tenant directory and Telegram
binding remain the same. Admira-sponsored central image access follows the same
five-day clock: it starts at account creation for dashboard-created accounts
and at the first Telegram claim only for the legacy claim-first flow. Licensing
never restarts that clock. A
private operator may extend its exact end date for one customer through the
internal dashboard; the change is durable, audited, idempotent and cannot
shorten an existing benefit. `/conectar_chatgpt` remains available from day one
and stores the customer's personal ChatGPT/Codex session only inside that
tenant. Connecting it does not cancel sponsored images. The customer may use
an account-advertised Codex model as the primary through `/model`; when Gemini
is primary, the tenant may use `gpt-5.6-luna` as its single personal Codex
fallback. This is independent from the customer's Gemini text credential.
Provider choices live in the tenant's private `runtime/.env` and are not
overwritten by restart or scale-to-zero.

The shared r90 image is read-only product code. A tenant container never mounts
the Docker socket, another tenant directory or a host-wide credential file.
Suspending a tenant removes only that tenant's ephemeral container and network;
it never passes `--volumes` and never removes the bind-mounted directories.
Hermes session and memory continuity therefore survive scale-to-zero, while a
host reboot cannot wake every registered tenant at once.

`tenantctl.py` is the only supported host-side lifecycle entry point for this
foundation. It pins `admira-ia:r90`, refuses builds and pulls during wake-up,
publishes no tenant port, and gives every tenant a unique Compose project.

```bash
./tenantctl.py plan client-001
./tenantctl.py provision client-001
./tenantctl.py start client-001
./tenantctl.py suspend client-001
```

`tenant_turn.py` is the narrow bridge used by the central Telegram runtime
worker. It accepts one JSON request on stdin and runs `hermes_bridge.chat` in
the already-running tenant container. It derives a stable session from the
Telegram chat ID, accepts only broker-materialized attachments below the
tenant's own `/app/output/telegram_uploads/` directory, extracts bounded video
preview frames, routes PDFs through the existing document/catalog behavior and
never returns raw provider errors to Telegram. `/restart`, `/reset`,
`/conectar_chatgpt` and the two-step `/resetear_completamente` flow are handled
deterministically before model inference:

```bash
printf '%s\n' '{"message":"Hola","chat_id":"123","user_id":"456","language":"es","update_id":42}' \
  | ./tenant_turn.py client-001
```

The shared Telegram bot token is intentionally absent from every tenant
runtime.

## Control plane

For the complete current-state inventory, activation gate, update/rollback
procedure and incident runbook, see [`OPERATIONS.md`](./OPERATIONS.md).

`compose.yaml` starts PostgreSQL and Redis on an internal-only Docker network.
It publishes no host ports. PostgreSQL is the canonical source for tenant,
trial, entitlement, Telegram binding, inbox, outbox, runtime lease and
scheduled-work state. Redis is transient coordination only; it is not the
durable source of truth.

Trial/entitlement fields are reserved control-plane data, not a dashboard or
billing product in this phase. Runtime dispatch currently fails closed on the
tenant's active/inactive status.

Prepare secrets once:

```bash
# Run as admiraops (the service UID), never as root/sudo: file-backed 0600
# secrets must remain readable by the UID 1001 control-plane workers.
./bootstrap-control-plane.sh
./apply-control-plane.sh
sudo ./install-runtime-broker.sh
```

The generated `secrets/` directory and `.env` are git-ignored and must be
included in private recovery backups, never committed. Encrypt any off-host
backup export; local deployment backups must not be described as encrypted
unless that has actually been verified.
Any bot token pasted into a ticket, chat or transcript is canary-only and must
be revoked and replaced out of band before commercial traffic.
Gemini trial keys are never pre-seeded as a host-wide secret or committed into a
tenant template. The internal dashboard or `gemini_pool_admin.py register` can
register an operator-pool credential; the host-only provisioner assigns one
active registered entry to a new trial after its project quota and auth-key type
have been verified.
The central image route remains explicitly disabled until the broker has passed its canary:
`ADMIRA_CENTRAL_IMAGE_READY=false`.

Migration `010_operator_gemini_pool.sql` reserves the durable operator pool for
trial onboarding. It tracks Gemini projects (the quota boundary), auth-key
credentials, one active assignment per tenant and auditable release events.
Several keys in one project do not create independent quota. Only auth keys
may be assigned to customer-ready trials; standard/legacy keys are not a
commercial fallback. The pool CLI, when present, must use the hosted
assignment functions and never print or store key material in PostgreSQL.
Migration 010 and its disposable validator are present in this worktree, but
the pool is not claimed deployed or live until real projects and keys have
been created, restricted and validated out of band.

### Internal credential-preparation dashboard

The opt-in `operator-dashboard` profile serves a Spanish operator panel on
`127.0.0.1:8791` only. Follow [OPERATOR_DASHBOARD.md](OPERATOR_DASHBOARD.md) for
the exact private-directory, migration, first-password and SSH-tunnel sequence.
On the configured Mac, [open-operator-dashboard.command](open-operator-dashboard.command)
opens that tunnel using the existing `admira-contabo` alias.
For the verified VPS snapshot, actual customer inventory and the difference
between configured and pending work, see [DASHBOARD_STATUS.md](DASHBOARD_STATUS.md).

The live panel registers Gemini keys without returning them, runs the official
device-login flow separately for `primary` and `secondary`, and manages actual
customer accounts. Migration 013 adds the host-only lifecycle route: create a
five-day trial, issue or reissue its Telegram claim, set a later exact expiry,
expire it manually, or convert the same tenant to licensed with the customer's
Gemini key. The **Licenciadas** tab separately lists licensed accounts with a
redacted license reference and their image-sponsorship status. Conversion calls
the deployed Vercel bridge, which writes one idempotent license record in
Upstash and returns the new code once; email/recovery is intentionally deferred.
The dashboard itself still has no Docker socket, tenant-root mount, bot token,
pool key, or ability to activate the image broker. First-run password creation
and provider authentication are performed by the operator in the browser,
never by pasting credentials into chat.

### Central image broker: prepared but dormant

The central image path is implemented behind the `central-images` Compose
profile, but it is not currently started. It requires a separately built and
verified hosted canary image tagged exactly
`admira-ia-hosted:r91-canary-<12sha>`; the live tenant image remains pinned to
`admira-ia:r90`.
Migration `008_central_image_jobs.sql` provides the durable, idempotent job
ledger and fenced leases. Only the `admira_image` database role can call its
runtime-keyed functions; it can enqueue or claim work only after the control
plane re-resolves the active tenant and its `central_sponsored` entitlement.

Prepare only the host boundaries with:

```bash
sudo ./prepare-central-image-broker.sh
```

This creates private directories for the broker socket, verifier keys, the
tenant-scoped exchange, and central Codex authentication. It never starts
Compose, enables `ADMIRA_CENTRAL_IMAGE_READY`, logs in to a provider, or copies
central credentials into a tenant. The service receives the central provider
credential only through its own restricted mount; tenants receive only a
per-tenant HMAC key, the Unix socket, and their own exchange directory.

Before these host boundaries exist, `tenantctl.py` deliberately omits the
central-image socket, exchange mount and client key from a tenant Compose file;
Docker must never autocreate those paths as root. After preparation, run the
normal idempotent provisioning operation once for each existing tenant so it
creates the tenant HMAC key and the exact `<tenant>/output` exchange mount:

```bash
./tenantctl.py provision client-001
```

Repeat for each tenant that should be prepared. This changes no readiness flag
and does not start the central broker or a tenant.

The safe activation sequence is: verify the separate r91 build and manifest;
install two authorized central provider connections out of band into separate
central-only auth locations; apply and verify migration 008; start exactly one
broker in the `central-images` profile for an operator-owned canary; exercise
one sponsored image plus the single-fallback and cooldown cases; inspect the
ledger, output hash, tenant boundaries and resource usage; then enable the route
only after both accounts and the canary pass. Until every gate is complete,
leave the profile stopped and `ADMIRA_CENTRAL_IMAGE_READY=false`.

The trial/explicit-extension image pool requires at least two independently authorized
central accounts. Each account has its own private 0700 auth directory and
0600 credential files under the host root
`/srv/admira/shared/central-codex-auth/{primary,secondary}/`, mounted into the
broker and the private operator dashboard at `/app/runtime/hermes/codex-auth-pool`.
This bind mount is writable because Codex may refresh its home; no tenant
mounts it. Login is performed through the private panel's official device
flow or a private terminal; credentials must never appear in chat, command
arguments, environment variables, logs, PostgreSQL, Git or a tenant. Stop the
central broker before rotating or disconnecting accounts: the two services
do not share a credential-rotation lock. The broker may try the other account at most once per request, for a
maximum of two provider attempts total, including when the primary reports a
quota or image-limit failure. The failed account enters its per-account
cooldown, and no further attempt is made against it during that cooldown.
Tenants remain pinned to `admira-ia:r90` while this central canary is pending.

The shared image route uses the standalone ChatGPT/Codex OAuth Images transport:
`/backend-api/codex/images/generations` for generation and
`/backend-api/codex/images/edits` for approved reference images. Hermes owns
OAuth storage and refresh only. The request never starts a Responses/chat-model
turn and never invokes `codex exec`. A private Python child selects exactly one
account home, so it cannot fall back to a tenant/global account. Buyer-owned
protected real photos and official logos remain governed by the hybrid creative
flow. Image-endpoint limits are reduced to safe categories; credentials,
provider bodies and prompts are not returned to tenants. The account lock
covers OAuth refresh and generation, including mirroring a refreshed session
before a long request.

#### Hosted clean-canary evidence

On 2026-08-31, the private operator release was deployed after the disposable
PostgreSQL rehearsal and the dashboard mount-boundary fix. Migrations 001–013
are current on the VPS and were applied idempotently; the final server
preflight returned `PASS`. The deployed control-plane marker is commit
`d1bef249927c96e38cbd1ccd51bad1fe17f31b00`; tenant runtimes remain deliberately
pinned to `admira-ia:r90`. The private dashboard uses hosted image
`admira-ia-hosted:r91-canary-e6fa64f85138` (manifest
`sha256:346e893c33cf3cdff7e4e8d3be2067536afc433b97c506925c9acef0e4a2714b`).

The synthetic/code canary uses two fake isolated auth homes and a fake provider:
it forces a primary image-limit failure, verifies exactly one fallback attempt
to the secondary account, cooldown bookkeeping, idempotency and tenant
isolation. This is only a local pool/code result; it does not verify real
ChatGPT authentication. The separate real-provider canary exercises the
external image route and requires both central-provider authentications; that
authentication is still pending: the dashboard password is configured, but only
one of the two 0700 central auth directories currently contains `auth.json`.
The central image service is stopped and `ADMIRA_CENTRAL_IMAGE_READY=false`.
Recovery and capacity soak remain deferred and off. The remaining image gate is
a second distinct authorized login and the real image/fallback test; this is
not commercial readiness. The validated private recovery backup is
`/srv/admira/backups/operator-lifecycle-caeb723-20260831T201433Z/`.

## Central Telegram path

The implementation is split into four independently credentialed processes:

1. `telegram-poller` owns the shared bot token, downloads inbound media and
   inserts a sanitized Telegram update.
2. Each `runtime-worker` replica owns no bot token and no Docker socket. It
   claims one durable turn at a time and calls the authenticated host broker
   over a Unix socket. This is the only buyer worker that may scale from one to
   eight replicas.
3. `telegram-delivery` owns the bot token, reads only opaque outbound spool
   references, verifies SHA-256 and sends ordered text/media from the outbox.
4. `scheduler-worker` owns no bot token. It claims due Hermes jobs, wakes the
   same tenant runtime through the broker, and puts the result in the outbox.

Only poller/delivery join the outbound Telegram network. Only
runtime/scheduler receive the broker key and socket group. None mounts
`/var/run/docker.sock`; that remains confined to the sandboxed host broker.
All database roles have function-only permissions and no direct table access.

The broker keeps `ProtectHome=true`. Its installer gives the Docker CLI a
private, empty `DOCKER_CONFIG` below `/run/admira-runtime-broker` so Compose can
wake a tenant without exposing the service user's home or registry credentials.
Broker dependency failures expose only stable machine codes; Docker stderr is
never returned through Telegram.

Keep exactly one `telegram-poller`, one `telegram-delivery` and one
`scheduler-worker` replica. Telegram user concurrency is handled by the durable
inbox/outbox, one-to-eight `runtime-worker` replicas and isolated tenant
runtimes, not by duplicating token-owning workers; the poller has one long-poll
cursor and the delivery process owns the shared pacing state.

PostgreSQL transactions provide deduplication, per-tenant turn ordering,
fencing leases, ordered response parts, retries and scheduler run history. A
container can sleep after the configured idle period without losing the
Hermes session: `runtime/`, `data/`, `output/` and brand files remain on disk.
Inbound spool objects expire after seven days and outbound objects after
fourteen days; successful outbound media is removed immediately after the
fenced outbox acknowledgement.

The single delivery process serializes sends, paces the shared bot globally
and per chat, and honors Telegram's bounded `retry_after` response. Telegram
rate limiting remains durable backpressure in the outbox instead of consuming
the normal dead-letter attempt budget; unrelated delivery failures retain a
finite retry budget.

If Telegram media download fails, the poller retries staging twice and then
durably enqueues a text-only resend request. The Telegram cursor advances only
after the original update or that fallback is durably handled; database
failures keep the cursor parked. Broker materializations inside a tenant are
removed after the turn completes.

### Tenant claim and `chat_id → tenant_id`

An operator can bind already-known public IDs, but the normal path is a
one-time Telegram deep link. The CLI provisions the private tenant directory,
stores only the SHA-256 of the claim in PostgreSQL, and returns a `start`
parameter. Telegram consumes it once; the raw value never reaches the inbox,
tenant files or model context.

```bash
./tenant_admin.py claim buyer-001 "Nombre del comprador" \
  --bot-username NombreDelBotCentral

# Support-only alternative when all public Telegram IDs are already known:
./tenant_admin.py bind buyer-001 "Nombre del comprador" BOT_ID CHAT_ID USER_ID
```

Issuing a claim does not start the buyer runtime or enable the shared bot.

### Deliberate activation gate

All four network workers use the Compose profile `buyers`. The bootstrap
creates an empty token file, so ordinary deployment cannot accidentally start
buyer traffic. Only after a real central token is installed and a controlled
canary is approved should an operator run:

```bash
docker compose --profile buyers build
docker compose --profile buyers up -d \
  --scale telegram-poller=1 \
  --scale runtime-worker=1 \
  --scale telegram-delivery=1 \
  --scale scheduler-worker=1
```

Do not run that activation command during infrastructure preparation.

The deployed starter profile remains conservative: one runtime worker and at
most four simultaneously running tenant containers
(`ADMIRA_MAX_ACTIVE_TENANTS=4`). The prepared capacity profile uses six normal
slots, an absolute ceiling of eight, and up to eight runtime-worker replicas.
Slots 7–8 are admitted only while Linux `MemAvailable` remains at or above
`ADMIRA_BURST_MIN_AVAILABLE_MB` (2048 MiB by default). The locked broker, not
Compose, owns this admission decision.

When a new turn reaches a full node, PostgreSQL may fence and select the
least-recently-used runtime that is actually idle. A runtime with a current
holder, a processing turn, an eligible queued update, or leased/due scheduled
work cannot be evicted. Suspending the selected container does not remove the
tenant filesystem, conversation history, memory, provider connections or
outputs; the next turn wakes the same workspace. If every slot is busy, the
turn and scheduled job remain in durable retry state. Capacity deferrals have a
separate counter and do not consume the finite execution-failure budget.

Do not activate the 6+2 profile merely because it is configured. First run a
staged multi-tenant soak and record cold-wake latency, active-tenant RSS, queue
age and provider latency. Host swap is an emergency cushion only and is never
counted as normal or burst admission memory.

### Verification

Run the non-mutating release gate locally before packaging, then on Contabo
after installing the release and two operator-owned canary tenants. It never
starts buyer workers, creates tenants, changes PostgreSQL or prints secrets:

```bash
./release-preflight.sh --local
./release-preflight.sh --server --tenant-a canary-one --tenant-b canary-two
./capacity-preflight.sh
```

`capacity-preflight.sh` is read-only. It reports CPU, RAM, swap, swappiness,
disk, cgroup memory and Docker RSS/limits without reading environment files or
printing credentials.

`db/validate_control_plane.sql` and `db/validate_trial_lifecycle.sql` are
destructive fixtures intended only for disposable PostgreSQL databases. They
prove the claim, binding, inbox, runtime lease, outbox, scheduled-work and
trial/license transitions while switching to restricted roles. Never run them
against the live control database.

`db/validate_telegram_license_recovery.sql` is also destructive and disposable
only. It validates the recovery identity schema, generic decoy responses,
rate-limit state, OTP fencing and binding history. Unit/integration tests cover
the prepared `/recuperar` and `/codigo` routing and SMTP/outbox boundaries, but
they do not prove a live Telegram recovery until the readiness flag is enabled
in a canary with an authorized SMTP provider.

## Trial and licensing operator flow

Migration `007_trial_provider_lifecycle.sql` makes the legacy claim-first
lifecycle durable. For an account created through the operator dashboard,
migration `013_operator_trial_provisioning.sql` deliberately supersedes that
start rule: the exact five-day clock is anchored to the account creation time,
not the later Telegram claim. Reissuing its link never moves the clock. Expired
trials are suspended and cannot be bypassed by issuing a new claim; the same
durable tenant can still be licensed in place.

The normal path for a dashboard-created customer is the live **Pruebas** →
**Licenciadas** conversion: it preserves the tenant, history and Telegram
binding, creates the hosted license through Vercel/Upstash, installs the
customer Gemini key privately and displays the code once. It deliberately does
not ask for or send recovery email yet.

The supported credential CLI below is a separate host-only legacy/repair path.
It accepts the Gemini key only from stdin or a private regular file (mode 0600);
it never accepts a key in an argument:

```bash
./gemini_pool_admin.py register my-gemini-project --capacity 15 --key-kind auth --key-file /secure/operator-gemini.txt
./gemini_pool_admin.py assign buyer-001
./provider_admin.py gemini-set buyer-001 --source customer --key-file /secure/customer-gemini.txt --replace
./provider_admin.py gemini-license buyer-001 --source customer --key-file /secure/customer-gemini.txt \
  --email-file /secure/customer-recovery-email.txt
```

`gemini-license` generates a license ID unless `--license-file` supplies one;
the one-time JSON result contains that license ID, so deliver it through a
private operator channel. `--email-file` is required for `gemini-license`; it
must be a regular mode-0600 file and is consumed only in memory. The command
uses the central recovery HMAC key at `secrets/recovery_hmac_key.txt` by
default. License ID, normalized-contact HMACs and provider metadata are
recorded atomically; PostgreSQL never stores the email, Gemini key or any
ChatGPT/Codex credential. The lifecycle validator is disposable-DB-only and is
not an operational migration command.

Every non-dry-run `gemini-set` and `gemini-license` performs a bounded health
check using Google's official `GET /v1beta/models?pageSize=1` endpoint. The key
is sent only in the `x-goog-api-key` header, together with
`x-goog-api-client: admira-hosted/r91`; it is never placed in a URL, argument,
log, or returned error. `--allow-unverified` is an explicit emergency/operator
exception and must not be used when preparing customer-ready accounts. Dry-run
does not call the network. See Google's [Gemini API key guidance](https://ai.google.dev/gemini-api/docs/api-key).

Provider replacement is fenced: suspend the tenant runtime, write the private
secret, run the health check, and only then update PostgreSQL metadata.
`--runtime-already-stopped` is an explicit operator bypass for a separately
verified stopped runtime, not a routine shortcut. If the suspend fence fails,
no credential is changed.

### Telegram recovery readiness

The prepared user flow is private-chat only. An unbound Telegram identity is
given a generic instruction to send `/recuperar EMAIL LICENCIA`; if the factors
match a licensed contact, the encrypted delivery outbox sends an OTP by email.
The user then sends `/codigo REQUEST_ID OTP`. A successful confirmation revokes
the old binding and atomically binds the same durable tenant to the new private
Telegram identity. Invalid or unknown factors receive the same generic public
outcome and are rate-limited.

This flow is not enabled in the current deployment. Keep
`ADMIRA_TELEGRAM_RECOVERY_READY=false` and do not start `recovery-email` until
all of the following are recorded: an authorized SMTP provider, a verified
sender/domain with SPF, DKIM and DMARC, private recovery HMAC/delivery/SMTP
secrets, a backup and reviewed migration state, a second operator-owned
Telegram identity, and a canary showing request idempotency, OTP fencing and
atomic rebind. Start and verify the email worker while the flag is still
`false`; then set it to `true`, rerun the server preflight, recreate the poller
and perform the end-to-end canary. For rollback, stop the poller and email
worker first, set the flag back to `false`, and recreate only the poller;
restore the pre-canary backup only if the canary changed data.

The customer-ready preparation pool must use authorization (auth) keys. New
AI Studio keys are auth keys; unrestricted standard keys are rejected, and
Google plans to reject all standard keys in September 2026. A health response
from a legacy standard key is therefore not commercial readiness, even if the
endpoint still answers. This repository does not claim to contain confirmed
real pool keys or a live pool; operators must create and restrict keys out of
band before admitting accounts.

## Release integrity

The live tenant image must remain exactly:

- version: `r90`
- commit: `d03707465a5fedf7e5d1bb6b528365b299795540`
- source manifest: `5df0e07e8b4a10e59a5b9c3659336f9b3a55ab556beaa67c2faba218dabc99db`

Future images require the same three-way verification before any runtime is
restarted. Never patch a running tenant container or copy files from an older
release directory.

The isolated hosted central-image candidate is identified only by the exact
canary tag `admira-ia-hosted:r91-canary-<12sha>`. Building or smoke-testing it
does not make it live: tenant runtimes stay pinned to `admira-ia:r90`, and the
canary tag may not be promoted until the real-provider authentication and
remaining promotion gates have passed.
