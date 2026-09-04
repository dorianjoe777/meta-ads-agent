# Codex image generation: architecture and troubleshooting

This is the durable operating guide for image generation through a buyer's
ChatGPT/Codex subscription. Read it before changing models, upgrading Codex,
or debugging a Telegram creative that is slow, missing, or reported as
successful without an attachment.

## Shared ChatGPT/Codex OAuth pool

The hosted service uses two to eight operator-managed ChatGPT/Codex accounts.
Each account has a private `CODEX_HOME` below
`/app/runtime/hermes/codex-auth-pool/<account-id>` and its own lock/cooldown.
The operator dashboard may add or reconnect a slot, but image jobs never copy
OAuth material into a tenant container or select an API key.

Personal/non-sponsored installations retain their own isolated login at
`CODEX_HOME = HERMES_HOME/codex-auth`; never import an older CLI cache over a
newer login.

On a personal installation, the authorized Telegram chat can send `/conectar_chatgpt` or a
clear request such as “dame el enlace para cambiar la cuenta de ChatGPT”. The
gateway handles this before inference, so it also works while the primary model
is unavailable. It returns only the allow-listed OpenAI URL and one-time code.
The deliberate account-switch flow clears OAuth artifacts from the old main and
image-only stores, preserves business memory/campaign data, changes Image 2 to
`main_chatgpt`, and starts `codex login --device-auth` without the former
30-second timeout. A Hermes-only login remains a 300-second compatibility
fallback when the Codex CLI is absent.

For a hosted pool slot, verify these conditions without reading `auth.json`:

1. `codex login status` succeeds with that slot's isolated `CODEX_HOME`.
2. A Terra probe succeeds with `-m gpt-5.6-terra` in the same home.
3. The central pool selects and cools down only the slot that actually ran.

The companion end-to-end test procedure is
[`real-conversation-image-canary.md`](real-conversation-image-canary.md).

## What the product actually does

This route does **not** call the OpenAI Images API with an Admira API key. The
shared service selects one isolated operator-owned ChatGPT/Codex OAuth slot and
starts one ephemeral `codex exec` turn pinned to `gpt-5.6-terra`. Terra receives
the complete creative brief and the `$imagegen` instruction, invokes the image
tool, and writes the raster result below that slot's `generated_images` tree.

```text
Telegram buyer
  -> Hermes Gateway
  -> configured conversational brain (Gemini in the current canary)
  -> mcp_admira_codex_image_generate
  -> Admira MCP subprocess
  -> Admira tool bridge / dashboard image action
  -> shared central OAuth account pool
  -> codex exec -m gpt-5.6-terra with $imagegen
  -> the image-generation tool in that Codex turn
  -> <selected-CODEX_HOME>/generated_images/.../image.png
  -> /app/output/creatives/codex-.../admira-image.png
  -> MCP role=tool result containing media_attachment=MEDIA:<path>
  -> Admira Hermes runtime attachment hook
  -> Telegram sendPhoto/media-group delivery
```

The older standalone `/codex/images/generations` adapter remains in the source
only as a rollback/diagnostic component; it is no longer the production
provider for the shared pool. The active route consumes the selected account's
Codex allowance as well as any image-generation allowance enforced by OpenAI.

## Hybrid designs with real buyer photos

When real buyer-owned photos must remain literal, the existing image MCP can
use its `real_media` contract. This is a branch inside the same provider path,
not another image service and not a Codex reasoning runtime:

```text
natural Telegram request
  -> main model reads creative-production-codex-image
  -> mcp_admira_codex_image_generate(real_media=[1..6 ordered slots])
  -> select non-brand chroma key per slot
  -> Terra calls `$imagegen` to create one dynamic overlay
  -> validate connected masks and slot mapping
  -> insert exact buyer photos locally (crop/scale/mask only)
  -> insert exact saved logo locally
  -> return and attach the final composited PNG
```

Supported layouts are one-photo `hero`, two-photo `before_after`, two or more
independent `services`, three-to-six-photo `collage`, and one-to-six-photo
`freeform`. Image 2 remains free to vary hierarchy, frames, typography,
negative space, bullets and CTA. The slot IDs and chroma colors are technical
coordinates, not a fixed visual template.

The buyer does not need to write an Image 2 prompt. Before the MCP call, the
creative skill expands a short natural request into a semantic art direction
using the exact active offer, confirmed parent branding, objective, audience,
format, on-image text and ordered photos. The backend rebuilds any sparse
optional context from the same exact saved brand/product/brief references. It
never selects the first saved offer as a fallback and never invents a price,
promotion, guarantee, testimonial, credential or result. The reusable prompt
families and placeholders live in
`agent/skills/creative-production-codex-image/references/hybrid-prompt-refinement-playbook.md`.
They constrain meaning, not geometry, so repeated generations may remain
materially different.

