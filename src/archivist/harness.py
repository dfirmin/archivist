"""Which agent harness runs a session: Claude Code (the default) or Pi (ADR 0008).

The runner (``claude_runner``) owns the run: contracts, the plan, the session loop, the
dispatch check, the fence. A harness owns only how one session is started and read:

- ``install`` — put the engine's agents and skills where the harness finds them;
- ``session_env`` — the process environment, from the resolved auth;
- ``argv`` — the headless command (the kickoff goes in on stdin);
- ``monitor`` — a parser of that command's stdout with ``StreamMonitor``'s surface;
- ``smoke_argv`` — one prompt, text out, no agents.

``ARCHIVIST_HARNESS`` chooses (``claude-code`` or ``pi``). It is read from the environment, not
a flag, so it survives the hand-off to a target's pinned engine.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, Sequence

from archivist.agents import write_agent_definitions
from archivist.config import AuthConfig, ConfigError
from archivist.engine import Engine
from archivist.skills import install_skills, reset_path
from archivist.stream import StreamMonitor

HARNESS_ENV = "ARCHIVIST_HARNESS"
CLAUDE_CODE = "claude-code"
PI = "pi"
HARNESSES = (CLAUDE_CODE, PI)

SKILLS_DIR_REL = Path(".claude") / "skills"
AGENTS_DIR_REL = Path(".claude") / "agents"


class Harness(Protocol):
    name: str

    def install(self, workspace: Path, engine: Engine, *, spawnable: tuple[str, ...]) -> tuple[str, ...]: ...

    def session_env(self, env: dict[str, str], auth: AuthConfig, workspace: Path) -> dict[str, str]: ...

    def argv(
        self,
        *,
        model: str | None,
        workspace: Path,
        agent: str | None = None,
        system_prompt: str | None = None,
    ) -> list[str]: ...

    def monitor(self, *, required_agents: Sequence[str], workspace: Path) -> StreamMonitor: ...

    def smoke_argv(self, prompt: str, *, model: str | None, workspace: Path) -> list[str]: ...


def harness_name(environ: dict[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    name = (env.get(HARNESS_ENV) or CLAUDE_CODE).strip()
    if name not in HARNESSES:
        raise ConfigError(f"invalid {HARNESS_ENV}: {name!r} (expected one of: {', '.join(HARNESSES)})")
    return name


def get_harness(environ: dict[str, str] | None = None) -> Harness:
    name = harness_name(environ)
    if name == PI:
        from archivist.pi_harness import PiHarness

        return PiHarness()
    return ClaudeCodeHarness()


def install_claude_definitions(workspace: Path, engine: Engine, *, spawnable: tuple[str, ...]) -> tuple[str, ...]:
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


class ClaudeCodeHarness:
    """``claude -p --agent <name> --output-format stream-json`` — the engine's original harness."""

    name = CLAUDE_CODE

    def install(self, workspace: Path, engine: Engine, *, spawnable: tuple[str, ...]) -> tuple[str, ...]:
        return install_claude_definitions(workspace, engine, spawnable=spawnable)

    def session_env(self, env: dict[str, str], auth: AuthConfig, workspace: Path) -> dict[str, str]:
        return env

    def argv(
        self,
        *,
        model: str | None,
        workspace: Path,
        agent: str | None = None,
        system_prompt: str | None = None,
    ) -> list[str]:
        """``agent`` runs the session *as* that agent (its prompt, tools and roster); the smoke
        check has no agent file for its supervisor and passes ``system_prompt`` instead."""
        if (agent is None) == (system_prompt is None):
            raise ValueError("pass exactly one of agent or system_prompt")
        argv = [
            "claude",
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            *(["--model", model] if model else []),
            "--permission-mode",
            "bypassPermissions",
        ]
        if agent is not None:
            return [*argv, "--agent", agent]
        assert system_prompt is not None
        return [*argv, "--append-system-prompt", system_prompt]

    def monitor(self, *, required_agents: Sequence[str], workspace: Path) -> StreamMonitor:
        return StreamMonitor(required_agents=tuple(required_agents))

    def smoke_argv(self, prompt: str, *, model: str | None, workspace: Path) -> list[str]:
        return ["claude", "-p", prompt, *(["--model", model] if model else []), "--output-format", "text"]
