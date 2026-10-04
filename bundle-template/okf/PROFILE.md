---
type: Reference
title: Archivist OKF Profile
description: How archivist lays out and stamps the OKF bundle it maintains.
---

# OKF profile

This repository is an [Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format)
v0.2 bundle and the repository root is the bundle root. Concepts live under `knowledge/`, so
concept IDs are `knowledge/…` paths. Source documents enter through `references/inbox/` and
are kept, once authored, under `references/processed/` for citation.

`contracts/` is this target's specification for the engine: which concept types exist, how
they are structured, how inbox documents are taken in, which gaps are judged and how
confidence is scored. Contracts change only by human pull request.

Concepts use OKF's own fields where OKF defines one:

- `type` — the exact string the concept-types contract declares;
- `title`, `description`, `tags`, `status`;
- `sources` — the processed documents a concept was authored from;
- `generated: {by: archivist-author/1, at: <UTC>}` — the last authored change;
- `verified` — the verifier appends `{by: process:archivist-verifier/1, at: <UTC>}`.

Every other field starts with `okfx_`. The engine owns `okfx_gaps` (written by the gap-agent
fleet) and `okfx_confidence` (written by the scorer); the target's concept types declare the
rest.

```yaml
type: Business View Group Overview
title: Customer Case
tags: [data, customer-care, business-view-group-overview]
status: draft
generated: {by: archivist-author/1, at: 2026-10-03T16:30:00Z}
sources:
  - {resource: references/processed/documents/catalog-custcase-essential-information.md, title: CUSTCASE - Essential Information}
okfx_subject_area: customer-care
okfx_confidence: 0.85
```
