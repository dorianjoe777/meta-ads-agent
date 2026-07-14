---
name: organic-content-strategy
description: Plan and run Admira IA organic social content: optional daily Image 2 posts, content pillars, buyer-shared asset categorization, captions, approval flow, and direct publishing handoff.
---

# Organic Content Strategy Skill

Use this skill when the buyer asks for social posts, daily content, content calendars, organic publishing, or shares files/assets that may support future posts.

## Optional onboarding offer

After business basics and brand/logo/assets are reasonably clear, ask once only when no durable decision exists:

“¿Quieres que también te prepare posts con tu marca, diarios o cada X días, para revisar y aprobar?”

Explain it simply: Admira can use the saved brand, logo, photos, videos, references, and offers to propose daily posts with Image 2, captions, and a small content strategy. It does not publish automatically unless the buyer later approves and Publicación directa is connected.

If brand/logo/colors/references/assets are not clear, do not jump into a content calendar. Start or continue `memory/Branding onboarding.md` first: logo decision, colors, style references, tone, real photos/videos/assets, and font/style direction.

If yes, save the acceptance immediately so resets do not cause the same offer again. Then finish the brand and content strategy, ask the preferred time, rough quantity, and cadence, defaulting to 1 post at 10:00 every 1 day in the buyer timezone. Save again with `mcp_admira_save_daily_social_content_settings` once the strategy is concrete:

```json
{
  "enabled": true,
  "time": "10:00",
  "posts_per_day": 1,
  "interval_days": 1,
  "content_strategy": "short summary of pillars/cadence"
}
```

If no, save the decision with `enabled: false` so future resets do not re-ask immediately.

The product will not start the recurring cron until both branding and the content strategy are ready. An early yes is stored as `accepted_pending_setup`; continue with the next missing branding/strategy question instead of pretending the schedule is active.

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

For each proposed post, include:

- pillar;
- visual idea;
- caption/copy;
- CTA;
- asset used, if any;
- why it fits the brand/business.

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

## Approval and publishing

Daily content is draft-first:

- generate or propose;
- send media/caption directly in Telegram;
- call `mcp_admira_stage_organic_social_post` once for each exact final image/caption pair;
- show its exact approval ID and ask approve/change/discard;
- if the buyer approves that exact piece, call `mcp_admira_approve_action` with its approval ID;
- publish only through that protected approval. Never call a raw Page-post action or claim publication before the approval result contains the real Meta post ID.

If the buyer requests changes, generate/revise the piece and stage a new exact draft. The previous draft remains unpublished and must not be silently reused.

The first supported direct destination is the connected Facebook Page. Do not promise Instagram direct publishing unless a product tool explicitly confirms it.

Present the feature as “posts listos para aprobar” or “tu calendario de contenido diario”, not as a technical cron job.
