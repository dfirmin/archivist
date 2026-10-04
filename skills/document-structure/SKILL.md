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

**Authoring (choose once, record it).**

1. Concept type: the document's intake class names it (`concept_type` on the class); a class
   without one uses the intake's default `concept_type`.
2. Structure: the type's `structures` list. One entry → that structure. Several → apply the
   type's `structure_rule` to this document, reading any reference data it names, and pick
   exactly one of the listed structures.
3. Record the choice as `okfx_structure: <structure id>` in the concept's frontmatter, and
   say in your report which rule decided it.

**Any later stage (read, never re-decide).** Find the concept type whose OKF `type` equals
the concept's `type`. The structure is the concept's `okfx_structure`. Only when that field
is absent (a concept written before it existed) fall back to the type's single structure or
its `structure_rule`.

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
| `author`, required | write it from the sources when the class routes to it; otherwise a stub: `*[Awaiting source material.]*` | add what the new source supports, keep what is there |
| `author`, `required: false` | write it only when a source supports it; never a stub, never an empty heading | add it when the new source supports it |
| `placeholder` | the heading plus its `placeholder` text, verbatim | leave as it is |
| `enricher` | nothing: the enricher writes it, with any parent heading it needs | leave as it is |

A heading whose only children are enricher sections is written by the enricher too, so a concept
the enricher could not enrich has no empty headings.

Class routing: `sections: all` → every author section; a list → those headings; `best-fit`
→ the sections the document's content supports. PARTIAL CREATE writes every heading but
authors only routed sections.

Ground every authored sentence in a cited source document. Reference contracts supply
frontmatter values and lookups only: their wording (a registry description, a system's
"authoritative source" note) never becomes body text, and nothing the source does not say is
added for context. End each authored passage with
`*Source: [<document title>](<path under sources/processed/>), retrieved
<YYYY-MM-DD>*`. Expand a term only where a source expands it; a reference-data hit is
evidence for gap judging, not source text.

## 4. Frontmatter

CREATE and PARTIAL CREATE write, in this order:

- `type` — the concept type's OKF `type`, exactly;
- `title`, `description` (one sentence from the sources);
- `tags` — the type's `tags`, placeholders filled, in order;
- `status: draft`;
- `generated: {by: archivist-author/1, at: <now>}`, where `<now>` is the output of
  `date -u +%Y-%m-%dT%H:%M:%SZ` run at write time, never a date you type;
- `sources` — one `{resource, title}` per cited document;
- `okfx_structure` — the structure chosen in §1;
- each `fields` entry from its `from` rule; a `required` field with no value stops the
  write (report it).

ENRICH preserves every existing key, appends to `sources`, and refreshes `generated`. When the
new source changes something the concept states (an amendment, a correction), update that text
to the new value everywhere it appears and cite the new source there; say what changed when
the source does (for example "raised from $60 to $75, effective November 1").
Nobody but its owner writes `okfx_gaps`, `okfx_confidence` or `verified`; `okfx_structure` is
written by the author on CREATE and never changed afterwards.

## 5. Companions

For each `companions` entry: one file per item in the parent's `for_each` list, at `path`
relative to the parent's directory (`{item}` is the item as listed, `{item_lower}`
lowercased). Its frontmatter is the companion type's OKF `type`, `title: <item>`,
`status: draft`, plus what its `guidance` says. Leave an existing companion file unchanged.

Done when type, structure, path and mode are known, headings follow the structure, each
section matches its owner's rule, and frontmatter follows §4.
