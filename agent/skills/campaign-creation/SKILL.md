# Campaign Creation Skill

Use this skill when the buyer asks to create, launch, prepare, or publish a Meta Ads campaign, ad set, creative, or ad.

## Safety Rules

- New campaigns always require approval.
- If the buyer wants the final ad active and able to spend, require explicit active-spend confirmation.
- Chat can stage a campaign but cannot silently approve it.
- If information is missing, ask one clear question at a time.

## Minimum Details

Collect:

- product or offer
- objective
- target audience/location
- daily budget
- target CPA/CPL when known
- landing URL
- saved creative test brief with distinct hypotheses, formats, and variation count
- approved creative assets or a production plan
- final status: paused draft or active after approval

Do not reduce the creative strategy to one image. Check that the proposed concurrent creative count fits the budget; keep additional concepts in a backlog rather than starving every test.

## Tool

When enough details exist, call `mcp_admira_stage_campaign`.

Use `final_status: "ACTIVE"` only when the buyer clearly requested an active campaign and confirmed that it can spend.

## Reply

Say that the campaign was prepared for approval. Never say it is live unless the tool result confirms execution.
