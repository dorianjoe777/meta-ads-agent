import importlib.util
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from campaign_canary_matrix import (  # noqa: E402
    LIVE_FAMILY_COUNTS,
    contract_cases,
    live_cases,
    manifest_summary,
    natural_language_briefs,
)


def load_runner():
    spec = importlib.util.spec_from_file_location(
        "exhaustive_campaign_canary_runner",
        ROOT / "scripts" / "exhaustive_campaign_canary.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExhaustiveCampaignCanaryTests(unittest.TestCase):
    def test_cleanup_retries_transient_meta_delete_failure(self):
        runner = load_runner()

        class Client:
            def __init__(self):
                self.calls = 0

            def delete(self, *_args, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    return {"returncode": 400, "body": {"error": {"message": "IN_PROCESS"}}}
                return {"returncode": 0, "body": {"success": True}}

        client = Client()
        result = runner.delete_campaign(client, "123", attempts=2, retry_seconds=0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["attempts"], 2)
    def test_manifest_has_exact_planned_coverage(self):
        cases = live_cases()
        summary = manifest_summary()
        self.assertEqual(len(cases), 60)
        self.assertEqual(len(contract_cases()), 128)
        self.assertEqual(len(natural_language_briefs()), 30)
        self.assertEqual(Counter(item["family"] for item in cases), Counter(LIVE_FAMILY_COUNTS))
        self.assertGreaterEqual(summary["estimated_ads"], 90)
        self.assertLessEqual(summary["estimated_ads"], 110)
        keepers = [item for item in cases if item.get("canary_keep")]
        self.assertEqual(len({item["subtype"] for item in keepers}), len(keepers))
        existing_keeper = next(item for item in keepers if item["subtype"] == "existing_post")
        story_ids = [ad.get("object_story_id") for adset in existing_keeper["ad_sets"] for ad in adset["ads"]]
        self.assertEqual(story_ids, ["{{AD_STORY_ID}}"])

    def test_every_live_probe_is_paused_and_has_exact_creative_contract(self):
        for case in live_cases():
            self.assertEqual(case["final_status"], "PAUSED")
            self.assertFalse(case["active_spend_confirmed"])
            self.assertIn(case["budget_level"], {"campaign", "adset"})
            self.assertTrue(case["ad_sets"])
            for adset in case["ad_sets"]:
                targeting = adset["targeting"]
                self.assertIn(targeting["targeting_mode"], {"broad", "advantage_plus", "manual"})
                if targeting["targeting_mode"] == "advantage_plus":
                    self.assertLessEqual(targeting["age_range"]["min"], 25)
                    self.assertEqual(targeting["age_range"]["max"], 65)
                    self.assertEqual(targeting["targeting_automation"], {"advantage_audience": 1})
                if targeting["targeting_mode"] == "broad":
                    self.assertLessEqual(targeting["age_range"]["min"], 25)
                    self.assertEqual(targeting["age_range"]["max"], 65)
                    self.assertEqual(targeting["targeting_automation"], {"advantage_audience": 1})
                if targeting["targeting_mode"] == "manual":
                    self.assertEqual(targeting["targeting_automation"], {"advantage_audience": 0})
                self.assertTrue(adset["ads"])
                for ad in adset["ads"]:
                    self.assertTrue(ad.get("name"))
                    self.assertTrue(ad.get("primary_text"))
                    self.assertTrue(ad.get("headline"))
                    self.assertTrue(any(ad.get(key) for key in ("creative_image_path", "video_path", "object_story_id")))
                    if ad.get("video_path"):
                        self.assertTrue(ad.get("creative_image_path"), "every video canary must carry an explicit thumbnail")

    def test_contract_layer_executes_all_128_cases_without_graph(self):
        runner = load_runner()
        with tempfile.TemporaryDirectory() as directory:
            report = runner.run_contracts(Path(directory))
        self.assertTrue(report["ok"])
        self.assertEqual(report["passed"], 128)
        self.assertEqual(report["failed"], 0)

    def test_negative_layer_blocks_every_required_failure_before_graph_write(self):
        runner = load_runner()
        with tempfile.TemporaryDirectory() as directory:
            report = runner.run_negative_contracts(Path(directory))
        self.assertTrue(report["ok"])
        self.assertEqual(report["cases"], 10)
        self.assertEqual(report["passed"], 10)
        self.assertTrue(all(row["blocked_before_graph_write"] for row in report["rows"]))

    def test_live_capability_blocks_do_not_mutate(self):
        runner = load_runner()
        app_case = next(item for item in live_cases() if item["subtype"] == "app_promotion")
        catalog_case = next(item for item in live_cases() if item["subtype"] == "catalog_sales")
        self.assertEqual(runner.capability_block(app_case, {}), "missing_live_capability:app")
        self.assertEqual(runner.capability_block(catalog_case, {}), "missing_live_capability:catalog")

    def test_natural_language_briefs_preserve_high_risk_fields(self):
        for brief in natural_language_briefs():
            expected = brief["expected"]
            self.assertIn(expected["name"], brief["text"])
            self.assertIn(str(expected["daily_budget"]), brief["text"])
            self.assertIn(expected["primary_text"], brief["text"])
            self.assertIn(expected["headline"], brief["text"])
            self.assertEqual(expected["final_status"], "PAUSED")


if __name__ == "__main__":
    unittest.main()
