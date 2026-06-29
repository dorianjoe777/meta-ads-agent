# Future Initiative: Cloud API, CLI, and MCP Platform

This document captures a later-stage product direction. It is not part of the current local/self-hosted v1 promise.

The current product is a buyer-installed Meta Ads agent with local/VPS dashboard, Telegram/Hermes conversation, protected product tools, and buyer-owned Meta connection. A future cloud company version should expose Admira's value as an integration platform so CRMs, booking tools, ecommerce platforms, WhatsApp inboxes, automation tools, and external agents can connect to the verified-signal workflow.

## Why This Matters

The long-term differentiator is not only creating ads. It is helping businesses convert messy marketing activity into verified business-quality signals:

- which leads were real;
- which conversations became qualified;
- which prospects booked;
- which appointments showed up;
- which people purchased;
- which customers were high value;
- which ads/creatives attracted noise instead of buyers.

If Admira becomes a cloud platform with its own API, CLI, and MCP server, other tools can push and pull those signals instead of forcing users to manually copy data between WhatsApp, CRM, booking calendars, ecommerce, and Ads Manager.

The future positioning:

> Admira trains ad decisions with verified customer-quality signals, and exposes that intelligence through API/MCP so the rest of the business stack can use it.

## Product Boundary

Do not promise this in v1 local buyer docs as already available.

This initiative belongs to a later product launch after:

- a cloud-hosted Admira backend exists;
- the Meta app is approved for the required permissions and use cases;
- privacy, consent, retention, audit, and deletion workflows are ready;
- business messaging and/or CRM integrations are properly reviewed;
- rate limits, tenancy, billing, and support obligations are understood.

## Platform Surfaces

### 1. Public REST API

The cloud product should expose a versioned HTTPS API for business systems and integration partners.

Potential resources:

- `/v1/events`
- `/v1/leads`
- `/v1/conversations`
- `/v1/outcomes`
- `/v1/campaign-quality`
- `/v1/creative-quality`
- `/v1/audiences`
- `/v1/recommendations`
- `/v1/webhooks`

Example uses:

- CRM sends a lead stage update: `qualified`, `booked`, `showed`, `won`, `lost`.
- Booking tool sends appointment status.
- Ecommerce platform sends purchase and customer value.
- WhatsApp inbox sends click-to-WhatsApp referral metadata such as `ctwa_clid`.
- Admira returns quality summaries by campaign/ad/creative.
- Admira returns recommended next actions for the account.

### 2. Webhooks

Admira should both receive and emit webhooks.

Inbound:

- new lead;
- new message/conversation;
- stage changed in CRM;
- booking created/cancelled/showed/no-show;
- purchase/refund;
- human quality confirmation.

Outbound:

- agent recommendation created;
- campaign quality changed;
- creative marked noisy/high quality;
- verified outcome ready to send to Meta;
- follow-up due;
- event match quality or deduplication issue detected.

### 3. CLI

A CLI makes Admira usable in operations, support, debugging, and customer migration flows.

Possible commands:

```bash
admira events import leads.csv
admira events send --source crm --event Lead --email buyer@example.com
admira events dedupe --since 7d
admira leads list --status qualified
admira outcomes confirm --lead-id lead_123 --stage booked
admira meta send-verified-events --dry-run
admira quality report --campaign-id 123
admira recommendations list
```

The CLI should use the same API and safety rules as the cloud dashboard. It should never bypass account permissions, audit logs, privacy controls, or Meta send validation.

### 4. MCP Server for External Agents

Admira should expose an official MCP server so other AI agents and automation environments can safely interact with the verified-signal system.

Potential MCP tools:

- `admira_get_campaign_quality`
- `admira_get_lead_quality_summary`
- `admira_submit_verified_event`
- `admira_confirm_lead_stage`
- `admira_list_open_followups`
- `admira_get_recommendations`
- `admira_create_webhook_subscription`
- `admira_run_signal_diagnostics`

The MCP server should be read-first and approval-aware. Mutating tools must follow the same safety model as the dashboard:

- scoped tenant identity;
- explicit permissions;
- audit log;
- dry-run where possible;
- approval required for risky Meta/account actions;
- PII redaction in tool outputs;
- no raw token exposure.

## Verified Signal Ledger

The cloud API should be built around a durable event ledger.

The ledger must be automatic-first. Admira should ingest, parse, map, deduplicate, and score all available leads/messages/bookings/purchases by itself before asking the buyer anything. The buyer should not be asked to classify every lead one by one unless volume is low and that is genuinely useful.

Each record should support:

