"""Inbox scans with groups in parallel (ADR 0009).

The serial loop runs one conductor session per group: plan the inbox, take the first group,
run its stages, catalog, publish, repeat. Groups are independent units by construction (the
planner puts every document about one concept in one group), so their stages can run at the
same time. What cannot is the shared bookkeeping: `log.md`, `index.md` and the git branch.

Each round:

1. **Plan once.** The planner runs as its own session; Python parses every group of its reply.
2. **Extract first.** An `extract` group runs alone, as in the serial loop (it ends its session
   and adds extracts to the inbox), and the round starts over.
3. **Stages in parallel.** Up to N groups at once, one conductor session each, told the group is
   already planned and that catalog and publishing come later.
4. **Finish in order.** One conductor session catalogs and publishes each group, in plan order,
   one commit per group, from the groups' own summaries.

No document waits for another (ADR 0011), so a document a round leaves in the inbox is a stage
that did not place it: it is planned again next round, and left a second time it is held for the
rest of the run, so a run never loops on it.

Python decides only scheduling here; every judgement stays with the agents.
"""

from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from archivist.dispatch_check import PlannedGroup, check_entry_stage_ran, parse_plan
from archivist.harness import Harness
from archivist.profile import Profile, Roster
from archivist.run_plan import PLAN_REL
from archivist.stream import StreamMonitor
from archivist.workspace import INBOX_DIR

CONDUCTOR = "conductor"
EXTRACT = "extract"


class _Prefixed:
    """A text stream that prefixes every line, so parallel sessions stay readable."""

    _lock = threading.Lock()

    def __init__(self, stream, prefix: str) -> None:  # type: ignore[no-untyped-def]
        self._stream, self._prefix, self._buffer = stream, prefix, ""

    def write(self, text: str) -> int:
        self._buffer += text
        *lines, self._buffer = self._buffer.split("\n")
        if lines:
            with self._lock:
                for line in lines:
                    self._stream.write(f"{self._prefix}{line}\n")
                self._stream.flush()
        return len(text)

    def flush(self) -> None:
        pass


@dataclass
class GroupOutcome:
    group: PlannedGroup
    code: int
    summary: str
    problem: str | None = None


