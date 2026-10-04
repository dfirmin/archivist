"""The engine profile (``agents/profile.yaml``) and the roster of one run.

The profile names the coordinator, the planner, every stage agent with the contracts it
``requires`` and the ``dispatch`` rules the conductor follows, the engine pipelines, and the
enrichment methods structures may name. A target adds or replaces *pipelines* (ordered
lists of engine stage agents) in ``contracts/target.yaml``; it cannot add agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from archivist.agents import engine_agents_root
from archivist.contracts import BUILTIN_KINDS, REFERENCE
from archivist.errors import ContractError, DefinitionError

PROFILE_FILE = "profile.yaml"
PROFILE_KEYS = frozenset(
    {"version", "coordinator", "planner", "default_pipeline", "agents", "pipelines", "enrichment_methods"}
)
AGENT_SPEC_KEYS = frozenset({"produces", "requires", "optional", "dispatch"})
DISPATCH_KEYS = frozenset(
    {"per", "parallel", "before", "description", "prompt", "done_when", "on_empty", "on_failure"}
)
DISPATCH_PER = frozenset({"group", "concept", "gap-kind"})
CONTRACT_KINDS = frozenset({*BUILTIN_KINDS, REFERENCE})


@dataclass(frozen=True, slots=True)
class AgentSpec:
    name: str
    produces: bool = False
    requires: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    dispatch: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class Profile:
    coordinator: str
    planner: str
    default_pipeline: str
    agents: dict[str, AgentSpec]
    pipelines: dict[str, tuple[str, ...]]
    enrichment_methods: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def stage_agents(self) -> frozenset[str]:
        return frozenset(name for name, spec in self.agents.items() if spec.dispatch)


@dataclass(frozen=True, slots=True)
class Roster:
    """Who one run may spawn: the pipeline's stages plus the planner when it authors."""

    pipeline: str
    stages: tuple[str, ...]
    support: tuple[str, ...]
    authoring: bool

    @property
    def spawnable(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.support, *self.stages)))


