---
name: meta-campaign-execution
description: Execute or stage Meta campaigns safely through Admira IA tools and Meta Graph: preflight, direct publishing/hidden posts, lead forms, promoted objects, budgets, bidding, statuses, approvals, and error handling.
---

# Meta Campaign Execution Skill

Use this skill when the campaign strategy is ready and the buyer asks to prepare, create, publish, approve, or retry a Meta action.

## Safe execution

- Use `mcp_admira_review_signal_quality` before conversion, lead, message, or website-action campaigns.
- Use `mcp_admira_preflight_campaign` for serious launches or advanced targeting/creative setups.
- Use `mcp_admira_stage_campaign` to prepare campaigns.
- Creating a complete campaign/ad set/ad structure in `PAUSED` status is allowed after the buyer asks for it; it should not require a second approval just to create non-spending Meta objects. The protected approval is activation, resuming, publishing active, budget increases, customer-data sends, or any action that can spend or materially mutate a live running account.
- New campaigns requested as `ACTIVE` or any spend-capable change require explicit approval/confirmation. Do not claim execution unless a tool confirms it.
- Preparing a paused draft, preflight, retry, or approval-ready staging is the normal next step after the buyer asks for it. Do not ask a redundant “should I prepare it?” confirmation unless an unresolved choice would materially change what is staged.

## Direct publishing

When Publicación directa is connected, prefer native unpublished Page posts for image/static ads, then create the ad from `object_story_id`. Present this as a product capability, not a hack.

If the publishing token/page access fails, explain the connection problem simply and keep the campaign prepared for retry.

## Video website completion modes

For video ads that send traffic/conversions to a website, avoid claiming that an empty ad can be created. Meta requires a creative before an ad exists.

Use one of these explicit staging modes:

- `manual_creative_completion: true`: create/reuse campaign and ad set only, paused, then return a checklist for completing the video creative in Ads Manager.
- `create_placeholder_ad: true` with `placeholder_ad_count` and, when known, `placeholder_ad_names`: create paused ad(s) with temporary static dark/placeholder media, saved copy/headline/CTA/website URL, and names already filled. The buyer replaces the placeholder media with the corresponding final video and verifies/adjusts the final link in Ads Manager before activating.

Use placeholder ads only for video creative completion, when the buyer wants this convenience or when it clearly saves time for several ads. If no provisional image exists, the backend may create a plain temporary placeholder image. Say plainly that the placeholder must not be activated. Do not use this fallback for normal static-image ads.

## Payload reminders

Pass justified fields only: objective, budget level, daily/lifetime budgets, statuses, placements, promoted object, optimization goal/event, billing event, bid strategy, image/video/story fields, CTA/link, message starter fields, lead form ID, direct publishing flag, and video completion fields (`manual_creative_completion`, `create_placeholder_ad`, `placeholder_ad_count`, `placeholder_ad_names`) when appropriate.

Budgets are interpreted in the connected ad account currency; do not assume USD.
