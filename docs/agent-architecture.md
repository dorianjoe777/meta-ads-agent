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
4. Hermes runs the conversation using the buyer's configured brain model. The buyer-facing default is `OpenAI Codex` through Hermes, which uses the buyer's ChatGPT/Codex OAuth session. Advanced installs can set `AGENT_BRAIN_PROVIDER=nvidia_nim`, `minimax`, `openai_api`, or `custom_api` to use NVIDIA NIM API Catalog, MiniMax M3, OpenAI API, OpenRouter, Groq, Together, LM Studio, or another OpenAI-compatible `/chat/completions` URL inside Hermes.
5. In dashboard chat, if Hermes returns a tool request, the dashboard executes it through `execute_agent_tool()` and the normal approval queue.
6. In Telegram, Hermes Gateway talks directly to the buyer and calls product tools through the local `admira` MCP server. Hermes still cannot bypass backend approvals, license checks, live-action rules, or logs.
7. The backend returns the final manager reply to the chat bubble when the dashboard channel is used.

Hermes receives the profile and account summary as context, but the backend still owns permissions. The agent cannot bypass dashboard authorization, Con supervision/Piloto automatico rules, approvals, license checks, or the live-action switch.

There is no buyer runtime that bypasses Hermes. Model choices change the conversation brain inside Hermes, not the product's agentic infrastructure or safety layer. Meta actions, approvals, Telegram approvals, license checks, and audit logs still run through the backend. The dashboard never shows the saved API key back to the browser; it only reports whether a key is configured.

## Telegram Channel

Telegram is a native Hermes Gateway channel, not a separate product bot that calls Hermes as a subroutine.

The dashboard only helps the buyer save the BotFather token, detect the private chat, create an isolated `HERMES_HOME`, write the Admira IA profile/config, and start `hermes gateway run`. After that, normal Telegram messages are handled directly by Hermes. This is required so Hermes owns conversation memory, slash commands such as `/model`, attachments, clarification loops, and long-running replies.

`src/telegram_agent.py` is legacy/setup support only. It may still be used to detect a private chat during onboarding or by old installs with `TELEGRAM_AGENT_MODE=legacy`, but it must not be the default buyer conversation path.

Each buyer install uses its own Hermes home:

```text
Local/native: dashboard/data/hermes-home
Docker/VPS:   /app/runtime/hermes
```

This prevents Admira IA from reading or modifying the buyer's personal `~/.hermes` sessions, crons, model settings, or unrelated Telegram gateways.

## Agent-Led Onboarding

The first-run UI onboarding stays short. It connects the operational essentials first:

1. Facebook/Meta connection
2. ad account
3. Page/Instagram/website destination
4. ChatGPT/Codex or compatible model
5. website/social links for a quick scan
6. Telegram

After Telegram is ready, the deeper onboarding happens conversationally inside Hermes Gateway. The buyer should not fill a long form before using the product. Hermes reads `dashboard/data/Agent onboarding plan.md` and moves through these phases:

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

## Product Tools Through MCP

Direct Telegram conversations use Hermes' native MCP client. The product writes this server into the isolated `HERMES_HOME/config.yaml`:

```yaml
mcp_servers:
  admira:
    command: "python3"
    args:
      - "src/admira_mcp_server.py"
```

Hermes registers these tools with the `mcp_admira_` prefix. Important examples:

```text
mcp_admira_get_real_meta_context
mcp_admira_run_daily_brief
mcp_admira_codex_image_generate
mcp_admira_create_whatsapp_campaign
mcp_admira_create_lead_form_campaign
mcp_admira_create_website_campaign
mcp_admira_create_messaging_campaign
mcp_admira_create_app_campaign
mcp_admira_create_on_meta_campaign
mcp_admira_stage_budget_change
mcp_admira_list_pending_approvals
mcp_admira_approve_action
mcp_admira_reject_action
mcp_admira_record_verified_signal
mcp_admira_get_verified_signal_summary
mcp_admira_verified_signal_feedback_prompt
```

The MCP server does not execute risky logic by itself. It calls `src/admira_tool_bridge.py`, which loads the existing dashboard action layer and routes through `execute_agent_tool()`. That means one safety path is shared by dashboard chat, Telegram, approvals, Codex/Image, campaign staging, budget changes, and memory saves.

Product skills live in `agent/skills/*/SKILL.md` and are copied into the Hermes workspace under `skills/`. They tell Hermes when to call each MCP tool. These skills are versioned with the product instead of being generated ad hoc during a chat.

The verified-signal tools write to a private local ledger first. They organize human-confirmed lead quality and outcomes for reporting, decisions, and future Meta feedback flows; they do not send events to Meta by themselves.

