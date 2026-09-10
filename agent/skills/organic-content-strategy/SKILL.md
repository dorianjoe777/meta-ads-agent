---
name: organic-content-strategy
description: "Plan and run Admira IA organic social content: optional recurring Image 2 posts and motion videos, content pillars, buyer-shared asset categorization, captions, approval flow, and direct publishing handoff."
---

# Organic Content Strategy Skill

Use this skill when the buyer asks for social posts, daily content, content calendars, organic publishing, or shares files/assets that may support future posts.

## Route the request before using tools

First distinguish a one-off content request from a recurring schedule change:

- “crea otro post”, “haz otra imagen”, “crea un video educativo”, “cambia el título”, “haz una variante” and similar instructions continue the current one-off creative workflow. Use Image 2 for images; for motion video use `mcp_admira_search_motion_graphic_recipes`, any needed Image 2 storyboard assets, and `mcp_admira_generate_motion_graphic_video`. Send the resulting media and stage the exact organic piece only after its image/video and caption are final.
- Call `mcp_admira_save_daily_social_content_settings` only when the buyer explicitly accepts, declines, enables, disables, or changes the recurring cadence, preparation time, quantity, or content strategy. Never call it merely to label, register, save, approve, generate, or revise one organic post.
- Never register a post as approved before generating and showing its final image/caption. The order is: generate -> deliver -> revise if requested -> stage exact draft -> natural-language approval -> publish.

If Image 2 returns a blocked/error result, explain that specific generation blocker briefly and stop that branch. Do not switch to recurring settings, invent an approval, or claim a post was registered as a workaround.

## Mandatory first-run organic strategy

Use this skill only after business discovery and the buyer-confirmed branding/logo foundation are complete, and before ads/campaign production. Do not ask the passive generic question “¿quieres contenido orgánico?”. Act as the buyer's marketing manager and proactively present a useful, tailored starting plan based on the business and brand facts already saved.

The proposal must contain:

- 2–4 content pillars that fit the niche;
- examples of post ideas under those pillars;
- a practical cadence recommendation;
- which posts Image 2 will design and when motion video would genuinely add clarity;
- that every piece arrives in Telegram as a draft for review and nothing visible is published without approval.
- a niche-specific daily mix rather than a universal template. For example, a local service business may benefit from education + one concrete service + proof/testimonial, while another niche may need a different mix. Choose the mix as the marketing expert.
- a short explanation that the buyer can send real photos at any time for named content vaults. Until suitable real assets exist, daily concepts that need imagery use clearly generated visual material instead of pretending to use real business/customer photos.

Use simple language. Facebook and branding are already ready before this strategy step, so the buyer may approve the plan or adjust it without another technical interruption. Then finish cadence setup. Never ask for a Meta token, System User, or app.

If the buyer accepts, save the acceptance immediately so resets do not cause the same offer again. Then finish the brand and content strategy, ask the preferred time, rough quantity, and cadence, defaulting to 1 post at 10:00 every 1 day in the buyer timezone. Save again with `mcp_admira_save_daily_social_content_settings` once the strategy is concrete:

```json
{
  "enabled": true,
  "time": "10:00",
  "posts_per_day": 1,
  "interval_days": 1,
  "content_formats": ["image", "motion_video"],
  "video_frequency_days": 7,
  "content_strategy": "short summary of pillars/cadence"
}
```

If they decline, save the decision with `enabled: false` so future resets do not re-ask immediately.

The product will not start the recurring cron until both branding and the content strategy are ready. An early yes is stored as `accepted_pending_setup`; after Facebook connection, continue with the next missing branding/strategy question instead of pretending the schedule is active.

## Buyer-shared files/assets

When the buyer uploads or links a file, image, video, logo, reference, testimonial, offer, local photo, product photo, or UGC material:

1. Use vision or `mcp_admira_fetch_public_asset` when needed.
2. Ask or infer what it is for. If unclear, ask: “¿Esto lo uso como logo oficial, foto real, referencia de estilo, prueba social, oferta, UGC o prefieres que no lo use?”
3. Categorize it and call `mcp_admira_save_content_asset`.

Telegram first archives every inbound image batch durably as pending. Analyze every attached image with vision, then call the save tool with the durable path(s) grouped by their real category and purpose. Use `preservation_mode: "pixel_locked"` for buyer-owned real photos/logos, `style_only` for inspiration, `pending_classification` only while a grouped clarification is still needed, and `prohibited` for do-not-use assets. A pending asset is stored safely but must not be selected by the daily content cron.

Recommended categories:

- `official_logo`
- `product`
- `location`
- `team_founder`
- `customer_testimonial`
- `ugc`
- `style_reference`
- `offer_promo`
- `social_proof`
- `do_not_use`
- `other`

