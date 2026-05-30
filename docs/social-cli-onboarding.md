# Social-CLI Onboarding

This is the recommended buyer path.

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

This means most buyers should not start by creating a Facebook Developer app. They should start by connecting through `social`.

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

## Why This Is The Default

The direct Graph API path requires app/token setup and more explanation. `social-cli` already provides:

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
