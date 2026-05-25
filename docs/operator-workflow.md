# Operator Workflow

The product is designed around a human-in-the-loop ads operator pattern.

## Daily Loop

1. Pull or load campaign metrics.
2. Answer the 5 daily questions.
3. Identify winners, losers, and fatigue.
4. Auto-pause only obvious waste.
5. Stage bigger changes for approval.
6. Send or display the daily brief.
7. Log every decision.

## Safe Automatic Actions

Auto-pause can run without approval when:

- CPA is greater than the target CPA multiplied by the configured high-CPA multiplier.
- Spend is over the configured zero-conversion threshold and conversions are zero.

Default settings:

```text
META_TARGET_CPA=50
META_AUTO_PAUSE_ZERO_CONVERSION_SPEND=50
META_AUTO_PAUSE_HIGH_CPA_MULTIPLIER=3
```

## Approval Required

The agent stages these actions:

- Budget changes over `META_APPROVAL_REQUIRED_OVER_PCT`.
- Resuming paused campaigns/ad sets.
- New campaign creation.

Pending approvals are stored in:

```text
dashboard/data/pending_approvals.json
```

Approve from the command line:

```bash
./scripts/list-pending.sh
./scripts/approve.sh approval_id_here
```

## Con Supervision Vs Piloto Automatico

Con supervision:

- Reads real Meta performance when the account is connected.
- Generates reports.
- Creates pending approvals.
- Does not execute Meta mutations by itself.

Piloto automatico:

- Reads the same real insights.
- Executes auto-pauses only inside the buyer's configured rules.
- Executes approved budget/resume actions.

## Audit Trail

Important logs:

```text
dashboard/data/actions.json
output/daily_brief_YYYY-MM-DD.json
output/fatigue-log.md
```
