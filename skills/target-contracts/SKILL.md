---
name: target-contracts
description: >
  How to find and read the target's contracts in contracts/: the index, the built-in kinds
  (concept-types, structures, intake, gap-kinds, scoring, catalog, publishing) and the
  target's own reference data. Use whenever a step says "per the contract" or names
  reference data such as an inventory, owner manifest, glossary or naming standards.
allowed-tools: Bash, Read, Grep, Glob
---

The target owns the *what*; you apply it. Contracts are read-only: never edit anything under
`contracts/`. A contract states rules in fields and in prose (`guidance`, `scope`,
`grouping`, `naming`, `structure_rule`, `from` …). Prose in a contract is binding the same
way a field is.

## 1. Start at the index

`contracts/target.yaml` is the only fixed path. Its `contracts:` map names each built-in
kind's file (paths relative to `contracts/`); its `reference:` map names the target's own
data. A kind that is absent is not used by this target: apply the default named below,
never invent a contract.

```bash
cat contracts/target.yaml
```

The run plan (`.claude/archivist/run-plan.yaml`) lists the same paths bundle-relative.

## 2. Built-in kinds

| Kind | What it decides | Default when absent |
|---|---|---|
| `concept-types` | each concept type: OKF `type`, `path`, `structures` + `structure_rule`, `tags`, `fields` (with `from`), `companions` | none — authoring needs it |
| `structures` (directory) | one file per structure: `sections`, each with `owner` (author, enricher, placeholder), `placeholder`, `enrich`, `subsections` | none — authoring needs it |
| `intake` | `concept_type`, `scope`, `grouping`, `ordering`, `naming`, `classes` (mode + routed sections) | every document in scope, its own group, one class `create` / all sections |
| `gap-kinds` | the gap fleet (see the **gap-kinds** skill) | no gap stage |
| `scoring` | the confidence rubric | no score stage |
| `catalog` | index grouping and log wording | group the index by concept type |
| `publishing` | gap-issue title, labels, routing | title `{title} — {kind}` |

## 3. Reference data

Each `reference.<name>` entry has a `path`, a `description` (what it holds) and usually
`guidance` (how to look things up in it and what a hit or a miss means). **Follow the
guidance exactly**: it is where the target puts rules such as "no row means out of scope" or
"abbreviations resolve here before the glossary".

Read only what you need:

```bash
grep -i "^<KEY>," contracts/<path>.csv          # CSV: rows start with the key column
grep -n -A3 "^  <KEY>:" contracts/<path>.yaml    # YAML mapping keyed by name
```

A CSV may carry `#` comment lines; the first non-comment row is the header (the index's
`columns` lists it). Copy values exactly as stored. An empty lookup is a result: report it
and leave the value unset rather than inferring one. Model knowledge, a familiar-looking
expansion or a nearby value is not a lookup hit.

## 4. Fields

Concept frontmatter uses OKF fields (`type`, `title`, `description`, `tags`, `sources`,
`generated`, `verified`, `status` …) and `okfx_` extensions. A concept type's `fields` lists
its extensions and where each value comes from. `okfx_gaps` and `okfx_confidence` belong to
the engine (gap-agent fleet and scorer); no other role writes them.

Done when you have the contract entries and reference values the current step needs, each
traced to a file under `contracts/`.
