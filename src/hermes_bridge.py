#!/usr/bin/env python3
"""Hermes Agent bridge for dashboard and Telegram conversations."""
import contextlib
import io
import json
import os
import shutil
import subprocess
from pathlib import Path

from agent_runtime import build_system_prompt
from decision_memory import decision_memory_payload, format_learning_log
from local_store import read_json
from security import redact_payload


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "dashboard" / "data"
BRAND_GUIDES_DIR = ROOT_DIR / "brand_guides"
HERMES_WORKSPACE_DIR = DATA_DIR / "hermes-workspace" / "current"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_IMAGE_DIRS = (ROOT_DIR / "output", ROOT_DIR / "dashboard" / "data" / "uploads")
MEMORY_TEXT_LIMIT = 8000
MEMORY_ITEM_LIMIT = 8
BLOCKED_MEMORY_TOKENS = {".env", "license_unlock.json"}


def split_csv(value):
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def safe_image_paths(payload):
    safe = []
    for raw_path in payload.get("image_paths") or []:
        try:
            path = Path(str(raw_path)).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if path.suffix.lower() not in IMAGE_EXTENSIONS or not path.exists() or not path.is_file():
            continue
        allowed = False
        for root in ALLOWED_IMAGE_DIRS:
            try:
                path.relative_to(root.resolve())
                allowed = True
                break
            except ValueError:
                continue
        if allowed:
            safe.append(str(path))
    return safe[:4]

def read_text(path, limit=MEMORY_TEXT_LIMIT):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return ""
    return text[:limit]


def scrub_memory(payload):
    if isinstance(payload, dict):
        clean = {}
        for key, value in payload.items():
            lowered = str(key or "").lower()
            if lowered in {"product_guide", "file", "filename", "path", "payload_path"} and any(token in str(value).lower() for token in BLOCKED_MEMORY_TOKENS):
                clean[key] = "redacted"
            else:
                clean[key] = scrub_memory(value)
        return clean
    if isinstance(payload, list):
        return [scrub_memory(item) for item in payload]
    if isinstance(payload, str):
        clean = payload
        for token in BLOCKED_MEMORY_TOKENS:
            clean = clean.replace(token, "redacted")
        return clean
    return payload


def write_workspace_file(relative_path, content):
    target = (HERMES_WORKSPACE_DIR / relative_path).resolve()
    target.relative_to(HERMES_WORKSPACE_DIR.resolve())
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, (dict, list)):
        target.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        target.write_text(str(content or ""), encoding="utf-8")
    return str(target.relative_to(HERMES_WORKSPACE_DIR))


def copy_workspace_file(source_path, relative_dir):
    source = Path(source_path).resolve()
    target_dir = (HERMES_WORKSPACE_DIR / relative_dir).resolve()
    target_dir.relative_to(HERMES_WORKSPACE_DIR.resolve())
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    shutil.copy2(source, target)
    return str(target)


def business_memory_files():
    files = {
        "business_profile": DATA_DIR / "business_profile.json",
        "onboarding_questions": DATA_DIR / "Onboarding questions.md",
        "onboarding_plan": DATA_DIR / "Agent onboarding plan.md",
        "ads_onboarding": DATA_DIR / "Ads campaign onboarding.md",
        "audience_strategy": DATA_DIR / "audience_strategy.json",
        "individual_business_binding": DATA_DIR / "individual_business_binding.json",
        "general_branding": BRAND_GUIDES_DIR / "general_branding.md",
        "creative_references": BRAND_GUIDES_DIR / "creative_references.md",
    }
    product_guides = []
    products_dir = BRAND_GUIDES_DIR / "products"
    if products_dir.exists():
        for path in sorted(products_dir.glob("*.md"))[:MEMORY_ITEM_LIMIT]:
            if path.name == "product.example.md":
                continue
            product_guides.append(path)
    ad_briefs = []
    ad_briefs_dir = BRAND_GUIDES_DIR / "ad_briefs"
    if ad_briefs_dir.exists():
        for path in sorted(ad_briefs_dir.glob("*.md"))[:MEMORY_ITEM_LIMIT]:
            if path.name == "ad_brief.example.md":
                continue
            ad_briefs.append(path)
    return files, product_guides, ad_briefs


