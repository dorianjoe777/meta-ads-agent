# Hosted onboarding and trial creation — 2026-09-09

Verified live default for new tenants: `admira-ia-hosted:r99-canary-bb05a5ebc761`,
selected by the provisioner's `tenant-image.conf` systemd drop-in. `dorian1`
uses that image. The numeric OAuth gate is injected by the host broker from
`/srv/admira/releases/control-plane-990c0780584f/tenant_turn.py`; changing only
the tenant image would not update that gate.

Diagnosis from the live records:

- At 14:59 UTC the gate sent the fixed Facebook Page/ad-account inventory.
  After the buyer selected a pair, the gate persisted it and returned `None`.
  That dispatched the numeric reply into a fresh model conversation, which
  asked for the same selection again at 15:00 UTC using different wording.
- Trial creation at 14:56 UTC reserved a Gemini credential, failed its single
  health request, rolled back and released the reservation. A later request
  succeeded at 14:57 UTC. Read-only reproduction with the same installed key
  produced a transport timeout followed by two HTTP 200 responses in under
  0.1 seconds each. The dashboard kept the creation error visible after the
  separate Enlace action recovered the assignment.

Fix:

- Keep both the selection prompt and saved-selection acknowledgement in the
  deterministic host gate. A verified selection returns a fixed response and
  cannot invoke the model in that turn. Invalid and partial choices continue
  to show the full inventory; persistence failures remain blocked.
- Retry Gemini transport failures and HTTP 408/429/500/502/503/504 up to three
  total attempts with the existing eight-second per-request timeout. Rejected
  credentials, certificate verification failures and invalid responses still
  fail closed. Log only a safe category and attempt count.
- Track a failed creation by its exact client reference. Subsequent successful
  inventory refreshes clear the obsolete error only when that same trial has
  a ready Gemini assignment. Partially created accounts are described as
  created with activation pending and point to Enlace for recovery.

Validation before deployment: 165 focused Python tests across provider admin,
pool assignment, operator dashboard, provisioner lifecycle, hosted turns and
OAuth selection. The 31 OAuth integration tests ran in an isolated container
using the actual default r99 image with the patched host gate mounted, with
network disabled and no customer volumes. Node tests exercise partial
creation, later recovery, lost responses, another account's readiness, failed
refresh and identical VPS/mobile JavaScript. JavaScript syntax passes.

The tenant image itself needs no change for these fixes. Deploy the gate to
both the active broker release and `/srv/admira/control-plane`, the provider
module to the active provisioner, and matching operator assets to the VPS
panel and the `admira-mobile-operator-dashboard` Vercel project. Keep recovery
copies of replaced files and the prior operator image before restarting the
services. Verify live hashes and a disposable trial lifecycle after rollout.
