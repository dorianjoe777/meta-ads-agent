#!/usr/bin/env python3
"""Telegram entry point for the Meta Ads manager agent.

Uses long polling so a local/VPS buyer does not need a public webhook URL.
Messages are answered by Hermes and product tools continue to run through the
same backend guardrails used by the dashboard.
"""
import argparse
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from agent_chat import chat as agent_chat
from local_store import read_json, utc_iso, write_json as write_json_file
from product_config import ROOT_DIR, env_bool, env_int, load_config
from security import redact_payload


DATA_DIR = ROOT_DIR / "dashboard" / "data"
HISTORY_FILE = DATA_DIR / "telegram_chat_history.json"
OFFSET_FILE = DATA_DIR / "telegram_offset.json"
APPROVAL_CONTEXT_FILE = DATA_DIR / "telegram_approval_context.json"
UPLOAD_DIR = ROOT_DIR / "output" / "telegram_uploads"
DASHBOARD_PATH = ROOT_DIR / "dashboard" / "monitoring-dashboard.py"
MAX_HISTORY_ITEMS = 20
MAX_MESSAGE_LENGTH = 4000
_DASHBOARD = None


def approve_pending(approval_id):
    from daily_agent import approve

    return approve(approval_id)


def reject_pending(approval_id, reason=""):
    from daily_agent import reject

    return reject(approval_id, reason)

