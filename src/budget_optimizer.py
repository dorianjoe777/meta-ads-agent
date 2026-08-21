#!/usr/bin/env python3
"""
Meta Ads Budget Optimization Logic
Optimizes campaign budgets based on performance metrics.
"""
import json
import math
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class OptimizationStrategy(Enum):
    """Budget optimization strategies."""
    EVEN_DISTRIBUTION = "even_distribution"
    PERFORMANCE_BASED = "performance_based"
    CONVERSION_FOCUSED = "conversion_focused"
    COST_PER_RESULT = "cost_per_result"
    MANUAL = "manual"


@dataclass
class PerformanceMetrics:
    """Campaign performance metrics."""
    spend: float
    impressions: int
    clicks: int
    conversions: int
    revenue: float
    cost_per_result: float
    roas: float  # Return on Ad Spend
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'PerformanceMetrics':
        """Create metrics from dictionary."""
        return cls(
            spend=data.get("spend", 0),
            impressions=data.get("impressions", 0),
            clicks=data.get("clicks", 0),
            conversions=data.get("conversions", 0),
            revenue=data.get("revenue", 0),
            cost_per_result=data.get("cost_per_result", 0),
            roas=data.get("roas", 0)
        )


@dataclass
class BudgetRecommendation:
    """Budget optimization recommendation."""
    campaign_id: str
    current_budget: float
    recommended_budget: float
    confidence: float  # 0-100
    strategy: OptimizationStrategy
    reasoning: str
    metrics: PerformanceMetrics
    projected_results: Dict


