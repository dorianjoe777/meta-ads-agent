#!/usr/bin/env python3
"""
Scaling Logic for Meta Ads
Automatically scales winning ads while maintaining profitability.
"""
import json
import math
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum


class ScalingStatus(Enum):
    """Scaling status."""
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    MAX_REACHED = "max_reached"
    UNDERPERFORMING = "underperforming"


class ScalingStrategy(Enum):
    """Scaling strategy."""
    GRADUAL = "gradual"  # Increase by percentage each period
    AGGRESSIVE = "aggressive"  # Increase by larger percentage
    CONSERVATIVE = "conservative"  # Smaller increases, more careful
    DYNAMIC = "dynamic"  # Adjust based on performance


@dataclass
class ScalingRule:
    """Rule for scaling an ad or campaign."""
    id: str
    name: str
    target_id: str  # Campaign or ad set ID
    target_type: str  # "campaign" or "ad_set"
    
    # Scaling parameters
    strategy: ScalingStrategy
    initial_budget: float
    current_budget: float
    target_budget: float
    max_budget: float
    
    # Scaling increments
    increase_percentage: float  # How much to increase each time
    increase_interval_hours: int  # How often to increase
    
    # Performance thresholds
    min_roas: float  # Minimum return on ad spend
    min_conversions: int  # Minimum conversions per day
    max_cpa: float  # Maximum cost per acquisition
    
    # State
    status: ScalingStatus
    last_scaled: Optional[str] = None
    scale_count: int = 0
    
    def __post_init__(self):
        if self.last_scaled is None:
            self.last_scaled = datetime.now().isoformat()


@dataclass
class ScalingMetrics:
    """Performance metrics for scaling decisions."""
    campaign_id: str
    spend: float
    impressions: int
    clicks: int
    conversions: int
    revenue: float
    roas: float
    cpa: float
    ctr: float
    period_hours: int
    
    @property
    def conversions_per_day(self) -> float:
        """Calculate conversions per day."""
        if self.period_hours == 0:
            return 0.0
        return (self.conversions / self.period_hours) * 24


