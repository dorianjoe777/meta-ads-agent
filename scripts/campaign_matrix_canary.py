#!/usr/bin/env python3
"""Broad, no-write campaign contract canary.

This exercises the exact normalization and Graph-boundary mapping used by the
agent without creating anything in Meta. A real canary host can run this file
inside its installed container after every release.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path


ROOT = Path(os.environ.get("ADMIRA_APP_ROOT") or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(ROOT / "src"))


def load_dashboard():
    spec = importlib.util.spec_from_file_location(
        "monitoring_dashboard_campaign_matrix",
        ROOT / "dashboard" / "monitoring-dashboard.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def creative(name, text, headline, *, image="/tmp/canary.png", link="https://example.com/a", prefilled=""):
    item = {
        "name": name,
        "copy": {"primary_text": text, "headline": headline, "cta": "LEARN_MORE"},
        "creative_image_path": image,
        "landing_url": link,
    }
    if prefilled:
        item["prefilled_message"] = prefilled
    return item


def set_payload(name, targeting, ads, *, budget=20, **extra):
    return {"name": name, "budget": budget, "targeting": targeting, "ads": ads, **extra}


def base(name, objective, targeting, ads, *, budget=20, budget_level="adset", **extra):
    payload = {
        "name": name,
        "objective": objective,
        "daily_budget": budget,
        "budget_level": budget_level,
        "final_status": "PAUSED",
        "active_spend_confirmed": False,
        "ad_sets": [set_payload(f"{name} - Core", targeting, ads, budget=budget, **extra.pop("ad_set", {}))],
        **extra,
    }
    if budget_level == "campaign":
        payload["campaign_daily_budget"] = budget
    return payload


def interest(name, ident):
    return {"id": str(ident), "name": name}


def cases():
    city_pereira = {"key": "476114", "name": "Pereira", "type": "city", "country_code": "CO"}
    city_dos = {"key": "462207", "name": "Dosquebradas", "type": "city", "country_code": "CO"}
    # IDs resolved from Meta's live ``/search?type=adinterest`` catalog on the
    # 2026-08-07 canary.  The matrix deliberately uses real IDs rather than
    # placeholders so stale/invalid-interest regressions fail locally.
    ecommerce = interest("Comercio electrónico (comercio minorista)", "6003221485467")
    music = interest("Música (entretenimiento y medios de comunicación)", "6003020834693")
    beauty = interest("ULTA Beauty (minorista)", "6003143331761")

    result = []
    result.append(base("sales-broad-co", "sales", {"locations": ["CO"], "age_range": {"min": 18, "max": 65}}, [creative("Broad", "Compra ahora.", "Oferta", link="https://example.com/sales")]))
    result.append(base("sales-advantage-mx", "PURCHASES", {"locations": ["MX"], "age_range": {"min": 25, "max": 44}, "targeting_mode": "advantage_plus", "meta_targeting": {"interests": [ecommerce]}}, [creative("MX", "Descubre la oferta.", "Compra online", link="https://example.com/mx")], budget=30, budget_level="campaign"))
    result.append(base("sales-strict-women-city", "ventas", {"meta_targeting": {"locations": [city_pereira, city_dos], "interests": [beauty]}, "age_range": {"min": 30, "max": 58}, "gender": "mujeres", "targeting_mode": "manual", "placements": "automatic"}, [creative("Glow", "Reserva tu valoración.", "Solo para mujeres", link="https://example.com/glow")]))
    result.append(base("sales-strict-men-age", "COMPRAS", {"locations": ["AR"], "age_range": {"min": 55, "max": 65}, "genders": [1], "targeting_mode": "strict", "meta_targeting": {"interests": [ecommerce]}}, [creative("Senior men", "Conoce la solución.", "Resultados claros", link="https://example.com/ar")]))
    result.append(base("sales-all-gender", "VENTA", {"locations": ["PE", "CL"], "age_range": {"min": 18, "max": 24}, "gender": "todos", "placements": "advantage+ placements"}, [creative("Young", "Empieza hoy.", "Nueva oportunidad", link="https://example.com/young")]))
    result.append(base("messages-whatsapp-broad", "messages", {"locations": ["CO"], "age_range": {"min": 18, "max": 65}}, [creative("WhatsApp", "Escríbenos para recibir información.", "Habla con nosotros", prefilled="Hola, quiero información", link="https://example.com/wa")], message_destination="WHATSAPP", whatsapp_phone_number_id="573000000000"))
    result.append(base("messages-whatsapp-advantage", "WHATSAPP", {"locations": ["CO"], "age_range": {"min": 25, "max": 45}, "targeting_mode": "advantage_plus", "meta_targeting": {"interests": [music]}}, [creative("Artist", "Habla con un asesor.", "Escríbenos", prefilled="Hola, quiero una asesoría", link="https://example.com/artist")], message_destination="WHATSAPP", whatsapp_phone_number_id="573000000000"))
    result.append(base("messages-messenger-city", "MESSAGES", {"meta_targeting": {"locations": [city_pereira]}, "age_range": {"min": 30, "max": 40}, "gender": "mujeres", "placements": {"automatic": False, "manual": ["FACEBOOK_FEED", "FACEBOOK_STORIES"]}}, [creative("Messenger", "Conversemos sobre tu caso.", "Te ayudamos", prefilled="Hola, quiero conocer más", link="https://example.com/messenger")], message_destination="MESSENGER"))
    result.append(base("messages-instagram", "interacción", {"locations": ["BR"], "age_range": {"min": 18, "max": 34}, "gender": "todos"}, [creative("Instagram", "Mira la propuesta.", "Escríbenos", prefilled="Hola, vi el anuncio", link="https://example.com/ig")], message_destination="INSTAGRAM_DIRECT"))
    result.append(base("leads-form", "formularios", {"locations": ["CO"], "age_range": {"min": 25, "max": 55}, "gender": "mujeres", "targeting_mode": "manual", "meta_targeting": {"interests": [beauty]}}, [creative("Lead", "Déjanos tus datos y te contactamos.", "Solicita información", link="https://example.com/privacy")], lead_gen_form_id="form_123"))
    result.append(base("traffic-city", "traffic", {"meta_targeting": {"locations": [city_dos]}, "age_range": {"min": 18, "max": 65}}, [creative("Traffic", "Conoce todos los detalles.", "Ver sitio", link="https://example.com/traffic")]))
    result.append(base("awareness-open", "awareness", {"locations": ["US"], "age_range": {"min": 18, "max": 65}, "placements": "automatic"}, [creative("Awareness", "Conoce nuestra marca.", "Descubre", link="https://example.com/about")]))
    result.append(base("video-placeholder", "video", {"locations": ["CO"], "age_range": {"min": 18, "max": 65}}, [
        {**creative("Video 1", "Mira la historia.", "Video 1", link="https://example.com/v1"), "video_path": "/tmp/video-1.mp4"},
        {**creative("Video 2", "Descubre el cambio.", "Video 2", link="https://example.com/v2"), "video_path": "/tmp/video-2.mp4"},
    ], manual_creative_completion=True, create_placeholder_ad=True, placeholder_ad_count=2))
    result.append({
        "name": "multi-adset-mixed",
        "objective": "sales",
        "daily_budget": 40,
        "budget_level": "campaign",
        "campaign_daily_budget": 40,
        "final_status": "PAUSED",
        "active_spend_confirmed": False,
        "ad_sets": [
            set_payload("Offer A", {"locations": ["CO"], "age_range": {"min": 18, "max": 30}, "gender": "mujeres", "targeting_mode": "advantage_plus", "meta_targeting": {"interests": [music]}}, [creative("A1", "Texto A1", "Oferta A1", link="https://example.com/a1"), creative("A2", "Texto A2", "Oferta A2", link="https://example.com/a2")], budget=20),
            set_payload("Offer B", {"meta_targeting": {"locations": [city_pereira, city_dos], "interests": [beauty]}, "age_range": {"min": 31, "max": 58}, "gender": "mujeres", "targeting_mode": "manual", "placements": "automatic"}, [creative("B1", "Texto B1", "Oferta B1", link="https://example.com/b1"), creative("B2", "Texto B2", "Oferta B2", link="https://example.com/b2")], budget=20),
        ],
    })
    result.append({
        "name": "nested-copy-and-parent-message",
        "objective": "messages",
        "daily_budget": 15,
        "final_status": "PAUSED",
        "active_spend_confirmed": False,
        "message_destination": "WHATSAPP",
        "whatsapp_phone_number_id": "573000000000",
        "ad_sets": [{
            "name": "Parent brief",
            "budget": 15,
            "primary_text": "Texto aprobado del conjunto.",
            "headline": "Titular aprobado",
            "prefilled_message": "Hola, quiero saber más",
            "targeting": {"locations": ["CO"], "age_range": {"min": 21, "max": 35}, "gender": "mujeres"},
            "ads": [{"name": "Child 1", "image_path": "/tmp/child-1.png"}, {"name": "Child 2", "image_path": "/tmp/child-2.png"}],
        }],
    })
    return result


def check_case(dashboard, daily_agent, payload):
    normalized = dashboard.normalize_campaign_stack_arguments(payload)
    assert normalized.get("name"), "missing campaign name"
    assert normalized.get("ad_sets"), "ad sets were lost"
    assert not dashboard._campaign_gender_contract_error(normalized), "explicit gender was lost or invalid"
    objective = daily_agent.campaign_objective_for_social(normalized.get("objective"), campaign=normalized)
    expected = {
        "OUTCOME_SALES": {"OUTCOME_SALES"},
        "OUTCOME_ENGAGEMENT": {"OUTCOME_ENGAGEMENT"},
        "OUTCOME_LEADS": {"OUTCOME_LEADS"},
        "OUTCOME_TRAFFIC": {"OUTCOME_TRAFFIC"},
        "OUTCOME_AWARENESS": {"OUTCOME_AWARENESS"},
    }
    assert objective in expected, f"unknown objective mapping: {objective}"
    for adset in normalized["ad_sets"]:
        targeting = adset.get("targeting") or {}
        spec = daily_agent.targeting_for_social(targeting)
        assert spec.get("geo_locations"), "location targeting was lost"
        assert "age_min" in spec and "age_max" in spec, "age targeting was lost"
        if targeting.get("genders") or targeting.get("gender"):
            assert spec.get("genders"), "gender targeting was lost"
        if targeting.get("targeting_mode") in {"advantage_plus", "manual", "strict"}:
            assert spec.get("targeting_automation") in ({"advantage_audience": 1}, {"advantage_audience": 0}), "Advantage flag missing"
        ads = adset.get("ads") or []
        assert ads, "ads were lost"
        for ad in ads:
            assert ad.get("primary_text"), f"copy lost for {ad.get('name')}"
            assert ad.get("headline"), f"headline lost for {ad.get('name')}"
            if adset.get("message_destination") or normalized.get("message_destination"):
                assert ad.get("prefilled_message") or ad.get("welcome_message"), f"message opener lost for {ad.get('name')}"
            if ad.get("landing_url"):
                assert ad["landing_url"].startswith("https://"), "invalid ad link"
        if adset.get("message_destination") or normalized.get("message_destination"):
            goal = daily_agent.adset_optimization_goal_for_campaign(adset, normalized, message_destination=adset.get("message_destination") or normalized.get("message_destination"))
            assert goal == "CONVERSATIONS", f"wrong message goal: {goal}"
        elif normalized.get("lead_gen_form_id") or normalized.get("objective") in {"leads", "formularios"}:
            assert daily_agent.adset_optimization_goal_for_campaign(adset, normalized) == "LEAD_GENERATION"
    return {"name": normalized["name"], "objective": objective, "ad_sets": len(normalized["ad_sets"]), "ads": sum(len(x.get("ads") or []) for x in normalized["ad_sets"])}


def check_interest_parenthetical_fallback(daily_agent):
    """Ensure a catalog ID survives Meta search labels with a category suffix."""
    calls = []

    def live_search(kind, query):
        calls.append((kind, query))
        if query == "Música":
            return {"ok": True, "items": [{"id": "6003020834693", "name": "Música (entretenimiento y medios de comunicación)"}]}
        return {"ok": True, "items": []}

    result = daily_agent.validate_meta_targeting_selection(
        interests=[{"id": "6003020834693", "name": "Música (entretenimiento y medios de comunicación)"}],
        locations=[{"key": "CO", "name": "Colombia", "type": "country", "country_code": "CO"}],
        live_search=live_search,
        verify_locations=False,
    )
    assert result.get("ok"), f"parenthetical Meta label fallback failed: {result}"
    assert calls == [("interest", "Música (entretenimiento y medios de comunicación)"), ("interest", "Música")], calls


def main():
    dashboard = load_dashboard()
    import daily_agent

    check_interest_parenthetical_fallback(daily_agent)
    summaries = []
    for index, payload in enumerate(cases(), 1):
        try:
            summaries.append(check_case(dashboard, daily_agent, payload))
        except Exception as exc:
            raise SystemExit(f"CASE {index} FAILED ({payload.get('name')}): {exc}") from exc
    print(json.dumps({"ok": True, "interest_parenthetical_fallback": True, "cases": len(summaries), "ads": sum(x["ads"] for x in summaries), "summaries": summaries}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
