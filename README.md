# Archivist

A **contract-driven document engine**. Headless [Claude Code](https://code.claude.com) agents
author, enrich, verify, gap-check and score [OKF](https://github.com/GoogleCloudPlatform/open-knowledge-format)
concepts in a knowledge repo. The repo decides *what* to produce, through contracts; the
engine supplies *how*, through a fixed team of general-purpose agents.

```
target repo (owns the what)                 engine (owns the how)
───────────────────────────                 ─────────────────────
contracts/target.yaml   ← required          agents/profile.yaml   team, requires, dispatch, pipelines
contracts/concept-types.yaml                agents/conductor.md   main agent: follows the run plan
contracts/structures/*.yaml                 agents/intake-planner, author, enricher,
contracts/intake.yaml          optional,            verifier, gap-agent, scorer
contracts/gap-kinds.yaml       declared     skills/               target-contracts, document-structure,
contracts/scoring.yaml         as the               gap-kinds, update-catalog, code-logic method,
contracts/catalog.yaml         pipeline             git / PR / issue publishing
contracts/publishing.yaml      needs        schemas/contracts/    one JSON Schema per contract kind
contracts/reference/*  (any target data)    src/archivist/        validate, resolve, launch (thin)
knowledge/  references/  index.md  log.md
```

## How a run works

1. **Validate.** Python loads `contracts/target.yaml` and every contract it declares, checks
   syntax, schemas and cross-references, enforces the `okfx_` prefix on non-OKF fields, and
   refuses the run if the chosen pipeline's agents `require` a contract the target did not
   declare. It also refuses targets that try to ship agents or skills.
2. **Install.** Engine skills and agents are copied into `<workspace>/.claude/`. The
   conductor's `Agent` tool is narrowed to the pipeline's roster.
3. **Plan.** Python writes `.claude/archivist/run-plan.yaml`: the stages in order, each with its
   dispatch rules from the profile, plus contract and reference paths.
4. **Run.** `claude -p --agent conductor` reads the plan and carries each group of inbox
   documents through the stages, then catalogs and (optionally) publishes it. An inbox scan is
   one session per group.
5. **Guard.** The run fails if the entry stage never dispatched. Python writes a redacted
   transcript per sub-agent under `out/transcripts/`.

Agents read contracts through the **target-contracts** skill, so a target can add its own
reference data (an inventory, an owners list, a glossary) with a description and lookup
guidance, and no engine change.

## Contracts at a glance

| Kind | Decides | Required when |
|---|---|---|
| `concept-types` | OKF `type`, path pattern, structures, tags, `okfx_` fields, companions | author, enricher, gap-agent run |
| `structures/` | sections in order and who owns each (author, enricher, placeholder) | author, enricher run |
| `intake` | scope, grouping, ordering, naming, document classes and routing | never (defaults apply) |
| `gap-kinds` | the gap fleet: applies-to types, evidence, detection, origin, priority | gap-agent, scorer run |
| `scoring` | the confidence rubric | scorer runs |
| `catalog` | index grouping and log wording | never |
| `publishing` | gap issue title, labels, routing | never |
| `reference` | anything else the target wants agents to look up | never |

`examples/warehouse` reproduces a full business-view setup (inventory routing, archetype-style
structures, code-extracted logic, glossary checks) entirely as contracts. `examples/minimal` is
a policy-summary target with two contracts and an author + verifier pipeline.

## Pipelines

The engine profile defines `full`, `author-verify`, `enrich` and `gaps`. A target adds or
replaces pipelines in its index, using engine agents only:

```yaml
default_pipeline: no-code
pipelines:
  no-code: [author, verifier, gap-agent, scorer]
```

## Run

Docker is the only runtime (`colima start` if the daemon is down).

```bash
./tests/run.sh                                            # offline pytest
CLAUDE_AUTH_MODE=local-claude ./tests/smoke-claude.sh     # live: claude -p + sub-agent spawn

./scripts/docker-run.sh prepare-target --target sample --local /workspace/sample   # seed a repo
./scripts/docker-run.sh validate /workspace/sample --pipeline full                  # check contracts
./scripts/publisher-run.sh load-target --target sample /workspace/sample            # fresh clone + validate
./scripts/docker-run.sh prepare-workspace /workspace/sample                         # inspect .claude/ and the plan

CLAUDE_AUTH_MODE=local-claude ./scripts/run-conductor.sh                            # whole inbox, publish
CLAUDE_AUTH_MODE=local-claude INBOX_LIMIT=1 SKIP_PUBLISH=1 ./scripts/run-conductor.sh
CLAUDE_AUTH_MODE=local-claude SKIP_PUBLISH=1 \
  INBOX_FILE=references/inbox/documents/foo.md ./scripts/run-conductor.sh
CLAUDE_AUTH_MODE=local-claude SKIP_PUBLISH=1 PIPELINE=gaps \
  CONCEPT_FILE='knowledge/…/overview.md' ./scripts/run-conductor.sh                 # existing concept
```

`SKIP_PUBLISH=1` leaves git alone. Without it the conductor pushes one branch, opens or reuses
one pull request and files one issue per gap, so the container needs a `gh` login
(`docker-compose.github.yml` mounts the host `~/.config/gh`).

`record-gap` is the only way a gap-agent writes `okfx_gaps`:

```bash
archivist record-gap 'knowledge/…/overview.md' --kind undefined_acronym --origin author --description '…'
```

## Auth

`CLAUDE_AUTH_MODE=local-claude` mounts the host `~/.claude-code-auth` and lets Claude Code call
the local `apiKeyHelper`, so tokens refresh during long sessions. The default `gateway-key`
mode uses `LITELLM_API_KEY` from `.env`. All model traffic goes through the LiteLLM gateway.

See [`AGENTS.md`](AGENTS.md) for contributor rules, [`CONTEXT.md`](CONTEXT.md) for vocabulary
and [`docs/adr/`](docs/adr/) for decisions.
