# Branding Creatives Creation Skill

Use this skill after the buyer has explained the business basics and before asking about prior campaigns.

## Goal

Create durable creative memory so every future ad image, ad copy, and campaign idea feels like the buyer's real brand.

This is not just "pretty branding". It is the ad creative operating system:

- general brand style
- logo and how to use it
- product or offer details
- approved references
- ad brief per promotion, product, campaign, or ad set
- rules for fixed variants and freer creative exploration

## Required Memory

Use product tools. Do not edit arbitrary files directly.

- `mcp_admira_save_brand_memory`
- `mcp_admira_save_product_memory`
- `mcp_admira_save_creative_references`
- `mcp_admira_save_ad_brief`
- `mcp_admira_codex_creative_plan`
- `mcp_admira_codex_image_generate`

## General Brand Questions

Ask one question at a time. Keep the language simple.

Collect enough to save:

- brand name
- what the business sells
- main promise
- ideal buyer
- tone of voice
- colors
- typography or letter style
- visual style
- what must always appear
- what must never appear
- logo notes

If the buyer sends a logo image, save it as brand memory. Include useful notes such as shape, colors, when to show it, and when not to show it. The backend can store uploaded reference images as the logo when the tool request clearly mentions logo.

## Product Or Offer Questions

For each important product, service, promo, or offer, collect:

- product or offer name
- sales page or public link if available
- price or range
- what the buyer receives
- who it is for
- pain
- desire
- objections
- approved strong phrases
- what to show
- what to avoid

Save each with `mcp_admira_save_product_memory`.

## Creative References

Use web/browser retrieval when available to look for ad design references from the niche.

Do not copy competitors directly. Use them to extract:

- layout patterns
- color moods
- product presentation
- offer framing
- social proof patterns
- hook styles

Ask the buyer which references they like. Save approved references with `mcp_admira_save_creative_references`.

## Ad Briefs

When the buyer wants a specific ad, promotion, campaign, or ad set, create an ad brief. Collect:

- what is being promoted
- who should see it
- desired action
- key offer or promo
- what cannot change
- whether they want one idea or several options
- what can vary
- image or copy constraints

Save with `mcp_admira_save_ad_brief`.

## Image Creation

For actual finished images, always use `mcp_admira_codex_image_generate`. Do not use Hermes internal image generation. The product routes final image generation through the buyer's connected ChatGPT/Codex session.

Use:

- `mode: "fixed"` when the buyer wants brand consistency, logo consistency, or variants of an ad that already works.
- `mode: "free"` when the buyer wants very different creative directions.

If the saved brand guide has `Logo de marca` or `Notas del logo`, tell the image tool to respect it. Never invent a different logo.

## Conversation Pattern

1. Confirm what you already understood.
2. Ask one missing question.
3. Save useful answers as soon as they are stable.
4. When brand and product memory are good enough, say what has been saved.
5. Move to prior campaigns and current ad goals.

## Tone

Warm, decisive, beginner-friendly Spanish by default.

Example:

> Ya tengo la base de tu marca: colores, tono, tipo de cliente y logo. Ahora quiero entender qué producto vamos a empujar primero para que los creativos no salgan genéricos.