class BudgetOptimizer:
    """
    Optimizes Meta Ads campaign budgets based on performance.
    """
    
    def __init__(self, min_budget: float = 10.0, max_budget: float = 10000.0):
        """
        Initialize budget optimizer.
        
        Args:
            min_budget: Minimum daily budget per campaign
            max_budget: Maximum daily budget per campaign
        """
        self.min_budget = min_budget
        self.max_budget = max_budget
        
        # Performance thresholds
        self.target_roas = 2.0  # Target 2x return on ad spend
        self.target_cpa = 50.0  # Target cost per acquisition
        self.min_conversions_per_day = 5
        
    def calculate_optimal_budget(self, 
                                 metrics: PerformanceMetrics,
                                 current_budget: float,
                                 strategy: OptimizationStrategy = OptimizationStrategy.PERFORMANCE_BASED) -> BudgetRecommendation:
        """
        Calculate optimal budget based on performance metrics.
        
        Args:
            metrics: Current performance metrics
            current_budget: Current daily budget
            strategy: Optimization strategy
            
        Returns:
            Budget recommendation
        """
        if strategy == OptimizationStrategy.EVEN_DISTRIBUTION:
            return self._optimize_even_distribution(metrics, current_budget)
        elif strategy == OptimizationStrategy.PERFORMANCE_BASED:
            return self._optimize_performance_based(metrics, current_budget)
        elif strategy == OptimizationStrategy.CONVERSION_FOCUSED:
            return self._optimize_conversion_focused(metrics, current_budget)
        elif strategy == OptimizationStrategy.COST_PER_RESULT:
            return self._optimize_cost_per_result(metrics, current_budget)
        else:
            return self._optimize_manual(metrics, current_budget)
    
    def _optimize_even_distribution(self, 
                                   metrics: PerformanceMetrics,
                                   current_budget: float) -> BudgetRecommendation:
        """Even distribution strategy."""
        recommended_budget = current_budget
        
        return BudgetRecommendation(
            campaign_id="unknown",
            current_budget=current_budget,
            recommended_budget=recommended_budget,
            confidence=50.0,
            strategy=OptimizationStrategy.EVEN_DISTRIBUTION,
            reasoning="Even distribution maintains stable performance",
            metrics=metrics,
            projected_results={
                "daily_spend": recommended_budget,
                "expected_conversions": metrics.conversions,
                "expected_roas": metrics.roas
            }
        )
    
    def _optimize_performance_based(self,
                                   metrics: PerformanceMetrics,
                                   current_budget: float) -> BudgetRecommendation:
        """Performance-based optimization."""
        # Calculate performance score (0-100)
        performance_score = self._calculate_performance_score(metrics)
        
        # Adjust budget based on performance
        if performance_score >= 80:
            # High performance - increase budget
            multiplier = 1.2  # +20%
            reasoning = "High performance detected - increasing budget"
        elif performance_score >= 60:
            # Good performance - maintain budget
            multiplier = 1.0
            reasoning = "Good performance - maintaining current budget"
        elif performance_score >= 40:
            # Average performance - slight decrease
            multiplier = 0.9
            reasoning = "Average performance - slight budget reduction"
        else:
            # Poor performance - significant decrease
            multiplier = 0.7
            reasoning = "Low performance - reducing budget significantly"
        
        recommended_budget = current_budget * multiplier
        recommended_budget = self._clamp_budget(recommended_budget)
        
        return BudgetRecommendation(
            campaign_id="unknown",
            current_budget=current_budget,
            recommended_budget=recommended_budget,
            confidence=abs(performance_score - 50),
            strategy=OptimizationStrategy.PERFORMANCE_BASED,
            reasoning=reasoning,
            metrics=metrics,
            projected_results={
                "daily_spend": recommended_budget,
                "performance_score": performance_score,
                "expected_roas": metrics.roas * multiplier if metrics.roas > 0 else 0
            }
        )
    
    def _optimize_conversion_focused(self,
                                    metrics: PerformanceMetrics,
                                    current_budget: float) -> BudgetRecommendation:
        """Conversion-focused optimization."""
        # Calculate conversion efficiency
        if metrics.conversions > 0:
            cpa = metrics.spend / metrics.conversions
            efficiency = self.target_cpa / cpa if cpa > 0 else 0
        else:
            efficiency = 0
        
        # Adjust budget based on conversion efficiency
        if efficiency >= 1.5:
            # Very efficient - increase budget aggressively
            multiplier = 1.5
            reasoning = "Highly efficient conversions - increasing budget aggressively"
        elif efficiency >= 1.0:
            # Efficient - increase budget moderately
            multiplier = 1.2
            reasoning = "Efficient conversions - increasing budget moderately"
        elif efficiency >= 0.7:
            # Break-even - maintain budget
            multiplier = 1.0
            reasoning = "Break-even efficiency - maintaining budget"
        else:
            # Inefficient - decrease budget
            multiplier = 0.7
            reasoning = "Inefficient conversions - decreasing budget"
        
        recommended_budget = current_budget * multiplier
        recommended_budget = self._clamp_budget(recommended_budget)
        
        return BudgetRecommendation(
            campaign_id="unknown",
            current_budget=current_budget,
            recommended_budget=recommended_budget,
            confidence=min(efficiency * 100, 100),
            strategy=OptimizationStrategy.CONVERSION_FOCUSED,
            reasoning=reasoning,
            metrics=metrics,
            projected_results={
                "daily_spend": recommended_budget,
                "efficiency": efficiency,
                "expected_conversions": metrics.conversions * multiplier
            }
        )
    
    def _optimize_cost_per_result(self,
                                 metrics: PerformanceMetrics,
                                 current_budget: float) -> BudgetRecommendation:
        """Cost per result optimization."""
        # Use cost per result as primary metric
        cpr = metrics.cost_per_result if metrics.cost_per_result > 0 else float('inf')
        
        # Calculate adjustment based on cost per result
        if cpr <= self.target_cpa * 0.8:
            # Very low cost per result - increase budget
            multiplier = 1.3
            reasoning = f"Low cost per result (${cpr:.2f}) - increasing budget"
        elif cpr <= self.target_cpa:
            # At target cost per result - maintain budget
            multiplier = 1.0
            reasoning = f"At target cost per result (${cpr:.2f}) - maintaining budget"
        elif cpr <= self.target_cpa * 1.2:
            # Slightly above target - slight decrease
            multiplier = 0.9
            reasoning = f"Slightly above target cost per result (${cpr:.2f}) - slight decrease"
        else:
            # Significantly above target - decrease budget
            multiplier = 0.7
            reasoning = f"High cost per result (${cpr:.2f}) - decreasing budget"
        
        recommended_budget = current_budget * multiplier
        recommended_budget = self._clamp_budget(recommended_budget)
        
        return BudgetRecommendation(
            campaign_id="unknown",
            current_budget=current_budget,
            recommended_budget=recommended_budget,
            confidence=100 - min((cpr / self.target_cpa) * 100, 100),
            strategy=OptimizationStrategy.COST_PER_RESULT,
            reasoning=reasoning,
            metrics=metrics,
            projected_results={
                "daily_spend": recommended_budget,
                "cost_per_result": cpr,
                "projected_cpr": cpr * (1 / multiplier) if multiplier > 0 else cpr
            }
        )
    
    def _optimize_manual(self,
                        metrics: PerformanceMetrics,
                        current_budget: float) -> BudgetRecommendation:
        """Manual optimization (no automatic changes)."""
        return BudgetRecommendation(
            campaign_id="unknown",
            current_budget=current_budget,
            recommended_budget=current_budget,
            confidence=100.0,
            strategy=OptimizationStrategy.MANUAL,
            reasoning="Manual optimization mode - no automatic changes",
            metrics=metrics,
            projected_results={
                "daily_spend": current_budget,
                "note": "Manual optimization required"
            }
        )
    
    def _calculate_performance_score(self, metrics: PerformanceMetrics) -> float:
        """
        Calculate overall performance score (0-100).
        
        Factors:
        - ROAS (40%)
        - Conversion rate (30%)
        - Cost efficiency (20%)
        - Engagement (10%)
        """
        score = 0
        
        # ROAS component (40%)
        if metrics.roas > 0:
            roas_score = min(metrics.roas / self.target_roas * 40, 40)
            score += roas_score
        
        # Conversion component (30%)
        if metrics.impressions > 0:
            conversion_rate = metrics.conversions / metrics.impressions * 100
            conversion_score = min(conversion_rate * 10, 30)  # Scale to 30
            score += conversion_score
        
        # Cost efficiency component (20%)
        if metrics.cost_per_result > 0 and metrics.conversions > 0:
            cpa_score = max(0, (self.target_cpa / metrics.cost_per_result) * 20)
            score += min(cpa_score, 20)
        
        # Engagement component (10%)
        if metrics.impressions > 0:
            ctr = (metrics.clicks / metrics.impressions) * 100
            ctr_score = min(ctr * 5, 10)  # Scale to 10
            score += ctr_score
        
        return min(score, 100)
    
    def _clamp_budget(self, budget: float) -> float:
        """Clamp budget to min/max limits."""
        return max(self.min_budget, min(budget, self.max_budget))
    
    def optimize_campaign_budgets(self,
                                 campaigns: List[Dict],
                                 strategy: OptimizationStrategy = OptimizationStrategy.PERFORMANCE_BASED) -> List[BudgetRecommendation]:
        """
        Optimize budgets for multiple campaigns.
        
        Args:
            campaigns: List of campaign dictionaries with metrics
            strategy: Optimization strategy to apply
            
        Returns:
            List of budget recommendations
        """
        recommendations = []
        
        for campaign in campaigns:
            # Extract metrics
            metrics_data = campaign.get("metrics", {})
            metrics = PerformanceMetrics.from_dict(metrics_data)
            
            # Get current budget
            current_budget = campaign.get("budget", {}).get("daily", 100.0)
            
            # Calculate recommendation
            recommendation = self.calculate_optimal_budget(
                metrics, current_budget, strategy
            )
            recommendation.campaign_id = campaign.get("id", campaign.get("name", "unknown"))
            
            recommendations.append(recommendation)
        
        return recommendations
    
    def generate_optimization_report(self,
                                    recommendations: List[BudgetRecommendation]) -> Dict:
        """Generate a comprehensive optimization report."""
        total_current = sum(r.current_budget for r in recommendations)
        total_recommended = sum(r.recommended_budget for r in recommendations)
        total_change = total_recommended - total_current
        percent_change = (total_change / total_current * 100) if total_current > 0 else 0
        
        return {
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_campaigns": len(recommendations),
                "total_current_budget": total_current,
                "total_recommended_budget": total_recommended,
                "total_change": total_change,
                "percent_change": percent_change
            },
            "recommendations": [
                {
                    "campaign_id": r.campaign_id,
                    "current_budget": r.current_budget,
                    "recommended_budget": r.recommended_budget,
                    "change": r.recommended_budget - r.current_budget,
                    "confidence": r.confidence,
                    "strategy": r.strategy.value,
                    "reasoning": r.reasoning,
                    "projected_results": r.projected_results
                }
                for r in recommendations
            ]
        }


