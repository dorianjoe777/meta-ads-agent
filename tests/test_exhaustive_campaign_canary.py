import importlib.util
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace


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
    def test_visible_post_cleanup_resolves_page_token(self):
        runner = load_runner()

        class Client:
            def meta_page_token(self):
                return "user-token"

            def page_access_token(self, page_id, user_token):
                self.lookup = (page_id, user_token)
                return {"access_token": "page-token"}

            def delete_graph_object(self, post_id, access_token):
                self.deleted = (post_id, access_token)
                return {"ok": True, "body": {"success": True}}

        client = Client()
        result = runner.delete_post(client, "12345_67890")
        self.assertTrue(result["ok"])
        self.assertEqual(client.lookup, ("12345", "user-token"))
        self.assertEqual(client.deleted, ("12345_67890", "page-token"))

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

    def test_summary_gate_includes_negative_contracts_and_capability_blocks(self):
        runner = load_runner()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            runner.write_json(output / "contracts.json", {"ok": True, "passed": 128, "cases": 128})
            runner.write_json(output / "negative-contracts.json", {"ok": True, "passed": 10, "cases": 10})
            runner.write_json(output / "briefs.json", {"ok": True, "passed": 30, "briefs": 30})
            runner.write_json(output / "live-report.json", {
                "ok": True, "passed": 60, "cases": 60,
                "rows": [{"ok": True, "case_id": "case-057", "family": "app_catalog", "status": "capability_block", "reason": "missing_live_capability:app"}],
            })
            runner.write_json(output / "assets.json", {})
            summary = runner.markdown_summary(output).read_text(encoding="utf-8")
        self.assertIn("Negative preflight contracts: 10/10", summary)
        self.assertIn("Canary matrix gate: PASS", summary)
        self.assertIn("case-057: app_catalog", summary)

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

    def test_brief_runner_falls_back_once_and_keeps_fallback_for_correction(self):
        runner = load_runner()
        expected = {
            "name": "Fallback canary", "objective": "traffic", "daily_budget": 20,
            "budget_level": "campaign", "age_min": 25, "age_max": 65,
            "genders": [], "countries": ["CO"], "placements": "automatic",
            "adset_count": 1, "ad_count": 1, "primary_text": "Texto exacto",
            "headline": "Titular exacto", "cta": "LEARN_MORE", "message_destination": "",
            "landing_url": "https://example.com", "initial_message": "", "media_kind": "image",
            "final_status": "PAUSED",
        }
        runner.natural_language_briefs = lambda: [{"brief_id": "brief-fallback", "text": "brief", "expected": expected}]
        calls = []

        def fake_extract(_prompt, _timeout, model=""):
            calls.append(model)
            if len(calls) == 1:
                return SimpleNamespace(returncode=1, stdout="", stderr="HTTP 429: Too Many Requests"), {}
            if len(calls) == 2:
                parsed = dict(expected)
                parsed["daily_budget"] = ""
                return SimpleNamespace(returncode=0, stdout="{}", stderr=""), parsed
            return SimpleNamespace(returncode=0, stdout="{}", stderr=""), dict(expected)

        runner.run_brief_extraction = fake_extract
        with tempfile.TemporaryDirectory() as directory:
            report = runner.run_briefs(
                Path(directory), timeout_seconds=1, resume=False, delay_seconds=0,
                fallback_model="minimaxai/minimax-m3",
            )
            row = report["rows"][0]
        self.assertTrue(row["ok"])
        self.assertEqual(report["passed"], 1)
        self.assertEqual(report["failed"], 0)
        self.assertEqual(row["provider_model"], "minimaxai/minimax-m3")
        self.assertEqual(row["attempts"], 3)
        self.assertEqual(row["total_attempts"], 3)
        self.assertEqual(calls, ["", "minimaxai/minimax-m3", "minimaxai/minimax-m3"])

    def test_brief_runner_escalates_once_when_primary_changes_a_decision(self):
        runner = load_runner()
        expected = {
            "name": "Fidelity canary", "objective": "traffic", "daily_budget": 20,
            "budget_level": "adset", "age_min": 25, "age_max": 44,
            "genders": [2], "countries": ["CO"], "placements": "automatic",
            "adset_count": 1, "ad_count": 1, "primary_text": "Texto exacto",
            "headline": "Titular exacto", "cta": "LEARN_MORE", "message_destination": "",
            "landing_url": "https://example.com", "initial_message": "", "media_kind": "image",
            "final_status": "PAUSED",
        }
        runner.natural_language_briefs = lambda: [{"brief_id": "brief-fidelity", "text": "brief", "expected": expected}]
        calls = []

        def fake_extract(_prompt, _timeout, model=""):
            calls.append(model)
            parsed = dict(expected)
            if len(calls) < 3:
                parsed["genders"] = [1]
            return SimpleNamespace(returncode=0, stdout="{}", stderr=""), parsed

        runner.run_brief_extraction = fake_extract
        with tempfile.TemporaryDirectory() as directory:
            report = runner.run_briefs(
                Path(directory), timeout_seconds=1, resume=False, delay_seconds=0,
                fallback_model="minimaxai/minimax-m3",
            )
            row = report["rows"][0]
        self.assertTrue(row["ok"])
        self.assertEqual(row["provider_model"], "minimaxai/minimax-m3")
        self.assertEqual(row["attempts"], 3)
        self.assertEqual(calls, ["", "", "minimaxai/minimax-m3"])

    def test_brief_runner_can_pin_a_primary_model_for_provider_isolation(self):
        runner = load_runner()
        expected = {
            "name": "Pinned model canary", "objective": "awareness", "daily_budget": 20,
            "budget_level": "campaign", "age_min": 18, "age_max": 65,
            "genders": [], "countries": ["CO"], "placements": "automatic",
            "adset_count": 1, "ad_count": 1, "primary_text": "Texto exacto",
            "headline": "Titular exacto", "cta": "", "message_destination": "",
            "landing_url": "", "initial_message": "", "media_kind": "image",
            "final_status": "PAUSED",
        }
        runner.natural_language_briefs = lambda: [{"brief_id": "brief-pinned", "text": "brief", "expected": expected}]
        calls = []

        def fake_extract(_prompt, _timeout, model=""):
            calls.append(model)
            return SimpleNamespace(returncode=0, stdout="{}", stderr=""), dict(expected)

        runner.run_brief_extraction = fake_extract
        with tempfile.TemporaryDirectory() as directory:
            report = runner.run_briefs(
                Path(directory), timeout_seconds=1, resume=False, delay_seconds=0,
                primary_model="deepseek-ai/deepseek-v4-flash-0731",
                fallback_model="minimaxai/minimax-m3",
            )
            row = report["rows"][0]
        self.assertTrue(row["ok"])
        self.assertEqual(row["provider_model"], "deepseek-ai/deepseek-v4-flash-0731")
        self.assertEqual(calls, ["deepseek-ai/deepseek-v4-flash-0731"])


if __name__ == "__main__":
    unittest.main()
