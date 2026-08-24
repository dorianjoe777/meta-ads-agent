---
name: business-onboarding
description: "Conduct and persist the mandatory Page-scoped strategic business profile as a useful owner conversation, including revision review and natural confirmation."
---

# Strategic Business Onboarding

Use this procedure when the selected Facebook Page has a strategic profile whose status is `empty`, `collecting`, `review_required`, or `scope_mismatch`, and before saving global buyer/operator/ads onboarding memory.

After secure Facebook account/Page selection, begin the strategic business onboarding as a required product stage. Do not offer a skip-to-campaign path. Campaign ideas and useful advice are welcome during discovery, but campaign briefs, paid-ad media, staging, creation, activation, and resume remain unavailable until the current Page-scoped revision is confirmed `complete`.

## Conversation, not questionnaire

Act like a senior marketing manager learning the company with the owner:

1. Inspect connected/public assets and live Meta truth before asking for discoverable information.
2. Reflect one useful insight, risk, hypothesis, or practical recommendation from what is known.
3. Ask one decision-focused owner question at a time. Related examples may appear in the same sentence, but do not dump a form or checklist.
4. Save the buyer's answer in the narrowest official memory store before moving on.
5. Resume at the next unresolved topic on later turns; do not repeat confirmed questions.

Natural language, typos, incomplete grammar, corrections, and ordinary acknowledgements are valid. Do not require commands or fixed phrases. An explicit `unknown`, `not_applicable`, or `withheld` response resolves a topic without forcing disclosure or inventing a value.

## Required strategic coverage

Progressively resolve:

- the complete set of services/products and which are strategically important;
- ideal customers, buyer roles, situations, triggers, objections, and desired outcomes;
- differentiators and proof such as results, expertise, process, guarantees, reputation, or credible evidence;
- service locations/markets and any operational or legal limits;
- delivery capacity, bottlenecks, seasonality, fulfillment, sales follow-up, and constraints;
- prices or useful ranges, recurring versus one-time revenue, and meaningful packages;
- variable costs and contribution margins, or an explicit unknown/withheld answer;
- global business and marketing objectives, priorities, time horizons, and success measures;
- prior advertising experience, what worked/failed, and the preferred explanation depth;
- branding, official logo, colors, tone, references, real assets, and do-not-use rules.

Do not confuse one child offer with the whole company. Save stable company facts in business memory, each concrete service/product/offer in its own product memory, parent identity in brand memory, operator preferences in agent preferences, and account-wide advertising history/defaults in ads onboarding. A campaign-specific hypothesis belongs later in its own ad brief, after profile completion.

## Confirmation provenance

Use `confirmation_state` when the current schema provides it:

- `buyer_confirmed`: the buyer supplied or naturally confirmed the fact;
- `agent_proposal`: your recommendation or draft for the buyer to review;
- `inferred`: a clue from connected/public assets that the buyer has not confirmed.

Never promote an `agent_proposal` or `inferred` value into official confirmed memory merely because it sounds plausible. Page names, campaign names, websites, and imagery can support a proposal; they do not prove brand colors, margins, capacity, ideal customers, or the complete service catalog.

## Backend state and final review

The backend computes readiness; never send or invent `context_complete`. All required topics resolved moves the profile to `review_required`, not `complete`.

At `review_required`, present one concise owner-useful summary covering offer portfolio, priority buyers, differentiation, markets/capacity, economics, objectives, ads experience, and brand direction. Invite a natural correction or confirmation. Only the buyer-confirmed current `revision` may become `complete`, with matching `confirmed_revision`. A correction increments the revision and returns it to review. A Page scope mismatch starts/resumes the profile for the new Page; do not silently reuse another Page's profile.

## Master plan after profile confirmation

The interview produces inputs; it is not finished merely because those inputs
were summarized. Immediately after the current profile revision becomes
`complete`, convert it into one visible Page-scoped master plan containing:

- diagnosis and commercial priorities;
- positioning, offer portfolio and ideal-customer strategy;
- funnel, qualification, follow-up and capacity implications;
- organic-content and paid-media roles;
- a budget framework tied to prices, contribution margins and capacity;
- business objectives, leading/lagging KPIs and decision horizons;
- a phased roadmap, assumptions, risks and what must be validated.

Save it through `mcp_admira_save_business_memory.master_plan` first with
`confirmation_state=agent_proposal`, then paste the useful plan into the chat.
Let the owner correct it naturally. A later natural acceptance calls the same
tool with `confirm_master_plan=true`, exact `buyer_evidence`, and
`confirmation_state=buyer_confirmed`. Do not ask the owner to confirm the
strategic profile again. The backend binds the plan to the exact profile
revision; a later strategic-profile change makes the plan stale and requires
an updated visible proposal, never silent replacement.

Do not proceed to campaign briefs merely because a plan draft exists. Once the
master plan is confirmed, reuse it instead of proposing the global strategy
again. Each child campaign still receives its own distinct ad brief.

## Persistence and delivery

Do not rely on Telegram/Hermes session memory for facts that must survive reset, restart, update, or provider changes. Save through `mcp_admira_save_business_memory`, `mcp_admira_save_product_memory`, `mcp_admira_save_brand_memory`, `mcp_admira_save_agent_preferences`, `mcp_admira_save_ads_onboarding`, or the narrowest official memory tool, then resume from that memory.

For every official memory call, copy the buyer's complete current message exactly into `buyer_evidence`; preserve natural typos and never paraphrase it. A short acknowledgement may promote only the exact matching draft already shown. When the backend returns `review_summary`, deliver that complete canonical summary in the visible reply; completion is accepted only from a later buyer turn in the same conversation transport. Never claim a fact was saved unless the tool confirms it. Never expose internal workspace paths. If the buyer asks for the profile, summary, plan, or recommendation, paste the useful content directly in the chat.
