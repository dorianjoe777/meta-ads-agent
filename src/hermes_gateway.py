#!/usr/bin/env python3
"""Configure and run Admira IA through Hermes' native Telegram gateway."""
import json
import os
import hashlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

from hermes_bridge import hermes_environment, prepare_hermes_workspace
from local_store import now_iso
from product_config import ROOT_DIR, env_bool, env_int


DATA_DIR = ROOT_DIR / "dashboard" / "data"
LOGS_DIR = ROOT_DIR / "logs"
GATEWAY_STATE_FILE = DATA_DIR / "hermes_gateway_state.json"
DAILY_BRIEF_PROMPT_FILE = DATA_DIR / "hermes_daily_brief_prompt.md"

_GATEWAY_PROCESS = None
_GATEWAY_FINGERPRINT = None


def telegram_settings(config):
    return {
        "enabled": env_bool("TELEGRAM_AGENT_ENABLED", False),
        "mode": os.environ.get("TELEGRAM_AGENT_MODE", "hermes_gateway").strip().lower() or "hermes_gateway",
        "language": os.environ.get("TELEGRAM_LANGUAGE", "es").strip().lower() or "es",
        "poll_timeout": max(5, min(50, env_int("TELEGRAM_POLL_TIMEOUT", 25))),
        "bot_configured": bool(config.telegram_bot_token),
        "chat_id": str(config.telegram_chat_id or "").strip(),
        "hermes_home": str(getattr(config, "hermes_home", "") or ""),
    }


def hermes_home(config):
    path = Path(str(getattr(config, "hermes_home", "") or DATA_DIR / "hermes-home")).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def gateway_workspace(config):
    workspace_info = prepare_hermes_workspace(
        {
            "channel": "telegram",
            "language": os.environ.get("TELEGRAM_LANGUAGE", "es"),
            "account_context": {
                "note": "Native Hermes Gateway workspace for Admira IA Telegram conversations.",
                "metrics_source": "read CURRENT_CONTEXT.json only if present and real.",
            },
        }
    )
    return Path(workspace_info["path"])


def _quote_yaml(value):
    return json.dumps(str(value or ""), ensure_ascii=False)


def _env_value(value):
    return str(value or "").replace("\r", "\n").split("\n", 1)[0].strip()


def _gateway_fingerprint(config, status, files):
    token_hash = hashlib.sha256(str(config.telegram_bot_token or "").encode("utf-8")).hexdigest()[:16]
    return f"{token_hash}:{status['chat_id']}:{files['hermes_home']}"


def gateway_prompt(language="es"):
    if str(language or "es").lower().startswith("en"):
        return (
            "You are Admira IA, the buyer's private Meta Ads manager. You are running directly inside Hermes Telegram Gateway. "
            "Use Hermes memory and workspace files before asking repeated questions. Do not cite ROAS, CPA, CTR, winners, losers, "
            "or campaign names unless CURRENT_CONTEXT.json confirms real Meta data. Protected Meta actions must be prepared for approval; "
            "never claim execution unless a product tool result confirms it."
        )
    return (
        "Eres Admira IA, el manager privado de Meta Ads del comprador. Estás hablando directamente desde Hermes Telegram Gateway. "
        "Usa tu memoria de Hermes y los archivos de este workspace antes de repetir preguntas. No cites ROAS, CPA, CTR, ganadoras, "
        "perdedoras ni campañas si CURRENT_CONTEXT.json no confirma datos reales de Meta. Las acciones protegidas de Meta se preparan "
        "para aprobación; nunca digas que ejecutaste algo si una herramienta del producto no lo confirmó."
    )


