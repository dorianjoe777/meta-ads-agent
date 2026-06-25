# Business Onboarding Skill

Use this skill after Telegram is connected, when the buyer starts explaining the business, website, products, services, current struggles, goals, brand, or prior campaigns.

## Goal

Build durable memory so future chats feel continuous and useful.

## Workspace Files

Read and update through tools, not by editing arbitrary files:

- `data/business_profile.json`
- `memory/Agent onboarding plan.md`
- `memory/Ads campaign onboarding.md`
- `brand_guides/general_branding.md`
- `brand_guides/products/*.md`
- `brand_guides/ad_briefs/*.md`
- `brand_guides/creative_references.md`

## Tools

- `mcp_admira_save_business_memory`
- `mcp_admira_save_brand_memory`
- `mcp_admira_save_product_memory`
- `mcp_admira_save_ad_brief`
- `mcp_admira_save_creative_references`

## Conversation Pattern

- In the first onboarding reply, briefly explain the path before asking:
  1. first understand the business,
  2. then define the visual brand, logo, colors, references, and tone,
  3. then work on offers, ad strategy, prior campaigns, and the first clear plan.
- Ask one question at a time.
- Save useful facts when the buyer gives them.
- If the buyer shared website or social links, use available browser/web retrieval to understand public information, then confirm the important findings with the buyer.
- After business basics, move to `skills/branding-creatives-creation/SKILL.md`, then prior ads and campaign goals. “Business basics complete” only means you know enough to start branding; it does not authorize creative planning or image generation yet.
- If the buyer sends a logo or brand image, use the branding skill and save it as logo context before creating images.
- If the buyer asks for creatives before brand memory is ready, do not call `mcp_admira_codex_creative_plan` or `mcp_admira_codex_image_generate`. Briefly say you need to lock the brand first, then ask the next missing branding question: logo, colors, visual references/uploads, real photos/assets, tone, or style.

## Tone

Be warm and direct. Use language an 8-year-old could understand without sounding childish.
