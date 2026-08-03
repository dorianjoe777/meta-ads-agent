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


def main() -> None:
    sys.path.insert(0, str(SRC))
    import admira_mcp_server

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    installer = (ROOT / "scripts" / "install-local.sh").read_text(encoding="utf-8")
    if "ARG MCP_SDK_VERSION=" not in dockerfile or '"mcp==${MCP_SDK_VERSION}"' not in dockerfile:
        fail("Docker installs must pin the MCP SDK exactly")
    if 'MCP_SDK_VERSION="${MCP_SDK_VERSION:-' not in installer or '"mcp==${MCP_SDK_VERSION}"' not in installer:
        fail("native installs must pin the MCP SDK exactly")
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
        required = {"preflight_campaign", "codex_image_generate", "stage_campaign"}
        if not required.issubset(tools):
            fail("MCP tool contract is incomplete")
        print("CANARY PASS: pinned SDK, protocol MCP transport, and required tools are healthy.")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
