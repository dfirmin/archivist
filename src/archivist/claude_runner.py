"""Headless runner: load the workspace, then hand the run to the conductor.

One primitive does the work: a headless session running *as* the conductor — on Claude Code
``claude -p --agent conductor --output-format stream-json``, on Pi ``pi --mode json -p`` with
the engine extension (ADR 0008; ``ARCHIVIST_HARNESS`` chooses, see ``archivist.harness``).
The conductor is an engine agent running as the main thread. Python validates the target's
contracts for the chosen pipeline, installs the engine's skills and agents for the harness,
writes the run plan, states the job in a short kickoff, launches the session, checks that the
entry stage ran, and records transcripts.

Docker is the isolation boundary, so sessions run with permissions bypassed.
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from archivist.agents import engine_agents_root, parse_agent
from archivist.config import AuthConfig, ConfigError, resolve_auth
from archivist.dispatch_check import (
    check_entry_stage_ran,
    first_group_documents,
    planned_groups,
    planner_gave_up,
)
from archivist.engine import Engine, ResolvedRun, load_engine, resolve_run
from archivist.errors import ArchivistError, DefinitionError
from archivist.preload import with_contracts
from archivist.profile import fenced_fields
from archivist.record_gap import prune_gaps
from archivist.run_plan import PLAN_REL, build_run_plan, write_run_plan
from archivist.harness import AGENTS_DIR_REL, SKILLS_DIR_REL, ClaudeCodeHarness, Harness, get_harness
from archivist.scope import GAP_STAGE, ScopeError, batches, bundle_file, fence_violations, select, snapshot
from archivist.stream import StreamMonitor
from archivist.workspace import INBOX_DIR, PROCESSED_DIR

CONDUCTOR = "conductor"
SMOKE_AGENT = "smoke"
DEFAULT_SMOKE_TOKEN = "SMOKE_OK"
DEFAULT_PROMPT = f"Reply with exactly the token {DEFAULT_SMOKE_TOKEN} and nothing else."
PRELOAD_ENV = "ARCHIVIST_PRELOAD_CONTRACTS"  # 0 turns the contract preload off (comparison runs)

# A session that prints nothing for this long is hung; one that runs this long is runaway.
IDLE_TIMEOUT_S = 1200.0
SESSION_TIMEOUT_S = 7200.0

__all__ = ["AGENTS_DIR_REL", "SKILLS_DIR_REL"]


# --------------------------------------------------------------------------- auth / env


def _resolve_run_env(base_env: dict[str, str]) -> tuple[dict[str, str], str | None, AuthConfig] | None:
    """Print the auth line and return (env for the session, default model, auth); None after a failure."""
    try:
        auth = resolve_auth(base_env)
    except ConfigError as err:
        print(f"FAIL  {err}", file=sys.stderr)
        return None
    print(auth.describe())
    return auth.apply(base_env), auth.model, auth


def _harness() -> Harness | None:
    try:
        return get_harness()
    except ConfigError as err:
        print(f"FAIL  {err}", file=sys.stderr)
        return None


# ----------------------------------------------------------------------- workspace load


@dataclass(frozen=True, slots=True)
class PreparedWorkspace:
    run: ResolvedRun
    skills: tuple[str, ...]
    agents: tuple[str, ...]
    plan: Path


def install_engine(
    workspace: Path,
    engine: Engine,
    *,
    spawnable: tuple[str, ...],
    harness: Harness | None = None,
) -> tuple[str, ...]:
    """Install engine skills and agents where the harness finds them (``<workspace>/.claude/``)."""
    return (harness or ClaudeCodeHarness()).install(workspace, engine, spawnable=spawnable)


def prepare_agent_workspace(
    workspace: Path,
    *,
    pipeline: str | None = None,
    authoring: bool | None = None,
    kinds: Sequence[str] | None = None,
    harness: Harness | None = None,
) -> PreparedWorkspace:
    """Validate contracts for the pipeline, install the engine, write the run plan.

    Every agent is installed; the conductor's ``Agent`` tool is narrowed to the roster.
    """
    workspace = workspace.resolve()
    run = resolve_run(workspace, pipeline=pipeline, authoring=authoring)
    engine = run.engine
    if os.environ.get(PRELOAD_ENV, "1") != "0":
        # ADR 0009: each agent's prompt carries the contracts it uses, already read.
        engine = replace(engine, agents=with_contracts(engine.agents, engine.profile, run.contracts))
    agents = install_engine(workspace, engine, spawnable=run.roster.spawnable, harness=harness)
    plan = write_run_plan(
        workspace, build_run_plan(run.engine.profile, run.roster, run.contracts, kinds=kinds)
    )
    (workspace / PROCESSED_DIR).mkdir(parents=True, exist_ok=True)
    return PreparedWorkspace(run, tuple(sorted(run.engine.skills)), agents, plan)


# ------------------------------------------------------------------------ claude process


def build_claude_argv(
    *,
    model: str | None,
    agent: str | None = None,
    system_prompt: str | None = None,
) -> list[str]:
    """The Claude Code headless command. The prompt goes in on stdin, not argv."""
    return ClaudeCodeHarness().argv(model=model, workspace=Path("."), agent=agent, system_prompt=system_prompt)


def _terminate(proc: subprocess.Popen[str]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def launch_claude(
    argv: Sequence[str],
    *,
    env: dict[str, str],
    cwd: Path,
    prompt: str,
    monitor: StreamMonitor,
    idle_timeout_s: float = IDLE_TIMEOUT_S,
    total_timeout_s: float = SESSION_TIMEOUT_S,
) -> int:
    """Run one ``claude -p`` process, feeding every stdout line to ``monitor``.

    Returns 0 only for a process that exited cleanly *and* reported a successful result.
    """
    proc = subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    lines: queue.Queue[str | None] = queue.Queue()

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    assert proc.stdin is not None
    try:
        proc.stdin.write(prompt)
        proc.stdin.close()
    except BrokenPipeError:
        pass

    deadline = time.monotonic() + total_timeout_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(f"[error] session exceeded {total_timeout_s:.0f}s", file=sys.stderr)
            _terminate(proc)
            return 1
        try:
            line = lines.get(timeout=min(idle_timeout_s, remaining))
        except queue.Empty:
            print(f"[error] no output for {idle_timeout_s:.0f}s; ending session", file=sys.stderr)
            _terminate(proc)
            return 1
        if line is None:
            break
        monitor.feed(line)
        if monitor.abort_reason:
            _terminate(proc)
            return 1

    returncode = proc.wait()
    if returncode != 0:
        return returncode
    if not monitor.saw_result:
        print("[error] session ended without a result event", file=sys.stderr)
        return 1
    return 1 if monitor.is_error else 0


# ------------------------------------------------------------------------------- smoke


def run_claude_smoke(
    prompt: str,
    *,
    model: str | None,
    env: dict[str, str],
    harness: Harness | None = None,
    workspace: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Call the harness directly, with no skills or sub-agents, to prove auth and model."""
    argv = (harness or ClaudeCodeHarness()).smoke_argv(prompt, model=model, workspace=workspace or Path("."))
    return subprocess.run(
        argv,
        env=env,
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )


