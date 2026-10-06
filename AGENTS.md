# AGENTS.md

Guidance for AI coding agents working in this repository. Read [`CONTEXT.md`](CONTEXT.md) for
the vocabulary before changing the layout, the run loop or a contract kind.

## What archivist is

A contract-driven document engine. A **target** (a git knowledge repo, an OKF bundle) owns the
*what* in `contracts/`: concept types, document structures, intake rules, gap kinds, scoring,
catalog and publishing conventions, and any reference data of its own. The **engine** (this
repo) owns the *how*: a fixed team of general-purpose agents and the skills they use. One
engine runs many targets without engine changes.

## The rules that shape every change

1. **Agentic first.** Judgement, authoring, enrichment, verification, gap judging and scoring
   live in agents and skills. Python prepares, validates and launches. Do not build a Python
   workflow that re-implements what an agent does or could do more flexibly.
2. **Deterministic code is for guardrails and contracts:** a contract exists, parses, satisfies
   its schema, its cross-references resolve, and the contracts a pipeline needs are declared.
   Add any other deterministic step only after a **live** failure shows an agent cannot be made
   reliable, and record the failure and the decision in `docs/adr/`. Today there are
   these: contract validation, engine pinning, the entry-stage dispatch check, `record-gap`
   and `prune-gaps` (YAML serialization under a lock), `check-concept` (frontmatter checked
   after an agent writes it, including that nothing quarantined sits in `knowledge/`), scope
   resolution for runs on existing concepts and the write fence on runs whose stages only set
   frontmatter (ADR 0004), and `requeue` (a quarantined draft's documents back to the inbox,
   ADR 0005).
3. **Contracts are flexible by default.** Only `contracts/target.yaml` is required. Every other
   contract is required only when an agent in the chosen pipeline lists it under `requires` in
   `agents/profile.yaml`. Never make a contract mandatory for every target.
4. **Domain lives in contracts, not in the engine.** No engine agent, core skill or Python
   module names a business domain (no subject areas, business views, physical views,
   warehouses). Enrichment-method skills may be technology-specific (`code-logic` reads SQL);
   that is the method, not a domain.
   Domain rules belong in a target's contract `guidance`, `scope`, `from` or reference data. A
   change that needs a domain word in the engine is a missing contract field: add the field.
5. **Targets ship contracts only.** No target agents, no target skills, no overrides. A target
   chooses and orders engine agents through `pipelines` in `contracts/target.yaml`. Python
   refuses a target with `agents/`, `contracts/agents/` or `contracts/skills/`.
6. **Targets are pinned to an engine release.** `engine:` in `contracts/target.yaml` decides
   which engine runs a target; `archivist.engines` enforces it before any target command. A
   change that alters what contracts mean or what agents produce reaches a target only through a
   release and an upgrade PR (`prepare-target --upgrade`). Versions come from git tags; never
   type a version number. Releases happen only when the owner asks, through the **release**
   workflow; never create or move tags from a session. Contract schema changes must stay
   readable by the release that introduced them. See [`docs/releasing.md`](docs/releasing.md).
7. **OKF is the output standard.** Use OKF's own frontmatter fields where OKF defines one
   (`type`, `title`, `description`, `tags`, `sources`, `generated`, `verified`, `status` …).
   Every other field starts with `okfx_`; validation enforces it. The engine owns `okfx_gaps`
   and `okfx_confidence`.

## Layout

```
agents/          engine agents (<name>.md) and profile.yaml (team, requires, dispatch, pipelines, methods)
skills/          engine skills (<name>/SKILL.md), one concept each
schemas/contracts/  JSON Schema per built-in contract kind
src/archivist/   Python: contracts, profile, engine, run plan, runner, record-gap, CLI
bundle-template/ what prepare-target seeds: OKF root files, a pinned contracts/target.yaml and
                 generic starter contracts (the engine's examples/ are copied in as reference)
                 and the publishing workflows in .github/ (seeded once, then the target's; ADR 0003),
                 plus CODEOWNERS and the inbox-drop workflow (ADR 0007)
examples/        example targets: warehouse (full business-view setup), minimal (author + verify)
tests/           offline pytest for the deterministic code
docs/            guides: contracts, testing, releasing, authoring agents and skills
docs/adr/        decisions, especially every deterministic step
```

## Adding things

| To add | Do this | Never |
|---|---|---|
| A target behaviour | a contract field, guidance, or reference data in the target | an engine branch on a target name or domain |
| A contract kind | a schema in `schemas/contracts/`, a loader entry and cross-checks in `contracts.py`, a row in the **target-contracts** skill, `requires`/`optional` on the agents that use it, a test, an example | a kind every target must ship |
| An agent | `agents/<name>.md` written per [the authoring guide](docs/authoring-agents-and-skills.md), a profile entry with `requires` and `dispatch`, live proof | an agent tied to one target |
| A skill | `skills/<name>/SKILL.md` written per [the authoring guide](docs/authoring-agents-and-skills.md), named in the `skills` of the agents that always need it, live proof | a skill for one target or one domain |
| A stage behaviour | the agent's `dispatch` in `profile.yaml` (the conductor reads it from the run plan) | stage names hard-coded in `conductor.md` |
| A stage that only sets frontmatter | `writes: [<fields>]` on its profile entry, so runs of such stages are fenced | a stage that sets fields without declaring them |
| An enrichment method | `enrichment_methods` in `profile.yaml` plus its skills; structures name it in `enrich.method` | a method that decides where its output goes (the structure does) |
| A frontmatter field | declare it in the target's concept type with the `okfx_` prefix | a non-OKF field without the prefix |

