# 0005 — Contract-declared identity for placement, and quarantine for what cannot be placed

Status: proposed, 2026-10-05 (issue #7). Accepted once proven live on two targets.

## Context

The author always produces a new concept. **document-structure** §2 asks it to search for an
existing concept first — the resolved path, or a concept of the same type "whose `title`
matches or whose list fields overlap" — and to ENRICH when one is found, but the identity key
is implicit. On `examples/warehouse` the path pattern carries `{title}`, the business name the
author extracts from the document, so the same views can resolve to `Customer Case` on one
run and `Customer Case Views` on the next, and the lookup misses. Live proof so far (wh4)
shows ENRICH within one run, where grouping hands the author both documents; it does not show
an update across runs. Two concepts for one set of views is the drift issue #7 describes.

The second problem is what happens when the author cannot place a document at all. Today it
stays in the inbox with a reason in the report. Nothing else happens: every inbox scan reads it
again, nobody is told, and the document that needs an owner's attention is indistinguishable
from one that arrived a minute ago.

What the inventory does and does not say, since it is the obvious candidate: on the warehouse
target `contracts/reference/inventory.csv` tells the author which *entities* are in scope and
which subject area each belongs to. It does not tell it document boundaries — CUSTCASE and
CUSTCASE_INCRMTL_SV are one concept because the intake `grouping` prose says so. "Does a
document for this exist" is therefore not an inventory lookup; it is a lookup over the
concepts already written, keyed by the field that identifies an instance.

## Decision

1. **A concept type may declare its identity.** New optional `identity` on a concept type:

   ```yaml
   identity:
     fields: [okfx_physical_views]   # one or more frontmatter fields
     match: any                       # any | all — how list fields are compared
   ```

   `fields` name declared `fields` of the type, or `title`. Validation resolves the names.
   `match: any` means an existing concept sharing any list item is the same instance;
   `all` means every item must match (the default for scalar fields is equality, with
   `title` compared case- and whitespace-insensitively).

2. **Placement is a lookup, then a judgement.** **document-structure** §2 becomes: resolve
   the identity values from the document and the reference data (the same step that resolves
   `fields`), then search every concept of the type under `knowledge/` for one whose identity
   matches.

   | Candidates | Outcome |
   |---|---|
   | exactly one | **update** — ENRICH that concept; `sources` is appended, never replaced |
   | none | **new** — CREATE or PARTIAL CREATE per the class `mode` |
   | more than one, or one that the intake `grouping` rule says is a different group | **quarantine** (below), with the candidate paths in the reason |

   A type without `identity` keeps today's rule (resolved path, then title) and is encouraged
   to declare one. The author records the outcome as `okfx_placement: {outcome, matched}`
   so live runs can be audited. The judgement left to the author is the grouping check and the
   identity values themselves; the lookup is a grep.

3. **Quarantine is the third disposition.** Anything the author cannot place in `knowledge/`
   goes to `quarantine/` at the bundle root (a sibling of `knowledge/` and `sources/`), never to
   `knowledge/`, and the source document moves to `sources/quarantine/`. The reasons:

   - *out of intake scope* (no inventory row, `UNKNOWN` subject area, a scope rule that says
     no) — the author writes only a frontmatter stub, since the content is not wanted as it
     stands and a draft would cost 7–10 minutes for nothing;
   - *a required field cannot be resolved* from the document and reference data — the author
     writes its best-effort draft, body included, with the field missing;
   - *ambiguous placement* (rule 2, last row) — best-effort draft.

   A quarantined file carries `status: quarantined` and
   `okfx_quarantine: {reason: <one sentence>, needs: <what would resolve it>, candidates: [...]}`.
   `needs` is written for the owner who will act on it ("an inventory row for LEGACY_FEED with
   a subject area"). The only thing that still stays in the inbox is a document whose class is
   `enrich-only` and whose primary document has not arrived: that condition is transient and
   resolves itself on a later run.

   `quarantine/README.md` is seeded by the scaffold and says what the directory is: drafts the
   engine could not place, waiting for an owner to resolve the stated need; nothing in it is
   published or indexed. The target's catalog, gap and score runs, the write fence and the
   publishing workflows all walk `knowledge/` only, so quarantine needs no exclusion logic.
   `log.md` gets a `**Quarantined**` bullet per document so the change log stays honest.

4. **Quarantine is visible.** `file-gap-issues` files one issue per quarantined document
   (title from the stub, body from `okfx_quarantine`) and closes it when the document leaves
   quarantine, as it already does for resolved gaps (ADR 0004 §7). A directory nobody is told
   about is a directory that rots.

5. **Resolution is a re-run, through `archivist requeue`.** The typical fix is a contract
   change — a reference-data row, a sharper `grouping` rule — made by a human PR. After it,
   `archivist requeue quarantine/<file>.md` moves the source back to `sources/inbox/` and
   deletes the stub or draft; the next run authors it with the fixed contracts and every
   downstream stage runs. Hand-moving a draft into `knowledge/` is not a supported path:
   `check-concept` refuses `status: quarantined` under `knowledge/`, so a moved draft fails
   validation until it has been re-authored. The librarian (#6) calls `requeue` the same way
   a person does.

6. **Dispatch.** The author's report gains a `Quarantined:` block (`<file> — <reason>`); its
   `done_when` in the profile counts a quarantined document as having left the inbox. The
   conductor dispatches no later stage for a quarantined path. The intake-planner still only
   reads: documents it lists under `Skipped:` are dispatched to the author as one final group
   so the author quarantines them with the stub (steps 1–3 only, so this is cheap).

## Deterministic steps added

- **`requeue`** — two file moves and a delete, with no judgement in them; an agent doing it
  would be cost for nothing, the same argument as `prune-gaps`.
- **`check-concept` refuses `status: quarantined` under `knowledge/`** — a guardrail on the
  one shortcut that would skip enrichment, verification, gaps and scoring.

Identity matching stays agent work: the grep is trivial, and the grouping judgement around it
is not. If a live run shows the author missing a clean identity match, the fix order from
ADR 0001 applies: sharper skill wording, then a structured field, then a deterministic lookup
with its own ADR.

## Not decided here

- **Creating on ambiguity with a `possible-duplicate` gap** (issue #7, solution B) instead of
  quarantining. It would keep in-scope knowledge live while an owner decides. Quarantine is
  chosen first because it has one disposition to prove, never produces a duplicate or a wrong
  merge, and ambiguity should be rare once a type declares `identity`. If live runs show
  owners leaving useful drafts in quarantine, an intake field choosing between the two is the
  next step, not an engine policy change.
- **A coverage report** — inventory rows (or any reference list) with no concept — falls out
  of `identity` for free and is a separate issue.
- **`split`** (part of a document enriches an existing concept, part is new): the author
  updates the matched concept and reports the remainder under `Judgement calls`; a split
  outcome waits for a live case.

## Consequences

- `examples/warehouse` declares `identity: {fields: [okfx_physical_views], match: any}` on
  `business-view-group-overview` and `identity: {fields: [okfx_subject_area]}` on
  `subject-area-overview`; `examples/handbook` and `minimal` declare `title`.
- The concept-types schema gains `identity`; a target using it must pin to the release that
  introduces it (ADR 0002).
- Scaffold adds `quarantine/README.md` and `sources/quarantine/`; the bundle README's layout
  block names them.
- Live proof: on the warehouse, a document about `LEGACY_FEED` (already `UNKNOWN` in the
  example inventory) quarantines with a stub and an issue; an attribute-notes document for
  CUSTCASE in a *second* run updates the existing overview rather than creating one; a
  `requeue` after adding the inventory row authors the quarantined document and closes its
  issue. On the handbook, a second remote-work document updates the policy, and a document
  matching two policies quarantines with both candidates named.
