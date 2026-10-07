"""The Pi harness (ADR 0008): ``pi --mode json -p`` sessions with an engine extension for sub-agents.

Pi has no sub-agents and loads skills on demand only. Everything Claude Code does for the engine
with agent files is resolved here, once, at install time, into a private Pi agent dir
(``<workspace>/.claude/pi/``, which ``PI_CODING_AGENT_DIR`` points every pi process at):

- ``agents/<name>.json`` — the agent's model, its tool list in Pi's names, and its prompt file;
- ``agents/<name>.prompt.md`` — the agent body with each preloaded skill (``skills:``) appended,
  which is what Claude Code's preload gives an agent;
- ``skills/`` — every engine skill, which Pi lists in the prompt for on-demand loading;
- ``extensions/archivist.ts`` — the ``Agent``, ``Skill`` and ``TodoWrite`` tools;
- ``models.json`` — the provider for the run's auth mode (a gateway, or a key helper).

The extension reads the JSON and spawns; it makes no decision Python could make.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from archivist.agents import Agent, SPAWN_TOOL
from archivist.config import (
    ANTHROPIC_API_AUTH,
    GATEWAY_KEY_AUTH,
    INHERIT_AUTH,
    LOCAL_CLAUDE_AUTH,
    AuthConfig,
    ConfigError,
)
from archivist.engine import Engine
from archivist.errors import DefinitionError
from archivist.harness import PI, install_claude_definitions
from archivist.pi_stream import PiStreamMonitor
from archivist.skills import Skill, reset_path, repo_root
from archivist.stream import StreamMonitor

PI_DIR_REL = Path(".claude") / "pi"
EXTENSION_SRC = Path("harness") / "pi" / "archivist.ts"
PI_BIN_ENV = "ARCHIVIST_PI_BIN"
GATEWAY_PROVIDER = "archivist-gateway"
BUILTIN_PROVIDER = "anthropic"
# Pi has no "harness default" model to fall back on as Claude Code does. An agent without a pin
# (the smoke agent) and a run without ACT_CLAUDE_MODEL get the engine's main model.
DEFAULT_MODEL = "claude-sonnet-5-5"

# Claude Code tool names (as agents list them) → Pi's. `Glob` is Pi's `find`; `Agent`, `Skill`
# and `TodoWrite` come from the engine extension.
TOOL_MAP = {
    "Read": ("read",),
    "Write": ("write",),
    "Edit": ("edit",),
    "Bash": ("bash",),
    "Grep": ("grep",),
    "Glob": ("find", "ls"),
    "Skill": ("Skill",),
    "TodoWrite": ("TodoWrite",),
    SPAWN_TOOL: (SPAWN_TOOL,),
}
# An agent without `tools:` gets every tool in Claude Code except spawning (sub-agents cannot
# spawn); the same here.
ALL_TOOLS = ("read", "write", "edit", "bash", "grep", "find", "ls", "Skill")

# Gateway models need metadata Pi cannot discover. Pi uses it for compaction and output limits.
_FAMILY_LIMITS = (("haiku", 200_000, 64_000), ("sonnet", 1_000_000, 128_000),
                  ("opus", 1_000_000, 128_000), ("fable", 1_000_000, 128_000))
_DEFAULT_LIMITS = (200_000, 64_000)


def pi_dir(workspace: Path) -> Path:
    return workspace / PI_DIR_REL


def pi_tools(tools: Sequence[str]) -> tuple[str, ...]:
    """Map an agent's Claude Code tool list to Pi's; an empty list means every tool."""
    if not tools:
        return ALL_TOOLS
    out: list[str] = []
    for tool in tools:
        bare = tool.split("(", 1)[0].strip()
        mapped = TOOL_MAP.get(bare)
        if mapped is None:
            raise DefinitionError(f"tool {tool!r} has no Pi equivalent (known: {', '.join(TOOL_MAP)})")
        out.extend(t for t in mapped if t not in out)
    return tuple(out)


def agent_prompt(agent: Agent, skills: dict[str, Skill]) -> str:
    """The agent's system prompt on Pi: its body, then each preloaded skill in full."""
    parts = [agent.body.strip()]
    if agent.skills:
        parts.append(
            "# Preloaded skills\n\nThese skills are loaded for you; follow them as written. "
            "Do not load them again."
        )
        for name in agent.skills:
            skill = skills[name]
            parts.append(f'<skill name="{name}">\n{skill.body.strip()}\n</skill>')
    return "\n\n".join(parts) + "\n"


