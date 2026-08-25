---
name: daily-brief
description: Build the Telegram-friendly daily Meta Ads brief from current live Meta data and adaptive creative-experiment checkpoints. Use for morning briefs, daily readings, summaries, or what to watch today.
---

# Daily Brief Skill

Use this skill for the morning brief, "lectura diaria", "resumen diario", or when the buyer asks "que debo vigilar hoy".

Before interpreting results, read the current Page-scoped business lifecycle and
strategic-plan artifact. These are separate states: `business_profile=review_required`
means the onboarding/business summary awaits confirmation and must never be described
as a strategic-plan draft. If `strategic_plan_status=missing`, say that no strategic
plan exists yet. Only if the plan itself is `proposed`/draft or `stale`, include a
short useful summary of it and remind the buyer that it is not yet the final
approved plan. If it is `confirmed`, use it as active context and never ask to
confirm it again. The business onboarding summary is a separate baseline; while
it is pending review, describe it as such, and once complete never re-request it.
The daily read is observational: new results, services, campaign changes or
recommendations never rewrite or invalidate the saved strategic plan. A plan
revision begins only after a direct buyer request to update that plan.

## Tool

Call `mcp_admira_run_daily_brief`.
Then call `mcp_admira_list_experiment_reviews` when creative tests are active or mentioned in the brief.

## Output Shape

Write a short Telegram-friendly brief:

1. What changed in the last few days.
2. What campaign, ad set, or creative needs attention.
3. What still looks healthy.
4. What safe paused work you already prepared, or what exact protected live action needs the buyer's confirmation now.
5. Which creative test is still collecting evidence, its provisional leader only when supported, and the exact next review date.
6. Data quality, Shopify/Meta reconciliation, signal quality, learning or cooldown holds, anomalies, and shadow-mode unlock progress when present.

Always end exactly with:

`¿Tienes alguna pregunta?`

## Data Rules

- Only use real Meta data from `mcp_admira_get_real_meta_context` or the daily brief tool result.
- Treat the current Meta inventory and insights as authoritative. Never infer what is active from memory, local campaign plans, created-campaign records, action logs, or old approvals.
- Treat the live Meta inventory and insights as authoritative for campaigns,
  spend, delivery and performance; the strategic plan supplies direction and
  hypotheses, not replacement KPI data.
- Do not list approvals as a routine daily section. Mention one only when it is the exact current activation or protected change the buyer is already discussing.
- If real Meta data is missing, say that clearly and do not use demo examples.
- Never turn an early delivery signal into a winner. Say "evidencia insuficiente" when the experiment tool does.
- A review recommendation is not an executed Meta change. Scaling, pausing, or budget changes still use the normal approval tools.
- Explain that Shopify is the business-truth source when connected and that Meta attribution can arrive later.
- Never recommend action from an incomplete current day, stale data, a learning campaign, or an active significant-edit cooldown.
- Mention signal quality when relevant: correct optimization event, Pixel/Dataset, Conversions API, Event Match Quality, AEM/event eligibility, event priority, and enough conversion volume. If one is unknown, say it is unknown and ask for the exact check instead of guessing.
