---
name: campaign-strategy
description: "Choose the right Meta Ads campaign strategy for Admira IA: objective, three success metrics, optimization event, budget mode, placements, audience, click-to-message starter, lead form needs, and test structure."
---

# Campaign Strategy Skill

Use this skill to design or complete a campaign brief. Strategy and execution are separate states.

## Intent state before tools

Classify the conversation by meaning, not keywords:

1. **Explore/advise:** the buyer states a goal, asks what to do, or discusses an idea. Recommend a strategy and gather only the next material input. Do not call a campaign creator.
2. **Complete the brief:** the buyer answers a question about budget, audience, destination, message, placements, or creative. Preserve that answer and continue the brief. An answer to one field does not authorize campaign creation or media generation.
3. **Execute:** the buyer directly asks to prepare or create the campaign, or clearly accepts a complete campaign proposal that explicitly says it will now create PAUSED Meta objects. Only then follow the compact execution procedure already supplied and call the destination MCP; do not add a read-file unlock turn.

Do not manufacture authorization through your own question. While important fields or the final creative decision are missing, ask about those fields—not “shall I leave the campaign ready?” Never combine a discovery question with an execution confirmation. If the buyer says no creative exists, present the natural choices (create, reuse recent, or upload) and wait for their choice; do not list or generate assets unless they request that outcome.

Every new campaign or offer opens a new scope. Do not inherit the previous campaign's budget, currency, offer, audience, geography, copy, title, CTA, destination message, or creative merely because it was discussed immediately before. Parent-brand visual identity may carry over; commercial decisions belong to the active child offer and must be restated or re-confirmed.

## Transition from business onboarding into a campaign

The confirmed strategic profile is input to the recommendation, not a form to
repeat. When the buyer asks for a campaign after completing the business and
brand foundation:

- do not recite the profile and ask the buyer to confirm it again;
- turn it immediately into a concrete first-test recommendation: offer,
  commercial angle, audience, destination/funnel, test structure, creative
  hypotheses, and the three results that should decide whether to continue;
- explain briefly how the known price, contribution margin, capacity,
  differentiators, market and objective shaped that recommendation;
- distinguish facts already confirmed for the business from decisions that
  belong only to this new campaign;
- ask only for the highest-impact missing campaign decision after presenting
  the useful recommendation.

Read the confirmed `memory/Business master plan.md` before designing the child
campaign. Explain which master-plan priority this campaign advances. Reuse the
global diagnosis, positioning, funnel and KPI hierarchy; do not regenerate the
master plan. Campaign-specific budget, offer, audience slice, copy, creative,
destination and hypothesis remain isolated in that campaign's own ad brief.

A suggested budget range is advice, not a selected budget. Never convert a
range such as 30,000–50,000 COP into 40,000 COP merely because the buyer says
"yes" or asks to create a campaign. If the exact current-campaign amount is
missing, recommend a specific amount with its rationale and ask the buyer to
accept or change that amount in ordinary language. Do not ask the buyer to
confirm the same profile, strategy or creation intent twice.

## Manager-led discovery before production

When the buyer asks for a new campaign, behave like the accountable marketing manager who must defend the investment—not like a form or a payload executor. Start with the live Meta context and the saved business/product/ads documents, then fill only the owner-only gaps that materially change the plan. Build the plan in this order:

1. **Business outcome and horizon:** what must improve (sales, qualified leads, booked consultations, real WhatsApp conversations, foot traffic, or another result) and by when.
2. **Active offer:** the exact product/service/package, what is included, price or price range, capacity/availability, service area, proof, and the commercial differentiator.
3. **Ideal customer:** who decides, who pays, location, trigger/problem, desired outcome, objections, and why they should act now.
4. **Funnel and follow-up:** destination, first reply/message, qualification questions, response time, booking/closing process, and the step that turns a lead or conversation into revenue.
5. **Economics:** price or average order value, variable cost or contribution margin, close/booking rate when known, acceptable CPA/CPL or cost per real conversation, and the daily/test budget in the account currency. If a figure is unknown, label it as an assumption or range; never invent precision.
6. **Measurement and projection:** recommend up to three success metrics, calculate a simple break-even threshold, and give conservative/base/upside expectations for the test. State what will be checked after 24 hours, 3 days, and 7 days. This is a planning estimate, never a guarantee.

