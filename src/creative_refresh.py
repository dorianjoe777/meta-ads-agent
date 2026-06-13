#!/usr/bin/env python3
"""Creative refresh planning for Codex/Image ad creative workflows."""
import base64
import copy
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from product_config import ROOT_DIR, load_config
from codex_brand_guides import creative_memory
from local_store import now_iso, read_json, write_json


AD_CONFIG_FILE = ROOT_DIR / "ad-config.json"
AD_CONFIG_EXAMPLE_FILE = ROOT_DIR / "ad-config.example.json"
OUTPUT_DIR = ROOT_DIR / "output" / "creatives"
INDEX_FILE = OUTPUT_DIR / "creative_refresh_index.json"
CREATIVE_IMAGE_STORAGE_POLICY = "manual_cleanup"
ASSET_STORAGE_KEY = "retention"

def parse_iso(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed

def asset_created_at(asset, plan=None, path=None):
    created = parse_iso(asset.get("created_at") or asset.get(ASSET_STORAGE_KEY, {}).get("created_at") or (plan or {}).get("created_at"))
    if created:
        return created
    if path and Path(path).exists():
        try:
            return datetime.fromtimestamp(Path(path).stat().st_mtime, tz=timezone.utc).astimezone()
        except OSError:
            return datetime.now(timezone.utc).astimezone()
    return datetime.now(timezone.utc).astimezone()


def asset_storage_state(asset, plan=None):
    """Return buyer-facing storage metadata for a generated creative asset."""
    storage = dict(asset.get(ASSET_STORAGE_KEY) or {})
    path = asset.get("path")
    created = asset_created_at(asset, plan, path)
    saved = bool(storage.get("saved") or asset.get("retained_for_ad"))
    if saved:
        return {
            **storage,
            "kind": storage.get("kind") or "ad_image",
            "saved": True,
            "created_at": storage.get("created_at") or created.isoformat(timespec="seconds"),
            "expires_at": "",
            "days_remaining": None,
            "status": "saved",
        }
    status = "deleted" if storage.get("deleted_at") else "temporary"
    return {
        **storage,
        "kind": storage.get("kind") or "temporary",
        "saved": False,
        "created_at": storage.get("created_at") or created.isoformat(timespec="seconds"),
        "expires_at": "",
        "days_remaining": None,
        "status": status,
        "cleanup": CREATIVE_IMAGE_STORAGE_POLICY,
    }


def set_asset_storage(asset, storage):
    asset[ASSET_STORAGE_KEY] = storage
    return storage


def asset_retention(asset, plan=None, *_):
    """Backward-compatible name for older callers and stored manifest vocabulary."""
    return asset_storage_state(asset, plan)


def manifest_paths():
    if not OUTPUT_DIR.exists():
        return []
    return sorted(OUTPUT_DIR.glob("*/manifest.json"))


def normalize_path(value):
    try:
        return Path(str(value or "")).expanduser().resolve()
    except OSError:
        return None


def path_under_output(path):
    if not path:
        return False
    try:
        Path(path).resolve().relative_to(OUTPUT_DIR.resolve())
        return True
    except (OSError, ValueError):
        return False


def iter_variant_assets(plan, variant_id=""):
    for variant in plan.get("variants", []):
        if variant_id and variant.get("variant_id") != variant_id:
            continue
        for asset in variant.get("assets", []):
            yield variant, asset


def mark_assets_retained(manifest_path, variant_id="", selected_ratios=None, file_paths=None, reason="selected_for_ad", meta=None):
    manifest_path = Path(manifest_path)
    plan = read_json(manifest_path, {})
    if not isinstance(plan, dict) or not plan.get("variants"):
        return {"updated": 0, "manifest_path": str(manifest_path)}
    ratios = set(selected_ratios or [])
    target_paths = {path for path in (normalize_path(item) for item in (file_paths or [])) if path}
    now = now_iso()
    updated = 0
    for _variant, asset in iter_variant_assets(plan, variant_id):
        asset_path = normalize_path(asset.get("path"))
        ratio_match = not ratios or asset.get("aspect_ratio") in ratios
        path_match = not target_paths or (asset_path and asset_path in target_paths)
        if not asset.get("path") or not ratio_match or not path_match:
            continue
        storage = asset_storage_state(asset, plan)
        set_asset_storage(asset, {
            **storage,
            "kind": "ad_image",
            "saved": True,
            "saved_at": now,
            "reason": reason,
            "meta": meta or {},
            "expires_at": "",
            "status": "saved",
        })
        asset["retained_for_ad"] = True
        updated += 1
    if updated:
        write_json(manifest_path, plan)
    return {"updated": updated, "manifest_path": str(manifest_path)}


def mark_asset_files_retained(file_paths, reason="ad_created", meta=None):
    target_paths = {path for path in (normalize_path(item) for item in (file_paths or [])) if path}
    if not target_paths:
        return {"updated": 0, "files": 0}
    updated = 0
    for manifest_path in manifest_paths():
        result = mark_assets_retained(manifest_path, file_paths=target_paths, reason=reason, meta=meta)
        updated += result.get("updated", 0)
    return {"updated": updated, "files": len(target_paths)}


def clear_temporary_creative_assets(reason="manual_storage_cleanup"):
    stats = {"mode": CREATIVE_IMAGE_STORAGE_POLICY, "scanned": 0, "deleted": 0, "saved": 0, "skipped": 0, "errors": 0}
    for manifest_path in manifest_paths():
        plan = read_json(manifest_path, {})
        if not isinstance(plan, dict):
            continue
        changed = False
        for _variant, asset in iter_variant_assets(plan):
            raw_path = str(asset.get("path") or "").strip()
            if not raw_path:
                continue
            path = normalize_path(raw_path)
            stats["scanned"] += 1
            storage = set_asset_storage(asset, asset_storage_state(asset, plan))
            if storage.get("saved"):
                stats["saved"] += 1
                continue
            if storage.get("deleted_at"):
                continue
            if not path or not path_under_output(path):
                stats["skipped"] += 1
                continue
            try:
                if path.exists() and path.is_file():
                    path.unlink()
                    stats["deleted"] += 1
                else:
                    stats["skipped"] += 1
                asset["path"] = ""
                set_asset_storage(asset, {
                    **storage,
                    "deleted_at": now_iso(),
                    "deleted_reason": reason,
                    "status": "deleted",
                })
                changed = True
            except OSError:
                stats["errors"] += 1
        if changed:
            write_json(manifest_path, plan)
    return stats


def load_ad_config():
    return read_json(AD_CONFIG_FILE, read_json(AD_CONFIG_EXAMPLE_FILE, {}))


def pct_change(current, previous):
    current = float(current or 0)
    previous = float(previous or 0)
    if previous == 0:
        return 0.0
    return ((current - previous) / previous) * 100


def should_refresh(campaign, ad_config=None):
    ad_config = ad_config or load_ad_config()
    refresh = ad_config.get("creative", {}).get("refresh_when", {})
    health_in = set(refresh.get("health_in", ["fatigue", "losing"]))
    if campaign.get("health") in health_in:
        return True
    frequency_over = float(refresh.get("frequency_over", 3.0))
    roas_below = float(refresh.get("roas_below", 1.2))
    ctr_drop_pct_over = float(refresh.get("ctr_drop_pct_over", 20))
    ctr_drop = pct_change(campaign.get("ctr"), campaign.get("previous_ctr"))
    return (
        float(campaign.get("frequency", 0)) > frequency_over
        or float(campaign.get("roas", 0)) < roas_below
        or ctr_drop <= -abs(ctr_drop_pct_over)
    )


def campaigns_needing_refresh(campaigns, ad_config=None):
    return [campaign for campaign in campaigns if should_refresh(campaign, ad_config)]


def apply_brand_memory(ad_config, product_guide="", ad_brief=""):
    effective = copy.deepcopy(ad_config)
    memory = creative_memory(product_guide, ad_brief)
    brand = effective.setdefault("brand", {})
    for key, value in memory.get("brand", {}).items():
        if value:
            brand[key] = value
    return effective, memory


def split_axes(value):
    axes = [item.strip() for item in str(value or "").replace(";", ",").split(",") if item.strip()]
    return axes or ["color", "gancho visual", "composicion", "beneficio principal"]


def variation_count(value, fallback):
    try:
        count = int(str(value or "").strip())
    except (TypeError, ValueError):
        return fallback
    return min(max(count, 1), 8)


def copy_variants(campaign, ad_config, count):
    brand = ad_config.get("brand", {})
    offer = brand.get("offer", "the offer")
    voice = brand.get("voice", "clear, direct, benefit-led")
    name = campaign.get("name", "Campaign")
    voice = {"clear, direct, benefit-led": "claro, directo y centrado en beneficios"}.get(voice, voice)
    pain = brand.get("pain") or ("fatiga del anuncio" if campaign.get("health") == "fatigue" else "baja eficiencia de conversión")
    desire = brand.get("desire") or "un resultado más claro"
    if brand.get("variation_window") or brand.get("base_ad"):
        axes = split_axes(brand.get("variation_axes"))
        promotion = brand.get("promotion") or "la promocion actual"
        base_ad = brand.get("base_ad") or brand.get("base_ad_name") or "el anuncio que ya funciona"
        locked = brand.get("locked_elements") or "la promesa central, la oferta y el publico"
        window = brand.get("variation_window") or "probar cambios pequeños y medibles"
        variants = []
        for index in range(count):
            axis = axes[index % len(axes)]
            variants.append(
                {
                    "headline": f"{offer}: variante de {axis}",
                    "primary_text": (
                        f"Partir de {base_ad}. Mantener {locked}. Probar solo {axis} dentro de esta ventana: "
                        f"{window}. Promocion o idea puntual: {promotion}."
                    ),
                    "cta": "Ver oferta",
                    "angle": f"variacion de {axis}",
                }
            )
        return variants
    templates = [
        {
            "headline": f"Descubre por qué {offer} funciona",
            "primary_text": f"{name} necesita un ángulo fresco. Abre con {desire}, haz la promesa concreta y facilita el siguiente clic.",
            "cta": "Más información",
            "angle": "prueba y confianza",
        },
        {
            "headline": "Una mejor forma de empezar",
            "primary_text": f"Usa un mensaje {voice} que hable directamente de {pain}. Muestra el producto con claridad y deja obvio el primer paso.",
            "cta": "Comprar ahora",
            "angle": "respuesta directa",
        },
        {
            "headline": "Nueva imagen, la misma oferta",
            "primary_text": f"Presenta {offer} con una imagen limpia, un beneficio y una razón sencilla para actuar hoy.",
            "cta": "Ver oferta",
            "angle": "renovar oferta",
        },
        {
            "headline": "Detente. Empieza aquí.",
            "primary_text": "Dale una nueva oportunidad a la campaña con un gancho más claro y una imagen cuyo valor se entienda al instante.",
            "cta": "Más información",
            "angle": "detener el scroll",
        },
    ]
    return templates[:count]


def image_prompt(campaign, ad_config, variant, aspect_ratio):
    brand = ad_config.get("brand", {})
    avoid_items = brand.get("avoid", [])
    avoid = ", ".join(avoid_items if isinstance(avoid_items, list) else [str(avoid_items)]) or "misleading claims, excessive text"
    ad_context = ""
    if brand.get("variation_window") or brand.get("promotion"):
        ad_context = (
            f"Promocion o idea puntual: {brand.get('promotion', 'no especificada')}. "
            f"Anuncio base o aprendizaje previo: {brand.get('base_ad') or brand.get('base_ad_name') or 'no especificado'}. "
            f"No cambiar: {brand.get('locked_elements', 'la oferta esencial')}. "
            f"Ventana creativa permitida: {brand.get('variation_window', 'variaciones moderadas')}. "
        )
    return (
        f"Crea una imagen para anuncio de Meta de {brand.get('name', 'una marca premium')}. "
        f"Campaña: {campaign.get('name', 'Campaña')}. "
        f"Objetivo: renovar un anuncio con estado {campaign.get('health', 'neutral')} usando el ángulo '{variant['angle']}'. "
        f"Oferta: {brand.get('offer', 'producto o servicio premium')}. "
        f"Audiencia: {brand.get('audience', 'personas interesadas en la oferta')}. "
        f"{ad_context}"
        f"Estilo visual: {brand.get('visual_style', 'fotografía ecommerce premium, limpia y confiable')}. "
        f"Formato: {aspect_ratio}. "
        "Usa un punto focal claro, producto o contexto reconocible, luz realista y poco o ningún texto integrado. "
        f"Evita: {avoid}."
    )


def build_creative_plan(campaign, ad_config=None, variants_per_campaign=None, product_guide="", ad_brief=""):
    config = load_config()
    ad_config = ad_config or load_ad_config()
    ad_config, memory = apply_brand_memory(ad_config, product_guide, ad_brief)
    creative_cfg = ad_config.get("creative", {})
    brand = ad_config.get("brand", {})
    default_count = config.creative_variants_per_campaign or int(creative_cfg.get("variants_per_campaign", 3))
    count = variants_per_campaign or variation_count(brand.get("variation_count"), default_count)
    aspect_ratios = creative_cfg.get("default_aspect_ratios", ["1:1", "4:5", "9:16"])
    variants = []
    for index, copy in enumerate(copy_variants(campaign, ad_config, count), start=1):
        prompts = [{"aspect_ratio": ratio, "prompt": image_prompt(campaign, ad_config, copy, ratio)} for ratio in aspect_ratios]
        variants.append({"variant_id": f"v{index}", "copy": copy, "image_prompts": prompts, "assets": []})
    return {
        "id": f"creative_{campaign.get('id', 'campaign')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "created_at": now_iso(),
        "status": "draft",
        "provider": "codex-image",
        "image_mode": "codex-image",
        "brand_memory": memory,
        "campaign": {
            "id": campaign.get("id"),
            "name": campaign.get("name"),
            "health": campaign.get("health"),
            "roas": campaign.get("roas"),
            "ctr": campaign.get("ctr"),
            "frequency": campaign.get("frequency"),
        },
        "variants": variants,
        "upload_policy": {
            "create_ads_as_paused": bool(creative_cfg.get("create_ads_as_paused", True)),
            "requires_approval": True,
        },
    }


def call_nano_banana(prompt, aspect_ratio, config):
    if not config.gemini_api_key:
        return {"ok": False, "error": "Legacy image provider is disabled. Use Codex/Image from the agent."}
    model = config.nano_banana_model
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"imageConfig": {"aspectRatio": aspect_ratio}},
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "x-goog-api-key": config.gemini_api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": exc.read().decode("utf-8")[:1000]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    parts = body.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            mime_type = inline.get("mimeType", "image/png")
            return {"ok": True, "mime_type": mime_type, "data": inline["data"], "raw": body}
    return {"ok": False, "error": "No image data returned", "raw": body}