def business_memory_context():
    files, product_guides, ad_briefs = business_memory_files()
    memory = {
        "business_profile": redact_payload(read_json(files["business_profile"], {})),
        "audience_strategy": redact_payload(read_json(files["audience_strategy"], {})),
        "business_binding": redact_payload(read_json(files["individual_business_binding"], {})),
        "onboarding_questions": read_text(files["onboarding_questions"]),
        "onboarding_plan": read_text(files["onboarding_plan"]),
        "ads_onboarding": read_text(files["ads_onboarding"]),
        "creative_references": read_text(files["creative_references"]),
        "brand_guides": {
            "general_branding": read_text(files["general_branding"]),
            "products": [
                {"path": str(path.relative_to(ROOT_DIR)), "content": read_text(path, 5000)}
                for path in product_guides
            ],
            "ad_briefs": [
                {"path": str(path.relative_to(ROOT_DIR)), "content": read_text(path, 5000)}
                for path in ad_briefs
            ],
        },
        "recent_history": {
            "chat": scrub_memory(redact_payload(read_json(DATA_DIR / "chat_history.json", [])[-MEMORY_ITEM_LIMIT:])),
            "actions": scrub_memory(redact_payload(read_json(DATA_DIR / "actions.json", [])[-MEMORY_ITEM_LIMIT:])),
            "creative_refreshes": scrub_memory(redact_payload(read_json(ROOT_DIR / "output" / "creatives" / "index.json", [])[-MEMORY_ITEM_LIMIT:])),
        },
        "profitability_memory": scrub_memory(redact_payload(decision_memory_payload())),
    }
    return memory


def prepare_hermes_workspace(payload):
    memory = business_memory_context()
    if HERMES_WORKSPACE_DIR.exists():
        shutil.rmtree(HERMES_WORKSPACE_DIR)
    HERMES_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    written.append(
        write_workspace_file(
            "README.md",
            """# Hermes Workspace

This folder is the only workspace Hermes should read for this product turn.
It contains curated business memory, brand guides, recent activity, and uploaded reference images.

Do not request files outside this workspace. If something is missing, ask the buyer or request a backend tool.
""",
        )
    )
    written.append(write_workspace_file("data/business_profile.json", memory["business_profile"]))
    written.append(write_workspace_file("memory/Onboarding questions.md", memory.get("onboarding_questions", "")))
    written.append(write_workspace_file("memory/Agent onboarding plan.md", memory.get("onboarding_plan", "")))
    written.append(write_workspace_file("memory/Ads campaign onboarding.md", memory.get("ads_onboarding", "")))
    written.append(write_workspace_file("data/audience_strategy.json", memory["audience_strategy"]))
    written.append(write_workspace_file("data/business_binding.json", memory["business_binding"]))
    written.append(write_workspace_file("memory/recent_chat.json", memory["recent_history"]["chat"]))
    written.append(write_workspace_file("memory/recent_actions.json", memory["recent_history"]["actions"]))
    written.append(write_workspace_file("memory/creative_refreshes.json", memory["recent_history"]["creative_refreshes"]))
    written.append(write_workspace_file("memory/profitability_rules.json", memory["profitability_memory"].get("profitability_rules", {})))
    written.append(write_workspace_file("memory/decision_memory.json", memory["profitability_memory"]))
    written.append(write_workspace_file("memory/learning_log.md", format_learning_log()))
    written.append(write_workspace_file("brand_guides/general_branding.md", memory["brand_guides"]["general_branding"]))
    written.append(write_workspace_file("brand_guides/creative_references.md", memory.get("creative_references", "")))
    for product in memory["brand_guides"]["products"]:
        name = Path(product["path"]).name
        written.append(write_workspace_file(f"brand_guides/products/{name}", product["content"]))
    for ad_brief in memory["brand_guides"].get("ad_briefs", []):
        name = Path(ad_brief["path"]).name
        written.append(write_workspace_file(f"brand_guides/ad_briefs/{name}", ad_brief["content"]))
    workspace_images = []
    for image_path in safe_image_paths(payload):
        workspace_images.append(copy_workspace_file(image_path, "uploads"))
    return {
        "path": str(HERMES_WORKSPACE_DIR),
        "files": written,
        "image_paths": workspace_images,
        "memory": memory,
    }


