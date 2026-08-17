#!/usr/bin/env python3
"""Safe, brand-aware motion-graphics rendering for Admira IA.

The model supplies a bounded storyboard, never React or shell code.  This
module resolves the parent brand and active child offer, copies only approved
local media into an isolated render directory, and invokes the pinned Remotion
renderer with a normalized JSON contract.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from codex_brand_guides import (
    BRAND_ASSET_DIR,
    GENERAL_GUIDE,
    PRODUCT_DIR,
    creative_reference_allowed_roots,
    general_fields,
    official_brand_logo_path,
    product_fields,
    product_guide_paths,
    read_text,
    resolve_product_guide,
)
from local_store import now_iso, read_json, write_json
from motion_recipe_compiler import MotionRecipeCompileError, build_generated_entrypoint
from product_config import ROOT_DIR
from shotcraft_catalog import (
    ShotcraftCatalogError,
    resolve_shotcraft_recipe,
    shotcraft_catalog_summary,
)


OUTPUT_ROOT = ROOT_DIR / "output" / "motion-graphics"
RENDER_SCRIPT = ROOT_DIR / "scripts" / "render-motion-graphic.mjs"
CONTENT_ASSET_LIBRARY = ROOT_DIR / "dashboard" / "data" / "content_asset_library.json"

FORMAT_DIMENSIONS = {
    "9:16": (1080, 1920),
    "4:5": (1080, 1350),
    "1:1": (1080, 1080),
    "16:9": (1920, 1080),
}
FORMAT_ALIASES = {
    "vertical": "9:16",
    "story": "9:16",
    "stories": "9:16",
    "reel": "9:16",
    "reels": "9:16",
    "portrait": "4:5",
    "feed": "4:5",
    "square": "1:1",
    "cuadrado": "1:1",
    "landscape": "16:9",
    "horizontal": "16:9",
    "youtube": "16:9",
}
SCENE_TYPES = {
    "hook",
    "statement",
    "list",
    "steps",
    "stat",
    "comparison",
    "quote",
    "media",
    "cta",
}
LEGACY_MOTION_RECIPES = {
    "editorial-reveal",
    "card-cascade",
    "step-stack",
    "stat-focus",
    "split-compare",
    "quote-frame",
    "spotlight-media",
    "cta-lockup",
}

# The agent may combine up to four compatible recipe layers in one shot.
# These are parameterized implementations derived from the Apache-2.0
# video-shotcraft recipe library; they are data-driven, not arbitrary React.
SHOT_RECIPE_CATALOG = {
    # Primary/opening/layout recipes.
    "brand-ink-open": {"layer": "base", "requires_media": False},
    "paper-title-card": {"layer": "base", "requires_media": False},
    "product-card-progressive-assemble": {"layer": "base", "requires_media": False},
    "card-stack": {"layer": "base", "requires_media": False},
    "deck-deal-flyin": {"layer": "base", "requires_media": False},
    "row-embed": {"layer": "base", "requires_media": False},
    "list-stack-press": {"layer": "base", "requires_media": False},
    "odometer-digit-roll": {"layer": "base", "requires_media": False},
    "before-after-slider-scrub": {"layer": "base", "requires_media": False},
    "page-waterfall-wall": {"layer": "base", "requires_media": False},
    "radial-wave": {"layer": "base", "requires_media": False},
    # Camera recipes.
    "page-cam-2.5d": {"layer": "camera", "requires_media": True},
    "multiplane": {"layer": "camera", "requires_media": True},
    "crash-zoom-punch": {"layer": "camera", "requires_media": False},
    # Typography recipes.
    "gradient-word-sweep": {"layer": "typography", "requires_media": False},
    "marker-underline-title": {"layer": "accent", "requires_media": False},
    # Accent/effect recipes. They can sit above one base/camera recipe.
    "brand-frame-snap": {"layer": "accent", "requires_media": False},
    "scanline-annotate-focus": {"layer": "accent", "requires_media": False},
    "spotlight-sweep": {"layer": "accent", "requires_media": False},
    "halation-bloom": {"layer": "accent", "requires_media": False},
    # Outro.
    "cta-ink-lockup": {"layer": "base", "requires_media": False},
    # Transitions.
    "flash-cut": {"layer": "transition", "requires_media": False},
    "whip-pan": {"layer": "transition", "requires_media": False},
    "ink-bleed-reveal": {"layer": "transition", "requires_media": False},
}
MOTION_RECIPES = LEGACY_MOTION_RECIPES | set(SHOT_RECIPE_CATALOG)
MOTION_TEMPLATES = {
    "adaptive",
    "ink-press",
    "cinematic-product",
    "educational-cards",
    "data-story",
    "social-vertical",
}
DEFAULT_MOTION_BY_SCENE = {
    "hook": "editorial-reveal",
    "statement": "editorial-reveal",
    "list": "card-cascade",
    "steps": "step-stack",
    "stat": "stat-focus",
    "comparison": "split-compare",
    "quote": "quote-frame",
    "media": "spotlight-media",
    "cta": "cta-lockup",
}
DEFAULT_SHOT_RECIPES_BY_SCENE = {
    "hook": ["brand-ink-open", "brand-frame-snap"],
    "statement": ["paper-title-card"],
    "list": ["card-stack"],
    "steps": ["list-stack-press"],
    "stat": ["odometer-digit-roll", "halation-bloom"],
    "comparison": ["before-after-slider-scrub"],
    "quote": ["paper-title-card"],
    "media": ["page-cam-2.5d", "spotlight-sweep"],
    "cta": ["cta-ink-lockup"],
}
TEMPLATE_RECIPE_SEQUENCE = {
    "ink-press": [
        ["brand-ink-open", "flash-cut"],
        ["paper-title-card", "marker-underline-title"],
        ["page-cam-2.5d", "scanline-annotate-focus"],
        ["row-embed", "ink-bleed-reveal"],
        ["odometer-digit-roll", "halation-bloom"],
        ["cta-ink-lockup"],
    ],
    "cinematic-product": [
        ["crash-zoom-punch", "brand-frame-snap"],
        ["product-card-progressive-assemble", "spotlight-sweep"],
        ["page-cam-2.5d", "halation-bloom"],
        ["before-after-slider-scrub", "whip-pan"],
        ["cta-ink-lockup"],
    ],
    "educational-cards": [
        ["paper-title-card"], ["card-stack"], ["list-stack-press"],
        ["before-after-slider-scrub"], ["cta-ink-lockup"],
    ],
    "data-story": [
        ["brand-ink-open"], ["odometer-digit-roll", "halation-bloom"],
        ["radial-wave"], ["card-stack"], ["cta-ink-lockup"],
    ],
    "social-vertical": [
        ["crash-zoom-punch"], ["gradient-word-sweep"], ["card-stack"],
        ["product-card-progressive-assemble"], ["cta-ink-lockup"],
    ],
}
FAST_RECIPE_REFERENCE_ALIASES = {
    "page-cam-2.5d": "spotlight-hero-card",
    "cta-ink-lockup": "outro-group-photo-launch",
}
OBJECTIVES = {
    "educational",
    "explainer",
    "promotional",
    "tutorial",
    "social_proof",
    "announcement",
    "awareness",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS
MAX_SCENES = 12
MAX_DURATION_SECONDS = 90
MIN_DURATION_SECONDS = 3
DEFAULT_SCENE_SECONDS = 4.2

NAMED_COLORS = {
    "negro": "#111111",
    "black": "#111111",
    "blanco": "#FFFFFF",
    "white": "#FFFFFF",
    "azul": "#2563EB",
    "blue": "#2563EB",
    "navy": "#0F172A",
    "morado": "#7C3AED",
    "purple": "#7C3AED",
    "violeta": "#7C3AED",
    "rosa": "#EC4899",
    "pink": "#EC4899",
    "rojo": "#DC2626",
    "red": "#DC2626",
    "naranja": "#F97316",
    "orange": "#F97316",
    "amarillo": "#EAB308",
    "yellow": "#EAB308",
    "verde": "#16A34A",
    "green": "#16A34A",
    "turquesa": "#0D9488",
    "teal": "#0D9488",
    "dorado": "#C89B3C",
    "gold": "#C89B3C",
    "beige": "#E7D7C5",
    "gris": "#64748B",
    "gray": "#64748B",
    "grey": "#64748B",
}


class MotionGraphicError(ValueError):
    """A buyer-correctable motion-video contract error."""


def _clean_text(value, limit=600):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[\n;|]+", value) if item.strip()]
    return [value]


def normalize_aspect_ratio(value):
    raw = str(value or "9:16").strip().lower().replace("×", ":").replace("x", ":")
    raw = FORMAT_ALIASES.get(raw, raw)
    if raw not in FORMAT_DIMENSIONS:
        raise MotionGraphicError("El formato debe ser 9:16, 4:5, 1:1 o 16:9.")
    return raw


def _path_is_within(path, root):
    try:
        path.relative_to(Path(root).resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def safe_motion_media_path(raw_path, *, expected=None):
    if not str(raw_path or "").strip():
        return None
    try:
        path = Path(str(raw_path)).expanduser().resolve()
    except (OSError, RuntimeError):
        return None
    allowed_roots = [*creative_reference_allowed_roots(), OUTPUT_ROOT]
    if not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS:
        return None
    if not any(_path_is_within(path, root) for root in allowed_roots):
        return None
    if expected == "image" and path.suffix.lower() not in IMAGE_EXTENSIONS:
        return None
    if expected == "video" and path.suffix.lower() not in VIDEO_EXTENSIONS:
        return None
    if expected == "audio" and path.suffix.lower() not in AUDIO_EXTENSIONS:
        return None
    return path


def _library_asset_paths(asset_ids):
    wanted = {str(item or "").strip() for item in _as_list(asset_ids) if str(item or "").strip()}
    if not wanted:
        return []
    library = read_json(CONTENT_ASSET_LIBRARY, {"items": []})
    results = []
    for item in library.get("items") or []:
        if not isinstance(item, dict) or str(item.get("id") or "").strip() not in wanted:
            continue
        if str(item.get("preservation_mode") or "").strip().lower() == "prohibited":
            continue
        for raw in item.get("file_paths") or []:
            path = safe_motion_media_path(raw)
            if path and path not in results:
                results.append(path)
    return results[:12]


def _extract_product_asset_paths(product):
    raw = str((product or {}).get("assets") or "")
    candidates = re.findall(r"(?:/|~/?)[^\s,;|]+\.(?:png|jpe?g|webp|mp4|mov|m4v|webm)", raw, re.I)
    return [path for path in (safe_motion_media_path(item) for item in candidates) if path]


def _hex_to_rgb(value):
    value = str(value or "").lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
        return 17, 24, 39
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, int(value))):02X}" for value in rgb)


def _mix(color, other, amount):
    first = _hex_to_rgb(color)
    second = _hex_to_rgb(other)
    return _rgb_to_hex(tuple(first[index] * (1 - amount) + second[index] * amount for index in range(3)))


def _luminance(color):
    # WCAG relative luminance is gamma-corrected.  The old, simple RGB-weight
    # approximation was fine for choosing a decorative background, but it
    # routinely selected muted copy below readable contrast on dark palettes.
    def linear(value):
        channel = value / 255
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(value) for value in _hex_to_rgb(color))
    return (0.2126 * red) + (0.7152 * green) + (0.0722 * blue)


def contrast_ratio(foreground, background):
    """Return the WCAG contrast ratio for two hexadecimal colors."""
    first = _luminance(foreground)
    second = _luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def readable_text_color(background):
    """Choose the higher-contrast neutral foreground for an arbitrary color."""
    candidates = ("#FFFFFF", "#10131A")
    return max(candidates, key=lambda candidate: contrast_ratio(candidate, background))


def accessible_muted_color(foreground, background, minimum_ratio=5.5):
    """Soften text only while preserving readable contrast against its surface."""
    if contrast_ratio(foreground, background) < minimum_ratio:
        foreground = readable_text_color(background)
    low, high = 0.0, 1.0
    for _ in range(18):
        midpoint = (low + high) / 2
        candidate = _mix(foreground, background, midpoint)
        if contrast_ratio(candidate, background) >= minimum_ratio:
            low = midpoint
        else:
            high = midpoint
    return _mix(foreground, background, low)


def readable_emphasis_color(preferred, background, fallback):
    """Keep a brand highlight only when it is safe to use as text."""
    return preferred if contrast_ratio(preferred, background) >= 4.5 else fallback


def even_render_dimension(value):
    rounded = max(2, round(float(value)))
    return rounded if rounded % 2 == 0 else rounded + 1


def parse_palette(*values):
    colors = []
    text = " ".join(str(value or "") for value in values)
    for match in re.findall(r"#[0-9a-fA-F]{3,8}\b", text):
        normalized = match[:7] if len(match) >= 7 else _rgb_to_hex(_hex_to_rgb(match))
        if normalized.upper() not in colors:
            colors.append(normalized.upper())
    normalized_text = re.sub(r"[^a-záéíóúüñ]+", " ", text.lower())
    for word, color in NAMED_COLORS.items():
        if re.search(rf"\b{re.escape(word)}\b", normalized_text) and color not in colors:
            colors.append(color)
    if not colors:
        colors = ["#4F46E5", "#14B8A6", "#F59E0B"]
    primary = colors[0]
    accent = colors[1] if len(colors) > 1 else _mix(primary, "#FFFFFF", 0.35)
    highlight = colors[2] if len(colors) > 2 else _mix(accent, "#FFFFFF", 0.28)
    darkest = min(colors, key=_luminance)
    background = _mix(darkest, "#05070D", 0.76) if _luminance(darkest) > 0.18 else _mix(darkest, "#05070D", 0.38)
    surface = _mix(background, "#FFFFFF", 0.10)
    text_color = readable_text_color(background)
    surface_text = readable_text_color(surface)
    primary_text = readable_text_color(primary)
    accent_text = readable_text_color(accent)
    highlight_text = readable_text_color(highlight)
    # A brand accent may be excellent as a decorative stroke but unreadable
    # when placed directly on the generated background. Keep the raw accent
    # for shapes and expose a guarded foreground for text overlays.
    accent_on_background = readable_emphasis_color(accent, background, text_color)
    return {
        "background": background,
        "surface": surface,
        "primary": primary,
        "accent": accent,
        "highlight": highlight,
        "text": text_color,
        "mutedText": accessible_muted_color(text_color, background),
        "surfaceText": surface_text,
        "surfaceMutedText": accessible_muted_color(surface_text, surface),
        "primaryText": primary_text,
        "accentText": accent_text,
        "accentOnBackground": accent_on_background,
        "highlightText": highlight_text,
        # Accent colors are still available for strokes and decoration.  Text
        # uses this guarded value so a subtle brand gold or teal never becomes
        # unreadable copy over the background.
        "emphasisText": readable_emphasis_color(highlight, background, text_color),
    }


def typography_stack(value):
    text = str(value or "").lower()
    if any(token in text for token in ("serif", "editorial", "elegant", "luxury", "lujo")):
        return "Georgia, 'Times New Roman', serif"
    if any(token in text for token in ("rounded", "amable", "friendly", "redonde")):
        return "'Trebuchet MS', Verdana, sans-serif"
    if any(token in text for token in ("mono", "technical", "técnic", "codigo", "código")):
        return "'Courier New', monospace"
    return "Inter, Arial, Helvetica, sans-serif"


def motion_profile(value, visual_style=""):
    """Translate natural-language brand pacing into bounded render tokens."""
    text = f"{value or ''} {visual_style or ''}".lower()
    if any(word in text for word in ("energ", "dinám", "dinam", "bold", "deport", "sport", "gaming", "cyber", "rápid", "rapid")):
        return {"preset": "energetic", "entry_seconds": 0.38, "travel_px": 64, "media_scale": 0.90, "stagger_seconds": 0.075, "decor_drift": 0.050}
    if any(word in text for word in ("juguet", "playful", "alegre", "friendly", "amigable", "social", "divertid")):
        return {"preset": "playful", "entry_seconds": 0.50, "travel_px": 52, "media_scale": 0.93, "stagger_seconds": 0.10, "decor_drift": 0.040}
    if any(word in text for word in ("premium", "lujo", "luxury", "elegant", "sofistic", "refinad")):
        return {"preset": "premium", "entry_seconds": 0.90, "travel_px": 22, "media_scale": 0.98, "stagger_seconds": 0.17, "decor_drift": 0.015}
    if any(word in text for word in ("calm", "calmad", "suave", "tranquil", "seren", "care", "salud", "health", "educa")):
        return {"preset": "calm", "entry_seconds": 0.78, "travel_px": 28, "media_scale": 0.97, "stagger_seconds": 0.15, "decor_drift": 0.020}
    return {"preset": "professional", "entry_seconds": 0.62, "travel_px": 38, "media_scale": 0.95, "stagger_seconds": 0.12, "decor_drift": 0.028}


def _resolve_brand_and_product(payload):
    general = general_fields(read_text(GENERAL_GUIDE)) if GENERAL_GUIDE.exists() else {}
    product_ref = str(
        payload.get("product_guide")
        or payload.get("product_id")
        or payload.get("product_name")
        or payload.get("offer")
        or ""
    ).strip()
    product_path = None
    product = {}
    if product_ref:
        try:
            product_path = resolve_product_guide(product_ref)
        except ValueError as exc:
            raise MotionGraphicError(str(exc)) from exc
    elif PRODUCT_DIR.exists():
        choices = product_guide_paths()
        if len(choices) == 1:
            product_path = choices[0]
    if product_path:
        product = product_fields(read_text(product_path))
    return general, product, product_path


def normalize_motion_template(value):
    template = _clean_text(value or "adaptive", 60).lower().replace("_", "-").replace(" ", "-")
    return template if template in MOTION_TEMPLATES else "adaptive"


def _normalize_shot_recipes(raw, scene_type, template, index):
    requested = _as_list(
        raw.get("shot_recipes")
        or raw.get("shot_recipe")
        or raw.get("recipe_cards")
        or raw.get("recipe_card")
    )
    recipes = []
    recipe_refs = []
    for value in requested:
        recipe = _clean_text(value, 80).lower().replace("_", "-").replace(" ", "-")
        try:
            reference = resolve_shotcraft_recipe(FAST_RECIPE_REFERENCE_ALIASES.get(recipe, recipe))
        except ShotcraftCatalogError as exc:
            raise MotionGraphicError(str(exc)) from exc
        canonical = recipe if recipe in SHOT_RECIPE_CATALOG else reference["style"]
        if canonical not in recipes:
            recipes.append(canonical)
            recipe_refs.append({**reference, "requested": canonical})
    if not recipes and template != "adaptive":
        sequence = TEMPLATE_RECIPE_SEQUENCE.get(template) or []
        if sequence:
            recipes = list(sequence[index % len(sequence)])
    if not recipes:
        recipes = list(DEFAULT_SHOT_RECIPES_BY_SCENE[scene_type])

    if not recipe_refs:
        try:
            recipe_refs = [
                {
                    **resolve_shotcraft_recipe(FAST_RECIPE_REFERENCE_ALIASES.get(recipe, recipe)),
                    "requested": recipe,
                }
                for recipe in recipes
            ]
        except ShotcraftCatalogError as exc:
            raise MotionGraphicError(str(exc)) from exc

    # One dominant visual grammar, optionally a compatible typography layer,
    # up to two emphasis layers, and one transition.  This rule works across
    # all 152 cards rather than hard-coding a 24-name shortlist.
    normalized = []
    normalized_refs = []
    dominant_category = ""
    typography = False
    accent_count = 0
    transition = False
    for recipe, reference in zip(recipes, recipe_refs):
        category = reference["category"]
        fast_layer = (SHOT_RECIPE_CATALOG.get(recipe) or {}).get("layer")
        if fast_layer == "transition" or (not fast_layer and category == "transition"):
            if transition:
                continue
            transition = True
        elif fast_layer == "accent" or (not fast_layer and category == "effects"):
            if accent_count >= 2:
                continue
            accent_count += 1
        elif fast_layer == "typography" or (not fast_layer and category == "typography"):
            if typography:
                continue
            typography = True
        else:
            if dominant_category:
                continue
            dominant_category = category
        normalized.append(recipe)
        normalized_refs.append(reference)
        if len(normalized) >= 4:
            break
    return normalized, normalized_refs


def _normalize_scene(raw, index, default_seconds, template="adaptive"):
    raw = raw if isinstance(raw, dict) else {"title": str(raw or "")}
    scene_type = str(raw.get("type") or raw.get("layout") or ("hook" if index == 0 else "statement")).strip().lower()
    aliases = {
        "headline": "hook",
        "title": "statement",
        "bullet": "list",
        "bullets": "list",
        "process": "steps",
        "number": "stat",
        "before_after": "comparison",
        "testimonial": "quote",
        "image": "media",
        "photo": "media",
        "end": "cta",
    }
    scene_type = aliases.get(scene_type, scene_type)
    if scene_type not in SCENE_TYPES:
        scene_type = "statement"
    try:
        seconds = float(raw.get("duration_seconds") or raw.get("seconds") or default_seconds)
    except (TypeError, ValueError):
        seconds = default_seconds
    seconds = max(1.5, min(15.0, seconds))
    items = [_clean_text(item, 150) for item in _as_list(raw.get("items") or raw.get("bullets") or raw.get("steps"))]
    items = [item for item in items if item][:6]
    left = _clean_text(raw.get("left") or raw.get("before"), 180)
    right = _clean_text(raw.get("right") or raw.get("after"), 180)
    motion = _clean_text(raw.get("motion") or raw.get("animation"), 60).lower().replace("_", "-")
    if motion not in MOTION_RECIPES:
        motion = DEFAULT_MOTION_BY_SCENE[scene_type]
    shot_recipes, shot_recipe_refs = _normalize_shot_recipes(raw, scene_type, template, index)
    fast_dominant = next(
        (
            recipe
            for recipe in shot_recipes
            if recipe in SHOT_RECIPE_CATALOG
            and SHOT_RECIPE_CATALOG[recipe]["layer"] in {"base", "camera", "typography"}
        ),
        "",
    )
    compiled_recipe_source = str(
        raw.get("compiled_recipe_source")
        or raw.get("recipe_component_source")
        or raw.get("shot_component_source")
        or ""
    ).strip()
    requires_compiled_recipe = any(recipe not in SHOT_RECIPE_CATALOG for recipe in shot_recipes)
    if requires_compiled_recipe and not compiled_recipe_source:
        selected = ", ".join(shot_recipes)
        references = "; ".join(
            f"{item['card_source']} -> {item['demo_source'] or 'sin demo separado'}"
            for item in shot_recipe_refs
        )
        raise MotionGraphicError(
            "Para usar la receta completa "
            f"{selected}, lee su tarjeta y demo exactos ({references}) y vuelve a enviar "
            "la adaptación de esta escena en compiled_recipe_source."
        )
    layer_asset_paths = []
    for value in _as_list(raw.get("layer_asset_paths") or raw.get("media_paths")):
        candidate = str(value or "").strip()
        if candidate and candidate not in layer_asset_paths:
            layer_asset_paths.append(candidate)
        if len(layer_asset_paths) >= 6:
            break
    return {
        "type": scene_type,
        "eyebrow": _clean_text(raw.get("eyebrow") or raw.get("label"), 80),
        "title": _clean_text(raw.get("title") or raw.get("headline"), 180),
        "body": _clean_text(raw.get("body") or raw.get("description") or raw.get("text"), 420),
        "items": items,
        "stat": _clean_text(raw.get("stat") or raw.get("number") or raw.get("value"), 80),
        "left": left,
        "right": right,
        "quote": _clean_text(raw.get("quote"), 320),
        "attribution": _clean_text(raw.get("attribution") or raw.get("author"), 120),
        "media_path": str(raw.get("media_path") or raw.get("image_path") or "").strip(),
        "layer_asset_paths": layer_asset_paths,
        "media_fit": "contain" if str(raw.get("media_fit") or "").lower() == "contain" else "cover",
        "duration_seconds": seconds,
        "motion": motion,
        "shot_recipe": fast_dominant or (shot_recipes[0] if shot_recipes else ""),
        "shot_recipes": shot_recipes,
        "shot_recipe_refs": shot_recipe_refs,
        "compiled_recipe_source": compiled_recipe_source,
        "transition": next(
            (
                recipe
                for recipe, reference in zip(shot_recipes, shot_recipe_refs)
                if reference["category"] == "transition"
            ),
            "",
        ),
    }


def _default_scenes(payload, general, product):
    objective = str(payload.get("objective") or "educational").strip().lower()
    topic = _clean_text(payload.get("topic") or payload.get("request") or product.get("name") or general.get("offer"), 180)
    if not topic:
        raise MotionGraphicError("Indica el tema del video o envía escenas concretas.")
    audience = _clean_text(payload.get("audience") or product.get("audience") or general.get("ideal_customer"), 180)
    key_points = [_clean_text(item, 150) for item in _as_list(payload.get("key_points") or payload.get("points"))]
    key_points = [item for item in key_points if item][:5]
    if not key_points:
        key_points = [
            _clean_text(product.get("pain") or f"Por qué {topic.lower()} importa", 150),
            _clean_text(product.get("features") or product.get("includes") or "Qué debes observar", 150),
            _clean_text(product.get("desire") or "Cuál es el siguiente paso práctico", 150),
        ]
    key_points = [item for item in key_points if item]
    cta = _clean_text(payload.get("cta") or ("Guarda este video" if objective == "educational" else "Conoce más"), 120)
    introduction = _clean_text(payload.get("intro") or payload.get("summary") or product.get("short_description") or product.get("description"), 360)
    if not introduction:
        introduction = f"Una explicación clara para {audience or 'tomar una mejor decisión'}"
    template = normalize_motion_template(payload.get("template") or payload.get("motion_template"))
    scenes = [
        {"type": "hook", "eyebrow": general.get("category") or objective, "title": topic, "body": introduction, "duration_seconds": 4.2},
        {"type": "list", "eyebrow": "Puntos clave", "title": "Lo importante", "items": key_points, "duration_seconds": 6.2},
    ]
    if template == "ink-press":
        scenes = [
            {"type": "hook", "eyebrow": general.get("category") or objective, "title": topic, "body": introduction, "duration_seconds": 3.8},
            {"type": "statement", "eyebrow": "La idea", "title": introduction, "body": audience, "duration_seconds": 4.2},
            {"type": "steps", "eyebrow": "En contexto", "title": "Lo esencial", "items": key_points, "duration_seconds": 6.0},
            {"type": "media", "eyebrow": product.get("name") or general.get("brand_name"), "title": topic, "body": _clean_text(product.get("features") or product.get("includes"), 320), "duration_seconds": 5.2},
        ]
    if product.get("desire") or product.get("pain"):
        scenes.append(
            {
                "type": "comparison",
                "eyebrow": "Cambio esperado",
                "title": product.get("name") or topic,
                "left": product.get("pain") or "Antes",
                "right": product.get("desire") or "Después",
                "duration_seconds": 5.0,
            }
        )
    scenes.append({"type": "cta", "eyebrow": general.get("brand_name") or "Siguiente paso", "title": cta, "body": _clean_text(product.get("url") or general.get("website"), 180), "duration_seconds": 4.0})
    return scenes


def _copy_asset(path, public_dir, *, label):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    filename = f"{label}-{digest}{path.suffix.lower()}"
    destination = public_dir / "assets" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(path, destination)
    return f"assets/{filename}"


def build_motion_graphic_spec(payload, *, job_id=None):
    payload = dict(payload or {})
    require_visual_assets = str(payload.get("require_visual_assets") or "").strip().lower() in {"1", "true", "yes", "si", "sí", "on"}
    require_transparent_story_element = str(payload.get("require_transparent_story_element") or "").strip().lower() in {"1", "true", "yes", "si", "sí", "on"}
    try:
        minimum_visual_assets = int(payload.get("minimum_visual_assets") or 1)
    except (TypeError, ValueError):
        minimum_visual_assets = 1
    minimum_visual_assets = max(1, min(12, minimum_visual_assets))
    general, product, product_path = _resolve_brand_and_product(payload)
    objective = str(payload.get("objective") or "educational").strip().lower()
    if objective not in OBJECTIVES:
        objective = "educational"
    brand_name_source = general.get("brand_name") or payload.get("brand_name")
    color_source = product.get("visual_colors") or payload.get("colors") or general.get("colors")
    style_source = product.get("visual_style") or product.get("motion_style") or payload.get("visual_style") or general.get("visual_style")
    missing_brand = []
    if not _clean_text(brand_name_source):
        missing_brand.append("nombre de marca")
    if not _clean_text(color_source):
        missing_brand.append("colores")
    if not _clean_text(style_source):
        missing_brand.append("estilo visual")
    if missing_brand:
        raise MotionGraphicError(
            "Antes de producir el video, completa el branding básico: " + ", ".join(missing_brand) + "."
        )
    saved_products = product_guide_paths()
    if objective in {"promotional", "social_proof", "announcement"} and not product_path and len(saved_products) > 1:
        raise MotionGraphicError("Selecciona la oferta, producto o servicio exacto para no mezclar su mensaje con otra ficha.")
    aspect_ratio = normalize_aspect_ratio(payload.get("aspect_ratio") or payload.get("format"))
    template = normalize_motion_template(payload.get("template") or payload.get("motion_template"))
    width, height = FORMAT_DIMENSIONS[aspect_ratio]
    try:
        fps = int(payload.get("fps") or 30)
    except (TypeError, ValueError):
        fps = 30
    fps = 30 if fps not in {24, 25, 30} else fps
    try:
        default_seconds = float(payload.get("scene_duration_seconds") or DEFAULT_SCENE_SECONDS)
    except (TypeError, ValueError):
        default_seconds = DEFAULT_SCENE_SECONDS

    raw_scenes = payload.get("scenes") or payload.get("storyboard") or []
    if isinstance(raw_scenes, dict):
        raw_scenes = raw_scenes.get("scenes") or [raw_scenes]
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raw_scenes = _default_scenes(payload, general, product)
    scenes = [
        _normalize_scene(raw, index, default_seconds, template=template)
        for index, raw in enumerate(raw_scenes[:MAX_SCENES])
    ]
    if not any(
        scene.get("title")
        or scene.get("body")
        or scene.get("items")
        or scene.get("stat")
        or scene.get("quote")
        or scene.get("left")
        or scene.get("right")
        for scene in scenes
    ):
        raise MotionGraphicError("El storyboard necesita al menos un título, texto o lista útil.")
    total_seconds = sum(scene["duration_seconds"] for scene in scenes)
    if total_seconds < MIN_DURATION_SECONDS or total_seconds > MAX_DURATION_SECONDS:
        raise MotionGraphicError(f"La duración total debe estar entre {MIN_DURATION_SECONDS} y {MAX_DURATION_SECONDS} segundos.")

    job_id = job_id or f"motion-{uuid.uuid4().hex[:12]}"
    job_dir = OUTPUT_ROOT / job_id
    public_dir = job_dir / "public"
    public_dir.mkdir(parents=True, exist_ok=True)

    explicit_assets = []
    for raw in _as_list(payload.get("asset_paths") or payload.get("reference_image_paths")):
        path = safe_motion_media_path(raw)
        if path and path not in explicit_assets:
            explicit_assets.append(path)
    for path in _library_asset_paths(payload.get("content_asset_ids")) + _extract_product_asset_paths(product):
        if path not in explicit_assets:
            explicit_assets.append(path)

    copied_assets = []
    for index, path in enumerate(explicit_assets[:12]):
        copied_assets.append({"source": str(path), "src": _copy_asset(path, public_dir, label=f"media-{index + 1}"), "extension": path.suffix.lower()})

    copied_by_source = {item["source"]: item["src"] for item in copied_assets}
    image_assets = [item for item in copied_assets if item["extension"] in IMAGE_EXTENSIONS]
    explicitly_bound_sources = set()
    has_transparent_layer_binding = False
    for index, scene in enumerate(scenes):
        media_path = safe_motion_media_path(scene.pop("media_path", ""))
        if media_path:
            source = str(media_path)
            explicitly_bound_sources.add(source)
            if source not in copied_by_source:
                copied_item = {
                    "source": source,
                    "src": _copy_asset(media_path, public_dir, label=f"scene-{index + 1}"),
                    "extension": media_path.suffix.lower(),
                }
                copied_assets.append(copied_item)
                copied_by_source[source] = copied_item["src"]
            scene["media_src"] = copied_by_source[source]
            scene["media_kind"] = "video" if media_path.suffix.lower() in VIDEO_EXTENSIONS else "image"
        elif image_assets and scene["type"] in {"media", "hook", "comparison", "cta"}:
            scene["media_src"] = image_assets[index % len(image_assets)]["src"]
            scene["media_kind"] = "image"
        else:
            scene["media_src"] = ""
            scene["media_kind"] = ""
        scene["layer_media"] = []
        for layer_index, raw_path in enumerate(scene.pop("layer_asset_paths", [])[:6]):
            layer_path = safe_motion_media_path(raw_path)
            if not layer_path:
                continue
            source = str(layer_path)
            explicitly_bound_sources.add(source)
            has_transparent_layer_binding = True
            if source not in copied_by_source:
                copied_item = {
                    "source": source,
                    "src": _copy_asset(layer_path, public_dir, label=f"scene-{index + 1}-layer-{layer_index + 1}"),
                    "extension": layer_path.suffix.lower(),
                }
                copied_assets.append(copied_item)
                copied_by_source[source] = copied_item["src"]
            scene["layer_media"].append(
                {
                    "src": copied_by_source[source],
                    "kind": "video" if layer_path.suffix.lower() in VIDEO_EXTENSIONS else "image",
                }
            )
        fast_recipe = SHOT_RECIPE_CATALOG.get(scene.get("shot_recipe") or "")
        if fast_recipe and fast_recipe["requires_media"] and not scene["media_src"]:
            original_recipe = scene["shot_recipe"]
            replacement = "paper-title-card" if scene["type"] in {"hook", "statement", "quote", "media"} else DEFAULT_SHOT_RECIPES_BY_SCENE[scene["type"]][0]
            scene["shot_recipes"] = [
                replacement if recipe == scene["shot_recipe"] else recipe
                for recipe in scene["shot_recipes"]
            ]
            scene["shot_recipe"] = replacement
            try:
                replacement_ref = resolve_shotcraft_recipe(replacement)
                scene["shot_recipe_refs"] = [
                    {**replacement_ref, "requested": replacement}
                    if item.get("requested") == original_recipe
                    else item
                    for item in scene.get("shot_recipe_refs") or []
                ]
            except ShotcraftCatalogError:
                pass
        scene["duration_frames"] = max(1, round(scene["duration_seconds"] * fps))

    # A generic typography-only video can be valid. It is not valid after the
    # agent has committed to generated or buyer visual assets: those assets
    # must be deliberately mapped to scenes, not silently dropped.
    if require_visual_assets and len(explicitly_bound_sources) < minimum_visual_assets:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise MotionGraphicError(
            "Este storyboard prometió usar activos visuales, pero solo vinculó "
            f"{len(explicitly_bound_sources)} de los {minimum_visual_assets} requeridos. "
            "Genera o reutiliza los activos y pásalos explícitamente en media_path "
            "o layer_asset_paths de las escenas correspondientes antes de renderizar."
        )
    if require_transparent_story_element and not has_transparent_layer_binding:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise MotionGraphicError(
            "Este storyboard prometió un elemento transparente, pero no hay ningún "
            "layer_asset_paths vinculado. Pasa el PNG transparente devuelto por Image 2 "
            "como capa de la escena donde debe aparecer."
        )

    logo_mode = str(payload.get("logo_usage") or general.get("logo_usage") or "auto").strip().lower()
    logo_path = None if logo_mode in {"never", "nunca", "omit", "none", "no"} else official_brand_logo_path(general)
    logo_src = _copy_asset(logo_path, public_dir, label="official-logo") if logo_path else ""

    audio_path = safe_motion_media_path(payload.get("audio_path") or payload.get("music_path"), expected="audio")
    audio_src = _copy_asset(audio_path, public_dir, label="audio") if audio_path else ""

    product_palette = " ".join(
        filter(
            None,
            [
                product.get("visual_colors", ""),
                product.get("motion_colors", ""),
                product.get("additional_details", "") if "color" in product.get("additional_details", "").lower() else "",
            ],
        )
    )
    palette = parse_palette(product_palette, payload.get("colors"), general.get("colors"))
    visual_style = _clean_text(
        payload.get("visual_style")
        or product.get("visual_style")
        or product.get("motion_style")
        or general.get("visual_style")
        or "editorial moderno",
        360,
    )
    typography = _clean_text(payload.get("typography") or product.get("visual_typography") or general.get("typography"), 180)
    energy = _clean_text(payload.get("energy") or product.get("motion_pacing") or general.get("energy") or "medio", 80)
    resolved_motion_style = _clean_text(product.get("motion_style") or payload.get("motion_style") or visual_style, 240)
    brand_name = _clean_text(brand_name_source, 100)
    offer_name = _clean_text(product.get("name") or payload.get("product_name") or payload.get("offer") or general.get("offer") or "", 140)
    audience = _clean_text(payload.get("audience") or product.get("audience") or general.get("ideal_customer"), 220)

    quality = str(payload.get("quality") or "final").strip().lower()
    if quality not in {"draft", "preview", "final"}:
        quality = "final"
    scale = 0.5 if quality in {"draft", "preview"} else 1.0
    try:
        audio_volume = float(payload.get("audio_volume") or 0.18)
    except (TypeError, ValueError):
        audio_volume = 0.18
    spec = {
        "schema": "admira.motion-graphic.v1",
        "job_id": job_id,
        "created_at": now_iso(),
        "visual_asset_contract": {
            "required": require_visual_assets,
            "minimum_visual_assets": minimum_visual_assets if require_visual_assets else 0,
            "transparent_story_element_required": require_transparent_story_element,
            "explicitly_bound_assets": len(explicitly_bound_sources),
        },
        "objective": objective,
        "template": template,
        "aspect_ratio": aspect_ratio,
        "width": width,
        "height": height,
        "fps": fps,
        "duration_frames": sum(scene["duration_frames"] for scene in scenes),
        "duration_seconds": round(total_seconds, 3),
        "quality": quality,
        "render_scale": scale,
        "brand": {
            "name": brand_name,
            "offer": offer_name,
            "audience": audience,
            "tone": _clean_text(general.get("tone"), 240),
            "visual_style": visual_style,
            "motion_style": resolved_motion_style,
            "energy": energy,
            "motion_profile": motion_profile(energy, resolved_motion_style),
            "must_show": _clean_text(product.get("motion_show") or general.get("show_always"), 280),
            "must_avoid": _clean_text(product.get("motion_avoid") or general.get("avoid_always"), 280),
            "font_family": typography_stack(typography),
            "typography_direction": typography,
            "logo_src": logo_src,
            "palette": palette,
        },
        "product": {
            "id": product_path.stem if product_path else "",
            "guide": str(product_path.relative_to(ROOT_DIR)) if product_path else "",
            "name": offer_name,
        },
        "scenes": scenes,
        "audio": {"src": audio_src, "volume": max(0.0, min(1.0, audio_volume)) if audio_src else 0.0},
        "assets": [{"src": item["src"], "preservation": "pixel_locked"} for item in copied_assets],
        "asset_policy": "Buyer-owned media is copied byte-for-byte and rendered without filters, recoloring, retouching, relighting, beautification, regeneration, or content changes. Layout may crop, scale, frame, mask boundaries, or overlay design.",
        "shotcraft_catalog": shotcraft_catalog_summary(),
    }
    manifest_path = job_dir / "motion-spec.json"
    try:
        build_generated_entrypoint(spec, job_dir)
    except MotionRecipeCompileError as exc:
        raise MotionGraphicError(str(exc)) from exc
    write_json(manifest_path, spec)
    return {"spec": spec, "job_dir": job_dir, "public_dir": public_dir, "manifest_path": manifest_path}


def probe_video(path):
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,avg_frame_rate:format=duration,size",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=True)
        return json.loads(result.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {}


def generate_motion_graphic_video(payload):
    """Build and render one motion-graphics MP4 from a bounded storyboard."""
    try:
        prepared = build_motion_graphic_spec(payload)
    except MotionGraphicError as exc:
        return {"ok": False, "blocked": True, "reason": "motion_graphic_request_incomplete", "error": str(exc)}
    manifest_path = prepared["manifest_path"]
    job_dir = prepared["job_dir"]
    video_path = job_dir / "video.mp4"
    poster_path = job_dir / "poster.png"
    render_log = job_dir / "render.log"
    if not RENDER_SCRIPT.is_file():
        return {"ok": False, "blocked": True, "reason": "motion_renderer_missing", "error": "La instalación no incluye todavía el renderer de motion graphics."}
    node_modules = ROOT_DIR / "node_modules" / "@remotion" / "renderer"
    if not node_modules.exists():
        return {"ok": False, "blocked": True, "reason": "motion_renderer_dependencies_missing", "error": "El renderer de video no está instalado en esta versión. Instala la actualización completa de Admira IA."}
    try:
        timeout = int(os.environ.get("ADMIRA_MOTION_RENDER_TIMEOUT_SECONDS", "1200"))
    except ValueError:
        timeout = 1200
    timeout = max(120, min(3600, timeout))
    command = ["node", str(RENDER_SCRIPT), str(manifest_path), str(video_path), str(poster_path)]
    try:
        result = subprocess.run(
            command,
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "REMOTION_CONCURRENCY": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        render_log.write_text(f"Render timeout after {timeout}s\n{exc.stdout or ''}\n{exc.stderr or ''}", encoding="utf-8")
        return {"ok": False, "blocked": True, "reason": "motion_render_timeout", "error": "El video tardó demasiado en renderizarse. La solicitud quedó guardada y puede reintentarse con menos duración o calidad preview.", "manifest_path": str(manifest_path)}
    render_log.write_text((result.stdout or "") + "\n" + (result.stderr or ""), encoding="utf-8")
    if result.returncode != 0 or not video_path.is_file() or video_path.stat().st_size < 1024:
        detail = _clean_text((result.stderr or result.stdout or "render_failed")[-1600:], 1600)
        return {"ok": False, "blocked": True, "reason": "motion_render_failed", "error": "No pude terminar el MP4 con el renderer local.", "technical_detail": detail, "manifest_path": str(manifest_path)}
    probe = probe_video(video_path)
    stream = ((probe.get("streams") or [{}])[0]) if isinstance(probe, dict) else {}
    spec = prepared["spec"]
    expected_width = even_render_dimension(spec["width"] * spec["render_scale"])
    expected_height = even_render_dimension(spec["height"] * spec["render_scale"])
    if stream and (int(stream.get("width") or 0) != expected_width or int(stream.get("height") or 0) != expected_height):
        return {"ok": False, "blocked": True, "reason": "motion_render_verification_failed", "error": "El MP4 se generó con dimensiones distintas a las solicitadas.", "probe": probe, "manifest_path": str(manifest_path)}
    return {
        "ok": True,
        "type": "motion_graphic_video",
        "video_path": str(video_path),
        "poster_path": str(poster_path) if poster_path.is_file() else "",
        "asset_id": f"{prepared['spec']['job_id']}/video.mp4",
        "manifest_path": str(manifest_path),
        "duration_seconds": spec["duration_seconds"],
        "aspect_ratio": spec["aspect_ratio"],
        "quality": spec["quality"],
        "template": spec["template"],
        "brand": {"name": spec["brand"]["name"], "offer": spec["brand"]["offer"], "product_id": spec["product"]["id"]},
        "scene_count": len(spec["scenes"]),
        "shot_recipes": [scene.get("shot_recipes", []) for scene in spec["scenes"]],
        "probe": probe,
        "buyer_summary": f"Video de {spec['duration_seconds']:.1f}s en formato {spec['aspect_ratio']}, creado con {len(spec['scenes'])} escenas y la identidad de {spec['brand']['offer'] or spec['brand']['name'] or 'la marca'}.",
    }


__all__ = [
    "MotionGraphicError",
    "build_motion_graphic_spec",
    "even_render_dimension",
    "generate_motion_graphic_video",
    "normalize_aspect_ratio",
    "normalize_motion_template",
    "SHOT_RECIPE_CATALOG",
    "motion_profile",
    "parse_palette",
    "probe_video",
    "safe_motion_media_path",
]
