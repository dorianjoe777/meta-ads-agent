# Shotcraft recipe storyboards

Use recipes as motion grammar, not as a new brand skin. Colors, typography, surface treatment, rhythm, and logo use always come from the parent brand plus active child offer.

The vendored gallery contains all 152 cards and 209 motion styles/previews. The names below are only the faster parameterized subset. Any other exact card/style remains available through the validated job-scoped adaptation route described in `../SKILL.md`; do not treat this list as a catalog limit.

## Composition model

- One dominant layer: base, camera, or typography.
- Up to two compatible accent layers.
- At most one transition.
- Maximum four recipe names per scene.
- Use `template=ink-press` for a coordinated paper/ink sequence with title stamping, 2.5D media movement, card insertion, controlled highlights, and a final lockup. Branding still overrides colors, logo, typography direction, offer, and pacing.

Useful fast-path combinations:

- Screenshot/product education: `page-cam-2.5d` + `scanline-annotate-focus` + `flash-cut`.
- Product reveal: `product-card-progressive-assemble` + `spotlight-sweep`.
- Metric: `odometer-digit-roll` + `halation-bloom`.
- High-energy hook: `crash-zoom-punch` + `brand-frame-snap` + `whip-pan`.
- Editorial statement: `paper-title-card` + `marker-underline-title` + `ink-bleed-reveal`.
- Tutorial: `list-stack-press`, followed by a separate `before-after-slider-scrub` scene.

Fast-path dominant recipes include `brand-ink-open`, `paper-title-card`, `page-cam-2.5d`, `multiplane`, `crash-zoom-punch`, `card-stack`, `deck-deal-flyin`, `row-embed`, `list-stack-press`, `odometer-digit-roll`, `before-after-slider-scrub`, `gradient-word-sweep`, `marker-underline-title`, `radial-wave`, `product-card-progressive-assemble`, `page-waterfall-wall`, and `cta-ink-lockup`.

Fast-path accents/transitions include `brand-frame-snap`, `scanline-annotate-focus`, `spotlight-sweep`, `halation-bloom`, `flash-cut`, `whip-pan`, and `ink-bleed-reveal`.

## Scene mapping

- `editorial-reveal`: strong hook or statement; large type rises into place, then holds.
- `card-cascade`: short list; cards enter in sequence and stop moving before the viewer must read them.
- `step-stack`: ordered tutorial; numbered blocks build a clear process.
- `stat-focus`: one verified number; the statistic is the only hero element.
- `split-compare`: before/after, myth/reality, wrong/right, or option A/B.
- `quote-frame`: one verified quote with attribution and generous whitespace.
- `spotlight-media`: approved photo, footage, screenshot, product, or location is the focal point; overlays explain it without altering it.
- `cta-lockup`: brand/offer and one next action settle into a clean final frame.

## Selection rules

- Do not repeat the same hero motion in consecutive scenes.
- One shot communicates one idea. Split dense copy into scenes instead of shrinking it.
- Use motion to direct attention, not decorate every element.
- Opening focal action normally receives about three seconds; important final states hold at least half a second, and a brand lockup about one second when duration permits.
- Prefer a purposeful hard cut or subtle exit over a flashy transition that competes with the message.
- A buyer-selected recipe constrains motion, not brand styling.

## By objective

- Education/explainer: `editorial-reveal` → `card-cascade` or `step-stack` → `stat-focus`/`split-compare` → `cta-lockup`.
- Tutorial: hook → two to five `step-stack` points → result → CTA.
- Promotion: hook → `spotlight-media` → benefit/proof → offer → CTA.
- Social proof: verified `quote-frame` or `stat-focus` → explanation → CTA. Never invent proof.
- Announcement: reveal → what changes → who benefits → date/action.
