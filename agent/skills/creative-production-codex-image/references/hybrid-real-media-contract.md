---
name: hybrid-real-media-contract
description: Contract for composing Image 2 graphic overlays with ordered buyer-owned real photos and programmatic logos.
---

# Hybrid real-media contract

Use this reference only when a creative combines an Image 2-generated graphic overlay with one or more buyer-owned photos. The generation provider and existing Codex/Image bridge are unchanged.

Before building this technical request, apply [hybrid-prompt-refinement-playbook.md](hybrid-prompt-refinement-playbook.md). It defines how a short natural buyer request becomes a rich brand/offer-aware visual direction. That semantic refinement does not change the slot or source-integrity rules below.

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
  "style_reference": {"mode": "explicit", "asset_id": "one-off-style-reference"}
}
```

`slot_id` order is authoritative. The backend resolves each asset and inserts it into the matching keyed region; never infer a slot from visual similarity after generation.

For photos attached in the current buyer turn, inspect and classify the whole batch first with `mcp_admira_save_content_asset`, using `pixel_locked` and making the semantic `approved_for_ads` decision from the buyer's actual requested use. Feed the returned IDs directly into `real_media`. If an older model/client omits that optional boolean, the backend may issue a five-minute, exact-ID capability bound to the same trusted chat/session/message; it is not permanent ad approval, cannot cross turns, and is consumed only after a successful hybrid composition. A provider failure leaves it available for a same-turn retry.

Hermes CLI versions that accept only one visual attachment may send a labelled `hermes-attachments-contact-sheet-<turn>.png`. This is a vision transport artifact, never a source asset. Classify/save the attached transport image once; the backend validates the turn-specific sheet, expands it to the ordered originals, and returns their individual IDs. Use those IDs for `real_media`. Never composite the contact sheet itself.

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

If a model accidentally falls back to ordinary generation with the exact IDs from the current same-turn receipt, the backend returns `hybrid_required` without invoking Image 2. Retry the same request with `real_media`. This narrow compatibility behavior does not affect durable approved assets or ordinary requests from another turn.

Any hybrid error receipt may include a `retry_contract`. Preserve its `layout_intent`, every ordered `real_media` item and the same style-reference policy exactly. Never remove photos, change roles, or collapse a collage/services request into a hero just because the first overlay failed. Only a later explicit buyer correction may change that semantic contract.

## References

Omit `style_reference` by default: the backend then attaches every approved `reference_scope: "brand"` reference saved during branding. A reference supplied only for the current creative is saved with `reference_scope: "task"` and selected using `{"mode": "explicit", "asset_id": "..."}`; it is attached together with persistent brand references and does not mutate them. Use `{"mode": "none"}` only when the buyer explicitly asks to suppress references for one generation. `pool` is a compatibility alias for the complete persistent brand set, not a shuffle. Real photos and official logos are never eligible style references. References guide visual language only; confirmed branding and exact offer facts always take precedence.
