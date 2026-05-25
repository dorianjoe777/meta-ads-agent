"""Audience strategy builder for beginner-friendly Meta Ads targeting guidance."""
from datetime import datetime, timezone


SENSITIVE_TERMS = {
    "health",
    "medical",
    "debt",
    "credit",
    "loan",
    "politics",
    "religion",
    "race",
    "ethnicity",
    "salud",
    "medicina",
    "deuda",
    "credito",
    "crédito",
    "prestamo",
    "préstamo",
    "politica",
    "política",
    "religion",
    "religión",
}


def split_terms(value):
    return [item.strip() for item in str(value or "").replace("\n", ",").split(",") if item.strip()]


def has_sensitive_terms(payload):
    text = " ".join(str(payload.get(key, "")) for key in ["product", "buyer", "interests", "notes"]).lower()
    return sorted(term for term in SENSITIVE_TERMS if term in text)


def readiness(payload):
    data_sources = split_terms(payload.get("data_sources"))
    has_customer_list = any("email" in item.lower() or "cliente" in item.lower() or "customer" in item.lower() for item in data_sources)
    has_pixel = any("pixel" in item.lower() or "compra" in item.lower() or "purchase" in item.lower() or "lead" in item.lower() for item in data_sources)
    has_engagement = any("engagement" in item.lower() or "instagram" in item.lower() or "facebook" in item.lower() or "ig" in item.lower() for item in data_sources)
    consent = str(payload.get("consent", "")).lower() in {"yes", "si", "sí", "true", "on", "1"}
    seed_ready = has_pixel or has_engagement or (has_customer_list and consent)
    if has_customer_list and not consent:
        reason = "Customer list detected, but consent is not confirmed."
    elif seed_ready:
        reason = "A valid seed source appears available."
    else:
        reason = "No strong seed source yet. Start broad or with interests while collecting pixel/customer data."
    return {
        "ready": seed_ready and not (has_customer_list and not consent),
        "has_customer_list": has_customer_list,
        "has_pixel_or_events": has_pixel,
        "has_engagement": has_engagement,
        "consent_confirmed": consent,
        "reason": reason,
    }


def build_audience_strategy(payload, language="es"):
    locations = split_terms(payload.get("locations")) or ["Latin America" if language == "en" else "Latinoamérica"]
    interests = split_terms(payload.get("interests"))
    data_sources = split_terms(payload.get("data_sources"))
    sensitive = has_sensitive_terms(payload)
    lookalike = readiness(payload)
    objective = payload.get("objective") or ("Purchases" if language == "en" else "Compras")
    product = payload.get("product") or ("the offer" if language == "en" else "la oferta")
    buyer = payload.get("buyer") or ("current best buyers" if language == "en" else "los mejores compradores actuales")

    broad_name = "Broad / Advantage+ prospecting" if language == "en" else "Prospección amplia / Advantage+"
    interest_name = "Interest testing" if language == "en" else "Prueba por intereses"
    retargeting_name = "Warm retargeting" if language == "en" else "Retargeting tibio"
    lookalike_name = "Lookalike from seed audience" if language == "en" else "Lookalike desde audiencia semilla"

    strategies = [
        {
            "name": broad_name,
            "priority": 1,
            "use_when": "Default starting point when the offer has enough budget to let Meta optimize." if language == "en" else "Punto de partida recomendado cuando la oferta tiene presupuesto para que Meta aprenda.",
            "targeting": {
                "locations": locations,
                "age": payload.get("age") or "25-54",
                "interests": [],
                "expansion": "Advantage+ audience / broad",
            },
            "why": f"Meta usually finds buyers faster when it is not boxed in too early. Use creative and conversion data to guide it for {product}.",
        },
        {
            "name": interest_name,
            "priority": 2,
            "use_when": "Useful for small budgets, niche offers, or early validation." if language == "en" else "Útil con presupuestos pequeños, nichos claros o validación temprana.",
            "targeting": {
                "locations": locations,
                "age": payload.get("age") or "25-54",
                "interests": interests[:8],
                "expansion": "Advantage detailed targeting when allowed",
            },
            "why": f"Start with interests that describe what {buyer} already follows, buys, or compares.",
        },
        {
            "name": retargeting_name,
            "priority": 3,
            "use_when": "Use when there is website traffic, IG/Facebook engagement, leads, or video viewers." if language == "en" else "Úsalo cuando haya visitas web, interacción en IG/Facebook, leads o reproducciones de video.",
            "targeting": {
                "sources": data_sources or ["Pixel / IG engagement / leads"],
                "window": "7, 14, and 30 day tests",
                "exclusions": "Recent buyers when available",
            },
            "why": "Warm audiences usually convert better, but can fatigue quickly if the audience is small." if language == "en" else "Las audiencias tibias suelen convertir mejor, pero se fatigan rápido si son pequeñas.",
        },
    ]

    if lookalike["ready"]:
        strategies.append(
            {
                "name": lookalike_name,
                "priority": 4,
                "use_when": "Use after the seed source is clean and large enough." if language == "en" else "Úsalo cuando la audiencia semilla esté limpia y tenga suficiente tamaño.",
                "targeting": {
                    "seed": "Pixel/customers/engagement source",
                    "sizes": "1%, 2%, 5% tests",
                    "locations": locations,
                },
                "why": "Lookalikes can scale what already works, but the seed quality matters more than the label.",
            }
        )

    blockers = []
    if sensitive:
        blockers.append("Sensitive targeting terms detected. Keep targeting broad and avoid personal-attribute wording." if language == "en" else "Detecté términos sensibles. Mantén segmentación amplia y evita textos que parezcan atributos personales.")
    if lookalike["has_customer_list"] and not lookalike["consent_confirmed"]:
        blockers.append("Confirm consent before uploading customer emails or phones." if language == "en" else "Confirma consentimiento antes de subir emails o teléfonos de clientes.")

    next_steps = [
        "Launch broad + one interest test first." if language == "en" else "Lanza primero amplia + una prueba de intereses.",
        "Keep retargeting separate if warm traffic exists." if language == "en" else "Separa retargeting si ya existe tráfico tibio.",
        "Build lookalike only after seed data and consent are clear." if language == "en" else "Crea lookalike solo cuando la data semilla y el consentimiento estén claros.",
    ]

    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "product": product,
        "objective": objective,
        "buyer": buyer,
        "locations": locations,
        "lookalike_readiness": lookalike,
        "sensitive_terms": sensitive,
        "blockers": blockers,
        "strategies": strategies,
        "next_steps": next_steps,
    }
