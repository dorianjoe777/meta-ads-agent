# Budget Optimization Skill

Use this skill when the buyer asks to raise, lower, move, protect, pause spend, scale, or optimize budgets.

## Rules

- First call `mcp_admira_get_real_meta_context`.
- If real Meta data is missing, do not recommend exact budget moves from demo data.
- Use `memory/profitability_rules.json` and `memory/decision_memory.json` when available.
- Explain why the move makes sense in simple terms.
- Before recommending scale, pause, or budget movement on a conversion-focused campaign with weak or confusing results, call `mcp_admira_review_signal_quality`. Do not burn budget trying to optimize spend if the event setup may be teaching Meta the wrong signal.
- If CAPI, Event Match Quality, AEM/event eligibility, event priority, Pixel/Dataset, or event volume are weak/unknown, propose the setup fix or a paused test before budget changes. Tracking/reliability problems are not solved by raising spend.

## Tools

- Use `mcp_admira_review_signal_quality` for event/signal readiness.
- Use `mcp_admira_stage_budget_change` to prepare a budget change.
- Use `mcp_admira_pause_campaign` only for exact campaign pause requests.
- Use `mcp_admira_resume_campaign` only for exact campaign resume requests.

## Approval

If guardrails require approval, tell the buyer the action is prepared for approval. Do not claim it was executed.
