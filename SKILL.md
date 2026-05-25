# Meta Ads Agent — OpenClaw Skill

> Autonomous Meta Ads management via social-flow CLI + OpenClaw cron.

## Architecture

```
OpenClaw Agent (cron @ 7am)
  → meta-ads skill (daily checks, actions)
  → ad-creative-monitor (fatigue tracking)
  → budget-optimizer (spend efficiency)
  → social-flow CLI
  → Meta Marketing API
```

## The 5 Daily Questions

1. **Am I on track?** — Spend pacing vs daily budget
2. **What's running?** — All active campaigns, status, spend
3. **How's performance?** — 7-day ROAS, CPA, CPL, CTR by campaign
4. **Who's winning/losing?** — Ad-level data, ranked best to worst
5. **Any fatigue?** — CTR trends, frequency, CPC creep

## Commands Reference

```bash
# Auth
social auth login
social auth status
social auth permissions

# Accounts
social marketing accounts
social marketing set-default-account act_XXXX

# Insights (daily questions)
social marketing insights --preset last_7d --level campaign
social marketing insights --preset last_7d --level ad
social marketing status

# Actions
social marketing pause ad AD_ID
social marketing pause adset ADSET_ID
social marketing resume ad AD_ID
social marketing set-budget adset ADSET_ID --daily-budget 5000

# Reports
social marketing insights --preset last_30d --level campaign --format table
```

## Decision Rules

### Auto-Pause (no approval needed)
- CPA > 3x target for 48+ hours
- Spend > $50 with 0 conversions
- Notify Dorian after pausing

### Approval Required
- Budget shifts > 20%
- Resuming paused ads
- New campaign creation

### Fatigue Triggers
- Frequency > 3.0
- CTR decline > 20% week-over-week
- CPC increase > 30% without seasonality
- Log observations to `output/fatigue-log.md`

## Cron Setup

```bash
# Daily morning brief at 7am Colombia time
0 7 * * * /path/to/meta-ads-daily.sh
```

## Workflow

1. Cron fires at 7am
2. Agent runs 5 questions via social-flow
3. Compiles brief with actions taken + recommendations
4. Sends to Telegram
5. Dorian replies "approved" or asks questions
6. Agent executes approved actions

## File Structure

```
meta-ads-agent/
├── SKILL.md           # This file
├── docs/              # Documentation
├── skills/            # Sub-skills (creative monitor, budget optimizer)
├── output/            # Daily reports, fatigue logs
└── scripts/           # Automation scripts
```

---
*Based on: https://www.bigplayers.co/p/this-openclaw-agent-runs-your-meta-ads*
