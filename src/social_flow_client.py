#!/usr/bin/env python3
"""Thin execution wrapper around social-cli and Telegram notifications."""
import json
import mimetypes
import subprocess
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

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
        if str(getattr(self.config, "meta_connector", "") or "").strip().lower() == "graph_api":
            fallback = self.graph_fallback(args, record, direct=True)
            if fallback:
                return fallback
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            record["returncode"] = completed.returncode
            record["stdout"] = completed.stdout.strip()
            record["stderr"] = completed.stderr.strip()
        except FileNotFoundError as exc:
            fallback = self.graph_fallback(args, record)
            if fallback:
                return fallback
            record["returncode"] = 127
            record["stderr"] = (
                f"{exc}. Meta action could not run because social-cli is not installed "
                "and no direct Meta Graph fallback is configured."
            )
        return record

    def graph_url(self, endpoint):
        endpoint = str(endpoint or "").lstrip("/")
        version = str(getattr(self.config, "meta_graph_api_version", "") or "v24.0").strip() or "v24.0"
        return f"https://graph.facebook.com/{version}/{endpoint}"

    def graph_record(self, record, endpoint, result):
        stdout = json.dumps(result.get("body") if isinstance(result.get("body"), dict) else {"error": result.get("body")}, ensure_ascii=False)
        return {
            **record,
            "connector": "graph_api_fallback",
            "graph_endpoint": endpoint,
            "returncode": 0 if result.get("ok") else int(result.get("status") or 1),
            "stdout": stdout if result.get("ok") else "",
            "stderr": "" if result.get("ok") else stdout,
        }

    def graph_local_record(self, record, endpoint, body, ok=True, status=200):
        stdout = json.dumps(body if isinstance(body, dict) else {"result": body}, ensure_ascii=False)
        return {
            **record,
            "connector": "graph_api_fallback",
            "graph_endpoint": endpoint,
            "returncode": 0 if ok else int(status or 1),
            "stdout": stdout if ok else "",
            "stderr": "" if ok else stdout,
        }

    def get_graph(self, endpoint, params=None):
        normalized = {}
        for key, value in (params or {}).items():
            if value in (None, ""):
                continue
            normalized[key] = json.dumps(value) if isinstance(value, (dict, list)) else value
        normalized["access_token"] = getattr(self.config, "meta_access_token", "")
        query = urllib.parse.urlencode(normalized).encode("utf-8").decode("utf-8")
        request = urllib.request.Request(
            f"{self.graph_url(endpoint)}?{query}",
            headers={"Accept": "application/json", "User-Agent": "AdmiraIA/1.0"},
            method="GET",
        )
        return self.perform_graph_request(request)

    def post_graph_form(self, endpoint, fields):
        body = urllib.parse.urlencode(fields).encode("utf-8")
        request = urllib.request.Request(
            self.graph_url(endpoint),
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        return self.perform_graph_request(request)

    def post_graph_multipart(self, endpoint, fields, files):
        boundary, body = self.encode_multipart(fields, files)
        request = urllib.request.Request(
            self.graph_url(endpoint),
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        return self.perform_graph_request(request)

    def perform_graph_request(self, request):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                headers = {}
                try:
                    headers = {
                        key: value
                        for key, value in response.headers.items()
                        if str(key).lower().startswith(("x-", "facebook-api", "x-app", "x-ad-account"))
                    }
                except Exception:
                    headers = {}
                return {"ok": True, "status": response.status, "body": json.loads(response.read().decode("utf-8")), "headers": headers}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = raw[:1000]
            return {"ok": False, "status": exc.code, "body": body}
        except Exception as exc:
            return {"ok": False, "status": None, "body": str(exc)}

    def encode_multipart(self, fields, files):
        boundary = f"----admirasocialfallback{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        chunks = []
        for name, value in fields.items():
            chunks.append(f"--{boundary}\r\n".encode("utf-8"))
            chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
            chunks.append(str(value).encode("utf-8"))
            chunks.append(b"\r\n")
        for name, path in files.items():
            file_path = Path(path)
            mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            chunks.append(f"--{boundary}\r\n".encode("utf-8"))
            chunks.append(f'Content-Disposition: form-data; name="{name}"; filename="{file_path.name}"\r\n'.encode("utf-8"))
            chunks.append(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
            with open(file_path, "rb") as handle:
                chunks.append(handle.read())
            chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        return boundary, b"".join(chunks)

    @staticmethod
    def flag(args, name, default=""):
        try:
            index = list(args).index(name)
            return str(args[index + 1])
        except (ValueError, IndexError):
            return default

    @staticmethod
    def positional(args, index, default=""):
        try:
            value = str(args[index])
        except (IndexError, TypeError):
            return default
        return default if value.startswith("--") else value

    @staticmethod
    def normalize_ad_account_id(value):
        raw = str(value or "").strip()
        if not raw:
            return ""
        return raw if raw.startswith("act_") else f"act_{raw}"

    @staticmethod
    def json_flag(args, name, default=None):
        raw = SocialFlowClient.flag(args, name, "")
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    @staticmethod
    def default_insight_fields(level):
        identity_fields = {
            "campaign": "campaign_id,campaign_name",
            "adset": "campaign_id,campaign_name,adset_id,adset_name",
            "ad": "campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name",
        }.get(str(level or "campaign").lower(), "campaign_id,campaign_name")
        return f"{identity_fields},date_start,date_stop,spend,impressions,clicks,inline_link_clicks,frequency,actions,action_values"

    @staticmethod
    def clean_graph_fields(value, fallback):
        fields = str(value or "").strip()
        return fields if fields else fallback

    @staticmethod
    def normalize_optimization_goal(value):
        goal = str(value or "").strip().upper()
        aliases = {
            "CONVERSIONS": "OFFSITE_CONVERSIONS",
            "WEBSITE_CONVERSIONS": "OFFSITE_CONVERSIONS",
            "WEB_CONVERSIONS": "OFFSITE_CONVERSIONS",
            "PURCHASES": "OFFSITE_CONVERSIONS",
            "SALES": "OFFSITE_CONVERSIONS",
            "LEADS": "LEAD_GENERATION",
            "QUALITY_LEADS": "QUALITY_LEAD",
        }
        return aliases.get(goal, goal or "LINK_CLICKS")

    @staticmethod
    def normalize_custom_event_type(value):
        raw = str(value or "").strip()
        compact = raw.lower().replace("-", "_").replace(" ", "_")
        squashed = compact.replace("_", "")
        aliases = {
            "purchase": "PURCHASE",
            "purchases": "PURCHASE",
            "omni_purchase": "PURCHASE",
            "offsite_conversion.fb_pixel_purchase": "PURCHASE",
            "initiatecheckout": "INITIATED_CHECKOUT",
            "initiatedcheckout": "INITIATED_CHECKOUT",
            "initiate_checkout": "INITIATED_CHECKOUT",
            "initiated_checkout": "INITIATED_CHECKOUT",
            "offsite_conversion.fb_pixel_initiate_checkout": "INITIATED_CHECKOUT",
            "offsite_conversion.fb_pixel_initiated_checkout": "INITIATED_CHECKOUT",
            "addtocart": "ADD_TO_CART",
            "add_to_cart": "ADD_TO_CART",
            "offsite_conversion.fb_pixel_add_to_cart": "ADD_TO_CART",
            "viewcontent": "VIEW_CONTENT",
            "view_content": "VIEW_CONTENT",
            "offsite_conversion.fb_pixel_view_content": "VIEW_CONTENT",
            "lead": "LEAD",
            "leads": "LEAD",
            "offsite_conversion.fb_pixel_lead": "LEAD",
            "complete_registration": "COMPLETE_REGISTRATION",
            "completeregistration": "COMPLETE_REGISTRATION",
            "contact": "CONTACT",
        }
        if compact in aliases:
            return aliases[compact]
        if squashed in aliases:
            return aliases[squashed]
        return raw.upper()[:80]

    @classmethod
    def normalize_promoted_object(cls, value):
        if not isinstance(value, dict):
            return value
        promoted = dict(value)
        if promoted.get("custom_event_type"):
            promoted["custom_event_type"] = cls.normalize_custom_event_type(promoted.get("custom_event_type"))
        return promoted

    @staticmethod
    def normalize_bid_strategy(value):
        strategy = str(value or "").strip().upper().replace(" ", "_").replace("-", "_")
        aliases = {
            "LOWEST_COST": "LOWEST_COST_WITHOUT_CAP",
            "LOWEST_COST_NO_CAP": "LOWEST_COST_WITHOUT_CAP",
            "WITHOUT_CAP": "LOWEST_COST_WITHOUT_CAP",
            "BID_CAP": "LOWEST_COST_WITH_BID_CAP",
            "CAP": "LOWEST_COST_WITH_BID_CAP",
            "TARGET": "TARGET_COST",
        }
        return aliases.get(strategy, strategy)

    @classmethod
    def normalize_bidding_config(cls, value):
        if not isinstance(value, dict):
            return value
        bidding = dict(value)
        strategy = cls.normalize_bid_strategy(bidding.get("bid_strategy"))
        try:
            amount = int(float(str(bidding.get("bid_amount") or 0).replace(",", "")))
        except (TypeError, ValueError):
            amount = 0
        amount_required = {"LOWEST_COST_WITH_BID_CAP", "TARGET_COST", "COST_CAP"}
        clean = {}
        if strategy:
            if strategy in amount_required and amount <= 0:
                strategy = "LOWEST_COST_WITHOUT_CAP"
            clean["bid_strategy"] = strategy
        elif amount > 0:
            clean["bid_strategy"] = "LOWEST_COST_WITH_BID_CAP"
        if amount > 0 and clean.get("bid_strategy") in amount_required:
            clean["bid_amount"] = amount
        return clean

    def graph_fallback(self, args, record, direct=False):
        if not getattr(self.config, "meta_access_token", ""):
            return None
        args = list(args)
        if len(args) < 2:
            return None
        area = args[0]
        action = args[1]
        access_token = getattr(self.config, "meta_access_token", "")
        ad_account_id = self.normalize_ad_account_id(self.positional(args, 2, getattr(self.config, "ad_account_id", "")))
        configured_ad_account_id = self.normalize_ad_account_id(getattr(self.config, "ad_account_id", ""))
        try:
            if area == "limits" and action == "check":
                account = configured_ad_account_id or ad_account_id
                endpoint = account
                result = self.get_graph(endpoint, {"fields": "id,name,account_status,disable_reason"})
                body = result.get("body") if isinstance(result.get("body"), dict) else {}
                body = {
                    "ok": bool(result.get("ok")),
                    "source": "graph_api_health_check",
                    "account": body,
                    "headers": result.get("headers") or {},
                    "note": "Meta Marketing API rate limits are exposed through response headers and 4xx errors, not through a generic limits endpoint.",
                }
                return self.graph_local_record(record, endpoint, body, ok=bool(result.get("ok")), status=result.get("status") or 1)
            if area == "policy" and action == "preflight":
                intent = self.positional(args, 2, "create Meta ad")
                endpoint = configured_ad_account_id or ad_account_id
                body = {
                    "ok": True,
                    "source": "graph_api_policy_preflight",
                    "intent": intent,
                    "action": self.flag(args, "--action", "create_ad"),
                    "policy_validation": "Meta does not provide a generic policy decision endpoint for plain text intent. Validate the actual campaign/ad/creative payload with Marketing API validation/execution options, then keep final spend behind approval.",
                    "supports_validate_only_payloads": True,
                }
                return self.graph_local_record(record, endpoint, body)
            if area != "marketing":
                return None
            if action == "status":
                endpoint = configured_ad_account_id or ad_account_id
                fields = "id,name,account_status,currency,timezone_name,disable_reason,business,created_time,amount_spent,balance,spend_cap"
                result = self.get_graph(endpoint, {"fields": fields})
                body = result.get("body") if isinstance(result.get("body"), dict) else {}
                if result.get("ok"):
                    body = {"ok": True, "account": body}
                return self.graph_record(record, endpoint, {"ok": result.get("ok"), "status": result.get("status"), "body": body})
            if action == "insights":
                endpoint = f"{configured_ad_account_id or ad_account_id}/insights"
                level = self.flag(args, "--level", "campaign")
                params = {
                    "date_preset": self.flag(args, "--preset", "last_7d"),
                    "level": level,
                    "fields": self.clean_graph_fields(self.flag(args, "--fields", ""), self.default_insight_fields(level)),
                    "action_report_time": "conversion",
                    "limit": self.flag(args, "--limit", "500"),
                }
                breakdowns = self.flag(args, "--breakdowns", "")
                if breakdowns:
                    params["breakdowns"] = breakdowns
                result = self.get_graph(endpoint, params)
                return self.graph_record(record, endpoint, result)
            if action == "audiences":
                endpoint = f"{ad_account_id}/customaudiences"
                limit = self.flag(args, "--limit", "50")
                params = {
                    "fields": "id,name,subtype,description,approximate_count,delivery_status,operation_status,time_created,time_updated",
                    "limit": limit,
                }
                return self.graph_record(record, endpoint, self.get_graph(endpoint, params))
            if action == "creatives":
                endpoint = f"{ad_account_id}/adcreatives"
                limit = self.flag(args, "--limit", "25")
                params = {
                    "fields": "id,name,effective_object_story_id,object_story_spec,asset_feed_spec,thumbnail_url,image_hash,video_id",
                    "limit": limit,
                }
                return self.graph_record(record, endpoint, self.get_graph(endpoint, params))
            if action == "create-campaign":
                endpoint = f"{ad_account_id}/campaigns"
                fields = {
                    "access_token": access_token,
                    "name": self.flag(args, "--name", "New Campaign"),
                    "objective": self.flag(args, "--objective", "OUTCOME_SALES"),
                    "status": self.flag(args, "--status", "PAUSED"),
                    "special_ad_categories": "[]",
                }
                daily_budget = self.flag(args, "--daily-budget", "")
                if daily_budget:
                    fields["daily_budget"] = daily_budget
                return self.graph_record(record, endpoint, self.post_graph_form(endpoint, fields))
            if action == "create-adset":
                campaign_id = self.positional(args, 2, "")
                endpoint = f"{configured_ad_account_id}/adsets"
                fields = {
                    "access_token": access_token,
                    "campaign_id": campaign_id,
                    "name": self.flag(args, "--name", "Ad Set"),
                    "status": self.flag(args, "--status", "PAUSED"),
                    "targeting": self.flag(args, "--targeting", "{}"),
                    "optimization_goal": self.normalize_optimization_goal(self.flag(args, "--optimization-goal", "LINK_CLICKS")),
                    "billing_event": self.flag(args, "--billing-event", "IMPRESSIONS"),
                }
                for source, target in (
                    ("--daily-budget", "daily_budget"),
                    ("--lifetime-budget", "lifetime_budget"),
                    ("--start-time", "start_time"),
                    ("--end-time", "end_time"),
                    ("--promoted-object", "promoted_object"),
                ):
                    value = self.flag(args, source, "")
                    if value:
                        if source == "--promoted-object":
                            try:
                                promoted_payload = json.loads(value)
                                value = json.dumps(self.normalize_promoted_object(promoted_payload))
                            except json.JSONDecodeError:
                                pass
                        fields[target] = value
                bidding = self.flag(args, "--bidding", "")
                if bidding:
                    try:
                        bidding_payload = json.loads(bidding)
                    except json.JSONDecodeError:
                        bidding_payload = {"bid_strategy": bidding}
                    if isinstance(bidding_payload, dict):
                        bidding_payload = self.normalize_bidding_config(bidding_payload)
                        if bidding_payload.get("bid_strategy"):
                            fields["bid_strategy"] = bidding_payload["bid_strategy"]
                        if bidding_payload.get("bid_amount"):
                            fields["bid_amount"] = bidding_payload["bid_amount"]
                return self.graph_record(record, endpoint, self.post_graph_form(endpoint, fields))
            if action == "upload-image":
                endpoint = f"{ad_account_id}/adimages"
                file_path = self.flag(args, "--file", "")
                if not file_path:
                    return None
                fields = {"access_token": access_token}
                return self.graph_record(record, endpoint, self.post_graph_multipart(endpoint, fields, {"filename": file_path}))
            if action == "upload-video":
                endpoint = f"{ad_account_id}/advideos"
                file_path = self.flag(args, "--file", "")
                file_url = self.flag(args, "--file-url", "")
                title = self.flag(args, "--title", "")
                fields = {"access_token": access_token}
                if title:
                    fields["title"] = title
                if file_url:
                    fields["file_url"] = file_url
                    return self.graph_record(record, endpoint, self.post_graph_form(endpoint, fields))
                if not file_path:
                    return None
                return self.graph_record(record, endpoint, self.post_graph_multipart(endpoint, fields, {"source": file_path}))
            if action == "create-creative":
                endpoint = f"{ad_account_id}/adcreatives"
                fields = {
                    "access_token": access_token,
                    "name": self.flag(args, "--name", "Ad Creative"),
                }
                object_story_spec = self.flag(args, "--object-story-spec", "")
                if not object_story_spec:
                    link = self.flag(args, "--cta-link", "") or self.flag(args, "--link", "")
                    video_id = self.flag(args, "--video-id", "")
                    image_hash = self.flag(args, "--image-hash", "")
                    image_url = self.flag(args, "--image-url", "")
                    cta = self.flag(args, "--call-to-action", "")
                    story = {
                        "page_id": self.flag(args, "--page-id", ""),
                        **({"instagram_actor_id": self.flag(args, "--instagram-actor-id", "")} if self.flag(args, "--instagram-actor-id", "") else {}),
                    }
                    if video_id:
                        video_data = {
                            "video_id": video_id,
                            "message": self.flag(args, "--body-text", ""),
                            "title": self.flag(args, "--headline", ""),
                        }
                        if image_url:
                            video_data["image_url"] = image_url
                        if cta:
                            video_data["call_to_action"] = {"type": cta, "value": {"link": link}}
                        story["video_data"] = video_data
                    else:
                        link_data = {
                            "link": link,
                            "message": self.flag(args, "--body-text", ""),
                            "name": self.flag(args, "--headline", ""),
                        }
                        if image_hash:
                            link_data["image_hash"] = image_hash
                        if image_url:
                            link_data["picture"] = image_url
                        if cta:
                            link_data["call_to_action"] = {"type": cta, "value": {"link": link}}
                        story["link_data"] = link_data
                    object_story_spec = json.dumps(story)
                fields["object_story_spec"] = object_story_spec
                return self.graph_record(record, endpoint, self.post_graph_form(endpoint, fields))
            if action == "create-ad":
                endpoint = f"{configured_ad_account_id}/ads"
                fields = {
                    "access_token": access_token,
                    "name": self.flag(args, "--name", "Ad"),
                    "adset_id": self.positional(args, 2, ""),
                    "creative": json.dumps({"creative_id": self.flag(args, "--creative-id", "")}),
                    "status": self.flag(args, "--status", "PAUSED"),
                }
                return self.graph_record(record, endpoint, self.post_graph_form(endpoint, fields))
            if action in {"pause", "resume"}:
                target_id = self.positional(args, 3, self.positional(args, 2, ""))
                endpoint = target_id
                fields = {"access_token": access_token, "status": "PAUSED" if action == "pause" else "ACTIVE"}
                return self.graph_record(record, endpoint, self.post_graph_form(endpoint, fields))
            if action == "set-budget":
                target_id = self.positional(args, 3, self.positional(args, 2, ""))
                daily_budget = self.flag(args, "--daily-budget", "")
                if not daily_budget:
                    return None
                endpoint = target_id
                fields = {"access_token": access_token, "daily_budget": daily_budget}
                return self.graph_record(record, endpoint, self.post_graph_form(endpoint, fields))
        except Exception as exc:
            return {
                **record,
                "connector": "graph_api_fallback",
                "returncode": 1,
                "stdout": "",
                "stderr": f"Graph API fallback failed: {exc}",
            }
        return None

    def auth_status(self):
        return self.run(["auth", "status"], live_required=False)

    def marketing_status(self):
        return self.run(["marketing", "status"], live_required=False)

    def insights(self, preset="last_7d", level="campaign", fields=None, breakdowns="", limit=None, timeout=None):
        # Reading performance is safe in both control levels. Only mutations are gated by live mode.
        args = ["marketing", "insights", "--preset", preset, "--level", level, "--json"]
        if fields:
            args.extend(["--fields", fields])
        if breakdowns:
            args.extend(["--breakdowns", breakdowns])
        if limit:
            args.extend(["--limit", str(int(limit))])
        if timeout:
            args.extend(["--timeout", str(int(timeout))])
        result = self.run(args, live_required=False)
        result["data"] = None
        try:
            result["data"] = json.loads(result.get("stdout") or "{}")
        except json.JSONDecodeError:
            pass
        return result

    def custom_audiences(self, ad_account_id="", limit=50):
        args = ["marketing", "audiences"]
        if ad_account_id:
            args.append(ad_account_id)
        args.extend(["--limit", str(int(limit)), "--json"])
        return self.run(args, live_required=False)

    def creatives(self, ad_account_id="", limit=25):
        args = ["marketing", "creatives"]
        if ad_account_id:
            args.append(ad_account_id)
        args.extend(["--limit", str(int(limit)), "--json"])
        return self.run(args, live_required=False)

    def rate_limits(self):
        return self.run(["limits", "check", "--json"], live_required=False)

    def policy_preflight(self, intent, action="create_ad"):
        args = ["policy", "preflight", str(intent or "create meta ad"), "--action", action, "--json"]
        return self.run(args, live_required=False)

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

    def create_adset(
        self,
        campaign_id,
        name,
        targeting,
        daily_budget_cents=0,
        status="PAUSED",
        optimization_goal="LINK_CLICKS",
        promoted_object=None,
        billing_event="IMPRESSIONS",
        bidding=None,
        lifetime_budget_cents=0,
        start_time="",
        end_time="",
        approved=False,
    ):
        optimization_goal = self.normalize_optimization_goal(optimization_goal)
        args = [
            "marketing", "create-adset", campaign_id,
            "--name", name,
            "--status", status,
            "--targeting", json.dumps(targeting),
            "--optimization-goal", optimization_goal,
            "--billing-event", billing_event,
            "--json",
            "--yes",
        ]
        if promoted_object:
            args.extend(["--promoted-object", json.dumps(self.normalize_promoted_object(promoted_object))])
        if bidding:
            args.extend(["--bidding", json.dumps(self.normalize_bidding_config(bidding))])
        if daily_budget_cents:
            args.extend(["--daily-budget", str(int(daily_budget_cents))])
        if lifetime_budget_cents:
            args.extend(["--lifetime-budget", str(int(lifetime_budget_cents))])
        if start_time:
            args.extend(["--start-time", start_time])
        if end_time:
            args.extend(["--end-time", end_time])
        return self.run(args, live_required=True, mutation=True, approved=approved)

    def upload_image(self, ad_account_id, file_path, approved=False):
        args = ["marketing", "upload-image"]
        if ad_account_id:
            args.append(ad_account_id)
        args.extend(["--file", file_path, "--json"])
        return self.run(args, live_required=True, mutation=True, approved=approved)

    def upload_video(self, ad_account_id, file_path="", file_url="", title="", approved=False):
        args = ["marketing", "upload-video"]
        if ad_account_id:
            args.append(ad_account_id)
        if file_path:
            args.extend(["--file", file_path])
        if file_url:
            args.extend(["--file-url", file_url])
        if title:
            args.extend(["--title", title])
        args.extend(["--json", "--yes"])
        return self.run(args, live_required=True, mutation=True, approved=approved)

    def create_creative(
        self,
        ad_account_id,
        name,
        page_id,
        link,
        body_text,
        headline,
        image_hash,
        cta,
        instagram_actor_id="",
        object_story_spec=None,
        image_url="",
        video_url="",
        video_id="",
        cta_link="",
        approved=False,
    ):
        args = ["marketing", "create-creative"]
        if ad_account_id:
            args.append(ad_account_id)
        args.extend(["--name", name])
        if object_story_spec:
            args.extend(["--object-story-spec", json.dumps(object_story_spec)])
        else:
            args.extend([
                "--page-id", page_id,
                "--link", link,
                "--body-text", body_text,
                "--headline", headline,
            ])
            if image_hash:
                args.extend(["--image-hash", image_hash])
            if image_url:
                args.extend(["--image-url", image_url])
            if video_url:
                args.extend(["--video-url", video_url])
            if video_id:
                args.extend(["--video-id", video_id])
            if cta:
                args.extend(["--call-to-action", cta])
            if cta_link:
                args.extend(["--cta-link", cta_link])
        args.extend(["--json", "--yes"])
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
