#!/usr/bin/env python3
"""Deterministic exhaustive campaign-canary manifests.

This module owns no credentials and performs no I/O.  It deliberately keeps
the case generation separate from the live runner so every requested variant
can be reviewed and regression-tested before anything is sent to Meta.
"""

from __future__ import annotations

import copy
from collections import Counter


LIVE_FAMILY_COUNTS = {
    "sales_web": 12,
    "traffic": 8,
    "awareness": 6,
    "engagement_video": 8,
    "messaging": 10,
    "lead_form": 8,
    "existing_post": 4,
    "app_catalog": 4,
}

KEEPER_FAMILIES = {
    "sales_web",
    "traffic",
    "awareness",
    "post_engagement",
    "video_views",
    "whatsapp",
    "messenger",
    "instagram_direct",
    "lead_form",
    "existing_post",
    "app_promotion",
    "catalog_sales",
}

COUNTRY_ROTATION = [
    ["CO"], ["MX"], ["AR"], ["PE", "CL"], ["CO", "MX"], ["US"],
]
LOCATION_ROTATION = [
    [], ["Pereira, Risaralda, Colombia"], ["Dosquebradas, Risaralda, Colombia"],
    ["Medellín, Antioquia, Colombia"], ["Bogotá, Colombia"],
]
INTEREST_ROTATION = [
    [], ["Música"], ["Comercio electrónico"], ["Belleza"],
    ["Marketing digital"], ["Emprendimiento"],
]
AGE_ROTATION = [(18, 24), (25, 44), (30, 58), (55, 65), (18, 65)]
GENDER_ROTATION = [[], [2], [1], []]
PLACEMENT_ROTATION = [
    "automatic",
    ["FACEBOOK_FEED", "INSTAGRAM_FEED"],
    ["FACEBOOK_STORIES", "INSTAGRAM_STORIES", "INSTAGRAM_REELS"],
    ["FACEBOOK_FEED", "FACEBOOK_REELS", "INSTAGRAM_FEED", "INSTAGRAM_PROFILE_FEED"],
    ["FACEBOOK_FEED", "FACEBOOK_STORIES", "INSTAGRAM_FEED", "INSTAGRAM_STORIES"],
]
COPY_ROTATION = [
    ("Una solución clara para avanzar hoy.", "Conoce la propuesta"),
    ("¿Sigues perdiendo tiempo en tareas que podrías simplificar? Descubre una alternativa práctica.", "Hazlo más simple"),
    ("✨ Una experiencia diferente, pensada para personas que valoran claridad, rapidez y buenos resultados.", "Empieza hoy"),
    ("Oferta canary: USD 19. Información transparente, sin promesas exageradas y con todos los detalles antes de decidir.", "Ver oferta de USD 19"),
    ("Primera línea para detener el scroll.\n\nSegunda línea con el beneficio principal.\n\nTercera línea con una invitación concreta.", "Descubre cómo funciona"),
    ("Resultados reales comienzan con una decisión bien informada. Revisa la información y elige con calma.", "Más información"),
]


def _copy(index: int, family: str) -> dict:
    text, headline = COPY_ROTATION[index % len(COPY_ROTATION)]
    return {
        "primary_text": f"{text} [{family} {index + 1}]",
        "headline": f"{headline} {index + 1}",
        "description": "Prueba técnica pausada de Admira IA.",
    }


def _targeting(index: int, *, force_broad: bool = False) -> dict:
    age_min, age_max = AGE_ROTATION[index % len(AGE_ROTATION)]
    mode = ("broad", "advantage_plus", "manual")[index % 3]
    if force_broad:
        mode = "broad"
    if mode in {"advantage_plus", "broad"}:
        # Meta treats both explicit Advantage+ and an open/broad audience as
        # Advantage+ delivery. Its hard minimum-age control cannot be greater
        # than 25 and its hard maximum must remain 65. Strict older bands are
        # still exercised by manual cases instead of being sent as an invalid
        # Advantage+ combination.
        age_min = min(age_min, 25)
        age_max = 65
    location_queries = LOCATION_ROTATION[index % len(LOCATION_ROTATION)]
    interest_queries = [] if mode == "broad" else INTEREST_ROTATION[(index + 1) % len(INTEREST_ROTATION)]
    result = {
        "locations": copy.deepcopy(COUNTRY_ROTATION[index % len(COUNTRY_ROTATION)]),
        "age_range": {"min": age_min, "max": age_max},
        "genders": copy.deepcopy(GENDER_ROTATION[index % len(GENDER_ROTATION)]),
        "placements": copy.deepcopy(PLACEMENT_ROTATION[index % len(PLACEMENT_ROTATION)]),
        "targeting_mode": mode,
        "canary_location_queries": copy.deepcopy(location_queries),
        "canary_interest_queries": copy.deepcopy(interest_queries),
    }
    if mode in {"advantage_plus", "broad"}:
        result["targeting_automation"] = {"advantage_audience": 1}
    elif mode == "manual":
        result["targeting_automation"] = {"advantage_audience": 0}
    return result


