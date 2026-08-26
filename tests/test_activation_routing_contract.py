import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ActivationRoutingContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = (ROOT / "agent/skills/meta-campaign-execution/SKILL.md").read_text(encoding="utf-8")
        cls.tools = (ROOT / "agent/TOOLS.md").read_text(encoding="utf-8")
        cls.skills = (ROOT / "agent/SKILLS.md").read_text(encoding="utf-8")
        cls.core = (ROOT / "agent/skills/core-agent-behavior/SKILL.md").read_text(encoding="utf-8")
        cls.server_source = (ROOT / "src/admira_mcp_server.py").read_text(encoding="utf-8")
        tree = ast.parse(cls.server_source)
        cls.definitions = ast.literal_eval(next(
            node.value for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "TOOL_DEFINITIONS" for target in node.targets)
        ))

    def test_immediate_activation_routes_to_resume(self):
        text = "\n".join((self.skill, self.tools, self.skills))
        self.assertIn("mcp_admira_resume_campaign", text)
        self.assertIn("immediate path never creates a cron", text.lower())
        self.assertIn("never create a cron for an immediate activation", text.lower())

    def test_scheduler_requires_explicit_future_timing_and_evidence(self):
        text = "\n".join((self.skill, self.tools, self.core))
        self.assertIn("explicitly future", text)
        self.assertIn("schedule_request_evidence", text)
        self.assertIn("literal", text)
        self.assertIn("without asking the buyer to repeat an exact sentence", text.lower())
        self.assertIn('"required": ["campaign_id", "scheduled_at", "buyer_authorized", "creative_ready_confirmed", "schedule_request_evidence"]', self.server_source)

    def test_mcp_descriptions_keep_routes_distinct(self):
        definitions = dict(self.definitions)
        resume = definitions["resume_campaign"]
        schedule = definitions["schedule_campaign_activation"]
        self.assertIn("now", resume)
        self.assertIn("do not create a cron", resume.lower())
        self.assertIn("future local date/time", schedule)
        self.assertIn("schedule_request_evidence", schedule)
        self.assertIn("now/immediately", schedule.lower())


if __name__ == "__main__":
    unittest.main()