def model_limits(model: str) -> tuple[int, int]:
    lowered = model.lower()
    for family, context, output in _FAMILY_LIMITS:
        if family in lowered:
            return context, output
    return _DEFAULT_LIMITS


def _key_helper(env: dict[str, str]) -> str:
    """The apiKeyHelper Claude Code would use in local-claude mode."""
    for name in ("CLAUDE_REAL_API_KEY_HELPER", "CLAUDE_LOCAL_API_KEY_HELPER"):
        if env.get(name):
            return env[name]
    home = Path(env.get("HOME") or Path.home())
    settings = home / ".claude" / "settings.json"
    if settings.is_file():
        try:
            helper = json.loads(settings.read_text(encoding="utf-8")).get("apiKeyHelper")
        except (OSError, ValueError):
            helper = None
        if isinstance(helper, str) and helper.strip():
            return helper.strip()
    default = home / ".claude-code-auth" / "bin" / "api_key_helper.sh"
    if os.access(default, os.X_OK):
        return str(default)
    raise ConfigError("local-claude on Pi needs the apiKeyHelper (CLAUDE_LOCAL_API_KEY_HELPER or settings.json)")


@dataclass(frozen=True)
class PiProvider:
    name: str
    models_json: dict | None  # None: Pi's built-in provider, nothing to write
    env: dict[str, str]


def provider_for(auth: AuthConfig, env: dict[str, str], models: Sequence[str]) -> PiProvider:
    """Map the four auth modes onto a Pi provider (ADR 0008 §5)."""
    if auth.mode in (ANTHROPIC_API_AUTH, INHERIT_AUTH):
        extra: dict[str, str] = {}
        if (
            auth.mode == INHERIT_AUTH
            and not env.get("ANTHROPIC_API_KEY")
            and not env.get("ANTHROPIC_OAUTH_TOKEN")
            and env.get("CLAUDE_CODE_OAUTH_TOKEN")
        ):
            extra["ANTHROPIC_OAUTH_TOKEN"] = env["CLAUDE_CODE_OAUTH_TOKEN"]
        return PiProvider(BUILTIN_PROVIDER, None, extra)

    if auth.mode == GATEWAY_KEY_AUTH:
        base_url = auth.endpoint
        api_key = "$ANTHROPIC_API_KEY"
    elif auth.mode == LOCAL_CLAUDE_AUTH:
        base_url = env.get("ANTHROPIC_BASE_URL") or env.get("LITELLM_API_BASE") or ""
        if not base_url:
            raise ConfigError("local-claude on Pi needs ANTHROPIC_BASE_URL or LITELLM_API_BASE")
        api_key = f"!{_key_helper(env)}"
    else:  # pragma: no cover - resolve_auth refuses anything else
        raise ConfigError(f"auth mode {auth.mode!r} has no Pi provider")

    provider: dict = {
        "baseUrl": base_url.rstrip("/"),
        "api": "anthropic-messages",
        "apiKey": api_key,
        "models": [],
    }
    if env.get("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS", "") not in ("", "0"):
        # What CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS does for Claude Code: no anthropic-beta.
        provider["headers"] = {"anthropic-beta": ""}  # an empty list: Pi sends no beta features
    for model in dict.fromkeys(m for m in models if m):
        context, output = model_limits(model)
        provider["models"].append(
            {"id": model, "name": model, "reasoning": True, "input": ["text", "image"],
             "contextWindow": context, "maxTokens": output}
        )
    return PiProvider(GATEWAY_PROVIDER, {"providers": {GATEWAY_PROVIDER: provider}}, {})


