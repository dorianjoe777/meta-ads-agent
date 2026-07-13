---
name: measurement-optimization
description: Analyze and optimize real Meta Ads performance for Admira IA: daily briefs, signal quality, winners/losers, budgets, creative experiments, verified lead feedback, and follow-up decisions.
---

# Measurement and Optimization Skill

Use this skill for performance questions, daily briefs, optimization, creative test decisions, budget changes, and verified lead/outcome feedback.

## Data truth

Use real Meta data only when `CURRENT_CONTEXT.json` or a tool confirms it. Treat Shopify/store aggregates as business truth when connected and Meta as attribution evidence. Do not invent winners, ROAS, CPA, or fatigue.

## Adaptive dashboard metrics — mandatory audit

After every live synchronization, audit each active campaign's `metric_profile` and `priority_metrics` against its real objective, ad-set optimization goal, promoted event, funnel and the buyer's business priorities. The dashboard infers a safe default automatically, but you are responsible for improving it when conversation context knows more.

Use `mcp_admira_set_campaign_metric_priorities` when a campaign is new, its objective/event changes, the current profile is generic/wrong, or the buyer confirms more useful outcomes. Choose up to six KPIs. Examples:

- sales: spend, purchases, cost per purchase, ROAS, initiated checkouts, cost per checkout;
- leads/forms: spend, leads, cost per lead, landing-page views, CTR;
- WhatsApp/Messenger: spend, conversations, cost per conversation, clicks, CTR;
- traffic: spend, landing-page views, cost per landing-page view, clicks, CPC;
- awareness: spend, reach, impressions, CPM, frequency;
- video: spend, ThruPlays, cost per ThruPlay, completed views.

Never select revenue/ROAS as the primary health signal for leads or messages merely because those are familiar advertising metrics. Never edit UI source code or arbitrary files for a buyer-specific preference; save the campaign profile through the product tool so it survives reset/update safely. This dashboard-only change is safe and does not require spend approval.

## Decisions

Before recommending pause, scale, refresh, or budget movement, check:

- maturity, spend, attribution lag, learning status, data freshness, and edit cooldown;
- objective type: sales, leads, messages, bookings, or awareness;
- signal quality and optimization event;
- active creative experiment evidence.

## Follow-up

After a real multi-creative launch with real Meta IDs, schedule adaptive experiment reviews. If evidence is insufficient, keep watching and say what will be checked next.

For verified signal mode, organize/dedupe leads first and ask the buyer only for exceptions and meaningful outcomes.
