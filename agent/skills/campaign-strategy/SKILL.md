---
name: campaign-strategy
description: Choose the right Meta Ads campaign strategy for Admira IA: objective, three success metrics, optimization event, budget mode, placements, audience, click-to-message starter, lead form needs, and test structure.
---

# Campaign Strategy Skill

Use this skill before staging or launching a campaign.

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

## Message campaigns

For WhatsApp, Messenger, or Instagram Direct, ask what initial message/welcome text should appear or propose 2-3 concise options. For WhatsApp, use a buyer-sent `prefilled_message`. For Messenger/Instagram, use `welcome_message`, `quick_replies`, and `message_flow_id` only when supported by the connected messaging flow. Never imply unsolicited first messages.

## Budget and placements

Use ad set budget by default for small controlled tests. Use campaign budget/CBO when several ad sets should compete and budget is high enough. Choose placements from the creative and audience, not a rigid checklist.

## Lead forms

For native Meta Lead Ads, check existing forms when possible. If a new form is needed, gather name, questions, privacy policy URL, thank-you URL when useful, and form intent before execution.

## Video website ads

For video ads that send people to a website, be practical and buyer-friendly. Until the product has a central approved Meta ads app, do not keep forcing brittle full video creative creation through the API when Ads Manager is better for previewing video crops, placements, and final appearance.

Recommended decision:

- If the buyer wants the easiest manual finish: prepare the campaign and ad set paused, then guide them to complete the video creative in Ads Manager.
- If the buyer wants maximum time saving, or the video route keeps failing: create paused ads with simple static temporary dark/placeholder creatives, copy, CTA, URL, names, targeting, and budget already filled. Tell them to replace each placeholder image with its corresponding final video and verify/adjust the final website link in Ads Manager before activating.
- When several video concepts were defined in conversation, name each paused placeholder ad from the actual concept/hypothesis, not generically. Examples: `UGC - Objeción precio`, `Demo - cómo funciona`, `Oferta - reserva hoy`.
- If no provisional image exists, it is acceptable to let the backend create a plain temporary placeholder image. It is not a real ad creative; it only saves setup clicks.
- This workaround is only for video creatives. Do not apply it to normal static-image ads; static ads should use the normal direct-publishing/Image route.
- Never imply Meta supports an empty ad without a creative. The API requires a creative before an ad can be created.
- Never leave placeholder ads active. They must stay paused until the real video is reviewed.

Explain this simply: “I can leave the structure and paused placeholder ads ready, so you only replace the image with the video in Ads Manager and check previews before turning it on.”
