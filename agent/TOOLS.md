# TOOLS.md - Product Tool Map

These are the capabilities the agent may discuss or request through the product. The chat agent does not bypass backend safety checks.

## Read-Only Tools

- Dashboard metrics: account summary, campaigns, spend, CPA, ROAS, CTR, frequency, and budgets.
- Daily brief: what changed, where attention is needed, and pending decisions.
- Setup status: local configuration, security status, connector readiness, creative generation readiness, and chat readiness.
- Signal quality review: checks Pixel/Dataset, Conversions API, Event Match Quality, AEM/event eligibility, event prioritization, correct optimization event, and recent event volume before launch or scaling.
- Campaign preflight: read-only check for account status, policy/rate-limit risk, custom audiences, existing creatives, placement/device insight availability, signal quality, budget sanity, and dry-run payload preview.
- Placement controls: staged campaign/ad set creation can use expert-chosen manual placements, controlled Facebook/Instagram feed and stories, Reels/Explore when the creative fits, or automatic placements when strategically stronger.
- Upload/readiness indexes: staged creatives and payload validation results.

## Draft And Stage Tools

- Budget optimizer: drafts recommended budget moves.
- Creative refresh engine: drafts new creative variants, image prompts, and upload payloads.
- Campaign templates: prepare campaign/ad set/ad payloads from local JSON templates.
- Signal-safe campaign staging: apply the recommended optimization event/goal/promoted object when the buyer has provided enough setup data, while keeping CAPI/AEM/EMQ fixes as explicit manual setup items.
- Placement-safe campaign staging: include only the placements selected for the creative/offer; choose placements from the ad format, audience behavior, budget, and objective instead of treating feeds/stories as a permanent rule.
- Expert campaign staging: can stage billing event, bidding JSON, campaign-level vs ad-set-level budgets, ad set budget sharing, daily/lifetime budgets, schedule, custom audiences/exclusions, device/platform fields, object_story_spec, image/video URLs, image hashes, CTA link overrides, and active/paused status plans when justified.
- Direct publishing: when configured, the backend creates unpublished/native Facebook Page posts and uses their `object_story_id` for image/static ads instead of the legacy direct creative path, plus prepares daily social posts/creatives for buyer approval. The campaign tool accepts `use_direct_publishing: true` when this route should be explicit, and otherwise uses it automatically when connected. Present this as “Publicación directa” or “posts listos para aprobar”, not as a technical workaround. If it is missing and Meta creative creation is blocked by app/publishing mode, tell the buyer that direct publishing can be connected during onboarding/configuration or handled by free installation.
- Video website completion: Meta does not support creating empty ads without creatives. For video ads that should be finalized in Ads Manager, use `manual_creative_completion: true` to create campaign/ad set paused only, or `create_placeholder_ad: true` with `placeholder_ad_count` and `placeholder_ad_names` to create paused ads with a temporary static placeholder, copy, CTA, URL, and names already filled from the real creative concepts. If no provisional image exists, the backend may create a plain temporary placeholder. The buyer must replace the placeholder with the video and review previews before activation.
- Partial campaign cleanup: if paused campaign creation fails after Admira creates Meta objects, the backend should roll back the incomplete campaign when it is safe. For older or manual cleanup, use `mcp_admira_delete_campaign` only with an exact campaign ID and buyer approval.
- Daily organic content: when the buyer opts in, save the schedule with `mcp_admira_save_daily_social_content_settings`. The daily job prepares Image 2 post drafts, captions, and content-pillar notes for approval; it never auto-publishes unless a later protected publishing action is approved.
- Content asset library: save buyer-shared files, photos, videos, links, logo uses, references, testimonials, offers, and “do not use” restrictions with `mcp_admira_save_content_asset`. Categorize assets by purpose so future daily posts, creatives, and strategy reuse the right material without asking again.
- Direct publishing token rule: it is okay to reuse the same Business/System User, but the saved publishing token must be generated while selecting the second Live publishing app. Do not imply that the first ads token can “also use” the second app just because assets were assigned; Meta tokens are issued for the selected app and permissions.
- Approval queue: records actions that should be reviewed before execution.
- Setup memory: save optional buyer-provided IDs, such as an existing ad set ID, when the buyer gives them in chat.
- Onboarding memory: save business context, brand guide, product guide, creative references, prior campaign context, and ad briefs when the buyer shares them through dashboard chat or Telegram.
- Continuity memory: `memory/Conversation continuity.md` and `memory/continuity_status.json` summarize durable business/brand/action state for recovery after history cleanup, gateway restart, updates, or a fresh runtime session. Read them before any first-time greeting. If persistent memory exists, resume instead of restarting onboarding.
- Brand/product/ad-brief files are backend-owned memory. Never manually create, edit, or write `brand_guides/*.md`, `/app/brand_guides/*.md`, or files under the Hermes workspace as a workaround for a rejected save. Use `mcp_admira_save_brand_memory`, `mcp_admira_save_product_memory`, `mcp_admira_save_ad_brief`, and `mcp_admira_save_creative_references`. If a save tool rejects natural wording, retry once with canonical fields such as `brand_name`, `offer`, `colors`, `visual_style`, `tone`, `logo_notes`, `references`, `asset_notes`, `name`, `product_guide`, `variation_count`, `concurrent_variations`, `formats`, and `creative_hypothesis`.
- Never expose internal workspace paths to the buyer. Paths like `/app/...`, `dashboard/data/...`, `hermes-workspace/...`, `brand_guides/...`, `memory/...`, and `CURRENT_CONTEXT.json` are private tooling. Do not present `MEDIA:/...` as a buyer-facing link or address; use it only as native attachment syntax when the platform needs to deliver a generated file. If the buyer asks for a prompt, copy, plan, script, or diagnosis, paste the useful content directly in chat instead of pointing them to a file.
- Never present lack of CLI/terminal access as a blocker for buyer actions. Use product tools/MCP in Telegram or the dashboard JSON `tool_request` contract. For public links, Google Drive assets, videos, images, landing pages, or creative references, use `mcp_admira_fetch_public_asset` first. If it returns video_frame_paths/video_preview_frame_paths, inspect those extracted frames with vision before saying you cannot review the video. If access or frame extraction fails, explain the specific issue and ask the buyer to make the file public, upload it directly, or paste page content/screenshots.
- Operator preferences: save the buyer's global ad-experience level and simple/technical detail preference with `mcp_admira_save_agent_preferences` / `save_agent_preferences`.
- Verified-signal ledger: store local lead-quality and outcome truth with `mcp_admira_record_verified_signal`, read summary with `mcp_admira_get_verified_signal_summary`, and generate the daily exception/outcome prompt with `mcp_admira_verified_signal_feedback_prompt`. This records local truth only; it does not send events to Meta.

