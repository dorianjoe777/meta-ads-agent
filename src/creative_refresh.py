#!/usr/bin/env python3
"""Creative refresh planning and optional Nano Banana image generation."""
import base64
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from product_config import ROOT_DIR, load_config


AD_CONFIG_FILE = ROOT_DIR / "ad-config.json"
AD_CONFIG_EXAMPLE_FILE = ROOT_DIR / "ad-config.example.json"
OUTPUT_DIR = ROOT_DIR / "output" / "creatives"
INDEX_FILE = OUTPUT_DIR / "creative_refresh_index.json"


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path, fallback):
    if not path.exists():
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return fallback


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def load_ad_config():
    return read_json(AD_CONFIG_FILE, read_json(AD_CONFIG_EXAMPLE_FILE, {}))


def pct_change(current, previous):
    current = float(current or 0)
    previous = float(previous or 0)
    if previous == 0:
        return 0.0
    return ((current - previous) / previous) * 100


def should_refresh(campaign, ad_config=None):
    ad_config = ad_config or load_ad_config()
    refresh = ad_config.get("creative", {}).get("refresh_when", {})
    health_in = set(refresh.get("health_in", ["fatigue", "losing"]))
    if campaign.get("health") in health_in:
        return True
    frequency_over = float(refresh.get("frequency_over", 3.0))
    roas_below = float(refresh.get("roas_below", 1.2))
    ctr_drop_pct_over = float(refresh.get("ctr_drop_pct_over", 20))
    ctr_drop = pct_change(campaign.get("ctr"), campaign.get("previous_ctr"))
    return (
        float(campaign.get("frequency", 0)) > frequency_over
        or float(campaign.get("roas", 0)) < roas_below
        or ctr_drop <= -abs(ctr_drop_pct_over)
    )


def campaigns_needing_refresh(campaigns, ad_config=None):
    return [campaign for campaign in campaigns if should_refresh(campaign, ad_config)]


def copy_variants(campaign, ad_config, count):
    brand = ad_config.get("brand", {})
    offer = brand.get("offer", "the offer")
    voice = brand.get("voice", "clear, direct, benefit-led")
    name = campaign.get("name", "Campaign")
    pain = "ad fatigue" if campaign.get("health") == "fatigue" else "low conversion efficiency"
    templates = [
        {
            "headline": f"See Why {offer} Works",
            "primary_text": f"{name} needs a fresh angle. Lead with the strongest outcome, keep the promise specific, and remove friction for the next click.",
            "cta": "Learn More",
            "angle": "proof-led refresh",
        },
        {
            "headline": "A Better Way To Start",
            "primary_text": f"Use a {voice} message that speaks directly to {pain}. Show the product clearly and make the first step obvious.",
            "cta": "Shop Now",
            "angle": "direct response",
        },
        {
            "headline": "Fresh Creative, Same Offer",
            "primary_text": f"Reframe {offer} with a clean visual, one benefit, and a simple reason to act today.",
            "cta": "Get Offer",
            "angle": "offer refresh",
        },
        {
            "headline": "Stop Scrolling. Start Here.",
            "primary_text": f"Turn the campaign around with a sharper hook and a visual that makes the value instantly legible.",
            "cta": "Learn More",
            "angle": "scroll-stopper",
        },
    ]
    return templates[:count]


def image_prompt(campaign, ad_config, variant, aspect_ratio):
    brand = ad_config.get("brand", {})
    avoid = ", ".join(brand.get("avoid", [])) or "misleading claims, excessive text"
    return (
        f"Create a Meta ad image for {brand.get('name', 'a premium brand')}. "
        f"Campaign: {campaign.get('name', 'Campaign')}. "
        f"Objective: refresh a {campaign.get('health', 'neutral')} ad with angle '{variant['angle']}'. "
        f"Offer: {brand.get('offer', 'premium product or service')}. "
        f"Visual style: {brand.get('visual_style', 'clean premium ecommerce photography')}. "
        f"Aspect ratio: {aspect_ratio}. "
        "Use a clear focal point, strong product/context signal, realistic lighting, and minimal or no embedded text. "
        f"Avoid: {avoid}."
    )


