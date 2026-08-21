---
name: lead-form-management
description: List, create, verify, or manually stage native Meta Instant Forms. Use when a buyer needs the form itself; campaign creation that consumes a verified form remains in meta-campaign-execution.
---

# Lead Form Management

Read this skill before calling `mcp_admira_list_lead_forms`, `mcp_admira_create_lead_form`, or `mcp_admira_stage_lead_form`.

## Procedure

1. Call `mcp_admira_list_lead_forms` first to find an existing suitable form and avoid duplicates.
2. If creation is requested, collect in one compact question only what is genuinely missing: internal form name, approved questions, and public privacy-policy URL. The active selected Page is used automatically unless the buyer explicitly identifies another authorized Page.
3. Call `mcp_admira_create_lead_form` once with complete schema arguments. Never call it with `{}` or wrap the questions in invented containers.
4. Success requires a real verified `lead_gen_form_id` read back from Meta. The form creates no campaign and spends no money.
5. Use `mcp_admira_stage_lead_form` only after direct creation returns a real Meta permission or capability blocker. Give the exact manual blueprint, then list forms again after the buyer publishes it.

Do not interpret an unrelated license, OAuth, model, or provider error as a Meta form capability error. A user-token versus Page-token problem must be reported from the actual structured Meta result, not guessed.
