# Meta Upload Staging

This module converts a creative refresh manifest into upload-ready Meta Graph API payloads.

It is intentionally a staging module first. It only executes a prepared upload after an explicit approved action.

## Why Staging First

Meta upload has higher risk than generating creative drafts:

- It touches ad account assets.
- It requires page/ad account IDs. An existing ad set ID is only required when placing a new ad inside an already-created Meta ad set.
- It must upload image files before creating ad creatives.
- It should create ads as `PAUSED`.
- It must remain approval-gated.

The current module builds the payloads, validates missing requirements, and stores them for review.

## Required Config

Edit `ad-config.json`:

```json
{
  "creative": {
    "destination": {
      "page_id": "YOUR_PAGE_ID",
      "instagram_actor_id": "OPTIONAL_INSTAGRAM_ACTOR_ID",
      "default_adset_id": "OPTIONAL_EXISTING_ADSET_ID",
      "url": "https://your-landing-page.com"
    }
  }
}
```

Recommended connector:

```bash
META_CONNECTOR=social_cli
META_AD_ACCOUNT_ID=act_123456789
```

Advanced direct Graph fallback:

```bash
META_CONNECTOR=graph_api
META_AD_ACCOUNT_ID=act_123456789
META_ACCESS_TOKEN=your_meta_system_user_or_user_token
META_GRAPH_API_VERSION=v24.0
```

## Stage Upload Payload

From a manifest path:

```bash
python3 src/daily_agent.py stage-upload output/creatives/creative_x/manifest.json --variant-id v1 --ratios 1:1
```

From a refresh id:

```bash
python3 src/daily_agent.py stage-upload creative_camp_002_20260511_212858 --variant-id v1 --ratios 1:1
```

The staged payload is saved under:

```text
output/uploads/
```

## What Gets Built

- Image upload plan:
  - endpoint: `/act_xxx/adimages`
  - file path
  - expected image hash result
- Ad creative payload:
  - endpoint: `/act_xxx/adcreatives`
  - `object_story_spec`
  - `asset_feed_spec`
  - headline/body/CTA
- Ad creation payload:
  - endpoint: `/act_xxx/ads`
  - target ad set
  - creative id placeholder
  - `status: PAUSED`

## Approval Behavior

If required IDs and image assets exist, staging creates a pending approval item:

```text
dashboard/data/pending_approvals.json
```

If anything is missing, the upload payload is marked `blocked` and no approval is created.

## Current Boundary

Staging prepares a reviewable payload without executing anything. After explicit approval and license validation, the execution layer may upload images, create Meta creatives, and create ads. An active final status needs its own explicit confirmation.

## Execute Upload Payload

Validation without an approved action:

```bash
python3 src/daily_agent.py execute-upload output/uploads/upload_x/payload.json
```

In the internal `META_ADS_AGENT_MODE=dry-run` value, shown in the dashboard as `Con supervision`, running this direct command validates the payload and logs the planned sequence without calling Meta. An action explicitly approved from the dashboard or Telegram can execute under supervision when its license and required data are valid.

Automatic execution in `Piloto automatico` requires:

- `META_ADS_AGENT_MODE=live`
- `LIVE_ACTIONS_ENABLED=true`
- `META_ACCESS_TOKEN`
- `META_AD_ACCOUNT_ID`
- page id in `ad-config.json`
- existing ad set id in `ad-config.json`, only if using an existing ad set
- generated image assets on disk

Live execution sequence:

1. Upload image files to `/act_xxx/adimages`.
2. Capture returned image hashes.
3. Create ad creative at `/act_xxx/adcreatives`.
4. Create ad at `/act_xxx/ads` with `status: PAUSED`.
5. Log every response with tokens redacted.

The approval flow executes `creative_upload` pending items through this same executor.
