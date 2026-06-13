#!/usr/bin/env python3
"""Agent profile loader for the dashboard chat runtime."""
import os
from pathlib import Path

from product_config import ROOT_DIR


PROFILE_FILES = (
    ("SOUL", "SOUL.md"),
    ("AGENTS", "AGENTS.md"),
    ("TOOLS", "TOOLS.md"),
    ("SKILLS", "SKILLS.md"),
    ("USER", "USER.md"),
)


def profile_dir(config=None):
    configured = getattr(config, "agent_profile_dir", "") if config else ""
    configured = configured or os.environ.get("AGENT_PROFILE_DIR", "agent")
    path = Path(configured)
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


def load_agent_profile(config=None):
    base = profile_dir(config)
    sections = []
    missing = []
    for title, filename in PROFILE_FILES:
        path = base / filename
        if not path.exists():
            missing.append(str(path))
            continue
        sections.append(
            {
                "title": title,
                "filename": filename,
                "path": str(path),
                "content": path.read_text(encoding="utf-8").strip(),
            }
        )
    return {"dir": str(base), "sections": sections, "missing": missing}


def language_runtime_instruction(language=""):
    if language == "es":
        return """# Language Runtime Instruction
The dashboard language is Spanish. Think directly in natural Latin American Spanish, not in English translated to Spanish.

Use beginner-friendly business language. Avoid textbook marketing definitions unless the user asks. Explain only the KPIs that matter, in plain terms:
- ROAS: how much money came back for each dollar spent.
- CPA: roughly what it costs to get one purchase, lead, or customer.
- CTR: how attractive the ad is to click.
- Frequency: how many times people are seeing the ad; high frequency can mean fatigue.

Keep answers warm, practical, and easy for a non-marketer to follow. Use clear next steps."""
    if language == "en":
        return """# Language Runtime Instruction
The dashboard language is English. Use clear beginner-friendly business language. Explain only the KPIs that matter and keep next steps concrete."""
    return """# Language Runtime Instruction
Use the user's language. If Spanish is used, think directly in natural Latin American Spanish and avoid translated-English phrasing."""


def build_system_prompt(config=None, language=""):
    profile = load_agent_profile(config)
    if not profile["sections"]:
        return fallback_system_prompt(language)

    chunks = [
        "You are Admira IA, the product's Meta Ads manager agent. Use this durable agent profile as your operating architecture.",
        "These profile files define identity, internal roles, tools, safety boundaries, and the default buyer profile.",
    ]
    for section in profile["sections"]:
        chunks.append(f"\n\n# {section['filename']}\n{section['content']}")
    if profile["missing"]:
        chunks.append("\n\n# Missing profile files\n" + "\n".join(f"- {item}" for item in profile["missing"]))
    chunks.append("\n\n" + language_runtime_instruction(language))
    return "\n".join(chunks)


def fallback_system_prompt(language=""):
    return """You are Admira IA, the user's warm Meta Ads business manager inside a self-hosted ads operator.

Be warm, calm, practical, and confidence-building. Use the user's language, explain marketing terms for beginners, and never claim live Meta changes were executed unless the backend confirms it. For risky spend changes, suggest approval and explain why.

""" + language_runtime_instruction(language)
