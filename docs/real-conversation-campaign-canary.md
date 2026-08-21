# Real conversation campaign canary (simulated Telegram)

Use this runbook when the operator asks for a real Hermes conversation test that
creates a complete Meta campaign. It exercises the same buyer-facing path as
Telegram without sending a Telegram message. It may create real Meta objects,
so use it only after the operator explicitly authorizes PAUSED canary creation.

## Safety contract

- Run only on the requested canary droplet/container, never in the local repo.
- Use `telegram_agent.handle_text(..., send=False)` with a reserved negative
  chat ID. This invokes Hermes and the configured main model but does not send
  to Telegram.
- Give the campaign a unique `CANARY - ...` name.
- Require campaign, ad set, and ad to remain `PAUSED`; never authorize spend.
- Use a small explicit daily budget and currency.
- Record every real Meta ID. Delete the canary through
  `mcp_admira_delete_campaign` plus its exact `mcp_admira_approve_action`
  approval after verification.
- If any requested field differs in Meta, the test fails even if Hermes says it
  succeeded. Keep the objects paused, capture the exact call, then clean up.

## Preconditions

Verify the container, dashboard, main model, and MCP inventory:

```bash
docker inspect <container> --format 'image={{.Config.Image}} status={{.State.Status}} restart={{.RestartCount}}'
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:7871/
docker exec <container> hermes mcp test admira
```

The destination-specific creation tools must be visible and the broad legacy
`stage_campaign` tool must not be public.

## Execute through the real conversation path

Use an existing isolated canary chat when the campaign should reuse a creative
made earlier in that conversation; otherwise use a new unique negative ID.

```bash
docker exec -i <container> sh -lc '
  cd /app && PYTHONPATH=/app/src:/app/dashboard python3 -
' <<'PY'
from product_config import load_config
from telegram_agent import handle_text

chat_id = -820080099
prompt = """Crea una campaña canary real, completamente PAUSADA y sin gasto.
Nombre exacto: CANARY - Example - 2026-08-19. Presupuesto diario: 5 USD.
Público: Cartagena, Colombia, edades 25 a 55, todos los géneros.
Usa ubicaciones automáticas Advantage+. Crea campaña, conjunto y anuncio;
no pidas una segunda aprobación y no actives nada."""
print(handle_text(load_config(), chat_id, prompt, send=False))
PY
```

Do not use `ssh -tt` with the heredoc. A pseudo-terminal can keep Python waiting
for EOF, which looks like a hung agent even though no conversation began.

## Inspect the exact Hermes call

Read the current session messages from `/app/runtime/hermes/state.db`. Confirm
that Hermes selected the correct destination MCP and inspect its serialized
arguments. Pay special attention to retries after contract validation.

The destination MCP call must now contain exactly one `brief_markdown`. Inspect
that Markdown and confirm it naturally includes the buyer's exact budget and
currency, destination, audience, live location selection, placements, creative
reference, copy/messages, and approval state. Gemini/Hermes must not assemble
the nested payload itself.

The bridge privately overwrites these two operational artifacts:

- `dashboard/data/campaign-compiler/latest-campaign.md`
- `dashboard/data/campaign-compiler/latest-campaign-payload.json`

It sends the Markdown plus `agent/contracts/campaign-payload-compiler.md` to
the guarded compiler chain: `gemini-3.5-flash`, then `gemini-3.6-flash`, then
`gpt-5.6-terra` through Codex CLI and the connected ChatGPT subscription.
Compiler models produce candidate JSON only; they do not call Meta. Confirm the
tool result reports the selected `payload_compiler.model` and ordered
`compiler_attempts`. A provider failure or malformed/contract-invalid output
advances to the next compiler. A valid `ready=false` ambiguity refusal is
terminal and must never be retried with a more willing model. The backend then treats
`budget_confirmation` as authoritative, resolves targeting, forces PAUSED, and
applies every deterministic validation before the first mutation.

## Verify directly in Meta

Never rely only on Hermes text or the local saved campaign file. Read the real
campaign, ad set, and ad IDs from Graph with the active OAuth connection.

Pass only when all requested facts are confirmed:

