---
type: Reference
title: Contract examples
description: Worked examples of archivist contracts, for reference only.
---

# Contract examples

Copies of the engine's example targets, kept here while you write this repository's own
contracts in `contracts/`. Agents never read them. They are refreshed whenever the engine
re-scaffolds or upgrades this repository, so edit your own `contracts/`, not these. Each example
has a `sources/inbox/` of sample documents, clean and messy, and a `README.md` listing what each
document should become and when the example was last tested live.

## Which example shows what

| You want to… | Look at |
|---|---|
| Start as small as possible (two contracts, author + verifier) | `minimal/` |
| Send different kinds of document to different concept types | `handbook/contracts/intake.yaml` (each class names a `concept_type`) |
| Let one concept type pick a structure **by the document's content** | `handbook/contracts/concept-types.yaml` → `runbook` → `structure_rule` |
| Let a concept type pick a structure **by looking something up** | `warehouse/contracts/concept-types.yaml` → `subject-area-overview` → `structure_rule` (reads the archetype in `reference/owners.yaml`) |
| Use the recorded structure (`okfx_structure`) in a gap check | `handbook/contracts/gap-kinds.yaml` → `missing_escalation`, `missing_rollback` |
| Give agents your own reference data with lookup rules | `handbook/contracts/reference/teams.yaml`, `warehouse/contracts/reference/` + `reference:` in each `target.yaml` |
| Fill a section from source code (an enrichment method) | `warehouse/contracts/structures/data-view-group.yaml` → `Code-Extracted Logic` |
| Fill only some sections from a partial document | `warehouse/contracts/intake.yaml` → classes with `mode: partial` |
| Hold a document until its main document exists | `handbook/contracts/intake.yaml` → `policy-amendment`, `warehouse/…` → `rule-amendment` (`mode: enrich-only`) |
| Update the existing document instead of creating a duplicate | `identity` on each type in `warehouse/contracts/concept-types.yaml` (a list field, a reference code, a composite) and `handbook/` (title with matching guidance) |
| Hold back what cannot be placed (quarantine) | `scope` in `warehouse/contracts/intake.yaml` and `handbook/contracts/intake.yaml`; the expected outcomes in each example's `README.md` |
| Split meeting transcripts into topic extracts | `warehouse/contracts/intake.yaml` → `meeting-transcript`, `handbook/…` → `incident-review-call` (`mode: extract`) |
| Define metrics and business rules | `warehouse/contracts/concept-types.yaml` → `metric-definition`, `business-rule` |
| Group the index and title gap issues your way | `catalog.yaml`, `publishing.yaml` in `handbook/` and `warehouse/` |
| Choose your own pipeline | `pipelines:` in `handbook/contracts/target.yaml` and `minimal/contracts/target.yaml` |

How a document's structure is decided, step by step: see the engine's `docs/contracts.md`.
