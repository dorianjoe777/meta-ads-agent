---
name: motion-graphics-video
description: Plan and render branded motion-graphics videos for any niche through Admira's Remotion renderer, including educational explainers, tutorials, offers, announcements, social proof, real-media compositions, and placement-specific versions.
---

# Motion Graphics Video

Use this skill when the buyer asks for an animated, educational, explainer, promotional, tutorial, social-proof, announcement, or other motion-graphics video. Use `mcp_admira_generate_motion_graphic_video` for the actual MP4. This is a local deterministic renderer; do not redirect the buyer to external video tools when it is available.

## Orient first

1. Read the parent brand, Offer map, exact child product/service/offer guide, classified asset library, and `memory/currently-decided/motion-graphics-video-currently-decided.md`.
2. Identify the active child offer from the latest request. Parent brand controls logo, core palette, typography, tone, references, and restrictions. The child offer controls audience, promise, subject, CTA, visual overrides, motion style, and pacing.
3. If several offers exist and the request is ambiguous, ask only which exact offer is active. Never blend old offer claims, prices, photos, or CTAs into the new video.
4. If brand name, colors, or visual style are missing, complete that part of branding before production. Save confirmed offer-specific motion choices with `mcp_admira_save_product_memory`; never edit this skill.

## Proactive production

Treat a direct request to create a video as permission to storyboard and render a safe draft. Do not ask “should I create it now?” Ask only when a missing fact changes the truth of the video, the exact offer, rights to an asset/quote, or the final creative direction materially.

When the buyer is not a marketer, choose a strong structure yourself:

- One clear hook in the first scene.
- One new idea per scene.
- Enough hold time to read before moving on.
- A practical sequence: problem or curiosity → explanation or steps → proof/contrast → next action.
- A useful CTA that matches the purpose; educational content may use no sales CTA.

Build the video as a recipe storyboard. For every scene, choose one dominant named recipe and, when it improves comprehension, combine it with compatible effect/transition recipes in `shot_recipes`. Think in layers: base or camera → typography/emphasis → transition. Do not stack two competing full-screen recipes. The buyer describes the outcome naturally; do not ask them to select technical recipe names.

The full Video Shotcraft library is available: 152 recipe cards and 209 named styles. There is no 24-recipe ceiling. Use progressive disclosure so the catalog does not bloat the conversation:

1. Call `mcp_admira_search_motion_graphic_recipes` with the message's narrative role, tone, energy, tempo, impact, or category. Search `references/shotcraft-storytelling-vocabulary.json` only when deeper comparison is needed.
2. Read each selected card's exact `source` Markdown.
3. Read the exact TSX demo named by that card under `references/shotcraft/demos/` or `references/shotcraft/template/`.
4. Translate the tuned timing, easing, masks, staging, and known pitfalls into the buyer's actual scene, copy, assets, aspect ratio, parent brand, and active child offer. Do not imitate a card from its name alone.

Choose by narrative purpose before visual novelty. Search [shotcraft-storytelling-vocabulary.json](references/shotcraft-storytelling-vocabulary.json) to compare every style by normalized energy, tempo, impact, reading priority, layer role, narrative role, message fit, tone fit, and compatible categories. A calm trust message should not inherit an aggressive recipe merely because it looks impressive; a launch crescendo should not be flattened into slow educational motion. Treat these labels as selection guidance, then verify the card's exact intention and known pitfalls.

The parameterized recipes in [motion-recipes.md](references/motion-recipes.md) are a fast path, not the catalog. Any other catalog card/style is rendered through a validated, job-scoped adaptation in `compiled_recipe_source`. That source never changes the product or skill: it exists only inside this render job. For catalog navigation, also see [shotcraft-gallery-index.md](references/shotcraft-gallery-index.md). For rendering and quality rules, read [production-standard.md](references/production-standard.md).

## Image 2 visual production for storyboards

When ChatGPT/Codex Image is connected, treat it as part of video production. Do not limit the storyboard to plain text merely because the needed visual does not exist yet.

Use a two-pass workflow:

1. Draft the communication storyboard and mark which scenes genuinely benefit from a generated full-frame image, background, foreground cutout, icon, shape, texture, badge, branded motif, or transition element.
2. Search `memory/content_asset_library.json` first. Reuse a compatible approved `brand_graphic_element`, `motion_graphic_element`, or `decorative_element` with the same parent brand/product scope instead of generating it again.
3. For each missing asset, call `mcp_admira_codex_image_generate` with `purpose: motion_graphic_asset`, the exact active product/offer, scene intent, aspect/size, visual role, palette, safe space, camera/perspective, and the Shotcraft recipe it must support.
4. For a full-frame image, keep its normal background and bind the returned image to the intended scene. For an isolated foreground/design element, set `background_removal: green_screen`; ask for one complete element on flat `#00FF00`, with no crop, shadow, floor, extra object, or green inside the subject. The backend returns a transparent PNG.
5. Set `reusable_asset: true` only for elements that form part of the reusable visual language. Use `reusable_category: brand_graphic_element` for parent-brand motifs, `motion_graphic_element` for product/video components, and `decorative_element` for broadly useful shapes/illustrations. Include `product_scope`, `asset_role`, `asset_purpose`, and reuse restrictions.
6. Inspect the actual generated files. Then revise the storyboard around their real composition, proportions, negative space, and visual weight. Do not keep a layout that assumed an asset Image 2 did not actually produce.
7. Pass returned paths/asset IDs to `mcp_admira_generate_motion_graphic_video`. Use `media_path` for the scene background/main medium and `layer_asset_paths` for up to six independent foreground/design layers. Use `ProtectedMedia assetIndex={0..5}` inside an adapted Shotcraft recipe to position and animate each transparent layer.