def write_gateway_files(config):
    home = hermes_home(config)
    workspace = gateway_workspace(config)
    status = telegram_settings(config)
    env_path = home / ".env"
    env_lines = []
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            key = line.split("=", 1)[0].strip() if "=" in line else ""
            if key not in {"TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS", "TELEGRAM_HOME_CHANNEL"}:
                env_lines.append(line)
    if config.telegram_bot_token:
        env_lines.append(f"TELEGRAM_BOT_TOKEN={_env_value(config.telegram_bot_token)}")
    if status["chat_id"]:
        env_lines.append(f"TELEGRAM_ALLOWED_USERS={_env_value(status['chat_id'])}")
        env_lines.append(f"TELEGRAM_HOME_CHANNEL={_env_value(status['chat_id'])}")
    env_path.write_text("\n".join(env_lines).rstrip() + "\n", encoding="utf-8")
    env_path.chmod(0o600)

    allowed = status["chat_id"]
    prompt = gateway_prompt(status["language"])
    toolsets = ["hermes-telegram", "memory", "skills", "session_search", "vision", "file", "web", "browser", "admira"]
    mcp_server_path = ROOT_DIR / "src" / "admira_mcp_server.py"
    config_yaml = [
        "model:",
        "  provider: openai-codex",
        f"  default: {_quote_yaml(getattr(config, 'hermes_model', '') or 'auto')}",
        "agent:",
        "  max_turns: 60",
        "  gateway_timeout: 1800",
        "  gateway_timeout_warning: 900",
        "  clarify_timeout: 600",
        "  disabled_toolsets:",
        "    - terminal",
        "    - code_execution",
        "    - image_gen",
        "mcp_servers:",
        "  admira:",
        "    enabled: true",
        f"    command: {_quote_yaml(sys.executable)}",
        "    args:",
        f"      - {_quote_yaml(str(mcp_server_path))}",
        "    env:",
        f"      PYTHONPATH: {_quote_yaml(str(ROOT_DIR / 'src'))}",
        f"      ADMIRA_PRODUCT_ROOT: {_quote_yaml(str(ROOT_DIR))}",
        "    timeout: 300",
        "    connect_timeout: 45",
        "terminal:",
        f"  cwd: {_quote_yaml(str(workspace))}",
        "telegram:",
        "  reactions: false",
        f"  allowed_chats: {_quote_yaml(allowed)}",
        "  channel_prompts:",
    ]
    if allowed:
        config_yaml.extend([f"    {_quote_yaml(allowed)}: |", *[f"      {line}" for line in prompt.splitlines()]])
    else:
        config_yaml.append("    {}")
    config_yaml.extend(["platform_toolsets:", "  telegram:"])
    config_yaml.extend([f"    - {toolset}" for toolset in toolsets])
    config_yaml.extend(["streaming:", "  enabled: false", "hooks_auto_accept: true"])
    config_path = home / "config.yaml"
    config_path.write_text("\n".join(config_yaml).rstrip() + "\n", encoding="utf-8")
    config_path.chmod(0o600)
    return {"hermes_home": str(home), "workspace": str(workspace), "config": str(config_path), "env": str(env_path)}


def gateway_status(config):
    global _GATEWAY_PROCESS, _GATEWAY_FINGERPRINT
    status = telegram_settings(config)
    running = bool(_GATEWAY_PROCESS and _GATEWAY_PROCESS.poll() is None)
    payload = {
        **status,
        "direct_hermes": True,
        "process_running": running,
        "pid": _GATEWAY_PROCESS.pid if running else None,
        "fingerprint": _GATEWAY_FINGERPRINT or "",
    }
    if GATEWAY_STATE_FILE.exists():
        try:
            payload["last_state"] = json.loads(GATEWAY_STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload["last_state"] = {}
    return payload


def stop_gateway():
    global _GATEWAY_PROCESS, _GATEWAY_FINGERPRINT
    if _GATEWAY_PROCESS and _GATEWAY_PROCESS.poll() is None:
        _GATEWAY_PROCESS.terminate()
        try:
            _GATEWAY_PROCESS.wait(timeout=6)
        except subprocess.TimeoutExpired:
            _GATEWAY_PROCESS.kill()
    _GATEWAY_PROCESS = None
    _GATEWAY_FINGERPRINT = None


def start_gateway(config):
    global _GATEWAY_PROCESS, _GATEWAY_FINGERPRINT
    status = telegram_settings(config)
    if status["mode"] == "legacy":
        return {"started": False, "mode": "legacy", "detail": "Legacy Telegram bot mode selected."}
    if not (status["enabled"] and status["bot_configured"] and status["chat_id"]):
        stop_gateway()
        return {"started": False, "mode": "hermes_gateway", "detail": "Telegram no está completo todavía."}
    hermes_cli = shutil.which(getattr(config, "hermes_cli", "hermes") or "hermes")
    if not hermes_cli:
        return {"started": False, "mode": "hermes_gateway", "detail": "Hermes no está instalado en esta instalación."}
    files = write_gateway_files(config)
    fingerprint = _gateway_fingerprint(config, status, files)
    if _GATEWAY_PROCESS and _GATEWAY_PROCESS.poll() is None and _GATEWAY_FINGERPRINT == fingerprint:
        return {"started": True, "mode": "hermes_gateway", "pid": _GATEWAY_PROCESS.pid, **files}
    stop_gateway()
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "hermes-gateway.log"
    env = hermes_environment(config)
    env["HERMES_HOME"] = files["hermes_home"]
    env["HERMES_ACCEPT_HOOKS"] = "1"
    try:
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"\n[{now_iso()}] Starting Hermes Gateway for Admira IA\n")
            log_file.flush()
            _GATEWAY_PROCESS = subprocess.Popen(
                [hermes_cli, "gateway", "run", "--accept-hooks"],
                cwd=files["workspace"],
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
            )
    except (OSError, ValueError) as exc:
        state = {"started_at": now_iso(), "mode": "hermes_gateway", "error": str(exc), **files}
        GATEWAY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        GATEWAY_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        _GATEWAY_PROCESS = None
        _GATEWAY_FINGERPRINT = None
        return {"started": False, "mode": "hermes_gateway", "detail": "No pude iniciar Hermes Gateway.", "error": str(exc), "log": str(log_path), **files}
    _GATEWAY_FINGERPRINT = fingerprint
    state = {"started_at": now_iso(), "pid": _GATEWAY_PROCESS.pid, "mode": "hermes_gateway", **files}
    GATEWAY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    GATEWAY_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    time.sleep(0.3)
    started = _GATEWAY_PROCESS.poll() is None
    response = {"started": started, "mode": "hermes_gateway", "pid": _GATEWAY_PROCESS.pid, "log": str(log_path), **files}
    if not started:
        response["detail"] = "Hermes Gateway se cerró al iniciar. Revisa el diagnóstico técnico."
    return response