1. Campaign and ad set are `PAUSED` (the new ad may temporarily be
   `IN_PROCESS`/`PENDING_REVIEW`).
2. Meta's `daily_budget` minor-unit value matches the requested major amount;
   for USD, Graph `500` means 5 USD.
3. `geo_locations` contains the requested country/city/region and exact live
   key. It must not contain an unrelated fallback country.
4. Automatic placements are represented by the absence of explicit
   `publisher_platforms`/position lists. Manual placements must match the exact
   requested lists.
5. Campaign, ad-set, and ad IDs are all real and linked to one another.

`targeting_automation.advantage_audience` describes audience expansion, not
placement automation; do not use it to judge automatic placements.

## Cleanup and final verification

Call `mcp_admira_delete_campaign` with the exact canary campaign ID, extract its
approval ID, then call `mcp_admira_approve_action`. Finally query all canary IDs
again and confirm none remain accessible/listed. Report any cleanup failure and
leave the exact PAUSED IDs for manual removal.

## Failure patterns found in real canaries

- A pre-model Telegram approval router treated “the creative is approved”
  inside a complete campaign brief as a pending-action decision. With no
  linked approval card, natural language must continue to Hermes; only an
  unambiguous card-context response uses the deterministic approval fast path.
- Flat `ads[]` become an implicit ad set and the campaign arguments are
  normalized more than once. The implicit set must inherit the exact top-level
  location, age, gender, targeting mode, and placement decision on every pass.
  Losing them produced `targeting_location_missing` even though Hermes supplied
  live Cartagena key `459425` correctly.
- Reusing an existing creative must never call image generation. The campaign
  Markdown references the exact recent asset/path; Terra only compiles that
  reference and cannot create or edit media.
- A real Gemini turn exposed a non-empty destination schema cached from the
  previous contract. The provider compatibility layer must replace every
  Admira schema with the current canonical schema, not only repair empty
  schemas. For explicit existing-creative reuse, keep
  `list_recent_creatives` visible but remove image/video generation for that
  turn. The private provider instruction requires one complete
  `brief_markdown`; after a compiler error it permits at most one complete
  retry and forbids partial field-by-field retries.
- Inspect every destination tool call, not only the successful final call. A
  generated image, an old structured-argument call, or several progressively
  smaller Markdown retries fails the conversational canary even when the last
  call creates real Meta IDs.
- Terra compilation depends on the buyer's Codex subscription, current Codex
  CLI support for `--output-schema`, and availability of `gpt-5.6-terra` for
  that subscription. A disconnected/expired OAuth session, unsupported model,
  old CLI, usage limit, invalid structured-output schema, or compiler timeout
  must fail before Meta and preserve the latest Markdown for retry.

- A model converted `5 USD` to `daily_budget: 500`. The backend must reparse
  `budget_confirmation` and perform Meta's minor-unit conversion only at the
  Graph boundary.
- A live Cartagena object was sent under loose `locations`; an older
  normalizer erased it and silently used US. Live city/region objects must be
  promoted to `targeting_locations`, and missing geography must block.
- The same failure can occur inside an explicit
  `ad_sets[*].targeting.locations` payload even when the top-level destination
  contract is correct. Treat structured `{id/key, name, type}` city/region
  objects as live selections at every nesting level. Never stringify them as
  country names and never replace an unrecognized shape with US.
- Post-write verification must compare the exact requested and persisted
  `geo_locations` signature (countries/cities/regions and their keys). Checking
  only interests or `advantage_audience` is insufficient. A mismatch is a
  failed canary and must trigger safe cleanup of the newly created PAUSED
  stack instead of producing a buyer-visible success message.
- A destination MCP can carry `placements: {"automatic": true}` at the top
  level while flat `ads[]` are normalized into an implicit ad set. Propagate
  that decision to every ad set without an override. Otherwise execution falls
  back to the legacy manual Facebook/Instagram feed+story list even though the
  model and buyer both requested Advantage+ placements.
- Post-write verification must compare placement mode and exact manual
  positions too. For automatic placements Graph should contain no explicit
  `publisher_platforms` or per-platform position lists; their presence is a
  failed automatic-placement canary.
- Gemini emitted `placements: {"\"automatic\"": true}`. The bridge must
  canonicalize quoted keys and reject unknown placement structures.
