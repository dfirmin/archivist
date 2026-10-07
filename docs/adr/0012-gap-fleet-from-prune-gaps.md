# 0012 — `prune-gaps` prints each concept's gap fleet

Status: accepted, 2026-10-07.

## Live failure

The gap-agent's `before` rule had the conductor read the gap-kinds contract and work out each
concept's fleet: the enabled kinds whose `applies_to` holds the concept's type, narrowed to the
run plan's `scope.kinds`. In a Pi run on the warehouse mirror (2026-10-07), the conductor
concluded "No gap kind applies to subject-area-overview" (`missing_section` lists that type),
spawned no gap-agent for two concepts, and the scorer gave both 1.0 with stub sections still in
them. Every other run of the day sized that fleet correctly, but a concept that silently skips
its gap check is the worst kind of miss: nothing downstream reports it.

## Decision

Which kinds apply to a concept is a lookup, not a judgement. `archivist prune-gaps`, which the
`before` rule already runs on every concept before its fleet and which already computes
applicability to drop stale entries, now prints the fleet:

```
fleet     missing_section, undefined_acronym, …
fleet     none (no enabled kind applies to physical-view in this run)
```

The `before` rule tells the conductor to spawn exactly the kinds on that line, one gap-agent each,
in one message. `scope.kinds` comes from the run plan in the workspace, as before. The conductor
no longer reads the gap-kinds or concept-types contract, so ADR 0009 no longer preloads them into
its prompt.

## Proof

Offline: the fleet per type, a subject-area overview's fleet, disabled kinds left out, the run
plan's scope applied. Live (docs/live-proof/2026-10-07.md): on both harnesses, every authored
concept of the warehouse mirror got exactly its applicable kinds.