class ScalingManager:
    """
    Manages automatic scaling of winning ads.
    """
    
    def __init__(self, 
                 min_budget: float = 10.0,
                 max_budget: float = 50000.0,
                 evaluation_interval_hours: int = 24):
        """
        Initialize scaling manager.
        
        Args:
            min_budget: Minimum budget for scaled campaigns
            max_budget: Maximum budget limit
            evaluation_interval_hours: How often to evaluate scaling
        """
        self.min_budget = min_budget
        self.max_budget = max_budget
        self.evaluation_interval_hours = evaluation_interval_hours
        
        self.rules: Dict[str, ScalingRule] = {}
        self.scaling_history: Dict[str, List[Dict]] = defaultdict(list)
        
    def create_rule(self,
                   name: str,
                   target_id: str,
                   target_type: str,
                   strategy: ScalingStrategy,
                   initial_budget: float,
                   target_budget: float,
                   max_budget: Optional[float] = None) -> ScalingRule:
        """
        Create a new scaling rule.
        
        Args:
            name: Rule name
            target_id: Campaign or ad set ID
            target_type: "campaign" or "ad_set"
            strategy: Scaling strategy
            initial_budget: Starting budget
            target_budget: Target budget
            max_budget: Maximum budget limit
            
        Returns:
            Created scaling rule
        """
        rule_id = f"scale_rule_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Set strategy-specific parameters
        if strategy == ScalingStrategy.GRADUAL:
            increase_percentage = 15.0  # 15% increase
            increase_interval = 24  # Every 24 hours
        elif strategy == ScalingStrategy.AGGRESSIVE:
            increase_percentage = 25.0  # 25% increase
            increase_interval = 12  # Every 12 hours
        elif strategy == ScalingStrategy.CONSERVATIVE:
            increase_percentage = 10.0  # 10% increase
            increase_interval = 48  # Every 48 hours
        else:  # DYNAMIC
            increase_percentage = 20.0
            increase_interval = 24
        
        rule = ScalingRule(
            id=rule_id,
            name=name,
            target_id=target_id,
            target_type=target_type,
            strategy=strategy,
            initial_budget=initial_budget,
            current_budget=initial_budget,
            target_budget=target_budget,
            max_budget=max_budget or self.max_budget,
            increase_percentage=increase_percentage,
            increase_interval_hours=increase_interval,
            min_roas=2.0,  # Default minimum ROAS
            min_conversions=5,  # Default minimum conversions per day
            max_cpa=50.0,  # Default maximum CPA
            status=ScalingStatus.DRAFT,
            scale_count=0
        )
        
        self.rules[rule_id] = rule
        return rule
    
    def activate_rule(self, rule_id: str) -> bool:
        """Activate a scaling rule."""
        if rule_id not in self.rules:
            return False
        
        rule = self.rules[rule_id]
        rule.status = ScalingStatus.ACTIVE
        return True
    
    def pause_rule(self, rule_id: str) -> bool:
        """Pause a scaling rule."""
        if rule_id not in self.rules:
            return False
        
        rule = self.rules[rule_id]
        rule.status = ScalingStatus.PAUSED
        return True
    
    def evaluate_scaling(self, rule_id: str, metrics: ScalingMetrics) -> Optional[float]:
        """
        Evaluate whether to scale and return new budget.
        
        Args:
            rule_id: Scaling rule ID
            metrics: Performance metrics
            
        Returns:
            New budget amount if scaling, None otherwise
        """
        if rule_id not in self.rules:
            return None
        
        rule = self.rules[rule_id]
        
        if rule.status != ScalingStatus.ACTIVE:
            return None
        
        # Check performance thresholds
        if metrics.roas < rule.min_roas:
            rule.status = ScalingStatus.UNDERPERFORMING
            return None
        
        if metrics.conversions_per_day < rule.min_conversions:
            rule.status = ScalingStatus.UNDERPERFORMING
            return None
        
        if metrics.cpa > rule.max_cpa:
            rule.status = ScalingStatus.UNDERPERFORMING
            return None
        
        # Check if target budget reached
        if rule.current_budget >= rule.target_budget:
            rule.status = ScalingStatus.MAX_REACHED
            return None
        
        # Check if max budget reached
        if rule.current_budget >= rule.max_budget:
            rule.status = ScalingStatus.MAX_REACHED
            return None
        
        # Calculate new budget based on strategy
        if rule.strategy == ScalingStrategy.DYNAMIC:
            # Dynamic scaling based on performance
            performance_score = self._calculate_performance_score(metrics)
            
            if performance_score >= 80:
                increase_pct = rule.increase_percentage * 1.5  # Increase faster for high performers
            elif performance_score >= 60:
                increase_pct = rule.increase_percentage
            else:
                increase_pct = rule.increase_percentage * 0.5  # Slower increase
        
        else:
            increase_pct = rule.increase_percentage
        
        # Calculate new budget
        new_budget = rule.current_budget * (1 + increase_pct / 100)
        
        # Clamp to target and max budget
        new_budget = min(new_budget, rule.target_budget, rule.max_budget)
        
        # Ensure minimum budget
        new_budget = max(new_budget, self.min_budget)
        
        return new_budget
    
    def apply_scaling(self, rule_id: str, new_budget: float) -> bool:
        """
        Apply the scaled budget.
        
        Args:
            rule_id: Scaling rule ID
            new_budget: New budget amount
            
        Returns:
            True if successful
        """
        if rule_id not in self.rules:
            return False
        
        rule = self.rules[rule_id]
        old_budget = rule.current_budget
        
        rule.current_budget = new_budget
        rule.last_scaled = datetime.now().isoformat()
        rule.scale_count += 1
        
        # Record in history
        history_entry = {
            "timestamp": datetime.now().isoformat(),
            "old_budget": old_budget,
            "new_budget": new_budget,
            "increase_pct": ((new_budget - old_budget) / old_budget * 100) if old_budget > 0 else 0
        }
        
        self.scaling_history[rule_id].append(history_entry)
        
        return True
    
    def _calculate_performance_score(self, metrics: ScalingMetrics) -> float:
        """
        Calculate overall performance score (0-100).
        
        Factors:
        - ROAS (40%)
        - Conversions per day (30%)
        - CPA efficiency (20%)
        - CTR (10%)
        """
        score = 0
        
        # ROAS component (40%)
        roas_score = min(metrics.roas / 3.0 * 40, 40)  # Target ROAS of 3.0
        score += roas_score
        
        # Conversions per day component (30%)
        conv_score = min(metrics.conversions_per_day / 10 * 30, 30)  # Target 10 conversions/day
        score += conv_score
        
        # CPA efficiency component (20%)
        if metrics.cpa > 0:
            cpa_score = max(0, (50 / metrics.cpa) * 20)  # Target $50 CPA
            score += min(cpa_score, 20)
        
        # CTR component (10%)
        ctr_score = min(metrics.ctr * 5, 10)  # Scale to 10
        score += ctr_score
        
        return min(score, 100)
    
    def should_scale_now(self, rule_id: str) -> bool:
        """
        Check if enough time has passed since last scaling.
        
        Args:
            rule_id: Scaling rule ID
            
        Returns:
            True if scaling can happen now
        """
        if rule_id not in self.rules:
            return False
        
        rule = self.rules[rule_id]
        
        if rule.last_scaled is None:
            return True
        
        last_scaled = datetime.fromisoformat(rule.last_scaled.replace('Z', '+00:00'))
        hours_since = (datetime.now() - last_scaled).total_seconds() / 3600
        
        return hours_since >= rule.increase_interval_hours
    
    def generate_scaling_report(self) -> Dict:
        """Generate a comprehensive scaling report."""
        active_rules = [r for r in self.rules.values() if r.status == ScalingStatus.ACTIVE]
        
        total_budget = sum(r.current_budget for r in active_rules)
        total_target = sum(r.target_budget for r in active_rules)
        
        return {
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_rules": len(self.rules),
                "active_rules": len(active_rules),
                "total_current_budget": total_budget,
                "total_target_budget": total_target,
                "budget_to_scale": total_target - total_budget
            },
            "rules": [
                {
                    "id": r.id,
                    "name": r.name,
                    "target_id": r.target_id,
                    "current_budget": r.current_budget,
                    "target_budget": r.target_budget,
                    "status": r.status.value,
                    "scale_count": r.scale_count,
                    "last_scaled": r.last_scaled
                }
                for r in active_rules
            ]
        }
    
    def save_rules(self, output_path: str) -> bool:
        """Save scaling rules to file."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Convert rules to dict, handling enums
        rules_dict = []
        for rule in self.rules.values():
            rule_dict = asdict(rule)
            rule_dict["strategy"] = rule.strategy.value
            rule_dict["status"] = rule.status.value
            rules_dict.append(rule_dict)
        
        data = {
            "rules": rules_dict,
            "scaling_history": {k: v for k, v in self.scaling_history.items()},
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "total_rules": len(self.rules)
            }
        }
        
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)
        
        print(f"✅ Scaling rules saved to: {output_path}")
        return True


def main():
    """Demo: Create and manage scaling rules for winning ads."""
    import sys
    from collections import defaultdict
    
    # Fix for missing import
    sys.modules['collections'].defaultdict = defaultdict
    
    manager = ScalingManager()
    
    print("=" * 70)
    print("META ADS SCALING LOGIC DEMO")
    print("=" * 70)
    
    # Create scaling rules for different campaigns
    print("\n📋 Creating Scaling Rules...")
    
    # Campaign 1: Gradual scaling
    rule1 = manager.create_rule(
        name="Q2 Sales Campaign - Gradual Scale",
        target_id="camp_q2-sales-20260323",
        target_type="campaign",
        strategy=ScalingStrategy.GRADUAL,
        initial_budget=100.0,
        target_budget=1000.0,
        max_budget=2000.0
    )
    manager.activate_rule(rule1.id)
    print(f"✅ Rule 1: {rule1.name}")
    print(f"   Budget: ${rule1.current_budget} → ${rule1.target_budget}")
    print(f"   Strategy: {rule1.strategy.value} (+{rule1.increase_percentage}% every {rule1.increase_interval_hours}h)")
    
    # Campaign 2: Aggressive scaling
    rule2 = manager.create_rule(
        name="Lead Gen Campaign - Aggressive Scale",
        target_id="camp_lead-gen-20260323",
        target_type="campaign",
        strategy=ScalingStrategy.AGGRESSIVE,
        initial_budget=50.0,
        target_budget=500.0,
        max_budget=1000.0
    )
    manager.activate_rule(rule2.id)
    print(f"✅ Rule 2: {rule2.name}")
    print(f"   Budget: ${rule2.current_budget} → ${rule2.target_budget}")
    print(f"   Strategy: {rule2.strategy.value} (+{rule2.increase_percentage}% every {rule2.increase_interval_hours}h)")
    
    # Evaluate and apply scaling
    print("\n📊 Evaluating Scaling Rules...")
    
    # Simulate metrics for Rule 1 (good performance)
    metrics1 = ScalingMetrics(
        campaign_id="camp_q2-sales-20260323",
        spend=300.0,
        impressions=15000,
        clicks=450,
        conversions=15,
        revenue=600.0,
        roas=2.0,
        cpa=20.0,
        ctr=3.0,
        period_hours=24
    )
    
    new_budget1 = manager.evaluate_scaling(rule1.id, metrics1)
    if new_budget1 and manager.should_scale_now(rule1.id):
        manager.apply_scaling(rule1.id, new_budget1)
        increase_pct = ((new_budget1 - rule1.current_budget) / rule1.current_budget * 100)
        print(f"✅ Rule 1 scaled: ${rule1.current_budget} → ${new_budget1} ({increase_pct:+.1f}%)")
    
    # Simulate metrics for Rule 2 (very good performance)
    metrics2 = ScalingMetrics(
        campaign_id="camp_lead-gen-20260323",
        spend=150.0,
        impressions=10000,
        clicks=300,
        conversions=30,
        revenue=0.0,  # Leads don't have direct revenue
        roas=0.0,
        cpa=5.0,
        ctr=3.0,
        period_hours=24
    )
    
    new_budget2 = manager.evaluate_scaling(rule2.id, metrics2)
    if new_budget2 and manager.should_scale_now(rule2.id):
        manager.apply_scaling(rule2.id, new_budget2)
        increase_pct = ((new_budget2 - rule2.current_budget) / rule2.current_budget * 100)
        print(f"✅ Rule 2 scaled: ${rule2.current_budget} → ${new_budget2} ({increase_pct:+.1f}%)")
    
    # Generate report
    report = manager.generate_scaling_report()
    
    print("\n📈 Scaling Report")
    print("-" * 70)
    print(f"Active Rules: {report['summary']['active_rules']}")
    print(f"Current Total Budget: ${report['summary']['total_current_budget']:.2f}")
    print(f"Target Total Budget: ${report['summary']['total_target_budget']:.2f}")
    print(f"Budget to Scale: ${report['summary']['budget_to_scale']:.2f}")
    
    print("\n📋 Active Rules:")
    for rule in report['rules']:
        status_symbol = "✅" if rule['status'] == 'active' else "⏸️"
        print(f"  {status_symbol} {rule['name']}")
        print(f"     ${rule['current_budget']:.2f} → ${rule['target_budget']:.2f}")
        print(f"     Scaled {rule['scale_count']} times")
    
    # Save rules
    output_path = Path(__file__).parent.parent / "output" / "scaling_rules.json"
    manager.save_rules(str(output_path))
    
    print("\n✅ Scaling logic demo complete!")


if __name__ == "__main__":
    from collections import defaultdict
    main()
