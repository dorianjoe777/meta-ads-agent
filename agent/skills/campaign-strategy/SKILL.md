---
name: campaign-strategy
description: "Choose the right Meta Ads campaign strategy for Admira IA: objective, three success metrics, optimization event, budget mode, placements, audience, click-to-message starter, lead form needs, and test structure."
---

# Campaign Strategy Skill

Use this skill before staging or launching a campaign.

## Live Meta audience discovery

- Treat remembered interest names, web research, competitor language, and buyer wording as strategy ideas only. Meta's available interest catalog changes and each real selection needs a current Meta ID.
- Before recommending or staging explicit interests, call `mcp_admira_search_meta_targeting` with `kind: interest` and a useful search phrase. Choose from the live results and preserve both the returned `id` and `name`; never invent IDs or silently convert a phrase into an assumed interest.
- Decide whether those interests should be strict detailed targeting or Advantage+ audience suggestions. For Advantage+ suggestions, pass `targeting_mode: advantage_plus` (equivalent to `targeting_automation: {"advantage_audience": 1}`) plus the exact `targeting_interests` returned by Meta.
- Explain the strategic effect correctly: with Advantage+ audience, interests guide Meta but delivery may expand beyond them. Do not describe them as a hard audience restriction.
- Meta requires an explicit `targeting_automation.advantage_audience` flag when detailed interests are sent. If the buyer has not asked for strict control, recommend Advantage+ suggestions (`1`) for cold prospecting and small tests because Meta can find buyers beyond the seed interests. Recommend strict manual (`0`) only when the buyer explicitly prioritizes a narrow/controlled audience, a regulated constraint, or a retargeting/exclusion rule. State this recommendation before staging; do not ask a blank “Advantage or manual?” question.
- Advantage+ age rule: when `advantage_audience=1`, Meta does not allow an enforced `age_max` below 65. Treat a requested lower maximum (for example 40) as an age suggestion and use an effective maximum of 65. If the buyer needs a strict upper age limit, recommend `targeting_mode: manual` / `advantage_audience=0` and explain that this trades algorithmic expansion for control. Never retry the invalid Advantage+ payload unchanged.

## Minimum strategy

Collect or infer:

- offer/product and target audience/location;
- objective: sales, leads, messages, bookings, traffic, awareness, or retargeting;
- the three success metrics/results in priority order;
- budget, target CPA/CPL when known, and account currency;
- landing URL or message/lead destination;
- optimization event and signal quality needs;
- creative formats and placements that fit the asset.

Do not over-question. Infer safe defaults from the business, offer, budget, destination, existing memory, and the buyer's request. Ask only for details that materially change the campaign or are required for a protected/live action. If the campaign can be prepared paused for approval with a clear assumption, prepare it instead of asking whether to proceed.

Do not ask broad campaign questions as a blank form. For each important lever, first give the professional recommendation and why:

- geography/market: infer from language, offer, payment platform, shipping/service area, page, website, and previous conversation; never default silently to US;
- objective and optimization event: recommend the deepest reliably tracked business outcome; use volume to explain confidence and volatility, not to automatically replace the real outcome with an easier proxy;
- budget mode and test size: recommend ad set budget or campaign budget based on budget, number of ad sets, and need for control;
- placements: recommend from the creative format and buyer behavior, not from a rigid default;
- creative portfolio: recommend the number and types of creatives that the budget can realistically test;
- destination: recommend website, WhatsApp/Messenger, Instagram DM, lead form, or booking flow based on friction and buyer intent.

If recent market context could improve the choice, use available web/browser/search tools before finalizing. Then summarize the recommendation in buyer language and ask only for a correction or one strategic confirmation.

## Optimization event

- When the campaign's purpose is direct revenue, optimize for the final economic outcome: use `Purchase` for a completed transaction. When the campaign intentionally has another purpose, choose the event that directly represents that purpose instead of forcing a sales event.
- The often-cited ~50 weekly events is learning guidance, not a binary minimum; below it Meta still optimizes, but results may fluctuate or show Learning Limited.
- Do not choose `InitiateCheckout` merely to obtain more events or avoid Learning Limited. Check checkout-to-purchase quality: if many checkouts rarely buy, that proxy teaches Meta to find checkout starters, not buyers. Keep checkout and other funnel events as secondary diagnostics.

## Message campaigns

For WhatsApp, Messenger, or Instagram Direct, ask what initial message/welcome text should appear or propose 2-3 concise options. For WhatsApp, use a buyer-sent `prefilled_message`. For Messenger/Instagram, use `welcome_message`, `quick_replies`, and `message_flow_id` only when supported by the connected messaging flow. Never imply unsolicited first messages.

## Budget and placements

Use ad set budget by default for small controlled tests. Use campaign budget/CBO when several ad sets should compete and budget is high enough. Choose placements from the creative and audience, not a rigid checklist.

## Lead forms

For native Meta Lead Ads, check existing forms in Meta first. If a new form is needed, help the buyer design its exact name, questions, privacy policy URL, thank-you URL when useful, and form intent. Then guide them to create and publish it once in Meta Ads Manager: Leads objective → Instant forms conversion location → Ad level → Instant form → Create form. Do not claim the form was created by Admira and do not request a product approval for form creation. Ask the buyer to say when it is ready, list live forms again, match the exact form, and persist its real `lead_gen_form_id` in the campaign brief.

Once the live form ID exists, set the campaign objective to Meta's current `OUTCOME_LEADS` (with ad-set `LEAD_GENERATION`, conversion location `ON_AD`, and the Page `promoted_object`). Pass the verified form ID directly into the inline image/video creative; no external landing URL or dark post is required. Never let a stale `SALES`/`OUTCOME_SALES` default survive on a lead-form campaign.

## Video website ads

For video ads that send people to a website, use the native ad-account video upload and inline creative route by default. Ads Manager completion remains an optional workflow when the buyer specifically wants manual crop/placement preview control or Meta rejects an unsupported media asset.

Recommended decision:

- If the buyer wants the easiest manual finish: prepare the campaign and ad set paused, then guide them to complete the video creative in Ads Manager.
- If the buyer explicitly chooses manual completion, create paused ads with simple temporary static placeholders, copy, CTA, URL, names, targeting, and budget already filled. Tell them to replace each placeholder with its corresponding final video and verify the website link before activating.
- When several video concepts were defined in conversation, name each paused placeholder ad from the actual concept/hypothesis, not generically. Examples: `UGC - Objeción precio`, `Demo - cómo funciona`, `Oferta - reserva hoy`.
- If no provisional image exists, it is acceptable to let the backend create a plain temporary placeholder image. It is not a real ad creative; it only saves setup clicks.
- This optional workflow is only for video creatives. Static and normal video ads should use the native inline Ads app route.
- Never imply Meta supports an empty ad without a creative. The API requires a creative before an ad can be created.
- Never leave placeholder ads active. They must stay paused until the real video is reviewed.

Explain this simply: “I can leave the structure and paused placeholder ads ready, so you only replace the image with the video in Ads Manager and check previews before turning it on.”
