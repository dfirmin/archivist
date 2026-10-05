# 0004 — Scoped gap and score runs over published concepts

Status: accepted, 2026-10-04

## Context

Gap kinds and the scoring rubric change more often than the concepts they judge. A new kind,
a reworded `detection` list or a new band should reach the published knowledge without
re-authoring it: a full run costs 7–10 minutes per concept, and the author, enricher and
verifier have nothing new to do.

ADR 0001 already lets a run skip authoring (`--concept`, with the producing stage dropping
out) and ships a `gaps` pipeline. Three things stopped that from being the answer:

- **Scope was one concept and every kind.** "Every published concept", "these three" and
  "only kind X" could not be asked for.
- **The fleet started by wiping `okfx_gaps`.** The `before` rule set `okfx_gaps: []`, so a run
  limited to one kind would have erased every other kind's verdict, and a kind whose agent
  failed lost its previous verdict.
- **Nothing stopped a gap or score run from touching the body.** In a run with no author,
  enricher or verifier, any body change is wrong, but nothing checked it.

## Decision

1. **Scope has two independent axes.** `run-conductor --concept` takes one or more
   bundle-relative concept paths, or `all` for every concept under `knowledge/` whose `type` is
   a concept type. `--kind` (repeatable) limits the gap fleet to those kind ids; without it the
   fleet is every enabled, applicable kind. `--kind` needs a pipeline with `gap-agent` and kind
   ids the gap-kinds contract holds and has enabled. The run plan carries the scope
   (`scope.kinds`); the conductor reads it like any other dispatch rule.
2. **Applicability narrows the concept list.** With `--kind`, a concept none of whose
   in-scope kinds applies to its type (the same `applies_to` check `record-gap` makes) is
   skipped and reported. An empty selection is a clean exit. This is contract resolution, not
   judgement.
3. **Pipelines.** `gaps: [gap-agent, scorer]` stays (re-judge, then re-score). `rescore:
   [scorer]` is added for a scoring-contract change. The scorer always scores the whole
   concept: confidence is a judgement over every gap, so `--kind` never narrows it.
4. **Verdicts are replaced per kind, never wiped.** The fleet's `before` rule runs
   `archivist prune-gaps <concept>` instead of setting `okfx_gaps: []`. `prune-gaps` removes
   entries whose kind is no longer in the contract, is disabled, or no longer applies to the
   concept's type, and writes `okfx_gaps: []` when the field is missing. Each gap-agent then
   replaces only its kind through `record-gap`, as before. A run scoped to kind X changes only
   X's entry; a failed agent leaves its kind's previous verdict in place.
5. **Stages declare what they write; a run of writers-of-fields-only is fenced.** A stage
   agent may list `writes:` in `agents/profile.yaml` (`gap-agent: [okfx_gaps]`, `scorer:
   [okfx_confidence]`). When every stage of a run declares `writes`, Python snapshots
   `knowledge/` before each conductor session and fails the run if any concept's body changed,
   any frontmatter field outside the union of `writes` changed, or a concept outside the
   session's scope changed at all. Stages without `writes` (author, enricher, verifier) leave
   the fence off.
6. **Sessions are batched.** A scoped run lists its concepts in the kickoff, at most
   `--concept-batch` (default 10) per conductor session; later sessions continue the first
   session's branch and pull request, like an inbox scan.
7. **Resolved gaps close their issues.** When a published run leaves no entry for a kind that
   applies to a concept, `file-gap-issues` closes the open issue with that kind's title. A
   regap that clears a gap no longer leaves its issue open.

## Deterministic steps added

- **`prune-gaps`** — removing an entry for a kind the contract no longer has is a lookup with
  one right answer, and spawning an agent per removed kind per concept would be cost with no
  judgement in it. It runs under the same lock as `record-gap`.
- **The write fence** — a guardrail on agent output, like `check-concept`. Without it a gap or
  score run over every published concept could rewrite bodies across the corpus unnoticed.
  The fence reports after a session, so on a publishing run the pull request is already open;
  it is never merged automatically, and the failed run says which concepts to inspect.

## Not decided here

- **A `stale` selector** (per-kind contract fingerprints on `okfx_gaps` entries, selecting only
  concepts judged under an older kind) is deferred. `--concept all --kind <id>` covers the
  cases in view; a fingerprint is another deterministic step and needs its own live reason.
- **Resolution state on gaps.** Gap entries carry no human resolution; that lives on the
  GitHub issue.

## Consequences

- A gap-kinds or scoring change reaches the knowledge base with
  `--pipeline gaps --concept all [--kind …]` or `--pipeline rescore --concept all`, without
  re-authoring.
- A full run now re-judges kind by kind instead of from an empty list; its result is the same
  once every kind returns.
- New stage agents that only set frontmatter should declare `writes` to get the fence.
- Live proof for this change: one kind on one concept, one kind on every concept, and a
  rescore of every concept, on two targets.