- tenant/business ID;
- source system;
- source event ID;
- source object type: lead, message, booking, order, contact, ad event;
- Meta campaign/ad set/ad IDs when known;
- creative ID/hash when known;
- event name;
- event stage;
- event timestamp;
- customer identifiers, stored safely;
- raw identifiers needed for matching, when allowed;
- hashed identifiers for Meta sends;
- deduplication key;
- human confirmation status;
- confidence score;
- send-to-Meta status;
- error/retry history;
- deletion/retention metadata.

The ledger lets Admira answer the business question:

> Which ads created real business outcomes, not just cheap platform actions?

## Human Feedback UX: Exceptions and Important Outcomes Only

The daily feedback loop should not become homework. The product should assume the agent does the operational work and the human only supplies the truth that the software cannot know.

Default daily prompt:

> I organized yesterday's new leads/messages automatically. Please mark only the exceptions: people who were fake, confused, not really interested, wrong audience, or people who moved to an important stage like booked, showed up, purchased, or high value.

The buyer's job should be reduced to:

- flag bad/uninterested/fake/wrong-audience leads;
- mark meaningful outcomes: booked, showed, purchased, high value;
- optionally mention stage changes from previous days.

Admira's job:

- map each person/event to campaign, ad set, ad, creative, and source when possible;
- deduplicate repeated messages/leads/orders/bookings;
- choose the best Meta event/stage to send when allowed;
- decide whether event volume is enough for optimization or only reporting;
- calculate real lead quality, cost per qualified lead, cost per booking, and cost per purchase;
- identify which creative/audience/source creates real buyers versus noise;
- recommend what to pause, scale, rewrite, retarget, or rebuild.

Feedback mode should adapt to volume:

- Low volume: lead-by-lead review is acceptable.
- Medium volume: exception review plus important outcomes.
- High volume: prefer structured outcome reporting for the most important events, ideally person-level or CRM-level if the business has a sales manager, receptionist, booking team, CRM, spreadsheet, or inbox process. Aggregate outcome summaries are a fallback, not the ideal.

Unreviewed leads should be treated as "assumed normal / unverified", not as high-confidence qualified leads. Human-confirmed outcomes should carry higher confidence and drive reporting, recommendations, and any supported Meta feedback sends.

The loop should also ask about delayed movement:

> Did any lead from previous days move forward today?

This captures the reality that message campaigns often convert days after first contact.

For higher-volume businesses, the best daily workflow may be a sales-manager report rather than a business-owner tap flow:

> Send today's booked/showed/purchased/high-value outcomes with names, phone/email/order/booking ID when available, source if known, and notes about bad-quality patterns.

Admira should accept multiple input formats:

- quick text: `Today: 14 booked, 9 showed, 4 purchased`;
- named list: `Maria booked, Carlos purchased, Ana no-show`;
- CSV/spreadsheet import;
- CRM/booking/ecommerce integration;
- WhatsApp/inbox export;
- structured API/webhook event.

The highest-value events should be enriched as much as possible because they are the most important signals for future and ongoing improvement:

- name/contact identifier when allowed;
- phone/email hash or source contact ID;
- booking/order/CRM ID;
- campaign/ad/adset/creative source when known;
- event timestamp;
- value/currency when there is revenue;
- outcome stage and quality notes.

If the business can provide person-level outcomes, Admira should use them. If it cannot, aggregate totals still improve reporting and decisions, but they should be labeled lower confidence and not treated as fully matched Meta feedback events unless they can be reconciled.

## Event Matching and Deduplication Responsibilities

Admira should help improve match quality by organizing and validating data, not by making unverifiable claims.

The system can:

- capture and preserve `fbp`, `fbc`, `fbclid`, and `ctwa_clid` when available;
- store Meta Lead IDs for instant forms;
- normalize phone/email before hashing;
- generate stable `event_id` values;
- prevent duplicate sends;
- distinguish lifecycle events from duplicates;
- reconcile CRM/booking/ecommerce records with ad source data;
- report missing identifiers and weak match quality;
- recommend setup improvements when data is too weak.

The user or connected systems still need to provide the source data:

- website forms must collect identifiers with consent;
- ecommerce/booking tools must expose order/booking/contact data;
- WhatsApp feedback loop needs WhatsApp Business Platform/Cloud API or a provider that exposes ad referral metadata;
- privacy policy and consent language must cover the data use.

## Privacy Notice and Consent Requirement

Any feature that stores customer identifiers locally or sends customer/event identifiers to Meta needs a clear privacy/compliance checkpoint.

The product and agent should tell the business owner, in plain language:

> To use verified-signal optimization, you may need to update your privacy policy or customer notice to explain that you use Meta advertising tools and may share hashed customer information and event data with Meta for measurement, reporting, audience creation, and ad optimization. Confirm this with your legal/privacy advisor for your country and business.

