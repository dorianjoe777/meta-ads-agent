# Natural-language campaign editing

Admira treats every buyer message as a request to edit one exact live Meta
campaign. Hermes interprets the wording, but the backend owns identity,
state, validation, approval, execution, and Graph read-back.

## Conversation behavior

- A current-message campaign name, city, product, destination, or numeric Meta
  ID is resolved against live inventory before prior context is considered.
- A different unique campaign reference opens a separate draft automatically.
  The buyer does not need to say “now”, “another”, or any fixed phrase.
- Pronouns such as “esa”, “la misma”, or “también” continue the last
  unambiguous campaign for that Telegram chat and ad account.
- Ambiguous or missing references stop before mutation and return candidate
  campaign names/IDs. The backend never guesses.
- Drafts are isolated by chat, ad account, and campaign ID. A later request for
  the same field replaces the earlier requested value; unrelated changes stay.
- There is no fixed number of messages or campaigns per session. The buyer can
  alternate A → B → C → A → D; returning to A resumes only A's draft, while B,
  C, and D remain independent.

Example:

1. “En la campaña de abogados de Cartagena sube el presupuesto a 12 USD.”
2. “En la de Miami usa solo Instagram Stories.”

The second message resolves Miami from the current live inventory and creates
a Miami draft. It cannot overwrite or inherit the Cartagena payload.

## Deterministic boundary

`mcp_admira_edit_campaign` receives the exact natural-language message. The
server:

1. refreshes live Meta campaigns, ad sets, and ads;
2. resolves one campaign and rejects account mismatches;
3. writes a private campaign-scoped draft and Markdown audit summary;
4. asks the configured compiler chain for a field-level diff only;
5. validates every entity ID and field against allowlists;
6. validates budget amount/currency in major units and stores Meta API units;
7. creates one approval item without changing Meta;
8. on explicit approval, rereads all targets and rejects stale snapshots;
9. applies the exact Graph fields and reads every affected object back.

The compiler may interpret language, but it cannot choose arbitrary IDs,
change unsupported fields, bypass approval, or declare success.

## In-place versus replacement changes

Supported in-place edits include names, budgets, schedules, targeting,
placements, paused status, and ad creative text/link/media. Creative edits use
a replacement creative object and relink the existing ad because Meta
creatives themselves are immutable.

Objective, destination, Page, ad account, conversion event, budget level
(CBO/ABO), and structural additions/removals are not treated as in-place
edits. They must use a separately reviewed replacement/structure workflow.
Activation and spend remain separate approval-protected actions.

## Operational files

- Contract: `/app/agent/contracts/campaign-edit-compiler.md`
- Draft state: `/app/dashboard/data/campaign-edit-workflows/`
- Pending approvals: `/app/dashboard/data/pending_approvals.json`
- Runtime implementation: `/app/src/campaign_editing.py`

Draft files are private (`0600`). A pending revision for the same campaign
supersedes the previous pending revision; drafts for other campaigns remain
separate.

## First checks when editing fails

1. Confirm the selected Meta ad account still matches the campaign.
2. Confirm live inventory returns the campaign/ad-set/ad IDs and names.
3. Inspect the campaign-specific `draft.json` for resolution, compiler model,
   missing fields, operations, and preconditions.
4. Confirm the account currency and `budget_confirmation` agree.
5. Confirm no one changed the target in Ads Manager after approval was staged;
   stale preconditions intentionally block execution.
6. Inspect the approval result and Graph response/read-back mismatch. A failed
   read-back must never be presented as a successful edit.

Meta does not provide an atomic transaction across several campaign objects.
Admira therefore prechecks every target before the first write, stops on the
first Graph failure, records any already-applied IDs, and never reports full
success unless every requested read-back matches.
