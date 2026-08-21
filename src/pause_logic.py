#!/usr/bin/env python3
"""
Pause Logic for Underperforming Ads
Automatically pauses ads that fail to meet performance criteria.
"""
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum


class PauseReason(Enum):
    """Reasons for pausing an ad."""
    LOW_CTR = "low_ctr"
    HIGH_CPA = "high_cpa"
    LOW_ROAS = "low_roas"
    LOW_CONVERSIONS = "low_conversions"
    HIGH_SPEND = "high_spend"
    CUSTOM_RULE = "custom_rule"


@dataclass
class PauseThreshold:
    """Performance thresholds for pausing ads."""
    min_ctr: float = 0.5  # Minimum click-through rate (%)
    max_cpa: float = 50.0  # Maximum cost per acquisition ($)
    min_roas: float = 2.0  # Minimum return on ad spend
    min_conversions: int = 1  # Minimum conversions per day
    max_spend_per_day: float = 1000.0  # Maximum daily spend


@dataclass
class PauseRule:
    """Rule for pausing underperforming ads."""
    id: str
    name: str
    threshold: PauseThreshold
    active: bool = True
    created_at: str = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()


@dataclass
class AdPerformance:
    """Performance data for an ad."""
    ad_id: str
    ad_name: str
    campaign_id: str
    spend: float
    impressions: int
    clicks: int
    conversions: int
    revenue: float
    period_hours: int
    status: str = "active"
    
    @property
    def ctr(self) -> float:
        """Calculate click-through rate."""
        if self.impressions == 0:
            return 0.0
        return (self.clicks / self.impressions) * 100
    
    @property
    def cpa(self) -> float:
        """Calculate cost per acquisition."""
        if self.conversions == 0:
            return float('inf')
        return self.spend / self.conversions
    
    @property
    def roas(self) -> float:
        """Calculate return on ad spend."""
        if self.spend == 0:
            return 0.0
        return self.revenue / self.spend
    
    @property
    def conversions_per_day(self) -> float:
        """Calculate conversions per day."""
        if self.period_hours == 0:
            return 0.0
        return (self.conversions / self.period_hours) * 24
    
    @property
    def spend_per_day(self) -> float:
        """Calculate spend per day."""
        if self.period_hours == 0:
            return 0.0
        return (self.spend / self.period_hours) * 24


