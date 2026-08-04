---
name: meta-campaign-execution
description: Execute or stage Meta campaigns safely through Admira IA tools and Meta Graph: preflight, direct publishing/hidden posts, lead forms, promoted objects, budgets, bidding, statuses, approvals, and error handling.
---

# Meta Campaign Execution Skill

Use this skill when the campaign strategy is ready and the buyer asks to prepare, create, publish, approve, or retry a Meta action.

## Safe execution

- Use `mcp_admira_review_signal_quality` before conversion, lead, message, or website-action campaigns.
- Use `mcp_admira_preflight_campaign` for serious launches or advanced targeting/creative setups.
- Use `mcp_admira_stage_campaign` to create or stage campaigns. For fully `PAUSED` no-spend setups, the backend may execute the Meta creation immediately after the buyer asks for it; for `ACTIVE` or spend-capable changes, it stages an approval.
- Creating a complete campaign/ad set/ad structure in `PAUSED` status is allowed after the buyer asks for it; it should not require a second approval just to create non-spending Meta objects. The protected approval is activation, resuming, publishing active, budget increases, customer-data sends, or any action that can spend or materially mutate a live running account.
- New campaigns requested as `ACTIVE` or any spend-capable change require explicit approval/confirmation. Do not claim execution unless a tool confirms it.
- Preparing a paused draft, preflight, retry, or approval-ready staging is the normal next step after the buyer asks for it. Do not ask a redundant “should I prepare it?” confirmation unless an unresolved choice would materially change what is staged.
- If paused creation fails because a technical field such as pixel/event/promoted_object is missing or invalid, do not ask “do you want me to continue?” The buyer already asked for creation. Fix the payload from known context when safe, retry through the tool, or give the exact blocker and the one missing detail needed.

## Scheduled activation

When the buyer asks to activate an existing campaign at a future time, never create a generic reasoning cron and never place a campaign name/local draft ID in a free-form reminder.

- Read real Meta context first and resolve exactly one numeric Meta `campaign_id`.
- Confirm the buyer explicitly authorizes spend at the scheduled time, the final creatives are ready (not temporary placeholders), the budget currently configured is the expected one, and the buyer timezone/date-time is unambiguous.
- Then call `mcp_admira_schedule_campaign_activation` with `campaign_id`, `campaign_name`, `scheduled_at`, `timezone`, `buyer_authorized: true`, `active_spend_confirmed: true`, `creative_ready_confirmed: true`, and a budget snapshot.
- The scheduling request itself is the activation approval. Do not request a second approval when the due time arrives.
- This product tool executes deterministically without inference, verifies the campaign identity again, activates only that campaign, and confirms `ACTIVE` from Meta. Do not substitute `mcp_admira_resume_campaign` inside a generic cron.

## Direct publishing

When Publicación directa is connected, prefer native unpublished Page posts for image/static ads, then create the ad from `object_story_id`. Present this as a product capability, not a hack.

If the publishing token/page access fails, explain the connection problem simply and keep the campaign prepared for retry.

## Partial campaign cleanup

Do not leave failed campaign-creation attempts scattered in Meta Ads Manager when Admira created them.

- If a paused campaign creation fails after Admira already created the campaign/ad set, the backend may automatically roll back the partial campaign. Tell the buyer plainly: “Meta stopped the setup, and I cleaned the incomplete paused campaign so it does not stay abandoned.”
- If the automatic cleanup fails, tell the buyer the campaign ID and offer to clean it with `mcp_admira_delete_campaign`.
- Use `mcp_admira_delete_campaign` only with an exact campaign ID and only for buyer-approved cleanup/deletion. Never silently delete active campaigns, old campaigns, or campaigns not clearly created by the failed Admira attempt.
- Prefer cleanup over leaving duplicate partial campaigns, but prefer pause/retry over deletion when the campaign has real delivery history, spend, or uncertain ownership.

## Video website completion modes

For video ads that send traffic/conversions to a website, avoid claiming that an empty ad can be created. Meta requires a creative before an ad exists.

Use one of these explicit staging modes:

- `manual_creative_completion: true`: create/reuse campaign and ad set only, paused, then return a checklist for completing the video creative in Ads Manager.
- `create_placeholder_ad: true` with `placeholder_ad_count` and, when known, `placeholder_ad_names`: create paused ad(s) with temporary static dark/placeholder media, saved copy/headline/CTA/website URL, and names already filled. The buyer replaces the placeholder media with the corresponding final video and verifies/adjusts the final link in Ads Manager before activating.

Use placeholder ads only for video creative completion, when the buyer wants this convenience or when it clearly saves time for several ads. If no provisional image exists, the backend may create a plain temporary placeholder image. Say plainly that the placeholder must not be activated. Do not use this fallback for normal static-image ads.

## Payload reminders

Pass justified fields only: objective, budget level, daily/lifetime budgets, statuses, placements, promoted object, optimization goal/event, billing event, bid strategy, image/video/story fields, CTA/link, message starter fields, lead form ID, direct publishing flag, and video completion fields (`manual_creative_completion`, `create_placeholder_ad`, `placeholder_ad_count`, `placeholder_ad_names`) when appropriate.

## Interest and Advantage+ verification

- Never send free-form interest names as if they were valid targeting. Search first with `mcp_admira_search_meta_targeting`, then pass `targeting_interests` as objects containing the exact live Meta `id` and `name`.
- The backend applies a second server-side guard: interest IDs must be decimal IDs returned by Meta, and the live catalog is rechecked immediately before the first Graph mutation. Never append suffixes, repair IDs from memory, or continue when the catalog cannot confirm them. Explicit countries and age bounds are normalized and validated; an explicit invalid value must fail instead of defaulting to US or 18–65.
- For Advantage+ audience with interest suggestions, pass `targeting_mode: advantage_plus` or `targeting_automation: {"advantage_audience": 1}`. For intentionally strict/manual detailed targeting, pass `targeting_mode: manual` only when that strategy is supported and justified.
- When interests are present and no mode is explicitly chosen, the backend defaults to Advantage+ suggestions (`targeting_automation: {"advantage_audience": 1}`) so Meta receives the required flag. Preserve an explicit manual/strict choice as `0`; never omit the field from a detailed-interest ad set.
- With Advantage+ audience enabled, send an effective `age_max` of 65. A lower requested maximum is only a suggestion and must not be sent as an enforced cap. If the buyer requires a strict lower maximum, switch to manual targeting (`advantage_audience: 0`) before staging and explain the tradeoff.
- Campaign/ad-set creation success is not targeting verification. After the ad set is created, the backend rereads it from Meta. If the result does not confirm all requested interest IDs and the requested Advantage+ flag, treat creation as incomplete; do not claim it worked. For an existing ad set, call `mcp_admira_inspect_adset_targeting` with its numeric ID.
- Describe confirmed state precisely: “Meta returned these interest IDs in the live ad-set targeting, with Advantage+ audience enabled/disabled.” Never claim a value is visible under a particular Ads Manager UI heading unless it was actually observed there; UI labels and placement can change independently of Graph state.

Budgets are interpreted in the connected ad account currency; do not assume USD.
