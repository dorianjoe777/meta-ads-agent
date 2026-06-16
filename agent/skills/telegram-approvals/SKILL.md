# Telegram Approvals Skill

Use this skill when the buyer asks from Telegram or dashboard chat to approve, reject, list pending decisions, or continue with a staged action.

## Tools

- `mcp_admira_list_pending_approvals`
- `mcp_admira_approve_action`
- `mcp_admira_reject_action`

## Rules

- Approval requires one exact pending approval.
- If several approvals are pending and the buyer says only "aprobar", list the choices and ask which one.
- Active campaign creation requires the exact confirmation phrase shown by the product approval card.
- Never invent approval IDs.
- Never approve your own recommendation without the buyer's explicit decision.
