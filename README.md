# Self-Hosted Meta Ads Agent

A local/VPS Meta Ads operator for daily monitoring, budget recommendations, creative refresh drafts, approval-based actions, and a warm manager-style chat.

The product is designed for business owners and marketers who want automation without handing control of their ad account to a black-box SaaS. Admira follows one simple approval rule: it may analyze, recommend, and create fully paused/no-spend campaign structures after the buyer asks; activation, spend, visible publishing, deletion, customer-data sending, or live-account mutations require explicit approval.

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
6. Run one daily check with real data.
7. Confirm approvals work.
8. Create the buyer-owned dashboard password.
9. Prepare a paused campaign structure.
10. Activate or spend only after the buyer approves clearly.

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

- Buyer-facing behavior is approval-based: paused creation is allowed; activation/spend is approval-protected.
- Legacy internal compatibility keeps `META_ADS_AGENT_MODE=dry-run` and `LIVE_ACTIONS_ENABLED=false`.
- `DASHBOARD_HOST=127.0.0.1`
- Buyer-created dashboard password required for protected actions
- `LICENSE_SERVER_URL` is required for buyer release builds.
- The buyer creates their own dashboard password at the end of onboarding.
- `.env`, logs, output, and dashboard data are private after install.

## Hosted clean canary status

The hosted r91 clean canary was validated on 2026-08-30 in a disposable clone
of the live control plane. Migrations 001–010 are current on Contabo and were
applied idempotently; the server preflight returned `PASS`. The control plane
is live at deployed commit `d9a623a6388b62df369ab97091386f6692e0c231` with
image `admira-control-plane:r91-d9a623a6388b`; tenant runtimes remain
deliberately pinned to image `r90`. The dormant hosted image is
`admira-ia-hosted:r91-canary-d9a623a6388b`.

The synthetic/code canary uses a fake provider and verifies local contracts,
idempotency, and tenant isolation. A separate real-provider canary is required
to verify the external route; it remains pending central-provider
authentication. Both central auth directories are prepared 0700 but lack
`auth.json`, so the central service remains stopped and
`ADMIRA_CENTRAL_IMAGE_READY=false`. The real-provider canary is blocked only
on the two authorized out-of-band logins and their canary; this is not
commercial readiness. Recovery and soak are deferred/off. This hosted canary
does not publish a buyer dashboard or turn the deployment into a SaaS product.

## Docs

- `docs/setup-local-vps.md`
- `docs/buyer-quick-start.md`
- `docs/es-activar-licencia.md`
- `docs/es-conectar-meta.md`
- `docs/es-crear-primera-campana.md`
- `docs/es-aprobaciones-y-seguridad.md`
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
