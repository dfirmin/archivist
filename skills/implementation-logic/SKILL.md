---
name: implementation-logic
description: >
  Extracts filter predicates, join semantics, derived fields and source-system divergences
  from SQL/ETL code and writes them into the concept section the structure assigns to the
  code-logic method. Use after source-code-locator has mapped the entities to files.
allowed-tools: Bash, Read, Edit
---

Read the located files and record what the **code** does that a consumer must know.
Every row is **grounded**: a located file states it. A category the code does not
support gets no table.

## 1. Extract four categories

Discover column and table names by reading the SQL; the patterns repeat across domains.

| Category | Look for | Capture per row |
|---|---|---|
| **Filter Predicates & Discriminators** | `WHERE` / `ON` filters on status, type, flag and source-system columns (`IN (...)`, `= 'X'`) that decide which rows exist | Column, the exact value list, what it means (from a nearby `CASE`, comment or name) |
| **Key Join Semantics** | `JOIN`s that shape the business result | Target, key(s), join type, one-line purpose |
| **Derived Field Logic** | `CASE`, `COALESCE`, arithmetic, `SUBSTR`, `CAST`, window functions in the `SELECT` | Output column, the condensed rule, its caveat |
| **Source-System Divergences** | Branches conditioned on the source-system discriminator (a channel / source code) | The rule, then each source's behavior, labelled by source name |

Rules of thumb:

- A join whose `ON` has `BETWEEN eff AND term` is a **date-range window**: say so and add
  "check for fan-out".
- `QUALIFY ROW_NUMBER() ... = 1` is dedup: write "most recent row per `<key>`, ordered by
  `<column>`".
- A `CASE` with more than about ten branches becomes a pattern plus a count and two or
  three samples ("Maps 44 codes to 12 categories (sample: ...)").
- Skip joins that only attach audit columns, and purely technical filters.
- Name the discriminator column first (Filter Predicates); divergences hang off it.
  Branches on another column (line of business, product category) are Derived Field
  Logic rows; Source-System Divergences stays for source codes.

Done when each category is a set of grounded rows or recorded as empty, and every located
file was read through its final assembly statement.

## 2. Write the section

The section is the one whose `enrich.method` is `code-logic` in the concept's structure; its
heading and level come from there (a `#### Code-Extracted Logic` under `### Implementation
Logic`, for example). Create missing parent headings the structure lists, in structure order.
Text other roles wrote stays as written.

**Replace** any existing copy of the section (a stub, or an earlier run) wherever it sits:
delete it from its heading to the next heading of the same or a higher level, then write the
new one in its place, so it appears once. Sub-headings are one level below the section;
the example shows a level-4 section.

````markdown
<section heading>

> Extracted from `<repo>` @ `<short-sha>` by `archivist-enricher`.

##### Filter Predicates & Discriminators

| Column | Valid Values | Notes |
|--------|--------------|-------|
| <col> | <values> | <meaning> |

*Source: [<repo>/<path>](<repo-url>/blob/<sha>/<path>), retrieved <YYYY-MM-DD>*

##### Key Join Semantics

| Join Target | Key(s) | Type | Purpose |
|-------------|--------|------|---------|

##### Derived Field Logic

| Output Column | Formula / Rule | Caveat |
|---------------|----------------|--------|

##### Source-System Divergences

| Rule | <Source A> | <Source B> |
|------|------------|------------|
````

Each table ends with its own `*Source: ...*` line listing the files its rows came from.
The attribution line names exactly the repos that appear in those `*Source: ...*` lines.
Use the short repo name, and the repo URL without `.git` in links.

When the code differs from what the concept's text states, write the code's fact and start
that row's note with `Differs from authored text:` and the difference. The existing text
stays as it is.

Done when the section exists once with only non-empty tables, each table has its
`*Source: ...*` line, and the rest of the concept is unchanged.