def main():
    """Demo: Optimize sample campaigns."""
    from budget_optimizer import BudgetOptimizer, OptimizationStrategy
    
    optimizer = BudgetOptimizer()
    
    # Sample campaign data
    campaigns = [
        {
            "id": "campaign_001",
            "name": "Q2 Sales Campaign",
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
            "id": "campaign_002",
            "name": "Lead Generation Campaign",
            "budget": {"daily": 50.0, "total": 1500.0},
            "metrics": {
                "spend": 150.0,
                "impressions": 10000,
                "clicks": 300,
                "conversions": 30,
                "revenue": 0.0,  # Leads don't have direct revenue
                "cost_per_result": 5.0,
                "roas": 0.0
            }
        }
    ]
    
    # Optimize with different strategies
    print("=" * 70)
    print("META ADS BUDGET OPTIMIZATION REPORT")
    print("=" * 70)
    
    for strategy in [OptimizationStrategy.PERFORMANCE_BASED, 
                     OptimizationStrategy.CONVERSION_FOCUSED,
                     OptimizationStrategy.COST_PER_RESULT]:
        print(f"\n📋 Strategy: {strategy.value.upper()}")
        print("-" * 70)
        
        recommendations = optimizer.optimize_campaign_budgets(campaigns, strategy)
        report = optimizer.generate_optimization_report(recommendations)
        
        print(f"Total Current Budget: ${report['summary']['total_current_budget']:.2f}")
        print(f"Total Recommended: ${report['summary']['total_recommended_budget']:.2f}")
        print(f"Change: ${report['summary']['total_change']:.2f} ({report['summary']['percent_change']:.1f}%)")
        print()
        
        for rec in report['recommendations']:
            change = rec['change']
            change_symbol = "↑" if change > 0 else "↓" if change < 0 else "="
            print(f"  {rec['campaign_id']}: ${rec['current_budget']:.2f} → ${rec['recommended_budget']:.2f} {change_symbol} ${abs(change):.2f}")
            print(f"    Confidence: {rec['confidence']:.1f}% | {rec['reasoning']}")
            print()


if __name__ == "__main__":
    main()
