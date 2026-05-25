# Creative Refresh Engine

The creative layer is designed as a draft-and-approval workflow first.

It uses the ad account benchmarks and brand settings from `ad-config.json` to identify campaigns that need fresh creative, generate copy variants, and prepare Nano Banana image prompts.

## What It Does In v1

- Detects campaigns with fatigue or poor performance.
- Generates 3 copy/image directions per campaign by default.
- Produces image prompts for:
  - `1:1`
  - `4:5`
  - `9:16`
- Saves a manifest under `output/creatives/`.
- Shows recent refresh drafts in the dashboard.
- Can optionally call Nano Banana through Gemini API when explicitly enabled.

## What It Does Not Do Automatically

- It does not upload generated assets, create Meta creatives, or create ads without an explicit approval step.
- New ads are created paused unless an approved campaign creation explicitly confirms an `ACTIVE` final status.

Those steps remain approval-gated and visibly logged.

## Configuration

Copy the config files if the installer has not already done it:

```bash
cp .env.example .env
cp ad-config.example.json ad-config.json
```

Set brand and benchmark values in:

```text
ad-config.json
```

Creative environment settings:

```bash
CREATIVE_REFRESH_ENABLED=true
CREATIVE_AUTO_GENERATE_ON_DAILY=true
CREATIVE_PROVIDER=nano-banana
CREATIVE_IMAGE_MODE=dry-run
GEMINI_API_KEY=
NANO_BANANA_MODEL=gemini-2.5-flash-image
CREATIVE_VARIANTS_PER_CAMPAIGN=3
```

`CREATIVE_IMAGE_MODE` is an internal provider control. Buyer-facing safety is explained as `Con supervision` and approvals.

## Draft Usage

Generate refresh drafts for all matching campaigns:

```bash
python3 src/daily_agent.py creative-refresh
```

Generate for one campaign:

```bash
python3 src/daily_agent.py creative-refresh --campaign-id camp_004
```

Generate for every campaign:

```bash
python3 src/daily_agent.py creative-refresh --all
```

The output manifest includes:

- campaign performance context
- ad copy variants
- Nano Banana prompts
- aspect ratios
- upload policy

## Live Nano Banana Generation

Google’s official Nano Banana API uses Gemini image models. The baseline model documented by Google is:

```text
gemini-2.5-flash-image
```

To enable image generation:

```bash
CREATIVE_IMAGE_MODE=live
GEMINI_API_KEY=your_google_ai_studio_key
```

Then run:

```bash
python3 src/daily_agent.py creative-refresh
```

Generated image files are saved next to the manifest under:

```text
output/creatives/
```

## Recommended Product Flow

1. Agent detects fatigue or weak performance.
2. Agent generates creative refresh drafts.
3. User reviews copy and image directions in the dashboard.
4. User approves selected concepts.
5. The approved upload flow creates Meta ads as paused by default.
6. User reviews in Meta or dashboard before launch.

## Stage For Meta Upload

After reviewing a manifest, build an upload-ready payload:

```bash
python3 src/daily_agent.py stage-upload output/creatives/creative_x/manifest.json --variant-id v1 --ratios 1:1
```

See [meta-upload.md](meta-upload.md).