def hermes_environment(config):
    env = os.environ.copy()
    hermes_home = getattr(config, "hermes_home", "") or ""
    if hermes_home:
        env["HERMES_HOME"] = str(Path(hermes_home).expanduser())
    settings = hermes_brain_settings(config)
    if settings.get("provider") == "minimax" and settings.get("api_key"):
        env["MINIMAX_API_KEY"] = settings["api_key"]
        if settings.get("base_url"):
            env["MINIMAX_BASE_URL"] = settings["base_url"]
    if settings.get("provider") == "custom" and settings.get("api_key"):
        env["OPENAI_API_KEY"] = settings["api_key"]
        if settings.get("base_url"):
            env["OPENAI_BASE_URL"] = settings["base_url"]
    return env


def hermes_brain_settings(config):
    brain = str(getattr(config, "agent_brain_provider", "") or "").strip().lower().replace("-", "_")
    if not brain:
        legacy = str(getattr(config, "agent_chat_provider", "") or "").strip().lower().replace("-", "_")
        if legacy == "minimax":
            brain = "minimax"
        elif legacy in {"openai", "openai_compatible"}:
            base = str(getattr(config, "agent_chat_base_url", "") or "")
            brain = "openai_api" if "api.openai.com" in base else "custom_api"
        else:
            brain = "openai_codex"
    if brain in {"chatgpt", "chatgpt_subscription", "codex", "openai_codex", "hermes"}:
        return {
            "brain": "openai_codex",
            "provider": "openai-codex",
            "model": str(getattr(config, "hermes_model", "") or "").strip(),
            "base_url": "",
            "api_key": "",
            "requires_codex_auth": True,
        }
    if brain in {"minimax", "minimax_m3"}:
        return {
            "brain": "minimax",
            "provider": "minimax",
            "model": str(getattr(config, "agent_chat_model", "") or "MiniMax-M3").strip(),
            "base_url": str(getattr(config, "agent_chat_base_url", "") or "https://api.minimax.io/v1").strip().rstrip("/"),
            "api_key": str(getattr(config, "agent_chat_api_key", "") or "").strip(),
            "requires_codex_auth": False,
        }
    if brain in {"openai", "openai_api"}:
        return {
            "brain": "openai_api",
            "provider": "custom",
            "model": str(getattr(config, "agent_chat_model", "") or "gpt-4.1-mini").strip(),
            "base_url": str(getattr(config, "agent_chat_base_url", "") or "https://api.openai.com/v1").strip().rstrip("/"),
            "api_key": str(getattr(config, "agent_chat_api_key", "") or "").strip(),
            "requires_codex_auth": False,
        }
    return {
        "brain": "custom_api",
        "provider": "custom",
        "model": str(getattr(config, "agent_chat_model", "") or "").strip(),
        "base_url": str(getattr(config, "agent_chat_base_url", "") or "").strip().rstrip("/"),
        "api_key": str(getattr(config, "agent_chat_api_key", "") or "").strip(),
        "requires_codex_auth": False,
    }


def hermes_brain_ready(config):
    settings = hermes_brain_settings(config)
    if settings["requires_codex_auth"]:
        ready, detail = hermes_codex_ready(config)
        return ready, detail
    missing = []
    if not settings.get("api_key"):
        missing.append("API key")
    if not settings.get("model"):
        missing.append("model")
    if settings.get("provider") == "custom" and not settings.get("base_url"):
        missing.append("base URL")
    if missing:
        return False, "Missing " + ", ".join(missing)
    label = settings["brain"].replace("_", " ")
    return True, f"{label} configured inside Hermes"


def setup_reply(language="es"):
    if language == "es":
        return (
            "Todavia falta conectar el cerebro del agente. Abre Configuracion > Conectar ChatGPT o modelo API "
            "para terminar el paso guiado. En PC/Mac se abre la terminal; en VPS/DigitalOcean el dashboard "
            "muestra el login desde el navegador."
        )
    return (
        "The agent brain is not connected yet. Open Setup > Connect ChatGPT or API model for guided steps. "
        "On desktop it can open a terminal; on VPS/DigitalOcean the dashboard shows the login in the browser."
    )


