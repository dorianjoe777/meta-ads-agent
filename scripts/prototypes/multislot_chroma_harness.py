#!/usr/bin/env python3
"""Standalone prototype for composing several real-image chroma slots.

This is intentionally outside the product runtime.  The overlay is produced by
Image 2 (or a fixture); this script only keys slot colours and composites the
source media deterministically.
"""
from __future__ import annotations

import argparse
import colorsys
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def choose_key_colors(count: int, brand_palette: list[tuple[int, int, int]] | None = None) -> list[tuple[int, int, int]]:
    """Choose chroma keys away from brand hues and from one another.

    RGB distance alone considers lime and green sufficiently different in some
    cases, even though both can key out parts of a green brand.  Saturated
    brand colours therefore reserve a hue neighbourhood before the greedy
    RGB/hue-separated selection begins.
    """
    brand = brand_palette or []
    candidates = [
        (0, 255, 0), (255, 0, 255), (0, 220, 255), (255, 70, 0),
        (130, 0, 255), (255, 235, 0), (0, 255, 150), (255, 0, 90),
        (30, 255, 255), (255, 120, 0), (120, 255, 0), (210, 0, 255),
        (20, 70, 255), (255, 25, 60), (255, 0, 200),
    ]
    def d(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))
    def hsv(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
        return colorsys.rgb_to_hsv(*(channel / 255 for channel in rgb))
    brand_hues = [hsv(c)[0] for c in brand if hsv(c)[1] >= 0.45]
    hue_exclusion = 60 / 360
    min_key_hue_separation = 25 / 360
    picked: list[tuple[int, int, int]] = []
    for _ in range(count):
        options = []
        for candidate in candidates:
            if candidate in picked:
                continue
            hue, sat, _ = hsv(candidate)
            if any(hue_distance(hue, brand_hue) < hue_exclusion for brand_hue in brand_hues):
                continue
            if any(hue_distance(hue, hsv(other)[0]) < min_key_hue_separation for other in picked):
                continue
            options.append(candidate)
        if not options:
            raise ValueError(f"Unable to choose {count} keys with hue separation from brand palette")
        # Use the minimum RGB distance as a tie-breaker after hue filtering.
        best = max(options, key=lambda c: min([d(c, p) for p in brand + picked] or [999.0]))
        picked.append(best)
    return picked


def cover_source(source: Image.Image, size: tuple[int, int], box: tuple[int, int, int, int]) -> Image.Image:
    """Cover the slot bounding box with source pixels, preserving aspect ratio."""
    x0, y0, x1, y1 = box
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    src = source.convert("RGBA")
    scale = max(w / src.width, h / src.height)
    resized = src.resize((max(w, round(src.width * scale)), max(h, round(src.height * scale))), Image.Resampling.LANCZOS)
    left = max(0, (resized.width - w) // 2)
    top = max(0, (resized.height - h) // 2)
    tile = resized.crop((left, top, left + w, top + h))
    canvas = Image.new("RGBA", size)
    canvas.paste(tile, (x0, y0))
    return canvas


def connected_components(points: list[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    """Return 8-connected regions in a keyed mask."""
    remaining = set(points)
    components: list[list[tuple[int, int]]] = []
    while remaining:
        start = remaining.pop()
        component = [start]
        stack = [start]
        while stack:
            x, y = stack.pop()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if not dx and not dy:
                        continue
                    neighbour = (x + dx, y + dy)
                    if neighbour in remaining:
                        remaining.remove(neighbour)
                        component.append(neighbour)
                        stack.append(neighbour)
        components.append(component)
    return components


def colour_summary(pixels: list[tuple[int, int, int]]) -> dict[str, Any]:
    if not pixels:
        return {"dominant_rgb": None, "mean_rgb": None}
    # Quantisation makes the dominant colour useful for anti-aliased Image 2
    # output (e.g. magenta around 252,2,237 instead of exact #FF00FF).
    quantized = [tuple(round(v / 8) * 8 for v in rgb) for rgb in pixels]
    dominant = Counter(quantized).most_common(1)[0][0]
    mean = [round(sum(rgb[i] for rgb in pixels) / len(pixels), 2) for i in range(3)]
    return {"dominant_rgb": list(dominant), "mean_rgb": mean}


def hue_distance(a: float, b: float) -> float:
    delta = abs(a - b)
    return min(delta, 1.0 - delta)


def compose(spec: dict[str, Any], output: Path) -> dict[str, Any]:
    overlay_path = Path(spec["overlay"])
    overlay = Image.open(overlay_path).convert("RGBA")
    px = overlay.load()
    tolerance = float(spec.get("tolerance", 40))
    min_mask_area_ratio = float(spec.get("min_mask_area_ratio", 0.01))
    min_extra_component_ratio = float(spec.get("min_extra_component_ratio", 0.0005))
    edge_cleanup_radius = int(spec.get("edge_cleanup_radius", 2))
    edge_cleanup_tolerance = float(spec.get("edge_cleanup_tolerance", tolerance * 1.75))
    edge_cleanup_hue_degrees = float(spec.get("edge_cleanup_hue_degrees", 20))
    edge_cleanup_min_saturation = float(spec.get("edge_cleanup_min_saturation", 0.45))
    slots = spec["slots"]
    keys = [tuple(s["key_rgb"]) for s in slots]
    output_img = overlay.copy()
    outpx = output_img.load()
    evidence: dict[str, Any] = {
        "overlay": str(overlay_path), "overlay_sha256": sha256(overlay_path),
        "size": {"width": overlay.width, "height": overlay.height},
        "tolerance": tolerance, "min_mask_area_ratio": min_mask_area_ratio,
        "min_extra_component_ratio": min_extra_component_ratio,
        "edge_cleanup": {"radius": edge_cleanup_radius, "tolerance": edge_cleanup_tolerance,
                          "hue_degrees": edge_cleanup_hue_degrees,
                          "min_saturation": edge_cleanup_min_saturation},
        "slot_count": len(slots), "slots": [],
    }
    masks: list[list[tuple[int, int]]] = [[] for _ in slots]
    collisions: list[tuple[int, int]] = []
    remaining_before = 0
    for y in range(overlay.height):
        for x in range(overlay.width):
            rgb = px[x, y][:3]
            distances = [math.sqrt(sum((a - b) ** 2 for a, b in zip(rgb, key))) for key in keys]
            matches = [i for i, dist in enumerate(distances) if dist <= tolerance]
            if matches:
                if len(matches) > 1:
                    collisions.append((x, y))
                chosen = min(matches, key=lambda i: distances[i])
                masks[chosen].append((x, y))
            if any(dist <= tolerance for dist in distances):
                remaining_before += 1
    slot_passes: list[bool] = []
    selected_masks: list[list[tuple[int, int]]] = []
    selected_sets: list[set[tuple[int, int]]] = []
    all_matched = {p for mask in masks for p in mask}
    for i, (slot, mask) in enumerate(zip(slots, masks)):
        source_path = Path(slot["source"])
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        if not mask:
            raise ValueError(f"Slot {i + 1} key colour was not found")
        components = sorted(connected_components(mask), key=len, reverse=True)
        selected = components[0]
        selected_set = set(selected)
        extra_components = components[1:]
        extra_pixels = sum(len(component) for component in extra_components)
        meaningful_extras = [component for component in extra_components if len(component) >= max(16, round(overlay.width * overlay.height * min_extra_component_ratio))]
        area_ratio = len(selected) / (overlay.width * overlay.height)
        matched_colours = [px[x, y][:3] for x, y in mask]
        selected_colours = [px[x, y][:3] for x, y in selected]
        slot_ok = area_ratio >= min_mask_area_ratio and not meaningful_extras
        slot_passes.append(slot_ok)
        selected_masks.append(selected)
        selected_sets.append(selected_set)
        xs, ys = zip(*selected)
        box = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
        source = Image.open(source_path)
        tile = cover_source(source, output_img.size, box)
        for x, y in selected:
            outpx[x, y] = tile.getpixel((x, y))
        evidence["slots"].append({
            "index": i + 1, "name": slot.get("name", f"slot-{i + 1}"),
            "key_rgb": list(keys[i]), "source": str(source_path),
            "source_sha256": sha256(source_path), "mask_pixels": len(mask),
            "selected_component_pixels": len(selected),
            "component_count": len(components),
            "extra_component_count": len(extra_components),
            "extra_component_pixels": extra_pixels,
            "meaningful_extra_component_count": len(meaningful_extras),
            "mask_area_ratio": round(area_ratio, 6),
            "matched_colour": colour_summary(matched_colours),
            "selected_colour": colour_summary(selected_colours),
            "mask_bbox": list(box), "source_size": [source.width, source.height],
            "pass": slot_ok,
        })
    # Recover a narrow anti-aliased key halo without touching unrelated
    # artwork: only pixels immediately adjacent to the selected component,
    # outside every keyed mask, and close to that slot's key are expanded.
    cleanup_added: list[list[tuple[int, int]]] = [[] for _ in slots]
    for i, selected_set in enumerate(selected_sets):
        for x, y in selected_set:
            for dy in range(-edge_cleanup_radius, edge_cleanup_radius + 1):
                for dx in range(-edge_cleanup_radius, edge_cleanup_radius + 1):
                    if not dx and not dy:
                        continue
                    if dx * dx + dy * dy > edge_cleanup_radius * edge_cleanup_radius:
                        continue
                    p = (x + dx, y + dy)
                    if not (0 <= p[0] < overlay.width and 0 <= p[1] < overlay.height):
                        continue
                    if p in all_matched or p in selected_set or p in cleanup_added[i]:
                        continue
                    rgb = px[p[0], p[1]][:3]
                    distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(rgb, keys[i])))
                    r, g, b = [channel / 255 for channel in rgb]
                    pixel_hue, pixel_sat, _ = colorsys.rgb_to_hsv(r, g, b)
                    kr, kg, kb = [channel / 255 for channel in keys[i]]
                    key_hue, _, _ = colorsys.rgb_to_hsv(kr, kg, kb)
                    hue_match = (hue_distance(pixel_hue, key_hue) <= edge_cleanup_hue_degrees / 360
                                 and pixel_sat >= edge_cleanup_min_saturation)
                    if distance <= edge_cleanup_tolerance or hue_match:
                        cleanup_added[i].append(p)
        selected_masks[i].extend(cleanup_added[i])
        selected_sets[i].update(cleanup_added[i])
        evidence["slots"][i]["edge_cleanup_pixels"] = len(cleanup_added[i])
        evidence["slots"][i]["composite_mask_pixels"] = len(selected_masks[i])
    # Re-composite using the expanded masks so cleanup pixels receive the same
    # source crop as their neighbouring placeholder pixels.
    for slot, expanded in zip(slots, selected_masks):
        xs, ys = zip(*expanded)
        box = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
        source_path = Path(slot["source"])
        tile = cover_source(Image.open(source_path), output_img.size, box)
        for x, y in expanded:
            outpx[x, y] = tile.getpixel((x, y))
    # A key-colour residual is measured outside the intended masks; key-like
    # pixels inside source photos are legitimate image content, not failures.
    intended = {p for mask in selected_masks for p in mask}
    residual = 0
    hue_residual = 0
    for y in range(output_img.height):
        for x in range(output_img.width):
            if (x, y) in intended:
                continue
            rgb = outpx[x, y][:3]
            if any(math.sqrt(sum((a - b) ** 2 for a, b in zip(rgb, key))) <= tolerance for key in keys):
                residual += 1
            rr, gg, bb = [channel / 255 for channel in rgb]
            ph, ps, _ = colorsys.rgb_to_hsv(rr, gg, bb)
            if any(hue_distance(ph, colorsys.rgb_to_hsv(*(channel / 255 for channel in key))[0]) <= edge_cleanup_hue_degrees / 360
                   and ps >= edge_cleanup_min_saturation for key in keys):
                hue_residual += 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output_img.save(output, "PNG")
    evidence.update({
        "mask_overlap_pixels": len(collisions),
        "mask_overlap_examples": [list(p) for p in collisions[:10]],
        "key_pixels_before": remaining_before,
        "remaining_key_pixels_outside_masks": residual,
        "remaining_key_hue_pixels_outside_masks": hue_residual,
        "output": str(output), "output_sha256": sha256(output),
        "edge_cleanup_pixels": sum(len(p) for p in cleanup_added),
        "slot_passes": slot_passes,
        "pass": not collisions and residual == 0 and all(slot_passes),
    })
    return evidence


def make_demo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    W, H = 1000, 700
    colours = choose_key_colors(4, [(15, 25, 35), (220, 80, 20), (240, 240, 240)])
    # Synthetic source photos make this harness reproducible without external assets.
    sources: list[Path] = []
    for i, colour in enumerate([(55, 95, 140), (175, 80, 55), (55, 145, 95), (130, 75, 165)]):
        im = Image.new("RGB", (520 + i * 40, 380 + i * 20), colour)
        draw = ImageDraw.Draw(im)
        for j in range(8):
            draw.ellipse((30 + j * 55, 40 + j * 25, 180 + j * 55, 190 + j * 25), fill=tuple(min(255, v + 35 + j * 4) for v in colour))
        p = root / f"source-{i + 1}.png"; im.save(p); sources.append(p)

    def fixture(name: str, rectangles: list[tuple[int, int, int, int]]) -> tuple[Path, list[dict[str, Any]]]:
        ov = Image.new("RGB", (W, H), (17, 25, 38)); d = ImageDraw.Draw(ov)
        slots = []
        for i, box in enumerate(rectangles):
            d.rectangle(box, fill=colours[i])
            slots.append({"name": f"slot-{i + 1}", "key_rgb": list(colours[i]), "source": str(sources[i])})
        # simulated Image 2 text/decorations are outside the replaceable areas
        d.text((35, 25), name.upper(), fill=(255, 255, 255))
        p = root / f"overlay-{name}.png"; ov.save(p); return p, slots

    cases = {
        "before-after": [(60, 150, 475, 620), (525, 150, 940, 620)],
        "services-2": [(60, 150, 475, 620), (525, 150, 940, 620)],
        "collage-4": [(40, 130, 470, 400), (530, 130, 960, 400), (40, 430, 470, 670), (530, 430, 960, 670)],
    }
    all_evidence = {}
    for name, boxes in cases.items():
        ov, slots = fixture(name, boxes)
        spec = {"overlay": str(ov), "slots": slots}
        all_evidence[name] = compose(spec, root / f"composite-{name}.png")
    (root / "evidence.json").write_text(json.dumps({"key_colors": [list(c) for c in colours], "cases": all_evidence}, indent=2), encoding="utf-8")


def key_color_self_test(output: Path) -> dict[str, Any]:
    """Exercise green-brand exclusion for 2, 4, and 6 requested slots."""
    brand = (20, 180, 40)
    cases: dict[str, Any] = {}
    for count in (2, 4, 6):
        keys = choose_key_colors(count, [brand])
        hues = [colorsys.rgb_to_hsv(*(v / 255 for v in key))[0] for key in keys]
        brand_hue = colorsys.rgb_to_hsv(*(v / 255 for v in brand))[0]
        brand_distances = [round(hue_distance(h, brand_hue) * 360, 2) for h in hues]
        pair_distances = [round(hue_distance(hues[i], hues[j]) * 360, 2)
                          for i in range(len(hues)) for j in range(i + 1, len(hues))]
        passed = min(brand_distances) >= 59 and (not pair_distances or min(pair_distances) >= 24)
        cases[str(count)] = {
            "keys": [list(key) for key in keys],
            "key_hues_degrees": [round(h * 360, 2) for h in hues],
            "min_brand_hue_distance_degrees": min(brand_distances),
            "min_pair_hue_distance_degrees": min(pair_distances) if pair_distances else None,
            "pass": passed,
        }
        if not passed:
            raise AssertionError(f"key colour self-test failed for {count} slots: {cases[str(count)]}")
    evidence = {"brand_palette": [list(brand)], "cases": cases, "pass": True}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", type=Path, help="JSON spec with overlay and slots")
    ap.add_argument("--output", type=Path)
    ap.add_argument("--demo", type=Path, help="Generate and run reproducible 2-slot/4-slot cases")
    ap.add_argument("--self-test", action="store_true", help="Run deterministic key-colour selection checks")
    ap.add_argument("--self-test-output", type=Path,
                    default=Path("output/prototypes/multislot-chroma-20260827/key-color-self-test.json"))
    args = ap.parse_args()
    if args.self_test:
        print(json.dumps(key_color_self_test(args.self_test_output), indent=2)); return
    if args.demo:
        make_demo(args.demo); print(args.demo / "evidence.json"); return
    if not args.spec or not args.output:
        ap.error("provide --spec and --output, or --demo")
    print(json.dumps(compose(json.loads(args.spec.read_text(encoding="utf-8")), args.output), indent=2))


if __name__ == "__main__":
    main()
