# Hosted onboarding and trial creation — 2026-09-09

Later same-day deployment: see `CONVERSATION_RECOVERY_20260909.md` for the new
tenant default and proposal/context fix. The host/operator fixes below remain.

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

Deployment verified:

- Fix commit `9114afc34c9621b718b67fb13194a25f4a00d05b` pushed to the hosted
  branch. The tenant default remains `r99-canary-bb05a5ebc761` because these
  changes run at the host gate and operator boundary.
- Gate installed in both the active broker release and
  `/srv/admira/control-plane`; provider installed in the active provisioner.
  Both systemd services restarted successfully after confirming zero active
  buyer turns. No customer runtime image was replaced.
- Operator image `admira-operator:onboarding-9114afc34c96` layers only
  `provider_admin.py` and `operator_dashboard.js` onto the previously active
  `r99-canary-0601767a73ab` image. Its `io.admira.patch-commit` and
  `io.admira.patch-base` labels describe the overlay; inherited source labels
  still describe the base image. The `.env` operator-image selector was updated.
- Recovery copies are in `/srv/admira/backups/onboarding-9114afc34c96`, including
  the prior host modules, JavaScript and operator `.env`. Base images remain.
- Vercel deployment `dpl_Dsd4iWwaenfdEAyjNW2iFrWiKcLV` is ready. The custom
  alias `dashboard.uboost.lat` was explicitly moved to
  `admira-mobile-operator-dashboard-qdjfksctf-dorianx.vercel.app`; that alias
  was pinned separately and did not follow a normal production deploy.
- The VPS panel and public domain both serve JavaScript SHA-256
  `4c05dffd5d531a1b338cb86d7374266abc993dda5c8342f21df1990601d8bd96`.
  Both active gate copies have SHA-256
  `9e1f622bd23c42b10eeecde145a3405e69cb84f14841607b0039247a216ca269`.
  Provider SHA-256 is
  `92914ce0fbd30c6370990e999c6dac4d45d2ef0d5fe34dd7e6af6a39670e27f2`.
- A real signed request through the deployed operator/provisioner created
  disposable trial `onboarding-smoke-aa7821c600` with Gemini ready and a claim
  URL in 2.74 seconds. The fixture was deleted through the normal fenced
  lifecycle; its workspace was removed and the prior customer inventory and
  per-project occupancy were unchanged. No claim was consumed and no Telegram
  message was sent. The existing `dorian1` Facebook selection was preserved.
- Public session and protected trial routes still return their expected
  unauthenticated responses through the deployed gateway.
