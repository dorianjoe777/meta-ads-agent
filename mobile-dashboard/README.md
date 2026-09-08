# Mobile operator dashboard

This separate Vercel project serves the operator interface at
`https://dashboard.uboost.lat`. It keeps the control-plane UI available from a
phone while the database, pool credentials and lifecycle operations remain on
the Contabo VPS.

The Vercel function in `api/operator/[...path].js` forwards only the operator
API routes to `https://origin-dashboard.uboost.lat`. Vercel environment
variables hold the fixed HTTPS origin and a private proxy key. Caddy checks
that key and forwards the request to the loopback-only operator service.

Deploy from this directory with the Vercel project
`admira-mobile-operator-dashboard` in the `dorianx` scope. The production
domain is `dashboard.uboost.lat`; keep `admiraia.uboost.lat` reserved for the
license API.

The wildcard rewrite in `vercel.json` is required: this is a plain Node
function, so the `[...path]` filename alone does not route multi-segment paths
such as `gemini/status`, `sponsorship/status`, or client lifecycle actions.
Both the SSH tunnel and HTTPS gateway use the same VPS service and password.
Pool metadata and assignments live in VPS PostgreSQL; the actual Gemini keys
remain in private files under `/etc/admira/gemini-pool` on that VPS.

After deployment, run `node tests/smoke.mjs` with `OPERATOR_TEST_PASSWORD` set
securely in the environment. Optionally set `OPERATOR_TEST_URL` to the
deployment URL before assigning `dashboard.uboost.lat` to it. The smoke check
verifies login, every inventory, nested routes, authentication and logout
without modifying clients or printing secrets. After assigning the custom
domain, rerun the check against that domain as well.