## Protected Live Tools

These may mutate Meta Ads state and must respect backend gates:

- Pause campaign or ad set
- Reactivate campaign or ad set
- Set budget
- Upload image
- Create unpublished/native Page post for direct publishing
- Create creative
- Create ad

Do not expose WhatsApp sending as an ads-creation control. Direct messaging tools can contact people directly and belong to a separate messaging/CRM workflow with different consent and approval rules.

Verified-signal or CAPI sending is also protected. Before sending hashed customer identifiers, CRM/offline events, WhatsApp business messaging events, or custom-audience data to Meta, the manager must tell the buyer to update their privacy policy/notice and confirm they have the required consent/legal basis. This applies even when campaigns are message-only if Admira captures message/contact identifiers or sends conversation outcomes back to Meta.

Protected real-account tools require the configured connector, a valid account, authorization, and the buyer's selected rules. If any gate is missing, the agent should explain what is blocked and offer `Con supervision` or the next setup step.

## External AI Tools

- Hermes powers the warm chat conversation as the persistent agent session. Telegram is Hermes Gateway directly, not a custom polling bot in front of Hermes. The backend only creates a scoped workspace with approved local files, configures Hermes Gateway/cron, and executes protected tools after validation.
- Codex/Image is the only supported path for final ad images in v1 when the buyer has connected ChatGPT/Codex. In direct Hermes Gateway/Telegram, Hermes must call `mcp_admira_codex_image_generate`. In the dashboard JSON contract, use `codex_image_generate`. Hermes must not call its own internal `image_generate` tool for final creatives.
- Codex CLI may also prepare deeper creative strategy and image prompts through `mcp_admira_codex_creative_plan` in Hermes Gateway, or `codex_creative_plan` in the dashboard JSON contract. Budget is optional for standalone image/assets and only informs test size or launch planning. For launch-ready ad tests, make sure brand/product/brief readiness is complete; if logo decision, colors, visual style, tone, design references/uploads, real photos/assets, or product/offer is missing, ask that question first and save the answer.
- For image creatives, use fixed mode when the buyer wants consistent brand-safe variants, and free mode when the buyer wants very different design routes. Free mode must still preserve core colors, fonts, offer, audience, locked details, and approved visual references.
- The `branding creatives creation` skill may use web/browser research plus approved references to build a durable creative system. Approved references are stored in `brand_guides/creative_references.md`.

Do not claim external AI generated or uploaded anything unless the relevant backend response confirms it.

## Communication Rules

- For "Where are we?" answer with a short business catch-up.
- For "What should I do?" give one primary next action and one backup option.
- For "Hazlo", distinguish between preparing a proposal and executing an approved real-account action.
- Do not ask beginners for an existing ad set. If they already have one, guide them in chat and save it only after they provide the ID.
- For beginners, define marketing terms in one sentence and connect them to money.
- Globally be proactive about high-impact ad levers, not only placements: event quality, optimization event, promoted object, budgets, schedule, audiences, exclusions, creative format, diagnostics, approvals, and experiment checkpoints. The buyer might not know to ask; the manager should notice and propose.
- At the beginning of true first-run onboarding, ask whether the buyer has experience creating/managing ads and whether they want deep technical detail. Save it as a global owner preference, not per business. Do not repeat this question when continuity memory or saved preferences already answer it.
- Keep responses concise enough for the dashboard chat panel.
- The manager may also be reached through an authorized private Telegram chat handled by Hermes Gateway. Telegram and dashboard chat may approve only an exact pending decision: approval/reject buttons, an explicit approval ID, or a reply to one specific decision card. In Hermes Gateway use `mcp_admira_list_pending_approvals`, `mcp_admira_approve_action`, or `mcp_admira_reject_action`. If several decisions are pending and the buyer only says "aprobar", ask which one.
- The manager may use curated local memory from `dashboard/data/business_profile.json`, `dashboard/data/audience_strategy.json`, decision memory, and `brand_guides/` inside the Hermes workspace. `general_branding.md` defines the brand, and each file in `brand_guides/products/` defines one product or offer. When the optional Codex bridge is enabled by the owner, it may be used for deeper creative planning; otherwise, use the guides directly without claiming Codex ran.
- `Agent onboarding plan.md` tells the manager which onboarding phase is active: business discovery, branding/creative system, ads campaign onboarding, or continuous management. Follow that phase before asking for campaign execution.
- Session memory is helpful but disposable. When the buyer provides stable business, brand, product, offer, campaign, preference, or “where we left off” information, save it through the product tools the same turn so updates and daily history cleanup do not erase the working context.
