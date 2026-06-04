# Agent Architecture

The agent now uses Hermes as the main reasoning/runtime layer. The product still keeps Meta execution inside its own backend guardrails, so Hermes can reason, remember, plan, and request tools, while approvals, license checks, live-action rules, and audit logs stay under our control.

## Profile Files

- `agent/SOUL.md` defines the manager's identity, tone, boundaries, and safety posture.
- `agent/AGENTS.md` defines the internal reasoning roles: manager, analyst, budget operator, creative strategist, safety controller, and setup coach.
- `agent/TOOLS.md` defines what the product can read, draft, stage, or execute, including safety gates.
- `agent/USER.md` defines the default buyer profile, especially Latin American beginners who need plain-language guidance.

## Runtime Flow

1. The dashboard sends the user's chat message plus current account context to `/api/chat`.
2. `src/agent_runtime.py` loads the profile files and builds one combined system prompt.
3. `src/agent_chat.py` sends the profile and account context through `src/hermes_bridge.py`.
4. Hermes runs the conversation using the buyer's configured Hermes model. The buyer-facing default is `OpenAI Codex` through `hermes model`, which uses the buyer's ChatGPT/Codex OAuth session. Advanced installs can instead set `AGENT_CHAT_PROVIDER=minimax` or `AGENT_CHAT_PROVIDER=openai_compatible` to use MiniMax M3, OpenRouter, Groq, Together, LM Studio, or another OpenAI-compatible `/chat/completions` URL.
5. If Hermes returns a tool request, the dashboard executes it through `execute_agent_tool()` and the normal approval queue.
6. The backend returns the final manager reply to the chat bubble or Telegram.

Hermes receives the profile and account summary as context, but the backend still owns permissions. The agent cannot bypass dashboard authorization, Con supervision/Piloto automatico rules, approvals, license checks, or the live-action switch.

The direct model path is intentionally narrow: it changes the conversation brain, not the product's safety layer. Meta actions, approvals, Telegram approvals, license checks, and audit logs still run through the backend. The dashboard never shows the saved API key back to the browser; it only reports whether a key is configured.

## Telegram Channel

`src/telegram_agent.py` exposes the same manager through a private Telegram bot using long polling, so local/VPS installs do not need a public webhook. It keeps a small Telegram-specific conversation history, accepts creative images into local storage, restricts access to the selected private chat ID, and sends tool requests through the same backend guardrails. Exact pending actions can be approved or rejected through Telegram buttons, a reply to the decision card, an explicit approval ID, or the single pending decision shortcut. If the action can leave ads active, Telegram still requires the exact active-spend confirmation phrase.

## Website Intelligence Onboarding

The first-run onboarding now starts before Meta setup with a business discovery layer:

- The buyer enters the business website.
- The local scanner reads title, description, headings, Page/landing URL clues, and simple offer signals.
- The buyer then writes their current stage, what feels confusing, and what they want to improve.
- The system saves this into `dashboard/data/business_profile.json`.
- Before the dashboard opens, the buyer sees an initial plan and ad-angle suggestions.

This profile is included in the Hermes account context, so the manager does not answer only from ad metrics. It also understands the offer, buyer stage, likely audience, and first strategic direction.

The current scanner is intentionally local and simple: HTTP fetch plus HTML parsing. Hermes can later strengthen this with browser retrieval for JavaScript-heavy websites, product catalogs, screenshots, or deeper competitive research.

## Model Options

### Hermes + ChatGPT/Codex

The recommended buyer default does not ask for an OpenAI API key for chat. The dashboard first tries to launch the Hermes login automatically with:

```bash
hermes model
```

They choose `OpenAI Codex`, complete the OAuth/device login with their ChatGPT account, and Hermes stores those credentials in its own auth store. Our product only calls Hermes; it does not store the buyer's ChatGPT password or OAuth token.

### Direct OpenAI-Compatible API

For buyers who prefer token-based providers, the setup card can save:

```text
AGENT_CHAT_PROVIDER=minimax
AGENT_CHAT_BASE_URL=https://api.minimax.io/v1
AGENT_CHAT_MODEL=MiniMax-M3
AGENT_CHAT_API_KEY=...
```

Or:

```text
AGENT_CHAT_PROVIDER=openai_compatible
AGENT_CHAT_BASE_URL=https://provider.example/v1
AGENT_CHAT_MODEL=provider-model-name
AGENT_CHAT_API_KEY=...
```

Use `https://` for remote providers. `http://` is allowed only for local model servers such as `127.0.0.1` or `localhost`.

## Image-Aware Defaults

Hermes is configured for the agent-centered creative workflow, but not with broad machine control by default.

Default enabled toolsets:

```text
memory,skills,session_search,vision,image_gen,file
```

These allow Hermes to remember useful context, use the agent profile, read the curated Hermes workspace, inspect uploaded product/reference images, and prepare image-generation direction. Uploaded Telegram images are saved under `output/telegram_uploads/`, copied into the Hermes workspace, and passed to Hermes with the CLI image attachment path.

Default disabled/sensitive capability posture:

```text
terminal,code_execution
```

Codex creative planning still runs through the product backend and guardrails. If Hermes sees an uploaded image and asks for `codex_creative_plan`, it should include a visual summary in the request so Codex receives the useful creative context without needing arbitrary filesystem access.

Image generation is separate from chat because image APIs are not all OpenAI-compatible. Current v1 creative rendering still uses the configured creative provider, such as Nano Banana/Gemini, while Codex/Hermes prepares strategy and prompts. MiniMax image generation can be added later as a dedicated creative-provider adapter.

## Curated Business Memory

Skills are not enough by themselves because the agent also needs the buyer's actual business information. Instead of enabling general file browsing, the backend injects a curated business memory packet into Hermes on each chat turn.

Included memory:

```text
dashboard/data/business_profile.json
dashboard/data/audience_strategy.json
dashboard/data/individual_business_binding.json
dashboard/data/profitability_rules.json
dashboard/data/decision_memory.json
output/learning-log.md
brand_guides/general_branding.md
brand_guides/products/*.md
recent chat turns
recent action log entries
recent creative refresh index
explicit uploaded image paths from allowed upload folders
```

At runtime, those files are copied into `dashboard/data/hermes-workspace/current/`, and Hermes runs from that folder with the file tool enabled. This gives Hermes real file-reading ability while keeping secrets, install files, `.env`, logs, and arbitrary local files outside its intended workspace.

The profitability and decision memory is structured on purpose. The agent should remember what it recommended, what the buyer approved, what was executed, and what should be checked again after 24h, 3 days, and 7 days. MemPalace can be added later as an optional retrieval backend, but the release default stays local, lightweight, and auditable.
