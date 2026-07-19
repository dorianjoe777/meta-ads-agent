# Telegram Approvals Skill

Use this skill when the buyer asks from Telegram or dashboard chat to approve, reject, list pending decisions, or continue with a staged action.

## Tools

- `mcp_admira_list_pending_approvals`
- `mcp_admira_approve_action`
- `mcp_admira_reject_action`

## Rules

- Approval requires one exact pending approval.
- Keep approval IDs internal. Never show them in buyer-facing text.
- A plain `aprobado` refers to the most recent proposal/card just presented. If the buyer names or replies to an older proposal, use that exact one; if the intended item is genuinely unclear, show named choices without IDs.
- Campaign activation/resume requires the short confirmation phrase shown by the product approval card: `Sí, activar`. No ID is appended.
- Never invent approval IDs.
- Never approve your own recommendation without the buyer's explicit decision.