def daily_brief_prompt():
    return """Buenos días. Revisa la cuenta de Meta Ads con datos reales y memoria reciente.

Incluye contexto de los últimos días y fluctuaciones importantes. Responde corto y útil:

1. qué cambió
2. qué campaña o creativo necesita atención
3. qué se ve sano
4. qué prepararías para aprobación

Termina exactamente con: ¿Tienes alguna pregunta?

Si todavía no hay Datos reales de Meta, dilo claramente y explica qué falta conectar. No uses datos demo.
"""


def ensure_daily_brief_cron(config):
    status = telegram_settings(config)
    if not (status["enabled"] and status["bot_configured"] and status["chat_id"]):
        return {"configured": False, "detail": "Telegram no está completo todavía."}
    hermes_cli = shutil.which(getattr(config, "hermes_cli", "hermes") or "hermes")
    if not hermes_cli:
        return {"configured": False, "detail": "Hermes no está instalado."}
    files = write_gateway_files(config)
    DAILY_BRIEF_PROMPT_FILE.write_text(daily_brief_prompt(), encoding="utf-8")
    env = hermes_environment(config)
    env["HERMES_HOME"] = files["hermes_home"]
    name = "Admira IA - lectura diaria"
    try:
        list_result = subprocess.run([hermes_cli, "cron", "list"], cwd=files["workspace"], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"configured": False, "detail": "No pude revisar los horarios de Hermes.", "error": str(exc), **files}
    if name in ((list_result.stdout or "") + (list_result.stderr or "")):
        return {"configured": True, "exists": True, "name": name, **files}
    try:
        hour, minute = str(getattr(config, "daily_brief_time", "08:00") or "08:00").split(":", 1)
        schedule = f"{int(minute)} {int(hour)} * * *"
    except (TypeError, ValueError):
        schedule = "0 8 * * *"
    try:
        result = subprocess.run(
            [
                hermes_cli,
                "cron",
                "create",
                "--name",
                name,
                "--deliver",
                f"telegram:{status['chat_id']}",
                "--workdir",
                files["workspace"],
                schedule,
                DAILY_BRIEF_PROMPT_FILE.read_text(encoding="utf-8"),
            ],
            cwd=files["workspace"],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"configured": False, "detail": "No pude crear la lectura diaria en Hermes.", "error": str(exc), "name": name, "schedule": schedule, **files}
    return {
        "configured": result.returncode == 0,
        "exists": False,
        "name": name,
        "schedule": schedule,
        "stdout": (result.stdout or "")[-500:],
        "stderr": (result.stderr or "")[-500:],
        **files,
    }
