---
name: meta-analysis
description: Analyze real Meta Ads performance, profitability, fatigue, winners, losers, and creative experiments without inventing data or declaring premature winners. Use for account performance questions and catch-ups.
---

# Meta Analysis Skill

Use this skill when the buyer asks what is happening in the Meta Ads account, asks for ROAS, CPA, CTR, winners, losers, fatigue, daily status, or a catch-up.

## Rules

- First call `mcp_admira_get_real_meta_context`. This tool performs a live synchronization; do not answer current-state questions from workspace memory alone.
- During that live read, verify that each active campaign's dashboard `metric_profile` matches the real objective/event. If it is generic, wrong, or missing a business-important outcome, call `mcp_admira_set_campaign_metric_priorities` before finishing the analysis.
- Meta is the source of truth for current existence, status, budget, delivery, spend, ad sets, ads and live configuration. Durable/local memory is only context and may be stale, incomplete, or missing because a prior turn did not persist correctly.
- Compare the live inventory with saved campaigns, recent actions, approvals and experiments. If they disagree, state the discrepancy and prefer the object currently verified by Meta.
- Never interpret an empty campaign list as “there are no campaigns” unless `live_sync.ok` is true and the inventory/data-quality response is complete. If synchronization failed or is partial, say the live read is incomplete and inspect the campaign, ad-set and ad inventories plus directly verified known campaign IDs before reaching a conclusion.
- Do not require the buyer to remember or type an exact campaign name merely to inspect the account. Enumerate live objects and identify the likely campaign from ID, status, update time, ads/creatives and the current conversation.
- If `metrics_source.is_real_meta_data` is not true, do not cite campaign names, ROAS, CPA, CTR, winners, losers, budgets, or fatigue.
- If there is no real Meta data, distinguish “not connected” from “live synchronization failed”; never turn a backend read failure into a claim that the account is empty.
- If real Meta inventory exists but insights are empty or all delivery metrics are zero, you may enumerate the created campaigns/ad sets/ads and their statuses. Say clearly that there is not enough delivery/performance data yet to judge winners, losers, CPA, ROAS, fatigue, or scaling.
- Explain in beginner-friendly Latin American Spanish.
- End with one clear next step.
- For a creative test, call `mcp_admira_list_experiment_reviews` before naming a winner. Respect its evidence status and next review date.
- If a due checkpoint must be run manually, call `mcp_admira_run_due_experiment_reviews`; do not run a future checkpoint early.
- Separate objective types: sales use CPA/ROAS and store outcomes; leads use CPL/lead volume; messages use cost per conversation. Never mark a lead/message campaign as losing because revenue is zero.
- Treat CPA as unknown when conversions are zero. Require mature runtime, spend, attribution lag, fresh data, and no learning/edit cooldown before proposing a cut or pause.
- Treat Shopify aggregates as business truth when connected and Meta as attribution evidence. A mismatch is a tracking/attribution investigation, not permission to change spend.
- Diagnose fatigue from relative CPA deterioration plus CTR, frequency, reach/delivery, and creative age. Frequency alone is not a verdict.
- Use `mcp_admira_list_optimization_research` only for relevant hypotheses. Official guidance has priority; community claims are anecdotal and can only justify a controlled experiment.
- For conversion, lead, message, or website-action campaigns, call `mcp_admira_review_signal_quality` when the buyer asks why delivery is poor, why Meta is finding the wrong people, why conversions are not attributed, or whether the event setup is ready.
- Treat signal quality as a first-class diagnosis before blaming audience or creative: correct optimization event, Pixel/Dataset, Conversions API, Event Match Quality, AEM/event eligibility, event prioritization, and enough conversion volume.
- If a signal issue is outside Admira's direct control, explain the exact Events Manager/server/ecommerce setup step. Do not pretend the agent fixed CAPI, EMQ, AEM, or event priority unless a product tool confirms it.

## Tone

Use decisive but honest language:

- "Hice el analisis..."
- "Lo importante hoy es..."
- "Mi sugerencia es..."
- "Lo puedo preparar para aprobacion si quieres."
