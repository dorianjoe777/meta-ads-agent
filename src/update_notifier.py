"""Deterministic Telegram notifications for official Admira IA updates.

This module never calls the agent or an inference provider.  The dashboard
supplies its existing signed-release checker and Telegram Bot API helper, so
Telegram and the UI always agree about the current stable release.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from local_store import read_json, write_private_json


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_text(value, limit):
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())[:limit]


def telegram_update_text(release, language="es"):
    latest = _safe_text((release or {}).get("latest_version"), 40)
    improvements = (release or {}).get("improvements") or []
    titles = []
    for item in improvements[:3]:
        title = _safe_text(item.get("title") if isinstance(item, dict) else item, 100)
        if title:
            titles.append(title)
    if str(language or "es").lower() == "en":
        lines = [
            f"Admira IA update available: {latest}",
            "",
            "It is ready to install with an automatic backup and verification.",
        ]
        if titles:
            lines.extend(["", "What is new:", *[f"• {title}" for title in titles]])
        lines.extend(["", "Open the dashboard to review and install it. Nothing will update or restart until you confirm."])
        return "\n".join(lines)
    lines = [
        f"Actualización de Admira IA disponible: {latest}",
        "",
        "Está lista para instalarse con copia de seguridad y verificación automática.",
    ]
    if titles:
        lines.extend(["", "Novedades:", *[f"• {title}" for title in titles]])
    lines.extend(["", "Abre el dashboard para revisarla e instalarla. Nada se actualizará ni reiniciará hasta que lo confirmes."])
    return "\n".join(lines)


def telegram_update_keyboard(update_url, language="es"):
    url = str(update_url or "").strip()
    if not url.startswith(("https://", "http://")):
        return []
    label = "Open update" if str(language or "es").lower() == "en" else "Abrir actualización"
    return [[{"text": label, "url": url}]]


def check_and_notify_update(
    config,
    *,
    request_release,
    bot_request,
    state_file,
    update_url="",
    language="es",
    now=None,
):
    """Check once and notify the configured Telegram chat at most once/version."""
    path = Path(state_file)
    checked_at = str(now or _now_iso())
    state = read_json(path, {})
    if not isinstance(state, dict):
        state = {}
    chat_id = str(getattr(config, "telegram_chat_id", "") or "").strip()
    bot_token = str(getattr(config, "telegram_bot_token", "") or "").strip()
    if not chat_id or not bot_token:
        return {"ok": True, "notified": False, "reason": "telegram_not_ready"}
    try:
        release = request_release()
    except Exception:
        state.update({
            "last_checked_at": checked_at,
            "last_error": "update_check_failed",
        })
        write_private_json(path, state, ensure_ascii=False)
        return {"ok": False, "notified": False, "reason": "update_check_failed"}
    latest = _safe_text(release.get("latest_version"), 40)
    state.update({
        "last_checked_at": checked_at,
        "last_seen_version": latest,
        "last_error": "",
    })
    if not release.get("available") or not latest:
        write_private_json(path, state, ensure_ascii=False)
        return {"ok": True, "notified": False, "reason": "up_to_date", "version": latest}
    if str(state.get("last_notified_version") or "") == latest:
        write_private_json(path, state, ensure_ascii=False)
        return {"ok": True, "notified": False, "reason": "already_notified", "version": latest}
    payload = {
        "chat_id": chat_id,
        "text": telegram_update_text(release, language),
        "disable_web_page_preview": "true",
    }
    keyboard = telegram_update_keyboard(update_url, language)
    if keyboard:
        payload["reply_markup"] = json.dumps({"inline_keyboard": keyboard}, ensure_ascii=False)
    try:
        bot_request(config, "sendMessage", payload, timeout=15)
    except Exception:
        state["last_error"] = "telegram_send_failed"
        write_private_json(path, state, ensure_ascii=False)
        return {"ok": False, "notified": False, "reason": "telegram_send_failed", "version": latest}
    state.update({
        "last_notified_version": latest,
        "last_notified_at": checked_at,
        "last_error": "",
    })
    write_private_json(path, state, ensure_ascii=False)
    return {"ok": True, "notified": True, "reason": "update_available", "version": latest}
