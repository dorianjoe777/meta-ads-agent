# Campaign Creation Script

This document describes the campaign creation script for Meta Ads Agent.

## Overview

The campaign creation script (`campaign_creator.py`) provides a Python API and CLI for generating Meta Ads campaign configurations from templates.

## Runtime contracts for Hermes

Live conversational campaign creation separates conversation from payload compilation. Each destination MCP publishes one small input, `brief_markdown`, for the latest buyer-approved campaign:

- `create_whatsapp_campaign`
- `create_lead_form_campaign`
- `create_website_campaign`
- `create_messaging_campaign`
- `create_app_campaign`
- `create_on_meta_campaign`

Gemini/Hermes gathers requirements and writes them naturally; it does not assemble nested campaign JSON. The MCP persists the latest Markdown privately at `dashboard/data/campaign-compiler/latest-campaign.md`, then invokes `gpt-5.6-terra` through Codex CLI using the buyer's connected ChatGPT/Codex subscription and the isolated `CODEX_HOME = HERMES_HOME/codex-auth` session. Terra receives the destination compiler contract and a strict JSON output schema.

Terra output is candidate data, never authority or approval. The bridge performs a separate deterministic pass before Meta: it canonicalizes supported aliases/nesting, rejects ambiguous or missing fields, validates the destination contract, verifies creative files, and enforces server-side currency/budget and PAUSED-creation safeguards. After the writes, exact Graph read-back validates geography, placements and IDs. A compiler timeout, unavailable Terra model, disconnected Codex subscription, missing fact, or contract mismatch fails closed without creating Meta objects.

Tool visibility is also model-independent. Before every Gemini, Codex/Terra, or
legacy provider request, Admira classifies the latest buyer turn locally. When
the destination is explicit it exposes exactly one campaign creator plus the
small read-only context/preflight and durable-memory set. For example, a clear
WhatsApp creation turn exposes `create_whatsapp_campaign` but none of the
website, form, app, Messenger, or generic Meta campaign creators. If the buyer
has not chosen a destination yet, the creator options remain available long
enough for the agent to ask the clarifying question. This routing never calls a
second model and never changes the destination MCP's JSON Schema.

For the current Gemini canary, the only text-inference fallback is the buyer's connected ChatGPT/Codex subscription using `openai-codex` with `gpt-5.6-terra`. NVIDIA/NIM providers and aliases must not appear in the generated Hermes configuration or fallback chain. Codex image generation continues to use the same isolated `CODEX_HOME = HERMES_HOME/codex-auth` session.

## Features

- ✅ Campaign template validation
- ✅ Audience targeting configuration
- ✅ Budget management (daily and total)
- ✅ Date range handling
- ✅ Multiple ad set support
- ✅ Campaign ID generation
- ✅ JSON output for Meta Ads API

## Native creative execution

When a staged campaign is materialized in Meta, Admira IA uses the primary Live Ads app for every supported format:

- Website sales and traffic: inline `link_data` with the exact destination.
- Awareness and post engagement: inline `photo_data` or `video_data` without a fake URL.
- Video: direct upload to the ad account, then inline `video_data`.
- Instant forms: inline CTA with the verified `lead_gen_form_id`; no external landing URL is required.
- WhatsApp, Messenger, and Instagram Direct: native messaging destination and approved starter/welcome text.
- App promotion: native `OUTCOME_APP_PROMOTION`/`APP_INSTALLS` with the real Meta `application_id`, App Store/Google Play `object_store_url`, and destination `APP`.

The product does not create dark/unpublished Page posts as campaign intermediates. `object_story_id` is used only when the buyer explicitly chooses an existing Page post. Publicación directa remains an organic-post capability and an optional ads-authorized credential fallback.

## Native Instant Form workflow

Hermes must use these tools in this order:

1. `mcp_admira_list_lead_forms` reads the active Page first and avoids duplicate names.
2. `mcp_admira_create_lead_form` creates the form through `/{page_id}/leadgen_forms`, then reads the Page edge again and returns a verified `lead_gen_form_id`. The active selected Page is automatic; `page_id` is only an override. Required buyer content is `name`, `questions`, and `privacy_policy_url`.
3. `mcp_admira_create_lead_form_campaign` receives that verified ID for the native inline creative and creates the complete stack PAUSED without another approval.

Creating a form does not create a campaign or spend money. `mcp_admira_stage_lead_form` is only the manual Ads Manager fallback after Meta returns an actual Page-token permission, application-capability, or Lead Ads Terms blocker. It must not replace `create_lead_form` preemptively.

