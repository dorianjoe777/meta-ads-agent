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