def run_smoke_agent(
    prompt: str = DEFAULT_PROMPT,
    *,
    expect_token: str = DEFAULT_SMOKE_TOKEN,
) -> int:
    """Prove the harness answers, then that a headless session can spawn a sub-agent."""
    agent_path = engine_agents_root() / f"{SMOKE_AGENT}.md"
    harness = _harness()
    if harness is None:
        return 1
    try:
        smoke = parse_agent(agent_path)
        engine = load_engine()
    except DefinitionError as err:
        print(f"FAIL  {err}", file=sys.stderr)
        return 1

    resolved = _resolve_run_env(dict(os.environ))
    if resolved is None:
        return 1
    base_env, default_model, auth = resolved
    model = smoke.model or default_model
    print(f"harness   {harness.name}")
    print(f"model     {model or 'Claude Code default'}")
    print(f"agent     {agent_path}")
    print("sandbox   none (Docker boundary)")
    print(f"prompt    {prompt!r}\n")

    scratch = Path(tempfile.mkdtemp(prefix="archivist-smoke-"))
    try:
        try:
            written = install_engine(scratch, engine, spawnable=(smoke.name,), harness=harness)
            env = harness.session_env(base_env, auth, scratch)
        except ArchivistError as err:
            print(f"FAIL  {err}", file=sys.stderr)
            return 1
        direct = run_claude_smoke(prompt, model=model, env=env, harness=harness, workspace=scratch)
        if direct.returncode != 0 or expect_token not in direct.stdout:
            combined = direct.stdout + direct.stderr
            if "Claude Code is not enabled" in combined:
                print(
                    "FAIL  the gateway denied the Claude Code client (a gateway access policy); "
                    "try CLAUDE_AUTH_MODE=anthropic-api with ANTHROPIC_API_KEY to rule out the gateway.",
                    file=sys.stderr,
                )
            elif direct.returncode != 0:
                print(f"FAIL  {harness.name} -p", file=sys.stderr)
            else:
                print(f"FAIL  expected {expect_token!r} in {harness.name} output", file=sys.stderr)
            sys.stderr.write(combined)
            return direct.returncode or 1
        print(f"PASS  {harness.name} -p smoke")

        supervisor = (
            f"You are a smoke-test supervisor. Spawn the `{smoke.name}` sub-agent with the "
            f"`Agent` tool (subagent_type `{smoke.name}`) using exactly this prompt: {prompt!r}. "
            "Then reply with only the text the sub-agent returned."
        )
        monitor = harness.monitor(required_agents=written, workspace=scratch)
        code = launch_claude(
            harness.argv(model=model, workspace=scratch, system_prompt=supervisor),
            env=env,
            cwd=scratch,
            prompt="Begin.",
            monitor=monitor,
        )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if code != 0:
        print("FAIL  sub-agent smoke run", file=sys.stderr)
        return code or 1
    if smoke.name not in monitor.dispatched_agents:
        print(f"FAIL  the session never spawned the {smoke.name!r} sub-agent", file=sys.stderr)
        return 1
    if expect_token not in monitor.final_text:
        print(f"FAIL  expected {expect_token!r} in sub-agent output", file=sys.stderr)
        return 1
    print("PASS  sub-agent spawn smoke")
    print(monitor.final_text)
    return 0


