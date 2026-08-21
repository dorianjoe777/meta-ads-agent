# video-shotcraft attribution

Admira IA includes the text/source reference corpus from `video-shotcraft` and
modified, parameterized adaptations of selected components and motion recipes:

- Upstream: https://github.com/Vincentwei1021/video-shotcraft
- Author: Vincent Wei and contributors
- License: Apache License 2.0 (see `LICENSE` in this directory)
- Local adapted code: `src/remotion/shotcraft/ShotRecipes.tsx`
- Vendored on-demand card/demo references:
  `agent/skills/motion-graphics-video/references/shotcraft/`

Changes include a bounded JSON storyboard contract, brand and child-offer
overrides, arbitrary social aspect ratios, safe local-media resolution,
pixel-preservation rules, compatibility layering, and removal of upstream
product-specific content from the parameterized runtime components. The
vendored cards/demos remain unmodified reference material except for omitted
audio and large preview-media files.

No upstream sound-effect or music files are redistributed. Buyer-supplied
audio is accepted only through Admira's existing safe local-asset contract.

Remotion itself is used under Remotion's own current license terms and is not
covered by the Apache-2.0 license above.