@dataclass
class ParallelRun:
    workspace: Path
    harness: Harness
    env: dict[str, str]
    model: str | None
    planner_model: str | None
    agents: tuple[str, ...]
    profile: Profile
    roster: Roster
    branch: str
    skip_publish: bool
    parallel: int
    inbox_limit: int = 0
    group_limit: int = 0
    branch_pushed: bool = False
    launch: Callable[..., int] | None = None
    failures: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ kickoffs

    def _header(self, work: str) -> list[str]:
        return [
            work,
            f"Plan: `{PLAN_REL.as_posix()}` (pipeline `{self.roster.pipeline}`).",
            f"Stages: {', '.join(self.roster.stages)}. Spawn only these, in this order.",
        ]

    def _publish_line(self) -> str:
        if self.skip_publish:
            return "Publish: no. Leave git alone: no branch, commit, push, pull request or issues."
        if self.branch_pushed:
            return (
                f"Publish: yes, on branch `{self.branch}`, which an earlier session of this run already "
                "created and pushed. Check it out; do not recreate it."
            )
        return f"Publish: yes, on branch `{self.branch}`."

    def group_kickoff(self, group: PlannedGroup, *, later: bool) -> str:
        listed = "\n".join(f"- `{d}`" for d in group.documents)
        lines = self._header(
            f"Work: the planned group `{group.slug}`, already planned (do not spawn the planner):\n{listed}"
        )
        if later:
            lines.append(
                "Catalog and publish: later. Run the stages for this group, skip the catalog and "
                "publishing, leave git alone, and write the summary; a finishing session of this run "
                "does them."
            )
        else:
            lines.append(self._publish_line())
        return "Run archivist on this repository.\n\n" + "\n".join(lines) + "\n"

    def finishing_kickoff(self, outcomes: Sequence[GroupOutcome]) -> str:
        blocks = []
        for o in outcomes:
            docs = "\n".join(f"- `{d}`" for d in o.group.documents)
            blocks.append(f"### Group `{o.group.slug}`\nDocuments:\n{docs}\nIts session's summary:\n\n{o.summary.strip()}")
        work = (
            "Work: finishing. Earlier sessions of this run ran the stages for these groups. Spawn no "
            "sub-agent. For each group, in this order, catalog it (§3) and publish it (§4), from what "
            "its summary lists:\n\n" + "\n\n".join(blocks)
        )
        lines = [work, f"Plan: `{PLAN_REL.as_posix()}` (pipeline `{self.roster.pipeline}`).", self._publish_line()]
        return "Run archivist on this repository.\n\n" + "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ sessions

    def _session(self, label: str, argv: list[str], prompt: str, required: Sequence[str]) -> tuple[int, StreamMonitor]:
        from archivist.claude_runner import launch_claude

        launch = self.launch or launch_claude
        monitor = self.harness.monitor(required_agents=tuple(required), workspace=self.workspace)
        monitor.out = _Prefixed(sys.stdout, f"[{label}] ")
        monitor.err = _Prefixed(sys.stderr, f"[{label}] ")
        started = time.monotonic()
        code = launch(argv, env=self.env, cwd=self.workspace, prompt=prompt, monitor=monitor)
        print(f"[timing] {label} {time.monotonic() - started:.1f}s", flush=True)
        try:
            monitor.write_transcripts(self.workspace)
        except OSError as err:
            print(f"[warn] transcripts not written for {label}: {err}", file=sys.stderr)
        return code, monitor

    def conductor(self, label: str, prompt: str) -> tuple[int, StreamMonitor]:
        argv = self.harness.argv(model=self.model, workspace=self.workspace, agent=CONDUCTOR)
        return self._session(label, argv, prompt, self.agents)

    def plan(self, held: set[str], round_no: int, limit: int) -> list[PlannedGroup]:
        scope = f"at most {limit} inbox documents." if limit else "all inbox documents."
        prompt = f"Plan the queue: {scope}"
        if held:
            prompt += "\nLeave out:\n" + "\n".join(f"- {d}" for d in sorted(held))
        argv = self.harness.argv(model=self.planner_model, workspace=self.workspace, agent=self.profile.planner)
        for attempt in (1, 2):
            code, monitor = self._session(f"plan-{round_no}" + ("-retry" if attempt == 2 else ""), argv, prompt, ())
            groups = parse_plan(monitor.final_text) if code == 0 else []
            if groups:
                return groups
        return []

    def inbox_docs(self) -> set[str]:
        return {f"{INBOX_DIR}/{p.name}" for p in (self.workspace / INBOX_DIR).glob("*.md")}

    # ---------------------------------------------------------------------- loop

    def run(self) -> int:
        held: set[str] = set()
        left_once: set[str] = set()
        groups_run = 0
        consumed = 0
        round_no = 0
        run_started = time.monotonic()
        while True:
            round_no += 1
            before = self.inbox_docs()
            pending = before - held
            if not pending:
                break
            remaining_limit = self.inbox_limit - consumed if self.inbox_limit else 0
            if self.inbox_limit and remaining_limit <= 0:
                break
            print(f"\n=== round {round_no}: {len(pending)} inbox documents ===\n", flush=True)
            groups = self.plan(held, round_no, remaining_limit)
            if not groups:
                print("[loop] the planner returned no groups; stopping", file=sys.stderr)
                break

            if groups[0].slug == EXTRACT:
                code, monitor = self.conductor(f"r{round_no}-extract", self.group_kickoff(groups[0], later=False))
                if code != 0:
                    self.failures.append(f"extract session failed (exit {code})")
                    break
                if not self.skip_publish:
                    self.branch_pushed = True
                if not (before - self.inbox_docs()):
                    print("[loop] the extraction took no inbox documents; stopping", file=sys.stderr)
                    break
                continue  # extracts join the inbox; plan again

            work = [g for g in groups if g.slug != EXTRACT]
            if self.group_limit:
                work = work[: max(0, self.group_limit - groups_run)]
            if not work:
                break
            print(f"[parallel] {len(work)} groups, {min(self.parallel, len(work))} at a time: "
                  f"{', '.join(g.slug for g in work)}", flush=True)
            wave_started = time.monotonic()

            def one(group: PlannedGroup) -> GroupOutcome:
                code, monitor = self.conductor(f"r{round_no}-{group.slug}", self.group_kickoff(group, later=True))
                problem = None if code == 0 else f"session failed (exit {code})"
                if problem is None:
                    problem = check_entry_stage_ran(monitor, self.profile, self.roster, inbox_documents=None)
                return GroupOutcome(group, code, monitor.final_text, problem)

            with ThreadPoolExecutor(max_workers=max(1, self.parallel)) as pool:
                outcomes = list(pool.map(one, work))  # plan order kept
            print(f"[timing] round {round_no} stages {time.monotonic() - wave_started:.1f}s", flush=True)
            groups_run += len(work)
            done = [o for o in outcomes if o.problem is None]
            for o in outcomes:
                if o.problem:
                    self.failures.append(f"{o.group.slug}: {o.problem}")
                    print(f"FAIL  group {o.group.slug}: {o.problem}", file=sys.stderr)

            if done:
                code, _ = self.conductor(f"r{round_no}-finish", self.finishing_kickoff(done))
                if code != 0:
                    self.failures.append(f"round {round_no} finishing session failed (exit {code})")
                    break
                if not self.skip_publish:
                    self.branch_pushed = True

            after = self.inbox_docs()
            taken = before - after
            consumed += len(taken)
            left = {d for g in work for d in g.documents} & after
            held |= left & left_once
            left_once |= left
            if left:
                print(f"[loop] left in the inbox this round: {', '.join(sorted(left))}", file=sys.stderr)
            if not taken or self.failures:
                break
            if self.group_limit and groups_run >= self.group_limit:
                break
        print(f"[timing] run {time.monotonic() - run_started:.1f}s", flush=True)
        if self.failures:
            for failure in self.failures:
                print(f"FAIL  {failure}", file=sys.stderr)
            return 1
        print(f"PASS  conductor finished ({round_no} rounds, {groups_run} groups in parallel)")
        return 0