Real photos and the official logo are never sent to Image 2 in this branch.
At most one style-only reference is sent, and only when the main model
explicitly supplies `style_reference.mode=pool|explicit`; the default is
`none`. Pool selection is a persisted shuffled bag with no immediate repeat.

Technical acceptance checks masks, overlap, meaningful duplicate regions,
residual chroma, source hashes and final output hash. It does not classify the
buyer conversation and does not add an approval card. OCR is advisory because
stylized text recognition is unreliable; the buyer's visual review remains
the aesthetic/text decision.

Logo modes are `original`, `white`, `black`, `brand_primary`,
`brand_secondary`, and `auto_contrast`. Solid/recolored modes require an
official transparent PNG. An opaque JPG is allowed only in `original` mode;
the product does not guess which white pixels are background because doing so
could damage the real logo.

First places to inspect when this branch fails:

- `real_media` asset is not classified `pixel_locked` or not approved for the
  requested paid/organic purpose;
- a slot ID is duplicated, or before/after roles are swapped/missing;
- stored brand colors are absent, causing poor chroma selection;
- Image 2 reused a key color outside its slot, omitted a slot, or produced
  more than one meaningful keyed component;
- a recolored logo mode was requested from an opaque logo;
- the overlay succeeded but the final `MEDIA:` attachment hook did not send
  the composited `*-composited.png` file.

The full contract and prototype evidence are in
[`IMAGE2_REAL_MEDIA_MULTISLOT_PROTOTYPE_2026-08-27.md`](IMAGE2_REAL_MEDIA_MULTISLOT_PROTOTYPE_2026-08-27.md)
and [`real-photo-ad-overlay-pipeline.md`](real-photo-ad-overlay-pipeline.md).

## Current canary contract

As of 2026-09-04, the intended canary contract is:

- Main conversational brain: Gemini through Hermes.
- Primary shared image worker: `codex exec -m gpt-5.6-terra` with `$imagegen`.
- Authentication: the central pool's selected ChatGPT/Codex OAuth slot; no
  OpenAI API key or custom API base is inherited by the image subprocess.
- Codex CLI observed during the repair: `0.147.0`.
- Inner image-provider or Codex-fallback timeout: 270 seconds.
- Complete buyer-facing creative-tool ceiling: 300 seconds.
- Codex process starts in its own process group and the complete group is
  terminated on timeout.
- Published images live under `/app/output/creatives/`.
- Codex OAuth is isolated under `/app/runtime/hermes/codex-auth`; it must not
  share Hermes' provider `auth.json`.
- Telegram success requires a native attachment event, not only a PNG on disk
  or a success sentence.

The primary provider now depends on Terra being available to the selected
account and CLI. Account catalogs, subscription entitlements, and CLI
compatibility can change, so release validation must include a real canary.

## Configuration flow: central pool, Terra, then ImageGen

`CentralCodexAccountPool` chooses an available account, locks that slot, and
passes its private home to `call_codex_image_cli_direct()`. The provider pins
`gpt-5.6-terra`; tenant configuration cannot replace it. The subprocess receives
the same selected path as both `CODEX_HOME` and the isolation boundary, and any
inherited OpenAI API key/base URL is removed. A Codex usage-limit failure puts
only that slot on cooldown and permits at most one alternate account attempt.

Do not trust only the host `.env`, Compose inspection, dashboard display, or
`/app/runtime/.env`. The value that matters is the value inside the live MCP
process and the `-m` argument on the live Codex command.

Verify all four layers:

```bash
# 1. Central pool configuration
docker inspect <central-container> --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep -E '^ADMIRA_CENTRAL_CODEX_(AUTH_ROOT|ACCOUNT_IDS)='

# 2. OAuth status for each configured slot (never print auth.json)
docker exec <central-container> sh -lc \
  'CODEX_HOME=/app/runtime/hermes/codex-auth-pool/<account> codex login status'

# 3. While the controlled canary runs, inspect the pinned command
docker top <central-container> -eo pid,ppid,etimes,stat,comm,args \
  | grep -E 'codex exec|admira_codex_image_generate'
```

The live command must contain `-m gpt-5.6-terra`. A different model means the
central image service is running an old image or old source checkout.

## Authentication layout

Hermes and Codex use different authentication formats:

