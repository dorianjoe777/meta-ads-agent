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
- If a non-blocking detail is missing, make the best safe assumption, state it briefly, and generate a draft the buyer can correct **only for a standalone/organic creative request**. For a new paid campaign, this permission does not apply: first show the recommended positioning, exact primary text, distinct title, CTA/destination message, and concrete visual concept; wait for the buyer's natural correction or approval, then generate the image. A campaign request, budget answer, service name, “no creative yet”, or existing campaign context is not an image request.
- Before calling the tool, identify the active offer from the latest request, selected product guide, ad brief, or `brand_guides/Offer map.md`. If the buyer is asking about a different/new offer under the same parent brand, pass that active offer in `product_guide` or in the request. Do not let older saved products contaminate the output. When several product guides exist and the active offer is not resolved, keep the work at proposal level and ask the one owner-only question needed to select the offer; never silently use the first guide or the general brand guide as a substitute.

## References and logos

For hybrid compositions that combine buyer-owned photos with an Image 2 graphic overlay, read [references/hybrid-real-media-contract.md](references/hybrid-real-media-contract.md). It defines the ordered slot contract, layout modes, chroma-key rules, logo rendering modes, and reference-selection semantics. The existing Codex/Image provider and bridge remain the only generation path; this reference describes MCP arguments and post-generation composition, not a replacement provider.

- For ordinary non-hybrid inspiration only, pass safe uploaded images in `reference_image_paths`.
- Use `memory/content_asset_library.json` to choose only assets approved for the requested purpose.
- For compatibility, ordinary non-hybrid calls can still resolve saved photos through `protected_reference_image_paths` or `content_asset_ids`. When a buyer-owned real photo must remain exact and visible in the final bitmap, use the `real_media` hybrid contract below; do not rely on Image 2 to reproduce the photo.
- When the buyer wants a real photo as the base/background, set `use_reference_as_background: true`; this automatically makes the base a protected real asset.
- For every protected real asset, preserve the source programmatically. Allowed operations are crop, scale, position, frame, boundary mask, and text/graphic overlays above or around the source. Never permit Image 2 to redraw, regenerate, retouch, relight, recolor, beautify, remove/add objects, or change people, products, packaging, text, architecture, or other visible photo content.
- Pass inspiration-only material as ordinary `reference_image_paths` and classify it as `style_only`; do not confuse it with protected buyer photography.
- When an official logo is saved and should appear, set `include_logo: true` and require `pixel-level accurate` reproduction.
- If the logo is altered, use the canonical `logo_color_mode` and let the backend apply the exact saved logo after the logo-free base is generated.

## Hybrid real-media compositions

When the buyer wants a designed graphic that contains real photos, use the hybrid composition contract. This is appropriate for a single hero photo, before/after, multiple unrelated services, or a collage/freeform layout. Preserve each buyer-owned photo exactly by inserting it programmatically after Image 2 returns the overlay; in hybrid mode do not pass real photos or the official logo to Image 2 as generative references. Image 2 receives only the visual direction, text, CTA, brand guidance, and keyed placeholder instructions.

- Build an ordered `real_media` array with stable `slot_id` values and the exact source asset for each slot. Include the semantic role/label (`hero`, `before`, `after`, or a service name) so the compositor cannot swap photos.
- Let the main model express layout intent naturally as `hero`, `before_after`, `services`, `collage`, or `freeform`; do not impose keyword-based conversation rules or a separate visual-brief approval ceremony.
- Use one photo for a hero. Use two photos as before/after when the conversation establishes that relationship; otherwise treat them as two independent service slots. Use 3–6 photos as a collage or another layout selected from the buyer's visual direction. More than two photos are not automatically before/after.
- Ask Image 2 to create all overlay typography, bullets/features, titles, CTA and graphic composition while reserving one distinct keyed placeholder per ordered slot. The prompt must include the slot-to-color mapping and tell Image 2 not to draw a logo or any real photographic content.
- Select saturated key colors away from every confirmed brand hue. If the brand uses green, never key with green. Use tolerant color clustering and connected-component detection rather than exact RGB matching; Image 2 may slightly shift requested RGB values. Remove keyed regions, insert the matching source photo by slot, and retain the overlay outside each mask. Reject or revise only when a slot is missing, duplicated, contaminated, or cannot be mapped safely.
- The official logo is composited programmatically from the saved original file, never regenerated or approximated by Image 2. Support `original` (multicolor source), `white`, `black`, `brand_primary`, `brand_secondary`, and `auto_contrast` render modes. `auto_contrast` chooses among the saved solid variants based on the local background; it must not invent a new logo color.
- Variations are deliberately dynamic: keep the same offer, copy constraints, slot mapping, and brand rules, but allow Image 2 to vary composition, hierarchy, framing, card geometry, negative space, typography arrangement, and CTA treatment. A request for another variation should generate another image, not ask the buyer to reconfigure a template.
- Style references are opt-in. Pass `style_reference: {"mode": "none"}` by default. Use `{"mode": "pool"}` only when the buyer explicitly asks to use saved graphic-design references; use one shuffled eligible reference without immediate repetition. An explicitly selected reference uses `{"mode": "explicit", ...}` and overrides the pool. Never place real photos or logos in this pool.
- Review the final composited bitmap and attach it. A deterministic media/mask/source-integrity check is useful, but natural-language understanding remains with the main model and user review remains the final aesthetic decision.

## Output

After generation, inspect the result and send the media to the buyer. Do not reply only with a path, `MEDIA:/...`, or “lo guardé en este archivo.” If a native attachment directive is needed, use it only as internal syntax at the end of the response.

If the generation tool returns blocked/error, report the specific blocker in simple words and keep the current creative request active for retry. Do not call an unrelated save/scheduling tool to manufacture progress, and do not claim the image or organic post was created.

For real-world people, places, food, interiors, products, or locations, request photorealism unless the buyer explicitly wants illustration.
