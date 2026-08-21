# Payload compiler chain — real Meta conversation canary — 2026-08-19

## Active order

1. `gemini-3.5-flash`
2. `gemini-3.6-flash`
3. `gpt-5.6-terra` through the connected Codex subscription

The conversational brain remains `gemini-3.5-flash-lite`; this chain is used
only inside destination campaign creation after Hermes submits one natural
Markdown brief. Provider/JSON/contract failures advance in order. A valid
ambiguity refusal is terminal. Only a candidate that passes deterministic
server validation can mutate Meta.

## Verification performed

- Compiler routing tests: 5/5 focused and 19/19 campaign-contract tests.
- Model-independent request routing and false-claim guards: 50/50 tests.
- No Docker build or image rebuild was used. Remote source and the live canary
  container were updated with identical files.

## Real simulated-Telegram cases

| Case | Requested | Graph result | Outcome |
|---|---|---|---|
| WhatsApp broad | Cartagena city, 25–55, all genders, no interests, automatic placements, 5 USD | city key `459425`, `daily_budget=500`, no manual placement lists, native WhatsApp | Passed; deleted |
| WhatsApp manual | Colombia, women 30–54, live interest, no Advantage+ Audience, Facebook Feed + Instagram Stories, 7 USD | interest `6014483580000`, genders `[2]`, `advantage_audience=0`, exact two positions, `daily_budget=700` | Passed after routing fix; deleted |
| Website omission probe | Bogotá + Barranquilla, men 35–60, explicit Advantage+ Audience, automatic placements, 9 USD | compiler initially omitted audience automation and Graph stored `advantage_audience=0` | Failed as intended; exposed and fixed the comparator gap; deleted |
| Advantage+ invalid ranges | same website case with 35–60 and then 35–65 | deterministic preflight rejected Meta-incompatible hard age bounds before mutation | Passed negative safety checks; no retained objects |
| Website valid Advantage+ | Bogotá + Barranquilla, 25–65, all genders, Advantage+ Audience, automatic placements, 9 USD | city keys `458130` and `457644`, `advantage_audience=1`, `OUTCOME_TRAFFIC`, `LANDING_PAGE_VIEWS`, `daily_budget=900` | Passed; deleted |

One website attempt defaulted to sales/offsite conversions and created only a
PAUSED campaign before Meta rejected the ad set for a missing promoted object.
The partial-cleanup guard immediately deleted campaign `120253689137040722`.
The server now defaults a website brief without an explicit conversion goal to
traffic/landing-page views.

## Product weaknesses fixed during the canary

1. Incidental ad-copy text such as `para mi empresa` no longer routes an
   explicit campaign request to onboarding.
2. A campaign success/ready claim without current creation-tool verification
   is rejected.
3. Explicit Advantage+ Audience/manual-audience decisions are compared against
   the candidate payload independently from placement automation.
4. A bare website destination uses traffic instead of silently requiring a
   Pixel for offsite conversions.
5. Provider and contract failures fall through 3.5 → 3.6 → Terra, while a
   valid missing/ambiguous-data refusal remains terminal.

## Cleanup evidence

Graph returned `configured_status=DELETED` and `effective_status=DELETED` for
all real or partial campaign IDs created in this run:

- `120253688996330722`
- `120253689048090722`
- `120253689073450722`
- `120253689137040722`
- `120253689168540722`

Meta also accepted deletion of the three allowlisted CANARY ad-creative IDs:
`2218380652337317`, `28339713062385737`, and `1635619288235056`. The original
buyer image file was reused and intentionally retained.

## Second real conversation matrix (R2, 2026-08-20 UTC)

This round used isolated simulated Telegram chat IDs and the real Hermes
`handle_text(..., send=False)` path. It did not invoke campaign MCPs directly.
All successful writes used the connected OAuth account and were checked again
through Graph. No Docker image was rebuilt and no container was restarted.

R2 produced nine real campaign objects: eight complete campaign/ad-set/ad
stacks and one partial campaign that the cleanup guard deleted immediately.
Four complete stacks passed every requested semantic check after fixes.

