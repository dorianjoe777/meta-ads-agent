#!/usr/bin/env python3
"""
Meta Ads Agent CLI
Command-line interface for managing Meta Ads campaigns.
"""
import argparse
import json
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from campaign_creator import CampaignCreator
from budget_optimizer import BudgetOptimizer, OptimizationStrategy


def main():
    """CLI entry point for Meta Ads Agent."""
    parser = argparse.ArgumentParser(
        description="Meta Ads Agent - Campaign Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s campaign create --name "Q2 Campaign" --daily-budget 100 --total-budget 3000
  %(prog)s campaign validate --input output/campaign.json
  %(prog)s audience create --locations US,CA --age-min 25 --age-max 54
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command category")
    
    # Campaign commands
    campaign_parser = subparsers.add_parser("campaign", help="Manage campaigns")
    campaign_subparsers = campaign_parser.add_subparsers(dest="campaign_command")
    
    # Create campaign
    create_parser = campaign_subparsers.add_parser("create", help="Create a campaign")
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
    
    # Validate campaign
    validate_parser = campaign_subparsers.add_parser("validate", help="Validate campaign")
    validate_parser.add_argument("--input", "-i", required=True, help="Input JSON file")
    
    # Budget commands
    budget_parser = subparsers.add_parser("budget", help="Manage budgets")
    budget_subparsers = budget_parser.add_subparsers(dest="budget_command")
    
    optimize_parser = budget_subparsers.add_parser("optimize", help="Optimize campaign budgets")
    optimize_parser.add_argument("--strategy", 
                                  choices=["performance", "conversion", "cost", "even"],
                                  default="performance",
                                  help="Optimization strategy")
    optimize_parser.add_argument("--campaigns", required=True,
                                  help="JSON file with campaign data")
    optimize_parser.add_argument("--output", "-o", default="output/optimization.json",
                                  help="Output file path")
    
    # Audience commands
    audience_parser = subparsers.add_parser("audience", help="Manage audiences")
    audience_subparsers = audience_parser.add_subparsers(dest="audience_command")
    
    # Create audience
    audience_create_parser = audience_subparsers.add_parser("create", help="Create audience targeting")
    audience_create_parser.add_argument("--locations", help="Comma-separated locations")
    audience_create_parser.add_argument("--age-min", type=int, default=18, help="Minimum age")
    audience_create_parser.add_argument("--age-max", type=int, default=65, help="Maximum age")
    audience_create_parser.add_argument("--interests", help="Comma-separated interests")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    creator = CampaignCreator()
    
    if args.command == "campaign":
        if args.campaign_command == "create":
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
        
        elif args.campaign_command == "validate":
            # Load and validate
            try:
                with open(args.input, "r") as f:
                    campaign_config = json.load(f)
                
                creator.validate_campaign(campaign_config)
            except FileNotFoundError:
                print(f"❌ File not found: {args.input}")
            except json.JSONDecodeError:
                print(f"❌ Invalid JSON in: {args.input}")
    
    elif args.command == "budget":
        if args.budget_command == "optimize":
            # Load campaign data
            try:
                with open(args.campaigns, "r") as f:
                    campaigns = json.load(f)
            except FileNotFoundError:
                print(f"❌ Campaign file not found: {args.campaigns}")
                return
            except json.JSONDecodeError:
                print(f"❌ Invalid JSON in: {args.campaigns}")
                return
            
            # Map strategy
            strategy_map = {
                "performance": OptimizationStrategy.PERFORMANCE_BASED,
                "conversion": OptimizationStrategy.CONVERSION_FOCUSED,
                "cost": OptimizationStrategy.COST_PER_RESULT,
                "even": OptimizationStrategy.EVEN_DISTRIBUTION
            }
            
            strategy = strategy_map.get(args.strategy, OptimizationStrategy.PERFORMANCE_BASED)
            
            # Optimize budgets
            optimizer = BudgetOptimizer()
            recommendations = optimizer.optimize_campaign_budgets(campaigns, strategy)
            report = optimizer.generate_optimization_report(recommendations)
            
            # Print report
            print(f"\n📊 Budget Optimization Report")
            print(f"   Strategy: {args.strategy}")
            print(f"   Current Total: ${report['summary']['total_current_budget']:.2f}/day")
            print(f"   Recommended Total: ${report['summary']['total_recommended_budget']:.2f}/day")
            print(f"   Change: ${report['summary']['total_change']:.2f} ({report['summary']['percent_change']:+.1f}%)")
            
            # Save to file
            with open(args.output, "w") as f:
                json.dump(report, f, indent=2)
            
            print(f"\n✅ Report saved to: {args.output}")
    
    elif args.command == "audience":
        if args.audience_command == "create":
            # Parse locations
            locations = None
            if args.locations:
                locations = [loc.strip() for loc in args.locations.split(",")]
            
            # Parse interests
            interests = None
            if args.interests:
                interests = [interest.strip() for interest in args.interests.split(",")]
            
            # Create audience
            audience = creator.create_audience_targeting(
                locations=locations,
                age_min=args.age_min,
                age_max=args.age_max,
                interests=interests
            )
            
            print(json.dumps(audience, indent=2))


if __name__ == "__main__":
    main()
