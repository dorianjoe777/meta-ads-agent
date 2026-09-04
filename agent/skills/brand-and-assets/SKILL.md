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

One visible brand proposal needs at most one natural buyer confirmation. When `mcp_admira_save_brand_memory` returns `saved: true` and `draft: false`, the identity is official and its strategic `branding` topic is synchronized by the server in that same operation. Do not ask the buyer to repeat a special phrase, do not copy the same identity into `mcp_admira_save_business_memory`, and do not request another confirmation merely because the conversation moves to a campaign. Read the returned next step and ask only for a genuinely missing fact such as references or available real assets. A later “sí”, “listo”, or campaign approval is about the current visible proposal; never reinterpret it as a request to reconfirm already-saved branding.

This phase comes before organic or paid production. If no official logo exists and the buyer wants one, agree on name, category/offer, palette, visual style and tone, then call `mcp_admira_codex_image_generate` with `purpose: logo` (or `brand_exploration`, `moodboard`, `brand_sample`). Show the actual attached result and revise it conversationally. It is only a candidate until the buyer approves it and `mcp_admira_save_brand_memory` confirms the exact real file as official. Never say a blocked Image call is queued or will appear later.

## Parent brand vs child offers

Save colors, logo, tone, typography, visual style, and general restrictions as parent-brand memory. Do not save every new promotion or service by overwriting the brand's core offer. If the buyer introduces a specific package, service, product, seasonal promo, lead magnet, or organic content line, save it as a child offer with `mcp_admira_save_product_memory`.

When a creative request references a different offer from the one already saved, explicitly keep them separate: brand style can transfer, but promise, price, audience, CTA, and benefit must come from the active child offer.

## Official logo rule

When an official logo exists, use that exact saved file by default unless the buyer asks not to. Image prompts must say `pixel-level accurate` and pixel-faithful reproduction: unchanged text, symbols, geometry, proportions, colors, texture, and internal layout.

If a generated creative visibly alters the official logo, retry with the exact-composite fallback instead of inventing or approximating the mark.

## Real assets

Ask if the buyer has real photos/videos that should be used. If they provide a public link, use `mcp_admira_fetch_public_asset`.

Treat buyer-owned real photos as protected source material, not style inspiration. Save them with `preservation_mode: "pixel_locked"`. When any protected photo is used in Image 2, pass its durable file path in `protected_reference_image_paths` (or select it by `content_asset_ids`) and explicitly require `pixel by pixel accuracy`, `pixel-level accurate reproduction`, and `pixel-faithful` use. Image 2 may crop, scale, position, frame, mask the boundary, or add typography/graphics above or around it, but it must not redraw, regenerate, retouch, relight, recolor, beautify, remove/add objects, change people/products/text, or otherwise alter the photo content that appears in the design.

`style_reference` is different: it may guide composition, colors, typography, or mood and must be saved with `preservation_mode: "style_only"`. Also classify its lifetime. Use `reference_scope: "task"` (the safe default) when the buyer supplies it for one isolated creative; it is selected explicitly for that task and must not alter durable branding. Use `reference_scope: "brand"` only when the buyer supplies or approves it while defining durable branding; those references are automatically attached to every later creative. Never promote a one-off reference to brand scope merely because the model considers it reusable. Never treat a protected real photo as style-only merely because it is attached alongside design references.

A design reference is subordinate to confirmed brand memory and the active offer. It can guide visual language, but it never replaces approved colors, restrictions, exact phone numbers, prices, promotions, copy, or other business facts. Never copy the reference's own logo, photos, business name, phone number, prices, promotion, or wording.

## Asset library

When the buyer uploads or links a reusable asset, save its purpose with `mcp_admira_save_content_asset` so future posts/ads can reuse it correctly after history cleanup. Telegram archives every inbound image to durable product storage first as `pending_agent_review`; analyze the entire batch with vision and then classify every file. Group files only when they truly share the same category/purpose. Do not leave a batch pending after telling the buyer it was organized.

Categories to use: `official_logo`, `product`, `location`, `team_founder`, `customer_testimonial`, `ugc`, `style_reference`, `offer_promo`, `social_proof`, `do_not_use`, or `other`.

If the purpose is unclear, ask one short question before saving: “¿Esto lo uso como logo oficial, foto real, referencia de estilo, prueba social, UGC, oferta, o prefieres que no lo use?”

For a batch, ask that as one grouped question, not once per image. Use these preservation modes:

- buyer-owned real photo or official logo: `pixel_locked`;
- inspiration/design reference: `style_only`;
- one-off inspiration for the current creative: `style_only` plus `reference_scope: "task"`;
- durable reference approved during branding: `style_only` plus `reference_scope: "brand"`;
- not yet understood: `pending_classification` and not approved for reuse;
- buyer says not to use it: `prohibited`.

For videos, use any extracted frames to understand the footage visually, save the video/link/frame set with `mcp_admira_save_content_asset`, and note whether it is for ads, organic posts, UGC review, or “reference only.”
