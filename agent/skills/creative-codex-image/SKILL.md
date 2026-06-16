# Creative Codex Image Skill

Use this skill when the buyer asks for images, ad creatives, variants, designs, static ad graphics, product showcase images, or creative refreshes.

## Required Tool Path

- For final ad images, always call `mcp_admira_codex_image_generate`.
- For creative concepts or prompt planning, call `mcp_admira_codex_creative_plan`.
- Do not use Hermes internal image generation.
- Do not mention FAL, Nous, or random image APIs.

## Context To Use

Read these workspace files when present:

- `brand_guides/general_branding.md`
- `brand_guides/products/*.md`
- `brand_guides/ad_briefs/*.md`
- `brand_guides/creative_references.md`
- `memory/Ads campaign onboarding.md`
- uploaded images in `uploads/`

If an uploaded image is relevant, summarize what you see and include that summary in the tool arguments as `reference_image_summary`.

## Arguments

For `mcp_admira_codex_image_generate`, include:

- `request`: buyer's exact creative ask in Spanish.
- `mode`: `fixed` when preserving brand strictly, `free` when the buyer asks for more creative variety.
- `variations`: number of variants if requested.
- `product_guide`: product or offer name/content when known.
- `ad_brief`: campaign/ad brief when known.
- `reference_image_summary`: only if the buyer uploaded a useful image.

## Reply

After the tool returns, tell the buyer where the image is saved and what to do next. If the tool fails, explain the missing connection without inventing an image.
