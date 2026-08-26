#!/usr/bin/env python3
"""Non-destructive release contract checks for Admira IA.

This is deliberately independent of an LLM and never writes to Meta, creates
an image, or starts a buyer Gateway.  It verifies the exact product MCP
contract that Hermes consumes before a source archive can be published.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


def fail(message: str) -> None:
    raise SystemExit(f"CANARY FAILED: {message}")


def request(process: subprocess.Popen, payload: dict) -> dict:
    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
    process.stdin.flush()
    line = process.stdout.readline()
    if not line:
        stderr = process.stderr.read() if process.stderr else ""
        fail(f"MCP server stopped before replying ({stderr[-500:]})")
    try:
        return json.loads(line)
    except json.JSONDecodeError as exc:
        fail(f"MCP server returned invalid JSON: {exc}")


def verify_runtime_import_guard() -> None:
    """The Hermes import bridge must not recurse while applying gateway hooks."""
    with tempfile.TemporaryDirectory(prefix="admira-import-guard-") as raw:
        fixture = Path(raw)
        gateway = fixture / "gateway"
        gateway.mkdir()
        (gateway / "__init__.py").write_text("", encoding="utf-8")
        (gateway / "run.py").write_text(
            "class GatewayRunner:\n"
            "    async def _handle_message(self, event):\n"
            "        return 'original'\n",
            encoding="utf-8",
        )
        (fixture / "admira_hermes_runtime_patch.py").write_text(
            "def apply():\n"
            "    return True\n"
            "def _nested_import():\n"
            "    from gateway.run import GatewayRunner\n"
            "    return GatewayRunner is not None\n"
            "def _patch_nvidia_request_gate():\n"
            "    return _nested_import()\n"
            "def _patch_gateway_chatgpt_slash_commands():\n"
            "    return _nested_import()\n"
            "def _patch_gateway_generated_media_delivery():\n"
            "    return _nested_import()\n"
            "def _patch_gateway_reset_campaign_scope():\n"
            "    return _nested_import()\n",
            encoding="utf-8",
        )
        env = dict(os.environ)
        env["ADMIRA_HERMES_RUNTIME_PATCHES"] = "1"
        env["PYTHONPATH"] = os.pathsep.join([str(fixture), str(SRC)])
        try:
            result = subprocess.run(
                [sys.executable, "-c", "import gateway.run; print('runtime-import-ok')"],
                cwd=str(ROOT),
                env=env,
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
        except subprocess.TimeoutExpired:
            fail("Hermes runtime import bridge recursed or exceeded five seconds")
        if result.returncode != 0 or "runtime-import-ok" not in result.stdout:
            fail(f"Hermes runtime import guard failed ({result.stderr[-300:]})")


def verify_chatgpt_gateway_contract() -> None:
    """A Telegram account switch must return its link before any restart."""
    dashboard_text = (ROOT / "dashboard" / "monitoring-dashboard.py").read_text(encoding="utf-8")
    runtime_text = (SRC / "admira_hermes_runtime_patch.py").read_text(encoding="utf-8")
    try:
        switch_block = dashboard_text.split(
            "def reconnect_shared_chatgpt_subscription():", 1
        )[1].split("\n\nAGENT_MODEL_GATEWAY_ENV_KEYS", 1)[0]
        finish_block = dashboard_text.split(
            "def finish_hermes_browserless_session(", 1
        )[1].split("\n\ndef read_hermes_browserless_output(", 1)[0]
    except IndexError:
        fail("ChatGPT reconnect lifecycle functions are missing")
    if "update_env_values(" in switch_block:
        fail("ChatGPT switch rewrites gateway environment before returning the device code")
    if "CODEX_IMAGE_SOURCE" not in finish_block or "update_env_values(" not in finish_block:
        fail("ChatGPT switch no longer persists the shared session after successful login")
    if "await asyncio.to_thread(" not in runtime_text:
        fail("ChatGPT device login blocks the Telegram event loop")

    import asyncio
    import types
    import admira_hermes_runtime_patch as runtime_patch

    gateway_package = types.ModuleType("gateway")
    gateway_package.__path__ = []
    gateway_run = types.ModuleType("gateway.run")

    class GatewayRunner:
        original_called = False

        def _is_user_authorized(self, _source):
            return True

        def _session_key_for_source(self, _source):
            return "agent:main:telegram:dm:release-canary"

        async def _handle_message(self, _event):
            self.original_called = True
            return "original"

    gateway_run.GatewayRunner = GatewayRunner
    previous_gateway = sys.modules.get("gateway")
    previous_gateway_run = sys.modules.get("gateway.run")
    original_recovery = runtime_patch._automatic_codex_recovery
    original_pending = runtime_patch._remember_chatgpt_login_pending
    try:
        sys.modules["gateway"] = gateway_package
        sys.modules["gateway.run"] = gateway_run
        runtime_patch._automatic_codex_recovery = lambda **_kwargs: {
            "url": "https://auth.openai.com/codex/device",
            "code": "ABCD-EFGH",
        }
        runtime_patch._remember_chatgpt_login_pending = lambda _key: True
        if not runtime_patch._patch_gateway_chatgpt_slash_commands():
            fail("ChatGPT Telegram slash handler was not installed")
        event = types.SimpleNamespace(text="/conectar_chatgpt", source=object())
        runner = GatewayRunner()
        reply = asyncio.run(runner._handle_message(event))
        if "https://auth.openai.com/codex/device" not in reply or "ABCD-EFGH" not in reply:
            fail("ChatGPT Telegram command did not return its secure link and code")
        if runner.original_called:
            fail("ChatGPT Telegram command fell through to the model")
    finally:
        runtime_patch._automatic_codex_recovery = original_recovery
        runtime_patch._remember_chatgpt_login_pending = original_pending
        if previous_gateway is None:
            sys.modules.pop("gateway", None)
        else:
            sys.modules["gateway"] = previous_gateway
        if previous_gateway_run is None:
            sys.modules.pop("gateway.run", None)
        else:
            sys.modules["gateway.run"] = previous_gateway_run


def main() -> None:
    sys.path.insert(0, str(SRC))
    import admira_mcp_server

    verify_runtime_import_guard()
    verify_chatgpt_gateway_contract()

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    installer = (ROOT / "scripts" / "install-local.sh").read_text(encoding="utf-8")
    if "ARG MCP_SDK_VERSION=" not in dockerfile or '"mcp==${MCP_SDK_VERSION}"' not in dockerfile:
        fail("Docker installs must pin the MCP SDK exactly")
    if 'MCP_SDK_VERSION="${MCP_SDK_VERSION:-' not in installer or '"mcp==${MCP_SDK_VERSION}"' not in installer:
        fail("native installs must pin the MCP SDK exactly")
    provenance_contract = (
        "ARG ADMIRA_BUILD_SHA=",
        "ARG ADMIRA_SOURCE_MANIFEST=",
        "org.opencontainers.image.revision=",
        "org.opencontainers.image.source-manifest=",
        "/app/source-manifest.sha256",
        "/app/build-commit.sha",
    )
    missing_provenance = [item for item in provenance_contract if item not in dockerfile]
    if missing_provenance:
        fail("Docker provenance contract is incomplete: " + ", ".join(missing_provenance))
    compose_contract = (
        "ADMIRA_BUILD_SHA: ${ADMIRA_BUILD_SHA:-unknown}",
        "ADMIRA_SOURCE_MANIFEST: ${ADMIRA_SOURCE_MANIFEST:-unknown}",
        "META_ADS_AGENT_VERSION: ${ADMIRA_BUILD_VERSION:-unknown}",
    )
    missing_compose = [item for item in compose_contract if item not in compose]
    if missing_compose:
        fail("Compose provenance contract is incomplete: " + ", ".join(missing_compose))
    if admira_mcp_server.create_fastmcp_server() is not None:
        fail("Admira must default to the protocol-owned MCP transport")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env["ADMIRA_MCP_USE_FASTMCP"] = "0"
    process = subprocess.Popen(
        [sys.executable, str(SRC / "admira_mcp_server.py")],
        cwd=str(ROOT),
        env=env,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        initialized = request(process, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        if initialized.get("result", {}).get("serverInfo", {}).get("name") != "admira":
            fail("MCP initialization did not identify Admira")
        listed = request(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = {item.get("name") for item in listed.get("result", {}).get("tools", [])}
        required = {
            "preflight_campaign",
            "codex_image_generate",
            "search_motion_graphic_recipes",
            "generate_motion_graphic_video",
            # Campaign creation is destination-specific. stage_campaign is a
            # retired generic helper and is not part of the public contract.
            "create_whatsapp_campaign",
            "create_lead_form_campaign",
            "create_website_campaign",
            "create_messaging_campaign",
        }
        if not required.issubset(tools):
            fail("MCP tool contract is incomplete")
        print(
            "CANARY PASS: runtime import guard, ChatGPT reconnect, pinned SDK, "
            "protocol MCP transport, and required tools are healthy."
        )
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
