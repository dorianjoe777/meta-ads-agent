#!/usr/bin/env python3
"""
Meta Ads Campaign Creation Script
Generates campaign configurations from templates for Meta Ads API.
"""
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import sys


class CampaignCreator:
    """Creates Meta Ads campaigns from templates."""
    
    def __init__(self, templates_dir: str = None):
        """
        Initialize campaign creator.
        
        Args:
            templates_dir: Path to templates directory
        """
        if templates_dir is None:
            templates_dir = str(Path(__file__).parent / "templates")
        
        self.templates_dir = Path(templates_dir)
        self.campaign_templates = self.templates_dir / "campaigns"
        self.ad_set_templates = self.templates_dir / "campaigns" / "conversion"
        
    def load_template(self, template_type: str, subtype: str = "conversion") -> Dict:
        """Load a template from the templates directory."""
        template_path = self.campaign_templates / subtype / f"{template_type}-template.json"
        
        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")
        
        with open(template_path, "r") as f:
            return json.load(f)
    
    def create_campaign_config(self, 
                               name: str,
                               objective: str,
                               budget_daily: float,
                               budget_total: float,
                               start_date: str = None,
                               end_date: str = None,
                               pixel_id: Optional[str] = None,
                               ad_sets: List[Dict] = None,
                               create_default_ad_set: bool = True) -> Dict:
        """
        Create a campaign configuration.
        
        Args:
            name: Campaign name
            objective: Campaign objective (CONVERSIONS, LEADS, PURCHASES)
            budget_daily: Daily budget in USD
            budget_total: Total budget in USD
            start_date: Campaign start date (YYYY-MM-DD)
            end_date: Campaign end date (YYYY-MM-DD)
            pixel_id: Meta Pixel ID for tracking
            ad_sets: List of ad set configurations
            
        Returns:
            Campaign configuration dictionary
        """
        # Set default dates
        if start_date is None:
            start_date = datetime.now().strftime("%Y-%m-%d")
        
        if end_date is None:
            end_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        
        # Load campaign template
        campaign_template = self.load_template("campaign")
        
        # Create default ad set if none provided
        if ad_sets is None and create_default_ad_set:
            default_ad_set = self.create_ad_set_config(
                name=f"{name} - Ad Set 1",
                targeting=self.create_audience_targeting(),
                budget=budget_total / 3
            )
            ad_sets = [default_ad_set]
        
        # Create campaign config
        campaign_config = {
            "name": name,
            "objective": objective,
            "budget": {
                "daily": budget_daily,
                "total": budget_total
            },
            "start_date": start_date,
            "end_date": end_date,
            "pixel_id": pixel_id,
            "ad_sets": ad_sets or []
        }
        
        return campaign_config
    
    def create_ad_set_config(self,
                             name: str,
                             targeting: Dict,
                             budget: float,
                             bid_strategy: str = "LOWEST_COST_WITHOUT_CAP") -> Dict:
        """
        Create an ad set configuration.
        
        Args:
            name: Ad set name
            targeting: Targeting configuration
            budget: Ad set budget in USD
            bid_strategy: Bidding strategy
            
        Returns:
            Ad set configuration dictionary
        """
        return {
            "name": name,
            "targeting": targeting,
            "budget": budget,
            "bid_strategy": bid_strategy
        }
    
    def create_audience_targeting(self,
                                  locations: List[str] = None,
                                  age_min: int = 18,
                                  age_max: int = 65,
                                  interests: List[str] = None,
                                  lookalike_percentage: Optional[int] = None,
                                  retargeting: Optional[Dict] = None) -> Dict:
        """
        Create audience targeting configuration.
        
        Args:
            locations: List of country/location codes
            age_min: Minimum age
            age_max: Maximum age
            interests: List of interest keywords
            lookalike_percentage: Lookalike audience percentage (1, 3, 5)
            retargeting: Retargeting configuration
            
        Returns:
            Targeting configuration dictionary
        """
        targeting = {
            "locations": locations or ["US"],
            "age_range": {"min": age_min, "max": age_max}
        }
        
        if interests:
            targeting["interests"] = interests
        
        if lookalike_percentage:
            targeting["lookalike"] = {"percentage": lookalike_percentage}
        
        if retargeting:
            targeting["retargeting"] = retargeting
        
        return targeting
    
    def validate_campaign(self, campaign_config: Dict) -> bool:
        """
        Validate campaign configuration against template.
        
        Args:
            campaign_config: Campaign configuration to validate
            
        Returns:
            True if valid, False otherwise
        """
        try:
            # Load schema
            schema = self.load_template("campaign")
            
            # Basic validation
            required_fields = ["name", "objective", "budget", "start_date", "ad_sets"]
            for field in required_fields:
                if field not in campaign_config:
                    print(f"❌ Missing required field: {field}")
                    return False
            
            # Validate objective
            valid_objectives = ["CONVERSIONS", "LEADS", "PURCHASES"]
            if campaign_config["objective"] not in valid_objectives:
                print(f"❌ Invalid objective: {campaign_config['objective']}")
                return False
            
            # Validate budget
            budget = campaign_config.get("budget", {})
            if not isinstance(budget.get("daily"), (int, float)) or budget.get("daily") < 10:
                print(f"❌ Invalid daily budget: {budget.get('daily')}")
                return False
            
            if not isinstance(budget.get("total"), (int, float)) or budget.get("total") < 100:
                print(f"❌ Invalid total budget: {budget.get('total')}")
                return False
            
            # Validate dates
            try:
                datetime.strptime(campaign_config["start_date"], "%Y-%m-%d")
                if "end_date" in campaign_config:
                    datetime.strptime(campaign_config["end_date"], "%Y-%m-%d")
            except ValueError:
                print("❌ Invalid date format. Use YYYY-MM-DD")
                return False
            
            # Validate ad sets
            if not campaign_config.get("ad_sets"):
                print("❌ Campaign must have at least one ad set")
                return False
            
            if len(campaign_config["ad_sets"]) > 10:
                print("❌ Maximum 10 ad sets per campaign")
                return False
            
            print("✅ Campaign configuration is valid")
            return True
            
        except Exception as e:
            print(f"❌ Validation error: {e}")
            return False
    
    def generate_campaign_id(self, campaign_config: Dict) -> str:
        """
        Generate a campaign ID based on configuration.
        
        Args:
            campaign_config: Campaign configuration
            
        Returns:
            Generated campaign ID
        """
        name_clean = campaign_config["name"].lower().replace(" ", "-").replace("_", "-")
        date_str = datetime.now().strftime("%Y%m%d")
        return f"camp_{name_clean}_{date_str}"
    
    def save_campaign(self, campaign_config: Dict, output_path: str) -> str:
        """
        Save campaign configuration to JSON file.
        
        Args:
            campaign_config: Campaign configuration
            output_path: Output file path
            
        Returns:
            Path to saved file
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w") as f:
            json.dump(campaign_config, f, indent=2)
        
        print(f"✅ Campaign saved to: {output_path}")
        return str(output_path)
    
    def create_conversion_campaign(self,
                                   name: str,
                                   daily_budget: float,
                                   total_budget: float,
                                   pixel_id: str,
                                   audience: Dict,
                                   creative_variations: int = 3) -> Dict:
        """
        Create a conversion-focused campaign (for purchases, leads, signups).
        
        Args:
            name: Campaign name
            daily_budget: Daily budget in USD
            total_budget: Total budget in USD
            pixel_id: Meta Pixel ID
            audience: Audience targeting configuration
            creative_variations: Number of ad creative variations
            
        Returns:
            Complete campaign configuration
        """
        # Create ad set with targeting
        ad_set = self.create_ad_set_config(
            name=f"{name} - Ad Set 1",
            targeting=audience,
            budget=total_budget / 3  # Distribute budget across ad sets
        )
        
        # Create campaign
        campaign = self.create_campaign_config(
            name=name,
            objective="PURCHASES",
            budget_daily=daily_budget,
            budget_total=total_budget,
            pixel_id=pixel_id,
            ad_sets=[ad_set]
        )
        
        return campaign


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Meta Ads Campaign Creator",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Create campaign command
    create_parser = subparsers.add_parser("create", help="Create a new campaign")
    create_parser.add_argument("--name", required=True, help="Campaign name")
    create_parser.add_argument("--objective", choices=["CONVERSIONS", "LEADS", "PURCHASES"],
                               default="PURCHASES", help="Campaign objective")
    create_parser.add_argument("--daily-budget", type=float, required=True,
                               help="Daily budget in USD")
    create_parser.add_argument("--total-budget", type=float, required=True,
                               help="Total budget in USD")
    create_parser.add_argument("--pixel-id", help="Meta Pixel ID")
    create_parser.add_argument("--output", "-o", default="output/campaign.json",
                               help="Output file path")
    
    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate campaign config")
    validate_parser.add_argument("--input", "-i", required=True, help="Input JSON file")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    creator = CampaignCreator()
    
    if args.command == "create":
        # Create campaign
        campaign = creator.create_campaign_config(
            name=args.name,
            objective=args.objective,
            budget_daily=args.daily_budget,
            budget_total=args.total_budget,
            pixel_id=args.pixel_id
        )
        
        # Validate
        if creator.validate_campaign(campaign):
            # Generate campaign ID
            campaign_id = creator.generate_campaign_id(campaign)
            campaign["id"] = campaign_id
            
            # Save
            creator.save_campaign(campaign, args.output)
            print(f"\n📋 Campaign ID: {campaign_id}")
    
    elif args.command == "validate":
        # Load and validate
        try:
            with open(args.input, "r") as f:
                campaign_config = json.load(f)
            
            creator.validate_campaign(campaign_config)
        except FileNotFoundError:
            print(f"❌ File not found: {args.input}")
        except json.JSONDecodeError:
            print(f"❌ Invalid JSON in: {args.input}")


if __name__ == "__main__":
    main()