def save_generated_asset(refresh_dir, refresh_id, variant_id, aspect_ratio, result):
    extension = "png"
    if result.get("mime_type") == "image/jpeg":
        extension = "jpg"
    filename = f"{refresh_id}_{variant_id}_{aspect_ratio.replace(':', 'x')}.{extension}"
    path = refresh_dir / filename
    with open(path, "wb") as handle:
        handle.write(base64.b64decode(result["data"]))
    created_at = now_iso()
    asset = {
        "path": str(path),
        "mime_type": result.get("mime_type"),
        "aspect_ratio": aspect_ratio,
        "created_at": created_at,
    }
    set_asset_storage(asset, {
        "kind": "temporary",
        "saved": False,
        "created_at": created_at,
        "status": "temporary",
        "cleanup": CREATIVE_IMAGE_STORAGE_POLICY,
    })
    return asset


def generate_creative_refresh(campaign, generate_images=False, product_guide="", ad_brief=""):
    config = load_config()
    plan = build_creative_plan(campaign, product_guide=product_guide, ad_brief=ad_brief)
    refresh_dir = OUTPUT_DIR / plan["id"]
    refresh_dir.mkdir(parents=True, exist_ok=True)
    if generate_images and config.creative_live:
        for variant in plan["variants"]:
            for prompt in variant["image_prompts"]:
                variant["assets"].append({
                    "aspect_ratio": prompt["aspect_ratio"],
                    "error": "Las imagenes finales ahora se crean con Codex/Image desde el chat o la accion codex_image_generate.",
                })
        plan["status"] = "needs_codex_image"
    else:
        plan["status"] = "dry_run"
    manifest_path = refresh_dir / "manifest.json"
    write_json(manifest_path, plan)
    update_index(plan, manifest_path)
    return plan, manifest_path


def update_index(plan, manifest_path):
    index = read_json(INDEX_FILE, [])
    summary = {
        "id": plan["id"],
        "created_at": plan["created_at"],
        "status": plan["status"],
        "campaign": plan["campaign"],
        "variant_count": len(plan.get("variants", [])),
        "manifest_path": str(manifest_path),
    }
    index = [item for item in index if item.get("id") != plan["id"]]
    index.insert(0, summary)
    write_json(INDEX_FILE, index[:100])


def recent_creative_refreshes(limit=10):
    return read_json(INDEX_FILE, [])[:limit]
