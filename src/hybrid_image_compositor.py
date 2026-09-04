"""Deterministic compositor for Image 2 hybrid creatives.

Image 2 creates the visual direction and coloured media windows; this module
only builds that request and replaces the windows with the user's real media.
It deliberately has no provider, network, Hermes, or model dependencies.
"""
from __future__ import annotations

import colorsys
import hashlib
import json
import math
from collections import deque
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image, ImageEnhance

RGB = tuple[int, int, int]
Box = tuple[int, int, int, int]


class HybridMaskMissingError(ValueError):
    """Raised when a required keyed slot has no recoverable mask."""

    code = "composition_mask_missing"

    def __init__(self, slot_id: Any):
        self.slot_id = slot_id
        super().__init__(f"{self.code}: missing mask for slot {slot_id}")


_KEY_CANDIDATES: tuple[RGB, ...] = (
    (255, 0, 255), (0, 255, 255), (255, 255, 0), (0, 0, 255),
    (255, 96, 0), (128, 0, 255), (255, 0, 128), (0, 255, 160),
    (30, 255, 255), (255, 160, 0), (64, 0, 255), (255, 0, 64),
    (0, 160, 255), (192, 0, 255), (255, 32, 160), (0, 255, 80),
)


def _hue(rgb: RGB) -> tuple[float, float, float]:
    return colorsys.rgb_to_hsv(*(max(0, min(255, c)) / 255 for c in rgb))


def hue_distance(a: float, b: float) -> float:
    d = abs(a - b)
    return min(d, 1.0 - d)


def choose_key_colors(
    count: int,
    brand_palette: Sequence[RGB] | None = None,
    *,
    min_brand_hue_degrees: float = 58,
    min_key_hue_degrees: float = 24,
) -> list[RGB]:
    """Return saturated, distinct key colours outside the brand hue families.

    Brand colours with low saturation (white, black, grey) do not reserve a
    hue. The extra fallback candidates make six-slot collages practical while
    retaining a strict hue separation guarantee.
    """
    if not 1 <= count <= 6:
        raise ValueError("count must be between 1 and 6")
    brand = list(brand_palette or [])
    reserved = [_hue(c)[0] for c in brand if _hue(c)[1] >= 0.45]
    selected: list[RGB] = []
    for candidate in _KEY_CANDIDATES:
        ch, cs, _ = _hue(candidate)
        if any(hue_distance(ch, h) * 360 < min_brand_hue_degrees for h in reserved):
            continue
        if any(hue_distance(ch, _hue(other)[0]) * 360 < min_key_hue_degrees for other in selected):
            continue
        selected.append(candidate)
        if len(selected) == count:
            return selected
    raise ValueError("not enough hue-separated key colours for this brand palette")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _distance(a: RGB, b: RGB) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _safe_key_drift(rgb: RGB, key: RGB, *, max_hue_degrees: float = 16.0) -> bool:
    """Accept Image 2's small chroma drift without accepting nearby artwork.

    Image 2 sometimes turns an exact key such as magenta into a nearby,
    anti-aliased chromatic value.  Hue, saturation, and value are a safer
    signal for that case than increasing the RGB radius (which can absorb
    text, shadows, or brand colours).  The caller still resolves competing
    keys by nearest hue and keeps overlap evidence.
    """
    h, saturation, value = _hue(rgb)
    key_h, key_saturation, key_value = _hue(key)
    return (
        key_saturation >= 0.70 and saturation >= 0.70 and value >= 0.60
        and hue_distance(h, key_h) * 360 <= max_hue_degrees
        and abs(saturation - key_saturation) <= 0.35
        and abs(value - key_value) <= 0.35
    )