Store the intended use in plain language: background, product proof, style direction, social post source, ad creative, testimonial, “do not use in ads,” etc.

### Buyer-named content vaults

Treat a vault as a logical collection inside the durable content-asset library, not as an ephemeral chat folder. When the buyer says “guarda esto en el vault de X”, preserve that intent in `vault_name`.

- Examples: `casos de testimonios`, `fotos de sucursal del negocio`, `servicio: detailing premium`, `producto: serum vitamina C`.
- If several files belong to one case/shoot, reuse the same `content_group`.
- If two images in one message are explicitly “antes” and “después”, save/classify both, keep the same vault/group, and distinguish them with `visual_role=before` and `visual_role=after`. Do not flatten the pair into an unlabeled batch.
- The buyer may add assets to these vaults at any time, outside onboarding. Classify and save them without restarting onboarding.
- Real buyer-owned photos remain `pixel_locked` and are preferred when a future organic concept actually calls for that vault/category and the asset is approved for daily content.
- If the relevant vault has no suitable approved real media, continue producing the organic proposal with AI-generated imagery. Never invent a real testimonial, real customer, real branch, real result, or real before/after.

## Content strategy

Build 3–5 pillars before generating regular posts. Read `brand_guides/Offer map.md` and separate pillars by brand-wide themes and active child offers/products/services. Good defaults:

- education/helpful tips;
- offer and promotion;
- proof/testimonials/results;
- behind-the-scenes or founder/local trust;
- objection handling;
- seasonal/community posts.

Before locking the strategy, discuss:

- which offers/services/products should receive content;
- which topics are educational, proof-based, promotional, community, objection-handling, or behind-the-scenes;
- whether the cadence should be daily or every X days;
- whether posts go to Facebook, Instagram, or both after buyer approval.
- whether the mix is image-only, motion-video-only, or adaptive; and a sensible video cadence. If the buyer does not know, propose a mix based on the niche, available assets, production value, and whether topics benefit from sequential explanation.

For each proposed post, include:

- pillar;
- visual idea;
- caption/copy;
- CTA;
- asset used, if any;
- why it fits the brand/business.

### Rolling 15-day novelty memory

Before preparing each recurring batch, read the last 15 days of `memory/organic_content_posts.json`. Compare at least: pillar, topic, offer/product/service, hook/headline, CTA, visual concept, asset/vault used, and format.

- Avoid near-duplicate ideas inside that rolling window, even if the wording changes.
- Repetition is a semantic judgment, not a keyword filter. A recurring pillar is expected; the underlying angle and execution should keep evolving.
- Around days 12–15, an early successful/useful idea may be recycled when appropriate, but reframe it materially with a new hook, example, visual treatment, audience objection, proof point, format, or CTA.
- Prefer novelty when a strong unused idea exists.

## Daily competitor-inspired paid creative

The recurring organic job also prepares one separate paid-ad candidate per day when public research can support it. This is not an organic post and must never be staged for organic publishing.

1. Use web/browser research on Meta Ad Library for the buyer's niche/market, known competitors, or comparable businesses solving the same customer problem.
2. Public evidence can show that an ad is active, repeated in variants, or apparently long-running. Treat those only as directional signals. Never claim Meta Ad Library reveals competitor CPA, ROAS, conversions, profitability, or a verified winner.
3. Require an exact public Meta Ad Library URL plus a real visual reference for the chosen ad. If either cannot be verified, skip that day's competitor-derived candidate rather than inventing a source.
4. Save/capture the public visual as a one-task `style_reference` with `preservation_mode=style_only`, `reference_scope=task`, and `approved_for_ads=false`. Store the exact source URL as provenance.
5. Extract only the transferable concept: angle, hook structure, hierarchy, proof type, layout, pacing/format, and composition. Do not copy competitor branding, logo, palette, photos/people, exact copy, claims, phone, price, promotion, or identifying content.
6. Generate an original paid-ad proposal through Image 2 with that task reference explicitly selected. Persistent `reference_scope=brand` references and the confirmed written brand guide remain attached and authoritative. Competitor inspiration controls only the day's angle/structure.
7. Deliver the generated image plus the exact Ad Library link and explain the observed public signal without claiming private performance.
8. Archive the generated file as `category=competitor_inspired_creative`, vault `propuestas competitivas para paid ads`, `creative_candidate_status=proposed`, `approved_for_ads=false`, and persist `source_reference_url`, source label, angle, structure, and observation date.
9. If the buyer later asks to save/use it for paid ads, search the exact candidate with `mcp_admira_search_content_assets` and update the same durable file to `approved_for_ads=true`, `creative_candidate_status=saved_for_paid`. That explicit request promotes the candidate; the daily cron never does.
10. Retrieval requests such as “muéstrame los creativos guardados basados en competencia” should use `mcp_admira_search_content_assets`, not the short three-day generated-creative recovery window.

