# Self-Hosted Meta Ads Agent

A standalone local/VPS Meta Ads operator inspired by the OpenClaw agent workflow. It monitors campaign performance, generates a daily brief, auto-pauses obvious waste, stages risky changes for approval, and keeps an audit log of every action.

This is positioned as a self-hosted product, not as an official OpenClaw agent and not as an official Meta product.

## What It Does

- Runs on a local PC, Mac, or VPS.
- Starts in `Con supervision`: real-data reading, explanation, and approval staging.
- Requires a dashboard password for protected actions.
- Blocks real mutations behind license validation, dashboard password, approvals, guardrails, and `LIVE_ACTIONS_ENABLED`.
- Connects to Meta through the buyer's own Meta app/token, with social-cli/direct Graph execution where available.
- Answers the 5 daily operator questions:
  - Am I on track?
  - What's running?
  - How's performance?
  - Who's winning or losing?
  - Any fatigue?
- Auto-pauses obvious waste rules:
  - CPA greater than 3x target.
  - Spend over the configured threshold with zero conversions.
- Requires approval for:
  - Budget changes over the configured percentage threshold.
  - Resuming paused campaigns/ad sets.
  - New campaign, ad set, creative, and ad creation.
- Logs daily reports, pending approvals, completed actions, and fatigue observations.
- Generates creative refresh drafts for fatigued or losing campaigns.
- Can initialize brand/product guide files so the agent can use Codex CLI as a creative strategy and image-prompt layer.
- Provides a dashboard at `http://127.0.0.1:7871`.

## Install Locally

```bash
./scripts/install-local.sh
./scripts/run-dashboard.sh
```

Beginner-friendly Docker install:

```bash
./scripts/run-docker.sh
```

The Docker image includes Python, Node/npm, and Codex CLI. See [es-instalacion-docker-codex.md](es-instalacion-docker-codex.md).

The ZIP also includes double-click launchers:

- `Instalar en Windows.bat`
- `Instalar en Mac.command`
- `Instalar en Linux.desktop`

Then open:

```text
http://127.0.0.1:7871
```

The installer creates `.env` from `.env.example` if one does not exist. During onboarding, the buyer creates their own dashboard password; the installer locks down local data permissions.

## First Supervised Run

Keep the agent in supervised mode:

```bash
META_ADS_AGENT_MODE=dry-run
```

Run the daily loop:

```bash
./scripts/run-daily-agent.sh
```

The dashboard labels this as `Con supervision`: the agent reads real data, explains, and prepares actions for approval.

## Setup Status

Use the dashboard `Setup` tab to see what is ready and what is blocked.

CLI equivalent:

```bash
python3 src/daily_agent.py status
```

See [setup-status.md](setup-status.md).

See [social-cli-onboarding.md](social-cli-onboarding.md) for the recommended buyer flow.

## Piloto Automatico

Piloto automatico should only be enabled after license, Meta connection, real insights, password, and approvals are ready. Existing social-cli helper commands are still useful for support:

```bash
social setup
social auth login
social auth status
social marketing accounts
social marketing set-default-account act_XXXX
```

Then confirm `.env` has:

```bash
META_ADS_AGENT_MODE=live
LIVE_ACTIONS_ENABLED=true
META_CONNECTOR=social_cli
META_AD_ACCOUNT_ID=act_XXXX
META_NOTIFY_CHANNEL=telegram
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

Run:

```bash
python3 src/daily_agent.py status
./scripts/run-daily-agent.sh
```

## Approvals

List pending approvals:

```bash
./scripts/list-pending.sh
```

Approve one action:

```bash
./scripts/approve.sh approval_id_here
```

Or use the dashboard approval queue for visibility.

## Daily Schedule

On Mac/Linux with cron:

```bash
./scripts/setup-cron.sh
```

This installs a 7am daily run:

```cron
0 7 * * * ./scripts/run-daily-agent.sh
```

On a Linux VPS with systemd user services:

```bash
./scripts/install-systemd-service.sh
```

That starts the dashboard and schedules the daily run.

## Important Files

```text
.env.example                         Example configuration
dashboard/monitoring-dashboard.py     Web dashboard
src/daily_agent.py                    Daily runner and approval executor
src/social_flow_client.py             social-cli and notification wrapper
src/product_config.py                 Config loader
dashboard/data/metrics.json           Demo/live metrics cache
dashboard/data/pending_approvals.json Approval queue
dashboard/data/actions.json           Action log
output/daily_brief_YYYY-MM-DD.json    Daily reports
output/fatigue-log.md                 Fatigue observations
output/creatives/                     Creative refresh manifests and generated images
```

## Creative Refresh

The creative refresh engine can generate copy variants and Codex/Image prompts for fatigued or losing campaigns.

Start with a supervised creative run:

```bash
python3 src/daily_agent.py creative-refresh
```

See [creative-refresh.md](creative-refresh.md) for setup and Codex/Image generation.

For the Codex creative strategy layer, see [es-codex-creativos.md](es-codex-creativos.md).

## Meta Upload Staging

Approved creative drafts can be converted into Meta Graph API upload payloads:

```bash
python3 src/daily_agent.py stage-upload output/creatives/creative_x/manifest.json --variant-id v1 --ratios 1:1
```

This creates a staged payload under `output/uploads/`. It does not upload until the buyer approves an exact action.

See [meta-upload.md](meta-upload.md).

Execute a staged payload for validation:

```bash
python3 src/daily_agent.py execute-upload output/uploads/upload_x/payload.json
```

An approved upload is blocked unless required Meta credentials, destination IDs, generated image assets, and an active license exist. Automatic execution additionally requires `Piloto automatico`.

## Security

The buyer-facing security story is local-first and fail-closed: dashboard password, local-only bind by default, private `.env`/data folders, cloud license validation for real buyer actions, redacted action logs, approval queues, and an optional Piloto automatico control.

See [security-model.md](security-model.md).

## Product Promise

This agent is not a guaranteed ROAS machine. It is a self-hosted operator assistant that makes the daily Meta Ads workflow visible, repeatable, and safer:

- It checks the account.
- It explains what it sees.
- It pauses only obvious waste.
- It asks before bigger changes.
- It logs everything.

## Product Boundary

Use this language in marketing:

- self-hosted
- local/VPS install
- approval-based
- human-in-the-loop
- inspired by OpenClaw-style agents

Avoid this language:

- official Meta automation
- official OpenClaw product
- fully hands-off spend manager
- guaranteed ROAS
