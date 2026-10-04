---
name: knowledge-repo-git
description: >
  Git publish for the knowledge repo: take the run branch from current main, stage the
  catalog paths, commit, push. Use when the kickoff says to publish.
allowed-tools: Bash, Read
---

Run from the knowledge-repo root. The remote is this checkout's `origin`. The run
branch is the one your kickoff names (`RUN_BRANCH`). Keep `https_proxy` if it is set, so
`git` reaches `github.com`. Credentials come from the environment or the `gh` login; keep
them out of output.

## 1. Branch, before any sub-agent runs

Every run starts from **current `main`**, and `main` itself receives no commits. Unless the
kickoff says an earlier session of this run pushed it (below), a remote branch with the
run's name is debris from an earlier run and is not resumed.

```bash
git fetch origin main
git checkout main
git pull --ff-only origin main
git checkout -B "$RUN_BRANCH"
```

When the kickoff says an earlier session already created and pushed the branch, continue
it instead; `main` stays untouched:

```bash
git fetch origin "$RUN_BRANCH"
git checkout "$RUN_BRANCH"
git pull --ff-only origin "$RUN_BRANCH"
```

Done when `git branch --show-current` prints the run branch.

## 2. Stage, once per group

Steps 2 and 3 run after **each group** finishes, on the same branch, so every group is its
own commit and the work reaches origin as it is done. Step 1 runs once per run.

The run's output lives in `knowledge/`, `sources/` (inbox → processed moves),
`log.md` and `index.md`. Nothing else is staged.

```bash
git add knowledge sources log.md index.md
```

`contracts/`, `okf/`, `.claude/`, `tmp/`, `AGENTS.md` and `README.md` stay unstaged:
contracts change only by human pull request, and `.claude/` is generated for the run. An empty
`git status --porcelain` means there is nothing to publish: stop here.

## 3. Commit and push

```bash
git commit -m "archivist: <the group's concept, what was authored or changed>"
git push -u origin "$RUN_BRANCH"
```

Push without force. Only the run's **first** push can meet debris: a non-fast-forward
rejection of an `archivist/*` branch on that push means the remote branch is
leftover from an earlier run that also started at `main`. Delete it and push the branch
you just created; there is no choice to make between the two histories:

```bash
git push origin --delete "$RUN_BRANCH"
git push -u origin "$RUN_BRANCH"
```

A rejection on a later push, or on any other branch name, stops the publish; leave that
remote branch alone and report it.
When credentials are missing, report that a token or `gh` login is absent.

Done when `git ls-remote --heads origin "$RUN_BRANCH"` lists the branch.
