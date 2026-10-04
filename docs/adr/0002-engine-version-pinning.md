# 0002 — Targets are pinned to an engine release

Status: accepted, 2026-10-03

## Context

Agents, skills, schemas and dispatch rules change as the engine evolves. A target authored
under one engine can behave differently — or fail validation — under the next. Targets must
not change behaviour just because the engine repository moved.

## Decision

1. **The pin lives in the target**, in `contracts/target.yaml` as `engine:` (a `vX.Y.Z` tag or
   a full commit SHA), required by the schema. It travels with the contracts it was written
   for and changes only by pull request. The registry's unused `engine_version` field is removed
   so there is one source of truth.
2. **`prepare-target` writes it**: this engine's release, or `--engine`. A development build
   cannot be pinned, because it has no tag to fetch. An existing target's pin moves only
   through `prepare-target --upgrade` (amended 2026-10-04).
3. **Every target command enforces it** (`archivist.engines.enforce_pin`): on a mismatch the
   pinned release is cloned from `ARCHIVIST_ENGINE_REPO`, installed once into a venv under
   `ARCHIVIST_ENGINE_CACHE` (under a file lock), and the command is `exec`'d there with its
   `bin/` first on `PATH`, so agent-invoked tools such as `record-gap` are pinned too.
   `ARCHIVIST_ENGINE_PINNED` marks the handed-over process: it runs exactly that version or
   fails, so there are no loops and no silent fallback.
4. **One-off overrides** (`--engine vX.Y.Z`, `--engine current`) let an operator trial an upgrade
   without changing the pin.
5. **Release identity** comes from git (amended 2026-10-04, see below).

## Why deterministic

Which code runs a target is a guardrail, not a judgement: it must never vary with an agent.

## Consequences

- Pins only point to releases from v0.1.0 on; earlier commits do not understand `engine:`.
- Docker runs cache releases under `/out/engines`, so a pinned release installs once per host.
- Upgrading a target is explicit and reviewable: a PR that changes `engine:`, ideally after a
  trial run with `--engine`.

## Amendment 2026-10-04: versions from git tags

Originally the version was typed into `pyproject.toml` and `__init__.py`: a release commit set
it to `X.Y.Z`, a workflow tagged that commit, and `main` was then moved by hand to the next
`.devN`. If that last step was missed, every later commit still reported `X.Y.Z`, and an engine
built from one of them would run a target pinned `vX.Y.Z` itself, with unreleased code.

Now the version is computed by setuptools-scm, and `running_version()` reads it live with `git
describe` when the engine runs from a checkout (an editable install's recorded version goes
stale as the checkout moves). Only a clean commit carrying the tag reports the release; any other
commit reports `vX.Y.(Z+1).devN+g<sha>`, which can never equal a pin. A build without git (the
Docker image) reports `v0.0.0.dev0` unless a release build passes `ARCHIVIST_VERSION`.

Releasing is a manual `release` workflow (version typed at dispatch): it tests, tags the tip of
`main`, checks the tagged engine reports the tag, and publishes a GitHub release. Upgrading a
target is `prepare-target --upgrade <pin>`, which validates on the new engine before opening a
PR. Unreleased code is tested by commit SHA (`--engine <sha>` or a SHA pin on a test target).
