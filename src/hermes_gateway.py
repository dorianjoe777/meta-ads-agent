#!/usr/bin/env python3
"""Configure and run Admira IA through Hermes' native Telegram gateway."""
import json
import os
import hashlib
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from communication_style import (
    ad_experience_from_environment,
    ad_experience_instruction,
    communication_preference,
    communication_style_from_environment,
    communication_style_instruction,
)
from hermes_bridge import hermes_brain_settings, hermes_environment, prepare_hermes_workspace
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
RESEARCH_PROMPT_FILE = DATA_DIR / "hermes_optimization_research_prompt.md"

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
    language = os.environ.get("TELEGRAM_LANGUAGE", "es")
    workspace_info = prepare_hermes_workspace(
        {
            "channel": "telegram",
            "language": language,
            "account_context": {
                "note": "Native Hermes Gateway workspace for Admira IA Telegram conversations.",
                "metrics_source": "read CURRENT_CONTEXT.json only if present and real.",
                "communication_preference": communication_preference(
                    communication_style_from_environment(),
                    language,
                    ad_experience_level=ad_experience_from_environment(),
                ),
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
    timezone_name = str(getattr(config, "daily_brief_timezone", "UTC") or "UTC")
    communication_style = communication_style_from_environment()
    ad_experience = ad_experience_from_environment()
    brain = hermes_brain_settings(config)
    brain_fingerprint = {
        "brain": brain.get("brain", ""),
        "provider": brain.get("provider", ""),
        "model": brain.get("model", ""),
        "base_url": brain.get("base_url", ""),
        "api_key_set": bool(brain.get("api_key")),
        "requires_codex_auth": bool(brain.get("requires_codex_auth")),
    }
    brain_hash = hashlib.sha256(json.dumps(brain_fingerprint, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"{token_hash}:{status['chat_id']}:{files['hermes_home']}:{timezone_name}:{communication_style}:{ad_experience}:{brain_hash}"


def gateway_prompt(language="es", communication_style="simple", ad_experience_level=""):
    style_instruction = communication_style_instruction(communication_style, language)
    experience_instruction = ad_experience_instruction(ad_experience_level, language)
    if str(language or "es").lower().startswith("en"):
        return (
            "You are Admira IA, the buyer's private Meta Ads manager. Your customer-facing identity is only Admira IA. "
            "Never mention Hermes, gateway/runtime details, MCP/tool names, internal commands, or `/help` command suggestions to the buyer unless support explicitly asks for diagnostics. "
            "Do not expose internal file paths such as `/app/...`, `dashboard/data/...`, `hermes-workspace/...`, `brand_guides/...`, `memory/...`, or `CURRENT_CONTEXT.json` to buyers unless support explicitly asks for technical diagnostics. "
            "If the buyer asks for a prompt, copy, plan, script, diagnosis, or useful content, paste it directly in the chat; do not reply only with “I saved it in this file” or ask them to open an internal path. "
            "Internal workspace files are your private memory/tooling; the buyer's usable workspace is the conversation. You may say you saved something internally only after giving the requested content in the same reply. "
            "Before any first-time greeting or onboarding question, read `memory/Conversation continuity.md`, `memory/continuity_status.json`, `CURRENT_CONTEXT.json`, `data/business_profile.json`, `memory/Agent onboarding plan.md`, `memory/Ads campaign onboarding.md`, `memory/recent_actions.json`, `memory/creative_experiments.json`, and relevant `brand_guides/` files in the workspace. "
            "If the continuity status says persistent memory exists, treat history cleanup, gateway restart, updates, or a fresh runtime session as a resume event: do not introduce yourself as first time, do not restart onboarding, and do not repeat the initial ads-experience/technical-detail question unless those files prove it is still missing. "
            "Resume with a short continuation message that mentions one concrete remembered item and continue from the next useful step. Use session search for prior Telegram sessions only as a helper; durable workspace files are enough to keep moving. "
            "When the buyer shares a public URL, Google Drive link, video, image, landing page, or creative reference, use `mcp_admira_fetch_public_asset` before saying you cannot access it. If it returns a video, use its returned video_url/direct_url when preparing a video creative. "
            "Use your memory and workspace files before asking repeated questions. Do not cite ROAS, CPA, CTR, winners, losers, "
            "or campaign names unless CURRENT_CONTEXT.json confirms real Meta data. Protected Meta actions must be prepared for approval; "
            "never claim execution unless a product tool result confirms it. Business interview, brand, creatives, and previous campaign "
            "questions are handled by this Telegram conversation and are not dashboard setup blockers. Never tell the buyer setup is incomplete "
            "for those reasons; only say setup is missing when license, Meta connection, ad account, destination, real Meta data, ChatGPT/Codex, "
            "or Telegram itself is actually missing in CURRENT_CONTEXT.json or a product tool result. In Telegram, do not use Markdown tables; "
            "use short headings and bullet lists so the buyer always sees a readable message on mobile. Only when the continuity status shows no persistent memory, use the first onboarding message to explain "
            "the journey before asking: first understand the business, then define visual brand and creative style, then turn that into offers, "
            "ad briefs, strategy, and campaigns. In that first-run case, also ask whether the buyer has experience creating/managing ads and whether they want deep technical details only if that operator preference is not already saved; "
            "save that operator preference with `mcp_admira_save_agent_preferences` when the tool is available. Before using Codex for launch-ready creative planning or ad production, explicitly ask about colors, design references/uploads, official logo usage, "
            "Before creating or staging a campaign, ask for the buyer's three most important success metrics/results in priority order, not only the single optimization event; examples include ROAS, cost per purchase, cost per initiate checkout, cost per qualified lead, booked appointments, or cost per real WhatsApp conversation. Save and pass them as success_metrics/key_results when staging. "
            "real photos/assets, and the test budget when a real test/launch is being planned. If any brand item is missing, ask that question instead of claiming a final ad is ready. For a standalone image/asset/draft, do not block on budget or a complete brief; pass the current offer context and mark it as asset-only. Recommend a multi-format portfolio and several meaningful hypotheses sized to the budget when budget exists; Image 2 "
            "is only one production tool, never the strategy. Do not claim a launch-ready final ad until the brand and test brief are ready. After a real multi-creative launch, "
            "schedule adaptive experiment reviews with real Meta IDs, budget, and target CPA; never call an early signal a winner. After that, ask one clear question."
            " For optimization, distinguish sales, leads, and messages; treat zero-conversion CPA as unknown until runtime, spend, attribution lag, learning status, freshness, and edit cooldown are mature. "
            "Use Shopify aggregates as business truth when connected. Respect optimizer shadow mode and account/test-budget caps. Official research outranks community anecdotes; research may propose controlled tests but never spend actions."
            " Be globally proactive as an expert ad configurator across measurement, event setup, budgets, schedules, placements, audiences, creative format, diagnostics, and approval flow; do not limit that posture to placements."
            f" {style_instruction} {experience_instruction}"
        )
    return (
        "Eres Admira IA, el manager privado de Meta Ads del comprador. Tu identidad de cara al cliente es solo Admira IA. "
        "Nunca menciones Hermes, gateway/runtime, nombres de herramientas MCP, comandos internos ni sugerencias de comandos como `/help` al comprador, salvo que soporte pida diagnóstico explícitamente. "
        "No muestres rutas internas como `/app/...`, `dashboard/data/...`, `hermes-workspace/...`, `brand_guides/...`, `memory/...` o `CURRENT_CONTEXT.json` al comprador, salvo que soporte pida diagnóstico técnico explícitamente. "
        "Si el comprador pide un prompt, copy, plan, guion, diagnóstico o contenido útil, entrégalo directamente en el chat; no respondas solo “lo guardé en este archivo” ni le pidas abrir una ruta interna. "
        "Los archivos internos son tu memoria/herramienta privada; el workspace útil del comprador es la conversación. Puedes decir que algo quedó guardado internamente solo después de dar el contenido solicitado en el mismo mensaje. "
        "Antes de saludar como si fuera la primera vez o hacer preguntas de onboarding, lee `memory/Conversation continuity.md`, `memory/continuity_status.json`, `CURRENT_CONTEXT.json`, `data/business_profile.json`, `memory/Agent onboarding plan.md`, `memory/Ads campaign onboarding.md`, `memory/recent_actions.json`, `memory/creative_experiments.json` y los archivos relevantes de `brand_guides/` en el workspace. "
        "Si el estado de continuidad dice que existe memoria persistente, trata una limpieza de historial, reinicio del gateway, actualización o sesión nueva del runtime como una reanudación: no te presentes como primera vez, no reinicies el onboarding y no repitas la pregunta inicial de experiencia en anuncios/detalle técnico salvo que esos archivos demuestren que todavía falta. "
        "Retoma con un mensaje corto que mencione un dato concreto recordado y sigue con el siguiente paso útil. Usa búsqueda de sesiones anteriores de Telegram solo como ayuda; los archivos durables del workspace bastan para continuar. "
        "Cuando el comprador comparta una URL pública, enlace de Google Drive, video, imagen, landing page o referencia creativa, usa `mcp_admira_fetch_public_asset` antes de decir que no puedes acceder. Si devuelve un video, usa su video_url/direct_url al preparar un creativo de video. "
        "Usa tu memoria y los archivos de este workspace antes de repetir preguntas. No cites ROAS, CPA, CTR, ganadoras, "
        "perdedoras ni campañas si CURRENT_CONTEXT.json no confirma datos reales de Meta. Las acciones protegidas de Meta se preparan "
        "para aprobación; nunca digas que ejecutaste algo si una herramienta del producto no lo confirmó. La entrevista del negocio, marca, "
        "creativos y campañas previas se completan conversando por Telegram y no bloquean la configuración inicial del dashboard. No le digas "
        "al comprador que falta completar configuración por esas razones; solo menciona que falta configurar algo si CURRENT_CONTEXT.json o una "
        "herramienta del producto confirma que falta licencia, conexión de Meta, cuenta publicitaria, destino, datos reales de Meta, ChatGPT/Codex "
        "o Telegram. En Telegram no uses tablas Markdown; usa títulos cortos y listas con viñetas para que el comprador siempre vea el mensaje "
        "bien en el celular. Solo cuando el estado de continuidad indique que no hay memoria persistente, usa el primer mensaje del onboarding para explicar el camino antes de preguntar: primero entenderemos el negocio, "
        "después definiremos la marca visual y el estilo creativo, y luego convertiremos eso en ofertas, briefs, estrategia y campañas. "
        "En ese caso de primera ejecución, también pregunta si el comprador tiene experiencia creando/gestionando anuncios y si quiere detalles técnicos profundos solo si esa preferencia de operador no está guardada; guarda esa preferencia de operador con `mcp_admira_save_agent_preferences` cuando la herramienta esté disponible. "
        "Antes de crear o preparar una campaña, pregunta por los 3 resultados más importantes para juzgarla, en orden de prioridad, no solo por el evento de optimización. Ejemplos: ROAS, costo por compra, costo por iniciar checkout, costo por lead calificado, reservas o costo por conversación real de WhatsApp. Guárdalos y pásalos como success_metrics/key_results al preparar campañas. "
        "Antes de usar Codex para planear o producir creativos, pregunta de forma explícita por colores, referencias o diseños para subir, uso del logo oficial, fotos/activos reales "
        "y presupuesto de prueba. Si falta cualquier pieza de marca, pregunta eso en vez de llamar Codex. Recomienda un portafolio de varios formatos e hipótesis realmente distintas que quepan en ese presupuesto; Image 2 "
        "es solo una herramienta de producción, nunca la estrategia. No generes un anuncio final hasta completar la marca y el brief de prueba. "
        "Después de lanzar una prueba real con varios creativos, programa revisiones adaptativas con IDs reales de Meta, presupuesto y CPA objetivo; "
        "nunca llames ganador a una señal temprana. Después de explicar eso, haz una sola pregunta clara."
        " Para optimizar, distingue ventas, leads y mensajes; un CPA con cero conversiones es desconocido hasta madurar tiempo, gasto, atribución, aprendizaje, frescura y cooldown de cambios. "
        "Usa agregados de Shopify como verdad del negocio cuando estén conectados. Respeta el modo observación del optimizador y los topes/reserva de tests. La guía oficial tiene prioridad; una anécdota comunitaria solo puede proponer un test controlado, nunca una acción de gasto."
        " Sé proactivo globalmente como configurador experto de anuncios en medición, evento correcto, presupuesto, calendario, ubicaciones, audiencias, formato creativo, diagnósticos y aprobaciones; no limites esa postura a placements."
        f" {style_instruction} {experience_instruction}"
    )


def write_gateway_files(config):
    home = hermes_home(config)
    workspace = gateway_workspace(config)
    status = telegram_settings(config)
    timezone_name = str(getattr(config, "daily_brief_timezone", "UTC") or "UTC")
    env_path = home / ".env"
    env_lines = []
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            key = line.split("=", 1)[0].strip() if "=" in line else ""
            if key not in {"TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS", "TELEGRAM_HOME_CHANNEL", "HERMES_TIMEZONE"}:
                env_lines.append(line)
    if config.telegram_bot_token:
        env_lines.append(f"TELEGRAM_BOT_TOKEN={_env_value(config.telegram_bot_token)}")
    if status["chat_id"]:
        env_lines.append(f"TELEGRAM_ALLOWED_USERS={_env_value(status['chat_id'])}")
        env_lines.append(f"TELEGRAM_HOME_CHANNEL={_env_value(status['chat_id'])}")
    env_lines.append(f"HERMES_TIMEZONE={_env_value(timezone_name)}")
    env_path.write_text("\n".join(env_lines).rstrip() + "\n", encoding="utf-8")
    env_path.chmod(0o600)

    allowed = status["chat_id"]
    communication_style = communication_style_from_environment()
    ad_experience = ad_experience_from_environment()
    prompt = gateway_prompt(status["language"], communication_style, ad_experience)
    brain = hermes_brain_settings(config)
    model_provider = brain.get("provider") or "openai-codex"
    model_default = brain.get("model") or normalize_hermes_model(getattr(config, "hermes_model", ""))
    toolsets = ["hermes-telegram", "memory", "skills", "session_search", "vision", "file", "web", "browser", "admira"]
    mcp_server_path = ROOT_DIR / "src" / "admira_mcp_server.py"
    config_yaml = [
        f"timezone: {_quote_yaml(timezone_name)}",
        "model:",
        f"  provider: {_quote_yaml(model_provider)}",
        f"  default: {_quote_yaml(model_default)}",
        "agent:",
        "  max_turns: 60",
        "  gateway_timeout: 1800",
        "  gateway_timeout_warning: 900",
        "  clarify_timeout: 600",
        "  disabled_toolsets:",
        "    - terminal",
        "    - code_execution",
        "    - image_gen",
        "compression:",
        "  enabled: true",
        "  threshold: 0.85",
        "  codex_gpt55_autoraise: false",
        "mcp_servers:",
        "  admira:",
        "    enabled: true",
        f"    command: {_quote_yaml(sys.executable)}",
        "    args:",
        f"      - {_quote_yaml(str(mcp_server_path))}",
        "    env:",
        f"      PYTHONPATH: {_quote_yaml(str(ROOT_DIR / 'src'))}",
        f"      ADMIRA_PRODUCT_ROOT: {_quote_yaml(str(ROOT_DIR))}",
        "    timeout: 900",
        "    connect_timeout: 45",
        "    keepalive_interval: 1200",
        "terminal:",
        f"  cwd: {_quote_yaml(str(workspace))}",
        "telegram:",
        "  gateway_restart_notification: false",
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
    existing_pythonpath = env.get("PYTHONPATH", "")
    source_path = str(ROOT_DIR / "src")
    env["PYTHONPATH"] = source_path if not existing_pythonpath else f"{source_path}{os.pathsep}{existing_pythonpath}"
    env["ADMIRA_HERMES_RUNTIME_PATCHES"] = "1"
    env["ADMIRA_GATEWAY_LANGUAGE"] = status["language"]
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
5. qué test creativo sigue esperando evidencia, cuál es su líder provisional si existe y cuándo será la próxima revisión
6. calidad y frescura de datos, conciliación Shopify/Meta, bloqueos por aprendizaje/cooldown, anomalías y progreso del modo observación

No declares una ganadora si el seguimiento dice que la evidencia todavía es insuficiente.
No conviertas cero conversiones en un CPA artificial. No recomiendes cambios por datos del día incompleto, aprendizaje, atribución inmadura, datos viejos o cooldown activo.

Termina exactamente con: ¿Tienes alguna pregunta?

Si todavía no hay Datos reales de Meta, dilo claramente y explica qué falta conectar. No uses datos demo.
"""


def optimization_research_prompt():
    return """Haz la revisión semanal de estrategias actuales para Meta Ads.

1. Busca primero documentación oficial de Meta sobre entrega, aprendizaje, medición, Conversions API, presupuesto y creativos.
2. Después revisa fuentes expertas recientes y discusiones actuales de Reddit/foros para detectar problemas o tácticas que valga la pena probar.
3. No conviertas una opinión comunitaria en regla. Registra contradicciones y exige corroboración.
4. Por cada hallazgo útil llama `mcp_admira_save_optimization_research` con URL HTTPS, título, source_type, fecha publicada/observada, claim, counterevidence y testable_hypothesis.
5. Ningún hallazgo puede ejecutar cambios de gasto. Solo puede proponer un experimento que respete presupuesto, evidencia madura y aprobaciones.
6. Descarta fuentes expiradas, contenido sin fecha útil y afirmaciones que prometen resultados garantizados.

Al terminar, resume máximo tres hipótesis nuevas y di claramente qué proviene de Meta y qué es anecdótico. Sin tablas Markdown.
"""


def ensure_weekly_research_cron(config):
    status = telegram_settings(config)
    if not (status["enabled"] and status["bot_configured"] and status["chat_id"]):
        return {"configured": False, "detail": "Telegram no está completo todavía."}
    hermes_cli = shutil.which(getattr(config, "hermes_cli", "hermes") or "hermes")
    if not hermes_cli:
        return {"configured": False, "detail": "Hermes no está instalado."}
    files = write_gateway_files(config)
    prompt = optimization_research_prompt()
    RESEARCH_PROMPT_FILE.write_text(prompt, encoding="utf-8")
    env = hermes_environment(config)
    env["HERMES_HOME"] = files["hermes_home"]
    timezone_name = str(getattr(config, "daily_brief_timezone", "UTC") or "UTC")
    env["HERMES_TIMEZONE"] = timezone_name
    env["TZ"] = timezone_name
    name = "Admira IA - investigación semanal"
    schedule = "0 3 * * 0"
    try:
        listed = subprocess.run([hermes_cli, "cron", "list"], cwd=files["workspace"], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"configured": False, "detail": "No pude revisar la investigación semanal.", "error": str(exc), **files}
    output = (listed.stdout or "") + (listed.stderr or "")
    existing = _cron_job(output, name)
    delivery = f"telegram:{status['chat_id']}"
    command = None
    if existing and (existing.get("schedule") != schedule or existing.get("deliver") != delivery):
        command = [hermes_cli, "cron", "edit", existing["id"], "--schedule", schedule, "--prompt", prompt, "--deliver", delivery, "--workdir", files["workspace"]]
    elif not existing and name not in output:
        command = [hermes_cli, "cron", "create", "--name", name, "--deliver", delivery, "--workdir", files["workspace"], schedule, prompt]
    if command:
        try:
            result = subprocess.run(command, cwd=files["workspace"], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"configured": False, "detail": "No pude programar la investigación semanal.", "error": str(exc), **files}
        return {"configured": result.returncode == 0, "name": name, "schedule": schedule, "timezone": timezone_name, "stdout": (result.stdout or "")[-500:], "stderr": (result.stderr or "")[-500:], **files}
    return {"configured": True, "exists": True, "name": name, "job_id": (existing or {}).get("id", ""), "schedule": schedule, "timezone": timezone_name, **files}


def _cron_job(output, name):
    ansi = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
    lines = ansi.sub("", str(output or "")).splitlines()
    current = None
    jobs = []
    for line in lines:
        job_match = re.match(r"^\s*([0-9a-fA-F]{8,})\s+\[(active|paused)\]\s*$", line)
        if job_match:
            current = {"id": job_match.group(1), "status": job_match.group(2), "name": "", "schedule": "", "deliver": ""}
            jobs.append(current)
            continue
        if current is None:
            continue
        field_match = re.match(r"^\s*(Name|Schedule|Deliver):\s*(.*?)\s*$", line)
        if field_match:
            current[field_match.group(1).lower()] = field_match.group(2)
    return next((job for job in jobs if job.get("name") == name), None)


def _daily_brief_job(output, name):
    return _cron_job(output, name)


def experiment_review_prompt(experiment):
    experiment_id = str((experiment or {}).get("id") or "").strip()
    return f"""Revisa el experimento creativo `{experiment_id}` en Admira IA.

1. Llama `mcp_admira_run_due_experiment_reviews` con `experiment_id: {experiment_id}`.
2. Usa únicamente la evidencia real devuelta por la herramienta.
3. Si falta evidencia, explica en palabras simples qué falta y menciona la próxima fecha de revisión.
4. Si hay líder, llámala provisional y explica la evidencia. Propón pausar, refrescar o escalar solo cuando la herramienta lo recomiende.
5. Nunca ejecutes cambios protegidos sin la aprobación normal del comprador.

Responde en español, corto y sin tablas Markdown.
"""


def experiment_review_cron_name(experiment):
    experiment_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", str((experiment or {}).get("id") or "experiment"))[:42]
    due = re.sub(r"[^0-9]+", "", str((experiment or {}).get("next_review_at") or ""))[:14]
    return f"Admira IA - experimento {experiment_id} - {due or 'review'}"


def ensure_experiment_review_cron(config, experiment):
    next_review_at = str((experiment or {}).get("next_review_at") or "").strip()
    if not next_review_at or (experiment or {}).get("status") in {"completed", "cancelled", "decision_ready"}:
        return {"configured": False, "needed": False, "detail": "El experimento no tiene otra revisión pendiente."}
    status = telegram_settings(config)
    if not (status["enabled"] and status["bot_configured"] and status["chat_id"]):
        return {"configured": False, "needed": True, "detail": "Telegram no está completo todavía."}
    hermes_cli = shutil.which(getattr(config, "hermes_cli", "hermes") or "hermes")
    if not hermes_cli:
        return {"configured": False, "needed": True, "detail": "Hermes no está instalado."}
    files = write_gateway_files(config)
    env = hermes_environment(config)
    env["HERMES_HOME"] = files["hermes_home"]
    timezone_name = str(getattr(config, "daily_brief_timezone", "UTC") or "UTC")
    env["HERMES_TIMEZONE"] = timezone_name
    env["TZ"] = timezone_name
    name = experiment_review_cron_name(experiment)
    schedule = next_review_at
    try:
        list_result = subprocess.run(
            [hermes_cli, "cron", "list"],
            cwd=files["workspace"],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"configured": False, "needed": True, "detail": "No pude revisar los seguimientos de Hermes.", "error": str(exc), **files}
    list_output = (list_result.stdout or "") + (list_result.stderr or "")
    existing = _cron_job(list_output, name)
    if existing or name in list_output:
        return {
            "configured": True,
            "needed": True,
            "exists": True,
            "name": name,
            "job_id": (existing or {}).get("id", ""),
            "schedule": schedule,
            "next_review_at": next_review_at,
            "timezone": timezone_name,
            **files,
        }
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
                "--repeat",
                "1",
                "--workdir",
                files["workspace"],
                schedule,
                experiment_review_prompt(experiment),
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
        return {"configured": False, "needed": True, "detail": "No pude programar la revisión del experimento.", "error": str(exc), "name": name, **files}
    return {
        "configured": result.returncode == 0,
        "needed": True,
        "exists": False,
        "name": name,
        "schedule": schedule,
        "next_review_at": next_review_at,
        "timezone": timezone_name,
        "stdout": (result.stdout or "")[-500:],
        "stderr": (result.stderr or "")[-500:],
        **files,
    }


def ensure_experiment_review_crons(config):
    try:
        from experiment_scheduler import load_experiments
        experiments = load_experiments().get("experiments", [])
    except (ImportError, OSError, ValueError):
        experiments = []
    results = []
    for experiment in experiments:
        if experiment.get("next_review_at") and experiment.get("status") not in {"completed", "cancelled", "decision_ready"}:
            results.append(ensure_experiment_review_cron(config, experiment))
    return {"count": len(results), "configured": len([item for item in results if item.get("configured")]), "items": results}


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
    timezone_name = str(getattr(config, "daily_brief_timezone", "UTC") or "UTC")
    env["HERMES_TIMEZONE"] = timezone_name
    env["TZ"] = timezone_name
    name = "Admira IA - lectura diaria"
    try:
        hour, minute = str(getattr(config, "daily_brief_time", "08:00") or "08:00").split(":", 1)
        schedule = f"{int(minute)} {int(hour)} * * *"
    except (TypeError, ValueError):
        schedule = "0 8 * * *"
    try:
        list_result = subprocess.run([hermes_cli, "cron", "list"], cwd=files["workspace"], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"configured": False, "detail": "No pude revisar los horarios de Hermes.", "error": str(exc), **files}
    list_output = (list_result.stdout or "") + (list_result.stderr or "")
    existing = _daily_brief_job(list_output, name)
    if existing:
        desired_delivery = f"telegram:{status['chat_id']}"
        if existing.get("schedule") == schedule and existing.get("deliver") == desired_delivery:
            return {"configured": True, "exists": True, "name": name, "job_id": existing["id"], "schedule": schedule, "timezone": timezone_name, **files}
        try:
            edit_result = subprocess.run(
                [
                    hermes_cli,
                    "cron",
                    "edit",
                    existing["id"],
                    "--schedule",
                    schedule,
                    "--prompt",
                    DAILY_BRIEF_PROMPT_FILE.read_text(encoding="utf-8"),
                    "--deliver",
                    desired_delivery,
                    "--workdir",
                    files["workspace"],
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
            return {"configured": False, "detail": "No pude actualizar la hora de la lectura diaria.", "error": str(exc), "name": name, "schedule": schedule, "timezone": timezone_name, **files}
        return {
            "configured": edit_result.returncode == 0,
            "exists": True,
            "updated": edit_result.returncode == 0,
            "name": name,
            "job_id": existing["id"],
            "schedule": schedule,
            "timezone": timezone_name,
            "stdout": (edit_result.stdout or "")[-500:],
            "stderr": (edit_result.stderr or "")[-500:],
            **files,
        }
    if name in list_output:
        return {"configured": True, "exists": True, "name": name, "schedule": schedule, "timezone": timezone_name, **files}
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
        "timezone": timezone_name,
        "stdout": (result.stdout or "")[-500:],
        "stderr": (result.stderr or "")[-500:],
        **files,
    }
