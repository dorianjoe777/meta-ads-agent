---
name: meta-account-connection
description: Connect Facebook through OAuth, list authorized ad accounts and Pages, persist the buyer's selected workspace, and read current Meta inventory. Use for connection, selection, account/Page switching, or current-account truth.
---

# Meta Account Connection

The runtime compiles this procedure before exposing the relevant connection tools. Follow that compact procedure and the current schema; do not add a read-file unlock turn.

## Choose the operation

- Need current campaigns, status, performance, account currency, account timezone, or selected Page/account truth: call `mcp_admira_get_real_meta_context`. Do not call it for an unrelated greeting or creative conversation.
- Need to know whether Facebook is connected or which accounts/Pages OAuth exposed: call `mcp_admira_get_meta_oauth_workspaces`.
- OAuth is genuinely absent: call `mcp_admira_start_meta_oauth_connection` and send its visible URL. Do not ask for a token or send terminal commands.
- Buyer chooses an account and Page from the returned inventory: call `mcp_admira_select_meta_oauth_workspace` with those exact IDs. Resolve a natural name or numbered choice against the displayed inventory; never invent IDs.

## Text-only selection

Communicate only through ordinary chat text. Never use `clarify`, inline choice cards, approval cards, or account/Page buttons. List every returned ad account and every publishable Page with short numbers and names, without exposing tokens. The buyer may answer by number, name, approximate spelling, or a natural phrase; resolve the meaning against the displayed inventory.

Require an explicit choice for both the ad account and the Page. If the buyer specifies only one, ask one short text question for the missing asset. Never auto-select the first Page, never infer the missing half of the pair, and never call the selection tool until both choices are unambiguous. Treat selection as successful only when the tool returns both `selected: true` and `verified_persisted: true`.

If the selection tool rejects authorization, do not invent a Meta outage or ask for a chain of generic confirmations such as “sí”, “sí, usar estos”, and “ok”. State plainly that the pair was not saved and ask once for the exact account and Page by their displayed names or numbers. A generic confirmation is sufficient only when the backend already reports `authorized_pending_persistence`; otherwise it does not identify a pair.

## Persistence and continuation

A successful selection is durable across `/reset`, `/restart`, gateway restarts, and model changes. Use it silently afterward. Ask again only when the buyer requests a switch or the backend reports that the binding is missing, inaccessible, or no longer authorized.

After sending an OAuth URL, the next “Listo/Done” means only “check OAuth completion”. List the workspaces and continue selection; do not route that acknowledgement to campaigns, images, or approvals.

## Truth

OAuth authorization, workspace selection, and live campaign synchronization are different states. A transient Graph read failure does not mean Facebook is disconnected. Preserve structured Meta error details for support and never describe an empty partial response as proof that nothing exists.
