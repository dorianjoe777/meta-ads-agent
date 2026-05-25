# Campaign Creation Script

This document describes the campaign creation script for Meta Ads Agent.

## Overview

The campaign creation script (`campaign_creator.py`) provides a Python API and CLI for generating Meta Ads campaign configurations from templates.

## Features

- ✅ Campaign template validation
- ✅ Audience targeting configuration
- ✅ Budget management (daily and total)
- ✅ Date range handling
- ✅ Multiple ad set support
- ✅ Campaign ID generation
- ✅ JSON output for Meta Ads API

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