def build_creative_plan(campaign, ad_config=None, variants_per_campaign=None):
    config = load_config()
    ad_config = ad_config or load_ad_config()
    creative_cfg = ad_config.get("creative", {})
    count = variants_per_campaign or config.creative_variants_per_campaign or int(creative_cfg.get("variants_per_campaign", 3))
    aspect_ratios = creative_cfg.get("default_aspect_ratios", ["1:1", "4:5", "9:16"])
    variants = []
    for index, copy in enumerate(copy_variants(campaign, ad_config, count), start=1):
        prompts = [{"aspect_ratio": ratio, "prompt": image_prompt(campaign, ad_config, copy, ratio)} for ratio in aspect_ratios]
        variants.append({"variant_id": f"v{index}", "copy": copy, "image_prompts": prompts, "assets": []})
    return {
        "id": f"creative_{campaign.get('id', 'campaign')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "created_at": now_iso(),
        "status": "draft",
        "provider": config.creative_provider,
        "image_mode": config.creative_image_mode,
        "campaign": {
            "id": campaign.get("id"),
            "name": campaign.get("name"),
            "health": campaign.get("health"),
            "roas": campaign.get("roas"),
            "ctr": campaign.get("ctr"),
            "frequency": campaign.get("frequency"),
        },
        "variants": variants,
        "upload_policy": {
            "create_ads_as_paused": bool(creative_cfg.get("create_ads_as_paused", True)),
            "requires_approval": True,
        },
    }


def call_nano_banana(prompt, aspect_ratio, config):
    if not config.gemini_api_key:
        return {"ok": False, "error": "GEMINI_API_KEY is not configured"}
    model = config.nano_banana_model
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"imageConfig": {"aspectRatio": aspect_ratio}},
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "x-goog-api-key": config.gemini_api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": exc.read().decode("utf-8")[:1000]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    parts = body.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            mime_type = inline.get("mimeType", "image/png")
            return {"ok": True, "mime_type": mime_type, "data": inline["data"], "raw": body}
    return {"ok": False, "error": "No image data returned", "raw": body}


def save_generated_asset(refresh_dir, refresh_id, variant_id, aspect_ratio, result):
    extension = "png"
    if result.get("mime_type") == "image/jpeg":
        extension = "jpg"
    filename = f"{refresh_id}_{variant_id}_{aspect_ratio.replace(':', 'x')}.{extension}"
    path = refresh_dir / filename
    with open(path, "wb") as handle:
        handle.write(base64.b64decode(result["data"]))
    return {"path": str(path), "mime_type": result.get("mime_type"), "aspect_ratio": aspect_ratio}


def generate_creative_refresh(campaign, generate_images=False):
    config = load_config()
    plan = build_creative_plan(campaign)
    refresh_dir = OUTPUT_DIR / plan["id"]
    refresh_dir.mkdir(parents=True, exist_ok=True)
    if generate_images and config.creative_live:
        for variant in plan["variants"]:
            for prompt in variant["image_prompts"]:
                result = call_nano_banana(prompt["prompt"], prompt["aspect_ratio"], config)
                if result.get("ok"):
                    variant["assets"].append(save_generated_asset(refresh_dir, plan["id"], variant["variant_id"], prompt["aspect_ratio"], result))
                else:
                    variant["assets"].append({"aspect_ratio": prompt["aspect_ratio"], "error": result.get("error", "generation failed")})
    else:
        plan["status"] = "dry_run"
    manifest_path = refresh_dir / "manifest.json"
    write_json(manifest_path, plan)
    update_index(plan, manifest_path)
    return plan, manifest_path


def update_index(plan, manifest_path):
    index = read_json(INDEX_FILE, [])
    summary = {
        "id": plan["id"],
        "created_at": plan["created_at"],
        "status": plan["status"],
        "campaign": plan["campaign"],
        "variant_count": len(plan.get("variants", [])),
        "manifest_path": str(manifest_path),
    }
    index = [item for item in index if item.get("id") != plan["id"]]
    index.insert(0, summary)
    write_json(INDEX_FILE, index[:100])


def recent_creative_refreshes(limit=10):
    return read_json(INDEX_FILE, [])[:limit]

