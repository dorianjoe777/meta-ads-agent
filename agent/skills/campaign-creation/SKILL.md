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

- A complete campaign/ad set/ad structure that will remain `PAUSED` may be created after the buyer asks for it; do not add a second approval ceremony for no-spend creation. The important approval is activation or another spend-capable live change.
- If the buyer wants the final ad active and able to spend, require explicit active-spend confirmation.
- Chat can stage a campaign but cannot silently approve it.
- If information is truly blocking, ask one clear question at a time.
- If the buyer asked to prepare/create and the remaining choice is safe, reversible, or can be staged paused for approval, proceed instead of asking a redundant permission question.
- Do not say campaign creation is blocked because you lack CLI or terminal access. In Telegram use the MCP tools; in dashboard chat use the JSON tool request contract. The product backend stages supported actions and keeps spend behind approval.
- Publicación directa is only for approved organic Facebook posts. Campaign creatives use the primary Live Ads app inline; an ads-authorized publishing credential may retry that same inline payload only after an explicit Development-mode error.
- If asked about setup tokens, explain the current one-token contract: use one Live Meta app/System User token with both Ads permissions (`ads_management`, `ads_read`) and Page permissions (`pages_manage_posts`, `pages_read_engagement`, `pages_show_list`, plus Page/ad-account access). Never ask the buyer to paste a second publishing token. Legacy separate publishing credentials may be used internally only as a fallback during migration.

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
- native creative strategy: use direct ad-account image/video upload plus an inline AdCreative for website, traffic, awareness, engagement, lead forms, WhatsApp, Messenger and Instagram Direct. Never create an automatic dark post. `object_story_id` is only for an existing post deliberately selected by the buyer.
- native lead-form strategy: design the questions in chat, then use `mcp_admira_create_lead_form` to create and verify the native Meta Instant Form through the connected Page. Reuse an exact existing form when available, pass the verified `lead_gen_form_id` into the paused campaign, and use the manual `mcp_admira_stage_lead_form` path only when Meta permissions prevent the direct form mutation.
- app-promotion strategy: require the real Meta `application_id` and exact App Store/Google Play `object_store_url`; use the native app objective/destination and inline creative instead of pretending it is ordinary website traffic.
- optional video completion strategy: normal video ads are supported natively. Use manual completion or paused named placeholders only when the buyer prefers Ads Manager preview/crop replacement or Meta rejects a genuinely unsupported asset. Never activate placeholders.
- budget/schedule strategy: daily vs lifetime budget, ad set budget, start/end time, active/paused status for campaign, ad set, and ad, and whether the budget can support the proposed number of concurrent variants.
- audience strategy: geo, age, interests, `custom_audiences`, exclusions, lookalikes/retargeting audiences when available, device/platform fields when they materially help, and placements.
- live interest discovery and confirmation: use `mcp_admira_search_meta_targeting` to resolve every proposed interest to a current Meta ID; for Advantage+ suggestions pass `targeting_mode: advantage_plus` with those structured selections. A successful create response alone never proves targeting applied. Use the backend verification result or `mcp_admira_inspect_adset_targeting` before saying the interests/Advantage+ suggestions are present.
- saved creative test brief with distinct hypotheses, formats, and variation count
- approved creative assets or a production plan
- final status: paused draft or active after approval

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

Use `mcp_admira_review_signal_quality` before `mcp_admira_stage_campaign`.
Use `mcp_admira_preflight_campaign` before `mcp_admira_stage_campaign` when the buyer is preparing a serious campaign, especially if it may launch active or uses advanced targeting, placements, video, custom audiences, or conversion optimization.
If the buyer provides a Google Drive/public URL for a video, image, landing page, or creative reference, call `mcp_admira_fetch_public_asset` before staging. For public videos, pass the returned `video_url`/`direct_url` as `video_url` when staging a video creative.
When enough details exist, call `mcp_admira_stage_campaign`.

When staging, pass the expert fields that are justified by the conversation:

- `optimization_event`, `pixel_id`, `optimization_goal`, `billing_event`, `promoted_object` context when known
- `success_metrics` or `key_results` as a ranked list of up to three campaign KPIs/results, for example `["ROAS", "cost per purchase", "cost per initiate checkout"]`
- `placements` with manual placement names or `{ "automatic": true }`
- `bidding`, `bid_strategy`, and `bid_amount` only when there is a clear reason
- `budget_level` as `"adset"` by default for controlled first tests/small budgets, or `"campaign"` when the strategy is CBO/Advantage campaign budget and Meta should distribute spend across multiple ad sets
- `daily_budget`, `campaign_daily_budget`, `adset_daily_budget`, `lifetime_budget`/`adset_lifetime_budget`, `target_cpa`/`target_cpl`, and `concurrent_creatives`
- `is_adset_budget_sharing_enabled` only when intentionally allowing ad set budget sharing; otherwise leave it omitted and the backend will send `false` for ad set budget mode
- `start_time`, `end_time`, `campaign_status`, `adset_status`, `ad_status`, and `final_status`
- `object_story_spec`, `image_hash`, `image_url`, `video_url`, `cta_link`, `creative_format`
- `message_destination` for WhatsApp/Messenger/Instagram Direct campaigns, plus `whatsapp_phone_number_id` when Meta exposes the numeric ID for the connected WhatsApp number. For WhatsApp, keep the optimization goal as Meta's Graph-valid `CONVERSATIONS` goal and include the Page/WhatsApp promoted object; never let a stale pixel/conversion goal override a messaging destination. Also collect `prefilled_message` when known, `welcome_message` and `quick_replies` for Messenger/Instagram when known, and `message_flow_id`/`ref_payload` only when the buyer has a connected messaging app or partner flow.
- `object_story_id` only when the buyer explicitly selected an existing Page post; omit it for normal native inline creatives
- `manual_creative_completion: true` for video website ads that should be finished in Ads Manager after the campaign/ad set is prepared
- `create_placeholder_ad: true`, `placeholder_ad_count`, and `placeholder_ad_names` when the buyer wants paused placeholder ads created to save setup clicks before replacing the media with final video. Use names from the actual concepts/angles discussed with the buyer.
- `custom_audiences`, `excluded_custom_audiences`, `excluded_interests`, `device_platforms`, `user_os`, `user_device`, and `flexible_spec` only when the buyer/context supports them
- `targeting_interests` as exact `{id, name}` objects returned by `mcp_admira_search_meta_targeting`; add `targeting_mode: "advantage_plus"` when the interests are suggestions rather than strict restrictions

Budgets are always interpreted in the connected Meta ad account currency. Do not assume USD. Accept buyer wording like `S/20`, `COP 40.000`, `MXN 300`, `€15`, or `$20`, and pass the numeric amount plus any known `account_currency`/`ad_account_currency` context. If the buyer mentions a different currency from the account currency, explain simply that Meta will use the ad account currency and do not invent currency conversion.

Do not expose auth, app-secret, gateway, hub/package, raw batch, or WhatsApp-send operations as campaign-creation controls.

Use `final_status: "ACTIVE"` only when the buyer clearly requested an active campaign and confirmed that it can spend.

## Reply

Say that the campaign was prepared for approval. Never say it is live unless the tool result confirms execution.
