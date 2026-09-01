#!/usr/bin/env python3
"""Safe live canary for the central Terra campaign compiler.

This command sends only a structured-output compilation request through the
tenant HMAC client and the central Codex pool. It never invokes a campaign MCP,
Graph API, image generation, Telegram delivery, or a Meta mutation.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from src.hosted_central_campaign_compiler import maybe_compile_central_campaign


CANARY_TOOL = "admira_create_whatsapp_campaign"
CANARY_PROMPT = """This is a transport-only Admira campaign compiler canary.
Return the required JSON wrapper with ready=false, missing_fields=["canary"],
and payload_json="{}". Do not call tools, create media, contact Meta, or
describe anything outside that JSON wrapper."""


def run_real_canary(*, timeout: float = 240) -> dict[str, Any]:
    """Exercise the signed tenant-to-Terra path with no Meta side effect."""
    result = maybe_compile_central_campaign(CANARY_TOOL, CANARY_PROMPT, timeout=timeout)
    if result is None:
        return {
            "mode": "real",
            "ok": False,
            "status": "not_configured",
            "message": "Hosted central compiler entitlement/socket is not configured.",
        }
    if result.get("ok") is not True:
        return {
            "mode": "real",
            "ok": False,
            "status": "blocked",
            "error": str(result.get("reason") or "provider_failed"),
        }
    compiled = result.get("compiled")
    if not isinstance(compiled, dict) or compiled.get("ready") is not False:
        return {"mode": "real", "ok": False, "status": "invalid_output"}
    return {
        "mode": "real",
        "ok": True,
        "status": "provider_verified",
        "model": str(result.get("model") or ""),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=240)
    args = parser.parse_args(argv)
    result = run_real_canary(timeout=max(1.0, min(args.timeout, 300.0)))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
