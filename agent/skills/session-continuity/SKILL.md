---
name: session-continuity
description: Recover Admira IA conversation context after Telegram/Hermes history cleanup, gateway restart, product update, or a fresh runtime session. Use before greeting, onboarding, or continuing any in-progress work.
---

# Session Continuity Skill

Use this skill before any first greeting, onboarding question, or "new session" response.

## Required memory files

Read these workspace files when present:

- `memory/continuity_status.json`
- `memory/Conversation continuity.md`
- `memory/latest_day_context.md`
- `memory/active_workflow.json`
- `CURRENT_CONTEXT.json`
- `data/business_profile.json`
- `memory/Agent onboarding plan.md`
- `memory/Ads campaign onboarding.md`
- `memory/recent_actions.json`
- `memory/pending_approvals.json`
- `memory/creative_refreshes.json`
- `memory/content_asset_library.json`
- `memory/content_strategy.md`
- relevant `brand_guides/` files

## Resume behavior

- If persistent memory or an active workflow exists, do not introduce yourself as if this were the first conversation.
- Do not repeat the initial ads-experience/technical-detail question unless memory proves it is missing.
- Continue from the next missing/actionable step, not from the beginning of onboarding.
- If daily content settings, content strategy, or content assets exist, continue with that context instead of asking again whether uploaded files/logos/references exist.
- Mention one concrete remembered item only when it helps the buyer feel continuity.
- Use a short phrase like “Retomo donde quedamos…” only when the session truly feels fresh after cleanup/update.

## Last day context

`memory/latest_day_context.md` summarizes the most recent local day with activity, checking today first and then the most recent day within the last 7 days. Treat it as the best short-term memory after Hermes session cleanup.

`memory/active_workflow.json` is the machine-readable state. Prefer its `next_step`, `last_user_message`, `last_agent_message`, pending approvals, recent blockers, and workflow phase before asking a repeated question.
