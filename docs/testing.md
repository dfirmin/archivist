# Testing

Three layers, each answering a different question:

| Layer | Answers | When |
|---|---|---|
| Offline tests (`pytest`) | do the deterministic guardrails still hold? | every change; CI runs them on every PR |
| Live runs on a test target | do the agents produce the right concepts from real documents? | every agent, skill, dispatch, contract-kind or runner change |
| Upgrade check | does an existing target still validate and run on a newer engine? | before merging an upgrade PR |

How versions, releases and pins work is in [releasing.md](releasing.md); this page assumes it.

## Setup

Native (what the examples below use):

```bash
pip install -e ".[dev]"
archivist --version          # v0.4.1.dev3+g… on unreleased code, v0.4.0 on the tag
```

Docker: the same commands through the wrappers, `./scripts/docker-run.sh <command>` for
read-only commands and `./scripts/publisher-run.sh <command>` for ones that push to GitHub.
Paths are container paths (`/workspace/<slug>`).

Model access for live runs comes from `CLAUDE_AUTH_MODE` (README → Configuration): `anthropic-api`
with `ANTHROPIC_API_KEY`, `gateway-key` for LiteLLM, `local-claude` for your own login, or
`inherit` where Claude Code is already signed in (a Claude Code cloud session). Check it first:

```bash
archivist config-check       # which endpoint and model a run will use
archivist smoke-agent        # live: claude -p answers and can spawn a sub-agent
```

A change to the runner or auth is proven live in both `anthropic-api` and `gateway-key` mode.

## Offline tests

```bash
python -m pytest -q          # or ./tests/run.sh in Docker
```

They cover the deterministic code only: auth resolution, contract loading and cross-checks,
profile and roster, the run plan, engine pinning and versions, scaffold and upgrade,
`record-gap`, `prune-gaps`, `check-concept`, the dispatch check, concept/kind scope and the
write fence. Add one test per guardrail behaviour that
shows it refusing bad input. Don't write tests that restate a prompt or mock an agent's
judgement; that is what live runs are for. The `examples/` targets double as fixtures, so keep
them valid.

The publishing workflows a scaffold seeds (`bundle-template/.github/`) are covered offline: the
script runs against local fakes of the Databricks, Confluence and Graph APIs, and a test keeps
the workflows, `secrets.yaml` and the script's required names in agreement. Nothing offline proves
a real destination. To try one, scaffold a test target, set that destination's secrets and
variables, and run its workflow with **Dry run** first, then for real.

## Test targets

Use a target that exists for testing, never a team's real knowledge repo:

- **A local copy of an example** for quick runs without GitHub:
  `cp -r examples/handbook /tmp/handbook` (the examples carry sample inbox documents).
- **A GitHub test repo** for anything that publishes (branch, PR, issues). Ours is
  `dfirmin/archivist-knowledge-01`, registered in `targets.yaml` as `archivist-knowledge-01`.
  A new one: create an empty repo, add it to `targets.yaml`, then scaffold it with the engine
  (never by hand):

  ```bash
  ARCHIVIST_PUBLISHER=1 archivist prepare-target /tmp/kb --target <slug> --engine v0.4.0
  ```

  That opens an onboarding PR with starter contracts and examples. Merge it, then replace the
  starters with the contracts you want to test.
- **A mirror of an example**, so a published run tests exactly what the example's README
  promises. `dfirmin/archivist-knowledge-example` is registered with `mirrors: warehouse`:
  onboarding seeds it with that example's contracts and inbox (slug, name and pin its own), and
  every `prepare-target --upgrade` copies them again from the engine version it moves to, so
  the repo cannot drift from the example. Change the example in the engine, never the mirror.
  Test-run PRs on a mirror stay open for review and are never merged, so `main` keeps the
  example's inbox for the next run.

**Source documents.** The engine's value is turning messy documents into structured ones, so
every live test mixes:

- well-structured documents (headings, clear steps), and messy ones (forwarded email threads,
  chat exports, meeting notes, a document amended by a later one);