def hermes_codex_ready(config):
    hermes_cli = shutil.which(getattr(config, "hermes_cli", "hermes") or "hermes")
    if not hermes_cli:
        return False, "Hermes not installed"
    try:
        completed = subprocess.run(
            [hermes_cli, "status"],
            cwd=str(ROOT_DIR),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        return False, f"Could not check Hermes status: {exc}"
    output = (completed.stdout or "") + "\n" + (completed.stderr or "")
    provider_line = next((line.strip() for line in output.splitlines() if "Provider:" in line), "")
    codex_line = next((line.strip() for line in output.splitlines() if "OpenAI Codex" in line), "")
    provider_ok = "codex" in provider_line.lower() or "openai codex" in provider_line.lower()
    codex_detail = codex_line.lower()
    codex_ok = bool(codex_line and "not logged in" not in codex_detail and "\u2717" not in codex_line and "error:" not in codex_detail)
    detail = f"{provider_line or 'Provider unknown'}; {codex_line or 'OpenAI Codex auth unknown'}"
    return provider_ok and codex_ok, detail


def hermes_prompt(config, payload, workspace_info=None):
    language = payload.get("language", "")
    context = payload.get("account_context") or {}
    workspace_info = workspace_info or prepare_hermes_workspace(payload)
    memory = workspace_info.get("memory") or business_memory_context()
    images = workspace_info.get("image_paths") or []
    image_note = ""
    if images:
        image_note = (
            "\n\nUploaded reference images:\n"
            + "\n".join(f"- {path}" for path in images)
            + "\nThe first image is attached to Hermes directly when the CLI supports it. Use vision to understand the image. "
            + "If you request `codex_creative_plan`, include a concise visual summary in the request arguments; do not rely on Codex reading arbitrary local files."
        )
    system_prompt = build_system_prompt(config, language)
    return (
        system_prompt
        + "\n\nHermes workspace path:\n"
        + str(workspace_info.get("path", ""))
        + "\n\nHermes workspace files:\n"
        + "\n".join(f"- {path}" for path in workspace_info.get("files", []))
        + "\n\nRead business files only inside this workspace. Do not read arbitrary local files. If a needed file is missing, ask the buyer or request a backend tool."
        + "\n\nCurrent account context JSON:\n"
        + json.dumps(context, ensure_ascii=False)
        + "\n\nCurated local business memory JSON:\n"
        + json.dumps(memory, ensure_ascii=False)
        + "\n\nOnboarding interview instructions, if pending:\n"
        + str(memory.get("onboarding_questions") or "")[:4000]
        + "\n\nAgent onboarding phase plan:\n"
        + str(memory.get("onboarding_plan") or "")[:4000]
        + "\n\nAds campaign onboarding memory:\n"
        + str(memory.get("ads_onboarding") or "")[:3000]
        + image_note
        + "\n\nReturn normal helpful text for explanations. If the user asks for a product action, return this JSON contract only:\n"
        + '{"assistant_message":"short user-facing reply","tool_request":{"tool":"tool_name","arguments":{}}}\n'
        + "Approvals are allowed only when the buyer asks to approve or reject one exact pending approval ID already present in context. Use `approval_decision` with that exact ID. If ambiguous, ask which decision or show choices; never invent approval IDs.\n\n"
        + f"User message:\n{str(payload.get('message') or '')[:5000]}"
    )


def library_chat(config, payload):
    from run_agent import AIAgent

    workspace_info = prepare_hermes_workspace(payload)
    brain = hermes_brain_settings(config)
    kwargs = {
        "quiet_mode": True,
        "platform": payload.get("channel") or "dashboard",
        "max_iterations": max(1, int(getattr(config, "hermes_max_iterations", 12) or 12)),
    }
    if brain.get("provider"):
        kwargs["provider"] = brain["provider"]
    if brain.get("base_url"):
        kwargs["base_url"] = brain["base_url"]
    if brain.get("api_key"):
        kwargs["api_key"] = brain["api_key"]
    if brain.get("model"):
        kwargs["model"] = brain["model"]
    enabled = split_csv(getattr(config, "hermes_enabled_toolsets", ""))
    disabled = split_csv(getattr(config, "hermes_disabled_toolsets", ""))
    if enabled:
        kwargs["enabled_toolsets"] = enabled
    if disabled:
        kwargs["disabled_toolsets"] = disabled

    env = hermes_environment(config)
    old_home = os.environ.get("HERMES_HOME")
    old_cwd = os.getcwd()
    if "HERMES_HOME" in env:
        os.environ["HERMES_HOME"] = env["HERMES_HOME"]
    try:
        os.chdir(workspace_info["path"])
        agent = AIAgent(**kwargs)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = agent.run_conversation(
                user_message=str(payload.get("message") or "")[:5000],
                system_message=hermes_prompt(config, payload, workspace_info),
            )
        if isinstance(result, dict):
            return str(result.get("final_response") or result.get("response") or "").strip()
        return str(result or "").strip()
    finally:
        os.chdir(old_cwd)
        if old_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = old_home


def cli_chat(config, payload):
    workspace_info = prepare_hermes_workspace(payload)
    prompt = hermes_prompt(config, payload, workspace_info)
    images = workspace_info.get("image_paths") or []
    brain = hermes_brain_settings(config)
    command = [
        getattr(config, "hermes_cli", "hermes") or "hermes",
        "chat",
        "--quiet",
        "--source",
        "meta-ads-agent",
        "--max-turns",
        str(max(1, int(getattr(config, "hermes_max_iterations", 12) or 12))),
        "-q",
        prompt,
    ]
    if brain.get("provider"):
        command.extend(["--provider", brain["provider"]])
    if brain.get("model"):
        command.extend(["--model", brain["model"]])
    enabled = ",".join(split_csv(getattr(config, "hermes_enabled_toolsets", "")))
    if enabled:
        command.extend(["--toolsets", enabled])
    if images:
        command.extend(["--image", images[0]])
    completed = subprocess.run(
        command,
        cwd=workspace_info["path"],
        env=hermes_environment(config),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=max(10, int(getattr(config, "hermes_timeout_seconds", 90) or 90)),
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "Hermes command failed").strip()[:1000])
    return (completed.stdout or "").strip()


