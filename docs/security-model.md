# Security Model

This product is designed to run as a self-hosted local/VPS operator. The safe default is local-only, supervised, approval-based, and password-protected for dashboard actions.

## Default Protections

- `META_ADS_AGENT_MODE=dry-run` is shown to buyers as `Con supervision`.
- `LIVE_ACTIONS_ENABLED=false` blocks live mutations even if live mode is enabled.
- A cloud-validated license is required for buyer live features.
- `DASHBOARD_HOST=127.0.0.1` keeps the dashboard local by default.
- `REQUIRE_DASHBOARD_TOKEN=true` requires the dashboard password for protected routes.
- `ALLOW_PUBLIC_DASHBOARD=false` refuses public dashboard binds unless explicitly changed.
- `LAN_ACCESS_ENABLED=false` keeps same-Wi-Fi phone access off until the buyer turns it on from Configuracion.
- `.env`, `dashboard/data`, `output`, and `logs` are made private by the installer.
- Action logs redact tokens, API keys, secrets, and passwords before writing records.

## Dashboard Password

The installer leaves the dashboard password empty. The buyer creates their own dashboard password at the end of onboarding.

The dashboard shows an unlock screen the first time the user performs a protected action. If the user chooses "Remember this device", the password is stored in browser local storage on that device. The password is never sent in the dashboard payload.

Protected routes include approvals, campaign creation, budget actions, creative refresh generation, upload staging, upload execution, CSV export, and report generation.

## Phone On Same Wi-Fi

For local installs, the dashboard starts as "this computer only". If the buyer wants to review it from a phone, they can open Configuracion and turn on `Ver desde mi telefono`.

The dashboard then shows a LAN link like:

```text
http://192.168.1.50:7871/
```

The phone must be connected to the same Wi-Fi or local network. The dashboard password still protects private data and actions. Turning phone access off returns native installs to `DASHBOARD_HOST=127.0.0.1` and `ALLOW_PUBLIC_DASHBOARD=false`.

Docker and VPS installs have different network requirements. Docker may need the container port reachable from the host; VPS/cloud access should use the DigitalOcean access gate, firewall, and HTTPS path instead of the same-Wi-Fi LAN option.

## Piloto Automatico Checklist

Before allowing live actions:

```bash
python3 src/daily_agent.py status
```

Then set:

```bash
META_ADS_AGENT_MODE=live
LIVE_ACTIONS_ENABLED=true
```

Keep `LIVE_ACTIONS_ENABLED=false` while connecting accounts, testing approvals, or teaching the buyer the workflow. It is the final switch that permits Meta mutations.

## VPS Guidance

Do not expose the Python dashboard directly to the public internet.

Recommended VPS setup:

- Keep `DASHBOARD_HOST=127.0.0.1`.
- Access through SSH tunnel, VPN, Tailscale, or a reverse proxy with HTTPS and authentication.
- Keep `ALLOW_PUBLIC_DASHBOARD=false` unless the buyer understands the risk.
- Use firewall rules to block direct access to the dashboard port.

Only set `ALLOW_PUBLIC_DASHBOARD=true` behind HTTPS, a firewall, and an additional authentication layer.

## What This Does Not Guarantee

This layer reduces common self-hosting risks, but it is not a substitute for server hardening. Buyers still need to protect their VPS login, keep the machine updated, avoid sharing `.env`, and rotate passwords/keys if a device is compromised.