- at least two subject areas (for example two teams' documents), so routing and structure
  selection are exercised, not one happy path;
- at least one case with a conflict between sources, and one with information the sources lack
  (it should become a gap, not invented text).

Put them in `sources/inbox/` on the target's `main` before the run: a pull request that only adds
inbox documents merges itself (ADR 0007).

## Testing unreleased code

Unreleased code has no tag, but every commit has a SHA, and that is what you test by. Pick the
lightest option that answers your question:

**1. Your checkout, one command (`--engine current`).** Runs the engine you are sitting in (a
feature branch, uncommitted edits included) against a target, whatever its pin says. Nothing in
the target changes.

```bash
archivist validate /tmp/kb --engine current
archivist run-conductor /tmp/kb --inbox-file sources/inbox/a.md --skip-publish --engine current
```

**2. A specific commit, one command (`--engine <sha>`).** Fetches and installs that commit
(pushed to GitHub, any branch) and runs the command on it. Good for checking a teammate's branch
or `main` without checking it out.

```bash
archivist run-conductor /tmp/kb --skip-publish --engine 7a58ebc0f1d2…   # full 40-character SHA
```

**3. Pin a test target to a commit (`--upgrade <sha>`).** For runs that publish, or several runs
over time, pin the test target itself, through the same PR flow as a release upgrade:

```bash
ARCHIVIST_PUBLISHER=1 archivist prepare-target /tmp/kb --target archivist-knowledge-01 \
  --upgrade "$(git rev-parse HEAD)"     # push the commit first
```

Merge that PR on the test target; every later command against it runs that commit. Move it to
the release with `--upgrade vX.Y.Z` once the release exists. Only test targets pin a SHA.

Note: a checkout with uncommitted edits is never a release, even on a tagged commit, so a
target pinned to that tag runs the real release, not your edits. Use `--engine current` to run
your edits.

## A full live test

1. **Fresh clone and validate** (validation runs on the target's pinned engine):

   ```bash
   ARCHIVIST_PUBLISHER=1 archivist load-target /tmp/kb --target archivist-knowledge-01
   archivist validate /tmp/kb --pipeline full
   ```

   `load-target`, remote `prepare-target` and publishing need GitHub credentials; natively that is
   `ARCHIVIST_PUBLISHER=1` with a `gh` login, in Docker `./scripts/publisher-run.sh`.

2. **One document, no publishing**, to see the agents work:

   ```bash
   archivist run-conductor /tmp/kb --inbox-file sources/inbox/<doc>.md --skip-publish
   ```

   On a target whose intake has a `mode: extract` class, a named document is planned first
   (ADR 0006): a transcript gets `[dispatch] extractor` and the run follows its extracts
   through further sessions until each has left the inbox; any other document goes on to the
   author as usual.

   Read the stream for one `[dispatch]` line per stage in run-plan order. Then inspect the
   concept under `knowledge/`, and the sub-agent transcripts (`/out/transcripts/`, or
   `CHILD_SESSION_TRANSCRIPT_DIR` when set) for any agent that behaved oddly.

3. **Check the output**:

   ```bash
   archivist check-concept knowledge/<path>.md   # frontmatter vs contracts
   ```

   and by reading: type and structure match the contracts and the author's stated reason; every
   sentence traces to a cited source; conflicts resolved to the latest source; nothing copied
   from reference data into the body; gaps recorded for what the sources lack; the document
   moved to `sources/processed/`. The per-agent checklist is the live-proof table in
   [AGENTS.md](../AGENTS.md#live-proof).

4. **The whole inbox with publishing** (`git -C /tmp/kb checkout main` and a fresh
   `load-target` first):

   ```bash
   RUN_BRANCH=archivist/run-$(date -u +%Y%m%dT%H%M%SZ) archivist run-conductor /tmp/kb
   ```

   Expect one branch, one PR, one issue per gap.

5. **Re-run the same documents** to check idempotence: the PR is reused and issues are updated,
   not duplicated. To add to an existing run's branch and PR, use the same `RUN_BRANCH` with
   `--continue-branch`.

6. **Record the proof** in `docs/live-proof/<YYYY-MM-DD>.md`: engine version or SHA, target,
   documents, concept paths, PR and issue links, what you checked, what failed and what changed.

Narrower runs: `--inbox-limit N` / `--group-limit N` cap an inbox scan. Runs on existing
concepts (ADR 0004):

```bash
archivist run-conductor /tmp/kb --pipeline gaps --concept knowledge/<path>.md      # every kind, one concept
archivist run-conductor /tmp/kb --pipeline gaps --concept all --kind <kind-id>     # one kind, every concept
archivist run-conductor /tmp/kb --pipeline rescore --concept all                   # scores only
```

Check that `okfx_gaps` entries of kinds outside `--kind` are unchanged, that the run prints
`fence okfx_gaps, okfx_confidence` (or `okfx_confidence`), and that a kind removed from the
contract disappears from `okfx_gaps` on the next gap run.

## Testing an upgrade

```bash
ARCHIVIST_PUBLISHER=1 archivist prepare-target /tmp/kb --target <slug> --upgrade v0.4.0 --no-publish
```

This validates the target on the new engine without pushing anything. Then trial a run on it
while the target's pin is unchanged:

```bash
archivist run-conductor /tmp/kb --inbox-file sources/inbox/<doc>.md --skip-publish --engine v0.4.0
```

When both look right, run the same `--upgrade` without `--no-publish` to open the upgrade PR.

## Before a release

- `main` is green in CI.
- Every agent, skill, dispatch or contract-kind change merged since the last release has live
  proof on at least two targets with different contracts, run on `main`'s commit (option 2 or
  3 above).
- The examples' contracts validate (the offline tests cover this).

Then press the release button ([releasing.md](releasing.md)).

## Troubleshooting

| Message | Meaning |
|---|---|
| `… is a development build, not a release` | You asked to pin a `.dev` version. Pin a release tag or a full commit SHA. |
| `target pins engine X; this engine is Y; handing over` | Normal: the pinned engine runs the command. |
| `handed over to engine X, but it reports Y` | The cached engine for X is not X (a broken install). Delete `~/.cache/archivist/engines/X` and retry. |
| `could not install engine X` | The tag or SHA doesn't exist on `ARCHIVIST_ENGINE_REPO`, or isn't pushed yet. |
| `already pins engine X; move it with … --upgrade` | `--engine` only sets a new target's pin. Use `--upgrade`. |
| `engine X refuses <slug>'s contracts` | The upgrade's validation failed; nothing was committed. Fix the contracts or stay on the old engine. |
