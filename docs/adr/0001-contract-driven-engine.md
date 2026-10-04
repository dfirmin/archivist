# 0001 — Contract-driven engine, engine-owned agents

Status: accepted, 2026-10-03

## Context

The predecessor pipeline was built for one shape of output: business-view overviews of a
data warehouse. Document classes, the path layout, section routing, inventory scoping,
physical-view stubs, the type-to-level mapping for gaps and the confidence rubric were written
into agent prompts, skills and Python. Every target had to ship the same set of reference files
whether its pipeline used them or not, and targets could override engine agents and skills.

## Decision

1. **Targets own the what in `contracts/`** (renamed from `_meta/`). Only
   `contracts/target.yaml` is required. Built-in kinds — concept-types, structures, intake,
   gap-kinds, scoring, catalog, publishing — each have a JSON Schema. Anything else is a
   reference contract the target describes itself.
2. **Requirements follow the pipeline.** Each engine agent lists the contract kinds it
   `requires` in `agents/profile.yaml`; Python refuses a run whose pipeline needs an undeclared
   kind. Nothing else is mandatory.
3. **Archetypes are ordinary structures.** A concept type names one or more structures and, for
   several, a prose `structure_rule`. Section ownership (`author`, `enricher`, `placeholder`)
   replaces hard-coded placement such as a fixed code-logic subsection.
4. **General agents.** `author` and `enricher` replace the business-view specialists. Business-
   view behaviour is reproduced by contracts (`examples/warehouse`), not by engine code.
5. **The conductor follows a generated run plan.** Stage order and dispatch rules come from the
   profile (and target pipelines), not from the conductor prompt.
6. **Targets cannot define agents or skills.** They pick and order engine agents through
   `pipelines`. Python refuses `agents/`, `contracts/agents/` and `contracts/skills/` in a target.
7. **OKF is the output standard.** OKF fields are used where OKF defines them (`sources`
   replaces the old source-docs extension). Every other field carries the `okfx_` prefix;
   validation enforces it for target-declared fields. `okfx_gaps` and `okfx_confidence` stay
   engine-owned.
8. **Gap applicability is by concept type id** (`applies_to`), replacing the fixed
   `levels` enum and the three duplicated type-to-level mappings.

## Deterministic steps kept

- **Contract validation** — guardrail; cheap, and catches YAML and reference errors before any
  tokens are spent.
- **Entry-stage dispatch check** — a live run ended `result ok` without spawning the author.
- **`record-gap`** — hand-written YAML broke frontmatter on `: ` in descriptions, and fifteen
  concurrent gap-agents lost each other's entries. The command serializes and locks.

- **`check-concept`** (added 2026-10-04) — a live run on messy sources wrote an email subject
  (`FW: RE: meal limit - FINAL`) unquoted into `sources`; the colons made the frontmatter invalid
  YAML and every later stage failed on it. Agents still write frontmatter; the command reports
  invalid YAML, an unknown type, a structure the type does not allow, and missing or undeclared
  fields, and the author, verifier, enricher and scorer must fix what it lists.

Everything else — classification, scoping, grouping, structure choice, field resolution,
enrichment, verification, gap judgement, scoring, cataloguing, publishing — is agent work.

## Consequences

- A new kind of document is a new target with new contracts; the engine is unchanged.
- Prose in contracts (`guidance`, `scope`, `from`) is binding for agents but unchecked by Python.
  Live proof on at least two targets is required for author, conductor and contract-kind changes.
- If a prose rule proves unreliable live, the fix order is: sharper contract wording, then a
  structured contract field, then (with an ADR) a deterministic step.
