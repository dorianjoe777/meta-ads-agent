#!/usr/bin/env python3
"""
A/B Testing for Meta Ads Creatives
Tests different ad variations to determine optimal creative elements.
"""
import json
import random
import math
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from collections import defaultdict


class TestStatus(Enum):
    """A/B test status."""
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CreativeElement(Enum):
    """Creative elements to test."""
    HEADLINE = "headline"
    BODY_COPY = "body_copy"
    IMAGE = "image"
    CTA_BUTTON = "cta_button"
    LANDING_PAGE = "landing_page"
    COLOR_SCHEME = "color_scheme"


@dataclass
class CreativeVariant:
    """A single creative variant for testing."""
    id: str
    name: str
    creative_type: str
    element: CreativeElement
    content: Dict[str, str]  # Content details (headline, text, etc.)
    metadata: Dict = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class ABTest:
    """A/B test configuration."""
    id: str
    name: str
    campaign_id: str
    element: CreativeElement
    variants: List[CreativeVariant]
    status: TestStatus
    start_date: str
    end_date: Optional[str] = None
    metrics: Dict = None
    results: Dict = None
    
    def __post_init__(self):
        if self.metrics is None:
            self.metrics = {
                "impressions": defaultdict(int),
                "clicks": defaultdict(int),
                "conversions": defaultdict(int),
                "spend": defaultdict(float)
            }
        if self.results is None:
            self.results = {}


