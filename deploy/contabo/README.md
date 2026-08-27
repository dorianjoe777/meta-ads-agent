# Admira hosted runtime foundation

This directory is the initial control-plane foundation for hosted Admira IA.
It deliberately preserves the proven r90 product boundary: one immutable image
is shared by the host, while every buyer receives a separate process,
environment and persistent filesystem.

## Isolation boundary

Each tenant owns an exclusive directory below `/srv/admira/tenants/<tenant>`:

- `runtime/` for `HERMES_HOME` and `CODEX_HOME`
- `data/` for business memory, OAuth state and product state
- `output/` for generated and uploaded media materializations
- `brand_guides/` for the buyer's approved brand assets
- `logs/` for that runtime only

New tenants are bootstrapped with Gemini 3.5 Flash Lite as the text brain,
without a Telegram token and with live Meta actions disabled. A buyer can later
choose a ChatGPT/Codex subscription or another supported provider through the
normal onboarding flow; that choice is written to the tenant's private
`runtime/.env` and is not overwritten by a restart.

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
Telegram chat ID, accepts only broker-materialized image paths below the
tenant's own `/app/output/telegram_uploads/` directory, and never returns raw
provider errors to Telegram:

```bash
printf '%s\n' '{"message":"Hola","chat_id":"123","language":"es","update_id":42}' \
  | ./tenant_turn.py client-001
```

The shared Telegram bot token is intentionally absent from every tenant
runtime.

## Control plane

`compose.yaml` starts PostgreSQL and Redis on an internal-only Docker network.
It publishes no host ports. PostgreSQL is the canonical source for tenant,
trial, entitlement, Telegram binding, inbox, outbox, runtime lease and
scheduled-work state. Redis is transient coordination only; it is not the
durable source of truth.

Prepare secrets once:

```bash
./bootstrap-control-plane.sh
./apply-control-plane.sh
sudo ./install-runtime-broker.sh
```

The generated `secrets/` directory and `.env` are git-ignored and must be
backed up through the server's encrypted backup process, never committed.

## Central Telegram path

The implementation is split into four independently credentialed processes:

1. `telegram-poller` owns the shared bot token, downloads inbound media and
   inserts a sanitized Telegram update.
2. `runtime-worker` owns no bot token and no Docker socket. It claims one turn
   per tenant and calls the authenticated host broker over a Unix socket.
3. `telegram-delivery` owns the bot token, reads only opaque outbound spool
   references, verifies SHA-256 and sends ordered text/media from the outbox.
4. `scheduler-worker` owns no bot token. It claims due Hermes jobs, wakes the
   same tenant runtime through the broker, and puts the result in the outbox.

Only poller/delivery join the outbound Telegram network. Only
runtime/scheduler receive the broker key and socket group. None mounts
`/var/run/docker.sock`; that remains confined to the sandboxed host broker.
All database roles have function-only permissions and no direct table access.

PostgreSQL transactions provide deduplication, per-tenant turn ordering,
fencing leases, ordered response parts, retries and scheduler run history. A
container can sleep after the configured idle period without losing the
Hermes session: `runtime/`, `data/`, `output/` and brand files remain on disk.
Inbound spool objects expire after seven days and outbound objects after
fourteen days; successful outbound media is removed immediately after the
fenced outbox acknowledgement.

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
docker compose --profile buyers up -d
```

Do not run that activation command during infrastructure preparation.

### Verification

`db/validate_control_plane.sql` is a destructive fixture intended only for a
disposable PostgreSQL database. It proves the claim, binding, inbox, runtime
lease, outbox and scheduled-run path while switching to the same restricted
roles used in production. Never run it against the live control database.

## Release integrity

The first server image must remain exactly:

- version: `r90`
- commit: `d03707465a5fedf7e5d1bb6b528365b299795540`
- source manifest: `5df0e07e8b4a10e59a5b9c3659336f9b3a55ab556beaa67c2faba218dabc99db`

Future images require the same three-way verification before any runtime is
restarted. Never patch a running tenant container or copy files from an older
release directory.
