# Keyframe To Motion Pipeline

This is the higher-quality motion workflow for the content factory.

The goal is not to let an image model bake finished social posts with text. The goal is to use the image model as an art director for visual keyframes, then rebuild the important pieces as editable Remotion layers.

## Why This Is Better

Image models are strong at:

- rich composition
- mood
- texture
- background depth
- brand-world exploration
- product/subject staging

Remotion is stronger at:

- crisp typography
- exact Spanish copy
- consistent logo placement
- reusable animation systems
- versioning
- Postiz-ready MP4 rendering

So the pipeline should separate those responsibilities.

## Recommended Flow

1. Content strategy creates the message:
   - hook
   - body
   - mechanism
   - CTA
   - platform
   - buyer stage

2. Image model creates text-free keyframes:
   - no embedded copy
   - no fake UI text
   - no distorted logo
   - Ad+-inspired palette and composition
   - clear empty text-safe areas

3. Visual analysis creates a layer manifest:
   - background plate
   - angular planes
   - halftone/grid texture
   - glow areas
   - hero subject or product area
   - logo zone
   - text-safe zone
   - motion direction

4. Optional extraction creates raster layers:
   - foreground person/product cutout
   - gradient background plate
   - texture overlays
   - abstract 3D shapes

5. Remotion rebuilds the final video:
   - text added as live type
   - logo added as code/vector
   - key raster layers animated independently
   - planes and overlays recreated as code-native elements
   - final MP4 goes to review

## Prompt Rules For Image Keyframes

Think visually, not as a poster with text.

Use:

```text
Create a text-free vertical key visual for a premium technology brand called Ad+.
Use deep violet, electric purple, soft lavender, pale peach, fresh green, and restrained teal accents.
Use angular geometric planes, subtle halftone texture, futuristic editorial composition, soft glow, and premium tech-brand lighting.
Leave clean negative space for Spanish headline and CTA that will be added later in Remotion.
No readable text, no fake UI labels, no watermark, no distorted logo, no typography.
```

Avoid:

- baked-in Spanish copy
- fake dashboards with unreadable text
- distorted logos
- random neon cyberpunk
- generic AI stock style
- cluttered backgrounds where text cannot breathe

## Layer Manifest Schema

Each generated keyframe should receive a manifest like:

```json
{
  "schema": "meta-ads-agent.keyframe-layer-map.v1",
  "source_image": "output/content-factory/YYYY-MM-DD/keyframes/item_hero.png",
  "brand": {
    "palette": ["#230052", "#5B13B8", "#DCCBFF", "#FFD0CB", "#C7F1B7", "#0D6E62"],
    "font_direction": "geometric futuristic, Orbitron fallback until real Ad+ font is available"
  },
  "text_safe_zones": [
    {"name": "headline", "x": 80, "y": 500, "w": 860, "h": 460},
    {"name": "cta", "x": 80, "y": 1260, "w": 720, "h": 140}
  ],
  "layers": [
    {"id": "background_plate", "type": "raster", "path": "background.png", "motion": "slow_scale"},
    {"id": "violet_plane", "type": "vector_plane", "color": "#3B008C", "motion": "diagonal_slide"},
    {"id": "peach_plane", "type": "vector_plane", "color": "#FFD0CB", "motion": "parallax"},
    {"id": "halftone", "type": "procedural_texture", "motion": "drift"},
    {"id": "hero_cutout", "type": "raster_cutout", "path": "hero.png", "motion": "float"}
  ]
}
```

## Automation Boundary

Daily automation may generate:

- strategy copy
- keyframe prompts
- Remotion videos from existing templates
- layer manifests

Daily automation should not silently approve or post.

When image keyframes are generated, they should enter review before being promoted into the reusable Remotion style library.

## Next Technical Steps

1. Generate 2-3 keyframe concepts per content format.
2. Select one brand direction.
3. Create a reusable `brand_layers.json` from that direction.
4. Add a Remotion composition that consumes:
   - live Spanish text
   - `brand_layers.json`
   - optional extracted raster layers
5. Add a visual QA step:
   - screenshot frame 0, 8s, 16s, 23s
   - check text contrast
   - check no baked-in wrong text
   - check safe areas
