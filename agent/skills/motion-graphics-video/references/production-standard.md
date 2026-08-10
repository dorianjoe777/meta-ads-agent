# Production standard

## Determinism and safety

- All animation is driven by Remotion frame values and explicit easing. No CSS animation/transition, current time, network-dependent layout, or unseeded randomness.
- The model normally provides data through the bounded storyboard schema. A full-catalog Shotcraft scene may additionally provide the narrowly validated `compiled_recipe_source` JSX body described by the skill. It has no imports, network/file access, timers, global objects, raw media URLs, or direct execution path; it is isolated to one job and capability-checked before bundling.
- Use only safe local buyer-media roots and copied render assets. Render concurrency is one by default.

## Composition

- Use explicit sequences and premount scenes.
- Keep type readable on a phone and shorten/split dense copy.
- Maintain safe margins for social UI.
- Do not stretch logos or media. Use `contain` when the full asset must remain visible.
- No retouching, filtering, recoloring, regeneration, or content alteration of protected media.

## QA

- Render a representative still plus the complete MP4.
- Verify codec, dimensions, duration, and non-empty output with ffprobe.
- Review the first hook, each scene midpoint, every transition, and the final hold.
- Confirm exact active offer, factual copy, spelling, logo, palette, aspect ratio, and CTA.
- Final render failure never becomes a claim that a video was created.

## Installation/runtime

- All Remotion packages use the exact same pinned version.
- The buyer release installs dependencies at build time; Hermes does not install or upgrade them.
- Production maintainers can update the pinned version only after contract, render, media, packaging, and canary tests pass.
