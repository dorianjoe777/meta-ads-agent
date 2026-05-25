# Content Creation System

This project now has a separate content factory for social media assets.

## Content Classes

1. Motion graphics
   - Generated as playable vertical MP4 drafts with Remotion.
   - Each MP4 also gets a `.remotion.json` sidecar with the intended Remotion scene plan.
   - Approved MP4s go to `output/postiz/inbox/`.
   - Higher-quality variants should use the keyframe-to-motion pipeline in `docs/keyframe-to-motion-pipeline.md`.

2. Static image / graphic design posts
   - Generated as reviewable vertical social graphics.
   - Approved assets go to `output/postiz/inbox/`.
   - This gives Postiz a stable pickup folder.

3. UGC / influencer-style video
   - Planned for a later ComfyUI + RunPod workflow.
   - Keep this separate because it needs model/workflow selection, actor consistency, prompt controls, and QA.

## Daily Flow

1. Codex generates the daily batch.
2. Assets appear in `output/content-factory/YYYY-MM-DD/`.
3. The review dashboard shows every generated item.
4. You approve or leave comments.
5. Approved image posts move to `output/postiz/inbox/`.
6. Approved motion videos move to `output/postiz/inbox/`.

## Codex Automation

An active Codex automation named `Daily social content batch` runs every morning and generates:

- 2 static image post drafts
- 2 motion-graphics video drafts with Remotion scene sidecars

It does not approve, post, or move anything to Postiz by itself. Approval stays manual from the review dashboard.

## Commands

Generate today's batch:

```bash
./scripts/generate-content-batch.sh
```

Generate a custom mix:

```bash
./scripts/generate-content-batch.sh --images 3 --motions 2
```

Open the review dashboard:

```bash
./scripts/run-content-dashboard.sh
```

Then open:

```text
http://127.0.0.1:7872
```

Plan image-model keyframes and layer maps for the current motion drafts:

```bash
./scripts/plan-keyframes.sh
```

List the queue:

```bash
python3 src/content_pipeline.py list
```

Approve an item:

```bash
python3 src/content_pipeline.py approve CONTENT_ID
```

Request changes:

```bash
python3 src/content_pipeline.py comment CONTENT_ID "Make the hook shorter and more direct."
```

## Strategy Rules

- Spanish-first for LATAM launch.
- When creating Spanish content, think and write directly in Spanish. Do not draft in English and translate.
- Use proper Spanish orthography: accents, punctuation, and natural phrasing matter.
- Visuals follow the Ad+ reference direction: deep violet, lavender, soft peach, fresh green, teal accents, angular planes, dotted texture, and geometric futuristic type.
- Sell calm operator discipline, not magic automation.
- Avoid guaranteed ROAS, official Meta claims, and fully autonomous spend promises.
- Every piece should connect to one of these pillars:
  - daily ads clarity
  - approval-based automation
  - local/VPS control
  - beginner-friendly explanations

## Postiz Handoff

Postiz should watch or import from:

```text
output/postiz/inbox/
```

Approved static graphics and approved motion MP4 drafts are copied there automatically.