- A WhatsApp message containing the phrase `para mi empresa` was mistaken for
  a business-onboarding introduction, hiding every campaign MCP and causing a
  12-iteration file-search loop. Explicit campaign creation now wins over
  incidental business phrases inside approved copy or messages.
- A compiler preserved automatic placements but omitted an explicitly chosen
  Advantage+ Audience decision. The compiler boundary now extracts that one
  explicit brief decision and rejects any candidate that omits or contradicts
  `targeting_mode`, advancing safely to the next compiler before Meta.
- Advantage+ Audience is not compatible with every hard demographic range.
  Current preflight correctly blocked `age_max=60` and `age_min=35` requests
  before writing; the tested compatible 25–65 configuration persisted
  `targeting_automation.advantage_audience=1` in Graph.
- A website brief without an explicit objective previously fell through to
  sales/offsite conversions and required a Pixel. The server now defaults a
  bare website destination to traffic/landing-page views; explicit sales or
  conversions still require the real Pixel/Dataset promoted object.
- A campaign-creation request that reaches the final response without any
  creation-tool evidence must never be described as configured, ready, or
  paused. The response guard now reports that nothing was created.
- A buyer-visible success sentence can disagree with the live Meta payload.
  Direct Graph verification is always the final authority.
- A natural `locations: ["Cartagena de Indias, Colombia"]` list was initially
  reduced to country `CO` because location-query parsing handled a scalar
  `"City, Country"` but not the same phrase inside a one-item list. Parse each
  delimited list item recursively, preserve `targeting_location_queries`
  through repeated implicit-ad-set normalization, resolve it live, and require
  Graph to persist Cartagena city key `459425` rather than broad Colombia.
- Natural all-gender phrases such as "hombres y mujeres", "women and men" and
  "todos los géneros" must normalize to Meta `[1, 2]`. Unknown phrases still
  fail closed instead of broadening silently.
- Destination words inside negations are not intent. "Instagram Direct; no
  WhatsApp ni Messenger" must expose only the Instagram Direct campaign
  creator, while "Messenger; no WhatsApp" must expose Messenger.
- For Messenger/Instagram Direct, verify the creative's actual
  `page_welcome_message` through Graph. A compiler payload or durable campaign
  file containing `welcome_message` is insufficient evidence; both the
  campaign materializer and the Graph serializer can independently drop it.
- Meta `photo_data` does not accept a `title` field (observed code `100`,
  subcode `1443050`). When an on-Meta image brief requires a headline, use
  `link_data` to the selected Facebook Page without an external CTA, then
  verify `link_data.name` exactly.
- A compiler may emit a live place as `locations:[{id,name}]` without `type` or
  `country_code`. Resolve the name against Meta and enrich only the exact
  matching ID before mutation. Never pass an unknown structured type through
  to execution, because it becomes empty `geo_locations`.
- Native Instagram Direct requires a bound professional
  `instagram_actor_id`. Graph may provisionally accept a stack without it and
  later block edits/deletion with `2534013`; preflight this before creating the
  campaign. Treat an `IN_PROCESS` ad as provisional until destination identity
  is valid.
- Measure full Hermes latency separately from Graph latency. In R2, several
  natural-language turns took minutes while the eventual Meta operations took
  only seconds. A response before the five-minute product timeout can still be
  operationally slow and should be recorded in canary evidence.

## Passing reference conversation (r60)

The final real simulated-Telegram canary used ordinary Spanish and exposed no
image-generation tool because the buyer requested reuse. Hermes called
`list_recent_creatives` once and `create_whatsapp_campaign` once with only
`brief_markdown`. Terra compiled it in the destination tool. Direct Graph
confirmed campaign `120253688767630722`, ad set `120253688767850722`, creative
`1754145055773091`, and ad `120253688768710722`: all configured PAUSED; 5 USD
as ad-set `daily_budget=500`; Cartagena city key `459425`; ages 25–65; genders
`[1,2]`; automatic placements; native WhatsApp; exact copy, headline and
starter message. The campaign, ad set and ad were then deleted through the real
approval conversation and Graph confirmed `DELETED`. Meta separately accepted
deletion of the four exact CANARY creative objects left by r57-r60; the cleanup
used an allowlist plus a `CANARY` name check and did not touch buyer campaigns
or creatives.

