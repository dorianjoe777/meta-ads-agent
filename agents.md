# Agents

## Session Startup

1. Read `identity.md`, `soul.md`, and this file.
2. Load the kanban project `1f637025e8623953` from the central kanban database.
3. Review active items first: blocked, in progress, review, todo, then backlog.
4. Review recent updates and any linked files before changing project files.
5. Save important decisions and session notes back to the dashboard conversation history or kanban updates.

## Project Boundaries

- Work inside: `/Users/macminim1/.openclaw/workspace/projects/meta-ads-agent`
- Do not modify unrelated projects unless Dorian explicitly asks.
- Scripts and data should stay under the project folder when possible.
- Prefer existing project conventions over new structure.

## Handling Scripts And Data

- Inspect scripts before running them.
- Prefer dry runs or read-only commands first when the effect is unclear.
- Keep credentials out of commits and markdown files.
- Record important outputs, generated artifacts, and manual steps in kanban updates.

## Admira IA Production License API

The buyer-facing domain `admiraia.uboost.lat` belongs only to this Vercel
target:

- service root: `seller/vercel-license-api`
- project: `miro-ai-license-api`
- project ID: `prj_7EHTqtYTj4V1wxUeFvU5h4gzKqLX`
- organization ID: `team_1dW3qJzfquT0ONCFYEw2GRE1`
- Vercel scope: `dorianx`

Never run a bare `vercel deploy`, `vercel --prod`, or `vercel link` for this
service. Never deploy it from the repository root. Root-level `.vercel`
metadata belongs to another project and is not evidence of the license API
target.

All production deployments and deployment checks for this service must use:

```bash
./seller/vercel-license-api/scripts/deploy-production-safe.sh
```

For a read-only verification without a deployment:

```bash
./seller/vercel-license-api/scripts/deploy-production-safe.sh --check
```

The script reconstructs the ignored local Vercel link from the tracked target
manifest, refuses identity mismatches, runs tests, and verifies the public
domain and health endpoint. A successful preview or auxiliary deployment is
not a successful production release.

Preserve unrelated dirty worktree changes and stage only files belonging to
the current task.
