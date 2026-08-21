#!/usr/bin/env python3
"""Deterministic NVIDIA/Hermes request-budget canary.

This command never calls Meta, a model provider, or a buyer Gateway. It
constructs representative Hermes requests and runs the same shipped NIM
preflight used immediately before a provider call. The remote canary adds
one bounded, no-tool Hermes smoke request on an isolated home directory.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import admira_hermes_runtime_patch as runtime  # noqa: E402
import hermes_bridge  # noqa: E402


NATIVE_TOOLS = ("read_file", "memory_search", "web_search", "vision_analyze")
CASES = (
    ("metrics", "Revisa métricas, gasto, CTR, checkout y compras de la campaña", 8192, "get_real_meta_context"),
    ("campaign", "Prepara campaña de ventas con targeting, presupuesto, creativo y aprobación en pausa", 8192, "stage_campaign"),
    ("creative", "Crea video con Image 2, storyboard, recetas y render", 12288, "generate_motion_graphic_video"),
    ("organic", "Prepara imagen y video orgánico para Facebook en borrador aprobable", 12288, "stage_organic_social_post"),
    ("organic_en", "Create an organic social media post and leave it as a draft", 12288, "stage_organic_social_post"),
    ("catalog", "Importa catálogo, busca productos y combina ofertas en un bundle", 8192, "import_product_catalog"),
)


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": f"mcp_admira_{name}", "description": name}}


def _names(tools: list[dict]) -> set[str]:
    return {
        runtime._nvidia_normalize_tool_name(runtime._nvidia_tool_name(item))
        for item in tools
    }


def run_matrix() -> dict:
    all_names = sorted(set().union(*runtime.ADMIRA_NVIDIA_TOOL_PROFILES.values()))
    tools = [_tool(name) for name in all_names]
    tools.extend({"type": "function", "function": {"name": name}} for name in NATIVE_TOOLS)
    rows = []
    for case_id, prompt, max_tokens, required_tool in CASES:
        prepared = runtime._nvidia_prepare_request({
            "model": "minimaxai/minimax-m3",
            "messages": [{"role": "user", "content": prompt}],
            "tools": tools,
            "max_tokens": 65536,
        })
        names = _names(prepared.get("tools") or [])
        estimated = runtime._nvidia_estimated_input_tokens(
            prepared.get("messages") or [], prepared.get("tools") or []
        )
        rows.append({
            "case_id": case_id,
            "required_tool_present": required_tool in names,
            "native_tools_preserved": set(NATIVE_TOOLS).issubset(names),
            "tools_before": len(tools),
            "tools_after": len(names),
            "estimated_input_tokens": estimated,
            "input_budget_tokens": runtime.ADMIRA_NVIDIA_INPUT_BUDGET_TOKENS,
            "max_tokens": int(prepared.get("max_tokens") or 0),
            "passed": (
                required_tool in names
                and set(NATIVE_TOOLS).issubset(names)
                and estimated <= runtime.ADMIRA_NVIDIA_INPUT_BUDGET_TOKENS
                and int(prepared.get("max_tokens") or 0) <= 12288
                and len(names) < len(tools)
            ),
        })

    oversized = runtime._nvidia_prepare_request({
        "model": "minimaxai/minimax-m3",
        "messages": [
            {"role": "system", "content": "system " * 100000},
            {"role": "user", "content": "latest " * 100000},
        ],
        "tools": [_tool("get_real_meta_context")],
        "max_tokens": 65536,
    })
    oversized_tokens = runtime._nvidia_estimated_input_tokens(
        oversized.get("messages") or [], oversized.get("tools") or []
    )
    rows.append({
        "case_id": "oversized_context",
        "required_tool_present": True,
        "native_tools_preserved": True,
        "tools_before": 1,
        "tools_after": len(oversized.get("tools") or []),
        "estimated_input_tokens": oversized_tokens,
        "input_budget_tokens": runtime.ADMIRA_NVIDIA_INPUT_BUDGET_TOKENS,
        "max_tokens": int(oversized.get("max_tokens") or 0),
        "passed": oversized_tokens <= runtime.ADMIRA_NVIDIA_INPUT_BUDGET_TOKENS
        and int(oversized.get("max_tokens") or 0) <= 12288,
    })
    policy = hermes_bridge.inference_runtime_policy({
        "brain": "nvidia_nim",
        "provider": hermes_bridge.ADMIRA_NVIDIA_PROVIDER,
        "model": "minimaxai/minimax-m3",
    })
    fallback = {
        "primary": "minimaxai/minimax-m3",
        "first_model_specific_alternate": "deepseek-ai/deepseek-v4-flash-0731",
        "same_key_429_blocked": runtime._admira_same_nvidia_fallback_blocked("429 upstream rate limit"),
        "same_key_timeout_allowed": not runtime._admira_same_nvidia_fallback_blocked("model timeout"),
        "api_max_retries": int(policy.get("api_max_retries") or 0),
        "stream_retries": int(policy.get("stream_retries") or 0),
    }
    return {
        "kind": "nvidia_hermes_protection_matrix",
        "provider_calls": 0,
        "meta_calls": 0,
        "secrets_recorded": False,
        "rows": rows,
        "fallback": fallback,
        "passed": all(row["passed"] for row in rows)
        and fallback["same_key_429_blocked"]
        and fallback["same_key_timeout_allowed"]
        and fallback["api_max_retries"] == 0
        and fallback["stream_retries"] == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_matrix()
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
        try:
            args.output.chmod(0o600)
        except OSError:
            pass
    print(serialized, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
