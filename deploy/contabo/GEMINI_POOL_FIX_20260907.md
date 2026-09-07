# Gemini pool assignment and visibility — 2026-09-07

The production dashboard runs on the Contabo VPS, through the private
operator-dashboard service. Local entry point: http://127.0.0.1:18793/.
Repository worktree: .contabo-multitenant-work, branch feat/contabo-multitenant.

Production diagnosis:
- Six active healthy auth credentials, each project configured for two trials.
- At inspection, zero active assignments; twelve configured slots were free.
- dorian-admira existed in trial state despite the dashboard error.
- The failed attempt on September 7 at 00:55 UTC reserved a credential, then
  released it about ten seconds later. The provisioner collapsed every
  installation failure into gemini_pool_unavailable and recorded no category.
  The historical installation failure cannot be determined from those records.
- Retrying the normal assignment and signed provisioner claim flow succeeded.
  dorian-admira now occupies one slot on cuenta-prueba-1-y-2; eleven remain free.

Changes:
- Separate no eligible assignment from installation, health, environment,
  finalization, fencing and cleanup failures; log only safe categories.
- Add migration 020 with an operator-only occupancy/client projection.
- Show configured capacity, occupied slots, eligible free slots and client
  references per project, with automatic refresh after account operations.
- Refresh account lists after failed creation so partially created accounts
  remain visible and can be retried with the same reference.

Allocation remains transactional and persistent. It fills an eligible project
up to its configured capacity before using the next; it does not randomly
choose a key on every request. Licensing releases the trial pool assignment
and uses the customer's Gemini credential. These are local admission limits,
not a measurement or guarantee of Google's request/token quota.

Validation: 8 provisioner tests, 14 pool-admin tests, 36 operator-dashboard
tests and 6 operator lifecycle tests. JavaScript syntax check. A disposable
PostgreSQL database cloned from the production schema verified 6 x 2 slots,
12 successful assignments, refusal of the thirteenth, idempotent retries,
release and reuse, licensing release, unhealthy-key exclusion and permissions.

Deployment verified:
- Source commit 3a0064e6e374 pushed to origin/feat/contabo-multitenant.
- Live release: /srv/admira/releases/control-plane-3a0064e6e374.
- Dashboard image: admira-ia-hosted:r99-canary-3a0064e6e374, derived from the
  previously deployed 990c0780584f image with only the five changed modules/assets.
- Recovery files: /srv/admira/backups/gemini-3a0064e6e374.
- Provisioner now starts through /srv/admira/control-plane using the systemd
  current-release.conf drop-in, rather than staying pinned to the old release.
- Migration 020 applied; operator projection returns 11 free slots and the
  dorian-admira assignment. Signed claim generation succeeds after restart.
- Served JavaScript SHA-256 matches the committed source. UI layout checked
  in a read-only local fixture. Production account readiness verified via
  the running operator service and actual provisioner.
- Disposable validation database removed. No other clients were modified.