def _safe_key_fringe(rgb: RGB, key: RGB, *, max_hue_degrees: float = 18.0) -> bool:
    """Recognise a dark chroma-key fringe produced by antialiasing.

    A generated overlay can alpha-blend a saturated key edge with a dark
    background.  The resulting pixel keeps the key hue/saturation but has a
    much lower value (for example magenta ``#6F0978``), so
    :func:`_safe_key_drift` intentionally rejects it.  This predicate is only
    used while expanding pixels immediately adjacent to an already validated
    slot, never for discovering a mask or validating arbitrary artwork.
    """
    h, saturation, value = _hue(rgb)
    key_h, key_saturation, _ = _hue(key)
    return (
        key_saturation >= 0.70 and saturation >= 0.55 and value >= 0.08
        and hue_distance(h, key_h) * 360 <= max_hue_degrees
        and saturation >= key_saturation * 0.45
    )


def _key_matches(rgb: RGB, keys: Sequence[RGB], tolerance: float) -> list[int]:
    """Return exact matches, or one unambiguous chromatic-drift match."""
    exact = [index for index, key in enumerate(keys) if _distance(rgb, key) <= tolerance]
    if exact:
        return exact
    candidates = [
        (hue_distance(_hue(rgb)[0], _hue(key)[0]), index)
        for index, key in enumerate(keys) if _safe_key_drift(rgb, key)
    ]
    if not candidates:
        return []
    candidates.sort()
    # Do not classify a hue midpoint as two slots.  A four-degree margin also
    # keeps two deliberately close key families from swallowing each other.
    if len(candidates) > 1 and (candidates[1][0] - candidates[0][0]) * 360 < 4:
        return []
    return [candidates[0][1]]


