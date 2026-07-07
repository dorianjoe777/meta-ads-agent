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

Use `mcp_admira_save_brand_memory`, `mcp_admira_save_product_memory`, and `mcp_admira_save_creative_references`. Treat `brand_guides/` files as read-only snapshots; do not manually write them.

## Official logo rule

When an official logo exists, use that exact saved file by default unless the buyer asks not to. Image prompts must say `pixel-level accurate` and pixel-faithful reproduction: unchanged text, symbols, geometry, proportions, colors, texture, and internal layout.

If a generated creative visibly alters the official logo, retry with the exact-composite fallback instead of inventing or approximating the mark.

## Real assets

Ask if the buyer has real photos/videos that should be used. If they provide a public link, use `mcp_admira_fetch_public_asset`. If a real photo should be the base/background, pass it as an input/reference and preserve it pixel-faithfully as much as Image 2 allows.