- `HERMES_HOME=/app/runtime/hermes` stores Hermes provider/session state.
- `CODEX_HOME=/app/runtime/hermes/codex-auth` stores Codex CLI OAuth.

Sharing one `auth.json` between them can make a status check look plausible
while `codex exec` receives a 401 or unusable credentials. Always check the
same home the worker uses:

```bash
docker exec <container> sh -lc \
  'CODEX_HOME=/app/runtime/hermes/codex-auth codex login status'
```

Do not print or copy `auth.json` into logs, tickets, documentation, or chat.

## First-response checklist

Use read-only checks before restarting or editing anything:

1. Record UTC time, buyer/chat, elapsed time, and requested asset count.
2. Inspect `agent.log` from just before the request.
3. Inspect the process tree and exact `codex exec -m ...` command.
4. Check whether a new file exists in `/app/output/creatives/` and in the
   selected `CODEX_HOME/generated_images/` tree.
5. Sample the native Codex process I/O twice several seconds apart. Zero I/O,
   no new files, and no network activity indicate a stall rather than a slow
   render.
6. Confirm effective model, CLI version, login home, and timeout.
7. Check native Telegram delivery logs separately from generation logs.
8. Compare host, live-container, and tagged-image source hashes before editing.

Useful commands:

```bash
date -Is
docker top <container> -eo pid,ppid,etimes,stat,comm,args
docker exec <container> tail -n 240 /app/runtime/hermes/logs/agent.log
docker exec <container> sh -lc \
  'find /app/output/creatives -type f -mmin -15 -printf "%TY-%Tm-%TdT%TH:%TM:%TS %s %p\n" | sort'
docker exec <container> codex --version
```

## Frequent failure modes and where to look

### Installed Codex CLI is too old

Symptoms include unsupported flags, missing `$imagegen` capability, model
metadata errors, or a model that works in a newer Codex environment but not on
the droplet. Check `codex --version`, the exact binary path, and whether the
container image actually contains the upgraded CLI. Upgrading a host-global
binary does not upgrade a binary baked into the running container.

After an upgrade, verify login status again and perform one controlled canary.
Do not assume CLI upgrades preserve authentication paths or model support.

### Configured model is unavailable or too new for the CLI

The buyer's plan determines which Codex models are exposed. A model available
on one subscription may be absent on Go or another plan. The CLI may also be
too old to recognize a currently entitled model. Look for `model_not_found`,
`unsupported model`, `model metadata`, or `requires a newer version of codex`.

Never silently substitute a heavy or unrelated model. Use a model confirmed in
the buyer's actual account catalog. On this canary, Terra was retained because
Luna could not be assumed for Go subscriptions.

### Model propagation bridge is missing

The container may correctly advertise Terra while the isolated MCP subprocess
loads an old value from `/app/runtime/.env`. The visible symptom is a live
command such as `codex exec -m gpt-5.5` despite Compose showing Terra. Inspect
`mcp_servers.admira.env`, the MCP process environment, and the live command.

The required bridge fields are:

```text
CODEX_IMAGE_HERMES_MODEL=<configured model>
ADMIRA_HEAVY_TOOL_TIMEOUT_SECONDS=300
```

Restart the Gateway/container after changing generated MCP configuration;
long-running processes do not reload Python modules or environment variables.

### MCP result compatibility bridge is missing

Hermes Agent 0.18 reads `CallToolResult.isError`; MCP 2.x exposes the Python
field as `is_error`. A successful image can be followed by:

```text
'CallToolResult' object has no attribute 'isError'
```

All Hermes subprocesses must receive `/app/src` on `PYTHONPATH` and
`ADMIRA_HERMES_RUNTIME_PATCHES=1` so the compatibility alias loads before the
MCP adapter.

### Image exists but Telegram sends only text

Generation and delivery are separate stages. Real Hermes MCP output stores the
asset in a `role=tool` message, followed by the model's normal assistant text.
The runtime attachment hook must inspect all current-turn tool/assistant
messages after the latest buyer message, append the internal `MEDIA:<path>`
directive, and never replay media from an older turn.

A PNG on disk plus “good news, I generated it” is still a failure unless logs
show image extraction and `sendPhoto`/media-group delivery.

One concrete failure shape is `MEDIA:<path>` followed by `[ADMIRA FINAL]` in
the model response. Private-reasoning cleanup removes everything before that
marker. The runtime must therefore normalize the visible answer first and only
then append current-turn media recovered from the successful `role=tool`
message. Reversing those operations silently deletes the valid attachment.

### Codex stalls until timeout

