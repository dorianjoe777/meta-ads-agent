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
4. Hermes runs the conversation using the buyer's configured brain model. The buyer-facing default is `OpenAI Codex` through Hermes, which uses the buyer's ChatGPT/Codex OAuth session. Advanced installs can set `AGENT_BRAIN_PROVIDER=minimax`, `openai_api`, or `custom_api` to use MiniMax M3, OpenAI API, OpenRouter, Groq, Together, LM Studio, or another OpenAI-compatible `/chat/completions` URL inside Hermes.
5. If Hermes returns a tool request, the dashboard executes it through `execute_agent_tool()` and the normal approval queue.
6. The backend returns the final manager reply to the chat bubble or Telegram.

Hermes receives the profile and account summary as context, but the backend still owns permissions. The agent cannot bypass dashboard authorization, Con supervision/Piloto automatico rules, approvals, license checks, or the live-action switch.

There is no buyer runtime that bypasses Hermes. Model choices change the conversation brain inside Hermes, not the product's agentic infrastructure or safety layer. Meta actions, approvals, Telegram approvals, license checks, and audit logs still run through the backend. The dashboard never shows the saved API key back to the browser; it only reports whether a key is configured.

## Telegram Channel

`src/telegram_agent.py` exposes the same manager through a private Telegram bot using long polling, so local/VPS installs do not need a public webhook. It keeps a small Telegram-specific conversation history, accepts creative images into local storage, restricts access to the selected private chat ID, and sends tool requests through the same backend guardrails. Exact pending actions can be approved or rejected through Telegram buttons, a reply to the decision card, an explicit approval ID, or the single pending decision shortcut. If the action can leave ads active, Telegram still requires the exact active-spend confirmation phrase.

## Agent-Led Onboarding

The first-run UI onboarding stays short. It connects the operational essentials first:

1. Facebook/Meta connection
2. ad account
3. Page/Instagram/website destination
4. ChatGPT/Codex or compatible model
5. website/social links for a quick scan
6. Telegram

After Telegram is ready, the deeper onboarding happens conversationally. The buyer should not fill a long form before using the product. Hermes reads `dashboard/data/Agent onboarding plan.md` and moves through these phases:

1. `business_discovery`: understand offer, products/services, customer, stage, struggle, and goals.
2. `branding_creatives_creation`: research visual references, propose palettes/fonts/feelings/style, decide what is brand-wide vs product-specific, and save approved references.
3. `ads_campaign_onboarding`: understand previous promotions, results, lessons, constraints, budgets, and campaign goals.
4. `continuous_ads_manager`: use metrics, profitability memory, decisions, brand guides, references, ad briefs, and campaign context to manage the account coherently over time.

The backend persists this memory into:

```text
dashboard/data/business_profile.json
dashboard/data/Onboarding questions.md
dashboard/data/Agent onboarding plan.md
dashboard/data/Ads campaign onboarding.md
brand_guides/general_branding.md
brand_guides/creative_references.md
brand_guides/products/*.md
brand_guides/ad_briefs/*.md
```

The website/social links are context for the agent and optional scanner, not the whole onboarding. Hermes can strengthen discovery with browser retrieval when available, especially for product catalogs, visual references, and competitor/ad-design research.

## Model Options

### Hermes + ChatGPT/Codex

The recommended buyer default does not ask for an OpenAI API key for chat. On local desktop installs, the dashboard first tries to launch Hermes in the system terminal with:

```bash
hermes model
```

On Docker, DigitalOcean, or other headless VPS installs, the dashboard starts a restricted Hermes pseudo-terminal in the server with:

```bash
hermes model --no-browser
```

The buyer sees the Hermes output inside the dashboard, opens any ChatGPT login link in their own browser, and can answer simple Hermes prompts from the dashboard. Hermes stores the OAuth credentials in its own auth store on that install. Our product only calls Hermes; it does not store the buyer's ChatGPT password or OAuth token.

### API Brain Inside Hermes

For buyers who prefer token-based providers, the setup card can save:

```text
AGENT_CHAT_PROVIDER=hermes
AGENT_BRAIN_PROVIDER=minimax
AGENT_CHAT_BASE_URL=https://api.minimax.io/v1
AGENT_CHAT_MODEL=MiniMax-M3
AGENT_CHAT_API_KEY=...
```

Or:

```text
AGENT_CHAT_PROVIDER=hermes
AGENT_BRAIN_PROVIDER=custom_api
AGENT_CHAT_BASE_URL=https://provider.example/v1
AGENT_CHAT_MODEL=provider-model-name
AGENT_CHAT_API_KEY=...
```

Use `https://` for remote providers. `http://` is allowed only for local model servers such as `127.0.0.1` or `localhost`.

Legacy installs that still contain `AGENT_CHAT_PROVIDER=minimax` or `AGENT_CHAT_PROVIDER=openai_compatible` are interpreted as `AGENT_CHAT_PROVIDER=hermes` plus the matching `AGENT_BRAIN_PROVIDER`. This preserves old installs while preventing a direct chat bypass.

## Image-Aware Defaults

Hermes is configured for the agent-centered creative workflow, but not with broad machine control by default.

Default enabled toolsets:

```text
memory,skills,session_search,vision,image_gen,file,web,browser
```

These allow Hermes to remember useful context, use the agent profile, read the curated Hermes workspace, inspect uploaded product/reference images, and prepare image-generation direction. Uploaded Telegram images are saved under `output/telegram_uploads/`, copied into the Hermes workspace, and passed to Hermes with the CLI image attachment path.

Default disabled/sensitive capability posture:

```text
terminal,code_execution
```

Codex creative planning still runs through the product backend and guardrails. If Hermes sees an uploaded image and asks for `codex_creative_plan` or `codex_image_generate`, it should include a visual summary in the request so Codex receives the useful creative context without needing arbitrary filesystem access.

Final image generation in v1 uses the backend `codex_image_generate` tool, which calls Codex CLI with the buyer's authenticated ChatGPT/Codex session and saves the raster image in `output/creatives/`. Other image providers are legacy/disabled unless we intentionally add a new adapter later.

## Curated Business Memory

Skills are not enough by themselves because the agent also needs the buyer's actual business information. Instead of enabling general file browsing, the backend injects a curated business memory packet into Hermes on each chat turn.

Included memory:

```text
dashboard/data/business_profile.json
dashboard/data/Onboarding questions.md
dashboard/data/Agent onboarding plan.md
dashboard/data/Ads campaign onboarding.md
dashboard/data/audience_strategy.json
dashboard/data/individual_business_binding.json
dashboard/data/profitability_rules.json
dashboard/data/decision_memory.json
output/learning-log.md
brand_guides/general_branding.md
brand_guides/creative_references.md
brand_guides/products/*.md
recent chat turns
recent action log entries
recent creative refresh index
explicit uploaded image paths from allowed upload folders
```

At runtime, those files are copied into `dashboard/data/hermes-workspace/current/`, and Hermes runs from that folder with the file tool enabled. This gives Hermes real file-reading ability while keeping secrets, install files, `.env`, logs, and arbitrary local files outside its intended workspace.

The profitability and decision memory is structured on purpose. The agent should remember what it recommended, what the buyer approved, what was executed, and what should be checked again after 24h, 3 days, and 7 days. MemPalace can be added later as an optional retrieval backend, but the release default stays local, lightweight, and auditable.
