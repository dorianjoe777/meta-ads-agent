# Agent Architecture

The agent uses an OpenClaw-inspired profile structure without depending on the OpenClaw daemon or runtime. This keeps the product easier to install and safer to sell as a standalone local/VPS tool.

## Profile Files

- `agent/SOUL.md` defines the manager's identity, tone, boundaries, and safety posture.
- `agent/AGENTS.md` defines the internal reasoning roles: manager, analyst, budget operator, creative strategist, safety controller, and setup coach.
- `agent/TOOLS.md` defines what the product can read, draft, stage, or execute, including safety gates.
- `agent/USER.md` defines the default buyer profile, especially Latin American beginners who need plain-language guidance.

## Runtime Flow

1. The dashboard sends the user's chat message plus current account context to `/api/chat`.
2. `src/agent_runtime.py` loads the profile files and builds one combined system prompt.
3. `src/agent_chat.py` adds the current dashboard context to that system prompt and sends one system message to MiniMax M2.7.
4. The backend returns the agent reply to the chat bubble.

MiniMax receives the profile and account summary as prompt context, but the backend still owns permissions. The chat model cannot bypass dashboard authorization, Con supervision/Piloto automatico rules, approvals, license checks, or the live-action switch.

## Telegram Channel

`src/telegram_agent.py` exposes the same manager through a private Telegram bot using long polling, so local/VPS installs do not need a public webhook. It keeps a small Telegram-specific conversation history, accepts creative images into local storage, restricts access to the selected private chat ID, and sends tool requests through the same backend guardrails. Free-text approval requests are rejected, while exact pending actions can be approved or rejected through Telegram inline buttons.

## Website Intelligence Onboarding

The first-run onboarding now starts before Meta setup with a business discovery layer:

- The buyer enters the business website.
- The local scanner reads title, description, headings, Page/landing URL clues, and simple offer signals.
- The buyer then writes their current stage, what feels confusing, and what they want to improve.
- The system saves this into `dashboard/data/business_profile.json`.
- Before the dashboard opens, the buyer sees an initial plan and ad-angle suggestions.

This profile is included in the MiniMax account context, so the manager does not answer only from ad metrics. It also understands the offer, buyer stage, likely audience, and first strategic direction.

The current scanner is intentionally local and simple: HTTP fetch plus HTML parsing. The abstraction is ready to be replaced or strengthened later by a Hermes/browser-retrieval implementation for JavaScript-heavy websites, product catalogs, screenshots, or deeper competitive research.

## Why Not Install OpenClaw Runtime?

For this product, the durable architecture matters more than the specific daemon. Shipping a self-contained agent profile avoids extra buyer setup, reduces security questions, and keeps the offer positioned as a custom Meta Ads operator rather than an OpenClaw clone.
