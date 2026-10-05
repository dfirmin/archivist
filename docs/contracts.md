# Writing contracts

A target's `contracts/` folder tells the engine *what* to produce. This guide explains each
piece, then walks through exactly how one inbox document becomes a concept. Every example is a
real file in [`examples/`](../examples), and the same examples are copied into each scaffolded
target under `examples/`.

Check any change with `archivist validate . --pipeline <name>`: it reports every problem at
once, before an agent runs.

## The pieces

| File | Decides | Needed when |
|---|---|---|
| `target.yaml` | the target's slug, its pinned engine release, its pipelines, where everything else lives | always |
| `concept-types.yaml` | each kind of document: OKF `type`, file path, allowed structures, tags, `okfx_` fields, and the `identity` that says when two documents are the same one | the author, enricher or gap-agent runs |
| `structures/*.yaml` | the sections of a document, in order, and who writes each one | the author or enricher runs |
| `intake.yaml` | which inbox documents are in scope, how they group, what class each is, and which concept type each class becomes | optional (defaults: everything in scope, one document per concept) |
| `gap-kinds.yaml` | what counts as a gap, per concept type | the gap-agent or scorer runs |
| `scoring.yaml` | how gaps become `okfx_confidence` | the scorer runs |
| `catalog.yaml` | how `index.md` groups concepts | optional |
| `publishing.yaml` | how gap issues are titled, labelled and routed | optional |
| `reference:` entries | your own data (owners, glossaries, inventories) plus how to look things up in it | optional |

Rules written in prose (`scope`, `grouping`, `structure_rule`, `from`, `guidance`) are binding for
the agents, exactly like fields. Write them as you would brief a careful colleague.

## How a document becomes a concept

```
sources/inbox/deploy-web-app.md
        │
        ▼  intake: which class is it?            → procedure-document
        ▼  the class names a concept type        → runbook
        ▼  runbook allows two structures; its structure_rule reads the document:
        │  "planned, repeatable work"            → routine-procedure
        ▼  recorded on the concept               → okfx_structure: routine-procedure
        ▼  the structure lists the sections      → When To Use, Prerequisites, Steps, …
knowledge/runbooks/Deploying the Web App.md
```

### 1. Class → concept type (routing)

The intake contract classifies each document. A class can name the concept type its documents
become; a class without one uses the intake's default `concept_type`.

```yaml
# examples/handbook/contracts/intake.yaml
classes:
  - id: policy-document
    concept_type: policy
  - id: procedure-document
    concept_type: runbook
```

A target with a single kind of document just sets `concept_type:` once and needs no classes
(see `examples/minimal`, which has no intake at all, and the scaffold's starter contracts).

### 2. Concept type → structure

A concept type lists the structures it may use.

- **One structure**: always that one. Most types look like this.
  ```yaml
  policy:
    structures: [policy]
  ```
- **Several structures**: a `structure_rule` says how to choose. Two common styles:

  *By the document's content.* Each document is judged on its own, so two documents of the same
  type can get different structures.
  ```yaml
  # examples/handbook/contracts/concept-types.yaml
  runbook:
    structures: [routine-procedure, incident-response]
    structure_rule: >-
      Use incident-response when the document is about responding to an outage, alert or other
      unplanned failure. Use routine-procedure for planned, repeatable work.
  ```
  The scaffold's starter contracts do the same with `article` vs `how-to`.

  *By looking something up.* The rule reads reference data, so everything sharing that value
  gets the same structure.
  ```yaml
  # examples/warehouse/contracts/concept-types.yaml
  subject-area-overview:
    structures: [data-subject-area, process-subject-area]
    structure_rule: Use the structure named for the subject area's archetype in owners
                    (data → data-subject-area, process → process-subject-area).
  ```

Validation guarantees every listed structure exists and that a type with several has a rule.
Choosing among them is the author agent's judgement, made once.

### 3. The choice is recorded

The author writes the chosen structure on the concept as `okfx_structure`. Every later stage —
enricher, verifier, gap-agents, scorer — reads it instead of deciding again, so all stages agree
on the document's shape. Gap kinds can use it too: `examples/handbook` only checks escalation on
`incident-response` runbooks and rollback on `routine-procedure` ones.

### 4. Structure → sections

```yaml
# examples/handbook/contracts/structures/incident-response.yaml
sections:
  - Symptoms
  - Impact
  - heading: Escalation
    description: Who to contact and when, as the source states it.
  - heading: Follow-up
    required: false              # written only when the source supports it
```

Each section has an owner: `author` (default, written from the sources), `enricher` (filled by an
engine enrichment method, such as code-logic in `examples/warehouse`), or `placeholder` (fixed
text for people to complete later). The intake class decides which author sections a given
document fills (`sections: all`, a list, or `best-fit`).

## Fields

OKF's own fields (`type`, `title`, `description`, `tags`, `sources`, `status`, `generated`,
`verified`) are used as OKF defines them. Anything else you declare on a concept type must start
with `okfx_`, and says where its value comes from:

```yaml
fields:
  okfx_team:
    required: true
    from: teams — the team the document names as owner
```

The engine owns five `okfx_` fields: `okfx_structure` and `okfx_placement` (author),
`okfx_quarantine` (author, on quarantined drafts only), `okfx_gaps` (gap-agents) and
`okfx_confidence` (scorer). Targets cannot declare them.

## Identity: update or new

Before writing, the author asks whether a concept for this document already exists. The
concept type's `identity` answers it: the fields whose values say two documents describe the
same instance.

```yaml
# examples/warehouse/contracts/concept-types.yaml
business-view-group-overview:
  identity:
    fields: [okfx_physical_views]   # any view already documented → update that group
    match: any
    guidance: Compare view names case-insensitively; a view and its _INCRMTL_ sibling are the same group.
```

The author resolves the document's identity values, finds every existing concept of the type
that shares them and then:

- exactly one match → **update** it in place (its path and title stay; sources are appended);
- no match → **new** concept;
- several matches, or one your `grouping` says is a different concept → **quarantine**.

It records the decision as `okfx_placement`. A type without `identity` is identified by
`title`, which is fragile when titles come from messy documents, so declare an identity from
fields the reference data or the document fixes (an entity name, a product code, a team plus a
task). See `examples/handbook` for `title` with matching guidance and `[title, okfx_team]`.

## Transcripts and other multi-topic documents

A meeting transcript talks about several things, and one concept comes from one group of
documents. Give such documents a class with `mode: extract` and a rule saying what to keep:

```yaml
- id: meeting-transcript
  description: A recorded meeting or call, as an exported transcript.
  mode: extract
  extract: >-
    Keep passages that define, change or question a physical view, a metric or a business
    rule, one extract per view, metric or rule. Drop scheduling, introductions and small talk.
```

Before planning, the extractor writes one extract per topic into the inbox: the passages quoted
word for word with speaker and timestamp, under a one-line `About:`. The transcript moves to
`sources/processed/`. From then on each extract is an ordinary document, placed by identity like
any other. A transcript with nothing the rule keeps is quarantined. An extract class names no
`concept_type` or `sections`. See ADR 0006.

## Quarantine

What the author cannot place goes to `quarantine/` at the repository root, not `knowledge/`:
documents out of your intake `scope` (as a frontmatter-only stub), documents whose required
field has no value (as a best-effort draft), and ambiguous placements (as a draft naming the
candidates). Each carries `status: quarantined` and `okfx_quarantine: {reason, needs,
candidates}`; its documents wait in `sources/quarantine/`; the run opens a `Quarantined: …`
issue. Nothing there is indexed, judged, scored or published.

To resolve one, make the change `needs` names (usually in your reference data or `scope`
prose), then `archivist requeue quarantine/<file>.md` and run again. Write your `scope` as a
rule ("out of scope until an owner assigns it"), not as a disposition ("stays in the inbox"):
where out-of-scope documents go is the engine's job. ADR 0005 has the reasoning.

## Reference data and gap origin

Reference data (`reference:` in `target.yaml`) fills frontmatter fields and decides scope. It
never becomes body text: the author restates only the cited source documents, and missing
information becomes a gap rather than being filled from a registry.

Gap origin follows the same line. `author` means a cited source states the missing information
and the concept dropped it; the gap-agent quotes that passage in the gap description. Anything
else, including a value only a reference contract holds, is `documentation`: an owner has to
put it in a source. Keep `detection` rules about whether a gap is present; a rule that ties
`author` to reference data contradicts the author's grounding and makes origins unstable.

## Where to look next

[`examples/README`](../bundle-template/examples-README.md) maps each feature to the example
that shows it.
