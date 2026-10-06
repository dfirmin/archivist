# 0007 — Inbox drops merge without review; the scaffold applies the repo setup a target needs

Status: accepted, 2026-10-06. Inbox drops proven live on both test targets; the ruleset is
proven offline only (see Live proof).

## Context

Getting a document into a target meant a pull request someone reviewed. The review adds nothing:
a reviewer approving "add 2026-10-02-dw-office-hours.vtt" does not read an hour of transcript,
nothing in `sources/inbox/` is published or indexed, and the real review point already exists
downstream — every engine run opens a pull request a person merges, and what cannot be placed is
quarantined (ADR 0005). The friction lands where it hurts most: if SMEs, and later the librarian
(#6), must wait on a reviewer to drop a document, the inbox stays empty.

Contracts are the opposite case. They are binding rules for every agent, and a change to one
must be reviewed.

GitHub cannot express "pull requests on main, except under `sources/inbox/`" with branch
protection alone: rules are per branch, not per path. And until now the scaffold only wrote
files; the protection a target relied on was whatever its owner set by hand, if anything.

## Decision

1. **An inbox drop is a pull request that only adds files directly under `sources/inbox/`.**
   It is merged without a review when its author has write access, every file has an accepted
   extension and none is over the size limit (repository variables
   `ARCHIVIST_INBOX_EXTENSIONS`, default `.md,.txt`; `ARCHIVIST_INBOX_MAX_KB`, default 1024).
   A drop that breaks a rule fails its check and says why in one comment on the pull request.
   Anything else — a contract change, a mix of inbox and other files, an engine run's pull
   request — is not a drop and waits for review as before. A drop is still a pull request, so
   provenance (who added what, when) stays in history; GitHub's web upload opens one in two clicks.

2. **Review is required through code owners, not an approval count.** The scaffold seeds
   `.github/CODEOWNERS` that owns every path (`*`) except `/sources/inbox/`, which has no owner.
   The engine's ruleset requires a pull request and a code owner's review, with zero required
   approvals. A pull request that touches only unowned files needs no review, so the workflow
   token can merge a drop with no bypass; everything else needs an owner. Owners come from
   `owners:` on the target in `targets.yaml`, else the person who runs the scaffold.

3. **The check runs on `pull_request_target`.** `.github/workflows/inbox.yml` and
   `.github/archivist/inbox.py` run as they are on the default branch, check out only the base
   branch's `.github/archivist/`, and read the pull request through the REST API. A pull request
   cannot change the rules it is judged by. The merge is pinned to the head SHA that was checked.

4. **The scaffold applies the settings a target needs, where it can.** On every remote
   `prepare-target` (whether or not files changed) and upgrade, the engine creates or replaces one
   ruleset named `archivist` on the default branch: pull request with code owner review, no force
   push, no deletion, repository admins may bypass. It owns that ruleset by name and touches
   nothing else in the repo's settings; a team that wants more (approvals, status checks) adds its
   own ruleset, and GitHub applies the strictest. It also checks that Actions is enabled. What it
   cannot apply (no admin rights, an organization policy, a network that blocks the API) is
   reported as `TODO` with what to set by hand; it never fails the scaffold.

5. **Seeded once, then the target's.** `CODEOWNERS`, `inbox.yml` and `inbox.py` follow ADR 0003:
   written when missing — by `prepare-target` and by an upgrade, so existing targets receive them
   — and never overwritten. The ruleset is the exception: it is re-applied every time, because a
   setting someone changed by hand has no pull request to show for it.

## Why deterministic

Merging a drop is a check of paths, statuses, extensions and sizes with one right answer, run in
CI outside any engine run; repo settings are configuration. Neither has judgement to hand to an
agent. The guardrails are tests: the decision table, the merge pinned to the checked SHA, the
workflow never running the pull request's code, the ruleset replaced by name, and a refused
setting reported rather than raised.

## Not decided here

- **Drops without a pull request** (a direct push, a drop folder, a Teams upload). A
  librarian or an ingest workflow would open a drop pull request itself; that is #6's to build.
- **Status checks on contract pull requests** (`archivist validate` in CI). It needs the pinned
  engine on the runner; a separate change.
- **Deleting what the engine applied** when a target leaves archivist. Delete the `archivist`
  ruleset by hand.

## Consequences

- An inbox drop needs no reviewer; an engine run picks it up on its next scan. The engine's own
  pull requests, contract changes and anything outside the inbox need a code owner.
- A sole owner cannot approve their own pull request; as an admin they merge with the ruleset's
  bypass. Teams name a group in `owners:` instead.
- The token that scaffolds needs admin on the target for the ruleset, besides the `workflow`
  scope ADR 0003 already requires. Without admin the scaffold still writes the files and reports
  the ruleset as `TODO`.
- This is GitHub-specific, as publishing is (ADR 0003). The bundle itself stays
  platform-neutral.

## Live proof

`docs/live-proof/2026-10-06.md`. On both test targets `prepare-target` seeded the three files in
the onboarding pull request; on `archivist-knowledge-01` an inbox-only drop merged itself and its
branch was deleted, a mixed pull request and a `.github` change were left for review, and a drop
with a disallowed file failed with a comment naming it; on the mirror a drop of an `.xlsx` failed
the same way. A second `prepare-target` wrote nothing and opened no pull request. The proving
session's network refused the rulesets and Actions APIs, so both settings came back `TODO`, as
designed: applying the ruleset is proven offline only, and the first scaffold run with admin
rights is its live proof.
