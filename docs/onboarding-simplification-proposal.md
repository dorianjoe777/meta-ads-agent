# Onboarding simplification proposal

Goal: make first setup feel calm, obvious, and low-click. The buyer should only see what they need for the current action.

## Current friction observed

- Some steps explain too much before the buyer needs it.
- Several actions require an extra confirmation click after the system already has enough information.
- Cards use many badges, helper paragraphs, and glowing states at the same time, which makes the screen feel heavier than the actual task.
- The final communication-preference step had too much explanatory copy for a simple choice.

## Proposed direction

Use a “one action per screen” rhythm:

1. What to do now.
2. One primary button or field.
3. Tiny reassurance only if needed.
4. Advanced/fallback help hidden in a collapsible area.

## Suggested step-by-step cleanup

### 1. Meta connection

- Keep the guided screenshots, but reduce surrounding text.
- Show only the current screenshot instruction and one next action.
- Move detailed explanations into “Need help?”.

### 2. Account and Page selection

- If there is one obvious result, auto-select or highlight it as the default.
- If there are several, show them as simple cards with one sentence each.
- Hide manual ID fields by default, as they already are.

### 3. Agent connection

- Keep the large visible code.
- Keep the device-code help button.
- Reduce secondary diagnostic text unless there is an error.

### 4. Telegram

- Current improvement: after “I sent hello”, auto-select the detected chat, send the welcome message, and move to the next step.
- Later: compress the bot setup into:
  - “Open BotFather”
  - “Send /newbot”
  - “Paste the key here”
  - “Send hello”
- Keep the video, but make it optional/collapsible on desktop if the main action is clear.

### 5. Communication style

- Keep as a final lightweight choice.
- Copy should stay short:
  - “Palabras simples — Directo, claro y sin jerga.”
  - “Explicaciones técnicas — Más detalle cuando ayude a decidir.”
- No long legal/safety explanation here.

## Product rule to apply across onboarding

If the system can safely infer or complete the next action, it should do it automatically and only tell the buyer what happened.

Examples:

- One detected Telegram chat: select it automatically.
- One obvious Page/account: consider auto-selecting or preselecting it.
- Saved token + found assets: move forward without requiring another click when risk is low.

## Later design pass

Create a dedicated “minimal onboarding mode” with:

- shorter cards;
- fewer badges;
- one primary CTA per step;
- optional help drawer;
- stronger progress indication;
- cleaner mobile layout;
- less animated glow except for the one action that matters.
