---
name: campaign-creation
description: "Compatibility shim that routes legacy campaign-creation requests to the current campaign strategy and Meta execution skills."
---

# Campaign Creation Skill

## Compatibility shim

This legacy skill remains for compatibility. Before using it, read:

- `skills/core-agent-behavior/SKILL.md`
- `skills/session-continuity/SKILL.md`
- `skills/campaign-strategy/SKILL.md`
- `skills/meta-campaign-execution/SKILL.md`
- `skills/measurement-optimization/SKILL.md` when the campaign depends on real performance, events, feedback, or follow-up decisions

Use this skill when the buyer asks to create, launch, prepare, or publish a Meta Ads campaign, ad set, creative, or ad.

## Safety Rules

- A complete campaign/ad set/ad structure that will remain `PAUSED` may be created after the buyer asks for it, but only after the current campaign's exact budget/currency, creative, primary text, title, and destination-specific message/form/URL have been shown and resolved. A campaign request is not approval for values invented by the agent or copied from another campaign. Once those inputs are explicitly accepted, do not add a redundant second approval ceremony merely because the structure is PAUSED; activation or another spend-capable live change still needs its own approval.
- If the buyer wants the final ad active and able to spend, require explicit active-spend confirmation.
- Chat can stage a campaign but cannot silently approve it.
- If information is truly blocking, ask one clear question at a time.
- If the buyer asked to prepare/create and the remaining choice is safe, reversible, or can be staged paused for approval, proceed instead of asking a redundant permission question.
- Do not say campaign creation is blocked because you lack CLI or terminal access. In Telegram use the MCP tools; in dashboard chat use the JSON tool request contract. The product backend stages supported actions and keeps spend behind approval.
- Publicación directa is only for approved organic Facebook posts. Campaign creatives use the primary Live Ads app inline; an ads-authorized publishing credential may retry that same inline payload only after an explicit Development-mode error.
- For new installs, never ask the buyer to create a System User, generate a token, or paste a Meta key. Admira sends a secure Facebook OAuth link to the buyer's connected Telegram. After they connect, show the discovered ad accounts and Pages, recommend the most likely business match when context makes it clear, and ask which one should be active. Store all discovered assets for later switching, but create/manage campaigns only in one explicitly active account/Page at a time. Existing token connections remain a migration fallback only.

## Minimum Details

Collect:

- product or offer
- objective
- the three most important success metrics/results in priority order. Ask simply: “What are the 3 results that matter most for judging this campaign?” Examples: ROAS, cost per purchase, cost per initiate checkout, cost per qualified lead, booked appointments, or cost per real WhatsApp conversation.
- target audience/location
- daily budget
- target CPA/CPL when known
- landing URL
- correct optimization event or enough context to choose it
- Pixel/Dataset ID for web conversion events when available
- whether Conversions API, Event Match Quality, AEM/event eligibility, event prioritization, and recent weekly event volume are known
- placement strategy. Use expert judgment instead of a rigid default: choose controlled Facebook/Instagram feeds and stories when they fit, add Reels/Explore/other placements when the creative format, audience behavior, offer, and budget justify them, or use automatic/Advantage+ placements when that is strategically stronger.
- creative object strategy: local image, image hash, image URL, video URL, or full `object_story_spec`; CTA and optional CTA link override; Page ID and Instagram actor should come from saved setup when available.
- Image 2 generated creative handoff: use the returned durable `asset_id` as `creative_asset_id`. It is deliberately not a public URL; the backend resolves the protected local asset, uploads it to the ad account, and creates the inline AdCreative. Never ask the buyer to host it or pass dashboard preview URLs to Meta.
- message-ad conversation starter when the destination is WhatsApp, Messenger, or Instagram Direct. Ask the buyer what first message/welcome text should appear, or proactively propose 2-3 options if they are unsure. For WhatsApp, prefer a buyer-sent `prefilled_message` such as “Hola, quiero más información sobre [oferta]”; for Messenger/Instagram, define a `welcome_message`, useful `quick_replies`, and a `message_flow_id` only when a connected messaging partner/app supports it. Never claim Admira can send an unsolicited first WhatsApp/Messenger message from an ad; the user must click/tap or the approved Meta welcome/flow must show it.
- For WhatsApp, decide the creative before campaign creation: ask once whether to create a new creative, reuse one from the three-day library, or use a buyer upload. Finish and show the exact asset first. Pass `creative_decision` and set `creative_approved: true` only after the buyer has selected/approved that final asset. Show the exact `prefilled_message` and set `prefilled_message_approved: true` only after the buyer approves it. Never invent either approval.
- native creative strategy: use direct ad-account image/video upload plus an inline AdCreative for website, traffic, awareness, engagement, lead forms, WhatsApp, Messenger and Instagram Direct. Never create an automatic dark post. `object_story_id` is only for an existing post deliberately selected by the buyer.
- native lead-form strategy: design the questions in chat, then guide the buyer to create and publish the Instant Form once in Meta Ads Manager. Meta's API capability for form creation is currently unreliable even when permissions look correct, so do not promise a direct creation or retry it. Reuse an exact existing form when available; otherwise use `mcp_admira_stage_lead_form`, then list forms and persist the verified `lead_gen_form_id` before creating the paused campaign.
- app-promotion strategy: require the real Meta `application_id` and exact App Store/Google Play `object_store_url`; use the native app objective/destination and inline creative instead of pretending it is ordinary website traffic.
- optional video completion strategy: normal video ads are supported natively. Use manual completion or paused named placeholders only when the buyer prefers Ads Manager preview/crop replacement or Meta rejects a genuinely unsupported asset. Never activate placeholders.
- budget/schedule strategy: daily vs lifetime budget, ad set budget, start/end time, active/paused status for campaign, ad set, and ad, and whether the budget can support the proposed number of concurrent variants.
- audience strategy: geo, age, interests, `custom_audiences`, exclusions, lookalikes/retargeting audiences when available, device/platform fields when they materially help, and placements.
- live interest discovery and confirmation: use `mcp_admira_search_meta_targeting` to resolve every proposed interest to a current Meta ID; for Advantage+ suggestions pass `targeting_mode: advantage_plus` with those structured selections. A successful create response alone never proves targeting applied. Use the backend verification result or `mcp_admira_inspect_adset_targeting` before saying the interests/Advantage+ suggestions are present.
- saved creative test brief with distinct hypotheses, formats, and variation count
- approved creative assets or a production plan
- ad copy package for every ad: the exact copy principal/texto del anuncio, a distinct title/título del anuncio, the CTA, and any destination-specific opening message. The campaign name and ad-set name are internal labels, not ad copy.
- final status: paused draft or active after approval

