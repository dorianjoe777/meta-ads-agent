---
name: chatgpt-connection
description: Connect or switch the buyer's ChatGPT/Codex subscription through a secure device-login URL for Image generation and Terra fallback. Use only when the buyer requests connection, reconnection, or account switching, or a verified tool result says the subscription is disconnected.
---

# ChatGPT Connection

The runtime compiles this procedure before exposing `mcp_admira_connect_chatgpt`. Follow the compact procedure and current schema; do not add a read-file unlock turn.

## Procedure

1. Call `mcp_admira_connect_chatgpt`, optionally passing the buyer's natural reason.
2. Send the exact secure URL and device code returned by the tool as ordinary chat text.
3. Treat conversational state as waiting for ChatGPT login confirmation.
4. While that state is pending, “Listo/Done” means only: verify the connection and reply with the verified result. It must never reach campaign, Meta-selection, image, or approval tools.

Never tell the buyer to run Codex, Hermes, shell, SSH, or dashboard commands. Do not claim connection, quota exhaustion, account identity, or image availability without corresponding tool evidence. A model-provider rate limit is not automatically an Image quota limit.