class PiHarness:
    name = PI

    def __init__(self) -> None:
        self._roster: tuple[str, ...] = ()
        self._models: tuple[str, ...] = ()
        self._provider: str = BUILTIN_PROVIDER
        self._default_model: str = DEFAULT_MODEL

    # -------------------------------------------------------------------- install

    def install(self, workspace: Path, engine: Engine, *, spawnable: tuple[str, ...]) -> tuple[str, ...]:
        # The Claude Code files too: the runner reads the conductor's model from .claude/agents/,
        # and one layout keeps a workspace inspectable whichever harness ran it.
        written = install_claude_definitions(workspace, engine, spawnable=spawnable)
        root = pi_dir(workspace)
        reset_path(root)
        (root / "agents").mkdir(parents=True)
        (root / "extensions").mkdir()
        (root / "events").mkdir()
        shutil.copytree(workspace / ".claude" / "skills", root / "skills")
        extension = repo_root() / EXTENSION_SRC
        if not extension.is_file():
            raise DefinitionError(f"missing Pi extension: {extension}")
        shutil.copy2(extension, root / "extensions" / extension.name)
        (root / "settings.json").write_text(json.dumps({"quietStartup": True}, indent=2) + "\n", encoding="utf-8")

        models: list[str] = []
        for name in written:
            agent = engine.agents[name]
            prompt_file = root / "agents" / f"{name}.prompt.md"
            prompt_file.write_text(agent_prompt(agent, engine.skills), encoding="utf-8")
            spec = {
                "name": name,
                "model": agent.model,
                "tools": list(pi_tools(agent.tools)),
                "prompt_file": str(prompt_file),
            }
            (root / "agents" / f"{name}.json").write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
            if agent.model:
                models.append(agent.model)
        self._roster = spawnable
        self._models = tuple(models)
        return written

    # ----------------------------------------------------------------------- env

    def session_env(self, env: dict[str, str], auth: AuthConfig, workspace: Path) -> dict[str, str]:
        root = pi_dir(workspace)
        if not root.is_dir():
            raise ConfigError(f"Pi agent dir missing: {root} (install the engine first)")
        provider = provider_for(auth, env, (*self._models, auth.model or DEFAULT_MODEL))
        models_file = root / "models.json"
        if provider.models_json is not None:
            models_file.write_text(json.dumps(provider.models_json, indent=2) + "\n", encoding="utf-8")
        elif models_file.exists():
            models_file.unlink()
        if auth.mode == INHERIT_AUTH:
            operator_auth = Path(env.get("HOME") or Path.home()) / ".pi" / "agent" / "auth.json"
            if operator_auth.is_file():
                shutil.copy2(operator_auth, root / "auth.json")
        self._provider = provider.name
        self._default_model = auth.model or DEFAULT_MODEL
        out = dict(env)
        out.update(provider.env)
        out.update(
            {
                "PI_CODING_AGENT_DIR": str(root),
                "PI_TELEMETRY": "0",
                "PI_SKIP_VERSION_CHECK": "1",
                "ARCHIVIST_PI_ROSTER": ",".join(self._roster),
                "ARCHIVIST_PI_PROVIDER": provider.name,
                "ARCHIVIST_PI_DEFAULT_MODEL": self._default_model,
                "ARCHIVIST_PI_EVENTS_DIR": str(root / "events"),
            }
        )
        return out

    # ---------------------------------------------------------------------- argv

    def _base(self, model: str | None) -> list[str]:
        binary = os.environ.get(PI_BIN_ENV) or "pi"
        argv = [binary, "--mode", "json", "-p", "--no-session", "-nc", "--provider", self._provider]
        return [*argv, "--model", model or self._default_model]

    def argv(
        self,
        *,
        model: str | None,
        workspace: Path,
        agent: str | None = None,
        system_prompt: str | None = None,
    ) -> list[str]:
        if (agent is None) == (system_prompt is None):
            raise ValueError("pass exactly one of agent or system_prompt")
        root = pi_dir(workspace)
        if agent is not None:
            spec = json.loads((root / "agents" / f"{agent}.json").read_text(encoding="utf-8"))
            return [
                *self._base(model or spec.get("model")),
                "--tools", ",".join(spec["tools"]),
                "--append-system-prompt", spec["prompt_file"],
            ]
        assert system_prompt is not None
        prompt_file = root / "supervisor.prompt.md"
        prompt_file.write_text(system_prompt + "\n", encoding="utf-8")
        return [*self._base(model), "--tools", SPAWN_TOOL, "--append-system-prompt", str(prompt_file)]

    def monitor(self, *, required_agents: Sequence[str], workspace: Path) -> StreamMonitor:
        return PiStreamMonitor(required_agents=tuple(required_agents), events_dir=pi_dir(workspace) / "events")

    def smoke_argv(self, prompt: str, *, model: str | None, workspace: Path) -> list[str]:
        binary = os.environ.get(PI_BIN_ENV) or "pi"
        return [binary, "-p", "--no-session", "-nc", "--no-tools", "--provider", self._provider,
                "--model", model or self._default_model, prompt]
