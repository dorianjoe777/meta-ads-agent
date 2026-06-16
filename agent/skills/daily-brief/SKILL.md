# Daily Brief Skill

Use this skill for the morning brief, "lectura diaria", "resumen diario", or when the buyer asks "que debo vigilar hoy".

## Tool

Call `mcp_admira_run_daily_brief`.

## Output Shape

Write a short Telegram-friendly brief:

1. What changed in the last few days.
2. What campaign, ad set, or creative needs attention.
3. What still looks healthy.
4. What action you would prepare for approval.

Always end exactly with:

`¿Tienes alguna pregunta?`

## Data Rules

- Only use real Meta data from `mcp_admira_get_real_meta_context` or the daily brief tool result.
- If real Meta data is missing, say that clearly and do not use demo examples.