def _components(points: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
    result: list[set[tuple[int, int]]] = []
    while points:
        root = points.pop()
        component = {root}
        queue = deque([root])
        while queue:
            x, y = queue.popleft()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    point = (x + dx, y + dy)
                    if point in points:
                        points.remove(point)
                        component.add(point)
                        queue.append(point)
        result.append(component)
    return result


def _cover(source: Image.Image, size: tuple[int, int], box: Box) -> Image.Image:
    x0, y0, x1, y1 = box
    width, height = max(1, x1 - x0), max(1, y1 - y0)
    image = source.convert("RGBA")
    scale = max(width / image.width, height / image.height)
    resized = image.resize((max(width, round(image.width * scale)), max(height, round(image.height * scale))), Image.Resampling.LANCZOS)
    left, top = max(0, (resized.width - width) // 2), max(0, (resized.height - height) // 2)
    tile = resized.crop((left, top, left + width, top + height))
    canvas = Image.new("RGBA", size)
    canvas.paste(tile, (x0, y0))
    return canvas


def compose_overlay(
    overlay: str | Path | Image.Image,
    slots: Sequence[Mapping[str, Any]],
    output: str | Path,
    *,
    tolerance: float = 40,
    min_area_ratio: float = 0.01,
    edge_radius: int = 2,
    edge_tolerance: float | None = None,
    min_extra_component_ratio: float = 0.0005,
) -> dict[str, Any]:
    """Replace each keyed window with its source and emit auditable evidence.

    ``slots`` are ordered and require ``source`` plus ``key_rgb``. Their
    optional ``slot_id``/``label`` values are retained in evidence. The input
    overlay and source files are opened read-only and never modified.
    """
    overlay_path = Path(overlay) if not isinstance(overlay, Image.Image) else None
    base = (Image.open(overlay_path) if overlay_path else overlay).convert("RGBA")
    pixels = base.load()
    keys = [tuple(s["key_rgb"]) for s in slots]
    if not 1 <= len(slots) <= 6:
        raise ValueError("slots must contain between 1 and 6 items")
    masks: list[set[tuple[int, int]]] = [set() for _ in slots]
    overlap = 0
    for y in range(base.height):
        for x in range(base.width):
            rgb = pixels[x, y][:3]
            distances = [_distance(rgb, key) for key in keys]
            matches = _key_matches(rgb, keys, tolerance)
            if len(matches) > 1:
                overlap += 1
            if matches:
                masks[min(matches, key=lambda i: distances[i])].add((x, y))
    all_keyed = set().union(*masks)
    output_image = base.copy()
    evidence: dict[str, Any] = {
        "size": [base.width, base.height], "tolerance": tolerance,
        "overlay_sha256": _sha256(overlay_path) if overlay_path else None,
        "slot_count": len(slots), "mask_overlap_pixels": overlap, "slots": [],
    }
    expanded_masks: list[set[tuple[int, int]]] = []
    ignored_tiny_components: set[tuple[int, int]] = set()
    cleanup_limit = edge_tolerance if edge_tolerance is not None else tolerance * 1.75
    for index, (slot, mask) in enumerate(zip(slots, masks)):
        source_path = Path(slot["source"])
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        if not mask:
            raise HybridMaskMissingError(slot.get("slot_id", index + 1))
        components = sorted(_components(set(mask)), key=len, reverse=True)
        chosen = components[0]
        area_ratio = len(chosen) / (base.width * base.height)
        extra = sum(len(c) for c in components[1:])
        # Tiny isolated anti-alias speckles are expected from Image 2 and are
        # not evidence that another media window exists. Only components that
        # exceed both a pixel floor and the configured image-area ratio fail.
        meaningful_extras = [c for c in components[1:]
                             if len(c) >= max(16, round(base.width * base.height * min_extra_component_ratio))]
        ignored_tiny_components.update(set().union(*(set(c) for c in components[1:] if c not in meaningful_extras)))
        # Expand only chromatic pixels immediately beside the selected region;
        # this removes Image 2's anti-aliased one-pixel key fringe safely.
        expanded = set(chosen)
        for x, y in chosen:
            for dy in range(-edge_radius, edge_radius + 1):
                for dx in range(-edge_radius, edge_radius + 1):
                    if not dx and not dy or dx * dx + dy * dy > edge_radius * edge_radius:
                        continue
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < base.width and 0 <= ny < base.height) or (nx, ny) in all_keyed:
                        continue
                    rgb = pixels[nx, ny][:3]
                    if (_distance(rgb, keys[index]) <= cleanup_limit
                            or _safe_key_drift(rgb, keys[index], max_hue_degrees=20)
                            or _safe_key_fringe(rgb, keys[index])):
                        expanded.add((nx, ny))
        # A dark letter or a small decorative mark can punch a hole through a
        # otherwise valid window.  Fill only regions enclosed by the selected
        # component's bounding box; anything connected to the box boundary is
        # left alone and therefore remains visible to residual validation.
        xs0, ys0 = zip(*chosen)
        hole_box = (min(xs0), min(ys0), max(xs0) + 1, max(ys0) + 1)
        hx0, hy0, hx1, hy1 = hole_box
        outside: set[tuple[int, int]] = set()
        queue: deque[tuple[int, int]] = deque()
        for hx in range(hx0, hx1):
            for hy in (hy0, hy1 - 1):
                if (hx, hy) not in chosen and (hx, hy) not in outside:
                    outside.add((hx, hy)); queue.append((hx, hy))
        for hy in range(hy0, hy1):
            for hx in (hx0, hx1 - 1):
                if (hx, hy) not in chosen and (hx, hy) not in outside:
                    outside.add((hx, hy)); queue.append((hx, hy))
        while queue:
            hx, hy = queue.popleft()
            for nx, ny in ((hx - 1, hy), (hx + 1, hy), (hx, hy - 1), (hx, hy + 1)):
                if not (hx0 <= nx < hx1 and hy0 <= ny < hy1):
                    continue
                if (nx, ny) in chosen or (nx, ny) in outside:
                    continue
                outside.add((nx, ny)); queue.append((nx, ny))
        enclosed_holes = {
            (hx, hy) for hx in range(hx0, hx1) for hy in range(hy0, hy1)
            if (hx, hy) not in chosen and (hx, hy) not in outside
        }
        expanded.update(enclosed_holes)
        expanded_masks.append(expanded)
        xs, ys = zip(*expanded)
        box = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
        tile = _cover(Image.open(source_path), output_image.size, box)
        out = output_image.load()
        for x, y in expanded:
            out[x, y] = tile.getpixel((x, y))
        evidence["slots"].append({
            "slot_id": slot.get("slot_id", f"slot-{index + 1}"), "label": slot.get("label"),
            "key_rgb": list(keys[index]), "source": str(source_path),
            "source_sha256": _sha256(source_path), "component_count": len(components),
            "selected_pixels": len(chosen), "composite_pixels": len(expanded),
            "extra_component_pixels": extra, "ignored_tiny_component_pixels": sum(len(c) for c in components[1:] if c not in meaningful_extras),
            "meaningful_extra_component_count": len(meaningful_extras),
            "mask_bbox": list(box), "area_ratio": round(area_ratio, 6),
            "pass": area_ratio >= min_area_ratio and not meaningful_extras,
        })
    intended = set().union(*expanded_masks)
    residual = 0
    for y in range(output_image.height):
        for x in range(output_image.width):
            if (x, y) in intended or (x, y) in ignored_tiny_components:
                continue
            if _key_matches(output_image.getpixel((x, y))[:3], keys, tolerance):
                residual += 1
    passed = overlap == 0 and residual == 0 and all(s["pass"] for s in evidence["slots"])
    destination = Path(output)
    if passed:
        destination.parent.mkdir(parents=True, exist_ok=True)
        output_image.save(destination, "PNG")
    evidence.update({"output": str(destination), "output_sha256": _sha256(destination) if passed else None,
                     "remaining_key_pixels_outside_masks": residual,
                     "min_extra_component_ratio": min_extra_component_ratio,
                     "pass": passed})
    if not passed:
        evidence["output_sha256"] = None
    return evidence


def build_overlay_prompt(
    *,
    layout: str,
    slots: Sequence[Mapping[str, Any]],
    visual_direction: str = "",
    text_content: Mapping[str, Any] | None = None,
    brand_palette: Sequence[str] | None = None,
    brand_context: Mapping[str, Any] | None = None,
    active_offer: str = "",
    objective: str = "",
    audience: str = "",
    format_hint: str = "",
    logo_safe_zone: str = "",
    style_reference_mode: str = "none",
    use_style_reference_pool: bool | None = None,
) -> str:
    """Build a natural-language Image 2 request without imposing a fixed design.

    ``layout`` accepts hero, before_after, services, collage, or freeform.
    ``none`` uses no reference, ``brand``/``pool`` describe the complete
    persistent brand-reference set, and ``explicit`` adds the one-task design
    reference selected by the user. Slot colours and labels are exact so the
    compositor can recover each asset deterministically after generation.
    """
    if layout not in {"hero", "before_after", "services", "collage", "freeform"}:
        raise ValueError("unsupported layout")
    # Preserve compatibility with early prototype callers while making the
    # three-state contract the canonical API used by the dashboard.
    if use_style_reference_pool is not None:
        style_reference_mode = "pool" if use_style_reference_pool else "none"
    if style_reference_mode not in {"none", "brand", "pool", "explicit"}:
        raise ValueError("style_reference_mode must be none, brand, pool, or explicit")
    if not 1 <= len(slots) <= 6:
        raise ValueError("slots must contain between 1 and 6 items")
    lines = [
        "Create one polished advertising graphic from the semantic creative brief below.",
        "Treat a short buyer request as intent to refine, not as the complete art-direction prompt. Preserve every explicit buyer instruction, then complete the hierarchy and composition from confirmed brand, offer, audience, objective, format, text, and media-slot context.",
        "Keep the composition dynamic and editorial; do not use a fixed template or add a logo.",
        "Choose a fresh visual solution for this generation. You may vary composition, hierarchy, framing, card geometry, negative space, typography arrangement, accents, and CTA treatment while preserving confirmed facts and the ordered media slots.",
        f"Layout family: {layout}.",
    ]
    if format_hint:
        lines.append(f"Output format/aspect ratio: {format_hint}.")
    if active_offer:
        lines.append(f"Active offer/topic: {active_offer}")
    if objective:
        lines.append(f"Communication objective: {objective}")
    if audience:
        lines.append(f"Audience: {audience}")
    if visual_direction:
        lines.append(f"Buyer and manager visual direction: {visual_direction}")
    if brand_context:
        confirmed_brand = {
            str(key): value
            for key, value in brand_context.items()
            if str(value or "").strip()
        }
        if confirmed_brand:
            lines.append("Confirmed brand context; replace generic styling with these values: " + json.dumps(confirmed_brand, ensure_ascii=False))
    if brand_palette:
        lines.append("Brand palette to respect: " + ", ".join(brand_palette) + ".")
    if text_content:
        lines.append("Render this supplied text clearly and legibly; preserve its facts and wording: " + json.dumps(dict(text_content), ensure_ascii=False))
    else:
        lines.append(
            "No structured on-image text was supplied. Derive only a concise, commercially useful title, up to three short benefit/feature lines, and a fitting CTA from the confirmed buyer request and active-offer context. Omit any element that lacks support. Never invent a price, discount, guarantee, testimonial, credential, measurable result, promotion, or business fact, and never describe generated wording as buyer-approved."
        )
    if logo_safe_zone:
        normalized_logo_zone = str(logo_safe_zone).strip().lower().replace("-", "_")
        if normalized_logo_zone not in {"top_left", "top_right", "bottom_left", "bottom_right"}:
            raise ValueError("logo_safe_zone must be a named corner")
        readable_zone = normalized_logo_zone.replace("_", "-")
        lines.append(
            f"Reserve a clean official-logo safe zone in the {readable_zone} corner, sized for a logo up to roughly 22% of canvas width with proportional height. "
            "Keep all text, CTA elements, media slots, faces, products, and critical artwork outside that zone. Continue the surrounding background naturally through it, but keep it visually calm and high-contrast. Do not draw a logo, logo-like symbol, placeholder, box, label, or watermark there; the application will place the exact official transparent logo programmatically after generation."
        )
    lines.append("CRITICAL HYBRID COMPOSITING CONTRACT: Never draw, recreate, infer, stylize, retouch, or reconstruct the real subject, product, person, scene, or photograph. The real media is supplied separately and is pixel-locked; your only job is to leave an exact empty chroma slot for the application to insert it later.")
    lines.append("Replaceable media windows are EMPTY RESERVED SLOTS. Do not place any text, letters, numbers, labels, icons, logos, borders, patterns, gradients, textures, shadows, glow, or artwork inside a slot. Put every label (including ANTES/DESPUÉS and service names) fully outside the slot, in the surrounding composition, with visible separation. Do not depict even a placeholder version of the real subject inside or over a slot.")
    lines.append("Use each key colour exactly once, as one uninterrupted contiguous flat solid fill per slot, and nowhere else in the artwork. Keep every other graphic and every character visibly distinct from every key colour; do not punch holes or add marks inside a slot. The key-colour region must remain a clean, solid, uninterrupted fill from edge to edge of each reserved slot.")
    for slot in slots:
        colour = tuple(slot["key_rgb"])
        hex_colour = "#%02X%02X%02X" % colour
        lines.append(f"- slot_id={slot.get('slot_id', 'slot')}; label={slot.get('label', '')}; key={hex_colour}; shape and placement may be creative.")
    if layout == "before_after":
        lines.append("Use clearly distinct windows labelled ANTES and DESPUÉS. The treatment may be an equal split, diagonal comparison, reveal, overlapping cards, or a result-dominant layout; keep both slots unambiguous and all labels outside them.")
    elif layout == "services":
        lines.append("Give each service its own distinct window and preserve the supplied service labels. Choose a dynamic card system, editorial split, staggered band, or asymmetric service showcase; never imply before/after unless the brief says so.")
    elif layout == "collage":
        lines.append("Arrange the windows as a coherent collage or mosaic. Choose either one visual anchor with supporting images or a balanced editorial grid, and vary scale, crop windows, rhythm, and composition naturally.")
    elif layout == "hero":
        lines.append("Use the single media window as the visual hero. It may be full-bleed, offset, framed, arched, or integrated into an asymmetric editorial composition, while leaving clear hierarchy for the title, supporting message, and CTA.")
    else:
        lines.append("Resolve the freeform layout from the buyer's visual direction while keeping every media slot distinct, legible, and compositionally intentional.")
    if style_reference_mode in {"brand", "pool"}:
        lines.append("Use all attached persistent brand design references as stylistic guidance. They may guide composition, typography energy, palette, rhythm, and graphic treatment, but confirmed brand rules and exact current-offer facts have priority. Never copy reference logos, photography, names, phone numbers, prices, promotions, or text.")
    elif style_reference_mode == "explicit":
        lines.append("The first attached design reference is explicit inspiration for this task only; any remaining style references are persistent brand guidance. Merge their visual cues intelligently, but confirmed brand rules and exact current-offer facts always have priority. Never copy reference logos, photography, names, phone numbers, prices, promotions, or text.")
    else:
        lines.append("Do not use any saved style reference; develop the visual direction freely.")
    lines.append("FINAL OUTPUT CHECK: every listed slot must be visibly present as its exact flat key colour. If the creative brief names or describes the protected real subject, represent its intended location only with that keyed slot; never render a substitute subject or a finished photograph there.")
    return "\n".join(lines)


def prepare_logo(image: str | Path | Image.Image, mode: str = "original", *, brand_primary: RGB = (255, 128, 0), brand_secondary: RGB = (0, 128, 255)) -> Image.Image:
    """Prepare an official logo with alpha-preserving colour variants."""
    if mode not in {"original", "white", "black", "brand_primary", "brand_secondary", "auto_contrast"}:
        raise ValueError("unsupported logo mode")
    source = Image.open(image) if not isinstance(image, Image.Image) else image
    rgba = source.convert("RGBA")
    if mode == "original":
        return rgba.copy()
    alpha = rgba.getchannel("A")
    if alpha.getextrema() == (255, 255):
        raise ValueError("solid logo variants require an official transparent PNG; refusing to guess or remove a JPG background")
    if mode == "auto_contrast":
        return rgba.copy()
    colour = {"white": (255, 255, 255, 255), "black": (0, 0, 0, 255),
              "brand_primary": (*brand_primary, 255), "brand_secondary": (*brand_secondary, 255)}[mode]
    result = Image.new("RGBA", rgba.size, colour)
    result.putalpha(alpha)
    return result


def composite_logo(base: str | Path | Image.Image, logo: str | Path | Image.Image, *, mode: str = "original", position: str | tuple[int, int] = "auto", margin: int = 24, max_fraction: float = 0.22, brand_primary: RGB = (255, 128, 0), brand_secondary: RGB = (0, 128, 255)) -> Image.Image:
    """Place an official logo without a plate, preserving its transparent geometry."""
    canvas = Image.open(base).convert("RGBA") if not isinstance(base, Image.Image) else base.convert("RGBA").copy()
    prepared = prepare_logo(logo, "original" if mode == "auto_contrast" else mode,
                            brand_primary=brand_primary, brand_secondary=brand_secondary)
    max_w = max(1, round(canvas.width * max_fraction))
    if prepared.width > max_w:
        prepared = prepared.resize((max_w, max(1, round(prepared.height * max_w / prepared.width))), Image.Resampling.LANCZOS)
    positions = {"top_left": (margin, margin),
                 "top_right": (canvas.width - margin - prepared.width, margin),
                 "bottom_left": (margin, canvas.height - margin - prepared.height),
                 "bottom_right": (canvas.width - margin - prepared.width, canvas.height - margin - prepared.height)}
    positions = {name: (max(0, min(canvas.width - prepared.width, x)),
                        max(0, min(canvas.height - prepared.height, y)))
                 for name, (x, y) in positions.items()}
    def region_metrics(xy: tuple[int, int]) -> tuple[float, float, float]:
        x0, y0 = xy
        x1 = min(canvas.width, x0 + prepared.width)
        y1 = min(canvas.height, y0 + prepared.height)
        region = canvas.crop((x0, y0, max(x0 + 1, x1), max(y0 + 1, y1))).convert("L")
        # Downsample the actual logo rectangle so the score is inexpensive and
        # stable across output sizes. Contrast alone used to prefer text-heavy
        # corners; local edges and variance now penalize visually occupied
        # regions without needing OCR, another model, or a fixed layout rule.
        region.thumbnail((32, 32), Image.Resampling.BILINEAR)
        width, height = region.size
        values = [value / 255 for value in region.getdata()]
        mean = sum(values) / max(1, len(values))
        variance = math.sqrt(sum((value - mean) ** 2 for value in values) / max(1, len(values)))
        edge_total = 0.0
        edge_count = 0
        pixels = region.load()
        for y in range(height):
            for x in range(width):
                if x:
                    edge_total += abs(pixels[x, y] - pixels[x - 1, y]) / 255
                    edge_count += 1
                if y:
                    edge_total += abs(pixels[x, y] - pixels[x, y - 1]) / 255
                    edge_count += 1
        edge_density = edge_total / max(1, edge_count)
        return mean, edge_density, min(1.0, variance * 2)

    def region_luminance(xy: tuple[int, int]) -> float:
        return region_metrics(xy)[0]

    def placement_score(xy: tuple[int, int]) -> float:
        luminance, edge_density, variance = region_metrics(xy)
        best_solid_contrast = max(luminance, 1 - luminance)
        return best_solid_contrast - 0.35 * edge_density - 0.15 * variance
    if position == "auto":
        # Prefer a clean corner where either a white or black exact logo has
        # strong contrast. Existing text and texture reduce the score.
        xy = max(positions.values(), key=placement_score)
        position = xy
    if mode == "auto_contrast":
        local_luminance = region_luminance(tuple(position) if not isinstance(position, str) else positions[position])
        mode = "white" if local_luminance < 0.5 else "black"
        prepared = prepare_logo(logo, mode, brand_primary=brand_primary, brand_secondary=brand_secondary)
        if prepared.width > max_w:
            prepared = prepared.resize((max_w, max(1, round(prepared.height * max_w / prepared.width))), Image.Resampling.LANCZOS)
        # Recalculate named-position bounds after the mode conversion/resize.
        positions = {"top_left": (margin, margin), "top_right": (canvas.width - margin - prepared.width, margin),
                     "bottom_left": (margin, canvas.height - margin - prepared.height), "bottom_right": (canvas.width - margin - prepared.width, canvas.height - margin - prepared.height)}
        positions = {name: (max(0, min(canvas.width - prepared.width, x)), max(0, min(canvas.height - prepared.height, y))) for name, (x, y) in positions.items()}
        if isinstance(position, str):
            position = positions[position]
    if isinstance(position, str):
        if position not in positions:
            raise ValueError("position must be auto or a named corner")
        xy = positions[position]
    else:
        xy = (max(0, min(canvas.width - prepared.width, int(position[0]))),
              max(0, min(canvas.height - prepared.height, int(position[1]))))
    canvas.alpha_composite(prepared, xy)
    return canvas


# Friendly aliases for MCP adapters.
build_image2_overlay_prompt = build_overlay_prompt
compose_real_media = compose_overlay
