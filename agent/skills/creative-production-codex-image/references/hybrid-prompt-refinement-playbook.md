---
name: hybrid-prompt-refinement-playbook
description: Semantic prompt-refinement patterns for dynamic Image 2 overlays that preserve buyer-owned real photos.
---

# Hybrid prompt refinement playbook

Use this reference before a hybrid `mcp_admira_codex_image_generate` call. Its purpose is to let a buyer write naturally—even something as short as “haz un diseño atractivo con estas fotos”—while the manager supplies the complete art direction Image 2 needs.

This is a semantic prompt scaffold, not a fixed visual template and not a conversational filter. Never show placeholders to the buyer, require the buyer to fill a technical form, or add a separate approval ceremony. Preserve every explicit buyer instruction and complete only the missing art-direction details from confirmed context.

## Context priority

Build the refined request in this order:

1. The buyer's latest visual instructions and corrections.
2. The exact active child offer/product and its confirmed facts.
3. Exact on-image text, CTA, and slot labels already agreed in the conversation or ad brief.
4. The saved parent-brand identity: name, palette, typography, visual style, tone, restrictions, and official logo decision.
5. The campaign/content objective, audience, format, and destination.
6. Safe creative judgment only for missing composition details.

Do not borrow price, promise, promotion, audience, CTA, proof, or benefits from another saved offer. Do not invent a discount, guarantee, testimonial, credential, measurable result, or business fact. If a nonessential fact is unknown, omit it. If the buyer explicitly adds a badge, bullet, feature, layout idea, safe area, or other visual element, include it; explicit buyer direction overrides a default below.

## Semantic scaffold

Translate the conversation into this internal structure before calling the MCP. Replace every bracketed value with real confirmed context and omit empty sections:

```text
ACTIVE OFFER
[ACTIVE_OFFER_NAME]
[CONFIRMED_PRICE_OR_PROMOTION_IF_RELEVANT]
[CONFIRMED_BENEFIT_OR_FEATURES]

OBJECTIVE AND AUDIENCE
[COMMUNICATION_OBJECTIVE]
[CONFIRMED_AUDIENCE]
[DESTINATION_OR_CTA_INTENT]

VISUAL DIRECTION
[ONE CLEAR CREATIVE IDEA]
[COMPOSITION_AND_HIERARCHY]
[MOOD_ENERGY_AND_GRAPHIC_TREATMENT]
[SAFE_AREAS_OR_PLACEMENT_NEEDS]
[ANY_EXTRA_DETAIL_REQUESTED_BY_BUYER]

BRANDING
[BRAND_NAME]
[BRAND_PALETTE]
[TYPOGRAPHY_STYLE]
[VISUAL_STYLE_AND_TONE]
[SHOW_ALWAYS]
[AVOID_ALWAYS]
Official logo: omit from Image 2 and let the backend insert the saved file.

ON-IMAGE TEXT
Title: [TITLE]
Subtitle: [SUBTITLE]
Body: [SHORT_BODY_IF_NEEDED]
Bullets: [UP_TO_THREE_SHORT_CONFIRMED_FEATURES_OR_BENEFITS]
CTA: [CTA_OR_EXPLICITLY_NONE]
Slot labels: [ORDERED_LABELS]

REAL MEDIA
[SLOT_ID] = [ROLE], [LABEL], [DURABLE_ASSET_ID]

FORMAT
[1:1 | 4:5 | 9:16 | OTHER_CONFIRMED_FORMAT]

STYLE REFERENCE
[none by default | pool only when explicitly requested | explicit selected reference]

VARIATION FREEDOM
Preserve facts, copy constraints, branding, and slot order. Create a fresh solution by varying composition, hierarchy, framing, card geometry, negative space, typography arrangement, accents, and CTA treatment.
```

The MCP/backend also reconstructs this context from saved brand and explicit offer fields when the main model leaves an optional field sparse. Still send the richest accurate structure available; the fallback is protection against omission, not a reason to discard the conversation.

## Layout families

Choose the family semantically from the relationship among the supplied photos. These are creative families, not fixed arrangements.

### `hero`: one real photo

Use one dominant media window and build the message around it. Image 2 may choose full bleed, offset crop, editorial frame, arch, diagonal, layered card, or another fresh geometry. Keep the title readable in under two seconds and preserve space for an optional programmatic logo.

Reference form:

