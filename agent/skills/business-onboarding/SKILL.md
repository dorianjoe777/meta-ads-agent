# Business Onboarding Skill

Use this skill after Telegram is connected, when the buyer starts explaining the business, website, products, services, current struggles, goals, brand, or prior campaigns.

## Goal

Build durable memory so future chats feel continuous and useful.

## Workspace Files

Read and update through tools, not by editing arbitrary files:

- `data/business_profile.json`
- `memory/Conversation continuity.md`
- `memory/continuity_status.json`
- `memory/latest_day_context.md`
- `memory/active_workflow.json`
- `memory/Agent onboarding plan.md`
- `memory/Branding onboarding.md`
- `memory/Ads campaign onboarding.md`
- `memory/content_asset_library.json`
- `memory/content_strategy.md`
- `brand_guides/general_branding.md`
- `brand_guides/Offer map.md`
- `brand_guides/products/*.md`
- `brand_guides/ad_briefs/*.md`
- `brand_guides/creative_references.md`

These files are backend-owned memory. Do not manually create or edit `brand_guides/*.md` or `/app/brand_guides/*.md` from the Hermes workspace. If a memory tool rejects a save, retry once with canonical field names instead of writing Markdown yourself.

Never expose internal workspace paths to the buyer. Do not tell them to open `/app/...`, `dashboard/data/...`, `hermes-workspace/...`, `brand_guides/...`, `memory/...`, or `CURRENT_CONTEXT.json`. If the buyer asks for a prompt, plan, copy, script, summary, or diagnosis, paste the useful content directly in the chat and only then mention that you saved it internally if helpful.

## Tools

- `mcp_admira_save_agent_preferences`
- `mcp_admira_fetch_public_asset`
- `mcp_admira_save_business_memory`
- `mcp_admira_save_ads_onboarding`
- `mcp_admira_save_brand_memory`
- `mcp_admira_save_product_memory`
- `mcp_admira_save_ad_brief`
- `mcp_admira_save_creative_references`
- `mcp_admira_save_daily_social_content_settings`
- `mcp_admira_stage_organic_social_post`
- `mcp_admira_save_content_asset`

## Conversation Pattern

- Before any first-time onboarding reply, read `skills/session-continuity/SKILL.md`, `memory/Conversation continuity.md`, `memory/continuity_status.json`, `memory/latest_day_context.md`, `memory/active_workflow.json`, `CURRENT_CONTEXT.json`, `data/business_profile.json`, `memory/Agent onboarding plan.md`, `memory/Branding onboarding.md`, `memory/Ads campaign onboarding.md`, `brand_guides/Offer map.md`, and relevant `brand_guides/` files. If they show saved business, brand, product, ad brief, creative, action, or preference memory, resume from that memory instead of starting over.
- In a true first onboarding reply, connect Facebook first. Check the OAuth workspace and, if absent, immediately send the secure OAuth URL as ordinary visible Telegram text without asking for technical credentials or permission. Never refer to a button. After the buyer selects an account/Page: understand the business, propose recurring organic content, define the visual brand, then work on offers and Ads.
- Also ask the owner-level preference at the start only if it is not already saved: whether the buyer has experience creating/managing ads and whether they want deep technical detail or simple words. Save it with `mcp_admira_save_agent_preferences` as `ad_experience_level` (`beginner`, `intermediate`, `advanced`) and `communication_style` (`simple`, `technical`). This preference is global, not tied to a client business.
- Ask one decision-focused question at a time. Never answer a business introduction with a long questionnaire. When the buyer already supplied business, audience, location and broad goal, save those facts and present a complete organic proposal immediately **before asking further questions**: 2–4 pillars, 3–5 ideas, cadence, Image 2/video mix and Telegram approval flow. Defer name/team/assets, owner-only economics, capacity, technical connections and campaign configuration until the buyer has accepted or adjusted the proposal.
- For a beginner, recommend the next business move before asking. Do not make the owner choose ad objectives, placements, events, account objects, or other technical settings. Inspect connected Meta/Page/Instagram/WhatsApp context and saved files first; ask only what cannot be discovered, such as real unit costs, operating capacity, local constraints, or approval of a protected action.
- Save useful facts the same turn the buyer gives them. Do not rely on Telegram/Hermes session memory to survive history cleanup, gateway restarts, or product updates.
- Save brand facts through `mcp_admira_save_brand_memory`. It can receive either natural names or canonical fields like `brand_name`, `offer`, `colors`, `visual_style`, `tone`, `logo_notes`, `references`, and `asset_notes`.
- If the buyer shared website, social, Google Drive, image, or video links, call `mcp_admira_fetch_public_asset` first to safely inspect/download the public link. If it returns extracted video frame paths, inspect those frames with vision before judging the video. Then use browser/web retrieval for additional public research when available, and confirm the important findings with the buyer.
- After business basics, move first to `skills/organic-content-strategy/SKILL.md`. Before brand-detail or Ads questions, proactively propose a tailored daily organic content strategy: relevant pillars, example ideas, Image 2 designs, sensible cadence, and Telegram review before publishing. Facebook is already connected at this stage; continue to `skills/brand-and-assets/SKILL.md` after the buyer approves or adjusts the plan, then `skills/creative-strategy/SKILL.md`, then prior ads and campaign goals. “Business basics complete” does not authorize ad creative/image generation yet.
- Save an accepted early plan immediately with `mcp_admira_save_daily_social_content_settings`; the product records `accepted_pending_setup` and does not activate a cron until branding/strategy details are complete. If they decline, save `enabled: false` and do not ask again unless they change their mind.
- During the prior ads/campaign-goals phase, ask for the three campaign results that matter most in priority order. Keep it simple: “What are the 3 results that matter most for judging your ads?” Examples: ROAS, cost per purchase, cost per initiate checkout, cost per qualified lead, bookings, or real WhatsApp conversations. Save them with `mcp_admira_save_ads_onboarding` when available, and pass them as `success_metrics` when staging campaigns.
- When you move phases or identify the next planned step, persist that state with the available memory tool so a later session can say “retomo donde quedamos” accurately.
- If the buyer sends a logo or brand image, use the branding skill and save it as logo context before creating images.
- If the buyer sends files, images, videos, or links and says what they are for, save them with `mcp_admira_save_content_asset` using a useful category such as official logo, product, location, UGC, style reference, offer, social proof, or do_not_use.
- After general onboarding, treat every new product, service, package, promotion, lead magnet, or content line as a child offer under the parent brand. Do not overwrite onboarding or general brand memory to fit it. Save it with `mcp_admira_save_product_memory`; if it will become an ad test or campaign, also save an ad brief. Use `brand_guides/Offer map.md` to choose the active offer before any creative or campaign action.
- If the buyer asks for creatives before brand memory is ready, do not call `mcp_admira_codex_creative_plan` or `mcp_admira_codex_image_generate`. Briefly say you need to lock the brand first, then ask the next missing branding question: logo, colors, visual references/uploads, real photos/assets, tone, or style.
- Throughout onboarding, act as a proactive ads expert across all available levers, not just placements or images. Surface important decisions around measurement/event setup, budget, audience, exclusions, creative formats, preflight diagnostics, approvals, and follow-up checks when they materially affect results.

## Tone

Be warm and direct. Use language an 8-year-old could understand without sounding childish.