def _media(index: int, kind: str) -> dict:
    mapping = {
        "image": ["{{IMAGE_1_1}}", "{{IMAGE_4_5}}", "{{IMAGE_9_16}}"],
        "video": ["{{VIDEO_1_1}}", "{{VIDEO_4_5}}", "{{VIDEO_9_16}}", "{{VIDEO_16_9}}"],
    }
    key = mapping[kind][index % len(mapping[kind])]
    if kind == "image":
        return {"creative_image_path": key}
    # Meta's inline video_data requires a thumbnail. Reuse a deliberately
    # generated canary image with a matching orientation instead of relying on
    # an implicit frame extraction that differs across Graph versions.
    thumbnails = ["{{IMAGE_1_1}}", "{{IMAGE_4_5}}", "{{IMAGE_9_16}}", "{{IMAGE_1_1}}"]
    return {
        "video_path": key,
        "creative_image_path": thumbnails[index % len(thumbnails)],
    }


def _ad(index: int, family: str, *, media="image", destination="website") -> dict:
    copy_fields = _copy(index, family)
    ad = {
        "name": f"CANARY {family} — variante {index + 1}",
        **copy_fields,
        **_media(index, media),
        "cta": "LEARN_MORE",
        "landing_url": f"https://uboost.lat/?utm_source=admira_canary&utm_campaign={family}&utm_content={index + 1}",
    }
    if destination == "sales":
        ad["cta"] = "SHOP_NOW"
    elif destination == "lead_form":
        ad["cta"] = "SIGN_UP"
        ad.pop("landing_url", None)
        ad["lead_gen_form_id"] = "{{LEAD_FORM_ID}}"
    elif destination in {"WHATSAPP", "MESSENGER", "INSTAGRAM_DIRECT"}:
        ad.pop("landing_url", None)
        ad["message_destination"] = destination
        if destination == "WHATSAPP":
            ad["prefilled_message"] = f"Hola, vi la variante {index + 1} y quiero información."
        else:
            ad["welcome_message"] = f"Hola. Cuéntanos qué necesitas sobre la variante {index + 1}."
    elif destination == "awareness":
        ad.pop("landing_url", None)
        ad["cta"] = ""
    return ad


def _topology(index: int, family: str, destination: str, media: str) -> list[dict]:
    # Most live probes are intentionally compact.  Five cases of each complex
    # shape still exercise 1x4, 2x2, and three-ad-set execution while keeping
    # the full 60-case run close to the planned 90-110 real ads.
    shape = index % 12
    if shape == 1:
        counts = [4]
    elif shape == 2:
        counts = [2, 2]
    elif shape == 3:
        counts = [1, 1, 1]
    else:
        counts = [1]
    adsets = []
    ad_index = index * 4
    for set_index, ad_count in enumerate(counts):
        ads = [_ad(ad_index + offset, family, media=media if offset % 2 == 0 else "image", destination=destination) for offset in range(ad_count)]
        targeting = _targeting(index + set_index)
        adset = {
            "name": f"CANARY {family} — conjunto {set_index + 1}",
            "budget": 10 + set_index * 2,
            "targeting": targeting,
            "placements": targeting["placements"],
            "ads": ads,
        }
        if destination in {"WHATSAPP", "MESSENGER", "INSTAGRAM_DIRECT"}:
            adset["message_destination"] = destination
        if destination == "lead_form":
            adset["lead_gen_form_id"] = "{{LEAD_FORM_ID}}"
            adset["destination_type"] = "ON_AD"
        adsets.append(adset)
    return adsets


