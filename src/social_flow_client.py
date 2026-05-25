#!/usr/bin/env python3
"""Thin execution wrapper around social-cli and Telegram notifications."""
import json
import subprocess
import urllib.parse
import urllib.request
from dataclasses import asdict

from security import redact_payload


class SocialFlowClient:
    def __init__(self, config):
        self.config = config

    def run(self, args, live_required=True, mutation=False, approved=False):
        command = [self.config.social_cli] + list(args)
        record = {
            "command": command,
            "mode": self.config.mode,
            "approved_execution": bool(approved),
            "executed": self.config.live or approved or not live_required,
            "returncode": None,
            "stdout": "",
            "stderr": "",
        }
        if live_required and not self.config.live and not approved:
            record["stdout"] = "dry-run: command not executed"
            return record
        if mutation and self.config.live and not self.config.live_actions_enabled and not approved:
            record["executed"] = False
            record["stderr"] = "blocked: LIVE_ACTIONS_ENABLED=false"
            return record
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            record["returncode"] = completed.returncode
            record["stdout"] = completed.stdout.strip()
            record["stderr"] = completed.stderr.strip()
        except FileNotFoundError as exc:
            record["returncode"] = 127
            record["stderr"] = str(exc)
        return record

    def auth_status(self):
        return self.run(["auth", "status"], live_required=False)

    def marketing_status(self):
        return self.run(["marketing", "status"], live_required=False)

    def insights(self, preset="last_7d", level="campaign"):
        # Reading performance is safe in both control levels. Only mutations are gated by live mode.
        result = self.run(["marketing", "insights", "--preset", preset, "--level", level, "--format", "json"], live_required=False)
        result["data"] = None
        try:
            result["data"] = json.loads(result.get("stdout") or "{}")
        except json.JSONDecodeError:
            pass
        return result

    def pause(self, target_type, target_id, approved=False):
        return self.run(["marketing", "pause", target_type, target_id], live_required=True, mutation=True, approved=approved)

    def resume(self, target_type, target_id, approved=False):
        return self.run(["marketing", "resume", target_type, target_id], live_required=True, mutation=True, approved=approved)

    def set_budget(self, target_type, target_id, daily_budget_cents, approved=False):
        return self.run(["marketing", "set-budget", target_type, target_id, "--daily-budget", str(int(daily_budget_cents))], live_required=True, mutation=True, approved=approved)

    def create_campaign(self, ad_account_id, name, objective, daily_budget_cents=0, status="PAUSED", approved=False):
        args = ["marketing", "create-campaign"]
        if ad_account_id:
            args.append(ad_account_id)
        args.extend(["--name", name, "--objective", objective, "--status", status, "--json", "--yes"])
        if daily_budget_cents:
            args.extend(["--daily-budget", str(int(daily_budget_cents))])
        return self.run(args, live_required=True, mutation=True, approved=approved)

    def create_adset(self, campaign_id, name, targeting, daily_budget_cents=0, status="PAUSED", optimization_goal="LINK_CLICKS", approved=False):
        args = [
            "marketing", "create-adset", campaign_id,
            "--name", name,
            "--status", status,
            "--targeting", json.dumps(targeting),
            "--optimization-goal", optimization_goal,
            "--billing-event", "IMPRESSIONS",
            "--json",
            "--yes",
        ]
        if daily_budget_cents:
            args.extend(["--daily-budget", str(int(daily_budget_cents))])
        return self.run(args, live_required=True, mutation=True, approved=approved)

    def upload_image(self, ad_account_id, file_path, approved=False):
        args = ["marketing", "upload-image"]
        if ad_account_id:
            args.append(ad_account_id)
        args.extend(["--file", file_path, "--json"])
        return self.run(args, live_required=True, mutation=True, approved=approved)

    def create_creative(self, ad_account_id, name, page_id, link, body_text, headline, image_hash, cta, instagram_actor_id="", approved=False):
        args = ["marketing", "create-creative"]
        if ad_account_id:
            args.append(ad_account_id)
        args.extend([
            "--name", name,
            "--page-id", page_id,
            "--link", link,
            "--body-text", body_text,
            "--headline", headline,
            "--image-hash", image_hash,
            "--call-to-action", cta,
            "--json",
            "--yes",
        ])
        if instagram_actor_id:
            args.extend(["--instagram-actor-id", instagram_actor_id])
        return self.run(args, live_required=True, mutation=True, approved=approved)

    def create_ad(self, adset_id, name, creative_id, status="PAUSED", approved=False):
        return self.run(["marketing", "create-ad", adset_id, "--name", name, "--creative-id", creative_id, "--status", status, "--json", "--yes"], live_required=True, mutation=True, approved=approved)


def send_notification(config, title, message):
    if config.notify_channel != "telegram":
        return {"channel": "dashboard", "sent": False, "reason": "telegram not enabled"}
    if not config.telegram_bot_token or not config.telegram_chat_id:
        return {"channel": "telegram", "sent": False, "reason": "missing telegram credentials"}
    text = f"{title}\n\n{message}"
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": config.telegram_chat_id, "text": text}).encode("utf-8")
    try:
        with urllib.request.urlopen(url, data=payload, timeout=15) as response:
            body = response.read().decode("utf-8")
        return {"channel": "telegram", "sent": True, "response": body[:500]}
    except Exception as exc:
        return {"channel": "telegram", "sent": False, "reason": str(exc)}


def config_snapshot(config):
    return redact_payload(asdict(config))
