#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import model_health_watchdog as watchdog
import hermes_bridge


class ModelHealthWatchdogTest(unittest.TestCase):
    def config(self, brain="minimax"):
        return SimpleNamespace(
            agent_brain_provider=brain,
            agent_chat_provider="minimax" if brain == "minimax" else "hermes",
            agent_chat_model="MiniMax-M3",
            agent_chat_base_url="https://api.minimax.io/v1",
            agent_chat_api_key="test-key",
            hermes_model="gpt-5.4-mini",
            hermes_cli="hermes",
            hermes_home="",
            daily_brief_timezone="UTC",
        )

    @staticmethod
    def telegram(_config):
        return {
            "enabled": True,
            "bot_configured": True,
            "chat_id": "123",
            "mode": "hermes_gateway",
        }

    @staticmethod
    def runtime(_config):
        return {
            "provider": "admira-minimax",
            "model": "MiniMax-M3",
            "configured_provider": "admira-minimax",
            "configured_model": "MiniMax-M3",
        }

    def run_check(self, tmp, **overrides):
        calls = overrides.pop("calls", {})
        calls.setdefault("start", 0)
        calls.setdefault("stop", 0)
        calls.setdefault("doctor", 0)
        calls.setdefault("notify", [])
        calls.setdefault("reconcile", 0)

        def start(_config):
            calls["start"] += 1
            return {"started": True}

        def stop():
            calls["stop"] += 1

        def doctor(_config):
            calls["doctor"] += 1
            return {"ok": True, "reason": "doctor_ok"}

        def notify(issue, _context):
            calls["notify"].append(issue)
            return True

        def reconcile(_config):
            calls["reconcile"] += 1
            return {"ok": True, "updated": 0}

        kwargs = {
            "state_file": Path(tmp) / "watchdog.json",
            "log_path": Path(tmp) / "gateway.log",
            "telegram_status": self.telegram,
            "gateway_status": lambda _config: {"process_running": True},
            "runtime_model_state": self.runtime,
            "codex_session_status": lambda _config, timeout=10: {"ready": True},
            "start_gateway": start,
            "stop_gateway": stop,
            "reconcile_crons": reconcile,
            "notify": notify,
            "doctor": doctor,
            "now_epoch": 1_000_000,
        }
        kwargs.update(overrides)
        result = watchdog.run_model_health_check(self.config(), **kwargs)
        return result, calls

    def test_healthy_runtime_is_not_restarted_and_reconciles_crons(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "gateway.log").write_text("old fixed error\n", encoding="utf-8")
            result, calls = self.run_check(tmp)
            self.assertEqual(result["status"], "healthy")
            self.assertEqual(calls["start"], 0)
            self.assertEqual(calls["stop"], 0)
            self.assertEqual(calls["reconcile"], 1)

    def test_dead_gateway_is_restarted_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = {}
            result, calls = self.run_check(
                tmp,
                calls=calls,
                gateway_status=lambda _config: {"process_running": False},
            )
            self.assertEqual(result["action"], "gateway_restarted")
            self.assertEqual((calls["stop"], calls["start"]), (1, 1))
            self.assertEqual(calls["doctor"], 0)

    def test_revoked_codex_asks_for_reconnect_without_restart_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = {}
            codex_config = self.config("openai_codex")
            common = {
                "state_file": Path(tmp) / "watchdog.json",
                "log_path": Path(tmp) / "gateway.log",
                "telegram_status": self.telegram,
                "gateway_status": lambda _config: {"process_running": True},
                "runtime_model_state": self.runtime,
                "codex_session_status": lambda _config, timeout=10: {"ready": False, "reauth_required": True},
                "start_gateway": lambda _config: calls.__setitem__("start", calls.get("start", 0) + 1) or {"started": True},
                "stop_gateway": lambda: calls.__setitem__("stop", calls.get("stop", 0) + 1),
                "reconcile_crons": lambda _config: {"ok": True},
                "notify": lambda issue, _context: calls.setdefault("notify", []).append(issue) or True,
                "doctor": lambda _config: {"ok": True},
            }
            first = watchdog.run_model_health_check(codex_config, now_epoch=1_000_000, **common)
            second = watchdog.run_model_health_check(codex_config, now_epoch=1_000_060, **common)
            self.assertEqual(first["action"], "buyer_notified")
            self.assertEqual(second["action"], "waiting_for_buyer")
            self.assertEqual(calls.get("notify"), ["credential_reconnect_required"])
            self.assertEqual(calls.get("start", 0), 0)
            self.assertEqual(calls.get("stop", 0), 0)

    def test_fresh_crash_loop_runs_read_only_doctor_then_bounded_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "gateway.log"
            log.write_text("startup\n", encoding="utf-8")
            calls = {}
            first, calls = self.run_check(tmp, calls=calls)
            self.assertEqual(first["status"], "healthy")
            with log.open("a", encoding="utf-8") as handle:
                handle.write("Hermes Gateway exited with code 1; restarting in 3s\n")
                handle.write("Hermes Gateway exited with code 1; restarting in 3s\n")
            second, calls = self.run_check(tmp, calls=calls, now_epoch=1_000_120)
            self.assertEqual(second["issue"], "gateway_crash_loop")
            self.assertEqual(second["action"], "gateway_restarted")
            self.assertEqual(calls["doctor"], 1)
            self.assertEqual((calls["stop"], calls["start"]), (1, 1))

    def test_rate_limit_never_restarts_or_runs_doctor(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "gateway.log"
            log.write_text("startup\n", encoding="utf-8")
            calls = {}
            self.run_check(tmp, calls=calls)
            with log.open("a", encoding="utf-8") as handle:
                handle.write("Provider quota exhausted (429); retry later\n")
            result, calls = self.run_check(tmp, calls=calls, now_epoch=1_000_120)
            self.assertEqual(result["status"], "degraded_rate_limit")
            self.assertEqual(result["action"], "fallback_left_running")
            self.assertEqual(calls["start"], 0)
            self.assertEqual(calls["doctor"], 0)

    def test_restart_budget_blocks_loops_and_notifies_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "watchdog.json"
            state_file.write_text(
                json.dumps({
                    "version": 1,
                    "restart_epochs": [999_700, 999_800],
                    "last_issue": "gateway_down",
                    "consecutive_failures": 2,
                }),
                encoding="utf-8",
            )
            calls = {}
            result, calls = self.run_check(
                tmp,
                calls=calls,
                gateway_status=lambda _config: {"process_running": False},
            )
            self.assertEqual(result["action"], "restart_budget_exhausted")
            self.assertEqual(calls["start"], 0)
            self.assertEqual(calls["notify"], ["restart_budget_exhausted"])

    def test_codex_status_accepts_successful_non_revoked_status_without_literal_logged_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth_path = Path(tmp) / "auth.json"
            auth_path.write_text(
                json.dumps({"credential_pool": {"openai-codex": [{}]}}),
                encoding="utf-8",
            )

            class Completed:
                returncode = 0
                stdout = "Provider: OpenAI Codex\nOpenAI Codex account ready\n"
                stderr = ""

            config = SimpleNamespace(
                hermes_cli="hermes",
                hermes_home=tmp,
                hermes_status_timeout_seconds=5,
                daily_brief_timezone="UTC",
                agent_brain_provider="openai_codex",
                hermes_model="gpt-5.4-mini",
            )
            old_which = hermes_bridge.shutil.which
            old_run = hermes_bridge.subprocess.run
            try:
                hermes_bridge.shutil.which = lambda _command: "/usr/local/bin/hermes"
                hermes_bridge.subprocess.run = lambda *_args, **_kwargs: Completed()
                status = hermes_bridge.hermes_codex_session_status(config)
            finally:
                hermes_bridge.shutil.which = old_which
                hermes_bridge.subprocess.run = old_run
            self.assertTrue(status["ready"])
            self.assertTrue(status["authenticated"])


if __name__ == "__main__":
    unittest.main()