def chat(config, payload):
    language = payload.get("language", "es")
    try:
        brain = hermes_brain_settings(config)
        if getattr(config, "hermes_require_codex_auth", True) or brain.get("requires_codex_auth"):
            ready, detail = hermes_brain_ready(config)
            if not ready:
                return {
                    "ok": False,
                    "provider": "hermes",
                    "fallback": True,
                    "reply": setup_reply(language),
                    "error": f"Hermes brain is not ready: {detail}",
                }
        elif not brain.get("requires_codex_auth"):
            ready, detail = hermes_brain_ready(config)
            if not ready:
                return {
                    "ok": False,
                    "provider": "hermes",
                    "fallback": True,
                    "reply": setup_reply(language),
                    "error": f"Hermes brain is not ready: {detail}",
                }
        images = safe_image_paths(payload)
        if images:
            reply = cli_chat(config, payload)
        elif getattr(config, "hermes_use_python_library", True):
            try:
                reply = library_chat(config, payload)
            except (ImportError, ModuleNotFoundError):
                reply = cli_chat(config, payload)
        else:
            reply = cli_chat(config, payload)
        return {"ok": True, "provider": "hermes", "brain_provider": brain.get("brain"), "model": brain.get("model") or "configured-in-hermes", "reply": reply}
    except (ImportError, ModuleNotFoundError) as exc:
        return {"ok": False, "provider": "hermes", "fallback": True, "reply": setup_reply(language), "error": f"Hermes Python library is not installed: {exc}"}
    except FileNotFoundError as exc:
        return {"ok": False, "provider": "hermes", "fallback": True, "reply": setup_reply(language), "error": f"Hermes CLI is not installed: {exc}"}
    except Exception as exc:
        return {"ok": False, "provider": "hermes", "fallback": True, "reply": setup_reply(language), "error": str(exc)}
