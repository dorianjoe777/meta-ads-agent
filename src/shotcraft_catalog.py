#!/usr/bin/env python3
"""Read and validate Admira's vendored Video Shotcraft catalog.

The gallery catalog is product reference data, not executable input.  This
module gives the motion renderer a deterministic view of every published card
and style while keeping the small, parameterized fast path separate.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

from product_config import ROOT_DIR


SHOTCRAFT_ROOT = (
    ROOT_DIR
    / "agent"
    / "skills"
    / "motion-graphics-video"
    / "references"
    / "shotcraft"
)
SHOTCRAFT_LIBRARY = SHOTCRAFT_ROOT / "gallery" / "api" / "library.json"

EXPECTED_CARD_COUNT = 152
EXPECTED_STYLE_COUNT = 209

_CATEGORY_STORY = {
    "opening": {
        "layer_role": "dominant",
        "narrative_roles": ["hook", "establish_identity", "open_chapter"],
        "message_fit": ["launch", "brand_statement", "curiosity"],
        "combine_with": ["typography", "effects", "transition"],
    },
    "typography": {
        "layer_role": "dominant_or_support",
        "narrative_roles": ["state_message", "emphasize_phrase", "clarify"],
        "message_fit": ["education", "claim", "quote", "benefit"],
        "combine_with": ["camera", "ui-entrance", "data", "effects", "transition"],
    },
    "ui-entrance": {
        "layer_role": "dominant",
        "narrative_roles": ["demonstrate", "reveal_system", "show_breadth"],
        "message_fit": ["product_demo", "process", "capability", "how_it_works"],
        "combine_with": ["typography", "effects", "transition"],
    },
    "camera": {
        "layer_role": "dominant",
        "narrative_roles": ["direct_attention", "reveal", "immerse"],
        "message_fit": ["product_demo", "transformation", "discovery"],
        "combine_with": ["typography", "effects", "transition"],
    },
    "data": {
        "layer_role": "dominant",
        "narrative_roles": ["prove", "compare", "make_data_tangible"],
        "message_fit": ["evidence", "metric", "before_after", "education"],
        "combine_with": ["typography", "effects", "transition"],
    },
    "interaction": {
        "layer_role": "dominant",
        "narrative_roles": ["show_cause_effect", "demonstrate", "confirm_action"],
        "message_fit": ["tutorial", "workflow", "automation", "feature"],
        "combine_with": ["typography", "effects", "transition"],
    },
    "transition": {
        "layer_role": "transition",
        "narrative_roles": ["bridge", "pivot", "change_chapter"],
        "message_fit": ["contrast", "progression", "pace_change"],
        "combine_with": ["opening", "typography", "ui-entrance", "camera", "data", "interaction", "outro"],
    },
    "rhythm": {
        "layer_role": "dominant_or_transition",
        "narrative_roles": ["build_momentum", "crescendo", "montage"],
        "message_fit": ["launch", "urgency", "multiple_benefits", "high_energy"],
        "combine_with": ["typography", "effects", "transition"],
    },
    "effects": {
        "layer_role": "support",
        "narrative_roles": ["punctuate", "focus", "heighten_emotion"],
        "message_fit": ["emphasis", "reveal", "confirmation", "impact"],
        "combine_with": ["opening", "typography", "ui-entrance", "camera", "data", "interaction", "outro"],
    },
    "outro": {
        "layer_role": "dominant",
        "narrative_roles": ["resolve", "brand_lockup", "invite_action"],
        "message_fit": ["cta", "summary", "brand_recall"],
        "combine_with": ["typography", "effects", "transition"],
    },
}


class ShotcraftCatalogError(ValueError):
    """The requested card/style is absent or the vendored catalog is invalid."""


def _slug(value):
    text = str(value or "").strip().lower().replace("_", "-").replace(" ", "-")
    return re.sub(r"[^a-z0-9.-]+", "-", text).strip("-")


def _camel_slug(value):
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", str(value or ""))
    return _slug(Path(value).stem)


def _safe_catalog_path(relative, *, suffixes=None):
    relative = str(relative or "").strip().replace("\\", "/")
    if not relative or relative.startswith("/") or ".." in Path(relative).parts:
        return None
    candidate = (SHOTCRAFT_ROOT / relative).resolve()
    try:
        candidate.relative_to(SHOTCRAFT_ROOT.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    if suffixes and candidate.suffix.lower() not in suffixes:
        return None
    return candidate


def _reference_demo_names(card):
    source = _safe_catalog_path(card.get("source"), suffixes={".md"})
    if not source:
        return []
    text = source.read_text(encoding="utf-8", errors="ignore")
    names = re.findall(r"([A-Za-z][A-Za-z0-9_-]*\.tsx)\b", text)
    return list(dict.fromkeys(names))


_TEMPLATE_CARD_SOURCES = {
    "brand-ink-open": "template/src/aifl/live/SceneOpen.tsx",
    "deck-deal-flyin": "template/src/aifl/live/SceneFlyIn.tsx",
    "document-typewriter-reveal": "template/src/aifl/live/SceneDetail.tsx",
    "list-stack-press": "template/src/aifl/live/ScenePapers.tsx",
    "outro-group-photo-launch": "template/src/aifl/live/SceneOutroLive.tsx",
    "paper-title-card": "template/src/aifl/PaperTitleCard.tsx",
    "row-embed": "template/src/aifl/live/SceneWbr.tsx",
    "spotlight-hero-card": "template/src/aifl/live/SceneOpen.tsx",
    "type-and-filter": "template/src/aifl/live/SceneDetail.tsx",
}


def _demo_candidates(card):
    candidates = []
    demo_dir = SHOTCRAFT_ROOT / "demos" / card.get("category", "") / card["name"]
    if demo_dir.is_dir():
        candidates.extend(sorted(demo_dir.glob("*.tsx")))
    template = _TEMPLATE_CARD_SOURCES.get(card["name"])
    if template:
        path = _safe_catalog_path(template, suffixes={".tsx"})
        if path:
            candidates.append(path)
    if card["name"] == "shot-transitions":
        for relative in ("assets/lib/FlashCut.tsx", "assets/lib/FlashCut.tsx"):
            path = _safe_catalog_path(relative, suffixes={".tsx"})
            if path:
                candidates.append(path)
    return list(dict.fromkeys(path.resolve() for path in candidates if path.is_file()))


def _source_score(style_key, path, preferred_names):
    style = _slug(style_key)
    file_slug = _camel_slug(path.name)
    simplified = re.sub(r"-(real|retry|v[0-9]+|build)$", "", file_slug)
    score = max(
        SequenceMatcher(None, style, file_slug).ratio(),
        SequenceMatcher(None, style, simplified).ratio(),
    )
    if style == file_slug or style == simplified:
        score += 2
    if path.name in preferred_names:
        score += 0.5
    style_tokens = set(style.split("-"))
    file_tokens = set(simplified.split("-"))
    score += len(style_tokens & file_tokens) / max(1, len(style_tokens | file_tokens))
    return score


def _storytelling_profile(card, style):
    category = _slug(card.get("category"))
    base = _CATEGORY_STORY.get(category, _CATEGORY_STORY["effects"])
    energy_text = str(card.get("energy") or "").lower()
    text = " ".join(
        str(value or "").lower()
        for value in (
            card.get("energy"),
            card.get("duration"),
            card.get("summary"),
            card.get("use"),
            style.get("description"),
            style.get("use"),
        )
    )
    if any(token in energy_text for token in ("极高", "very high")):
        energy, impact = "very_high", "aggressive"
    elif any(token in energy_text for token in ("中高", "高（", "high")):
        energy, impact = "high", "assertive"
    elif any(token in energy_text for token in ("中低", "低（", "low")):
        energy, impact = "low", "gentle"
    else:
        energy, impact = "medium", "balanced"
    if any(token in text for token in ("爆发", "重击", "strobe", "slam", "crash", "whip", "高速", "快切")):
        tempo = "burst"
    elif energy in {"high", "very_high"} or any(token in text for token in ("快速", "加速", "punch", "flash", "冲刺")):
        tempo = "fast"
    elif energy == "low" or any(token in text for token in ("沉稳", "安静", "缓慢", "slow", "calm")):
        tempo = "slow"
    else:
        tempo = "measured"

    if category in {"data", "interaction"}:
        reading_priority = "high"
    elif category in {"rhythm", "transition", "effects"}:
        reading_priority = "low"
    else:
        reading_priority = "medium"

    if energy == "low":
        tone_fit = ["calm", "premium", "trust", "educational"]
    elif energy in {"high", "very_high"}:
        tone_fit = ["bold", "urgent", "energetic", "launch"]
    else:
        tone_fit = ["clear", "professional", "confident", "educational"]
    if category == "data":
        tone_fit = ["credible", "analytical", "educational", "proof_led"]
    elif category == "outro":
        tone_fit = ["decisive", "confident", "memorable", "action_oriented"]

    return {
        "energy": energy,
        "tempo": tempo,
        "impact": impact,
        "reading_priority": reading_priority,
        "layer_role": base["layer_role"],
        "narrative_roles": list(base["narrative_roles"]),
        "message_fit": list(base["message_fit"]),
        "tone_fit": tone_fit,
        "combine_with": list(base["combine_with"]),
        "selection_rule": (
            "Use as the scene's main visual grammar; do not stack with another dominant recipe."
            if base["layer_role"] == "dominant"
            else "Use only when it supports the scene's narrative role and preserves reading time."
        ),
    }


@lru_cache(maxsize=1)
def load_shotcraft_catalog():
    try:
        payload = json.loads(SHOTCRAFT_LIBRARY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShotcraftCatalogError("El catálogo completo de Shotcraft no está disponible en esta instalación.") from exc
    cards = payload.get("cards") or []
    card_count = int((payload.get("stats") or {}).get("cardCount") or len(cards))
    style_count = int((payload.get("stats") or {}).get("styleCount") or 0)
    if card_count != EXPECTED_CARD_COUNT or style_count != EXPECTED_STYLE_COUNT or len(cards) != EXPECTED_CARD_COUNT:
        raise ShotcraftCatalogError(
            f"El catálogo Shotcraft está incompleto ({len(cards)} tarjetas, {style_count} estilos)."
        )

    by_card = {}
    by_style = {}
    normalized_cards = []
    for raw in cards:
        name = _slug(raw.get("name"))
        source = _safe_catalog_path(raw.get("source"), suffixes={".md"})
        if not name or not source:
            raise ShotcraftCatalogError(f"Tarjeta Shotcraft inválida: {raw.get('name') or 'sin nombre'}.")
        candidates = _demo_candidates({**raw, "name": name})
        preferred_names = _reference_demo_names(raw)
        styles = []
        for style_raw in raw.get("styles") or []:
            key = _slug(style_raw.get("key"))
            if not key or key in by_style:
                raise ShotcraftCatalogError(f"Estilo Shotcraft inválido o duplicado: {key or 'sin nombre'}.")
            chosen = max(candidates, key=lambda path: _source_score(key, path, preferred_names)) if candidates else None
            style = {
                "key": key,
                "label": str(style_raw.get("label") or key),
                "description": str(style_raw.get("description") or raw.get("summary") or ""),
                "demo_source": str(chosen.relative_to(SHOTCRAFT_ROOT)) if chosen else "",
            }
            style["storytelling"] = _storytelling_profile(raw, {**style_raw, **style})
            styles.append(style)
            by_style[key] = {"card": name, **style}
        card = {
            "name": name,
            "category": _slug(raw.get("category")),
            "summary": str(raw.get("summary") or ""),
            "use": str(raw.get("use") or ""),
            "duration": str(raw.get("duration") or ""),
            "energy": str(raw.get("energy") or ""),
            "intention": str(raw.get("intention") or ""),
            "source": str(source.relative_to(SHOTCRAFT_ROOT)),
            "demo_sources": [str(path.relative_to(SHOTCRAFT_ROOT)) for path in candidates],
            "styles": styles,
        }
        by_card[name] = card
        normalized_cards.append(card)
    if len(by_style) != EXPECTED_STYLE_COUNT:
        raise ShotcraftCatalogError(f"El catálogo Shotcraft resolvió solo {len(by_style)} estilos.")
    return {
        "revision": str(payload.get("revision") or ""),
        "cards": normalized_cards,
        "by_card": by_card,
        "by_style": by_style,
        "categories": payload.get("categories") or {},
        "card_count": len(normalized_cards),
        "style_count": len(by_style),
    }


def resolve_shotcraft_recipe(value, style=None):
    """Resolve a card name or style key to exact vendored provenance."""
    catalog = load_shotcraft_catalog()
    requested = _slug(value)
    requested_style = _slug(style)
    if requested in catalog["by_card"]:
        card = catalog["by_card"][requested]
        if requested_style:
            match = next((item for item in card["styles"] if item["key"] == requested_style), None)
            if not match:
                raise ShotcraftCatalogError(
                    f"El estilo '{requested_style}' no pertenece a la tarjeta '{requested}'."
                )
        else:
            match = card["styles"][0]
    elif requested in catalog["by_style"]:
        style_record = catalog["by_style"][requested]
        card = catalog["by_card"][style_record["card"]]
        match = next(item for item in card["styles"] if item["key"] == requested)
        if requested_style and requested_style != requested:
            raise ShotcraftCatalogError(
                f"La receta '{requested}' ya identifica un estilo; no combines otro style-key distinto."
            )
    else:
        raise ShotcraftCatalogError(
            f"La receta Shotcraft '{requested or value}' no existe en el catálogo instalado."
        )
    return {
        "card": card["name"],
        "style": match["key"],
        "category": card["category"],
        "summary": card["summary"],
        "use": card["use"],
        "card_source": card["source"],
        "demo_source": match.get("demo_source") or (card["demo_sources"][0] if card["demo_sources"] else ""),
        "catalog_revision": catalog["revision"],
        "storytelling": match["storytelling"],
    }


def shotcraft_catalog_summary():
    catalog = load_shotcraft_catalog()
    return {
        "revision": catalog["revision"],
        "card_count": catalog["card_count"],
        "style_count": catalog["style_count"],
        "categories": sorted(catalog["categories"]),
    }


def _search_terms(value):
    return {
        token
        for token in re.findall(r"[a-z0-9áéíóúüñ_-]{2,}", str(value or "").lower())
        if token not in {"and", "con", "del", "para", "the", "una", "uno", "use", "usar"}
    }


_QUERY_HINTS = {
    "calm": {"low", "slow", "gentle", "calm", "premium", "trust", "education", "educational"},
    "calmado": {"low", "slow", "gentle", "calm", "premium", "trust", "education", "educational"},
    "lento": {"low", "slow", "gentle", "calm", "trust"},
    "aggressive": {"high", "very_high", "burst", "aggressive", "bold", "urgent", "impact"},
    "agresivo": {"high", "very_high", "burst", "aggressive", "bold", "urgent", "impact"},
    "energetic": {"high", "very_high", "fast", "burst", "energetic", "launch"},
    "energético": {"high", "very_high", "fast", "burst", "energetic", "launch"},
    "educational": {"education", "educational", "tutorial", "clarify", "high"},
    "educativo": {"education", "educational", "tutorial", "clarify", "high"},
    "launch": {"launch", "urgency", "crescendo", "high_energy", "bold"},
    "lanzamiento": {"launch", "urgency", "crescendo", "high_energy", "bold"},
    "proof": {"prove", "evidence", "credible", "analytical", "metric"},
    "prueba": {"prove", "evidence", "credible", "analytical", "metric"},
    "tutorial": {"tutorial", "workflow", "demonstrate", "show_cause_effect", "educational"},
}


def search_shotcraft_recipes(filters=None):
    """Return a bounded, provenance-rich selection from all 209 styles.

    The agent supplies narrative constraints instead of loading the complete
    catalog into one prompt.  Exact filters remain deterministic; the free-text
    query only ranks matching catalog facts and never invents a recipe.
    """
    filters = filters if isinstance(filters, dict) else {}
    catalog = load_shotcraft_catalog()
    category = _slug(filters.get("category"))
    energy = _slug(filters.get("energy")).replace("-", "_")
    tempo = _slug(filters.get("tempo")).replace("-", "_")
    impact = _slug(filters.get("impact")).replace("-", "_")
    narrative_role = _slug(filters.get("narrative_role")).replace("-", "_")
    message_fit = _slug(filters.get("message_fit")).replace("-", "_")
    tone_fit = _slug(filters.get("tone_fit")).replace("-", "_")
    query = str(filters.get("query") or "").strip()
    query_terms = _search_terms(query)
    expanded_terms = set(query_terms)
    for term in query_terms:
        expanded_terms.update(_QUERY_HINTS.get(term, set()))
    try:
        limit = max(1, min(20, int(filters.get("limit") or 8)))
    except (TypeError, ValueError):
        limit = 8

    matches = []
    for card in catalog["cards"]:
        if category and card["category"] != category:
            continue
        for style in card["styles"]:
            story = style["storytelling"]
            exact_constraints = (
                (energy, story["energy"]),
                (tempo, story["tempo"]),
                (impact, story["impact"]),
            )
            if any(expected and actual != expected for expected, actual in exact_constraints):
                continue
            list_constraints = (
                (narrative_role, story["narrative_roles"]),
                (message_fit, story["message_fit"]),
                (tone_fit, story["tone_fit"]),
            )
            if any(expected and expected not in actual for expected, actual in list_constraints):
                continue
            searchable = " ".join(
                [
                    card["name"],
                    style["key"],
                    card["category"],
                    card["summary"],
                    card["use"],
                    style["description"],
                    story["energy"],
                    story["tempo"],
                    story["impact"],
                    story["reading_priority"],
                    *story["narrative_roles"],
                    *story["message_fit"],
                    *story["tone_fit"],
                ]
            ).lower()
            matched_terms = sorted(term for term in expanded_terms if term in searchable)
            score = len(matched_terms) * 3
            if query and query.lower() in searchable:
                score += 8
            if style["key"] in query.lower() or card["name"] in query.lower():
                score += 12
            if expanded_terms and not matched_terms and score == 0:
                continue
            matches.append(
                {
                    "card": card["name"],
                    "style": style["key"],
                    "category": card["category"],
                    "summary": card["summary"],
                    "use": card["use"],
                    "card_source": card["source"],
                    "demo_source": style["demo_source"],
                    **story,
                    "matched_terms": matched_terms,
                    "score": score,
                }
            )
    matches.sort(key=lambda item: (-item["score"], item["card"], item["style"]))
    return {
        "ok": True,
        "catalog_revision": catalog["revision"],
        "card_count": catalog["card_count"],
        "style_count": catalog["style_count"],
        "query": query,
        "filters": {
            key: value
            for key, value in {
                "category": category,
                "energy": energy,
                "tempo": tempo,
                "impact": impact,
                "narrative_role": narrative_role,
                "message_fit": message_fit,
                "tone_fit": tone_fit,
            }.items()
            if value
        },
        "matches": matches[:limit],
        "match_count": len(matches),
    }


__all__ = [
    "EXPECTED_CARD_COUNT",
    "EXPECTED_STYLE_COUNT",
    "SHOTCRAFT_LIBRARY",
    "SHOTCRAFT_ROOT",
    "ShotcraftCatalogError",
    "load_shotcraft_catalog",
    "resolve_shotcraft_recipe",
    "search_shotcraft_recipes",
    "shotcraft_catalog_summary",
]