Operational checks when the agent says it cannot create forms:

- Inspect the MCP description first. `create_lead_form` must describe direct creation, not a compatibility/manual alias.
- Confirm the handler routes to `create_lead_form_creation`, not `stage_lead_form_creation`.
- Run a read-only `list_lead_forms` call with no `page_id`; it must resolve the active Page and reach the `leadgen_forms` edge.
- Ensure the Page token can be resolved and has the required Page/Ads permissions. A publishing-only token must not mask a capable primary Ads token.
- A privacy link without a scheme is normalized to HTTPS when it is a valid public host.
- For Meta Lead Ads Terms error `1815089`, stop retries and send `https://www.facebook.com/ads/leadgen/tos`.
- Never claim success from the POST alone. The returned form ID must appear in the follow-up read before it is used in a campaign.

## Usage

### Python API

```python
from campaign_creator import CampaignCreator

creator = CampaignCreator()

# Create audience targeting
audience = creator.create_audience_targeting(
    locations=["US", "CA", "GB"],
    age_min=25,
    age_max=54,
    interests=["e-commerce", "online shopping"]
)

# Create conversion campaign
campaign = creator.create_conversion_campaign(
    name="Q2 Sales Campaign",
    daily_budget=100.0,
    total_budget=3000.0,
    pixel_id="123456789012345",
    audience=audience
)

# Validate and save
if creator.validate_campaign(campaign):
    campaign_id = creator.generate_campaign_id(campaign)
    creator.save_campaign(campaign, "output/campaign.json")
```

### CLI Usage

```bash
# Create a campaign
python3 src/cli.py campaign create \
  --name "Q2 Campaign" \
  --daily-budget 100 \
  --total-budget 3000 \
  --pixel-id 123456789012345 \
  --output output/q2_campaign.json

# Validate a campaign
python3 src/cli.py campaign validate --input output/q2_campaign.json

# Create audience targeting
python3 src/cli.py audience create \
  --locations "US,CA,GB" \
  --age-min 25 \
  --age-max 54 \
  --interests "e-commerce,online shopping"
```

## Campaign Structure

### Conversion Campaign

```json
{
  "id": "camp_q2-sales-20260323",
  "name": "Q2 Sales Campaign",
  "objective": "PURCHASES",
  "budget": {
    "daily": 100.0,
    "total": 3000.0
  },
  "start_date": "2026-03-23",
  "end_date": "2026-04-22",
  "pixel_id": "123456789012345",
  "ad_sets": [
    {
      "name": "Q2 Sales Campaign - Ad Set 1",
      "targeting": {
        "locations": ["US", "CA", "GB"],
        "age_range": {"min": 25, "max": 54},
        "interests": ["e-commerce", "online shopping"]
      },
      "budget": 1000.0,
      "bid_strategy": "LOWEST_COST_WITHOUT_CAP"
    }
  ]
}
```

## Audience Targeting

### Location Targeting

```python
audience = creator.create_audience_targeting(
    locations=["US", "CA", "GB"]
)
```

### Age Range

```python
audience = creator.create_audience_targeting(
    age_min=25,
    age_max=54
)
```

### Interest Targeting

```python
audience = creator.create_audience_targeting(
    interests=["e-commerce", "technology", "business"]
)
```

### Lookalike Audiences

```python
audience = creator.create_audience_targeting(
    lookalike_percentage=3  # 3% lookalike audience
)
```

### Retargeting

```python
audience = creator.create_audience_targeting(
    retargeting={
        "website_visitors": True,
        "video_viewers": True,
        "cart_abandoners": True
    }
)
```

## Budget Rules

- **Daily budget**: Minimum $10 per day
- **Total budget**: Minimum $100 per campaign
- **Ad set budget**: Distributed automatically from total budget
- **Bid strategy**: Default is LOWEST_COST_WITHOUT_CAP

## Validation Rules

✅ **Valid campaign must have:**
- Name (string)
- Objective (CONVERSIONS, LEADS, or PURCHASES)
- Budget with daily and total amounts
- Start date in YYYY-MM-DD format
- At least one ad set
- Maximum 10 ad sets

❌ **Common validation errors:**
- Daily budget < $10
- Total budget < $100
- Invalid date format
- No ad sets defined
- Too many ad sets (>10)

## Output Files

Campaigns are saved as JSON files that can be:
1. Uploaded to Meta Ads API
2. Reviewed and modified manually
3. Used with other Meta Ads tools
4. Stored in version control

## Examples

See `examples/create_q2_campaign.py` for a complete example of creating a Q2 conversion campaign.
