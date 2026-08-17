#!/usr/bin/env python3
"""Smoke-test whether a dev-mode Meta app can promote a dark Page post.

This script intentionally does not create a final Ad and does not spend money.
It only:
1. optionally creates an unpublished Page post/photo with the configured token;
2. attempts to create an AdCreative that points to that post via object_story_id;
3. reports whether Meta blocks it with error_subcode 1885183.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from product_config import load_config, load_dotenv  # noqa: E402
from social_flow_client import SocialFlowClient  # noqa: E402


AD_CONFIG_FILE = ROOT_DIR / "ad-config.json"


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def configured_destination():
    data = read_json(AD_CONFIG_FILE, {})
    return data.get("creative", {}).get("destination", {}) if isinstance(data, dict) else {}


def graph_url(version, endpoint):
    return f"https://graph.facebook.com/{str(version or 'v24.0').strip().lstrip('/')}/{str(endpoint or '').lstrip('/')}"


def graph_post(version, endpoint, fields):
    body = urllib.parse.urlencode({k: v for k, v in fields.items() if v not in (None, "")}).encode("utf-8")
    request = urllib.request.Request(
        graph_url(version, endpoint),
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "AdmiraIA-SmokeTest/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return {"ok": True, "status": response.status, "body": json.loads(response.read().decode("utf-8"))}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"error": raw[:1000]}
        return {"ok": False, "status": exc.code, "body": body}
    except Exception as exc:
        return {"ok": False, "status": None, "body": {"error": str(exc)}}


def graph_delete(version, node_id, token):
    return graph_post(version, node_id, {"access_token": token, "method": "delete"})


def meta_error(result):
    body = result.get("body") if isinstance(result, dict) else {}
    if not isinstance(body, dict):
        return {}
    err = body.get("error")
    return err if isinstance(err, dict) else {}


def classify_creative_result(result):
    if result.get("ok"):
        return "creative_created"
    error = meta_error(result)
    if str(error.get("error_subcode") or "") == "1885183":
        return "confirmed_development_mode_block"
    if str(error.get("code") or "") == "200":
        return "permissions_block"
    if str(error.get("code") or "") == "190":
        return "token_block"
    return "creative_failed_other"


def create_dark_post(args, version, page_id, page_token, fallback_link):
    message = args.message.strip()
    if args.image_url:
        fields = {
            "access_token": page_token,
            "url": args.image_url,
            "caption": message,
            "published": "false",
        }
        if args.temporary_photo:
            fields["temporary"] = "true"
        if args.unpublished_content_type:
            fields["unpublished_content_type"] = args.unpublished_content_type
        result = graph_post(version, f"{page_id}/photos", fields)
        body = result.get("body") if isinstance(result.get("body"), dict) else {}
        photo_id = str(body.get("id") or "").strip()
        post_id = str(body.get("post_id") or "").strip()
        if not post_id and photo_id:
            post_id = f"{page_id}_{photo_id}"
        return {
            "mode": "photo",
            "ok": bool(result.get("ok") and post_id),
            "post_id": post_id,
            "photo_id": photo_id,
            "result": result,
        }

    link = args.link.strip() or fallback_link
    if not link:
        raise SystemExit("Missing --link or configured landing URL. Use a link post or pass --image-url.")
    fields = {
        "access_token": page_token,
        "message": message,
        "link": link,
        "published": "false",
    }
    if args.unpublished_content_type:
        fields["unpublished_content_type"] = args.unpublished_content_type
    result = graph_post(version, f"{page_id}/feed", fields)
    body = result.get("body") if isinstance(result.get("body"), dict) else {}
    post_id = str(body.get("id") or body.get("post_id") or "").strip()
    return {
        "mode": "feed",
        "ok": bool(result.get("ok") and post_id),
        "post_id": post_id,
        "result": result,
    }


def main():
    load_dotenv()
    config = load_config()
    destination = configured_destination()
    parser = argparse.ArgumentParser(description="Smoke-test dev-mode dark post promotion through Meta Graph.")
    parser.add_argument("--page-id", default=destination.get("page_id", ""), help="Facebook Page ID.")
    parser.add_argument("--ad-account-id", default=config.ad_account_id, help="Meta ad account ID, with or without act_.")
    parser.add_argument("--access-token", default=config.meta_access_token, help="Marketing API token. Defaults to META_ACCESS_TOKEN.")
    parser.add_argument("--page-access-token", default=os.environ.get("META_PAGE_ACCESS_TOKEN", ""), help="Optional Page token. Defaults to access token.")
    parser.add_argument("--existing-post-id", default="", help="Skip dark post creation and test an existing PAGEID_POSTID.")
    parser.add_argument("--image-url", default="", help="Optional public image URL for /{page_id}/photos.")
    parser.add_argument("--link", default=destination.get("url", ""), help="Landing URL for a hidden link post.")
    parser.add_argument("--message", default="Admira IA smoke test: unpublished post for Meta API validation.", help="Hidden post message.")
    parser.add_argument("--creative-name", default="Admira IA smoke test creative", help="AdCreative name.")
    parser.add_argument("--creative-field", choices=["object_story_id", "object_id"], default="object_story_id", help="Field to send to /adcreatives.")
    parser.add_argument("--unpublished-content-type", default="", help="Optional Meta unpublished_content_type such as ADS_POST.")
    parser.add_argument("--temporary-photo", action="store_true", help="Send temporary=true when uploading a photo.")
    parser.add_argument("--cleanup", action="store_true", help="Try deleting the created post/photo after the test.")
    args = parser.parse_args()

    page_id = str(args.page_id or "").strip()
    ad_account_id = SocialFlowClient.normalize_ad_account_id(args.ad_account_id)
    access_token = str(args.access_token or "").strip()
    page_token = str(args.page_access_token or access_token).strip()
    version = config.meta_graph_api_version

    missing = []
    if not access_token:
        missing.append("META_ACCESS_TOKEN or --access-token")
    if not ad_account_id:
        missing.append("META_AD_ACCOUNT_ID or --ad-account-id")
    if not args.existing_post_id and not page_id:
        missing.append("page_id or --existing-post-id")
    if not page_token and not args.existing_post_id:
        missing.append("META_PAGE_ACCESS_TOKEN/--page-access-token or access token")
    if missing:
        raise SystemExit("Missing required values: " + ", ".join(missing))

    output = {
        "ok": False,
        "version": version,
        "ad_account_id": ad_account_id,
        "page_id": page_id,
        "created_dark_post": None,
        "object_story_id": "",
        "creative": None,
        "classification": "",
        "cleanup": None,
        "note": "No final Ad is created; this test cannot spend money.",
    }

    if args.existing_post_id:
        post_id = str(args.existing_post_id).strip()
        output["object_story_id"] = post_id
    else:
        dark_post = create_dark_post(args, version, page_id, page_token, args.link.strip())
        output["created_dark_post"] = {
            "mode": dark_post.get("mode"),
            "ok": dark_post.get("ok"),
            "post_id": dark_post.get("post_id"),
            "photo_id": dark_post.get("photo_id", ""),
            "status": dark_post.get("result", {}).get("status"),
            "error": meta_error(dark_post.get("result", {})),
        }
        if not dark_post.get("ok"):
            output["classification"] = "dark_post_creation_failed"
            print(json.dumps(output, indent=2, ensure_ascii=False))
            return 1
        post_id = dark_post.get("post_id")
        output["object_story_id"] = post_id

    creative_fields = {
        "access_token": access_token,
        "name": args.creative_name,
        args.creative_field: post_id,
    }
    creative_result = graph_post(version, f"{ad_account_id}/adcreatives", creative_fields)
    output["creative"] = {
        "ok": creative_result.get("ok"),
        "status": creative_result.get("status"),
        "id": (creative_result.get("body") or {}).get("id") if isinstance(creative_result.get("body"), dict) else "",
        "error": meta_error(creative_result),
        "field_used": args.creative_field,
    }
    output["classification"] = classify_creative_result(creative_result)
    output["ok"] = bool(creative_result.get("ok"))

    if args.cleanup and not args.existing_post_id and output.get("object_story_id"):
        cleanup_result = graph_delete(version, output["object_story_id"], page_token)
        output["cleanup"] = {
            "ok": cleanup_result.get("ok"),
            "status": cleanup_result.get("status"),
            "error": meta_error(cleanup_result),
        }

    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0 if output["classification"] in {"creative_created", "confirmed_development_mode_block"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
