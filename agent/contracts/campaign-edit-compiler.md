# Campaign edit compiler contract

This contract applies to `admira_edit_campaign`. The buyer speaks in ordinary
language; the server resolves the campaign against the current Meta inventory
and the compiler returns only a field-level diff for existing IDs.

## Identity and state

- Resolve the reference in the current buyer message before inheriting any
  previous campaign context.
- A unique name, city, destination, product, or exact Meta ID may identify a
  campaign. A different uniquely matched campaign always opens a different
  edit draft, even when the buyer does not say “another campaign” or “now”.
- Use the previous campaign only for pronouns such as “esa”, “la misma”,
  “también”, or when the current message contains no campaign reference.
- Never choose among tied campaigns. Return `ready=false` and list the
  ambiguous target in `missing_fields`.
- Never merge drafts from different campaign IDs, ad accounts, or chats.
- There is no two-message or two-campaign limit. A chat may alternate among any
  number of live campaigns; every campaign ID keeps its own independent draft.
- Within one campaign draft, requests are chronological. If a later request
  changes the same field again, the later explicit value replaces the earlier
  one; unrelated earlier changes remain in the draft.

## Allowed in-place differences

Campaign operations may change only `name`, `daily_budget`,
`lifetime_budget`, and the exact buyer `budget_confirmation`.

Ad-set operations may change only `name`, `daily_budget`, `lifetime_budget`,
`budget_confirmation`, `start_time`, `end_time`, `age_min`, `age_max`,
`genders`, `locations`, `interest_ids`, `targeting_mode`, and `placements`.

Ad operations may change only `name`, `status=PAUSED`, and creative fields
(`primary_text`, `headline`, `description`, `link_url`,
`call_to_action_type`, `image_path`, `image_hash`, `image_url`, `video_id`,
`prefilled_message`, and `welcome_message`). Active delivery is a separate
approval-protected operation and must not be emitted by this compiler.

Changing objective, destination, Page, ad account, conversion event, budget
level (CBO versus ABO), or deleting/adding structure is not an in-place edit.
Return a precise unsupported/missing field so the manager can stage a
replacement workflow later.

## Safety

- Emit only existing campaign, ad-set, and ad IDs from the supplied snapshot.
- Emit only fields explicitly requested in the accumulated buyer messages.
- Preserve all unspecified fields; the server merges targeting changes with the
  live ad-set targeting and read-backs the final Graph object.
- A budget must retain the buyer's exact amount and currency. The server, not
  the model, converts major units to Meta's account-specific minor units.
- Never invent a location or interest ID. Use a live Meta catalog result or
  refuse the edit.
- The compiler never calls Meta and never creates media. The server applies the
  diff only after the buyer's approval and verifies every affected object.