Distinguish two asset families:

- **Brand/design-system elements**: recurring motifs, frames, textures, shapes, badges, patterns, or product-specific graphic devices. Archive genuinely reusable ones with `reusable_asset: true` and an exact product scope.
- **Story elements**: people, products, objects, environments, symbols, visual metaphors, or props needed to communicate one scene—for example a relaxed spa customer, a floating appointment calendar, a damaged microphone, a skincare bottle, or hands demonstrating a process. Generate the exact subject on flat green with `asset_role: story_subject` or `story_prop`, explain its `narrative_role`, remove the background, and compose it into the scene. These are one-off by default (`reusable_asset: false`); archive as `story_element` only when the same exact asset is genuinely useful again.

For story elements, design from the destination scene backwards: specify camera angle, perspective, direction of gaze/movement, lighting direction, crop safety, scale, and required negative space so the extracted subject fits the storyboard. Do not force brand colors onto a real-world subject when that would make it unnatural; instead harmonize the scene through surrounding palette, typography, lighting, shadows, framing, and motion. Any cast shadow or contact shadow needed after extraction should be created in Remotion, not baked into the green plate.

Generate only what improves the story. Reusable elements must align with the saved parent brand and exact child offer; they are not a substitute for official logos or buyer-owned real product/person/location media. Never regenerate real buyer media. An official logo remains the exact saved logo file.

## Tool contract

Call `mcp_admira_generate_motion_graphic_video` with:

- `topic`, `objective`, `product_guide`, `audience`, `aspect_ratio`, and `quality`.
- Either `key_points` for an automatic storyboard or up to 12 explicit `scenes`.
- Optionally choose a coordinated `template`: `adaptive`, `ink-press`, `cinematic-product`, `educational-cards`, `data-story`, or `social-vertical`.
- Each explicit scene may include `shot_recipes` with one to four exact card names or style keys from the complete catalog. A coherent example is one camera/UI/data recipe + one typography or emphasis recipe + one transition.
- For any recipe outside the parameterized fast path, include `compiled_recipe_source`: a bounded React JSX function body adapted from the exact card and demo. It may use only the provided `scene`, `brand`, `palette`, `frame`, `fps`, `width`, `height`, `durationInFrames`, `interpolate`, `interpolateColors`, `spring`, `Easing`, `seededRandom`, `AbsoluteFill`, `Sequence`, `CameraMotionBlur`, `ProtectedMedia`, and `BrandLogo` bindings. It must return JSX. Never include imports, exports, network/file access, timers, global objects, raw media URLs, or nondeterministic time/randomness.
- `ProtectedMedia` is the only way for a compiled recipe to show generated or buyer media. Without `assetIndex` it resolves `media_path`; with `<ProtectedMedia assetIndex={0} fit="contain" />` it resolves the first item in `layer_asset_paths`. It preserves pixels and PNG transparency. Never recolor, regenerate, distort, or filter buyer-owned real media.
- Generated transparent PNGs are also immutable composition inputs after generation. Use `contain` and position/scale/mask them; do not run them back through Image 2 merely to fit a layout.
- Exact `asset_paths`/`content_asset_ids` only when those assets are approved for this use.
- `audio_path` only when the buyer owns or may use the audio.

Scene types are `hook`, `statement`, `list`, `steps`, `stat`, `comparison`, `quote`, `media`, and `cta`. Total length must be 3–90 seconds. Prefer 9:16 for Reels/Stories, 4:5 for feed, 1:1 for square feeds, and 16:9 for YouTube/presentations. If the destination is unspecified, use 9:16 for social-first video.

Never put unsupported claims, invented statistics, or fabricated testimonials in a scene. A `quote` requires a verified quote and attribution. A `stat` requires a factual source in the conversation or durable business memory.

## Real media and logo protection

Buyer-owned photos, footage, products, packaging, people, interiors, screenshots, and official logos are source truth. The renderer may copy, crop boundaries, scale, position, frame, mask edges, and overlay text or graphics. It must not redraw, regenerate, retouch, recolor, relight, beautify, alter faces/bodies/products/text, or change the media content. Use `media_fit: contain` when no crop is acceptable.

If an asset is merely inspiration, classify it as `style_only`; do not show it as buyer-owned content. Do not use prohibited or unclassified assets.

## Output and review

Render `preview` first for a new direction, then `final` once the buyer requests/finalizes delivery. Inspect the returned duration, dimensions, poster, and MP4 attachment. The buyer-facing answer should briefly say what was created and attach the video; never expose a local path or `MEDIA:` directive.

Video creation itself does not publish, activate a campaign, or spend money. Publishing or activating remains a separate protected action.

## Source synthesis

This skill intentionally combines two external systems without installing either as an autonomous agent runtime:

- Remotion's current best-practice skills: deterministic frame-driven React composition, explicit sequencing, media handling, metadata, and render verification.
- Video Shotcraft's Apache-2.0 recipe system and adapted parametric components: named shot cards, coordinated recipe storyboards, PageCam-style 2.5D motion, Ink Press structure, data/typography/UI recipes, transitions, breathing room, real-media fidelity, and staged aesthetic QA.

The product owns the normalized storyboard contract and renderer. Hermes may synthesize only the bounded per-scene JSX body described above after reading exact trusted references; the MCP validates its syntax and capabilities and stores it only inside that render job. Hermes never executes code directly, adds imports, installs packages, or edits the official renderer, product code, or skill catalog.
