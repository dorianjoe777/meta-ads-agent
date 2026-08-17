#!/usr/bin/env python3
"""Exact, pre-authorized scheduled Meta campaign actions."""
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from license import license_status
from local_store import now_iso, read_json, write_private_json
from product_config import ROOT_DIR, load_config
from social_flow_client import SocialFlowClient

DATA_DIR = ROOT_DIR / "dashboard" / "data"
SCHEDULED_ACTIONS_FILE = DATA_DIR / "scheduled_campaign_actions.json"
ACTIONS_FILE = DATA_DIR / "actions.json"
METRICS_FILE = DATA_DIR / "metrics.json"


def _numeric_id(value):
    value = str(value or "").strip()
    return value if re.fullmatch(r"\d{12,24}", value) else ""


def _result_campaign_id(record):
    payload = record.get("payload") if isinstance(record, dict) else {}
    for candidate in (
        (payload or {}).get("result"),
        ((payload or {}).get("payload") or {}).get("result"),
        record.get("result") if isinstance(record, dict) else None,
    ):
        if isinstance(candidate, dict):
            campaign_id = _numeric_id(candidate.get("campaign_id"))
            if campaign_id and candidate.get("executed", True):
                return campaign_id
    return ""


def resolve_campaign_reference(campaign_id="", campaign_name=""):
    exact_id = _numeric_id(campaign_id)
    name = str(campaign_name or "").strip()
    if exact_id:
        return {"ok": True, "campaign_id": exact_id, "campaign_name": name, "source": "exact_meta_id"}

    reference = str(campaign_id or "").strip()
    metrics = read_json(METRICS_FILE, {})
    matches = []
    for campaign in (metrics.get("campaigns") or []) if isinstance(metrics, dict) else []:
        if not isinstance(campaign, dict):
            continue
        if reference and str(campaign.get("id") or "") == reference:
            matches.append((str(campaign.get("id")), str(campaign.get("name") or ""), "metrics_id"))
        elif name and str(campaign.get("name") or "").strip().casefold() == name.casefold():
            matches.append((str(campaign.get("id")), str(campaign.get("name") or ""), "metrics_name"))

    lookup = name or reference
    if lookup:
        for action in read_json(ACTIONS_FILE, []):
            if not isinstance(action, dict) or str(action.get("status") or "") not in {"approved", "completed"}:
                continue
            text = json.dumps(action, ensure_ascii=False)
            if lookup.casefold() not in text.casefold():
                continue
            result_id = _result_campaign_id(action)
            if result_id:
                matches.append((result_id, name or lookup, "creation_result"))

    unique = []
    seen = set()
    for item in matches:
        if _numeric_id(item[0]) and item[0] not in seen:
            unique.append(item)
            seen.add(item[0])
    if len(unique) == 1:
        return {"ok": True, "campaign_id": unique[0][0], "campaign_name": unique[0][1], "source": unique[0][2]}
    return {
        "ok": False,
        "reason": "ambiguous_campaign" if len(unique) > 1 else "missing_exact_meta_campaign_id",
        "candidates": [{"campaign_id": item[0], "campaign_name": item[1]} for item in unique[:8]],
    }


def _parse_due(value, timezone_name):
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        raise ValueError("scheduled_at_required")
    due = datetime.fromisoformat(text)
    if due.tzinfo is None:
        due = due.replace(tzinfo=ZoneInfo(str(timezone_name or "UTC")))
    return due.astimezone(timezone.utc)


def _state():
    value = read_json(SCHEDULED_ACTIONS_FILE, {"actions": []})
    return value if isinstance(value, dict) else {"actions": []}


def _save_record(record):
    state = _state()
    items = [item for item in state.get("actions", []) if isinstance(item, dict) and item.get("id") != record.get("id")]
    items.append(record)
    write_private_json(SCHEDULED_ACTIONS_FILE, {"updated_at": now_iso(), "actions": items[-200:]}, ensure_ascii=False)


