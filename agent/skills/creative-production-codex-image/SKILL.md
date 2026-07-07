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

## References and logos

- Pass safe uploaded images in `reference_image_paths`.
- When the buyer wants a real photo as the base/background, set `use_reference_as_background: true`.
- When an official logo is saved and should appear, set `include_logo: true` and require `pixel-level accurate` reproduction.
- If the logo is altered, retry with `logo_render_mode: "exact_composite"`.

## Output

After generation, inspect the result and send the media to the buyer. Do not reply only with a path, `MEDIA:/...`, or “lo guardé en este archivo.” If a native attachment directive is needed, use it only as internal syntax at the end of the response.

For real-world people, places, food, interiors, products, or locations, request photorealism unless the buyer explicitly wants illustration.
