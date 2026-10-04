---
type: Reference
title: Contract examples
description: Worked examples of archivist contracts, for reference only.
---

# Contract examples

These folders are copies of the engine's example targets, kept here as reference while you
write this repository's own contracts in `contracts/`. Agents never read them.

| Example | Shows |
|---|---|
| `minimal/` | The smallest useful target: two contracts, an author + verifier pipeline |
| `warehouse/` | Every contract kind: intake classes, several structures, an enrichment section, reference data with lookup guidance, gap kinds, scoring, catalog grouping, issue publishing |

Copy a shape into `contracts/`, adapt it, and run `archivist validate . --pipeline <name>`.
