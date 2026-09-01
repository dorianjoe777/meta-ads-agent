---
name: creative-codex-image
description: Legacy compatibility name for image production. Route every request to the canonical creative-production-codex-image skill and follow that contract instead of this shim.
---

# Creative Codex Image Skill

## Compatibility shim

This file intentionally contains no production procedure. It exists only so older
workspaces that still mention `creative-codex-image` do not fail skill discovery.

Read and follow, in full:

`../creative-production-codex-image/SKILL.md`

When that canonical skill selects the hybrid real-media path, also read its linked
`references/hybrid-real-media-contract.md`. Do not reinterpret old arguments from a
cached copy of this shim, and do not create or select a second image MCP.

The canonical tool remains `mcp_admira_codex_image_generate`. Do not present
`MEDIA:/...` as a link; when Telegram needs it, use the local path only as
native attachment syntax at the end of the final response.
