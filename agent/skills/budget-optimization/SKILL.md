# Budget Optimization Skill

Use this skill when the buyer asks to raise, lower, move, protect, pause spend, scale, or optimize budgets.

## Rules

- First call `mcp_admira_get_real_meta_context`.
- If real Meta data is missing, do not recommend exact budget moves from demo data.
- Use `memory/profitability_rules.json` and `memory/decision_memory.json` when available.
- Explain why the move makes sense in simple terms.

## Tools

- Use `mcp_admira_stage_budget_change` to prepare a budget change.
- Use `mcp_admira_pause_campaign` only for exact campaign pause requests.
- Use `mcp_admira_resume_campaign` only for exact campaign resume requests.

## Approval

If guardrails require approval, tell the buyer the action is prepared for approval. Do not claim it was executed.
