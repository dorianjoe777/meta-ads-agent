# Stable Canary Snapshot

This repository snapshot captures the code and product configuration that was
running successfully on the DigitalOcean canary on 2026-08-20.

- Version: `v1.0.242-canary`
- Snapshot purpose: stable baseline for the Admira IA Meta Ads agent
- Verified flows: creative generation, paused campaign creation, and campaign editing

The snapshot intentionally excludes runtime and customer-specific state:

- environment files and credentials;
- backups and historical copies;
- logs and generated output;
- `dashboard/data/` runtime memory, account bindings, tokens, and action history.

Use `.env.example` as the starting point for a new installation. The canary's
live account connections and buyer memory must be restored through the normal
OAuth and Admira memory tools, never committed to this repository.
