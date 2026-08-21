# Payload compiler model benchmark — 2026-08-19

## Scope and safety

This benchmark ran on the DigitalOcean canary only. It used the same campaign
compiler contract and strict wrapper schema as production, but it did not call
Meta, create campaigns, alter the active compiler order, or rebuild Docker.
The configured Google AI Studio key listed all three tested model IDs with
`generateContent` support:

- `gemini-3.5-flash`
- `gemini-3.6-flash`
- `gemini-3.7-flash`

Four common briefs were used: exact WhatsApp, website with two distinct ads,
exact native lead form, and an intentionally ambiguous WhatsApp request that
must return `ready=false` and an empty payload. A fifth production-shaped
Hermes Markdown brief quoted exact strings. Gemini 3.5 also repeated the
two-ad case twice to check semantic consistency. Terra ran the original four
cases in an isolated temp directory so operational latest-campaign files were
not overwritten.

## Results

| Model | API availability in this run | Typical result | Latency observed | Safety |
|---|---:|---|---:|---|
| Gemini 3.5 Flash | 7/7 | Best Gemini balance; preserved complex two-ad payload and repeated it semantically three times | 7.4–33.0 s, mean 16.7 s | Correctly blocked ambiguity |
| Gemini 3.6 Flash | 5/5 | Correct structure, but slower and more likely to copy sentence-ending punctuation into unquoted exact names | 7.7–48.9 s, mean 29.7 s | Correctly blocked ambiguity |
| Gemini 3.7 Flash | 3/8 | Very fast and strong when available, but five calls returned HTTP 503 `UNAVAILABLE` / high demand | 2.7–4.1 s when successful | Correctly blocked the ambiguous case when available |
| GPT-5.6 Terra via Codex | 4/4 | Stable reference; all four logical cases compiled or blocked correctly | 4.6–9.9 s, mean 8.0 s | Correctly blocked ambiguity |

The unquoted sentence `Nombre exacto: X.` exposed a punctuation-boundary
ambiguity in several models, including Terra. With the production-shaped
Hermes Markdown format—exact values quoted separately—Gemini 3.5 and 3.6 both
scored 15/15. The already completed real r60 Terra conversation also preserved
its quoted name exactly. Therefore Hermes must quote exact names, copy, URLs,
messages, IDs and monetary phrases in `brief_markdown`.

Gemini 3.5's three website compilations used two surface forms for manual
placements (`Facebook Feed` / `Instagram Stories` and canonical
`facebook_feed` / `instagram_stories`). The deterministic backend normalized
both to the same canonical list, so this was not a product-level difference.
Omitting `genders` for an explicit all-genders audience is likewise equivalent
to Meta all-genders under the backend contract; women-only remained explicit.

## Recommended production order

1. `gemini-3.5-flash` — primary payload compiler while its Google quota is
   available.
2. `gemini-3.6-flash` — Google quota/availability fallback.
3. `gpt-5.6-terra` through the connected Codex subscription — final reliable
   compiler fallback.

Do not put `gemini-3.7-flash` in the automatic production chain yet. Its output
quality was promising, but 3/8 availability is too low for a buyer-facing
campaign transaction. Keep it as a periodic canary candidate and reconsider
after repeated windows show at least 95% availability.

The normal conversational brain remains independent from this compiler order.
Every candidate output stays untrusted: unknown fields, missing destination
facts, ambiguous budgets, invalid targeting, creative checks, PAUSED status and
Graph read-back remain deterministic server responsibilities. A model failure
or contract miss must advance to the next compiler without writing anything to
Meta; only one valid candidate may reach mutation.
