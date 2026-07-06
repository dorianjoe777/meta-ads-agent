# Self-Hosted Meta Ads Agent

A local/VPS Meta Ads operator for daily monitoring, budget recommendations, creative refresh drafts, approval-based actions, and a warm manager-style chat.

The product is designed for business owners and marketers who want automation without handing control of their ad account to a black-box SaaS. It starts **Con supervisión**: it reads real Meta data, explains what is happening, and executes only an exact approved action. **Piloto automático** can execute allowed actions only after setup, license validation and guardrails are ready.

## Quick Start

```bash
./scripts/install-local.sh
./scripts/run-dashboard.sh
```

Open:

```text
http://127.0.0.1:7871
```

The dashboard defaults to Spanish and can be switched to English from the header.

## What It Does

- Shows a daily Meta Ads brief.
- Flags winners, losers, and fatigue.
- Recommends budget changes.
- Stages risky decisions for approval.
- Generates creative refresh drafts.
- Can prepare Meta upload payloads.
- Offers a chat interface to talk to the agent like a business manager.
- Offers optional Telegram access so the buyer can talk to the same manager from their phone.
- Keeps real account actions behind a cloud-validated license, dashboard password, approvals and buyer rules.
- Can stage full campaign stacks: campaign, ad set, creative, and ad, with explicit approval before anything can spend.

## Buyer Setup Path

Use the dashboard `Configuración` / `Setup` tab. The guided path is:

1. Enter the license key.
2. Create a private Meta connection with the buyer's own Meta app/token.
3. Choose the ad account.
4. Select or save Facebook Page, Instagram if available, and landing URL.
5. Pull read-only live insights and confirm the dashboard shows `Datos reales de Meta`.
6. Run one supervised daily check.
7. Confirm approvals work.
8. Create the buyer-owned dashboard password.
9. Enable Piloto automatico only if the buyer wants allowed actions executed under their rules.
10. Complete a small real-action smoke test.

## Important Commands

```bash
./scripts/run-dashboard.sh
./scripts/run-daily-agent.sh
python3 src/daily_agent.py status
python3 src/daily_agent.py pending
python3 src/daily_agent.py approve APPROVAL_ID
./scripts/run-telegram-agent.sh
```

## Safety Defaults

- `META_ADS_AGENT_MODE=dry-run` shown to buyers as `Con supervisión`
- `LIVE_ACTIONS_ENABLED=false`
- `DASHBOARD_HOST=127.0.0.1`
- Buyer-created dashboard password required for protected actions
- `LICENSE_SERVER_URL` is required for buyer release builds.
- The buyer creates their own dashboard password at the end of onboarding.
- `.env`, logs, output, and dashboard data are private after install.

## Docs

- `docs/setup-local-vps.md`
- `docs/buyer-quick-start.md`
- `docs/es-activar-licencia.md`
- `docs/es-conectar-meta.md`
- `docs/es-crear-primera-campana.md`
- `docs/es-supervision-vs-piloto.md`
- `docs/es-checklist-anuncios-activos.md`
- `docs/es-solucion-problemas.md`
- `docs/es-usar-telegram.md`
- `docs/es-planes-de-licencia.md`
- `docs/es-instaladores-producto.md`
- `docs/es-firma-instaladores.md`
- `docs/setup-call-checklist.md`
- `docs/meta-graph-onboarding.md`
- `docs/security-explanation.md`
- `docs/live-mode-checklist.md`
- `docs/video-scripts.md`
- `docs/agent-architecture.md`