**Writing agent and skill files:** read
[`docs/authoring-agents-and-skills.md`](docs/authoring-agents-and-skills.md) before you add or
change anything in `agents/` or `skills/`. It holds the frontmatter rules, how to word a prompt
for the model it pins (Sonnet/Opus 5.x versus Haiku), one place per instruction, grounding,
and the checklist for the pull request. `.claude/` in a workspace is generated on every run;
edit `agents/` and `skills/`.

## Runtime

Everything runs **inside Docker**; use the wrappers. Prompts and skills use container paths
(`/workspace/…`, `/app/…`); a host path in a prompt or config is a defect.

```bash
./tests/run.sh                                   # offline pytest
./scripts/docker-run.sh validate /workspace/<target>
./scripts/publisher-run.sh load-target --target <slug> /workspace/<slug>
./scripts/run-conductor.sh
```

Model access is `CLAUDE_AUTH_MODE` in `.env`: `anthropic-api` (direct, `ANTHROPIC_API_KEY`),
`gateway-key` (LiteLLM or another Anthropic-compatible gateway), `local-claude` (your own
login, local dev) or `inherit` (the installed Claude Code's own auth, untouched). All of it goes through `archivist.config.resolve_auth`; never read auth
variables anywhere else, and never assume a gateway. A change to the runner or auth is proven
live in both `anthropic-api` and `gateway-key` mode. Offline tests need no auth.

## Git workflow

Every change goes on a feature branch and into `main` by pull request; the `tests` workflow
must be green. `main` is unreleased code; a release is a tag the **release** workflow creates
when the owner asks ([`docs/releasing.md`](docs/releasing.md)).

## Testing

**Read [`docs/testing.md`](docs/testing.md) before testing anything.** It covers the offline
tests, test targets and source documents, how to run unreleased code against a target
(`--engine current`, `--engine <sha>`, `prepare-target --upgrade <sha>`), the full live-test
sequence (`load-target`, `validate`, `run-conductor`, `check-concept`, publish, re-run),
upgrade checks and what to do before a release.

The short version:

- **Offline tests** cover the deterministic code, and only that: auth resolution, contract
  loading and cross-checks, profile and roster resolution, the run plan, engine pinning and
  versions, scaffold and upgrade, `record-gap` and `prune-gaps` (locking, YAML),
  `check-concept`, the dispatch check, concept/kind scope and the write fence, and the
  scaffold's inbox-drop check and repo ruleset (ADR 0007). One test per guardrail behaviour; no tests that restate a prompt, count lines in a
  skill, or mock an agent's judgement. When you add a guardrail, add the test that shows it
  refusing bad input. `examples/` targets double as fixtures: keep them valid.
- **Live tests** run on a test target (never a team's real repo) with a mix of messy and
  well-structured documents from more than one subject area.
- **Unreleased code** is tested by commit SHA or `--engine current`; never by a version number.

## Live proof

Offline tests do not prove an agent works. An agent, skill or dispatch change is done when it
has run **live** on a real inbox document against a real target, and you inspected the output.
Every agent you changed must show a `[dispatch]` line in the stream. Record on the task: the
target, the document, the concept path written, the transcripts under `out/transcripts/` you
read, and what you checked:

| Role | Must prove |
|---|---|
| author | the path, type, tags and okfx_ fields follow the target's contracts; `okfx_placement` matches what was there (an update lands on the existing concept); sections follow the structure and their owners; the document moved to `sources/processed/` and is in `sources`, or what could not be placed is a quarantined draft with its document in `sources/quarantine/`; `okfx_gaps`, `okfx_confidence`, `verified` untouched |
| extractor | one extract per topic the contract's `extract` rule keeps; every quoted line found verbatim in the original (`grep -F`); a correction quoted with what it corrects; the original moved to `sources/processed/`, or quarantined as a stub when nothing is kept |
| enricher | only `owner: enricher` sections changed; rows cite a file at a commit; clones removed |
| verifier | lost source content restored, cited, under existing headings; one `verified` entry appended; nothing else in frontmatter |
| gap-agent | one kind; the write went through `record-gap`; body unchanged; a `--kind` run touched only that kind's entry |
| scorer | `okfx_confidence` set per the scoring contract; nothing else changed |
| conductor | stages dispatched in run-plan order; the gap fleet spawned in one message; `SKIP_PUBLISH=1` leaves git alone; a publish run leaves one branch, one PR, one issue per gap, no duplicates on re-run |

Prove engine generality on at least two targets with different contracts when a change touches
the author, the conductor or a contract kind (the two examples are a minimum).

## Issue tracker

Issues live on GitHub, managed with `gh`. Triage labels: `needs-triage`, `needs-info`,
`ready-for-agent`, `ready-for-human`, `wontfix`.
