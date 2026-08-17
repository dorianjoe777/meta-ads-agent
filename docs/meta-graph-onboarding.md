# Meta Graph onboarding

Admira IA connects to Meta through the buyer's own Meta app/token and executes Marketing API actions directly with Meta Graph.

Buyer-facing flow:

1. Open Meta Business and create or use a private Meta app/system user.
2. Generate a token with the ad permissions needed for the buyer's own ad account.
3. Paste that token in the dashboard setup.
4. Admira uses Graph API to list ad accounts, discover Pages/Instagram assets, read insights, and execute approved actions.

Required environment values for live execution:

```bash
META_AD_ACCOUNT_ID=act_123456789
META_ACCESS_TOKEN=your_meta_system_user_or_user_token
META_GRAPH_API_VERSION=v24.0
```

Notes:

- `META_CONNECTOR` is no longer a buyer setting. The product uses Graph API directly.
- A missing local CLI binary must never block campaign creation.
- Support/debug messages should say “Meta Graph” or “Meta connection”, not refer to a local CLI connector.
- If Meta rejects a request, surface the real Graph error and the action that failed.