# ---------------------------------------------------------------------------- conductor


def run_branch(inbox_file: str | None, *, now: datetime | None = None) -> str:
    """The branch a publishing run works on: the file stem for one document, else a timestamp."""
    if inbox_file:
        stem = "".join(c if c.isalnum() else "-" for c in Path(inbox_file).stem.lower()).strip("-")
        return f"archivist/{stem or 'run'}"
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return f"archivist/run-{stamp}"


def build_kickoff(
    *,
    inbox_file: str | None = None,
    inbox_documents: Sequence[str] = (),
    inbox_limit: int = 0,
    concept_files: Sequence[str] = (),
    kinds: Sequence[str] | None = None,
    skip_publish: bool = False,
    branch: str | None = None,
    stages: tuple[str, ...] = (),
    pipeline: str | None = None,
    one_group: bool = False,
    continue_branch: bool = False,
    held: Sequence[str] = (),
) -> str:
    """The conductor's first message: the job, in a few lines. The plan holds the rest."""
    if len(concept_files) == 1:
        work = f"Work: the concept `{concept_files[0]}` already exists. Run the stages on it."
    elif concept_files:
        listed = "\n".join(f"- `{c}`" for c in concept_files)
        work = (
            f"Work: these {len(concept_files)} existing concepts, one group each, in this order. "
            f"Run the stages on each.\n{listed}"
        )
    elif inbox_documents:
        # ADR 0006 §5: on a target that extracts, named documents are planned first, so a
        # transcript named directly is split instead of reaching the author whole.
        listed = "\n".join(f"- `{d}`" for d in inbox_documents)
        work = (
            f"Work: only these inbox documents, planned first (the planner on these documents "
            f"only, never the rest of the inbox):\n{listed}"
        )
    elif inbox_file:
        work = f"Work: author the inbox document `{inbox_file}`."
    elif inbox_limit > 0:
        work = f"Work: the inbox `{INBOX_DIR}/`, at most {inbox_limit} documents."
    else:
        work = f"Work: every document in the inbox `{INBOX_DIR}/`."
    lines = [work, f"Plan: `{PLAN_REL.as_posix()}` (pipeline `{pipeline}`)."]
    if stages:
        lines.append(f"Stages: {', '.join(stages)}. Spawn only these, in this order.")
    if kinds:
        lines.append(f"Gap kinds: only {', '.join(kinds)} (the plan's `scope.kinds`).")
    if held:
        listed = "\n".join(f"- `{d}`" for d in sorted(held))
        lines.append(
            "Held: these inbox documents wait for a document not yet authored; an earlier session "
            f"took none of them. Tell the planner to leave them out of the queue:\n{listed}"
        )
    if one_group:
        lines.append(
            "Scope: one group. Plan the queue, take only the first group through every stage, "
            "publish it, then write the summary. A later session takes the next group."
        )
    if skip_publish:
        lines.append("Publish: no. Leave git alone: no branch, commit, push, pull request or issues.")
    elif continue_branch:
        lines.append(
            f"Publish: yes, on branch `{branch}`, which an earlier session of this run already "
            "created and pushed. Check it out; do not recreate it."
        )
    else:
        lines.append(f"Publish: yes, on branch `{branch}`.")
    return "Run archivist on this repository.\n\n" + "\n".join(lines) + "\n"