def _case(index: int, family: str, ordinal: int) -> dict:
    budget_level = "campaign" if ordinal % 3 == 1 else "adset"
    media = "video" if ordinal % 3 == 2 else "image"
    objective = "sales"
    destination = "sales"
    subtype = family
    expected = "success"
    required_capability = ""

    if family == "traffic":
        objective, destination = "traffic", "website"
    elif family == "awareness":
        objective, destination = "awareness", "awareness"
    elif family == "engagement_video":
        if ordinal % 2:
            objective, destination, media, subtype = "video", "awareness", "video", "video_views"
        else:
            objective, destination, subtype = "engagement", "awareness", "post_engagement"
    elif family == "messaging":
        destinations = ["WHATSAPP"] * 6 + ["MESSENGER"] * 2 + ["INSTAGRAM_DIRECT"] * 2
        message_destination = destinations[ordinal % len(destinations)]
        objective, destination, subtype = "messages", message_destination, message_destination.lower()
        required_capability = message_destination.lower()
    elif family == "lead_form":
        objective, destination, subtype = "leads", "lead_form", "lead_form"
        required_capability = "lead_form"
    elif family == "existing_post":
        objective, destination, subtype = ("traffic" if ordinal % 2 else "engagement"), "website", "existing_post"
        media = "image"
        required_capability = "existing_post"
    elif family == "app_catalog":
        if ordinal % 2:
            objective, destination, subtype = "sales", "sales", "catalog_sales"
            required_capability = "catalog"
        else:
            objective, destination, subtype = "app_promotion", "website", "app_promotion"
            required_capability = "app"
        expected = "success_or_capability_block"

    adsets = _topology(index, subtype, destination, media)
    if family == "existing_post":
        for adset in adsets:
            for ad in adset["ads"]:
                ad.pop("creative_image_path", None)
                ad.pop("video_path", None)
                ad["object_story_id"] = "{{VISIBLE_POST_ID}}" if ordinal % 2 == 0 else "{{AD_STORY_ID}}"
    payload = {
        "canary_id": f"case-{index + 1:03d}",
        "family": family,
        "subtype": subtype,
        "name": f"CANARY-{{{{RUN_ID}}}}-{index + 1:03d}-{subtype}",
        "objective": objective,
        "daily_budget": 20,
        "budget_level": budget_level,
        "campaign_daily_budget": 20 if budget_level == "campaign" else 0,
        "budget_currency": "",
        "final_status": "PAUSED",
        "active_spend_confirmed": False,
        "ad_sets": adsets,
        "canary_expected": expected,
        "canary_required_capability": required_capability,
        "canary_keep": False,
        "canary_dimensions": {
            "budget_level": budget_level,
            "media": media,
            "topology": [len(adset["ads"]) for adset in adsets],
            "copy_variant": ordinal % len(COPY_ROTATION),
        },
    }
    if family == "sales_web":
        payload["optimization_event"] = "Purchase"
        payload["promoted_object"] = {"pixel_id": "{{PIXEL_ID}}", "custom_event_type": "PURCHASE"}
    if family == "app_catalog":
        if subtype == "app_promotion":
            payload.update({"application_id": "{{APPLICATION_ID}}", "object_store_url": "{{OBJECT_STORE_URL}}"})
        else:
            payload.update({"catalog_id": "{{CATALOG_ID}}", "product_set_id": "{{PRODUCT_SET_ID}}"})
    return payload


def live_cases() -> list[dict]:
    result = []
    index = 0
    for family, count in LIVE_FAMILY_COUNTS.items():
        for ordinal in range(count):
            result.append(_case(index, family, ordinal))
            index += 1
    seen = set()
    for case in result:
        subtype = case["subtype"]
        if subtype not in KEEPER_FAMILIES or subtype in seen:
            continue
        # The visible post is intentionally deleted after the run. Preserve
        # the existing-post keeper only when it reuses an ad-originated story
        # that will remain available for visual inspection.
        if subtype == "existing_post":
            selected_story = next(
                (ad.get("object_story_id") for adset in case["ad_sets"] for ad in adset["ads"]),
                "",
            )
            if selected_story != "{{AD_STORY_ID}}":
                continue
        case["canary_keep"] = True
        seen.add(subtype)
    assert len(result) == 60
    return result


