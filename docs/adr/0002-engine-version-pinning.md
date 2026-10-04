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
   (`.devN`) cannot be pinned, because it has no tag to fetch.
3. **Every target command enforces it** (`archivist.engines.enforce_pin`): on a mismatch the
   pinned release is cloned from `ARCHIVIST_ENGINE_REPO`, installed once into a venv under
   `ARCHIVIST_ENGINE_CACHE` (under a file lock), and the command is `exec`'d there with its
   `bin/` first on `PATH`, so agent-invoked tools such as `record-gap` are pinned too.
   `ARCHIVIST_ENGINE_PINNED` marks the handed-over process: it runs exactly that version or
   fails, so there are no loops and no silent fallback.
4. **One-off overrides** (`--engine vX.Y.Z`, `--engine current`) let an operator trial an upgrade
   without changing the pin.
5. **Release identity** is `v` + the package version; a test keeps `pyproject.toml` and
   `__init__.py` equal. Release by tagging that commit, then move `main` to the next `.devN`.

## Why deterministic

Which code runs a target is a guardrail, not a judgement: it must never vary with an agent.

## Consequences

- Pins only point to releases from v0.1.0 on; earlier commits do not understand `engine:`.
- Docker runs cache releases under `/out/engines`, so a pinned release installs once per host.
- Upgrading a target is explicit and reviewable: a PR that changes `engine:`, ideally after a
  trial run with `--engine`.
