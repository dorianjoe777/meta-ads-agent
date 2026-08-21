#!/usr/bin/env python3
"""
Auto-Warmup for New Meta Ads Accounts
Gradually increases ad spend and testing to warm up new accounts safely.
"""
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum


class WarmupStage(Enum):
    """Warmup stages for new accounts."""
    PRE_LAUNCH = "pre_launch"
    SOFT_LAUNCH = "soft_launch"
    TESTING = "testing"
    SCALED = "scaled"
    OPTIMIZED = "optimized"


@dataclass
class WarmupConfig:
    """Configuration for account warmup."""
    stage: WarmupStage
    daily_budget: float
    campaigns_per_day: int
    ad_sets_per_campaign: int
    duration_days: int
    max_risk_score: float
    
    @classmethod
    def for_stage(cls, stage: WarmupStage) -> 'WarmupConfig':
        """Get config for a specific stage."""
        configs = {
            WarmupStage.PRE_LAUNCH: cls(
                stage=WarmupStage.PRE_LAUNCH,
                daily_budget=10.0,
                campaigns_per_day=0,
                ad_sets_per_campaign=0,
                duration_days=3,
                max_risk_score=0.1
            ),
            WarmupStage.SOFT_LAUNCH: cls(
                stage=WarmupStage.SOFT_LAUNCH,
                daily_budget=50.0,
                campaigns_per_day=1,
                ad_sets_per_campaign=1,
                duration_days=7,
                max_risk_score=0.3
            ),
            WarmupStage.TESTING: cls(
                stage=WarmupStage.TESTING,
                daily_budget=100.0,
                campaigns_per_day=2,
                ad_sets_per_campaign=2,
                duration_days=14,
                max_risk_score=0.5
            ),
            WarmupStage.SCALED: cls(
                stage=WarmupStage.SCALED,
                daily_budget=250.0,
                campaigns_per_day=3,
                ad_sets_per_campaign=3,
                duration_days=21,
                max_risk_score=0.7
            ),
            WarmupStage.OPTIMIZED: cls(
                stage=WarmupStage.OPTIMIZED,
                daily_budget=500.0,
                campaigns_per_day=5,
                ad_sets_per_campaign=5,
                duration_days=30,
                max_risk_score=0.9
            )
        }
        return configs[stage]


@dataclass
class AccountWarmup:
    """Warmup progress for a new account."""
    account_id: str
    account_name: str
    current_stage: WarmupStage
    start_date: str
    current_daily_budget: float
    total_spend: float
    stage_progress: Dict[WarmupStage, Dict]
    status: str  # active, paused, completed, failed
    
    @classmethod
    def new_account(cls, account_id: str, account_name: str) -> 'AccountWarmup':
        """Create a new account warmup instance."""
        return cls(
            account_id=account_id,
            account_name=account_name,
            current_stage=WarmupStage.PRE_LAUNCH,
            start_date=datetime.now().isoformat(),
            current_daily_budget=WarmupConfig.for_stage(WarmupStage.PRE_LAUNCH).daily_budget,
            total_spend=0.0,
            stage_progress={
                WarmupStage.PRE_LAUNCH: {"days_completed": 0, "status": "active"},
                WarmupStage.SOFT_LAUNCH: {"days_completed": 0, "status": "pending"},
                WarmupStage.TESTING: {"days_completed": 0, "status": "pending"},
                WarmupStage.SCALED: {"days_completed": 0, "status": "pending"},
                WarmupStage.OPTIMIZED: {"days_completed": 0, "status": "pending"}
            },
            status="active"
        )


