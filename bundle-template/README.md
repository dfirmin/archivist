---
type: Reference
title: "{{name}} Knowledge Bundle"
description: An OKF knowledge bundle — the business context layer for {{name}}.
---

# {{name}}

**Business context as an OKF knowledge bundle.** This repository holds curated
domain knowledge — concepts and the sources they cite —
so people and agents can locate, read, and ground work in a shared catalog.

It follows the [Open Knowledge Format (OKF)](https://github.com/GoogleCloudPlatform/open-knowledge-format)
v0.2 conventions: one concept per Markdown file, YAML frontmatter for typed
metadata, and reserved `index.md` / `log.md` files for navigation and history.

## Why this exists

Scattered documentation and tribal knowledge do not travel well into
agent workflows. This bundle is the durable, reviewable layer: progressive
disclosure for discovery, cited concepts for trust, and a change log for
temporal honesty.

## Getting started

| Goal | Start here |
|------|------------|
| Find a concept | [`index.md`](index.md) — the concept map with links and short descriptions |
| See what changed | [`log.md`](log.md) — newest-first creation and update history |
| Read a concept | Follow the link into `knowledge/` (or another concept file) |
| Agent instructions | [`AGENTS.md`](AGENTS.md) |

**Recommended flow:** open the index → pick the matching group and
concept → read the concept body and frontmatter → follow citations when you
need source detail.

## Repository layout

```
.
├── index.md          # Progressive disclosure — what exists and where
├── log.md            # Chronological update history
├── AGENTS.md         # How agents should navigate this bundle
├── README.md         # This file
├── knowledge/        # Authored OKF concepts (paths are concept IDs; layout set by contracts)
├── contracts/        # This target's specification for archivist (human PRs only)
└── sources/          # Source documents: inbox/ (waiting) and processed/ (cited)
    ├── inbox/        # Incoming inputs awaiting processing
    └── processed/    # Consumed inputs retained for citation
```

## Concept documents

Each file under `knowledge/` is one OKF concept. Typical frontmatter
includes:

- `type` — concept class (required by OKF)
- `title` / `description` — human-readable identity
- `tags` — cross-cutting categories
- `sources` — the documents the concept was authored from
- `generated` / `verified` — authorship and trust stamps
- `okfx_` fields — this target's extensions, plus `okfx_gaps` and `okfx_confidence`

The Markdown body carries the business explanation: purpose, grain, attributes,
relationships, and known gaps. Prefer the body and its citations over guessing.

## Who maintains this

Content is authored and refreshed by archivist (inbox → author → enrich →
verify → gaps → score → catalog), as this repository's `contracts/` specify,
then reviewed through pull requests. Humans own product decisions and gap resolution; agents record what
the sources support and what is still missing.

## Further reading

- Agent navigation: [`AGENTS.md`](AGENTS.md)
- Bundle profile: [`okf/PROFILE.md`](okf/PROFILE.md)
- Bundle map: [`index.md`](index.md)
- Change history: [`log.md`](log.md)
- OKF specification: [GoogleCloudPlatform/open-knowledge-format](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md)