Ask related owner-only facts together in one natural packet when possible, not as a long checklist. If the buyer cannot provide costs or conversion rates, proceed with a clearly labelled sensitivity range and explain which number would most change the recommendation. Save stable business facts with `mcp_admira_save_business_memory`, the active offer with `mcp_admira_save_product_memory`, account-wide ads history/defaults only with `mcp_admira_save_ads_onboarding`, and this campaign's complete goals/KPIs, budget/currency, hypothesis, copy, projection and plan with a uniquely named `mcp_admira_save_ad_brief`. Do not write these Markdown files manually. When updating an existing campaign brief, reuse its returned brief ID; for a new campaign, do not reuse another campaign's ID or name.

Before any image/video tool, present a concise strategic read-back: recommended angle and audience, exact primary text, distinct title, CTA/destination message, visual concept, and the economic hypothesis it tests. Let the buyer correct or approve that direction. Only after that should the creative be produced and reviewed; only after the complete brief is resolved should the paused Meta structure be handed to the destination MCP.

The first campaign reply does not need to contain final copy or a generated
creative when a material owner decision is still missing. It must nevertheless
contain a real plan. Once the direction is resolved, show the exact copy and
visual concept together, create the requested asset, attach it, and review that
exact package collaboratively before asking to create Meta objects.

## Live performance authority

The ad brief is planning memory: its KPIs, break-even, projections, and hypotheses describe what to measure, not what Meta has actually delivered. Before claiming spend, delivery, status, results, CPA, ROAS, conversations, leads, audience, or learning, call `mcp_admira_get_real_meta_context` and use the current synchronized Meta values. If live Meta is unavailable or partial, say that the result is unknown and keep the brief's projections clearly labelled as estimates. Never let a saved brief override current Meta state.

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

## Ad copy is part of the strategy

Do not treat the creative as complete when only the image/video exists. For
each ad, develop and discuss the exact Meta ad copy package:

- copy principal/texto del anuncio: the problem, promise, proof, offer, and next step in the
  buyer's language;
- title/título del anuncio: a short, distinct benefit or action-oriented hook;
- CTA and the destination-specific WhatsApp prefilled message, Messenger
  welcome, lead-form context, or website framing.

Recommend the strongest copy based on the active offer and audience, show it in
the conversation, and let the buyer approve, edit, or replace it before
execution. Keep different hypotheses attached to their own ad variants. The
campaign name is an internal label and should not become the title by default.
Review it only through ordinary conversational text; never use `clarify`, a
choice card, or a generic approval button. The creative and copy are a joint
natural-language review with the buyer, not an internal handoff.

Do not over-question. Infer safe defaults from the business, offer, budget, destination, existing memory, and the buyer's request. Ask only for details that materially change the campaign or are required for a protected/live action. Safe defaults may complete a proposal, but they never convert a planning conversation into execution.

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

## Campaign read-back before staging

Before handing the brief to the matching destination-specific campaign tool, read it back as a compact
contract: business goal versus Meta outcome, destination, exact gender and
age, automatic/Advantage+ or manual placements, and every ad's approved
primary text, headline, CTA, and WhatsApp prefilled/Messenger welcome text.
Correct any mismatch before calling Meta. State clearly that accepting this complete read-back will create PAUSED Meta objects; only the buyer's natural acceptance of that complete proposal authorizes the handoff. Never allow a missing field to turn
into generic copy, an all-gender audience, default US targeting, or default
manual placements. For click-to-WhatsApp, explain that Meta's native outcome
may be shown as Engagement while the ad set optimizes Conversations; this is
different from silently changing a website-sales campaign to Engagement.

## Lead forms

For native Meta Lead Ads, follow the compact lead-form procedure already supplied and check existing forms first. If a new form is needed and the buyer asks to create it, collect its exact name, approved questions, privacy-policy URL, optional follow-up URL, and form intent, then use the direct form tool. Use the manual Ads Manager fallback only when the direct tool returns a real Meta permission/capability blocker. Require a verified real `lead_gen_form_id` before the campaign handoff.

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