```text
Create a [FORMAT] [MOOD] advertising design for [ACTIVE_OFFER]. Use [BRAND_STYLE], [PALETTE], and [TYPOGRAPHY]. Make the single protected photo the visual hero inside one clean keyed window. Establish a clear title → supporting benefit → CTA hierarchy. Include [EXTRA_BUYER_DETAILS]. Do not draw a logo or recreate photography.
```

### `before_after`: exactly two photos with an established relationship

Make the transformation unmistakable while keeping `before` and `after` mapped to their exact sources. The treatment may be an equal split, diagonal comparison, result-dominant layout, reveal, or overlapping cards. Keep `ANTES` and `DESPUÉS` outside the keyed windows.

Reference form:

```text
Create a [FORMAT] transformation ad for [ACTIVE_OFFER]. Show two unmistakable keyed windows: [BEFORE_SLOT] labelled ANTES and [AFTER_SLOT] labelled DESPUÉS. Use [BRAND_STYLE] and [PALETTE], with [TITLE], [SHORT_PROOF_OR_BENEFITS], and [CTA]. Make the result visually dominant without changing either source photo. Do not draw a logo.
```

Never choose this family merely because two files exist. The conversation or inspected content must establish before/after semantics.

### `services`: two to six independent services/products

Give each service a distinct, correctly labelled window. Image 2 may use an asymmetric editorial split, staggered cards, bands, modular tiles, or another coherent system. Never imply a transformation timeline.

Reference form:

```text
Create a [FORMAT] multi-service ad for [BRAND_NAME]. Present [SERVICE_1] and [SERVICE_2...] as distinct choices using ordered keyed windows and labels outside each window. Use [BRAND_STYLE], [PALETTE], a unifying title, concise confirmed benefits, and [CTA]. Vary card scale and hierarchy so the design feels custom rather than templated. Do not draw a logo.
```

### `collage`: three to six real photos

Use a coherent mosaic with either one anchor image and supporting details or a balanced editorial grid. Vary crop-window geometry, rhythm, overlap, captions, and scale while preserving every slot's mapping.

Reference form:

```text
Create a [FORMAT] editorial collage for [ACTIVE_OFFER] using [NUMBER] ordered keyed media windows. Use one visual anchor plus supporting moments, or a balanced mosaic when the buyer requests equal emphasis. Apply [BRAND_STYLE], [PALETTE], [TITLE], [BULLETS], and [CTA]. Keep every label outside its window, avoid clutter, and do not draw a logo.
```

### `freeform`: one to six photos with a specific conversational concept

Use when the buyer and manager have defined a composition that does not fit the other families. Describe the concept precisely, retain every ordered slot, and allow Image 2 to solve the artwork around those constraints.

## Text refinement

- If exact `text_content` exists, pass it structurally and preserve its facts and wording.
- If the buyer asks for a draft but has not supplied on-image wording, propose a concise title, up to three short confirmed features/benefits, and a fitting CTA from the active offer. Generated wording remains a proposal; never label it approved.
- Do not copy the full primary ad caption into the image. On-image copy should be short and legible unless the buyer explicitly requests a text-heavy design.
- Labels belong outside the keyed media windows. No text, icons, patterns, shadows, borders, or artwork may contaminate a keyed window.

## Dynamic variations

A request such as “otra variante” should reuse the current offer, media order, confirmed wording constraints, and branding while producing a materially different composition. Do not ask the buyer to choose a template family again unless their new request changes the relationship among the photos.

Possible variation axes include:

- full-bleed versus framed hero;
- symmetric versus asymmetric hierarchy;
- diagonal versus vertical comparison;
- editorial bands versus floating cards;
- anchor-image collage versus balanced mosaic;
- restrained versus high-energy accents;
- compact CTA chip versus wide CTA bar;
- typography-led versus photo-led hierarchy.

Do not randomly change brand colors, facts, offers, photo roles, or required copy. Randomness applies to presentation, not business truth.

## References, real photos, and logo

- `style_reference.mode` is `none` unless the buyer naturally asked to use saved design references.
- `pool` selects one eligible graphic-design reference through the shuffle pool; `explicit` uses the named reference.
- A real photo or logo is never a style reference.
- Real photos remain pixel-locked and never enter Image 2 in hybrid mode.
- Image 2 must omit the logo. The backend inserts the saved official logo in its requested deterministic color/position variant.
