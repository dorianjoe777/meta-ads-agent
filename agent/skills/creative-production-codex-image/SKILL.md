---
name: creative-production-codex-image
description: Produce raster creative assets through Codex/Image for Admira IA using saved brand/product context, uploaded references, real-photo background preservation, photorealistic prompts, and automatic media delivery.
---

# Creative Production Codex/Image Skill

Use this skill when the buyer asks to generate, revise, or deliver image creatives.

## Tool path

- Use `mcp_admira_codex_image_generate` for actual image files.
- Use `mcp_admira_codex_creative_plan` only for concept/prompt planning after brand/product context is ready.
- Do not use Hermes internal image generation or mention external image APIs.
- For organic daily posts, use purpose `daily_social_post` or `standalone_creative`; do not require budget, launch readiness, or a campaign brief unless the buyer is actually creating an ad.
- If the buyer asks you to create, revise, or show an image, proceed to generate/deliver it once the necessary creative inputs exist. Do not ask a redundant “quieres que la genere ahora?” unless the choice would materially change the design direction or spend/publish something.
- If a non-blocking detail is missing, make the best safe assumption, state it briefly, and generate a draft the buyer can correct.

## References and logos

- Pass safe uploaded images in `reference_image_paths`.
- Use `memory/content_asset_library.json` to choose only assets approved for the requested purpose.
- When the buyer wants a real photo as the base/background, set `use_reference_as_background: true`.
- When an official logo is saved and should appear, set `include_logo: true` and require `pixel-level accurate` reproduction.
- If the logo is altered, retry with `logo_render_mode: "exact_composite"`.

## Output

After generation, inspect the result and send the media to the buyer. Do not reply only with a path, `MEDIA:/...`, or “lo guardé en este archivo.” If a native attachment directive is needed, use it only as internal syntax at the end of the response.

For real-world people, places, food, interiors, products, or locations, request photorealism unless the buyer explicitly wants illustration.
