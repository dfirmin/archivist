---
name: document-structure
description: >
  Turn a concept type, its structure and an intake class into a concept file: path, mode
  (CREATE, PARTIAL CREATE, ENRICH), headings, section ownership, OKF and okfx_ frontmatter,
  placeholders and companions. Use when writing, enriching or validating a concept.
allowed-tools: Bash, Read, Glob, Grep
---

Read the contracts through **target-contracts**. This skill is how they combine.

## 1. Type and structure

The concept type comes from the intake `concept_type` (authoring) or from the concept's own
`type` (any later stage: find the entry in `concept-types` whose `type` equals it). One
entry in `structures` → that structure. Several → apply `structure_rule`, using the
reference data it names.

## 2. Path and mode

Fill the type's `path` pattern: `{field}` placeholders take that field's value, `{title}`
the concept title. Keep spaces and case as the value has them.

Search for an existing concept first: the resolved path, and any concept of the same type
whose `title` matches or whose list fields overlap (for example the same entity names).

| Situation | Mode |
|---|---|
| A concept is found (including one written earlier this run) | **ENRICH**: additive |
| None, and the class `mode` is `create` | **CREATE** |
| None, and the class `mode` is `partial` | **PARTIAL CREATE** |
| None, and the class `mode` is `enrich-only` | leave the document in the inbox: "awaiting its primary document" |

## 3. Sections

A structure's `sections` are `##` headings, `subsections` one level deeper, in order. A bare
string is a section with defaults: `owner: author`, `required: true`.

| Owner | CREATE / PARTIAL CREATE | ENRICH |
|---|---|---|
| `author` | write it from the sources when the class routes to it; otherwise a stub: `*[Awaiting source material.]*` | add what the new source supports, keep what is there |
| `placeholder` | the heading plus its `placeholder` text, verbatim | leave as it is |
| `enricher` | the heading only | leave as it is |

Class routing: `sections: all` → every author section; a list → those headings; `best-fit`
→ the sections the document's content supports. PARTIAL CREATE writes every heading but
authors only routed sections. A `required: false` section with nothing to say is omitted.

Ground every authored sentence in a cited source and end each authored passage with
`*Source: [<document title>](<path under references/processed/documents/>), retrieved
<YYYY-MM-DD>*`. Expand a term only where a source expands it; a reference-data hit is
evidence for gap judging, not source text.

## 4. Frontmatter

CREATE and PARTIAL CREATE write, in this order:

- `type` — the concept type's OKF `type`, exactly;
- `title`, `description` (one sentence from the sources);
- `tags` — the type's `tags`, placeholders filled, in order;
- `status: draft`;
- `generated: {by: archivist-author/1, at: <ISO-8601 UTC now>}`;
- `sources` — one `{resource, title}` per cited document;
- each `fields` entry from its `from` rule; a `required` field with no value stops the
  write (report it).

ENRICH preserves every existing key, appends to `sources`, and refreshes `generated`.
Nobody but its owner writes `okfx_gaps`, `okfx_confidence` or `verified`.

## 5. Companions

For each `companions` entry: one file per item in the parent's `for_each` list, at `path`
relative to the parent's directory (`{item}` is the item as listed, `{item_lower}`
lowercased). Its frontmatter is the companion type's OKF `type`, `title: <item>`,
`status: draft`, plus what its `guidance` says. Leave an existing companion file unchanged.

Done when type, structure, path and mode are known, headings follow the structure, each
section matches its owner's rule, and frontmatter follows §4.
