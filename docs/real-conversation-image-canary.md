# Real conversation image canary (simulated Telegram)

Use this runbook when the operator asks for a **real conversation canary**, a
**Hermes image-generation canary**, or a **simulated Telegram image test**.
It exercises the buyer-facing agent and its real MCP tool path without sending
a message to Telegram and without publishing or changing anything in Meta.

For architecture, known failure modes, configuration propagation, authentication
layout, process cleanup, source-skew checks, and recovery order, read
[`codex-image-generation-operations.md`](codex-image-generation-operations.md)
first.

## Path under test

```text
simulated Telegram payload
  -> telegram_agent.handle_text(send=False)
  -> agent_chat.chat
  -> hermes_bridge.chat / Hermes CLI
  -> configured main brain (for example Gemini)
  -> mcp_admira_codex_image_generate
  -> Hermes openai-codex provider with the dedicated ChatGPT subscription
  -> gpt-image-2-medium (direct Codex CLI/Terra only as compatibility fallback)
  -> saved image under /app/output/creatives/
```

This is not a direct call to `codex_image_generate`. The test only passes when
Hermes independently selects and calls the MCP image tool during a natural
conversation.

## Safety rules

- Run only on the requested canary droplet/container, never in the local repo.
- Use a unique negative numeric chat ID reserved for the canary.
- Pass `send=False`; never contact a real Telegram chat.
- State explicitly in the buyer prompt that nothing should be published to Meta.
- Request one asset only. Stop if Hermes retries an identical successful image
  call, because duplicate calls consume the buyer's subscription quota.
- Do not reset or overwrite a real dashboard or Telegram conversation.
- Never print credentials, OAuth artifacts, dashboard passwords, or tokens.

## Preconditions

Resolve the active canary container and verify the model routes without showing
secrets:

```bash
docker ps --format '{{.Names}} {{.Image}} {{.Status}}'
docker exec <container> sh -lc 'python3 -c "import os; print({
  \"agent_provider\": os.getenv(\"AGENT_CHAT_PROVIDER\"),
  \"agent_model\": os.getenv(\"AGENT_CHAT_MODEL\"),
  \"image_source\": os.getenv(\"CODEX_IMAGE_SOURCE\"),
  \"image_model\": os.getenv(\"CODEX_IMAGE_HERMES_MODEL\"),
})"'
docker exec <container> sh -lc 'CODEX_HOME=/app/runtime/hermes/codex-auth codex login status'
```

Expected architecture:

- `AGENT_CHAT_PROVIDER=hermes`
- the main conversational model is the configured buyer-facing brain
- `CODEX_IMAGE_SOURCE=dedicated_chatgpt`
- provider status resolves to `openai-codex`; the configured Codex model is
  only the compatibility fallback
- Codex reports that it is logged in with ChatGPT

## Execute one real conversation

Record the UTC start time and current image inventory. Then invoke the exact
Telegram handler with a unique test ID. The prompt should contain a complete
offer and visual brief so the agent does not need clarification.

```bash
docker exec <container> sh -lc '
  cd /app &&
  PYTHONPATH=/app/src:/app/dashboard python3 -c "
from product_config import load_config
from telegram_agent import handle_text

chat_id = -820080001  # replace with a new unique negative ID
prompt = (
    \"Hola. Vendo cafe colombiano premium en bolsas de 340 g. \"
    \"Genera ahora una imagen cuadrada 1:1 lista para un anuncio de Meta: \"
    \"bolsa kraft sin logotipos inventados sobre una mesa de madera, \"
    \"montanas colombianas suaves al amanecer al fondo, granos de cafe, \"
    \"fotografia publicitaria realista, luz calida, sin texto ni personas. \"
    \"No quiero solo ideas: usa la herramienta de imagen y crea el archivo final. \"
    \"No publiques nada en Meta.\"
)
print(handle_text(load_config(), chat_id, prompt, send=False))
"'
```

The command can take several minutes. A successful render normally finishes in
about one minute; the buyer-facing image tool must stop and return a clear
failure within five minutes. Do not launch a second test while it is running.

## Verify the result

Check the Hermes trace from the recorded start time. A passing trace contains:

1. `conversation turn` with `provider=<main brain>` and the expected model.
2. Exactly one `mcp_admira_codex_image_generate` execution.
3. A completed tool result, with no adapter exception afterward.
4. A final response that truthfully says the image was created and includes the
   saved preview or asset information.
5. A Telegram media-delivery log after the text response, such as
   `Extracted 1 image(s) to send as attachments` or the equivalent successful
   `sendPhoto`/media-group event. A success sentence without this evidence is
   a delivery failure even when the PNG exists.

```bash
docker exec <container> sh -lc 'tail -n 240 /app/runtime/hermes/logs/agent.log'
docker exec <container> sh -lc '
  find /app/output/creatives -type f -mmin -15 \
    \( -iname "*.png" -o -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.webp" \) \
    -printf "%TY-%Tm-%TdT%TH:%TM:%TS %s %p\n" | sort'
```

Validate every newly created file as a real decodable image:

```bash
docker exec <container> sh -lc 'python3 -c "
from pathlib import Path
from PIL import Image
for path in sorted(Path(\"/app/output/creatives\").glob(\"codex-*/*\")):
    if path.is_file():
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            print(path, image.format, image.size, image.mode, path.stat().st_size)
"'
```

Visually inspect the new image before declaring success. Confirm it follows the
requested subject, ratio, no-text requirement, and basic commercial quality.

## Pass/fail contract

The canary passes only when all of these are true:

- Hermes handled the conversational turn using the configured main brain.
- Hermes selected `mcp_admira_codex_image_generate` itself.
- The image worker used the configured dedicated ChatGPT/Codex route.
- Exactly one new, valid image was created for one requested asset.
- The final buyer response reports success and exposes the resulting asset.
- Telegram receives the actual native image attachment, not only a success
  sentence or a private server path.
- No Meta mutation and no real Telegram send occurred.
- Logs contain no quota/authentication error, timeout, adapter exception, or
  repeated identical tool failure.

Creating a valid file while returning a failure message is **not** a pass.

## Known compatibility diagnostic

Hermes Agent 0.18 may read the old Python attribute
`CallToolResult.isError`, while MCP 2.x exposes the Python field as
`CallToolResult.is_error` and uses `isError` only as its serialized alias. If
the file is created but Hermes logs this exception:

```text
'CallToolResult' object has no attribute 'isError'
```

then Codex/Image succeeded and the failure is in the Hermes MCP result adapter.
Verify that all Hermes subprocesses have `/app/src` on `PYTHONPATH` and
`ADMIRA_HERMES_RUNTIME_PATCHES=1`, then confirm the compatibility shim is active:

```bash
docker exec <container> sh -lc '
  PYTHONPATH=/app/src ADMIRA_HERMES_RUNTIME_PATCHES=1 python3 -c "
from mcp.types import CallToolResult
r = CallToolResult(content=[])
print(hasattr(r, \"isError\"), r.isError, r.is_error)
"'
```

Expected output begins with `True False False`.
