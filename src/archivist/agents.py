"""Engine agents: ``agents/<name>.md``.

An agent file is the Claude Code sub-agent format, authored directly:

- ``name`` — equals the file name (``agents/verifier.md`` is ``verifier``);
- ``description`` — what the conductor matches on;
- ``model`` — a literal model id or alias, omitted to inherit;
- ``tools`` — tool allow-list, omitted for all tools;
- ``skills`` — engine skills preloaded into the agent.

The body is the system prompt. Any other key (``hooks``, ``mcpServers``,
``permissionMode`` …) is refused: agents are prompts, not code. Agents exist only in the
engine; targets choose and order them through pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from archivist.errors import DefinitionError
from archivist.frontmatter import check_identity, split_frontmatter, split_list
from archivist.skills import repo_root

AGENT_KEYS = frozenset({"name", "description", "model", "tools", "skills"})
SPAWN_TOOL = "Agent"


@dataclass(frozen=True, slots=True)
class Agent:
    name: str
    path: Path
    description: str
    body: str
    model: str | None
    tools: tuple[str, ...]
    skills: tuple[str, ...]


def engine_agents_root() -> Path:
    return repo_root() / "agents"


def parse_agent(path: Path) -> Agent:
    """Parse ``agents/<name>.md``; the file stem must equal ``name:``."""
    if not path.is_file():
        raise DefinitionError(f"missing agent file: {path}")
    try:
        frontmatter, body = split_frontmatter(path.read_text(encoding="utf-8"))
    except DefinitionError as exc:
        raise DefinitionError(f"{path}: {exc}") from exc
    unsupported = sorted(set(frontmatter) - AGENT_KEYS)
    if unsupported:
        raise DefinitionError(
            f"{path}: unsupported frontmatter {', '.join(unsupported)} "
            f"(agents may set {', '.join(sorted(AGENT_KEYS))})"
        )
    name, description = check_identity(frontmatter, expected_name=path.stem, label=str(path))
    model = frontmatter.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise DefinitionError(f"{path}: model must be a non-empty string")
    if isinstance(model, str) and model.strip().startswith("${"):
        raise DefinitionError(f"{path}: model must be a literal id, not {model.strip()!r}")
    if not body.strip():
        raise DefinitionError(f"{path}: the body is the agent's prompt and may not be empty")
    return Agent(
        name=name,
        path=path,
        description=description,
        body=body.strip(),
        model=model.strip() if isinstance(model, str) else None,
        tools=split_list(frontmatter.get("tools")),
        skills=split_list(frontmatter.get("skills")),
    )


def load_agents(root: Path | None = None) -> dict[str, Agent]:
    root = root or engine_agents_root()
    return {path.stem: parse_agent(path) for path in sorted(root.glob("*.md"))}


def render_agent(agent: Agent, *, tools: tuple[str, ...] | None = None) -> str:
    """Claude Code sub-agent markdown for one agent."""
    frontmatter: dict[str, object] = {"name": agent.name, "description": agent.description}
    effective_tools = agent.tools if tools is None else tools
    if effective_tools:
        frontmatter["tools"] = ", ".join(effective_tools)
    if agent.model:
        frontmatter["model"] = agent.model
    if agent.skills:
        frontmatter["skills"] = list(agent.skills)
    header = yaml.safe_dump(
        frontmatter, sort_keys=False, allow_unicode=True, default_flow_style=False, width=10_000
    )
    return f"---\n{header}---\n\n{agent.body}\n"


def with_roster(tools: tuple[str, ...], spawnable: tuple[str, ...], *, label: str) -> tuple[str, ...]:
    """Replace the coordinator's bare ``Agent`` tool with ``Agent(<roster>)``."""
    out: list[str] = []
    found = False
    for tool in tools:
        if tool == SPAWN_TOOL:
            out.append(f"{SPAWN_TOOL}({', '.join(spawnable)})")
            found = True
        elif tool.startswith(f"{SPAWN_TOOL}(") or tool.startswith("Task("):
            raise DefinitionError(f"{label}: list the bare `Agent` tool; the roster comes from profile.yaml")
        else:
            out.append(tool)
    if not found:
        raise DefinitionError(f"{label}: the coordinator needs the `Agent` tool to spawn sub-agents")
    return tuple(out)


def write_agent_definitions(
    agents: dict[str, Agent],
    dest: Path,
    *,
    coordinator: str,
    spawnable: tuple[str, ...],
    available_skills: set[str],
) -> list[Path]:
    """Write ``dest/<name>.md`` for every agent; the coordinator gets its roster."""
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in sorted(agents):
        agent = agents[name]
        missing = [skill for skill in agent.skills if skill not in available_skills]
        if missing:
            raise DefinitionError(f"agent {name!r} lists skills that do not exist: {', '.join(missing)}")
        tools = with_roster(agent.tools, spawnable, label=f"agent {name!r}") if name == coordinator else None
        path = dest / f"{name}.md"
        path.write_text(render_agent(agent, tools=tools), encoding="utf-8")
        written.append(path)
    return written