This requirement is not limited to website campaigns. It can also apply to message-only or Click-to-WhatsApp campaigns if Admira:

- captures phone/contact identifiers from conversations;
- stores message/conversation lifecycle data;
- captures ad referral metadata such as `ctwa_clid`;
- sends qualified lead, booking, purchase, or other conversation outcomes back to Meta;
- builds retargeting, lookalike, or exclusion audiences from customer/message data.

Hashing helps protect identifiers such as email and phone, but hashed identifiers can still be treated as personal data under many privacy laws because they are used for matching. The platform should avoid saying "anonymous" unless data is truly anonymized and no longer matchable.

Implementation safeguards:

- collect only the identifiers needed for matching and reporting;
- normalize and hash contact fields before sending to Meta when Meta requires hashing;
- do not hash fields Meta expects raw, such as click IDs when applicable;
- keep raw PII out of logs, prompts, URLs, and MCP/tool outputs;
- provide retention controls and deletion/export paths;
- record the buyer's confirmation before enabling Meta sends;
- keep a dry-run mode that reports what would be sent without sending it.

## Meta App Approval Dependency

A serious cloud version will require Meta app review and stable permissions. Until that exists, the product must not imply official platform-level access.

Likely areas to evaluate:

- Marketing API permissions for ads management and insights;
- Lead Ads retrieval;
- business asset/page permissions;
- WhatsApp Business Platform / Cloud API webhooks;
- Conversions API / datasets;
- business messaging Conversions API;
- offline/CRM conversion events;
- data deletion callbacks and privacy compliance.

## Development Phases

### Phase 1: Internal Ledger in Local Product

- Build local verified-signal ledger.
- Add daily Telegram feedback loop.
- Support manual quality confirmation and delayed stage changes.
- Produce real quality reporting and agent recommendations.
- Do not expose public API yet.

### Phase 2: Cloud Ledger and Private API

- Move ledger to a multi-tenant cloud backend.
- Add authentication, tenant isolation, audit logs, retention settings, and deletion flow.
- Add private API used only by Admira dashboard/agents.
- Start with a few integrations: Shopify, booking CSV/API, Lead Ads, WhatsApp Cloud API.

### Phase 3: Partner API and CLI

- Publish versioned API documentation.
- Add API keys/OAuth, webhook subscriptions, rate limits, SDK examples, and CLI.
- Build import/export tools for agencies and customers.
- Support external CRM and automation workflows.

### Phase 4: Official MCP Platform

- Publish an MCP server for external agents.
- Expose read-first quality intelligence and approval-aware mutation tools.
- Allow partner agents to use Admira's signal diagnostics and quality ledger without accessing raw buyer secrets.

## Future Dashboard CRM Area

The cloud product should eventually include a CRM-style area inside the dashboard. This is a future product surface, not the first local ledger slice.

Goal:

> Make Admira a one-stop shop for service-business owners: ads, lead quality, follow-up stages, booked/showed/purchased outcomes, creative decisions, and Meta feedback signals in one place.

Possible UI:

- CRM/Kanban board with stages such as New, Qualified, Still Talking, Booked, Showed, Purchased, High Value, Lost, No-Show, Bad Fit.
- Person/contact cards that can be moved between stages.
- Quick stage buttons on each card.
- Daily "exceptions and important outcomes" inbox.
- Sales-manager view for uploading or entering booked/showed/purchased/high-value outcomes.
- CSV/spreadsheet import for daily outcome reports.
- Filters by campaign, ad set, ad, creative, source, date, and stage.
- Quality score by creative/audience/campaign.
- Warnings when a stage lacks match identifiers or privacy confirmation.
- Suggested next actions: follow up, retarget, exclude, scale, pause, rewrite creative, or change campaign structure.

Important design principle:

- The CRM UI should help humans update only what the agent cannot know.
- It should not become another manual CRM burden.
- Automatic ingestion and deduplication should happen first; human interaction should focus on exceptions, high-value outcomes, and sales-stage corrections.

## Non-Goals for the Current Product

- Do not present the local v1 as a public integration platform.
- Do not promise third-party CRM compatibility before integrations exist.
- Do not claim Meta optimization from verified events until Meta accepts the events and the account has enough volume.
- Do not expose raw PII, tokens, or buyer Meta credentials through any API/MCP surface.
- Do not let external tools mutate Meta accounts without the same approval/safety layer.

## Strategic Note

This initiative is important for turning the product from an installable info-product/tool into a real SaaS/platform company.

The local product proves the workflow:

ads agent → daily feedback → verified outcomes → better decisions.

The cloud/API/MCP product turns that workflow into infrastructure:

CRM/WhatsApp/booking/ecommerce → Admira verified signal ledger → Meta feedback + agent decisions + external integrations.
