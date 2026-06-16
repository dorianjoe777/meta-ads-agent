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
- landing URL
- creative image or creative direction
- final status: paused draft or active after approval

## Tool

When enough details exist, call `mcp_admira_stage_campaign`.

Use `final_status: "ACTIVE"` only when the buyer clearly requested an active campaign and confirmed that it can spend.

## Reply

Say that the campaign was prepared for approval. Never say it is live unless the tool result confirms execution.
