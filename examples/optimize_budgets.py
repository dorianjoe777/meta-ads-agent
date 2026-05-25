#!/usr/bin/env python3
"""
Example: Optimize campaign budgets for Meta Ads.
"""
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from budget_optimizer import BudgetOptimizer, OptimizationStrategy


def main():
    """Optimize sample campaign budgets."""
    optimizer = BudgetOptimizer(min_budget=10.0, max_budget=10000.0)
    
    # Sample campaign data (replace with real data from Meta Ads API)
    campaigns = [
        {
            "id": "camp_q2-sales-20260323",
            "name": "Q2 Sales Campaign - May 2026",
            "budget": {"daily": 100.0, "total": 3000.0},
            "metrics": {
                "spend": 300.0,
                "impressions": 15000,
                "clicks": 450,
                "conversions": 15,
                "revenue": 600.0,
                "cost_per_result": 20.0,
                "roas": 2.0
            }
        },
        {
            "id": "camp_lead-gen-20260323",
            "name": "Lead Generation Campaign",
            "budget": {"daily": 50.0, "total": 1500.0},
            "metrics": {
                "spend": 150.0,
                "impressions": 10000,
                "clicks": 300,
                "conversions": 30,
                "revenue": 0.0,
                "cost_per_result": 5.0,
                "roas": 0.0
            }
        }
    ]
    
    print("=" * 70)
    print("META ADS BUDGET OPTIMIZATION REPORT")
    print("=" * 70)
    print()
    
    # Optimize with PERFORMANCE_BASED strategy
    recommendations = optimizer.optimize_campaign_budgets(
        campaigns, 
        strategy=OptimizationStrategy.PERFORMANCE_BASED
    )
    
    report = optimizer.generate_optimization_report(recommendations)
    
    print(f"📊 Generated: {report['generated_at']}")
    print()
    print("SUMMARY")
    print(f"  Total Campaigns: {report['summary']['total_campaigns']}")
    print(f"  Current Budget: ${report['summary']['total_current_budget']:.2f}/day")
    print(f"  Recommended: ${report['summary']['total_recommended_budget']:.2f}/day")
    print(f"  Change: ${report['summary']['total_change']:.2f} ({report['summary']['percent_change']:+.1f}%)")
    print()
    
    print("RECOMMENDATIONS")
    print("-" * 70)
    
    for rec in report['recommendations']:
        change = rec['change']
        change_pct = (change / rec['current_budget'] * 100) if rec['current_budget'] > 0 else 0
        change_symbol = "↑" if change > 0 else "↓" if change < 0 else "="
        
        print(f"  📋 {rec['campaign_id']}")
        print(f"     ${rec['current_budget']:.2f} → ${rec['recommended_budget']:.2f} {change_symbol} ${abs(change):.2f} ({change_pct:+.1f}%)")
        print(f"     Confidence: {rec['confidence']:.1f}% | Strategy: {rec['strategy']}")
        print(f"     Reasoning: {rec['reasoning']}")
        print(f"     Projected: {rec['projected_results']}")
        print()
    
    # Save recommendations to file
    output_path = Path(__file__).parent / "output" / "budget_optimization.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    
    print(f"✅ Report saved to: {output_path}")


if __name__ == "__main__":
    main()
