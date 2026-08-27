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

`tenant_turn.py` is the text-only bridge used by the future central Telegram
ingress. It accepts one JSON request on stdin and runs `hermes_bridge.chat` in
the already-running tenant container; the caller must resolve the tenant from
the control plane first. It derives a stable session from the Telegram chat
ID, rejects media until the text path is proven, and never returns raw provider
errors to Telegram:

```bash
printf '%s\n' '{"message":"Hola","chat_id":"123","language":"es","update_id":42}' \
  | ./tenant_turn.py client-001
```

The shared Telegram bot token is intentionally absent from every tenant
runtime. The central ingress, durable `tenant_telegram_updates` ledger and a
future outbox are required before enabling buyer traffic.

## Control plane

`compose.yaml` starts PostgreSQL and Redis on an internal-only Docker network.
It publishes no host ports. PostgreSQL is the canonical source for tenant,
trial, entitlement, Telegram binding, runtime lease and scheduled-work state.
Redis is transient coordination only; it is not the durable source of truth.

Prepare secrets once:

```bash
./bootstrap-control-plane.sh
docker compose up -d
```

The generated `secrets/` directory and `.env` are git-ignored and must be
backed up through the server's encrypted backup process, never committed.

## Telegram boundary

Only one central Telegram ingress may own the shared bot token. It resolves a
Telegram DM to a tenant, deduplicates `update_id`, and relays the event to that
tenant's runtime. The shared token must never be copied into tenant volumes.
The Relay connector is intentionally a later slice; until its end-to-end
isolation tests pass, hosted buyer traffic must not be enabled.

## Release integrity

The first server image must remain exactly:

- version: `r90`
- commit: `d03707465a5fedf7e5d1bb6b528365b299795540`
- source manifest: `5df0e07e8b4a10e59a5b9c3659336f9b3a55ab556beaa67c2faba218dabc99db`

Future images require the same three-way verification before any runtime is
restarted. Never patch a running tenant container or copy files from an older
release directory.
