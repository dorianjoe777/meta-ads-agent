#!/usr/bin/env python3
"""Configure and run Admira IA through Hermes' native Telegram gateway."""
import json
import os
import hashlib
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from hermes_bridge import hermes_environment, prepare_hermes_workspace
from local_store import now_iso
from product_config import ROOT_DIR, env_bool, env_int

try:
    from product_config import normalize_hermes_model
except ImportError:
    def normalize_hermes_model(value):
        model = str(value or "").strip()
        if not model or model.lower() in {"auto", "recommended", "recomendado", "default"}:
            return "gpt-5.5"
        return model


DATA_DIR = ROOT_DIR / "dashboard" / "data"
LOGS_DIR = ROOT_DIR / "logs"
GATEWAY_STATE_FILE = DATA_DIR / "hermes_gateway_state.json"
DAILY_BRIEF_PROMPT_FILE = DATA_DIR / "hermes_daily_brief_prompt.md"

_GATEWAY_PROCESS = None
_GATEWAY_FINGERPRINT = None
_GATEWAY_PROCESS_KIND = "admira_hermes_gateway_supervisor"


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
            "never claim execution unless a product tool result confirms it. Business interview, brand, creatives, and previous campaign "
            "questions are handled by this Telegram conversation and are not dashboard setup blockers. Never tell the buyer setup is incomplete "
            "for those reasons; only say setup is missing when license, Meta connection, ad account, destination, real Meta data, ChatGPT/Codex, "
            "or Telegram itself is actually missing in CURRENT_CONTEXT.json or a product tool result. In Telegram, do not use Markdown tables; "
            "use short headings and bullet lists so the buyer always sees a readable message on mobile. On the first onboarding message, explain "
            "the journey before asking: first understand the business, then define visual brand and creative style, then turn that into offers, "
            "ad briefs, strategy, and campaigns. After that, ask one clear question."
        )
    return (
        "Eres Admira IA, el manager privado de Meta Ads del comprador. Estás hablando directamente desde Hermes Telegram Gateway. "
        "Usa tu memoria de Hermes y los archivos de este workspace antes de repetir preguntas. No cites ROAS, CPA, CTR, ganadoras, "
        "perdedoras ni campañas si CURRENT_CONTEXT.json no confirma datos reales de Meta. Las acciones protegidas de Meta se preparan "
        "para aprobación; nunca digas que ejecutaste algo si una herramienta del producto no lo confirmó. La entrevista del negocio, marca, "
        "creativos y campañas previas se completan conversando por Telegram y no bloquean la configuración inicial del dashboard. No le digas "
        "al comprador que falta completar configuración por esas razones; solo menciona que falta configurar algo si CURRENT_CONTEXT.json o una "
        "herramienta del producto confirma que falta licencia, conexión de Meta, cuenta publicitaria, destino, datos reales de Meta, ChatGPT/Codex "
        "o Telegram. En Telegram no uses tablas Markdown; usa títulos cortos y listas con viñetas para que el comprador siempre vea el mensaje "
        "bien en el celular. En el primer mensaje del onboarding, explica el camino antes de preguntar: primero entenderemos el negocio, "
        "después definiremos la marca visual y el estilo creativo, y luego convertiremos eso en ofertas, briefs, estrategia y campañas. "
        "Después de explicar eso, haz una sola pregunta clara."
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
        f"  default: {_quote_yaml(normalize_hermes_model(getattr(config, 'hermes_model', '')))}",
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
        "  extra:",
        "    rich_messages: false",
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


def _pid_cmdline(pid):
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return ""
    if pid_int <= 0:
        return ""
    proc_cmdline = Path(f"/proc/{pid_int}/cmdline")
    try:
        if proc_cmdline.exists():
            raw = proc_cmdline.read_bytes()
            return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    except OSError:
        return ""
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid_int), "-o", "command="],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
        return (result.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _looks_like_gateway_process(command):
    text = str(command or "")
    return _GATEWAY_PROCESS_KIND in text or "hermes gateway run" in text


def _pid_is_running(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def _terminate_pid_group(pid):
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    terminated = False
    try:
        if hasattr(os, "killpg"):
            try:
                os.killpg(pid_int, signal.SIGTERM)
            except OSError:
                os.kill(pid_int, signal.SIGTERM)
            terminated = True
        else:
            os.kill(pid_int, signal.SIGTERM)
            terminated = True
    except ProcessLookupError:
        return True
    except OSError:
        return False
    deadline = time.time() + 4
    while time.time() < deadline:
        if not _pid_is_running(pid_int):
            return True
        time.sleep(0.1)
    try:
        if hasattr(os, "killpg"):
            try:
                os.killpg(pid_int, signal.SIGKILL)
            except OSError:
                os.kill(pid_int, signal.SIGKILL)
        else:
            os.kill(pid_int, signal.SIGKILL)
        terminated = True
    except ProcessLookupError:
        return True
    except OSError:
        pass
    return terminated


def _terminate_process(process):
    if not process:
        return
    pid = getattr(process, "pid", None)
    terminated_by_group = bool(pid and _terminate_pid_group(pid))
    try:
        process.terminate()
        process.wait(timeout=1 if terminated_by_group else 6)
        return
    except subprocess.TimeoutExpired:
        pass
    except (OSError, AttributeError):
        if terminated_by_group:
            return
    if terminated_by_group:
        return
    try:
        process.kill()
    except (OSError, AttributeError):
        return
    try:
        process.wait(timeout=1)
    except Exception:
        pass


def _terminate_stale_gateway_from_state(skip_pid=None):
    if not GATEWAY_STATE_FILE.exists():
        return
    try:
        state = json.loads(GATEWAY_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    pid = state.get("pid")
    try:
        pid_int = int(pid)
        skip_int = int(skip_pid) if skip_pid else None
    except (TypeError, ValueError):
        return
    if skip_int and pid_int == skip_int:
        return
    command = _pid_cmdline(pid_int)
    if command and not _looks_like_gateway_process(command):
        return
    if command:
        _terminate_pid_group(pid_int)


def stop_gateway():
    global _GATEWAY_PROCESS, _GATEWAY_FINGERPRINT
    if _GATEWAY_PROCESS and _GATEWAY_PROCESS.poll() is None:
        _terminate_process(_GATEWAY_PROCESS)
    _terminate_stale_gateway_from_state(getattr(_GATEWAY_PROCESS, "pid", None))
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
            supervisor_script = "\n".join(
                [
                    f"# {_GATEWAY_PROCESS_KIND}",
                    "while :; do",
                    f"  {shlex.quote(hermes_cli)} gateway run --replace --accept-hooks",
                    "  code=$?",
                    "  echo \"[$(date -Is)] Hermes Gateway exited with code ${code}; restarting in 3s\"",
                    "  sleep 3",
                    "done",
                ]
            )
            _GATEWAY_PROCESS = subprocess.Popen(
                ["/bin/sh", "-c", supervisor_script],
                cwd=files["workspace"],
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
    except (OSError, ValueError) as exc:
        state = {"started_at": now_iso(), "mode": "hermes_gateway", "error": str(exc), **files}
        GATEWAY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        GATEWAY_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        _GATEWAY_PROCESS = None
        _GATEWAY_FINGERPRINT = None
        return {"started": False, "mode": "hermes_gateway", "detail": "No pude iniciar Hermes Gateway.", "error": str(exc), "log": str(log_path), **files}
    _GATEWAY_FINGERPRINT = fingerprint
    state = {"started_at": now_iso(), "pid": _GATEWAY_PROCESS.pid, "process_kind": _GATEWAY_PROCESS_KIND, "mode": "hermes_gateway", **files}
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
