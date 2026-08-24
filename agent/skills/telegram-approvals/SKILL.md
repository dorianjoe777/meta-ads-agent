# Telegram Approvals Skill

Use this skill when the buyer asks from Telegram or dashboard chat to approve, reject, list pending decisions, or continue with a staged action.

## Tools

- `mcp_admira_list_pending_approvals`
- `mcp_admira_approve_action`
- `mcp_admira_reject_action`

## Rules

- Approval requires one exact pending approval.
- Keep approval IDs internal. Never show them in buyer-facing text.
- A plain `aprobado` refers to the most recent visible proposal just presented. If the buyer names or replies to an older proposal, use that exact one; if the intended item is genuinely unclear, list named choices in ordinary text without IDs.
- Campaign activation/resume requires the short natural-language confirmation phrase `Sí, activar`. No ID is appended.
- Never use `clarify`, question cards, selection cards, or approval/reject buttons. Present every proposal and any ambiguous choices as ordinary chat text.
- Never invent approval IDs.
- Never approve your own recommendation without the buyer's explicit decision.