| Conversation | Result and Graph evidence | Classification |
|---|---|---|
| Website, two ads | 6 USD/day (`600`), women 28-50, Bucaramanga `458349` + Cali `479542`, manual Facebook Feed + Instagram Feed, two distinct ads and exact copy | Exact pass; deleted |
| WhatsApp | 8 USD/day (`800`), Pereira `476114` + Manizales `473594`, ages 25-65, Advantage+ Audience, automatic placements, native WhatsApp and exact starter | Exact pass; deleted |
| Messenger initial/retry | Router first matched the negated word WhatsApp. After routing fix two complete stacks still omitted `page_welcome_message` at different internal boundaries | Semantic failures; deleted |
| Messenger 3C | 5 USD/day (`500`), Colombia, ages 25-55, manual audience, automatic placements, native Messenger and exact welcome text in Graph `page_welcome_message` | Exact pass; deleted |
| Awareness first | 4 USD/day (`400`), Barranquilla `457644`, women, Advantage+ Audience, automatic placements; Graph lost the requested headline because native `photo_data` cannot store `title` | Semantic failure; deleted |
| Awareness 4B | Correct ambiguity question for incompatible Advantage+ ages; a later structured-location attempt created only a campaign before `geo_locations:{}` failed, then cleanup deleted it | Safe negative/partial-cleanup pass |
| Awareness 4C | 4 USD/day (`400`), Barranquilla `457644`, women 25-65, Advantage+ Audience; internal Page link preserved exact body and headline in `link_data` without an external CTA | Exact pass; deleted |
| Instagram Direct | Exact budget, Medellin `474037`, women 23-45, manual Instagram Feed + Stories and exact welcome text were initially accepted, but no professional `instagram_actor_id` was bound | Operational failure; remains PAUSED because Meta blocks deletion with `2534013` |

### R2 defects fixed

1. Destination routing now ignores natural negations such as "no WhatsApp"
   and checks Messenger/Instagram Direct before WhatsApp.
2. The simple one-ad campaign file now keeps `welcome_message`.
3. Graph welcome serialization now supports Messenger/Instagram briefs that
   contain a welcome message without a separate WhatsApp-style
   `prefilled_message`.
4. On-Meta image ads that need a headline use `link_data` pointing to the
   selected Facebook Page. Meta directly rejected `photo_data.title` with
   code `100`, subcode `1443050`; the Page link preserves the headline without
   inventing an external site or CTA.
5. Structured Meta locations are accepted under either `locations` or
   `targeting_locations`. Abbreviated `{id, name}` objects are enriched from
   the live Meta catalog with exact `type` and `country_code` before mutation.
6. Instagram Direct now blocks before the first Graph write unless a
   professional `instagram_actor_id` is bound. This prevents provisional
   stacks that Meta later refuses to update or delete.

### R2 cleanup state

The partial awareness campaign `120253689668830722` was automatically deleted.
Seven other retained R2 campaigns and eight allowlisted R2/probe creatives were
deleted after exact-name checks. The only remaining objects are:

- Campaign `120253689603270722` — `CANARY - R2 - Instagram Direct Medellin - 20260820-5`, confirmed `PAUSED`.
- Creative `1050271234405180`, still referenced by that campaign.

Meta rejects delete and `status=DELETED` for the campaign, ad set and ad with
code `100`, subcode `2534013` because the Page is not currently linked to a
professional Instagram account. It rejects deleting the creative with code
`200`, subcode `1487235` because the retained ad uses it. Remove this exact
campaign in Ads Manager after restoring a valid professional Instagram link;
do not broaden cleanup to other objects.

Final regression result after R2: 84/84 tests passed across campaign contracts,
model-independent routing/policy, and tool argument normalization.

## Complex multi-turn matrices (R3/R4, 2026-08-20 UTC)