class ABTestingManager:
    """
    Manages A/B testing for Meta Ads creatives.
    """
    
    def __init__(self, min_sample_size: int = 1000, confidence_level: float = 0.95):
        """
        Initialize A/B testing manager.
        
        Args:
            min_sample_size: Minimum impressions per variant
            confidence_level: Statistical confidence level (default 95%)
        """
        self.min_sample_size = min_sample_size
        self.confidence_level = confidence_level
        self.tests: Dict[str, ABTest] = {}
        
    def create_test(self, 
                   name: str,
                   campaign_id: str,
                   element: CreativeElement,
                   variants: List[CreativeVariant]) -> ABTest:
        """
        Create a new A/B test.
        
        Args:
            name: Test name
            campaign_id: Campaign ID
            element: Creative element to test
            variants: List of creative variants
            
        Returns:
            Created AB test
        """
        test_id = f"ab_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}"
        
        test = ABTest(
            id=test_id,
            name=name,
            campaign_id=campaign_id,
            element=element,
            variants=variants,
            status=TestStatus.DRAFT,
            start_date=datetime.now().isoformat()
        )
        
        self.tests[test_id] = test
        return test
    
    def create_headline_test(self,
                            campaign_id: str,
                            base_headline: str,
                            variations: List[str]) -> ABTest:
        """
        Create a headline A/B test.
        
        Args:
            campaign_id: Campaign ID
            base_headline: Base headline (control)
            variations: List of headline variations
            
        Returns:
            A/B test configuration
        """
        variants = [
            CreativeVariant(
                id=f"variant_{i}",
                name=f"Headline {i+1}",
                creative_type="text",
                element=CreativeElement.HEADLINE,
                content={"headline": var}
            )
            for i, var in enumerate([base_headline] + variations)
        ]
        
        return self.create_test(
            name=f"Headline Test - {campaign_id}",
            campaign_id=campaign_id,
            element=CreativeElement.HEADLINE,
            variants=variants
        )
    
    def create_image_test(self,
                         campaign_id: str,
                         image_variants: List[Dict]) -> ABTest:
        """
        Create an image A/B test.
        
        Args:
            campaign_id: Campaign ID
            image_variants: List of image variant details
            
        Returns:
            A/B test configuration
        """
        variants = [
            CreativeVariant(
                id=f"image_{i}",
                name=f"Image {i+1}",
                creative_type="image",
                element=CreativeElement.IMAGE,
                content=variant
            )
            for i, variant in enumerate(image_variants)
        ]
        
        return self.create_test(
            name=f"Image Test - {campaign_id}",
            campaign_id=campaign_id,
            element=CreativeElement.IMAGE,
            variants=variants
        )
    
    def create_cta_test(self,
                       campaign_id: str,
                       base_cta: str,
                       variations: List[str]) -> ABTest:
        """
        Create a CTA button A/B test.
        
        Args:
            campaign_id: Campaign ID
            base_cta: Base CTA (control)
            variations: List of CTA variations
            
        Returns:
            A/B test configuration
        """
        variants = [
            CreativeVariant(
                id=f"cta_{i}",
                name=f"CTA {i+1}",
                creative_type="text",
                element=CreativeElement.CTA_BUTTON,
                content={"cta_text": var}
            )
            for i, var in enumerate([base_cta] + variations)
        ]
        
        return self.create_test(
            name=f"CTA Test - {campaign_id}",
            campaign_id=campaign_id,
            element=CreativeElement.CTA_BUTTON,
            variants=variants
        )
    
    def start_test(self, test_id: str) -> bool:
        """Start an A/B test."""
        if test_id not in self.tests:
            return False
        
        self.tests[test_id].status = TestStatus.ACTIVE
        self.tests[test_id].start_date = datetime.now().isoformat()
        return True
    
    def pause_test(self, test_id: str) -> bool:
        """Pause an A/B test."""
        if test_id not in self.tests:
            return False
        
        if self.tests[test_id].status == TestStatus.ACTIVE:
            self.tests[test_id].status = TestStatus.PAUSED
            return True
        return False
    
    def complete_test(self, test_id: str) -> bool:
        """Mark a test as completed."""
        if test_id not in self.tests:
            return False
        
        self.tests[test_id].status = TestStatus.COMPLETED
        self.tests[test_id].end_date = datetime.now().isoformat()
        return True
    
    def record_impression(self, test_id: str, variant_id: str, count: int = 1):
        """Record impressions for a variant."""
        if test_id in self.tests:
            test = self.tests[test_id]
            test.metrics["impressions"][variant_id] += count
    
    def record_click(self, test_id: str, variant_id: str, count: int = 1):
        """Record clicks for a variant."""
        if test_id in self.tests:
            test = self.tests[test_id]
            test.metrics["clicks"][variant_id] += count
    
    def record_conversion(self, test_id: str, variant_id: str, count: int = 1):
        """Record conversions for a variant."""
        if test_id in self.tests:
            test = self.tests[test_id]
            test.metrics["conversions"][variant_id] += count
    
    def record_spend(self, test_id: str, variant_id: str, amount: float):
        """Record spend for a variant."""
        if test_id in self.tests:
            test = self.tests[test_id]
            test.metrics["spend"][variant_id] += amount
    
    def calculate_ctr(self, test_id: str, variant_id: str) -> float:
        """Calculate click-through rate for a variant."""
        if test_id not in self.tests:
            return 0.0
        
        test = self.tests[test_id]
        impressions = test.metrics["impressions"].get(variant_id, 0)
        clicks = test.metrics["clicks"].get(variant_id, 0)
        
        if impressions == 0:
            return 0.0
        
        return (clicks / impressions) * 100
    
    def calculate_conversion_rate(self, test_id: str, variant_id: str) -> float:
        """Calculate conversion rate for a variant."""
        if test_id not in self.tests:
            return 0.0
        
        test = self.tests[test_id]
        clicks = test.metrics["clicks"].get(variant_id, 0)
        conversions = test.metrics["conversions"].get(variant_id, 0)
        
        if clicks == 0:
            return 0.0
        
        return (conversions / clicks) * 100
    
    def calculate_cost_per_conversion(self, test_id: str, variant_id: str) -> float:
        """Calculate cost per conversion for a variant."""
        if test_id not in self.tests:
            return float('inf')
        
        test = self.tests[test_id]
        spend = test.metrics["spend"].get(variant_id, 0)
        conversions = test.metrics["conversions"].get(variant_id, 0)
        
        if conversions == 0:
            return float('inf')
        
        return spend / conversions
    
    def calculate_statistical_significance(self, 
                                          test_id: str, 
                                          variant_id_a: str,
                                          variant_id_b: str,
                                          metric: str = "ctr") -> Tuple[float, bool]:
        """
        Calculate statistical significance between two variants.
        
        Args:
            test_id: Test ID
            variant_id_a: First variant ID
            variant_id_b: Second variant ID
            metric: Metric to compare ("ctr", "conversion_rate", "cost_per_conversion")
            
        Returns:
            Tuple of (p_value, is_significant)
        """
        if test_id not in self.tests:
            return 1.0, False
        
        test = self.tests[test_id]
        
        # Get metric values
        if metric == "ctr":
            rate_a = self.calculate_ctr(test_id, variant_id_a) / 100
            rate_b = self.calculate_ctr(test_id, variant_id_b) / 100
        elif metric == "conversion_rate":
            rate_a = self.calculate_conversion_rate(test_id, variant_id_a) / 100
            rate_b = self.calculate_conversion_rate(test_id, variant_id_b) / 100
        else:
            return 1.0, False
        
        # Get sample sizes
        n_a = test.metrics["impressions"].get(variant_id_a, 0)
        n_b = test.metrics["impressions"].get(variant_id_b, 0)
        
        if n_a < self.min_sample_size or n_b < self.min_sample_size:
            return 1.0, False  # Insufficient data
        
        # Calculate pooled proportion
        p_pool = (rate_a * n_a + rate_b * n_b) / (n_a + n_b)
        
        # Calculate standard error
        se = math.sqrt(
            p_pool * (1 - p_pool) * (1/n_a + 1/n_b)
        )
        
        if se == 0:
            return 1.0, False
        
        # Calculate z-score
        z = abs(rate_a - rate_b) / se
        
        # Approximate p-value using normal distribution
        # Using simplified approximation for z-score to p-value
        from math import erf, sqrt
        p_value = 2 * (1 - 0.5 * (1 + erf(z / sqrt(2))))
        
        # Determine significance
        is_significant = p_value < (1 - self.confidence_level)
        
        return p_value, is_significant
    
    def get_winner(self, test_id: str, metric: str = "conversion_rate") -> Optional[CreativeVariant]:
        """
        Determine the winning variant based on a metric.
        
        Args:
            test_id: Test ID
            metric: Metric to optimize for
            
        Returns:
            Winning variant or None if inconclusive
        """
        if test_id not in self.tests:
            return None
        
        test = self.tests[test_id]
        
        if metric == "conversion_rate":
            scores = {
                vid: self.calculate_conversion_rate(test_id, vid)
                for vid in test.metrics["conversions"].keys()
            }
        elif metric == "ctr":
            scores = {
                vid: self.calculate_ctr(test_id, vid)
                for vid in test.metrics["clicks"].keys()
            }
        elif metric == "cost_per_conversion":
            scores = {
                vid: 1 / max(self.calculate_cost_per_conversion(test_id, vid), 0.001)
                for vid in test.metrics["spend"].keys()
            }
        else:
            return None
        
        if not scores:
            return None
        
        # Find winner
        winner_id = max(scores, key=scores.get)
        
        # Find variant object
        for variant in test.variants:
            if variant.id == winner_id:
                return variant
        
        return None
    
    def generate_report(self, test_id: str) -> Dict:
        """Generate a comprehensive A/B test report."""
        if test_id not in self.tests:
            return {"error": "Test not found"}
        
        test = self.tests[test_id]
        
        report = {
            "test_id": test.id,
            "test_name": test.name,
            "campaign_id": test.campaign_id,
            "element": test.element.value,
            "status": test.status.value,
            "start_date": test.start_date,
            "end_date": test.end_date,
            "variants": []
        }
        
        # Calculate metrics for each variant
        for variant in test.variants:
            variant_id = variant.id
            ctr = self.calculate_ctr(test_id, variant_id)
            conv_rate = self.calculate_conversion_rate(test_id, variant_id)
            cpc = self.calculate_cost_per_conversion(test_id, variant_id)
            
            variant_report = {
                "id": variant_id,
                "name": variant.name,
                "impressions": test.metrics["impressions"].get(variant_id, 0),
                "clicks": test.metrics["clicks"].get(variant_id, 0),
                "conversions": test.metrics["conversions"].get(variant_id, 0),
                "spend": test.metrics["spend"].get(variant_id, 0),
                "ctr": ctr,
                "conversion_rate": conv_rate,
                "cost_per_conversion": cpc
            }
            report["variants"].append(variant_report)
        
        # Determine winner
        winner = self.get_winner(test_id, "conversion_rate")
        if winner:
            report["winner"] = {
                "id": winner.id,
                "name": winner.name,
                "reason": "Highest conversion rate"
            }
        
        return report
    
    def save_test(self, test_id: str, output_path: str) -> bool:
        """Save test configuration and results to file."""
        if test_id not in self.tests:
            return False
        
        test = self.tests[test_id]
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Convert test to dict, handling enums
        test_dict = asdict(test)
        test_dict["element"] = test.element.value
        test_dict["status"] = test.status.value
        test_dict["variants"] = [
            {**v, "element": v["element"].value if isinstance(v.get("element"), CreativeElement) else v.get("element")}
            for v in test_dict["variants"]
        ]
        
        data = {
            "test": test_dict,
            "report": self.generate_report(test_id),
            "saved_at": datetime.now().isoformat()
        }
        
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)
        
        print(f"✅ Test saved to: {output_path}")
        return True


