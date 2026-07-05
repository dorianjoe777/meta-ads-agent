# Campaign Creation Skill

Use this skill when the buyer asks to create, launch, prepare, or publish a Meta Ads campaign, ad set, creative, or ad.

## Safety Rules

- New campaigns always require approval.
- If the buyer wants the final ad active and able to spend, require explicit active-spend confirmation.
- Chat can stage a campaign but cannot silently approve it.
- If information is missing, ask one clear question at a time.
- Do not say campaign creation is blocked because you lack CLI or terminal access. In Telegram use the MCP tools; in dashboard chat use the JSON tool request contract. The product backend stages supported actions and keeps spend behind approval.

## Minimum Details

Collect:

- product or offer
- objective
- target audience/location
- daily budget
- target CPA/CPL when known
- landing URL
- correct optimization event or enough context to choose it
- Pixel/Dataset ID for web conversion events when available
- whether Conversions API, Event Match Quality, AEM/event eligibility, event prioritization, and recent weekly event volume are known
- placement strategy. Use expert judgment instead of a rigid default: choose controlled Facebook/Instagram feeds and stories when they fit, add Reels/Explore/other placements when the creative format, audience behavior, offer, and budget justify them, or use automatic/Advantage+ placements when that is strategically stronger.
- creative object strategy: local image, image hash, image URL, video URL, or full `object_story_spec`; CTA and optional CTA link override; Page ID and Instagram actor should come from saved setup when available.
- budget/schedule strategy: daily vs lifetime budget, ad set budget, start/end time, active/paused status for campaign, ad set, and ad, and whether the budget can support the proposed number of concurrent variants.
- audience strategy: geo, age, interests, custom audiences, exclusions, lookalikes/retargeting audiences when available, device/platform fields when they materially help, and placements.
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
When enough details exist, call `mcp_admira_stage_campaign`.

When staging, pass the expert fields that are justified by the conversation:

- `optimization_event`, `pixel_id`, `optimization_goal`, `billing_event`, `promoted_object` context when known
- `placements` with manual placement names or `{ "automatic": true }`
- `bidding`, `bid_strategy`, and `bid_amount` only when there is a clear reason
- `daily_budget`, `adset_daily_budget`, `lifetime_budget`/`adset_lifetime_budget`, `target_cpa`/`target_cpl`, and `concurrent_creatives`
- `start_time`, `end_time`, `campaign_status`, `adset_status`, `ad_status`, and `final_status`
- `object_story_spec`, `image_hash`, `image_url`, `video_url`, `cta_link`, `creative_format`
- `custom_audiences`, `excluded_custom_audiences`, `excluded_interests`, `device_platforms`, `user_os`, `user_device`, and `flexible_spec` only when the buyer/context supports them

Do not expose auth, app-secret, gateway, hub/package, raw batch, or WhatsApp-send operations as campaign-creation controls.

Use `final_status: "ACTIVE"` only when the buyer clearly requested an active campaign and confirmed that it can spend.

## Reply

Say that the campaign was prepared for approval. Never say it is live unless the tool result confirms execution.
