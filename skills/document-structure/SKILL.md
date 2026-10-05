---
name: document-structure
description: >
  Turns a concept type, its structure and an intake class into a concept file: placement
  (update an existing concept, write a new one, or quarantine), path, mode (CREATE, PARTIAL
  CREATE, ENRICH), headings, section ownership, source grounding, OKF and okfx_ frontmatter,
  placeholders, companions and quarantined drafts. Use when writing, enriching or validating
  a concept.
allowed-tools: Bash, Read, Write, Glob, Grep
---

Read the contracts through **target-contracts**. This skill is how they combine.

Contents: 1 Type and structure · 2 Placement, path and mode · 3 Sections and grounding ·
4 Frontmatter · 5 Companions · 6 Quarantine

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

## 2. Placement, path and mode

Placement decides whether the document updates a concept that already exists, becomes a new
one, or is quarantined. It turns on the type's `identity`: the fields whose values say two
documents describe the same instance. A type without `identity` is identified by `title`.

1. Resolve the document's identity values with the fields' `from` rules, as for any field.
2. Find the candidates: every concept under `knowledge/` with the same OKF `type` whose identity
   matches, read through the identity `guidance`. With `match: any` (the default) a list field
   matches when the two share any item; with `match: all` every identity field must be equal.
   Grep for each value, then read each hit's frontmatter to confirm its `type` and values:
   `grep -rli -- "<value>" knowledge/ --include="*.md"`. A concept written earlier in this run
   counts.
3. Place it:

| Candidates | Placement | Mode |
|---|---|---|
| Exactly one, and the intake `grouping` agrees this document belongs to it | update | **ENRICH** that concept at its own path: additive; its title and path stay as they are |
| None, and the class `mode` is `create` | new | **CREATE** |
| None, and the class `mode` is `partial` | new | **PARTIAL CREATE** |
| None, and the class `mode` is `enrich-only` | — | leave the document in the inbox: "awaiting its primary document" |
| Several, or one the `grouping` says is a different concept | quarantine | a draft per §6, every candidate path in `candidates` |

Record it on the concept as `okfx_placement: {outcome: new}` or
`okfx_placement: {outcome: update, matched: "<field>: <the value both share>"}`.

For a new concept, fill the type's `path` pattern: `{field}` placeholders take that field's
value, `{title}` the concept title. Keep spaces and case as the value has them.

## 3. Sections and grounding

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

**Grounding.** The body restates its sources; it adds nothing to them.

| Input | May supply | Never supplies |
|---|---|---|
| A cited source document (this group's inbox documents; in ENRICH also the concept's existing `sources`) | body text, quoted or restated | — |
| A reference contract (registry, owner list, glossary …) | frontmatter field values per the field's `from` rule; scope decisions | body text, a contact, name, role, channel, expansion or description |
| Your own knowledge or "context for clarity" | nothing | anything |

A section no source passage supports is an outcome, not a hole to fill: it takes its owner
rule's empty form (stub when required, nothing when `required: false`), and the gap fleet
reports it downstream. Expand a term only
where a source expands it. End each authored passage with
`*Source: [<document title>](<path under sources/processed/>), retrieved <YYYY-MM-DD>*`
(`sources/quarantine/` in a quarantined draft).

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
- `okfx_placement` — the placement from §2;
- each `fields` entry from its `from` rule; a `required` field with no value stops the
  write (report it).

ENRICH preserves every existing key, appends to `sources`, refreshes `generated` and sets
`okfx_placement` to this update. When the
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

## 6. Quarantine

A document the author cannot place goes to `quarantine/` at the bundle root, never to
`knowledge/`, so an owner can resolve it. Nothing there is indexed, judged, scored or published.

| Reason | What is written |
|---|---|
| Out of scope under the intake `scope` | a stub: frontmatter only, no body |
| A required field has no value the sources or reference data supply | the draft: CREATE rules, that field absent |
| Placement is ambiguous (§2) | the draft: CREATE rules |

- Path: `quarantine/<document file name>` for a stub, one per document. A draft takes the
  group's first document's file name, and a later document of that group joins the draft. A
  file already at the path is replaced.
- Frontmatter: as §4, with `status: quarantined` in place of `draft`, no `okfx_placement`,
  `okfx_structure` only when chosen, and a stub needs just `type` (the class's concept type),
  `title`, `status`, `generated` and `sources`. Then
  `okfx_quarantine: {reason: <one sentence>, needs: <what would resolve it>, candidates: [<paths>]}`
  (`candidates` only for ambiguous placement). `needs` is written for the owner who will act on
  it and names the change that would place the document: the reference-data entry, owner or
  contract rule that is missing, with the value the document gives.
- Each document moves to `sources/quarantine/` (`mkdir -p` it) and is listed in `sources` there.
- No companions.

`archivist check-concept` checks a draft too, and refuses `status: quarantined` anywhere but
`quarantine/`. An owner resolves a draft with `archivist requeue`, which sends its documents
back to the inbox; a draft is never moved into `knowledge/`.

Done when placement, type, structure, path and mode are known, headings follow the structure,
each section matches its owner's rule, frontmatter follows §4, and a document that could not be
placed is a quarantined draft per §6.
