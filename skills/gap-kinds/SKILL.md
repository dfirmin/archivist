---
name: gap-kinds
description: >
  Applies the target's gap-kinds contract for one kind on one concept: applicability,
  evidence, detection, an evidence-bound origin, and the `okfx_gaps` write through
  `archivist record-gap`. Use when a gap-agent is given a kind id and a concept path.
allowed-tools: Bash, Read, Write, Grep
---

The contract is the file `contracts/target.yaml` names under `contracts.gap-kinds`. The
engine supplies no kinds.

## Procedure

1. Read the gap-kinds contract. Take the **kind id from the kickoff**; ignore every other kind.
2. Applicability: map the concept's `type` to its concept-type id (the `concept-types`
   entry whose `type` equals it). The kind applies when `enabled` is not false and
   `applies_to` holds that id. Not applicable → record it absent (below) and report why.
3. Presence: the concept's structure, when a kind needs it (required sections, owners), is
   the one named in its `okfx_structure`: the file `<okfx_structure>.yaml` in the directory
   `contracts.structures` names. Treat `context` as the evidence to inspect and
   `detection` as the binding decision list. Judge substance, not heading presence. When the
   kind lists `uses`, read those reference contracts the way their `guidance` says.
4. Origin, only when present. Follow these steps in order and stop at the first that decides:
   1. The kind has `fixed_origin` → omit `--origin`.
   2. The kind allows one origin → that origin.
   3. Find the source text: open every `resource` in the concept's OKF `sources` list (a
      missing path may sit under `sources/processed/` with the same file name) and search it
      for a passage that states the information the concept lacks. Only these documents
      count. A reference contract, a frontmatter value or general knowledge is not source
      text: the author may never copy those into the body, so their holding a value is not
      an author omission.
   4. A passage found → `author`. Quote it in the description, under 30 words, with its
      document path.
   5. No passage → `documentation`.

   When the contract has an `origins` map, its meanings replace the two defaults: choose the
   origin whose meaning fits the result of step 3. An origin that means "the information
   exists" still needs the quoted passage; without one, choose the origin for missing
   information.
5. Write a specific description: the failed condition, the evidence inspected and, for
   `author`, the quoted passage. Priority stays on the contract; never copy it into
   `okfx_gaps`.

## Output (binding)

Do not edit the concept. `record-gap` holds an exclusive lock, replaces only your kind,
serializes the YAML, and rejects a kind that is unknown, disabled or not applicable and an
origin the kind does not allow. A rejection means re-read the contract, not retry with
different wording.

Present, `author` origin:

```bash
archivist record-gap "<concept>" --kind <kind id> --origin author \
  --description-file /tmp/gap-<kind id>.txt
```

with the file holding, for example: `Requirements names no approval limit, although
sources/processed/travel-policy.md states one: "Trips over $2,000 need director approval."`

Present, `documentation` origin:

```bash
archivist record-gap "<concept>" --kind <kind id> --origin documentation \
  --description "The Escalation section names no contact, and none of the 2 cited sources names one."
```

Absent:

```bash
archivist record-gap "<concept>" --kind <kind id> --absent
```

A description is one paragraph of prose. When it holds a quote, write it to a file with the
Write tool or a heredoc and pass `--description-file <path>` (or `-` for stdin), so no shell
quoting is needed.

Done when the command reports your kind added, updated, removed or unchanged.
