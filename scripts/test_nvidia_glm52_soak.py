#!/usr/bin/env python3
"""Run a resumable 40-turn GLM-5.2/NVIDIA hosted-endpoint soak test.

This is a diagnostics-only test. Meta tools are simulated and no external
business state is mutated. The NVIDIA API key must be supplied through the
NVIDIA_API_KEY environment variable and is never written to the result files.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL = "z-ai/glm-5.2"

SYSTEM_PROMPT = """Eres Admira IA, manager personal y estratega experto en Meta Ads para duenos de negocio.
Responde en espanol sencillo, ejecutivo y conciso. Antes de responder, identifica el objetivo inmediato,
lo ya hecho y el siguiente paso util. Se proactivo: recomienda con criterio en vez de comportarte como
formulario. No termines rutinariamente con 'si quieres'. Consulta Meta mediante herramientas cuando la
pregunta dependa del estado real; nunca inventes datos ni uses memoria como sustituto de datos live.
Puedes preparar objetos PAUSED sin aprobacion, pero activar gasto requiere confirmacion explicita.
Mantén separadas las ofertas. Datos persistentes de esta prueba:
- Negocio: Cafe Aurora, Medellin.
- Objetivo principal: reservas por WhatsApp.
- Presupuesto: USD 10 diarios.
- Oferta principal: brunch ejecutivo.
- Oferta secundaria: catering corporativo; no mezclarla sin permiso.
- Marca: verde salvia, crema y dorado; tono calido y premium.
- El negocio no quiere usar descuentos.
Cuando llames herramientas, usa argumentos JSON validos. No muestres rutas internas ni IDs tecnicos salvo
que sean necesarios. Las herramientas de esta prueba son simuladas: interpreta sus resultados como datos reales.
"""

TURNS = [
    "Hola. No se mucho de anuncios. Mira como va mi campana hoy y dime lo importante en palabras sencillas.",
    "Eso de costo por reserva no lo entiendo. Explicamelo sin tecnicismos.",
    "Entonces, con lo que viste, cual es el problema principal ahora mismo?",
    "Vuelve a revisar Meta antes de responder: quiero saber si algo cambio desde la primera lectura.",
    "No quiero estar entrando a Ads Manager. Dame una recomendacion concreta para hoy.",
    "Tengo solo 10 dolares diarios. Conviene subir presupuesto ya?",
    "Recuerda que no quiero descuentos. Dame dos formas de mejorar la oferta sin bajar el precio.",
    "Una idea debe sentirse premium y la otra cercana. No me hagas diez preguntas; avanza con lo que sabes.",
    "Guarda esa decision para que no me la preguntes otra vez.",
    "Antes de seguir, resume en pocas lineas que negocio manejo, ciudad, objetivo, presupuesto y restriccion de oferta.",
    "Ahora revisa otra vez la campana y compara con la lectura anterior.",
    "Cual de las dos ideas probarias primero y por que?",
    "Prepara la estructura de una prueba nueva, pero dejala pausada y sin gastar.",
    "Que nombres claros pondrias a la campana, conjunto y dos anuncios?",
    "No quiero nombres genericos. Que cada anuncio diga el angulo que prueba.",
    "Como sabremos si funciona sin obsesionarnos con clics?",
    "Programa revisiones razonables para esta prueba, sin cambiar cosas cada pocas horas.",
    "Que vas a revisar en la primera revision?",
    "Si llegan muchos mensajes pero pocos son clientes reales, que hacemos?",
    "Recapitula el plan activo y confirma si algo quedo activado o gastando.",
    "Hoy llegaron 8 mensajes: 3 interesados reales, 1 reserva y 4 confundidos. Registra la lectura estrategica.",
    "Con esa informacion, Meta aprende inmediatamente o necesita mas volumen?",
    "Que dato debo confirmar cada dia sin volver esto una tarea pesada?",
    "Dame el mensaje diario exacto que me enviarias para recoger esa informacion.",
    "Tambien quiero contenido organico. Antes de proponerlo, confirma la marca que recuerdas.",
    "Propone una semana de contenido para el brunch, sin mezclar catering.",
    "Tengo fotos reales del local. Como las usarias sin alterarlas?",
    "La foto debe conservarse pixel por pixel; solo puedes componer texto y diseno alrededor. Guarda esa regla.",
    "Crea el brief de la primera pieza del lunes, corto y accionable.",
    "Haz un control de continuidad: enumera oferta principal, oferta separada, colores, presupuesto y lo que esta pausado.",
    "Ahora quiero hablar del catering. No mezcles lo anterior: cual seria el primer paso comercial?",
    "Tengo un PDF con menus y precios. Que harias al recibirlo?",
    "Para catering, que evento de negocio importa mas que un clic?",
    "Con poco volumen, cual seria una senal intermedia sensata para optimizar?",
    "Revisa el estado live otra vez antes de aconsejar cualquier cambio en la campana activa.",
    "Dame una decision: mantener, pausar o cambiar; explica en tres puntos.",
    "Si manana hay una compra, que cambiaria y que no cambiaria todavia?",
    "Que alerta importante deberias enviarme sin esperar que yo pregunte?",
    "Resume lo aprendido hoy como memoria durable, sin inventar acciones.",
    "Cierre del dia: dime donde quedamos, el siguiente paso exacto y confirma que recuerdas los datos clave.",
]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_live_meta_campaigns",
            "description": "Consulta campanas y metricas live directamente en Meta Ads Manager.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_range": {"type": "string"},
                    "status": {"type": "string"},
                },
                "required": ["date_range"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_business_memory",
            "description": "Guarda una decision durable confirmada por el usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["category", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stage_paused_campaign",
            "description": "Crea una estructura de campana en PAUSED, sin gasto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_name": {"type": "string"},
                    "daily_budget_usd": {"type": "number"},
                    "status": {"type": "string", "enum": ["PAUSED"]},
                    "objective": {"type": "string"},
                },
                "required": ["campaign_name", "daily_budget_usd", "status", "objective"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_campaign_review",
            "description": "Programa una revision analitica sin autorizar gasto ni cambios.",
            "parameters": {
                "type": "object",
                "properties": {
                    "after_hours": {"type": "integer"},
                    "purpose": {"type": "string"},
                },
                "required": ["after_hours", "purpose"],
            },
        },
    },
]


def tool_result(name: str, args: dict[str, Any], turn: int) -> dict[str, Any]:
    if name == "get_live_meta_campaigns":
        spend = round(6.2 + turn * 0.31, 2)
        messages = 5 + turn // 5
        qualified = 2 + turn // 12
        return {
            "source": "meta_live_simulation",
            "as_of_turn": turn,
            "campaigns": [
                {
                    "name": "Cafe Aurora | WhatsApp | Brunch",
                    "status": "ACTIVE",
                    "daily_budget_usd": 10,
                    "spend_usd": spend,
                    "impressions": 740 + turn * 19,
                    "link_clicks": 39 + turn,
                    "messages": messages,
                    "qualified_leads": qualified,
                    "reservations": 1,
                }
            ],
        }
    if name == "save_business_memory":
        return {"ok": True, "saved": args, "durable": True}
    if name == "stage_paused_campaign":
        return {
            "ok": True,
            "executed": True,
            "campaign_name": args.get("campaign_name"),
            "status": "PAUSED",
            "spend_enabled": False,
            "children": {"adsets": 1, "ads": 2},
        }
    if name == "schedule_campaign_review":
        return {"ok": True, "scheduled": True, "after_hours": args.get("after_hours")}
    return {"ok": False, "error": "unknown_simulated_tool"}


class ProviderRateLimit(RuntimeError):
    def __init__(self, latency: float, retry_after: str | None, body: str) -> None:
        super().__init__(f"http_429: {body[:300]}")
        self.latency = latency
        self.retry_after = retry_after


def request_completion(api_key: str, messages: list[dict[str, Any]]) -> tuple[dict[str, Any], float, int]:
    payload = {
        "model": MODEL,
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": "auto",
        "temperature": 0.4,
        "top_p": 0.9,
        "max_tokens": 900,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    started = time.monotonic()
    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=180)
    except requests.RequestException as exc:
        raise RuntimeError(f"transport_error: {type(exc).__name__}: {exc}") from exc
    latency = time.monotonic() - started
    if response.status_code == 200:
        return response.json(), latency, response.status_code
    if response.status_code == 429:
        raise ProviderRateLimit(latency, response.headers.get("Retry-After"), response.text)
    raise RuntimeError(f"http_{response.status_code}: {response.text[:500]}")


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    fraction = index - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


def continuity_score(turn: int, text: str) -> dict[str, bool]:
    normalized = text.lower()
    checks = {
        "business": "cafe aurora" in normalized or "café aurora" in normalized,
        "city": "medell" in normalized,
        "objective": "whatsapp" in normalized or "reserva" in normalized,
        "budget": "10" in normalized,
        "no_discount": "descuento" in normalized,
    }
    if turn >= 30:
        checks.update(
            {
                "main_offer": "brunch" in normalized,
                "secondary_offer": "catering" in normalized,
                "brand": any(color in normalized for color in ("salvia", "crema", "dorado")),
            }
        )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", default="/tmp/glm52_40turn_soak_20260715.json")
    parser.add_argument("--progress", default="/tmp/glm52_40turn_soak_20260715.progress.json")
    parser.add_argument("--state", default="/tmp/glm52_40turn_soak_20260715.state.json")
    args = parser.parse_args()

    api_key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not api_key:
        print("NVIDIA_API_KEY is required", file=sys.stderr)
        return 2

    result_path = Path(args.result)
    progress_path = Path(args.progress)
    state_path = Path(args.state)
    if state_path.exists():
        saved_state = json.loads(state_path.read_text(encoding="utf-8"))
        messages = saved_state["messages"]
        turns = saved_state["turns"]
        latencies = saved_state["latencies"]
        status_counts = saved_state["status_counts"]
        prompt_tokens = saved_state["prompt_tokens"]
        completion_tokens = saved_state["completion_tokens"]
        provider_requests = saved_state["provider_requests"]
        invalid_tool_json = saved_state["invalid_tool_json"]
        started_at = saved_state["started_at"]
    else:
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        turns: list[dict[str, Any]] = []
        latencies: list[float] = []
        status_counts: dict[str, int] = {}
        prompt_tokens = 0
        completion_tokens = 0
        provider_requests = 0
        invalid_tool_json = 0
        started_at = datetime.now(timezone.utc).isoformat()

    for turn_number, user_text in enumerate(TURNS, 1):
        if turn_number <= len(turns):
            continue
        messages_before_turn = list(messages)
        messages.append({"role": "user", "content": user_text})
        turn_record: dict[str, Any] = {
            "turn": turn_number,
            "user": user_text,
            "tool_calls": [],
            "latencies_seconds": [],
            "status": "started",
        }
        final_text = ""
        try:
            for _round in range(3):
                data, latency, http_status = request_completion(api_key, messages)
                provider_requests += 1
                latencies.append(latency)
                turn_record["latencies_seconds"].append(round(latency, 3))
                status_counts[str(http_status)] = status_counts.get(str(http_status), 0) + 1
                usage = data.get("usage") or {}
                prompt_tokens += int(usage.get("prompt_tokens") or 0)
                completion_tokens += int(usage.get("completion_tokens") or 0)
                choice = (data.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                assistant_message: dict[str, Any] = {"role": "assistant"}
                if message.get("content") is not None:
                    assistant_message["content"] = message.get("content")
                tool_calls = message.get("tool_calls") or []
                if tool_calls:
                    assistant_message["tool_calls"] = tool_calls
                messages.append(assistant_message)
                if not tool_calls:
                    final_text = str(message.get("content") or "")
                    break
                for call in tool_calls:
                    function = call.get("function") or {}
                    name = str(function.get("name") or "")
                    raw_args = function.get("arguments") or "{}"
                    try:
                        parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                        valid_json = True
                    except (TypeError, ValueError):
                        parsed_args = {}
                        valid_json = False
                        invalid_tool_json += 1
                    simulated = tool_result(name, parsed_args, turn_number)
                    turn_record["tool_calls"].append(
                        {"name": name, "arguments": parsed_args, "valid_json": valid_json, "result": simulated}
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id"),
                            "name": name,
                            "content": json.dumps(simulated, ensure_ascii=False),
                        }
                    )
            if not final_text:
                final_text = "[no_final_text_after_tool_rounds]"
            turn_record["assistant"] = final_text
            turn_record["status"] = "ok"
            if turn_number in (10, 20, 30, 40):
                turn_record["continuity_checks"] = continuity_score(turn_number, final_text)
        except ProviderRateLimit as exc:
            provider_requests += 1
            latencies.append(exc.latency)
            status_counts["429"] = status_counts.get("429", 0) + 1
            messages = messages_before_turn  # retry this user turn cleanly on the next scheduled run
            progress = {
                "model": MODEL,
                "started_at": started_at,
                "status": "rate_limited",
                "last_completed_turn": len(turns),
                "pending_turn": turn_number,
                "total_turns": len(TURNS),
                "ok_turns": sum(1 for item in turns if item["status"] == "ok"),
                "error_turns": sum(1 for item in turns if item["status"] == "error"),
                "provider_requests": provider_requests,
                "http_status_counts": status_counts,
                "retry_after": exc.retry_after,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            checkpoint = {
                "messages": messages,
                "turns": turns,
                "latencies": latencies,
                "status_counts": status_counts,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "provider_requests": provider_requests,
                "invalid_tool_json": invalid_tool_json,
                "started_at": started_at,
            }
            state_path.write_text(json.dumps(checkpoint, ensure_ascii=False), encoding="utf-8")
            progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(progress, ensure_ascii=False), flush=True)
            return 75
        except Exception as exc:  # diagnostics must preserve partial results
            turn_record["status"] = "error"
            turn_record["error"] = f"{type(exc).__name__}: {exc}"
            status_counts["errors"] = status_counts.get("errors", 0) + 1
            messages.append(
                {
                    "role": "assistant",
                    "content": "Tuve un error temporal del proveedor. Conservo el contexto y continuo con el siguiente punto.",
                }
            )
        turns.append(turn_record)
        checkpoint = {
            "messages": messages,
            "turns": turns,
            "latencies": latencies,
            "status_counts": status_counts,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "provider_requests": provider_requests,
            "invalid_tool_json": invalid_tool_json,
            "started_at": started_at,
        }
        state_path.write_text(json.dumps(checkpoint, ensure_ascii=False), encoding="utf-8")
        progress = {
            "model": MODEL,
            "started_at": started_at,
            "last_completed_turn": turn_number,
            "total_turns": len(TURNS),
            "ok_turns": sum(1 for item in turns if item["status"] == "ok"),
            "error_turns": sum(1 for item in turns if item["status"] == "error"),
            "provider_requests": provider_requests,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(progress, ensure_ascii=False), flush=True)

    continuity_checks = [
        item.get("continuity_checks") for item in turns if item.get("continuity_checks") is not None
    ]
    all_continuity_values = [value for check in continuity_checks for value in check.values()]
    summary = {
        "model": MODEL,
        "endpoint": API_URL,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "turns_requested": len(TURNS),
        "turns_ok": sum(1 for item in turns if item["status"] == "ok"),
        "turns_error": sum(1 for item in turns if item["status"] == "error"),
        "provider_requests": provider_requests,
        "http_status_counts": status_counts,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "invalid_tool_json": invalid_tool_json,
        "tool_calls": sum(len(item.get("tool_calls") or []) for item in turns),
        "latency_seconds": {
            "median": round(statistics.median(latencies), 3) if latencies else None,
            "p95": round(percentile(latencies, 0.95), 3) if latencies else None,
            "max": round(max(latencies), 3) if latencies else None,
            "total": round(sum(latencies), 3),
        },
        "continuity_pass_rate": (
            round(sum(1 for value in all_continuity_values if value) / len(all_continuity_values), 4)
            if all_continuity_values
            else None
        ),
        "continuity_checks": continuity_checks,
    }
    result_path.write_text(
        json.dumps({"summary": summary, "turns": turns}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"final_summary": summary}, ensure_ascii=False), flush=True)
    return 0 if summary["turns_error"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
