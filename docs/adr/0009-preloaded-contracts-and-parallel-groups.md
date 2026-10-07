# 0009 — Contracts preloaded into agents; inbox groups in parallel

Status: proposed, 2026-10-07. Proven live on both harnesses and both test targets, publishing
included on Pi (docs/live-proof/2026-10-07.md). Both changes are harness-independent.

## Why

A full inbox ran one group at a time, and every agent opened its work by reading the same
contract files. Measured on the warehouse mirror (17 documents, 12 sessions, 1,178–1,250 s):
the author took about a fifth of the time, the gap fleet and scorer about two fifths, the
planner (re-run every session) an eighth, the conductor's own turns a fifth. No single stage
dominates, so no single-agent change makes a run much faster. Two changes do, without touching
any agent's judgement: give agents what they always read, and stop waiting for one group to
finish before starting an unrelated one.

## Decision

### 1. Contracts in the prompt (`archivist.preload`)

At install time each agent's prompt gains a section with the contract files its profile entry
`requires` or lists as `optional`, verbatim: always `contracts/target.yaml`, the built-in kinds,
the structures directory, and the reference data when `reference` is listed. The conductor gets
`gap-kinds` and `concept-types`, which its gap-fleet `before` rule reads. The section says the
files are already read. A file over 48 KB, or past 160 KB per agent, stays on disk and is listed
as not loaded. The section is identical for every spawn of an agent in a run, so prompt caching
covers it after the first. `ARCHIVIST_PRELOAD_CONTRACTS=0` turns it off.

It lives in the agent body, before the harness renders it, so Claude Code and Pi get the same
text.

**Found live:** with every registry in view, the author titled a view with no business name in
its source from the naming standards ("Claim Payment" for `CLAIM_PMT_SV`), against the intake
rule and five earlier runs. Reference data had only ever reached the author through a targeted
lookup. The section now restates the existing rule: reference data answers the lookups a
contract or the instructions call for, and its wording never becomes a title, a name or body
text. The re-run titled it `CLAIM_PMT_SV`.

### 2. Groups in parallel (`archivist.parallel`, `run-conductor --parallel N`)

For an inbox scan with `--parallel` above 1 (default 1, the serial loop, unchanged):

1. The planner runs once per round as its own session, and Python parses every group of its
   reply (`dispatch_check.parse_plan`).
2. An `extract` group runs alone first, as in the serial loop, and the round starts over, so
   extracts are planned with the rest of the inbox.
3. The other groups run N at a time, one conductor session each, told the group is already
   planned and that catalog and publishing come later. Groups are independent by construction:
   the planner puts every document about one concept in one group.
4. One finishing session catalogs and publishes each group in plan order, from each group's own
   summary (which now lists its concept paths), one commit per group.

A document a round leaves in the inbox is planned again next round, because its primary may
have been authored in the same round; left a second time, it is held for the rest of the run,
as the serial loop holds it after one try.

Conductor changes: a *planned group* mode (no planner), a *catalog and publish later* mode, a
*finishing* mode, and the `Concepts:` summary line. `knowledge-repo-git` stages one group at a
time in a finishing session.

## Deterministic steps added

- **Parsing the planner's groups** (already done for the first group; now for all).
- **Scheduling**: which group runs when, the finishing order, holding a document left twice.

No judgement moves to Python. Agents still plan, place, author, judge and catalog.

## Risks

| Risk | Handling |
|---|---|
| Two groups place onto the same concept at once (both create it) | The planner groups by concept; placement identity (ADR 0005) catches a later run. Not observed in 3 parallel runs. A post-round check that no concept path was written by two sessions is the next guardrail if it appears |
| An amendment runs in the same round as its primary | Re-planned next round (proven offline; live, the warehouse amendment has no primary and is held after round 2) |
| Rate limits with N sessions each spawning a fleet | N defaults to 1; 3 ran cleanly on both harnesses' auth |
| Preloaded text grows with a target's reference data | Per-file and per-agent caps; large data stays on disk |

## Live proof

docs/live-proof/2026-10-07.md: on Claude Code, example mirror 460 s against 1,178–1,250 s
serial and knowledge-01 373 s against 829 s; on Pi, 431 s for knowledge-01 and 864 s for the
example mirror with publishing. Outputs equal to the serial runs and baselines on both
harnesses; a blind review of every concept found no run materially worse.
