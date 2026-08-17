# Meta Ads Campaign Templates

This directory contains reusable templates for Meta Ads campaigns, ad sets, and ads.

## Structure

```
templates/
├── campaigns/           # Campaign-level templates
│   ├── awareness/
│   ├── consideration/
│   └── conversion/
├── ad-sets/             # Ad set-level templates
│   ├── audience-targets/
│   └── placement-configs/
├── ads/                 # Ad-level templates
│   ├── creative-formats/
│   └── copy-variations/
└── schemas/             # JSON schemas for validation
```

## Usage

```bash
# Generate campaign from template
meta-ads generate campaign --type awareness --name "Q2 Awareness" --budget 5000

# Validate campaign structure
meta-ads validate --schema campaign.json --input campaign-config.json
```

## Template Types

### Campaign Templates
- **Awareness**: Top-of-funnel, broad targeting, brand awareness
- **Consideration**: Middle-funnel, engagement, website traffic
- **Conversion**: Bottom-funnel, purchase/sales, lead generation

### Ad Set Templates
- **Lookalike Audiences**: 1%, 3%, 5% LAL
- **Interest Targeting**: Interest-based audiences
- **Retargeting**: Website visitors, video viewers, cart abandoners

### Ad Templates
- **Single Image**: Static image ads
- **Video**: In-stream, stories, reels
- **Carousel**: Multi-product showcase
- **Collection**: Shoppable catalog ads

## Best Practices

1. **Start with goal**: Choose campaign template based on business objective
2. **Layer audiences**: Combine 2-3 audience types per ad set
3. **Test creatives**: Minimum 3 ad variations per ad set
4. **Budget allocation**: 70/20/10 rule for conversion/consideration/awareness
