---
name: update-catalog
description: >
  Update the OKF bundle-root `log.md` (one dated line per concept created or updated) and
  rebuild the generated block of `index.md`, grouped as the target's catalog contract says.
  Use once per group, after its last stage.
allowed-tools: Bash, Read, Edit, Write, Glob, Grep
---

cwd is the bundle root. `index.md` and `log.md` are OKF reserved files: disclosure a reader
scans to decide which concept to open, not a dashboard. They live only at the bundle root.
The optional catalog contract (per **target-contracts**) shapes them; without it the
defaults below apply.

Paths are written from the bundle root with spaces percent-encoded (`Travel Policy` →
`Travel%20Policy`).

## 1. `log.md` — change history

Newest date first, `## YYYY-MM-DD` headings (`date -u +%Y-%m-%d`). Keep the `#` title;
insert today's heading under it when missing; leave older dates untouched. One bullet per
concept this group created or changed, newest first:

```markdown
## 2026-10-03
* **Creation**: [Travel Policy](/knowledge/policies/Travel%20Policy.md) — who may book travel and the approval limits.
* **Update**: [Travel Policy](/knowledge/policies/Travel%20Policy.md) — added the exceptions from the 2026 amendment.
```

**Creation** when the concept was new this run, **Update** otherwise. Apply the contract's
`log.guidance` when present. Scores and gap counts live on the concept, not here.

Done when each concept from this group has exactly one new bullet under today.

## 2. `index.md` — progressive disclosure

Frontmatter: only `okf_version: "0.2"` (add it when the file has none; add nothing else).

Rebuild the generated block: from the `# <title>` heading (contract `index.title`, default
`Concepts`) to the next `#` heading. Preserve every other section and any prose people added
outside the block.

- Listed concepts: types in `index.include`, default every `authored: true` type.
- Groups: one `## <heading>` per distinct value of `index.group_by` (default: the concept's
  type title), formatted per `index.group_heading`; omit empty groups; sort headings.
- Lines: `* [<title>](<path>) - <description>`, path without a leading slash. When
  `index.suffix_field` holds a number, append ` <Field name> <value>.` (for
  `okfx_confidence`: ` Confidence 0.85.`).

```markdown
# Policies

## Finance

* [Travel Policy](knowledge/policies/Travel%20Policy.md) - Who may book travel and the approval limits. Confidence 0.85.
```

Done when every listed concept appears once under its group and no group is empty.