def run_conductor_agent(
    *,
    workspace: Path,
    inbox_file: str | None = None,
    inbox_limit: int = 0,
    group_limit: int = 0,
    concept_files: Sequence[str] = (),
    kinds: Sequence[str] = (),
    concept_batch: int = 10,
    skip_publish: bool = False,
    pipeline: str | None = None,
    continue_branch: bool = False,
    parallel: int = 1,
) -> int:
    """Load the workspace and run conductor sessions over it.

    ``continue_branch``: RUN_BRANCH names a branch an earlier run already pushed (with its PR);
    this run adds commits to it instead of starting it again from main.
    """
    workspace = workspace.resolve()
    if not workspace.is_dir():
        print(f"FAIL  workspace not found: {workspace}", file=sys.stderr)
        return 1
    harness = _harness()
    if harness is None:
        return 1
    on_concepts = bool(concept_files)
    try:
        if inbox_file and on_concepts:
            raise ScopeError("--inbox-file and --concept do not combine")
        if kinds and not on_concepts:
            raise ScopeError("--kind applies to runs on existing concepts; name them with --concept")
        if inbox_file:
            inbox_file = bundle_file(workspace, inbox_file, label="inbox file")
        prepared = prepare_agent_workspace(
            workspace, pipeline=pipeline, authoring=not on_concepts, kinds=kinds or None, harness=harness
        )
        run = prepared.run
        queue: list[tuple[str, ...]] = []
        if on_concepts:
            selection = select(
                workspace, run.contracts, concepts=concept_files, kinds=kinds, stages=run.roster.stages
            )
            for rel, reason in selection.skipped:
                print(f"skip      {rel} — {reason}")
            if not selection.concepts:
                print("PASS  nothing in scope; no session started")
                return 0
            queue = batches(selection.concepts, concept_batch)
        conductor = parse_agent(workspace / AGENTS_DIR_REL / f"{CONDUCTOR}.md")
    except ArchivistError as err:
        print(f"FAIL  {err}", file=sys.stderr)
        return 1
    roster, profile = run.roster, run.engine.profile
    fence = fenced_fields(profile, roster) if on_concepts else None

    resolved = _resolve_run_env(dict(os.environ))
    if resolved is None:
        return 1
    base_env, default_model, auth = resolved
    try:
        env = harness.session_env(base_env, auth, workspace)
    except ArchivistError as err:
        print(f"FAIL  {err}", file=sys.stderr)
        return 1
    model = conductor.model or default_model

    branch = env.get("RUN_BRANCH") or run_branch(inbox_file)
    env["RUN_BRANCH"] = branch
    scanning_inbox = not (inbox_file or on_concepts)

    # ADR 0006 §5: a named document on a target that extracts is planned, and the extracts it
    # yields are followed in later sessions until every one has left the inbox.
    named: list[str] = [inbox_file] if inbox_file and roster.extracting else []
    # Documents a session planned first and then took none of (an amendment awaiting its primary
    # document): later sessions plan without them, so one waiting group never ends a scan.
    held: set[str] = set()

    def kickoff_for(*, limit: int, continue_branch: bool, concepts: Sequence[str] = ()) -> str:
        return build_kickoff(
            inbox_file=None if named else inbox_file,
            inbox_documents=tuple(named),
            inbox_limit=limit,
            concept_files=concepts,
            kinds=kinds or None,
            skip_publish=skip_publish,
            branch=branch,
            stages=roster.stages,
            pipeline=roster.pipeline,
            one_group=scanning_inbox or bool(named),
            continue_branch=continue_branch,
            held=tuple(sorted(held)),
        )

    if continue_branch and not env.get("RUN_BRANCH"):
        print("FAIL  --continue-branch needs RUN_BRANCH set to the branch to continue", file=sys.stderr)
        return 1
    kickoff = kickoff_for(
        limit=inbox_limit,
        continue_branch=continue_branch and not skip_publish,
        concepts=queue[0] if queue else (),
    )
    print(f"workspace {workspace}")
    print(f"target    {run.contracts.slug}")
    print(f"harness   {harness.name}")
    print(f"model     {model or 'Claude Code default'}")
    print(f"pipeline  {roster.pipeline}: {', '.join(roster.stages)}")
    print(f"roster    {', '.join(roster.spawnable)}")
    print(f"contracts {', '.join(sorted(run.contracts.declared)) or 'none'}")
    if on_concepts:
        total = sum(len(b) for b in queue)
        print(f"scope     {total} concept(s) in {len(queue)} session(s); kinds: {', '.join(kinds) or 'all'}")
        print(f"fence     {', '.join(sorted(fence)) if fence is not None else 'off (a stage writes bodies)'}")
    print(f"plan      {prepared.plan.relative_to(workspace)}\n")

    if parallel > 1 and scanning_inbox:
        # ADR 0009: plan once, run groups' stages in parallel, catalog and publish in order.
        from archivist.parallel import ParallelRun

        planner = parse_agent(workspace / AGENTS_DIR_REL / f"{profile.planner}.md")
        print(f"parallel  {parallel} groups at a time\n")
        return ParallelRun(
            workspace=workspace,
            harness=harness,
            env=env,
            model=model,
            planner_model=planner.model or default_model,
            agents=prepared.agents,
            profile=profile,
            roster=roster,
            branch=branch,
            skip_publish=skip_publish,
            parallel=parallel,
            inbox_limit=inbox_limit,
            group_limit=group_limit,
            branch_pushed=continue_branch and not skip_publish,
        ).run()

    def inbox_docs() -> set[str]:
        return {f"{INBOX_DIR}/{p.name}" for p in (workspace / INBOX_DIR).glob("*.md")}

    def pending() -> set[str]:
        """The documents this run still has to take from the inbox (empty for other runs)."""
        if scanning_inbox:
            return inbox_docs() - held
        if named:
            return (set(named) & inbox_docs()) - held
        return set()

    # A named document or concept is one session. An inbox scan is one session per group: a
    # single context cannot hold a whole inbox, so each session plans the remaining inbox and
    # takes the first group; documents leaving the inbox are what advances the loop.
    consumed_total = 0
    session = 0
    planner_retries = 0
    run_started = time.monotonic()
    while True:
        session += 1
        before_docs = inbox_docs()
        waiting = pending()
        before = len(waiting) if (scanning_inbox or named) else None
        batch = queue[session - 1] if on_concepts else ()
        if session > 1 and on_concepts:
            kickoff = kickoff_for(limit=0, continue_branch=not skip_publish, concepts=batch)
            print(f"\n=== session {session}: next {len(batch)} concept(s) ===\n")
        elif session > 1 and named:
            kickoff = kickoff_for(limit=0, continue_branch=not skip_publish)
            print(f"\n=== session {session}: next group ({len(named)} named or extracted documents left) ===\n")
        elif session > 1:
            remaining = inbox_limit - consumed_total if inbox_limit else 0
            kickoff = kickoff_for(limit=remaining, continue_branch=not skip_publish)
            print(f"\n=== session {session}: next group ({before} inbox documents left) ===\n")

        if on_concepts and GAP_STAGE in roster.stages:
            # Deterministic, so not left to the conductor: a live run skipped the `before` rule's
            # prune on one concept of three (ADR 0004).
            try:
                for rel in batch:
                    for kind in prune_gaps(workspace / rel).removed:
                        print(f"prune     {rel}: {kind} (no longer in, enabled for or applicable under the contract)")
            except ArchivistError as err:
                print(f"FAIL  {err}", file=sys.stderr)
                return 1
        fence_before = snapshot(workspace) if fence is not None else None
        monitor = harness.monitor(required_agents=prepared.agents, workspace=workspace)
        session_started = time.monotonic()
        code = launch_claude(
            harness.argv(model=model, workspace=workspace, agent=CONDUCTOR),
            env=env,
            cwd=workspace,
            prompt=kickoff,
            monitor=monitor,
        )
        print(f"[timing] session {session} {time.monotonic() - session_started:.1f}s")
        try:
            written = monitor.write_transcripts(workspace)
            print(f"transcripts {len(written)} file(s)")
        except OSError as err:
            print(f"[warn] transcripts not written: {err}", file=sys.stderr)

        if code != 0:
            print("FAIL  conductor session", file=sys.stderr)
            return code or 1
        if (scanning_inbox or named) and (before or 0) > 0 and planner_gave_up(monitor, profile.planner):
            if planner_retries >= 1:
                print("FAIL  the planner twice returned no groups for a non-empty inbox", file=sys.stderr)
                return 1
            planner_retries += 1
            print("[loop] the planner returned no groups for a non-empty inbox; trying again", file=sys.stderr)
            session -= 1
            continue
        planner_retries = 0
        stalled = check_entry_stage_ran(monitor, profile, roster, inbox_documents=before)
        if stalled:
            print(f"FAIL  {stalled}", file=sys.stderr)
            return 1
        if fence_before is not None and fence is not None:
            problems = fence_violations(fence_before, snapshot(workspace), scope=batch, fields=fence)
            if problems:
                print(f"FAIL  write fence: this run may change only {', '.join(sorted(fence))}", file=sys.stderr)
                for problem in problems:
                    print(f"      - {problem}", file=sys.stderr)
                return 1
        if on_concepts:
            if session >= len(queue):
                break
            continue
        if not (scanning_inbox or named):
            break
        # Progress is which documents left the inbox, not the count: an extraction session
        # takes one document and adds several extracts (ADR 0006).
        after_docs = inbox_docs()
        taken = waiting - after_docs
        consumed_total += len(taken)
        if named:
            named = sorted((set(named) & after_docs) | (after_docs - before_docs))
        if planned_groups(monitor, profile.planner) == 0 or not pending():
            break
        if not taken:
            waiting_group = set(first_group_documents(monitor, profile.planner)) & after_docs
            if not waiting_group or waiting_group <= held:
                print("[loop] this session took no inbox documents; stopping", file=sys.stderr)
                break
            held |= waiting_group
            print(f"[loop] held for later runs: {', '.join(sorted(waiting_group))}", file=sys.stderr)
            if not pending():
                break
        if inbox_limit and consumed_total >= inbox_limit:
            break
        if group_limit and session >= group_limit:
            break
    print(f"[timing] run {time.monotonic() - run_started:.1f}s")
    print(f"PASS  conductor finished{f' ({session} sessions)' if session > 1 else ''}")
    return 0
