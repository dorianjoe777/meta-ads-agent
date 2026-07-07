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
- New campaigns and spend-capable changes require approval. Do not claim execution unless a tool confirms it.

## Direct publishing

When Publicación directa is connected, prefer native unpublished Page posts for image/video ads, then create the ad from `object_story_id`. Present this as a product capability, not a hack.

If the publishing token/page access fails, explain the connection problem simply and keep the campaign prepared for retry.

## Payload reminders

Pass justified fields only: objective, budget level, daily/lifetime budgets, statuses, placements, promoted object, optimization goal/event, billing event, bid strategy, image/video/story fields, CTA/link, message starter fields, lead form ID, and direct publishing flag.

Budgets are interpreted in the connected ad account currency; do not assume USD.
