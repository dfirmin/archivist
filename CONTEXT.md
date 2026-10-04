# Archivist

A contract-driven document engine. Engine-owned agents author, enrich, verify, gap and score
OKF concepts in a target knowledge repo, as that repo's contracts specify.

## Language

**Target**:
A knowledge repo registered in `targets.yaml`, laid out as an OKF bundle. It owns `contracts/`.
_Avoid_: tenant, project

**Contract**:
A file under a target's `contracts/` that states part of the *what*. Built-in kinds have an
engine schema; reference contracts are the target's own data.
_Avoid_: config, `_meta`, metadata

**Contract index**:
`contracts/target.yaml`, the one required file: slug, pipelines, and the path of every
contract the target declares.

**Contract kind**:
A built-in contract type with a schema: `concept-types`, `structures`, `intake`, `gap-kinds`,
`scoring`, `catalog`, `publishing`.

**Reference contract**:
Target-defined data (`reference:` in the index) with a `description` and `guidance` saying how
to look things up in it. An inventory, an owners list, a glossary. Agents read it through the
**target-contracts** skill; the engine never knows its shape.
_Avoid_: registry (unqualified), lookup table

**Concept**:
One OKF Markdown file under `knowledge/`; its path is its ID.
_Avoid_: overview (unless the target's concept type is called that), doc, page

**Concept type**:
An entry in `concept-types`: the OKF `type` string, path pattern, structures, tags, `okfx_`
fields, companions. `authored: true` means the author may create it from inbox documents.

**Structure**:
A file under the structures directory: the sections a concept has, in order, and who owns each
(`author`, `enricher`, `placeholder`).
_Avoid_: archetype, template

**Intake**:
The contract that scopes, groups, orders, names and classifies inbox documents and routes
each class to sections.

**Gap kind** / **Gap fleet**:
A kind in `gap-kinds`, applying to concept types by id. The fleet is one gap-agent per
applicable kind on one concept, spawned in parallel.

**Engine**:
This repo: agents, skills, profile, schemas, Python.

**Engine pin**:
`engine:` in a target's contract index: the engine release (tag or commit SHA) that target
runs on. A different engine hands the run to the pinned release. Changed only by pull request.
_Avoid_: engine_version (the old, unused registry field)

**Profile**:
`agents/profile.yaml`: coordinator, planner, each agent's `requires`/`optional` contracts and
`dispatch` rules, engine pipelines, enrichment methods.

**Pipeline**:
An ordered list of engine stage agents. Engine pipelines live in the profile; a target adds
or replaces pipelines by name in its index.

**Roster**:
What one run may spawn: the pipeline's stages, plus the planner when the run authors from the
inbox. Enforced through the conductor's `Agent(...)` allowlist.

**Run plan**:
`.claude/archivist/run-plan.yaml`, generated per run: stages in order with their dispatch
rules, contract paths, reference names, enrichment methods. The conductor follows it.

**Conductor**:
The main agent (`claude --agent conductor`). Reads the run plan, spawns stages, keeps the
catalog, owns git. Never does a stage's work.
_Avoid_: orchestrator

**Producing stage**:
The stage that creates concepts from the inbox (`produces: true`; the author). It is the
entry stage of an inbox run and drops out of a run on an existing concept.

**Author** / **Enricher** / **Verifier** / **Gap-agent** / **Scorer**:
The general stage agents. The author writes concepts from inbox documents; the enricher fills
`owner: enricher` sections with an enrichment method; the verifier restores context lost from
cited sources and stamps `verified`; a gap-agent judges one kind; the scorer writes
`okfx_confidence` from `okfx_gaps` by the scoring contract.

**Enrichment method**:
An engine capability (`code-logic`) a structure section names in `enrich.method`. The method's
skills are the how; the section says where the output goes.

**okfx_ field**:
Any concept frontmatter field OKF does not define. Target fields are declared in concept types;
`okfx_gaps` and `okfx_confidence` belong to the engine.

**Run branch**:
The one branch a publishing run works on (`RUN_BRANCH`). One run, one branch, one PR.

**Publisher mode**:
`publisher-run.sh` sets `ARCHIVIST_PUBLISHER=1`, which unlocks `load-target` and remote
`prepare-target`. Conductor runs push and file issues but do not set it.
