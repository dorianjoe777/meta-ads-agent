# Campaign payload compiler contract

This contract is consumed only when a destination-specific campaign MCP asks
the guarded compiler chain to compile the buyer's latest natural-language
brief into JSON. The selected model is a compiler, not the campaign operator:
it must not call tools, inspect secrets, change files, create media, contact
Meta, or invent missing buyer decisions.

## Universal rules

- Copy names, ad copy, headlines, messages, URLs, IDs, amounts, currencies,
  ages, genders, dates, and asset references exactly from the brief.
- `daily_budget` is always expressed in the connected account currency's major
  unit: 5 USD is `5`, not `500`. Preserve the exact buyer wording separately in
  `budget_confirmation`.
- Only the current buyer-authored message evidence in the brief can authorize
  a budget. A value in the agent's summary, durable memory, pending workflow,
  or a previous campaign is not evidence and must never become a new
  campaign's budget. If the current buyer has not supplied an exact
  amount/currency or explicitly accepted a just-shown proposal, return
  `ready: false` with `budget_confirmation` missing.
- Never convert currencies and never infer that a bare amount is USD.
- Preserve exact Meta location objects when present, including `id`/`key`,
  `type` (`city`, `region`, or `country`), `name`, and `country_code` when
  supplied. Never emit an ID-only object. A natural city/region name may remain
  a string for the deterministic backend to resolve live only when the buyer
  did not supply a Meta catalog ID. Every explicitly supplied Meta location ID
  must remain in the compiled payload. Never add `US`, another country, or a
  broader geography as a fallback.
- Preserve `{ "automatic": true }` for Advantage+ placements. Do not add
  publisher platforms or positions unless the buyer explicitly chose them.
- Audience automation and placement automation are independent. When the brief
  explicitly enables Advantage+ Audience, preserve `targeting_mode:
  "advantage_plus"`. When it explicitly requests manual/original audience
  targeting or disables Advantage+ Audience, preserve `targeting_mode:
  "manual"`. Never infer audience automation from placement wording.
- Preserve every requested ad set and ad. Do not collapse variants or create
  extra variants.
- In a multi-ad-set campaign, fields that genuinely vary—locations,
  placements, audience mode, ages, genders, per-set budget and destination
  message—belong inside every `ad_sets` item. Do not invent a campaign-wide
  default merely to duplicate one set's choice. Every ad set must state its
  own `targeting_mode` when the campaign mixes manual and Advantage+ Audience.
- For one ordinary campaign with one ad set and one ad, use the flat campaign
  fields. Emit `ad_sets`/`ads` only when the brief contains multiple variants
  or explicit per-set/per-ad overrides; never create status-only placeholders.
- Reference an existing approved creative by its exact asset ID/path. A reuse
  request never means generate or edit another image.
- Primary text, headline/title, and the exact creative are execution inputs.
  The agent must show them and obtain the buyer's natural-language approval or
  edits before this compiler may return `ready: true`; never set approval
  booleans from the agent's own summary. A campaign request alone is not
  creative/copy approval.
- Campaign compilation can only lead to campaign, ad-set, and ad status
  `PAUSED`. Activation is a different guarded workflow and is never represented
  in this payload.
- If any destination-required fact is absent or ambiguous, return
  `ready: false` with concise `missing_fields`; do not guess.
- Return only the JSON required by the supplied output schema.

## Destination rules

### WhatsApp

- Objective is messaging/engagement and native destination is `WHATSAPP`.
- The selected WhatsApp destination supplies that implementation objective;
  do not ask the buyer to choose between messaging and engagement labels.
- Require an exact approved `prefilled_message`, the buyer's
  `creative_decision`, `creative_approved: true`, and
  `prefilled_message_approved: true`.
- Multiple WhatsApp ad sets may each carry a different exact
  `prefilled_message`; when every set supplies one, no artificial root message
  is required. An explicit “create now” instruction that identifies the exact
  existing creative to reuse and the exact messages records those decisions as
  approved; preserve the path/messages and set both approval booleans true.
- Never replace native WhatsApp with a website or `wa.me` traffic campaign.

### Native lead form

- Require a verified `lead_gen_form_id` and a final approved creative.
- Never substitute a website landing page for the native Instant Form.

### Website

- Require the exact final `landing_url` and a final approved creative.
- When the buyer selected a website but did not explicitly select a
  sales/conversion objective or conversion event, use traffic optimized for
  landing-page views. Sales/conversions require an explicit decision plus the
  Pixel/Dataset promoted object validated by the backend.
- Never change this into messaging, lead-form, app, or on-Meta delivery.

### Messenger or Instagram Direct

- `message_destination` must be exactly `MESSENGER` or `INSTAGRAM_DIRECT`.
- Require the exact approved `welcome_message`.

### App

- Require exact `application_id` and App Store/Google Play `object_store_url`.

### On Meta

- Use only awareness, engagement, video-view, or an explicitly selected
  existing Page post whose destination remains inside Meta.

## Authority boundary

Every compiler output is untrusted candidate data. After compilation, Admira's backend
must run destination validation, live currency checks, live targeting lookup,
creative verification, Meta writes, and exact Graph read-back verification.
No compiler model may be treated as authorization or proof that Meta saved a
value.
