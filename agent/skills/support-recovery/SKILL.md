---
name: support-recovery
description: Handle Admira IA support and recovery situations: rate limits, Codex/Image disconnected, DigitalOcean access/update issues, Meta Graph errors, gateway restarts, memory cleanup, and buyer-safe explanations.
---

# Support and Recovery Skill

Use this skill when something fails, times out, rate-limits, disconnects, or needs support explanation.

## Buyer-safe explanation

- Explain what happened in simple words first.
- Do not show scary raw logs unless support diagnostics are explicitly requested.
- Never blame the buyer when the issue is technical.
- If a retry is safe, say what will be retried and what changed.

## Common recovery paths

- Rate limit: explain the likely reset/wait window when available and suggest a lighter model if appropriate.
- Codex/Image disconnected: separate text model health from Image 2/Codex auth.
- DigitalOcean access: mention past-due billing/write-permission restrictions when the firewall/access update fails with provider permission errors.
- Meta errors: name the exact failing step in buyer language, then keep the approval/action ready for retry after the backend fix.
- Update issues: prefer a proper release/update path over manually patching a buyer install.

### NVIDIA NIM model-pool recovery

- A hosted NIM key can expose several model pools. The runtime may try **one** alternate model only for a model-specific timeout, 5xx, overload, or empty response, and only when that model came from a recent authenticated NVIDIA `/models` catalog.
- Never rotate models under the same NIM key after `429`, quota/rate-limit, authentication, authorization, or billing errors. Those failures can be shared by the key; retrying every model would amplify the outage.
- If no fresh live catalog or independent provider exists, say that no verified fallback is available. Never invent a model ID or promise that another NIM endpoint will work.

## Continuity

After cleanup, restart, or update, use `session-continuity` before saying hello or asking onboarding questions again.
