"""Headless Claude Code runner: load the workspace, then hand the run to the conductor.

One primitive does the work: ``claude -p --agent conductor --output-format stream-json``.
The conductor is an engine agent running as the main thread. Python validates the target's
contracts for the chosen pipeline, installs the engine's skills and agents into
``<workspace>/.claude/``, writes the run plan, states the job in a short kickoff, launches
the session, checks that the entry stage ran, and records transcripts.

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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from archivist.agents import engine_agents_root, parse_agent, write_agent_definitions
from archivist.config import (
    LOCAL_CLAUDE_AUTH,
    ConfigError,
    LiteLLMConfig,
    resolve_agent_model,
    resolve_claude_auth_mode,
    resolve_litellm_config,
)
from archivist.dispatch_check import check_entry_stage_ran, planned_groups, planner_gave_up
from archivist.engine import Engine, ResolvedRun, load_engine, resolve_run
from archivist.errors import ArchivistError, DefinitionError
from archivist.run_plan import PLAN_REL, build_run_plan, write_run_plan
from archivist.skills import install_skills, reset_path
from archivist.stream import StreamMonitor
from archivist.workspace import INBOX_DIR, PROCESSED_DIR

CONDUCTOR = "conductor"
SMOKE_AGENT = "smoke"
DEFAULT_SMOKE_TOKEN = "SMOKE_OK"
DEFAULT_PROMPT = f"Reply with exactly the token {DEFAULT_SMOKE_TOKEN} and nothing else."

# A session that prints nothing for this long is hung; one that runs this long is runaway.
IDLE_TIMEOUT_S = 1200.0
SESSION_TIMEOUT_S = 7200.0

SKILLS_DIR_REL = Path(".claude") / "skills"
AGENTS_DIR_REL = Path(".claude") / "agents"


# --------------------------------------------------------------------------- auth / env


def _prepare_env(
    base_env: dict[str, str],
    config: LiteLLMConfig | None = None,
) -> tuple[dict[str, str], str]:
    """Configure Claude Code for the gateway or the operator's own login."""
    env = dict(base_env)
    mode = resolve_claude_auth_mode(env)
    if mode == LOCAL_CLAUDE_AUTH:
        model = resolve_agent_model(env)
    else:
        resolved = config or resolve_litellm_config(environ=env)
        model = resolved.model
        env["ANTHROPIC_API_KEY"] = resolved.anthropic_api_key
        env["ANTHROPIC_BASE_URL"] = resolved.anthropic_base_url

    env["ANTHROPIC_MODEL"] = model
    env["ACT_CLAUDE_MODEL"] = model
    env.setdefault("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS", "1")
    return env, model


def _resolve_run_env(
    base_env: dict[str, str],
) -> tuple[dict[str, str], str] | None:
    """Print the auth line and return (env, default model); None after printing a failure."""
    mode = resolve_claude_auth_mode(base_env)
    config: LiteLLMConfig | None = None
    try:
        if mode == LOCAL_CLAUDE_AUTH:
            resolve_agent_model(base_env)
            print("auth      local Claude Code (apiKeyHelper)")
        else:
            config = resolve_litellm_config(environ=base_env)
            print(f"gateway   {config.anthropic_base_url}")
        return _prepare_env(base_env, config)
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


def install_engine(workspace: Path, engine: Engine, *, spawnable: tuple[str, ...]) -> tuple[str, ...]:
    """Copy engine skills and write engine agents into ``<workspace>/.claude/``."""
    install_skills(engine.skills, workspace / SKILLS_DIR_REL)
    reset_path(workspace / AGENTS_DIR_REL)
    written = write_agent_definitions(
        engine.agents,
        workspace / AGENTS_DIR_REL,
        coordinator=engine.profile.coordinator,
        spawnable=spawnable,
        available_skills=set(engine.skills),
    )
    return tuple(path.stem for path in written)


def prepare_agent_workspace(
    workspace: Path,
    *,
    pipeline: str | None = None,
    authoring: bool | None = None,
) -> PreparedWorkspace:
    """Validate contracts for the pipeline, install the engine, write the run plan.

    Every agent is installed; the conductor's ``Agent`` tool is narrowed to the roster.
    """
    workspace = workspace.resolve()
    run = resolve_run(workspace, pipeline=pipeline, authoring=authoring)
    agents = install_engine(workspace, run.engine, spawnable=run.roster.spawnable)
    plan = write_run_plan(workspace, build_run_plan(run.engine.profile, run.roster, run.contracts))
    (workspace / PROCESSED_DIR).mkdir(parents=True, exist_ok=True)
    return PreparedWorkspace(run, tuple(sorted(run.engine.skills)), agents, plan)