## Complex multi-turn 4x4 procedure

Use this variant when the operator asks whether Hermes can preserve a large
natural-language campaign instead of merely accepting a compact one-shot
brief. It is the reference procedure used for R3/R4.

1. Reserve a new negative chat ID and send the brief in at least three ordinary
   buyer turns. Put destination and budget in the first turn, per-ad-set
   audience/placement details in the second, and all ads/copy/URLs/messages in
   the third. Explicitly say not to create yet in the first two turns.
2. After each deferred turn, inspect Meta by the unique campaign name and prove
   that no object was created. A friendly acknowledgement is acceptable; any
   Graph mutation is a failure.
3. In the final turn, confirm the accumulated brief in natural language. Do not
   send an MCP payload and do not call the MCP directly. Let Hermes choose the
   destination MCP and let the server-side compiler build the payload.
4. Inspect every tool call and retry. The final destination call must use one
   `brief_markdown`; image generation may remain available when the buyer asks
   to create or vary media, but it must not be called when an existing creative
   is explicitly reused.
5. Verify through Graph, not the chat response. For a 4x4 test require exactly
   one campaign, four ad sets, sixteen ads, and sixteen expected creative
   references/instances. Compare PAUSED state, budget location (campaign for
   CBO or each ad set for ABO), minor-unit values, exact geo IDs, age/gender,
   targeting automation, exact placement lists, destination identity, copy,
   headlines, URLs/UTMs, and native conversation messages.
6. If any branch differs, mark the whole matrix failed, keep it PAUSED, capture
   the candidate payload and Graph response, and delete only the exact canary
   IDs. A buyer-visible success sentence is never evidence of success.
7. Run the focused contract suite after each correction. The current baseline
   after the complex matrices is 93/93 passing tests:
   `tests.test_campaign_contract_regression`,
   `tests.test_nvidia_inference_policy`, and
   `tests.test_tool_argument_normalization`.

The final R3 WhatsApp ABO matrix proved four ad sets, sixteen ads, sixteen
unique creatives, exact mixed audience/placement modes, and exact native
WhatsApp messages. The final R4 website CBO matrix proved the same 4x4 shape,
campaign-level 20 USD/day (`2000` Meta minor units), no ad-set budgets, and
sixteen distinct UTM URLs. Both were fully deleted by exact campaign ID after
verification. Meta may retain ad-creative message objects with subcode
`1487235` after their campaigns are deleted; record that state rather than
attempting broad or repeated deletion.

## Native lead-form capability canary (2026-08-20 UTC)

This is a separate no-campaign test. The active selected Page was resolved
automatically as `1333279616526600` (`E.Q.Perez S:A:C Firma de Abogados`).

1. `admira_list_lead_forms` reached
   `1333279616526600/leadgen_forms` with a Page Access Token and returned HTTP
   200 with an empty `data` array.
2. `admira_create_lead_form` was called once with the exact canary name
   `CANARY - Lead Form - 2026-08-20 - Direct API`, standard `FULL_NAME`,
   `EMAIL`, and `PHONE` questions, `https://amira.uboost.com/privacy`, Spanish
   locale, and `HIGHER_INTENT`.
3. Meta returned HTTP 400, Graph error code `3`:
   `Application does not have the capability to make this API call.` No form
   ID was returned and no campaign or spend was created.

The connected OAuth user is `997589869987375`; its granted permissions include
`pages_manage_ads`, `pages_manage_metadata`, `pages_read_engagement`,
`ads_management`, `ads_read`, `business_management`, and `leads_retrieval`.
The runtime exchanged that user token for a distinct Page Access Token, and the
same Page token successfully read the Page's `leadgen_forms` edge. This proves
the current failure is not caused by using a user token for the POST or by a
missing requested permission. It is an app-level Meta capability/review
restriction. Do not switch to `stage_lead_form` merely because of this test;
use that fallback only after recording this exact Meta blocker and deciding
whether the configured Meta app should be replaced or have Lead Ads capability
enabled/reviewed.
