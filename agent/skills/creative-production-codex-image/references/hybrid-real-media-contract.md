---
name: hybrid-real-media-contract
description: Contract for composing Image 2 graphic overlays with ordered buyer-owned real photos and programmatic logos.
---

# Hybrid real-media contract

Use this reference only when a creative combines an Image 2-generated graphic overlay with one or more buyer-owned photos. The generation provider and existing Codex/Image bridge are unchanged.

## Request shape

The natural-language manager supplies a self-contained visual direction and an ordered payload equivalent to:

```json
{
  "layout_intent": "hero|before_after|services|collage|freeform",
  "visual_direction": "...the agreed composition, hierarchy, copy, bullets and CTA...",
  "real_media": [
    {"slot_id": "before", "asset_id": "asset-1", "label": "ANTES", "role": "before"},
    {"slot_id": "after", "asset_id": "asset-2", "label": "DESPUÉS", "role": "after"}
  ],
  "logo_color_mode": "original|white|black|brand_primary|brand_secondary|auto_contrast",
  "style_reference": {"mode": "none"}
}
```

`slot_id` order is authoritative. The backend resolves each asset and inserts it into the matching keyed region; never infer a slot from visual similarity after generation.

## Layout semantics

- One source: a hero/photo-led composition.
- Two sources with an established before/after relationship: two distinct slots labelled accordingly.
- Two sources without that relationship: two independent service/product slots.
- Three to six sources: collage, mosaic, cards, or another freeform composition described by the manager. Do not force before/after semantics.

The manager may ask for another variation. Keep the same required facts and slot mapping while allowing a materially different composition. Do not add a deterministic keyword classifier to decide whether a buyer meant “reference.”

## Image 2 overlay requirements

Image 2 receives no buyer-owned real photo and no official logo in hybrid mode. It receives only the agreed visual direction, brand palette/style, copy/title/bullets/CTA, and a mapping such as:

```text
SLOT before = saturated magenta placeholder
SLOT after  = saturated cyan placeholder
```

The prompt must request flat, solid, highly saturated placeholder regions, no gradients or texture inside them, no logo, and no photographic recreation. Placeholder colors must be selected outside the brand hue families. Exact RGB is not guaranteed; tolerant clustering is required.

## Composition and validation

After Image 2 returns the overlay:

1. Detect each keyed color using a tolerance suitable for Image 2's small color shifts.
2. Select the intended connected component for each slot and reject missing, duplicated, overlapping, or contaminated slot masks.
3. Insert the exact source photo associated with that `slot_id`; crop, scale, position, frame, and mask boundaries are allowed, but photo content is pixel-locked.
4. Composite the saved logo programmatically in the requested render mode.
5. Inspect the final bitmap and attach it. OCR may be advisory only; stylized text should not be blocked solely by weak OCR.

## References

By default pass `style_reference: {"mode": "none"}`. Only when the buyer explicitly asks to use saved graphic-design references, pass `{"mode": "pool"}` and select one eligible `style_reference` from the shuffle pool without immediate repetition. An explicitly named reference uses `{"mode": "explicit", "asset_id": "..."}` and wins over the pool. Real photos and official logos are never eligible style references.
