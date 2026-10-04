# Versions and releases

How engine code moves from a feature branch to a release, and from a release into a target.
For testing unreleased code before a release, see [testing.md](testing.md).

## The flow

```
feature/x ──PR──┐
feature/y ──PR──┤          (tests run on every PR)
                ▼
main: ─ A ─ B ─ C ─ D ─ E                      versions computed from git, never typed
                ▲
     Actions → release → "0.4.0"  ⇒  tag v0.4.0 on C + GitHub release
                ▼
target repo: PR "Upgrade engine to v0.4.0"     (prepare-target --upgrade v0.4.0)
```

1. **Work on a feature branch** and open a pull request into `main`. The `tests` workflow runs
   the offline tests on every PR. Merge when it is green and the change has its live proof.
2. **`main` is always unreleased code.** Merged work sits on `main` until someone decides to
   release it. Nobody edits a version number.
3. **Release by pressing a button.** In GitHub: Actions → **release** → Run workflow (branch
   `main`) → type the version, e.g. `0.4.0`. The workflow checks the version is new and newer
   than the last release, runs the tests, tags the tip of `main` as `v0.4.0`, checks the engine
   at that tag reports `v0.4.0`, and publishes a GitHub release with notes generated from the
   merged PRs. Tags are never moved or reused; a mistake is fixed by releasing the next version.
4. **Targets move only when they choose to.** Each target pins its engine in
   `contracts/target.yaml`. Releasing changes no target. Upgrading one is a pull request in the
   target repo, opened for you by `prepare-target --upgrade` (below).

## Where the version comes from

The version is computed from git tags by [setuptools-scm](https://setuptools-scm.readthedocs.io),
and the engine reads it live from git whenever it runs from a checkout:

| The code is… | It reports | Can a target pin it by version? |
|---|---|---|
| exactly the commit tagged `v0.4.0`, unmodified | `v0.4.0` | yes: `engine: v0.4.0` |
| 3 commits after `v0.4.0` (main, or a feature branch) | `v0.4.1.dev3+g1a2b3c4` | no; pin its commit SHA instead |
| the `v0.4.0` commit with uncommitted edits | `v0.4.1.dev0+g….dirty` | no |
| a build without git history (the Docker image) | `v0.0.0.dev0`, unless built with `--build-arg ARCHIVIST_VERSION=X.Y.Z` | no |

Only a clean, tagged commit can claim a release, so a pin always gets exactly the code that was
released. `archivist --version` shows what the running engine is.

## How a pin is honoured

Before any command that works on a target (`validate`, `load-target`, `prepare-workspace`,
`run-conductor`), the engine compares the target's `engine:` with itself:

- **Same** (the release tag, or the commit SHA the engine runs from) → it runs the command.
- **Different** → it clones the pinned tag or commit from `ARCHIVIST_ENGINE_REPO` (default
  this repository), installs it once into `ARCHIVIST_ENGINE_CACHE`
  (`~/.cache/archivist/engines/<pin>`), and hands the command over. Tools the agents call during
  the run (`archivist record-gap`, `archivist check-concept`) are the pinned engine's too.

`--engine <pin>` overrides the pin for one command; `--engine current` means "this engine,
whatever the pin says".

## Upgrading a target

```bash
ARCHIVIST_PUBLISHER=1 archivist prepare-target /tmp/my-target --target <slug> --upgrade v0.4.0
```

This clones the target fresh, sets `engine: v0.4.0`, refreshes the reference copies in
`examples/` from that engine, and runs `archivist validate` **on the new engine** for the
default pipeline and every pipeline the target defines. If the new engine refuses the contracts,
nothing is committed and the error says why. Otherwise it pushes the branch
`archivist/upgrade-engine-v0.4.0` and opens a PR whose description links the engine changes
(`compare/<old>...<new>`) and holds the validation output. Contracts, sources, `knowledge/`,
`index.md` and `log.md` are never touched.

- `--no-publish` stops after validation (nothing pushed); `--local` upgrades a local directory.
- The pin can be a release tag or a full commit SHA (for testing, see [testing.md](testing.md)).
- Before merging the PR, try a run on the new engine (`run-conductor … --engine v0.4.0
  --skip-publish`) if the release changed agents or skills.

`--engine` on `prepare-target` only sets the pin of a **new** target; on an existing target it
refuses and points to `--upgrade`, so a pin never moves by accident.

## Rules

- Release only when the owner asks. Agents never create tags from a session; the workflow does.
- A change that alters what contracts mean or what agents produce reaches targets only through a
  release and an upgrade PR.
- Long-lived targets pin release tags. A commit-SHA pin is for test targets and short trials.
- Contract schema changes stay readable by the release that introduced them: a target only
  moves when its pin moves.
