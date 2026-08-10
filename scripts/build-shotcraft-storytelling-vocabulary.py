#!/usr/bin/env python3
"""Regenerate the compact narrative index for every Shotcraft style."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from shotcraft_catalog import load_shotcraft_catalog  # noqa: E402


OUTPUT = (
    ROOT
    / "agent"
    / "skills"
    / "motion-graphics-video"
    / "references"
    / "shotcraft-storytelling-vocabulary.json"
)


def main():
    catalog = load_shotcraft_catalog()
    payload = {
        "schema": "admira.shotcraft-storytelling.v1",
        "catalog_revision": catalog["revision"],
        "card_count": catalog["card_count"],
        "style_count": catalog["style_count"],
        "purpose": "Choose motion by message, narrative role, energy and reading needs; never by visual novelty alone.",
        "styles": [
            {
                "card": card["name"],
                "style": style["key"],
                "category": card["category"],
                "summary": card["summary"],
                "use": card["use"],
                "card_source": card["source"],
                "demo_source": style["demo_source"],
                **style["storytelling"],
            }
            for card in catalog["cards"]
            for style in card["styles"]
        ],
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(payload['styles'])} styles to {OUTPUT}")


if __name__ == "__main__":
    main()
