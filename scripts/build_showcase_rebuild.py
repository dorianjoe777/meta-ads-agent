#!/usr/bin/env python3
"""Build intentionally diverse showcase briefs for motion canary renders."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "showcase-rebuild"
ASSETS = OUT / "assets"
LEGACY = ROOT / "output" / "showcase-canary" / "assets"


def scene(kind, eyebrow, title, body, recipe, media, *, items=None, left="", right="", seconds=4.6):
    return {
        "type": kind,
        "eyebrow": eyebrow,
        "title": title,
        "body": body,
        "items": items or [],
        "left": left,
        "right": right,
        "duration_seconds": seconds,
        "media_path": str(media),
        "shot_recipes": [recipe],
    }


def brief(slug, brand_name, colors, style, energy, aspect_ratio, objective, topic, audience, cta, story, mark, scenes):
    return {
        "slug": slug,
        "brand_name": brand_name,
        "colors": colors,
        "visual_style": style,
        "energy": energy,
        "template": "adaptive",
        "aspect_ratio": aspect_ratio,
        "objective": objective,
        "topic": topic,
        "audience": audience,
        "cta": cta,
        "asset_paths": [str(story), str(mark)],
        "scenes": scenes,
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    story = {
        "aura": ASSETS / "aura-serum.png",
        "brujula": ASSETS / "brujula-pour-over.png",
        "norte": ASSETS / "norte-dumbbells.png",
        "singularity": ASSETS / "singularity-mic.png",
    }
    mark = {
        "aura": LEGACY / "aura-brand-mark.png",
        "brujula": LEGACY / "brujula-brand-mark.png",
        "norte": LEGACY / "norte-brand-mark.png",
        "singularity": LEGACY / "singularity-brand-mark.png",
    }
    specs = [
        brief(
            "aura-skin-studio-v2", "AURA Skin Studio", "marfil, rosa, vino, dorado",
            "premium editorial, calm, luminous, elegant", "calm premium", "9:16", "educational",
            "Una rutina facial que sí puedes sostener", "Personas que buscan cuidado facial simple",
            "Guarda este ritual", story["aura"], mark["aura"], [
                scene("media", "AURA · diagnóstico", "La piel pide señales, no ruido", "Observa la sensación antes de sumar productos.", "page-cam-2.5d", story["aura"], seconds=4.8),
                scene("comparison", "Antes / después", "Tirar más no es cuidar mejor", "Una barrera tranquila se construye con constancia.", "before-after-slider-scrub", story["aura"], left="Rutina saturada", right="Ritual sostenible", seconds=4.8),
                scene("media", "El producto", "Textura, pausa y contacto", "Integra cada paso sin perder la experiencia sensorial.", "product-card-progressive-assemble", story["aura"], seconds=4.8),
                scene("statement", "Ritual AURA", "Tres minutos también cuentan", "Limpia, hidrata y protege. Repite con calma.", "paper-title-card", mark["aura"], seconds=4.5),
                scene("cta", "AURA Skin Studio", "Empieza pequeño", "Guarda el ritual y vuelve a él esta noche.", "cta-ink-lockup", mark["aura"], seconds=4.5),
            ],
        ),
        brief(
            "brujula-cafe-v2", "Brújula Café", "café, terracota, crema, naranja",
            "editorial cálido, artesanal, tactile, cinematic", "measured curious", "4:5", "tutorial",
            "Extraer café con intención", "Personas que quieren mejorar su café en casa",
            "Guarda la guía", story["brujula"], mark["brujula"], [
                # Coffee is a story subject, not a decorative filename: every
                # image-led scene uses a different media-capable recipe and a
                # different accent layer so the cutout remains visible while
                # the motion language changes.
                scene("media", "BRÚJULA · apertura", "El sabor empieza antes del sorbo", "La extracción tiene ritmo, aroma y equilibrio.", "page-cam-2.5d", story["brujula"], seconds=4.8),
                scene("media", "Paso 01", "Mira el flujo", "El agua debe atravesar el café sin correr ni quedarse quieta.", "product-card-progressive-assemble", story["brujula"], seconds=4.8),
                scene("media", "Paso 02", "Busca equilibrio", "Acidez, dulzor y cuerpo deben sentirse como una conversación.", "multiplane", story["brujula"], seconds=4.8),
                scene("steps", "La diferencia", "Ajusta una variable", "Cambia solo una cosa y vuelve a probar.", "page-waterfall-wall", story["brujula"], items=["Tu pausa", "Tu mesa", "Tu mezcla"], seconds=4.8),
                scene("cta", "Brújula Café", "Encuentra tu próxima taza", "Guarda la guía y pruébala mañana.", "brand-ink-open", mark["brujula"], seconds=4.5),
            ],
        ),
        brief(
            "norte-fit-v2", "Norte Fit", "azul noche, menta, blanco, lima",
            "athletic editorial, bold, kinetic, high contrast", "energetic athletic", "1:1", "tutorial",
            "Fuerza que puedes repetir", "Personas ocupadas que quieren entrenar sin complicarse",
            "Empieza con una sesión", story["norte"], mark["norte"], [
                scene("hook", "NORTE FIT · fuerza sostenible", "No necesitas entrenar perfecto", "Necesitas una sesión que puedas volver a hacer mañana.", "crash-zoom-punch", story["norte"], seconds=4.8),
                scene("stat", "Bloque 01", "Activa", "Prepara el cuerpo con movimientos simples y controlados.", "odometer-digit-roll", story["norte"], seconds=4.8),
                scene("steps", "Bloque 02", "Construye", "Elige un ejercicio base y repítelo con buena técnica.", "list-stack-press", story["norte"], items=["Control", "Rango", "Progreso"], seconds=4.8),
                scene("steps", "Bloque 03", "Cierra", "Termina con energía suficiente para volver a empezar.", "card-stack", story["norte"], items=["Baja el ritmo", "Registra", "Descansa"], seconds=4.8),
                scene("cta", "Norte Fit", "Tu norte es la constancia", "Guarda la rutina y hazla tuya esta semana.", "gradient-word-sweep", mark["norte"], seconds=4.5),
            ],
        ),
        brief(
            "singularity-x-records-v2", "Singularity X Records", "negro, blanco, cian, magenta",
            "experimental music editorial, cinematic, high contrast, precise", "bold cinematic", "16:9", "awareness",
            "Una canción también se diseña", "Artistas que quieren convertir identidad en sonido",
            "Escucha lo que viene", story["singularity"], mark["singularity"], [
                scene("media", "SINGULARITY X · estudio", "El sonido también tiene arquitectura", "Cada textura deja una decisión visible.", "multiplane", story["singularity"], seconds=4.8),
                scene("comparison", "Capa 01", "La textura", "Elige el espacio donde la idea puede respirar.", "before-after-slider-scrub", story["singularity"], left="Silencio", right="Pulso", seconds=4.8),
                scene("media", "Capa 02", "El movimiento", "Entrada, pausa y repetición cambian lo que sentimos.", "product-card-progressive-assemble", story["singularity"], seconds=4.8),
                scene("statement", "Capa 03", "La identidad", "Cuando todo encaja, reconoces el sonido antes del nombre.", "radial-wave", mark["singularity"], seconds=4.8),
                scene("cta", "Singularity X Records", "Haz que tu idea tenga órbita", "Escucha lo que viene.", "cta-ink-lockup", mark["singularity"], seconds=4.5),
            ],
        ),
    ]
    for spec in specs:
        (OUT / f"{spec['slug']}.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "manifest.json").write_text(
        json.dumps({"version": "showcase-rebuild-v2", "unique_primary_recipes": True, "specs": [s["slug"] for s in specs]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("built", len(specs), "specs in", OUT)


if __name__ == "__main__":
    main()
