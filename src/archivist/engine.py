"""Load the engine (agents, skills, profile) and resolve one run against a target's contracts.

Every entry point goes through ``resolve_run``: ``validate``, ``load-target``,
``prepare-workspace`` and ``run-conductor`` apply the same guardrails in the same order.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from archivist.agents import Agent, load_agents
from archivist.contracts import (
    TargetContracts,
    check_requirements,
    load_contracts,
    reject_target_agents,
)
from archivist.errors import ContractError
from archivist.profile import (
    Profile,
    Roster,
    load_profile,
    merged_pipelines,
    required_contracts,
    resolve_roster,
)
from archivist.skills import Skill, load_skills, repo_root


@dataclass(frozen=True, slots=True)
class Engine:
    agents: dict[str, Agent]
    skills: dict[str, Skill]
    profile: Profile


@dataclass(frozen=True, slots=True)
class ResolvedRun:
    engine: Engine
    contracts: TargetContracts
    pipelines: dict[str, tuple[str, ...]]
    roster: Roster
    required: dict[str, list[str]]


def load_engine(root: Path | None = None) -> Engine:
    root = root or repo_root()
    agents = load_agents(root / "agents")
    skills = load_skills(root / "skills")
    profile = load_profile(root / "agents", agent_names=set(agents), skill_names=set(skills))
    return Engine(agents, skills, profile)


def resolve_run(
    workspace: Path,
    *,
    engine: Engine | None = None,
    pipeline: str | None = None,
    authoring: bool | None = None,
    expected_slug: str | None = None,
) -> ResolvedRun:
    """Validate the target for this pipeline and return what the run may spawn."""
    engine = engine or load_engine()
    workspace = workspace.resolve()
    reject_target_agents(workspace)
    contracts = load_contracts(workspace, enrichment_methods=engine.profile.enrichment_methods)
    if expected_slug is not None and contracts.slug != expected_slug:
        raise ContractError(
            f"contracts/target.yaml slug {contracts.slug!r} does not match target {expected_slug!r}"
        )
    pipelines = merged_pipelines(engine.profile, contracts.pipelines)
    roster = resolve_roster(
        engine.profile, pipelines, pipeline, authoring=authoring, default=contracts.default_pipeline
    )
    required = required_contracts(engine.profile, roster)
    check_requirements(contracts, required)
    return ResolvedRun(engine, contracts, pipelines, roster, required)
