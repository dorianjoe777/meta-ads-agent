# Social-CLI Onboarding

This is an advanced/historical connector note, not the current default buyer path.

The current buyer-facing path shows two options:

1. Recommended: create a stable Meta Business connection with a System User.
2. Faster start: use Graph API Explorer and renew later if needed.

Graph API Explorer can be useful when the buyer wants to start quickly or does not control the Business Portfolio owner yet. Its token can expire, so the dashboard copy should explain renewal reminders around 60 days and the option to switch to a stable key later from Setup. `social-cli` remains useful as a connector layer and fallback, but buyer docs should not present terminal auth as the main beginner flow.

The installed `social` CLI supports Meta authentication and Marketing API commands:

```bash
social setup
social auth login
social auth status
social marketing accounts
social marketing set-default-account act_XXXX
social marketing insights
social marketing upload-image
social marketing create-creative
social marketing create-ad
```

Most buyers should not start by running terminal auth commands. They should follow the guided Meta connection in the dashboard: stable key recommended, quick key accepted for faster starts.

## Buyer Flow

1. Install the product:

```bash
./scripts/install-local.sh
./scripts/run-dashboard.sh
```

2. Run social-cli setup:

```bash
social setup
```

or:

```bash
social onboard
```

3. Authenticate:

```bash
social auth login
social auth status
```

The CLI supports manual token or OAuth-style flows depending on its configuration.

4. List ad accounts:

```bash
social marketing accounts
```

5. Set the default ad account:

```bash
social marketing set-default-account act_XXXX
```

6. Add the account id to `.env`:

```bash
META_CONNECTOR=social_cli
META_AD_ACCOUNT_ID=act_XXXX
```

7. Check the dashboard `Setup` tab.

## Why This Is Not The Default Anymore

The terminal flow is harder for beginner buyers and can still depend on session/token behavior. The System User path is a better match for a self-hosted product because the buyer owns the Meta Business connection and can revoke it directly from Meta.

`social-cli` still provides useful lower-level operations:

- onboarding
- auth status
- ad account listing
- insights
- image upload
- creative creation
- paused ad creation
- pause/resume/budget commands

So `social-cli` is the lowest-friction live connector for buyers.

## Advanced Fallback

Use direct Graph API only when:

- social-cli is unavailable
- you need server-side execution independent of social-cli
- you have a Meta app or system-user token already

Advanced `.env` values:

```bash
META_CONNECTOR=graph_api
META_ACCESS_TOKEN=...
META_AD_ACCOUNT_ID=act_XXXX
META_GRAPH_API_VERSION=v24.0
```