This local MCP bridge is not the same as a future public platform API. The later cloud product direction is documented in [future-cloud-api-mcp-platform.md](future-cloud-api-mcp-platform.md): a versioned API, CLI, webhooks, and official MCP server for CRMs, booking tools, ecommerce, WhatsApp inboxes, and external agents after Meta app approval and cloud tenancy/privacy controls are ready.

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
AGENT_BRAIN_PROVIDER=nvidia_nim
AGENT_CHAT_BASE_URL=https://integrate.api.nvidia.com/v1
AGENT_CHAT_MODEL=z-ai/glm-5.2
AGENT_CHAT_API_KEY=...
```

The NVIDIA preset discovers the buyer's current `/v1/models` catalog and registers a named `admira-nvidia` provider in Hermes. The API key is passed only through the live process environment and is never written into Hermes YAML or the model-catalog cache. NVIDIA hosted access remains subject to provider quotas.

For MiniMax:

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

Legacy prototypes used this broader list:

```text
memory,skills,session_search,vision,image_gen,file,web,browser
```

Release builds disable Hermes internal final image generation. The active Hermes Gateway toolset is:

```text
memory,skills,session_search,vision,file,web,browser,admira
```

These allow Hermes to remember useful context, use the agent profile, read the curated Hermes workspace, inspect uploaded product/reference images, browse public pages, and call protected Admira tools. Uploaded Telegram images are saved under `output/telegram_uploads/`, copied into the Hermes workspace, and passed to Hermes with the CLI image attachment path.

Default disabled/sensitive capability posture:

```text
terminal,code_execution,image_gen
```

Codex creative planning still runs through the product backend and guardrails. If Hermes sees an uploaded image and asks for `mcp_admira_codex_creative_plan` or `mcp_admira_codex_image_generate`, it should include a visual summary in the request so Codex receives the useful creative context without needing arbitrary filesystem access.

Final image generation in v1 uses the backend `codex_image_generate` tool, which calls Codex CLI with the buyer's authenticated ChatGPT/Codex session and saves the raster image in `output/creatives/`. Other image providers are legacy/disabled unless we intentionally add a new adapter later.

## Curated Business Memory

Skills are not enough by themselves because the agent also needs the buyer's actual business information.

In dashboard chat, the backend prepares a curated business memory packet for each request. In Telegram, Hermes Gateway is the conversation owner: it keeps the Hermes session, reads the curated workspace files directly, and calls `mcp_admira_*` tools when it needs fresh data or a protected product action. We do not keep appending the entire Telegram history into each prompt.

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
dashboard/data/creative_experiments.json
dashboard/data/optimization_state.json
dashboard/data/performance_history.json
dashboard/data/business_outcomes.json
dashboard/data/optimization_research.json
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

## Daily Brief

The buyer-facing daily brief must be a Hermes cron job delivered to Telegram, not a dashboard-side scheduler pretending to be the agent.

Default:

```bash
hermes cron create \
  --name "Admira IA - lectura diaria" \
  --deliver telegram:<buyer_chat_id> \
  --workdir dashboard/data/hermes-workspace/current \
  "0 8 * * *" \
  "<brief prompt>"
```

The brief should use real Meta data and recent memory when available, mention fluctuations over the last few days, name decisions waiting for approval, and end with:

```text
¿Tienes alguna pregunta?
```

If no real Meta data exists, Hermes must say that clearly and must not use demo campaigns or fake ROAS/CPA/CTR.

## Evidence-gated optimization

The optimizer is a state machine, not one weighted score. It identifies the campaign objective first, then requires fresh, mature evidence. It holds changes during Meta learning/preparing, incomplete attribution, stale reads, partial-day data, and the cooldown after a significant edit. Zero conversions leaves CPA unknown; it never substitutes an extreme sentinel value.

New installs begin in `shadow` mode. Recommendations are evaluated after they mature, but they cannot mutate Meta. Unlock requires all three conditions: 14 elapsed days, 10 matured outcomes, and explicit buyer confirmation. Existing live-action, license, approval, account-cap, and test-reserve controls still apply after unlock.

When Shopify is connected, the read-only connector queries only order timing and financial totals with `read_orders`. Local persistence contains daily gross/net/refund/order aggregates and SHA-256 deduplication keys—never customer names, emails, addresses, or raw order IDs. Shopify is the business-outcome truth; Meta remains attribution evidence, so differences trigger a measurement investigation rather than an automatic spend change.

Meta collection stores daily campaign, ad-set, and ad history plus separate placement/device, age/gender, and country views when the API permits them. Unsupported views are recorded as data-quality gaps. Funnel, anomaly, fatigue, and experiment diagnostics are recommendations only.

## Curated optimization research

Hermes schedules a weekly Sunday 03:00 research job in the buyer's timezone. It searches official Meta guidance first, then recent expert/community discussion. Every saved item includes URL, source type, observed/published date, credibility, counterevidence, expiry, and a testable hypothesis. Official sources have highest trust. Reddit/forum findings are anecdotal unless corroborated, expire quickly, and can only propose controlled experiments; they cannot trigger spend mutations.