def main():
    """Demo: Create and manage A/B tests for creatives."""
    manager = ABTestingManager()
    
    print("=" * 70)
    print("META ADS A/B TESTING MANAGER")
    print("=" * 70)
    
    # Create headline test
    print("\n📋 Creating Headline A/B Test...")
    headline_test = manager.create_headline_test(
        campaign_id="camp_q2-sales-20260323",
        base_headline="Open Your Trading Account Today",
        variations=[
            "Start Trading in Minutes",
            "Trade Forex with Confidence",
            "Join 50,000+ Traders"
        ]
    )
    print(f"   Test ID: {headline_test.id}")
    print(f"   Variants: {len(headline_test.variants)}")
    
    # Start the test
    manager.start_test(headline_test.id)
    print(f"   Status: {headline_test.status.value}")
    
    # Simulate recording metrics
    print("\n📊 Simulating Test Data...")
    
    # Variant 0 (control): "Open Your Trading Account Today"
    manager.record_impression(headline_test.id, "variant_0", 1500)
    manager.record_click(headline_test.id, "variant_0", 45)
    manager.record_conversion(headline_test.id, "variant_0", 3)
    manager.record_spend(headline_test.id, "variant_0", 150.0)
    
    # Variant 1: "Start Trading in Minutes"
    manager.record_impression(headline_test.id, "variant_1", 1450)
    manager.record_click(headline_test.id, "variant_1", 58)
    manager.record_conversion(headline_test.id, "variant_1", 5)
    manager.record_spend(headline_test.id, "variant_1", 145.0)
    
    # Variant 2: "Trade Forex with Confidence"
    manager.record_impression(headline_test.id, "variant_2", 1520)
    manager.record_click(headline_test.id, "variant_2", 42)
    manager.record_conversion(headline_test.id, "variant_2", 2)
    manager.record_spend(headline_test.id, "variant_2", 152.0)
    
    # Variant 3: "Join 50,000+ Traders"
    manager.record_impression(headline_test.id, "variant_3", 1480)
    manager.record_click(headline_test.id, "variant_3", 62)
    manager.record_conversion(headline_test.id, "variant_3", 6)
    manager.record_spend(headline_test.id, "variant_3", 148.0)
    
    # Generate report
    report = manager.generate_report(headline_test.id)
    
    print("\n📈 Test Results:")
    print("-" * 70)
    print(f"{'Variant':<25} {'Impressions':<12} {'CTR':<8} {'Conv Rate':<12} {'Cost/Conv':<12}")
    print("-" * 70)
    
    for variant in report["variants"]:
        print(
            f"{variant['name']:<25} "
            f"{variant['impressions']:<12} "
            f"{variant['ctr']:.2f}% "
            f"{variant['conversion_rate']:.2f}% "
            f"${variant['cost_per_conversion']:.2f}"
        )
    
    if "winner" in report:
        print("\n🎉 Winner:")
        print(f"   {report['winner']['name']} ({report['winner']['reason']})")
    
    # Check statistical significance between winner and runner-up
    print("\n📊 Statistical Significance:")
    p_value, significant = manager.calculate_statistical_significance(
        headline_test.id, "variant_3", "variant_1", "conversion_rate"
    )
    print(f"   Variant 3 vs Variant 1: p-value = {p_value:.4f}")
    print(f"   Statistically significant: {'Yes' if significant else 'No'}")
    
    # Save test
    output_path = Path(__file__).parent.parent / "output" / "ab_test_headlines.json"
    manager.save_test(headline_test.id, str(output_path))
    
    print("\n✅ A/B Testing demo complete!")


if __name__ == "__main__":
    main()
