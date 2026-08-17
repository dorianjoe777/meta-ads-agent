---
name: creative-production-codex-image
description: Produce raster creative assets through Codex/Image for Admira IA using saved brand/product context, uploaded references, real-photo background preservation, photorealistic prompts, and automatic media delivery.
---

# Creative Production Codex/Image Skill

Use this skill when the buyer asks to generate, revise, or deliver image creatives.

## Tool path

- Use `mcp_admira_codex_image_generate` for actual image files.
- For motion-graphics storyboard assets, use `purpose: motion_graphic_asset`. Generate full-frame scene imagery normally; use `background_removal: green_screen` for isolated shapes, icons, foreground objects, branded motifs, badges, or transition elements that Remotion must layer over other scenes.
- Storytelling subjects and props are equally valid: send `asset_role: story_subject` or `story_prop` plus the exact `narrative_role`, scene perspective, gaze/action direction, lighting, scale, and safe crop. They are one-off by default and should not be saved as reusable brand elements unless the exact asset truly belongs in the recurring library.
- Before generating a recurring design element, search the classified content library. Save useful parent-brand/product elements with `reusable_asset`, an exact `product_scope`, and a semantic `asset_role`; do not regenerate equivalent elements on every video.
- Use `mcp_admira_codex_creative_plan` only for concept/prompt planning after brand/product context is ready.
- Do not use Hermes internal image generation or mention external image APIs.
- When Image 2/Codex is configured, never redirect the buyer to Midjourney, DALL·E, Bing, Canva, or manual generation because the tool is absent from one runtime session. Treat that as an internal product-health fault: keep the image request active, trigger/recommend the Admira update or connection recovery path, and retry the official tool after recovery. Do not turn the fault into placeholder work or another decision for the buyer unless the buyer explicitly requests that workaround.
- For organic daily posts, use purpose `daily_social_post` or `standalone_creative`; do not require budget, launch readiness, or a campaign brief unless the buyer is actually creating an ad.
- If the buyer asks you to create, revise, or show an image, proceed to generate/deliver it once the necessary creative inputs exist. Do not ask a redundant “quieres que la genere ahora?” unless the choice would materially change the design direction or spend/publish something.
- A follow-up such as “crea otro”, “otro título”, “otro arrangement”, “haz una variante”, or “cámbialo” remains an image-generation/revision request. Do not reroute it into recurring-content settings, content onboarding, or approval before a new final image exists.
- If a non-blocking detail is missing, make the best safe assumption, state it briefly, and generate a draft the buyer can correct.
- Before calling the tool, identify the active offer from the latest request, selected product guide, ad brief, or `brand_guides/Offer map.md`. If the buyer is asking about a different/new offer under the same parent brand, pass that active offer in `product_guide` or in the request. Do not let older saved products contaminate the output.

## References and logos

- Pass safe uploaded images in `reference_image_paths`.
- Use `memory/content_asset_library.json` to choose only assets approved for the requested purpose.
- For buyer-owned real photos that must appear, pass their paths in `protected_reference_image_paths` or their IDs in `content_asset_ids`. These are `pixel_locked`, not inspiration.
- When the buyer wants a real photo as the base/background, set `use_reference_as_background: true`; this automatically makes the base a protected real asset.
- For every protected real asset, the request must require `pixel by pixel accuracy`, `pixel-level accurate reproduction`, and `pixel-faithful` use. Allowed operations are crop, scale, position, frame, boundary mask, and text/graphic overlays above or around the source. Never permit Image 2 to redraw, regenerate, retouch, relight, recolor, beautify, remove/add objects, or change people, products, packaging, text, architecture, or other visible photo content.
- Pass inspiration-only material as ordinary `reference_image_paths` and classify it as `style_only`; do not confuse it with protected buyer photography.
- When an official logo is saved and should appear, set `include_logo: true` and require `pixel-level accurate` reproduction.
- If the logo is altered, retry with `logo_render_mode: "exact_composite"`.

## Output

After generation, inspect the result and send the media to the buyer. Do not reply only with a path, `MEDIA:/...`, or “lo guardé en este archivo.” If a native attachment directive is needed, use it only as internal syntax at the end of the response.

If the generation tool returns blocked/error, report the specific blocker in simple words and keep the current creative request active for retry. Do not call an unrelated save/scheduling tool to manufacture progress, and do not claim the image or organic post was created.

For real-world people, places, food, interiors, products, or locations, request photorealism unless the buyer explicitly wants illustration.