# ------------------------------------------------------------------------ claude process


def build_claude_argv(
    *,
    model: str,
    agent: str | None = None,
    system_prompt: str | None = None,
) -> list[str]:
    """The headless command. The prompt goes in on stdin, not argv.

    ``agent`` runs the session *as* that agent (its prompt, tools and roster); the smoke
    check has no agent file for its supervisor and passes ``system_prompt`` instead.
    """
    if (agent is None) == (system_prompt is None):
        raise ValueError("pass exactly one of agent or system_prompt")
    argv = [
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        model,
        "--permission-mode",
        "bypassPermissions",
    ]
    if agent is not None:
        return [*argv, "--agent", agent]
    assert system_prompt is not None
    return [*argv, "--append-system-prompt", system_prompt]


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
    model: str,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    """Call Claude Code directly, with no skills or sub-agents, to prove auth and model."""
    return subprocess.run(
        ["claude", "-p", prompt, "--model", model, "--output-format", "text"],
        env=env,
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
    """Prove Claude Code answers, then that a headless session can spawn a sub-agent."""
    agent_path = engine_agents_root() / f"{SMOKE_AGENT}.md"
    try:
        smoke = parse_agent(agent_path)
        engine = load_engine()
    except DefinitionError as err:
        print(f"FAIL  {err}", file=sys.stderr)
        return 1

    resolved = _resolve_run_env(dict(os.environ))
    if resolved is None:
        return 1
    env, default_model = resolved
    model = smoke.model or default_model
    print(f"model     {model}")
    print(f"agent     {agent_path}")
    print("sandbox   none (Docker boundary)")
    print(f"prompt    {prompt!r}\n")

    claude = run_claude_smoke(prompt, model=model, env=env)
    if claude.returncode != 0:
        combined = claude.stdout + claude.stderr
        if "Claude Code is not enabled" in combined:
            print(
                "FAIL  gateway denied the Claude Code client; this is an "
                "access-control policy on the gateway.",
                file=sys.stderr,
            )
        else:
            print("FAIL  claude -p", file=sys.stderr)
        sys.stderr.write(combined)
        return claude.returncode
    if expect_token not in claude.stdout:
        print(f"FAIL  expected {expect_token!r} in claude output", file=sys.stderr)
        return 1
    print("PASS  claude -p smoke")

    scratch = Path(tempfile.mkdtemp(prefix="archivist-smoke-"))
    try:
        written = install_engine(scratch, engine, spawnable=(smoke.name,))
        supervisor = (
            f"You are a smoke-test supervisor. Spawn the `{smoke.name}` sub-agent with the "
            f"`Agent` tool (subagent_type `{smoke.name}`) using exactly this prompt: {prompt!r}. "
            "Then reply with only the text the sub-agent returned."
        )
        monitor = StreamMonitor(required_agents=written)
        code = launch_claude(
            build_claude_argv(model=model, system_prompt=supervisor),
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


def _bundle_file(workspace: Path, rel: str, *, label: str) -> str:
    """A bundle-relative path to an existing file inside ``workspace``."""
    if not rel.strip() or Path(rel).is_absolute() or ".." in Path(rel).parts:
        raise ValueError(f"{label} must be a bundle-relative path without '..': {rel!r}")
    path = (workspace / rel).resolve()
    if not path.is_relative_to(workspace.resolve()):
        raise ValueError(f"{label} must resolve inside the workspace: {rel!r}")
    if not path.is_file():
        raise ValueError(f"{label} not found: {rel}")
    return Path(rel).as_posix()


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
    inbox_limit: int = 0,
    concept_file: str | None = None,
    skip_publish: bool = False,
    branch: str | None = None,
    stages: tuple[str, ...] = (),
    pipeline: str | None = None,
    one_group: bool = False,
    continue_branch: bool = False,
) -> str:
    """The conductor's first message: the job, in a few lines. The plan holds the rest."""
    if concept_file:
        work = f"Work: the concept `{concept_file}` already exists. Run the stages on it."
    elif inbox_file:
        work = f"Work: author the inbox document `{inbox_file}`."
    elif inbox_limit > 0:
        work = f"Work: the inbox `{INBOX_DIR}/`, at most {inbox_limit} documents."
    else:
        work = f"Work: every document in the inbox `{INBOX_DIR}/`."
    lines = [work, f"Plan: `{PLAN_REL.as_posix()}` (pipeline `{pipeline}`)."]
    if stages:
        lines.append(f"Stages: {', '.join(stages)}. Spawn only these, in this order.")
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
    concept_file: str | None = None,
    skip_publish: bool = False,
    pipeline: str | None = None,
) -> int:
    """Load the workspace and run conductor sessions over it."""
    workspace = workspace.resolve()
    if not workspace.is_dir():
        print(f"FAIL  workspace not found: {workspace}", file=sys.stderr)
        return 1
    try:
        if inbox_file:
            inbox_file = _bundle_file(workspace, inbox_file, label="inbox file")
        if concept_file:
            concept_file = _bundle_file(workspace, concept_file, label="concept file")
        prepared = prepare_agent_workspace(
            workspace, pipeline=pipeline, authoring=concept_file is None
        )
        conductor = parse_agent(workspace / AGENTS_DIR_REL / f"{CONDUCTOR}.md")
    except (ValueError, ArchivistError) as err:
        print(f"FAIL  {err}", file=sys.stderr)
        return 1
    run = prepared.run
    roster, profile = run.roster, run.engine.profile

    resolved = _resolve_run_env(dict(os.environ))
    if resolved is None:
        return 1
    env, default_model = resolved
    model = conductor.model or default_model

    branch = env.get("RUN_BRANCH") or run_branch(inbox_file)
    env["RUN_BRANCH"] = branch
    scanning_inbox = not (inbox_file or concept_file)

    def kickoff_for(*, limit: int, continue_branch: bool) -> str:
        return build_kickoff(
            inbox_file=inbox_file,
            inbox_limit=limit,
            concept_file=concept_file,
            skip_publish=skip_publish,
            branch=branch,
            stages=roster.stages,
            pipeline=roster.pipeline,
            one_group=scanning_inbox,
            continue_branch=continue_branch,
        )

    kickoff = kickoff_for(limit=inbox_limit, continue_branch=False)
    print(f"workspace {workspace}")
    print(f"target    {run.contracts.slug}")
    print(f"model     {model}")
    print(f"pipeline  {roster.pipeline}: {', '.join(roster.stages)}")
    print(f"roster    {', '.join(roster.spawnable)}")
    print(f"contracts {', '.join(sorted(run.contracts.declared)) or 'none'}")
    print(f"plan      {prepared.plan.relative_to(workspace)}\n")

    def inbox_size() -> int | None:
        if not scanning_inbox:
            return None
        return len(list((workspace / INBOX_DIR).glob("*.md")))

    # A named document or concept is one session. An inbox scan is one session per group: a
    # single context cannot hold a whole inbox, so each session plans the remaining inbox and
    # takes the first group; documents leaving the inbox are what advances the loop.
    consumed_total = 0
    session = 0
    planner_retries = 0
    while True:
        session += 1
        before = inbox_size()
        if session > 1:
            remaining = inbox_limit - consumed_total if inbox_limit else 0
            kickoff = kickoff_for(limit=remaining, continue_branch=not skip_publish)
            print(f"\n=== session {session}: next group ({before} inbox documents left) ===\n")

        monitor = StreamMonitor(required_agents=prepared.agents)
        code = launch_claude(
            build_claude_argv(model=model, agent=CONDUCTOR),
            env=env,
            cwd=workspace,
            prompt=kickoff,
            monitor=monitor,
        )
        try:
            written = monitor.write_transcripts(workspace)
            print(f"transcripts {len(written)} file(s)")
        except OSError as err:
            print(f"[warn] transcripts not written: {err}", file=sys.stderr)

        if code != 0:
            print("FAIL  conductor session", file=sys.stderr)
            return code or 1
        if scanning_inbox and (before or 0) > 0 and planner_gave_up(monitor, profile.planner):
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
        if not scanning_inbox:
            break
        after = inbox_size() or 0
        consumed_total += (before or 0) - after
        if planned_groups(monitor, profile.planner) == 0 or after == 0:
            break
        if (before or 0) - after <= 0:
            print("[loop] this session took no inbox documents; stopping", file=sys.stderr)
            break
        if inbox_limit and consumed_total >= inbox_limit:
            break
        if group_limit and session >= group_limit:
            break
    print(f"PASS  conductor finished{f' ({session} sessions)' if session > 1 else ''}")
    return 0
