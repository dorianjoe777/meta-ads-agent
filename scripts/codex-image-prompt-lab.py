#!/usr/bin/env python3
"""Generate and optionally run Codex image-prompt packages for Meta Ads creatives."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import codex_brand_guides as guides  # noqa: E402


def configure_root(root):
    root = Path(root).resolve()
    guides.ROOT_DIR = root
    guides.BRAND_DIR = root / "brand_guides"
    guides.PRODUCT_DIR = guides.BRAND_DIR / "products"
    guides.AD_BRIEF_DIR = guides.BRAND_DIR / "ad_briefs"
    guides.GENERAL_GUIDE = guides.BRAND_DIR / "general_branding.md"
    guides.CREATIVE_REFERENCES_FILE = guides.BRAND_DIR / "creative_references.md"
    guides.GENERAL_EXAMPLE = guides.BRAND_DIR / "general_branding.example.md"
    guides.PRODUCT_EXAMPLE = guides.PRODUCT_DIR / "product.example.md"
    guides.AD_BRIEF_EXAMPLE = guides.AD_BRIEF_DIR / "ad_brief.example.md"
    guides.BUSINESS_PROFILE_FILE = root / "dashboard" / "data" / "business_profile.json"
    return root


def read_request(args):
    parts = []
    if args.request:
        parts.append(args.request.strip())
    if args.request_file:
        parts.append(Path(args.request_file).read_text(encoding="utf-8").strip())
    return "\n\n".join(part for part in parts if part)


def default_output_path(root, mode):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return root / "output" / "codex-image-prompts" / f"{stamp}-{mode}.json"


def main():
    parser = argparse.ArgumentParser(
        description="Build fixed or free creative prompt packages using brand, product and ad brief memory."
    )
    parser.add_argument("--root", default=str(ROOT_DIR), help="Project/install root. Defaults to this repo.")
    parser.add_argument("--mode", choices=["fixed", "free"], default="fixed", help="fixed keeps strict brand consistency; free explores varied design routes.")
    parser.add_argument("--product", default="", help="Product guide slug or path inside brand_guides/products.")
    parser.add_argument("--ad-brief", default="", help="Ad brief slug or path inside brand_guides/ad_briefs.")
    parser.add_argument("--request", default="", help="Natural-language creative request.")
    parser.add_argument("--request-file", default="", help="Optional file with a longer creative request.")
    parser.add_argument("--variations", type=int, default=3, help="Number of prompt variants to prepare.")
    parser.add_argument("--seed", default="", help="Use a seed for repeatable free-mode route selection.")
    parser.add_argument("--out", default="", help="Where to save the JSON manifest.")
    parser.add_argument("--execute-codex", action="store_true", help="Also ask Codex CLI to refine the final image prompts.")
    parser.add_argument("--codex-model", default="", help="Optional Codex model override for the execute step.")
    parser.add_argument("--timeout", type=int, default=120, help="Codex CLI timeout in seconds.")
    args = parser.parse_args()

    root = configure_root(args.root)
    request = read_request(args)
    package = guides.build_codex_image_prompt_package(
        product_guide=args.product,
        ad_brief=args.ad_brief,
        request=request,
        mode=args.mode,
        variations=args.variations,
        seed=args.seed or None,
    )
    if args.execute_codex:
        package["codex_result"] = guides.call_codex_cli(package["codex_prompt"], timeout=args.timeout, model=args.codex_model)
    out_path = Path(args.out).resolve() if args.out else default_output_path(root, args.mode)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Manifest saved: {out_path}")
    print(f"Mode: {package['mode']} · Variants: {package['variation_count']} · Seed: {package['seed']}")
    print("Design axes:")
    for item in package["variation_ledger"]:
        print(f"- {item['variant_id']}: {item['design_axis']}")


if __name__ == "__main__":
    main()
