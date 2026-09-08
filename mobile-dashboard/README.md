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