def load_dashboard_module():
    global _DASHBOARD
    if _DASHBOARD is None:
        spec = importlib.util.spec_from_file_location("telegram_dashboard_runtime", DASHBOARD_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _DASHBOARD = module
    return _DASHBOARD


def telegram_settings(config):
    return {
        "enabled": env_bool("TELEGRAM_AGENT_ENABLED", False),
        "language": os.environ.get("TELEGRAM_LANGUAGE", "es").strip().lower() or "es",
        "poll_timeout": max(5, min(50, env_int("TELEGRAM_POLL_TIMEOUT", 25))),
        "bot_configured": bool(config.telegram_bot_token),
        "chat_id": str(config.telegram_chat_id or "").strip(),
    }


def bot_request(config, method, payload=None, timeout=40):
    if not config.telegram_bot_token:
        raise ValueError("Falta configurar el bot de Telegram.")
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/{method}"
    data = urllib.parse.urlencode(payload or {}).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("ok"):
        raise ValueError("Telegram no acepto la solicitud.")
    return body.get("result")


def message_text(text):
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", str(text or ""), flags=re.DOTALL)
    cleaned = re.sub(r"^#{1,4}\s*", "", cleaned, flags=re.MULTILINE)
    return cleaned.strip()


def send_message(config, chat_id, text):
    clean = message_text(text) or "No pude generar una respuesta."
    chunks = [clean[i : i + MAX_MESSAGE_LENGTH] for i in range(0, len(clean), MAX_MESSAGE_LENGTH)]
    results = []
    for chunk in chunks:
        results.append(bot_request(config, "sendMessage", {"chat_id": chat_id, "text": chunk}))
    return results


def send_message_with_keyboard(config, chat_id, text, keyboard):
    clean = message_text(text) or "Revisa esta decision."
    payload = {"chat_id": chat_id, "text": clean[:MAX_MESSAGE_LENGTH], "reply_markup": json.dumps({"inline_keyboard": keyboard})}
    return bot_request(config, "sendMessage", payload)


def is_allowed_chat(config, chat_id):
    allowed = str(config.telegram_chat_id or "").strip()
    return bool(allowed) and str(chat_id) == allowed


def load_history(chat_id):
    histories = read_json(HISTORY_FILE, {})
    items = histories.get(str(chat_id), []) if isinstance(histories, dict) else []
    return items[-MAX_HISTORY_ITEMS:]


def append_turn(chat_id, user_message, reply):
    histories = read_json(HISTORY_FILE, {})
    if not isinstance(histories, dict):
        histories = {}
    history = histories.get(str(chat_id), [])
    history.extend(
        [
            {"role": "user", "content": str(user_message)[:5000], "created_at": utc_iso()},
            {"role": "agent", "content": str(reply)[:5000], "created_at": utc_iso()},
        ]
    )
    histories[str(chat_id)] = history[-MAX_HISTORY_ITEMS:]
    write_json_file(HISTORY_FILE, histories, ensure_ascii=False)


def reset_history(chat_id):
    histories = read_json(HISTORY_FILE, {})
    if not isinstance(histories, dict):
        histories = {}
    histories[str(chat_id)] = []
    write_json_file(HISTORY_FILE, histories, ensure_ascii=False)


def reset_polling_state():
    for path in (OFFSET_FILE, APPROVAL_CONTEXT_FILE):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def help_message():
    return (
        "Soy tu manager IA de Meta Ads.\n\n"
        "Puedes escribirme como a una persona:\n"
        "- Que debo vigilar hoy?\n"
        "- Prepara una campana para mi producto.\n"
        "- Revisa presupuesto de la campana X.\n"
        "- Que falta para activar piloto automatico?\n\n"
        "Comandos:\n"
        "/nuevo - empezar una conversacion nueva\n"
        "/pendientes - ver decisiones esperando aprobacion\n"
        "/ayuda - ver esta guia\n\n"
        "Cuando te muestre una decision pendiente, puedes tocar Aprobar/No aprobar. "
        "Tambien puedes responder 'aprobar' a esa tarjeta si es una decision normal. "
        "Si puede quedar activa y gastar dinero, te pedire la frase exacta: Si, crear y dejar activo."
    )


def pending_message(pending):
    if not pending:
        return "No tienes aprobaciones pendientes ahora."
    lines = ["Decisiones pendientes:"]
    for item in pending[:8]:
        name = item.get("payload", {}).get("name") or item.get("payload", {}).get("campaign_name") or item.get("type", "Accion")
        lines.append(f"- {name} ({item.get('type', 'accion')})")
    lines.append("\nToca un boton debajo de cada decision, o responde 'aprobar' a una tarjeta concreta.")
    return "\n".join(lines)


def approval_title(item):
    payload = item.get("payload", {}) if isinstance(item, dict) else {}
    return payload.get("name") or payload.get("campaign_name") or payload.get("action") or item.get("type", "Decision")


def approval_body(item):
    payload = item.get("payload", {}) if isinstance(item, dict) else {}
    lines = [f"Decision pendiente: {approval_title(item)}", f"ID: {item.get('id', '')}", f"Tipo: {item.get('type', 'accion')}"]
    if payload.get("requested"):
        lines.append(f"Pedido: {payload.get('requested')}")
    if payload.get("connector"):
        lines.append(f"Conector: {payload.get('connector')}")
    if payload.get("recommended_budget") or payload.get("new_budget"):
        lines.append(f"Presupuesto: {payload.get('recommended_budget') or payload.get('new_budget')}")
    if payload.get("final_status") == "ACTIVE":
        lines.append("")
        lines.append("ATENCION: si apruebas, el anuncio puede quedar ACTIVO y gastar presupuesto real.")
        lines.append("Para aprobar por texto, responde exactamente: Si, crear y dejar activo")
    else:
        lines.append("")
        lines.append("Si apruebas, ejecutaré exactamente esta accion y guardaré el resultado.")
        lines.append("Puedes tocar Aprobar o responder: aprobar")
    return "\n".join(lines)


def approval_keyboard(item):
    approval_id = item.get("id", "")
    payload = item.get("payload", {}) if isinstance(item, dict) else {}
    if item.get("type") == "create_campaign" and payload.get("final_status") == "ACTIVE":
        return [
            [{"text": "Si, crear y dejar activo", "callback_data": f"approve_active:{approval_id}"}],
            [{"text": "No aprobar", "callback_data": f"reject:{approval_id}"}],
        ]
    return [[{"text": "Aprobar", "callback_data": f"approve:{approval_id}"}, {"text": "No aprobar", "callback_data": f"reject:{approval_id}"}]]


def send_approval_card(config, chat_id, item):
    remember_approval_context(chat_id, item)
    return send_message_with_keyboard(config, chat_id, approval_body(item), approval_keyboard(item))


def remember_approval_context(chat_id, item):
    context = read_json(APPROVAL_CONTEXT_FILE, {})
    if not isinstance(context, dict):
        context = {}
    context[str(chat_id)] = {"approval_id": item.get("id", ""), "updated_at": utc_iso()}
    write_json_file(APPROVAL_CONTEXT_FILE, context, ensure_ascii=False)


def last_approval_context(chat_id):
    context = read_json(APPROVAL_CONTEXT_FILE, {})
    if not isinstance(context, dict):
        return ""
    return str((context.get(str(chat_id)) or {}).get("approval_id") or "")


def extract_approval_id(text):
    match = re.search(r"\bapproval_[A-Za-z0-9_\-]+\b", str(text or ""))
    return match.group(0) if match else ""


def text_approval_decision(text):
    lowered = str(text or "").strip().lower()
    if re.search(r"\b(rechaza|rechazar|rechazalo|recházalo|no aprobar|no apruebo|reject|deny)\b", lowered):
        return "reject"
    if re.search(r"\b(aprueba|aprobar|aprobalo|apruébalo|approve)\b", lowered):
        return "approve"
    if lowered in {
        "si, crear y dejar activo",
        "sí, crear y dejar activo",
        "si crear y dejar activo",
        "sí crear y dejar activo",
        "yes, create and leave active",
        "yes create and leave active",
        "yes, create and keep active",
        "yes create and keep active",
        "yes, approve active",
        "yes approve active",
        "create and leave active",
    }:
        return "approve"
    return ""


def text_confirms_active(text):
    lowered = str(text or "").strip().lower()
    return lowered in {
        "si, crear y dejar activo",
        "sí, crear y dejar activo",
        "si crear y dejar activo",
        "sí crear y dejar activo",
        "aprobar activo",
        "yes, create and leave active",
        "yes create and leave active",
        "yes, create and keep active",
        "yes create and keep active",
        "yes, approve active",
        "yes approve active",
        "create and leave active",
    }


def approval_requires_active_confirmation(item):
    payload = item.get("payload", {}) if isinstance(item, dict) else {}
    return item.get("type") == "create_campaign" and str(payload.get("final_status") or "").upper() == "ACTIVE"


def resolve_pending_from_text(chat_id, text, pending, reply_approval_id=""):
    exact = reply_approval_id or extract_approval_id(text)
    if exact:
        for item in pending:
            if item.get("id") == exact:
                return item, "exact"
    if len(pending) == 1:
        return pending[0], "single"
    context_id = last_approval_context(chat_id)
    if context_id and re.search(r"\b(esta|esa|this|that)\b", str(text or "").lower()):
        for item in pending:
            if item.get("id") == context_id:
                return item, "context"
    return None, "ambiguous"


def handle_text_approval(config, chat_id, text, dashboard, send=True, reply_approval_id=""):
    decision = text_approval_decision(text)
    if not decision:
        return None
    pending = dashboard.dashboard_payload().get("pending", [])
    if not pending:
        reply = "No veo aprobaciones pendientes ahora mismo."
        if send:
            send_message(config, chat_id, reply)
        return reply
    item, reason = resolve_pending_from_text(chat_id, text, pending, reply_approval_id=reply_approval_id)
    if not item:
        reply = "Tienes varias decisiones pendientes. Responde a la tarjeta exacta con 'aprobar' o escribe /pendientes y usa el boton correcto."
        if send:
            send_message(config, chat_id, reply)
            send_pending_cards(config, chat_id, pending)
        return reply
    approval_id = item.get("id", "")
    if decision == "reject":
        rejected = reject_pending(approval_id, "Rejected from Telegram text")
        reply = f"Decision rechazada: {approval_title(item)}" if rejected else "No encontre esa aprobacion pendiente."
        if send:
            send_message(config, chat_id, reply)
        return reply
    if approval_requires_active_confirmation(item) and not text_confirms_active(text):
        reply = "Esta decision puede dejar anuncios activos y gastar dinero real. Para aprobar por texto, responde exactamente: Si, crear y dejar activo"
        if send:
            send_message(config, chat_id, reply)
            send_approval_card(config, chat_id, item)
        return reply
    result = approve_pending(approval_id)
    if result:
        executed = result[0].get("result", {})
        succeeded = result[0].get("status") == "approved" or (executed.get("ok") is True and not executed.get("blocked"))
        reply = f"Aprobacion ejecutada: {approval_title(item)}\nEstado: {'completada' if succeeded else 'bloqueada o fallida; sigue pendiente para reintentar'}"
    else:
        reply = "No encontre esa aprobacion pendiente."
    if send:
        send_message(config, chat_id, reply)
    return reply


def send_pending_cards(config, chat_id, pending):
    if not pending:
        send_message(config, chat_id, "No tienes aprobaciones pendientes ahora.")
        return []
    results = []
    for item in pending[:8]:
        results.append(send_approval_card(config, chat_id, item))
    return results


def agent_payload(message, chat_id, language, image_paths=None):
    dashboard = load_dashboard_module()
    state = dashboard.dashboard_payload()
    return {
        "message": message,
        "language": language,
        "history": load_history(chat_id),
        "image_paths": image_paths or [],
        "metrics": state.get("metrics", {}),
        "recommendations": state.get("recommendations", []),
        "fatigue": state.get("fatigue", []),
        "pending": state.get("pending", []),
        "audience_strategy": state.get("audience_strategy", {}),
        "brand_guides": state.get("brand_guides", {}),
        "business_profile": state.get("business_profile", {}),
        "channel": "telegram",
    }


def handle_text(config, chat_id, text, send=True, image_paths=None, reply_approval_id=""):
    settings = telegram_settings(config)
    stripped = str(text or "").strip()
    command = stripped.split()[0].lower() if stripped.startswith("/") else ""
    dashboard = load_dashboard_module()
    if command in {"/start", "/ayuda", "/help"}:
        reply = help_message()
    elif command in {"/nuevo", "/new"}:
        reset_history(chat_id)
        reply = "Listo. Empezamos una conversacion nueva, sin contexto anterior. Que quieres trabajar hoy?"
    elif command in {"/pendientes", "/pending"}:
        pending = dashboard.dashboard_payload().get("pending", [])
        reply = pending_message(pending)
        if send:
            send_message(config, chat_id, reply)
            send_pending_cards(config, chat_id, pending)
            return reply
    else:
        approval_reply = handle_text_approval(config, chat_id, stripped, dashboard, send=send, reply_approval_id=reply_approval_id)
        if approval_reply is not None:
            return approval_reply
        else:
            payload = agent_payload(stripped, chat_id, settings["language"], image_paths=image_paths)
            result = agent_chat(config, payload)
            tool_result = None
            if result.get("fallback") and config.agent_chat_provider == "hermes":
                reply = result.get("reply") or "Todavia falta conectar el cerebro del agente. Abre Configuracion > Conectar ChatGPT o modelo API. En VPS/DigitalOcean el dashboard te mostrara el login desde el navegador."
            elif result.get("fallback") and not config.agent_chat_api_key:
                reply = "Todavia falta conectar el motor del agente."
            else:
                tool_result = dashboard.execute_agent_tool(result.get("tool_request"), payload)
                reply = (tool_result or {}).get("reply") or result.get("reply") or "No pude responder en este momento."
            append_turn(chat_id, stripped, reply)
            dashboard.log_action("telegram_agent_message", {"chat_id": str(chat_id)[-4:], "tool": (tool_result or {}).get("type") if tool_result else "", "message_length": len(stripped)}, "completed")
    if send:
        send_message(config, chat_id, reply)
        result_payload = (tool_result or {}).get("result") if "tool_result" in locals() and tool_result else None
        approval_id = result_payload.get("id") if isinstance(result_payload, dict) else ""
        if approval_id:
            pending = [item for item in dashboard.dashboard_payload().get("pending", []) if item.get("id") == approval_id]
            if pending:
                send_approval_card(config, chat_id, pending[0])
    return reply


def download_photo(config, file_id):
    info = bot_request(config, "getFile", {"file_id": file_id})
    remote_path = str(info.get("file_path") or "")
    suffix = Path(remote_path).suffix or ".jpg"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / f"telegram_{datetime.now().strftime('%Y%m%d_%H%M%S')}{suffix}"
    url = f"https://api.telegram.org/file/bot{config.telegram_bot_token}/{remote_path}"
    with urllib.request.urlopen(url, timeout=45) as response:
        target.write_bytes(response.read())
    return target


def handle_update(config, update):
    if update.get("callback_query"):
        return handle_callback(config, update.get("callback_query") or {})
    message = update.get("message") or update.get("edited_message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    if chat_id is None or not is_allowed_chat(config, chat_id):
        return {"handled": False, "reason": "unauthorized_chat"}
    text = str(message.get("text") or message.get("caption") or "").strip()
    photos = message.get("photo") or []
    image_paths = []
    if photos:
        target = download_photo(config, photos[-1].get("file_id"))
        image_paths.append(str(target))
        if text:
            text = f"{text}\nImagen de referencia adjunta para creativos."
        else:
            reply = f"Imagen recibida y guardada. Para usarla, dime que campaña quieres preparar con esta imagen:\n{target}"
            send_message(config, chat_id, reply)
            return {"handled": True, "type": "photo_saved", "path": str(target)}
    if not text:
        return {"handled": False, "reason": "unsupported_message"}
    reply_approval_id = extract_approval_id((message.get("reply_to_message") or {}).get("text", ""))
    reply = handle_text(config, chat_id, text, image_paths=image_paths, reply_approval_id=reply_approval_id)
    return {"handled": True, "type": "text", "reply": reply}


def find_pending(approval_id):
    dashboard = load_dashboard_module()
    for item in dashboard.dashboard_payload().get("pending", []):
        if item.get("id") == approval_id:
            return item
    return None


def callback_answer(config, callback_id, text=""):
    if not callback_id:
        return None
    return bot_request(config, "answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:180]})


def handle_callback(config, query):
    callback_id = query.get("id", "")
    message = query.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    if chat_id is None or not is_allowed_chat(config, chat_id):
        callback_answer(config, callback_id, "Chat no autorizado.")
        return {"handled": False, "reason": "unauthorized_chat"}
    data = str(query.get("data") or "")
    action, _, approval_id = data.partition(":")
    if action not in {"approve", "approve_active", "reject"} or not approval_id:
        callback_answer(config, callback_id, "Accion no reconocida.")
        return {"handled": False, "reason": "unsupported_callback"}
    item = find_pending(approval_id)
    if not item:
        callback_answer(config, callback_id, "Esta decision ya no esta pendiente.")
        send_message(config, chat_id, "Esta decision ya no aparece pendiente. Puede que ya se haya ejecutado o rechazado.")
        return {"handled": True, "type": "missing_approval", "approval_id": approval_id}
    payload = item.get("payload", {})
    if action == "approve" and item.get("type") == "create_campaign" and payload.get("final_status") == "ACTIVE":
        callback_answer(config, callback_id, "Confirmacion extra requerida.")
        send_approval_card(config, chat_id, item)
        return {"handled": True, "type": "active_confirmation_required", "approval_id": approval_id}
    if action in {"approve", "approve_active"}:
        result = approve_pending(approval_id)
        if result:
            executed = result[0].get("result", {})
            succeeded = result[0].get("status") == "approved" or (executed.get("ok") is True and not executed.get("blocked"))
            status = "completada" if succeeded else "bloqueada o fallida; sigue pendiente para reintentar"
            callback_answer(config, callback_id, "Ejecutado." if succeeded else "No se pudo ejecutar.")
            send_message(config, chat_id, f"Aprobacion ejecutada: {approval_title(item)}\nEstado: {status}\nRevisa el registro para ver el detalle completo.")
            return {"handled": True, "type": "approved" if succeeded else "failed", "approval_id": approval_id}
        else:
            callback_answer(config, callback_id, "No encontre la decision.")
            send_message(config, chat_id, "No encontre esa aprobacion pendiente.")
        return {"handled": True, "type": "missing_approval", "approval_id": approval_id}
    rejected = reject_pending(approval_id, "Rejected from Telegram")
    callback_answer(config, callback_id, "Rechazado.")
    send_message(config, chat_id, f"Decision rechazada: {approval_title(item)}" if rejected else "No encontre esa aprobacion pendiente.")
    return {"handled": True, "type": "rejected", "approval_id": approval_id}


def poll_once(config, offset=None):
    settings = telegram_settings(config)
    payload = {"timeout": settings["poll_timeout"], "allowed_updates": json.dumps(["message", "edited_message", "callback_query"])}
    if offset is not None:
        payload["offset"] = int(offset)
    updates = bot_request(config, "getUpdates", payload, timeout=settings["poll_timeout"] + 10) or []
    next_offset = offset
    results = []
    for update in updates:
        next_offset = int(update.get("update_id", 0)) + 1
        results.append(handle_update(config, update))
    if next_offset is not None:
        write_json_file(OFFSET_FILE, {"offset": next_offset, "updated_at": utc_iso()}, ensure_ascii=False)
    return next_offset, results


def run(stop_event=None):
    config = load_config()
    settings = telegram_settings(config)
    if not settings["enabled"]:
        raise ValueError("Activa TELEGRAM_AGENT_ENABLED=true para usar el agente por Telegram.")
    if not settings["bot_configured"] or not settings["chat_id"]:
        raise ValueError("Configura TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID antes de iniciar Telegram.")
    saved_offset = read_json(OFFSET_FILE, {})
    offset = saved_offset.get("offset") if isinstance(saved_offset, dict) else None
    print("Telegram agent listening. Press Ctrl+C to stop.")
    while not (stop_event and stop_event.is_set()):
        try:
            offset, _ = poll_once(config, offset)
        except (urllib.error.URLError, TimeoutError):
            if stop_event:
                stop_event.wait(2)
            else:
                time.sleep(2)


def main():
    parser = argparse.ArgumentParser(description="Telegram access for Meta Ads Agent")
    parser.add_argument("--once", action="store_true", help="Read available Telegram messages once, then exit.")
    parser.add_argument("--test-message", action="store_true", help="Send a setup confirmation to the configured Telegram chat.")
    args = parser.parse_args()
    config = load_config()
    if args.test_message:
        settings = telegram_settings(config)
        if not settings["bot_configured"] or not settings["chat_id"]:
            raise SystemExit("Configura el bot y chat de Telegram primero.")
        send_message(config, settings["chat_id"], "Conexion lista. Ya puedes hablar con tu manager IA desde Telegram.")
        print("Mensaje de prueba enviado.")
        return 0
    if args.once:
        saved_offset = read_json(OFFSET_FILE, {})
        offset = saved_offset.get("offset") if isinstance(saved_offset, dict) else None
        _, results = poll_once(config, offset)
        print(json.dumps(redact_payload(results), ensure_ascii=False, indent=2))
        return 0
    try:
        run()
    except ValueError as exc:
        print(str(exc))
        return 2
    except KeyboardInterrupt:
        print("\nTelegram agent stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
