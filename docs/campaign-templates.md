# Meta Ads Campaign Template Structure

This document outlines the campaign template structure for the Meta Ads Agent.

## Overview

The campaign template system provides reusable, validated templates for creating Meta Ads campaigns, ad sets, and ads. Templates follow JSON Schema validation to ensure consistency and prevent configuration errors.

## Directory Structure

```
meta-ads-agent/
└── src/
    └── templates/
        ├── campaigns/           # Campaign-level templates
        │   ├── awareness/       # Top-of-funnel templates
        │   ├── consideration/   # Middle-funnel templates
        │   └── conversion/      # Bottom-funnel templates
        ├── ads/                 # Ad-level templates
        │   └── creative-templates.json
        ├── schemas/             # JSON schemas for validation
        └── examples/            # Example campaign configurations
```

## Template Categories

### Campaign Templates

#### 1. Conversion Campaigns (Bottom Funnel)
**Objective**: Purchases, Leads, Signups
**Use Case**: Direct response, sales, lead generation
**Example**: `campaigns/conversion/campaign-template.json`

**Structure**:
- Campaign name and objective
- Budget (daily and total)
- Start/end dates
- Pixel ID for tracking
- Ad set array (1-10 ad sets)

#### 2. Consideration Campaigns (Middle Funnel)
**Objective**: Website traffic, engagement, app installs
**Use Case**: Building audience, warming leads
**Example**: `campaigns/consideration/campaign-template.json`

**Structure**:
- Campaign name and objective
- Budget allocation
- Ad sets focused on engagement

#### 3. Awareness Campaigns (Top Funnel)
**Objective**: Reach, brand awareness
**Use Case**: New product launches, brand building
**Example**: `campaigns/awareness/campaign-template.json`

**Structure**:
- Campaign name and objective
- Broad targeting
- High reach optimization

### Ad Set Templates

#### Audience Types
1. **Lookalike Audiences**
   - 1%, 3%, 5%, 10% LAL based on source audiences
   - Best for: Conversions, quality leads

2. **Interest Targeting**
   - Specific interests and behaviors
   - Best for: Consideration campaigns

3. **Retargeting Audiences**
   - Website visitors, cart abandoners, video viewers
   - Best for: Conversion campaigns

#### Placement Configurations
- **Automatic Placements**: Meta optimizes across placements
- **Manual Placements**: Specific control over where ads appear
  - Facebook Feed
  - Instagram Feed
  - Instagram Stories
  - Facebook Stories
  - Messenger
  - Audience Network

### Ad Templates

#### Creative Formats
1. **Single Image**
   - Recommended: 1080x1080 or 1200x628
   - Best for: Simple messaging, product showcases

2. **Video**
   - Recommended: 1080x1080 or 1080x1920
   - Max duration: 60 seconds (optimal: 15-30s)
   - Best for: Storytelling, demonstrations

3. **Carousel**
   - 2-10 cards per ad
   - 1080x1080 per card
   - Best for: Product catalogs, multiple features

4. **Collection**
   - Hero image + product catalog
   - Best for: E-commerce, catalog sales

## Using Templates

### Generate Campaign from Template

```bash
# Command structure (example)
meta-ads generate campaign \
  --template conversion \
  --name "Q2 Sales Campaign" \
  --daily-budget 100 \
  --total-budget 3000 \
  --start-date 2026-05-01 \
  --pixel-id 123456789012345
```

### Validate Campaign Configuration

```bash
# Validate against schema
meta-ads validate \
  --schema conversion \
  --input campaign-config.json
```

### Create Ad Set from Template

```bash
meta-ads generate adset \
  --template lookalike-1pct \
  --name "LAL 1% - Purchasers" \
  --budget 50 \
  --audience-source "Purchasers - Last 180 Days"
```

## Validation Rules

### Campaign-Level Validation
- Minimum 1 ad set required
- Maximum 10 ad sets per campaign
- Budget must be positive numbers
- Dates must be in YYYY-MM-DD format
- Pixel ID must be numeric string

### Ad Set-Level Validation
- Minimum budget: $5/day
- Audience must include locations and age range
- Bid strategy must match optimization goal
- Placements must be valid Meta placements

### Ad-Level Validation
- Image size must meet minimum specs
- Video duration must be within limits
- Text must not exceed character limits
- All assets must be approved by Meta

## Best Practices

### Campaign Structure
1. **Start with goal**: Choose template based on business objective
2. **Budget allocation**: Follow 70/20/10 rule (conversion/consideration/awareness)
3. **Test and learn**: Minimum 3 ad variations per ad set
4. **Audience layering**: Combine 2-3 audience types per ad set

### Template Selection
- **Cold Traffic**: Use awareness or consideration templates
- **Warm Traffic**: Use consideration or conversion templates
- **Hot Traffic**: Use conversion templates with retargeting

### Optimization
- Review performance daily for first 7 days
- Pause underperforming ads after 3 days with minimal spend
- Scale winning ads by increasing budget 20% per day
- Rotate creative every 2-3 weeks to prevent fatigue

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Campaign not delivering | Check pixel firing, audience size, bid amount |
| High CPA | Review creative, test new audiences, adjust bids |
| Low CTR | Test new creatives, improve ad copy, refine targeting |
| Ad rejected | Review Meta policies, remove prohibited content |

## Related Documentation

- [Meta Ads Agent SKILL.md](../SKILL.md) - Main skill documentation
- [Campaign Decision Rules](../SKILL.md#decision-rules) - Auto-pause and approval rules
- [Meta Graph campaign controls](../SKILL.md#commands-reference) - action reference
