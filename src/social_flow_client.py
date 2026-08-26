#!/usr/bin/env python3
"""Meta Graph API execution wrapper and Telegram notifications."""
import json
import mimetypes
import os
import time
import unicodedata
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from security import redact_payload


class SocialFlowClient:
    # Meta's native page_welcome_message schema stores the customer action as
    # an ice-breaker title.  Meta rejects titles over 80 characters.  Keep the
    # limit explicit here so a failed creative never becomes a partial Meta
    # object merely because the approved WhatsApp opener was too long.
    META_PAGE_WELCOME_ACTION_MAX_LENGTH = 80

    def __init__(self, config):
        self.config = config

    def meta_page_token(self):
        """Return the unified Meta credential, with legacy fallback.

        New installations grant Ads and Page permissions to one token. The
        old publishing-only variable remains a migration fallback so an
        existing installation is not broken during upgrade.
        """
        return str(
            getattr(self.config, "meta_access_token", "")
            or getattr(self.config, "meta_publishing_access_token", "")
            or ""
        ).strip()

    def legacy_publishing_token(self):
        """Return the old publishing-only token for migration fallback paths."""
        return str(
            getattr(self.config, "meta_publishing_access_token", "")
            or getattr(self.config, "meta_access_token", "")
            or ""
        ).strip()

    def run(self, args, live_required=True, mutation=False, approved=False):
        operation = ["meta-graph"] + list(args)
        record = {
            "command": operation,
            "operation": list(args),
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
        if mutation and live_required and not approved:
            record["executed"] = False
            record["stderr"] = "blocked: approval_required"
            return record
        result = self.graph_execute(args, record)
        if result:
            return result
        record["returncode"] = 1
        record["stderr"] = "Unsupported Meta Graph operation or missing Meta access token."
        return record

    def graph_url(self, endpoint):
        endpoint = str(endpoint or "").lstrip("/")
        version = str(getattr(self.config, "meta_graph_api_version", "") or "v24.0").strip() or "v24.0"
        return f"https://graph.facebook.com/{version}/{endpoint}"

    def graph_record(self, record, endpoint, result):
        stdout = json.dumps(result.get("body") if isinstance(result.get("body"), dict) else {"error": result.get("body")}, ensure_ascii=False)
        return {
            **record,
            "connector": "graph_api",
            "graph_endpoint": endpoint,
            "returncode": 0 if result.get("ok") else int(result.get("status") or 1),
            "stdout": stdout if result.get("ok") else "",
            "stderr": "" if result.get("ok") else stdout,
        }

    def graph_local_record(self, record, endpoint, body, ok=True, status=200):
        stdout = json.dumps(body if isinstance(body, dict) else {"result": body}, ensure_ascii=False)
        return {
            **record,
            "connector": "graph_api",
            "graph_endpoint": endpoint,
            "returncode": 0 if ok else int(status or 1),
            "stdout": stdout if ok else "",
            "stderr": "" if ok else stdout,
        }

    def get_graph(self, endpoint, params=None, access_token=""):
        normalized = {}
        for key, value in (params or {}).items():
            if value in (None, ""):
                continue
            normalized[key] = json.dumps(value) if isinstance(value, (dict, list)) else value
        normalized["access_token"] = access_token or getattr(self.config, "meta_access_token", "")
        query = urllib.parse.urlencode(normalized).encode("utf-8").decode("utf-8")
        request = urllib.request.Request(
            f"{self.graph_url(endpoint)}?{query}",
            headers={"Accept": "application/json", "User-Agent": "AdmiraIA/1.0"},
            method="GET",
        )
        return self.perform_graph_request(request)

    def post_graph_form(self, endpoint, fields):
        normalized = {}
        for key, value in (fields or {}).items():
            if value in (None, ""):
                continue
            normalized[key] = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
        body = urllib.parse.urlencode(normalized).encode("utf-8")
        request = urllib.request.Request(
            self.graph_url(endpoint),
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        return self.perform_graph_request(request)

    def delete_graph_object(self, endpoint, access_token=""):
        token = access_token or getattr(self.config, "meta_access_token", "")
        query = urllib.parse.urlencode({"access_token": token}).encode("utf-8").decode("utf-8")
        request = urllib.request.Request(
            f"{self.graph_url(endpoint)}?{query}",
            headers={"Accept": "application/json", "User-Agent": "AdmiraIA/1.0"},
            method="DELETE",
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

    def page_access_token(self, page_id, user_token):
        page_id = str(page_id or "").strip()
        user_token = str(user_token or "").strip()
        if not page_id or not user_token:
            return {"ok": False, "access_token": "", "page": {}, "error": "missing_page_or_token"}
        result = self.get_graph("me/accounts", {"fields": "id,name,access_token", "limit": "200"}, access_token=user_token)
        body = result.get("body") if isinstance(result.get("body"), dict) else {}
        for page in body.get("data") or []:
            if str(page.get("id") or "") == page_id:
                return {"ok": True, "access_token": page.get("access_token") or user_token, "page": page, "source": "me_accounts"}
        direct_attempts = []
        for fields in ("id,name,access_token", "id,name"):
            direct = self.get_graph(page_id, {"fields": fields}, access_token=user_token)
            direct_body = direct.get("body") if isinstance(direct.get("body"), dict) else {}
            direct_error = (direct_body.get("error") or {}).get("message", "") if isinstance(direct_body.get("error"), dict) else ""
            direct_attempts.append(
                {
                    "fields": fields,
                    "ok": bool(direct.get("ok")),
                    "status": direct.get("status"),
                    "matched": str(direct_body.get("id") or "") == page_id,
                    "error": direct_error,
                }
            )
            if direct.get("ok") and str(direct_body.get("id") or "") == page_id:
                return {
                    "ok": True,
                    "access_token": direct_body.get("access_token") or user_token,
                    "page": direct_body,
                    "source": "direct_page_lookup",
                    "lookup_fields": fields,
                    "used_direct_page_token": not bool(direct_body.get("access_token")),
                }
            if not direct_error:
                break
            if "nonexisting field" not in direct_error.lower() and "unknown field" not in direct_error.lower():
                break
        last_direct = direct_attempts[-1] if direct_attempts else {}
        direct_errors = [str(item.get("error") or "") for item in direct_attempts if item.get("error")]
        return {
            "ok": False,
            "access_token": user_token,
            "page": {},
            "error": "page_not_found",
            "lookup_methods": {
                "me_accounts_ok": bool(result.get("ok")),
                "me_accounts_count": len(body.get("data") or []) if isinstance(body.get("data"), list) else 0,
                "direct_page_lookup_ok": any(bool(item.get("matched")) for item in direct_attempts),
                "direct_page_lookup_status": last_direct.get("status"),
                "direct_page_lookup_error": " | ".join(direct_errors)[:500],
                "direct_page_lookup_attempts": [
                    {
                        "fields": item.get("fields"),
                        "ok": bool(item.get("ok")),
                        "status": item.get("status"),
                        "matched": bool(item.get("matched")),
                    }
                    for item in direct_attempts
                ],
            },
        }

    def resolve_whatsapp_phone_number(self, page_id):
        """Resolve the WhatsApp identifier Meta already accepts for a Page.

        A Page linked to the WhatsApp Business mobile app can return an empty
        ``whatsapp_number`` field even while Ads Manager has valid native
        click-to-WhatsApp ad sets. In that case, recover the value from the
        promoted object of the most recent matching native ad set.
        """
        page_id = str(page_id or "").strip()
        ad_account_id = self.normalize_ad_account_id(getattr(self.config, "ad_account_id", ""))
        access_token = str(getattr(self.config, "meta_access_token", "") or "").strip()
        if not page_id or not ad_account_id or not access_token:
            return {
                "ok": False,
                "whatsapp_phone_number": "",
                "source": "meta_live",
                "reason": "missing_page_account_or_token",
            }

        page_result = self.get_graph(page_id, {"fields": "whatsapp_number"}, access_token=access_token)
        page_body = page_result.get("body") if isinstance(page_result.get("body"), dict) else {}
        page_number = "".join(character for character in str(page_body.get("whatsapp_number") or "") if character.isdigit())
        if page_number:
            return {
                "ok": True,
                "whatsapp_phone_number": page_number,
                "source": "page.whatsapp_number",
                "page_id": page_id,
            }

        adsets_result = self.get_graph(
            f"{ad_account_id}/adsets",
            {
                "fields": "id,name,status,effective_status,updated_time,destination_type,promoted_object",
                "limit": "500",
            },
            access_token=access_token,
        )
        adsets_body = adsets_result.get("body") if isinstance(adsets_result.get("body"), dict) else {}
        candidates = []
        for adset in adsets_body.get("data") or []:
            if not isinstance(adset, dict) or str(adset.get("destination_type") or "").upper() != "WHATSAPP":
                continue
            promoted = adset.get("promoted_object") if isinstance(adset.get("promoted_object"), dict) else {}
            if str(promoted.get("page_id") or "").strip() != page_id:
                continue
            number = "".join(character for character in str(promoted.get("whatsapp_phone_number") or "") if character.isdigit())
            if not number:
                continue
            status = str(adset.get("effective_status") or adset.get("status") or "").upper()
            status_rank = 2 if status in {"ACTIVE", "PAUSED", "CAMPAIGN_PAUSED", "ADSET_PAUSED"} else 1
            candidates.append((status_rank, str(adset.get("updated_time") or ""), number, adset))
        if not candidates:
            page_error = page_body.get("error") if isinstance(page_body.get("error"), dict) else {}
            page_error_code = str(page_error.get("code") or "").strip()
            page_error_message = str(page_error.get("message") or "").strip()
            # A blank `whatsapp_number` is normal for some Business Suite
            # links, but a Graph permission error is not. Keep the historical
            # ad-set fallback above, then surface this as a deterministic
            # preflight blocker instead of pretending no number exists and
            # letting a campaign become partial later.
            permission_missing = page_error_code in {"10", "200"} and (
                "pages_read_engagement" in page_error_message.lower()
                or "page public" in page_error_message.lower()
            )
            return {
                "ok": False,
                "whatsapp_phone_number": "",
                "source": "meta_live",
                "reason": (
                    "page_read_permission_missing_for_whatsapp"
                    if permission_missing
                    else "no_page_linked_whatsapp_number_found"
                ),
                "page_lookup_ok": bool(page_result.get("ok")),
                "adsets_lookup_ok": bool(adsets_result.get("ok")),
                "page_error_code": page_error_code,
                "page_error_message": page_error_message[:240],
            }
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        _, _, number, adset = candidates[0]
        return {
            "ok": True,
            "whatsapp_phone_number": number,
            "source": "historical_whatsapp_adset",
            "page_id": page_id,
            "adset_id": str(adset.get("id") or ""),
            "adset_name": str(adset.get("name") or ""),
        }

    def publishing_ads_capability(self):
        """Verify that the Live publishing credential can create ad assets."""
        cached = getattr(self, "_publishing_ads_capability_cache", None)
        if isinstance(cached, dict):
            return cached
        token = self.meta_page_token()
        ad_account_id = self.normalize_ad_account_id(getattr(self.config, "ad_account_id", ""))
        if not token or not ad_account_id:
            result = {
                "ok": False,
                "source": "publishing_live_app",
                "reason": "missing_publishing_token_or_ad_account",
                "granted_permissions": [],
            }
            self._publishing_ads_capability_cache = result
            return result
        permissions_result = self.get_graph("me/permissions", {}, access_token=token)
        permissions_body = permissions_result.get("body") if isinstance(permissions_result.get("body"), dict) else {}
        granted = sorted({
            str(item.get("permission") or "")
            for item in (permissions_body.get("data") or [])
            if isinstance(item, dict) and str(item.get("status") or "").lower() == "granted"
        })
        account_result = self.get_graph(ad_account_id, {"fields": "id,name,account_status"}, access_token=token)
        result = {
            "ok": "ads_management" in granted and bool(account_result.get("ok")),
            "source": "publishing_live_app",
            "reason": "" if "ads_management" in granted and account_result.get("ok") else "publishing_token_missing_ads_management_or_account_access",
            "granted_permissions": granted,
            "ads_management_granted": "ads_management" in granted,
            "ads_read_granted": "ads_read" in granted,
            "ad_account_access": bool(account_result.get("ok")),
            "ad_account_status": account_result.get("status"),
        }
        self._publishing_ads_capability_cache = result
        return result

    @staticmethod
    def page_post_id_from_body(page_id, body):
        if not isinstance(body, dict):
            return ""
        post_id = str(body.get("post_id") or body.get("object_story_id") or "").strip()
        if post_id:
            return post_id
        media_id = str(body.get("id") or "").strip()
        if media_id and "_" not in media_id and str(page_id or "").strip():
            return f"{str(page_id).strip()}_{media_id}"
        return media_id

    def page_video_ad_post_details(self, page_id, video_id, page_token):
        """Resolve the real Page post ID for a Page video uploaded as an ads post.

        The Page videos edge returns the video object ID first. That ID is not
        always the promotable Page post ID. Meta exposes the actual post through
        the video's `post_id` field; ad creatives must use page_id_post_id.
        """
        page_id = str(page_id or "").strip()
        video_id = str(video_id or "").strip()
        page_token = str(page_token or "").strip()
        if not page_id or not video_id or not page_token:
            return {"ok": False, "error": "missing_page_video_lookup_detail", "video_id": video_id}
        try:
            attempts = max(1, min(60, int(os.environ.get("META_VIDEO_POST_READY_ATTEMPTS", "30") or 30)))
        except ValueError:
            attempts = 30
        try:
            sleep_seconds = max(0.0, min(10.0, float(os.environ.get("META_VIDEO_POST_READY_SLEEP_SECONDS", "3") or 3)))
        except ValueError:
            sleep_seconds = 3.0
        last = {}
        last_object_story_id = ""
        last_page_post_id = ""
        last_thumbnail_url = ""
        last_status = {}
        for attempt in range(1, attempts + 1):
            result = self.get_graph(video_id, {"fields": "id,post_id,picture,status", "access_token": page_token}, access_token=page_token)
            body = result.get("body") if isinstance(result.get("body"), dict) else {}
            last = {
                "ok": bool(result.get("ok")),
                "status": result.get("status"),
                "body": body,
                "attempt": attempt,
            }
            raw_post_id = str(body.get("post_id") or "").strip()
            object_story_id = raw_post_id if raw_post_id.startswith(f"{page_id}_") else (f"{page_id}_{raw_post_id}" if raw_post_id else "")
            video_status = body.get("status") if isinstance(body.get("status"), dict) else {}
            ready = self.page_video_status_ready(video_status)
            if object_story_id:
                last_object_story_id = object_story_id
                last_page_post_id = raw_post_id
            if body.get("picture"):
                last_thumbnail_url = str(body.get("picture") or "").strip()
            if video_status:
                last_status = video_status
            if result.get("ok") and object_story_id and ready:
                return {
                    "ok": True,
                    "video_id": video_id,
                    "page_post_id": raw_post_id,
                    "object_story_id": object_story_id,
                    "thumbnail_url": str(body.get("picture") or "").strip(),
                    "status": video_status,
                    "attempt": attempt,
                }
            phase_statuses = [
                str((video_status.get(key) or {}).get("status") or "").lower()
                for key in ("uploading_phase", "processing_phase", "publishing_phase")
                if isinstance(video_status.get(key), dict)
            ]
            if "error" in phase_statuses or "failed" in phase_statuses:
                break
            if attempt < attempts and sleep_seconds:
                time.sleep(sleep_seconds)
        return {
            "ok": False,
            "error": "video_post_not_ready" if last_object_story_id else "video_post_id_not_ready",
            "video_id": video_id,
            "page_post_id": last_page_post_id,
            "object_story_id": last_object_story_id,
            "thumbnail_url": last_thumbnail_url,
            "status": last_status,
            "last_lookup": last,
        }

    @staticmethod
    def page_video_status_ready(status):
        if not isinstance(status, dict):
            return False
        overall = str(status.get("video_status") or "").strip().lower()
        if overall in {"ready", "complete", "completed", "published"}:
            return True
        phase_values = []
        for key in ("uploading_phase", "processing_phase", "publishing_phase"):
            value = status.get(key)
            if isinstance(value, dict):
                phase_values.append(str(value.get("status") or "").strip().lower())
        if not phase_values:
            return False
        ready_values = {"complete", "completed", "ready", "published", "success", "succeeded"}
        return all(value in ready_values for value in phase_values)

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
        boundary = f"----admirametagraph{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
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
            "MESSAGES": "CONVERSATIONS",
            "MESSAGE": "CONVERSATIONS",
            "MESSAGING": "CONVERSATIONS",
            "MESSAGING_CONVERSATIONS": "CONVERSATIONS",
            "WHATSAPP": "CONVERSATIONS",
            "MESSENGER": "CONVERSATIONS",
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

    @staticmethod
    def normalize_call_to_action(value):
        cta = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
        aliases = {
            "COMPRAR": "SHOP_NOW",
            "COMPRA": "SHOP_NOW",
            "COMPRA_AHORA": "SHOP_NOW",
            "BUY": "SHOP_NOW",
            "BUY_NOW": "SHOP_NOW",
            "RESERVAR": "BOOK_NOW",
            "RESERVA": "BOOK_NOW",
            "RESERVA_AHORA": "BOOK_NOW",
            "BOOK": "BOOK_NOW",
            "CONTACTAR": "CONTACT_US",
            "CONTACTO": "CONTACT_US",
            "ESCRIBIR": "CONTACT_US",
            "MENSAJE": "MESSAGE_PAGE",
            "MESSAGE": "MESSAGE_PAGE",
            "SIGNUP": "SIGN_UP",
            "REGISTRO": "SIGN_UP",
            "REGISTRARME": "SIGN_UP",
            "INSCRIBIRME": "SIGN_UP",
            "SOLICITAR_INFO": "SIGN_UP",
        }
        return aliases.get(cta, cta or "LEARN_MORE")

    @classmethod
    def normalize_message_destination(cls, value):
        destination = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
        aliases = {
            "WA": "WHATSAPP",
            "WSP": "WHATSAPP",
            "WHATS": "WHATSAPP",
            "WHATSAPP_BUSINESS": "WHATSAPP",
            "CLICK_TO_WHATSAPP": "WHATSAPP",
            "CTWA": "WHATSAPP",
            "FB_MESSENGER": "MESSENGER",
            "FACEBOOK_MESSENGER": "MESSENGER",
            "CLICK_TO_MESSENGER": "MESSENGER",
            "CTM": "MESSENGER",
            "IG": "INSTAGRAM_DIRECT",
            "INSTAGRAM": "INSTAGRAM_DIRECT",
            "INSTAGRAM_DM": "INSTAGRAM_DIRECT",
            "INSTAGRAM_DIRECT_MESSAGE": "INSTAGRAM_DIRECT",
        }
        return aliases.get(destination, destination)

    @classmethod
    def message_destination_cta_type(cls, destination):
        normalized = cls.normalize_message_destination(destination)
        return {
            "WHATSAPP": "WHATSAPP_MESSAGE",
            "MESSENGER": "MESSAGE_PAGE",
            "INSTAGRAM_DIRECT": "INSTAGRAM_MESSAGE",
        }.get(normalized, "")

    @classmethod
    def default_message_destination_link(cls, destination, page_id=""):
        normalized = cls.normalize_message_destination(destination)
        if normalized == "WHATSAPP":
            return "https://api.whatsapp.com/send"
        if normalized == "MESSENGER" and str(page_id or "").strip():
            return f"https://m.me/{str(page_id).strip()}"
        if normalized == "INSTAGRAM_DIRECT":
            # The destination is selected by ``app_destination``. Meta still
            # expects link_data to carry a valid URL in some API versions, so
            # use Instagram's public root instead of inventing a profile URL.
            return "https://www.instagram.com/"
        return ""

    @staticmethod
    def page_welcome_message_payload(prefilled_message, greeting=""):
        """Build Meta's Visual Editor payload for click-to-message ads.

        Meta stores the customer-sendable first message as an icebreaker in
        AdCreative.page_welcome_message. Putting ``text=`` on a wa.me/API
        link is not equivalent: Meta can replace that value while building
        the native WhatsApp destination.
        """
        message = str(prefilled_message or "").strip()
        welcome = str(greeting or "").strip()
        # Messenger/Instagram briefs commonly provide only the visible
        # welcome text.  That is still enough to build a valid native welcome
        # screen: reuse it as the single customer action instead of silently
        # dropping page_welcome_message from the creative.
        customer_action = message or welcome
        if not customer_action:
            return {}
        welcome = welcome or "¡Hola! ¿Cómo podemos ayudarte?"
        return {
            "type": "VISUAL_EDITOR",
            "version": 2,
            "landing_screen_type": "welcome_message",
            "media_type": "text",
            "text_format": {
                "customer_action_type": "ice_breakers",
                "message": {"text": welcome, "ice_breakers": [{"title": customer_action}]},
            },
            "image_format": {
                "customer_action_type": "quick_replies",
                "message": {
                    "attachment": {
                        "type": "template",
                        "payload": {"template_type": "generic", "elements": [{"title": "", "buttons": []}]},
                    },
                    "quick_replies": [{"title": customer_action, "content_type": "text"}],
                    "text": welcome,
                },
            },
            "video_format": {
                "customer_action_type": "quick_replies",
                "message": {
                    "attachment": {"type": "video", "payload": {"attachment_id": ""}},
                    "quick_replies": [{"title": message, "content_type": "text"}],
                    "text": welcome,
                },
            },
            "user_edit": True,
            "surface": "visual_editor_new",
            "ice_breakers_edited": True,
            "autofill_message_edited": False,
        }

    @classmethod
    def validate_page_welcome_message(cls, prefilled_message, welcome_message=""):
        """Validate the native customer action without changing buyer text.

        Meta applies the 80-character limit to the Visual Editor ice-breaker
        title, not to the ad's primary text or headline.  Return a structured
        retryable diagnostic with the exact approved value and a separate,
        generic short proposal.  The proposal is never substituted silently.
        """
        message = str(prefilled_message or "").strip()
        welcome = str(welcome_message or "").strip()
        customer_action = message or welcome
        if not customer_action:
            return {"ok": True, "customer_action": "", "length": 0}

        maximum = cls.META_PAGE_WELCOME_ACTION_MAX_LENGTH
        length = len(customer_action)
        if length <= maximum:
            return {"ok": True, "customer_action": customer_action, "length": length}

        return {
            "ok": False,
            "error": "meta_page_welcome_message_too_long",
            "field": "page_welcome_message.text_format.message.ice_breakers[0].title",
            "max_length": maximum,
            "length": length,
            "approved_value": customer_action,
            # This is only a proposal.  It must be shown to the buyer and
            # explicitly approved before a retry; never replace approved_value.
            "safe_short_proposal": "Hola, quiero más información.",
            "retryable": True,
        }

    @staticmethod
    def default_lead_form_link(page_id=""):
        page = str(page_id or "").strip()
        return f"https://www.facebook.com/{page}" if page else "https://www.facebook.com"

    @staticmethod
    def normalize_lead_form_slug(value, fallback="custom_question"):
        text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
        text = "".join(char for char in text if not unicodedata.combining(char))
        chars = []
        for char in text:
            chars.append(char if char.isalnum() else "_")
        slug = "_".join(part for part in "".join(chars).split("_") if part)
        return (slug or fallback)[:80]

    @classmethod
    def normalize_lead_form_question(cls, value):
        aliases = {
            "correo": "EMAIL",
            "email": "EMAIL",
            "e_mail": "EMAIL",
            "mail": "EMAIL",
            "nombre": "FULL_NAME",
            "nombre_completo": "FULL_NAME",
            "full_name": "FULL_NAME",
            "fullname": "FULL_NAME",
            "first_name": "FIRST_NAME",
            "nombre_de_pila": "FIRST_NAME",
            "last_name": "LAST_NAME",
            "apellido": "LAST_NAME",
            "telefono": "PHONE",
            "teléfono": "PHONE",
            "phone": "PHONE",
            "phone_number": "PHONE",
            "numero": "PHONE",
            "número": "PHONE",
            "ciudad": "CITY",
            "city": "CITY",
            "provincia": "STATE",
            "estado": "STATE",
            "state": "STATE",
            "pais": "COUNTRY",
            "país": "COUNTRY",
            "country": "COUNTRY",
            "empresa": "COMPANY_NAME",
            "company": "COMPANY_NAME",
            "company_name": "COMPANY_NAME",
            "cargo": "JOB_TITLE",
            "job_title": "JOB_TITLE",
            "work_email": "WORK_EMAIL",
            "correo_laboral": "WORK_EMAIL",
            "zip": "ZIP",
            "postal": "ZIP",
            "codigo_postal": "ZIP",
            "código_postal": "ZIP",
        }
        # MCP/tool schemas sometimes wrap a question in an ``item`` (or
        # ``question``/``value``) envelope when the model emits an array of
        # objects.  Meta's ``/{page-id}/leadgen_forms`` edge accepts the
        # question object itself, never that envelope.  Unwrap it before
        # normalizing so the wire payload cannot contain ``item``.
        seen = set()
        while isinstance(value, dict):
            has_question_fields = any(
                key in value for key in ("type", "label", "question", "title", "key")
            )
            wrapper = next(
                (
                    key
                    for key in ("item", "question", "value")
                    if key in value
                    and isinstance(value.get(key), (dict, list, str))
                    and (len(value) == 1 or not has_question_fields)
                ),
                None,
            )
            if not wrapper or id(value) in seen:
                break
            seen.add(id(value))
            value = value.get(wrapper)

        if isinstance(value, str):
            raw = value.strip()
            normalized = cls.normalize_lead_form_slug(raw, raw).lower()
            return {"type": aliases.get(normalized, raw.upper().replace(" ", "_") or "EMAIL")}
        if not isinstance(value, dict):
            return {}
        raw_question = dict(value)
        label = str(
            raw_question.get("label")
            or raw_question.get("question")
            or raw_question.get("title")
            or ""
        ).strip()
        # Keep only fields from Meta's LeadGenQuestion schema.  In particular,
        # never forward model/tool bookkeeping keys such as ``item``.
        allowed_keys = {
            "type",
            "key",
            "label",
            "options",
            "conditional_questions_choices",
            "conditional_questions_group_id",
            "dependent_conditional_questions",
            "inline_context",
        }
        question = {
            key: val
            for key, val in value.items()
            if key in allowed_keys and val not in (None, "")
        }
        raw_type = str(question.get("type") or ("CUSTOM" if label else "")).strip()
        normalized = cls.normalize_lead_form_slug(raw_type, raw_type).lower()
        if raw_type:
            question["type"] = aliases.get(normalized, raw_type.upper().replace(" ", "_"))
        if question.get("type") == "CUSTOM":
            if label:
                question["label"] = label
            if not question.get("key"):
                question["key"] = cls.normalize_lead_form_slug(label or "custom_question")
        return question

    @classmethod
    def normalize_lead_form_questions(cls, value):
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = [item.strip() for item in text.split(",") if item.strip()]
        else:
            parsed = value
        if not isinstance(parsed, list):
            parsed = [parsed] if parsed else []
        questions = []
        for item in parsed:
            question = cls.normalize_lead_form_question(item)
            if question:
                questions.append(question)
        return questions

    @staticmethod
    def normalize_lead_form_form_type(value):
        raw = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
        aliases = {
            "MORE_VOLUME": "MORE_VOLUME",
            "VOLUME": "MORE_VOLUME",
            "MAS_VOLUMEN": "MORE_VOLUME",
            "MÁS_VOLUMEN": "MORE_VOLUME",
            "HIGHER_INTENT": "HIGHER_INTENT",
            "HIGH_INTENT": "HIGHER_INTENT",
            "MAYOR_INTENCION": "HIGHER_INTENT",
            "MAYOR_INTENCIÓN": "HIGHER_INTENT",
            "CALIDAD": "HIGHER_INTENT",
        }
        return aliases.get(raw, raw)

    @classmethod
    def destination_type_for_message_destination(cls, destination):
        normalized = cls.normalize_message_destination(destination)
        return {
            "WHATSAPP": "WHATSAPP",
            "MESSENGER": "MESSENGER",
            "INSTAGRAM_DIRECT": "INSTAGRAM_DIRECT",
        }.get(normalized, normalized)

    @classmethod
    def normalize_destination_type(cls, value):
        raw = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
        aliases = {
            "WA": "WHATSAPP",
            "WSP": "WHATSAPP",
            "WHATSAPP_BUSINESS": "WHATSAPP",
            "FB_MESSENGER": "MESSENGER",
            "FACEBOOK_MESSENGER": "MESSENGER",
            "IG": "INSTAGRAM_DIRECT",
            "INSTAGRAM": "INSTAGRAM_DIRECT",
            "INSTAGRAM_DM": "INSTAGRAM_DIRECT",
            "MESSAGING_WHATSAPP": "WHATSAPP",
            "MESSAGING_MESSENGER": "MESSENGER",
        }
        return aliases.get(raw, raw)

    @classmethod
    def page_post_call_to_action(cls, cta, link, message_destination="", lead_gen_form_id=""):
        # Lead-form ads need the form association on the native Page post
        # itself.  If it is only passed to the later AdCreative request, the
        # dark post exists but Meta cannot promote it as a lead-form ad.
        lead_form_id = str(lead_gen_form_id or "").strip()
        if lead_form_id:
            return json.dumps(
                {
                    "type": cls.normalize_call_to_action(cta or "SIGN_UP"),
                    "value": {"lead_gen_form_id": lead_form_id},
                },
                ensure_ascii=False,
            )
        destination = cls.normalize_message_destination(message_destination)
        cta_type = cls.message_destination_cta_type(destination) if destination else cls.normalize_call_to_action(cta)
        target = str(link or "").strip()
        if not target and not destination:
            return ""
        value = {"app_destination": destination} if destination else {"link": target}
        if target and destination:
            value["link"] = target
        return json.dumps(
            {
                "type": cta_type,
                "value": value,
            },
            ensure_ascii=False,
        )

    def create_linked_image_page_post(
        self,
        page_id,
        page_token,
        message,
        link,
        image_id,
        cta,
        unpublished_type,
        message_destination="",
        lead_gen_form_id="",
        published=False,
    ):
        fields = {
            "access_token": page_token,
            "published": "true" if published else "false",
            # Graph's Page feed endpoint expects each attachment as an indexed
            # form field (`attached_media[0]`), not one JSON array field.  The
            # latter can return a successful post while silently dropping the
            # photo; the resulting AdCreative then fails with Meta 1487212 or
            # 1487891 when the ad is materialized.
            "attached_media[0]": json.dumps({"media_fbid": image_id}, ensure_ascii=False),
        }
        if not published and unpublished_type:
            fields["unpublished_content_type"] = unpublished_type
        if link:
            fields["link"] = link
        if message:
            fields["message"] = message
        call_to_action = self.page_post_call_to_action(cta, link, message_destination, lead_gen_form_id)
        if call_to_action:
            fields["call_to_action"] = call_to_action
        return self.post_graph_form(f"{page_id}/feed", fields)

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

    @classmethod
    def default_adset_bidding(cls, value=None):
        bidding = cls.normalize_bidding_config(value or {})
        if not isinstance(bidding, dict):
            bidding = {}
        if not bidding.get("bid_strategy"):
            bidding["bid_strategy"] = "LOWEST_COST_WITHOUT_CAP"
        return bidding

    def graph_execute(self, args, record):
        args = list(args)
        if len(args) < 2:
            return None
        area = args[0]
        action = args[1]
        access_token = getattr(self.config, "meta_access_token", "")
        ad_account_id = self.normalize_ad_account_id(self.positional(args, 2, getattr(self.config, "ad_account_id", "")))
        configured_ad_account_id = self.normalize_ad_account_id(getattr(self.config, "ad_account_id", ""))
        try:
            if area == "auth" and action == "status":
                endpoint = "local/meta-token"
                body = {
                    "ok": bool(access_token),
                    "source": "graph_api_local_auth",
                    "facebook_ready": bool(access_token),
                    "token_expired": False,
                    "default_account": configured_ad_account_id,
                    "message": "Meta access token is configured." if access_token else "Missing Meta access token.",
                }
                return self.graph_local_record(record, endpoint, body, ok=bool(access_token), status=0 if access_token else 1)
            if area == "limits" and action == "check":
                if not access_token:
                    return self.graph_local_record(record, "local/meta-token", {"ok": False, "error": "missing_meta_access_token"}, ok=False, status=1)
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
            if action == "create-page-post":
                publishing_token = self.meta_page_token()
                page_id = self.flag(args, "--page-id", "")
                if not publishing_token:
                    return self.graph_local_record(record, "local/meta-page-token", {"ok": False, "error": "missing_meta_page_token", "message": "Direct publishing is not connected. Save the unified Meta token in the main Meta connection field."}, ok=False, status=1)
                if not page_id:
                    return self.graph_local_record(record, "local/meta-page-post", {"ok": False, "error": "missing_page_id"}, ok=False, status=1)
                page_lookup = self.page_access_token(page_id, publishing_token)
                if not page_lookup.get("ok"):
                    return self.graph_local_record(
                        record,
                        "local/meta-page-post",
                        {
                            "ok": False,
                            "error": page_lookup.get("error") or "page_not_found",
                            "message": "The publishing token cannot access this Facebook Page. Save the Page publishing token in Settings > Publicación directa, not in the main Meta Ads token field. It can be a user/system token that can list the Page, or a direct Page access token for this exact Page.",
                            "lookup_methods": page_lookup.get("lookup_methods", {}),
                        },
                        ok=False,
                        status=1,
                    )
                page_token = page_lookup.get("access_token") or publishing_token
                message = self.flag(args, "--message", "")
                link = self.flag(args, "--link", "")
                image_path = self.flag(args, "--image-path", "")
                image_url = self.flag(args, "--image-url", "")
                video_path = self.flag(args, "--video-path", "")
                video_url = self.flag(args, "--video-url", "")
                media_only = str(self.flag(args, "--media-only", "false") or "false").strip().lower() in {"1", "true", "yes", "si", "sí", "on"}
                cta = self.flag(args, "--call-to-action", "LEARN_MORE")
                message_destination = self.normalize_message_destination(self.flag(args, "--message-destination", ""))
                lead_gen_form_id = self.flag(args, "--lead-gen-form-id", "")
                # Image/video message ads can use an attached-media Page post
                # with a native messaging CTA and no website link.  Do not
                # force the api.whatsapp.com/m.me URL here: doing so turns the
                # post into a link-preview creative and Meta may drop the
                # attached media or reject it for the messaging objective.
                if message_destination and not link and not (image_path or image_url or video_path or video_url):
                    link = self.default_message_destination_link(message_destination, page_id)
                unpublished_type = self.flag(args, "--unpublished-content-type", "ADS_POST") or "ADS_POST"
                published = str(self.flag(args, "--published", "false") or "false").strip().lower() in {"1", "true", "yes", "si", "sí", "on"}
                published_value = "true" if published else "false"
                is_video_post = bool(video_path or video_url)
                if video_path:
                    if not Path(video_path).exists():
                        return self.graph_local_record(record, "local/meta-page-post", {"ok": False, "error": "video_file_missing", "path": video_path}, ok=False, status=1)
                    endpoint = f"{page_id}/videos"
                    fields = {"access_token": page_token, "published": published_value}
                    if not published and unpublished_type:
                        fields["unpublished_content_type"] = unpublished_type
                    if message:
                        fields["description"] = message
                    call_to_action = self.page_post_call_to_action(cta, link, message_destination, lead_gen_form_id)
                    if call_to_action:
                        fields["call_to_action"] = call_to_action
                    result = self.post_graph_multipart(endpoint, fields, {"source": video_path})
                elif video_url:
                    endpoint = f"{page_id}/videos"
                    fields = {"access_token": page_token, "published": published_value, "file_url": video_url}
                    if not published and unpublished_type:
                        fields["unpublished_content_type"] = unpublished_type
                    if message:
                        fields["description"] = message
                    call_to_action = self.page_post_call_to_action(cta, link, message_destination, lead_gen_form_id)
                    if call_to_action:
                        fields["call_to_action"] = call_to_action
                    result = self.post_graph_form(endpoint, fields)
                elif image_path:
                    if not Path(image_path).exists():
                        return self.graph_local_record(record, "local/meta-page-post", {"ok": False, "error": "image_file_missing", "path": image_path}, ok=False, status=1)
                    endpoint = f"{page_id}/photos"
                    # When a visible post also includes a destination link, upload the
                    # photo as an unpublished media object first. The following /feed
                    # request is the single buyer-visible post and attaches this image.
                    photo_published = published and not (link or message_destination or lead_gen_form_id)
                    fields = {"access_token": page_token, "published": "true" if photo_published else "false"}
                    if not published and unpublished_type:
                        fields["unpublished_content_type"] = unpublished_type
                    if message:
                        fields["caption"] = message
                    photo_result = self.post_graph_multipart(endpoint, fields, {"source": image_path})
                    photo_body = photo_result.get("body") if isinstance(photo_result.get("body"), dict) else {}
                    image_id = str(photo_body.get("id") or "").strip()
                    if (link or message_destination or lead_gen_form_id) and not media_only and photo_result.get("ok") and image_id:
                        endpoint = f"{page_id}/feed"
                        result = self.create_linked_image_page_post(page_id, page_token, message, link, image_id, cta, unpublished_type, message_destination, lead_gen_form_id, published=published)
                    else:
                        result = photo_result
                elif image_url:
                    endpoint = f"{page_id}/photos"
                    photo_published = published and not (link or message_destination or lead_gen_form_id)
                    fields = {"access_token": page_token, "published": "true" if photo_published else "false", "url": image_url}
                    if not published and unpublished_type:
                        fields["unpublished_content_type"] = unpublished_type
                    if message:
                        fields["caption"] = message
                    photo_result = self.post_graph_form(endpoint, fields)
                    photo_body = photo_result.get("body") if isinstance(photo_result.get("body"), dict) else {}
                    image_id = str(photo_body.get("id") or "").strip()
                    if (link or message_destination or lead_gen_form_id) and not media_only and photo_result.get("ok") and image_id:
                        endpoint = f"{page_id}/feed"
                        result = self.create_linked_image_page_post(page_id, page_token, message, link, image_id, cta, unpublished_type, message_destination, lead_gen_form_id, published=published)
                    else:
                        result = photo_result
                else:
                    endpoint = f"{page_id}/feed"
                    fields = {"access_token": page_token, "published": published_value}
                    if not published and unpublished_type:
                        fields["unpublished_content_type"] = unpublished_type
                    if message:
                        fields["message"] = message
                    if link:
                        fields["link"] = link
                    call_to_action = self.page_post_call_to_action(cta, link, message_destination, lead_gen_form_id)
                    if call_to_action:
                        fields["call_to_action"] = call_to_action
                    result = self.post_graph_form(endpoint, fields)
                body = result.get("body") if isinstance(result.get("body"), dict) else {}
                if result.get("ok"):
                    if is_video_post and not published:
                        video_id = str(body.get("id") or body.get("video_id") or "").strip()
                        details = self.page_video_ad_post_details(page_id, video_id, page_token)
                        object_story_id = str(details.get("object_story_id") or "").strip()
                        details_ok = bool(details.get("ok") and object_story_id)
                        body = {
                            **body,
                            "ok": details_ok,
                            "video_id": video_id,
                            "page_post_id": details.get("page_post_id") or "",
                            "post_id": object_story_id,
                            "object_story_id": object_story_id,
                            "thumbnail_url": details.get("thumbnail_url") or "",
                            "video_status": details.get("status") or {},
                            "video_post_lookup": details,
                            "page_id": page_id,
                            "page_name": (page_lookup.get("page") or {}).get("name", ""),
                        }
                        if not details_ok:
                            body["error"] = details.get("error") or "video_post_id_not_ready"
                            body["message"] = "Meta created the Page video, but it is still processing and is not promotable yet. Retry the approval in a moment."
                        result = {**result, "ok": details_ok, "status": result.get("status") if details_ok else 1, "body": body}
                    else:
                        post_id = self.page_post_id_from_body(page_id, body)
                        body = {**body, "ok": bool(post_id), "post_id": post_id, "object_story_id": post_id, "page_id": page_id, "page_name": (page_lookup.get("page") or {}).get("name", "")}
                        result = {**result, "ok": bool(post_id), "status": result.get("status") if post_id else 1, "body": body}
                return self.graph_record(record, endpoint, result)
            if action in {"lead-forms", "create-lead-form"}:
                page_id = self.flag(args, "--page-id", "")
                # Lead forms are a Marketing API/Page Ads capability.  Do not
                # blindly prefer the publishing-only token: installations can
                # have a live publishing token without pages_manage_ads while
                # the primary Ads token is the one that can read/create forms.
                token_candidates = []
                for candidate in (
                    access_token,
                    getattr(self.config, "meta_access_token", ""),
                    self.meta_page_token(),
                ):
                    candidate = str(candidate or "").strip()
                    if candidate and candidate not in token_candidates:
                        token_candidates.append(candidate)
                if not token_candidates:
                    return self.graph_local_record(record, "local/meta-page-token", {"ok": False, "error": "missing_meta_page_token", "message": "Lead forms need a Page-capable token. Connect Publicación directa or a Page access token first."}, ok=False, status=1)
                if not page_id:
                    return self.graph_local_record(record, "local/meta-lead-form", {"ok": False, "error": "missing_page_id"}, ok=False, status=1)
                endpoint = f"{page_id}/leadgen_forms"
                if action == "lead-forms":
                    limit = self.flag(args, "--limit", "25")
                    fields = self.clean_graph_fields(
                        self.flag(args, "--fields", ""),
                        "id,name,status,created_time,leads_count,locale,questions",
                    )
                    last_error = None
                    for token in token_candidates:
                        page_lookup = self.page_access_token(page_id, token)
                        if not page_lookup.get("ok"):
                            last_error = page_lookup
                            continue
                        page_token = page_lookup.get("access_token") or token
                        result = self.get_graph(endpoint, {"fields": fields, "limit": limit}, access_token=page_token)
                        if result.get("ok"):
                            return self.graph_record(record, endpoint, result)
                        last_error = result
                    return self.graph_record(record, endpoint, last_error or {"ok": False, "status": 1, "body": {"error": "page_not_found"}})

                # For creation, probe the read edge first.  This is a safe,
                # non-mutating permission check and prevents a publishing-only
                # token from reaching the POST and producing a misleading
                # pages_manage_ads error.
                page_lookup = None
                page_token = ""
                permission_result = None
                for token in token_candidates:
                    candidate_lookup = self.page_access_token(page_id, token)
                    if not candidate_lookup.get("ok"):
                        permission_result = candidate_lookup
                        continue
                    candidate_page_token = candidate_lookup.get("access_token") or token
                    permission_result = self.get_graph(
                        endpoint,
                        {"fields": "id,name", "limit": "1"},
                        access_token=candidate_page_token,
                    )
                    if permission_result.get("ok"):
                        page_lookup = candidate_lookup
                        page_token = candidate_page_token
                        break
                if not page_lookup:
                    return self.graph_record(record, endpoint, permission_result or {"ok": False, "status": 1, "body": {"error": "page_not_found"}})

                name = self.flag(args, "--name", "")
                privacy_url = self.flag(args, "--privacy-policy-url", "")
                questions = self.normalize_lead_form_questions(self.flag(args, "--questions", ""))
                if not name:
                    return self.graph_local_record(record, "local/meta-lead-form", {"ok": False, "error": "missing_lead_form_name"}, ok=False, status=1)
                if not privacy_url.startswith(("http://", "https://")):
                    return self.graph_local_record(record, "local/meta-lead-form", {"ok": False, "error": "missing_or_invalid_privacy_policy_url"}, ok=False, status=1)
                if not questions:
                    return self.graph_local_record(record, "local/meta-lead-form", {"ok": False, "error": "missing_lead_form_questions"}, ok=False, status=1)
                link_text = (self.flag(args, "--privacy-policy-link-text", "Política de privacidad") or "Política de privacidad")[:70]
                fields = {
                    "access_token": page_token,
                    "name": name,
                    "questions": questions,
                    "privacy_policy": {"url": privacy_url, "link_text": link_text},
                }
                locale = self.flag(args, "--locale", "")
                form_type = self.normalize_lead_form_form_type(self.flag(args, "--form-type", ""))
                follow_up_url = self.flag(args, "--follow-up-action-url", "")
                context_card = self.json_flag(args, "--context-card", None)
                thank_you_page = self.json_flag(args, "--thank-you-page", None)
                custom_disclaimer = self.json_flag(args, "--custom-disclaimer", None)
                if locale:
                    fields["locale"] = locale
                if form_type:
                    fields["form_type"] = form_type
                if follow_up_url:
                    fields["follow_up_action_url"] = follow_up_url
                if isinstance(context_card, dict) and context_card:
                    fields["context_card"] = context_card
                if isinstance(thank_you_page, dict) and thank_you_page:
                    fields["thank_you_page"] = thank_you_page
                if isinstance(custom_disclaimer, dict) and custom_disclaimer:
                    fields["custom_disclaimer"] = custom_disclaimer
                result = self.post_graph_form(endpoint, fields)
                body = result.get("body") if isinstance(result.get("body"), dict) else {}
                if result.get("ok"):
                    form_id = str(body.get("id") or body.get("lead_gen_form_id") or "").strip()
                    body = {
                        **body,
                        "ok": bool(form_id),
                        "lead_gen_form_id": form_id,
                        "page_id": page_id,
                        "page_name": (page_lookup.get("page") or {}).get("name", ""),
                    }
                    result = {**result, "ok": bool(form_id), "status": result.get("status") if form_id else 1, "body": body}
                return self.graph_record(record, endpoint, result)
            if not access_token:
                return self.graph_local_record(record, "local/meta-token", {"ok": False, "error": "missing_meta_access_token"}, ok=False, status=1)
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
                    fields["bid_strategy"] = self.normalize_bid_strategy(self.flag(args, "--bid-strategy", "LOWEST_COST_WITHOUT_CAP"))
                bid_strategy = self.flag(args, "--bid-strategy", "")
                if bid_strategy and not fields.get("bid_strategy"):
                    fields["bid_strategy"] = self.normalize_bid_strategy(bid_strategy)
                adset_sharing = self.flag(args, "--is-adset-budget-sharing-enabled", "")
                if adset_sharing:
                    fields["is_adset_budget_sharing_enabled"] = "true" if str(adset_sharing).strip().lower() in {"1", "true", "yes", "si", "sí", "on"} else "false"
                return self.graph_record(record, endpoint, self.post_graph_form(endpoint, fields))
            if action == "campaign-details":
                campaign_id = self.positional(args, 2, "")
                endpoint = campaign_id
                return self.graph_record(record, endpoint, self.get_graph(endpoint, {"fields": "id,name,status,effective_status,configured_status,daily_budget,lifetime_budget,bid_strategy"}))
            if action == "adset-details":
                adset_id = self.positional(args, 2, "")
                endpoint = adset_id
                return self.graph_record(
                    record,
                    endpoint,
                    self.get_graph(
                        endpoint,
                        {
                            "fields": (
                                "id,name,status,effective_status,configured_status,targeting,"
                                "optimization_goal,promoted_object,destination_type"
                            )
                        },
                    ),
                )
            if action == "update-campaign":
                campaign_id = self.positional(args, 2, "")
                endpoint = campaign_id
                fields = {"access_token": access_token}
                bid_strategy = self.flag(args, "--bid-strategy", "")
                if bid_strategy:
                    fields["bid_strategy"] = self.normalize_bid_strategy(bid_strategy)
                status = self.flag(args, "--status", "")
                if status:
                    fields["status"] = status
                if len(fields) <= 1:
                    return None
                return self.graph_record(record, endpoint, self.post_graph_form(endpoint, fields))
            if action == "delete":
                target_type = self.positional(args, 2, "")
                target_id = self.positional(args, 3, "")
                if not target_id:
                    target_id = target_type
                    target_type = "object"
                endpoint = target_id
                result = self.delete_graph_object(endpoint, access_token)
                body = result.get("body") if isinstance(result.get("body"), dict) else {}
                if not result.get("ok"):
                    fallback = self.post_graph_form(endpoint, {"access_token": access_token, "status": "DELETED"})
                    fallback_body = fallback.get("body") if isinstance(fallback.get("body"), dict) else {}
                    body = {
                        "ok": bool(fallback.get("ok")),
                        "target_type": target_type,
                        "target_id": target_id,
                        "primary_delete": body,
                        "fallback_status_deleted": fallback_body,
                    }
                    result = {"ok": bool(fallback.get("ok")), "status": fallback.get("status") or result.get("status"), "body": body}
                else:
                    body = {**body, "ok": True, "target_type": target_type, "target_id": target_id}
                    result = {**result, "body": body}
                return self.graph_record(record, endpoint, result)
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
                    ("--is-adset-budget-sharing-enabled", "is_adset_budget_sharing_enabled"),
                    ("--destination-type", "destination_type"),
                ):
                    value = self.flag(args, source, "")
                    if value:
                        if source == "--promoted-object":
                            try:
                                promoted_payload = json.loads(value)
                                value = json.dumps(self.normalize_promoted_object(promoted_payload))
                            except json.JSONDecodeError:
                                pass
                        elif source == "--is-adset-budget-sharing-enabled":
                            value = "true" if str(value).strip().lower() in {"1", "true", "yes", "si", "sí", "on"} else "false"
                        elif source == "--destination-type":
                            value = self.normalize_destination_type(value)
                        fields[target] = value
                bidding = self.flag(args, "--bidding", "")
                bidding_payload = self.default_adset_bidding({})
                if bidding:
                    try:
                        bidding_payload = json.loads(bidding)
                    except json.JSONDecodeError:
                        bidding_payload = {"bid_strategy": bidding}
                if isinstance(bidding_payload, dict):
                    bidding_payload = self.default_adset_bidding(bidding_payload)
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
                creative_token_source = self.flag(args, "--creative-token-source", "")
                creative_access_token = access_token
                credential_source = "primary"
                if str(creative_token_source or "").strip().lower() in {"publishing", "direct_publishing", "page_publishing"}:
                    publishing_token = self.legacy_publishing_token()
                    if publishing_token:
                        creative_access_token = publishing_token
                        credential_source = "publishing"
                fields = {
                    "access_token": creative_access_token,
                    "name": self.flag(args, "--name", "Ad Creative"),
                }
                page_welcome_message = self.flag(args, "--page-welcome-message", "")
                page_welcome_message_value = page_welcome_message
                if page_welcome_message:
                    try:
                        page_welcome_message_value = json.loads(page_welcome_message)
                    except json.JSONDecodeError:
                        pass
                record = {**record, "credential_source": credential_source}
                object_story_id = self.flag(args, "--object-story-id", "")
                if object_story_id:
                    fields["object_story_id"] = object_story_id
                    if page_welcome_message:
                        fields["page_welcome_message"] = page_welcome_message
                    link_url = self.flag(args, "--link-url", "")
                    if link_url:
                        fields["link_url"] = link_url
                    return self.graph_record(record, endpoint, self.post_graph_form(endpoint, fields))
                object_story_spec = self.flag(args, "--object-story-spec", "")
                if object_story_spec and page_welcome_message:
                    try:
                        supplied_story = json.loads(object_story_spec)
                    except json.JSONDecodeError:
                        supplied_story = {}
                    if isinstance(supplied_story, dict):
                        for data_key in ("link_data", "video_data"):
                            if isinstance(supplied_story.get(data_key), dict):
                                supplied_story[data_key].setdefault("page_welcome_message", page_welcome_message_value)
                        object_story_spec = json.dumps(supplied_story, ensure_ascii=False)
                if not object_story_spec:
                    link = self.flag(args, "--cta-link", "") or self.flag(args, "--link", "")
                    video_id = self.flag(args, "--video-id", "")
                    image_hash = self.flag(args, "--image-hash", "")
                    image_url = self.flag(args, "--image-url", "")
                    cta = self.normalize_call_to_action(self.flag(args, "--call-to-action", "")) if self.flag(args, "--call-to-action", "") else ""
                    lead_gen_form_id = self.flag(args, "--lead-gen-form-id", "")
                    message_destination = self.normalize_message_destination(self.flag(args, "--message-destination", ""))
                    story = {
                        "page_id": self.flag(args, "--page-id", ""),
                        **({"instagram_actor_id": self.flag(args, "--instagram-actor-id", "")} if self.flag(args, "--instagram-actor-id", "") else {}),
                    }
                    if lead_gen_form_id and not link:
                        link = self.default_lead_form_link(story.get("page_id", ""))
                    if message_destination and not link:
                        link = self.default_message_destination_link(message_destination, story.get("page_id", ""))

                    def call_to_action_payload():
                        if lead_gen_form_id:
                            return {
                                "type": self.normalize_call_to_action(cta or "SIGN_UP"),
                                "value": {"lead_gen_form_id": lead_gen_form_id},
                            }
                        if message_destination:
                            value = {"app_destination": message_destination}
                            if link:
                                value["link"] = link
                            return {
                                "type": self.message_destination_cta_type(message_destination),
                                "value": value,
                            }
                        if cta and link:
                            return {"type": cta, "value": {"link": link}}
                        return {}

                    call_to_action = call_to_action_payload()
                    if video_id:
                        video_data = {
                            "video_id": video_id,
                            "message": self.flag(args, "--body-text", ""),
                            "title": self.flag(args, "--headline", ""),
                        }
                        if image_hash:
                            video_data["image_hash"] = image_hash
                        if image_url:
                            video_data["image_url"] = image_url
                        if call_to_action:
                            video_data["call_to_action"] = call_to_action
                        if page_welcome_message:
                            video_data["page_welcome_message"] = page_welcome_message_value
                        story["video_data"] = video_data
                    elif not link and not lead_gen_form_id and not message_destination:
                        # Awareness/post-engagement ads do not need a fake
                        # website destination. Meta's native photo_data shape
                        # carries the image and copy without creating a Page
                        # post first.
                        photo_data = {"caption": self.flag(args, "--body-text", "")}
                        if image_hash:
                            photo_data["image_hash"] = image_hash
                        if image_url:
                            photo_data["url"] = image_url
                        if page_welcome_message:
                            photo_data["page_welcome_message"] = page_welcome_message_value
                        story["photo_data"] = photo_data
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
                        if call_to_action:
                            link_data["call_to_action"] = call_to_action
                        if page_welcome_message:
                            link_data["page_welcome_message"] = page_welcome_message_value
                        story["link_data"] = link_data
                    object_story_spec = json.dumps(story)
                fields["object_story_spec"] = object_story_spec
                return self.graph_record(record, endpoint, self.post_graph_form(endpoint, fields))
            if action == "create-ad":
                endpoint = f"{configured_ad_account_id}/ads"
                object_story_id = self.flag(args, "--object-story-id", "")
                # Meta's existing-post route accepts the Page post directly
                # as the creative input. Keep it opt-in so normal ads still
                # use the documented standalone creative_id route.
                use_object_story_ad = bool(self.flag(args, "--use-object-story-ad", ""))
                creative_payload = (
                    {"object_story_id": object_story_id}
                    if use_object_story_ad and object_story_id
                    else {"creative_id": self.flag(args, "--creative-id", "")}
                )
                fields = {
                    "access_token": access_token,
                    "name": self.flag(args, "--name", "Ad"),
                    "adset_id": self.positional(args, 2, ""),
                    "creative": json.dumps(creative_payload),
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
                "connector": "graph_api",
                "returncode": 1,
                "stdout": "",
                "stderr": f"Meta Graph API request failed: {exc}",
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

    def delete(self, target_type, target_id, approved=False):
        return self.run(["marketing", "delete", target_type, target_id, "--json", "--yes"], live_required=True, mutation=True, approved=approved)

    def set_budget(self, target_type, target_id, daily_budget_cents, approved=False):
        return self.run(["marketing", "set-budget", target_type, target_id, "--daily-budget", str(int(daily_budget_cents))], live_required=True, mutation=True, approved=approved)

    def campaign_details(self, campaign_id):
        return self.run(["marketing", "campaign-details", campaign_id, "--json"], live_required=False)

    def adset_details(self, adset_id):
        return self.run(["marketing", "adset-details", adset_id, "--json"], live_required=False)

    def search_meta_targeting(self, kind, query, limit=25):
        """Resolve a targeting phrase against Meta's current Graph catalog."""
        normalized_kind = "location" if str(kind or "").strip().lower() in {"location", "locations", "geo", "adgeolocation"} else "interest"
        params = {
            "type": "adgeolocation" if normalized_kind == "location" else "adinterest",
            "q": str(query or "").strip(),
            "limit": max(1, min(int(limit or 25), 25)),
        }
        if normalized_kind == "location":
            params["location_types"] = ["country", "region", "city"]
        result = self.get_graph("search", params)
        body = result.get("body") if isinstance(result, dict) and isinstance(result.get("body"), dict) else {}
        if not result.get("ok"):
            return {"ok": False, "items": [], "error": body.get("error") or body}
        items = []
        for row in body.get("data") or []:
            if not isinstance(row, dict):
                continue
            if normalized_kind == "location":
                key = str(row.get("key") or row.get("id") or "").strip()
                country_code = str(row.get("country_code") or row.get("country") or "").strip().upper()
                items.append({
                    "kind": "location",
                    "id": key,
                    "key": key,
                    "name": str(row.get("name") or key).strip(),
                    "type": str(row.get("type") or row.get("location_type") or "location").strip().lower(),
                    "country_code": country_code,
                })
            else:
                items.append({
                    "kind": "interest",
                    "id": str(row.get("id") or "").strip(),
                    "name": str(row.get("name") or "").strip(),
                })
        return {"ok": True, "items": items[: params["limit"]]}

    def validate_meta_targeting(self, targeting_list):
        """Validate detailed-targeting IDs against Meta's live account catalog."""
        entries = [item for item in (targeting_list or []) if isinstance(item, dict) and item.get("id")]
        if not entries:
            return {"ok": True, "items": []}
        account_id = self.normalize_ad_account_id(getattr(self.config, "ad_account_id", ""))
        if not account_id:
            return {"ok": False, "items": [], "error": "missing_ad_account_id"}
        result = self.get_graph(
            f"{account_id}/targetingvalidation",
            {"targeting_list": entries},
        )
        body = result.get("body") if isinstance(result, dict) and isinstance(result.get("body"), dict) else {}
        if not result.get("ok"):
            return {"ok": False, "items": [], "error": body.get("error") or body}
        rows = body.get("data") if isinstance(body.get("data"), list) else []
        if rows:
            invalid = [row for row in rows if isinstance(row, dict) and row.get("valid") is False]
            if not invalid:
                return {"ok": True, "items": rows, "invalid": []}
            # Current Graph versions can return ``valid:false`` from the old
            # targetingvalidation edge for IDs returned moments earlier by
            # the live adinterest catalog. Confirm each ID against that live
            # catalog before rejecting it; exact ID matching prevents stale or
            # fabricated values from passing this compatibility fallback.
            confirmed = []
            for entry in entries:
                name = str(entry.get("name") or "").strip()
                interest_id = str(entry.get("id") or "").strip()
                if not name:
                    break
                searched = self.search_meta_targeting("interest", name, limit=25)
                match = next(
                    (item for item in searched.get("items") or [] if str(item.get("id") or "").strip() == interest_id),
                    None,
                ) if searched.get("ok") else None
                if not match and "(" in name:
                    searched = self.search_meta_targeting("interest", name.split("(", 1)[0].strip(), limit=25)
                    match = next(
                        (item for item in searched.get("items") or [] if str(item.get("id") or "").strip() == interest_id),
                        None,
                    ) if searched.get("ok") else None
                if not match:
                    break
                confirmed.append({"id": interest_id, "name": str(match.get("name") or name), "valid": True})
            if len(confirmed) == len(entries):
                return {
                    "ok": True,
                    "items": confirmed,
                    "invalid": [],
                    "validation_source": "live_adinterest_exact_id_fallback",
                }
            return {"ok": False, "items": rows, "invalid": invalid}
        if "valid" in body:
            return {"ok": bool(body.get("valid")), "items": [body] if isinstance(body, dict) else []}
        # A successful empty response is not proof that the IDs are valid.
        return {"ok": False, "items": [], "error": "targeting_validation_empty"}

    def update_campaign_bid_strategy(self, campaign_id, bid_strategy="LOWEST_COST_WITHOUT_CAP", approved=False):
        return self.run(["marketing", "update-campaign", campaign_id, "--bid-strategy", bid_strategy, "--json", "--yes"], live_required=True, mutation=True, approved=approved)

    def create_campaign(self, ad_account_id, name, objective, daily_budget_cents=0, status="PAUSED", approved=False, bid_strategy="", is_adset_budget_sharing_enabled=None):
        args = ["marketing", "create-campaign"]
        if ad_account_id:
            args.append(ad_account_id)
        args.extend(["--name", name, "--objective", objective, "--status", status, "--json", "--yes"])
        if daily_budget_cents:
            args.extend(["--daily-budget", str(int(daily_budget_cents))])
            args.extend(["--bid-strategy", bid_strategy or "LOWEST_COST_WITHOUT_CAP"])
        elif bid_strategy:
            args.extend(["--bid-strategy", bid_strategy])
        if is_adset_budget_sharing_enabled is not None:
            args.extend(["--is-adset-budget-sharing-enabled", "true" if is_adset_budget_sharing_enabled else "false"])
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
        is_adset_budget_sharing_enabled=None,
        destination_type="",
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
        args.extend(["--bidding", json.dumps(self.default_adset_bidding(bidding or {}))])
        if daily_budget_cents:
            args.extend(["--daily-budget", str(int(daily_budget_cents))])
        if lifetime_budget_cents:
            args.extend(["--lifetime-budget", str(int(lifetime_budget_cents))])
        if start_time:
            args.extend(["--start-time", start_time])
        if end_time:
            args.extend(["--end-time", end_time])
        if is_adset_budget_sharing_enabled is not None:
            args.extend(["--is-adset-budget-sharing-enabled", "true" if is_adset_budget_sharing_enabled else "false"])
        if destination_type:
            args.extend(["--destination-type", self.normalize_destination_type(destination_type)])
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

    def create_page_post(
        self,
        page_id,
        message="",
        link="",
        image_path="",
        image_url="",
        video_path="",
        video_url="",
        unpublished_content_type="ADS_POST",
        cta="LEARN_MORE",
        message_destination="",
        lead_gen_form_id="",
        published=False,
        media_only=False,
        approved=False,
    ):
        args = ["marketing", "create-page-post", "--page-id", page_id]
        if message:
            args.extend(["--message", message])
        if link:
            args.extend(["--link", link])
        if cta:
            args.extend(["--call-to-action", cta])
        if message_destination:
            args.extend(["--message-destination", self.normalize_message_destination(message_destination)])
        if lead_gen_form_id:
            args.extend(["--lead-gen-form-id", lead_gen_form_id])
        if image_path:
            args.extend(["--image-path", image_path])
        if image_url:
            args.extend(["--image-url", image_url])
        if video_path:
            args.extend(["--video-path", video_path])
        if video_url:
            args.extend(["--video-url", video_url])
        if unpublished_content_type:
            args.extend(["--unpublished-content-type", unpublished_content_type])
        if published:
            args.extend(["--published", "true"])
        if media_only:
            args.extend(["--media-only", "true"])
        args.extend(["--json", "--yes"])
        return self.run(args, live_required=True, mutation=True, approved=approved)

    def lead_forms(self, page_id="", limit=25):
        args = ["marketing", "lead-forms", "--page-id", page_id, "--limit", str(int(limit or 25)), "--json"]
        return self.run(args, live_required=False)

    def create_lead_form(
        self,
        page_id,
        name,
        questions=None,
        privacy_policy_url="",
        privacy_policy_link_text="Política de privacidad",
        follow_up_action_url="",
        locale="",
        form_type="",
        context_card=None,
        thank_you_page=None,
        custom_disclaimer=None,
        approved=False,
    ):
        args = ["marketing", "create-lead-form", "--page-id", page_id, "--name", name]
        normalized_questions = self.normalize_lead_form_questions(questions or [])
        if normalized_questions:
            args.extend(["--questions", json.dumps(normalized_questions, ensure_ascii=False)])
        if privacy_policy_url:
            args.extend(["--privacy-policy-url", privacy_policy_url])
        if privacy_policy_link_text:
            args.extend(["--privacy-policy-link-text", privacy_policy_link_text])
        if follow_up_action_url:
            args.extend(["--follow-up-action-url", follow_up_action_url])
        if locale:
            args.extend(["--locale", locale])
        if form_type:
            args.extend(["--form-type", self.normalize_lead_form_form_type(form_type)])
        if isinstance(context_card, dict) and context_card:
            args.extend(["--context-card", json.dumps(context_card, ensure_ascii=False)])
        if isinstance(thank_you_page, dict) and thank_you_page:
            args.extend(["--thank-you-page", json.dumps(thank_you_page, ensure_ascii=False)])
        if isinstance(custom_disclaimer, dict) and custom_disclaimer:
            args.extend(["--custom-disclaimer", json.dumps(custom_disclaimer, ensure_ascii=False)])
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
        object_story_id="",
        lead_gen_form_id="",
        prefilled_message="",
        welcome_message="",
        message_destination="",
        object_story_link_url="",
        prefer_publishing_token=False,
        use_instagram_identity=None,
        approved=False,
    ):
        normalized_message_destination = self.normalize_message_destination(message_destination)
        welcome_validation = self.validate_page_welcome_message(prefilled_message, welcome_message)
        if not welcome_validation.get("ok"):
            operation = [
                "meta-graph", "marketing", "create-creative",
                str(ad_account_id or ""),
            ]
            body = {
                "ok": False,
                "error": welcome_validation["error"],
                "message": "The approved customer message exceeds Meta's 80-character ice-breaker title limit.",
                "validation": welcome_validation,
                "preserved_inputs": {
                    "prefilled_message": str(prefilled_message or "").strip(),
                    "welcome_message": str(welcome_message or "").strip(),
                    "body_text": str(body_text or ""),
                    "headline": str(headline or ""),
                    "page_id": str(page_id or ""),
                    "message_destination": normalized_message_destination,
                },
                "next_step": "Ask the buyer to approve a shorter customer message, then retry with all other approved fields unchanged.",
            }
            record = {
                "command": operation,
                "operation": operation[1:],
                "mode": self.config.mode,
                "approved_execution": bool(approved),
                "executed": False,
                "returncode": 422,
                "stdout": "",
                "stderr": "",
            }
            return self.graph_local_record(record, "adcreatives:validation", body, ok=False, status=422)
        # A Page-only Messenger/WhatsApp ad must not inherit a stale Instagram
        # identity from the global account binding. Ads Manager represents
        # this as "Use Facebook Page". Sending instagram_actor_id anyway can
        # make Meta reject the final ad even when Instagram was never selected.
        page_only_message_destination = normalized_message_destination in {"MESSENGER", "WHATSAPP"}
        if page_only_message_destination or use_instagram_identity is False:
            instagram_actor_id = ""
            if isinstance(object_story_spec, dict):
                object_story_spec = dict(object_story_spec)
                object_story_spec.pop("instagram_actor_id", None)
                object_story_spec.pop("instagram_user_id", None)
        args = ["marketing", "create-creative"]
        if ad_account_id:
            args.append(ad_account_id)
        args.extend(["--name", name])
        if prefer_publishing_token:
            args.extend(["--creative-token-source", "publishing"])
        welcome_payload = self.page_welcome_message_payload(prefilled_message, welcome_message)
        if welcome_payload:
            args.extend(["--page-welcome-message", json.dumps(welcome_payload, ensure_ascii=False)])
        if object_story_id:
            args.extend(["--object-story-id", object_story_id])
            if object_story_link_url:
                args.extend(["--link-url", object_story_link_url])
        elif object_story_spec:
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
            if lead_gen_form_id:
                args.extend(["--lead-gen-form-id", lead_gen_form_id])
            if normalized_message_destination:
                args.extend(["--message-destination", normalized_message_destination])
        args.extend(["--json", "--yes"])
        if instagram_actor_id:
            args.extend(["--instagram-actor-id", instagram_actor_id])
        return self.run(args, live_required=True, mutation=True, approved=approved)

    def create_ad(self, adset_id, name, creative_id, status="PAUSED", website_url="", approved=False, object_story_id="", prefer_object_story_ad=False):
        args = ["marketing", "create-ad", adset_id, "--name", name, "--creative-id", creative_id, "--status", status]
        if website_url:
            args.extend(["--website-url", website_url])
        if object_story_id:
            args.extend(["--object-story-id", object_story_id])
        if prefer_object_story_ad and object_story_id:
            args.extend(["--use-object-story-ad", "true"])
        args.extend(["--json", "--yes"])
        return self.run(args, live_required=True, mutation=True, approved=approved)


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
