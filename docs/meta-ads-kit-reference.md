# Reference Assessment: TheMattBerman/meta-ads-kit

Reference: https://github.com/TheMattBerman/meta-ads-kit

## Summary

This project should be treated as an important upstream/reference implementation for the info-product version of this Meta Ads Agent.

It should not replace the standalone positioning. The stronger commercial direction remains: a self-hosted local/VPS Meta Ads operator inspired by OpenClaw-style workflows, packaged so buyers do not need to understand or depend on OpenClaw.

## What It Adds To The Bar

The reference kit defines a fuller loop than this project currently implements:

- Monitor campaign performance.
- Detect fatigue.
- Find winners and bleeders.
- Recommend budget shifts.
- Generate fresh ad copy matched to image creatives.
- Upload images/copy to Meta through Graph API.
- Ask for approval before actions.

This exposes two major gaps in this project:

1. Creative generation and upload are not implemented.
2. Live Meta insights are not fully normalized into dashboard metrics yet.

## Useful Patterns To Adopt

- `ad-config.json` benchmark configuration:
  - account id/name
  - target CPA
  - target ROAS
  - max frequency
  - minimum CTR
  - max CPC
  - reporting timezone
- Standalone report runner commands:
  - daily check
  - overview
  - campaigns
  - bleeders
  - winners
  - fatigue
  - budget recommendations
- Clear permissions model:
  - `ads_read` and `read_insights` for monitoring
  - `ads_management` for actions
- Creative upload chain:
  - validate copy and image
  - upload image to Meta
  - create `asset_feed_spec`
  - create ad as paused first
- Read-only by default, approval for spend/status changes.

## What Not To Copy Directly

- Do not lead with OpenClaw as the product dependency.
- Do not ship only shell scripts as the customer experience.
- Do not rely on an agent framework for basic setup/status/approval UX.
- Do not claim upload/live execution until the Graph API path is tested.

## Product Decision

Use `meta-ads-kit` as a technical reference and benchmark, not as the brand identity.

The customer-facing product should remain:

> A standalone self-hosted Meta Ads operator for local PC or VPS installs, with dry-run mode, live mode, dashboard approvals, and explicit Meta permissions.

## Updated Build Priorities

1. Add an `ad-config.json` benchmark file and load it into the dashboard/agent.
2. Normalize live `social-cli` insights into `dashboard/data/metrics.json`.
3. Add dashboard setup status:
   - social-cli installed
   - auth status
   - default ad account
   - mode
   - Telegram config
   - cron status
4. Add approval detail/reject flow.
5. Add creative refresh module:
   - copy variants
   - image validation
   - dry-run payload preview
6. Add Meta upload module:
   - image upload
   - `asset_feed_spec`
   - create ads as paused
7. Add release packaging with attribution if any MIT-licensed code is incorporated.

