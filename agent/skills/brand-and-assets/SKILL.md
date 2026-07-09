---
name: brand-and-assets
description: Build and use brand memory for Admira IA creatives: logo, colors, references, real photos/videos, visual style, tone, and exact pixel-level logo handling before creative production.
---

# Brand and Assets Skill

Use this skill when the buyer discusses brand, logo, colors, references, photos, videos, or visual style.

## Brand lock

Collect and save:

- brand name and offer context;
- colors, visual style, tone, and design references;
- logo decision: provided logo, create new logo, no logo, or logo optional;
- real asset decision: buyer photos/videos, generated assets, or both;
- reference decision: uploaded or public references to follow.

Use `mcp_admira_save_brand_memory`, `mcp_admira_save_product_memory`, `mcp_admira_save_creative_references`, and `mcp_admira_save_content_asset`. Read `memory/Branding onboarding.md` and `brand_guides/Offer map.md` when present. Treat `brand_guides/` and `memory/content_*` files as read-only snapshots; do not manually write them.

## Parent brand vs child offers

Save colors, logo, tone, typography, visual style, and general restrictions as parent-brand memory. Do not save every new promotion or service by overwriting the brand's core offer. If the buyer introduces a specific package, service, product, seasonal promo, lead magnet, or organic content line, save it as a child offer with `mcp_admira_save_product_memory`.

When a creative request references a different offer from the one already saved, explicitly keep them separate: brand style can transfer, but promise, price, audience, CTA, and benefit must come from the active child offer.

## Official logo rule

When an official logo exists, use that exact saved file by default unless the buyer asks not to. Image prompts must say `pixel-level accurate` and pixel-faithful reproduction: unchanged text, symbols, geometry, proportions, colors, texture, and internal layout.

If a generated creative visibly alters the official logo, retry with the exact-composite fallback instead of inventing or approximating the mark.

## Real assets

Ask if the buyer has real photos/videos that should be used. If they provide a public link, use `mcp_admira_fetch_public_asset`. If a real photo should be the base/background, pass it as an input/reference and preserve it pixel-faithfully as much as Image 2 allows.

## Asset library

When the buyer uploads or links a reusable asset, save its purpose with `mcp_admira_save_content_asset` so future posts/ads can reuse it correctly after history cleanup.

Categories to use: `official_logo`, `product`, `location`, `team_founder`, `customer_testimonial`, `ugc`, `style_reference`, `offer_promo`, `social_proof`, `do_not_use`, or `other`.

If the purpose is unclear, ask one short question before saving: “¿Esto lo uso como logo oficial, foto real, referencia de estilo, prueba social, UGC, oferta, o prefieres que no lo use?”

For videos, use any extracted frames to understand the footage visually, save the video/link/frame set with `mcp_admira_save_content_asset`, and note whether it is for ads, organic posts, UGC review, or “reference only.”
