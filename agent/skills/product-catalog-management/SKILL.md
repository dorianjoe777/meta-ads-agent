---
name: product-catalog-management
description: Import, organize, retrieve, combine, and use multi-product catalogs of up to 50 products from PDF, Excel, CSV, JSON, chat, or existing product guides. Use whenever the buyer has several products/services/offers, shares a catalog document, asks about bundles, or needs content/campaigns across different product combinations.
---

# Product catalog management

Treat product memory as a catalog, not as one mutable “current offer”. The parent brand owns identity; every product, service, promotion, package, bundle, or lead magnet owns its commercial facts.

## Import

- When the buyer shares PDF, Excel, CSV, TSV, or JSON product information, call `mcp_admira_import_product_catalog` in the same turn with the attached `file_paths`.
- Import every identifiable product into its own natural-language product guide. Preserve SKU, type, category, status, price/cost/margin, descriptions, includes/features/variants, availability, audience, pain, benefit, objections, assets, tags, related products, and unmapped source fields.
- Never flatten 50 products into onboarding, one giant product guide, or durable conversation memory.
- If the importer returns `needs_agent_structuring=true`, read the returned extracted text and call the importer again with a structured `products` array. Do not tell the buyer the catalog is ready before the second call confirms saved product IDs.
- Ask one grouped clarification only for rows that genuinely cannot be identified or mapped.

## Retrieval

- Before discussing, generating, comparing, or reporting on a product in a multi-product business, call `mcp_admira_search_product_catalog` using the buyer's name/SKU/category/benefit/tag wording.
- Use the exact returned guide as the active product context. Never choose the alphabetically first product and never rely only on chat memory.
- When several matches remain plausible, present the short names once and ask the smallest disambiguation question.

## Bundles and combinations

- A combination, kit, package, seasonal set, cross-sell, or multi-product promotion is a separate child offer. Save it with `mcp_admira_save_product_memory` using `kind=bundle` (or the natural equivalent) and `components` containing exact saved product names/SKUs.
- Do not overwrite or merge the source products. A bundle may have its own price, audience, promise, objections, assets, CTA, brief, content pillars, and campaign.
- Validate component names through catalog search before saving or using the bundle.

## Content and campaigns

- For a single-product piece, lock one active product guide.
- For comparison, collection, bundle, or cross-sell content, retrieve every involved product and state the intended relationship before production.
- Rotate organic content intentionally across products/categories/pillars; do not repeatedly select whichever product was discussed most recently.
- Keep product-specific photos and approvals associated with their product IDs/names. Brand assets may be shared; product facts and product photos must not leak into another product.
- Save a separate ad brief for each materially different product, bundle, promotion, or audience test.

## Completion standard

An import is complete only when the tool confirms the expected count, the catalog remains within 50 products, exact products can be searched back by name/SKU/category, and combinations remain separate from their components.