def contract_cases() -> list[dict]:
    """Return 128 deterministic payloads with extra dimension rotations."""
    base = live_cases()
    result = []
    for index in range(128):
        payload = copy.deepcopy(base[index % len(base)])
        payload["canary_id"] = f"contract-{index + 1:03d}"
        payload["name"] = f"CONTRACT-{index + 1:03d}-{payload['subtype']}"
        for set_index, adset in enumerate(payload["ad_sets"]):
            targeting = adset["targeting"]
            targeting["locations"] = copy.deepcopy(COUNTRY_ROTATION[(index + set_index) % len(COUNTRY_ROTATION)])
            age_min, age_max = AGE_ROTATION[(index + set_index) % len(AGE_ROTATION)]
            if targeting.get("targeting_mode") in {"advantage_plus", "broad"}:
                age_min = min(age_min, 25)
                age_max = 65
            targeting["age_range"] = {"min": age_min, "max": age_max}
            targeting["genders"] = copy.deepcopy(GENDER_ROTATION[(index + set_index) % len(GENDER_ROTATION)])
            targeting["placements"] = copy.deepcopy(PLACEMENT_ROTATION[(index + set_index) % len(PLACEMENT_ROTATION)])
        result.append(payload)
    return result


def natural_language_briefs() -> list[dict]:
    cases = contract_cases()
    briefs = []
    for index, payload in enumerate(cases[:30]):
        first = payload["ad_sets"][0]
        first_ad = first["ads"][0]
        targeting = first["targeting"]
        # This extraction field describes a *messaging* destination only.
        # A web, lead-form, app, awareness, or existing-post campaign must
        # serialize it as empty rather than inventing WEBSITE/ON_AD/APP.
        destination = first.get("message_destination") or ""
        placements = targeting.get("placements")
        genders = targeting.get("genders") or []
        gender_text = "solo mujeres" if genders == [2] else "solo hombres" if genders == [1] else "todos los géneros"
        message_text = first_ad.get("prefilled_message") or first_ad.get("welcome_message") or ""
        landing_url = first_ad.get("landing_url") or ""
        total_ads = sum(len(adset.get("ads") or []) for adset in payload["ad_sets"])
        media_kind = "video" if first_ad.get("video_path") else "existing_post" if first_ad.get("object_story_id") else "image"
        brief = (
            f"Crea en pausa una campaña llamada {payload['name']}. Objetivo {payload['objective']}; "
            f"presupuesto {payload['daily_budget']} a nivel {payload['budget_level']}. "
            f"Usa {gender_text}, edades {targeting['age_range']['min']} a {targeting['age_range']['max']}, "
            f"países {', '.join(targeting.get('locations') or [])}, modo {targeting.get('targeting_mode')}, "
            f"y placements {placements}. La estructura contiene {len(payload['ad_sets'])} conjuntos y {total_ads} anuncios. "
            f"El primer anuncio se llama {first_ad['name']}; "
            f"texto exacto: {first_ad['primary_text']} Titular exacto: {first_ad['headline']}. "
            f"CTA {first_ad.get('cta') or ''}; destino {destination}; enlace exacto {landing_url or 'ninguno'}; "
            f"mensaje inicial exacto {message_text or 'ninguno'}; medio {media_kind}. No actives ni gastes."
        )
        briefs.append({
            "brief_id": f"brief-{index + 1:02d}",
            "text": brief,
            "expected": {
                "name": payload["name"],
                "objective": payload["objective"],
                "daily_budget": payload["daily_budget"],
                "budget_level": payload["budget_level"],
                "age_min": targeting["age_range"]["min"],
                "age_max": targeting["age_range"]["max"],
                "genders": genders,
                "countries": targeting.get("locations") or [],
                "placements": placements,
                "adset_count": len(payload["ad_sets"]),
                "ad_count": total_ads,
                "primary_text": first_ad["primary_text"],
                "headline": first_ad["headline"],
                "cta": first_ad.get("cta") or "",
                "message_destination": destination,
                "landing_url": landing_url,
                "initial_message": message_text,
                "media_kind": media_kind,
                "final_status": "PAUSED",
            },
        })
    return briefs


def manifest_summary() -> dict:
    cases = live_cases()
    return {
        "live_cases": len(cases),
        "contract_cases": len(contract_cases()),
        "briefs": len(natural_language_briefs()),
        "family_counts": dict(Counter(item["family"] for item in cases)),
        "estimated_ads": sum(len(adset["ads"]) for item in cases for adset in item["ad_sets"]),
    }
