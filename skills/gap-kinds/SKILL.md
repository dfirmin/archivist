---
name: gap-kinds
description: >
  The target's gap-kinds contract for one kind on one concept: applicability, evidence,
  detection, origin, and the `okfx_gaps` write through `archivist record-gap`. Use when a
  gap-agent is given a kind id and a concept path.
allowed-tools: Bash, Read
---

The contract is the file `contracts/target.yaml` names under `contracts.gap-kinds`. The
engine supplies no kinds.

## Procedure

1. Read the gap-kinds contract. Take the **kind id from the kickoff**; ignore every other kind.
2. Applicability: map the concept's `type` to its concept-type id (the `concept-types`
   entry whose `type` equals it). The kind applies when `enabled` is not false and
   `applies_to` holds that id. Not applicable → record it absent (below) and report why.
3. Treat `context` as the evidence to inspect and `detection` as the binding decision list.
   Judge substance, not heading presence. When the kind lists `uses`, read those reference
   contracts the way their `guidance` says.
4. Origin: with `fixed_origin`, omit `--origin`. Otherwise choose from the kind's `origins`,
   using the meanings in the contract's `origins` map. Defaults when the map is absent:
   - `author` — a cited source or reference contract holds the information, but the concept
     omitted or misstated it;
   - `documentation` — the sources lack it, or it needs an owner's decision.
5. Write a specific description: the failed condition and the evidence inspected. Priority
   stays on the contract; never copy it into `okfx_gaps`.

## Output (binding)

Do not edit the concept. `record-gap` holds an exclusive lock, replaces only your kind,
serializes the YAML, and rejects a kind that is unknown, disabled or not applicable and an
origin the kind does not allow. A rejection means re-read the contract, not retry with
different wording.

Present:

```bash
archivist record-gap "<concept>" --kind <kind id> --origin <origin> \
  --description "Requirements names no approval limit, although the cited policy states one in section 4."
```

Absent:

```bash
archivist record-gap "<concept>" --kind <kind id> --absent
```

One paragraph of prose; punctuation needs no escaping. If it carries both quote characters,
write it to a file and pass `--description-file <path>` (or `-` for stdin).

Done when the command reports your kind added, updated, removed or unchanged.
