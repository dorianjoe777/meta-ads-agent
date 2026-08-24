---
name: campaign-editing
description: Resolve and edit existing Meta campaigns from natural language, including budget, pause, resume, activation scheduling, and deletion. Use only for an existing object, not new campaign creation.
---

# Campaign Editing

The runtime compiles this procedure before exposing the relevant campaign-editing tools. Follow that compact procedure and the current schema; do not add a read-file unlock turn.

## Resolve scope naturally

Use the full conversation and fresh Meta inventory when needed. A newly named campaign starts a new scope even without words such as “now” or “another”. Pronouns continue the previous campaign only when the reference is unambiguous. This supports any number of campaigns in one session and also works after `/reset` by resolving against live inventory.

## General edits

For ordinary edits call `mcp_admira_edit_campaign` with the buyer's complete current wording in `change_request` and a natural `campaign_reference` when present. Do not build a replacement campaign payload. Preserve every unspecified field. The tool stages the exact diff and controls verification.

## Specialized operations

- Budget: use `mcp_admira_stage_budget_change` with the exact real campaign ID, amount in major account-currency units, and the buyer-facing currency quote. Never multiply by 100 or convert currencies. If the spoken currency differs from the ad account currency, ask the buyer rather than choosing an exchange rate.
- Pause/resume: use the exact campaign ID with the matching tool.
- Scheduled activation: require buyer authorization to spend, final creatives, exact local date/time, and timezone.
- Delete/archive: require exact scope and approval; never silently delete active, old, or external campaigns.

## Completion and retries

Staged or pending is not applied. Claim completion only after execution and live read-back. Correct at most one purely technical issue from already verified facts. If a retry needs a new buyer choice, approval, changed currency, or invented field, stop and ask; never loop through repeated mutations.
