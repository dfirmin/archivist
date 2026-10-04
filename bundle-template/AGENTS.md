---
type: Reference
title: Agent entry point
description: How agents should navigate and use this OKF knowledge bundle.
---

# Agents

This repository is a **business context layer**: curated domain knowledge that
humans and agents share when answering questions, drafting analysis, or grounding
downstream work. It is an [Open Knowledge Format (OKF)](https://github.com/GoogleCloudPlatform/open-knowledge-format)
bundle — Markdown concepts with YAML frontmatter, organized for progressive
disclosure.

## How to use this bundle

1. **Orient with [`index.md`](index.md).** Start here every time you need to find
   or retrieve knowledge. The index is the progressive-disclosure map of the
   bundle: groups, linked concepts, and short descriptions. Scan it first;
   open only the concept files that match the question.
2. **Check [`log.md`](log.md) for what changed.** When currency matters — what was
   added or revised, and when — read the update log (newest first). Use it to
   prioritize recently authored or updated concepts and to avoid stale
   assumptions about coverage.
3. **Open the linked concept under `knowledge/`.** Concept paths are the
   identity. Prefer the concept the index or log linked you
   to. Read frontmatter for type, tags, provenance, and trust stamps; read the
   body for the business explanation.
4. **Follow citations and links.** Ground answers in the concept body and any
   cited sources it names. Prefer cited facts over inference. When the concept
   notes a gap or placeholder, report that gap as unresolved.

## Layout (consumer view)

| Path | Role |
|------|------|
| [`index.md`](index.md) | Bundle map — find concepts by group |
| [`log.md`](log.md) | Chronological change history (newest first) |
| `knowledge/` | Authored concepts (OKF IDs are paths under here) |
| `references/` | Source documents that concepts cite |
| `contracts/` | The engine's specification for this bundle — not knowledge to answer from |

## Done when

You have answered from indexed concepts (and their citations), noted gaps when
present, and used `log.md` whenever the question depends on what changed over
time.
