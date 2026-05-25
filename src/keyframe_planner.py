#!/usr/bin/env python3
"""Plan image-model keyframes and layer maps for Remotion content."""
import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "dashboard" / "data"
QUEUE_FILE = DATA_DIR / "content_queue.json"
CONTENT_ROOT = ROOT_DIR / "output" / "content-factory"


PALETTE = ["#230052", "#5B13B8", "#DCCBFF", "#FFD0CB", "#C7F1B7", "#0D6E62"]


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path, fallback):
    if not path.exists():
        return fallback
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return fallback


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)


def prompt_for_item(item):
    copy = item.get("copy", {})
    strategy = item.get("strategy", {})
    return f"""Create a text-free vertical key visual for a premium technology brand called Ad+.

Brand direction:
- deep violet and electric purple base
- soft lavender and pale peach light planes
- fresh green background accents
- restrained teal details
- angular geometric planes
- subtle halftone or micro-grid texture
- futuristic editorial tech-brand composition
- premium, clean, high-design, not generic stock AI

Content intent:
- Spanish hook to be added later in Remotion: "{copy.get("headline", "")}"
- Message: "{copy.get("body", "")}"
- Strategic pillar: {strategy.get("pillar", "")}

Composition requirements:
- 1080x1920 vertical social video keyframe
- leave clean negative space for live Spanish headline and CTA
- strong foreground/background depth with separable visual elements
- include areas that can become independent motion layers

Strict avoid:
- no readable text
- no fake UI labels
- no distorted logos
- no watermark
- no baked-in Spanish copy
- no clutter in headline safe zone
"""


def layer_manifest_for_item(item, source_image=""):
    item_id = item.get("id", "unknown")
    return {
        "schema": "meta-ads-agent.keyframe-layer-map.v1",
        "item_id": item_id,
        "created_at": now_iso(),
        "source_image": source_image,
        "brand": {
            "palette": PALETTE,
            "font_direction": "geometric futuristic, Orbitron fallback until the real Ad+ font is available",
        },
        "text_safe_zones": [
            {"name": "headline", "x": 80, "y": 470, "w": 860, "h": 500},
            {"name": "body", "x": 80, "y": 940, "w": 860, "h": 330},
            {"name": "cta", "x": 80, "y": 1320, "w": 720, "h": 150},
        ],
        "layers": [
            {
                "id": "background_plate",
                "type": "raster_or_gradient",
                "preferred_motion": "slow_scale_and_blur_depth",
                "notes": "Use generated keyframe as reference or extracted raster plate.",
            },
            {
                "id": "violet_angular_plane",
                "type": "vector_plane",
                "color": "#3B008C",
                "preferred_motion": "diagonal_slide_in",
            },
            {
                "id": "lavender_light_plane",
                "type": "vector_plane",
                "color": "#DCCBFF",
                "preferred_motion": "parallax_sweep",
            },
            {
                "id": "peach_highlight_plane",
                "type": "vector_plane",
                "color": "#FFD0CB",
                "preferred_motion": "soft_mask_reveal",
            },
            {
                "id": "halftone_texture",
                "type": "procedural_texture",
                "color": "#5B13B8",
                "preferred_motion": "slow_drift",
            },
            {
                "id": "hero_subject_or_product",
                "type": "optional_raster_cutout",
                "preferred_motion": "float_and_scale",
                "notes": "Extract only if the generated keyframe includes a useful person, product, or 3D object.",
            },
        ],
        "remotion_animation": {
            "opening": "brand planes slide and glow into place",
            "middle": "text-safe zone stabilizes while background layers drift",
            "transition": "diagonal metallic sweep between message beats",
            "cta": "arrow/pill enters with spring, logo locks up",
        },
    }


def plan_keyframes(status="needs_review", attach=True):
    queue = read_json(QUEUE_FILE, {"items": []})
    items = [item for item in queue.get("items", []) if item.get("type") == "motion"]
    if status:
        items = [item for item in items if item.get("status") == status]
    out_dir = CONTENT_ROOT / date.today().isoformat() / "keyframe-plans"
    out_dir.mkdir(parents=True, exist_ok=True)
    plans = []
    for item in items:
        item_dir = out_dir / item["id"]
        item_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = item_dir / "image-model-prompt.txt"
        manifest_path = item_dir / "layer-manifest.json"
        prompt_path.write_text(prompt_for_item(item), encoding="utf-8")
        manifest = layer_manifest_for_item(item)
        write_json(manifest_path, manifest)
        plan = {
            "status": "planned",
            "prompt_path": str(prompt_path),
            "manifest_path": str(manifest_path),
            "source_image_path": "",
            "layer_manifest_schema": manifest["schema"],
            "updated_at": now_iso(),
        }
        if attach:
            item["keyframe_pipeline"] = plan
            item["updated_at"] = now_iso()
        plans.append({"item_id": item["id"], **plan})
    index_path = out_dir / "index.json"
    write_json(index_path, {"created_at": now_iso(), "plans": plans})
    if attach:
        write_json(QUEUE_FILE, queue)
    return {"count": len(plans), "index_path": str(index_path), "plans": plans}


def main():
    parser = argparse.ArgumentParser(description="Create image-model keyframe prompts and layer manifests.")
    parser.add_argument("--status", default="needs_review")
    parser.add_argument("--no-attach", action="store_true", help="Do not write keyframe fields back into the content queue")
    args = parser.parse_args()
    print(json.dumps(plan_keyframes(args.status, attach=not args.no_attach), indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