A healthy image commonly finishes in about one minute, but provider latency
varies. The current worker ceiling is 270 seconds and the complete tool ceiling
is 300 seconds. A request must not leave Telegram working for nine or ten
minutes.

On timeout, `codex exec` must have `start_new_session=True`, and cleanup must
signal its complete process group. Killing only the Node launcher can leave the
native Codex child alive and consuming memory or holding subscription work.

After cleanup, check for leftovers:

```bash
docker top <container> -eo pid,ppid,etimes,stat,comm,args | grep -E 'codex exec|\[codex\]'
ps -eo pid,ppid,pgid,sid,stat,etime,comm,args | grep -E 'codex|admira_tool_bridge'
```

A `Z`/`<defunct>` process cannot be killed again; its parent must reap it. A
planned container restart clears it. Confirm the PID and command belong to the
failed image request before signaling any process group.

### Legacy direct-image route preempts Codex exec

The shared-pool invariant is now the reverse of the retired 2026-08-18 design:
`CentralCodexAccountPool._default_provider()` must call
`call_codex_image_cli_direct()` directly. It must not call
`run_hermes_image_bridge()` or `call_codex_image_native()` first. One request
gets at most one attempt per slot and two slots total; it never runs both image
transports for the same attempt.

### Subscription quota or provider throttling

Look for rate-limit, usage-limit, weekly-image-limit, quota, 429, or retry-after
text. Do not automatically retry a successful or ambiguous image call: a
duplicate consumes subscription capacity and can create the wrong attachment.
Return one clear retryable failure and preserve the original diagnostic.

On this route, a generic usage/rate-limit result from `codex-cli-direct` is a
Codex allowance failure. The pool records only `codex_usage_limit`, cools down
that exact slot, and may try one other slot. It does not bypass a Codex limit by
calling the retired standalone image transport.

### A file appears after a reported failure

Compare file modification time and request start time, then validate the file
with Pillow. Do not attach an older image merely because it is the newest file
in a shared directory. Current-turn tool metadata is authoritative; directory
scanning is only diagnostic/recovery evidence.

### Host, container, and image tag contain different code

The canary can have three distinct copies:

1. Host checkout under `/opt/admira-ia`.
2. Writable filesystem of the running container under `/app`.
3. Image currently referenced by the canary tag.

Never patch the oldest convenient copy. Hash the exact files first:

```bash
sha256sum /opt/admira-ia/src/<file>
docker exec <container> sha256sum /app/src/<file>
docker run --rm --entrypoint sha256sum <image-tag> /app/src/<file>
```

If they differ, recover the exact live or intended image baseline before using
`apply_patch`. After verification, sync the repaired source deliberately,
restart the canary, and commit/tag the verified container state. Keep a named
pre-fix image tag for rollback. Do not update the local repository until that
separate task is explicitly requested.

### Tests expect an obsolete authentication directory

Older tests expected `CODEX_HOME` to equal `HERMES_HOME`. The current security
contract deliberately uses `<HERMES_HOME>/codex-auth`. A failing path assertion
must be checked against `codex_cli_environment()` before changing production
behavior. Update stale test expectations when the isolated path is intentional;
do not collapse the two auth stores to make an old test pass.

## Safe recovery order

1. Stop duplicate requests; do not generate another image for diagnosis.
2. Let a request close through its bounded timeout unless it threatens the
   service. Capture its final tool result.
3. Terminate only a confirmed leftover image-worker process group.
4. Correct configuration/code on the exact live baseline.
5. Run focused tests that use fake subprocesses and consume no image quota.
6. Restart so Gateway and MCP reload the patch.
7. Verify model and timeout inside the live MCP process.
8. Check HTTP health, Telegram reconnection, and Codex login.
9. Persist the verified container to the canary tag with a rollback tag.
10. Run one real conversational canary only when end-to-end proof is needed.

## Required regression coverage

Keep tests for all of these behaviors:

- MCP receives the configured image-worker model.
- A healthy `openai-codex` provider runs before direct Codex CLI fallback.
- Creative tool timeout cannot exceed 300 seconds.
- Inner Codex worker uses a shorter 270-second ceiling.
- Timeout sends SIGTERM to the complete Codex process group.
- MCP `isError` compatibility loads in every Hermes subprocess.
- A current-turn `role=tool` media attachment reaches the final response.
- Media from an older turn is not replayed.
- Codex and Hermes authentication homes remain isolated.

## Meaning of success

Declare the route healthy only when one buyer request produces exactly one
valid image, Hermes returns a truthful natural-language response, Telegram
sends the native attachment, no duplicate tool call occurs, and no Codex
process remains after completion. Each stage must be verified independently.