def _names(value: Any, *, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise DefinitionError(f"{label} must be a list of names")
    names = tuple(v.strip() for v in value)
    if len(set(names)) != len(names):
        raise DefinitionError(f"{label} lists a name twice")
    return names


def load_profile(root: Path | None = None, *, agent_names: set[str], skill_names: set[str]) -> Profile:
    """Read and validate the engine profile against the engine's agents and skills."""
    path = (root or engine_agents_root()) / PROFILE_FILE
    if not path.is_file():
        raise DefinitionError(f"engine profile not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DefinitionError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise DefinitionError(f"{path}: profile must be a mapping")
    unknown = sorted(set(raw) - PROFILE_KEYS)
    if unknown:
        raise DefinitionError(f"{path}: unsupported key(s): {', '.join(unknown)}")

    coordinator, planner = raw.get("coordinator"), raw.get("planner")
    for role, name in (("coordinator", coordinator), ("planner", planner)):
        if not isinstance(name, str) or name not in agent_names:
            raise DefinitionError(f"{path}: {role} {name!r} is not an agent")

    agents: dict[str, AgentSpec] = {}
    for name, spec in (raw.get("agents") or {}).items():
        label = f"{path}: agents.{name}"
        if name not in agent_names:
            raise DefinitionError(f"{label}: no agents/{name}.md")
        if name == coordinator:
            raise DefinitionError(f"{label}: the coordinator takes no spec")
        spec = spec or {}
        extra = sorted(set(spec) - AGENT_SPEC_KEYS)
        if extra:
            raise DefinitionError(f"{label}: unsupported key(s): {', '.join(extra)}")
        requires = _names(spec.get("requires"), label=f"{label}.requires")
        optional = _names(spec.get("optional"), label=f"{label}.optional")
        for kind in (*requires, *optional):
            if kind not in CONTRACT_KINDS:
                raise DefinitionError(f"{label}: {kind!r} is not a contract kind")
        dispatch = spec.get("dispatch")
        if dispatch is not None:
            extra = sorted(set(dispatch) - DISPATCH_KEYS)
            if extra:
                raise DefinitionError(f"{label}.dispatch: unsupported key(s): {', '.join(extra)}")
            for key in ("per", "description", "prompt", "done_when", "on_failure"):
                if not dispatch.get(key):
                    raise DefinitionError(f"{label}.dispatch: {key} is required")
            if dispatch["per"] not in DISPATCH_PER:
                raise DefinitionError(f"{label}.dispatch.per must be one of {sorted(DISPATCH_PER)}")
        agents[name] = AgentSpec(name, bool(spec.get("produces")), requires, optional, dispatch)
    if planner not in agents:
        agents[planner] = AgentSpec(planner)
    if agents[planner].dispatch:
        raise DefinitionError(f"{path}: the planner is support, not a stage; it takes no dispatch")

    stage_agents = {n for n, s in agents.items() if s.dispatch}
    pipelines = {
        str(name): check_pipeline(str(name), stages, stage_agents, label=f"{path}: pipelines")
        for name, stages in (raw.get("pipelines") or {}).items()
    }
    default = raw.get("default_pipeline")
    if default not in pipelines:
        raise DefinitionError(f"{path}: default_pipeline {default!r} is not a pipeline")

    methods: dict[str, dict[str, Any]] = {}
    for name, spec in (raw.get("enrichment_methods") or {}).items():
        skills = _names((spec or {}).get("skills"), label=f"{path}: enrichment_methods.{name}.skills")
        missing = [s for s in skills if s not in skill_names]
        if missing:
            raise DefinitionError(f"{path}: enrichment method {name!r} names missing skill(s): {', '.join(missing)}")
        methods[str(name)] = {"description": (spec or {}).get("description", ""), "skills": list(skills)}

    return Profile(coordinator, planner, default, agents, pipelines, methods)


def check_pipeline(name: str, stages: Any, stage_agents: set[str] | frozenset[str], *, label: str) -> tuple[str, ...]:
    names = _names(stages, label=f"{label}.{name}")
    if not names:
        raise DefinitionError(f"{label}.{name} is empty")
    for stage in names:
        if stage not in stage_agents:
            known = ", ".join(sorted(stage_agents))
            raise DefinitionError(f"{label}.{name}: {stage!r} is not an engine stage agent ({known})")
    return names


def merged_pipelines(profile: Profile, target_pipelines: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    """Engine pipelines with the target's on top (same name replaces). Stages must be engine agents."""
    merged = dict(profile.pipelines)
    for name, stages in target_pipelines.items():
        try:
            merged[name] = check_pipeline(name, list(stages), profile.stage_agents, label="contracts/target.yaml: pipelines")
        except DefinitionError as exc:
            raise ContractError(str(exc)) from exc
    return merged


def resolve_roster(
    profile: Profile,
    pipelines: Mapping[str, tuple[str, ...]],
    name: str | None,
    *,
    authoring: bool | None,
    default: str | None = None,
) -> Roster:
    """Pick the run's pipeline. Without authoring (an existing concept) producing stages drop out.

    ``authoring=None`` means "whatever the pipeline does" (validation without a run).
    """
    chosen = (name or default or profile.default_pipeline).strip()
    if chosen not in pipelines:
        raise ContractError(f"unknown pipeline {chosen!r} (defined: {', '.join(sorted(pipelines))})")
    stages = pipelines[chosen]
    producers = [s for s in stages if profile.agents[s].produces]
    if authoring is None:
        authoring = bool(producers)
    if authoring and not producers:
        raise ContractError(
            f"pipeline {chosen!r} authors nothing; name an existing concept (--concept) or "
            "choose a pipeline with a producing stage"
        )
    if not authoring:
        stages = tuple(s for s in stages if not profile.agents[s].produces)
        if not stages:
            raise ContractError(f"pipeline {chosen!r} has no stage left once authoring is skipped")
    support = (profile.planner,) if authoring else ()
    return Roster(chosen, stages, support, authoring)


def required_contracts(profile: Profile, roster: Roster) -> dict[str, list[str]]:
    """Contract kind -> the roster agents that require it."""
    out: dict[str, list[str]] = {}
    for agent in roster.spawnable:
        for kind in profile.agents[agent].requires:
            out.setdefault(kind, []).append(agent)
    return out


def entry_stage(profile: Profile, roster: Roster) -> str:
    """The stage that must dispatch for a run to have done anything."""
    if roster.authoring:
        return next(s for s in roster.stages if profile.agents[s].produces)
    return roster.stages[0]