class AutoWarmupManager:
    """
    Manages auto-warmup for new Meta Ads accounts.
    """
    
    def __init__(self):
        self.accounts: Dict[str, AccountWarmup] = {}
        self.warmup_history: List[Dict] = []
    
    def start_warmup(self, account_id: str, account_name: str) -> AccountWarmup:
        """Start warmup for a new account."""
        if account_id in self.accounts:
            return self.accounts[account_id]
        
        warmup = AccountWarmup.new_account(account_id, account_name)
        self.accounts[account_id] = warmup
        
        self.warmup_history.append({
            "account_id": account_id,
            "action": "started",
            "timestamp": datetime.now().isoformat(),
            "stage": warmup.current_stage.value
        })
        
        return warmup
    
    def advance_stage(self, account_id: str) -> bool:
        """Advance to the next warmup stage."""
        if account_id not in self.accounts:
            return False
        
        warmup = self.accounts[account_id]
        stages = list(WarmupStage)
        current_index = stages.index(warmup.current_stage)
        
        if current_index < len(stages) - 1:
            new_stage = stages[current_index + 1]
            config = WarmupConfig.for_stage(new_stage)
            
            warmup.current_stage = new_stage
            warmup.current_daily_budget = config.daily_budget
            
            # Mark previous stage as completed
            warmup.stage_progress[warmup.current_stage]["status"] = "completed"
            
            # Mark new stage as active
            warmup.stage_progress[new_stage]["status"] = "active"
            
            self.warmup_history.append({
                "account_id": account_id,
                "action": "stage_advanced",
                "timestamp": datetime.now().isoformat(),
                "from_stage": stages[current_index].value,
                "to_stage": new_stage.value,
                "new_budget": config.daily_budget
            })
            
            return True
        
        return False
    
    def update_spend(self, account_id: str, daily_spend: float) -> bool:
        """Update total spend for an account."""
        if account_id not in self.accounts:
            return False
        
        self.accounts[account_id].total_spend += daily_spend
        
        # Check if we should advance stage based on performance
        self._check_stage_advance(account_id)
        
        return True
    
    def _check_stage_advance(self, account_id: str):
        """Check if account should advance to next stage."""
        warmup = self.accounts[account_id]
        config = WarmupConfig.for_stage(warmup.current_stage)
        
        # Check if enough days have passed
        start_date = datetime.fromisoformat(warmup.start_date)
        days_running = (datetime.now() - start_date).days
        
        if days_running >= config.duration_days:
            # Check risk score (simplified - in reality would check actual metrics)
            risk_score = 0.5  # Placeholder
            
            if risk_score <= config.max_risk_score:
                self.advance_stage(account_id)
    
    def pause_warmup(self, account_id: str) -> bool:
        """Pause warmup for an account."""
        if account_id not in self.accounts:
            return False
        
        self.accounts[account_id].status = "paused"
        
        self.warmup_history.append({
            "account_id": account_id,
            "action": "paused",
            "timestamp": datetime.now().isoformat()
        })
        
        return True
    
    def resume_warmup(self, account_id: str) -> bool:
        """Resume warmup for an account."""
        if account_id not in self.accounts:
            return False
        
        self.accounts[account_id].status = "active"
        
        self.warmup_history.append({
            "account_id": account_id,
            "action": "resumed",
            "timestamp": datetime.now().isoformat()
        })
        
        return True
    
    def get_warmup_status(self, account_id: str) -> Optional[AccountWarmup]:
        """Get warmup status for an account."""
        return self.accounts.get(account_id)
    
    def get_all_warmups(self) -> List[AccountWarmup]:
        """Get all active warmups."""
        return list(self.accounts.values())
    
    def generate_report(self) -> Dict:
        """Generate warmup report."""
        warmups = self.get_all_warmups()
        
        return {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_accounts": len(warmups),
                "active_accounts": len([w for w in warmups if w.status == "active"]),
                "total_spend": sum(w.total_spend for w in warmups)
            },
            "accounts": [
                {
                    "account_id": w.account_id,
                    "account_name": w.account_name,
                    "stage": w.current_stage.value,
                    "daily_budget": w.current_daily_budget,
                    "total_spend": w.total_spend,
                    "status": w.status
                }
                for w in warmups
            ],
            "recent_history": self.warmup_history[-10:]
        }
    
    def save_report(self, output_path: str) -> bool:
        """Save report to file."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        report = self.generate_report()
        
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)
        
        print(f"✅ Warmup report saved to: {output_path}")
        return True


def main():
    """Demo: Auto-warmup for new accounts."""
    manager = AutoWarmupManager()
    
    print("=" * 70)
    print("META ADS AUTO-WARMUP DEMO")
    print("=" * 70)
    
    # Start warmup for new accounts
    print("\n📋 Starting Warmups for New Accounts...")
    
    account1 = manager.start_warmup("acc_new_001", "New Business Account")
    print(f"✅ Started warmup: {account1.account_name}")
    print(f"   Stage: {account1.current_stage.value}")
    print(f"   Daily Budget: ${account1.current_daily_budget}")
    
    account2 = manager.start_warmup("acc_new_002", "Second Business Account")
    print(f"✅ Started warmup: {account2.account_name}")
    print(f"   Stage: {account2.current_stage.value}")
    print(f"   Daily Budget: ${account2.current_daily_budget}")
    
    # Simulate spending
    print("\n📊 Simulating Spend...")
    
    for day in range(1, 5):
        manager.update_spend("acc_new_001", 10.0 * day)
        manager.update_spend("acc_new_002", 8.0 * day)
        print(f"Day {day}: Account 1 spent ${10.0 * day}, Account 2 spent ${8.0 * day}")
    
    # Check status
    status1 = manager.get_warmup_status("acc_new_001")
    status2 = manager.get_warmup_status("acc_new_002")
    
    print("\n📈 Warmup Status:")
    print("-" * 70)
    print(f"Account 1: Stage={status1.current_stage.value}, Total=${status1.total_spend:.2f}")
    print(f"Account 2: Stage={status2.current_stage.value}, Total=${status2.total_spend:.2f}")
    
    # Generate report
    report = manager.generate_report()
    
    print("\n📋 Warmup Report")
    print("-" * 70)
    print(f"Total Accounts: {report['summary']['total_accounts']}")
    print(f"Active Accounts: {report['summary']['active_accounts']}")
    print(f"Total Spend: ${report['summary']['total_spend']:.2f}")
    
    # Save report
    output_path = Path(__file__).parent.parent / "output" / "warmup_report.json"
    manager.save_report(str(output_path))
    
    print("\n✅ Auto-warmup demo complete!")


if __name__ == "__main__":
    main()
