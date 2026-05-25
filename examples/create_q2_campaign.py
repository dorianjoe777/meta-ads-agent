#!/usr/bin/env python3
"""
Example: Create a Q2 conversion campaign for Meta Ads.
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from campaign_creator import CampaignCreator


def main():
    """Create a Q2 conversion campaign example."""
    creator = CampaignCreator()
    
    # Define audience targeting
    audience = creator.create_audience_targeting(
        locations=["US", "CA", "GB"],
        age_min=25,
        age_max=54,
        interests=["e-commerce", "online shopping", "technology"],
        lookalike_percentage=3  # 3% lookalike audience
    )
    
    # Create conversion campaign
    campaign = creator.create_conversion_campaign(
        name="Q2 Sales Campaign - May 2026",
        daily_budget=100.0,
        total_budget=3000.0,
        pixel_id="123456789012345",  # Replace with actual Pixel ID
        audience=audience,
        creative_variations=3
    )
    
    # Validate
    if creator.validate_campaign(campaign):
        # Generate ID
        campaign_id = creator.generate_campaign_id(campaign)
        campaign["id"] = campaign_id
        
        # Save to file
        output_path = Path(__file__).parent / "output" / "q2_sales_campaign.json"
        creator.save_campaign(campaign, output_path)
        
        print(f"\n✅ Campaign created successfully!")
        print(f"   Campaign ID: {campaign_id}")
        print(f"   Name: {campaign['name']}")
        print(f"   Objective: {campaign['objective']}")
        print(f"   Budget: ${campaign['budget']['daily']}/day (Total: ${campaign['budget']['total']})")
        print(f"   Ad Sets: {len(campaign['ad_sets'])}")
        print(f"\n📁 Saved to: {output_path}")


if __name__ == "__main__":
    main()