These tests used ordinary Spanish across three real Hermes turns through
`telegram_agent.handle_text(..., send=False)`. The first two turns supplied the
brief in parts and explicitly deferred creation. The third turn confirmed the
complete brief. No campaign MCP was invoked before that confirmation, and no
Docker image was rebuilt or container restarted.

### R3 WhatsApp ABO 4x4

Campaign `120253690643800722` contained exactly four ad sets and sixteen ads,
with sixteen distinct creative objects. Each ad set had 4 USD/day, persisted by
Graph as `daily_budget="400"` in Meta minor units. The four branches covered
Cartagena `459425`, Pereira `476114`, Manizales `473594`, and Colombia; mixed
manual and Advantage+ Audience settings; and automatic, Facebook-only, and
Instagram-only placements. Graph matched every requested name, age/gender
constraint, copy, headline, WhatsApp starter, destination, and PAUSED state.

### R4 website CBO 4x4

Campaign `120253691602960722` contained exactly four ad sets and sixteen ads,
with sixteen distinct creative objects. Campaign-level CBO was 20 USD/day,
persisted as `daily_budget="2000"`; no ad set carried a budget. Branches used
Bogota `458130`, Medellin `474037`, Cali `479542`, and Barranquilla `457644`,
with mixed manual/Advantage audiences and automatic or exact manual
placements. All sixteen ads preserved distinct UTM URLs, body copy, and
headlines. Every campaign, ad set, and ad was PAUSED.

The two final verifiers returned respectively:

```json
{"ok":true,"campaign_id":"120253690643800722","counts":{"campaigns":1,"adsets":4,"ads":16,"unique_creatives":16},"failures":[]}
{"ok":true,"campaign_id":"120253691602960722","counts":{"campaigns":1,"adsets":4,"ads":16,"unique_creatives":16},"campaign_daily_budget_minor_units":"2000","failures":[]}
```

### Defects exposed and fixed by R3/R4

1. Structured city objects previously lost precedence to broader country
   values. Exact Meta IDs now remain authoritative through compilation,
   normalization, execution, and post-write verification.
2. Placement fragments such as `[facebook, feed, story]` are expanded into
   canonical platform positions instead of silently becoming the default
   Facebook+Instagram placement set.
3. A structured location without `type` can no longer degrade to a broad
   country. It must be enriched by exact live-ID match or rejected so the next
   compiler can try.
4. Explicit Meta IDs present in the buyer brief must survive compilation.
   Dropping one rejects that compiler candidate before any Graph mutation.
5. The last three buyer messages are appended verbatim to the compiler brief.
   This keeps exact locations, placements, copy, URLs, and per-branch details
   when the conversational model's summary is shorter than the source.
6. Facebook Video Feeds was accepted by an old placement contract but Meta v25
   rejects it with subcode `2490562`. It is now in
   `DEPRECATED_MANUAL_PLACEMENTS` and fails preflight before the first write.
7. The direct Python simulated-Telegram route now applies the same
   `_guard_unconfirmed_campaign_claim` as the gateway. Hermes cannot say a
   campaign was created when the destination tool failed or its provisional
   objects were cleaned up.

### Cleanup and retained exception

All eight complete/failed R3/R4 campaign objects that still existed after the
run were deleted by exact ID; the one partial R4 campaign had already been
auto-cleaned. The two failed generated-image directories
`codex-20260820-020552` and `codex-20260820-021322` were removed explicitly.
The known-good source creative under `codex-20260819-221535` was retained.

Meta retained 48 historical creative objects after campaign deletion and
returned code `200`, subcode `1487235`: an ad message cannot be deleted while
Meta still considers an ad-group reference. Direct audit found no references
from non-canary campaigns. These objects cannot spend and must not be retried
with broad cleanup. The audit is stored at
`/tmp/r3-r4-creative-cleanup-report.json` on the canary host.

R2 Instagram Direct campaign `120253689603270722` was explicitly excluded and
rechecked after cleanup; it remains PAUSED with its original ad set, ad, and
creative.

Final regression result after R3/R4: 93/93 tests passed across campaign
contracts, model-independent provider/routing policy, and tool argument
normalization.
