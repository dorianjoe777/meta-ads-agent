# Private tenant lifecycle boundary

`tenant_provisioner.py` is the small host-side bridge used by the loopback-only
operator dashboard. It exists so the dashboard can create or manage Admira
customer accounts without receiving Docker access, the tenant filesystem, the
provisioner database password, Gemini pool files, or the hosted-license bridge
key.

It listens only on `/run/admira-tenant-provisioner/provisioner.sock`. Every
request is one bounded JSON line, HMAC-SHA256 signed with
`/etc/admira/tenant-provisioner.key`. The browser never sees that key; the
dashboard reads its private bind-mounted copy at
`/run/admira-tenant-provisioner.key` only to authenticate to the fixed Unix
socket. The socket directory itself remains a separate read-only bind so the
key is not nested below a read-only mount. Requests must be younger than 90
seconds and their nonces
are durably remembered across a daemon restart.

The only accepted actions are:

- `create_trial` — prepares the same customer tenant that will later become
  licensed, anchors the trial to its account creation time, assigns an active
  operator Gemini-pool entry, then issues a one-time Telegram deep link.
- `reissue_trial_claim` — makes a replacement link without moving the five-day
  clock. It first verifies that Gemini is assigned, so a customer never gets a
  link to an unusable trial.
- `extend_trial` — sets a later exact expiration timestamp, bounded to one
  year.
- `expire_trial` — changes the database to a fail-closed trial-expired state
  and stops the tenant runtime. Retrying it is safe if Docker was temporarily
  unavailable during the first stop attempt.
- `license_trial` — calls the deployed Vercel hosted-license bridge with the
  server-to-server key. That bridge creates one idempotent record in the
  Upstash-backed registry; the provisioner then validates and installs the
  customer's Gemini key in the tenant's private environment and executes the
  matching licensed transition. It returns the newly generated license code
  once to the logged-in operator dashboard. It does not fabricate an email or
  configure recovery.

The code deliberately returns generic stable error codes and discards Docker,
database, Google, and hosted-license error text. Raw Gemini keys are never put
in command arguments, PostgreSQL, logs, responses, or audit events.

## Install on Contabo

Run the normal control-plane bootstrap first as the service user. It creates
the two private key files if they do not exist:

```bash
./bootstrap-control-plane.sh
sudo ./install-tenant-provisioner.sh
```

The hosted license bridge also needs the identical
`LICENSE_HOSTED_BRIDGE_KEY` configured in the Vercel license project before
the service is useful. The deploy runbook sets it without printing the value.
The installer rejects any endpoint other than the pinned HTTPS Admira license
endpoint and validates the public Telegram bot username.

`admira-tenant-provisioner.service` is intentionally a privileged host daemon:
membership in Docker's group is effectively root-equivalent. That membership
is necessary only because it invokes the existing tenant and Compose helpers.
It must remain confined to this service; **never** mount `/var/run/docker.sock`
or `/srv/admira/tenants` into the dashboard, and never add the dashboard user
to Docker's group.

When the separate central-image host roots have already been prepared, tenant
creation also writes only a per-tenant verifier under
`/etc/admira/central-image-keys/` and that tenant's isolated exchange directory
under `/srv/admira/shared/central-image-exchange/`. Those two paths are the
only additional sandbox write exceptions; they do not activate central images
or expose either central ChatGPT account to the dashboard or a tenant.

## Verification

```bash
systemctl status --no-pager admira-tenant-provisioner.service
test -S /run/admira-tenant-provisioner/provisioner.sock
python3 -m unittest discover -s deploy/contabo/tests -v
```

The final release preflight also checks that the dashboard has only the
authenticated socket/key bind and provisioner group—not Docker or a tenant
directory—and that migration 013 exposes read-only lists to the dashboard role
while mutations remain provisioner-only.