## Image 2 production

For final daily post visuals, use `mcp_admira_codex_image_generate` through `creative-production-codex-image`.

- Use purpose `daily_social_post` or `organic_social_post`, not `standalone_creative` or a launch-ready campaign unless the buyer asks for an ad.
- Every image call must include one self-contained `request` with the exact active offer/topic, content pillar, objective, intended on-image message, 4:5 format, CTA decision, and the approved reference/style to follow. A generic call such as “usa las guías guardadas” or “crea un post con el branding” is forbidden: saved memory can contain older offers and must never replace the current post brief.
- Explicitly classify the post as education, proof/testimonial, community, objection handling, behind-the-scenes, or promotion. Do not turn every organic post into a direct-response ad. Prices, discounts, urgency, and commercial CTAs appear only for an explicitly promotional pillar.
- When approved references contain several directions, the most recently approved reference is the active visual direction. It overrides older generic style notes where they conflict; preserve non-conflicting brand colors, logo, typography, and restrictions.
- Use the official logo when appropriate and require `pixel-level accurate`.
- Select only classified assets approved for daily content; never use `do_not_use`, `prohibited`, or `pending_agent_review` items.
- If using a buyer-owned real photo/video frame, pass it in `protected_reference_image_paths` or select its `content_asset_ids`. The prompt must say `pixel by pixel accuracy`, `pixel-level accurate reproduction`, and `pixel-faithful`. Any used part of the real image must remain unchanged: no regeneration, retouching, relighting, recoloring, beautification, changed faces/products/text/objects, or reconstructed background. Cropping, scaling, positioning, framing, boundary masks, and overlays above/around the unchanged photo are allowed.
- Pass `style_reference` assets only as ordinary `reference_image_paths`; they guide style and are not required to preserve their exact content.
- Do not invent access to private links; ask the buyer to make them public or upload directly.
- Deliver the media directly in chat and avoid internal paths.

## Motion-video production

Use `skills/motion-graphics-video/SKILL.md` when the buyer asks for an organic video or the saved strategy allows motion and today's topic materially benefits from it.

- Choose motion for sequential education, demonstrations, comparisons, transformations, data stories, visual metaphors, announcements, or emotionally paced storytelling—not merely to make every post move.
- Search the complete Shotcraft catalog first with `mcp_admira_search_motion_graphic_recipes`.
- Use Image 2 only for missing full-frame images, brand elements, and story subjects/props required by the storyboard.
- Render with `mcp_admira_generate_motion_graphic_video`; inspect the actual MP4 and revise if readability, contrast, pacing, composition, or branding is weak.
- For recurring generation, obey the saved `content_formats` and `video_frequency_days`. When the strategy is image-only, a cron may propose adding motion but must not silently change settings or generate scheduled videos before the buyer accepts.
- For a direct one-off buyer request, generate the video without changing recurring settings.
- Deliver the MP4 in chat, then stage it with `mcp_admira_stage_organic_social_post` using `video_path` and the exact caption.

## Approval and publishing

Daily content is draft-first:

- generate or propose;
- send media/caption directly in Telegram;
- call `mcp_admira_stage_organic_social_post` once for each exact final image-or-video/caption pair;
- ask the buyer to reply simply `aprobado`, request changes, or discard; never expose the internal approval ID;
- internally retain the exact approval returned by the tool and, when the buyer approves that piece, call `mcp_admira_approve_action` with that hidden approval ID;
- publish only through that protected approval. Never call a raw Page-post action or claim publication before the approval result contains the real Meta post ID.

If the buyer requests changes, generate/revise the piece and stage a new exact draft. The previous draft remains unpublished and must not be silently reused.

The first supported direct destination is the connected Facebook Page. Do not promise Instagram direct publishing unless a product tool explicitly confirms it.

Present the feature as “posts listos para aprobar” or “tu calendario de contenido diario”, not as a technical cron job.

## Unified strategy activation
When the confirmed strategic plan contains organic_content_strategy and organic_daily_plan, that same acceptance approves the organic direction. Persist its exact strategy and cadence through mcp_admira_save_daily_social_content_settings with enabled=true; ask only for a genuinely missing delivery preference. Use the account timezone and the configured delivery time when no different time was requested. Never ask for a second approval of the same strategy. Recurring delivery is distinct from publishing each post on Meta.

Record every delivered proposal with mcp_admira_record_organic_content_proposal even when direct publishing is disconnected. Record pillar, topic, offer, hook, CTA, visual concept, format and vault/asset IDs, not just published posts.