def _graph_body(result):
    try:
        return json.loads((result or {}).get("stdout") or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


def schedule_campaign_activation(payload, hermes_home, telegram_chat_id, hermes_cli="hermes"):
    if not bool(payload.get("buyer_authorized") or payload.get("active_spend_confirmed")):
        return {"ok": False, "blocked": True, "reason": "activation_authorization_required"}
    if not bool(payload.get("creative_ready_confirmed")):
        return {"ok": False, "blocked": True, "reason": "creative_readiness_confirmation_required"}
    resolved = resolve_campaign_reference(payload.get("campaign_id"), payload.get("campaign_name"))
    if not resolved.get("ok"):
        return {"ok": False, "blocked": True, **resolved}
    timezone_name = str(payload.get("timezone") or os.environ.get("HERMES_TIMEZONE") or "UTC")
    try:
        due = _parse_due(payload.get("scheduled_at"), timezone_name)
    except (ValueError, KeyError):
        return {"ok": False, "blocked": True, "reason": "invalid_scheduled_at"}
    if due <= datetime.now(timezone.utc):
        return {"ok": False, "blocked": True, "reason": "scheduled_time_is_past"}

    config = load_config()
    details = SocialFlowClient(config).campaign_details(resolved["campaign_id"])
    body = _graph_body(details)
    if details.get("returncode") != 0 or str(body.get("id") or "") != resolved["campaign_id"]:
        return {"ok": False, "blocked": True, "reason": "meta_campaign_not_verified"}
    actual_name = str(body.get("name") or resolved.get("campaign_name") or "")
    requested_name = str(payload.get("campaign_name") or "").strip()
    if requested_name and actual_name.casefold() != requested_name.casefold():
        return {"ok": False, "blocked": True, "reason": "campaign_name_mismatch", "campaign_id": resolved["campaign_id"], "actual_name": actual_name}

    action_id = f"scheduled_activation_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    record = {
        "id": action_id,
        "type": "activate_campaign",
        "status": "scheduled",
        "campaign_id": resolved["campaign_id"],
        "campaign_name": actual_name,
        "scheduled_at": due.isoformat(),
        "timezone": timezone_name,
        "buyer_authorized": True,
        "creative_ready_confirmed": True,
        "budget_snapshot": str(payload.get("budget_snapshot") or payload.get("daily_budget") or ""),
        "created_at": now_iso(),
    }
    _save_record(record)

    home = Path(hermes_home)
    scripts_dir = home / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    script_name = f"{action_id}.py"
    script_path = scripts_dir / script_name
    script_path.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT_DIR / 'src')!r})\n"
        "from scheduled_campaign_actions import run_scheduled_activation\n"
        f"raise SystemExit(run_scheduled_activation({action_id!r}))\n",
        encoding="utf-8",
    )
    script_path.chmod(0o700)
    env = os.environ.copy()
    env["HERMES_HOME"] = str(home)
    command = [
        shutil.which(hermes_cli) or hermes_cli,
        "cron", "create", "--name", f"Admira IA - activar {actual_name}",
        "--deliver", f"telegram:{telegram_chat_id}", "--repeat", "1",
        "--script", script_name, "--no-agent", due.isoformat(),
    ]
    completed = subprocess.run(command, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
    if completed.returncode != 0:
        record.update({"status": "scheduling_failed", "error": (completed.stderr or completed.stdout or "")[-500:], "updated_at": now_iso()})
        _save_record(record)
        return {"ok": False, "blocked": True, "reason": "cron_creation_failed", "action_id": action_id}
    match = re.search(r"\b[0-9a-f]{12}\b", (completed.stdout or "") + (completed.stderr or ""), re.I)
    record.update({"cron_job_id": match.group(0) if match else "", "updated_at": now_iso()})
    _save_record(record)
    return {"ok": True, "scheduled": True, "action_id": action_id, "cron_job_id": record.get("cron_job_id"), "campaign_id": record["campaign_id"], "campaign_name": actual_name, "scheduled_at": due.isoformat(), "timezone": timezone_name}


def run_scheduled_activation(action_id):
    state = _state()
    record = next((item for item in state.get("actions", []) if item.get("id") == action_id), None)
    if not record or record.get("status") not in {"scheduled", "retry"}:
        print("La activación programada ya no está pendiente.")
        return 0
    config = load_config()
    if config.license_required_for_live and not license_status(config).get("valid"):
        record.update({"status": "blocked", "reason": "license_not_ready", "updated_at": now_iso()}); _save_record(record)
        print("No activé la campaña porque la licencia no pudo validarse.")
        return 1
    client = SocialFlowClient(config)
    before = _graph_body(client.campaign_details(record["campaign_id"]))
    if str(before.get("id") or "") != record["campaign_id"] or (record.get("campaign_name") and str(before.get("name") or "").casefold() != str(record["campaign_name"]).casefold()):
        record.update({"status": "blocked", "reason": "campaign_identity_changed", "updated_at": now_iso()}); _save_record(record)
        print("No activé la campaña porque su identidad ya no coincide con la autorización guardada.")
        return 1
    if str(before.get("status") or before.get("configured_status") or "").upper() == "ACTIVE":
        record.update({"status": "completed", "result": "already_active", "completed_at": now_iso()}); _save_record(record)
        print(f"La campaña {record['campaign_name']} ya estaba activa.")
        return 0
    result = client.resume("campaign", record["campaign_id"], approved=True)
    after = _graph_body(client.campaign_details(record["campaign_id"]))
    active = result.get("executed") and result.get("returncode") == 0 and str(after.get("status") or after.get("configured_status") or "").upper() == "ACTIVE"
    record.update({"status": "completed" if active else "failed", "completed_at": now_iso(), "verified_status": after.get("status") or after.get("configured_status") or "", "updated_at": now_iso()})
    _save_record(record)
    actions = read_json(ACTIONS_FILE, [])
    if not isinstance(actions, list):
        actions = []
    actions.insert(0, {"id": f"act_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}", "type": "scheduled_campaign_activation", "status": "completed" if active else "failed", "payload": {"scheduled_action_id": action_id, "campaign_id": record["campaign_id"], "campaign_name": record["campaign_name"], "verified_status": record.get("verified_status")}, "created_at": now_iso()})
    write_private_json(ACTIONS_FILE, actions[:500], ensure_ascii=False)
    if active:
        print(f"Activé {record['campaign_name']} a la hora autorizada y confirmé el estado ACTIVE en Meta.")
        return 0
    print(f"No pude activar {record['campaign_name']}; Meta no confirmó el estado ACTIVE. No hice otros cambios.")
    return 1
