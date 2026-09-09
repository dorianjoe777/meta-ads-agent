# Hosted conversation and proposal recovery — 2026-09-09

Implementation: `0dcae21ac47d681d10f3579bf59f12611aed2cc1` on
`feat/contabo-multitenant`. This supersedes the tenant-default version recorded
earlier in `ONBOARDING_FIX_20260909.md`; the earlier host/operator fixes remain.

## Observed failure

The `dorian1` business profile was confirmed at revision 5. Its isolated
proposal compiler received HTTP 503 from `gemini-3.7-flash`; fresh Meta reads
were verified and the confirmed business facts were present. This was an
intermittent planner-provider failure, not an outage of the conversational
`gemini-3.5-flash-lite` model. A private read-only replay reproduced 503 and
then generated a valid five-section proposal on the bounded retry.

The hosted bridge tried compilation only on the original confirmation turn,
despite promising recovery. Its canned failure response skipped Hermes,
whose stored drafts could also differ from the finalized Telegram reply.
Shared provider-boundary code appended application instructions to the latest
user message. These gaps explain the subsequent reply blaming the buyer for
technical metadata and continuing an unrelated draft conversation.

## Changes

- Resume pending compilation from durable state on subsequent buyer turns.
  Existing readiness checks, five-minute failure cooldown, lease, exact-turn
  compare-and-swap and existing-plan checks remain authoritative.
- Planner order is full Gemini 3.7 Flash, 3.6 Flash, 3.5 Flash, then entitled
  hosted ChatGPT/Codex pool with Terra. All three Gemini models were listed as
  supporting `generateContent` by the installed account. Lite is never used
  for this proposal. Local/personal Codex remains a fallback when no hosted
  route is configured. Retry transient Gemini status codes at most once per
  model within the total deadline; rejected credentials skip other Gemini
  models using the same key.
- The central compiler accepts the dedicated `admira_prepare_strategic_plan`
  operation with its server-owned five-field schema, existing HMAC validation,
  entitlement checks and pooled account locks. No new mutation tool is exposed.
- Runtime guidance goes into the system role (or Responses instructions).
  Persist the finalized bridge reply with an exact-turn check; project that
  actual prior exchange into the next request while preserving tool receipts
  and the current buyer message. Include the confirmed business facts after
  onboarding, including when proposal generation has failed.
- Let the conversational model explain failed generation naturally. No new
  buyer-word filters or canned failure responses were added.

## Verification

278 targeted tests passed inside isolated containers based on the actual
default r99 image, with network disabled and no customer volumes: conversation
recovery 6, strategic compiler 17, OAuth 33, proposal lifecycle 10, prompt
performance 35, plan context 18, inference policy 126, signed central client 6,
central service 21, compiler broker 6. Affected prompt/context suites were
rerun after the final context adjustment. Module imports and image source
hashes matched the commit.

A private live Gemini chat simulation of the original `que` exchange, using
the confirmed business state and finalized prior response, explained the
proposal failure and preserved the business facts. Earlier reduced-context
simulations exposed continuing drift and were not accepted as verification.
These checks did not send Telegram messages or write customer business data.

## Deployment

- New tenant default and `dorian1/compose.yaml`:
  `admira-ia-hosted:r99-canary-0dcae21ac47d`, image `ac63b09e15ec`.
  Runtime overlay base: `r99-canary-bb05a5ebc761`.
- Central broker: `admira-ia-hosted:proposal-pool-0dcae21ac47d`, image
  `8bd0087a462c`, overlay base `r99-canary-990c0780584f`.
- Both images identify the patch commit and prior image in `io.admira.patch-*`
  labels. Inherited upstream labels describe their base image.
- Verified the live provisioner process environment contains the new default;
  provisioner is active and central broker is running. Dorian was dormant
  during deployment and will wake with the new image on its next turn.
  Session, business profile and Facebook selection were preserved.
- Recovery copies: `/srv/admira/backups/conversation-0dcae21ac47d`.
  Contains prior tenant compose, provisioner drop-in and control-plane `.env`.
  **Rollback caveat:** the previous `.env` central selector was stale
  (`r99-canary-3a0064e6e374`) while the actual running image was
  `r99-canary-990c0780584f`. Restore the latter explicitly for central rollback;
  do not blindly restart using the archived `.env` selector.
- The earlier OAuth gate copies still have SHA-256
  `9e1f622bd23c42b10eeecde145a3405e69cb84f14841607b0039247a216ca269`.

## Remaining external pool limitation

The real signed strategy request reached the deployed central provider, but
the configured pool could not return a proposal. Private diagnostics reduced
responses to safe categories: primary HTTP 429 (`provider_limited`), secondary
HTTP 401 (`token_revoked`). Normal forced refresh succeeded for secondary but
the provider still rejected the renewed session as revoked. The secondary
account must be reconnected; primary must regain available quota. No tokens,
raw OAuth diagnostics or customer prompts were printed. The pool fallback is
implemented and protocol-tested, but successful live pool generation has **not**
been verified. Full-Flash Gemini generation was verified independently.