class PauseManager:
    """
    Manages automatic pausing of underperforming ads.
    """
    
    def __init__(self):
        self.rules: Dict[str, PauseRule] = {}
        self.paused_ads: Dict[str, Dict] = {}
        self.pause_history: List[Dict] = []
        
        # Default rule
        self.default_threshold = PauseThreshold()
        self.default_rule = PauseRule(
            id="default",
            name="Default Pause Rule",
            threshold=self.default_threshold
        )
        self.rules["default"] = self.default_rule
    
    def create_rule(self, name: str, threshold: PauseThreshold) -> PauseRule:
        """Create a new pause rule."""
        rule_id = f"pause_rule_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        rule = PauseRule(id=rule_id, name=name, threshold=threshold)
        self.rules[rule_id] = rule
        return rule
    
    def evaluate_ad(self, 
                   ad: AdPerformance, 
                   rule_id: str = "default") -> Tuple[bool, Optional[PauseReason]]:
        """
        Evaluate if an ad should be paused.
        
        Args:
            ad: Ad performance data
            rule_id: Rule to use for evaluation
            
        Returns:
            Tuple of (should_pause, reason)
        """
        if rule_id not in self.rules:
            rule = self.default_rule
        else:
            rule = self.rules[rule_id]
        
        if not rule.active:
            return False, None
        
        threshold = rule.threshold
        
        # Check each threshold
        if ad.ctr < threshold.min_ctr:
            return True, PauseReason.LOW_CTR
        
        if ad.cpa > threshold.max_cpa:
            return True, PauseReason.HIGH_CPA
        
        if ad.roas < threshold.min_roas:
            return True, PauseReason.LOW_ROAS
        
        if ad.conversions_per_day < threshold.min_conversions:
            return True, PauseReason.LOW_CONVERSIONS
        
        if ad.spend_per_day > threshold.max_spend_per_day:
            return True, PauseReason.HIGH_SPEND
        
        return False, None
    
    def pause_ad(self, 
                 ad: AdPerformance, 
                 reason: PauseReason,
                 rule_id: str = "default") -> bool:
        """
        Pause an ad and record the action.
        
        Args:
            ad: Ad to pause
            reason: Reason for pausing
            rule_id: Rule that triggered the pause
            
        Returns:
            True if successfully paused
        """
        if ad.ad_id in self.paused_ads:
            return False  # Already paused
        
        pause_record = {
            "ad_id": ad.ad_id,
            "ad_name": ad.ad_name,
            "campaign_id": ad.campaign_id,
            "reason": reason.value,
            "reason_text": self._get_reason_text(reason, ad),
            "rule_id": rule_id,
            "paused_at": datetime.now().isoformat(),
            "performance": {
                "ctr": ad.ctr,
                "cpa": ad.cpa,
                "roas": ad.roas,
                "conversions_per_day": ad.conversions_per_day,
                "spend_per_day": ad.spend_per_day
            }
        }
        
        self.paused_ads[ad.ad_id] = pause_record
        self.pause_history.append(pause_record)
        
        return True
    
    def resume_ad(self, ad_id: str) -> bool:
        """Resume a paused ad."""
        if ad_id in self.paused_ads:
            del self.paused_ads[ad_id]
            return True
        return False
    
    def should_resume(self, ad: AdPerformance, rule_id: str = "default") -> bool:
        """
        Check if a paused ad should be resumed.
        
        Args:
            ad: Ad performance data
            rule_id: Rule to use for evaluation
            
        Returns:
            True if ad should be resumed
        """
        should_pause, _ = self.evaluate_ad(ad, rule_id)
        return not should_pause
    
    def get_paused_ads(self) -> List[Dict]:
        """Get all paused ads."""
        return list(self.paused_ads.values())
    
    def get_pause_history(self, 
                          limit: int = 100,
                          ad_id: Optional[str] = None) -> List[Dict]:
        """Get pause history."""
        history = self.pause_history
        
        if ad_id:
            history = [h for h in history if h["ad_id"] == ad_id]
        
        return history[-limit:] if limit else history
    
    def _get_reason_text(self, reason: PauseReason, ad: AdPerformance) -> str:
        """Get human-readable reason text."""
        if reason == PauseReason.LOW_CTR:
            return f"CTR too low ({ad.ctr:.2f}% < {self.default_threshold.min_ctr}%)"
        elif reason == PauseReason.HIGH_CPA:
            return f"CPA too high (${ad.cpa:.2f} > ${self.default_threshold.max_cpa})"
        elif reason == PauseReason.LOW_ROAS:
            return f"ROAS too low ({ad.roas:.2f}x < {self.default_threshold.min_roas}x)"
        elif reason == PauseReason.LOW_CONVERSIONS:
            return f"Too few conversions ({ad.conversions_per_day:.1f}/day < {self.default_threshold.min_conversions}/day)"
        elif reason == PauseReason.HIGH_SPEND:
            return f"Daily spend too high (${ad.spend_per_day:.2f} > ${self.default_threshold.max_spend_per_day})"
        else:
            return "Underperforming"
    
    def generate_report(self) -> Dict:
        """Generate a pause management report."""
        paused = self.get_paused_ads()
        history = self.get_pause_history(limit=50)
        
        # Group by reason
        reason_counts = {}
        for record in history:
            reason = record["reason"]
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        
        return {
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_paused": len(paused),
                "total_resumed": len(self.pause_history) - len(paused),
                "reason_distribution": reason_counts
            },
            "paused_ads": paused,
            "recent_history": history
        }
    
    def save_report(self, output_path: str) -> bool:
        """Save report to file."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        report = self.generate_report()
        
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)
        
        print(f"✅ Report saved to: {output_path}")
        return True


def main():
    """Demo: Pause underperforming ads."""
    manager = PauseManager()
    
    print("=" * 70)
    print("META ADS PAUSE LOGIC DEMO")
    print("=" * 70)
    
    # Create sample ads with different performance levels
    ads = [
        AdPerformance(
            ad_id="ad_001",
            ad_name="High Performer",
            campaign_id="camp_q2_sales",
            spend=150.0,
            impressions=15000,
            clicks=600,
            conversions=20,
            revenue=400.0,
            period_hours=24,
            status="active"
        ),
        AdPerformance(
            ad_id="ad_002",
            ad_name="Low CTR Ad",
            campaign_id="camp_q2_sales",
            spend=200.0,
            impressions=20000,
            clicks=100,  # Low CTR
            conversions=5,
            revenue=100.0,
            period_hours=24,
            status="active"
        ),
        AdPerformance(
            ad_id="ad_003",
            ad_name="High CPA Ad",
            campaign_id="camp_lead_gen",
            spend=500.0,
            impressions=10000,
            clicks=300,
            conversions=5,  # High CPA
            revenue=0.0,
            period_hours=24,
            status="active"
        ),
        AdPerformance(
            ad_id="ad_004",
            ad_name="Low ROAS Ad",
            campaign_id="camp_q2_sales",
            spend=300.0,
            impressions=12000,
            clicks=400,
            conversions=10,
            revenue=200.0,  # Low ROAS
            period_hours=24,
            status="active"
        )
    ]
    
    print("\n📊 Evaluating Ads...")
    print("-" * 70)
    print(f"{'Ad Name':<20} {'CTR':<8} {'CPA':<8} {'ROAS':<8} {'Status':<10}")
    print("-" * 70)
    
    for ad in ads:
        should_pause, reason = manager.evaluate_ad(ad)
        
        if should_pause:
            manager.pause_ad(ad, reason)
            status = "⏸️ Paused"
        else:
            status = "✅ Active"
        
        print(
            f"{ad.ad_name:<20} "
            f"{ad.ctr:<8.2f}% "
            f"${ad.cpa:<7.2f} "
            f"{ad.roas:<7.2f}x "
            f"{status:<10}"
        )
    
    # Generate report
    report = manager.generate_report()
    
    print("\n📈 Pause Report")
    print("-" * 70)
    print(f"Total Ads Evaluated: {len(ads)}")
    print(f"Ads Paused: {report['summary']['total_paused']}")
    print(f"Reasons:")
    for reason, count in report['summary']['reason_distribution'].items():
        print(f"  - {reason}: {count}")
    
    print("\n📋 Paused Ads:")
    for ad in report['paused_ads']:
        print(f"  - {ad['ad_name']}: {ad['reason_text']}")
    
    # Save report
    output_path = Path(__file__).parent.parent / "output" / "pause_report.json"
    manager.save_report(str(output_path))
    
    print("\n✅ Pause logic demo complete!")


if __name__ == "__main__":
    main()
