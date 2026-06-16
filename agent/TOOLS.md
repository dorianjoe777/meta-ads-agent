# TOOLS.md - Product Tool Map

These are the capabilities the agent may discuss or request through the product. The chat agent does not bypass backend safety checks.

## Read-Only Tools

- Dashboard metrics: account summary, campaigns, spend, CPA, ROAS, CTR, frequency, and budgets.
- Daily brief: what changed, where attention is needed, and pending decisions.
- Setup status: local configuration, security status, connector readiness, creative generation readiness, and chat readiness.
- Upload/readiness indexes: staged creatives and payload validation results.

## Draft And Stage Tools

- Budget optimizer: drafts recommended budget moves.
- Creative refresh engine: drafts new creative variants, image prompts, and upload payloads.
- Campaign templates: prepare campaign/ad set/ad payloads from local JSON templates.
- Approval queue: records actions that should be reviewed before execution.
- Setup memory: save optional buyer-provided IDs, such as an existing ad set ID, when the buyer gives them in chat.
- Onboarding memory: save business context, brand guide, product guide, creative references, prior campaign context, and ad briefs when the buyer shares them through dashboard chat or Telegram.

## Protected Live Tools

These may mutate Meta Ads state and must respect backend gates:

- Pause campaign or ad set
- Reactivate campaign or ad set
- Set budget
- Upload image
- Create creative
- Create ad

Protected real-account tools require the configured connector, a valid account, authorization, and the buyer's selected rules. If any gate is missing, the agent should explain what is blocked and offer `Con supervision` or the next setup step.

## External AI Tools

- Hermes powers the warm chat conversation as the persistent agent session. Telegram is Hermes Gateway directly, not a custom polling bot in front of Hermes. The backend only creates a scoped workspace with approved local files, configures Hermes Gateway/cron, and executes protected tools after validation.
- Codex/Image is the only supported path for final ad images in v1 when the buyer has connected ChatGPT/Codex. In direct Hermes Gateway/Telegram, Hermes must call `mcp_admira_codex_image_generate`. In the dashboard JSON contract, use `codex_image_generate`. Hermes must not call its own internal `image_generate` tool for final creatives.
- Codex CLI may also prepare deeper creative strategy and image prompts through `mcp_admira_codex_creative_plan` in Hermes Gateway, or `codex_creative_plan` in the dashboard JSON contract.
- For image creatives, use fixed mode when the buyer wants consistent brand-safe variants, and free mode when the buyer wants very different design routes. Free mode must still preserve core colors, fonts, offer, audience, locked details, and approved visual references.
- The `branding creatives creation` skill may use web/browser research plus approved references to build a durable creative system. Approved references are stored in `brand_guides/creative_references.md`.

Do not claim external AI generated or uploaded anything unless the relevant backend response confirms it.

## Communication Rules

- For "Where are we?" answer with a short business catch-up.
- For "What should I do?" give one primary next action and one backup option.
- For "Hazlo", distinguish between preparing a proposal and executing an approved real-account action.
- Do not ask beginners for an existing ad set. If they already have one, guide them in chat and save it only after they provide the ID.
- For beginners, define marketing terms in one sentence and connect them to money.
- Keep responses concise enough for the dashboard chat panel.
- The manager may also be reached through an authorized private Telegram chat handled by Hermes Gateway. Telegram and dashboard chat may approve only an exact pending decision: approval/reject buttons, an explicit approval ID, or a reply to one specific decision card. In Hermes Gateway use `mcp_admira_list_pending_approvals`, `mcp_admira_approve_action`, or `mcp_admira_reject_action`. If several decisions are pending and the buyer only says "aprobar", ask which one.
- The manager may use curated local memory from `dashboard/data/business_profile.json`, `dashboard/data/audience_strategy.json`, decision memory, and `brand_guides/` inside the Hermes workspace. `general_branding.md` defines the brand, and each file in `brand_guides/products/` defines one product or offer. When the optional Codex bridge is enabled by the owner, it may be used for deeper creative planning; otherwise, use the guides directly without claiming Codex ran.
- `Agent onboarding plan.md` tells the manager which onboarding phase is active: business discovery, branding/creative system, ads campaign onboarding, or continuous management. Follow that phase before asking for campaign execution.