### Required ad copy conversation

Every new inline ad needs its own sales message, not only an image. Before the
destination MCP is called, act as the client's marketing manager: draft the
copy principal and a separate title from the active offer, audience, proof,
objection, and destination. Recommend the strongest version and show the exact
wording in the chat. Ask the buyer to approve it, edit it, or provide their own
wording; natural agreement is enough and no magic approval phrase is required.
If you use Hermes' native clarification/choice UI for that review, the visible
question must repeat the exact copy principal, distinct title, CTA and
destination opener/message. Never show a generic “approve this copy and create”
button while the wording is hidden in the model's context; emit the readable
proposal first, deliver the actual creative, and let the buyer correct or
approve the package together in natural language. Buttons are only a convenient
way to answer an already-visible proposal, not a substitute for the review.

- Never copy the campaign name or ad-set name into the title merely because a
  title is missing. The title should sell the benefit, promise, proof, or
  next step; an internal name should identify the test.
- Keep copy, title, CTA, and destination message associated with the correct
  ad variant. Do not reuse one ad's wording across different offers or
  hypotheses without a strategic reason.
- Do not confuse text embedded inside an image with the ad's copy principal or
  title fields. Confirm both layers separately when the ad uses image text.
- For an existing Page post deliberately selected as the creative, inspect and
  explain the post's current wording; do not silently replace it or pretend its
  campaign name is a headline.

### Final compiler brief before staging

Before calling the matching destination MCP, write one complete
`brief_markdown` in natural language from the latest buyer-approved campaign.
Include every ad set/ad, destination, exact amount and currency, geography,
age/gender, automatic or manual placements, approved asset reference, copy,
CTA, and WhatsApp/welcome/form/app/website detail that applies. Copy live Meta
location/interest objects into the Markdown when they were searched. Do not
assemble a nested JSON payload: the backend sends this Markdown to Terra, and
Terra compiles the candidate payload against the destination contract.

The Markdown must carry the copy principal and title separately for every new
ad (including every ad in a multi-ad-set brief). When the destination contract
uses the technical fields `primary_text` and `headline`, map the agreed wording
to those fields without changing its meaning. Never ask Terra to invent the
wording or silently reuse an internal campaign label as the title.

If a real buyer decision is missing, ask for it before calling the tool. Never
fill a Markdown gap with generic copy, all genders, US, manual feed/story
placements, a different destination, or a newly generated creative.

For click-to-WhatsApp campaigns, distinguish the business goal from Meta's
current enum: Meta normally displays the campaign outcome as Engagement while
the ad set uses Conversations. Explain this when relevant, but never silently
change a requested website-sales campaign into an engagement campaign.

Do not reduce the creative strategy to one image. Check that the proposed concurrent creative count fits the budget; keep additional concepts in a backlog rather than starving every test.

Before staging a conversion, lead, message, or website-action campaign, call `mcp_admira_review_signal_quality`. Use its recommended event and warnings in the campaign proposal. If it says signal setup is weak, still allow a paused draft, but do not present active launch as low-risk until the buyer understands the warning.

## Expert Configuration Posture

Act like the best ads advisor and configurator the buyer could have: assume the buyer may not know which Meta settings matter, but you do. This applies globally to every available configuration/tool, not only placements. Be proactive when a configuration can materially improve results, save time, protect budget, or avoid poor learning. Do not wait for the buyer to ask about every setting.

For every campaign proposal, actively evaluate:

- offer and conversion intent: direct purchase, lead, message, booking, local visit, awareness, or retargeting
- buyer sophistication and audience behavior: cold, warm, visual discovery, high-intent, impulse, or research-heavy
- creative format and asset quality: square/feed image, vertical video, UGC, carousel, proof/testimonial, product demo, native post, or motion graphic
- budget and evidence needs: enough budget for placement spread, or narrower delivery to avoid starving the test
- measurement fit: optimization event, Pixel/Dataset, promoted object, signal quality, and conversion volume
- decision scorecard: the primary metric plus two supporting metrics so daily briefings and optimization do not judge the campaign from only one number
- message experience: for click-to-message campaigns, the first conversation text is part of the ad experience. It should match the offer, reduce friction, and qualify intent. If the buyer has no wording ready, propose concise options like: “Hola, quiero más información”, “Hola, ¿hay disponibilidad para esta semana?”, or “Hola, quiero reservar la oferta de [producto]”.
- preflight readiness: account status, policy/rate-limit checks, available custom audiences, existing creatives, recent placement/device/ad/adset insight availability, and dry-run payload preview

## Placement Strategy

Never treat placements as a static checkbox list. Decide them from the ad itself:

- Standard static image or simple offer: usually start with Facebook Feed, Instagram Feed, Facebook Stories, and Instagram Stories.
- Vertical UGC, creator-style, demo, before/after, food, beauty, fitness, local experience, or emotion-led video: strongly consider Instagram Reels, Facebook Reels, and Stories if the asset is built for vertical delivery.
- Discovery products, visual lifestyle offers, fashion, food, beauty, travel, and local venues: consider Instagram Explore/Reels when the creative is native enough.
- B2B, high-ticket, detailed proof, or research-heavy offers: prioritize feed placements where copy and proof can be consumed; use Reels only if the hook can explain quickly.
- Retargeting and warm audiences: keep placements tighter if budget is small; expand only when frequency or delivery becomes constrained.
- Very small budgets or low conversion volume: avoid spreading the test across too many placements unless using automatic placements for a clear reason.

If using manual placements, keep creative dimensions/copy compatible with the chosen placements and tell the buyer which placements are being used and why. If a valuable placement needs a different creative format, propose that proactively: for example, “This should also have a vertical Reels version; I can prepare that as variant 2.”

When automatic/Advantage+ placements are better, say why. When manual placements are better, say what is intentionally excluded and why. The goal is not to use every placement; the goal is to give Meta good learning opportunities without wasting budget on placements that do not fit the ad.

## Tool

Use `mcp_admira_review_signal_quality` before the destination campaign tool.
Use `mcp_admira_preflight_campaign` before the destination campaign tool when the buyer is preparing a serious campaign, especially if it may launch active or uses advanced targeting, placements, video, custom audiences, or conversion optimization.
If the buyer provides a Google Drive/public URL for a video, image, landing page, or creative reference, call `mcp_admira_fetch_public_asset` before staging. For public videos, pass the returned `video_url`/`direct_url` as `video_url` when staging a video creative.
When enough details exist, call exactly one matching tool: `mcp_admira_create_whatsapp_campaign`, `mcp_admira_create_lead_form_campaign`, `mcp_admira_create_website_campaign`, `mcp_admira_create_messaging_campaign`, `mcp_admira_create_app_campaign`, or `mcp_admira_create_on_meta_campaign`. Never call the legacy broad `stage_campaign` tool and never convert one destination into another to satisfy missing fields.

Every destination call sends exactly one argument: `brief_markdown`. The
Markdown must state all expert fields justified by the conversation, including
optimization/budget level, schedules, success metrics, audience exclusions,
exact live targeting results, destination fields, creative source and all ad
variants. Preserve the buyer's budget phrase exactly and explicitly say whether
placements are automatic Advantage+ or list the exact manual placements.

Terra compilation is not approval and cannot spend. The server reparses the
compiled amount against the connected account currency, resolves/validates
targeting live, verifies the creative, forces the complete stack to `PAUSED`,
and rereads Meta. If Terra reports missing fields or fails, preserve the latest
Markdown and ask only for the actual missing buyer decision; never construct a
fallback payload in the conversational model.

When the buyer refers naturally to a generated creative from today, yesterday, or a named recent day, use `mcp_admira_list_recent_creatives` and present the matching images by description/date rather than asking for IDs. The automatic recovery window is three days. For older creatives, ask the buyer to resend the saved image from their gallery; do not promise a permanent archive.

Do not expose auth, app-secret, gateway, hub/package, raw batch, or WhatsApp-send operations as campaign-creation controls.

Use `final_status: "ACTIVE"` only when the buyer clearly requested an active campaign and confirmed that it can spend.

## Reply

Say it was created PAUSED only when the tool returns `campaign_creation_verified: true` with real campaign, ad-set, and ad IDs. A blocker means nothing was created; report the exact missing detail/error and do not call it prepared, configured, staged, or paused. Never ask for another approval to create PAUSED. Activation/spend remains separately protected.
