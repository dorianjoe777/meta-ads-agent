---
name: creative-codex-image
description: Produce standalone creative assets or approved raster ad creatives through Codex/Image using brand/product context, safe uploaded references, photorealistic real-world imagery, and exact official-logo placement. Use a full ad-test brief only for launch-ready/test-ready ads.
---

# Creative Codex Image Skill

## Compatibility shim

This legacy skill remains for compatibility. Before using it, read:

- `skills/core-agent-behavior/SKILL.md`
- `skills/session-continuity/SKILL.md`
- `skills/brand-and-assets/SKILL.md` when logo, references, or real assets matter
- `skills/creative-production-codex-image/SKILL.md`

Use this skill when the buyer asks to produce approved raster ad images, variants, designs, static ad graphics, product showcases, or creative refreshes.

Image 2 is a production capability, not the creative strategy. First read `memory/Agent onboarding plan.md`, `skills/brand-and-assets/SKILL.md`, `skills/creative-strategy/SKILL.md`, and `skills/creative-production-codex-image/SKILL.md`. If the buyer wants a launch-ready ad test, make sure brand discovery, references/assets decisions, and the creative test brief are complete. If the buyer only asks for a standalone image/asset/draft to keep or review, do not block on test budget or a complete ad brief; use the current product/offer context and mark the request as `asset_only: true` or `purpose: "standalone_creative"`.

## Required Tool Path

- For actual image files, always call `mcp_admira_codex_image_generate`.
- For creative concepts or prompt planning, call `mcp_admira_codex_creative_plan` only after the branding/product readiness gate is complete.
- If a launch-ready/test-ready readiness gate is missing anything, ask the next missing discovery question and save the answer first. For standalone draft assets, pass the buyer's current product/offer context directly instead of claiming a missing internal ficha blocks simple image generation.
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

Treat `brand_guides/` as read-only workspace context. Do not create or edit those Markdown files manually to unblock image production. If brand, product, or ad-brief readiness is incomplete, save the missing memory with `mcp_admira_save_brand_memory`, `mcp_admira_save_product_memory`, `mcp_admira_save_ad_brief`, or `mcp_admira_save_creative_references`, then call `mcp_admira_codex_image_generate` again.

Internal files are not buyer-facing deliverables. Do not tell the buyer to open `/app/...`, `dashboard/data/...`, `hermes-workspace/...`, `brand_guides/...`, `memory/...`, or `CURRENT_CONTEXT.json`. Do not present `MEDIA:/...` as a link, preview URL, or address the buyer should copy/open. If they ask for the prompt, paste the full prompt directly in the chat. You may also save it internally, but the answer must be usable from Telegram alone.

If an uploaded image is relevant, summarize what you see and include that summary in the tool arguments as `reference_image_summary`.

Also pass its safe workspace path in `reference_image_paths`. Ask proactively whether the buyer has a real product, founder, customer, location, packaging, or design-reference image to upload.

If the buyer confirms that an uploaded real photo should be the actual background/base of the creative, not merely inspiration, call `mcp_admira_codex_image_generate` with `use_reference_as_background: true`. The backend will still use Image 2, attach the real photo as an input/reference image, and add a strict prompt to preserve the real background pixel-faithfully as much as Image 2 allows while permitting only subtle global beautification and ad text/CTA.

## Arguments

For `mcp_admira_codex_image_generate`, include:

- `request`: buyer's exact creative ask in Spanish.
- `mode`: `fixed` when preserving brand strictly, `free` when the buyer asks for more creative variety.
- `variations`: number of variants if requested.
- `test_budget`: daily or monthly ad-test budget when the buyer already gave it.
- `product_guide`: product or offer name/content when known.
- `ad_brief`: campaign/ad brief when known.
- `reference_image_summary`: only if the buyer uploaded a useful image.
- `reference_image_paths`: safe uploaded images that must guide the result.
- `use_reference_as_background`: true when the buyer says yes to using the uploaded real photo as the actual background/base. Use this for real locations/receptions/products that must remain recognizably the same.
- `purpose`: use `standalone_creative` for asset-only/draft images, `ad_creative` for normal ad creative, and `logo` or `brand_exploration` only when that is truly the buyer's request.
- `asset_only`: true when the buyer wants an image/creative to keep, review, or use later without launching or sizing a Meta test yet.
- `include_logo`: true when the saved official logo should appear. If an official logo is saved, future creatives should use that exact file by default unless the buyer explicitly asks for no logo.
- `logo_position`: approved placement such as `top-right`, `top-left`, `bottom-right`, or `bottom-left`.
- `logo_render_mode`: normally `protected_context`; use `exact_composite` only as a fallback if a generated result visibly alters the official mark.

If an official logo is included, the backend attaches the saved file as a protected reference and adds a strict prompt requiring pixel-level accurate reproduction and pixel-faithful reproduction (fiel píxel por píxel). The logo's wording, spelling, letterforms, symbols, artwork, geometry, proportions, spacing, colors, texture, borders, and internal layout must not change. Never replace it with a similar mark.

Inspect the returned image. If the logo is visibly changed, regenerate with `logo_render_mode: "exact_composite"`. In that fallback the model creates a logo-free base and the backend applies the exact saved asset afterward.

Any generated person, product, location, food, interior, or other real-world scene must be photorealistic unless the buyer explicitly approved an illustrated or stylized treatment.

## Reply

After the tool returns successfully, the visible reply should say the image is ready and attached here, plus one short recommendation or next option. Do not expose internal local paths. If the platform needs a `MEDIA:<local_path>` tag to deliver the image, include that tag only as native attachment syntax at the very end of the response, never as text like "use this path" or "MEDIA:/app/...". If the tool fails, explain the missing connection without inventing an image. If the buyer asks for a prompt because Image 2 is unavailable, paste the exact prompt in the chat instead of pointing to an internal file.
