# Internal operator dashboard

This is an operator-only control surface, not a buyer dashboard. It publishes
exactly `127.0.0.1:8791` on the VPS and has no Docker socket, tenant volumes,
Telegram token, public endpoint, or tenant-provisioning authority. Never open
8791 in a firewall or put this service behind a public reverse proxy.

The service has its own provider-egress network. Only PostgreSQL shares its
internal `operator_private` network; buyer workers and the central image broker
share neither operator network. This isolates the first-run password screen
from those containers. Root and the host service user remain trusted operators.

## Prepare the exact release

Make a private recovery backup of PostgreSQL and the existing `secrets/`
directory; encrypt the backup before any off-host export. Rehearse migrations 001–011 on a disposable
database and run `db/validate_operator_dashboard.sql` there; the validator rolls
its fixtures back. Never run disposable validators on production. Migration 011
does not alter tenant data or weaken forced RLS. It grants the dedicated
`admira_operator` role only project registration, credential metadata
registration, and a status projection without secrets or tenant identifiers.

As `admiraops` (the configured service UID, normally 1001):

```bash
cd /srv/admira/control-plane
./bootstrap-control-plane.sh
./apply-control-plane.sh
```

Bootstrap generates a separate `operator_db_password.txt` and creates private
`secrets/operator-password/` with mode 0700. It does not create a default password,
an empty hash, or a provider credential. The directory is mounted read/write so
first-run setup can persist `password.hash` with mode 0600. Preserve the directory
across release swaps and include it in the private secrets recovery backup.

The fixed provider bind sources must exist before Docker starts the service:

```bash
sudo ./bootstrap-control-plane.sh --prepare-operator-host-dirs
```

That explicit root-only mode creates/validates private Gemini and Codex account
directories, then exits without touching release-local secrets. Existing
unexpected owners or symlinks cause failure. If UID/GID values differ from the
defaults, pass the reviewed numeric `ADMIRA_SERVICE_UID`, `ADMIRA_SERVICE_GID`,
and `ADMIRA_CENTRAL_IMAGE_GID` to that command; they must match `.env`.

Pin `CENTRAL_IMAGE_IMAGE` in `.env` to the exact clean output of
`build-hosted-runtime.sh --inspect`, such as the verified
`admira-ia-hosted:r91-canary-<12sha>` tag. The hosted image includes the pinned
Codex CLI and the dashboard source. The all-zero placeholder is dormant and must
not be used to start the dashboard. Do not use a mutable `latest` tag.

## Start, restrict setup, and tunnel

```bash
docker compose --profile operator-dashboard config --quiet
docker compose --profile operator-dashboard up -d operator-dashboard
docker compose --profile operator-dashboard ps operator-dashboard
```

Docker may present a bridge gateway instead of `127.0.0.1` to the container for
host-loopback requests. Setup accepts only `ADMIRA_OPERATOR_SETUP_CIDRS`, which
defaults to loopback addresses and ignores forwarded headers. Inspect the two
dedicated network gateways (these commands print network addresses, not secrets):

```bash
docker network inspect admira-control-plane_operator_private \
  --format '{{range .IPAM.Config}}{{.Gateway}}{{"\n"}}{{end}}'
docker network inspect admira-control-plane_operator_provider_egress \
  --format '{{range .IPAM.Config}}{{.Gateway}}{{"\n"}}{{end}}'
```

If required by Docker's observed peer address, add only those exact gateway
addresses with `/32` (IPv4) or `/128` (IPv6) to `ADMIRA_OPERATOR_SETUP_CIDRS` in
`.env`, alongside loopback, then recreate only the dashboard. Do not allow an
entire bridge subnet, a private-address range, or `0.0.0.0/0`. Custom Compose
project names change the network-name prefix. Host/Origin checks still permit
only `localhost`, `127.0.0.1`, and `::1`.

```bash
docker compose --profile operator-dashboard up -d --force-recreate operator-dashboard
./release-preflight.sh --server --operator-dashboard \
  --tenant-a canary-one --tenant-b canary-two
```

Preflight is read-only. It checks the rendered loopback port and dedicated
networks, image pin, private directories/ownership, dedicated database role,
and exact setup-source addresses. A missing password hash is reported as pending
first-run setup, not silently seeded. General server canary checks still apply.

From your own computer, keep this tunnel open:

```bash
ssh -N -L 127.0.0.1:8791:127.0.0.1:8791 admiraops@your-vps
```

On this Mac, the executable `open-operator-dashboard.command` is a convenience
launcher using the existing `admira-contabo` SSH alias/key. Double-click it or run
it from the local checkout; it creates a loopback-only tunnel and opens the
browser without handling any password or provider credential. Keep its terminal
open. Closing it closes only its own tunnel, not the VPS dashboard.

Open `http://127.0.0.1:8791` in your local browser. The service itself is HTTP;
SSH encrypts the transport to the VPS. Its session cookie is HttpOnly and
SameSite=Strict; Secure is disabled solely for this loopback HTTP tunnel.
Never visit the dashboard through a non-loopback HTTP hostname.

Create a unique password in the first-run screen (at least 16 characters,
preferably a password-manager-generated passphrase). Only its adaptive hash is
stored. Setup is one-time and CSRF-protected; afterward sign in explicitly with
the new password. Do not paste passwords, API keys, auth files, or device codes
into chat, tickets, logs, shell arguments, or environment variables.

## Connect Gemini and two image accounts

Do not rotate/reconnect or disconnect Codex accounts while the central image
broker is running. The dashboard and broker share the private pool, but there is
not yet an integrated cross-service rotation interlock. Perform account changes
only while `central-image-broker` is stopped, then repeat the account and image
canaries before any approved broker restart. This dashboard release leaves that
broker dormant and does not authorize a production stop or activation.

Register each Gemini project's auth key and quota capacity through the dashboard.
The key is checked against Google's official endpoint and stored only in the
private Gemini pool; PostgreSQL gets an opaque reference and fingerprint, never
the key. Capacity is per project: multiple keys do not multiply project quota.
The status screen is metadata, not proof that a commercial trial was provisioned.

In the image-account section, connect both fixed slots, `primary` and `secondary`:

1. Start the device login for `primary` and open the displayed official OpenAI
   verification URL yourself. Confirm it is the account you intend to sponsor.
2. Complete the provider's device confirmation, then refresh its status.
3. Repeat with the second intended account in `secondary`.

Each slot has a separate private auth home under
`/srv/admira/shared/central-codex-auth/`. The dashboard runs only the native
allowlisted device-login command, one bounded job per slot, with expiry and
cancel support. It never exposes raw CLI output or `auth.json`. Device URLs/codes
are temporary and cleared from expired/finished jobs. Disconnect removes only
that selected slot's auth file; the other account is preserved. A connected
status alone does not establish usable image quota or successful failover.

## Status, stop, and activation boundary

```bash
docker compose --profile operator-dashboard ps operator-dashboard
docker compose --profile operator-dashboard stop operator-dashboard
docker compose --profile operator-dashboard up -d operator-dashboard
```

Stopping the profile preserves its hash and both provider pools. It does not
start or stop buyer workers. Sessions are in memory, so restart requires login.
Do not delete the private directories when removing a container.

The central image broker remains separately opt-in and dormant. Dashboard
startup, registering a Gemini key, and connecting two accounts do not activate
`central-images`, license buyers, or prove delivery. Keep
`ADMIRA_CENTRAL_IMAGE_READY=false` until the pinned broker image, both account
checks, real-provider image canary, failover checks, and tenant-isolation canary
have passed under the existing approved activation procedure. The dashboard
cannot change that flag or start the broker.
