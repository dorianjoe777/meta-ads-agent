# Setup Status Checklist

The dashboard includes a `Setup` tab that reports whether the local/VPS install is ready for demo viewing, real Meta monitoring, creative generation, campaign creation, and upload execution.

The same data is available from:

```bash
python3 src/daily_agent.py status
```

## Status Levels

- `OK`: configured or available.
- `Check`: not required yet, but worth reviewing before buyer launch.
- `Blocked`: required before real execution can work.

## What It Checks

Files:

- `.env`
- `ad-config.json`
- metrics cache
- dashboard script
- daily runner script

Runtime:

- control level
- social-cli installation
- latest daily report
- latest action log

Security:

- dashboard bind host
- dashboard password
- live-action switch
- `.env` permissions
- dashboard data, output, and log directory permissions

Meta live requirements:

- `META_AD_ACCOUNT_ID`
- `META_ACCESS_TOKEN`
- page ID
- landing page URL

Creative generation:

- creative refresh enabled
- image generation mode
- Gemini/Nano Banana key
- creative drafts index

Upload readiness:

- upload staging index
- latest upload payload
- missing requirement count

Scheduler:

- cron setup script
- systemd setup script
- logs directory

## Intended Use

For customers:

1. Install locally.
2. Open dashboard.
3. Go to `Setup`.
4. Fix blocked items from top to bottom.
5. Confirm `Datos reales de Meta`.
6. Enable Piloto automatico only when the checklist makes the risk visible.

For support:

Ask for a screenshot or JSON export of the `Setup` tab before debugging live execution.
